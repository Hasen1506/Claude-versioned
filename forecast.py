"""
Demand Forecasting Engine — v3.6 (P3)
======================================
Multi-model forecasting service. Runs classical, ML, hybrid, and DL approaches
and returns a leaderboard ranked by holdout MAPE so the UI can pick the winner.

Models:
- Naive Seasonal (baseline reference)
- Holt-Winters Exponential Smoothing (additive / multiplicative)
- ARIMA (auto-selected via AIC over a small grid)
- RandomForest (sklearn, with engineered features)
- GradientBoosting (sklearn)
- XGBoost (if installed)
- MLPRegressor (sklearn neural net — "DL" tier without TF/PyTorch overhead)
- Hybrid: Holt-Winters baseline + ML residual correction

Features (engineered when ML/DL/Hybrid):
- Lag values (lag-1, lag-7, lag-30 if data length permits)
- Rolling mean (window 3, 7)
- Day-of-week, month, quarter
- Promotion flag (from promo_periods passed in payload)
- Holiday flag (from holidays list passed in payload)

Graceful degradation: every model is wrapped in a try/except — if its dependency
is unavailable the model is skipped (with a note in the leaderboard) instead of
breaking the whole forecast.
"""
import math
import time
import warnings
from datetime import date, timedelta

import numpy as np

warnings.filterwarnings('ignore')

# ─── Optional dependencies — degrade gracefully when missing ───
HAS_SKLEARN = False
HAS_STATSMODELS = False
HAS_XGBOOST = False

try:
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    pass

try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    from statsmodels.tsa.arima.model import ARIMA
    HAS_STATSMODELS = True
except ImportError:
    pass

try:
    from xgboost import XGBRegressor
    HAS_XGBOOST = True
except ImportError:
    pass


# ─── Helpers ───
def _mape(actual, pred):
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = actual != 0
    if mask.sum() == 0:
        return float('inf')
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def _rmse(actual, pred):
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


def _mae(actual, pred):
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(pred))))


def _safe_period_grain(grain):
    return {'daily': 1, 'weekly': 7, 'monthly': 30}.get(grain, 7)


def _date_axis(start_iso, n_periods, grain):
    """Build n_periods consecutive dates starting from start_iso at the given grain."""
    if not start_iso:
        start = date.today()
    else:
        try:
            start = date.fromisoformat(start_iso)
        except ValueError:
            start = date.today()
    days = _safe_period_grain(grain)
    return [start + timedelta(days=i * days) for i in range(n_periods)]


def _build_features(history, dates, promo_periods, holidays_set):
    """Build a DataFrame-like 2D feature matrix for ML/DL models.

    Returns (X, y, feature_names). X[i] corresponds to forecasting y[i] using
    only information available before period i.
    """
    n = len(history)
    promo_periods = promo_periods or []
    holidays_set = holidays_set or set()
    promo_set = set(promo_periods)  # period indices that are promo

    feats = []
    for t in range(n):
        row = []
        # Lag features — guard against insufficient history.
        row.append(history[t - 1] if t >= 1 else 0)
        row.append(history[t - 7] if t >= 7 else (history[max(t - 1, 0)] if t > 0 else 0))
        row.append(history[t - 30] if t >= 30 else (history[max(t - 1, 0)] if t > 0 else 0))
        # Rolling means
        row.append(np.mean(history[max(0, t - 3):t]) if t >= 1 else 0)
        row.append(np.mean(history[max(0, t - 7):t]) if t >= 1 else 0)
        # Calendar
        if t < len(dates):
            d = dates[t]
            row.append(d.weekday())          # day of week 0-6
            row.append(d.month)               # 1-12
            row.append((d.month - 1) // 3)    # quarter 0-3
            row.append(1 if d.isoformat() in holidays_set else 0)
        else:
            row.extend([0, 1, 0, 0])
        # Promo flag
        row.append(1 if t in promo_set else 0)
        feats.append(row)

    X = np.asarray(feats, dtype=float)
    y = np.asarray(history, dtype=float)
    names = ['lag1', 'lag7', 'lag30', 'roll3', 'roll7', 'dow', 'month', 'quarter', 'holiday', 'promo']
    return X, y, names


def _future_features(history, future_dates, promo_periods, holidays_set, h_periods):
    """Build feature matrix for h future periods. Uses last-known history values
    as lags for the first horizon step and propagates predictions forward."""
    promo_set = set(promo_periods or [])
    holidays_set = holidays_set or set()
    n = len(history)
    rows = []
    extended = list(history)
    for h in range(h_periods):
        t = n + h
        row = []
        row.append(extended[t - 1])
        row.append(extended[t - 7] if t >= 7 else extended[-1])
        row.append(extended[t - 30] if t >= 30 else extended[-1])
        row.append(np.mean(extended[max(0, t - 3):t]))
        row.append(np.mean(extended[max(0, t - 7):t]))
        if h < len(future_dates):
            d = future_dates[h]
            row.append(d.weekday())
            row.append(d.month)
            row.append((d.month - 1) // 3)
            row.append(1 if d.isoformat() in holidays_set else 0)
        else:
            row.extend([0, 1, 0, 0])
        row.append(1 if t in promo_set else 0)
        rows.append(row)
        # Propagate prediction back into "extended" via caller after each step.
    return np.asarray(rows, dtype=float), extended


# ─── Model implementations ───
def _naive_seasonal(history, h_periods, season=12):
    """Repeat the last `season` values."""
    if len(history) < 1:
        return [0] * h_periods, [0] * len(history)
    fitted = list(history)
    season_len = min(season, len(history))
    last = history[-season_len:] if season_len > 0 else history
    forecast = [last[i % len(last)] for i in range(h_periods)]
    return forecast, fitted


def _holt_winters(history, h_periods, season=12, trend='add', seasonal='add'):
    if not HAS_STATSMODELS:
        raise ImportError('statsmodels not available')
    if len(history) < 2 * season:
        # Not enough data for seasonal HW — fall back to non-seasonal
        seasonal = None
        season = None
    model = ExponentialSmoothing(
        np.asarray(history, dtype=float),
        trend=trend,
        seasonal=seasonal,
        seasonal_periods=season,
        initialization_method='estimated',
    ).fit(optimized=True)
    fitted = list(model.fittedvalues)
    forecast = list(model.forecast(h_periods))
    return forecast, fitted


def _arima(history, h_periods):
    if not HAS_STATSMODELS:
        raise ImportError('statsmodels not available')
    if len(history) < 6:
        raise ValueError('ARIMA needs ≥6 observations')
    # Small-grid AIC search
    best = (None, math.inf)
    arr = np.asarray(history, dtype=float)
    for p in (0, 1, 2):
        for d in (0, 1):
            for q in (0, 1, 2):
                try:
                    m = ARIMA(arr, order=(p, d, q)).fit()
                    if m.aic < best[1]:
                        best = (m, m.aic)
                except Exception:
                    pass
    if best[0] is None:
        raise RuntimeError('ARIMA: no order converged')
    fitted = list(best[0].fittedvalues)
    forecast = list(best[0].forecast(h_periods))
    return forecast, fitted


def _ml_regressor(model_cls, history, h_periods, dates, future_dates, promo, holidays_set, **kwargs):
    if not HAS_SKLEARN:
        raise ImportError('scikit-learn not available')
    X, y, _ = _build_features(history, dates, promo, holidays_set)
    if len(history) < 10:
        raise ValueError('ML needs ≥10 observations')
    # Skip first row (lag-1 has no predecessor)
    model = model_cls(**kwargs)
    model.fit(X[1:], y[1:])
    # Fitted values
    fitted = [history[0]] + list(model.predict(X[1:]))
    # Recursive multi-step forecast — predict one period at a time, append, regenerate features
    extended = list(history)
    forecast = []
    for h in range(h_periods):
        Xf, _ = _future_features(extended, future_dates[h:h + 1], promo, holidays_set, 1)
        yhat = float(model.predict(Xf)[0])
        forecast.append(yhat)
        extended.append(yhat)
    return forecast, fitted


def _xgboost(history, h_periods, dates, future_dates, promo, holidays_set):
    if not HAS_XGBOOST:
        raise ImportError('xgboost not available')
    return _ml_regressor(
        XGBRegressor, history, h_periods, dates, future_dates, promo, holidays_set,
        n_estimators=120, max_depth=4, learning_rate=0.1, verbosity=0
    )


def _hybrid(history, h_periods, season, dates, future_dates, promo, holidays_set):
    """Holt-Winters baseline + RandomForest residual correction."""
    if not (HAS_STATSMODELS and HAS_SKLEARN):
        raise ImportError('hybrid needs both statsmodels and sklearn')
    hw_forecast, hw_fit = _holt_winters(history, h_periods, season)
    residuals = np.asarray(history, dtype=float) - np.asarray(hw_fit[:len(history)])
    X, _, _ = _build_features(history, dates, promo, holidays_set)
    if len(history) < 10:
        raise ValueError('Hybrid needs ≥10 observations')
    rf = RandomForestRegressor(n_estimators=80, max_depth=5, random_state=0)
    rf.fit(X[1:], residuals[1:])
    fitted = list(np.asarray(hw_fit[:len(history)]) + np.concatenate([[0], rf.predict(X[1:])]))
    extended = list(history)
    forecast = []
    for h in range(h_periods):
        Xf, _ = _future_features(extended, future_dates[h:h + 1], promo, holidays_set, 1)
        residual_pred = float(rf.predict(Xf)[0])
        yhat = hw_forecast[h] + residual_pred
        forecast.append(yhat)
        extended.append(yhat)
    return forecast, fitted


# ─── Main entry point ───
def run_forecast(payload):
    """Run all available models and return a leaderboard ranked by holdout MAPE.

    Payload schema:
      products: [{ name, history: [...] , history_freq?: 'monthly' | 'weekly' | 'daily',
                   promo_periods?: [int...], # period indices that are promotional
                 }, ...]
      params:
        h_periods: int                 # forecast horizon length
        time_grain: 'daily'|'weekly'|'monthly'
        horizon_start_date: ISO        # anchors future dates for calendar features
        season_length: int             # default 12 (monthly) / 7 (weekly) / 30 (daily)
        holidays: [ISO,...]
        models?: ['naive','holt_winters','arima','random_forest','gradient_boost','xgboost','mlp','hybrid']
        holdout_periods?: int          # default = min(6, len(history)//4)

    Returns:
      { products: [{ name, leaderboard: [{model, mape, rmse, mae, fitted, forecast, status}],
                     winner: <model name>, recommendation: <model name> }],
        env: { sklearn, statsmodels, xgboost }, solve_time, status }
    """
    t0 = time.time()
    products = payload.get('products') or []
    params = payload.get('params') or {}
    h = int(params.get('h_periods') or params.get('periods') or 12)
    grain = params.get('time_grain', 'monthly')
    season = int(params.get('season_length') or {'daily': 7, 'weekly': 13, 'monthly': 12}.get(grain, 12))
    holidays_set = set(params.get('holidays') or [])
    horizon_start = params.get('horizon_start_date')
    requested = params.get('models')

    available_models = {
        'naive': True,
        'holt_winters': HAS_STATSMODELS,
        'arima': HAS_STATSMODELS,
        'random_forest': HAS_SKLEARN,
        'gradient_boost': HAS_SKLEARN,
        'xgboost': HAS_XGBOOST,
        'mlp': HAS_SKLEARN,
        'hybrid': HAS_STATSMODELS and HAS_SKLEARN,
    }
    if requested:
        run_models = [m for m in requested if available_models.get(m, False)]
    else:
        run_models = [m for m, ok in available_models.items() if ok]

    out_products = []
    for prod in products:
        name = prod.get('name', 'product')
        history = [float(x or 0) for x in (prod.get('history') or [])]
        if len(history) < 2:
            out_products.append({
                'name': name,
                'error': 'history too short (need ≥2 observations)',
                'leaderboard': [],
            })
            continue

        promo_periods = prod.get('promo_periods') or []
        # Build calendar axes
        n_hist = len(history)
        full_dates = _date_axis(horizon_start, n_hist + h, grain)
        hist_dates = full_dates[:n_hist]
        future_dates = full_dates[n_hist:]

        # Holdout split for fair MAPE
        holdout_n = int(params.get('holdout_periods') or min(6, max(1, n_hist // 4)))
        train = history[:-holdout_n] if n_hist > holdout_n + 2 else history
        test = history[-holdout_n:] if n_hist > holdout_n + 2 else []
        train_dates = hist_dates[:len(train)]
        test_dates = hist_dates[len(train):n_hist]

        leaderboard = []
        recommendations = {
            'small': ['naive', 'holt_winters', 'arima'],   # <12 obs
            'medium': ['holt_winters', 'arima', 'random_forest', 'hybrid'],   # 12-36
            'large': ['random_forest', 'gradient_boost', 'xgboost', 'mlp', 'hybrid'],  # >36
        }
        bucket = 'small' if n_hist < 12 else ('medium' if n_hist <= 36 else 'large')
        recommended = next((m for m in recommendations[bucket] if m in run_models), run_models[0] if run_models else 'naive')

        for model_name in run_models:
            try:
                if model_name == 'naive':
                    test_pred, train_fit = _naive_seasonal(train, len(test), season)
                    full_fcst, full_fit = _naive_seasonal(history, h, season)
                elif model_name == 'holt_winters':
                    test_pred, train_fit = _holt_winters(train, len(test), season)
                    full_fcst, full_fit = _holt_winters(history, h, season)
                elif model_name == 'arima':
                    test_pred, train_fit = _arima(train, len(test))
                    full_fcst, full_fit = _arima(history, h)
                elif model_name == 'random_forest':
                    test_pred, train_fit = _ml_regressor(RandomForestRegressor, train, len(test), train_dates, test_dates, promo_periods, holidays_set, n_estimators=100, max_depth=6, random_state=0)
                    full_fcst, full_fit = _ml_regressor(RandomForestRegressor, history, h, hist_dates, future_dates, promo_periods, holidays_set, n_estimators=100, max_depth=6, random_state=0)
                elif model_name == 'gradient_boost':
                    test_pred, train_fit = _ml_regressor(GradientBoostingRegressor, train, len(test), train_dates, test_dates, promo_periods, holidays_set, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=0)
                    full_fcst, full_fit = _ml_regressor(GradientBoostingRegressor, history, h, hist_dates, future_dates, promo_periods, holidays_set, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=0)
                elif model_name == 'xgboost':
                    test_pred, train_fit = _xgboost(train, len(test), train_dates, test_dates, promo_periods, holidays_set)
                    full_fcst, full_fit = _xgboost(history, h, hist_dates, future_dates, promo_periods, holidays_set)
                elif model_name == 'mlp':
                    test_pred, train_fit = _ml_regressor(MLPRegressor, train, len(test), train_dates, test_dates, promo_periods, holidays_set, hidden_layer_sizes=(32, 16), max_iter=500, random_state=0)
                    full_fcst, full_fit = _ml_regressor(MLPRegressor, history, h, hist_dates, future_dates, promo_periods, holidays_set, hidden_layer_sizes=(32, 16), max_iter=500, random_state=0)
                elif model_name == 'hybrid':
                    test_pred, train_fit = _hybrid(train, len(test), season, train_dates, test_dates, promo_periods, holidays_set)
                    full_fcst, full_fit = _hybrid(history, h, season, hist_dates, future_dates, promo_periods, holidays_set)
                else:
                    continue

                mape = _mape(test, test_pred) if test else float('inf')
                rmse_v = _rmse(test, test_pred) if test else 0.0
                mae_v = _mae(test, test_pred) if test else 0.0

                leaderboard.append({
                    'model': model_name,
                    'mape': round(mape, 2),
                    'rmse': round(rmse_v, 2),
                    'mae': round(mae_v, 2),
                    'forecast': [round(float(v), 2) for v in full_fcst],
                    'fitted': [round(float(v), 2) for v in full_fit[:n_hist]],
                    'status': 'ok',
                })
            except Exception as e:
                leaderboard.append({
                    'model': model_name,
                    'mape': float('inf'),
                    'rmse': 0,
                    'mae': 0,
                    'forecast': [],
                    'fitted': [],
                    'status': f'failed: {str(e)[:80]}',
                })

        # Sort by MAPE ascending (best first), but valid models above failed
        leaderboard.sort(key=lambda r: (r['status'] != 'ok', r['mape']))
        winner = leaderboard[0]['model'] if leaderboard and leaderboard[0]['status'] == 'ok' else None

        out_products.append({
            'name': name,
            'history_length': n_hist,
            'data_size_bucket': bucket,
            'recommended_model': recommended,
            'winner': winner,
            'horizon_periods': h,
            'leaderboard': leaderboard,
            'warning': 'Insufficient history for seasonality assessment — classical methods recommended.' if n_hist < 12 else None,
        })

    return {
        'status': 'ok',
        'products': out_products,
        'env': {
            'sklearn': HAS_SKLEARN,
            'statsmodels': HAS_STATSMODELS,
            'xgboost': HAS_XGBOOST,
        },
        'solve_time': round(time.time() - t0, 2),
    }
