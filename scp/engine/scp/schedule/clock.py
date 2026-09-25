"""Working time on one resource: shift windows on its calendar, measured in clock hours from the
schedule origin (planning start, 00:00). Work is productive hours; a unit delivers ``efficiency``
productive hours per clock hour inside a window, so ``work`` hours take ``work / efficiency`` clock hours.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta

from ..time import WorkCalendar

EPS = 1e-9
_MAX_DAYS = 4000


class ResourceClock:
    def __init__(self, cal: WorkCalendar, origin: date, start_hour: float, span_hours: float,
                 efficiency: float) -> None:
        self.cal = cal
        self.origin = origin
        self.start_hour = start_hour
        self.span = span_hours
        self.eff = efficiency
        self.win_s: list[float] = []
        self.win_e: list[float] = []
        self._day = 0

    def _extend(self, t: float) -> None:
        """Generate windows until one ends after ``t``."""
        while not self.win_e or self.win_e[-1] <= t + EPS:
            if self._day > _MAX_DAYS:
                raise ValueError(f"calendar {self.cal.id}: no working time within {_MAX_DAYS} days")
            d = self.origin + timedelta(days=self._day)
            if self.cal.is_workday(d):
                s = self._day * 24.0 + self.start_hour
                self.win_s.append(s)
                self.win_e.append(s + self.span)
            self._day += 1

    def _index(self, t: float) -> int:
        """Index of the first window that ends after ``t``."""
        self._extend(t)
        return bisect_right(self.win_e, t + EPS)

    def next_open(self, t: float) -> float:
        i = self._index(t)
        return max(t, self.win_s[i])

    def advance(self, t: float, work: float) -> tuple[float, float]:
        """Start at the first working instant ≥ ``t`` and consume ``work`` productive hours.

        Returns (start, end) in clock hours; the job pauses outside the shift windows."""
        start = self.next_open(t)
        left = work / self.eff
        if left <= EPS:
            return start, start
        i = self._index(start)
        cur = start
        while True:
            avail = self.win_e[i] - cur
            if left <= avail + EPS:
                return start, cur + left
            left -= avail
            i += 1
            while i >= len(self.win_s):
                self._extend(self.win_e[-1])
            cur = self.win_s[i]

    def work_between(self, a: float, b: float) -> float:
        """Productive hours available in [a, b]."""
        if b <= a:
            return 0.0
        self._extend(b)
        i = bisect_right(self.win_e, a + EPS)
        tot = 0.0
        while i < len(self.win_s) and self.win_s[i] < b:
            tot += max(0.0, min(b, self.win_e[i]) - max(a, self.win_s[i]))
            i += 1
        return tot * self.eff

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
