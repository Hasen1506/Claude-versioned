"""Finance overlay settings (blueprint P9): capacity investment options to appraise against the S&OP plan."""
from __future__ import annotations

from pydantic import Field

from .common import Id, Model, Ref, Unit


class CapacityOption(Model):
    """A capacity investment (a new machine, an added shift, a line upgrade) that adds regular hours to one
    resource. Its value is what the S&OP plan saves with the hours; its NPV nets that against the spend."""

    id: Id
    name: str = ""
    resource: str = Ref("resource")
    added_hours_per_week: float = Unit("hours", gt=0, description="Extra regular hours per week the option adds")
    capex: float = Unit("money", default=0.0, description="One-off investment at year 0")
    fixed_cost_per_year: float = Unit("money", default=0.0, description="Running cost per year (crew, lease, upkeep)")
    life_years: int = Field(5, ge=1, le=50, description="Years of benefit counted in the NPV")


class FinanceSettings(Model):
    capacity_options: list[CapacityOption] = Field(default_factory=list)
    discount_rate: float | None = Unit("fraction", le=1, default=None,
                                       description="Per year for NPV; empty = the company WACC")
