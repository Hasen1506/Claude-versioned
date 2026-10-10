"""Running it for real (ENTERPRISE_PLAN 1.5): with SCP_ENV=production the server refuses to start open to anyone."""
from __future__ import annotations

import pytest

from scp.api.companies import production_guard


@pytest.mark.parametrize("env, starts", [
    ({}, True),                                                                       # not production: as before
    ({"SCP_ENV": "production"}, False),                                               # open sign-up, no sign-in
    ({"SCP_ENV": "production", "SCP_REQUIRE_SIGNIN": "1"}, True),
    ({"SCP_ENV": "production", "SCP_SIGNUP": "invite"}, True),
    ({"SCP_ENV": "production", "SCP_SIGNUP": "closed"}, True),
    ({"SCP_ENV": "production", "SCP_OPEN_ON_PURPOSE": "1"}, True),                     # a public demonstration
])
def test_production_refuses_to_start_open_to_anyone(monkeypatch, env, starts):
    for k in ("SCP_ENV", "SCP_REQUIRE_SIGNIN", "SCP_SIGNUP", "SCP_OPEN_ON_PURPOSE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if starts:
        production_guard()
    else:
        with pytest.raises(RuntimeError, match="SCP_REQUIRE_SIGNIN=1 and SCP_SIGNUP=invite"):
            production_guard()


def test_the_server_does_not_start_when_the_guard_refuses(monkeypatch):
    from fastapi.testclient import TestClient

    from scp.api.app import app
    for k in ("SCP_REQUIRE_SIGNIN", "SCP_SIGNUP", "SCP_OPEN_ON_PURPOSE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SCP_ENV", "production")
    with pytest.raises(RuntimeError), TestClient(app):
        pass
