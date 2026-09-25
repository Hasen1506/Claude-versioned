"""Model competition: rolling-origin backtest, accuracy metrics and champion selection.

For each series, every eligible candidate forecasts ``H`` periods from each of ``K`` rolling
origins (the last K positions that leave H periods of actuals). Errors are pooled over all
(origin, step) pairs:

* MAE, RMSE
* MASE = MAE / mean |y_t − y_{t−1}| over the whole history (scale-free, Hyndman & Koehler 2006)
* WAPE = Σ|f − a| / Σa
* bias = Σ(f − a) / Σa (positive = over-forecast)

The champion minimises the chosen metric; an exact tie goes to the simpler model. The champion is
refitted on the full history for the future forecast. Its error spread per step (RMSE at step h,
growing with √h beyond the backtest horizon) gives the prediction interval and σ for safety stock.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..model import ForecastModelId as M
from ..model import SelectionMetric
from .models import COMBINATION_MEMBERS, SPECS, Infeasible

# (training_length, horizon) -> the foundation model's forecast for this series from that origin,
# computed beforehand in one batch (see pipeline._foundation_batches)
FoundationPreds = dict[tuple[int, int], np.ndarray]


@dataclass
class Score:
    model: M
    eligible: bool
    reason: str = ""
    mae: float | None = None
    rmse: float | None = None
    mase: float | None = None
    wape: float | None = None
    bias: float | None = None
    step_rmse: list[float] = field(default_factory=list)
    backtest: list[tuple[int, int, float, float]] = field(default_factory=list)  # origin, step, actual, fc

    def metric(self, m: SelectionMetric) -> float:
        v = {SelectionMetric.MASE: self.mase, SelectionMetric.WAPE: self.wape, SelectionMetric.RMSE: self.rmse}[m]
        return float("inf") if v is None else v


@dataclass
class Outcome:
    scores: list[Score]
    champion: M | None
    forecast: np.ndarray            # champion, full history, length h
    sigma: np.ndarray               # error spread per future step
    naive_wape: float | None


def mase_scale(y: np.ndarray) -> float:
    if len(y) >= 2:
        s = float(np.abs(np.diff(y)).mean())
        if s > 0:
            return s
    s = float(np.abs(y).mean()) if len(y) else 0.0
    return s if s > 0 else 1.0


def origins(n: int, k: int, h: int, m: int = 1) -> tuple[list[int], int]:
    """Training lengths of the backtest origins and the effective horizon.

    Origins are spread evenly over the most recent season (stride ≈ m / k) when the history allows,
    so the backtest sees the seasonal turns and not just the last few quiet periods. The horizon is
    shortened (never below one period) when the history is short.
    """
    min_train = max(2, min(n - 1, 4))
    h_eff = min(h, n - min_train)
    if h_eff < 1:
        return [], 0
    last = n - h_eff
    room = last - min_train          # how far back the earliest origin can go
    stride = max(1, min(m, room + 1) // k) if k > 1 else 1
    out = [last - i * stride for i in range(k) if last - i * stride >= min_train]
    return sorted(out), h_eff


def _predict(model: M, y: np.ndarray, h: int, m: int, cache: dict[M, np.ndarray],
             foundation: FoundationPreds | None) -> np.ndarray:
    if model is M.COMBINATION:
        members = [cache[x] for x in COMBINATION_MEMBERS if x in cache]
        if len(members) < 2:
            raise Infeasible("needs at least two of SES, damped trend and Holt-Winters")
        return np.mean(members, axis=0)
    if model is M.TIMESFM:
        f = foundation.get((len(y), h)) if foundation else None
        if f is None:
            raise Infeasible("not available on this engine")
        return f
    fn = SPECS[model].fn
    assert fn is not None
    return fn(y, h, m)


def _run_all(models: list[M], y: np.ndarray, h: int, m: int,
             foundation: FoundationPreds | None) -> tuple[dict[M, np.ndarray], dict[M, str]]:
    """Forecast with every model; combination last so its members are in the cache."""
    out: dict[M, np.ndarray] = {}
    why: dict[M, str] = {}
    for model in sorted(models, key=lambda x: x is M.COMBINATION):
        try:
            out[model] = _predict(model, y, h, m, out, foundation)
        except Infeasible as e:
            why[model] = str(e)
    return out, why


def compete(y: np.ndarray, horizon: int, m: int, candidates: list[M], *, k: int, h: int,
            metric: SelectionMetric, foundation: FoundationPreds | None = None) -> Outcome:
    n = len(y)
    starts, h_eff = origins(n, k, h, m)
    scale = mase_scale(y)
    scores: dict[M, Score] = {c: Score(c, True) for c in candidates}
    errs: dict[M, list[tuple[int, int, float, float]]] = {c: [] for c in candidates}
    for o in starts:
        preds, why = _run_all(candidates, y[:o], h_eff, m, foundation)
        actual = y[o:o + h_eff]
        for c in candidates:
            if not scores[c].eligible:
                continue
            if c not in preds:
                scores[c].eligible = False
                scores[c].reason = why.get(c, "not feasible")
                continue
            for s, (a, f) in enumerate(zip(actual, preds[c], strict=True), start=1):
                errs[c].append((o, s, float(a), float(f)))
    if not starts:
        for c in candidates:
            scores[c].eligible = False
            scores[c].reason = "history too short for a backtest"
    for c, sc in scores.items():
        if not sc.eligible:
            continue
        e = errs[c]
        a = np.array([x[2] for x in e])
        f = np.array([x[3] for x in e])
        d = f - a
        sc.mae = float(np.abs(d).mean())
        sc.rmse = float(np.sqrt((d ** 2).mean()))
        sc.mase = sc.mae / scale
        tot = float(a.sum())
        sc.wape = float(np.abs(d).sum() / tot) if tot > 0 else (0.0 if sc.mae == 0 else None)
        sc.bias = float(d.sum() / tot) if tot > 0 else None
        steps = np.array([x[1] for x in e])
        sc.step_rmse = [float(np.sqrt((d[steps == s] ** 2).mean())) for s in range(1, h_eff + 1)]
        sc.backtest = e
    ranked = sorted((s for s in scores.values() if s.eligible),
                    key=lambda s: (round(s.metric(metric), 9), SPECS[s.model].complexity))
    champion = ranked[0].model if ranked else None
    naive_wape = scores[M.NAIVE].wape if M.NAIVE in scores and scores[M.NAIVE].eligible else None

    if champion is not None:
        full, _ = _run_all([x for x in candidates if x in (champion, *COMBINATION_MEMBERS)] if champion is M.COMBINATION
                           else [champion], y, horizon, m, foundation)
        forecast = full[champion]
        sigma = _sigma(scores[champion].step_rmse, horizon)
    else:
        forecast = np.full(horizon, float(y.mean()) if n else 0.0)
        sd = float(y.std()) if n > 1 else float(forecast[0]) * 0.5
        sigma = np.full(horizon, sd)
    return Outcome(list(scores.values()), champion, forecast, sigma, naive_wape)


def _sigma(step_rmse: list[float], horizon: int) -> np.ndarray:
    if not step_rmse:
        return np.zeros(horizon)
    h_eff = len(step_rmse)
    out = np.empty(horizon)
    for i in range(horizon):
        out[i] = step_rmse[i] if i < h_eff else step_rmse[-1] * np.sqrt((i + 1) / h_eff)
    return out
