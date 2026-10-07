"""Regression tests for the security and integrity audit of 2026-10-07 (CV-C01 … CV-L09): each test fails on the code
the audit read (commit 435873f) and passes with the fixes."""
from __future__ import annotations

import base64
import copy
import datetime as dt
import http.server
import json
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.companies import get_companies
from scp.companies import store as company_store

from .factory import load_example

client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})


def signup(email: str, password: str = "correct horse", name: str = "") -> str:
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


def invite(owner: str, cid: str, email: str, role: str, **kw) -> str:
    """Invite ``email``; the invitation's token."""
    r = client.post(f"/api/companies/{cid}/members", headers=h(owner), json={"email": email, "role": role, **kw})
    assert r.status_code == 200, r.text
    return next(m["invite_link"] for m in r.json() if m["email"] == email).rsplit("/", 1)[1]


def join(owner: str, cid: str, member: str, email: str, role: str, **kw) -> None:
    r = client.post("/api/auth/invites/accept", headers=h(member), json={"token": invite(owner, cid, email, role, **kw)})
    assert r.status_code == 200, r.text


def companies_of(token: str) -> list[tuple[str, str]]:
    return [(c["id"], c["role"]) for c in client.get("/api/auth/me", headers=h(token)).json()["companies"]]


def verify(token: str) -> None:
    c = get_companies()
    assert client.post("/api/auth/email/verify", json={"token": c.email_token(c.whoami(token))}).status_code == 200


def lock_is_free() -> bool:
    """Whether another thread could take the store's lock right now."""
    lock = get_companies().lock
    got: list[bool] = []

    def probe() -> None:
        ok = lock.acquire(blocking=False)
        if ok:
            lock.release()
        got.append(ok)
    t = threading.Thread(target=probe)
    t.start()
    t.join()
    return got[0]


# ---- CV-C01: invitations ---------------------------------------------------------------------------------------
def test_c01_registering_an_invited_address_does_not_take_the_invitation():
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    token = invite(owner, cid, "cfo@acme.example", "owner")
    attacker = signup("cfo@acme.example")
    assert companies_of(attacker) == []                                       # no auto-join on sign-up …
    assert client.get(f"/api/companies/{cid}", headers=h(attacker)).status_code == 404
    other = signup("someone@else.example")
    r = client.post("/api/auth/invites/accept", headers=h(other), json={"token": token})
    assert r.status_code == 403                                               # … a link is for its address only
    # an unverified account cannot take an invitation by the company's id either
    r = client.post("/api/auth/invites/accept", headers=h(attacker), json={"company": cid})
    assert r.status_code == 403 and "confirm your e-mail" in r.json()["detail"]
    assert client.get("/api/auth/me", headers=h(attacker)).json()["invites"] == []


def test_c01_an_existing_account_is_invited_never_added_unasked():
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    pre = signup("planner@acme.example")                                      # registered before the owner adds it
    token = invite(owner, cid, "planner@acme.example", "planner")
    assert companies_of(pre) == []
    members = client.get(f"/api/companies/{cid}/members", headers=h(owner)).json()
    assert [(m["email"], m["user_id"]) for m in members if m["email"] == "planner@acme.example"] == [
        ("planner@acme.example", None)]                                     # shown as invited
    assert client.post("/api/auth/invites/accept", headers=h(pre), json={"token": token}).status_code == 200
    assert companies_of(pre) == [(cid, "planner")]
    assert client.post("/api/auth/invites/accept", headers=h(pre), json={"token": token}).status_code == 410  # once


def test_c01_a_verified_account_sees_and_accepts_its_invitations():
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    ravi = signup("ravi@acme.example")
    invite(owner, cid, "ravi@acme.example", "viewer")
    verify(ravi)
    me = client.get("/api/auth/me", headers=h(ravi)).json()
    assert me["user"]["verified"] and [(i["company"], i["role"]) for i in me["invites"]] == [(cid, "viewer")]
    assert client.post("/api/auth/invites/accept", headers=h(ravi), json={"company": cid}).status_code == 200
    assert companies_of(ravi) == [(cid, "viewer")]


def test_c01_an_invitation_expires(monkeypatch):
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    ravi = signup("ravi@acme.example")
    token = invite(owner, cid, "ravi@acme.example", "planner")
    later = company_store._now() + dt.timedelta(days=company_store.INVITE_DAYS + 1)
    monkeypatch.setattr(company_store, "_now", lambda: later)
    assert client.post("/api/auth/invites/accept", headers=h(ravi), json={"token": token}).status_code == 410


# ---- CV-H01: owner-minted resets ---------------------------------------------------------------------------------
def test_h01_an_owner_cannot_mint_a_reset_for_an_account_that_never_joined():
    victim = signup("victim@other.example", "victim-secret-1")
    attacker = signup("mallory@evil.example")
    cid = new_company(attacker)
    invite(attacker, cid, "victim@other.example", "planner")
    r = client.post(f"/api/companies/{cid}/members/victim@other.example/reset", headers=h(attacker))
    assert r.status_code == 404
    assert client.post("/api/auth/signin", json={"email": "victim@other.example",
                                                 "password": "victim-secret-1"}).status_code == 200
    assert client.get("/api/auth/me", headers=h(victim)).status_code == 200


def test_h01_with_mail_the_reset_goes_to_the_member_not_the_owner(monkeypatch):
    from scp.companies import mail
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    ravi = signup("ravi@acme.example")
    join(owner, cid, ravi, "ravi@acme.example", "planner")
    sent: list = []
    monkeypatch.setattr(mail, "send", lambda *a: sent.append(a))
    monkeypatch.setenv("SCP_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example.com")
    r = client.post(f"/api/companies/{cid}/members/ravi@acme.example/reset", headers=h(owner))
    assert r.status_code == 200 and r.json() == {**r.json(), "link": "", "mailed": True}
    assert sent[-1][0] == "ravi@acme.example" and "https://plan.example.com/#/account/reset/" in sent[-1][2]


def test_h01_an_account_owning_a_company_is_never_reset_by_another_owner():
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    ravi = signup("ravi@acme.example")
    join(owner, cid, ravi, "ravi@acme.example", "planner")
    mine = new_company(ravi)
    client.delete(f"/api/companies/{mine}", headers=h(ravi))                  # even a company since deleted
    assert client.post(f"/api/companies/{cid}/members/ravi@acme.example/reset", headers=h(owner)).status_code == 403


# ---- CV-H02 / CV-L09: single sign-on -----------------------------------------------------------------------------
def _id_token(sub: str, nonce: str, aud: str = "scp") -> str:
    def part(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return ".".join([part({"alg": "none"}), part({"iss": "https://idp.example", "aud": aud, "sub": sub, "nonce": nonce,
                                                  "exp": int(time.time()) + 300}), "sig"])


@pytest.fixture
def idp(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from scp.companies import sso
    monkeypatch.setenv("SCP_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("SCP_OIDC_CLIENT_ID", "scp")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example")
    monkeypatch.setattr(sso, "_discovery", {})
    state = {"info": {}, "nonce": "", "aud": "scp", "sub": None}
    monkeypatch.setattr(sso, "discovery", lambda: {"authorization_endpoint": "https://idp.example/auth",
                                                   "token_endpoint": "https://idp.example/token",
                                                   "userinfo_endpoint": "https://idp.example/userinfo"})
    monkeypatch.setattr(sso, "_post", lambda url, data: {
        "access_token": "at", "id_token": _id_token(state["sub"] or state["info"]["sub"], state["nonce"], state["aud"])})
    monkeypatch.setattr(sso, "_get", lambda url, **kw: dict(state["info"]))

    def login(info: dict, begin: str = "", token: str = "", nonce: str | None = None, aud: str = "scp") -> str:
        """Sign on; the redirect's location."""
        state.update(info=info, aud=aud)
        if begin == "link":
            url = client.post("/api/auth/sso/link", headers=h(token)).json()["url"]
        else:
            url = client.get("/api/auth/sso/start", follow_redirects=False).headers["location"]
        q = parse_qs(urlparse(url).query)
        state["nonce"] = q["nonce"][0] if nonce is None else nonce
        return client.get(f"/api/auth/sso/callback?code=c&state={q['state'][0]}",
                          follow_redirects=False).headers["location"]
    return login


def test_h02_sso_without_a_verified_address_is_refused(idp):
    loc = idp({"sub": "s1", "email": "new@acme.example"})                      # no email_verified at all
    assert "/#/account/sso-failed/" in loc and "not%20verified" in loc


def test_h02_sso_never_takes_over_a_password_account_by_e_mail(idp):
    owner = signup("owner@acme.example", "owner-password-1")
    new_company(owner)
    loc = idp({"sub": "attacker", "email": "owner@acme.example", "email_verified": True})
    assert "/#/account/sso-failed/" in loc and "already%20an%20account" in loc
    # the holder links it, signed in; later sign-ons with that subject reach the account; a binding is kept
    loc = idp({"sub": "owner-sub", "email": "owner@acme.example", "email_verified": True}, begin="link", token=owner)
    assert "/#/account/sso/" in loc
    loc = idp({"sub": "owner-sub", "email": "owner@acme.example", "email_verified": True})
    tok = loc.rsplit("/", 1)[1]
    assert client.get("/api/auth/me", headers=h(tok)).json()["user"]["email"] == "owner@acme.example"
    loc = idp({"sub": "other-sub", "email": "owner@acme.example", "email_verified": True}, begin="link", token=tok)
    assert "already%20linked" in loc


def test_h02_a_new_sso_account_is_verified_and_a_wrong_nonce_or_audience_is_refused(idp):
    loc = idp({"sub": "s2", "email": "meera@acme.example", "email_verified": "true"})
    tok = loc.rsplit("/", 1)[1]
    assert client.get("/api/auth/me", headers=h(tok)).json()["user"]["verified"] is True
    assert "nonce" in idp({"sub": "s2", "email": "meera@acme.example", "email_verified": True}, nonce="forged")
    assert "sso-failed" in idp({"sub": "s2", "email": "meera@acme.example", "email_verified": True}, aud="other-app")


def test_h02_a_start_link_cannot_bind_someone_elses_account(idp):
    from urllib.parse import parse_qs, urlparse
    owner = signup("owner@acme.example")
    uid = client.get("/api/auth/me", headers=h(owner)).json()["user"]["id"]
    url = client.get(f"/api/auth/sso/start?next=link:{uid}", follow_redirects=False).headers["location"]
    q = parse_qs(urlparse(url).query)
    assert get_companies().take_state(q["state"][0])[2] == ""


# ---- CV-H03: place limits ----------------------------------------------------------------------------------------
def test_h03_a_decoy_way_to_buy_does_not_widen_a_place_limit():
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    pl = signup("delhi@acme.example")
    join(owner, cid, pl, "delhi@acme.example", "planner", places=["DC-DELHI"])
    doc = client.get(f"/api/companies/{cid}", headers=h(pl)).json()["dataset"]
    d = copy.deepcopy(doc)
    src = copy.deepcopy(d["purchasing_sources"][0])
    src.update(id="PIR-X", location="DC-DELHI", supplier="PLT-PUNE")
    d["purchasing_sources"].append(src)
    for p in d["resources"]:
        if p.get("location") == "PLT-PUNE":
            p["name"] = "renamed by Delhi planner"
    r = client.put(f"/api/companies/{cid}", headers=h(pl), json={"dataset": d, "base_revision": 1})
    assert r.status_code == 403 and "ways to buy PIR-X" in r.json()["detail"]
    # a decoy alone (no other change) is refused too: a plant is not a supplier
    d2 = copy.deepcopy(doc)
    d2["purchasing_sources"].append(src)
    assert client.put(f"/api/companies/{cid}", headers=h(pl), json={"dataset": d2, "base_revision": 1}).status_code == 403
    # an existing place relabelled a customer in the same save widens nothing either
    d3 = copy.deepcopy(doc)
    next(x for x in d3["locations"] if x["id"] == "PLT-PUNE")["type"] = "customer"
    d3["lanes"].append({**copy.deepcopy(d3["lanes"][0]), "id": "LANE-X", "origin": "DC-DELHI", "destination": "PLT-PUNE"})
    assert client.put(f"/api/companies/{cid}", headers=h(pl), json={"dataset": d3, "base_revision": 1}).status_code == 403


# ---- CV-H04: purchase-order release ------------------------------------------------------------------------------
def _po_company():
    from scp.model import Dataset
    from scp.plan import run_mrp
    from scp.purchasing import create_purchase_orders
    ds = Dataset.model_validate(example())
    ds = Dataset.model_validate({**ds.model_dump(mode="json"), "purchasing": {
        **ds.purchasing.model_dump(mode="json"),
        "release_levels": [{"name": "Buyer", "above": 0, "approvers": []},
                           {"name": "CFO", "above": 0, "approvers": ["cfo@acme.example"]}]}})
    new, _ = create_purchase_orders(ds, run_mrp(ds), None, None)
    doc = new.model_dump(mode="json")
    po = next(p for p in doc["purchase_orders"] if not p["approved"])
    return doc, po["id"]


def test_h04_a_save_cannot_forge_a_release():
    doc, pid = _po_company()
    owner = signup("owner@acme.example")
    cid = new_company(owner, doc)
    buyer, cfo = signup("buyer@acme.example"), signup("cfo@acme.example")
    join(owner, cid, buyer, "buyer@acme.example", "planner")
    join(owner, cid, cfo, "cfo@acme.example", "planner")

    def save(tok: str, change) -> object:
        cur = client.get(f"/api/companies/{cid}", headers=h(tok)).json()
        d = copy.deepcopy(cur["dataset"])
        change(next(p for p in d["purchase_orders"] if p["id"] == pid), d)
        return client.put(f"/api/companies/{cid}", headers=h(tok), json={"dataset": d, "base_revision": cur["meta"]["revision"]})
    on = doc["settings"]["planning_start"]
    # forged: someone else's name, a release with no releases, a skipped level, or the strategy loosened in the save
    r = save(buyer, lambda p, d: p.update(approved=True, approvals=[{"level": "Buyer", "by": "x@acme.example", "on": on}]))
    assert r.status_code == 403 and "recorded under the name of who gives it" in r.json()["detail"]
    assert save(buyer, lambda p, d: p.update(approved=True)).status_code == 403
    assert save(buyer, lambda p, d: p.update(approvals=[{"level": "CFO", "by": "buyer@acme.example", "on": on}])
                ).status_code == 403
    r = save(buyer, lambda p, d: (d["purchasing"].update(release_levels=[]), p.update(approved=True)))
    assert r.status_code == 403
    # the real releases, one person per level: through the engine's action, then saved
    for tok in (buyer, cfo):
        cur = client.get(f"/api/companies/{cid}", headers=h(tok)).json()
        a = client.post("/api/purchasing/act", headers=h(tok, cid), json={"dataset": cur["dataset"], "action": "approve",
                                                                          "po": pid})
        assert a.status_code == 200, a.text
        r = client.put(f"/api/companies/{cid}", headers=h(tok), json={"dataset": a.json()["dataset"],
                                                                      "base_revision": cur["meta"]["revision"]})
        assert r.status_code == 200, r.text
    final = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    po = next(p for p in final["purchase_orders"] if p["id"] == pid)
    assert po["approved"] and [a["by"] for a in po["approvals"]] == ["buyer@acme.example", "cfo@acme.example"]


def test_h04_who_released_a_credit_block_comes_from_the_session():
    from scp.sales import act
    from scp.model import Dataset
    ds = Dataset.model_validate(example())
    cust = next(x.id for x in ds.locations if x.type.value == "customer")
    blocked, _ = act(ds, "create_order", customer=cust, lines=[{"product": ds.products[0].id, "qty": 5,
                                                                 "date": str(ds.settings.planning_start)}])
    doc = blocked.model_dump(mode="json")
    so = doc["sales_orders"][-1]
    so.update(credit_block=True, credit_note="over the credit limit")
    owner = signup("owner@acme.example")
    cid = new_company(owner, doc)
    cur = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    d = copy.deepcopy(cur["dataset"])
    next(o for o in d["sales_orders"] if o["id"] == so["id"]).update(credit_block=False,
                                                                       credit_note="Released by cfo@acme.example")
    r = client.put(f"/api/companies/{cid}", headers=h(owner), json={"dataset": d, "base_revision": 1})
    assert r.status_code == 200
    kept = next(o for o in r.json()["dataset"]["sales_orders"] if o["id"] == so["id"])
    assert kept["credit_note"] == "Released by owner@acme.example (was: over the credit limit)"


# ---- CV-H05: the worklist --------------------------------------------------------------------------------------
def test_h05_a_viewer_cannot_rewrite_or_clear_the_worklist():
    owner = signup("owner@acme.example")
    cid = new_company(owner)
    viewer = signup("viewer@acme.example")
    join(owner, cid, viewer, "viewer@acme.example", "viewer")
    live = client.post("/api/tower", headers=h(owner, cid), json=example()).json()["worklist"]
    stripped = example()
    stripped.update(demand=[], receipts=[], location_products=[], history=[])
    r = client.post("/api/tower", headers=h(viewer, cid), json=stripped)
    assert r.status_code == 200 and r.json()["cleared"] == []
    hist = client.get(f"/api/tower/items/{live[0]['id']}/history", headers=h(owner, cid)).json()
    assert [x["action"] for x in hist] == ["opened"]
    # the viewer still sees the worklist as it stands
    seen = client.post("/api/tower", headers=h(viewer, cid), json=example()).json()["worklist"]
    assert {w["id"] for w in seen} == {w["id"] for w in live}


# ---- CV-H06: the browser's own space ------------------------------------------------------------------------------
def test_h06_anonymous_versions_belong_to_the_browser_that_made_them():
    alice = {"X-Browser-Key": "alice-browser-own-random-key"}
    bob = {"X-Browser-Key": "bob-browser-own-random-key-00"}
    v = client.post("/api/versions", headers=alice, json={"dataset": example(), "name": "Alice's base"}).json()
    assert [x["id"] for x in client.get("/api/versions", headers=alice).json()] == [v["id"]]
    assert client.get("/api/versions", headers=bob).json() == []
    assert client.get(f"/api/versions/{v['id']}", headers=bob).status_code == 404
    assert client.post(f"/api/versions/{v['id']}/discard", headers=bob).status_code == 404
    no_key = TestClient(app)
    assert no_key.get("/api/versions").status_code == 400                     # never one shared pool
    assert no_key.post("/api/tower", json=example()).status_code == 200       # stateless planning still works
    signed = signup("solo@acme.example")
    assert no_key.get("/api/versions", headers=h(signed)).json() == []        # a person's own space


# ---- CV-H07: mail -------------------------------------------------------------------------------------------------
def test_h07_reminders_go_to_members_only_and_documents_need_a_verified_sender(monkeypatch):
    from scp.companies import mail
    sent: list = []
    monkeypatch.setenv("SCP_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example.com")
    monkeypatch.setattr(mail, "deliver", sent.append)
    spammer = signup("spammer@evil.example")
    ds = example()
    ds["vendors"][0]["email"] = "ceo@victim-bank.example"
    cid = new_company(spammer, ds)
    body = {"kind": "invoice", "ref": "INV-1", "to": ["ceo@victim-bank.example"], "subject": "Urgent: wire transfer",
            "text": "Please pay", "html": "<h1>Invoice</h1>"}
    r = client.post(f"/api/companies/{cid}/mail", headers=h(spammer), json=body)
    assert r.status_code == 403 and "SCP_MAIL_OPEN_SIGNUP" in r.json()["detail"]
    monkeypatch.setenv("SCP_MAIL_OPEN_SIGNUP", "1")
    r = client.post(f"/api/companies/{cid}/mail", headers=h(spammer), json=body)
    assert r.status_code == 403 and "confirm your own e-mail" in r.json()["detail"]
    verify(spammer)
    monkeypatch.setenv("SCP_MAIL_DAILY_PER_ACCOUNT", "1")
    assert client.post(f"/api/companies/{cid}/mail", headers=h(spammer), json=body).status_code == 200
    assert "Sent by" in sent[-1].get_body(("plain",)).get_content()           # says who sent it, from where
    other = new_company(spammer, ds)                                          # a second company does not reset it
    assert client.post(f"/api/companies/{other}/mail", headers=h(spammer), json=body).status_code == 429
    n = len(sent)
    items = client.post("/api/tower", headers=h(spammer, cid), json=example()).json()["worklist"]
    client.post(f"/api/tower/items/{items[0]['id']}", headers=h(spammer, cid), json={"owner": "stranger@elsewhere.example"})
    r = client.post(f"/api/companies/{cid}/mail/reminders/send", headers=h(spammer))
    assert r.status_code == 200 and "stranger@elsewhere.example" not in [t for x in r.json() for t in x["to"]]
    assert all(m["To"] != "stranger@elsewhere.example" for m in sent[n:])


def test_m03_mail_is_delivered_outside_the_lock(monkeypatch):
    from scp.companies import mail
    seen: list[bool] = []
    monkeypatch.setenv("SCP_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SCP_SIGNUP", "invite")
    monkeypatch.setattr(mail, "deliver", lambda msg: seen.append(lock_is_free()))
    owner = signup("owner@acme.example")
    ds = example()
    ds["vendors"][0]["email"] = "orders@vendor.example"
    cid = new_company(owner, ds)
    verify(owner)
    r = client.post(f"/api/companies/{cid}/mail", headers=h(owner), json={
        "kind": "purchase_order", "ref": "PO-1", "to": ["orders@vendor.example"], "subject": "PO", "text": "x"})
    assert r.status_code == 200 and r.json()["status"] == "sent" and seen == [True]


# ---- CV-H08: the import's address check -----------------------------------------------------------------------------
def test_h08_carrier_grade_nat_and_dns_rebinding_are_refused(monkeypatch):
    from scp.connect import imports
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError):
        imports.reachable("http://100.64.0.1/stock.csv")
    with pytest.raises(ValueError):
        imports.reachable("http://[::ffff:127.0.0.1]/x.csv")

    class S(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"location,product,qty\nINTERNAL,SECRET,42\n")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), S)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = socket.getaddrinfo
    calls = {"n": 0}

    def fake(host, *a, **k):
        if host == "rebind.attacker.example":
            calls["n"] += 1
            ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
        return real(host, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    try:
        with pytest.raises(Exception) as e:
            imports._fetch(f"http://rebind.attacker.example:{port}/x.csv", {})
        assert "SECRET" not in str(e.value)
        # an administrator's allowlist still reaches a host inside the network, on the address it resolved to
        monkeypatch.setenv("SCP_IMPORT_HOSTS", "inside.example")
        monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))] if host == "inside.example" else real(host, *a, **k))
        assert b"SECRET" in imports._fetch(f"http://inside.example:{port}/x.csv", {})
    finally:
        srv.shutdown()


# ---- CV-H09: merge renumbering ---------------------------------------------------------------------------------------
def test_h09_renumbered_order_keeps_its_lines():
    from scp.companies.merge import merge
    line = {"location": "C1", "product": "P", "date": "2026-10-10", "kind": "order", "qty": 5}
    base = {"sales_orders": [{"id": "SO-00001", "customer": "C1"}],
            "demand": [{**line, "id": "SO-00001/10", "order": "SO-00001"}]}
    theirs = {"sales_orders": base["sales_orders"] + [{"id": "SO-00002", "customer": "C2"}],
              "demand": base["demand"] + [{**line, "id": "SO-00002/10", "order": "SO-00002", "location": "C2"}]}
    mine = {"sales_orders": base["sales_orders"] + [{"id": "SO-00002", "customer": "C3"}],
            "demand": base["demand"] + [{**line, "id": "SO-00002/10", "order": "SO-00002", "location": "C3"},
                                        {**line, "id": "SO-00002/20", "order": "SO-00002", "location": "C3"}]}
    out, rep = merge(base, mine, theirs)
    heads = {h["id"]: h["customer"] for h in out["sales_orders"]}
    assert heads == {"SO-00001": "C1", "SO-00002": "C2", "SO-00003": "C3"}
    lines = {d["id"]: (d["order"], d["location"]) for d in out["demand"]}
    assert lines == {"SO-00001/10": ("SO-00001", "C1"), "SO-00002/10": ("SO-00002", "C2"),
                     "SO-00003/10": ("SO-00003", "C3"), "SO-00003/20": ("SO-00003", "C3")}
    assert "SO-00002/10 → SO-00003/10" in rep.renumbered


def test_h09_two_planners_taking_multi_line_orders_end_to_end():
    from scp.model import Dataset, LocationType
    from scp.sales import act
    base = example()
    ds = Dataset.model_validate(base)
    cust = [x.id for x in ds.locations if x.type == LocationType.CUSTOMER]
    p0, p1, day = ds.products[0].id, ds.products[1].id, str(ds.settings.planning_start)
    a, b = signup("asha@x.in"), signup("ravi@x.in")
    cid = new_company(a, base)
    join(a, cid, b, "ravi@x.in", "planner")
    theirs, _ = act(ds, "create_order", customer=cust[0], lines=[{"product": p0, "qty": 5, "date": day}])
    mine, _ = act(ds, "create_order", customer=cust[1], lines=[{"product": p0, "qty": 7, "date": day},
                                                               {"product": p1, "qty": 3, "date": day}])
    T, M = theirs.model_dump(mode="json"), mine.model_dump(mode="json")
    assert client.put(f"/api/companies/{cid}", headers=h(b), json={"dataset": T, "base_revision": 1}).status_code == 200
    r = client.post(f"/api/companies/{cid}/merge", headers=h(a), json={"base": base, "dataset": M, "base_revision": 1})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/companies/{cid}", headers=h(a)).json()["dataset"]
    heads = {x["id"]: x["customer"] for x in got["sales_orders"]}
    for hid in heads:
        assert any(d.get("order") == hid for d in got["demand"]) or not hid.startswith("SO-")
    bad = [d["id"] for d in got["demand"] if d.get("order") in heads and heads[d["order"]] != d["location"]]
    assert bad == []


# ---- CV-H10: links from the Host header -------------------------------------------------------------------------------
def test_h10_no_reset_mail_without_a_public_address_and_the_host_header_is_never_used(monkeypatch):
    from scp.companies import mail
    box: list = []
    monkeypatch.setattr(mail, "send", lambda to, subject, body: box.append(body))
    monkeypatch.setenv("SCP_SMTP_HOST", "smtp.example.com")
    monkeypatch.delenv("SCP_PUBLIC_URL", raising=False)
    signup("victim@acme.example")
    r = client.post("/api/auth/reset/request", json={"email": "victim@acme.example"}, headers={"Host": "attacker.example"})
    assert r.json() == {"ok": True, "mail": False} and box == []
    assert client.get("/api/auth/config").json()["mail"] is False
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example.com")
    client.post("/api/auth/reset/request", json={"email": "victim@acme.example"},
                headers={"Host": "attacker.example", "X-Forwarded-Host": "attacker.example"})
    assert "https://plan.example.com/#/account/reset/" in box[-1] and "attacker" not in box[-1]


def test_h10_single_sign_on_needs_the_public_address(monkeypatch):
    monkeypatch.setenv("SCP_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("SCP_OIDC_CLIENT_ID", "scp")
    monkeypatch.delenv("SCP_PUBLIC_URL", raising=False)
    assert client.get("/api/auth/config").json()["sso"] is None
    assert client.get("/api/auth/sso/start", follow_redirects=False).status_code == 503


# ---- CV-H11 / CV-M05: sign-in under load --------------------------------------------------------------------------
def test_h11_passwords_are_hashed_outside_the_lock(monkeypatch):
    seen: list[bool] = []
    real = company_store._hash_pw
    monkeypatch.setattr(company_store, "_hash_pw", lambda pw, salt: (seen.append(lock_is_free()), real(pw, salt))[1])
    signup("asha@acme.example")
    client.post("/api/auth/signin", json={"email": "asha@acme.example", "password": "correct horse"})
    client.post("/api/auth/signin", json={"email": "asha@acme.example", "password": "wrong horse"})
    assert seen and all(seen)


def test_h11_sign_ins_are_limited_per_address(monkeypatch):
    monkeypatch.setenv("SCP_AUTH_RATE", "5")
    codes = [client.post("/api/auth/signin", json={"email": f"n{i}@x.example", "password": "x" * 8}).status_code
             for i in range(8)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429] * 3


def test_m05_the_failure_counter_keeps_only_failures_and_stays_bounded(monkeypatch):
    c = get_companies()
    signup("asha@acme.example")
    client.post("/api/auth/signin", json={"email": "asha@acme.example", "password": "correct horse"})
    assert "asha@acme.example" not in c.failures                                # a good sign-in leaves nothing
    monkeypatch.setattr(company_store, "FAILURE_KEYS", 5)
    for i in range(12):
        client.post("/api/auth/signin", json={"email": f"n{i}@x.example", "password": "x" * 8})
    assert len(c.failures) <= 5


# ---- CV-M01: scheduled imports ----------------------------------------------------------------------------------------
def test_m01_one_malformed_file_stops_no_other_import():
    from scp.connect import imports
    o = signup("owner@acme.example")
    c = get_companies()
    user = c.whoami(o)
    cid = new_company(o)
    served = {"https://a.example/bad.json": b'"just a string"', "https://b.example/good.json": b'{"records": []}'}
    fetched: list[str] = []
    real = imports.fetch
    imports.fetch = lambda url, headers: (fetched.append(url), served[url])[1]
    try:
        now = dt.datetime(2026, 10, 7, 5, 0, tzinfo=dt.UTC)
        for name, url in (("bad", "https://a.example/bad.json"), ("good", "https://b.example/good.json")):
            imports.save_job(c, user, cid, imports.JobInput(name=name, kind="records:products", source_type="url",
                                                            source=url, format="json", every="hour", at="06:00"), now=now)
        later = now + dt.timedelta(hours=2)
        for tick in range(3):
            imports.run_due(c, later + dt.timedelta(seconds=30 * tick))
        jobs = {j.name: j for j in imports.jobs(c, user, cid).jobs}
    finally:
        imports.fetch = real
    assert fetched.count("https://a.example/bad.json") == 1 and "https://b.example/good.json" in fetched
    assert jobs["bad"].last_status == "failed" and "not a list of records" in (jobs["bad"].last_summary or "")


# ---- CV-M02 / CV-L01: lot sizes -------------------------------------------------------------------------------------
def test_m02_a_split_keeps_every_lot_within_the_maximum_and_on_the_rounding():
    from scp.plan.lotsize import apply_modifiers
    assert apply_modifiers(170, mins=[100], roundings=[None], maxes=[80]) == [80, 80, 10]
    assert apply_modifiers(170, mins=[], roundings=[30], maxes=[100]) == [90, 90]
    assert apply_modifiers(250, mins=[60], roundings=[None], maxes=[100]) == [100, 100, 60]
    assert apply_modifiers(50, mins=[], roundings=[10], maxes=[100]) == [50]
    for need in range(1, 400, 7):
        lots = apply_modifiers(need, mins=[20], roundings=[25], maxes=[110])
        assert all(x <= 110 and x % 25 == 0 for x in lots) and sum(lots) >= need


def test_l01_a_fixed_lot_without_its_quantity_is_an_error_not_an_assert():
    from scp.model import LotSizePolicy, LotSizing
    from scp.plan.lotsize import base_lot
    ls = LotSizing.model_construct(policy=LotSizePolicy.FIXED, fixed_qty=None)
    with pytest.raises(ValueError):
        base_lot(ls, 10)


# ---- CV-M04: anonymous work ---------------------------------------------------------------------------------------
def test_m04_anonymous_planning_calls_are_limited_per_address_and_in_size(monkeypatch):
    anon = TestClient(app)
    monkeypatch.setenv("SCP_ANON_RATE", "3")
    codes = [anon.post("/api/validate", json={}).status_code for _ in range(5)]
    assert codes[-1] == 429 and 429 not in codes[:3]
    tok = signup("signed@acme.example")
    assert anon.post("/api/validate", headers=h(tok), json={}).status_code != 429   # a session is not limited
    monkeypatch.setenv("SCP_ANON_RATE", "0")
    monkeypatch.setenv("SCP_ANON_MAX_MB", "1")
    r = anon.post("/api/validate", content=b"{" + b" " * (2 * 1024 * 1024) + b"}",
                  headers={"content-type": "application/json"})
    assert r.status_code == 413


# ---- CV-M06: backups -------------------------------------------------------------------------------------------------
def test_m06_backup_and_restore_refuse_on_postgres(monkeypatch, capsys):
    from scp import admin
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example/scp")
    assert admin.main(["restore", "/tmp/nothing.sqlite"]) == 2
    assert "PostgreSQL" in capsys.readouterr().err


# ---- CV-L06: sessions ------------------------------------------------------------------------------------------------
def test_l06_a_session_ends_after_its_absolute_lifetime(monkeypatch):
    t = signup("asha@acme.example")
    start = company_store._now()
    for days in range(0, company_store.SESSION_MAX_DAYS, 20):                 # used every 20 days
        monkeypatch.setattr(company_store, "_now", lambda d=days: start + dt.timedelta(days=d))
        assert client.get("/api/auth/me", headers=h(t)).status_code == 200
    monkeypatch.setattr(company_store, "_now", lambda: start + dt.timedelta(days=company_store.SESSION_MAX_DAYS + 1))
    assert client.get("/api/auth/me", headers=h(t)).status_code == 401


# ---- CV-L03: the API pages -------------------------------------------------------------------------------------------
def test_l03_api_pages_are_off_when_sign_in_is_required(monkeypatch):
    from scp.api import app as app_module
    monkeypatch.setenv("SCP_REQUIRE_SIGNIN", "1")
    monkeypatch.delenv("SCP_DOCS", raising=False)
    assert app_module._docs_on() is False
    monkeypatch.setenv("SCP_DOCS", "1")
    assert app_module._docs_on() is True
