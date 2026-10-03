import os

import pytest

from scp.versions import Store, set_store

os.environ.setdefault("SCP_SCHEDULER", "0")   # no clock thread for imports and reminders in tests


@pytest.fixture(autouse=True)
def _version_store():
    """Every test gets a fresh in-memory version store: nothing is written to the user's ~/.scp."""
    set_store(Store(":memory:"))
    yield
    set_store(None)
