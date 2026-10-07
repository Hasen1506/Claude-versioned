"""Property-based imports: a malformed file never crashes the batch (CV-M01).

Scheduled imports of every kind (orders, stock, postings, any master-data list) are fed fuzzed files — random bytes,
broken UTF-8, JSON of every shape, CSV grids with junk cells — next to a good import. Whatever the bad file holds:

* ``run_due`` never raises, and the good import after it still runs and succeeds
* the bad import is logged as a file that could not be read (or as refused rows), never as an unforeseen crash
* every job moves on to its next time (nothing retried in a loop), and the company is never left half-written"""
from __future__ import annotations

import datetime as dt
import json

import pytest
from hypothesis import given, note
from hypothesis import strategies as st

from scp.companies import get_companies
from scp.connect import imports

from .strategies import FROZEN_NOW
from .test_audit_fixes import new_company, signup

KINDS = ["orders", "stock", "postings", "records:products", "records:locations", "records:demand",
         "records:location_products", "records:history"]

scalars = st.one_of(st.none(), st.booleans(), st.integers(-10**12, 10**12), st.floats(allow_nan=True),
                    st.text(max_size=12))
json_values = st.recursive(scalars, lambda inner: st.one_of(st.lists(inner, max_size=4),
                                                            st.dictionaries(st.text(max_size=8), inner, max_size=4)),
                           max_leaves=12)
FIELDS = ["number", "customer", "product", "qty", "date", "location", "id", "type", "ref", "action", "batch",
          "expires_on", "stock_type", "price", "order_date", "cancelled", "final", "kind", "name", ""]
cells = st.one_of(st.text(max_size=10), st.sampled_from(["", "-5", "1e309", "NaN", "31/02/2026", "2026-13-01",
                                                         "abc", "1,5", "  ", "\"", "=cmd()", "∞", "0x10"]))


@st.composite
def csv_files(draw) -> bytes:
    head = draw(st.lists(st.sampled_from(FIELDS), min_size=0, max_size=6))
    rows = draw(st.lists(st.lists(cells, min_size=0, max_size=len(head) + 2), max_size=5))
    sep = draw(st.sampled_from([",", ";", "\t"]))
    text = "\n".join(sep.join(r) for r in [head, *rows])
    return text.encode(draw(st.sampled_from(["utf-8", "utf-16", "latin-1"])), errors="replace")


@st.composite
def json_files(draw, kind: str) -> bytes:
    key = {"orders": "orders", "stock": "stock", "postings": "postings"}.get(kind, "records")
    v = draw(st.one_of(json_values, st.lists(st.dictionaries(st.sampled_from(FIELDS), json_values, max_size=5),
                                             max_size=4).map(lambda xs: {key: xs})))
    try:
        return json.dumps(v, allow_nan=True).encode()
    except (TypeError, ValueError):
        return b"{"


files = st.one_of(st.binary(max_size=200), csv_files())


@pytest.fixture
def company(monkeypatch):
    from scp.companies import store as company_store
    monkeypatch.setattr(company_store, "_now", lambda: FROZEN_NOW)
    o = signup("owner@imports.example")
    c = get_companies()
    return c, c.whoami(o), new_company(o)


@given(data=st.data(), kind=st.sampled_from(KINDS), fmt=st.sampled_from(["csv", "json"]))
def test_a_malformed_file_never_crashes_the_batch(company, monkeypatch, data, kind, fmt):
    c, user, cid = company
    raw = data.draw(files if fmt == "csv" else st.one_of(json_files(kind), st.binary(max_size=80)), label="file")
    served = {"https://bad.example/f": raw, "https://good.example/f": b'{"records": []}'}
    monkeypatch.setattr(imports, "fetch", lambda url, headers: served[url])
    now = FROZEN_NOW
    ids = []
    for name, k, f, url in (("bad", kind, fmt, "https://bad.example/f"),
                            ("good", "records:products", "json", "https://good.example/f")):
        ids.append(imports.save_job(c, user, cid, imports.JobInput(name=name, kind=k, source_type="url", source=url,
                                                                    format=f, every="hour", at="06:00"),
                                    now=now).jobs[-1].id)
    before = c.db.execute("SELECT revision FROM companies WHERE id = ?", (cid,)).fetchone()[0]
    later = now + dt.timedelta(hours=2)
    out = imports.run_due(c, later)                              # never raises
    note(f"{kind}/{fmt}: {[(r.status, r.summary) for rows in out.values() for r in rows]}")
    jobs = {j.id: j for j in imports.jobs(c, user, cid).jobs}
    bad, good = jobs[ids[0]], jobs[ids[1]]
    assert good.last_status != "failed", good.last_summary
    assert not (bad.last_summary or "").startswith("could not run"), bad.last_summary      # foreseen, not a crash
    for j in (bad, good):
        assert j.next_run is not None and j.next_run > later.isoformat()[:16]               # moved on
    after = c.db.execute("SELECT revision FROM companies WHERE id = ?", (cid,)).fetchone()[0]
    assert after - before <= 2                                   # at most one save per import, never a half-write
    assert imports.run_due(c, later) == {}                       # nothing re-runs before its next time
    for jid in ids:
        imports.delete_job(c, user, cid, jid)


@given(kind=st.sampled_from(KINDS), raw=files)
def test_parsing_any_bytes_either_reads_or_says_why(kind, raw):
    for fmt in ("csv", "json"):
        try:
            items = imports.parse(kind, fmt, raw)
        except (ValueError, json.JSONDecodeError):
            continue
        assert isinstance(items, list)
        imports.applier(kind, items)                            # typing rows never raises either
