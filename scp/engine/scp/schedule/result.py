"""Detailed-schedule output schema. Times are clock hours from ``origin`` (planning start, 00:00)."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from ..model.common import Out
from ..validate import Issue


class ScheduledOp(Out):
    id: str                          # "<order>:<seq>/<sublot>"
    key: str                         # "<order>:<seq>" — what a sequence refers to
    order: str
    seq: int
    sub: int
    product: str
    group: str
    resource: str
    unit: int                        # 0-based unit (machine) of the resource
    qty: float
    setup_start: float
    run_start: float
    end: float
    setup_hours: float               # productive hours
    run_hours: float
    setup_from: str | None           # setup group that ran before on the unit
    late: bool
    machines: list[str] = []         # where the step may run: its own resource, then its alternatives


class PartSupply(Out):
    supply: str                      # order or receipt the parts come from
    product: str
    available: float                 # clock hour they are there
    scheduled: bool                  # made by an order in this schedule (its finish moves with the sequence)


class ScheduledOrder(Out):
    id: str
    location: str
    product: str
    group: str
    qty: float
    release: float
    due: float
    completion: float
    lateness_hours: float
    tardy: bool
    baseline_completion: float
    mrp_start_date: dt.date
    mrp_due_date: dt.date
    firm: bool                       # a production order already released (scheduled receipt)
    parts_ready: float = 0.0         # when the last part it uses is there (0 = from stock now)
    held_for_parts: float = 0.0      # hours its steps waited for parts after they could otherwise start
    parts_from: list[PartSupply] = Field(default_factory=list)   # supplies arriving after its release
    missing_parts: list[str] = Field(default_factory=list)       # parts no supply covers
    finish_date: dt.date | None = None       # day the last step ends
    available_date: dt.date | None = None    # finish plus goods-receipt days: when the plan can use it
    days_late: int = 0                       # available date after the MRP due/available date
    frozen: bool = False                     # in the frozen zone: keeps its place and machine
    hold: float | None = None                # held until this clock hour (just in time), when later than its release


class ScheduleResource(Out):
    id: str
    name: str
    kind: str
    units: int
    finite: bool
    efficiency: float
    windows: list[list[float]]       # shift windows [start, end) over the displayed span
    busy_hours: float                # clock hours with a job on a unit (setup + run)
    setup_hours: float
    available_hours: float           # clock shift hours × units over the span
    utilization: float
    changeovers: int
    sequence: list[str]              # realised operation order (keys)


class LabourDay(Out):
    resource: str
    date: dt.date
    required: float
    available: float
    overload: bool


class ScheduleKpis(Out):
    orders: int = 0
    operations: int = 0
    late_orders: int = 0
    waiting_for_parts: int = 0       # orders with a step that waited for parts
    tardiness_hours: float = 0.0
    earliness_hours: float = 0.0     # hours orders finish before they are due, summed
    max_lateness_hours: float = 0.0
    setup_hours: float = 0.0
    changeovers: int = 0
    makespan_hours: float = 0.0
    objective: float = 0.0


class OptimizerInfo(Out):
    status: str = "not run"          # optimal | feasible | no solution | too big | not installed
    seconds: float = 0.0
    model_objective: float | None = None   # the solver's own (averaged-time) objective and bound
    model_bound: float | None = None
    steps: int = 0
    machines_changed: int = 0        # steps it moved to another machine
    kept: bool = False               # its schedule beat the local search and is the one shown
    note: str = ""


class SearchInfo(Out):
    mode: Literal["improved", "edd", "rule", "manual", "optimized"]
    start_rule: str = "edd"
    moves_tried: int = 0
    moves_accepted: int = 0
    passes: int = 0
    seconds: float = 0.0
    stopped: Literal["converged", "time_limit", "off"] = "off"
    trace: list[float] = Field(default_factory=list)
    optimizer: OptimizerInfo | None = None


class ScheduleResult(Out):
    ok: bool
    origin: dt.datetime | None = None
    span_hours: float = 0.0          # displayed span (horizon)
    day_start_hour: float = 0.0
    ops: list[ScheduledOp] = Field(default_factory=list)
    orders: list[ScheduledOrder] = Field(default_factory=list)
    resources: list[ScheduleResource] = Field(default_factory=list)
    labour: list[LabourDay] = Field(default_factory=list)
    baseline: ScheduleKpis = Field(default_factory=ScheduleKpis)
    kpis: ScheduleKpis = Field(default_factory=ScheduleKpis)
    search: SearchInfo = Field(default_factory=lambda: SearchInfo(mode="edd"))
    profile: str = "balanced"
    holds: dict[str, float] = Field(default_factory=dict)   # order -> not-before clock hour (send back with a sequence)
    violations: list[str] = Field(default_factory=list)
    beyond_horizon: int = 0          # make orders starting after the scheduling window
    without_routing: int = 0         # make orders whose source has no operations
    issues: list[Issue] = Field(default_factory=list)


class CompareRow(Out):
    method: str                      # a heuristic id (see /api/schedule/catalogue)
    name: str
    kpis: ScheduleKpis
    seconds: float
    best: bool = False               # lowest objective under the current weights


class ScheduleComparison(Out):
    ok: bool
    weights: dict[str, float] = Field(default_factory=dict)
    rows: list[CompareRow] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
