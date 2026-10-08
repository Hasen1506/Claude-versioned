"""Roadmap H: the DMSC example case, a Chennai pump maker whose port slows in the north-east monsoon.

The case is a fictional teaching dataset, opened from the start screen like any example, labelled as an example case
(never as real company data), with ready-made what-if scenarios. Fails on main: there is no such example, no
``scp.cases`` and no ``/api/cases``."""
from __future__ import annotations

from fastapi.testclient import TestClient

from scp.api.app import app
from scp.cases import CASE_LABEL, CASES
from scp.plan import run_mrp
from scp.validate import validate
from scp.whatif import WhatIfRequest, apply_chips, compare_scenarios

from .factory import EXAMPLES, load_example

client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})
NAME = "chennai_port_pumps"


def test_every_case_is_a_bundled_example_and_is_labelled_fictional():
    assert NAME in CASES
    for name, case in CASES.items():
        assert (EXAMPLES / f"{name}.json").exists()
        ds = load_example(name)
        assert ds.settings.company_name == case.company_name          # how the web client recognises it
        assert "Example case" in ds.settings.company_name and "fictional" in ds.settings.company_name
        assert "not real company data" in case.label and "invented" in case.brief


def test_the_case_is_complete_and_plans():
    ds = load_example(NAME)
    assert not [i for i in validate(ds) if str(getattr(i.severity, "value", i.severity)) == "error"]
    plan = run_mrp(ds)
    assert plan.ok and plan.kpis.independent_demand > 0
    # the story's moving parts are there: exports through the port yard, imported seals in every pump
    assert {ln.origin for ln in ds.lanes if ln.destination in ("CUS-JEBEL-ALI", "CUS-SINGAPORE")} == {"PORT-MAA"}
    assert all(any(c.product == "SEAL-MECH" for c in ps.components) for ps in ds.production_sources)


def test_its_scenarios_apply_to_its_own_data():
    ds = load_example(NAME)
    for s in CASES[NAME].scenarios:
        apply_chips(ds, s.chips)                                      # every supplier, machine and place exists


def test_the_monsoon_costs_service_and_a_third_shift_does_not_buy_it_back():
    """The teaching point: a port delay is lost in transit, not on the shop floor."""
    r = compare_scenarios(WhatIfRequest(base=load_example(NAME), scenarios=CASES[NAME].scenarios))
    base, monsoon, shift = r.scenarios
    assert all(s.ok for s in r.scenarios)
    assert monsoon.service < base.service - 0.02 and monsoon.late_units > base.late_units
    assert monsoon.late_revenue > base.late_revenue
    assert shift.capacity_peak < monsoon.capacity_peak                # the shift relieves the line…
    assert abs(shift.service - monsoon.service) < 0.005               # …but not the port
    assert r.best_service == "Baseline"


def test_the_start_screen_lists_it_as_an_example_case():
    rows = {e["name"]: e for e in client.get("/api/examples").json()}
    assert rows[NAME]["case"] is True and rows[NAME]["label"] == CASE_LABEL and rows[NAME]["brief"]
    assert rows["kitchenware_network"]["case"] is False and rows["kitchenware_network"]["label"] == ""
    assert client.get(f"/api/examples/{NAME}").status_code == 200
    cases = client.get("/api/cases").json()
    c = next(x for x in cases if x["example"] == NAME)
    assert [s["label"] for s in c["scenarios"]] == ["Baseline", "Monsoon at the port", "Monsoon + third shift"]
    assert c["questions"]
