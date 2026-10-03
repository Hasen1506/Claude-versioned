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
