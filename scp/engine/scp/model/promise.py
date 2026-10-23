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
    """Product allocation (PAL): caps what can be confirmed for a product or a product family (and optionally a set
    of customers) in a period, independent of stock. Once a product-customer combination has any allocation, a date
    in no allocation period has nothing to confirm (strict, as in aATP).

    Hierarchy (S/4 guide §7.4): a family's cap is checked before the product's, and an order is confirmed only as far
    as every level allows. At each level the allocations naming the customer apply; an allocation for no customer in
    particular is the catch-all for every customer without one of their own."""

    id: Id
    product: str | None = Ref("product", default=None, description="The product it caps (or give a family)")
    family: str | None = Field(None, max_length=64, description="The product family it caps, across its products "
                                                                "(checked before a product's own allocation)")
    customers: list[str] = Field(default_factory=list,
                                 description="Demand locations it applies to (empty = every customer without an "
                                             "allocation of their own)")
    start: dt.date
    end: dt.date = Field(description="Exclusive")
    qty: float = Unit("qty")
    fallback: Literal["next_period", "reject"] = Field(
        "next_period", description="When the period is used up: confirm the rest in later periods, or not at all")
    carry_forward: bool = Field(False, description="What earlier periods of the same allocation left unused can be "
                                                   "confirmed in this one")

    @model_validator(mode="after")
    def _span(self) -> Allocation:
        if self.end <= self.start:
            raise ValueError("an allocation period ends after it starts")
        if (self.product is None) == (self.family is None):
            raise ValueError("an allocation caps either a product or a product family")
        return self


class Substitution(Model):
    """A product that may ship in another's place when that one is short (≈ aATP product substitution, a CPIM
    substitute item). An order short of ``product`` on its date is offered what ``substitute`` can confirm on time;
    taking the offer moves the short part to a line of the substitute at the ordered line's price. Several
    substitutions of one product are offered in the order they are listed."""

    product: str = Ref("product", description="The product that may be short")
    substitute: str = Ref("product", description="What may ship in its place")
    customers: list[str] = Field(default_factory=list,
                                 description="Customers who accept it (empty = every customer)")
    valid_from: dt.date | None = Field(None, description="First requested date it applies to (empty = always)")
    valid_to: dt.date | None = Field(None, description="Last requested date it applies to (empty = always)")
    note: str = Field("", max_length=200, description="Why it is acceptable, e.g. same motor, larger jar")

    @model_validator(mode="after")
    def _differs(self) -> Substitution:
        if self.product == self.substitute:
            raise ValueError("a product cannot be its own substitute")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("a substitution ends after it starts")
        return self

    def applies(self, customer: str, day: dt.date) -> bool:
        return ((not self.customers or customer in self.customers)
                and (self.valid_from is None or day >= self.valid_from)
                and (self.valid_to is None or day <= self.valid_to))


class Confirmation(Model):
    """A persisted schedule line: what was promised to a sales order, from where and when."""

    order: str = Field(min_length=1, max_length=64, description="Sales-order demand record id")
    ship_from: str = Ref("location")
    ship_date: dt.date = Field(description="Material availability date: the goods are there to pick and pack")
    date: dt.date = Field(description="Confirmed delivery date at the demand location")
    qty: float = Unit("qty", gt=0)
    method: Literal["atp", "rlt", "ctp"] = "atp"
    goods_issue: dt.date | None = Field(None, description="The goods leave, after picking, packing and loading "
                                                          "(empty: the day they are there)")


class PromiseSettings(Model):
    include_planned_orders: bool = Field(
        True, description="Scope of check: count MRP planned receipts as supply (else stock and firm receipts only)")
    quality_in_promise: bool = Field(
        False, description="Scope of check: stock in quality inspection can be promised (off, as SAP's checking rule "
                           "A: only unrestricted stock is promised, since inspection stock cannot be shipped until "
                           "it is released)")
    confirm_beyond_rlt: bool = Field(
        True, description="Confirm unconditionally beyond the replenishment lead time (else backorder)")
    alternative_locations: bool = Field(
        True, description="Alternative-based confirmation: try other shipping locations when the first is short")
    ctp: bool = Field(True, description="Capable-to-promise: quote new production / transfers for what ATP cannot cover")
    bop_segments: list[BopSegment] = Field(default_factory=_default_segments)
