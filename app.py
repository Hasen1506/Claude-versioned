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
            products = []
            for p in base.get('products', []):
                demand = list(p.get('demand', []))
                d_shifted = demand[w * shift:] + demand[:w * shift]
                products.append({**p, 'demand': d_shifted})
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


# ─── Hierarchical Disaggregation ───
@app.route('/api/calc/disaggregate', methods=['POST'])
def api_disaggregate():
    try:
        return jsonify(disaggregate(request.json))
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

        interpretation = f"Scenario: \"{query}\". Identified {len(changes)} parameter change(s)."
        impact = "Re-run the MILP solver with modified parameters to see exact cost impact."

        return jsonify({
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

# ─── Working Calendar ───
from solvers.calendar import build_calendar

@app.route('/api/calc/calendar', methods=['POST'])
def api_calendar():
    try:
        data = request.json or {}
        result = build_calendar(
            work_days_per_week=data.get('work_days_per_week', 6),
            use_indian_holidays=data.get('indian_holidays', True),
            start_month=data.get('start_month', 0),
        )
        # Don't send 365 daily entries by default (too large)
        if not data.get('include_daily', False):
            result.pop('daily', None)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
