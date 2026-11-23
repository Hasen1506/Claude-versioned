"""A booked carrier cash return must reopen AP and reconcile both bank movements."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from xml.etree import ElementTree as XML

import pytest

from scp.accounting import view
from scp.companies import commands, get_companies
from scp.finance.cash import cash_view
from scp.plan.result import PlanResult
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_carrier_account_reconciliation import fixture, send
from .test_commercial_integrity import save
from .test_companies import h, new_company, signup
from .test_company_commands import command
from .test_enterprise_integrity import client, team
from .test_grouped_carrier_bank import P1, P2, bank, saved
from .test_native_carrier_bank import native_file

P3 = P2 + timedelta(days=1)
NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"


def statement(on, opening, movement, ref, *, reversal=None, account=None):
    root = XML.fromstring(native_file().strip("\ufeff"))
    hdr = root.find(".//{*}GrpHdr")
    hdr.find("{*}MsgId").text = f"MSG-{on}-{ref}"
    hdr.find("{*}CreDtTm").text = f"{on}T23:59:59+05:30"
    stmt = root.find(".//{*}Stmt")
    stmt.find("{*}Id").text = f"STMT-{on}"
    stmt.find("{*}FrToDt/{*}FrDtTm").text = f"{on}T00:00:00+05:30"
    stmt.find("{*}FrToDt/{*}ToDtTm").text = f"{on}T23:59:59+05:30"
    if account:
        stmt.find("{*}Acct/{*}Id/{*}IBAN").text = account
    for bal, amount, day in zip(stmt.findall("{*}Bal"), [opening, opening + movement], [on - timedelta(days=1), on], strict=True):
        bal.find("{*}Amt").text = f"{amount / 100:.2f}"
        bal.find("{*}Dt/{*}Dt").text = str(day)
    summary = stmt.find("{*}TxsSummry")
    direction = "CRDT" if movement > 0 else "DBIT"
    minor = f"{abs(movement) / 100:.2f}"
    summary.find("{*}TtlNtries/{*}Sum").text = minor
    summary.find("{*}TtlNtries/{*}TtlNetNtry/{*}Amt").text = minor
    summary.find("{*}TtlNtries/{*}TtlNetNtry/{*}CdtDbtInd").text = direction
    for tag, sign in [("TtlCdtNtries", "CRDT"), ("TtlDbtNtries", "DBIT")]:
        subtotal = summary.find(f"{{*}}{tag}")
        subtotal.find("{*}NbOfNtries").text = "1" if sign == direction else "0"
        subtotal.find("{*}Sum").text = minor if sign == direction else "0"
    entry = stmt.find("{*}Ntry")
    entry.find("{*}Amt").text = minor
    entry.find("{*}CdtDbtInd").text = direction
    entry.find("{*}BookgDt/{*}Dt").text = str(on)
    entry.find("{*}AcctSvcrRef").text = f"SVCR-{on}"
    entry.find("{*}NtryDtls/{*}Btch/{*}PmtInfId").text = ref
    if reversal is not None:
        entry.insert(3, XML.Element(f"{{{NS}}}RvslInd"))
        entry[3].text = reversal
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + XML.tostring(root, encoding="unicode", default_namespace=None)


def reverse(token, cid, identifier, revision, day, line, original, *, action="reverse_cash"):
    return command(token, cid, identifier, "carrier_bank", action, revision, date=str(day),
                   event={"kind": "reverse_cash", "line": line, "original": {"order": "FO-1", "voucher": original}})


def import_statement(token, cid, identifier, revision, day, xml):
    return command(token, cid, identifier, "carrier_bank", "record", revision, date=str(day),
                   event={"kind": "import_camt", "account": "BANK-A", "xml": xml})


def setup_paid():
    ds = fixture()
    roles = {**ds.finance.control_roles, "period_close": ["owner@integrity.example"]}
    ds.finance.control_roles = roles
    owner, treasury, cid = team(ds)
    opening = dict(id="BANK-A", company="E1", starts_on=str(P1), opening_minor=20_000)
    saved(bank(owner, cid, "register", 1, "register_account", **opening))
    payment_xml = statement(P1, 20_000, -4025, "WIRE-1")
    saved(bank(owner, cid, "link", 2, "link_camt_source", account="BANK-A", xml=payment_xml))
    saved(send(treasury, cid, "pay", 3, "pay_bill", P1, "FO-1", amount=40.25, reference="WIRE-1", bank_account="BANK-A"))
    imported = saved(bank(treasury, cid, "import", 4, "import_camt", account="BANK-A", xml=payment_xml))
    return owner, treasury, cid, imported.carrier_bank_lines[0].id


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
@pytest.mark.parametrize("refund", [False, True], ids=["payment", "refund"])
def test_native_return_is_a_separate_reconciled_and_recoverable_ap_posting(backend, refund, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    owner, treasury, cid, payment_line = setup_paid()
    matched = saved(bank(treasury, cid, "match-payment", 5, "match", line=payment_line, version=0,
                         targets=[{"order": "FO-1", "voucher": "FO-1/P-1"}]))
    original, original_line, amount, opening, revision, when, reference = "FO-1/P-1", payment_line, 4025, 15_975, 6, P2, "WIRE-1"
    if refund:
        credit = dict(kind="adjust_bill", amount_minor=1225, reference="CREDIT", reason="Carrier acknowledged overcharge")
        saved(send(owner, cid, "credit", 6, "bill_event", P2, "FO-1", event=credit))
        payment = dict(kind="refund_bill", amount_minor=1225, reference="REFUND-1", bank_account="BANK-A")
        saved(send(treasury, cid, "refund", 7, "bill_event", P2, "FO-1", event=payment))
        xml = statement(P2, 15_975, 1225, "REFUND-1")
        received = saved(bank(treasury, cid, "import-refund", 8, "import_camt", account="BANK-A", xml=xml))
        original_line = received.carrier_bank_lines[-1].id
        original, amount, opening, revision, when, reference = "FO-1/R-2", -1225, 17_200, 10, P3, "REFUND-1"
        matched = saved(bank(treasury, cid, "match-refund", 9, "match", line=original_line, version=0,
                             targets=[{"order": "FO-1", "voucher": original}]))
    before = view(matched, period_end=when - timedelta(days=1))
    reversal_xml = statement(when, opening, amount, reference, reversal="1" if refund else "true")
    imported = saved(import_statement(treasury, cid, "import-return", revision, when, reversal_xml))
    revision += 1
    reversal_line = imported.carrier_bank_lines[-1]
    assert reversal_line.reversal and reversal_line.amount_minor == amount and not reversal_line.active
    feed = payables_view(imported).carrier_bank
    assert {v.voucher for v in feed.reversible_cash} >= {original}
    first_period = feed.periods[0]
    assert not first_period.reconciled and first_period.period.closing_minor - first_period.ledger_closing_minor == amount
    assert view(imported, period_end=when) == view(matched, period_end=when)
    assert reverse(treasury, cid, "wrong-action", revision, when, reversal_line.id, original, action="record").status_code == 422
    assert reverse(treasury, cid, "wrong-date", revision, when + timedelta(days=1), reversal_line.id, original).status_code == 409
    assert reverse(owner, cid, "wrong-role", revision, when, reversal_line.id, original).status_code == 403
    outsider = signup("other-tenant@reversal.example")
    other_company = new_company(outsider)
    assert reverse(outsider, other_company, "other-tenant", 1, when, reversal_line.id, original).status_code == 409
    assert reverse(treasury, cid, "ordinary-line", revision, P1, payment_line, original).status_code == 409
    regular = bank(treasury, cid, "wrong-match", revision, "match", line=reversal_line.id, version=0,
                   targets=[{"order": "FO-1", "voucher": original}])
    assert regular.status_code == 409 and "own reversal posting" in regular.text
    before_failure = client.get(f"/api/companies/{cid}", headers=h(treasury)).json()

    def fail_receipt(*args, **kwargs):
        raise OSError("forced reversal receipt failure")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail_receipt)
        with pytest.raises(OSError, match="forced reversal receipt failure"):
            reverse(treasury, cid, "return", revision, when, reversal_line.id, original)
    assert client.get(f"/api/companies/{cid}", headers=h(treasury)).json() == before_failure
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: reverse(treasury, cid, "return", revision, when, reversal_line.id, original), range(2)))
    result = saved(results[0])
    assert sorted(reply.json()["duplicate"] for reply in results) == [False, True]
    revision += 1
    assert reverse(treasury, cid, "return", revision, when, reversal_line.id, "FO-1/P-99").status_code == 409
    assert reverse(treasury, cid, "second-post", revision, when, reversal_line.id, original).status_code == 409
    assert view(result, period_end=when - timedelta(days=1)) == before
    purchase = payables_view(result)
    bill = next(bill for bill in purchase.carrier_bills if bill.order == "FO-1")
    correction_id, correction = next(bill.reversals())
    assert correction.reverses == original and correction.original_line == original_line
    assert bill.open_at(when - timedelta(days=1)) == 0
    assert bill.open_at(when) == amount / 100
    assert bill.status == ("refund due" if refund else "to pay")
    assert not bill.unreconciled_cash
    assert set(purchase.carrier_bank.locked_lines) == {original_line, reversal_line.id}
    assert all(period.reconciled for period in purchase.carrier_bank.periods)
    correction_gl = next(v for v in view(result, period_end=when).vouchers if v.number == correction_id)
    assert (correction_gl.date, correction_gl.company) == (when, "E1")
    assert {row.account: round((row.debit - row.credit) * 100) for row in correction_gl.lines} == {
        "BANK": amount, "PAYABLES": -amount,
    }
    assert next(row for row in correction_gl.lines if row.account == "BANK").bank_account == "BANK-A"
    receipt = client.get(f"/api/companies/{cid}/commands", params={"id": "return"}, headers=h(treasury)).json()
    assert (receipt["revision"], receipt["posting_date"], receipt["action"]) == (revision, str(when), "reverse_cash")
    db = get_companies().db
    assert db.execute("SELECT COUNT(*) FROM company_commands WHERE company_id = ? AND command_id = ?", (cid, "return")).fetchone()[0] == 1
    for index, line in enumerate([original_line, reversal_line.id]):
        assert bank(treasury, cid, f"release-{index}", revision, "release", line=line, version=1).status_code == 409

    plan = PlanResult(ok=True, currency="INR", carrying_rate=0)
    settings = matched.settings.model_copy(update={"planning_start": when})
    forecasts = [cash_view(data.model_copy(update={"settings": settings}), plan, weeks=12) for data in (matched, result)]
    if refund:
        before_cash, after_cash = (forecast.weeks[0].by for forecast in forecasts)
        assert after_cash.get("carrier_refunds", 0) - before_cash.get("carrier_refunds", 0) == 12.25
        payment = dict(kind="refund_bill", amount_minor=1225, reference="REFUND-2", bank_account="BANK-A")
        repaid = saved(send(treasury, cid, "refund-again", revision, "bill_event", when, "FO-1", event=payment))
    else:
        before_cash, after_cash = (sum(week.by.get("freight", 0) for week in forecast.weeks) for forecast in forecasts)
        assert round(after_cash - before_cash, 2) == -40.25
        repaid = saved(send(treasury, cid, "pay-again", revision, "pay_bill", when, "FO-1", amount=40.25, reference="WIRE-2",
                            bank_account="BANK-A"))
    assert next(bill for bill in payables_view(repaid).carrier_bills if bill.order == "FO-1").open == 0


def test_bank_returns_with_wrong_evidence_and_closed_posting_date_stay_unposted():
    owner, treasury, cid, payment_line = setup_paid()
    original = "FO-1/P-1"
    saved(bank(treasury, cid, "match-payment", 5, "match", line=payment_line, version=0,
               targets=[{"order": "FO-1", "voucher": original}]))
    wrong = saved(bank(treasury, cid, "import-wrong-ref", 6, "import_camt", account="BANK-A",
                       xml=statement(P2, 15_975, 4025, "OTHER-BANK-REF", reversal="true")))
    error = reverse(treasury, cid, "wrong-ref", 7, P2, wrong.carrier_bank_lines[-1].id, original)
    assert error.status_code == 409 and "original account and reference" in error.text
    partial = saved(import_statement(treasury, cid, "import-partial", 7, P3, statement(P3, 20_000, 4024, "WIRE-1", reversal="true")))
    error = reverse(treasury, cid, "partial", 8, P3, partial.carrier_bank_lines[-1].id, original)
    assert error.status_code == 409 and "full opposite" in error.text
    later = P3 + timedelta(days=1)
    good = saved(import_statement(treasury, cid, "import-right", 8, later, statement(later, 24_024, 4025, "WIRE-1", reversal="true")))
    line = good.carrier_bank_lines[-1]
    closed = good.model_copy(update={"finance": good.finance.model_copy(update={"closed_through": later})})
    assert save(owner, cid, closed, 9).status_code == 200
    error = reverse(treasury, cid, "closed-period", 10, later, line.id, original)
    assert error.status_code == 403 and "closed" in error.text
    current = client.get(f"/api/companies/{cid}", headers=h(treasury)).json()
    assert current["meta"]["revision"] == 10
    assert not current["dataset"]["carrier_bank_lines"][-1]["history"]
