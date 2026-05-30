"""
MF-34 · Perishability levers (the Systemic finding + MF-1/MF-2).

shelf_life and salvage_rate were collected, swept by the researcher, and named in docstrings but
changed no result anywhere. These tests assert each lever now genuinely MOVES the objective, in all
three solvers that model it — so a future refactor that re-inerts them fails loudly.
"""
from montecarlo import run_montecarlo
from profitmix import solve_profitmix
from procurement import solve_procurement
from conftest import make_product, make_part


def _mc(shelf, salvage, init_inv=80, capacity=5):
    data = {
        'params': {'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
                   'carry_rate': 0.24, 'corr_demand_cost': 0.0},
        'products': [make_product(demand=[20] * 8, shelf=shelf, salvage=salvage,
                                  init_inventory=init_inv, capacity=capacity)],
    }
    return run_montecarlo(data, n_runs=300)['avg_cost']


def test_montecarlo_shelf_life_moves_cost():
    # MF-1 — a short shelf life must cost MORE than a long one (surplus stock spoils).
    short = _mc(shelf=1, salvage=0.0)
    long = _mc(shelf=99, salvage=0.0)
    assert short > long, f"shelf life inert in MC: short={short} not > long={long}"


def test_montecarlo_salvage_moves_cost():
    # MF-1 — higher salvage recovers more on spoilage → lower cost.
    low = _mc(shelf=1, salvage=0.0)
    high = _mc(shelf=1, salvage=0.9)
    assert low > high, f"salvage inert in MC: low-salvage={low} not > high-salvage={high}"


def _pm(salvage):
    data = {
        'planning_horizon_months': 6, 'demand_mode': 'mts',
        'products': [{
            'name': 'Y', 'sell_price': 12.0, 'variable_cost': 1.0,
            'history': [20] * 12, 'forecast': [20] * 6, 'cycle_time': 1.0,
            'shelf_life': 1, 'salvage_rate': salvage, 'carry_rate': 0.24,
            'init_inventory': 200, 'max_demand': 100, 'mape_pct': 15,
            'parts': [{'name': 'm', 'cost': 2.0, 'qty_per': 1.0}],
        }],
        'constraints': {'shared_capacity': 100000},
    }
    return solve_profitmix(data)


def test_profitmix_salvage_moves_profit():
    # MF-2 — salvage write-off is in the objective; low salvage must not beat high salvage.
    low = _pm(0.0)['total_profit']
    high = _pm(0.9)['total_profit']
    assert high >= low, f"salvage inert in profitmix: high={high} < low={low}"


def _proc(shelf, salvage):
    data = {
        'params': {'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
                   'carry_rate_annual': 0.24, 'salvage_rate': salvage,
                   'ss_floor_mode': 'off', 'allow_backorder': True},
        'products': [make_product(demand=[20] * 8, shelf=shelf, salvage=salvage,
                                  init_inventory=120, capacity=100,
                                  parts=[make_part(cost=2.0)])],
    }
    return solve_procurement(data)


def test_procurement_fifo_spoilage_forces_writeoff():
    # Systemic — 120 on hand, demand 20/period, shelf 2 → FIFO forces 60 units to spoil by period 2.
    r = _proc(shelf=2, salvage=0.0)
    assert r['status'] == 'Optimal'
    assert r['expiry_units_total'] > 0, "FIFO spoilage not forced for a perishable surplus"
    assert r['cost_breakdown']['expiry_writeoff'] > 0


def test_procurement_salvage_reduces_writeoff():
    # Systemic — same spoiled units, higher salvage → lower write-off cost.
    lo = _proc(shelf=2, salvage=0.0)['cost_breakdown']['expiry_writeoff']
    hi = _proc(shelf=2, salvage=0.8)['cost_breakdown']['expiry_writeoff']
    assert lo > hi > 0, f"salvage does not lower spoilage cost: lo={lo} hi={hi}"


def test_procurement_nonperishable_has_no_spoilage():
    # Guard the other direction — shelf ≥ horizon must never fabricate a write-off.
    r = _proc(shelf=99, salvage=0.0)
    assert r['expiry_units_total'] == 0
    assert r['cost_breakdown']['expiry_writeoff'] == 0
