"""Posted carrier bills shared by the journal, payable worklist and cash forecast."""
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Literal

from pydantic import computed_field

from .transfer_price import freight_company
from ..model import Dataset, FreightOrder, Payment
from ..model.common import Out


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

    def open_at(self, through: date) -> float:
        if self.date > through or (self.credited_on and self.credited_on <= through):
            return 0.0
        paid = sum(round(p.amount * 100) for p in self.payments if p.date <= through)
        return (round(self.amount * 100) - paid) / 100

    @computed_field
    @property
    def open(self) -> float:
        return self.open_at(date.max)

    @computed_field
    @property
    def status(self) -> Literal["to pay", "paid", "credited"]:
        return "credited" if self.credited_on else "to pay" if self.open else "paid"


def bills_for_order(ds: Dataset, order: FreightOrder) -> Iterator[CarrierBill]:
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
                          payments=order.bill_payments)


def carrier_bills(ds: Dataset) -> Iterator[CarrierBill]:
    for order in ds.freight_orders:
        yield from bills_for_order(ds, order)
