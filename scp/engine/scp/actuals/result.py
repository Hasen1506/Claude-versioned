"""Outputs of the execution stage (P7)."""
from __future__ import annotations

import datetime as dt

from ..model import AccuracyRecord, ClosedOrder
from ..model.common import Out


class LotRow(Out):
    batch: str | None                     # None: stock without a batch
    stock_type: str                       # unrestricted | quality | blocked
    qty: float
    made_on: dt.date | None = None
    expires_on: dt.date | None = None
    expired: bool = False                 # past its last day on the as-of date: planning no longer counts it


class StockRow(Out):
    location: str
    product: str
    master_on_hand: float                 # LocationProduct.on_hand as maintained / last rolled
    movement_stock: float | None          # Σ movements before the as-of date (None: no movements)
    difference: float                     # max(0, movement stock) − master (0 when there are no movements)
    movements: int
    last_date: dt.date | None
    by_type: dict[str, float]             # signed quantity per movement type
    negative_on: dt.date | None = None    # when the balance went below zero: still is, or did in the last week
    opening_from_setup: bool = False      # on-hand typed at setup counts as the opening balance (journalled at the next roll)
    # the stock there is now (at the planning start: this week's postings included), by kind:
    unrestricted: float = 0.0             # free to use (expired batches included: see ``expired``)
    quality: float = 0.0                  # in quality inspection
    blocked: float = 0.0
    expired: float = 0.0                  # unrestricted or inspection stock of batches past their last day
    lots: list[LotRow] = []               # by batch and stock type (only when there is more than plain unrestricted)
    serials: list[str] = []               # serial numbers here
    in_transit: float = 0.0               # shipped to this place on a transfer and not yet received
    planning_stock: float | None = None   # what the plan starts from: usable stock before the as-of date (None: no movements)
    counting: str | None = None           # an open physical inventory document that counts it


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
    planned_as: str | None = None         # the planned order it was firmed from


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


class Unbooked(Out):
    """Postings dated before the planning start that the starting position does not reflect yet (a late posting, or
    one dated in a week already rolled): what moving the plan to the same start again would change."""

    needed: bool
    movements: int                        # movements dated before the start (the journal the position comes from)
    stock: int                            # places whose starting stock would change
    orders: int                           # firm and sales orders whose open quantity would change or that would close
    accuracy_weeks: int                   # rolled weeks whose actual sales would change
    history_days: int                     # sales-history days that would change
    closed: int                           # closed orders whose deliveries would change


class YieldRow(Out):
    """One part of one production version: the loss its bill of materials plans with and the loss measured on the
    orders posted with actual usage (R17)."""

    source: str
    location: str
    product: str                          # what is made
    part: str
    orders: int                           # orders posted with actual usage
    made: float                           # good units they made
    planned: float                        # what the bill of materials says they take, its loss included
    used: float                           # what they used
    scrap_now: float                      # the part's loss in the bill of materials (component scrap)
    scrap_measured: float                 # the loss that would have planned what was used
    change: bool                          # they differ by half a point or more


class ActualsView(Out):
    as_of: dt.date
    stock: list[StockRow]
    open_orders: list[OpenOrderRow]
    accuracy: AccuracyReport
    movements: int
    unmatched: list[str]                  # movement ids whose reference matches no open or closed order
    unbooked: Unbooked | None = None      # None when the view is not as of the planning start
    yields: list[YieldRow] = []           # parts' measured loss against the bill of materials


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
    purchase_orders: list[str] = []       # purchase orders created for the firmed buys (grouped as Buying does)
    notes: list[str] = []                 # from those orders: approval needed, below a supplier's minimum, …
    sent: list[str] = []                  # of those orders, the ones sent to their suppliers (``send``)
