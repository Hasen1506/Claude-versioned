"""Inventory-optimisation settings (blueprint §5): defaults for demand variability, the service
time promised to customers (multi-echelon placement) and the DDMRP buffer-profile factors."""
from __future__ import annotations

from pydantic import model_validator

from .common import Model, Unit


class InventorySettings(Model):
    default_demand_cv: float = Unit(
        "fraction", le=5, default=0.3,
        description="Weekly forecast-error CV used where a location-product has no demand_cv")
    customer_service_days: float = Unit(
        "days", le=365, default=0.0,
        description="Service time promised to customers: 0 = ship from stock (MEIO outbound service limit)")
    # ---- DDMRP buffer profile
    adu_window_days: int = Unit("days", ge=1, le=365, default=28,
                                description="Average daily usage: forward window over requirements")
    order_cycle_days: float = Unit("days", default=7.0, description="Imposed order cycle (green-zone floor)")
    lt_short_days: float = Unit("days", default=14.0, description="Decoupled lead time up to this is 'short'")
    lt_long_days: float = Unit("days", default=42.0, description="Decoupled lead time above this is 'long'")
    ltf_short: float = Unit("fraction", le=1, default=0.7, description="Lead-time factor for short DLT")
    ltf_medium: float = Unit("fraction", le=1, default=0.5, description="Lead-time factor for medium DLT")
    ltf_long: float = Unit("fraction", le=1, default=0.3, description="Lead-time factor for long DLT")
    cv_low: float = Unit("ratio", default=0.3, description="Weekly CV up to this is 'low' variability")
    cv_high: float = Unit("ratio", default=0.6, description="Weekly CV above this is 'high' variability")
    vf_low: float = Unit("fraction", le=1, default=0.25, description="Variability factor, low")
    vf_medium: float = Unit("fraction", le=1, default=0.5, description="Variability factor, medium")
    vf_high: float = Unit("fraction", le=1, default=0.75, description="Variability factor, high")
    spike_factor: float = Unit("ratio", default=0.5,
                               description="Order spike threshold as a multiple of the red zone")

    @model_validator(mode="after")
    def _order(self) -> InventorySettings:
        if self.lt_long_days < self.lt_short_days:
            raise ValueError("lt_long_days must be ≥ lt_short_days")
        if self.cv_high < self.cv_low:
            raise ValueError("cv_high must be ≥ cv_low")
        return self
