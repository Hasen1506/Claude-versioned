"""Promising runs.

* ``entry`` — persisted confirmations keep their supply; orders without one are checked in entry
  sequence (dataset order), like order entry. Persisted promises no longer covered by supply are
  flagged *at risk* — the trigger for backorder processing.
* ``bop``   — backorder processing: segments are processed in sequence, each order per its
  segment's confirmation strategy; orders no segment selects keep their confirmations.
* ``check`` — the entry state plus one simulated order (not persisted).

``commit`` writes the confirmations of an entry or BOP run into the dataset.
"""
from __future__ import annotations

from collections import defaultdict

from ..model import ConfirmationStrategy, Dataset, DemandKind, DemandRecord
from ..model.promise import Confirmation
from ..plan import run_mrp
from ..validate import has_errors, validate
from .atp import EPS
from .engine import OrderPromise, Promiser, finish, sales_orders, segment_of, sort_key
from .result import AllocationUse, BopRow, PromiseKpis, PromiseResult, ScheduleLine


def _start(ds: Dataset, mode: str) -> tuple[PromiseResult, Promiser | None]:
    res = PromiseResult(ok=False, mode=mode, origin=ds.settings.planning_start, currency=ds.settings.currency)
    res.issues = validate(ds)
    if has_errors(res.issues):
        return res, None
    return res, Promiser(ds, run_mrp(ds))


def _persisted(ds: Dataset) -> dict[str, list[Confirmation]]:
    out: dict[str, list[Confirmation]] = defaultdict(list)
    for c in ds.confirmations:
        out[c.order].append(c)
    return out


def _entry(ds: Dataset, P: Promiser) -> list[OrderPromise]:
    persisted = _persisted(ds)
    orders = sales_orders(ds)
    out: dict[str, OrderPromise] = {}
    for key, d in orders:
        if key in persisted:
            lines = [P.register(d, c) for c in persisted[key]]
            r = OrderPromise(order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date,
                             priority=d.priority, complete_delivery=d.complete_delivery, lines=lines, previous=list(lines),
                             change="kept", value=d.qty * _price(ds, d))
            out[key] = finish(r)
    # which persisted promises does the current supply no longer cover? Promises shipping before the first day the
    # cumulative balance goes negative are covered (everything up to that day is); those shipping inside a
    # negative stretch are not
    for node, s in P.series.items():
        c = s.cum()
        neg = [j for j in range(min(s.horizon, s.days)) if c[j] < -EPS]
        if not neg:
            continue
        short = set(neg)
        for r in out.values():
            if any((x.ship_from, r.product) == node and P.day(x.ship_date) in short for x in r.lines):
                r.at_risk = True
    for key, d in orders:
        if key not in out:
            out[key] = P.check(d, key)
    return [out[k] for k, _ in orders]


def _price(ds: Dataset, d: DemandRecord) -> float:
    p = ds.product_by_id.get(d.product)
    return (p.price or 0.0) if p else 0.0


def _summary(lines: list[ScheduleLine]) -> tuple[float, float]:
    return (round(sum(x.qty for x in lines if x.on_time), 6), round(sum(x.qty for x in lines), 6))


def _reclaim(P: Promiser, d: DemandRecord, key: str, prev: list[Confirmation]) -> list[ScheduleLine]:
    """Take back a requirement's previous schedule lines as far as supply still allows."""
    lines = []
    allocs = P.allocations(d)
    for c in sorted(prev, key=lambda c: c.ship_date):
        node = (c.ship_from, d.product)
        day = P.day(c.ship_date)
        take = min(c.qty, P.series_for(node).available(day), P.alloc_cap(allocs, day))
        if take > EPS:
            sh = next((s for s in P.ships(d) if s.node == node), None)
            if sh is None:
                continue
            lines.append(P.commit_line(d, sh, day, take, c.method, allocs, d.date))
    return lines


def _combine(P: Promiser, d: DemandRecord, key: str, lines: list[ScheduleLine]) -> OrderPromise:
    got = sum(x.qty for x in lines)
    extra = P.check(d, key, qty=d.qty - got) if d.qty - got > EPS else None
    r = OrderPromise(order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date,
                     priority=d.priority, complete_delivery=d.complete_delivery,
                     lines=lines + (extra.lines if extra else []), ctp=extra.ctp if extra else [])
    return finish(r)


def _bop(ds: Dataset, P: Promiser) -> tuple[list[OrderPromise], list[BopRow]]:
    persisted = _persisted(ds)
    orders = sales_orders(ds)
    idx = {k: i for i, (k, _) in enumerate(orders)}
    segs = ds.promising.bop_segments
    out: dict[str, OrderPromise] = {}
    seg_of = {k: segment_of(segs, d) for k, d in orders}
    # orders no segment selects keep their confirmations and claim supply first
    for key, d in orders:
        if seg_of[key] is None and key in persisted:
            lines = [P.register(d, c) for c in persisted[key]]
            out[key] = finish(OrderPromise(order=key, location=d.location, product=d.product, qty=d.qty,
                                           requested=d.date, priority=d.priority, complete_delivery=d.complete_delivery,
                                           lines=lines))
    for sg in segs:
        members = sorted(((k, d) for k, d in orders if seg_of[k] is sg), key=lambda kd: sort_key(sg, kd[1], idx[kd[0]]))
        for key, d in members:
            prev = persisted.get(key, [])
            st = sg.strategy
            if st in (ConfirmationStrategy.WIN, ConfirmationStrategy.GAIN):
                snap = P.snapshot()
                r = P.check(d, key)
                before = (sum(c.qty for c in prev if c.date <= max(d.date, P.origin)), sum(c.qty for c in prev))
                if _summary(r.lines) < (round(before[0], 6), round(before[1], 6)):
                    P.restore(snap)
                    r = _combine(P, d, key, _reclaim(P, d, key, prev))
            elif st is ConfirmationStrategy.FILL:
                r = _combine(P, d, key, _reclaim(P, d, key, prev))
            elif st is ConfirmationStrategy.LOSE:
                cap = sum(c.qty for c in prev)
                r = P.check(d, key, qty=cap) if cap > EPS else finish(OrderPromise(
                    order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date,
                    priority=d.priority, complete_delivery=d.complete_delivery))
            else:
                r = P.check(d, key)
            r.segment, r.strategy = sg.name, st.value
            out[key] = r
    rows: list[BopRow] = []
    result: list[OrderPromise] = []
    for key, d in orders:
        r = out.get(key)
        prev = persisted.get(key, [])
        prev_lines = [ScheduleLine(ship_from=c.ship_from, ship_date=c.ship_date, date=c.date, qty=c.qty, method=c.method,
                                   on_time=c.date <= max(d.date, P.origin)) for c in prev]
        if r is None:   # not selected and nothing persisted: untouched
            r = finish(OrderPromise(order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date,
                                    priority=d.priority, complete_delivery=d.complete_delivery))
        r.previous = prev_lines
        r.value = d.qty * _price(ds, d)
        b_on, b_conf = _summary(prev_lines)
        a_on, a_conf = r.on_time, r.confirmed
        if a_on > b_on + EPS or (abs(a_on - b_on) <= EPS and a_conf > b_conf + EPS):
            outcome = "gained"
        elif a_on < b_on - EPS or a_conf < b_conf - EPS:
            outcome = "lost"
        elif _same(prev_lines, r.lines):
            outcome = "unchanged"
        else:
            outcome = "changed"
        r.change = outcome
        rows.append(BopRow(order=key, location=d.location, product=d.product, priority=d.priority, segment=r.segment,
                           strategy=r.strategy, before_confirmed=b_conf, before_on_time=b_on, after_confirmed=a_conf,
                           after_on_time=a_on, outcome=outcome))
        result.append(r)
    return result, rows


def _same(a: list[ScheduleLine], b: list[ScheduleLine]) -> bool:
    key = lambda x: (x.ship_from, x.ship_date, round(x.qty, 6))  # noqa: E731
    return sorted(map(key, a)) == sorted(map(key, b))


def _finish(ds: Dataset, P: Promiser, res: PromiseResult, orders: list[OrderPromise]) -> PromiseResult:
    res.orders = orders
    nodes = {(x.ship_from, o.product) for o in orders for x in o.lines}
    for _key, d in sales_orders(ds):
        for sh in P.ships(d):
            nodes.add(sh.node)
    span = ds.settings.horizon_days
    res.nodes = [P.node_view(n, span) for n in sorted(nodes)]
    res.allocations = [AllocationUse(id=a.id, product=a.product, customers=a.customers, start=a.start, end=a.end, qty=a.qty,
                                     used=P.alloc_used.get(a.id, 0.0), fallback=a.fallback) for a in ds.allocations]
    k = PromiseKpis(orders=len(orders))
    for o in orders:
        k.qty += o.qty
        k.on_time_qty += o.on_time
        k.confirmed_qty += o.confirmed
        k.unconfirmed_qty += o.unconfirmed
        k.on_time_orders += o.status == "on_time"
        k.value_unconfirmed += o.unconfirmed * (o.value / o.qty if o.qty else 0.0)
        k.rlt_lines += sum(x.method == "rlt" for x in o.lines)
        k.ctp_lines += sum(x.method == "ctp" for x in o.lines)
        primary = P.ships(_rec(o))[0].node[0] if P.ships(_rec(o)) else None
        k.alternative_lines += sum(x.ship_from != primary for x in o.lines)
        k.at_risk_orders += o.at_risk
    res.kpis = k
    res.ok = True
    return res


def _rec(o: OrderPromise) -> DemandRecord:
    return DemandRecord(location=o.location, product=o.product, date=o.requested, qty=o.qty,
                        kind=DemandKind.SALES_ORDER, priority=o.priority)


def run_promise(ds: Dataset) -> PromiseResult:
    res, P = _start(ds, "entry")
    if P is None:
        return res
    return _finish(ds, P, res, _entry(ds, P))


def run_bop(ds: Dataset) -> PromiseResult:
    res, P = _start(ds, "bop")
    if P is None:
        return res
    orders, rows = _bop(ds, P)
    res.bop = rows
    return _finish(ds, P, res, orders)


def check_order(ds: Dataset, order: DemandRecord) -> PromiseResult:
    res, P = _start(ds, "check")
    if P is None:
        return res
    orders = _entry(ds, P)
    rec = order.model_copy(update={"kind": DemandKind.SALES_ORDER})
    checked = P.check(rec, rec.id or "SIMULATION")
    checked.value = rec.qty * _price(ds, rec)
    res = _finish(ds, P, res, orders)
    res.checked = checked
    res.mode = "check"
    return res


def commit(ds: Dataset, mode: str = "entry") -> tuple[Dataset, PromiseResult]:
    res = run_bop(ds) if mode == "bop" else run_promise(ds)
    if not res.ok:
        return ds, res
    confs = [Confirmation(order=o.order, ship_from=x.ship_from, ship_date=x.ship_date, date=x.date, qty=x.qty,
                          method=x.method) for o in res.orders for x in o.lines]
    return ds.model_copy(update={"confirmations": confs}), res
