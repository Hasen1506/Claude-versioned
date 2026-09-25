"""A planning dataset: one self-contained document with all master and transactional data.

It is what the user imports/exports, what the API accepts, and (later) what a plan version
snapshots. Lookup helpers build id indices lazily; they never mutate the data.
"""
from __future__ import annotations

from functools import cached_property
from typing import Literal

from pydantic import Field

from .common import LocationType, Model
from .demand import DemandEvent, ForecastOverride, ForecastSettings, NpiRule
from .inventory import InventorySettings
from .promise import Allocation, Confirmation, PromiseSettings
from .schedule import Changeover, ScheduleSettings
from .sop import SopSettings
from .master import (
    Calendar, Location, LocationProduct, Product, ProductionSource, PurchasingSource, Resource,
    Settings, TransportLane,
)
from .transactional import DemandRecord, SalesHistory, ScheduledReceipt


class Dataset(Model):
    schema_version: Literal["1"] = "1"
    settings: Settings
    calendars: list[Calendar] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    location_products: list[LocationProduct] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    production_sources: list[ProductionSource] = Field(default_factory=list)
    purchasing_sources: list[PurchasingSource] = Field(default_factory=list)
    lanes: list[TransportLane] = Field(default_factory=list)
    demand: list[DemandRecord] = Field(default_factory=list)
    receipts: list[ScheduledReceipt] = Field(default_factory=list)
    history: list[SalesHistory] = Field(default_factory=list)
    forecasting: ForecastSettings = Field(default_factory=ForecastSettings)
    events: list[DemandEvent] = Field(default_factory=list)
    npi: list[NpiRule] = Field(default_factory=list)
    overrides: list[ForecastOverride] = Field(default_factory=list)
    inventory: InventorySettings = Field(default_factory=InventorySettings)
    sop: SopSettings = Field(default_factory=SopSettings)
    changeovers: list[Changeover] = Field(default_factory=list)
    scheduling: ScheduleSettings = Field(default_factory=ScheduleSettings)
    allocations: list[Allocation] = Field(default_factory=list)
    confirmations: list[Confirmation] = Field(default_factory=list)
    promising: PromiseSettings = Field(default_factory=PromiseSettings)

    # ---- indices (first occurrence wins; duplicates are reported by the readiness gate) ----
    @cached_property
    def location_by_id(self) -> dict[str, Location]:
        return _index(self.locations)

    @cached_property
    def product_by_id(self) -> dict[str, Product]:
        return _index(self.products)

    @cached_property
    def calendar_by_id(self) -> dict[str, Calendar]:
        return _index(self.calendars)

    @cached_property
    def resource_by_id(self) -> dict[str, Resource]:
        return _index(self.resources)

    @cached_property
    def production_source_by_id(self) -> dict[str, ProductionSource]:
        return _index(self.production_sources)

    @cached_property
    def purchasing_source_by_id(self) -> dict[str, PurchasingSource]:
        return _index(self.purchasing_sources)

    @cached_property
    def lane_by_id(self) -> dict[str, TransportLane]:
        return _index(self.lanes)

    @cached_property
    def location_product_by_key(self) -> dict[tuple[str, str], LocationProduct]:
        out: dict[tuple[str, str], LocationProduct] = {}
        for lp in self.location_products:
            out.setdefault((lp.location, lp.product), lp)
        return out

    def location_type(self, loc_id: str) -> LocationType | None:
        loc = self.location_by_id.get(loc_id)
        return loc.type if loc else None


def _index(items: list) -> dict:
    out: dict = {}
    for it in items:
        out.setdefault(it.id, it)
    return out
