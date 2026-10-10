"""Control-tower output (blueprint P10): the KPI set of the S/4 guide §18.2 and the exception worklist."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from ..model.common import Out
from ..validate import Issue

Status = Literal["good", "warning", "critical", "none"]


class KpiRow(Out):
    """One slice of a KPI (a customer, a supplier, a product type…)."""
    label: str
    value: float | None
    numerator: float = 0.0
    denominator: float = 0.0


class KpiPoint(Out):
    """A KPI's value on an earlier day (the trend), worked out from the records dated before it."""
    as_of: dt.date
    value: float | None


class Kpi(Out):
    id: str
    name: str
    definition: str
    source: str
    unit: Literal["ratio", "days", "money_per_unit", "money", "times"]  # times: a rate per year (inventory turns)
    direction: Literal["up", "down", "zero", "none"]   # which way is better
    value: float | None = None                          # None: no data yet
    target: float | None = None
    status: Status = "none"
    numerator: float = 0.0
    denominator: float = 0.0
    n: int = 0                                          # observations (orders, records, items)
    note: str = ""
    breakdown_by: str = ""
    breakdown: list[KpiRow] = []
    trend: list[KpiPoint] = []                          # weekly, oldest first, ending on the planning start
    ageing: list[KpiRow] = []                           # what is open by days past due (value: amount, numerator: count)


class InboxAction(Out):
    """The one thing the exception inbox suggests doing about an item (roadmap F)."""
    kind: Literal["expedite", "switch_supplier", "overtime", "split_delivery", "push_out", "sell_first", "chase", "pay",
                  "release", "review"]
    label: str
    protects: float = 0.0             # money at risk the action takes away, if it works (company currency)
    costs: float | None = None        # what doing it costs, when the data says (overtime hours, a dearer supplier)
    href: str = ""                    # where in the application it is done
    one_click: bool = False           # it can be tried on a copy of the plan and kept in one click (tower/fix.py)
    why_not: str = ""                 # an expedite, switch or overtime that cannot: why, in plain words


class WorkItem(Out):
    """An exception on the worklist, with its lifecycle kept across runs in the version store."""
    id: str
    key: str
    code: str
    category: str
    severity: Literal["error", "warning", "info"]
    message: str
    location: str | None = None
    product: str | None = None
    resource: str | None = None
    order_id: str | None = None
    date: dt.date | None = None
    qty: float | None = None
    owner: str
    owner_source: Literal["rule", "default", "manual"]
    status: Literal["open", "acknowledged", "resolved", "cleared"]
    first_seen: dt.date
    last_seen: dt.date
    resolved_on: dt.date | None = None
    age_days: int = 0
    sla_days: int | None = None
    breached: bool = False
    reopened: int = 0
    note: str = ""
    money_at_risk: float = 0.0        # roadmap F: what leaving it costs, in the company currency (tower/money.py)
    money_basis: str = ""             # how that amount was worked out, in words
    customer: str | None = None       # the customer it concerns, for grouping the inbox
    action: InboxAction | None = None


class DataQualityRow(Out):
    code: str
    severity: str
    title: str
    count: int
    examples: list[str] = []


class TowerResult(Out):
    ok: bool
    company: str
    as_of: dt.date
    kpis: list[Kpi] = []
    worklist: list[WorkItem] = []           # open, acknowledged and resolved-but-still-listed items
    cleared: list[WorkItem] = []            # cleared by this run (no longer detected)
    inbox: list[str] = []                   # roadmap F: open/acknowledged item ids, most money at risk first
    money_at_risk: float = 0.0              # their total
    data_quality: list[DataQualityRow] = []
    notes: list[str] = []
    issues: list[Issue] = []
