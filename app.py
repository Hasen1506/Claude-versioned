"""
Enterprise Simulator v2.0 — Flask Backend
==========================================
Serves the React SPA + provides solver API endpoints.

Deploy to Render:
  git push → auto-deploys
  
Local:
  pip install -r requirements.txt
  python app.py
  → http://localhost:5000
"""
import os
import json
import time
import traceback
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from solvers.procurement import solve_procurement
from solvers.production import solve_production
from solvers.profitmix import solve_profitmix
from solvers.transport import solve_transport
from solvers.capital import solve_capital_budget
from solvers.montecarlo import run_montecarlo
from solvers.finance import calc_landed_cost, calc_npv, calc_depreciation, calc_wacc
from solvers.report import generate_report
from solvers.disaggregate import disaggregate
from solvers.lot_sizing import solve_lot_sizing
from solvers.pattern_sensing import sense as demand_sense, list_patterns
from solvers.forecast import run_forecast
from solvers.risk import detect_regimes, detect_many
from solvers.aggregate import solve_aggregate
from solvers.cvar import solve_cvar
from solvers.reconcile import run_sop_pipeline
from solvers.policy import derive_policies
from solvers.capital_capacity import solve_capital_capacity
from solvers.sequencing import evaluate_line as sequence_evaluate_line
from solvers.transport import consolidate_shipments, MODE_SPECS as TRANSPORT_MODE_SPECS

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)


# ─── Static Frontend ───
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ─── Favicon (inline SVG, no file needed) ───
@app.route('/favicon.ico')
def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="6" fill="#0d1117"/>'
        '<text x="16" y="22" font-size="18" text-anchor="middle" fill="#00d4aa" '
        'font-family="monospace" font-weight="bold">ES</text>'
        '</svg>'
    )
    from flask import Response
    return Response(svg, mimetype='image/svg+xml')


# ─── Health Check ───
@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'version': '2.0.0',
        'solver': 'PuLP CBC',
        'timestamp': time.time(),
    })


# ─── Procurement MILP Solver ───
@app.route('/api/solve/procurement', methods=['POST'])
def api_solve_procurement():
    try:
        data = request.json
        result = solve_procurement(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'error': str(e),
            'trace': traceback.format_exc()
        }), 500


# ─── Rolling-horizon MPS re-planning ───
@app.route('/api/solve/rolling', methods=['POST'])
def api_solve_rolling():
    """Re-plan procurement on a rolling horizon. For each wave, freeze the first
    frozen_weeks of the previous plan, shift horizon forward, re-solve, and
    collect plan changes. Returns: waves[], nervousness, final_plan."""
    try:
        data = request.json
        waves = int(data.get('n_waves', 4))
        shift = int(data.get('shift_weeks', 4))
        frozen = int(data.get('frozen_weeks', 2))
        base = data.get('base', {})
        results = []
        prev_plan = None
        nervousness = 0
        for w in range(waves):
            # Slice demand forward by shift*w weeks — simulate time passing
            sliced = dict(base)
            # (MF-6) Slide the horizon FORWARD over the known demand series and pad newly-revealed
            # tail periods with a naive forecast (trailing mean) — NOT a cyclic wrap. The old
            # `demand[w*shift:] + demand[:w*shift]` rotated the tail to the front, injecting phantom
            # demand spikes and making "nervousness" a permutation artifact rather than a measure of
            # re-planning churn. Sliding forward + fresh-forecast tail is a genuine rolling re-plan.
            products = []
            for p in base.get('products', []):
                demand = list(p.get('demand', []))
                n_d = len(demand)
                start = min(w * shift, n_d)
                window = demand[start:]
                if len(window) < n_d:
                    fresh = round(sum(demand) / n_d) if n_d else 0  # trailing-mean naive forecast
                    window = window + [fresh] * (n_d - len(window))
                products.append({**p, 'demand': window})
            sliced['products'] = products
            # Add frozen constraint marker
            params = dict(base.get('params', {}))
            params['frozen_weeks'] = frozen
            params['wave_index'] = w
            sliced['params'] = params
            res = solve_procurement(sliced)
            # Measure nervousness — delta between this wave's wk-(frozen..shift) vs prev plan's
            if prev_plan and not res.get('error'):
                prev_po = prev_plan.get('procurement_schedule', [])
                curr_po = res.get('procurement_schedule', [])
                prev_map = {(po.get('week'), po.get('part')): po.get('qty', 0) for po in prev_po}
                for po in curr_po:
                    key = (po.get('week'), po.get('part'))
                    if key in prev_map:
                        nervousness += abs(po.get('qty', 0) - prev_map[key])
            results.append({'wave': w, 'shift_weeks': w * shift, 'total_cost': res.get('total_cost', 0),
                            'solve_time': res.get('solve_time', 0), 'error': res.get('error')})
            prev_plan = res
        return jsonify({'waves': results, 'nervousness': nervousness,
                        'final_plan': prev_plan, 'frozen_weeks': frozen, 'shift_weeks': shift})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Monte Carlo Simulation ───
@app.route('/api/solve/montecarlo', methods=['POST'])
def api_solve_montecarlo():
    try:
        data = request.json
        n_runs = data.get('n_runs', 500)
        result = run_montecarlo(data, n_runs=n_runs)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Sensitivity Analysis ───
@app.route('/api/solve/sensitivity', methods=['POST'])
def api_solve_sensitivity():
    try:
        data = request.json
        base_data = data.get('base_data', {})
        param_ranges = data.get('param_ranges', {})
        results = []

        # For each parameter, sweep values and run MC
        for param_name, values in param_ranges.items():
            for val in values:
                modified = json.loads(json.dumps(base_data))
                # Apply parameter change
                if '.' in param_name:
                    parts = param_name.split('.')
                    obj = modified
                    for p in parts[:-1]:
                        obj = obj.get(p, {})
                    obj[parts[-1]] = val
                else:
                    modified['params'][param_name] = val

                mc_result = run_montecarlo(modified, n_runs=100)
                results.append({
                    'param': param_name,
                    'value': val,
                    'avg_cost': mc_result['avg_cost'],
                    'var95': mc_result['var95'],
                    'fill': mc_result['avg_fill'],
                })

        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Auto-Researcher (150 experiments) ───
@app.route('/api/solve/researcher', methods=['POST'])
def api_solve_researcher():
    try:
        data = request.json
        import numpy as np
        rng = np.random.default_rng()
        base_data = data.get('base_data', {})
        mode = data.get('mode', 'fixed')  # fixed or upgrade
        n_experiments = min(data.get('n_experiments', 150), 200)

        # Parameter ranges for exploration
        sl_values = [0.85, 0.90, 0.95, 0.99]
        setup_values = [20, 50, 100, 200]
        hold_delay = [0, 1, 3, 7]

        if mode == 'upgrade':
            cap_values = [20, 35, 50, 80]
            yield_values = [0.85, 0.90, 0.95, 1.0]
            shelf_values = [4, 8, 12, 26, 52]

        experiments = []
        for exp in range(n_experiments):
            modified = json.loads(json.dumps(base_data))
            config = {}

            # Randomize parameters
            sl = float(rng.choice(sl_values))
            modified['params']['service_level'] = sl
            config['service_level'] = sl

            setup = int(rng.choice(setup_values))
            for prod in modified.get('products', []):
                prod['setup_cost'] = setup
            config['setup_cost'] = setup

            if mode == 'upgrade':
                cap = int(rng.choice(cap_values))
                for prod in modified.get('products', []):
                    prod['capacity'] = cap
                config['capacity'] = cap

                fy = float(rng.choice(yield_values))
                for prod in modified.get('products', []):
                    prod['yield_pct'] = fy
                config['yield_pct'] = fy

                sh = int(rng.choice(shelf_values))
                for prod in modified.get('products', []):
                    prod['shelf_life'] = sh
                config['shelf_life'] = sh

            # Run MC (fast: 50 runs)
            mc = run_montecarlo(modified, n_runs=50)
            experiments.append({
                'config': config,
                'avg_cost': mc['avg_cost'],
                'var95': mc['var95'],
                'fill': mc['avg_fill'],
                'fragility': mc['fragility'],
            })

        # Sort by avg_cost
        experiments.sort(key=lambda x: x['avg_cost'])

        # Get baseline
        baseline_mc = run_montecarlo(base_data, n_runs=50)
        baseline_cost = baseline_mc['avg_cost']

        for exp in experiments:
            exp['savings_pct'] = round(
                (baseline_cost - exp['avg_cost']) / max(baseline_cost, 1) * 100, 1
            )

        return jsonify({
            'baseline_cost': baseline_cost,
            'experiments': experiments[:20],  # top 20
            'total_run': n_experiments,
            'mode': mode,
        })
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Finance: Landed Cost ───
@app.route('/api/calc/landed-cost', methods=['POST'])
def api_landed_cost():
    try:
        return jsonify(calc_landed_cost(request.json))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Finance: NPV ───
@app.route('/api/calc/npv', methods=['POST'])
def api_npv():
    try:
        return jsonify(calc_npv(request.json))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Finance: Depreciation ───
@app.route('/api/calc/depreciation', methods=['POST'])
def api_depreciation():
    try:
        return jsonify(calc_depreciation(request.json))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Finance: WACC ───
@app.route('/api/calc/wacc', methods=['POST'])
def api_wacc():
    try:
        return jsonify(calc_wacc(request.json))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Production Scheduler MILP ───
@app.route('/api/solve/production', methods=['POST'])
def api_solve_production():
    try:
        return jsonify(solve_production(request.json))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── R15 / Phase 3 · D4 — Production Sensitivity (CapEx Expansion Suggester) ───
# Takes a base production payload + a list of scenarios. Each scenario is a perturbation:
#   {line_idx, type:'shift'|'machine'|'worker', delta, capex}
# Re-solves production.py once per scenario and returns delta_cost, delta_throughput, payback.
# Payback = capex / annual_delta_margin where annual_delta_margin = avg per-unit margin × delta_throughput × periods_per_year.
@app.route('/api/solve/production-sensitivity', methods=['POST'])
def api_solve_production_sensitivity():
    try:
        data = request.json or {}
        base = data.get('base', {})
        scenarios = data.get('scenarios', [])
        avg_margin = float(data.get('avg_margin_per_unit', 0) or 0)
        periods_per_year = int(data.get('periods_per_year', 52) or 52)

        base_result = solve_production(base)
        base_cost = base_result.get('total_cost', 0)
        base_produced = sum(int(l.get('total_produced', 0) or 0) for l in (base_result.get('lines') or []))

        out = []
        for sc in scenarios:
            modified = json.loads(json.dumps(base))
            line_idx = int(sc.get('line_idx', 0))
            stype = sc.get('type', 'shift')
            delta = float(sc.get('delta', 1) or 1)
            capex = float(sc.get('capex', 0) or 0)
            lines = modified.get('lines') or []
            if 0 <= line_idx < len(lines):
                L = lines[line_idx]
                orig_shifts = max(float(L.get('shifts_per_day', 1) or 1), 1)
                cap_factor = 1.0
                if stype == 'shift':
                    cap_factor = 1 + delta / orig_shifts
                    L['shifts_per_day'] = orig_shifts + delta
                    L['capacity'] = int(float(L.get('capacity', 50) or 50) * cap_factor)
                elif stype == 'machine':
                    cap_factor = 1 + 0.5 * delta  # heuristic: +1 machine lifts cap ~50% when bottleneck-relief
                    L['capacity'] = int(float(L.get('capacity', 50) or 50) * cap_factor)
                elif stype == 'worker':
                    cap_factor = 1 + 0.1 * delta  # workers rarely lift cap unless labor-bound
                    L['workers_per_shift'] = float(L.get('workers_per_shift', 1) or 1) + delta
                    L['capacity'] = int(float(L.get('capacity', 50) or 50) * cap_factor)
                # (MF-3) The machine-hours model (production.py LineCapHrs / _route_cap) derives
                # capacity from per-line cycle_time_by_sku_min + hrs_per_period and IGNORES the flat
                # capacity/shifts_per_day fields above once cycle data is present — so the old
                # perturbation no-op'd (delta_throughput=0, payback None) on any modern payload. Also
                # scale this line's cycle minutes by 1/cap_factor: a faster effective cycle == the
                # throughput the added shift/machine/worker buys, in the basis the solver actually reads.
                by_sku = L.get('cycle_time_by_sku_min')
                if isinstance(by_sku, dict) and by_sku and cap_factor > 0:
                    L['cycle_time_by_sku_min'] = {kk: (float(vv) / cap_factor) for kk, vv in by_sku.items()}
            sc_result = solve_production(modified)
            sc_cost = sc_result.get('total_cost', 0)
            sc_produced = sum(int(l.get('total_produced', 0) or 0) for l in (sc_result.get('lines') or []))
            delta_cost = sc_cost - base_cost
            delta_thru = sc_produced - base_produced
            annual_delta_margin = avg_margin * max(0, delta_thru) * (periods_per_year / max(1, base.get('params', {}).get('periods', 26)))
            payback = (capex / annual_delta_margin) if annual_delta_margin > 0 else None
            out.append({
                'label': sc.get('label') or f"{stype} +{delta} on line {line_idx}",
                'line_idx': line_idx,
                'type': stype,
                'delta': delta,
                'capex': capex,
                'delta_cost': round(delta_cost, 2),
                'delta_throughput': delta_thru,
                'annual_delta_margin': round(annual_delta_margin, 2),
                'payback_years': round(payback, 2) if payback is not None else None,
                'status': sc_result.get('status', '—'),
            })

        return jsonify({
            'status': 'Optimal',
            'base_cost': round(base_cost, 2),
            'base_produced': base_produced,
            'scenarios': out,
            'avg_margin_per_unit': avg_margin,
        })
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Profit Maximizer LP ───
@app.route('/api/solve/profitmix', methods=['POST'])
def api_solve_profitmix():
    try:
        return jsonify(solve_profitmix(request.json))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Transport Optimizer ───
@app.route('/api/solve/transport', methods=['POST'])
def api_solve_transport():
    try:
        return jsonify(solve_transport(request.json))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Capital Budget Optimizer ───
@app.route('/api/solve/capital', methods=['POST'])
def api_solve_capital():
    try:
        return jsonify(solve_capital_budget(request.json))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Forecast Engine (v3.6 P3) ───
@app.route('/api/forecast', methods=['POST'])
def api_forecast():
    try:
        return jsonify(run_forecast(request.json))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Round 4 P6 — HMM Regime Detection (procurement risk) ───
@app.route('/api/risk/regimes', methods=['POST'])
def api_risk_regimes():
    """Detect low-vol / high-vol regimes in price (or any 1-D) series via 2-state Gaussian HMM.

    Two call shapes:
      single:  {"series":[...], "n_iter":30}
      batch:   {"rows":[{"name":"PartA","series":[...]}, ...], "n_iter":30}
    """
    try:
        data = request.json or {}
        if 'rows' in data:
            return jsonify(detect_many(data))
        return jsonify(detect_regimes(data.get('series', []), n_iter=int(data.get('n_iter', 30))))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Aggregate Production Planning / S&OP (GAP-0) ───
@app.route('/api/solve/aggregate', methods=['POST'])
def api_solve_aggregate():
    """Multi-period Hax–Meal aggregate plan: level-vs-chase over monthly buckets
    with regular/overtime production, hire/fire, inventory carry, and backorder.
    This is the missing middle tier (GAP-0) — the only place seasonal build-ahead
    can actually be planned, and the coherent quantity source for downstream solvers."""
    try:
        return jsonify(solve_aggregate(request.json or {}))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── CVaR optimization (Rockafellar–Uryasev) — GAP-1 ───
@app.route('/api/solve/cvar', methods=['POST'])
def api_solve_cvar():
    """CVaR-β-optimal newsvendor order-up-to level via the R–U linear program.
    Returns the robust stocking level, its CVaR/VaR, and the robustness premium
    over the expected-value (critical-ratio) plan. Procurement consumes the same
    formulation as a safety-stock floor when params.ss_source='cvar'."""
    try:
        return jsonify(solve_cvar(request.json or {}))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Solver Pipeline: Profit → Procurement → Production ───
@app.route('/api/solve/pipeline', methods=['POST'])
def api_solve_pipeline():
    """Chain solvers: profit mix determines WHAT to produce,
    procurement determines HOW to source materials,
    production determines WHEN to schedule on lines."""
    try:
        data = request.json
        results = {}

        # Step 1: Profit mix — determine optimal quantities
        profit_data = data.get('profit_data', {})
        if profit_data.get('products'):
            profit_result = solve_profitmix(profit_data)
            results['profit_mix'] = profit_result

            # Step 2: Feed quantities into procurement using hierarchical disaggregation
            if profit_result.get('status') == 'Optimal':
                proc_data = data.get('procurement_data', {})
                calendar = data.get('calendar', {})

                # Disaggregate annual profit mix → weekly using seasonal profile
                disagg_input = {
                    'products': [],
                    'calendar': {
                        'work_days_per_week': calendar.get('work_days_per_week', 6),
                        'start_month': calendar.get('start_month', 0),
                    }
                }
                for k, p in enumerate(proc_data.get('products', [])):
                    if k < len(profit_result.get('products', [])):
                        opt_qty = profit_result['products'][k].get('quantity', 0)
                        forecast = p.get('demand', [])  # use existing demand as seasonal profile
                        disagg_input['products'].append({
                            'name': p.get('name', f'P{k}'),
                            'annual_qty': round(opt_qty),
                            'forecast_monthly': forecast[:12] if len(forecast) >= 12 else forecast,
                        })

                disagg_result = disaggregate(disagg_input)
                results['disaggregation'] = disagg_result

                # Override procurement demand with disaggregated weekly quantities
                for k, p in enumerate(proc_data.get('products', [])):
                    if k < len(disagg_result.get('products', [])):
                        dr = disagg_result['products'][k]
                        T = proc_data.get('params', {}).get('periods', 26)
                        weekly = dr.get('weekly', [])
                        p['demand'] = weekly[:T] if len(weekly) >= T else weekly + [weekly[-1] if weekly else 0] * (T - len(weekly))

                proc_result = solve_procurement(proc_data)
                results['procurement'] = proc_result

                # Step 3: Feed production requirements into scheduler
                prod_data = data.get('production_data', {})
                if prod_data.get('products'):
                    for k, p in enumerate(prod_data.get('products', [])):
                        if k < len(profit_result.get('products', [])):
                            p['required_qty'] = round(profit_result['products'][k].get('quantity', 0))
                    prod_result = solve_production(prod_data)
                    results['production'] = prod_result

        results['pipeline_status'] = 'complete'
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Transport consolidation (GAP-9) ───
@app.route('/api/solve/consolidate', methods=['POST'])
def api_solve_consolidate():
    """LTL→FTL / LCL→FCL consolidation across shipments sharing a lane: bin-pack the
    combined weight into full loads and report the saving vs shipping each individually."""
    try:
        data = request.json or {}
        modes = {k: {**v} for k, v in TRANSPORT_MODE_SPECS.items()}
        for mn, ov in (data.get('params', {}).get('mode_overrides', {}) or {}).items():
            if mn in modes:
                modes[mn].update(ov)
        return jsonify({'consolidation': consolidate_shipments(data.get('shipments', []), modes, data.get('params', {}))})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Sequence-dependent changeover (GAP-8) ───
@app.route('/api/solve/sequence', methods=['POST'])
def api_solve_sequence():
    """Cheapest run order over the asymmetric changeover matrix for a set of SKUs
    (shortest Hamiltonian path), plus the saving vs the averaged approximation."""
    try:
        return jsonify(sequence_evaluate_line(request.json or {}))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Multi-period capital plan w/ endogenous capacity (GAP-5) ───
@app.route('/api/solve/capital-capacity', methods=['POST'])
def api_solve_capital_capacity():
    """Multi-period capital plan: invest[i,t] timing under a rollover budget, where a
    'capacity' option's NPV is DERIVED from the throughput it unlocks (capacity_hours ×
    margin_per_hour × utilization − opex, margin defaulting to the capacity shadow price),
    then risk-adjusted by a Monte Carlo pass on the cash-flow drivers."""
    try:
        return jsonify(solve_capital_capacity(request.json or {}))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Inventory policy derivation (GAP-3) ───
@app.route('/api/solve/policy', methods=['POST'])
def api_solve_policy():
    """Derive per-part (s,S) continuous-review and (R,Q) periodic-review reorder
    policies (EOQ + safety stock from LT/demand variability) from a procurement-shaped
    payload. The operational output planners actually run, vs. a frozen PO schedule."""
    try:
        return jsonify(derive_policies(request.json or {}))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Closed-loop S&OP pipeline (GAP-2) ───
@app.route('/api/solve/sop', methods=['POST'])
def api_solve_sop():
    """One demand truth + capacity feedback. Stamps a single consensus demand vector
    onto every solver, runs profit → produce, and re-solves the mix with a tightened
    ceiling wherever production is capacity-bound below the requested quantity — then
    procures on the reconciled plan. Turns the forward report pipeline into S&OP."""
    try:
        data = request.json or {}
        return jsonify(run_sop_pipeline(
            data,
            max_iters=int(data.get('max_iters', 3)),
            tol=float(data.get('tol', 0.02)),
        ))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Hierarchical Disaggregation ───
@app.route('/api/calc/disaggregate', methods=['POST'])
def api_disaggregate():
    try:
        return jsonify(disaggregate(request.json))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Lot-Sizing Policies (v3.2) ───
@app.route('/api/solve/lotsizing', methods=['POST'])
def api_lot_sizing():
    """Run one policy or 'auto' (evaluate all, pick cheapest per part)."""
    try:
        return jsonify(solve_lot_sizing(request.json or {}))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Demand Sensing — SAP IBP-style pattern sensing (v3.2) ───
@app.route('/api/demand/sense', methods=['POST'])
def api_demand_sense():
    """Pattern-match recent actuals against library, blend sensed + statistical."""
    try:
        return jsonify(demand_sense(request.json or {}))
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/api/demand/patterns', methods=['GET'])
def api_demand_patterns():
    """Return the pattern library for UI documentation."""
    try:
        return jsonify({'patterns': list_patterns()})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── PDF Report Export ───
@app.route('/api/report/pdf', methods=['POST'])
def api_report_pdf():
    try:
        from flask import Response
        pdf_bytes = generate_report(request.json)
        return Response(pdf_bytes, mimetype='application/pdf',
                        headers={'Content-Disposition': 'attachment;filename=supply_chain_report.pdf'})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── What-If Bot (Claude API proxy) ───
@app.route('/api/whatif', methods=['POST'])
def api_whatif():
    """Interpret natural language scenario and map to parameter changes."""
    try:
        query = request.json.get('query', '')
        context = request.json.get('context', {})

        # Rule-based interpretation (no external API needed)
        changes = []
        query_lower = query.lower()

        # Price changes
        if any(w in query_lower for w in ['price up', 'cost up', 'price increase', 'material up']):
            pct = 20
            for w in query_lower.split():
                try:
                    v = int(w.replace('%', ''))
                    if 1 <= v <= 200:
                        pct = v
                except:
                    pass
            changes.append({'param': 'bom_cost', 'change': f'+{pct}%', 'reason': f'Material cost increase by {pct}%'})

        if any(w in query_lower for w in ['price down', 'cost down', 'cheaper', 'discount']):
            pct = 15
            for w in query_lower.split():
                try:
                    v = int(w.replace('%', ''))
                    if 1 <= v <= 80:
                        pct = v
                except:
                    pass
            changes.append({'param': 'bom_cost', 'change': f'-{pct}%', 'reason': f'Material cost decrease by {pct}%'})

        # Demand changes
        if any(w in query_lower for w in ['demand doubles', 'demand spike', 'demand up', 'demand increase']):
            mult = 2 if 'double' in query_lower else 1.5
            changes.append({'param': 'demand', 'change': f'×{mult}', 'reason': f'Demand multiplied by {mult}'})

        if any(w in query_lower for w in ['demand drops', 'demand down', 'demand decrease', 'recession']):
            changes.append({'param': 'demand', 'change': '×0.7', 'reason': 'Demand drops 30%'})

        # Lead time
        if any(w in query_lower for w in ['lead time', 'delivery delay', 'supplier delay']):
            changes.append({'param': 'lead_time', 'change': '+2 weeks', 'reason': 'Supplier lead time increases'})

        # Capacity
        if any(w in query_lower for w in ['capacity up', 'new machine', 'add line', 'expand']):
            changes.append({'param': 'capacity', 'change': '+50%', 'reason': 'Production capacity expansion'})

        if any(w in query_lower for w in ['capacity down', 'machine break', 'line down']):
            changes.append({'param': 'capacity', 'change': '-30%', 'reason': 'Capacity reduction'})

        # Shelf life
        if any(w in query_lower for w in ['shelf life', 'expiry', 'perishab']):
            changes.append({'param': 'shelf_life', 'change': 'varies', 'reason': 'Shelf life parameter change'})

        # Currency
        if any(w in query_lower for w in ['rupee', 'inr', 'dollar', 'forex', 'exchange', 'currency']):
            changes.append({'param': 'exchange_rate', 'change': '±5-10%', 'reason': 'Currency fluctuation impact on import costs'})

        # New supplier
        if any(w in query_lower for w in ['new supplier', 'alternative', 'backup', 'second source']):
            changes.append({'param': 'supplier', 'change': 'add backup', 'reason': 'New supplier qualification reduces supply risk'})

        if not changes:
            changes.append({'param': 'unknown', 'change': '?', 'reason': 'Could not parse scenario. Try: "material cost up 20%", "demand doubles in Dec", "new supplier with LT=2w"'})

        # (MF-11) This endpoint is an intent PARSER, not a solver. It maps natural-language
        # scenarios to the parameter knobs they *would* touch; it does NOT apply them or re-solve.
        # Label that explicitly so the UI can't present advisory prose as a computed result.
        parsed_ok = not (len(changes) == 1 and changes[0].get('param') == 'unknown')
        interpretation = (
            f"Scenario: \"{query}\". Parsed {len(changes)} parameter change(s) — advisory only."
            if parsed_ok else
            f"Scenario: \"{query}\". Could not map to known parameters."
        )
        impact = ("Advisory only — no parameters were changed and no solve was run. "
                  "Apply these changes in the relevant tab and re-run the solver to see exact cost impact.")

        return jsonify({
            'advisory_only': True,
            'applied': False,
            'parsed': parsed_ok,
            'interpretation': interpretation,
            'changes': changes,
            'impact': impact,
            'query': query,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── AI Insights Proxy (keeps API key server-side, avoids CORS) ───
@app.route('/api/ai/insights', methods=['POST'])
def api_ai_insights():
    try:
        import anthropic
        data = request.json or {}
        prompt = data.get('prompt', '')
        system = data.get('system', 'Return only a raw JSON array. No preamble. No code fences.')
        model = data.get('model', 'claude-sonnet-4-20250514')
        max_tokens = int(data.get('max_tokens', 1000))

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return jsonify({'text': msg.content[0].text})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─── Working Calendar ───
from solvers.plant_calendar import build_calendar

@app.route('/api/calc/calendar', methods=['POST'])
def api_calendar():
    try:
        data = request.json or {}
        # (MF-16) Pass through custom_holidays + year so the function's custom-holiday support and
        # non-2026 calendars are actually reachable from the API (both were previously dead).
        result = build_calendar(
            work_days_per_week=data.get('work_days_per_week', 6),
            use_indian_holidays=data.get('indian_holidays', True),
            custom_holidays=data.get('custom_holidays'),
            start_month=data.get('start_month', 0),
            year=int(data.get('year', 2026) or 2026),
        )
        # Don't send the full daily array by default (too large)
        if not data.get('include_daily', False):
            result.pop('daily', None)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Must stay LAST: app.run() blocks, so any @app.route defined below it never
# registers when launched via `python app.py`. (Was previously below this guard,
# which silently disabled /api/calc/calendar.)
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
