"""Fuzzed API inputs never 500.

Every route the API publishes (read from its own OpenAPI document, so a new route is fuzzed the day it is added) is
called with bodies generated from its request schema and then broken: wrong types, missing and unknown keys, huge,
negative and non-finite numbers, impossible dates, nulls, deep nesting; and with junk path and query parameters.
Planning bodies are a small real company with one field broken, so the request gets past parsing into the engine.
Whatever arrives, the answer is a 2xx/3xx/4xx — an input the server cannot handle is the caller's error, said in
words, never an unhandled exception."""
from __future__ import annotations

import copy
import json
import os
import re
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, note, settings
from hypothesis import strategies as st

from scp.api.app import app

from .factory import base, demand

FUZZ = int(os.environ.get("HYPOTHESIS_FUZZ_EXAMPLES", "8"))
SPEC = app.openapi()
SCHEMAS = SPEC["components"]["schemas"]
# a full scenario run is a 30-second benchmark, not an input handler: it is fuzzed with junk ids only
SLOW = {("post", "/api/scenarios/{sid}/run")}

client = TestClient(app, raise_server_exceptions=False, headers={"X-Browser-Key": "fuzz-browser-key-000001"})


def small_company() -> dict:
    d = base(horizon=28)
    d["demand"] = [demand("P", "A", "2026-01-12", 20), demand("P", "A", "2026-01-20", 15, kind="sales_order")]
    return d


SMALL = small_company()

junk = st.one_of(
    st.none(), st.booleans(), st.integers(-2**63, 2**63), st.sampled_from([0, -1, 10**30, 1e308, -1e308]),
    st.floats(allow_nan=True, allow_infinity=True), st.text(max_size=20),
    st.sampled_from(["", " ", "2026-02-30", "2026-13-01", "0000-00-00", "../../etc/passwd", "<script>", "%00",
                     "SO-00001", "PO-00001", "P", "A", "x" * 5000, "\u0000", "🙂", "NaN", "-Infinity"]),
    st.builds(list), st.builds(dict), st.builds(lambda: [[[[[]]]]]),     # fresh objects: a draw may be mutated later
)
json_values = st.recursive(junk, lambda inner: st.one_of(st.lists(inner, max_size=3),
                                                         st.dictionaries(st.text(max_size=8), inner, max_size=3)),
                           max_leaves=8)


def _resolve(s: dict) -> dict:
    while "$ref" in s:
        s = SCHEMAS[s["$ref"].rsplit("/", 1)[-1]]
    return s


def _paths(x, at=()):
    yield at
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _paths(v, (*at, k))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _paths(v, (*at, i))


@st.composite
def broken(draw, doc):
    """``doc`` with one to three places replaced, removed, or given an unknown key."""
    doc = copy.deepcopy(doc)
    for _ in range(draw(st.integers(1, 3))):
        paths = [p for p in _paths(doc) if p]
        if not paths:
            break
        p = draw(st.sampled_from(paths))
        parent = doc
        for k in p[:-1]:
            parent = parent[k]
        how = draw(st.sampled_from(["replace", "replace", "drop", "extra"]))
        if how == "drop":
            del parent[p[-1]]
        elif how == "extra" and isinstance(parent, dict):
            parent[draw(st.text(min_size=1, max_size=8))] = draw(json_values)
        else:
            parent[p[-1]] = draw(json_values)
    return doc


def from_schema(s: dict, depth: int = 0) -> st.SearchStrategy:
    """A value roughly of schema ``s`` (good enough to pass parsing often), any JSON sometimes."""
    if s.get("$ref", "").endswith("/Dataset") or s.get("title") in ("Dataset", "Raw"):
        return st.one_of(st.builds(lambda: copy.deepcopy(SMALL)), broken(SMALL))
    s = _resolve(s)
    if depth > 4:
        return json_values
    if "anyOf" in s or "oneOf" in s:
        return st.one_of(*[from_schema(x, depth + 1) for x in s.get("anyOf") or s.get("oneOf")])
    if "enum" in s:
        return st.sampled_from(s["enum"])
    t = s.get("type")
    if t == "object" or "properties" in s:
        props = s.get("properties", {})
        if not props:
            return st.one_of(st.builds(lambda: copy.deepcopy(SMALL)), broken(SMALL), json_values)
        fields = {k: from_schema(v, depth + 1) for k, v in props.items()}
        return st.fixed_dictionaries({k: v for k, v in fields.items() if k in s.get("required", [])},
                                     optional={k: v for k, v in fields.items() if k not in s.get("required", [])})
    if t == "array":
        return st.lists(from_schema(s.get("items", {}), depth + 1), max_size=3)
    if t == "integer":
        return st.integers(-5, 50)
    if t == "number":
        return st.floats(-10, 1000, allow_nan=False)
    if t == "boolean":
        return st.booleans()
    if t == "string":
        if s.get("format") == "date":
            return st.sampled_from(["2026-01-05", "2026-01-12", "2025-12-31"])
        return st.sampled_from(["", "P", "A", "B", "S", "x", "PO-00001", "SO-00001", "kitchenware_network"])
    return json_values


def _body(op: dict) -> st.SearchStrategy | None:
    schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    if schema is None:
        return None
    good = from_schema(schema)
    return st.one_of(good, good.flatmap(lambda b: broken(b) if isinstance(b, dict | list) and b else st.just(b)),
                     json_values)


def _handled(r) -> bool:
    """Below 500, or a deliberate 503 saying what the server's administrator must configure (fail closed)."""
    if r.status_code < 500:
        return True
    try:
        return r.status_code == 503 and bool(r.json().get("detail"))
    except ValueError:
        return False


ROUTES = sorted((m, p, op) for p, ops in SPEC["paths"].items() for m, op in ops.items())


@pytest.fixture(scope="module")
def owner():
    t = client.post("/api/auth/signup", json={"email": "fuzz@scp.example", "password": "correct horse"}).json()["token"]
    cid = client.post("/api/companies", headers={"Authorization": f"Bearer {t}"}, json={"dataset": SMALL}).json()["id"]
    return t, cid


@pytest.fixture(autouse=True, scope="module")
def _module_store():
    """One store for the module: the owner and the company live across the routes (the per-test store is swapped
    back in by the session's autouse fixture for every other module)."""
    from scp.versions import Store, set_store
    set_store(Store(":memory:"))
    yield


@pytest.fixture(autouse=True)
def _version_store():           # overrides conftest's per-test fresh store: this module keeps one (above)
    yield


@pytest.mark.parametrize("method,path,op", ROUTES, ids=[f"{m.upper()} {p}" for m, p, _ in ROUTES])
def test_fuzzed_inputs_never_500(owner, method, path, op):
    token, cid = owner
    params = op.get("parameters", [])
    body = _body(op)

    @settings(max_examples=FUZZ, suppress_health_check=list(HealthCheck))
    @given(data=st.data())
    def run(data):
        url = path
        for p in params:
            if p["in"] != "path":
                continue
            real = {"cid": cid, "email": "fuzz@scp.example", "name": "kitchenware_network"}.get(p["name"])
            if (method, path) in SLOW:
                real = None
            v = data.draw(st.one_of(st.just(real) if real else st.nothing(),
                                    st.text(min_size=1, max_size=12).filter(lambda s: s not in (".", "..")),
                                    st.sampled_from(["0", "-1", "999999999999", "%2F", "null", "x" * 300])),
                          label=p["name"])
            url = url.replace("{" + p["name"] + "}", quote(re.sub(r"[/?#]", "_", str(v)) or "_", safe=""))
        query = {p["name"]: data.draw(st.one_of(st.text(max_size=10), st.sampled_from(["-1", "0", "1e9", "true",
                                                                                      "2026-02-30"])),
                                      label=p["name"])
                 for p in params if p["in"] == "query" and data.draw(st.booleans(), label=f"send {p['name']}")}
        headers = data.draw(st.sampled_from([{"Authorization": f"Bearer {token}"},
                                             {"Authorization": f"Bearer {token}", "X-Company": cid},
                                             {"Authorization": "Bearer nonsense"}, {}]), label="auth")
        kw: dict = {"params": query, "headers": headers}
        if body is not None:
            payload = data.draw(body, label="body")
            kw["content"] = json.dumps(payload, allow_nan=True).encode()
            kw["headers"] = {**headers, "Content-Type": "application/json"}
        r = client.request(method.upper(), url, **kw)
        note(f"{method.upper()} {url} -> {r.status_code}: {r.text[:300]}")
        assert _handled(r), f"{method.upper()} {url} answered {r.status_code}: {r.text[:500]}"

    run()


@given(raw=st.binary(max_size=200))
@settings(max_examples=FUZZ * 3)
def test_bodies_that_are_not_json_never_500(raw):
    for path in ("/api/plan", "/api/validate", "/api/auth/signin", "/api/forecast"):
        r = client.post(path, content=raw, headers={"Content-Type": "application/json"})
        assert _handled(r), (path, r.status_code, r.text[:300])


@given(path=st.one_of(st.text(min_size=1, max_size=40), st.sampled_from(["x" * 300, "a/" + "x" * 5000, "%00",
                                                                         "assets/" + "x" * 300, "..%2f..%2fetc",
                                                                         "index.html", "api"])))
@settings(max_examples=FUZZ * 3)
def test_any_page_path_never_500(path):
    """The single-page app's catch-all (served when the web client is built) and the static assets."""
    r = client.get("/" + quote(path, safe="/%"))
    assert _handled(r), (path, r.status_code, r.text[:200])
