"""Planning strategies and forecast consumption (S/4 guide §5.2, §5.4).

MTS          forecast drives supply; sales orders are not planning-relevant (SAP 10)
MTS_CONSUME  sales orders consume forecast: backward first (nearest earlier bucket outward),
             then forward, within the consumption windows; orders are demand (SAP 40).
             A forecast for a period (``period_days``) covers every day of it, so an order first
             consumes the forecast of the period it falls in, however far into the period it is:
             an S&OP release dated at the start of the month is consumed by that month's orders.
MTO          sales orders only; forecast ignored (SAP 20)
ATO          as MTS_CONSUME for quantities; supply created for forecast is flagged
             non-convertible until an order arrives (SAP 50)

Reduction by delivered orders (S/4 guide §5.1, §17.2, §20.1 #1 "a PIR is consumed exactly once"). The roll-forward
keeps each forecast as it was entered (``original_date``/``original_period_days``/``original_qty``, written when its
period begins) and only moves the record's own date, period and quantity to what is left of the period by time. At
every plan the consumption is worked out again from scratch, from the original forecasts and every order:

1. what orders already delivered took (the delivered part of an open order, and closed orders from the closed-order
   log) consumes the ORIGINAL forecasts, with the node's windows; an order dated before the node's earliest forecast
   period is left out (it consumed a forecast that is gone, or a forecast made after it);
2. a forecast keeps for the rest of its period what neither the elapsed days nor those deliveries took, whichever
   took more: of the record's quantity, the deliveries beyond the elapsed share come off;
3. open orders then consume what is left (strategy 40/50), matched by the original periods, so an order dated early
   in a period that has since begun still consumes that period's forecast.

Nothing is carried from one roll to the next but the original forecast and the journal, so rolling a week and then
another plans exactly what rolling two weeks at once does. Forecast 100 over four weeks, 80 ordered and delivered in
week one, roll two weeks: 50 is left by time, deliveries took 80, so 20 is planned (not 50, which planned 130 for a
period whose forecast was 100).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..model import DemandKind, DemandRecord, Strategy

EPS = 1e-9


@dataclass
class IndependentReq:
    id: str
    date: date
    qty: float
    kind: str          # "forecast" | "sales_order"
    priority: int
    source_ref: str    # original demand id / index
    consumed: float = 0.0  # forecast only: quantity consumed by orders


def original_window(r: DemandRecord) -> tuple[date, int, float]:
    """The forecast as it was entered: first day, days covered, quantity (the record itself until its period began)."""
    od = getattr(r, "original_date", None)
    if od is None:
        return r.date, max(1, r.period_days or 1), r.qty
    oq = getattr(r, "original_qty", None)
    return od, max(1, getattr(r, "original_period_days", None) or 1), r.qty if oq is None else oq


def _consume(fcs: list[tuple[str, date, int]], cap: dict[str, float], orders: list[tuple[date, float]],
             back_days: float, fwd_days: float) -> dict[str, float]:
    """Each order, in date order, takes from the forecasts ``fcs`` ((id, first day, days) sorted by first day): backward
    first (the nearest period at or before the order's date, outward, within the backward window), then forward
    (periods starting after it, within the forward window), at most ``cap`` of each. Returns what each forecast gave."""
    took: dict[str, float] = {f[0]: 0.0 for f in fcs}
    for when, qty in orders:
        need = qty
        lo = when - timedelta(days=back_days)
        hi = when + timedelta(days=fwd_days)
        backward = [f for f in reversed(fcs) if f[1] <= when and f[1] + timedelta(days=f[2] - 1) >= lo]
        forward = [f for f in fcs if when < f[1] <= hi]
        for fid, _, _ in backward + forward:
            if need <= 1e-12:
                break
            take = min(need, cap[fid] - took[fid])
            if take > 0:
                took[fid] += take
                need -= take
    return took


def delivered_orders(ds, node: tuple[str, str], records: list[tuple[str, DemandRecord]]) -> list[tuple[date, float]]:
    """What orders at ``node`` already delivered, on their requested dates: the delivered part of open orders (ordered
    less open) and the closed sales orders of the closed-order log. Orders dated before the node's earliest forecast
    period are left out: what they consumed is gone with the period they fell in."""
    starts = [original_window(r)[0] for _, r in records if r.kind is DemandKind.FORECAST]
    if not starts:
        return []
    first = min(starts)
    out: list[tuple[date, str, float]] = []
    for rid, r in records:
        ordered = getattr(r, "ordered_qty", None)
        if r.kind is DemandKind.SALES_ORDER and ordered is not None and ordered - r.qty > EPS and r.date >= first:
            out.append((r.date, f"D:{rid}", ordered - r.qty))
    for c in getattr(ds, "closed_orders", None) or []:
        if (c.kind == "sales" and (c.location, c.product) == node and c.delivered_qty > EPS
                and c.due_date >= first):
            out.append((c.due_date, f"C:{c.id}", c.delivered_qty))
    return [(d, q) for d, _, q in sorted(out)]


def elapsed_share(ds, r: DemandRecord) -> float:
    """Of a forecast whose period has begun, the part due on the working days before the record's date (the date the
    roll moved it to), on the place's calendar: what time alone took of it."""
    od = getattr(r, "original_date", None)
    if od is None or r.date <= od:
        return 0.0
    from .leadtime import location_calendar
    start, span, qty = original_window(r)
    cal = location_calendar(ds, r.location)
    days = [start + timedelta(days=k) for k in range(span)]
    work = [d for d in days if cal.is_workday(d)] or [start]
    return qty * sum(d < r.date for d in work) / len(work)


def effective_demand(records: list[tuple[str, DemandRecord]], strategy: Strategy,
                     back_days: float, fwd_days: float, ds=None, node: tuple[str, str] | None = None
                     ) -> list[IndependentReq]:
    """The node's independent requirements by strategy: forecasts after reduction by delivered orders (when ``ds``
    and ``node`` are given) and consumption by open orders, plus the orders."""
    fcs = [IndependentReq(f"D:{rid}", r.date, r.qty, "forecast", r.priority, rid)
           for rid, r in records if r.kind is DemandKind.FORECAST]
    sos = [IndependentReq(f"D:{rid}", r.date, r.qty, "sales_order", r.priority, rid)
           for rid, r in records if r.kind is DemandKind.SALES_ORDER]
    if strategy is Strategy.MTO:
        return sorted(sos, key=_k)
    src = {f"D:{rid}": r for rid, r in records}
    win = {f.id: original_window(src[f.id]) for f in fcs}
    order = sorted(fcs, key=lambda f: (win[f.id][0], f.date, f.id))
    windows = [(f.id, win[f.id][0], win[f.id][1]) for f in order]
    # ① what delivered orders took of the original forecasts; ② what of the record that leaves for the rest of it
    if ds is not None and node is not None:
        delivered = delivered_orders(ds, node, records)
        if delivered:
            took = _consume(windows, {f.id: win[f.id][2] for f in fcs}, delivered, back_days, fwd_days)
            for f in fcs:
                beyond = took[f.id] - elapsed_share(ds, src[f.id])
                if beyond > EPS:
                    f.qty = max(0.0, f.qty - beyond)
    if strategy is Strategy.MTS:
        return sorted([f for f in fcs if f.qty > 1e-9 or f.qty == src[f.id].qty], key=_k)
    # ③ open orders consume what is left, matched by the original periods
    took = _consume(windows, {f.id: f.qty for f in fcs}, [(so.date, so.qty) for so in sorted(sos, key=_k)],
                    back_days, fwd_days)
    out = [IndependentReq(f.id, f.date, f.qty - took[f.id], "forecast", f.priority, f.source_ref, took[f.id])
           for f in fcs if f.qty - took[f.id] > 1e-9]
    return sorted(out + sos, key=_k)


def _k(r: IndependentReq) -> tuple:
    return (r.date, 0 if r.kind == "sales_order" else 1, r.id)
