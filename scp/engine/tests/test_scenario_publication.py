"""An approved scenario and its live company revision share one commit."""
from __future__ import annotations

import json

import pytest

from scp.companies import get_companies
from scp.promise import commit
from scp.versions.store import Store, set_store

from .factory import ds, lp
from .test_backup_postgres import pg_databases as pg_databases
from .test_companies import client, h, join, new_company, signup
from .test_promise import net, so


def _success(response):
    assert response.status_code == 200, response.text
    return response.json()


def _workflow():
    raw = net(bop_segments=[{"name": "Replan", "strategy": "redistribute"}])
    lp(raw, "D", "A")["on_hand"] = 40
    raw["demand"] = [so("C1", 60, "2026-01-10", "HIGH", priority=1), so("C2", 40, "2026-01-10", "LOW", priority=5)]
    raw["purchasing_sources"].append({"id": "PURCHASE", "supplier": "S", "location": "D", "product": "A",
                                      "price": 10, "lead_time_days": 1})
    raw["purchase_orders"] = [{"id": "PO-1", "supplier": "S", "location": "D", "order_date": "2026-01-05"}]
    raw["receipts"] = [{"id": "PO-1-10", "po": "PO-1", "kind": "purchase", "location": "D", "product": "A",
                        "qty": 60, "due_date": "2026-01-09", "price": 10, "source": "PURCHASE"}]
    baseline, _ = commit(ds(raw))
    owner, planner = signup("owner@publication.example"), signup("planner@publication.example")
    cid = new_company(owner, baseline.model_dump(mode="json"))
    join(owner, cid, "planner@publication.example", "planner")
    opened = _success(client.get(f"/api/companies/{cid}", headers=h(owner)))
    base = _success(client.post("/api/versions", headers=h(owner, cid),
                                json={"name": "Live baseline", "dataset": opened["dataset"]}))
    draft = _success(client.post(f"/api/versions/{base['id']}/branch", headers=h(planner, cid), json={"name": "Delay"}))
    change = baseline.model_dump(mode="json")
    change["receipts"][0].update(confirmed_date="2026-01-14", confirmed_qty=60)
    reviewed = _success(client.put(f"/api/versions/{draft['id']}", json=change,
                                   headers={**h(planner, cid), "If-Match": json.dumps(draft["sha256"])}))
    owner_headers = {**h(owner, cid), "If-Match": json.dumps(reviewed["sha256"])}
    path = f"/api/companies/{cid}/scenarios/{draft['id']}"
    preview = _success(client.post(f"{path}/publication-preview", headers=owner_headers))
    request = {field: preview[field] for field in ("base_revision", "plan_sha256")}
    return cid, owner, planner, reviewed, path, owner_headers, preview, request


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_publication_releases_reviewed_plan_once_and_reaches_two_users(backend, request, tmp_path, monkeypatch):
    path = tmp_path / "publish.db" if backend == "sqlite" else request.getfixturevalue("pg_databases")()
    store = Store(path)
    set_store(store)
    try:
        cid, owner, planner, reviewed, path, headers, preview, payload = _workflow()
        assert [(o["order"], [line["qty"] for line in o["lines"]]) for o in preview["orders"]] == [
            ("HIGH", [40, 20]), ("LOW", [40]),
        ]
        assert client.post(f"{path}/publish", headers={**h(planner), "If-Match": headers["If-Match"]},
                           json=payload).status_code == 403
        assert client.post(f"{path}/publish", headers=headers,
                           json={**payload, "plan_sha256": "0" * 64}).status_code == 412

        # Promotion, company data and command receipt must all roll back on a write failure.
        with monkeypatch.context() as failing:
            def fail_log(*args):
                raise RuntimeError("publication audit unavailable")
            failing.setattr(get_companies(), "_log", fail_log)
            with pytest.raises(RuntimeError, match="publication audit unavailable"):
                client.post(f"{path}/publish", headers=headers, json=payload)
        assert store.get(reviewed["id"], cid).meta.status == "active"
        assert _success(client.get(f"/api/companies/{cid}", headers=h(planner)))["meta"]["revision"] == 1

        result = _success(client.post(f"{path}/publish", headers=headers, json=payload))
        assert result["revision"] == 2 and not result["duplicate"]
        assert result["result"]["version"]["sha256"] == preview["plan_sha256"]
        for person in (owner, planner):
            live = _success(client.get(f"/api/companies/{cid}", headers=h(person)))
            assert live["meta"]["revision"] == 2
            assert live["dataset"]["receipts"][0]["confirmed_date"] == "2026-01-14"
            assert [(c["order"], c["date"], c["qty"]) for c in live["dataset"]["confirmations"]] == [
                ("HIGH", "2026-01-10", 40), ("HIGH", "2026-01-15", 20), ("LOW", "2026-01-15", 40),
            ]
        saved = _success(client.get(f"/api/companies/{cid}/commands", params={"id": result["id"]}, headers=h(owner)))
        assert saved["kind"] == "scenario_publication" and saved["parameters"]["scenario_sha256"] == reviewed["sha256"]
        assert saved["result"] == result["result"]
        replay = _success(client.post(f"{path}/publish", headers=headers, json=payload))
        assert replay["duplicate"] and replay["revision"] == 2 and replay["result"] == result["result"]
        assert replay["company"]["meta"]["revision"] == 2
    finally:
        store.db.close()


def test_publication_rejects_a_stale_scenario_and_intervening_live_save():
    cid, owner, planner, reviewed, path, headers, _, payload = _workflow()
    version_path = f"/api/versions/{reviewed['id']}"
    draft = _success(client.get(version_path, headers=h(planner, cid)))["dataset"]
    draft["receipts"][0]["confirmed_date"] = "2026-01-15"
    modified = _success(client.put(version_path, json=draft, headers={**headers, **h(planner, cid)}))
    assert client.post(f"{path}/publish", headers=headers, json=payload).status_code == 412
    headers["If-Match"] = json.dumps(modified["sha256"])
    preview = _success(client.post(f"{path}/publication-preview", headers=headers))
    company_path = f"/api/companies/{cid}"
    live = _success(client.get(company_path, headers=h(owner)))
    live["dataset"]["settings"]["company_name"] = "Intervening live save"
    _success(client.put(company_path, headers=h(owner), json={"dataset": live["dataset"], "base_revision": 1}))
    payload = {field: preview[field] for field in ("base_revision", "plan_sha256")}
    assert client.post(f"{path}/publish", headers=headers, json=payload).status_code == 409
    assert client.post(f"{path}/publication-preview", headers=headers).status_code == 409
    current = _success(client.get(company_path, headers=h(planner)))
    assert current["dataset"]["settings"]["company_name"] == "Intervening live save"
    assert current["meta"]["revision"] == 2 and current["dataset"]["receipts"][0]["confirmed_date"] is None
