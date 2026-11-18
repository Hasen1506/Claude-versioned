"""Retained outsourced-production facts and independent stock/WIP/AP reconciliation."""
from datetime import date

import pytest

from scp import jobwork as jw
from scp.accounting import view
from scp.actuals.stock import before, stock
from scp.model import Dataset
from scp.purchasing.payables import enter_invoice, pay_invoice
from scp.companies.patch import make_patch

from .factory import base
from .test_companies import h
from .test_enterprise_integrity import client, team

SENT = date(2026, 1, 5)
BACK = date(2026, 1, 6)
BILLED = date(2026, 1, 7)


def company():
    raw = base()
    raw['products'] = [{'id': 'A', 'type': 'FG', 'standard_cost': 10},
                       {'id': 'B', 'type': 'RM', 'standard_cost': 4}]
    raw['location_products'] = [{'location': 'P', 'product': 'A', 'on_hand': 0},
                                {'location': 'P', 'product': 'B', 'on_hand': 100}]
    raw['production_sources'] = [{'id': 'MAKE-A', 'location': 'P', 'product': 'A', 'output_qty': 1,
        'components': [{'product': 'B', 'qty': 2}],
        'operations': [{'seq': 10, 'subcontract': {'supplier': 'S', 'workdays': 1, 'cost_per_unit': 2}}]}]
    raw['receipts'] = [{'id': 'MO-1', 'kind': 'production', 'location': 'P', 'product': 'A', 'qty': 10,
                       'start_date': SENT.isoformat(), 'due_date': BACK.isoformat(), 'source': 'MAKE-A'}]
    return Dataset.model_validate(raw)


def billed():
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    x, _ = jw.receive(x, 'JW-00001', 10, on=BACK)
    return enter_invoice(x, None, [{'order': 'JW-00001'}], on=BILLED)[0]


def saved(token, cid, ds, revision):
    response = client.put(f'/api/companies/{cid}', headers=h(token), json={
        'base_revision': revision, 'dataset': ds.model_dump(mode='json')})
    assert response.status_code == 200, response.text
    return Dataset.model_validate(client.get(f'/api/companies/{cid}', headers=h(token)).json()['dataset'])


@pytest.mark.parametrize('route', ['whole', 'patch', 'merge'])
@pytest.mark.parametrize('attack', ['delete', 'charge', 'sent_quantity', 'used_quantity'])
def test_posted_jobwork_facts_cannot_be_replaced_by_another_persistence_route(route, attack):
    x = billed()
    owner, _, cid = team(x)
    baseline = x.model_dump(mode='json')
    raw = x.model_dump(mode='json')
    if attack == 'delete':
        raw['challans'] = []
    elif attack == 'charge':
        raw['challans'][0]['charge'] = 999
    elif attack == 'sent_quantity':
        raw['challans'][0]['lines'][0]['qty'] += 10
    else:
        raw['challans'][0]['returns'][0]['used'] = {}
    if route == 'merge':
        response = client.post(f'/api/companies/{cid}/merge', headers=h(owner), json={
            'base_revision': 1, 'base': baseline, 'dataset': raw})
    else:
        delta = {'dataset': raw} if route == 'whole' else {'patch': make_patch(baseline, raw)}
        response = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, **delta})
    assert response.status_code == 403, response.text
    current = client.get(f'/api/companies/{cid}', headers=h(owner)).json()
    assert current['meta']['revision'] == 1
    books = view(Dataset.model_validate(current['dataset']), period_end=BILLED)
    balances = {r.account: r.balance for r in books.balances}
    assert balances.get('WIP', 0) == 0 and balances.get('SUSPENSE', 0) == 0
    assert balances['PAYABLES'] == -20 and balances['STOCK'] == 420


def test_partial_jobwork_return_unused_invoice_and_payment_reconcile_literal_amounts():
    x = company()
    owner, _, cid = team(x)
    x, _ = jw.send(x, 'MO-1', on=SENT)
    x = saved(owner, cid, x, 1)
    x, _ = jw.receive(x, 'JW-00001', 9, on=BACK)
    x = saved(owner, cid, x, 2)
    x, _ = jw.return_unused(x, 'JW-00001', 'B', 2, on=BILLED)
    x = saved(owner, cid, x, 3)
    x, _ = enter_invoice(x, None, [{'order': 'JW-00001'}], on=BILLED)
    x = saved(owner, cid, x, 4)
    x, _ = pay_invoice(x, 'SI-00001', on=date(2026, 1, 8))
    x = saved(owner, cid, x, 5)
    assert x.challans[0].closed_on == BILLED
    assert stock(before(x, date(2026, 1, 9)))[('P', 'B')] == 82
    books = view(x, period_end=date(2026, 1, 9))
    balances = {r.account: r.balance for r in books.balances}
    assert {k: balances.get(k, 0) for k in ('STOCK', 'WIP', 'PAYABLES', 'BANK', 'SUSPENSE')} == {
        'STOCK': 418, 'WIP': 0, 'PAYABLES': 0, 'BANK': -18, 'SUSPENSE': 0}
    assert all(c.ok for c in books.checks)


@pytest.mark.parametrize('attack', ['unused_without_stock', 'cancel_without_reversal', 'custody_overdraw'])
def test_jobwork_custody_cannot_be_changed_without_its_material_effect(attack):
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    if attack == 'cancel_without_reversal':
        raw['challans'][0].update(cancelled=True, closed_on=BACK.isoformat())
    else:
        raw['challans'][0]['returns'].append({'kind': 'unused' if attack == 'unused_without_stock' else 'lost',
                                            'date': BACK.isoformat(), 'product': 'B',
                                            'qty': 2 if attack == 'unused_without_stock' else 21})
    r = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, 'dataset': raw})
    assert r.status_code == 403, r.text


def test_cancelling_a_challan_returns_all_parts_and_preserves_its_record():
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    owner, _, cid = team(x)
    x, _ = jw.cancel(x, 'JW-00001', on=BACK)
    x = saved(owner, cid, x, 1)
    assert x.challans[0].cancelled and stock(before(x, BILLED))[('P', 'B')] == 100
    assert all(c.ok for c in view(x, period_end=BILLED).checks)


def test_a_challan_issue_cannot_be_reversed_behind_its_custody_record():
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    issue = next(m for m in raw['movements'] if m['type'] == 'issue')
    raw['movements'].append({**issue, 'id': 'BACK-WITHOUT-CHALLAN', 'date': BACK.isoformat(), 'reversal_of': issue['id']})
    r = client.put(f'/api/companies/{cid}', headers=h(owner), json={'base_revision': 1, 'dataset': raw})
    assert r.status_code == 403, r.text


@pytest.mark.parametrize('action', ['processed', 'unused', 'lost', 'cancel'])
def test_jobwork_custody_cannot_precede_its_dispatch(action):
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    earlier = date(2026, 1, 4)
    with pytest.raises(jw.JobWorkError, match='dated on or after'):
        if action == 'processed':
            jw.receive(x, 'JW-00001', 1, on=earlier)
        elif action == 'unused':
            jw.return_unused(x, 'JW-00001', 'B', 1, on=earlier)
        elif action == 'lost':
            jw.write_off(x, 'JW-00001', 'B', 1, on=earlier)
        else:
            jw.cancel(x, 'JW-00001', on=earlier)


def test_future_returns_and_cancellation_do_not_restate_earlier_custody_or_period_dispatches():
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    original_stock = jw.view(x, SENT).stock
    returned, _ = jw.receive(x, 'JW-00001', 10, on=BACK)
    assert jw.view(returned, SENT).stock == original_stock
    assert jw.view(returned, SENT).challans[0].processed == 0
    assert jw.view(returned, BACK).stock == []
    period = (date(2026, 1, 1), date(2026, 1, 31))
    original_return = jw.itc04(x, *period)
    cancelled, _ = jw.cancel(x, 'JW-00001', on=date(2026, 2, 1))
    assert jw.view(cancelled, SENT).stock == original_stock
    assert jw.itc04(cancelled, *period) == original_return
    assert jw.view(cancelled, date(2026, 2, 1)).stock == []


@pytest.mark.parametrize('granted', [False, True])
def test_jobworker_loss_requires_the_separate_adjustment_grant(granted):
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    roles = {'manufacturing': ['owner@integrity.example']}
    if granted:
        roles['inventory_adjustment'] = ['owner@integrity.example']
    x = x.model_copy(update={'finance': x.finance.model_copy(update={'control_roles': roles})})
    owner, _, cid = team(x)
    x, _ = jw.write_off(x, 'JW-00001', 'B', 1, on=BACK)
    r = client.put(f'/api/companies/{cid}', headers=h(owner), json={
        'base_revision': 1, 'dataset': x.model_dump(mode='json')})
    assert r.status_code == (200 if granted else 403), r.text
    if not granted:
        assert 'inventory_adjustment' in r.text


def test_authoritative_jobwork_commands_and_replays_preserve_later_receipts_and_billing():
    from .test_company_commands import command
    owner, _, cid = team(company())
    sent = command(owner, cid, 'dispatch-to-worker', 'outside', 'send_parts', date=SENT.isoformat(),
                   production_order='MO-1')
    assert sent.status_code == 200, sent.text
    back = command(owner, cid, 'worker-completion', 'outside', 'back_processed', revision=2,
                   date=BACK.isoformat(), id='JW-00001', qty=10)
    assert back.status_code == 200, back.text
    bill = command(owner, cid, 'worker-charge', 'purchasing', 'enter_invoice', revision=3,
                   date=BILLED.isoformat(), lines=[{'order': 'JW-00001'}])
    assert bill.status_code == 200, bill.text
    replay = command(owner, cid, 'dispatch-to-worker', 'outside', 'send_parts', date=SENT.isoformat(),
                     production_order='MO-1')
    assert replay.status_code == 200 and replay.json()['duplicate'], replay.text
    current = Dataset.model_validate(replay.json()['company']['dataset'])
    assert len(current.challans) == 1 and current.challans[0].processed == 10
    assert len(current.supplier_invoices) == 1
    balances = {r.account: r.balance for r in view(current, period_end=BILLED).balances}
    assert balances.get('WIP', 0) == 0 and balances['PAYABLES'] == -20


@pytest.mark.parametrize('malformed', [None, {'kind': 'lost'}, [None]])
def test_malformed_custody_records_are_refused_without_an_internal_error(malformed):
    x, _ = jw.send(company(), 'MO-1', on=SENT)
    owner, _, cid = team(x)
    raw = x.model_dump(mode='json')
    raw['challans'][0]['returns'] = malformed
    response = client.put(f'/api/companies/{cid}', headers=h(owner), json={
        'base_revision': 1, 'dataset': raw})
    assert response.status_code in (403, 422), response.text
    assert client.get(f'/api/companies/{cid}', headers=h(owner)).json()['meta']['revision'] == 1
