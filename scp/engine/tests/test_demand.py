"""Demand planning: models on series with known answers, metrics computed by hand, and the pipeline
(cleansing, segmentation, events, NPI, overrides, release, foundation-model integration)."""
import math
from datetime import date, timedelta

import numpy as np
import pytest

from scp.demand import foundation, release, run_forecast
from scp.demand.competition import compete, mase_scale, origins
from scp.demand.models import (
    INTERMITTENT_ALPHA, Infeasible, croston, holt_damped, holt_winters, moving_average, naive, regression, sba,
    seasonal_naive, ses, tsb,
)
from scp.demand.periods import future_periods, history_periods, period_start
from scp.model import DemandKind, ForecastModelId as M, ForecastPeriod, SelectionMetric
from scp.plan import run_mrp

from .factory import base, ds, load_example


# ---- periods --------------------------------------------------------------------------------------
def test_week_and_month_alignment():
    assert period_start(date(2026, 1, 8), ForecastPeriod.WEEK, 0) == date(2026, 1, 5)
    assert period_start(date(2026, 1, 8), ForecastPeriod.WEEK, 6) == date(2026, 1, 4)
    assert period_start(date(2026, 1, 31), ForecastPeriod.MONTH, 0) == date(2026, 1, 1)


def test_partial_first_and_last_period():
    ps = future_periods(date(2026, 1, 7), date(2026, 1, 21), ForecastPeriod.WEEK, 0)
    assert [p.start for p in ps] == [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)]
    assert [round(p.share, 4) for p in ps] == [round(5 / 7, 4), 1.0, round(2 / 7, 4)]
    months = future_periods(date(2026, 1, 16), date(2026, 3, 1), ForecastPeriod.MONTH, 0)
    assert [p.label for p in months] == ["Jan 2026", "Feb 2026"]
    assert months[0].share == 16 / 31 and months[1].share == 1.0


def test_history_periods_stop_before_end():
    assert history_periods(date(2025, 12, 17), date(2026, 1, 5), ForecastPeriod.WEEK, 0) == [
        date(2025, 12, 15), date(2025, 12, 22), date(2025, 12, 29)]


# ---- models: known answers ---------------------------------------------------------------------
CONST = np.full(30, 10.0)


@pytest.mark.parametrize("fn", [naive, moving_average, ses, holt_damped, regression])
def test_constant_series_forecasts_the_constant(fn):
    assert np.allclose(fn(CONST, 5, 4), 10.0, atol=1e-6)


def test_seasonal_models_on_a_pure_season():
    y = np.tile([10.0, 20.0, 30.0, 40.0], 6)
    assert list(seasonal_naive(y, 6, 4)) == [10, 20, 30, 40, 10, 20]
    assert np.allclose(holt_winters(y, 4, 4), [10, 20, 30, 40], atol=0.5)


def test_regression_recovers_a_line():
    y = 5 + 2 * np.arange(20.0)
    assert np.allclose(regression(y, 3, 52), [45, 47, 49])


def test_holt_damped_trend_flattens():
    y = 5 + 2 * np.arange(30.0)
    f = holt_damped(y, 30, 52)
    steps = np.diff(f)
    assert f[0] > y[-1] and np.all(steps > 0) and steps[-1] < steps[0]


def test_croston_family_by_hand():
    y = np.array([0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5], dtype=float)
    assert croston(y, 2, 52) == pytest.approx([5 / 3, 5 / 3])
    assert sba(y, 1, 52)[0] == pytest.approx((1 - INTERMITTENT_ALPHA / 2) * 5 / 3)
    t = tsb(y, 1, 52)[0]
    assert 0 < t < 5
    with pytest.raises(Infeasible):
        croston(np.array([0, 0, 3, 0.0]), 1, 52)


def test_forecasts_never_negative():
    y = np.array([50, 40, 30, 20, 10, 5, 2, 1.0])
    for fn in (naive, holt_damped, regression, ses):
        assert (fn(y, 20, 52) >= 0).all()


def test_short_history_is_infeasible_not_wrong():
    with pytest.raises(Infeasible):
        seasonal_naive(np.ones(3), 2, 4)
    with pytest.raises(Infeasible):
        holt_winters(np.ones(10), 2, 4)


# ---- metrics and the competition --------------------------------------------------------------
def test_backtest_origins():
    assert origins(6, 2, 1) == ([4, 5], 1)
    assert origins(30, 6, 4) == ([21, 22, 23, 24, 25, 26], 4)       # no season: consecutive
    assert origins(104, 6, 4, 52) == ([60, 68, 76, 84, 92, 100], 4)  # spread over the last season
    assert origins(30, 6, 4, 52) == ([11, 14, 17, 20, 23, 26], 4)   # as far as the history allows
    assert origins(6, 6, 4) == ([4], 2)  # short history shortens the horizon, never below one period
    assert origins(2, 3, 1) == ([], 0)


def test_metrics_by_hand():
    y = np.array([1, 2, 3, 4, 5, 6.0])
    out = compete(y, 2, 52, [M.NAIVE], k=2, h=1, metric=SelectionMetric.MASE)
    s = out.scores[0]
    # origins 4, 5: naive forecasts 4 then 5 against actuals 5, 6 → errors −1, −1
    assert (s.mae, s.rmse, s.mase) == (1.0, 1.0, 1.0)
    assert s.wape == pytest.approx(2 / 11) and s.bias == pytest.approx(-2 / 11)
    assert mase_scale(y) == 1.0


def test_champion_is_the_exact_model_and_ties_go_to_the_simpler_one():
    line = 5 + 2 * np.arange(40.0)
    out = compete(line, 4, 52, [M.NAIVE, M.SES, M.HOLT_DAMPED, M.REGRESSION], k=4, h=3, metric=SelectionMetric.MASE)
    assert out.champion is M.REGRESSION
    season = np.tile([10.0, 20.0, 30.0, 40.0], 8)
    out = compete(season, 4, 4, [M.NAIVE, M.SEASONAL_NAIVE, M.HOLT_WINTERS, M.REGRESSION], k=4, h=4,
                  metric=SelectionMetric.WAPE)
    assert out.champion is M.SEASONAL_NAIVE  # exact; HW/regression may also be ~exact but are more complex
    out = compete(CONST, 3, 52, [M.NAIVE, M.SES, M.MOVING_AVERAGE], k=3, h=2, metric=SelectionMetric.RMSE)
    assert out.champion is M.NAIVE


def test_combination_is_the_mean_of_its_members():
    rng = np.random.default_rng(3)
    y = 100 + rng.normal(0, 5, 40)
    out = compete(y, 3, 52, [M.SES, M.HOLT_DAMPED, M.COMBINATION], k=2, h=2, metric=SelectionMetric.MASE)
    sc = {s.model: s for s in out.scores}
    assert sc[M.COMBINATION].eligible
    comb = [f for (_, _, _, f) in sc[M.COMBINATION].backtest]
    members = np.mean([[f for (_, _, _, f) in sc[m].backtest] for m in (M.SES, M.HOLT_DAMPED)], axis=0)
    assert np.allclose(comb, members)


def test_interval_grows_beyond_the_backtest_horizon():
    rng = np.random.default_rng(7)
    y = 50 + rng.normal(0, 4, 60)
    out = compete(y, 12, 52, [M.NAIVE, M.SES], k=6, h=4, metric=SelectionMetric.MASE)
    assert out.sigma[5] == pytest.approx(out.sigma[3] * math.sqrt(6 / 4))


# ---- pipeline -----------------------------------------------------------------------------------
START = date(2026, 1, 5)


def weekly(loc, prod, values, *, start=START - timedelta(weeks=0), promo=()):
    first = start - timedelta(weeks=len(values))
    return [{"location": loc, "product": prod, "date": (first + timedelta(weeks=i)).isoformat(), "qty": v,
             "promo": i in promo} for i, v in enumerate(values)]


def dataset(history, **extra):
    d = base(horizon=56)
    d["products"][0]["price"] = 100
    d["history"] = history
    d.update(extra)
    return d


def smooth(n=60, level=100.0, seed=1):
    rng = np.random.default_rng(seed)
    return [round(float(level * (1 + rng.normal(0, 0.05))), 1) for _ in range(n)]


def test_forecast_runs_and_releases_as_pirs():
    d = dataset(weekly("P", "A", smooth()))
    d["demand"] = [{"location": "P", "product": "A", "date": "2026-01-12", "qty": 999, "kind": "forecast"},
                   {"location": "P", "product": "A", "date": "2026-01-14", "qty": 7, "kind": "sales_order"}]
    r = run_forecast(ds(d))
    assert r.ok and len(r.series) == 1 and len(r.periods) == 8
    s = r.series[0]
    assert s.champion is not None and s.leaderboard[0].rank == 1
    assert all(abs(p.final - 100) < 20 for p in s.forecast)
    new, info = release(ds(d), r)
    fc = [x for x in new.demand if x.kind is DemandKind.FORECAST]
    so = [x for x in new.demand if x.kind is DemandKind.SALES_ORDER]
    assert info.replaced == 1 and info.records == 8 and len(so) == 1 and all(x.period_days == 7 for x in fc)
    assert sum(x.qty for x in fc) == pytest.approx(sum(p.released_qty for p in s.forecast), abs=0.01)
    assert run_mrp(new).ok  # the released forecast plans


def test_history_promos_are_cleansed_and_their_lift_measured():
    vals = [100.0] * 40
    vals[20] = vals[21] = 150.0
    d = dataset(weekly("P", "A", vals, promo=(20, 21)))
    s = run_forecast(ds(d)).series[0]
    flagged = [h for h in s.history if h.flag == "event"]
    assert len(flagged) == 2 and all(h.cleaned == 100 for h in flagged)
    assert s.lifts["promo"] == pytest.approx(0.5)
    assert all(p.statistical == pytest.approx(100) for p in s.forecast)


def test_future_event_uses_given_or_measured_lift_prorated_by_days():
    vals = [100.0] * 40
    vals[10] = 130.0
    d = dataset(weekly("P", "A", vals, promo=(10,)))
    d["events"] = [
        {"id": "E-GIVEN", "kind": "promo", "start": "2026-01-12", "end": "2026-01-18", "lift": 0.2},
        {"id": "E-MEASURED", "kind": "promo", "products": ["A"], "start": "2026-01-19", "end": "2026-01-25"},
        {"id": "E-HALF", "kind": "price_change", "start": "2026-01-29", "end": "2026-02-01", "lift": -0.35},
        {"id": "E-UNKNOWN", "kind": "competitor", "start": "2026-02-09", "end": "2026-02-15"},
    ]
    s = run_forecast(ds(d)).series[0]
    f = {p.start.isoformat(): p for p in s.forecast}
    assert f["2026-01-12"].event_factor == pytest.approx(1.2)
    assert f["2026-01-19"].event_factor == pytest.approx(1.3)
    assert f["2026-01-26"].event_factor == pytest.approx(1 - 0.35 * 4 / 7)
    assert f["2026-02-09"].event_factor == 1.0 and any("E-UNKNOWN" in n for n in s.notes)


def test_outliers_are_clipped_but_intermittent_series_are_not_touched():
    vals = smooth(50)
    vals[30] = 900.0
    d = dataset(weekly("P", "A", vals) + weekly("P", "B", [0, 0, 6, 0, 0, 0, 9, 0, 0, 4] * 4))
    r = run_forecast(ds(d))
    a = next(s for s in r.series if s.product == "A")
    b = next(s for s in r.series if s.product == "B")
    assert [h.flag for h in a.history].count("outlier") >= 1 and max(h.cleaned for h in a.history) < 200
    assert b.segment.pattern in ("intermittent", "lumpy") and not any(h.flag for h in b.history)
    assert b.champion in (M.CROSTON, M.SBA, M.TSB, M.SES, M.NAIVE, M.MOVING_AVERAGE)
    assert all(sc.model not in (M.HOLT_WINTERS, M.REGRESSION) for sc in b.leaderboard)


def test_segmentation():
    d = dataset(weekly("P", "A", smooth(52, 100)) + weekly("P", "B", smooth(52, 10, seed=2))
                + weekly("P", "C", [30, 0, 0, 0] * 13))
    d["products"][1]["price"] = 100
    d["products"][2]["price"] = 100
    r = run_forecast(ds(d))
    seg = {s.product: s.segment for s in r.series}
    assert seg["A"].abc == "A" and seg["C"].abc in ("B", "C")
    assert seg["A"].pattern == "smooth" and seg["C"].pattern == "intermittent" and seg["C"].adi == 4
    assert seg["A"].xyz == "X" and seg["A"].suggested_service_level == 0.98


def test_short_history_uses_the_average():
    d = dataset(weekly("P", "A", [10, 20, 30]))
    s = run_forecast(ds(d)).series[0]
    assert s.champion is None and s.segment.lifecycle == "new"
    assert all(p.statistical == 20 for p in s.forecast)


def test_npi_ramp_and_cannibalisation():
    d = dataset(weekly("P", "A", [100.0] * 30))
    d["npi"] = [{"location": "P", "product": "C", "like_product": "A", "scale": 0.5, "launch_date": "2026-01-12",
                 "ramp_periods": 2, "cannibalisation": 0.4}]
    r = run_forecast(ds(d))
    new = next(s for s in r.series if s.product == "C")
    like = next(s for s in r.series if s.product == "A")
    assert new.segment.lifecycle == "npi"
    assert [round(p.final, 6) for p in new.forecast[:4]] == [0, 25, 50, 50]
    assert [round(p.final, 6) for p in like.forecast[:4]] == [100, 90, 80, 80]


def test_overrides_absolute_and_relative():
    d = dataset(weekly("P", "A", [100.0] * 30))
    d["overrides"] = [{"location": "P", "product": "A", "date": "2026-01-14", "qty": 250, "reason": "tender"},
                      {"location": "P", "product": "A", "date": "2026-01-20", "change": -0.1}]
    f = run_forecast(ds(d)).series[0].forecast
    assert f[1].final == 250 and f[1].override_reason == "tender"
    assert f[2].final == pytest.approx(90) and f[0].override is None


def test_release_of_a_partial_first_period():
    d = dataset(weekly("P", "A", [70.0] * 30))
    d["settings"]["planning_start"] = "2026-01-07"  # Wednesday
    r = run_forecast(ds(d))
    new, _ = release(ds(d), r)
    first = min((x for x in new.demand if x.kind is DemandKind.FORECAST), key=lambda x: x.date)
    assert first.date == date(2026, 1, 7) and first.period_days == 5 and first.qty == pytest.approx(50)


def test_monthly_forecast_and_cv_conversion():
    d = dataset([{"location": "P", "product": "A", "date": f"{2024 + (i // 12)}-{i % 12 + 1:02d}-10",
                  "qty": 400 + 20 * ((-1) ** i)} for i in range(24)])
    d["forecasting"] = {"period": "month"}
    d["settings"]["horizon_days"] = 90
    d["location_products"][0]["safety_stock"] = {"method": "service_level", "demand_cv": 0.9}
    r = run_forecast(ds(d))
    s = r.series[0]
    assert r.period == "month" and s.forecast[0].label == "Jan 2026"
    assert s.demand_cv_weekly == pytest.approx(s.segment.error_cv * math.sqrt((365.25 / 12) / 7))
    _, info = release(ds(d), r)
    assert info.cv_suggestions[0].current == 0.9


def test_gate_errors_block_the_forecast():
    d = dataset(weekly("P", "ZZZ", [1.0] * 10))
    r = run_forecast(ds(d))
    assert not r.ok and any(i.code == "REF_UNKNOWN" for i in r.issues)


def test_example_forecasts():
    r = run_forecast(load_example("kitchenware_network"))
    assert r.ok and r.series and r.summary.wape is not None and r.summary.wape < 0.35
    assert all(s.champion is not None for s in r.series if s.segment.lifecycle == "mature")


# ---- foundation model ---------------------------------------------------------------------------
class Oracle:
    """Stands in for TimesFM: knows the true continuation of a noiseless sine series."""

    name, license = "oracle", "test"

    def __init__(self, truth):
        self.truth, self.calls = truth, 0

    def forecast(self, contexts, horizon):
        self.calls += 1
        return [self.truth[len(c):len(c) + horizon] for c in contexts]


@pytest.fixture
def oracle():
    t = np.arange(200)
    truth = 100 + 30 * np.sin(2 * np.pi * t / 13) + 10 * np.sin(2 * np.pi * t / 7)
    o = Oracle(truth)
    foundation.set_provider(o)
    yield o
    foundation.set_provider(None)


def test_foundation_model_competes_and_wins_when_it_is_better(oracle):
    vals = [round(float(v), 6) for v in oracle.truth[:60]]
    d = dataset(weekly("P", "A", vals), forecasting={"models": ["naive", "ses", "holt_damped", "timesfm"]})
    r = run_forecast(ds(d))
    s = r.series[0]
    assert r.foundation.available and s.champion is M.TIMESFM
    assert oracle.calls == 2  # one batch for all backtest origins, one for the future
    assert [round(p.statistical, 6) for p in s.forecast] == [round(float(v), 6) for v in oracle.truth[60:68]]


def test_foundation_model_is_skipped_when_not_selected(oracle):
    d = dataset(weekly("P", "A", smooth()))
    r = run_forecast(ds(d))
    assert oracle.calls == 0 and not r.foundation.enabled
    assert all(sc.model is not M.TIMESFM for sc in r.series[0].leaderboard)


def test_foundation_disabled_by_default_and_noncommercial_refused(monkeypatch):
    foundation.set_provider(None)
    monkeypatch.delenv("SCP_TIMESFM", raising=False)
    _, st = foundation.get()
    assert not st.enabled and not st.available
    foundation.set_provider(None)
    monkeypatch.setenv("SCP_TIMESFM", "1")
    monkeypatch.setenv("SCP_TIMESFM_CHECKPOINT", "google/timesfm-3.0-pytorch")
    _, st = foundation.get()
    assert st.enabled and not st.available and st.license == "non-commercial"
    foundation.set_provider(None)
    d = dataset(weekly("P", "A", smooth()), forecasting={"models": ["naive", "timesfm"]})
    s = run_forecast(ds(d)).series[0]
    assert s.champion is M.NAIVE
    assert all(sc.model is not M.TIMESFM for sc in s.leaderboard)
    foundation.set_provider(None)
