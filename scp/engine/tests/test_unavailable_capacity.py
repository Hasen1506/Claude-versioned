"""Unavailable machines must neither invent production dates nor hide viable alternatives."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.plan import run_mrp
from scp.plan.leadtime import schedule_make
from scp.schedule import run_schedule

from .factory import demand, ds, lp
from .test_resource_calendar_dates import calendar_company


def closed_company(*, alternative=False, firm=False, finite=True):
    d = calendar_company(False)
    d["calendars"][-1]["holidays"] = []
    d["resources"][0].update(finite=finite, capacity_changes=[{"valid_from": "2026-01-05", "units": 0}])
    d["scheduling"] = {"improve": False}
    if alternative:
        d["resources"].append({"id": "M2", "location": "P", "efficiency": 1, "hours_per_shift": 8})
        d["production_sources"][0]["operations"][0]["alternatives"] = ["M2"]
    if firm:
        d["receipts"] = [{"id": "FIRM", "kind": "production", "location": "P", "product": "A", "qty": 16,
                           "source": "PV-A", "start_date": "2026-01-05", "due_date": "2026-01-06"}]
        lp(d, "P", "A")["on_hand"] = 1000
    else:
        d["demand"] = [demand("P", "A", "2026-01-06", 16)]
    return d


@pytest.mark.parametrize("finite", [True, False])
def test_no_working_time_never_produces_an_invented_make_order(finite):
    data = ds(closed_company(finite=finite))
    with pytest.raises(ValueError, match="working time"):
        schedule_make(data, data.production_sources[0], 16, start=date(2026, 1, 5))
    plan = run_mrp(data)
    assert not plan.orders
    assert any(e.code == "SOURCE_NO_WORKING_TIME" for e in plan.exceptions)
    assert plan.kpis.on_time_qty == 0
    assert all(not r.daily_load for r in plan.resources)


def test_an_unavailable_product_does_not_block_an_independent_purchase():
    d = closed_company()
    lp(d, "P", "C")["on_hand"] = 0
    d["demand"].append(demand("P", "C", "2026-01-06", 20))
    plan = run_mrp(ds(d))
    assert [(o.product, o.kind, o.qty) for o in plan.orders] == [("C", "buy", 20)]


def test_a_second_production_source_remains_available():
    d = closed_company()
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1, "hours_per_shift": 8})
    ps = d["production_sources"][0]
    d["production_sources"].append({**ps, "id": "PV-A2", "priority": 2,
                                    "operations": [{**ps["operations"][0], "resource": "M2"}]})
    plan = run_mrp(ds(d))
    assert [(o.source_id, o.qty, o.available_date) for o in plan.orders] == [("PV-A2", 16, date(2026, 1, 6))]


@pytest.mark.parametrize("firm", [False, True])
@pytest.mark.parametrize("constrained", [False, True])
def test_the_open_alternative_is_used_when_the_primary_is_closed(firm, constrained):
    d = closed_company(alternative=True, firm=firm)
    d["settings"]["capacity_constrained"] = constrained
    data = ds(d)
    plan = run_mrp(data)
    if not firm:
        assert plan.orders[0].available_date == date(2026, 1, 6)
        assert plan.orders[0].step_resources == {10: "M2"}
    result = run_schedule(data)
    assert result.ok and not result.violations
    assert {o.resource for o in result.ops} == {"M2"}
    assert result.ops[0].end == pytest.approx(14)


def test_fallback_source_uses_its_own_minimum_lot():
    d = closed_company()
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1, "hours_per_shift": 8})
    ps = d["production_sources"][0]
    d["production_sources"].append({**ps, "id": "PV-A2", "priority": 2, "min_lot": 20,
                                    "operations": [{**ps["operations"][0], "resource": "M2"}]})
    plan = run_mrp(ds(d))
    assert [(o.source_id, o.qty, o.for_lot_size) for o in plan.orders] == [("PV-A2", 20, 4)]


def test_parallel_units_are_tried_when_one_unit_cannot_finish_before_shutdown():
    d = closed_company(firm=True)
    d["resources"][0].update(units=2, capacity_changes=[{"valid_from": "2026-01-06", "units": 0}])
    d["receipts"][0]["qty"] = 32
    result = run_schedule(ds(d))
    assert result.ok and not result.violations
    assert {o.unit for o in result.ops} == {0, 1}
    assert all(o.end == pytest.approx(14) for o in result.ops)


@pytest.mark.parametrize("path,body", [
    ("/api/schedule", True), ("/api/schedule/compare", False),
])
def test_an_impossible_firm_schedule_returns_an_explained_result(path, body):
    d = closed_company(firm=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path, json={"dataset": d} if body else d)
    assert response.status_code == 200, response.text
    out = response.json()
    assert not out["ok"]
    assert any(i["code"] == "NO_WORKING_TIME" and "working time" in i["message"] for i in out["issues"])


def test_applying_an_impossible_schedule_preserves_the_input():
    from scp.schedule.apply import apply_schedule
    data = ds(closed_company(firm=True))
    updated, report = apply_schedule(data)
    assert not report.ok
    assert updated == data


def test_temporary_shutdown_still_returns_the_real_reopening_date():
    d = closed_company()
    d["resources"][0]["capacity_changes"][0]["valid_to"] = "2026-01-06"
    plan = run_mrp(ds(d))
    assert [(o.qty, o.available_date) for o in plan.orders] == [(16, date(2026, 1, 8))]


def test_manual_pin_to_a_closed_machine_is_refused_without_switching():
    result = run_schedule(ds(closed_company(alternative=True, firm=True)), {"M1": ["FIRM:10"]})
    assert not result.ok and not result.ops
    assert any(i.code == "NO_WORKING_TIME" for i in result.issues)


def test_firm_load_dates_follow_the_explicit_alternative_assignment():
    d = closed_company(alternative=True, firm=True)
    d["receipts"][0]["step_resources"] = {10: "M2"}
    plan = run_mrp(ds(d))
    machine = next(r for r in plan.resources if r.resource == "M2")
    assert machine.daily_load == {date(2026, 1, 5): pytest.approx(8)}
    assert not any(e.code == "FIRM_NO_WORKING_TIME" for e in plan.exceptions)


def test_send_ahead_to_an_open_alternative_does_not_inherit_a_closed_tail_clock():
    d = closed_company(alternative=True, firm=True)
    d["resources"].append({"id": "M3", "location": "P", "efficiency": 1, "hours_per_shift": 8})
    ops = d["production_sources"][0]["operations"]
    ops[0].update(resource="M3", alternatives=[], send_ahead_qty=8)
    ops.append({"seq": 20, "resource": "M1", "alternatives": ["M2"], "run_hours_per_unit": 0.25})
    result = run_schedule(ds(d))
    assert result.ok and not result.violations
    step = next(o for o in result.ops if o.seq == 20)
    # The predecessor ends at 14:00; M2's final two hours resume at 06:00 Tuesday.
    assert step.resource == "M2" and step.end == pytest.approx(34)


def test_infeasible_optimizer_proposal_keeps_the_feasible_schedule(monkeypatch):
    import importlib
    from scp.schedule.run import build_instance
    optimizer = importlib.import_module("scp.schedule.optimize")
    from scp.schedule.core import decode, edd
    inst, *_ = build_instance(ds(closed_company(alternative=True, firm=True)))
    sequence = edd(inst)
    baseline = decode(inst, sequence)
    monkeypatch.setattr(optimizer, "solve", lambda *a: ({"M1": ["FIRM:10"], "M2": []}, {},
                                                       optimizer.OptInfo(status="feasible")))
    _, result, _, _, info = optimizer.optimize(inst, sequence, {}, 1, searched=(sequence, baseline, []))
    assert result == baseline and not info.kept
    assert "cannot finish" in info.note


@pytest.mark.parametrize("finite", [True, False])
def test_ctp_does_not_confirm_new_production_without_working_time(finite):
    from scp.promise import run_promise
    d = closed_company(finite=finite)
    d["demand"][0].update(kind="sales_order", id="SO-CLOSED")
    d["promising"] = {"include_planned_orders": False, "confirm_beyond_rlt": False, "ctp": True}
    result = run_promise(ds(d))
    assert result.ok
    assert result.orders[0].unconfirmed == 16 and not result.orders[0].lines
