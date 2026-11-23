"""Carry the original bank identity through the normal accounting export boundary."""
from csv import DictReader
from decimal import Decimal
from io import StringIO
from xml.etree import ElementTree as XML

import pytest

from scp import transport
from scp.accounting import view
from scp.model import Dataset
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_carrier_account_reconciliation import fixture, send
from .test_carrier_bank_reversal import import_statement, reverse, statement
from .test_commercial_integrity import save
from .test_companies import h
from .test_enterprise_integrity import client, team
from .test_grouped_carrier_bank import D0, P1, P2, bank, cash_keys, saved

NAMES = {"BANK-A": "Primary & Co", "BANK-B": "Reserve Bank", "BANK-C": "Primary & Co"}


def bank_fixture():
    start, _ = transport.pay_bill(fixture(), "FO-2", "FO-2", 9.75, "LEGACY", D0)
    owner, treasury, cid = team(start)
    for revision, (identifier, entity, opening) in enumerate([
        ("BANK-A", "E1", 20_000), ("BANK-B", "E1", 30_000), ("BANK-C", "E2", 20_000),
    ], 1):
        saved(bank(owner, cid, f"register-{identifier}", revision, "register_account",
                   id=identifier, company=entity, starts_on=str(P1), opening_minor=opening))
    xml = statement(P1, 20_000, -4025, "WIRE-A")
    saved(bank(owner, cid, "link-a", 4, "link_camt_source", account="BANK-A", xml=xml))
    for revision, (order, account, amount, ref) in enumerate([
        ("FO-1", "BANK-A", 40.25, "WIRE-A"), ("FO-2", "BANK-B", 50.0, "WIRE-B"), ("FO-3", "BANK-C", 100.0, "WIRE-C"),
    ], 5):
        saved(send(treasury, cid, f"pay-{order}", revision, "pay_bill", P1, order, amount=amount, reference=ref, bank_account=account))
    original = saved(import_statement(treasury, cid, "source-a", 8, P1, xml))
    saved(bank(treasury, cid, "match-a", 9, "match", line=original.carrier_bank_lines[-1].id, version=0, targets=cash_keys("FO-1")))
    returned = saved(import_statement(treasury, cid, "source-return-a", 10, P2, statement(P2, 15975, 4025, "WIRE-A", reversal="true")))
    saved(reverse(treasury, cid, "return-a", 11, P2, returned.carrier_bank_lines[-1].id, "FO-1/P-1"))
    reserve = saved(bank(treasury, cid, "source-b", 12, "import_period", account="BANK-B", number="RESERVE",
                         starts_on=str(P1), ends_on=str(P2), opening_minor=30_000, closing_minor=25_000, line_count=1,
                         csv=f"line,date,reference,amount,currency\nRES-1,{P1},WIRE-B,-50.00,INR\n"))
    complete = saved(bank(treasury, cid, "match-b", 13, "match", line=reserve.carrier_bank_lines[-1].id, version=0,
                          targets=[{"order": "FO-2", "voucher": "FO-2/P-2"}]))
    return owner, treasury, cid, complete


def export(accounting_format, data, *, token=None, cid=None, co="E1", detail=True, start=D0, end=P2):
    format = f"{accounting_format}_bank_detail" if detail else accounting_format
    return client.post("/api/accounting/export", json=data,
                       params={"format": format, "company": co, "period_start": start.isoformat(), "period_end": end.isoformat()},
                       headers={**h(token), "X-Company": cid} if cid else {})


def csv_bank(text, *, entity="E1"):
    return {row["voucher"]: (row["bank_account"], int(100 * (Decimal(row["debit"]) - Decimal(row["credit"]))))
            for row in DictReader(StringIO(text)) if row["account"] == "BANK" and row["company_id"] == entity}


def tally_vouchers(text):
    root = XML.fromstring(text)
    masters = {row.get("NAME"): row.findtext("PARENT") for row in root.iter("LEDGER")}
    vouchers = {}
    for voucher in root.iter("VOUCHER"):
        lines = {}
        for leg in voucher.findall("ALLLEDGERENTRIES.LIST"):
            value = Decimal(leg.findtext("AMOUNT"))
            assert (leg.findtext("ISDEEMEDPOSITIVE") == "Yes") is (value < 0)
            lines[leg.findtext("LEDGERNAME")] = int(-100 * value)
        assert sum(lines.values()) == 0
        vouchers[voucher.findtext("VOUCHERNUMBER")] = lines
    return masters, vouchers


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_bank_detail_exports_registered_movements_from_confirmed_company_revision(backend, request):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    owner, treasury, cid, ds = bank_fixture()
    expected = {"FO-1/P-1": ("BANK-A", -4025), "FO-1/V-1": ("BANK-A", 4025),
                "FO-2/P-1": ("", -975), "FO-2/P-2": ("BANK-B", -5000)}
    for period in payables_view(ds).carrier_bank.periods:
        assert period.reconciled
    context = {"cid": cid, "token": treasury}
    before = {"$ref": {"revision": 14}}
    legacy_csv = export("csv", before, detail=False, **context)
    legacy_xml = export("tally", before, detail=False, **context)
    assert legacy_csv.status_code == legacy_xml.status_code == 200
    assert DictReader(StringIO(legacy_csv.json()["text"])).fieldnames[-2:] == ["debit", "credit"]
    assert all(lines.get("Bank") == expected[voucher][1] for voucher, lines in tally_vouchers(legacy_xml.json()["text"])[1].items()
               if voucher in expected)
    unmapped = export("tally", before, **context)
    assert unmapped.status_code == 409 and "BANK-A, BANK-B" in unmapped.text
    detail_csv = export("csv", before, **context)
    assert detail_csv.status_code == 200 and detail_csv.json()["name"].endswith("-bank-detail.csv")
    assert csv_bank(detail_csv.json()["text"]) == expected
    assert csv_bank(detail_csv.json()["text"], entity="E2") == {"FO-3/P-1": ("BANK-C", -10000)}

    raw = ds.model_dump(mode="json")
    for mapping in ({"UNKNOWN": "Unregistered"}, {"BANK-A": 5}, {"BANK-A": "Bad\x01Ledger"}):
        invalid = {**raw, "finance": {**raw["finance"], "tally_bank_ledgers": mapping}}
        assert save(owner, cid, invalid, 14).status_code == 403
        assert client.post("/api/companies", headers=h(owner), json={"dataset": invalid}).status_code == 422
    configured = {**raw, "finance": {**raw["finance"], "tally_bank_ledgers": NAMES}}
    assert save(treasury, cid, configured, 14).status_code == 403
    applied = save(owner, cid, configured, 14)
    assert applied.status_code == 200, applied.text
    actual = Dataset.model_validate(client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"])
    assert actual.finance.tally_bank_ledgers == NAMES
    assert view(actual, D0, P2) == view(ds, D0, P2)
    ready = {"$ref": {"revision": 15}}
    assert export("csv", ready, detail=False, **context).json() == legacy_csv.json()
    assert export("tally", ready, detail=False, **context).json() == legacy_xml.json()
    result = export("tally", ready, **context)
    assert result.status_code == 200 and result.json()["name"].endswith("-bank-detail.xml")
    masters, vouchers = tally_vouchers(result.json()["text"])
    assert set(NAMES.values()).isdisjoint(masters)
    assert masters["Bank"] == "Bank Accounts"
    assert {number: vouchers[number] for number in expected} == {
        "FO-1/P-1": {"Primary & Co": -4025, "Flat": 4025}, "FO-1/V-1": {"Primary & Co": 4025, "Flat": -4025},
        "FO-2/P-1": {"Bank": -975, "Flat": 975}, "FO-2/P-2": {"Reserve Bank": -5000, "Flat": 5000},
    }
    assert "FO-3/P-1" not in vouchers
    other = export("tally", ready, co="E2", **context)
    assert other.status_code == 200
    assert tally_vouchers(other.json()["text"])[1]["FO-3/P-1"].get("Primary & Co") == -10000

    change = {**configured, "finance": {**configured["finance"], "tally_bank_ledgers": {**NAMES, "BANK-A": "Primary New"}}}
    assert save(owner, cid, change, 15).status_code == 200
    assert export("tally", ready, **context).json() == result.json()
    after = export("tally", {"$ref": {"revision": 16}}, **context)
    assert after.status_code == 200
    assert tally_vouchers(after.json()["text"])[1]["FO-1/V-1"].get("Primary New") == 4025


@pytest.mark.parametrize("conflict", [" bank ", "fLaT", "Ｒｅｓｅｒｖｅ Bank"])
def test_tally_detail_refuses_bank_destinations_that_would_merge_ledger_identities(conflict):
    _, _, _, ds = bank_fixture()
    raw = ds.model_dump(mode="json")
    raw["finance"]["tally_bank_ledgers"] = {**NAMES, "BANK-A": conflict}
    response = export("tally", raw)
    assert response.status_code == 409 and "distinct Tally bank ledger" in response.text
