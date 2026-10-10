"""Backups rehearsed end to end (ENTERPRISE_PLAN 1.6): a server's database is copied while it runs, put back into an
empty database, and every company opens there as it was, at its latest revision and at every one kept before
(across a whole copy and the deltas after it), with its members, history and versions; the owner signs in with
the same password. On SQLite always; from and into PostgreSQL when ``SCP_TEST_POSTGRES`` names a server."""
from __future__ import annotations

import os
import secrets

import pytest

from scp import admin
from scp.backup import backup, backup_postgres, check, restore
from scp.companies.store import FULL_EVERY, Companies
from scp.model import Dataset
from scp.versions.store import Store

from .factory import base

PG = os.environ.get("SCP_TEST_POSTGRES", "").strip()
PASSWORD = "correct horse battery"


@pytest.fixture
def pg_databases():
    """Fresh PostgreSQL databases on the test server, dropped afterwards."""
    if not PG:
        pytest.skip("SCP_TEST_POSTGRES is not set")
    import psycopg
    made: list[str] = []

    def make() -> str:
        name = "scp_bk_" + secrets.token_hex(6)
        with psycopg.connect(PG, autocommit=True) as admin_conn:
            admin_conn.execute(f"CREATE DATABASE {name}")
        made.append(name)
        return PG.rsplit("/", 1)[0] + "/" + name
    yield make
    with psycopg.connect(PG, autocommit=True) as admin_conn:
        for name in made:
            admin_conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def fill(url: str) -> dict:
    """Two companies, one saved past a whole copy; a planner; versions. What each should hold afterwards."""
    store = Store(url)
    c = Companies(store)
    owner = c.signup("owner@acme.example", "Owner", PASSWORD)
    c.signup("planner@acme.example", "Planner", PASSWORD)
    doc = base()
    doc["settings"]["company_name"] = "Kept Ltd"
    meta = c.create(owner.user, doc)
    c.set_member(owner.user, meta.id, "planner@acme.example", "planner")
    rev, at = meta.revision, {meta.revision: c.revision(owner.user, meta.id, meta.revision)}
    for k in range(FULL_EVERY + 5):                       # deltas, a whole copy, deltas after it
        d = c.open(owner.user, meta.id).dataset
        d["location_products"][0]["on_hand"] = 100 + k
        rev = c.save(owner.user, meta.id, d, rev).meta.revision
        at[rev] = d
    other = base()
    other["settings"]["company_name"] = "Second Ltd"
    second = c.create(owner.user, other)
    v = store.save_base(Dataset.model_validate(doc), "Plan of record", scope=meta.id)
    store.branch(v.id, "What if", scope=meta.id)
    out = {"cid": meta.id, "at": at, "second": second.id, "second_doc": c.open(owner.user, second.id).dataset,
           "history": len(c.history(owner.user, meta.id)), "versions": [x.name for x in store.list(meta.id)]}
    store.db.close()
    return out


def opens_as_it_was(url: str, want: dict) -> None:
    c = Companies(Store(url))
    owner = c.signin("owner@acme.example", PASSWORD).user
    cid = want["cid"]
    latest = max(want["at"])
    doc = c.open(owner, cid)
    assert doc.meta.revision == latest and doc.dataset == want["at"][latest]
    for rev, d in want["at"].items():                     # every revision kept, whole copy or delta
        assert c.revision(owner, cid, rev) == d, rev
    assert c.open(owner, want["second"]).dataset == want["second_doc"]
    assert {m.email for m in c.members(owner, cid)} == {"owner@acme.example", "planner@acme.example"}
    assert len(c.history(owner, cid)) == want["history"]
    assert [x.name for x in c.store.list(cid)] == want["versions"]
    # and it goes on from there: the next save is the next revision
    d = doc.dataset
    d["settings"]["company_name"] = "Kept Ltd, restored"
    assert c.save(owner, cid, d, latest).meta.revision == latest + 1


def test_sqlite_backup_restores_into_an_empty_file_and_every_company_opens(tmp_path):
    src = str(tmp_path / "live.sqlite")
    want = fill(src)
    store = Store(src)
    with store.lock:
        kept = backup(store.db, tmp_path / "backups")
    assert "2 accounts" in check(kept)
    target = tmp_path / "restored.sqlite"
    restore(kept, target)
    opens_as_it_was(str(target), want)


def test_postgres_backup_while_it_runs_and_restore_into_an_empty_database(pg_databases, tmp_path, monkeypatch, capsys):
    live, empty = pg_databases(), pg_databases()
    want = fill(live)
    # the server goes on saving during the copy: the snapshot is the moment the copy began, whole
    monkeypatch.setenv("DATABASE_URL", live)
    assert admin.main(["backup", str(tmp_path / "backups")]) == 0
    kept = capsys.readouterr().out.strip()
    assert kept.endswith(".sqlite") and "2 accounts" in check(kept) and "Kept Ltd (revision" in "\n".join(check(kept))
    # put back into an empty PostgreSQL database with the same command
    monkeypatch.setenv("DATABASE_URL", empty)
    assert admin.main(["restore", kept]) == 0
    opens_as_it_was(empty, want)
    # a second restore over it is refused: only into an empty database
    assert admin.main(["restore", kept]) == 1
    assert "nonempty" in capsys.readouterr().err
    # the same file restores as a SQLite file as well (moving off PostgreSQL)
    target = tmp_path / "moved.sqlite"
    restore(kept, target)
    opens_as_it_was(str(target), want)


def test_postgres_backup_holds_no_lock_the_server_waits_for(pg_databases, tmp_path):
    """The copy is a read-only snapshot on its own connection: a save while it is taken goes through."""
    import threading

    live = pg_databases()
    want = fill(live)
    store = Store(live)
    c = Companies(store)
    owner = c.signin("owner@acme.example", PASSWORD).user
    with store.lock:                                      # the server is in the middle of a save
        done = threading.Event()
        t = threading.Thread(target=lambda: (backup_postgres(live, tmp_path / "b"), done.set()))
        t.start()
        assert done.wait(60), "the backup waited for the server's lock"
    t.join()
    latest = max(want["at"])
    d = c.open(owner, want["cid"]).dataset
    assert c.save(owner, want["cid"], d | {"settings": {**d["settings"], "company_name": "After"}}, latest).saved
