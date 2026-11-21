"""The store's lock, held across server processes (Phase 1.1 of ENTERPRISE_PLAN).

Every read-then-write holds a store lock. Global operations take it exclusively.
Selected PostgreSQL company and authentication operations take it in shared mode,
with a separate connection and an exclusive lock for their own scope:

* PostgreSQL: session advisory locks held through reads, writes and transaction commit;
* a SQLite file: an exclusive ``flock`` on ``<file>.lock`` beside it;
* SQLite in memory: nothing more (one process by nature).

The work that takes time (planning, password hashing) runs outside it, so several processes plan in parallel while
their reads and writes of the database take turns.

``lead(name)`` says whether this process is the one that runs a server-wide clock (scheduled imports, reminders, the
nightly copy): the first to ask keeps it until it stops, and then the next process to ask takes over.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

try:
    import fcntl
except ImportError:                     # not on a POSIX system: one process only
    fcntl = None  # type: ignore[assignment]


@dataclass
class _Admission:
    lock: Any = field(default_factory=threading.Lock)
    users: int = 0


class StoreLock:
    """A re-entrant lock: a thread lock within the process; at its outermost level the database's lock as well."""

    def __init__(self, db: Any, path: str) -> None:
        self._thread = threading.RLock()
        self._depth = 0                 # touched only by the thread that holds ``_thread``
        self._local = threading.local()
        self._admissions: dict[str, _Admission] = {}
        self._admission_guard = threading.Lock()
        self._db = db
        self._file: int | None = None
        self._path = path
        self._leads: dict[str, Any] = {}
        if getattr(db, "backend", "sqlite") != "postgresql" and path != ":memory:" and fcntl is not None:
            self._file = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)

    def acquire(self, blocking: bool = True) -> bool:
        if getattr(self._local, "scope", None) is not None:
            return True
        if not self._thread.acquire(blocking):
            return False
        if self._depth == 0:
            try:
                got = self._take(blocking)
            except BaseException:
                self._thread.release()
                raise
            if not got:
                self._thread.release()
                return False
        self._depth += 1
        self._local.global_depth = self._depth
        return True

    def release(self) -> None:
        if getattr(self._local, "scope", None) is not None:
            return
        self._depth -= 1
        self._local.global_depth = self._depth
        try:
            if self._depth == 0:
                self._give()
        finally:
            self._thread.release()

    def __enter__(self) -> StoreLock:
        self.acquire()
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()

    @contextmanager
    def scoped(self, namespace: str, key: str):
        """Serialize one company or credential, with the global lock as a compatibility gate."""
        scope = f"{namespace}:{key}"
        outer = getattr(self._local, "scope", None)
        if outer is not None:
            if outer != scope:
                raise RuntimeError("cannot enter a different store scope within a scoped operation")
            yield
            return
        if getattr(self._db, "backend", "") != "postgresql" or getattr(self._local, "global_depth", 0):
            with self:
                yield
            return
        with self._admission_guard:
            admission = self._admissions.setdefault(scope, _Admission())
            admission.users += 1
        try:
            # Same-scope waiters in this process do not use up the connection pool.
            with admission.lock, self._db.scoped(scope):
                self._local.scope = scope
                try:
                    yield
                finally:
                    del self._local.scope
        finally:
            with self._admission_guard:
                admission.users -= 1
                if not admission.users:
                    del self._admissions[scope]

    def _take(self, blocking: bool) -> bool:
        if getattr(self._db, "backend", "") == "postgresql":
            return self._db.hold(blocking)
        if self._file is not None:
            try:
                fcntl.flock(self._file, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                return False
        return True

    def _give(self) -> None:
        if getattr(self._db, "backend", "") == "postgresql":
            self._db.let_go()
        elif self._file is not None:
            fcntl.flock(self._file, fcntl.LOCK_UN)

    def lead(self, name: str) -> bool:
        """Whether this process runs the server-wide job ``name``: it keeps the role while it runs."""
        if getattr(self._local, "scope", None) is not None:
            raise RuntimeError("global job leadership requires the store's global connection")
        with self:
            if getattr(self._db, "backend", "") == "postgresql":
                return self._db.lead(name)
            if self._file is None:
                return True
            fd = self._leads.get(name)
            if fd is not None:
                return True
            fd = os.open(f"{self._path}.{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                return False
            self._leads[name] = fd       # kept open (and so held) while the process runs
            return True

    def __del__(self) -> None:
        for fd in [self._file, *self._leads.values()]:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
