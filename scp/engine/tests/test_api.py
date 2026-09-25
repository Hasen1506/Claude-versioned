from fastapi.testclient import TestClient

from scp.api.app import app

from .factory import example_dict

client = TestClient(app)


def test_health_and_examples():
    assert client.get("/api/health").json()["status"] == "ok"
    names = {e["name"] for e in client.get("/api/examples").json()}
    assert {"kitchenware_network", "single_product_plant"} <= names
    assert client.get("/api/examples/kitchenware_network").json()["settings"]["currency"] == "INR"
    assert client.get("/api/examples/nope").status_code == 404
    assert client.get("/api/examples/..%2Fsecrets").status_code == 404


def test_validate_network_plan_round_trip():
    d = example_dict("kitchenware_network")
    v = client.post("/api/validate", json=d).json()
    assert v == {"issues": [], "blocking": False}
    net = client.post("/api/network", json=d).json()
    assert {loc["id"] for loc in net["locations"]} >= {"PLT-PUNE", "DC-DELHI", "SUP-SHENZHEN"}
    assert any(e["kind"] == "purchase" and e["origin"] == "SUP-SHENZHEN" for e in net["edges"])
    plan = client.post("/api/plan", json=d).json()
    assert plan["ok"] and plan["orders"] and plan["kpis"]["total_cost"] > 0


def test_schema_errors_are_field_level():
    d = example_dict("single_product_plant")
    d["settings"]["wacc"] = 12  # percent typed instead of a fraction
    r = client.post("/api/validate", json=d)
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][-2:] == ["settings", "wacc"]


def test_rules_catalog():
    codes = {r["code"] for r in client.get("/api/rules").json()}
    assert "NO_SOURCE" in codes and "BOM_CYCLE" in codes


def test_unknown_api_route_is_404_not_the_spa():
    assert client.get("/api/nope").status_code == 404


def test_forecast_and_release():
    d = example_dict("kitchenware_network")
    models = client.get("/api/forecast/models").json()
    assert {m["id"] for m in models["models"]} >= {"ses", "croston", "timesfm"}
    assert models["foundation"]["available"] is False
    r = client.post("/api/forecast", json=d).json()
    assert r["ok"] and len(r["series"]) == 9 and r["summary"]["wape"] > 0
    rel = client.post("/api/forecast/release", json={"dataset": d, "keys": [r["series"][0]["key"]]}).json()
    assert rel["release"]["series"] == 1 and rel["release"]["records"] > 0
    assert client.post("/api/plan", json=rel["dataset"]).json()["ok"]


def test_release_refuses_a_blocked_dataset():
    d = example_dict("kitchenware_network")
    d["history"][0]["product"] = "NOPE"
    assert client.post("/api/forecast/release", json={"dataset": d}).status_code == 409


def test_inventory():
    r = client.post("/api/inventory", json=example_dict("kitchenware_network")).json()
    assert r["ok"] and r["solver"]["status"] == "optimal"
    assert r["totals"]["meio_cost"] <= r["totals"]["single_cost"]
    assert {n["decision"] for n in r["nodes"]} >= {"buffer", "pass_through", "customer"}


def test_sop_and_release():
    d = example_dict("kitchenware_network")
    r = client.post("/api/sop", json=d).json()
    assert r["ok"] and r["solver"]["status"] == "optimal" and r["kpis"]["fill_rate"] > 0.9
    rel = client.post("/api/sop/release", json=d).json()
    assert rel["release"]["records"] > 0
    assert any(x.get("id", "") and x["id"].startswith("SOP-") for x in rel["dataset"]["demand"])
    assert client.post("/api/plan", json=rel["dataset"]).json()["ok"]


def test_schedule():
    d = example_dict("kitchenware_network")
    r = client.post("/api/schedule", json={"dataset": d}).json()
    assert r["ok"] and r["violations"] == [] and r["search"]["mode"] == "improved"
    seq = next(x for x in r["resources"] if x["id"] == "PUNE-L1")["sequence"][::-1]
    m = client.post("/api/schedule", json={"dataset": d, "sequence": {"PUNE-L1": seq}}).json()
    assert m["search"]["mode"] == "manual"
    assert next(x for x in m["resources"] if x["id"] == "PUNE-L1")["sequence"] == seq


def test_promise_flow():
    d = example_dict("kitchenware_network")
    r = client.post("/api/promise", json=d).json()
    assert r["ok"] and r["kpis"]["orders"] == 9
    c = client.post("/api/promise/check", json={"dataset": d, "order": {
        "location": "CUS-WEST-TRADE", "product": "MG-750", "date": "2026-10-02", "qty": 6000}}).json()
    assert c["mode"] == "check" and c["checked"]["qty"] == 6000
    m = client.post("/api/promise/commit", json={"dataset": d}).json()
    assert len(m["dataset"]["confirmations"]) >= 9
    b = client.post("/api/promise/bop", json=m["dataset"]).json()
    assert b["mode"] == "bop" and len(b["bop"]) == 9
