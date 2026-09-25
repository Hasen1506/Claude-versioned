"""Demand planning run: history → cleansing → segmentation → model competition → events → NPI →
consensus overrides → release as forecast demand.

Every step is visible in the result: the raw and cleansed history with the reason for each change,
the full leaderboard, the statistical forecast, the event factor, cannibalisation, and the override,
so a planner can see why a number is what it is.
"""
from __future__ import annotations

import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np

from ..model import (
    Dataset, DemandKind, DemandRecord, ForecastModelId, ForecastPeriod, NpiRule, OutlierMethod,
)
from ..validate import blocks_demand, validate
from . import foundation as fm
from .competition import Outcome, compete, origins
from .models import INTERMITTENT_ONLY, SMOOTH_ONLY, SPECS
from .periods import (
    Period, default_season, future_periods, history_periods, label, mean_days, next_start, period_start,
)
from .result import (
    BacktestPoint, CvSuggestion, ForecastPoint, ForecastResult, FoundationStatus, HistoryPoint, ModelScore,
    ReleaseResult, Segment, Series, Summary,
)

ADI_CUT = 1.32   # Syntetos, Boylan & Croston (2005) demand-pattern boundaries
CV2_CUT = 0.49
SERVICE_LEVEL = {  # suggested cycle service level per ABC-XYZ cell
    ("A", "X"): 0.98, ("A", "Y"): 0.97, ("A", "Z"): 0.95,
    ("B", "X"): 0.96, ("B", "Y"): 0.95, ("B", "Z"): 0.93,
    ("C", "X"): 0.93, ("C", "Y"): 0.92, ("C", "Z"): 0.90,
}
HISTORY_PROMO = "history-promo"


def key_of(location: str, product: str) -> str:
    return f"{location}|{product}"


# ---- history ------------------------------------------------------------------------------------
@dataclass
class _Hist:
    location: str
    product: str
    starts: list[date]
    raw: np.ndarray
    revenue: float
    flags: list[str | None] = field(default_factory=list)
    events: list[list[str]] = field(default_factory=list)
    cleaned: np.ndarray = field(default_factory=lambda: np.zeros(0))
    lifts: dict[str, float] = field(default_factory=dict)
    lift_sums: dict[str, tuple[float, float]] = field(default_factory=dict)
    pattern: str = "none"
    adi: float | None = None
    cv2: float | None = None


def _aggregate(ds: Dataset, period: ForecastPeriod, cutoff: date) -> dict[tuple[str, str], _Hist]:
    ws = ds.settings.week_start
    qty: dict[tuple[str, str], dict[date, float]] = defaultdict(lambda: defaultdict(float))
    promo: dict[tuple[str, str], set[date]] = defaultdict(set)
    revenue: dict[tuple[str, str], float] = defaultdict(float)
    first: dict[tuple[str, str], date] = {}
    horizon_start = period_start(cutoff, period, ws)
    # History runs through the period holding the latest row of the whole dataset (never into the
    # period in which planning starts). A series without rows in a period inside that range sold zero.
    usable = [r.date for r in ds.history if period_start(r.date, period, ws) < horizon_start]
    if not usable:
        return {}
    data_end = min(next_start(period_start(max(usable), period, ws), period), horizon_start)
    for r in ds.history:
        k = (r.location, r.product)
        ps = period_start(r.date, period, ws)
        if ps >= horizon_start:
            continue
        qty[k][ps] += r.qty
        if r.promo:
            promo[k].add(ps)
        prod = ds.product_by_id.get(r.product)
        price = r.price if r.price is not None else (prod.price or prod.standard_cost or 0.0) if prod else 0.0
        revenue[k] += r.qty * price
        if r.qty > 0 and (k not in first or ps < first[k]):
            first[k] = ps
    out: dict[tuple[str, str], _Hist] = {}
    for k, by_period in qty.items():
        if k not in first:
            continue  # only zeros: nothing to learn from
        starts = history_periods(first[k], data_end, period, ws)
        if not starts:
            continue
        raw = np.array([by_period.get(s, 0.0) for s in starts], dtype=float)
        h = _Hist(k[0], k[1], starts, raw, revenue[k])
        h.flags = [None] * len(starts)
        h.events = [[] for _ in starts]
        for i, s in enumerate(starts):
            if s in promo[k]:
                h.flags[i] = "event"
                h.events[i].append(HISTORY_PROMO)
        out[k] = h
    return out


def _mark_events(ds: Dataset, h: _Hist, period: ForecastPeriod) -> None:
    for e in ds.events:
        if not e.applies(h.location, h.product):
            continue
        for i, s in enumerate(h.starts):
            if s <= e.end and next_start(s, period) > e.start:
                h.flags[i] = "event"
                h.events[i].append(e.id)


def _pattern(y: np.ndarray) -> tuple[str, float | None, float | None]:
    nz = y[y > 0]
    if len(nz) == 0:
        return "none", None, None
    adi = len(y) / len(nz)
    cv2 = float((nz.std() / nz.mean()) ** 2) if len(nz) > 1 else 0.0
    if adi < ADI_CUT:
        return ("smooth" if cv2 < CV2_CUT else "erratic"), adi, cv2
    return ("intermittent" if cv2 < CV2_CUT else "lumpy"), adi, cv2


def _neighbour_median(y: np.ndarray, ok: np.ndarray, i: int, reach: int = 3) -> float | None:
    """Median of the ``reach`` nearest normal periods on each side of ``i``."""
    left = [y[j] for j in range(i - 1, -1, -1) if ok[j]][:reach]
    right = [y[j] for j in range(i + 1, len(y)) if ok[j]][:reach]
    vals = left + right
    return float(np.median(vals)) if vals else None


def _cleanse(ds: Dataset, h: _Hist, ev_kind: dict[str, str]) -> None:
    fs = ds.forecasting
    y = h.raw.copy()
    h.pattern, h.adi, h.cv2 = _pattern(h.raw)
    unflagged = np.array([f is None for f in h.flags])
    # 1. event periods → baseline from neighbouring normal periods; the ratio measures the lift
    for i, f in enumerate(h.flags):
        if f != "event":
            continue
        base = _neighbour_median(h.raw, unflagged, i)
        if base is None:
            continue
        y[i] = base
        for eid in h.events[i]:
            kind = ev_kind.get(eid, "promo")
            a, b = h.lift_sums.get(kind, (0.0, 0.0))
            h.lift_sums[kind] = (a + h.raw[i], b + base)
    for kind, (a, b) in h.lift_sums.items():
        if b > 0:
            h.lifts[kind] = a / b - 1
    # 2. outliers on normal periods: robust z of the residual to a centred rolling median.
    #    Skipped for intermittent / lumpy series, where every demand would look like an outlier.
    if fs.outlier_method is OutlierMethod.MAD and h.pattern in ("smooth", "erratic") and len(y) >= 8:
        idx = np.flatnonzero(unflagged)
        local = np.array([np.median(y[idx[max(0, j - 3):j + 4]]) for j in range(len(idx))])
        resid = y[idx] - local
        sigma = 1.4826 * float(np.median(np.abs(resid - np.median(resid))))
        if sigma > 0:
            z = resid / sigma
            for j, i in enumerate(idx):
                if abs(z[j]) > fs.outlier_threshold:
                    y[i] = max(0.0, local[j] + np.sign(z[j]) * fs.outlier_threshold * sigma)
                    h.flags[i] = "outlier"
    h.cleaned = y


def _abc(hists: list[_Hist], a: float, b: float) -> dict[tuple[str, str], tuple[str, float]]:
    total = sum(max(h.revenue, 0.0) for h in hists)
    use_qty = total <= 0
    vals = {(h.location, h.product): (float(h.raw.sum()) if use_qty else max(h.revenue, 0.0)) for h in hists}
    total = sum(vals.values()) or 1.0
    out: dict[tuple[str, str], tuple[str, float]] = {}
    cum = 0.0
    for k, v in sorted(vals.items(), key=lambda kv: -kv[1]):
        share_before = cum / total
        cum += v
        cls = "A" if share_before < a else "B" if share_before < b else "C"
        out[k] = (cls, v / total)
    return out


def _xyz(cv: float | None, x: float, y: float) -> str:
    if cv is None:
        return "Z"
    return "X" if cv < x else "Y" if cv < y else "Z"


# ---- the run -------------------------------------------------------------------------------------
@dataclass
class _Ctx:
    ds: Dataset
    period: ForecastPeriod
    m: int
    fut: list[Period]
    z: float


def _event_factors(ctx: _Ctx, loc: str, prod: str, lifts: dict[str, float],
                   pooled: dict[str, float], notes: list[str]) -> tuple[list[float], list[list[str]]]:
    factors = [1.0] * len(ctx.fut)
    ids: list[list[str]] = [[] for _ in ctx.fut]
    for e in ctx.ds.events:
        if not e.applies(loc, prod):
            continue
        lift = e.lift
        if lift is None:
            lift = lifts.get(e.kind.value, pooled.get(e.kind.value))
            if lift is None:
                notes.append(f"Event {e.id} has no lift and none was measured for {e.kind.value}: ignored.")
                continue
        for i, p in enumerate(ctx.fut):
            lo, hi = max(p.start, e.start), min(p.end, e.end + timedelta(days=1))
            days = (hi - lo).days
            if days > 0:
                factors[i] *= 1 + lift * days / p.days
                ids[i].append(e.id)
    return factors, ids


def _foundation_batches(ctx: _Ctx, hists: dict[tuple[str, str], _Hist], provider: fm.Provider | None,
                        competing: set[tuple[str, str]]) -> dict[tuple[str, str], dict[tuple[int, int], np.ndarray]]:
    """Run TimesFM once over every (series, origin) context, backtest and final, in two batches."""
    out: dict[tuple[str, str], dict[tuple[int, int], np.ndarray]] = defaultdict(dict)
    if provider is None or not competing:
        return out
    fs = ctx.ds.forecasting
    bt_ctx: list[tuple[tuple[str, str], int, int]] = []
    for k in competing:
        y = hists[k].cleaned
        starts, h_eff = origins(len(y), fs.backtest_origins, fs.backtest_horizon, ctx.m)
        bt_ctx += [(k, o, h_eff) for o in starts]
    for batch, horizon in ((bt_ctx, fs.backtest_horizon), ([(k, len(hists[k].cleaned), len(ctx.fut)) for k in competing],
                                                          len(ctx.fut))):
        if not batch or horizon < 1:
            continue
        preds = provider.forecast([hists[k].cleaned[:o] for k, o, _ in batch], horizon)
        for (k, o, h), p in zip(batch, preds, strict=True):
            out[k][(o, h)] = np.asarray(p[:h], dtype=float)
    return out


def run_forecast(ds: Dataset) -> ForecastResult:
    issues = validate(ds)
    fs = ds.forecasting
    period = fs.period
    m = fs.season_length or default_season(period)
    start = ds.settings.planning_start
    fut = future_periods(start, start + timedelta(days=ds.settings.horizon_days), period, ds.settings.week_start)
    ctx = _Ctx(ds, period, m, fut, NormalDist().inv_cdf(0.5 + fs.interval / 2))
    provider, status = fm.get() if ForecastModelId.TIMESFM in fs.models else (None, fm.Status(
        False, False, "", "", "Not selected in forecast settings."))
    foundation_status = FoundationStatus(**status.__dict__)
    if blocks_demand(issues):
        return ForecastResult(ok=False, period=period.value, season_length=m, periods=[p.label for p in fut],
                              issues=issues, series=[], summary=Summary(series=0), foundation=foundation_status)

    hists = _aggregate(ds, period, start)
    ev_kind = {e.id: e.kind.value for e in ds.events}
    ev_kind[HISTORY_PROMO] = "promo"
    for h in hists.values():
        _mark_events(ds, h, period)
        _cleanse(ds, h, ev_kind)
    pooled_sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for h in hists.values():
        for kind, (a, b) in h.lift_sums.items():
            pooled_sums[kind][0] += a
            pooled_sums[kind][1] += b
    pooled = {k: a / b - 1 for k, (a, b) in pooled_sums.items() if b > 0}
    abc = _abc(list(hists.values()), fs.abc_a, fs.abc_b)

    competing = {k for k, h in hists.items() if len(h.cleaned) >= fs.min_history_periods}
    fbatch = _foundation_batches(ctx, hists, provider, competing)

    jobs = {k: (hists[k].cleaned, len(fut), m, _candidates(ds, hists[k].pattern, k in fbatch), fs.backtest_origins,
                fs.backtest_horizon, fs.selection_metric, fbatch.get(k)) for k in sorted(competing)}
    outcomes = _compete_all(jobs)
    series: dict[tuple[str, str], Series] = {}
    for k, h in sorted(hists.items()):
        series[k] = _series_from_history(ctx, h, abc[k], pooled, outcomes.get(k))
    for rule in ds.npi:
        k = (rule.location, rule.product)
        if k in hists and len(hists[k].cleaned) >= fs.min_history_periods:
            series[k].notes.append("NPI rule ignored: the product has enough history for a statistical forecast.")
            continue
        series[k] = _npi_series(ctx, rule, series, pooled, hists.get(k))
    _apply_overrides(ds, series, fut)

    out = sorted(series.values(), key=lambda s: (s.location, s.product))
    return ForecastResult(ok=True, period=period.value, season_length=m, periods=[p.label for p in fut], issues=issues,
                          series=out, summary=_summary(out), foundation=foundation_status)


PARALLEL_MIN_SERIES = 24


def _compete_job(job: tuple) -> Outcome:
    y, horizon, m, candidates, k, h, metric, fpreds = job
    return compete(y, horizon, m, candidates, k=k, h=h, metric=metric, foundation=fpreds)


def _compete_all(jobs: dict[tuple[str, str], tuple]) -> dict[tuple[str, str], Outcome]:
    """Series are independent, so large portfolios compete in parallel processes."""
    workers = min(os.cpu_count() or 1, 8)
    if len(jobs) < PARALLEL_MIN_SERIES or workers < 2:
        return {k: _compete_job(j) for k, j in jobs.items()}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return dict(zip(jobs, pool.map(_compete_job, jobs.values(), chunksize=4), strict=True))


def _candidates(ds: Dataset, pattern: str, foundation_ok: bool) -> list[ForecastModelId]:
    out = []
    for mid in ds.forecasting.models:
        if mid is ForecastModelId.TIMESFM and not foundation_ok:
            continue
        if pattern in ("intermittent", "lumpy") and mid in SMOOTH_ONLY:
            continue
        if pattern in ("smooth", "erratic") and mid in INTERMITTENT_ONLY:
            continue
        out.append(mid)
    if ForecastModelId.NAIVE not in out:
        out.insert(0, ForecastModelId.NAIVE)  # always scored: it is the forecast-value-add yardstick
    return out


def _series_from_history(ctx: _Ctx, h: _Hist, abc: tuple[str, float], pooled: dict[str, float],
                         res: Outcome | None) -> Series:
    fs = ctx.ds.forecasting
    y = h.cleaned
    n_fut = len(ctx.fut)
    notes: list[str] = []
    leaderboard: list[ModelScore] = []
    champion = None
    champion_label = ""
    fva = None
    backtest: list[BacktestPoint] = []
    sigma1 = None
    if res is not None:
        champion = res.champion
        stat, sigma = res.forecast, res.sigma
        ranked = sorted([s for s in res.scores if s.eligible],
                        key=lambda s: (round(s.metric(fs.selection_metric), 9), SPECS[s.model].complexity))
        rank = {s.model: i + 1 for i, s in enumerate(ranked)}
        for sc in sorted(res.scores, key=lambda s: (rank.get(s.model, 999), SPECS[s.model].complexity)):
            spec = SPECS[sc.model]
            leaderboard.append(ModelScore(model=sc.model, label=spec.label, family=spec.family, eligible=sc.eligible,
                                          reason=sc.reason, mae=sc.mae, rmse=sc.rmse, mase=sc.mase, wape=sc.wape,
                                          bias=sc.bias, rank=rank.get(sc.model)))
        if champion is not None:
            champion_label = SPECS[champion].label
            cs = next(s for s in res.scores if s.model is champion)
            backtest = [BacktestPoint(origin=o, step=st, start=h.starts[o + st - 1], actual=a, forecast=f)
                        for o, st, a, f in cs.backtest]
            sigma1 = cs.step_rmse[0] if cs.step_rmse else None
            if res.naive_wape is not None and cs.wape is not None:
                fva = res.naive_wape - cs.wape
        else:
            notes.append("No model could be backtested; the forecast is the history average.")
    else:
        stat = np.full(n_fut, float(y.mean()))
        sd = float(y.std()) if len(y) > 1 else float(y.mean()) * 0.5
        sigma = np.full(n_fut, sd)
        champion_label = f"Average of {len(y)} periods"
        notes.append(f"Only {len(y)} periods of history (< {fs.min_history_periods}): no competition; "
                     "the forecast is the average. Add history or an NPI rule.")

    mean_level = float(y[-min(len(y), ctx.m):].mean()) if len(y) else 0.0
    error_cv = (sigma1 / mean_level) if (sigma1 is not None and mean_level > 0) else (
        float(y.std() / y.mean()) if len(y) > 1 and y.mean() > 0 else None)
    xyz = _xyz(error_cv, fs.xyz_x, fs.xyz_y)
    recent = y[-min(len(y), 8):]
    lifecycle = "new" if len(y) < fs.min_history_periods else "inactive" if recent.sum() == 0 else "mature"
    weekly_cv = None
    if error_cv is not None:
        weekly_cv = error_cv * float(np.sqrt(mean_days(ctx.period) / 7))
    factors, ev_ids = _event_factors(ctx, h.location, h.product, h.lifts, pooled, notes)
    segment = Segment(abc=abc[0], xyz=xyz, pattern=h.pattern, lifecycle=lifecycle, revenue=h.revenue,
                      revenue_share=abc[1], adi=h.adi, cv2=h.cv2, error_cv=error_cv,
                      suggested_service_level=SERVICE_LEVEL[(abc[0], xyz)])
    history = [HistoryPoint(start=s, label=label(s, ctx.period), raw=float(h.raw[i]), cleaned=float(y[i]),
                            flag=h.flags[i], events=h.events[i]) for i, s in enumerate(h.starts)]
    return Series(key=key_of(h.location, h.product), location=h.location, product=h.product, segment=segment,
                  history=history, leaderboard=leaderboard, champion=champion, champion_label=champion_label,
                  fva=fva, backtest=backtest, forecast=_points(ctx, stat, sigma, factors, ev_ids),
                  lifts=h.lifts, sigma_one_step=sigma1, demand_cv_weekly=weekly_cv, notes=notes)


def _points(ctx: _Ctx, stat: np.ndarray, sigma: np.ndarray, factors: list[float],
            ev_ids: list[list[str]]) -> list[ForecastPoint]:
    out = []
    for i, p in enumerate(ctx.fut):
        base = float(stat[i]) * factors[i]
        out.append(ForecastPoint(start=p.start, end=p.end, label=p.label, share=p.share, statistical=float(stat[i]),
                                 event_factor=factors[i], events=ev_ids[i], final=base,
                                 lower=max(0.0, base - ctx.z * float(sigma[i])), upper=base + ctx.z * float(sigma[i]),
                                 released_qty=base * p.share))
    return out


def _npi_series(ctx: _Ctx, rule: NpiRule, series: dict[tuple[str, str], Series], pooled: dict[str, float],
                hist: _Hist | None) -> Series:
    like_key = (rule.like_location or rule.location, rule.like_product)
    like = series.get(like_key)
    notes: list[str] = []
    stat = np.zeros(len(ctx.fut))
    spread = np.zeros(len(ctx.fut))
    if like is None:
        notes.append(f"Like series {like_key[1]} at {like_key[0]} has no history: the NPI forecast is zero.")
    else:
        launch_idx = None
        for i, p in enumerate(ctx.fut):
            if p.end <= rule.launch_date:
                continue
            if launch_idx is None:
                launch_idx = i
            j = i - launch_idx
            ramp = min(1.0, (j + 1) / rule.ramp_periods) if rule.ramp_periods > 0 else 1.0
            live = (p.end - max(p.start, rule.launch_date)).days / p.days
            stat[i] = like.forecast[i].statistical * rule.scale * ramp * live
            spread[i] = (like.forecast[i].upper - like.forecast[i].final) * rule.scale / max(ctx.z, 1e-9)
        # cannibalisation: the like product loses part of what the new one sells
        if rule.cannibalisation > 0 and like_key[0] == rule.location:
            for i, pt in enumerate(like.forecast):
                take = rule.cannibalisation * stat[i]
                if take > 0:
                    pt.cannibalised += take
                    pt.final = max(0.0, pt.final - take)
                    pt.lower = max(0.0, pt.lower - take)
                    pt.upper = max(0.0, pt.upper - take)
                    pt.released_qty = pt.final * pt.share
    lifts = hist.lifts if hist else {}
    factors, ev_ids = _event_factors(ctx, rule.location, rule.product, lifts, pooled, notes)
    y = hist.cleaned if hist else np.zeros(0)
    seg = Segment(abc="C", xyz="Z", pattern="none", lifecycle="npi", revenue=hist.revenue if hist else 0.0,
                  revenue_share=0.0, suggested_service_level=SERVICE_LEVEL[("C", "Z")])
    history = [HistoryPoint(start=s, label=label(s, ctx.period), raw=float(hist.raw[i]), cleaned=float(y[i]),
                            flag=hist.flags[i], events=hist.events[i]) for i, s in enumerate(hist.starts)] if hist else []
    return Series(key=key_of(rule.location, rule.product), location=rule.location, product=rule.product, segment=seg,
                  history=history, leaderboard=[], champion=None,
                  champion_label=f"NPI: {rule.scale:.0%} of {rule.like_product}, launch {rule.launch_date.isoformat()}",
                  forecast=_points(ctx, stat, spread, factors, ev_ids), notes=notes)


def _apply_overrides(ds: Dataset, series: dict[tuple[str, str], Series], fut: list[Period]) -> None:
    for ov in ds.overrides:
        s = series.get((ov.location, ov.product))
        if s is None:
            continue  # reported by the readiness gate (OVERRIDE_NO_SERIES)
        for pt in s.forecast:
            if pt.start <= ov.date < pt.end:
                base = pt.statistical * pt.event_factor - pt.cannibalised
                pt.override = ov.qty if ov.qty is not None else max(0.0, base * (1 + (ov.change or 0.0)))
                pt.override_reason = ov.reason
                if pt.final > 0:  # keep the interval's relative width around the new value
                    ratio = pt.override / pt.final
                    pt.lower, pt.upper = pt.lower * ratio, pt.upper * ratio
                else:
                    pt.lower = pt.upper = pt.override
                pt.final = pt.override
                pt.released_qty = pt.final * pt.share
                break


def _summary(series: list[Series]) -> Summary:
    abs_err = act = bias = naive_err = 0.0
    champions: dict[str, int] = defaultdict(int)
    abc: dict[str, int] = defaultdict(int)
    patterns: dict[str, int] = defaultdict(int)
    for s in series:
        champions[s.champion.value if s.champion else ("npi" if s.segment.lifecycle == "npi" else "average")] += 1
        abc[s.segment.abc] += 1
        patterns[s.segment.pattern] += 1
        if s.backtest:
            a = sum(b.actual for b in s.backtest)
            abs_err += sum(abs(b.forecast - b.actual) for b in s.backtest)
            bias += sum(b.forecast - b.actual for b in s.backtest)
            act += a
            naive = next((sc for sc in s.leaderboard if sc.model is ForecastModelId.NAIVE and sc.wape is not None), None)
            if naive is not None:
                naive_err += naive.wape * a
    return Summary(series=len(series), wape=abs_err / act if act else None, bias=bias / act if act else None,
                   fva=(naive_err - abs_err) / act if act else None, champions=dict(champions), abc=dict(abc),
                   patterns=dict(patterns), total_final=sum(p.released_qty for s in series for p in s.forecast))


# ---- release --------------------------------------------------------------------------------------
def release(ds: Dataset, result: ForecastResult, keys: list[str] | None = None) -> tuple[Dataset, ReleaseResult]:
    """Write the consensus forecast into the dataset as forecast demand (≈ PIRs), replacing the
    forecast records of the released series. Sales orders are never touched."""
    chosen = [s for s in result.series if keys is None or s.key in keys]
    released = {(s.location, s.product) for s in chosen}
    kept = [d for d in ds.demand if not (d.kind is DemandKind.FORECAST and (d.location, d.product) in released)]
    replaced = len(ds.demand) - len(kept)
    new: list[DemandRecord] = []
    for s in chosen:
        for p in s.forecast:
            qty = round(p.released_qty, 3)
            if qty <= 0:
                continue
            frm = max(p.start, ds.settings.planning_start)
            days = max(1, round(p.share * (p.end - p.start).days))
            new.append(DemandRecord(location=s.location, product=s.product, date=frm, qty=qty,
                                    kind=DemandKind.FORECAST, period_days=days))
    out = ds.model_copy(update={"demand": kept + new})
    cv: list[CvSuggestion] = []
    for s in chosen:
        lp = ds.location_product_by_key.get((s.location, s.product))
        if lp is not None and s.demand_cv_weekly is not None:
            cv.append(CvSuggestion(location=s.location, product=s.product, current=lp.safety_stock.demand_cv,
                                   suggested=round(s.demand_cv_weekly, 4)))
    return Dataset.model_validate(out.model_dump()), ReleaseResult(records=len(new), series=len(chosen),
                                                                  replaced=replaced, cv_suggestions=cv)
