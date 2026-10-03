"""Outputs of procure-to-pay (Phase E)."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from ..model import Approval, Payment, PriceScale, ConfirmedDelivery
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
    contract: str | None = None       # the contract its price comes from


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
    wanted_order_date: dt.date | None = None   # late: when it should have been ordered to arrive when needed
    choices: list[SourceChoice]
    open_later: list[str] = []        # open order lines for the same product and place that arrive after it is needed
    contract: str | None = None       # the contract its price comes from
    agreement: str | None = None      # ordering adds a delivery schedule line to this scheduling agreement


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
    confirmations: list[ConfirmedDelivery] = []   # the supplier's confirmation in several deliveries
    contract: str | None = None
    invoiced: float = 0.0                    # quantity on supplier invoices less credit memos
    returned: float = 0.0                    # quantity sent back to the supplier


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
    kind: str = "standard"            # or scheduling_agreement
    approvals: list[Approval] = []    # releases given
    levels_needed: list[str] = []     # release levels its value needs, in order
    next_level: str | None = None     # the level that releases it next
    product: str | None = None        # scheduling agreement
    valid_to: dt.date | None = None
    target_qty: float | None = None
    released_qty: float = 0.0         # scheduling agreement: on its schedule lines, open and closed


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
    terms: str = ""                   # the payment terms in words (a cash discount, or net days)
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
    blocked_invoices: int = 0
    payables_overdue: float = 0.0      # company currency
    to_invoice: int = 0                # order lines received and not invoiced


class PurchasingView(Out):
    ok: bool
    as_of: dt.date
    currency: str
    approval_limit: float | None
    totals: PurchasingTotals
    requisitions: list[Requisition]
    orders: list[PoView]
    vendors: list[VendorRow]
    payables: PayablesView | None = None


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


class ShortOrder(Out):
    """A firm order the parts no longer cover in full after a short or late receipt (R16)."""

    order: str                        # the production or transfer order
    product: str                      # what it makes or moves
    part: str                         # the part it is short of
    location: str                     # where the part is taken from
    needs: float                      # still to be issued for the order
    available: float                  # of the part, for this order, after the orders before it
    can_make: float                   # the order's quantity the part covers (what "shorten" sets it to)
    qty: float                        # the order's open quantity now
    starts: dt.date | None = None     # when the order takes the part
    complete_on: dt.date | None = None  # receipts due after it starts bring the rest on this day: late, not short


class ActionReport(Out):
    ok: bool
    message: str
    movements: list[str] = []         # goods movements posted (receive)
    doc: str | None = None            # the material document of those movements
    id: str | None = None             # the document made (supplier invoice, return, scheduling agreement)
    sent: list[str] = []              # purchase orders sent (send_all)
    short_orders: list[ShortOrder] = []   # firm orders a short receipt leaves without enough parts


class InvoiceLineView(Out):
    order: str
    product: str
    qty: float
    price: float
    amount: float
    order_price: float | None          # the purchase order's price
    received: float                    # on the order line, less returns
    invoiced: float                    # on all invoices less credit memos, this one included


class SupplierInvoiceView(Out):
    id: str
    kind: str
    supplier: str
    reference: str
    date: dt.date
    due_date: dt.date
    discount_date: dt.date | None
    discount: float
    currency: str
    net: float
    tax: float
    total: float
    settled: float
    open: float
    status: Literal["blocked", "released", "to pay", "paid", "cancelled", "credit open", "credited"]
    blocks: list[str]                  # why it was blocked when entered
    still: list[str]                   # what still stands in the way of paying it
    released_by: str
    released_on: dt.date | None
    days_overdue: int
    lines: list[InvoiceLineView]
    payments: list[Payment]
    return_id: str | None = None
    note: str = ""


class ToInvoice(Out):
    """Goods received and not yet invoiced, or invoiced and not received, per order line (≈ GR/IR clearing)."""

    order: str
    po: str | None
    supplier: str
    product: str
    location: str
    received: float
    invoiced: float
    qty: float                         # received less invoiced (negative: invoiced ahead of the goods)
    price: float | None
    value: float                       # qty × price, order currency
    currency: str
    last_receipt: dt.date | None


class PayableRow(Out):
    """What we owe one supplier (company currency)."""

    supplier: str
    name: str
    open: float                        # open invoices less open credit memos
    overdue: float
    due_soon: float                    # due within the next 7 days
    blocked: float
    not_invoiced: float                # goods received and not yet invoiced
    next_due: dt.date | None
    terms: str


class ContractLineView(Out):
    product: str
    price: float
    target_qty: float | None
    ordered: float                     # on order lines that name the contract, open and closed
    left: float | None                 # target less ordered


class ContractView(Out):
    id: str
    supplier: str
    location: str | None
    valid_from: dt.date
    valid_to: dt.date
    currency: str
    target_value: float | None
    ordered_value: float
    status: Literal["active", "not started", "expired", "used up"]
    lines: list[ContractLineView]
    attention: list[str]
    supplier_reference: str = ""
    note: str = ""


class SupplierReturnView(Out):
    id: str
    supplier: str
    order: str
    product: str
    location: str
    qty: float
    date: dt.date
    reason: str
    replace: bool
    stock_type: str
    batch: str | None
    status: Literal["to credit", "credited", "replacement due", "replaced"]
    credit_memo: str | None = None


class PayablesView(Out):
    """Invoice verification and what is owed to whom."""

    invoices: list[SupplierInvoiceView]
    to_invoice: list[ToInvoice]
    payables: list[PayableRow]
    contracts: list[ContractView]
    returns: list[SupplierReturnView]
    blocked: int
    open_value: float                  # company currency
    overdue_value: float
    not_invoiced_value: float


PurchasingView.model_rebuild()
