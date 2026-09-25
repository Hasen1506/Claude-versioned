"""P8 versions & scenarios: base versions are immutable and stay byte-identical whatever happens to the
scenarios branched from them; scenarios can be edited, discarded, compared and promoted."""
from __future__ import annotations

import sqlite3

import pytest

from scp.versions import Store, VersionError, canonical, compare, diff, sha

from .factory import ds, lp, load_example


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
    edited = store.update(sc.id, ds(d))
    assert edited.sha256 != base.sha256
    store.discard(sc.id)
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
    store.update(sub.id, ds(_small(on_hand=77)))
    new = store.promote(sub.id, "Jan (revised)")
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
