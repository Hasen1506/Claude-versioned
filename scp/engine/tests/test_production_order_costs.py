"""Order costs must price the selected machine and the whole batches actually run."""
import math

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.finance import run_finance
from scp.plan import run_mrp
from scp.plan.costing import conversion_unit_cost

from .factory import demand, ds
from .test_resource_calendar_dates import calendar_company
from .test_unavailable_capacity import closed_company


def alternative_company(rate=25, constrained=False):
    raw = closed_company(alternative=True)
    raw["settings"].update(wacc=0, holding_spread=0, capacity_constrained=constrained)
    raw["products"][0]["price"] = 200
    raw["production_sources"][0]["operations"][0]["setup_hours"] = 2
    raw["resources"][-1]["cost_per_hour"] = rate
    return raw


@pytest.mark.parametrize("rate", [25, 250])
@pytest.mark.parametrize("constrained", [False, True])
def test_make_and_finance_costs_follow_the_selected_alternative(rate, constrained):
    data = ds(alternative_company(rate, constrained))
    plan = run_mrp(data)
    order = plan.orders[0]
    assert order.step_resources == {10: "M2"}
    assert order.costs == {"production": pytest.approx(8 * rate), "setup": pytest.approx(2 * rate)}
    assert order.total_cost == pytest.approx(10 * rate)
    assert plan.kpis.production_cost == pytest.approx(8 * rate)
    assert plan.kpis.setup_cost == pytest.approx(2 * rate)
    finance = run_finance(data, plan)
    assert finance.reconciliation.reconciled
    assert finance.serve[0].costs["production"] == pytest.approx(8 * rate)
    assert finance.serve[0].margin == pytest.approx(2800 - 10 * rate)


def batch_company(qty):
    raw = calendar_company(False)
    raw["calendars"][-1]["holidays"] = []
    raw["settings"].update(wacc=0, holding_spread=0)
    raw["products"][0]["price"] = 200
    source = raw["production_sources"][0]
    source["full_batches"] = False
    source["operations"][0].update(setup_hours=2, run_hours_per_unit=0, batch_qty=10, batch_hours=3)
    raw["demand"] = [demand("P", "A", "2026-01-15", qty)]
    return raw


@pytest.mark.parametrize("qty", [1, 9, 10, 11, 20, 21])
def test_partial_batches_cost_the_whole_machine_workload(qty):
    data = ds(batch_company(qty))
    plan = run_mrp(data)
    order = plan.orders[0]
    work = 3 * math.ceil(qty / 10)
    assert order.qty == qty
    assert sum(b.load_hours for r in plan.resources for b in r.buckets) == pytest.approx(work + 2)
    assert order.costs == {"production": pytest.approx(work * 100), "setup": pytest.approx(200)}
    finance = run_finance(data, plan)
    assert finance.reconciliation.reconciled
    assert finance.serve[0].costs["production"] == pytest.approx(work * 100)
    assert finance.serve[0].margin == pytest.approx(175 * qty - work * 100 - 200)


def test_batch_cost_rounding_happens_after_operation_scrap():
    raw = batch_company(10)
    raw["production_sources"][0]["operations"][0]["scrap"] = 0.2
    order = run_mrp(ds(raw)).orders[0]
    # 10 good require 12.5 entering units: two three-hour batches.
    assert order.costs["production"] == pytest.approx(600)


def test_exact_order_cost_keeps_labor_outside_processing_and_conversion():
    raw = batch_company(11)
    raw["resources"].append({"id": "LAB", "location": "P", "kind": "labor", "cost_per_hour": 20})
    source = raw["production_sources"][0]
    source["conversion_cost_per_unit"] = 7
    source["operations"][0].update(run_hours_per_unit=0.2, labor_resource="LAB", labor_hours_per_unit=0.5)
    source["operations"].append({"seq": 20, "subcontract": {"supplier": "S", "workdays": 1,
                                                             "cost_per_unit": 3}})
    order = run_mrp(ds(raw)).orders[0]
    # Machine (2.2 + 6) * 100, labor 5.5 * 20, supplier 11 * 3, overhead 11 * 7.
    assert order.costs["production"] == pytest.approx(1040)
    assert order.costs["setup"] == pytest.approx(200)


def test_nominal_unit_valuation_remains_a_full_batch_average():
    assert conversion_unit_cost(ds(batch_company(1)), "PV-A") == pytest.approx(30)


@pytest.mark.parametrize("raw,expected", [(alternative_company(25), 200), (batch_company(11), 600)])
def test_finance_api_reports_the_order_work_cost(raw, expected):
    with TestClient(app) as client:
        response = client.post("/api/finance", json=raw)
    assert response.status_code == 200
    assert response.json()["serve"][0]["costs"]["production"] == pytest.approx(expected)
