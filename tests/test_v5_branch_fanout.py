"""
V5-2 — server-side concurrent branching: /api/solve/branches fan-out.

Contracts pinned here (the client phase-batching is probe-observed):
  · a batched job returns the SAME result the dedicated endpoint's solver gives
    (the registry maps to the identical callables — no parallel re-implementation);
  · jobs genuinely run CONCURRENTLY (CBC is a subprocess, so wall < Σ solver-ms
    with a healthy margin) and the meta echoes honest wall/sum/speedup numbers;
  · per-job failure is ISOLATED — a bad payload or unknown solver yields ok:false
    + error on that entry while siblings still solve to Optimal;
  · the envelope is validated (empty / oversized job lists → 400, not a crash).
"""
import json
from app import app
from production import solve_production


def _client():
    app.config['TESTING'] = True
    return app.test_client()


def _prod_payload(periods=8, n_products=2):
    """A small-but-not-trivial production MILP (~100ms+ in CBC) so concurrency
    is measurable without making the suite slow."""
    products = []
    for k in range(n_products):
        dem = [30.0 + 5 * ((k + t) % 3) for t in range(periods)]
        products.append({
            'name': f'P{k}', 'required_qty': sum(dem), 'setup_cost': 50,
            'oee': 1.0, 'yield_pct': 1.0, 'demand_by_period': dem,
            'routing': [{'line_id': 'L1', 'cycleTimeMin': 12,
                         'parallelism': 1, 'yieldPct': 100}]})
    return {'products': products,
            'lines': [{'id': 'L1', 'name': 'L1', 'capacity': 5000, 'oee': 1.0,
                       'workers_per_shift': 2, 'shifts_per_day': 2, 'hourly_rate': 100,
                       'max_ot_hrs_per_worker_per_week': 16, 'changeover_mins': 20}],
            'params': {'periods': periods, 'hrs_per_period': 40, 'hours_per_shift': 8,
                       'makespan_weight': 0, 'time_phased': True,
                       'holding_cost_per_unit': 2, 'changeover_cost': 150}}


def _post(c, body):
    r = c.post('/api/solve/branches', data=json.dumps(body),
               content_type='application/json')
    return r.status_code, r.get_json()


def test_batched_job_matches_the_dedicated_solver():
    pl = _prod_payload()
    direct = solve_production(json.loads(json.dumps(pl)))   # deep copy — solvers may mutate
    code, out = _post(_client(), {'jobs': [{'id': 'a|production',
                                            'solver': 'production', 'payload': pl}]})
    assert code == 200
    e = out['results'][0]
    assert e['ok'] is True and e['id'] == 'a|production'
    assert e['result']['status'] == direct['status'] == 'Optimal'
    # same model ⇒ same objective (CBC is deterministic on identical input)
    assert abs(e['result']['total_cost'] - direct['total_cost']) < 1e-6


def test_jobs_run_concurrently_not_sequentially():
    jobs = [{'id': f's{i}|production', 'solver': 'production',
             'payload': _prod_payload()} for i in range(4)]
    code, out = _post(_client(), {'jobs': jobs, 'params': {'max_workers': 4}})
    assert code == 200
    assert all(e['ok'] for e in out['results'])
    m = out['meta']
    assert m['jobs'] == 4 and m['max_workers'] == 4
    # CBC solves are subprocesses → real parallelism. Demand only a modest margin
    # (1.4×) so the assertion is robust on a loaded CI box; observed locally ≳3×.
    assert m['solver_ms_sum'] > 0 and m['wall_ms'] > 0
    assert m['wall_ms'] < m['solver_ms_sum'] / 1.4, \
        f"no concurrency observed: wall {m['wall_ms']}ms vs sum {m['solver_ms_sum']}ms"
    assert m['speedup'] >= 1.4


def test_per_job_failure_is_isolated():
    jobs = [
        {'id': 'good|production', 'solver': 'production', 'payload': _prod_payload()},
        {'id': 'bad|production', 'solver': 'production',
         'payload': {'products': 'not-a-list'}},          # raises inside the solver
        {'id': 'odd|nope', 'solver': 'nope', 'payload': {}},  # unknown solver key
    ]
    code, out = _post(_client(), {'jobs': jobs})
    assert code == 200, 'a failing job must NOT fail the batch'
    by = {e['id']: e for e in out['results']}
    assert by['good|production']['ok'] is True
    assert by['good|production']['result']['status'] == 'Optimal'
    assert by['bad|production']['ok'] is False and by['bad|production']['error']
    assert by['odd|nope']['ok'] is False and 'unknown solver' in by['odd|nope']['error']


def test_envelope_validation():
    c = _client()
    code, out = _post(c, {'jobs': []})
    assert code == 400 and 'jobs' in out['error']
    code, out = _post(c, {})
    assert code == 400
    too_many = [{'id': str(i), 'solver': 'linecap', 'payload': {}} for i in range(49)]
    code, out = _post(c, {'jobs': too_many})
    assert code == 400 and 'max 48' in out['error']
