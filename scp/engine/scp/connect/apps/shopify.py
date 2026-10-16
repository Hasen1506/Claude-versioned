"""Shopify (ENTERPRISE_PLAN 3.3): the shop's Admin API (GraphQL) with the access token of a custom app.

The shop's address (``my-shop.myshopify.com``) is the job's source and the custom app's Admin API access token
(``shpat_…``, with the scopes ``read_products``, ``read_inventory``, ``read_locations``, ``read_orders`` and, for
fulfilments, ``read_fulfillments``) is kept with the job and never shown again; it goes in Shopify's own header,
``X-Shopify-Access-Token`` (N205). Each answer names whether more follow and where (``pageInfo``); a throttled
call is asked again once. A job reads:

* product variants as products: the SKU, else the product's title (and the variant's, when it has more than one),
  as the code; the product type as a new product's family; the variant's price as its price;
* the shop's locations as places here (a warehouse, a new one, with its address);
* stock on hand at each location, per variant tracked there: a location is the place of the same name here, or the
  one the mapping translates it to, or the place the job names when it is not translated;
* orders changed since the last good run (newest first): each order's name without its ``#`` is the order number,
  the customer here the job names (a shop's buyers are not places here; the buyer's name is the order's note), each
  line's quantity what is left after edits and refunds, and a cancelled order cancelled here;
* fulfilments (``postings``) of the same orders as deliveries of their lines, each taken once.

Shopify keeps no purchase or production orders, so nothing is sent to it.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from typing import Any

from . import AppSettings, today

KINDS = ["records:products", "records:locations", "stock", "orders", "postings"]
SECRETS = ["access_token"]
PLACES = True                   # stock is given by location
SHOP = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com$")
MAX_PAGES = 200
#: tests replace it so a throttled call is asked again at once
pause = time.sleep

PRODUCTS = """query($after: String) { productVariants(first: 100, after: $after) {
  nodes { id sku title price inventoryItem { tracked } product { title productType status } }
  pageInfo { hasNextPage endCursor } } }"""
LOCATIONS = """query($after: String) { locations(first: 100, after: $after) {
  nodes { id name isActive address { address1 address2 city province zip country } }
  pageInfo { hasNextPage endCursor } } }"""
STOCK = """query($after: String) { inventoryItems(first: 40, after: $after) {
  nodes { sku tracked variant { sku title product { title } }
    inventoryLevels(first: 20) { nodes { location { name } quantities(names: ["on_hand"]) { name quantity } }
      pageInfo { hasNextPage } } }
  pageInfo { hasNextPage endCursor } } }"""
ORDERS = """query($after: String, $q: String) { orders(first: 10, after: $after, query: $q, sortKey: UPDATED_AT,
  reverse: true) { nodes { name createdAt cancelledAt note customer { displayName }
    lineItems(first: 50) { nodes { sku name currentQuantity variant { sku title product { title } }
      originalUnitPriceSet { shopMoney { amount } } } pageInfo { hasNextPage } } }
  pageInfo { hasNextPage endCursor } } }"""
FULFILMENTS = """query($after: String, $q: String) { orders(first: 5, after: $after, query: $q, sortKey: UPDATED_AT,
  reverse: true) { nodes { name lineItems(first: 30) { nodes { id currentQuantity } pageInfo { hasNextPage } }
    fulfillments(first: 5) { id createdAt status fulfillmentLineItems(first: 30) { nodes { quantity lineItem { id } } } } }
  pageInfo { hasNextPage endCursor } } }"""


def shop(source: str) -> str:
    """The shop's host, from what was given (``my-shop.myshopify.com``, with or without https:// and a path)."""
    s = source.strip().lower()
    s = re.sub(r"^https?://", "", s).split("/", 1)[0]
    return s


def check(source: str, s: AppSettings, secrets: dict[str, str], kind: str = "") -> None:
    if not SHOP.match(shop(source)):
        raise ValueError("Shopify's shop is its myshopify.com address (my-shop.myshopify.com: Settings → Domains)")
    if not (secrets.get("access_token") or "").strip():
        raise ValueError("Shopify needs the Admin API access token of a custom app (Settings → Apps and sales "
                         "channels → Develop apps)")
    if kind == "orders" and not s.customer:
        raise ValueError("Shopify's orders go to a customer here (the online shop): name it")


def same(old_source: str, old: AppSettings, source: str, new: AppSettings) -> bool:
    return shop(old_source) == shop(source)


class Session:
    """Calls to one shop."""

    def __init__(self, job: dict, s: AppSettings, secrets: dict[str, str]) -> None:
        check(job["source"], s, secrets)
        self.url = f"https://{shop(job['source'])}/admin/api/{s.api_version}/graphql.json"
        self.token = secrets["access_token"].strip()
        self.calls = 0

    def query(self, q: str, variables: dict[str, Any]) -> dict[str, Any]:
        from .. import imports
        body = json.dumps({"query": q, "variables": variables}).encode()
        for attempt in (0, 1):
            self.calls += 1
            status, raw = imports.http("POST", self.url, {"X-Shopify-Access-Token": self.token,
                                                          "Content-Type": "application/json"}, body)
            data = _json(raw)
            errors = data.get("errors")
            throttled = status == 429 or (isinstance(errors, list) and any(
                (e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors if isinstance(e, dict)))
            if throttled and attempt == 0:
                pause(2)
                continue
            if status in (401, 403):
                raise ValueError(f"Shopify does not take the access token ({status}): check it, and the app's "
                                 "Admin API scopes")
            if status >= 400 or errors:
                raise ValueError(f"Shopify says: {_said(errors) or status}")
            return data.get("data") or {}
        raise ValueError("Shopify is busy (throttled): the next run reads it")

    def nodes(self, q: str, key: str, variables: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Every node of a connection, page by page."""
        out: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(MAX_PAGES):
            conn = self.query(q, {**(variables or {}), "after": after}).get(key) or {}
            out += [n for n in conn.get("nodes") or [] if isinstance(n, dict)]
            info = conn.get("pageInfo") or {}
            if not info.get("hasNextPage") or not info.get("endCursor"):
                return out
            after = info["endCursor"]
        raise ValueError(f"Shopify has more than {MAX_PAGES} pages of {key}: read only what changed")


def _said(errors: Any) -> str:
    if isinstance(errors, list):
        return "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)[:300]
    return str(errors or "")[:300]


def _json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
    except json.JSONDecodeError:
        raise ValueError(f"Shopify's answer is not JSON: {raw[:120]!r}") from None
    return data if isinstance(data, dict) else {}


def _when(v: Any) -> dt.datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        t = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def _since(job: dict, s: AppSettings) -> str:
    t = _when(job.get("cursor") or "") or dt.datetime.combine(today() - dt.timedelta(days=s.days_back), dt.time(),
                                                               dt.UTC)
    return f"updated_at:>'{t.astimezone(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}'"


def read(job: dict, s: AppSettings, secrets: dict[str, str], headers: dict[str, str]) -> bytes:
    z = Session(job, s, secrets)
    kind = job["kind"]
    if kind == "records:products":
        return json.dumps({"productVariants": z.nodes(PRODUCTS, "productVariants")}).encode()
    if kind == "records:locations":
        return json.dumps({"locations": z.nodes(LOCATIONS, "locations")}).encode()
    if kind == "stock":
        return json.dumps({"inventoryItems": z.nodes(STOCK, "inventoryItems")}).encode()
    if kind == "orders":
        return json.dumps({"orders": z.nodes(ORDERS, "orders", {"q": _since(job, s)})}).encode()
    if kind == "postings":
        return json.dumps({"orders": z.nodes(FULFILMENTS, "orders", {"q": _since(job, s)})}).encode()
    raise ValueError(f"Shopify gives no {kind}")


# ------------------------------------------------------------------------------------------------ reading
def code(sku: Any, product: Any, variant: Any) -> str:
    """A variant's code here: its SKU, else its product's title (with the variant's when there are several)."""
    if str(sku or "").strip():
        return str(sku).strip()
    p, v = str(product or "").strip(), str(variant or "").strip()
    return p if not v or v == "Default Title" else f"{p} {v}"


def _of(x: dict[str, Any]) -> str:
    v = x.get("variant") or {}
    return code(v.get("sku") or x.get("sku"), (v.get("product") or {}).get("title") or x.get("name"),
                v.get("title") if v else "")


def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    got = data.get(key)
    if not isinstance(got, list):
        raise ValueError(f"Shopify's answer has no {key}")
    return [x for x in got if isinstance(x, dict)]


def _number(name: Any) -> str:
    return str(name or "").strip().lstrip("#")


def _lines(o: dict[str, Any]) -> list[dict[str, Any]]:
    conn = o.get("lineItems") or {}
    if (conn.get("pageInfo") or {}).get("hasNextPage"):
        raise ValueError(f"Shopify order {o.get('name')} has more lines than are read at once")
    return [ln for ln in conn.get("nodes") or [] if isinstance(ln, dict)]


def rows(kind: str, raw: bytes, s: AppSettings) -> list[dict[str, Any]]:
    data = _json(raw)
    out: list[dict[str, Any]] = []
    if kind == "records:products":
        for v in _list(data, "productVariants"):
            p = v.get("product") or {}
            if str(p.get("status") or "ACTIVE") != "ACTIVE":
                continue
            c = code(v.get("sku"), p.get("title"), v.get("title"))
            if not c:
                continue
            title = str(p.get("title") or c)
            r: dict[str, Any] = {"id": c, "name": title if v.get("title") in (None, "", "Default Title")
                                 else f"{title} {v['title']}", "base_uom": "Pcs"}
            if p.get("productType"):
                r["family"] = str(p["productType"])
            try:
                if float(v.get("price") or 0) > 0:
                    r["price"] = float(v["price"])
            except (TypeError, ValueError):
                pass
            out.append(r)
    elif kind == "records:locations":
        for loc in _list(data, "locations"):
            name = str(loc.get("name") or "").strip()
            if not name or loc.get("isActive") is False:
                continue
            r = {"id": name, "name": name, "type": "warehouse"}
            a = loc.get("address") or {}
            lines = [str(a.get(k) or "").strip() for k in ("address1", "address2", "city", "province", "zip", "country")]
            if any(lines):
                r["address"] = "\n".join(x for x in lines if x)[:400]
            out.append(r)
    elif kind == "stock":
        for it in _list(data, "inventoryItems"):
            if not it.get("tracked"):
                continue
            c = _of(it)
            levels = it.get("inventoryLevels") or {}
            if (levels.get("pageInfo") or {}).get("hasNextPage"):
                raise ValueError(f"Shopify keeps {c} at more locations than are read at once")
            for lv in levels.get("nodes") or []:
                q = next((x.get("quantity") for x in lv.get("quantities") or [] if x.get("name") == "on_hand"), None)
                if c and isinstance(q, (int, float)):
                    out.append({"location": str((lv.get("location") or {}).get("name") or ""), "product": c,
                                "qty": float(max(q, 0))})
    elif kind == "orders":
        for o in _list(data, "orders"):
            made = _when(o.get("createdAt"))
            head: dict[str, Any] = {"number": _number(o.get("name")), "customer": s.customer,
                                    "customer_ref": str(o.get("name") or "")[:64]}
            if made:
                head["order_date"] = made.date().isoformat()
            buyer = str((o.get("customer") or {}).get("displayName") or "").strip()
            note = ": ".join(x for x in (buyer, str(o.get("note") or "").strip()) if x)
            if note:
                head["note"] = note[:400]
            if o.get("cancelledAt"):
                head["cancelled"] = True
            lines = [ln for ln in _lines(o) if (ln.get("currentQuantity") or 0) > 0]
            if not lines:
                out.append(head)
            for ln in lines:
                r = {**head, "product": _of(ln), "qty": ln["currentQuantity"], "date": head.get("order_date")}
                price = ((ln.get("originalUnitPriceSet") or {}).get("shopMoney") or {}).get("amount")
                if price not in (None, ""):
                    r["price"] = float(price)
                out.append(r)
    elif kind == "postings":
        for o in _list(data, "orders"):
            number = _number(o.get("name"))
            # the order's lines here are its lines left after edits, numbered 10, 20, … as they came
            item = {ln.get("id"): 10 * (i + 1) for i, ln in enumerate(
                ln for ln in _lines(o) if (ln.get("currentQuantity") or 0) > 0)}
            for f in o.get("fulfillments") or []:
                if not isinstance(f, dict) or f.get("status") != "SUCCESS":
                    continue
                when = _when(f.get("createdAt"))
                fid = str(f.get("id") or "").rsplit("/", 1)[-1]
                for fl in (f.get("fulfillmentLineItems") or {}).get("nodes") or []:
                    n = item.get((fl.get("lineItem") or {}).get("id"))
                    if n is None or not (fl.get("quantity") or 0) > 0:
                        continue
                    r = {"ref": f"shopify-{fid}/{n}", "action": "deliver", "order": f"{number}/{n}",
                         "qty": fl["quantity"], "note": f"Shopify fulfilment of {o.get('name')}"}
                    if when:
                        r["date"] = when.date().isoformat()
                    out.append(r)
    return out


__all__ = ["Session", "check", "read", "rows"]
