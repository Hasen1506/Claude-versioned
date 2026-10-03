"""Stock, open quantities and forecast accuracy from the goods-movement journal (pure functions)."""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from ..model import AccuracyRecord, Dataset, DemandKind, GoodsMovement, LocationType, MovementType, StockType
from ..plan.leadtime import location_calendar, transit_whole_days
from .lots import Lot, batch_index, usable
from .result import AccuracyReport, AccuracySeries, AccuracyWeek, LotRow, OpenOrderRow, StockRow

EPS = 1e-6
Node = tuple[str, str]


def movement_ids(ds: Dataset, taken: Iterable[str] = ()) -> Iterable[str]:
    """Fresh journal numbers (GM-00001, …) after the highest one used by the journal and ``taken``."""
    n = 0
    for mid in [m.id for m in ds.movements] + list(taken):
        x = re.fullmatch(r"GM-(\d+)", mid)
        if x:
            n = max(n, int(x.group(1)))
    while True:
        n += 1
        yield f"GM-{n:05d}"


def pending_openings(ds: Dataset) -> list[GoodsMovement]:
    """Stock typed in during setup that the journal does not hold yet.

    On-hand in the planning policies is the stock at the planning start. A place with no movement dated before the
    start has nothing in the journal to derive it from, so its on-hand is its opening balance: an opening movement
    the day before the start. The roll-forward writes these into the journal, after which the journal alone decides."""
    start = ds.settings.planning_start
    seen = {(m.location, m.product) for m in ds.movements if m.date < start}
    ids = movement_ids(ds)
    return [GoodsMovement(id=next(ids), date=start - timedelta(days=1), type=MovementType.OPENING, location=lp.location,
                          product=lp.product, qty=round(lp.on_hand, 6), note="Opening balance: stock entered at setup")
            for lp in ds.location_product_by_key.values()      # a record kept twice: the one planning uses
            if lp.on_hand > EPS and (lp.location, lp.product) not in seen]


def before(ds: Dataset, as_of: date) -> list[GoodsMovement]:
    """The journal before ``as_of``, with setup stock not yet in it as opening balances."""
    return [m for m in [*ds.movements, *pending_openings(ds)] if m.date < as_of]


def stock(movs: list[GoodsMovement]) -> dict[Node, float]:
    """On-hand per node = Σ signed movements."""
    out: dict[Node, float] = defaultdict(float)
    for m in movs:
        out[(m.location, m.product)] += m.signed
    return dict(out)


COUNTED = {MovementType.ADJUSTMENT, MovementType.OPENING}   # what a stock count posts


def stock_rows(ds: Dataset, as_of: date) -> list[StockRow]:
    """Stock per place and product: what the plan starts from (the journal before ``as_of``) and, at the planning start,
    the batches, stock types and serial numbers there are now, this week's postings included (they are what a
    release, a block or a scrap acts on)."""
    movs = sorted(before(ds, as_of), key=lambda m: (m.date, m.id))
    by_node: dict[Node, list[GoodsMovement]] = defaultdict(list)
    for m in movs:
        by_node[(m.location, m.product)].append(m)
    now_node: dict[Node, list[GoodsMovement]] = by_node
    if as_of == ds.settings.planning_start:
        now_node = defaultdict(list)
        for m in sorted([*ds.movements, *pending_openings(ds)], key=lambda m: (m.date, m.id)):
            now_node[(m.location, m.product)].append(m)
    transit = in_transit(ds)
    nodes = (set(by_node) | set(now_node) | {(lp.location, lp.product) for lp in ds.location_products if lp.on_hand > 0}
             | set(transit))
    setup = {(m.location, m.product) for m in pending_openings(ds)}
    bi = batch_index(ds)
    counting = {(it.location, it.product): d.id for d in ds.inventory_docs if d.status == "open" for it in d.items}
    rows = []
    for n in sorted(nodes):
        lp = ds.location_product_by_key.get(n)
        master = lp.on_hand if lp else 0.0
        ms = by_node.get(n, [])
        # a dip below zero is reported while it lasts, or when it began in the week just closed (a late receipt
        # can still be posted for it); an older dip the stock came back from has had its say at that week's roll,
        # and one a count ended is settled: the count says what is there. Only unrestricted stock can be issued,
        # so that is the stock that dips
        bal, neg, dip = 0.0, None, None
        by_type: dict[str, float] = defaultdict(float)
        by_lot: dict[tuple[str | None, StockType], float] = defaultdict(float)
        serials: dict[str, float] = defaultdict(float)
        total = plan = 0.0
        for m in ms:
            total += m.signed
            rec = bi.get((n[1], m.batch)) if m.batch else None
            if usable(ds, Lot(m.batch, m.stock_type, m.signed, rec.expires_on if rec else None), as_of):
                plan += m.signed
        for m in now_node.get(n, []):
            by_lot[(m.batch, m.stock_type)] += m.signed
            for sn in m.serials:
                serials[sn] += 1.0 if m.signed > 0 else -1.0
        for m in ms:
            by_type[m.type.value] += m.signed
            if m.stock_type is not StockType.UNRESTRICTED:
                continue
            bal += m.signed
            if bal < -EPS:
                dip = dip or m.date
            elif dip is not None:
                if neg is None and dip >= as_of - timedelta(days=7) and m.type not in COUNTED:
                    neg = dip
                dip = None
        if neg is None and dip is not None:
            neg = dip
        lots = []
        kinds = {"unrestricted": 0.0, "quality": 0.0, "blocked": 0.0}
        expired = 0.0
        for (b, t), q in sorted(by_lot.items(), key=lambda kv: (kv[0][0] is not None, kv[0][0] or "", kv[0][1].value)):
            if abs(q) <= EPS:
                continue
            rec = bi.get((n[1], b)) if b else None
            lot = Lot(b, t, q, rec.expires_on if rec else None)
            kinds[t.value] += q
            gone = lot.expired(as_of) and t is not StockType.BLOCKED
            expired += q if gone else 0.0
            lots.append(LotRow(batch=b, stock_type=t.value, qty=round(q, 6), made_on=rec.made_on if rec else None,
                               expires_on=lot.expires_on, expired=lot.expired(as_of)))
        plain = len(lots) == 1 and lots[0].batch is None and lots[0].stock_type == "unrestricted"
        rows.append(StockRow(location=n[0], product=n[1], master_on_hand=master,
                             movement_stock=round(total, 6) if ms else None,
                             difference=round(max(0.0, plan) - master, 6) if ms else 0.0, movements=len(ms),
                             last_date=ms[-1].date if ms else None, by_type=dict(by_type), negative_on=neg,
                             opening_from_setup=n in setup, unrestricted=round(kinds["unrestricted"], 6),
                             quality=round(kinds["quality"], 6), blocked=round(kinds["blocked"], 6),
                             expired=round(expired, 6), in_transit=round(transit.get(n, 0.0), 6),
                             planning_stock=round(plan, 6) if ms else None, lots=[] if plain else lots,
                             serials=sorted(k for k, v in serials.items() if v > 0.5), counting=counting.get(n)))
    return rows


def in_transit(ds: Dataset) -> dict[Node, float]:
    """Stock in transit to each place: shipped on an open transfer and not yet received there (every posting, as the
    open orders show it). It belongs to the receiving place: planning counts it as the transfer's open receipt."""
    moved: dict[tuple[str, str], float] = defaultdict(float)
    for m in ds.movements:
        if m.reference and m.type in (MovementType.TRANSFER_OUT, MovementType.RECEIPT):
            moved[(m.reference, m.type.value)] += m.net
    out: dict[Node, float] = defaultdict(float)
    transfers = [r for r in ds.receipts if r.kind.value == "transfer"] + [
        c for c in ds.closed_orders if c.kind == "transfer"]
    for rc in transfers:
        q = moved.get((rc.id, "transfer_out"), 0.0) - moved.get((rc.id, "receipt"), 0.0)
        if q > EPS:
            out[(rc.location, rc.product)] += q
    return dict(out)


def _sum(movs: list[GoodsMovement], types: set[MovementType]) -> tuple[dict, dict, dict, set]:
    """Quantity, first and last date per (reference, location, product), and references closed as final. Receipts
    count less what went back to the supplier against the same order line."""
    qty: dict[tuple[str, str, str], float] = defaultdict(float)
    first: dict[tuple[str, str, str], date] = {}
    last: dict[tuple[str, str, str], date] = {}
    final: set[str] = set()
    reversed_ids = {m.reversal_of for m in movs if m.reversal_of}
    back = MovementType.RECEIPT in types
    for m in movs:
        if back and m.type is MovementType.RETURN and m.reference:
            qty[(m.reference, m.location, m.product)] -= m.net
            continue
        if m.type not in types or not m.reference:
            continue
        k = (m.reference, m.location, m.product)
        qty[k] += m.net
        if not m.reversal_of and m.id not in reversed_ids:
            first[k] = min(first.get(k, m.date), m.date)
            last[k] = max(last.get(k, m.date), m.date)
        if m.final and not m.reversal_of and m.id not in reversed_ids:
            final.add(m.reference)
    return qty, first, last, final


def by_ref(d: dict, ref: str, product: str, location: str | None = None) -> float:
    return sum(v for (r, lo, p), v in d.items() if r == ref and p == product and (location is None or lo == location))


def open_orders(ds: Dataset, as_of: date) -> list[OpenOrderRow]:
    """Every firm and sales order with what has been received, shipped and issued against it so far (all postings,
    whatever their date: an order received this week shows as received now, not after the next roll)."""
    movs = list(ds.movements)
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
                                 reservations_open=open_rv, planned_as=rc.planned_as))
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


def sale_key(ds: Dataset, m: GoodsMovement, keys: set[Node]) -> Node:
    """Where a sale counts as demand: the customer if demand is planned there; a sale without a customer from a place
    that plans no demand of its own and ships the product to one channel only, that channel (a dispatch register
    often has no customer column); else the shipping location."""
    if m.counterparty and (m.counterparty, m.product) in keys:
        return (m.counterparty, m.product)
    if not m.counterparty and (m.location, m.product) not in ds.demand_nodes:
        channels = {ln.destination for ln in ds.lanes if ln.origin == m.location
                    and (not ln.products or m.product in ln.products)
                    and ds.location_type(ln.destination) is LocationType.CUSTOMER
                    and (ln.destination, m.product) in keys}
        if len(channels) == 1:
            return (channels.pop(), m.product)
    return (m.location, m.product)


def transit_days(ds: Dataset, origin: str, destination: str, product: str) -> int:
    """Whole days a shipment takes on the lane that carries it (0 when origin and destination coincide)."""
    if origin == destination:
        return 0
    for ln in sorted(ds.lanes, key=lambda ln: (ln.priority, ln.id)):
        if ln.origin == origin and ln.destination == destination and ln.carries(product):
            return transit_whole_days(ln.planning_mode.transit_days)
    return 0


def arrival(ds: Dataset, ship_from: str, to: str, product: str, goods_issue: date) -> date:
    """When the demand location receives a shipment: demand dates (forecast, requested and confirmed dates)
    are delivery dates at the demand location, so a sale is measured against them on this date."""
    return goods_issue + timedelta(days=transit_days(ds, ship_from, to, product))


def sale_point(ds: Dataset, m: GoodsMovement, keys: set[Node]) -> tuple[Node, date]:
    """Where and when a sale counts as demand: at the customer on the day it arrives, if demand is planned
    there; else at the shipping location on the goods-issue date."""
    if m.reversal_of:
        m = next((x for x in ds.movements if x.id == m.reversal_of), m)
    node = sale_key(ds, m, keys)
    return node, arrival(ds, m.location, node[0], m.product, m.date)


def forecast_days(ds: Dataset, d) -> list[date]:
    cal = location_calendar(ds, d.location)
    days = [d.date + timedelta(days=i) for i in range(d.period_days or 1)]
    return [day for day in days if cal.is_workday(day)] or [d.date]


def forecast_in(ds: Dataset, start: date, end: date) -> dict[Node, float]:
    """Forecast quantity falling in [start, end), using MRP's workday distribution."""
    out: dict[Node, float] = defaultdict(float)
    for d in ds.demand:
        if d.kind is not DemandKind.FORECAST:
            continue
        days = forecast_days(ds, d)
        share = sum(start <= day < end for day in days)
        if share:
            out[(d.location, d.product)] += d.qty * share / len(days)
    return dict(out)


def sales_arrived(ds: Dataset, start: date, end: date, keys: set[Node]) -> dict[Node, float]:
    """Journal sales per demand node that arrive in [start, end)."""
    act: dict[Node, float] = defaultdict(float)
    for m in ds.movements:
        if m.type is MovementType.SALE:
            node, day = sale_point(ds, m, keys)
            if start <= day < end:
                act[node] += m.net
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
