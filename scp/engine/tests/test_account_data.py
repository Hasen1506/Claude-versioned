"""The account's own data (ENTERPRISE_PLAN 1.4): download everything it holds, and delete it, with the companies it
alone owns handed to another member or deleted (said first, chosen by the holder), and the histories kept
accountable without the person's address or name."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from scp.api.app import app
from scp.companies import get_companies

from .factory import load_example

PW = "kaveri-pumps-chennai-2026"
client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signup(email: str, name: str = "") -> str:
    r = client.post("/api/auth/signup", json={"email": email, "name": name, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def company(token: str, name: str) -> str:
    doc = load_example("kitchenware_network").model_dump(mode="json")
    doc["settings"]["company_name"] = name
    r = client.post("/api/companies", headers=h(token), json={"dataset": doc})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def join(owner: str, cid: str, email: str, role: str) -> None:
    r = client.post(f"/api/companies/{cid}/members", headers=h(owner), json={"email": email, "role": role})
    link = next(m["invite_link"] for m in r.json() if m["email"] == email)
    c = get_companies()
    uid = c.db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
    c.accept_invite(c._user(uid), token=link.rsplit("/", 1)[1])


def test_the_download_holds_every_company_its_history_and_what_the_account_did():
    asha = signup("asha@kaveri.example", "Asha")
    ravi = signup("ravi@kaveri.example", "Ravi")
    pumps = company(asha, "Kaveri Pumps")
    valves = company(ravi, "Ravi Valves")
    join(ravi, valves, "asha@kaveri.example", "viewer")
    company(ravi, "Ravi Private")                         # not hers: not in her download
    assert client.post("/api/auth/account/export", headers=h(asha), json={"password": "wrong-password-1"}).status_code == 403
    r = client.post("/api/auth/account/export", headers=h(asha), json={"password": PW})
    assert r.status_code == 200 and r.headers["content-disposition"].startswith('attachment; filename="scp-account-')
    data = json.loads(r.content)
    assert data["account"]["email"] == "asha@kaveri.example" and data["account"]["name"] == "Asha"
    assert "pw_hash" not in r.text and "totp" not in r.text.replace("two_step", "")
    by = {c["name"]: c for c in data["companies"]}
    assert set(by) == {"Kaveri Pumps", "Ravi Valves"}
    assert by["Kaveri Pumps"]["role"] == "owner" and by["Ravi Valves"]["role"] == "viewer"
    assert by["Kaveri Pumps"]["dataset"]["settings"]["company_name"] == "Kaveri Pumps"
    assert by["Kaveri Pumps"]["id"] == pumps and by["Kaveri Pumps"]["history"][-1]["action"] == "created"
    assert {m["email"] for m in by["Ravi Valves"]["members"]} == {"asha@kaveri.example", "ravi@kaveri.example"}
    assert [a["action"] for a in by["Kaveri Pumps"]["your_actions"]] == ["created"]
    assert by["Ravi Valves"]["your_actions"][0]["summary"].startswith("Asha accepted the invitation")


def test_deleting_says_first_what_happens_and_needs_a_choice_for_each_company_owned_alone():
    asha = signup("asha@kaveri.example", "Asha")
    ravi = signup("ravi@kaveri.example", "Ravi")
    meena = signup("meena@kaveri.example", "Meena")
    handed = company(asha, "Kaveri Pumps")                # alone: handed to Ravi
    gone = company(asha, "Old Trials")                    # alone: deleted
    shared = company(asha, "Shared Works")                # owned with Meena: she leaves
    theirs = company(meena, "Meena Foods")                # a planner there: she leaves
    join(asha, handed, "ravi@kaveri.example", "planner")
    join(asha, shared, "meena@kaveri.example", "owner")
    join(meena, theirs, "asha@kaveri.example", "planner")
    client.post(f"/api/companies/{handed}/members", headers=h(asha), json={"email": "new@kaveri.example", "role": "viewer"})
    plan = client.get("/api/auth/account/delete", headers=h(asha)).json()
    assert [c["name"] for c in plan["alone"]] == ["Kaveri Pumps", "Old Trials"]
    assert plan["alone"][0]["members"] == [{"email": "ravi@kaveri.example", "name": "Ravi", "role": "planner"}]
    assert [c["name"] for c in plan["shared"]] == ["Shared Works"] and [c["name"] for c in plan["member"]] == ["Meena Foods"]
    # nothing happens without a choice for each company she alone owns, or to someone outside the company
    r = client.post("/api/auth/account/delete", headers=h(asha), json={"password": PW, "choices": {handed: "delete"}})
    assert r.status_code == 409 and "Old Trials" in r.json()["detail"] and r.json()["plan"]["alone"]
    # a choice that cannot be done undoes the ones before it: Kaveri Pumps is not deleted when Old Trials fails
    r = client.post("/api/auth/account/delete", headers=h(asha),
                    json={"password": PW, "choices": {handed: "delete", gone: "meena@kaveri.example"}})
    assert r.status_code == 422 and "not a member of Old Trials" in r.json()["detail"]
    assert client.get("/api/auth/me", headers=h(asha)).status_code == 200
    assert client.get(f"/api/companies/{handed}", headers=h(asha)).status_code == 200
    assert "deleted" not in client.get(f"/api/companies/{handed}/history", headers=h(asha)).json()[0]["summary"]
    r = client.post("/api/auth/account/delete", headers=h(asha),
                    json={"password": "wrong-password-1", "choices": {handed: "ravi@kaveri.example", gone: "delete"}})
    assert r.status_code == 403
    r = client.post("/api/auth/account/delete", headers=h(asha),
                    json={"password": PW, "choices": {handed: "ravi@kaveri.example", gone: "delete"}})
    assert r.status_code == 200, r.text
    assert r.json()["done"] == ["Kaveri Pumps handed to Ravi", "Old Trials deleted", "left Shared Works", "left Meena Foods"]
    # signed out, cannot sign in, the address is free again
    assert client.get("/api/auth/me", headers=h(asha)).status_code == 401
    assert client.post("/api/auth/signin", json={"email": "asha@kaveri.example", "password": PW}).status_code == 401
    # Ravi owns Kaveri Pumps now; its history keeps who did what, without her address or name
    pumps = client.get("/api/companies", headers=h(ravi)).json()
    assert pumps[0]["role"] == "owner"
    hist = client.get(f"/api/companies/{handed}/history", headers=h(ravi)).json()
    assert hist[0]["summary"] == "Asha handed the company to Ravi as owner before deleting their account"
    assert hist[-1]["user"] == "Deleted account"
    assert all("asha@" not in json.dumps(x) for x in hist)
    members = client.get(f"/api/companies/{handed}/members", headers=h(ravi)).json()
    assert {m["email"] for m in members} == {"ravi@kaveri.example", "new@kaveri.example"}   # her invitation stands
    assert client.get(f"/api/companies/{gone}", headers=h(ravi)).status_code == 404
    shared_members = client.get(f"/api/companies/{shared}/members", headers=h(meena)).json()
    assert [m["email"] for m in shared_members] == ["meena@kaveri.example"]
    c = get_companies()
    row = c.db.execute("SELECT * FROM users WHERE name = 'Deleted account'").fetchone()
    assert row["email"].endswith("@deleted.invalid") and row["pw_hash"] == "" and row["kind"] == "deleted"
    assert signup("asha@kaveri.example", "Asha again")


def test_an_account_with_two_steps_gives_the_code_to_download_or_delete(monkeypatch):
    from scp.companies import twostep
    step = [twostep.now_step()]
    monkeypatch.setattr(twostep, "now_step", lambda at=None: step[0])
    t = signup("lata@kaveri.example")
    secret = client.post("/api/auth/two-step/begin", headers=h(t), json={"password": PW}).json()["secret"]
    client.post("/api/auth/two-step/enable", headers=h(t), json={"code": twostep.code_at(secret, step[0])})
    r = client.post("/api/auth/account/export", headers=h(t), json={"password": PW})
    assert r.status_code == 401 and r.json()["two_step"] is True
    step[0] += 1
    assert client.post("/api/auth/account/export", headers=h(t),
                       json={"password": PW, "code": twostep.code_at(secret, step[0])}).status_code == 200
    step[0] += 1
    r = client.post("/api/auth/account/delete", headers=h(t), json={"password": PW, "code": twostep.code_at(secret, step[0])})
    assert r.status_code == 200 and r.json()["done"] == []


def test_a_key_cannot_download_or_delete_an_account():
    owner = signup("owner@kaveri.example")
    cid = company(owner, "Kaveri Pumps")
    key = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "ERP"}).json()["token"]
    assert client.post("/api/auth/account/export", headers=h(key), json={"password": PW}).status_code == 403
    assert client.get("/api/auth/account/delete", headers=h(key)).status_code == 403
    assert client.post("/api/auth/account/delete", headers=h(key), json={"password": PW}).status_code == 403
