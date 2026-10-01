"""The production form's defaults match effective BOMs and net posted usage without changing data."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals import firm_orders, post, receive, roll_forward
from scp.actuals.post import production_usage
from scp.api.app import app
from scp.plan import run_mrp

from .factory import base, demand, ds, lp


def fixed_order():
    raw = base()
    raw['production_sources'][0]['components'][1].update(qty=5, fixed_qty=True)
    for product in 'BC':
        lp(raw, 'P', product)['on_hand'] = 100
    lp(raw, 'P', 'A')['on_hand'] = 0
    raw['demand'] = [demand('P', 'A', '2026-01-12', 20)]
    data = ds(raw)
    data, _ = firm_orders(data, run_mrp(data), within_days=20)
    return data


def test_preview_keeps_fixed_parts_and_agrees_after_roll_and_reversal():
    data = fixed_order()
    assert production_usage(data, 'PRD-00001', 8) == [
        {'location': 'P', 'product': 'B', 'qty': 16}, {'location': 'P', 'product': 'C', 'qty': 5}]
    data, receipt = receive(data, 'PRD-00001', qty=8, on=date(2026, 1, 11))
    data, _ = roll_forward(data, date(2026, 1, 12))
    assert production_usage(data, 'PRD-00001', 12) == [
        {'location': 'P', 'product': 'B', 'qty': 24}, {'location': 'P', 'product': 'C', 'qty': 0}]
    data, _ = post(data, 'reverse', movement=receipt.movements[0], on=date(2026, 1, 12))
    assert production_usage(data, 'PRD-00001', 8) == [
        {'location': 'P', 'product': 'B', 'qty': 16}, {'location': 'P', 'product': 'C', 'qty': 5}]


def test_imported_order_preview_uses_scrap_and_effective_phantom_bom():
    raw = base()
    raw['products'].append({'id': 'SUB', 'type': 'SFG'})
    lp(raw, 'P', 'SUB')['phantom'] = True
    raw['production_sources'][0].update(components=[{'product': 'SUB', 'qty': 2}], assembly_scrap=0.2)
    raw['production_sources'].append({'id': 'SUB-PV', 'location': 'P', 'product': 'SUB', 'output_qty': 4,
                                      'components': [{'product': 'B', 'qty': 4}, {'product': 'C', 'qty': 3, 'fixed_qty': True}]})
    raw['receipts'] = [{'id': 'WO', 'kind': 'production', 'location': 'P', 'product': 'A', 'qty': 20,
                        'source': 'PV-A', 'due_date': '2026-01-12'}]
    data = ds(raw)
    # 8 good A / 80% yield * 2 SUB per A * 1 B per SUB, plus 3 C once for this run.
    assert production_usage(data, 'WO', 8) == [
        {'location': 'P', 'product': 'B', 'qty': 20}, {'location': 'P', 'product': 'C', 'qty': 3}]


def test_preview_api_is_read_only_and_rejects_a_nonproduction_order():
    client = TestClient(app)
    data = fixed_order().model_dump(mode='json')
    before = dict(data)
    response = client.post('/api/actuals/production-usage', json={'dataset': data, 'order': 'PRD-00001', 'qty': 8})
    assert response.status_code == 200 and response.json()[1]['qty'] == 5
    assert data == before and not data['movements']
    assert client.post('/api/actuals/production-usage', json={'dataset': data, 'order': 'NOPE', 'qty': 8}).status_code == 409


@pytest.mark.parametrize('qty', [0, -1, 0.0000001])
def test_preview_rejects_quantities_that_cannot_be_posted(qty):
    response = TestClient(app).post('/api/actuals/production-usage', json={
        'dataset': fixed_order().model_dump(mode='json'), 'order': 'PRD-00001', 'qty': qty})
    assert response.status_code in (409, 422)
