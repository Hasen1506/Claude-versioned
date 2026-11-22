"""Independent statement balance and account-ledger oracles for carrier cash."""
from datetime import timedelta
from hashlib import sha256

import pytest

from scp import transport
from scp.accounting import view
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client, team
from .test_freight_billing_integrity import shipped_freight
from .test_grouped_carrier_bank import D0, P1, P2, bank, cash_keys, saved


def fixture():
    ds = shipped_freight()
    for order, amount in (("FO-1", 40.25), ("FO-2", 59.75), ("FO-3", 100)):
        ds, _ = transport.settle(ds, order, amount, f"BILL-{order}", D0)
    return ds.model_copy(update={"finance": ds.finance.model_copy(update={"control_roles": {
        "master_data": ["owner@integrity.example"], "payments": ["buyer@integrity.example"],
        "billing": ["owner@integrity.example"],
    }})})


def send(token, company, key, revision, action, on, order, **params):
    return command(token, company, key, "transport", action, revision, date=on.isoformat(),
                   order=order, voucher=order, **params)


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_balance_carry_forward_and_company_bank_journal(backend, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    ds = fixture()
    owner, treasury, cid = team(ds)
    register = dict(company="E1", starts_on=P1.isoformat(), opening_minor=20_000)
    assert bank(treasury, cid, "unapproved", 1, "register_account", id="BANK-A", **register).status_code == 403
    assert not saved(bank(owner, cid, "register-a", 1, "register_account", id="BANK-A", **register)).carrier_bank_periods
    saved(bank(owner, cid, "register-b", 2, "register_account", id="BANK-B", **register))
    assert send(treasury, cid, "unassigned", 3, "pay_bill", P1, "FO-1", amount=40.25, reference="WIRE-COMB").status_code == 409
    assert send(treasury, cid, "wrong-company", 3, "pay_bill", P1, "FO-3", amount=100,
                reference="WIRE-COMB", bank_account="BANK-A").status_code == 409
    saved(send(treasury, cid, "pay-1", 3, "pay_bill", P1, "FO-1", amount=40.25, reference="WIRE-COMB", bank_account="BANK-A"))
    cash = saved(send(treasury, cid, "pay-2", 4, "pay_bill", P1, "FO-2", amount=59.75, reference="WIRE-COMB", bank_account="BANK-A"))
    assert cash.freight_orders[0].bill_payments[0].bank_account == "BANK-A"
    assert bank(treasury, cid, "line-only", 5, "import", company="E1", account="bank-a",
                csv=f"line,date,reference,amount,currency\nLINE-1,{P1},WIRE-COMB,-100,INR\n").status_code == 409
    csv = f"\ufeffline,date,reference,amount,currency\r\nLINE-1,{P1},WIRE-COMB,-100.00,INR\r\n"
    window = dict(account="BANK-A", number="S-1", starts_on=P1.isoformat(), ends_on=P1.isoformat(),
                  opening_minor=20_000, closing_minor=10_000, line_count=1, csv=csv)
    before = client.get(f"/api/companies/{cid}", headers=h(treasury)).json()
    for key, change in (("wrong-balance", {"closing_minor": 9_999}), ("wrong-count", {"line_count": 2}),
                        ("outside-window", {"csv": csv.replace(P1.isoformat(), P2.isoformat())})):
        assert bank(treasury, cid, key, 5, "import_period", **{**window, **change}).status_code == 409
    assert client.get(f"/api/companies/{cid}", headers=h(treasury)).json() == before
    assert bank(owner, cid, "wrong-grant", 5, "import_period", **window).status_code == 403
    from scp.companies import commands
    with monkeypatch.context() as change:
        def fail_receipt(*args, **kwargs):
            raise RuntimeError("forced receipt failure")

        change.setattr(commands, "_record", fail_receipt)
        with pytest.raises(RuntimeError, match="forced receipt"):
            bank(treasury, cid, "import-a", 5, "import_period", **window)
    assert client.get(f"/api/companies/{cid}", headers=h(treasury)).json() == before
    imported = saved(bank(treasury, cid, "import-a", 5, "import_period", **window))
    assert imported.carrier_bank_periods[0].file_sha256 == sha256(csv.encode()).hexdigest()
    duplicate = bank(treasury, cid, "import-a", 5, "import_period", **window)
    assert duplicate.json()["duplicate"] and duplicate.json()["revision"] == 6
    reoffered = bank(treasury, cid, "reoffered", 6, "import_period", **window)
    assert reoffered.json()["revision"] == 6
    changed = bank(treasury, cid, "changed-file", 6, "import_period", **{**window, "csv": csv.strip()})
    assert changed.status_code == 409 and "differs" in changed.text
    assert save(treasury, cid, imported.model_copy(update={"carrier_bank_periods": []}), 6).status_code == 403
    other = saved(bank(treasury, cid, "import-b", 6, "import_period", **{**window, "account": "BANK-B"}))
    line_a, line_b = other.carrier_bank_lines
    targets = cash_keys("FO-1", "FO-2")
    refuses = bank(treasury, cid, "wrong-account", 7, "match", line=line_b.id, version=0, targets=targets)
    assert refuses.status_code == 409 and "registered account" in refuses.text
    projected = {r.period.account: r for r in payables_view(other).carrier_bank.periods}
    assert projected["BANK-A"].ledger_opening_minor == 20_000 and projected["BANK-A"].ledger_closing_minor == 10_000
    assert projected["BANK-A"].unmatched_vouchers == ["FO-1/P-1", "FO-2/P-1"]
    assert projected["BANK-A"].unmatched_lines == ["LINE-1"] and not projected["BANK-A"].reconciled
    assert not projected["BANK-B"].reconciled and projected["BANK-B"].ledger_closing_minor == 20_000
    matched = saved(bank(treasury, cid, "match-a", 7, "match", line=line_a.id, version=0, targets=targets))
    assert payables_view(matched).carrier_bank.periods[-1].reconciled
    books = view(matched, period_end=P1)
    bank_lines = [(v.number, v.company, row.bank_account, row.debit, row.credit)
                  for v in books.vouchers for row in v.lines if row.account == "BANK"]
    assert set(bank_lines) == {("FO-1/P-1", "E1", "BANK-A", 0, 40.25), ("FO-2/P-1", "E1", "BANK-A", 0, 59.75)}
    assert books == view(cash, period_end=P1)
    released = saved(bank(treasury, cid, "release-a", 8, "release", line=line_a.id, version=1))
    assert not payables_view(released).carrier_bank.periods[-1].reconciled
    assert view(released, period_end=P1) == books
    saved(bank(treasury, cid, "rematch-a", 9, "match", line=line_a.id, version=2, targets=targets))
    adjust = {"kind": "adjust_bill", "amount_minor": 2000, "reference": "CREDIT-1", "reason": "Verified adjustment"}
    saved(send(owner, cid, "credit", 10, "bill_event", P2, "FO-1", event=adjust))
    refund = {"kind": "refund_bill", "amount_minor": 2000, "reference": "RFD-1", "bank_account": "BANK-A"}
    assert send(treasury, cid, "unassigned-refund", 11, "bill_event", P2, "FO-1",
                event={key: value for key, value in refund.items() if key != "bank_account"}).status_code == 409
    refund_books = saved(send(treasury, cid, "refund", 11, "bill_event", P2, "FO-1", event=refund))
    p3 = P2 + timedelta(days=1)
    next_period = {**window, "number": "S-2", "starts_on": P2.isoformat(), "ends_on": P2.isoformat(),
                   "opening_minor": 10_000, "closing_minor": 12_000,
                   "csv": f"line,date,reference,amount,currency\nLINE-2,{P2},RFD-1,+20.00,INR\n"}
    for key, replacement in (("gap", {"starts_on": p3.isoformat(), "ends_on": p3.isoformat()}),
                             ("overlap", {"starts_on": P1.isoformat()}), ("carry-error", {"opening_minor": 10_001})):
        assert bank(treasury, cid, key, 12, "import_period", **{**next_period, **replacement}).status_code == 409
    next_import = saved(bank(treasury, cid, "import-next", 12, "import_period", **next_period))
    refund_match = [{"order": "FO-1", "voucher": "FO-1/R-2"}]
    tied = saved(bank(treasury, cid, "match-refund", 13, "match", line=next_import.carrier_bank_lines[-1].id,
                      version=0, targets=refund_match))
    assert all(r.reconciled for r in payables_view(tied).carrier_bank.periods if r.period.account == "BANK-A")
    assert view(refund_books, period_end=P2) == view(tied, period_end=P2)
    credit = next(row for voucher in view(tied, period_end=P2).vouchers if voucher.number == "FO-1/R-2"
                  for row in voucher.lines if row.account == "BANK")
    assert credit.bank_account == "BANK-A" and (credit.debit, credit.credit) == (20, 0)
    quiet = {**next_period, "number": "S-3", "starts_on": p3.isoformat(), "ends_on": p3.isoformat(),
             "opening_minor": 12_000, "line_count": 0, "csv": "line,date,reference,amount,currency\n"}
    assert bank(treasury, cid, "import-empty", 14, "import_period", **quiet).status_code == 200


def test_equal_balances_keep_offsetting_unmatched_postings_open():
    owner, treasury, cid = team(fixture())
    saved(bank(owner, cid, "register", 1, "register_account", id="BANK-A", company="E1", starts_on=P1.isoformat(),
               opening_minor=20000))
    saved(send(treasury, cid, "payment", 2, "pay_bill", P1, "FO-1", amount=40.25, reference="PAY", bank_account="BANK-A"))
    saved(send(owner, cid, "credit", 3, "bill_event", P1, "FO-1", event={
        "kind": "adjust_bill", "amount_minor": 4025, "reference": "CREDIT", "reason": "Credit in full"}))
    saved(send(treasury, cid, "refund", 4, "bill_event", P1, "FO-1", event={
        "kind": "refund_bill", "amount_minor": 4025, "reference": "REFUND", "bank_account": "BANK-A"}))
    imported = saved(bank(treasury, cid, "empty", 5, "import_period", account="BANK-A", number="S-1",
                         starts_on=P1.isoformat(), ends_on=P1.isoformat(), opening_minor=20000, closing_minor=20000,
                         line_count=0, csv="line,date,reference,amount,currency\n"))
    result, = payables_view(imported).carrier_bank.periods
    assert result.ledger_opening_minor == result.ledger_closing_minor == result.period.closing_minor
    assert result.unmatched_vouchers == ["FO-1/P-1", "FO-1/R-2"] and not result.reconciled
