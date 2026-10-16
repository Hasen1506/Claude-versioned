"""Named connectors (ENTERPRISE_PLAN 3.2, 3.3): Tally Prime, Zoho Inventory, Shopify and Odoo, as scheduled imports
that know the other system's own answers.

A connector is a scheduled import (:mod:`scp.connect.imports`) whose source is the other system itself: it asks it
in its own way (Tally's XML over its HTTP port, Zoho's REST API with an OAuth refresh token), reads its answer, and
gives rows named as the fields here, which then go the way a file's rows go: a customer order per order number, a
stock row per place and product, master data record by record, each logged with what was read. A job reads one kind:

* ``records:products``: Tally's stock items, Zoho's items;
* ``records:locations``: Tally's ledgers under Sundry Debtors and Sundry Creditors, Zoho's contacts and Odoo's
  partners as customers and suppliers; Shopify's locations as places;
* ``records:production_sources``: Odoo's bills of materials;
* ``stock``: what is on hand at the place the job names (Tally, Zoho), or by Shopify location and Odoo warehouse;
* ``orders``: Tally's sales order vouchers, Zoho's and Odoo's sales orders, Shopify's orders;
* ``postings``: Shopify's fulfilments, as deliveries;
* ``send:purchase_order`` (Tally, Zoho, Odoo) and ``send:production_order`` (Odoo): orders released here go to it,
  and the number it gives each is kept as the ERP's (``erp_ref``), so a changed order goes again and a cancelled one
  is cancelled there.

Codes are translated by the job's mapping (``values``: the other system's code = the code here); a name that is not
translated becomes a code here as it is, with characters a code cannot have made hyphens ("Steel Tumbler 250 ml"
is ``Steel-Tumbler-250-ml``). A field that only a new record takes (a product's type and unit, a place's type and
region) is not changed on a record kept here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import Field

from ...model.common import Model, ProductType
from ..mapping import Mapping, recode

APPS = ("tally", "zoho", "shopify", "odoo")
SENDS = ["send:purchase_order", "send:production_order"]
NAMES = {"tally": "Tally", "zoho": "Zoho Inventory", "shopify": "Shopify", "odoo": "Odoo"}
#: fields a new record takes from the other system, and one kept here does not
ADD_ONLY = {"records:products": frozenset({"type", "base_uom", "family"}),
            "records:locations": frozenset({"type", "region"})}
DataCentre = Literal["in", "com", "eu", "com.au", "jp", "ca", "sa"]


class AppSettings(Model):
    """What a connector needs to know beyond its address and credentials."""
    company: str = Field("", max_length=120, description="Tally: the company's name in Tally (empty: the one open "
                                                         "in Tally)")
    place: str = Field("", max_length=64, description="Stock: the place here it is at, unless a godown or warehouse "
                                                      "is translated (the mapping's location)")
    product_type: ProductType = Field(ProductType.FG, description="The type a new product gets here")
    days_back: int = Field(90, ge=1, le=730, description="Tally orders: the vouchers of this many days back are read "
                                                         "(a changed one is changed here)")
    order_type: str = Field("Sales Order", min_length=1, max_length=60,
                            description="Tally: the voucher type read as customer orders")
    purchase_type: str = Field("Purchase Order", min_length=1, max_length=60,
                               description="Tally: the voucher type purchase orders are made as")
    purchase_ledger: str = Field("Purchase", min_length=1, max_length=120,
                                 description="Tally: the ledger a purchase order is booked to")
    data_centre: DataCentre = Field("in", description="Zoho: where the organisation is kept (zoho.in, zoho.com, …)")
    customer: str = Field("", max_length=64, description="Shopify orders: the customer here they are booked to (the "
                                                         "online shop)")
    api_version: str = Field("2026-07", pattern=r"^\d{4}-(01|04|07|10)$",
                             description="Shopify: the Admin API version asked (a supported one, 2026-07)")
    database: str = Field("", max_length=80, pattern=r"^[A-Za-z0-9_.\-]*$", description="Odoo: the database's name")
    odoo_api: Literal["jsonrpc", "json2"] = Field("jsonrpc", description="Odoo: JSON-RPC (every version), or the JSON "
                                                                          "API of Odoo 19 and later")


def module(app: str):  # type: ignore[no-untyped-def]
    from . import odoo, shopify, tally, zoho
    return {"tally": tally, "zoho": zoho, "shopify": shopify, "odoo": odoo}[app]


def kinds(app: str) -> list[str]:
    return list(module(app).KINDS)


def secrets_of(app: str) -> list[str]:
    """The credentials a connector keeps (never shown again)."""
    return list(module(app).SECRETS)


def keeps_secrets(app: str) -> bool:
    """A connector with credentials of its own (kept as the headers of a web address are)."""
    return app in APPS and bool(module(app).SECRETS)


def settings_of(job: dict) -> AppSettings:
    return AppSettings.model_validate_json(job["app"]) if job.get("app") else AppSettings()


def slug(name: Any) -> str:
    """A name from the other system as a code here: characters a code cannot have become hyphens."""
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", str(name or "").strip()).strip("-._")[:64]


def check(app: str, kind: str, source: str, s: AppSettings, secrets: dict[str, str], m: Mapping | None) -> None:
    """Refuse a connector that cannot work (ValueError, saying what to give)."""
    if kind not in kinds(app):
        raise ValueError(f"{NAMES[app]} gives {', '.join(kinds(app))}")
    if kind == "stock" and not getattr(module(app), "PLACES", False) and not s.place and not (
            m and "location" in m.fields and m.fields["location"].values):
        raise ValueError(f"{NAMES[app]}'s stock goes to a place here: name the place, or translate each "
                         f"{'godown' if app == 'tally' else 'warehouse'} (location)")
    module(app).check(source, s, secrets, kind)


# ------------------------------------------------------------------------------------------------ reading
ID_FIELDS = {"orders": ("customer", "product"), "stock": ("location", "product"), "records:products": ("id",),
             "records:locations": ("id",), "records:production_sources": ("id", "location", "product")}


def items(job: dict, raw: bytes, m: Mapping | None, day_first: bool = True) -> list[dict[str, Any]]:
    """What the other system answered, as the items of the job's kind."""
    from ..imports import _orders
    kind = job["kind"]
    s = settings_of(job)
    got = module(job["source_type"]).rows(kind, raw, s)
    if kind == "stock" and s.place:   # a location there not translated is the place the job names
        told = _values(m, "location")
        for r in got:
            if r.get("location") and "*" not in told and str(r["location"]).strip() not in told:
                r["location"] = s.place
    rows = recode(kind, got, m, day_first)
    for r in rows:
        for f in ID_FIELDS.get(kind, ()):
            if r.get(f) not in (None, ""):
                r[f] = slug(r[f])
        if kind == "records:products":
            r.setdefault("type", s.product_type.value)
        if kind == "records:production_sources":
            told = _values(m, "product")
            for c in r.get("components") or []:
                c["product"] = slug(told.get(str(c["product"]).strip(), told.get("*", c["product"])))
    if kind == "stock":
        return _summed(rows, s.place)
    if kind == "orders":
        return _orders(rows)
    return rows


def _values(m: Mapping | None, field: str) -> dict[str, str]:
    f = m.fields.get(field) if m is not None else None
    return dict(f.values) if f is not None and f.values else {}


def _summed(rows: list[dict[str, Any]], place: str) -> list[dict[str, Any]]:
    """Stock rows that land on one place, product, batch and stock type (two godowns kept as one place here) as one."""
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        if not r.get("location") and place:
            r["location"] = place
        k = (r.get("location"), r.get("product"), r.get("batch"), r.get("stock_type"))
        if k in out and isinstance(out[k].get("qty"), (int, float)) and isinstance(r.get("qty"), (int, float)):
            out[k]["qty"] += r["qty"]
        else:
            out[k] = dict(r)
    return list(out.values())


def columns(job: dict, raw: bytes) -> list[str]:
    """The fields the connector's rows have (before the mapping): what a translation can name."""
    rows = module(job["source_type"]).rows(job["kind"], raw, settings_of(job))
    seen: list[str] = []
    for r in rows[:20]:
        for k in r:
            if k not in seen:
                seen.append(k)
    return seen


def fingerprint(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:24]


def today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


__all__ = ["ADD_ONLY", "APPS", "AppSettings", "NAMES", "SENDS", "check", "columns", "items", "keeps_secrets", "kinds",
           "module", "secrets_of", "settings_of", "slug"]
