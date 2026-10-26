"""Signed links to the supplier portal (Enterprise 7.2).

A planner makes a link for one supplier of one company. Whoever holds it sees that supplier's sent, open order lines
and nothing else, and can confirm or change them and send dispatch advice; the link expires (90 days by default) and
can be withdrawn. Only a hash of the link's secret is kept. What the supplier does is saved as a change made by the
person who made the link ("from the supplier portal, link L0003"), so that person must still be allowed to change
the company's data: a link stops working with its maker's rights.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
from collections.abc import Callable
from typing import Any

from ..companies import CAN_EDIT, CompanyError, Companies, User
from ..model import Dataset
from ..model.common import Out
from ..validate.lenient import lenient_checked

PREFIX = "scp_sp_"
DAYS = 90
SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_links (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL, supplier TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  last_used TEXT, uses INTEGER NOT NULL DEFAULT 0, revoked_at TEXT, revoked_by TEXT
);
"""


class PortalLink(Out):
    id: str
    supplier: str
    supplier_name: str
    prefix: str                     # the link's first characters, to tell links apart; the link is shown once
    created_by: str
    created_at: str
    expires_at: str
    last_used: str | None = None
    uses: int = 0
    revoked_at: str | None = None
    status: str = "live"            # live | expired | withdrawn
    token: str | None = None        # only in the answer that made it


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _ensure(c: Companies) -> None:
    if not getattr(c, "_portal_ready", False):
        c.db.executescript(SCHEMA)
        c._portal_ready = True  # type: ignore[attr-defined]


def _dataset(c: Companies, cid: str) -> tuple[dict, Dataset, set[str], int]:
    r = c.db.execute("SELECT dataset, revision FROM companies WHERE id = ? AND deleted = 0", (cid,)).fetchone()
    if r is None:
        raise CompanyError("this link's company no longer exists", 404)
    doc = json.loads(r["dataset"])
    ds, aside, _ = lenient_checked(doc)
    return doc, ds, {a.collection for a in aside}, r["revision"]


def _row(c: Companies, r: Any, names: dict[str, str], token: str | None = None) -> PortalLink:
    now = _now()
    status = "withdrawn" if r["revoked_at"] else "expired" if dt.datetime.fromisoformat(r["expires_at"]) <= now \
        else "live"
    return PortalLink(id=r["id"], supplier=r["supplier"], supplier_name=names.get(r["supplier"], r["supplier"]),
                      prefix=r["prefix"], created_by=c._name(r["created_by"]), created_at=r["created_at"],
                      expires_at=r["expires_at"], last_used=r["last_used"], uses=r["uses"],
                      revoked_at=r["revoked_at"], status=status, token=token)


def _names(ds: Dataset) -> dict[str, str]:
    return {loc.id: loc.name or loc.id for loc in ds.locations}


def create(c: Companies, user: User, cid: str, supplier: str, days: int = DAYS) -> PortalLink:
    """A new link for ``supplier``; the secret is in this answer only."""
    if not 1 <= days <= 366:
        raise CompanyError("a link lasts between 1 and 366 days", 422)
    with c.lock:
        _ensure(c)
        c._need(user, cid, *CAN_EDIT)
        _doc, ds, _aside, _rev = _dataset(c, cid)
        loc = ds.location_by_id.get(supplier)
        if loc is None or loc.type.value != "supplier":
            raise CompanyError(f"{supplier} is not a supplier of this company", 422)
        n = c.db.execute("SELECT COUNT(*) FROM portal_links").fetchone()[0] + 1
        lid = f"L{n:04d}"
        while c.db.execute("SELECT 1 FROM portal_links WHERE id = ?", (lid,)).fetchone():
            n += 1
            lid = f"L{n:04d}"
        token = PREFIX + secrets.token_urlsafe(32)
        now = _now()
        c.db.execute("INSERT INTO portal_links (id, company_id, supplier, token_hash, prefix, created_by, created_at, "
                     "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (lid, cid, supplier, _hash(token), token[:12], user.id, now.isoformat(),
                      (now + dt.timedelta(days=days)).isoformat()))
        c._log(cid, None, user.id, "member", f"supplier portal link {lid} made for {loc.name or supplier}, "
                                             f"{days} days")
        return _row(c, c.db.execute("SELECT * FROM portal_links WHERE id = ?", (lid,)).fetchone(), _names(ds), token)


def listing(c: Companies, user: User, cid: str) -> list[PortalLink]:
    with c.lock:
        _ensure(c)
        c._need(user, cid)
        _doc, ds, _aside, _rev = _dataset(c, cid)
        names = _names(ds)
        return [_row(c, r, names) for r in c.db.execute(
            "SELECT * FROM portal_links WHERE company_id = ? ORDER BY revoked_at IS NOT NULL, created_at DESC, id DESC",
            (cid,))]


def revoke(c: Companies, user: User, cid: str, lid: str) -> list[PortalLink]:
    with c.lock:
        _ensure(c)
        c._need(user, cid, *CAN_EDIT)
        r = c.db.execute("SELECT * FROM portal_links WHERE id = ? AND company_id = ?", (lid, cid)).fetchone()
        if r is None:
            raise CompanyError(f"no supplier portal link {lid} in this company", 404)
        if r["revoked_at"]:
            raise CompanyError(f"link {lid} was already withdrawn on {r['revoked_at'][:10]}")
        c.db.execute("UPDATE portal_links SET revoked_at = ?, revoked_by = ? WHERE id = ?",
                     (_now().isoformat(), user.id, lid))
        c._log(cid, None, user.id, "member", f"supplier portal link {lid} withdrawn")
    return listing(c, user, cid)


class Access(Out):
    link: str
    company: str
    supplier: str
    created_by: str                 # the account id the link acts as


def access(c: Companies, token: str) -> Access:
    """The company and supplier a link opens; refused when unknown, expired, withdrawn, or its maker can no longer
    change the company's data. The same answer for each, so a guess learns nothing."""
    bad = CompanyError("this link does not work (unknown, expired or withdrawn): ask your customer for a new one", 401)
    if not token or not token.startswith(PREFIX) or len(token) > 100:
        raise bad
    with c.lock:
        _ensure(c)
        r = c.db.execute("SELECT * FROM portal_links WHERE token_hash = ?", (_hash(token),)).fetchone()
        if r is None or r["revoked_at"] or dt.datetime.fromisoformat(r["expires_at"]) <= _now():
            raise bad
        try:
            role = c.role(c._user(r["created_by"]), r["company_id"], two_step=False)
        except CompanyError:
            raise bad from None
        if role not in CAN_EDIT:
            raise bad
        return Access(link=r["id"], company=r["company_id"], supplier=r["supplier"], created_by=r["created_by"])


def read(c: Companies, token: str) -> tuple[Access, Dataset]:
    a = access(c, token)
    with c.lock:
        _doc, ds, _aside, _rev = _dataset(c, a.company)
    return a, ds


def write(c: Companies, token: str, change: Callable[[Dataset, str], tuple[Dataset, Any]], what: str) -> tuple[Access, Dataset, Any]:
    """Apply a supplier's step to the company's latest save and save it as a change by the link's maker."""
    from ..connect.messages import changed_doc
    a = access(c, token)
    with c.lock:
        doc, ds, aside, rev = _dataset(c, a.company)
        new, rep = change(ds, a.supplier)
        after = changed_doc(doc, ds, new, aside)
        if after is not doc:
            name = next((x.name for x in ds.locations if x.id == a.supplier), None) or a.supplier
            c.save(c._user(a.created_by), a.company, after, rev, action="received",
                   note=f"{what} from {name} on the supplier portal (link {a.link})")
        now = _now().isoformat()
        c.db.execute("UPDATE portal_links SET last_used = ?, uses = uses + 1 WHERE id = ?", (now, a.link))
    return a, new, rep


__all__ = ["Access", "PortalLink", "access", "create", "listing", "read", "revoke", "write"]
