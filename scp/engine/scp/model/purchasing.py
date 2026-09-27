"""Procure-to-pay master and document data (≈ S/4 MM purchasing), scaled to small and mid-sized buyers.

* :class:`Vendor` is the supplier's purchasing view (≈ business partner, purchasing data): how to reach them,
  terms, a purchasing block, whether they confirm orders, and how much more than ordered a goods receipt may take.
  One record per supplier location; a supplier without one buys on the defaults.
* The info record and source list live on :class:`~scp.model.master.PurchasingSource` (price, price scales, lead
  time, validity, fixed and blocked).
* :class:`PurchaseOrder` is the PO header. Its lines are the firm purchase receipts that name it (``po``): planning,
  confirmations and goods receipts already work line by line, so a line is never stored twice.
"""
from __future__ import annotations

import datetime as dt

from pydantic import Field, field_validator

from .common import Id, Model, Ref, Unit


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

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class PriceScale(Model):
    """A quantity break on an info record: from this quantity per order line, this price."""

    from_qty: float = Unit("qty", gt=0)
    price: float = Unit("money_per_unit")


class PurchaseOrder(Model):
    """A purchase order header (≈ EKKO). Lines are the purchase receipts whose ``po`` is this id."""

    id: Id
    supplier: str = Ref("location")
    location: str = Ref("location", description="Receiving location")
    order_date: dt.date
    currency: str | None = Field(None, min_length=3, max_length=3, description="Empty = company currency")
    approved: bool = Field(True, description="Released for sending (orders above the approval limit start unapproved)")
    sent_on: dt.date | None = Field(None, description="When the order went to the supplier; empty = not sent yet")
    vendor_reference: str = Field("", max_length=64, description="The supplier's order confirmation number")
    note: str = Field("", max_length=400)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class PurchasingSettings(Model):
    approval_limit: float | None = Unit(
        "money", default=None,
        description="Purchase orders worth more than this (company currency) need approval before they are sent; "
                    "empty = no approval step")
    release_window_days: int = Unit(
        "days", le=366, default=7,
        description="Requisitions whose order date falls within this many days are shown as due to order")
