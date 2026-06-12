"""
V4-1 — profit-aware aggregate objective (explicit toggle) + Q10 σ-aware backorder rider.

Contract under test (aggregate.py):
  · default objective_mode='min_cost' is BYTE-IDENTICAL to the legacy model
    (no 'lost' demand, profit block None, weighting block None);
  · objective_mode='max_profit' prices a lost sale at revenue_per_unit (the LP
    already charges reg/OT for building, so revenue is the coefficient) — when
    serving marginal demand costs more than it sells for (OT ₹ > revenue ₹) the
    LP sheds it (lost > 0) and the profit identity holds:
        profit == revenue × served − total_cost ;
  · when the revenue comfortably beats every cost the profit plan sheds nothing;
  · max_profit with revenue<=0 is rejected loudly (everything free to lose);
  · backorder_sigma_weight scales ONLY the backorder ₹: back_eff = back×(1+w·cv).
"""
import pytest

from aggregate import solve_aggregate


def _payload(demand, **params):
    base = {
        'periods': len(demand),
        'init_workforce': 10, 'init_inventory': 0,
        'rate_per_worker': 10,           # regular cap = 100 u/period
        'reg_cost_per_unit': 100,
        'ot_cost_per_unit': 500,         # expensive OT — the profit trap
        'holding_cost_per_unit': 5,
        'backorder_cost_per_unit': 1000,
        'hire_cost': 0, 'fire_cost': 0, 'wage_per_worker': 0,
        'max_ot_pct': 0.5,
        'min_workforce': 10, 'max_workforce': 10,   # workforce pinned: OT is the only flex
        'allow_backorder': True,
    }
    base.update(params)
    return {'products': [{'name': 'AGG', 'forecast': demand}], 'params': base}


PEAKY = [100, 100, 100, 140, 100, 100]   # 40 u over regular cap in t=4, no room to prebuild? (cap 100 ≡ demand elsewhere)


def test_min_cost_default_has_no_lost_demand():
    res = solve_aggregate(_payload(PEAKY))
    assert res['status'] == 'Optimal'
    assert res['objective_mode'] == 'min_cost'
    assert res['profit'] is None
    assert res['backorder_weighting'] is None
    assert all(p['lost'] == 0 for p in res['periods'])


def test_max_profit_sheds_demand_when_ot_exceeds_revenue():
    # the peak's marginal units need OT at ₹500/u but sell for ₹300 → shed them;
    # regular-time units cost ₹100 and sell for ₹300 → keep (the Q8 trap, priced).
    res = solve_aggregate(_payload(PEAKY, objective_mode='max_profit',
                                   revenue_per_unit=300))
    assert res['status'] == 'Optimal'
    assert res['objective_mode'] == 'max_profit'
    lost = sum(p['lost'] for p in res['periods'])
    assert lost > 0, 'the LP should refuse to serve ₹300 revenue with ₹500 overtime'
    pb = res['profit']
    served = sum(p['demand'] for p in res['periods']) - pb['lost_units']
    assert abs(pb['profit'] - (300 * served - res['total_cost'])) < 1.0
    assert abs(pb['lost_units'] - lost) < 0.5


def test_max_profit_keeps_demand_when_revenue_dominates():
    res = solve_aggregate(_payload(PEAKY, objective_mode='max_profit',
                                   revenue_per_unit=5000))
    assert res['status'] == 'Optimal'
    assert sum(p['lost'] for p in res['periods']) == 0


def test_max_profit_requires_positive_revenue():
    res = solve_aggregate(_payload(PEAKY, objective_mode='max_profit'))
    assert 'error' in res and 'revenue' in res['error']


def test_v42_machine_resource_caps_production():
    # V4-2 — labour says 100 u/period is fine; a machine class that only has
    # 60 machine-hours at 1 hr/u must cap production at 60 u/period and force
    # the overflow into backorder. Without resources the same payload serves all.
    flat = [100] * 4
    free = solve_aggregate(_payload(flat))
    capped_payload = _payload(flat, allow_backorder=True)
    capped_payload['resources'] = [{'name': 'LINE-X', 'hours_per_agg_unit': 1.0,
                                    'capacity_hours': 60.0}]
    capped = solve_aggregate(capped_payload)
    assert free['status'] == capped['status'] == 'Optimal'
    assert free['resources'] is None
    assert free['total_backorder'] == 0
    for pr in capped['periods']:
        assert pr['regular_production'] + pr['overtime_production'] <= 60.0 + 1e-6
    assert capped['total_backorder'] > 0, 'machine ceiling must bite where labour would not'
    rs = capped['resources'][0]
    assert rs['name'] == 'LINE-X' and rs['peak_util'] >= 99.9
    # the binding machine row is priced (a shadow price row exists for it)
    assert any(sp['constraint'].startswith('Machine LINE-X') for sp in capped.get('shadow_prices', []))


def test_sigma_weight_scales_only_backorder_cost():
    # force a real backorder: a late spike the pinned workforce cannot fully serve
    spike = [100, 100, 100, 100, 100, 180]
    base = solve_aggregate(_payload(spike, backorder_cost_per_unit=50, max_ot_pct=0.0))
    wtd = solve_aggregate(_payload(spike, backorder_cost_per_unit=50, max_ot_pct=0.0,
                                   backorder_sigma_weight=2.0, demand_cv=0.5))
    assert base['status'] == wtd['status'] == 'Optimal'
    assert base['backorder_weighting'] is None
    bw = wtd['backorder_weighting']
    assert bw and abs(bw['backorder_cost_effective'] - 50 * (1 + 2.0 * 0.5)) < 1e-6
    # dearer backorder ⇒ the plan gets MORE backorder-averse (prebuilds inventory
    # instead of letting the spike linger) — never more backordered than the base
    assert base['total_backorder'] > 0, 'fixture must actually force a backorder'
    assert wtd['total_backorder'] <= base['total_backorder']
