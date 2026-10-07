"""Property-based planning invariants (Hypothesis). These must hold for ANY valid company, not just the examples:

* lot sizes: every lot is within the minimum and maximum and a multiple of the rounding value
* MRP: planned and firm supply covers the net demand of every deterministic node it can source
* inventory: projected stock never goes below zero silently (every negative bucket is a STOCKOUT exception)
* plans are pure functions of the company: the same input gives byte-identical output
* costs stay in range: no negative cost, the total is the sum of its parts, unit costs are finite

Profiles (tests/conftest.py): ``ci`` is derandomised (the same examples on every run), ``deep`` explores."""
from __future__ import annotations

import json
import math
from collections import defaultdict

import pytest
from hypothesis import assume, given, note
from hypothesis import strategies as st

from scp.model import Dataset
from scp.plan import run_mrp
from scp.plan.lotsize import apply_modifiers

from .strategies import companies, network
from .test_invariants import check_invariants

EPS = 1e-6


def _multiple(q: float, r: float) -> bool:
    return abs(q / r - round(q / r)) < 1e-6


# ---- lot-size modifiers: unit level ---------------------------------------------------------------------------------
@given(qty=st.floats(0.001, 5000, allow_nan=False), mn=st.sampled_from([0.0, 7.0, 20.0, 60.0]),
       r=st.one_of(st.none(), st.sampled_from([1.0, 5.0, 10.0, 12.0, 25.0])),
       mx=st.one_of(st.none(), st.sampled_from([30.0, 35.0, 50.0, 80.0, 150.0])))
def test_lots_are_within_min_max_and_multiples_of_the_rounding(qty, mn, r, mx):
    lots = apply_modifiers(qty, mins=[mn], roundings=[r], maxes=[mx])
    note(f"lots={lots}")
    assert lots and all(q > 0 for q in lots)
    assert sum(lots) >= qty - EPS                                       # the lots cover what was asked
    usable_max = None
    if mx is not None:
        usable_max = math.floor(mx / r + 1e-9) * r if r else mx
        if usable_max <= EPS:                                           # rounding above the maximum: one rounding each
            usable_max = r
    for q in lots:
        if r:
            assert _multiple(q, r), (q, r)
        if usable_max is not None:
            assert q <= usable_max + EPS, (q, usable_max)
        if usable_max is None or mn <= usable_max + EPS:
            assert q >= mn - EPS, (q, mn)
    # never more lots, nor more quantity, than one rounding step beyond what was needed
    if usable_max is not None and len(lots) > 1:
        assert sum(lots[:-1]) < max(qty, mn) + EPS


# ---- whole plans ----------------------------------------------------------------------------------------------------
def _plan(d: dict):
    x = Dataset.model_validate(d)
    return x, run_mrp(x)


@given(companies())
def test_random_companies_hold_the_plan_invariants(d):
    x, r = _plan(d)
    assume(r.ok)
    check_invariants(x, r)


@given(companies())
def test_planned_lots_respect_the_lot_size_rules(d):
    """Every planned order's quantity is within its lot sizing (min, max, rounding, fixed batch) — the rules the
    planner typed, on whole plans (CV-M02 regressions included: replenish-to-max and max-lot splits)."""
    x, r = _plan(d)
    assume(r.ok)
    lps = {(lp.location, lp.product): lp for lp in x.location_products}
    for o in r.orders:
        if o.kind not in ("buy", "make"):
            continue
        lp = lps[(o.location, o.product)]
        ls = lp.lot_sizing
        mx = [m for m in (ls.max_qty,
                          x.production_source_by_id[o.source_id].max_lot if o.kind == "make" else None) if m]
        rounds = [ls.rounding_qty] if ls.rounding_qty else []
        if o.kind == "buy" and (pr := x.purchasing_source_by_id[o.source_id].rounding_qty):
            rounds.append(pr)
        note(f"{o.id} {o.location}/{o.product} qty={o.qty} lot={ls.model_dump(exclude_defaults=True)}")
        if len(rounds) == 1:
            assert _multiple(o.qty, rounds[0]), f"{o.id}: {o.qty} is not a multiple of {rounds[0]}"
        if mx:
            cap = min(mx)
            if len(rounds) == 1:
                cap = math.floor(cap / rounds[0] + 1e-9) * rounds[0] or rounds[0]
            assert o.qty <= cap + EPS, f"{o.id}: {o.qty} above the maximum lot {cap}"


@given(companies())
def test_projected_stock_is_never_negative_without_a_stockout_exception(d):
    """Inventory never goes negative silently: a node whose projected stock dips below zero is reported."""
    x, r = _plan(d)
    assume(r.ok)
    flagged = {(e.location, e.product) for e in r.exceptions if e.code == "STOCKOUT"}
    customers = {loc.id for loc in x.locations if loc.type.value == "customer"}
    for nd in r.nodes:
        if nd.location in customers:
            continue
        if any(b.projected_on_hand < -EPS for b in nd.buckets):
            assert (nd.location, nd.product) in flagged, (nd.location, nd.product)
        for b in nd.buckets:
            assert b.shortage == pytest.approx(max(0.0, -b.projected_on_hand), abs=1e-6)
    # and a stockout always has its reason: supply that could not start in time, a fence, or no source at all
    late = {(o.location, o.product) for o in r.orders if o.start_in_past or o.fence_shifted or o.delay_days}
    late |= {(e.location, e.product) for e in r.exceptions
             if e.code in ("NO_VALID_SOURCE", "START_IN_PAST", "RESCHEDULE_IN", "SCHEDULE_LATE")}
    for loc, prod in flagged:
        assert (loc, prod) in late, f"{loc}/{prod} is short with supply that could have been in time"


@given(st.integers(0, 2**31 - 1))
def test_net_demand_is_covered_when_lead_times_fit_the_horizon(seed):
    """With demand starting after every lead time, no fence and no safety-stock pre-build, MRP covers every
    requirement on time: no node ends any bucket short, and independent demand is filled 100 % on time."""
    d = network(seed, bucket="week")
    first = "2026-04-13"                         # six weeks in: longer than any cumulative lead time generated
    d["demand"] = [{**x, "date": max(x["date"], first)} for x in d["demand"]]
    for lp in d["location_products"]:
        lp["planning_time_fence_days"] = 0
        lp["safety_stock"] = {"method": "none"}          # a safety stock is due today: it may be late by design
    for ps in d["production_sources"]:                   # lead times that do not grow with the lot
        for op in ps["operations"]:
            op.update(setup_hours=0, run_hours_per_unit=0.0001)
    x, r = _plan(d)
    assert r.ok
    assert not [e for e in r.exceptions if e.code in ("NO_VALID_SOURCE", "STOCKOUT")], \
        [(e.code, e.message) for e in r.exceptions if e.severity == "error"]
    for nd in r.nodes:
        assert all(b.shortage <= EPS for b in nd.buckets), (nd.location, nd.product)
    assert r.kpis.on_time_fill_rate == pytest.approx(1.0)
    # pegging: each independent requirement is fully pegged to supply or stock
    pegged = defaultdict(float)
    for p in r.pegs:
        pegged[p.requirement_id] += p.qty
    for q in r.requirements:
        if q.kind in ("forecast", "sales_order"):
            assert pegged[q.id] <= q.qty + EPS


@given(companies())
def test_costs_stay_in_range(d):
    x, r = _plan(d)
    assume(r.ok)
    k = r.kpis
    parts = (k.purchase_cost, k.production_cost, k.setup_cost, k.ordering_cost, k.transport_cost, k.handling_cost,
             k.holding_cost)
    assert all(math.isfinite(p) and p >= -EPS for p in parts), parts
    assert k.total_cost == pytest.approx(sum(parts), rel=1e-9, abs=1e-6)
    assert 0.0 <= k.on_time_fill_rate <= 1.0 + EPS
    assert k.inventory_value_start >= -EPS and k.inventory_value_end >= -EPS and k.inventory_value_avg >= -EPS
    for o in r.orders:
        assert math.isfinite(o.unit_cost) and o.unit_cost >= -EPS
        assert o.total_cost == pytest.approx(sum(o.costs.values()), rel=1e-6, abs=1e-6)
    for nd in r.nodes:
        assert math.isfinite(nd.unit_value) and nd.unit_value >= -EPS
        assert all(b.holding_cost >= -EPS for b in nd.buckets)


@given(companies(), st.sampled_from([0.0, 0.05, 0.1, 0.25, 0.5, 1.0]))
def test_holding_cost_grows_with_the_cost_of_capital(d, wacc):
    """Holding cost is the stock value times (WACC + spread): monotone in the WACC, zero at zero rates."""
    lo = json.loads(json.dumps(d))
    lo["settings"].update(wacc=0.0, holding_spread=0.0)
    hi = json.loads(json.dumps(d))
    hi["settings"].update(wacc=wacc, holding_spread=0.0)
    _, rl = _plan(lo)
    _, rh = _plan(hi)
    assume(rl.ok and rh.ok)
    assert rl.kpis.holding_cost == pytest.approx(0.0, abs=1e-6)
    assert rh.kpis.holding_cost >= rl.kpis.holding_cost - EPS


@pytest.mark.parametrize("field,value", [("wacc", -0.1), ("wacc", 1.5), ("holding_spread", -0.01),
                                         ("holding_spread", 2.0)])
def test_rates_out_of_range_are_refused(field, value):
    d = network(1)
    d["settings"][field] = value
    with pytest.raises(ValueError):
        Dataset.model_validate(d)


@given(companies())
def test_a_plan_is_a_pure_function_of_the_company(d):
    """Same company, same plan, byte for byte (no clock, no hash-order, no global state)."""
    a = run_mrp(Dataset.model_validate(d)).model_dump_json()
    b = run_mrp(Dataset.model_validate(json.loads(json.dumps(d)))).model_dump_json()
    assert a == b
