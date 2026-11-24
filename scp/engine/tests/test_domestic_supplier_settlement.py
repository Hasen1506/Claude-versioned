"""One domestic supplier settlement across the live journal, Purchasing and cash outlook."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest

from scp.accounting import csv_rows, view
from scp.companies import commands
from scp.finance import run_finance
from scp.purchasing.payables import pay_invoice, reverse_invoice_payment
from scp.tower.capital import capital_at
from scp.tower.worklist import _money
from scp.versions import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import h, join, signup
from .test_company_commands import command
from .test_domestic_invoice_currency import balances, business, current, invoice, receive
from .test_enterprise_integrity import client

INV = "SI-00001"


def payment(user, cid, revision, day, reference, amount=None, identifier=None, iid=INV):
    return command(user, cid, identifier or f"pay-{revision}", "purchasing", "pay_invoice",
                   revision, date=day, po=iid, reference=reference, amount=amount)


def reversal(user, cid, revision, day, number, identifier=None):
    return command(user, cid, identifier or f"reverse-{revision}", "purchasing", "reverse_invoice_payment",
                   revision, date=day, po=INV, payment_number=number, note="Returned by bank")


def payables(ds):
    response = client.post("/api/purchasing", json=ds.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    return response.json()["payables"]


def document(user, cid):
    return client.get(f"/api/companies/{cid}", headers=h(user)).json()["dataset"]


def put_payment_history(user, cid, revision, dataset):
    raw = document(user, cid)
    raw["supplier_invoices"][0]["payments"] = dataset.supplier_invoices[0].model_dump(mode="json")["payments"]
    return save(user, cid, raw, revision)


@pytest.mark.parametrize("currency,price,tax,gross,cash,discount,minor", [
    ("KWD", 1.2345, 0.001, "1.236", "0.989", "0.247", "0.001"),
    ("JPY", 600.25, 1, "601", "481", "120", "1"),
])
def test_payment_reversal_and_cancellation_reconcile_at_every_cutoff(currency, price, tax, gross, cash, discount, minor):
    total, bank, disc, unit = map(Decimal, (gross, cash, discount, minor))
    owner, _, cid = business(currency, price, vendors=[{"supplier": "S", "payment_terms": "EARLY"}],
                             payment_terms=[{"id": "EARLY", "net_days": 10, "discount_days": 6, "discount": 0.2}])
    current(receive(owner, cid, 1, "2026-01-06", 1))
    issued = current(invoice(owner, cid, 2, "2026-01-07", tax=tax))
    original = balances(issued, "2026-01-07")
    paid = current(payment(owner, cid, 3, "2026-01-08", "wire-1"))
    assert paid.supplier_invoices[0].open == 0
    assert balances(paid, "2026-01-07") == original
    paid_balances = balances(paid, "2026-01-08")
    assert paid_balances["PAYABLES"] == 0 and paid_balances["BANK"] == -bank
    assert paid_balances["DISC_RECEIVED"] == -disc and "SUSPENSE" not in paid_balances
    assert payables(paid)["open_value"] == 0
    refused = command(owner, cid, "active-cancel", "purchasing", "cancel_invoice", 4, date="2026-01-09", po=INV)
    assert refused.status_code == 409
    undone = current(reversal(owner, cid, 4, "2026-01-09", 1))
    assert balances(undone, "2026-01-08") == paid_balances
    reversed_balances = balances(undone, "2026-01-09")
    assert reversed_balances["BANK"] == reversed_balances["DISC_RECEIVED"] == 0
    assert reversed_balances["PAYABLES"] == -total and reversed_balances["GRIR"] == original["GRIR"]
    assert Decimal(str(payables(undone)["open_value"])) == total
    assert reversal(owner, cid, 5, "2026-01-09", 1).status_code == 409
    reused = payment(owner, cid, 5, "2026-01-09", " ＷＩＲＥ-1 ", float(unit))
    assert reused.status_code == 409 and "unused bank reference" in reused.text
    too_precise = payment(owner, cid, 5, "2026-01-09", "wire-2", float(unit) / 2)
    assert too_precise.status_code == 409 and "exact" in too_precise.text
    part = current(payment(owner, cid, 5, "2026-01-09", "wire-2", float(unit)))
    assert part.supplier_invoices[0].payments[2].discount == 0
    closing = current(payment(owner, cid, 6, "2026-01-10", "wire-3"))
    assert Decimal(str(closing.supplier_invoices[0].payments[3].amount)) == total - unit
    assert balances(closing, "2026-01-10")["BANK"] == -total
    assert reversal(owner, cid, 7, "2026-01-09", 3).status_code == 409
    current(reversal(owner, cid, 7, "2026-01-11", 3))
    current(reversal(owner, cid, 8, "2026-01-11", 4))
    final = current(command(owner, cid, "cancel-after-reversal", "purchasing", "cancel_invoice", 9,
                            date="2026-01-11", po=INV))
    close = balances(final, "2026-01-11")
    assert close["PAYABLES"] == close["BANK"] == close["DISC_RECEIVED"] == 0
    assert close["GRIR"] == -close["STOCK"]
    book = view(final, period_end=date(2026, 1, 11))
    assert {f"{INV}/{k}" for k in range(1, 7)} <= {v.number for v in book.vouchers}
    assert "Returned by bank" in "\n".join(",".join(row) for row in csv_rows(book, final))


def test_payment_controls_and_one_fils_reporting():
    owner, warehouse, cid = business("KWD", 0.001)
    cashier = signup("cashier@settlement.example")
    join(owner, cid, "cashier@settlement.example", "planner")
    setup = document(owner, cid)
    setup["finance"] = {"separate_payments": True, "control_roles": {
        "warehouse": ["buyer@integrity.example"],
        "billing": ["owner@integrity.example"],
        "payments": ["owner@integrity.example", "cashier@settlement.example"],
        "period_close": ["owner@integrity.example"],
    }}
    assert save(owner, cid, setup, 1).status_code == 200
    current(receive(warehouse, cid, 2, "2026-01-06", 2))
    current(invoice(owner, cid, 3, "2026-01-07"))
    issued = current(invoice(owner, cid, 4, "2026-01-07"))
    assert payment(owner, cid, 5, "2026-01-08", "PENNY").status_code == 403
    assert payment(warehouse, cid, 5, "2026-01-08", "PENNY").status_code == 403
    proposed, _ = pay_invoice(issued, INV, on=date(2026, 1, 8), reference="PENNY")
    direct = put_payment_history(cashier, cid, 5, proposed)
    assert direct.status_code == 403 and "signed-in company command" in direct.text
    preview = client.post("/api/purchasing/act", json={"dataset": issued.model_dump(mode="json"),
                                                       "action": "pay_invoice", "po": INV, "reference": "PENNY"})
    assert preview.status_code == 422
    paid = current(payment(cashier, cid, 5, "2026-01-08", "PENNY"))
    assert payment(cashier, cid, 6, "2026-01-08", "penny", iid="SI-00002").status_code == 409
    proposed, _ = reverse_invoice_payment(paid, INV, 1, date(2026, 1, 9), "Cash returned")
    direct = put_payment_history(cashier, cid, 6, proposed)
    assert direct.status_code == 403 and "signed-in company command" in direct.text
    closed = document(owner, cid)
    closed["finance"]["closed_through"] = "2026-01-08"
    assert save(owner, cid, closed, 6).status_code == 200
    refused = reversal(cashier, cid, 7, "2026-01-08", 1)
    assert refused.status_code == 403 and "closed" in refused.text
    assert reversal(owner, cid, 7, "2026-01-09", 1).status_code == 403
    reopened = current(reversal(cashier, cid, 7, "2026-01-09", 1))
    assert payables(reopened)["open_value"] == 0.002
    snapshot = reopened.model_copy(update={"settings": reopened.settings.model_copy(
        update={"planning_start": date(2026, 2, 15)})})
    assert run_finance(snapshot).cash.overdue_out == 0.002
    assert run_finance(snapshot).cash.weeks[0].by["supplier_invoices"] == -0.002
    items = []
    _money(snapshot, items.append)
    assert sum("0.001 KWD unpaid" in item.message for item in items) == 2
    ageing = capital_at(snapshot, {}, {}, date(2026, 2, 15), 90, 1)
    assert ageing.ap == 0.002


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_settlement_write_failure_and_concurrent_retry(backend, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)
        request.addfinalizer(store.db.close)
    owner, _, cid = business("KWD", 0.001)
    current(receive(owner, cid, 1, "2026-01-06", 1))
    issued = current(invoice(owner, cid, 2, "2026-01-07"))

    def post():
        return payment(owner, cid, 3, "2026-01-08", "ATOMIC")

    def fail(*args):
        raise OSError("settlement receipt failed")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail)
        with pytest.raises(OSError, match="settlement receipt failed"):
            post()
    before = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    assert before["meta"]["revision"] == 3 and not before["dataset"]["supplier_invoices"][0]["payments"]
    assert balances(issued, "2026-01-08")["PAYABLES"] == Decimal("-0.001")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(post) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert {r.json()["duplicate"] for r in responses if r.status_code == 200} == {True, False}
    for response in responses:
        data = current(response)
        assert len(data.supplier_invoices[0].payments) == 1
        assert balances(data, "2026-01-08")["BANK"] == Decimal("-0.001")
