"""Execution (blueprint P7): goods movements, firming, roll-forward and the forecast-accuracy loop."""
from __future__ import annotations

from datetime import date

from ..model import Dataset
from .firm import firm_orders
from .result import (
    AccuracyReport, ActualsView, FirmedOrder, FirmReport, OpenOrderRow, RollReport, StockRow,
)
from .roll import roll_forward
from .stock import accuracy_records, accuracy_report, open_orders, stock, stock_rows, unmatched


def actuals_view(ds: Dataset, as_of: date | None = None) -> ActualsView:
    d = as_of or ds.settings.planning_start
    return ActualsView(as_of=d, stock=stock_rows(ds, d), open_orders=open_orders(ds, d),
                       accuracy=accuracy_report(ds.accuracy), movements=len(ds.movements), unmatched=unmatched(ds))


__all__ = [
    "AccuracyReport", "ActualsView", "FirmReport", "FirmedOrder", "OpenOrderRow", "RollReport", "StockRow",
    "accuracy_records", "accuracy_report", "actuals_view", "firm_orders", "open_orders", "roll_forward", "stock",
    "stock_rows",
]
