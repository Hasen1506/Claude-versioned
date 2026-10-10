"""Sign-in and companies kept on the server (Phase I).

A request says who is asking with ``Authorization: Bearer <token>`` and which company it works in with
``X-Company: <id>``. Planning calls stay stateless (the dataset travels with each request); what is stored, the
company's document, its plan versions and its worklist, belongs to the company and needs a member.

Server settings (environment):

* ``SCP_SIGNUP``: ``open`` (anyone can make an account, the default), ``invite`` (only an e-mail a company owner
  invited, and the very first account) or ``closed`` (only the very first account).
* ``SCP_REQUIRE_SIGNIN=1``: every API call except health and signing in needs a session, and plan versions and the
  worklist need an open company (nothing is kept outside a company).
* ``SCP_PUBLIC_URL``: where people open the application. Links that leave the server (a reset or invitation mailed,
  the single sign-on redirect) are made only from it, never from the request's Host header (CV-H10).
* ``SCP_AUTH_RATE``: sign-ins, sign-ups and resets a minute per client address (default 30; 0: no limit, CV-H11).
* ``SCP_ANON_RATE``: the work a minute per client address without a session, in cost units (default 120; 0: no
  limit). A cheap call costs 1, a heavy one more (a plan 20, a schedule 30, a comparison 40, a what-if 80: ``ANON_COSTS``), from
  one token bucket per address; a refusal says when to come back (``Retry-After``). Roadmap D.
  ``SCP_ANON_MAX_MB``: the largest request body without a session (default 64), and ``SCP_ANON_CONCURRENCY``: how
  many of them run at once (default half the CPUs; the rest wait up to ``SCP_ANON_WAIT_S``, 60 s), against
  CPU-heavy anonymous use (CV-M04). A public server should still set ``SCP_REQUIRE_SIGNIN=1``.

**Browser sessions (roadmap D).** The web client asks for its session in a cookie (``X-SCP-Session: cookie`` on the
sign-in, sign-up, reset and adopt calls; the single sign-on callback always does) and is answered without the token
(it lives in the cookie only), and must send the double-submit token already on sign-in (login CSRF; from
``GET /api/auth/csrf``), which is renewed when the session starts: ``scp_session`` is HttpOnly,
``SameSite=Lax`` (``None`` for the cross-site Pages client) and ``Secure`` whenever the server is reached over HTTPS
(``SCP_COOKIE_SECURE=1``/``0`` forces it). A request that signs in with that cookie and changes something must carry
the double-submit token: header ``X-CSRF-Token`` equal to the ``scp_csrf`` cookie (also handed out in the sign-in
answer and by ``GET /api/auth/csrf``). ``Authorization: Bearer`` still works for integration keys and scripts and
needs no CSRF token (a browser never adds it by itself). A token a browser kept in its storage before this change is
swapped for a cookie once (``POST /api/auth/adopt``), and stops working.

Without a company, the "browser's own" plan versions and worklist belong to the browser that made them: the client
sends a random key it keeps (``X-Browser-Key``), and they are kept under a hash of it (CV-H06); a signed-in person
without an open company works in their own space.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import os
import secrets
import time
from collections import OrderedDict
from threading import BoundedSemaphore, Lock
from typing import Annotated, Any, Literal

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..companies import (
    CAN_EDIT, CompanyDoc, CompanyError, CompanyMeta, FieldChangeRow, HeldChange, LogRow, Member, MergeResult,
    SaveReport, Session, User, get_companies,
)
from ..companies.store import PendingInvite
from ..companies import mail, sso
from ..companies.store import KEY_PREFIX
from ..model.common import Out
from .working import asker, send_raw, takes_gzip, takes_rows

router = APIRouter(prefix="/api", tags=["companies"])

OPEN_PATHS = ("/api/health", "/api/metrics", "/api/auth/config", "/api/auth/signin", "/api/auth/signup", "/api/auth/reset",
              "/api/auth/reset/request", "/api/auth/sso/start", "/api/auth/sso/callback", "/api/auth/email/verify",
              "/api/auth/csrf", "/api/auth/adopt")
# calls that never act on the session cookie, so they need no CSRF token (sign-in itself, and swapping a token)
NO_CSRF = ("/api/auth/signin", "/api/auth/signup", "/api/auth/reset", "/api/auth/reset/request", "/api/auth/adopt",
           "/api/auth/email/verify")
# the sign-in calls that set the session cookie when a browser asks for it: that browser must prove it is this
# application's own page (the double-submit token of ``GET /api/auth/csrf``), so a forged form cannot sign it into
# someone else's account (login CSRF)
COOKIE_SIGNIN = ("/api/auth/signin", "/api/auth/signup", "/api/auth/reset")
SESSION_COOKIE, CSRF_COOKIE, CSRF_HEADER = "scp_session", "scp_csrf", "x-csrf-token"
# the cost in units of one anonymous call (roadmap D): what is not listed costs 1
ANON_COSTS: dict[str, int] = {
    "/api/plan": 20, "/api/plan/trace": 10, "/api/schedule": 30, "/api/schedule/compare": 40, "/api/sop": 20,
    "/api/forecast": 10, "/api/inventory": 10, "/api/finance": 10, "/api/capacity/level": 10, "/api/compare": 40,
    "/api/promise": 5, "/api/promise/bop": 5, "/api/promise/check": 5, "/api/tower": 10, "/api/actuals": 5,
    "/api/purchasing": 5, "/api/sales": 5, "/api/network": 2, "/api/validate": 1,
    "/api/whatif": 80,                       # roadmap E: up to four full plans in one call
    "/api/tower/fix": 30,                    # two plans and their exceptions
}
RATED_PATHS = ("/api/auth/signin", "/api/auth/signup", "/api/auth/reset", "/api/auth/reset/request",
               "/api/auth/email/verify", "/api/auth/email/request")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# planning calls without a session that may run at once (CV-M04)
_ANON_SLOTS = BoundedSemaphore(max(1, _int_env("SCP_ANON_CONCURRENCY", max(1, (os.cpu_count() or 2) // 2))))


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def signup_policy() -> str:
    p = os.environ.get("SCP_SIGNUP", "open").strip().lower()
    if p not in ("open", "invite", "closed"):
        raise CompanyError("SCP_SIGNUP must be open, invite, or closed", 503)
    return p


def production_guard() -> None:
    """With ``SCP_ENV=production`` the server does not start open to anyone: anyone may make an account
    (``SCP_SIGNUP=open``) and no call needs a session (no ``SCP_REQUIRE_SIGNIN``) is refused, unless
    ``SCP_OPEN_ON_PURPOSE=1`` says it is meant (a public demonstration). ENTERPRISE_PLAN 1.5."""
    if os.environ.get("SCP_ENV", "").strip().lower() != "production":
        return
    on_purpose = os.environ.get("SCP_OPEN_ON_PURPOSE", "").strip().lower() in ("1", "true", "yes", "on")
    if signup_policy() == "open" and not require_signin() and not on_purpose:
        raise RuntimeError(
            "SCP_ENV=production with open sign-up and no sign-in: anyone could make an account and use the server "
            "without one. Set SCP_REQUIRE_SIGNIN=1 and SCP_SIGNUP=invite (or closed); for a public demonstration "
            "set SCP_OPEN_ON_PURPOSE=1.")


def require_signin() -> bool:
    value = os.environ.get("SCP_REQUIRE_SIGNIN", "").strip().lower()
    if value not in ("", "0", "false", "no", "off", "1", "true", "yes", "on"):
        raise CompanyError("SCP_REQUIRE_SIGNIN must be a boolean (1/0, true/false, yes/no, on/off)", 503)
    return value in ("1", "true", "yes", "on")


def bearer_of(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() or None if h.lower().startswith("bearer ") else None


def token_of(request: Request) -> str | None:
    """The session or key this request signs in with: ``Authorization: Bearer``, else the browser's session cookie."""
    return bearer_of(request) or request.cookies.get(SESSION_COOKIE) or None


def via_cookie(request: Request) -> bool:
    return not bearer_of(request) and bool(request.cookies.get(SESSION_COOKIE))


def wants_cookie(request: Request) -> bool:
    return request.headers.get("x-scp-session", "").strip().lower() == "cookie"


def _cross_site(request: Request) -> bool:
    """A call from the client served elsewhere (the GitHub Pages build talking to this server)."""
    origin = request.headers.get("origin", "")
    return bool(origin) and origin.rstrip("/") != str(request.base_url).rstrip("/") and origin in CORS_ORIGINS


CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173", "https://hasen1506.github.io")


def cookie_secure(request: Request) -> bool:
    forced = os.environ.get("SCP_COOKIE_SECURE", "").strip().lower()
    if forced:
        return forced not in ("0", "false", "no", "off")
    return (request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
            or mail.public_url().startswith("https://"))


def set_session_cookies(response: Response, request: Request, token: str, csrf: str | None = None) -> str:
    """Put a session in the browser's HttpOnly cookie, with its double-submit token; returns the token."""
    from ..companies.store import SESSION_MAX_DAYS
    csrf = csrf or request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
    cross = _cross_site(request)
    secure = cookie_secure(request) or cross            # SameSite=None needs Secure
    same = "none" if cross else "lax"
    age = SESSION_MAX_DAYS * 86400
    response.set_cookie(SESSION_COOKIE, token, max_age=age, path="/", httponly=True, secure=secure, samesite=same)
    response.set_cookie(CSRF_COOKIE, csrf, max_age=age, path="/", httponly=False, secure=secure, samesite=same)
    return csrf


def clear_session_cookies(response: Response, request: Request) -> None:
    secure = cookie_secure(request) or _cross_site(request)
    same = "none" if _cross_site(request) else "lax"
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=secure, httponly=name == SESSION_COOKIE, samesite=same)


def csrf_ok(request: Request) -> bool:
    cookie, header = request.cookies.get(CSRF_COOKIE, ""), request.headers.get(CSRF_HEADER, "")
    return bool(cookie) and bool(header) and hmac.compare_digest(cookie.encode(), header.encode())


# ---- the cost-weighted limit on anonymous work (roadmap D) -----------------------------------------------------
_BUCKETS: OrderedDict[str, tuple[float, float]] = OrderedDict()
_BUCKETS_LOCK = Lock()
BUCKET_KEYS = 10_000


def anon_cost(path: str) -> int:
    if path.startswith("/api/scenarios/") and path.endswith("/run"):
        return 30
    return ANON_COSTS.get(path.rstrip("/"), 1)


def anon_take(key: str, cost: int, per_minute: int, now: float | None = None) -> float:
    """Take ``cost`` units from the address's bucket (``per_minute`` units, refilled evenly). 0 when it fits, else
    the seconds until it would. ``per_minute`` 0: no limit."""
    if per_minute <= 0:
        return 0.0
    now = time.monotonic() if now is None else now
    cost = min(cost, per_minute)            # one call never costs more than a full bucket
    rate = per_minute / 60.0
    with _BUCKETS_LOCK:
        tokens, at = _BUCKETS.pop(key, (float(per_minute), now))
        tokens = min(float(per_minute), tokens + (now - at) * rate)
        if tokens >= cost:
            _BUCKETS[key] = (tokens - cost, now)
            wait = 0.0
        else:
            _BUCKETS[key] = (tokens, now)
            wait = (cost - tokens) / rate
        while len(_BUCKETS) > BUCKET_KEYS:
            _BUCKETS.popitem(last=False)
    return wait


def client_of(request: Request) -> str:
    """The browser window a save comes from (``X-Client``), so a reload during a save is not taken for a colleague."""
    return request.headers.get("x-client", "").strip()[:64]


def company_error(_request: Request, exc: CompanyError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), **exc.extra})


async def gate(request: Request, call_next):
    """With SCP_REQUIRE_SIGNIN, every API call but health and signing in needs a valid session."""
    path = request.url.path
    asker.set((token_of(request), request.headers.get("x-company", "").strip()))
    takes_gzip.set("gzip" in request.headers.get("accept-encoding", ""))
    takes_rows.set(request.headers.get("x-pack", "") == "rows")
    try:
        signin_required = require_signin()
    except CompanyError as e:
        return company_error(request, e)
    if path in RATED_PATHS and request.method == "POST" and \
            not get_companies().auth_rate(client_ip(request), _int_env("SCP_AUTH_RATE", 30)):
        return JSONResponse(status_code=429, content={"detail": "too many sign-in attempts from your address; try again "
                                                                "in a minute"})
    if (request.method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/") and via_cookie(request)
            and path not in NO_CSRF and not csrf_ok(request)):
        # roadmap D: a change made with the session cookie must prove it comes from this application's own page
        return JSONResponse(status_code=403, content={"detail": "this request is missing its security token "
                                                                "(X-CSRF-Token); reload the page and try again"})
    if request.method == "POST" and path in COOKIE_SIGNIN and wants_cookie(request) and not csrf_ok(request):
        return JSONResponse(status_code=403, content={"detail": "this sign-in is missing its security token "
                                                                "(X-CSRF-Token); reload the page and try again"})
    if signin_required and path.startswith("/api/") and path not in OPEN_PATHS and request.method != "OPTIONS":
        try:
            get_companies().whoami(token_of(request))
        except CompanyError as e:
            return company_error(request, e)
    elif (path.startswith("/api/") and request.method == "POST" and path not in OPEN_PATHS
          and path not in RATED_PATHS and not get_companies().signed_in(token_of(request))):
        # a made-up Bearer token or cookie is no session: it is limited like no token at all (roadmap D)
        # CV-M04: CPU-heavy planning calls without a session are limited per address and in size
        cap = _int_env("SCP_ANON_MAX_MB", 64) * 1024 * 1024
        try:
            size = int(request.headers.get("content-length") or 0)
        except ValueError:
            size = 0
        if cap > 0 and size > cap:
            return JSONResponse(status_code=413, content={"detail": "the request is too large without signing in"})
        wait = anon_take("anon:" + client_ip(request), anon_cost(path), _int_env("SCP_ANON_RATE", 120))
        if wait > 0:
            return JSONResponse(status_code=429, headers={"Retry-After": str(max(1, math.ceil(wait)))},
                                content={"detail": "too much work from your address without signing in; sign in or "
                                                   f"try again in {max(1, math.ceil(wait))} seconds"})
        # and only a few run at once, so anonymous work never takes every CPU from signed-in people
        waited = 0.0
        while not _ANON_SLOTS.acquire(blocking=False):
            if waited >= _int_env("SCP_ANON_WAIT_S", 60):
                return JSONResponse(status_code=429, content={"detail": "the server is busy with work from people who "
                                                                        "are not signed in; sign in or try again"})
            await asyncio.sleep(0.05)
            waited += 0.05
        try:
            return await call_next(request)
        finally:
            _ANON_SLOTS.release()
    return await call_next(request)


def who_asks() -> str | None:
    """The signed-in account's e-mail behind this request, if any (a release of a purchase order is theirs)."""
    token, _ = asker.get()
    if not token:
        return None
    try:
        return get_companies().whoami(token).email
    except CompanyError:
        return None


def signed_in(request: Request) -> User:
    return get_companies().whoami(token_of(request))


def _scope(request: Request, roles: tuple[str, ...]) -> str:
    cid = request.headers.get("x-company", "").strip()
    c = get_companies()
    token = token_of(request)
    user = c.whoami(token) if token and token.startswith(KEY_PREFIX) else None
    if user is not None and not cid:
        cid = c.key_company(user) or ""
    if not cid:
        if require_signin():
            raise CompanyError("open a company first: on this server plan versions and the worklist belong to a "
                               "company", 403)
        return browser_scope(request)
    user = user or c.whoami(token)
    role = c.role(user, cid)
    if roles and role not in roles:
        raise CompanyError(f"as a {role} of this company you cannot change it; ask an owner", 403)
    return cid


def browser_scope(request: Request) -> str:
    """The space of a browser without an open company (CV-H06): a signed-in person's own, else the browser's own
    under a hash of the random key it keeps; never one space shared by every anonymous caller."""
    token = token_of(request)
    if token:
        return "user:" + get_companies().whoami(token).id
    key = request.headers.get("x-browser-key", "").strip()
    if len(key) < 16 or len(key) > 200:
        return ""                 # nowhere to keep anything: stored things refuse (stored_scope), the rest is stateless
    return "anon:" + hashlib.sha256(key.encode()).hexdigest()[:32]


def is_company(scope: str) -> bool:
    """A scope of a server company (as against a browser's or a person's own space)."""
    return bool(scope) and not scope.startswith(("anon:", "user:"))


def scope(request: Request) -> str:
    """The company a stored thing belongs to: the open server company (the asker must be a member), or ``""`` for
    the browser's own."""
    return _scope(request, ())


def edit_scope(request: Request) -> str:
    """As :func:`scope`, for a change: a viewer may not."""
    return _scope(request, CAN_EDIT)


def _kept(sc: str) -> str:
    if not sc:
        raise CompanyError("sign in, open a company, or send this browser's own key (X-Browser-Key): plan versions "
                           "and the worklist are never kept in one space shared by everyone", 400)
    return sc


def stored_scope(request: Request) -> str:
    """As :func:`scope`, for something kept on the server: never the space shared by every anonymous caller."""
    return _kept(scope(request))


def stored_edit_scope(request: Request) -> str:
    return _kept(edit_scope(request))


Signed = Annotated[User, Depends(signed_in)]
Scope = Annotated[str, Depends(scope)]
EditScope = Annotated[str, Depends(edit_scope)]
StoredScope = Annotated[str, Depends(stored_scope)]
StoredEditScope = Annotated[str, Depends(stored_edit_scope)]


# ---- accounts ------------------------------------------------------------------------------------------------
class AuthConfig(Out):
    signup: Literal["open", "invite", "closed"]
    require_signin: bool
    first_account: bool           # nobody has an account yet: the first one can always be made
    mail: bool = False            # the server sends mail (and knows its public address, SCP_PUBLIC_URL): a forgotten
    #                               password is reset by a link sent to the address
    sso: str | None = None        # single sign-on is set up: "Sign in with <sso>"
    password_min: int = 12        # the shortest password a new account, a reset or a change accepts (roadmap D)


class ResetRequest(Out):
    email: str


class ResetPassword(Out):
    token: str
    password: str


class ResetLink(Out):
    link: str                     # to hand to the colleague: opening it lets them choose a new password ("" when mailed)
    expires_at: str
    mailed: bool = False          # the link went to the colleague's own address instead (the server sends mail)


class SignUp(Out):
    email: str
    name: str = ""
    password: str


class SignIn(Out):
    email: str
    password: str


class Me(Out):
    user: User
    companies: list[CompanyMeta]
    invites: list[PendingInvite] = []   # invitations waiting for this account (its address verified)


class InviteAccept(Out):
    token: str = ""               # the invitation's link; or
    company: str = ""             # the company invited to (the account's address must be verified)


class EmailVerify(Out):
    token: str


class Sent(Out):
    ok: bool = True
    mail: bool                    # a link was mailed


class SsoLink(Out):
    url: str                      # open this to link the sign-on account to the signed-in account


class PasswordChange(Out):
    old: str
    new: str


class Csrf(Out):
    csrf: str                     # send it back as X-CSRF-Token on every change made with the session cookie


@router.get("/auth/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    from ..companies import passwords
    return AuthConfig(signup=signup_policy(), require_signin=require_signin(),  # type: ignore[arg-type]
                      first_account=get_companies().users() == 0, mail=links_by_mail(),
                      sso=sso.button() if mail.public_url() else None, password_min=passwords.min_length())


def browser_session(s: Session, request: Request, response: Response) -> Session:
    """A browser that asked for it (``X-SCP-Session: cookie``) gets the session in its HttpOnly cookie and a fresh
    double-submit token in the answer, and no token: a script running in the page at sign-in never sees the
    session. Other callers (scripts) get the token as before."""
    if wants_cookie(request):
        s.csrf = set_session_cookies(response, request, s.token, csrf=secrets.token_urlsafe(24))
        s.token = ""
    return s


@router.post("/auth/signup", response_model=Session)
def auth_signup(body: SignUp, request: Request, response: Response) -> Session:
    return browser_session(get_companies().signup(body.email, body.name, body.password, signup_policy()),
                           request, response)


@router.post("/auth/signin", response_model=Session)
def auth_signin(body: SignIn, request: Request, response: Response) -> Session:
    return browser_session(get_companies().signin(body.email, body.password), request, response)


@router.post("/auth/adopt", response_model=Session)
def auth_adopt(request: Request, response: Response) -> Session:
    """Once, for a browser that kept its session token in its own storage before roadmap D: the token (as
    ``Authorization: Bearer``) is swapped for a new session in the HttpOnly cookie, and stops working."""
    token = bearer_of(request)
    if not token:
        raise CompanyError("send the token kept in this browser to move it to a cookie", 400)
    s = get_companies().adopt(token)
    s.csrf = set_session_cookies(response, request, s.token)
    s.token = ""                  # the new session lives in the cookie only
    return s


@router.get("/auth/csrf", response_model=Csrf)
def auth_csrf(request: Request, response: Response) -> Csrf:
    """The double-submit token of this browser (a client served from another site cannot read the cookie)."""
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        token = secrets.token_urlsafe(24)
        secure = cookie_secure(request) or _cross_site(request)
        response.set_cookie(CSRF_COOKIE, token, path="/", httponly=False, secure=secure,
                            samesite="none" if _cross_site(request) else "lax")
    return Csrf(csrf=token)


@router.post("/auth/signout")
def auth_signout(request: Request, response: Response) -> dict:
    t = token_of(request)
    if t:
        get_companies().signout(t)
    clear_session_cookies(response, request)
    return {"ok": True}


@router.get("/auth/me", response_model=Me)
def auth_me(user: Signed) -> Me:
    c = get_companies()
    return Me(user=user, companies=c.list(user), invites=c.pending_invites(user))


@router.post("/auth/invites/accept", response_model=CompanyMeta)
def auth_accept_invite(body: InviteAccept, user: Signed) -> CompanyMeta:
    """Join a company you were invited to: with the invitation's link, or by its id once your address is verified
    (CV-C01: an invitation is never taken by registering its address)."""
    return get_companies().accept_invite(user, token=body.token.strip(), cid=body.company.strip())


@router.post("/auth/email/request", response_model=Sent)
def auth_email_request(user: Signed) -> Sent:
    """Mail a link that confirms the account's address (needs the server's mail and SCP_PUBLIC_URL)."""
    if not links_by_mail():
        return Sent(mail=False)
    token = get_companies().email_token(user)
    mail.send(user.email, "Confirm your e-mail address",
              f"Open this link within a day to confirm that {user.email} is yours:\n"
              f"{mail.public_url()}/#/account/verify/{token}\n\nIf you did not ask, ignore this mail.")
    return Sent(mail=True)


@router.post("/auth/email/verify", response_model=User)
def auth_email_verify(body: EmailVerify) -> User:
    return get_companies().verify_email(body.token.strip())


@router.post("/auth/password")
def auth_password(body: PasswordChange, user: Signed, request: Request) -> dict:
    get_companies().change_password(user, body.old, body.new, keep_token=token_of(request))
    return {"ok": True}


# ---- companies -----------------------------------------------------------------------------------------------
class NewCompany(Out):
    dataset: dict[str, Any]
    note: str = ""


class SaveCompany(Out):
    dataset: dict[str, Any] | None = None   # the working copy, whole; or
    patch: dict[str, Any] | None = None     # what changed since ``base_revision`` (scp.companies.patch)
    base_revision: int
    note: str = ""                # said in the audit trail, e.g. "from plan version V0003"


class MergeCompany(Out):
    base: dict[str, Any] | None = None      # the save the working copy was made from (default: that revision, kept here)
    dataset: dict[str, Any] | None = None   # the working copy; or
    patch: dict[str, Any] | None = None     # what changed in it since ``base_revision``
    base_revision: int
    clean_only: bool = False      # refuse instead of choosing when a record changed on both sides (autosave)
    choose: dict[str, Literal["mine", "theirs"]] = {}   # per clash id (report.clashes), whose version to keep
    preview: bool = False         # say what the merge would do; save nothing


class RestoreCompany(Out):
    revision: int
    base_revision: int


class MemberChange(Out):
    email: str
    role: Literal["owner", "planner", "viewer"]
    places: list[str] | None = None      # limit a planner's rights to these places ([] = every place; None = as it was)
    families: list[str] | None = None    # … and these product groups


class ApprovalSetting(Out):
    approval: bool                       # master-data changes wait for a second person's approval


class Decision(Out):
    decision: Literal["approve", "reject", "withdraw"]
    note: str = ""


@router.get("/companies", response_model=list[CompanyMeta])
def list_companies(user: Signed) -> list[CompanyMeta]:
    return get_companies().list(user)


@router.post("/companies", response_model=CompanyMeta)
def create_company(body: NewCompany, user: Signed) -> CompanyMeta:
    """Keep a company on the server (e.g. the one in this browser); whoever creates it is its owner."""
    return get_companies().create(user, body.dataset, body.note)


@router.get("/companies/{cid}", response_model=CompanyDoc)
def open_company(cid: str, user: Signed) -> Response:
    meta, text = get_companies().open_text(user, cid)
    return send_raw(b'{"meta":' + meta.model_dump_json(by_alias=True).encode() + b',"dataset":' + text.encode() + b"}")


@router.put("/companies/{cid}", response_model=SaveReport)
def save_company(cid: str, body: SaveCompany, user: Signed, request: Request) -> SaveReport:
    """Save the working copy, whole or as what changed. 409 when someone saved after ``base_revision``
    (``revision``, ``updated_by`` and ``updated_at`` say who and when); not when every save since came from the
    same window (``X-Client``), which a reload during a save leaves behind."""
    return get_companies().save(user, cid, body.dataset, body.base_revision, note=body.note, patch=body.patch,
                                client=client_of(request))


@router.post("/companies/{cid}/merge", response_model=MergeResult)
def merge_company(cid: str, body: MergeCompany, user: Signed, request: Request) -> MergeResult:
    """After a refused save: merge the working copy with the saves made since, record by record, and save that
    (or, with ``preview``, only say what it would do, with each record changed on both sides side by side)."""
    return get_companies().merge_save(user, cid, body.base, body.dataset, body.base_revision, body.clean_only,
                                      patch=body.patch, client=client_of(request), choose=dict(body.choose),
                                      preview=body.preview)


@router.delete("/companies/{cid}")
def delete_company(cid: str, user: Signed) -> dict:
    get_companies().delete(user, cid)
    return {"ok": True}


@router.get("/companies/{cid}/history", response_model=list[LogRow])
def company_history(cid: str, user: Signed, limit: int = 200, before: int | None = None) -> list[LogRow]:
    return get_companies().history(user, cid, min(max(limit, 1), 1000), before)


@router.get("/companies/{cid}/revisions/{rev}", response_model=dict[str, Any])
def company_revision(cid: str, rev: int, user: Signed) -> dict[str, Any]:
    return get_companies().revision(user, cid, rev)


@router.post("/companies/{cid}/restore", response_model=SaveReport)
def restore_company(cid: str, body: RestoreCompany, user: Signed, request: Request) -> SaveReport:
    return get_companies().restore(user, cid, body.revision, body.base_revision, client=client_of(request))


@router.get("/companies/{cid}/members", response_model=list[Member])
def company_members(cid: str, user: Signed) -> list[Member]:
    return get_companies().members(user, cid)


@router.post("/companies/{cid}/members", response_model=list[Member])
def set_company_member(cid: str, body: MemberChange, user: Signed, request: Request) -> list[Member]:
    """Change a member's role, or invite an address (with or without an account): the answer carries the
    invitation's link once (``invite_link``), and it is mailed to the address when the server sends mail. Nobody
    joins until they accept it (CV-C01)."""
    out = get_companies().set_member(user, cid, body.email, body.role, body.places, body.families)
    for m in out:
        if m.invite_link:
            link = f"{base_url(request)}/#/account/invite/{m.invite_link}"
            m.invite_link = link
            if links_by_mail():
                mailed = f"{mail.public_url()}/#/account/invite/{link.rsplit('/', 1)[1]}"
                try:
                    mail.send(m.email, "You are invited to a company",
                              f"{user.name or user.email} invited you to work in their company as a {m.role}.\n\n"
                              f"Open this link within {14} days to accept (sign up or sign in with {m.email}):\n"
                              f"{mailed}\n\nIf you do not know them, ignore this mail.")
                except Exception:  # noqa: BLE001 - the owner still has the link to hand over
                    pass
    return out


@router.delete("/companies/{cid}/members/{email}", response_model=list[Member])
def remove_company_member(cid: str, email: str, user: Signed) -> list[Member]:
    return get_companies().remove_member(user, cid, email)


@router.put("/companies/{cid}/approval", response_model=CompanyMeta)
def set_company_approval(cid: str, body: ApprovalSetting, user: Signed) -> CompanyMeta:
    """An owner turns master-data approval on or off (on needs a second person who can change the data)."""
    return get_companies().set_approval(user, cid, body.approval)


@router.get("/companies/{cid}/held", response_model=list[HeldChange])
def company_held_changes(cid: str, user: Signed, status: Literal["pending", "approved", "rejected", "withdrawn", "all"] = "pending",
                         limit: int = 50) -> list[HeldChange]:
    """Master-data changes waiting for approval (or decided), newest first, each with every field it changes."""
    return get_companies().held_changes(user, cid, status, min(max(limit, 1), 200))


@router.post("/companies/{cid}/held/{rid}", response_model=SaveReport)
def decide_held_change(cid: str, rid: int, body: Decision, user: Signed, request: Request) -> SaveReport:
    """Approve (someone other than who asked; the change is saved), reject, or withdraw (who asked) a held change.
    An approval answers with the company as saved."""
    return get_companies().decide(user, cid, rid, body.decision, body.note, client=client_of(request))


@router.get("/companies/{cid}/changes", response_model=list[FieldChangeRow])
def company_changes(cid: str, user: Signed, q: str = "", list: str = "", limit: int = 200,  # noqa: A002
                    before: int | None = None) -> list[FieldChangeRow]:
    """Change documents: every field changed with its old and new value, newest first; ``q`` finds records by key."""
    return get_companies().changes(user, cid, q, list, min(max(limit, 1), 1000), before)


# ---- a forgotten password (Phase L) ---------------------------------------------------------------------------
def base_url(request: Request) -> str:
    """Where people open the application: SCP_PUBLIC_URL, else the address this request came to. Only for a link
    shown to the signed-in person who asked; anything mailed or sent to an identity provider uses SCP_PUBLIC_URL
    alone (CV-H10)."""
    return mail.public_url() or str(request.base_url).rstrip("/")


def links_by_mail() -> bool:
    """The server mails links: it has a mail server and knows its own public address (never the Host header)."""
    return mail.mail_on() and bool(mail.public_url())


def public_base() -> str:
    url = mail.public_url()
    if not url:
        raise CompanyError("the server's administrator must set SCP_PUBLIC_URL (where people open the application) "
                           "for this", 503)
    return url


def reset_link(request: Request, token: str) -> str:
    return f"{base_url(request)}/#/account/reset/{token}"


@router.post("/auth/reset/request")
def auth_reset_request(body: ResetRequest, request: Request) -> dict:
    """Mail a link to set a new password, if the address has an account and the server sends mail. The answer is
    the same either way, so nobody learns which addresses have accounts."""
    if links_by_mail():
        get_companies().request_reset(body.email, lambda t: f"{public_base()}/#/account/reset/{t}",
                                      lambda *a: mail.send(*a))
    return {"ok": True, "mail": links_by_mail()}


@router.post("/auth/reset", response_model=Session)
def auth_reset(body: ResetPassword, request: Request, response: Response) -> Session:
    """Set a new password with a reset link's token; signs out every other session of the account."""
    return browser_session(get_companies().reset_password(body.token, body.password), request, response)


@router.post("/companies/{cid}/members/{email}/reset", response_model=ResetLink)
def member_reset_link(cid: str, email: str, user: Signed, request: Request) -> ResetLink:
    """An owner makes a link for a planner or viewer to set a new password (valid 24 hours), to hand over."""
    token, expires = get_companies().member_reset(user, cid, email)
    if links_by_mail():   # CV-H01: to the account's own address, never shown to the owner
        mail.send(email.strip(), "Set a new password",
                  f"{user.name or user.email}, an owner of your company, asked for a link for you to set a new password "
                  f"for {email.strip()}.\n\nOpen it within a day:\n{public_base()}/#/account/reset/{token}\n\n"
                  "If you did not expect this, tell your company's owner; your password stays as it is.")
        return ResetLink(link="", expires_at=expires, mailed=True)
    return ResetLink(link=reset_link(request, token), expires_at=expires)


# ---- single sign-on (Phase L) ---------------------------------------------------------------------------------
def _callback(_request: Request | None = None) -> str:
    return f"{public_base()}/api/auth/sso/callback"


@router.get("/auth/sso/start")
def auth_sso_start(request: Request, next: str = "") -> RedirectResponse:  # noqa: A002
    """Send the browser to the company's identity provider to sign in."""
    if not sso.configured():
        raise CompanyError("single sign-on is not set up on this server", 404)
    url, state, verifier, nonce = sso.begin(_callback(request))
    back = "" if next.startswith("link:") else next[:200]      # a link is begun only signed in (auth_sso_link)
    get_companies().keep_state(state, verifier, nonce, back)
    return RedirectResponse(url, status_code=302)


@router.post("/auth/sso/link", response_model=SsoLink)
def auth_sso_link(user: Signed) -> SsoLink:
    """Begin binding the company's sign-on to the signed-in account (the only way an existing account gets it)."""
    if not sso.configured():
        raise CompanyError("single sign-on is not set up on this server", 404)
    url, state, verifier, nonce = sso.begin(_callback())
    get_companies().keep_state(state, verifier, nonce, f"link:{user.id}")
    return SsoLink(url=url)


@router.get("/auth/sso/callback")
def auth_sso_callback(request: Request, code: str = "", state: str = "", error: str = "",
                      error_description: str = "") -> RedirectResponse:
    """The identity provider sends the browser back here: sign in, and open the application signed in."""
    home = public_base()
    try:
        if error:
            raise CompanyError(error_description or error, 401)
        verifier, nonce, next_ = get_companies().take_state(state)
        subject, email, name = sso.finish(code, verifier, _callback(request), nonce=nonce)
        s = get_companies().sso_session(subject, email, name, signup_policy(),
                                        link_to=next_.removeprefix("link:") if next_.startswith("link:") else "")
    except CompanyError as e:
        return RedirectResponse(f"{home}/#/account/sso-failed/{quote(str(e), safe='')}", status_code=302)
    # roadmap D: the session goes into the HttpOnly cookie, never into the address (history, logs, referrers)
    out = RedirectResponse(f"{home}/#/account/sso", status_code=302)
    set_session_cookies(out, request, s.token)
    return out
