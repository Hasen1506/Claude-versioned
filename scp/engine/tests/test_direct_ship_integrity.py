"""Direct-ship references must keep their posted purchasing and sales meaning."""
import pytest

from scp import dropship as tp
from scp.accounting import view
from scp.model import Dataset
from scp.purchasing.payables import enter_invoice

from .test_companies import h
from .test_enterprise_integrity import client, team
from .test_jobwork_integrity import company, SENT, BACK, BILLED, saved


def direct_company():
    raw = company().model_dump(mode='json')
    raw['locations'].append({'id': 'K', 'type': 'customer'})
    return Dataset.model_validate(raw)


def dispatched():
    x, _ = tp.create(direct_company(), 'K', 'A', 2, BILLED, 'S', price=20, cost=10, on=SENT)
    x, _ = tp.send(x, 'TP-00001', on=SENT)
    return tp.dispatch(x, 'TP-00001', on=BACK)[0]


@pytest.mark.parametrize('attack', ['delete', 'cost', 'quantity', 'dispatch'])
def test_direct_ship_purchasing_facts_cannot_reclassify_or_restate_a_posted_charge(attack):
    x, _ = enter_invoice(dispatched(), None, [{'order': 'TP-00001'}], on=BILLED)
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    if attack == 'delete':
        raw['third_party_orders'] = []
    elif attack == 'cost':
        raw['third_party_orders'][0]['cost'] = 99
    elif attack == 'quantity':
        raw['third_party_orders'][0]['qty'] = 99
    else:
        raw['third_party_orders'][0]['shipments'] = []
    response = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, 'dataset': raw})
    assert response.status_code == 403, response.text
    current = client.get(f'/api/companies/{cid}', headers=h(owner)).json()
    assert current['meta']['revision'] == 1
    balances = {r.account: r.balance for r in view(Dataset.model_validate(current['dataset']), period_end=BILLED).balances}
    assert balances['PAYABLES'] == -20 and balances.get('SUSPENSE', 0) == 0


def test_direct_ship_can_be_saved_at_each_real_business_step():
    x = direct_company()
    owner, _, cid = team(x)
    x, _ = tp.create(x, 'K', 'A', 2, BILLED, 'S', price=20, cost=10, on=SENT)
    x = saved(owner, cid, x, 1)
    x, _ = tp.send(x, 'TP-00001', on=SENT)
    x = saved(owner, cid, x, 2)
    x, _ = tp.dispatch(x, 'TP-00001', qty=1, on=BACK)
    x = saved(owner, cid, x, 3)
    x, _ = tp.dispatch(x, 'TP-00001', qty=1, on=BILLED)
    x = saved(owner, cid, x, 4)
    assert x.third_party_orders[0].shipped == 2


def test_raw_dispatch_cannot_precede_the_supplier_order():
    x, _ = tp.create(direct_company(), 'K', 'A', 2, BILLED, 'S', price=20, cost=10, on=SENT)
    x, _ = tp.send(x, 'TP-00001', on=SENT)
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    raw['third_party_orders'][0]['shipments'] = [{'date': '2026-01-04', 'qty': 2}]
    response = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, 'dataset': raw})
    assert response.status_code == 403, response.text


def test_sending_a_direct_ship_order_keeps_its_company_currency_basis():
    x, _ = tp.create(direct_company(), 'K', 'A', 2, BILLED, 'S', price=20, cost=10, on=SENT)
    x, _ = tp.send(x, 'TP-00001', on=SENT)
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    raw['settings']['currency'] = 'USD'
    response = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, 'dataset': raw})
    assert response.status_code == 403 and 'company currency' in response.text, response.text


@pytest.mark.parametrize('purchasing_grant', [False, True])
def test_a_direct_ship_supplier_commitment_requires_purchasing_authority(purchasing_grant):
    x, _ = tp.create(direct_company(), 'K', 'A', 2, BILLED, 'S', price=20, cost=10, on=SENT)
    roles = {'sales': ['owner@integrity.example']}
    if purchasing_grant:
        roles['purchasing'] = ['owner@integrity.example']
    x = x.model_copy(update={'finance': x.finance.model_copy(update={'control_roles': roles})})
    owner, _, cid = team(x)
    x, _ = tp.send(x, 'TP-00001', on=SENT)
    response = client.put(f'/api/companies/{cid}', headers=h(owner), json={
        'base_revision': 1, 'dataset': x.model_dump(mode='json')})
    assert response.status_code == (200 if purchasing_grant else 403), response.text
