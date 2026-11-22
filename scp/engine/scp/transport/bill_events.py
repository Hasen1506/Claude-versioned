"""Append corrections, statement matches and receipt allocations to a posted carrier bill."""
from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from ..freight import CarrierBill, active_bank_matches, active_landed, bills_for_order, freight_company
from ..model import Dataset, FreightOrder, MovementType
from ..model.common import Id, Model
from ..model.transport import CarrierBankMatch, CarrierBillAdjustment, CarrierRefund, FreightBillEvent, FreightLandedCost
from . import TransportError, TransportReport, _fo, _put


class AdjustBillInput(Model):
    kind: Literal["adjust_bill"]
    reference: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(gt=0, strict=True)


class RefundBillInput(Model):
    kind: Literal["refund_bill"]
    reference: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(gt=0, strict=True)


class BankMatchInput(Model):
    kind: Literal["match_bank"]
    cash_voucher: str = Field(min_length=1, max_length=64)
    account: str = Field(min_length=1, max_length=64)
    statement_line: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(strict=True)
    currency: str = Field(min_length=3, max_length=3)


class ReleaseMatchInput(Model):
    kind: Literal["release_match"]
    cash_voucher: str = Field(min_length=1, max_length=64)
    account: str = Field(min_length=1, max_length=64)
    statement_line: str = Field(min_length=1, max_length=64)


class LandedCostInput(Model):
    kind: Literal["landed_cost"]
    service: str = Field(min_length=1, max_length=64)
    receipt: Id
    actual_minor: int = Field(ge=0, strict=True)


class ReverseLandedInput(Model):
    kind: Literal["reverse_landed"]
    reverses: int = Field(gt=0, strict=True)


BillEventInput = Annotated[AdjustBillInput | RefundBillInput | BankMatchInput | ReleaseMatchInput
                           | LandedCostInput | ReverseLandedInput, Field(discriminator="kind")]


def _credit_refs(order: FreightOrder) -> set[str]:
    return ({c.reference.casefold() for c in order.bill_credits}
            | {e.reference.casefold() for e in order.bill_events if isinstance(e, CarrierBillAdjustment)})


def _allocate(ds: Dataset, order: FreightOrder, bill: CarrierBill, request: LandedCostInput, day: date) -> FreightLandedCost:
    if not order.purchases or not bill.reference:
        raise TransportError("landed cost needs a referenced inbound carrier bill and a purchase receipt")
    receipt = next((m for m in ds.movements if m.id == request.receipt), None)
    if (receipt is None or receipt.type != MovementType.RECEIPT or receipt.reversal_of
            or receipt.reference not in order.purchases or receipt.location != order.ship_to
            or receipt.counterparty != order.ship_from or order.shipped_on is None
            or not order.shipped_on <= receipt.date <= day):
        raise TransportError("select the original goods receipt for a purchase collected on this freight order")
    if any(m.reversal_of == receipt.id for m in ds.movements):
        raise TransportError("a reversed goods receipt cannot be matched for landed cost")
    basis = ds.purchase_valuation_by_id.get(receipt.reference or "")
    if not basis or (basis.supplier, basis.location, basis.product) != (order.ship_from, receipt.location, receipt.product):
        raise TransportError("the original receipt requires its frozen purchase valuation basis")
    if any(e.receipt == receipt.id for other in ds.freight_orders for _, e in active_landed(other)):
        raise TransportError("this goods receipt already has an active freight allocation")
    if any(other.id != order.id and other.carrier == order.carrier and freight_company(ds, other) == bill.company
           and any(isinstance(e, FreightLandedCost) and e.service.casefold() == request.service.casefold()
                   for e in other.bill_events) for other in ds.freight_orders):
        raise TransportError("this accepted service is already attached to another carrier bill in the company")
    credits = [e for e in bill.events if isinstance(e, CarrierBillAdjustment)]
    if any(e.date > day for e in credits):
        raise TransportError("a freight allocation cannot precede an existing carrier credit")
    credited = sum(e.amount_minor for e in credits)
    allocated = sum(e.actual_minor for _, e in active_landed(order))
    if allocated + request.actual_minor > round(bill.amount * 100) - credited:
        raise TransportError("landed-cost allocations exceed the net carrier bill")
    if any(isinstance(e, FreightLandedCost) and e.receipt == receipt.id and e.date > day
           for other in ds.freight_orders for e in other.bill_events):
        raise TransportError("a new freight allocation cannot precede its prior receipt allocation history")
    return FreightLandedCost(date=day, service=request.service, receipt=receipt.id, actual_minor=request.actual_minor,
                             absorbed_minor=round(round(receipt.qty * basis.freight, 2) * 100))


def _match(ds: Dataset, bill: CarrierBill, request: BankMatchInput | ReleaseMatchInput, day: date) -> CarrierBankMatch:
    existing = active_bank_matches(bill.events).get(request.cash_voucher)
    key = request.account.casefold(), request.statement_line.casefold()
    if isinstance(request, ReleaseMatchInput):
        if not existing or (existing.account.casefold(), existing.statement_line.casefold()) != key:
            raise TransportError("review the current match before releasing it")
        if day < existing.date:
            raise TransportError("a release cannot precede the matched bank statement date")
        return existing.model_copy(update={"date": day, "released": True})
    if existing:
        raise TransportError("that cash voucher already has a bank statement match")
    if any(row.source_key() == (bill.company, *key) for row in ds.carrier_bank_lines):
        raise TransportError("that line was imported; match it from the carrier bank statement worklist")
    if any(target.key() == (bill.order, request.cash_voucher) for row in ds.carrier_bank_lines for target in row.active):
        raise TransportError("that cash voucher already belongs to a statement match")
    leg = next((row for row in bill.cash() if row[0] == request.cash_voucher), None)
    if (leg is None or not leg[2] or leg[2].casefold() != request.reference.casefold()
            or leg[3] != request.amount_minor or request.currency.upper() != ds.settings.currency):
        raise TransportError("statement direction, amount, currency and bank reference must match the cash voucher")
    for other in ds.freight_orders:
        if freight_company(ds, other) == bill.company and any(
                (e.account.casefold(), e.statement_line.casefold()) == key for e in active_bank_matches(other.bill_events).values()):
            raise TransportError("that bank statement line is already matched in the paying company")
    return CarrierBankMatch(date=day, cash_voucher=request.cash_voucher, account=request.account,
                            statement_line=request.statement_line, reference=request.reference, amount_minor=request.amount_minor)


def record_event(ds: Dataset, fid: str, voucher: str, request: BillEventInput, day: date) -> tuple[Dataset, TransportReport]:
    order = _fo(ds, fid)
    bill = next((b for b in bills_for_order(ds, order) if b.credited_on is None), None)
    if bill is None or bill.voucher != voucher or not bill.carrier:
        raise TransportError("review the posted carrier voucher before recording a bill event")
    if not isinstance(request, (BankMatchInput, ReleaseMatchInput)) and day < bill.date:
        raise TransportError("a carrier adjustment cannot precede its original bill")
    event: FreightBillEvent
    if isinstance(request, (BankMatchInput, ReleaseMatchInput)):
        event = _match(ds, bill, request, day)
    elif isinstance(request, LandedCostInput):
        event = _allocate(ds, order, bill, request, day)
    elif isinstance(request, ReverseLandedInput):
        original = dict(active_landed(order)).get(request.reverses)
        if original is None or day < original.date:
            raise TransportError("select an active allocation and a date on or after its posting")
        event = original.model_copy(update={"date": day, "reverses": request.reverses})
    else:
        monetary = [e.date for e in bill.events if isinstance(e, (CarrierBillAdjustment, CarrierRefund))]
        if day < max([bill.date, *monetary, *(p.date for p in bill.payments)]):
            raise TransportError("the credit or refund cannot precede an existing carrier cash or credit posting")
        if isinstance(request, AdjustBillInput):
            if any(active_landed(order)):
                raise TransportError("reverse the active landed-cost allocation before crediting the carrier bill")
            if any(isinstance(e, FreightLandedCost) and e.date > day for e in bill.events):
                raise TransportError("the credit cannot precede the latest landed-cost posting")
            credited = sum(e.amount_minor for e in bill.events if isinstance(e, CarrierBillAdjustment))
            if credited + request.amount_minor > round(bill.amount * 100):
                raise TransportError("carrier credits cannot exceed the original bill")
            if any(other.carrier == order.carrier and freight_company(ds, other) == bill.company
                   and request.reference.casefold() in _credit_refs(other) for other in ds.freight_orders):
                raise TransportError("that carrier credit reference is already posted in this company")
            event = CarrierBillAdjustment(date=day, **request.model_dump())
        else:
            if request.amount_minor > -round(bill.open * 100):
                raise TransportError("that refund exceeds the amount owed back on this carrier voucher")
            if any(isinstance(e, CarrierRefund) and e.reference.casefold() == request.reference.casefold() for e in bill.events):
                raise TransportError("that refund bank reference is already recorded on this voucher")
            event = CarrierRefund(date=day, **request.model_dump())
    changed = order.model_copy(update={"bill_events": [*order.bill_events, event]})
    label = {"adjust_bill": "Carrier credit", "refund_bill": "Carrier refund", "match_bank": "Bank match",
             "release_match": "Bank match release", "landed_cost": "Landed cost", "reverse_landed": "Landed-cost reversal"}
    return _put(ds, changed), TransportReport(orders=[fid], message=f"{label[request.kind]} recorded on {voucher}.")


def replay_input(event: FreightBillEvent, currency: str) -> BillEventInput:
    """Recompute stored facts during the company save instead of trusting submitted derived amounts."""
    if isinstance(event, FreightLandedCost):
        if event.reverses:
            return ReverseLandedInput(kind="reverse_landed", reverses=event.reverses)
        return LandedCostInput(kind="landed_cost", service=event.service, receipt=event.receipt, actual_minor=event.actual_minor)
    if isinstance(event, CarrierBankMatch):
        keys = dict(cash_voucher=event.cash_voucher, account=event.account, statement_line=event.statement_line)
        if event.released:
            return ReleaseMatchInput(kind="release_match", **keys)
        return BankMatchInput(kind="match_bank", **keys, reference=event.reference, amount_minor=event.amount_minor,
                              currency=currency)
    values = event.model_dump(exclude={"date"})
    return AdjustBillInput(**values) if isinstance(event, CarrierBillAdjustment) else RefundBillInput(**values)
