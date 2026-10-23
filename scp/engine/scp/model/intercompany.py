"""Several companies in one network (Enterprise 7.3, S/4 guide §17.5).

* :class:`LegalEntity` is a company of the group with its own books and tax registration (≈ S/4 company code). A
  place belongs to one (``Location.entity``); a place without one belongs to the company itself (its settings).
* :class:`TransferPrice` says what one company charges another for what it ships (≈ the inter-company price
  condition): a fixed price, the cost plus a mark-up, or the selling price less a margin (the OECD resale-price
  method). The most specific rule wins: a product's before all products, a named seller and buyer before any.
* :class:`IntercompanyInvoice` bills a stock transfer between companies, or between two GST registrations of one
  company (a supply between distinct persons, schedule I of the CGST Act): GST on the transfer price, CGST and SGST
  inside one state, IGST across. Its lines are the shipments (the transfer's goods issues); a shipment taken back
  after billing is credited on a credit note.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, model_validator

from .common import Id, Model, Ref, Unit
from .sales import Payment


class LegalEntity(Model):
    id: Id
    name: str = Field("", max_length=120)
    tax_id: str = Field("", max_length=40, description="Its tax registration (GSTIN, VAT number), printed on its "
                                                       "invoices; a place's own registration goes before it")
    region: str = Field("", max_length=40, description="Its state or region for the place of supply; empty = from "
                                                       "the GSTIN")
    address: str = Field("", max_length=400, json_schema_extra={"x-multiline": True},
                         description="Its registered address, a line per row, printed on its invoices")
    invoice_prefix: str = Field("", max_length=8, pattern=r"^[A-Za-z0-9/-]*$",
                                description="The start of its inter-company invoice numbers (GST: a series of its "
                                            "own, 16 characters in all); empty = IC-<id>/")


class TransferPrice(Model):
    id: Id
    seller: str | None = Ref("entity", default=None, description="The company that ships; empty = any")
    buyer: str | None = Ref("entity", default=None, description="The company that receives; empty = any")
    product: str | None = Ref("product", default=None, description="Empty = every product")
    method: Literal["cost_plus", "fixed", "resale_minus"] = Field(
        "cost_plus", description="cost_plus: the planned unit value where it leaves, plus the mark-up; fixed: the "
                                 "price; resale_minus: the product's selling price less the margin")
    markup: float = Unit("fraction", le=10, default=0.0,
                         description="cost_plus: the mark-up on cost (0.08 = 8 %); resale_minus: the margin taken off")
    price: float | None = Unit("money_per_unit", default=None, description="fixed: the price per base unit")
    valid_from: dt.date | None = Field(None, description="From this day of shipping; empty = always")

    @model_validator(mode="after")
    def _priced(self) -> TransferPrice:
        if self.method == "fixed" and self.price is None:
            raise ValueError("a fixed transfer price needs a price")
        if self.method == "resale_minus" and self.markup >= 1:
            raise ValueError("a resale margin is less than the whole price")
        return self


class IntercompanyLine(Model):
    movement: str = Field(min_length=1, max_length=64, description="The shipment (the transfer's goods issue)")
    order: str = Field(min_length=1, max_length=64, description="The stock transfer")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    price: float = Unit("money_per_unit", description="The transfer price per base unit, before tax")
    tax_rate: float = Unit("fraction", le=1, default=0.0)

    @property
    def net(self) -> float:
        return round(self.qty * self.price, 2)

    @property
    def tax(self) -> float:
        return round(self.net * self.tax_rate, 2)


class IntercompanyInvoice(Model):
    id: str = Field(min_length=1, max_length=16, description="The invoice number (GST: up to 16 characters)")
    kind: Literal["invoice", "credit_note"] = "invoice"
    date: dt.date
    seller: str = Field("", max_length=64, description="The company that shipped; empty = the company itself")
    buyer: str = Field("", max_length=64, description="The company that received; empty = the company itself")
    ship_from: str = Ref("location")
    ship_to: str = Ref("location")
    split: Literal["", "cgst_sgst", "igst"] = Field("", description="How the GST shows: CGST and SGST in one state, "
                                                                    "IGST across; empty = one tax")
    lines: list[IntercompanyLine] = Field(min_length=1, max_length=500)
    cancelled: bool = False
    note: str = Field("", max_length=400)
    payments: list[Payment] = Field(default_factory=list, description="Settled between the companies: the buyer's "
                                                                       "payments (paid back, for a credit note)")

    @property
    def net(self) -> float:
        return round(sum(ln.net for ln in self.lines), 2)

    @property
    def tax(self) -> float:
        return round(sum(ln.tax for ln in self.lines), 2)

    @property
    def total(self) -> float:
        return round(self.net + self.tax, 2)

    @property
    def open(self) -> float:
        """Still to settle (paid to the seller, or paid back to the buyer for a credit note)."""
        return 0.0 if self.cancelled else round(max(0.0, self.total - sum(p.amount + p.discount
                                                                          for p in self.payments)), 2)

    @property
    def sign(self) -> float:
        return -1.0 if self.kind == "credit_note" else 1.0
