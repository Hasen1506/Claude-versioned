"""Real company command tests for bank-driven payable and cash postings."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as XML

import pytest

from scp.accounting import view
from scp.companies import commands
from scp.purchasing.payables import payables_view
from scp.versions import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import h, join, signup
from .test_company_commands import command
from .test_domestic_invoice_currency import balances, business, current, invoice, receive
from .factory import base
from .test_enterprise_integrity import client, team
from .test_supplier_bank_reconciliation import ACCOUNT, INV, bank, native_fixture, pay, register


def financial(owner, cid, revision, kind, **data):
    return command(owner, cid, data.pop("identifier", f"{kind}-{revision}"), "carrier_bank", kind, revision,
                   date=data.pop("day", "2026-01-08"), event={"kind": kind, **data})


def attach(owner, cid, revision, xml):
    current(bank(owner, cid, revision, "2026-01-08", "link_camt_source", account=ACCOUNT, xml=xml))
    return current(bank(owner, cid, revision + 1, "2026-01-08", "import_camt", account=ACCOUNT, xml=xml))


def allocations(*amounts):
    return [{"invoice": f"SI-{index:05d}", "invoice_minor": inv, "bank_minor": bank_amount}
            for index, (inv, bank_amount) in enumerate(amounts, 1)]


OWNER_GRANTS = {"control_roles": {grant: ["owner@integrity.example"]
                                for grant in ("master_data", "purchasing", "payments", "billing", "warehouse", "invoice_release")}}


@pytest.mark.parametrize(("backend", "currency", "price", "booked", "closing", "fee"), [
    ("sqlite", "JPY", 1, "3", "997", "1"),
    ("sqlite", "KWD", 0.001, "0.003", "0.997", "0.001"),
    ("postgresql", "KWD", 0.001, "0.003", "0.997", "0.001"),
])
def test_grouped_clearing_and_explicit_fee_are_one_recoverable_posting(backend, currency, price, booked, closing, fee,
                                                              request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)
        request.addfinalizer(store.db.close)
    owner, buyer, cid = business(currency, price, finance=OWNER_GRANTS)
    current(receive(owner, cid, 1, "2026-01-06", 2))
    current(invoice(owner, cid, 2, "2026-01-07"))
    current(invoice(owner, cid, 3, "2026-01-07"))
    current(register(owner, cid, 4))
    xml = native_fixture(currency)
    old_cash, old_closing = ("1.00", "999.00") if currency == "JPY" else ("0.001", "0.999")
    charges = (f'<Chrgs><TtlChrgsAndTaxAmt Ccy="{currency}">{fee}</TtlChrgsAndTaxAmt>'
               f'<Rcrd><Amt Ccy="{currency}">{fee}</Amt><CdtDbtInd>DBIT</CdtDbtInd><ChrgInclInd>true</ChrgInclInd></Rcrd></Chrgs>')
    xml = xml.replace(f">{old_cash}<", f">{booked}<").replace(f">{old_closing}<", f">{closing}<")
    xml = xml.replace("<NbOfTxs>1</NbOfTxs>", "<NbOfTxs>2</NbOfTxs>").replace("<NtryDtls>", f"{charges}<NtryDtls>")
    source = attach(owner, cid, 5, xml)
    line = source.carrier_bank_lines[0]
    assert line.requires_allocation and line.supplier_debit.included_fee_minor == 1
    assert financial(buyer, cid, 7, "clear_supplier_statement", line=line.id, reason="Bank advice",
                     allocations=allocations((1, 1), (1, 1))).status_code == 403
    assert financial(owner, cid, 7, "clear_supplier_statement", line=line.id, reason="Bank advice",
                     allocations=allocations((1, 1), (1, 2))).status_code == 409
    assert financial(owner, cid, 7, "clear_supplier_statement", line=line.id, reason="Bank advice",
                     allocations=allocations((1, 1), (2, 1))).status_code == 409

    def post():
        return financial(owner, cid, 7, "clear_supplier_statement", line=line.id, reason="Verified allocation",
                         allocations=allocations((1, 1), (1, 1)), identifier="CLEAR-ONCE")

    def fail(*args):
        raise OSError("receipt unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail)
        with pytest.raises(OSError, match="receipt unavailable"):
            post()
    clean = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    assert clean["meta"]["revision"] == 7
    assert all(not record["payments"] for record in clean["dataset"]["supplier_invoices"])
    assert not clean["dataset"]["carrier_bank_lines"][0]["history"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: post(), range(2)))
    assert {response.json()["duplicate"] for response in outcomes} == {False, True}
    posted = current(outcomes[0])
    assert all(record.open == 0 for record in posted.supplier_invoices)
    ledger = balances(posted, "2026-01-08")
    assert float(ledger["BANK"]) == -3 * price
    assert float(ledger["BANK_FEES"]) == price
    assert ledger["PAYABLES"] == 0
    result = payables_view(posted).carrier_bank.periods[0]
    assert result.reconciled and result.ledger_closing_minor == 997
    assert set(posted.carrier_bank_lines[0].matched_vouchers()) == {f"{INV}/1", "SI-00002/1", f"{line.id}/FEE"}
    assert bank(owner, cid, 8, "2026-01-09", "release", line=line.id, version=1).status_code == 409


def test_statement_cash_sets_the_observed_fx_and_clears_the_original_liability():
    raw = base()
    raw["finance"] = OWNER_GRANTS
    raw["settings"].update(currency="INR", fx_rates={"USD": 80})
    raw["purchase_orders"] = [{"id": "PO-1", "supplier": "S", "location": "P", "order_date": "2026-01-05", "currency": "USD"}]
    raw["receipts"] = [{"id": "PR-B", "po": "PO-1", "kind": "purchase", "product": "B", "location": "P",
                        "qty": 1, "price": 1, "due_date": "2026-01-06"}]
    from scp.model import Dataset
    owner, _, cid = team(Dataset.model_validate(raw))
    current(command(owner, cid, "receive-usd", "purchasing", "receive", 1, date="2026-01-06", po="PO-1",
                    lines=[{"id": "PR-B", "qty": 1}]))
    current(command(owner, cid, "invoice-usd", "purchasing", "enter_invoice", 2, date="2026-01-07", po="PO-1",
                    reference="USD-1", lines=[{"order": "PR-B", "qty": 1}]))
    current(register(owner, cid, 3, opening=20000))
    xml = (Path(__file__).with_name("fixtures") / "camt053-booked.xml").read_text()
    xml = xml.replace("2026-03-03", "2026-01-08").replace("2026-03-02", "2026-01-07")
    sourced = attach(owner, cid, 4, xml)
    line = sourced.carrier_bank_lines[0]
    settled = current(financial(owner, cid, 6, "clear_supplier_statement", line=line.id,
                                reason="USD principal from settlement advice", allocations=allocations((100, 10000))))
    assert settled.supplier_invoices[0].fx_rate == 80
    assert settled.supplier_invoices[0].payments[0].fx_rate == 100
    assert settled.supplier_invoices[0].open == 0
    assert payables_view(settled).carrier_bank.periods[0].reconciled
    journal = next(voucher for voucher in view(settled, period_end=date(2026, 1, 8)).vouchers if voucher.number == f"{INV}/1")
    assert {row.account: (row.debit, row.credit) for row in journal.lines} == {
        "PAYABLES": (80, 0), "BANK": (0, 100), "FX_LOSS": (20, 0),
    }
    assert next(row for row in journal.lines if row.account == "BANK").bank_account == ACCOUNT
    returned_xml = xml.replace("2026-01-08", "2026-01-09").replace("2026-01-07", "2026-01-08")
    returned_xml = returned_xml.replace("FIXTURE-MSG-001", "RETURN-MSG-001")
    returned_xml = returned_xml.replace("FIXTURE-STMT-001", "RETURN-STMT-001").replace("SVCR-00001", "SVCR-RETURN")
    returned_xml = returned_xml.replace("200.00</Amt>", "PREVIOUS</Amt>", 1).replace("100.00</Amt>", "200.00</Amt>", 1)
    returned_xml = returned_xml.replace("PREVIOUS</Amt>", "100.00</Amt>").replace("DBIT", "CRDT")
    returned_xml = returned_xml.replace("TtlCdtNtries", "PENDING").replace("TtlDbtNtries", "TtlCdtNtries").replace("PENDING", "TtlDbtNtries")
    returned_xml = returned_xml.replace("<Sts><Cd>BOOK</Cd></Sts>", "<RvslInd>true</RvslInd><Sts><Cd>BOOK</Cd></Sts>")
    source = current(bank(owner, cid, 7, "2026-01-09", "import_camt", account=ACCOUNT, xml=returned_xml))
    credit = source.carrier_bank_lines[-1]
    result = current(financial(owner, cid, 8, "return_supplier_statement", day="2026-01-09", line=credit.id,
                               original=line.id, payments=[{"invoice": INV, "payment_number": 1}], reason="Bank returned transfer"))
    assert result.supplier_invoices[0].open == 1
    assert all(period.reconciled for period in payables_view(result).carrier_bank.periods)
    assert balances(result, "2026-01-09")["PAYABLES"] == -80
    returned = next(voucher for voucher in view(result, period_end=date(2026, 1, 9)).vouchers if voucher.number == f"{INV}/2")
    assert {row.account: (row.debit, row.credit) for row in returned.lines} == {
        "PAYABLES": (0, 80), "BANK": (100, 0), "FX_LOSS": (0, 20),
    }


def test_later_receipt_and_review_do_not_authorize_a_backdated_bank_posting():
    owner, _, cid = business("INR", 100, finance=OWNER_GRANTS)
    billed = current(invoice(owner, cid, 1, "2026-01-07"))
    assert billed.supplier_invoices[0].blocks
    current(receive(owner, cid, 2, "2026-01-09", 1))
    current(command(owner, cid, "late-release", "purchasing", "release_invoice", 3, date="2026-01-09", po=INV))
    current(register(owner, cid, 4, opening=20000))
    xml = (Path(__file__).with_name("fixtures") / "camt053-booked.xml").read_text()
    xml = xml.replace("2026-03-03", "2026-01-08").replace("2026-03-02", "2026-01-07")
    statement = attach(owner, cid, 5, xml)
    denied = financial(owner, cid, 7, "clear_supplier_statement", day="2026-01-09", line=statement.carrier_bank_lines[0].id,
                       reason="Reviewed later", allocations=allocations((10000, 10000)))
    assert denied.status_code == 409 and "blocked for payment" in denied.text


@pytest.mark.parametrize("outcome", ["booked", "rejected"])
def test_approved_payment_file_is_stable_private_and_clears_only_when_booked(outcome):
    owner, _, cid = business("KWD", 0.001)
    checker_email = "treasury-review@supplier-disbursement.example"
    checker = signup(checker_email)
    join(owner, cid, checker_email, "planner")
    original = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    original["finance"] = {"separate_payments": True, "control_roles": {
        "master_data": ["owner@integrity.example"], "billing": ["owner@integrity.example"],
        "warehouse": ["owner@integrity.example"], "purchasing": ["owner@integrity.example"],
        "payments": ["owner@integrity.example", checker_email],
    }}
    assert save(owner, cid, original, 1).status_code == 200
    current(receive(owner, cid, 2, "2026-01-06", 1))
    current(invoice(owner, cid, 3, "2026-01-07"))
    current(register(owner, cid, 4))
    xml = native_fixture("KWD")
    current(bank(owner, cid, 5, "2026-01-08", "link_camt_source", account=ACCOUNT, xml=xml))
    routing = {
        "debtor": {"name": "Test & Treasury", "bic": "COBADEFFXXX", "iban": "DE89370400440532013000"},
        "creditor": {"name": "Fixture Supplier", "bic": "NWBKGB2L", "iban": "GB29NWBK60161331926819"},
    }
    proposed = current(financial(owner, cid, 6, "propose_supplier_payment", account=ACCOUNT, execute_on="2026-01-08",
                                 legs=[{"invoice": INV, "amount_minor": 1}], routing=routing))
    instruction = proposed.supplier_payment_instructions[0]
    identifier = instruction.id
    assert proposed.supplier_invoices[0].open == 0.001 and not proposed.supplier_invoices[0].payments
    receipt = client.get(f"/api/companies/{cid}/commands", params={"id": "propose_supplier_payment-6"}, headers=h(owner))
    assert receipt.status_code == 200 and "routing_sha256" in receipt.text and "DE893" not in receipt.text
    assert pay(checker, cid, 7).status_code == 409
    assert financial(owner, cid, 7, "approve_supplier_payment", instruction=identifier, routing=routing).status_code == 403
    exporter = f"/api/companies/{cid}/supplier-payment-instructions/{identifier}/export"
    assert client.post(exporter, headers=h(checker), json=routing).status_code == 409
    altered = {**routing, "creditor": {**routing["creditor"], "name": "Different beneficiary"}}
    assert financial(checker, cid, 7, "approve_supplier_payment", instruction=identifier, routing=altered).status_code == 409
    current(financial(checker, cid, 7, "approve_supplier_payment", instruction=identifier, routing=routing))
    assert client.post(exporter, headers=h(owner), json=routing).status_code == 403
    first = client.post(exporter, headers=h(checker), json=routing)
    assert first.status_code == 200 and first.headers["Cache-Control"] == "no-store"
    assert client.post(exporter, headers=h(checker), json=routing).json() == first.json()
    artifact = first.json()
    assert sha256(artifact["xml"].encode()).hexdigest() == artifact["sha256"]
    document = XML.fromstring(artifact["xml"])
    assert document.find(".//{*}EndToEndId").text == identifier
    assert document.find(".//{*}InstdAmt").text == "0.001"
    assert document.find(".//{*}InstdAmt").get("Ccy") == "KWD"
    assert document.find(".//{*}Nm").text == "Test & Treasury"
    from os import environ
    if path := environ.get("SCP_CAPTURE_PAYMENT_XML"):
        Path(path).write_bytes(artifact["xml"].encode())
    if outcome == "rejected":
        xml_status = f'''<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.10">
          <CstmrPmtStsRpt><GrpHdr><MsgId>STATUS-ONE</MsgId></GrpHdr>
          <OrgnlGrpInfAndSts><OrgnlMsgId>{identifier}</OrgnlMsgId>
            <OrgnlMsgNmId>pain.001.001.09</OrgnlMsgNmId><GrpSts>RJCT</GrpSts></OrgnlGrpInfAndSts>
          <OrgnlPmtInfAndSts><OrgnlPmtInfId>{identifier}</OrgnlPmtInfId><PmtInfSts>RJCT</PmtInfSts>
            <TxInfAndSts><OrgnlEndToEndId>{identifier}</OrgnlEndToEndId><TxSts>RJCT</TxSts>
              <StsRsnInf><Rsn><Cd>AC01</Cd></Rsn></StsRsnInf></TxInfAndSts>
          </OrgnlPmtInfAndSts></CstmrPmtStsRpt></Document>'''
        for unconfirmed in (xml_status.replace("<TxSts>RJCT", "<TxSts>ACTC"),
                            xml_status.replace(f"<OrgnlEndToEndId>{identifier}", "<OrgnlEndToEndId>WRONG")):
            assert financial(checker, cid, 8, "reject_supplier_payment", instruction=identifier, xml=unconfirmed).status_code == 409
        assert financial(owner, cid, 8, "reject_supplier_payment", instruction=identifier, xml=xml_status).status_code == 403
        rejected = current(financial(checker, cid, 8, "reject_supplier_payment", instruction=identifier, xml=xml_status))
        assert rejected.supplier_payment_instructions[0].rejection.file_sha256 == sha256(xml_status.encode()).hexdigest()
        assert rejected.supplier_invoices[0].open == 0.001 and not rejected.supplier_invoices[0].payments
        assert client.post(exporter, headers=h(checker), json=routing).status_code == 409
        assert pay(checker, cid, 9).status_code == 200
        return
    source = current(bank(checker, cid, 8, "2026-01-08", "import_camt", account=ACCOUNT,
                          xml=xml.replace("WIRE-A", identifier)))
    line = source.carrier_bank_lines[0]
    assert financial(checker, cid, 9, "clear_supplier_statement", line=line.id, reason="Bank booked transfer",
                     allocations=allocations((1, 1))).status_code == 409
    cleared = current(financial(checker, cid, 9, "clear_supplier_statement", line=line.id, instruction=identifier,
                                reason="Bank booked transfer"))
    assert cleared.supplier_payment_instructions[0].statement_line == line.id
    assert cleared.supplier_invoices[0].payments[0].statement_cash.instruction == identifier
    assert payables_view(cleared).carrier_bank.periods[0].reconciled
    assert client.post(exporter, headers=h(checker), json=routing).status_code == 409
