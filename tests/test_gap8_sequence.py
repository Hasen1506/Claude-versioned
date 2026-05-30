"""
GAP-8 · Sequence-dependent (asymmetric) changeover.

The MILP averages the changeover matrix to stay linear; this pins the exact
minimum run order over the real asymmetric matrix and its saving vs that average.
"""
from sequencing import optimal_sequence, evaluate_line
from production import solve_production

# A→B cheap, B→A dear: order matters, and the matrix is asymmetric.
M = {'A': {'B': 5, 'C': 40}, 'B': {'A': 50, 'C': 8}, 'C': {'A': 10, 'B': 45}}


def test_optimal_sequence_finds_cheapest_path():
    r = optimal_sequence(['A', 'B', 'C'], M, default_min=30)
    assert r['sequence'] == ['A', 'B', 'C']        # 5 + 8 = 13
    assert r['total_changeover_min'] == 13.0
    assert r['basis'] == 'exact'
    assert r['n_changeovers'] == 2


def test_asymmetry_respected():
    # Reverse direction is far more expensive; the sequencer must not pick C→B→A (45+50).
    r = optimal_sequence(['A', 'B', 'C'], M)
    assert r['total_changeover_min'] < 40


def test_evaluate_line_reports_saving_vs_average():
    ev = evaluate_line({'skus': ['A', 'B', 'C'], 'changeover_matrix': M})
    assert ev['total_changeover_min'] == 13.0
    assert ev['averaged_approx_min'] > ev['total_changeover_min']
    assert ev['sequence_saving_min'] == round(ev['averaged_approx_min'] - 13.0, 2)


def test_single_sku_has_no_changeover():
    r = optimal_sequence(['A'], M)
    assert r['total_changeover_min'] == 0.0
    assert r['n_changeovers'] == 0


def test_heuristic_path_for_large_line():
    # >8 SKUs uses the NN + reinsertion heuristic and must still return a full permutation.
    skus = [f'S{i}' for i in range(10)]
    r = optimal_sequence(skus, {}, default_min=20)   # empty matrix → all default
    assert r['basis'] == 'heuristic'
    assert sorted(r['sequence']) == sorted(skus)
    assert r['n_changeovers'] == 9


def test_production_emits_sequence_plans():
    pr = solve_production({
        'products': [{'name': n, 'required_qty': 50, 'setup_cost': 10, 'yield_pct': 1.0, 'cycle_time': 1.0}
                     for n in ('A', 'B', 'C')],
        'lines': [{'id': 'L1', 'name': 'Line 1', 'capacity': 200, 'type': 'shared',
                   'products': [0, 1, 2], 'changeover_mins': 30, 'changeover_matrix': M}],
        'params': {'periods': 6, 'changeover_cost': 100},
    })
    assert pr['status'] == 'Optimal'
    assert pr['sequence_plans']
    sp = pr['sequence_plans'][0]
    assert sp['line'] == 'Line 1'
    assert sp['sequence_saving_min'] >= 0
