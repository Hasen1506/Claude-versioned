"""Phase I: the company kept on the server (Q14): sign-in, members and roles, saves that never overwrite a colleague
unseen, revisions to go back to, an audit trail, and plan versions and the worklist kept per company."""
from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.companies import CompanyError, get_companies
from scp.companies import store as company_store

from .factory import load_example

client = TestClient(app)


def signup(email: str, name: str = "", password: str = "correct horse") -> str:
    r = client.post("/api/auth/signup", json={"email": email, "name": name, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def h(token: str, company: str | None = None) -> dict:
    out = {"Authorization": f"Bearer {token}"}
    if company:
        out["X-Company"] = company
    return out


def example() -> dict:
    return load_example("kitchenware_network").model_dump(mode="json")


def new_company(token: str, doc: dict | None = None) -> str:
    r = client.post("/api/companies", headers=h(token), json={"dataset": doc or example()})
    assert r.status_code == 200, r.text
    return r.json()["id"]


class Clock:
    def __init__(self) -> None:
        self.t = dt.datetime(2026, 9, 28, 9, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.t

    def tick(self, minutes: float) -> None:
        self.t += dt.timedelta(minutes=minutes)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(company_store, "_now", c)
    return c


# ---- accounts -------------------------------------------------------------------------------------------------
def test_an_account_signs_in_and_only_a_hash_of_the_token_is_kept():
    t = signup("Asha@Kaveri.in", "Asha Rao")
    me = client.get("/api/auth/me", headers=h(t)).json()
    assert me["user"]["name"] == "Asha Rao" and me["companies"] == []
    db = get_companies().db
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (t,)).fetchone()[0] == 0
    assert "correct horse" not in str(db.execute("SELECT * FROM users").fetchone()[:])
    t2 = client.post("/api/auth/signin", json={"email": "asha@kaveri.in", "password": "correct horse"}).json()["token"]
    assert client.get("/api/auth/me", headers=h(t2)).status_code == 200            # the e-mail's case does not matter
    r = client.post("/api/auth/signin", json={"email": "asha@kaveri.in", "password": "wrong one"})
    assert r.status_code == 401 and "not right" in r.json()["detail"]
    assert client.post("/api/auth/signup", json={"email": "asha@kaveri.in", "password": "12345678"}).status_code == 409
    assert client.post("/api/auth/signup", json={"email": "ravi@kaveri.in", "password": "short"}).status_code == 422
    client.post("/api/auth/signout", headers=h(t2))
    assert client.get("/api/auth/me", headers=h(t2)).status_code == 401
    assert client.get("/api/auth/me").json()["detail"] == "sign in first"
    for _ in range(10):
        client.post("/api/auth/signin", json={"email": "asha@kaveri.in", "password": "wrong one"})
    r = client.post("/api/auth/signin", json={"email": "asha@kaveri.in", "password": "correct horse"})
    assert r.status_code == 429


def test_a_session_expires_after_thirty_days_unused(clock):
    t = signup("asha@kaveri.in")
    clock.tick(60 * 24 * 29)
    assert client.get("/api/auth/me", headers=h(t)).status_code == 200            # use extends it
    clock.tick(60 * 24 * 31)
    r = client.get("/api/auth/me", headers=h(t))
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_new_accounts_by_invitation_only(monkeypatch):
    monkeypatch.setenv("SCP_SIGNUP", "invite")
    assert client.get("/api/auth/config").json() == {"signup": "invite", "require_signin": False, "first_account": True}
    owner = signup("asha@kaveri.in")                                                # the first account is always allowed
    r = client.post("/api/auth/signup", json={"email": "stranger@x.com", "password": "12345678"})
    assert r.status_code == 403 and "invitation" in r.json()["detail"]
    cid = new_company(owner)
    client.post(f"/api/companies/{cid}/members", headers=h(owner), json={"email": "ravi@kaveri.in", "role": "planner"})
    ravi = signup("ravi@kaveri.in", "Ravi")
    (c,) = client.get("/api/auth/me", headers=h(ravi)).json()["companies"]
    assert c["id"] == cid and c["role"] == "planner"
    monkeypatch.setenv("SCP_SIGNUP", "closed")
    assert client.post("/api/auth/signup", json={"email": "z@x.com", "password": "12345678"}).status_code == 403


# ---- saves ----------------------------------------------------------------------------------------------------
def test_a_save_based_on_an_older_revision_is_refused_and_says_who_saved(clock):
    asha, ravi = signup("asha@kaveri.in", "Asha"), signup("ravi@kaveri.in", "Ravi")
    cid = new_company(asha)
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "ravi@kaveri.in", "role": "planner"})
    a = client.get(f"/api/companies/{cid}", headers=h(asha)).json()
    b = client.get(f"/api/companies/{cid}", headers=h(ravi)).json()
    assert a["meta"]["revision"] == b["meta"]["revision"] == 1 and a["meta"]["name"].startswith("Kaveri")
    doc = a["dataset"]
    doc["products"][0]["price"] = 1234
    clock.tick(1)
    r = client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": doc, "base_revision": 1})
    assert r.status_code == 200 and r.json()["saved"] and r.json()["meta"]["revision"] == 2
    assert r.json()["summary"] == "products: 1 changed"
    theirs = b["dataset"]
    theirs["settings"]["company_name"] = "Kaveri Home"
    r = client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": theirs, "base_revision": 1})
    assert r.status_code == 409
    body = r.json()
    assert body["revision"] == 2 and body["updated_by"] == "Asha" and "Asha saved this company" in body["detail"]
    # the same document again is not a new revision
    r = client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": doc, "base_revision": 2})
    assert r.json() == {**r.json(), "saved": False, "summary": "nothing changed"} and r.json()["meta"]["revision"] == 2
    # a working copy with unfinished records is kept as it is
    doc["products"].append({"id": "HALF-DONE"})
    r = client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": doc, "base_revision": 2})
    assert r.status_code == 200
    assert client.get(f"/api/companies/{cid}", headers=h(ravi)).json()["dataset"]["products"][-1] == {"id": "HALF-DONE"}
    assert client.get("/api/companies", headers=h(ravi)).json()[0]["updated_by"] == "Asha"


def test_roles_decide_who_may_change_the_data_and_the_members():
    asha, ravi, meera, other = (signup(e) for e in ("asha@k.in", "ravi@k.in", "meera@k.in", "other@x.in"))
    cid = new_company(asha)
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "ravi@k.in", "role": "planner"})
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "meera@k.in", "role": "viewer"})
    doc = client.get(f"/api/companies/{cid}", headers=h(meera)).json()["dataset"]  # a viewer reads it
    doc["products"][0]["price"] = 1
    r = client.put(f"/api/companies/{cid}", headers=h(meera), json={"dataset": doc, "base_revision": 1})
    assert r.status_code == 403 and "as a viewer of this company you cannot change its data" in r.json()["detail"]
    assert client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": doc, "base_revision": 1}).status_code == 200
    r = client.post(f"/api/companies/{cid}/members", headers=h(ravi), json={"email": "x@k.in", "role": "owner"})
    assert r.status_code == 403 and "manage its members" in r.json()["detail"]
    assert client.get(f"/api/companies/{cid}", headers=h(other)).status_code == 404   # not even that it exists
    r = client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "asha@k.in", "role": "planner"})
    assert r.status_code == 409 and "needs an owner" in r.json()["detail"]
    assert client.delete(f"/api/companies/{cid}/members/asha@k.in", headers=h(asha)).status_code == 409
    members = client.post(f"/api/companies/{cid}/members", headers=h(asha),
                          json={"email": "new@k.in", "role": "viewer"}).json()
    assert [(m["email"], m["role"], m["user_id"] is None) for m in members][-1] == ("new@k.in", "viewer", True)
    members = client.delete(f"/api/companies/{cid}/members/new@k.in", headers=h(asha)).json()
    assert "new@k.in" not in [m["email"] for m in members]
    client.delete(f"/api/companies/{cid}/members/meera@k.in", headers=h(asha))
    assert client.get(f"/api/companies/{cid}", headers=h(meera)).status_code == 404
    assert client.delete(f"/api/companies/{cid}", headers=h(ravi)).status_code == 403
    assert client.delete(f"/api/companies/{cid}", headers=h(asha)).status_code == 200
    assert client.get("/api/companies", headers=h(asha)).json() == []


# ---- revisions and the audit trail ----------------------------------------------------------------------------
def test_saves_are_kept_per_ten_minute_run_and_a_company_can_be_put_back(clock):
    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    cid = new_company(asha)
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "ravi@k.in", "role": "planner"})
    doc = example()
    rev = 1
    for i in range(3):                                   # Asha: three saves in four minutes
        clock.tick(2 if i else 1)
        doc["products"][0]["price"] = 100 + i
        rev = client.put(f"/api/companies/{cid}", headers=h(asha),
                         json={"dataset": doc, "base_revision": rev}).json()["meta"]["revision"]
    clock.tick(1)
    doc["demand"] = doc["demand"][:-2]
    doc["locations"][0]["name"] = "Pune works"
    rev = client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": doc, "base_revision": rev}).json()["meta"]["revision"]
    assert rev == 5
    hist = client.get(f"/api/companies/{cid}/history", headers=h(asha)).json()
    assert [(x["revision"], x["user"], x["action"], x["kept"]) for x in hist if x["action"] != "member"] == [
        (5, "Ravi", "saved", True), (4, "Asha", "saved", True), (3, "Asha", "saved", False),
        (2, "Asha", "saved", False), (1, "Asha", "created", True)]
    top = hist[0]
    assert "orders and forecasts: 2 removed" in top["summary"] and "places: 1 changed" in top["summary"]
    lists = {c["list"]: c for c in top["changes"]}
    assert lists["places"]["names"] == ["~ PLT-PUNE"] and len(lists["orders and forecasts"]["names"]) == 2
    assert any(x["action"] == "member" and x["summary"] == "Ravi added as planner" for x in hist)
    r = client.get(f"/api/companies/{cid}/revisions/3", headers=h(asha))
    assert r.status_code == 404 and "not kept" in r.json()["detail"]
    assert client.get(f"/api/companies/{cid}/revisions/4", headers=h(asha)).json()["products"][0]["price"] == 102
    clock.tick(15)                                       # a new run of Asha's saves keeps its own copy
    doc["products"][0]["price"] = 7
    client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": doc, "base_revision": 5})
    kept = {x["revision"] for x in client.get(f"/api/companies/{cid}/history", headers=h(asha)).json() if x["kept"]}
    assert kept == {1, 4, 5, 6}
    r = client.post(f"/api/companies/{cid}/restore", headers=h(asha), json={"revision": 1, "base_revision": 6})
    assert r.status_code == 200 and r.json()["meta"]["revision"] == 7
    now = client.get(f"/api/companies/{cid}", headers=h(ravi)).json()["dataset"]
    assert now == example()
    top = client.get(f"/api/companies/{cid}/history", headers=h(asha)).json()[0]
    assert top["action"] == "restored" and top["summary"].startswith("put back to revision 1: ") and top["kept"]
    assert client.post(f"/api/companies/{cid}/restore", headers=h(asha),
                       json={"revision": 1, "base_revision": 6}).status_code == 409


# ---- plan versions and the worklist belong to the company -----------------------------------------------------
def test_plan_versions_and_the_worklist_are_kept_per_company():
    asha, meera, other = signup("asha@k.in"), signup("meera@k.in"), signup("other@x.in")
    cid = new_company(asha)
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "meera@k.in", "role": "viewer"})
    ds = example()
    r = client.post("/api/versions", headers=h(asha, cid), json={"dataset": ds, "name": "Oct cycle"})
    assert r.status_code == 200
    vid = r.json()["id"]
    assert [v["id"] for v in client.get("/api/versions", headers=h(meera, cid)).json()] == [vid]
    assert client.get("/api/versions").json() == []                                # not in the browser's own
    assert client.get(f"/api/versions/{vid}").status_code == 404
    local = client.post("/api/versions", json={"dataset": ds, "name": "mine"}).json()["id"]
    assert [v["id"] for v in client.get("/api/versions", headers=h(asha, cid)).json()] == [vid]
    assert client.get(f"/api/versions/{local}", headers=h(asha, cid)).status_code == 404
    r = client.post(f"/api/versions/{vid}/branch", headers=h(meera, cid), json={"name": "what if"})
    assert r.status_code == 403
    sc = client.post(f"/api/versions/{vid}/branch", headers=h(asha, cid), json={"name": "what if"}).json()["id"]
    assert client.get(f"/api/versions/{sc}", headers=h(asha, cid)).status_code == 200
    assert client.get("/api/versions", headers=h(other, cid)).status_code == 404   # not a member
    assert client.get("/api/versions", headers={"X-Company": cid}).status_code == 401
    # the worklist: items are the company's
    w = client.post("/api/tower", headers=h(asha, cid), json=ds).json()["worklist"]
    assert w
    iid = w[0]["id"]
    assert client.post(f"/api/tower/items/{iid}", json={"status": "acknowledged"}).status_code == 404
    assert client.post(f"/api/tower/items/{iid}", headers=h(meera, cid), json={"status": "acknowledged"}).status_code == 403
    r = client.post(f"/api/tower/items/{iid}", headers=h(asha, cid), json={"status": "acknowledged"})
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    local_items = {x["id"] for x in client.post("/api/tower", json=ds).json()["worklist"]}
    assert iid not in local_items                                                  # the browser's worklist is its own


def test_a_server_that_requires_sign_in_answers_nobody_else(monkeypatch):
    monkeypatch.setenv("SCP_REQUIRE_SIGNIN", "1")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/config").json()["require_signin"] is True
    ds = example()
    r = client.post("/api/validate", json=ds)
    assert r.status_code == 401 and r.json()["detail"] == "sign in first"
    t = signup("asha@k.in")
    assert client.post("/api/validate", headers=h(t), json=ds).status_code == 200
    r = client.get("/api/versions", headers=h(t))
    assert r.status_code == 403 and "open a company first" in r.json()["detail"]
    cid = new_company(t)
    assert client.get("/api/versions", headers=h(t, cid)).status_code == 200


def test_the_store_refuses_what_the_rules_do_not_allow():
    c = get_companies()
    s = c.signup("asha@k.in", "Asha", "12345678")
    with pytest.raises(CompanyError, match="e-mail"):
        c.signup("not an address", "", "12345678")
    meta = c.create(s.user, {"settings": {"company_name": ""}})
    assert meta.name == "Unnamed company" and meta.role == "owner"
    with pytest.raises(CompanyError, match="a role is one of"):
        c.set_member(s.user, meta.id, "x@k.in", "admin")


# ---- merging two people's changes -----------------------------------------------------------------------------
def test_two_people_taking_an_order_at_once_both_keep_theirs_after_a_merge():
    from scp.companies.merge import merge
    from scp.model import Dataset, DemandRecord
    from scp.promise.orders import accept

    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    base = example()
    cid = new_company(asha, base)
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "ravi@k.in", "role": "planner"})
    ds = Dataset.model_validate(base)
    cust = next(d for d in ds.demand if d.kind == "sales_order")

    def taken(qty: float, ref: str) -> dict:
        x, rep = accept(ds, DemandRecord(location=cust.location, product=cust.product, date=cust.date, qty=qty,
                                         kind="sales_order", customer_ref=ref))
        return x.model_dump(mode="json"), rep.order

    theirs, oid = taken(5, "RAVI-1")
    mine, oid2 = taken(7, "ASHA-1")
    assert oid == oid2                                              # both got the same next number
    mine["products"][0]["price"] = 999                              # and Asha changed a price too
    assert client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": theirs, "base_revision": 1}).status_code == 200
    assert client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": mine, "base_revision": 1}).status_code == 409
    r = client.post(f"/api/companies/{cid}/merge", headers=h(asha), json={"base": base, "dataset": mine, "base_revision": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    n = int(oid.split("-")[1])
    new = f"SO-{n + 1:05d}"
    assert body["merged_with"] == "Ravi" and body["report"]["renumbered"] == [f"{oid} → {new}"]
    assert body["report"]["conflicts"] == [] and body["meta"]["revision"] == 3
    got = client.get(f"/api/companies/{cid}", headers=h(ravi)).json()["dataset"]
    assert got == body["dataset"]
    orders = {d["id"]: d for d in got["demand"] if d["id"] in (oid, new)}
    assert (orders[oid]["customer_ref"], orders[oid]["qty"]) == ("RAVI-1", 5)
    assert (orders[new]["customer_ref"], orders[new]["qty"]) == ("ASHA-1", 7)
    assert sum(c["qty"] for c in got["confirmations"] if c["order"] == new) == pytest.approx(7)   # her promise follows
    assert sum(c["qty"] for c in got["confirmations"] if c["order"] == oid) == pytest.approx(5)
    assert got["products"][0]["price"] == 999
    Dataset.model_validate(got)
    top = client.get(f"/api/companies/{cid}/history", headers=h(asha)).json()[0]
    assert top["action"] == "merged" and top["summary"].startswith("merged with Ravi's save")
    # the rules of a merge on their own
    b = {"settings": {"a": 1, "b": 1}, "products": [{"id": "A", "price": 1}, {"id": "B", "price": 1}, {"id": "C"}]}
    m = {"settings": {"a": 2, "b": 1}, "products": [{"id": "A", "price": 2}, {"id": "B", "price": 3}]}
    t = {"settings": {"a": 1, "b": 5}, "products": [{"id": "A", "price": 1}, {"id": "B", "price": 4}, {"id": "C"},
                                                    {"id": "D"}]}
    out, rep = merge(b, m, t)
    assert out["settings"] == {"a": 2, "b": 5}
    assert out["products"] == [{"id": "A", "price": 2}, {"id": "B", "price": 4}, {"id": "D"}]   # C removed here
    assert rep.conflicts == ["products B"] and "1 changed on both sides (theirs kept)" in rep.summary


def test_an_autosave_merge_refuses_when_a_record_changed_on_both_sides():
    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    base = example()
    cid = new_company(asha, base)
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "ravi@k.in", "role": "planner"})
    theirs, mine = json.loads(json.dumps(base)), json.loads(json.dumps(base))
    theirs["products"][0]["price"] = 111
    mine["products"][0]["price"] = 222
    assert client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": theirs, "base_revision": 1}).status_code == 200
    body = {"base": base, "dataset": mine, "base_revision": 1, "clean_only": True}
    r = client.post(f"/api/companies/{cid}/merge", headers=h(asha), json=body)
    assert r.status_code == 409 and r.json()["revision"] == 2 and r.json()["updated_by"] == "Ravi"
    assert client.get(f"/api/companies/{cid}", headers=h(asha)).json()["meta"]["revision"] == 2   # nothing saved
    mine["products"][0]["price"] = theirs["products"][0]["price"]
    mine["products"][1]["price"] = 333                               # a different record: merged without asking
    r = client.post(f"/api/companies/{cid}/merge", headers=h(asha), json=body | {"dataset": mine})
    assert r.status_code == 200 and r.json()["report"]["conflicts"] == []
    got = client.get(f"/api/companies/{cid}", headers=h(ravi)).json()["dataset"]
    assert (got["products"][0]["price"], got["products"][1]["price"]) == (111, 333)
