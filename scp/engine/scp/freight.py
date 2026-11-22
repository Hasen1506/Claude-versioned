"""Posted carrier bills shared by the journal, payable worklist and cash forecast."""
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from pydantic import computed_field

from .model import Dataset, FreightOrder, Payment
from .model.common import Out
from .model.transport import CarrierBankMatch, CarrierBillAdjustment, CarrierRefund, FreightBillEvent, FreightLandedCost


def freight_company(ds: Dataset, order: FreightOrder) -> str:
    return ds.entity_at(order.ship_to if order.purchases else order.ship_from)


class CarrierBill(Out):
    voucher: str
    order: str
    carrier: str
    name: str
    company: str
    reference: str
    date: date
    due_on: date
    amount: float
    credited_on: date | None = None
    credit_reference: str = ""
    payments: list[Payment]
    events: list[FreightBillEvent] = []
    statement_vouchers: list[str] = []

    def open_at(self, through: date) -> float:
        if self.date > through or (self.credited_on and self.credited_on <= through):
            return 0.0
        paid = sum(round(p.amount * 100) for p in self.payments if p.date <= through)
        credit = sum(e.amount_minor for e in self.events if isinstance(e, CarrierBillAdjustment) and e.date <= through)
        refunded = sum(e.amount_minor for e in self.events if isinstance(e, CarrierRefund) and e.date <= through)
        return (round(self.amount * 100) - paid - credit + refunded) / 100

    @computed_field
    @property
    def open(self) -> float:
        return self.open_at(date.max)

    @computed_field
    @property
    def status(self) -> Literal["to pay", "paid", "credited", "refund due", "refunded"]:
        if self.credited_on:
            return "credited"
        if self.open:
            return "refund due" if self.open < 0 else "to pay"
        if any(isinstance(e, CarrierRefund) for e in self.events):
            return "refunded"
        if not self.payments and any(isinstance(e, CarrierBillAdjustment) for e in self.events):
            return "credited"
        return "paid"

    def cash(self) -> Iterator[tuple[str, date, str, int]]:
        for index, payment in enumerate(self.payments, 1):
            yield f"{self.voucher}/P-{index}", payment.date, payment.reference, -round(payment.amount * 100)
        for index, event in enumerate(self.events, 1):
            if isinstance(event, CarrierRefund):
                yield f"{self.voucher}/R-{index}", event.date, event.reference, event.amount_minor

    @computed_field
    @property
    def unreconciled_cash(self) -> list[str]:
        matched = set(active_bank_matches(self.events)) | set(self.statement_vouchers)
        return [voucher for voucher, _, _, _ in self.cash() if voucher not in matched]


def bills_for_order(ds: Dataset, order: FreightOrder, statement_vouchers: list[str] | None = None) -> Iterator[CarrierBill]:
    carrier = ds.carrier_by_id.get(order.carrier or "")
    days = timedelta(days=carrier.payment_days if carrier else 0)
    identity = dict(order=order.id, carrier=order.carrier or "", company=freight_company(ds, order),
                    name=(carrier.name or carrier.id) if carrier else order.carrier or "Unassigned carrier")
    for index, credit in enumerate(order.bill_credits):
        yield CarrierBill(**identity, voucher=order.bill_voucher(index), reference=credit.bill, date=credit.settled_on,
                          due_on=credit.due_on or credit.settled_on + days, amount=round(credit.billed, 2),
                          credited_on=credit.date, credit_reference=credit.reference, payments=[])
    if order.status == "settled" and order.billed is not None and order.settled_on is not None:
        yield CarrierBill(**identity, voucher=order.bill_voucher(), reference=order.bill, date=order.settled_on,
                          due_on=order.bill_due_on or order.settled_on + days, amount=round(order.billed, 2),
                          payments=order.bill_payments, events=order.bill_events, statement_vouchers=statement_vouchers or [])


def carrier_bills(ds: Dataset) -> Iterator[CarrierBill]:
    claimed: dict[str, list[str]] = defaultdict(list)
    for line in ds.carrier_bank_lines:
        for target in line.active:
            claimed[target.order].append(target.voucher)
    for order in ds.freight_orders:
        yield from bills_for_order(ds, order, claimed.get(order.id))


def active_landed(order: FreightOrder) -> Iterator[tuple[int, FreightLandedCost]]:
    reversed_indices = {e.reverses for e in order.bill_events if isinstance(e, FreightLandedCost) and e.reverses}
    for index, event in enumerate(order.bill_events, 1):
        if isinstance(event, FreightLandedCost) and not event.reverses and index not in reversed_indices:
            yield index, event


def active_bank_matches(events: list[FreightBillEvent]) -> dict[str, CarrierBankMatch]:
    matches: dict[str, CarrierBankMatch] = {}
    for event in events:
        if isinstance(event, CarrierBankMatch):
            if event.released:
                matches.pop(event.cash_voucher, None)
            else:
                matches[event.cash_voucher] = event
    return matches


@dataclass(frozen=True)
class FreightCostPosting:
    voucher: str
    order: str
    event: FreightLandedCost


def landed_postings(ds: Dataset) -> Iterator[FreightCostPosting]:
    for order in ds.freight_orders:
        for index, event in enumerate(order.bill_events, 1):
            if isinstance(event, FreightLandedCost):
                yield FreightCostPosting(f"{order.bill_voucher()}/L-{index}", order.id, event)
