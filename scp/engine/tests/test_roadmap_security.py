"""Roadmap D: security (UX audit of 7 Oct 2026, section 4).

Password policy on sign-up, reset and change; HttpOnly + Secure + SameSite cookie sessions for the web client with a
double-submit CSRF token; a one-time swap of a token a browser kept in its storage; single sign-on into the cookie;
and a cost-weighted per-address limit on heavy anonymous calls (off with SCP_ANON_RATE=0).
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from scp.api import companies as api_companies
from scp.api.app import app
from scp.companies import get_companies

from .factory import load_example

COOKIE = {"X-SCP-Session": "cookie"}
STRONG = "kaveri-pumps-chennai-2026"


def browser(https: bool = True) -> TestClient:
    """A browser-like client: keeps cookies (only over https when they are Secure)."""
    return TestClient(app, base_url="https://testserver" if https else "http://testserver")


def plain() -> TestClient:
    return TestClient(app)


def set_cookies(r) -> dict[str, str]:
    """name → the whole Set-Cookie header of that cookie."""
    out = {}
    for v in r.headers.get_list("set-cookie"):
        out[v.split("=", 1)[0]] = v
    return out


def example() -> dict:
    return load_example("kitchenware_network").model_dump(mode="json")


# ---- password policy --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("pw, why", [
    ("short-pw1", "at least 12"),                  # 9 characters: main took 8+
    ("password1234", "breached"),                  # on the list
    ("Password123!", "breached"),                  # the list's word with digits/punctuation around it
    ("aaaaaaaaaaaaaa", "repeats"),
    ("asha.kumar-2026-pw", "e-mail"),              # contains the address's name
])
def test_signup_refuses_weak_passwords(pw, why):
    r = plain().post("/api/auth/signup", json={"email": "asha.kumar@kaveri.in", "password": pw})
    assert r.status_code == 422 and why in r.json()["detail"], r.text


def test_reset_and_change_follow_the_policy():
    c = plain()
    tok = c.post("/api/auth/signup", json={"email": "ravi@kaveri.in", "password": STRONG}).json()["token"]
    r = c.post("/api/auth/password", headers={"Authorization": f"Bearer {tok}"},
               json={"old": STRONG, "new": "12345678"})
    assert r.status_code == 422 and "at least 12" in r.json()["detail"]
    reset = get_companies().reset_token("ravi@kaveri.in")
    r = c.post("/api/auth/reset", json={"token": reset, "password": "qwerty123456"})
    assert r.status_code == 422 and "breached" in r.json()["detail"]
    # the link is still good for a strong password, and the policy is told to the forms
    assert c.post("/api/auth/reset", json={"token": reset, "password": "a-much-better-one-77"}).status_code == 200
    assert c.get("/api/auth/config").json()["password_min"] == 12


# ---- cookie sessions + CSRF ---------------------------------------------------------------------------------------
def test_browser_sign_in_sets_an_httponly_secure_samesite_cookie_and_csrf():
    b = browser()
    r = b.post("/api/auth/signup", headers=COOKIE, json={"email": "meena@kaveri.in", "password": STRONG})
    assert r.status_code == 200, r.text
    ck = set_cookies(r)
    sess, csrf = ck["scp_session"].lower(), ck["scp_csrf"].lower()
    assert "httponly" in sess and "secure" in sess and "samesite=lax" in sess and "path=/" in sess
    assert "httponly" not in csrf and "secure" in csrf
    assert r.json()["csrf"] and r.json()["csrf"] in ck["scp_csrf"]
    # the cookie alone signs in (no Authorization header)
    assert b.get("/api/auth/me").json()["user"]["email"] == "meena@kaveri.in"
    # a change with the cookie but no CSRF token is refused; with it, it goes through
    r = b.post("/api/companies", json={"dataset": example()})
    assert r.status_code == 403 and "X-CSRF-Token" in r.json()["detail"]
    r = b.post("/api/companies", headers={"X-CSRF-Token": "forged"}, json={"dataset": example()})
    assert r.status_code == 403
    r = b.post("/api/companies", headers={"X-CSRF-Token": b.cookies["scp_csrf"]}, json={"dataset": example()})
    assert r.status_code == 200, r.text
    # sign-out ends the session and clears both cookies
    kept = b.cookies["scp_session"]
    r = b.post("/api/auth/signout", headers={"X-CSRF-Token": b.cookies["scp_csrf"]})
    assert r.status_code == 200
    assert all("max-age=0" in v.lower() for v in set_cookies(r).values()) and len(set_cookies(r)) == 2
    assert plain().get("/api/auth/me", headers={"Authorization": f"Bearer {kept}"}).status_code == 401


def test_without_asking_for_a_cookie_nothing_changes_for_scripts():
    c = plain()
    r = c.post("/api/auth/signup", json={"email": "bot@kaveri.in", "password": STRONG})
    assert "scp_session" not in set_cookies(r) and r.json()["token"] and r.json()["csrf"] is None
    tok = r.json()["token"]
    # Bearer needs no CSRF token
    assert c.post("/api/companies", headers={"Authorization": f"Bearer {tok}"},
                  json={"dataset": example()}).status_code == 200


def test_cookie_is_not_secure_on_plain_http_unless_forced(monkeypatch):
    r = browser(https=False).post("/api/auth/signup", headers=COOKIE,
                                  json={"email": "lan@kaveri.in", "password": STRONG})
    assert "secure" not in set_cookies(r)["scp_session"].lower()
    monkeypatch.setenv("SCP_COOKIE_SECURE", "1")
    r = browser(https=False).post("/api/auth/signin", headers=COOKIE,
                                  json={"email": "lan@kaveri.in", "password": STRONG})
    assert "secure" in set_cookies(r)["scp_session"].lower()
    # behind a TLS proxy
    monkeypatch.delenv("SCP_COOKIE_SECURE")
    r = browser(https=False).post("/api/auth/signin", headers={**COOKIE, "X-Forwarded-Proto": "https"},
                                  json={"email": "lan@kaveri.in", "password": STRONG})
    assert "secure" in set_cookies(r)["scp_session"].lower()


def test_cross_site_pages_client_gets_samesite_none():
    r = browser().post("/api/auth/signup", headers={**COOKIE, "Origin": "https://hasen1506.github.io"},
                       json={"email": "pages@kaveri.in", "password": STRONG})
    sess = set_cookies(r)["scp_session"].lower()
    assert "samesite=none" in sess and "secure" in sess
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_csrf_endpoint_hands_out_the_cookie_value():
    b = browser()
    b.post("/api/auth/signup", headers=COOKIE, json={"email": "x@kaveri.in", "password": STRONG})
    assert b.get("/api/auth/csrf").json()["csrf"] == b.cookies["scp_csrf"]
    fresh = browser()
    tok = fresh.get("/api/auth/csrf").json()["csrf"]
    assert tok and fresh.cookies["scp_csrf"] == tok


# ---- adopt: a token kept in the browser's storage becomes a cookie, once -------------------------------------------
def test_a_stored_token_is_swapped_for_a_cookie_once_and_stops_working():
    old = plain().post("/api/auth/signup", json={"email": "old@kaveri.in", "password": STRONG}).json()["token"]
    b = browser()
    r = b.post("/api/auth/adopt", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 200, r.text
    assert r.json()["token"] == "" and r.json()["csrf"] == b.cookies["scp_csrf"]
    assert "httponly" in set_cookies(r)["scp_session"].lower()
    assert b.get("/api/auth/me").json()["user"]["email"] == "old@kaveri.in"
    # the old token is dead: neither usable nor adoptable again
    assert plain().get("/api/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert browser().post("/api/auth/adopt", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_adopt_refuses_integration_keys_and_nothing():
    assert browser().post("/api/auth/adopt").status_code == 400
    assert browser().post("/api/auth/adopt", headers={"Authorization": "Bearer scpk_abc"}).status_code == 400


def test_adopt_keeps_the_absolute_lifetime(monkeypatch):
    from scp.companies import store as s
    old = plain().post("/api/auth/signup", json={"email": "life@kaveri.in", "password": STRONG}).json()["token"]
    c = get_companies()
    before = c.db.execute("SELECT created_at FROM sessions").fetchone()[0]
    b = browser()
    b.post("/api/auth/adopt", headers={"Authorization": f"Bearer {old}"})
    new_hash = s._token_hash(b.cookies["scp_session"])
    assert c.db.execute("SELECT created_at FROM sessions WHERE token_hash = ?", (new_hash,)).fetchone()[0] == before


# ---- single sign-on lands in the cookie ----------------------------------------------------------------------------
@pytest.fixture
def idp(monkeypatch):
    from scp.companies import sso

    from .test_audit_fixes import _id_token
    monkeypatch.setenv("SCP_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("SCP_OIDC_CLIENT_ID", "scp")
    monkeypatch.setenv("SCP_PUBLIC_URL", "https://plan.example")
    monkeypatch.setattr(sso, "_discovery", {})
    st = {"nonce": ""}
    monkeypatch.setattr(sso, "discovery", lambda: {"authorization_endpoint": "https://idp.example/auth",
                                                   "token_endpoint": "https://idp.example/token",
                                                   "userinfo_endpoint": "https://idp.example/userinfo"})
    monkeypatch.setattr(sso, "_post", lambda url, data: {"access_token": "at", "id_token": _id_token("s-9", st["nonce"], "scp")})
    monkeypatch.setattr(sso, "_get", lambda url, **kw: {"sub": "s-9", "email": "sso@kaveri.in", "email_verified": True})
    return st


def test_sso_callback_sets_the_cookie_and_keeps_the_token_out_of_the_address(idp):
    b = browser()
    q = parse_qs(urlparse(b.get("/api/auth/sso/start", follow_redirects=False).headers["location"]).query)
    idp["nonce"] = q["nonce"][0]
    r = b.get(f"/api/auth/sso/callback?code=c&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://plan.example/#/account/sso"
    sess = set_cookies(r)["scp_session"].lower()
    assert "httponly" in sess and "secure" in sess and "samesite=lax" in sess
    assert b.get("/api/auth/me").json()["user"]["email"] == "sso@kaveri.in"


# ---- cost-weighted anonymous limit ---------------------------------------------------------------------------------
@pytest.fixture
def fresh_buckets():
    api_companies._BUCKETS.clear()
    yield
    api_companies._BUCKETS.clear()


def test_heavy_anonymous_calls_cost_more_and_say_when_to_retry(monkeypatch, fresh_buckets):
    monkeypatch.setenv("SCP_ANON_RATE", "60")
    anon = plain()
    codes = [anon.post("/api/plan", json={}).status_code for _ in range(4)]     # 20 units each out of 60
    assert codes[:3] != [429] * 3 and 429 not in codes[:3] and codes[3] == 429, codes
    r = anon.post("/api/plan", json={})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "seconds" in r.json()["detail"]


def test_cheap_calls_are_not_charged_like_a_plan(monkeypatch, fresh_buckets):
    monkeypatch.setenv("SCP_ANON_RATE", "60")
    anon = plain()
    codes = [anon.post("/api/validate", json={}).status_code for _ in range(10)]
    assert 429 not in codes          # main counted calls, not cost: the same 60 would allow ten plans too


def test_bucket_refills_over_time():
    api_companies._BUCKETS.clear()
    assert api_companies.anon_take("k", 20, 60, now=0.0) == 0
    assert api_companies.anon_take("k", 20, 60, now=0.0) == 0
    assert api_companies.anon_take("k", 20, 60, now=0.0) == 0
    assert api_companies.anon_take("k", 20, 60, now=0.0) == pytest.approx(20.0)
    assert api_companies.anon_take("k", 20, 60, now=20.0) == 0         # 1 unit a second at 60/min
    assert api_companies.anon_take("x", 500, 60, now=0.0) == 0          # never more than a full bucket
    api_companies._BUCKETS.clear()


def test_limit_is_off_with_zero(monkeypatch, fresh_buckets):
    monkeypatch.setenv("SCP_ANON_RATE", "0")
    anon = plain()
    assert 429 not in [anon.post("/api/plan", json={}).status_code for _ in range(8)]


def test_a_made_up_token_does_not_escape_the_anonymous_limit(monkeypatch, fresh_buckets):
    monkeypatch.setenv("SCP_ANON_RATE", "3")
    anon = plain()
    codes = [anon.post("/api/validate", headers={"Authorization": "Bearer made-up"}, json={}).status_code
             for _ in range(5)]
    assert codes[-1] == 429, codes                  # main let any Authorization header through unlimited
