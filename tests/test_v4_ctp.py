"""
V4-5 — capable-to-promise (CTP) quote against the REAL production MILP.

Contract (production.solve_ctp):
  · ATP first — when the baseline schedule already over-builds past committed
    demand by the due week, the promise is FREE (covered_by_atp, ₹0, no resolve);
  · else test-fit: add the qty to required_qty + demand_by_period[w] and re-solve
    at due, due+1, … — first Optimal week = EARLIEST promise; cost/OT/schedule
    diff vs baseline = what the promise displaces;
  · a quote that can never fit inside the search window → NoPromise (honest no);
  · advisory: the input payload is never mutated.

Fixture: one line, 40 reg hrs + 16 OT hrs/wk, 1 hr/unit → 40 reg / 56 max units
per week, 2 periods. Committed demand 38/wk leaves ~2u/wk of slack capacity.
"""
import copy
from production import solve_ctp


def _payload(dem=(38, 38), quote=None):
    T = len(dem)
    p = {
        'products': [{'name': 'Y', 'required_qty': float(sum(dem)), 'setup_cost': 0,
                      'oee': 1.0, 'yield_pct': 1.0,
                      'demand_by_period': [float(d) for d in dem],
                      'routing': [{'line_id': 'L1', 'cycleTimeMin': 60,
                                   'parallelism': 1, 'yieldPct': 100}]}],
        'lines': [{'id': 'L1', 'name': 'L1', 'capacity': 1000, 'oee': 1.0,
                   'workers_per_shift': 1, 'shifts_per_day': 1, 'hourly_rate': 100,
                   'max_ot_hrs_per_worker_per_week': 16}],
        'params': {'periods': T, 'hrs_per_period': 40, 'hours_per_shift': 8,
                   'makespan_weight': 0, 'time_phased': True,
                   'holding_cost_per_unit': 1},
    }
    if quote:
        p['quote'] = quote
    return p


def test_ctp_buys_overtime_to_promise():
    # 10 extra units in week 0 on a 38/40 loaded line → ~8 OT hrs bought, priced.
    r = solve_ctp(_payload(quote={'product': 'Y', 'qty': 10, 'due_period': 0}))
    assert r['status'] == 'Optimal' and r['promised'] is True
    assert r['earliest_period'] == 0 and r['covered_by_atp'] is False
    assert r['ot_hours_added'] >= 7.5
    # cost-to-promise ≈ OT bill (₹150/hr × ~8h); never free
    assert r['cost_to_promise'] >= 1000


def test_ctp_slips_to_the_earliest_feasible_week():
    # 30 extra in week 0 exceeds even max OT (38+30=68 > 56) → earliest = week 1
    # (cumulative coverage lets week-0 demand backfill from... no backorder — so the
    # quote itself must slip to week 1 where cumulative capacity 112 ≥ 106).
    r = solve_ctp(_payload(quote={'product': 'Y', 'qty': 30, 'due_period': 0}))
    assert r['status'] == 'Optimal' and r['promised'] is False
    assert r['earliest_period'] == 1
    assert r['tried'][0]['status'] != 'Optimal' and r['tried'][-1]['status'] == 'Optimal'


def test_ctp_honest_no_when_it_never_fits():
    # 50 extra never fits in a 2-week window (max 112 < 126) → NoPromise, not a fudge.
    r = solve_ctp(_payload(quote={'product': 'Y', 'qty': 50, 'due_period': 0}))
    assert r['status'] == 'NoPromise' and r['earliest_period'] is None
    assert all(t['status'] != 'Optimal' for t in r['tried'])


def test_atp_covers_without_resolving():
    # demand 20/wk → baseline builds to demand... force slack: required_qty already
    # produces 60 total vs 40 committed — cumulative ATP at week 0 covers a 5u ask.
    pl = _payload(dem=(20, 20))
    pl['products'][0]['required_qty'] = 60.0          # 20u of uncommitted build
    pl['quote'] = {'product': 'Y', 'qty': 5, 'due_period': 1}
    r = solve_ctp(pl)
    assert r['status'] == 'Optimal' and r['covered_by_atp'] is True
    assert r['cost_to_promise'] == 0.0 and r['displaced'] == []


def test_atp_is_look_ahead_not_naive_cumulative():
    # demand (0, 56): holding ₹1/u beats OT ₹150/h, so the schedule PRE-BUILDS ~16u
    # in week 0. Naive cumulative ATP would see 16u "available" at week 0 and promise
    # them free — but week 1 consumes every unit. Look-ahead ATP reserves them: the
    # ask must be CAPACITY-fit, never skimmed off the prebuild. 30u on top of the
    # 16u prebuild overflows the 40 regular hrs → ~6 OT hrs, a PAID promise.
    r = solve_ctp(_payload(dem=(0, 56), quote={'product': 'Y', 'qty': 30, 'due_period': 0}))
    assert r['status'] == 'Optimal'
    assert r['covered_by_atp'] is False        # the prebuild was spoken for
    assert r['atp_at_due'] <= 0.5
    assert r['ot_hours_added'] >= 5            # the system-wide overflow buys OT
    assert r['cost_to_promise'] >= 700         # ≈ 6h × ₹150 — paid, not skimmed


def test_payload_never_mutated():
    pl = _payload(quote={'product': 'Y', 'qty': 10, 'due_period': 0})
    snap = copy.deepcopy(pl)
    solve_ctp(pl)
    assert pl == snap
