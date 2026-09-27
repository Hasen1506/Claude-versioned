"""Forecast periods: whole weeks (aligned to ``settings.week_start``) or calendar months.

History is aggregated to these periods and the forecast is produced per period. The planning
horizon rarely starts or ends on a period boundary, so the first and last forecast periods may be
*partial*: their quantity is prorated by calendar days when released.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..model import ForecastPeriod


def period_start(d: date, period: ForecastPeriod, week_start: int) -> date:
    if period is ForecastPeriod.WEEK:
        return d - timedelta(days=(d.weekday() - week_start) % 7)
    return d.replace(day=1)


def next_start(start: date, period: ForecastPeriod) -> date:
    if period is ForecastPeriod.WEEK:
        return start + timedelta(days=7)
    return date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)


def label(start: date, period: ForecastPeriod) -> str:
    if period is ForecastPeriod.WEEK:
        return f"W{start.isocalendar().week:02d} {start.strftime('%d %b %Y')}"
    return start.strftime("%b %Y")


def default_season(period: ForecastPeriod) -> int:
    return 52 if period is ForecastPeriod.WEEK else 12


def mean_days(period: ForecastPeriod) -> float:
    return 7.0 if period is ForecastPeriod.WEEK else 365.25 / 12


@dataclass(frozen=True)
class Period:
    start: date          # full period start
    end: date            # full period end (exclusive)
    label: str
    from_: date          # part of the period inside the horizon: [from_, to)
    to: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def share(self) -> float:
        """Fraction of the period that falls inside the horizon."""
        return (self.to - self.from_).days / self.days


def future_periods(first_day: date, last_day_excl: date, period: ForecastPeriod, week_start: int) -> list[Period]:
    """Periods covering [first_day, last_day_excl), clipped to that window."""
    out: list[Period] = []
    s = period_start(first_day, period, week_start)
    while s < last_day_excl:
        e = next_start(s, period)
        out.append(Period(s, e, label(s, period), max(s, first_day), min(e, last_day_excl)))
        s = e
    return out


def history_periods(first_day: date, end: date, period: ForecastPeriod, week_start: int) -> list[date]:
    """Starts of the periods from the one containing ``first_day`` up to the period start ``end``
    (exclusive)."""
    s = period_start(first_day, period, week_start)
    out: list[date] = []
    while s < end:
        out.append(s)
        s = next_start(s, period)
    return out
