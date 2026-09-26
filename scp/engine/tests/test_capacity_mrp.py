"""Phase C: capacity-constrained MRP.

With ``capacity_constrained`` on, a make order that would push a finite machine (or labour pool) over its daily
capacity runs on one of the step's alternative machines, else starts earlier (never before today), else finishes
later (reported, with the demand it makes late). Released orders are loaded first. Off, the plan is unchanged.
"""
from __future__ import annotations

from datetime import date

import pytest

from scp.plan import run_mrp
from scp.time.capacity import day_capacity
from scp.plan.leadtime import resource_calendar

from .factory import base, demand, ds, load_example, lp


def _two_products(day: str = "2026-01-12") -> dict:
    """A and D both need a full 8 h day on M1 (8 h/day, 100 %) for demand on the same day."""
    d = base(horizon=28)
    d["products"].append({"id": "D", "type": "FG"})
    ps = d["production_sources"][0]
    ps.pop("fixed_lead_time_workdays")
    ps["operations"][0]["setup_hours"] = 0
    d["production_sources"].append({**ps, "id": "PV-D", "product": "D",
                                    "operations": [{**ps["operations"][0]}]})
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "D")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 1000
    lp(d, "P", "C")["on_hand"] = 1000
    d["demand"] = [demand("P", "A", day, 16), demand("P", "D", day, 16)]
    return d


def _constrained(d: dict) -> dict:
    d["settings"]["capacity_constrained"] = True
    return d


def _within_capacity(p, dset) -> None:
    for rp in p.resources:
        r = dset.resource_by_id[rp.resource]
        if not r.finite:
            continue
        cal = resource_calendar(dset, r.id)
        for d, h in rp.daily_load.items():
            if d > dset.settings.planning_start:
                assert h <= day_capacity(r, cal, d, dset.scheduling.day_start_hour).productive_hours + 1e-6, (r.id, d)


def test_off_the_plan_overloads_a_day():
    p = run_mrp(ds(_two_products()))
    m1 = next(r for r in p.resources if r.resource == "M1")
    assert m1.daily_load == {date(2026, 1, 11): pytest.approx(16.0)}
    assert all(o.capacity_shift_days == 0 for o in p.orders)


def test_an_order_that_does_not_fit_starts_earlier():
    dset = ds(_constrained(_two_products()))
    p = run_mrp(dset)
    made = {o.product: o for o in p.orders if o.kind == "make"}
    assert made["A"].start_date == date(2026, 1, 11) and made["A"].capacity_shift_days == 0
    assert made["D"].start_date == date(2026, 1, 10) and made["D"].capacity_shift_days == -1
    m1 = next(r for r in p.resources if r.resource == "M1")
    assert m1.daily_load == {date(2026, 1, 10): pytest.approx(8.0), date(2026, 1, 11): pytest.approx(8.0)}
    assert [e.order_id for e in p.exceptions if e.code == "CAPACITY_EARLIER"] == [made["D"].id]
    assert p.kpis.on_time_fill_rate == 1.0
    _within_capacity(p, dset)


def test_an_alternative_machine_comes_before_moving():
    d = _constrained(_two_products())
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1.0, "hours_per_shift": 8})
    for ps in d["production_sources"]:
        ps["operations"][0]["alternatives"] = ["M2"]
    p = run_mrp(ds(d))
    made = {o.product: o for o in p.orders if o.kind == "make"}
    assert made["D"].capacity_shift_days == 0 and made["D"].step_resources == {10: "M2"}
    assert made["A"].step_resources == {}
    m2 = next(r for r in p.resources if r.resource == "M2")
    assert m2.daily_load == {date(2026, 1, 11): pytest.approx(8.0)}
    alt = [e for e in p.exceptions if e.code == "ALTERNATIVE_MACHINE"]
    assert [(e.order_id, e.resource) for e in alt] == [(made["D"].id, "M2")]
    assert "instead of M1" in alt[0].message


def test_an_order_that_cannot_start_earlier_finishes_later_and_is_reported():
    """Needed tomorrow: one order takes today, the other can only go the day after and makes its demand late."""
    dset = ds(_constrained(_two_products("2026-01-06")))
    p = run_mrp(dset)
    made = sorted((o for o in p.orders if o.kind == "make"), key=lambda o: o.start_date)
    assert [o.start_date for o in made] == [date(2026, 1, 5), date(2026, 1, 6)]
    late = made[1]
    assert late.capacity_shift_days == 1 and late.available_date == date(2026, 1, 7)
    e = next(e for e in p.exceptions if e.code == "CAPACITY_LATE")
    assert e.severity == "warning" and e.order_id == late.id and "1 d after it is needed" in e.message
    assert any(x.code == "DEMAND_AT_RISK" and x.product == late.product for x in p.exceptions)
    _within_capacity(p, dset)


def test_released_orders_keep_their_machine_time():
    """A released order on M1 the day A would run: the planned order moves earlier around it."""
    d = _constrained(_two_products())
    d["demand"] = [demand("P", "A", "2026-01-12", 16)]
    d["receipts"] = [{"id": "PRD-1", "kind": "production", "location": "P", "product": "D", "qty": 16,
                      "due_date": "2026-01-12", "start_date": "2026-01-11", "source": "PV-D"}]
    lp(d, "P", "D")["on_hand"] = 100      # the released order is not needed; it still occupies M1
    p = run_mrp(ds(d))
    a = next(o for o in p.orders if o.product == "A")
    assert a.start_date == date(2026, 1, 10) and a.capacity_shift_days == -1


def test_example_stays_within_daily_capacity_and_is_unchanged_when_off():
    ex = load_example("kitchenware_network")
    off = run_mrp(ex)
    assert all(o.capacity_shift_days == 0 and not o.step_resources for o in off.orders)
    on_ds = ex.model_copy(update={"settings": ex.settings.model_copy(update={"capacity_constrained": True})})
    on = run_mrp(on_ds)
    assert on.ok   # (parts' order count may differ: moving an order earlier moves its parts' need dates, and lots)
    moved = [o for o in on.orders if o.capacity_shift_days]
    assert moved and all(o.start_date >= ex.settings.planning_start for o in moved)
    _within_capacity(on, on_ds)
    # the same work, levelled: every machine's total load is unchanged
    for a, b in zip(off.resources, on.resources, strict=True):
        assert sum(x.load_hours for x in b.buckets) == pytest.approx(sum(x.load_hours for x in a.buckets), rel=2e-3)
    for rp in on.resources:
        assert sum(rp.daily_load.values()) == pytest.approx(sum(b.load_hours for b in rp.buckets), rel=1e-6)
        assert all(d >= ex.settings.planning_start for d in rp.daily_load)


def test_level_preview_lists_what_moves():
    from scp.plan.level import level_preview
    r = level_preview(ds(_two_products()))
    assert r.ok and not r.active
    assert [(m.product, m.shift_days, m.late_days) for m in r.moves] == [("D", -1, 0)]
    m1 = next(x for x in r.resources if x.resource == "M1")
    assert m1.peak_before == pytest.approx(2.0) and m1.peak_after == pytest.approx(1.0)
    assert (m1.overloaded_days_before, m1.overloaded_days_after) == (1, 0)
    late = level_preview(ds(_two_products("2026-01-06")))
    assert [(m.shift_days, m.late_days) for m in late.moves] == [(1, 1)] and late.late_after == late.late_before + 1


def test_a_firmed_order_keeps_its_alternative_machine():
    """Levelled onto M2, firmed, planned again: the released order still loads M2, and the shop floor starts it there."""
    from scp.actuals.firm import firm_orders
    from scp.schedule import run_schedule
    d = _constrained(_two_products())
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1.0, "hours_per_shift": 8})
    for ps in d["production_sources"]:
        ps["operations"][0]["alternatives"] = ["M2"]
    dset = ds(d)
    p = run_mrp(dset)
    moved = next(o for o in p.orders if o.step_resources)
    firmed, rep = firm_orders(dset, p, [moved.id])
    rc = next(r for r in firmed.receipts if r.id == rep.firmed[0].receipt_id)
    assert rc.step_resources == {10: "M2"}
    again = run_mrp(firmed)
    m2 = next(r for r in again.resources if r.resource == "M2")
    assert [o.order for o in m2.orders] == [rc.id]
    sch = run_schedule(firmed)
    assert {op.resource for op in sch.ops if op.order == rc.id} == {"M2"}
    assert sch.violations == []
