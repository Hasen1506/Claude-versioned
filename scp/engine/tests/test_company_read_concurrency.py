"""Account and role reads must not observe another request's uncommitted transaction."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from scp.companies import get_companies


@pytest.mark.parametrize("read", ["users", "role"])
def test_read_waits_for_a_writer_and_observes_the_committed_state(read):
    companies = get_companies()
    owner = companies.signup("concurrency@example.invalid", "Concurrency owner", "audit-password").user
    cid = companies.create(owner, {"settings": {"company_name": "Concurrent read audit"}}).id
    started, finished = Event(), Event()

    def query():
        started.set()
        try:
            return companies.users() if read == "users" else companies.role(owner, cid)
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with companies.lock:
            companies.db.execute("BEGIN")
            try:
                if read == "users":
                    companies.db.execute(
                        "INSERT INTO users (id, email, name, pw_salt, pw_hash, created_at) "
                        "SELECT 'pending', 'pending@example.invalid', name, pw_salt, pw_hash, created_at "
                        "FROM users WHERE id = ?", (owner.id,))
                else:
                    companies.db.execute("DELETE FROM members WHERE company_id = ?", (cid,))
                future = pool.submit(query)
                assert started.wait(2), "reader did not start"
                # The transaction will roll back; another request must never see its temporary state.
                premature = finished.wait(0.1)
            finally:
                companies.db.execute("ROLLBACK")
        result = future.result(timeout=2)
    assert not premature, "another request read an uncommitted transaction"
    assert result == (1 if read == "users" else "owner")

