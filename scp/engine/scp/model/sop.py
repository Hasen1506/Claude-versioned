"""S&OP (constrained supply) settings: the time-phased network LP of blueprint §6."""
from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import Field

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
