"""Native bank evidence is validated, account-bound, and replayable without storing the XML."""
from hashlib import sha256
from pathlib import Path

import pytest

from scp.accounting import view
from scp.camt_statements import read_statement
from scp.companies import commands
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_carrier_account_reconciliation import fixture, send
from .test_commercial_integrity import save
from .test_companies import h
from .test_enterprise_integrity import client, team
from .test_grouped_carrier_bank import D0, P1, P2, bank, cash_keys, saved

IBAN = "DE89370400440532013000"
OTHER_IBAN = "GB29NWBK60161331926819"
MARKER = "PRIVATE-FIXTURE-XML-MARKER"


def native_file():
    sample = Path(__file__).with_name("fixtures") / "camt053-booked.xml"
    return "\ufeff" + sample.read_text(encoding="utf-8").replace("\n", "\r\n")


@pytest.mark.parametrize(("old", "new", "error"), [
    ("camt.053.001.08", "camt.053.001.02", "format"),
    ("<LastPgInd>true</LastPgInd>", "<LastPgInd>false</LastPgInd>", "complete single-page"),
    ("<PgNb>1</PgNb>", "<PgNb>2</PgNb>", "complete single-page"),
    ("<NbOfNtries>1</NbOfNtries>", "<NbOfNtries>2</NbOfNtries>", "reported entry count"),
    ("<Sum>100.00</Sum>", "<Sum>99.99</Sum>", "reported gross"),
    ("<TtlNetNtry><Amt>100.00</Amt>", "<TtlNetNtry><Amt>99.99</Amt>", "reported net"),
    ("<Cd>OPBD</Cd>", "<Cd>ITBD</Cd>", "opening"),
    ("<Amt Ccy=\"INR\">200.00</Amt>", "<Amt Ccy=\"INR\">200.01</Amt>", "signed activity"),
    ("<Amt Ccy=\"INR\">100.00</Amt>", "<Amt Ccy=\"USD\">100.00</Amt>", "currency"),
    ("<CdtDbtInd>DBIT</CdtDbtInd>", "<CdtDbtInd>HINT</CdtDbtInd>", "credit or debit"),
    ("<Cd>BOOK</Cd>", "<Cd>PDNG</Cd>", "booked entries"),
    ("<Sts><Cd>BOOK", "<RvslInd>true</RvslInd><Sts><Cd>BOOK", "reversal"),
    ("<BookgDt><Dt>2026-03-03", "<BookgDt><Dt>2026-03-04", "within the statement dates"),
    ("<Amt Ccy=\"INR\">200.00</Amt>", "<Amt Ccy=\"INR\">200.001</Amt>", "two decimals"),
    ("encoding=\"UTF-8\"", "encoding=\"UTF-16\"", "declare UTF-8"),
    (IBAN, "DE88370400440532013000", "IBAN checksum"),
])
def test_camt_controls_refuse_invalid_files(old, new, error):
    with pytest.raises(ValueError, match=error):
        read_statement(native_file().replace(old, new, 1), "BANK-A", "INR")


def test_camt_refuses_dtd_multiple_statements_duplicates_and_excess_bytes():
    xml = native_file()
    start = xml.index("    <Stmt>")
    end = xml.index("    </Stmt>") + len("    </Stmt>")
    entry = xml[xml.index("      <Ntry>"):xml.index("      </Ntry>") + len("      </Ntry>")]
    cases = [
        (xml.replace("<Document", "<!DOCTYPE Document []><Document", 1), "entity declaration"),
        (xml[:end] + xml[start:end] + xml[end:], "requires one Stmt"),
        (xml.replace("</Ntry>", "</Ntry>" + entry, 1), "repeats a bank entry"),
        (xml + "ö" * 130_000, "256000 bytes"),
    ]
    for raw, reason in cases:
        with pytest.raises(ValueError, match=reason):
            read_statement(raw, "BANK-A", "INR")


def test_camt_preserves_local_account_identity_and_signed_quiet_overdraft():
    xml = native_file().replace(f"<IBAN>{IBAN}</IBAN>", "<Othr><Id>Bank-Local-01</Id></Othr>")
    xml = xml.replace("</Acct>", "<Svcr><FinInstnId><BICFI>TESTDEFF</BICFI></FinInstnId></Svcr></Acct>")
    assert read_statement(xml, "BANK-A", "INR").account_hash == sha256(b"iso20022:other:TESTDEFF:Bank-Local-01").hexdigest()
    with pytest.raises(ValueError, match="BICFI"):
        read_statement(xml.replace("<BICFI>TESTDEFF</BICFI>", ""), "BANK-A", "INR")
    start, end = xml.index("      <Ntry>"), xml.index("      </Ntry>") + len("      </Ntry>")
    xml = (xml[:start] + xml[end:]).replace("<NbOfNtries>1", "<NbOfNtries>0")
    xml = xml.replace("<Sum>100.00", "<Sum>0").replace("<TtlNetNtry><Amt>100.00", "<TtlNetNtry><Amt>0")
    xml = xml.replace('Ccy="INR">100.00', 'Ccy="INR">200.00').replace("<CdtDbtInd>CRDT", "<CdtDbtInd>DBIT")
    statement = read_statement(xml, "BANK-A", "INR")
    assert statement.header.opening_minor == statement.header.closing_minor == -20_000
    assert not statement.entries


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_original_file_is_linked_reconciled_and_receipted_atomically(backend, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    owner, treasury, cid = team(fixture())
    account = dict(id="BANK-A", company="E1", starts_on=D0.isoformat(), opening_minor=20_000)
    saved(bank(owner, cid, "register-a", 1, "register_account", **account))
    saved(bank(owner, cid, "register-b", 2, "register_account", **{**account, "id": "BANK-B", "company": "E2"}))
    old = dict(account="BANK-A", number="PREVIOUS", starts_on=D0.isoformat(), ends_on=D0.isoformat(), opening_minor=20000,
               closing_minor=20000, line_count=0, csv="line,date,reference,amount,currency\n")
    saved(bank(treasury, cid, "historic-csv", 3, "import_period", **old))
    xml = native_file()
    assert bank(treasury, cid, "wrong-grant-link", 4, "link_camt_source", account="BANK-A", xml=xml).status_code == 403
    assert bank(treasury, cid, "not-linked", 4, "import_camt", account="BANK-A", xml=xml).status_code == 409
    linked = saved(bank(owner, cid, "link", 4, "link_camt_source", account="BANK-A", xml=xml))
    source = linked.carrier_bank_accounts[0].camt_source
    assert source is not None and source.starts_on == P1
    assert source.account_sha256 == sha256(f"iso20022:iban:{IBAN}".encode()).hexdigest()
    assert bank(owner, cid, "second-bank", 5, "link_camt_source", account="BANK-B", xml=xml).status_code == 403
    new_file = xml.replace(IBAN, OTHER_IBAN)
    assert bank(owner, cid, "rebind", 5, "link_camt_source", account="BANK-A", xml=new_file).status_code == 409
    forged = linked.model_copy(update={"carrier_bank_accounts": [a.model_copy(update={"camt_source": None})
                                                                 for a in linked.carrier_bank_accounts]})
    assert save(owner, cid, forged, 5).status_code == 403
    assert bank(treasury, cid, "historic-reoffer", 5, "import_period", **old).json()["revision"] == 5
    managed = {**old, "number": "BAD-CSV", "starts_on": P1.isoformat(), "ends_on": P1.isoformat()}
    assert bank(treasury, cid, "downgrade", 5, "import_period", **managed).status_code == 409
    saved(send(treasury, cid, "pay-1", 5, "pay_bill", P1, "FO-1", amount=40.25, reference="WIRE-COMB", bank_account="BANK-A"))
    paid = saved(send(treasury, cid, "pay-2", 6, "pay_bill", P1, "FO-2", amount=59.75, reference="WIRE-COMB", bank_account="BANK-A"))
    assert bank(owner, cid, "wrong-grant-import", 7, "import_camt", account="BANK-A", xml=xml).status_code == 403
    assert bank(treasury, cid, "wrong-account", 7, "import_camt", account="BANK-A", xml=new_file).status_code == 409
    endpoint = f"/api/companies/{cid}"
    before = client.get(endpoint, headers=h(treasury)).json()
    with monkeypatch.context() as change:
        def fail_receipt(*args, **kwargs):
            raise OSError("forced source receipt failure")

        change.setattr(commands, "_record", fail_receipt)
        with pytest.raises(OSError, match="forced source receipt"):
            bank(treasury, cid, "upload", 7, "import_camt", account="BANK-A", xml=xml)
    assert client.get(endpoint, headers=h(treasury)).json() == before
    imported = saved(bank(treasury, cid, "upload", 7, "import_camt", account="BANK-A", xml=xml))
    period = imported.carrier_bank_periods[-1]
    assert (period.number, period.opening_minor, period.closing_minor, period.line_count) == ("FIXTURE-STMT-001", 20000, 10000, 1)
    assert period.camt_source and period.camt_source.message_id == "FIXTURE-MSG-001"
    digest = sha256(xml.encode()).hexdigest()
    assert period.file_sha256 == digest
    for identifier, mode in (("link", "link_camt_source"), ("upload", "import_camt")):
        receipt = client.get(endpoint + "/commands", headers=h(treasury), params={"id": identifier})
        assert receipt.json()["parameters"] == {"event": {
            "kind": mode, "account": "BANK-A", "file_sha256": digest, "byte_count": len(xml.encode()),
        }}
        assert MARKER not in receipt.text and IBAN not in receipt.text
    assert MARKER not in imported.model_dump_json() and IBAN not in imported.model_dump_json()
    assert bank(treasury, cid, "upload", 7, "import_camt", account="BANK-A", xml=xml).json()["duplicate"]
    assert bank(treasury, cid, "reoffer", 8, "import_camt", account="BANK-A", xml=xml).json()["revision"] == 8
    for identifier in ("upload", "new-id"):
        changed = bank(treasury, cid, identifier, 8, "import_camt", account="BANK-A", xml=xml + "\n")
        assert changed.status_code == 409
    row, = imported.carrier_bank_lines
    assert (row.statement_line, row.reference, row.amount_minor) == ("SVCR-00001", "WIRE-COMB", -10000)
    matched = saved(bank(treasury, cid, "group", 8, "match", line=row.id, version=0, targets=cash_keys("FO-1", "FO-2")))
    assert payables_view(matched).carrier_bank.periods[0].reconciled
    assert view(paid, period_end=P2) == view(matched, period_end=P2)
