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
from typing import Any
from pathlib import Path

PREFIX = "scp-"


def backup(db: sqlite3.Connection, folder: str | os.PathLike, keep: int = 14, now: dt.datetime | None = None) -> Path:
    """Copy the database into ``folder`` as ``scp-YYYYMMDD-HHMMSS.sqlite`` (SQLite's online backup: consistent
    while others write) and remove all but the newest ``keep``."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%d-%H%M%S")
    fd, name = tempfile.mkstemp(prefix=".scp-backup-", suffix=".tmp", dir=out)
    os.close(fd)
    pending = Path(name)
    try:
        dst = sqlite3.connect(pending)
        try:
            db.backup(dst)
        finally:
            dst.close()
        path = _publish(pending, out, stamp)
    finally:
        pending.unlink(missing_ok=True)
    _prune(out, keep)
    return path


def _publish(pending: Path, out: Path, stamp: str) -> Path:
    suffix = 0
    while True:
        path = out / f"{PREFIX}{stamp}{f'~{suffix:06d}' if suffix else ''}.sqlite"
        try:
            os.link(pending, path)  # publish a complete copy without overwriting another same-second backup
            return path
        except FileExistsError:
            suffix += 1


def _prune(out: Path, keep: int) -> None:
    for old in sorted(out.glob(f"{PREFIX}*.sqlite"))[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)


def backup_postgres(url: str, folder: str | os.PathLike, keep: int = 14, now: dt.datetime | None = None) -> Path:
    """Copy a PostgreSQL database into ``folder`` as a backup file of the same kind as a SQLite server's (so
    ``check`` reads it, ``restore`` puts it back as a file, and ``scp.migrate_postgres`` puts it into an empty
    PostgreSQL database). One consistent snapshot (a read-only, repeatable-read transaction on its own connection):
    the server goes on saving meanwhile and nothing waits for it. Every table's row count is compared."""
    import psycopg

    from .companies.store import Companies
    from .connect import imports, messages, outbox
    from .postgres import Postgres, row_factory
    from .tower.worklist import Tracker
    from .versions.store import Store

    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%d-%H%M%S")
    fd, name = tempfile.mkstemp(prefix=".scp-backup-", suffix=".tmp", dir=out)
    os.close(fd)
    pending = Path(name)
    pending.unlink()
    source = Postgres(url)          # checks the address the way the server does (TLS on a hosted server)
    try:
        dst = Store(str(pending))   # the server's own schema, as SQLite
        c = Companies(dst)
        Tracker(dst)
        for module in (imports, messages, outbox):
            module._ensure(c)
        conn = source.connection
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            tables = [r["table_name"] for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'scp' "
                "AND table_type = 'BASE TABLE' ORDER BY table_name")]
            have = {r[0] for r in dst.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not set(tables) <= have:
                raise ValueError(f"tables this version does not know: {sorted(set(tables) - have)}")
            dst.db.execute("PRAGMA foreign_keys = OFF")     # tables in any order; checked once all are in
            dst.db.execute("BEGIN")
            counts: dict[str, int] = {}
            for t in tables:
                cols = [r["column_name"] for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'scp' AND table_name = %s "
                    "ORDER BY ordinal_position", (t,))]
                mine = {r[1] for r in dst.db.execute(f'PRAGMA table_info("{t}")')}
                if not set(cols) <= mine:
                    raise ValueError(f"columns of {t} this version does not know: {sorted(set(cols) - mine)}")
                insert = (f'INSERT INTO "{t}" ({", ".join(f"{chr(34)}{c}{chr(34)}" for c in cols)}) '
                          f'VALUES ({", ".join("?" for _ in cols)})')
                n = 0
                with conn.cursor(name=f"scp_backup_{t}", row_factory=row_factory) as cur:
                    cur.itersize = 500
                    cur.execute(psycopg.sql.SQL("SELECT {} FROM {}").format(
                        psycopg.sql.SQL(", ").join(map(psycopg.sql.Identifier, cols)), psycopg.sql.Identifier(t)))
                    batch: list[list[Any]] = []
                    for row in cur:
                        batch.append([row[c] for c in cols])
                        if len(batch) >= 500:
                            dst.db.executemany(insert, batch)
                            n += len(batch)
                            batch = []
                    dst.db.executemany(insert, batch)
                    n += len(batch)
                counts[t] = n
            dst.db.execute("COMMIT")
        finally:
            conn.execute("ROLLBACK")
        broken = dst.db.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise ValueError(f"the copy has {len(broken)} row(s) pointing at rows that are not there")
        for t, n in counts.items():
            got = dst.db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if got != n:
                raise ValueError(f"{t}: {n} rows read, {got} written")
        dst.db.close()
        check(pending)
        path = _publish(pending, out, stamp)
    finally:
        source.close()
        for extra in (pending, Path(str(pending) + ".lock"), Path(str(pending) + "-wal"), Path(str(pending) + "-shm")):
            extra.unlink(missing_ok=True)
    _prune(out, keep)
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


def start_nightly(db: sqlite3.Connection, lock: Any) -> threading.Thread | None:
    """With SCP_BACKUP_DIR set, a thread that backs the database up once a day at SCP_BACKUP_HOUR (UTC)."""
    if getattr(db, "backend", "sqlite") == "postgresql":
        if os.environ.get("SCP_BACKUP_DIR"):
            raise ValueError("SCP_BACKUP_DIR is SQLite-only; use PostgreSQL backups and Neon restore history")
        return None
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
            if hasattr(lock, "lead") and not lock.lead("backup"):    # another server process on the file copies it
                continue
            try:
                with lock:
                    path = backup(db, folder, keep)
                print(f"backup: {path}", flush=True)
            except Exception as e:                      # a failed night must not stop the next
                print(f"backup failed: {e}", flush=True)

    t = threading.Thread(target=run, name="nightly-backup", daemon=True)
    t.start()
    return t
