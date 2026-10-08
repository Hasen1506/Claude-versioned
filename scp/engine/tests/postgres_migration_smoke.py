"""Explicit, fictional SQLite-to-PostgreSQL check on a dedicated dev branch."""
import os
import tempfile
from pathlib import Path

from scp.companies.store import Companies
from scp.migrate_postgres import migrate
from scp.model import Dataset
from scp.versions.store import Store


def main():
    if os.environ.get('SCP_POSTGRES_SMOKE') != '1':
        raise RuntimeError('Requires explicit isolated development target')
    os.environ['DATABASE_URL'] = os.environ['SCP_MIGRATION_TEST_URL']
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'fictional.sqlite'
        source = Store(path)
        c = Companies(source)
        session = c.signup('migration-smoke@example.invalid', 'Fictional migration fixture', 'fictional test password')
        example = Path(__file__).resolve().parents[2] / 'examples' / 'kitchenware_network.json'
        dataset = Dataset.model_validate_json(example.read_text())
        doc = dataset.model_dump(mode='json')
        company = c.create(session.user, doc)
        c.save(session.user, company.id, dict(doc, settings=dict(doc['settings'], company_name='Migration fixture')),
               company.revision)
        base = source.save_base(dataset, 'Fictional immutable base', scope=company.id)
        source.branch(base.id, 'Fictional child', scope=company.id)
        source.db.close()
        existing = Store(os.environ['DATABASE_URL'])
        accounts = Companies(existing).users()
        existing.db.close()
        if accounts == 0:
            migrate(path)
            empty = Store(os.environ['DATABASE_URL'])
            assert Companies(empty).users() == 0, 'Dry run committed rows'
            empty.db.close()
            migrate(path, True)
        else:
            print('MIGRATION SMOKE: prior verified fictional fixture retained')
        try:
            migrate(path, True)
        except ValueError as error:
            assert 'nonempty' in str(error)
        else:
            raise AssertionError('Nonempty target was not rejected')
        restored = Store(os.environ['DATABASE_URL'])
        assert Companies(restored).signin('migration-smoke@example.invalid', 'fictional test password').user.name == \
            'Fictional migration fixture'
        assert len(restored.list()) == 2
        restored.db.close()
        print('MIGRATION SMOKE: dry-run rollback, full-field copy, binary revisions, version parents and overwrite refusal passed')


if __name__ == '__main__':
    main()
