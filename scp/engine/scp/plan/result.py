"""Plan output schema — everything the UI shows is here, with its derivation."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from ..model.common import Out
from ..validate import Issue

OrderKind = Literal["make", "buy", "transfer"]
ReqKind = Literal["forecast", "sales_order", "dependent", "transfer"]
SupplyKind = Literal["on_hand", "receipt", "order"]


class Peg(Out):
    supply_kind: SupplyKind
    supply_id: str
    requirement_id: str
    qty: float


class Requirement(Out):
    id: str
    location: str
    product: str
    date: dt.date
    qty: float
    kind: ReqKind
    parent_order: str | None = None   # order that created a dependent/transfer requirement
    priority: int = 5
    consumed_forecast: float = 0.0    # forecast rows: quantity consumed by sales orders
    past_due: bool = False


class PlannedOrder(Out):
    id: str
    kind: OrderKind
    location: str                 # receiving / producing location
    product: str
    qty: float                    # good (receipt) quantity
    source_id: str                # production source / purchasing source / lane
    origin: str | None = None     # transfer: shipping location; buy: supplier
    need_date: dt.date               # date the requirement needs it (netting date)
    start_date: dt.date
    due_date: dt.date
    available_date: dt.date
    start_in_past: bool = False
    fence_shifted: bool = False
    convertible: bool = True      # False: ATO forecast-driven FG supply
    unit_cost: float = 0.0
    total_cost: float = 0.0
    shipments: int | None = None
    delay_days: float = 0.0       # projected lateness vs need incl. upstream delays; −1 = an input is uncovered
    projected_available_date: dt.date | None = None
    lot_excess: float = 0.0       # quantity not pegged to any requirement (lot sizing / SS)


class ScheduledReceiptOut(Out):
    id: str
    kind: str
    location: str
    product: str
    qty: float
    date: dt.date


class NodeBucket(Out):
    bucket: int
    gross_independent: float = 0.0
    gross_dependent: float = 0.0
    scheduled_receipts: float = 0.0
    planned_receipts: float = 0.0
    projected_on_hand: float = 0.0   # end of bucket, physical (by available dates)
    safety_stock: float = 0.0
    below_safety: float = 0.0        # max(0, SS − projected)
    shortage: float = 0.0            # max(0, −projected)


class NodePlan(Out):
    location: str
    product: str
    llc: int
    strategy: str
    mrp_type: str
    lot_policy: str
    unit_value: float
    value_basis: str
    on_hand: float
    safety_stock_method: str
    safety_stock_note: str = ""
    lead_time_days: float | None = None
    sources: list[str] = Field(default_factory=list)
    buckets: list[NodeBucket]
    order_ids: list[str] = Field(default_factory=list)


class BucketOut(Out):
    index: int
    start: dt.date
    end: dt.date
    label: str


class ResourceBucket(Out):
    bucket: int
    load_hours: float
    capacity_hours: float
    overtime_hours: float
    utilization: float


class ResourcePlan(Out):
    resource: str
    location: str
    kind: str
    finite: bool
    buckets: list[ResourceBucket]


class PlanException(Out):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    location: str | None = None
    product: str | None = None
    resource: str | None = None
    order_id: str | None = None
    date: dt.date | None = None
    qty: float | None = None


class Kpis(Out):
    purchase_cost: float = 0.0
    production_cost: float = 0.0
    setup_cost: float = 0.0
    ordering_cost: float = 0.0
    transport_cost: float = 0.0
    handling_cost: float = 0.0
    holding_cost: float = 0.0
    total_cost: float = 0.0
    inventory_value_start: float = 0.0
    inventory_value_end: float = 0.0
    inventory_value_avg: float = 0.0
    orders_make: int = 0
    orders_buy: int = 0
    orders_transfer: int = 0
    independent_demand: float = 0.0
    on_time_qty: float = 0.0
    on_time_fill_rate: float = 1.0  # share of independent demand projected available on time
    max_utilization: float = 0.0


class PlanResult(Out):
    ok: bool
    currency: str
    carrying_rate: float
    buckets: list[BucketOut] = Field(default_factory=list)
    nodes: list[NodePlan] = Field(default_factory=list)
    orders: list[PlannedOrder] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    receipts: list[ScheduledReceiptOut] = Field(default_factory=list)
    pegs: list[Peg] = Field(default_factory=list)
    resources: list[ResourcePlan] = Field(default_factory=list)
    exceptions: list[PlanException] = Field(default_factory=list)
    kpis: Kpis = Field(default_factory=Kpis)
    issues: list[Issue] = Field(default_factory=list)
