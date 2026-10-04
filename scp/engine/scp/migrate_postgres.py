"""Copy a stopped-server SQLite backup to an empty PostgreSQL application schema.

Run: DATABASE_URL=... python -m scp.migrate_postgres backup.sqlite --apply
The source is opened read-only. Every copied field is compared before commit.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from psycopg import sql

from .companies.store import Companies
from .connect import imports, messages, outbox
from .tower.worklist import Tracker
from .versions.store import Store


def migrate(path: Path, apply: bool = False):
    source = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    target = Store(os.environ['DATABASE_URL'])
    if target.backend != 'postgresql':
        raise ValueError('Destination must be PostgreSQL')
    try:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        companies = Companies(target)
        Tracker(target)
        for module in (imports, messages, outbox):
            module._ensure(companies)
        connection = target.db.connection
        known = {r[0] for r in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='scp' AND table_type='BASE TABLE'")}
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables.discard('sqlite_sequence')
        if not tables <= known:
            raise ValueError('Unknown source tables; refusing incomplete migration')
        dependencies = {t: {r['table'] for r in source.execute(f'PRAGMA foreign_key_list("{t}")')
                            if r['table'] != t} for t in tables}
        ordered = []
        while dependencies:
            ready = sorted(t for t, deps in dependencies.items() if deps <= set(ordered))
            if not ready:
                raise ValueError('Unexpected foreign-key dependency cycle')
            ordered.extend(ready)
            for t in ready:
                del dependencies[t]
        counts = {}
        with connection.transaction():
            connection.execute('SELECT pg_advisory_xact_lock(739310021)')
            # Prevent an app using the destination from writing during the copy.
            for table in sorted(known):
                connection.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(sql.Identifier(table)))
                if connection.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]:
                    raise ValueError('Destination is nonempty; refusing to overwrite')
            for table in ordered:
                rows = [dict(r) for r in source.execute(f'SELECT * FROM "{table}"')]
                columns = [r['name'] for r in source.execute(f'PRAGMA table_info("{table}")')]
                target_columns = {r[0] for r in connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='scp' AND table_name=%s",
                    (table,))}
                if not set(columns) <= target_columns:
                    raise ValueError('Source column is missing from destination')
                if table == 'versions':
                    pending, rows, inserted = rows, [], set()
                    while pending:
                        ready = [r for r in pending if not r['parent_id'] or r['parent_id'] in inserted]
                        if not ready:
                            raise ValueError('Version parent is missing or cyclic')
                        rows.extend(ready)
                        inserted.update(r['id'] for r in ready)
                        pending = [r for r in pending if r['id'] not in inserted]
                statement = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                    sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                    sql.SQL(',').join(sql.Placeholder() for _ in columns))
                for row in rows:
                    connection.execute(statement, [row[c] for c in columns])
                copied = [dict(r) for r in connection.execute(sql.SQL('SELECT {} FROM {}').format(
                    sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table)))]
                # repr(bytes) preserves compressed revision payloads exactly.
                def canonical(values, fields=columns):
                    return sorted(repr([(c, r[c]) for c in fields]) for r in values)
                if canonical(rows) != canonical(copied):
                    raise ValueError('Full-field migration verification failed')
                counts[table] = len(rows)
                for column in columns:
                    sequence = connection.execute('SELECT pg_get_serial_sequence(%s,%s)',
                                                  (f'scp.{table}', column)).fetchone()[0]
                    if sequence:
                        maximum = max((r[column] for r in rows), default=0)
                        connection.execute('SELECT setval(%s,%s,%s)', (sequence, maximum or 1, bool(maximum)))
            if not apply:
                raise DryRun(counts)
        print('MIGRATION COMMITTED: verified row counts', counts)
    except DryRun as dry:
        print('DRY RUN: copy verified and rolled back; row counts', dry.counts)
    finally:
        source.close()
        target.db.close()


class DryRun(Exception):
    def __init__(self, counts):
        self.counts = counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    migrate(args.backup, args.apply)
