"""ENTERPRISE_PLAN 3.3: Shopify and Odoo as connectors, and a web API paged by its Link header (N206). Shopify is
asked through its Admin GraphQL API with its own token header (N205) and pages by cursor; Odoo through JSON-RPC (or
the JSON API of Odoo 19) as a user with an API key. What each gives is read as the fields here; purchase and
manufacturing orders made here go to Odoo and come back with the reference it gave them. The servers here answer
as Shopify's and Odoo's documented interfaces do."""
from __future__ import annotations

import json
import re

import pytest

from scp.connect import imports
from scp.connect.apps import shopify

from .test_apps import cancel_po, run, save
from .test_connections import client, doc_of, h, setup

SHOP = "kaveri-kitchenware.myshopify.com"
GRAPHQL = f"https://{SHOP}/admin/api/2026-07/graphql.json"
TOKEN = {"access_token": "shpat_0123456789abcdef"}


class Shopify:
    """A shop's Admin API: the lists it keeps, given ``per`` nodes a page whatever was asked."""

    def __init__(self, monkeypatch, lists: dict[str, list[dict]], per: int = 100) -> None:
        self.lists, self.per = lists, per
        self.asked: list[tuple[str, dict]] = []
        self.throttle = 0
        monkeypatch.setattr(imports, "http", self)
        monkeypatch.setattr(shopify, "pause", lambda s: None)

    def __call__(self, method, url, headers, body):
        assert (method, url) == ("POST", GRAPHQL), url
        if headers.get("X-Shopify-Access-Token") != TOKEN["access_token"]:
            return 401, b'{"errors": "[API] Invalid API key or access token (unrecognized login or wrong password)"}'
        q = json.loads(body)
        key = re.search(r"\{\s*(\w+)\(", q["query"]).group(1)
        self.asked.append((key, q["variables"]))
        if self.throttle:
            self.throttle -= 1
            return 200, b'{"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]}'
        rows = self.lists[key]
        start = int(q["variables"].get("after") or 0)
        page = rows[start: start + self.per]
        more = start + self.per < len(rows)
        return 200, json.dumps({"data": {key: {"nodes": page, "pageInfo": {
            "hasNextPage": more, "endCursor": str(start + self.per) if more else None}}}}).encode()


def shop_job(kind: str, **kw) -> dict:
    return {"name": f"Shopify {kind}", "kind": kind, "source_type": "shopify", "source": f"https://{SHOP}/admin",
            "every": "hour", "at": "00:20", "app": {"customer": "K"}, "secrets": TOKEN, **kw}


def variant(sku, product, title="Default Title", price="0.00", status="ACTIVE", ptype="", tracked=True) -> dict:
    return {"id": f"gid://shopify/ProductVariant/{abs(hash((sku, product, title))) % 10**6}", "sku": sku,
            "title": title, "price": price, "inventoryItem": {"tracked": tracked},
            "product": {"title": product, "productType": ptype, "status": status}}


# ---- Shopify ----------------------------------------------------------------------------------------------------
def test_shopifys_variants_become_products_page_by_page_with_its_own_token_header(monkeypatch):
    """Input: four variants, two a page: A by its SKU, a tumbler with no SKU in two sizes, a draft product.
    Processing: the SKU is the code, else the product's and the variant's titles; a draft is not read. Output: A
    renamed and priced, two new tumbler products in the product type's family, every page asked with the token."""
    owner, cid, _ = setup()
    s = Shopify(monkeypatch, {"productVariants": [
        variant("A", "Tin of white paint", price="115.00", ptype="Paint"),
        variant("", "Steel Tumbler", "250 ml", "149.00", ptype="Tumblers"),
        variant("", "Steel Tumbler", "400 ml", "189.00", ptype="Tumblers"),
        variant("DRAFT-1", "Coming soon", status="DRAFT")]}, per=2)
    j = save(owner, cid, shop_job("records:products"))
    assert j["header_names"] == ["access_token"] and "shpat" not in json.dumps(j)
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied" and row["summary"] == "3 products: 3 taken", row
    assert [k for k, _v in s.asked] == ["productVariants", "productVariants"]
    assert s.asked[1][1] == {"after": "2"}                         # the second page by the first's cursor
    prods = {p["id"]: p for p in doc_of(owner, cid)["dataset"]["products"]}
    assert (prods["A"]["name"], prods["A"]["price"], prods["A"]["type"]) == ("Tin of white paint", 115.0, "FG")
    assert prods["A"].get("family", "") == ""                      # a product kept here keeps its family
    t = prods["Steel-Tumbler-250-ml"]
    assert (t["name"], t["family"], t["base_uom"], t["price"]) == ("Steel Tumbler 250 ml", "Tumblers", "Pcs", 149.0)
    assert "Steel-Tumbler-400-ml" in prods and "DRAFT-1" not in prods


def test_shopifys_locations_become_places_and_its_stock_on_hand_lands_by_location(monkeypatch):
    """Input: two active locations (one inactive), and on-hand stock of A at both and of an untracked item.
    Processing: the warehouse is translated to plant P; the pop-up store, not translated, is the place of its own
    name. Output: the pop-up becomes a place; then A's stock is 60 at P, the pop-up's 36 stays its own."""
    owner, cid, _ = setup()
    Shopify(monkeypatch, {
        "locations": [{"id": "gid://shopify/Location/1", "name": "Main Warehouse", "isActive": True,
                       "address": {"address1": "Plot 7, MIDC", "city": "Pune", "province": "Maharashtra",
                                   "zip": "411019", "country": "India"}},
                      {"id": "gid://shopify/Location/2", "name": "Pop-up Store", "isActive": True, "address": {}},
                      {"id": "gid://shopify/Location/3", "name": "Old Shop", "isActive": False}],
        "inventoryItems": [
            {"sku": "A", "tracked": True, "variant": {"sku": "A", "title": "Default Title", "product": {"title": "Tin"}},
             "inventoryLevels": {"nodes": [
                 {"location": {"name": "Main Warehouse"}, "quantities": [{"name": "on_hand", "quantity": 60}]},
                 {"location": {"name": "Pop-up Store"}, "quantities": [{"name": "on_hand", "quantity": 36}]}],
                 "pageInfo": {"hasNextPage": False}}},
            {"sku": "GIFT", "tracked": False, "variant": None, "inventoryLevels": {"nodes": [
                {"location": {"name": "Main Warehouse"}, "quantities": [{"name": "on_hand", "quantity": 5}]}]}}]})
    j = save(owner, cid, shop_job("records:locations", app={}))
    [row] = run(owner, cid, j["id"])
    assert row["summary"] == "2 locations: 2 taken", row
    locs = {x["id"]: x for x in doc_of(owner, cid)["dataset"]["locations"]}
    assert (locs["Main-Warehouse"]["type"], locs["Pop-up-Store"]["type"]) == ("warehouse", "warehouse")
    assert locs["Main-Warehouse"]["address"] == "Plot 7, MIDC\nPune\nMaharashtra\n411019\nIndia"
    assert "Old-Shop" not in locs
    j = save(owner, cid, shop_job("stock", app={}, mapping={"fields": {"location": {"values": {"Main Warehouse": "P"}}}}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied", row
    stock = {(x["location"], x["product"]): x.get("on_hand", 0) for x in doc_of(owner, cid)["dataset"]["location_products"]}
    assert stock[("P", "A")] == 60 and stock[("Pop-up-Store", "A")] == 36


def test_untranslated_locations_go_to_the_place_the_job_names_and_are_summed(monkeypatch):
    owner, cid, _ = setup()
    Shopify(monkeypatch, {"inventoryItems": [
        {"sku": "A", "tracked": True, "variant": {"sku": "A", "title": "", "product": {"title": "Tin"}},
         "inventoryLevels": {"nodes": [
             {"location": {"name": "Main Warehouse"}, "quantities": [{"name": "on_hand", "quantity": 60}]},
             {"location": {"name": "Pop-up Store"}, "quantities": [{"name": "available", "quantity": 1},
                                                                   {"name": "on_hand", "quantity": 36}]}]}}]})
    j = save(owner, cid, shop_job("stock", app={"place": "P"}))
    [row] = run(owner, cid, j["id"])
    assert row["items"][0]["message"].startswith("96 on hand"), row


def order(name, lines, created="2026-01-05T09:12:00Z", cancelled=None, buyer="Ravi Kumar", note="") -> dict:
    return {"name": name, "createdAt": created, "cancelledAt": cancelled, "note": note,
            "customer": {"displayName": buyer}, "lineItems": {"nodes": lines, "pageInfo": {"hasNextPage": False}}}


def line(lid, sku, qty, price="115.00") -> dict:
    return {"id": f"gid://shopify/LineItem/{lid}", "sku": sku, "name": sku, "currentQuantity": qty,
            "variant": {"sku": sku, "title": "Default Title", "product": {"title": sku}},
            "originalUnitPriceSet": {"shopMoney": {"amount": price}}}


def test_shopifys_orders_since_the_last_run_become_orders_of_the_online_shop_customer(monkeypatch):
    """Input: order #1001 (3 A at 115, and a line of B removed by an edit) and #1002, cancelled before it was read.
    Processing: orders updated since the last good run (the first run: 90 days back); the buyer is the note.
    Output: one order for customer K numbered 1001 with one line; #1002 was never taken and is not."""
    owner, cid, _ = setup()
    s = Shopify(monkeypatch, {"orders": [
        order("#1001", [line(1, "A", 3), line(2, "B", 0)], note="Gift wrap"),
        order("#1002", [line(3, "A", 1)], cancelled="2026-01-05T10:00:00Z")]})
    j = save(owner, cid, shop_job("orders"))
    [row] = run(owner, cid, j["id"])
    assert row["summary"] == "2 orders: 1 taken, 1 as here already", row
    assert re.fullmatch(r"updated_at:>'\d{4}-\d\d-\d\dT00:00:00Z'", s.asked[0][1]["q"])
    so = doc_of(owner, cid)["dataset"]["sales_orders"][-1]
    assert (so["customer"], so["erp_ref"], so["customer_ref"], so["note"]) == ("K", "1001", "#1001",
                                                                                "Ravi Kumar: Gift wrap")
    lines = [d for d in doc_of(owner, cid)["dataset"]["demand"] if d.get("order") == so["id"]]
    assert [(x["product"], x["qty"], x["date"], x["price"]) for x in lines] == [("A", 3, "2026-01-05", 115.0)]
    # read again later: only what changed since this run started
    run(owner, cid, j["id"])
    assert s.asked[-1][1]["q"] > s.asked[0][1]["q"]


def test_shopify_fulfilments_are_deliveries_of_the_orders_lines_each_taken_once(monkeypatch):
    """Input: #1001 taken as an order (3 A); a fulfilment of 2 of them, and a cancelled one. Processing: the
    fulfilled line is the order's line 10 here. Output: 2 A delivered from 1001's line; the same answer again posts
    nothing twice."""
    owner, cid, _ = setup()
    s = Shopify(monkeypatch, {"orders": [order("#1001", [line(2, "B", 0), line(1, "A", 3)])]})
    run(owner, cid, save(owner, cid, shop_job("orders"))["id"])
    s.lists["orders"] = [{"name": "#1001", "lineItems": {"nodes": [{"id": "gid://shopify/LineItem/2",
                                                                     "currentQuantity": 0},
                                                                    {"id": "gid://shopify/LineItem/1",
                                                                     "currentQuantity": 3}]},
                          "fulfillments": [
                              {"id": "gid://shopify/Fulfillment/77", "createdAt": "2026-01-06T08:00:00Z",
                               "status": "SUCCESS", "fulfillmentLineItems": {"nodes": [
                                   {"quantity": 2, "lineItem": {"id": "gid://shopify/LineItem/1"}}]}},
                              {"id": "gid://shopify/Fulfillment/78", "createdAt": "2026-01-06T09:00:00Z",
                               "status": "CANCELLED", "fulfillmentLineItems": {"nodes": [
                                   {"quantity": 1, "lineItem": {"id": "gid://shopify/LineItem/1"}}]}}]}]
    j = save(owner, cid, shop_job("postings", app={}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied" and row["items"][0]["ref"] == "shopify-77/10", row
    d = doc_of(owner, cid)["dataset"]
    so = d["sales_orders"][-1]
    [mv] = d["movements"]
    assert (mv["type"], mv["product"], mv["qty"], mv["date"], mv["reference"], mv["erp_ref"]) == \
        ("sale", "A", 2, "2026-01-06", f"{so['id']}/10", "shopify-77/10")
    [again] = run(owner, cid, j["id"])
    assert again["status"] == "duplicate"


def test_shopify_refuses_a_wrong_token_and_asks_a_throttled_call_again(monkeypatch):
    owner, cid, _ = setup()
    s = Shopify(monkeypatch, {"productVariants": [variant("A", "Tin")]})
    j = save(owner, cid, shop_job("records:products", secrets={"access_token": "shpat_wrong"}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "failed" and "does not take the access token (401)" in row["summary"], row
    j = save(owner, cid, shop_job("records:products"))
    s.throttle = 1
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied" and len(s.asked) == 2


@pytest.mark.parametrize(("change", "says"), [
    ({"source": "kaveri.example.com"}, "myshopify.com address"),
    ({"secrets": {"access_token": " "}}, "Admin API access token"),
    ({"app": {}}, "go to a customer here"),
    ({"kind": "send:purchase_order"}, "Shopify gives records:products"),
    ({"app": {"customer": "K", "api_version": "2026-05"}}, "api_version"),
])
def test_a_shopify_job_that_cannot_work_is_refused_saying_what_to_give(change, says):
    owner, cid, _ = setup()
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json={**shop_job("orders"), **change})
    assert r.status_code == 422 and says in r.text, r.text


def test_shopifys_token_is_kept_when_the_job_is_saved_again_without_it(monkeypatch):
    owner, cid, _ = setup()
    s = Shopify(monkeypatch, {"productVariants": [variant("A", "Tin")]})
    j = save(owner, cid, shop_job("records:products"))
    r = client.put(f"/api/companies/{cid}/imports/{j['id']}", headers=h(owner),
                   json={**shop_job("records:products", name="Shopify products"), "secrets": {"access_token": ""}})
    assert r.status_code == 200, r.text
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied" and s.asked
    # another shop does not get this shop's token
    r = client.put(f"/api/companies/{cid}/imports/{j['id']}", headers=h(owner),
                   json={**shop_job("records:products", source="other-shop.myshopify.com"), "secrets": None})
    assert r.status_code == 422 and "access token" in r.text


# ---- Odoo -------------------------------------------------------------------------------------------------------
ODOO = "https://kaveri.odoo.com"
LOGIN = {"login": "planner@kaveri.example", "api_key": "a1b2c3d4"}


def _match(rec: dict, dom: list) -> bool:
    """Odoo's domain (prefix & and |, the operators used here) on one record."""
    def ev(i: int) -> tuple[bool, int]:
        t = dom[i]
        if t in ("&", "|"):
            a, j = ev(i + 1)
            b, k = ev(j)
            return (a and b if t == "&" else a or b), k
        f, op, v = t
        x = rec.get(f)
        if isinstance(x, list) and x and isinstance(x[0], int):
            x = x[0]
        ok = {"=": lambda: x == v or (v is False and not x), "!=": lambda: x != v, "in": lambda: x in v,
              ">": lambda: x is not None and x > v}[op]()
        return ok, i + 1
    i, ok = 0, True
    while i < len(dom):
        r, i = ev(i)
        ok = ok and r
    return ok


class Odoo:
    """One Odoo database: its tables by model, what it was called with, and the user who may call."""

    def __init__(self, monkeypatch, tables: dict[str, list[dict]], json2: bool = False) -> None:
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        for k in ("purchase.order", "purchase.order.line", "mrp.production", "change.production.qty"):
            self.t.setdefault(k, [])
        self.json2 = json2
        self.calls: list[tuple[str, str, list, dict]] = []
        monkeypatch.setattr(imports, "http", self)

    def __call__(self, method, url, headers, body):
        q = json.loads(body)
        if self.json2:
            m = re.fullmatch(re.escape(ODOO) + r"/json/2/([\w.]+)/(\w+)", url)
            assert m and headers["X-Odoo-Database"] == "kaveri", (url, headers)
            if headers["Authorization"] != f"bearer {LOGIN['api_key']}":
                return 401, b'{"name": "werkzeug.exceptions.Unauthorized", "message": "Invalid apikey"}'
            model, meth = m.groups()
            args = [q.pop(k) for k in ("domain", "vals_list", "ids", "vals") if k in q]
            return 200, json.dumps(self.execute(model, meth, args, q)).encode()
        assert url == f"{ODOO}/jsonrpc" and q["method"] == "call", url
        p = q["params"]
        if p["service"] == "common":
            db, login, key, _ = p["args"]
            ok = (db, login, key) == ("kaveri", LOGIN["login"], LOGIN["api_key"])
            return 200, json.dumps({"jsonrpc": "2.0", "id": q["id"], "result": 2 if ok else False}).encode()
        db, uid, key, model, meth, args, kw = p["args"]
        assert (db, uid, key) == ("kaveri", 2, LOGIN["api_key"])
        try:
            res = self.execute(model, meth, args, kw)
        except ValueError as e:
            return 200, json.dumps({"jsonrpc": "2.0", "id": q["id"], "error": {
                "code": 200, "message": "Odoo Server Error", "data": {"name": "odoo.exceptions.UserError",
                                                                      "message": str(e)}}}).encode()
        return 200, json.dumps({"jsonrpc": "2.0", "id": q["id"], "result": res}).encode()

    def execute(self, model, meth, args, kw):
        self.calls.append((model, meth, args, kw))
        rows = self.t.setdefault(model, [])
        if meth == "search_read":
            got = [r for r in rows if _match(r, args[0])]
            got = got[kw.get("offset", 0): kw.get("offset", 0) + kw.get("limit", 10**6)]
            return [{"id": r["id"], **{f: r.get(f, False) for f in kw["fields"]}} for r in got]
        if meth == "fields_get":
            return {"date_start": {"type": "datetime"}, "date_deadline": {"type": "datetime"}}
        if meth == "create":
            ids = []
            for vals in args[0]:
                rid = 100 + len(rows) + 1
                rec = {"id": rid, **vals}
                if model == "purchase.order":
                    rec.update(name=f"P{rid:05d}", state="draft")
                    for cmd in rec.pop("order_line", []):
                        self.t["purchase.order.line"].append({"id": 500 + len(self.t["purchase.order.line"]),
                                                              "order_id": [rid, rec["name"]], "qty_received": 0,
                                                              "product_id": [cmd[2]["product_id"], ""], **{
                                                                  k: v for k, v in cmd[2].items() if k != "product_id"}})
                if model == "mrp.production":
                    rec.update(name=f"WH/MO/{rid:05d}", state="draft")
                rows.append(rec)
                ids.append(rid)
            return ids
        by = {r["id"]: r for r in rows}
        if meth == "write":
            for rid in args[0]:
                vals = dict(args[1])
                for cmd in vals.pop("order_line", []):
                    if cmd[0] == 0:
                        self.t["purchase.order.line"].append({"id": 500 + len(self.t["purchase.order.line"]),
                                                              "order_id": [rid, ""], "qty_received": 0,
                                                              "product_id": [cmd[2]["product_id"], ""]})
                    elif cmd[0] == 1:
                        ln = next(x for x in self.t["purchase.order.line"] if x["id"] == cmd[1])
                        ln.update(cmd[2])
                by[rid].update(vals)
            return True
        if meth in ("button_confirm", "action_confirm"):
            for rid in args[0]:
                by[rid]["state"] = "purchase" if model == "purchase.order" else "confirmed"
            return True
        if meth in ("button_cancel", "action_cancel"):
            for rid in args[0]:
                by[rid]["state"] = "cancel"
            return True
        if meth == "change_prod_qty":
            for rid in args[0]:
                w = by[rid]
                mo = next(x for x in self.t["mrp.production"] if x["id"] == w["mo_id"])
                mo["product_qty"] = w["product_qty"]
            return True
        raise ValueError(f"{model}.{meth} is not known here")


def odoo_job(kind: str, **kw) -> dict:
    return {"name": f"Odoo {kind}", "kind": kind, "source_type": "odoo", "source": f"{ODOO}/odoo/action-1",
            "every": "hour", "at": "00:25", "app": {"database": "kaveri", "place": "P"}, "secrets": LOGIN, **kw}


PRODUCTS = [
    {"id": 11, "default_code": "A", "name": "Tin of white", "uom_id": [1, "Units"], "categ_id": [3, "All / Paints"],
     "list_price": 120.0, "type": "consu", "active": True, "product_tmpl_id": [11, "Tin of white"]},
    {"id": 12, "default_code": "B", "name": "Steel sheet", "uom_id": [12, "kg"], "categ_id": [4, "All / Metals"],
     "list_price": 0.0, "type": "consu", "active": True, "product_tmpl_id": [12, "Steel sheet"]},
    {"id": 13, "default_code": False, "name": "Pressure Cooker 3L", "uom_id": [1, "Units"],
     "categ_id": [5, "All / Saleable / Cookers"], "list_price": 1450.0, "type": "consu", "active": True,
     "product_tmpl_id": [13, "Pressure Cooker 3L"]},
    {"id": 14, "default_code": "SRV", "name": "Installation", "type": "service", "active": True,
     "product_tmpl_id": [14, "Installation"]},
    {"id": 15, "default_code": False, "name": "Lid", "type": "consu", "active": True, "product_tmpl_id": [15, "Lid"]},
]
PARTNERS = [
    {"id": 7, "name": "Kumar Stores", "customer_rank": 3, "supplier_rank": 0, "vat": "27AAACK1234F1Z5",
     "street": "12 MG Road", "city": "Pune", "zip": "411001", "state_id": [21, "Maharashtra"],
     "country_id": [104, "India"], "parent_id": False, "commercial_partner_id": [7, "Kumar Stores"]},
    {"id": 8, "name": "Kumar Stores, Ravi", "customer_rank": 1, "parent_id": [7, "Kumar Stores"],
     "commercial_partner_id": [7, "Kumar Stores"]},
    {"id": 9, "name": "Sharma Metals", "customer_rank": 0, "supplier_rank": 5, "parent_id": False,
     "commercial_partner_id": [9, "Sharma Metals"]},
    {"id": 10, "name": "Walk-in", "customer_rank": 0, "supplier_rank": 0, "parent_id": False},
]


def test_odoos_products_partners_and_boms(monkeypatch):
    """Input: Odoo's products, partners and bills of materials. Processing: read as the user with the API key, the
    internal reference (else the name) as the code. Output: products (no service), customers and suppliers (a
    contact person is not one), and A's BOM as PV-A's components with the steps here kept."""
    owner, cid, _ = setup()
    o = Odoo(monkeypatch, {"product.product": PRODUCTS, "res.partner": PARTNERS, "mrp.bom": [
        {"id": 1, "code": "PV-A", "product_tmpl_id": [11, "Tin of white"], "product_id": False, "product_qty": 10,
         "active": True, "type": "normal"},
        {"id": 2, "code": "", "product_tmpl_id": [13, "Pressure Cooker 3L"], "product_id": [13, "Cooker"],
         "product_qty": 1, "active": True, "type": "normal"},
        {"id": 3, "code": "KIT", "product_tmpl_id": [11, "Tin"], "product_id": False, "product_qty": 1,
         "active": True, "type": "phantom"}],
        "mrp.bom.line": [{"id": 1, "bom_id": [1, "PV-A"], "product_id": [12, "Steel sheet"], "product_qty": 25},
                         {"id": 2, "bom_id": [1, "PV-A"], "product_id": [15, "Lid"], "product_qty": 10},
                         {"id": 3, "bom_id": [2, ""], "product_id": [12, "Steel sheet"], "product_qty": 1.2}]})
    [row] = run(owner, cid, save(owner, cid, odoo_job("records:products"))["id"])
    assert row["summary"] == "4 products: 4 taken", row
    prods = {p["id"]: p for p in doc_of(owner, cid)["dataset"]["products"]}
    assert (prods["A"]["name"], prods["A"]["price"], prods["A"]["type"]) == ("Tin of white", 120.0, "FG")
    cooker = prods["Pressure-Cooker-3L"]
    assert (cooker["family"], cooker["base_uom"], cooker["price"]) == ("Cookers", "Units", 1450.0)
    assert "SRV" not in prods
    assert o.calls[0][:2] == ("product.product", "search_read")
    [row] = run(owner, cid, save(owner, cid, odoo_job("records:locations"))["id"])
    assert row["summary"] == "2 locations: 2 taken", row
    locs = {x["id"]: x for x in doc_of(owner, cid)["dataset"]["locations"]}
    assert (locs["Kumar-Stores"]["type"], locs["Kumar-Stores"]["region"], locs["Kumar-Stores"]["tax_id"]) == \
        ("customer", "Maharashtra", "27AAACK1234F1Z5")
    assert locs["Kumar-Stores"]["address"] == "12 MG Road\nPune\n411001\nMaharashtra\nIndia"
    assert locs["Sharma-Metals"]["type"] == "supplier" and "Walk-in" not in locs
    [row] = run(owner, cid, save(owner, cid, odoo_job("records:production_sources", mapping={"fields": {
        "product": {"values": {"Lid": "C"}}}}))["id"])                  # Odoo's lid is C here
    assert row["status"] == "applied", row
    ps = {x["id"]: x for x in doc_of(owner, cid)["dataset"]["production_sources"]}
    assert (ps["PV-A"]["output_qty"], [(c["product"], c["qty"]) for c in ps["PV-A"]["components"]]) == \
        (10, [("B", 25), ("C", 10)])
    assert ps["PV-A"]["operations"][0]["resource"] == "M1"           # the steps here are kept
    assert (ps["Pressure-Cooker-3L"]["location"], ps["Pressure-Cooker-3L"]["components"][0]["qty"]) == ("P", 1.2)
    assert "KIT" not in ps


def test_odoos_stock_is_summed_by_warehouse_into_the_place_it_is_translated_to(monkeypatch):
    owner, cid, _ = setup()
    Odoo(monkeypatch, {"product.product": PRODUCTS, "stock.quant": [
        {"id": 1, "product_id": [11, "[A] Tin"], "location_id": [8, "WH/Stock"], "warehouse_id": [1, "Pune WH"],
         "quantity": 50, "location_id.usage": "internal"},
        {"id": 2, "product_id": [11, "[A] Tin"], "location_id": [9, "WH/Stock/Shelf 2"], "warehouse_id": [1, "Pune WH"],
         "quantity": 22, "location_id.usage": "internal"},
        {"id": 3, "product_id": [12, "[B] Steel"], "location_id": [8, "WH/Stock"], "warehouse_id": [1, "Pune WH"],
         "quantity": -4, "location_id.usage": "internal"},
        {"id": 4, "product_id": [11, "[A] Tin"], "location_id": [5, "Partners/Customers"], "warehouse_id": False,
         "quantity": 999, "location_id.usage": "customer"}]})
    j = save(owner, cid, odoo_job("stock", app={"database": "kaveri"},
                                  mapping={"fields": {"location": {"values": {"Pune WH": "P"}}}}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied", row
    stock = {(x["location"], x["product"]): x.get("on_hand", 0) for x in doc_of(owner, cid)["dataset"]["location_products"]}
    assert (stock[("P", "A")], stock[("P", "B")]) == (72, 0)


def test_odoos_confirmed_sales_orders_become_orders_of_the_customers_company(monkeypatch):
    """Input: S00012, confirmed, for a contact of Kumar Stores with a delivery date, and a quotation. Processing:
    orders changed since the last run; the contact's company is the customer (translated to K). Output: an order
    of K numbered S00012 with its lines due on the delivery date; the quotation is not read."""
    owner, cid, _ = setup()
    o = Odoo(monkeypatch, {"product.product": PRODUCTS, "res.partner": PARTNERS, "sale.order": [
        {"id": 40, "name": "S00012", "partner_id": [8, "Kumar Stores, Ravi"], "date_order": "2026-01-05 10:30:00",
         "commitment_date": "2026-01-12 09:00:00", "client_order_ref": "KS-PO-91", "state": "sale",
         "note": "<p>Deliver <b>before noon</b></p>", "write_date": "2099-01-05 10:31:00"},
        {"id": 41, "name": "S00013", "partner_id": [7, "Kumar Stores"], "date_order": "2026-01-05 11:00:00",
         "state": "draft", "write_date": "2099-01-05 11:00:00"}],
        "sale.order.line": [
            {"id": 1, "order_id": [40, "S00012"], "product_id": [11, "A"], "product_uom_qty": 8, "price_unit": 118.0,
             "display_type": False},
            {"id": 2, "order_id": [40, "S00012"], "product_id": False, "product_uom_qty": 0, "display_type": "line_note"},
            {"id": 3, "order_id": [40, "S00012"], "product_id": [13, "Cooker"], "product_uom_qty": 2,
             "price_unit": 1450.0, "display_type": False}]})
    j = save(owner, cid, odoo_job("orders", mapping={"fields": {"customer": {"values": {"Kumar Stores": "K"}}}},
                                  ))
    d = doc_of(owner, cid)["dataset"]
    d["products"].append({"id": "Pressure-Cooker-3L", "type": "FG"})
    c = doc_of(owner, cid)
    client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    [row] = run(owner, cid, j["id"])
    assert row["summary"] == "1 order: 1 taken", row
    model, meth, args, _kw = o.calls[0]
    assert (model, meth, args[0][1]) == ("sale.order", "search_read", ["state", "in", ["sale", "done", "cancel"]])
    so = doc_of(owner, cid)["dataset"]["sales_orders"][-1]
    assert (so["customer"], so["erp_ref"], so["customer_ref"], so["note"]) == ("K", "S00012", "KS-PO-91",
                                                                                "Deliver before noon")
    lines = [x for x in doc_of(owner, cid)["dataset"]["demand"] if x.get("order") == so["id"]]
    assert [(x["product"], x["qty"], x["date"]) for x in lines] == [("A", 8, "2026-01-12"),
                                                                    ("Pressure-Cooker-3L", 2, "2026-01-12")]


def test_a_purchase_order_goes_to_odoo_confirmed_and_changes_and_cancelling_follow(monkeypatch):
    """Input: PO-00001 (100 B from Sharma Metals, due 8 January, 10 a unit). Processing: Odoo's vendor and product
    found by name and internal reference; made and confirmed; then due later, then cancelled here. Output: P00101
    in Odoo with our number as its source document; the change rewrites its line; the cancel cancels it."""
    owner, cid, _ = setup()
    o = Odoo(monkeypatch, {"product.product": PRODUCTS, "res.partner": PARTNERS})
    j = save(owner, cid, odoo_job("send:purchase_order"))
    [out] = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner),
                        json={"job": odoo_job("send:purchase_order")}).json()["messages"]
    assert out["items"][0]["message"] == "would be made in Odoo (Sharma Metals)" and not o.t["purchase.order"], out
    ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "made in Odoo as P00101", out
    [po] = o.t["purchase.order"]
    assert (po["partner_id"], po["origin"], po["state"], po["date_order"]) == (9, "PO-00001", "purchase",
                                                                               "2026-01-02 12:00:00")
    [ln] = o.t["purchase.order.line"]
    assert (ln["product_id"][0], ln["product_qty"], ln["price_unit"], ln["date_planned"]) == \
        (12, 100, 10, "2026-01-08 12:00:00")
    assert doc_of(owner, cid)["dataset"]["purchase_orders"][0]["erp_ref"] == "P00101"
    c = doc_of(owner, cid)
    d = c["dataset"]
    d["receipts"][0]["due_date"] = "2026-01-12"
    client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    _ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "changed in Odoo as P00101", out
    assert (len(o.t["purchase.order.line"]), o.t["purchase.order.line"][0]["date_planned"]) == (1, "2026-01-12 12:00:00")
    write = next(c for c in o.calls if c[1] == "write")
    assert write[2][1]["order_line"][0][:2] == [1, ln["id"]]
    [quiet] = run(owner, cid, j["id"])
    assert quiet["status"] == "unchanged"
    cancel_po(owner, cid)
    _ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "cancelled in Odoo as P00101", out
    assert o.t["purchase.order"][0]["state"] == "cancel"


def test_a_manufacturing_order_goes_to_odoo_and_a_new_quantity_uses_change_quantity(monkeypatch):
    """Input: MO-1 (20 A at P, 7 to 9 January). Processing: made with Odoo's start field and confirmed; then 25 here.
    Output: WH/MO/00101 confirmed; the new quantity through Odoo's change-quantity wizard; deleted here, cancelled
    there."""
    owner, cid, _ = setup()
    o = Odoo(monkeypatch, {"product.product": PRODUCTS})
    j = save(owner, cid, odoo_job("send:production_order"))
    ack, out = run(owner, cid, j["id"])
    assert out["summary"] == "1 production order to Odoo: 1 sent" and \
        out["items"][0]["message"] == "made in Odoo as WH/MO/00101", out
    [mo] = o.t["mrp.production"]
    assert (mo["product_id"], mo["product_qty"], mo["origin"], mo["date_start"], mo["date_deadline"], mo["state"]) == \
        (11, 20, "MO-1", "2026-01-07 12:00:00", "2026-01-09 12:00:00", "confirmed")
    rec = next(r for r in doc_of(owner, cid)["dataset"]["receipts"] if r["id"] == "MO-1")
    assert rec["erp_ref"] == "WH/MO/00101"
    c = doc_of(owner, cid)
    d = c["dataset"]
    next(r for r in d["receipts"] if r["id"] == "MO-1")["qty"] = 25
    client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    _ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "changed in Odoo as WH/MO/00101", out
    assert mo["product_qty"] == 25 and any(c[:2] == ("change.production.qty", "change_prod_qty") for c in o.calls)
    c = doc_of(owner, cid)
    d = c["dataset"]
    d["receipts"] = [r for r in d["receipts"] if r["id"] != "MO-1"]
    client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "cancelled in Odoo as WH/MO/00101" and mo["state"] == "cancel", out
    assert "closed its copy" in ack["items"][0]["message"]


def test_odoo_refuses_a_vendor_or_product_it_does_not_have_and_a_wrong_key(monkeypatch):
    owner, cid, _ = setup()
    Odoo(monkeypatch, {"product.product": PRODUCTS, "res.partner": [p for p in PARTNERS if p["id"] != 9]})
    j = save(owner, cid, odoo_job("send:purchase_order"))
    [out] = run(owner, cid, j["id"])
    assert out["status"] == "refused" and "Odoo has no vendor 'Sharma Metals'" in out["items"][0]["message"], out
    j = save(owner, cid, odoo_job("records:products", secrets={"login": LOGIN["login"], "api_key": "wrong"}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "failed" and "does not take the login and API key" in row["summary"], row


def test_odoo_19s_json_api_takes_the_key_as_a_bearer_token_and_named_arguments(monkeypatch):
    owner, cid, _ = setup()
    o = Odoo(monkeypatch, {"product.product": PRODUCTS, "res.partner": PARTNERS}, json2=True)
    j = save(owner, cid, odoo_job("send:purchase_order", app={"database": "kaveri", "odoo_api": "json2"}))
    _ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "made in Odoo as P00101", out
    assert o.t["purchase.order"][0]["state"] == "purchase"


@pytest.mark.parametrize(("change", "says"), [
    ({"app": {"place": "P"}}, "database's name"),
    ({"secrets": {"login": "x"}}, "API key"),
    ({"kind": "records:production_sources", "app": {"database": "kaveri"}}, "name the plant"),
    ({"source": "ftp://kaveri.odoo.com"}, "web address"),
    ({"kind": "postings"}, "Odoo gives"),
])
def test_an_odoo_job_that_cannot_work_is_refused_saying_what_to_give(change, says):
    owner, cid, _ = setup()
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json={**odoo_job("orders"), **change})
    assert r.status_code == 422 and says in r.text, r.text


# ---- N206: a web API paged by its Link header -------------------------------------------------------------------
def test_a_web_api_that_names_its_next_page_in_a_link_header_is_read_to_the_end(monkeypatch):
    owner, cid, _ = setup()
    asked: list[str] = []
    first = "https://api.example.com/stock?limit=1"
    nxt = "https://api.example.com/stock?limit=1&page_info=abc"

    def fake(method, url, headers, body):
        asked.append(url)
        assert headers.get("Authorization") == "Bearer t"
        if url == first:
            return imports.Answer(200, b'[{"location": "P", "product": "A", "qty": 7}]',
                                  {"Link": f'<{nxt}>; rel="next"'})
        return imports.Answer(200, b'[{"location": "P", "product": "B", "qty": 3}]',
                              {"Link": f'<{first}>; rel="previous"'})
    monkeypatch.setattr(imports, "http", fake)
    j = save(owner, cid, {"name": "Stock API", "kind": "stock", "source_type": "api", "source": first, "format": "json",
                          "headers": {"Authorization": "Bearer t"}, "paging": {"mode": "link"}, "every": "hour",
                          "at": "00:30"})
    [row] = run(owner, cid, j["id"])
    assert asked == [first, nxt] and row["summary"].startswith("2 stock"), row


def test_a_link_header_with_several_links_gives_the_next_one():
    a = imports.Answer(200, b"", {"Link": '<https://x/a>; rel="previous", <https://x/b>; rel="next"'})
    assert imports.link_next(a) == "https://x/b"
    assert imports.link_next((200, b"")) is None
    assert imports.link_next(imports.Answer(200, b"", {"Link": '<https://x/a>; rel="previous"'})) is None
