"""P10 control tower: every §18.2 KPI against a hand-checked fixture, the grading bands, and the worklist life
cycle (open → acknowledged → aged → cleared → reopened) kept in the version store across runs."""
from __future__ import annotations

import datetime as dt

import pytest

from scp.plan import run_mrp
from scp.tower import plan_stability, run_tower
from scp.tower.kpis import grade
from scp.versions import get_store

from .factory import START, base, demand, ds, lp


def fixture() -> dict:
    d = base()
    d["demand"] = [demand("P", "A", "2026-01-10", 5),
                   demand("P", "A", "2026-01-12", 40, kind="sales_order", id="SO-1")]
    d["confirmations"] = [{"order": "SO-1", "ship_from": "P", "ship_date": "2026-01-12", "date": "2026-01-12", "qty": 30},
                          {"order": "SO-1", "ship_from": "P", "ship_date": "2026-01-14", "date": "2026-01-14", "qty": 10}]

    def co(kind, oid, ordered, delivered, due, last, promised=None, first=None, cp="P"):
        return {"kind": kind, "id": oid, "location": "P", "product": "A", "counterparty": cp, "ordered_qty": ordered,
                "delivered_qty": delivered, "due_date": due, "promised_date": promised,
                "first_delivery": first or last, "last_delivery": last, "closed_on": last}
    d["closed_orders"] = [
        co("sales", "S1", 100, 100, "2026-01-01", "2026-01-01", promised="2026-01-01"),
        co("sales", "S2", 100, 99, "2026-01-02", "2026-01-03", promised="2026-01-03"),     # within 2 % tolerance
        co("sales", "S3", 100, 90, "2026-01-02", "2026-01-02", promised="2026-01-02"),     # short
        co("sales", "S4", 50, 50, "2026-01-02", "2026-01-02", first="2025-12-30"),          # split, no promise
        co("purchase", "P1", 10, 10, "2026-01-01", "2025-12-31", cp="S"),
        co("purchase", "P2", 10, 10, "2026-01-01", "2026-01-03", cp="S"),
        co("production", "M1", 10, 10, "2025-12-31", "2026-01-02"),                        # same week (Mon 29 Dec)
        co("production", "M2", 10, 10, "2026-01-02", "2026-01-05"),                        # next week
    ]
    d["accuracy"] = [
        {"location": "P", "product": "A", "start": "2025-12-22", "end": "2025-12-29", "forecast": 100, "actual": 80},
        {"location": "P", "product": "A", "start": "2025-12-29", "end": "2026-01-05", "forecast": 100, "actual": 120},
    ]
    return d


def kpis(res) -> dict:
    return {k.id: k for k in res.kpis}


def test_kpis_against_hand_calculation():
    k = kpis(run_tower(ds(fixture())))
    assert k["forecast_accuracy"].value == pytest.approx(0.8)          # 1 − (20 + 20) / 200
    assert k["forecast_bias"].value == pytest.approx(0.0)
    assert k["confirmation_rate"].value == pytest.approx(230 / 340)    # S1 100 + S3 100 + SO-1 30 of 100+100+100+40
    assert k["otif_confirmed"].value == pytest.approx(2 / 3)           # S1, S2 (in tolerance, on promise); not S3
    assert k["otif_requested"].value == pytest.approx(2 / 4)           # S1, S4
    assert k["perfect_order"].value == pytest.approx(1 / 4)            # S1 only: S4 came in two deliveries
    assert k["supplier_reliability"].value == pytest.approx(1 / 2)
    assert k["supplier_reliability"].breakdown[0].label == "S"
    assert k["schedule_adherence"].value == pytest.approx(1 / 2)
    assert k["otif_requested"].n == 4 and k["otif_requested"].status == "critical"


def test_inventory_kpis_by_hand():
    d = fixture()
    res = run_tower(ds(d))
    plan = run_mrp(ds(d))
    uv = {(n.location, n.product): n.unit_value for n in plan.nodes}
    k = kpis(res)
    need_a = 40                                                    # the 5 forecast is consumed by SO-1
    # A: 10 on hand against 45 required → no excess; B (30 × 10) has requirements only if A is made
    made = any(o.product == "A" for o in plan.orders)
    assert made
    a_daily = need_a / 28 * uv[("P", "A")]
    b_req = sum(b.gross_dependent for n in plan.nodes if n.product == "B" for b in n.buckets)
    b_daily = b_req / 28 * uv[("P", "B")]
    stock = 10 * uv[("P", "A")] + 30 * uv[("P", "B")]
    assert k["days_of_supply"].value == pytest.approx(stock / (a_daily + b_daily))
    assert k["excess_obsolete"].value == pytest.approx(max(0, 30 - b_req) * uv[("P", "B")] / stock)


def test_obsolete_stock_is_flagged_and_listed():
    d = fixture()
    lp(d, "P", "C")["on_hand"] = 50
    d["products"].append({"id": "Z", "type": "RM", "standard_cost": 4})
    d["location_products"].append({"location": "P", "product": "Z", "on_hand": 25})
    res = run_tower(ds(d))
    eo = kpis(res)["excess_obsolete"]
    assert any(r.label == "P · Z (no demand)" and r.value == pytest.approx(100) for r in eo.breakdown)
    assert any(w.code == "NO_DEMAND_STOCK" and w.product == "Z" for w in res.worklist)


def test_no_data_is_none_not_a_flattering_default():
    d = base()
    k = kpis(run_tower(ds(d)))
    for kid in ("forecast_accuracy", "otif_requested", "supplier_reliability", "schedule_adherence", "plan_stability"):
        assert k[kid].value is None and k[kid].status == "none" and k[kid].note


def test_grading_bands():
    assert grade(0.95, 0.95, "up", "ratio") == "good"
    assert grade(0.93, 0.95, "up", "ratio") == "warning"
    assert grade(0.89, 0.95, "up", "ratio") == "critical"
    assert grade(-0.12, 0.1, "zero", "ratio") == "warning" and grade(0.2, 0.1, "zero", "ratio") == "critical"
    assert grade(3.5, 3.0, "down", "days") == "warning" and grade(4.0, 3.0, "down", "days") == "critical"
    assert grade(None, 0.9, "up", "ratio") == "none"


def overdue(d: dict, rid: str = "PO-OLD") -> dict:
    d["receipts"] = [{"id": rid, "kind": "purchase", "location": "P", "product": "B", "qty": 20,
                      "due_date": "2026-01-02", "source": "PIR-B"}]
    return d


def shifted(d: dict, days: int) -> dict:
    d = {**d, "settings": {**d["settings"],
                           "planning_start": (dt.date.fromisoformat(START) + dt.timedelta(days=days)).isoformat()}}
    return d


def item(res, code):
    return next(w for w in res.worklist if w.code == code)


def test_worklist_lifecycle_ages_on_the_planning_clock():
    d = overdue(base())
    d["tower"] = {"owners": [{"owner": "Buyer", "categories": ["orders"]}], "sla_days": {"orders": 3}}
    w = item(run_tower(ds(d)), "RECEIPT_OVERDUE")
    assert (w.status, w.owner, w.owner_source, w.age_days) == ("open", "Buyer", "rule", 0)
    from scp.tower import get_tracker
    get_tracker().update(w.id, status="acknowledged", owner="Asha")
    again = item(run_tower(ds(d)), "RECEIPT_OVERDUE")          # same day: nothing changes but the refresh
    assert (again.id, again.status, again.owner, again.age_days) == (w.id, "acknowledged", "Asha", 0)
    later = item(run_tower(ds(shifted(d, 7))), "RECEIPT_OVERDUE")
    assert later.age_days == 7 and later.breached and later.owner == "Asha" and later.status == "acknowledged"
    gone = shifted({**d, "receipts": []}, 8)
    res = run_tower(ds(gone))
    assert all(x.code != "RECEIPT_OVERDUE" for x in res.worklist)
    (c,) = [x for x in res.cleared if x.code == "RECEIPT_OVERDUE"]
    assert c.status == "cleared" and c.resolved_on == dt.date(2026, 1, 13)
    back = item(run_tower(ds(shifted(d, 10))), "RECEIPT_OVERDUE")
    assert back.status == "open" and back.reopened == 1 and back.age_days == 0
    assert back.owner == "Asha"                                # a manual assignment survives


def test_manual_resolve_holds_on_the_same_day_and_reopens_later():
    d = overdue(base())
    w = item(run_tower(ds(d)), "RECEIPT_OVERDUE")
    from scp.tower import get_tracker
    get_tracker().update(w.id, status="resolved", note="expediting with supplier")
    assert item(run_tower(ds(d)), "RECEIPT_OVERDUE").status == "resolved"
    re = item(run_tower(ds(shifted(d, 1))), "RECEIPT_OVERDUE")
    assert re.status == "open" and re.reopened == 1 and re.note == "expediting with supplier"


def test_master_data_goes_to_data_quality_not_the_worklist():
    d = base()
    d["location_products"][0]["lot_sizing"] = {"policy": "EOQ"}   # EOQ without cost data falls back (a data note)
    res = run_tower(ds(d))
    assert all(w.code != "EOQ_FALLBACK" for w in res.worklist)
    d["tower"] = {"owners": [{"owner": "X", "locations": ["NOWHERE"]}]}
    res = run_tower(ds(d))
    assert any(r.code == "REF_UNKNOWN" for r in res.data_quality)


def test_plan_stability_against_the_previous_base():
    d = base()
    d["demand"] = [demand("P", "A", "2026-01-12", 30), demand("P", "A", "2026-01-26", 30)]
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 0
    assert kpis(run_tower(ds(d)))["plan_stability"].value is None       # nothing saved yet
    get_store().save_base(ds(d), "week 1")
    assert kpis(run_tower(ds(d)))["plan_stability"].value is None       # identical to the saved base: excluded
    same = {**d, "settings": {**d["settings"], "holding_spread": 0.11}}
    assert kpis(run_tower(ds(same)))["plan_stability"].value == pytest.approx(1.0)
    changed = {**d, "demand": [demand("P", "A", "2026-01-12", 30), demand("P", "A", "2026-01-26", 45)]}
    cur, prev = run_mrp(ds(changed)), run_mrp(ds(d))
    v, n, m, _ = plan_stability(cur, prev, dt.date(2026, 2, 2), dt.date(2026, 1, 5))
    assert n == len(cur.orders) and m == n - 3                           # the late A order and its B and C buys moved
    k = kpis(run_tower(ds(changed)))["plan_stability"]
    assert k.value == pytest.approx(v) and "week 1" in k.source
