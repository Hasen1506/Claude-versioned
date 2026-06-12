"""
V4-3 — OT purchase mode: per_hour (legacy, continuous) vs per_shift (indivisible
8-hr blocks — you call a crew in for a whole shift, not 37 minutes).

Contract (production.py):
  · default ot_mode='per_hour' — pay exactly the OT hours used (byte-identical
    legacy; overtime_shifts is None);
  · ot_mode='per_shift' — integer blocks gate usable OT (ot ≤ shift_len·blocks)
    and the WHOLE block is charged: a 3-hr overflow costs one full 8-hr shift,
    so the per-shift schedule is never cheaper on OT than the per-hour one;
  · the lumpiness is surfaced (overtime_shifts, overtime_hours_paid), never hidden.
"""
from production import solve_production


def _payload(**params):
    base = {
        'periods': 1,
        'hrs_per_period': 40,          # one 40-hr week of regular time
        'hours_per_shift': 8,
        'makespan_weight': 0,
    }
    base.update(params)
    return {
        'products': [{'name': 'Y', 'required_qty': 43, 'setup_cost': 0, 'oee': 1.0,
                      'yield_pct': 1.0,
                      'routing': [{'line_id': 'L1', 'cycleTimeMin': 60,
                                   'parallelism': 1, 'yieldPct': 100}]}],
        'lines': [{'id': 'L1', 'name': 'L1', 'capacity': 1000, 'oee': 1.0,
                   'workers_per_shift': 1, 'shifts_per_day': 1, 'hourly_rate': 100,
                   'max_ot_hrs_per_worker_per_week': 16}],
        'params': base,
    }


def test_per_hour_default_pays_hours_used():
    r = solve_production(_payload())
    assert r.get('status') == 'Optimal'
    assert r['ot_mode'] == 'per_hour'
    line = r['lines'][0]
    assert line['overtime_shifts'] is None and line['overtime_hours_paid'] is None
    # 43 units at 1 hr/u vs 40 regular hrs → ~3 OT hrs at 1×100×1.5 = ₹150/hr
    assert 2.5 <= line['overtime_hours'] <= 3.5
    assert abs(line['overtime_cost'] - line['overtime_hours'] * 150) < 1.0


def test_per_shift_charges_whole_blocks():
    r = solve_production(_payload(ot_mode='per_shift'))
    assert r.get('status') == 'Optimal'
    assert r['ot_mode'] == 'per_shift'
    line = r['lines'][0]
    # the 3-hr overflow forces ONE whole 8-hr block, paid in full
    assert line['overtime_shifts'] == 1
    assert line['overtime_hours_paid'] == 8.0
    assert abs(line['overtime_cost'] - 8 * 150) < 1.0
    # hours USED stay ~3 — the paid-but-unused gap is visible, not hidden
    assert 2.5 <= line['overtime_hours'] <= 3.5


def test_per_shift_never_cheaper_on_ot():
    a = solve_production(_payload())
    b = solve_production(_payload(ot_mode='per_shift'))
    assert b['lines'][0]['overtime_cost'] >= a['lines'][0]['overtime_cost'] - 1e-6
