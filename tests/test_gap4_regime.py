"""
GAP-4 · HMM regime signal feeds sourcing (was computed and thrown away).

A supplier whose part is in a high-volatility regime gets a tightened effective
concentration cap + a soft penalty steering spend toward stabler alternatives.
"""
from procurement import solve_procurement


def _payload(regime_on, tightening=0.6, persistence=0.9, high_vol=True):
    return {
        'params': {'periods': 8, 'periods_per_year': 52, 'service_level': 0.9,
                   'carry_rate_annual': 0.24, 'ss_floor_mode': 'off', 'allow_backorder': True,
                   'regime_aware_sourcing': regime_on, 'regime_default_cap_pct': 50,
                   'regime_concentration_tightening': tightening, 'regime_penalty_mult': 0.8},
        'products': [
            {'name': 'A', 'demand': [30] * 8, 'capacity': 500, 'yield_pct': 1.0, 'shelf_life': 99,
             'init_inventory': 0, 'parts': [{'name': 'res', 'cost': 5, 'qty_per': 1, 'lead_time': 1,
                                             'supplier_name': 'VolatileCo', 'regime_high_vol': high_vol,
                                             'regime_persistence': persistence, 'max_order': 9999}]},
            {'name': 'B', 'demand': [30] * 8, 'capacity': 500, 'yield_pct': 1.0, 'shelf_life': 99,
             'init_inventory': 0, 'parts': [{'name': 'res', 'cost': 6, 'qty_per': 1, 'lead_time': 1,
                                             'supplier_name': 'StableCo', 'regime_high_vol': False,
                                             'regime_persistence': 0, 'max_order': 9999}]},
        ],
    }


def test_regime_off_emits_no_sourcing_adjustment():
    r = solve_procurement(_payload(False))
    assert r['status'] == 'Optimal'
    assert r['regime_aware_sourcing'] is False
    assert r['regime_sourcing'] == []


def test_high_vol_supplier_cap_is_tightened():
    r = solve_procurement(_payload(True, tightening=0.6, persistence=0.9))
    assert r['status'] == 'Optimal'
    vol = next(s for s in r['regime_sourcing'] if s['supplier'] == 'VolatileCo')
    # effective = 50 × (1 − 0.6 × 0.9) = 50 × 0.46 = 23.0
    assert abs(vol['effective_cap_pct'] - 23.0) < 0.5
    assert vol['effective_cap_pct'] < vol['base_cap_pct']
    assert vol['severity'] == 0.9


def test_only_high_vol_suppliers_listed():
    r = solve_procurement(_payload(True))
    names = [s['supplier'] for s in r['regime_sourcing']]
    assert 'VolatileCo' in names
    assert 'StableCo' not in names          # low-vol supplier untouched


def test_higher_persistence_tightens_more():
    lo = solve_procurement(_payload(True, persistence=0.5))['regime_sourcing'][0]['effective_cap_pct']
    hi = solve_procurement(_payload(True, persistence=0.95))['regime_sourcing'][0]['effective_cap_pct']
    assert hi < lo                          # stickier high-vol regime ⇒ tighter cap
