"""Execution data (blueprint P7): the goods-movement journal and the logs the roll-forward writes.

Stock is never typed in once movements exist: on-hand at a node is the sum of its movements before the
planning start (an S/4 MATDOC projection). Stock entered at setup at a node with no earlier movement is its opening
balance; the roll-forward writes it into the journal, and a count posts an opening balance or a count difference. Firm orders keep their original quantity next to what is
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
    STATUS = "status"                # ± stock moved between stock types or batches at one place (signed; the pair
                                     #   posted together sums to zero: release from inspection, block, unblock)


SIGN: dict[MovementType, float] = {
    MovementType.OPENING: 1.0, MovementType.RECEIPT: 1.0, MovementType.ISSUE: -1.0, MovementType.SALE: -1.0,
    MovementType.TRANSFER_OUT: -1.0, MovementType.SCRAP: -1.0, MovementType.ADJUSTMENT: 1.0, MovementType.STATUS: 1.0,
}
SIGNED = {MovementType.ADJUSTMENT, MovementType.STATUS}


class StockType(str, Enum):
    """What stock may be used for (≈ SAP's stock types). Only unrestricted stock is issued, sold or shipped; stock in
    quality inspection counts in planning when the company says so (as SAP's MRP does by default); blocked stock never."""

    UNRESTRICTED = "unrestricted"
    QUALITY = "quality"              # in quality inspection: received, not yet released
    BLOCKED = "blocked"              # held back: damaged, recalled, waiting for a decision


class Batch(Model):
    """A batch of a product (≈ a batch master record): made or received together, with one expiry date. Stock of a
    batch-managed product is kept by batch; issues take the batch that expires first (first expiring, first out)."""

    product: str = Ref("product")
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
                    description="Batch number, unique per product")
    made_on: dt.date | None = Field(None, description="Made or received")
    expires_on: dt.date | None = Field(None, description="Last day it may be used, sold or shipped")
    supplier_batch: str = Field("", max_length=40, description="The supplier's own batch number")
    note: str = Field("", max_length=200)


class NegativeStock(str, Enum):
    """What happens when a posting would take stock below zero (R17)."""

    REFUSE = "refuse"                # the posting is refused: post the missing receipt or a count first
    ALLOW = "allow"                  # posted; the place shows as needing a count, and the plan starts from zero
    FOUND = "found"                  # posted; the week's roll counts the missing stock as found (a count difference)


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
    batch: str | None = Field(None, max_length=40, description="The batch moved (batch-managed products)")
    stock_type: StockType = Field(StockType.UNRESTRICTED, description="The stock the quantity comes from or goes to")
    doc: str | None = Field(None, max_length=20, description="Material document: the movements posted together")
    reversal_of: str | None = Field(None, max_length=64, description="The movement this one takes back: its "
                                                                        "quantity counts with the opposite sign")
    serials: list[str] = Field(default_factory=list, max_length=10000,
                               description="Serial numbers moved (serialised products: one per unit)")

    @model_validator(mode="after")
    def _qty(self) -> GoodsMovement:
        if self.type in SIGNED:
            if self.qty == 0:
                raise ValueError(f"a {'count difference' if self.type is MovementType.ADJUSTMENT else 'stock change'} "
                                 "needs a non-zero quantity")
        elif self.qty <= 0:
            raise ValueError(f"a {self.type.value} movement needs a positive quantity")
        if self.serials and len(set(self.serials)) != len(self.serials):
            raise ValueError("a serial number is listed twice")
        return self

    @property
    def net(self) -> float:
        """The quantity as it counts: a reversal takes its quantity back."""
        return -self.qty if self.reversal_of else self.qty

    @property
    def signed(self) -> float:
        return SIGN[self.type] * self.net


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
    cancelled: bool = Field(False, description="Sales: cancelled before it was delivered in full; what was delivered "
                                               "is `delivered_qty`, and only that counts in OTIF")
    source_order: dict | None = Field(None, description="Original order retained so a reversed delivery can reopen it")
    source_confirmations: list[dict] = Field(default_factory=list)
    confirmed_on_time_qty: float | None = Unit("qty", default=None)


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


class CountItem(Model):
    location: str = Ref("location")
    product: str = Ref("product")
    batch: str | None = Field(None, max_length=40)
    stock_type: StockType = StockType.UNRESTRICTED
    book_qty: float = Unit("qty", ge=None, description="The journal's stock when the document was made (frozen)")
    counted: float | None = Unit("qty", default=None, description="What was found; empty until counted")


class InventoryDoc(Model):
    """A physical inventory document (≈ MI01/MI04/MI07): places and products to count on a day, their book stock
    frozen when the document is made, the counts entered, and the differences posted against the frozen stock.
    With ``block``, postings for its places and products are refused until it is posted or cancelled."""

    id: str = Field(min_length=1, max_length=20)
    date: dt.date = Field(description="Count date: the differences are posted at the end of this day")
    status: str = Field("open", pattern=r"^(open|posted|cancelled)$")
    block: bool = Field(False, description="Refuse postings for these places and products while open")
    items: list[CountItem] = Field(default_factory=list)
    note: str = Field("", max_length=200)
    posted_doc: str | None = Field(None, max_length=20, description="The material document of the differences")


class ExecutionSettings(Model):
    firm_zone_days: int = Field(14, ge=0, le=366, description="Firming converts planned orders starting within this "
                                                               "many days of the planning start")
    delivery_tolerance: float = Unit("fraction", le=0.5, default=0.02,
                                     description="Under-delivery still counted as in full, and that closes an order")
    negative_stock: NegativeStock = Field(NegativeStock.ALLOW, description="A posting that takes stock below zero: "
                                          "refuse it, allow it and ask for a count, or count the missing stock as found")
    quality_in_planning: bool = Field(True, description="Stock in quality inspection counts as available in planning")
