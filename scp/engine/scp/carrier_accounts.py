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


def check_window(period: CarrierBankPeriod, account: CarrierBankAccount, prior: CarrierBankPeriod | None,
                 lines: dict[str, CarrierBankLine]) -> None:
    start = prior.ends_on.toordinal() + 1 if prior else account.starts_on.toordinal()
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
    for prior, retained in ((old.carrier_bank_accounts, new.carrier_bank_accounts), (old.carrier_bank_periods, new.carrier_bank_periods)):
        if retained[:len(prior)] != prior or len(retained) > len(prior) + 1:
            raise ValueError("bank account openings and source statement periods are retained")
    accounts = BankAccounts(new)
    if len(accounts.by_id) != len(new.carrier_bank_accounts) or any(
            a.currency != new.settings.currency or (a.company and a.company not in new.entity_by_id)
            for a in new.carrier_bank_accounts):
        raise ValueError("registered bank accounts must be unique and keep their company and currency")
    for company, posting in postings:
        accounts.check_posting(company, posting.date, posting.bank_account)
    previous: dict[str, CarrierBankPeriod] = {}
    owned: dict[str, CarrierBankPeriod] = {}
    identifiers = set()
    for period in new.carrier_bank_periods:
        account = accounts.by_id.get(period.account)
        if (account is None or period.id in identifiers or period.id != period_id(period.account, period.number)
                or any(line in owned for line in period.line_ids)):
            raise ValueError("a source statement and its lines can occur only once within its registered account")
        check_window(period, account, previous.get(period.account), lines)
        previous[period.account] = period
        identifiers.add(period.id)
        owned.update(dict.fromkeys(period.line_ids, period))
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
