"""Account ownership, statement continuity and reconciliation of posted carrier cash."""
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from hashlib import sha256
from operator import attrgetter

from .freight import BankPosting
from .model import Dataset
from .model.carrier_bank import CarrierBankAccount, CarrierBankLine, CarrierBankPeriod
from .model.common import Out


class BankAccounts:
    def __init__(self, ds: Dataset):
        self.by_id = {account.id: account for account in ds.carrier_bank_accounts}
        self.starts_on: dict[str, date] = {}
        for account in self.by_id.values():
            self.starts_on[account.company] = min(account.starts_on, self.starts_on.get(account.company, date.max))

    def check_posting(self, company: str, on: date, account_id: str | None) -> None:
        if account_id is None:
            if company in self.starts_on and on >= self.starts_on[company]:
                raise ValueError("choose a registered bank account for this carrier cash posting")
            return
        account = self.by_id.get(account_id)
        if account is None or account.company != company or on < account.starts_on:
            raise ValueError("the bank account must belong to the paying company and be active on the posting date")


def period_id(account: str, number: str) -> str:
    return "BP-" + sha256(f"{account}:{number.casefold()}".encode()).hexdigest()[:40]


def statement_periods(ds: Dataset) -> dict[str, CarrierBankPeriod]:
    return {line_id: period for period in ds.carrier_bank_periods for line_id in period.line_ids}


def last_period(ds: Dataset, account: str) -> CarrierBankPeriod | None:
    return next((p for p in reversed(ds.carrier_bank_periods) if p.account == account), None)


def next_start(account: CarrierBankAccount, prior: CarrierBankPeriod | None) -> int:
    return prior.ends_on.toordinal() + 1 if prior else account.starts_on.toordinal()


def check_window(period: CarrierBankPeriod, account: CarrierBankAccount, prior: CarrierBankPeriod | None,
                 lines: dict[str, CarrierBankLine]) -> None:
    start = next_start(account, prior)
    opening = prior.closing_minor if prior else account.opening_minor
    if period.starts_on.toordinal() != start or period.opening_minor != opening:
        raise ValueError("the statement must start on the next account date and carry forward the preceding closing balance")
    if len(period.line_ids) != period.line_count or len(set(period.line_ids)) != period.line_count:
        raise ValueError("the source statement line count must equal the distinct uploaded lines")
    activity = 0
    for line_id in period.line_ids:
        row = lines.get(line_id)
        if (row is None or (row.company, row.account, row.currency) != (account.company, account.id, account.currency)
                or not period.starts_on <= row.date <= period.ends_on):
            raise ValueError("all statement lines must belong to this bank account and statement period")
        activity += row.amount_minor
    if period.opening_minor + activity != period.closing_minor:
        raise ValueError("statement opening balance plus signed activity must equal closing balance")


def protect_accounts(old: Dataset, new: Dataset, command: bool, lines: dict[str, CarrierBankLine],
                     postings: Iterable[tuple[str, BankPosting]]) -> dict[str, CarrierBankPeriod]:
    if (old.carrier_bank_accounts != new.carrier_bank_accounts or old.carrier_bank_periods != new.carrier_bank_periods) and not command:
        raise ValueError("registered bank accounts and statement periods require an authoritative bank command")
    earlier, retained = old.carrier_bank_accounts, new.carrier_bank_accounts
    if not len(earlier) <= len(retained) <= len(earlier) + 1:
        raise ValueError("registered bank accounts are retained")
    for prior, current in zip(earlier, retained, strict=False):
        if prior == current:
            continue
        if (prior.camt_source is not None or current.camt_source is None
                or prior != current.model_copy(update={"camt_source": None})
                or current.camt_source.starts_on.toordinal() != next_start(prior, last_period(old, prior.id))):
            raise ValueError("bank account openings and existing camt.053 links are retained")
    earlier_periods, retained_periods = old.carrier_bank_periods, new.carrier_bank_periods
    if retained_periods[:len(earlier_periods)] != earlier_periods or len(retained_periods) > len(earlier_periods) + 1:
        raise ValueError("source statement periods are retained")
    accounts = BankAccounts(new)
    if len(accounts.by_id) != len(new.carrier_bank_accounts) or any(
            a.currency != new.settings.currency or (a.company and a.company not in new.entity_by_id)
            for a in new.carrier_bank_accounts):
        raise ValueError("registered bank accounts must be unique and keep their company and currency")
    bindings = [a.camt_source.account_sha256 for a in new.carrier_bank_accounts if a.camt_source is not None]
    if len(bindings) != len(set(bindings)):
        raise ValueError("a camt.053 source account can only be linked once in the company")
    for company, posting in postings:
        accounts.check_posting(company, posting.date, posting.bank_account)
    previous: dict[str, CarrierBankPeriod] = {}
    owned: dict[str, CarrierBankPeriod] = {}
    identifiers = set()
    messages = set()
    for period in new.carrier_bank_periods:
        account = accounts.by_id.get(period.account)
        if (account is None or period.id in identifiers or period.id != period_id(period.account, period.number)
                or any(line in owned for line in period.line_ids)):
            raise ValueError("a source statement and its lines can occur only once within its registered account")
        check_window(period, account, previous.get(period.account), lines)
        native = account.camt_source
        if bool(period.camt_source) != bool(native and period.starts_on >= native.starts_on):
            raise ValueError("a linked account requires native camt.053 evidence beginning on its linked date")
        if native and period.starts_on < native.starts_on <= period.ends_on:
            raise ValueError("the camt.053 link must start at a statement boundary")
        if period.camt_source:
            message = (account.id, period.camt_source.message_id)
            if message in messages:
                raise ValueError("a camt.053 message identifier can only be retained once per statement account")
            messages.add(message)
        previous[period.account] = period
        identifiers.add(period.id)
        owned.update(dict.fromkeys(period.line_ids, period))
    for account in new.carrier_bank_accounts:
        native = account.camt_source
        if native and not (account.starts_on <= native.starts_on
                           and native.starts_on.toordinal() <= next_start(account, previous.get(account.id))):
            raise ValueError("the camt.053 link must start at the recorded account or statement boundary")
    return owned


class CarrierBankTieOut(Out):
    period: CarrierBankPeriod
    ledger_opening_minor: int
    ledger_closing_minor: int
    unmatched_lines: list[str]
    unmatched_vouchers: list[str]
    reconciled: bool


def tie_out(ds: Dataset, postings: Iterable[BankPosting]) -> list[CarrierBankTieOut]:
    if not ds.carrier_bank_periods:
        return []
    lines = {line.id: line for line in ds.carrier_bank_lines}
    opening = {account.id: account.opening_minor for account in ds.carrier_bank_accounts}
    history: dict[str, list[BankPosting]] = defaultdict(list)
    for posting in postings:
        if posting.bank_account is not None and posting.bank_account in opening:
            history[posting.bank_account].append(posting)
    for entries in history.values():
        entries.sort(key=attrgetter("date", "voucher"))
    offset: dict[str, int] = defaultdict(int)
    results = []
    for period in ds.carrier_bank_periods:
        entries = history[period.account]
        end = bisect_right(entries, period.ends_on, lo=offset[period.account], key=attrgetter("date"))
        activity = entries[offset[period.account]:end]
        ledger_opening = opening[period.account]
        ledger_closing = ledger_opening + sum(posting.amount_minor for posting in activity)
        opening[period.account], offset[period.account] = ledger_closing, end
        matched = {target.voucher for key in period.line_ids for target in lines[key].active}
        missing_lines = [lines[key].statement_line for key in period.line_ids if not lines[key].active]
        missing_vouchers = [posting.voucher for posting in activity if posting.voucher not in matched]
        results.append(CarrierBankTieOut(period=period, ledger_opening_minor=ledger_opening, ledger_closing_minor=ledger_closing,
                                       unmatched_lines=missing_lines, unmatched_vouchers=missing_vouchers,
                                       reconciled=(not missing_lines and not missing_vouchers and ledger_opening == period.opening_minor
                                                   and ledger_closing == period.closing_minor)))
    return results[::-1]
