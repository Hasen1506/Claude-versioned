"""
V4-4 — exogenous regressor columns in the forecast engine (price → Q16).

Contract (forecast.py):
  · products[].exog = {name: [values aligned with history]} — each column rides
    into the ML/hybrid feature matrix as one raw feature; classical models never
    see it (inherent — the leaderboard routes price-driven SKUs to ML);
  · holdout backtests feed the ACTUAL historical exog values over the test
    window (they are history — no peeking at the target);
  · future values come from products[].exog_future[name], else the last known
    value is carried forward;
  · result surfaces exog_features (the columns that rode in), None when none.

The synthetic series is PRICE-DRIVEN by construction: demand = 300 − 10·price,
price flips between 10 and 20 in 6-period blocks → demand flips 200/100. Lags
alone always trail the flip by a period; the price column explains it exactly.
"""
from forecast import run_forecast

N = 36
PRICE = [10 if (t // 6) % 2 == 0 else 20 for t in range(N)]
DEMAND = [300 - 10 * p for p in PRICE]          # 200 / 100 blocks, no noise


def _payload(exog=None, exog_future=None, models=('random_forest',)):
    prod = {'name': 'PRICED', 'history': list(DEMAND)}
    if exog is not None:
        prod['exog'] = exog
    if exog_future is not None:
        prod['exog_future'] = exog_future
    return {
        'products': [prod],
        'params': {'h_periods': 6, 'time_grain': 'monthly',
                   'horizon_start_date': '2023-01-01', 'models': list(models)},
    }


def _rf_row(res):
    p = res['products'][0]
    return p, next(r for r in p['leaderboard'] if r['model'] == 'random_forest')


def test_exog_features_surface_in_result():
    with_p, _ = _rf_row(run_forecast(_payload(exog={'price': PRICE})))
    without, _ = _rf_row(run_forecast(_payload()))
    assert with_p['exog_features'] == ['price']
    assert without['exog_features'] is None


def test_price_column_improves_holdout_mape():
    # holdout = last 6 periods = a price-20/demand-100 block entered straight from a
    # 200-block; lags trail the flip, the price feature explains it.
    _, base = _rf_row(run_forecast(_payload()))
    _, priced = _rf_row(run_forecast(_payload(exog={'price': PRICE})))
    assert priced['mape'] < base['mape'], (priced['mape'], base['mape'])


def test_future_price_scenario_moves_the_forecast():
    # SAME trained model, two planned futures: keep price 20 vs cut to 10.
    hi = run_forecast(_payload(exog={'price': PRICE}, exog_future={'price': [20] * 6}))
    lo = run_forecast(_payload(exog={'price': PRICE}, exog_future={'price': [10] * 6}))
    _, hi_rf = _rf_row(hi)
    _, lo_rf = _rf_row(lo)
    f_hi = sum(hi_rf['forecast']) / len(hi_rf['forecast'])
    f_lo = sum(lo_rf['forecast']) / len(lo_rf['forecast'])
    # price cut → demand up, and the gap should be a real chunk of the 100-unit swing
    assert f_lo > f_hi + 30, (f_lo, f_hi)


def test_short_and_junk_columns_degrade_gracefully():
    r = run_forecast(_payload(exog={'price': PRICE[:10],          # short → pad last known
                                    'notes': ['a', 'b'],          # non-numeric → dropped
                                    'empty': []}))                # empty → dropped
    p, rf = _rf_row(r)
    assert p['exog_features'] == ['price']
    assert len(rf['forecast']) == 6
