"""Phase C: the detailed schedule's dates fed back into supply planning and promising.

* Applying a schedule firms each scheduled planned order as a production order dated by the schedule (start = the day
  its first step sets up, due = the day after its last step ends), with each part reserved for the day the step that
  uses it starts; applying the same schedule again changes nothing.
* Re-planning counts a schedule-dated order where it is needed and reports the delay (``SCHEDULE_LATE``); it never adds
  an order in front of it, even when an order planned at unlimited capacity would look faster.
* Promising reads the same dates.
* A released production order occupies its machines in the capacity plan, so firming moves no load away.
"""
from __future__ import annotations

from datetime import date

import pytest

from scp.actuals.firm import firm_orders
from scp.plan import run_mrp
from scp.promise import run_promise
from scp.schedule import apply_schedule, run_schedule

from .factory import base, demand, ds, load_example, lp
from .test_schedule import _made_sub

JAN = date(2026, 1, 5)


def _late_sub() -> dict:
    d = _made_sub()
    d["demand"] = [demand("P", "A", "2026-01-08", 40, kind="sales_order", id="SO-1")]
    d["scheduling"] = {"improve": False}
    d["promising"] = {"confirm_beyond_rlt": False, "ctp": False}
    return d


def test_apply_firms_planned_orders_with_the_schedules_dates():
    d = _late_sub()
    before = run_schedule(ds(d))
    new, rep = apply_schedule(ds(d))
    assert rep.ok and len(rep.applied) == 2 and all(a.new for a in rep.applied)
    by_product = {a.product: a for a in rep.applied}
    rcs = {r.product: r for r in new.receipts}
    for so in before.orders:
        a, rc = by_product[so.product], rcs[so.product]
        first = min(op.setup_start for op in before.ops if op.order == so.id)
        assert rc.scheduled and rc.id == a.receipt and rc.kind.value == "production"
        assert rc.start_date == date.fromordinal(JAN.toordinal() + int(first // 24))
        assert rc.due_date == date.fromordinal(JAN.toordinal() + -int(-so.completion // 24))
    # A's part SUB is reserved for the day A's step starts, not the plan's earlier date
    a_rc = rcs["A"]
    a_first = min(op.setup_start for op in before.ops if op.product == "A")
    assert [(r.product, r.date) for r in a_rc.reservations] == [
        ("SUB", date.fromordinal(JAN.toordinal() + int(a_first // 24)))]
    # applying the same schedule again: nothing new, no date moves
    again, rep2 = apply_schedule(new)
    assert not any(a.new for a in rep2.applied)
    assert all(a.start_date == a.was_start and a.due_date == a.was_due for a in rep2.applied)
    assert again.receipts == new.receipts


def test_replanning_reports_a_late_scheduled_order_and_adds_none():
    d = _late_sub()
    new, _ = apply_schedule(ds(d))
    p = run_mrp(new)
    assert p.orders == []                                   # the scheduled orders cover everything
    late = [e for e in p.exceptions if e.code == "SCHEDULE_LATE"]
    assert [(e.product, e.date) for e in late] == [("A", date(2026, 1, 8))]
    assert any(e.code == "DEMAND_AT_RISK" for e in p.exceptions)


def test_scheduled_flag_stops_a_duplicate_order():
    """A firm order due after its need, where a new order (planned at unlimited capacity) could arrive in time: an
    ordinary firm order gets a new order in front of it; one dated by the schedule does not."""
    d = base(horizon=28)
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 1000
    lp(d, "P", "C")["on_hand"] = 1000
    d["demand"] = [demand("P", "A", "2026-01-12", 10)]
    d["receipts"] = [{"id": "PRD-1", "kind": "production", "location": "P", "product": "A", "qty": 10,
                      "due_date": "2026-01-20", "start_date": "2026-01-15", "source": "PV-A"}]
    plain = run_mrp(ds(d))
    assert [o.product for o in plain.orders if o.kind == "make"] == ["A"]
    d["receipts"][0]["scheduled"] = True
    fixed = run_mrp(ds(d))
    assert [o for o in fixed.orders if o.kind == "make"] == []
    assert [e.order_id for e in fixed.exceptions if e.code == "SCHEDULE_LATE"] == ["PRD-1"]


def test_promise_reads_the_schedules_dates():
    d = _late_sub()
    before = run_promise(ds(d)).orders[0]
    assert before.status == "on_time" and before.lines[0].date == date(2026, 1, 8)
    new, rep = apply_schedule(ds(d))
    after = run_promise(new).orders[0]
    a_due = next(a.due_date for a in rep.applied if a.product == "A")
    assert after.status == "late" and after.lines[0].date == a_due == date(2026, 1, 9)


def test_released_production_orders_load_their_machines():
    """Firming every order keeps each machine's total load in the capacity plan."""
    ex = load_example("kitchenware_network")
    p0 = run_mrp(ex)
    firmed, _ = firm_orders(ex, p0, within_days=400)
    p1 = run_mrp(firmed)
    assert not any(o.kind == "make" for o in p1.orders)
    for r0 in p0.resources:
        r1 = next(r for r in p1.resources if r.resource == r0.resource)
        assert sum(b.load_hours for b in r1.buckets) == pytest.approx(sum(b.load_hours for b in r0.buckets), rel=1e-6)


def test_apply_only_chosen_orders_and_the_example():
    ex = load_example("kitchenware_network")
    sch = run_schedule(ex)
    pick = [o.id for o in sch.orders if not o.firm][:2]
    new, rep = apply_schedule(ex, ids=[*pick, "NOPE"])
    assert [a.order for a in rep.applied] == pick and rep.skipped == {"NOPE": "not on the schedule"}
    assert len(new.receipts) == len(ex.receipts) + 2
    everything, rep = apply_schedule(ex)
    assert len(rep.applied) == len(sch.orders) and not rep.skipped
    re = run_schedule(everything)
    assert re.ok and re.violations == [] and len(re.orders) == len(sch.orders)
    assert all(o.firm for o in re.orders)
