"""A CGI page set becomes one authoritative bank statement or no statement."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as XML

import pytest

from scp.accounting import view
from scp.camt_statements import XML_NS, read_statement, read_statement_files
from scp.companies import commands
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_carrier_account_reconciliation import fixture, send
from .test_commercial_integrity import save
from .test_companies import h
from .test_enterprise_integrity import client, team
from .test_grouped_carrier_bank import P1, P2, bank, cash_keys, saved


def page_files() -> list[str]:
    path = Path(__file__).with_name("fixtures")
    return [(path / f"camt053-page-{page}.xml").read_text(encoding="utf-8") for page in (1, 2)]


def combined(files: list[str]) -> str:
    root = XML.fromstring(files[0])
    message = root.find("BkToCstmrStmt", XML_NS)
    for file in files[1:]:
        message.append(XML.fromstring(file).find("BkToCstmrStmt/Stmt", XML_NS))
    return XML.tostring(root, encoding="unicode")


def test_original_delivery_forms_have_the_same_booked_facts_and_distinct_file_provenance():
    pages = page_files()
    originals = read_statement_files(pages[::-1], "BANK-A", "INR")
    single_xml = combined(pages)
    single = read_statement(single_xml, "BANK-A", "INR")
    assert originals.entries == single.entries
    assert originals.header == single.header
    assert [e.amount_minor for e in originals.entries] == [-4025, -5975]
    assert (originals.header.opening_minor, originals.header.closing_minor, originals.header.line_count) == (20000, 10000, 2)
    assert [f.pages for f in originals.source.originals] == [[1], [2]]
    assert [f.pages for f in single.source.originals] == [[1, 2]]
    assert single.file_sha256 == sha256(single_xml.encode()).hexdigest()
    expected = sha256(b"scp/camt.053/page-set/v1\0" + b"".join(sha256(page.encode()).digest() for page in pages)).hexdigest()
    assert originals.file_sha256 == expected


def test_incomplete_or_incompatible_pages_are_refused():
    first, second = page_files()
    summary = first[first.index("<TxsSummry>"):first.index("</TxsSummry>") + len("</TxsSummry>")]
    conflicting = second.replace("159.75", "160.75").replace('Ccy="INR">100.00', 'Ccy="INR">101.00')
    cases = [
        ([first], "every|single-page"),
        ([second], "every|single-page"),
        ([first, first], "consecutive page"),
        ([first, second.replace("<PgNb>2", "<PgNb>3")], "consecutive page"),
        ([first.replace("LastPgInd>false", "LastPgInd>true"), second], "one final-page"),
        ([first, second.replace("LastPgInd>true", "LastPgInd>false")], "one final-page"),
        ([first, second.replace("2026030301", "2026030302")], "electronic sequence"),
        ([first, second.replace("SPLIT-STMT", "OTHER-STMT")], "statement ID"),
        ([first, second.replace("DE89370400440532013000", "GB29NWBK60161331926819")], "bank account"),
        ([first, second.replace("23:59:59+05:30", "23:59:58+05:30")], "statement window"),
        ([first, second.replace("<Ntry>", summary + "<Ntry>", 1)], "first page"),
        ([first.replace("<NbOfNtries>2", "<NbOfNtries>1", 1), second], "reported entry count"),
        ([first, second.replace("PAGE-SVCR-2", "page-svcr-1")], "repeats a bank entry"),
        ([first, conflicting], "carry forward"),
        ([first.replace("159.75", "159.76"), second], "signed activity"),
        ([first, second.replace("<SubTp><Cd>INTM</Cd></SubTp>", "")], "OPBD-INTM"),
        ([first + " " * 130_000, second + " " * 130_000], "256000 bytes"),
    ]
    for files, diagnostic in cases:
        with pytest.raises(ValueError, match=diagnostic):
            read_statement_files(files, "BANK-A", "INR")


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_complete_pages_are_atomic_and_retriable_in_any_attachment_order(backend, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    first, second = page_files()
    owner, treasury, cid = team(fixture())
    saved(bank(owner, cid, "register", 1, "register_account", id="BANK-A", company="E1",
               starts_on=P1.isoformat(), opening_minor=20000))
    saved(bank(owner, cid, "link", 2, "link_camt_pages", account="BANK-A", files=[second, first]))
    saved(send(treasury, cid, "pay-1", 3, "pay_bill", P1, "FO-1", amount=40.25, reference="WIRE-COMB", bank_account="BANK-A"))
    paid = saved(send(treasury, cid, "pay-2", 4, "pay_bill", P1, "FO-2", amount=59.75, reference="WIRE-COMB", bank_account="BANK-A"))
    endpoint = f"/api/companies/{cid}"
    before = client.get(endpoint, headers=h(treasury)).json()
    assert bank(treasury, cid, "partial", 5, "import_camt", account="BANK-A", xml=first).status_code == 409
    assert bank(owner, cid, "wrong-role", 5, "import_camt_pages", account="BANK-A", files=[first, second]).status_code == 403
    with monkeypatch.context() as change:
        def fail_receipt(*args, **kwargs):
            raise OSError("forced multipart receipt failure")

        change.setattr(commands, "_record", fail_receipt)
        with pytest.raises(OSError, match="forced multipart receipt"):
            bank(treasury, cid, "import", 5, "import_camt_pages", account="BANK-A", files=[first, second])
    assert client.get(endpoint, headers=h(treasury)).json() == before
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda files: bank(treasury, cid, "import", 5, "import_camt_pages", account="BANK-A", files=files),
                                ([second, first], [first, second])))
    imported = saved(replies[0])
    assert sorted(reply.json()["duplicate"] for reply in replies) == [False, True]
    assert all(reply.json()["revision"] == 6 for reply in replies)
    period, = imported.carrier_bank_periods
    report, = payables_view(imported).carrier_bank.periods
    assert report.unmatched_lines == ["PAGE-SVCR-1", "PAGE-SVCR-2"]
    assert report.unmatched_vouchers == ["FO-1/P-1", "FO-2/P-1"] and not report.reconciled
    for key in ("link", "import"):
        receipt = client.get(endpoint + "/commands", headers=h(treasury), params={"id": key}).json()["parameters"]["event"]
        expected = sorted((sha256(page.encode()).hexdigest(), len(page.encode())) for page in [first, second])
        assert [(f["file_sha256"], f["byte_count"]) for f in receipt["files"]] == expected
        assert all(set(f) == {"file_sha256", "byte_count"} for f in receipt["files"])
    assert bank(treasury, cid, "import", 6, "import_camt_pages", account="BANK-A", files=[second + "\n", first]).status_code == 409
    assert bank(treasury, cid, "exact-reoffer", 6, "import_camt_pages", account="BANK-A", files=[first, second]).json()["revision"] == 6
    source = period.camt_source.model_copy(update={"originals": list(reversed(period.camt_source.originals))})
    forged = imported.model_copy(update={"carrier_bank_periods": [period.model_copy(update={"camt_source": source})]})
    assert save(treasury, cid, forged, 6).status_code == 422
    first_original, second_original = period.camt_source.originals
    source = period.camt_source.model_copy(update={"originals": [first_original, second_original.model_copy(
        update={"message_id": "REPLACED-SOURCE"})]})
    forged = imported.model_copy(update={"carrier_bank_periods": [period.model_copy(update={"camt_source": source})]})
    assert save(treasury, cid, forged, 6).status_code == 403
    one, two = period.line_ids
    saved(bank(treasury, cid, "match-1", 6, "match", line=one, version=0, targets=cash_keys("FO-1")))
    tied = saved(bank(treasury, cid, "match-2", 7, "match", line=two, version=0, targets=cash_keys("FO-2")))
    assert payables_view(tied).carrier_bank.periods[0].reconciled
    assert view(tied, period_end=P2) == view(paid, period_end=P2)
