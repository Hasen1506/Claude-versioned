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
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..model import DemandKind, DemandRecord, Strategy


@dataclass
class IndependentReq:
    id: str
    date: date
    qty: float
    kind: str          # "forecast" | "sales_order"
    priority: int
    source_ref: str    # original demand id / index
    consumed: float = 0.0  # forecast only: quantity consumed by orders


def effective_demand(records: list[tuple[str, DemandRecord]], strategy: Strategy,
                     back_days: float, fwd_days: float) -> list[IndependentReq]:
    fcs = [IndependentReq(f"D:{rid}", r.date, r.qty, "forecast", r.priority, rid)
           for rid, r in records if r.kind is DemandKind.FORECAST]
    span = {f"D:{rid}": max(1, r.period_days or 1) for rid, r in records}
    sos = [IndependentReq(f"D:{rid}", r.date, r.qty, "sales_order", r.priority, rid)
           for rid, r in records if r.kind is DemandKind.SALES_ORDER]
    if strategy is Strategy.MTS:
        return sorted(fcs, key=_k)
    if strategy is Strategy.MTO:
        return sorted(sos, key=_k)
    fcs.sort(key=_k)
    for so in sorted(sos, key=_k):
        need = so.qty
        lo = so.date - timedelta(days=back_days)
        hi = so.date + timedelta(days=fwd_days)
        backward = [f for f in reversed(fcs) if f.date <= so.date and f.date + timedelta(days=span[f.id] - 1) >= lo]
        forward = [f for f in fcs if so.date < f.date <= hi]
        for f in backward + forward:
            if need <= 1e-12:
                break
            take = min(need, f.qty - f.consumed)
            if take > 0:
                f.consumed += take
                need -= take
    out = [IndependentReq(f.id, f.date, f.qty - f.consumed, "forecast", f.priority, f.source_ref, f.consumed)
           for f in fcs if f.qty - f.consumed > 1e-9]
    return sorted(out + sos, key=_k)


def _k(r: IndependentReq) -> tuple:
    return (r.date, 0 if r.kind == "sales_order" else 1, r.id)
