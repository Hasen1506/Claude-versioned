"""Connected to the rest of the company (Phase Q): keys for other systems, an ERP's messages and the orders it takes
back, and the log of every message.

An ERP sends ``Authorization: Bearer scpk_…`` (a key an owner made on the Connections page) and works in the one
company the key belongs to. See ``docs/INTEGRATION.md`` for the messages, with examples.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from ..companies import ApiKey, CompanyError, get_companies
from ..connect import (
    ErpAck, ErpOrder, ErpPosting, ErpStock, MessageAnswer, MessageRow, OutOrder, acknowledge, apply_orders,
    apply_postings, apply_records, apply_stock, history, log, outbound, read_company, receive, record_lists,
)
from ..connect import imports, outbox
from ..connect.erp import ItemResult, withdrawn
from ..connect.imports import ImportJobs
from ..model.common import Model, Out
from .companies import Signed

router = APIRouter(prefix="/api/companies/{cid}", tags=["connections"])


# ---- keys ------------------------------------------------------------------------------------------------------
class NewKey(Model):
    name: str = Field(min_length=1, max_length=60)
    role: Literal["planner", "viewer"] = "planner"


@router.get("/keys", response_model=list[ApiKey])
def list_keys(cid: str, user: Signed) -> list[ApiKey]:
    return get_companies().keys(user, cid)


@router.post("/keys", response_model=ApiKey)
def make_key(cid: str, body: NewKey, user: Signed) -> ApiKey:
    """A key for another system; the key itself (``token``) is in this answer only: give it to that system now."""
    return get_companies().create_key(user, cid, body.name, body.role)


@router.delete("/keys/{kid}", response_model=list[ApiKey])
def revoke_key(cid: str, kid: str, user: Signed) -> list[ApiKey]:
    return get_companies().revoke_key(user, cid, kid)


# ---- messages in -----------------------------------------------------------------------------------------------
class OrdersMessage(Model):
    message_id: str = Field("", max_length=100, description="The sender's id for the message: sent again, it is not "
                                                             "applied twice")
    orders: list[ErpOrder] = Field(max_length=5000)


class StockMessage(Model):
    message_id: str = Field("", max_length=100)
    as_of: dt.date | None = Field(None, description="Stock at the end of this day (default: the day before the "
                                                    "planning start)")
    stock: list[ErpStock] = Field(max_length=200_000)


class PostingsMessage(Model):
    message_id: str = Field("", max_length=100)
    postings: list[ErpPosting] = Field(max_length=20_000)


class RecordsMessage(Model):
    message_id: str = Field("", max_length=100)
    records: list[dict[str, Any]] = Field(max_length=200_000)


class AckMessage(Model):
    message_id: str = Field("", max_length=100)
    orders: list[ErpAck] = Field(max_length=20_000)


@router.post("/erp/orders", response_model=MessageAnswer)
def erp_orders(cid: str, body: OrdersMessage, user: Signed) -> MessageAnswer:
    """Customer orders from the ERP, new or changed (by the ERP's order number), or cancelled."""
    return receive(get_companies(), user, cid, "orders", body.message_id, lambda ds: apply_orders(ds, body.orders))


@router.post("/erp/stock", response_model=MessageAnswer)
def erp_stock(cid: str, body: StockMessage, user: Signed) -> MessageAnswer:
    """The ERP's stock per place and product: differences are posted as count differences."""
    return receive(get_companies(), user, cid, "stock", body.message_id,
                   lambda ds: apply_stock(ds, body.stock, body.as_of))


@router.post("/erp/postings", response_model=MessageAnswer)
def erp_postings(cid: str, body: PostingsMessage, user: Signed) -> MessageAnswer:
    """Goods movements from the ERP, each taken once by its document number."""
    return receive(get_companies(), user, cid, "postings", body.message_id,
                   lambda ds: apply_postings(ds, body.postings))


@router.get("/erp/records", response_model=list[str])
def erp_record_lists(cid: str, user: Signed) -> list[str]:
    """The lists of master data the ERP can send record by record."""
    get_companies().role(user, cid)
    return record_lists()


@router.post("/erp/records/{name}", response_model=MessageAnswer)
def erp_records(cid: str, name: str, body: RecordsMessage, user: Signed) -> MessageAnswer:
    """Master data records of one list (products, locations, …), added or changed in the fields sent."""
    if name not in record_lists():
        raise CompanyError(f"{name!r} is not a list of master data the ERP can send; it is one of "
                           f"{', '.join(record_lists())}", 404)
    return receive(get_companies(), user, cid, f"records:{name}", body.message_id,
                   lambda ds: apply_records(ds, name, body.records))


# ---- orders back -----------------------------------------------------------------------------------------------
class OutAnswer(Out):
    revision: int
    orders: list[OutOrder]


def _gone(c, cid: str) -> list[dict]:
    return [dict(r) for r in c.db.execute("SELECT * FROM erp_withdrawn WHERE company_id = ? ORDER BY at, id", (cid,))]


def _out(cid: str, user, kind: str, everything: bool) -> OutAnswer:
    c = get_companies()
    with c.lock:
        ds, rev = read_company(c, user, cid)
        gone = [o for o in withdrawn(kind, _gone(c, cid)) if everything or o.change != "taken"]  # type: ignore[arg-type]
        orders = outbound(ds, kind, everything) + gone  # type: ignore[arg-type]
    pending = [o for o in orders if o.change != "taken"]
    if pending:
        items = [ItemResult(ref=o.id, status="applied", id=o.id, message=f"{o.change}, version {o.version}")
                 for o in pending]
        with c.lock:
            last = history(c, user, cid, limit=1, kind=kind)
            if not last or last[0].direction != "out" or [i.ref + i.message for i in last[0].items] != \
                    [i.ref + i.message for i in items]:
                log(c, cid, user.id, "out", kind, "", "sent",
                    f"{len(pending)} {kind.replace('_', ' ')}{'' if len(pending) == 1 else 's'} for the ERP to take", rev,
                    items)
    return OutAnswer(revision=rev, orders=orders)


@router.get("/erp/purchase-orders", response_model=OutAnswer)
def erp_purchase_orders(cid: str, user: Signed, all: bool = False) -> OutAnswer:
    """Purchase orders released for sending that the ERP has not taken, or that changed since it took them
    (``all``: every one)."""
    return _out(cid, user, "purchase_order", all)


@router.get("/erp/production-orders", response_model=OutAnswer)
def erp_production_orders(cid: str, user: Signed, all: bool = False) -> OutAnswer:
    """Firm production orders the ERP has not taken or that changed since."""
    return _out(cid, user, "production_order", all)


@router.get("/erp/transfer-orders", response_model=OutAnswer)
def erp_transfer_orders(cid: str, user: Signed, all: bool = False) -> OutAnswer:
    """Firm transfers between places the ERP has not taken or that changed since."""
    return _out(cid, user, "transfer_order", all)


@router.post("/erp/acknowledge", response_model=MessageAnswer)
def erp_acknowledge(cid: str, body: AckMessage, user: Signed) -> MessageAnswer:
    """The ERP took these orders: the number it gave each, and the version it took. An order listed as withdrawn
    (deleted here) is acknowledged with its ERP number when the ERP has closed its copy."""
    c = get_companies()
    with c.lock:
        rows = [r for r in _gone(c, cid) if not r["taken_at"]]
        generations = {(r["kind"], r["id"]): r["generation"] for r in rows}
        gone = {(o.kind, o.id): o for kind in ("purchase_order", "production_order", "transfer_order")
                for o in withdrawn(kind, rows)}
        answer = receive(c, user, cid, "acknowledgements", body.message_id, lambda ds: acknowledge(ds, body.orders, gone))
        closed = [(i.id, a.kind) for i, a in zip(answer.message.items, body.orders, strict=False)
                  if i.status == "applied" and (a.kind, a.id) in gone and "deleted here" in i.message]
        if closed and answer.message.status != "duplicate":
            c.db.executemany("UPDATE erp_withdrawn SET taken_at = ? WHERE company_id = ? AND kind = ? AND id = ? "
                             "AND generation = ? AND taken_at IS NULL",
                             [(answer.message.at, cid, k, oid, generations[(k, oid)]) for oid, k in closed])
        return answer


# ---- scheduled imports -----------------------------------------------------------------------------------------
@router.get("/imports", response_model=ImportJobs)
def list_imports(cid: str, user: Signed) -> ImportJobs:
    return imports.jobs(get_companies(), user, cid)


@router.post("/imports", response_model=ImportJobs)
def make_import(cid: str, body: imports.JobInput, user: Signed) -> ImportJobs:
    """A scheduled import; only an owner may make one (it reads from outside with the owner's rights)."""
    return imports.save_job(get_companies(), user, cid, body)


@router.put("/imports/{jid}", response_model=ImportJobs)
def change_import(cid: str, jid: str, body: imports.JobInput, user: Signed) -> ImportJobs:
    return imports.save_job(get_companies(), user, cid, body, jid)


@router.delete("/imports/{jid}", response_model=ImportJobs)
def remove_import(cid: str, jid: str, user: Signed) -> ImportJobs:
    return imports.delete_job(get_companies(), user, cid, jid)


@router.post("/imports/{jid}/run", response_model=list[MessageRow])
def run_import(cid: str, jid: str, user: Signed) -> list[MessageRow]:
    """Run an import now, whatever its schedule says."""
    c = get_companies()
    if jid not in {j.id for j in imports.jobs(c, user, cid).jobs}:
        raise CompanyError(f"no import {jid} in this company", 404)
    return imports.run_job(c, jid, user)


# ---- e-mail ----------------------------------------------------------------------------------------------------
@router.get("/mail", response_model=outbox.MailSetup)
def mail_setup(cid: str, user: Signed) -> outbox.MailSetup:
    return outbox.setup(get_companies(), user, cid)


@router.post("/mail", response_model=outbox.MailRow)
def send_mail(cid: str, body: outbox.MailInput, user: Signed) -> outbox.MailRow:
    """Send a document (a purchase order, an order confirmation, an invoice) from the server, with the page attached;
    only to addresses in the company's supplier and customer data or of its members."""
    return outbox.send_document(get_companies(), user, cid, body)


@router.get("/mail/sent", response_model=list[outbox.MailRow])
def mail_sent(cid: str, user: Signed, limit: int = 100, ref: str = "", before: int | None = None) -> list[outbox.MailRow]:
    return outbox.outbox(get_companies(), user, cid, limit, ref, before)


@router.put("/mail/reminders", response_model=outbox.MailSetup)
def mail_reminders(cid: str, body: outbox.ReminderSettings, user: Signed) -> outbox.MailSetup:
    """Worklist reminders: on which days and at what time each owner of open exceptions gets them by e-mail."""
    return outbox.set_reminders(get_companies(), user, cid, body)


@router.post("/mail/reminders/send", response_model=list[outbox.MailRow])
def mail_reminders_now(cid: str, user: Signed) -> list[outbox.MailRow]:
    """Send the worklist reminders now."""
    return outbox.remind_now(get_companies(), user, cid)


# ---- the log ---------------------------------------------------------------------------------------------------
@router.get("/messages", response_model=list[MessageRow])
def messages(cid: str, user: Signed, limit: int = 100, kind: str = "", status: str = "",
             before: int | None = None) -> list[MessageRow]:
    return history(get_companies(), user, cid, limit, kind, status, before)
