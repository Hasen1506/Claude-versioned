"""Source statement lines and append-only matches to carrier cash vouchers."""
from datetime import date
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Id, Model


BankAccountId = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")]
MAX_BANK_MINOR = 999_999_999_999_999
BankMinor = Annotated[int, Field(strict=True, ge=-MAX_BANK_MINOR, le=MAX_BANK_MINOR)]
ReturnMinor = Annotated[BankMinor, Field(gt=0)]
BankDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CAMT_MAX_PAGES = 20
CAMT_MAX_BYTES = 256_000
CamtPageNumber = Annotated[int, Field(strict=True, ge=1, le=CAMT_MAX_PAGES)]


class BankAccountOpening(Model):
    id: BankAccountId
    company: str = Field(max_length=64)
    starts_on: date
    opening_minor: BankMinor


class CamtAccountBinding(Model):
    account_sha256: BankDigest
    starts_on: date


class CarrierBankAccount(BankAccountOpening):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    camt_source: CamtAccountBinding | None = Field(None, exclude_if=lambda value: value is None)


class BankStatementHeader(Model):
    account: BankAccountId
    number: str = Field(min_length=1, max_length=64)
    starts_on: date
    ends_on: date
    opening_minor: BankMinor
    closing_minor: BankMinor
    line_count: int = Field(strict=True, ge=0, le=500)

    @model_validator(mode="after")
    def valid_window(self) -> "BankStatementHeader":
        if self.ends_on < self.starts_on:
            raise ValueError("a statement ends on or after its start date")
        return self


class CamtOriginal(Model):
    message_id: str = Field(min_length=1, max_length=35)
    file_sha256: BankDigest
    byte_count: int = Field(strict=True, ge=1, le=CAMT_MAX_BYTES)
    pages: list[CamtPageNumber] = Field(min_length=1, max_length=CAMT_MAX_PAGES)


class CamtSourceEvidence(Model):
    format: Literal["camt.053.001.08"] = "camt.053.001.08"
    message_id: str = Field(min_length=1, max_length=35)
    byte_count: int = Field(strict=True, ge=1, le=CAMT_MAX_BYTES)
    originals: list[CamtOriginal] = Field(default_factory=list, max_length=CAMT_MAX_PAGES, exclude_if=lambda files: not files)

    @model_validator(mode="after")
    def complete_manifest(self) -> "CamtSourceEvidence":
        if self.originals:
            pages = [page for file in self.originals for page in file.pages]
            if (not 2 <= len(pages) <= CAMT_MAX_PAGES or pages != list(range(1, len(pages) + 1))
                    or len({file.file_sha256 for file in self.originals}) != len(self.originals)
                    or (len(self.originals) > 1 and any(len(file.pages) != 1 for file in self.originals))
                    or sum(file.byte_count for file in self.originals) != self.byte_count
                    or self.originals[0].message_id != self.message_id):
                raise ValueError("camt.053 originals must account for every contiguous source page and byte")
        return self

    def manifest_sha256(self) -> str:
        if len(self.originals) == 1:
            return self.originals[0].file_sha256
        return sha256(b"scp/camt.053/page-set/v1\0" + b"".join(bytes.fromhex(file.file_sha256) for file in self.originals)).hexdigest()

    def message_ids(self) -> set[str]:
        return {file.message_id for file in self.originals} or {self.message_id}


class CarrierBankPeriod(BankStatementHeader):
    id: Id
    file_sha256: BankDigest
    line_ids: list[Id] = Field(max_length=500)
    camt_source: CamtSourceEvidence | None = Field(None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def valid_manifest(self) -> "CarrierBankPeriod":
        if self.camt_source and self.camt_source.originals and self.file_sha256 != self.camt_source.manifest_sha256():
            raise ValueError("the retained camt.053 checksum must agree with its original files")
        return self


class BankCashRef(Model):
    order: str = Field(min_length=1, max_length=20)
    voucher: str = Field(min_length=1, max_length=64)

    def key(self) -> tuple[str, str]:
        return self.order, self.voucher


class BankReturnLeg(Model):
    original: BankCashRef
    amount_minor: ReturnMinor


class BankReturnAllocation(Model):
    legs: list[BankReturnLeg] = Field(min_length=1, max_length=100)
    advice: str = Field("", max_length=120, exclude_if=lambda value: not value)
    late_reason: str = Field("", max_length=200, exclude_if=lambda value: not value)


class SupplierCashRef(Model):
    invoice: Id
    payment_number: int = Field(ge=1, strict=True)

    @property
    def voucher(self) -> str:
        return f"{self.invoice}/{self.payment_number}"


class SupplierDebitSource(Model):
    included_fee_minor: ReturnMinor | None = None
    unresolved_charges: bool = False


class SupplierClearing(Model):
    postings: list[SupplierCashRef] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=200)
    instruction: Id | None = Field(None, exclude_if=lambda value: value is None)
    return_of: Id | None = Field(None, exclude_if=lambda value: value is None)


class SupplierInstructionLeg(Model):
    invoice: Id
    amount_minor: ReturnMinor


class SupplierInstructionRejection(Model):
    date: date
    by: str
    message: str = Field(min_length=1, max_length=35)
    reason: str = Field(pattern=r"^[A-Z0-9]{1,4}$")
    file_sha256: BankDigest


class SupplierPaymentInstruction(Model):
    id: Annotated[str, Field(pattern=r"^SP-[a-f0-9]{28}$")]
    account: BankAccountId
    supplier: Id
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    execute_on: date
    proposed_on: date
    proposed_by: str = Field(min_length=1, max_length=254)
    routing_sha256: BankDigest
    legs: list[SupplierInstructionLeg] = Field(min_length=1, max_length=100)
    approved_on: date | None = None
    approved_by: str = ""
    cancelled_on: date | None = None
    cancelled_by: str = ""
    statement_line: Id | None = None
    rejection: SupplierInstructionRejection | None = Field(None, exclude_if=lambda value: value is None)

    @property
    def reserved(self) -> bool:
        return self.cancelled_on is None and self.statement_line is None and self.rejection is None

    @property
    def amount_minor(self) -> int:
        return sum(leg.amount_minor for leg in self.legs)


class BankMatchEvent(Model):
    date: date
    targets: list[BankCashRef] = Field(max_length=100, description="Empty releases the preceding match")
    allocation: BankReturnAllocation | None = Field(None, exclude_if=lambda value: value is None)
    supplier_payment: SupplierCashRef | None = Field(None, exclude_if=lambda value: value is None)
    supplier_clearing: SupplierClearing | None = Field(None, exclude_if=lambda value: value is None)


class CarrierBankLine(Model):
    id: Id
    company: str = Field(max_length=64)
    account: str = Field(min_length=1, max_length=64)
    statement_line: str = Field(min_length=1, max_length=64)
    date: date
    reference: str = Field(min_length=1, max_length=64)
    amount_minor: BankMinor
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reversal: bool = Field(False, strict=True, exclude_if=lambda value: not value)
    return_source_checked: bool = Field(False, strict=True, exclude_if=lambda value: not value)
    trace_ids: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    included_fee_minor: ReturnMinor | None = Field(None, exclude_if=lambda value: value is None)
    unresolved_charges: bool = Field(False, strict=True, exclude_if=lambda value: not value)
    requires_allocation: bool = Field(False, strict=True, exclude_if=lambda value: not value,
                                      description="Native supplier cash includes multiple transactions or bank charges")
    supplier_debit: SupplierDebitSource | None = Field(None, exclude_if=lambda value: value is None)
    history: list[BankMatchEvent] = Field(default_factory=list)

    def source_key(self) -> tuple[str, str, str]:
        return self.company, self.account.casefold(), self.statement_line.casefold()

    @property
    def active(self) -> list[BankCashRef]:
        return self.history[-1].targets if self.history else []

    @property
    def active_supplier(self) -> SupplierCashRef | None:
        return self.history[-1].supplier_payment if self.history else None

    @property
    def supplier_clearing(self) -> SupplierClearing | None:
        return self.history[0].supplier_clearing if self.history else None

    @property
    def supplier_fee(self) -> int:
        if not self.supplier_clearing:
            return 0
        if self.supplier_clearing.return_of:
            return self.included_fee_minor or 0
        return (self.supplier_debit.included_fee_minor or 0) if self.supplier_debit else 0

    def matched_vouchers(self) -> list[str]:
        if self.supplier_clearing:
            vouchers = [target.voucher for target in self.supplier_clearing.postings]
            if self.supplier_fee:
                vouchers.append(f"{self.id}/FEE")
            return vouchers
        return [self.active_supplier.voucher] if self.active_supplier else [target.voucher for target in self.active]

    @model_validator(mode="after")
    def consistent_history(self) -> "CarrierBankLine":
        if not self.amount_minor:
            raise ValueError("a bank statement movement must have a nonzero signed amount")
        date_ = self.date
        for index, entry in enumerate(self.history):
            if entry.date < date_ or bool(entry.targets or entry.supplier_payment or entry.supplier_clearing) != (index % 2 == 0):
                raise ValueError("a match and its release must follow the statement date in order")
            if entry.supplier_clearing and (len(self.history) != 1 or entry.targets or entry.supplier_payment or entry.allocation):
                raise ValueError("a posted supplier clearing retains its original statement and vouchers")
            if entry.supplier_clearing and (self.reversal != bool(entry.supplier_clearing.return_of)
                    or entry.supplier_clearing.return_of and entry.supplier_clearing.instruction):
                raise ValueError("supplier returns preserve the originating debit")
            if entry.supplier_payment and (entry.targets or entry.allocation):
                raise ValueError("a supplier match identifies exactly one payment or its reversal")
            if len({r.key() for r in entry.targets}) != len(entry.targets):
                raise ValueError("a cash voucher is listed twice in the match")
            if entry.allocation and (not self.reversal or index or len(entry.targets) != len(entry.allocation.legs)):
                raise ValueError("a return allocation must belong to its first native reversal match")
            date_ = entry.date
        return self
