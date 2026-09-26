"""Capacity levelling (S/4 CRP levelling, done the MRP way): what planning within machine capacity changes.

The same plan is run twice, at unlimited capacity and within capacity (``Settings.capacity_constrained``), and the
make orders are matched by what they are for (place, product, need date, source): an order that starts earlier, runs
on an alternative machine or finishes later is a *move*. Each finite machine and labour pool gets its worst day and
its overloaded days before and after. Nothing is changed: turning the setting on plans this way from then on, and
firming the moved orders keeps their dates whatever the setting.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from pydantic import Field

from ..model import Dataset
from ..model.common import Out
from ..time.capacity import day_capacity
from ..validate import Issue
from .leadtime import resource_calendar
from .mrp import run_mrp
from .result import PlanResult


class LevelMove(Out):
    order: str                       # id in the levelled plan
    location: str
    product: str
    qty: float
    need_date: dt.date
    was_start: dt.date
    was_available: dt.date
    start: dt.date
    available: dt.date
    shift_days: int                  # available date change (negative = earlier)
    late_days: int                   # available after the need date, levelled
    step_resources: dict[int, str] = Field(default_factory=dict)   # steps on an alternative machine


class LevelResource(Out):
    resource: str
    finite: bool
    peak_before: float               # worst day's load ÷ capacity
    peak_after: float
    overloaded_days_before: int
    overloaded_days_after: int
    hours: float                     # total load (the same before and after, up to the horizon's edge)


class LevelPreview(Out):
    ok: bool
    active: bool                     # the dataset already plans within capacity
    moves: list[LevelMove] = Field(default_factory=list)
    resources: list[LevelResource] = Field(default_factory=list)
    late_before: int = 0             # make orders available after their need date
    late_after: int = 0
    fill_before: float = 1.0
    fill_after: float = 1.0
    issues: list[Issue] = Field(default_factory=list)


def _with(ds: Dataset, on: bool) -> Dataset:
    return ds.model_copy(update={"settings": ds.settings.model_copy(update={"capacity_constrained": on})})


def _days(ds: Dataset, p: PlanResult) -> dict[str, tuple[float, int]]:
    out = {}
    start = ds.scheduling.day_start_hour
    for rp in p.resources:
        r = ds.resource_by_id[rp.resource]
        cal = resource_calendar(ds, r.id)
        peak, over = 0.0, 0
        for d, h in rp.daily_load.items():
            cap = day_capacity(r, cal, d, start).productive_hours
            u = h / cap if cap > 0 else (float("inf") if h > 1e-9 else 0.0)
            peak = max(peak, u)
            over += u > 1 + 1e-6
        out[rp.resource] = (peak, over)
    return out


def level_preview(ds: Dataset) -> LevelPreview:
    off = run_mrp(_with(ds, False))
    if not off.ok:
        return LevelPreview(ok=False, active=ds.settings.capacity_constrained, issues=off.issues)
    on = run_mrp(_with(ds, True))
    out = LevelPreview(ok=True, active=ds.settings.capacity_constrained, fill_before=off.kpis.on_time_fill_rate,
                       fill_after=on.kpis.on_time_fill_rate)
    key = lambda o: (o.location, o.product, o.need_date, o.source_id)   # noqa: E731
    was = defaultdict(list)
    for o in off.orders:
        if o.kind == "make":
            was[key(o)].append(o)
    for o in on.orders:
        if o.kind != "make":
            continue
        cands = was.get(key(o))
        if not cands:
            continue
        b = min(cands, key=lambda x: abs(x.qty - o.qty))
        cands.remove(b)
        if b.available_date == o.available_date and b.start_date == o.start_date and not o.step_resources:
            continue
        out.moves.append(LevelMove(
            order=o.id, location=o.location, product=o.product, qty=o.qty, need_date=o.need_date,
            was_start=b.start_date, was_available=b.available_date, start=o.start_date, available=o.available_date,
            shift_days=(o.available_date - b.available_date).days,
            late_days=max(0, (o.available_date - o.need_date).days), step_resources=dict(o.step_resources)))
    out.moves.sort(key=lambda m: (-m.late_days, m.shift_days, m.need_date, m.order))
    out.late_before = sum(1 for o in off.orders if o.kind == "make" and o.available_date > o.need_date)
    out.late_after = sum(1 for o in on.orders if o.kind == "make" and o.available_date > o.need_date)
    a, b = _days(ds, off), _days(ds, on)
    for rp in off.resources:
        out.resources.append(LevelResource(
            resource=rp.resource, finite=rp.finite, peak_before=a[rp.resource][0], peak_after=b[rp.resource][0],
            overloaded_days_before=a[rp.resource][1], overloaded_days_after=b[rp.resource][1],
            hours=sum(rp.daily_load.values())))
    return out


__all__ = ["LevelMove", "LevelPreview", "LevelResource", "level_preview"]
