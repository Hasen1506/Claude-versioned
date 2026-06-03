"""
Capital-structure wedge: source-weighted hurdle + min-WACC optimizer (W5 · F-1, F-2)
====================================================================================
This is the finance wedge the big IBP/Kinaxis suites are weakest on. Two pure
calculations (no MILP needed — these are closed-form / a 1-D sweep), packaged as a
new module so the existing solver logic stays frozen.

F-1 · blended_hurdle(data)
  The owner's real cost of capital is NOT a single textbook Ke. It is the
  amount-weighted blend of every equity source (retained earnings, promoter funds,
  a PE round — each with its own opportunity cost) and every debt source (bank term
  loan, family loan — each with its own rate), with the debt side tax-shielded:
      Ke* = Σ (equity_i · cost_i) / Σ equity_i
      Kd* = Σ (debt_j   · rate_j) / Σ debt_j
      WACC (hurdle) = wE·Ke* + wD·Kd*·(1 − t)
  Returns the blended hurdle + each source's ₹ weight and contribution.

F-2 · min_wacc_structure(data)
  Sweeps the debt ratio and finds the leverage that MINIMIZES WACC, subject to a
  DSCR covenant cap. As leverage rises two things fight:
    • the tax shield pulls WACC down (cheap, deductible debt displaces equity), but
    • Ke rises (Hamada re-levering: βL = βU·(1 + (1−t)·D/E)) and
    • Kd rises (a credit spread that widens with leverage),
  so WACC is U-shaped and has a real trough. The DSCR covenant caps how far right we
  may go: debt is admissible only while NOI / annual_debt_service ≥ min_dscr.
  Returns the full curve, the unconstrained trough, and the DSCR-feasible optimum.
"""
import math


def blended_hurdle(data):
    equity = data.get('equity_sources', []) or []
    debt = data.get('debt_sources', []) or []
    tax = float(data.get('tax_rate', 25)) / 100.0

    def _norm(rows, cost_key):
        out = []
        for r in rows:
            amt = float(r.get('amount', 0) or 0)
            cost = float(r.get(cost_key, r.get('cost', r.get('rate', 0)) or 0))
            out.append({'name': r.get('name', '?'), 'amount': amt, 'cost_pct': cost})
        return out

    eq = _norm(equity, 'cost')
    db = _norm(debt, 'rate')
    eE = sum(r['amount'] for r in eq)
    eD = sum(r['amount'] for r in db)
    V = eE + eD
    if V <= 0:
        return {'error': 'Provide equity_sources and/or debt_sources with positive amounts'}

    ke = sum(r['amount'] * r['cost_pct'] for r in eq) / eE if eE > 0 else 0.0
    kd = sum(r['amount'] * r['cost_pct'] for r in db) / eD if eD > 0 else 0.0
    wE, wD = eE / V, eD / V
    kd_after = kd * (1 - tax)
    wacc = wE * ke + wD * kd_after

    # ₹ weight + contribution-to-WACC of every individual source (so the user sees which
    # rupee is expensive). A source's contribution = (amount/V) · its (after-tax) cost.
    sources = []
    for r in eq:
        sources.append({'name': r['name'], 'kind': 'equity', 'amount': round(r['amount'], 2),
                        'weight_pct': round(r['amount'] / V * 100, 2), 'cost_pct': round(r['cost_pct'], 2),
                        'contribution_pct': round(r['amount'] / V * r['cost_pct'], 3)})
    for r in db:
        c_after = r['cost_pct'] * (1 - tax)
        sources.append({'name': r['name'], 'kind': 'debt', 'amount': round(r['amount'], 2),
                        'weight_pct': round(r['amount'] / V * 100, 2), 'cost_pct': round(r['cost_pct'], 2),
                        'cost_after_tax_pct': round(c_after, 2),
                        'contribution_pct': round(r['amount'] / V * c_after, 3)})

    return {
        'blended_ke': round(ke, 3),
        'blended_kd_pretax': round(kd, 3),
        'blended_kd_after_tax': round(kd_after, 3),
        'equity_amount': round(eE, 2),
        'debt_amount': round(eD, 2),
        'total_capital': round(V, 2),
        'equity_weight_pct': round(wE * 100, 2),
        'debt_weight_pct': round(wD * 100, 2),
        'tax_rate_pct': round(tax * 100, 2),
        'hurdle_wacc': round(wacc, 3),
        'sources': sources,
    }


def min_wacc_structure(data):
    rf = float(data.get('risk_free', 7.0))
    erp = float(data.get('equity_risk_premium', 6.0))
    beta_u = float(data.get('unlevered_beta', 0.9))
    base_kd = float(data.get('base_cost_of_debt', 9.0))     # Kd at zero leverage
    spread_slope = float(data.get('credit_spread_slope', 6.0))  # extra Kd %-pts per unit of D/E
    tax = float(data.get('tax_rate', 25)) / 100.0
    total_capital = float(data.get('total_capital', 0) or 0)
    noi = float(data.get('net_operating_income', 0) or 0)    # for the DSCR covenant
    min_dscr = float(data.get('min_dscr', 1.5))
    d_max = float(data.get('max_debt_ratio', 0.8))
    step = float(data.get('step', 0.05))

    curve = []
    best = None                  # unconstrained min WACC
    best_feasible = None         # min WACC s.t. DSCR ≥ min_dscr
    d = 0.0
    while d <= d_max + 1e-9:
        e_ratio = 1 - d
        # Hamada re-levering of beta with the current D/E.
        de = (d / e_ratio) if e_ratio > 1e-9 else 1e9
        beta_l = beta_u * (1 + (1 - tax) * de)
        ke = rf + beta_l * erp
        kd = base_kd + spread_slope * de            # credit spread widens with leverage
        kd_after = kd * (1 - tax)
        wacc = e_ratio * ke + d * kd_after

        # DSCR covenant: annual debt service on the debt tranche at this leverage.
        debt_amt = total_capital * d
        # Service approximated as interest + a 10% principal amortization (illustrative, governed by Kd).
        debt_service = debt_amt * (kd / 100.0 + 0.10) if debt_amt > 0 else 0.0
        dscr = (noi / debt_service) if debt_service > 0 else None
        feasible = (dscr is None) or (dscr >= min_dscr)

        row = {
            'debt_ratio': round(d, 3),
            'equity_ratio': round(e_ratio, 3),
            'ke': round(ke, 3),
            'kd_pretax': round(kd, 3),
            'kd_after_tax': round(kd_after, 3),
            'wacc': round(wacc, 3),
            'dscr': round(dscr, 2) if dscr is not None else None,
            'dscr_feasible': feasible,
        }
        curve.append(row)
        if best is None or wacc < best['wacc']:
            best = row
        if feasible and (best_feasible is None or wacc < best_feasible['wacc']):
            best_feasible = row
        d += step

    return {
        'curve': curve,
        'min_wacc_point': best,
        'dscr_feasible_optimum': best_feasible,
        'dscr_capped': bool(best and best_feasible and best['debt_ratio'] != best_feasible['debt_ratio']),
        'min_dscr': min_dscr,
        'inputs': {
            'risk_free': rf, 'equity_risk_premium': erp, 'unlevered_beta': beta_u,
            'base_cost_of_debt': base_kd, 'credit_spread_slope': spread_slope,
            'tax_rate_pct': round(tax * 100, 2), 'total_capital': total_capital,
            'net_operating_income': noi,
        },
    }
