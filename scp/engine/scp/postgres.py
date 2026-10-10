"""PostgreSQL implementation of the small SQL interface used by SCP stores.

SQL is application-owned; values always remain bound parameters. SQLite stays
available for local files. Hosted PostgreSQL requires verified TLS.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import certifi
import psycopg


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Result:
    def __init__(self, rows=(), rowcount=0, lastrowid=None):
        self.rows = iter(rows)
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return self.rows


def row_factory(cursor):
    names = [col.name for col in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, [bytes(v) if isinstance(v, memoryview) else v for v in values], strict=True))


def parameters(sql):
    # Qmarks inside quoted SQL strings are literal, never placeholders.
    out, quoted, i = [], False, 0
    while i < len(sql):
        c = sql[i]
        if c == "'":
            if quoted and i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            quoted = not quoted
        out.append('%s' if c == '?' and not quoted else '%%' if c == '%' else c)
        i += 1
    return ''.join(out)


LOCK = 739310021                 # the store's lock: every transaction takes it, and so does StoreLock (scp.dblock)
LEADS = {'clock': 739310022, 'backup': 739310023}   # server-wide jobs one process runs


class Postgres:
    backend = 'postgresql'

    def __init__(self, url):
        parsed = urlsplit(url)
        local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        mode = parse_qs(parsed.query).get('sslmode', ['verify-full'])[0]
        if not local and mode != 'verify-full':
            raise ValueError('Hosted PostgreSQL requires sslmode=verify-full')
        self.url = url
        self.options = {} if local else {'sslmode': 'verify-full', 'sslrootcert': certifi.where()}
        self.leading = {}            # job -> the connection that holds its lock
        self._connect()

    def _connect(self):
        self.connection = psycopg.connect(self.url, autocommit=True, row_factory=row_factory, **self.options)
        self.connection.execute('CREATE SCHEMA IF NOT EXISTS scp')
        self.connection.execute('SET search_path TO scp, public')
        self.connection.execute('CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public')

    def hold(self, blocking=True):
        """Take the store's lock for this session (it waits for another process holding it, unless not
        ``blocking``). A connection the server dropped while idle (a database that sleeps, a restart) is made again
        first: nothing was under way."""
        sql = f'SELECT pg_advisory_lock({LOCK})' if blocking else f'SELECT pg_try_advisory_lock({LOCK})'
        try:
            row = self.connection.execute(sql).fetchone()
        except psycopg.OperationalError:
            try:
                self.connection.close()
            except psycopg.Error:
                pass
            self._connect()
            row = self.connection.execute(sql).fetchone()
        return blocking or bool(row[0])

    def let_go(self):
        try:
            self.connection.execute(f'SELECT pg_advisory_unlock({LOCK})')
        except psycopg.Error:        # a lost connection holds nothing any more
            pass

    def lead(self, name):
        """Whether this process runs the job ``name``: the first session to ask keeps it while it is connected."""
        if self.leading.get(name) is self.connection and not self.connection.closed:
            return True
        row = self.connection.execute(f'SELECT pg_try_advisory_lock({LEADS[name]})').fetchone()
        got = bool(list(row.values())[0])
        if got:
            self.leading[name] = self.connection
        return got

    def close(self):
        self.connection.close()

    def execute(self, sql, args=()):
        if sql == 'PRAGMA foreign_keys = ON':
            return Result()
        info = re.fullmatch(r'PRAGMA table_info\((\w+)\)', sql)
        if info:
            cur = self.connection.execute(
                "SELECT ordinal_position - 1 AS cid, column_name AS name FROM information_schema.columns "
                "WHERE table_schema='scp' AND table_name=%s ORDER BY ordinal_position", (info[1],))
            return Result(cur.fetchall())
        if sql.strip().upper() == 'BEGIN':
            self.connection.execute('BEGIN')
            self.connection.execute(f'SELECT pg_advisory_xact_lock({LOCK})')
            return Result()
        ignore = sql.startswith('INSERT OR IGNORE INTO ')
        if ignore:
            sql = sql.replace('INSERT OR IGNORE INTO ', 'INSERT INTO ', 1) + ' ON CONFLICT DO NOTHING'
        sql = re.sub(r'\bLIKE\b', 'ILIKE', sql)
        sql = sql.replace('MAX(last_seen, ?)', 'GREATEST(last_seen, ?)')
        inserted = re.match(r'INSERT INTO (change_requests|messages|mail_outbox)\b', sql)
        if inserted:
            sql += ' RETURNING ' + ('id' if inserted[1] == 'change_requests' else 'seq')
        cur = self.connection.execute(parameters(sql), args)
        rows = cur.fetchall() if cur.description else []
        return Result(rows, cur.rowcount, rows[0][0] if inserted and rows else None)

    def executemany(self, sql, rows):
        for args in rows:
            self.execute(sql, args)

    def executescript(self, script):
        immutable = 'CREATE TRIGGER IF NOT EXISTS base_is_immutable' in script
        script = re.sub(r'CREATE TRIGGER IF NOT EXISTS base_is_immutable.*?END;', '', script, flags=re.S)
        script = re.sub(r'\bINTEGER PRIMARY KEY AUTOINCREMENT\b', 'BIGSERIAL PRIMARY KEY', script)
        script = re.sub(r'\bBLOB\b', 'BYTEA', script)
        script = re.sub(r'\bREAL\b', 'DOUBLE PRECISION', script)
        script = re.sub(r'email TEXT NOT NULL( UNIQUE)? COLLATE NOCASE',
                        lambda m: 'email CITEXT NOT NULL' + (m[1] or ''), script)
        with self.connection.transaction():
            self.connection.execute(f'SELECT pg_advisory_xact_lock({LOCK})')
            self.connection.execute(script, prepare=False)
            if immutable:
                self.connection.execute("""
                CREATE OR REPLACE FUNCTION scp.reject_base_update() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF OLD.kind = 'base' THEN RAISE EXCEPTION 'a base version is immutable'; END IF;
                  RETURN NEW;
                END $$;
                CREATE OR REPLACE TRIGGER base_is_immutable BEFORE UPDATE OF dataset, sha256 ON scp.versions
                FOR EACH ROW EXECUTE FUNCTION scp.reject_base_update();
                """, prepare=False)
