"""The S&OP horizon (Enterprise 8.5, N360): S&OP decides presses, shifts and suppliers a year and more ahead, while the
weekly plan looks only as far as ``settings.horizon_days``. With ``sop.horizon_months`` longer than that, the S&OP
plan runs over the longer horizon: the demand inside the weekly plan's horizon is what MRP plans to (the released
forecast and the orders), and beyond it the consensus forecast the Demand page shows, run out to the S&OP horizon on
the same period grid, so no week is counted twice or left out. Nothing is written back: the company keeps its horizon.
"""
from __future__ import annotations

from datetime import timedelta

from ..demand.pipeline import run_forecast
from ..model import Dataset, DemandKind, DemandRecord, Strategy

DAYS_PER_MONTH = 365.0 / 12.0


def sop_days(ds: Dataset) -> int:
    """The S&OP plan's horizon in days: the S&OP horizon when it is longer than the weekly plan's, else the plan's."""
    months = ds.sop.horizon_months
    return max(ds.settings.horizon_days, round(months * DAYS_PER_MONTH)) if months else ds.settings.horizon_days


def extend(ds: Dataset) -> tuple[Dataset, list[str]]:
    """``ds`` over the S&OP horizon, with the forecast beyond the weekly plan's horizon added as demand, and what was
    done in words. ``ds`` itself when the S&OP horizon is not longer."""
    days = sop_days(ds)
    s = ds.settings
    if days <= s.horizon_days:
        return ds, []
    long = ds.model_copy(update={"settings": s.model_copy(update={"horizon_days": days})})
    end = s.planning_start + timedelta(days=s.horizon_days)
    fr = run_forecast(long)
    added: list[DemandRecord] = []
    for ser in fr.series if fr.ok else []:
        lp = ds.demand_lp((ser.location, ser.product)) if ds.location_type(ser.location) is not None else None
        if lp is not None and lp.strategy is Strategy.MTO:   # its customer orders drive it, as release has it
            continue
        for p in ser.forecast:
            if p.end <= end or p.final <= 0:
                continue
            frm = max(p.start, end)
            stop = p.start + timedelta(days=max(1, round(p.share * (p.end - p.start).days)))
            span = (stop - frm).days
            if span <= 0:
                continue
            qty = p.final * span / (p.end - p.start).days
            added.append(DemandRecord(location=ser.location, product=ser.product, date=frm, qty=qty,
                                      kind=DemandKind.FORECAST, period_days=span))
    months = round(days / DAYS_PER_MONTH)
    notes = [f"The S&OP plan looks {months} months ahead, past the weekly plan's {s.horizon_days} days: beyond "
             f"{end.isoformat()} its demand is the statistical and consensus forecast"
             + (f" ({len({(d.location, d.product) for d in added})} series)." if added
                else ", and no series has one there.")]
    return long.model_copy(update={"demand": [*ds.demand, *added]}), notes


__all__ = ["DAYS_PER_MONTH", "extend", "sop_days"]
