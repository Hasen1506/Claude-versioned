import ipaddress
import os
import socket

import pytest
from hypothesis import HealthCheck, settings

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


# ---- determinism: Hypothesis profiles ------------------------------------------------------------------------------
# ``ci`` (the default) is derandomised: the same examples on every run and every machine, so a red build is always
# reproducible and never flaky; ``deep`` explores (HYPOTHESIS_PROFILE=deep, e.g. nightly or before a release).
_common = dict(deadline=None, database=None, print_blob=True,
               suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow,
                                      HealthCheck.data_too_large])
settings.register_profile("ci", derandomize=True, max_examples=int(os.environ.get("HYPOTHESIS_EXAMPLES", "30")),
                          **_common)
settings.register_profile("deep", derandomize=False, max_examples=500, **_common)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


# ---- no network: a test may talk to this machine (its own servers), never to the internet --------------------------
def _local(address) -> bool:
    if not isinstance(address, tuple):          # AF_UNIX paths
        return True
    host = address[0]
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


_connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex


def _guarded(real):
    def connect(self, address):
        if not _local(address):
            raise OSError(f"tests must not use the network (tried {address!r})")
        return real(self, address)
    return connect


@pytest.fixture(autouse=True, scope="session")
def _no_network():
    socket.socket.connect, socket.socket.connect_ex = _guarded(_connect), _guarded(_connect_ex)
    yield
    socket.socket.connect, socket.socket.connect_ex = _connect, _connect_ex
