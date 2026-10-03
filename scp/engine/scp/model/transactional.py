"""Transactional data: demand, firm supply in the pipeline, and sales history."""
from __future__ import annotations

import datetime as dt

from pydantic import Field

from .common import DemandKind, Model, ReceiptKind, Ref, Unit
from .promise import Confirmation


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
    price: float | None = Unit(
        "money_per_unit", default=None,
        description="Sales order: the agreed net price per unit, in the company currency. Empty = the customer's "
                    "price, else the product's")
    customer_ref: str = Field("", max_length=64, description="Sales order: the customer's own order number")
    order: str | None = Field(None, max_length=64, description="Sales order: the order header this line is on (empty: "
                                                              "an order of one line, its own header)")
    discount: float = Unit("fraction", lt=1, default=0.0,
                           description="Sales order: the discount its net price already has in it (customer and price "
                                       "discounts together), shown on its documents")
    fulfilled_confirmations: list[Confirmation] = Field(default_factory=list,
        description="Schedule lines removed by deliveries; retained for quantity-based confirmation metrics")
    period_days: int | None = Field(
        None, ge=1, le=366,
        description="Forecast only: the record covers [date, date + period_days) and is spread evenly over the "
                    "working days of that window (PIR splitting). Empty = the whole quantity is due on `date`.")
    released: bool = Field(
        False, description="Forecast only: written by a forecast release. Releasing every series again replaces it, "
                           "so a series the new forecast no longer has does not stay in demand")


class Reservation(Model):
    """What a firm order still has to draw from stock (S/4 RESB / stock-transport requirement): a production
    order's components, or a stock transfer's goods at its shipping location until they are issued."""

    location: str = Ref("location")
    product: str = Ref("product")
    date: dt.date
    qty: float = Unit("qty", description="Still to be issued")
    required_qty: float | None = Unit("qty", default=None,
                                      description="Originally required; empty = `qty` (nothing issued yet)")


class ConfirmedDelivery(Model):
    """One dated quantity the supplier confirmed for an order line (≈ a confirmation line of a PO item)."""

    date: dt.date
    qty: float = Unit("qty", ge=0)


class ScheduledReceipt(Model):
    """Firm supply already committed: open PO, released production order, stock in transit."""

    id: str = Field(min_length=1, max_length=64)
    kind: ReceiptKind
    location: str = Ref("location")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0, description="Still to be received")
    ordered_qty: float | None = Unit("qty", default=None,
                                     description="Originally ordered; empty = `qty` (nothing received yet)")
    delivery_target_qty: float | None = Unit(
        "qty", default=None,
        description="Purchase: total delivery quantity when goods are returned for replacement; "
                    "the original order quantity is retained for history")
    due_date: dt.date
    start_date: dt.date | None = Field(None, description="Production start / shipping date (information; "
                                                         "scheduling releases a production order from here)")
    source: str | None = Field(None, max_length=64, description="Purchasing source, production source or lane id")
    reservations: list[Reservation] = Field(default_factory=list,
                                            description="Components (production) or goods at the origin (transfer) "
                                                        "still to be issued; planning reserves them")
    original_reservations: list[Reservation] = Field(default_factory=list,
        description="Full component targets retained across rolls and reversals")
    step_resources: dict[int, str] = Field(default_factory=dict,
                                           description="Production: steps (by number) to run on one of their alternative "
                                                       "machines instead of their own")
    scheduled: bool = Field(False, description="Dates set by the detailed schedule: when it finishes later than "
                                               "needed, planning counts it where it is needed and reports the delay "
                                               "instead of adding an order in front of it")
    po: str | None = Field(None, max_length=64, description="Purchase: the purchase order (header) this line is on")
    planned_as: str | None = Field(None, max_length=64,
                                   description="The planned order it was firmed from (for reference: planned numbers "
                                               "are handed out again on every plan)")
    price: float | None = Unit("money_per_unit", default=None,
                               description="Purchase: net price per base unit, in the order's currency")
    confirmed_date: dt.date | None = Field(None, description="Purchase: delivery date the supplier confirmed; "
                                                             "planning expects the goods then")
    confirmed_qty: float | None = Unit("qty", default=None,
                                       description="Purchase: quantity the supplier confirmed (of the ordered "
                                                   "quantity); planning counts no more than this")
    confirmations: list[ConfirmedDelivery] = Field(
        default_factory=list,
        description="Purchase: the supplier's confirmation in several deliveries (date and quantity each); "
                    "`confirmed_date` is then the last of them and `confirmed_qty` their total")
    contract: str | None = Field(None, max_length=64, description="Purchase: the contract the line releases against")
    erp_ref: str = Field("", max_length=64, description="Production or transfer: the order's number in the ERP")
    erp_sent: str = Field("", max_length=32, description="Production or transfer: the version of the order the ERP "
                                                        "took last (empty: never)")
    erp_generation: str = Field("", max_length=32, description="Integration lifecycle identifier, assigned when an "
                                                               "order closed by the ERP is restored")

    @property
    def target_qty(self) -> float:
        """Total quantity to receive, retaining any remainder cancelled by a final delivery."""
        if self.delivery_target_qty is not None:
            return self.delivery_target_qty
        return self.ordered_qty if self.ordered_qty is not None else self.qty

    @property
    def expected_date(self) -> dt.date:
        """When the goods are expected: the confirmed date, else the due date."""
        return self.confirmed_date or self.due_date

    @property
    def expected_qty(self) -> float:
        """What is still expected: the open quantity, capped by what the supplier confirmed and has not delivered."""
        if self.confirmed_qty is None:
            return self.qty
        received = self.target_qty - self.qty
        return max(0.0, min(self.qty, self.confirmed_qty - received))

    def expected_parts(self) -> list[tuple[dt.date, float]]:
        """What is still expected and when: one part per confirmation line still to come (what was received is set
        against the earliest lines first), else the expected quantity on the expected date."""
        if not self.confirmations:
            return [(self.expected_date, self.expected_qty)]
        received = self.target_qty - self.qty
        left = self.qty
        out = []
        for c in sorted(self.confirmations, key=lambda c: c.date):
            take = min(max(0.0, c.qty - received), left)
            received = max(0.0, received - c.qty)
            if take > 1e-9:
                out.append((c.date, take))
                left -= take
        return out


class SalesHistory(Model):
    """Long-format history row: one product at one location on one date."""

    location: str = Ref("location")
    product: str = Ref("product")
    date: dt.date
    qty: float = Unit("qty")
    price: float | None = Unit("money_per_unit", default=None)
    promo: bool = False
    period_days: int | None = Field(
        None, ge=1, le=366,
        description="The row is a total over [date, date + period_days), e.g. a month of sales: it is spread evenly "
                    "over those days. Empty = sold on `date`.")
    from_journal: bool = Field(False, description="Written by the roll-forward from sale movements, and rebuilt from "
                                                  "the whole journal on every roll (so a late posting reaches it)")
