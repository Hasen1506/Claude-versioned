"""Adversarial reversal quantities and independently expected contra accounts."""
from datetime import date

import pytest

from scp.accounting import view
from scp.actuals.documents import reverse, scrap
from scp.actuals.stock import before, stock
from scp.companies.patch import make_patch
from scp.model import Dataset

from .test_companies import h
from .test_enterprise_integrity import client, team
from .test_jobwork_integrity import company


@pytest.mark.parametrize('route', ['whole', 'patch', 'merge'])
@pytest.mark.parametrize('attack', ['over_quantity', 'duplicate', 'wrong_product', 'wrong_type', 'before_original', 'missing_original'])
def test_a_saved_reversal_cannot_invent_stock_or_change_its_posting_identity(route, attack):
    x, rep = scrap(company(), 'P', 'B', 5, on=date(2026, 1, 6))
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    baseline = x.model_dump(mode='json')
    original = next(m for m in raw['movements'] if m['id'] == rep.movements[0])
    reversed_row = {**original, 'id': 'FAKE-REVERSAL', 'date': '2026-01-07', 'reversal_of': original['id'], 'final': False}
    if attack == 'over_quantity':
        reversed_row['qty'] = 500
    elif attack == 'duplicate':
        raw['movements'].append({**reversed_row, 'id': 'FIRST-REVERSAL'})
    elif attack == 'wrong_product':
        reversed_row['product'] = 'A'
    elif attack == 'wrong_type':
        reversed_row['type'] = 'adjustment'
    elif attack == 'before_original':
        reversed_row['date'] = '2026-01-05'
    else:
        reversed_row['reversal_of'] = 'NO-SUCH-POSTING'
    raw['movements'].append(reversed_row)
    if route == 'merge':
        response = client.post(f'/api/companies/{cid}/merge', headers=h(owner), json={
            'base_revision': 1, 'base': baseline, 'dataset': raw})
    else:
        delta = {'dataset': raw} if route == 'whole' else {'patch': make_patch(baseline, raw)}
        response = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, **delta})
    assert response.status_code == 403, response.text
    current = client.get(f'/api/companies/{cid}', headers=h(owner)).json()
    assert current['meta']['revision'] == 1
    assert stock(before(Dataset.model_validate(current['dataset']), date(2026, 1, 8)))[('P', 'B')] == 95


def test_a_scrap_reversal_clears_the_original_expense_without_a_price_difference():
    x, rep = scrap(company(), 'P', 'B', 5, on=date(2026, 1, 6))
    prior = view(x, period_end=date(2026, 1, 6)).model_dump()
    x, _ = reverse(x, rep.movements[0], on=date(2026, 1, 7))
    assert view(x, period_end=date(2026, 1, 6)).model_dump() == prior
    balances = {r.account: r.balance for r in view(x, period_end=date(2026, 1, 7)).balances}
    assert {k: balances.get(k, 0) for k in ('STOCK', 'SCRAP', 'PRICE_DIFF', 'SUSPENSE')} == {
        'STOCK': 400, 'SCRAP': 0, 'PRICE_DIFF': 0, 'SUSPENSE': 0}


def test_cumulative_partial_reversals_can_return_exactly_the_original_quantity():
    x, rep = scrap(company(), 'P', 'B', 5, on=date(2026, 1, 6))
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    original = next(m for m in raw['movements'] if m['id'] == rep.movements[0])
    raw['movements'] += [{**original, 'id': f'REVERSAL-{q}', 'qty': q, 'date': '2026-01-07',
                          'reversal_of': original['id'], 'final': False} for q in (2, 3)]
    response = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, 'dataset': raw})
    assert response.status_code == 200, response.text
    current = Dataset.model_validate(client.get(f'/api/companies/{cid}', headers=h(owner)).json()['dataset'])
    assert stock(before(current, date(2026, 1, 8)))[('P', 'B')] == 100
