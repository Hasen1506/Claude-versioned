"""Enterprise 8.2: inventory policy in one table (docs/CONFORMANCE.md §1). Every figure is worked by hand from the
textbook definitions (Silver, Pyke & Thomas): ABC by annual usage value, XYZ by the weekly coefficient of variation,
SS = z·σ_L for a cycle service level, the reorder point s = d̄·(L + R) + SS, and the service achieved as the share
of the place's customer orders delivered in full by the requested date."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.inventory.policy import PolicyError, apply_policy, policy_view

from .factory import START, base, ds

client = TestClient(app)
Z95, Z98 = 1.6448536, 2.0537489


def shop() -> dict:
    """Plant P makes A from 2 B and 1 C (B and C bought); customer K orders 280 A over the 28 days: 10 a day.
    Values are set, so the usage is: A 10 × 365 × 200 = 730,000; B 20 × 365 × 10 = 73,000; C 10 × 365 × 5 = 18,250."""
    d = base()
    d["locations"].append({"id": "K", "name": "Kumar Stores", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["demand"] = [{"location": "K", "product": "A", "date": START, "qty": 280, "kind": "forecast", "period_days": 28}]
    lp = {x["product"]: x for x in d["location_products"]}
    lp["A"].update(unit_cost=200, mrp_type="reorder_point", reorder_point=50,
                   lot_sizing={"policy": "FIXED", "fixed_qty": 100},
                   safety_stock={"method": "service_level", "service_level": 0.95, "demand_cv": 0.2})
    lp["B"].update(unit_cost=10)
    lp["C"].update(unit_cost=5)
    start = date.fromisoformat(START)
    closed = []
    for i, late in enumerate([False, False, False, True]):
        due = start - timedelta(days=20 - i)
        closed.append({"kind": "sales", "id": f"SO-{i}", "location": "K", "product": "A", "counterparty": "P",
                       "ordered_qty": 10, "delivered_qty": 10, "due_date": due.isoformat(),
                       "first_delivery": (due + timedelta(days=2 if late else 0)).isoformat(),
                       "last_delivery": (due + timedelta(days=2 if late else 0)).isoformat(),
                       "closed_on": (due + timedelta(days=2)).isoformat()})
    # one delivered on time but short (6 of 10), and a transfer out of P, which is not a customer's order
    due = start - timedelta(days=10)
    closed.append({"kind": "sales", "id": "SO-short", "location": "K", "product": "A", "counterparty": "P",
                   "ordered_qty": 10, "delivered_qty": 6, "due_date": due.isoformat(), "first_delivery": due.isoformat(),
                   "last_delivery": due.isoformat(), "closed_on": due.isoformat()})
    closed.append({"kind": "transfer", "id": "STO-1", "location": "K", "product": "A", "counterparty": "P",
                   "ordered_qty": 10, "delivered_qty": 10, "due_date": due.isoformat(), "first_delivery": due.isoformat(),
                   "last_delivery": due.isoformat(), "closed_on": due.isoformat()})
    d["closed_orders"] = closed
    return d


def rows(v) -> dict:
    return {r.product: r for r in v.rows}


def test_each_product_is_classed_by_usage_value_and_variability():
    v = policy_view(ds(shop()))
    assert v.ok
    r = rows(v)
    assert {p: x.usage_value for p, x in r.items()} == pytest.approx({"A": 730_000, "B": 73_000, "C": 18_250})
    # A opens the ranking; B starts at 730,000 / 821,250 = 0.889 (past 0.8, before 0.95); C at 803,000 / 821,250 = 0.978
    assert (r["A"].abc, r["B"].abc, r["C"].abc) == ("A", "B", "C")
    assert r["A"].cv == pytest.approx(0.2) and r["A"].xyz == "X" and r["A"].cv_from == "set on the product"
    assert r["A"].suggested == 0.98                     # the AX cell
    assert [c.cell for c in v.cells] == ["AX", "BX", "CX"]


def test_the_policy_reads_as_the_textbook_rule_with_its_safety_stock_and_reorder_point():
    r = rows(policy_view(ds(shop())))["A"]
    assert r.rule == "sQ" and r.rule_label == "Reorder point, fixed quantity (s, Q)" and r.order_qty == 100
    assert r.lead_time_days == pytest.approx(2.0) and r.mean_daily == pytest.approx(10.0)
    # σ of daily demand = 0.2 × 10 × √7 / √7 per day ⇒ variance 0.2² × 10² × 7 = 28 a day; over L = 2 days: √56
    ss = Z95 * math.sqrt(2 * 28)
    assert r.safety_stock == pytest.approx(ss, rel=1e-6)
    assert r.safety_stock_value == pytest.approx(ss * 200, rel=1e-6)
    assert r.suggested_reorder_point == pytest.approx(10 * 2 + ss, rel=1e-6)          # 32.31
    assert r.target == 0.95 and r.target_kind == "cycle" and r.target_from == "product"
    assert any("more than 10 %" in n for n in r.notes)                                  # 50 against 32.31


def test_a_review_period_adds_its_days_to_the_exposure_and_the_reorder_point():
    d = shop()
    d["location_products"][0]["safety_stock"]["review_period_days"] = 5
    r = rows(policy_view(ds(d)))["A"]
    ss = Z95 * math.sqrt(7 * 28)                        # L + R = 7 days
    assert r.review_days == 5
    assert r.safety_stock == pytest.approx(ss, rel=1e-6)
    assert r.suggested_reorder_point == pytest.approx(10 * 7 + ss, rel=1e-6)


def test_the_service_achieved_is_the_share_of_orders_in_full_by_the_requested_date():
    v = policy_view(ds(shop()))
    r = rows(v)["A"]
    # five customer orders: three on time in full, one late, one short; the transfer is not counted
    assert (r.orders, r.served, r.achieved) == (5, 3, 0.6)
    assert v.short_of_target == 1 and v.below_suggestion == 1 and v.reorder_off == 1
    ax = next(c for c in v.cells if c.cell == "AX")
    assert (ax.rows, ax.orders, ax.served, ax.targets) == (1, 5, 3, [0.95])


def test_an_order_up_to_rule_and_a_product_without_safety_stock_say_so():
    d = shop()
    d["location_products"][0].update(lot_sizing={"policy": "MIN_MAX"}, max_stock=300)
    r = rows(policy_view(ds(d)))
    assert r["A"].rule == "sS" and r["A"].order_up_to == 300
    assert r["B"].method == "none" and r["B"].target is None and r["B"].rule == "mrp"
    assert any("no safety stock" in n for n in r["B"].notes)


def test_a_segment_is_given_its_suggested_target_and_the_reorder_point_follows():
    d, msg = apply_policy(ds(shop()), [("P", "A")], service_level="suggested", reorder_point="suggested")
    lp = d.location_product_by_key[("P", "A")]
    assert lp.safety_stock.service_level == 0.98
    # the reorder point is suggested from the policy as it stood: 20 + 1.645 √56
    assert lp.reorder_point == pytest.approx(round(20 + Z95 * math.sqrt(56), 2))
    assert msg == "Set 1 service target, 1 reorder point on 1 product at a place."
    r = rows(policy_view(d))["A"]
    assert r.safety_stock == pytest.approx(Z98 * math.sqrt(56), rel=1e-6)
    assert r.suggested_reorder_point == pytest.approx(20 + Z98 * math.sqrt(56), rel=1e-6)


def test_several_products_get_one_method_and_what_cannot_change_is_named():
    d, msg = apply_policy(ds(shop()), [("P", "B"), ("P", "C")], method="service_level", service_level=0.9,
                          review_period_days=7, reorder_point="suggested")
    for p in ("B", "C"):
        ss = d.location_product_by_key[("P", p)].safety_stock
        assert (ss.method.value, ss.service_level, ss.review_period_days) == ("service_level", 0.9, 7)
    assert "Left as they were, not planned by reorder point: B at P, C at P." in msg
    # a target means nothing to a product whose safety stock is not set by one (B has none): it is left, and said
    d2, msg2 = apply_policy(ds(shop()), [("P", "A"), ("P", "B")], service_level="suggested")
    assert d2.location_product_by_key[("P", "B")].safety_stock.service_level is None
    assert msg2 == ("Set 1 service target on 2 products at places. Left as they were, safety stock not set by a "
                    "service target: B at P.")
    # many left alone: five named, the rest counted
    d3 = shop()
    for i in range(7):
        d3["products"].append({"id": f"X{i}", "type": "RM"})
        d3["location_products"].append({"location": "P", "product": f"X{i}", "on_hand": 1})
    with pytest.raises(PolicyError, match=r"^nothing to change: X0 at P, X1 at P, X2 at P, X3 at P, X4 at P and 2 more \(safety"):
        apply_policy(ds(d3), [("P", f"X{i}") for i in range(7)], service_level=0.9)
    with pytest.raises(PolicyError, match="from 50 % to below 100 %"):
        apply_policy(ds(shop()), [("P", "A")], service_level=1.2)
    with pytest.raises(PolicyError, match="needs its quantity"):
        apply_policy(ds(shop()), [("P", "A")], method="fixed")
    with pytest.raises(PolicyError, match="there is no P Z"):
        apply_policy(ds(shop()), [("P", "Z")], service_level=0.9)


def test_the_api_shows_the_table_and_applies_a_policy():
    r = client.post("/api/inventory/policy", json=shop())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and {x["product"] for x in body["rows"]} == {"A", "B", "C"}
    r = client.post("/api/inventory/policy/apply", json={"dataset": shop(), "keys": ["P|B"], "method": "days_of_supply",
                                                         "days": 3})
    assert r.status_code == 200, r.text
    lp = next(x for x in r.json()["dataset"]["location_products"] if x["product"] == "B")
    assert lp["safety_stock"]["method"] == "days_of_supply" and lp["safety_stock"]["days"] == 3
    assert r.json()["message"] == "Set 1 safety-stock method on 1 product at a place."
    r = client.post("/api/inventory/policy/apply", json={"dataset": shop(), "keys": ["P|B"], "method": "fixed"})
    assert r.status_code == 422 and "needs its quantity" in r.json()["detail"]
