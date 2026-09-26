"""Unfinished records are set aside instead of locking the dataset; the setup checklist says what is missing."""
import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.model import Dataset
from scp.plan import run_mrp
from scp.validate import validate
from scp.validate.lenient import DatasetRejected, lenient
from scp.validate.setup import checklist, ready

from .factory import START, base, demand

client = TestClient(app)


def planned() -> dict:
    d = base()
    d["demand"] = [demand("P", "A", "2026-01-12", 30)]
    return d


def test_a_clean_dataset_sets_nothing_aside():
    ds, aside = lenient(planned())
    assert aside == [] and validate(ds) == []


def test_a_lane_without_a_mode_is_set_aside_and_the_rest_plans_the_same():
    d = planned()
    d["lanes"].append({"id": "LN-1", "origin": "P", "destination": "P", "modes": []})
    ds, aside = lenient(d)
    assert [(a.collection, a.index, a.object_id, a.field) for a in aside] == [("lanes", 0, "LN-1", "modes")]
    assert "add at least one" in aside[0].reason
    assert ds.lanes == []
    ref = run_mrp(Dataset.model_validate(planned()))
    assert run_mrp(ds).kpis == ref.kpis


def test_a_new_demand_row_with_nothing_chosen_is_set_aside_with_its_position():
    d = planned()
    d["demand"].insert(0, {"location": "", "product": "", "date": START, "qty": 0})
    ds, aside = lenient(d)
    assert [(a.collection, a.index, a.field) for a in aside] == [("demand", 0, "location")]
    assert aside[0].reason == "location is not filled in"
    assert len(ds.demand) == 1


def test_setting_aside_cascades_to_records_that_use_a_set_aside_record():
    d = planned()
    d["resources"].append({"id": "R-9", "location": ""})
    d["production_sources"][0]["operations"].append({"seq": 20, "resource": "R-9", "run_hours_per_unit": 0.1})
    _, aside = lenient(d)
    by = {a.object_id: a.reason for a in aside}
    assert by["R-9"] == "location is not filled in"
    assert by["PV-A"] == "operation 20: resource R-9 is itself left out"


def test_a_real_inconsistency_is_not_set_aside_but_stays_an_error():
    d = planned()
    d["demand"].append(demand("NOWHERE", "A", "2026-01-12", 5))
    ds, aside = lenient(d)
    assert aside == []
    assert any(i.code == "REF_UNKNOWN" and i.severity == "error" for i in validate(ds))


def test_broken_settings_or_master_records_are_still_rejected_in_plain_words():
    d = planned()
    d["settings"]["wacc"] = 12
    with pytest.raises(DatasetRejected) as e:
        lenient(d)
    assert e.value.errors == [{"type": "less_than_equal", "loc": ["settings", "wacc"], "msg": "WACC must be 100% or less"}]
    d = planned()
    d["products"][0]["shelf_life_days"] = -1
    with pytest.raises(DatasetRejected):
        lenient(d)


def test_the_api_reports_set_aside_records_and_keeps_answering():
    d = planned()
    d["lanes"].append({"id": "LN-1", "origin": "", "destination": "", "modes": []})
    r = client.post("/api/validate", json=d)
    assert r.status_code == 200
    v = r.json()
    assert v["blocking"] is False
    assert [(a["collection"], a["object_id"]) for a in v["set_aside"]] == [("lanes", "LN-1")]
    assert any(i["code"] == "SET_ASIDE" and "Lane LN-1 is left out" in i["message"] for i in v["issues"])
    assert client.post("/api/network", json=d).status_code == 200


def test_rejections_over_the_api_are_in_plain_words():
    d = planned()
    d["settings"]["horizon_days"] = 3
    r = client.post("/api/plan", json=d)
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "horizon days must be 7 or more"


# ---- setup checklist ------------------------------------------------------------------------------------------
def _steps(items):
    return [(i.step, i.status) for i in items]


def test_an_empty_company_is_told_to_add_places_and_products():
    ds = Dataset.model_validate({"settings": {"planning_start": START}})
    items = checklist(ds)
    assert ("places", "todo") in _steps(items) and ("products", "todo") in _steps(items)
    assert not ready(items)


def test_a_company_without_demand_is_not_ready_even_though_nothing_is_wrong():
    d = base()
    ds = Dataset.model_validate(d)
    assert [i for i in validate(ds) if i.severity == "error"] == []
    items = checklist(ds)
    assert ("demand", "todo") in _steps(items)
    assert not ready(items)


def test_a_component_nobody_supplies_is_named_with_its_parent():
    d = planned()
    d["purchasing_sources"] = [p for p in d["purchasing_sources"] if p["product"] != "C"]
    items = checklist(Dataset.model_validate(d))
    supply = [i for i in items if i.step == "supply" and i.status == "todo"]
    assert len(supply) == 1
    assert supply[0].text.startswith("C at P (a component of A) has no way to be supplied")
    assert supply[0].action and supply[0].action.route == ["setup", "product", "C", "P"]


def test_a_planned_company_is_ready():
    items = checklist(Dataset.model_validate(planned()))
    assert ready(items)
    assert ("demand", "done") in _steps(items) and ("supply", "done") in _steps(items)
