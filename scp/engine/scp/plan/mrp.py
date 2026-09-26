"""Network MRP/DRP heuristic (S/4 guide §8, figure 8.1, applied across a multi-echelon network).

For every planning node (location, product), in ascending low-level code:

  ① collect requirements — independent (after forecast consumption) + dependent/transfer
     requirements created by already-planned consumers
  ② net: walk dates forward, ``avail += receipts − requirements``; a shortage exists when
     ``avail < threshold`` (safety stock, or reorder point for reorder-point nodes)
  ③ lot-size the shortage, ④ pick a source (quota rating / priority), ⑤ schedule backward from
     the need date (forward from today when the start falls in the past; to the fence end inside
     the planning time fence), ⑥ explode: component and origin requirements, resource load

Then: FIFO pegging per node, upstream-delay propagation (projected availability), the physical
projection per bucket, capacity/supplier/lane checks, exceptions and KPIs.

Netting uses *need dates* (the plan's intent) so orders are never duplicated. The physical projection
uses each order's *available date* (the MD04 view of the plan); the fill-rate KPI, DEMAND_AT_RISK and the
per-bucket ``at_risk`` row use *projected dates*, which carry upstream delays down the pegging. They are
quantities by date, not one date per order: when an input is only partly late, the share of the order its
on-time inputs cover stays on time (as promising would split the shipment), and only the rest is delayed.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..model import (
    Dataset, LocationProduct, LocationType, LotSizePolicy, MrpType, SafetyStockMethod, Strategy,
)
from ..network import NetworkGraph, Node, SupplyOption, build_graph
from ..time import Buckets
from ..time.capacity import hours_between, overtime_between
from ..validate import has_errors, validate
from . import costing, rates
from .consumption import effective_demand
from .leadtime import (
    Schedule, gr_days, lead_time_std_days, location_calendar, nominal_lead_time_days, resource_calendar,
    schedule, supplier_lane,
)
from .lotsize import apply_modifiers, base_lot
from .structure import co_output, needs
from .result import (
    BucketOut, Kpis, NodeBucket, NodePlan, Peg, PlanException, PlannedOrder, PlanResult,
    Requirement, ResourceBucket, ResourcePlan, ScheduledReceiptOut,
)

EPS = 1e-9
_PREFIX = {"make": "MO", "buy": "PR", "transfer": "TO"}


@dataclass
class _Supply:
    kind: str       # on_hand | receipt | order
    id: str
    date: date      # netting date
    qty: float
    avail_date: date  # physical availability


@dataclass
class _NodeState:
    lp: LocationProduct
    reqs: list[Requirement] = field(default_factory=list)
    supplies: list[_Supply] = field(default_factory=list)
    ss_by_bucket: list[float] = field(default_factory=list)
    targets: list[tuple[date, float]] = field(default_factory=list)   # S&OP stock targets (date, qty), by date
    ss_note: str = ""
    lead_time: float | None = None


class _Planner:
    def __init__(self, ds: Dataset, g: NetworkGraph):
        self.ds = ds
        self.s = ds.settings
        self.g = g
        self.b = Buckets(ds.settings)
        self.start = ds.settings.planning_start
        self.val = costing.roll_up(ds, g)
        self.flow = rates.horizon_flows(ds, g)
        self.orders: list[PlannedOrder] = []
        self.order_by_id: dict[str, PlannedOrder] = {}
        self.order_inputs: dict[str, list[str]] = defaultdict(list)  # order → requirement ids it created
        self.req_by_id: dict[str, Requirement] = {}
        self.state: dict[Node, _NodeState] = {}
        self.pegs: list[Peg] = []
        self.exceptions: list[PlanException] = []
        self.counters: dict[str, int] = defaultdict(int)
        self.quota_alloc: dict[tuple[Node, str], float] = defaultdict(float)
        self.res_daily: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
        self.supplier_load: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(self.b))
        self.lane_load: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(self.b))
        self.kpi = Kpis()

    # ------------------------------------------------------------------ setup
    def lp(self, node: Node) -> LocationProduct:
        lp = self.ds.location_product_by_key.get(node)
        return lp or LocationProduct(location=node[0], product=node[1])

    def is_customer(self, node: Node) -> bool:
        return self.ds.location_type(node[0]) is LocationType.CUSTOMER

    def seed(self) -> None:
        for node in self.g.order:
            self.state[node] = _NodeState(lp=self.lp(node))
        for t in sorted(self.ds.stock_targets, key=lambda t: t.date):
            st = self.state.get((t.location, t.product))
            if st is not None and not self.is_customer((t.location, t.product)):
                st.targets.append((t.date, t.qty))
        by_node: dict[Node, list] = defaultdict(list)
        for i, d in enumerate(self.ds.demand):
            by_node[(d.location, d.product)].append((d.id or f"#{i}", d))
        for node, recs in by_node.items():
            st = self.state.get(node)
            if st is None:
                continue
            lp = st.lp
            period = {rid: rec.period_days for rid, rec in recs}
            for r in effective_demand(recs, lp.strategy, lp.consumption_backward_days, lp.consumption_forward_days):
                for i, (d, q) in enumerate(self._split(node, r.date, r.qty, period.get(r.source_ref)
                                                        if r.kind == "forecast" else None)):
                    if d >= self.b.end:
                        continue  # beyond horizon (validator warned)
                    rid = r.id if i == 0 else f"{r.id}~{i}"
                    req = Requirement(id=rid, location=node[0], product=node[1], date=max(d, self.start),
                                      qty=q, kind=r.kind, priority=r.priority,
                                      consumed_forecast=r.consumed if i == 0 else 0.0, past_due=d < self.start)
                    self._add_req(node, req)
        for rc in self.ds.receipts:
            node = (rc.location, rc.product)
            st = self.state.get(node)
            if st is None:
                continue
            d = self.receipt_date(rc)
            st.supplies.append(_Supply("receipt", rc.id, d, rc.qty, d))
            # what the firm order still draws from stock: components, or goods at a transfer's origin
            for rv in rc.reservations:
                rn = (rv.location, rv.product)
                if rn not in self.state or rv.qty <= EPS:
                    continue
                kind = "transfer" if rv.location != rc.location else "dependent"
                self._add_req(rn, Requirement(id=f"RV:{rc.id}:{rv.location}:{rv.product}", location=rv.location,
                                              product=rv.product, date=max(rv.date, self.start), qty=rv.qty,
                                              kind=kind, parent_order=rc.id, past_due=rv.date < self.start))

    def receipt_date(self, rc) -> date:
        """A firm receipt is available after goods-receipt processing, like a planned order."""
        gr = gr_days(self.ds.location_product_by_key.get((rc.location, rc.product)))
        return max(rc.due_date + timedelta(days=math.ceil(gr - 1e-9)), self.start)

    def _split(self, node: Node, d: date, qty: float, period_days: int | None) -> list[tuple[date, float]]:
        """PIR splitting: spread a period forecast evenly over the working days of its window."""
        if not period_days or period_days <= 1:
            return [(d, qty)]
        cal = location_calendar(self.ds, node[0])
        days = [d + timedelta(days=k) for k in range(period_days) if cal.is_workday(d + timedelta(days=k))]
        if not days:
            return [(d, qty)]
        return [(x, qty / len(days)) for x in days]

    def _add_req(self, node: Node, req: Requirement) -> None:
        self.state[node].reqs.append(req)
        self.req_by_id[req.id] = req

    # ------------------------------------------------------------------ safety stock
    def safety_stock(self, node: Node, st: _NodeState) -> None:
        lp = st.lp
        n = len(self.b)
        st.ss_by_bucket = [0.0] * n
        opts = self.g.options.get(node) or []
        st.lead_time = nominal_lead_time_days(self.ds, opts[0]) if opts else None
        pol = lp.safety_stock
        if self.is_customer(node) or lp.strategy is Strategy.MTO or pol.method is SafetyStockMethod.NONE:
            st.ss_note = "none" if pol.method is SafetyStockMethod.NONE else f"none ({lp.strategy.value})"
            return
        if pol.method is SafetyStockMethod.FIXED:
            st.ss_by_bucket = [pol.qty or 0.0] * n
            st.ss_note = f"fixed {pol.qty:g}"
            return
        if pol.method is SafetyStockMethod.DAYS_OF_SUPPLY:
            days = pol.days or 0.0
            for bk in self.b:
                hi = bk.start + timedelta(days=days)
                st.ss_by_bucket[bk.index] = sum(r.qty for r in st.reqs if bk.start <= r.date < hi)
            st.ss_note = f"coverage: requirements in the next {days:g} days"
            return
        opts_lt = lead_time_std_days(self.ds, opts[0]) if opts else 0.0
        # the shared network rate, as the inventory screen sizes it: a node only firm or one-off requirements draw
        # on has no forecast error to protect against, so no statistical buffer
        res = rates.policy_safety_stock(self.ds, self.g, node, mean_daily=self.flow.mean.get(node, 0.0),
                                        lead_time=st.lead_time or 0.0, lead_time_std=opts_lt,
                                        unit_value=self.val.unit_value.get(node, 0.0),
                                        days_per_bucket=rates.bucket_days(self.ds, len(self.b)))
        st.ss_by_bucket = [res.qty] * n
        st.ss_note = res.note

    def _rate(self, node: Node, st: _NodeState) -> float:
        """Mean daily demand for lot sizing: the network demand rate every module shares (:mod:`.rates`); a node
        that only firm orders draw on falls back to its own requirements, so its EOQ still has a volume."""
        r = self.flow.mean.get(node, 0.0)
        return r if r > EPS else sum(x.qty for x in st.reqs) / self.s.horizon_days

    # ------------------------------------------------------------------ netting
    def plan_node(self, node: Node) -> None:
        st = self.state[node]
        lp = st.lp
        self.safety_stock(node, st)
        mto = lp.strategy is Strategy.MTO
        onhand = 0.0 if self.is_customer(node) else lp.on_hand
        if onhand > 0:
            st.supplies.insert(0, _Supply("on_hand", f"OH:{node[0]}:{node[1]}", self.start, onhand, self.start))
        if lp.mrp_type is MrpType.NONE:
            self._peg(node, st)
            return
        reqs = sorted(st.reqs, key=lambda r: (r.date, r.priority, r.id))
        receipts = sorted((s for s in st.supplies if s.kind in ("receipt", "co_product")), key=lambda s: s.date)
        # the buffer is checked where requirements fall, buckets start and targets are set, never on a date where
        # only a receipt lands: a stock target ramps daily, so checking on receipt dates would size orders by
        # when firm supply happens to arrive (and firming a plan, then planning again, would change it)
        checks = ({r.date for r in reqs} | {bk.start for bk in self.b}
                  | {t for t, _ in st.targets if self.start <= t < self.b.end})
        dates = sorted(checks | {s.date for s in receipts})
        req_on: dict[date, float] = defaultdict(float)
        for r in reqs:
            req_on[r.date] += r.qty
        rec_on: dict[date, float] = defaultdict(float)
        for s in receipts:
            rec_on[s.date] += s.qty
        avail = 0.0 if mto else onhand
        eoq_qty = None
        if lp.lot_sizing.policy is LotSizePolicy.EOQ:
            eoq_qty = rates.eoq_qty(self.ds, self.g, node, self._rate(node, st), self.val.unit_value.get(node, 0.0))
            if eoq_qty is None:
                self._exc("EOQ_FALLBACK", "info", "EOQ undefined (no ordering cost, value or demand): lot-for-lot used",
                          node=node)
        for d in dates:
            avail += rec_on.get(d, 0.0) - req_on.get(d, 0.0)
            if d not in checks:
                continue
            bi = self.b.index_of(d)
            ss = 0.0 if mto else (st.ss_by_bucket[bi] if 0 <= bi < len(self.b) else 0.0)
            threshold = max(ss, 0.0 if mto else target_at(st.targets, d))
            if lp.mrp_type is MrpType.REORDER_POINT and lp.reorder_point is not None:
                threshold = max(threshold, lp.reorder_point)
            if avail >= threshold - EPS:
                continue
            # reschedule in (S/4 rescheduling check): a firm receipt that lands no later than a new order could
            # is expedited to cover the shortage instead of being duplicated by a new order. How soon a new order
            # could land depends on its size (production time grows with it), so it is asked for the lot that would
            # replace the firm supply: sized as if none lay ahead (a period lot the receipt already covers would
            # otherwise shrink to the shortage and look faster than the order it duplicates)
            lot = self._lot(lp, mto, threshold - avail, d, avail, req_on, {}, eoq_qty)[0]
            pulled = self._reschedule_in(node, st, receipts, rec_on, d, threshold - avail, lot)
            avail += pulled
            if avail >= threshold - EPS:
                continue
            shortage = threshold - avail
            qty, gap = self._lot(lp, mto, shortage, d, avail, req_on, rec_on, eoq_qty)
            need = max(self.start, d - timedelta(days=lp.safety_time_days)) if lp.safety_time_days else d
            ceiling = gap if lp.lot_sizing.policy is LotSizePolicy.MIN_MAX and not mto else None
            # what the order is for: requirements below zero first, then the buffer up to the threshold
            created = self._supply(node, st, qty, need, shortage=shortage, ceiling=ceiling,
                                   below_zero=min(shortage, max(0.0, -avail)))
            avail += created
        self._peg(node, st)

    def _lot(self, lp: LocationProduct, mto: bool, shortage: float, d: date, avail: float, req_on: dict[date, float],
             rec_on: dict[date, float], eoq_qty: float | None) -> tuple[float, float | None]:
        """The lot a shortage on ``d`` is ordered in, and the room left to the maximum stock."""
        ls = lp.lot_sizing
        window = 0.0
        if ls.policy is LotSizePolicy.POQ and not mto:
            bi = self.b.index_of(d)
            end_idx = min(bi + (ls.periods or 1), len(self.b))
            we = self.b[end_idx].start if end_idx < len(self.b) else self.b.end
            window = max(0.0, sum(q for dd, q in req_on.items() if d < dd < we)
                         - sum(q for dd, q in rec_on.items() if d < dd < we))
        gap = (lp.max_stock - avail) if lp.max_stock is not None else None
        if mto:
            return shortage, gap
        return base_lot(ls, shortage, window_requirements=window, max_stock_gap=gap, eoq_qty=eoq_qty), gap

    def _earliest_new(self, node: Node, st: _NodeState, need: date, qty: float) -> date | None:
        """When a new order for ``need`` would be available: on time if its backward-scheduled start is not in
        the past (nor inside the fence), else its forward-scheduled date from today (or the fence end)."""
        opt = self._choose(node, need, qty)
        if opt is None:
            return None
        fence_end = self.start + timedelta(days=st.lp.planning_time_fence_days)
        target = max(need, fence_end) if st.lp.planning_time_fence_days > 0 else need
        sch = schedule(self.ds, opt, qty, available=target)
        if sch.start_date >= self.start:
            return target
        return schedule(self.ds, opt, qty, start=self.start).available_date

    def _reschedule_in(self, node: Node, st: _NodeState, receipts: list[_Supply], rec_on: dict[date, float],
                       d: date, short: float, lot: float) -> float:
        """Pull later firm receipts forward to ``d`` (for netting) while a new order of ``lot`` could not arrive
        before them. Their physical date is kept, so the projection and the pegging still show the delay."""
        earliest = self._earliest_new(node, st, d, lot)
        if earliest is None or earliest <= d:
            return 0.0
        got = 0.0
        for s in receipts:
            if got >= short - EPS:
                break
            if s.kind != "receipt" or s.date <= d or s.date > earliest:
                continue   # only firm orders are expedited; a co-product comes when its run does
            rec_on[s.date] -= s.qty
            self._exc("RESCHEDULE_IN", "warning",
                      f"{s.id}: arrives {s.date.isoformat()} but is needed {d.isoformat()}; expedite it by "
                      f"{(s.date - d).days} d (a new order could not arrive before {earliest.isoformat()})",
                      node=node, order=s.id, when=d, qty=s.qty)
            s.date = d
            got += s.qty
        return got

    def _supply(self, node: Node, st: _NodeState, qty: float, need: date, *, shortage: float | None = None,
                ceiling: float | None = None, below_zero: float | None = None) -> float:
        opt = self._choose(node, need, qty)
        if opt is None:
            self._exc("NO_VALID_SOURCE", "error", f"No valid source on {need.isoformat()} for {qty:,.1f}",
                      node=node, when=need, qty=qty)
            return 0.0
        ls = st.lp.lot_sizing
        mins, rounds, maxes = [ls.min_qty], [ls.rounding_qty], [ls.max_qty]
        if opt.kind == "buy":
            pu = self.ds.purchasing_source_by_id[opt.source_id]
            mins.append(pu.moq)
            rounds.append(pu.rounding_qty)
        elif opt.kind == "make":
            ps = self.ds.production_source_by_id[opt.source_id]
            mins.append(ps.min_lot)
            maxes.append(ps.max_lot)
        if st.lp.strategy is Strategy.MTO:
            lots = apply_modifiers(qty, mins=[], roundings=[], maxes=maxes)
        else:
            lots = apply_modifiers(qty, mins=mins, roundings=rounds, maxes=maxes)
            step = max((r for r in rounds if r), default=None)
            if ceiling is not None and step and sum(lots) > ceiling + EPS:
                # replenish-to-max: round DOWN when that still covers the shortage and the minimums
                down = math.floor(ceiling / step + 1e-9) * step
                if down >= max([shortage or 0.0, *mins]) - EPS:
                    lots = apply_modifiers(down, mins=[], roundings=[], maxes=maxes)
        total = 0.0
        req_left = qty if below_zero is None else below_zero
        buf_left = 0.0 if shortage is None else max(0.0, shortage - req_left)
        for q in lots:
            self._create_order(node, st, opt, q, need)
            o = self.orders[-1]
            for_req = min(q, req_left)
            o.for_buffer = min(q - for_req, buf_left)
            o.for_lot_size = max(0.0, q - for_req - o.for_buffer)
            req_left -= for_req
            buf_left -= o.for_buffer
            self.quota_alloc[(node, opt.source_id)] += q
            total += q
        return total

    def _valid(self, opt: SupplyOption, d: date) -> bool:
        if opt.kind == "make":
            src = self.ds.production_source_by_id[opt.source_id]
        elif opt.kind == "buy":
            src = self.ds.purchasing_source_by_id[opt.source_id]
        else:
            return True
        return (src.valid_from is None or src.valid_from <= d) and (src.valid_to is None or src.valid_to >= d)

    def _choose(self, node: Node, need: date, qty: float) -> SupplyOption | None:
        valid = [o for o in self.g.options.get(node, []) if self._valid(o, need)]
        if not valid:
            return None
        quota = [o for o in valid if o.quota]
        if quota:
            total = sum(o.quota for o in quota)
            return min(quota, key=lambda o: ((self.quota_alloc[(node, o.source_id)] + qty) / (o.quota / total),
                                             o.priority, o.source_id))
        return valid[0]

    # ------------------------------------------------------------------ orders
    def _next_id(self, kind: str) -> str:
        self.counters[kind] += 1
        return f"{_PREFIX[kind]}-{self.counters[kind]:05d}"

    def _create_order(self, node: Node, st: _NodeState, opt: SupplyOption, qty: float, need: date) -> None:
        ds = self.ds
        target = need
        fence_end = self.start + timedelta(days=st.lp.planning_time_fence_days)
        fenced = st.lp.planning_time_fence_days > 0 and need < fence_end
        if fenced:
            target = fence_end
        sch: Schedule = schedule(ds, opt, qty, available=target)
        past = sch.start_date < self.start
        if past:
            sch = schedule(ds, opt, qty, start=self.start)
        oid = self._next_id(opt.kind)
        loc, prod = node
        origin = None
        if opt.kind == "transfer":
            origin = ds.lane_by_id[opt.source_id].origin
        elif opt.kind == "buy":
            origin = ds.purchasing_source_by_id[opt.source_id].supplier
        order = PlannedOrder(id=oid, kind=opt.kind, location=loc, product=prod, qty=qty, source_id=opt.source_id,
                             origin=origin, need_date=need, start_date=sch.start_date, due_date=sch.due_date,
                             available_date=sch.available_date, start_in_past=past, fence_shifted=fenced)
        self._cost(order, opt, qty)
        self.orders.append(order)
        self.order_by_id[oid] = order
        st.supplies.append(_Supply("order", oid, need, qty, sch.available_date))
        if past:
            late = (sch.available_date - need).days
            self._exc("START_IN_PAST", "warning",
                      f"{order.kind} {oid}: start would be before today; earliest availability "
                      f"{sch.available_date.isoformat()} ({late} d after need)", node=node, order=oid, when=need, qty=qty)
        if fenced:
            self._exc("FENCE_SHIFT", "info", f"{oid} moved to the planning time fence end {fence_end.isoformat()}",
                      node=node, order=oid, when=need, qty=qty)
        # explode
        if opt.kind == "make":
            ps = ds.production_source_by_id[opt.source_id]
            # the BOM as it stands on the day production starts (engineering change), phantoms passed through
            prod_start = sch.ops[0].start if sch.ops else sch.start_date
            for n in needs(ds, ps, prod_start):
                cq = n.qty(qty)
                if cq <= EPS:
                    continue
                cd = max(self.start, (sch.component_dates or {}).get(n.product, sch.start_date))
                req = Requirement(id=f"R:{oid}:{n.product}", location=loc, product=n.product, date=cd, qty=cq,
                                  kind="dependent", parent_order=oid)
                self._add_dependent((loc, n.product), req, oid)
            for co, cq in co_output(ps, qty):
                cst = self.state.get((loc, co))
                if cst is not None and cq > EPS:
                    cst.supplies.append(_Supply("co_product", oid, sch.available_date, cq, sch.available_date))
            for w in sch.ops:
                if w.resource is None:
                    continue   # done outside by a supplier
                self._load(w.resource, w.start, w.end, w.machine_hours)
                if w.labor_resource and w.labor_hours > 0:
                    self._load(w.labor_resource, w.start, w.end, w.labor_hours)
        elif opt.kind == "transfer":
            ln = ds.lane_by_id[opt.source_id]
            req = Requirement(id=f"T:{oid}", location=ln.origin, product=prod, date=max(self.start, sch.start_date),
                              qty=qty, kind="transfer", parent_order=oid)
            self._add_dependent((ln.origin, prod), req, oid)
            bi = self.b.index_of(sch.start_date)
            if 0 <= bi < len(self.b):
                self.lane_load[ln.id][bi] += qty
        else:
            bi = self.b.index_of(sch.ship_date or sch.start_date)
            if 0 <= bi < len(self.b):
                self.supplier_load[opt.source_id][bi] += qty

    def _add_dependent(self, node: Node, req: Requirement, parent: str) -> None:
        if node not in self.state:  # cannot happen for an acyclic, validated graph
            raise RuntimeError(f"requirement for unplanned node {node}")
        self._add_req(node, req)
        self.order_inputs[parent].append(req.id)

    def _load(self, resource: str, start: date, end: date, hours: float) -> None:
        if hours <= 0:
            return
        cal = resource_calendar(self.ds, resource)
        days = []
        d = start
        while d < end:
            if cal.is_workday(d):
                days.append(d)
            d += timedelta(days=1)
        if not days:
            days = [start]
        for d in days:
            self.res_daily[resource][d] += hours / len(days)

    def _cost(self, order: PlannedOrder, opt: SupplyOption, qty: float) -> None:
        ds, k = self.ds, self.kpi
        total = 0.0
        if opt.kind == "buy":
            pu = ds.purchasing_source_by_id[opt.source_id]
            price = pu.price * costing.fx(ds, pu.currency) * (1.0 + pu.duty_rate)
            lane = supplier_lane(ds, pu.supplier, pu.location, pu.product)
            freight = 0.0
            if lane:
                mode = lane.planning_mode
                order.shipments = costing.shipments_needed(ds, mode, pu.product, qty)
                freight = qty * costing.freight_per_unit(ds, mode, pu.product) + order.shipments * mode.cost_per_shipment
            hand = qty * costing.handling(ds, pu.location)
            k.purchase_cost += qty * price
            k.transport_cost += freight
            k.ordering_cost += pu.ordering_cost
            k.handling_cost += hand
            total = qty * price + freight + pu.ordering_cost + hand
            order.costs = {"purchase": qty * price, "transport": freight, "ordering": pu.ordering_cost, "handling": hand}
        elif opt.kind == "make":
            conv = qty * costing.conversion_unit_cost(ds, opt.source_id)
            setup = costing.setup_cost(ds, opt.source_id)
            k.production_cost += conv
            k.setup_cost += setup
            total = conv + setup
            order.costs = {"production": conv, "setup": setup}
        else:
            ln = ds.lane_by_id[opt.source_id]
            mode = ln.planning_mode
            order.shipments = costing.shipments_needed(ds, mode, order.product, qty)
            freight = qty * costing.freight_per_unit(ds, mode, order.product) + order.shipments * mode.cost_per_shipment
            hand = 0.0 if self.is_customer((ln.destination, order.product)) else qty * costing.handling(ds, ln.destination)
            k.transport_cost += freight
            k.handling_cost += hand
            total = freight + hand
            order.costs = {"transport": freight, "handling": hand}
        order.total_cost = total
        order.unit_cost = total / qty if qty > 0 else 0.0

    # ------------------------------------------------------------------ pegging
    def _peg(self, node: Node, st: _NodeState) -> None:
        supplies = sorted(st.supplies, key=lambda s: (s.date, {"on_hand": 0, "receipt": 1, "co_product": 2, "order": 3}[s.kind],
                                                      s.id))
        reqs = sorted(st.reqs, key=lambda r: (r.date, r.priority, r.id))
        left = [s.qty for s in supplies]
        first_peg = len(self.pegs)
        i = 0
        for r in reqs:
            need = r.qty
            while need > EPS and i < len(supplies):
                take = min(need, left[i])
                if take > EPS:
                    self.pegs.append(Peg(supply_kind=supplies[i].kind, supply_id=supplies[i].id,
                                         requirement_id=r.id, qty=take))
                    left[i] -= take
                    need -= take
                if left[i] <= EPS:
                    i += 1
        for s, rem in zip(supplies, left, strict=True):
            if s.kind == "order":
                self.order_by_id[s.id].lot_excess = max(0.0, rem)
        if st.lp.strategy is Strategy.ATO:
            forecast_reqs = {r.id for r in st.reqs if r.kind == "forecast"}
            for p in self.pegs[first_peg:]:
                if p.supply_kind == "order" and p.requirement_id in forecast_reqs:
                    self.order_by_id[p.supply_id].convertible = False

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        self.seed()
        for node in self.g.order:
            self.plan_node(node)
        self._propagate()

    def _propagate(self) -> None:
        """Projected availability: an order cannot finish earlier than its inputs are available. Each order carries
        a profile of how much of it is available by when, so an input that is only partly late delays only that
        share of the order (the part covered from stock ships on time, as promising splits it). An order's supply
        goes to its requirements earliest first. Upstream first (descending LLC)."""
        pegs_by_req: dict[str, list[int]] = defaultdict(list)
        pegs_by_order: dict[str, list[int]] = defaultdict(list)
        for i, p in enumerate(self.pegs):
            pegs_by_req[p.requirement_id].append(i)
            if p.supply_kind == "order":
                pegs_by_order[p.supply_id].append(i)
        receipt_date = {rc.id: self.receipt_date(rc) for rc in self.ds.receipts}
        beyond = self.b.end + timedelta(days=3650)
        chunks: dict[int, list[tuple[date, float]]] = {}  # peg index -> (date available, qty)

        def peg_chunks(i: int) -> list[tuple[date, float]]:
            p = self.pegs[i]
            if p.supply_kind == "order":
                return chunks.get(i, [(self.order_by_id[p.supply_id].available_date, p.qty)])
            if p.supply_kind == "receipt":
                return [(receipt_date.get(p.supply_id, self.start), p.qty)]
            if p.supply_kind == "co_product":
                main = self.order_by_id[p.supply_id]
                return [(main.projected_available_date or main.available_date, p.qty)]
            return [(self.start, p.qty)]

        def req_profile(r: Requirement) -> list[tuple[date, float]]:
            out = [c for i in pegs_by_req.get(r.id, []) for c in peg_chunks(i)]
            short = r.qty - sum(q for _, q in out)
            if short > 1e-6:
                out.append((beyond, short))
            return sorted(out)

        def order_profile(o: PlannedOrder) -> list[tuple[date, float]]:
            steps = []  # per input: requirement date, [(cumulative share, date)]
            for rid in self.order_inputs.get(o.id, []):
                r = self.req_by_id[rid]
                if r.qty <= 1e-9:
                    continue
                cum, marks = 0.0, []
                for d, q in req_profile(r):
                    cum += q
                    marks.append((cum / r.qty, d))
                steps.append((r.date, marks))
            if not steps:
                return [(o.available_date, o.qty)]
            cuts = sorted({min(1.0, x) for _, marks in steps for x, _ in marks} | {1.0})
            out: dict[date, float] = defaultdict(float)
            prev = 0.0
            for x in cuts:
                if x - prev <= 1e-12:
                    continue
                mid, delay, late = (prev + x) / 2, 0, False
                for need, marks in steps:
                    d = next((d for c, d in marks if c >= mid - 1e-12), beyond)
                    late = late or d >= beyond
                    delay = max(delay, (d - need).days)
                out[beyond if late else o.available_date + timedelta(days=delay)] += (x - prev) * o.qty
                prev = x
            return sorted((d, round(q, 9)) for d, q in out.items())

        for node in sorted(self.g.order, key=lambda n: -self.g.llc[n]):
            for s in self.state[node].supplies:
                if s.kind != "order":
                    continue
                o = self.order_by_id[s.id]
                prof = order_profile(o)
                last = prof[-1][0]
                o.projected_available_date = last if last < beyond else None
                o.delay_days = float(max(0, (last - o.need_date).days)) if last < beyond else -1.0
                o.projected_on_time_qty = sum(q for d, q in prof if d <= o.need_date)
                queue = [list(c) for c in prof]
                for i in sorted(pegs_by_order.get(o.id, []),
                                key=lambda i: (self.req_by_id[self.pegs[i].requirement_id].date, i)):
                    need, got = self.pegs[i].qty, []
                    while need > 1e-9 and queue:
                        take = min(need, queue[0][1])
                        got.append((queue[0][0], take))
                        need -= take
                        queue[0][1] -= take
                        if queue[0][1] <= 1e-9:
                            queue.pop(0)
                    if need > 1e-9:
                        got.append((beyond, need))
                    chunks[i] = got
        self._pegs_by_req = pegs_by_req
        self._peg_chunks = peg_chunks

    def _on_time(self, r: Requirement) -> float:
        """How much of a requirement its pegged supply projects to be available by the requirement's date."""
        return sum(q for i in self._pegs_by_req.get(r.id, []) for d, q in self._peg_chunks(i) if d <= r.date)

    # ------------------------------------------------------------------ outputs
    def result(self) -> PlanResult:
        s = self.s
        out = PlanResult(ok=True, currency=s.currency, carrying_rate=s.carrying_rate)
        out.buckets = [BucketOut(index=b.index, start=b.start, end=b.end, label=b.label) for b in self.b]
        n = len(self.b)
        k = self.kpi
        inv_start = inv_end = inv_avg_num = 0.0
        on_time = total_ind = 0.0
        for node in self.g.order:
            st = self.state[node]
            lp = st.lp
            val = self.val.unit_value.get(node, 0.0)
            rate = lp.holding_rate if lp.holding_rate is not None else s.carrying_rate
            bks = [NodeBucket(bucket=i, safety_stock=st.ss_by_bucket[i] if st.ss_by_bucket else 0.0,
                              target_stock=target_at(st.targets, self.b[i].end - timedelta(days=1)))
                   for i in range(n)]
            for r in st.reqs:
                bi = self.b.index_of(r.date)
                if 0 <= bi < n:
                    if r.kind in ("forecast", "sales_order"):
                        bks[bi].gross_independent += r.qty
                    else:
                        bks[bi].gross_dependent += r.qty
            for sp in st.supplies:
                if sp.kind == "on_hand":
                    continue
                bi = self.b.index_of(sp.avail_date)
                if 0 <= bi < n:
                    if sp.kind == "receipt":
                        bks[bi].scheduled_receipts += sp.qty
                    else:
                        bks[bi].planned_receipts += sp.qty
            onhand = 0.0 if self.is_customer(node) else lp.on_hand
            poh = onhand
            for bk, meta in zip(bks, self.b, strict=True):
                poh += bk.scheduled_receipts + bk.planned_receipts - bk.gross_independent - bk.gross_dependent
                bk.projected_on_hand = poh
                bk.shortage = max(0.0, -poh)
                bk.below_safety = max(0.0, bk.safety_stock - max(poh, 0.0)) if bk.safety_stock > 0 else 0.0
                if not self.is_customer(node):
                    bk.holding_cost = max(0.0, poh) * val * rate * meta.days / 365.0
                    k.holding_cost += bk.holding_cost
                    inv_avg_num += max(0.0, poh) * val * meta.days
            if not self.is_customer(node):
                inv_start += onhand * val
                inv_end += max(0.0, bks[-1].projected_on_hand) * val if bks else 0.0
            self._node_exceptions(node, st, bks)
            # service: independent demand projected available on time
            for r in st.reqs:
                if r.kind not in ("forecast", "sales_order"):
                    continue
                total_ind += r.qty
                covered = self._on_time(r)
                on_time += covered
                bi = self.b.index_of(r.date)
                if 0 <= bi < n and r.qty - covered > 1e-6:
                    bks[bi].at_risk += r.qty - covered
            opts = self.g.options.get(node) or []
            out.nodes.append(NodePlan(
                location=node[0], product=node[1], llc=self.g.llc[node], strategy=lp.strategy.value,
                mrp_type=lp.mrp_type.value, lot_policy=lp.lot_sizing.policy.value, unit_value=val,
                value_basis=self.val.basis.get(node, ""), on_hand=onhand,
                safety_stock_method=lp.safety_stock.method.value, safety_stock_note=st.ss_note,
                lead_time_days=st.lead_time, sources=[f"{o.kind}:{o.source_id}" for o in opts],
                buckets=bks, order_ids=[sp.id for sp in st.supplies if sp.kind == "order"]))
        self._demand_risk()
        out.resources = self._resources()
        self._capacity_checks()
        out.orders = self.orders
        out.requirements = [r for st in self.state.values() for r in st.reqs]
        out.receipts = [ScheduledReceiptOut(id=r.id, kind=r.kind.value, location=r.location, product=r.product,
                                            qty=r.qty, date=self.receipt_date(r)) for r in self.ds.receipts]
        out.pegs = self.pegs
        k.inventory_value_start = inv_start
        k.inventory_value_end = inv_end
        k.inventory_value_avg = inv_avg_num / s.horizon_days
        k.orders_make = sum(1 for o in self.orders if o.kind == "make")
        k.orders_buy = sum(1 for o in self.orders if o.kind == "buy")
        k.orders_transfer = sum(1 for o in self.orders if o.kind == "transfer")
        k.independent_demand = total_ind
        k.on_time_qty = on_time
        k.on_time_fill_rate = on_time / total_ind if total_ind > 0 else 1.0
        k.max_utilization = max((b.utilization for r in out.resources for b in r.buckets), default=0.0)
        k.total_cost = (k.purchase_cost + k.production_cost + k.setup_cost + k.ordering_cost + k.transport_cost
                        + k.handling_cost + k.holding_cost)
        out.kpis = k
        sev = {"error": 0, "warning": 1, "info": 2}
        out.exceptions = sorted(self.exceptions, key=lambda e: (sev[e.severity], e.code, e.location or "",
                                                                 e.product or "", e.date or self.start))
        return out

    def _node_exceptions(self, node: Node, st: _NodeState, bks: list[NodeBucket]) -> None:
        if self.is_customer(node):
            return
        short = [b for b in bks if b.shortage > EPS]
        if short:
            b0 = self.b[short[0].bucket]
            self._exc("STOCKOUT", "error",
                      f"Projected stock negative in {len(short)} bucket(s) from {b0.label}; "
                      f"worst {max(b.shortage for b in short):,.1f}", node=node, when=b0.start,
                      qty=max(b.shortage for b in short))
        below = [b for b in bks if b.below_safety > EPS and b.shortage <= EPS]
        if below:
            b0 = self.b[below[0].bucket]
            self._exc("BELOW_SAFETY_STOCK", "warning",
                      f"Below safety stock in {len(below)} bucket(s) from {b0.label}", node=node, when=b0.start,
                      qty=max(b.below_safety for b in below))
        lp = st.lp
        if lp.max_stock is not None:
            ex = [b for b in bks if b.projected_on_hand > lp.max_stock + EPS]
            if ex:
                b0 = self.b[ex[0].bucket]
                self._exc("EXCESS_STOCK", "warning", f"Above max stock {lp.max_stock:g} in {len(ex)} bucket(s)",
                          node=node, when=b0.start, qty=max(b.projected_on_hand for b in ex) - lp.max_stock)
        prod = self.ds.product_by_id.get(node[1])
        shelf = prod.shelf_life_days if prod else None
        if shelf:
            daily = sum(b.gross_independent + b.gross_dependent for b in bks) / self.s.horizon_days
            if daily > 0:
                worst = max((b.projected_on_hand / daily for b in bks), default=0.0)
                if worst > shelf:
                    self._exc("SHELF_LIFE_RISK", "warning",
                              f"Up to {worst:.0f} days of cover vs shelf life {shelf} d", node=node)

    def _demand_risk(self) -> None:
        for node in self.g.order:
            late = 0.0
            first: date | None = None
            for r in self.state[node].reqs:
                if r.kind not in ("forecast", "sales_order"):
                    continue
                covered = self._on_time(r)
                if r.qty - covered > 1e-6:
                    late += r.qty - covered
                    first = r.date if first is None else min(first, r.date)
            if late > 1e-6:
                why = ""
                if first is not None and (soon := self._earliest_new(node, self.state[node], first, late)) and soon > first:
                    why = (f": a new order started today is available {soon.isoformat()} at the earliest, so earlier "
                           "demand needs stock on hand or a firm receipt")
                self._exc("DEMAND_AT_RISK", "error",
                          f"{late:,.1f} units of demand projected late or uncovered (first {first.isoformat()}){why}",
                          node=node, when=first, qty=late)

    def _resources(self) -> list[ResourcePlan]:
        out = []
        for r in self.ds.resources:
            cal = resource_calendar(self.ds, r.id)
            loads = self.res_daily.get(r.id, {})
            bks = []
            for b in self.b:
                cap = hours_between(r, cal, b.start, b.end)
                ot = overtime_between(r, cal, b.start, b.end)
                load = sum(h for d, h in loads.items() if b.start <= d < b.end)
                bks.append(ResourceBucket(bucket=b.index, load_hours=load, capacity_hours=cap, overtime_hours=ot,
                                          utilization=(load / cap) if cap > 0 else (0.0 if load == 0 else math.inf)))
            before = sum(h for d, h in loads.items() if d < self.b.start)
            if before > 0:
                bks[0].load_hours += before
                cap0 = bks[0].capacity_hours
                bks[0].utilization = bks[0].load_hours / cap0 if cap0 > 0 else math.inf
            out.append(ResourcePlan(resource=r.id, location=r.location, kind=r.kind.value, finite=r.finite, buckets=bks))
        self._resource_plans = out
        return out

    def _capacity_checks(self) -> None:
        for rp in self._resource_plans:
            over = [b for b in rp.buckets if b.load_hours > b.capacity_hours + b.overtime_hours + 1e-6]
            ot = [b for b in rp.buckets if b.capacity_hours + 1e-6 < b.load_hours <= b.capacity_hours + b.overtime_hours + 1e-6]
            if over:
                b0 = self.b[over[0].bucket]
                worst = max(b.load_hours - b.capacity_hours - b.overtime_hours for b in over)
                self._exc("CAPACITY_OVERLOAD", "error" if rp.finite else "info",
                          f"{rp.resource}: load exceeds capacity + overtime in {len(over)} bucket(s) from {b0.label}; "
                          f"worst excess {worst:,.1f} h", resource=rp.resource, when=b0.start, qty=worst)
            if ot:
                b0 = self.b[ot[0].bucket]
                self._exc("CAPACITY_OVERTIME", "warning",
                          f"{rp.resource}: overtime needed in {len(ot)} bucket(s) from {b0.label}",
                          resource=rp.resource, when=b0.start)
        for src_id, loads in self.supplier_load.items():
            pu = self.ds.purchasing_source_by_id[src_id]
            if not pu.capacity_per_week:
                continue
            for b, q in zip(self.b, loads, strict=True):
                cap = pu.capacity_per_week * b.days / 7.0
                if q > cap + 1e-6:
                    self._exc("SUPPLIER_CAPACITY", "error",
                              f"{pu.supplier} ({src_id}): {q:,.0f} ordered vs capacity {cap:,.0f} in {b.label}",
                              node=(pu.location, pu.product), when=b.start, qty=q - cap)
        for lane_id, loads in self.lane_load.items():
            mode = self.ds.lane_by_id[lane_id].planning_mode
            if not mode.capacity_units_per_week:
                continue
            for b, q in zip(self.b, loads, strict=True):
                cap = mode.capacity_units_per_week * b.days / 7.0
                if q > cap + 1e-6:
                    self._exc("LANE_CAPACITY", "error", f"Lane {lane_id}: {q:,.0f} shipped vs capacity {cap:,.0f} in {b.label}",
                              when=b.start, qty=q - cap)

    def _exc(self, code: str, severity: str, message: str, *, node: Node | None = None, order: str | None = None,
             resource: str | None = None, when: date | None = None, qty: float | None = None) -> None:
        self.exceptions.append(PlanException(code=code, severity=severity, message=message,
                                             location=node[0] if node else None, product=node[1] if node else None,
                                             resource=resource, order_id=order, date=when, qty=qty))


def target_at(points: list[tuple[date, float]], d: date) -> float:
    """The S&OP stock target on ``d``: linear between the surrounding points, none outside them."""
    if not points or d < points[0][0] or d > points[-1][0]:
        return 0.0
    for (d0, q0), (d1, q1) in zip(points, points[1:], strict=False):
        if d0 <= d <= d1:
            span = (d1 - d0).days
            return q1 if span <= 0 else q0 + (q1 - q0) * (d - d0).days / span
    return points[-1][1] if d == points[-1][0] else 0.0


def run_mrp(ds: Dataset) -> PlanResult:
    """Validate, then plan. With blocking issues the result carries only the issues."""
    issues = validate(ds)
    if has_errors(issues):
        return PlanResult(ok=False, currency=ds.settings.currency, carrying_rate=ds.settings.carrying_rate,
                          issues=issues)
    g = build_graph(ds)
    p = _Planner(ds, g)
    p.run()
    res = p.result()
    res.issues = issues
    return res


__all__ = ["run_mrp"]
