"""P3 inventory optimisation: guaranteed-service placement against hand calculations and brute
force, DDMRP zones against the Ptak–Smith formulas, demand propagation and pooling."""
from __future__ import annotations

import math
import random
from statistics import NormalDist

import pytest

from scp.inventory import ddmrp, gsm, run_inventory
from scp.model import InventorySettings

from .factory import base, demand, ds, load_example, lp

Z95 = NormalDist().inv_cdf(0.95)


# ---------------------------------------------------------------- guaranteed-service model
def test_two_stage_serial_pools_downstream_when_costs_are_equal():
    # c√3 + c√2 (decouple) = 3.146 > c√5 (hold everything downstream) = 2.236
    st = [gsm.Stage("up", 3, 1.0), gsm.Stage("dn", 2, 1.0, ["up"], max_service=0)]
    sol = gsm.solve(st)
    assert sol.status == "optimal"
    assert sol.service == {"up": 3, "dn": 0}
    assert sol.net == {"up": 0, "dn": 5}
    assert sol.objective == pytest.approx(math.sqrt(5))


def test_two_stage_serial_decouples_when_downstream_is_expensive():
    # 1·√3 + 3·√2 = 5.975 < 3·√5 = 6.708
    st = [gsm.Stage("up", 3, 1.0), gsm.Stage("dn", 2, 3.0, ["up"], max_service=0)]
    sol = gsm.solve(st)
    assert sol.net == {"up": 3, "dn": 2}
    assert sol.objective == pytest.approx(math.sqrt(3) + 3 * math.sqrt(2))


def test_customer_service_time_is_respected_and_used():
    st = [gsm.Stage("up", 3, 1.0), gsm.Stage("dn", 2, 1.0, ["up"], max_service=2)]
    sol = gsm.solve(st)
    assert sol.service["dn"] <= 2
    assert sol.objective == pytest.approx(math.sqrt(3))  # quoting 2 days leaves 3 days of net time to cover
    assert sum(sol.net.values()) == 3


def test_no_stock_stage_has_zero_net_time():
    st = [gsm.Stage("comp", 4, 1.0), gsm.Stage("mto", 2, 10.0, ["comp"], max_service=0, no_stock=True)]
    sol = gsm.solve(st)
    assert sol.net["mto"] == 0
    assert sol.service["mto"] == sol.inbound["mto"] + 2


def _random_network(rng: random.Random, n: int) -> list[gsm.Stage]:
    out = []
    for k in range(n):
        ups = [f"s{i}" for i in range(k) if rng.random() < 0.4]
        out.append(gsm.Stage(f"s{k}", rng.randint(0, 3), round(rng.uniform(0, 5), 2), ups,
                             max_service=rng.choice([None, None, 0, 1, 2]), no_stock=rng.random() < 0.1))
    return out


def test_milp_matches_brute_force_on_random_networks():
    rng = random.Random(20260925)
    for _ in range(120):
        st = _random_network(rng, rng.randint(2, 5))
        a, b = gsm.solve(st), gsm.brute_force(st)
        assert a.status == "optimal"
        assert a.objective == pytest.approx(b.objective, abs=1e-6)


def test_serial_line_solutions_are_extreme_points():
    """Graves–Willems: on a serial line every stage either holds a full buffer or passes through."""
    rng = random.Random(7)
    for _ in range(40):
        n = rng.randint(2, 6)
        st = [gsm.Stage(f"s{k}", rng.randint(1, 6), rng.uniform(0.1, 5), [f"s{k-1}"] if k else [],
                        max_service=0 if k == n - 1 else None) for k in range(n)]
        sol = gsm.solve(st)
        for s in st:
            full = sol.inbound[s.id] + s.lead_time
            assert sol.service[s.id] in (0, full), (s.id, sol)
        assert sol.objective <= sum(s.cost * math.sqrt(s.lead_time) for s in st) + 1e-9  # ≤ every-stage buffering


def test_cycle_is_rejected():
    with pytest.raises(ValueError):
        gsm.solve([gsm.Stage("a", 1, 1, ["b"]), gsm.Stage("b", 1, 1, ["a"])])


# ---------------------------------------------------------------- DDMRP
def test_ddmrp_zones_follow_the_formulas():
    s = InventorySettings()  # medium DLT (14 < 20 ≤ 42) → LTF 0.5; CV 0.4 → medium VF 0.5; order cycle 7
    b = ddmrp.size(adu=10, dlt=20, cv_weekly=0.4, moq=0, s=s)
    assert (b.ltf, b.lt_band, b.vf, b.var_band) == (0.5, "medium", 0.5, "medium")
    assert b.yellow == pytest.approx(200)
    assert (b.red_base, b.red_safety, b.red) == pytest.approx((100, 50, 150))
    assert b.green == pytest.approx(100)  # max(10·7, 10·20·0.5, 0)
    assert (b.tor, b.toy, b.tog) == pytest.approx((150, 350, 450))
    assert ddmrp.zone(300, b) == "yellow" and ddmrp.order_qty(300, b) == pytest.approx(150)
    assert ddmrp.zone(400, b) == "green" and ddmrp.order_qty(400, b) == 0
    assert ddmrp.zone(100, b) == "red" and ddmrp.zone(500, b) == "over"
    # the MOQ and the order cycle floor the green zone; short DLT and high CV pick the other factors
    b2 = ddmrp.size(adu=10, dlt=5, cv_weekly=0.9, moq=400, s=s)
    assert (b2.lt_band, b2.ltf, b2.var_band, b2.vf, b2.green) == ("short", 0.7, "high", 0.75, 400)


# ---------------------------------------------------------------- dataset level
def _two_dc() -> dict:
    """Plant P makes A (2×B + 1×C); DCs D1 and D2 are replenished from P over 2-day lanes."""
    d = base(horizon=28)
    d["locations"] += [{"id": "D1", "type": "dc"}, {"id": "D2", "type": "dc"}]
    d["lanes"] = [{"id": f"P-{x}", "origin": "P", "destination": x, "products": ["A"], "modes": [{"transit_days": 2}]}
                  for x in ("D1", "D2")]
    for x in ("D1", "D2"):
        lp(d, x, "A")
    d["products"][0]["standard_cost"] = 100
    for day in range(28):
        date = f"2026-01-{5 + day:02d}" if day < 27 else "2026-02-01"
        d["demand"] += [demand("D1", "A", date, 10), demand("D2", "A", date, 10)]
    return d


def test_demand_flows_upstream_and_variability_pools():
    r = run_inventory(ds(_two_dc()))
    assert r.ok
    by = {(n.location, n.product): n for n in r.nodes}
    d1, pa, pb = by[("D1", "A")], by[("P", "A")], by[("P", "B")]
    assert d1.mean_daily == pytest.approx(10) and d1.cv_weekly == pytest.approx(0.3)
    assert d1.sd_daily == pytest.approx(0.3 * 10 * math.sqrt(7))
    assert pa.mean_daily == pytest.approx(20)
    assert pa.cv_weekly == pytest.approx(0.3 / math.sqrt(2))       # two independent streams pool
    assert pb.mean_daily == pytest.approx(40)                        # 2 B per A
    assert pb.cv_weekly == pytest.approx(pa.cv_weekly)               # one parent: no further pooling
    assert d1.demand_facing and not pa.demand_facing
    assert pa.cv_source == "pooled" and d1.cv_source == "default"


def test_single_echelon_formula_and_meio_never_worse():
    r = run_inventory(ds(_two_dc()))
    by = {(n.location, n.product): n for n in r.nodes}
    d1 = by[("D1", "A")]
    assert d1.single_ss == pytest.approx(Z95 * math.sqrt(2 * d1.sd_daily ** 2))
    assert d1.meio_service_days == 0  # customers are served from stock
    assert r.totals.meio_cost <= r.totals.single_cost + 1e-6
    assert r.solver.status == "optimal"


def test_measured_cv_overrides_and_customer_service_time_relaxes_the_dc():
    d = _two_dc()
    lp(d, "D1", "A")["safety_stock"] = {"method": "service_level", "demand_cv": 0.6}
    d["inventory"] = {"customer_service_days": 2}
    r = run_inventory(ds(d))
    by = {(n.location, n.product): n for n in r.nodes}
    assert by[("D1", "A")].cv_source == "policy" and by[("D1", "A")].cv_weekly == pytest.approx(0.6)
    assert by[("D1", "A")].meio_service_days <= 2
    assert by[("D1", "A")].current_method == "service_level"


def test_mto_nodes_hold_no_stock():
    d = _two_dc()
    lp(d, "P", "A")["strategy"] = "MTO"
    r = run_inventory(ds(d))
    pa = next(n for n in r.nodes if (n.location, n.product) == ("P", "A"))
    assert pa.role == "no_stock" and pa.meio_net_days == 0 and pa.meio_ss == 0


def test_pooling_square_root_law():
    r = run_inventory(ds(_two_dc()))
    (row,) = r.pooling
    assert row.product == "A" and sorted(row.locations) == ["D1", "D2"]
    assert row.pooled_ss == pytest.approx(row.separate_ss / math.sqrt(2))   # equal σ and L
    assert row.saving_pct == pytest.approx(1 - 1 / math.sqrt(2))


def test_ddmrp_positions_decouple_lead_time_and_signal_orders():
    d = _two_dc()
    lp(d, "D1", "A").update(ddmrp_buffer=True, on_hand=5)
    unbuffered = {(x.location, x.product): x for x in run_inventory(ds(d)).ddmrp}
    plant = unbuffered[("P", "A")].dlt
    # with no buffer at the plant, D1's decoupled lead time runs back through P to the supplier
    assert plant > 0 and unbuffered[("D1", "A")].dlt == pytest.approx(2 + plant)
    lp(d, "P", "A")["ddmrp_buffer"] = True
    r = run_inventory(ds(d))
    by = {(x.location, x.product): x for x in r.ddmrp}
    assert by[("D1", "A")].dlt == pytest.approx(2) and by[("D2", "A")].dlt == pytest.approx(2)
    row = by[("D1", "A")]
    assert row.positioned and not by[("D2", "A")].positioned and row.adu == pytest.approx(10)
    assert row.nfp == pytest.approx(5) and row.zone == "red"
    assert row.order_qty == pytest.approx(row.tog - 5)
    assert r.totals.ddmrp_positions == 2


def test_blocked_dataset_returns_issues_only():
    d = _two_dc()
    d["lanes"][0]["origin"] = "NOPE"
    r = run_inventory(ds(d))
    assert not r.ok and r.nodes == [] and r.issues


@pytest.mark.parametrize("name", ["kitchenware_network", "single_product_plant"])
def test_examples_optimise(name):
    r = run_inventory(load_example(name))
    assert r.ok and r.solver.status == "optimal"
    assert r.totals.meio_cost <= r.totals.single_cost + 1e-6
    for n in r.nodes:
        if n.demand_facing and n.role == "stocking":
            assert n.meio_service_days <= (n.max_service_days or 0)
