"""Control-tower settings (blueprint P10): who owns which exceptions, how fast they must be handled, and the
KPI targets the dashboard grades against."""
from __future__ import annotations

from pydantic import Field

from .common import Model, Unit

CATEGORIES = ("coverage", "capacity", "inventory", "orders", "delivery", "demand")


def _default_sla() -> dict[str, int]:
    return {"coverage": 2, "capacity": 5, "inventory": 10, "orders": 3, "delivery": 1, "demand": 7}


def _default_targets() -> dict[str, float]:
    return {"forecast_accuracy": 0.7, "forecast_bias": 0.1, "confirmation_rate": 0.9, "otif_confirmed": 0.95,
            "otif_requested": 0.9, "supplier_reliability": 0.95, "schedule_adherence": 0.9, "excess_obsolete": 0.1,
            "plan_stability": 0.8, "exception_ageing": 3.0, "perfect_order": 0.9}


class OwnerRule(Model):
    """The first rule that matches an exception names its owner. Empty lists match anything."""

    owner: str = Field(min_length=1, max_length=60)
    categories: list[str] = Field(default_factory=list, description=f"Any of {', '.join(CATEGORIES)}")
    locations: list[str] = Field(default_factory=list, description="Location ids", json_schema_extra={"x-ref": "location"})
    products: list[str] = Field(default_factory=list, description="Product ids", json_schema_extra={"x-ref": "product"})
    families: list[str] = Field(default_factory=list, description="Product families")


class TowerSettings(Model):
    default_owner: str = Field("Unassigned", min_length=1, max_length=60)
    owners: list[OwnerRule] = Field(default_factory=list)
    sla_days: dict[str, int] = Field(default_factory=_default_sla,
                                     description="Days an exception may stay open, by category, before it breaches")
    targets: dict[str, float] = Field(default_factory=_default_targets, description="KPI targets by KPI id")
    kpi_window_days: int = Field(91, ge=7, le=730, description="Closed orders and accuracy records counted: this many "
                                                               "days before the planning start")
    excess_cover_days: int = Field(90, ge=1, le=730, description="Stock above this many days of requirements is excess")
    slow_moving_days: int = Field(90, ge=1, le=730, description="Stock with no issue or sale for this long is slow-moving")
    bias_alert: float = Unit("fraction", le=5, default=0.2, description="Flag a series whose forecast bias exceeds this")
