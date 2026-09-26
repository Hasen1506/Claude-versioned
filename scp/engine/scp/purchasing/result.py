"""Outputs of procure-to-pay (Phase E)."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from ..model import PriceScale
from ..model.common import Out


class SourceChoice(Out):
    """A supplier that could fill a requisition, with its terms for this quantity."""

    source_id: str
    supplier: str
    price: float                      # per unit for this line's quantity, in ``currency``, before duty
    currency: str
    value: float                      # the line in company currency, duty included
    qty: float                        # the quantity after this source's minimum and rounding
    lead_time_days: float
    arrives: dt.date                  # delivery date if ordered on the requisition's order date (or today)
    days_late: int                    # after the date it is needed at the receiving place (0 = in time)
    fixed: bool
    assigned: bool                    # the source planning chose
    blocked: str = ""                 # why it cannot be used ("" = usable)


class Requisition(Out):
    """A planned purchase (≈ purchase requisition from MRP): what to buy, from whom, by when."""

    id: str                           # the planned order id
    location: str
    product: str
    qty: float
    need_date: dt.date
    order_date: dt.date               # when to place the order (the planned order's start)
    due_date: dt.date                 # delivery date asked of the supplier
    source_id: str
    supplier: str
    price: float
    currency: str
    value: float                      # company currency, duty included
    due_now: bool                     # to order within the release window
    late: bool                        # should already have been ordered
    choices: list[SourceChoice]


class PoLine(Out):
    id: str
    product: str
    ordered: float
    received: float                   # all goods receipts posted against the line (any date)
    open: float
    price: float | None
    value: float                      # ordered × price, order currency
    due_date: dt.date
    confirmed_date: dt.date | None
    confirmed_qty: float | None
    expected_date: dt.date
    status: str                       # plain words: awaiting confirmation, confirmed late, partly received, closed…
    days_late: int                    # expected after due, or still open past today
    closed: bool
    last_receipt: dt.date | None = None
    source: str | None = None


class PoView(Out):
    id: str
    header: bool                      # False: an open purchase receipt without an order document (e.g. imported)
    supplier: str | None
    location: str
    order_date: dt.date | None
    currency: str
    approved: bool
    sent_on: dt.date | None
    vendor_reference: str
    note: str
    status: Literal["awaiting approval", "to send", "awaiting confirmation", "confirmed", "sent", "partly received",
                    "received", "closed"]
    value: float                      # order currency
    open_value: float                 # order currency
    lines: list[PoLine]
    attention: list[str]              # what needs doing, in plain words


class InfoRecord(Out):
    source_id: str
    product: str
    location: str
    price: float
    currency: str
    price_scales: list[PriceScale]
    moq: float
    rounding_qty: float | None
    lead_time_days: float
    valid_from: dt.date | None
    valid_to: dt.date | None
    fixed: bool
    blocked: bool
    priority: int
    quota: float | None
    vendor_material: str


class VendorRow(Out):
    supplier: str
    name: str
    has_record: bool                  # a purchasing record is kept (else the defaults apply)
    blocked: bool
    block_reason: str
    confirmation_required: bool
    payment_terms_days: int
    currency: str
    open_lines: int
    open_value: float                 # company currency
    closed_lines: int
    on_time: float | None             # share of closed lines fully delivered by their due date
    in_full: float | None             # share of closed lines delivered within tolerance
    avg_days_late: float | None       # over the closed lines that were late
    confirmed_late: int               # closed and open lines the supplier confirmed after the requested date
    last_delivery: dt.date | None
    info_records: list[InfoRecord]


class PurchasingTotals(Out):
    requisitions: int
    due_now: int
    due_now_value: float
    late_to_order: int
    open_orders: int
    open_value: float
    awaiting_approval: int
    to_send: int
    confirmations_overdue: int
    late_lines: int


class PurchasingView(Out):
    ok: bool
    as_of: dt.date
    currency: str
    approval_limit: float | None
    totals: PurchasingTotals
    requisitions: list[Requisition]
    orders: list[PoView]
    vendors: list[VendorRow]


class CreatedPo(Out):
    id: str
    supplier: str
    location: str
    currency: str
    value: float                      # order currency
    lines: list[str]                  # line ids
    approved: bool
    notes: list[str]


class CreateReport(Out):
    ok: bool
    created: list[CreatedPo]
    lines: dict[str, str]             # requisition id → purchase order line id
    skipped: dict[str, str]           # requisition id → why


class ActionReport(Out):
    ok: bool
    message: str
    movements: list[str] = []         # goods movements posted (receive)
