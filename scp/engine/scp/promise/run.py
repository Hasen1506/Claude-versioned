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

import math
from collections import defaultdict
from datetime import date

from ..model import ConfirmationStrategy, Dataset, DemandKind, DemandRecord, Strategy
from ..model.promise import Confirmation
from ..actuals.post import delivered, ordered_now
from ..plan import run_mrp
from ..plan.rates import independent_demand
from ..validate import Issue, has_errors, validate
from .atp import EPS
from .engine import OrderPromise, Promiser, finish, sales_orders, segment_of, sort_key
from .result import AllocationUse, BopRow, PromiseKpis, PromiseResult, SafeView, ScheduleLine


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
                             change="kept")
            _value(ds, d, r)
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
    together = {h.id for h in ds.sales_orders if h.single_delivery}
    groups: dict[str, list[tuple[DemandRecord, OrderPromise]]] = defaultdict(list)
    for key, d in orders:
        if key not in out:
            if d.order in together:          # one delivery for the whole order: each line in full, then aligned
                d = d.model_copy(update={"complete_delivery": True})
            out[key] = _value(ds, d, P.check(d, key))
            if d.order in together:
                groups[d.order].append((d, out[key]))
    for group in groups.values():
        P.together(group)
    return [out[k] for k, _ in orders]


def ship_together(ds: Dataset, oid: str) -> list[OrderPromise]:
    """Promise an order's lines as one delivery (they were just taken line by line): the promises after aligning."""
    res, P = _start(ds, "check")
    if P is None:
        return []
    persisted = _persisted(ds)
    group = []
    for key, d in sales_orders(ds):
        if d.order == oid:
            lines = [P.register(d, c) for c in persisted.get(key, [])]
            group.append((d, _value(ds, d, finish(OrderPromise(
                order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date, priority=d.priority,
                complete_delivery=True, lines=lines)))))
    for key, d in sales_orders(ds):           # everything else keeps its promise
        if d.order != oid:
            for c in persisted.get(key, []):
                P.register(d, c)
    P.together(group)
    return [r for _, r in group]


def _value(ds: Dataset, d: DemandRecord, r: OrderPromise) -> OrderPromise:
    """The order's price and value: its own price, else the customer's, else the product's; empty without one."""
    r.price = ds.selling_price(d.location, d.product, d.price)
    r.value = None if r.price is None else d.qty * r.price
    if d.id:
        r.shipped = round(max(0.0, delivered(ds, d.id) - (ordered_now(ds, d) - d.qty)), 6)
    return r


def _summary(lines: list[ScheduleLine]) -> tuple[float, float]:
    return (round(sum(x.qty for x in lines if x.on_time), 6), round(sum(x.qty for x in lines), 6))


_STRATEGY_ORDER = {strategy: index for index, strategy in enumerate((
    ConfirmationStrategy.LOSE, ConfirmationStrategy.WIN, ConfirmationStrategy.GAIN,
    ConfirmationStrategy.REDISTRIBUTE, ConfirmationStrategy.FILL,
))}


def _promise(key: str, d: DemandRecord, lines: list[ScheduleLine]) -> OrderPromise:
    return finish(OrderPromise(order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date,
                               priority=d.priority, complete_delivery=d.complete_delivery, lines=lines))


def _kept(P: Promiser, key: str, d: DemandRecord, previous: list[Confirmation]) -> OrderPromise:
    return _promise(key, d, [P.register(d, c) for c in previous])


def _no_later(lines: list[ScheduleLine], previous: list[Confirmation]) -> bool:
    """Gain must preserve the amount available by each existing confirmation date."""
    before, after = sorted(previous, key=lambda c: c.date), iter(sorted(lines, key=lambda x: x.date))
    line = next(after, None)
    required = supplied = 0.0
    for confirmation in before:
        required += confirmation.qty
        while line is not None and line.date <= confirmation.date:
            supplied += line.qty
            line = next(after, None)
        if supplied < required - EPS:
            return False
    return True


def _affected_orders(ds: Dataset, P: Promiser, orders: list[tuple[str, DemandRecord]],
                     persisted: dict[str, list[Confirmation]], failures: set[str]) -> set[str]:
    """Close the failed groups over supply nodes, allocations, delivery groups and CTP inputs."""
    together = {h.id for h in ds.sales_orders if h.single_delivery}
    by_resource = defaultdict(set)
    by_order = {}
    for key, d in orders:
        nodes = {ship.node for ship in P.ships(d)} | {(c.ship_from, d.product) for c in persisted.get(key, ())}
        resources = {("allocation", a.id) for level in P.allocations(d) for a in level}
        if d.order in together:
            resources.add(("delivery", d.order))
        pending = list(nodes)
        while pending:
            node = pending.pop()
            resource = ("stock", node)
            if resource in resources:
                continue
            resources.add(resource)
            if not P.cfg.ctp:
                continue
            for option in P.g.options.get(node, ()):
                if option.kind == "buy":
                    continue
                pending.extend(option.upstream)
                if option.kind == "make":
                    source = ds.production_source_by_id[option.source_id]
                    for operation in source.operations:
                        resources.add(("capacity", operation.resource))
                        resources.update(("capacity", r) for r in operation.alternatives)
        resources.discard(("capacity", None))
        resources.discard(("capacity", ""))
        by_order[key] = resources
        for resource in resources:
            by_resource[resource].add(key)

    affected, pending_orders = set(failures), list(failures)
    visited = set()
    while pending_orders:
        for resource in by_order[pending_orders.pop()] - visited:
            visited.add(resource)
            newly_affected = by_resource[resource] - affected
            affected.update(newly_affected)
            pending_orders.extend(newly_affected)
    return affected


def _bop(ds: Dataset, P: Promiser) -> tuple[list[OrderPromise], list[BopRow], list[Issue]]:
    persisted = _persisted(ds)
    orders = sales_orders(ds)
    idx = {k: i for i, (k, _) in enumerate(orders)}
    segs = ds.promising.bop_segments
    seg_of = {k: segment_of(segs, d) for k, d in orders}
    members = defaultdict(list)
    for key, d in orders:
        sg = seg_of[key]
        if sg is not None:
            members[id(sg)].append((key, d))
    cascade = [order for sg in sorted(segs, key=lambda sg: _STRATEGY_ORDER[sg.strategy])
               for order in sorted(members[id(sg)], key=lambda kd: sort_key(sg, kd[1], idx[kd[0]]))]
    snapshot = P.snapshot()
    frozen: set[str] = set()
    issues: list[Issue] = []
    while True:
        out = {}
        for key, d in orders:
            if seg_of[key] is None or key in frozen:
                out[key] = _kept(P, key, d, persisted.get(key, []))
                if key in frozen:
                    out[key].reason = "Previous confirmation retained because this backorder group failed"
        failed = set()
        for key, d in cascade:
            sg = seg_of[key]
            if key in frozen:
                out[key].segment, out[key].strategy = sg.name, sg.strategy.value
                continue
            previous = persisted.get(key, [])
            st = sg.strategy
            if st is ConfirmationStrategy.LOSE:
                r = _promise(key, d, [])
            elif st is ConfirmationStrategy.FILL:
                r = _promise(key, d, P.refill(d, previous))
            else:
                r = P.check(d, key)
            r.segment, r.strategy = sg.name, st.value
            out[key] = r
            if st is ConfirmationStrategy.WIN and r.on_time < d.qty - EPS:
                reason = f"Win requires {d.qty:g} on time and could confirm {r.on_time:g}"
            elif st is ConfirmationStrategy.GAIN and not _no_later(r.lines, previous):
                reason = "Gain could not preserve the quantities and delivery dates previously confirmed"
            else:
                continue
            failed.add(key)
            issues.append(Issue(code="BOP_GROUP_STOPPED", severity="warning", object_type="demand", object_id=key,
                                message=f"{reason}. The affected group's confirmations were retained."))
        if not failed:
            break
        frozen.update(_affected_orders(ds, P, orders, persisted, failed))
        P.restore(snapshot)

    rows: list[BopRow] = []
    result: list[OrderPromise] = []
    for key, d in orders:
        r = out.get(key)
        prev = persisted.get(key, [])
        prev_lines = [ScheduleLine(ship_from=c.ship_from, ship_date=c.ship_date, date=c.date, qty=c.qty, method=c.method,
                                   on_time=c.date <= max(d.date, P.origin), goods_issue=c.goods_issue) for c in prev]
        if r is None:   # not selected and nothing persisted: untouched
            r = finish(OrderPromise(order=key, location=d.location, product=d.product, qty=d.qty, requested=d.date,
                                    priority=d.priority, complete_delivery=d.complete_delivery))
        r.previous = prev_lines
        _value(ds, d, r)
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
    return result, rows, issues


def _same(a: list[ScheduleLine], b: list[ScheduleLine]) -> bool:
    def key(line: ScheduleLine):
        return (line.ship_from, line.ship_date, line.date, line.goods_issue or line.ship_date,
                line.method, round(line.qty, 6))

    return sorted(map(key, a)) == sorted(map(key, b))


def _offer(P: Promiser, pairs: list[tuple[DemandRecord, OrderPromise]]) -> None:
    """Substitutes for the orders not on time, in sequence on what is left free after every promise, each offer held
    against the next; the supply picture is put back afterwards, since an offer promises nothing until it is taken."""
    if not P.ds.substitutions:
        return
    snap = P.snapshot()
    for d, r in pairs:
        r.substitutes = P.substitutes(d, r)
    P.restore(snap)


def _finish(ds: Dataset, P: Promiser, res: PromiseResult, orders: list[OrderPromise]) -> PromiseResult:
    res.orders = orders
    if res.mode != "check":                # an order check offers substitutes for the order being checked only
        _offer(P, [(_rec(o), o) for o in orders])
    for o in orders:
        if not o.why and o.lines:          # kept or combined promises: the chain behind their latest date too
            o.why = P.explain(_rec(o), o)
    nodes = {(x.ship_from, o.product) for o in orders for x in o.lines}
    for _key, d in sales_orders(ds):
        for sh in P.ships(d):
            nodes.add(sh.node)
    span = ds.settings.horizon_days
    res.nodes = [P.node_view(n, span) for n in sorted(nodes)]
    res.allocations = [AllocationUse(id=a.id, product=a.product, family=a.family, carry_forward=a.carry_forward,
                                     customers=a.customers, start=a.start, end=a.end, qty=a.qty,
                                     used=P.alloc_used.get(a.id, 0.0), fallback=a.fallback) for a in ds.allocations]
    k = PromiseKpis(orders=len(orders))
    for o in orders:
        k.qty += o.qty
        k.on_time_qty += o.on_time
        k.confirmed_qty += o.confirmed
        k.unconfirmed_qty += o.unconfirmed
        k.on_time_orders += o.status == "on_time"
        if o.price is not None:
            k.value_unconfirmed += o.unconfirmed * o.price
        elif o.unconfirmed > EPS:
            k.unpriced_unconfirmed += 1
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
                        kind=DemandKind.SALES_ORDER, priority=o.priority, complete_delivery=o.complete_delivery)


def run_promise(ds: Dataset) -> PromiseResult:
    res, P = _start(ds, "entry")
    if P is None:
        return res
    return _finish(ds, P, res, _entry(ds, P))


def run_bop(ds: Dataset) -> PromiseResult:
    res, P = _start(ds, "bop")
    if P is None:
        return res
    orders, rows, issues = _bop(ds, P)
    res.bop = rows
    res.issues.extend(issues)
    return _finish(ds, P, res, orders)


def _high_end(ds: Dataset, lines: list[DemandRecord]) -> dict[str, list[DemandRecord]]:
    """Per product checked, the forecast still to be ordered up to its latest requested date, at the high end of the
    forecast's interval: what is left of each forecast once the orders, the checked lines among them, have used it
    up (as they do under make to stock too, the forecast being every order to come), plus its spread above the
    expected quantity. Products without a high end on their forecast, and nodes made to order (the forecast plans
    nothing there), are left out."""
    until: dict[str, date] = {}
    for ln in lines:
        until[ln.product] = max(until.get(ln.product, ln.date), ln.date)
    # only the products checked (and their variants, whose orders use up their forecast) are worked out, each record
    # named as the plan names it
    keep = set(until) | {p.id for p in ds.products if p.planning_material in until}
    recs = [d if d.id else d.model_copy(update={"id": f"#{i}"}) for i, d in enumerate(ds.demand) if d.product in keep]
    checked = [ln.model_copy(update={"id": f"CHECKED {j}"}) for j, ln in enumerate(lines)]
    with_lines = ds.model_copy(update={"demand": recs + checked})
    open_qty = {r.source_ref: r.qty for reqs in independent_demand(with_lines, orders_consume=True).values()
                for r, _ in reqs if r.kind == "forecast"}
    out: dict[str, list[DemandRecord]] = {}
    for i, d in enumerate(ds.demand):
        if (d.kind is not DemandKind.FORECAST or d.product not in until or d.high_qty is None
                or ds.location_type(d.location) is None or ds.demand_lp((d.location, d.product)).strategy is Strategy.MTO):
            continue
        out.setdefault(d.product, [])
        # the part of the forecast's period up to the requested date (the whole of it once the date is past its end)
        span = max(1, d.period_days or 1)
        share = min(span, max(0, (until[d.product] - d.date).days + 1)) / span
        qty = (open_qty.get(d.id or f"#{i}", 0.0) + max(0.0, d.high_qty - d.qty)) * share
        if ds.whole(d.product):
            qty = math.ceil(qty - 1e-6)
        if qty > EPS:
            out[d.product].append(DemandRecord(location=d.location, product=d.product,
                                               date=max(d.date, ds.settings.planning_start), qty=round(qty, 6),
                                               kind=DemandKind.SALES_ORDER, priority=d.priority))
    return out


def _safe(ds: Dataset, P: Promiser, lines: list[DemandRecord], keys: list[str]) -> list[SafeView | None]:
    """Each line checked again after the orders already promised and the high-end forecast before it."""
    high = _high_end(ds, lines)
    if not high:
        return [None] * len(lines)
    S = Promiser(ds, P.plan, P.g)
    _entry(ds, S)
    reserved: dict[str, float] = {}
    for prod, recs in high.items():
        for j, r in enumerate(sorted(recs, key=lambda r: (r.date, r.priority, r.location))):
            S.check(r, f"HIGH {prod} {j + 1}")
        reserved[prod] = round(sum(r.qty for r in recs), 6)
    out: list[SafeView | None] = []
    for ln, key in zip(lines, keys, strict=True):
        if ln.product not in high:
            out.append(None)
            continue
        c = S.check(ln, key)
        out.append(SafeView(reserved=reserved[ln.product], confirmed=c.confirmed, on_time=c.on_time, status=c.status,
                            date=max((x.date for x in c.lines), default=None), lines=c.lines))
    return out


def check_order(ds: Dataset, order: DemandRecord) -> PromiseResult:
    res, P = _start(ds, "check")
    if P is None:
        return res
    orders = _entry(ds, P)
    rec = order.model_copy(update={"kind": DemandKind.SALES_ORDER})
    checked = P.check(rec, rec.id or "SIMULATION")
    _value(ds, rec, checked)
    _offer(P, [(rec, checked)])
    res = _finish(ds, P, res, orders)
    checked.safe = _safe(ds, P, [rec], [rec.id or "SIMULATION"])[0]
    res.checked = checked
    res.mode = "check"
    return res


def check_lines(ds: Dataset, lines: list[DemandRecord]) -> PromiseResult:
    """Check the lines of one order before taking it (N119): each line after the orders already promised and after the
    lines before it, so two lines of one product do not both count the same stock."""
    res, P = _start(ds, "check")
    if P is None:
        return res
    orders = _entry(ds, P)
    out, recs, keys = [], [], []
    for i, ln in enumerate(lines):
        rec = ln.model_copy(update={"kind": DemandKind.SALES_ORDER})
        c = P.check(rec, rec.id or f"LINE {10 * (i + 1)}")
        _value(ds, rec, c)
        out.append(c)
        recs.append(rec)
        keys.append(rec.id or f"LINE {10 * (i + 1)}")
    _offer(P, list(zip(recs, out, strict=True)))
    res = _finish(ds, P, res, orders)
    for c, safe in zip(out, _safe(ds, P, recs, keys), strict=True):
        c.safe = safe
    res.checked = out[0] if out else None
    res.checked_lines = out
    res.mode = "check"
    return res


def commit(ds: Dataset, mode: str = "entry") -> tuple[Dataset, PromiseResult]:
    res = run_bop(ds) if mode == "bop" else run_promise(ds)
    if not res.ok:
        return ds, res
    confs = [Confirmation(order=o.order, ship_from=x.ship_from, ship_date=x.ship_date, date=x.date, qty=x.qty,
                          method=x.method, goods_issue=x.goods_issue) for o in res.orders for x in o.lines]
    return ds.model_copy(update={"confirmations": confs}), res
