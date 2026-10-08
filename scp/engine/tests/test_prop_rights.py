"""Property-based role permissions: a viewer can't write; a planner limited to places changes only those places.

Random changes to a real company (any planning policy, order, receipt, setting, master record, at any place) are saved
by members of each role through the API:

* a **viewer** is refused every write — whole saves, merges, restores, the worklist, members, keys, imports, ERP
  messages — and the company's revision and document are exactly what they were
* a **planner limited to a place** can change that place's planning policies, and is refused (403, nothing written)
  for the same change at any other plant or DC, for company settings and for products themselves
* an **owner** is never limited"""
from __future__ import annotations

import copy
import json

import pytest
from hypothesis import given, note, settings
from hypothesis import strategies as st

from scp.companies import store as company_store

from .strategies import FrozenClock
from .test_audit_fixes import client, example, h, join, new_company, signup

DOC = example()
INNER = ["PLT-PUNE", "DC-BHIWANDI", "DC-DELHI"]            # the places that hold stock and plans
API = settings(max_examples=15)     # each example is a dozen real API calls on a real company
LP_FIELDS = [("on_hand", st.integers(0, 5000)), ("planning_time_fence_days", st.integers(0, 30)),
             ("unit_cost", st.integers(1, 900))]


@pytest.fixture
def team(monkeypatch):
    monkeypatch.setattr(company_store, "_now", FrozenClock())
    owner, viewer, planner = (signup(e) for e in ("own@r.example", "view@r.example", "plan@r.example"))
    cid = new_company(owner, copy.deepcopy(DOC))
    join(owner, cid, viewer, "view@r.example", "viewer")
    join(owner, cid, planner, "plan@r.example", "planner", places=["DC-DELHI"])
    return owner, viewer, planner, cid


def _current(owner: str, cid: str) -> tuple[int, str]:
    got = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    return got["meta"]["revision"], json.dumps(got["dataset"], sort_keys=True)


@st.composite
def any_change(draw):
    """(what, a function that makes the change on a copy of the document)."""
    kind = draw(st.sampled_from(["lp", "demand", "receipt", "setting", "product", "lane", "location"]))
    if kind == "lp":
        i = draw(st.integers(0, len(DOC["location_products"]) - 1))
        f, s = draw(st.sampled_from(LP_FIELDS))
        v = draw(s)
        return f"location_products[{i}].{f}={v}", lambda d: d["location_products"][i].update({f: v})
    if kind == "demand":
        i = draw(st.integers(0, len(DOC["demand"]) - 1))
        v = draw(st.integers(1, 999))
        return f"demand[{i}].qty={v}", lambda d: d["demand"][i].update(qty=v)
    if kind == "receipt" and DOC["receipts"]:
        i = draw(st.integers(0, len(DOC["receipts"]) - 1))
        v = draw(st.integers(1, 999))
        return f"receipts[{i}].qty={v}", lambda d: d["receipts"][i].update(qty=v)
    if kind == "setting":
        v = draw(st.text(min_size=1, max_size=10))
        return f"company_name={v!r}", lambda d: d["settings"].update(company_name=v)
    if kind == "product":
        i = draw(st.integers(0, len(DOC["products"]) - 1))
        v = draw(st.integers(1, 9999))
        return f"products[{i}].price={v}", lambda d: d["products"][i].update(price=v)
    if kind == "lane":
        i = draw(st.integers(0, len(DOC["lanes"]) - 1))
        return f"lanes[{i}] removed", lambda d: d["lanes"].pop(i)
    i = draw(st.integers(0, len(DOC["locations"]) - 1))
    v = draw(st.floats(-80, 80))
    return f"locations[{i}].lat={v}", lambda d: d["locations"][i].update(lat=v)


@API
@given(change=any_change())
def test_a_viewer_can_never_write(team, change):
    owner, viewer, _, cid = team
    what, apply = change
    rev, doc = _current(owner, cid)
    mine = json.loads(doc)
    apply(mine)
    note(what)
    attempts = [
        ("PUT", f"/api/companies/{cid}", {"dataset": mine, "base_revision": rev}),
        ("POST", f"/api/companies/{cid}/merge", {"base": json.loads(doc), "dataset": mine, "base_revision": rev}),
        ("POST", f"/api/companies/{cid}/restore", {"revision": 1, "base_revision": rev}),
        ("POST", f"/api/companies/{cid}/members", {"email": "x@r.example", "role": "owner"}),
        ("POST", f"/api/companies/{cid}/keys", {"name": "k"}),
        ("POST", f"/api/companies/{cid}/imports", {"name": "i", "kind": "orders", "source_type": "url",
                                                   "source": "https://x.example/f"}),
        ("POST", f"/api/companies/{cid}/erp/orders", {"orders": []}),
        ("PUT", f"/api/companies/{cid}/approval", {"approval": True}),
        ("DELETE", f"/api/companies/{cid}", None),
    ]
    for method, url, body in attempts:
        r = client.request(method, url, headers=h(viewer), json=body)
        assert r.status_code in (403, 404), (method, url, r.status_code, r.text[:300])
    assert _current(owner, cid) == (rev, doc), "a viewer's request changed the company"


def test_a_viewer_reads_the_worklist_but_records_nothing(team):
    """CV-H05, on the same team: the viewer's tower call is answered read-only and changes no worklist item."""
    owner, viewer, _, cid = team
    doc = copy.deepcopy(DOC)
    before = client.post("/api/tower", headers=h(owner, cid), json=doc).json()
    mine = copy.deepcopy(doc)
    mine["demand"] = mine["demand"][: len(mine["demand"]) // 2]          # a different plan: other exceptions
    assert client.post("/api/tower", headers=h(viewer, cid), json=mine).status_code == 200
    after = client.post("/api/tower", headers=h(owner, cid), json=doc).json()
    def key(r: dict) -> list:
        return sorted((i["id"], i.get("status")) for i in r.get("items", []))
    assert key(before) == key(after)


@API
@given(i=st.integers(0, len(DOC["location_products"]) - 1), field=st.sampled_from(LP_FIELDS), data=st.data())
def test_a_planner_changes_only_the_places_he_may(team, i, field, data):
    owner, _, planner, cid = team
    f, s = field
    v = data.draw(s, label="value")
    rev, doc = _current(owner, cid)
    mine = json.loads(doc)
    lp = mine["location_products"][i]
    assume_changed = lp.get(f) != v
    lp[f] = v
    r = client.put(f"/api/companies/{cid}", headers=h(planner), json={"dataset": mine, "base_revision": rev})
    note(f"{lp['location']}/{lp['product']}.{f}={v} -> {r.status_code} {r.text[:200]}")
    if lp["location"] == "DC-DELHI":
        assert r.status_code == 200, r.text
    elif assume_changed:
        assert r.status_code == 403 and r.json().get("out_of_scope"), r.text
        assert _current(owner, cid) == (rev, doc)


@API
@given(change=any_change().filter(lambda c: c[0].startswith(("company_name", "products["))))
def test_a_limited_planner_cannot_change_company_settings_or_products(team, change):
    owner, _, planner, cid = team
    what, apply = change
    rev, doc = _current(owner, cid)
    mine = json.loads(doc)
    apply(mine)
    if json.dumps(mine, sort_keys=True) == doc:
        return
    r = client.put(f"/api/companies/{cid}", headers=h(planner), json={"dataset": mine, "base_revision": rev})
    assert r.status_code == 403, (what, r.status_code, r.text[:300])
    assert _current(owner, cid) == (rev, doc)


@API
@given(change=any_change())
def test_an_owner_is_never_limited(team, change):
    owner, _, _, cid = team
    what, apply = change
    rev, doc = _current(owner, cid)
    mine = json.loads(doc)
    apply(mine)
    r = client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": mine, "base_revision": rev})
    assert r.status_code in (200, 422), (what, r.status_code, r.text[:300])     # 422: the change itself is invalid
