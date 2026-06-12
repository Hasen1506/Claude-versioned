"""
V5-1 — multi-site on-hand TRANSACTION layer: the ledger is consumed by netting.

Contracts pinned here (python side — the JS resolver/scoping is probe-observed):
  · production.py: opening_inventory serves the EARLIEST weeks of a time-phased
    schedule (InvBal opens at the ledger qty) while the netted required_qty caps
    the total build — stock on hand is built exactly once, never re-made;
  · production.solve_ctp: the ATP look-ahead balance OPENS at opening_inventory —
    warehouse stock is promisable (it was under-promised by exactly that before);
  · procurement.py: an explicit parts[].init_inventory nets the buy unit-for-unit
    (vs the fabricated avg×(lt+1) default the ledger send replaces).
"""
import copy
from production import solve_production, solve_ctp
from procurement import solve_procurement
from conftest import make_product


def _prod_payload(dem=(20, 20), opening=0.0):
    total = float(sum(dem))
    return {
        'products': [{'name': 'Y',
                      'required_qty': max(0.0, total - opening),   # netted, as the store sends it
                      'opening_inventory': opening,
                      'setup_cost': 0, 'oee': 1.0, 'yield_pct': 1.0,
                      'demand_by_period': [float(d) for d in dem],
                      'routing': [{'line_id': 'L1', 'cycleTimeMin': 60,
                                   'parallelism': 1, 'yieldPct': 100}]}],
        'lines': [{'id': 'L1', 'name': 'L1', 'capacity': 1000, 'oee': 1.0,
                   'workers_per_shift': 1, 'shifts_per_day': 1, 'hourly_rate': 100,
                   'max_ot_hrs_per_worker_per_week': 16, 'changeover_mins': 0}],
        # changeover_cost 0 isolates the netting economics — otherwise starting a SKU
        # in W1 books a changeover and a token 1-unit W0 run is genuinely cheaper.
        'params': {'periods': len(dem), 'hrs_per_period': 40, 'hours_per_shift': 8,
                   'makespan_weight': 0, 'time_phased': True,
                   'holding_cost_per_unit': 1, 'changeover_cost': 0},
    }


def test_opening_inventory_serves_the_earliest_weeks():
    # 30u on hand vs demand (20,20): W0 is covered from stock; only the residual
    # ~10u is built, weighted into W1. (A ≤1u token W0 run is legitimate: the x≥y
    # run floor plus the changeover-avoidance economics — changeover_mins 0 is
    # coerced to 30 by the `or 30` fallback — make a 1u early start cheaper than
    # booking a W1 changeover. The NETTING contract is the 10u total + W1 weight.)
    r = solve_production(_prod_payload(opening=30.0))
    assert r['status'] == 'Optimal'
    made = {t: 0 for t in range(2)}
    for g in r['gantt']:
        made[g['period']] += g['quantity']
    assert made[0] <= 1, 'week 0 must be served from the ledger (≤ token run floor)'
    assert made[1] >= 9
    assert made[0] + made[1] == 10, 'total build = demand − ledger, exactly'


def test_gross_vs_netted_build_differs_by_exactly_the_ledger():
    gross = solve_production(_prod_payload(opening=0.0))
    netted = solve_production(_prod_payload(opening=30.0))
    assert gross['products'][0]['produced'] - netted['products'][0]['produced'] == 30


def test_ctp_atp_balance_opens_at_the_ledger():
    # nothing scheduled, nothing demanded — 10u sitting in the warehouse must be
    # promisable for FREE (pre-V5-1 the balance opened at 0 and bought capacity).
    pl = _prod_payload(dem=(0.0, 0.0), opening=10.0)
    pl['quote'] = {'product': 'Y', 'qty': 5, 'due_period': 0}
    r = solve_ctp(pl)
    assert r['status'] == 'Optimal' and r['covered_by_atp'] is True
    assert r['cost_to_promise'] == 0.0 and r['atp_at_due'] >= 10.0


def _proc_payload(init_rm):
    p = make_product()
    p['parts'] = [dict(p['parts'][0], init_inventory=init_rm)]
    return {'params': {'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
                       'carry_rate_annual': 0.24, 'salvage_rate': 0.8,
                       'ss_floor_mode': 'off', 'allow_backorder': True},
            'products': [p]}


def test_rm_ledger_nets_the_buy_unit_for_unit():
    # both ledgers cover the pre-first-arrival burn (lead 1 ⇒ W0 needs ~20 on hand;
    # a hard-zero start is honestly Infeasible) — the CONTRACT is that +60 in the
    # plant store cuts the buy by exactly 60.
    base = solve_procurement(_proc_payload(20))
    netted = solve_procurement(_proc_payload(80))
    assert base['status'] == netted['status'] == 'Optimal'
    b = [m for m in base['materials'] if m['name'] == 'milk'][0]['total_ordered']
    n = [m for m in netted['materials'] if m['name'] == 'milk'][0]['total_ordered']
    assert b - n == 60, f'+60 in the plant store must cut the buy by 60 (got {b} vs {n})'


def test_absent_key_keeps_the_legacy_fabricated_default():
    # no init_inventory key anywhere ⇒ the avg×(lt+1) smoothing default still applies
    # (old payloads keep their behaviour; only an explicit ledger send changes it)
    p = make_product()
    assert 'init_inventory' not in p['parts'][0]
    r = solve_procurement({'params': {'periods': 8, 'periods_per_year': 52,
                                      'service_level': 0.95, 'carry_rate_annual': 0.24,
                                      'salvage_rate': 0.8, 'ss_floor_mode': 'off',
                                      'allow_backorder': True},
                           'products': [p]})
    assert r['status'] == 'Optimal'
    # fabricated default = avg 20 × qty 1 × (lt+1)=2 = 40 ⇒ buy = 160 − 40 = 120
    assert [m for m in r['materials'] if m['name'] == 'milk'][0]['total_ordered'] == 120
