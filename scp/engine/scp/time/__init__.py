"""Calendars (working-day arithmetic) and planning buckets with real calendar dates."""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

from ..model import BucketSize, Calendar, Settings

ALL_DAYS = Calendar(id="SYS-7DAY", name="7-day", workdays=[0, 1, 2, 3, 4, 5, 6])


class WorkCalendar:
    """Working-day arithmetic over a :class:`Calendar`."""

    def __init__(self, cal: Calendar | None):
        cal = cal or ALL_DAYS
        self.id = cal.id
        self._workdays = frozenset(cal.workdays)
        self._holidays = frozenset(cal.holidays)

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self._workdays and d not in self._holidays

    def next_workday(self, d: date) -> date:
        """``d`` itself if it is a working day, else the next one."""
        for _ in range(400):
            if self.is_workday(d):
                return d
            d += timedelta(days=1)
        raise ValueError(f"calendar {self.id} has no working day within 400 days of {d}")

    def prev_workday(self, d: date) -> date:
        for _ in range(400):
            if self.is_workday(d):
                return d
            d -= timedelta(days=1)
        raise ValueError(f"calendar {self.id} has no working day within 400 days before {d}")

    def add_workdays(self, d: date, n: float) -> date:
        """Move ``n`` working days from ``d`` (fractional n rounds up). ``n`` may be negative.

        Adding 0 returns ``d`` unchanged; adding k>0 lands on the k-th working day after ``d``.
        """
        k = math.ceil(abs(n) - 1e-9)
        step = 1 if n >= 0 else -1
        cur = d
        guard = 0
        while k > 0:
            cur += timedelta(days=step)
            guard += 1
            if guard > 5000:
                raise ValueError(f"calendar {self.id}: cannot move {n} working days from {d}")
            if self.is_workday(cur):
                k -= 1
        return cur

    def workdays_between(self, start: date, end: date) -> int:
        """Working days in [start, end)."""
        if end <= start:
            return 0
        n = 0
        d = start
        while d < end:
            if self.is_workday(d):
                n += 1
            d += timedelta(days=1)
        return n


@dataclass(frozen=True)
class Bucket:
    index: int
    start: date   # inclusive
    end: date     # exclusive
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days


class Buckets:
    """Planning buckets from ``settings.planning_start`` over ``settings.horizon_days``.

    Weeks align to ``settings.week_start`` and months to calendar months, so the first bucket may
    be partial. Labels are real dates, never "P01".
    """

    def __init__(self, settings: Settings):
        self.start = settings.planning_start
        self.end = settings.planning_start + timedelta(days=settings.horizon_days)
        self.size = settings.bucket
        self.items: list[Bucket] = []
        cur = self.start
        i = 0
        while cur < self.end:
            nxt = min(self._next_boundary(cur, settings), self.end)
            self.items.append(Bucket(i, cur, nxt, self._label(cur)))
            cur = nxt
            i += 1
        self._starts = [b.start for b in self.items]

    def _next_boundary(self, d: date, settings: Settings) -> date:
        if self.size is BucketSize.DAY:
            return d + timedelta(days=1)
        if self.size is BucketSize.WEEK:
            delta = (settings.week_start - d.weekday()) % 7 or 7
            return d + timedelta(days=delta)
        if d.month == 12:
            return date(d.year + 1, 1, 1)
        return date(d.year, d.month + 1, 1)

    def _label(self, d: date) -> str:
        if self.size is BucketSize.DAY:
            return d.strftime("%a %d %b %Y")
        if self.size is BucketSize.WEEK:
            iso = d.isocalendar()
            return f"W{iso.week:02d} {d.strftime('%d %b %Y')}"
        return d.strftime("%b %Y")

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, i: int) -> Bucket:
        return self.items[i]

    def index_of(self, d: date) -> int:
        """Bucket index containing ``d``; -1 before the horizon, len(self) at/after its end."""
        if d < self.start:
            return -1
        if d >= self.end:
            return len(self.items)
        return bisect_right(self._starts, d) - 1

    def in_horizon(self, d: date) -> bool:
        return self.start <= d < self.end
