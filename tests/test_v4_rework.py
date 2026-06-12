"""
V4-6 (Q24) — rework cost adder: the failure stream is priced, not free.

Contract (production.solve_production):
  · x[k,l,t] counts units STARTED; Σx·fy ≥ req means x·(1−fy) units FAIL;
  · each failed unit costs products[k].rework_cost_per_unit (₹/fail) — charged
    in the objective as rw × (1−fy) per unit started (linear, MILP-safe);
  · fy mirrors the Demand constraint exactly: routing-cascaded yield when a
    routing exists, else yield_pct;
  · default 0 ⇒ objective + results byte-identical to pre-V4-6;
  · result surfaces rework_cost (total) + per-product rework_units/rework_cost.
"""
from production import solve_production


def _payload(yield_pct=0.8, rework=None, routing_yield=None, req=80.0):
    prod = {'name': 'Y', 'required_qty': req, 'setup_cost': 0, 'oee': 1.0,
            'yield_pct': yield_pct,
            'routing': [{'line_id': 'L1', 'cycleTimeMin': 6, 'parallelism': 1,
                         'yieldPct': (routing_yield if routing_yield is not None
                                      else yield_pct * 100)}]}
    if rework is not None:
        prod['rework_cost_per_unit'] = rework
    return {
        'products': [prod],
        'lines': [{'id': 'L1', 'name': 'L1', 'capacity': 1000, 'oee': 1.0,
                   'workers_per_shift': 1, 'shifts_per_day': 1, 'hourly_rate': 100}],
        'params': {'periods': 2, 'hrs_per_period': 40, 'hours_per_shift': 8,
                   'makespan_weight': 0},
    }


def test_default_zero_is_byte_identical():
    base = solve_production(_payload())
    explicit = solve_production(_payload(rework=0))
    assert base['status'] == explicit['status'] == 'Optimal'
    assert base['total_cost'] == explicit['total_cost']
    assert base['rework_cost'] == 0.0 and explicit['rework_cost'] == 0.0
    assert base['products'][0]['rework_cost'] == 0.0


def test_failure_stream_is_priced():
    # yield 0.8 → 80 good needs 100 started → 20 fail × ₹50 = ₹1,000 in the objective
    base = solve_production(_payload())
    r = solve_production(_payload(rework=50))
    assert r['status'] == 'Optimal'
    p = r['products'][0]
    assert p['produced'] == 100                       # started, not good
    assert abs(p['rework_units'] - 20.0) <= 0.5       # 100 × (1−0.8)
    assert abs(p['rework_cost'] - 1000.0) <= 25.0     # 20 fails × ₹50
    assert abs(r['rework_cost'] - p['rework_cost']) < 0.01
    assert r['total_cost'] >= base['total_cost'] + 950  # adder lands in the objective


def test_routing_cascaded_yield_drives_the_adder():
    # routing 90% × yield_pct ignored → fy = 0.9: 89 started ≈ 80 good,
    # fails ≈ 8.9 × ₹100 ≈ ₹890 (the QUANTITY gross-up and the PRICED stream agree)
    r = solve_production(_payload(yield_pct=0.5, routing_yield=90, rework=100))
    assert r['status'] == 'Optimal'
    p = r['products'][0]
    assert 88 <= p['produced'] <= 90                  # req/0.9, not req/0.5
    assert abs(p['rework_units'] - p['produced'] * 0.1) <= 0.2
    assert abs(p['rework_cost'] - p['produced'] * 0.1 * 100) <= 25.0
