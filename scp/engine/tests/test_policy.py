"""Enterprise 8.2: inventory policy in one table (docs/CONFORMANCE.md §1). Every figure is worked by hand from the
textbook definitions (Silver, Pyke & Thomas): ABC by annual usage value, XYZ by the weekly coefficient of variation,
SS = z·σ_L for a cycle service level, the reorder point s = d̄·(L + R) + SS, and the service achieved measured as the
target is set: replenishment cycles without a miss for a cycle level, units by the requested date for a fill rate."""
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


def receipts(d: dict, *days: int) -> dict:
    start = date.fromisoformat(START)
    d["movements"] = [{"id": f"GR-{i}", "date": (start - timedelta(days=n)).isoformat(), "type": "receipt",
                       "location": "P", "product": "A", "qty": 100} for i, n in enumerate(days)]
    return d


def test_the_service_achieved_against_a_cycle_target_counts_replenishment_cycles_without_a_miss():
    # receipts at P 21, 18 and 14 days before the start cut the window into cycles; the orders were due 20, 19 (on
    # time), 18 (on time), 17 (late) and 10 days before (short): [−21, −18) clean, [−18, −14) late, [−14, 0) short,
    # and the time before −21 had no order. 1 of 3 cycles, against a 95 % cycle target
    v = policy_view(ds(receipts(shop(), 21, 18, 14)))
    r = rows(v)["A"]
    assert (r.orders, r.served) == (5, 3)                 # the transfer is not counted
    assert (r.achieved_in, r.achieved_of, r.achieved_ok) == ("cycles", 3, 1)
    assert r.achieved == pytest.approx(1 / 3)
    assert v.short_of_target == 1 and v.below_suggestion == 1 and v.reorder_off == 1
    ax = next(c for c in v.cells if c.cell == "AX")
    assert (ax.rows, ax.orders, ax.served, ax.targets) == (1, 5, 3, [0.95])
    # no receipt in the window: the cycles cannot be told apart, so nothing is measured, and the row says why
    v = policy_view(ds(shop()))
    r = rows(v)["A"]
    assert (r.achieved_in, r.achieved_of, r.achieved_ok, r.achieved) == ("cycles", 0, 0, None)
    assert any("cannot be told apart" in n for n in r.notes) and (v.short_of_target, v.not_measured) == (0, 1)


def test_the_service_achieved_against_a_fill_rate_counts_the_units_there_by_the_requested_date():
    d = shop()
    d["location_products"][0]["safety_stock"]["method"] = "fill_rate"
    r = rows(policy_view(ds(d)))["A"]
    # 10 + 10 + 10 on time, the late order's 10 after the date, the short one's 6 on time: 36 of 50
    assert (r.target_kind, r.achieved_in, r.achieved_of, r.achieved_ok) == ("fill", "units", 50, 36)
    assert r.achieved == pytest.approx(0.72)
    # a delivery in the journal splits an order: 4 of the late order's 10 left on the requested date
    due = date.fromisoformat(START) - timedelta(days=17)
    d["movements"] = [{"id": "GI-1", "date": due.isoformat(), "type": "sale", "location": "P", "product": "A",
                       "qty": 4, "reference": "SO-3"},
                      {"id": "GI-2", "date": (due + timedelta(days=2)).isoformat(), "type": "sale", "location": "P",
                       "product": "A", "qty": 6, "reference": "SO-3"}]
    r = rows(policy_view(ds(d)))["A"]
    assert (r.achieved_of, r.achieved_ok) == (50, 40)


def test_with_no_target_the_service_achieved_is_the_share_of_orders_in_full_on_time():
    d = shop()
    d["location_products"][0]["safety_stock"] = {"method": "fixed", "qty": 20}
    r = rows(policy_view(ds(d)))["A"]
    assert (r.target, r.achieved_in, r.achieved_of, r.achieved_ok, r.achieved) == (None, "orders", 5, 3, 0.6)


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
    # the reorder point is suggested from the policy as it now is, the new target's: 20 + 2.054 √56 (not 1.645's)
    assert lp.reorder_point == pytest.approx(round(20 + Z98 * math.sqrt(56), 2))
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


def weekly(review: float = 7, **kw) -> dict:
    """B bought with a 3-day lead time, 30 on hand, 10 used every day for the 28 days, a reorder point of 20 and no
    safety stock. The plan starts on Monday 5 January, so a weekly review falls on the 5th, 12th, 19th and 26th."""
    d = base()
    d["products"] = [{"id": "B", "type": "RM"}]
    d["location_products"] = [{"location": "P", "product": "B", "on_hand": 30, "mrp_type": "reorder_point",
                               "reorder_point": 20, "lot_sizing": {"policy": "L4L"},
                               "safety_stock": {"method": "none", "review_period_days": review}, **kw}]
    d["production_sources"], d["resources"] = [], []
    d["purchasing_sources"] = d["purchasing_sources"][:1]
    start = date.fromisoformat(START)
    d["demand"] = [{"location": "P", "product": "B", "date": (start + timedelta(days=i)).isoformat(), "qty": 10,
                    "kind": "forecast"} for i in range(28)]
    return d


def orders(d: dict) -> list[tuple[str, str, float]]:
    from scp.plan import run_mrp
    return [(o.start_date.isoformat(), o.available_date.isoformat(), o.qty) for o in run_mrp(ds(d)).orders]


def test_a_reorder_point_with_a_review_period_orders_on_review_days_only():
    # continuous review: an order of 10 each day the stock would fall under 20
    assert len(orders(weekly(0))) == 27
    # every 7 days (R, s, Q) with lot-for-lot: short on the 6th (10 left); the only review before is the 5th, whose order
    # arrives the 8th (late, said); it covers until the next review's order can arrive (the 15th): 10 a day to the
    # 14th leaves −70, so 90. Then short on the 15th: the 12th's order arrives that day and covers to the 22nd (70);
    # the same from the 19th; the 26th's covers the 29th to the end of the plan on 1 February (40)
    assert orders(weekly()) == [("2026-01-05", "2026-01-08", 90), ("2026-01-12", "2026-01-15", 70),
                                ("2026-01-19", "2026-01-22", 70), ("2026-01-26", "2026-01-29", 40)]
    from scp.plan import run_mrp
    late = [e for e in run_mrp(ds(weekly())).exceptions if e.code == "REVIEW_LATE"]
    assert len(late) == 1 and "the first review that can order it is 2026-01-05" in late[0].message
    # fixed lots of 50: what is short is ordered in whole lots on the same review days (100, 100, 50, 50)
    q = orders(weekly(lot_sizing={"policy": "FIXED", "fixed_qty": 50}))
    assert [(s, n) for s, _, n in q] == [("2026-01-05", 50), ("2026-01-05", 50), ("2026-01-12", 50),
                                         ("2026-01-12", 50), ("2026-01-19", 50), ("2026-01-26", 50)]


def test_order_up_to_fills_to_the_maximum_on_the_day_the_order_arrives():
    # (R, s, S), S = 120: the 5th's order arrives the 8th, when the stock would be 30 − 40 = −10: 130 brings it to 120.
    # From 120 on the 8th the stock is under 20 on the 19th; the 12th's order arrives the 15th, when 50 are left: 70
    q = orders(weekly(lot_sizing={"policy": "MIN_MAX"}, max_stock=120))
    assert q == [("2026-01-05", "2026-01-08", 130), ("2026-01-12", "2026-01-15", 70), ("2026-01-19", "2026-01-22", 70)]
    from scp.plan import run_mrp
    assert not [e for e in run_mrp(ds(weekly(lot_sizing={"policy": "MIN_MAX"}, max_stock=120))).exceptions
                if e.code == "EXCESS_STOCK"]


def test_reviews_fall_on_the_day_given_and_the_policy_names_the_rule():
    # reviews every 7 days from a Wednesday: the 7th, 14th, … The 7th's order (arriving the 10th) is the first
    q = orders(weekly(safety_stock={"method": "none", "review_period_days": 7, "review_from": "2025-12-31"}))
    assert [s for s, _, _ in q] == ["2026-01-07", "2026-01-14", "2026-01-21", "2026-01-28"]
    r = rows(policy_view(ds(weekly())))["B"]
    assert r.rule == "RsQ" and r.rule_label == "Periodic review, reorder point, fixed quantity (R, s, Q)"
    assert r.next_review == date(2026, 1, 5)
    # a review period on time-phased MRP only widens the safety stock: said
    d = weekly()
    d["location_products"][0].update(mrp_type="deterministic")
    assert any("orders whenever it is short" in n for n in rows(policy_view(ds(d)))["B"].notes)
    # given through the policy step
    d2, msg = apply_policy(ds(weekly(0)), [("P", "B")], review_period_days=14, review_from=date(2026, 1, 8))
    ss = d2.location_product_by_key[("P", "B")].safety_stock
    assert (ss.review_period_days, ss.review_from) == (14, date(2026, 1, 8))
    assert msg == "Set 1 review period on 1 product at a place."


def test_the_review_chosen_is_the_last_whose_order_arrives_in_time_when_lead_times_differ():
    # a weekday calendar, a 1-day lead time and reviews every 10 days from 1 January 2024: Saturday 10 January, then
    # Tuesday 20th, Friday 30th. An order from the Saturday review goes out on Monday and arrives Tuesday 13th, so
    # that review's lead time is 3 days, the Tuesday one's only 1: what is short on Wednesday 21st comes from the
    # Tuesday 20th review (arriving the 21st), not from the Saturday's, which a 3-day estimate would pick
    d = weekly(10)
    d["calendars"][0]["workdays"] = [0, 1, 2, 3, 4]
    d["purchasing_sources"][0]["lead_time_days"] = 1
    q = orders(d)
    assert [(s, a) for s, a, _ in q] == [("2026-01-12", "2026-01-13"), ("2026-01-20", "2026-01-21"),
                                         ("2026-01-30", "2026-01-31")]


def test_a_class_is_put_on_a_periodic_reorder_point_in_one_step():
    # B and C on time-phased MRP, put on a reorder point reviewed every 7 days with a 90 % target. Their reorder points
    # come from the policy as it then is. B: 20 a day, 3 days' lead time, CV 0.3 set on the product (a week's σ is
    # 0.3 × 140 = 42, so σ_d² = 42² / 7 = 252 a day): SS = z(0.9) √(10 × 252) and s = 20 × 10 + SS. C has no demand: no reorder point to
    # order at, so it stays on MRP; nor any variability to size a target with, so its safety stock stays: both named
    d = shop()
    d["location_products"][1]["safety_stock"] = {"method": "none", "demand_cv": 0.3}
    d["demand"] = [{"location": "K", "product": "A", "date": START, "qty": 280, "kind": "forecast", "period_days": 28}]
    d["production_sources"][0]["components"] = [{"product": "B", "qty": 2}]
    out, msg = apply_policy(ds(d), [("P", "B"), ("P", "C")], method="service_level", service_level=0.9,
                            review_period_days=7, rule="reorder_point")
    b, c = out.location_product_by_key[("P", "B")], out.location_product_by_key[("P", "C")]
    z90 = 1.2815516
    assert b.mrp_type.value == "reorder_point"
    assert b.reorder_point == pytest.approx(round(200 + z90 * math.sqrt(10 * 252), 2))      # 264.33
    assert c.mrp_type.value == "deterministic" and c.reorder_point is None
    assert c.safety_stock.method.value == "none"
    assert msg == ("Set 1 safety-stock method, 1 service target, 2 review periods, 1 rule, 1 reorder point on 2 "
                   "products at places. Left as they were, no demand variability to size a service target with: C at "
                   "P. Left as they were, no demand to set a reorder point from: C at P.")
    assert rows(policy_view(out))["B"].rule == "RsQ"
    # and back to MRP: the reorder point is kept for later but no longer orders
    back, msg = apply_policy(out, [("P", "B")], rule="mrp")
    assert back.location_product_by_key[("P", "B")].mrp_type.value == "deterministic"
    assert msg == "Set 1 rule on 1 product at a place."
    with pytest.raises(PolicyError, match="time-phased MRP or a reorder point"):
        apply_policy(out, [("P", "B")], rule="kanban")
    # without a CV of its own, B's is measured from the demand it feeds: A's 0.2 (2 B to each A, the same shape)
    d["location_products"][1]["safety_stock"] = {"method": "none"}
    cv_out, msg = apply_policy(ds(d), [("P", "B")], method="service_level")
    assert cv_out.location_product_by_key[("P", "B")].safety_stock.demand_cv == pytest.approx(0.2)
    assert msg.endswith("The demand variability is the one measured from the demand they feed for B at P.")


def test_lumpy_and_slow_demand_are_sized_by_their_own_distribution():
    from scp.model import SafetyStockPolicy
    from scp.plan.safety import SSInputs, statistical_ss

    def ss(dist: str, method: str, mean: float, cv: float, lead: float, q: float = 0.0) -> float:
        p = SafetyStockPolicy(method=method, service_level=0.95, demand_cv=cv, distribution=dist)
        return statistical_ss(p, SSInputs(mean, lead, 0.0, 0.95, q)).qty
    # 1 a day for 4 days with a weekly CV of 2/√7: σ_d = 2, so demand over the lead time has mean 4 and σ 4 (CV 1). A
    # gamma with CV 1 is the exponential: its 95 % point is 4·ln 20 = 11.98, so SS = 7.98 where the normal says 1.645 × 4
    cv = 2 / math.sqrt(7)
    assert ss("normal", "service_level", 1, cv, 4) == pytest.approx(Z95 * 4, rel=1e-6)
    assert ss("gamma", "service_level", 1, cv, 4) == pytest.approx(4 * math.log(20) - 4, rel=1e-6)
    # a 95 % fill rate with lots of 8: the exponential's expected shortage per cycle is 4·e^(−s/4) = 0.05 × 8, so
    # s = 4·ln 10 = 9.21 and SS = 5.21
    assert ss("gamma", "fill_rate", 1, cv, 4, q=8) == pytest.approx(4 * math.log(10) - 4, rel=1e-6)
    # a slow mover, half a unit a day over 4 days: Poisson with mean 2. P(X ≤ 4) = 0.947, P(X ≤ 5) = 0.983: s = 5, SS = 3.
    # For a 95 % fill rate in lots of 4 the expected shortage must be at most 0.2: 0.218 at s = 3, 0.075 at 4: SS = 2
    assert ss("poisson", "service_level", 0.5, 0.3, 4) == pytest.approx(3)
    assert ss("poisson", "fill_rate", 0.5, 0.3, 4, q=4) == pytest.approx(2)
    # lots of 4.4 allow 0.22: 0.218 at s = 3 is within it, SS = 1
    assert ss("poisson", "fill_rate", 0.5, 0.3, 4, q=4.4) == pytest.approx(1)
    # the review period is part of the exposure: 2 days' lead time and a 2-day review are the same mean of 2
    p = SafetyStockPolicy(method="service_level", service_level=0.95, demand_cv=0.3, distribution="poisson",
                          review_period_days=2)
    assert statistical_ss(p, SSInputs(0.5, 2, 0.0, 0.95, 0.0)).qty == pytest.approx(3)


def test_the_policy_says_when_demand_is_lumpy_and_a_class_can_be_sized_by_a_gamma():
    from scipy.stats import gamma
    d = shop()
    d["location_products"][0]["safety_stock"]["demand_cv"] = 1.0
    r = rows(policy_view(ds(d)))["A"]
    # 10 a day, a weekly CV of 1 (σ_d = 10√7), 2 days: mean 20, σ = 10√14 = 37.4, CV 1.87
    mu, sd = 20.0, 10 * math.sqrt(14)
    assert r.exposure_cv == pytest.approx(sd / mu)
    want = gamma.ppf(0.95, (mu / sd) ** 2, scale=sd ** 2 / mu) - mu
    assert f"spread as a gamma, the target needs {want:,.0f} instead of {Z95 * sd:,.0f}" in " ".join(r.notes)
    out, msg = apply_policy(ds(d), [("P", "A"), ("P", "B")], distribution="gamma")
    assert msg == ("Set 1 demand spread on 2 products at places. Left as they were, safety stock not set by a service "
                   "target: B at P.")
    r2 = rows(policy_view(out))["A"]
    assert r2.distribution == "gamma" and r2.safety_stock == pytest.approx(want, rel=1e-6)
    assert not any("varies widely" in n for n in r2.notes)
    # the plan holds the same safety stock
    from scp.plan import run_mrp
    node = next(n for n in run_mrp(out).nodes if (n.location, n.product) == ("P", "A"))
    assert "gamma" in node.safety_stock_note
    with pytest.raises(PolicyError, match="normal, gamma or Poisson"):
        apply_policy(out, [("P", "A")], distribution="weibull")
