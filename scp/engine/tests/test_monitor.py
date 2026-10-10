"""Watching the running server (ENTERPRISE_PLAN 1.2): request ids, one log line per call (JSON when asked, never a
body or a query), Prometheus metrics by route pattern, the build commit and the database in the health answer."""
from __future__ import annotations

import io
import json
import logging

from fastapi.testclient import TestClient

from scp.api import monitor
from scp.api.app import app

client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})


def test_every_answer_carries_a_request_id_and_keeps_a_sensible_one_given():
    r = client.get("/api/examples")
    rid = r.headers["x-request-id"]
    assert len(rid) == 32 and int(rid, 16) >= 0
    assert client.get("/api/examples", headers={"X-Request-ID": "lb-7f3a.1"}).headers["x-request-id"] == "lb-7f3a.1"
    # a made-up header that could break a log line is replaced
    assert client.get("/api/examples", headers={"X-Request-ID": "a b\"c"}).headers["x-request-id"] != "a b\"c"


def test_health_says_the_build_and_reaches_the_database(monkeypatch):
    monkeypatch.setenv("SCP_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert h["database"] in ("sqlite", "postgresql") and h["up_seconds"] >= 0
    monkeypatch.delenv("SCP_COMMIT")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "feedface")
    assert client.get("/api/health").json()["commit"] == "feedface"


def test_health_is_503_when_the_database_cannot_be_reached(monkeypatch):
    from scp.versions.store import get_store
    store = get_store()

    class Down:
        backend = store.db.backend if hasattr(store.db, "backend") else "sqlite"

        def execute(self, *_a, **_k):
            raise RuntimeError("connection refused")
    monkeypatch.setattr(store, "db", Down())
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["status"] == "database unreachable"


def test_metrics_count_by_route_pattern_never_by_address():
    client.get("/api/companies/C-does-not-exist/history")
    client.get("/api/examples")
    text = client.get("/api/metrics").text
    assert 'scp_requests_total{method="GET",route="/api/examples",status="200"}' in text
    assert 'route="/api/companies/{cid}/history"' in text and "C-does-not-exist" not in text
    assert 'scp_request_seconds_bucket{route="/api/examples",le="+Inf"}' in text
    assert "scp_requests_in_progress 1" in text           # this call
    assert "scp_build_info{" in text and "scp_process_start_time_seconds" in text


def test_metrics_need_the_token_when_one_is_set(monkeypatch):
    monkeypatch.setenv("SCP_METRICS_TOKEN", "s3cret-scrape")
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/api/metrics", headers={"Authorization": "Bearer s3cret-scrape"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")


def test_metrics_are_open_with_sign_in_required_unless_a_token_guards_them(monkeypatch):
    monkeypatch.setenv("SCP_REQUIRE_SIGNIN", "1")
    assert client.get("/api/metrics").status_code == 200


def test_one_json_log_line_per_call_with_its_request_id_and_nothing_private(monkeypatch):
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.addFilter(monitor._WithRequestId())
    h.setFormatter(monitor.JsonFormatter())
    log = logging.getLogger("scp.request")
    log.addHandler(h)
    try:
        r = client.post("/api/validate?secret=1", json={"settings": {"company_name": "Private Ltd"}},
                        headers={"X-Request-ID": "req-42"})
    finally:
        log.removeHandler(h)
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    line = next(x for x in lines if x.get("route") == "/api/validate")
    assert line["request_id"] == "req-42" and line["method"] == "POST" and line["status"] == r.status_code
    assert line["level"] in ("info", "warning") and line["ms"] >= 0
    raw = buf.getvalue()
    assert "Private Ltd" not in raw and "secret" not in raw
