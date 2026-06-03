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


# ─── GAP-7 · accuracy metrics that work where MAPE breaks ───
def _mase(actual, pred, train, season=1):
    """Mean Absolute Scaled Error. Scales MAE by the in-sample one-step (seasonal) naive MAE,
    so it's defined even when actuals are zero — the regime where MAPE is meaningless. <1 beats naive."""
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    tr = np.asarray(train, dtype=float)
    m = season if (season and len(tr) > season) else 1
    denom = np.mean(np.abs(tr[m:] - tr[:-m])) if len(tr) > m else 0.0
    if denom <= 1e-9 or len(actual) == 0:
        return float('inf')
    return float(np.mean(np.abs(actual - pred)) / denom)


def _bias(actual, pred):
    """Signed mean error (pred − actual). Positive ⇒ systematic over-forecast. A biased-but-accurate
    forecast is the dangerous case MAPE/RMSE hide."""
    if len(actual) == 0:
        return 0.0
    return float(np.mean(np.asarray(pred, dtype=float) - np.asarray(actual, dtype=float)))


def _tracking_signal(actual, pred):
    """RSFE / MAD — running sum of forecast errors over mean absolute deviation. |TS| > 4 ⇒ the
    forecast is out of statistical control (persistent bias), independent of headline MAPE."""
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    if len(actual) == 0:
        return 0.0
    err = pred - actual
    mad = np.mean(np.abs(err))
    if mad <= 1e-9:
        return 0.0
    return float(np.sum(err) / mad)


# ─── GAP-7 · intermittent-demand models (pure numpy, always available) ───
def _intermittence(series):
    """Syntetos–Boylan demand classification. Returns (ADI, CV2, label).
    ADI = avg inter-demand interval; CV2 = squared CV of non-zero sizes."""
    s = np.asarray(series, dtype=float)
    nz = s[s > 0]
    n_nz = len(nz)
    if n_nz == 0:
        return float('inf'), 0.0, 'no-demand'
    adi = len(s) / n_nz
    cv2 = (np.std(nz) / np.mean(nz)) ** 2 if np.mean(nz) > 0 else 0.0
    if adi < 1.32 and cv2 < 0.49:
        label = 'smooth'
    elif adi >= 1.32 and cv2 < 0.49:
        label = 'intermittent'
    elif adi < 1.32 and cv2 >= 0.49:
        label = 'erratic'
    else:
        label = 'lumpy'
    return float(adi), float(cv2), label


def _croston_core(series, h, alpha=0.1, variant='croston'):
    """Croston / SBA / TSB one-rate forecast. Returns (forecast[h], fitted[len(series)]).
    croston: rate = z/p; sba: (1−α/2)·z/p; tsb: prob·z (probability-based, handles obsolescence)."""
    s = np.asarray(series, dtype=float)
    n = len(s)
    fitted = np.zeros(n)
    if n == 0 or np.all(s <= 0):
        return [0.0] * h, list(fitted)

    if variant == 'tsb':
        beta = 0.1
        nz = s[s > 0]
        z = float(nz[0]) if len(nz) else 0.0
        prob = float(np.mean(s > 0))
        for t in range(n):
            fitted[t] = prob * z
            if s[t] > 0:
                z = z + alpha * (s[t] - z)
                prob = prob + beta * (1.0 - prob)
            else:
                prob = prob + beta * (0.0 - prob)
        rate = prob * z
    else:
        # Croston / SBA — update demand size z and interval p at each non-zero point.
        first = next((i for i, v in enumerate(s) if v > 0), 0)
        z = float(s[first]) if s[first] > 0 else float(np.mean(s[s > 0]))
        p = 1.0
        q = 1  # periods since last non-zero
        for t in range(n):
            if s[t] > 0:
                z = z + alpha * (s[t] - z)
                p = p + alpha * (q - p)
                q = 1
            else:
                q += 1
            fitted[t] = z / p if p > 0 else 0.0
        rate = z / p if p > 0 else 0.0
        if variant == 'sba':
            rate *= (1.0 - alpha / 2.0)
            fitted *= (1.0 - alpha / 2.0)
    return [float(rate)] * h, list(fitted)


def _croston(series, h, alpha=0.1):
    return _croston_core(series, h, alpha, 'croston')


def _sba(series, h, alpha=0.1):
    return _croston_core(series, h, alpha, 'sba')


def _tsb(series, h, alpha=0.1):
    return _croston_core(series, h, alpha, 'tsb')


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


def _lag_offsets(grain, season=None):
    """(MF-14) Grain-aware lag offsets so the three lag features mean the same thing
    regardless of time grain. The old hardcoded (1, 7, 30) read as day/week/month — but on
    the DEFAULT monthly grain `lag-30` meant "30 months ago", needing 2.5 years of history
    before the feature was ever real. Now:
        daily   → (1, 7, 30)      # yesterday / last week / last month
        weekly  → (1, 4, season)  # last week / ~last month / last season (13 or 52)
        monthly → (1, 3, season)  # last month / last quarter / last year (12)
    """
    grain = (grain or 'monthly').lower()
    if grain == 'daily':
        return (1, 7, 30)
    if grain == 'weekly':
        return (1, 4, season if season and season > 4 else 13)
    return (1, 3, season if season and season > 3 else 12)  # monthly default


def _build_features(history, dates, promo_periods, holidays_set, lags=(1, 7, 30)):
    """Build a DataFrame-like 2D feature matrix for ML/DL models.

    Returns (X, y, feature_names). X[i] corresponds to forecasting y[i] using
    only information available before period i. `lags` are grain-aware (see _lag_offsets).
    """
    n = len(history)
    promo_periods = promo_periods or []
    holidays_set = holidays_set or set()
    promo_set = set(promo_periods)  # period indices that are promo
    l0, l1, l2 = lags

    feats = []
    for t in range(n):
        row = []
        # Lag features — guard against insufficient history.
        row.append(history[t - l0] if t >= l0 else 0)
        row.append(history[t - l1] if t >= l1 else (history[max(t - 1, 0)] if t > 0 else 0))
        row.append(history[t - l2] if t >= l2 else (history[max(t - 1, 0)] if t > 0 else 0))
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
    l0, l1, l2 = lags
    names = [f'lag{l0}', f'lag{l1}', f'lag{l2}', 'roll3', 'roll7', 'dow', 'month', 'quarter', 'holiday', 'promo']
    return X, y, names


def _future_features(history, future_dates, promo_periods, holidays_set, h_periods, lags=(1, 7, 30)):
    """Build feature matrix for h future periods. Uses last-known history values
    as lags for the first horizon step and propagates predictions forward.
    `lags` must match the ones _build_features used for training (grain-aware)."""
    promo_set = set(promo_periods or [])
    holidays_set = holidays_set or set()
    n = len(history)
    l0, l1, l2 = lags
    rows = []
    extended = list(history)
    for h in range(h_periods):
        t = n + h
        row = []
        row.append(extended[t - l0] if t >= l0 else extended[-1])
        row.append(extended[t - l1] if t >= l1 else extended[-1])
        row.append(extended[t - l2] if t >= l2 else extended[-1])
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


def _ml_regressor(model_cls, history, h_periods, dates, future_dates, promo, holidays_set, lags=(1, 7, 30), **kwargs):
    if not HAS_SKLEARN:
        raise ImportError('scikit-learn not available')
    X, y, _ = _build_features(history, dates, promo, holidays_set, lags=lags)
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
        Xf, _ = _future_features(extended, future_dates[h:h + 1], promo, holidays_set, 1, lags=lags)
        yhat = float(model.predict(Xf)[0])
        forecast.append(yhat)
        extended.append(yhat)
    return forecast, fitted


def _xgboost(history, h_periods, dates, future_dates, promo, holidays_set, lags=(1, 7, 30)):
    if not HAS_XGBOOST:
        raise ImportError('xgboost not available')
    return _ml_regressor(
        XGBRegressor, history, h_periods, dates, future_dates, promo, holidays_set, lags=lags,
        n_estimators=120, max_depth=4, learning_rate=0.1, verbosity=0
    )


def _hybrid(history, h_periods, season, dates, future_dates, promo, holidays_set, lags=(1, 7, 30)):
    """Holt-Winters baseline + RandomForest residual correction."""
    if not (HAS_STATSMODELS and HAS_SKLEARN):
        raise ImportError('hybrid needs both statsmodels and sklearn')
    hw_forecast, hw_fit = _holt_winters(history, h_periods, season)
    residuals = np.asarray(history, dtype=float) - np.asarray(hw_fit[:len(history)])
    X, _, _ = _build_features(history, dates, promo, holidays_set, lags=lags)
    if len(history) < 10:
        raise ValueError('Hybrid needs ≥10 observations')
    rf = RandomForestRegressor(n_estimators=80, max_depth=5, random_state=0)
    rf.fit(X[1:], residuals[1:])
    fitted = list(np.asarray(hw_fit[:len(history)]) + np.concatenate([[0], rf.predict(X[1:])]))
    extended = list(history)
    forecast = []
    for h in range(h_periods):
        Xf, _ = _future_features(extended, future_dates[h:h + 1], promo, holidays_set, 1, lags=lags)
        residual_pred = float(rf.predict(Xf)[0])
        yhat = hw_forecast[h] + residual_pred
        forecast.append(yhat)
        extended.append(yhat)
    return forecast, fitted


def _forecast_full(model_name, history, h, hist_dates, future_dates, promo, holidays_set, season, lags):
    """Re-run ONE model for its h-step forecast only (no holdout split). Mirrors the
    `full_fcst` branch of run_forecast exactly, so a counterfactual run can never
    diverge from the headline forecast. Used by DM-B (promo uplift attribution):
    the same winner re-run with promo flags STRIPPED gives the baseline, and
    uplift = committed − baseline. Returns a plain float list, or None for an
    unknown model; raises like the underlying model on a genuine failure."""
    if model_name == 'naive':
        f, _ = _naive_seasonal(history, h, season)
    elif model_name == 'holt_winters':
        f, _ = _holt_winters(history, h, season)
    elif model_name == 'arima':
        f, _ = _arima(history, h)
    elif model_name == 'random_forest':
        f, _ = _ml_regressor(RandomForestRegressor, history, h, hist_dates, future_dates, promo, holidays_set, lags=lags, n_estimators=100, max_depth=6, random_state=0)
    elif model_name == 'gradient_boost':
        f, _ = _ml_regressor(GradientBoostingRegressor, history, h, hist_dates, future_dates, promo, holidays_set, lags=lags, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=0)
    elif model_name == 'xgboost':
        f, _ = _xgboost(history, h, hist_dates, future_dates, promo, holidays_set, lags=lags)
    elif model_name == 'mlp':
        f, _ = _ml_regressor(MLPRegressor, history, h, hist_dates, future_dates, promo, holidays_set, lags=lags, hidden_layer_sizes=(32, 16), max_iter=500, random_state=0)
    elif model_name == 'hybrid':
        f, _ = _hybrid(history, h, season, hist_dates, future_dates, promo, holidays_set, lags=lags)
    elif model_name == 'croston':
        f, _ = _croston(history, h)
    elif model_name == 'sba':
        f, _ = _sba(history, h)
    elif model_name == 'tsb':
        f, _ = _tsb(history, h)
    else:
        return None
    return [float(v) for v in f]


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
    lags = _lag_offsets(grain, season)  # (MF-14) grain-aware lag offsets for ML feature builders
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
        # GAP-7 — intermittent-demand models (pure numpy, always available).
        'croston': True,
        'sba': True,
        'tsb': True,
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
        preds = {}          # W9·D-5 — per-model {test, full} predictions, for the ensemble + accuracy-by-horizon
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
                    test_pred, train_fit = _ml_regressor(RandomForestRegressor, train, len(test), train_dates, test_dates, promo_periods, holidays_set, lags=lags, n_estimators=100, max_depth=6, random_state=0)
                    full_fcst, full_fit = _ml_regressor(RandomForestRegressor, history, h, hist_dates, future_dates, promo_periods, holidays_set, lags=lags, n_estimators=100, max_depth=6, random_state=0)
                elif model_name == 'gradient_boost':
                    test_pred, train_fit = _ml_regressor(GradientBoostingRegressor, train, len(test), train_dates, test_dates, promo_periods, holidays_set, lags=lags, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=0)
                    full_fcst, full_fit = _ml_regressor(GradientBoostingRegressor, history, h, hist_dates, future_dates, promo_periods, holidays_set, lags=lags, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=0)
                elif model_name == 'xgboost':
                    test_pred, train_fit = _xgboost(train, len(test), train_dates, test_dates, promo_periods, holidays_set, lags=lags)
                    full_fcst, full_fit = _xgboost(history, h, hist_dates, future_dates, promo_periods, holidays_set, lags=lags)
                elif model_name == 'mlp':
                    test_pred, train_fit = _ml_regressor(MLPRegressor, train, len(test), train_dates, test_dates, promo_periods, holidays_set, lags=lags, hidden_layer_sizes=(32, 16), max_iter=500, random_state=0)
                    full_fcst, full_fit = _ml_regressor(MLPRegressor, history, h, hist_dates, future_dates, promo_periods, holidays_set, lags=lags, hidden_layer_sizes=(32, 16), max_iter=500, random_state=0)
                elif model_name == 'hybrid':
                    test_pred, train_fit = _hybrid(train, len(test), season, train_dates, test_dates, promo_periods, holidays_set, lags=lags)
                    full_fcst, full_fit = _hybrid(history, h, season, hist_dates, future_dates, promo_periods, holidays_set, lags=lags)
                elif model_name == 'croston':
                    test_pred, train_fit = _croston(train, len(test))
                    full_fcst, full_fit = _croston(history, h)
                elif model_name == 'sba':
                    test_pred, train_fit = _sba(train, len(test))
                    full_fcst, full_fit = _sba(history, h)
                elif model_name == 'tsb':
                    test_pred, train_fit = _tsb(train, len(test))
                    full_fcst, full_fit = _tsb(history, h)
                else:
                    continue

                mape = _mape(test, test_pred) if test else float('inf')
                rmse_v = _rmse(test, test_pred) if test else 0.0
                mae_v = _mae(test, test_pred) if test else 0.0
                # GAP-7 — MASE (defined on zero-heavy series), signed bias, and tracking signal.
                mase_v = _mase(test, test_pred, train, season) if test else float('inf')
                bias_v = _bias(test, test_pred) if test else 0.0
                ts_v = _tracking_signal(test, test_pred) if test else 0.0

                leaderboard.append({
                    'model': model_name,
                    'mape': round(mape, 2),
                    'rmse': round(rmse_v, 2),
                    'mae': round(mae_v, 2),
                    'mase': round(mase_v, 3) if math.isfinite(mase_v) else None,
                    'bias': round(bias_v, 2),
                    'tracking_signal': round(ts_v, 2),
                    'out_of_control': bool(abs(ts_v) > 4),
                    'forecast': [round(float(v), 2) for v in full_fcst],
                    'fitted': [round(float(v), 2) for v in full_fit[:n_hist]],
                    'status': 'ok',
                })
                # W9·D-5 — keep raw holdout + full predictions for the ensemble blend
                # and the accuracy-by-horizon backtest.
                preds[model_name] = {'test': list(test_pred), 'full': list(full_fcst)}
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

        # GAP-7 — intermittence classification. For lumpy/intermittent series MAPE is meaningless
        # (zeros), so rank by MASE and steer the recommendation to Croston/SBA/TSB.
        adi, cv2, intermit_label = _intermittence(history)
        is_intermittent = intermit_label in ('intermittent', 'lumpy')

        # ── W9 · D-5 — ENSEMBLE (top-N inverse-error-weighted blend), depth-gated ──
        # A blend of the best few models beats any single one when the data is deep
        # enough to estimate their relative skill; on THIN data it overfits the tiny
        # holdout, so it is gated on n_hist ≥ 18 AND a real holdout AND ≥2 components.
        # Components are the top-N by the ranking metric (MASE on intermittent series,
        # else MAPE); weights ∝ 1/error so the most accurate model dominates honestly.
        ensemble_meta = None
        metric = 'mase' if is_intermittent else 'mape'
        ok_rows = [r for r in leaderboard if r['status'] == 'ok' and preds.get(r['model'])
                   and r.get(metric) is not None and math.isfinite(r.get(metric, float('inf'))) and r.get(metric) > 0]
        if len(test) >= 2 and n_hist >= 18 and len(ok_rows) >= 2:
            top = sorted(ok_rows, key=lambda r: r[metric])[:3]
            inv = [1.0 / r[metric] for r in top]
            wsum = sum(inv) or 1.0
            comps = [(r['model'], w / wsum) for r, w in zip(top, inv)]
            ens_test = [0.0] * len(test)
            ens_full = [0.0] * h
            for (m, w) in comps:
                tp, fp = preds[m]['test'], preds[m]['full']
                for k in range(min(len(ens_test), len(tp))): ens_test[k] += w * float(tp[k])
                for k in range(min(len(ens_full), len(fp))): ens_full[k] += w * float(fp[k])
            e_mape = _mape(test, ens_test); e_rmse = _rmse(test, ens_test); e_mae = _mae(test, ens_test)
            e_mase = _mase(test, ens_test, train, season); e_bias = _bias(test, ens_test); e_ts = _tracking_signal(test, ens_test)
            leaderboard.append({
                'model': 'ensemble', 'mape': round(e_mape, 2), 'rmse': round(e_rmse, 2), 'mae': round(e_mae, 2),
                'mase': round(e_mase, 3) if math.isfinite(e_mase) else None,
                'bias': round(e_bias, 2), 'tracking_signal': round(e_ts, 2), 'out_of_control': bool(abs(e_ts) > 4),
                'forecast': [round(float(v), 2) for v in ens_full], 'fitted': [], 'status': 'ok',
                'components': [{'model': m, 'weight': round(w, 3)} for (m, w) in comps],
            })
            preds['ensemble'] = {'test': ens_test, 'full': ens_full}
            ensemble_meta = {'gated_on': f'n_hist≥18 ({n_hist}) · holdout {len(test)} · {metric}',
                             'components': [{'model': m, 'weight': round(w, 3)} for (m, w) in comps]}
        elif len(ok_rows) >= 1:
            ensemble_meta = {'skipped': True,
                             'reason': ('history < 18 periods — a blend would overfit the holdout' if n_hist < 18
                                        else 'need ≥2 scorable models for a blend')}

        if is_intermittent:
            # rank by MASE (finite on zeros); push the intermittent methods up
            leaderboard.sort(key=lambda r: (r['status'] != 'ok',
                                            r['mase'] if (r.get('mase') is not None) else float('inf')))
            recommended = next((m for m in ('tsb', 'sba', 'croston') if m in run_models), recommended)
        else:
            leaderboard.sort(key=lambda r: (r['status'] != 'ok', r['mape']))
        winner = leaderboard[0]['model'] if leaderboard and leaderboard[0]['status'] == 'ok' else None

        # ── W9 — ACCURACY BY HORIZON. The headline MAPE averages the whole holdout;
        # this exposes how the WINNER's error grows step-by-step into the future
        # (period 1 ahead vs period h ahead), the honest read on how far out the
        # forecast can be trusted. Per-step absolute % error on the holdout window.
        accuracy_by_horizon = None
        wp = preds.get(winner)
        if wp and test:
            tp = wp['test']
            accuracy_by_horizon = []
            for k in range(min(len(test), len(tp))):
                a = float(test[k]); f = float(tp[k])
                accuracy_by_horizon.append({'step': k + 1, 'actual': round(a, 1), 'forecast': round(f, 1),
                                            'ape': round(abs(a - f) / max(abs(a), 1e-9) * 100, 1)})

        # ── DM-A · per-period PREDICTION INTERVAL on the winner ──
        # Honest forecast-uncertainty band from the winner's in-sample residual
        # dispersion, WIDENING with the horizon step (error compounds the further
        # out you forecast): σ_k = σ_resid·√(k+1), P10/P90 via the normal quantile
        # ±1.2816σ. The safety-stock (z·σ) and CVaR cards already consume this
        # dispersion implicitly — DM-A surfaces it per period so the planner sees
        # the cone of uncertainty, not just the point line.
        forecast_pi = None
        wrow = next((r for r in leaderboard if r['model'] == winner), None) if winner else None
        if wrow and wrow.get('forecast'):
            # Prefer OUT-OF-SAMPLE holdout error dispersion — in-sample fitted residuals
            # badly understate uncertainty for ML models that overfit the training fit.
            sigma = 0.0
            wp2 = preds.get(winner)
            if wp2 and test:
                e = [test[k] - wp2['test'][k] for k in range(min(len(test), len(wp2['test'])))]
                sigma = float(np.std(e)) if len(e) >= 2 else (abs(e[0]) if e else 0.0)
            if sigma <= 0:                       # no holdout → fall back to fitted residuals
                fit = wrow.get('fitted') or []
                resid = [history[i] - fit[i] for i in range(min(len(fit), n_hist))]
                sigma = float(np.std(resid)) if len(resid) >= 2 else 0.0
            z90 = 1.2816
            forecast_pi = []
            for k, f in enumerate(wrow['forecast']):
                band = z90 * sigma * math.sqrt(k + 1)
                forecast_pi.append({'step': k + 1, 'point': round(float(f), 1),
                                    'p10': round(max(0.0, float(f) - band), 1),
                                    'p90': round(float(f) + band, 1)})

        # ── DM-B · PROMO UPLIFT ATTRIBUTION on the winner ──
        # Re-run the winner with promo flags STRIPPED → a baseline counterfactual;
        # uplift = committed − baseline, per period. Decomposes how many forecast
        # units the promo flag is actually driving (the causal contribution), vs
        # the total — only when there are FUTURE promo periods to attribute, and
        # only honestly: a model with no promo regressor (naive/croston) yields
        # zero uplift, which is the truthful answer for it.
        promo_attribution = None
        future_promos = [p - n_hist for p in promo_periods if p >= n_hist]
        if winner and future_promos and wrow and wrow.get('forecast'):
            try:
                baseline = _forecast_full(winner, history, h, hist_dates, future_dates, [], holidays_set, season, lags)
                if baseline:
                    fc = wrow['forecast']
                    rows = []
                    for k in range(min(len(fc), len(baseline))):
                        up = float(fc[k]) - float(baseline[k])
                        rows.append({'step': k + 1, 'baseline': round(float(baseline[k]), 1),
                                     'uplift': round(up, 1), 'total': round(float(fc[k]), 1),
                                     'is_promo': k in future_promos})
                    promo_attribution = {
                        'periods': rows,
                        'promo_uplift_total': round(sum(r['uplift'] for r in rows if r['is_promo']), 1),
                        'model': winner,
                        'method': 'winner counterfactual (promo flags stripped)',
                    }
            except Exception:
                promo_attribution = None

        out_products.append({
            'name': name,
            'history_length': n_hist,
            'data_size_bucket': bucket,
            'recommended_model': recommended,
            'winner': winner,
            'horizon_periods': h,
            'leaderboard': leaderboard,
            'ensemble': ensemble_meta,                       # W9·D-5
            'accuracy_by_horizon': accuracy_by_horizon,      # W9
            'forecast_pi': forecast_pi,                      # DM-A — per-period P10/P90 band
            'promo_attribution': promo_attribution,          # DM-B — baseline vs promo uplift

            # GAP-7 — demand-pattern classification (Syntetos–Boylan).
            'intermittence': {'adi': round(adi, 2) if math.isfinite(adi) else None,
                              'cv2': round(cv2, 3), 'label': intermit_label,
                              'is_intermittent': is_intermittent,
                              'ranked_by': 'mase' if is_intermittent else 'mape'},
            'warning': 'Insufficient history for seasonality assessment — classical methods recommended.' if n_hist < 12 else None,
        })

    # ── GAP-7 · hierarchical reconciliation (bottom-up) ──
    # Sum each SKU's winning forecast into a coherent family/total forecast, so the SKU level and
    # the aggregate agree by construction (the input disaggregation/aggregate tiers consume this).
    # Bottom-up is the unbiased, dependency-free reconciliation; MinT would need a residual
    # covariance estimate we don't carry here.
    reconciliation = None
    winners = []
    for op in out_products:
        lb = op.get('leaderboard') or []
        win = next((r for r in lb if r.get('status') == 'ok' and r.get('forecast')), None)
        if win:
            winners.append(win['forecast'])
    if winners:
        L = max(len(w) for w in winners)
        total = [0.0] * L
        for w in winners:
            for t in range(len(w)):
                total[t] += w[t]
        reconciliation = {
            'method': 'bottom_up',
            'total_forecast': [round(v, 2) for v in total],
            'total_horizon': round(sum(total), 1),
            'n_series': len(winners),
            'note': 'SKU winners summed to a coherent total — SKU and aggregate levels now agree.',
        }

    return {
        'status': 'ok',
        'products': out_products,
        'reconciliation': reconciliation,
        'env': {
            'sklearn': HAS_SKLEARN,
            'statsmodels': HAS_STATSMODELS,
            'xgboost': HAS_XGBOOST,
        },
        'solve_time': round(time.time() - t0, 2),
    }
