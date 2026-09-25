"""End-to-end scenarios (scp.scenarios): every hand-derived checkpoint, straight through the engine and
through the HTTP API the web client uses."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.model import Dataset
from scp.scenarios import SCENARIOS, EngineClient, ScenarioReport
from scp.scenarios.http import HttpClient
from scp.versions import get_store

IDS = [s.id for s in SCENARIOS]


def _explain(r: ScenarioReport) -> str:
    lines = [f"{r.id} over {r.client}: {r.failed} failed"]
    for st in r.steps:
        if st.error:
            lines.append(f"  step {st.n} '{st.title}' raised: {st.error}")
        for c in st.checks:
            if not c.passed:
                lines.append(f"  step {st.n} '{st.title}' · {c.label}\n      expected {c.expected}\n      actual   {c.actual}")
    return "\n".join(lines)


@pytest.mark.parametrize("sc", SCENARIOS, ids=IDS)
def test_scenario_engine(sc):
    r = sc.execute(EngineClient())
    assert r.ok, _explain(r)
    assert r.passed >= 10 and all(st.checks for st in r.steps)


@pytest.mark.parametrize("sc", SCENARIOS, ids=IDS)
def test_scenario_over_http(sc):
    r = sc.execute(HttpClient(TestClient(app)))
    assert r.ok, _explain(r)


def test_every_checkpoint_carries_a_derivation_or_a_self_evident_label():
    for sc in SCENARIOS:
        r = sc.execute(EngineClient())
        assert all(st.narrative for st in r.steps), sc.id
        explained = sum(1 for st in r.steps for c in st.checks if c.why)
        assert explained >= len(r.steps) // 2, f"{sc.id}: only {explained} checkpoints explain themselves"


def test_the_declared_stages_are_the_stages_the_steps_check():
    """The Proof page's coverage matrix reads both: a stage a scenario claims must carry checkpoints."""
    for sc in SCENARIOS:
        checked = {st for s in sc.execute(EngineClient()).steps if s.checks for st in s.stage.split("+")}
        assert checked == set(sc.stages), sc.id


def test_scenario_api_lists_serves_and_runs_in_isolation():
    api = TestClient(app)
    listed = api.get("/api/scenarios").json()
    assert [x["id"] for x in listed] == IDS and all(x["proves"] and x["stages"] for x in listed)
    ds = Dataset.model_validate(api.get(f"/api/scenarios/{IDS[0]}/dataset").json())
    assert ds.settings.company_name == SCENARIOS[0].company
    before = get_store().list()
    rep = ScenarioReport.model_validate(api.post("/api/scenarios/s6-tents/run").json())
    assert rep.ok and rep.client == "engine" and rep.passed > 0
    assert get_store().list() == before          # the run saved versions, but in its own store
    assert api.post("/api/scenarios/nope/run").status_code == 404
