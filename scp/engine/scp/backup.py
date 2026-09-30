"""Backups of the server's database (Phase L): a consistent copy taken while the server runs, every night if set
up, and putting one back.

* ``SCP_BACKUP_DIR``: where the nightly copies go (none: no nightly copy); ``SCP_BACKUP_HOUR`` (UTC, default 2) when;
  ``SCP_BACKUP_KEEP`` (default 14) how many are kept, the oldest removed.
* ``python -m scp.admin backup <dir>`` takes one now; ``python -m scp.admin restore <file>`` puts one back (stop the
  server first: the current database is kept beside it as ``*.before-restore``).
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

PREFIX = "scp-"


def backup(db: sqlite3.Connection, folder: str | os.PathLike, keep: int = 14, now: dt.datetime | None = None) -> Path:
    """Copy the database into ``folder`` as ``scp-YYYYMMDD-HHMMSS.sqlite`` (SQLite's online backup: consistent
    while others write) and remove all but the newest ``keep``."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%d-%H%M%S")
    path = out / f"{PREFIX}{stamp}.sqlite"
    dst = sqlite3.connect(path)
    try:
        db.backup(dst)
    finally:
        dst.close()
    for old in sorted(out.glob(f"{PREFIX}*.sqlite"))[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return path


def check(path: str | os.PathLike) -> list[str]:
    """What is in a backup: its companies and accounts (and SQLite's own integrity check)."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise ValueError(f"{path} is damaged: {ok}")
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        companies = db.execute("SELECT name, revision FROM companies WHERE deleted = 0 ORDER BY name").fetchall()
        return [f"{users} accounts", *(f"{n} (revision {r})" for n, r in companies)]
    finally:
        db.close()


def restore(backup_file: str | os.PathLike, db_path: str | os.PathLike) -> Path:
    """Put a backup in place of the database (the server must be stopped); the database it replaces is kept beside
    it. Returns where that copy is."""
    source = Path(backup_file).resolve()
    check(source)
    target = Path(db_path)
    if source == target.resolve():
        raise ValueError("the backup and target database must be different files")
    target.parent.mkdir(parents=True, exist_ok=True)
    kept = target.with_name(target.name + ".before-restore")
    suffix = 1
    while kept.exists() or kept.resolve() == source:
        suffix += 1
        kept = target.with_name(target.name + f".before-restore-{suffix}")

    def stage() -> Path:
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".restore", dir=target.parent)
        os.close(fd)
        return Path(name)

    pending = stage()
    previous = None
    try:
        # Finish and validate the incoming copy before touching the current database. A failed
        # copy (full disk, permissions, interrupted I/O) cannot truncate the live file.
        shutil.copy2(source, pending)
        check(pending)
        if target.exists():
            previous = stage()
            # A stopped/crashed database can still have committed pages in its WAL. SQLite's
            # backup API preserves them in the recovery copy, unlike copying only the main file.
            current = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
            saved = sqlite3.connect(previous)
            try:
                current.backup(saved)
            finally:
                saved.close()
                current.close()
            os.replace(previous, kept)
        os.replace(pending, target)
        for extra in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
            extra.unlink(missing_ok=True)
    finally:
        pending.unlink(missing_ok=True)
        if previous is not None:
            previous.unlink(missing_ok=True)
    return kept


def start_nightly(db: sqlite3.Connection, lock: threading.RLock) -> threading.Thread | None:
    """With SCP_BACKUP_DIR set, a thread that backs the database up once a day at SCP_BACKUP_HOUR (UTC)."""
    folder = os.environ.get("SCP_BACKUP_DIR", "").strip()
    if not folder:
        return None
    hour = int(os.environ.get("SCP_BACKUP_HOUR", "2"))
    keep = int(os.environ.get("SCP_BACKUP_KEEP", "14"))

    def run() -> None:
        while True:
            now = dt.datetime.now(dt.UTC)
            nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if nxt <= now:
                nxt += dt.timedelta(days=1)
            time.sleep((nxt - now).total_seconds())
            try:
                with lock:
                    path = backup(db, folder, keep)
                print(f"backup: {path}", flush=True)
            except Exception as e:                      # a failed night must not stop the next
                print(f"backup failed: {e}", flush=True)

    t = threading.Thread(target=run, name="nightly-backup", daemon=True)
    t.start()
    return t
