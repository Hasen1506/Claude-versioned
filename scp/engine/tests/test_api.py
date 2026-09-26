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
    assert v["issues"] == [] and v["blocking"] is False and v["set_aside"] == []
    assert all(i["status"] != "todo" for i in v["setup"])
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
    # the manual sequence's dates go back into the plan: every scheduled order becomes a dated production order
    a = client.post("/api/schedule/apply", json={"dataset": d, "sequence": {"PUNE-L1": seq}}).json()
    assert len(a["report"]["applied"]) == len(m["orders"]) and a["report"]["skipped"] == {}
    dated = {x["receipt"]: x for x in a["report"]["applied"]}
    for rc in a["dataset"]["receipts"]:
        if rc["id"] in dated:
            assert rc["scheduled"] and rc["due_date"] == dated[rc["id"]]["due_date"]
    bad = {**d, "changeovers": [{"resource": "NOPE", "from_group": "A", "to_group": "B", "hours": 1}]}
    assert client.post("/api/schedule/apply", json={"dataset": bad}).status_code == 409


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


def test_actuals_flow():
    d = example_dict("kitchenware_network")
    v = client.post("/api/actuals", json={"dataset": d}).json()
    assert v["movements"] > 0 and all(r["difference"] == 0 for r in v["stock"])
    r = client.post("/api/actuals/roll", json={"dataset": d, "as_of": "2026-10-05"}).json()
    assert r["report"]["ok"] and r["dataset"]["settings"]["planning_start"] == "2026-10-05"
    assert {c["id"] for c in r["report"]["closed"]} >= {"SO-88121", "MO-100455", "STO-2201"}
    assert client.post("/api/actuals/roll", json={"dataset": d, "as_of": "2026-01-01"}).status_code == 409
    f = client.post("/api/orders/firm", json={"dataset": r["dataset"]}).json()
    assert f["report"]["ok"] and f["report"]["firmed"]
    assert len(f["dataset"]["receipts"]) == len(r["dataset"]["receipts"]) + len(f["report"]["firmed"])


def test_finance():
    r = client.post("/api/finance", json=example_dict("kitchenware_network")).json()
    assert r["ok"] and r["reconciliation"]["reconciled"] and r["serve"] and r["inventory"]["buckets"]
    assert {a["id"] for a in r["capacity"]} == {"CAP-L1-SHIFT3", "CAP-WIND-M4"}


def test_tower_flow():
    d = example_dict("kitchenware_network")
    r = client.post("/api/tower", json=d).json()
    assert {k["id"] for k in r["kpis"]} >= {"forecast_accuracy", "otif_requested", "supplier_reliability",
                                             "excess_obsolete", "exception_ageing", "cost_to_serve"}
    item = r["worklist"][0]
    u = client.post(f"/api/tower/items/{item['id']}", json={"owner": "Asha", "status": "acknowledged"}).json()
    assert u["owner"] == "Asha" and u["owner_source"] == "manual" and u["status"] == "acknowledged"
    again = client.post("/api/tower", json=d).json()
    assert next(w for w in again["worklist"] if w["id"] == item["id"])["owner"] == "Asha"
    assert [h["action"] for h in client.get(f"/api/tower/items/{item['id']}/history").json()] == ["opened", "acknowledged", "assigned"]
    assert client.post("/api/tower/items/nope", json={"status": "resolved"}).status_code == 404
    assert client.post(f"/api/tower/items/{item['id']}", json={"status": "cleared"}).status_code == 422


def test_versions_flow():
    d = example_dict("single_product_plant")
    base = client.post("/api/versions", json={"dataset": d, "name": "Week 1"}).json()
    assert base["kind"] == "base" and base["status"] == "active"
    sc = client.post(f"/api/versions/{base['id']}/branch", json={"name": "Double demand"}).json()
    doc = client.get(f"/api/versions/{sc['id']}").json()
    edited = doc["dataset"]
    for x in edited["demand"]:
        x["qty"] *= 2
    assert client.put(f"/api/versions/{sc['id']}", json=edited).json()["sha256"] != base["sha256"]
    assert client.put(f"/api/versions/{base['id']}", json=edited).status_code == 409
    c = client.get(f"/api/versions/{base['id']}/compare/{sc['id']}").json()
    assert c["diff"]["changes"] == len(edited["demand"]) and c["plan_b"]["orders"] >= c["plan_a"]["orders"]
    new = client.post(f"/api/versions/{sc['id']}/promote", json={}).json()
    assert new["kind"] == "base" and new["parent_id"] == sc["id"]
    assert [v["status"] for v in client.get("/api/versions").json()] == ["superseded", "promoted", "active"]
    assert client.get("/api/versions/V9999").status_code == 404
    same = client.post("/api/compare", json={"a": d, "b": d}).json()
    assert same["diff"]["identical"]
