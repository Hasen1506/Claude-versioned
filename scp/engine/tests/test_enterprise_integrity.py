"""Independent counterexamples from the enterprise audit, expressed as release gates."""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from scp.accounting import view
from scp.api.app import app
from scp.actuals.stock import before, stock
from scp.companies import get_companies
from scp.companies.patch import make_patch
from scp.connect import messages
from scp.connect.erp import ErpStock, apply_stock
from scp.model import Dataset
from scp.purchasing import PurchasingError, act

from .test_companies import h, join, new_company, signup
from .test_backup_postgres import pg_databases as pg_databases
from .test_procure_to_pay import JAN, ordered, received

client = TestClient(app)


def balance(ds, account, on=JAN, company=""):
    return next((b.balance for b in view(ds, period_end=on).balances
                 if b.account == account and b.company == company), 0.0)


def team(ds):
    owner, planner = signup("owner@integrity.example"), signup("buyer@integrity.example")
    cid = new_company(owner, ds.model_dump(mode="json"))
    join(owner, cid, "buyer@integrity.example", "planner")
    return owner, planner, cid


@pytest.mark.parametrize("route", ["whole", "patch", "merge"])
def test_a_blocked_payment_cannot_be_persisted_by_another_write_path(route):
    ds, _ = act(received(b=100, c=0), "enter_invoice", on=JAN,
                lines=[{"order": "PO-00001-10", "qty": 100, "price": 11}])
    owner, planner, cid = team(ds)
    doc = ds.model_dump(mode="json")
    assert client.post("/api/purchasing/act", headers=h(planner), json={
        "dataset": doc, "action": "pay_invoice", "po": "SI-00001"}).status_code == 409
    altered = copy.deepcopy(doc)
    altered["supplier_invoices"][0]["payments"] = [{"date": "2026-01-05", "amount": 1210}]
    if route == "merge":
        result = client.post(f"/api/companies/{cid}/merge", headers=h(planner),
                             json={"base": doc, "dataset": altered, "base_revision": 1})
    else:
        body = {"dataset": altered} if route == "whole" else {"patch": make_patch(doc, altered)}
        result = client.put(f"/api/companies/{cid}", headers=h(planner), json={**body, "base_revision": 1})
    assert result.status_code == 403, result.text
    kept = Dataset.model_validate(client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"])
    assert kept.supplier_invoices[0].open == 1210 and balance(kept, "BANK") == 0


def test_increasing_a_released_order_requires_a_new_release_at_persistence():
    d = ordered()
    d["receipts"] = d["receipts"][:1]
    d["receipts"][0]["qty"] = 1
    d["purchase_orders"][0]["sent_on"] = None
    d["purchasing"]["release_levels"] = [{"name": "CFO", "above": 5000,
                                             "approvers": ["cfo@integrity.example"]}]
    ds = Dataset.model_validate(d)
    _, planner, cid = team(ds)
    d["receipts"][0]["price"] = 10000
    result = client.put(f"/api/companies/{cid}", headers=h(planner), json={"dataset": d, "base_revision": 1})
    assert result.status_code == 403 and "released again" in result.json()["detail"]


def test_payment_removal_cannot_hide_in_a_restore():
    ds, _ = act(received(b=100, c=0), "enter_invoice", "PO-00001", on=JAN)
    owner, planner, cid = team(ds)
    paid, _ = act(ds, "pay_invoice", "SI-00001", on=JAN)
    saved = client.put(f"/api/companies/{cid}", headers=h(planner),
                       json={"dataset": paid.model_dump(mode="json"), "base_revision": 1})
    assert saved.status_code == 200, saved.text
    restored = client.post(f"/api/companies/{cid}/restore", headers=h(owner),
                           json={"revision": 1, "base_revision": saved.json()["meta"]["revision"]})
    assert restored.status_code == 403 and "payments cannot" in restored.json()["detail"]


def test_an_invoice_cancelled_later_keeps_the_original_period_and_adds_a_dated_reversal():
    ds, _ = act(received(b=100, c=0), "enter_invoice", "PO-00001", on=JAN)
    cutoff = date(2026, 1, 10)
    original = view(ds, period_end=cutoff)
    cancelled, _ = act(ds, "cancel_invoice", "SI-00001", on=date(2026, 1, 20))
    assert view(cancelled, period_end=cutoff).model_dump() == original.model_dump()
    assert balance(cancelled, "PAYABLES", cutoff) == -1100
    assert balance(cancelled, "PAYABLES", date(2026, 1, 20)) == 0
    vs = view(cancelled, period_end=date(2026, 1, 20)).vouchers
    assert any(v.number == "SI-00001" and v.date == JAN for v in vs)
    assert any(v.number == "SI-00001/REV" and v.date == date(2026, 1, 20) for v in vs)
    assert all(c.ok for c in view(cancelled, period_end=date(2026, 1, 20)).checks)


def test_posting_exchange_rates_and_stock_values_survive_a_planning_rate_edit():
    d = ordered()
    d["settings"].update(currency="INR", fx_rates={"USD": 80})
    d["purchase_orders"][0]["currency"] = "USD"
    d["purchasing_sources"][0]["currency"] = "USD"
    ds, _ = act(Dataset.model_validate(d), "receive", "PO-00001",
                lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    ds, _ = act(ds, "enter_invoice", "PO-00001", on=JAN)
    original = view(ds, period_end=JAN).model_dump()
    edited = ds.model_dump(mode="json")
    edited["settings"]["fx_rates"]["USD"] = 90
    changed = Dataset.model_validate(edited)
    assert balance(changed, "PAYABLES") == -88000
    assert view(changed, period_end=JAN).model_dump() == original


def test_raw_save_cannot_remove_an_invoice_or_change_a_posted_movement():
    ds, _ = act(received(b=100, c=0), "enter_invoice", "PO-00001", on=JAN)
    _, planner, cid = team(ds)
    for field in ("supplier_invoices", "movements"):
        changed = ds.model_dump(mode="json")
        if field == "movements":
            changed[field][0]["qty"] += 1
        else:
            changed[field] = []
        response = client.put(f"/api/companies/{cid}", headers=h(planner),
                              json={"dataset": changed, "base_revision": 1})
        assert response.status_code == 403, response.text


def two_entities():
    d = ordered()
    d["entities"] = [{"id": "E1"}, {"id": "E2"}]
    d["locations"][0]["entity"] = "E1"
    d["locations"].append({"id": "P2", "type": "plant", "entity": "E2"})
    d["location_products"].append({"location": "P2", "product": "B", "on_hand": 0})
    d["purchase_orders"].append({**d["purchase_orders"][0], "id": "PO-00002", "location": "P2"})
    d["receipts"].append({**d["receipts"][0], "id": "PO-00002-10", "po": "PO-00002", "location": "P2"})
    ds, _ = act(Dataset.model_validate(d), "receive", "PO-00001", on=JAN)
    return act(ds, "receive", "PO-00002", on=JAN)[0]


def test_mixed_legal_entities_are_rejected_and_separate_invoices_reconcile():
    ds = two_entities()
    with pytest.raises(PurchasingError, match="one legal entity"):
        act(ds, "enter_invoice", on=JAN, lines=[
            {"order": "PO-00001-10", "qty": 100}, {"order": "PO-00002-10", "qty": 100}])
    for po in ("PO-00001", "PO-00002"):
        ds, _ = act(ds, "enter_invoice", po, on=JAN)
    assert all(c.ok for c in view(ds, period_end=JAN).checks)
    assert balance(ds, "PAYABLES", company="E1") == -1375
    assert balance(ds, "PAYABLES", company="E2") == -1100


def test_export_rejects_an_unreconciled_legacy_document():
    ds = two_entities()
    d = ds.model_dump(mode="json")
    d["supplier_invoices"] = [{"id": "LEGACY", "supplier": "S", "date": "2026-01-05", "due_date": "2026-02-04",
        "lines": [{"order": "PO-00001-10", "product": "B", "qty": 100, "price": 10},
                  {"order": "PO-00002-10", "product": "B", "qty": 100, "price": 10}], "tax": 200}]
    result = client.post("/api/accounting/export?format=csv", json=d)
    assert result.status_code == 409 and "do not reconcile" in result.json()["detail"]


def test_failed_inbound_log_rolls_back_the_company_revision_and_effect(monkeypatch):
    owner = signup("integration@integrity.example")
    cid = new_company(owner, received(b=0, c=30).model_dump(mode="json"))
    c = get_companies()
    user = c.whoami(owner)
    initial = c.open(user, cid)
    def broken(*args, **kwargs):
        raise OSError("injected message log failure")
    with monkeypatch.context() as patch:
        patch.setattr(messages, "log", broken)
        with pytest.raises(OSError, match="injected"):
            messages.receive(c, user, cid, "stock", "SNAPSHOT-1", lambda x: apply_stock(
                x, [ErpStock(location="P", product="B", qty=100)], JAN))
    kept = c.open(user, cid)
    assert kept.meta.revision == initial.meta.revision and kept.dataset == initial.dataset
    assert c.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert c.db.execute("SELECT COUNT(*) FROM inbound_receipts").fetchone()[0] == 0
    first = messages.receive(c, user, cid, "stock", "SNAPSHOT-1", lambda x: apply_stock(
        x, [ErpStock(location="P", product="B", qty=100)], JAN))
    from scp.actuals.post import post
    changed, _ = post(Dataset.model_validate(c.open(user, cid).dataset), "scrap",
                       location="P", product="B", qty=10, on=JAN)
    c.save(user, cid, changed.model_dump(mode="json"), first.revision)
    again = messages.receive(c, user, cid, "stock", "SNAPSHOT-1", lambda x: apply_stock(
        x, [ErpStock(location="P", product="B", qty=100)], JAN))
    assert again.message.status == "duplicate"
    final = Dataset.model_validate(c.open(user, cid).dataset)
    assert stock(before(final, JAN + timedelta(days=1)))[("P", "B")] == 90


def test_closed_period_rejects_backdated_payments():
    ds, _ = act(received(b=100, c=0), "enter_invoice", "PO-00001", on=JAN)
    ds = ds.model_copy(update={"finance": ds.finance.model_copy(update={"closed_through": JAN})})
    _, planner, cid = team(ds)
    paid, _ = act(ds, "pay_invoice", "SI-00001", on=JAN)
    result = client.put(f"/api/companies/{cid}", headers=h(planner),
                        json={"dataset": paid.model_dump(mode="json"), "base_revision": 1})
    assert result.status_code == 403 and "closed" in result.json()["detail"]


def test_postgres_inbound_atomicity_and_replay_identity_survive_restore(pg_databases, tmp_path, monkeypatch):
    from scp.backup import backup_postgres
    from scp.companies.store import Companies
    from scp.migrate_postgres import migrate
    from scp.versions.store import Store
    from scp.actuals.post import post

    url = pg_databases()
    c = Companies(Store(url))
    user = c.signup("pg@integrity.example", "Integration", "integration-audit-river-563").user
    meta = c.create(user, received(b=0, c=30).model_dump(mode="json"))
    original = c.open(user, meta.id)
    def callback(ds):
        return apply_stock(ds, [ErpStock(location="P", product="B", qty=100)], JAN)
    def broken(*args, **kwargs):
        raise OSError("injected postgres log failure")
    with monkeypatch.context() as patch:
        patch.setattr(messages, "log", broken)
        with pytest.raises(OSError, match="injected postgres"):
            messages.receive(c, user, meta.id, "stock", "PG-SNAPSHOT", callback)
    assert c.open(user, meta.id).dataset == original.dataset
    assert c.open(user, meta.id).meta.revision == original.meta.revision
    first = messages.receive(c, user, meta.id, "stock", "PG-SNAPSHOT", callback)
    changed, _ = post(Dataset.model_validate(c.open(user, meta.id).dataset), "scrap",
                       location="P", product="B", qty=10, on=JAN)
    c.save(user, meta.id, changed.model_dump(mode="json"), first.revision)
    saved = backup_postgres(url, tmp_path)
    target = pg_databases()
    monkeypatch.setenv("DATABASE_URL", target)
    migrate(saved, apply=True)
    restored = Companies(Store(target))
    again = restored.signin("pg@integrity.example", "integration-audit-river-563").user
    answer = messages.receive(restored, again, meta.id, "stock", "PG-SNAPSHOT", callback)
    assert answer.message.status == "duplicate"
    ds = Dataset.model_validate(restored.open(again, meta.id).dataset)
    assert stock(before(ds, JAN + timedelta(days=1)))[("P", "B")] == 90
    assert restored.db.execute("SELECT COUNT(*) FROM inbound_receipts").fetchone()[0] == 1
    c.db.close()
    restored.db.close()


def test_a_planner_cannot_loosen_release_policy_then_approve_a_larger_order():
    ds = Dataset.model_validate(ordered(release_levels=[{"name": "CFO", "above": 5000,
                                                       "approvers": ["cfo@integrity.example"]}]))
    _, planner, cid = team(ds)
    changed = ds.model_dump(mode="json")
    changed["purchasing"]["release_levels"] = []
    response = client.put(f"/api/companies/{cid}", headers=h(planner),
                          json={"dataset": changed, "base_revision": 1})
    assert response.status_code == 403 and "release policy" in response.json()["detail"]


def test_received_purchase_line_prices_are_immutable_across_raw_saves():
    ds = received(b=100, c=0)
    _, planner, cid = team(ds)
    changed = ds.model_dump(mode="json")
    changed["receipts"][0]["price"] = 999
    response = client.put(f"/api/companies/{cid}", headers=h(planner),
                          json={"dataset": changed, "base_revision": 1})
    assert response.status_code == 403 and "posted price" in response.json()["detail"]


def test_a_new_movement_cannot_forge_the_valuation_of_old_stock():
    ds = received(b=100, c=0)
    _, planner, cid = team(ds)
    changed = ds.model_dump(mode="json")
    forged = {**changed["movements"][0], "id": "GM-FORGED", "opening_standards": {"P": {"A": 999999}}}
    changed["movements"].append(forged)
    result = client.put(f"/api/companies/{cid}", headers=h(planner),
                        json={"dataset": changed, "base_revision": 1})
    assert result.status_code == 403 and "opening valuation" in result.json()["detail"]


def test_a_raw_purchase_receipt_cannot_bypass_the_overdelivery_tolerance():
    ds = received(b=100, c=0)
    _, planner, cid = team(ds)
    changed = ds.model_dump(mode="json")
    forged = {**changed["movements"][0], "id": "GM-OVERSIZED", "qty": 1000}
    changed["movements"].append(forged)
    result = client.put(f"/api/companies/{cid}", headers=h(planner),
                        json={"dataset": changed, "base_revision": 1})
    assert result.status_code == 403 and "over-delivery tolerance" in result.json()["detail"]


def test_restore_cannot_resurrect_a_release_under_an_obsolete_policy():
    d = ordered(approval_limit=50000)
    d["receipts"] = d["receipts"][:1]
    d["receipts"][0]["price"] = 100
    ds = Dataset.model_validate(d)  # INR 10,000 was released under the old threshold.
    owner, _, cid = team(ds)
    changed = ds.model_dump(mode="json")
    changed["purchasing"]["approval_limit"] = 5000
    changed["purchase_orders"][0]["approved"] = False
    saved = client.put(f"/api/companies/{cid}", headers=h(owner),
                       json={"dataset": changed, "base_revision": 1})
    assert saved.status_code == 200, saved.text
    restored = client.post(f"/api/companies/{cid}/restore", headers=h(owner),
                           json={"revision": 1, "base_revision": 2})
    assert restored.status_code == 403 and "release" in restored.json()["detail"]


def test_an_invoice_cannot_use_a_rate_that_is_still_waiting_for_master_approval():
    d = ordered()
    d["settings"].update(currency="INR", fx_rates={"USD": 80})
    d["purchase_orders"][0]["currency"] = "USD"
    d["purchasing_sources"][0]["currency"] = "USD"
    ds, _ = act(Dataset.model_validate(d), "receive", "PO-00001", on=JAN)
    owner, _, cid = team(ds)
    get_companies().db.execute("UPDATE companies SET approval = 1 WHERE id = ?", (cid,))
    changed = ds.model_dump(mode="json")
    changed["settings"]["fx_rates"]["USD"] = 90
    proposed, _ = act(Dataset.model_validate(changed), "enter_invoice", "PO-00001", on=JAN)
    response = client.put(f"/api/companies/{cid}", headers=h(owner),
        json={"dataset": proposed.model_dump(mode="json"), "base_revision": 1})
    assert response.status_code == 403 and "posting basis" in response.json()["detail"]
