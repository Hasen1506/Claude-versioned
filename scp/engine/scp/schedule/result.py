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
    tardiness_hours: float = 0.0
    max_lateness_hours: float = 0.0
    setup_hours: float = 0.0
    changeovers: int = 0
    makespan_hours: float = 0.0
    objective: float = 0.0


class SearchInfo(Out):
    mode: Literal["improved", "edd", "manual"]
    moves_tried: int = 0
    moves_accepted: int = 0
    passes: int = 0
    seconds: float = 0.0
    stopped: Literal["converged", "time_limit", "off"] = "off"
    trace: list[float] = Field(default_factory=list)


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
    violations: list[str] = Field(default_factory=list)
    beyond_horizon: int = 0          # make orders starting after the scheduling window
    without_routing: int = 0         # make orders whose source has no operations
    issues: list[Issue] = Field(default_factory=list)
