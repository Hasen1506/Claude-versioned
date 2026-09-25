"""Plan versions & scenarios (blueprint P8): an SQLite store of immutable base versions and mutable
scenario branches, a dataset diff, and a side-by-side plan comparison."""
from __future__ import annotations

from ..model import Dataset
from ..model.common import Out
from ..plan import run_mrp
from .diff import DatasetDiff, diff
from .store import LogEntry, Store, VersionDoc, VersionError, VersionMeta, canonical, get_store, set_store, sha


class PlanSummary(Out):
    ok: bool
    total_cost: float
    fill_rate: float
    orders: int
    inventory_value_avg: float
    max_utilization: float
    exceptions: int
    errors: int


class Comparison(Out):
    a: str
    b: str
    diff: DatasetDiff
    plan_a: PlanSummary
    plan_b: PlanSummary


def plan_summary(ds: Dataset) -> PlanSummary:
    p = run_mrp(ds)
    k = p.kpis
    return PlanSummary(ok=p.ok, total_cost=k.total_cost, fill_rate=k.on_time_fill_rate, orders=len(p.orders),
                       inventory_value_avg=k.inventory_value_avg, max_utilization=k.max_utilization,
                       exceptions=len(p.exceptions), errors=sum(e.severity == "error" for e in p.exceptions))


def compare(a: Dataset, b: Dataset, label_a: str = "A", label_b: str = "B") -> Comparison:
    return Comparison(a=label_a, b=label_b, diff=diff(a, b), plan_a=plan_summary(a), plan_b=plan_summary(b))


__all__ = [
    "Comparison", "DatasetDiff", "LogEntry", "PlanSummary", "Store", "VersionDoc", "VersionError", "VersionMeta",
    "canonical", "compare", "diff", "get_store", "plan_summary", "set_store", "sha",
]
