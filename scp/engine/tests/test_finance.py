"""P9 finance overlay: cost to serve by hand on a two-level BOM, the books closing category by category on the
examples, inventory value against the plan KPIs, and capacity appraisal (shadow prices against a re-solve, NPV)."""
from __future__ import annotations

import math

import pytest

from scp.finance import run_finance
from scp.finance.capacity import irr, npv
from scp.plan import run_mrp
from scp.validate import validate

from .factory import base, demand, ds, load_example, lp
from .test_sop import mix


def simple(price: float = 200.0, lot_b: dict | None = None, carrying: bool = False) -> dict:
    """Plant P makes A (1 h × 100 + 2 h setup) from 2 B (10 each) and 1 C (5); 20 A wanted on day 10."""
    d = base()
    d["settings"].update({"wacc": 0.1 if carrying else 0.0, "holding_spread": 0.1 if carrying else 0.0})
    d["products"][0]["price"] = price
    for x in d["location_products"]:
        x["on_hand"] = 0
        x["lot_sizing"] = lot_b if (x["product"] == "B" and lot_b) else {"policy": "L4L"}
    d["demand"] = [demand("P", "A", "2026-01-15", 20)]
    return d


def test_cost_to_serve_by_hand():
    r = run_finance(ds(simple()))
    (row,) = r.serve
    # A: 20 × 0.5 h × 100 conversion + 2 h × 100 setup; B 40 × 10; C 20 × 5
    assert row.costs["production"] == pytest.approx(1000)
    assert row.costs["setup"] == pytest.approx(200)
    assert row.costs["purchase"] == pytest.approx(500)
    assert row.plan_cost == pytest.approx(1700)
    assert row.served == pytest.approx(20) and row.revenue == pytest.approx(4000)
    assert row.margin == pytest.approx(2300) and row.cost_per_unit == pytest.approx(85)
    assert r.reconciliation.reconciled and r.reconciliation.total_unabsorbed == pytest.approx(0)


def test_lot_excess_is_unabsorbed_pro_rata():
    r = run_finance(ds(simple(lot_b={"policy": "FIXED", "fixed_qty": 50})))
    (row,) = r.serve
    assert row.costs["purchase"] == pytest.approx(400 + 100)          # 40 of the 50 B, plus C
    un = {ln.category: ln.unabsorbed for ln in r.reconciliation.lines}
    assert un["purchase"] == pytest.approx(100)                        # 10 of 50 B at 10
    assert r.reconciliation.unabsorbed_reasons["lot-size and safety-stock excess"] == pytest.approx(100)
    assert r.reconciliation.reconciled


def test_opening_stock_is_valued_not_spent():
    d = simple(carrying=True)
    lp(d, "P", "A")["on_hand"] = 5
    r = run_finance(ds(d))
    (row,) = r.serve
    node = next(n for n in run_mrp(ds(d)).nodes if n.product == "A")
    assert row.costs["stock"] == pytest.approx(5 * node.unit_value)
    assert row.costs["production"] == pytest.approx(15 * 50)           # only the 15 made
    assert row.costs["holding"] > 0
    assert row.total_cost == pytest.approx(row.plan_cost + row.costs["stock"])
    assert r.reconciliation.reconciled


@pytest.mark.parametrize("name", ["kitchenware_network", "single_product_plant"])
def test_books_close_on_examples(name):
    d = load_example(name)
    plan = run_mrp(d)
    r = run_finance(d, plan)
    rec = r.reconciliation
    assert rec.reconciled
    for ln in rec.lines:
        assert ln.served + ln.unabsorbed == pytest.approx(ln.plan, rel=1e-9, abs=1e-6)
        assert ln.sources == pytest.approx(ln.plan, rel=1e-9, abs=1e-6)
    assert sum(ln.plan for ln in rec.lines) == pytest.approx(plan.kpis.total_cost)
    assert sum(s.plan_cost for s in r.serve) == pytest.approx(rec.total_served)
    inv = r.inventory
    assert inv.start == pytest.approx(plan.kpis.inventory_value_start)
    assert inv.end == pytest.approx(plan.kpis.inventory_value_end)
    assert inv.avg == pytest.approx(plan.kpis.inventory_value_avg)
    assert sum(b.value * b.days for b in inv.buckets) / d.settings.horizon_days == pytest.approx(inv.avg)
    for b in inv.buckets:
        assert sum(b.by_type.values()) == pytest.approx(b.value)
    served = {(s.location, s.product): s.served for s in r.serve}
    assert all(q >= 0 for q in served.values())


def with_option(d: dict, hours: float, capex: float = 100.0, fixed: float = 0.0, life: int = 3) -> dict:
    d["finance"] = {"capacity_options": [{"id": "SHIFT", "resource": "M1", "added_hours_per_week": hours,
                                          "capex": capex, "fixed_cost_per_year": fixed, "life_years": life}],
                    "discount_rate": 0.1}
    return d


@pytest.mark.parametrize("mode", ["profit", "cost"])
def test_capacity_duals_match_re_solve(mode):
    r = run_finance(ds(with_option(mix(mode=mode), 0.7)))
    (a,) = r.capacity
    assert a.within_range
    assert a.dual_estimate == pytest.approx(a.objective_saving, rel=1e-6, abs=1e-6)
    assert a.dual_estimate > 0
    if mode == "profit":  # the hour is worth B's margin per hour: 15 × 0.7 × 4 weeks
        assert a.dual_estimate == pytest.approx(42)
        assert a.cash_delta == pytest.approx(42)


def test_capacity_beyond_valid_range_is_capped_and_flagged():
    # B's demand is met with 60 extra hours a week; the rest of 1000 h is worth nothing
    r = run_finance(ds(with_option(mix(mode="profit"), 1000)))
    (a,) = r.capacity
    assert not a.within_range
    assert a.objective_saving == pytest.approx(4 * 30 * 30)          # 30 more B a week at margin 30
    assert a.dual_estimate == pytest.approx(a.objective_saving)      # capped at the headroom, where it stays exact
    assert a.fill_rate_after > a.fill_rate_before


def test_npv_payback_and_irr():
    r = run_finance(ds(with_option(mix(mode="profit"), 0.7, capex=1000, fixed=100, life=3)))
    (a,) = r.capacity
    assert a.annual_cash == pytest.approx(42 * 365 / 28)
    assert a.annual_net == pytest.approx(a.annual_cash - 100)
    assert a.cash_flows == pytest.approx([-1000] + [a.annual_net] * 3)
    assert a.npv == pytest.approx(-1000 + sum(a.annual_net / 1.1 ** y for y in (1, 2, 3)))
    assert a.payback_years == pytest.approx(1000 / a.annual_net)
    assert npv(a.cash_flows, a.irr) == pytest.approx(0, abs=1e-6)
    assert irr([-100, 10]) is not None and irr([100, 10]) is None
    assert math.isclose(irr([-100, 110]), 0.1, abs_tol=1e-9)


def test_capacity_option_refs_are_validated():
    d = with_option(mix(), 1)
    d["finance"]["capacity_options"][0]["resource"] = "NOPE"
    d["sop"]["capacity_add_hours_per_week"] = {"GHOST": 5}
    codes = [(i.code, i.object_type) for i in validate(ds(d))]
    assert ("REF_UNKNOWN", "capacity_option") in codes and ("REF_UNKNOWN", "sop") in codes


def test_added_hours_lever_raises_sop_capacity():
    from scp.sop import run_sop
    r0 = run_sop(ds(mix()))
    d = mix()
    d["sop"]["capacity_add_hours_per_week"] = {"M1": 14}
    r1 = run_sop(ds(d))
    assert [c1 - c0 for c0, c1 in zip(r0.resources[0].capacity, r1.resources[0].capacity, strict=True)] == \
        pytest.approx([14.0] * 4)
