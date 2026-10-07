import os

import pytest

from scp.versions import Store, set_store

os.environ.setdefault("SCP_SCHEDULER", "0")   # no clock thread for imports and reminders in tests
# the per-address limits (CV-H11, CV-M04) would trip over a test run's thousands of calls from one client; the tests of
# the limits switch them on themselves
os.environ.setdefault("SCP_AUTH_RATE", "0")
os.environ.setdefault("SCP_ANON_RATE", "0")


@pytest.fixture(autouse=True)
def _version_store():
    """Every test gets a fresh in-memory version store: nothing is written to the user's ~/.scp."""
    set_store(Store(":memory:"))
    yield
    set_store(None)
