"""
GAP-7 · Forecasting — intermittent methods, scale-free + bias metrics, reconciliation.

Covers Croston/SBA/TSB, the Syntetos–Boylan classification, MASE/bias/tracking-signal,
and the bottom-up hierarchical reconciliation.
"""
import math
from forecast import (run_forecast, _intermittence, _croston, _sba, _tsb,
                      _mase, _bias, _tracking_signal)

SPIKY = [0, 0, 5, 0, 0, 8, 0, 0, 0, 6, 0, 4, 0, 0, 7, 0, 0, 5, 0, 3, 0, 0, 6, 0]
STEADY = [100, 110, 95, 105, 100, 108, 98, 112, 101, 107, 99, 103] * 2


def test_intermittence_classifies_spiky_series():
    adi, cv2, label = _intermittence(SPIKY)
    assert adi > 1.32
    assert label in ('intermittent', 'lumpy')


def test_intermittence_classifies_steady_series_smooth():
    adi, cv2, label = _intermittence(STEADY)
    assert label == 'smooth'


def test_croston_sba_tsb_produce_positive_flat_rate():
    for fn in (_croston, _sba, _tsb):
        fcst, fitted = fn(SPIKY, 3)
        assert len(fcst) == 3
        assert all(v >= 0 for v in fcst)
        assert len(set(round(v, 6) for v in fcst)) == 1   # flat rate


def test_sba_is_bias_corrected_below_croston():
    # SBA multiplies Croston's rate by (1 − α/2) < 1.
    c = _croston(SPIKY, 1)[0][0]
    s = _sba(SPIKY, 1)[0][0]
    assert s < c


def test_mase_finite_on_zero_heavy_series():
    # MAPE would be inf (zeros); MASE must stay finite.
    train, test = SPIKY[:-4], SPIKY[-4:]
    pred = _croston(train, 4)[0]
    m = _mase(test, pred, train, season=1)
    assert math.isfinite(m)


def test_bias_and_tracking_signal_detect_over_forecast():
    actual = [10, 10, 10, 10]
    over = [13, 13, 13, 13]      # persistent +3 over-forecast
    assert _bias(actual, over) > 0
    assert abs(_tracking_signal(actual, over)) > 3   # all errors same sign ⇒ |TS| large


def test_run_forecast_ranks_intermittent_by_mase_and_picks_intermittent_model():
    r = run_forecast({'products': [{'name': 'Spiky', 'history': SPIKY}],
                      'params': {'h_periods': 3, 'time_grain': 'monthly',
                                 'season_length': 12, 'holdout_periods': 4}})
    op = r['products'][0]
    assert op['intermittence']['is_intermittent'] is True
    assert op['intermittence']['ranked_by'] == 'mase'
    assert op['winner'] in ('croston', 'sba', 'tsb')
    # every ok row now carries the new metrics
    ok = [row for row in op['leaderboard'] if row['status'] == 'ok']
    assert ok and all('bias' in row and 'tracking_signal' in row for row in ok)


def test_bottom_up_reconciliation_sums_winners():
    r = run_forecast({'products': [{'name': 'A', 'history': STEADY},
                                   {'name': 'B', 'history': STEADY}],
                      'params': {'h_periods': 3, 'time_grain': 'monthly', 'holdout_periods': 4}})
    rec = r['reconciliation']
    assert rec and rec['method'] == 'bottom_up'
    assert rec['n_series'] == 2
    # total per period = sum of the two SKU winner forecasts
    a = next(w for w in (next(p for p in r['products'] if p['name'] == 'A')['leaderboard']) if w['status'] == 'ok')
    b = next(w for w in (next(p for p in r['products'] if p['name'] == 'B')['leaderboard']) if w['status'] == 'ok')
    expected0 = round(a['forecast'][0] + b['forecast'][0], 2)
    assert abs(rec['total_forecast'][0] - expected0) < 0.05
