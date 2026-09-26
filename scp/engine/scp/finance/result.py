"""Finance overlay output (blueprint P9): every number here reconciles to the plan it was computed from."""
from __future__ import annotations

import datetime as dt

from ..model.common import Out
from ..validate import Issue

PLAN_COSTS = ("purchase", "production", "setup", "ordering", "transport", "handling", "holding")


class CostLine(Out):
    """One plan cost category traced three ways: the plan KPI, the sum over its sources (orders or node
    buckets), and its allocation to served demand plus what no demand absorbs."""
    category: str
    plan: float
    sources: float
    served: float
    unabsorbed: float
    difference: float                # plan − (served + unabsorbed); zero when the books close


class Reconciliation(Out):
    lines: list[CostLine] = []
    total_plan: float = 0.0
    total_served: float = 0.0
    total_unabsorbed: float = 0.0
    reconciled: bool = True
    unabsorbed_reasons: dict[str, float] = {}


class ValueBucket(Out):
    bucket: int
    label: str
    start: dt.date
    days: int
    value: float
    by_type: dict[str, float] = {}   # product type → value


class LocationValue(Out):
    location: str
    type: str
    start: float
    end: float
    avg: float
    holding: float


class InventoryValue(Out):
    start: float = 0.0
    end: float = 0.0
    avg: float = 0.0                 # time-weighted over the horizon (= plan KPI)
    buckets: list[ValueBucket] = []
    locations: list[LocationValue] = []
    types: list[str] = []


class ServeRow(Out):
    """Demand at one point (customer, or a stocking location selling directly) for one product."""
    location: str
    location_type: str
    region: str
    product: str
    demand: float
    served: float                    # pegged to supply within the horizon
    price: float | None
    revenue: float
    costs: dict[str, float] = {}     # plan categories + stock + firm
    plan_cost: float = 0.0           # Σ plan categories: the cost this plan spends to serve it
    total_cost: float = 0.0          # plan cost + value of stock and firm receipts consumed
    cost_per_unit: float = 0.0
    margin: float = 0.0              # revenue − total cost
    margin_pct: float | None = None


class BucketValue(Out):
    bucket: int
    label: str
    capacity: float
    added: float
    shadow_price: float
    valid_headroom: float | None     # hours the shadow price stays valid for
    estimate: float                  # shadow price × min(added, headroom)


class CapacityAppraisal(Out):
    id: str
    name: str
    resource: str
    added_hours_per_week: float
    capex: float
    fixed_cost_per_year: float
    life_years: int
    discount_rate: float
    horizon_days: int
    dual_estimate: float             # objective saving predicted by the shadow prices
    within_range: bool               # every bucket's added hours inside the shadow price's valid range
    objective_saving: float          # re-solved: base objective − objective with the option
    cash_delta: float                # re-solved: Δ(revenue − purchase − production − transport − holding − overtime)
    fill_rate_before: float
    fill_rate_after: float
    annual_cash: float               # cash_delta × 365 / horizon
    annual_net: float                # annual_cash − fixed cost
    npv: float
    irr: float | None
    payback_years: float | None
    cash_flows: list[float] = []     # year 0 … life
    buckets: list[BucketValue] = []


class FinanceResult(Out):
    ok: bool
    currency: str
    sop_mode: str | None = None
    reconciliation: Reconciliation | None = None
    inventory: InventoryValue | None = None
    serve: list[ServeRow] = []
    capacity: list[CapacityAppraisal] = []
    notes: list[str] = []
    issues: list[Issue] = []
