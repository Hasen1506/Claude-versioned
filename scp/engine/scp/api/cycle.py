"""The monthly S&OP cycle over HTTP: cycles of a company, step owners, sign-off and reopening (scp.sop.cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import Field

from ..companies import get_companies
from ..model.common import Out
from ..sop.cycle import STEPS, Actor, Cycle, CycleSummary, Figures, figures, get_cycles
from ..versions import VersionError
from .companies import Scope, StoredEditScope, StoredScope, is_company, token_of
from .working import PlanData

router = APIRouter(prefix="/api/sop", tags=["sop"])


def actor(request: Request, sc: str) -> Actor:
    """Who acts in ``sc``: in a company the member and their role; in one's own space, its owner."""
    token = token_of(request)
    c = get_companies()
    if is_company(sc):
        user = c.whoami(token)
        return Actor(user.email, c.role(user, sc), True)
    return Actor(c.whoami(token).email if token else "", "owner", False)


class NewCycle(Out):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="The month of the cycle, YYYY-MM")


class OwnerRequest(Out):
    owner: str = Field("", max_length=200, description="Who signs the step (a member's e-mail); empty = nobody")


class SignRequest(Out):
    dataset: PlanData
    note: str = Field("", max_length=4000, description="What was agreed (the pre-S&OP and executive steps need it)")


class ReopenRequest(Out):
    note: str = Field(max_length=4000, description="Why it is reopened")


class FiguresRequest(Out):
    dataset: PlanData
    step: str = Field(description="One of " + ", ".join(STEPS))


@router.get("/cycles", response_model=list[CycleSummary])
def list_cycles(sc: StoredScope) -> list[CycleSummary]:
    return get_cycles().list(sc)


@router.post("/cycles", response_model=Cycle)
def create_cycle(req: NewCycle, sc: StoredEditScope, request: Request) -> Cycle:
    return get_cycles().create(req.month, sc, actor(request, sc))


@router.get("/cycles/{cid}", response_model=Cycle)
def get_cycle(cid: str, sc: StoredScope) -> Cycle:
    return get_cycles().get(cid, sc)


@router.delete("/cycles/{cid}", response_model=list[CycleSummary])
def delete_cycle(cid: str, sc: StoredEditScope, request: Request) -> list[CycleSummary]:
    get_cycles().delete(cid, sc, actor(request, sc))
    return get_cycles().list(sc)


@router.put("/cycles/{cid}/steps/{step}/owner", response_model=Cycle)
def set_step_owner(cid: str, step: str, req: OwnerRequest, sc: StoredEditScope, request: Request) -> Cycle:
    who = actor(request, sc)
    owner = req.owner.strip()
    if owner and who.company:
        user = get_companies().whoami(token_of(request))
        members = {m.email.lower(): m for m in get_companies().members(user, sc)}
        m = members.get(owner.lower())
        if m is None:
            raise VersionError(f"{owner} is not a member of this company", 422)
        if m.role == "viewer":
            raise VersionError(f"{owner} is a viewer here and cannot sign a step", 422)
        owner = m.email
    return get_cycles().set_owner(cid, step, owner, sc, who)


@router.post("/cycles/{cid}/steps/{step}/sign", response_model=Cycle)
def sign_step(cid: str, step: str, req: SignRequest, sc: StoredEditScope, request: Request) -> Cycle:
    return get_cycles().sign(cid, step, req.dataset, req.note, sc, actor(request, sc))


@router.post("/cycles/{cid}/steps/{step}/reopen", response_model=Cycle)
def reopen_step(cid: str, step: str, req: ReopenRequest, sc: StoredEditScope, request: Request) -> Cycle:
    return get_cycles().reopen(cid, step, req.note, sc, actor(request, sc))


@router.post("/figures", response_model=Figures)
def step_figures(req: FiguresRequest, _sc: Scope) -> Figures:
    """A step's figures for the company as it is now: what signing it would record (nothing is kept)."""
    return figures(req.dataset, req.step)
