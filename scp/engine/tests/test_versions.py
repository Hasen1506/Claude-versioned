"""P8 versions & scenarios: base versions are immutable and stay byte-identical whatever happens to the
scenarios branched from them; scenarios can be edited, discarded, compared and promoted."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from scp.versions import Store, VersionError, canonical, compare, diff, sha

from .factory import ds, lp, load_example
from .test_backup_postgres import pg_databases as pg_databases


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "v.sqlite")


def raw(store: Store, vid: str) -> tuple[bytes, str]:
    r = store.db.execute("SELECT CAST(dataset AS BLOB) AS b, sha256 FROM versions WHERE id = ?", (vid,)).fetchone()
    return r["b"], r["sha256"]


def test_base_round_trips_byte_for_byte(store):
    ex = load_example("kitchenware_network")
    m = store.save_base(ex, "Oct cycle")
    text = store.text(m.id)
    assert text == canonical(ex) and m.sha256 == sha(text) and m.size == len(text.encode())
    assert canonical(store.dataset(m.id)) == text                     # load → store is lossless
    assert m.kind == "base" and m.status == "active" and m.company.startswith("Kaveri")


def test_base_is_byte_identical_after_branch_edit_and_discard(store):
    ex = load_example("kitchenware_network")
    base = store.save_base(ex, "Oct cycle")
    before = raw(store, base.id)
    sc = store.branch(base.id, "Diwali push")
    d = store.dataset(sc.id).model_dump(mode="json")
    lp(d, "PLT-PUNE", "RM-HEATER")["on_hand"] = 1
    d["demand"] = d["demand"][:-3]
    edited = store.update(sc.id, ds(d), expected_sha256=sc.sha256)
    assert edited.sha256 != base.sha256
    store.discard(sc.id, expected_sha256=edited.sha256)
    assert raw(store, base.id) == before
    assert store.meta(sc.id).status == "discarded"
    with pytest.raises(VersionError):
        store.update(sc.id, ex)                                        # a discarded scenario is closed


def test_base_cannot_be_changed(store):
    base = store.save_base(ds(_small()), "b")
    with pytest.raises(VersionError) as e:
        store.update(base.id, ds(_small(on_hand=99)))
    assert e.value.status == 409
    with pytest.raises(VersionError):
        store.discard(base.id)
    with pytest.raises(sqlite3.IntegrityError):                        # enforced by the database, not only the API
        store.db.execute("UPDATE versions SET dataset = '{}' WHERE id = ?", (base.id,))


def test_promote_writes_a_new_base_and_supersedes_the_old_one(store):
    base = store.save_base(ds(_small()), "Jan")
    before = raw(store, base.id)
    sc = store.branch(base.id, "More stock")
    sub = store.branch(sc.id, "More stock, variant")                   # a scenario of a scenario
    edited = store.update(sub.id, ds(_small(on_hand=77)), expected_sha256=sub.sha256)
    new = store.promote(sub.id, "Jan (revised)", expected_sha256=edited.sha256)
    assert new.kind == "base" and new.parent_id == sub.id and store.text(new.id) == store.text(sub.id)
    assert store.meta(sub.id).status == "promoted" and store.meta(base.id).status == "superseded"
    assert raw(store, base.id) == before
    with pytest.raises(VersionError):
        store.promote(sub.id)
    log = [x.action for x in store.get(base.id).log]
    assert log == ["created", "branched", "superseded"]


def test_unknown_version_is_404(store):
    with pytest.raises(VersionError) as e:
        store.get("V9999")
    assert e.value.status == 404


def test_versions_persist_across_connections(tmp_path):
    p = tmp_path / "x.sqlite"
    a = Store(p)
    m = a.save_base(ds(_small()), "b")
    a.db.close()
    b = Store(p)
    assert [v.id for v in b.list()] == [m.id] and b.text(m.id) == canonical(ds(_small()))


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_only_one_sibling_can_supersede_the_reviewed_base(backend, tmp_path, request, monkeypatch):
    path = tmp_path / "race.sqlite" if backend == "sqlite" else request.getfixturevalue("pg_databases")()
    first, second = Store(path), Store(path)
    try:
        data = ds(_small())
        base = first.save_base(data, "Base")
        left, right = [first.branch(base.id, name) for name in ("Left", "Right")]
        changed = first.update(left.id, ds(_small(on_hand=60)), expected_sha256=left.sha256)
        with pytest.raises(VersionError) as no_header:
            second.update(left.id, data)
        assert no_header.value.status == 428
        for operation in (lambda: second.update(left.id, data, expected_sha256=left.sha256),
                          lambda: second.discard(left.id, expected_sha256=left.sha256),
                          lambda: second.promote(left.id, expected_sha256=left.sha256)):
            with pytest.raises(VersionError) as stale:
                operation()
            assert stale.value.status == 412
        assert first.get(left.id).meta.sha256 == changed.sha256

        def fail_log(*args):
            raise OSError("audit storage unavailable")

        with monkeypatch.context() as altered:
            altered.setattr(first, "_log", fail_log)
            with pytest.raises(OSError, match="audit storage unavailable"):
                first.promote(left.id, expected_sha256=changed.sha256)
        assert [row.status for row in first.list()] == ["active", "active", "active"]

        gate = Barrier(2, timeout=10)

        def promote(item):
            store, scenario = item
            gate.wait()
            try:
                return store.promote(scenario.id, expected_sha256=scenario.sha256)
            except VersionError as error:
                assert error.status == 409 and "base was superseded" in str(error)
                return None

        with ThreadPoolExecutor(2) as workers:
            outcomes = list(workers.map(promote, [(first, changed), (second, right)]))
        winner, = [version for version in outcomes if version is not None]
        assert [version.id for version in first.list() if version.kind == "base" and version.status == "active"] == [winner.id]
        assert first.text(base.id) == canonical(data)
        assert [x.detail for x in first.get(base.id).log if x.action == "superseded"] == [f"by {winner.id}"]
        assert sum(row.status == "active" for row in first.list() if row.kind == "scenario") == 1
    finally:
        first.db.close()
        second.db.close()


# ---- diff & compare ------------------------------------------------------------------------------
def _small(on_hand: float = 10) -> dict:
    from .factory import base, demand
    d = base()
    lp(d, "P", "A")["on_hand"] = on_hand
    d["demand"] = [demand("P", "A", "2026-01-14", 20, id="F1"), demand("P", "A", "2026-01-21", 20, id="F2")]
    return d


def test_diff_by_identity_and_field():
    a = _small()
    b = _small(on_hand=25)
    b["demand"] = [b["demand"][1]]                                    # F1 removed
    b["receipts"] = [{"id": "PO-1", "kind": "purchase", "location": "P", "product": "B", "qty": 5, "due_date": "2026-01-08"}]
    b["settings"]["horizon_days"] = 35
    r = diff(ds(a), ds(b))
    by = {c.collection: c for c in r.collections}
    assert (by["demand"].removed, by["receipts"].added, by["location_products"].changed) == (1, 1, 1)
    f = by["location_products"].items[0]
    assert f.key == "P | A" and [(x.path, x.a, x.b) for x in f.fields] == [("on_hand", 10.0, 25.0)]
    assert [(x.path, x.a, x.b) for x in by["settings"].items[0].fields] == [("horizon_days", 28, 35)]
    assert r.changes == 4 and not r.identical


def test_reordering_is_not_a_change():
    a = _small()
    b = _small()
    b["demand"].reverse()
    b["location_products"].reverse()
    assert diff(ds(a), ds(b)).identical


def test_compare_runs_both_plans():
    a = _small()
    b = _small()
    b["demand"][0]["qty"] = 200
    c = compare(ds(a), ds(b))
    assert c.plan_a.ok and c.plan_b.ok and c.plan_b.total_cost > c.plan_a.total_cost
    assert c.diff.changes == 1
