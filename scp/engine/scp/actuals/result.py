"""Outputs of the execution stage (P7)."""
from __future__ import annotations

import datetime as dt

from ..model import AccuracyRecord, ClosedOrder
from ..model.common import Out


class StockRow(Out):
    location: str
    product: str
    master_on_hand: float                 # LocationProduct.on_hand as maintained / last rolled
    movement_stock: float | None          # Σ movements before the as-of date (None: no movements)
    difference: float                     # max(0, movement stock) − master (0 when there are no movements)
    movements: int
    last_date: dt.date | None
    by_type: dict[str, float]             # signed quantity per movement type
    negative_on: dt.date | None = None    # first date the running balance went below zero


class OpenOrderRow(Out):
    kind: str                             # sales | purchase | production | transfer
    id: str
    location: str
    product: str
    counterparty: str | None
    ordered: float
    delivered: float
    open: float
    in_transit: float = 0.0               # transfers: issued at the origin, not yet received
    due_date: dt.date
    past_due: bool
    reservations_open: float = 0.0        # components / goods at the origin still to be issued


class AccuracyWeek(Out):
    start: dt.date
    end: dt.date
    forecast: float
    actual: float


class AccuracySeries(Out):
    location: str
    product: str
    forecast: float
    actual: float
    abs_error: float
    wmape: float | None                   # Σ|F−A| / ΣA (None: no actuals)
    bias: float | None                    # (ΣF − ΣA) / ΣA: > 0 over-forecast
    accuracy: float | None                # max(0, 1 − WMAPE)
    weeks: list[AccuracyWeek]


class AccuracyReport(Out):
    series: list[AccuracySeries]
    forecast: float
    actual: float
    wmape: float | None
    bias: float | None
    accuracy: float | None
    periods: int                          # distinct weeks logged


class ActualsView(Out):
    as_of: dt.date
    stock: list[StockRow]
    open_orders: list[OpenOrderRow]
    accuracy: AccuracyReport
    movements: int
    unmatched: list[str]                  # movement ids whose reference matches no open or closed order


class StockChange(Out):
    location: str
    product: str
    before: float
    after: float


class OrderChange(Out):
    kind: str
    id: str
    location: str
    product: str
    open_before: float
    open_after: float
    closed: bool


class RollReport(Out):
    ok: bool
    from_date: dt.date
    to_date: dt.date
    stock: list[StockChange]
    orders: list[OrderChange]
    closed: list[ClosedOrder]
    accuracy: list[AccuracyRecord]
    forecast_dropped: float
    forecast_prorated: int
    history_added: int
    confirmations_trimmed: int
    warnings: list[str]


class FirmedOrder(Out):
    planned_id: str
    receipt_id: str
    kind: str
    location: str
    product: str
    qty: float
    start_date: dt.date
    due_date: dt.date
    reservations: int


class FirmReport(Out):
    ok: bool
    firmed: list[FirmedOrder]
    skipped: dict[str, str]               # planned order id → reason
