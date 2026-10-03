"""Outputs of order to cash (Phase M)."""
from __future__ import annotations

import datetime as dt

from pydantic import Field

from ..actuals.result import FirmedOrder
from ..model.common import Out
from ..promise.result import OrderPromise


class SalesReport(Out):
    """What an order-to-cash action did, in plain words, and the documents it made or changed."""

    ok: bool = True
    message: str
    documents: list[str] = []             # the orders, quotations, deliveries, invoices or returns made or changed
    movements: list[str] = []             # goods movements posted
    promises: list[OrderPromise] = []     # a new order's lines as promised
    firmed: list[FirmedOrder] = []        # production and transfers made firm for them (R13)
    credit_block: bool = False            # the order is over the customer's credit limit


class OrderLineView(Out):
    id: str
    product: str
    qty: float                            # ordered
    delivered: float
    invoiced: float
    returned: float
    open: float                           # still to deliver (0 when the line is closed)
    on_delivery: float                    # on a delivery not shipped yet
    date: dt.date                         # wanted on
    promised: dt.date | None = None       # the last confirmed date
    ship_from: str | None = None
    price: float | None = None            # net per unit
    list_price: float | None = None       # before discounts
    discount: float = 0.0
    value: float | None = None            # ordered × net price
    closed: bool = False
    cancelled: bool = False


class OrderView(Out):
    id: str
    customer: str
    order_date: dt.date
    customer_ref: str = ""
    payment_terms: str                    # in words
    quotation: str | None = None
    credit_block: bool = False
    credit_note: str = ""
    confirmation_sent_on: dt.date | None = None
    lines: list[OrderLineView] = []
    value: float | None = None
    status: str                           # open · partly delivered · delivered · invoiced · cancelled · credit block
    header: bool = True                   # False: an order of one line taken before order headers existed


class QuotationView(Out):
    id: str
    customer: str
    quote_date: dt.date
    valid_to: dt.date
    status: str                           # open · expired · won · lost
    value: float
    lines: int
    order: str | None = None


class DeliveryView(Out):
    id: str
    customer: str
    ship_from: str
    planned_on: dt.date
    status: str                           # to pick · picked · packed · shipped · delivered
    qty: float
    lines: int
    packages: int | None = None
    gross_kg: float | None = None
    issued_on: dt.date | None = None
    pod_on: dt.date | None = None
    short: float = 0.0                    # signed for less than shipped at proof of delivery
    invoiced: bool = False


class TaxPart(Out):
    name: str                             # Tax · CGST · SGST · IGST
    rate: float
    base: float                           # the amount it is charged on
    amount: float


class InvoiceView(Out):
    id: str
    kind: str
    customer: str
    date: dt.date
    due_date: dt.date
    net: float
    tax: float
    total: float
    open: float
    status: str                           # open · overdue · paid · cancelled · part paid
    days_overdue: int = 0
    discount_until: dt.date | None = None
    discount_amount: float = 0.0          # the cash discount if paid by then
    reminder_level: int = 0               # the last payment reminder sent
    reminded_on: dt.date | None = None
    reminder_due: int = 0                 # the reminder it has reached and not had yet (0: none)
    tax_parts: list[TaxPart] = Field(default_factory=list)   # per rate, split into CGST and SGST or IGST (N123)


class ReturnView(Out):
    id: str
    customer: str
    product: str
    qty: float
    received_qty: float | None = None
    status: str
    value: float
    order: str | None = None
    credit_note: str | None = None


class ToDeliver(Out):
    """An order line due to ship and not on a delivery yet."""

    order: str
    header: str
    customer: str
    product: str
    qty: float
    ship_from: str | None
    ship_date: dt.date
    credit_block: bool = False


class ToBill(Out):
    """Goods delivered and not invoiced yet."""

    order: str
    customer: str
    product: str
    qty: float
    price: float | None
    value: float | None
    delivered_on: dt.date
    movements: list[str]


class CustomerRow(Out):
    customer: str
    credit_limit: float | None = None
    open_orders: float                    # value still to deliver
    to_bill: float                        # delivered, not invoiced
    receivable: float                     # unpaid invoices less credit notes not paid out
    exposure: float
    overdue: float
    headroom: float | None = None         # credit limit less exposure
    payment_terms: str
    blocked: bool = False
    reminder_due: int = 0                 # the highest payment reminder an overdue invoice has reached and not had


class SalesView(Out):
    currency: str
    as_of: dt.date
    orders: list[OrderView] = []
    quotations: list[QuotationView] = []
    deliveries: list[DeliveryView] = []
    invoices: list[InvoiceView] = []
    returns: list[ReturnView] = []
    to_deliver: list[ToDeliver] = []
    to_bill: list[ToBill] = []
    customers: list[CustomerRow] = []
