"""Scheduled imports (Phase Q): a file another system leaves, read on a schedule and applied as its message.

A job reads, every hour, day or week at a time of day, either

* a **web address** (``https://erp.example.com/export/stock.csv``, with a header such as ``Authorization`` if the
  address needs one), or
* a **folder on the server**: files matching a pattern in ``SCP_IMPORT_DIR/<company>/`` (``stock-*.csv``), each read in
  name order and moved to ``done/`` (or ``failed/``, when it cannot be read) beside it,

and applies what it read as the message of its kind (customer orders, stock, goods movements or the records of a
list of master data: :mod:`scp.connect.erp`), as the owner who made the job, logged with the others. A file whose
content was applied before (the same bytes, by its fingerprint) is not applied twice.

A file is CSV (comma, semicolon or tab; the header names the columns, as the browser's upload reads them) or JSON (the
message the ERP would send, or its list of items). Server settings:

* ``SCP_IMPORT_DIR``: where folders of files are looked for (none: only web addresses);
* ``SCP_IMPORT_HOSTS``: if set, the only hosts a web address may name (comma-separated). Without it any host on the
  internet may be named, but not one inside the server's own network (a private, loopback or link-local address, as
  the name resolves when the file is read, redirects included), so a job cannot reach the server's neighbours;
* ``SCP_TIMEZONE``: the time zone of the times of day (default UTC), e.g. ``Asia/Kolkata``.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import ipaddress
import json
import os
import re
import http.client
import shutil
import socket
import ssl
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

from pydantic import Field

from ..companies import CompanyError, Companies, User
from ..model.common import Model, Out
from .erp import (
    ErpOrder, ErpPosting, ErpStock, ItemResult, apply_orders, apply_postings, apply_records, apply_stock, record_lists,
)
from . import apps
from .apps import AppSettings
from .mapping import Mapping, columns, dig, fields_of, json_items, records, sample
from .mapping import apply as map_rows
from .mapping import check as check_mapping
from .messages import MessageAnswer, MessageRow, log, receive

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_jobs (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, source_type TEXT NOT NULL,
  source TEXT NOT NULL, headers TEXT NOT NULL DEFAULT '{}', format TEXT NOT NULL, day_first INTEGER NOT NULL DEFAULT 1,
  every TEXT NOT NULL, at TEXT NOT NULL DEFAULT '06:00', weekday INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1, run_as TEXT NOT NULL, created_at TEXT NOT NULL, next_run TEXT,
  last_run TEXT, last_status TEXT NOT NULL DEFAULT '', last_summary TEXT NOT NULL DEFAULT '', deleted INTEGER NOT NULL DEFAULT 0
);
"""
MAX_BYTES = 50 * 1024 * 1024
Every = Literal["hour", "day", "week"]


def import_dir() -> Path | None:
    v = os.environ.get("SCP_IMPORT_DIR", "").strip()
    return Path(v) if v else None


def timezone() -> str:
    return os.environ.get("SCP_TIMEZONE", "").strip() or "UTC"


def _zone() -> ZoneInfo:
    try:
        return ZoneInfo(timezone())
    except Exception:  # an unknown zone name: UTC rather than no imports at all
        return ZoneInfo("UTC")


def kinds() -> list[str]:
    return ["orders", "stock", "postings", *(f"records:{n}" for n in record_lists())]


class Paging(Model):
    """How a web API gives its records page by page."""
    mode: Literal["next", "page"] = Field("next", description="next: each answer names the next page's address; "
                                                              "page: pages are numbered")
    next: str = Field("", max_length=200, description="next: the path in the answer to the next page's address "
                                                      "(links.next, @odata.nextLink); page: the path to a flag that "
                                                      "more pages follow (page_context.has_more_page); empty: until "
                                                      "a page has no records")
    param: str = Field("page", min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.\-\[\]]+$",
                       description="page: the parameter that numbers the pages, from 1")
    max_pages: int = Field(50, ge=1, le=500)


SINCE = "{since}"


class JobInput(Model):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(description="orders, stock, postings or records:<list>")
    source_type: Literal["url", "folder", "api", "tally", "zoho"]
    source: str = Field(min_length=1, max_length=500, description="The web address, or the file pattern in the "
                                                                  "folder; {since} in an address is the time the last "
                                                                  "good run started (only what changed since); Tally: "
                                                                  "its address (http://tally-pc:9000); Zoho: the "
                                                                  "organisation ID")
    app: AppSettings | None = Field(None, description="Tally or Zoho: what the connector needs beyond its source")
    secrets: dict[str, str] | None = Field(None, description="Zoho: client_id, client_secret and refresh_token; "
                                                             "omitted (or a value left empty) keeps the one kept for "
                                                             "the same organisation")
    mapping: Mapping | None = Field(None, description="Which column or field there fills each field here; none: "
                                                      "columns are recognised by their names")
    paging: Paging | None = Field(None, description="api: how the answer comes page by page")
    headers: dict[str, str] | None = Field(None, description="A web address: headers to send (Authorization); omitted "
                                         "keeps them only for the same origin, {} removes them")
    format: Literal["csv", "json"] = "csv"
    day_first: bool = Field(True, description="CSV dates such as 05/01/2026 are day first (5 January)")
    every: Every = "day"
    at: str = Field("06:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="Time of day (the minute, hourly)")
    weekday: int = Field(0, ge=0, le=6, description="Weekly: 0 Monday … 6 Sunday")
    enabled: bool = True


class ImportJob(Out):
    id: str
    name: str
    kind: str
    source_type: str
    source: str
    header_names: list[str]        # the headers sent (their values are not shown again)
    format: str
    day_first: bool
    every: str
    at: str
    weekday: int
    enabled: bool
    run_as: str                    # a name: whose rights the job uses
    next_run: str | None
    last_run: str | None
    last_status: str
    last_summary: str
    mapping: Mapping | None = None
    paging: Paging | None = None
    since: str | None = None       # {since}: the start of the last good run (only what changed after it is read)
    app: AppSettings | None = None   # Tally or Zoho: the connector's settings


class ImportJobs(Out):
    jobs: list[ImportJob]
    folder: str | None             # the company's folder on the server, when the server has one
    timezone: str
    kinds: list[str]
    fields: dict[str, list[str]] = {}   # the fields a mapping can fill, by kind
    apps: dict[str, list[str]] = {}     # Tally and Zoho: the kinds each reads (or, send:…, sends)
    secrets: dict[str, list[str]] = {}  # the credentials each keeps


class Tried(Out):
    """A dry run: what an import would do now, with nothing saved, no file moved and its schedule as it was."""
    messages: list[MessageRow]
    columns: list[str] = []        # the columns (paths) the first records read have: what a mapping can name
    rows: list[dict[str, Any]] = []   # the first rows as the fields here, after the mapping


def _ensure(c: Companies) -> None:
    if not getattr(c, "_imports_ready", False):
        c.db.executescript(SCHEMA)
        have = {r[1] for r in c.db.execute("PRAGMA table_info(import_jobs)")}
        for col in ("mapping", "paging", "cursor", "app"):   # ENTERPRISE_PLAN 3.1–3.2: connectors
            if col not in have:
                c.db.execute(f"ALTER TABLE import_jobs ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        c._imports_ready = True  # type: ignore[attr-defined]


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).replace(microsecond=0).isoformat()


def company_timezone(c: Companies, cid: str) -> str:
    """The company's own time zone (its settings), else the server's: a 06:00 import of a company in Chennai runs at
    06:00 in Chennai, not 06:00 UTC (UX audit: the scheduler's zone was a server setting only)."""
    try:
        r = c.db.execute("SELECT dataset FROM companies WHERE id = ?", (cid,)).fetchone()
        tz = (json.loads(r["dataset"]).get("settings") or {}).get("timezone") if r and r["dataset"] else None
        if tz:
            ZoneInfo(tz)
            return tz
    except Exception:  # noqa: BLE001 - an unreadable or unknown zone: the server's, rather than no imports at all
        pass
    return timezone()


def next_run(every: str, at: str, weekday: int, after: dt.datetime, zone: str | None = None) -> dt.datetime:
    """The first time after ``after`` the schedule falls on (times of day in ``zone``, else the server's time zone)."""
    try:
        z = ZoneInfo(zone) if zone else _zone()
    except Exception:  # noqa: BLE001
        z = _zone()
    local = after.astimezone(z)
    h, m = (int(x) for x in at.split(":"))
    if every == "hour":
        t = local.replace(minute=m, second=0, microsecond=0)
        while t <= local:
            t += dt.timedelta(hours=1)
        return t.astimezone(dt.UTC)
    t = local.replace(hour=h, minute=m, second=0, microsecond=0)
    while t <= local or (every == "week" and t.weekday() != weekday):
        t = (t + dt.timedelta(days=1)).replace(hour=h, minute=m)
    return t.astimezone(dt.UTC)


def _check(c: Companies, cid: str, body: JobInput) -> None:
    if body.source_type in apps.APPS:
        if body.kind not in apps.kinds(body.source_type):
            raise CompanyError(f"{apps.NAMES[body.source_type]} gives {', '.join(apps.kinds(body.source_type))}", 422)
    elif body.kind not in kinds():
        raise CompanyError(f"an import is one of {', '.join(kinds())}", 422)
    if body.mapping is not None:
        try:
            check_mapping(body.kind, body.mapping)
        except ValueError as e:
            raise CompanyError(str(e), 422) from None
    if body.paging is not None and body.source_type != "api":
        raise CompanyError("pages are read from a web API (from: a web API)", 422)
    if body.source_type == "api" and body.format != "json":
        raise CompanyError("a web API answers in JSON", 422)
    if body.source_type == "zoho":
        return
    if body.source_type in ("url", "api", "tally"):
        u = urlparse(body.source.replace(SINCE, ""))
        if u.scheme not in ("http", "https") or not u.hostname:
            raise CompanyError("a web address starts with https:// (or http://)", 422)
        try:
            _origin(body.source.replace(SINCE, ""))
        except ValueError as e:
            raise CompanyError("the web address has an invalid port", 422) from e
        allowed = _hosts()
        if allowed and u.hostname.lower() not in allowed:
            raise CompanyError(f"this server reads files only from {', '.join(allowed)}", 422)
    else:
        if import_dir() is None:
            raise CompanyError("this server has no folder for files (SCP_IMPORT_DIR): use a web address", 422)
        if "/" in body.source or "\\" in body.source or body.source.startswith("."):
            raise CompanyError("a file pattern names files in the company's folder (stock-*.csv), not other folders", 422)


def _check_app(body: JobInput, secrets: dict[str, str]) -> None:
    """A connector that cannot work with what it was given (its credentials as they will be kept)."""
    if body.source_type in apps.APPS:
        try:
            apps.check(body.source_type, body.kind, body.source, body.app or AppSettings(), secrets, body.mapping)
        except ValueError as e:
            raise CompanyError(str(e), 422) from None


def _given(body: JobInput) -> dict[str, str] | None:
    """The headers (a web address, Tally) or the credentials (Zoho) sent with a job."""
    return body.secrets if body.source_type == "zoho" else body.headers


def _kept(old: Any, body: JobInput) -> dict[str, str]:
    """The headers or credentials a job keeps: those sent, else (or for a value left empty) the ones kept for the
    same place, the same address or the same Zoho organisation in the same data centre."""
    given = _given(body)
    if body.source_type == "folder":
        return {}
    same = _same(old, body)
    before = json.loads(old["headers"]) if same and old is not None else {}
    if given is None:
        return before
    return {k: (v if v.strip() or k not in before else before[k]) for k, v in given.items()
            if v.strip() or k in before} if body.source_type == "zoho" else given


def _same(old: Any, body: JobInput) -> bool:
    if old is None or old["source_type"] == "folder" or body.source_type == "folder":
        return False
    if (old["source_type"] == "zoho") != (body.source_type == "zoho"):
        return False
    if body.source_type == "zoho":
        was = AppSettings.model_validate_json(old["app"]) if old["app"] else AppSettings()
        return old["source"].strip() == body.source.strip() and was.data_centre == (body.app or AppSettings()).data_centre
    return _origin(old["source"]) == _origin(body.source)


def _job(c: Companies, r: Any) -> ImportJob:
    return ImportJob(id=r["id"], name=r["name"], kind=r["kind"], source_type=r["source_type"], source=r["source"],
                     header_names=sorted(json.loads(r["headers"])), format=r["format"], day_first=bool(r["day_first"]),
                     every=r["every"], at=r["at"], weekday=r["weekday"], enabled=bool(r["enabled"]),
                     run_as=c._name(r["run_as"]), next_run=r["next_run"], last_run=r["last_run"],
                     last_status=r["last_status"], last_summary=r["last_summary"], mapping=_mapping(r),
                     paging=Paging.model_validate_json(r["paging"]) if r["paging"] else None,
                     since=r["cursor"] or None,
                     app=AppSettings.model_validate_json(r["app"]) if r["app"] else None)


def _mapping(r: Any) -> Mapping | None:
    return Mapping.model_validate_json(r["mapping"]) if r["mapping"] else None


def folder_of(cid: str) -> Path | None:
    d = import_dir()
    return d / cid if d is not None else None


def jobs(c: Companies, user: User, cid: str) -> ImportJobs:
    with c.lock:
        _ensure(c)
        c._need(user, cid)
        rows = c.db.execute("SELECT * FROM import_jobs WHERE company_id = ? AND deleted = 0 ORDER BY id", (cid,)).fetchall()
        f = folder_of(cid)
        return ImportJobs(jobs=[_job(c, r) for r in rows], folder=str(f) if f else None, timezone=company_timezone(c, cid),
                          kinds=kinds(), fields={k: fields_of(k) for k in [*kinds(), *apps.SENDS]},
                          apps={a: apps.kinds(a) for a in apps.APPS}, secrets={a: apps.secrets_of(a) for a in apps.APPS})


def save_job(c: Companies, user: User, cid: str, body: JobInput, jid: str | None = None,
             now: dt.datetime | None = None) -> ImportJobs:
    """Make a job, or change one (``jid``); only an owner may: a job reads from outside with the owner's rights."""
    _check(c, cid, body)
    now = now or dt.datetime.now(dt.UTC)
    with c.lock:
        _ensure(c)
        c._need(user, cid, "owner")
        nxt = _iso(next_run(body.every, body.at, body.weekday, now, company_timezone(c, cid))) if body.enabled else None
        if jid is None:
            n = c.db.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] + 1
            jid = f"J{n:04d}"
            while c.db.execute("SELECT 1 FROM import_jobs WHERE id = ?", (jid,)).fetchone():
                n += 1
                jid = f"J{n:04d}"
            kept = _kept(None, body)
            _check_app(body, kept)
            c.db.execute("INSERT INTO import_jobs (id, company_id, name, kind, source_type, source, headers, format, "
                         "day_first, every, at, weekday, enabled, run_as, created_at, next_run, mapping, paging, app) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (jid, cid, body.name, body.kind, body.source_type, body.source, json.dumps(kept),
                          body.format, int(body.day_first), body.every, body.at, body.weekday, int(body.enabled),
                          user.id, _iso(now), nxt, *_extras(body)))
            c._log(cid, None, user.id, "member", f"import {jid} “{body.name}” made: {body.kind} every {body.every}")
        else:
            r = c.db.execute("SELECT * FROM import_jobs WHERE id = ? AND company_id = ? AND deleted = 0",
                             (jid, cid)).fetchone()
            if r is None:
                raise CompanyError(f"no import {jid} in this company", 404)
            headers = _kept(r, body)
            _check_app(body, headers)
            # another address or another kind of record: what changed since is read again from the start
            cursor = r["cursor"] if _same(r, body) and r["kind"] == body.kind else ""
            c.db.execute("UPDATE import_jobs SET name = ?, kind = ?, source_type = ?, source = ?, headers = ?, format = ?, "
                         "day_first = ?, every = ?, at = ?, weekday = ?, enabled = ?, run_as = ?, next_run = ?, "
                         "mapping = ?, paging = ?, app = ?, cursor = ? WHERE id = ?",
                         (body.name, body.kind, body.source_type, body.source, json.dumps(headers), body.format,
                          int(body.day_first), body.every, body.at, body.weekday, int(body.enabled), user.id, nxt,
                          *_extras(body), cursor, jid))
            c._log(cid, None, user.id, "member", f"import {jid} “{body.name}” changed"
                   + ("" if body.enabled else " (switched off)"))
    return jobs(c, user, cid)


def _extras(body: JobInput) -> tuple[str, str, str]:
    """The mapping, the paging and a connector's settings as kept: an empty mapping is none."""
    m = body.mapping
    return (m.model_dump_json() if m is not None and (m.fields or m.items) else "",
            body.paging.model_dump_json() if body.paging is not None and body.source_type == "api" else "",
            (body.app or AppSettings()).model_dump_json() if body.source_type in apps.APPS else "")


def delete_job(c: Companies, user: User, cid: str, jid: str) -> ImportJobs:
    with c.lock:
        _ensure(c)
        c._need(user, cid, "owner")
        r = c.db.execute("SELECT name FROM import_jobs WHERE id = ? AND company_id = ? AND deleted = 0", (jid, cid)).fetchone()
        if r is None:
            raise CompanyError(f"no import {jid} in this company", 404)
        c.db.execute("UPDATE import_jobs SET deleted = 1, enabled = 0, next_run = NULL WHERE id = ?", (jid,))
        c._log(cid, None, user.id, "member", f"import {jid} “{r['name']}” removed")
    return jobs(c, user, cid)


def _origin(url: str) -> tuple[str, str, int | None]:
    u = urlparse(url)
    return (u.scheme.lower(), (u.hostname or "").lower(),
            u.port if u.port is not None else (443 if u.scheme == "https" else 80))


# ------------------------------------------------------------------------------------------------ reading files
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


SYNONYMS: dict[str, list[str]] = {
    "location": ["location", "place", "plant", "site", "warehouse", "werk", "storagelocation", "loc"],
    "product": ["product", "material", "item", "sku", "article", "matnr", "productid", "itemcode"],
    "qty": ["qty", "quantity", "onhand", "stock", "unrestricted", "labst", "menge", "amount"],
    "number": ["number", "order", "ordernumber", "salesorder", "orderno", "vbeln", "documentnumber"],
    "customer": ["customer", "soldto", "shipto", "customerid", "kunnr"],
    "order_date": ["orderdate", "documentdate", "created"],
    "customer_ref": ["customerref", "customerpo", "ponumber", "bstkd"],
    "date": ["date", "deliverydate", "wanted", "wantedon", "requesteddate", "postingdate", "due", "duedate"],
    "price": ["price", "netprice", "unitprice"],
    "cancelled": ["cancelled", "canceled", "deleted"],
    "payment_terms": ["paymentterms", "terms"],
    "ref": ["ref", "document", "materialdocument", "mblnr", "reference", "docno"],
    "action": ["action", "movement", "movementtype", "type"],
    "final": ["final", "complete", "last"],
    "batch": ["batch", "lot", "charg"],
    "expires_on": ["expireson", "expiry", "bestbefore", "shelflifeexpiration"],
    "supplier_batch": ["supplierbatch", "vendorbatch"],
    "stock_type": ["stocktype", "fromstock"],
    "to_type": ["totype", "tostock"],
    "quality": ["quality", "qualityinspection", "inqualityinspection", "insme", "inspection"],
    "blocked": ["blocked", "blockedstock", "speme"],
    "note": ["note", "text", "comment"],
}
ACTIONS = {"101": "receive", "gr": "receive", "receipt": "receive", "receive": "receive", "goodsreceipt": "receive",
           "601": "deliver", "sale": "deliver", "deliver": "deliver", "delivery": "deliver", "gi": "deliver",
           "641": "ship", "351": "ship", "ship": "ship", "transfer": "ship",
           "551": "scrap", "scrap": "scrap", "311": "move", "move": "move", "321": "move"}


def read_grid(text: str) -> list[list[str]]:
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text else ""
    delim = max((",", ";", "\t", "|"), key=first.count)
    try:   # newline="": a lone carriage return inside a cell is the file's business, not a crash
        return [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=delim) if any(c.strip() for c in row)]
    except csv.Error as e:   # a file that is not CSV at all is refused like any unreadable file, never a crash
        raise ValueError(f"the file cannot be read as CSV: {e}") from e


def parse_date(v: str, day_first: bool) -> str | None:
    v = v.strip()
    if not v:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", v):
        return v[:10]
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", v)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        d, mo = (a, b) if day_first else (b, a)
        try:
            return dt.date(y, mo, d).isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"\d{8}", v):                 # 20260105, as SAP writes dates
        return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    return None


def _num(v: str) -> float | None:
    v = v.strip().replace(" ", "")
    if not v:
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", v) or re.fullmatch(r"-?\d+,\d+", v):   # 1.234,5 (German)
        v = v.replace(".", "").replace(",", ".")
    else:
        v = v.replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


DATES = {"date", "order_date", "expires_on"}
NUMBERS = {"qty", "price", "quality", "blocked"}
# stock types as exports write them: SAP's stock type indicator (2 quality inspection, 3 blocked) and plain words
STOCK_TYPES = {"": "unrestricted", "1": "unrestricted", "unrestricted": "unrestricted", "free": "unrestricted",
               "2": "quality", "q": "quality", "quality": "quality", "qualityinspection": "quality",
               "inspection": "quality", "3": "blocked", "s": "blocked", "blocked": "blocked"}
FLAGS = {"cancelled", "final"}


def _rows(grid: list[list[str]], fields: list[str], day_first: bool) -> list[dict[str, Any]]:
    if not grid:
        return []
    head = [_norm(h) for h in grid[0]]
    col: dict[str, int] = {}
    for f in fields:
        for i, h in enumerate(head):
            if h in SYNONYMS.get(f, [_norm(f)]) and i not in col.values():
                col[f] = i
                break
    out = []
    for row in grid[1:]:
        rec: dict[str, Any] = {}
        for f, i in col.items():
            v = row[i].strip() if i < len(row) else ""
            if v != "":
                rec[f] = convert(f, v, day_first)
        out.append(rec)
    return out


def convert(f: str, v: str, day_first: bool) -> Any:
    """A cell of a file as the field it fills: a date, a number, a yes/no, a movement or stock type by its code."""
    if f in DATES:
        return parse_date(v, day_first) or v
    if f in NUMBERS:
        n = _num(v)
        return n if n is not None else v
    if f in FLAGS:
        return v.lower() in ("1", "x", "yes", "y", "true", "ja")
    if f == "action":
        return ACTIONS.get(_norm(v), v.lower())
    if f in ("stock_type", "to_type"):
        return STOCK_TYPES.get(_norm(v), v.lower())
    return v


def _stock_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stock with a column per stock type (as SAP's MARD has unrestricted, quality inspection and blocked) becomes a
    row per stock type."""
    if not any("quality" in r or "blocked" in r for r in rows):
        return rows
    out = []
    for r in rows:
        base = {k: v for k, v in r.items() if k not in ("qty", "quality", "blocked", "stock_type")}
        for col, kind in (("qty", "unrestricted"), ("quality", "quality"), ("blocked", "blocked")):
            out.append({**base, "qty": r.get(col, 0), "stock_type": kind})
    return out


def _records(grid: list[list[str]], day_first: bool) -> list[dict[str, Any]]:
    """Rows of master data: the header names fields (``lot_sizing.policy`` for a field within a field)."""
    if not grid:
        return []
    head = [h.strip() for h in grid[0]]
    out = []
    for row in grid[1:]:
        rec: dict[str, Any] = {}
        for h, v in zip(head, row, strict=False):
            v = v.strip()
            if not h or v == "":
                continue
            d = parse_date(v, day_first) if re.search(r"\d[./-]\d|^\d{8}$", v) and not re.fullmatch(r"-?[\d.,]+", v) else None
            val: Any = d or v
            node = rec
            *path, last = h.split(".")
            for p in path:
                node = node.setdefault(p, {})
            node[last] = val
        out.append(rec)
    return out


def parse(kind: str, fmt: str, raw: bytes, day_first: bool = True, mapping: Mapping | None = None) -> list[Any]:
    """The items of a message of ``kind`` read from a file: :class:`pydantic.ValidationError` on a bad row is the
    caller's to report per item, so rows are returned as dicts for orders, stock and postings. With a ``mapping``
    each field is filled from the column or path it names (:mod:`scp.connect.mapping`)."""
    if mapping is not None and mapping.fields:
        rows = map_rows(kind, records(kind, fmt, raw, mapping), mapping, day_first)
        if kind.startswith("records:"):
            return rows
        return _stock_rows(rows) if kind == "stock" else rows if kind == "postings" else _orders(rows)
    text = raw.decode("utf-8-sig", errors="replace")
    if fmt == "json":
        return json_items(json.loads(text), mapping.items if mapping else "", kind)
    grid = read_grid(text)
    if kind.startswith("records:"):
        return _records(grid, day_first)
    if kind == "stock":
        return _stock_rows(_rows(grid, ["location", "product", "qty", "batch", "expires_on", "stock_type", "quality",
                                        "blocked"], day_first))
    if kind == "postings":
        return _rows(grid, ["ref", "action", "number", "qty", "date", "final", "location", "product", "batch",
                            "expires_on", "supplier_batch", "stock_type", "to_type", "note"], day_first)
    return _orders(_rows(grid, ["number", "customer", "order_date", "customer_ref", "payment_terms", "product", "qty",
                                "date", "price", "cancelled", "note"], day_first))


def _orders(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows of order lines, an order's header repeated on each, as one order per number."""
    orders: dict[str, dict[str, Any]] = {}
    for ln in lines:
        num = str(ln.get("number") or "")
        o = orders.setdefault(num, {"number": num, "customer": ln.get("customer", ""), "lines": [],
                                    **{k: ln[k] for k in ("order_date", "customer_ref", "payment_terms", "note") if k in ln}})
        if ln.get("cancelled"):
            o["cancelled"] = True
        if "product" in ln:
            o["lines"].append({k: ln[k] for k in ("product", "qty", "date", "price") if k in ln})
    return list(orders.values())


def _typed(kind: str, items: list[Any]) -> tuple[list[Any], list[ItemResult]]:
    """Items checked against the message's form: the ones that fit, and a refusal for each that does not."""
    form = {"orders": ErpOrder, "stock": ErpStock, "postings": ErpPosting}.get(kind)
    if form is None:
        return items, []
    good, bad = [], []
    for i, it in enumerate(items):
        if kind == "postings" and isinstance(it, dict) and "number" in it:
            it = dict(it)
            it["order"] = it.pop("number")
        try:
            good.append(form.model_validate(it))
        except Exception as e:  # noqa: BLE001 - reported per row
            from .erp import _why
            ref = str((it or {}).get("number") or (it or {}).get("ref") or f"row {i + 2}") if isinstance(it, dict) \
                else f"row {i + 2}"
            bad.append(ItemResult(ref=ref, status="refused", message=_why(e)))
    return good, bad


def applier(kind: str, items: list[Any], add_only: frozenset[str] = frozenset()) -> Callable:
    good, bad = _typed(kind, items)

    def change(ds):
        if kind == "orders":
            new, res = apply_orders(ds, good)
        elif kind == "stock":
            new, res = apply_stock(ds, good)
        elif kind == "postings":
            new, res = apply_postings(ds, good)
        else:
            new, res = apply_records(ds, kind.split(":", 1)[1], good, add_only)
        return new, [*bad, *res]
    return change


# ------------------------------------------------------------------------------------------------ running
Fetch = Callable[[str, dict[str, str]], bytes]


def _hosts() -> list[str]:
    return [x.strip().lower() for x in os.environ.get("SCP_IMPORT_HOSTS", "").split(",") if x.strip()]


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """An address on the public internet: global (so not private, loopback, link-local, carrier-grade NAT
    100.64.0.0/10, reserved, …) and not multicast; an IPv4 address inside IPv6 is judged as itself (CV-H08)."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _resolve(host: str, port: int) -> list[tuple[int, str]]:
    """The addresses a host name resolves to: (family, address)."""
    out = []
    for fam, _type, _proto, _name, addr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        out.append((fam, str(addr[0]).split("%")[0]))
    return out


def _inside(host: str) -> bool:
    """Whether a host name resolves to any address that is not on the public internet (the server's own network,
    the machine itself, a cloud's metadata address)."""
    try:
        infos = _resolve(host, 0)
    except OSError:
        return False                    # no such name: reading it fails on its own
    return any(not _public(ipaddress.ip_address(a)) for _f, a in infos)


def _vetted(host: str, port: int) -> list[tuple[int, str]]:
    """The addresses to connect to for ``host``: resolved once, each one public unless the administrator allows the
    host by name (SCP_IMPORT_HOSTS). The connection is made to these very addresses, so a second lookup cannot
    point it elsewhere (DNS rebinding, CV-H08)."""
    infos = _resolve(host, port)
    if not infos:
        raise ValueError(f"{host} does not resolve")
    if host.lower() not in _hosts():
        bad = [a for _f, a in infos if not _public(ipaddress.ip_address(a))]
        if bad:
            raise ValueError(f"{host} is inside the server's own network ({bad[0]}): the server's administrator can "
                             "allow it with SCP_IMPORT_HOSTS")
    return infos


def _connect(host: str, port: int, timeout: float | None) -> socket.socket:
    err: Exception | None = None
    for fam, addr in _vetted(host, port):
        sock = socket.socket(fam, socket.SOCK_STREAM)
        if timeout is not None:
            sock.settimeout(timeout)
        try:
            sock.connect((addr, port))
            return sock
        except OSError as e:
            sock.close()
            err = e
    raise err or OSError(f"cannot connect to {host}")


class _PinnedHTTP(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = _connect(self.host, self.port, self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self) -> None:
        sock = _connect(self.host, self.port, self.timeout)
        ctx = getattr(self, "_context", None) or ssl.create_default_context()
        self.sock = ctx.wrap_socket(sock, server_hostname=self.host)   # the certificate is checked for the name


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(_PinnedHTTP, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(_PinnedHTTPS, req, context=ssl.create_default_context())


def reachable(url: str) -> None:
    """Refuse an address a job may not read: not http(s), a host not on the allowlist, or (without one) a host inside
    the server's own network."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"{url} is not a web address (http:// or https://)")
    allowed = _hosts()
    if allowed:
        if u.hostname.lower() not in allowed:
            raise ValueError(f"this server reads files only from {', '.join(allowed)}, not {u.hostname}")
    elif _inside(u.hostname):
        raise ValueError(f"{u.hostname} is inside the server's own network: the server's administrator can allow it "
                         "with SCP_IMPORT_HOSTS")


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to an address the job could name itself; headers given for the job (Authorization)
    are not sent on to it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        reachable(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url: str, headers: dict[str, str]) -> bytes:
    reachable(url)
    req = urllib.request.Request(url, headers={"User-Agent": "scp-import/1"})
    for k, v in headers.items():
        req.add_unredirected_header(k, v)          # not carried to wherever a redirect points
    # no proxy from the environment (it would be the address connected to), and every connection, a redirect's
    # included, goes to an address checked when it is made
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHTTPHandler, _PinnedHTTPSHandler,
                                         _Redirect)
    with opener.open(req, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    return data


#: tests replace this to serve a file without a network
fetch: Fetch = _fetch
Http = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


def _http(method: str, url: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, bytes]:
    """A request a connector makes (ENTERPRISE_PLAN 3.2): to an address a job may read, as :func:`_fetch` is, and
    answered with its status and body (an error's body too: Zoho says why in it)."""
    import urllib.error
    reachable(url)
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": "scp-connector/1"})
    for k, v in headers.items():
        req.add_unredirected_header(k, v)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHTTPHandler, _PinnedHTTPSHandler,
                                         _Redirect)
    try:
        with opener.open(req, timeout=60) as r:
            status, data = r.status, r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        status, data = e.code, e.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"the answer is larger than {MAX_BYTES // (1024 * 1024)} MB")
    return status, data


#: tests replace this to answer as Tally or Zoho would
http: Http = _http


def _apply(c: Companies, user: User, cid: str, job: dict, raw: bytes, source: str, dry: bool = False) -> MessageAnswer:
    fingerprint = hashlib.sha256(raw).hexdigest()[:24]
    if job["source_type"] in apps.APPS:
        items = apps.items(job, raw, _mapping_of(job), bool(job["day_first"]))
    else:
        items = parse(job["kind"], job["format"], raw, bool(job["day_first"]), _mapping_of(job))
    return receive(c, user, cid, job["kind"], f"{job['id']}:{fingerprint}",
                   applier(job["kind"], items, apps.ADD_ONLY.get(job["kind"], frozenset()) if job["source_type"]
                           in apps.APPS else frozenset()),
                   source=f"{job['id']} {job['name']}: {source}", sample=sample(raw), dry_run=dry)


def _mapping_of(job: dict) -> Mapping | None:
    """The job's mapping; pages read from a web API are already the list of records (``items`` was followed)."""
    m = _mapping(job)
    if m is not None and job["source_type"] == "api":
        m = m.model_copy(update={"items": ""})
    return m


def _failed(c: Companies, job: dict, source: str, why: str, dry: bool = False, raw: bytes = b"") -> MessageRow:
    return log(c, job["company_id"], job["run_as"], "in", job["kind"], "", "failed", f"could not read {source}: {why}",
               None, [], source=f"{job['id']} {job['name']}: {source}", sample=sample(raw) if raw else "",
               dry_run=dry)


def since(url: str, cursor: str | None) -> str:
    """The address with ``{since}`` as the time the last good run started (the first run: everything)."""
    return url.replace(SINCE, quote(cursor or "1970-01-01T00:00:00+00:00", safe=""))


def _numbered(url: str, param: str, n: int) -> str:
    u = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != param] + [(param, str(n))]
    return urlunparse(u._replace(query=urlencode(q)))


def read_api(job: dict) -> bytes:
    """Every page of a web API's answer, as one JSON list of its records. The job's headers go only to its own
    address's host (a next page elsewhere gets none); more pages than the job allows is a failure, not a part."""
    headers = json.loads(job["headers"])
    paging = Paging.model_validate_json(job["paging"]) if job["paging"] else None
    m = _mapping(job)
    url: str | None = since(job["source"], job["cursor"])
    first = url
    origin = _origin(url)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    size = 0
    for n in range(1, (paging.max_pages if paging else 1) + 1):
        assert url is not None
        seen.add(url)
        raw = fetch(url, headers if _origin(url) == origin else {})
        size += len(raw)
        if size > MAX_BYTES:
            raise ValueError(f"the pages are larger than {MAX_BYTES // (1024 * 1024)} MB together: read only what "
                             "changed ({since} in the address)")
        data = json.loads(raw.decode("utf-8-sig", errors="replace"))
        got = json_items(data, m.items if m else "", job["kind"])
        out += got
        if paging is None:
            return json.dumps(out).encode()
        if paging.mode == "next":
            nxt = dig(data, paging.next)
            url = urljoin(url, nxt) if isinstance(nxt, str) and nxt.strip() else None
            if url in seen:
                url = None
        else:
            more = dig(data, paging.next) if paging.next else bool(got)
            url = _numbered(first, paging.param, n + 1) if got and more not in (None, False, 0, "", "false") else None
        if url is None:
            return json.dumps(out).encode()
    raise ValueError(f"the answer has more than {paging.max_pages} pages: allow more pages, or read only what "
                     "changed ({since} in the address)")


def _read(job: dict) -> bytes:
    if job["source_type"] in apps.APPS:
        kept = json.loads(job["headers"])
        zoho = job["source_type"] == "zoho"
        return apps.module(job["source_type"]).read(job, apps.settings_of(job), kept if zoho else {},
                                                    {} if zoho else kept)
    if job["source_type"] == "api":
        return read_api(job)
    return fetch(since(job["source"], job["cursor"]), json.loads(job["headers"]))


def _runner(c: Companies, job: dict) -> User | None:
    try:
        runner = c._user(job["run_as"])
        c._need(runner, job["company_id"], "owner", "planner", two_step=False)   # a schedule, not a sign-in
        return runner
    except CompanyError:
        return None


def _run(c: Companies, job: dict, runner: User, dry: bool = False) -> list[tuple[MessageRow, bytes]]:
    """Read what the job names and apply it (``dry``: say what would become of it, move no file): each message
    with what was read."""
    cid = job["company_id"]
    out: list[tuple[MessageRow, bytes]] = []
    if job["kind"].startswith("send:"):
        from .apps import send
        return send.run(c, job, runner, dry)
    if job["source_type"] in ("url", "api", *apps.APPS):
        try:
            raw = _read(job)
        except Exception as e:  # noqa: BLE001 - the log says what went wrong
            out.append((_failed(c, job, job["source"], str(e) or type(e).__name__, dry), b""))
        else:
            out.append((_message(c, runner, cid, job, raw, job["source"], dry), raw))
        return out
    folder = folder_of(cid)
    files = sorted(p for p in folder.glob(job["source"]) if p.is_file()) if folder and folder.is_dir() else []
    for p in files:
        raw = b""
        try:
            raw = p.read_bytes()
            row = _message(c, runner, cid, job, raw, p.name, dry)
            dest = "failed" if row.status == "failed" else "done"
        except Exception as e:  # noqa: BLE001
            row, dest = _failed(c, job, p.name, str(e) or type(e).__name__, dry, raw), "failed"
        out.append((row, raw))
        if not dry:
            (folder / dest).mkdir(exist_ok=True)
            shutil.move(str(p), str(folder / dest / p.name))
    return out


def run_job(c: Companies, jid: str, user: User | None = None, now: dt.datetime | None = None) -> list[MessageRow]:
    """Run one job now (as its owner, or ``user`` when asked from the Connections page): what it read, logged."""
    now = now or dt.datetime.now(dt.UTC)
    job = _saved(c, jid, user)
    runner = _runner(c, job)
    if runner is None:
        out = [_failed(c, job, job["source"], f"{c._name(job['run_as'])}, who made it, may no longer change this "
                                              "company: an owner should save the import again")]
    else:
        out = [row for row, _raw in _run(c, job, runner)]
    last = out[-1] if out else None
    good = bool(out) and all(r.status != "failed" for r in out)
    with c.lock:
        c.db.execute("UPDATE import_jobs SET last_run = ?, last_status = ?, last_summary = ?, next_run = ?, "
                     "cursor = ? WHERE id = ?",
                     (_iso(now), last.status if last else "nothing", last.summary if last else "no file to read",
                      _iso(next_run(job["every"], job["at"], job["weekday"], now, company_timezone(c, job["company_id"])))
                      if job["enabled"] else None, _iso(now) if good else job["cursor"], jid))
    return out


def _saved(c: Companies, jid: str, user: User | None) -> dict:
    with c.lock:
        _ensure(c)
        job = c.db.execute("SELECT * FROM import_jobs WHERE id = ? AND deleted = 0", (jid,)).fetchone()
        if job is None:
            raise CompanyError(f"no import {jid}", 404)
        if user is not None:
            c._need(user, job["company_id"], "owner")
        return dict(job)


def _message(c: Companies, user: User, cid: str, job: dict, raw: bytes, source: str, dry: bool = False) -> MessageRow:
    try:
        return _apply(c, user, cid, job, raw, source, dry).message
    except CompanyError as e:
        return _failed(c, job, source, str(e), dry, raw)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return _failed(c, job, source, str(e), dry, raw)
    except (TypeError, AttributeError, KeyError) as e:     # a file of a shape nobody foresaw (CV-M01)
        return _failed(c, job, source, f"the file cannot be read as {job['kind']}: {e}", dry, raw)


# ------------------------------------------------------------------------------------------------ dry runs
def _tried(job: dict, rows: list[tuple[MessageRow, bytes]]) -> Tried:
    raw = next((r for _row, r in rows if r), b"")
    cols: list[str] = []
    shown: list[dict[str, Any]] = []
    if raw and job["kind"].startswith("send:"):
        pass
    elif raw:
        m = _mapping_of(job)
        try:
            if job["source_type"] in apps.APPS:
                cols = apps.columns(job, raw)
                got = apps.items(job, raw, m, bool(job["day_first"]))
            else:
                cols = columns(records(job["kind"], job["format"], raw, m), m.each if m else "")
                got = parse(job["kind"], job["format"], raw, bool(job["day_first"]), m)
            shown = [x if isinstance(x, dict) else {"value": x} for x in got[:10]]
        except Exception:  # noqa: BLE001 - the message already says why it cannot be read
            pass
    return Tried(messages=[r for r, _raw in rows], columns=cols, rows=shown)


def dry_run(c: Companies, user: User, cid: str, jid: str) -> Tried:
    """What a saved import would do now: read and checked line by line, nothing saved or moved, its schedule and
    what it read last as they were."""
    job = _saved(c, jid, user)
    if job["company_id"] != cid:
        raise CompanyError(f"no import {jid} in this company", 404)
    return _tried(job, _run(c, job, user, dry=True))


class TryInput(Model):
    job: JobInput
    content: str | None = Field(None, max_length=5_000_000, description="A sample of the file or answer to try the "
                                                                        "mapping on; none: read the source now")
    id: str | None = Field(None, description="The saved import this changes: its headers and {since} are used")


def try_job(c: Companies, user: User, cid: str, body: TryInput) -> Tried:
    """An import tried before it is saved: on a sample pasted in, or on what its source gives now. Nothing is saved
    or logged; only an owner may (it reads from outside)."""
    j = body.job
    with c.lock:
        _ensure(c)
        c._need(user, cid, "owner")
    _check(c, cid, j)
    with c.lock:
        saved = None
        if body.id:
            saved = c.db.execute("SELECT * FROM import_jobs WHERE id = ? AND company_id = ? AND deleted = 0",
                                 (body.id, cid)).fetchone()
            if saved is None:
                raise CompanyError(f"no import {body.id} in this company", 404)
    same = _same(saved, j)
    headers = _kept(saved, j)
    if body.content is None or j.kind.startswith("send:"):
        _check_app(j, headers)
    mapping, paging, app = _extras(j)
    job = {"id": body.id or "new", "company_id": cid, "name": j.name, "kind": j.kind, "source_type": j.source_type,
           "source": j.source, "headers": json.dumps(headers), "format": j.format,
           "day_first": int(j.day_first), "run_as": user.id, "mapping": mapping, "paging": paging, "app": app,
           "cursor": saved["cursor"] if same and saved and saved["kind"] == j.kind else ""}
    if body.content is None or j.kind.startswith("send:"):
        return _tried(job, _run(c, job, user, dry=True))
    raw = body.content.encode()
    if j.source_type == "api":   # a sample of one page: its records are where the mapping says
        try:
            m = _mapping(job)
            raw = json.dumps(json_items(json.loads(body.content), m.items if m else "", j.kind)).encode()
        except (ValueError, json.JSONDecodeError) as e:
            return Tried(messages=[_failed(c, job, "the sample", str(e), True, raw)])
    return _tried(job, [(_message(c, user, cid, job, raw, "the sample", True), raw)])


def due(c: Companies, now: dt.datetime) -> list[str]:
    with c.lock:
        _ensure(c)
        return [r["id"] for r in c.db.execute(
            "SELECT j.id FROM import_jobs j JOIN companies co ON co.id = j.company_id WHERE j.enabled = 1 AND "
            "j.deleted = 0 AND co.deleted = 0 AND j.next_run IS NOT NULL AND j.next_run <= ? ORDER BY j.next_run",
            (_iso(now),))]


def run_due(c: Companies, now: dt.datetime | None = None) -> dict[str, list[MessageRow]]:
    """Run every job whose time has come. One job that fails in a way nobody foresaw is logged against itself and
    moved to its next time; the jobs after it still run (CV-M01)."""
    now = now or dt.datetime.now(dt.UTC)
    out: dict[str, list[MessageRow]] = {}
    for jid in due(c, now):
        try:
            out[jid] = run_job(c, jid, now=now)
        except Exception as e:  # noqa: BLE001 - one job never stops the others
            out[jid] = _gave_up(c, jid, now, str(e) or type(e).__name__)
    return out


def _gave_up(c: Companies, jid: str, now: dt.datetime, why: str) -> list[MessageRow]:
    with c.lock:
        job = c.db.execute("SELECT * FROM import_jobs WHERE id = ?", (jid,)).fetchone()
        if job is None:
            return []
        c.db.execute("UPDATE import_jobs SET last_run = ?, last_status = 'failed', last_summary = ?, next_run = ? "
                     "WHERE id = ?", (_iso(now), f"could not run: {why}"[:300],
                                      _iso(next_run(job["every"], job["at"], job["weekday"], now,
                                                    company_timezone(c, job["company_id"]))) if job["enabled"]
                                      else None, jid))
    try:
        return [_failed(c, job, job["source"], why)]
    except Exception:  # noqa: BLE001 - the job's own status says it
        return []
