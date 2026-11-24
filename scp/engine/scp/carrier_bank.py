"""Import normalized bank statement evidence and reconcile it to carrier cash."""
import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter, ValidationError

from .camt_statements import file_evidence, file_set_evidence, read_statement_files
from .carrier_accounts import (BankAccounts, CarrierBankTieOut, CarrierBankTiming, check_window, last_period, next_start,
                               period_id, protect_accounts, statement_periods, tie_out)
from .freight import BankPosting, CarrierBill, active_bank_matches, bank_return_fees, carrier_bills, freight_company
from .model import Dataset
from .model.carrier_bank import (CAMT_MAX_BYTES, CAMT_MAX_PAGES, BankAccountId, BankAccountOpening, BankCashRef, BankMatchEvent, BankStatementHeader,
                                 BankReturnAllocation, CamtAccountBinding, CamtSourceEvidence, CarrierBankAccount, CarrierBankLine,
                                 CarrierBankPeriod, SupplierCashRef)
from .model.common import Model, Out
from .model.currency import MATERIAL_CURRENCIES, material_units
from .model.purchasing import supplier_payment_reference
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


class MatchSupplierStatement(Model):
    kind: Literal["match_supplier_payment"]
    line: str = Field(min_length=1, max_length=64)
    target: SupplierCashRef
    version: int = Field(ge=0, strict=True)


class ReleaseStatement(Model):
    kind: Literal["release"]
    line: str = Field(min_length=1, max_length=64)
    version: int = Field(gt=0, strict=True)


class ReverseBankCash(Model):
    kind: Literal["reverse_cash"]
    line: str = Field(min_length=1, max_length=64)
    original: BankCashRef
    late_reason: str = Field("", max_length=200)


class AllocateBankReturn(BankReturnAllocation):
    kind: Literal["allocate_return"]
    line: str = Field(min_length=1, max_length=64)


BankOperation = Annotated[ImportStatement | MatchStatement | MatchSupplierStatement | ReleaseStatement | ReverseBankCash | RegisterBankAccount | ImportBankPeriod
                          | CamtFile | CamtFiles | AllocateBankReturn,
                          Field(discriminator="kind")]
parse_operation = TypeAdapter(BankOperation)
HEADER = ["line", "date", "reference", "amount", "currency"]
AMOUNT = re.compile(r"[+-]?[0-9]{1,13}(?:\.[0-9]{1,2})?")
THREE_DECIMALS = re.compile(r"[+-]?[0-9]{1,13}(?:\.[0-9]{1,3})?")


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
    original_bank_date: date
    eligible_from: date
    remaining_minor: int
    full_return_eligible: bool
    source_trace_ids: list[str]


class SupplierBankCash(Out):
    invoice: str
    payment_number: int
    voucher: str
    supplier: str
    date: date
    reference: str
    amount_minor: int
    bank_account: str | None

    def posting(self) -> BankPosting:
        return BankPosting(self.voucher, self.date, self.reference, self.amount_minor, self.bank_account)


class CarrierBankView(Out):
    lines: list[CarrierBankLine]
    unmatched_cash: list[CarrierCash]
    periods: list[CarrierBankTieOut]
    reversible_cash: list[ReversibleCash]
    locked_lines: list[str]
    timing: list[CarrierBankTiming]
    unmatched_supplier_cash: list[SupplierBankCash] = Field(default_factory=list, exclude_if=lambda rows: not rows)


def _cash(bill: CarrierBill, posting: BankPosting) -> CarrierCash:
    return CarrierCash(order=bill.order, company=bill.company, carrier=bill.name, voucher=posting.voucher,
                       date=posting.date, reference=posting.reference, amount_minor=posting.amount_minor,
                       bank_account=posting.bank_account)


def supplier_bank_cash(ds: Dataset) -> dict[str, SupplierBankCash]:
    if ds.settings.currency not in MATERIAL_CURRENCIES:
        return {}
    units = material_units(ds.settings.currency)
    cash = {}
    for invoice in ds.supplier_invoices:
        for number, payment in enumerate(invoice.payments, 1):
            voucher = f"{invoice.id}/{number}"
            cash[voucher] = SupplierBankCash(invoice=invoice.id, payment_number=number, voucher=voucher,
                supplier=invoice.supplier, date=payment.date, reference=payment.reference,
                amount_minor=(1 if payment.reverses else -1) * units.minor(payment.amount), bank_account=payment.bank_account)
    return cash


def bank_view(ds: Dataset, bills: list[CarrierBill]) -> CarrierBankView:
    unmatched = []
    posted = []
    reversible = []
    fees = {line: posting for _, line, posting in bank_return_fees(ds)}
    timing = [CarrierBankTiming(account=line.account, voucher=line.active[0].voucher, statement_line=line.id,
                                bank_date=line.date, posting_date=line.history[0].date,
                                amount_minor=line.amount_minor, reason=line.history[0].allocation.late_reason,
                                additional_vouchers=[target.voucher for target in line.active[1:]]
                                + ([fees[line.id].voucher] if line.id in fees else []))
              for line in ds.carrier_bank_lines if line.active and line.history[0].allocation and line.history[0].allocation.late_reason]
    lines = {line.id: line for line in ds.carrier_bank_lines}
    locked = _locked_reversal_lines(bills)
    sources = _original_matches(ds)
    for bill in bills:
        available = set(bill.unreconciled_cash)
        latest = bill.latest_monetary_date()
        returned = bill.returned_principal()
        for voucher, event in bill.reversals():
            if not event.late_reason or event.allocated:
                continue
            line = lines.get(event.statement_line)
            if (line and line.reversal and (line.account, line.company, line.amount_minor) == (
                    event.bank_account, bill.company, event.amount_minor) and line.date < event.date
                    and [target.key() for target in line.active] == [(bill.order, voucher)]):
                timing.append(CarrierBankTiming(account=line.account, voucher=voucher, statement_line=line.id,
                                                bank_date=line.date, posting_date=event.date,
                                                amount_minor=event.amount_minor, reason=event.late_reason))
        for posting in bill.cash():
            posted.append(posting)
            if posting.voucher in available:
                unmatched.append(_cash(bill, posting))
            original = sources.get((bill.order, posting.voucher))
            remaining = abs(posting.amount_minor) - returned.get(posting.voucher, 0)
            if original and remaining:
                reversible.append(ReversibleCash(**_cash(bill, posting).model_dump(),
                                                  original_line=original.statement_line, original_bank_date=original.date,
                                                  eligible_from=max(latest, original.date), remaining_minor=remaining,
                                                  full_return_eligible=len(original.active) == 1 and original.id not in locked,
                                                  source_trace_ids=original.trace_ids if len(original.active) == 1
                                                  and len(original.trace_ids) == 1 else []))
    supplier_postings = supplier_bank_cash(ds)
    posted.extend(item.posting() for item in supplier_postings.values())
    matched = {line.active_supplier.voucher for line in ds.carrier_bank_lines if line.active_supplier}
    suppliers = [item for voucher, item in supplier_postings.items() if item.bank_account and voucher not in matched]
    return CarrierBankView(lines=sorted(ds.carrier_bank_lines, key=lambda line: (line.date, line.id), reverse=True),
                           unmatched_cash=unmatched, periods=tie_out(ds, [*posted, *fees.values()], timing), reversible_cash=reversible,
                           locked_lines=sorted(locked), timing=timing, unmatched_supplier_cash=suppliers)


def _locked_reversal_lines(bills: list[CarrierBill]) -> set[str]:
    return {line for bill in bills for _, event in bill.reversals() for line in (event.original_line, event.statement_line)}


def _original_matches(ds: Dataset) -> dict[tuple[str, str], CarrierBankLine]:
    managed = statement_periods(ds)
    return {target.key(): row for row in ds.carrier_bank_lines if row.id in managed and not row.reversal for target in row.active}


def _legacy(ds: Dataset) -> dict[tuple[str, str, str], CarrierBankMatch]:
    return {(freight_company(ds, order), row.account.casefold(), row.statement_line.casefold()): row
            for order in ds.freight_orders for row in active_bank_matches(order.bill_events).values()}


def _read_lines(company: str, account: str, currency_code: str, file: str) -> dict[tuple[str, str, str], CarrierBankLine]:
    if len(file.encode()) > 256_000:
        raise ValueError("the statement CSV can contain at most 256000 bytes")
    source = csv.reader(io.StringIO(file.lstrip("\ufeff"), newline=""), strict=True)
    lines = {}
    digits = material_units(currency_code).digits
    pattern = THREE_DECIMALS if digits == 3 else AMOUNT
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
            if currency != currency_code or not pattern.fullmatch(amount):
                raise ValueError(f"CSV row {source.line_num} needs company currency and an exact signed amount")
            minor = Decimal(amount).scaleb(digits)
            if minor != int(minor):
                raise ValueError(f"CSV row {source.line_num} needs company currency and an exact signed amount")
            try:
                on = date.fromisoformat(day)
                if on.isoformat() != day:
                    raise ValueError("date format")
                key = company, account.casefold(), statement.casefold()
                line = CarrierBankLine(id=_line_id(key), company=company, account=account,
                                       statement_line=statement, date=on, reference=reference,
                                       amount_minor=int(minor), currency=currency)
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
        if source:
            refreshed = []
            for row in ds.carrier_bank_lines:
                original = lines.get(row.id)
                if original is not None and row.reversal and not row.return_source_checked and not row.history:
                    row = _refresh_return(row, original)
                refreshed.append(row)
            if refreshed != ds.carrier_bank_lines:
                return ds.model_copy(update={"carrier_bank_lines": refreshed}), f"Verified return evidence for statement {period.number}."
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
                            reversal=entry.reversal, trace_ids=list(entry.trace_ids), return_source_checked=entry.reversal,
                            included_fee_minor=entry.included_fee_minor, unresolved_charges=entry.unresolved_charges,
                            requires_allocation=entry.requires_allocation)
            for entry in statement.entries]
    return _append_period(ds, account, statement.header, rows, statement.file_sha256, statement.source)


def _refresh_return(row: CarrierBankLine, original: CarrierBankLine) -> CarrierBankLine:
    return row.model_copy(update={"return_source_checked": original.return_source_checked, "trace_ids": original.trace_ids,
                                  "included_fee_minor": original.included_fee_minor,
                                  "unresolved_charges": original.unresolved_charges})


def _validate_match(line: CarrierBankLine, targets: list[BankCashRef], cash: dict[tuple[str, str], CarrierCash], day: date,
                    period: CarrierBankPeriod | None, *, late_return: bool = False, allocated_return: bool = False) -> None:
    keys = [target.key() for target in targets]
    if len(keys) != len(set(keys)):
        raise ValueError("select each cash voucher once")
    total = -(line.included_fee_minor or 0) if allocated_return else 0
    for key in keys:
        leg = cash.get(key)
        if not leg or leg.company != line.company or (not allocated_return and (leg.amount_minor > 0) != (line.amount_minor > 0)):
            raise ValueError("cash vouchers must be unmatched and have the statement's entity and direction")
        if (leg.bank_account != (period.account if period else None)
                or (period and not late_return and not period.starts_on <= leg.date <= period.ends_on)):
            raise ValueError("the carrier cash must belong to the statement's registered account and posting period")
        if leg.reference.casefold() != line.reference.casefold():
            raise ValueError("the cash vouchers must share the statement's bank reference")
        if leg.date > day:
            raise ValueError("the reconciliation date cannot precede a selected cash posting")
        total += leg.amount_minor
    if total != line.amount_minor:
        raise ValueError("the signed cash vouchers must add up exactly to the statement line")


def _validate_supplier_match(line: CarrierBankLine, posting: SupplierBankCash | None, day: date,
                             period: CarrierBankPeriod | None) -> None:
    if (period is None or posting is None or posting.bank_account != period.account
            or not period.starts_on <= posting.date <= period.ends_on):
        raise ValueError("the supplier cash must belong to the statement's registered account and posting period")
    if line.requires_allocation:
        raise ValueError("grouped or fee-bearing bank cash requires a separate allocation")
    if line.included_fee_minor or line.unresolved_charges or (line.reversal and posting.amount_minor < 0):
        raise ValueError("resolve the return or its bank charges before matching the supplier cash")
    if supplier_payment_reference(posting.reference) != supplier_payment_reference(line.reference):
        raise ValueError("the supplier cash must share the statement's bank reference")
    if posting.amount_minor != line.amount_minor:
        raise ValueError("the signed supplier cash must equal the statement line exactly")
    if posting.date > day:
        raise ValueError("the reconciliation date cannot precede the supplier cash posting")


def _supplier_match(ds: Dataset, request: MatchSupplierStatement | ReleaseStatement, line: CarrierBankLine,
                    day: date) -> tuple[Dataset, str]:
    if request.version != len(line.history):
        raise ValueError("the statement match changed; review its current history")
    if day < (line.history[-1].date if line.history else line.date):
        raise ValueError("the reconciliation date cannot precede the statement or its last action")
    if ds.finance.closed_through is not None and day <= ds.finance.closed_through:
        raise ValueError("choose an open reconciliation date after the closed period")
    period = statement_periods(ds).get(line.id)
    if isinstance(request, MatchSupplierStatement):
        if line.active_supplier:
            raise ValueError("release the statement's current match first")
        target = request.target
        if any(row.active_supplier == target for row in ds.carrier_bank_lines):
            raise ValueError("that supplier cash already belongs to another statement match")
        _validate_supplier_match(line, supplier_bank_cash(ds).get(target.voucher), day, period)
        message = f"Matched {line.statement_line} to supplier cash {target.voucher}."
    else:
        if not line.active_supplier:
            raise ValueError("the statement has no active supplier match to release")
        target = None
        message = f"Released the supplier match for {line.statement_line}."
    event = BankMatchEvent(date=day, targets=[], supplier_payment=target)
    updated = line.model_copy(update={"history": [*line.history, event]})
    return ds.model_copy(update={"carrier_bank_lines": [updated if row.id == line.id else row for row in ds.carrier_bank_lines]}), message


def _check_return_source(line: CarrierBankLine, original: CarrierBankLine, period: CarrierBankPeriod | None) -> None:
    if (not line.reversal or period is None or period.camt_source is None or original.reversal
            or (line.company, line.account, line.currency) != (original.company, original.account, original.currency)
            or line.date < original.date):
        raise ValueError("a return requires a native statement and an earlier reconciled movement in the same entity, account and currency")
    if line.unresolved_charges:
        raise ValueError("resolve ambiguous bank charge evidence before posting this return")


def _check_reversal_source(line: CarrierBankLine, original: CarrierBankLine, period: CarrierBankPeriod | None) -> None:
    _check_return_source(line, original, period)
    if (line.included_fee_minor or line.amount_minor != -original.amount_minor
            or line.reference.casefold() != original.reference.casefold()):
        raise ValueError("a bank reversal requires native evidence of the full opposite movement with the original account and reference")


def _check_return_date(ds: Dataset, line: CarrierBankLine, day: date, late_reason: str) -> None:
    if line.reversal and not line.return_source_checked:
        raise ValueError("reattach the exact original bank statement to verify return fees and references before posting")
    if day < line.date or line.history:
        raise ValueError("select an unused reversal and a date on or after its bank booking date")
    if day != line.date:
        closed = ds.finance.closed_through
        if closed is None or line.date > closed or not late_reason:
            raise ValueError("a later posting requires a closed bank booking date and a reason")
    elif late_reason:
        raise ValueError("a late posting reason requires a date after the bank booking date")


def _record_reversal(ds: Dataset, request: ReverseBankCash, line: CarrierBankLine, day: date) -> tuple[Dataset, str]:
    _check_return_date(ds, line, day, request.late_reason)
    bills = list(carrier_bills(ds))
    locked = _locked_reversal_lines(bills)
    original = _original_matches(ds).get(request.original.key())
    if original is None or original.id in locked or len(original.active) != 1:
        raise ValueError("select one individually reconciled carrier payment or refund that has not already been reversed")
    _check_reversal_source(line, original, statement_periods(ds).get(line.id))
    bill = next((b for b in bills if b.order == request.original.order and any(
        cash.voucher == request.original.voucher for cash in b.cash())), None)
    if bill is None or day < bill.latest_monetary_date():
        raise ValueError("the posting date precedes a later cash or credit posting on this carrier bill")
    order = next(order for order in ds.freight_orders if order.id == bill.order)
    event = CarrierBankReversal(date=day, reverses=request.original.voucher, original_line=original.id, statement_line=line.id,
                                reference=line.reference, amount_minor=line.amount_minor, bank_account=line.account,
                                late_reason=request.late_reason)
    changed = order.model_copy(update={"bill_events": [*order.bill_events, event]})
    target = BankCashRef(order=bill.order, voucher=f"{bill.voucher}/V-{len(changed.bill_events)}")
    matched = line.model_copy(update={"history": [BankMatchEvent(date=day, targets=[target])]})
    return ds.model_copy(update={"freight_orders": [changed if f.id == order.id else f for f in ds.freight_orders],
                                 "carrier_bank_lines": [matched if row.id == line.id else row for row in ds.carrier_bank_lines]}), (
        f"Recorded and reconciled {target.voucher} reversing {event.reverses}.")


def _check_return_reference(line: CarrierBankLine, source: CarrierBankLine, advice: str) -> None:
    shared_trace = len(source.active) == 1 and len(line.trace_ids) == 1 and line.trace_ids == source.trace_ids
    if line.reference.casefold() != source.reference.casefold() and not (shared_trace or advice):
        raise ValueError("a changed bank reference requires a shared transaction trace or the identifier of reviewed bank advice")


def _record_allocation(ds: Dataset, request: AllocateBankReturn, line: CarrierBankLine, day: date) -> tuple[Dataset, str]:
    _check_return_date(ds, line, day, request.late_reason)
    source_lines = _original_matches(ds)
    period = statement_periods(ds).get(line.id)
    allocation = BankReturnAllocation(legs=sorted(request.legs, key=lambda leg: leg.original.key()),
                                      advice=request.advice, late_reason=request.late_reason)
    keys = {leg.original.key() for leg in allocation.legs}
    if len(keys) != len(allocation.legs):
        raise ValueError("select each original carrier cash voucher once")
    if allocation.advice and any(
            row.account == line.account and row.history and row.history[0].allocation
            and row.history[0].allocation.advice.casefold() == allocation.advice.casefold()
            for row in ds.carrier_bank_lines):
        raise ValueError("that bank advice identifier already belongs to a return on this account")
    vouchers = {(bill.order, posting.voucher): (bill, posting)
                for bill in carrier_bills(ds) if not bill.credited_on for posting in bill.cash()
                if (bill.order, posting.voucher) in keys}
    orders = {order.id: order for order in ds.freight_orders}
    targets = []
    total = -(line.included_fee_minor or 0)
    direction = 0
    remaining_by_order: dict[str, dict[str, int]] = {}
    for leg in allocation.legs:
        key = leg.original.key()
        source = source_lines.get(key)
        if source is None or key not in vouchers:
            raise ValueError("select reconciled original carrier cash for each return leg")
        _check_return_source(line, source, period)
        _check_return_reference(line, source, allocation.advice)
        bill, posting = vouchers[key]
        if day < bill.latest_monetary_date():
            raise ValueError("the posting date precedes a later cash or credit posting on a selected carrier bill")
        if bill.order not in remaining_by_order:
            remaining_by_order[bill.order] = bill.returned_principal()
        remaining = abs(posting.amount_minor) - remaining_by_order[bill.order].get(posting.voucher, 0)
        if leg.amount_minor > remaining:
            raise ValueError("a return leg exceeds the original voucher's remaining principal")
        sign = 1 if posting.amount_minor < 0 else -1
        if direction and direction != sign:
            raise ValueError("one return allocation cannot mix payment and refund corrections")
        direction = sign
        total += sign * leg.amount_minor
        order = orders[bill.order]
        event = CarrierBankReversal(date=day, reverses=posting.voucher, original_line=source.id, statement_line=line.id,
                                    reference=line.reference, amount_minor=sign * leg.amount_minor, bank_account=line.account,
                                    late_reason=request.late_reason, allocated=True)
        orders[bill.order] = order.model_copy(update={"bill_events": [*order.bill_events, event]})
        targets.append(BankCashRef(order=bill.order, voucher=f"{bill.voucher}/V-{len(order.bill_events) + 1}"))
    if total != line.amount_minor:
        raise ValueError("signed return principal minus evidenced included bank fees must equal the booked statement amount")
    matched = line.model_copy(update={"history": [BankMatchEvent(date=day, targets=targets, allocation=allocation)]})
    return ds.model_copy(update={"freight_orders": list(orders.values()),
                                 "carrier_bank_lines": [matched if row.id == line.id else row for row in ds.carrier_bank_lines]}), (
        f"Allocated bank return {line.statement_line} to {len(targets)} carrier cash vouchers.")


def record_bank(ds: Dataset, request: BankOperation, day: date) -> tuple[Dataset, str]:
    domestic = ds.settings.currency in MATERIAL_CURRENCIES
    if domestic and isinstance(request, (ImportStatement, MatchStatement, ReverseBankCash, AllocateBankReturn)):
        raise ValueError("use a registered account period and reconcile it to recorded domestic supplier cash")
    if not domestic and isinstance(request, MatchSupplierStatement):
        raise ValueError("supplier statement matching supports domestic JPY and KWD")
    if isinstance(request, ImportStatement):
        return _import(ds, request)
    if isinstance(request, RegisterBankAccount):
        return _register(ds, request)
    if isinstance(request, ImportBankPeriod):
        if domestic and day < request.ends_on:
            raise ValueError("the bank evidence date cannot precede the statement close")
        return _import_period(ds, request)
    if isinstance(request, (CamtFile, CamtFiles)):
        return _camt(ds, request, day)
    line = next((row for row in ds.carrier_bank_lines if row.id == request.line), None)
    if line is None:
        raise ValueError("select an imported statement line in this company")
    if isinstance(request, MatchSupplierStatement) or (domestic and isinstance(request, ReleaseStatement)):
        return _supplier_match(ds, request, line, day)
    if isinstance(request, ReverseBankCash):
        return _record_reversal(ds, request, line, day)
    if isinstance(request, AllocateBankReturn):
        return _record_allocation(ds, request, line, day)
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
    supplier_claims: set[str] = set()
    domestic = new.settings.currency in MATERIAL_CURRENCIES
    legacy = _legacy(new)
    cash: dict[tuple[str, str], CarrierCash] = {}
    posted = []
    reversals: dict[str, dict[tuple[str, str], tuple[tuple[str, str], CarrierBankReversal]]] = defaultdict(dict)
    for bill in carrier_bills(new):
        legacy_vouchers = active_bank_matches(bill.events)
        for posting in bill.cash():
            posted.append((bill.company, posting))
            if posting.voucher not in legacy_vouchers:
                cash[bill.order, posting.voucher] = _cash(bill, posting)
        for voucher, event in bill.reversals():
            reversals[event.statement_line][bill.order, voucher] = ((bill.order, event.reverses), event)
    posted.extend((company, posting) for company, _, posting in bank_return_fees(new))
    supplier_postings = supplier_bank_cash(new)
    posted.extend(("", item.posting()) for item in supplier_postings.values())
    periods = protect_accounts(old, new, command, {line.id: line for line in new.carrier_bank_lines}, posted)
    accounts = BankAccounts(new).by_id
    lines = {row.id: row for row in new.carrier_bank_lines}
    for line_id, corrections in reversals.items():
        reversal = lines.get(line_id)
        if reversal is None or len(reversal.history) != 1 or {target.key() for target in reversal.active} != corrections.keys():
            raise ValueError("a posted bank reversal must retain both of its original statement allocations")
        match = reversal.history[0]
        allocation = match.allocation
        legs = {leg.original.key(): leg.amount_minor for leg in allocation.legs} if allocation else {}
        actual_legs = {original_key: abs(event.amount_minor) for original_key, event in corrections.values()}
        if (allocation and (len(legs) != len(corrections) or legs != actual_legs
                             or len({event.amount_minor > 0 for _, event in corrections.values()}) != 1)
                or not allocation and len(corrections) != 1):
            raise ValueError("a return must retain its original principal allocations")
        first = next(iter(corrections.values()))[1]
        if first.late_reason:
            closed = new.finance.closed_through
            if closed is None or reversal.date > closed or reversal.date >= match.date:
                raise ValueError("a late return must retain its closed bank date and later accounting date")
        elif reversal.date != match.date:
            raise ValueError("a reversal posted across accounting periods must retain its reason")
        for original_key, event in corrections.values():
            original = lines.get(event.original_line)
            if (original is None or original.id not in periods or original_key not in {target.key() for target in original.active}
                    or event.date != match.date or event.allocated != bool(allocation)
                    or event.late_reason != (allocation.late_reason if allocation else first.late_reason)):
                raise ValueError("a posted bank reversal must retain both of its original statement allocations")
            if allocation:
                _check_return_source(reversal, original, periods.get(line_id))
                _check_return_reference(reversal, original, allocation.advice)
            elif len(original.active) == 1:
                _check_reversal_source(reversal, original, periods.get(line_id))
            else:
                raise ValueError("a legacy reversal requires one individually matched voucher")
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
        if ((domestic and (row.id not in periods or any(event.targets for event in row.history)))
                or (not domestic and any(event.supplier_payment for event in row.history))):
            raise ValueError("domestic supplier matches require a registered JPY or KWD account period")
        native = row.id in periods and periods[row.id].camt_source
        if (((row.trace_ids or row.requires_allocation) and not native)
                or row.return_source_checked and not row.reversal
                or (row.included_fee_minor is not None or row.unresolved_charges) and not row.return_source_checked
                or row.reversal and (not native or (row.active and row.id not in reversals))
                or any(entry.allocation for entry in row.history) and (not row.return_source_checked or row.id not in reversals)):
            raise ValueError("a marked reversal must keep its native source and match only its reversal posting")
        keys.add(key)
        earlier = prior.get(row.id)
        if (earlier is not None and command and native and earlier.reversal and not earlier.history
                and not row.history and not earlier.return_source_checked and row.return_source_checked):
            earlier = _refresh_return(earlier, row)
        if earlier is not None and (row.model_dump(exclude={"history"}) != earlier.model_dump(exclude={"history"})
                                    or row.history[:len(earlier.history)] != earlier.history
                                    or len(row.history) > len(earlier.history) + 1):
            raise ValueError("statement source and match history are retained")
        if row.active:
            late = row.id in reversals and bool(next(iter(reversals[row.id].values()))[1].late_reason)
            _validate_match(row, row.active, cash, row.history[-1].date, periods.get(row.id), late_return=late,
                            allocated_return=row.history[-1].allocation is not None)
            active_keys = {target.key() for target in row.active}
            if active_keys & claimed:
                raise ValueError("that cash voucher already belongs to another statement match")
            claimed.update(active_keys)
        for event in row.history:
            if event.supplier_payment:
                _validate_supplier_match(row, supplier_postings.get(event.supplier_payment.voucher), event.date, periods.get(row.id))
        if row.active_supplier:
            voucher = row.active_supplier.voucher
            if voucher in supplier_claims:
                raise ValueError("that supplier cash already belongs to another statement match")
            supplier_claims.add(voucher)
