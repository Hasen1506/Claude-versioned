"""Plan versions in SQLite (blueprint P8).

A *base* version is an immutable snapshot of a planning dataset: its canonical JSON text and SHA-256 are
written once and never updated. A *scenario* is a mutable branch of a base (or of another scenario):
it can be edited, discarded, or promoted — promotion writes a new base, it never rewrites the old one.
Every action is appended to an audit log.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

from ..model import Dataset
from ..model.common import Out

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('base', 'scenario')),
  parent_id   TEXT REFERENCES versions(id),
  status      TEXT NOT NULL CHECK (status IN ('active', 'discarded', 'promoted', 'superseded')),
  note        TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  planning_start TEXT NOT NULL,
  sha256      TEXT NOT NULL,
  size        INTEGER NOT NULL,
  dataset     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS version_log (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id  TEXT NOT NULL REFERENCES versions(id),
  at          TEXT NOT NULL,
  action      TEXT NOT NULL,
  detail      TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS base_is_immutable
BEFORE UPDATE OF dataset, sha256 ON versions
WHEN OLD.kind = 'base'
BEGIN
  SELECT RAISE(ABORT, 'a base version is immutable');
END;
"""


class VersionError(Exception):
    """A request the version rules do not allow (maps to HTTP 409), or an unknown id (404)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class LogEntry(Out):
    at: str
    action: str
    detail: str


class VersionMeta(Out):
    id: str
    name: str
    kind: str
    parent_id: str | None
    status: str
    note: str
    created_at: str
    updated_at: str
    planning_start: str
    sha256: str
    size: int
    company: str


class VersionDoc(Out):
    meta: VersionMeta
    dataset: Dataset
    log: list[LogEntry]


def canonical(ds: Dataset) -> str:
    """The byte-exact form a version is stored and hashed in."""
    return json.dumps(ds.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | os.PathLike = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()

    # ---- helpers ------------------------------------------------------------------------------------
    def _row(self, vid: str) -> sqlite3.Row:
        r = self.db.execute("SELECT * FROM versions WHERE id = ?", (vid,)).fetchone()
        if r is None:
            raise VersionError(f"no version '{vid}'", 404)
        return r

    @staticmethod
    def _meta(r: sqlite3.Row) -> VersionMeta:
        company = json.loads(r["dataset"])["settings"].get("company_name", "")
        return VersionMeta(id=r["id"], name=r["name"], kind=r["kind"], parent_id=r["parent_id"], status=r["status"],
                           note=r["note"], created_at=r["created_at"], updated_at=r["updated_at"],
                           planning_start=r["planning_start"], sha256=r["sha256"], size=r["size"], company=company)

    def _next_id(self) -> str:
        n = self.db.execute("SELECT COUNT(*) FROM versions").fetchone()[0]
        while True:
            n += 1
            vid = f"V{n:04d}"
            if self.db.execute("SELECT 1 FROM versions WHERE id = ?", (vid,)).fetchone() is None:
                return vid

    def _log(self, vid: str, action: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO version_log (version_id, at, action, detail) VALUES (?, ?, ?, ?)",
                        (vid, _now(), action, detail))

    def _insert(self, ds: Dataset, name: str, kind: str, parent: str | None, note: str) -> str:
        text = canonical(ds)
        vid = self._next_id()
        now = _now()
        self.db.execute(
            "INSERT INTO versions (id, name, kind, parent_id, status, note, created_at, updated_at, planning_start, "
            "sha256, size, dataset) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)",
            (vid, name, kind, parent, note, now, now, ds.settings.planning_start.isoformat(), sha(text),
             len(text.encode("utf-8")), text))
        return vid

    # ---- queries ------------------------------------------------------------------------------------
    def list(self) -> list[VersionMeta]:
        with self.lock:
            return [self._meta(r) for r in self.db.execute("SELECT * FROM versions ORDER BY created_at, id")]

    def meta(self, vid: str) -> VersionMeta:
        with self.lock:
            return self._meta(self._row(vid))

    def text(self, vid: str) -> str:
        with self.lock:
            return self._row(vid)["dataset"]

    def dataset(self, vid: str) -> Dataset:
        return Dataset.model_validate_json(self.text(vid))

    def get(self, vid: str) -> VersionDoc:
        with self.lock:
            r = self._row(vid)
            log = [LogEntry(at=x["at"], action=x["action"], detail=x["detail"]) for x in
                   self.db.execute("SELECT * FROM version_log WHERE version_id = ? ORDER BY seq", (vid,))]
            return VersionDoc(meta=self._meta(r), dataset=Dataset.model_validate_json(r["dataset"]), log=log)

    # ---- actions ------------------------------------------------------------------------------------
    def save_base(self, ds: Dataset, name: str, note: str = "") -> VersionMeta:
        with self.lock:
            vid = self._insert(ds, name, "base", None, note)
            self._log(vid, "created", "base version")
            return self._meta(self._row(vid))

    def branch(self, parent: str, name: str, note: str = "") -> VersionMeta:
        with self.lock:
            p = self._row(parent)
            if p["status"] == "discarded":
                raise VersionError(f"{parent} is discarded")
            vid = self._insert(Dataset.model_validate_json(p["dataset"]), name, "scenario", parent, note)
            self._log(vid, "branched", f"from {parent}")
            self._log(parent, "branched", f"to {vid}")
            return self._meta(self._row(vid))

    def update(self, vid: str, ds: Dataset) -> VersionMeta:
        with self.lock:
            r = self._row(vid)
            if r["kind"] != "scenario":
                raise VersionError(f"{vid} is a base version: base versions are immutable — branch a scenario to change it")
            if r["status"] != "active":
                raise VersionError(f"{vid} is {r['status']}")
            text = canonical(ds)
            if text == r["dataset"]:
                return self._meta(r)
            self.db.execute("UPDATE versions SET dataset = ?, sha256 = ?, size = ?, planning_start = ?, updated_at = ? "
                            "WHERE id = ?", (text, sha(text), len(text.encode("utf-8")),
                                             ds.settings.planning_start.isoformat(), _now(), vid))
            self._log(vid, "saved", sha(text)[:12])
            return self._meta(self._row(vid))

    def discard(self, vid: str) -> VersionMeta:
        with self.lock:
            r = self._row(vid)
            if r["kind"] != "scenario":
                raise VersionError(f"{vid} is a base version and cannot be discarded")
            if r["status"] != "active":
                raise VersionError(f"{vid} is already {r['status']}")
            self.db.execute("UPDATE versions SET status = 'discarded', updated_at = ? WHERE id = ?", (_now(), vid))
            self._log(vid, "discarded")
            return self._meta(self._row(vid))

    def promote(self, vid: str, name: str | None = None, note: str = "") -> VersionMeta:
        """A scenario becomes the new base: a new immutable base version with the scenario's content. The
        base it descends from is marked superseded (its content is untouched)."""
        with self.lock:
            r = self._row(vid)
            if r["kind"] != "scenario" or r["status"] != "active":
                raise VersionError(f"only an active scenario can be promoted ({vid} is a {r['status']} {r['kind']})")
            self.db.execute("BEGIN")
            try:
                new = self._insert(Dataset.model_validate_json(r["dataset"]), name or r["name"], "base", vid,
                                   note or f"promoted from scenario {vid}")
                self.db.execute("UPDATE versions SET status = 'promoted', updated_at = ? WHERE id = ?", (_now(), vid))
                root = self._base_of(vid)
                if root:
                    self.db.execute("UPDATE versions SET status = 'superseded', updated_at = ? WHERE id = ? AND "
                                    "status = 'active'", (_now(), root))
                    self._log(root, "superseded", f"by {new}")
                self._log(vid, "promoted", f"to {new}")
                self._log(new, "created", f"promoted from {vid}")
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return self._meta(self._row(new))

    def _base_of(self, vid: str) -> str | None:
        cur: str | None = self._row(vid)["parent_id"]
        while cur:
            r = self._row(cur)
            if r["kind"] == "base":
                return cur
            cur = r["parent_id"]
        return None


_store: Store | None = None


def get_store() -> Store:
    """The process-wide store: ``$SCP_DB`` or ``~/.scp/scp.sqlite``."""
    global _store
    if _store is None:
        _store = Store(os.environ.get("SCP_DB") or Path.home() / ".scp" / "scp.sqlite")
    return _store


def set_store(store: Store | None) -> None:
    global _store
    _store = store
