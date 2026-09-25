"""Forecast output schema: everything the Demand workspace shows, with its derivation."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from ..model import ForecastModelId
from ..model.common import Out
from ..validate import Issue

Abc = Literal["A", "B", "C"]
Xyz = Literal["X", "Y", "Z"]
Pattern = Literal["smooth", "erratic", "intermittent", "lumpy", "none"]
Lifecycle = Literal["new", "mature", "inactive", "npi"]
Flag = Literal["event", "outlier"]


class HistoryPoint(Out):
    start: dt.date
    label: str
    raw: float
    cleaned: float
    flag: Flag | None = None
    events: list[str] = []


class ModelScore(Out):
    model: ForecastModelId
    label: str
    family: str
    eligible: bool
    reason: str = ""
    mae: float | None = None
    rmse: float | None = None
    mase: float | None = None
    wape: float | None = None
    bias: float | None = None
    rank: int | None = None


class BacktestPoint(Out):
    origin: int          # index of the first forecast period in the history
    step: int            # 1 = one period ahead
    start: dt.date
    actual: float
    forecast: float


class ForecastPoint(Out):
    start: dt.date
    end: dt.date
    label: str
    share: float                 # part of the period inside the horizon (partial first/last period)
    statistical: float           # champion model (or NPI curve) for the whole period
    event_factor: float = 1.0
    events: list[str] = []
    cannibalised: float = 0.0    # volume taken by an NPI product that follows this one
    override: float | None = None
    override_reason: str = ""
    final: float                 # consensus value for the whole period
    lower: float
    upper: float
    released_qty: float          # final × share: what release writes as the forecast demand


class Segment(Out):
    abc: Abc
    xyz: Xyz
    pattern: Pattern
    lifecycle: Lifecycle
    revenue: float
    revenue_share: float
    adi: float | None = None     # average demand interval (periods)
    cv2: float | None = None     # squared CV of non-zero demand sizes
    error_cv: float | None = None
    suggested_service_level: float


class Series(Out):
    key: str
    location: str
    product: str
    segment: Segment
    history: list[HistoryPoint]
    leaderboard: list[ModelScore]
    champion: ForecastModelId | None = None
    champion_label: str = ""
    fva: float | None = None     # naïve WAPE − champion WAPE (points of WAPE the model adds)
    backtest: list[BacktestPoint] = []
    forecast: list[ForecastPoint]
    lifts: dict[str, float] = {}             # measured lift per event kind on this history
    sigma_one_step: float | None = None      # RMSE of 1-period-ahead backtest errors
    demand_cv_weekly: float | None = None    # → SafetyStockPolicy.demand_cv
    notes: list[str] = []


class FoundationStatus(Out):
    enabled: bool
    available: bool
    model: str
    license: str
    detail: str


class Summary(Out):
    series: int
    wape: float | None = None          # volume-weighted across series (champion backtests)
    bias: float | None = None
    fva: float | None = None           # naïve WAPE − champion WAPE, volume-weighted
    champions: dict[str, int] = {}
    abc: dict[str, int] = {}
    patterns: dict[str, int] = {}
    total_final: float = 0.0


class ForecastResult(Out):
    ok: bool
    period: Literal["week", "month"]
    season_length: int
    periods: list[str]                 # labels of the forecast periods
    issues: list[Issue]
    series: list[Series]
    summary: Summary
    foundation: FoundationStatus


class CvSuggestion(Out):
    location: str
    product: str
    current: float | None
    suggested: float


class ReleaseResult(Out):
    records: int
    series: int
    replaced: int
    cv_suggestions: list[CvSuggestion]
