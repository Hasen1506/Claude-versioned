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
    complete_delivery: bool = Field(False, description="Sales order: confirm only the full quantity on one date")
    ordered_qty: float | None = Unit(
        "qty", default=None,
        description="Sales order: the originally ordered quantity; `qty` is what is still open. Set by the roll-forward "
                    "on the first delivery (empty = nothing delivered yet)")
    period_days: int | None = Field(
        None, ge=1, le=366,
        description="Forecast only: the record covers [date, date + period_days) and is spread evenly over the "
                    "working days of that window (PIR splitting). Empty = the whole quantity is due on `date`.")


class Reservation(Model):
    """What a firm order still has to draw from stock (S/4 RESB / stock-transport requirement): a production
    order's components, or a stock transfer's goods at its shipping location until they are issued."""

    location: str = Ref("location")
    product: str = Ref("product")
    date: dt.date
    qty: float = Unit("qty", description="Still to be issued")
    required_qty: float | None = Unit("qty", default=None,
                                      description="Originally required; empty = `qty` (nothing issued yet)")


class ScheduledReceipt(Model):
    """Firm supply already committed: open PO, released production order, stock in transit."""

    id: str = Field(min_length=1, max_length=64)
    kind: ReceiptKind
    location: str = Ref("location")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0, description="Still to be received")
    ordered_qty: float | None = Unit("qty", default=None,
                                     description="Originally ordered; empty = `qty` (nothing received yet)")
    due_date: dt.date
    start_date: dt.date | None = Field(None, description="Production start / shipping date (information; "
                                                         "scheduling releases a production order from here)")
    source: str | None = Field(None, max_length=64, description="Purchasing source, production source or lane id")
    reservations: list[Reservation] = Field(default_factory=list,
                                            description="Components (production) or goods at the origin (transfer) "
                                                        "still to be issued; planning reserves them")


class SalesHistory(Model):
    """Long-format history row: one product at one location on one date."""

    location: str = Ref("location")
    product: str = Ref("product")
    date: dt.date
    qty: float = Unit("qty")
    price: float | None = Unit("money_per_unit", default=None)
    promo: bool = False
