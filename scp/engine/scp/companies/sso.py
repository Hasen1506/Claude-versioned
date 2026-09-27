"""Single sign-on with the company's identity provider, by OpenID Connect (Phase L): Microsoft Entra ID, Google
Workspace, Okta, Keycloak and the like. Set up by the server's environment:

* ``SCP_OIDC_ISSUER`` (e.g. ``https://login.microsoftonline.com/<tenant>/v2.0``; none: no single sign-on),
  ``SCP_OIDC_CLIENT_ID``, ``SCP_OIDC_CLIENT_SECRET``, ``SCP_OIDC_NAME`` (the button says "Sign in with <name>"),
  and ``SCP_PUBLIC_URL`` (the redirect URI registered with the provider is ``<SCP_PUBLIC_URL>/api/auth/sso/callback``).

The authorisation-code flow with PKCE: the server sends the browser to the provider, takes the code back, exchanges
it for tokens over its own connection (with the client secret), and asks the provider's user-info endpoint who
signed in. Only a verified e-mail address is accepted. Who may make a new account follows ``SCP_SIGNUP`` as for
passwords.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .store import CompanyError


def configured() -> bool:
    return bool(os.environ.get("SCP_OIDC_ISSUER", "").strip() and os.environ.get("SCP_OIDC_CLIENT_ID", "").strip())


def button() -> str | None:
    return (os.environ.get("SCP_OIDC_NAME", "").strip() or "your company account") if configured() else None


def _get(url: str, **kw: Any) -> dict:
    r = httpx.get(url, timeout=15, **kw)
    r.raise_for_status()
    return r.json()


def _post(url: str, data: dict) -> dict:
    r = httpx.post(url, data=data, timeout=15, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise CompanyError(f"the sign-on service refused the sign-in ({r.status_code}): try again", 401)
    return r.json()


_discovery: dict[str, tuple[float, dict]] = {}


def discovery() -> dict:
    issuer = os.environ["SCP_OIDC_ISSUER"].strip().rstrip("/")
    hit = _discovery.get(issuer)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    doc = _get(f"{issuer}/.well-known/openid-configuration")
    _discovery[issuer] = (time.time(), doc)
    return doc


def begin(redirect_uri: str) -> tuple[str, str, str, str]:
    """The provider's sign-in URL to send the browser to, and the state, PKCE verifier and nonce to keep."""
    state, verifier, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(48), secrets.token_urlsafe(16)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code", "client_id": os.environ["SCP_OIDC_CLIENT_ID"].strip(), "redirect_uri": redirect_uri,
         "scope": os.environ.get("SCP_OIDC_SCOPES", "openid email profile"), "state": state, "nonce": nonce,
         "code_challenge": challenge, "code_challenge_method": "S256"}
    return f"{discovery()['authorization_endpoint']}?{urlencode(q)}", state, verifier, nonce


def finish(code: str, verifier: str, redirect_uri: str) -> tuple[str, str, str]:
    """Exchange the code, and say who signed in: (subject, e-mail, name)."""
    d = discovery()
    tokens = _post(d["token_endpoint"], {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier,
        "client_id": os.environ["SCP_OIDC_CLIENT_ID"].strip(),
        "client_secret": os.environ.get("SCP_OIDC_CLIENT_SECRET", "").strip()})
    if not tokens.get("access_token"):
        raise CompanyError("the sign-on service gave no access", 401)
    info = _get(d["userinfo_endpoint"], headers={"Authorization": f"Bearer {tokens['access_token']}"})
    if info.get("email_verified") is False:
        raise CompanyError("the sign-on service has not verified that e-mail address", 403)
    sub = str(info.get("sub") or "")
    if not sub:
        raise CompanyError("the sign-on service did not say who signed in", 401)
    return f"{os.environ['SCP_OIDC_ISSUER'].strip()}#{sub}", str(info.get("email") or ""), str(info.get("name") or "")
