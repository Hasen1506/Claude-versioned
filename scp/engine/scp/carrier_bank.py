"""Import normalized bank statement evidence and reconcile it to carrier cash."""
import csv
import hashlib
import io
import json
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter, ValidationError

from .carrier_accounts import BankAccounts, CarrierBankTieOut, check_window, period_id, protect_accounts, statement_periods, tie_out
from .freight import BankPosting, CarrierBill, active_bank_matches, carrier_bills, freight_company
from .model import Dataset
from .model.carrier_bank import (BankAccountOpening, BankCashRef, BankMatchEvent, BankStatementHeader,
                                 CarrierBankAccount, CarrierBankLine, CarrierBankPeriod)
from .model.common import Model, Out
from .model.transport import CarrierBankMatch


class ImportStatement(Model):
    kind: Literal["import"]
    company: str = Field(max_length=64)
    account: str = Field(min_length=1, max_length=64)
    csv: str = Field(min_length=1, max_length=256_000)


class RegisterBankAccount(BankAccountOpening):
    kind: Literal["register_account"]


class ImportBankPeriod(BankStatementHeader):
    kind: Literal["import_period"]
    csv: Annotated[str, StringConstraints(min_length=1, max_length=256_000, strip_whitespace=False)]


class MatchStatement(Model):
    kind: Literal["match"]
    line: str = Field(min_length=1, max_length=64)
    targets: list[BankCashRef] = Field(min_length=1, max_length=100)
    version: int = Field(ge=0, strict=True)


class ReleaseStatement(Model):
    kind: Literal["release"]
    line: str = Field(min_length=1, max_length=64)
    version: int = Field(gt=0, strict=True)


BankOperation = Annotated[ImportStatement | MatchStatement | ReleaseStatement | RegisterBankAccount | ImportBankPeriod,
                          Field(discriminator="kind")]
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
    bank_account: str | None = None


class CarrierBankView(Out):
    lines: list[CarrierBankLine]
    unmatched_cash: list[CarrierCash]
    periods: list[CarrierBankTieOut]


def _cash(bill: CarrierBill, posting: BankPosting) -> CarrierCash:
    return CarrierCash(order=bill.order, company=bill.company, carrier=bill.name, voucher=posting.voucher,
                       date=posting.date, reference=posting.reference, amount_minor=posting.amount_minor,
                       bank_account=posting.bank_account)


def bank_view(ds: Dataset, bills: list[CarrierBill]) -> CarrierBankView:
    unmatched = []
    posted = []
    for bill in bills:
        available = set(bill.unreconciled_cash)
        for posting in bill.cash():
            posted.append(posting)
            if posting.voucher in available:
                unmatched.append(_cash(bill, posting))
    return CarrierBankView(lines=sorted(ds.carrier_bank_lines, key=lambda line: (line.date, line.id), reverse=True),
                           unmatched_cash=unmatched, periods=tie_out(ds, posted))


def _legacy(ds: Dataset) -> dict[tuple[str, str, str], CarrierBankMatch]:
    return {(freight_company(ds, order), row.account.casefold(), row.statement_line.casefold()): row
            for order in ds.freight_orders for row in active_bank_matches(order.bill_events).values()}


def _read_lines(company: str, account: str, currency_code: str, file: str) -> dict[tuple[str, str, str], CarrierBankLine]:
    if len(file.encode()) > 256_000:
        raise ValueError("the statement CSV can contain at most 256000 bytes")
    source = csv.reader(io.StringIO(file.lstrip("\ufeff"), newline=""), strict=True)
    lines = {}
    try:
        if next(source, None) != HEADER:
            raise ValueError("use the exact CSV columns line,date,reference,amount,currency")
        for fields in source:
            if not fields or not any(field.strip() for field in fields):
                continue
            if len(lines) >= 500:
                raise ValueError("one statement import can contain at most 500 lines")
            if len(fields) != 5:
                raise ValueError(f"CSV row {source.line_num} must contain exactly five fields")
            statement, day, reference, amount, currency = (field.strip() for field in fields)
            if currency != currency_code or not AMOUNT.fullmatch(amount):
                raise ValueError(f"CSV row {source.line_num} needs company currency and an exact signed amount")
            try:
                on = date.fromisoformat(day)
                if on.isoformat() != day:
                    raise ValueError("date format")
                key = company, account.casefold(), statement.casefold()
                line = CarrierBankLine(id=_line_id(key), company=company, account=account,
                                       statement_line=statement, date=on, reference=reference,
                                       amount_minor=int(Decimal(amount) * 100), currency=currency)
            except (ValidationError, ValueError) as error:
                raise ValueError(f"CSV row {source.line_num} has an invalid identifier, date, reference, or amount") from error
            if key in lines:
                raise ValueError(f"CSV row {source.line_num} repeats a statement line in the file")
            lines[key] = line
    except csv.Error as error:
        raise ValueError(f"the statement CSV is malformed at row {source.line_num}") from error
    return lines


def _import(ds: Dataset, request: ImportStatement) -> tuple[Dataset, str]:
    if request.company and request.company not in ds.entity_by_id:
        raise ValueError("choose the legal entity that owns the bank statement")
    parsed = _read_lines(request.company, request.account, ds.settings.currency, request.csv)
    if not parsed:
        raise ValueError("the statement file needs at least one line")
    account = BankAccounts(ds).by_id.get(request.account.upper())
    if account and account.company == request.company and any(line.date >= account.starts_on for line in parsed.values()):
        raise ValueError("import the registered account's statement period with its source balances")
    existing = {line.source_key(): line for line in ds.carrier_bank_lines}
    legacy = _legacy(ds)
    added = []
    for key, line in parsed.items():
        prior = existing.get(key) or legacy.get(key)
        if prior is None:
            added.append(line)
        elif (prior.date, prior.reference, prior.amount_minor) != (line.date, line.reference, line.amount_minor):
            raise ValueError(f"Line {line.statement_line} conflicts with the retained statement line")
    kept = len(parsed) - len(added)
    return ds.model_copy(update={"carrier_bank_lines": [*ds.carrier_bank_lines, *added]}), (
        f"Imported {len(added)} statement lines. Already recorded: {kept}.")


def _register(ds: Dataset, request: RegisterBankAccount) -> tuple[Dataset, str]:
    account = CarrierBankAccount(**request.model_dump(exclude={"kind"}), currency=ds.settings.currency)
    prior = BankAccounts(ds).by_id.get(account.id)
    if request.company and request.company not in ds.entity_by_id:
        raise ValueError("choose the owning legal entity for this bank account")
    if prior == account:
        return ds, f"Bank account {account.id} is already registered."
    if prior:
        raise ValueError("the opening basis of a registered account is retained")
    return ds.model_copy(update={"carrier_bank_accounts": [*ds.carrier_bank_accounts, account]}), f"Registered bank account {account.id}."


def _import_period(ds: Dataset, request: ImportBankPeriod) -> tuple[Dataset, str]:
    account = BankAccounts(ds).by_id.get(request.account)
    if account is None:
        raise ValueError("register the bank account before importing its statement period")
    rows = _read_lines(account.company, account.id, account.currency, request.csv)
    lines = {line.id: line for line in rows.values()}
    period = CarrierBankPeriod(**request.model_dump(exclude={"kind", "csv"}), id=period_id(account.id, request.number),
                               file_sha256=hashlib.sha256(request.csv.encode()).hexdigest(), line_ids=list(lines))
    prior = next((p for p in ds.carrier_bank_periods if p.id == period.id), None)
    if prior == period:
        return ds, f"Statement {period.number} is already recorded."
    if prior:
        raise ValueError("the offered file differs from the retained source statement")
    if rows.keys() & ({line.source_key() for line in ds.carrier_bank_lines} | _legacy(ds).keys()):
        raise ValueError("a source line was already recorded outside this statement period")
    preceding = next((p for p in reversed(ds.carrier_bank_periods) if p.account == account.id), None)
    check_window(period, account, preceding, lines)
    return ds.model_copy(update={"carrier_bank_periods": [*ds.carrier_bank_periods, period],
                                 "carrier_bank_lines": [*ds.carrier_bank_lines, *lines.values()]}), f"Imported statement {period.number}."


def _validate_match(line: CarrierBankLine, targets: list[BankCashRef], cash: dict[tuple[str, str], CarrierCash], day: date,
                    period: CarrierBankPeriod | None) -> None:
    keys = [target.key() for target in targets]
    if len(keys) != len(set(keys)):
        raise ValueError("select each cash voucher once")
    total = 0
    for key in keys:
        leg = cash.get(key)
        if not leg or leg.company != line.company or (leg.amount_minor > 0) != (line.amount_minor > 0):
            raise ValueError("cash vouchers must be unmatched and have the statement's entity and direction")
        if leg.bank_account != (period.account if period else None) or (period and not period.starts_on <= leg.date <= period.ends_on):
            raise ValueError("the carrier cash must belong to the statement's registered account and posting period")
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
    if isinstance(request, RegisterBankAccount):
        return _register(ds, request)
    if isinstance(request, ImportBankPeriod):
        return _import_period(ds, request)
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
        _validate_match(line, request.targets, {(p.order, p.voucher): p for p in available}, day, statement_periods(ds).get(line.id))
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
    if old.carrier_bank_lines != new.carrier_bank_lines and not command:
        raise ValueError("statement lines and allocations require an authoritative carrier bank command")
    prior = {row.id: row for row in old.carrier_bank_lines}
    if not prior.keys() <= {row.id for row in new.carrier_bank_lines}:
        raise ValueError("statement lines are retained")
    keys: set[tuple[str, str, str]] = set()
    claimed: set[tuple[str, str]] = set()
    legacy = _legacy(new)
    cash: dict[tuple[str, str], CarrierCash] = {}
    posted = []
    for bill in carrier_bills(new):
        legacy_vouchers = active_bank_matches(bill.events)
        for posting in bill.cash():
            posted.append((bill.company, posting))
            if posting.voucher not in legacy_vouchers:
                cash[bill.order, posting.voucher] = _cash(bill, posting)
    periods = protect_accounts(old, new, command, {line.id: line for line in new.carrier_bank_lines}, posted)
    accounts = BankAccounts(new).by_id
    for (company, account_id, _), match in legacy.items():
        account = accounts.get(account_id.upper())
        if account and account.company == company and match.date >= account.starts_on:
            raise ValueError("legacy matches must precede a registered bank account's first statement date")
    for row in new.carrier_bank_lines:
        key = row.source_key()
        if (row.id != _line_id(key) or key in keys or key in legacy or row.currency != new.settings.currency
                or (row.company and row.company not in new.entity_by_id)):
            raise ValueError("statement lines must keep a unique source within their original paying entity and currency")
        account = accounts.get(row.account.upper())
        if account and account.company == row.company and row.date >= account.starts_on and row.id not in periods:
            raise ValueError("a registered account's statement lines require their source period")
        keys.add(key)
        earlier = prior.get(row.id)
        if earlier is not None and (row.model_dump(exclude={"history"}) != earlier.model_dump(exclude={"history"})
                                    or row.history[:len(earlier.history)] != earlier.history
                                    or len(row.history) > len(earlier.history) + 1):
            raise ValueError("statement source and match history are retained")
        if row.active:
            _validate_match(row, row.active, cash, row.history[-1].date, periods.get(row.id))
            active_keys = {target.key() for target in row.active}
            if active_keys & claimed:
                raise ValueError("that cash voucher already belongs to another statement match")
            claimed.update(active_keys)
