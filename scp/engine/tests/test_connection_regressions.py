"""PR #18 audit regressions: movement files, credentials, cancellation delivery, and integration key scope."""
from datetime import date

import pytest

from scp.actuals.roll import roll_forward
from scp.companies import get_companies
from scp.connect import imports
from scp.connect.erp import ErpAck, acknowledge, outbound, record_lists
from scp.model import Dataset
from scp.plan.mrp import run_mrp
from scp.purchasing import act, create_agreement, create_purchase_orders, requisitions

from .test_connections import client, company, doc_of, h, setup
from .test_purchasing import _ordered


def test_csv_receipt_import_accepts_the_order_column(monkeypatch, tmp_path):
    monkeypatch.setenv("SCP_IMPORT_DIR", str(tmp_path))
    owner, cid, _ = setup()
    folder = tmp_path / cid
    folder.mkdir()
    (folder / "receipt.csv").write_text(
        "Document,Action,Order,Quantity,Date\nGM-1,101,PO-00001-10,10,08.01.2026\n"
    )
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json={
        "name": "Receipts", "kind": "postings", "source_type": "folder", "source": "receipt.csv",
        "format": "csv", "every": "hour", "at": "00:15",
    })
    assert r.status_code == 200, r.text
    jid = r.json()["jobs"][0]["id"]
    r = client.post(f"/api/companies/{cid}/imports/{jid}/run", headers=h(owner))
    assert r.status_code == 200, r.text
    assert r.json()[0]["status"] == "applied", r.json()[0]["items"]
    [movement] = doc_of(owner, cid)["dataset"]["movements"]
    assert (movement["qty"], movement["reference"], movement["erp_ref"]) == (10, "PO-00001-10", "GM-1")


def test_an_acknowledged_purchase_order_exports_its_cancellation_and_takes_the_ack():
    owner, cid, key = setup()
    url = f"/api/companies/{cid}/erp/purchase-orders"
    [po] = client.get(url, headers=h(key)).json()["orders"]
    ack = {"kind": "purchase_order", "id": po["id"], "erp_ref": "4500000123", "version": po["version"]}
    r = client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={"orders": [ack]})
    assert r.json()["message"]["items"][0]["status"] == "applied", r.text
    doc = doc_of(owner, cid)
    new, report = act(Dataset.model_validate(doc["dataset"]), "cancel", "PO-00001")
    assert report.ok and not new.purchase_orders
    r = client.put(f"/api/companies/{cid}", headers=h(owner), json={
        "dataset": new.model_dump(mode="json"), "base_revision": doc["meta"]["revision"],
    })
    assert r.status_code == 200, r.text
    [cancel] = client.get(url, headers=h(key)).json()["orders"]
    assert (cancel["id"], cancel["erp_ref"], cancel["cancelled"], cancel["change"]) == (
        "PO-00001", "4500000123", True, "changed")
    [line] = cancel["lines"]
    assert (line["id"], line["qty"], line["open"], line["cancelled"]) == ("PO-00001-10", 100, 0, True)
    assert cancel["version"] != po["version"]
    r = client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={
        "orders": [{**ack, "version": cancel["version"]}],
    })
    assert r.json()["message"]["items"][0]["status"] == "applied", r.text
    assert client.get(url, headers=h(key)).json()["orders"] == []
    [taken] = client.get(url + "?all=true", headers=h(key)).json()["orders"]
    assert taken["cancelled"] and taken["change"] == "taken"
    retry = client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={
        "orders": [{**ack, "version": cancel["version"]}],
    })
    assert retry.json()["message"]["items"][0]["status"] == "unchanged"


def test_partial_cancellation_is_exported_with_the_remaining_lines():
    d = company()
    d["receipts"].append({**d["receipts"][0], "id": "PO-00001-20", "qty": 50})
    ds = Dataset.model_validate(d)
    [po] = outbound(ds, "purchase_order")
    ds, _ = acknowledge(ds, [ErpAck(kind="purchase_order", id=po.id, erp_ref="ERP-1", version=po.version)])
    ds, _ = act(ds, "cancel", po.id, lines=[{"id": "PO-00001-10"}])
    [pending] = outbound(ds, "purchase_order")
    assert pending.change == "changed" and not pending.cancelled
    assert [(ln.id, ln.cancelled, ln.open) for ln in pending.lines] == [
        ("PO-00001-10", True, 0), ("PO-00001-20", False, 50)]
    assert len(ds.purchase_orders) == 1 and len(ds.purchase_orders[0].cancelled_lines) == 1
    ds, _ = acknowledge(ds, [ErpAck(kind="purchase_order", id=po.id, erp_ref="ERP-1", version=pending.version)])
    assert not outbound(ds, "purchase_order")
    ds, _ = act(ds, "cancel", po.id)
    [last] = outbound(ds, "purchase_order")
    assert last.cancelled and last.change == "changed" and all(ln.cancelled for ln in last.lines)
    assert last.version != pending.version


def test_a_delayed_ack_after_cancellation_keeps_the_cancellation_pending_through_roll_and_reload():
    ds = Dataset.model_validate(company())
    [po] = outbound(ds, "purchase_order")
    ds, _ = act(ds, "cancel", po.id)
    ds, results = acknowledge(ds, [ErpAck(kind="purchase_order", id=po.id, erp_ref="ERP-1", version=po.version,
                                         sent_to_supplier=True)])
    assert results[0].status == "applied" and "goes to the ERP again" in results[0].message
    ds, _ = roll_forward(ds, date(2026, 1, 6))
    ds = Dataset.model_validate_json(ds.model_dump_json())
    [pending] = outbound(ds, "purchase_order")
    assert pending.cancelled and pending.change == "changed" and pending.erp_ref == "ERP-1"
    ds, _ = acknowledge(ds, [ErpAck(kind="purchase_order", id=po.id, erp_ref="ERP-1", version=pending.version)])
    assert not outbound(ds, "purchase_order")
    assert "cancelled_purchase_orders" not in record_lists()


def test_cancelling_orders_does_not_reuse_their_numbers():
    ds, pid = _ordered()
    ds, _ = act(ds, "cancel", pid)
    plan = run_mrp(ds)
    ds, made = create_purchase_orders(ds, plan, [{"id": r.id} for r in requisitions(ds, plan)])
    assert made.created and all(o.id != pid for o in made.created)
    ds, agreement = create_agreement(ds, "S", "P", "B", target_qty=100)
    sid = agreement.id
    # Give the agreement a delivery line, then cancel its last line.
    receipt = ds.receipts[0].model_copy(update={"id": f"{sid}-10", "po": sid, "product": "B"})
    ds = ds.model_copy(update={"receipts": [*ds.receipts, receipt]})
    ds, _ = act(ds, "cancel", sid)
    _, again = create_agreement(ds, "S", "P", "B", target_qty=100)
    assert again.id != sid


def test_cancelling_an_agreement_line_does_not_reuse_its_line_number():
    ds = Dataset.model_validate(company())
    ds, agreement = create_agreement(ds, "S", "P", "B", target_qty=100)
    # Keep one live line so the agreement remains active.
    lines = [ds.receipts[0].model_copy(update={"id": f"{agreement.id}-{n}", "po": agreement.id}) for n in (10, 20)]
    ds = ds.model_copy(update={"receipts": lines})
    ds, _ = act(ds, "cancel", agreement.id, lines=[{"id": lines[1].id}])
    d = ds.model_dump(mode="json")
    d["location_products"][1]["on_hand"] = 0
    d["demand"] = [{"location": "P", "product": "B", "date": "2026-01-14", "qty": 300, "kind": "sales_order"}]
    ds = Dataset.model_validate(d)
    plan = run_mrp(ds)
    ds, made = create_purchase_orders(ds, plan, [{"id": r.id} for r in requisitions(ds, plan)])
    assert made.created
    assert all(lid != lines[1].id for o in made.created for lid in o.lines)


@pytest.mark.parametrize(("new_source", "new_headers", "expected"), [
    ("https://erp.example.com/next.csv", None, {"Authorization": "Bearer TEST-ONLY"}),
    ("https://ERP.example.com:443/next.csv", None, {"Authorization": "Bearer TEST-ONLY"}),
    ("https://other.example.com/stock.csv", None, {}),
    ("http://erp.example.com/stock.csv", None, {}),
    ("https://erp.example.com:8443/stock.csv", None, {}),
    ("https://erp.example.com/stock.csv", {}, {}),
    ("https://other.example.com/stock.csv", {"Authorization": "Bearer NEW-TEST"}, {"Authorization": "Bearer NEW-TEST"}),
])
def test_import_credentials_are_retained_only_for_the_same_origin(monkeypatch, new_source, new_headers, expected):
    monkeypatch.setenv("SCP_IMPORT_HOSTS", "erp.example.com,other.example.com")
    owner, cid, _ = setup()
    body = {"name": "ERP stock", "kind": "stock", "source_type": "url",
            "source": "https://erp.example.com/stock.csv", "headers": {"Authorization": "Bearer TEST-ONLY"},
            "format": "csv", "every": "hour", "at": "00:15"}
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=body)
    assert r.status_code == 200, r.text
    jid = r.json()["jobs"][0]["id"]
    changed = {**body, "source": new_source}
    if new_headers is None:
        del changed["headers"]  # the browser omits values it was never shown
    else:
        changed["headers"] = new_headers
    r = client.put(f"/api/companies/{cid}/imports/{jid}", headers=h(owner), json=changed)
    assert r.status_code == 200, r.text
    requests = []

    def fake_fetch(url, headers):
        requests.append((url, headers))
        return b"Plant,Material,Quantity\nP,A,100\n"

    monkeypatch.setattr(imports, "fetch", fake_fetch)
    r = client.post(f"/api/companies/{cid}/imports/{jid}/run", headers=h(owner))
    assert r.status_code == 200, r.text
    assert requests == [(new_source, expected)]


def test_switching_an_import_to_a_folder_does_not_keep_its_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("SCP_IMPORT_DIR", str(tmp_path))
    owner, cid, _ = setup()
    c, user = get_companies(), get_companies().whoami(owner)
    job = imports.JobInput(name="Stock", kind="stock", source_type="url", source="https://erp.example.com/stock.csv",
                           headers={"Authorization": "Bearer TEST-ONLY"})
    saved = imports.save_job(c, user, cid, job).jobs[0]
    imports.save_job(c, user, cid, job.model_copy(update={"source_type": "folder", "source": "stock.csv"}), saved.id)
    after = imports.save_job(c, user, cid, job.model_copy(update={"headers": None}), saved.id).jobs[0]
    assert after.header_names == []


@pytest.mark.parametrize("role", ["viewer", "planner"])
def test_integration_keys_cannot_create_another_company_or_promote_themselves(role):
    owner, cid, _ = setup()
    made = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "ERP", "role": role}).json()
    key = made["token"]
    assert client.post("/api/companies", headers=h(key), json={"dataset": company()}).status_code == 403
    assert client.post(f"/api/companies/{cid}/keys", headers=h(key), json={"name": "Escape"}).status_code == 403
    other = client.post("/api/companies", headers=h(owner), json={"dataset": company()}).json()["id"]
    c, user = get_companies(), get_companies().whoami(key)
    # Even if a key's account acquired owner memberships, authorization follows the original key.
    c.db.execute("UPDATE members SET role = 'owner' WHERE user_id = ?", (user.id,))
    c.db.execute("INSERT INTO members (company_id, user_id, role, added_at, added_by) VALUES (?, ?, 'owner', ?, ?)",
                 (other, user.id, "2026-01-05", user.id))
    assert client.get(f"/api/companies/{other}", headers=h(key)).status_code == 404
    assert client.get(f"/api/companies/{other}/erp/purchase-orders", headers=h(key)).status_code == 404
    assert client.post(f"/api/companies/{cid}/keys", headers=h(key), json={"name": "Escape"}).status_code == 403
    listed = client.get("/api/companies", headers=h(key)).json()
    assert [(r["id"], r["role"]) for r in listed] == [(cid, role)]
    r = client.post(f"/api/companies/{cid}/erp/stock", headers=h(key), json={
        "stock": [{"location": "P", "product": "A", "qty": 1}],
    })
    assert r.status_code == (403 if role == "viewer" else 200)


def test_a_viewer_key_cannot_write_unscoped_plan_versions_and_a_planner_uses_its_company():
    owner, cid, planner = setup()
    viewer = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "BI", "role": "viewer"}).json()["token"]
    body = {"dataset": company(), "name": "Nightly plan"}
    assert client.post("/api/versions", headers=h(viewer), json=body).status_code == 403
    r = client.post("/api/versions", headers=h(planner), json=body)
    assert r.status_code == 200, r.text
    versions = client.get("/api/versions", headers={**h(owner), "X-Company": cid}).json()
    assert versions[0]["id"] == r.json()["id"]
    assert client.get("/api/versions").json() == []
