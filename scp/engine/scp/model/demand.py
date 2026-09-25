"""Demand-planning inputs: forecast settings, demand events, new-product rules and consensus overrides.

Sales history itself is :class:`~scp.model.transactional.SalesHistory`. The statistical forecast is
computed, never stored; what is stored is what a planner decides (events, NPI rules, overrides) and,
after release, the resulting forecast :class:`~scp.model.transactional.DemandRecord` rows.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import Field, model_validator

from .common import Id, Model, Ref, Unit


class ForecastPeriod(str, Enum):
    WEEK = "week"
    MONTH = "month"


class ForecastModelId(str, Enum):
    """Models entered into the forecast competition. See ``scp.demand.models``."""

    NAIVE = "naive"
    SEASONAL_NAIVE = "seasonal_naive"
    MOVING_AVERAGE = "moving_average"
    SES = "ses"
    HOLT_DAMPED = "holt_damped"
    HOLT_WINTERS = "holt_winters"
    CROSTON = "croston"
    SBA = "sba"
    TSB = "tsb"
    REGRESSION = "regression"
    COMBINATION = "combination"
    TIMESFM = "timesfm"


DEFAULT_MODELS = [m for m in ForecastModelId if m is not ForecastModelId.TIMESFM]


class SelectionMetric(str, Enum):
    MASE = "mase"
    WAPE = "wape"
    RMSE = "rmse"


class OutlierMethod(str, Enum):
    NONE = "none"
    MAD = "mad"


class ForecastSettings(Model):
    """How the statistical forecast is built and chosen (S/4 guide §4: IBP Demand)."""

    period: ForecastPeriod = Field(ForecastPeriod.WEEK, description="Time grain of history and forecast")
    season_length: int | None = Field(
        None, ge=2, le=53, description="Periods per seasonal cycle; empty = 52 for weeks, 12 for months")
    models: list[ForecastModelId] = Field(
        default_factory=lambda: list(DEFAULT_MODELS),
        description="Candidate models. TimesFM is only used when the engine has it installed.")
    selection_metric: SelectionMetric = SelectionMetric.MASE
    backtest_origins: int = Field(6, ge=1, le=26, description="Rolling forecast origins in the backtest")
    backtest_horizon: int = Field(
        4, ge=1, le=26, description="Periods forecast from each origin; match it to the replenishment lead time")
    min_history_periods: int = Field(
        8, ge=2, le=104, description="Series shorter than this skip the competition and use a simple average")
    outlier_method: OutlierMethod = OutlierMethod.MAD
    outlier_threshold: float = Field(
        4.0, gt=0, le=20, description="Robust z-score (median / MAD) beyond which a value is clipped")
    abc_a: float = Unit("fraction", gt=0, le=1, default=0.8,
                        description="Cumulative revenue share that closes class A")
    abc_b: float = Unit("fraction", gt=0, le=1, default=0.95,
                        description="Cumulative revenue share that closes class B")
    xyz_x: float = Unit("ratio", gt=0, default=0.5, description="Forecast-error CV that closes class X")
    xyz_y: float = Unit("ratio", gt=0, default=1.0, description="Forecast-error CV that closes class Y")
    interval: float = Unit("fraction", gt=0.5, lt=1, default=0.8,
                           description="Central prediction interval shown with the forecast (0.8 = P10–P90)")

    @model_validator(mode="after")
    def _ordered(self) -> ForecastSettings:
        if self.abc_a >= self.abc_b:
            raise ValueError("abc_a must be below abc_b")
        if self.xyz_x >= self.xyz_y:
            raise ValueError("xyz_x must be below xyz_y")
        if not self.models:
            raise ValueError("choose at least one forecast model")
        return self


class EventKind(str, Enum):
    PROMO = "promo"
    PRICE_CHANGE = "price_change"
    LAUNCH = "launch"
    COMPETITOR = "competitor"
    STORE_OPENING = "store_opening"
    DISRUPTION = "disruption"
    OTHER = "other"


class DemandEvent(Model):
    """Something that moves demand for a period: a promotion, a price change, a competitor launch…

    Past events mark the history they affected, so the baseline is cleansed of them and their lift
    is measured. Future events multiply the baseline forecast by ``1 + lift``. Leave ``lift`` empty
    on a future event to use the lift measured on past events of the same kind.
    """

    id: Id
    name: str = Field("", max_length=120)
    kind: EventKind = EventKind.PROMO
    products: list[str] = Field(default_factory=list, json_schema_extra={"x-ref": "product"},
                                description="Empty = every product")
    locations: list[str] = Field(default_factory=list, json_schema_extra={"x-ref": "location"},
                                 description="Empty = every location")
    start: dt.date
    end: dt.date = Field(description="Last day of the event (inclusive)")
    lift: float | None = Unit("fraction", ge=-1, le=20, default=None,
                              description="Demand change while the event runs: 0.3 = +30 %, −0.2 = −20 %")

    @model_validator(mode="after")
    def _dates(self) -> DemandEvent:
        if self.end < self.start:
            raise ValueError("end must be on or after start")
        return self

    def applies(self, location: str, product: str) -> bool:
        return (not self.products or product in self.products) and (not self.locations or location in self.locations)


class NpiRule(Model):
    """New product introduction: forecast a product without history from a like product."""

    location: str = Ref("location", description="Where the new product sells")
    product: str = Ref("product", description="The new product")
    like_product: str = Ref("product", description="Existing product whose demand shape it follows")
    like_location: str | None = Ref("location", default=None, description="Empty = the same location")
    scale: float = Unit("fraction", gt=0, le=20, default=1.0, description="Share of the like product's volume")
    launch_date: dt.date
    ramp_periods: int = Field(4, ge=0, le=52, description="Periods to ramp linearly from 0 to full volume")
    cannibalisation: float = Unit(
        "fraction", le=1, default=0.0,
        description="Share of the new volume taken from the like product (its forecast is reduced)")


class ForecastOverride(Model):
    """A consensus adjustment for one period: an absolute quantity or a relative change."""

    location: str = Ref("location")
    product: str = Ref("product")
    date: dt.date = Field(description="Any date inside the forecast period to adjust")
    qty: float | None = Unit("qty", default=None, description="Final quantity for the period")
    change: float | None = Unit("fraction", ge=-1, le=20, default=None,
                                description="Relative change to the statistical forecast: 0.1 = +10 %")
    reason: str = Field("", max_length=200)
    author: str = Field("", max_length=80)

    @model_validator(mode="after")
    def _one(self) -> ForecastOverride:
        if (self.qty is None) == (self.change is None):
            raise ValueError("set exactly one of qty or change")
        return self
