"""P4 S&OP LP: shadow prices against finite-difference re-solves, the single-resource profit case
against margin-per-bottleneck-hour ranking, and the behaviours the LP must show (pre-build,
overtime, supplier limits, shelf life, lost vs late), plus release to MRP."""
from __future__ import annotations

import copy
import math

import pytest

from scp.model import Dataset
from scp.plan import run_mrp
from scp.sop import release_sop, run_sop

from .factory import demand, ds, load_example

WEEKS = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]


def mix(capacity_h: float = 100.0, **sop) -> dict:
    """One plant, one resource M1 (capacity_h hours a week), products A and B bought as materials
    MA / MB and converted on M1. A small carrying rate makes building ahead strictly worse than
    building on time, so the optimum is unique. Weekly S&OP buckets over four weeks."""
    units = max(1, math.ceil(capacity_h / 168))
    return {
        "settings": {"planning_start": WEEKS[0], "horizon_days": 28, "bucket": "week", "default_calendar": "CAL",
                     "wacc": 0.05, "holding_spread": 0.0},
        "calendars": [{"id": "CAL", "workdays": [0, 1, 2, 3, 4, 5, 6]}],
        "locations": [{"id": "P", "type": "plant"}, {"id": "S", "type": "supplier"}],
        "products": [{"id": "A", "type": "FG", "price": 30}, {"id": "B", "type": "FG", "price": 50},
                     {"id": "MA", "type": "RM"}, {"id": "MB", "type": "RM"}],
        "location_products": [],
        "resources": [{"id": "M1", "location": "P", "efficiency": 1.0, "units": units, "hours_per_shift": capacity_h / 7 / units}],
        "production_sources": [
            {"id": "PV-A", "location": "P", "product": "A", "fixed_lead_time_workdays": 0,
             "components": [{"product": "MA", "qty": 1}], "operations": [{"seq": 10, "resource": "M1", "run_hours_per_unit": 1}]},
            {"id": "PV-B", "location": "P", "product": "B", "fixed_lead_time_workdays": 0,
             "components": [{"product": "MB", "qty": 1}], "operations": [{"seq": 10, "resource": "M1", "run_hours_per_unit": 2}]},
        ],
        "purchasing_sources": [
            {"id": "PIR-MA", "supplier": "S", "product": "MA", "location": "P", "price": 10, "lead_time_days": 0},
            {"id": "PIR-MB", "supplier": "S", "product": "MB", "location": "P", "price": 20, "lead_time_days": 0},
        ],
        "lanes": [], "receipts": [],
        "demand": [demand("P", "A", w, 60, period_days=7) for w in WEEKS] + [demand("P", "B", w, 50, period_days=7) for w in WEEKS],
        "sop": {"bucket": "week", **sop},
    }


def line(res, loc, prod):
    return next(d for d in res.demand if (d.location, d.product) == (loc, prod))


def test_single_resource_profit_mode_is_margin_per_bottleneck_hour_ranking():
    # A earns 20 per hour (margin 20, 1 h); B earns 15 per hour (margin 30, 2 h): A first, B gets the rest
    r = run_sop(ds(mix(mode="profit")))
    assert r.ok and r.solver.status == "optimal"
    assert line(r, "P", "A").sales == pytest.approx([60] * 4)
    assert line(r, "P", "B").sales == pytest.approx([20] * 4)  # (100 − 60) / 2
    (m1,) = r.resources
    assert m1.shadow_price == pytest.approx([15.0] * 4)        # the marginal product's margin per hour
    assert r.economics.profit == pytest.approx(4 * (60 * 20 + 20 * 30))


def test_ranking_flips_when_margins_flip():
    d = mix(mode="profit")
    d["products"][1]["price"] = 70  # B: margin 50 over 2 h = 25/h > A's 20/h
    r = run_sop(ds(d))
    assert line(r, "P", "B").sales == pytest.approx([50] * 4)
    assert line(r, "P", "A").sales == pytest.approx([0] * 4)   # 100 h all to B
    # B's demand is exactly met, so one more hour would go to A: the hour is worth A's 20
    assert r.resources[0].shadow_price == pytest.approx([20.0] * 4)


def _objective(r) -> float:
    return -r.economics.profit if r.mode.value == "profit" else r.economics.total_cost


@pytest.mark.parametrize("mode", ["profit", "cost"])
def test_capacity_duals_equal_finite_difference(mode):
    base = mix(mode=mode)
    r0 = run_sop(ds(base))
    bumped = copy.deepcopy(base)
    delta = 0.7  # hours a week
    bumped["resources"][0]["hours_per_shift"] = (100 + delta) / 7
    r1 = run_sop(ds(bumped))
    predicted = -sum(r0.resources[0].shadow_price) * delta
    assert _objective(r1) - _objective(r0) == pytest.approx(predicted, rel=1e-6, abs=1e-6)
    assert all(up is None or up >= 100 + delta for up in r0.resources[0].valid_up)


def test_demand_marginal_cost_equals_finite_difference():
    d = mix(capacity_h=1000)  # uncapacitated: serving one more A costs its material (10)
    r0 = run_sop(ds(d))
    assert line(r0, "P", "A").marginal_cost[2] == pytest.approx(10)
    d2 = copy.deepcopy(d)
    d2["demand"][2]["qty"] += 1
    assert run_sop(ds(d2)).economics.total_cost - r0.economics.total_cost == pytest.approx(10)


def test_cost_mode_prebuilds_a_peak_instead_of_serving_late():
    d = mix(capacity_h=100)
    d["demand"] = [demand("P", "A", w, q, period_days=7) for w, q in zip(WEEKS, [50, 50, 150, 50], strict=True)]
    d["settings"]["wacc"] = 0.1
    r = run_sop(ds(d))
    a = line(r, "P", "A")
    assert a.sales == pytest.approx([50, 50, 150, 50])
    assert r.kpis.on_time_rate == pytest.approx(1.0)
    inv = next(s for s in r.supply if (s.location, s.product) == ("P", "A")).inventory
    assert sum(inv[:2]) == pytest.approx(50)       # 50 built ahead of the peak
    assert r.economics.holding > 0 and r.economics.backlog_penalty == 0


def test_overtime_is_bought_when_cheaper_than_late_delivery_and_prices_the_hour():
    d = mix(capacity_h=100)
    d["demand"] = [demand("P", "A", w, 130, period_days=7) for w in WEEKS]
    d["resources"][0].update(overtime_hours_per_day=10 / 7, overtime_cost_per_hour=4)
    r = run_sop(ds(d))
    m1 = r.resources[0]
    assert m1.overtime == pytest.approx([10] * 4)  # 100 regular + 10 overtime of 130 needed
    assert m1.shadow_price[0] > 4                  # overtime at its limit: the hour is worth more than its cost
    assert any(b.kind == "overtime" for b in r.binding)
    assert r.kpis.sales < r.kpis.demand


def test_supplier_capacity_binds_and_is_reported():
    d = mix(capacity_h=1000)
    d["purchasing_sources"][0]["capacity_per_week"] = 40
    r = run_sop(ds(d))
    assert line(r, "P", "A").sales == pytest.approx([40] * 4)
    sup = [b for b in r.binding if b.kind == "supplier"]
    assert len(sup) == 4 and all(b.used == pytest.approx(40) for b in sup)


def test_cost_mode_lost_sales_when_capacity_cannot_catch_up():
    d = mix(capacity_h=50)
    r = run_sop(ds(d))
    # 160 h of work a week (A 60 h + B 100 h) on 50 h: whatever is still open at the end is lost
    assert r.kpis.backlog_end > 0 or r.kpis.lost > 0
    assert r.kpis.fill_rate < 1


def test_shelf_life_caps_stock_to_what_leaves_in_time():
    d = mix(capacity_h=100)
    d["demand"] = [demand("P", "A", w, q, period_days=7) for w, q in zip(WEEKS, [50, 50, 150, 50], strict=True)]
    d["products"][0]["shelf_life_days"] = 7  # stock at the end of a week must be sold the next week
    d["settings"]["wacc"] = 0.1
    r = run_sop(ds(d))
    inv = next(s for s in r.supply if (s.location, s.product) == ("P", "A")).inventory
    a = line(r, "P", "A")
    assert inv[0] == pytest.approx(0) and inv[1] == pytest.approx(50)  # only the week before the peak can build ahead
    assert a.sales == pytest.approx([50, 50, 150, 50])


def test_scenario_levers_scale_demand_and_capacity():
    r = run_sop(ds(mix(mode="profit", capacity_factor=1.2)))
    assert line(r, "P", "B").sales == pytest.approx([30] * 4)  # (120 − 60) / 2
    r = run_sop(ds(mix(mode="profit", demand_factor=0.5)))
    assert line(r, "P", "A").demand == pytest.approx([30] * 4)


def test_release_writes_constrained_demand_that_mrp_plans():
    d = mix(capacity_h=100, mode="profit")
    r = run_sop(ds(d))
    new, info = release_sop(ds(d), r)
    assert info.replaced == 8 and info.nodes == 2
    assert info.constrained_qty == pytest.approx(320) and info.unconstrained_qty == pytest.approx(440)
    b = [x for x in new.demand if x.product == "B"]
    assert sum(x.qty for x in b) == pytest.approx(80) and all(x.id.startswith("SOP-") for x in b)
    assert run_mrp(new).ok


def test_blocked_dataset():
    d = mix()
    d["demand"][0]["product"] = "NOPE"
    r = run_sop(ds(d))
    assert not r.ok and r.issues


@pytest.mark.parametrize("name", ["kitchenware_network", "single_product_plant"])
@pytest.mark.parametrize("mode", ["cost", "profit"])
def test_examples_solve(name, mode):
    base = load_example(name)
    data = base.model_dump(mode="json")
    data["sop"]["mode"] = mode
    r = run_sop(Dataset.model_validate(data))
    assert r.ok and r.solver.status == "optimal"
    assert r.kpis.sales <= r.kpis.demand + 1e-6
    # material balance at every stocking node: start + in − out = end
    for s in r.supply:
        if s.role != "stocking":
            continue
        lp = base.location_product_by_key.get((s.location, s.product))
        on_hand = lp.on_hand if lp else 0.0
        firm = sum(x.qty for x in base.receipts if (x.location, x.product) == (s.location, s.product)
                   and x.due_date < r.buckets[-1].end)
        dl = next((x for x in r.demand if (x.location, x.product) == (s.location, s.product)), None)
        sold = sum(dl.sales) if dl else 0.0
        inflow = sum(s.make) + sum(s.buy) + sum(s.transfer_in) + firm
        outflow = sum(s.transfer_out) + sum(s.consumed) + sold
        assert on_hand + inflow - outflow == pytest.approx(s.inventory[-1], abs=1e-4)
