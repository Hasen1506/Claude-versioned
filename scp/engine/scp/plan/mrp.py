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

import bisect
import hashlib
import math
import os
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Callable
from contextvars import ContextVar
from itertools import accumulate
import dataclasses
import gc
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, TypeVar

from ..model import (
    Dataset, LocationProduct, LocationType, LotSizePolicy, MrpType, ReceiptKind, SafetyStockMethod, SafetyStockPolicy,
    Strategy,
)
from ..model.common import DYNAMIC_LOTS
from ..network import NetworkGraph, Node, SupplyOption, build_graph
from ..time import Buckets
from ..time.capacity import NoWorkingTime, day_capacity, hours_between, overtime_between
from ..validate import has_errors, validate
from . import costing, rates
from .consumption import _consume
from .leadtime import (
    Schedule, batch_multiple, gr_after, lead_time_std_days, location_calendar, nominal_lead_time_days,
    resource_calendar, schedule, schedule_make, supplier_lane,
)
from .lotsize import apply_modifiers, base_lot, dynamic_periods
from .structure import co_output, needs
from .result import (
    BucketOut, Kpis, LateDemand, NodeBucket, NodePlan, OrderLoad, Peg, PlanException, PlannedOrder, PlanResult,
    Requirement, ResourceBucket, ResourcePlan, ScheduledReceiptOut,
)

EPS = 1e-9
_PREFIX = {"make": "MO", "buy": "PR", "transfer": "TO"}
# what planning one node does beyond its own state, kept so that an unchanged node is replayed, not planned again
_REQ, _INPUT, _SUP, _LOAD, _FLOW, _KPI, _EXC, _PEG = range(8)


@dataclass
class _Supply:
    kind: str       # on_hand | receipt | co_product | order | follow_up
    id: str
    date: date      # netting date
    qty: float
    avail_date: date  # physical availability
    fixed: bool = False   # a receipt dated by the detailed schedule
    segment: str | None = None   # held for this sales order (sales-order stock): pegged only to it


@dataclass
class _NodeState:
    lp: LocationProduct
    reqs: list[Requirement] = field(default_factory=list)
    supplies: list[_Supply] = field(default_factory=list)
    ss_by_bucket: list[float] = field(default_factory=list)
    targets: list[tuple[date, float]] = field(default_factory=list)   # S&OP stock targets (date, qty), by date
    ss_note: str = ""
    lead_time: float | None = None
    fixed: list[tuple[_Supply, str, float]] = field(default_factory=list)   # sales-order stock pegged to its order
    netted: list[Requirement] | None = None   # the requirements left once the sales orders' own supply is counted
    forecasts: list[tuple[str, date, int, list[str]]] = field(default_factory=list)   # strategy 70: each forecast's
    # (id, first day, days, the ids of the daily requirements it was spread into)


@dataclass
class _NodeMemo:
    """One node's planning, as the next plan replays it when nothing it reads has changed."""
    key: tuple                             # everything the node reads of the data (see ``_Planner._key``)
    incoming: list[tuple[Node, Any]]       # what planned consumers handed it before it was planned, in order
    fx: list[tuple]                        # what it did beyond its own state, in order
    st: _NodeState                         # its state once planned
    orders: list[PlannedOrder]
    pegs: list[Peg]
    quota: list[tuple[tuple[Node, str], float]]
    lot_cost: tuple[float, float] | None
    reads_up: bool                         # its plan reads its consumers' plans (sales-order stock, make to order)
    chunks: list[list[tuple[date, float]]] | None = None   # each peg's supply, by when available (projection)
    out: tuple | None = None               # its part of the result (see ``_Planner._node_result``)


class _NotIncremental(Exception):
    """The change reaches something the previous plan's work cannot be reused for: plan everything."""


@dataclass
class Kept:
    """What a plan keeps for planning the same company again after a change (S/4 net change planning): the data it
    was made from and each node's work. Only the nodes a change reaches are planned again."""
    gkey: tuple
    order: list[Node]
    llc: dict[Node, int]
    memo: dict[Node, _NodeMemo]
    reused: bool = False                   # this plan was itself made from a previous plan's work
    planned: int = 0                       # nodes it planned (the rest it replayed)


class _Fresh:
    """Stock of a product with a shelf life by the day it expires, used first expiring first out (R15, N109): what a
    lot still holds after its last day is gone. Stock at the start comes first (it is older; its batches that expire
    unused are requirements already, see ``_expiry``); a requirement the stock does not cover is owed and taken
    from the next lot to arrive."""

    def __init__(self, plain: float):
        self.plain = plain
        self.lots: list[list] = []   # [last day, quantity, what it came from], soonest first
        self.owed = 0.0

    def add(self, last: date, qty: float, what: str) -> None:
        pay = min(qty, self.owed)
        self.owed -= pay
        if qty - pay > EPS:
            bisect.insort(self.lots, [last, qty - pay, what])

    def use(self, qty: float) -> None:
        take = min(qty, self.plain)
        self.plain -= take
        qty -= take
        for lot in self.lots:
            if qty <= EPS:
                break
            take = min(qty, lot[1])
            lot[1] -= take
            qty -= take
        self.lots = [x for x in self.lots if x[1] > EPS]
        self.owed += max(0.0, qty)

    def expire(self, on: date) -> list[list]:
        """The lots whose last day is before ``on``: gone, with what they still held."""
        gone = [x for x in self.lots if x[0] < on]
        if gone:
            self.lots = [x for x in self.lots if x[0] >= on]
        return gone


def fence_end(ds: Dataset, node: Node, lp: LocationProduct) -> date | None:
    """The end of the planning time fence (S/4 §8.5) from the planning start (None: no fence): working days of the
    place's calendar when the company counts them so, else calendar days."""
    if lp.planning_time_fence_days <= 0:
        return None
    start = ds.settings.planning_start
    if ds.settings.working_day_fences:
        return location_calendar(ds, node[0]).add_workdays(start, lp.planning_time_fence_days)
    return start + timedelta(days=lp.planning_time_fence_days)


def fence_days_to(ds: Dataset, node: Node, end: date) -> float:
    """The fence, in the company's days, that ends on ``end`` (the inverse of :func:`fence_end`)."""
    start = ds.settings.planning_start
    if end <= start:
        return 0.0
    if ds.settings.working_day_fences:
        return float(location_calendar(ds, node[0]).workdays_between(start + timedelta(days=1), end + timedelta(days=1)))
    return float((end - start).days)


class _Planner:
    def __init__(self, ds: Dataset, g: NetworkGraph, kept: Kept | None = None):
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
        self.counters: dict[tuple[Node, str], int] = defaultdict(int)   # orders of each kind made at each node
        self._node_no = {n: i for i, n in enumerate(g.order, 1)}         # its number in planned order numbers
        self.quota_alloc: dict[tuple[Node, str], float] = defaultdict(float)
        self.res_daily: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
        self.res_orders: dict[str, dict[tuple[str, str, bool], dict[date, float]]] = defaultdict(dict)
        self._caps: dict[tuple[str, date], float] = {}
        self.supplier_load: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(self.b))
        self.lane_load: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(self.b))
        self.kpi = Kpis()
        self.kept = kept
        self._expiring: dict[Node, list[tuple[date, float, str]]] | None = None
        self._buffers: dict | None = None
        self._lot_costs: dict[Node, tuple[float, float]] = {}
        self._pegs_of: dict[str, list[Peg]] = defaultdict(list)   # supply id → its pegs so far
        # each node's work, kept for planning again after a change (see :class:`Kept`)
        self.memo: dict[Node, _NodeMemo] = {}
        self.incoming: dict[Node, list[tuple[Node, Any]]] = defaultdict(list)   # what other nodes added, in order
        self.touched: set[Node] = set()           # nodes planned (not replayed) in this run
        self._cur: Node | None = None             # the node being planned or replayed
        self._fx: list[tuple] | None = None       # its effects, while it is planned
        self._done: set[Node] = set()
        self._peg_at: dict[Node, tuple[int, int]] = {}
        self._order_at: dict[Node, tuple[int, int]] = {}

    # ------------------------------------------------------------------ setup
    def lp(self, node: Node) -> LocationProduct:
        return self.ds.planning_lp(node)

    def is_customer(self, node: Node) -> bool:
        return self.ds.location_type(node[0]) is LocationType.CUSTOMER

    def shelf(self, node: Node) -> int | None:
        """Days a batch of this product keeps, where the plan follows its batches (R15); None otherwise."""
        prod = self.ds.product_by_id.get(node[1])
        if prod is None or not prod.shelf_life_days or not prod.batch_managed or self.is_customer(node):
            return None
        return prod.shelf_life_days

    def prepare(self) -> None:
        """What seeding every node draws on, gathered once: independent demand, stock targets, the firm receipts and
        what they reserve, and the machines firm production orders occupy."""
        for node in self.g.order:
            self.state[node] = _NodeState(lp=self.lp(node))
        self._targets: dict[Node, list[tuple[date, float]]] = defaultdict(list)
        for t in sorted(self.ds.stock_targets, key=lambda t: t.date):
            node = (t.location, t.product)
            if node in self.state and not self.is_customer(node):
                self._targets[node].append((t.date, t.qty))
        self._indep = rates.independent_demand(self.ds)
        self._rc_at: dict[Node, list] = defaultdict(list)
        self._rv_at: dict[Node, list] = defaultdict(list)
        for rc in self.ds.receipts:
            node = (rc.location, rc.product)
            if node not in self.state:
                continue
            self._rc_at[node].append(rc)
            self._firm_load(rc)
            for rv in rc.reservations:
                rn = (rv.location, rv.product)
                if rn in self.state and rv.qty > EPS:
                    self._rv_at[rn].append((rc, rv))

    def seed(self, node: Node) -> None:
        """A node's own requirements and firm supply, ahead of what its planned consumers already handed it."""
        st = self.state[node]
        came, brought = st.reqs, st.supplies
        st.reqs, st.supplies = [], []
        st.targets = list(self._targets.get(node, ()))
        parts = st.lp.strategy is Strategy.ASSEMBLY
        for r, days in self._indep.get(node, ()):
            ids: list[str] = []
            for i, (d, q) in enumerate(self._split(node, r.date, r.qty, days if r.kind == "forecast" else None)):
                if d >= self.b.end:
                    continue  # beyond horizon (validator warned)
                rid = r.id if i == 0 else f"{r.id}~{i}"
                req = Requirement(id=rid, location=node[0], product=node[1], date=max(d, self.start),
                                  qty=q, kind=r.kind, priority=r.priority,
                                  consumed_forecast=r.consumed if i == 0 else 0.0, past_due=d < self.start)
                self._add_req(node, req)
                ids.append(rid)
            if parts and r.kind == "forecast" and ids:
                st.forecasts.append((r.id, r.date, days, ids))
        for rc in self._rc_at.get(node, ()):
            if rc.confirmations:        # confirmed in several deliveries: each arrives on its own day
                for day, q in rc.expected_parts():
                    d = self._available(rc, day)
                    st.supplies.append(_Supply("receipt", rc.id, d, q, d, rc.scheduled, rc.sales_order))
            elif rc.expected_qty > EPS:   # a supplier who confirmed less than ordered: the plan counts what is confirmed
                d = self.receipt_date(rc)
                st.supplies.append(_Supply("receipt", rc.id, d, rc.expected_qty, d, rc.scheduled, rc.sales_order))
        # what the firm orders still draw from stock: components, or goods at a transfer's origin
        for rc, rv in self._rv_at.get(node, ()):
            kind = "transfer" if rv.location != rc.location else "dependent"
            self._add_req(node, Requirement(id=f"RV:{rc.id}:{rv.location}:{rv.product}", location=rv.location,
                                            product=rv.product, date=max(rv.date, self.start), qty=rv.qty,
                                            kind=kind, parent_order=rc.id, past_due=rv.date < self.start))
        st.reqs.extend(came)
        st.supplies.extend(brought)

    def _firm_load(self, rc) -> None:
        """A released production order still to finish occupies its machines like a planned order would: forward from
        its start date when that is today or later (a date the shop floor schedule set, or the planner), else backward
        from its due date (work already overdue lands in the first bucket)."""
        ps = self.ds.production_source_by_id.get(rc.source or "")
        if rc.kind.value != "production" or ps is None or ps.location != rc.location or ps.product != rc.product:
            return
        ps = ps.model_copy(update={"operations": [
            op.model_copy(update={"resource": rc.step_resources[op.seq]})
            if rc.step_resources.get(op.seq) in self.ds.resource_by_id else op for op in ps.operations]})
        try:
            if rc.start_date is not None and rc.start_date >= self.start:
                sch = schedule_make(self.ds, ps, rc.qty, start=rc.start_date)
            else:
                sch = schedule_make(self.ds, ps, rc.qty, available=self.receipt_date(rc))
        except NoWorkingTime as failure:
            self._exc("FIRM_NO_WORKING_TIME", "error", str(failure),
                      node=(rc.location, rc.product), order=rc.id)
            return
        who = (rc.id, rc.product, True)
        for w in sch.ops:
            if w.resource is None:
                continue
            self._load(rc.step_resources.get(w.seq, w.resource), w.start, w.end, w.machine_hours, who)
            if w.labor_resource and w.labor_hours > 0:
                self._load(w.labor_resource, w.start, w.end, w.labor_hours, who)
            for t in w.tools:
                self._load(t, w.start, w.end, w.machine_hours, who)

    def receipt_date(self, rc) -> date:
        """A firm receipt is available after goods-receipt processing, like a planned order; a purchase line the
        supplier confirmed arrives on the confirmed date."""
        return self._available(rc, rc.expected_date)

    def _available(self, rc, day: date) -> date:
        return max(gr_after(self.ds, rc.location, rc.product, day), self.start)

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
        st = self.state[node]
        st.reqs.append(req)
        if st.netted is not None and st.netted is not st.reqs:   # added while the node is netted (stock that expires)
            st.netted.append(req)
        self.req_by_id[req.id] = req
        if node != self._cur:
            self._hand(node, _REQ, req)

    def _add_supply(self, node: Node, sp: _Supply) -> None:
        self.state[node].supplies.append(sp)
        self._hand(node, _SUP, sp)

    def _hand(self, node: Node, op: int, what: Any) -> None:
        """Something the node being planned hands another node (a requirement, a co-product): that node is planned
        later, with it."""
        if node in self._done and self.kept is not None:
            raise _NotIncremental(f"{node} was handed something after it was planned")
        self.incoming[node].append((self._cur, what))
        if self._fx is not None:
            self._fx.append((op, node, what))

    def _add_order(self, order: PlannedOrder) -> None:
        self.orders.append(order)
        self.order_by_id[order.id] = order

    def _kpi(self, name: str, value: float) -> None:
        setattr(self.kpi, name, getattr(self.kpi, name) + value)
        if self._fx is not None:
            self._fx.append((_KPI, name, value))

    def _flow_load(self, loads: dict[str, list[float]], key: str, bi: int, qty: float) -> None:
        loads[key][bi] += qty
        if self._fx is not None:
            self._fx.append((_FLOW, loads is self.lane_load, key, bi, qty))

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
        direct = lp.direct_production and not self.is_customer(node)
        if direct:   # special procurement: made for each order that needs it, never from stock, lot-for-lot
            lp = st.lp = lp.model_copy(update={"strategy": Strategy.MTO, "safety_stock": SafetyStockPolicy()})
        if lp.strategy is Strategy.ASSEMBLY:
            self._consume_by_parents(node, st)
        self.safety_stock(node, st)
        mto = lp.strategy is Strategy.MTO
        onhand = 0.0 if self.is_customer(node) or direct else lp.on_hand
        disc = lp.discontinued_on if lp.follow_up and lp.discontinued_on else None
        if onhand > 0:
            st.supplies.insert(0, _Supply("on_hand", f"OH:{node[0]}:{node[1]}", self.start, onhand, self.start))
            self._expiry(node, st, onhand)
        if not self.is_customer(node):
            for os_ in lp.order_stock:
                if os_.qty > EPS:
                    st.supplies.insert(0, _Supply("on_hand", f"OS:{node[0]}:{node[1]}:{os_.order}", self.start,
                                                  os_.qty, self.start, segment=os_.order))
        netted = self._segments(node, st)
        if lp.mrp_type is MrpType.NONE:
            self._peg(node, st)
            return
        if lp.mrp_type is MrpType.DDMRP and not mto and disc is None and (b := self._buffer(node)) is not None:
            self._plan_ddmrp(node, st, b, onhand)
            self._peg(node, st)
            return
        reqs = sorted(netted, key=lambda r: (r.date, r.priority, r.id))
        receipts = sorted((s for s in st.supplies if s.kind in ("receipt", "co_product") and s.segment is None),
                          key=lambda s: s.date)
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
        # make to order still uses free stock first: what a full batch left over, or stock made before the product
        # became make-to-order, would otherwise sit (and, with a shelf life, spoil) while the next order is made new
        avail = onhand
        eoq_qty = None
        if lp.lot_sizing.policy is LotSizePolicy.EOQ:
            eoq_qty = rates.eoq_qty(self.ds, self.g, node, self._rate(node, st), self.val.unit_value.get(node, 0.0))
            if eoq_qty is None:
                self._exc("EOQ_FALLBACK", "info", "EOQ undefined (no ordering cost, value or demand): lot-for-lot used",
                          node=node)
        shelf = self.shelf(node)
        fresh = _Fresh(onhand) if shelf else None
        thresholds: dict[date, float] = {}
        # firming types 2 and 4 (S/4 §8.5): nothing new inside the fence; what is short there waits for the first
        # check beyond it, and is reported
        fence_end = self._fence_end(node, lp)
        hold = fence_end if fence_end is not None and lp.firming_type in (2, 4) else None
        held: list[tuple[date, float]] = []
        for d in dates:
            if fresh is not None:
                for last, q, what in fresh.expire(d):
                    avail -= q
                    self._lot_expires(node, st, last, q, what, shelf)
                fresh.add(d + timedelta(days=shelf), rec_on.get(d, 0.0), "the firm orders due then")
                fresh.use(req_on.get(d, 0.0))
            avail += rec_on.get(d, 0.0) - req_on.get(d, 0.0)
            if d not in checks:
                continue
            bi = self.b.index_of(d)
            ss = 0.0 if mto else (st.ss_by_bucket[bi] if 0 <= bi < len(self.b) else 0.0)
            threshold = max(ss, 0.0 if mto else target_at(st.targets, d))
            if lp.mrp_type is MrpType.REORDER_POINT and lp.reorder_point is not None:
                threshold = max(threshold, lp.reorder_point)
            thresholds[d] = threshold
            if disc is not None and d >= disc:
                threshold = 0.0           # discontinued: no buffer, no new supply; the follow-up takes over
                if avail < -EPS:
                    self._follow_up(node, st, d, -avail)
                    avail = 0.0
                continue
            if avail >= threshold - EPS:
                continue
            # reschedule in (S/4 rescheduling check): a firm receipt that lands no later than a new order could
            # is expedited to cover the shortage instead of being duplicated by a new order. How soon a new order
            # could land depends on its size (production time grows with it), so it is asked for the lot that would
            # replace the firm supply: sized as if none lay ahead (a period lot the receipt already covers would
            # otherwise shrink to the shortage and look faster than the order it duplicates)
            lot = self._lot(lp, mto, threshold - avail, d, avail, req_on, {}, eoq_qty, shelf)[0]
            pulled = self._reschedule_in(node, st, receipts, rec_on, d, threshold - avail, lot)
            avail += pulled
            if fresh is not None and pulled > EPS:
                fresh.add(d + timedelta(days=shelf), pulled, "the firm orders brought forward")
            if avail >= threshold - EPS:
                continue
            if hold is not None and d < hold:
                held.append((d, threshold - avail))
                continue
            shortage = threshold - avail
            qty, gap = self._lot(lp, mto, shortage, d, avail, req_on, rec_on, eoq_qty, shelf)
            # safety time (S/4 §8.1): the receipt is planned this many WORKING days early on the location's calendar,
            # so a Monday requirement with two days of safety time is due on Thursday, never on a closed Saturday
            need = (max(self.start, location_calendar(self.ds, node[0]).add_workdays(d, -lp.safety_time_days))
                    if lp.safety_time_days else d)
            ceiling = gap if lp.lot_sizing.policy is LotSizePolicy.MIN_MAX and not mto else None
            # what the order is for: requirements below zero first, then the buffer up to the threshold
            first = len(self.orders)
            created = self._supply(node, st, qty, need, shortage=shortage, ceiling=ceiling,
                                   below_zero=min(shortage, max(0.0, -avail)))
            avail += created
            if fresh is not None:
                for o in self.orders[first:]:   # a batch keeps from the day it is there
                    fresh.add(max(d, o.available_date) + timedelta(days=shelf), o.qty, o.id)
        if held:
            worst = max(q for _, q in held)
            self._exc("FENCE_SHORTAGE", "warning",
                      f"{worst:,.1f} short inside the planning time fence (to {hold.isoformat()}), first on "
                      f"{held[0][0].isoformat()}: firming type {lp.firming_type} plans no new order there. Firm one "
                      f"by hand or bring a firm order in; beyond the fence the plan covers it",
                      node=node, when=held[0][0], qty=worst)
        if disc is None:
            self._reschedule_out(node, st, thresholds, netted)
        self._peg(node, st)

    def _buffer(self, node: Node):
        """The DDMRP buffer of a node planned by MRP type ``ddmrp`` (None: not a stocking position)."""
        if self._buffers is None:
            from .ddbuffer import size_all
            only = {n for n in self.g.order if self.lp(n).mrp_type is MrpType.DDMRP}
            self._buffers = size_all(self.ds, self.g, self.flow, only=only)
        return self._buffers.get(node)

    def _plan_ddmrp(self, node: Node, st: _NodeState, b, onhand: float) -> None:
        """MRP type ``ddmrp`` (S/4 MRP type D1; Ptak & Smith, ch. 9): the buffer, not the net requirements, decides the
        orders. On every day the net flow position can change (a requirement falls due, a spike comes within the
        decoupled lead time, a bucket starts)

            NFP = on hand + open supply − requirements due by that day − spikes within the decoupled lead time

        and when NFP is at or under the top of yellow an order of TOG − NFP is placed that day, arriving a lead time
        later: supply follows the buffer, so one signal plans the item instead of a buffer advising beside an MRP that
        nets requirements. The red zone stands in for safety stock in the projection, so stock projected into red is
        reported; the buffer's state on the first day goes to the inbox (red: expedite, yellow: order now)."""
        inv = self.ds.inventory
        st.ss_by_bucket = [b.tor] * len(self.b)
        st.ss_note = (f"DDMRP buffer: red to {b.tor:,.1f}, yellow to {b.toy:,.1f}, green to {b.tog:,.1f} "
                      f"(ADU {b.adu:,.2f} a day over a decoupled lead time of {b.dlt:g} d)")
        reqs = sorted(st.reqs, key=lambda r: (r.date, r.priority, r.id))
        req_on: dict[date, float] = defaultdict(float)
        for r in reqs:
            req_on[r.date] += r.qty
        window = max(1, math.ceil(b.dlt - EPS))
        spikes = [(r.date, r.qty) for r in reqs if r.qty > inv.spike_factor * b.tor + EPS]
        checks = ({r.date for r in reqs} | {bk.start for bk in self.b}
                  | {d - timedelta(days=window - 1) for d, _ in spikes})
        checks = sorted(d for d in checks if self.start <= d < self.b.end)
        supply = onhand + sum(s.qty for s in st.supplies if s.kind in ("receipt", "co_product"))
        days = sorted(req_on)
        cum = list(accumulate(req_on[dd] for dd in days))
        first: tuple[float, float, list[str]] | None = None
        for d in checks:
            k = bisect.bisect_right(days, d)
            due = cum[k - 1] if k else 0.0     # due by d, what fell due before the start included
            nfp = supply - due - sum(q for dd, q in spikes if d < dd < d + timedelta(days=window))
            made: list[str] = []
            if nfp <= b.toy + EPS and (q := b.tog - nfp) > EPS:
                opt = self._choose(node, d, q)
                need = schedule(self.ds, opt, q, start=d).available_date if opt is not None else d
                k = len(self.orders)
                q = self._supply(node, st, q, need, shortage=q, below_zero=0.0)
                supply += q
                made = [o.id for o in self.orders[k:]]
            if first is None:
                first = (nfp, q if made else b.tog - nfp, made)
        if first is None:
            return
        nfp, q, made = first
        what = f" ({', '.join(made)})" if made else ""
        if nfp <= b.tor + EPS:
            self._exc("BUFFER_RED", "warning",
                      f"Buffer in red: the net flow position {nfp:,.1f} is at or under the top of red ({b.tor:,.1f}). "
                      f"Order {q:,.1f} today{what} and expedite the open supply", node=node, when=self.start, qty=q,
                      order=made[0] if made else None)
        elif nfp <= b.toy + EPS:
            self._exc("BUFFER_YELLOW", "warning",
                      f"Buffer in yellow: the net flow position {nfp:,.1f} is at or under the top of yellow "
                      f"({b.toy:,.1f}). Order {q:,.1f} today{what} to bring it back to the top of green ({b.tog:,.1f})",
                      node=node, when=self.start, qty=q, order=made[0] if made else None)

    def sales_order_of(self, r: Requirement) -> str | None:
        """The sales order a requirement serves: its own id for a sales order, and for what a delivery to a customer
        draws from the place that ships it, the sales order that delivery is for (one transfer, one order)."""
        if r.kind == "sales_order":
            return r.id.removeprefix("D:").split("~")[0]
        o = self.order_by_id.get(r.parent_order or "")
        if o is None or o.kind != "transfer":
            return None
        if o.sales_order is not None:
            return o.sales_order
        found = {self.sales_order_of(self.req_by_id[p.requirement_id]) for p in self._pegs_of.get(o.id, ())
                 if p.requirement_id in self.req_by_id}
        return found.pop() if len(found) == 1 else None

    def _consume_by_parents(self, node: Node, st: _NodeState) -> None:
        """Strategy 70 (S/4 planning at assembly level, §5.2): a forecast on an assembly builds it ahead of its parents'
        orders. What the parents need of it (the dependent requirements of their planned and firm orders) uses that
        forecast up, within the consumption windows, backward first, as a sales order uses up a forecast, so the
        assembly is planned once, not for its forecast and again for its parents. What no forecast in reach covers is
        planned on top; what is left of a forecast stays spread evenly over its working days."""
        deps = sorted((r.date, r.id, r.qty) for r in st.reqs
                      if r.kind == "dependent" and r.parent_order is not None and r.qty > EPS)
        if not deps or not st.forecasts:
            return
        by_id = {r.id: r for r in st.reqs}
        cap = {fid: sum(by_id[x].qty for x in ids if x in by_id) for fid, _, _, ids in st.forecasts}
        fcs = sorted(((fid, first, days) for fid, first, days, _ in st.forecasts), key=lambda f: (f[1], f[0]))
        lp = st.lp
        took = _consume(fcs, cap, [(d, q) for d, _, q in deps], lp.consumption_backward_days,
                        lp.consumption_forward_days)
        gone: set[str] = set()
        for fid, _, _, ids in st.forecasts:
            t = took.get(fid, 0.0)
            if t <= EPS or cap[fid] <= EPS:
                continue
            keep = max(0.0, 1.0 - t / cap[fid])
            for x in ids:
                req = by_id.get(x)
                if req is None:
                    continue
                req.qty *= keep
                if req.qty <= EPS:
                    gone.add(x)
            if ids[0] in by_id:
                by_id[ids[0]].consumed_forecast += t
        if gone:
            st.reqs[:] = [r for r in st.reqs if r.id not in gone]
            for x in gone:
                self.req_by_id.pop(x, None)

    def _segments(self, node: Node, st: _NodeState) -> list[Requirement]:
        """Sales-order stock and fixed pegging (S/4 §16.2 make-to-order segment, account assignment E): stock and firm
        orders held for a sales order go to that order alone, first, in date order, and are never counted for any
        other requirement. What they do not cover is netted with the rest; what the order no longer needs stays held
        and is reported, and one that arrives after its order is due is to be expedited (no other supply is planned in
        front of it: it is that order's). Returns the requirements the free supply is netted against."""
        held: dict[str, list[_Supply]] = defaultdict(list)
        for sp in st.supplies:
            if sp.segment is not None:
                held[sp.segment].append(sp)
        st.netted = list(st.reqs)
        if not held:
            return st.netted
        by_so: dict[str, list[Requirement]] = defaultdict(list)
        for r in st.reqs:
            if (so := self.sales_order_of(r)) in held:
                by_so[so].append(r)
        cut: dict[str, float] = defaultdict(float)
        for so, sups in sorted(held.items()):
            sups.sort(key=lambda x: (x.date, x.kind != "on_hand", x.id))
            left = [x.qty for x in sups]
            i = 0
            late: dict[str, tuple[_Supply, Requirement]] = {}
            for r in sorted(by_so.get(so, []), key=lambda r: (r.date, r.id)):
                need = r.qty
                while need > EPS and i < len(sups):
                    take = min(need, left[i])
                    if take > EPS:
                        st.fixed.append((sups[i], r.id, take))
                        cut[r.id] += take
                        left[i] -= take
                        need -= take
                        if sups[i].date > r.date and sups[i].id not in late:
                            late[sups[i].id] = (sups[i], r)
                    if left[i] <= EPS:
                        i += 1
            for sp, r in late.values():
                self._exc("RESCHEDULE_IN", "warning",
                          f"{sp.id}: arrives {sp.date.isoformat()} but {so}, the sales order it is held for, needs it "
                          f"{r.date.isoformat()}; expedite it by {(sp.date - r.date).days} d (it is that order's, so "
                          f"nothing else is planned for it)", node=node, order=sp.id, when=r.date, qty=sp.qty)
            spare = sum(left)
            if spare > EPS:
                what = ", ".join(dict.fromkeys(sp.id if sp.kind == "receipt" else "stock" for sp, q in
                                               zip(sups, left, strict=True) if q > EPS))
                self._exc("ORDER_STOCK_LEFT", "warning",
                          f"{spare:,.1f} held for {so} ({what}) that {so} no longer needs: no other order may use it. "
                          f"Move it to free stock, or change or cancel the order it came on",
                          node=node, when=self.start, qty=spare)
        out: list[Requirement] = []
        for r in st.reqs:
            q = r.qty - cut.get(r.id, 0.0)
            if q > EPS:
                out.append(r if q >= r.qty - EPS else r.model_copy(update={"qty": q}))
        st.netted = out
        return out

    def _reschedule_out(self, node: Node, st: _NodeState, thresholds: dict[date, float],
                        reqs: list[Requirement]) -> None:
        """The rescheduling check the other way (S/4 exceptions 15 and 20): a firm receipt the plan does not need on its
        date. Receipts are taken in date order; each is needed on the first checked date where the stock without it
        (and without the firm receipts after it) would fall below the safety stock, target or reorder point. Needed
        nowhere in the horizon: RECEIPT_NOT_NEEDED (cancel it, or pull it in instead of a new order); needed more than
        the rescheduling tolerance later: RESCHEDULE_OUT to that date. Advice only: the receipt keeps its date."""
        tolerance = self._tolerance(st.lp)
        firm = sorted((s for s in st.supplies if s.kind == "receipt" and s.segment is None), key=lambda s: (s.date, s.id))
        if not firm or not thresholds:
            return
        others = [s for s in st.supplies if s.kind != "receipt" and s.segment is None]
        out_req: dict[date, float] = defaultdict(float)
        for r in reqs:
            out_req[r.date] += r.qty
        checks = sorted(thresholds)
        for k, rc in enumerate(firm):
            inflow: dict[date, float] = defaultdict(float)
            for s in [*others, *firm[:k]]:
                inflow[s.date] += s.qty
            avail = 0.0
            needed: date | None = None
            for d in sorted(set(checks) | set(inflow) | set(out_req)):
                avail += inflow.get(d, 0.0) - out_req.get(d, 0.0)
                if d in thresholds and avail < thresholds[d] - EPS:
                    needed = d
                    break
            if needed is None:
                self._exc("RECEIPT_NOT_NEEDED", "warning",
                          f"{rc.id}: {rc.qty:,.1f} arrive {rc.date.isoformat()} but nothing needs them before the "
                          f"planning horizon ends: cancel or push it out (or pull it in in place of a new order)",
                          node=node, order=rc.id, when=rc.date, qty=rc.qty)
            elif (needed - rc.date).days > tolerance + EPS:
                self._exc("RESCHEDULE_OUT", "warning",
                          f"{rc.id}: arrives {rc.date.isoformat()} but is first needed {needed.isoformat()}; push it "
                          f"out by {(needed - rc.date).days} d", node=node, order=rc.id, when=needed, qty=rc.qty)

    def _expiry(self, node: Node, st: _NodeState, onhand: float) -> None:
        """Batch stock the requirements will not use before it expires is gone the day after (R15): a requirement
        of its own, so the plan replaces it instead of counting on it."""
        lots = self.expiring.get(node)
        if not lots:
            return
        from ..actuals.lots import spoilage
        used: dict[date, float] = defaultdict(float)
        for r in st.reqs:
            used[r.date] += r.qty
        for day, q, batch in spoilage(lots, onhand, used):
            if day >= self.b.end:
                continue
            day = max(day, self.start)
            self._add_req(node, Requirement(id=f"EXP:{node[0]}:{node[1]}:{batch}", location=node[0], product=node[1],
                                            date=day, qty=q, kind="expiry", priority=9))
            self._exc("STOCK_EXPIRES", "warning", f"{q:,.1f} of batch {batch} expire unused on "
                      f"{(day - timedelta(days=1)).isoformat()}", node=node, when=day, qty=q)

    def _follow_up(self, node: Node, st: _NodeState, d: date, qty: float) -> None:
        """A discontinued product's requirement its stock no longer covers goes to its follow-up at the same place
        (≈ S/4 discontinuation with a follow-up material): a requirement there, and a supply here that it covers."""
        follow = st.lp.follow_up
        fnode = (node[0], follow or "")
        if fnode not in self.state:
            self._exc("NO_VALID_SOURCE", "error", f"Discontinued; its follow-up {follow} is not planned here",
                      node=node, when=d, qty=qty)
            return
        n = sum(1 for s in st.supplies if s.kind == "follow_up") + 1
        rid = f"FU:{node[0]}:{node[1]}:{n}"
        self._add_req(fnode, Requirement(id=rid, location=node[0], product=follow, date=d, qty=qty, kind="dependent"))
        st.supplies.append(_Supply("follow_up", rid, d, qty, d))
        if n == 1:
            self._exc("FOLLOW_UP", "info", f"Discontinued from {st.lp.discontinued_on.isoformat()}: {follow} takes "
                      f"over from {d.isoformat()}, once its stock is used up", node=node, when=d, qty=qty)

    def _lot_expires(self, node: Node, st: _NodeState, last: date, qty: float, what: str, shelf: int) -> None:
        """A lot the plan made or expects that the requirements will not use up before its last day: what is left is
        gone the day after, a requirement of its own the plan then covers again."""
        day = last + timedelta(days=1)
        if day >= self.b.end:
            return
        n = sum(1 for r in st.reqs if r.kind == "expiry" and r.id.startswith(f"EXP:{node[0]}:{node[1]}:"))
        self._add_req(node, Requirement(id=f"EXP:{node[0]}:{node[1]}:+{n + 1}", location=node[0], product=node[1],
                                        date=day, qty=qty, kind="expiry", priority=9))
        order = what if what in self.order_by_id else None
        self._exc("LOT_EXPIRES", "warning",
                  f"{qty:,.1f} of {what} would expire unused on {last.isoformat()}: the lot is more than "
                  f"{shelf} days' use (a smaller fixed batch, minimum or rounding avoids it)",
                  node=node, order=order, when=day, qty=qty)

    @property
    def expiring(self) -> dict[Node, list[tuple[date, float, str]]]:
        if self._expiring is None:
            from ..actuals.lots import expiring
            self._expiring = expiring(self.ds, self.b.end)
        return self._expiring

    def _lot(self, lp: LocationProduct, mto: bool, shortage: float, d: date, avail: float, req_on: dict[date, float],
             rec_on: dict[date, float], eoq_qty: float | None, shelf: int | None = None) -> tuple[float, float | None]:
        """The lot a shortage on ``d`` is ordered in, and the room left to the maximum stock. With a shelf life, a lot
        that is worked out (a period's need, an economic quantity, up to the maximum stock) covers no more than the
        requirements up to its last day (R15); a fixed batch stays as it is, and what it leaves is planned to expire."""
        ls = lp.lot_sizing
        window = 0.0
        keeps = d + timedelta(days=shelf + 1) if shelf else None
        if ls.policy is LotSizePolicy.POQ and not mto:
            bi = self.b.index_of(d)
            end_idx = min(bi + (ls.periods or 1), len(self.b))
            we = self.b[end_idx].start if end_idx < len(self.b) else self.b.end
            if keeps is not None:
                we = min(we, keeps)
            window = max(0.0, sum(q for dd, q in req_on.items() if d < dd < we)
                         - sum(q for dd, q in rec_on.items() if d < dd < we))
        elif ls.policy in DYNAMIC_LOTS and not mto:
            window = self._dynamic_window(lp, d, shortage, req_on, rec_on, keeps)
        gap = (lp.max_stock - avail) if lp.max_stock is not None else None
        if mto:
            return shortage, gap
        q = base_lot(ls, shortage, window_requirements=window, max_stock_gap=gap, eoq_qty=eoq_qty)
        if keeps is not None and ls.policy in (LotSizePolicy.EOQ, LotSizePolicy.MIN_MAX) and q > shortage + EPS:
            usable = max(0.0, sum(qq for dd, qq in req_on.items() if d < dd < keeps)
                         - sum(qq for dd, qq in rec_on.items() if d < dd < keeps))
            q = max(shortage, min(q, shortage + usable))
        return q, gap

    def _dynamic_window(self, lp: LocationProduct, d: date, shortage: float, req_on: dict[date, float],
                        rec_on: dict[date, float], keeps: date | None) -> float:
        """What a lot ordered for a shortage on ``d`` also covers under part-period balancing, least unit cost or
        Groff (S/4 guide §8.3): the net requirements of the periods the rule joins, each held from ``d`` to its own
        date at the product's carrying rate, against the cost of one order. Within the shelf life, as POQ."""
        node = (lp.location, lp.product)
        if node not in self._lot_costs:
            s = rates.ordering_cost(self.ds, lp, self.g.options.get(node) or [])
            h = self.val.unit_value.get(node, 0.0) * rates.holding_rate(self.ds, lp) / 365.0
            self._lot_costs[node] = (s, h)
            if s <= 0 or h <= 0:
                self._exc("EOQ_FALLBACK", "info", f"{lp.lot_sizing.policy.value} lot size undefined (no ordering cost "
                          "or value): lot-for-lot used", node=node)
        s, h = self._lot_costs[node]
        bi = self.b.index_of(d)
        needs: list[tuple[float, float]] = []
        for i in range(max(bi, 0), len(self.b)):
            lo, hi = (d, self.b[i].end) if i == bi else (self.b[i].start, self.b[i].end)
            if keeps is not None:
                hi = min(hi, keeps)
            if hi <= lo:
                break
            got = [(dd, q) for dd, q in req_on.items() if (d < dd if i == bi else lo <= dd) and dd < hi]
            came = sum(q for dd, q in rec_on.items() if (d < dd if i == bi else lo <= dd) and dd < hi)
            q = max(0.0, sum(x for _, x in got) - came)
            part_days = sum(x * (dd - d).days for dd, x in got)
            needs.append((q + (shortage if i == bi else 0.0),
                          part_days / sum(x for _, x in got) if got and i != bi else float((lo - d).days)))
        if not needs:
            return 0.0
        n = dynamic_periods(lp.lot_sizing.policy, needs, s, h, float(self.b[max(bi, 0)].days))
        return needs[0][0] - shortage + sum(q for q, _ in needs[1:n])

    def _fence_end(self, node: Node, lp: LocationProduct) -> date | None:
        return fence_end(self.ds, node, lp)

    def _horizon(self, lp: LocationProduct) -> float:
        """Working days after a shortage within which a later firm order is brought in rather than ordered again: the
        product's (or its MRP group's), else the company's."""
        h = lp.rescheduling_horizon_days
        return self.s.rescheduling_horizon_days if h is None else h

    def _tolerance(self, lp: LocationProduct) -> float:
        t = lp.reschedule_out_tolerance_days
        return self.s.reschedule_out_tolerance_days if t is None else t

    def _earliest_new(self, node: Node, st: _NodeState, need: date, qty: float) -> date | None:
        """When a new order for ``need`` would be available: on time if its backward-scheduled start is not in
        the past (nor inside the fence), else its forward-scheduled date from today (or the fence end)."""
        excluded: set[tuple[str, str]] = set()
        fence_end = self._fence_end(node, st.lp)
        target = max(need, fence_end) if fence_end is not None else need
        while (opt := self._choose(node, need, qty, excluded)) is not None:
            try:
                sch = schedule(self.ds, opt, qty, available=target)
                if sch.start_date >= self.start:
                    return target
                return schedule(self.ds, opt, qty, start=self.start).available_date
            except NoWorkingTime:
                excluded.add((opt.kind, opt.source_id))
        return None

    def _reschedule_in(self, node: Node, st: _NodeState, receipts: list[_Supply], rec_on: dict[date, float],
                       d: date, short: float, lot: float) -> float:
        """Pull later firm receipts forward to ``d`` (for netting) instead of planning new supply beside them: those
        due within the rescheduling horizon (S/4 §8.1: reschedule in first, new supply only beyond it), and later ones
        while a new order of ``lot`` could not arrive before them either. Their physical date is kept, so the
        projection and the pegging still show the delay.

        A receipt dated by the detailed schedule is always counted where it is needed: the schedule already put it
        as early as the machines allow, and a new order planned at unlimited capacity would only look faster."""
        got = 0.0
        for s in receipts:
            if got >= short - EPS:
                return got
            if not s.fixed or s.date <= d:
                continue
            rec_on[s.date] -= s.qty
            self._exc("SCHEDULE_LATE", "warning",
                      f"{s.id}: the schedule finishes it for {s.date.isoformat()}, {(s.date - d).days} d after it is "
                      f"needed on {d.isoformat()}", node=node, order=s.id, when=d, qty=s.qty)
            s.date = d
            got += s.qty
        if got >= short - EPS:
            return got
        if (horizon := self._horizon(st.lp)) > EPS:
            reach = location_calendar(self.ds, node[0]).add_workdays(d, horizon)
            for s in receipts:
                if got >= short - EPS:
                    return got
                if s.kind != "receipt" or s.date <= d or s.date > reach:
                    continue
                rec_on[s.date] -= s.qty
                self._exc("RESCHEDULE_IN", "warning",
                          f"{s.id}: arrives {s.date.isoformat()} but is needed {d.isoformat()}; expedite it by "
                          f"{(s.date - d).days} d (it is due within the {horizon:g}-working-day rescheduling horizon, "
                          f"so it is brought in rather than ordered again)", node=node, order=s.id, when=d, qty=s.qty)
                s.date = d
                got += s.qty
        if got >= short - EPS:
            return got
        earliest = self._earliest_new(node, st, d, lot)
        if earliest is None or earliest <= d:
            return got
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
                ceiling: float | None = None, below_zero: float | None = None,
                excluded: set[tuple[str, str]] | None = None) -> float:
        excluded = set(excluded or ())
        opt = self._choose(node, need, qty, excluded)
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
        whole = [1.0] if self.ds.whole(node[1]) else []
        batch: list[float | None] = []
        if opt.kind == "make" and ps.full_batches and (m := batch_multiple(ps)):
            # whole batches; a product counted in each takes the whole units a batch holds
            batch = [math.floor(m + 1e-9) if whole and m >= 1 else m]
        rounds += batch + whole   # a product counted in each is never planned as 25.9 tins
        if st.lp.strategy is Strategy.MTO:
            lots = apply_modifiers(qty, mins=[], roundings=batch + whole, maxes=maxes)
        elif ls.policy is LotSizePolicy.FIXED and ls.fixed_qty:
            # fixed lot size (S/4 FX): the fixed lot is repeated until the shortage is covered, one order per lot (a
            # shortage of 120 in lots of 50 is three orders of 50, not one of 150: each lot is a batch, a setup and
            # an order cost). The minimums and rounding apply to the lot itself
            one = apply_modifiers(ls.fixed_qty, mins=mins, roundings=rounds, maxes=maxes)
            n = max(1, math.ceil(qty / sum(one) - 1e-9))
            lots = one * n
        else:
            lots = apply_modifiers(qty, mins=mins, roundings=rounds, maxes=maxes)
            step = max((r for r in rounds if r), default=None)
            if ceiling is not None and step and sum(lots) > ceiling + EPS:
                # replenish-to-max: round DOWN when that still covers the shortage and the minimums
                down = math.floor(ceiling / step + 1e-9) * step
                if down >= max([shortage or 0.0, *mins]) - EPS:
                    # split by the maximum in whole rounding steps: a lot of 35 when lots come in tens is no lot
                    lots = apply_modifiers(down, mins=[], roundings=[step], maxes=maxes)
        total = 0.0
        req_left = qty if below_zero is None else below_zero
        buf_left = 0.0 if shortage is None else max(0.0, shortage - req_left)
        for lot in lots:
            try:
                made = self._within_limits(node, st, opt, lot, need)
            except NoWorkingTime as failure:
                self._exc("SOURCE_NO_WORKING_TIME", "warning", f"{opt.source_id}: {failure}",
                          node=node, when=need, qty=lot)
                excluded.add((opt.kind, opt.source_id))
                remaining = max(0.0, qty - total)
                if remaining <= EPS:
                    return total
                return total + self._supply(node, st, remaining, need,
                                            shortage=None if shortage is None else max(0.0, shortage - total),
                                            ceiling=None if ceiling is None else max(0.0, ceiling - total),
                                            below_zero=req_left, excluded=excluded)
            for o in made:
                q = o.qty
                for_req = min(q, req_left)
                o.for_buffer = min(q - for_req, buf_left)
                o.for_lot_size = max(0.0, q - for_req - o.for_buffer)
                req_left -= for_req
                buf_left -= o.for_buffer
                self.quota_alloc[(node, o.source_id)] += q
                total += q
        return total

    # ------------------------------------------------------------------ supplier and lane capacity
    def _limit(self, opt: SupplyOption) -> float | None:
        """Units a week the source can supply (supplier capacity) or the lane can carry; None: no limit."""
        if opt.kind == "buy":
            return self.ds.purchasing_source_by_id[opt.source_id].capacity_per_week
        if opt.kind == "transfer":
            return self.ds.lane_by_id[opt.source_id].planning_mode.capacity_units_per_week
        return None

    def _room(self, opt: SupplyOption, qty: float, need: date) -> tuple[float, bool]:
        """What is left of the weekly limit in the bucket an order needed on ``need`` would ship in, and whether
        that order could still start today or later."""
        cap = self._limit(opt)
        sch = schedule(self.ds, opt, qty, available=need)
        ok = sch.start_date >= self.start
        if cap is None:
            return math.inf, ok
        if not ok:
            sch = schedule(self.ds, opt, qty, start=self.start)
        day = sch.start_date if opt.kind == "transfer" else (sch.ship_date or sch.start_date)
        bi = self.b.index_of(day)
        if not 0 <= bi < len(self.b):
            return math.inf, ok
        load = (self.lane_load[opt.source_id] if opt.kind == "transfer" else self.supplier_load[opt.source_id])[bi]
        return max(0.0, cap * self.b[bi].days / 7.0 - load), ok

    def _piece(self, node: Node, opt: SupplyOption, room: float, left: float) -> float:
        """How much of ``left`` an order from ``opt`` may take within ``room``: whole packs, at least the minimum."""
        take = min(left, room)
        if opt.kind == "buy":
            pu = self.ds.purchasing_source_by_id[opt.source_id]
            if pu.rounding_qty and take < left - EPS:
                take = math.floor(take / pu.rounding_qty + 1e-9) * pu.rounding_qty
            if take < pu.moq - EPS:
                return 0.0
        if self.ds.whole(node[1]) and take < left - EPS:
            take = math.floor(take + 1e-9)
        return take if take > EPS else 0.0

    def _within_limits(self, node: Node, st: _NodeState, opt: SupplyOption, qty: float, need: date) -> list[PlannedOrder]:
        """Create the order for ``qty``. When capacity-constrained planning is on and the supplier or lane has a weekly
        limit, what does not fit that week goes to the node's other valid sources, then to earlier weeks of the same
        source (arriving early, held as stock); only what fits nowhere is ordered over the limit (and flagged)."""
        if not self.s.capacity_constrained or self._limit(opt) is None:
            self._create_order(node, st, opt, qty, need)
            return [self.orders[-1]]
        made: list[PlannedOrder] = []
        left = qty

        def order(o: SupplyOption, q: float, on: date) -> None:
            nonlocal left
            self._create_order(node, st, o, q, on)
            made.append(self.orders[-1])
            left -= q

        room, _ = self._room(opt, left, need)
        if (q := self._piece(node, opt, room, left)) > 0:
            order(opt, q, need)
        others = [o for o in self.g.options.get(node, []) if o.source_id != opt.source_id and self._valid(o, need)
                  and not (o.kind == "buy" and self.ds.purchasing_source_by_id[o.source_id].blocked)]
        for o in others:
            if left <= EPS:
                break
            room, _ = self._room(o, left, need)
            if (q := self._piece(node, o, room, left)) > 0:
                order(o, q, need)
        on = need
        for _ in range(26):
            if left <= EPS:
                break
            on -= timedelta(days=7)
            room, ok = self._room(opt, left, on)
            if not ok:
                break
            if (q := self._piece(node, opt, room, left)) > 0:
                order(opt, q, on)
        if left > EPS:
            order(opt, left, need)
        if len(made) > 1:
            what = "supplier" if opt.kind == "buy" else "lane"
            self._exc("SUPPLY_SPLIT", "info",
                      f"{qty:,.0f} needed {need.isoformat()} is over the {what} capacity of {opt.source_id}: split into "
                      + ", ".join(f"{o.id} {o.qty:,.0f} from {o.source_id}"
                                  + (f" arriving {o.available_date.isoformat()}" if o.need_date != need else "")
                                  for o in made), node=node, when=need, qty=qty)
        return made

    def _valid(self, opt: SupplyOption, d: date) -> bool:
        if opt.kind == "make":
            src = self.ds.production_source_by_id[opt.source_id]
        elif opt.kind == "buy":
            src = self.ds.purchasing_source_by_id[opt.source_id]
        else:
            return True
        return (src.valid_from is None or src.valid_from <= d) and (src.valid_to is None or src.valid_to >= d)

    def _choose(self, node: Node, need: date, qty: float,
                excluded: set[tuple[str, str]] | None = None) -> SupplyOption | None:
        valid = [o for o in self.g.options.get(node, [])
                 if self._valid(o, need) and (o.kind, o.source_id) not in (excluded or ())]
        if not valid:
            return None
        quota = [o for o in valid if o.quota]
        if quota:
            total = sum(o.quota for o in quota)
            return min(quota, key=lambda o: ((self.quota_alloc[(node, o.source_id)] + qty) / (o.quota / total),
                                             o.priority, o.source_id))
        if valid[0].kind == "buy":   # S/4 order: quota arrangement, then the source list's fixed source, then priority
            fixed = [o for o in valid if o.kind == "buy" and self.ds.purchasing_source_by_id[o.source_id].fixed]
            if fixed:
                return min(fixed, key=lambda o: (o.priority, o.source_id))
        return valid[0]

    # ------------------------------------------------------------------ orders
    def _next_id(self, kind: str, node: Node) -> str:
        """A planned order's number: the product at its place (by its place in the planning order), then the orders
        of that kind made there, so that a node planned as before keeps its numbers whatever changes elsewhere."""
        self.counters[(node, kind)] += 1
        return f"{_PREFIX[kind]}-{self._node_no[node]:04d}-{self.counters[(node, kind)]:02d}"

    def _create_order(self, node: Node, st: _NodeState, opt: SupplyOption, qty: float, need: date) -> None:
        ds = self.ds
        target = need
        fence_end = self._fence_end(node, st.lp)
        fenced = fence_end is not None and need < fence_end
        if fenced:
            target = fence_end
        sch: Schedule = schedule(ds, opt, qty, available=target)
        past = sch.start_date < self.start
        wanted = sch.start_date if past else None
        if past:
            sch = schedule(ds, opt, qty, start=self.start)
        placed: dict[int, str] | None = None
        base_avail = sch.available_date
        if opt.kind == "make" and self.s.capacity_constrained:
            sch, placed = self._fit(opt, qty, target, sch)
            past = past and sch.start_date <= self.start
        oid = self._next_id(opt.kind, node)
        loc, prod = node
        origin = None
        if opt.kind == "transfer":
            origin = ds.lane_by_id[opt.source_id].origin
        elif opt.kind == "buy":
            origin = ds.purchasing_source_by_id[opt.source_id].supplier
        order = PlannedOrder(id=oid, kind=opt.kind, location=loc, product=prod, qty=qty, source_id=opt.source_id,
                             origin=origin, need_date=need, start_date=sch.start_date, due_date=sch.due_date,
                             available_date=sch.available_date, start_in_past=past, fence_shifted=fenced,
                             wanted_start=wanted if past else None)
        if opt.kind == "make":
            order.step_resources = {w.seq: w.resource for w in sch.ops
                                    if w.resource and w.resource != self._primary(opt.source_id, w.seq)}
        if placed is not None:
            order.capacity_shift_days = (sch.available_date - base_avail).days
            order.step_resources = {seq: r for seq, r in placed.items() if r != self._primary(opt.source_id, seq)}
            order.overtime_hours = {r: round(h, 4) for r, h in self._ot_used.items() if h > 1e-9}
        self._cost(order, opt, qty)
        if order.overtime_hours:
            ot_cost = sum(h * ds.resource_by_id[r].overtime_cost_per_hour for r, h in order.overtime_hours.items())
            order.costs["overtime"] = ot_cost
            order.total_cost += ot_cost
            order.unit_cost = order.total_cost / qty if qty > 0 else 0.0
            self._kpi("production_cost", ot_cost)
            self._exc("OVERTIME_PLANNED", "info", f"{oid} fits with "
                      + ", ".join(f"{h:,.1f} h overtime on {r}" for r, h in order.overtime_hours.items())
                      + (f" (costing {ot_cost:,.0f})" if ot_cost > 0 else ""), node=node, order=oid, when=need, qty=qty)
        self._add_order(order)
        st.supplies.append(_Supply("order", oid, need, qty, sch.available_date))
        if past:
            late = (sch.available_date - need).days
            self._exc("START_IN_PAST", "warning",
                      f"{order.kind} {oid}: start would be before today; earliest availability "
                      f"{sch.available_date.isoformat()} ({late} d after need)", node=node, order=oid, when=need, qty=qty)
        if placed is not None:
            self._capacity_notes(order, sch, base_avail, need, node)
        if fenced:
            self._exc("FENCE_SHIFT", "info", f"{oid} moved to the planning time fence end {fence_end.isoformat()}",
                      node=node, order=oid, when=need, qty=qty)
        # explode
        if opt.kind == "make":
            ps = ds.production_source_by_id[opt.source_id]
            # the BOM as it stands on the day production starts (engineering change), phantoms passed through
            prod_start = sch.ops[0].start if sch.ops else sch.start_date
            for n in needs(ds, ps, prod_start, qty=qty):
                cq = n.qty(qty)
                if cq <= EPS:
                    continue
                cd = max(self.start, (sch.component_dates or {}).get(n.product, sch.start_date))
                at = n.location or loc     # withdrawn from another plant: its stock, no transfer
                req = Requirement(id=f"R:{oid}:{n.product}", location=at, product=n.product, date=cd, qty=cq,
                                  kind="dependent" if at == loc else "transfer", parent_order=oid)
                self._add_dependent((at, n.product), req, oid)
            for co, cq in co_output(ps, qty):
                if (loc, co) in self.state and cq > EPS:
                    self._add_supply((loc, co), _Supply("co_product", oid, sch.available_date, cq, sch.available_date))
            who = (oid, prod, False)
            for w in sch.ops:
                if w.resource is None:
                    continue   # done outside by a supplier
                self._load((placed or {}).get(w.seq, w.resource), w.start, w.end, w.machine_hours, who)
                if w.labor_resource and w.labor_hours > 0:
                    self._load(w.labor_resource, w.start, w.end, w.labor_hours, who)
                for t in w.tools:
                    self._load(t, w.start, w.end, w.machine_hours, who)
        elif opt.kind == "transfer":
            ln = ds.lane_by_id[opt.source_id]
            req = Requirement(id=f"T:{oid}", location=ln.origin, product=prod, date=max(self.start, sch.start_date),
                              qty=qty, kind="transfer", parent_order=oid)
            self._add_dependent((ln.origin, prod), req, oid)
            bi = self.b.index_of(sch.start_date)
            if 0 <= bi < len(self.b):
                self._flow_load(self.lane_load, ln.id, bi, qty)
        else:
            bi = self.b.index_of(sch.ship_date or sch.start_date)
            if 0 <= bi < len(self.b):
                self._flow_load(self.supplier_load, opt.source_id, bi, qty)

    def _add_dependent(self, node: Node, req: Requirement, parent: str) -> None:
        if node not in self.state:  # cannot happen for an acyclic, validated graph
            raise RuntimeError(f"requirement for unplanned node {node}")
        self._add_req(node, req)
        self.order_inputs[parent].append(req.id)
        if self._fx is not None:
            self._fx.append((_INPUT, parent, req.id))

    def _spread(self, resource: str, start: date, end: date, hours: float) -> list[tuple[date, float]]:
        """An operation's hours spread evenly over the working days of its window."""
        if hours <= 0:
            return []
        cal = resource_calendar(self.ds, resource)
        days = []
        d = start
        while d < end:
            if cal.is_workday(d):
                days.append(d)
            d += timedelta(days=1)
        if not days:
            days = [start]
        return [(d, hours / len(days)) for d in days]

    def _load(self, resource: str, start: date, end: date, hours: float, owner: tuple[str, str, bool]) -> None:
        spread = self._spread(resource, start, end, hours)
        self._add_load(resource, owner, spread)
        if self._fx is not None:
            self._fx.append((_LOAD, resource, owner, spread))

    def _add_load(self, resource: str, owner: tuple[str, str, bool], spread: list[tuple[date, float]]) -> None:
        by = self.res_orders[resource].setdefault(owner, defaultdict(float))
        for d, h in spread:
            self.res_daily[resource][d] += h
            by[d] += h

    # ------------------------------------------------------------------ capacity-constrained planning
    def _cap(self, resource: str, d: date) -> float:
        key = (resource, d)
        if key not in self._caps:
            r = self.ds.resource_by_id[resource]
            self._caps[key] = day_capacity(r, resource_calendar(self.ds, resource), d,
                                           self.ds.scheduling.day_start_hour).productive_hours
        return self._caps[key]

    def _primary(self, source_id: str, seq: int) -> str | None:
        ps = self.ds.production_source_by_id[source_id]
        return next((op.resource for op in ps.operations if op.seq == seq), None)

    def _ot(self, resource: str, d: date) -> float:
        """Overtime all units of a machine may add on ``d`` (none on a day it does not work)."""
        r = self.ds.resource_by_id[resource]
        if r.overtime_hours_per_day <= 0 or self._cap(resource, d) <= 0:
            return 0.0
        return r.overtime_hours_per_day * day_capacity(r, resource_calendar(self.ds, resource), d,
                                                       self.ds.scheduling.day_start_hour).units

    def _placement(self, opt: SupplyOption, sch: Schedule, overtime: bool = False) -> dict[int, str] | None:
        """The machine each step runs on so every finite machine and labour pool stays within its daily capacity
        (the step's own machine first, then its alternatives in order), or None when a step fits nowhere. With
        ``overtime``, a day's capacity includes the machine's overtime, and ``self._ot_used`` says how much of it the
        order takes, per machine."""
        ps = self.ds.production_source_by_id[opt.source_id]
        ops = {op.seq: op for op in ps.operations}
        extra: dict[tuple[str, date], float] = defaultdict(float)
        choice: dict[int, str] = {}
        self._ot_used: dict[str, float] = {}

        def cap(rid: str, d: date) -> float:
            return self._cap(rid, d) + (self._ot(rid, d) if overtime else 0.0)

        def fits(rid: str, spread: list[tuple[date, float]]) -> bool:
            if not self.ds.resource_by_id[rid].finite:
                return True
            return all(self.res_daily[rid].get(d, 0.0) + extra[(rid, d)] + h <= cap(rid, d) + 1e-6
                       for d, h in spread)

        def take(rid: str, spread: list[tuple[date, float]]) -> None:
            for d, h in spread:
                before = self.res_daily[rid].get(d, 0.0) + extra[(rid, d)]
                if overtime:
                    c = self._cap(rid, d)
                    over = max(0.0, before + h - c) - max(0.0, before - c)
                    if over > 1e-9:
                        self._ot_used[rid] = self._ot_used.get(rid, 0.0) + over
                extra[(rid, d)] += h

        for w in sch.ops:
            if w.resource is None:
                continue
            got = None
            for rid in [w.resource, *ops[w.seq].alternatives]:
                if rid not in self.ds.resource_by_id:
                    continue
                spread = self._spread(rid, w.start, w.end, w.machine_hours)
                if fits(rid, spread):
                    got = rid
                    break
            if got is None:
                return None
            if w.labor_resource and w.labor_hours > 0 and w.labor_resource in self.ds.resource_by_id:
                lab = self._spread(w.labor_resource, w.start, w.end, w.labor_hours)
                if not fits(w.labor_resource, lab):
                    return None
                take(w.labor_resource, lab)
            for t in w.tools:
                if t not in self.ds.resource_by_id:
                    continue
                held = self._spread(t, w.start, w.end, w.machine_hours)
                if not fits(t, held):
                    return None
                take(t, held)
            take(got, spread)
            choice[w.seq] = got
        return choice

    def _fit(self, opt: SupplyOption, qty: float, target: date, sch: Schedule) -> tuple[Schedule, dict[int, str] | None]:
        """Where a make order fits the machines: as planned; else, by the levelling direction, finishing a day earlier
        at a time (never starting before today, at most ``capacity_max_early_days``) or a day later at a time (up to a
        month past the horizon), the other way round when that finds nothing. None: it fits nowhere, and stays as
        planned (the capacity check reports the overload)."""
        got = self._placement(opt, sch)
        if got is not None:
            return sch, got
        if self.s.capacity_overtime:          # overtime on the day it is planned, before moving it
            got = self._placement(opt, sch, overtime=True)
            if got is not None:
                return sch, got
        ways = (self._earlier, self._later) if self.s.capacity_direction == "earlier" else (self._later, self._earlier)
        for ot in ([False, True] if self.s.capacity_overtime else [False]):
            for way in ways:
                found = way(opt, qty, target, sch, ot)
                if found is not None:
                    return found
        return sch, None

    def _earlier(self, opt: SupplyOption, qty: float, target: date, sch: Schedule, ot: bool = False):
        ds = self.ds
        cal = location_calendar(ds, opt.node[0])
        limit = self.s.capacity_max_early_days
        if sch.start_date <= self.start:
            return None
        d = min(target, sch.available_date)
        while True:
            d -= timedelta(days=1)
            if limit is not None and (sch.available_date - d).days > limit:
                return None
            s = schedule(ds, opt, qty, available=d)
            if s.start_date < self.start:
                return None
            if not cal.is_workday(s.start_date):
                continue
            got = self._placement(opt, s, ot)
            if got is not None:
                return s, got

    def _later(self, opt: SupplyOption, qty: float, target: date, sch: Schedule, ot: bool = False):
        ds = self.ds
        cal = location_calendar(ds, opt.node[0])
        last = self.b.end + timedelta(days=31)
        d = sch.start_date
        while True:
            d += timedelta(days=1)
            if not cal.is_workday(d):
                continue
            s = schedule(ds, opt, qty, start=d)
            if s.available_date > last:
                return None
            got = self._placement(opt, s, ot)
            if got is not None:
                return s, got

    def _capacity_notes(self, order: PlannedOrder, sch: Schedule, base_avail: date, need: date, node: Node) -> None:
        moved = (sch.available_date - base_avail).days
        oid = order.id
        if moved < 0:
            self._exc("CAPACITY_EARLIER", "info",
                      f"{oid} starts {sch.start_date.isoformat()}, {-moved} d earlier than it would, to fit the machines",
                      node=node, order=oid, when=need, qty=order.qty)
        elif moved > 0:
            late = (sch.available_date - need).days
            self._exc("CAPACITY_LATE", "warning" if late > 0 else "info",
                      f"{oid} fits the machines only {moved} d later: available {sch.available_date.isoformat()}"
                      + (f", {late} d after it is needed" if late > 0 else ""),
                      node=node, order=oid, when=need, qty=order.qty)
        for seq, rid in order.step_resources.items():
            self._exc("ALTERNATIVE_MACHINE", "info",
                      f"{oid} step {seq} runs on {rid} instead of {self._primary(order.source_id, seq)}, which is full",
                      node=node, order=oid, resource=rid, when=need, qty=order.qty)

    def _cost(self, order: PlannedOrder, opt: SupplyOption, qty: float) -> None:
        ds = self.ds
        total = 0.0
        if opt.kind == "buy":
            pu = ds.purchasing_source_by_id[opt.source_id]
            # a contract valid on the order day prices it as the requisition will be (N131), else the info record
            deal = costing.contract_for(ds, pu.supplier, pu.location, pu.product, order.start_date, ds.price_currency(pu))
            base = deal[1] if deal else pu.price_for(qty)
            price = base * costing.fx(ds, ds.price_currency(pu)) * (1.0 + pu.duty_rate)
            lane = supplier_lane(ds, pu.supplier, pu.location, pu.product)
            freight = 0.0
            if lane:
                mode = lane.planning_mode
                order.shipments = costing.shipments_needed(ds, mode, pu.product, qty)
                freight = qty * costing.freight_per_unit(ds, mode, pu.product) + order.shipments * mode.cost_per_shipment
            hand = qty * costing.handling(ds, pu.location)
            self._kpi("purchase_cost", qty * price)
            self._kpi("transport_cost", freight)
            self._kpi("ordering_cost", pu.ordering_cost)
            self._kpi("handling_cost", hand)
            total = qty * price + freight + pu.ordering_cost + hand
            order.costs = {"purchase": qty * price, "transport": freight, "ordering": pu.ordering_cost, "handling": hand}
        elif opt.kind == "make":
            conv, setup = costing.production_order_cost(ds, opt.source_id, qty, order.step_resources)
            self._kpi("production_cost", conv)
            self._kpi("setup_cost", setup)
            total = conv + setup
            order.costs = {"production": conv, "setup": setup}
        else:
            ln = ds.lane_by_id[opt.source_id]
            mode = ln.planning_mode
            order.shipments = costing.shipments_needed(ds, mode, order.product, qty)
            freight = qty * costing.freight_per_unit(ds, mode, order.product) + order.shipments * mode.cost_per_shipment
            hand = 0.0 if self.is_customer((ln.destination, order.product)) else qty * costing.handling(ds, ln.destination)
            self._kpi("transport_cost", freight)
            self._kpi("handling_cost", hand)
            total = freight + hand
            order.costs = {"transport": freight, "handling": hand}
        order.total_cost = total
        order.unit_cost = total / qty if qty > 0 else 0.0

    # ------------------------------------------------------------------ pegging
    def _peg(self, node: Node, st: _NodeState) -> None:
        first_peg = len(self.pegs)
        for sp, rid, q in st.fixed:       # sales-order stock: to its own order, already matched
            self._add_peg(Peg(supply_kind=sp.kind, supply_id=sp.id, requirement_id=rid, qty=q))
        supplies = sorted((s for s in st.supplies if s.segment is None),
                          key=lambda s: (s.date, {"on_hand": 0, "receipt": 1, "co_product": 2, "follow_up": 3,
                                                  "order": 3}[s.kind], s.id))
        reqs = sorted(st.netted if st.netted is not None else st.reqs, key=lambda r: (r.date, r.priority, r.id))
        left = [s.qty for s in supplies]
        i = 0
        for r in reqs:
            need = r.qty
            while need > EPS and i < len(supplies):
                take = min(need, left[i])
                if take > EPS:
                    self._add_peg(Peg(supply_kind=supplies[i].kind, supply_id=supplies[i].id,
                                      requirement_id=r.id, qty=take))
                    left[i] -= take
                    need -= take
                if left[i] <= EPS:
                    i += 1
        for s, rem in zip(supplies, left, strict=True):
            if s.kind == "order":
                self.order_by_id[s.id].lot_excess = max(0.0, rem)
        if st.lp.strategy is Strategy.MTO or st.lp.direct_production:
            # made to order: an order that serves one sales order alone is that order's, and is firmed for it
            serves: dict[str, set[str | None]] = defaultdict(set)
            for p in self.pegs[first_peg:]:
                if p.supply_kind == "order" and p.requirement_id in self.req_by_id:
                    serves[p.supply_id].add(self.sales_order_of(self.req_by_id[p.requirement_id]))
            for oid, sos in serves.items():
                if len(sos) == 1 and (so := next(iter(sos))) is not None:
                    self.order_by_id[oid].sales_order = so
        if st.lp.strategy is Strategy.ATO:
            forecast_reqs = {r.id for r in st.reqs if r.kind == "forecast"}
            for p in self.pegs[first_peg:]:
                if p.supply_kind == "order" and p.requirement_id in forecast_reqs:
                    self.order_by_id[p.supply_id].convertible = False
        if node[1] in self.ds.variants_of:
            # a planning material is never made or shipped itself: its orders plan the parts its variants share
            for p in self.pegs[first_peg:]:
                if p.supply_kind == "order":
                    self.order_by_id[p.supply_id].convertible = False

    def _add_peg(self, p: Peg) -> None:
        self.pegs.append(p)
        self._pegs_of[p.supply_id].append(p)
        if self._fx is not None:
            self._fx.append((_PEG, p))

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        self.prepare()
        for node in self.g.order:
            m = self.kept.memo.get(node) if self.kept is not None else None
            if m is not None and self._clean(node, m):
                self._replay(node, m)
            else:
                self._plan(node)
            self._done.add(node)
        self._propagate()

    def _plan(self, node: Node) -> None:
        self._cur, fx = node, []
        self._fx = fx
        came = list(self.incoming.get(node, ()))
        p0, o0 = len(self.pegs), len(self.orders)
        self.seed(node)
        self.plan_node(node)
        self._fx = self._cur = None
        self.touched.add(node)
        self._peg_at[node] = (p0, len(self.pegs))
        self._order_at[node] = (o0, len(self.orders))
        st = self.state[node]
        reads_up = (bool(st.fixed) or any(sp.segment is not None for sp in st.supplies)
                    or st.lp.strategy is Strategy.MTO or st.lp.direct_production)
        self.memo[node] = _NodeMemo(
            key=self._key(node), incoming=came, fx=fx, st=st, orders=self.orders[o0:], pegs=self.pegs[p0:],
            quota=[(k, self.quota_alloc[k]) for o in self.g.options.get(node, ())
                   if (k := (node, o.source_id)) in self.quota_alloc],
            lot_cost=self._lot_costs.get(node), reads_up=reads_up)

    def _clean(self, node: Node, m: _NodeMemo) -> bool:
        """Whether the node reads nothing that changed since the previous plan: the same data, the same requirements
        and co-products from its consumers and (where its plan reads its consumers' plans) consumers that were not
        planned again. Its order numbers are its own (see ``_next_id``), so it makes the same orders by the same
        numbers whatever other nodes now make."""
        came = self.incoming.get(node, [])
        if len(came) != len(m.incoming):
            return False
        for (who, a), (was, b) in zip(came, m.incoming, strict=True):
            if a is not b and (who != was or a != b):
                return False
        if m.reads_up and any(who in self.touched for who, _ in came):
            return False
        return m.key == self._key(node)

    def _replay(self, node: Node, m: _NodeMemo) -> None:
        """Do again what planning the node did, without planning it."""
        self._cur = node
        self.state[node] = m.st
        for r in m.st.reqs:
            self.req_by_id[r.id] = r
        p0, o0 = len(self.pegs), len(self.orders)
        for o in m.orders:
            self._add_order(o)
        for e in m.fx:
            op = e[0]
            if op == _REQ:
                self._add_req(e[1], e[2])
            elif op == _SUP:
                self._add_supply(e[1], e[2])
            elif op == _INPUT:
                self.order_inputs[e[1]].append(e[2])
            elif op == _PEG:
                self.pegs.append(e[1])
                self._pegs_of[e[1].supply_id].append(e[1])
            elif op == _KPI:
                setattr(self.kpi, e[1], getattr(self.kpi, e[1]) + e[2])
            elif op == _EXC:
                self.exceptions.append(e[1])
            elif op == _LOAD:
                self._add_load(e[1], e[2], e[3])
            else:   # _FLOW
                (self.lane_load if e[1] else self.supplier_load)[e[2]][e[3]] += e[4]
        for k, v in m.quota:
            self.quota_alloc[k] = v
        if m.lot_cost is not None:
            self._lot_costs[node] = m.lot_cost
        self._cur = None
        self._peg_at[node] = (p0, len(self.pegs))
        self._order_at[node] = (o0, len(self.orders))
        self.memo[node] = dataclasses.replace(m, incoming=list(self.incoming.get(node, ())))

    def _key(self, node: Node) -> tuple:
        """Everything planning the node reads of the data beyond what the whole plan reads (:func:`_global_key`): its
        policies and product, its sources with the bills of material, the parts' records and the lanes into its place, the
        values worked out for it (unit value, demand rate, DDMRP buffer, expiring stock) and what it is seeded with."""
        ds, (loc, prod) = self.ds, node
        opts = self.g.options.get(node) or []
        recs: list = []
        for o in opts:
            if o.kind == "make":
                ps = ds.production_source_by_id[o.source_id]
                recs.append(ps)
                self._bom_reads(loc, ps, recs, ())
            elif o.kind == "buy":
                recs.append(ds.purchasing_source_by_id[o.source_id])
            else:
                recs.append(ds.lane_by_id[o.source_id])
        lp = self.lp(node)
        return (lp, ds.location_product_by_key.get(node), ds.demand_lp(node), ds.product_by_id.get(prod),
                prod in ds.variants_of, tuple(opts), tuple(recs), self._lanes_to(loc),
                self.val.unit_value.get(node), self.val.basis.get(node), self.flow.direct.get(node),
                self.flow.mean.get(node), self.flow.var.get(node), self.flow.cv_source.get(node),
                tuple(self.expiring.get(node, ())), self._buffer(node) if lp.mrp_type is MrpType.DDMRP else None,
                tuple(self._indep.get(node, ())), tuple(self._rc_at.get(node, ())), tuple(self._rv_at.get(node, ())),
                tuple(self._targets.get(node, ())))

    def _bom_reads(self, loc: str, ps, recs: list, seen: tuple[str, ...]) -> None:
        """The records exploding ``ps`` reads: each part's product and planning record (phantom, withdrawal), and a
        phantom's own sources, through every level."""
        ds = self.ds
        parts = [c.product for c in ps.components] + [c.product for a in ps.bom_alternatives for c in a.components]
        for c in [*parts, *(co.product for co in ps.co_products)]:
            lp = ds.location_product_by_key.get((loc, c))
            recs += [c, ds.product_by_id.get(c), lp]
            if lp is not None and lp.phantom and c not in seen:
                for sub in ds.production_sources:
                    if sub.location == loc and sub.product == c:
                        recs.append(sub)
                        self._bom_reads(loc, sub, recs, (*seen, c))

    def _lanes_to(self, loc: str) -> tuple:
        if not hasattr(self, "_lanes_into"):
            self._lanes_into: dict[str, list] = defaultdict(list)
            for ln in self.ds.lanes:
                self._lanes_into[ln.destination].append(ln)
        return tuple(self._lanes_into.get(loc, ()))

    def _propagate(self) -> None:
        """Projected availability: an order cannot finish earlier than its inputs are available. Each order carries
        a profile of how much of it is available by when, so an input that is only partly late delays only that
        share of the order (the part covered from stock ships on time, as promising splits it). An order's supply
        goes to its requirements earliest first. Upstream first (descending LLC).

        Planning again after a change works out again only the nodes planned again and those an input of which now
        arrives differently; every other node keeps its projection."""
        receipt_date = {rc.id: self.receipt_date(rc) for rc in self.ds.receipts}
        beyond = self.b.end + timedelta(days=3650)
        chunks: dict[int, list[tuple[date, float]]] = {}  # id(peg) -> (date available, qty)
        on_req: dict[Node, dict[str, list[Peg]]] = {}

        def pegs_on(r: Requirement) -> list[Peg]:
            node = (r.location, r.product)
            by = on_req.get(node)
            if by is None:
                by = on_req[node] = defaultdict(list)
                a, b = self._peg_at.get(node, (0, 0))
                for p in self.pegs[a:b]:
                    by[p.requirement_id].append(p)
            return by.get(r.id, [])

        def peg_chunks(p: Peg) -> list[tuple[date, float]]:
            if p.supply_kind == "order":
                got = chunks.get(id(p))
                return got if got is not None else [(self.order_by_id[p.supply_id].available_date, p.qty)]
            if p.supply_kind == "receipt":
                return [(receipt_date.get(p.supply_id, self.start), p.qty)]
            if p.supply_kind == "co_product":
                main = self.order_by_id[p.supply_id]
                return [(main.projected_available_date or main.available_date, p.qty)]
            return [(self.start, p.qty)]

        def req_profile(r: Requirement) -> list[tuple[date, float]]:
            out = [c for p in pegs_on(r) for c in peg_chunks(p)]
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

        again = None if self.kept is None else set(self.touched)   # nodes whose projection is worked out again
        for node in sorted(self.g.order, key=lambda n: -self.g.llc[n]):
            m = self.memo[node]
            a, b = self._peg_at[node]
            mine = self.pegs[a:b]
            if again is not None and node not in again:
                for p, c in zip(mine, m.chunks, strict=True):
                    if p.supply_kind == "order":
                        chunks[id(p)] = c
                continue
            by_order: dict[str, list[int]] = defaultdict(list)
            for j, p in enumerate(mine):
                if p.supply_kind == "order":
                    by_order[p.supply_id].append(j)
            fresh = again is None or node in self.touched
            for s in self.state[node].supplies:
                if s.kind != "order":
                    continue
                o = self.order_by_id[s.id]
                if not fresh:
                    o = self._unshare(node, o)
                prof = order_profile(o)
                last = prof[-1][0]
                o.projected_available_date = last if last < beyond else None
                o.delay_days = float(max(0, (last - o.need_date).days)) if last < beyond else -1.0
                o.projected_on_time_qty = sum(q for d, q in prof if d <= o.need_date)
                if last > o.available_date:
                    # the input whose last share comes latest against its need: what the order waits for
                    worst = None
                    for rid in self.order_inputs.get(o.id, []):
                        r = self.req_by_id[rid]
                        if r.qty <= 1e-9:
                            continue
                        got = req_profile(r)[-1][0]
                        if worst is None or (got - r.date) > (worst[1] - worst[0].date):
                            worst = (r, got)
                    if worst is not None:
                        o.limited_by, o.limited_at = worst[0].product, worst[0].location
                        o.limited_until = worst[1] if worst[1] < beyond else None
                queue = [list(c) for c in prof]
                for j in sorted(by_order.get(o.id, []), key=lambda j: (self.req_by_id[mine[j].requirement_id].date, j)):
                    need, got = mine[j].qty, []
                    while need > 1e-9 and queue:
                        take = min(need, queue[0][1])
                        got.append((queue[0][0], take))
                        need -= take
                        queue[0][1] -= take
                        if queue[0][1] <= 1e-9:
                            queue.pop(0)
                    if need > 1e-9:
                        got.append((beyond, need))
                    chunks[id(mine[j])] = got
            m.chunks = [peg_chunks(p) for p in mine]
            if again is not None:
                self._tell_consumers(node, mine, m.chunks, again)
        self._again = again
        self._pegs_on = pegs_on
        self._peg_chunks = peg_chunks

    def _unshare(self, node: Node, o: PlannedOrder) -> PlannedOrder:
        """A copy of an order the previous plan also holds, to work its projection out again on (that plan's stays as
        it was), in this plan's place of it."""
        new = o.model_copy(update={"projected_available_date": None, "delay_days": 0.0, "projected_on_time_qty": None,
                                   "limited_by": None, "limited_at": None, "limited_until": None})
        m = self.memo[node]
        j = next(i for i, x in enumerate(m.orders) if x is o)
        m.orders = [*m.orders[:j], new, *m.orders[j + 1:]]
        self.orders[self._order_at[node][0] + j] = new
        self.order_by_id[o.id] = new
        return new

    def _tell_consumers(self, node: Node, mine: list[Peg], now: list[list[tuple[date, float]]], again: set[Node]):
        """After a node's projection is worked out again: the orders whose inputs at it now arrive differently are
        worked out again too."""
        old = self.kept.memo.get(node) if self.kept is not None else None
        if old is None or old.chunks is None:
            new_by: dict[str, list] = defaultdict(list)
            for p, c in zip(mine, now, strict=True):
                new_by[p.requirement_id].append(c)
            changed = set(new_by)
        else:
            new_by = defaultdict(list)
            for p, c in zip(mine, now, strict=True):
                new_by[p.requirement_id].append(c)
            old_by: dict[str, list] = defaultdict(list)
            for p, c in zip(old.pegs, old.chunks, strict=True):
                old_by[p.requirement_id].append(c)
            changed = {rid for rid in set(new_by) | set(old_by) if new_by.get(rid) != old_by.get(rid)}
        for rid in changed:
            r = self.req_by_id.get(rid)
            o = self.order_by_id.get(r.parent_order or "") if r is not None else None
            if o is not None:
                again.add((o.location, o.product))

    def _on_time(self, r: Requirement) -> float:
        """How much of a requirement its pegged supply projects to be available by the requirement's date."""
        return sum(q for p in self._pegs_on(r) for d, q in self._peg_chunks(p) if d <= r.date)

    # ------------------------------------------------------------------ outputs
    def result(self) -> PlanResult:
        s = self.s
        out = PlanResult(ok=True, currency=s.currency, carrying_rate=s.carrying_rate)
        out.buckets = [BucketOut(index=b.index, start=b.start, end=b.end, label=b.label) for b in self.b]
        k = self.kpi
        holding = k.holding_cost
        inv_start = inv_end = inv_avg_num = 0.0
        on_time = total_ind = 0.0
        risks: list[PlanException] = []
        again = getattr(self, "_again", None)
        for node in self.g.order:
            m = self.memo[node]
            if again is None or node in again or m.out is None:
                m.out = self._node_result(node)
            plan, excs, risk, held, avg, inv, ind = m.out
            for h in held:
                holding += h
            for x in avg:
                inv_avg_num += x
            if inv is not None:
                inv_start += inv[0]
                inv_end += inv[1]
            for q, c, late in ind:
                total_ind += q
                on_time += c
                if late is not None:
                    out._late.append(late)
            out.nodes.append(plan)
            self.exceptions.extend(excs)
            risks.extend(risk)
        k.holding_cost = holding
        self.exceptions.extend(risks)
        out.resources = self._resources()
        self._capacity_checks()
        self._purchase_checks()
        out.orders = self.orders
        out.requirements = [r for st in self.state.values() for r in st.reqs]
        out.receipts = [ScheduledReceiptOut(id=r.id, kind=r.kind.value, location=r.location, product=r.product,
                                            qty=r.expected_qty, date=self.receipt_date(r)) for r in self.ds.receipts]
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

    def _node_result(self, node: Node) -> tuple:
        """A node's part of the result: its plan by bucket, its exceptions, its demand at risk, and what it adds to
        the totals, each addition on its own so the totals add up in the same order however they are put together."""
        s, n = self.s, len(self.b)
        st = self.state[node]
        lp = st.lp
        val = self.val.unit_value.get(node, 0.0)
        rate = lp.holding_rate if lp.holding_rate is not None else s.carrying_rate
        bks = [NodeBucket(bucket=i, safety_stock=st.ss_by_bucket[i] if st.ss_by_bucket else 0.0,
                          target_stock=target_at(st.targets, self.b[i].end - timedelta(days=1)))
               for i in range(n)]
        # the free stock (S/4's anonymous segment): what is held for a sales order, and what of that order it
        # covers, is the order's alone and not in this projection
        for r in (st.netted if st.netted is not None else st.reqs):
            bi = self.b.index_of(r.date)
            if 0 <= bi < n:
                if r.kind in ("forecast", "sales_order"):
                    bks[bi].gross_independent += r.qty
                elif r.kind == "expiry":
                    bks[bi].expiring += r.qty
                else:
                    bks[bi].gross_dependent += r.qty
        for sp in st.supplies:
            if sp.kind == "on_hand" or sp.segment is not None:
                continue
            bi = self.b.index_of(sp.avail_date)
            if 0 <= bi < n:
                if sp.kind == "receipt":
                    bks[bi].scheduled_receipts += sp.qty
                else:
                    bks[bi].planned_receipts += sp.qty
        customer = self.is_customer(node)
        onhand = 0.0 if customer else lp.on_hand
        poh = onhand
        held: list[float] = []
        avg: list[float] = []
        for bk, meta in zip(bks, self.b, strict=True):
            poh += bk.scheduled_receipts + bk.planned_receipts - bk.gross_independent - bk.gross_dependent - bk.expiring
            bk.projected_on_hand = poh
            bk.shortage = max(0.0, -poh)
            bk.below_safety = max(0.0, bk.safety_stock - max(poh, 0.0)) if bk.safety_stock > 0 else 0.0
            if not customer:
                bk.holding_cost = max(0.0, poh) * val * rate * meta.days / 365.0
                held.append(bk.holding_cost)
                avg.append(max(0.0, poh) * val * meta.days)
        inv = None if customer else ((onhand + sum(x.qty for x in lp.order_stock)) * val,
                                     max(0.0, bks[-1].projected_on_hand) * val if bks else 0.0)
        e0 = len(self.exceptions)
        self._node_exceptions(node, st, bks)
        # service: independent demand projected available on time
        ind: list[tuple[float, float, LateDemand | None]] = []
        for r in st.reqs:
            if r.kind not in ("forecast", "sales_order"):
                continue
            covered = self._on_time(r)
            late = None
            if r.qty - covered > 1e-6:
                got = [c for p in self._pegs_on(r) for c in self._peg_chunks(p)]
                last = max((d for d, _ in got), default=None)
                whole = r.qty - sum(q for _, q in got) <= 1e-6 and last is not None and last < self.b.end + timedelta(days=3650)
                late = LateDemand(requirement=r.id, location=r.location, product=r.product, kind=r.kind, date=r.date,
                                  qty=r.qty, late=r.qty - covered, all_by=last if whole else None)
            ind.append((r.qty, covered, late))
            bi = self.b.index_of(r.date)
            if 0 <= bi < n and r.qty - covered > 1e-6:
                bks[bi].at_risk += r.qty - covered
        e1 = len(self.exceptions)
        self._demand_risk(node)
        excs, risk = self.exceptions[e0:e1], self.exceptions[e1:]
        del self.exceptions[e0:]
        opts = self.g.options.get(node) or []
        plan = NodePlan(
            location=node[0], product=node[1], llc=self.g.llc[node], strategy=lp.strategy.value,
            mrp_type=lp.mrp_type.value, lot_policy=lp.lot_sizing.policy.value, unit_value=val,
            value_basis=self.val.basis.get(node, ""), on_hand=onhand,
            safety_stock_method=lp.safety_stock.method.value, safety_stock_note=st.ss_note,
            lead_time_days=st.lead_time, sources=[f"{o.kind}:{o.source_id}" for o in opts],
            buckets=bks, order_ids=[sp.id for sp in st.supplies if sp.kind == "order"])
        return plan, excs, risk, held, avg, inv, ind

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

    def _demand_risk(self, node: Node) -> None:
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
            daily: dict[date, float] = defaultdict(float)
            for d, h in loads.items():
                if h > 0 and d < self.b.end:
                    daily[max(d, self.b.start)] += h
            per = []
            for (oid, prod, firm), by in self.res_orders.get(r.id, {}).items():
                hrs: dict[date, float] = defaultdict(float)
                for d, h in by.items():
                    if h > 0 and d < self.b.end:
                        hrs[max(d, self.b.start)] += h
                if hrs:
                    per.append(OrderLoad(order=oid, product=prod, firm=firm, hours=dict(sorted(hrs.items()))))
            out.append(ResourcePlan(resource=r.id, location=r.location, kind=r.kind.value, finite=r.finite, buckets=bks,
                                    daily_load=dict(sorted(daily.items())), orders=per))
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
            # a day over capacity and overtime inside a bucket that has room overall (N116): the bucket check above
            # does not see it, but the work cannot be done on that day as planned
            full = {b.bucket for b in over}
            r = self.ds.resource_by_id[rp.resource]
            cal = resource_calendar(self.ds, rp.resource)
            days = []
            for d, h in rp.daily_load.items():
                if self.b.index_of(d) in full:
                    continue
                room = self._cap(rp.resource, d) + overtime_between(r, cal, d, d + timedelta(days=1))
                if h > room + 1e-6:
                    days.append((d, h - room))
            if days:
                worst = max(days, key=lambda x: x[1])
                self._exc("CAPACITY_DAY_OVERLOAD", "warning" if rp.finite else "info",
                          f"{rp.resource}: {len(days)} day(s) loaded beyond the day's capacity and overtime in "
                          f"weeks with room, from {days[0][0].isoformat()}; worst {worst[1]:,.1f} h over on "
                          f"{worst[0].isoformat()}", resource=rp.resource, when=days[0][0], qty=worst[1])
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

    def _purchase_checks(self) -> None:
        """Open purchase lines against what their supplier confirmed (or has not)."""
        for rc in self.ds.receipts:
            if rc.kind.value != "purchase":
                continue
            node = (rc.location, rc.product)
            ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
            if rc.confirmed_date is not None and rc.confirmed_date > rc.due_date:
                days = (rc.confirmed_date - rc.due_date).days
                self._exc("PO_CONFIRMED_LATE", "warning",
                          f"{rc.id}: the supplier confirmed {rc.confirmed_date.isoformat()}, {days} d after the requested "
                          f"{rc.due_date.isoformat()}; the plan expects it then", node=node, order=rc.id,
                          when=rc.confirmed_date, qty=rc.expected_qty)
            if rc.confirmed_qty is not None and rc.confirmed_qty < ordered - EPS:
                self._exc("PO_CONFIRMED_SHORT", "warning",
                          f"{rc.id}: the supplier confirmed {rc.confirmed_qty:,.0f} of {ordered:,.0f}; the plan counts "
                          f"only what is confirmed", node=node, order=rc.id, when=rc.expected_date,
                          qty=ordered - rc.confirmed_qty)
            po = self.ds.purchase_order_by_id.get(rc.po or "")
            if po is None or rc.confirmed_date is not None or rc.confirmed_qty is not None or po.sent_on is None:
                continue
            v = self.ds.vendor(po.supplier)
            by = po.sent_on + timedelta(days=v.confirmation_days)
            if v.confirmation_required and by < self.start:
                self._exc("PO_NOT_CONFIRMED", "warning",
                          f"{rc.id}: sent to {po.supplier} on {po.sent_on.isoformat()} and not confirmed (expected by "
                          f"{by.isoformat()}); the plan still expects it on {rc.due_date.isoformat()}", node=node,
                          order=rc.id, when=rc.due_date, qty=rc.qty)

    def _exc(self, code: str, severity: str, message: str, *, node: Node | None = None, order: str | None = None,
             resource: str | None = None, when: date | None = None, qty: float | None = None) -> None:
        e = PlanException(code=code, severity=severity, message=message, location=node[0] if node else None,
                          product=node[1] if node else None, resource=resource, order_id=order, date=when, qty=qty)
        self.exceptions.append(e)
        if self._fx is not None:
            self._fx.append((_EXC, e))


def target_at(points: list[tuple[date, float]], d: date) -> float:
    """The S&OP stock target on ``d``: linear between the surrounding points, none outside them."""
    if not points or d < points[0][0] or d > points[-1][0]:
        return 0.0
    for (d0, q0), (d1, q1) in zip(points, points[1:], strict=False):
        if d0 <= d <= d1:
            span = (d1 - d0).days
            return q1 if span <= 0 else q0 + (q1 - q0) * (d - d0).days / span
    return points[-1][1] if d == points[-1][0] else 0.0


# "Plan everything" asks for the supply plan in six of its steps (the plan, promising, capacity, buying, money,
# performance), each with the same data: a large company's plan takes a minute and a half, so the last one that took
# long is kept, by the data's content, and handed out again. Callers only read a plan.
_KEEP_AFTER_S = 2.0
T = TypeVar("T")
_last: tuple[str, PlanResult, dict[str, Any]] | None = None
_last_work: Kept | None = None            # the kept plan's work: whoever is answered with that plan keeps it too
_last_lock = threading.Lock()
# and each planner's last plan's work, node by node, so that after a change only what the change reaches is planned
# again. Kept by who plans (``plan_owner``): two planners, or two companies, planning in turn would otherwise each
# find the other's work and plan everything (or, with the same data, read "nothing changed" of their own change).
# The work of a large company takes gigabytes: the newest is always kept, older ones while all kept hold no more
# than SCP_KEPT_NODES products at places (one company of 5,000 products at 20 places and some small ones).
KEPT_NODES = max(1, int(os.environ.get("SCP_KEPT_NODES", "150000") or 150000))
_kept: OrderedDict[str, Kept] = OrderedDict()
#: who plans: set for each request by the API's gate (the company open and the person or browser asking); planning
#: outside a request is one planner
plan_owner: ContextVar[str] = ContextVar("plan_owner", default="")


def _keep(owner: str, kept: Kept) -> None:
    """Keep ``kept`` as ``owner``'s, then drop the oldest others' while all kept hold more than KEPT_NODES nodes."""
    _kept.pop(owner, None)
    _kept[owner] = kept
    # two planners answered with one plan hold its work once
    held = Counter(id(k) for k in _kept.values())
    total = sum(len(k.memo) for k in {id(k): k for k in _kept.values()}.values())
    while len(_kept) > 1 and total > KEPT_NODES:
        _, k = _kept.popitem(last=False)
        held[id(k)] -= 1
        if not held[id(k)]:
            total -= len(k.memo)


#: A dataset's fingerprint when something already stands for its content (a company read by reference is its save
#: and the changes on it, scp.api.working), else None: hashing a large company takes seconds.
def _no_fingerprint(_ds: Dataset) -> str | None:
    return None


known_fingerprint: Callable[[Dataset], str | None] = _no_fingerprint


def _fingerprint(ds: Dataset) -> str:
    return known_fingerprint(ds) or hashlib.sha256(ds.model_dump_json().encode()).hexdigest()


def run_mrp(ds: Dataset) -> PlanResult:
    """Validate, then plan. With blocking issues the result carries only the issues."""
    global _last, _last_work
    key = None
    owner = plan_owner.get()
    if _last is not None:
        key = _fingerprint(ds)
        with _last_lock:
            if _last is not None and _last[0] == key:
                # the same data planned by someone else: the plan is theirs, and so is the work this planner's next
                # change is planned again from (else a second planner of an unchanged company plans all of it)
                if _last_work is not None:
                    _keep(owner, _last_work)
                return _last[1]
    t = time.perf_counter()
    with _last_lock:
        mine = _kept.get(owner)
    res, kept = plan_again(ds, mine)
    with _last_lock:
        if time.perf_counter() - t >= _KEEP_AFTER_S:
            _last = (key or _fingerprint(ds), res, {})
            _last_work = kept
        if kept is not None:
            _keep(owner, kept)
    return res


def with_kept_plan(ds: Dataset, plan: PlanResult, name: str, make: Callable[[], T]) -> T:
    """``make()``, kept beside the kept plan when ``plan`` is it and ``ds`` is the data it was made from (money and
    performance both follow the plan's costs to the customers, a quarter of a minute for a large company)."""
    kept = _last
    if kept is None or kept[1] is not plan or _fingerprint(ds) != kept[0]:
        return make()
    with _last_lock:
        if name in kept[2]:
            return kept[2][name]
    out = make()
    with _last_lock:
        kept[2][name] = out
    return out


def _run_mrp(ds: Dataset) -> PlanResult:
    return plan_again(ds, None)[0]


def _global_key(ds: Dataset) -> tuple:
    """What every node's plan reads: a change to any of it plans everything again."""
    return (ds.settings, ds.calendars, ds.locations, ds.resources, ds.vendors, ds.mrp_groups, ds.purchasing,
            ds.scheduling, ds.inventory, ds.contracts)


def _replayable(ds: Dataset) -> bool:
    """Plans whose nodes share nothing but what is handed down the network can be planned again node by node.
    Capacity-constrained planning (machines, suppliers and lanes shared between products) and co-products (a node's
    supply made by another product's orders) are planned whole."""
    return not ds.settings.capacity_constrained and not any(ps.co_products for ps in ds.production_sources)


def plan_again(ds: Dataset, kept: Kept | None) -> tuple[PlanResult, Kept | None]:
    """Validate, then plan: from the previous plan's work where ``kept`` holds it, planning again only the nodes the
    changes since then reach (S/4 net change planning), else from scratch. Either way the plan is the one planning
    from scratch makes. Returns the plan and its work, to plan from next time (None where it cannot be)."""
    issues = validate(ds)
    if has_errors(issues):
        return PlanResult(ok=False, currency=ds.settings.currency, carrying_rate=ds.settings.carrying_rate,
                          issues=issues), None
    g = build_graph(ds)
    replay = _replayable(ds)
    gkey = _global_key(ds) if replay else ()
    use = (kept if replay and kept is not None and kept.gkey == gkey and kept.order == g.order
           and kept.llc == g.llc else None)
    # the collector would look through every object the kept work holds (gigabytes for a large company) to find the
    # few cycles a plan again makes: not while planning again
    pause = use is not None and gc.isenabled()
    if pause:
        gc.disable()
    try:
        p = _Planner(ds, g, use)
        p.run()
        res = p.result()
    except _NotIncremental:
        if pause:                            # planning everything: as any plan from scratch
            gc.enable()
            pause = False
        p = _Planner(ds, g)
        p.run()
        res = p.result()
    finally:
        if pause:
            gc.enable()
    res.issues = issues
    if p.kept is not None:
        res.planned_again = len(p.touched)
    _open_later(ds, res)
    return res, (Kept(gkey, list(g.order), dict(g.llc), p.memo, reused=p.kept is not None, planned=len(p.touched))
                 if replay else None)


def _open_later(ds: Dataset, res: PlanResult) -> None:
    """Mark planned purchases that an open order for the same product and place would cover if it came sooner. (An
    order the previous plan also holds is copied first, so that plan stays as it was.)"""
    open_po: dict[tuple[str, str], list] = {}
    for r in ds.receipts:
        if r.kind is ReceiptKind.PURCHASE and (r.confirmed_qty is None or r.confirmed_qty > 0):
            open_po.setdefault((r.location, r.product), []).append(r)
    for i, o in enumerate(res.orders):
        if o.kind == "buy":
            later = [r.id for r in open_po.get((o.location, o.product), []) if (r.confirmed_date or r.due_date) > o.need_date]
            if later != o.open_later:
                res.orders[i] = o.model_copy(update={"open_later": later})


__all__ = ["run_mrp"]
