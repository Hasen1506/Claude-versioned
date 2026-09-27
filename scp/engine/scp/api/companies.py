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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..companies import (
    CAN_EDIT, CompanyDoc, CompanyError, CompanyMeta, LogRow, Member, MergeResult, SaveReport, Session, User,
    get_companies,
)
from ..model.common import Out

router = APIRouter(prefix="/api", tags=["companies"])

OPEN_PATHS = ("/api/health", "/api/auth/config", "/api/auth/signin", "/api/auth/signup")


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
    if require_signin() and path.startswith("/api/") and path not in OPEN_PATHS and request.method != "OPTIONS":
        try:
            get_companies().whoami(token_of(request))
        except CompanyError as e:
            return company_error(request, e)
    return await call_next(request)


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
    return AuthConfig(signup=signup_policy(), require_signin=require_signin(), first_account=get_companies().users() == 0)  # type: ignore[arg-type]


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


@router.get("/companies", response_model=list[CompanyMeta])
def list_companies(user: Signed) -> list[CompanyMeta]:
    return get_companies().list(user)


@router.post("/companies", response_model=CompanyMeta)
def create_company(body: NewCompany, user: Signed) -> CompanyMeta:
    """Keep a company on the server (e.g. the one in this browser); whoever creates it is its owner."""
    return get_companies().create(user, body.dataset, body.note)


@router.get("/companies/{cid}", response_model=CompanyDoc)
def open_company(cid: str, user: Signed) -> CompanyDoc:
    return get_companies().open(user, cid)


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
    return get_companies().set_member(user, cid, body.email, body.role)


@router.delete("/companies/{cid}/members/{email}", response_model=list[Member])
def remove_company_member(cid: str, email: str, user: Signed) -> list[Member]:
    return get_companies().remove_member(user, cid, email)
