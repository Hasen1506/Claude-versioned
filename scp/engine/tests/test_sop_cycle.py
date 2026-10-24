"""The monthly S&OP cycle (ENTERPRISE_PLAN 4.1, S/4 guide §4): steps signed in order by their owners, each sign-off
freezing the company as a base version with its figures (volume and revenue against the budget), reopening that
reopens the later steps, and the executive sign-off that closes the month."""
from __future__ import annotations

import copy

import pytest

from scp.model import Dataset
from scp.model.common import BucketSize
from scp.sop import run_sop
from scp.sop.cycle import figures
from scp.versions import get_store

from .test_audit_fixes import client, example, h, join, new_company, signup

DOC = example()


def tiny(**kw) -> dict:
    """One plant selling a pump (50 a unit) and a seal (no price) to one shop, both bought in."""
    doc = {
        "schema_version": "1",
        "settings": {"company_name": "Cycle test", "currency": "EUR", "planning_start": "2026-10-15",
                     "horizon_days": 60, "bucket": "week"},
        "locations": [{"id": "PL", "name": "Plant", "type": "plant"}, {"id": "CU", "name": "Shop", "type": "customer"},
                      {"id": "SU", "name": "Supplier", "type": "supplier"}],
        "products": [{"id": "P1", "name": "Pump", "family": "Pumps", "price": 50, "type": "FG", "standard_cost": 20},
                     {"id": "P2", "name": "Seal", "family": "Spares", "type": "FG", "standard_cost": 2}],
        "location_products": [{"location": "PL", "product": "P1", "on_hand": 10000},
                              {"location": "PL", "product": "P2", "on_hand": 10000}],
        "lanes": [{"id": "L1", "origin": "PL", "destination": "CU", "modes": [{"mode": "truck_ftl", "transit_days": 1}]}],
        "purchasing_sources": [{"id": f"BUY-{p}", "supplier": "SU", "location": "PL", "product": p, "price": c,
                                "lead_time_days": 2} for p, c in (("P1", 20), ("P2", 2))],
        "demand": [{"location": "CU", "product": "P1", "date": "2026-10-15", "qty": 300, "kind": "forecast",
                    "period_days": 30},
                   {"location": "CU", "product": "P1", "date": "2026-11-20", "qty": 40, "kind": "sales_order",
                    "id": "SO1", "price": 45},
                   {"location": "CU", "product": "P2", "date": "2026-11-02", "qty": 7, "kind": "sales_order",
                    "id": "SO2"},
                   {"location": "CU", "product": "P2", "date": "2026-10-01", "qty": 3, "kind": "sales_order",
                    "id": "SO3"}],
        "budgets": [{"month": "2026-10-01", "family": "Pumps", "qty": 620},
                    {"month": "2026-11-01", "product": "P1", "qty": 300},
                    {"month": "2026-12-01", "qty": 310, "revenue": 15500}],
    }
    doc.update(kw)
    return doc


# ------------------------------------------------------------------------------------------------ figures
def test_figures_count_the_budget_for_the_part_of_each_month_in_the_plan_and_price_the_demand():
    f = figures(Dataset.model_validate(tiny()), "demand")
    assert [m.month for m in f.months] == ["2026-10", "2026-11", "2026-12"]
    assert [m.label for m in f.months] == ["from 15 Oct 2026", "Nov 2026", "to 13 Dec 2026"]
    oct_, nov, dec = f.months
    # October: 17 of 31 days in the plan; a family budget without revenue has no revenue budget
    assert oct_.share == pytest.approx(17 / 31, abs=1e-4)
    assert oct_.budget_qty == pytest.approx(620 * 17 / 31, abs=1e-3) and oct_.budget_revenue == 0
    # November: a product's budget without revenue is its units at the product's price
    assert nov.budget_qty == 300 and nov.budget_revenue == 300 * 50
    # December: 13 of 31 days, the company's budget with its own revenue
    assert dec.budget_qty == pytest.approx(310 * 13 / 31, abs=1e-3)
    assert dec.budget_revenue == pytest.approx(15500 * 13 / 31, abs=0.01)
    # demand is what MRP plans: the order of 40 consumes 40 of the forecast of 300, which spreads the 260 left over its
    # 30 days from 15 Oct (17 in October, 13 in November); the order is in November at its own price; the seal has
    # no price, so its units count and its revenue does not
    # an order already past due (SO3, 1 Oct) is due in the first month
    assert oct_.demand_qty == pytest.approx(260 * 17 / 30 + 3, abs=1e-3)
    assert oct_.demand_revenue == pytest.approx(260 * 17 / 30 * 50, abs=0.01)
    assert nov.demand_qty == pytest.approx(260 * 13 / 30 + 40 + 7, abs=1e-3)
    assert nov.demand_revenue == pytest.approx(260 * 13 / 30 * 50 + 40 * 45, abs=0.01)
    assert f.unpriced == ["P2"]
    assert oct_.supply_qty is None and f.fill_rate is None        # the demand review does not solve the plan
    fam = {x.family: x for x in f.families}
    assert fam["Pumps"].demand_qty == pytest.approx(300) and fam["Spares"].demand_qty == 10
    assert fam["Pumps"].budget_qty == pytest.approx(620 * 17 / 31 + 300, abs=1e-3)
    assert fam[""].budget_qty == pytest.approx(310 * 13 / 31, abs=1e-3)     # the company's own budget
    assert f.budgets == 3


def test_supply_figures_are_the_constrained_plan_month_by_month():
    """The supply review's figures are what the capacity plan, solved in months, sells (an independent run)."""
    ds = Dataset.model_validate(DOC)
    f = figures(ds, "supply")
    res = run_sop(ds.model_copy(update={"sop": ds.sop.model_copy(update={"bucket": BucketSize.MONTH})}))
    assert [m.month for m in f.months] == [b.start.strftime("%Y-%m") for b in res.buckets]
    for t, m in enumerate(f.months):
        assert m.supply_qty == pytest.approx(sum(d.sales[t] for d in res.demand), abs=1e-3)
        assert m.demand_qty == pytest.approx(sum(d.demand[t] for d in res.demand), abs=1e-3)
    assert f.fill_rate == res.kpis.fill_rate
    assert sum(m.supply_revenue for m in f.months) == pytest.approx(res.economics.revenue, rel=1e-6)
    assert sum(m.budget_qty for m in f.months) == pytest.approx(sum(x.budget_qty for x in f.families), abs=1e-3)


def test_supply_revenue_counts_priced_sales_only():
    f = figures(Dataset.model_validate(tiny()), "supply")
    assert f.fill_rate == pytest.approx(1.0)
    fam = {x.family: x for x in f.families}
    assert fam["Spares"].supply_qty == pytest.approx(10) and fam["Spares"].supply_revenue == 0
    assert fam["Pumps"].supply_revenue == pytest.approx(260 * 50 + 40 * 45, abs=0.05)
    assert sum(m.supply_revenue for m in f.months) == pytest.approx(260 * 50 + 40 * 45, abs=0.05)


def test_a_capacity_cut_shows_as_supply_below_demand():
    doc = copy.deepcopy(DOC)
    doc["sop"] = {**doc.get("sop", {}), "capacity_factor": 0.2}
    f = figures(Dataset.model_validate(doc), "supply")
    assert f.fill_rate < 0.99 and f.limits
    assert sum(m.supply_qty for m in f.months) < sum(m.demand_qty for m in f.months) - 1


def test_a_demand_lever_scales_the_demand_the_supply_review_shows():
    doc = copy.deepcopy(DOC)
    doc["sop"] = {**doc.get("sop", {}), "demand_factor": 1.5}
    ds = Dataset.model_validate(doc)
    plain = figures(ds, "demand")
    f = figures(ds, "supply")
    res = run_sop(ds.model_copy(update={"sop": ds.sop.model_copy(update={"bucket": BucketSize.MONTH})}))
    for t, (a, b) in enumerate(zip(plain.months, f.months, strict=True)):
        assert b.demand_qty == pytest.approx(a.demand_qty * 1.5, abs=1e-3)
        assert b.demand_qty == pytest.approx(sum(d.demand[t] for d in res.demand), abs=1e-3)
        assert b.demand_revenue == pytest.approx(a.demand_revenue * 1.5, abs=0.05)
    assert any("scaled by 1.5" in n for n in f.notes)


# ------------------------------------------------------------------------------------------------ the cycle
def _cycle(month: str = "2026-10", headers: dict | None = None) -> dict:
    r = client.post("/api/sop/cycles", json={"month": month}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def _sign(c: dict, step: str, doc: dict, note: str = "", headers: dict | None = None):
    return client.post(f"/api/sop/cycles/{c['id']}/steps/{step}/sign", json={"dataset": doc, "note": note},
                       headers=headers or {})


def test_a_cycle_is_signed_step_by_step_and_each_step_freezes_the_company():
    c = _cycle()
    assert c["next"] == "data" and [s["status"] for s in c["steps"]] == ["open"] * 5
    assert client.post("/api/sop/cycles", json={"month": "2026-10"}).status_code == 409      # one per month
    assert client.post("/api/sop/cycles", json={"month": "2026-13"}).status_code == 422

    # out of order: the demand review waits for the data
    r = _sign(c, "demand", DOC)
    assert r.status_code == 409 and "Data comes first" in r.text
    # the data step refuses data with blocking problems
    bad = copy.deepcopy(DOC)
    bad["demand"][0]["product"] = "NO-SUCH"
    r = _sign(c, "data", bad)
    assert r.status_code == 409 and "blocking" in r.text
    assert _sign(c, "data", DOC).status_code == 200

    # the demand review is frozen as it was signed, with its figures
    low = copy.deepcopy(DOC)
    low["demand"] = [d for d in low["demand"] if d["product"] != "KT-15"]
    r = _sign(c, "demand", low, "kettles out")
    assert r.status_code == 200, r.text
    step = r.json()["steps"][1]
    assert step["status"] == "signed" and step["signed_by"] == "this browser" and step["note"] == "kettles out"
    frozen = get_store().get(step["version_id"], "anon:" + __import__("hashlib").sha256(
        b"tests-browser-key-0001").hexdigest()[:32])
    assert frozen.meta.kind == "base" and frozen.meta.name == "S&OP 2026-10 · Demand review"
    assert not any(d.product == "KT-15" for d in frozen.dataset.demand)
    whole = figures(Dataset.model_validate(DOC), "demand")
    assert sum(m["demand_qty"] for m in step["figures"]["months"]) < sum(m.demand_qty for m in whole.months)

    # supply review: the constrained plan; pre-S&OP and the executive step take their minutes
    r = _sign(c, "supply", DOC)
    assert r.status_code == 200 and r.json()["steps"][2]["figures"]["fill_rate"] is not None
    r = _sign(c, "pre", DOC)
    assert r.status_code == 422 and "decided" in r.text
    assert _sign(c, "pre", DOC, "third shift proposed").status_code == 200
    r = _sign(c, "pre", DOC, "again")
    assert r.status_code == 409 and "signed already" in r.text
    r = _sign(c, "exec", DOC, "approved: third shift from November")
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "closed" and done["next"] is None
    assert [x["action"] for x in done["log"]] == ["created"] + ["signed"] * 5 + ["closed"]
    assert len({s["version_id"] for s in done["steps"]}) == 5

    # a closed month lists as closed with five sign-offs
    assert client.get("/api/sop/cycles").json()[0] == {"id": c["id"], "month": "2026-10", "status": "closed",
                                                         "next": None, "signed": 5}


def test_reopening_a_step_reopens_the_later_ones_and_keeps_their_frozen_versions():
    c = _cycle("2026-11")
    for step, note in (("data", ""), ("demand", ""), ("supply", ""), ("pre", "ok"), ("exec", "ok")):
        assert _sign(c, step, DOC, note).status_code == 200
    before = client.get(f"/api/sop/cycles/{c['id']}").json()
    assert client.post(f"/api/sop/cycles/{c['id']}/steps/supply/reopen", json={"note": ""}).status_code == 422
    r = client.post(f"/api/sop/cycles/{c['id']}/steps/supply/reopen", json={"note": "supplier strike"})
    assert r.status_code == 200
    after = r.json()
    assert after["status"] == "open" and after["next"] == "supply"
    assert [s["status"] for s in after["steps"]] == ["signed", "signed", "open", "open", "open"]
    assert [s["version_id"] for s in after["steps"]] == [s["version_id"] for s in before["steps"]]
    assert after["log"][-1]["detail"] == "Supply review, Pre-S&OP, Executive S&OP: supplier strike"
    assert client.post(f"/api/sop/cycles/{c['id']}/steps/pre/reopen", json={"note": "x"}).status_code == 409
    # signed again: a new frozen version
    r = _sign(c, "supply", DOC)
    assert r.json()["steps"][2]["version_id"] != before["steps"][2]["version_id"]
    # a cycle with a sign-off on record cannot be deleted; an empty one can
    assert client.delete(f"/api/sop/cycles/{c['id']}").status_code == 409
    empty = _cycle("2027-01")
    assert [x["month"] for x in client.delete(f"/api/sop/cycles/{empty['id']}").json()] == ["2026-11"]


def test_figures_preview_records_nothing():
    r = client.post("/api/sop/figures", json={"dataset": DOC, "step": "demand"})
    assert r.status_code == 200 and r.json()["budgets"] == 12
    assert client.post("/api/sop/figures", json={"dataset": DOC, "step": "nope"}).status_code == 404
    assert client.get("/api/sop/cycles").json() == []


# ------------------------------------------------------------------------------------------------ owners
@pytest.fixture
def team():
    owner, planner, demand, viewer = (signup(e) for e in ("own@cy.example", "plan@cy.example", "dem@cy.example",
                                                          "view@cy.example"))
    cid = new_company(owner, copy.deepcopy(DOC))
    join(owner, cid, planner, "plan@cy.example", "planner")
    join(owner, cid, demand, "dem@cy.example", "planner")
    join(owner, cid, viewer, "view@cy.example", "viewer")
    return owner, planner, demand, viewer, cid


def _owner(c: dict, step: str, email: str, headers: dict):
    return client.put(f"/api/sop/cycles/{c['id']}/steps/{step}/owner", json={"owner": email}, headers=headers)


def test_in_a_company_each_step_is_signed_by_its_owner_and_owners_carry_over(team):
    owner, planner, demand, viewer, cid = team
    ho, hp, hd, hv = (h(t, cid) for t in (owner, planner, demand, viewer))
    assert client.post("/api/sop/cycles", json={"month": "2026-10"}, headers=hv).status_code == 403
    c = _cycle("2026-10", ho)
    # only an owner of the company says who owns a step, and only a member who may change the company
    assert _owner(c, "demand", "dem@cy.example", hp).status_code == 403
    assert _owner(c, "demand", "nobody@cy.example", ho).status_code == 422
    assert _owner(c, "demand", "view@cy.example", ho).status_code == 422
    assert _owner(c, "demand", "DEM@cy.example", ho).json()["steps"][1]["owner"] == "dem@cy.example"
    assert _owner(c, "supply", "plan@cy.example", ho).status_code == 200

    # no owner: anyone who may change the company signs (the data step), never a viewer
    assert _sign(c, "data", DOC, headers=hv).status_code == 403
    r = _sign(c, "data", DOC, headers=hp)
    assert r.status_code == 200 and r.json()["steps"][0]["signed_by"] == "plan@cy.example"
    # an owned step: its owner, not another planner
    r = _sign(c, "demand", DOC, headers=hp)
    assert r.status_code == 403 and "dem@cy.example's to sign" in r.text
    assert _sign(c, "demand", DOC, headers=hd).status_code == 200
    assert _sign(c, "supply", DOC, headers=hp).status_code == 200
    assert _sign(c, "pre", DOC, "agreed", headers=hd).status_code == 200
    # the executive step without an owner takes an owner of the company
    r = _sign(c, "exec", DOC, "approved", headers=hp)
    assert r.status_code == 403 and "owner of the company" in r.text
    assert _sign(c, "exec", DOC, "approved", headers=ho).json()["status"] == "closed"
    # only the step's owner (or a company owner) reopens it
    assert client.post(f"/api/sop/cycles/{c['id']}/steps/demand/reopen", json={"note": "x"},
                       headers=hp).status_code == 403
    # the frozen versions belong to the company
    names = [v["name"] for v in client.get("/api/versions", headers=ho).json()]
    assert "S&OP 2026-10 · Executive S&OP" in names

    # next month's cycle starts with the same owners; other companies and browsers do not see it
    nxt = _cycle("2026-11", ho)
    assert [s["owner"] for s in nxt["steps"]] == ["", "dem@cy.example", "plan@cy.example", "", ""]
    assert client.get("/api/sop/cycles").json() == []
    assert client.get(f"/api/sop/cycles/{c['id']}").status_code == 404
