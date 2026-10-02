"""A resource's holidays/weekends affect production dates without requiring named shifts."""
from datetime import date

import pytest

from scp.plan import run_mrp
from scp.plan.leadtime import production_workdays, schedule_make
from scp.schedule import run_schedule

from .factory import base, demand, ds, lp


def calendar_company(named: bool, weekends: bool = False) -> dict:
    d = base()
    d["calendars"].append({"id": "M-CAL", "workdays": list(range(5 if weekends else 7)),
                           "holidays": [] if weekends else ["2026-01-05"]})
    d["resources"][0]["calendar"] = "M-CAL"
    if named:
        d["resources"][0]["shifts"] = [{"start": "06:00", "end": "14:00"}]
    ps = d["production_sources"][0]
    ps.pop("fixed_lead_time_workdays")
    ps["operations"][0].update(setup_hours=0, run_hours_per_unit=0.5)
    for product in ("B", "C"):
        lp(d, "P", product)["on_hand"] = 1000
    lp(d, "P", "A")["on_hand"] = 0
    return d


@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize("weekends", [False, True])
@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_make_dates_respect_the_resource_calendar(named, weekends, direction):
    data = ds(calendar_company(named, weekends))
    ps = data.production_source_by_id["PV-A"]
    if direction == "forward":
        start = date(2026, 1, 10) if weekends else date(2026, 1, 5)
        expected = date(2026, 1, 13) if weekends else date(2026, 1, 7)
        result = schedule_make(data, ps, 16, start=start)
        # Eight productive hours: Monday's holiday or the weekend supplies none;
        # the next working day supplies eight, with availability the following day.
        assert result.available_date == expected
    else:
        available = date(2026, 1, 12) if weekends else date(2026, 1, 6)
        expected = date(2026, 1, 9) if weekends else date(2026, 1, 4)
        result = schedule_make(data, ps, 16, available=available)
        assert result.start_date == expected


@pytest.mark.parametrize("named", [False, True])
def test_mrp_and_shopfloor_agree_when_the_first_day_is_a_resource_holiday(named):
    d = calendar_company(named)
    d["demand"] = [demand("P", "A", "2026-01-06", 16)]
    data = ds(d)
    plan = run_mrp(data)
    order = next(o for o in plan.orders if o.kind == "make")
    assert order.qty == 16
    assert order.available_date == date(2026, 1, 7)
    machine = next(r for r in plan.resources if r.resource == "M1")
    assert machine.daily_load == {date(2026, 1, 6): pytest.approx(8)}
    scheduled = run_schedule(data)
    op = next(o for o in scheduled.ops if o.product == "A")
    assert op.setup_start == pytest.approx(30)  # Tuesday at 06:00, from Monday's origin.
    assert op.end == pytest.approx(38)          # Tuesday at 14:00.
    assert not op.late


@pytest.mark.parametrize("holiday,setup,send_qty,expected", [
    (True, 0, 8, date(2026, 1, 7)),  # Four hours cannot be made on Monday's holiday.
    (False, 8, 4, date(2026, 1, 7)),  # Setup eight + first four units two = ten hours.
])
def test_send_ahead_waits_for_the_first_batch_calendar_and_full_setup(holiday, setup, send_qty, expected):
    d = calendar_company(False)
    if not holiday:
        d["calendars"][-1]["holidays"] = []
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1, "hours_per_shift": 8})
    ops = d["production_sources"][0]["operations"]
    ops[0].update(setup_hours=setup, send_ahead_qty=send_qty)
    ops.append({"seq": 20, "resource": "M2", "run_hours_per_unit": 0.5})
    data = ds(d)
    result = schedule_make(data, data.production_sources[0], 16, start=date(2026, 1, 5))
    assert result.ops[1].start == expected


def test_send_ahead_nominal_duration_keeps_the_whole_first_setup():
    d = calendar_company(False)
    d["calendars"][-1]["holidays"] = []
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1, "hours_per_shift": 8})
    ops = d["production_sources"][0]["operations"]
    ops[0].update(setup_hours=8, send_ahead_qty=4)
    ops.append({"seq": 20, "resource": "M2", "run_hours_per_unit": 0.5})
    data = ds(d)
    assert production_workdays(data, data.production_sources[0], 16) == 3


def test_send_ahead_final_batch_waits_for_the_next_machine_to_reopen():
    d = calendar_company(False)
    d["calendars"][-1]["holidays"] = []
    d["calendars"].append({"id": "M2-CAL", "workdays": list(range(7)), "holidays": ["2026-01-07"]})
    d["resources"].append({"id": "M2", "location": "P", "calendar": "M2-CAL",
                           "efficiency": 1, "hours_per_shift": 8})
    ops = d["production_sources"][0]["operations"]
    ops[0]["send_ahead_qty"] = 8
    ops.append({"seq": 20, "resource": "M2", "run_hours_per_unit": 0.25})
    data = ds(d)
    result = schedule_make(data, data.production_sources[0], 32, start=date(2026, 1, 5))
    assert result.ops[0].end == date(2026, 1, 7)
    assert result.ops[1].start == date(2026, 1, 6)
    # The final eight units need two hours on M2 after the first machine finishes;
    # Wednesday is unavailable, so those hours fall on Thursday.
    assert result.ops[1].end == result.available_date == date(2026, 1, 9)
