"""The supplier portal over HTTP (Enterprise 7.2).

Three kinds of call:

* Buying's, on the company being worked on (``dataset``, like every step): what a supplier sees, a step recorded for
  them (a confirmation, a dispatch advice, goods received against it, a notice cancelled), a UBL message read in,
  and a purchase order as a UBL Order.
* The links, on a company kept on the server: made, listed and withdrawn by its planners.
* The supplier's, with the link's secret in ``X-Portal-Token`` and nothing else: their open order lines, their answer
  and their dispatch advice, saved straight to the company as a change by the link's maker.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import ConfigDict, Field

from .. import portal
from ..companies import get_companies
from ..model import Dataset
from ..model.common import Out
from ..portal import PortalError, PortalView, links, ubl
from .companies import Signed
from .working import PlanData, answer

router = APIRouter(tags=["portal"])
TOKEN_HEADER = "x-portal-token"


class ConfirmPart(Out):
    date: dt.date
    qty: float = Field(ge=0, allow_inf_nan=False)


class ConfirmLine(Out):
    order: str = Field(min_length=1, max_length=64)
    qty: float | None = Field(None, ge=0, allow_inf_nan=False)
    date: dt.date | None = None
    parts: list[ConfirmPart] | None = Field(None, max_length=20)


class NoticeLineInput(Out):
    order: str = Field(min_length=1, max_length=64)
    qty: float | None = Field(None, gt=0, allow_inf_nan=False)
    batch: str | None = Field(None, max_length=40)
    expires_on: dt.date | None = None


def _confirm_lines(lines: list[ConfirmLine]) -> list[dict]:
    out = []
    for x in lines:
        w: dict[str, Any] = {"order": x.order}
        if x.parts:
            w["parts"] = [{"date": p.date, "qty": p.qty} for p in x.parts]
        else:
            if x.qty is not None:
                w["qty"] = x.qty
            if x.date is not None:
                w["date"] = x.date.isoformat()
        out.append(w)
    return out


def _notice_lines(lines: list[NoticeLineInput]) -> list[dict]:
    return [x.model_dump() for x in lines]


# ---- Buying's side -----------------------------------------------------------------------------------------------
class PortalViewRequest(Out):
    dataset: PlanData
    supplier: str
    date: dt.date | None = None


@router.post("/api/portal/view", response_model=PortalView)
def post_portal_view(req: PortalViewRequest) -> PortalView:
    """What the supplier sees on their link: their sent, open order lines and their shipping notices."""
    try:
        return portal.view(req.dataset, req.supplier, req.date)
    except PortalError as e:
        raise HTTPException(409, str(e)) from e


class PortalActionRequest(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    dataset: PlanData
    action: Literal["respond", "dispatch", "receive", "cancel", "message"]
    supplier: str | None = None                     # respond, dispatch
    id: str | None = None                           # receive, cancel: the notice
    confirm: list[ConfirmLine] | None = Field(None, max_length=200)          # respond
    lines: list[NoticeLineInput] | None = Field(None, max_length=200)        # dispatch; receive: what came
    shipped_on: dt.date | None = None
    arrives_on: dt.date | None = None
    reference: str = Field("", max_length=64)
    note: str = Field("", max_length=400)
    date: dt.date | None = None                     # receive
    xml: str | None = Field(None, max_length=ubl.MAX_BYTES)                 # message: a UBL OrderResponse or DespatchAdvice


class PortalActionResponse(Out):
    dataset: Dataset | None = None
    patch: dict[str, Any] | None = None
    message: str
    id: str | None = None


@router.post("/api/portal/act", response_model=PortalActionResponse)
def post_portal_act(req: PortalActionRequest) -> PortalActionResponse:
    """A supplier's step recorded by Buying (they phoned or mailed it), goods received against a shipping notice, a
    notice cancelled, or a UBL message read in."""
    ds = req.dataset

    def need(v, what: str):
        if v is None or v == "" or v == []:
            raise PortalError(f"say {what}")
        return v

    try:
        if req.action == "respond":
            new, rep = portal.respond(ds, need(req.supplier, "which supplier"),
                                      _confirm_lines(need(req.confirm, "which lines")), req.reference)
        elif req.action == "dispatch":
            new, rep = portal.dispatch(ds, need(req.supplier, "which supplier"),
                                       _notice_lines(need(req.lines, "what is on the way")), req.shipped_on,
                                       req.arrives_on, req.reference, "entered", req.note)
        elif req.action == "receive":
            new, rep = portal.receive(ds, need(req.id, "which shipping notice"), req.date,
                                      _notice_lines(req.lines) if req.lines else None, req.reference)
        elif req.action == "cancel":
            new, rep = portal.cancel(ds, need(req.id, "which shipping notice"))
        else:
            text = need(req.xml, "the message")
            new, rep = ubl.apply(ds, ubl.kind_of(text), text)
    except PortalError as e:
        raise HTTPException(409, str(e)) from e
    return PortalActionResponse(**answer(ds, new), message=rep.message, id=rep.id)


class OrderXmlRequest(Out):
    dataset: PlanData
    po: str


@router.post("/api/portal/order-xml")
def post_order_xml(req: OrderXmlRequest) -> Response:
    """The purchase order as a UBL 2.1 Order (Peppol BIS Ordering), to send to a supplier's system."""
    try:
        text = ubl.order_xml(req.dataset, req.po)
    except PortalError as e:
        raise HTTPException(409, str(e)) from e
    return Response(text, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{req.po}.xml"'})


# ---- links ---------------------------------------------------------------------------------------------------------
class NewLink(Out):
    supplier: str = Field(min_length=1, max_length=64)
    days: int = Field(links.DAYS, ge=1, le=366)


@router.get("/api/companies/{cid}/portal-links", response_model=list[links.PortalLink])
def list_links(cid: str, user: Signed) -> list[links.PortalLink]:
    return links.listing(get_companies(), user, cid)


@router.post("/api/companies/{cid}/portal-links", response_model=links.PortalLink)
def make_link(cid: str, body: NewLink, user: Signed) -> links.PortalLink:
    """A link for one supplier; its secret (``token``) is in this answer only: send the link to the supplier now."""
    return links.create(get_companies(), user, cid, body.supplier, body.days)


@router.delete("/api/companies/{cid}/portal-links/{lid}", response_model=list[links.PortalLink])
def revoke_link(cid: str, lid: str, user: Signed) -> list[links.PortalLink]:
    return links.revoke(get_companies(), user, cid, lid)


# ---- the supplier's side -------------------------------------------------------------------------------------------
def _token(request: Request) -> str:
    return request.headers.get(TOKEN_HEADER, "").strip()


class SupplierView(PortalView):
    link: str
    expires_at: str


def _view(request: Request) -> SupplierView:
    c = get_companies()
    a, ds = links.read(c, _token(request))
    row = c.db.execute("SELECT expires_at FROM portal_links WHERE id = ?", (a.link,)).fetchone()
    return SupplierView(**portal.view(ds, a.supplier).model_dump(), link=a.link, expires_at=row["expires_at"])


@router.get("/api/portal", response_model=SupplierView)
def get_supplier_view(request: Request) -> SupplierView:
    """The supplier's open order lines and shipping notices, on their link."""
    return _view(request)


class SupplierRespond(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    lines: list[ConfirmLine] = Field(min_length=1, max_length=200)
    reference: str = Field("", max_length=64)


class SupplierAnswer(Out):
    message: str
    id: str | None = None
    view: SupplierView


def _do(request: Request, step, what: str) -> SupplierAnswer:
    try:
        _a, _new, rep = links.write(get_companies(), _token(request), step, what)
    except PortalError as e:
        raise HTTPException(409, str(e)) from e
    return SupplierAnswer(message=rep.message, id=rep.id, view=_view(request))


@router.post("/api/portal/respond", response_model=SupplierAnswer)
def post_supplier_respond(body: SupplierRespond, request: Request) -> SupplierAnswer:
    """Order lines confirmed as asked, or changed: a smaller quantity, a later date, several deliveries."""
    return _do(request, lambda ds, sup: portal.respond(ds, sup, _confirm_lines(body.lines), body.reference),
               "order confirmation")


class SupplierDispatch(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    lines: list[NoticeLineInput] = Field(min_length=1, max_length=200)
    shipped_on: dt.date | None = None
    arrives_on: dt.date | None = None
    reference: str = Field("", max_length=64)
    note: str = Field("", max_length=400)


@router.post("/api/portal/dispatch", response_model=SupplierAnswer)
def post_supplier_dispatch(body: SupplierDispatch, request: Request) -> SupplierAnswer:
    """Goods on their way: a shipping notice the customer receives against."""
    return _do(request, lambda ds, sup: portal.dispatch(ds, sup, _notice_lines(body.lines), body.shipped_on,
                                                        body.arrives_on, body.reference, "portal", body.note),
               "dispatch advice")


@router.post("/api/portal/message", response_model=SupplierAnswer)
async def post_supplier_message(request: Request) -> SupplierAnswer:
    """A UBL OrderResponse or DespatchAdvice, as the body (``application/xml``), from the supplier's own system."""
    raw = await request.body()
    if len(raw) > ubl.MAX_BYTES:
        raise HTTPException(413, f"the message is larger than {ubl.MAX_BYTES // 1_000_000} MB")
    try:
        kind = ubl.kind_of(raw)
    except PortalError as e:
        raise HTTPException(422, str(e)) from e

    def step(ds: Dataset, sup: str):
        if kind == "order_response":
            who, ref, lines = ubl.read_order_response(ds, raw)
        else:
            who, kw = ubl.read_despatch_advice(ds, raw)
        if who != sup:
            raise PortalError("the message is about another supplier's orders")
        if kind == "order_response":
            return portal.respond(ds, sup, lines, ref)
        return portal.dispatch(ds, sup, source="message", **kw)
    return _do(request, step, "order response" if kind == "order_response" else "despatch advice")


@router.get("/api/portal/order")
def get_supplier_order(po: str, request: Request) -> Response:
    """One of the supplier's orders as a UBL Order."""
    a, ds = links.read(get_companies(), _token(request))
    head = ds.purchase_order_by_id.get(po)
    if head is None or head.supplier != a.supplier or head.sent_on is None:
        raise HTTPException(404, f"no order {po} sent to you")
    return Response(ubl.order_xml(ds, po), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{po}.xml"'})
