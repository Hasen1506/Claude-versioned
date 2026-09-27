"""Execution (blueprint P7): goods movements, firming, roll-forward and the forecast-accuracy loop."""
from __future__ import annotations

from datetime import date

from ..model import Dataset
from .firm import firm_orders
from .post import PostingError, count_stock, post, receive, ship
from .result import (
    AccuracyReport, ActualsView, FirmedOrder, FirmReport, OpenOrderRow, RollReport, StockRow, Unbooked,
)
from .roll import roll_forward
from .stock import accuracy_records, accuracy_report, open_orders, pending_openings, stock, stock_rows, unmatched


def unbooked(ds: Dataset) -> Unbooked:
    """What re-rolling to the current planning start would change (Q15: a late posting shows, and offers the fix)."""
    start = ds.settings.planning_start
    new, rep = roll_forward(ds, start)
    acc = {(a.location, a.product, a.start): a.actual for a in ds.accuracy}
    weeks = {a.start for a in new.accuracy if abs(acc.get((a.location, a.product, a.start), 0.0) - a.actual) > 1e-6}
    was = {(c.kind, c.id): c.delivered_qty for c in ds.closed_orders}
    closed = sum(1 for c in new.closed_orders if (c.kind, c.id) in was and abs(was[(c.kind, c.id)] - c.delivered_qty) > 1e-6)
    orders = sum(1 for o in rep.orders if o.closed or abs(o.open_before - o.open_after) > 1e-6)
    out = Unbooked(needed=False, movements=sum(1 for m in ds.movements if m.date < start), stock=len(rep.stock),
                   orders=orders, accuracy_weeks=len(weeks), history_days=rep.history_added, closed=closed)
    out.needed = bool(out.stock or out.orders or out.accuracy_weeks or out.history_days or out.closed)
    return out


def actuals_view(ds: Dataset, as_of: date | None = None) -> ActualsView:
    d = as_of or ds.settings.planning_start
    return ActualsView(as_of=d, stock=stock_rows(ds, d), open_orders=open_orders(ds, d),
                       accuracy=accuracy_report(ds.accuracy), movements=len(ds.movements), unmatched=unmatched(ds),
                       unbooked=unbooked(ds) if d == ds.settings.planning_start else None)


__all__ = [
    "AccuracyReport", "ActualsView", "FirmReport", "FirmedOrder", "OpenOrderRow", "PostingError", "RollReport",
    "StockRow", "accuracy_records", "accuracy_report", "actuals_view", "count_stock", "firm_orders", "open_orders",
    "pending_openings", "post", "receive", "roll_forward", "ship", "stock", "stock_rows", "unbooked",
]
