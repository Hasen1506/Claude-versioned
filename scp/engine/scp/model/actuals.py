"""Execution data (blueprint P7): the goods-movement journal and the logs the roll-forward writes.

Stock is never typed in once movements exist: on-hand at a node is the sum of its movements before the
planning start (an S/4 MATDOC projection). Firm orders keep their original quantity next to what is
still open, so rolling forward is idempotent — re-running it with the same journal changes nothing.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import Field, model_validator

from .common import Id, Model, Ref, Unit


class MovementType(str, Enum):
    OPENING = "opening"              # + opening balance / stock take at go-live
    RECEIPT = "receipt"              # + goods receipt of a PO, production order or arriving transfer (reference = receipt)
    ISSUE = "issue"                  # − component issue to a production order (reference = receipt)
    SALE = "sale"                    # − goods issue to a customer (reference = sales order)
    TRANSFER_OUT = "transfer_out"    # − goods issue of a stock transfer (reference = the transfer receipt)
    SCRAP = "scrap"                  # −
    ADJUSTMENT = "adjustment"        # ± inventory count difference (signed quantity)


SIGN: dict[MovementType, float] = {
    MovementType.OPENING: 1.0, MovementType.RECEIPT: 1.0, MovementType.ISSUE: -1.0, MovementType.SALE: -1.0,
    MovementType.TRANSFER_OUT: -1.0, MovementType.SCRAP: -1.0, MovementType.ADJUSTMENT: 1.0,
}


class GoodsMovement(Model):
    id: Id
    date: dt.date
    type: MovementType
    location: str = Ref("location", description="Stocking location whose stock changes")
    product: str = Ref("product")
    qty: float = Unit("qty", ge=None, description="Positive; signed only for adjustments")
    reference: str | None = Field(None, max_length=64, description="Receipt or sales order id")
    counterparty: str | None = Ref("location", default=None, description="Customer (sale) or supplier (receipt)")
    final: bool = Field(False, description="Delivery completed: closes the referenced order even if short")
    note: str = Field("", max_length=200)

    @model_validator(mode="after")
    def _qty(self) -> GoodsMovement:
        if self.type is MovementType.ADJUSTMENT:
            if self.qty == 0:
                raise ValueError("an adjustment needs a non-zero quantity")
        elif self.qty <= 0:
            raise ValueError(f"a {self.type.value} movement needs a positive quantity")
        return self

    @property
    def signed(self) -> float:
        return SIGN[self.type] * self.qty


class ClosedOrder(Model):
    """A completed order, logged by the roll-forward: the source of OTIF and supplier reliability."""

    kind: str = Field(pattern=r"^(sales|purchase|production|transfer)$")
    id: str = Field(min_length=1, max_length=64)
    location: str = Ref("location", description="Customer (sales) or receiving location")
    product: str = Ref("product")
    counterparty: str | None = Field(None, max_length=64, description="Shipping location, supplier or source")
    ordered_qty: float = Unit("qty")
    delivered_qty: float = Unit("qty")
    due_date: dt.date = Field(description="Requested date (sales) or due date (receipts)")
    promised_date: dt.date | None = Field(None, description="Sales: last confirmed date, if it was confirmed")
    first_delivery: dt.date | None = None
    last_delivery: dt.date | None = None
    closed_on: dt.date
    po: str | None = Field(None, max_length=64, description="Purchase: the purchase order the line was on")
    price: float | None = Unit("money_per_unit", default=None, description="Purchase: net price per unit")
    confirmed_date: dt.date | None = Field(None, description="Purchase: the date the supplier confirmed, if any")


class AccuracyRecord(Model):
    """Forecast against actual sales for one series over one elapsed week (written by the roll-forward)."""

    location: str = Ref("location")
    product: str = Ref("product")
    start: dt.date
    end: dt.date = Field(description="Exclusive")
    forecast: float = Unit("qty")
    actual: float = Unit("qty")


class RolledWeek(Model):
    """A week the roll-forward closed (written by the roll). Its accuracy is logged per series that had forecast or
    sales, and re-read on every later roll, so a sale posted late for it still counts, even in a week that logged
    nothing at the time."""

    start: dt.date
    end: dt.date = Field(description="Exclusive")


class ExecutionSettings(Model):
    firm_zone_days: int = Field(14, ge=0, le=366, description="Firming converts planned orders starting within this "
                                                               "many days of the planning start")
    delivery_tolerance: float = Unit("fraction", le=0.5, default=0.02,
                                     description="Under-delivery still counted as in full, and that closes an order")
