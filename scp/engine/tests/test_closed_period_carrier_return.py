"""Open-date carrier cash returns bridge closed statements without changing the closed books."""
from concurrent.futures import ThreadPoolExecutor
from csv import DictReader
from datetime import timedelta
from io import StringIO
from xml.etree import ElementTree as XML

import pytest

from scp.accounting import view
from scp.companies import commands
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_accounting_bank_export import export
from .test_backup_postgres import pg_databases as pg_databases
from .test_carrier_account_reconciliation import send
from .test_carrier_bank_reversal import P3, import_statement, setup_paid, statement
from .test_commercial_integrity import save
from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client
from .test_grouped_carrier_bank import D0, P2, bank, cash_keys, saved

REASON = "Return confirmed after the controller closed the bank booking date"


def quiet_statement(on, opening):
    document = XML.fromstring(statement(on, opening, 0, "QUIET"))
    book = document.find(".//{*}Stmt")
    book.remove(book.find("{*}Ntry"))
    for count in book.findall(".//{*}NbOfNtries"):
        count.text = "0"
    return XML.tostring(document, encoding="unicode")


def post_return(token, cid, key, revision, day, target, original, reason=REASON):
    return command(token, cid, key, "carrier_bank", "reverse_cash", revision, date=str(day),
                   event={"kind": "reverse_cash", "line": target, "original": {"order": "FO-1", "voucher": original},
                          "late_reason": reason})


def before_return(refund):
    owner, treasury, company, original_line = setup_paid()
    matched = saved(bank(treasury, company, "match-payment", 5, "match", line=original_line, version=0, targets=cash_keys("FO-1")))
    if not refund:
        return owner, treasury, company, matched, 6, "FO-1/P-1", P2, 15975, 4025, "WIRE-1"
    credit = dict(kind="adjust_bill", amount_minor=1225, reference="CREDIT", reason="Carrier acknowledged overcharge")
    saved(send(owner, company, "credit", 6, "bill_event", P2, "FO-1", event=credit))
    repayment = dict(kind="refund_bill", amount_minor=1225, reference="REFUND-1", bank_account="BANK-A")
    saved(send(treasury, company, "refund", 7, "bill_event", P2, "FO-1", event=repayment))
    imported = saved(import_statement(treasury, company, "refund-file", 8, P2, statement(P2, 15975, 1225, "REFUND-1")))
    voucher = "FO-1/R-2"
    matched = saved(bank(treasury, company, "match-refund", 9, "match", line=imported.carrier_bank_lines[-1].id, version=0,
                         targets=[{"order": "FO-1", "voucher": voucher}]))
    return owner, treasury, company, matched, 10, voucher, P3, 17200, -1225, "REFUND-1"


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
@pytest.mark.parametrize("refund", [False, True], ids=["payment-return", "refund-return"])
def test_late_return_reconciles_both_dates_without_reopening_the_closed_books(backend, refund, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    owner, treasury, company, data, revision, original, booked, opening, amount, reference = before_return(refund)
    middle, posting = booked + timedelta(days=1), booked + timedelta(days=2)
    closing = opening + amount
    gl_before = view(data, period_end=booked)
    xml = statement(booked, opening, amount, reference, reversal="true")

    def import_return(rev):
        return saved(import_statement(treasury, company, "late-source", rev, posting, xml))

    if not refund:
        data = import_return(revision)
        revision += 1
    closed = data.model_copy(update={"finance": data.finance.model_copy(update={"closed_through": booked})})
    assert save(owner, company, closed, revision).status_code == 200
    revision += 1
    if refund:
        closed = import_return(revision)
        revision += 1
    line = closed.carrier_bank_lines[-1]
    assert not payables_view(closed).carrier_bank.periods[0].reconciled
    assert post_return(treasury, company, "closed", revision, booked, line.id, original, reason="").status_code == 403
    assert post_return(treasury, company, "missing-reason", revision, posting, line.id, original, reason=" ").status_code == 409
    refused = post_return(treasury, company, "needs-period-control", revision, posting, line.id, original)
    assert refused.status_code == 403 and "period_close" in refused.text
    assert post_return(owner, company, "needs-payment-control", revision, posting, line.id, original).status_code == 403
    roles = {**closed.finance.control_roles, "period_close": ["owner@integrity.example", "buyer@integrity.example"]}
    configured = closed.model_copy(update={"finance": closed.finance.model_copy(update={"control_roles": roles})})
    assert save(owner, company, configured, revision).status_code == 200
    revision += 1
    snapshot = client.get(f"/api/companies/{company}", headers=h(owner)).json()

    def post():
        return post_return(treasury, company, "late-post", revision, posting, line.id, original)

    def fail_receipt(*args, **kwargs):
        raise OSError("simulated late-return receipt failure")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail_receipt)
        with pytest.raises(OSError, match="late-return receipt failure"):
            post()
    assert client.get(f"/api/companies/{company}", headers=h(owner)).json() == snapshot
    with ThreadPoolExecutor(2) as pool:
        one, two = pool.submit(post), pool.submit(post)
        results = [one.result(), two.result()]
    posted = saved(results[0])
    assert sorted(result.json()["duplicate"] for result in results) == [False, True]
    revision += 1

    assert view(posted, period_end=booked) == gl_before
    assert posted.carrier_bank_lines[-1].model_dump(exclude={"history"}) == line.model_dump(exclude={"history"})
    bill = next(b for b in payables_view(posted).carrier_bills if b.order == "FO-1")
    voucher, event = next(bill.reversals())
    assert event.date == posting and event.late_reason == REASON and event.reverses == original
    assert bill.open_at(booked) == bill.open_at(middle) == 0
    assert bill.open_at(posting) == amount / 100
    entry = next(v for v in view(posted, period_end=posting).vouchers if v.number == voucher)
    assert entry.date == posting and entry.company == "E1"
    assert {row.account: round((row.debit - row.credit) * 100) for row in entry.lines} == {"BANK": amount, "PAYABLES": -amount}
    receipt = client.get(f"/api/companies/{company}/commands", headers=h(owner), params={"id": "late-post"}).json()
    assert receipt["posting_date"] == str(posting) and receipt["parameters"]["event"]["late_reason"] == REASON
    assert bank(treasury, company, "release-source", revision, "release", line=line.id, version=1).status_code == 409

    saved(import_statement(treasury, company, "middle-file", revision, middle, quiet_statement(middle, closing)))
    result = saved(import_statement(treasury, company, "posting-file", revision + 1, posting, quiet_statement(posting, closing)))
    bank_state = payables_view(result).carrier_bank
    assert len(bank_state.timing) == 1 and bank_state.timing[0].bank_date == booked
    assert bank_state.timing[0].posting_date == posting and bank_state.timing[0].voucher == voucher
    rows = {row.period.ends_on: row for row in bank_state.periods}
    assert all(row.reconciled for row in rows.values())
    assert [(rows[d].opening_timing_minor, rows[d].closing_timing_minor) for d in (booked, middle, posting)] == [
        (0, amount), (amount, amount), (amount, 0),
    ]
    assert [rows[d].ledger_closing_minor for d in (booked, middle, posting)] == [opening, opening, closing]
    assert all(rows[d].has_timing and not rows[d].unmatched_vouchers for d in (booked, middle, posting))
    assert post_return(treasury, company, "other-id", revision + 2, posting, line.id, original).status_code == 409
    closed_csv = export("csv", result.model_dump(mode="json"), start=D0, end=booked)
    assert closed_csv.status_code == 200 and voucher not in closed_csv.json()["text"]
    open_csv = export("csv", result.model_dump(mode="json"), start=posting, end=posting)
    assert open_csv.status_code == 200
    bank_leg = next(row for row in DictReader(StringIO(open_csv.json()["text"])) if row["account"] == "BANK")
    assert (bank_leg["voucher"], bank_leg["date"], bank_leg["bank_account"]) == (voucher, str(posting), "BANK-A")
