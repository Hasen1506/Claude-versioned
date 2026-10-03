"""Order-to-cash master and document data (≈ S/4 SD), scaled to small and mid-sized sellers.

* :class:`PaymentTerms`: when an invoice is due and the cash discount for paying early (≈ ZTERM).
* :class:`Customer` is the customer's sales view (≈ business partner, sales area data): how to reach them, payment
  terms, a credit limit, a discount on everything they buy, the tax rate on their invoices and a sales block. One record
  per customer location; a customer without one sells on the defaults.
* :class:`SalesOrder` is the order header (≈ VBAK). Its lines are the sales-order demand records that name it
  (``order``): promising, deliveries and the weekly roll already work line by line, so a line is never stored twice.
* :class:`Quotation` is an offer with a validity (≈ a quotation, VA21): its lines are not demand until it is won.
* :class:`Delivery` is an outbound delivery (≈ LIKP/LIPS): picked, packed, goods issued (the sale movements), and
  proof of delivery.
* :class:`Invoice` is a billing document (≈ VBRK/VBRP), an invoice or a credit note, with the payments received.
* :class:`ReturnOrder` is a customer return (≈ a returns order with its returns delivery): goods come back into stock
  as a receipt that names it, and a credit note pays the customer back.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .actuals import StockType
from .common import Id, Model, Ref, Unit

DOC_ID = r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"


class PaymentTerms(Model):
    """When an invoice is due, and the cash discount for paying early (e.g. 2 % within 10 days, net 30)."""

    id: Id
    name: str = Field("", max_length=80)
    net_days: int = Unit("days", le=365, default=30, description="Pay within this many days of the invoice date")
    discount_days: int = Unit("days", le=365, default=0, description="Paid within this many days, the cash discount "
                                                                      "applies (0 = no cash discount)")
    discount: float = Unit("fraction", lt=1, default=0.0, description="Cash discount for paying early (0.02 = 2 %)")

    @model_validator(mode="after")
    def _days(self) -> PaymentTerms:
        if self.discount_days > self.net_days:
            raise ValueError("the cash discount period cannot be longer than the payment period")
        if self.discount > 0 and not self.discount_days:
            raise ValueError("a cash discount needs the days it applies within")
        return self

    def text(self) -> str:
        net = f"net {self.net_days} days" if self.net_days else "due at once"
        if self.discount > 0:
            return f"{self.discount * 100:g} % within {self.discount_days} days, {net}"
        return net


class Customer(Model):
    """A customer's sales data (≈ customer master, sales area view)."""

    customer: str = Ref("location", description="The customer location this record describes")
    contact: str = Field("", max_length=120, description="Who to talk to")
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    payment_terms: str | None = Ref("payment_terms", default=None,
                                    description="Empty = the company's default payment terms")
    credit_limit: float | None = Unit(
        "money", default=None,
        description="Most the customer may owe: open orders, delivered and not invoiced, and unpaid invoices. A new "
                    "order beyond it is blocked for delivery until someone releases it. Empty = no credit check")
    discount: float = Unit("fraction", lt=1, default=0.0,
                           description="Discount on every line the customer orders (0.05 = 5 %), after quantity scales")
    tax_rate: float | None = Unit("fraction", le=1, default=None,
                                  description="Tax on the customer's invoices; empty = the company's rate")
    incoterms: str = Field("", max_length=40, description="Delivery terms, e.g. DAP Mumbai")
    blocked: bool = Field(False, description="Sales block: no new orders or quotations; open ones are still delivered")
    block_reason: str = Field("", max_length=200)


class SalesSettings(Model):
    payment_terms: str | None = Ref("payment_terms", default=None,
                                    description="Payment terms for customers without their own; empty = net 30 days")
    tax_rate: float = Unit("fraction", le=1, default=0.0, description="Tax on invoices (0.18 = 18 %)")
    credit_check: bool = Field(True, description="Orders beyond a customer's credit limit are blocked for delivery")
    quotation_days: int = Unit("days", ge=1, le=366, default=30, description="How long a new quotation is valid")
    delivery_days: int = Unit("days", le=60, default=3,
                              description="Order lines promised to ship within this many days are listed to deliver")


class SalesOrder(Model):
    """A sales order header (≈ VBAK). Lines are the sales-order demand records whose ``order`` is this id."""

    id: Id
    customer: str = Ref("location")
    order_date: dt.date
    customer_ref: str = Field("", max_length=64, description="The customer's own order number")
    payment_terms: str | None = Ref("payment_terms", default=None, description="Empty = the customer's")
    quotation: str | None = Field(None, max_length=64, description="The quotation the order was won from")
    credit_block: bool = Field(False, description="Over the customer's credit limit: not delivered until released")
    credit_note: str = Field("", max_length=200, description="Why it was blocked, or who released it")
    confirmation_sent_on: dt.date | None = Field(None, description="When the order confirmation went to the customer")
    note: str = Field("", max_length=400)
    erp_ref: str = Field("", max_length=64, description="The order's number in the ERP it came from")


class QuoteLine(Model):
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    date: dt.date = Field(description="Wanted on")
    price: float = Unit("money_per_unit", description="Net price per unit offered")
    list_price: float | None = Unit("money_per_unit", default=None, description="Before scales and discounts")


class Quotation(Model):
    """An offer to a customer (≈ a quotation): its lines become an order's lines when it is won."""

    id: Id
    customer: str = Ref("location")
    quote_date: dt.date
    valid_to: dt.date
    customer_ref: str = Field("", max_length=64, description="The customer's enquiry number")
    payment_terms: str | None = Ref("payment_terms", default=None, description="Empty = the customer's")
    lines: list[QuoteLine] = Field(min_length=1, max_length=200)
    status: Literal["open", "won", "lost"] = "open"
    order: str | None = Field(None, max_length=64, description="The order it became")
    lost_reason: str = Field("", max_length=200)
    note: str = Field("", max_length=400)

    @model_validator(mode="after")
    def _valid(self) -> Quotation:
        if self.valid_to < self.quote_date:
            raise ValueError("a quotation cannot end before it is made")
        return self


class DeliveryLine(Model):
    order: str = Field(min_length=1, max_length=64, description="The sales order line delivered")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0, description="To deliver")
    picked: float | None = Unit("qty", default=None, description="Picked; empty = not picked yet")
    batch: str | None = Field(None, max_length=40, description="Batch to pick (empty = first expiring)")
    final: bool = Field(False, description="Closes the order line even if short")
    received: float | None = Unit("qty", default=None, description="Proof of delivery: what the customer signed for; "
                                                                    "empty = all of it")


class Delivery(Model):
    """An outbound delivery (≈ LIKP): picked, packed, then goods issued, which posts the sale movements."""

    id: Id
    customer: str = Ref("location")
    ship_from: str = Ref("location")
    created_on: dt.date
    planned_on: dt.date = Field(description="Planned goods issue")
    lines: list[DeliveryLine] = Field(min_length=1, max_length=200)
    packages: int | None = Field(None, ge=1, le=100000, description="Packed: number of packages; empty = not packed")
    gross_kg: float | None = Unit("kg", default=None, description="Packed: gross weight")
    issued_on: dt.date | None = Field(None, description="Goods issue posted; empty = not shipped yet")
    movements: list[str] = Field(default_factory=list, description="The sale movements posted at goods issue")
    pod_on: dt.date | None = Field(None, description="Proof of delivery: when the customer received it")
    pod_by: str = Field("", max_length=120, description="Who signed for it")
    pod_note: str = Field("", max_length=200)
    note: str = Field("", max_length=400)

    @property
    def status(self) -> str:
        if self.pod_on:
            return "delivered"
        if self.issued_on:
            return "shipped"
        if self.packages:
            return "packed"
        if any(x.picked is not None for x in self.lines):
            return "picked"
        return "to pick"


class InvoiceLine(Model):
    order: str | None = Field(None, max_length=64, description="The sales order line billed")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    price: float = Unit("money_per_unit", description="Net price per unit")
    movements: list[str] = Field(default_factory=list, description="Invoice: the sale movements billed")
    ret: str | None = Field(None, max_length=64, description="Credit note: the return it pays back")

    @property
    def amount(self) -> float:
        return round(self.qty * self.price, 2)


class Payment(Model):
    date: dt.date
    amount: float = Unit("money", gt=0)
    reference: str = Field("", max_length=64, description="Bank reference")
    discount: float = Unit("money", default=0.0, description="Cash discount taken with this payment")


class Invoice(Model):
    """A billing document (≈ VBRK): an invoice for goods delivered, or a credit note for goods returned or a price
    put right. Its amounts are fixed when it is made; payments are recorded against it."""

    id: Id
    kind: Literal["invoice", "credit_note"] = "invoice"
    customer: str = Ref("location")
    date: dt.date
    due_date: dt.date
    discount_date: dt.date | None = Field(None, description="Paid by this day, the cash discount applies")
    discount: float = Unit("fraction", lt=1, default=0.0, description="Cash discount for paying by the discount date")
    payment_terms: str | None = Ref("payment_terms", default=None)
    lines: list[InvoiceLine] = Field(min_length=1, max_length=500)
    tax_rate: float = Unit("fraction", le=1, default=0.0)
    payments: list[Payment] = Field(default_factory=list)
    reference: str | None = Field(None, max_length=64, description="Credit note: the invoice it credits")
    sent_on: dt.date | None = None
    cancelled: bool = Field(False, description="Cancelled: it no longer counts as owed")
    note: str = Field("", max_length=400)

    @property
    def net(self) -> float:
        return round(sum(x.amount for x in self.lines), 2)

    @property
    def tax(self) -> float:
        return round(self.net * self.tax_rate, 2)

    @property
    def total(self) -> float:
        return round(self.net + self.tax, 2)

    @property
    def settled(self) -> float:
        """Paid, with any cash discount taken."""
        return round(sum(p.amount + p.discount for p in self.payments), 2)

    @property
    def open(self) -> float:
        """Still owed (an invoice) or still to pay back (a credit note)."""
        return 0.0 if self.cancelled else round(max(0.0, self.total - self.settled), 2)


class ReturnOrder(Model):
    """A customer return (≈ a returns order): agreed, then received into stock, then paid back with a credit note."""

    id: Id
    customer: str = Ref("location")
    order: str | None = Field(None, max_length=64, description="The sales order line the goods were sold on")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    price: float = Unit("money_per_unit", description="Paid back per unit")
    location: str = Ref("location", description="Where the goods come back to")
    reason: str = Field("", max_length=200)
    created_on: dt.date
    stock_type: StockType = Field(StockType.QUALITY, description="The stock the goods come back into: checked first "
                                                                 "(quality), held (blocked), or ready to sell")
    batch: str | None = Field(None, max_length=40, description="The batch coming back")
    received_on: dt.date | None = None
    received_qty: float | None = Unit("qty", default=None)
    movements: list[str] = Field(default_factory=list, description="The receipts posted")
    credit_note: str | None = Field(None, max_length=64, description="The credit note that paid it back")
    note: str = Field("", max_length=400)

    @field_validator("received_qty")
    @classmethod
    def _pos(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("a return is received with a positive quantity")
        return v

    @property
    def status(self) -> str:
        if self.credit_note:
            return "credited"
        if self.received_on:
            return "received"
        return "expected"
