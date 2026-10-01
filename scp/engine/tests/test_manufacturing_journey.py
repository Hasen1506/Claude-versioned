"""Independent material/capacity/money reconciliation through partial production and reversal."""
from datetime import date

import pytest

from scp.actuals import firm_orders, post, receive, roll_forward
from scp.actuals.post import deliver
from scp.finance import run_finance
from scp.model import MovementType
from scp.plan import run_mrp

from .factory import base, demand, ds


@pytest.mark.parametrize('first', [1, 8, 19.5])
def test_manufacturing_chain_reconciles_after_partial_roll_completion_and_reversal(first):
    raw = base(horizon=28)
    raw['settings'].update(wacc=0, holding_spread=0)
    for row in raw['location_products']:
        row.update(on_hand=0, lot_sizing={'policy': 'L4L'})
    raw['products'][0].update(price=100, whole_units=False)
    raw['demand'] = [demand('P', 'A', '2026-01-12', 20, kind='sales_order', id='SO-JOURNEY')]
    data = ds(raw)
    plan = run_mrp(data)
    assert plan.ok
    assert {(o.kind, o.product): o.qty for o in plan.orders} == {('make', 'A'): 20, ('buy', 'B'): 40, ('buy', 'C'): 20}
    assert sum(b.load_hours for r in plan.resources for b in r.buckets) == 12
    assert plan.kpis.purchase_cost == 500
    assert plan.kpis.production_cost + plan.kpis.setup_cost == 1200
    finance = run_finance(data, plan)
    assert finance.reconciliation.reconciled
    assert finance.serve[0].revenue == 2000
    assert finance.serve[0].total_cost == 1700
    assert finance.serve[0].margin == 300
    data, firm = firm_orders(data, plan, within_days=20)
    assert firm.ok and len(firm.firmed) == 3
    assert not run_mrp(data).orders
    for order in list(data.receipts):
        if order.kind.value == 'purchase':
            data, _ = receive(data, order.id, on=order.due_date)
    order = next(r for r in data.receipts if r.kind.value == 'production')
    data, _ = receive(data, order.id, qty=first, on=date(2026, 1, 11))
    data, _ = roll_forward(data, date(2026, 1, 12))
    assert {r.product: r.on_hand for r in data.location_products} == {'A': first, 'B': 40-2*first, 'C': 20-first}
    assert data.receipts[0].qty == 20-first
    data, _ = receive(data, order.id, qty=20-first, on=date(2026, 1, 12))
    data, shipment = deliver(data, 'SO-JOURNEY', qty=20, on=date(2026, 1, 12))
    data, _ = roll_forward(data, date(2026, 1, 13))
    assert {r.product: r.on_hand for r in data.location_products} == {'A': 0, 'B': 0, 'C': 0}
    assert not data.receipts and not data.demand
    assert {(c.kind, c.delivered_qty) for c in data.closed_orders} == {('purchase', 40), ('purchase', 20), ('production', 20), ('sales', 20)}
    # Taking back the shipment restores finished stock and sales demand, not consumed components.
    data, _ = post(data, 'reverse', movement=shipment.movements[0], on=date(2026, 1, 13))
    data, _ = roll_forward(data, date(2026, 1, 14))
    assert {r.product: r.on_hand for r in data.location_products} == {'A': 20, 'B': 0, 'C': 0}
    assert len(data.demand) == 1 and data.demand[0].qty == 20
    assert sum(m.net for m in data.movements if m.type is MovementType.ISSUE and m.product == 'B') == 40
    assert sum(m.net for m in data.movements if m.type is MovementType.ISSUE and m.product == 'C') == 20
    again, _ = roll_forward(data, date(2026, 1, 14))
    assert again.model_dump() == data.model_dump()
