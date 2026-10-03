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
import shutil
import socket
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import Field

from ..companies import CompanyError, Companies, User
from ..model.common import Model, Out
from .erp import (
    ErpOrder, ErpPosting, ErpStock, ItemResult, apply_orders, apply_postings, apply_records, apply_stock, record_lists,
)
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


class JobInput(Model):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(description="orders, stock, postings or records:<list>")
    source_type: Literal["url", "folder"]
    source: str = Field(min_length=1, max_length=500, description="The web address, or the file pattern in the folder")
    headers: dict[str, str] = Field(default_factory=dict, description="A web address: headers to send (Authorization)")
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


class ImportJobs(Out):
    jobs: list[ImportJob]
    folder: str | None             # the company's folder on the server, when the server has one
    timezone: str
    kinds: list[str]


def _ensure(c: Companies) -> None:
    if not getattr(c, "_imports_ready", False):
        c.db.executescript(SCHEMA)
        c._imports_ready = True  # type: ignore[attr-defined]


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).replace(microsecond=0).isoformat()


def next_run(every: str, at: str, weekday: int, after: dt.datetime) -> dt.datetime:
    """The first time after ``after`` the schedule falls on (times of day in the server's time zone)."""
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
    if body.kind not in kinds():
        raise CompanyError(f"an import is one of {', '.join(kinds())}", 422)
    if body.source_type == "url":
        u = urlparse(body.source)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise CompanyError("a web address starts with https:// (or http://)", 422)
        allowed = _hosts()
        if allowed and u.hostname.lower() not in allowed:
            raise CompanyError(f"this server reads files only from {', '.join(allowed)}", 422)
    else:
        if import_dir() is None:
            raise CompanyError("this server has no folder for files (SCP_IMPORT_DIR): use a web address", 422)
        if "/" in body.source or "\\" in body.source or body.source.startswith("."):
            raise CompanyError("a file pattern names files in the company's folder (stock-*.csv), not other folders", 422)


def _job(c: Companies, r: Any) -> ImportJob:
    return ImportJob(id=r["id"], name=r["name"], kind=r["kind"], source_type=r["source_type"], source=r["source"],
                     header_names=sorted(json.loads(r["headers"])), format=r["format"], day_first=bool(r["day_first"]),
                     every=r["every"], at=r["at"], weekday=r["weekday"], enabled=bool(r["enabled"]),
                     run_as=c._name(r["run_as"]), next_run=r["next_run"], last_run=r["last_run"],
                     last_status=r["last_status"], last_summary=r["last_summary"])


def folder_of(cid: str) -> Path | None:
    d = import_dir()
    return d / cid if d is not None else None


def jobs(c: Companies, user: User, cid: str) -> ImportJobs:
    with c.lock:
        _ensure(c)
        c._need(user, cid)
        rows = c.db.execute("SELECT * FROM import_jobs WHERE company_id = ? AND deleted = 0 ORDER BY id", (cid,)).fetchall()
        f = folder_of(cid)
        return ImportJobs(jobs=[_job(c, r) for r in rows], folder=str(f) if f else None, timezone=timezone(),
                          kinds=kinds())


def save_job(c: Companies, user: User, cid: str, body: JobInput, jid: str | None = None,
             now: dt.datetime | None = None) -> ImportJobs:
    """Make a job, or change one (``jid``); only an owner may: a job reads from outside with the owner's rights."""
    _check(c, cid, body)
    now = now or dt.datetime.now(dt.UTC)
    with c.lock:
        _ensure(c)
        c._need(user, cid, "owner")
        nxt = _iso(next_run(body.every, body.at, body.weekday, now)) if body.enabled else None
        if jid is None:
            n = c.db.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] + 1
            jid = f"J{n:04d}"
            while c.db.execute("SELECT 1 FROM import_jobs WHERE id = ?", (jid,)).fetchone():
                n += 1
                jid = f"J{n:04d}"
            c.db.execute("INSERT INTO import_jobs (id, company_id, name, kind, source_type, source, headers, format, "
                         "day_first, every, at, weekday, enabled, run_as, created_at, next_run) VALUES "
                         "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (jid, cid, body.name, body.kind, body.source_type, body.source, json.dumps(body.headers),
                          body.format, int(body.day_first), body.every, body.at, body.weekday, int(body.enabled),
                          user.id, _iso(now), nxt))
            c._log(cid, None, user.id, "member", f"import {jid} “{body.name}” made: {body.kind} every {body.every}")
        else:
            r = c.db.execute("SELECT * FROM import_jobs WHERE id = ? AND company_id = ? AND deleted = 0",
                             (jid, cid)).fetchone()
            if r is None:
                raise CompanyError(f"no import {jid} in this company", 404)
            headers = body.headers or json.loads(r["headers"])     # values not shown again: kept unless sent
            c.db.execute("UPDATE import_jobs SET name = ?, kind = ?, source_type = ?, source = ?, headers = ?, format = ?, "
                         "day_first = ?, every = ?, at = ?, weekday = ?, enabled = ?, run_as = ?, next_run = ? "
                         "WHERE id = ?", (body.name, body.kind, body.source_type, body.source, json.dumps(headers),
                                          body.format, int(body.day_first), body.every, body.at, body.weekday,
                                          int(body.enabled), user.id, nxt, jid))
            c._log(cid, None, user.id, "member", f"import {jid} “{body.name}” changed"
                   + ("" if body.enabled else " (switched off)"))
    return jobs(c, user, cid)


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
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in row)]


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
            if v == "":
                continue
            if f in DATES:
                rec[f] = parse_date(v, day_first) or v
            elif f in NUMBERS:
                n = _num(v)
                rec[f] = n if n is not None else v
            elif f in FLAGS:
                rec[f] = v.lower() in ("1", "x", "yes", "y", "true", "ja")
            elif f == "action":
                rec[f] = ACTIONS.get(_norm(v), v.lower())
            elif f in ("stock_type", "to_type"):
                rec[f] = STOCK_TYPES.get(_norm(v), v.lower())
            else:
                rec[f] = v
        out.append(rec)
    return out


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


def parse(kind: str, fmt: str, raw: bytes, day_first: bool = True) -> list[Any]:
    """The items of a message of ``kind`` read from a file: :class:`pydantic.ValidationError` on a bad row is the
    caller's to report per item, so rows are returned as dicts for orders, stock and postings."""
    text = raw.decode("utf-8-sig", errors="replace")
    if fmt == "json":
        data = json.loads(text)
        key = {"orders": "orders", "stock": "stock", "postings": "postings"}.get(kind, "records")
        return data.get(key, []) if isinstance(data, dict) else data
    grid = read_grid(text)
    if kind.startswith("records:"):
        return _records(grid, day_first)
    if kind == "stock":
        return _stock_rows(_rows(grid, ["location", "product", "qty", "batch", "expires_on", "stock_type", "quality",
                                        "blocked"], day_first))
    if kind == "postings":
        return _rows(grid, ["ref", "action", "number", "qty", "date", "final", "location", "product", "batch",
                            "expires_on", "supplier_batch", "stock_type", "to_type", "note"], day_first)
    lines = _rows(grid, ["number", "customer", "order_date", "customer_ref", "payment_terms", "product", "qty", "date",
                         "price", "cancelled", "note"], day_first)
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
            it = {**it, "order": it.pop("number")}
        try:
            good.append(form.model_validate(it))
        except Exception as e:  # noqa: BLE001 - reported per row
            from .erp import _why
            ref = str((it or {}).get("number") or (it or {}).get("ref") or f"row {i + 2}") if isinstance(it, dict) \
                else f"row {i + 2}"
            bad.append(ItemResult(ref=ref, status="refused", message=_why(e)))
    return good, bad


def applier(kind: str, items: list[Any]) -> Callable:
    good, bad = _typed(kind, items)

    def change(ds):
        if kind == "orders":
            new, res = apply_orders(ds, good)
        elif kind == "stock":
            new, res = apply_stock(ds, good)
        elif kind == "postings":
            new, res = apply_postings(ds, good)
        else:
            new, res = apply_records(ds, kind.split(":", 1)[1], good)
        return new, [*bad, *res]
    return change


# ------------------------------------------------------------------------------------------------ running
Fetch = Callable[[str, dict[str, str]], bytes]


def _hosts() -> list[str]:
    return [x.strip().lower() for x in os.environ.get("SCP_IMPORT_HOSTS", "").split(",") if x.strip()]


def _inside(host: str) -> bool:
    """Whether a host name resolves to an address in the server's own network (or the machine itself)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False                    # no such name: reading it fails on its own
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


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
    opener = urllib.request.build_opener(_Redirect)
    with opener.open(req, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    return data


#: tests replace this to serve a file without a network
fetch: Fetch = _fetch


def _apply(c: Companies, user: User, cid: str, job: Any, raw: bytes, source: str) -> MessageAnswer:
    fingerprint = hashlib.sha256(raw).hexdigest()[:24]
    items = parse(job["kind"], job["format"], raw, bool(job["day_first"]))
    return receive(c, user, cid, job["kind"], f"{job['id']}:{fingerprint}", applier(job["kind"], items),
                   source=f"{job['id']} {job['name']}: {source}")


def _failed(c: Companies, job: Any, source: str, why: str) -> MessageRow:
    return log(c, job["company_id"], job["run_as"], "in", job["kind"], "", "failed", f"could not read {source}: {why}",
               None, [], source=f"{job['id']} {job['name']}: {source}")


def run_job(c: Companies, jid: str, user: User | None = None, now: dt.datetime | None = None) -> list[MessageRow]:
    """Run one job now (as its owner, or ``user`` when asked from the Connections page): what it read, logged."""
    now = now or dt.datetime.now(dt.UTC)
    with c.lock:
        _ensure(c)
        job = c.db.execute("SELECT * FROM import_jobs WHERE id = ? AND deleted = 0", (jid,)).fetchone()
        if job is None:
            raise CompanyError(f"no import {jid}", 404)
        if user is not None:
            c._need(user, job["company_id"], "owner")
    cid = job["company_id"]
    out: list[MessageRow] = []
    try:
        runner = c._user(job["run_as"])
        c._need(runner, cid, "owner", "planner")
    except CompanyError:
        out.append(_failed(c, job, job["source"], f"{c._name(job['run_as'])}, who made it, may no longer change this "
                                                  "company: an owner should save the import again"))
        runner = None
    if runner is not None:
        if job["source_type"] == "url":
            try:
                raw = fetch(job["source"], json.loads(job["headers"]))
            except Exception as e:  # noqa: BLE001 - the log says what went wrong
                out.append(_failed(c, job, job["source"], str(e) or type(e).__name__))
            else:
                out.append(_message(c, runner, cid, job, raw, job["source"]))
        else:
            folder = folder_of(cid)
            files = sorted(p for p in folder.glob(job["source"]) if p.is_file()) if folder and folder.is_dir() else []
            for p in files:
                try:
                    raw = p.read_bytes()
                    row = _message(c, runner, cid, job, raw, p.name)
                    dest = "failed" if row.status == "failed" else "done"
                except Exception as e:  # noqa: BLE001
                    row, dest = _failed(c, job, p.name, str(e) or type(e).__name__), "failed"
                out.append(row)
                (folder / dest).mkdir(exist_ok=True)
                shutil.move(str(p), str(folder / dest / p.name))
    last = out[-1] if out else None
    with c.lock:
        c.db.execute("UPDATE import_jobs SET last_run = ?, last_status = ?, last_summary = ?, next_run = ? WHERE id = ?",
                     (_iso(now), last.status if last else "nothing", last.summary if last else "no file to read",
                      _iso(next_run(job["every"], job["at"], job["weekday"], now)) if job["enabled"] else None, jid))
    return out


def _message(c: Companies, user: User, cid: str, job: Any, raw: bytes, source: str) -> MessageRow:
    try:
        return _apply(c, user, cid, job, raw, source).message
    except CompanyError as e:
        return _failed(c, job, source, str(e))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return _failed(c, job, source, str(e))


def due(c: Companies, now: dt.datetime) -> list[str]:
    with c.lock:
        _ensure(c)
        return [r["id"] for r in c.db.execute(
            "SELECT j.id FROM import_jobs j JOIN companies co ON co.id = j.company_id WHERE j.enabled = 1 AND "
            "j.deleted = 0 AND co.deleted = 0 AND j.next_run IS NOT NULL AND j.next_run <= ? ORDER BY j.next_run",
            (_iso(now),))]


def run_due(c: Companies, now: dt.datetime | None = None) -> dict[str, list[MessageRow]]:
    """Run every job whose time has come."""
    now = now or dt.datetime.now(dt.UTC)
    return {jid: run_job(c, jid, now=now) for jid in due(c, now)}
