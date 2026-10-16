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

    @model_validator(mode="after")
    def _carries(self) -> FreightOrder:
        if not self.deliveries and not self.transfers:
            raise ValueError("a freight order carries at least one delivery or stock transfer")
        return self


class TransportSettings(Model):
    window_days: int = Field(0, ge=0, le=14, description="Loads due within this many days of the first share a "
                                                          "vehicle, the later ones sent early")
    horizon_days: int = Field(7, ge=0, le=60, description="Deliveries and transfers loading this far ahead are planned")
    low_fill: float = Unit("fraction", default=0.5, le=1, description="A vehicle filled less than this is named")
