"""V2-8 (PRODUCT_BLUEPRINT_V3) — scheduled-receipts netting contract (procurement.py T6).

The MRP must NOT re-order material that is already on the water: params.locked_pos
({part, qty, releaseDate|period}) books each open PO as an exogenous RM arrival at
release + lead, and the solver buys only the residual gap. The UI feeds this via
scheduledReceiptsLocked() (store.jsx) from network.scheduledReceipts.

GOLDEN logic (hand-reasoned, deterministic): one product, demand 20×8 = 160 units,
one part qty_per 1 ⇒ RM requirement 160. A locked PO of 60 arriving in-horizon must
cut the planned buy by exactly those 60 (the requirement is hard, so the residual
is 100) and cut RM spend accordingly.
"""
from procurement import solve_procurement
from conftest import make_product


def _payload(locked=None, horizon_start=None):
    params = {
        'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
        'carry_rate_annual': 0.24, 'salvage_rate': 0.8, 'ss_floor_mode': 'off',
        'allow_backorder': True,
    }
    if locked is not None:
        params['locked_pos'] = locked
    if horizon_start is not None:
        params['horizon_start_date'] = horizon_start
    return {'params': params, 'products': [make_product()]}


def _milk(r):
    m = [p for p in r['materials'] if p['name'] == 'milk']
    assert m, 'milk row missing from materials'
    return m[0]


def _base():
    r = solve_procurement(_payload())
    assert r.get('status') == 'Optimal'
    return _milk(r)['total_ordered']


def test_locked_po_nets_the_buy_period_path():
    # legacy integer `period` shape: release p0 + lead 1 ⇒ arrives p1 (in-horizon)
    base = _base()
    r = solve_procurement(_payload(locked=[{'part': 'milk', 'qty': 60, 'period': 0}]))
    assert r.get('status') == 'Optimal'
    netted = _milk(r)['total_ordered']
    assert netted == base - 60, f'buy must net down by the locked 60 (base {base}, got {netted})'


def test_locked_po_nets_the_buy_release_date_path():
    # releaseDate path (what scheduledReceiptsLocked() sends): weekly grain,
    # release = horizon start ⇒ rel_p 0, + lead 1 ⇒ arrives p1
    base = _base()
    r = solve_procurement(_payload(
        locked=[{'part': 'milk', 'qty': 60, 'releaseDate': '2026-06-01'}],
        horizon_start='2026-06-01'))
    assert r.get('status') == 'Optimal'
    assert _milk(r)['total_ordered'] == base - 60


def test_locked_po_unknown_part_and_out_of_horizon_are_ignored():
    base = _base()
    r = solve_procurement(_payload(locked=[
        {'part': 'no-such-part', 'qty': 999, 'period': 0},   # name miss ⇒ skipped
        {'part': 'milk', 'qty': 999, 'period': 50},          # arrives ≥ T ⇒ dropped
    ]))
    assert r.get('status') == 'Optimal'
    assert _milk(r)['total_ordered'] == base, 'ignored locks must not move the plan'
