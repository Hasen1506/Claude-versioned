"""Transport (Enterprise 6.3, S/4 guide §14, a small TM): carriers and their rates, freight orders and their cost.

A carrier's rate says what a vehicle on a lane (or on any lane of a mode) costs: so much a shipment, a kilogram and a
cubic metre, never less than a minimum, in a vehicle of so many kilograms and cubic metres. A freight order is one
vehicle: the deliveries and stock transfers it carries from one place to another, planned on a day, its load and what
it should cost. It is tendered to a carrier, accepted (or rejected, and tendered to the next), shipped (the goods
issues of what it carries) and settled with the carrier's bill, whose cost is shared over what was carried by weight.
"""
from __future__ import annotations

import datetime as dt

from pydantic import Field, model_validator

from .common import Id, Model, Ref, TransportMode, Unit
from .sales import Payment


class FreightRate(Model):
    """What one vehicle costs on a lane (≈ TM freight agreement rate table)."""

    lane: str = Ref("lane", default="", description="The lane (empty: every lane of the mode)")
    mode: TransportMode = TransportMode.TRUCK_FTL
    per_shipment: float = Unit("money", default=0.0, description="A vehicle, whatever it carries")
    per_kg: float = Unit("money_per_kg", default=0.0)
    per_m3: float = Unit("money_per_m3", default=0.0)
    min_charge: float = Unit("money", default=0.0, description="A vehicle never costs less")
    capacity_kg: float | None = Unit("kg", gt=0, default=None, description="Empty: the lane's vehicle")
    capacity_m3: float | None = Unit("m3", gt=0, default=None, description="Empty: the lane's vehicle")


class Carrier(Model):
    """A transport company and its rates."""

    id: Id
    name: str = Field("", max_length=120)
    rates: list[FreightRate] = Field(min_length=1, max_length=200)
    payment_days: int = Field(30, ge=0, le=365, description="Days to pay its freight bill")
    blocked: bool = Field(False, description="Not tendered to")
    note: str = Field("", max_length=400)


FREIGHT_STATUS = r"^(planned|tendered|accepted|shipped|settled|cancelled)$"


class FreightBillCredit(Model):
    """The original bill and the carrier's later full credit, kept together in the journal."""

    bill: str = Field("", max_length=64)
    billed: float = Unit("money", ge=0)
    settled_on: dt.date
    reference: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=200)
    date: dt.date
    due_on: dt.date | None = Field(None, exclude_if=lambda day: day is None)
    entered_by: str = Field("", max_length=200, exclude_if=lambda actor: not actor)


class FreightOrder(Model):
    """One vehicle from one place to another (≈ TM freight order): what it carries, its load and its cost."""

    id: str = Field(min_length=1, max_length=20)
    lane: str = Ref("lane")
    mode: TransportMode
    carrier: str | None = Ref("carrier", default=None, description="Empty: the lane's own cost, no carrier yet")
    ship_from: str = Ref("location")
    ship_to: str = Ref("location")
    planned_on: dt.date = Field(description="Loading")
    deliveries: list[str] = Field(default_factory=list, max_length=200)
    transfers: list[str] = Field(default_factory=list, max_length=200, description="Stock transfer orders")
    purchases: list[str] = Field(default_factory=list, max_length=200,
                                 description="Purchase order lines collected from the supplier (we pay the carriage)")
    weight_kg: float = Unit("kg", default=0.0)
    volume_m3: float = Unit("m3", default=0.0)
    weights: dict[str, float] = Field(default_factory=dict, description="Kilograms of each delivery and transfer")
    units: dict[str, float] = Field(default_factory=dict, description="Units of each delivery and transfer")
    capacity_kg: float | None = Unit("kg", gt=0, default=None)
    capacity_m3: float | None = Unit("m3", gt=0, default=None)
    planned_cost: float = Unit("money", default=0.0)
    status: str = Field("planned", pattern=FREIGHT_STATUS)
    tendered_on: dt.date | None = None
    accepted_on: dt.date | None = None
    rejected_by: list[str] = Field(default_factory=list, max_length=50, description="Carriers that turned it down")
    shipped_on: dt.date | None = None
    bill: str = Field("", max_length=64, description="Settled: the carrier's bill number")
    billed: float | None = Unit("money", default=None, description="Settled: what the carrier billed")
    settled_on: dt.date | None = None
    note: str = Field("", max_length=400)
    bill_credits: list[FreightBillCredit] = Field(default_factory=list, exclude_if=lambda credits: not credits)
    bill_due_on: dt.date | None = Field(None, exclude_if=lambda day: day is None)
    bill_entered_by: str = Field("", max_length=200, exclude_if=lambda actor: not actor)
    bill_payments: list[Payment] = Field(default_factory=list, exclude_if=lambda payments: not payments)

    def bill_voucher(self, index: int | None = None) -> str:
        ordinal = len(self.bill_credits) if index is None else index
        return self.id if ordinal == 0 else f"{self.id}/B{ordinal + 1}"

    @model_validator(mode="after")
    def _carries(self) -> FreightOrder:
        if not self.deliveries and not self.transfers and not self.purchases:
            raise ValueError("a freight order carries at least one delivery, stock transfer or purchase")
        if self.bill_credits:
            last = self.shipped_on
            if last is None or self.status not in ("shipped", "settled"):
                raise ValueError("credited freight retains its shipment and billing history")
            for credit in self.bill_credits:
                if not last <= credit.settled_on <= credit.date:
                    raise ValueError("freight bills and credits must be in posting order")
                last = credit.date
            if self.status == "settled" and (self.billed is None or self.settled_on is None or self.settled_on < last):
                raise ValueError("the replacement freight bill must follow its preceding credit")
            if self.status == "shipped" and (self.bill or self.billed is not None or self.settled_on is not None):
                raise ValueError("credited freight has no active bill until it is billed again")
        if self.bill_due_on or self.bill_entered_by or self.bill_payments:
            if self.status != "settled" or self.billed is None or self.settled_on is None:
                raise ValueError("freight terms and payments require an active posted bill")
            if self.bill_due_on and self.bill_due_on < self.settled_on:
                raise ValueError("a freight bill cannot be due before posting")
            if self.bill_payments and not self.carrier:
                raise ValueError("a carrier payment requires a named carrier")
            references = {p.reference.casefold() for p in self.bill_payments}
            if ("" in references or len(references) != len(self.bill_payments)
                    or any(p.date < self.settled_on or p.discount or p.fx_rate is not None
                           or round(p.amount, 2) != p.amount for p in self.bill_payments)
                    or sum(round(p.amount * 100) for p in self.bill_payments) > round(self.billed * 100)):
                raise ValueError("invalid freight payment dates, references or amounts")
        return self


class TransportSettings(Model):
    window_days: int = Field(0, ge=0, le=14, description="Loads due within this many days of the first share a "
                                                          "vehicle, the later ones sent early")
    horizon_days: int = Field(7, ge=0, le=60, description="Deliveries, transfers and collections loading this far ahead are planned")
    low_fill: float = Unit("fraction", default=0.5, le=1, description="A vehicle filled less than this is named")
