"""
GAP-0 · Aggregate Planning / S&OP solver tests.

The whole point of this tier is that it CAN do what the single-period profit-mix LP
cannot: carry inventory across months to pre-build for a seasonal peak, and trade that
off against flexing the workforce. These pin both directions plus the disaggregation.
"""
from aggregate import solve_aggregate

# Low for 6 months, a 4x peak in months 7-9, back to low — the classic seasonal shape.
SEASONAL = [100, 100, 100, 100, 100, 100, 400, 400, 400, 100, 100, 100]


def _solve(**param_overrides):
    params = {
        'init_inventory': 0, 'init_workforce': 100, 'rate_per_worker': 1.0,
        'reg_cost_per_unit': 10, 'ot_cost_per_unit': 15, 'holding_cost_per_unit': 1.0,
        'backorder_cost_per_unit': 50, 'allow_backorder': True,
        'hire_cost': 2000, 'fire_cost': 2000, 'wage_per_worker': 0.0,
        'max_ot_pct': 0.25, 'min_workforce': 0,
    }
    params.update(param_overrides)
    return solve_aggregate({
        'products': [{'name': 'Widget', 'forecast': SEASONAL, 'labor_hours_per_unit': 1.0}],
        'params': params,
    })


def test_expensive_labor_forces_level_prebuild():
    # Hire/fire expensive → hold workforce flat and BUILD AHEAD of the peak (the thing
    # the single-period profitmix LP structurally cannot express).
    r = _solve(hire_cost=2000, fire_cost=2000)
    assert r['status'] == 'Optimal'
    assert r['strategy'] in ('level',)
    assert r['seasonal_prebuild'] is True
    assert r['peak_inventory'] > 0
    # workforce barely moves
    wf = [p['workforce'] for p in r['periods']]
    assert max(wf) - min(wf) < 1e-3


def test_cheap_labor_forces_chase():
    # Cheap hire/fire + expensive holding → flex the workforce to track demand, carry no stock.
    r = _solve(hire_cost=1, fire_cost=1, holding_cost_per_unit=5.0)
    assert r['status'] == 'Optimal'
    assert r['strategy'] == 'chase'
    assert r['seasonal_prebuild'] is False
    wf = [p['workforce'] for p in r['periods']]
    assert max(wf) - min(wf) > 1.0  # workforce genuinely flexes


def test_disaggregation_conserves_quantity():
    # Per-SKU plan must sum to the aggregate net production (reg+ot) across the horizon.
    r = _solve()
    agg_made = sum(p['regular_production'] + p['overtime_production'] for p in r['periods'])
    sku_made = sum(s['total_planned'] for s in r['sku_plans'])
    assert abs(agg_made - sku_made) <= max(1.0, 0.02 * agg_made)


def test_forbidding_backorder_still_solves():
    # With enough workforce, a no-stockout plan must be feasible and carry zero backorder.
    r = _solve(allow_backorder=False, init_workforce=200, hire_cost=10, fire_cost=10)
    assert r['status'] == 'Optimal'
    assert r['total_backorder'] == 0


def test_capacity_shadow_prices_emitted_when_binding():
    # Tight capacity (low rate, no extra hiring room) → at least one binding regular-cap dual,
    # the marginal-value-of-a-worker-period hook GAP-5 consumes.
    r = _solve(max_workforce=100, rate_per_worker=1.0)
    assert r['status'] == 'Optimal'
    assert any(s['binding'] for s in r['shadow_prices'])
