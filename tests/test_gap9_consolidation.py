"""
GAP-9 · Transport consolidation across shipments sharing a lane.

The per-shipment mode choice is greedy; this pins the LTL→FTL / LCL→FCL consolidation
bin-packing and that it only recommends consolidation when it actually saves money.
"""
from transport import consolidate_shipments, solve_transport, MODE_SPECS


def _road(n, kg):
    # explicit is_import=False ⇒ road FTL/LTL path
    return [{'name': f'S{i}', 'origin': 'Pune', 'destination': 'Mumbai',
             'weight_kg': kg, 'is_import': False} for i in range(n)]


def test_ltl_to_ftl_consolidation_saves():
    # 6 × 4000 = 24000kg on one road lane. LTL @3.5 = 84000; one FTL truck (cap 25000 @1.8) = 45000.
    c = consolidate_shipments(_road(6, 4000), MODE_SPECS, {})
    assert len(c) == 1
    row = c[0]
    assert row['consolidated_mode'] == 'FTL'
    assert row['cost_individual'] > row['cost_consolidated']
    assert row['saving'] > 0
    assert row['recommend_consolidate'] is True


def test_tiny_shipments_not_consolidated():
    # Two 100kg parcels: an LTL rate beats booking a whole truck → no consolidation.
    c = consolidate_shipments([{'name': 'a', 'origin': 'Pune', 'destination': 'Mumbai', 'weight_kg': 100, 'is_import': False},
                               {'name': 'b', 'origin': 'Pune', 'destination': 'Mumbai', 'weight_kg': 150, 'is_import': False}],
                              MODE_SPECS, {})
    assert c[0]['recommend_consolidate'] is False
    assert c[0]['saving'] == 0.0


def test_bin_packs_into_multiple_full_loads():
    # 60000kg ⇒ 2 full FTL trucks (25k each) + 10000 remainder.
    c = consolidate_shipments(_road(6, 10000), MODE_SPECS, {})
    row = c[0]
    assert row['full_loads'] == 2
    assert row['remainder_kg'] == 10000


def test_single_shipment_lane_skipped():
    assert consolidate_shipments(_road(1, 5000), MODE_SPECS, {}) == []


def test_separate_lanes_not_merged():
    ships = (_road(3, 4000) +
             [{'name': f'D{i}', 'origin': 'Delhi', 'destination': 'Chennai', 'weight_kg': 4000, 'is_import': False} for i in range(3)])
    c = consolidate_shipments(ships, MODE_SPECS, {})
    lanes = {r['lane'] for r in c}
    assert lanes == {'Pune → Mumbai', 'Delhi → Chennai'}


def test_solve_transport_surfaces_consolidation():
    r = solve_transport({'shipments': _road(6, 4000), 'params': {}})
    assert 'consolidation' in r
    assert r['consolidation_saving'] >= 0
    assert r['status'] == 'Optimal'
