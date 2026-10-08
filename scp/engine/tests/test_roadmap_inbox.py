"""Roadmap F: an exception inbox ranked by money at risk (UX audit of 7 Oct 2026, section 4).

The worklist sorted by status, breach, severity and age; a week-old note about 3 units outranked a new 200-unit
late order. Each item now carries money at risk (worked out from the data, with its basis in words), the customer it
concerns and one action with what it protects and costs; the inbox is ranked by that money.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.tower import run_tower
from scp.tower.money import inbox_order, price_items
from scp.tower.result import WorkItem

from .factory import load_example

D0 = dt.date(2026, 1, 5)


def item(code: str, *, qty: float | None = None, location: str | None = None, product: str | None = None,
         resource: str | None = None, order_id: str | None = None, age: int = 0, breached: bool = False,
         status: str = "open", category: str = "coverage", severity: str = "warning") -> WorkItem:
    key = "|".join((code, location or "", product or "", resource or "", order_id or ""))
    return WorkItem(id=key, key=key, code=code, category=category, severity=severity, message=code, location=location,
                    product=product, resource=resource, order_id=order_id, qty=qty, owner="Unassigned",
                    owner_source="default", status=status, first_seen=D0, last_seen=D0, age_days=age,
                    breached=breached)


@pytest.fixture
def ds():
    return load_example("kitchenware_network")


def test_late_demand_is_priced_at_the_selling_price(ds):
    w = item("DEMAND_AT_RISK", qty=10, location="CUS-ECOM", product="KT-15")
    price_items(ds, None, [w])
    assert w.money_at_risk == pytest.approx(10 * 1190.0)
    assert "selling price" in w.money_basis and w.customer == "CUS-ECOM"
    assert w.action is not None and w.action.protects == pytest.approx(w.money_at_risk)


def test_the_late_sale_share_scales_it(ds):
    ds.tower.late_revenue_factor = 0.25
    w = item("PROMISE_LATE", qty=10, location="CUS-ECOM", product="KT-15")
    price_items(ds, None, [w])
    assert w.money_at_risk == pytest.approx(10 * 1190.0 * 0.25) and "0.25 late-sale share" in w.money_basis


def test_excess_stock_costs_a_year_of_carrying_it(ds):
    w = item("NO_DEMAND_STOCK", qty=100, location="PLT-PUNE", product="RM-STAMP", category="inventory")
    price_items(ds, None, [w])
    assert w.money_at_risk == pytest.approx(100 * 118.0 * ds.settings.carrying_rate)
    assert w.action is not None and w.action.kind == "push_out"


def test_capacity_is_priced_at_the_overtime_rate_and_the_action_says_what_it_costs(ds):
    w = item("CAPACITY_OVERLOAD", qty=4, resource="PUNE-L1", category="capacity", severity="error")
    price_items(ds, None, [w])
    assert w.money_at_risk == pytest.approx(4 * 2900.0)
    assert w.action is not None and w.action.kind == "overtime" and w.action.costs == pytest.approx(4 * 2900.0)


def test_a_quicker_second_supplier_is_suggested_with_its_extra_cost(ds):
    fast = ds.purchasing_sources[1].model_copy(update={"id": "PIR-STAMP-FAST", "supplier": "SUP-COPPER", "price": 130.0,
                                                       "lead_time_days": 2.0})
    ds.purchasing_sources.append(fast)
    w = item("STOCKOUT", qty=50, location="PLT-PUNE", product="RM-STAMP", severity="error")
    price_items(ds, None, [w])
    assert w.action is not None and w.action.kind == "switch_supplier" and "SUP-COPPER" in w.action.label
    assert w.action.costs == pytest.approx((130.0 - 118.0) * 50)


def test_money_owed_is_its_open_amount_and_unpriced_items_say_so(ds):
    a = item("RECEIVABLE_OVERDUE", qty=12345.5, category="receivables")
    b = item("FOLLOW_UP", location="PLT-PUNE", category="inventory")
    price_items(ds, None, [a, b])
    assert a.money_at_risk == pytest.approx(12345.5) and a.action.kind == "chase"
    assert b.money_at_risk == 0 and "not priced" in b.money_basis


def test_the_inbox_ranks_by_money_not_by_age_or_breach(ds):
    old = item("BELOW_SAFETY_STOCK", qty=3, location="PLT-PUNE", product="RM-STAMP", age=30, breached=True)
    big = item("PROMISE_LATE", qty=200, location="CUS-ECOM", product="KT-15", order_id="X")
    mid = item("DEMAND_AT_RISK", qty=5, location="CUS-ECOM", product="MG-500")
    done = item("DEMAND_AT_RISK", qty=999, location="CUS-ECOM", product="MG-750", status="resolved")
    price_items(ds, None, [old, big, mid, done])
    assert inbox_order([old, big, mid, done]) == [big.id, mid.id, old.id]     # resolved ones are not in the inbox


def test_run_tower_fills_the_inbox_and_its_total(ds):
    r = run_tower(ds, record=False)
    by = {w.id: w for w in r.worklist}
    money = [by[i].money_at_risk for i in r.inbox]
    assert money == sorted(money, reverse=True) and money[0] > 0
    assert r.money_at_risk == pytest.approx(sum(money), abs=0.05)
    assert all(by[i].money_basis for i in r.inbox)
    assert set(r.inbox) == {w.id for w in r.worklist if w.status in ("open", "acknowledged")}


def test_the_api_answers_with_the_inbox():
    c = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-inbox-1"})
    doc = load_example("kitchenware_network").model_dump(mode="json")
    r = c.post("/api/tower", json=doc)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inbox"] and body["money_at_risk"] > 0
    first = next(w for w in body["worklist"] if w["id"] == body["inbox"][0])
    assert first["money_at_risk"] > 0 and first["action"]["label"]


def test_the_factor_is_validated():
    doc = load_example("kitchenware_network").model_dump(mode="json")
    doc["tower"]["late_revenue_factor"] = 2
    r = TestClient(app).post("/api/validate", json=doc)
    assert r.status_code == 422 or any("late_revenue_factor" in str(i) for i in r.json().get("issues", []))
