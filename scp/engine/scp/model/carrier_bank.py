"""Source statement lines and append-only matches to carrier cash vouchers."""
from datetime import date
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Id, Model


BankAccountId = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")]
BankMinor = Annotated[int, Field(strict=True, ge=-999999999999999, le=999999999999999)]
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


class BankMatchEvent(Model):
    date: date
    targets: list[BankCashRef] = Field(max_length=100, description="Empty releases the preceding match")
    allocation: BankReturnAllocation | None = Field(None, exclude_if=lambda value: value is None)


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
    history: list[BankMatchEvent] = Field(default_factory=list)

    def source_key(self) -> tuple[str, str, str]:
        return self.company, self.account.casefold(), self.statement_line.casefold()

    @property
    def active(self) -> list[BankCashRef]:
        return self.history[-1].targets if self.history else []

    @model_validator(mode="after")
    def consistent_history(self) -> "CarrierBankLine":
        if not self.amount_minor:
            raise ValueError("a bank statement movement must have a nonzero signed amount")
        date_ = self.date
        for index, entry in enumerate(self.history):
            if entry.date < date_ or bool(entry.targets) != (index % 2 == 0):
                raise ValueError("a match and its release must follow the statement date in order")
            if len({r.key() for r in entry.targets}) != len(entry.targets):
                raise ValueError("a cash voucher is listed twice in the match")
            if entry.allocation and (not self.reversal or index or len(entry.targets) != len(entry.allocation.legs)):
                raise ValueError("a return allocation must belong to its first native reversal match")
            date_ = entry.date
        return self
