"""Two-step sign-in (ENTERPRISE_PLAN 1.3): a code from an authenticator app after the password, recovery codes for a
lost phone, required per company by its owner, and the password (and code) asked again before the account's address,
password or second step changes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.companies import get_companies, mail, twostep

from .factory import load_example

PW = "kaveri-pumps-chennai-2026"
client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})


class Steps:
    """The authenticator's clock, moved by hand: each code is good once, so a test takes the next step for the next."""

    def __init__(self) -> None:
        self.step = twostep.now_step()

    def code(self, secret: str, ahead: bool = True) -> str:
        if ahead:
            self.step += 1
        return twostep.code_at(secret, self.step)


@pytest.fixture
def steps(monkeypatch) -> Steps:
    s = Steps()
    monkeypatch.setattr(twostep, "now_step", lambda at=None: s.step)
    return s


def h(token: str, company: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token}", **({"X-Company": company} if company else {})}


def signup(email: str) -> str:
    r = client.post("/api/auth/signup", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def turn_on(token: str, steps: Steps) -> tuple[str, list[str]]:
    key = client.post("/api/auth/two-step/begin", headers=h(token), json={"password": PW})
    assert key.status_code == 200, key.text
    secret = key.json()["secret"]
    r = client.post("/api/auth/two-step/enable", headers=h(token), json={"code": steps.code(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["codes"]


def sign_in(email: str, secret: str, steps: Steps) -> str:
    r = client.post("/api/auth/signin", json={"email": email, "password": PW})
    assert r.status_code == 200 and r.json()["token"] == "", r.text
    s = client.post("/api/auth/signin/second", json={"ticket": r.json()["second_step"], "code": steps.code(secret)})
    assert s.status_code == 200, s.text
    return s.json()["token"]


def test_turning_it_on_then_signing_in_takes_the_apps_code(steps):
    token = signup("asha@kaveri.example")
    other = client.post("/api/auth/signin", json={"email": "asha@kaveri.example", "password": PW}).json()["token"]
    # the password again, before anything changes
    assert client.post("/api/auth/two-step/begin", headers=h(token), json={"password": "wrong-wrong-wrong"}).status_code == 403
    key = client.post("/api/auth/two-step/begin", headers=h(token), json={"password": PW}).json()
    assert key["uri"].startswith("otpauth://totp/SCP%3Aasha%40kaveri.example?secret=") and "period=30" in key["uri"]
    assert key["grouped"].replace(" ", "") == key["secret"] and len(key["secret"]) == 32
    # a key begun is not yet on: signing in still takes the password alone
    assert client.post("/api/auth/signin", json={"email": "asha@kaveri.example", "password": PW}).json()["token"]
    bad = client.post("/api/auth/two-step/enable", headers=h(token), json={"code": "000000"})
    assert bad.status_code == 422 and "phone's clock" in bad.json()["detail"]
    on = client.post("/api/auth/two-step/enable", headers=h(token), json={"code": steps.code(key["secret"])})
    codes = on.json()["codes"]
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 12 and c[4] == c[9] == "-" for c in codes)
    assert client.get("/api/auth/me", headers=h(token)).json()["user"]["two_step"] is True
    assert client.get("/api/auth/two-step", headers=h(token)).json() == {"on": True, "recovery_left": 10, "password": True}
    # turning it on signs the account out everywhere else
    assert client.get("/api/auth/me", headers=h(other)).status_code == 401
    # the password alone gives no session, only a ticket for the second step
    r = client.post("/api/auth/signin", json={"email": "asha@kaveri.example", "password": PW}).json()
    assert r["token"] == "" and r["second_step"] and r["user"]["two_step"]
    assert client.get("/api/auth/me", headers=h(r["second_step"])).status_code == 401
    wrong = client.post("/api/auth/signin/second", json={"ticket": r["second_step"], "code": "123456"})
    assert wrong.status_code == 401 and wrong.json()["two_step"] is True
    code = steps.code(key["secret"])
    ok = client.post("/api/auth/signin/second", json={"ticket": r["second_step"], "code": code})
    assert ok.status_code == 200 and client.get("/api/auth/me", headers=h(ok.json()["token"])).status_code == 200
    # a ticket is used once; a code is used once (the same code on a new ticket is refused)
    assert client.post("/api/auth/signin/second", json={"ticket": r["second_step"], "code": code}).status_code == 401
    again = client.post("/api/auth/signin", json={"email": "asha@kaveri.example", "password": PW}).json()["second_step"]
    assert client.post("/api/auth/signin/second", json={"ticket": again, "code": code}).status_code == 401


def test_a_recovery_code_signs_in_once(steps):
    token = signup("ravi@kaveri.example")
    _, codes = turn_on(token, steps)
    t = client.post("/api/auth/signin", json={"email": "ravi@kaveri.example", "password": PW}).json()["second_step"]
    typed = codes[3].upper().replace("-", " ")             # as read off paper
    assert client.post("/api/auth/signin/second", json={"ticket": t, "code": typed}).status_code == 200
    t = client.post("/api/auth/signin", json={"email": "ravi@kaveri.example", "password": PW}).json()["second_step"]
    assert client.post("/api/auth/signin/second", json={"ticket": t, "code": codes[3]}).status_code == 401
    assert client.get("/api/auth/two-step", headers=h(token)).json()["recovery_left"] == 9


def test_wrong_codes_stop_after_five(steps):
    token = signup("meena@kaveri.example")
    secret, _ = turn_on(token, steps)
    for _ in range(5):
        t = client.post("/api/auth/signin", json={"email": "meena@kaveri.example", "password": PW}).json()["second_step"]
        assert client.post("/api/auth/signin/second", json={"ticket": t, "code": "000000"}).status_code == 401
    t = client.post("/api/auth/signin", json={"email": "meena@kaveri.example", "password": PW}).json()["second_step"]
    r = client.post("/api/auth/signin/second", json={"ticket": t, "code": steps.code(secret)})
    assert r.status_code == 429 and "15 minutes" in r.json()["detail"]


def test_a_ticket_takes_five_tries_at_most(steps):
    token = signup("gopal@kaveri.example")
    secret, _ = turn_on(token, steps)
    t = client.post("/api/auth/signin", json={"email": "gopal@kaveri.example", "password": PW}).json()["second_step"]
    c = get_companies()
    c.db.execute("UPDATE two_step_tickets SET tries = 5")
    r = client.post("/api/auth/signin/second", json={"ticket": t, "code": steps.code(secret)})
    assert r.status_code == 401 and "sign in again" in r.json()["detail"]


def test_an_owner_requires_it_and_a_member_without_it_cannot_open_the_company(steps):
    owner = signup("owner@kaveri.example")
    doc = load_example("kitchenware_network").model_dump(mode="json")
    cid = client.post("/api/companies", headers=h(owner), json={"dataset": doc}).json()["id"]
    planner = signup("planner@kaveri.example")
    c = get_companies()
    invite = client.post(f"/api/companies/{cid}/members", headers=h(owner),
                         json={"email": "planner@kaveri.example", "role": "planner"}).json()
    link = next(m["invite_link"] for m in invite if m["email"] == "planner@kaveri.example")
    uid = c.db.execute("SELECT id FROM users WHERE email = 'planner@kaveri.example'").fetchone()["id"]
    c.accept_invite(c._user(uid), token=link.rsplit("/", 1)[1])
    # the owner turns it on for themselves first, so requiring it does not shut them out
    r = client.put(f"/api/companies/{cid}/two-step", headers=h(owner), json={"required": True})
    assert r.status_code == 409 and "your own account first" in r.json()["detail"]
    secret, _ = turn_on(owner, steps)
    assert client.put(f"/api/companies/{cid}/two-step", headers=h(planner), json={"required": True}).status_code == 403
    r = client.put(f"/api/companies/{cid}/two-step", headers=h(owner), json={"required": True})
    assert r.status_code == 200 and r.json()["two_step"] is True
    hist = client.get(f"/api/companies/{cid}/history", headers=h(owner)).json()
    assert "required of every member; not on yet for planner" in hist[0]["summary"]
    # the planner sees the company in the list, marked, but cannot open it or work in it
    listed = client.get("/api/companies", headers=h(planner)).json()
    assert listed[0]["needs_two_step"] is True and listed[0]["two_step"] is True
    r = client.get(f"/api/companies/{cid}", headers=h(planner))
    assert r.status_code == 403 and r.json()["two_step_required"] is True and "Two-step sign-in" in r.json()["detail"]
    assert client.get(f"/api/companies/{cid}/history", headers=h(planner)).status_code == 403
    # an integration key is not a person: it works on
    key = client.post(f"/api/companies/{cid}/keys", headers=h(owner), json={"name": "ERP", "role": "planner"})
    assert key.status_code == 200, key.text
    assert client.get(f"/api/companies/{cid}", headers=h(key.json()["token"])).status_code == 200
    # with two steps on, the planner opens it
    p_secret, _ = turn_on(planner, steps)
    planner = sign_in("planner@kaveri.example", p_secret, steps)
    assert client.get(f"/api/companies/{cid}", headers=h(planner)).status_code == 200
    assert client.get("/api/companies", headers=h(planner)).json()[0]["needs_two_step"] is False
    # … and cannot turn it off while the company requires it
    r = client.post("/api/auth/two-step/disable", headers=h(planner), json={"password": PW, "code": steps.code(p_secret)})
    assert r.status_code == 409 and "requires two-step sign-in of its members" in r.json()["detail"]
    assert client.put(f"/api/companies/{cid}/two-step", headers=h(owner), json={"required": False}).json()["two_step"] is False
    r = client.post("/api/auth/two-step/disable", headers=h(planner), json={"password": PW, "code": steps.code(p_secret)})
    assert r.status_code == 200
    assert client.post("/api/auth/signin", json={"email": "planner@kaveri.example", "password": PW}).json()["token"]


def test_password_and_address_changes_ask_for_the_password_and_the_code_again(steps, monkeypatch):
    token = signup("lata@kaveri.example")
    secret, _ = turn_on(token, steps)
    elsewhere = sign_in("lata@kaveri.example", secret, steps)
    r = client.post("/api/auth/password", headers=h(token), json={"old": PW, "new": "a-new-long-passphrase-26"})
    assert r.status_code == 401 and r.json()["two_step"] is True
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mail, "send", lambda *a: sent.append(a))
    monkeypatch.setenv("SCP_SMTP_HOST", "smtp.invalid")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.kaveri.example")
    body = {"password": PW, "email": "lata.r@kaveri.example"}
    assert client.post("/api/auth/email", headers=h(token), json=body).status_code == 401          # no code
    assert client.post("/api/auth/email", headers=h(token),
                       json={**body, "password": "not-my-password-x", "code": steps.code(secret)}).status_code == 403
    taken = signup("taken@kaveri.example")
    assert taken and client.post("/api/auth/email", headers=h(token),
                                 json={**body, "email": "taken@kaveri.example", "code": steps.code(secret)}).status_code == 409
    r = client.post("/api/auth/email", headers=h(token), json={**body, "code": steps.code(secret)})
    assert r.status_code == 200 and r.json()["email"] == "lata.r@kaveri.example" and r.json()["verified"] is False
    assert [m[0] for m in sent] == ["lata@kaveri.example", "lata.r@kaveri.example"]
    assert "now signs in as lata.r@kaveri.example" in sent[0][2] and "/#/account/verify/" in sent[1][2]
    # other sessions end; this one goes on; the old address no longer signs in
    assert client.get("/api/auth/me", headers=h(elsewhere)).status_code == 401
    assert client.get("/api/auth/me", headers=h(token)).json()["user"]["email"] == "lata.r@kaveri.example"
    assert client.post("/api/auth/signin", json={"email": "lata@kaveri.example", "password": PW}).status_code == 401
    r = client.post("/api/auth/password", headers=h(token),
                    json={"old": PW, "new": "a-new-long-passphrase-26", "code": steps.code(secret)})
    assert r.status_code == 200, r.text


def test_a_reset_link_alone_does_not_take_an_account_with_two_steps(steps):
    token = signup("venu@kaveri.example")
    secret, _ = turn_on(token, steps)
    link = get_companies().reset_token("venu@kaveri.example")
    r = client.post("/api/auth/reset", json={"token": link, "password": "another-long-passphrase-9"})
    assert r.status_code == 401 and r.json()["two_step"] is True
    # nothing changed: the old password still signs in (with the code), and the link still works with the code
    assert sign_in("venu@kaveri.example", secret, steps)
    r = client.post("/api/auth/reset", json={"token": link, "password": "another-long-passphrase-9",
                                             "code": steps.code(secret)})
    assert r.status_code == 200 and r.json()["token"]


def test_new_recovery_codes_replace_the_old(steps):
    token = signup("isha@kaveri.example")
    secret, old = turn_on(token, steps)
    r = client.post("/api/auth/two-step/recovery", headers=h(token), json={"password": PW, "code": steps.code(secret)})
    new = r.json()["codes"]
    assert len(new) == 10 and not set(new) & set(old)
    t = client.post("/api/auth/signin", json={"email": "isha@kaveri.example", "password": PW}).json()["second_step"]
    assert client.post("/api/auth/signin/second", json={"ticket": t, "code": old[0]}).status_code == 401
    assert client.post("/api/auth/signin/second", json={"ticket": t, "code": new[0]}).status_code == 200


def test_a_browser_gets_its_cookie_only_after_the_second_step(steps):
    token = signup("anu@kaveri.example")
    secret, _ = turn_on(token, steps)
    b = TestClient(app, base_url="https://testserver")
    csrf = b.get("/api/auth/csrf").json()["csrf"]
    head = {"X-SCP-Session": "cookie", "X-CSRF-Token": csrf}
    r = b.post("/api/auth/signin", headers=head, json={"email": "anu@kaveri.example", "password": PW})
    assert r.status_code == 200 and "scp_session" not in b.cookies and r.json()["second_step"]
    s = b.post("/api/auth/signin/second", headers=head, json={"ticket": r.json()["second_step"], "code": steps.code(secret)})
    assert s.status_code == 200 and s.json()["token"] == "" and "scp_session" in b.cookies
    assert b.get("/api/auth/me").json()["user"]["email"] == "anu@kaveri.example"


def test_rfc_6238_test_vectors():
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    for t, want in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (20000000000, "353130")):
        assert twostep.check(secret, want, at=t) == t // 30
    assert twostep.check(secret, "287082", at=59 + 30) == 1          # one step late is still taken
    assert twostep.check(secret, "287082", at=59 + 90) is None       # three steps late is not
    assert twostep.check(secret, "287082", after=1, at=59) is None   # a step used once is not taken again
