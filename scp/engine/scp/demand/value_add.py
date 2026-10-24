"""Forecast value add: does each layer of the forecast make it better? (Enterprise plan 4.2.)

Every release keeps what each layer said for each period (:class:`~scp.model.ForecastSnapshot`): the naïve forecast,
the champion model, the forecast after demand events and new products, and the consensus after the planners'
overrides. Once a period has sold, each layer is judged against the sales of that period: its error (WAPE, the
absolute misses over the sales) and its bias (over minus under, over the sales). A layer adds value when it misses
less than the layer before it. Measured in total, per product family and per planner (on the periods that planner
overrode), with the overrides that cost the most accuracy named.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from ..model import Dataset, ForecastPeriod, ForecastSnapshot
from ..model.common import Out
from .periods import label, next_start, period_start

LAYERS: tuple[tuple[str, str], ...] = (
    ("naive", "Naïve (last period's sales)"),
    ("statistical", "Statistical model"),
    ("adjusted", "Events and new products"),
    ("final", "Planners' overrides (consensus)"),
)
NO_FAMILY = "No family"
TS_WINDOW = 13     # periods the tracking signal reads: a quarter of weeks, a year of months
TS_LIMIT = 4.0     # |RSFE / MAD| at or past which a forecast is biased (the APICS ±4 limit)
TS_MIN = 4         # periods needed before a series is judged
NOT_NAMED = "Not named"
WORST = 8


class LayerScore(Out):
    layer: Literal["naive", "statistical", "adjusted", "final"]
    label: str
    forecast: float                     # Σ of the layer's forecast over the measured periods
    wape: float | None = None           # Σ |forecast − sales| / Σ sales
    bias: float | None = None           # Σ (forecast − sales) / Σ sales: + over-forecast, − under
    value_add: float | None = None      # WAPE of the layer before − this layer's WAPE (+ = it helped); none for naïve


class ValueAddGroup(Out):
    key: str
    label: str
    periods: int                        # series-periods measured
    actual: float                       # their sales
    layers: list[LayerScore]
    overrides: int = 0                  # of those, overridden by a planner
    improved: int = 0                   # overrides that came closer to the sales than the number they replaced


class ValueAddPeriod(Out):
    start: dt.date
    label: str
    actual: float
    statistical_wape: float | None = None
    final_wape: float | None = None


class CostlyOverride(Out):
    location: str
    product: str
    start: dt.date
    label: str
    author: str
    actual: float
    adjusted: float                     # what the override replaced
    final: float
    cost: float                         # |final − sales| − |adjusted − sales|: units of error the override added


class Tracking(Out):
    """One series' tracking signal over its last measured periods: the running sum of the errors (forecast − sales)
    over their mean absolute size. Errors that cancel keep it near 0; a forecast that misses the same way every
    period walks it to ± the number of periods."""
    location: str
    product: str
    periods: int
    forecast: float
    actual: float
    rsfe: float                         # Σ (final − sales): + over-forecast
    mad: float                          # mean |final − sales|
    signal: float                       # RSFE / MAD
    biased: bool                        # |signal| ≥ TS_LIMIT
    direction: Literal["over", "under", ""]


class ValueAdd(Out):
    period: Literal["week", "month"]
    lag: int
    measured_to: dt.date | None = None  # periods ending by this day have sold (the sales on record reach it)
    measured: int = 0                   # series-periods judged
    waiting: int = 0                    # kept forecasts for periods not sold yet
    total: ValueAddGroup
    families: list[ValueAddGroup] = []
    planners: list[ValueAddGroup] = []  # each on the periods that planner overrode
    periods: list[ValueAddPeriod] = []
    costly: list[CostlyOverride] = []   # the overrides that moved the forecast furthest from the sales
    tracking: list[Tracking] = []       # per series, the most biased first
    tracking_limit: float = TS_LIMIT
    biased: int = 0                     # series whose tracking signal is past the limit
    notes: list[str] = []


@dataclass
class _Row:
    k: ForecastSnapshot
    actual: float

    def layer(self, name: str) -> float:
        return float(getattr(self.k, name))

    @property
    def over(self) -> bool:
        return self.k.overridden or bool(self.k.author)

    @property
    def planner(self) -> str:
        return self.k.author or NOT_NAMED


def _sales(ds: Dataset, period: ForecastPeriod) -> tuple[dict[tuple[str, str, dt.date], float], dt.date | None]:
    """Sales per series and period, and the day the sales on record reach: the end of the period holding the latest
    row, never into the period in which planning starts (the rule the forecast's own history follows)."""
    from .pipeline import _spread
    ws = ds.settings.week_start
    horizon = period_start(ds.settings.planning_start, period, ws)
    out: dict[tuple[str, str, dt.date], float] = defaultdict(float)
    last: dt.date | None = None
    base = ds.planning_base
    for r in ds.history:
        b, factor = base.get(r.product, (r.product, 1.0))   # a variant sells for its planning material's forecast
        for ps, q in _spread(r.date, r.qty, r.period_days, period, ws):
            if ps >= horizon:
                continue
            out[(r.location, b, ps)] += q * factor
            last = ps if last is None or ps > last else last
    return out, (min(next_start(last, period), horizon) if last is not None else None)


def _group(key: str, name: str, rows: list[_Row]) -> ValueAddGroup:
    act = sum(r.actual for r in rows)
    layers: list[LayerScore] = []
    before: float | None = None
    for i, (lay, lab) in enumerate(LAYERS):
        f = sum(r.layer(lay) for r in rows)
        err = sum(abs(r.layer(lay) - r.actual) for r in rows)
        wape = err / act if act > 0 else None
        bias = (f - act) / act if act > 0 else None
        layers.append(LayerScore(layer=lay, label=lab, forecast=round(f, 4), wape=wape, bias=bias,
                                 value_add=(before - wape) if i and before is not None and wape is not None else None))
        before = wape
    over = [r for r in rows if r.over]
    return ValueAddGroup(key=key, label=name, periods=len(rows), actual=round(act, 4), layers=layers,
                         overrides=len(over),
                         improved=sum(abs(r.k.final - r.actual) < abs(r.k.adjusted - r.actual) for r in over))


def value_add(ds: Dataset) -> ValueAdd:
    fs = ds.forecasting
    period = fs.period
    sales, to = _sales(ds, period)
    latest: dict[tuple[str, str, dt.date], ForecastSnapshot] = {}
    for k in ds.forecast_snapshots:     # a duplicate (an edited import) counts once: the last row wins
        latest[(k.location, k.product, k.start)] = k
    rows: list[_Row] = []
    waiting = 0
    for (loc, prod, start), k in sorted(latest.items()):
        if to is None or k.end > to:
            waiting += 1
            continue
        rows.append(_Row(k, sales.get((loc, prod, start), 0.0)))

    notes: list[str] = []
    if not ds.forecast_snapshots:
        notes.append("No forecast has been released yet. Each release keeps what every layer said for each period; "
                     "they are judged here once the periods have sold.")
    elif not rows:
        notes.append(f"{waiting} kept forecast periods are waiting for their sales: they are judged once the sales "
                     "for those periods are in the sales history.")
    if rows and not any(r.over for r in rows):
        notes.append("No measured period was overridden by a planner, so the consensus equals the forecast after "
                     "events.")

    fam = {p.id: p.family for p in ds.products}
    by_fam: dict[str, list[_Row]] = defaultdict(list)
    by_planner: dict[str, list[_Row]] = defaultdict(list)
    by_period: dict[dt.date, list[_Row]] = defaultdict(list)
    for r in rows:
        by_fam[fam.get(r.k.product) or NO_FAMILY].append(r)
        by_period[r.k.start].append(r)
        if r.over:
            by_planner[r.planner].append(r)
    families = [_group(f, f, rs) for f, rs in sorted(by_fam.items(), key=lambda kv: (kv[0] == NO_FAMILY, kv[0]))]
    planners = [_group(a, a, rs) for a, rs in sorted(by_planner.items(), key=lambda kv: (kv[0] == NOT_NAMED, kv[0]))]

    trend = []
    for start, rs in sorted(by_period.items()):
        act = sum(r.actual for r in rs)
        trend.append(ValueAddPeriod(
            start=start, label=label(start, period), actual=round(act, 4),
            statistical_wape=sum(abs(r.k.statistical - r.actual) for r in rs) / act if act > 0 else None,
            final_wape=sum(abs(r.k.final - r.actual) for r in rs) / act if act > 0 else None))

    costly = sorted((CostlyOverride(location=r.k.location, product=r.k.product, start=r.k.start,
                                    label=label(r.k.start, period), author=r.planner, actual=round(r.actual, 4),
                                    adjusted=r.k.adjusted, final=r.k.final,
                                    cost=round(abs(r.k.final - r.actual) - abs(r.k.adjusted - r.actual), 4))
                     for r in rows if r.over), key=lambda c: (-c.cost, c.start, c.location, c.product))
    tracking = _tracking(rows)
    return ValueAdd(period=period.value, lag=fs.fva_lag, measured_to=to, measured=len(rows), waiting=waiting,
                    total=_group("*", "All products", rows), families=families, planners=planners, periods=trend,
                    costly=[c for c in costly if c.cost > 1e-9][:WORST], tracking=tracking,
                    biased=sum(t.biased for t in tracking), notes=notes)


def _tracking(rows: list[_Row]) -> list[Tracking]:
    by: dict[tuple[str, str], list[_Row]] = defaultdict(list)
    for r in rows:
        by[(r.k.location, r.k.product)].append(r)
    out: list[Tracking] = []
    for (loc, prod), rs in by.items():
        last = sorted(rs, key=lambda r: r.k.start)[-TS_WINDOW:]
        if len(last) < TS_MIN:
            continue
        errs = [r.k.final - r.actual for r in last]
        rsfe = sum(errs)
        mad = sum(abs(e) for e in errs) / len(errs)
        sig = rsfe / mad if mad > 1e-9 else 0.0
        out.append(Tracking(location=loc, product=prod, periods=len(last), forecast=round(sum(r.k.final for r in last), 4),
                            actual=round(sum(r.actual for r in last), 4), rsfe=round(rsfe, 4), mad=round(mad, 4),
                            signal=round(sig, 4), biased=abs(sig) >= TS_LIMIT - 1e-9,
                            direction="over" if sig > 1e-9 else "under" if sig < -1e-9 else ""))
    return sorted(out, key=lambda t: (-abs(t.signal), t.location, t.product))
