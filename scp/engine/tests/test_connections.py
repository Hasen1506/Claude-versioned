"""Phase Q: connected to the rest of the company. Keys for other systems, an ERP's customer orders, stock, goods
movements and master data applied to the company kept on the server, the orders it takes back with its numbers, and
the log of every message."""
from __future__ import annotations

from fastapi.testclient import TestClient

from scp.api.app import app

from .factory import base

client = TestClient(app)


def company() -> dict:
    """Plant P ships to customer K; PO-00001 for 100 B from S is released and not sent; MO-1 makes 20 A."""
    d = base()
    d["locations"].append({"id": "K", "name": "Kumar Stores", "type": "customer"})
    d["locations"][1]["name"] = "Sharma Metals"
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["products"][0].update(name="Tin of white", price=100)
    d["location_products"][0]["on_hand"] = 100
    d["purchase_orders"] = [{"id": "PO-00001", "supplier": "S", "location": "P", "order_date": "2026-01-02"}]
    d["receipts"] = [
        {"id": "PO-00001-10", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
         "due_date": "2026-01-08", "source": "PIR-B", "po": "PO-00001", "price": 10},
        {"id": "MO-1", "kind": "production", "location": "P", "product": "A", "qty": 20, "due_date": "2026-01-09",
         "start_date": "2026-01-07", "source": "PV-A"},
    ]
    return d


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def setup(doc: dict | None = None) -> tuple[str, str, str]:
    """An owner, their company, and a planner key for the ERP."""
    r = client.post("/api/auth/signup", json={"email": "owner@example.com", "name": "Asha", "password": "correct horse"})
    owner = r.json()["token"]
    cid = client.post("/api/companies", headers=h(owner), json={"dataset": doc or company()}).json()["id"]
    r = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "SAP", "role": "planner"})
    assert r.status_code == 200, r.text
    return owner, cid, r.json()["token"]


def doc_of(owner: str, cid: str) -> dict:
    return client.get(f"/api/companies/{cid}", headers=h(owner)).json()


# ---- keys -------------------------------------------------------------------------------------------------------
def test_an_owner_makes_a_key_shown_once_that_works_in_that_company_only_until_withdrawn():
    owner, cid, key = setup()
    assert key.startswith("scpk_")
    keys = client.get(f"/api/companies/{cid}/keys", headers=h(owner)).json()
    assert [(k["id"], k["name"], k["role"], k["token"]) for k in keys] == [("K0001", "SAP", "planner", None)]
    assert keys[0]["prefix"] == key[:12]
    # the key is not a person: not among the members, but it works in the company
    assert [m["email"] for m in client.get(f"/api/companies/{cid}/members", headers=h(owner)).json()] == \
        ["owner@example.com"]
    assert client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).status_code == 200
    # another company of the owner is not the key's
    other = client.post("/api/companies", headers=h(owner), json={"dataset": company()}).json()["id"]
    assert client.get(f"/api/companies/{other}/erp/purchase-orders", headers=h(key)).status_code == 404
    # a key cannot make keys; a planner cannot either
    assert client.post(f"/api/companies/{cid}/keys", headers=h(key), json={"name": "x"}).status_code == 403
    # withdrawn, it no longer signs in
    r = client.delete(f"/api/companies/{cid}/keys/K0001", headers=h(owner))
    assert r.json()[0]["revoked_at"]
    r = client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key))
    assert r.status_code == 401 and "not valid" in r.json()["detail"]
    log = client.get(f"/api/companies/{cid}/history", headers=h(owner)).json()
    assert [x["summary"] for x in log[:2]] == ["key K0001 “SAP” withdrawn", "key K0001 “SAP” made, as a planner"]


def test_a_viewer_key_reads_the_orders_but_cannot_send_data():
    owner, cid, _ = setup()
    viewer = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "BI", "role": "viewer"}).json()
    assert client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(viewer["token"])).status_code == 200
    r = client.post(f"/api/companies/{cid}/erp/stock", headers=h(viewer["token"]),
                    json={"stock": [{"location": "P", "product": "A", "qty": 1}]})
    assert r.status_code == 403


# ---- customer orders --------------------------------------------------------------------------------------------
ORDER = {"number": "4711", "customer": "K", "customer_ref": "K-PO-9",
         "lines": [{"product": "A", "qty": 10, "date": "2026-01-08", "price": 95}]}


def test_an_erp_order_is_taken_once_changed_line_by_line_and_cancelled_by_its_number():
    owner, cid, key = setup()
    url = f"/api/companies/{cid}/erp/orders"
    r = client.post(url, headers=h(key), json={"message_id": "M1", "orders": [ORDER]})
    assert r.status_code == 200, r.text
    m = r.json()["message"]
    assert m["status"] == "applied" and m["by"] == "SAP (key)" and m["summary"] == "1 orders: 1 taken"
    assert m["items"][0]["id"] == "SO-00001" and "SO-00001 taken for Kumar Stores" in m["items"][0]["message"]
    rev = r.json()["revision"]
    d = doc_of(owner, cid)["dataset"]
    assert [(o["id"], o["erp_ref"], o["customer_ref"]) for o in d["sales_orders"]] == [("SO-00001", "4711", "K-PO-9")]
    assert [(x["id"], x["qty"], x["price"]) for x in d["demand"]] == [("SO-00001/10", 10, 95)]
    # the same message again: the first answer, nothing applied twice
    r = client.post(url, headers=h(key), json={"message_id": "M1", "orders": [ORDER]})
    assert r.json()["message"]["status"] == "duplicate" and r.json()["revision"] == rev
    assert "sent before (message M1" in r.json()["message"]["summary"]
    # the same order unchanged in a new message: as here
    r = client.post(url, headers=h(key), json={"message_id": "M2", "orders": [ORDER]})
    assert r.json()["message"]["status"] == "unchanged" and r.json()["revision"] == rev
    # changed: 12 instead of 10, and a second line
    changed = {**ORDER, "lines": [{**ORDER["lines"][0], "qty": 12}, {"product": "A", "qty": 5, "date": "2026-01-09"}]}
    r = client.post(url, headers=h(key), json={"message_id": "M3", "orders": [changed]})
    assert r.json()["message"]["items"][0]["message"] == (
        "SO-00001/10 changed (quantity 10 → 12); all on the date asked. SO-00001: added: 1 line, INR 500.00 with tax. "
        "5 Tin of white on the date asked.")
    d = doc_of(owner, cid)["dataset"]
    assert [(x["id"], x["qty"]) for x in d["demand"]] == [("SO-00001/10", 12), ("SO-00001/20", 5)]
    # a line less: cancelled
    r = client.post(url, headers=h(key), json={"message_id": "M4", "orders": [{**changed, "lines": changed["lines"][:1]}]})
    assert r.json()["message"]["items"][0]["message"].startswith(
        "SO-00001/20 cancelled: 5 Tin of white for Kumar Stores no longer wanted (no longer on the ERP's order).")
    d = doc_of(owner, cid)["dataset"]
    assert [x["id"] for x in d["demand"]] == ["SO-00001/10"]
    # cancelled in the ERP
    r = client.post(url, headers=h(key), json={"message_id": "M5", "orders": [{**ORDER, "cancelled": True}]})
    assert "SO-00001 cancelled" in r.json()["message"]["items"][0]["message"]
    assert doc_of(owner, cid)["dataset"]["demand"] == []
    # each message that changed something is a revision by the key, in the company's history
    log = client.get(f"/api/companies/{cid}/history", headers=h(owner)).json()
    assert log[0]["user"] == "SAP (key)" and log[0]["summary"].startswith("orders from SAP (key) (message M5)")


def test_an_item_the_data_does_not_allow_is_refused_and_the_others_are_taken():
    owner, cid, key = setup()
    bad = {**ORDER, "number": "4712", "lines": [{"product": "NOPE", "qty": 1, "date": "2026-01-08"}]}
    r = client.post(f"/api/companies/{cid}/erp/orders", headers=h(key), json={"orders": [ORDER, bad]})
    m = r.json()["message"]
    assert m["status"] == "partly" and m["summary"] == "2 orders: 1 taken, 1 refused"
    assert m["items"][1] == {"ref": "4712", "status": "refused", "message": "line 1: there is no product 'NOPE'",
                             "id": None}
    rows = client.get(f"/api/companies/{cid}/messages", headers=h(owner)).json()
    assert [(x["kind"], x["status"]) for x in rows] == [("orders", "partly")]


# ---- stock and goods movements ----------------------------------------------------------------------------------
def test_the_erps_stock_is_posted_as_count_differences():
    owner, cid, key = setup()
    r = client.post(f"/api/companies/{cid}/erp/stock", headers=h(key), json={"message_id": "S1", "stock": [
        {"location": "P", "product": "A", "qty": 100}, {"location": "P", "product": "B", "qty": 42},
        {"location": "X", "product": "A", "qty": 1}]})
    items = r.json()["message"]["items"]
    assert [(i["ref"], i["status"]) for i in items] == [("P / A", "applied"), ("P / B", "applied"), ("X / A", "refused")]
    # nothing in the journal yet: the first stock is the opening balance
    assert [i["message"] for i in items[:2]] == ["100 on hand: +100 posted (opening balance)",
                                                "42 on hand: +42 posted (opening balance)"]
    assert [(m["type"], m["product"], m["qty"]) for m in doc_of(owner, cid)["dataset"]["movements"]] == [
        ("opening", "A", 100), ("opening", "B", 42)]
    # the same stock again changes nothing; less is a count difference
    r = client.post(f"/api/companies/{cid}/erp/stock", headers=h(key), json={"stock": [
        {"location": "P", "product": "B", "qty": 42}]})
    assert r.json()["message"]["status"] == "unchanged"
    r = client.post(f"/api/companies/{cid}/erp/stock", headers=h(key), json={"stock": [
        {"location": "P", "product": "B", "qty": 40}]})
    assert r.json()["message"]["items"][0]["message"] == "40 on hand: −2 posted (count difference)"


def test_the_erps_stock_by_batch_and_stock_type_is_counted_lot_by_lot():
    d = company()
    d["products"][1]["batches"] = True
    for lp in d["location_products"]:
        lp["on_hand"] = 0
    owner, cid, key = setup(d)
    r = client.post(f"/api/companies/{cid}/erp/stock", headers=h(key), json={"stock": [
        {"location": "P", "product": "B", "batch": "L1", "expires_on": "2026-06-30", "qty": 30},
        {"location": "P", "product": "B", "batch": "L2", "stock_type": "quality", "qty": 10},
        {"location": "P", "product": "A", "stock_type": "unrestricted", "qty": 90},
        {"location": "P", "product": "A", "stock_type": "blocked", "qty": 5},
        {"location": "P", "product": "B", "qty": 3},
        {"location": "P", "product": "A", "batch": "Z", "qty": 1}]})
    items = r.json()["message"]["items"]
    assert [(i["ref"], i["status"]) for i in items] == [
        ("P / B / L1", "applied"), ("P / B / L2 / quality", "applied"), ("P / A / unrestricted", "applied"),
        ("P / A / blocked", "applied"), ("P / B", "refused"), ("P / A / Z", "refused")]
    assert items[4]["message"] == "B is kept by batch: name the batch"
    assert items[5]["message"] == "A is not kept by batch here"
    assert items[0]["message"].startswith("30 on hand: +30 posted (count difference) (PI-")
    data = doc_of(owner, cid)["dataset"]
    assert sorted((m["product"], m["batch"] or "", m["stock_type"], m["qty"]) for m in data["movements"]) == [
        ("A", "", "blocked", 5), ("A", "", "unrestricted", 90), ("B", "L1", "unrestricted", 30),
        ("B", "L2", "quality", 10)]
    assert [(b["id"], b["expires_on"]) for b in data["batches"]] == [("L1", "2026-06-30"), ("L2", None)]
    [pi] = data["inventory_docs"]
    assert (pi["status"], pi["block"], pi["note"]) == ("posted", False, "Stock from the ERP")
    # the next day's stock no longer lists L2: it is counted as none
    r = client.post(f"/api/companies/{cid}/erp/stock", headers=h(key), json={"stock": [
        {"location": "P", "product": "B", "batch": "L1", "qty": 25}]})
    [it] = r.json()["message"]["items"]
    assert it["status"] == "applied"
    assert it["message"].endswith("; not in the ERP's stock, so counted as none: L2 (quality) 10 → 0")
    moves = doc_of(owner, cid)["dataset"]["movements"]
    assert sorted((m["batch"], m["qty"]) for m in moves[4:]) == [("L1", -5), ("L2", -10)]


def test_stock_from_a_csv_with_a_column_per_stock_type_becomes_a_row_per_stock_type():
    from scp.connect.imports import parse

    rows = parse("stock", "csv", b"Plant;Material;Batch;Unrestricted;Quality inspection;Blocked\n"
                                 b"P;B;L1;1.234,5;10;0\n")
    assert rows == [
        {"location": "P", "product": "B", "batch": "L1", "qty": 1234.5, "stock_type": "unrestricted"},
        {"location": "P", "product": "B", "batch": "L1", "qty": 10, "stock_type": "quality"},
        {"location": "P", "product": "B", "batch": "L1", "qty": 0, "stock_type": "blocked"}]


def test_a_purchase_order_goes_to_the_erp_comes_back_with_its_number_and_is_received_by_it_once():
    owner, cid, key = setup()
    r = client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).json()
    [po] = r["orders"]
    assert (po["id"], po["change"], po["supplier_name"], po["erp_ref"]) == ("PO-00001", "new", "Sharma Metals", "")
    assert [(x["id"], x["item"], x["product"], x["qty"], x["price"]) for x in po["lines"]] == [
        ("PO-00001-10", 10, "B", 100, 10)]
    r = client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={"orders": [
        {"kind": "purchase_order", "id": "PO-00001", "erp_ref": "4500000123", "version": po["version"],
         "sent_to_supplier": True}]})
    assert r.json()["message"]["items"][0]["message"] == \
        "PO-00001 is 4500000123 in the ERP. Sent to the supplier by the ERP."
    assert client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).json()["orders"] == []
    every = client.get(f"/api/companies/{cid}/erp/purchase-orders?all=true", headers=h(key)).json()["orders"]
    assert [(o["id"], o["change"], o["erp_ref"]) for o in every] == [("PO-00001", "taken", "4500000123")]
    head = doc_of(owner, cid)["dataset"]["purchase_orders"][0]
    assert head["sent_on"] == "2026-01-05" and head["erp_ref"] == "4500000123"
    # the goods arrive, posted in the ERP against its own number
    post = {"ref": "5000000001", "action": "receive", "order": "4500000123/10", "qty": 60, "date": "2026-01-08"}
    r = client.post(f"/api/companies/{cid}/erp/postings", headers=h(key), json={"postings": [post]})
    item = r.json()["message"]["items"][0]
    assert item["status"] == "applied" and "PO-00001" in item["message"], item
    moves = doc_of(owner, cid)["dataset"]["movements"]
    assert [(m["type"], m["reference"], m["qty"], m["erp_ref"]) for m in moves] == [
        ("receipt", "PO-00001-10", 60, "5000000001")]
    # the same document again is a duplicate, whatever the message id
    r = client.post(f"/api/companies/{cid}/erp/postings", headers=h(key), json={"postings": [post]})
    assert r.json()["message"]["items"][0]["status"] == "duplicate"
    assert len(doc_of(owner, cid)["dataset"]["movements"]) == 1


def test_a_production_order_changed_after_the_erp_took_it_goes_to_it_again():
    owner, cid, key = setup()
    [mo] = client.get(f"/api/companies/{cid}/erp/production-orders", headers=h(key)).json()["orders"]
    assert (mo["id"], mo["product"], mo["qty"], mo["start"], mo["due"], mo["source"]) == \
        ("MO-1", "A", 20, "2026-01-07", "2026-01-09", "PV-A")
    client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={"orders": [
        {"kind": "production_order", "id": "MO-1", "erp_ref": "1000077", "version": mo["version"]}]})
    assert client.get(f"/api/companies/{cid}/erp/production-orders", headers=h(key)).json()["orders"] == []
    # a planner moves it a day later in the browser and saves
    c = doc_of(owner, cid)
    d = c["dataset"]
    d["receipts"][1]["due_date"] = "2026-01-10"
    r = client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    assert r.status_code == 200, r.text
    [again] = client.get(f"/api/companies/{cid}/erp/production-orders", headers=h(key)).json()["orders"]
    assert (again["change"], again["erp_ref"], again["due"]) == ("changed", "1000077", "2026-01-10")
    # the ERP's receipt names the order by its own number
    r = client.post(f"/api/companies/{cid}/erp/postings", headers=h(key), json={"postings": [
        {"ref": "C-1", "action": "receive", "order": "1000077", "qty": 20, "date": "2026-01-10"}]})
    assert r.json()["message"]["items"][0]["status"] == "applied", r.text


def test_an_order_the_erp_took_and_then_deleted_here_goes_to_it_as_withdrawn_until_it_closes_its_copy():
    owner, cid, key = setup()
    [po] = client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).json()["orders"]
    [mo] = client.get(f"/api/companies/{cid}/erp/production-orders", headers=h(key)).json()["orders"]
    client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={"orders": [
        {"kind": "purchase_order", "id": "PO-00001", "erp_ref": "4500000123", "version": po["version"]},
        {"kind": "production_order", "id": "MO-1", "erp_ref": "1000077", "version": mo["version"]}]})
    # a planner deletes both outright and saves
    c = doc_of(owner, cid)
    d = c["dataset"]
    d["purchase_orders"], d["receipts"] = [], []
    r = client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    assert r.status_code == 200, r.text
    [gone] = client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).json()["orders"]
    assert (gone["id"], gone["change"], gone["erp_ref"], gone["location"], gone["lines"]) == \
        ("PO-00001", "withdrawn", "4500000123", "P", [])
    [made] = client.get(f"/api/companies/{cid}/erp/production-orders", headers=h(key)).json()["orders"]
    assert (made["id"], made["change"]) == ("MO-1", "withdrawn")
    # the wrong number is refused; the right one closes it
    r = client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={"orders": [
        {"kind": "purchase_order", "id": "PO-00001", "erp_ref": "999", "version": gone["version"]}]})
    assert r.json()["message"]["items"][0]["message"] == "PO-00001 was 4500000123 in the ERP, not 999"
    r = client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={"orders": [
        {"kind": "purchase_order", "id": "PO-00001", "erp_ref": "4500000123", "version": gone["version"]}]})
    assert r.json()["message"]["items"][0]["message"] == \
        "PO-00001 (4500000123) was deleted here: the ERP closed its copy"
    assert client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).json()["orders"] == []
    every = client.get(f"/api/companies/{cid}/erp/purchase-orders?all=true", headers=h(key)).json()["orders"]
    assert [(o["id"], o["change"]) for o in every] == [("PO-00001", "taken")]
    # the production order is put back before the ERP closed it: it is no longer withdrawn
    rev = doc_of(owner, cid)["meta"]["revision"]
    r = client.post(f"/api/companies/{cid}/restore", headers=h(owner), json={"revision": rev - 1, "base_revision": rev})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/companies/{cid}/erp/production-orders", headers=h(key)).json()["orders"] == []
    # the purchase order came back too, after the ERP had closed its copy: it goes to the ERP again as a new order
    [again] = client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).json()["orders"]
    assert (again["id"], again["change"], again["erp_ref"]) == ("PO-00001", "new", "")
    r = client.post(f"/api/companies/{cid}/erp/acknowledge", headers=h(key), json={"orders": [
        {"kind": "purchase_order", "id": "PO-00001", "erp_ref": "4500000999", "version": again["version"]}]})
    assert r.json()["message"]["items"][0]["status"] == "applied", r.text
    assert client.get(f"/api/companies/{cid}/erp/purchase-orders", headers=h(key)).json()["orders"] == []
    every = client.get(f"/api/companies/{cid}/erp/purchase-orders?all=true", headers=h(key)).json()["orders"]
    assert [(o["id"], o["change"], o["erp_ref"]) for o in every] == [("PO-00001", "taken", "4500000999")]


# ---- master data ------------------------------------------------------------------------------------------------
def test_master_data_records_are_added_or_changed_in_the_fields_sent():
    owner, cid, key = setup()
    r = client.post(f"/api/companies/{cid}/erp/records/products", headers=h(key), json={"records": [
        {"id": "A", "price": 110}, {"id": "E", "type": "FG", "name": "Tin of blue"}, {"id": "F", "type": "nonsense"}]})
    items = r.json()["message"]["items"]
    assert [(i["ref"], i["status"], i["message"]) for i in items[:2]] == [
        ("A", "applied", "changed: price"), ("E", "applied", "added")]
    assert items[2]["status"] == "refused" and items[2]["message"].startswith("type:")
    prods = {p["id"]: p for p in doc_of(owner, cid)["dataset"]["products"]}
    assert prods["A"]["price"] == 110 and prods["A"]["name"] == "Tin of white" and prods["E"]["name"] == "Tin of blue"
    assert client.post(f"/api/companies/{cid}/erp/records/movements", headers=h(key),
                       json={"records": []}).status_code == 404


# ---- living beside planners -------------------------------------------------------------------------------------
def test_a_planners_save_made_before_the_erps_message_merges_with_it():
    owner, cid, key = setup()
    c = doc_of(owner, cid)
    client.post(f"/api/companies/{cid}/erp/orders", headers=h(key), json={"orders": [ORDER]})
    mine = c["dataset"]
    mine["products"][1]["name"] = "Base white"
    r = client.post(f"/api/companies/{cid}/merge", headers=h(owner),
                    json={"dataset": mine, "base_revision": c["meta"]["revision"], "clean_only": True})
    assert r.status_code == 200, r.text
    d = doc_of(owner, cid)["dataset"]
    assert d["products"][1]["name"] == "Base white" and d["sales_orders"][0]["erp_ref"] == "4711"


def test_records_set_aside_as_unfinished_stay_when_a_message_changes_the_company():
    d = company()
    d["lanes"].append({"id": "HALF", "origin": "P", "destination": "K", "modes": []})   # unfinished: set aside
    owner, cid, key = setup(d)
    r = client.post(f"/api/companies/{cid}/erp/orders", headers=h(key), json={"orders": [ORDER]})
    assert r.json()["message"]["status"] == "applied", r.text
    assert [ln["id"] for ln in doc_of(owner, cid)["dataset"]["lanes"]] == ["PK", "HALF"]


# ---- scheduled imports ------------------------------------------------------------------------------------------
STOCK_CSV = b"Plant;Material;Unrestricted\nP;A;100\nP;B;1.234,5\nP;NOPE;3\n"


def test_a_scheduled_import_reads_a_web_address_on_its_schedule_and_never_applies_the_same_file_twice(monkeypatch):
    import datetime as dt

    from scp.companies import get_companies
    from scp.connect import imports

    owner, cid, _ = setup()
    served: list[tuple[str, dict]] = []

    def fake(url, headers):
        served.append((url, headers))
        return STOCK_CSV
    monkeypatch.setattr(imports, "fetch", fake)
    job = {"name": "Nightly stock", "kind": "stock", "source_type": "url", "source": "https://erp.example.com/stock.csv",
           "headers": {"Authorization": "Basic abc"}, "every": "day", "at": "06:00"}
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=job)
    assert r.status_code == 200, r.text
    [j] = r.json()["jobs"]
    assert (j["id"], j["header_names"], j["run_as"], r.json()["timezone"]) == ("J0001", ["Authorization"], "Asha", "UTC")
    c = get_companies()
    nxt = dt.datetime.fromisoformat(j["next_run"])
    assert (nxt.hour, nxt.minute) == (6, 0)
    assert imports.run_due(c, nxt - dt.timedelta(minutes=1)) == {}
    ran = imports.run_due(c, nxt)
    [row] = ran["J0001"]
    assert served == [("https://erp.example.com/stock.csv", {"Authorization": "Basic abc"})]
    assert row.status == "partly" and row.by == "Asha" and row.source.startswith("J0001 Nightly stock: https://")
    assert [(i.ref, i.status) for i in row.items] == [("P / A", "applied"), ("P / B", "applied"), ("P / NOPE", "refused")]
    assert row.items[1].message == "1,234.5 on hand: +1,234.5 posted (opening balance)"
    # the next day the same file is not applied again
    [again] = imports.run_due(c, nxt + dt.timedelta(days=1))["J0001"]
    assert again.status == "duplicate"
    jobs = client.get(f"/api/companies/{cid}/imports", headers=h(owner)).json()["jobs"]
    assert jobs[0]["last_status"] == "duplicate" and jobs[0]["next_run"] > j["next_run"]
    # only an owner makes imports; a web address into another network can be refused
    planner = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "Robot"}).json()["token"]
    assert client.post(f"/api/companies/{cid}/imports", headers=h(planner), json=job).status_code == 403
    monkeypatch.setenv("SCP_IMPORT_HOSTS", "erp.example.com")
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json={**job, "source": "http://10.0.0.1/x.csv"})
    assert r.status_code == 422 and "only from erp.example.com" in r.json()["detail"]


def test_a_folder_import_reads_each_file_in_order_and_moves_it_aside(monkeypatch, tmp_path):
    from scp.companies import get_companies
    from scp.connect import imports

    monkeypatch.setenv("SCP_IMPORT_DIR", str(tmp_path))
    owner, cid, _ = setup()
    folder = tmp_path / cid
    folder.mkdir()
    (folder / "orders-1.csv").write_text(
        "Order,Customer,Material,Quantity,Delivery date,Price\n4711,K,A,10,08.01.2026,95\n4711,K,A,5,09.01.2026,\n")
    (folder / "orders-2.csv").write_text("Order,Customer,Material,Quantity,Delivery date\n4800,K,A,abc,08.01.2026\n")
    (folder / "other.txt").write_text("not mine")
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json={
        "name": "Orders from SAP", "kind": "orders", "source_type": "folder", "source": "orders-*.csv", "every": "hour",
        "at": "00:15"})
    assert r.json()["folder"] == str(folder)
    rows = client.post(f"/api/companies/{cid}/imports/J0001/run", headers=h(owner)).json()
    assert [(x["status"], x["summary"]) for x in rows] == [("applied", "1 orders: 1 taken"),
                                                          ("refused", "1 orders: 1 refused")]
    assert rows[1]["items"][0]["message"].startswith("lines.0.qty:")
    d = doc_of(owner, cid)["dataset"]
    assert [(x["id"], x["qty"], x["date"], x["price"]) for x in d["demand"]] == [
        ("SO-00001/10", 10, "2026-01-08", 95), ("SO-00001/20", 5, "2026-01-09", 100)]
    assert sorted(p.name for p in (folder / "done").iterdir()) == ["orders-1.csv", "orders-2.csv"]
    assert [p.name for p in folder.iterdir() if p.is_file()] == ["other.txt"]
    # nothing left to read
    assert imports.run_job(get_companies(), "J0001") == []
    assert client.get(f"/api/companies/{cid}/imports", headers=h(owner)).json()["jobs"][0]["last_summary"] == \
        "no file to read"


def test_master_data_from_a_csv_names_fields_by_the_header():
    from scp.connect.imports import parse

    rows = parse("records:location_products", "csv",
                 b"location,product,lot_sizing.policy,lot_sizing.fixed_qty,safety_stock\nP,A,FIXED,50,5\n")
    assert rows == [{"location": "P", "product": "A", "lot_sizing": {"policy": "FIXED", "fixed_qty": "50"},
                     "safety_stock": "5"}]


# ---- e-mail ------------------------------------------------------------------------------------------------------
def mailing(monkeypatch) -> list:
    """The server has a mail server; what it would send is kept here instead."""
    from scp.companies import mail
    sent: list = []
    monkeypatch.setenv("SCP_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SCP_SMTP_FROM", "plan@example.com")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example.com")
    monkeypatch.setattr(mail, "deliver", sent.append)
    return sent


def with_contacts() -> dict:
    d = company()
    d["vendors"] = [{"supplier": "S", "email": "orders@sharma.example; accounts@sharma.example"}]
    d["customers"] = [{"customer": "K", "email": "buying@kumar.example"}]
    d["settings"]["company_name"] = "Mehta Paints"
    return d


def po_mail(**kw) -> dict:
    return {"kind": "purchase_order", "ref": "PO-00001", "to": ["orders@sharma.example"],
            "subject": "Purchase order PO-00001", "text": "Please find our order attached.",
            "html": "<h1>Purchase order PO-00001</h1>", **kw}


def test_a_document_goes_from_the_server_to_the_suppliers_address_with_the_document_attached(monkeypatch):
    owner, cid, key = setup(with_contacts())
    # no mail server: the browser opens the planner's own mail program instead
    monkeypatch.delenv("SCP_SMTP_HOST", raising=False)
    r = client.post(f"/api/companies/{cid}/mail", headers=h(owner), json=po_mail())
    assert r.status_code == 409 and "sends no mail" in r.json()["detail"]
    assert client.get(f"/api/companies/{cid}/mail", headers=h(owner)).json()["mail"] is False

    sent = mailing(monkeypatch)
    setup_ = client.get(f"/api/companies/{cid}/mail", headers=h(owner)).json()
    assert (setup_["mail"], setup_["sender"], setup_["timezone"]) == (True, "plan@example.com", "UTC")
    r = client.post(f"/api/companies/{cid}/mail", headers=h(owner), json=po_mail(cc=["buying@kumar.example"]))
    assert r.status_code == 200, r.text
    row = r.json()
    assert (row["status"], row["by"], row["to"], row["cc"], row["attachment"]) == \
        ("sent", "Asha", ["orders@sharma.example"], ["buying@kumar.example"], "PO-00001.pdf, PO-00001.html")
    [msg] = sent
    assert (msg["From"], msg["To"], msg["Cc"], msg["Reply-To"], msg["Subject"]) == \
        ("plan@example.com", "orders@sharma.example", "buying@kumar.example", "Asha <owner@example.com>",
         "Purchase order PO-00001")
    assert msg.get_body(("plain",)).get_content().strip() == "Please find our order attached."
    pdf, att = list(msg.iter_attachments())
    assert (att.get_filename(), att.get_content()) == ("PO-00001.html", "<h1>Purchase order PO-00001</h1>")
    # the same document as a PDF first (N140)
    assert (pdf.get_filename(), pdf.get_content_type()) == ("PO-00001.pdf", "application/pdf")
    assert pdf.get_content().startswith(b"%PDF-1.4")

    # only addresses the company knows: a stranger is refused and nothing is sent
    r = client.post(f"/api/companies/{cid}/mail", headers=h(owner), json=po_mail(to=["someone@elsewhere.example"]))
    assert r.status_code == 422
    assert r.json()["detail"].startswith("someone@elsewhere.example is not an address of this company's suppliers")
    # a key sends data, not mail
    r = client.post(f"/api/companies/{cid}/mail", headers=h(key), json=po_mail())
    assert r.status_code == 403 and "a key sends data" in r.json()["detail"]
    assert len(sent) == 1

    # a mail server that refuses: kept in the outbox as failed, with why
    from scp.companies import mail

    def refuse(_msg):
        raise OSError("connection refused")
    monkeypatch.setattr(mail, "deliver", refuse)
    r = client.post(f"/api/companies/{cid}/mail", headers=h(owner),
                    json=po_mail(kind="delivery_schedule", ref="SA-1", to=["accounts@sharma.example"]))
    assert (r.json()["status"], r.json()["error"]) == ("failed", "connection refused")
    out = client.get(f"/api/companies/{cid}/mail/sent", headers=h(owner)).json()
    assert [(m["ref"], m["status"]) for m in out] == [("SA-1", "failed"), ("PO-00001", "sent")]
    assert [m["ref"] for m in client.get(f"/api/companies/{cid}/mail/sent?ref=PO-00001", headers=h(owner)).json()] \
        == ["PO-00001"]


def test_worklist_reminders_reach_each_owner_once_on_the_days_set(monkeypatch):
    import datetime as dt

    from scp.companies import get_companies
    from scp.connect import outbox
    from scp.tower import get_tracker

    sent = mailing(monkeypatch)
    owner, cid, _ = setup(with_contacts())
    ravi = client.post("/api/auth/signup", json={"email": "ravi@example.com", "name": "Ravi",
                                                 "password": "correct horse"}).json()["token"]
    assert client.post(f"/api/companies/{cid}/members", headers=h(owner),
                       json={"email": "ravi@example.com", "role": "planner"}).status_code == 200
    db = get_tracker().db
    rows = [  # owner, category, message, first seen (the company plans from Monday 5 January 2026)
        ("owner@example.com", "coverage", "B at P runs out on 7 Jan", "2025-12-29"),
        ("Ravi", "orders", "PO-00001 not confirmed", "2026-01-04"),
        ("ravi", "capacity", "Line 1 overloaded in week 2", "2025-12-26"),
        ("Unassigned", "demand", "Forecast for A runs high", "2026-01-01"),
    ]
    for i, (who, cat, text, first) in enumerate(rows):
        db.execute("INSERT INTO tower_items (id, company, key, code, category, severity, message, owner, owner_source, "
                   "status, first_seen, last_seen) VALUES (?, ?, ?, 'X', ?, 'high', ?, ?, 'manual', ?, ?, ?)",
                   (f"r{cid}{i}", f"@{cid}", f"k{i}", cat, text, who, "acknowledged" if i == 1 else "open", first,
                    "2026-01-05"))
    db.execute("INSERT INTO tower_items (id, company, key, code, category, severity, message, owner, owner_source, "
               "status, first_seen, last_seen) VALUES (?, ?, 'done', 'X', 'orders', 'low', 'done already', 'Ravi', "
               "'manual', 'resolved', '2026-01-01', '2026-01-05')", (f"r{cid}x", f"@{cid}"))

    c = get_companies()
    asha = c.whoami(owner)
    # only an owner sets them; a planner may not
    r = client.put(f"/api/companies/{cid}/mail/reminders", headers=h(ravi), json={"on": True})
    assert r.status_code == 403
    friday = dt.datetime(2026, 1, 9, 12, 0, tzinfo=dt.UTC)
    s = outbox.set_reminders(c, asha, cid, outbox.ReminderSettings(on=True, at="07:30", weekdays=[0, 2, 2]), friday)
    assert (s.reminders.weekdays, s.next_reminder) == ([0, 2], "2026-01-12T07:30:00+00:00")   # Monday
    assert client.get(f"/api/companies/{cid}/history", headers=h(owner)).json()[0]["summary"] == \
        "worklist reminders on: Mon, Wed at 07:30"

    assert outbox.remind_due(c, dt.datetime(2026, 1, 12, 7, 29, tzinfo=dt.UTC)) == {}
    done = outbox.remind_due(c, dt.datetime(2026, 1, 12, 7, 31, tzinfo=dt.UTC))
    assert [m.to for m in done[cid]] == [["owner@example.com"], ["ravi@example.com"]]
    asha_mail, ravi_mail = sent
    assert asha_mail["Subject"] == "Worklist: 1 open, 1 past their time · Mehta Paints"
    assert ravi_mail["Subject"] == "Worklist: 2 open, 1 past their time · Mehta Paints"
    assert ravi_mail["To"] == "ravi@example.com"
    assert ravi_mail.get_content().splitlines()[2:6] == [
        "You own 2 open exceptions on the worklist of Mehta Paints, 1 past its time:",
        "",
        "- Line 1 overloaded in week 2 (capacity, open 10 days, 5 past its time)",
        "- PO-00001 not confirmed (orders, open 1 day)",
    ]
    assert "Open the worklist: https://plan.example.com/#/tower" in ravi_mail.get_content()
    assert "Unassigned" not in asha_mail.get_content() + ravi_mail.get_content()
    after = outbox.setup(c, asha, cid)
    assert (after.last_reminder, after.next_reminder) == ("2026-01-12T07:31:00+00:00", "2026-01-14T07:30:00+00:00")
    assert outbox.remind_due(c, dt.datetime(2026, 1, 12, 8, 0, tzinfo=dt.UTC)) == {}             # once a day
    assert [m["by"] for m in client.get(f"/api/companies/{cid}/mail/sent", headers=h(owner)).json()] == \
        ["the server", "the server"]
    # switched off: no more
    s = outbox.set_reminders(c, asha, cid, outbox.ReminderSettings(on=False), friday)
    assert s.next_reminder is None
    assert outbox.remind_due(c, dt.datetime(2026, 1, 14, 8, 0, tzinfo=dt.UTC)) == {}


def test_an_import_does_not_reach_into_the_servers_own_network(monkeypatch):
    import pytest

    from scp.connect.imports import reachable
    monkeypatch.delenv("SCP_IMPORT_HOSTS", raising=False)
    for url in ("http://127.0.0.1:8000/x.csv", "http://localhost/x.csv", "http://169.254.169.254/latest/meta-data",
                "http://10.0.0.5/export.csv", "http://[::1]/x.csv"):
        with pytest.raises(ValueError, match="inside the server's own network"):
            reachable(url)
    with pytest.raises(ValueError, match="not a web address"):
        reachable("file:///etc/passwd")
    # the administrator allows a host by name: then only it, wherever it is
    monkeypatch.setenv("SCP_IMPORT_HOSTS", "localhost")
    reachable("http://localhost/x.csv")
    with pytest.raises(ValueError, match="reads files only from localhost, not erp.example.com"):
        reachable("https://erp.example.com/x.csv")
