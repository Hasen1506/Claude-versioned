"""One-click fixes from the exception inbox: the suggested action is tried on a copy of the company, planned again,
and answered with the money at risk before and after and the edits that did it (scp/tower/fix.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.tower import run_tower, try_inbox_fix
from scp.tower.fix import FixError, apply_edits

from .factory import load_example


def _inbox(ds):
    r = run_tower(ds, record=False)
    by = {w.id: w for w in r.worklist}
    return [by[i] for i in r.inbox]


@pytest.fixture
def slow_stamping():
    """Kitchenware with the stamping supplier at 30 days and a dearer second one at 2 days."""
    ds = load_example("kitchenware_network")
    s = next(x for x in ds.purchasing_sources if x.id == "PIR-STAMP")
    s.lead_time_days = 30
    ds.purchasing_sources.append(s.model_copy(update={"id": "PIR-STAMP-FAST", "supplier": "SUP-COPPER", "price": 130.0,
                                                      "lead_time_days": 2.0}))
    return ds


def test_switching_to_the_quicker_supplier_clears_the_item_and_its_money(slow_stamping):
    w = next(x for x in _inbox(slow_stamping) if x.action and x.action.kind == "switch_supplier")
    assert w.action.one_click and not w.action.why_not
    f = try_inbox_fix(slow_stamping, w.key)
    assert [(e.collection, e.id, e.field, e.value) for e in f.edits] == [("purchasing_sources", "PIR-STAMP-FAST",
                                                                          "fixed", True)]
    assert f.before_item == pytest.approx(w.money_at_risk) and f.after_item is None        # gone
    assert f.after_total < f.before_total - w.money_at_risk + 0.01
    assert f.plan_ok and f.costs == pytest.approx(w.action.costs)
    # nothing was changed: the company still buys from the slow supplier
    assert not next(s for s in slow_stamping.purchasing_sources if s.id == "PIR-STAMP-FAST").fixed


def test_overtime_covers_a_day_over_capacity_within_what_is_left_of_the_day():
    ds = load_example("kitchenware_network")
    w = next(x for x in _inbox(ds) if x.code == "CAPACITY_DAY_OVERLOAD" and x.action.one_click)
    f = try_inbox_fix(ds, w.key)
    (e,) = f.edits
    r = ds.resource_by_id[w.resource]
    assert (e.collection, e.id, e.field, e.before) == ("resources", r.id, "overtime_hours_per_day",
                                                       r.overtime_hours_per_day)
    assert r.overtime_hours_per_day < e.value <= 24 - r.shifts_per_day * r.hours_per_shift
    assert f.after_item is None or f.after_item < f.before_item


def test_overtime_on_an_overloaded_line_says_when_the_day_has_no_more_room():
    ds = load_example("chennai_port_pumps")
    w = next(x for x in _inbox(ds) if x.code == "CAPACITY_OVERLOAD" and x.action.one_click)
    f = try_inbox_fix(ds, w.key)
    (e,) = f.edits
    assert "all that is left of its day" in e.note
    assert f.after_item is not None and f.after_item < f.before_item                     # less, not gone


def test_an_expedite_pulls_in_the_firm_receipt_and_says_when_it_still_cannot_make_it():
    ds = load_example("kitchenware_network")
    w = next(x for x in _inbox(ds) if x.code == "DEMAND_AT_RISK" and x.action.one_click)
    f = try_inbox_fix(ds, w.key)
    assert f.edits and all(e.collection == "receipts" for e in f.edits)
    rc = next(r for r in ds.receipts if r.id == f.edits[0].id)
    assert f.edits[0].field == "due_date" and f.edits[0].value < rc.expected_date.isoformat()
    if f.after_item is not None and f.after_item >= f.before_item:
        assert "stays late" in f.note


def test_what_cannot_be_done_in_one_click_says_why():
    ds = load_example("kitchenware_network")
    items = _inbox(ds)
    planned_only = next(x for x in items if x.action and x.action.kind == "expedite" and not x.action.one_click)
    assert "planned orders" in planned_only.action.why_not
    assert all(not x.action.one_click for x in items if x.action and x.action.kind in ("chase", "pay", "review"))
    with pytest.raises(FixError) as e:
        try_inbox_fix(ds, planned_only.key)
    assert e.value.status == 422
    with pytest.raises(FixError) as e:
        try_inbox_fix(ds, "NOPE||||")
    assert e.value.status == 404


def test_the_edits_are_kept_as_they_are_answered(slow_stamping):
    """What the browser keeps is exactly the edits: applied, the plan is the one the answer was worked out on."""
    w = next(x for x in _inbox(slow_stamping) if x.action and x.action.kind == "switch_supplier")
    f = try_inbox_fix(slow_stamping, w.key)
    kept = apply_edits(slow_stamping, f.edits)
    after = {x.key for x in _inbox(kept)}
    assert w.key not in after
    assert run_tower(kept, record=False).money_at_risk == pytest.approx(f.after_total, abs=0.05)


def test_the_api_tries_a_fix_and_records_nothing(slow_stamping):
    c = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-fix-1"})
    doc = slow_stamping.model_dump(mode="json")
    body = c.post("/api/tower", json=doc).json()
    w = next(x for x in body["worklist"] if x["action"] and x["action"]["kind"] == "switch_supplier")
    r = c.post("/api/tower/fix", json={"dataset": doc, "key": w["key"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["after_item"] is None and out["after_total"] < out["before_total"]
    assert out["before_total"] == pytest.approx(body["money_at_risk"], abs=0.05)
    again = c.post("/api/tower", json=doc).json()
    assert again["money_at_risk"] == pytest.approx(body["money_at_risk"], abs=0.05)
    bad = c.post("/api/tower/fix", json={"dataset": doc, "key": "NOPE||||"})
    assert bad.status_code == 404
