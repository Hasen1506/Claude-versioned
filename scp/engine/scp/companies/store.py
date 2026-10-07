"""Companies kept on the server (Q14): accounts, sign-in, members with roles, every save as a revision, and an
audit trail of who changed what.

* **Accounts.** An e-mail and a password (PBKDF2-SHA256, salted); signing in gives a session token, of which only
  the SHA-256 is stored. Sessions last 30 days from their last use.
* **Members.** Each company has members: an *owner* (changes the data and who may see it), a *planner* (changes the
  data) or a *viewer* (reads it). An owner can invite an e-mail that has no account yet; the invitation becomes a
  membership when that address signs up or signs in. A company always keeps at least one owner.
* **Saves.** The working copy is saved with the revision it was based on, as what changed since that revision (a
  patch, :mod:`scp.companies.patch`) or whole. A save based on an older revision than the company's is refused
  (someone else saved in between), so nobody overwrites a colleague's work without seeing it; but a save from the
  same window as the saves in between (a reload while a save was on its way) is its own work and is taken (R18). An
  unchanged document is not a new revision.
* **Revisions.** Every save is a revision, and every revision is kept (R19): as what changed since the one before,
  compressed, with a whole copy every so often. A company can be opened as it was at any revision, and put back to
  it (a new revision, nothing is lost). Revisions saved before this (Phase I kept one per ten-minute run) stay as
  they were.
* **Audit trail.** Every save, restore, membership change and deletion is logged with who, when, and for a save,
  what changed: records added, removed and changed per list, with the first few records by name.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import zlib
from typing import Any
from collections.abc import Callable

from ..model.common import Out
from ..versions.diff import diff_raw
from ..versions.store import Store, get_store, sha
from .guards import ReleaseRefused, check_releases, record_credit_releases
from .merge import MergeReport, merge
from .patch import PatchError, apply_patch, make_patch
from .rights import MAX_CHANGE_ROWS, Stale, apply_held, field_changes, out_of_scope, split_master

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
  pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id),
  updated_at TEXT NOT NULL, updated_by TEXT NOT NULL REFERENCES users(id), revision INTEGER NOT NULL,
  sha256 TEXT NOT NULL, size INTEGER NOT NULL, dataset TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS company_revisions (
  company_id TEXT NOT NULL REFERENCES companies(id), revision INTEGER NOT NULL, at TEXT NOT NULL,
  started_at TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
  sha256 TEXT NOT NULL, size INTEGER NOT NULL, data BLOB NOT NULL, PRIMARY KEY (company_id, revision)
);
CREATE TABLE IF NOT EXISTS members (
  company_id TEXT NOT NULL REFERENCES companies(id), user_id TEXT NOT NULL REFERENCES users(id),
  role TEXT NOT NULL CHECK (role IN ('owner', 'planner', 'viewer')), added_at TEXT NOT NULL, added_by TEXT,
  PRIMARY KEY (company_id, user_id)
);
CREATE TABLE IF NOT EXISTS invites (
  company_id TEXT NOT NULL REFERENCES companies(id), email TEXT NOT NULL COLLATE NOCASE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'planner', 'viewer')), invited_by TEXT NOT NULL, at TEXT NOT NULL,
  PRIMARY KEY (company_id, email)
);
CREATE TABLE IF NOT EXISTS company_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL REFERENCES companies(id), revision INTEGER,
  at TEXT NOT NULL, user_id TEXT NOT NULL, action TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS company_log_by_company ON company_log (company_id, seq);
CREATE TABLE IF NOT EXISTS change_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL REFERENCES companies(id), at TEXT NOT NULL,
  user_id TEXT NOT NULL, revision INTEGER NOT NULL, data BLOB NOT NULL, summary TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', decided_by TEXT, decided_at TEXT, note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS change_requests_by_company ON change_requests (company_id, status, id);
CREATE TABLE IF NOT EXISTS change_docs (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, revision INTEGER NOT NULL, at TEXT NOT NULL,
  user_id TEXT NOT NULL, list TEXT NOT NULL, record TEXT NOT NULL, field TEXT NOT NULL, old TEXT, new TEXT
);
CREATE INDEX IF NOT EXISTS change_docs_by_record ON change_docs (company_id, list, record, seq);
CREATE INDEX IF NOT EXISTS change_docs_by_revision ON change_docs (company_id, revision);
CREATE TABLE IF NOT EXISTS password_resets (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL, made_by TEXT, used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS api_keys (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id), user_id TEXT NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, role TEXT NOT NULL, prefix TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL, last_used TEXT, revoked_at TEXT, revoked_by TEXT
);
CREATE TABLE IF NOT EXISTS erp_withdrawn (
  company_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, erp_ref TEXT NOT NULL, location TEXT NOT NULL,
  at TEXT NOT NULL, user_id TEXT NOT NULL, taken_at TEXT, generation TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (company_id, kind, id)
);
CREATE TABLE IF NOT EXISTS sign_in_states (
  state TEXT PRIMARY KEY, verifier TEXT NOT NULL, nonce TEXT NOT NULL, at TEXT NOT NULL, next TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS email_checks (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL COLLATE NOCASE, expires_at TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0
);
"""

ROLES = ("owner", "planner", "viewer")
CAN_EDIT = ("owner", "planner")
SESSION_DAYS = 30
SESSION_MAX_DAYS = 90         # a session ends this long after sign-in however often it is used
INVITE_DAYS = 14              # an invitation link is valid this long
FAILURE_KEYS = 10_000         # most addresses the sign-in failure counter remembers (oldest dropped first)
FULL_EVERY = 25               # a whole copy at least every this many revisions; deltas in between
PBKDF2_ROUNDS = 200_000
LOG_ITEMS = 12                # records named per list in a save's detail
KEY_PREFIX = "scpk_"           # an integration key, not a session (Phase Q)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# PBKDF2 is CPU-bound: run at most this many at once, and never under the store's lock (CV-H11)
_HASHING = threading.BoundedSemaphore(max(1, (os.cpu_count() or 2) // 2))

def erp_records(doc: dict) -> dict[tuple[str, str], dict]:
    """Order records by integration identity, including ones the ERP has not numbered yet."""
    out: dict[tuple[str, str], dict] = {}
    # a cancelled order's header is kept in cancelled_purchase_orders and goes to the ERP as cancelled from there:
    # it is not withdrawn
    for p in [*(doc.get("purchase_orders") or []), *(doc.get("cancelled_purchase_orders") or [])]:
        if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"]:
            out[("purchase_order", p["id"])] = p
    for r in doc.get("receipts") or []:
        if (isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"]
                and r.get("kind") in ("production", "transfer")):
            out[(f"{r['kind']}_order", r["id"])] = r
    return out


def erp_orders(doc: dict) -> dict[tuple[str, str], tuple[str, str]]:
    """The orders of a company's data the ERP has numbered: (kind, id) → (the ERP's number, the place)."""
    return {key: (r["erp_ref"], str(r.get("location") or "")) for key, r in erp_records(doc).items() if r.get("erp_ref")}


# plain names of the dataset's lists, for the audit trail
LABELS = {
    "locations": "places", "products": "products", "customer_prices": "customer prices",
    "location_products": "planning policies", "resources": "machines", "production_sources": "ways to make",
    "purchasing_sources": "ways to buy", "lanes": "routes", "vendors": "suppliers", "purchase_orders": "purchase orders",
    "customers": "customers", "payment_terms": "payment terms", "sales_orders": "sales orders",
    "quotations": "quotations", "deliveries": "deliveries", "invoices": "invoices and credit notes", "returns": "returns",
    "contracts": "contracts", "supplier_invoices": "supplier invoices", "supplier_returns": "returns to suppliers",
    "cancelled_purchase_orders": "purchase order cancellations",
    "sales": "sales settings",
    "demand": "orders and forecasts", "receipts": "open orders", "history": "sales history", "events": "events",
    "npi": "new products", "overrides": "forecast overrides", "stock_targets": "stock targets",
    "changeovers": "changeovers", "allocations": "allocations", "confirmations": "promises", "movements": "goods movements",
    "batches": "batches", "inventory_docs": "physical inventory documents",
    "closed_orders": "closed orders", "accuracy": "forecast accuracy", "rolled_weeks": "weeks moved forward",
    "calendars": "calendars", "settings": "company settings", "forecasting": "forecast settings",
    "inventory": "stock settings", "sop": "capacity plan settings", "scheduling": "shop floor settings",
    "promising": "promising settings", "execution": "execution settings", "purchasing": "buying settings",
    "finance": "money settings", "tower": "performance settings",
}


class CompanyError(Exception):
    """A request the rules do not allow; ``status`` is its HTTP status (401 not signed in, 403 not allowed, 404
    unknown, 409 conflict)."""

    def __init__(self, message: str, status: int = 409, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.extra = extra or {}


class User(Out):
    id: str
    email: str
    name: str
    verified: bool = False        # the account has shown it receives mail at this address (a link, or the sign-on)


class PendingInvite(Out):
    """An invitation to a company waiting for the account to accept it (nobody joins a company unasked)."""
    company: str
    name: str                     # the company's name
    role: str
    invited_by: str               # a name
    at: str


class Session(Out):
    token: str
    user: User
    expires_at: str


class CompanyMeta(Out):
    id: str
    name: str
    role: str
    revision: int
    updated_at: str
    updated_by: str               # a name
    created_at: str
    size: int
    approval: bool = False        # master-data changes wait for a second person's approval
    pending: int = 0              # changes waiting for approval
    places: list[str] = []        # the asker's rights are limited to these places (empty: all)
    families: list[str] = []      # … and these product groups (empty: all)


class CompanyDoc(Out):
    meta: CompanyMeta
    dataset: dict[str, Any]


class FieldChangeRow(Out):
    """One field of one record changed (a change document)."""
    seq: int = 0
    revision: int | None = None
    at: str = ""
    user: str = ""
    list: str                     # a plain name
    record: str                   # the record's key ("PAINT-WHITE", "PLT-PUNE | PAINT-WHITE"); "" for settings
    field: str                    # "price", "lines[0].qty"; "" for a whole record added or removed
    old: Any = None
    new: Any = None


class HeldChange(Out):
    """A master-data change waiting for a second person's approval."""
    id: int
    at: str
    by: str                       # a name
    by_me: bool
    summary: str
    status: str                   # pending | approved | rejected | withdrawn
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""
    changes: list[FieldChangeRow] = []


class SaveReport(Out):
    meta: CompanyMeta
    saved: bool                   # False: nothing had changed
    summary: str
    own: bool = False             # the saves it replaced were this window's own (a reload while one was on its way)
    held: HeldChange | None = None        # the master-data part of the save, waiting for approval
    dataset: dict[str, Any] | None = None  # when something was held: the company as saved (take it as the working copy)


class MergeResult(Out):
    meta: CompanyMeta
    dataset: dict[str, Any]       # the merged company, now its latest save (as it would be, for a preview)
    report: MergeReport
    merged_with: str              # whose save it was merged with (a name); "you" when both were one's own
    saved: bool = True            # False: a preview, nothing saved
    held: HeldChange | None = None   # its master-data part, waiting for approval


class Member(Out):
    user_id: str | None           # None: invited, no account yet
    email: str
    name: str
    role: str
    since: str
    places: list[str] = []        # may change only records at these places (empty: every place)
    families: list[str] = []      # … of these product groups (empty: every group)
    invite_link: str | None = None  # only in the answer that made the invitation: the link to hand over (once)


class ListChange(Out):
    list: str                     # a plain name
    added: int
    removed: int
    changed: int
    names: list[str]              # the first few records, "+ SO-00012", "~ PAINT-WHITE at DC-MUMBAI", …


class ApiKey(Out):
    """A key another system (an ERP, a scheduled import) uses to work in one company as a member (Phase Q)."""
    id: str
    name: str
    role: str                     # planner (sends data) or viewer (only takes orders back)
    prefix: str                   # the key's first characters, to tell keys apart; the key itself is shown once
    created_by: str               # a name
    created_at: str
    last_used: str | None = None
    revoked_at: str | None = None
    token: str | None = None      # only in the answer that made it


class LogRow(Out):
    seq: int
    revision: int | None
    at: str
    user: str                     # a name
    action: str                   # created | saved | restored | member | deleted
    summary: str
    changes: list[ListChange]
    kept: bool                    # this revision's document is kept: it can be opened and put back


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _canonical(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_pw(password: str, salt: str) -> str:
    with _HASHING:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _company_name(doc: dict) -> str:
    s = doc.get("settings")
    name = s.get("company_name") if isinstance(s, dict) else None
    if name is not None and not isinstance(name, str):
        raise CompanyError("company name must be text", 422)
    return (name or "").strip() or "Unnamed company"


def summarise(before: dict | None, after: dict) -> tuple[str, list[ListChange]]:
    """What a save changed, in plain words, and per list."""
    if before is None:
        return "", []
    d = diff_raw(before, after)
    out: list[ListChange] = []
    for c in d.collections:
        names = [("+ " if i.change == "added" else "− " if i.change == "removed" else "~ ") + i.key.replace(" | ", " ")
                 for i in c.items[:LOG_ITEMS]]
        out.append(ListChange(list=LABELS.get(c.collection, c.collection.replace("_", " ")), added=c.added,
                              removed=c.removed, changed=c.changed, names=names))
    parts = []
    for c in out:
        if c.list.endswith("settings") and not (c.added or c.removed):
            parts.append(f"{c.list} changed")
            continue
        bits = [f"{n} {w}" for n, w in ((c.added, "added"), (c.removed, "removed"), (c.changed, "changed")) if n]
        parts.append(f"{c.list}: {', '.join(bits)}")
    return "; ".join(parts), out


class Companies:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.db = store.db
        self.lock = store.lock
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(company_revisions)")}
        if "kind" not in cols:        # Phase L: deltas between whole copies, and the window each save came from
            self.db.execute("ALTER TABLE company_revisions ADD COLUMN kind TEXT NOT NULL DEFAULT 'full'")
        if "client" not in cols:
            self.db.execute("ALTER TABLE company_revisions ADD COLUMN client TEXT NOT NULL DEFAULT ''")
        for table in ("members", "invites"):  # Phase L: rights limited to places and product groups
            have = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for col in ("places", "families"):
                if col not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT NOT NULL DEFAULT '[]'")
        if "approval" not in {r[1] for r in self.db.execute("PRAGMA table_info(companies)")}:
            self.db.execute("ALTER TABLE companies ADD COLUMN approval INTEGER NOT NULL DEFAULT 0")
        ucols = {r[1] for r in self.db.execute("PRAGMA table_info(users)")}
        if "sso_subject" not in ucols:
            self.db.execute("ALTER TABLE users ADD COLUMN sso_subject TEXT")
        if "kind" not in ucols:      # Phase Q: an account behind an integration key is not a person
            self.db.execute("ALTER TABLE users ADD COLUMN kind TEXT NOT NULL DEFAULT 'person'")
        if "verified_at" not in ucols:   # CV-C01: the address is shown to be the account holder's
            self.db.execute("ALTER TABLE users ADD COLUMN verified_at TEXT")
        icols = {r[1] for r in self.db.execute("PRAGMA table_info(invites)")}
        if "token_hash" not in icols:    # CV-C01: an invitation is accepted with its link, never by e-mail match
            self.db.execute("ALTER TABLE invites ADD COLUMN token_hash TEXT")
        if "expires_at" not in icols:
            self.db.execute("ALTER TABLE invites ADD COLUMN expires_at TEXT")
        if "generation" not in {r[1] for r in self.db.execute("PRAGMA table_info(erp_withdrawn)")}:
            self.db.execute("ALTER TABLE erp_withdrawn ADD COLUMN generation TEXT NOT NULL DEFAULT ''")
        self.failures: dict[str, list[dt.datetime]] = {}

    # ---- accounts ------------------------------------------------------------------------------------------
    def _user(self, uid: str) -> User:
        r = self.db.execute("SELECT id, email, name, verified_at FROM users WHERE id = ?", (uid,)).fetchone()
        if r is None:
            raise CompanyError("that account no longer exists", 401)
        return User(id=r["id"], email=r["email"], name=r["name"], verified=bool(r["verified_at"]))

    def _fail(self, key: str, recent: list[dt.datetime]) -> None:
        """Remember failures (only real ones) for ``key``, keeping the map bounded (CV-M05; the lock is held)."""
        if recent:
            self.failures.pop(key, None)
            self.failures[key] = recent
            while len(self.failures) > FAILURE_KEYS:
                self.failures.pop(next(iter(self.failures)))
        else:
            self.failures.pop(key, None)

    def auth_rate(self, key: str, per_minute: int) -> bool:
        """Whether one more sign-in, sign-up or reset from ``key`` (a client address) fits ``per_minute`` (CV-H11)."""
        if per_minute <= 0:
            return True
        now = _now()
        with self.lock:
            recent = [t for t in self.failures.get("rate:" + key, []) if now - t < dt.timedelta(minutes=1)]
            if len(recent) >= per_minute:
                self._fail("rate:" + key, recent)
                return False
            self._fail("rate:" + key, [*recent, now])
            return True

    def _name(self, uid: str) -> str:
        r = self.db.execute("SELECT name, email FROM users WHERE id = ?", (uid,)).fetchone()
        return (r["name"] or r["email"]) if r else uid

    def users(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def signup(self, email: str, name: str, password: str, policy: str = "open") -> Session:
        email = email.strip()
        if not EMAIL.match(email):
            raise CompanyError("that does not look like an e-mail address", 422)
        if len(password) < 8:
            raise CompanyError("a password needs at least 8 characters", 422)
        with self.lock:
            self._may_sign_up(email, policy)
        salt = secrets.token_hex(16)
        pw_hash = _hash_pw(password, salt)       # outside the lock: nobody else waits for it (CV-H11)
        with self.lock:
            self._may_sign_up(email, policy)
            return self._session(self._new_user(email, name, salt, pw_hash, policy))

    def _may_sign_up(self, email: str, policy: str) -> None:
        if self.db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise CompanyError("there is already an account for that e-mail; sign in instead")
        self._policy(email, policy)

    def _policy(self, email: str, policy: str) -> None:
        if policy == "closed" and self.users():
            raise CompanyError("new accounts are switched off on this server; ask its administrator", 403)
        if policy == "invite" and self.users() and not self.db.execute(
                "SELECT 1 FROM invites WHERE email = ?", (email,)).fetchone():
            raise CompanyError("this server takes new accounts by invitation only: ask a company owner to invite "
                               "your e-mail", 403)

    def _new_user(self, email: str, name: str, salt: str, pw_hash: str, policy: str, subject: str | None = None) -> str:
        """Make an account the sign-up policy allows (the lock is held)."""
        self._policy(email, policy)
        n = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        uid = f"U{n + 1:04d}"
        while self.db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
            n += 1
            uid = f"U{n + 1:04d}"
        self.db.execute("INSERT INTO users (id, email, name, pw_salt, pw_hash, created_at, sso_subject) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (uid, email, name.strip() or email.split("@")[0], salt, pw_hash, _iso(_now()), subject))
        return uid

    def signin(self, email: str, password: str) -> Session:
        email = email.strip().lower()
        now = _now()
        with self.lock:
            recent = [t for t in self.failures.get(email, []) if now - t < dt.timedelta(minutes=15)]
            self._fail(email, recent)
            if len(recent) >= 10:
                raise CompanyError("too many wrong passwords for that e-mail; try again in 15 minutes", 429)
            r = self.db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if r is not None and not r["pw_hash"]:
                raise CompanyError("this account signs in with the company's single sign-on, not a password", 401)
        # the hash is worked out outside the lock (CV-H11)
        good = r is not None and hmac.compare_digest(_hash_pw(password, r["pw_salt"]), r["pw_hash"])
        with self.lock:
            if not good:
                recent = [t for t in self.failures.get(email, []) if now - t < dt.timedelta(minutes=15)]
                self._fail(email, [*recent, now])
                raise CompanyError("the e-mail or the password is not right", 401)
            cur = self.db.execute("SELECT pw_hash FROM users WHERE id = ?", (r["id"],)).fetchone()
            if cur is None or cur["pw_hash"] != r["pw_hash"]:      # the password changed meanwhile
                raise CompanyError("the e-mail or the password is not right", 401)
            self.failures.pop(email, None)
            return self._session(r["id"])

    def _session(self, uid: str) -> Session:
        token = secrets.token_urlsafe(32)
        now = _now()
        exp = now + dt.timedelta(days=SESSION_DAYS)
        self.db.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                        (_token_hash(token), uid, _iso(now), _iso(exp)))
        # CV-C01: invitations are no longer taken on by e-mail match when a session starts; the account accepts
        # each one (pending_invites / accept_invite)
        return Session(token=token, user=self._user(uid), expires_at=_iso(exp))

    # ---- invitations and e-mail ownership (CV-C01) -------------------------------------------------------------
    def _join(self, uid: str, r: Any) -> None:
        """Make the accepted invitation ``r`` a membership (the lock is held)."""
        self.db.execute("INSERT OR IGNORE INTO members (company_id, user_id, role, added_at, added_by, places, families) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (r["company_id"], uid, r["role"], _iso(_now()), r["invited_by"],
                                                        r["places"], r["families"]))
        self.db.execute("DELETE FROM invites WHERE company_id = ? AND email = ?", (r["company_id"], r["email"]))
        self._log(r["company_id"], None, uid, "member", f"{self._name(uid)} accepted the invitation and joined as "
                                                        f"{r['role']}")

    def pending_invites(self, user: User) -> list[PendingInvite]:
        """Invitations to the account's address it may accept without a link: only once the address is verified."""
        with self.lock:
            if not self._user(user.id).verified:
                return []
            return [PendingInvite(company=r["company_id"], name=r["name"], role=r["role"],
                                  invited_by=self._name(r["invited_by"]), at=r["at"])
                    for r in self.db.execute("SELECT i.*, c.name FROM invites i JOIN companies c ON c.id = i.company_id "
                                             "WHERE i.email = ? AND c.deleted = 0 ORDER BY i.at", (user.email,))]

    def accept_invite(self, user: User, token: str = "", cid: str = "") -> CompanyMeta:
        """Join a company the account was invited to: with the invitation's link (``token``), or, when the account's
        address is verified, by the company's id. The invitation must be for this account's address."""
        if self.is_key(user):
            raise CompanyError("a key cannot accept invitations", 403)
        with self.lock:
            if token:
                r = self.db.execute("SELECT * FROM invites WHERE token_hash = ?", (_token_hash(token),)).fetchone()
            elif cid:
                if not self._user(user.id).verified:
                    raise CompanyError("confirm your e-mail address first, or open the invitation's link", 403)
                r = self.db.execute("SELECT * FROM invites WHERE company_id = ? AND email = ?", (cid, user.email)).fetchone()
            else:
                raise CompanyError("say which invitation to accept", 422)
            if r is None or (r["expires_at"] and dt.datetime.fromisoformat(r["expires_at"]) <= _now()):
                raise CompanyError("this invitation has expired or was withdrawn: ask the company's owner for a new one",
                                   410)
            if r["email"].lower() != user.email.lower():
                raise CompanyError(f"this invitation is for {r['email']}: sign in with that address to accept it", 403)
            c = self.db.execute("SELECT deleted FROM companies WHERE id = ?", (r["company_id"],)).fetchone()
            if c is None or c["deleted"]:
                raise CompanyError("that company no longer exists", 410)
            self._join(user.id, r)
            return self._meta(r["company_id"], r["role"], user.id)

    def email_token(self, user: User, hours: float = 24) -> str:
        """A one-time token that proves the account receives mail at its address, to send there."""
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.db.execute("INSERT INTO email_checks (token_hash, user_id, email, expires_at) VALUES (?, ?, ?, ?)",
                            (_token_hash(token), user.id, user.email, _iso(_now() + dt.timedelta(hours=hours))))
        return token

    def verify_email(self, token: str) -> User:
        with self.lock:
            r = self.db.execute("SELECT * FROM email_checks WHERE token_hash = ?", (_token_hash(token),)).fetchone()
            if r is None or r["used"] or dt.datetime.fromisoformat(r["expires_at"]) <= _now():
                raise CompanyError("this link has expired or was used already: ask for a new one", 410)
            u = self.db.execute("SELECT email FROM users WHERE id = ?", (r["user_id"],)).fetchone()
            if u is None or u["email"].lower() != r["email"].lower():
                raise CompanyError("this link was for another address", 410)
            self.db.execute("UPDATE email_checks SET used = 1 WHERE token_hash = ?", (r["token_hash"],))
            self.db.execute("UPDATE users SET verified_at = ? WHERE id = ?", (_iso(_now()), r["user_id"]))
            return self._user(r["user_id"])

    def whoami(self, token: str | None) -> User:
        """The account a session token belongs to; the session is extended on use."""
        if not token:
            raise CompanyError("sign in first", 401)
        if token.startswith(KEY_PREFIX):
            return self._key_user(token)
        with self.lock:
            r = self.db.execute("SELECT * FROM sessions WHERE token_hash = ?", (_token_hash(token),)).fetchone()
            now = _now()
            if r is None or dt.datetime.fromisoformat(r["expires_at"]) <= now:
                raise CompanyError("your sign-in has expired; sign in again", 401)
            ends = dt.datetime.fromisoformat(r["created_at"]) + dt.timedelta(days=SESSION_MAX_DAYS)
            if ends <= now:                                         # CV-L06: an absolute lifetime
                self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (r["token_hash"],))
                raise CompanyError("your sign-in has expired; sign in again", 401)
            self.db.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                            (_iso(min(now + dt.timedelta(days=SESSION_DAYS), ends)), r["token_hash"]))
            self.db.execute("UPDATE users SET last_seen = ? WHERE id = ?", (_iso(now), r["user_id"]))
            return self._user(r["user_id"])

    # ---- integration keys (Phase Q) --------------------------------------------------------------------------
    def _key_user(self, token: str) -> User:
        with self.lock:
            r = self.db.execute("SELECT k.*, c.deleted FROM api_keys k JOIN companies c ON c.id = k.company_id "
                                "WHERE k.token_hash = ?", (_token_hash(token),)).fetchone()
            if r is None or r["revoked_at"] or r["deleted"]:
                raise CompanyError("this key is not valid (unknown or withdrawn): ask the company's owner for a new "
                                   "one", 401)
            now = _iso(_now())
            if not r["last_used"] or r["last_used"][:16] != now[:16]:   # once a minute is enough
                self.db.execute("UPDATE api_keys SET last_used = ? WHERE id = ?", (now, r["id"]))
            return self._user(r["user_id"])

    def is_key(self, user: User) -> bool:
        with self.lock:
            r = self.db.execute("SELECT kind FROM users WHERE id = ?", (user.id,)).fetchone()
            return bool(r) and r["kind"] == "key"

    def key_company(self, user: User) -> str | None:
        """The company a key's account works in (a key belongs to one company), else None."""
        with self.lock:
            r = self.db.execute("SELECT company_id FROM api_keys WHERE user_id = ? AND revoked_at IS NULL",
                                (user.id,)).fetchone()
            return r["company_id"] if r else None

    def _key_row(self, r: Any, token: str | None = None) -> ApiKey:
        return ApiKey(id=r["id"], name=r["name"], role=r["role"], prefix=r["prefix"],
                      created_by=self._name(r["created_by"]), created_at=r["created_at"], last_used=r["last_used"],
                      revoked_at=r["revoked_at"], token=token)

    def create_key(self, user: User, cid: str, name: str, role: str = "planner") -> ApiKey:
        """A new key for another system, acting as a member of this company with ``role``; only an owner may."""
        name = " ".join(name.split())[:60]
        if not name:
            raise CompanyError("name the key after the system that uses it (\"SAP\", \"Nightly stock file\")", 422)
        if role not in ("planner", "viewer"):
            raise CompanyError("a key is a planner (it sends data) or a viewer (it only reads)", 422)
        with self.lock:
            self._need(user, cid, "owner")
            n = self.db.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0] + 1
            kid = f"K{n:04d}"
            while self.db.execute("SELECT 1 FROM api_keys WHERE id = ?", (kid,)).fetchone():
                n += 1
                kid = f"K{n:04d}"
            token = KEY_PREFIX + secrets.token_urlsafe(32)
            now = _iso(_now())
            self.db.execute("BEGIN")
            try:
                m = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                uid = f"U{m + 1:04d}"
                while self.db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
                    m += 1
                    uid = f"U{m + 1:04d}"
                self.db.execute("INSERT INTO users (id, email, name, pw_salt, pw_hash, created_at, kind) "
                                "VALUES (?, ?, ?, '', '', ?, 'key')",
                                (uid, f"{kid.lower()}.{cid.lower()}@keys.invalid", f"{name} (key)", now))
                self.db.execute("INSERT INTO members (company_id, user_id, role, added_at, added_by) VALUES (?, ?, ?, ?, ?)",
                                (cid, uid, role, now, user.id))
                self.db.execute("INSERT INTO api_keys (id, company_id, user_id, name, role, prefix, token_hash, created_by, "
                                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (kid, cid, uid, name, role, token[:12], _token_hash(token), user.id, now))
                self._log(cid, None, user.id, "member", f"key {kid} \u201c{name}\u201d made, as a {role}")
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return self._key_row(self.db.execute("SELECT * FROM api_keys WHERE id = ?", (kid,)).fetchone(), token)

    def keys(self, user: User, cid: str) -> list[ApiKey]:
        with self.lock:
            self._need(user, cid, "owner")
            return [self._key_row(r) for r in self.db.execute(
                "SELECT * FROM api_keys WHERE company_id = ? ORDER BY revoked_at IS NOT NULL, created_at, id", (cid,))]

    def revoke_key(self, user: User, cid: str, kid: str) -> list[ApiKey]:
        with self.lock:
            self._need(user, cid, "owner")
            r = self.db.execute("SELECT * FROM api_keys WHERE id = ? AND company_id = ?", (kid, cid)).fetchone()
            if r is None:
                raise CompanyError(f"no key {kid} in this company", 404)
            if r["revoked_at"]:
                raise CompanyError(f"key {kid} was already withdrawn on {r['revoked_at'][:10]}")
            self.db.execute("UPDATE api_keys SET revoked_at = ?, revoked_by = ? WHERE id = ?", (_iso(_now()), user.id, kid))
            self.db.execute("DELETE FROM members WHERE company_id = ? AND user_id = ?", (cid, r["user_id"]))
            self._log(cid, None, user.id, "member", f"key {kid} \u201c{r['name']}\u201d withdrawn")
        return self.keys(user, cid)

    def signout(self, token: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def _set_password(self, uid: str, new: str, keep_token: str | None = None, salt: str = "",
                      pw_hash: str = "") -> None:
        """Change credentials and revoke recovery links and other sessions atomically (the lock is held; pass the
        salt and hash worked out beforehand, outside it)."""
        if not salt:
            salt = secrets.token_hex(16)
            pw_hash = _hash_pw(new, salt)
        self.db.execute("BEGIN")
        try:
            self.db.execute("UPDATE users SET pw_salt = ?, pw_hash = ? WHERE id = ?", (salt, pw_hash, uid))
            self.db.execute("UPDATE password_resets SET used = 1 WHERE user_id = ?", (uid,))
            self.db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                            (uid, _token_hash(keep_token) if keep_token else ""))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def change_password(self, user: User, old: str, new: str, keep_token: str | None = None) -> None:
        if len(new) < 8:
            raise CompanyError("a password needs at least 8 characters", 422)
        with self.lock:
            r = self.db.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
        if not hmac.compare_digest(_hash_pw(old, r["pw_salt"]), r["pw_hash"]):
            raise CompanyError("the current password is not right", 403)
        salt = secrets.token_hex(16)
        pw_hash = _hash_pw(new, salt)
        with self.lock:
            self._set_password(user.id, new, keep_token, salt=salt, pw_hash=pw_hash)

    # ---- a forgotten password and single sign-on (Phase L) ---------------------------------------------------
    def reset_token(self, email: str, made_by: str | None = None, hours: float = 1) -> str | None:
        """A one-time token to set a new password for the account with this e-mail (None: no such account)."""
        with self.lock:
            r = self.db.execute("SELECT id, pw_hash, kind FROM users WHERE email = ?", (email.strip(),)).fetchone()
            if r is None or not r["pw_hash"] or r["kind"] != "person":
                return None
            token = secrets.token_urlsafe(24)
            self.db.execute("INSERT INTO password_resets (token_hash, user_id, expires_at, made_by) VALUES (?, ?, ?, ?)",
                            (_token_hash(token), r["id"], _iso(_now() + dt.timedelta(hours=hours)), made_by))
            return token

    def request_reset(self, email: str, link: Callable[[str], str], send: Callable[[str, str, str], None]) -> None:
        """Mail a reset link to the address if it has an account (and say nothing either way). At most five an hour."""
        key = "reset:" + email.strip().lower()
        now = _now()
        with self.lock:
            recent = [t for t in self.failures.get(key, []) if now - t < dt.timedelta(hours=1)]
            self._fail(key, recent + [now])
            if len(recent) >= 5:
                return
        token = self.reset_token(email)
        if token:
            send(email.strip(), "Set a new password",
                 f"Someone (we hope you) asked to set a new password for {email.strip()}.\n\n"
                 f"Open this link within an hour to choose one:\n{link(token)}\n\n"
                 "If you did not ask, ignore this mail: your password stays as it is.")

    def member_reset(self, user: User, cid: str, email: str, hours: float = 24) -> tuple[str, str]:
        """An owner makes a reset token for a planner or viewer of their company (to hand over when the server sends
        no mail). Returns the token and when it expires."""
        with self.lock:
            self._need(user, cid, "owner")
            r = self.db.execute("SELECT m.role, m.added_by, u.id, u.created_at FROM members m JOIN users u ON "
                                "u.id = m.user_id WHERE m.company_id = ? AND u.email = ?", (cid, email.strip())).fetchone()
            if r is None:
                raise CompanyError(f"{email} has no account in this company", 404)
            # CV-H01: only a member who accepted this company's invitation (a membership is never made without the
            # account's consent any more), and whose account holds nothing elsewhere: not a member of any other
            # company (deleted ones included), no other company's invitation accepted, no company of its own
            if r["id"] != user.id and self.db.execute(
                    "SELECT 1 FROM companies WHERE created_by = ? AND id != ?", (r["id"], cid)).fetchone():
                raise CompanyError("this account has companies of its own: its password must be reset by the account "
                                   "holder (Forgot your password) or the server administrator", 403)
            if r["role"] == "owner" and r["id"] != user.id:
                raise CompanyError("an owner's password is reset by the owner (Forgot your password) or the server's "
                                   "administrator", 403)
            if r["id"] != user.id and self.db.execute(
                    "SELECT 1 FROM members WHERE user_id = ? AND company_id != ?", (r["id"], cid)).fetchone():
                raise CompanyError("this account also belongs to another company: its password must be reset by "
                                   "the account holder (Forgot your password) or the server administrator", 403)
            token = self.reset_token(email, made_by=user.id, hours=hours)
            if token is None:
                raise CompanyError("this account signs in through single sign-on or an integration key; "
                                   "its credentials are managed there", 403)
            self._log(cid, None, user.id, "member", f"a link to set a new password was made for {self._name(r['id'])}")
            return token or "", _iso(_now() + dt.timedelta(hours=hours))

    def reset_password(self, token: str, new: str) -> Session:
        if len(new) < 8:
            raise CompanyError("a password needs at least 8 characters", 422)
        salt = secrets.token_hex(16)
        pw_hash = _hash_pw(new, salt)            # outside the lock (CV-H11)
        with self.lock:
            r = self.db.execute("SELECT * FROM password_resets WHERE token_hash = ?", (_token_hash(token),)).fetchone()
            if r is None or r["used"] or dt.datetime.fromisoformat(r["expires_at"]) <= _now():
                raise CompanyError("this link has expired or was used already: ask for a new one", 410)
            account = self.db.execute("SELECT pw_hash, kind FROM users WHERE id = ?", (r["user_id"],)).fetchone()
            if account is None or not account["pw_hash"] or account["kind"] != "person":
                raise CompanyError("this account's credentials are managed by its sign-on service", 410)
            self._set_password(r["user_id"], new, salt=salt, pw_hash=pw_hash)
            if not r["made_by"]:     # a link the server mailed to the address: whoever opened it receives its mail
                self.db.execute("UPDATE users SET verified_at = COALESCE(verified_at, ?) WHERE id = ?",
                                (_iso(_now()), r["user_id"]))
            email = self._user(r["user_id"]).email
            self.failures.pop(email.lower(), None)
            return self._session(r["user_id"])

    def sso_session(self, subject: str, email: str, name: str, policy: str, link_to: str = "") -> Session:
        """Sign in someone the company's identity provider vouched for (with a verified address): the account bound
        to the provider's subject, else a new one the sign-up policy allows. An existing account is never taken over
        by an e-mail match (CV-H02): it is bound to the sign-on only by its holder, signed in (``link_to``: their
        account id), and a binding is never overwritten."""
        email = email.strip()
        if not EMAIL.match(email):
            raise CompanyError("the sign-on service gave no e-mail address", 403)
        with self.lock:
            r = self.db.execute("SELECT id FROM users WHERE sso_subject = ?", (subject,)).fetchone()
            if link_to:
                u = self.db.execute("SELECT id, sso_subject FROM users WHERE id = ?", (link_to,)).fetchone()
                if u is None:
                    raise CompanyError("that account no longer exists", 401)
                if r is not None and r["id"] != link_to:
                    raise CompanyError("this sign-on account is already linked to another account", 409)
                if u["sso_subject"] and u["sso_subject"] != subject:
                    raise CompanyError("your account is already linked to another sign-on account", 409)
                self.db.execute("UPDATE users SET sso_subject = ? WHERE id = ?", (subject, link_to))
                return self._session(link_to)
            if r is not None:
                return self._session(r["id"])
            other = self.db.execute("SELECT id, sso_subject FROM users WHERE email = ?", (email,)).fetchone()
            if other is not None:
                raise CompanyError(f"there is already an account for {email}: sign in with its password, then link "
                                   "single sign-on from your account page", 409)
            uid = self._new_user(email, name, "", "", policy, subject)
            self.db.execute("UPDATE users SET verified_at = ? WHERE id = ?", (_iso(_now()), uid))
            return self._session(uid)

    def keep_state(self, state: str, verifier: str, nonce: str, next_: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM sign_in_states WHERE at < ?", (_iso(_now() - dt.timedelta(minutes=10)),))
            self.db.execute("INSERT INTO sign_in_states (state, verifier, nonce, at, next) VALUES (?, ?, ?, ?, ?)",
                            (state, verifier, nonce, _iso(_now()), next_))

    def take_state(self, state: str) -> tuple[str, str, str]:
        """The PKCE verifier, nonce and page to return to of a sign-on begun here (once, within ten minutes)."""
        with self.lock:
            r = self.db.execute("SELECT * FROM sign_in_states WHERE state = ?", (state,)).fetchone()
            self.db.execute("DELETE FROM sign_in_states WHERE state = ?", (state,))
            if r is None or dt.datetime.fromisoformat(r["at"]) < _now() - dt.timedelta(minutes=10):
                raise CompanyError("this sign-on took too long or was not begun here: try again", 400)
            return r["verifier"], r["nonce"], r["next"]

    # ---- companies -----------------------------------------------------------------------------------------
    def role(self, user: User, cid: str) -> str:
        with self.lock:
            key = None
            if self.is_key(user):
                key = self.db.execute("SELECT company_id, role FROM api_keys WHERE user_id = ? AND revoked_at IS NULL",
                                      (user.id,)).fetchone()
                if key is None or key["company_id"] != cid:
                    raise CompanyError(f"no company {cid} of yours", 404)
            r = self.db.execute("SELECT m.role FROM members m JOIN companies c ON c.id = m.company_id "
                                "WHERE m.company_id = ? AND m.user_id = ? AND c.deleted = 0", (cid, user.id)).fetchone()
            if r is None:
                raise CompanyError(f"no company {cid} of yours", 404)
            return key["role"] if key is not None else r["role"]

    def _need(self, user: User, cid: str, *roles: str) -> str:
        role = self.role(user, cid)
        if roles and role not in roles:
            what = "change its data" if roles == CAN_EDIT else "manage its members" if roles == ("owner",) else "do that"
            raise CompanyError(f"as a {role} of this company you cannot {what}; ask an owner", 403)
        return role

    def _limits(self, uid: str, cid: str) -> tuple[list[str], list[str]]:
        """The places and product groups a member's rights are limited to (empty: not limited)."""
        r = self.db.execute("SELECT places, families FROM members WHERE company_id = ? AND user_id = ?", (cid, uid)).fetchone()
        return (json.loads(r["places"]), json.loads(r["families"])) if r else ([], [])

    def _meta(self, cid: str, role: str, uid: str | None = None) -> CompanyMeta:
        r = self.db.execute("SELECT id, name, revision, updated_at, updated_by, created_at, size, approval FROM companies "
                            "WHERE id = ?", (cid,)).fetchone()
        pending = self.db.execute("SELECT COUNT(*) FROM change_requests WHERE company_id = ? AND status = 'pending'",
                                  (cid,)).fetchone()[0]
        places, families = self._limits(uid, cid) if uid else ([], [])
        return CompanyMeta(id=r["id"], name=r["name"], role=role, revision=r["revision"], updated_at=r["updated_at"],
                           updated_by=self._name(r["updated_by"]), created_at=r["created_at"], size=r["size"],
                           approval=bool(r["approval"]), pending=pending, places=places, families=families)

    def list(self, user: User) -> list[CompanyMeta]:
        with self.lock:
            rows = self.db.execute("SELECT c.id, m.role FROM companies c JOIN members m ON m.company_id = c.id "
                                   "WHERE m.user_id = ? AND c.deleted = 0 ORDER BY c.updated_at DESC, c.id",
                                   (user.id,)).fetchall()
            if self.is_key(user):
                cid = self.key_company(user)
                rows = [r for r in rows if r["id"] == cid]
            return [self._meta(r["id"], self.role(user, r["id"]), user.id) for r in rows]

    def create(self, user: User, doc: dict, note: str = "") -> CompanyMeta:
        with self.lock:
            if self.is_key(user):
                raise CompanyError("a key works only in its company; a person must create a company", 403)
            n = self.db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            cid = f"C{n + 1:04d}"
            while self.db.execute("SELECT 1 FROM companies WHERE id = ?", (cid,)).fetchone():
                n += 1
                cid = f"C{n + 1:04d}"
            text = _canonical(doc)
            now = _iso(_now())
            self.db.execute("BEGIN")
            try:
                self.db.execute(
                    "INSERT INTO companies (id, name, created_at, created_by, updated_at, updated_by, revision, sha256, "
                    "size, dataset) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (cid, _company_name(doc), now, user.id, now, user.id, sha(text), len(text.encode()), text))
                self.db.execute("INSERT INTO members (company_id, user_id, role, added_at, added_by) VALUES (?, ?, 'owner', ?, ?)",
                                (cid, user.id, now, user.id))
                self._keep(cid, 1, user.id, "created", text, now, {}, doc, "")
                self._log(cid, 1, user.id, "created", note or "company created")
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return self._meta(cid, "owner", user.id)

    def open(self, user: User, cid: str) -> CompanyDoc:
        meta, text = self.open_text(user, cid)
        return CompanyDoc(meta=meta, dataset=json.loads(text))

    def open_text(self, user: User, cid: str) -> tuple[CompanyMeta, str]:
        """The company's latest save as it is kept (JSON text), with its meta: sent on as it is, a large company
        opens without being read into objects and written out again."""
        with self.lock:
            role = self._need(user, cid)
            r = self.db.execute("SELECT dataset FROM companies WHERE id = ?", (cid,)).fetchone()
            return self._meta(cid, role, user.id), str(r["dataset"])

    def _working_copy(self, cid: str, doc: dict | None, patch: dict | None, base_revision: int,
                      current: dict, current_rev: int) -> dict:
        """The document a save sends: whole, or its patch applied to the revision it was based on."""
        if patch is None:
            if doc is None:
                raise CompanyError("a save needs the company or what changed in it", 422)
            return doc
        try:
            return apply_patch(current if base_revision == current_rev else self._doc_at(cid, base_revision), patch)
        except (PatchError, CompanyError) as e:
            raise CompanyError(f"the changes sent do not fit revision {base_revision}: {e}; send the whole company",
                               409, {"patch": "unfit", "revision": current_rev}) from None

    def _since(self, cid: str, base_revision: int) -> list[Any]:
        return self.db.execute("SELECT user_id, client FROM company_revisions WHERE company_id = ? AND revision > ? "
                               "ORDER BY revision", (cid, base_revision)).fetchall()

    def _own(self, cid: str, base_revision: int, current_rev: int, uid: str, client: str) -> bool:
        """Every save after ``base_revision`` came from this window (``client``): the working copy carries them."""
        rows = self._since(cid, base_revision)
        return bool(client) and len(rows) == current_rev - base_revision and all(
            r["user_id"] == uid and r["client"] == client for r in rows)

    def save(self, user: User, cid: str, doc: dict | None, base_revision: int, action: str = "saved",
             note: str = "", patch: dict | None = None, client: str = "") -> SaveReport:
        """Save the working copy (``doc``, or ``patch`` applied to revision ``base_revision``) over revision
        ``base_revision``; refused when the company has moved on, unless only this window's own saves moved it."""
        with self.lock:
            role = self._need(user, cid, *CAN_EDIT)
            r = self.db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
            current = json.loads(r["dataset"])
            own = False
            if base_revision != r["revision"]:
                if not (0 < base_revision < r["revision"] and self._own(cid, base_revision, r["revision"], user.id, client)):
                    raise CompanyError(
                        f"{self._name(r['updated_by'])} saved this company at {r['updated_at']} after you opened it "
                        f"(revision {r['revision']}, yours is based on {base_revision})", 409,
                        {"revision": r["revision"], "updated_by": self._name(r["updated_by"]),
                         "updated_at": r["updated_at"], "self": r["updated_by"] == user.id})
                own = True
            doc = self._working_copy(cid, doc, patch, base_revision, current, r["revision"])
            working = doc
            self._within_rights(user, cid, current, doc)
            guarded = doc
            if action != "restored":     # a revision put back carries the releases it was saved with
                try:
                    check_releases(current, doc, user.email)
                except ReleaseRefused as e:
                    raise CompanyError(str(e), 403) from None
                guarded = record_credit_releases(current, doc, user.email)
            doc = guarded
            held: dict | None = None
            if r["approval"] and action != "approved":
                doc, held = split_master(current, doc)
                if not held["before"] and not held["after"]:
                    held = None
            revived = self._revive_erp(cid, current, doc)
            erp_changed = revived is not doc or guarded is not working
            doc = revived
            text = _canonical(doc)
            now = _iso(_now())
            if text == r["dataset"]:
                if held is None:
                    return SaveReport(meta=self._meta(cid, role, user.id), saved=False, summary="nothing changed", own=own,
                                      dataset=doc if erp_changed else None)
                self.db.execute("BEGIN")
                try:
                    request = self._hold(cid, r["revision"], user, held, now)
                    self.db.execute("COMMIT")
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
                return SaveReport(meta=self._meta(cid, role, user.id), saved=False, own=own, held=request, dataset=doc,
                                  summary=f"waiting for approval: {request.summary}")
            summary, changes = summarise(current, doc)
            rev = r["revision"] + 1
            self.db.execute("BEGIN")
            try:
                self.db.execute("UPDATE companies SET name = ?, updated_at = ?, updated_by = ?, revision = ?, sha256 = ?, "
                                "size = ?, dataset = ? WHERE id = ?",
                                (_company_name(doc), now, user.id, rev, sha(text), len(text.encode()), text, cid))
                self._keep(cid, rev, user.id, action, text, now, current, doc, client)
                self._log(cid, rev, user.id, action, (note + ": " if note else "") + (summary or "no change"), changes)
                self._document(cid, rev, user.id, now, current, doc)
                self._withdraw(cid, user.id, now, current, doc)
                request = self._hold(cid, rev, user, held, now) if held else None
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return SaveReport(meta=self._meta(cid, role, user.id), saved=True, own=own, held=request,
                              dataset=doc if request or erp_changed else None,
                              summary=summary + (f"; waiting for approval: {request.summary}" if request else ""))

    def merge_save(self, user: User, cid: str, base: dict | None, mine: dict | None, base_revision: int,
                   clean_only: bool = False, patch: dict | None = None, client: str = "",
                   choose: dict[str, str] | None = None, preview: bool = False) -> MergeResult:
        """Save the working copy made from revision ``base_revision`` merged with the saves made since (see
        :mod:`scp.companies.merge`). The working copy is ``mine``, or ``patch`` applied to that revision; its base is
        ``base``, or that revision as kept here. ``clean_only``: refuse (409, as a stale save is) when a record was
        changed on both sides, so nothing is decided for the person without asking. ``choose``: per clash, whose
        version to keep. ``preview``: say what the merge would do, save nothing. When every save in between was the
        same person's (another window), their latest change of a record is kept without asking."""
        with self.lock:
            self._need(user, cid, *CAN_EDIT)
            r = self.db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
            who = self._name(r["updated_by"])
            current = json.loads(r["dataset"])
            if base is None:
                try:
                    base = current if base_revision == r["revision"] else self._doc_at(cid, base_revision)
                except CompanyError:
                    raise CompanyError(f"revision {base_revision} is not kept here: send the save your changes were "
                                       "made from", 409, {"base": "missing", "revision": r["revision"]}) from None
            if patch is not None:
                try:
                    mine = apply_patch(base, patch)
                except PatchError as e:
                    raise CompanyError(f"the changes sent do not fit revision {base_revision}: {e}", 409,
                                       {"patch": "unfit", "revision": r["revision"]}) from None
            if mine is None:
                raise CompanyError("a merge needs the working copy or what changed in it", 422)
            if base_revision == r["revision"]:
                if preview:
                    return MergeResult(meta=self._meta(cid, self.role(user, cid), user.id), dataset=mine, merged_with="", saved=False,
                                       report=MergeReport(mine=0, theirs=0, conflicts=[], renumbered=[], summary="nothing to merge"))
                rep = self.save(user, cid, mine, base_revision, client=client)
                return MergeResult(meta=rep.meta, dataset=mine, merged_with="",
                                   report=MergeReport(mine=0, theirs=0, conflicts=[], renumbered=[], summary="nothing to merge"))
            mine_only = all(x["user_id"] == user.id for x in self._since(cid, base_revision)) and \
                len(self._since(cid, base_revision)) == r["revision"] - base_revision
            merged, report = merge(base, mine, current, choose=choose, prefer_mine=mine_only)
            for c in report.clashes:
                c.list = LABELS.get(c.list, c.list.replace("_", " "))
            if mine_only:
                who = "you"
            if clean_only and report.conflicts and not mine_only:
                raise CompanyError(
                    f"{who} saved this company at {r['updated_at']} after you opened it and changed "
                    f"{len(report.conflicts)} of the same records", 409,
                    {"revision": r["revision"], "updated_by": who, "updated_at": r["updated_at"],
                     "conflicts": report.conflicts})
            if preview:
                return MergeResult(meta=self._meta(cid, self.role(user, cid), user.id), dataset=merged, report=report,
                                   merged_with=who, saved=False)
            saved = self.save(user, cid, merged, r["revision"], action="merged", client=client,
                              note="merged with your save from another window" if mine_only
                              else f"merged with {who}'s save ({report.summary})")
            return MergeResult(meta=saved.meta, dataset=saved.dataset or merged, report=report, merged_with=who,
                               held=saved.held)

    def _keep(self, cid: str, rev: int, uid: str, action: str, text: str, now: str, before: dict, doc: dict,
              client: str) -> None:
        """Keep this revision: as what changed since the one before, or whole when that is kept only as a delta
        chain too long, is missing, or the change is large."""
        prev = self.db.execute("SELECT revision, kind FROM company_revisions WHERE company_id = ? ORDER BY revision "
                               "DESC LIMIT ?", (cid, FULL_EVERY)).fetchall()
        kind, data = "full", text
        if prev and prev[0]["revision"] == rev - 1 and any(p["kind"] == "full" for p in prev):
            delta = json.dumps(make_patch(before, doc), separators=(",", ":"), ensure_ascii=False)
            if len(delta) * 4 < len(text):
                kind, data = "delta", delta
        self.db.execute("INSERT INTO company_revisions (company_id, revision, at, started_at, user_id, action, sha256, "
                        "size, data, kind, client) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (cid, rev, now, now, uid, action, sha(text), len(text.encode()),
                         zlib.compress(data.encode(), 6), kind, client))

    def _doc_at(self, cid: str, rev: int) -> dict:
        """The company as it was at revision ``rev``: the whole copy before it and the changes since."""
        rows = self.db.execute("SELECT revision, kind, data FROM company_revisions WHERE company_id = ? AND revision <= ? "
                               "ORDER BY revision DESC LIMIT ?", (cid, rev, FULL_EVERY + 1)).fetchall()
        chain: list[Any] = []
        want = rev
        for r in rows:
            if r["revision"] != want:
                break
            chain.append(r)
            if r["kind"] == "full":
                doc = json.loads(zlib.decompress(r["data"]).decode())
                for d in reversed(chain[:-1]):
                    doc = apply_patch(doc, json.loads(zlib.decompress(d["data"]).decode()))
                return doc
            want -= 1
        raise CompanyError(f"revision {rev} is not kept: before saves were all kept, only the last save of each "
                           "ten-minute run was", 404)

    def _kept(self, cid: str) -> set[int]:
        """The revisions that can be opened: a whole copy, or a delta on one that can."""
        out: set[int] = set()
        for r in self.db.execute("SELECT revision, kind FROM company_revisions WHERE company_id = ? ORDER BY revision",
                                 (cid,)):
            if r["kind"] == "full" or r["revision"] - 1 in out:
                out.add(r["revision"])
        return out

    def revision(self, user: User, cid: str, rev: int) -> dict:
        with self.lock:
            self._need(user, cid)
            return self._doc_at(cid, rev)

    def text_at(self, user: User, cid: str, rev: int) -> str:
        """The company at revision ``rev`` as JSON text, for a member: the latest save as it is kept, an earlier one
        rebuilt (the planning calls read the company here instead of receiving it, Phase S)."""
        with self.lock:
            self._need(user, cid)
            r = self.db.execute("SELECT revision, dataset FROM companies WHERE id = ? AND deleted = 0",
                                (cid,)).fetchone()
            if r is not None and r["revision"] == rev:
                return str(r["dataset"])
            return json.dumps(self._doc_at(cid, rev))

    def restore(self, user: User, cid: str, rev: int, base_revision: int, client: str = "") -> SaveReport:
        doc = self.revision(user, cid, rev)
        return self.save(user, cid, doc, base_revision, action="restored", note=f"put back to revision {rev}",
                         client=client)

    # ---- rights, approval and change documents (Phase L) --------------------------------------------------------
    def _within_rights(self, user: User, cid: str, before: dict, after: dict) -> None:
        places, families = self._limits(user.id, cid)
        bad = out_of_scope(before, after, places, families)
        if bad:
            limits = " and ".join(x for x in (
                f"the places {', '.join(places)}" if places else "",
                f"the product groups {', '.join(families)}" if families else "") if x)
            raise CompanyError(f"your rights cover {limits}; this change also touches {', '.join(bad[:6])}"
                               + (f" and {len(bad) - 6} more" if len(bad) > 6 else "") + ". Ask an owner", 403,
                               {"out_of_scope": bad[:50]})

    def _hold(self, cid: str, rev: int, user: User, held: dict, now: str) -> HeldChange:
        summary, _ = summarise(held["before"], held["after"])
        cur = self.db.execute("INSERT INTO change_requests (company_id, at, user_id, revision, data, summary) "
                              "VALUES (?, ?, ?, ?, ?, ?)",
                              (cid, now, user.id, rev, zlib.compress(_canonical(held).encode(), 6), summary or "master data"))
        self._log(cid, None, user.id, "held", f"waiting for approval (#{cur.lastrowid}): {summary}")
        return self._held(self.db.execute("SELECT * FROM change_requests WHERE id = ?", (cur.lastrowid,)).fetchone(),
                          user.id, detail=False)

    def _held(self, r: Any, uid: str, detail: bool = True) -> HeldChange:
        data = json.loads(zlib.decompress(r["data"]).decode())
        rows = [FieldChangeRow(list=LABELS.get(n, n), record=rec, field=f, old=o, new=v)
                for n, rec, f, o, v in field_changes(data["before"], data["after"])[:200]] if detail else []
        return HeldChange(id=r["id"], at=r["at"], by=self._name(r["user_id"]), by_me=r["user_id"] == uid,
                          summary=r["summary"], status=r["status"], decided_by=self._name(r["decided_by"]) if r["decided_by"] else "",
                          decided_at=r["decided_at"] or "", note=r["note"], changes=rows)

    def _revive_erp(self, cid: str, before: dict, after: dict) -> dict:
        """A restored order whose ERP copy was closed needs a new export and a distinct lifecycle. Preserve that
        lifecycle across subsequent saves and restores, so acknowledgements from its old copy cannot take it."""
        closed = {(r["kind"], r["id"]) for r in self.db.execute(
            "SELECT kind, id FROM erp_withdrawn WHERE company_id = ? AND taken_at IS NOT NULL", (cid,))}
        previous = erp_records(before)
        out = after
        for collection in ("purchase_orders", "cancelled_purchase_orders", "receipts"):
            rows = after.get(collection)
            if not isinstance(rows, list):
                continue
            new = []
            for r in rows:
                if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"]:
                    new.append(r)
                    continue
                if collection == "receipts" and r.get("kind") not in ("production", "transfer"):
                    new.append(r)
                    continue
                key = ("purchase_order" if collection != "receipts" else f"{r.get('kind')}_order", r.get("id"))
                prev = previous.get(key)
                if prev is None and key in closed:
                    r = {**r, "erp_sent": "", "erp_generation": secrets.token_hex(16)}
                elif prev and prev.get("erp_generation") and r.get("erp_generation") != prev["erp_generation"]:
                    r = {**r, "erp_sent": "", "erp_generation": prev["erp_generation"]}
                new.append(r)
            if new != rows:
                out = {**out, collection: new}
        return out

    def _withdraw(self, cid: str, uid: str, now: str, before: dict, after: dict) -> None:
        """An order the ERP numbered that this save removed (deleted, not completed) is kept to tell the ERP it is
        withdrawn (N137); one that comes back (a save put back) is no longer withdrawn."""
        old, new = erp_orders(before), erp_orders(after)
        closed = {(f"{c.get('kind')}_order", c.get("id")) for c in after.get("closed_orders") or [] if isinstance(c, dict)}
        for (kind, oid), (ref, place) in old.items():
            if (kind, oid) not in new and (kind, oid) not in closed:
                self.db.execute("INSERT INTO erp_withdrawn (company_id, kind, id, erp_ref, location, at, user_id, generation) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (company_id, kind, id) DO UPDATE SET erp_ref = "
                                "excluded.erp_ref, location = excluded.location, at = excluded.at, user_id = "
                                "excluded.user_id, taken_at = NULL, generation = excluded.generation",
                                (cid, kind, oid, ref, place, now, uid, secrets.token_hex(16)))
        for kind, oid in set(erp_records(after)) - set(erp_records(before)):
            self.db.execute("DELETE FROM erp_withdrawn WHERE company_id = ? AND kind = ? AND id = ?",
                            (cid, kind, oid))

    def _document(self, cid: str, rev: int, uid: str, now: str, before: dict, after: dict) -> None:
        """Keep every field this save changed, with its old and new value (change documents)."""
        rows = field_changes(before, after)
        cut = len(rows) > MAX_CHANGE_ROWS
        rows = rows[:MAX_CHANGE_ROWS]
        self.db.executemany(
            "INSERT INTO change_docs (company_id, revision, at, user_id, list, record, field, old, new) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(cid, rev, now, uid, n, rec, f, json.dumps(o, ensure_ascii=False), json.dumps(v, ensure_ascii=False))
             for n, rec, f, o, v in rows])
        if cut:
            self.db.execute("INSERT INTO change_docs (company_id, revision, at, user_id, list, record, field, old, new) "
                            "VALUES (?, ?, ?, ?, '', '', '', NULL, ?)",
                            (cid, rev, now, uid, json.dumps(f"more than {MAX_CHANGE_ROWS} fields changed: the "
                                                            "revision itself has them all")))

    def set_approval(self, user: User, cid: str, on: bool) -> CompanyMeta:
        """Master-data changes need a second person's approval (on) or not."""
        with self.lock:
            self._need(user, cid, "owner")
            editors = self.db.execute("SELECT COUNT(*) FROM members WHERE company_id = ? AND role IN ('owner', 'planner')",
                                      (cid,)).fetchone()[0]
            if on and editors < 2:
                raise CompanyError("approval needs a second person who can change the data: add a planner or an owner "
                                   "first", 409)
            self.db.execute("UPDATE companies SET approval = ? WHERE id = ?", (1 if on else 0, cid))
            self._log(cid, None, user.id, "member", "master data changes now need a second person's approval" if on
                      else "master data changes no longer need approval")
            return self._meta(cid, "owner", user.id)

    def held_changes(self, user: User, cid: str, status: str = "pending", limit: int = 50) -> list[HeldChange]:
        with self.lock:
            self._need(user, cid)
            q = "SELECT * FROM change_requests WHERE company_id = ?" + ("" if status == "all" else " AND status = ?") + \
                " ORDER BY id DESC LIMIT ?"
            args = (cid, limit) if status == "all" else (cid, status, limit)
            return [self._held(r, user.id) for r in self.db.execute(q, args).fetchall()]

    def decide(self, user: User, cid: str, rid: int, decision: str, note: str = "", client: str = "") -> SaveReport:
        """Approve (make the change), reject or withdraw (the one who asked) a held master-data change."""
        with self.lock:
            role = self._need(user, cid, *CAN_EDIT)
            r = self.db.execute("SELECT * FROM change_requests WHERE id = ? AND company_id = ?", (rid, cid)).fetchone()
            if r is None:
                raise CompanyError(f"no change #{rid} in this company", 404)
            if r["status"] != "pending":
                raise CompanyError(f"change #{rid} is already {r['status']}", 409)
            asker = self._name(r["user_id"])
            if decision == "withdraw" and r["user_id"] != user.id:
                raise CompanyError(f"only {asker} can withdraw their change; reject it instead", 403)
            if decision in ("approve", "reject") and r["user_id"] == user.id:
                raise CompanyError("a change needs a second person: someone else approves or rejects it (you can "
                                   "withdraw it)", 403)
            now = _iso(_now())
            if decision == "approve":
                c = self.db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
                current = json.loads(c["dataset"])
                try:
                    new = apply_held(current, json.loads(zlib.decompress(r["data"]).decode()))
                except Stale as e:
                    raise CompanyError(f"changed since {asker} asked: {e}. Reject it and ask {asker} to make the change "
                                       "again", 409) from None
                rep = self.save(user, cid, new, c["revision"], action="approved", client=client,
                                note=f"approved {asker}'s change #{rid}")
                rep.dataset = new
            elif decision in ("reject", "withdraw"):
                rep = SaveReport(meta=self._meta(cid, role, user.id), saved=False,
                                 summary=f"change #{rid} " + ("withdrawn" if decision == "withdraw" else "rejected"))
            else:
                raise CompanyError("approve, reject or withdraw", 422)
            status = {"approve": "approved", "reject": "rejected", "withdraw": "withdrawn"}[decision]
            self.db.execute("UPDATE change_requests SET status = ?, decided_by = ?, decided_at = ?, note = ? WHERE id = ?",
                            (status, user.id, now, note.strip()[:500], rid))
            if decision != "approve":
                self._log(cid, None, user.id, "held", f"change #{rid} by {asker} {status}" + (f": {note.strip()}" if note.strip() else ""))
            rep.meta = self._meta(cid, role, user.id)
            return rep

    def changes(self, user: User, cid: str, q: str = "", list_: str = "", limit: int = 200,
                before: int | None = None) -> list[FieldChangeRow]:
        """Change documents: every field changed, newest first; ``q`` finds a record by its key (a part of it)."""
        with self.lock:
            self._need(user, cid)
            names = {v: k for k, v in LABELS.items()}
            sql = "SELECT * FROM change_docs WHERE company_id = ?"
            args: list[Any] = [cid]
            if list_:
                sql += " AND list = ?"
                args.append(names.get(list_, list_))
            if q.strip():
                sql += " AND record LIKE ?"
                args.append(f"%{q.strip()}%")
            if before:
                sql += " AND seq < ?"
                args.append(before)
            sql += " ORDER BY seq DESC LIMIT ?"
            args.append(limit)
            return [FieldChangeRow(seq=r["seq"], revision=r["revision"], at=r["at"], user=self._name(r["user_id"]),
                                   list=LABELS.get(r["list"], r["list"]), record=r["record"], field=r["field"],
                                   old=json.loads(r["old"]) if r["old"] is not None else None,
                                   new=json.loads(r["new"]) if r["new"] is not None else None)
                    for r in self.db.execute(sql, args)]

    def delete(self, user: User, cid: str) -> None:
        with self.lock:
            self._need(user, cid, "owner")
            self.db.execute("UPDATE companies SET deleted = 1 WHERE id = ?", (cid,))
            self._log(cid, None, user.id, "deleted", "company deleted")

    # ---- members -------------------------------------------------------------------------------------------
    def members(self, user: User, cid: str) -> list[Member]:
        with self.lock:
            self._need(user, cid)
            out = [Member(user_id=r["user_id"], email=r["email"], name=r["name"], role=r["role"], since=r["added_at"],
                          places=json.loads(r["places"]), families=json.loads(r["families"]))
                   for r in self.db.execute("SELECT m.user_id, u.email, u.name, m.role, m.added_at, m.places, m.families "
                                            "FROM members m JOIN users u ON u.id = m.user_id WHERE m.company_id = ? "
                                            "AND u.kind != 'key' ORDER BY m.added_at, u.email", (cid,))]
            out += [Member(user_id=None, email=r["email"], name="", role=r["role"], since=r["at"],
                           places=json.loads(r["places"]), families=json.loads(r["families"]))
                    for r in self.db.execute("SELECT * FROM invites WHERE company_id = ? ORDER BY at, email", (cid,))]
            return out

    def _owners(self, cid: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM members WHERE company_id = ? AND role = 'owner'",
                               (cid,)).fetchone()[0]

    def set_member(self, user: User, cid: str, email: str, role: str, places: list[str] | None = None,
                   families: list[str] | None = None) -> list[Member]:
        """Add a member (or invite an e-mail without an account), or change a member's role, and the places and product
        groups a planner's rights are limited to (``None``: as they were; an owner is never limited)."""
        if role not in ROLES:
            raise CompanyError(f"a role is one of {', '.join(ROLES)}", 422)
        clean = lambda xs: sorted({x.strip() for x in xs if x and x.strip()}) if xs is not None else None  # noqa: E731
        places, families = clean(places), clean(families)
        if role == "owner":
            places, families = [], []
        email = email.strip()
        if not EMAIL.match(email):
            raise CompanyError("that does not look like an e-mail address", 422)
        with self.lock:
            self._need(user, cid, "owner")
            now = _iso(_now())
            u = self.db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            member = u is not None and self.db.execute("SELECT 1 FROM members WHERE company_id = ? AND user_id = ?",
                                                       (cid, u["id"])).fetchone() is not None
            if not member:
                # CV-C01: nobody becomes a member without accepting: an invitation with a one-time link, for an
                # address with an account as much as for one without
                token = secrets.token_urlsafe(24)
                self.db.execute("INSERT INTO invites (company_id, email, role, invited_by, at, places, families, "
                                "token_hash, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (company_id, "
                                "email) DO UPDATE SET role = excluded.role, places = excluded.places, families = "
                                "excluded.families, token_hash = excluded.token_hash, expires_at = excluded.expires_at, "
                                "invited_by = excluded.invited_by",
                                (cid, email, role, user.id, now, json.dumps(places or []), json.dumps(families or []),
                                 _token_hash(token), _iso(_now() + dt.timedelta(days=INVITE_DAYS))))
                lim = " and ".join(x for x in (f"places {', '.join(places)}" if places else "",
                                               f"product groups {', '.join(families)}" if families else "") if x)
                self._log(cid, None, user.id, "member", f"{email} invited as {role}" + (f", limited to {lim}" if lim else ""))
                out = self.members(user, cid)
                for m in out:
                    if m.user_id is None and m.email.lower() == email.lower():
                        m.invite_link = token
                return out
            else:
                cur = self.db.execute("SELECT role FROM members WHERE company_id = ? AND user_id = ?",
                                      (cid, u["id"])).fetchone()
                if cur and cur["role"] == "owner" and role != "owner" and self._owners(cid) == 1:
                    raise CompanyError("a company needs an owner: make someone else an owner first")
                self.db.execute("INSERT INTO members (company_id, user_id, role, added_at, added_by) VALUES (?, ?, ?, ?, ?) "
                                "ON CONFLICT (company_id, user_id) DO UPDATE SET role = excluded.role",
                                (cid, u["id"], role, now, user.id))
                who = self._name(u["id"])
                was = self._limits(u["id"], cid)
                if places is not None or families is not None:
                    new = (places if places is not None else was[0], families if families is not None else was[1])
                    self.db.execute("UPDATE members SET places = ?, families = ? WHERE company_id = ? AND user_id = ?",
                                    (json.dumps(new[0]), json.dumps(new[1]), cid, u["id"]))
                else:
                    new = was
                limits = " and ".join(x for x in (f"places {', '.join(new[0])}" if new[0] else "",
                                                  f"product groups {', '.join(new[1])}" if new[1] else "") if x)
                if cur and cur["role"] == role and new == was:
                    return self.members(user, cid)                  # nothing changed: nothing to record
                self._log(cid, None, user.id, "member",
                          (f"{who}: {cur['role']} → {role}" if cur and cur["role"] != role else f"{who}: {role}" if cur
                           else f"{who} added as {role}")
                          + (f", limited to {limits}" if limits and new != was or limits and not cur
                             else ", no longer limited" if was != new and not limits else ""))
            return self.members(user, cid)

    def remove_member(self, user: User, cid: str, email: str) -> list[Member]:
        with self.lock:
            self._need(user, cid, "owner")
            u = self.db.execute("SELECT id FROM users WHERE email = ?", (email.strip(),)).fetchone()
            cur = self.db.execute("SELECT role FROM members WHERE company_id = ? AND user_id = ?",
                                  (cid, u["id"])).fetchone() if u else None
            if cur:
                if cur["role"] == "owner" and self._owners(cid) == 1:
                    raise CompanyError("a company needs an owner: make someone else an owner first")
                self.db.execute("DELETE FROM members WHERE company_id = ? AND user_id = ?", (cid, u["id"]))
                self._log(cid, None, user.id, "member", f"{self._name(u['id'])} removed")
            elif self.db.execute("DELETE FROM invites WHERE company_id = ? AND email = ?", (cid, email.strip())).rowcount:
                self._log(cid, None, user.id, "member", f"invitation for {email.strip()} withdrawn")
            else:
                raise CompanyError(f"{email} is not a member of this company", 404)
            return self.members(user, cid)

    # ---- audit trail ---------------------------------------------------------------------------------------
    def _log(self, cid: str, rev: int | None, uid: str, action: str, summary: str,
             changes: list[ListChange] | None = None) -> None:
        self.db.execute("INSERT INTO company_log (company_id, revision, at, user_id, action, summary, detail) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (cid, rev, _iso(_now()), uid, action, summary,
                         json.dumps([c.model_dump() for c in changes or []])))

    def history(self, user: User, cid: str, limit: int = 200, before: int | None = None) -> list[LogRow]:
        with self.lock:
            self._need(user, cid)
            kept = self._kept(cid)
            q = "SELECT * FROM company_log WHERE company_id = ?" + (" AND seq < ?" if before else "") + \
                " ORDER BY seq DESC LIMIT ?"
            args = (cid, before, limit) if before else (cid, limit)
            return [LogRow(seq=r["seq"], revision=r["revision"], at=r["at"], user=self._name(r["user_id"]),
                           action=r["action"], summary=r["summary"],
                           changes=[ListChange(**c) for c in json.loads(r["detail"])],
                           kept=r["revision"] in kept and r["action"] != "member")
                    for r in self.db.execute(q, args)]


_by_store: dict[int, Companies] = {}
_by_store_lock = threading.Lock()


def get_companies() -> Companies:
    store = get_store()
    with _by_store_lock:   # two first requests at once would both add the new columns (Phase L)
        c = _by_store.get(id(store))
        if c is None or c.store is not store:
            c = Companies(store)
            _by_store.clear()
            _by_store[id(store)] = c
        return c
