"""Working time on one resource unit: shift windows on its calendar, measured in clock hours from the
schedule origin (planning start, 00:00). Work is productive hours; a unit delivers the window's
``efficiency`` productive hours per clock hour inside it, so ``work`` hours take ``work / efficiency`` clock
hours. The windows come from one stretch per working day (``start_hour`` for ``span_hours``) or, when
``days`` is given, from a function that returns each day's windows and efficiency (named shifts, breaks
and capacity changes: :func:`scp.time.capacity.day_capacity`).
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from datetime import date, timedelta

from ..time import WorkCalendar

EPS = 1e-9
_MAX_DAYS = 4000
_LOOK = 400      # days to look ahead for the next working time
INF = float("inf")


DayWindows = Callable[[date], tuple[list[tuple[float, float]], float]]


class ResourceClock:
    def __init__(self, cal: WorkCalendar, origin: date, start_hour: float, span_hours: float,
                 efficiency: float, days: DayWindows | None = None) -> None:
        self.cal = cal
        self.origin = origin
        self.start_hour = start_hour
        self.span = span_hours
        self.eff = efficiency
        self.days = days
        self.win_s: list[float] = []
        self.win_e: list[float] = []
        self.win_f: list[float] = []   # efficiency inside each window
        self._day = 0

    def _day_windows(self, d: date) -> tuple[list[tuple[float, float]], float]:
        if self.days is not None:
            return self.days(d)
        return ([(self.start_hour, self.start_hour + self.span)] if self.cal.is_workday(d) else []), self.eff

    def _extend(self, t: float) -> None:
        """Generate windows until one ends after ``t``."""
        while not self.win_e or self.win_e[-1] <= t + EPS:
            if self._day > _MAX_DAYS or self._day * 24.0 > t + _LOOK * 24.0:
                return   # no working time ahead (a unit that only exists for a while, or a shut-down resource)
            d = self.origin + timedelta(days=self._day)
            wins, eff = self._day_windows(d)
            for a, b in wins:
                s, e = self._day * 24.0 + a, self._day * 24.0 + b
                if self.win_e and s < self.win_e[-1] - EPS:
                    # an overnight shift from the day before still running: join, never overlap
                    s = self.win_e[-1]
                    if e <= s + EPS:
                        continue
                if self.win_e and abs(s - self.win_e[-1]) <= EPS and abs(self.win_f[-1] - eff) <= EPS:
                    self.win_e[-1] = e
                    continue
                self.win_s.append(s)
                self.win_e.append(e)
                self.win_f.append(eff)
            self._day += 1

    def _index(self, t: float) -> int:
        """Index of the first window that ends after ``t`` (``len`` of the windows when there is none)."""
        self._extend(t)
        return bisect_right(self.win_e, t + EPS)

    def next_open(self, t: float) -> float:
        """The first working instant at or after ``t`` (infinity when there is none)."""
        i = self._index(t)
        return max(t, self.win_s[i]) if i < len(self.win_s) else INF

    def advance(self, t: float, work: float) -> tuple[float, float]:
        """Start at the first working instant ≥ ``t`` and consume ``work`` productive hours.

        Returns (start, end) in clock hours; the job pauses outside the shift windows."""
        start = self.next_open(t)
        left = work
        if left <= EPS or start == INF:
            return start, start
        i = self._index(start)
        cur = start
        while True:
            f = self.win_f[i]
            avail = (self.win_e[i] - cur) * f
            if left <= avail + EPS:
                return start, cur + left / f
            left -= avail
            i += 1
            if i >= len(self.win_s):
                self._extend(self.win_e[-1])
                if i >= len(self.win_s):
                    return start, INF
            cur = self.win_s[i]

    def work_between(self, a: float, b: float) -> float:
        """Productive hours available in [a, b]."""
        if b <= a:
            return 0.0
        self._extend(b)
        i = bisect_right(self.win_e, a + EPS)
        tot = 0.0
        while i < len(self.win_s) and self.win_s[i] < b:
            tot += max(0.0, min(b, self.win_e[i]) - max(a, self.win_s[i])) * self.win_f[i]
            i += 1
        return tot

    def open_between(self, a: float, b: float) -> float:
        """Clock hours inside shift windows in [a, b]."""
        if b <= a:
            return 0.0
        self._extend(b)
        i = bisect_right(self.win_e, a + EPS)
        tot = 0.0
        while i < len(self.win_s) and self.win_s[i] < b:
            tot += max(0.0, min(b, self.win_e[i]) - max(a, self.win_s[i]))
            i += 1
        return tot

    def windows(self, a: float, b: float) -> list[tuple[float, float]]:
        self._extend(b)
        i = bisect_right(self.win_e, a + EPS)
        out = []
        while i < len(self.win_s) and self.win_s[i] < b:
            out.append((self.win_s[i], self.win_e[i]))
            i += 1
        return out


def after_queue(cal: WorkCalendar, origin: date, t: float, queue_workdays: float) -> float:
    """Earliest start of the next operation when an operation ends at ``t`` and is followed by
    ``queue_workdays`` of wait/move time: the queue occupies the next working days after the
    operation's last day, and the next operation may start on the working day after that."""
    if queue_workdays <= EPS:
        return t
    end_excl = origin + timedelta(days=int(-(-(t - EPS) // 24)))   # the day after the op's last day
    d = cal.add_workdays(cal.next_workday(end_excl), queue_workdays)
    return (d - origin).days * 24.0
