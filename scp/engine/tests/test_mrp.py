"""Golden MRP scenarios with hand-computed answers.

Base network (tests/factory.base): 7-day calendar, plant P, A = 2×B + 1×C, A made with a fixed
2-working-day lead time on M1 (setup 2 h + 0.5 h/unit), B bought (3 d, FIXED 50, 30 on hand),
C bought (1 d, L4L, 0 on hand), A has 10 on hand.
"""
from datetime import date

import pytest

from scp.plan import run_mrp
from scp.plan.consumption import effective_demand
from scp.plan.lotsize import apply_modifiers, base_lot, eoq
from scp.model import DemandRecord, LotSizing, Strategy

from .factory import base, demand, ds, lp


def D(s: str) -> date:
    return date.fromisoformat(s)


def plan(d):
    r = run_mrp(ds(d))
    assert r.ok, [i.message for i in r.issues if i.severity == "error"]
    return r


def orders(r, prod):
    return sorted((o for o in r.orders if o.product == prod), key=lambda o: o.need_date)


def node(r, loc, prod):
    return next(n for n in r.nodes if (n.location, n.product) == (loc, prod))


def textbook():
    d = base()
    d["demand"] = [demand("P", "A", "2026-01-12", 30), demand("P", "A", "2026-01-19", 20)]
    return d


def test_textbook_three_item_mrp():
    r = plan(textbook())
    a = orders(r, "A")
    assert [(o.qty, o.need_date, o.start_date, o.available_date) for o in a] == [
        (20, D("2026-01-12"), D("2026-01-10"), D("2026-01-12")),
        (20, D("2026-01-19"), D("2026-01-17"), D("2026-01-19")),
    ]
    b = orders(r, "B")
    assert [(o.qty, o.need_date, o.start_date) for o in b] == [(50, D("2026-01-10"), D("2026-01-07"))]
    c = orders(r, "C")
    assert [(o.qty, o.start_date) for o in c] == [(20, D("2026-01-09")), (20, D("2026-01-16"))]
    # dependent requirements are placed at the parent's start and sized by the BOM
    dep_b = sorted((q.date, q.qty) for q in r.requirements if q.product == "B")
    assert dep_b == [(D("2026-01-10"), 40), (D("2026-01-17"), 40)]
    # physical projection per weekly bucket
    assert [b.projected_on_hand for b in node(r, "P", "A").buckets] == [10, 0, 0, 0]
    assert [b.projected_on_hand for b in node(r, "P", "B").buckets] == [40, 0, 0, 0]
    # capacity: 12 h per order, spread over its 2-day window
    m1 = next(x for x in r.resources if x.resource == "M1")
    assert [b.load_hours for b in m1.buckets] == [12, 12, 0, 0]
    assert m1.buckets[0].capacity_hours == 56
    # costs
    assert r.kpis.purchase_cost == pytest.approx(50 * 10 + 40 * 5)
    assert r.kpis.production_cost == pytest.approx(40 * 0.5 * 100)
    assert r.kpis.setup_cost == pytest.approx(2 * 2 * 100)
    assert r.kpis.on_time_fill_rate == 1.0
    assert not [e for e in r.exceptions if e.severity == "error"]


def test_pegging_links_demand_to_stock_and_orders():
    r = plan(textbook())
    first = [p for p in r.pegs if p.requirement_id == "D:#0"]
    assert {(p.supply_kind, p.qty) for p in first} == {("on_hand", 10), ("order", 20)}


def test_scrap_inflates_requirements():
    d = textbook()
    d["production_sources"][0]["assembly_scrap"] = 0.2
    d["production_sources"][0]["components"][1]["scrap"] = 0.2
    r = plan(d)
    dep = {(q.product, q.date): q.qty for q in r.requirements if q.kind == "dependent"}
    assert dep[("B", D("2026-01-10"))] == pytest.approx(20 / 0.8 * 2)
    assert dep[("C", D("2026-01-10"))] == pytest.approx(20 / 0.8 / 0.8)


def test_working_day_scheduling():
    d = base(workdays=[0, 1, 2, 3, 4])
    d["demand"] = [demand("P", "A", "2026-01-12", 30)]  # Monday
    r = plan(d)
    (o,) = orders(r, "A")
    assert o.start_date == D("2026-01-08")  # Thu: 2 working days before Monday


def test_start_in_past_is_forward_scheduled_and_delays_propagate():
    d = base()
    d["demand"] = [demand("P", "A", "2026-01-06", 30)]
    r = plan(d)
    (a,) = orders(r, "A")
    assert a.start_in_past and a.start_date == D("2026-01-05") and a.available_date == D("2026-01-07")
    (b,) = orders(r, "B")
    assert b.start_in_past and b.available_date == D("2026-01-08")
    # A cannot start before B arrives (Jan 8, 3 days after its Jan 5 need): projected Jan 10
    assert a.projected_available_date == D("2026-01-10") and a.delay_days == 4
    assert r.kpis.on_time_fill_rate == pytest.approx(10 / 30)
    codes = {e.code for e in r.exceptions}
    assert {"START_IN_PAST", "DEMAND_AT_RISK"} <= codes


def test_fixed_safety_stock_and_safety_time():
    d = textbook()
    lp(d, "P", "A")["safety_stock"] = {"method": "fixed", "qty": 5}
    r = plan(d)
    assert [o.qty for o in orders(r, "A")] == [25, 20]
    d = textbook()
    lp(d, "P", "A")["safety_time_days"] = 2
    r = plan(d)
    assert [o.need_date for o in orders(r, "A")] == [D("2026-01-10"), D("2026-01-17")]


def test_days_of_supply_safety_stock_breathes():
    d = textbook()
    lp(d, "P", "A")["safety_stock"] = {"method": "days_of_supply", "days": 7}
    r = plan(d)
    # SS(t) = requirements in [t, t + 7 d): bucket 0 = [5 Jan, 12 Jan) excludes the 12 Jan demand
    assert [b.safety_stock for b in node(r, "P", "A").buckets] == [0, 30, 20, 0]


def test_service_level_safety_stock_formula():
    d = textbook()
    lp(d, "P", "B")["safety_stock"] = {"method": "service_level", "service_level": 0.95, "demand_cv": 0.2}
    d["purchasing_sources"][0]["lead_time_std_days"] = 1.0
    r = plan(d)
    n = node(r, "P", "B")
    mean = 80 / 28
    sd = 0.2 * mean * 7 ** 0.5
    expected = 1.6448536 * ((3 * sd ** 2) + (mean * 1.0) ** 2) ** 0.5
    assert n.buckets[0].safety_stock == pytest.approx(expected, rel=1e-6)


def test_planning_time_fence_shifts_new_orders():
    d = textbook()
    lp(d, "P", "A")["planning_time_fence_days"] = 10
    r = plan(d)
    a = orders(r, "A")
    assert a[0].fence_shifted and a[0].available_date == D("2026-01-15")
    assert not a[1].fence_shifted
    assert "FENCE_SHIFT" in {e.code for e in r.exceptions}


def test_quota_arrangement_alternates_sources():
    d = textbook()
    d["locations"].append({"id": "S2", "type": "supplier"})
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    lp(d, "P", "B")["on_hand"] = 0
    d["purchasing_sources"][0]["quota"] = 0.5
    d["purchasing_sources"].append({"id": "PIR-B2", "supplier": "S2", "product": "B", "location": "P", "price": 12,
                                    "lead_time_days": 3, "quota": 0.5})
    r = plan(d)
    assert [o.source_id for o in orders(r, "B")] == ["PIR-B", "PIR-B2"]


def test_transfer_chain_places_requirement_at_origin_on_ship_date():
    d = base()
    d["locations"] += [{"id": "D", "type": "dc"}, {"id": "K", "type": "customer"}]
    d["location_products"].append({"location": "D", "product": "A"})
    d["lanes"] = [{"id": "PD", "origin": "P", "destination": "D", "products": ["A"], "modes": [{"transit_days": 2}]},
                  {"id": "DK", "origin": "D", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["demand"] = [demand("K", "A", "2026-01-15", 10)]
    r = plan(d)
    tos = sorted((o for o in r.orders if o.kind == "transfer"), key=lambda o: o.start_date)
    assert [(o.origin, o.location, o.start_date, o.available_date) for o in tos] == [
        ("P", "D", D("2026-01-12"), D("2026-01-14")), ("D", "K", D("2026-01-14"), D("2026-01-15"))]
    req_p = [q for q in r.requirements if q.location == "P" and q.product == "A"]
    assert [(q.kind, q.date, q.qty) for q in req_p] == [("transfer", D("2026-01-12"), 10)]
    assert not orders(r, "B")  # plant stock (10) covers it: nothing to make


def test_mto_ignores_anonymous_stock_and_forecast():
    d = base()
    lp(d, "P", "A")["strategy"] = "MTO"
    d["demand"] = [demand("P", "A", "2026-01-12", 30, "sales_order", id="SO1"),
                   demand("P", "A", "2026-01-19", 99)]
    r = run_mrp(ds(d))
    assert [o.qty for o in orders(r, "A")] == [30]


def test_ato_forecast_supply_is_not_convertible():
    d = base()
    lp(d, "P", "A")["strategy"] = "ATO"
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [demand("P", "A", "2026-01-12", 30), demand("P", "A", "2026-01-12", 10, "sales_order", id="SO1")]
    r = plan(d)
    conv = sorted((o.qty, o.convertible) for o in orders(r, "A"))
    assert conv == [(30, False)]  # one L4L lot covering 10 SO + 20 remaining forecast


def test_supplier_and_capacity_exceptions():
    d = textbook()
    d["purchasing_sources"][0]["capacity_per_week"] = 10
    d["resources"][0]["hours_per_shift"] = 1
    r = plan(d)
    codes = {e.code for e in r.exceptions}
    assert "SUPPLIER_CAPACITY" in codes and "CAPACITY_OVERLOAD" in codes


def test_mrp_type_none_projects_without_replenishing():
    d = textbook()
    lp(d, "P", "A")["mrp_type"] = "none"
    r = plan(d)
    assert not orders(r, "A")
    assert "STOCKOUT" in {e.code for e in r.exceptions}


def test_reorder_point():
    d = textbook()
    x = lp(d, "P", "B")
    x["mrp_type"] = "reorder_point"
    x["reorder_point"] = 35
    r = plan(d)
    b = orders(r, "B")
    assert b[0].need_date == D("2026-01-05")  # 30 on hand is already below the reorder point


def test_blocking_issue_returns_no_plan():
    d = textbook()
    d["production_sources"][0]["components"].append({"product": "NOPE", "qty": 1})
    r = run_mrp(ds(d))
    assert not r.ok and not r.orders and any(i.code == "REF_UNKNOWN" for i in r.issues)


# --- units: lot sizing and consumption --------------------------------------------------------
def test_lot_sizing_units():
    assert base_lot(LotSizing(policy="FIXED", fixed_qty=50), 10) == 50
    assert base_lot(LotSizing(policy="FIXED", fixed_qty=50), 120) == 150
    assert base_lot(LotSizing(policy="POQ", periods=2), 10, window_requirements=35) == 45
    assert base_lot(LotSizing(policy="MIN_MAX"), 5, max_stock_gap=80) == 80
    assert base_lot(LotSizing(policy="EOQ"), 10, eoq_qty=120) == 120
    assert eoq(1000, 50, 20, 0.25) == pytest.approx((2 * 1000 * 50 / 5) ** 0.5)
    assert eoq(1000, 0, 20, 0.25) is None
    assert apply_modifiers(7, mins=[10], roundings=[4], maxes=[None]) == [12]
    assert apply_modifiers(25, mins=[0], roundings=[None], maxes=[10]) == [10, 10, 5]


def test_forecast_consumption_backward_then_forward():
    def rec(day, qty, kind="forecast"):
        return DemandRecord(location="P", product="A", date=day, qty=qty, kind=kind)

    recs = [("f1", rec("2026-01-05", 100)), ("f2", rec("2026-01-12", 100)),
            ("s1", rec("2026-01-08", 130, "sales_order"))]
    out = effective_demand(recs, Strategy.MTS_CONSUME, 7, 7)
    got = {(r.kind, r.date.isoformat()): r.qty for r in out}
    assert got == {("forecast", "2026-01-12"): 70, ("sales_order", "2026-01-08"): 130}
    assert {r.kind for r in effective_demand(recs, Strategy.MTS, 7, 7)} == {"forecast"}
    assert {r.kind for r in effective_demand(recs, Strategy.MTO, 7, 7)} == {"sales_order"}


def test_forecast_period_split_over_workdays():
    d = base(workdays=[0, 1, 2, 3, 4])
    d["demand"] = [demand("P", "A", "2026-01-12", 50, period_days=7)]
    r = plan(d)
    reqs = sorted((q.date, q.qty) for q in r.requirements if q.product == "A")
    assert [x[0].weekday() for x in reqs] == [0, 1, 2, 3, 4]
    assert all(q == pytest.approx(10) for _, q in reqs)


def test_normal_loss_and_fill_rate_k():
    from scp.plan.safety import k_for_fill_rate, loss

    assert loss(0) == pytest.approx(0.3989423, rel=1e-6)
    assert loss(1.0) == pytest.approx(0.0833155, rel=1e-5)
    k = k_for_fill_rate(0.0833155)
    assert k == pytest.approx(1.0, abs=1e-4)
