"""Phase B: named shifts, breaks and capacity that changes over time. One definition of a resource's
working time feeds MRP's capacity check, the S&OP capacity rows, make-order lead times and the finite
scheduler, so they agree about a shutdown week or a second shift."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from scp.model import Calendar, Resource, Shift
from scp.plan import run_mrp
from scp.plan.leadtime import schedule_make
from scp.schedule import run_schedule
from scp.sop import run_sop
from scp.time import WorkCalendar
from scp.time.capacity import day_capacity, hours_between, max_units

from .factory import START, base, demand, ds

MON = date(2026, 1, 5)
WEEK = WorkCalendar(Calendar(id="W", workdays=[0, 1, 2, 3, 4]))


def res(**kw) -> Resource:
    return Resource.model_validate({"id": "R", "location": "P", "efficiency": 1.0, **kw})


# ---- the model ------------------------------------------------------------------------------------
def test_shift_windows_split_around_the_break():
    s = Shift(name="Early", start="06:00", end="14:00", break_minutes=30)
    assert s.net_hours == pytest.approx(7.5)
    assert s.windows() == [(6.0, 9.75), (10.25, 14.0)]
    s2 = Shift(start="06:00", end="14:00", break_minutes=30, break_start="12:00")
    assert s2.windows() == [(6.0, 12.0), (12.5, 14.0)]
    night = Shift(name="Night", start="22:00", end="06:00")
    assert night.length_hours == 8 and night.windows() == [(22.0, 30.0)]


@pytest.mark.parametrize("bad", [
    {"start": "06:00", "end": "07:00", "break_minutes": 60},
    {"start": "06:00", "end": "14:00", "break_minutes": 60, "break_start": "13:30"},
    {"start": "6:00", "end": "14:00"},
])
def test_impossible_shifts_are_refused(bad):
    with pytest.raises(ValidationError):
        Shift.model_validate(bad)


def test_more_than_a_day_of_shifts_is_refused():
    with pytest.raises(ValidationError):
        res(shifts=[{"start": "00:00", "end": "12:00"}, {"start": "12:00", "end": "23:00"}], overtime_hours_per_day=2)


def test_day_capacity_follows_shifts_weekdays_and_changes():
    r = res(units=2, shifts=[{"name": "Early", "start": "06:00", "end": "14:00", "break_minutes": 30,
                              "weekdays": [0, 1, 2, 3, 4]},
                             {"name": "Sat", "start": "08:00", "end": "12:00", "weekdays": [5]}],
            capacity_changes=[
                {"valid_from": "2026-01-12", "valid_to": "2026-01-16", "units": 0, "note": "maintenance"},
                {"valid_from": "2026-01-19", "shifts_per_day": 2},
                {"valid_from": "2026-01-21", "valid_to": "2026-01-21", "efficiency": 0.5},
            ])
    six = WorkCalendar(Calendar(id="6", workdays=[0, 1, 2, 3, 4, 5]))
    assert day_capacity(r, six, MON).productive_hours == pytest.approx(15.0)            # 7.5 h × 2 units
    assert day_capacity(r, six, MON + timedelta(days=5)).productive_hours == pytest.approx(8.0)  # Sat 4 h × 2
    assert day_capacity(r, six, MON + timedelta(days=6)).productive_hours == 0.0          # Sunday: not a workday
    assert day_capacity(r, six, date(2026, 1, 13)).productive_hours == 0.0               # shut down
    assert day_capacity(r, six, date(2026, 1, 19)).productive_hours == pytest.approx(32.0)  # 2 × 8 h × 2 units
    # the later matching row wins: 21 Jan runs at half efficiency with the usual shifts
    assert day_capacity(r, six, date(2026, 1, 21)).productive_hours == pytest.approx(7.5)
    assert max_units(r) == 2
    assert hours_between(r, six, MON, MON + timedelta(days=7)) == pytest.approx(5 * 15 + 8)


def test_no_shifts_keeps_the_old_arithmetic():
    r = res(units=3, shifts_per_day=2, hours_per_shift=8, efficiency=0.8)
    assert hours_between(r, WEEK, MON, MON + timedelta(days=7)) == pytest.approx(5 * 16 * 0.8 * 3)
    assert r.hours_per_workday_per_unit == pytest.approx(12.8)


# ---- the plans agree about a shutdown week -----------------------------------------------------------
def _shutdown() -> dict:
    d = base(horizon=28, workdays=[0, 1, 2, 3, 4])
    d["production_sources"][0].pop("fixed_lead_time_workdays")
    d["resources"][0]["capacity_changes"] = [{"valid_from": "2026-01-12", "valid_to": "2026-01-16", "units": 0,
                                              "note": "maintenance"}]
    d["demand"] = [demand("P", "A", "2026-01-23", 40)]
    return d


def test_mrp_capacity_and_sop_capacity_drop_in_the_shutdown_week():
    plan = run_mrp(ds(_shutdown()))
    rp = next(r for r in plan.resources if r.resource == "M1")
    caps = [b.capacity_hours for b in rp.buckets]
    assert caps[0] == pytest.approx(40) and caps[1] == 0.0 and caps[2] == pytest.approx(40)
    sop = run_sop(ds(_shutdown()))
    row = next(r for r in sop.resources if r.resource == "M1")
    assert row.capacity[1] == 0.0 and row.capacity[0] > 0


def test_make_lead_time_steps_over_the_shutdown_week():
    d = ds(_shutdown())
    ps = d.production_source_by_id["PV-A"]
    # 2 h setup + 0.5 h × 40 = 22 h: three 8-hour days
    fwd = schedule_make(d, ps, 40, start=date(2026, 1, 8))        # Thu, Fri … then the shutdown, then Mon
    assert fwd.due_date == date(2026, 1, 20)
    bwd = schedule_make(d, ps, 40, available=date(2026, 1, 20))
    assert bwd.start_date == date(2026, 1, 8)
    plain = base(workdays=[0, 1, 2, 3, 4])
    plain["production_sources"][0].pop("fixed_lead_time_workdays")
    p = ds(plain)
    assert schedule_make(p, p.production_source_by_id["PV-A"], 40, start=date(2026, 1, 8)).due_date == date(2026, 1, 13)


def test_scheduler_never_works_in_a_break_or_a_shutdown():
    d = _shutdown()
    d["resources"][0]["shifts"] = [{"name": "Day", "start": "06:00", "end": "14:30", "break_minutes": 30,
                                    "break_start": "10:00"}]
    d["scheduling"] = {"horizon_days": 28, "improve": False}
    d["demand"] = [demand("P", "A", "2026-01-09", 10), demand("P", "A", "2026-01-23", 30)]
    out = run_schedule(ds(d))
    assert out.ok and not out.violations
    shut = ((date(2026, 1, 12) - MON).days * 24.0, (date(2026, 1, 17) - MON).days * 24.0)
    for op in out.ops:
        assert op.end <= shut[0] + 1e-6 or op.setup_start >= shut[1] - 1e-6, op
        day = int(op.setup_start // 24)
        brk = (day * 24 + 10.0, day * 24 + 10.5)
        # the run either finishes before the break, starts after it, or pauses across it
        if op.setup_start < brk[0] < op.end:
            assert op.end - op.setup_start >= 0.5 + op.setup_hours + op.run_hours - 1e-6
    res_row = next(r for r in out.resources if r.id == "M1")
    assert [10.0, 10.5] not in res_row.windows and [6.0, 10.0] in res_row.windows


def test_a_second_unit_from_a_date_runs_orders_side_by_side():
    d = base(horizon=21, workdays=[0, 1, 2, 3, 4])
    d["production_sources"][0].pop("fixed_lead_time_workdays")
    d["production_sources"][0]["operations"][0].update(setup_hours=0, run_hours_per_unit=0.8, parallel_units=1)
    d["resources"][0]["capacity_changes"] = [{"valid_from": "2026-01-12", "units": 2}]
    d["scheduling"] = {"horizon_days": 21, "improve": False}
    d["receipts"] = [{"id": f"FIRM-{i}", "kind": "production", "location": "P", "product": "A", "qty": 10,
                      "source": "PV-A", "start_date": "2026-01-12", "due_date": "2026-01-13"} for i in (1, 2)]
    d["receipts"].append({"id": "FIRM-0", "kind": "production", "location": "P", "product": "A", "qty": 10,
                          "source": "PV-A", "start_date": START, "due_date": "2026-01-06"})
    d["receipts"].append({"id": "FIRM-00", "kind": "production", "location": "P", "product": "A", "qty": 10,
                          "source": "PV-A", "start_date": START, "due_date": "2026-01-06"})
    out = run_schedule(ds(d))
    assert out.ok and not out.violations
    by = {o.order: o for o in out.ops}
    # in week one there is one unit: the two orders run one after the other
    assert by["FIRM-0"].unit == by["FIRM-00"].unit == 0
    # from 12 January there are two: the orders run at the same time on different units
    assert {by["FIRM-1"].unit, by["FIRM-2"].unit} == {0, 1}
    assert by["FIRM-1"].setup_start == by["FIRM-2"].setup_start
