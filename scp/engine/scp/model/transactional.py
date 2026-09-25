"""Transactional data: demand, firm supply in the pipeline, and sales history."""
from __future__ import annotations

import datetime as dt

from pydantic import Field

from .common import DemandKind, Model, ReceiptKind, Ref, Unit


class DemandRecord(Model):
    """A forecast bucket (≈ PIR) or a firm sales-order schedule line (≈ VBBE)."""

    id: str | None = Field(None, max_length=64)
    location: str = Ref("location", description="Customer or stocking location where demand occurs")
    product: str = Ref("product")
    date: dt.date
    qty: float = Unit("qty")
    kind: DemandKind = DemandKind.FORECAST
    priority: int = Field(5, ge=1, le=9, description="1 = highest; used by promising and constrained plans")
    period_days: int | None = Field(
        None, ge=1, le=366,
        description="Forecast only: the record covers [date, date + period_days) and is spread evenly over the "
                    "working days of that window (PIR splitting). Empty = the whole quantity is due on `date`.")


class ScheduledReceipt(Model):
    """Firm supply already committed: open PO, released production order, stock in transit."""

    id: str = Field(min_length=1, max_length=64)
    kind: ReceiptKind
    location: str = Ref("location")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    due_date: dt.date
    source: str | None = Field(None, max_length=64, description="Supplier, source or lane id (information)")


class SalesHistory(Model):
    """Long-format history row: one product at one location on one date."""

    location: str = Ref("location")
    product: str = Ref("product")
    date: dt.date
    qty: float = Unit("qty")
    price: float | None = Unit("money_per_unit", default=None)
    promo: bool = False
