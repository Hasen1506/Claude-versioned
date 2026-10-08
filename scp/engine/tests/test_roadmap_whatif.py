"""Roadmap E: what-if side by side (UX audit section 4).

Two to four scenarios are planned from one base (quick-change chips, or a whole dataset of their own) and compared in
one table against the first: cost, service, inventory, capacity, late units, the deltas and the cost of a point of
service. None of this existed before: these tests fail on main (no ``scp.whatif``, no ``POST /api/whatif``)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.plan import run_mrp
from scp.whatif import (AddShiftChip, DemandChip, LaneDelayChip, LeadTimeChip, ScenarioIn, SupplierOutChip,
                        WhatIfError, WhatIfRequest, apply_chips, chip_label, compare_scenarios)

from .factory import base, demand, ds, example_dict

client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})


def _plant() -> dict:
    """Plant P makes A (2×B + C on M1); B and C bought from S; A ships to depot D (2 days), customer demand at P."""
    d = base(horizon=56)
    d["locations"].append({"id": "D", "type": "dc"})
    d["location_products"].append({"location": "D", "product": "A", "on_hand": 0})
    d["lanes"] = [{"id": "P-D", "origin": "P", "destination": "D", "modes": [{"transit_days": 2}]}]
    d["demand"] = [demand("P", "A", "2026-01-20", 30), demand("P", "A", "2026-01-27", 30),
                   demand("P", "A", "2026-02-03", 20, "sales_order", id="SO1"), demand("D", "A", "2026-02-10", 10)]
    return d


# ---- chips --------------------------------------------------------------------------------------------------------

def test_chips_change_a_copy_and_leave_the_base_alone():
    D = ds(_plant())
    before = D.model_dump(mode="json")
    out = apply_chips(D, [DemandChip(pct=50)])
    assert D.model_dump(mode="json") == before
    assert [r.qty for r in out.demand] == [45, 45, 30, 15]          # forecast and sales orders both scale


def test_demand_chip_can_hit_some_products_only():
    d = _plant()
    d["demand"].append(demand("P", "B", "2026-01-20", 10))
    out = apply_chips(ds(d), [DemandChip(pct=-50, products=["B"])])
    assert [r.qty for r in out.demand] == [30, 30, 20, 10, 5]


def test_supplier_out_switches_to_another_supplier_where_there_is_one():
    d = _plant()
    d["locations"].append({"id": "S2", "type": "supplier"})
    d["purchasing_sources"].append({"id": "PIR-B2", "supplier": "S2", "product": "B", "location": "P", "price": 12,
                                    "lead_time_days": 4})
    out = apply_chips(ds(d), [SupplierOutChip(supplier="S")], notes := [])
    b, c, b2 = out.purchasing_sources
    assert b.blocked and not b2.blocked                             # B: bought from S2 instead
    assert not c.blocked and c.lead_time_days > out.settings.horizon_days   # C: S was the only supplier
    assert notes and "C at P" in notes[0] and "B at P" not in notes[0]
    plan = run_mrp(out)
    assert plan.ok
    buys = {o.source_id for o in plan.orders if str(getattr(o.kind, "value", o.kind)) == "buy"} - {None}
    assert "PIR-B" not in buys
    with pytest.raises(WhatIfError, match="NOPE"):
        apply_chips(ds(_plant()), [SupplierOutChip(supplier="NOPE")])


def test_lead_time_chip_adds_days_and_never_goes_below_zero():
    out = apply_chips(ds(_plant()), [LeadTimeChip(days=7)])
    assert [s.lead_time_days for s in out.purchasing_sources] == [10, 8]
    out = apply_chips(ds(_plant()), [LeadTimeChip(days=-2, supplier="S")])
    assert [s.lead_time_days for s in out.purchasing_sources] == [1, 0]


def test_add_shift_adds_one_of_the_usual_length_while_the_day_has_room():
    out = apply_chips(ds(_plant()), [AddShiftChip(resource="M1")])
    assert out.resources[0].shifts_per_day == 2
    d = _plant()
    d["resources"][0]["shifts_per_day"] = 3                         # 3 × 8 h fill the day
    with pytest.raises(WhatIfError, match="no room"):
        apply_chips(ds(d), [AddShiftChip(resource="M1")])
    with pytest.raises(WhatIfError, match="M9"):
        apply_chips(ds(_plant()), [AddShiftChip(resource="M9")])


def test_add_shift_after_named_shifts():
    d = _plant()
    d["resources"][0]["shifts"] = [{"name": "Day", "start": "06:00", "end": "14:00"}]
    out = apply_chips(ds(d), [AddShiftChip(resource="M1")])
    added = out.resources[0].shifts[-1]
    assert (added.start, added.end) == ("14:00", "22:00")


def test_lane_delay_adds_transit_days_to_routes_through_a_place():
    out = apply_chips(ds(_plant()), [LaneDelayChip(days=5, location="P")])
    assert out.lanes[0].modes[0].transit_days == 7
    with pytest.raises(WhatIfError, match="X"):
        apply_chips(ds(_plant()), [LaneDelayChip(days=5, location="X")])


def test_chip_labels_read_plainly():
    assert chip_label(DemandChip(pct=20)) == "Demand +20 %"
    assert chip_label(SupplierOutChip(supplier="S")) == "S out"
    assert chip_label(LaneDelayChip(days=4, location="PORT")) == "Routes via PORT +4 d"


# ---- comparison ---------------------------------------------------------------------------------------------------

def _req(*scen: ScenarioIn, d: dict | None = None) -> WhatIfRequest:
    return WhatIfRequest(base=ds(d or _plant()), scenarios=list(scen))


def test_baseline_has_no_deltas_and_more_demand_costs_more():
    r = compare_scenarios(_req(ScenarioIn(label="Base"), ScenarioIn(label="Up", chips=[DemandChip(pct=100)])))
    b, up = r.scenarios
    assert b.cost_delta is None and b.service_delta is None and b.verdict == ""
    assert up.levers[0].what == "Demand +100 %"
    assert up.total_cost > b.total_cost and up.cost_delta == pytest.approx(up.total_cost - b.total_cost, abs=0.01)
    assert r.lowest_cost == "Base"


def test_the_same_scenario_twice_is_same_service_at_no_cost():
    r = compare_scenarios(_req(ScenarioIn(label="A"), ScenarioIn(label="B", chips=[DemandChip(pct=0)])))
    assert r.scenarios[1].cost_delta == 0 and r.scenarios[1].verdict == "same service"


def test_a_sole_supplier_out_still_plans_and_loses_service():
    """Blocking the only supplier used to stop the whole plan with a data error, so the what-if said nothing."""
    r = compare_scenarios(_req(ScenarioIn(label="Base"), ScenarioIn(label="S out", chips=[SupplierOutChip(supplier="S")])))
    b, out = r.scenarios
    assert out.ok, out.note
    assert out.service < b.service and out.late_units > b.late_units
    assert out.service_delta < 0 and r.best_service == "Base"
    assert "No other supplier" in out.note


def test_a_stored_version_is_compared_by_what_changed():
    d2 = _plant()
    d2["lanes"][0]["modes"][0]["transit_days"] = 9
    r = compare_scenarios(_req(ScenarioIn(label="Base"), ScenarioIn(label="v2", dataset=ds(d2))))
    assert any(lv.what.startswith("lanes:") for lv in r.scenarios[1].levers)


def test_bad_requests_are_refused_plainly():
    with pytest.raises(WhatIfError, match="own name"):
        compare_scenarios(_req(ScenarioIn(label="A"), ScenarioIn(label="A")))
    with pytest.raises(WhatIfError, match="not both"):
        compare_scenarios(_req(ScenarioIn(label="A"),
                               ScenarioIn(label="B", dataset=ds(_plant()), chips=[DemandChip(pct=5)])))


def test_four_scenarios_on_the_example_network():
    d = example_dict("kitchenware_network")
    sup = d["purchasing_sources"][0]["supplier"]
    r = compare_scenarios(_req(ScenarioIn(label="Base"), ScenarioIn(label="+20", chips=[DemandChip(pct=20)]),
                               ScenarioIn(label="out", chips=[SupplierOutChip(supplier=sup)]),
                               ScenarioIn(label="slow", chips=[LeadTimeChip(days=14)]), d=d))
    assert [s.label for s in r.scenarios] == ["Base", "+20", "out", "slow"]
    assert all(s.ok for s in r.scenarios) and r.currency == "INR"


# ---- API ----------------------------------------------------------------------------------------------------------

def test_api_whatif_round_trip_and_plain_refusals():
    d = _plant()
    ok = client.post("/api/whatif", json={"base": d, "scenarios": [
        {"label": "Base"}, {"label": "Monsoon", "chips": [{"kind": "lane_delay", "days": 6, "location": "P"}]}]})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert [s["label"] for s in body["scenarios"]] == ["Base", "Monsoon"]
    assert body["scenarios"][1]["levers"] == [{"what": "Routes via P +6 d"}]
    bad = client.post("/api/whatif", json={"base": d, "scenarios": [
        {"label": "Base"}, {"label": "X", "chips": [{"kind": "supplier_out", "supplier": "NOPE"}]}]})
    assert bad.status_code == 422 and "NOPE" in bad.json()["detail"]
    one = client.post("/api/whatif", json={"base": d, "scenarios": [{"label": "Base"}]})
    assert one.status_code == 422                                   # 2–4 scenarios
    five = client.post("/api/whatif", json={"base": d, "scenarios": [{"label": str(i)} for i in range(5)]})
    assert five.status_code == 422
    chip = client.post("/api/whatif", json={"base": d, "scenarios": [
        {"label": "Base"}, {"label": "X", "chips": [{"kind": "teleport"}]}]})
    assert chip.status_code == 422


def test_whatif_is_priced_as_heavy_anonymous_work():
    """It plans up to four times, so an anonymous caller pays at least four plans for it (roadmap D's cost table)."""
    from scp.api.companies import _BUCKETS, ANON_COSTS, anon_cost, anon_take
    assert anon_cost("/api/whatif") >= 4 * ANON_COSTS["/api/plan"]
    assert anon_cost("/api/whatif/") == anon_cost("/api/whatif")
    # with the default 120 units a minute, one what-if fits and a second straight after must wait
    key = "anon:whatif-test"
    _BUCKETS.pop(key, None)
    assert anon_take(key, anon_cost("/api/whatif"), 120, now=1000.0) == 0
    assert anon_take(key, anon_cost("/api/whatif"), 120, now=1000.0) > 0
    _BUCKETS.pop(key, None)
