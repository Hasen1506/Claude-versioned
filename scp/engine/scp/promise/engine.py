"""Order promising (S/4 guide §7): availability check, product allocation, alternative-based
confirmation, capable-to-promise and backorder processing.

Supply picture per shipping node (the *scope of check*):

* inflows  — stock at planning start, firm receipts (on their availability date = due + GR) and, when
  ``include_planned_orders``, the MRP planned receipts;
* outflows — dependent and replenishment requirements from MRP (components, stock transfers to other
  stocking locations; those of planned orders only when planned receipts are in scope) and every
  sales-order confirmation shipping from the node. Forecast and the customer demand itself are not
  outflows: ATP promises supply to orders, not to forecasts.

A sales order at a customer is shipped over a lane from a stocking location; the requested ship
date is the requested delivery date minus transit and goods-receipt time. Its confirmed delivery
date is the confirmed ship date plus the same.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..model import (
    Dataset, DemandKind, DemandRecord, LocationType,
)
from ..model.promise import Allocation, BopSegment, Confirmation
from ..network import NetworkGraph, Node, build_graph
from ..plan import PlanResult
from ..plan.costing import component_factor
from ..plan.leadtime import (
    gr_days, nominal_lead_time_days, schedule_buy, schedule_make, schedule_transfer, started_qty,
)
from .atp import EPS, AtpSeries
from .result import AtpNode, CtpStep, OrderPromise, ScheduleLine

_MAX_DEPTH = 6


def order_key(d: DemandRecord, i: int) -> str:
    return d.id or f"#{i}"


@dataclass
class Ship:
    """One way to ship an order: from ``node`` over ``lane`` (None = the order sits at the node)."""
    node: Node
    lane: str | None


@dataclass
class Action:
    kind: str                 # "out" (node, day, qty) | "cap" (resource, bucket, hours)
    a: object
    b: int
    c: float


@dataclass
class CtpPlan:
    day: int                  # availability day at the shipping node
    steps: list[CtpStep] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)


class Promiser:
    def __init__(self, ds: Dataset, plan: PlanResult, g: NetworkGraph | None = None) -> None:
        self.ds = ds
        self.plan = plan
        self.g = g or build_graph(ds)
        self.cfg = ds.promising
        self.origin = ds.settings.planning_start
        self.days = ds.settings.horizon_days + 400
        self.series: dict[Node, AtpSeries] = {}
        self.other: dict[Node, list[float]] = {}
        self.promised: dict[Node, list[float]] = defaultdict(lambda: [0.0] * self.days)
        self.alloc_used: dict[str, float] = defaultdict(float)
        self.orders_by_id = {o.id: o for o in plan.orders}
        self._rlt: dict[Node, float] = {}
        # free finite capacity per resource and plan bucket (hours), for CTP
        self.bucket_days = [((b.start - self.origin).days, (b.end - self.origin).days) for b in plan.buckets]
        self.free: dict[str, list[float]] = {}
        for rp in plan.resources:
            if rp.finite:
                self.free[rp.resource] = [max(0.0, b.capacity_hours - b.load_hours) for b in rp.buckets]

    # ---- time -----------------------------------------------------------------------------------
    def day(self, d: date) -> int:
        return (d - self.origin).days

    def date(self, i: int) -> date:
        return self.origin + timedelta(days=i)

    # ---- supply picture -------------------------------------------------------------------------
    def rlt(self, node: Node, depth: int = 0) -> float:
        """Total replenishment lead time over the primary sources: transit plus the source's RLT for a
        transfer, production time plus the longest component RLT for a make, purchasing lead time
        (with transit and GR) for a buy. Beyond it, supply can always be arranged."""
        if node in self._rlt:
            return self._rlt[node]
        opts = self.g.options.get(node, [])
        if not opts or depth > 3 * _MAX_DEPTH:
            return 0.0
        opt = opts[0]
        lt = nominal_lead_time_days(self.ds, opt) or 0.0
        if opt.kind == "transfer":
            lt += self.rlt(opt.upstream[0], depth + 1)
        elif opt.kind == "make":
            lt += max((self.rlt(u, depth + 1) for u in opt.upstream), default=0.0)
        self._rlt[node] = lt
        return lt

    def series_for(self, node: Node) -> AtpSeries:
        if node in self.series:
            return self.series[node]
        ds = self.ds
        rlt_day = math.ceil(self.rlt(node) - 1e-9) if self.cfg.confirm_beyond_rlt else None
        s = AtpSeries(self.days, rlt_day)
        lp = ds.location_product_by_key.get(node)
        s.add_in(0, lp.on_hand if lp else 0.0)
        for r in ds.receipts:
            if (r.location, r.product) == node:
                s.add_in(self.day(r.due_date) + math.ceil(gr_days(lp) - 1e-9), r.qty)
        if self.cfg.include_planned_orders:
            for o in self.plan.orders:
                if (o.location, o.product) == node:
                    s.add_in(self.day(o.available_date), o.qty)
        other = [0.0] * self.days
        for rq in self.plan.requirements:
            if (rq.location, rq.product) != node or rq.kind not in ("dependent", "transfer"):
                continue
            parent = self.orders_by_id.get(rq.parent_order or "")
            if parent is not None:
                if not self.cfg.include_planned_orders:
                    continue   # symmetric scope: no planned receipts, so none of their requirements
                if rq.kind == "transfer" and ds.location_type(parent.location) is LocationType.CUSTOMER:
                    continue   # the customer demand itself: promised by this check, not reserved
            d = min(max(self.day(rq.date), 0), self.days - 1)
            s.add_out(d, rq.qty)
            other[d] += rq.qty
        self.series[node] = s
        self.other[node] = other
        return s

    def ships(self, d: DemandRecord) -> list[Ship]:
        node = (d.location, d.product)
        if self.ds.location_type(d.location) is not LocationType.CUSTOMER:
            return [Ship(node, None)]
        out = [Ship(o.upstream[0], o.source_id) for o in self.g.options.get(node, []) if o.kind == "transfer"]
        return out if self.cfg.alternative_locations else out[:1]

    def ship_day(self, sh: Ship, product: str, delivery: date) -> int:
        if sh.lane is None:
            return max(0, self.day(delivery))
        return max(0, self.day(schedule_transfer(self.ds, sh.lane, product, available=delivery).start_date))

    def delivery(self, sh: Ship, product: str, ship_day: int) -> date:
        if sh.lane is None:
            return self.date(ship_day)
        return schedule_transfer(self.ds, sh.lane, product, start=self.date(ship_day)).available_date

    # ---- product allocation ----------------------------------------------------------------------
    def allocations(self, d: DemandRecord) -> list[Allocation]:
        return [a for a in self.ds.allocations
                if a.product == d.product and (not a.customers or d.location in a.customers)]

    def alloc_period(self, allocs: list[Allocation], day: int) -> Allocation | None:
        dt_ = self.date(day)
        return next((a for a in allocs if a.start <= dt_ < a.end), None)

    def alloc_cap(self, allocs: list[Allocation], day: int) -> float:
        if not allocs:
            return math.inf
        a = self.alloc_period(allocs, day)
        return max(0.0, a.qty - self.alloc_used[a.id]) if a else 0.0

    # ---- committing -----------------------------------------------------------------------------
    def commit_line(self, d: DemandRecord, sh: Ship, ship_day: int, qty: float, method: str,
                    allocs: list[Allocation], requested: date) -> ScheduleLine:
        s = self.series_for(sh.node)
        s.add_out(ship_day, qty)
        self.promised[sh.node][min(max(ship_day, 0), self.days - 1)] += qty
        a = self.alloc_period(allocs, ship_day) if allocs else None
        if a:
            self.alloc_used[a.id] += qty
        deliv = self.delivery(sh, d.product, ship_day)
        return ScheduleLine(ship_from=sh.node[0], ship_date=self.date(ship_day), date=deliv, qty=qty, method=method,
                            on_time=deliv <= max(requested, self.origin))

    def register(self, d: DemandRecord, c: Confirmation) -> ScheduleLine:
        """A persisted schedule line claims its supply as an outflow."""
        node = (c.ship_from, d.product)
        day = self.day(c.ship_date)
        self.series_for(node).add_out(day, c.qty)
        self.promised[node][min(max(day, 0), self.days - 1)] += c.qty
        allocs = self.allocations(d)
        a = self.alloc_period(allocs, day) if allocs else None
        if a:
            self.alloc_used[a.id] += c.qty
        return ScheduleLine(ship_from=c.ship_from, ship_date=c.ship_date, date=c.date, qty=c.qty, method=c.method,
                            on_time=c.date <= max(d.date, self.origin))

    def snapshot(self) -> tuple:
        return ({n: s.snapshot() for n, s in self.series.items()}, {n: list(v) for n, v in self.promised.items()},
                dict(self.alloc_used), {r: list(v) for r, v in self.free.items()})

    def restore(self, snap: tuple) -> None:
        series, promised, alloc, free = snap
        for n in list(self.series):
            if n in series:
                self.series[n].restore(series[n])
            else:
                del self.series[n]
        self.promised = defaultdict(lambda: [0.0] * self.days, {n: list(v) for n, v in promised.items()})
        self.alloc_used = defaultdict(float, alloc)
        self.free = {r: list(v) for r, v in free.items()}

    # ---- the check ------------------------------------------------------------------------------
    def check(self, d: DemandRecord, key: str, qty: float | None = None) -> OrderPromise:
        """Promise ``qty`` (default: the order quantity) and commit the resulting schedule lines."""
        q = d.qty if qty is None else qty
        price = (self.ds.product_by_id[d.product].price or 0.0) if d.product in self.ds.product_by_id else 0.0
        res = OrderPromise(order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date,
                           priority=d.priority, complete_delivery=d.complete_delivery, value=d.qty * price)
        ships = self.ships(d)
        if not ships or q <= EPS:
            return finish(res)
        allocs = self.allocations(d)
        remaining = q
        # 1) on time: the first location, then alternatives (alternative-based confirmation)
        for k, sh in enumerate(ships):
            s = self.series_for(sh.node)
            i = self.ship_day(sh, d.product, d.date)
            if s.unconditional(i):
                continue            # beyond RLT is the fallback, not an on-time source
            cap = self.alloc_cap(allocs, i)
            a = s.available(i)
            if k == 0 and allocs:
                res.allocation_capped = max(0.0, min(a, remaining) - cap)
            a = min(a, cap)
            take = remaining if (d.complete_delivery and a >= remaining - EPS) else (0.0 if d.complete_delivery else min(a, remaining))
            if take > EPS:
                res.lines.append(self.commit_line(d, sh, i, take, "atp", allocs, d.date))
                remaining -= take
            if remaining <= EPS:
                return finish(res)
        # 2) the rest from the first location: later ATP dates / beyond RLT, or CTP if that is sooner
        sh = ships[0]
        s = self.series_for(sh.node)
        i0 = self.ship_day(sh, d.product, d.date)
        snap = self.snapshot()
        late = self._late(d, sh, i0, remaining, allocs)
        late_qty = sum(x.qty for x in late)
        late_last = max((self.day(x.ship_date) for x in late), default=None)
        if self.cfg.ctp and not s.unconditional(i0):
            self.restore(snap)
            plan = self.ctp(sh.node, remaining, i0, 0, set())
            if plan is not None:
                cap = self.alloc_cap(allocs, plan.day)
                better = (late_qty < remaining - EPS) or (late_last is not None and plan.day < late_last)
                if better and cap >= remaining - EPS:
                    for act in plan.actions:
                        self._apply(act)
                    res.lines.append(self.commit_line(d, sh, max(plan.day, i0), remaining, "ctp", allocs, d.date))
                    res.ctp = plan.steps
                    return finish(res)
            self.restore(snap)
            late = self._late(d, sh, i0, remaining, allocs)
        res.lines.extend(late)
        return finish(res)

    def _late(self, d: DemandRecord, sh: Ship, i0: int, qty: float, allocs: list[Allocation]) -> list[ScheduleLine]:
        s = self.series_for(sh.node)
        reject = allocs and (p := self.alloc_period(allocs, i0)) is not None and p.fallback == "reject"
        period = self.alloc_period(allocs, i0) if reject else None
        lines: list[ScheduleLine] = []
        remaining = qty
        for i in range(i0, self.days):
            if period is not None and not (period.start <= self.date(i) < period.end):
                break
            cap = self.alloc_cap(allocs, i)
            if cap <= EPS:
                continue
            a = s.available(i)
            unc = s.unconditional(i)
            if d.complete_delivery:
                if min(a, cap) >= remaining - EPS:
                    lines.append(self.commit_line(d, sh, i, remaining, "rlt" if unc else "atp", allocs, d.date))
                    return lines
                continue
            take = min(a, cap, remaining)
            if take > EPS:
                lines.append(self.commit_line(d, sh, i, take, "rlt" if unc else "atp", allocs, d.date))
                remaining -= take
                if remaining <= EPS:
                    break
        return lines

    # ---- capable-to-promise --------------------------------------------------------------------
    def ctp(self, node: Node, qty: float, need: int, depth: int, path: set) -> CtpPlan | None:
        """Earliest day ``qty`` extra could be available at ``node``: from real stock, else by a new
        transfer, production (components and finite capacity) or purchase."""
        if depth > _MAX_DEPTH or node in path:
            return None
        path = path | {node}
        best: CtpPlan | None = None
        loc, prod = node
        if depth > 0:
            s = self.series_for(node)
            k = s.first_firm(qty, need)
            if k is not None:
                best = CtpPlan(k, [CtpStep(kind="stock", location=loc, product=prod, qty=qty, start=self.date(k),
                                           note="available-to-promise at the source")],
                               [Action("out", node, k, qty)])
        for opt in self.g.options.get(node, [])[:4]:
            cand: CtpPlan | None = None
            if opt.kind == "transfer":
                src = opt.upstream[0]
                ln = self.ds.lane_by_id[opt.source_id]
                transit = math.ceil(ln.planning_mode.transit_days + gr_days(self.ds.location_product_by_key.get(node)) - 1e-9)
                up = self.ctp(src, qty, max(0, need - transit), depth + 1, path)
                if up is not None:
                    sched = schedule_transfer(self.ds, opt.source_id, prod, start=self.date(up.day))
                    arr = self.day(sched.available_date)
                    cand = CtpPlan(arr, up.steps + [CtpStep(kind="transfer", location=loc, product=prod, qty=qty,
                                                            start=sched.start_date, end=sched.available_date,
                                                            note=f"from {src[0]} over {opt.source_id}")], up.actions)
            elif opt.kind == "make":
                cand = self._ctp_make(opt.source_id, node, qty, need, depth, path)
            elif opt.kind == "buy":
                sched = schedule_buy(self.ds, opt.source_id, start=self.origin)
                cand = CtpPlan(self.day(sched.available_date), [CtpStep(
                    kind="buy", location=loc, product=prod, qty=qty, start=sched.start_date, end=sched.available_date,
                    note=f"purchase via {opt.source_id} placed today")], [])
            if cand is not None and (best is None or cand.day < best.day):
                best = cand
        return best

    def _ctp_make(self, ps_id: str, node: Node, qty: float, need: int, depth: int, path: set) -> CtpPlan | None:
        ds = self.ds
        ps = ds.production_source_by_id[ps_id]
        loc, prod = node
        steps: list[CtpStep] = []
        actions: list[Action] = []
        start = 0
        for comp in ps.components:
            cnode = (loc, comp.product)
            cq = qty * component_factor(ds, ps_id, comp.product)
            s = self.series_for(cnode)
            k = s.first_firm(cq, 0)
            if k is not None:
                steps.append(CtpStep(kind="component", location=loc, product=comp.product, qty=cq, start=self.date(k),
                                     note="component available-to-promise"))
                actions.append(Action("out", cnode, k, cq))
            else:
                sub = self.ctp(cnode, cq, 0, depth + 1, path)
                if sub is None:
                    return None
                k = sub.day
                steps += sub.steps
                actions += sub.actions
            start = max(start, k)
        # finite capacity: every operation's hours must fit into free bucket capacity from the start
        q = started_qty(ps, qty)
        hours: dict[str, float] = defaultdict(float)
        for op in ps.operations:
            if op.resource in self.free:
                hours[op.resource] += op.setup_hours + op.run_hours_per_unit * q
        finish = start
        for rid, h in hours.items():
            got = self._capacity(rid, start, h)
            if got is None:
                return None
            end, takes = got
            finish = max(finish, end)
            actions += [Action("cap", rid, b, x) for b, x in takes]
            steps.append(CtpStep(kind="capacity", location=loc, product=prod, qty=h, start=self.date(start),
                                 end=self.date(end), note=f"{h:.1f} h on {rid}"))
        sched = schedule_make(ds, ps, qty, start=self.date(start))
        done = max(self.day(sched.available_date), finish + math.ceil(gr_days(ds.location_product_by_key.get(node)) - 1e-9))
        steps.append(CtpStep(kind="make", location=loc, product=prod, qty=qty, start=self.date(start), end=self.date(done),
                             note=f"new production via {ps_id}"))
        return CtpPlan(done, steps, actions)

    def _capacity(self, rid: str, start: int, hours: float) -> tuple[int, list[tuple[int, float]]] | None:
        free = self.free[rid]
        need = hours
        takes: list[tuple[int, float]] = []
        for b, (s0, e0) in enumerate(self.bucket_days):
            if e0 <= start:
                continue
            span = e0 - s0
            share = (e0 - max(s0, start)) / span if span else 0.0
            avail = free[b] * share
            if avail <= EPS:
                continue
            take = min(avail, need)
            takes.append((b, take))
            need -= take
            if need <= EPS:
                used = take / free[b] * span if free[b] > 0 else span
                return max(s0, start) + math.ceil(used - 1e-9), takes
        return None

    def _apply(self, act: Action) -> None:
        if act.kind == "out":
            self.series_for(act.a).add_out(act.b, act.c)
        else:
            self.free[act.a][act.b] = max(0.0, self.free[act.a][act.b] - act.c)

    # ---- views ----------------------------------------------------------------------------------
    def node_view(self, node: Node, span: int) -> AtpNode:
        s = self.series_for(node)
        lp = self.ds.location_product_by_key.get(node)
        span = min(span, self.days)
        cum = s.cum()
        atp = s.atp()
        short = s.shortage()
        other = self.other.get(node, [0.0] * self.days)
        return AtpNode(
            location=node[0], product=node[1], rlt_days=s.rlt_day, on_hand=lp.on_hand if lp else 0.0,
            dates=[self.date(i) for i in range(span)], receipts=s.inflow[:span], other_demand=other[:span],
            promised=self.promised[node][:span], cumulative=cum[:span],
            available=[None if math.isinf(atp[i]) else max(0.0, atp[i]) for i in range(span)],
            shortage_date=self.date(short[0]) if short else None, shortage_qty=short[1] if short else 0.0)


def finish(res: OrderPromise) -> OrderPromise:
    res.lines.sort(key=lambda x: (x.ship_date, x.ship_from))
    res.confirmed = sum(x.qty for x in res.lines)
    res.on_time = sum(x.qty for x in res.lines if x.on_time)
    res.unconfirmed = max(0.0, res.qty - res.confirmed)
    if res.on_time >= res.qty - EPS:
        res.status = "on_time"
    elif res.confirmed >= res.qty - EPS:
        res.status = "late"
    elif res.confirmed > EPS:
        res.status = "partial"
    else:
        res.status = "unconfirmed"
    return res


def sales_orders(ds: Dataset) -> list[tuple[str, DemandRecord]]:
    """Open sales orders in entry sequence (dataset order)."""
    return [(order_key(d, i), d) for i, d in enumerate(ds.demand) if d.kind is DemandKind.SALES_ORDER and d.qty > EPS]


def segment_of(segs: list[BopSegment], d: DemandRecord) -> BopSegment | None:
    for sg in segs:
        if sg.priorities and d.priority not in sg.priorities:
            continue
        if sg.customers and d.location not in sg.customers:
            continue
        if sg.products and d.product not in sg.products:
            continue
        return sg
    return None


def sort_key(sg: BopSegment, d: DemandRecord, idx: int) -> tuple:
    if sg.sort == "date":
        return (d.date, idx)
    if sg.sort == "qty_desc":
        return (-d.qty, d.date, idx)
    return (d.priority, d.date, idx)

