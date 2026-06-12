"""V1-3 (PRODUCT_BLUEPRINT_V3 Part 8) — contract + golden tests for the 8 solvers
the May-30 suite did NOT cover: transport, meio, meio_network, linecap,
capital (budget), capital_structure, finance, sequencing.evaluate_line.

Two assert kinds:
  CONTRACT — exact output field names the frontend binds (the B-14 `total_cost` /
             B-15 `total_npv` drift class is caught HERE, before any browser boot).
  GOLDEN   — numbers verified by hand (annuity NPV, z·σ·√τ, √N pooling, 2×2
             transport, Hamiltonian changeover, after-tax WACC), not locked from
             observed output.
"""
import math

from capital import solve_capital_budget
from capital_structure import blended_hurdle
from finance import calc_npv
from linecap import solve_linecap
from meio import solve_meio
from meio_network import solve_meio_network
from sequencing import evaluate_line
from transport import solve_transport


# ── finance.calc_npv — annuity golden, hand-computed ────────────────────────
def test_npv_golden_and_contract():
    r = calc_npv({'rate': 0.10, 'cash_flows': [-1000, 500, 500, 500],
                  'initial_investment': 0})
    # hand: −1000 + 500/1.1 + 500/1.21 + 500/1.331 = 243.43
    assert abs(r['npv'] - 243.43) < 0.01
    assert abs(r['irr'] - 23.38) < 0.1          # hand-bracketed ≈23.4%
    assert r['payback_simple'] == 2
    assert r['decision'] == 'INVEST'
    for k in ('npv', 'irr', 'payback_simple', 'payback_discounted', 'wacc', 'decision'):
        assert k in r


# ── transport — 2×2 with an obvious diagonal optimum ────────────────────────
def test_transport_allocation_golden_and_conservation():
    r = solve_transport({
        'origins': [{'name': 'F1', 'supply': 10}, {'name': 'F2', 'supply': 10}],
        'destinations': [{'name': 'D1', 'demand': 10}, {'name': 'D2', 'demand': 10}],
        'cost_matrix': [[1, 5], [5, 1]]})
    alloc = r['allocation']
    assert alloc['status'] == 'Optimal'
    assert abs(alloc['total_cost'] - 20.0) < 1e-6        # hand: 10·1 + 10·1
    # conservation: each destination receives exactly its demand
    got = {}
    for a in alloc['allocation']:
        got[a['to']] = got.get(a['to'], 0) + a['quantity']
    assert got == {'D1': 10.0, 'D2': 10.0}
    assert 'total_cost' in r                              # top-level shipment-mode field


# ── sequencing.evaluate_line — exact Hamiltonian golden (UNITS: minutes) ─────
def test_sequence_golden_minutes_contract():
    r = evaluate_line({'skus': ['A', 'B', 'C'],
                       'changeover_matrix': {'A': {'B': 10, 'C': 50},
                                             'B': {'A': 10, 'C': 20},
                                             'C': {'A': 50, 'B': 20}},
                       'default_min': 30})
    # hand: cheapest 2-edge path is A→B(10)→C(20) (or its mirror) = 30 min
    assert abs(r['total_changeover_min'] - 30.0) < 1e-6
    assert r['n_changeovers'] == 2
    assert r['basis'] == 'exact'
    # T3 units contract: every emitted duration field is *_min (minutes)
    for k in ('total_changeover_min', 'averaged_approx_min', 'sequence_saving_min',
              'mean_changeover_min'):
        assert k in r


# ── linecap — binding dual equals the lost margin ────────────────────────────
def test_linecap_binding_dual_golden():
    r = solve_linecap({'lines': [{'id': 'L1', 'name': 'L1', 'cap': 50}],
                       'skus': [{'name': 'A', 'demand': 100, 'line': 'L1',
                                 'hours_per_unit': 1.0, 'margin': 40}],
                       'params': {'lost_margin_per_unit': 40}})
    assert r['status'] == 'Optimal'
    ln = r['lines'][0]
    # hand: demand 100 > cap 50 ⇒ binding; one more hour earns the lost margin 40
    assert ln['binding'] is True
    assert abs(ln['shadow_price'] - 40.0) < 1e-6
    assert abs(r['unmet_demand'] - 50.0) < 1e-6
    assert r['any_binding'] is True


def test_linecap_slack_line_has_zero_dual():
    r = solve_linecap({'lines': [{'id': 'L1', 'name': 'L1', 'cap': 500}],
                       'skus': [{'name': 'A', 'demand': 100, 'line': 'L1',
                                 'hours_per_unit': 1.0, 'margin': 40}],
                       'params': {'lost_margin_per_unit': 40}})
    ln = r['lines'][0]
    assert ln['binding'] is False and abs(ln['shadow_price']) < 1e-9
    assert r['unmet_demand'] == 0


# ── capital budget — annuity NPVs by hand; budget admits exactly one ─────────
def test_capital_budget_golden_and_b15_contract():
    r = solve_capital_budget({
        'investments': [
            {'name': 'M1', 'capex': 1000, 'annual_cash_flow': 400, 'useful_life': 5},
            {'name': 'M2', 'capex': 1000, 'annual_cash_flow': 300, 'useful_life': 5}],
        'params': {'budget': 1000, 'rate': 0.10}})
    assert r['status'] == 'Optimal'
    # hand: NPV(M1) = 400·a(5,10%) − 1000 = 400·3.7908 − 1000 = 516.31
    assert abs(r['total_npv'] - 516.31) < 0.05            # B-15: field is total_npv
    assert [s['name'] for s in r['selected']] == ['M1']
    assert [s['name'] for s in r['rejected']] == ['M2']
    assert abs(r['rejected'][0]['npv'] - 137.24) < 0.05   # 300·3.7908 − 1000


# ── capital_structure — after-tax WACC golden (tax_rate is PERCENT) ──────────
def test_blended_hurdle_tax_shield_golden():
    r = blended_hurdle({'debt_sources': [{'name': 'loan', 'amount': 600000, 'rate': 0.09}],
                        'equity_sources': [{'name': 'own', 'amount': 400000, 'cost': 0.14}],
                        'tax_rate': 25})       # UNITS: percent at this boundary
    # hand: kd_after = 0.09·(1−0.25) = 0.0675; WACC = 0.4·0.14 + 0.6·0.0675 = 0.0965
    assert abs(r['blended_kd_after_tax'] - 0.0675) < 1e-3
    assert abs(r['hurdle_wacc'] - 0.0965) < 1e-3
    for k in ('blended_ke', 'debt_weight_pct', 'equity_weight_pct', 'hurdle_wacc'):
        assert k in r


# ── meio — guaranteed-service SS = z·σ·√τ golden ─────────────────────────────
def test_meio_ss_golden():
    r = solve_meio({'stages': [
        {'id': 'rm', 'name': 'rm', 'kind': 'RM', 'lead_time': 2, 'unit_cost': 10,
         'hold_pct': 0.2, 'mu': 100, 'sigma': 20},
        {'id': 'fg', 'name': 'fg', 'kind': 'FG', 'lead_time': 1, 'unit_cost': 50,
         'hold_pct': 0.2, 'mu': 100, 'sigma': 20, 'max_service': 1,
         'suppliers': ['rm']}],
        'params': {'service_level': 0.95}})
    rm = next(s for s in r['stages'] if s['id'] == 'rm')
    # hand: z(0.95)=1.645 → SS = 1.645·20·√2 = 46.5
    assert abs(rm['safety_stock'] - 46.5) < 0.2
    assert r['total_holding_cost'] > 0
    for k in ('stages', 'total_safety_stock_value', 'z', 'service_level'):
        assert k in r


# ── meio_network — √N pooling law golden + the I-6 identity at unit level ────
def test_meionet_pooling_golden_and_identity():
    r = solve_meio_network({'parts': [
        {'id': 'p1', 'name': 'p1', 'unit_cost': 10, 'hold_pct': 0.2, 'lead_time': 2,
         'fgs': [{'name': 'A', 'mu': 100, 'sigma': 30, 'qty_per': 1, 'yield': 0.95},
                 {'name': 'B', 'mu': 80, 'sigma': 25, 'qty_per': 1, 'yield': 0.95}]}],
        'params': {'service_level': 0.95, 'correlation': 0.0}})
    p = r['parts'][0]
    # hand (yield-adjusted σ/0.95): σ_sum = 57.89, σ_pool = √(31.58²+26.32²) = 41.11
    assert abs(p['sigma_pooled'] - 41.11) < 0.1
    assert abs(p['pool_ratio'] - (41.11 / 57.89)) < 0.01
    # I-6 identity: pooled SS strictly below the decentralised sum, capital freed > 0
    assert p['ss_pooled'] < p['ss_decentralised']
    assert r['total_ss_value_pooled'] < r['total_ss_value_decentralised']
    assert r['total_capital_freed'] > 0
