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

from .camt_statements import file_evidence, file_set_evidence, read_statement_files
from .carrier_accounts import (BankAccounts, CarrierBankTieOut, check_window, last_period, next_start,
                               period_id, protect_accounts, statement_periods, tie_out)
from .freight import BankPosting, CarrierBill, active_bank_matches, carrier_bills, freight_company
from .model import Dataset
from .model.carrier_bank import (CAMT_MAX_BYTES, CAMT_MAX_PAGES, BankAccountId, BankAccountOpening, BankCashRef, BankMatchEvent, BankStatementHeader,
                                 CamtAccountBinding, CamtSourceEvidence, CarrierBankAccount, CarrierBankLine, CarrierBankPeriod)
from .model.common import Model, Out
from .model.transport import CarrierBankMatch, CarrierBankReversal


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


CamtXml = Annotated[str, StringConstraints(min_length=1, max_length=CAMT_MAX_BYTES, strip_whitespace=False)]


class CamtFile(Model):
    kind: Literal["link_camt_source", "import_camt"]
    account: BankAccountId
    xml: CamtXml

    def receipt_event(self) -> dict:
        data, digest = file_evidence(self.xml)
        return {"kind": self.kind, "account": self.account, "file_sha256": digest, "byte_count": len(data)}


class CamtFiles(Model):
    kind: Literal["link_camt_pages", "import_camt_pages"]
    account: BankAccountId
    files: list[CamtXml] = Field(min_length=2, max_length=CAMT_MAX_PAGES)

    def canonical_events(self) -> tuple[dict, dict]:
        originals = sorted(zip(self.files, file_set_evidence(self.files), strict=True), key=lambda item: item[1][1])
        identity = {"kind": self.kind, "account": self.account}
        files = [xml for xml, _ in originals]
        evidence = [{"file_sha256": digest, "byte_count": len(data)} for _, (data, digest) in originals]
        return {**identity, "files": files}, {**identity, "files": evidence}


class MatchStatement(Model):
    kind: Literal["match"]
    line: str = Field(min_length=1, max_length=64)
    targets: list[BankCashRef] = Field(min_length=1, max_length=100)
    version: int = Field(ge=0, strict=True)


class ReleaseStatement(Model):
    kind: Literal["release"]
    line: str = Field(min_length=1, max_length=64)
    version: int = Field(gt=0, strict=True)


class ReverseBankCash(Model):
    kind: Literal["reverse_cash"]
    line: str = Field(min_length=1, max_length=64)
    original: BankCashRef


BankOperation = Annotated[ImportStatement | MatchStatement | ReleaseStatement | ReverseBankCash | RegisterBankAccount | ImportBankPeriod
                          | CamtFile | CamtFiles,
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


class ReversibleCash(CarrierCash):
    original_line: str
    eligible_from: date


class CarrierBankView(Out):
    lines: list[CarrierBankLine]
    unmatched_cash: list[CarrierCash]
    periods: list[CarrierBankTieOut]
    reversible_cash: list[ReversibleCash]
    locked_lines: list[str]


def _cash(bill: CarrierBill, posting: BankPosting) -> CarrierCash:
    return CarrierCash(order=bill.order, company=bill.company, carrier=bill.name, voucher=posting.voucher,
                       date=posting.date, reference=posting.reference, amount_minor=posting.amount_minor,
                       bank_account=posting.bank_account)


def bank_view(ds: Dataset, bills: list[CarrierBill]) -> CarrierBankView:
    unmatched = []
    posted = []
    reversible = []
    locked = _locked_reversal_lines(bills)
    sources = _original_matches(ds, locked)
    for bill in bills:
        available = set(bill.unreconciled_cash)
        latest = bill.latest_monetary_date()
        for posting in bill.cash():
            posted.append(posting)
            if posting.voucher in available:
                unmatched.append(_cash(bill, posting))
            original = sources.get((bill.order, posting.voucher))
            if original:
                reversible.append(ReversibleCash(**_cash(bill, posting).model_dump(),
                                                  original_line=original.statement_line, eligible_from=max(latest, original.date)))
    return CarrierBankView(lines=sorted(ds.carrier_bank_lines, key=lambda line: (line.date, line.id), reverse=True),
                           unmatched_cash=unmatched, periods=tie_out(ds, posted), reversible_cash=reversible,
                           locked_lines=sorted(locked))


def _locked_reversal_lines(bills: list[CarrierBill]) -> set[str]:
    return {line for bill in bills for _, event in bill.reversals() for line in (event.original_line, event.statement_line)}


def _original_matches(ds: Dataset, locked: set[str]) -> dict[tuple[str, str], CarrierBankLine]:
    managed = statement_periods(ds)
    return {row.active[0].key(): row for row in ds.carrier_bank_lines
            if row.id in managed and row.id not in locked and not row.reversal and len(row.active) == 1}


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
    if prior and prior.model_copy(update={"camt_source": None}) == account:
        return ds, f"Bank account {account.id} is already registered."
    if prior:
        raise ValueError("the opening basis of a registered account is retained")
    return ds.model_copy(update={"carrier_bank_accounts": [*ds.carrier_bank_accounts, account]}), f"Registered bank account {account.id}."


def _append_period(ds: Dataset, account: CarrierBankAccount, header: BankStatementHeader, rows: list[CarrierBankLine],
                   digest: str, source: CamtSourceEvidence | None = None) -> tuple[Dataset, str]:
    lines = {line.id: line for line in rows}
    period = CarrierBankPeriod(**header.model_dump(), id=period_id(account.id, header.number), file_sha256=digest,
                               line_ids=list(lines), camt_source=source)
    prior = next((p for p in ds.carrier_bank_periods if p.id == period.id), None)
    if prior == period:
        return ds, f"Statement {period.number} is already recorded."
    if prior:
        raise ValueError("the offered file differs from the retained source statement")
    bound = account.camt_source
    if bool(source) != bool(bound and period.starts_on >= bound.starts_on):
        raise ValueError("import the original camt.053 file for the linked account beginning on its linked date")
    if {line.source_key() for line in rows} & ({line.source_key() for line in ds.carrier_bank_lines} | _legacy(ds).keys()):
        raise ValueError("a source line was already recorded outside this statement period")
    check_window(period, account, last_period(ds, account.id), lines)
    return ds.model_copy(update={"carrier_bank_periods": [*ds.carrier_bank_periods, period],
                                 "carrier_bank_lines": [*ds.carrier_bank_lines, *lines.values()]}), f"Imported statement {period.number}."


def _account(ds: Dataset, identifier: str) -> CarrierBankAccount:
    account = BankAccounts(ds).by_id.get(identifier)
    if account is None:
        raise ValueError("register the bank account before importing its statement period")
    return account


def _import_period(ds: Dataset, request: ImportBankPeriod) -> tuple[Dataset, str]:
    account = _account(ds, request.account)
    rows = _read_lines(account.company, account.id, account.currency, request.csv)
    header = BankStatementHeader(**request.model_dump(exclude={"kind", "csv"}))
    return _append_period(ds, account, header, list(rows.values()), hashlib.sha256(request.csv.encode()).hexdigest())


def _camt(ds: Dataset, request: CamtFile | CamtFiles, day: date) -> tuple[Dataset, str]:
    account = _account(ds, request.account)
    files = request.files if isinstance(request, CamtFiles) else [request.xml]
    statement = read_statement_files(files, account.id, account.currency)
    if statement.header.ends_on > day:
        raise ValueError("the bank evidence date cannot precede the statement close")
    bound = account.camt_source
    if request.kind in ("link_camt_source", "link_camt_pages"):
        if bound:
            if bound.account_sha256 != statement.account_hash:
                raise ValueError("the registered account's camt.053 source is retained")
            return ds, f"Bank account {account.id} already has a camt.053 source."
        begins = date.fromordinal(next_start(account, last_period(ds, account.id)))
        linked = account.model_copy(update={"camt_source": CamtAccountBinding(account_sha256=statement.account_hash, starts_on=begins)})
        return ds.model_copy(update={"carrier_bank_accounts": [linked if a.id == account.id else a for a in ds.carrier_bank_accounts]}), (
            f"Linked camt.053 source for {account.id}.")
    if bound is None or bound.account_sha256 != statement.account_hash:
        raise ValueError("the file does not identify the selected account's linked bank source")
    rows = [CarrierBankLine(id=_line_id((account.company, account.id.casefold(), entry.identifier.casefold())),
                            company=account.company, account=account.id, statement_line=entry.identifier, date=entry.date,
                            reference=entry.reference, amount_minor=entry.amount_minor, currency=account.currency,
                            reversal=entry.reversal)
            for entry in statement.entries]
    return _append_period(ds, account, statement.header, rows, statement.file_sha256, statement.source)


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


def _check_reversal_source(line: CarrierBankLine, original: CarrierBankLine, period: CarrierBankPeriod | None) -> None:
    if (not line.reversal or period is None or period.camt_source is None or original.reversal
            or (line.company, line.account, line.currency) != (original.company, original.account, original.currency)
            or line.amount_minor != -original.amount_minor or line.date < original.date
            or line.reference.casefold() != original.reference.casefold()):
        raise ValueError("a bank reversal requires native evidence of the full opposite movement with the original account and reference")


def _record_reversal(ds: Dataset, request: ReverseBankCash, line: CarrierBankLine, day: date) -> tuple[Dataset, str]:
    if day != line.date or line.history:
        raise ValueError("post an unused reversal on the bank booking date")
    bills = list(carrier_bills(ds))
    locked = _locked_reversal_lines(bills)
    original = _original_matches(ds, locked).get(request.original.key())
    if original is None:
        raise ValueError("select one individually reconciled carrier payment or refund that has not already been reversed")
    _check_reversal_source(line, original, statement_periods(ds).get(line.id))
    bill = next((b for b in bills if b.order == request.original.order and any(
        cash.voucher == request.original.voucher for cash in b.cash())), None)
    if bill is None or day < bill.latest_monetary_date():
        raise ValueError("the bank booking date precedes a later cash or credit posting on this carrier bill")
    order = next(order for order in ds.freight_orders if order.id == bill.order)
    event = CarrierBankReversal(date=day, reverses=request.original.voucher, original_line=original.id, statement_line=line.id,
                                reference=line.reference, amount_minor=line.amount_minor, bank_account=line.account)
    changed = order.model_copy(update={"bill_events": [*order.bill_events, event]})
    target = BankCashRef(order=bill.order, voucher=f"{bill.voucher}/V-{len(changed.bill_events)}")
    matched = line.model_copy(update={"history": [BankMatchEvent(date=day, targets=[target])]})
    return ds.model_copy(update={"freight_orders": [changed if f.id == order.id else f for f in ds.freight_orders],
                                 "carrier_bank_lines": [matched if row.id == line.id else row for row in ds.carrier_bank_lines]}), (
        f"Recorded and reconciled {target.voucher} reversing {event.reverses}.")


def record_bank(ds: Dataset, request: BankOperation, day: date) -> tuple[Dataset, str]:
    if isinstance(request, ImportStatement):
        return _import(ds, request)
    if isinstance(request, RegisterBankAccount):
        return _register(ds, request)
    if isinstance(request, ImportBankPeriod):
        return _import_period(ds, request)
    if isinstance(request, (CamtFile, CamtFiles)):
        return _camt(ds, request, day)
    line = next((row for row in ds.carrier_bank_lines if row.id == request.line), None)
    if line is None:
        raise ValueError("select an imported statement line in this company")
    if isinstance(request, ReverseBankCash):
        return _record_reversal(ds, request, line, day)
    if line.reversal:
        raise ValueError("a bank reversal can only be allocated to its own reversal posting")
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
        if line.id in _locked_reversal_lines(list(carrier_bills(ds))):
            raise ValueError("retain the original statement match for the posted bank reversal")
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
    reversals: dict[str, tuple[BankCashRef, BankCashRef, CarrierBankReversal]] = {}
    for bill in carrier_bills(new):
        legacy_vouchers = active_bank_matches(bill.events)
        for posting in bill.cash():
            posted.append((bill.company, posting))
            if posting.voucher not in legacy_vouchers:
                cash[bill.order, posting.voucher] = _cash(bill, posting)
        for voucher, event in bill.reversals():
            if event.statement_line in reversals:
                raise ValueError("a bank reversal line belongs to exactly one carrier cash correction")
            reversals[event.statement_line] = (BankCashRef(order=bill.order, voucher=voucher),
                                               BankCashRef(order=bill.order, voucher=event.reverses), event)
    periods = protect_accounts(old, new, command, {line.id: line for line in new.carrier_bank_lines}, posted)
    accounts = BankAccounts(new).by_id
    lines = {row.id: row for row in new.carrier_bank_lines}
    for line_id, (target, original_target, event) in reversals.items():
        reversal, original = lines.get(line_id), lines.get(event.original_line)
        if (reversal is None or original is None or original.id not in periods or original.active != [original_target]
                or reversal.active != [target] or len(reversal.history) != 1
                or reversal.date != event.date or reversal.history[0].date != event.date):
            raise ValueError("a posted bank reversal must retain both of its original statement allocations")
        _check_reversal_source(reversal, original, periods.get(line_id))
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
        if row.reversal and (row.id not in periods or not periods[row.id].camt_source or (row.active and row.id not in reversals)):
            raise ValueError("a marked reversal must keep its native source and match only its reversal posting")
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
