"""S&OP (constrained supply) settings: the time-phased network LP of blueprint §6."""
from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import Field, model_validator

from .common import BucketSize, Model, Ref, Unit


class SopMode(str, Enum):
    COST = "cost"       # serve demand at minimum cost; unmet demand is penalised
    PROFIT = "profit"   # maximise revenue − cost; demand is an upper bound


class SopSettings(Model):
    mode: SopMode = SopMode.COST
    bucket: BucketSize = Field(BucketSize.MONTH, description="S&OP time bucket (monthly is the S&OP norm)")
    backlog_rate_per_day: float = Unit(
        "fraction", le=1, default=0.005,
        description="Late-delivery penalty per unit per day, as a share of the unit's reference value "
                    "(price, else cost); scaled by demand priority")
    lost_sale_rate: float = Unit(
        "ratio", le=100, default=2.0,
        description="Cost mode: penalty per unit never delivered, as a multiple of the reference value")
    ss_shortfall_rate_per_day: float = Unit(
        "fraction", le=1, default=0.002,
        description="Penalty per unit per day below the safety-stock target, as a share of unit value")
    horizon_months: int | None = Field(
        None, ge=1, le=36,
        description="How far the S&OP plan looks, in months (18 to 24 is usual). Beyond the weekly plan's horizon its "
                    "demand is the statistical and consensus forecast. Empty: as far as the weekly plan")
    allow_overtime: bool = Field(True, description="Let the plan buy overtime hours up to each resource's limit")
    # what-if levers: scenarios are the same dataset with different levers
    demand_factor: float = Unit("ratio", le=10, default=1.0, description="Scenario: scale all demand (1 = as planned)")
    capacity_factor: float = Unit("ratio", le=10, default=1.0,
                                  description="Scenario: scale regular and overtime hours of every resource")
    capacity_add_hours_per_week: dict[str, float] = Field(
        default_factory=dict, description="Scenario: extra regular hours per week by resource id (e.g. an added shift)")


class StockTarget(Model):
    """A stock level MRP plans to keep at a node on a date, on top of its safety stock: the build-ahead the
    constrained S&OP plan decided (written by the S&OP release). Between two targets of a node the level is
    interpolated linearly by date; before the first and after the last there is none."""

    location: str = Ref("location")
    product: str = Ref("product")
    date: dt.date
    qty: float = Unit("qty")
    source: str = Field("sop", max_length=40, description="What wrote it (the S&OP release writes 'sop')")


class Budget(Model):
    """A month's budget: what the company planned to sell, for a product, a product family or the whole company.
    The monthly S&OP cycle sets the demand plan and the supply plan against it, volume and revenue."""

    month: dt.date = Field(description="The month it is for (any day of it; read as the month)")
    product: str | None = Ref("product", default=None, description="The product it budgets (or give a family, or "
                                                                    "neither for the whole company)")
    family: str | None = Field(None, max_length=64, description="The product family it budgets")
    qty: float = Unit("qty", default=0.0, description="Units planned to sell in the month")
    revenue: float | None = Unit("money", default=None,
                                 description="Sales planned in the month, in the company currency. Empty = the units "
                                             "at the product's price (a product's budget), else no revenue budget")

    @model_validator(mode="after")
    def _one(self) -> Budget:
        if self.product is not None and self.family is not None:
            raise ValueError("a budget is for a product or a product family, not both")
        return self
