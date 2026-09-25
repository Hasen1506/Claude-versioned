"""Plan-wide invariants on the examples and on randomly generated networks.

These are the checks that replace the legacy HARNESS gates: they hold for *any* valid dataset.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

import pytest

from scp.plan import run_mrp
from scp.plan.costing import component_factor
from scp.time import Buckets

from .factory import ds, load_example

EPS = 1e-6


def check_invariants(dataset, r):
    assert r.ok
    b = Buckets(dataset.settings)
    n = len(b)
    orders = {o.id: o for o in r.orders}
    # 1. material balance recomputed from raw lists
    reqs = defaultdict(lambda: [0.0] * n)
    recs = defaultdict(lambda: [0.0] * n)
    for q in r.requirements:
        i = b.index_of(q.date)
        if 0 <= i < n:
            reqs[(q.location, q.product)][i] += q.qty
    for o in r.orders:
        i = b.index_of(o.available_date)
        if 0 <= i < n:
            recs[(o.location, o.product)][i] += o.qty
    for rc in r.receipts:
        i = b.index_of(rc.date)
        if 0 <= i < n:
            recs[(rc.location, rc.product)][i] += rc.qty
    for nd in r.nodes:
        key = (nd.location, nd.product)
        poh = nd.on_hand
        for i, bk in enumerate(nd.buckets):
            poh += recs[key][i] - reqs[key][i]
            assert bk.projected_on_hand == pytest.approx(poh, abs=1e-6), (key, i)
            assert bk.gross_independent + bk.gross_dependent == pytest.approx(reqs[key][i], abs=1e-6)
    # 2. pegging never over-allocates, and order qty = pegged + lot excess
    by_req = defaultdict(float)
    by_sup = defaultdict(float)
    for p in r.pegs:
        by_req[p.requirement_id] += p.qty
        by_sup[p.supply_id] += p.qty
    req_qty = {q.id: q.qty for q in r.requirements}
    for rid, q in by_req.items():
        assert q <= req_qty[rid] + EPS
    for oid, o in orders.items():
        assert by_sup[oid] + o.lot_excess == pytest.approx(o.qty, abs=1e-6)
    # 3. every created requirement is sized by its parent order
    for q in r.requirements:
        if q.parent_order is None:
            continue
        o = orders[q.parent_order]
        if q.kind == "transfer":
            assert q.qty == pytest.approx(o.qty)
            assert (q.location, q.product) == (o.origin, o.product)
        else:
            assert q.qty == pytest.approx(o.qty * component_factor(dataset, o.source_id, q.product))
    # 4. supply covers requirements in total for replenished nodes (no NO_VALID_SOURCE raised)
    if not any(e.code == "NO_VALID_SOURCE" for e in r.exceptions):
        sup = defaultdict(float)
        for o in r.orders:
            sup[(o.location, o.product)] += o.qty
        for rc in r.receipts:
            sup[(rc.location, rc.product)] += rc.qty
        tot = defaultdict(float)
        for q in r.requirements:
            tot[(q.location, q.product)] += q.qty
        for nd in r.nodes:
            key = (nd.location, nd.product)
            if nd.mrp_type == "deterministic":
                assert nd.on_hand + sup[key] >= tot[key] - 1e-6, key
    # 5. dates are ordered
    for o in r.orders:
        assert o.start_date <= o.due_date <= o.available_date
        assert o.start_date >= dataset.settings.planning_start


@pytest.mark.parametrize("name", ["kitchenware_network", "single_product_plant"])
def test_examples_hold_invariants(name):
    d = load_example(name)
    check_invariants(d, run_mrp(d))


def random_network(seed: int) -> dict:
    rng = random.Random(seed)
    n_rm, n_sfg, n_fg = rng.randint(2, 6), rng.randint(0, 3), rng.randint(1, 4)
    n_dc, n_cus = rng.randint(0, 3), rng.randint(1, 4)
    bucket = rng.choice(["day", "week", "month"])
    horizon = {"day": 35, "week": 84, "month": 180}[bucket]
    locs = [{"id": "PL", "type": "plant", "calendar": "C6"}, {"id": "SUP", "type": "supplier"}]
    locs += [{"id": f"DC{i}", "type": "dc"} for i in range(n_dc)]
    locs += [{"id": f"K{i}", "type": "customer"} for i in range(n_cus)]
    rms = [f"RM{i}" for i in range(n_rm)]
    sfgs = [f"SF{i}" for i in range(n_sfg)]
    fgs = [f"FG{i}" for i in range(n_fg)]
    prods = ([{"id": p, "type": "RM", "weight_kg": 1} for p in rms] + [{"id": p, "type": "SFG"} for p in sfgs]
             + [{"id": p, "type": "FG", "weight_kg": 2} for p in fgs])

    def policy():
        ls = rng.choice([{"policy": "L4L"}, {"policy": "FIXED", "fixed_qty": rng.choice([25, 100])},
                         {"policy": "POQ", "periods": rng.randint(1, 3)}, {"policy": "EOQ", "ordering_cost": 500},
                         {"policy": "L4L", "min_qty": 30, "rounding_qty": 10, "max_qty": 200}])
        ss = rng.choice([{"method": "none"}, {"method": "fixed", "qty": rng.randint(0, 40)},
                         {"method": "days_of_supply", "days": rng.randint(2, 10)},
                         {"method": "service_level", "service_level": 0.95, "demand_cv": 0.3},
                         {"method": "fill_rate", "service_level": 0.98, "demand_cv": 0.3}])
        return {"lot_sizing": ls, "safety_stock": ss, "on_hand": rng.randint(0, 150),
                "safety_time_days": 0 if ss["method"] != "none" else rng.choice([0, 1]),
                "planning_time_fence_days": rng.choice([0, 0, 3]), "gr_processing_days": rng.choice([0, 1]),
                "unit_cost": rng.randint(5, 50)}

    lps = [{"location": "PL", "product": p, **policy()} for p in rms + sfgs + fgs]
    lps += [{"location": f"DC{i}", "product": p, **policy()} for i in range(n_dc) for p in fgs]
    res = [{"id": "R1", "location": "PL", "units": rng.randint(1, 3), "efficiency": 0.8},
           {"id": "LAB", "location": "PL", "kind": "labor", "units": 10}]
    srcs = []
    for p in sfgs + fgs:
        lower = rms + (sfgs[: sfgs.index(p)] if p in sfgs else sfgs)
        comps = rng.sample(lower, k=min(len(lower), rng.randint(1, 3)))
        srcs.append({"id": f"PV-{p}", "location": "PL", "product": p, "assembly_scrap": rng.choice([0, 0.02]),
                     "components": [{"product": c, "qty": rng.choice([1, 2, 0.5]), "scrap": rng.choice([0, 0.05])}
                                    for c in comps],
                     "operations": [{"seq": 10, "resource": "R1", "setup_hours": rng.choice([0, 2]),
                                     "run_hours_per_unit": rng.choice([0.01, 0.05, 0.2]),
                                     "labor_resource": "LAB", "labor_hours_per_unit": 0.1,
                                     "queue_workdays": rng.choice([0, 1])}]})
    pur = [{"id": f"PIR-{p}", "supplier": "SUP", "product": p, "location": "PL", "price": rng.randint(1, 20),
            "lead_time_days": rng.randint(1, 15), "lead_time_std_days": 1, "moq": rng.choice([0, 50])} for p in rms]
    lanes = []
    for i in range(n_dc):
        lanes.append({"id": f"L-PL-DC{i}", "origin": "PL", "destination": f"DC{i}", "products": fgs,
                      "modes": [{"transit_days": rng.randint(1, 4), "cost_per_kg": 1, "cost_per_shipment": 100,
                                 "vehicle_capacity_kg": 500}]})
    for k in range(n_cus):
        origin = f"DC{rng.randrange(n_dc)}" if n_dc else "PL"
        lanes.append({"id": f"L-{origin}-K{k}", "origin": origin, "destination": f"K{k}",
                      "modes": [{"transit_days": rng.randint(0, 3)}]})
    start = date(2026, 3, 2)
    dem = []
    for k in range(n_cus):
        for p in rng.sample(fgs, k=rng.randint(1, len(fgs))):
            for w in range(horizon // 7):
                if rng.random() < 0.8:
                    dd = start + timedelta(days=w * 7 + rng.randint(0, 6))
                    dem.append({"location": f"K{k}", "product": p, "date": dd.isoformat(),
                                "qty": rng.randint(5, 80), "kind": rng.choice(["forecast", "forecast", "sales_order"]),
                                "period_days": rng.choice([None, 7])})
    return {"settings": {"planning_start": start.isoformat(), "horizon_days": horizon, "bucket": bucket, "default_calendar": "C6"},
            "calendars": [{"id": "C6", "workdays": [0, 1, 2, 3, 4, 5]}], "locations": locs, "products": prods,
            "location_products": lps, "resources": res, "production_sources": srcs, "purchasing_sources": pur,
            "lanes": lanes, "demand": dem, "receipts": []}


@pytest.mark.parametrize("seed", range(40))
def test_random_networks_hold_invariants(seed):
    d = ds(random_network(seed))
    r = run_mrp(d)
    assert r.ok, [i.message for i in r.issues if i.severity == "error"]
    check_invariants(d, r)
