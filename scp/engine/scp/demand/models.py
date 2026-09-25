"""Statistical forecast models.

Every model is a pure function ``(y, h, m) -> ndarray[h]``: history ``y`` (one value per period,
oldest first, already cleansed), horizon ``h`` in periods, season length ``m``. A model raises
:class:`Infeasible` when the history is too short for it, so the competition can exclude it with a
reason instead of producing a meaningless fit. Smoothing parameters are fitted by minimising the
in-sample one-step squared error; the intermittent-demand models use the literature's fixed
smoothing constants (Syntetos & Boylan 2005; Teunter, Syntetos & Babai 2011) because squared-error
fitting on mostly-zero series is unstable.

Forecasts are clipped at zero: demand is never negative.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize, minimize_scalar

from ..model import ForecastModelId as M


class Infeasible(Exception):
    """The history is too short (or has the wrong shape) for this model."""


Forecaster = Callable[[np.ndarray, int, int], np.ndarray]


def _need(y: np.ndarray, n: int, what: str) -> None:
    if len(y) < n:
        raise Infeasible(f"needs at least {n} periods of history ({what})")


def _clip(f: np.ndarray) -> np.ndarray:
    return np.maximum(np.asarray(f, dtype=float), 0.0)


# ---- baselines ---------------------------------------------------------------------------------
def naive(y: np.ndarray, h: int, m: int) -> np.ndarray:
    _need(y, 1, "last value")
    return _clip(np.full(h, y[-1]))


def seasonal_naive(y: np.ndarray, h: int, m: int) -> np.ndarray:
    _need(y, m, "one full season")
    return _clip(y[-m:][np.arange(h) % m])


def ma_window(m: int) -> int:
    """4 periods for weekly data, 3 for monthly."""
    return max(3, round(m / 13))


def moving_average(y: np.ndarray, h: int, m: int) -> np.ndarray:
    _need(y, 1, "one value")
    k = min(len(y), ma_window(m))
    return _clip(np.full(h, y[-k:].mean()))


# ---- exponential smoothing ---------------------------------------------------------------------
def _ses_run(alpha: float, y: list[float]) -> tuple[float, float]:
    level = y[0]
    sse = 0.0
    for v in y[1:]:
        e = v - level
        sse += e * e
        level += alpha * e
    return sse, level


def ses_alpha(y: list[float]) -> float:
    res = minimize_scalar(lambda a: _ses_run(a, y)[0], bounds=(0.01, 0.99), method="bounded",
                          options={"xatol": 1e-4})
    return float(res.x)


def ses(y: np.ndarray, h: int, m: int) -> np.ndarray:
    _need(y, 2, "a level to smooth")
    ys = [float(v) for v in y]
    _, level = _ses_run(ses_alpha(ys), ys)
    return _clip(np.full(h, level))


def _holt_run(p: np.ndarray, y: list[float]) -> tuple[float, float, float, float]:
    alpha, beta_share, phi = (float(v) for v in p)
    beta = alpha * beta_share
    level = y[0]
    k = min(4, len(y) - 1)
    trend = (y[k] - y[0]) / k
    sse = 0.0
    for v in y[1:]:
        f = level + phi * trend
        e = v - f
        sse += e * e
        new_level = f + alpha * e
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return sse, level, trend, phi


def holt_damped(y: np.ndarray, h: int, m: int) -> np.ndarray:
    """Additive damped trend (Gardner & McKenzie). The trend flattens over the horizon, which is what
    makes it a robust default for business series."""
    _need(y, 4, "a level and a trend")
    ys = [float(v) for v in y]
    res = minimize(lambda p: _holt_run(p, ys)[0], x0=[0.3, 0.3, 0.9],
                   bounds=[(0.01, 0.99), (0.01, 1.0), (0.8, 0.98)], method="L-BFGS-B")
    _, level, trend, phi = _holt_run(res.x, ys)
    damp = np.cumsum(phi ** np.arange(1, h + 1))
    return _clip(level + damp * trend)


def _hw_init(y: np.ndarray, m: int) -> tuple[float, float, np.ndarray]:
    """Level and season from the first season; trend from the first two seasons when available."""
    first = y[:m].mean()
    trend = (y[m:2 * m].mean() - first) / m if len(y) >= 2 * m else 0.0
    return first, trend, y[:m] - first


def _hw_run(p: np.ndarray, y: list[float], m: int) -> tuple[float, float, float, list[float], float]:
    # plain Python floats: this loop runs thousands of times per fit, and numpy scalars are slow
    alpha, beta_share, gamma_share, phi = (float(v) for v in p)
    beta, gamma = alpha * beta_share, (1 - alpha) * gamma_share
    level, trend, s0 = _hw_init(np.asarray(y), m)
    season = [float(v) for v in s0]
    sse = 0.0
    for t, v in enumerate(y):
        i = t % m
        damped = phi * trend
        f = level + damped + season[i]
        e = v - f
        sse += e * e
        new_level = alpha * (v - season[i]) + (1 - alpha) * (level + damped)
        trend = beta * (new_level - level) + (1 - beta) * damped
        season[i] = gamma * (v - level - damped) + (1 - gamma) * season[i]
        level = new_level
    return sse, level, trend, season, phi


def holt_winters(y: np.ndarray, h: int, m: int) -> np.ndarray:
    """Additive Holt-Winters with a damped trend. Needs one full season plus 8 periods (two seasons
    give a better initial trend)."""
    _need(y, m + 8, "a full season plus 8 periods")
    ys = [float(v) for v in y]
    res = minimize(lambda p: _hw_run(p, ys, m)[0], x0=[0.2, 0.2, 0.3, 0.9],
                   bounds=[(0.01, 0.99), (0.01, 1.0), (0.01, 1.0), (0.8, 0.98)], method="L-BFGS-B")
    _, level, trend, season_list, phi = _hw_run(res.x, ys, m)
    season = np.array(season_list)
    n = len(y)
    damp = np.cumsum(phi ** np.arange(1, h + 1))
    idx = (n + np.arange(h)) % m
    return _clip(level + damp * trend + season[idx])


# ---- intermittent demand -----------------------------------------------------------------------
INTERMITTENT_ALPHA = 0.1
TSB_BETA = 0.1


def _croston_state(y: np.ndarray, alpha: float) -> tuple[float, float]:
    nz = np.flatnonzero(y > 0)
    if len(nz) < 2:
        raise Infeasible("needs at least two non-zero periods")
    size = y[nz[0]]
    interval = float(np.diff(nz).mean())
    q = 1
    for v in y[nz[0] + 1:]:
        if v > 0:
            size += alpha * (v - size)
            interval += alpha * (q - interval)
            q = 1
        else:
            q += 1
    return size, interval


def croston(y: np.ndarray, h: int, m: int) -> np.ndarray:
    size, interval = _croston_state(y, INTERMITTENT_ALPHA)
    return _clip(np.full(h, size / interval))


def sba(y: np.ndarray, h: int, m: int) -> np.ndarray:
    """Syntetos–Boylan approximation: Croston with its positive bias removed."""
    size, interval = _croston_state(y, INTERMITTENT_ALPHA)
    return _clip(np.full(h, (1 - INTERMITTENT_ALPHA / 2) * size / interval))


def tsb(y: np.ndarray, h: int, m: int) -> np.ndarray:
    """Teunter–Syntetos–Babai: smooths the probability of demand every period, so a dying item's
    forecast decays instead of staying frozen at its last level (Croston's weakness)."""
    nz = y > 0
    if nz.sum() < 2:
        raise Infeasible("needs at least two non-zero periods")
    prob = nz.mean()
    size = y[nz].mean()
    for v in y:
        prob += TSB_BETA * (float(v > 0) - prob)
        if v > 0:
            size += INTERMITTENT_ALPHA * (v - size)
    return _clip(np.full(h, prob * size))


# ---- regression --------------------------------------------------------------------------------
def _design(t: np.ndarray, m: int, harmonics: int) -> np.ndarray:
    cols = [np.ones_like(t), t]
    for k in range(1, harmonics + 1):
        w = 2 * np.pi * k * t / m
        cols += [np.sin(w), np.cos(w)]
    return np.column_stack(cols)


def regression(y: np.ndarray, h: int, m: int) -> np.ndarray:
    """Linear trend + Fourier seasonality (up to 3 harmonics once a full season is available)."""
    n = len(y)
    _need(y, 6, "a trend line")
    harmonics = min(3, m // 2) if n >= m + 4 else 0
    t = np.arange(n, dtype=float)
    x = _design(t, m, harmonics)
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    tf = np.arange(n, n + h, dtype=float)
    return _clip(_design(tf, m, harmonics) @ coef)


# ---- registry ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Spec:
    id: M
    label: str
    family: str          # baseline | smoothing | intermittent | regression | ensemble | foundation
    complexity: int      # tie-break: the simpler model wins an exact tie
    fn: Forecaster | None
    description: str


SPECS: dict[M, Spec] = {s.id: s for s in [
    Spec(M.NAIVE, "Naïve", "baseline", 0, naive, "Next periods = last period. The yardstick for forecast value add."),
    Spec(M.MOVING_AVERAGE, "Moving average", "baseline", 1, moving_average,
         "Mean of the last 4 weeks / 3 months."),
    Spec(M.SEASONAL_NAIVE, "Seasonal naïve", "baseline", 2, seasonal_naive,
         "Same period last season."),
    Spec(M.SES, "Simple exponential smoothing", "smoothing", 3, ses,
         "Weighted level, no trend or season. α fitted."),
    Spec(M.CROSTON, "Croston", "intermittent", 4, croston,
         "Smooths demand size and interval separately. For intermittent items."),
    Spec(M.SBA, "Syntetos–Boylan (SBA)", "intermittent", 4, sba, "Croston with its bias removed."),
    Spec(M.TSB, "Teunter–Syntetos–Babai (TSB)", "intermittent", 5, tsb,
         "Smooths demand probability, so obsolescence shows."),
    Spec(M.HOLT_DAMPED, "Damped trend (Holt)", "smoothing", 6, holt_damped,
         "Level + trend that flattens out. α, β, φ fitted."),
    Spec(M.REGRESSION, "Trend + Fourier regression", "regression", 7, regression,
         "Least-squares line plus seasonal harmonics."),
    Spec(M.HOLT_WINTERS, "Holt-Winters (additive, damped)", "smoothing", 8, holt_winters,
         "Level, damped trend and season. Needs a season of history plus 8 periods."),
    Spec(M.COMBINATION, "Combination (SES + damped + HW)", "ensemble", 9, None,
         "Average of the smoothing models. Combinations are hard to beat (M3/M4)."),
    Spec(M.TIMESFM, "TimesFM (Google foundation model)", "foundation", 10, None,
         "Pretrained transformer, zero-shot. Optional; runs where the engine has it installed."),
]}

COMBINATION_MEMBERS = (M.SES, M.HOLT_DAMPED, M.HOLT_WINTERS)
INTERMITTENT_ONLY = {M.CROSTON, M.SBA, M.TSB}
"""Models reserved for intermittent / lumpy series (and excluded from smooth ones)."""
SMOOTH_ONLY = {M.HOLT_DAMPED, M.HOLT_WINTERS, M.REGRESSION, M.COMBINATION, M.SEASONAL_NAIVE}
"""Models that chase shape. On an intermittent series they fit noise, so they are excluded there."""
