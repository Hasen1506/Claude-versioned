"""Several server processes on one database (ENTERPRISE_PLAN 1.1): saves that race each other never lose one, never
give two saves the same revision, and the one that comes second is told so (409) rather than written over the first.
Run on a SQLite file always, and on PostgreSQL when ``SCP_TEST_POSTGRES`` names a server this test may create
databases on (CI starts one)."""
from __future__ import annotations

import multiprocessing as mp
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from scp.companies.store import Companies, CompanyError, get_companies
from scp.versions.store import Store, set_store

from .factory import base

PG = os.environ.get("SCP_TEST_POSTGRES", "").strip()
ROUNDS = 15


@pytest.fixture(params=["sqlite"] + (["postgresql"] if PG else []))
def database(request, tmp_path):
    if request.param == "sqlite":
        yield str(tmp_path / "scp.sqlite")
        return
    import psycopg
    name = "scp_mp_" + secrets.token_hex(6)
    with psycopg.connect(PG, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    yield PG.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(PG, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


def results(procs, out) -> list:
    """What each process put on the queue; a process that died says so at once (not after a long wait)."""
    import queue
    import time
    got, deadline = [], time.monotonic() + 120
    while len(got) < len(procs):
        try:
            got.append(out.get(timeout=0.5))
        except queue.Empty:
            dead = [p for p in procs if p.exitcode not in (None, 0)]
            assert not dead, f"a server process failed (exit code {dead[0].exitcode})"
            assert time.monotonic() < deadline, "the processes did not finish"
    return got


def company(url: str) -> tuple[str, str, int]:
    c = Companies(Store(url))
    s = c.signup("owner@acme.example", "Owner", "correct horse battery")
    doc = base()
    doc["settings"]["company_name"] = "Race Ltd"
    meta = c.create(s.user, doc)
    c.store.db.close()
    return s.user.id, meta.id, meta.revision


def _saver(url: str, uid: str, cid: str, tag: str, start, out) -> None:
    """One server process: save a change ``ROUNDS`` times, each over the latest revision it reads; a refusal (someone
    else saved in between) is read again and tried again, as the browser does."""
    c = Companies(Store(url))
    user = c._user(uid)
    start.wait()
    saved, refused = [], 0
    for k in range(ROUNDS):
        while True:
            doc = c.open(user, cid)
            d = doc.dataset
            d["settings"]["company_name"] = f"{tag}-{k}"
            try:
                rep = c.save(user, cid, d, doc.meta.revision)
            except CompanyError as e:
                assert e.status == 409, e
                refused += 1
                continue
            assert rep.saved
            saved.append(rep.meta.revision)
            break
    out.put((tag, saved, refused))


def test_two_processes_saving_at_once_lose_nothing(database):
    uid, cid, first = company(database)
    ctx = mp.get_context("spawn")
    start, out = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=_saver, args=(database, uid, cid, tag, start, out)) for tag in ("a", "b")]
    for p in procs:
        p.start()
    got = results(procs, out)
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    revisions = sorted(r for _, saved, _ in got for r in saved)
    # every save got its own revision, one after another, none written over another
    assert revisions == list(range(first + 1, first + 1 + 2 * ROUNDS))
    c = Companies(Store(database))
    user = c._user(uid)
    latest = c.open(user, cid)
    assert latest.meta.revision == first + 2 * ROUNDS
    kept = c.db.execute("SELECT revision FROM company_revisions WHERE company_id = ? ORDER BY revision",
                        (cid,)).fetchall()
    assert [r[0] for r in kept] == list(range(first, first + 1 + 2 * ROUNDS))
    # the last save is the one the company holds
    last_tag = max(got, key=lambda g: max(g[1]))[0]
    assert latest.dataset["settings"]["company_name"] == f"{last_tag}-{ROUNDS - 1}"


def _stale(url: str, uid: str, cid: str, rev: int, tag: str, start, out) -> None:
    c = Companies(Store(url))
    user = c._user(uid)
    d = c.open(user, cid).dataset
    d["settings"]["company_name"] = tag
    start.wait()
    try:
        c.save(user, cid, d, rev)
        out.put((tag, "saved"))
    except CompanyError as e:
        out.put((tag, e.status))


def test_two_saves_over_the_same_revision_one_wins_one_is_told(database):
    uid, cid, first = company(database)
    ctx = mp.get_context("spawn")
    start, out = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=_stale, args=(database, uid, cid, first, tag, start, out)) for tag in ("a", "b")]
    for p in procs:
        p.start()
    got = dict(results(procs, out))
    for p in procs:
        p.join(timeout=60)
    assert sorted(got.values(), key=str) == [409, "saved"]
    c = Companies(Store(database))
    latest = c.open(c._user(uid), cid)
    assert latest.meta.revision == first + 1
    assert latest.dataset["settings"]["company_name"] == next(t for t, v in got.items() if v == "saved")


def test_the_lock_is_held_across_connections(database):
    """A second store on the same database (another process, as far as the database can tell) waits for the first."""
    a, b = Store(database), Store(database)
    held, done = threading.Event(), threading.Event()

    def hold() -> None:
        with a.lock:
            held.set()
            done.wait(10)
    t = threading.Thread(target=hold)
    t.start()
    held.wait(10)
    assert b.lock.acquire(blocking=False) is False
    done.set()
    t.join()
    assert b.lock.acquire(blocking=False) is True
    b.lock.release()


def test_postgres_saves_serialize_per_company_and_leave_other_companies_available(database, monkeypatch):
    from .test_companies import client, h
    source = Store(database)
    if source.backend != "postgresql":
        source.db.close()
        pytest.skip("SQLite uses one store lock")
    set_store(source)
    a, b = get_companies(), Companies(Store(database))
    actor_a = a.signup("scope-a@example.invalid", "First", "fixture-only-river-birch")
    actor_b = b.signup("scope-b@example.invalid", "Second", "fixture-only-loon-flock")
    first = a.create(actor_a.user, base())
    other = a.create(actor_b.user, base())
    monkeypatch.setenv("SCP_REQUIRE_SIGNIN", "1")

    def changed(name):
        doc = base()
        doc["settings"]["company_name"] = name
        return doc

    def same_scope():
        return a.save(actor_a.user, first.id, changed("Contended edit"), 1)

    def other_scope():
        route = f"/api/companies/{other.id}"
        read = client.get(route, headers=h(actor_b.token))
        assert read.status_code == 200 and read.json()["meta"]["revision"] == 1
        saved = client.put(route, headers=h(actor_b.token), json={
            "dataset": changed("Independent edit"), "base_revision": 1,
        })
        assert saved.status_code == 200, saved.text
        return saved.json()

    with ThreadPoolExecutor(8) as workers:
        with a.lock.scoped("company", first.id):
            assert not b.lock.acquire(blocking=False)     # membership or other global work still excludes a live save
            same = [workers.submit(same_scope) for _ in range(6)]
            from_other_store = workers.submit(b.save, actor_a.user, first.id, changed("Other server's edit"), 1)
            result = workers.submit(other_scope).result(timeout=10)
            assert result["saved"] and result["meta"]["revision"] == 2
            winner = a.save(actor_a.user, first.id, changed("First edit"), 1)
            assert winner.saved and winner.meta.revision == 2
        for waiting in [*same, from_other_store]:
            with pytest.raises(CompanyError) as stale:
                waiting.result(timeout=10)
            assert stale.value.status == 409
    assert a.open(actor_a.user, first.id).dataset["settings"]["company_name"] == "First edit"
    assert b.open(actor_b.user, other.id).dataset["settings"]["company_name"] == "Independent edit"
    for cid in (first.id, other.id):
        rows = b.db.execute("SELECT revision FROM company_revisions WHERE company_id = ? ORDER BY revision", (cid,))
        assert [row[0] for row in rows] == [1, 2]
    a.db.close()
    b.db.close()


def test_postgres_reopens_a_dropped_idle_scoped_connection(database):
    store = Store(database)
    if store.backend != "postgresql":
        store.db.close()
        pytest.skip("SQLite has no connection pool")
    import psycopg
    with store.lock.scoped("company", "company-pool-fixture"):
        failed = store.db.connection.info.backend_pid
    with psycopg.connect(database, autocommit=True) as observer:
        observer.execute("SELECT pg_terminate_backend(%s)", (failed,))
    with store.lock.scoped("company", "company-pool-fixture"):
        assert store.db.connection.info.backend_pid != failed
        assert store.db.execute("SELECT 1").fetchone()[0] == 1
    store.db.close()


def test_one_process_leads_the_clock(database):
    """Scheduled imports and reminders run in one process: the first to ask keeps it, the next takes over after."""
    a, b = Store(database), Store(database)
    assert a.lock.lead("clock") is True
    assert b.lock.lead("clock") is False
    assert a.lock.lead("clock") is True
    if a.backend == "postgresql":
        a.db.close()
    else:
        a.lock.__del__()
        a.lock._leads.clear()
    assert b.lock.lead("clock") is True


def test_a_dropped_connection_is_made_again(database):
    """A database that closes idle connections (a sleeping hosted server, a restart) costs no request."""
    s = Store(database)
    if s.backend != "postgresql":
        pytest.skip("SQLite opens a file: nothing to drop")
    import psycopg
    pid = s.db.connection.info.backend_pid
    with psycopg.connect(database, autocommit=True) as other:
        other.execute("SELECT pg_terminate_backend(%s)", (pid,))
    assert s.list() == []
    assert s.db.connection.info.backend_pid != pid


def test_sign_in_failures_count_across_processes(database):
    """Ten wrong passwords for an address are ten whichever process answered them."""
    uid, _, _ = company(database)
    a, b = Companies(Store(database)), Companies(Store(database))
    for i in range(10):
        with pytest.raises(CompanyError) as e:
            (a if i % 2 else b).signin("owner@acme.example", "wrong password")
        assert e.value.status == 401
    with pytest.raises(CompanyError) as e:
        a.signin("owner@acme.example", "correct horse battery")
    assert e.value.status == 429
