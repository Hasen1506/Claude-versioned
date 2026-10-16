"""Named connectors (ENTERPRISE_PLAN 3.2): Tally Prime and Zoho Inventory, as scheduled imports that know the other
system's own answers.

A connector is a scheduled import (:mod:`scp.connect.imports`) whose source is the other system itself: it asks it
in its own way (Tally's XML over its HTTP port, Zoho's REST API with an OAuth refresh token), reads its answer, and
gives rows named as the fields here, which then go the way a file's rows go: a customer order per order number, a
stock row per place and product, master data record by record, each logged with what was read. A job reads one kind:

* ``records:products``: Tally's stock items, Zoho's items;
* ``records:locations``: Tally's ledgers under Sundry Debtors and Sundry Creditors, Zoho's contacts, as customers and
  suppliers;
* ``stock``: what is on hand, by godown when Tally gives it, at the place the job names otherwise;
* ``orders``: Tally's sales order vouchers, Zoho's sales orders;
* ``send:purchase_order``: purchase orders released here go to it (a Tally purchase order voucher, a Zoho purchase
  order), and the number it gives each is kept as the ERP's (``erp_ref``), so a changed order goes again and a
  cancelled one is cancelled there.

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

APPS = ("tally", "zoho")
READS = ["records:products", "records:locations", "stock", "orders"]
SENDS = ["send:purchase_order"]
NAMES = {"tally": "Tally", "zoho": "Zoho Inventory"}
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


def module(app: str):  # type: ignore[no-untyped-def]
    from . import tally, zoho
    return {"tally": tally, "zoho": zoho}[app]


def kinds(app: str) -> list[str]:
    return [*READS, *SENDS]


def secrets_of(app: str) -> list[str]:
    """The credentials a connector keeps (never shown again)."""
    return list(module(app).SECRETS)


def settings_of(job: dict) -> AppSettings:
    return AppSettings.model_validate_json(job["app"]) if job.get("app") else AppSettings()


def slug(name: Any) -> str:
    """A name from the other system as a code here: characters a code cannot have become hyphens."""
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", str(name or "").strip()).strip("-._")[:64]


def check(app: str, kind: str, source: str, s: AppSettings, secrets: dict[str, str], m: Mapping | None) -> None:
    """Refuse a connector that cannot work (ValueError, saying what to give)."""
    if kind not in kinds(app):
        raise ValueError(f"{NAMES[app]} gives {', '.join(kinds(app))}")
    if kind == "stock" and not s.place and not (m and "location" in m.fields and m.fields["location"].values):
        raise ValueError(f"{NAMES[app]}'s stock goes to a place here: name the place, or translate each "
                         f"{'godown' if app == 'tally' else 'warehouse'} (location)")
    module(app).check(source, s, secrets)


# ------------------------------------------------------------------------------------------------ reading
ID_FIELDS = {"orders": ("customer", "product"), "stock": ("location", "product"), "records:products": ("id",),
             "records:locations": ("id",)}


def items(job: dict, raw: bytes, m: Mapping | None, day_first: bool = True) -> list[dict[str, Any]]:
    """What the other system answered, as the items of the job's kind."""
    from ..imports import _orders
    kind = job["kind"]
    s = settings_of(job)
    rows = recode(kind, module(job["source_type"]).rows(kind, raw, s), m, day_first)
    for r in rows:
        for f in ID_FIELDS.get(kind, ()):
            if r.get(f) not in (None, ""):
                r[f] = slug(r[f])
        if kind == "records:products":
            r.setdefault("type", s.product_type.value)
    if kind == "stock":
        return _summed(rows, s.place)
    if kind == "orders":
        return _orders(rows)
    return rows


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


__all__ = ["ADD_ONLY", "APPS", "AppSettings", "NAMES", "READS", "SENDS", "check", "columns", "items", "kinds",
           "module", "secrets_of", "settings_of", "slug"]
