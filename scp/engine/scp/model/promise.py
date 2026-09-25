"""Order-promising settings and objects (blueprint §7, S/4 guide §7 aATP): product allocations,
persisted confirmations (schedule lines), backorder-processing segments and the checking rules."""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import Id, Model, Ref, Unit


class ConfirmationStrategy(str, Enum):
    """BOP confirmation strategy (guide §7.3)."""

    WIN = "win"                    # may not lose, may gain; claims supply first
    GAIN = "gain"                  # may not lose, may gain; placed later in the sequence
    REDISTRIBUTE = "redistribute"  # re-planned from scratch: may lose or gain
    FILL = "fill"                  # keeps its schedule lines, tops up toward the requested quantity
    LOSE = "lose"                  # may lose, may not gain: gives supply back


class BopSegment(Model):
    name: str = Field(min_length=1, max_length=60)
    priorities: list[int] = Field(default_factory=list, description="Order priorities selected (empty = any)")
    customers: list[str] = Field(default_factory=list, description="Demand locations selected (empty = any)")
    products: list[str] = Field(default_factory=list, description="Products selected (empty = any)")
    strategy: ConfirmationStrategy = ConfirmationStrategy.REDISTRIBUTE
    sort: Literal["priority_date", "date", "qty_desc"] = Field(
        "priority_date", description="Order inside the segment: priority then requested date, date only, or largest first")

    @model_validator(mode="after")
    def _prio(self) -> BopSegment:
        if any(p < 1 or p > 9 for p in self.priorities):
            raise ValueError("priorities are 1..9")
        return self


def _default_segments() -> list[BopSegment]:
    return [
        BopSegment(name="Key accounts", priorities=[1, 2], strategy=ConfirmationStrategy.WIN),
        BopSegment(name="Standard", priorities=[3, 4, 5, 6], strategy=ConfirmationStrategy.REDISTRIBUTE),
        BopSegment(name="Low priority", priorities=[7, 8, 9], strategy=ConfirmationStrategy.LOSE),
    ]


class Allocation(Model):
    """Product allocation (PAL): caps what can be confirmed for a product (and optionally a set of
    customers) in a period, independent of stock. Once a product-customer combination has any
    allocation, a date in no allocation period has nothing to confirm (strict, as in aATP)."""

    id: Id
    product: str = Ref("product")
    customers: list[str] = Field(default_factory=list, description="Demand locations it applies to (empty = all)")
    start: dt.date
    end: dt.date = Field(description="Exclusive")
    qty: float = Unit("qty")
    fallback: Literal["next_period", "reject"] = Field(
        "next_period", description="When the period is used up: confirm the rest in later periods, or not at all")

    @model_validator(mode="after")
    def _span(self) -> Allocation:
        if self.end <= self.start:
            raise ValueError("an allocation period ends after it starts")
        return self


class Confirmation(Model):
    """A persisted schedule line: what was promised to a sales order, from where and when."""

    order: str = Field(min_length=1, max_length=64, description="Sales-order demand record id")
    ship_from: str = Ref("location")
    ship_date: dt.date
    date: dt.date = Field(description="Confirmed delivery date at the demand location")
    qty: float = Unit("qty", gt=0)
    method: Literal["atp", "rlt", "ctp"] = "atp"


class PromiseSettings(Model):
    include_planned_orders: bool = Field(
        True, description="Scope of check: count MRP planned receipts as supply (else stock and firm receipts only)")
    confirm_beyond_rlt: bool = Field(
        True, description="Confirm unconditionally beyond the replenishment lead time (else backorder)")
    alternative_locations: bool = Field(
        True, description="Alternative-based confirmation: try other shipping locations when the first is short")
    ctp: bool = Field(True, description="Capable-to-promise: quote new production / transfers for what ATP cannot cover")
    bop_segments: list[BopSegment] = Field(default_factory=_default_segments)
