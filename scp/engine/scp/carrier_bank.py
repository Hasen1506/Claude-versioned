"""Import normalized bank statement evidence and reconcile it to carrier cash."""
import csv
import hashlib
import io
import json
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from .freight import CarrierBill, active_bank_matches, carrier_bills, freight_company
from .model import Dataset
from .model.carrier_bank import BankCashRef, BankMatchEvent, CarrierBankLine
from .model.common import Model, Out
from .model.transport import CarrierBankMatch


class ImportStatement(Model):
    kind: Literal["import"]
    company: str = Field(max_length=64)
    account: str = Field(min_length=1, max_length=64)
    csv: str = Field(min_length=1, max_length=256_000)


class MatchStatement(Model):
    kind: Literal["match"]
    line: str = Field(min_length=1, max_length=64)
    targets: list[BankCashRef] = Field(min_length=1, max_length=100)
    version: int = Field(ge=0, strict=True)


class ReleaseStatement(Model):
    kind: Literal["release"]
    line: str = Field(min_length=1, max_length=64)
    version: int = Field(gt=0, strict=True)


BankOperation = Annotated[ImportStatement | MatchStatement | ReleaseStatement, Field(discriminator="kind")]
parse_operation = TypeAdapter(BankOperation)
HEADER = ["line", "date", "reference", "amount", "currency"]
AMOUNT = re.compile(r"[+-]?[0-9]{1,13}(?:\.[0-9]{1,2})?")


def _line_id(key: tuple[str, str, str]) -> str:
    return "BS-" + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:40]


class CarrierCash(Out):
    order: str
    voucher: str
    company: str
    carrier: str
    date: date
    reference: str
    amount_minor: int


class CarrierBankView(Out):
    lines: list[CarrierBankLine]
    unmatched_cash: list[CarrierCash]


def bank_view(ds: Dataset, bills: list[CarrierBill]) -> CarrierBankView:
    unmatched = []
    for bill in bills:
        available = set(bill.unreconciled_cash)
        unmatched.extend(CarrierCash(order=bill.order, voucher=voucher, company=bill.company, carrier=bill.name,
                                     date=on, reference=reference, amount_minor=minor)
                         for voucher, on, reference, minor in bill.cash() if voucher in available)
    return CarrierBankView(lines=sorted(ds.carrier_bank_lines, key=lambda line: (line.date, line.id), reverse=True),
                           unmatched_cash=unmatched)


def _legacy(ds: Dataset) -> dict[tuple[str, str, str], CarrierBankMatch]:
    return {(freight_company(ds, order), row.account.casefold(), row.statement_line.casefold()): row
            for order in ds.freight_orders for row in active_bank_matches(order.bill_events).values()}


def _import(ds: Dataset, request: ImportStatement) -> tuple[Dataset, str]:
    if request.company and request.company not in ds.entity_by_id:
        raise ValueError("choose the legal entity that owns the bank statement")
    if len(request.csv.encode()) > 256_000:
        raise ValueError("the statement CSV can contain at most 256000 bytes")
    source = csv.reader(io.StringIO(request.csv.lstrip("\ufeff"), newline=""), strict=True)
    existing = {line.source_key(): line for line in ds.carrier_bank_lines}
    legacy = _legacy(ds)
    seen = set()
    added = []
    kept = 0
    try:
        if next(source, None) != HEADER:
            raise ValueError("use the exact CSV columns line,date,reference,amount,currency")
        for fields in source:
            if not fields or not any(field.strip() for field in fields):
                continue
            if len(seen) >= 500:
                raise ValueError("one statement import can contain at most 500 lines")
            if len(fields) != 5:
                raise ValueError(f"CSV row {source.line_num} must contain exactly five fields")
            statement, day, reference, amount, currency = (field.strip() for field in fields)
            if currency != ds.settings.currency or not AMOUNT.fullmatch(amount):
                raise ValueError(f"CSV row {source.line_num} needs company currency and an exact signed amount")
            try:
                on = date.fromisoformat(day)
                if on.isoformat() != day:
                    raise ValueError("date format")
                key = request.company, request.account.casefold(), statement.casefold()
                line = CarrierBankLine(id=_line_id(key), company=request.company, account=request.account,
                                       statement_line=statement, date=on, reference=reference,
                                       amount_minor=int(Decimal(amount) * 100), currency=currency)
            except (ValidationError, ValueError) as error:
                raise ValueError(f"CSV row {source.line_num} has an invalid identifier, date, reference, or amount") from error
            if key in seen:
                raise ValueError(f"CSV row {source.line_num} repeats a statement line in the file")
            seen.add(key)
            prior, previous = existing.get(key), legacy.get(key)
            facts = line.date, line.reference, line.amount_minor
            if prior or previous:
                record = prior if prior else previous
                assert record is not None
                if (record.date, record.reference, record.amount_minor) != facts:
                    raise ValueError(f"CSV row {source.line_num} conflicts with the retained statement line")
                kept += 1
            else:
                added.append(line)
    except csv.Error as error:
        raise ValueError(f"the statement CSV is malformed at row {source.line_num}") from error
    if not seen:
        raise ValueError("the statement file needs at least one line")
    return ds.model_copy(update={"carrier_bank_lines": [*ds.carrier_bank_lines, *added]}), (
        f"Imported {len(added)} statement lines. Already recorded: {kept}.")


def _validate_match(line: CarrierBankLine, targets: list[BankCashRef], cash: dict[tuple[str, str], CarrierCash], day: date) -> None:
    keys = [target.key() for target in targets]
    if len(keys) != len(set(keys)):
        raise ValueError("select each cash voucher once")
    total = 0
    for key in keys:
        leg = cash.get(key)
        if not leg or leg.company != line.company or (leg.amount_minor > 0) != (line.amount_minor > 0):
            raise ValueError("cash vouchers must be unmatched and have the statement's entity and direction")
        if leg.reference.casefold() != line.reference.casefold():
            raise ValueError("the cash vouchers must share the statement's bank reference")
        if leg.date > day:
            raise ValueError("the reconciliation date cannot precede a selected cash posting")
        total += leg.amount_minor
    if total != line.amount_minor:
        raise ValueError("the signed cash vouchers must add up exactly to the statement line")


def record_bank(ds: Dataset, request: BankOperation, day: date) -> tuple[Dataset, str]:
    if isinstance(request, ImportStatement):
        return _import(ds, request)
    line = next((row for row in ds.carrier_bank_lines if row.id == request.line), None)
    if line is None:
        raise ValueError("select an imported statement line in this company")
    if len(line.history) != request.version:
        raise ValueError("the statement match changed; review its current history")
    if day < (line.history[-1].date if line.history else line.date):
        raise ValueError("the reconciliation date cannot precede the statement or its last action")
    if isinstance(request, MatchStatement):
        if line.active:
            raise ValueError("release the statement's current match first")
        available = bank_view(ds, list(carrier_bills(ds))).unmatched_cash
        _validate_match(line, request.targets, {(p.order, p.voucher): p for p in available}, day)
        targets = sorted(request.targets, key=BankCashRef.key)
        message = f"Matched {line.statement_line} to {len(targets)} carrier cash vouchers."
    else:
        if not line.active:
            raise ValueError("the statement has no active match to release")
        targets = []
        message = f"Released the match for {line.statement_line}."
    updated = line.model_copy(update={"history": [*line.history, BankMatchEvent(date=day, targets=targets)]})
    return ds.model_copy(update={"carrier_bank_lines": [updated if row.id == line.id else row for row in ds.carrier_bank_lines]}), message


def protect_bank(old: Dataset, new: Dataset, command: bool) -> None:
    """Check the evidence aggregate at the company save boundary, including legacy coexistence."""
    if not old.carrier_bank_lines and not new.carrier_bank_lines:
        return
    if old.carrier_bank_lines != new.carrier_bank_lines and not command:
        raise ValueError("statement lines and allocations require an authoritative carrier bank command")
    prior = {row.id: row for row in old.carrier_bank_lines}
    if not prior.keys() <= {row.id for row in new.carrier_bank_lines}:
        raise ValueError("statement lines are retained")
    keys: set[tuple[str, str, str]] = set()
    claimed: set[tuple[str, str]] = set()
    legacy = _legacy(new)
    cash: dict[tuple[str, str], CarrierCash] = {}
    for bill in carrier_bills(new):
        legacy_vouchers = active_bank_matches(bill.events)
        for voucher, on, ref, minor in bill.cash():
            if voucher not in legacy_vouchers:
                cash[bill.order, voucher] = CarrierCash(order=bill.order, voucher=voucher, company=bill.company, carrier=bill.name,
                                                       date=on, reference=ref, amount_minor=minor)
    for row in new.carrier_bank_lines:
        key = row.source_key()
        if (row.id != _line_id(key) or key in keys or key in legacy or row.currency != new.settings.currency
                or (row.company and row.company not in new.entity_by_id)):
            raise ValueError("statement lines must keep a unique source within their original paying entity and currency")
        keys.add(key)
        earlier = prior.get(row.id)
        if earlier is not None and (row.model_dump(exclude={"history"}) != earlier.model_dump(exclude={"history"})
                                    or row.history[:len(earlier.history)] != earlier.history
                                    or len(row.history) > len(earlier.history) + 1):
            raise ValueError("statement source and match history are retained")
        if row.active:
            _validate_match(row, row.active, cash, row.history[-1].date)
            active_keys = {target.key() for target in row.active}
            if active_keys & claimed:
                raise ValueError("that cash voucher already belongs to another statement match")
            claimed.update(active_keys)
