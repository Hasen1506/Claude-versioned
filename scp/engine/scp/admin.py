"""The server administrator's commands (Phase L). Run next to the server, with the same ``SCP_DB``:

    python -m scp.admin backup <folder> [--keep 14]   copy the database now (safe while the server runs);
                                                      with DATABASE_URL, PostgreSQL into the same kind of file
    python -m scp.admin check <backup file>           what a backup holds
    python -m scp.admin restore <backup file>         put a backup back (stop the server first); with
                                                      DATABASE_URL, into that PostgreSQL database (empty only)
    python -m scp.admin reset-link <e-mail> [--url https://plan.example.com]
                                                      a link for that account to set a new password (1 day)
    python -m scp.admin users                         the accounts and their companies
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scp.admin", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("folder")
    b.add_argument("--keep", type=int, default=14)
    sub.add_parser("check").add_argument("file")
    sub.add_parser("restore").add_argument("file")
    r = sub.add_parser("reset-link")
    r.add_argument("email")
    r.add_argument("--url", default=os.environ.get("SCP_PUBLIC_URL", "http://localhost:8000"))
    sub.add_parser("users")
    a = ap.parse_args(argv)

    from .backup import backup, check, restore
    from .versions.store import get_store

    if a.cmd == "check":
        print("\n".join(check(a.file)))
        return 0
    url = os.environ.get("DATABASE_URL", "").strip()
    if a.cmd == "backup" and url:
        # ENTERPRISE_PLAN 1.6: one consistent snapshot of PostgreSQL, written as the same backup file SQLite makes
        from .backup import backup_postgres
        print(backup_postgres(url, a.folder, a.keep))
        return 0
    if a.cmd == "restore" and url:
        # into an empty database only (a new Neon branch or database): every field is compared before it commits
        from .migrate_postgres import migrate
        if not Path(a.file).is_file():
            print(f"not restored: there is no backup file {a.file}", file=sys.stderr)
            return 2
        try:
            check(a.file)
            migrate(Path(a.file), apply=True)
        except (ValueError, sqlite3.DatabaseError) as e:
            print(f"not restored: {e}. Restore into an empty database (a new Neon branch or database) and point "
                  "DATABASE_URL at it.", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "restore":
        db = os.environ.get("SCP_DB") or str(Path.home() / ".scp" / "scp.sqlite")
        kept = restore(a.file, db)
        print(f"restored {a.file} to {db}; the database it replaced is kept as {kept}")
        return 0
    store = get_store()
    if a.cmd == "backup":
        with store.lock:
            print(backup(store.db, a.folder, a.keep))
        return 0
    from .companies import get_companies
    c = get_companies()
    if a.cmd == "reset-link":
        token = c.reset_token(a.email, hours=24)
        if not token:
            print(f"no account for {a.email}", file=sys.stderr)
            return 1
        print(f"{a.url.rstrip('/')}/#/account/reset/{token}")
        return 0
    if a.cmd == "users":
        for u in c.db.execute("SELECT id, email, name, last_seen FROM users ORDER BY email"):
            comps = [f"{r['name']} ({r['role']})" for r in c.db.execute(
                "SELECT c.name, m.role FROM members m JOIN companies c ON c.id = m.company_id WHERE m.user_id = ? "
                "AND c.deleted = 0", (u["id"],))]
            print(f"{u['email']}\t{u['name']}\tlast seen {u['last_seen'] or 'never'}\t{', '.join(comps)}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
