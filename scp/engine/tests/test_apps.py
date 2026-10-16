"""ENTERPRISE_PLAN 3.2: Tally Prime and Zoho Inventory as connectors. Each is asked in its own way (Tally's XML
envelope on its HTTP port, Zoho's REST API with an OAuth refresh token) and answers as it does; what it gives is
read as the fields here (codes translated by the job's mapping), and purchase orders made here go to it and come
back with the number it gave them. The servers here answer as Tally's and Zoho's documented interfaces do."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from scp.connect import imports
from scp.connect.apps import zoho

from .test_connections import client, doc_of, h, setup

TALLY = "http://tally.example.com:9000"


def run(owner: str, cid: str, jid: str) -> list[dict]:
    r = client.post(f"/api/companies/{cid}/imports/{jid}/run", headers=h(owner))
    assert r.status_code == 200, r.text
    return r.json()


def save(owner: str, cid: str, body: dict) -> dict:
    r = client.post(f"/api/companies/{cid}/imports", headers=h(owner), json=body)
    assert r.status_code == 200, r.text
    return r.json()["jobs"][-1]


def envelope(collection: str) -> bytes:
    return (f"<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA>"
            f"<COLLECTION>{collection}</COLLECTION></DATA></BODY></ENVELOPE>").encode()


ITEMS = envelope(
    '<STOCKITEM NAME="Tin White 1L" RESERVEDNAME=""><PARENT TYPE="String">Tins</PARENT>'
    '<BASEUNITS TYPE="String">Nos</BASEUNITS><CLOSINGBALANCE TYPE="Quantity"> 96 Nos</CLOSINGBALANCE></STOCKITEM>'
    '<STOCKITEM NAME="Steel Tumbler 250 ml&#4;"><PARENT>Tumblers</PARENT><BASEUNITS>Pcs</BASEUNITS>'
    "<CLOSINGBALANCE>1,200 Pcs</CLOSINGBALANCE></STOCKITEM>"
    '<STOCKITEM NAME="Old Lid"><PARENT>Primary</PARENT><BASEUNITS>Nos</BASEUNITS><CLOSINGBALANCE/></STOCKITEM>')
LEDGERS = envelope(
    '<LEDGER NAME="Kumar Stores"><PARENT>Sundry Debtors</PARENT><ADDRESS.LIST TYPE="String"><ADDRESS>12 MG Road'
    "</ADDRESS><ADDRESS>Pune 411001</ADDRESS></ADDRESS.LIST><LEDSTATENAME>Maharashtra</LEDSTATENAME>"
    "<PARTYGSTIN>27AAACK1234F1Z5</PARTYGSTIN><SCPDEBTOR>Yes</SCPDEBTOR><SCPCREDITOR>No</SCPCREDITOR></LEDGER>"
    '<LEDGER NAME="Mehta Traders"><PARENT>West Zone Dealers</PARENT><LEDSTATENAME>Gujarat</LEDSTATENAME>'
    "<SCPDEBTOR>Yes</SCPDEBTOR><SCPCREDITOR>No</SCPCREDITOR></LEDGER>"
    '<LEDGER NAME="Sharma Metals Pvt Ltd"><PARENT>Sundry Creditors</PARENT><LEDGSTREGDETAILS.LIST>'
    "<GSTIN>27AABCS9876K1Z2</GSTIN></LEDGSTREGDETAILS.LIST><SCPDEBTOR>No</SCPDEBTOR><SCPCREDITOR>Yes</SCPCREDITOR>"
    "</LEDGER>"
    '<LEDGER NAME="Cash"><PARENT>Cash-in-Hand</PARENT><SCPDEBTOR>No</SCPDEBTOR><SCPCREDITOR>No</SCPCREDITOR></LEDGER>')
ORDERS = envelope(
    '<VOUCHER REMOTEID="a1" VCHTYPE="Sales Order"><DATE>20260103</DATE><VOUCHERNUMBER>SO/12</VOUCHERNUMBER>'
    "<PARTYLEDGERNAME>Kumar Stores</PARTYLEDGERNAME><REFERENCE>KS-PO-88</REFERENCE><ISCANCELLED>No</ISCANCELLED>"
    "<ISOPTIONAL>No</ISOPTIONAL><ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Tin White 1L</STOCKITEMNAME>"
    "<RATE>120.00/Nos</RATE><ACTUALQTY> 10 Nos</ACTUALQTY><BILLEDQTY> 10 Nos</BILLEDQTY><AMOUNT>1200.00</AMOUNT>"
    "<BATCHALLOCATIONS.LIST><GODOWNNAME>Main Location</GODOWNNAME><ORDERDUEDATE P=\"08-Jan-2026\">08-Jan-2026"
    "</ORDERDUEDATE><ACTUALQTY> 6 Nos</ACTUALQTY><BILLEDQTY> 6 Nos</BILLEDQTY></BATCHALLOCATIONS.LIST>"
    "<BATCHALLOCATIONS.LIST><GODOWNNAME>Main Location</GODOWNNAME><ORDERDUEDATE>15-Jan-2026</ORDERDUEDATE>"
    "<ACTUALQTY> 4 Nos</ACTUALQTY><BILLEDQTY> 4 Nos</BILLEDQTY></BATCHALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>"
    "</VOUCHER>"
    '<VOUCHER VCHTYPE="Sales Order"><DATE>20260104</DATE><VOUCHERNUMBER>SO/13</VOUCHERNUMBER>'
    "<PARTYLEDGERNAME>Kumar Stores</PARTYLEDGERNAME><ISOPTIONAL>Yes</ISOPTIONAL><ALLINVENTORYENTRIES.LIST>"
    "<STOCKITEMNAME>Tin White 1L</STOCKITEMNAME><ACTUALQTY> 50 Nos</ACTUALQTY></ALLINVENTORYENTRIES.LIST></VOUCHER>")
TAKEN = (b"<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><DELETED>0</DELETED><LASTVCHID>311</LASTVCHID>"
         b"<LASTMID>0</LASTMID><COMBINED>0</COMBINED><IGNORED>0</IGNORED><ERRORS>0</ERRORS><CANCELLED>0</CANCELLED>"
         b"</RESPONSE>")


def tally(monkeypatch, answers: dict[str, bytes]) -> list[str]:
    """A Tally that answers each collection asked for, and takes vouchers: the requests it was sent, as text."""
    asked: list[str] = []

    def fake(method, url, headers, body):
        assert method == "POST" and url == TALLY and headers["Content-Type"] == "text/xml"
        text = body.decode()
        asked.append(text)
        if "<TALLYREQUEST>Import Data</TALLYREQUEST>" in text:
            return 200, answers.get("import", TAKEN)
        name = re.search(r"<ID>(\w+)</ID>", text).group(1)
        return 200, answers.get(name, envelope(""))
    monkeypatch.setattr(imports, "http", fake)
    return asked


def tally_job(kind: str, **kw) -> dict:
    return {"name": f"Tally {kind}", "kind": kind, "source_type": "tally", "source": TALLY, "every": "hour",
            "at": "00:05", "app": {"company": "Kaveri Kitchenware", "place": "P"}, **kw}


# ---- Tally ------------------------------------------------------------------------------------------------------
def test_tallys_stock_items_become_products_a_translated_one_keeps_its_type_here(monkeypatch):
    """Input: Tally's stock items (name, stock group, base unit). Processing: the item named here differently is
    translated; the others take their name as their code. Output: a new product per new item, the known one renamed
    and nothing else of it changed."""
    owner, cid, _ = setup()
    asked = tally(monkeypatch, {"SCPItems": ITEMS})
    before = {p["id"]: p for p in doc_of(owner, cid)["dataset"]["products"]}["A"]
    j = save(owner, cid, tally_job("records:products", mapping={"fields": {"id": {"values": {"Tin White 1L": "A"}}}}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied" and row["summary"] == "3 products: 3 taken", row
    assert "<SVCURRENTCOMPANY>Kaveri Kitchenware</SVCURRENTCOMPANY>" in asked[0]
    assert "<TYPE>StockItem</TYPE>" in asked[0] and row["sample"].startswith("<ENVELOPE>")
    prods = {p["id"]: p for p in doc_of(owner, cid)["dataset"]["products"]}
    keep = ("type", "base_uom", "family")                             # its type, unit and family stay as here
    assert prods["A"]["name"] == "Tin White 1L"
    assert [prods["A"].get(f, "") for f in keep] == [before.get(f, "") if f != "base_uom" else before.get(f, "EA")
                                                     for f in keep]
    tumbler = prods["Steel-Tumbler-250-ml"]                           # the control character Tally wrote is gone
    assert (tumbler["name"], tumbler["type"], tumbler["base_uom"], tumbler["family"]) == \
        ("Steel Tumbler 250 ml", "FG", "Pcs", "Tumblers")
    assert prods["Old-Lid"]["family"] == ""                            # Tally's top group is no family
    # the same answer again changes nothing
    [again] = run(owner, cid, j["id"])
    assert again["status"] == "duplicate"


def test_tallys_debtors_and_creditors_become_customers_and_suppliers(monkeypatch):
    owner, cid, _ = setup()
    tally(monkeypatch, {"SCPParties": LEDGERS})
    j = save(owner, cid, tally_job("records:locations", mapping={"fields": {"id": {"values": {
        "Kumar Stores": "K", "Sharma Metals Pvt Ltd": "S"}}}}))
    t = client.post(f"/api/companies/{cid}/imports/{j['id']}/dry-run", headers=h(owner)).json()
    assert {"id", "name", "type", "address", "region", "tax_id"} <= set(t["columns"])
    assert [r["id"] for r in t["rows"]] == ["K", "Mehta-Traders", "S"]        # the cash ledger is no party
    [row] = run(owner, cid, j["id"])
    assert row["summary"] == "3 locations: 3 taken", row
    locs = {x["id"]: x for x in doc_of(owner, cid)["dataset"]["locations"]}
    assert (locs["K"]["address"], locs["K"]["tax_id"], locs["K"]["region"]) == \
        ("12 MG Road\nPune 411001", "27AAACK1234F1Z5", "")                   # a region kept here is not changed
    assert locs["S"]["type"] == "supplier" and locs["S"]["tax_id"] == "27AABCS9876K1Z2"
    assert (locs["Mehta-Traders"]["type"], locs["Mehta-Traders"]["region"]) == ("customer", "Gujarat")


def test_tallys_closing_stock_is_counted_at_the_place_named(monkeypatch):
    owner, cid, _ = setup()
    tally(monkeypatch, {"SCPItems": ITEMS})
    j = save(owner, cid, tally_job("stock", mapping={"fields": {"product": {"values": {"Tin White 1L": "A"}}}}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "partly", row
    items = {i["ref"]: i for i in row["items"]}
    # the first stock heard of is the opening balance (planning's 100 was never posted)
    assert items["P / A"]["message"] == "96 on hand: +96 posted (opening balance)", items
    assert items["P / Steel-Tumbler-250-ml"]["status"] == "refused"    # not a product here
    assert "P / Old-Lid" not in items                                  # Tally gave it no balance
    moves = doc_of(owner, cid)["dataset"]["movements"]
    assert [(m["product"], m["qty"]) for m in moves] == [("A", 96)]


def test_tallys_sales_orders_come_in_line_by_due_date_and_an_optional_voucher_is_not_read(monkeypatch):
    owner, cid, _ = setup()
    asked = tally(monkeypatch, {"SCPOrders": ORDERS})
    j = save(owner, cid, tally_job("orders", app={"company": "Kaveri Kitchenware", "days_back": 30},
                                   mapping={"fields": {"customer": {"values": {"Kumar Stores": "K"}},
                                                       "product": {"values": {"Tin White 1L": "A"}}}}))
    [row] = run(owner, cid, j["id"])
    assert row["summary"] == "1 order: 1 taken", row
    assert '$VoucherTypeName = "Sales Order"' in asked[0] and '<SVFROMDATE TYPE="Date">' in asked[0]
    [so] = [o for o in doc_of(owner, cid)["dataset"]["sales_orders"] if o["erp_ref"] == "SO/12"]
    assert (so["customer"], so["customer_ref"]) == ("K", "KS-PO-88")
    lines = [ln for ln in doc_of(owner, cid)["dataset"]["demand"] if ln["id"].startswith(so["id"] + "/")]
    assert sorted((ln["qty"], ln["date"], ln["price"]) for ln in lines) == [(4, "2026-01-15", 120), (6, "2026-01-08", 120)]


def test_tallys_errors_and_a_document_type_fail_the_run_with_its_words(monkeypatch):
    owner, cid, _ = setup()
    tally(monkeypatch, {"SCPItems": b"<ENVELOPE><BODY><DATA><LINEERROR>Could not find Company 'Kaveri'"
                                    b"</LINEERROR></DATA></BODY></ENVELOPE>"})
    j = save(owner, cid, tally_job("stock"))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "failed" and "Tally says: Could not find Company 'Kaveri'" in row["summary"]
    tally(monkeypatch, {"SCPItems": b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;'
                                    b"</ENVELOPE>"})
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "failed" and "document type" in row["summary"]


def test_a_purchase_order_goes_to_tally_as_a_voucher_once_and_a_refused_one_goes_again(monkeypatch):
    """Input: PO-00001 (100 B from S, due 8 January, 10 a unit), released here. Processing: a purchase order
    voucher numbered as here, Tally's names from the mapping. Output: Tally made it; it is PO-00001 in Tally and is
    not sent again until it changes."""
    owner, cid, _ = setup()
    asked = tally(monkeypatch, {"import": b"<RESPONSE><CREATED>0</CREATED><ERRORS>1</ERRORS><LINEERROR>Ledger "
                                          b"'Sharma Metals' does not exist!</LINEERROR></RESPONSE>"})
    j = save(owner, cid, tally_job("send:purchase_order", mapping={"fields": {
        "product": {"values": {"Steel sheet 1 mm": "B"}}}}))
    # a dry run builds the voucher and sends nothing
    t = client.post(f"/api/companies/{cid}/imports/{j['id']}/dry-run", headers=h(owner)).json()
    [m] = t["messages"]
    assert m["summary"] == "Dry run, nothing saved: 1 purchase order to Tally: 1 would go" and m["dry_run"]
    assert m["items"][0]["message"] == "would be made in Tally (Sharma Metals)"
    assert not any("Import Data" in a for a in asked)
    # Tally refuses it: nothing kept, it goes again next time
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "refused" and "Ledger 'Sharma Metals' does not exist!" in row["items"][0]["message"]
    assert doc_of(owner, cid)["dataset"]["purchase_orders"][0].get("erp_ref", "") == ""
    # the supplier translated, Tally takes it
    asked = tally(monkeypatch, {})
    r = client.put(f"/api/companies/{cid}/imports/{j['id']}", headers=h(owner), json=tally_job(
        "send:purchase_order", mapping={"fields": {"product": {"values": {"Steel sheet 1 mm": "B"}},
                                                   "supplier": {"values": {"*": "S", "Sharma Metals Pvt Ltd": "S"}}}}))
    assert r.status_code == 200, r.text
    ack, out = run(owner, cid, j["id"])
    assert (out["direction"], out["status"], out["summary"]) == ("out", "sent", "1 purchase order to Tally: 1 sent")
    assert out["items"][0]["message"] == "made in Tally as PO-00001"
    assert ack["kind"] == "acknowledgements" and ack["status"] == "applied"
    find, voucher = asked
    assert '$VoucherNumber = "PO-00001"' in find                   # made before and its answer lost? it was not
    for part in ('<VOUCHER VCHTYPE="Purchase Order" ACTION="Create">', "<DATE>20260102</DATE>",
                 "<VOUCHERNUMBER>PO-00001</VOUCHERNUMBER>", "<PARTYLEDGERNAME>Sharma Metals Pvt Ltd</PARTYLEDGERNAME>",
                 "<AMOUNT>1000.00</AMOUNT>", "<STOCKITEMNAME>Steel sheet 1 mm</STOCKITEMNAME>", "<RATE>10.00</RATE>",
                 "<ACTUALQTY>100</ACTUALQTY>", "<AMOUNT>-1000.00</AMOUNT>", "<ORDERDUEDATE>08-Jan-2026</ORDERDUEDATE>",
                 "<LEDGERNAME>Purchase</LEDGERNAME>", "<SVCURRENTCOMPANY>Kaveri Kitchenware</SVCURRENTCOMPANY>"):
        assert part in voucher, part
    assert doc_of(owner, cid)["dataset"]["purchase_orders"][0].get("erp_ref", "") == "PO-00001"
    [quiet] = run(owner, cid, j["id"])
    assert quiet["summary"] == "nothing to send: every purchase order is in Tally as it is here"
    # the quantity changed here: the voucher is altered by its number
    asked = tally(monkeypatch, {"import": TAKEN.replace(b"<CREATED>1", b"<CREATED>0").replace(b"<ALTERED>0",
                                                                                                b"<ALTERED>1")})
    c = doc_of(owner, cid)
    d = c["dataset"]
    d["receipts"][0]["qty"] = 120
    assert client.put(f"/api/companies/{cid}", headers=h(owner),
                      json={"dataset": d, "base_revision": c["meta"]["revision"]}).status_code == 200
    _ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "changed in Tally as PO-00001"
    [voucher] = asked
    assert 'TAGNAME="Voucher Number" TAGVALUE="PO-00001" ACTION="Alter"' in voucher
    assert "<ACTUALQTY>120</ACTUALQTY>" in voucher


def test_a_purchase_order_made_in_tally_before_its_answer_was_lost_is_altered_not_made_twice(monkeypatch):
    owner, cid, _ = setup()
    asked = tally(monkeypatch, {"SCPFind": envelope('<VOUCHER><VOUCHERNUMBER>PO-00001</VOUCHERNUMBER></VOUCHER>')})
    j = save(owner, cid, tally_job("send:purchase_order"))
    run(owner, cid, j["id"])
    assert 'TAGVALUE="PO-00001" ACTION="Alter"' in asked[1]


def cancel_po(owner: str, cid: str) -> None:
    """Cancel PO-00001's open lines as the Buying page does."""
    from scp.model import Dataset
    from scp.purchasing import cancel
    c = doc_of(owner, cid)
    ds, _ = cancel(Dataset.model_validate(c["dataset"]), "PO-00001", None)
    r = client.put(f"/api/companies/{cid}", headers=h(owner),
                   json={"dataset": ds.model_dump(mode="json"), "base_revision": c["meta"]["revision"]})
    assert r.status_code == 200, r.text


def test_an_order_cancelled_here_goes_to_tally_only_when_tally_has_it(monkeypatch):
    owner, cid, _ = setup()
    asked = tally(monkeypatch, {})
    j = save(owner, cid, tally_job("send:purchase_order"))
    cancel_po(owner, cid)                                   # cancelled before it ever went: nothing to cancel there
    [quiet] = run(owner, cid, j["id"])
    assert quiet["status"] == "unchanged" and asked == []


def test_an_order_tally_has_and_cancelled_here_is_cancelled_in_tally(monkeypatch):
    owner, cid, _ = setup()
    tally(monkeypatch, {})
    j = save(owner, cid, tally_job("send:purchase_order"))
    run(owner, cid, j["id"])
    cancel_po(owner, cid)
    asked = tally(monkeypatch, {"import": TAKEN.replace(b"<CREATED>1", b"<CREATED>0").replace(b"<CANCELLED>0",
                                                                                                b"<CANCELLED>1")})
    _ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "cancelled in Tally as PO-00001", out
    assert 'TAGVALUE="PO-00001" VCHTYPE="Purchase Order" ACTION="Cancel"' in asked[0]


def test_two_tally_items_kept_as_one_product_here_are_counted_together(monkeypatch):
    owner, cid, _ = setup()
    tally(monkeypatch, {"SCPItems": envelope(
        '<STOCKITEM NAME="Tin White 1L"><CLOSINGBALANCE>96 Nos</CLOSINGBALANCE></STOCKITEM>'
        '<STOCKITEM NAME="Tin White 1L (old label)"><CLOSINGBALANCE>4 Nos</CLOSINGBALANCE></STOCKITEM>')})
    j = save(owner, cid, tally_job("stock", mapping={"fields": {"product": {"values": {
        "Tin White 1L": "A", "Tin White 1L (old label)": "A"}}}}))
    [row] = run(owner, cid, j["id"])
    assert [(i["ref"], i["message"]) for i in row["items"]] == [("P / A", "100 on hand: +100 posted (opening balance)")]


def test_an_order_deleted_here_is_cancelled_in_tally(monkeypatch):
    owner, cid, _ = setup()
    tally(monkeypatch, {})
    j = save(owner, cid, tally_job("send:purchase_order"))
    run(owner, cid, j["id"])
    c = doc_of(owner, cid)
    d = c["dataset"]
    d["purchase_orders"], d["receipts"] = [], d["receipts"][1:]
    assert client.put(f"/api/companies/{cid}", headers=h(owner),
                      json={"dataset": d, "base_revision": c["meta"]["revision"]}).status_code == 200
    asked = tally(monkeypatch, {"import": TAKEN.replace(b"<CREATED>1", b"<CREATED>0").replace(b"<CANCELLED>0",
                                                                                                b"<CANCELLED>1")})
    ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "cancelled in Tally as PO-00001", out
    assert 'TAGVALUE="PO-00001" VCHTYPE="Purchase Order" ACTION="Cancel"' in asked[0]
    assert "closed its copy" in ack["items"][0]["message"]
    [quiet] = run(owner, cid, j["id"])
    assert quiet["status"] == "unchanged"


# ---- Zoho -------------------------------------------------------------------------------------------------------
SECRETS = {"client_id": "1000.ABC", "client_secret": "s3cret", "refresh_token": "1000.r3fresh"}
API = "https://www.zohoapis.in/inventory/v1/"


class Zoho:
    """Zoho's accounts server and Inventory API for organisation 60012345: what it was asked, by path."""

    def __init__(self, monkeypatch, lists: dict[str, list[dict]], details: dict[str, dict] | None = None,
                 per_page: int = 200) -> None:
        self.lists, self.details, self.per_page = lists, details or {}, per_page
        self.calls: list[tuple[str, str, dict, dict | None]] = []
        self.tokens = 0
        self.reject_token = ""
        self.made: list[dict] = []
        zoho._tokens.clear()
        monkeypatch.setattr(imports, "http", self)

    def __call__(self, method, url, headers, body):
        if url.startswith("https://accounts.zoho.in/oauth/v2/token"):
            form = parse_qs(body.decode())
            assert form["client_secret"] == ["s3cret"] and form["grant_type"] == ["refresh_token"]
            self.tokens += 1
            return 200, json.dumps({"access_token": f"tok{self.tokens}", "expires_in": 3600}).encode()
        assert url.startswith(API), url
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        assert q.pop("organization_id") == "60012345"
        path = u.path.removeprefix("/inventory/v1/")
        self.calls.append((method, path, q, json.loads(body) if body else None))
        if headers["Authorization"] == f"Zoho-oauthtoken {self.reject_token}":
            return 401, b'{"code": 57, "message": "You are not authorized to perform this operation"}'
        if method == "GET" and path in self.lists:
            rows, n = self.lists[path], int(q.get("page", 1))
            page = rows[(n - 1) * self.per_page: n * self.per_page]
            return 200, json.dumps({"code": 0, path.split("/")[-1]: page, "page_context": {
                "page": n, "has_more_page": n * self.per_page < len(rows)}}).encode()
        if method == "GET" and path in self.details:
            return 200, json.dumps({"code": 0, **self.details[path]}).encode()
        if method == "GET" and path == "purchaseorders":
            return 200, json.dumps({"code": 0, "purchaseorders": [
                p for p in self.made if p["purchaseorder_number"] == q.get("purchaseorder_number")]}).encode()
        if method in ("POST", "PUT") and path.startswith("purchaseorders"):
            data = json.loads(body) if body else {}
            if "status/cancelled" in path:
                return 200, b'{"code": 0, "message": "The purchase order has been cancelled."}'
            if data.get("vendor_id") == "bad":
                return 400, b'{"code": 1001, "message": "Vendor does not exist."}'
            po = {"purchaseorder_id": path.split("/")[-1] if method == "PUT" else "4600000000071",
                  "purchaseorder_number": data["purchaseorder_number"]}
            if method == "POST":
                self.made.append(po)
            return 201, json.dumps({"code": 0, "message": "done", "purchaseorder": po}).encode()
        return 404, b'{"code": 5, "message": "Invalid URL Passed"}'


ZITEMS = [{"item_id": "460001", "name": "Tin of white", "sku": "A", "unit": "pcs", "rate": 110, "stock_on_hand": 90,
           "item_type": "inventory", "product_type": "goods"},
          {"item_id": "460002", "name": "Steel sheet", "sku": "B", "unit": "kg", "stock_on_hand": 30,
           "item_type": "inventory", "product_type": "goods", "group_name": "Metals"},
          {"item_id": "460003", "name": "Pressure Cooker 3L", "sku": "", "unit": "pcs", "rate": 1450,
           "item_type": "inventory", "product_type": "goods", "stock_on_hand": 12},
          {"item_id": "460004", "name": "Installation", "sku": "SRV-1", "product_type": "service"}]


def zoho_job(kind: str, **kw) -> dict:
    return {"name": f"Zoho {kind}", "kind": kind, "source_type": "zoho", "source": "60012345", "every": "hour",
            "at": "00:15", "app": {"place": "P", "data_centre": "in"}, "secrets": SECRETS, **kw}


def test_zohos_items_are_read_page_by_page_with_one_token_and_become_products_and_stock(monkeypatch):
    owner, cid, _ = setup()
    z = Zoho(monkeypatch, {"items": ZITEMS}, per_page=2)
    j = save(owner, cid, zoho_job("records:products"))
    assert j["header_names"] == ["client_id", "client_secret", "refresh_token"] and "s3cret" not in json.dumps(j)
    [row] = run(owner, cid, j["id"])
    assert row["summary"] == "3 products: 3 taken", row
    assert [(c[1], c[2]["page"]) for c in z.calls] == [("items", "1"), ("items", "2")] and z.tokens == 1
    prods = {p["id"]: p for p in doc_of(owner, cid)["dataset"]["products"]}
    assert prods["A"]["price"] == 110 and prods["A"]["type"] != "service"
    cooker = prods["Pressure-Cooker-3L"]                               # no SKU: its name is its code
    assert (cooker["name"], cooker["base_uom"], cooker["price"], cooker["type"]) == ("Pressure Cooker 3L", "pcs", 1450, "FG")
    assert "SRV-1" not in prods                                        # a service is no product
    # stock: the same answer, read as what is on hand; the token is still good
    j = save(owner, cid, zoho_job("stock"))
    [row] = run(owner, cid, j["id"])
    assert z.tokens == 1
    items = {i["ref"]: i["status"] for i in row["items"]}
    assert items == {"P / A": "applied", "P / B": "applied", "P / Pressure-Cooker-3L": "applied"}
    moves = {m["product"]: m["qty"] for m in doc_of(owner, cid)["dataset"]["movements"]}
    assert moves["A"] == 90                                            # the opening balance: 90 in Zoho


def test_zohos_contacts_become_customers_and_suppliers(monkeypatch):
    owner, cid, _ = setup()
    Zoho(monkeypatch, {"contacts": [
        {"contact_id": "1", "contact_name": "Kumar Stores", "contact_type": "customer", "gst_no": "27AAACK1234F1Z5",
         "place_of_contact": "MH", "billing_address": {"address": "12 MG Road", "city": "Pune", "zip": "411001"}},
        {"contact_id": "2", "contact_name": "Sharma Metals", "contact_type": "vendor"},
        {"contact_id": "3", "contact_name": "Desai & Sons", "contact_type": "customer", "place_of_contact": "GJ"}]})
    j = save(owner, cid, zoho_job("records:locations", mapping={"fields": {"id": {"values": {
        "Kumar Stores": "K", "Sharma Metals": "S"}}}}))
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied", row
    locs = {x["id"]: x for x in doc_of(owner, cid)["dataset"]["locations"]}
    assert locs["K"]["address"] == "12 MG Road\nPune\n411001" and locs["K"]["tax_id"] == "27AAACK1234F1Z5"
    assert (locs["Desai-Sons"]["type"], locs["Desai-Sons"]["region"]) == ("customer", "GJ")


def test_zohos_sales_orders_changed_since_the_last_run_are_read_whole(monkeypatch):
    """Input: Zoho's sales orders, newest change first; each read whole for its lines. Processing: only orders
    changed since the last good run; a draft is not read, a void one cancels. Output: customer orders here."""
    owner, cid, _ = setup()
    heads = [{"salesorder_id": "71", "salesorder_number": "SO-00071", "status": "confirmed",
              "last_modified_time": "2026-10-15T10:00:00+0530"},
             {"salesorder_id": "72", "salesorder_number": "SO-00072", "status": "draft",
              "last_modified_time": "2026-10-15T09:00:00+0530"},
             {"salesorder_id": "70", "salesorder_number": "SO-00070", "status": "confirmed",
              "last_modified_time": "2026-10-01T09:00:00+0530"},
             {"salesorder_id": "69", "salesorder_number": "SO-00069", "status": "confirmed",
              "last_modified_time": "2026-09-30T09:00:00+0530"}]
    detail = {"salesorder_id": "71", "salesorder_number": "SO-00071", "status": "confirmed", "date": "2026-01-03",
              "shipment_date": "2026-01-09", "customer_name": "Kumar Stores", "reference_number": "KS-91",
              "line_items": [{"sku": "A", "name": "Tin of white", "quantity": 8, "rate": 105.0}]}
    z = Zoho(monkeypatch, {"salesorders": heads}, {"salesorders/71": {"salesorder": detail}}, per_page=1)
    j = save(owner, cid, zoho_job("orders", mapping={"fields": {"customer": {"values": {"Kumar Stores": "K"}}}}))
    with get_store_cursor(j["id"], "2026-10-10T00:00:00+00:00"):
        [row] = run(owner, cid, j["id"])
    assert row["summary"] == "1 order: 1 taken", row
    # page by page, newest first, until a page with one older than the last run: the rest are not read
    assert [(c[1], c[2].get("page")) for c in z.calls] == [("salesorders", "1"), ("salesorders", "2"),
                                                           ("salesorders", "3"), ("salesorders/71", None)]
    assert z.calls[0][2]["sort_column"] == "last_modified_time" and z.calls[0][2]["sort_order"] == "D"
    [so] = [o for o in doc_of(owner, cid)["dataset"]["sales_orders"] if o["erp_ref"] == "SO-00071"]
    assert (so["customer"], so["customer_ref"]) == ("K", "KS-91")
    # voided in Zoho: cancelled here
    heads[0]["last_modified_time"] = "2026-10-16T10:00:00+0530"
    z.details["salesorders/71"]["salesorder"] = {**detail, "status": "void"}
    with get_store_cursor(j["id"], "2026-10-15T00:00:00+00:00"):
        [row] = run(owner, cid, j["id"])
    assert row["status"] == "applied" and "cancel" in row["items"][0]["message"].lower(), row


class get_store_cursor:
    """Set an import's last good run (the time Zoho's changes are read from)."""

    def __init__(self, jid: str, at: str) -> None:
        self.jid, self.at = jid, at

    def __enter__(self) -> None:
        from scp.companies import get_companies
        c = get_companies()
        with c.lock:
            c.db.execute("UPDATE import_jobs SET cursor = ? WHERE id = ?", (self.at, self.jid))

    def __exit__(self, *exc) -> None:
        return None


def test_a_purchase_order_goes_to_zoho_with_its_item_and_vendor_ids_and_changes_are_updates(monkeypatch):
    owner, cid, _ = setup()
    z = Zoho(monkeypatch, {"items": ZITEMS, "contacts": [{"contact_id": "9001", "contact_name": "Sharma Metals",
                                                          "contact_type": "vendor"}]})
    j = save(owner, cid, zoho_job("send:purchase_order"))
    ack, out = run(owner, cid, j["id"])
    assert out["items"][0]["message"] == "made in Zoho Inventory as 4600000000071", out
    method, path, q, body = z.calls[-1]
    assert (method, path, q) == ("POST", "purchaseorders", {"ignore_auto_number_generation": "true"})
    assert body == {"vendor_id": "9001", "purchaseorder_number": "PO-00001", "reference_number": "PO-00001",
                    "date": "2026-01-02", "delivery_date": "2026-01-08",
                    "line_items": [{"item_id": "460002", "quantity": 100, "rate": 10}]}
    assert doc_of(owner, cid)["dataset"]["purchase_orders"][0].get("erp_ref", "") == "4600000000071"
    # changed here: updated by Zoho's ID
    c = doc_of(owner, cid)
    d = c["dataset"]
    d["receipts"][0]["due_date"] = "2026-01-12"
    client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": c["meta"]["revision"]})
    _ack, out = run(owner, cid, j["id"])
    method, path, _q, body = z.calls[-1]
    assert (method, path, body["delivery_date"]) == ("PUT", "purchaseorders/4600000000071", "2026-01-12")
    assert out["items"][0]["message"] == "changed in Zoho Inventory as 4600000000071"


def test_a_purchase_order_zoho_made_before_its_answer_was_lost_is_updated_not_made_twice(monkeypatch):
    owner, cid, _ = setup()
    z = Zoho(monkeypatch, {"items": ZITEMS, "contacts": [{"contact_id": "9001", "contact_name": "Sharma Metals",
                                                          "contact_type": "vendor"}]})
    z.made.append({"purchaseorder_id": "4600000000055", "purchaseorder_number": "PO-00001"})
    j = save(owner, cid, zoho_job("send:purchase_order"))
    _ack, out = run(owner, cid, j["id"])
    assert z.calls[-1][:2] == ("PUT", "purchaseorders/4600000000055")
    assert out["items"][0]["message"] == "made in Zoho Inventory as 4600000000055"


def test_zoho_without_the_vendor_or_item_refuses_the_order_with_what_to_do(monkeypatch):
    owner, cid, _ = setup()
    Zoho(monkeypatch, {"items": ZITEMS, "contacts": []})
    j = save(owner, cid, zoho_job("send:purchase_order"))
    [out] = run(owner, cid, j["id"])
    assert out["status"] == "refused"
    assert out["items"][0]["message"] == "Zoho has no vendor 'Sharma Metals': translate the supplier, or add it in Zoho"
    Zoho(monkeypatch, {"items": [], "contacts": [{"contact_id": "9001", "contact_name": "Sharma Metals",
                                                  "contact_type": "vendor"}]})
    [out] = run(owner, cid, j["id"])
    assert "Zoho has no item 'B'" in out["items"][0]["message"]


def test_a_token_zoho_no_longer_takes_is_renewed_once_and_zohos_errors_are_its_words(monkeypatch):
    owner, cid, _ = setup()
    z = Zoho(monkeypatch, {"items": ZITEMS})
    j = save(owner, cid, zoho_job("stock"))
    run(owner, cid, j["id"])
    assert z.tokens == 1
    z.reject_token = "tok1"                                    # Zoho revoked it before the hour was up
    z.lists["items"] = ZITEMS[:1]
    [row] = run(owner, cid, j["id"])
    assert z.tokens == 2 and row["status"] != "failed", row
    z.reject_token = "tok2"
    monkeypatch.setattr(z, "tokens", 1)                         # the next token is tok2 again: still refused
    [row] = run(owner, cid, j["id"])
    assert row["status"] == "failed" and "You are not authorized" in row["summary"], row


def test_a_connector_says_what_it_needs_and_keeps_its_secrets_for_its_own_organisation(monkeypatch):
    owner, cid, _ = setup()
    url = f"/api/companies/{cid}/imports"

    def refused(body: dict) -> str:
        r = client.post(url, headers=h(owner), json=body)
        assert r.status_code == 422, r.text
        return r.json()["detail"]
    assert "client secret, refresh token" in refused(zoho_job("orders", secrets={"client_id": "x"}))
    assert "organisation ID is a number" in refused(zoho_job("orders", source="my-org"))
    assert "name the place" in refused(zoho_job("stock", app={}))
    assert "Tally gives" in refused(tally_job("postings"))
    assert "character Tally's request cannot carry" in refused(tally_job("stock", app={"company": 'K"', "place": "P"}))
    assert "is not a field of" in refused(tally_job("send:purchase_order", mapping={"fields": {"qty": {}}}))
    j = save(owner, cid, zoho_job("orders"))
    # changed with the secrets left empty: kept
    r = client.put(f"{url}/{j['id']}", headers=h(owner), json=zoho_job(
        "orders", name="Zoho orders daily", every="day", secrets={"client_id": "", "client_secret": "",
                                                                 "refresh_token": ""}))
    assert r.status_code == 200, r.text
    from scp.companies import get_companies
    kept = get_companies().db.execute("SELECT headers FROM import_jobs WHERE id = ?", (j["id"],)).fetchone()[0]
    assert json.loads(kept) == SECRETS
    # another organisation: they are not carried to it
    assert "client id, client secret, refresh token" in client.put(
        f"{url}/{j['id']}", headers=h(owner), json=zoho_job("orders", source="60099999", secrets=None)).json()["detail"]
    jobs = client.get(url, headers=h(owner)).json()
    assert jobs["apps"]["tally"][-1] == "send:purchase_order" and jobs["secrets"]["zoho"] == list(SECRETS)
    assert jobs["fields"]["send:purchase_order"] == ["product", "supplier", "location"]


@pytest.mark.parametrize("sample", [ORDERS.decode()])
def test_a_pasted_tally_answer_is_tried_before_the_connector_is_saved(monkeypatch, sample):
    owner, cid, _ = setup()
    r = client.post(f"/api/companies/{cid}/imports/try", headers=h(owner), json={
        "job": tally_job("orders", mapping={"fields": {"customer": {"values": {"Kumar Stores": "K"}},
                                                       "product": {"values": {"Tin White 1L": "A"}}}}),
        "content": sample})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["messages"][0]["summary"] == "Dry run, nothing saved: 1 order: 1 taken"
    assert t["rows"][0]["customer"] == "K" and len(t["rows"][0]["lines"]) == 2
    assert {"number", "customer", "product", "qty", "date", "price"} <= set(t["columns"])
