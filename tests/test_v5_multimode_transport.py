"""
V5-4 — multi-mode logistics: the per-shipment mode pick in transport.py is
all-or-nothing (one mode carries the whole load). params.mode_split allows a
shipment to SPLIT across modes when a bind makes the single pick wrong:

  · CAPACITY bind — a shipment heavier than every mode's max_kg used to get
    rec=None and silently contribute ₹0 (an unserveable lane reported as free);
    the split bin-packs full loads of a bulk mode + a remainder leg and the
    lane gets a real plan with a real cost;
  · DEADLINE bind — a demand spike used to force the ENTIRE shipment to air;
    the split flies only the consumption bridge (slow transit − days-of-stock,
    buffered) and ships the bulk on the cheap slow lane;
  · toggle OFF ⇒ output byte-identical to baseline (no new keys, same costs);
  · no bind / split not cheaper ⇒ split is None and the single pick stands.
"""
import copy
import json
from transport import solve_transport


def _dump(out):
    out = copy.deepcopy(out)
    out.pop('solve_time', None)
    return json.dumps(out, sort_keys=True)


def test_toggle_off_is_byte_identical():
    ship = {'name': 'L1', 'origin': 'Delhi', 'destination': 'Mumbai',
            'weight_kg': 12000, 'volume_cbm': 5, 'value': 900000, 'deadline_days': 7,
            'is_import': False}
    base = solve_transport({'shipments': [copy.deepcopy(ship)], 'params': {}})
    off = solve_transport({'shipments': [copy.deepcopy(ship)],
                           'params': {'mode_split': False}})
    assert _dump(base) == _dump(off)
    assert 'mode_split_active' not in base
    assert 'split' not in base['shipments'][0]


def test_capacity_split_rescues_overweight_shipment():
    # 70,000 kg domestic: every mode's max_kg is below it (rail tops out at 60,000)
    # so the single-mode pick is rec=None and the lane is silently FREE.
    ship = {'name': 'HEAVY', 'origin': 'Delhi', 'destination': 'Mumbai',
            'weight_kg': 70000, 'volume_cbm': 20, 'value': 5000000, 'deadline_days': 7,
            'is_import': False}
    base = solve_transport({'shipments': [copy.deepcopy(ship)], 'params': {}})
    assert base['shipments'][0]['recommended'] is None
    assert base['total_cost'] == 0, 'baseline silently prices the unserveable lane at 0'
    out = solve_transport({'shipments': [copy.deepcopy(ship)],
                           'params': {'mode_split': True}})
    sp = out['shipments'][0]['split']
    assert sp is not None and sp['recommended'] and sp['reason'] == 'capacity'
    assert sp['single_cost'] is None and sp['saving'] is None
    total_kg = sum(l['weight_kg'] for l in sp['legs'])
    assert abs(total_kg - 70000) < 1
    assert all(l['total_days'] <= 7 for l in sp['legs']), 'a split leg misses the SLA'
    assert out['total_cost'] > 0 and abs(out['total_cost'] - sp['total_cost']) < 1
    assert out['mode_split_active'] is True and out['n_splits'] == 1


def test_split_declined_when_single_mode_is_cheaper():
    # 12,000 kg fits rail whole at the cheapest ₹/kg — no multi-leg plan can beat it.
    ship = {'name': 'OK', 'origin': 'Delhi', 'destination': 'Mumbai',
            'weight_kg': 12000, 'volume_cbm': 5, 'value': 900000, 'deadline_days': 7,
            'is_import': False}
    base = solve_transport({'shipments': [copy.deepcopy(ship)], 'params': {}})
    out = solve_transport({'shipments': [copy.deepcopy(ship)],
                           'params': {'mode_split': True}})
    assert out['shipments'][0]['split'] is None
    assert abs(out['total_cost'] - base['total_cost']) < 1e-6
    assert out['shipments'][0]['recommended'] == base['shipments'][0]['recommended']
    assert out['n_splits'] == 0 and out['split_saving'] == 0


def test_deadline_split_bridges_spike_cheaper_than_full_air():
    # Import lane: sea 18d + customs 4d = 22d; air 4d + 4d = 8d. Stock covers 10d,
    # burn 100 kg/d, value high enough that the baseline override says USE AIR for
    # the WHOLE 4,000 kg. The split flies only the (22−10)d × 100 kg/d bridge
    # (+15% buffer) and sails the rest.
    ship = {'name': 'SPIKE', 'origin': 'Shanghai', 'destination': 'Chennai',
            'weight_kg': 4000, 'volume_cbm': 8, 'value': 10000000, 'deadline_days': 30,
            'demand_spike': True, 'current_stock': 1000, 'daily_consumption': 100}
    base = solve_transport({'shipments': [copy.deepcopy(ship)], 'params': {}})
    alert = base['shipments'][0]['spike_alert']
    assert alert and alert['decision'] == 'USE AIR', 'baseline should fly everything'
    full_air_cost = base['shipments'][0]['recommended']['total_cost']
    out = solve_transport({'shipments': [copy.deepcopy(ship)],
                           'params': {'mode_split': True}})
    s = out['shipments'][0]
    sp = s['split']
    assert sp is not None and sp['recommended'] and sp['reason'] == 'deadline'
    assert s['spike_alert']['decision'] == 'SPLIT FAST+SLOW'
    assert out['spike_alerts'][0]['decision'] == 'SPLIT FAST+SLOW'
    # bridge = (22 − 10) × 100 × 1.15 = 1,380 kg flies; the rest sails
    assert abs(sp['bridge_kg'] - 1380) < 1
    air_leg = next(l for l in sp['legs'] if 'air' in l['mode'])
    sea_leg = next(l for l in sp['legs'] if 'sea' in l['mode'])
    assert air_leg['total_days'] <= 10, 'bridge must land before the stockout'
    assert abs(air_leg['weight_kg'] + sea_leg['weight_kg'] - 4000) < 1
    assert sp['residual_stockout_cost'] == 0, 'buffered bridge fully covers the gap'
    assert sp['total_cost'] < full_air_cost, 'split must beat flying everything'
    assert out['total_cost'] < base['total_cost']
    assert sp['saving'] is not None and sp['saving'] > 0
