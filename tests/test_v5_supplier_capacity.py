"""
V5-3 — supplier-capacity allocation: suppliers carry finite ₹-spend capacity per
period; the procurement MILP allocates that capacity across the supplier's part
basket and may overflow to a part's BACKUP supplier (premium price, its own lead
time) when the primary binds.

Contracts pinned here:
  · NO caps sent ⇒ byte-identical baseline (status + total_cost unchanged);
  · a binding cap is RESPECTED every period (spend ≤ cap) and the solve stays
    Optimal — the MILP re-times buys across the basket instead of dying;
  · when the cap is too tight for demand, a configured backup lane takes the
    OVERFLOW (backup buys > 0, reported per part and per supplier) and the FG
    plan stays whole; without the backup the same cap forces FG shortage;
  · the backup is NOT free — when the primary has slack capacity the premium
    lane stays untouched (backup_orders all zero). The lane carries the part's
    OWN MOQ + ordering admin (probe-observed: a no-MOQ spot lane became an
    MOQ-evasion loophole the solver preferred over a slack primary).
"""
import copy
import json
from procurement import solve_procurement


def _payload(T=6, cap=None, backup=False, demand=40.0):
    """One FG, two parts that BOTH buy from supplier S1 — the allocation basket."""
    parts = []
    for nm, cost in (('PART-A', 100.0), ('PART-B', 60.0)):
        p = {'name': nm, 'cost': cost, 'qty_per': 1.0, 'lead_time': 1,
             'moq': 1, 'max_order': 100000, 'hold_pct': 24, 'ordering_cost': 50,
             'init_inventory': 50, 'supplier': 'S1'}
        if backup:
            p['backup'] = {'supplier': 'S9', 'premium_pct': 25, 'lead_time': 2}
        parts.append(p)
    body = {'products': [{'name': 'FG', 'demand': [demand] * T, 'capacity': 500,
                          'variable_cost': 10, 'sell_price': 400, 'yield_pct': 1.0,
                          'parts': parts}],
            'params': {'periods': T, 'service_level': 0.9}}
    if cap is not None:
        body['params']['supplier_capacity'] = {'S1': cap}
    return body


def test_no_caps_is_byte_identical_baseline():
    base = solve_procurement(copy.deepcopy(_payload()))
    with_empty = solve_procurement({**copy.deepcopy(_payload()),
                                    'params': {'periods': 6, 'service_level': 0.9,
                                               'supplier_capacity': {}}})
    assert base['status'] == with_empty['status'] == 'Optimal'
    assert abs(base['total_cost'] - with_empty['total_cost']) < 1e-6
    assert with_empty['supplier_allocation'] == []
    assert with_empty['supplier_capacity_active'] is False


def test_binding_cap_is_respected_and_allocated():
    # unconstrained spend: find a period's spend, then cap below the peak
    free = solve_procurement(copy.deepcopy(_payload()))
    assert free['status'] == 'Optimal'
    # ₹6,400/period: 40u × (100+60) = 6,400 is the steady refill rate, so any
    # lumpy MOQ-style batching above it must now be SPREAD across periods.
    capped = solve_procurement(copy.deepcopy(_payload(cap=6400)))
    assert capped['status'] == 'Optimal'
    alloc = capped['supplier_allocation']
    assert len(alloc) == 1 and alloc[0]['supplier'] == 'S1'
    assert set(alloc[0]['parts']) == {'PART-A', 'PART-B'}
    eff = alloc[0]['cap_per_period']
    assert all(s <= eff + 1e-6 for s in alloc[0]['spend']), \
        f"cap violated: {alloc[0]['spend']} vs {eff}"
    # demand is still met — the basket re-timed, it didn't starve the FG
    assert capped['products'][0]['total_shortage'] == 0


def test_overflow_goes_to_backup_when_cap_too_tight():
    # ₹4,800/period < the 40u × ₹160 = ₹6,400 steady refill rate. Under the default
    # NoBO (short==0 hard) the primary alone is honestly INFEASIBLE; the backup
    # lane (25% premium, lt 2) is exactly what restores a whole plan.
    tight = 4800
    no_bk = solve_procurement(copy.deepcopy(_payload(cap=tight)))
    assert no_bk['status'] == 'Infeasible', 'cap should be too tight for the primary alone'
    with_bk = solve_procurement(copy.deepcopy(_payload(cap=tight, backup=True)))
    assert with_bk['status'] == 'Optimal'
    assert with_bk['products'][0]['total_shortage'] == 0
    mats = {m['name']: m for m in with_bk['materials']}
    bk_total = sum(sum(m['backup_orders']) for m in mats.values())
    assert bk_total > 0, 'backup lane never used despite a binding cap'
    assert any(m['backup_supplier'] == 'S9' for m in mats.values() if sum(m['backup_orders']))
    assert with_bk['cost_breakdown']['backup_purchase'] > 0
    # primary spend still honours the cap even while overflowing
    alloc = {a['supplier']: a for a in with_bk['supplier_allocation']}
    assert all(s <= alloc['S1']['cap_per_period'] + 1e-6 for s in alloc['S1']['spend'])
    assert alloc['S1']['overflow_spend'] > 0


def test_backup_is_not_free_when_primary_has_slack():
    # generous cap — the 25% premium lane must stay untouched
    out = solve_procurement(copy.deepcopy(_payload(cap=10_000_000, backup=True)))
    assert out['status'] == 'Optimal'
    assert all(sum(m['backup_orders']) == 0 for m in out['materials'])
    assert out['cost_breakdown']['backup_purchase'] == 0
