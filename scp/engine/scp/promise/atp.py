"""Cumulative ATP with look-ahead (S/4 guide §7.1).

Day ``i`` is ``origin + i``. ``cum(i) = Σ inflows(≤ i) − Σ outflows(≤ i)``. What a *new* requirement can
take on day ``i`` without breaking an earlier promise later on is the look-ahead minimum

    ATP(i) = min_{i ≤ j < H} cum(j)

where ``H`` is the end of the checked window: the replenishment lead time (RLT) when confirmation
beyond RLT is unconditional, else the checking horizon. From ``H`` on, everything is confirmable.
"""
from __future__ import annotations

import math

EPS = 1e-6


class AtpSeries:
    def __init__(self, days: int, rlt_day: int | None = None) -> None:
        self.days = days
        self.inflow = [0.0] * days
        self.outflow = [0.0] * days
        self.rlt_day = rlt_day          # first day that is unconditional (None = never)
        self._atp: list[float] | None = None

    # ---- mutation -------------------------------------------------------------------------------
    def _i(self, day: int) -> int:
        return min(max(day, 0), self.days - 1)

    def add_in(self, day: int, qty: float) -> None:
        self.inflow[self._i(day)] += qty
        self._atp = None

    def add_out(self, day: int, qty: float) -> None:
        self.outflow[self._i(day)] += qty
        self._atp = None

    def snapshot(self) -> tuple[list[float], list[float]]:
        return list(self.inflow), list(self.outflow)

    def restore(self, snap: tuple[list[float], list[float]]) -> None:
        self.inflow, self.outflow = list(snap[0]), list(snap[1])
        self._atp = None

    # ---- queries --------------------------------------------------------------------------------
    @property
    def horizon(self) -> int:
        return self.rlt_day if self.rlt_day is not None else self.days

    def cum(self) -> list[float]:
        out, c = [], 0.0
        for a, b in zip(self.inflow, self.outflow, strict=True):
            c += a - b
            out.append(c)
        return out

    def atp(self) -> list[float]:
        if self._atp is None:
            c = self.cum()
            h = min(self.horizon, self.days)
            out = [math.inf] * self.days
            run = math.inf
            for j in range(h - 1, -1, -1):
                run = min(run, c[j])
                out[j] = run
            self._atp = out
        return self._atp

    def available(self, day: int) -> float:
        """What a new requirement can take on ``day`` (∞ at or beyond the RLT day)."""
        if day >= self.days:
            return math.inf if self.rlt_day is not None else 0.0
        return max(0.0, self.atp()[max(day, 0)])

    def unconditional(self, day: int) -> bool:
        return self.rlt_day is not None and day >= self.rlt_day

    def shortage(self) -> tuple[int, float] | None:
        """First day inside the checked window where promises exceed supply, and by how much."""
        c = self.cum()
        for j in range(min(self.horizon, self.days)):
            if c[j] < -EPS:
                return j, -min(c[j:min(self.horizon, self.days)])
        return None

    def first_firm(self, qty: float, start: int = 0) -> int | None:
        """First day ≥ start on which ``qty`` of real supply can be taken."""
        c = self.cum()
        suffix = [0.0] * (self.days + 1)
        suffix[self.days] = math.inf
        for j in range(self.days - 1, -1, -1):
            suffix[j] = min(suffix[j + 1], c[j])
        for i in range(max(start, 0), self.days):
            if suffix[i] >= qty - EPS:
                return i
        return None
