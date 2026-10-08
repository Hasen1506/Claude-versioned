"""PR #19 audit: withdrawal lifecycles, restored ERP orders, duplicate adjustments and billed tax snapshots."""
from copy import deepcopy
import json

import pytest

from scp.companies.store import Companies
from scp.connect.erp import withdrawn, withdrawn_version
from scp.purchasing import PurchasingError, act
from scp.sales import (
    create_deliveries, create_invoices, create_order, create_return, credit_return, issue, receive_return, tax_split,
)
from scp.versions import Store

from .factory import ds
from .test_connections import client, company, doc_of, h, setup
from .test_order_to_cash import LINES, shop
from .test_procure_to_pay import JAN, received


KINDS = ["purchase_order", "production_order", "transfer_order"]


def _orders(key, path, kind, everything=False):
    return client.get(path + f"/erp/{kind.replace('_', '-')}s", headers=h(key),
                      params={"all": str(everything).lower()}).json()["orders"]


def _ack(key, path, ack, message_id=""):
    r = client.post(path + "/erp/acknowledge", headers=h(key), json={"orders": [ack], "message_id": message_id})
    assert r.status_code == 200, r.text
    return r.json()["message"]


def _delete(owner, cid, path, kind, oid):
    c = doc_of(owner, cid)
    d = c["dataset"]
    if kind == "purchase_order":
        d["purchase_orders"] = [p for p in d["purchase_orders"] if p["id"] != oid]
        d["receipts"] = [r for r in d["receipts"] if r.get("po") != oid]
    else:
        d["receipts"] = [r for r in d["receipts"] if r["id"] != oid]
    r = client.put(path, headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    assert r.status_code == 200, r.text


def _restore(owner, cid, path, original):
    revision = doc_of(owner, cid)["meta"]["revision"]
    r = client.post(path + "/restore", headers=h(owner), json={
        "revision": original["meta"]["revision"], "base_revision": revision,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _withdrawn(kind):
    d = company()
    d["locations"].append({"id": "W", "name": "Warehouse", "type": "warehouse"})
    d["lanes"].append({"id": "WP", "origin": "W", "destination": "P", "modes": [{"transit_days": 1}]})
    d["receipts"].append({"id": "TO-1", "kind": "transfer", "location": "P", "product": "B", "qty": 20,
                          "start_date": "2026-01-07", "due_date": "2026-01-08", "source": "WP"})
    owner, cid, key = setup(d)
    path = f"/api/companies/{cid}"
    [order] = _orders(key, path, kind)
    ack = {"kind": kind, "id": order["id"], "erp_ref": "ERP-1", "version": order["version"]}
    assert _ack(key, path, ack)["items"][0]["status"] == "applied"
    original = deepcopy(doc_of(owner, cid))
    _delete(owner, cid, path, kind, order["id"])
    [gone] = _orders(key, path, kind)
    assert gone["change"] == "withdrawn"
    return owner, cid, key, path, original, ack, gone


@pytest.mark.parametrize("kind", KINDS)
def test_original_order_ack_does_not_acknowledge_its_withdrawal(kind):
    _, _, key, path, _, ack, gone = _withdrawn(kind)
    assert gone["version"] != ack["version"]
    assert _ack(key, path, ack)["items"][0]["status"] == "refused"
    assert _orders(key, path, kind) == [gone]
    assert _ack(key, path, {**ack, "version": gone["version"]})["items"][0]["status"] == "applied"
    assert _orders(key, path, kind) == []


@pytest.mark.parametrize("kind", KINDS)
def test_restoration_after_erp_closure_exports_a_new_lifecycle(kind):
    owner, cid, key, path, original, ack, gone = _withdrawn(kind)
    assert _ack(key, path, {**ack, "version": gone["version"]})["items"][0]["status"] == "applied"
    restored = _restore(owner, cid, path, original)
    assert restored["dataset"] is not None  # return the server's corrected integration state to the planner
    [new] = _orders(key, path, kind)
    assert new["id"] == ack["id"] and new["version"] != ack["version"] and new["change"] == "new"
    assert len(_orders(key, path, kind, everything=True)) == 1  # no stale withdrawal alongside the live order
    _ack(key, path, ack)  # an old live-order acknowledgement still cannot take the restored lifecycle
    assert _orders(key, path, kind)[0]["version"] == new["version"]
    assert _ack(key, path, {**ack, "version": new["version"]})["items"][0]["status"] == "applied"
    assert _orders(key, path, kind) == []
    _restore(owner, cid, path, original)  # an older snapshot cannot erase the current integration generation
    assert _orders(key, path, kind)[0]["version"] == new["version"]


@pytest.mark.parametrize("kind", KINDS)
def test_each_withdrawal_has_its_own_version_even_if_the_order_is_unchanged(kind):
    owner, cid, key, path, original, ack, first = _withdrawn(kind)
    _restore(owner, cid, path, original)  # the ERP has not closed it yet: the existing copy stays valid
    assert _orders(key, path, kind) == []
    _delete(owner, cid, path, kind, ack["id"])
    [second] = _orders(key, path, kind)
    assert second["version"] != first["version"]
    assert _ack(key, path, {**ack, "version": first["version"]})["items"][0]["status"] == "refused"
    assert _orders(key, path, kind) == [second]


def test_retry_of_a_previous_closure_message_does_not_close_a_new_withdrawal():
    owner, cid, key, path, original, ack, first = _withdrawn("production_order")
    closure = {**ack, "version": first["version"]}
    assert _ack(key, path, closure, "close-once")["status"] == "applied"
    _restore(owner, cid, path, original)
    [new] = _orders(key, path, "production_order")
    _ack(key, path, {**ack, "version": new["version"]})
    _delete(owner, cid, path, "production_order", ack["id"])
    [second] = _orders(key, path, "production_order")
    assert _ack(key, path, closure, "close-once")["status"] == "duplicate"
    assert _orders(key, path, "production_order") == [second]


def test_another_process_replacing_a_withdrawal_during_acknowledgement_is_not_consumed(monkeypatch):
    from scp.api import connect

    owner, cid, key, path, original, ack, first = _withdrawn("production_order")
    receive = connect.receive

    def interleaved(*args, **kwargs):
        # Simulate another server process's saves after this worker read the withdrawal. Its lock is separate.
        c = args[0]
        user = c.whoami(owner)
        revision = c.db.execute("SELECT revision FROM companies WHERE id = ?", (cid,)).fetchone()[0]
        c.restore(user, cid, original["meta"]["revision"], revision)
        row = c.db.execute("SELECT dataset, revision FROM companies WHERE id = ?", (cid,)).fetchone()
        doc = json.loads(row["dataset"])
        doc["receipts"] = [r for r in doc["receipts"] if r["id"] != ack["id"]]
        c.save(user, cid, doc, row["revision"])
        return receive(*args, **kwargs)

    monkeypatch.setattr(connect, "receive", interleaved)
    _ack(key, path, {**ack, "version": first["version"]})
    [second] = _orders(key, path, "production_order")
    assert second["change"] == "withdrawn" and second["version"] != first["version"]


def test_restoring_a_snapshot_before_erp_numbering_removes_the_closed_tombstone():
    owner, cid, key, path, _, ack, gone = _withdrawn("production_order")
    _ack(key, path, {**ack, "version": gone["version"]})
    revision = doc_of(owner, cid)["meta"]["revision"]
    r = client.post(path + "/restore", headers=h(owner), json={"revision": 1, "base_revision": revision})
    assert r.status_code == 200, r.text
    [new] = _orders(key, path, "production_order", everything=True)
    assert new["change"] == "new" and new["version"] != ack["version"]


def test_legacy_withdrawal_table_is_migrated_without_invalidating_its_exported_version():
    store = Store(":memory:")
    store.db.execute("CREATE TABLE erp_withdrawn (company_id TEXT, kind TEXT, id TEXT, erp_ref TEXT, location TEXT, "
                     "at TEXT, user_id TEXT, taken_at TEXT, PRIMARY KEY (company_id, kind, id))")
    store.db.execute("INSERT INTO erp_withdrawn VALUES ('C1', 'production_order', 'MO-1', 'ERP-1', 'P', '', '', NULL)")
    c = Companies(store)
    row = dict(c.db.execute("SELECT * FROM erp_withdrawn").fetchone())
    assert row["generation"] == ""
    [order] = withdrawn("production_order", [row])
    assert order.version == withdrawn_version("production_order", "MO-1", "ERP-1")


@pytest.mark.parametrize("unfinished", [[{"id": ["unfinished"], "supplier": "S"}], "unfinished"])
def test_unfinished_orders_are_preserved_during_an_unrelated_save(unfinished):
    d = company()
    d["purchase_orders"] = deepcopy(unfinished)
    owner, cid, _ = setup(d)
    c = doc_of(owner, cid)
    c["dataset"]["settings"]["company_name"] = "Renamed company"
    r = client.put(f"/api/companies/{cid}", headers=h(owner), json={
        "dataset": c["dataset"], "base_revision": c["meta"]["revision"],
    })
    assert r.status_code == 200, r.text
    assert doc_of(owner, cid)["dataset"]["purchase_orders"] == unfinished


@pytest.mark.parametrize("kind", ["subsequent_debit", "subsequent_credit"])
def test_supplier_adjustment_reference_is_checked_like_an_invoice(kind):
    x, _ = act(received(), "enter_invoice", "PO-00001", on=JAN, reference="INV-9")
    lines = [{"order": "PO-00001-10", "price": 0.1}]
    x, _ = act(x, "enter_invoice", "", on=JAN, kind=kind, reference="NOTE-1", lines=lines)
    with pytest.raises(PurchasingError, match="NOTE-1 is already entered"):
        act(x, "enter_invoice", "", on=JAN, kind=kind, reference=" note-1 ", lines=lines)
    y, _ = act(x, "enter_invoice", "", on=JAN, kind=kind, reference="NOTE-2", lines=lines)
    assert len(y.supplier_invoices) == 3  # a different note is a separate adjustment
    cancelled = x.model_copy(update={"supplier_invoices": [
        i.model_copy(update={"cancelled": True}) if i.reference == "NOTE-1" else i for i in x.supplier_invoices]})
    y, _ = act(cancelled, "enter_invoice", "", on=JAN, kind=kind, reference="NOTE-1", lines=lines)
    assert len(y.supplier_invoices) == 3  # a cancelled note can be entered again, like an invoice


@pytest.mark.parametrize("source", ["customer", "product", "company"])
def test_return_credit_keeps_the_original_effective_tax_and_gst_split(source):
    d = shop()
    d["settings"].update(company_region="MH")
    d["locations"][-1]["region"] = "Maharashtra"
    d["sales"] = {"tax_rate": 0.18, "tax_split": "gst"}
    d["customers"][0]["tax_rate"] = 0.18 if source == "customer" else None
    if source == "product":
        d["products"][0]["tax_rate"] = 0.12
    x, _ = create_order(ds(d), "K", LINES)
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")
    x, _ = create_invoices(x)
    inv = x.invoices[0]
    original = next(ln for ln in inv.lines if ln.product == "A")
    x = x.model_copy(update={
        "sales": x.sales.model_copy(update={"tax_rate": 0.05, "tax_split": "none"}),
        "customers": [c.model_copy(update={"tax_rate": 0.0}) for c in x.customers],
        "products": [p.model_copy(update={"tax_rate": 0.05}) for p in x.products],
        "locations": [loc.model_copy(update={"region": "KA"}) if loc.id == "K" else loc for loc in x.locations],
    })
    x, _ = create_return(x, "K", "A", 3, order="SO-00001/10")
    x, _ = receive_return(x, "RET-00001")
    x, _ = credit_return(x, "RET-00001")
    credit = x.invoices[-1]
    assert credit.reference == inv.id and credit.tax_split == inv.tax_split == "cgst_sgst"
    assert credit.tax == pytest.approx(credit.net * inv.rate_of(original))
    assert credit.rate_of(credit.lines[0]) == inv.rate_of(original)


@pytest.mark.parametrize("ours,theirs,our_tax,their_tax,expected", [
    ("Maharashtra", "", "27ABCDE1234F1Z5", "27FGHIJ5678K1Z6", "cgst_sgst"),
    ("", "MH", "27ABCDE1234F1Z5", "27FGHIJ5678K1Z6", "cgst_sgst"),
    ("27", "maharashtra", "", "", "cgst_sgst"),
    ("  Tamil Nadu ", "TN", "", "", "cgst_sgst"),
    ("Maharashtra", "Karnataka", "27ABCDE1234F1Z5", "27FGHIJ5678K1Z6", "igst"),
    ("", "", "27ABCDE1234F1Z5", "29FGHIJ5678K1Z6", "igst"),
    ("Île de France", "Île de France", "", "", "cgst_sgst"),
])
def test_gst_state_comparison_normalizes_names_abbreviations_and_codes(ours, theirs, our_tax, their_tax, expected):
    d = shop()
    d["settings"].update(company_region=ours, company_tax_id=our_tax)
    d["locations"][-1].update(region=theirs, tax_id=their_tax)
    d["sales"] = {"tax_split": "gst"}
    assert tax_split(ds(d), "K") == expected
