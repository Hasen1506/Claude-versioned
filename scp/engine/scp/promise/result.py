"""Order-promising output schema."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from ..model.common import Out
from ..validate import Issue

Method = Literal["atp", "rlt", "ctp"]


class ScheduleLine(Out):
    ship_from: str
    ship_date: dt.date
    date: dt.date                    # delivery at the demand location
    qty: float
    method: Method
    on_time: bool


class CtpStep(Out):
    kind: Literal["transfer", "make", "buy", "stock", "component", "capacity"]
    location: str
    product: str
    qty: float
    start: dt.date | None = None
    end: dt.date | None = None
    note: str = ""


class OrderPromise(Out):
    order: str
    location: str
    product: str
    qty: float
    requested: dt.date
    priority: int
    complete_delivery: bool
    segment: str | None = None
    strategy: str | None = None
    lines: list[ScheduleLine] = Field(default_factory=list)
    confirmed: float = 0.0
    on_time: float = 0.0
    unconfirmed: float = 0.0
    status: Literal["on_time", "late", "partial", "unconfirmed"] = "unconfirmed"
    allocation_capped: float = 0.0   # what the allocation withheld on the requested date
    ctp: list[CtpStep] = Field(default_factory=list)
    previous: list[ScheduleLine] = Field(default_factory=list)
    change: Literal["new", "kept", "gained", "lost", "changed", "unchanged"] = "new"
    at_risk: bool = False            # persisted promise no longer covered by supply
    value: float = 0.0               # qty × price


class AtpNode(Out):
    location: str
    product: str
    rlt_days: int | None             # None = confirmation beyond RLT is off
    on_hand: float
    dates: list[dt.date]
    receipts: list[float]            # stock at day 0, firm and (optionally) planned receipts
    other_demand: list[float]        # dependent and replenishment requirements (from MRP)
    promised: list[float]            # sales-order confirmations shipping from here
    cumulative: list[float]
    available: list[float | None]    # look-ahead ATP; None = unconditional (beyond RLT)
    shortage_date: dt.date | None = None
    shortage_qty: float = 0.0


class AllocationUse(Out):
    id: str
    product: str
    customers: list[str]
    start: dt.date
    end: dt.date
    qty: float
    used: float
    fallback: str


class BopRow(Out):
    order: str
    location: str
    product: str
    priority: int
    segment: str | None
    strategy: str | None
    before_confirmed: float
    before_on_time: float
    after_confirmed: float
    after_on_time: float
    outcome: Literal["gained", "lost", "unchanged", "changed"]


class PromiseKpis(Out):
    orders: int = 0
    qty: float = 0.0
    on_time_qty: float = 0.0
    confirmed_qty: float = 0.0
    unconfirmed_qty: float = 0.0
    on_time_orders: int = 0
    value_unconfirmed: float = 0.0
    rlt_lines: int = 0
    ctp_lines: int = 0
    alternative_lines: int = 0
    at_risk_orders: int = 0


class PromiseResult(Out):
    ok: bool
    mode: Literal["entry", "bop", "check"] = "entry"
    origin: dt.date | None = None
    currency: str = ""
    orders: list[OrderPromise] = Field(default_factory=list)
    nodes: list[AtpNode] = Field(default_factory=list)
    allocations: list[AllocationUse] = Field(default_factory=list)
    bop: list[BopRow] = Field(default_factory=list)
    kpis: PromiseKpis = Field(default_factory=PromiseKpis)
    checked: OrderPromise | None = None   # mode "check": the simulated order
    issues: list[Issue] = Field(default_factory=list)
