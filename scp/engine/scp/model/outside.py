"""Work done by suppliers outside our walls (Enterprise 7.1, S/4 guide §16.3 and §10.1).

* :class:`ThirdPartyOrder` is a sale the supplier ships straight to the customer (≈ S/4 item category TAS with the
  purchase order it makes): it never touches our stock and planning never sees it. The supplier's dispatch advice is
  its goods receipt and its delivery at once; the customer is billed for what was dispatched, and the supplier's
  invoice is matched against the same quantity.
* :class:`JobWorkChallan` sends a production order's parts to a job worker (≈ S/4 components provided to the vendor,
  movement 541, and the delivery challan GST asks for under rule 45 of the CGST rules): the parts leave the plant as
  issues to the order and are stock at the job worker until the processed goods come back (consumed, 543), they come
  back unused, or they are written off. Inputs not back within a year (capital goods: three) count as supplied on the
  day they were sent (section 143 of the CGST Act).
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, model_validator

from .common import Model, Ref, Unit


class DropShipment(Model):
    """The supplier's dispatch advice: what left their place for the customer, and when."""

    date: dt.date
    qty: float = Unit("qty", gt=0)
    reference: str = Field("", max_length=64, description="Their dispatch note or lorry receipt number")
    final: bool = Field(False, description="Nothing more comes: closes the order even if short")


class ThirdPartyOrder(Model):
    """A sales line bought from a supplier who ships it straight to the customer, with the purchase order it makes."""

    id: str = Field(min_length=1, max_length=20)
    customer: str = Ref("location")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    date: dt.date = Field(description="Wanted by the customer on")
    price: float = Unit("money_per_unit", description="Net sale price per unit")
    supplier: str = Ref("location", description="Who ships it")
    cost: float = Unit("money_per_unit", description="Purchase price per unit, in the supplier's currency")
    currency: str | None = Field(None, min_length=3, max_length=3, description="Purchase currency; empty = the company's")
    customer_ref: str = Field("", max_length=64, description="The customer's own order number")
    ordered_on: dt.date
    sent_on: dt.date | None = Field(None, description="When the purchase order went to the supplier")
    shipments: list[DropShipment] = Field(default_factory=list, max_length=100)
    cancelled: bool = False
    note: str = Field("", max_length=400)

    @property
    def shipped(self) -> float:
        return round(sum(s.qty for s in self.shipments), 6)

    @property
    def closed(self) -> bool:
        return self.cancelled or self.shipped >= self.qty - 1e-9 or any(s.final for s in self.shipments)


class ChallanLine(Model):
    """A part sent on the challan, at its value when it left (the taxable value GST asks the challan to show)."""

    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    value: float = Unit("money_per_unit", description="Value per unit when sent")
    capital_goods: bool = Field(False, description="A mould, die or tool: three years to come back instead of one")
    location: str = Ref("location", description="The place it left")
    movements: list[str] = Field(default_factory=list, description="The issues that took it out (one per batch)")


class ChallanReturn(Model):
    """Something that came back from the job worker, or was written off there."""

    date: dt.date
    kind: Literal["processed", "unused", "lost"] = Field(
        description="processed: the order's goods made from the parts (qty in the order's units); unused: parts back "
                    "as sent; lost: parts the job worker spoiled or lost")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    reference: str = Field("", max_length=64, description="The job worker's challan or invoice number")
    movements: list[str] = Field(default_factory=list, description="What it posted: the order's receipt, or the "
                                                                   "issues taken back")
    used: dict[str, float] = Field(default_factory=dict, description="processed: the parts it used, by product")


class JobWorkChallan(Model):
    """Parts of a production order sent to a job worker (≈ components provided to the vendor and the delivery challan
    for job work)."""

    id: str = Field(min_length=1, max_length=16, description="The challan number (GST: up to 16 characters)")
    job_worker: str = Ref("location", description="A supplier location")
    ship_from: str = Ref("location", description="The plant the parts leave")
    order: str = Field(min_length=1, max_length=64, description="The production order whose work is done outside")
    sent_on: dt.date
    lines: list[ChallanLine] = Field(min_length=1, max_length=100)
    charge: float = Unit("money_per_unit", default=0.0, description="Job charge per unit processed")
    vehicle: str = Field("", max_length=40, description="Vehicle number, printed on the challan")
    returns: list[ChallanReturn] = Field(default_factory=list, max_length=500)
    closed_on: dt.date | None = None
    cancelled: bool = False
    note: str = Field("", max_length=400)

    @model_validator(mode="after")
    def _parts(self) -> JobWorkChallan:
        if len({x.product for x in self.lines}) < len(self.lines):
            raise ValueError("a part is on the challan twice")
        return self

    @property
    def processed(self) -> float:
        return round(sum(r.qty for r in self.returns if r.kind == "processed"), 6)

    def back(self, product: str) -> tuple[float, float, float]:
        """(used in processed goods, back unused, lost) of a part."""
        used = sum(r.used.get(product, 0.0) for r in self.returns if r.kind == "processed")
        unused = sum(r.qty for r in self.returns if r.kind == "unused" and r.product == product)
        lost = sum(r.qty for r in self.returns if r.kind == "lost" and r.product == product)
        return round(used, 6), round(unused, 6), round(lost, 6)

    def at_job_worker(self, product: str) -> float:
        ln = next((x for x in self.lines if x.product == product), None)
        if ln is None or self.cancelled:
            return 0.0
        return round(max(0.0, ln.qty - sum(self.back(product))), 6)


class JobWorkSettings(Model):
    inputs_days: int = Field(365, ge=1, le=3650, description="Inputs must come back within this many days (GST: one year)")
    capital_goods_days: int = Field(1095, ge=1, le=3650,
                                    description="Capital goods must come back within this many days (GST: three years)")
    warn_days: int = Field(30, ge=0, le=365, description="A challan this close to its limit is named")
