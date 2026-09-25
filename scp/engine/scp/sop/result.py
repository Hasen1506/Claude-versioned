"""S&OP output schema: the constrained plan, its economics and its shadow prices."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from ..model import SopMode
from ..model.common import Out
from ..validate import Issue

ConstraintKind = Literal["resource", "overtime", "supplier", "lane", "storage", "shelf_life"]


class SopBucket(Out):
    index: int
    start: dt.date
    end: dt.date
    label: str
    days: int


class DemandLine(Out):
    """One demand point: what was asked, what the constrained plan delivers, and the gap."""
    location: str
    product: str
    price: float
    demand: list[float]
    sales: list[float]
    backlog: list[float]
    lost: list[float]
    marginal_cost: list[float]      # cost of supplying one more unit of demand in the bucket (from the dual)


class SupplyLine(Out):
    location: str
    product: str
    role: Literal["stocking", "customer"]
    make: list[float]
    buy: list[float]
    transfer_in: list[float]
    transfer_out: list[float]
    consumed: list[float]           # issued to production at this location
    inventory: list[float]
    ss_target: float
    ss_shortfall: list[float]
    unit_value: float


class Flow(Out):
    kind: Literal["make", "buy", "transfer"]
    source_id: str
    location: str
    product: str
    origin: str | None
    qty: list[float]                # by availability (receipt) bucket
    unit_cost: float
    lead_buckets: int


class ResourceLine(Out):
    resource: str
    location: str
    finite: bool
    capacity: list[float]
    load: list[float]
    overtime: list[float]
    overtime_limit: list[float]
    utilization: list[float]
    shadow_price: list[float]       # value of one more regular hour in the bucket
    valid_up: list[float | None]    # capacity up to which the shadow price holds
    valid_down: list[float | None]


class Binding(Out):
    """A constraint that limits the plan, with the value of relaxing it by one unit."""
    kind: ConstraintKind
    id: str
    bucket: int
    label: str
    limit: float
    used: float
    shadow_price: float
    unit: str
    valid_up: float | None
    valid_down: float | None


class Economics(Out):
    revenue: float
    purchase: float
    production: float
    transport: float
    holding: float
    overtime: float
    backlog_penalty: float
    lost_penalty: float
    ss_penalty: float
    total_cost: float
    profit: float


class SopKpis(Out):
    demand: float
    sales: float
    lost: float
    backlog_end: float
    fill_rate: float                # sales / demand over the horizon (incl. late)
    on_time_rate: float             # share of demand served in its own bucket
    max_utilization: float


class SolverStats(Out):
    status: str
    rows: int
    columns: int
    iterations: int
    seconds: float


class SopResult(Out):
    ok: bool
    mode: SopMode
    currency: str
    carrying_rate: float
    buckets: list[SopBucket] = []
    demand: list[DemandLine] = []
    supply: list[SupplyLine] = []
    flows: list[Flow] = []
    resources: list[ResourceLine] = []
    binding: list[Binding] = []
    economics: Economics | None = None
    kpis: SopKpis | None = None
    solver: SolverStats | None = None
    notes: list[str] = []
    issues: list[Issue] = []


class SopRelease(Out):
    nodes: int
    records: int
    replaced: int
    constrained_qty: float
    unconstrained_qty: float
