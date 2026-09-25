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
    assert {l["id"] for l in net["locations"]} >= {"PLT-PUNE", "DC-DELHI", "SUP-SHENZHEN"}
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
