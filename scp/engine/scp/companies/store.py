"""Companies kept on the server (Q14): accounts, sign-in, members with roles, every save as a revision, and an
audit trail of who changed what.

* **Accounts.** An e-mail and a password (PBKDF2-SHA256, salted); signing in gives a session token, of which only
  the SHA-256 is stored. Sessions last 30 days from their last use.
* **Members.** Each company has members: an *owner* (changes the data and who may see it), a *planner* (changes the
  data) or a *viewer* (reads it). An owner can invite an e-mail that has no account yet; the invitation becomes a
  membership when that address signs up or signs in. A company always keeps at least one owner.
* **Saves.** The working copy is saved as a whole document with the revision it was based on. A save based on an
  older revision than the company's is refused (someone else saved in between), so nobody overwrites a colleague's
  work without seeing it. An unchanged document is not a new revision.
* **Revisions.** Every save is a revision. Its document is kept compressed; one person's run of saves within ten
  minutes shares one kept copy (the last), so a day's autosaves keep a copy per ten minutes, not one per keystroke.
  A company can be opened as it was at any kept revision, and put back to it (a new revision, nothing is lost).
* **Audit trail.** Every save, restore, membership change and deletion is logged with who, when, and for a save,
  what changed: records added, removed and changed per list, with the first few records by name.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import zlib
from typing import Any

from ..model.common import Out
from ..versions.diff import diff_raw
from ..versions.store import Store, get_store, sha
from .merge import MergeReport, merge

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
"""

ROLES = ("owner", "planner", "viewer")
CAN_EDIT = ("owner", "planner")
SESSION_DAYS = 30
RUN_MINUTES = 10              # one person's saves within this share one kept copy
PBKDF2_ROUNDS = 200_000
LOG_ITEMS = 12                # records named per list in a save's detail
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# plain names of the dataset's lists, for the audit trail
LABELS = {
    "locations": "places", "products": "products", "customer_prices": "customer prices",
    "location_products": "planning policies", "resources": "machines", "production_sources": "ways to make",
    "purchasing_sources": "ways to buy", "lanes": "routes", "vendors": "suppliers", "purchase_orders": "purchase orders",
    "demand": "orders and forecasts", "receipts": "open orders", "history": "sales history", "events": "events",
    "npi": "new products", "overrides": "forecast overrides", "stock_targets": "stock targets",
    "changeovers": "changeovers", "allocations": "allocations", "confirmations": "promises", "movements": "goods movements",
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


class CompanyDoc(Out):
    meta: CompanyMeta
    dataset: dict[str, Any]


class SaveReport(Out):
    meta: CompanyMeta
    saved: bool                   # False: nothing had changed
    summary: str


class MergeResult(Out):
    meta: CompanyMeta
    dataset: dict[str, Any]       # the merged company, now its latest save
    report: MergeReport
    merged_with: str              # whose save it was merged with (a name)


class Member(Out):
    user_id: str | None           # None: invited, no account yet
    email: str
    name: str
    role: str
    since: str


class ListChange(Out):
    list: str                     # a plain name
    added: int
    removed: int
    changed: int
    names: list[str]              # the first few records, "+ SO-00012", "~ PAINT-WHITE at DC-MUMBAI", …


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
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _company_name(doc: dict) -> str:
    s = doc.get("settings")
    name = s.get("company_name") if isinstance(s, dict) else None
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
        self.failures: dict[str, list[dt.datetime]] = {}

    # ---- accounts ------------------------------------------------------------------------------------------
    def _user(self, uid: str) -> User:
        r = self.db.execute("SELECT id, email, name FROM users WHERE id = ?", (uid,)).fetchone()
        if r is None:
            raise CompanyError("that account no longer exists", 401)
        return User(id=r["id"], email=r["email"], name=r["name"])

    def _name(self, uid: str) -> str:
        r = self.db.execute("SELECT name, email FROM users WHERE id = ?", (uid,)).fetchone()
        return (r["name"] or r["email"]) if r else uid

    def users(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def signup(self, email: str, name: str, password: str, policy: str = "open") -> Session:
        email = email.strip()
        if not EMAIL.match(email):
            raise CompanyError("that does not look like an e-mail address", 422)
        if len(password) < 8:
            raise CompanyError("a password needs at least 8 characters", 422)
        with self.lock:
            if self.db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise CompanyError("there is already an account for that e-mail; sign in instead")
            if policy == "closed" and self.users():
                raise CompanyError("new accounts are switched off on this server; ask its administrator", 403)
            if policy == "invite" and self.users() and not self.db.execute(
                    "SELECT 1 FROM invites WHERE email = ?", (email,)).fetchone():
                raise CompanyError("this server takes new accounts by invitation only: ask a company owner to invite "
                                   "your e-mail", 403)
            n = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            uid = f"U{n + 1:04d}"
            while self.db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
                n += 1
                uid = f"U{n + 1:04d}"
            salt = secrets.token_hex(16)
            self.db.execute("INSERT INTO users (id, email, name, pw_salt, pw_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (uid, email, name.strip() or email.split("@")[0], salt, _hash_pw(password, salt),
                             _iso(_now())))
            return self._session(uid)

    def signin(self, email: str, password: str) -> Session:
        email = email.strip().lower()
        now = _now()
        with self.lock:
            recent = [t for t in self.failures.get(email, []) if now - t < dt.timedelta(minutes=15)]
            self.failures[email] = recent
            if len(recent) >= 10:
                raise CompanyError("too many wrong passwords for that e-mail; try again in 15 minutes", 429)
            r = self.db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if r is None or not hmac.compare_digest(_hash_pw(password, r["pw_salt"]), r["pw_hash"]):
                recent.append(now)
                raise CompanyError("the e-mail or the password is not right", 401)
            self.failures.pop(email, None)
            return self._session(r["id"])

    def _session(self, uid: str) -> Session:
        token = secrets.token_urlsafe(32)
        now = _now()
        exp = now + dt.timedelta(days=SESSION_DAYS)
        self.db.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                        (_token_hash(token), uid, _iso(now), _iso(exp)))
        self._accept_invites(uid)
        return Session(token=token, user=self._user(uid), expires_at=_iso(exp))

    def _accept_invites(self, uid: str) -> None:
        email = self._user(uid).email
        for r in self.db.execute("SELECT * FROM invites WHERE email = ?", (email,)).fetchall():
            self.db.execute("INSERT OR IGNORE INTO members (company_id, user_id, role, added_at, added_by) "
                            "VALUES (?, ?, ?, ?, ?)", (r["company_id"], uid, r["role"], _iso(_now()), r["invited_by"]))
            self.db.execute("DELETE FROM invites WHERE company_id = ? AND email = ?", (r["company_id"], email))
            self._log(r["company_id"], None, uid, "member", f"{self._name(uid)} joined as {r['role']}")

    def whoami(self, token: str | None) -> User:
        """The account a session token belongs to; the session is extended on use."""
        if not token:
            raise CompanyError("sign in first", 401)
        with self.lock:
            r = self.db.execute("SELECT * FROM sessions WHERE token_hash = ?", (_token_hash(token),)).fetchone()
            now = _now()
            if r is None or dt.datetime.fromisoformat(r["expires_at"]) < now:
                raise CompanyError("your sign-in has expired; sign in again", 401)
            self.db.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                            (_iso(now + dt.timedelta(days=SESSION_DAYS)), r["token_hash"]))
            self.db.execute("UPDATE users SET last_seen = ? WHERE id = ?", (_iso(now), r["user_id"]))
            return self._user(r["user_id"])

    def signout(self, token: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def change_password(self, user: User, old: str, new: str) -> None:
        if len(new) < 8:
            raise CompanyError("a password needs at least 8 characters", 422)
        with self.lock:
            r = self.db.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
            if not hmac.compare_digest(_hash_pw(old, r["pw_salt"]), r["pw_hash"]):
                raise CompanyError("the current password is not right", 403)
            salt = secrets.token_hex(16)
            self.db.execute("UPDATE users SET pw_salt = ?, pw_hash = ? WHERE id = ?", (salt, _hash_pw(new, salt), user.id))

    # ---- companies -----------------------------------------------------------------------------------------
    def role(self, user: User, cid: str) -> str:
        r = self.db.execute("SELECT m.role FROM members m JOIN companies c ON c.id = m.company_id "
                            "WHERE m.company_id = ? AND m.user_id = ? AND c.deleted = 0", (cid, user.id)).fetchone()
        if r is None:
            raise CompanyError(f"no company {cid} of yours", 404)
        return r["role"]

    def _need(self, user: User, cid: str, *roles: str) -> str:
        role = self.role(user, cid)
        if roles and role not in roles:
            what = "change its data" if roles == CAN_EDIT else "manage its members" if roles == ("owner",) else "do that"
            raise CompanyError(f"as a {role} of this company you cannot {what}; ask an owner", 403)
        return role

    def _meta(self, cid: str, role: str) -> CompanyMeta:
        r = self.db.execute("SELECT id, name, revision, updated_at, updated_by, created_at, size FROM companies "
                            "WHERE id = ?", (cid,)).fetchone()
        return CompanyMeta(id=r["id"], name=r["name"], role=role, revision=r["revision"], updated_at=r["updated_at"],
                           updated_by=self._name(r["updated_by"]), created_at=r["created_at"], size=r["size"])

    def list(self, user: User) -> list[CompanyMeta]:
        with self.lock:
            rows = self.db.execute("SELECT c.id, m.role FROM companies c JOIN members m ON m.company_id = c.id "
                                   "WHERE m.user_id = ? AND c.deleted = 0 ORDER BY c.updated_at DESC, c.id",
                                   (user.id,)).fetchall()
            return [self._meta(r["id"], r["role"]) for r in rows]

    def create(self, user: User, doc: dict, note: str = "") -> CompanyMeta:
        with self.lock:
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
                self._keep(cid, 1, user.id, "created", text, now, fresh=True)
                self._log(cid, 1, user.id, "created", note or "company created")
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return self._meta(cid, "owner")

    def open(self, user: User, cid: str) -> CompanyDoc:
        with self.lock:
            role = self._need(user, cid)
            r = self.db.execute("SELECT dataset FROM companies WHERE id = ?", (cid,)).fetchone()
            return CompanyDoc(meta=self._meta(cid, role), dataset=json.loads(r["dataset"]))

    def save(self, user: User, cid: str, doc: dict, base_revision: int, action: str = "saved",
             note: str = "") -> SaveReport:
        """Save the working copy over revision ``base_revision``; refused when the company has moved on."""
        with self.lock:
            role = self._need(user, cid, *CAN_EDIT)
            r = self.db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
            if base_revision != r["revision"]:
                raise CompanyError(
                    f"{self._name(r['updated_by'])} saved this company at {r['updated_at']} after you opened it "
                    f"(revision {r['revision']}, yours is based on {base_revision})", 409,
                    {"revision": r["revision"], "updated_by": self._name(r["updated_by"]), "updated_at": r["updated_at"]})
            text = _canonical(doc)
            if text == r["dataset"]:
                return SaveReport(meta=self._meta(cid, role), saved=False, summary="nothing changed")
            before = json.loads(r["dataset"])
            summary, changes = summarise(before, doc)
            rev = r["revision"] + 1
            now = _iso(_now())
            self.db.execute("BEGIN")
            try:
                self.db.execute("UPDATE companies SET name = ?, updated_at = ?, updated_by = ?, revision = ?, sha256 = ?, "
                                "size = ?, dataset = ? WHERE id = ?",
                                (_company_name(doc), now, user.id, rev, sha(text), len(text.encode()), text, cid))
                self._keep(cid, rev, user.id, action, text, now, fresh=action != "saved")
                self._log(cid, rev, user.id, action, (note + ": " if note else "") + (summary or "no change"), changes)
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return SaveReport(meta=self._meta(cid, role), saved=True, summary=summary)

    def merge_save(self, user: User, cid: str, base: dict, mine: dict, base_revision: int) -> MergeResult:
        """Save the working copy made from revision ``base_revision`` (whose document is ``base``) merged with the
        saves made since (see :mod:`scp.companies.merge`)."""
        with self.lock:
            self._need(user, cid, *CAN_EDIT)
            r = self.db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
            who = self._name(r["updated_by"])
            if base_revision == r["revision"]:
                rep = self.save(user, cid, mine, base_revision)
                return MergeResult(meta=rep.meta, dataset=mine, merged_with="",
                                   report=MergeReport(mine=0, theirs=0, conflicts=[], renumbered=[], summary="nothing to merge"))
            theirs = json.loads(r["dataset"])
            merged, report = merge(base, mine, theirs)
            saved = self.save(user, cid, merged, r["revision"], action="merged",
                              note=f"merged with {who}'s save ({report.summary})")
            return MergeResult(meta=saved.meta, dataset=merged, report=report, merged_with=who)

    def _keep(self, cid: str, rev: int, uid: str, action: str, text: str, now: str, fresh: bool) -> None:
        """Keep this revision's document; an autosave within the same person's ten-minute run replaces the run's
        previous copy."""
        started = now
        if not fresh:
            last = self.db.execute("SELECT * FROM company_revisions WHERE company_id = ? ORDER BY revision DESC LIMIT 1",
                                   (cid,)).fetchone()
            if (last is not None and last["user_id"] == uid and last["action"] == "saved"
                    and dt.datetime.fromisoformat(now) - dt.datetime.fromisoformat(last["started_at"])
                    < dt.timedelta(minutes=RUN_MINUTES)):
                started = last["started_at"]
                self.db.execute("DELETE FROM company_revisions WHERE company_id = ? AND revision = ?",
                                (cid, last["revision"]))
        self.db.execute("INSERT INTO company_revisions (company_id, revision, at, started_at, user_id, action, sha256, "
                        "size, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (cid, rev, now, started, uid, action, sha(text), len(text.encode()),
                         zlib.compress(text.encode(), 6)))

    def revision(self, user: User, cid: str, rev: int) -> dict:
        with self.lock:
            self._need(user, cid)
            r = self.db.execute("SELECT data FROM company_revisions WHERE company_id = ? AND revision = ?",
                                (cid, rev)).fetchone()
            if r is None:
                raise CompanyError(f"revision {rev} is not kept: only the last save of each ten-minute run is", 404)
            return json.loads(zlib.decompress(r["data"]).decode())

    def restore(self, user: User, cid: str, rev: int, base_revision: int) -> SaveReport:
        doc = self.revision(user, cid, rev)
        return self.save(user, cid, doc, base_revision, action="restored", note=f"put back to revision {rev}")

    def delete(self, user: User, cid: str) -> None:
        with self.lock:
            self._need(user, cid, "owner")
            self.db.execute("UPDATE companies SET deleted = 1 WHERE id = ?", (cid,))
            self._log(cid, None, user.id, "deleted", "company deleted")

    # ---- members -------------------------------------------------------------------------------------------
    def members(self, user: User, cid: str) -> list[Member]:
        with self.lock:
            self._need(user, cid)
            out = [Member(user_id=r["user_id"], email=r["email"], name=r["name"], role=r["role"], since=r["added_at"])
                   for r in self.db.execute("SELECT m.user_id, u.email, u.name, m.role, m.added_at FROM members m JOIN "
                                            "users u ON u.id = m.user_id WHERE m.company_id = ? ORDER BY m.added_at, "
                                            "u.email", (cid,))]
            out += [Member(user_id=None, email=r["email"], name="", role=r["role"], since=r["at"])
                    for r in self.db.execute("SELECT * FROM invites WHERE company_id = ? ORDER BY at, email", (cid,))]
            return out

    def _owners(self, cid: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM members WHERE company_id = ? AND role = 'owner'",
                               (cid,)).fetchone()[0]

    def set_member(self, user: User, cid: str, email: str, role: str) -> list[Member]:
        """Add a member (or invite an e-mail without an account), or change a member's role."""
        if role not in ROLES:
            raise CompanyError(f"a role is one of {', '.join(ROLES)}", 422)
        email = email.strip()
        if not EMAIL.match(email):
            raise CompanyError("that does not look like an e-mail address", 422)
        with self.lock:
            self._need(user, cid, "owner")
            now = _iso(_now())
            u = self.db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if u is None:
                self.db.execute("INSERT INTO invites (company_id, email, role, invited_by, at) VALUES (?, ?, ?, ?, ?) "
                                "ON CONFLICT (company_id, email) DO UPDATE SET role = excluded.role",
                                (cid, email, role, user.id, now))
                self._log(cid, None, user.id, "member", f"{email} invited as {role}")
            else:
                cur = self.db.execute("SELECT role FROM members WHERE company_id = ? AND user_id = ?",
                                      (cid, u["id"])).fetchone()
                if cur and cur["role"] == "owner" and role != "owner" and self._owners(cid) == 1:
                    raise CompanyError("a company needs an owner: make someone else an owner first")
                self.db.execute("INSERT INTO members (company_id, user_id, role, added_at, added_by) VALUES (?, ?, ?, ?, ?) "
                                "ON CONFLICT (company_id, user_id) DO UPDATE SET role = excluded.role",
                                (cid, u["id"], role, now, user.id))
                who = self._name(u["id"])
                self._log(cid, None, user.id, "member",
                          f"{who}: {cur['role']} → {role}" if cur else f"{who} added as {role}")
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
            kept = {r[0] for r in self.db.execute("SELECT revision FROM company_revisions WHERE company_id = ?", (cid,))}
            q = "SELECT * FROM company_log WHERE company_id = ?" + (" AND seq < ?" if before else "") + \
                " ORDER BY seq DESC LIMIT ?"
            args = (cid, before, limit) if before else (cid, limit)
            return [LogRow(seq=r["seq"], revision=r["revision"], at=r["at"], user=self._name(r["user_id"]),
                           action=r["action"], summary=r["summary"],
                           changes=[ListChange(**c) for c in json.loads(r["detail"])],
                           kept=r["revision"] in kept and r["action"] != "member")
                    for r in self.db.execute(q, args)]


_by_store: dict[int, Companies] = {}


def get_companies() -> Companies:
    store = get_store()
    c = _by_store.get(id(store))
    if c is None or c.store is not store:
        c = Companies(store)
        _by_store.clear()
        _by_store[id(store)] = c
    return c
