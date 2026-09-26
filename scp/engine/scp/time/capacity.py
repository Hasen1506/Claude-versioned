"""Resource capacity by day: the one place shifts, breaks and capacity changes turn into working time.

A resource works on the working days of its calendar. On such a day it runs its named shifts (each
window a stretch of clock time, split around its break) or, without named shifts, ``shifts_per_day ×
hours_per_shift`` in one stretch from the scheduling day start. A capacity change covering the day
replaces the shifts, the number of units or the efficiency for that day (the last matching change
wins), so a second shift from November or a week of maintenance is planned as it will happen.

MRP, S&OP and the rough-cut checks use :func:`hours_between`; the finite scheduler uses
:func:`day_windows` for the exact clock times.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..model import CapacityChange, Resource
from . import WorkCalendar


@dataclass(frozen=True)
class DayCapacity:
    windows: tuple[tuple[float, float], ...]   # clock hours from the start of the day (may pass 24)
    units: int
    efficiency: float

    @property
    def clock_hours(self) -> float:
        return sum(b - a for a, b in self.windows)

    @property
    def productive_hours(self) -> float:
        """Productive hours of all units together."""
        return self.clock_hours * self.efficiency * self.units


def change_on(r: Resource, d: date) -> CapacityChange | None:
    hit = None
    for ch in r.capacity_changes:
        if ch.covers(d):
            hit = ch
    return hit


def day_capacity(r: Resource, cal: WorkCalendar, d: date, day_start: float = 6.0) -> DayCapacity:
    ch = change_on(r, d)
    units = ch.units if ch is not None and ch.units is not None else r.units
    eff = ch.efficiency if ch is not None and ch.efficiency is not None else r.efficiency
    if not cal.is_workday(d) or units <= 0:
        return DayCapacity((), max(units, 0), eff)
    shifts = ch.shifts if ch is not None and ch.shifts is not None else r.shifts
    if ch is not None and ch.shifts is None and ch.shifts_per_day is not None:
        shifts = []
        span = ch.shifts_per_day * r.hours_per_shift
    else:
        span = r.shifts_per_day * r.hours_per_shift
    if shifts:
        wins = sorted(w for s in shifts if s.runs_on(d.weekday()) for w in s.windows())
    else:
        wins = [(day_start, day_start + span)]
    merged: list[tuple[float, float]] = []
    for a, b in wins:
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return DayCapacity(tuple(merged), units, eff)


def hours_between(r: Resource, cal: WorkCalendar, start: date, end: date, day_start: float = 6.0) -> float:
    """Productive hours of all units in [start, end)."""
    tot = 0.0
    d = start
    while d < end:
        tot += day_capacity(r, cal, d, day_start).productive_hours
        d += timedelta(days=1)
    return tot


def overtime_between(r: Resource, cal: WorkCalendar, start: date, end: date) -> float:
    """Overtime hours all units may add in [start, end): the resource's daily overtime on each day it works."""
    tot = 0.0
    d = start
    while d < end:
        dc = day_capacity(r, cal, d)
        if dc.windows:
            tot += r.overtime_hours_per_day * dc.units
        d += timedelta(days=1)
    return tot


def max_units(r: Resource) -> int:
    return max([r.units, *(ch.units for ch in r.capacity_changes if ch.units is not None)])


__all__ = ["DayCapacity", "change_on", "day_capacity", "hours_between", "max_units", "overtime_between"]
