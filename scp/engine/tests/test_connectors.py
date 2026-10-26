"""ENTERPRISE_PLAN 3.1: the connector framework on top of the keys and imports. Another system's records are mapped
field by field onto the fields here (codes translated, quantities converted, dates as it writes them), tried on a dry
run before anything is saved, read page by page from a web API with only what changed since the last good run, and
kept in the message log with the start of what was read."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scp.companies import get_companies
from scp.connect import imports

from .test_connections import client, doc_of, h, setup

SHOP = {"orders": [
    {"name": "#1001", "created_at": "2026-01-03T10:00:00Z", "customer": {"code": "C-77"},
     "note_attributes": {"deliver_by": "08 Jan 2026"},
     "line_items": [{"sku": "TIN-W", "quantity": 2}, {"sku": "TIN-W", "quantity": 1, "price": "90.00"}]},
    {"name": "#1002", "created_at": "2026-01-03T11:00:00Z", "customer": {"code": "C-99"},
     "note_attributes": {"deliver_by": "09 Jan 2026"}, "line_items": [{"sku": "TIN-W", "quantity": 1}]},
]}
ORDERS_MAP = {
    "items": "orders", "each": "line_items",
    "fields": {
        "number": {"source": "name"},
        "customer": {"source": "customer.code", "values": {"C-77": "K"}},
        "order_date": {"source": "created_at"},
        "date": {"source": "note_attributes.deliver_by", "date_format": "%d %b %Y"},
        "product": {"source": "line.sku", "values": {"TIN-W": "A"}},
        "qty": {"source": "line.quantity", "factor": 5},
        "price": {"source": "line.price"},
    },
}


def job(**kw) -> dict:
    return {"name": "Web shop orders", "kind": "orders", "source_type": "url", "format": "json",
            "source": "https://shop.example.com/orders.json", "every": "hour", "at": "00:10", "mapping": ORDERS_MAP,
            **kw}


def serve(monkeypatch, pages: dict[str, object]) -> list[tuple[str, dict]]:
    asked: list[tuple[str, dict]] = []

    def fake(url, headers):
        asked.append((url, headers))
        page = pages[url]
        return page if isinstance(page, bytes) else json.dumps(page).encode()
    monkeypatch.setattr(imports, "fetch", fake)
    return asked


# ---- mapping and the dry run -------------------------------------------------------------------------------------
def test_a_web_shops_orders_are_mapped_line_by_line_tried_first_and_then_taken(monkeypatch):
    """Input: the shop's JSON (an order per object, its lines inside, its own customer and product codes, dates as
    it writes them). Processing: the mapping fills each field here; the dry run checks every order. Output: what
    would be taken and refused, nothing saved until the import runs."""
    owner, cid, _ = setup()
    serve(monkeypatch, {"https://shop.example.com/orders.json": SHOP})
    before = doc_of(owner, cid)["meta"]["revision"]
    r = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={"job": job()})
    assert r.status_code == 200, r.text
    t = r.json()
    [m] = t["messages"]
    assert m["dry_run"] and m["seq"] == 0 and m["status"] == "partly"
    assert m["summary"] == "Dry run, nothing saved: 2 orders: 1 taken, 1 refused"
    assert [(i["ref"], i["status"]) for i in m["items"]] == [("#1001", "applied"), ("#1002", "refused")]
    assert "C-99" in m["items"][1]["message"]           # a customer code the mapping does not translate
    # what the shop's records have, and the first rows as the fields here
    assert {"name", "customer.code", "note_attributes.deliver_by", "line.sku", "line.quantity",
            "line.price"} <= set(t["columns"])
    assert t["rows"][0] == {"number": "#1001", "customer": "K", "order_date": "2026-01-03", "lines": [
        {"product": "A", "qty": 10, "date": "2026-01-08"}, {"product": "A", "qty": 5, "date": "2026-01-08",
                                                             "price": 90}]}
    # nothing saved and nothing logged
    assert doc_of(owner, cid)["meta"]["revision"] == before
    assert client.get(f"/api/companies/{cid}/messages", headers=h(owner)).json() == []
    # saved and run: the same answer, taken
    jid = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=job()).json()["jobs"][0]["id"]
    [row] = client.post(f"/api/companies/{cid}/imports/{jid}/run", headers=h(owner)).json()
    assert (row["status"], row["dry_run"]) == ("partly", False)
    d = doc_of(owner, cid)["dataset"]
    assert [(o["erp_ref"], o["customer"]) for o in d["sales_orders"]] == [("#1001", "K")]
    assert [(x["qty"], x["date"], x["price"]) for x in d["demand"]] == [(10, "2026-01-08", 100), (5, "2026-01-08", 90)]
    # the log keeps the start of what was read
    [logged] = client.get(f"/api/companies/{cid}/messages", headers=h(owner)).json()
    assert logged["sample"].startswith('{"orders": [{"name": "#1001"')


def test_a_tally_style_stock_sheet_is_mapped_by_its_own_column_names():
    """Godown names and stock in dozens: the godown is translated to the place, the quantity multiplied by 12, a
    column nobody named is left out."""
    owner, cid, _ = setup()
    sheet = ("Item Code,Godown,Closing Qty (doz),Remarks\nTIN-W,Main Godown,8,ok\nTIN-B,Main Godown,2.5,\n"
             "TIN-W,Shop,1,\n")
    mapping = {"fields": {"product": {"source": "Item Code", "values": {"TIN-W": "A", "TIN-B": "B"}},
                          "location": {"source": "godown", "values": {"Main Godown": "P", "*": "?"}},
                          "qty": {"source": "Closing Qty (doz)", "factor": 12}}}
    body = {"job": {"name": "Tally stock", "kind": "stock", "source_type": "url",
                    "source": "https://tally.example.com/stock.csv", "mapping": mapping}, "content": sheet}
    t = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json=body).json()
    assert t["rows"] == [{"product": "A", "location": "P", "qty": 96}, {"product": "B", "location": "P", "qty": 30},
                         {"product": "A", "location": "?", "qty": 12}]
    [m] = t["messages"]
    assert [(i["ref"], i["status"]) for i in m["items"]] == [("P / A", "applied"), ("P / B", "applied"),
                                                             ("? / A", "refused")]
    assert m["items"][0]["message"] == "96 on hand: +96 posted (opening balance)"
    assert m["source"] == "new Tally stock: the sample"
    assert doc_of(owner, cid)["dataset"].get("movements", []) == []


def test_master_data_fields_within_fields_are_mapped_by_a_dotted_name():
    owner, cid, _ = setup()
    mapping = {"fields": {"location": {"value": "P"}, "product": {"source": "sku", "values": {"TIN-W": "A"}},
                          "lot_sizing.policy": {"source": "rule", "values": {"fixed": "FIXED"}},
                          "lot_sizing.fixed_qty": {"source": "lot"}}}
    body = {"job": {"name": "Rules", "kind": "records:location_products", "source_type": "url",
                    "source": "https://erp.example.com/rules.csv", "mapping": mapping},
            "content": "sku,rule,lot\nTIN-W,fixed,50\n"}
    t = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json=body).json()
    assert t["rows"] == [{"location": "P", "product": "A", "lot_sizing": {"policy": "FIXED", "fixed_qty": "50"}}]
    assert t["messages"][0]["items"][0]["status"] == "applied"


def test_a_mapping_that_names_a_field_not_here_is_refused_with_the_fields_there_are():
    owner, cid, _ = setup()
    url = f"/api/companies/{cid}/imports"
    bad = job(mapping={"fields": {"colour": {"source": "x"}}})
    r = client.post(url, headers=h(owner), json=bad)
    assert r.status_code == 422 and r.json()["detail"].startswith("'colour' is not a field of orders: it is one of "
                                                                  "number, customer")
    r = client.post(url, headers=h(owner), json=job(mapping={"fields": {"date": {"source": "d", "date_format": "%Q"}}}))
    assert r.status_code == 422 and "date format" in r.json()["detail"]
    r = client.post(url, headers=h(owner), json=job(paging={"mode": "next", "next": "links.next"}))
    assert r.status_code == 422 and "web API" in r.json()["detail"]
    r = client.post(url, headers=h(owner), json=job(source_type="api", format="csv"))
    assert r.status_code == 422 and "JSON" in r.json()["detail"]
    fields = client.get(url, headers=h(owner)).json()["fields"]
    assert fields["stock"][:3] == ["location", "product", "qty"] and "lot_sizing" in fields["records:location_products"]


# ---- a web API page by page --------------------------------------------------------------------------------------
def page(n: int, items: list, nxt: str | None) -> dict:
    return {"data": {"items": items}, "links": {"next": nxt}, "page": n}


STOCK_MAP = {"items": "data.items", "fields": {"location": {"value": "P"}, "product": {"source": "sku"},
                                              "qty": {"source": "on_hand"}}}


def api_job(**kw) -> dict:
    return {"name": "Warehouse stock", "kind": "stock", "source_type": "api", "format": "json",
            "source": "https://wms.example.com/api/stock?changed_after={since}", "every": "day", "at": "05:00",
            "headers": {"Authorization": "Bearer TEST-ONLY"}, "mapping": STOCK_MAP,
            "paging": {"mode": "next", "next": "links.next"}, **kw}


def test_a_web_api_is_read_page_by_page_with_only_what_changed_since_the_last_good_run(monkeypatch):
    """Input: a warehouse system's API, two pages, the second named by the first; then a day later. Processing: the
    pages are joined, its key goes only to its own host, ``{since}`` is the start of the last good run. Output: one
    message for both pages; the next run asks only for what changed."""
    owner, cid, _ = setup()
    first = "https://wms.example.com/api/stock?changed_after=1970-01-01T00%3A00%3A00%2B00%3A00"
    asked = serve(monkeypatch, {
        first: page(1, [{"sku": "A", "on_hand": 40}], "/api/stock?cursor=2"),
        "https://wms.example.com/api/stock?cursor=2": page(2, [{"sku": "B", "on_hand": 7}], None)})
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=api_job())
    assert r.status_code == 200, r.text
    j = r.json()["jobs"][0]
    assert (j["since"], j["paging"]["next"], j["mapping"]["items"]) == (None, "links.next", "data.items")
    c = get_companies()
    at = dt.datetime.fromisoformat(j["next_run"])
    [row] = imports.run_due(c, at)[j["id"]]
    assert row.status == "applied" and [i.ref for i in row.items] == ["P / A", "P / B"]
    assert asked == [(first, {"Authorization": "Bearer TEST-ONLY"}),
                     ("https://wms.example.com/api/stock?cursor=2", {"Authorization": "Bearer TEST-ONLY"})]
    j = client.get(f"/api/companies/{cid}/imports", headers=h(owner)).json()["jobs"][0]
    assert j["since"] == at.isoformat()
    # the next day: only what changed since the last good run
    nxt = "https://wms.example.com/api/stock?changed_after=" + at.isoformat().replace(":", "%3A").replace("+", "%2B")
    asked = serve(monkeypatch, {nxt: page(1, [{"sku": "A", "on_hand": 38}], None)})
    [row] = imports.run_due(c, dt.datetime.fromisoformat(j["next_run"]))[j["id"]]
    assert [u for u, _ in asked] == [nxt] and row.items[0].message == "38 on hand: −2 posted (count difference)"


def test_a_next_page_on_another_host_gets_no_key_and_a_failed_run_keeps_the_last_good_time(monkeypatch):
    owner, cid, _ = setup()
    first = "https://wms.example.com/api/stock?changed_after=1970-01-01T00%3A00%3A00%2B00%3A00"
    asked = serve(monkeypatch, {first: page(1, [{"sku": "A", "on_hand": 40}], "https://cdn.example.net/p2"),
                                "https://cdn.example.net/p2": b"<html>gateway timeout</html>"})
    jid = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=api_job()).json()["jobs"][0]["id"]
    [row] = client.post(f"/api/companies/{cid}/imports/{jid}/run", headers=h(owner)).json()
    assert asked[1] == ("https://cdn.example.net/p2", {})
    assert row["status"] == "failed" and row["summary"].startswith("could not read https://wms.example.com")
    j = client.get(f"/api/companies/{cid}/imports", headers=h(owner)).json()["jobs"][0]
    assert j["since"] is None and j["last_status"] == "failed"
    assert doc_of(owner, cid)["dataset"].get("movements", []) == []        # half an answer is never taken


@pytest.mark.parametrize(("flag", "pages_read"), [("more", 2), ("", 3)])
def test_numbered_pages_are_read_until_the_answer_says_there_are_no_more(monkeypatch, flag, pages_read):
    """``page`` mode: page=1, 2, … until a flag in the answer says no more (or, without one, a page is empty)."""
    owner, cid, _ = setup()
    base = "https://inv.example.com/api/items?org=7"
    pages = {f"{base}&page=1": {"items": [{"sku": "A", "on_hand": 4}], "more": True},
             f"{base}&page=2": {"items": [{"sku": "B", "on_hand": 5}], "more": False},
             f"{base}&page=3": {"items": [], "more": False}}
    asked = serve(monkeypatch, {base: pages[f"{base}&page=1"], **pages})
    m = {**STOCK_MAP, "items": "items"}
    body = api_job(source=base, mapping=m, paging={"mode": "page", "param": "page", "next": flag}, headers={})
    t = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={"job": body}).json()
    assert len(asked) == pages_read and asked[1][0] == f"{base}&page=2"
    assert [i["ref"] for i in t["messages"][0]["items"]] == ["P / A", "P / B"]


def test_more_pages_than_the_import_allows_fail_rather_than_take_a_part(monkeypatch):
    owner, cid, _ = setup()
    base = "https://inv.example.com/api/items"
    serve(monkeypatch, {base: {"items": [{"sku": "A", "on_hand": 1}]},
                        **{f"{base}?page={n}": {"items": [{"sku": "A", "on_hand": n}]} for n in range(2, 6)}})
    body = api_job(source=base, mapping={**STOCK_MAP, "items": "items"},
                   paging={"mode": "page", "param": "page", "max_pages": 3}, headers={})
    [m] = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={"job": body}).json()["messages"]
    assert m["status"] == "failed" and "more than 3 pages" in m["summary"]


# ---- dry runs of saved imports -----------------------------------------------------------------------------------
def test_a_dry_run_of_a_folder_import_moves_no_file_and_leaves_its_schedule(monkeypatch, tmp_path):
    monkeypatch.setenv("SCP_IMPORT_DIR", str(tmp_path))
    owner, cid, _ = setup()
    folder = tmp_path / cid
    folder.mkdir()
    (folder / "stock-1.csv").write_text("Plant,Material,Quantity\nP,A,70\n")
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json={
        "name": "Stock", "kind": "stock", "source_type": "folder", "source": "stock-*.csv", "every": "day"})
    j = r.json()["jobs"][0]
    t = client.post(f"/api/companies/{cid}/imports/{j['id']}/dry-run", headers=h(owner)).json()
    assert t["messages"][0]["summary"] == "Dry run, nothing saved: 1 stock: 1 taken"
    assert t["columns"] == ["Plant", "Material", "Quantity"] and t["rows"] == [{"location": "P", "product": "A",
                                                                                "qty": 70}]
    assert (folder / "stock-1.csv").exists() and not (folder / "done").exists()
    after = client.get(f"/api/companies/{cid}/imports", headers=h(owner)).json()["jobs"][0]
    assert (after["last_run"], after["next_run"]) == (None, j["next_run"])
    assert doc_of(owner, cid)["dataset"].get("movements", []) == []
    # a planner may not try imports: they read from outside with an owner's rights
    planner = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "Robot"}).json()["token"]
    assert client.post(f"/api/companies/{cid}/imports/{j['id']}/dry-run", headers=h(planner)).status_code == 403
    assert client.post(f"/api/companies/{cid}/imports/try", headers=h(planner),
                       json={"job": job(), "content": "{}"}).status_code == 403


def test_trying_a_change_to_a_saved_import_uses_its_saved_key_for_the_same_host(monkeypatch):
    owner, cid, _ = setup()
    asked = serve(monkeypatch, {"https://shop.example.com/orders.json": SHOP,
                                "https://other.example.com/orders.json": SHOP})
    jid = client.post(f"/api/companies/{cid}/imports", headers=h(owner),
                      json=job(headers={"X-Shop-Token": "TEST-ONLY"})).json()["jobs"][0]["id"]
    same = {k: v for k, v in job().items() if k != "headers"}
    client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={"job": same, "id": jid})
    client.post(f"/api/companies/{cid}/imports/try", headers=h(owner),
                json={"job": {**same, "source": "https://other.example.com/orders.json"}, "id": jid})
    assert asked == [("https://shop.example.com/orders.json", {"X-Shop-Token": "TEST-ONLY"}),
                     ("https://other.example.com/orders.json", {})]


def test_a_refused_file_is_in_the_log_with_what_was_read(monkeypatch):
    owner, cid, _ = setup()
    serve(monkeypatch, {"https://shop.example.com/orders.json": b'{"orders": "not a list"}'})
    jid = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=job()).json()["jobs"][0]["id"]
    [row] = client.post(f"/api/companies/{cid}/imports/{jid}/run", headers=h(owner)).json()
    assert row["status"] == "failed" and "no list of records at 'orders'" in row["summary"]
    assert row["sample"] == '{"orders": "not a list"}'
    assert imports.run_job(get_companies(), jid)[0].sample == '{"orders": "not a list"}'


def test_a_next_page_that_names_itself_or_an_empty_page_flagged_more_ends_the_reading(monkeypatch):
    owner, cid, _ = setup()
    loop = "https://wms.example.com/api/stock"
    asked = serve(monkeypatch, {loop: page(1, [{"sku": "A", "on_hand": 4}], loop)})
    body = api_job(source=loop, headers={})
    [m] = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={"job": body}).json()["messages"]
    assert (m["status"], len(asked)) == ("applied", 1)
    base = "https://inv.example.com/api/items"
    asked = serve(monkeypatch, {base: {"items": [{"sku": "A", "on_hand": 1}], "more": True},
                                f"{base}?page=2": {"items": [], "more": True},
                                f"{base}?page=3": {"items": [{"sku": "B", "on_hand": 1}], "more": False}})
    body = api_job(source=base, mapping={**STOCK_MAP, "items": "items"}, paging={"mode": "page", "next": "more"},
                   headers={})
    [m] = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={"job": body}).json()["messages"]
    assert [u for u, _ in asked] == [base, f"{base}?page=2"] and m["status"] == "applied"


def test_a_file_address_takes_since_too_and_another_address_or_kind_reads_from_the_start(monkeypatch):
    owner, cid, _ = setup()
    asked = serve(monkeypatch, {
        "https://erp.example.com/stock.csv?from=1970-01-01T00%3A00%3A00%2B00%3A00": b"Plant,Material,Quantity\nP,A,5\n"})
    stock = {"name": "Stock", "kind": "stock", "source_type": "url", "every": "day",
             "source": "https://erp.example.com/stock.csv?from={since}"}
    jid = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=stock).json()["jobs"][0]["id"]
    [row] = client.post(f"/api/companies/{cid}/imports/{jid}/run", headers=h(owner)).json()
    assert row["status"] == "applied" and len(asked) == 1
    url = f"/api/companies/{cid}/imports/{jid}"
    since = client.get(f"/api/companies/{cid}/imports", headers=h(owner)).json()["jobs"][0]["since"]
    assert since and client.put(url, headers=h(owner), json={**stock, "name": "Stock (renamed)"}).json()["jobs"][0][
        "since"] == since
    assert client.put(url, headers=h(owner), json={**stock, "kind": "records:products"}).json()["jobs"][0]["since"] \
        is None


def test_pages_larger_than_a_file_may_be_together_fail_the_run(monkeypatch):
    owner, cid, _ = setup()
    monkeypatch.setattr(imports, "MAX_BYTES", 60)
    base = "https://inv.example.com/api/items"
    serve(monkeypatch, {base: {"items": [{"sku": "A", "on_hand": 1}]},
                        f"{base}?page=2": {"items": [{"sku": "B", "on_hand": 1}]}})
    body = api_job(source=base, mapping={**STOCK_MAP, "items": "items"}, paging={"mode": "page"}, headers={})
    [m] = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={"job": body}).json()["messages"]
    assert m["status"] == "failed" and "larger than 0 MB together" in m["summary"]
