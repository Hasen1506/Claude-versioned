"""Sign-in and companies kept on the server (Phase I).

A request says who is asking with ``Authorization: Bearer <token>`` and which company it works in with
``X-Company: <id>``. Planning calls stay stateless (the dataset travels with each request); what is stored, the
company's document, its plan versions and its worklist, belongs to the company and needs a member.

Server settings (environment):

* ``SCP_SIGNUP``: ``open`` (anyone can make an account, the default), ``invite`` (only an e-mail a company owner
  invited, and the very first account) or ``closed`` (only the very first account).
* ``SCP_REQUIRE_SIGNIN=1``: every API call except health and signing in needs a session, and plan versions and the
  worklist need an open company (nothing is kept outside a company).
"""
from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..companies import (
    CAN_EDIT, CompanyDoc, CompanyError, CompanyMeta, FieldChangeRow, HeldChange, LogRow, Member, MergeResult,
    SaveReport, Session, User, get_companies,
)
from ..companies import mail, sso
from ..model.common import Out
from .working import asker, send_raw, takes_gzip, takes_rows

router = APIRouter(prefix="/api", tags=["companies"])

OPEN_PATHS = ("/api/health", "/api/auth/config", "/api/auth/signin", "/api/auth/signup", "/api/auth/reset",
              "/api/auth/reset/request", "/api/auth/sso/start", "/api/auth/sso/callback")


def signup_policy() -> str:
    p = os.environ.get("SCP_SIGNUP", "open").strip().lower()
    return p if p in ("open", "invite", "closed") else "open"


def require_signin() -> bool:
    return os.environ.get("SCP_REQUIRE_SIGNIN", "").strip().lower() in ("1", "true", "yes", "on")


def token_of(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() or None if h.lower().startswith("bearer ") else None


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
    if require_signin() and path.startswith("/api/") and path not in OPEN_PATHS and request.method != "OPTIONS":
        try:
            get_companies().whoami(token_of(request))
        except CompanyError as e:
            return company_error(request, e)
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
    if not cid:
        if require_signin():
            raise CompanyError("open a company first: on this server plan versions and the worklist belong to a "
                               "company", 403)
        return ""
    c = get_companies()
    user = c.whoami(token_of(request))
    role = c.role(user, cid)
    if roles and role not in roles:
        raise CompanyError(f"as a {role} of this company you cannot change it; ask an owner", 403)
    return cid


def scope(request: Request) -> str:
    """The company a stored thing belongs to: the open server company (the asker must be a member), or ``""`` for
    the browser's own."""
    return _scope(request, ())


def edit_scope(request: Request) -> str:
    """As :func:`scope`, for a change: a viewer may not."""
    return _scope(request, CAN_EDIT)


Signed = Annotated[User, Depends(signed_in)]
Scope = Annotated[str, Depends(scope)]
EditScope = Annotated[str, Depends(edit_scope)]


# ---- accounts ------------------------------------------------------------------------------------------------
class AuthConfig(Out):
    signup: Literal["open", "invite", "closed"]
    require_signin: bool
    first_account: bool           # nobody has an account yet: the first one can always be made
    mail: bool = False            # the server sends mail: a forgotten password is reset by a link sent to the address
    sso: str | None = None        # single sign-on is set up: "Sign in with <sso>"


class ResetRequest(Out):
    email: str


class ResetPassword(Out):
    token: str
    password: str


class ResetLink(Out):
    link: str                     # to hand to the colleague: opening it lets them choose a new password
    expires_at: str


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


class PasswordChange(Out):
    old: str
    new: str


@router.get("/auth/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    return AuthConfig(signup=signup_policy(), require_signin=require_signin(),  # type: ignore[arg-type]
                      first_account=get_companies().users() == 0, mail=mail.mail_on(), sso=sso.button())


@router.post("/auth/signup", response_model=Session)
def auth_signup(body: SignUp) -> Session:
    return get_companies().signup(body.email, body.name, body.password, signup_policy())


@router.post("/auth/signin", response_model=Session)
def auth_signin(body: SignIn) -> Session:
    return get_companies().signin(body.email, body.password)


@router.post("/auth/signout")
def auth_signout(request: Request) -> dict:
    t = token_of(request)
    if t:
        get_companies().signout(t)
    return {"ok": True}


@router.get("/auth/me", response_model=Me)
def auth_me(user: Signed) -> Me:
    return Me(user=user, companies=get_companies().list(user))


@router.post("/auth/password")
def auth_password(body: PasswordChange, user: Signed) -> dict:
    get_companies().change_password(user, body.old, body.new)
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
def set_company_member(cid: str, body: MemberChange, user: Signed) -> list[Member]:
    """Add a member or change their role; an e-mail without an account is invited."""
    return get_companies().set_member(user, cid, body.email, body.role, body.places, body.families)


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
    """Where people open the application: SCP_PUBLIC_URL, else the address this request came to."""
    return mail.public_url() or str(request.base_url).rstrip("/")


def reset_link(request: Request, token: str) -> str:
    return f"{base_url(request)}/#/account/reset/{token}"


@router.post("/auth/reset/request")
def auth_reset_request(body: ResetRequest, request: Request) -> dict:
    """Mail a link to set a new password, if the address has an account and the server sends mail. The answer is
    the same either way, so nobody learns which addresses have accounts."""
    if mail.mail_on():
        get_companies().request_reset(body.email, lambda t: reset_link(request, t), lambda *a: mail.send(*a))
    return {"ok": True, "mail": mail.mail_on()}


@router.post("/auth/reset", response_model=Session)
def auth_reset(body: ResetPassword) -> Session:
    """Set a new password with a reset link's token; signs out every other session of the account."""
    return get_companies().reset_password(body.token, body.password)


@router.post("/companies/{cid}/members/{email}/reset", response_model=ResetLink)
def member_reset_link(cid: str, email: str, user: Signed, request: Request) -> ResetLink:
    """An owner makes a link for a planner or viewer to set a new password (valid 24 hours), to hand over."""
    token, expires = get_companies().member_reset(user, cid, email)
    return ResetLink(link=reset_link(request, token), expires_at=expires)


# ---- single sign-on (Phase L) ---------------------------------------------------------------------------------
def _callback(request: Request) -> str:
    return f"{base_url(request)}/api/auth/sso/callback"


@router.get("/auth/sso/start")
def auth_sso_start(request: Request, next: str = "") -> RedirectResponse:  # noqa: A002
    """Send the browser to the company's identity provider to sign in."""
    if not sso.configured():
        raise CompanyError("single sign-on is not set up on this server", 404)
    url, state, verifier, nonce = sso.begin(_callback(request))
    get_companies().keep_state(state, verifier, nonce, next[:200])
    return RedirectResponse(url, status_code=302)


@router.get("/auth/sso/callback")
def auth_sso_callback(request: Request, code: str = "", state: str = "", error: str = "",
                      error_description: str = "") -> RedirectResponse:
    """The identity provider sends the browser back here: sign in, and open the application signed in."""
    home = base_url(request)
    try:
        if error:
            raise CompanyError(error_description or error, 401)
        verifier, _nonce, _next = get_companies().take_state(state)
        subject, email, name = sso.finish(code, verifier, _callback(request))
        s = get_companies().sso_session(subject, email, name, signup_policy())
    except CompanyError as e:
        return RedirectResponse(f"{home}/#/account/sso-failed/{quote(str(e), safe='')}", status_code=302)
    return RedirectResponse(f"{home}/#/account/sso/{s.token}", status_code=302)
