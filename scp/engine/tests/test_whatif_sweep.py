"""Enterprise plan 5.3: what-if smaller than the leaders'.

* one change swept over several sizes, read as cost against service (safety stock, against the service expected when
  demand misses its forecast) or as an exposure (how far it can go before service falls);
* stored versions as columns of the side-by-side, read on the server for the caller's company;
* money at risk over time: the sales projected late, by the period their demand is due.

These tests fail before 5.3: there is no ``sweep_chip``, no ``POST /api/whatif/sweep``, no ``version`` on a scenario
and no ``at_risk`` on a scenario's result."""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.plan import run_mrp
from scp.whatif import (DemandChip, LeadTimeChip, MachineDownChip, SafetyDaysChip, ScenarioIn, SupplierPriceChip,
                        SweepRequest, WhatIfError, WhatIfRequest, apply_chips, compare_scenarios, expected_service,
                        sweep_chip)

from .factory import base, demand, ds, example_dict, load_example

KEY = {"X-Browser-Key": "tests-browser-key-5300"}
client = TestClient(app, headers=KEY)


def _bought(horizon: int = 56) -> dict:
    """A sold at P for 100 a unit, bought from S in 20 days, nothing on hand: the demand of 2026-01-07 is late (10
    units), the demand of 2026-02-09 is in time."""
    d = base(horizon=horizon)
    d["products"] = [{"id": "A", "type": "FG", "price": 100}]
    d["location_products"] = [{"location": "P", "product": "A", "on_hand": 0}]
    d["resources"], d["production_sources"] = [], []
    d["purchasing_sources"] = [{"id": "PIR-A", "supplier": "S", "product": "A", "location": "P", "price": 40,
                                "lead_time_days": 20}]
    d["demand"] = [demand("P", "A", "2026-01-07", 10), demand("P", "A", "2026-02-09", 10)]
    return d


def _req(d, chips_by_label: dict[str, list]) -> WhatIfRequest:
    return WhatIfRequest(base=d, scenarios=[ScenarioIn(label=k, chips=v) for k, v in chips_by_label.items()])


# ---- money at risk over time --------------------------------------------------------------------------------------

def test_money_at_risk_falls_in_the_period_the_late_demand_is_due():
    D = ds(_bought())
    r = compare_scenarios(_req(D, {"Today": [], "Lead time -15 d": [LeadTimeChip(days=-15)]}))
    today, quick = r.scenarios
    assert [p.start.isoformat() for p in r.periods[:2]] == ["2026-01-05", "2026-01-12"]
    assert len(today.at_risk) == len(r.periods) == len(quick.at_risk)
    # 10 late units × 100, due 2026-01-07: the first week only; the February demand is in time
    assert today.at_risk[0] == pytest.approx(1000.0)
    assert sum(today.at_risk[1:]) == 0
    assert sum(today.at_risk) == pytest.approx(today.late_revenue)
    # bought in 5 days, the first demand is still late (nothing on hand before 2026-01-10) but by its own week
    assert sum(quick.at_risk) == pytest.approx(quick.late_revenue)


@pytest.mark.parametrize("name", ["kitchenware_network", "chennai_port_pumps"])
def test_money_at_risk_over_time_adds_up_to_the_sales_at_risk(name):
    D = load_example(name)
    r = compare_scenarios(_req(D, {"Today": [], "Demand +20 %": [DemandChip(pct=20)]}))
    for s in r.scenarios:
        assert sum(s.at_risk) == pytest.approx(s.late_revenue, rel=1e-6, abs=0.05)
    assert sum(r.scenarios[1].at_risk) > sum(r.scenarios[0].at_risk)
    # each period's figure is the late demand due in it, at its price (an independent count from the plan's demand)
    plan = run_mrp(D)
    starts = [p.start for p in r.periods]
    by = [0.0] * len(starts)
    for x in plan._late:
        i = max(i for i, s in enumerate(starts) if s <= x.date) if x.date >= starts[0] else 0
        by[i] += x.late * (D.selling_price(x.location, x.product) or 0)
    assert r.scenarios[0].at_risk == pytest.approx([round(v, 2) for v in by])


# ---- stored versions as columns -----------------------------------------------------------------------------------

def _store(d: dict, name: str) -> str:
    res = client.post("/api/versions", json={"dataset": d, "name": name, "note": "5.3 test"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_a_stored_version_is_a_column_read_on_the_server():
    d = _bought()
    rush = _bought()
    rush["purchasing_sources"][0]["lead_time_days"] = 2
    va, vb = _store(d, "Plan as is"), _store(rush, "Rush supplier")
    res = client.post("/api/whatif", json={"base": d, "scenarios": [
        {"label": "Working copy", "chips": []}, {"label": "Plan as is", "version": va},
        {"label": "Rush supplier", "version": vb}, {"label": "Rush + demand", "version": vb,
                                                     "chips": [{"kind": "demand", "pct": 50}]}]})
    assert res.status_code == 200, res.text
    out = {s["label"]: s for s in res.json()["scenarios"]}
    # the same as passing the data itself
    direct = compare_scenarios(WhatIfRequest(base=d, scenarios=[ScenarioIn(label="w"), ScenarioIn(label="r", dataset=rush)]))
    assert out["Rush supplier"]["total_cost"] == pytest.approx(direct.scenarios[1].total_cost)
    assert out["Rush supplier"]["service"] == pytest.approx(direct.scenarios[1].service)
    assert out["Plan as is"]["cost_delta"] == pytest.approx(0) and out["Plan as is"]["verdict"] == "same service"
    assert out["Rush supplier"]["service_delta"] > 0
    assert sum(out["Working copy"]["at_risk"]) > 0 and sum(out["Rush supplier"]["at_risk"]) == 0
    levers = [lv["what"] for lv in out["Rush supplier"]["levers"]]
    assert levers[0] == f"stored version {vb}" and any(x.startswith("purchasing_sources: ") for x in levers)
    assert [lv["what"] for lv in out["Rush + demand"]["levers"]][:2] == [f"stored version {vb}", "Demand +50 %"]
    assert out["Rush + demand"]["sales_value"] == pytest.approx(1.5 * out["Rush supplier"]["sales_value"])


def test_stored_versions_are_only_those_of_the_callers_company():
    d = _bought()
    vid = _store(d, "Mine")
    body = {"base": d, "scenarios": [{"label": "a"}, {"label": "b", "version": vid}]}
    other = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-5301"}).post("/api/whatif", json=body)
    assert other.status_code == 404 and vid in other.json()["detail"]
    anon = TestClient(app).post("/api/whatif", json=body)
    assert anon.status_code == 400 and "never kept in one space" in anon.json()["detail"]
    # without a stored version, a browser with no key still compares
    assert TestClient(app).post("/api/whatif", json={"base": d, "scenarios": [{"label": "a"}, {"label": "b"}]}).status_code == 200
    both = client.post("/api/whatif", json={"base": d, "scenarios": [{"label": "a"},
                                                                       {"label": "b", "version": vid, "dataset": d}]})
    assert both.status_code == 422 and "not both" in both.json()["detail"]


def test_compare_without_a_reader_refuses_a_version():
    with pytest.raises(WhatIfError, match="not read here"):
        compare_scenarios(WhatIfRequest(base=ds(_bought()), scenarios=[ScenarioIn(label="a"),
                                                                        ScenarioIn(label="b", version="V-1")]))


# ---- a sweep ------------------------------------------------------------------------------------------------------

def test_each_point_of_a_sweep_is_the_what_if_of_that_size():
    D = load_example("chennai_port_pumps")
    r = sweep_chip(SweepRequest(base=D, chip=LeadTimeChip(days=0), values=[14, -7, 7, 21, 7]))
    assert [p.value for p in r.points] == [-7, 7, 14, 21]                  # sorted, the repeat dropped
    assert r.kind == "lead_time" and r.field == "days" and not r.lever
    one = compare_scenarios(_req(D, {"Today": [], "+14": [LeadTimeChip(days=14)]}))
    p14 = r.points[2]
    assert p14.label == "Lead time +14 d"
    assert p14.total_cost == pytest.approx(one.scenarios[1].total_cost)
    assert p14.service == pytest.approx(one.scenarios[1].service)
    assert p14.late_revenue == pytest.approx(one.scenarios[1].late_revenue)
    assert p14.at_risk == one.scenarios[1].at_risk and r.periods == one.periods
    assert r.baseline.total_cost == pytest.approx(one.scenarios[0].total_cost)
    assert p14.cost_delta == pytest.approx(one.scenarios[1].cost_delta)
    # longer lead times never help: service falls and money at risk grows along the sweep
    svc = [p.service for p in r.points]
    assert svc == sorted(svc, reverse=True) and svc[-1] < r.baseline.service
    assert [p.late_revenue for p in r.points] == sorted(p.late_revenue for p in r.points)
    assert not any(p.frontier for p in r.points) and all(p.expected_service is None for p in r.points)
    assert r.read[1].startswith("Service holds within half a point of today up to Lead time -7 d; at Lead time +7 d it is 96.5 %")


def test_a_safety_stock_sweep_is_read_against_expected_service():
    D = load_example("kitchenware_network")
    r = sweep_chip(SweepRequest(base=D, chip=SafetyDaysChip(days=0), values=[0, 5, 10, 30]))
    assert r.lever
    exp = [p.expected_service for p in r.points]
    assert all(e is not None for e in exp) and exp == sorted(exp)          # more safety stock, more expected service
    assert exp[0] < r.baseline.expected_service < exp[-1] + 1e-9
    cost = [p.total_cost for p in r.points]
    assert cost == sorted(cost)
    # the frontier: a value is on it when no other (nor today) is as cheap with as much expected service
    every = [r.baseline, *r.points]
    for p in r.points:
        beaten = any(x is not p and x.total_cost <= p.total_cost + 1e-6 and x.expected_service >= p.expected_service - 1e-4
                     and (x.total_cost < p.total_cost - 1e-6 or x.expected_service > p.expected_service + 1e-4)
                     for x in every)
        assert p.frontier is (not beaten), p.label
    assert [p.frontier for p in r.points] == [True, True, False, False]
    # each step's cost per point of expected service, from the point before
    a, b = r.points[0], r.points[1]
    assert b.step_cost_per_point == pytest.approx((b.total_cost - a.total_cost)
                                                  / ((b.expected_service - a.expected_service) * 100), rel=1e-6)
    text = " ".join(r.read)
    assert "expected service 93.7 % to 100.0 %" in text
    assert "The cheapest service is from Safety stock 0 d to Safety stock 5 d" in text
    assert "Not worth it: Safety stock 10 d, Safety stock 30 d" in text
    # the plan's own service falls as the stock is built at once: said, with what to do instead
    assert r.points[-1].service < r.points[0].service
    assert "Raise it in steps over several weeks instead." in text


def test_sweep_refusals_are_plain():
    D = ds(_bought())
    with pytest.raises(WhatIfError, match="only a change with a number"):
        sweep_chip(SweepRequest.model_validate({"base": D.model_dump(mode="json"),
                                                "chip": {"kind": "supplier_out", "supplier": "S"}, "values": [1, 2]}))
    with pytest.raises(WhatIfError, match="two different values"):
        sweep_chip(SweepRequest(base=D, chip=DemandChip(pct=0), values=[10, 10]))
    with pytest.raises(WhatIfError, match="-95 is not a size this change can take"):
        sweep_chip(SweepRequest(base=D, chip=DemandChip(pct=0), values=[-95, 10]))


def test_machine_down_days_are_whole_days():
    D = load_example("chennai_port_pumps")
    res = D.resources[0].id
    r = sweep_chip(SweepRequest(base=D, chip=MachineDownChip(resource=res, days=1), values=[2.4, 7]))
    assert [p.label for p in r.points] == [f"{res} down 2 d", f"{res} down 7 d"]


def test_api_sweep_round_trip():
    d = example_dict("chennai_port_pumps")
    ok = client.post("/api/whatif/sweep", json={"base": d, "chip": {"kind": "demand", "pct": 0}, "values": [-10, 10, 30]})
    assert ok.status_code == 200, ok.text
    j = ok.json()
    assert [p["label"] for p in j["points"]] == ["Demand -10 %", "Demand +10 %", "Demand +30 %"]
    assert j["currency"] == "INR" and len(j["periods"]) == len(j["points"][0]["at_risk"]) and j["read"]
    bad = client.post("/api/whatif/sweep", json={"base": d, "chip": {"kind": "add_shift", "resource": "X"}, "values": [1, 2]})
    assert bad.status_code == 422 and "only a change with a number" in bad.json()["detail"]
    few = client.post("/api/whatif/sweep", json={"base": d, "chip": {"kind": "demand", "pct": 0}, "values": [1]})
    assert few.status_code == 422


# ---- expected service against forecast error ---------------------------------------------------------------------

def _G(k: float) -> float:
    phi = math.exp(-k * k / 2) / math.sqrt(2 * math.pi)
    return phi - k * (1 - 0.5 * (1 + math.erf(k / math.sqrt(2))))


def _stocked(days: float) -> dict:
    """A bought at P, 10 a day, weekly forecast error 30 %, 7 days' lead time, lots of 70: safety stock as days."""
    d = _bought(horizon=84)
    d["location_products"] = [{"location": "P", "product": "A", "on_hand": 500,
                               "lot_sizing": {"policy": "FIXED", "fixed_qty": 70},
                               "safety_stock": {"method": "days_of_supply", "days": days, "demand_cv": 0.3}
                               if days else {"demand_cv": 0.3}}]
    d["purchasing_sources"][0]["lead_time_days"] = 7
    d["demand"] = [demand("P", "A", f"2026-{m:02d}-{day:02d}", 10) for m, last in ((1, 31), (2, 28), (3, 31))
                   for day in range(1, last + 1)]
    return d


def test_expected_service_is_the_loss_function_fill_rate():
    D = ds(_stocked(3))
    plan = run_mrp(D)
    node = next(n for n in plan.nodes if n.product == "A")
    ss = sum(b.safety_stock for b in node.buckets) / len(node.buckets)
    assert 30 <= ss <= 35                         # three days of 10 (the last weeks see the next ones' demand too)
    sigma = math.sqrt(7 * (0.3 * 10 * math.sqrt(7)) ** 2)                  # σ_d = cv·d̄·√7 over 7 days of lead time
    beta = 1 - sigma * _G(ss / sigma) / 70
    assert expected_service(D, plan) == pytest.approx(beta, abs=1e-5)
    # none held: the lot alone carries the error
    D0 = ds(_stocked(0))
    assert expected_service(D0, run_mrp(D0)) == pytest.approx(1 - sigma * _G(0) / 70, abs=1e-5)


def test_more_safety_stock_never_lowers_expected_service():
    D = ds(_stocked(0))
    # the chip keeps the measured forecast error: it describes the demand, not the policy
    assert apply_chips(D, [SafetyDaysChip(days=4)]).location_products[0].safety_stock.demand_cv == 0.3
    got = [expected_service(x, run_mrp(x)) for x in (apply_chips(D, [SafetyDaysChip(days=v)]) for v in (0, 1, 2, 4, 8))]
    assert got == sorted(got) and got[0] < got[-1] <= 1.0


# ---- a supplier's prices (N267) -----------------------------------------------------------------------------------

def test_a_supplier_price_change_reaches_its_prices_scales_and_contracts_only():
    d = _bought()
    d["locations"].append({"id": "S2", "type": "supplier"})
    d["purchasing_sources"][0]["price_scales"] = [{"from_qty": 100, "price": 36}]
    d["purchasing_sources"].append({"id": "PIR-A2", "supplier": "S2", "product": "A", "location": "P", "price": 50,
                                    "lead_time_days": 20, "priority": 2})
    d["contracts"] = [{"id": "K1", "supplier": "S", "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                       "lines": [{"product": "A", "price": 38}]},
                      {"id": "K2", "supplier": "S2", "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                       "lines": [{"product": "A", "price": 48}]}]
    D = ds(d)
    out = apply_chips(D, [SupplierPriceChip(supplier="S", pct=10)])
    by = {ps.id: ps for ps in out.purchasing_sources}
    assert by["PIR-A"].price == pytest.approx(44) and by["PIR-A"].price_scales[0].price == pytest.approx(39.6)
    assert by["PIR-A2"].price == 50                                          # another supplier's: untouched
    assert out.contracts[0].lines[0].price == pytest.approx(41.8)
    assert out.contracts[1].lines[0].price == 48                            # the other supplier's contract
    assert D.purchasing_sources[0].price == 40                              # the base is left alone
    assert apply_chips(D, [SupplierPriceChip(pct=-10)]).purchasing_sources[1].price == pytest.approx(45)
    with pytest.raises(WhatIfError, match="nothing is bought there"):
        apply_chips(D, [SupplierPriceChip(supplier="S", products=["B"], pct=5)])


def test_purchase_cost_moves_with_the_price_and_service_does_not():
    D = ds(_bought())
    r = sweep_chip(SweepRequest(base=D, chip=SupplierPriceChip(pct=0, supplier="S"), values=[10, 20]))
    a, b = r.points
    assert a.label == "Purchase prices +10 % at S" and r.field == "pct" and not r.lever
    assert a.cost_delta > 0 and b.cost_delta == pytest.approx(2 * a.cost_delta, rel=1e-6)   # linear in the price
    assert a.service == b.service == r.baseline.service


def test_ask_reads_a_suppliers_price_change():
    from scp.tower import open_items
    from scp.tower.ask import ask
    D = load_example("kitchenware_network")
    plan = run_mrp(D)
    items = open_items(D, plan)
    up = ask(D, plan, items, "What if Hindalco raises prices 10 %?")
    assert up.understood == "What if: Purchase prices +10 % at SUP-COPPER?" and "cost +" in up.answer
    assert ask(D, plan, items, "What if copper wire costs 10% more?").understood == \
        "What if: Purchase prices +10 % (RM-CU-WIRE)?"
    # a product we make is not bought: its price is not a purchase price
    kettle = ask(D, plan, items, "What if kettle prices rise 5 %?")
    assert "Purchase prices" not in kettle.understood
    # "down" with a price is a price, not a supplier out
    assert ask(D, plan, items, "what if Hindalco prices go down 5%?").understood == \
        "What if: Purchase prices -5 % at SUP-COPPER?"
