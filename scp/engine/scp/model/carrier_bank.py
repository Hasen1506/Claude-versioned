"""Source statement lines and append-only matches to carrier cash vouchers."""
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Id, Model


BankAccountId = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")]
BankMinor = Annotated[int, Field(strict=True, ge=-999999999999999, le=999999999999999)]
BankDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


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


class CamtSourceEvidence(Model):
    format: Literal["camt.053.001.08"] = "camt.053.001.08"
    message_id: str = Field(min_length=1, max_length=35)
    byte_count: int = Field(strict=True, ge=1, le=256_000)


class CarrierBankPeriod(BankStatementHeader):
    id: Id
    file_sha256: BankDigest
    line_ids: list[Id] = Field(max_length=500)
    camt_source: CamtSourceEvidence | None = Field(None, exclude_if=lambda value: value is None)


class BankCashRef(Model):
    order: str = Field(min_length=1, max_length=20)
    voucher: str = Field(min_length=1, max_length=64)

    def key(self) -> tuple[str, str]:
        return self.order, self.voucher


class BankMatchEvent(Model):
    date: date
    targets: list[BankCashRef] = Field(max_length=100, description="Empty releases the preceding match")


class CarrierBankLine(Model):
    id: Id
    company: str = Field(max_length=64)
    account: str = Field(min_length=1, max_length=64)
    statement_line: str = Field(min_length=1, max_length=64)
    date: date
    reference: str = Field(min_length=1, max_length=64)
    amount_minor: BankMinor
    currency: str = Field(pattern=r"^[A-Z]{3}$")
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
            date_ = entry.date
        return self
