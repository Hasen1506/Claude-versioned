"""Zoho Inventory (ENTERPRISE_PLAN 3.2): its REST API (``/inventory/v1``) with an OAuth refresh token.

The organisation's ID is the job's source, its data centre (zoho.in, zoho.com, zoho.eu, …) a setting, and a *self
client* made in Zoho's API console gives the client ID, client secret and a refresh token (scope
``ZohoInventory.FullAccess.all``, or the read scopes and ``ZohoInventory.purchaseorders.CREATE``/``UPDATE`` for what
it does), kept with the job and never shown again. Each run asks Zoho's accounts server for an access token (kept for
the hour Zoho gives it), then reads page by page (200 a page, ``page_context.has_more_page``):

* items as products (the SKU, else the name, as the code; the unit and the item group of a new product; the selling
  rate as its price), and the stock on hand of each tracked item at the place the job names;
* contacts as customers and suppliers (vendors), with the GSTIN and, for a new one, the place of supply as region;
* sales orders changed since the last good run (newest first, until one older), each read whole for its lines: the
  expected shipment date is each line's date, a void order cancels it here, a draft is not read;

and makes purchase orders numbered as the order here (Zoho's own number is switched off for them): a changed order
is updated, a cancelled one cancelled. Lines carry Zoho's item ID, found by the SKU or the name, and the vendor's
contact ID, found by its name; the earliest line date is the order's delivery date (Zoho keeps one an order).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any
from urllib.parse import quote, urlencode

from . import AppSettings, settings_of, slug, today

KINDS = ["records:products", "records:locations", "stock", "orders", "send:purchase_order"]
SECRETS = ["client_id", "client_secret", "refresh_token"]
ACCOUNTS = {"in": "https://accounts.zoho.in", "com": "https://accounts.zoho.com", "eu": "https://accounts.zoho.eu",
            "com.au": "https://accounts.zoho.com.au", "jp": "https://accounts.zoho.jp",
            "ca": "https://accounts.zohocloud.ca", "sa": "https://accounts.zoho.sa"}
API = {"in": "https://www.zohoapis.in", "com": "https://www.zohoapis.com", "eu": "https://www.zohoapis.eu",
       "com.au": "https://www.zohoapis.com.au", "jp": "https://www.zohoapis.jp", "ca": "https://www.zohoapis.ca",
       "sa": "https://www.zohoapis.sa"}
PER_PAGE = 200
MAX_PAGES = 100                 # 20,000 records of a kind
MAX_ORDERS = 500                # sales orders read whole in one run
_tokens: dict[str, tuple[str, float]] = {}


def check(source: str, s: AppSettings, secrets: dict[str, str], kind: str = "") -> None:
    if not source.strip().isdigit():
        raise ValueError("Zoho's organisation ID is a number (Settings → Organisation profile)")
    missing = [k.replace("_", " ") for k in SECRETS if not (secrets.get(k) or "").strip()]
    if missing:
        raise ValueError(f"Zoho needs the {', '.join(missing)} of a self client (api-console.zoho.{s.data_centre})")


def same(old_source: str, old: AppSettings, source: str, new: AppSettings) -> bool:
    return old_source.strip() == source.strip() and old.data_centre == new.data_centre


class Session:
    """Calls to one organisation, with a token refreshed when Zoho no longer takes it."""

    def __init__(self, job: dict, s: AppSettings, secrets: dict[str, str]) -> None:
        check(job["source"], s, secrets)
        self.org, self.s, self.secrets = job["source"].strip(), s, secrets
        self.calls = 0

    def _key(self) -> str:
        return hashlib.sha256("|".join([self.s.data_centre, self.secrets["client_id"],
                                        self.secrets["refresh_token"]]).encode()).hexdigest()

    def token(self, fresh: bool = False) -> str:
        from .. import imports
        k = self._key()
        if not fresh and k in _tokens and _tokens[k][1] > time.monotonic():
            return _tokens[k][0]
        body = urlencode({"refresh_token": self.secrets["refresh_token"], "client_id": self.secrets["client_id"],
                          "client_secret": self.secrets["client_secret"], "grant_type": "refresh_token"}).encode()
        status, raw = imports.http("POST", f"{ACCOUNTS[self.s.data_centre]}/oauth/v2/token",
                                   {"Content-Type": "application/x-www-form-urlencoded"}, body)
        data = _json(raw)
        if status >= 400 or not data.get("access_token"):
            raise ValueError(f"Zoho gave no access token: {data.get('error') or status} (check the client ID, the "
                             f"secret, the refresh token and the data centre, zoho.{self.s.data_centre})")
        _tokens[k] = (data["access_token"], time.monotonic() + max(60, int(data.get("expires_in") or 3600) - 120))
        return data["access_token"]

    def call(self, method: str, path: str, params: dict[str, Any] | None = None, body: Any = None) -> dict[str, Any]:
        from .. import imports
        url = (f"{API[self.s.data_centre]}/inventory/v1/{path}?"
               + urlencode({"organization_id": self.org, **(params or {})}))
        payload = json.dumps(body).encode() if body is not None else None
        for attempt in (0, 1):
            headers = {"Authorization": f"Zoho-oauthtoken {self.token(fresh=attempt == 1)}"}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            self.calls += 1
            status, raw = imports.http(method, url, headers, payload)
            if status == 401 and attempt == 0:
                continue                                         # the token ran out early: one fresh one
            data = _json(raw)
            if status >= 400 or data.get("code") not in (0, None):
                raise ValueError(f"Zoho says: {data.get('message') or status} (code {data.get('code', status)})")
            return data
        raise ValueError("Zoho does not take the access token")   # pragma: no cover - the loop returns or raises

    def pages(self, path: str, key: str, params: dict[str, Any] | None = None,
              older: dt.datetime | None = None) -> list[dict[str, Any]]:
        """Every record of a list; ``older``: newest first, until a page has none changed after it."""
        out: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            data = self.call("GET", path, {**(params or {}), "page": page, "per_page": PER_PAGE})
            got = data.get(key) or []
            if older is not None:
                newer = [r for r in got if (_when(r.get("last_modified_time")) or older) > older]
                out += newer
                if len(newer) < len(got):
                    return out
            else:
                out += got
            if not (data.get("page_context") or {}).get("has_more_page"):
                return out
        raise ValueError(f"Zoho has more than {MAX_PAGES * PER_PAGE} {key}: read only what changed")


def _json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
    except json.JSONDecodeError:
        raise ValueError(f"Zoho's answer is not JSON: {raw[:120]!r}") from None
    return data if isinstance(data, dict) else {}


def _when(v: Any) -> dt.datetime | None:
    """Zoho's 2026-10-14T10:22:31+0530 (or an ISO time with a colon in the offset)."""
    if not isinstance(v, str) or not v:
        return None
    for f in ("%Y-%m-%dT%H:%M:%S%z",):
        try:
            return dt.datetime.strptime(v, f)
        except ValueError:
            pass
    try:
        t = dt.datetime.fromisoformat(v)
        return t if t.tzinfo else t.replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def read(job: dict, s: AppSettings, secrets: dict[str, str], headers: dict[str, str]) -> bytes:
    z = Session(job, s, secrets)
    kind = job["kind"]
    if kind in ("records:products", "stock"):
        return json.dumps({"items": z.pages("items", "items", {"filter_by": "Status.Active"})}).encode()
    if kind == "records:locations":
        return json.dumps({"contacts": z.pages("contacts", "contacts", {"filter_by": "Status.Active"})}).encode()
    if kind == "orders":
        since = _when(job.get("cursor") or "") or dt.datetime.combine(today() - dt.timedelta(days=s.days_back),
                                                                     dt.time(), dt.UTC)
        heads = z.pages("salesorders", "salesorders", {"sort_column": "last_modified_time", "sort_order": "D"},
                        older=since)
        heads = [h for h in heads if h.get("status") != "draft"]
        if len(heads) > MAX_ORDERS:
            raise ValueError(f"{len(heads)} sales orders changed in Zoho since the last run, more than {MAX_ORDERS} "
                             "read whole at once: run the import more often")
        whole = [z.call("GET", f"salesorders/{quote(str(h['salesorder_id']), safe='')}").get("salesorder") or h
                 for h in heads]
        return json.dumps({"salesorders": whole}).encode()
    raise ValueError(f"Zoho gives no {kind}")


# ------------------------------------------------------------------------------------------------ reading
def _list(data: dict[str, Any], key: str, one: str) -> list[dict[str, Any]]:
    got = data.get(key)
    if got is None and isinstance(data.get(one), dict):
        got = [data[one]]
    if not isinstance(got, list):
        raise ValueError(f"Zoho's answer has no {key}")
    return [x for x in got if isinstance(x, dict)]


def code(item: dict[str, Any]) -> str:
    """An item's code here: its SKU, else its name."""
    return str(item.get("sku") or item.get("name") or "").strip()


def rows(kind: str, raw: bytes, s: AppSettings) -> list[dict[str, Any]]:
    data = _json(raw)
    out: list[dict[str, Any]] = []
    if kind in ("records:products", "stock"):
        for it in _list(data, "items", "item"):
            if it.get("product_type") == "service" or not code(it):
                continue
            if kind == "stock":
                if it.get("item_type", "inventory") == "inventory" and it.get("stock_on_hand") is not None:
                    out.append({"product": code(it), "qty": float(it["stock_on_hand"])})
                continue
            r: dict[str, Any] = {"id": code(it), "name": str(it.get("name") or code(it))}
            if it.get("unit"):
                r["base_uom"] = str(it["unit"])[:12]
            if it.get("group_name"):
                r["family"] = str(it["group_name"])
            if isinstance(it.get("rate"), (int, float)) and it["rate"] > 0:
                r["price"] = float(it["rate"])
            out.append(r)
    elif kind == "records:locations":
        for ct in _list(data, "contacts", "contact"):
            t = {"customer": "customer", "vendor": "supplier"}.get(str(ct.get("contact_type")))
            name = str(ct.get("contact_name") or "").strip()
            if not t or not name:
                continue
            r = {"id": name, "name": name, "type": t}
            if ct.get("gst_no"):
                r["tax_id"] = str(ct["gst_no"])[:40]
            if ct.get("place_of_contact"):
                r["region"] = str(ct["place_of_contact"])
            a = ct.get("billing_address")
            if isinstance(a, dict):
                lines = [str(a.get(k) or "").strip() for k in ("attention", "address", "street2", "city", "state",
                                                                "zip", "country")]
                if any(lines):
                    r["address"] = "\n".join(x for x in lines if x)[:400]
            out.append(r)
    elif kind == "orders":
        for so in _list(data, "salesorders", "salesorder"):
            if so.get("status") == "draft":
                continue
            head: dict[str, Any] = {"number": str(so.get("salesorder_number") or ""),
                                    "customer": str(so.get("customer_name") or "")}
            if so.get("date"):
                head["order_date"] = so["date"]
            if so.get("reference_number"):
                head["customer_ref"] = str(so["reference_number"])[:64]
            if so.get("notes"):
                head["note"] = str(so["notes"])[:400]
            if so.get("status") == "void":
                head["cancelled"] = True
            lines = so.get("line_items") or []
            if not lines:
                out.append(head)
            for ln in lines:
                r = {**head, "product": code(ln), "qty": ln.get("quantity"),
                     "date": so.get("shipment_date") or so.get("date")}
                if ln.get("rate") is not None:
                    r["price"] = ln["rate"]
                out.append(r)
    return out


# ------------------------------------------------------------------------------------------------ sending
class Sender:
    """Purchase orders to Zoho: each one made, updated or cancelled by its own call, and Zoho's ID kept."""

    def __init__(self, job: dict, s: AppSettings, secrets: dict[str, str], headers: dict[str, str]) -> None:
        self.z = Session(job, s, secrets)
        self._items: dict[str, str] | None = None
        self._vendors: dict[str, str] | None = None

    def codes(self, ds: Any, kind: str, here: str) -> str:
        if kind == "supplier":
            loc = ds.location_by_id.get(here)
            return (getattr(loc, "name", "") or here) if loc else here
        return here

    def items(self) -> dict[str, str]:
        if self._items is None:
            self._items = {}
            for it in self.z.pages("items", "items", {"filter_by": "Status.Active"}):
                for k in (str(it.get("sku") or ""), slug(it.get("name")), str(it.get("name") or "")):
                    if k:
                        self._items.setdefault(k, str(it["item_id"]))
        return self._items

    def vendors(self) -> dict[str, str]:
        if self._vendors is None:
            self._vendors = {}
            for ct in self.z.pages("contacts", "contacts", {"contact_type": "vendor", "filter_by": "Status.Active"}):
                for k in (str(ct.get("contact_name") or ""), slug(ct.get("contact_name"))):
                    if k:
                        self._vendors.setdefault(k, str(ct["contact_id"]))
        return self._vendors

    def payload(self, o: Any, party: str, items: dict[str, str], godowns: dict[str, str]) -> bytes:
        if o.change == "withdrawn" or o.cancelled or not any(not ln.cancelled for ln in o.lines):
            return json.dumps({"status": "cancelled", "purchaseorder_id": o.erp_ref}).encode()
        vendor = self.vendors().get(party)
        if vendor is None:
            raise ValueError(f"Zoho has no vendor {party!r}: translate the supplier, or add it in Zoho")
        lines = []
        for ln in o.lines:
            if ln.cancelled:
                continue
            item = self.items().get(items[ln.product])
            if item is None:
                raise ValueError(f"Zoho has no item {items[ln.product]!r} (by SKU or name): translate the product")
            x: dict[str, Any] = {"item_id": item, "quantity": ln.qty}
            if ln.price is not None:
                x["rate"] = ln.price
            lines.append(x)
        due = min(ln.date for ln in o.lines if not ln.cancelled)
        return json.dumps({"vendor_id": vendor, "purchaseorder_number": o.id, "reference_number": o.id,
                           "date": (o.order_date or today()).isoformat(), "delivery_date": due.isoformat(),
                           "line_items": lines}).encode()

    def send(self, o: Any, payload: bytes) -> str:
        body = json.loads(payload)
        if body.get("status") == "cancelled":
            self.z.call("POST", f"purchaseorders/{quote(o.erp_ref, safe='')}/status/cancelled")
            return o.erp_ref
        ref = o.erp_ref
        if not ref:     # made before and its answer lost: Zoho has it by our number
            found = self.z.call("GET", "purchaseorders", {"purchaseorder_number": o.id}).get("purchaseorders") or []
            ref = next((str(p["purchaseorder_id"]) for p in found if p.get("purchaseorder_number") == o.id), "")
        if ref:
            data = self.z.call("PUT", f"purchaseorders/{quote(ref, safe='')}", {"ignore_auto_number_generation": "true"},
                               body)
        else:
            data = self.z.call("POST", "purchaseorders", {"ignore_auto_number_generation": "true"}, body)
        po = data.get("purchaseorder") or {}
        got = str(po.get("purchaseorder_id") or ref or "")
        if not got:
            raise ValueError("Zoho made the purchase order but did not give its ID")
        return got


__all__ = ["Sender", "Session", "read", "rows", "settings_of"]
