"""Stock, open quantities and forecast accuracy from the goods-movement journal (pure functions)."""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from ..model import AccuracyRecord, Dataset, DemandKind, GoodsMovement, MovementType
from .result import AccuracyReport, AccuracySeries, AccuracyWeek, OpenOrderRow, StockRow

EPS = 1e-6
Node = tuple[str, str]


def before(ds: Dataset, as_of: date) -> list[GoodsMovement]:
    return [m for m in ds.movements if m.date < as_of]


def stock(movs: list[GoodsMovement]) -> dict[Node, float]:
    """On-hand per node = Σ signed movements."""
    out: dict[Node, float] = defaultdict(float)
    for m in movs:
        out[(m.location, m.product)] += m.signed
    return dict(out)


def stock_rows(ds: Dataset, as_of: date) -> list[StockRow]:
    movs = sorted(before(ds, as_of), key=lambda m: (m.date, m.id))
    by_node: dict[Node, list[GoodsMovement]] = defaultdict(list)
    for m in movs:
        by_node[(m.location, m.product)].append(m)
    nodes = set(by_node) | {(lp.location, lp.product) for lp in ds.location_products if lp.on_hand > 0}
    rows = []
    for n in sorted(nodes):
        lp = ds.location_product_by_key.get(n)
        master = lp.on_hand if lp else 0.0
        ms = by_node.get(n, [])
        bal, neg = 0.0, None
        by_type: dict[str, float] = defaultdict(float)
        for m in ms:
            bal += m.signed
            by_type[m.type.value] += m.signed
            if bal < -EPS and neg is None:
                neg = m.date
        rows.append(StockRow(location=n[0], product=n[1], master_on_hand=master,
                             movement_stock=round(bal, 6) if ms else None,
                             difference=round(max(0.0, bal) - master, 6) if ms else 0.0, movements=len(ms),
                             last_date=ms[-1].date if ms else None, by_type=dict(by_type), negative_on=neg))
    return rows


def _sum(movs: list[GoodsMovement], types: set[MovementType]) -> tuple[dict, dict, dict, set]:
    """Quantity, first and last date per (reference, location, product), and references closed as final."""
    qty: dict[tuple[str, str, str], float] = defaultdict(float)
    first: dict[tuple[str, str, str], date] = {}
    last: dict[tuple[str, str, str], date] = {}
    final: set[str] = set()
    for m in movs:
        if m.type not in types or not m.reference:
            continue
        k = (m.reference, m.location, m.product)
        qty[k] += m.qty
        first[k] = min(first.get(k, m.date), m.date)
        last[k] = max(last.get(k, m.date), m.date)
        if m.final:
            final.add(m.reference)
    return qty, first, last, final


def by_ref(d: dict, ref: str, product: str, location: str | None = None) -> float:
    return sum(v for (r, lo, p), v in d.items() if r == ref and p == product and (location is None or lo == location))


def open_orders(ds: Dataset, as_of: date) -> list[OpenOrderRow]:
    movs = before(ds, as_of)
    got, *_ = _sum(movs, {MovementType.RECEIPT})
    iss, *_ = _sum(movs, {MovementType.ISSUE, MovementType.TRANSFER_OUT})
    sold, *_ = _sum(movs, {MovementType.SALE})
    rows = []
    for rc in ds.receipts:
        ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
        delivered = by_ref(got, rc.id, rc.product, rc.location)
        open_rv = sum(max(0.0, (rv.required_qty if rv.required_qty is not None else rv.qty)
                          - by_ref(iss, rc.id, rv.product, rv.location)) for rv in rc.reservations)
        transit = 0.0
        if rc.kind.value == "transfer":
            shipped = sum(v for (r, lo, p), v in iss.items() if r == rc.id and p == rc.product and lo != rc.location)
            transit = max(0.0, shipped - delivered)
        rows.append(OpenOrderRow(kind=rc.kind.value, id=rc.id, location=rc.location, product=rc.product,
                                 counterparty=counterparty(ds, rc), ordered=ordered, delivered=delivered,
                                 open=max(0.0, ordered - delivered), in_transit=transit, due_date=rc.due_date,
                                 past_due=rc.due_date < as_of and ordered - delivered > EPS,
                                 reservations_open=open_rv))
    for d in ds.demand:
        if d.kind is not DemandKind.SALES_ORDER or not d.id:
            continue
        ordered = d.ordered_qty if d.ordered_qty is not None else d.qty
        delivered = by_ref(sold, d.id, d.product)
        ship = sorted({lo for (r, lo, p) in sold if r == d.id})
        rows.append(OpenOrderRow(kind="sales", id=d.id, location=d.location, product=d.product,
                                 counterparty=ship[0] if ship else None, ordered=ordered, delivered=delivered,
                                 open=max(0.0, ordered - delivered), due_date=d.date,
                                 past_due=d.date < as_of and ordered - delivered > EPS))
    return rows


def counterparty(ds: Dataset, rc) -> str | None:
    src = rc.source or ""
    if rc.kind.value == "purchase" and src in ds.purchasing_source_by_id:
        return ds.purchasing_source_by_id[src].supplier
    if rc.kind.value == "transfer" and src in ds.lane_by_id:
        return ds.lane_by_id[src].origin
    return rc.source


def unmatched(ds: Dataset) -> list[str]:
    known = {r.id for r in ds.receipts} | {d.id for d in ds.demand if d.id} | {c.id for c in ds.closed_orders}
    return [m.id for m in ds.movements if m.reference and m.reference not in known]


# ---- forecast accuracy -------------------------------------------------------------------------------
def demand_keys(ds: Dataset) -> set[Node]:
    return {(d.location, d.product) for d in ds.demand} | {(h.location, h.product) for h in ds.history}


def sale_key(m: GoodsMovement, keys: set[Node]) -> Node:
    """Where a sale counts as demand: the customer if demand is planned there, else the shipping location."""
    if m.counterparty and (m.counterparty, m.product) in keys:
        return (m.counterparty, m.product)
    return (m.location, m.product)


def transit_days(ds: Dataset, origin: str, destination: str, product: str) -> int:
    """Whole days a shipment takes on the lane that carries it (0 when origin and destination coincide)."""
    if origin == destination:
        return 0
    for ln in ds.lanes:
        if ln.origin == origin and ln.destination == destination and ln.carries(product):
            return math.ceil(ln.planning_mode.transit_days - 1e-9)
    return 0


def arrival(ds: Dataset, ship_from: str, to: str, product: str, goods_issue: date) -> date:
    """When the demand location receives a shipment: demand dates (forecast, requested and confirmed dates)
    are delivery dates at the demand location, so a sale is measured against them on this date."""
    return goods_issue + timedelta(days=transit_days(ds, ship_from, to, product))


def sale_point(ds: Dataset, m: GoodsMovement, keys: set[Node]) -> tuple[Node, date]:
    """Where and when a sale counts as demand: at the customer on the day it arrives, if demand is planned
    there; else at the shipping location on the goods-issue date."""
    node = sale_key(m, keys)
    return node, arrival(ds, m.location, node[0], m.product, m.date)


def forecast_in(ds: Dataset, start: date, end: date) -> dict[Node, float]:
    """Forecast quantity falling in [start, end), period records spread evenly over their calendar days."""
    out: dict[Node, float] = defaultdict(float)
    for d in ds.demand:
        if d.kind is not DemandKind.FORECAST:
            continue
        n = d.period_days or 1
        lo, hi = max(d.date, start), min(d.date + timedelta(days=n), end)
        if hi > lo:
            out[(d.location, d.product)] += d.qty * (hi - lo).days / n
    return dict(out)


def sales_arrived(ds: Dataset, start: date, end: date, keys: set[Node]) -> dict[Node, float]:
    """Journal sales per demand node that arrive in [start, end)."""
    act: dict[Node, float] = defaultdict(float)
    for m in ds.movements:
        if m.type is MovementType.SALE:
            node, day = sale_point(ds, m, keys)
            if start <= day < end:
                act[node] += m.qty
    return act


def week_grid(start: date, end: date) -> list[tuple[date, date]]:
    """The weeks a roll from ``start`` to ``end`` closes: seven days each from ``start``, the last one partial."""
    out = []
    w = start
    while w < end:
        out.append((w, min(w + timedelta(days=7), end)))
        w = out[-1][1]
    return out


def accuracy_records(ds: Dataset, start: date, end: date) -> list[AccuracyRecord]:
    """One record per series and elapsed week of [start, end); sales count in the week they arrive."""
    keys = demand_keys(ds)
    out: list[AccuracyRecord] = []
    for w, we in week_grid(start, end):
        fc = forecast_in(ds, w, we)
        act = sales_arrived(ds, w, we, keys)
        for n in sorted(set(fc) | set(act)):
            out.append(AccuracyRecord(location=n[0], product=n[1], start=w, end=we, forecast=round(fc.get(n, 0.0), 6),
                                      actual=round(act.get(n, 0.0), 6)))
    return out


def refresh_actuals(ds: Dataset, records: list[AccuracyRecord],
                    weeks: Sequence[tuple[date, date]] = ()) -> list[AccuracyRecord]:
    """Closed weeks (``weeks``, and every week ``records`` logged) with their actuals re-read from the journal: a
    sale posted late for an elapsed week counts in it (a series with no forecast that week gets a record once it
    has sales, even in a week that logged nothing at the time). The forecast stays as logged."""
    keys = demand_keys(ds)
    by_week: dict[tuple[date, date], dict[Node, AccuracyRecord]] = {w: {} for w in weeks}
    for r in records:
        by_week.setdefault((r.start, r.end), {})[(r.location, r.product)] = r
    out: list[AccuracyRecord] = []
    for (w, we), recs in sorted(by_week.items()):
        act = sales_arrived(ds, w, we, keys)
        for n in sorted(set(recs) | {n for n, q in act.items() if q > EPS}):
            fc = recs[n].forecast if n in recs else 0.0
            out.append(AccuracyRecord(location=n[0], product=n[1], start=w, end=we, forecast=fc,
                                      actual=round(act.get(n, 0.0), 6)))
    return out


def _ratios(f: float, a: float, err: float) -> tuple[float | None, float | None, float | None]:
    if a <= EPS:
        return None, None, None
    wm = err / a
    return wm, (f - a) / a, max(0.0, 1.0 - wm)


def accuracy_report(records: list[AccuracyRecord]) -> AccuracyReport:
    by: dict[Node, list[AccuracyRecord]] = defaultdict(list)
    for r in records:
        by[(r.location, r.product)].append(r)
    series = []
    tf = ta = te = 0.0
    for n in sorted(by):
        rs = sorted(by[n], key=lambda r: r.start)
        f = sum(r.forecast for r in rs)
        a = sum(r.actual for r in rs)
        e = sum(abs(r.forecast - r.actual) for r in rs)
        wm, bias, acc = _ratios(f, a, e)
        series.append(AccuracySeries(location=n[0], product=n[1], forecast=f, actual=a, abs_error=e, wmape=wm,
                                     bias=bias, accuracy=acc,
                                     weeks=[AccuracyWeek(start=r.start, end=r.end, forecast=r.forecast, actual=r.actual)
                                            for r in rs]))
        tf, ta, te = tf + f, ta + a, te + e
    wm, bias, acc = _ratios(tf, ta, te)
    return AccuracyReport(series=series, forecast=tf, actual=ta, wmape=wm, bias=bias, accuracy=acc,
                          periods=len({r.start for r in records}))
