"""Run explicitly against an isolated development branch; retains fictional fixtures.

Never run against a production branch. SCP_POSTGRES_SMOKE=1 is required.
"""
import os
import secrets
import subprocess
import sys
from pathlib import Path

import psycopg

from scp.companies.store import Companies, CompanyError
from scp.connect import imports, messages, outbox
from scp.model import Dataset
from scp.tower.worklist import Tracker
from scp.versions.store import Store


def main():
    if os.environ.get('SCP_POSTGRES_SMOKE') != '1':
        raise RuntimeError('Requires explicit isolated development target')
    store = Store(os.environ['DATABASE_URL'])
    assert store.backend == 'postgresql'
    companies = Companies(store)
    Tracker(store)
    for module in (imports, messages, outbox):
        module._ensure(companies)
    suffix = secrets.token_hex(8)
    password = secrets.token_urlsafe(32)
    session = companies.signup(f'Smoke-{suffix}@example.invalid', 'Fictional storage test', password)
    assert companies.signin(f'smoke-{suffix}@example.invalid', password).user.id == session.user.id
    example = Path(__file__).resolve().parents[2] / 'examples' / 'kitchenware_network.json'
    doc = Dataset.model_validate_json(example.read_text()).model_dump(mode='json')
    doc['settings']['company_name'] = 'Fictional PostgreSQL test'
    company = companies.create(session.user, doc)
    assert companies.open(session.user, company.id).dataset == doc
    changed = dict(doc)
    changed['settings'] = dict(doc['settings'], company_name='Fictional revision test')
    saved = companies.save(session.user, company.id, changed, company.revision)
    assert saved.saved
    assert companies.open(session.user, company.id).dataset == changed
    other = companies.signup(f'other-{suffix}@example.invalid', 'Other fictional account', password)
    try:
        companies.open(other.user, company.id)
    except CompanyError:
        pass
    else:
        raise AssertionError('Account isolation failed')
    base = store.save_base(Dataset.model_validate(doc), 'Fictional base', scope=company.id)
    scenario = store.branch(base.id, 'Fictional scenario', scope=company.id)
    store.update(scenario.id, Dataset.model_validate(changed), scope=company.id)
    promoted = store.promote(scenario.id, 'Fictional promoted', scope=company.id)
    assert promoted.kind == 'base'
    try:
        store.db.execute("UPDATE versions SET dataset='{}' WHERE id=?", (base.id,))
    except psycopg.errors.RaiseException:
        pass
    else:
        raise AssertionError('Immutable base was changed')
    store.db.close()
    reopened = Store(os.environ['DATABASE_URL'])
    assert Companies(reopened).open(session.user, company.id).dataset == changed
    reopened.db.close()
    print('POSTGRES SMOKE: accounts, isolation, compressed revisions, versions, immutable trigger and restart passed', flush=True)
    if os.environ.get('SCP_MIGRATION_TEST_URL'):
        subprocess.run([sys.executable, str(Path(__file__).with_name('postgres_migration_smoke.py'))], check=True)


if __name__ == '__main__':
    main()
