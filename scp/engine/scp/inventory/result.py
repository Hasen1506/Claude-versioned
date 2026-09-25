"""Inventory-optimisation output schema."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from ..model.common import Out
from ..validate import Issue

Role = Literal["stocking", "no_stock", "customer"]
CvSource = Literal["policy", "pooled", "default", "none"]


class NodeRef(Out):
    location: str
    product: str


class NodeInventory(Out):
    location: str
    product: str
    role: Role
    demand_facing: bool
    upstream: list[NodeRef]
    # demand seen at the node (direct + flowed from its consumers), per calendar day
    direct_mean_daily: float
    mean_daily: float
    sd_daily: float
    cv_weekly: float
    cv_source: CvSource
    # replenishment
    lead_time_days: float
    lead_time_std_days: float
    cumulative_lead_time_days: float
    # economics
    unit_value: float
    holding_rate: float
    service_level: float
    z: float
    # what the node holds today (its configured policy, as MRP computes it)
    current_method: str
    current_ss: float
    current_cost: float
    # every stage buffers its own lead time
    single_ss: float
    single_cost: float
    # guaranteed-service placement
    max_service_days: int | None
    meio_inbound_days: int
    meio_service_days: int
    meio_net_days: int
    meio_ss: float
    meio_cost: float
    decision: Literal["buffer", "pass_through", "no_stock", "customer"]


class DdmrpRow(Out):
    location: str
    product: str
    positioned: bool
    adu: float
    dlt: float
    ltf: float
    lt_band: Literal["short", "medium", "long"]
    vf: float
    var_band: Literal["low", "medium", "high"]
    red_base: float
    red_safety: float
    red: float
    yellow: float
    green: float
    tor: float
    toy: float
    tog: float
    on_hand: float
    open_supply: float
    qualified_demand: float
    nfp: float
    zone: Literal["red", "yellow", "green", "over"]
    priority: float                 # NFP / TOG: lower is more urgent
    order_qty: float
    unit_value: float
    average_on_hand: float          # red + green / 2: the planned average inventory
    average_value: float


class PoolingRow(Out):
    product: str
    locations: list[str]
    lead_time_days: float           # demand-weighted replenishment lead time
    separate_ss: float              # Σ z σ_i √L_i
    pooled_ss: float                # z √(Σ σ_i²) √L̄
    saving_qty: float
    saving_value: float
    saving_pct: float
    unit_value: float


class Totals(Out):
    stocking_nodes: int
    buffers_placed: int
    ddmrp_positions: int
    current_ss_value: float
    single_ss_value: float
    meio_ss_value: float
    current_cost: float
    single_cost: float
    meio_cost: float
    saving_vs_single: float
    saving_vs_current: float


class SolverInfo(Out):
    status: str
    objective: float
    variables: int
    constraints: int
    seconds: float
    message: str


class InventoryResult(Out):
    ok: bool
    currency: str
    carrying_rate: float
    planning_start: dt.date
    horizon_days: int
    nodes: list[NodeInventory] = []
    ddmrp: list[DdmrpRow] = []
    pooling: list[PoolingRow] = []
    totals: Totals | None = None
    solver: SolverInfo | None = None
    notes: list[str] = []
    issues: list[Issue] = []


class PlacementChange(Out):
    location: str
    product: str
    method_before: str
    ss_before: float
    ss_after: float
    value_change: float


class PlacementApplied(Out):
    changes: list[PlacementChange]
    value_change: float               # safety-stock value after − before, at unit value
