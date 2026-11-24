"""Dated supplier invoices allocate exact receipt amounts and preserve posted matches."""
from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest

from scp.accounting import view
from scp.companies import commands
from scp.model import Dataset
from scp.versions import Store, set_store

from .factory import base, lp
from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client, team

ORDER = "PO-1-10"


def business(currency, price):
    raw = base()
    raw["settings"]["currency"] = currency
    raw["execution"] = {"price_control": "moving_average"}
    lp(raw, "P", "A")["on_hand"] = lp(raw, "P", "B")["on_hand"] = 0
    raw["purchase_orders"] = [{"id": "PO-1", "supplier": "S", "location": "P", "order_date": "2026-01-05"}]
    raw["receipts"] = [{"id": ORDER, "po": "PO-1", "kind": "purchase", "product": "B", "location": "P",
                        "qty": 2, "price": price, "due_date": "2026-01-06", "source": "PIR-B"}]
    return team(Dataset.model_validate(raw))


def receive(user, cid, revision, day, qty):
    return command(user, cid, f"receipt-{revision}", "purchasing", "receive", revision, date=day, po="PO-1",
                   lines=[{"id": ORDER, "qty": qty}])


def invoice(user, cid, revision, day, qty=1, **terms):
    return command(user, cid, f"invoice-{revision}", "purchasing", "enter_invoice", revision, date=day,
                   reference=f"Supplier-{revision}", po="PO-1", lines=[{"order": ORDER, "qty": qty}], **terms)


def current(response):
    assert response.status_code == 200, response.text
    return Dataset.model_validate(response.json()["company"]["dataset"])


def balances(dataset, day):
    result = view(dataset, period_end=date.fromisoformat(day))
    assert all(check.ok for check in result.checks), result.checks
    return {row.account: Decimal(str(row.balance)) for row in result.balances}


@pytest.mark.parametrize(("currency", "price", "stock", "settled_first", "bill", "tax"), [
    ("JPY", 600.25, "1201", "601", "600", "1"),
    ("KWD", 1.2345, "2.469", "1.235", "1.235", "0.001"),
])
def test_partial_invoices_exact_cancellation_and_same_day_replacement(currency, price, stock, settled_first, bill, tax):
    total, first, net, charge = map(Decimal, (stock, settled_first, bill, tax))
    owner, _, cid = business(currency, price)
    got = current(receive(owner, cid, 1, "2026-01-06", 2))
    assert balances(got, "2026-01-06") == {"STOCK": total, "GRIR": -total}
    issued = current(invoice(owner, cid, 2, "2026-01-07", tax=float(charge)))
    one = balances(issued, "2026-01-07")
    assert one["GRIR"] == first - total and one["PAYABLES"] == -net - charge
    assert one["INPUT_TAX"] == charge and one["STOCK"] == total
    assert one.get("PRICE_DIFF", 0) == net - first
    second = current(invoice(owner, cid, 3, "2026-01-08"))
    two = balances(second, "2026-01-08")
    assert two["GRIR"] == 0 and two["PAYABLES"] == -2 * net - charge and two["PRICE_DIFF"] == 2 * net - total
    cancelled = current(command(owner, cid, "cancel", "purchasing", "cancel_invoice", 4,
                                date="2026-01-08", po="SI-00001"))
    assert cancelled.supplier_invoices[0].cancelled_after == 2
    assert balances(cancelled, "2026-01-07") == one
    left = balances(cancelled, "2026-01-08")
    assert left["GRIR"] == -first and left["PAYABLES"] == -net and left["INPUT_TAX"] == 0
    assert left["PRICE_DIFF"] == net - (total - first)
    purchasing = client.post("/api/purchasing", json=cancelled.model_dump(mode="json")).json()["payables"]
    assert Decimal(str(purchasing["not_invoiced_value"])) == first
    assert Decimal(str(purchasing["open_value"])) == net
    replacement = current(invoice(owner, cid, 5, "2026-01-08"))
    assert balances(replacement, "2026-01-08")["GRIR"] == 0
    payment = command(owner, cid, "attempt-settlement", "purchasing", "pay_invoice", 6,
                      date="2026-01-09", po="SI-00003", amount=float(net))
    assert payment.status_code == 409 and "two-decimal currency" in payment.text
    reversed_receipt = command(owner, cid, "attempt-reversal", "stock", "reverse", 6,
                               date="2026-01-09", movement=replacement.movements[0].id)
    assert reversed_receipt.status_code == 409 and "before reversing billed stock" in reversed_receipt.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 6

    # Cancel the invoice that owned the first slice. Reversing that slice clears exactly its booked stock cost.
    unbilled = current(command(owner, cid, "cancel-replacement", "purchasing", "cancel_invoice", 6,
                               date="2026-01-09", po="SI-00003"))
    original = unbilled.movements[0]
    reversal = original.model_copy(update={"id": "REV-PART", "qty": 1, "date": date(2026, 1, 10),
                                           "final": False, "doc": "MD-REV-PART", "reversal_of": original.id})
    proposed = unbilled.model_copy(update={"movements": [*unbilled.movements, reversal]})
    saved = save(owner, cid, proposed, 7)
    assert saved.status_code == 200, saved.text
    data = Dataset.model_validate(client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"])
    closing = balances(data, "2026-01-10")
    assert closing["GRIR"] == 0 and closing["STOCK"] == total - first and closing["PAYABLES"] == -net
    assert closing.get("DELIVERY", 0) == 0
    assert client.post("/api/accounting/export?format=csv", json=data.model_dump(mode="json")).status_code == 200
    assert client.post("/api/accounting/export?format=tally", json=data.model_dump(mode="json")).status_code == 409


def test_backdated_invoice_cannot_replace_existing_match_or_bill_future_receipt():
    owner, _, cid = business("KWD", 1.2345)
    current(receive(owner, cid, 1, "2026-01-06", 1))
    current(receive(owner, cid, 2, "2026-01-08", 1))
    before_goods = invoice(owner, cid, 3, "2026-01-05")
    assert before_goods.status_code == 409 and "unbilled receipts dated" in before_goods.text
    current(invoice(owner, cid, 3, "2026-01-08"))
    conflict = invoice(owner, cid, 4, "2026-01-07")
    assert conflict.status_code == 409 and "posted receipt allocation" in conflict.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 4


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_one_fils_invoice_is_open_and_duplicate_posting_is_atomic(backend, request, monkeypatch):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)
        request.addfinalizer(store.db.close)
    owner, _, cid = business("KWD", 0.001)
    current(receive(owner, cid, 1, "2026-01-06", 2))
    previous = client.get(f"/api/companies/{cid}", headers=h(owner)).json()

    def post():
        return invoice(owner, cid, 2, "2026-01-07")

    def fail(*args, **kwargs):
        raise OSError("receipt write failed")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail)
        with pytest.raises(OSError, match="receipt write failed"):
            post()
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json() == previous
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(post) for _ in range(2)]
        replies = [future.result(timeout=20) for future in futures]
    for reply in replies:
        data = current(reply)
        assert len(data.supplier_invoices) == 1 and reply.json()["revision"] == 3
    assert {reply.json()["duplicate"] for reply in replies} == {True, False}
    assert balances(data, "2026-01-07")["PAYABLES"] == Decimal("-0.001")
    payables = client.post("/api/purchasing", json=data.model_dump(mode="json")).json()["payables"]
    assert payables["open_value"] == 0.001 and payables["invoices"][0]["status"] == "to pay"
