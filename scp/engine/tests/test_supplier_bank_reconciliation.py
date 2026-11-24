"""Recorded supplier cash matches complete source statements in native minor units."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from scp.accounting import csv_rows, view
from scp.camt_statements import read_statement
from scp.companies import commands
from scp.purchasing.payables import payables_view
from scp.versions import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import h, join, signup
from .test_company_commands import command
from .test_domestic_invoice_currency import balances, business, current, invoice, receive
from .test_enterprise_integrity import client

INV = "SI-00001"
ACCOUNT = "BANK-A"
HEADER = "line,date,reference,amount,currency\n"


def bank(user, cid, revision, day, event_kind, identifier=None, **fields):
    return command(user, cid, identifier or f"bank-{revision}", "carrier_bank", "record", revision, date=day,
                   event={"kind": event_kind, **fields})


def register(user, cid, revision, account=ACCOUNT, start="2026-01-08", opening=1000):
    return bank(user, cid, revision, start, "register_account", id=account, company="", starts_on=start,
                opening_minor=opening)


def pay(user, cid, revision, reference="WIRE-A", account=ACCOUNT, day="2026-01-08", amount=None):
    return command(user, cid, f"pay-{revision}", "purchasing", "pay_invoice", revision, date=day, po=INV,
                   reference=reference, bank_account=account, amount=amount)


def csv_period(user, cid, revision, raw, *, start="2026-01-08", end="2026-01-08", opening=1000,
               closing=999, account=ACCOUNT, day=None):
    return bank(user, cid, revision, day or end, "import_period", account=account, number=end,
                starts_on=start, ends_on=end, opening_minor=opening, closing_minor=closing,
                line_count=len(raw.splitlines()) - 1, csv=raw)


def match(user, cid, revision, line, number=1, version=0, day="2026-01-08", identifier=None):
    return bank(user, cid, revision, day, "match_supplier_payment", identifier, line=line,
                target={"invoice": INV, "payment_number": number}, version=version)


def reverse(user, cid, revision, ref="RETURN-A", account=None):
    return command(user, cid, f"reverse-{revision}", "purchasing", "reverse_invoice_payment", revision,
                   date="2026-01-09", po=INV, reference=ref, bank_account=account, payment_number=1, note="Returned by bank")


@pytest.mark.parametrize("currency,price,lexeme", [("JPY", 1, "1.00"), ("KWD", 0.001, "0.001")])
def test_registered_payment_and_return_tie_out_without_new_accounting_postings(currency, price, lexeme):
    owner, _, cid = business(currency, price)
    current(receive(owner, cid, 1, "2026-01-06", 1))
    current(invoice(owner, cid, 2, "2026-01-07"))
    current(register(owner, cid, 3))
    assert pay(owner, cid, 4, account=None).status_code == 409
    assert pay(owner, cid, 4, account="UNREGISTERED").status_code == 409
    posted = current(pay(owner, cid, 4))
    before = view(posted, period_end=date(2026, 1, 8))
    data = HEADER + f"L-1,2026-01-08,ＷＩＲＥ-a,-{lexeme},{currency}\n"
    assert csv_period(owner, cid, 5, data, day="2026-01-07").status_code == 409
    assert csv_period(owner, cid, 5, data, closing=998).status_code == 409
    imported = current(csv_period(owner, cid, 5, data))
    line = imported.carrier_bank_lines[0]
    assert line.amount_minor == -1
    pending = payables_view(imported).carrier_bank.periods[0]
    assert not pending.reconciled and pending.unmatched_vouchers == [f"{INV}/1"]
    matched = current(match(owner, cid, 6, line.id))
    result = payables_view(matched).carrier_bank
    assert result.periods[0].reconciled and result.periods[0].ledger_closing_minor == 999
    assert not result.unmatched_supplier_cash
    after = view(matched, period_end=date(2026, 1, 8))
    assert before == after and all(check.ok for check in after.checks)
    bank_voucher = next(v for v in after.vouchers if v.number == f"{INV}/1")
    assert [ln.bank_account for ln in bank_voucher.lines if ln.account == "BANK"] == [ACCOUNT]
    csv = csv_rows(after, matched, bank_detail=True)
    assert any(row[-1] == ACCOUNT and row[csv[0].index("voucher")] == f"{INV}/1" for row in csv[1:])
    assert reverse(owner, cid, 7, account="OTHER").status_code == 409
    assert reverse(owner, cid, 7, ref="WIRE-A").status_code == 409
    reversed_ = current(reverse(owner, cid, 7))
    assert balances(reversed_, "2026-01-08")["BANK"] == -Decimal(str(price))
    assert balances(reversed_, "2026-01-09")["PAYABLES"] == -Decimal(str(price))
    assert balances(reversed_, "2026-01-09")["BANK"] == 0
    data = HEADER + f"L-2,2026-01-09,RETURN-A,{lexeme},{currency}\n"
    imported = current(csv_period(owner, cid, 8, data, start="2026-01-09", end="2026-01-09", opening=999, closing=1000))
    line2 = imported.carrier_bank_lines[-1]
    assert match(owner, cid, 9, line2.id, day="2026-01-09").status_code == 409
    settled = current(match(owner, cid, 9, line2.id, number=2, day="2026-01-09"))
    assert all(period.reconciled for period in payables_view(settled).carrier_bank.periods)
    cleared = current(bank(owner, cid, 10, "2026-01-10", "release", line=line2.id, version=1))
    assert not payables_view(cleared).carrier_bank.periods[0].reconciled
    assert view(cleared, period_end=date(2026, 1, 10)) == view(settled, period_end=date(2026, 1, 10))
    assert match(owner, cid, 11, line2.id, number=2, day="2026-01-10").status_code == 409
    restored = current(match(owner, cid, 11, line2.id, number=2, version=2, day="2026-01-10"))
    assert len(restored.carrier_bank_lines[-1].history) == 3
    assert all(period.reconciled for period in payables_view(restored).carrier_bank.periods)


def native_fixture(currency):
    text = (Path(__file__).with_name("fixtures") / "camt053-booked.xml").read_text()
    text = text.replace("2026-03-03", "2026-01-08").replace("2026-03-02", "2026-01-07").replace("INR", currency)
    text = text.replace('>100.00</Amt>', '>0.999</Amt>', 1).replace('>200.00</Amt>', '>1.000</Amt>')
    text = text.replace(">100.00<", ">0.001<").replace("WIRE-COMB", "WIRE-A")
    text = text.replace("<NbOfTxs>2</NbOfTxs>", "<NbOfTxs>1</NbOfTxs>").replace(
        "<TxDtls><Refs><EndToEndId>FO-2-EXTERNAL</EndToEndId></Refs></TxDtls>", "")
    if currency == "JPY":
        text = text.replace(">0.999<", ">999.00<").replace(">1.000<", ">1000<").replace(">0.001<", ">1.00<")
    return text


@pytest.mark.parametrize("currency,wrong", [("JPY", "1.1"), ("KWD", "0.0011")])
def test_native_camt_amounts_totals_and_account_identity(currency, wrong):
    xml = native_fixture(currency)
    statement = read_statement(xml, ACCOUNT, currency)
    assert (statement.header.opening_minor, statement.header.closing_minor) == (1000, 999)
    assert statement.entries[0].amount_minor == -1
    assert not statement.entries[0].requires_allocation
    grouped = xml.replace("<NbOfTxs>1</NbOfTxs>", "<NbOfTxs>2</NbOfTxs>")
    assert read_statement(grouped, ACCOUNT, currency).entries[0].requires_allocation
    value = "1.00" if currency == "JPY" else "0.001"
    with pytest.raises(ValueError, match="decimal"):
        read_statement(xml.replace(f'<Amt Ccy="{currency}">{value}</Amt>', f'<Amt Ccy="{currency}">{wrong}</Amt>'), ACCOUNT, currency)
    with pytest.raises(ValueError, match="reported gross"):
        read_statement(xml.replace(f"<Sum>{value}</Sum>", "<Sum>0</Sum>", 1), ACCOUNT, currency)


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_native_supplier_match_is_authorized_atomic_and_replayable(backend, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)
        request.addfinalizer(store.db.close)
    owner, warehouse, cid = business("KWD", 0.001)
    treasury = signup("treasury@supplier-bank.example")
    join(owner, cid, "treasury@supplier-bank.example", "planner")
    original = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    original["finance"] = {"separate_payments": True, "control_roles": {
        "master_data": ["owner@integrity.example"], "billing": ["owner@integrity.example"],
        "warehouse": ["buyer@integrity.example"], "period_close": ["owner@integrity.example"],
        "payments": ["treasury@supplier-bank.example"],
    }}
    assert save(owner, cid, original, 1).status_code == 200
    current(receive(warehouse, cid, 2, "2026-01-06", 1))
    current(invoice(owner, cid, 3, "2026-01-07"))
    assert register(treasury, cid, 4).status_code == 403
    current(register(owner, cid, 4))
    current(pay(treasury, cid, 5))
    xml = native_fixture("KWD")
    current(bank(owner, cid, 6, "2026-01-08", "link_camt_source", account=ACCOUNT, xml=xml))
    imported = current(bank(treasury, cid, 7, "2026-01-08", "import_camt", account=ACCOUNT, xml=xml))
    retained = imported.carrier_bank_periods[0]
    assert retained.file_sha256 == sha256(xml.encode()).hexdigest()
    line = imported.carrier_bank_lines[0]
    assert match(warehouse, cid, 8, line.id).status_code == 403

    def post():
        return match(treasury, cid, 8, line.id, identifier="MATCH-RETRY")

    def fail(*args):
        raise OSError("bank receipt write failed")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail)
        with pytest.raises(OSError, match="bank receipt write failed"):
            post()
    kept = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    assert kept["meta"]["revision"] == 8 and not kept["dataset"]["carrier_bank_lines"][0]["history"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        queued = [pool.submit(post) for _ in range(2)]
        results = [handle.result(timeout=20) for handle in queued]
    assert {r.json()["duplicate"] for r in results if r.status_code == 200} == {False, True}
    confirmed = current(results[0])
    assert payables_view(confirmed).carrier_bank.periods[0].reconciled
    assert len(confirmed.carrier_bank_lines[0].history) == 1
    raw = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    raw["carrier_bank_lines"][0]["history"].append({"date": "2026-01-09", "targets": []})
    assert save(treasury, cid, raw, 9).status_code == 403
    raw = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    raw["finance"]["closed_through"] = "2026-01-08"
    assert save(owner, cid, raw, 9).status_code == 200
    assert bank(treasury, cid, 10, "2026-01-08", "release", line=line.id, version=1).status_code == 409
    released = current(bank(treasury, cid, 10, "2026-01-09", "release", line=line.id, version=1))
    assert len(released.carrier_bank_lines[0].history) == 2
    assert not payables_view(released).carrier_bank.periods[0].reconciled


def test_cutover_keeps_unassigned_history_and_requires_an_account_for_subsequent_cash():
    owner, _, cid = business("KWD", 0.001)
    current(receive(owner, cid, 1, "2026-01-06", 1))
    current(invoice(owner, cid, 2, "2026-01-07"))
    current(pay(owner, cid, 3, account=None))
    assert register(owner, cid, 4, start="2026-01-08").status_code == 403
    enrolled = current(register(owner, cid, 4, start="2026-01-09"))
    assert enrolled.supplier_invoices[0].payments[0].bank_account is None
    assert reverse(owner, cid, 5, ref="", account=None).status_code == 409
    paid_back = current(reverse(owner, cid, 5, account=ACCOUNT))
    assert paid_back.supplier_invoices[0].payments[1].bank_account == ACCOUNT
    raw = HEADER + "RETURN-LINE,2026-01-09,RETURN-A,0.001,KWD\n"
    sourced = current(csv_period(owner, cid, 6, raw, start="2026-01-09", end="2026-01-09", closing=1001))
    reconciled = current(match(owner, cid, 7, sourced.carrier_bank_lines[0].id, number=2, day="2026-01-09"))
    assert payables_view(reconciled).carrier_bank.periods[0].reconciled


def test_wrong_account_reference_and_duplicate_claim_leave_statement_differences_visible():
    owner, _, cid = business("KWD", 0.001)
    current(receive(owner, cid, 1, "2026-01-06", 1))
    current(invoice(owner, cid, 2, "2026-01-07"))
    current(register(owner, cid, 3))
    current(register(owner, cid, 4, account="BANK-B"))
    current(pay(owner, cid, 5))
    same_other_bank = HEADER + "B-1,2026-01-08,WIRE-A,-0.001,KWD\n"
    other = current(csv_period(owner, cid, 6, same_other_bank, account="BANK-B"))
    denied = match(owner, cid, 7, other.carrier_bank_lines[0].id)
    assert denied.status_code == 409 and "registered account" in denied.text
    data = HEADER + "".join(f"{key},2026-01-08,{ref},-0.001,KWD\n" for key, ref in [
        ("WRONG", "WIRE-B"), ("RIGHT", "WIRE-A"), ("DUPLICATE", "WIRE-A"),
    ])
    imported = current(csv_period(owner, cid, 7, data, closing=997))
    lines = {line.statement_line: line for line in imported.carrier_bank_lines}
    denied = match(owner, cid, 8, lines["WRONG"].id)
    assert denied.status_code == 409 and "bank reference" in denied.text
    matched = current(match(owner, cid, 8, lines["RIGHT"].id))
    already = match(owner, cid, 9, lines["DUPLICATE"].id)
    assert already.status_code == 409 and "another statement match" in already.text
    periods = {row.period.account: row for row in payables_view(matched).carrier_bank.periods}
    assert periods[ACCOUNT].unmatched_lines == ["WRONG", "DUPLICATE"]
    assert periods[ACCOUNT].ledger_closing_minor == 999
    assert periods[ACCOUNT].period.closing_minor == 997
    assert all(not row.reconciled for row in periods.values())
