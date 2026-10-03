"""Procure-to-pay master and document data (≈ S/4 MM purchasing), scaled to small and mid-sized buyers.

* :class:`Vendor` is the supplier's purchasing view (≈ business partner, purchasing data): how to reach them,
  terms, a purchasing block, whether they confirm orders, and how much more than ordered a goods receipt may take.
  One record per supplier location; a supplier without one buys on the defaults.
* The info record and source list live on :class:`~scp.model.master.PurchasingSource` (price, price scales, lead
  time, validity, fixed and blocked).
* :class:`PurchaseOrder` is the PO header. Its lines are the firm purchase receipts that name it (``po``): planning,
  confirmations and goods receipts already work line by line, so a line is never stored twice. A scheduling
  agreement is a header of its own kind for one product: its delivery schedule lines are receipts naming it.
* :class:`PurchaseContract` is an outline agreement (≈ quantity or value contract): agreed prices for a period that
  orders release against.
* :class:`SupplierInvoice` is a supplier's invoice or credit memo checked against the order and the goods received
  (≈ MIRO, three-way match); :class:`SupplierReturn` sends goods back (≈ return delivery, movement 122).
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .actuals import StockType
from .common import Id, Model, Ref, Unit
from .sales import Payment


class Vendor(Model):
    """A supplier's purchasing data (≈ vendor master, purchasing organisation view)."""

    supplier: str = Ref("location", description="The supplier location this record describes")
    contact: str = Field("", max_length=120, description="Who to talk to")
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    currency: str | None = Field(None, min_length=3, max_length=3,
                                 description="Order currency; empty = the price's currency on each source")
    payment_terms_days: int = Unit("days", le=365, default=30, description="Pay this many days after the invoice")
    incoterms: str = Field("", max_length=40, description="Delivery terms, e.g. FCA Pune")
    blocked: bool = Field(False, description="Purchasing block: planning and new purchase orders skip this supplier; "
                                             "open orders are still received")
    block_reason: str = Field("", max_length=200)
    confirmation_required: bool = Field(False, description="The supplier confirms each order (date and quantity)")
    confirmation_days: int = Unit("days", le=60, default=3,
                                  description="A confirmation is overdue this many days after the order is sent")
    over_delivery_tolerance: float | None = Unit(
        "fraction", le=5, default=0.1,
        description="A goods receipt may take this much more than ordered; empty = no limit")
    under_delivery_tolerance: float = Unit(
        "fraction", le=0.5, default=0.0,
        description="A delivery this much short of the order closes the line (final delivery)")
    min_order_value: float = Unit("money", default=0.0, description="Smallest order the supplier accepts")
    payment_terms: str | None = Ref("payment_terms", default=None,
                                    description="Payment terms with a cash discount (empty: net `payment_terms_days`)")
    tax_rate: float | None = Unit("fraction", le=1, default=None,
                                  description="Tax on this supplier's invoices (empty: the purchasing default)")

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class PriceScale(Model):
    """A quantity break on an info record: from this quantity per order line, this price."""

    from_qty: float = Unit("qty", gt=0)
    price: float = Unit("money_per_unit")


class Approval(Model):
    """One release of a purchase order at one level of the release strategy."""

    level: str = Field(min_length=1, max_length=60)
    by: str = Field("", max_length=200, description="Who released it")
    on: dt.date


class PurchaseOrder(Model):
    """A purchase order header (≈ EKKO). Lines are the purchase receipts whose ``po`` is this id.

    A scheduling agreement (``kind``) is a long-running order for one product from one supplier: planning adds
    delivery schedule lines to it instead of making new orders, and each changed schedule is sent again."""

    id: Id
    kind: Literal["standard", "scheduling_agreement"] = "standard"
    supplier: str = Ref("location")
    location: str = Ref("location", description="Receiving location")
    order_date: dt.date
    currency: str | None = Field(None, min_length=3, max_length=3, description="Empty = company currency")
    approved: bool = Field(True, description="Released for sending (orders above the approval limit start unapproved)")
    sent_on: dt.date | None = Field(None, description="When the order went to the supplier; empty = not sent yet")
    vendor_reference: str = Field("", max_length=64, description="The supplier's order confirmation number")
    note: str = Field("", max_length=400)
    approvals: list[Approval] = Field(default_factory=list, description="Releases given, level by level")
    product: str | None = Ref("product", default=None, description="Scheduling agreement: the product")
    valid_to: dt.date | None = Field(None, description="Scheduling agreement: no schedule lines after this day")
    target_qty: float | None = Unit("qty", gt=0, default=None,
                                    description="Scheduling agreement: the quantity agreed over its life")

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class ReleaseLevel(Model):
    """A level of the release strategy: orders worth more than ``above`` need a release at this level, in order of
    the amounts. ``approvers``: who may release at this level (e-mail addresses); empty = anyone who may change the
    company. One person never releases two levels of the same order."""

    name: str = Field(min_length=1, max_length=60)
    above: float = Unit("money", description="Orders worth more than this (company currency) need this level")
    approvers: list[str] = Field(default_factory=list, max_length=50)


class ContractLine(Model):
    product: str = Ref("product")
    price: float = Unit("money_per_unit", description="Agreed price per base unit, in the contract's currency")
    target_qty: float | None = Unit("qty", gt=0, default=None, description="Quantity agreed over the contract")


class PurchaseContract(Model):
    """An outline agreement (≈ contract): prices agreed with a supplier for a period. Purchase orders for its products
    made while it is valid take its price and name it; what was ordered is set against its targets."""

    id: Id
    supplier: str = Ref("location")
    location: str | None = Ref("location", default=None, description="Receiving place (empty: any of ours)")
    valid_from: dt.date
    valid_to: dt.date
    currency: str | None = Field(None, min_length=3, max_length=3, description="Empty = company currency")
    target_value: float | None = Unit("money", gt=0, default=None, description="Value agreed over the contract")
    lines: list[ContractLine] = Field(min_length=1)
    supplier_reference: str = Field("", max_length=64, description="The supplier's own contract number")
    note: str = Field("", max_length=400)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @model_validator(mode="after")
    def _dates(self) -> PurchaseContract:
        if self.valid_to < self.valid_from:
            raise ValueError("a contract cannot end before it starts")
        if len({x.product for x in self.lines}) < len(self.lines):
            raise ValueError("a product is on the contract twice")
        return self


class SupplierInvoiceLine(Model):
    order: str = Field(min_length=1, max_length=64, description="The purchase order line invoiced")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    price: float = Unit("money_per_unit", description="Price per unit as invoiced, before tax")

    @property
    def amount(self) -> float:
        return round(self.qty * self.price, 2)


class SupplierInvoice(Model):
    """A supplier's invoice or credit memo (≈ MIRO). Checked when entered against the order's price and the goods
    received (three-way match); a difference beyond tolerance blocks it for payment until someone releases it, or
    until the goods it bills arrive."""

    id: Id
    kind: Literal["invoice", "credit_memo"] = "invoice"
    supplier: str = Ref("location")
    reference: str = Field("", max_length=64, description="The supplier's invoice number")
    date: dt.date
    due_date: dt.date
    discount_date: dt.date | None = None
    discount: float = Unit("fraction", lt=1, default=0.0)
    currency: str | None = Field(None, min_length=3, max_length=3, description="Empty = company currency")
    lines: list[SupplierInvoiceLine] = Field(min_length=1)
    tax: float = Unit("money", default=0.0, description="Tax on the invoice, as the supplier charged it")
    blocks: list[str] = Field(default_factory=list, description="Why it was blocked for payment when entered")
    released_by: str = Field("", max_length=200)
    released_on: dt.date | None = None
    payments: list[Payment] = Field(default_factory=list)
    return_id: str | None = Field(None, max_length=64, description="Credit memo: the return it credits")
    cancelled: bool = False
    note: str = Field("", max_length=400)

    @property
    def net(self) -> float:
        return round(sum(x.amount for x in self.lines), 2)

    @property
    def total(self) -> float:
        return round(self.net + self.tax, 2)

    @property
    def settled(self) -> float:
        return round(sum(p.amount + p.discount for p in self.payments), 2)

    @property
    def open(self) -> float:
        return 0.0 if self.cancelled else round(self.total - self.settled, 2)


class SupplierReturn(Model):
    """Goods sent back to the supplier (≈ return delivery): taken out of stock against the order line, so the line
    counts that much less received. ``replace``: the supplier sends new goods (the line is open again for them);
    otherwise a credit memo is expected."""

    id: Id
    supplier: str = Ref("location")
    order: str = Field(min_length=1, max_length=64, description="The purchase order line the goods came on")
    product: str = Ref("product")
    location: str = Ref("location", description="Where the goods leave from")
    qty: float = Unit("qty", gt=0)
    date: dt.date
    reason: str = Field("", max_length=200)
    stock_type: StockType = StockType.BLOCKED
    batch: str | None = Field(None, max_length=64)
    replace: bool = False
    movement: str | None = Field(None, max_length=64, description="The goods movement that took them out")
    credit_memo: str | None = Field(None, max_length=64)


class PurchasingSettings(Model):
    approval_limit: float | None = Unit(
        "money", default=None,
        description="Purchase orders worth more than this (company currency) need approval before they are sent; "
                    "empty = no approval step")
    release_window_days: int = Unit(
        "days", le=366, default=7,
        description="Requisitions whose order date falls within this many days are shown as due to order")
    release_levels: list[ReleaseLevel] = Field(
        default_factory=list, max_length=10,
        description="Release strategy: levels by order value (empty: the approval limit is the one level)")
    price_tolerance: float = Unit("fraction", le=1, default=0.02,
                                  description="An invoiced price this much over the order's price blocks the invoice")
    amount_tolerance: float = Unit("money", default=1.0,
                                   description="Differences up to this much per line never block an invoice")
    tax_rate: float = Unit("fraction", le=1, default=0.0, description="Tax on supplier invoices, unless the supplier "
                                                                     "has its own")
