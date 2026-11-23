"""A bank return reconciles independently computed principal, fee and cash balances."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from xml.etree import ElementTree as XML

import pytest

from scp.accounting import view
from scp.carrier_bank import AllocateBankReturn, CamtFile, protect_bank, record_bank
from scp.companies import commands
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_accounting_bank_export import csv_bank, export, tally_vouchers
from .test_backup_postgres import pg_databases as pg_databases
from .test_carrier_account_reconciliation import fixture, send
from .test_carrier_bank_reversal import NS, P3, import_statement, reverse, statement
from .test_closed_period_carrier_return import REASON, before_return, quiet_statement
from .test_commercial_integrity import save
from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client, team
from .test_grouped_carrier_bank import P1, P2, bank, cash_keys, saved

TRACE = "de92a6f6-163a-4ea0-8af3-99d266219ec8"


def source_file(on, opening, movement, reference, *, returned=False, fee=None, included="true", trace=None):
    root = XML.fromstring(statement(on, opening, movement, reference, reversal="true" if returned else None))
    entry = root.find(".//{*}Ntry")
    details = entry.find("{*}NtryDtls")

    def append(parent, tag, value, **attrs):
        child = XML.SubElement(parent, f"{{{NS}}}{tag}", attrs)
        child.text = value
        return child

    if trace:
        tx = append(details, "TxDtls", None)
        append(append(tx, "Refs", None), "UETR", trace)
    if fee is not None:
        charges = XML.Element(f"{{{NS}}}Chrgs")
        entry.insert(list(entry).index(details), charges)
        append(charges, "TtlChrgsAndTaxAmt", f"{fee / 100:.2f}", Ccy="INR")
        record = append(charges, "Rcrd", None)
        append(record, "Amt", f"{fee / 100:.2f}", Ccy="INR")
        append(record, "CdtDbtInd", "DBIT")
        if included:
            append(record, "ChrgInclInd", included)
    return XML.tostring(root, encoding="unicode")


def allocate(token, cid, identifier, revision, day, line, *legs, advice="", reason=""):
    event = {"kind": "allocate_return", "line": line,
             "legs": [{"original": {"order": order, "voucher": voucher}, "amount_minor": minor}
                      for order, voucher, minor in legs],
             "advice": advice, "late_reason": reason}
    return command(token, cid, identifier, "carrier_bank", "allocate_return", revision, date=str(day), event=event)


def setup_original(*orders, trace=None):
    owner, treasury, cid = team(fixture())
    saved(bank(owner, cid, "register", 1, "register_account", id="BANK-A", company="E1", starts_on=str(P1), opening_minor=20_000))
    amounts = {"FO-1": 4025, "FO-2": 5975}
    paid = sum(amounts[order] for order in orders)
    xml = source_file(P1, 20_000, -paid, "WIRE-ORIGINAL", trace=trace)
    saved(bank(owner, cid, "link", 2, "link_camt_source", account="BANK-A", xml=xml))
    for revision, order in enumerate(orders, 3):
        saved(send(treasury, cid, f"pay-{order}", revision, "pay_bill", P1, order,
                   amount=amounts[order] / 100, reference="WIRE-ORIGINAL", bank_account="BANK-A"))
    revision = 3 + len(orders)
    original = saved(import_statement(treasury, cid, "source-paid", revision, P1, xml)).carrier_bank_lines[-1]
    saved(bank(treasury, cid, "match-paid", revision + 1, "match", line=original.id, version=0, targets=cash_keys(*orders)))
    return owner, treasury, cid, original.id, revision + 2


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_grouped_partial_return_posts_and_recovers_principal_fee_and_advice(backend, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    owner, treasury, cid, original, revision = setup_original("FO-1", "FO-2")
    xml = source_file(P2, 10_000, 4875, "REISSUED-1", returned=True, fee=125)
    data = saved(import_statement(treasury, cid, "return-1-file", revision, P2, xml))
    revision += 1
    line = data.carrier_bank_lines[-1]
    a, b = ("FO-1", "FO-1/P-1", 2000), ("FO-2", "FO-2/P-1", 3000)
    assert line.included_fee_minor == 125
    assert not payables_view(data).carrier_bank.periods[0].reconciled
    assert view(data, period_end=P1).vouchers == view(data, period_end=P2).vouchers
    assert reverse(treasury, cid, "legacy", revision, P2, line.id, "FO-1/P-1").status_code == 409
    assert "reviewed bank advice" in allocate(treasury, cid, "without-advice", revision, P2, line.id, a, b).text
    wrong_net = allocate(treasury, cid, "net", revision, P2, line.id, a, advice="BANK-ADVICE-44")
    assert wrong_net.status_code == 409 and "booked statement amount" in wrong_net.text
    assert "remaining principal" in allocate(treasury, cid, "over", revision, P2, line.id, (a[0], a[1], 4026),
                                             advice="BANK-ADVICE-44").text
    assert "once" in allocate(treasury, cid, "duplicate-leg", revision, P2, line.id, a, a, advice="BANK-ADVICE-44").text
    assert allocate(owner, cid, "no-payment-grant", revision, P2, line.id, a, b, advice="BANK-ADVICE-44").status_code == 403
    assert allocate(treasury, cid, "future-leg", revision, P2, line.id, a, ("FO-3", "FO-3/P-1", 3000),
                    advice="BANK-ADVICE-44").status_code == 409

    def post():
        return allocate(treasury, cid, "post-group", revision, P2, line.id, b, a, advice="BANK-ADVICE-44")

    snapshot = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    with monkeypatch.context() as patch:
        def fail_receipt(*args, **kwargs):
            raise OSError("allocation receipt unavailable")

        patch.setattr(commands, "_record", fail_receipt)
        with pytest.raises(OSError, match="allocation receipt unavailable"):
            post()
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json() == snapshot
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _: post(), range(2)))
    data = saved(replies[0])
    assert sorted(reply.json()["duplicate"] for reply in replies) == [False, True]
    revision += 1
    receipt = client.get(f"/api/companies/{cid}/commands", headers=h(treasury), params={"id": "post-group"}).json()
    assert receipt["parameters"]["event"]["advice"] == "BANK-ADVICE-44"
    assert [target.voucher for target in data.carrier_bank_lines[-1].active] == ["FO-1/V-1", "FO-2/V-1"]
    assert bank(treasury, cid, "release-original", revision, "release", line=original, version=1).status_code == 409
    demand = payables_view(data)
    assert {bill.order: bill.open for bill in demand.carrier_bills} == {"FO-1": 20, "FO-2": 30, "FO-3": 100}
    assert {cash.order: cash.remaining_minor for cash in demand.carrier_bank.reversible_cash} == {"FO-1": 2025, "FO-2": 2975}
    assert all(period.reconciled for period in demand.carrier_bank.periods)
    assert demand.carrier_bank.periods[0].ledger_closing_minor == 14_875

    fee_voucher = f"{line.id}/F"
    journal = view(data, period_end=P2)
    postings = {v.number: {leg.account: round(100 * (leg.debit - leg.credit)) for leg in v.lines}
                for v in journal.vouchers if v.date == P2}
    assert postings == {"FO-1/V-1": {"BANK": 2000, "PAYABLES": -2000}, "FO-2/V-1": {"BANK": 3000, "PAYABLES": -3000},
                        fee_voucher: {"BANK": -125, "BANK_FEES": 125}}
    csv = export("csv", data.model_dump(mode="json"), start=P2, end=P2)
    assert csv.status_code == 200
    assert csv_bank(csv.json()["text"]) == {"FO-1/V-1": ("BANK-A", 2000), "FO-2/V-1": ("BANK-A", 3000), fee_voucher: ("BANK-A", -125)}
    raw = data.model_dump(mode="json")
    raw["finance"]["tally_bank_ledgers"] = {"BANK-A": "Primary Bank"}
    tally = export("tally", raw, start=P2, end=P2)
    assert tally.status_code == 200
    masters, vouchers = tally_vouchers(tally.json()["text"])
    assert masters["Bank Fees"] == "Indirect Expenses"
    assert vouchers[fee_voucher] == {"Bank Fees": 125, "Primary Bank": -125}

    xml = source_file(P3, 14_875, 5000, "WIRE-ORIGINAL", returned=True)
    second = saved(import_statement(treasury, cid, "return-2-file", revision, P3, xml)).carrier_bank_lines[-1]
    revision += 1
    a, b = ("FO-1", "FO-1/P-1", 2025), ("FO-2", "FO-2/P-1", 2975)
    assert "already belongs" in allocate(treasury, cid, "reuse-advice", revision, P3, second.id, a, b, advice="bank-advice-44").text
    assert "remaining principal" in allocate(treasury, cid, "cumulative-cap", revision, P3, second.id, (a[0], a[1], 2026), b).text
    final = saved(allocate(treasury, cid, "post-rest", revision, P3, second.id, a, b))
    demand = payables_view(final)
    assert not demand.carrier_bank.reversible_cash
    assert {bill.order: bill.open for bill in demand.carrier_bills} == {"FO-1": 40.25, "FO-2": 59.75, "FO-3": 100}
    assert demand.carrier_bank.periods[0].ledger_closing_minor == 19_875
    assert all(period.reconciled for period in demand.carrier_bank.periods)


def test_a_shared_uetr_supports_changed_reference_and_ambiguous_charges_stay_pending():
    _, treasury, cid, _, revision = setup_original("FO-1", trace=TRACE)
    changed = source_file(P2, 15_975, 890, "CHANGED", returned=True, trace=TRACE, fee=10, included=None)
    pending = saved(import_statement(treasury, cid, "ambiguous", revision, P2, changed)).carrier_bank_lines[-1]
    assert pending.unresolved_charges and pending.included_fee_minor is None
    leg = ("FO-1", "FO-1/P-1", 900)
    assert "ambiguous bank charge" in allocate(treasury, cid, "guess", revision + 1, P2, pending.id, leg).text
    changed = source_file(P3, 16_865, 890, "CHANGED", returned=True, trace=TRACE, fee=10)
    supported = saved(import_statement(treasury, cid, "supported", revision + 1, P3, changed)).carrier_bank_lines[-1]
    assert supported.trace_ids == [TRACE]
    final = saved(allocate(treasury, cid, "post-trace", revision + 2, P3, supported.id, leg))
    assert final.carrier_bank_lines[-1].history[0].allocation.advice == ""
    assert final.carrier_bank_lines[-2].active == []


def test_partial_refund_return_with_fee_bridges_closed_period_net():
    owner, treasury, cid, data, revision, original, booked, opening, _, reference = before_return(True)
    posting = booked + timedelta(days=1)
    data.finance.closed_through = booked
    data.finance.control_roles["period_close"] = ["owner@integrity.example", "buyer@integrity.example"]
    assert save(owner, cid, data, revision).status_code == 200
    historical = view(data, period_end=booked)
    xml = source_file(booked, opening, -525, reference, returned=True, fee=25)
    line = saved(import_statement(treasury, cid, "refund-return-file", revision + 1, posting, xml)).carrier_bank_lines[-1]
    leg = ("FO-1", original, 500)
    posted = saved(allocate(treasury, cid, "refund-return", revision + 2, posting, line.id, leg, reason=REASON))
    assert view(posted, period_end=booked) == historical
    activity = view(posted, period_start=posting, period_end=posting).vouchers
    assert {v.number: [(r.account, r.debit, r.credit) for r in v.lines] for v in activity} == {
        "FO-1/V-3": [("PAYABLES", 5.0, 0), ("BANK", 0, 5.0)],
        f"{line.id}/F": [("BANK_FEES", 0.25, 0), ("BANK", 0, 0.25)],
    }
    complete = saved(import_statement(treasury, cid, "refund-after", revision + 3, posting, quiet_statement(posting, opening - 525)))
    payables = payables_view(complete)
    assert next(b for b in payables.carrier_bills if b.order == "FO-1").open == -5
    assert payables.carrier_bank.timing[0].amount_minor == -525
    assert payables.carrier_bank.timing[0].additional_vouchers == [f"{line.id}/F"]
    assert all(period.reconciled for period in payables.carrier_bank.periods)
    assert payables.carrier_bank.periods[0].opening_timing_minor == -525
    assert payables.carrier_bank.periods[0].closing_timing_minor == 0


def test_historical_unposted_return_requires_original_bytes_to_enrich_charge_evidence():
    _, treasury, cid, _, revision = setup_original("FO-1")
    xml = source_file(P2, 15_975, 900, "WIRE-ORIGINAL", returned=True, fee=25)
    current = saved(import_statement(treasury, cid, "source", revision, P2, xml))
    line = current.carrier_bank_lines[-1]
    historical = current.model_copy(update={"carrier_bank_lines": [*current.carrier_bank_lines[:-1], line.model_copy(
        update={"return_source_checked": False, "included_fee_minor": None})]})
    event = AllocateBankReturn(kind="allocate_return", line=line.id, legs=[
        {"original": {"order": "FO-1", "voucher": "FO-1/P-1"}, "amount_minor": 925},
    ])
    with pytest.raises(ValueError, match="reattach the exact"):
        record_bank(historical, event, P2)
    with pytest.raises(ValueError, match="differs from the retained source statement"):
        record_bank(historical, CamtFile(kind="import_camt", account="BANK-A", xml=xml + "\n"), P2)
    refreshed, message = record_bank(historical, CamtFile(kind="import_camt", account="BANK-A", xml=xml), P2)
    assert refreshed == current and "Verified return evidence" in message
    protect_bank(historical, refreshed, command=True)
    with pytest.raises(ValueError, match="require an authoritative"):
        protect_bank(historical, refreshed, command=False)
    posted, _ = record_bank(refreshed, event, P2)
    assert payables_view(posted).carrier_bank.periods[0].reconciled
