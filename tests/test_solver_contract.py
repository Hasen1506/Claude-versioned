"""
MF-34 · Solver output-contract tests.

These pin the result keys the UI reads against what each solver actually emits — the exact
class of defect behind MF-29 (dashboard read `var_95`; MC emits `var95`) and MF-30 (UI read
`meio.avg_in_transit_value`). If a rename drifts the contract, these fail instead of silently
rendering a `|| 0`.
"""
from montecarlo import run_montecarlo
from profitmix import solve_profitmix
from production import solve_production
from procurement import solve_procurement
from conftest import make_product


def test_montecarlo_emits_var95_not_var_95(montecarlo_payload):
    # MF-29 — the dashboard reads var95/cvar95 (no underscore). Pin the spelling.
    r = run_montecarlo(montecarlo_payload, n_runs=200)
    for key in ('avg_cost', 'p10', 'p90', 'var95', 'cvar95', 'fragility', 'avg_fill'):
        assert key in r, f"Monte Carlo result missing UI-read key {key!r}"
    assert 'var_95' not in r, "underscore spelling resurfaced — MF-29 would regress"


def test_profitmix_contract(profitmix_payload):
    r = solve_profitmix(profitmix_payload)
    assert r.get('status') == 'Optimal'
    for key in ('total_profit', 'total_revenue', 'margin_pct'):
        assert key in r, f"profitmix result missing UI-read key {key!r}"


def test_production_contract():
    r = solve_production({
        'products': [{'name': 'Y', 'required_qty': 100, 'setup_cost': 10,
                      'yield_pct': 1.0, 'cycle_time': 1.0, 'capacity': 100}],
        'params': {'periods': 4},
    })
    assert r.get('status') == 'Optimal'
    assert 'total_cost' in r


def test_procurement_contract(procurement_payload):
    r = solve_procurement(procurement_payload)
    assert r.get('status') == 'Optimal'
    assert 'cost_breakdown' in r
    # Systemic — the spoilage write-off line now exists (docstring advertised "expiry" for ages).
    assert 'expiry_writeoff' in r['cost_breakdown']
    assert 'expiry_units_total' in r


def test_procurement_meio_emits_in_transit_value():
    # MF-30 — a MEIO network must emit avg_in_transit_value (UI reads result.meio.avg_in_transit_value).
    plant, dc = 'PLANT', 'DC1'
    data = {
        'params': {
            'periods': 6, 'periods_per_year': 52, 'service_level': 0.95,
            'carry_rate_annual': 0.24, 'meio_enabled': True, 'backorder_on': True,
            'ss_floor_mode': 'off',
            'node_init_inventory': {'Yogurt': {dc: 60, plant: 60}},
            'network_nodes': [
                {'id': plant, 'name': 'Plant', 'type': 'plant', 'capacity': 5000},
                {'id': dc, 'name': 'DC1', 'type': 'dc', 'capacity': 5000},
            ],
            'network_lanes': [
                {'id': 'L1', 'from': plant, 'to': dc, 'lead_time_periods': 1, 'transit_carry_pct': 24},
            ],
        },
        'products': [make_product(name='Yogurt', demand=[15] * 6, init_inventory=120, capacity=500)],
    }
    r = solve_procurement(data)
    assert r.get('status') == 'Optimal'
    meio = r.get('meio')
    assert meio is not None and meio.get('enabled')
    assert 'avg_in_transit_units' in meio
    assert 'avg_in_transit_value' in meio, "MF-30 — in-transit working-capital value not emitted"
