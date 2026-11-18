"""Nestable database transactions for operations spanning several stores.

Callers hold the store lock. A nested company save must never commit its caller's
inbound-message transaction. SQLite savepoints and psycopg transactions provide
the same commit/rollback boundary on both supported backends.
"""
from __future__ import annotations

from contextlib import contextmanager
from itertools import count

_savepoints = count()


@contextmanager
def atomic(db):
    if getattr(db, "backend", "sqlite") == "postgresql":
        with db.connection.transaction():
            yield
        return
    name = f"scp_atomic_{next(_savepoints)}"
    db.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        db.execute(f"ROLLBACK TO SAVEPOINT {name}")
        db.execute(f"RELEASE SAVEPOINT {name}")
        raise
    else:
        db.execute(f"RELEASE SAVEPOINT {name}")
