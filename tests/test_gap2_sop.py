"""
GAP-2 · One demand truth + closed-loop reconciliation.

The pipeline ran strictly forward and demand entered each solver independently. These
pin (1) that a single consensus demand vector is stamped onto every solver, and (2) that
production capacity feedback actually revises the mix until the plan is self-consistent.
"""
from reconcile import consensus_demand, run_sop_pipeline


def _base(line_capacity):
    return {
        'aggregate_plan': {'sku_plans': [{'name': 'Widget', 'monthly_plan': [100] * 12,
                                          'total_planned': 1200}]},
        'profit_data': {'products': [{'name': 'Widget', 'sell_price': 50, 'variable_cost': 10,
                                      'cycle_time': 1.0, 'forecast': [80] * 12,
                                      'parts': [{'name': 'm', 'cost': 5, 'qty_per': 1}]}],
                        'constraints': {'shared_capacity': 100000}},
        'procurement_data': {'products': [{'name': 'Widget', 'demand': [100] * 12, 'capacity': 500,
                                           'setup_cost': 50, 'variable_cost': 10, 'sell_price': 50,
                                           'shelf_life': 99, 'yield_pct': 1.0,
                                           'parts': [{'name': 'm', 'cost': 5, 'qty_per': 1, 'lead_time': 1}]}],
                             'params': {'periods': 12, 'service_level': 0.95}},
        'production_data': {'products': [{'name': 'Widget', 'required_qty': 1200, 'setup_cost': 50,
                                          'yield_pct': 1.0, 'cycle_time': 1.0}],
                            'lines': [{'id': 'L1', 'name': 'Line 1', 'capacity': line_capacity,
                                       'type': 'shared', 'products': [0]}],
                            'params': {'periods': 12, 'changeover_cost': 100}},
    }


def test_demand_truth_prefers_aggregate_plan():
    dmap, src = consensus_demand(_base(40))
    assert src == 'aggregate'
    assert sum(dmap['Widget']) == 1200


def test_demand_truth_falls_back_to_forecast():
    data = _base(40)
    data.pop('aggregate_plan')
    dmap, src = consensus_demand(data)
    assert src == 'forecast'
    assert dmap['Widget'] == [80] * 12


def test_capacity_feedback_reconciles_tight_line():
    # cap 40/period × 12 = 480 ≪ requested ~1380 → mix must be rationed and re-solved to feasible.
    r = run_sop_pipeline(_base(40), max_iters=4)
    assert r['status'] == 'Optimal'
    assert r['reconciled'] is True
    assert r['iterations_run'] >= 2                       # at least one re-solve happened
    assert r['iterations'][0]['production_status'] != 'Optimal'   # first pass was infeasible
    assert r['iterations'][-1]['production_status'] == 'Optimal'  # converged feasible
    assert r['final_gaps'] == []
    assert r['procurement']['status'] == 'Optimal'        # procures on the reconciled plan


def test_ample_capacity_converges_first_iteration():
    r = run_sop_pipeline(_base(500), max_iters=4)
    assert r['reconciled'] is True
    assert r['iterations_run'] == 1
    assert r['final_gaps'] == []
