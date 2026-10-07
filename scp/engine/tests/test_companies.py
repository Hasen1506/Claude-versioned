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

client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})


def signup(email: str, name: str = "", password: str = "correct horse") -> str:
    r = client.post("/api/auth/signup", json={"email": email, "name": name, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def h(token: str, company: str | None = None) -> dict:
    out = {"Authorization": f"Bearer {token}"}
    if company:
        out["X-Company"] = company
    return out


def join(owner: str, cid: str, email: str, role: str, **kw) -> list[dict]:
    """Invite ``email`` and accept the invitation as that account (CV-C01: nobody joins unasked)."""
    r = client.post(f"/api/companies/{cid}/members", headers=h(owner), json={"email": email, "role": role, **kw})
    assert r.status_code == 200, r.text
    link = next((m["invite_link"] for m in r.json() if m["email"] == email and m.get("invite_link")), None)
    if link is not None:
        c = get_companies()
        uid = c.db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
        c.accept_invite(c._user(uid), token=link.rsplit("/", 1)[1])
    return r.json()


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
    assert client.post("/api/auth/signup", json={"email": "asha@kaveri.in", "password": "kaveri-2026-river"}).status_code == 409
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
    assert client.get("/api/auth/config").json() == {"signup": "invite", "require_signin": False, "first_account": True,
                                                     "mail": False, "sso": None, "password_min": 12}
    owner = signup("asha@kaveri.in")                                                # the first account is always allowed
    r = client.post("/api/auth/signup", json={"email": "stranger@x.com", "password": "kaveri-2026-river"})
    assert r.status_code == 403 and "invitation" in r.json()["detail"]
    cid = new_company(owner)
    r = client.post(f"/api/companies/{cid}/members", headers=h(owner), json={"email": "ravi@kaveri.in", "role": "planner"})
    link = next(m["invite_link"] for m in r.json() if m["email"] == "ravi@kaveri.in")
    assert "/#/account/invite/" in link
    ravi = signup("ravi@kaveri.in", "Ravi")                                       # the invitation lets him sign up …
    assert client.get("/api/auth/me", headers=h(ravi)).json()["companies"] == []  # … but he joins only by accepting
    r = client.post("/api/auth/invites/accept", headers=h(ravi), json={"token": link.rsplit("/", 1)[1]})
    assert r.status_code == 200, r.text
    (c,) = client.get("/api/auth/me", headers=h(ravi)).json()["companies"]
    assert c["id"] == cid and c["role"] == "planner"
    monkeypatch.setenv("SCP_SIGNUP", "closed")
    assert client.post("/api/auth/signup", json={"email": "z@x.com", "password": "kaveri-2026-river"}).status_code == 403


# ---- saves ----------------------------------------------------------------------------------------------------
def test_a_save_based_on_an_older_revision_is_refused_and_says_who_saved(clock):
    asha, ravi = signup("asha@kaveri.in", "Asha"), signup("ravi@kaveri.in", "Ravi")
    cid = new_company(asha)
    join(asha, cid, "ravi@kaveri.in", "planner")
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
    join(asha, cid, "ravi@k.in", "planner")
    join(asha, cid, "meera@k.in", "viewer")
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
def test_every_save_is_kept_and_a_company_can_be_put_back_to_any_of_them(clock):
    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    cid = new_company(asha)
    join(asha, cid, "ravi@k.in", "planner")
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
        (5, "Ravi", "saved", True), (4, "Asha", "saved", True), (3, "Asha", "saved", True),
        (2, "Asha", "saved", True), (1, "Asha", "created", True)]
    top = hist[0]
    assert "orders and forecasts: 2 removed" in top["summary"] and "places: 1 changed" in top["summary"]
    lists = {c["list"]: c for c in top["changes"]}
    assert lists["places"]["names"] == ["~ PLT-PUNE"] and len(lists["orders and forecasts"]["names"]) == 2
    assert any(x["action"] == "member" and x["summary"] == "Ravi accepted the invitation and joined as planner" for x in hist)
    # every save opens as it was (R19), though only the first is kept whole
    for r, price in ((2, 100), (3, 101), (4, 102)):
        assert client.get(f"/api/companies/{cid}/revisions/{r}", headers=h(asha)).json()["products"][0]["price"] == price
    kinds = [r["kind"] for r in get_companies().db.execute(
        "SELECT kind FROM company_revisions WHERE company_id = ? ORDER BY revision", (cid,))]
    assert kinds == ["full", "delta", "delta", "delta", "delta"]
    r = client.post(f"/api/companies/{cid}/restore", headers=h(asha), json={"revision": 1, "base_revision": 5})
    assert r.status_code == 200 and r.json()["meta"]["revision"] == 6
    now = client.get(f"/api/companies/{cid}", headers=h(ravi)).json()["dataset"]
    assert now == example()
    top = client.get(f"/api/companies/{cid}/history", headers=h(asha)).json()[0]
    assert top["action"] == "restored" and top["summary"].startswith("put back to revision 1: ") and top["kept"]
    assert client.post(f"/api/companies/{cid}/restore", headers=h(asha),
                       json={"revision": 1, "base_revision": 5}).status_code == 409


def test_a_long_run_of_saves_keeps_a_whole_copy_every_so_often_and_old_gaps_stay_unopenable(clock):
    asha = signup("asha@k.in", "Asha")
    cid = new_company(asha)
    doc, rev = example(), 1
    for i in range(60):
        clock.tick(1)
        doc["products"][i % 3]["price"] = 1000 + i
        rev = client.put(f"/api/companies/{cid}", headers=h(asha),
                         json={"dataset": doc, "base_revision": rev}).json()["meta"]["revision"]
    kinds = [r["kind"] for r in get_companies().db.execute(
        "SELECT kind FROM company_revisions WHERE company_id = ? ORDER BY revision", (cid,))]
    assert len(kinds) == 61 and kinds.count("full") == 3 and kinds[0] == kinds[26] == kinds[52] == "full"
    for r in (1, 25, 26, 27, 40, 61):
        got = client.get(f"/api/companies/{cid}/revisions/{r}", headers=h(asha)).json()
        assert got["products"][(r - 2) % 3]["price"] == 1000 + r - 2 if r > 1 else got == example()
    # a company saved before every save was kept (Phase I kept one per ten-minute run): the gaps say so
    get_companies().db.execute("DELETE FROM company_revisions WHERE company_id = ? AND revision IN (30, 31)", (cid,))
    kept = {x["revision"] for x in client.get(f"/api/companies/{cid}/history?limit=100", headers=h(asha)).json()
            if x["kept"]}
    assert kept == set(range(1, 30)) | set(range(53, 62))
    r = client.get(f"/api/companies/{cid}/revisions/40", headers=h(asha))
    assert r.status_code == 404 and "not kept" in r.json()["detail"]


def test_a_save_sends_only_what_changed_and_a_patch_that_does_not_fit_is_refused(clock):
    from scp.companies.patch import PatchError, apply_patch, make_patch

    asha = signup("asha@k.in", "Asha")
    base = example()
    cid = new_company(asha, base)
    mine = json.loads(json.dumps(base))
    mine["products"][1]["price"] = 55
    mine["demand"] = mine["demand"][1:] + [{**mine["demand"][0], "id": "SO-NEW", "qty": 3}]
    mine["settings"]["company_name"] = "Kaveri Kitchens"
    del mine["overrides"]
    p = make_patch(base, mine)
    assert apply_patch(base, p) == mine
    assert set(p) == {"v", "lists", "set", "drop", "sizes"} and p["drop"] == ["overrides"]
    assert [r["id"] for r in p["lists"]["products"]["upsert"]] == [base["products"][1]["id"]]
    assert len(json.dumps(p)) * 20 < len(json.dumps(mine))
    r = client.put(f"/api/companies/{cid}", headers=h(asha), json={"patch": p, "base_revision": 1})
    assert r.status_code == 200 and r.json()["meta"]["revision"] == 2
    assert client.get(f"/api/companies/{cid}", headers=h(asha)).json()["dataset"] == mine
    # records re-ordered, or two with one key: the list goes whole
    shuffled = {**mine, "products": mine["products"][::-1]}
    assert "products" in make_patch(mine, shuffled)["set"] and apply_patch(mine, make_patch(mine, shuffled)) == shuffled
    # sent against the wrong company: refused, and the sender is told to send it whole
    wrong = {**p, "sizes": {**p["sizes"], "products": 999}}
    r = client.put(f"/api/companies/{cid}", headers=h(asha), json={"patch": wrong, "base_revision": 2})
    assert r.status_code == 409 and r.json()["patch"] == "unfit" and "send the whole company" in r.json()["detail"]
    with pytest.raises(PatchError):
        apply_patch(base, {"v": 1, "lists": {"products": {"remove": [["NOPE"]]}}})


def test_the_keys_the_browser_patches_by_are_the_servers():
    import pathlib
    import re

    from scp.versions.diff import KEYS, SINGLE

    ts = (pathlib.Path(__file__).parents[2] / "web" / "src" / "lib" / "patch.ts").read_text()
    body = re.search(r"export const KEYS[^{]*\{(.*?)\};", ts, re.S).group(1)
    got = {m.group(1): tuple(re.findall(r'"([^"]+)"', m.group(2)))
           for m in re.finditer(r'(\w+): \[([^\]]*)\]', body)}
    assert got == KEYS
    single = re.search(r"export const SINGLE[^\[]*\[(.*?)\]", ts, re.S).group(1)
    assert tuple(re.findall(r'"([^"]+)"', single)) == SINGLE


def test_a_reload_during_a_save_is_not_taken_for_a_colleague(clock):
    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    cid = new_company(asha)
    join(asha, cid, "ravi@k.in", "planner")
    doc = example()
    w1 = {**h(ravi), "X-Client": "tab-1"}
    doc["products"][0]["price"] = 10
    assert client.put(f"/api/companies/{cid}", headers=w1, json={"dataset": doc, "base_revision": 1}).status_code == 200
    # the answer never reached the page (it reloaded): it saves again on revision 1, with more changes
    doc["products"][1]["price"] = 20
    r = client.put(f"/api/companies/{cid}", headers=w1, json={"dataset": doc, "base_revision": 1})
    assert r.status_code == 200 and r.json()["own"] and r.json()["meta"]["revision"] == 3
    got = client.get(f"/api/companies/{cid}", headers=h(asha)).json()["dataset"]
    assert (got["products"][0]["price"], got["products"][1]["price"]) == (10, 20)
    # the same person in another window: refused, marked as their own, and merged keeping their latest change
    other = json.loads(json.dumps(doc))
    other["products"][0]["price"] = 11
    r = client.put(f"/api/companies/{cid}", headers={**h(ravi), "X-Client": "tab-2"},
                   json={"dataset": other, "base_revision": 2})
    assert r.status_code == 409 and r.json()["self"] is True
    r = client.post(f"/api/companies/{cid}/merge", headers={**h(ravi), "X-Client": "tab-2"},
                    json={"dataset": other, "base_revision": 2, "clean_only": True})
    assert r.status_code == 200 and r.json()["merged_with"] == "you"
    assert r.json()["dataset"]["products"][0]["price"] == 11
    # a colleague's save in between is still a colleague's
    doc = r.json()["dataset"]
    rev = r.json()["meta"]["revision"]
    doc["products"][2]["price"] = 30
    assert client.put(f"/api/companies/{cid}", headers={**h(asha), "X-Client": "a"},
                      json={"dataset": doc, "base_revision": rev}).status_code == 200
    doc["products"][2]["price"] = 31
    r = client.put(f"/api/companies/{cid}", headers=w1, json={"dataset": doc, "base_revision": rev})
    assert r.status_code == 409 and r.json()["updated_by"] == "Asha" and r.json()["self"] is False


def test_a_clash_shows_both_versions_and_each_record_is_kept_as_chosen(clock):
    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    base = example()
    cid = new_company(asha, base)
    join(asha, cid, "ravi@k.in", "planner")
    theirs, mine = json.loads(json.dumps(base)), json.loads(json.dumps(base))
    p0, p1 = base["products"][0]["id"], base["products"][1]["id"]
    theirs["products"][0]["price"], mine["products"][0]["price"] = 111, 222
    theirs["products"][1]["price"], mine["products"][1]["price"] = 5, 6
    theirs["settings"]["company_name"], mine["settings"]["company_name"] = "Theirs Ltd", "Mine Ltd"
    assert client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": theirs, "base_revision": 1}).status_code == 200
    r = client.post(f"/api/companies/{cid}/merge", headers=h(asha),
                    json={"dataset": mine, "base_revision": 1, "preview": True})
    assert r.status_code == 200 and r.json()["saved"] is False
    assert client.get(f"/api/companies/{cid}", headers=h(asha)).json()["meta"]["revision"] == 2   # nothing saved
    clashes = {c["id"]: c for c in r.json()["report"]["clashes"]}
    assert set(clashes) == {f"products {p0}", f"products {p1}", "settings.company_name"}
    c = clashes[f"products {p0}"]
    assert (c["list"], c["record"], c["kept"], c["group"]) == ("products", p0, "theirs", f"products {p0}")
    assert [(f["path"], f["base"], f["mine"], f["theirs"]) for f in c["fields"]] == [
        ("price", base["products"][0]["price"], 222, 111)]
    s = clashes["settings.company_name"]
    assert s["list"] == "company settings"
    assert [(f["path"], f["mine"], f["theirs"]) for f in s["fields"]] == [("", "Mine Ltd", "Theirs Ltd")]
    r = client.post(f"/api/companies/{cid}/merge", headers=h(asha), json={
        "dataset": mine, "base_revision": 1, "choose": {f"products {p0}": "mine", "settings.company_name": "mine"}})
    assert r.status_code == 200 and "yours kept for 2, theirs for 1" in r.json()["report"]["summary"]
    got = client.get(f"/api/companies/{cid}", headers=h(ravi)).json()["dataset"]
    assert (got["products"][0]["price"], got["products"][1]["price"], got["settings"]["company_name"]) == (222, 5, "Mine Ltd")


# ---- plan versions and the worklist belong to the company -----------------------------------------------------
def test_plan_versions_and_the_worklist_are_kept_per_company():
    asha, meera, other = signup("asha@k.in"), signup("meera@k.in"), signup("other@x.in")
    cid = new_company(asha)
    join(asha, cid, "meera@k.in", "viewer")
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
    s = c.signup("asha@k.in", "Asha", "kaveri-2026-river")
    with pytest.raises(CompanyError, match="e-mail"):
        c.signup("not an address", "", "kaveri-2026-river")
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
    join(asha, cid, "ravi@k.in", "planner")
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
    join(asha, cid, "ravi@k.in", "planner")
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


# ---- Phase L: rights by place and product group, master-data approval, change documents ------------------------
def _lp(doc: dict, loc: str, prod: str) -> dict:
    return next(x for x in doc["location_products"] if x["location"] == loc and x["product"] == prod)


def test_a_planner_limited_to_a_place_and_a_product_group_changes_only_those_records(clock):
    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    cid = new_company(asha)
    join(asha, cid, "ravi@k.in", "planner", places=["DC-DELHI"], families=["Mixer grinders"])
    r = client.get(f"/api/companies/{cid}/members", headers=h(asha))
    assert [(m["email"], m["places"], m["families"]) for m in r.json() if m["email"] == "ravi@k.in"] == [
        ("ravi@k.in", ["DC-DELHI"], ["Mixer grinders"])]
    assert client.get("/api/companies", headers=h(ravi)).json()[0]["places"] == ["DC-DELHI"]
    doc = example()
    _lp(doc, "DC-DELHI", "MG-500")["safety_stock"]["service_level"] = 0.99          # his place, his group
    r = client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": doc, "base_revision": 1})
    assert r.status_code == 200, r.text
    # an order his place's customer placed (the customer is served from Delhi): his too
    order = next(d for d in doc["demand"] if d["location"] == "CUS-NORTH-TRADE" and d["product"] == "MG-500")
    order["qty"] += 1
    assert client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": doc, "base_revision": 2}).status_code == 200
    # another place, another group, a product itself, the company settings: not his
    for change in (lambda d: _lp(d, "DC-BHIWANDI", "MG-500")["safety_stock"].update(service_level=0.9),
                   lambda d: _lp(d, "DC-DELHI", "KT-15")["safety_stock"].update(service_level=0.9),
                   lambda d: d["products"][0].update(price=1),
                   lambda d: d["settings"].update(company_name="Mine")):
        mine = json.loads(json.dumps(doc))
        change(mine)
        r = client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": mine, "base_revision": 3})
        assert r.status_code == 403 and r.json()["out_of_scope"] and "your rights cover the places DC-DELHI and the " \
            "product groups Mixer grinders" in r.json()["detail"], r.text
    assert "planning policies DC-BHIWANDI MG-500" in client.put(
        f"/api/companies/{cid}", headers=h(ravi), json={"dataset": (lambda d: (_lp(d, "DC-BHIWANDI", "MG-500")["safety_stock"].update(
            service_level=0.9), d)[1])(json.loads(json.dumps(doc))), "base_revision": 3}).json()["detail"]
    # the owner is never limited; taking the limits away frees him
    client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "ravi@k.in", "role": "planner",
                                                                        "places": [], "families": []})
    mine = json.loads(json.dumps(doc))
    mine["settings"]["company_name"] = "Mine"
    assert client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": mine, "base_revision": 3}).status_code == 200
    log = [x["summary"] for x in client.get(f"/api/companies/{cid}/history", headers=h(asha)).json() if x["action"] == "member"]
    assert "ravi@k.in invited as planner, limited to places DC-DELHI and product groups Mixer grinders" in log
    assert "Ravi accepted the invitation and joined as planner" in log
    assert "Ravi: planner, no longer limited" in log


def test_master_data_waits_for_a_second_persons_approval_and_the_rest_saves_at_once(clock):
    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    cid = new_company(asha)
    r = client.put(f"/api/companies/{cid}/approval", headers=h(asha), json={"approval": True})
    assert r.status_code == 409 and "second person" in r.json()["detail"]                   # nobody to approve yet
    join(asha, cid, "ravi@k.in", "planner")
    assert client.put(f"/api/companies/{cid}/approval", headers=h(ravi), json={"approval": True}).status_code == 403
    assert client.put(f"/api/companies/{cid}/approval", headers=h(asha), json={"approval": True}).json()["approval"]
    doc = example()
    price0 = doc["products"][0]["price"]
    doc["products"][0]["price"] = price0 + 50                        # master data: held
    doc["demand"][0]["qty"] += 3                                     # an order: saved
    r = client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": doc, "base_revision": 1})
    body = r.json()
    assert r.status_code == 200 and body["saved"] and body["held"]["summary"] == "products: 1 changed"
    assert body["dataset"]["products"][0]["price"] == price0 and body["dataset"]["demand"][0]["qty"] == doc["demand"][0]["qty"]
    assert body["meta"]["pending"] == 1 and "waiting for approval" in body["summary"]
    now = client.get(f"/api/companies/{cid}", headers=h(asha)).json()["dataset"]
    assert now["products"][0]["price"] == price0
    held = client.get(f"/api/companies/{cid}/held", headers=h(asha)).json()
    assert [(x["by"], x["by_me"], x["status"]) for x in held] == [("Ravi", False, "pending")]
    assert [(c["list"], c["record"], c["field"], c["old"], c["new"]) for c in held[0]["changes"]] == [
        ("products", doc["products"][0]["id"], "price", price0, price0 + 50)]
    rid = held[0]["id"]
    # the one who asked cannot approve it; someone else can
    assert client.post(f"/api/companies/{cid}/held/{rid}", headers=h(ravi), json={"decision": "approve"}).status_code == 403
    r = client.post(f"/api/companies/{cid}/held/{rid}", headers=h(asha), json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["dataset"]["products"][0]["price"] == price0 + 50
    assert r.json()["meta"]["pending"] == 0
    top = client.get(f"/api/companies/{cid}/history", headers=h(ravi)).json()[0]
    assert (top["user"], top["action"]) == ("Asha", "approved") and top["summary"].startswith(f"approved Ravi's change #{rid}")
    assert client.post(f"/api/companies/{cid}/held/{rid}", headers=h(asha), json={"decision": "approve"}).status_code == 409
    # a change asked for on a record changed since: refused, and can be rejected
    rev = r.json()["meta"]["revision"]
    doc = r.json()["dataset"]
    doc["products"][1]["price"] = 1
    rid2 = client.put(f"/api/companies/{cid}", headers=h(ravi), json={"dataset": doc, "base_revision": rev}).json()["held"]["id"]
    client.put(f"/api/companies/{cid}/approval", headers=h(asha), json={"approval": False})
    doc["products"][1]["price"] = 2
    rev = client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": doc, "base_revision": rev}).json()["meta"]["revision"]
    r = client.post(f"/api/companies/{cid}/held/{rid2}", headers=h(asha), json={"decision": "approve"})
    assert r.status_code == 409 and f"products {doc['products'][1]['id']}" in r.json()["detail"]
    r = client.post(f"/api/companies/{cid}/held/{rid2}", headers=h(asha), json={"decision": "reject", "note": "price is agreed"})
    assert r.status_code == 200
    assert [(x["status"], x["decided_by"], x["note"]) for x in client.get(
        f"/api/companies/{cid}/held?status=all", headers=h(ravi)).json()] == [
        ("rejected", "Asha", "price is agreed"), ("approved", "Asha", "")]


def test_every_field_changed_is_documented_with_its_old_and_new_value(clock):
    asha = signup("asha@k.in", "Asha")
    cid = new_company(asha)
    doc = example()
    p0 = doc["products"][0]
    old_price = p0["price"]
    p0["price"] = old_price + 1
    _lp(doc, "DC-DELHI", "MG-500")["safety_stock"]["service_level"] = 0.99
    doc["demand"] = doc["demand"][1:]
    client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": doc, "base_revision": 1})
    clock.tick(5)
    p0["price"] = old_price + 2
    client.put(f"/api/companies/{cid}", headers=h(asha), json={"dataset": doc, "base_revision": 2})
    rows = client.get(f"/api/companies/{cid}/changes?q={p0['id']}&list=products", headers=h(asha)).json()
    assert [(x["revision"], x["user"], x["field"], x["old"], x["new"]) for x in rows] == [
        (3, "Asha", "price", old_price + 1, old_price + 2), (2, "Asha", "price", old_price, old_price + 1)]
    rows = client.get(f"/api/companies/{cid}/changes?q=DC-DELHI | MG-500", headers=h(asha)).json()
    assert [(x["list"], x["field"], x["new"]) for x in rows] == [("planning policies", "safety_stock.service_level", 0.99)]
    gone = [x for x in client.get(f"/api/companies/{cid}/changes?list=orders and forecasts", headers=h(asha)).json()]
    assert len(gone) == 1 and gone[0]["field"] == "" and gone[0]["new"] is None and gone[0]["old"]["qty"] > 0


# ---- Phase L: a forgotten password, single sign-on, backups --------------------------------------------------------
def test_a_forgotten_password_is_reset_by_mail_or_by_a_link_an_owner_makes(monkeypatch, clock):
    from scp.companies import mail

    asha, ravi = signup("asha@k.in", "Asha"), signup("ravi@k.in", "Ravi")
    cid = new_company(asha)
    join(asha, cid, "ravi@k.in", "planner")
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mail, "send", lambda *a: sent.append(a))
    # no mail set up: the page says so, and nothing is sent
    assert client.get("/api/auth/config").json()["mail"] is False
    assert client.post("/api/auth/reset/request", json={"email": "ravi@k.in"}).json() == {"ok": True, "mail": False}
    assert sent == []
    monkeypatch.setenv("SCP_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example.com")
    assert client.get("/api/auth/config").json()["mail"] is True
    assert client.post("/api/auth/reset/request", json={"email": "nobody@k.in"}).json()["ok"]    # same answer
    assert client.post("/api/auth/reset/request", json={"email": "ravi@k.in"}).json()["ok"]
    assert [(to, subject) for to, subject, _ in sent] == [("ravi@k.in", "Set a new password")]
    link = next(w for w in sent[0][2].split() if w.startswith("https://plan.example.com/#/account/reset/"))
    token = link.rsplit("/", 1)[1]
    r = client.post("/api/auth/reset", json={"token": token, "password": "a new horse at last"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "ravi@k.in"
    assert client.get("/api/auth/me", headers=h(ravi)).status_code == 401        # signed out everywhere else
    assert client.post("/api/auth/signin", json={"email": "ravi@k.in", "password": "a new horse at last"}).status_code == 200
    assert client.post("/api/auth/reset", json={"token": token, "password": "another one to try"}).status_code == 410
    # an owner asks for a link for a planner: with mail, it goes to the planner's own address (CV-H01) …
    r = client.post(f"/api/companies/{cid}/members/ravi@k.in/reset", headers=h(asha))
    assert r.status_code == 200 and r.json()["mailed"] and r.json()["link"] == ""
    assert sent[-1][0] == "ravi@k.in" and "https://plan.example.com/#/account/reset/" in sent[-1][2]
    mailed = next(w for w in sent[-1][2].split() if "/#/account/reset/" in w)
    # … and on a server without mail the owner is shown it to hand over; not for another owner, and a planner cannot
    monkeypatch.delenv("SCP_SMTP_HOST")
    r = client.post(f"/api/companies/{cid}/members/ravi@k.in/reset", headers=h(asha))
    assert r.status_code == 200 and r.json()["link"].startswith("https://plan.example.com/#/account/reset/")
    assert mailed.startswith("https://plan.example.com/")
    ravi2 = client.post("/api/auth/signin", json={"email": "ravi@k.in", "password": "a new horse at last"}).json()["token"]
    assert client.post(f"/api/companies/{cid}/members/asha@k.in/reset", headers=h(ravi2)).status_code == 403
    join(asha, cid, "ravi@k.in", "owner")
    assert client.post(f"/api/companies/{cid}/members/ravi@k.in/reset", headers=h(asha)).status_code == 403
    tok = r.json()["link"].rsplit("/", 1)[1]
    assert client.post("/api/auth/reset", json={"token": tok, "password": "third horse at last"}).status_code == 200
    assert any("a link to set a new password was made for Ravi" in x["summary"]
               for x in client.get(f"/api/companies/{cid}/history", headers=h(asha)).json())
    # the link lasts a day
    t2 = client.post(f"/api/companies/{cid}/members/asha@k.in/reset", headers=h(asha)).json()["link"].rsplit("/", 1)[1]
    clock.tick(25 * 60)
    assert client.post("/api/auth/reset", json={"token": t2, "password": "too late by a day!"}).status_code == 410


def id_token(sub: str, nonce: str, iss: str = "https://id.example.com", aud: str = "scp") -> str:
    import base64
    import time

    def part(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return ".".join([part({"alg": "RS256"}), part({"iss": iss, "aud": aud, "sub": sub, "nonce": nonce,
                                                   "exp": int(time.time()) + 300}), "sig"])


def test_single_sign_on_signs_in_with_the_company_identity_provider(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from scp.companies import sso

    monkeypatch.setenv("SCP_OIDC_ISSUER", "https://id.example.com")
    monkeypatch.setenv("SCP_OIDC_CLIENT_ID", "scp")
    monkeypatch.setenv("SCP_OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("SCP_OIDC_NAME", "Kaveri account")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example.com")
    monkeypatch.setattr(sso, "_discovery", {})
    seen: dict = {}
    who = {"sub": "42", "email": "meera@k.in", "email_verified": True, "name": "Meera"}
    nonce = {"now": ""}

    def get(url, **kw):
        if url.endswith("/.well-known/openid-configuration"):
            return {"authorization_endpoint": "https://id.example.com/authorize", "token_endpoint": "https://id.example.com/token",
                    "userinfo_endpoint": "https://id.example.com/userinfo"}
        assert kw["headers"]["Authorization"] == "Bearer at-1"
        return dict(who)

    def post(url, data):
        seen.update(data)
        return {"access_token": "at-1", "id_token": id_token(who["sub"], nonce["now"])}

    monkeypatch.setattr(sso, "_get", get)
    monkeypatch.setattr(sso, "_post", post)
    assert client.get("/api/auth/config").json()["sso"] == "Kaveri account"
    r = client.get("/api/auth/sso/start", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    nonce["now"] = q["nonce"][0]
    assert r.headers["location"].startswith("https://id.example.com/authorize?")
    assert q["redirect_uri"] == ["https://plan.example.com/api/auth/sso/callback"] and q["code_challenge_method"] == ["S256"]
    r = client.get(f"/api/auth/sso/callback?code=c-1&state={q['state'][0]}", follow_redirects=False)
    loc = r.headers["location"]
    # roadmap D: the session is in the HttpOnly cookie, never in the address
    assert loc == "https://plan.example.com/#/account/sso", loc
    assert seen["client_secret"] == "s3cret" and seen["code"] == "c-1" and seen["code_verifier"]
    token = r.cookies["scp_session"]
    me = client.get("/api/auth/me", headers=h(token)).json()["user"]
    assert (me["email"], me["name"]) == ("meera@k.in", "Meera")
    # no password on such an account; the state works once; an unverified address is refused
    r = client.post("/api/auth/signin", json={"email": "meera@k.in", "password": "whatever-it-was-1"})
    assert r.status_code == 401 and "single sign-on" in r.json()["detail"]
    r = client.get(f"/api/auth/sso/callback?code=c-1&state={q['state'][0]}", follow_redirects=False)
    assert "/#/account/sso-failed/" in r.headers["location"]
    who["email_verified"] = False
    q2 = parse_qs(urlparse(client.get("/api/auth/sso/start", follow_redirects=False).headers["location"]).query)
    nonce["now"] = q2["nonce"][0]
    r = client.get(f"/api/auth/sso/callback?code=c-2&state={q2['state'][0]}", follow_redirects=False)
    assert "not%20verified" in r.headers["location"]
    # the same person again, by the provider's id: the same account
    who.update(email_verified=True, email="meera.k@k.in")
    q3 = parse_qs(urlparse(client.get("/api/auth/sso/start", follow_redirects=False).headers["location"]).query)
    nonce["now"] = q3["nonce"][0]
    t3 = client.get(f"/api/auth/sso/callback?code=c-3&state={q3['state'][0]}", follow_redirects=False).cookies["scp_session"]
    assert client.get("/api/auth/me", headers=h(t3)).json()["user"]["id"] == me["id"]


def test_a_backup_is_taken_while_the_server_runs_and_put_back(tmp_path):
    from scp import admin
    from scp.backup import backup, check, restore
    from scp.versions.store import Store

    db = tmp_path / "live.sqlite"
    store = Store(db)
    c = company_store.Companies(store)
    s = c.signup("asha@k.in", "Asha", "correct horse")
    meta = c.create(s.user, example())
    for i in range(3):
        backup(store.db, tmp_path / "b", keep=2, now=dt.datetime(2026, 9, 28, 2, i, tzinfo=dt.UTC))
    kept = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert kept == ["scp-20260928-020100.sqlite", "scp-20260928-020200.sqlite"]
    assert check(tmp_path / "b" / kept[-1]) == ["1 accounts", f"{meta.name} (revision 1)"]
    doc = example()
    doc["products"][0]["price"] = 1
    c.save(s.user, meta.id, doc, 1)
    store.db.close()
    before = restore(tmp_path / "b" / kept[-1], db)
    assert before.name == "live.sqlite.before-restore"
    back = company_store.Companies(Store(db))
    assert back.open(back.whoami(s.token), meta.id).meta.revision == 1
    assert admin.main(["check", str(tmp_path / "b" / kept[0])]) == 0
