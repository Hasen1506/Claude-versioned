"""Messages to and from other systems, applied to the company kept on the server and logged (Phase Q).

A message (an ERP's orders, its stock, a scheduled import's file) changes the company's latest save: it is read, the
change made, and saved as a new revision by whoever sent it (an integration key's account is named after the key), so
it is in the company's history, can be put back, and a planner's window merges it in on its next save as it would a
colleague's. Records set aside as unfinished stay as they are: the save carries only what the message changed.

Every message is logged with what became of each item. A message sent with an id it was sent with before is not
applied again: the first answer is given back (an ERP that did not hear the answer sends it again).
"""
from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any, Literal

from ..companies import CAN_EDIT, CompanyError, Companies, User
from ..companies.patch import PatchError, apply_patch, make_patch
from ..model import Dataset
from ..model.common import Out
from ..validate.lenient import lenient_checked
from .erp import ItemResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, at TEXT NOT NULL, user_id TEXT NOT NULL,
  direction TEXT NOT NULL, kind TEXT NOT NULL, message_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
  summary TEXT NOT NULL, revision INTEGER, items TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS messages_by_company ON messages (company_id, seq);
CREATE INDEX IF NOT EXISTS messages_by_id ON messages (company_id, kind, message_id);
"""

MessageStatus = Literal["applied", "partly", "refused", "unchanged", "duplicate", "sent", "failed"]


class MessageRow(Out):
    """A message logged: what came in (or went out), from whom, and what became of each item."""
    seq: int
    at: str
    by: str                        # a name: a person, or a key ("SAP (key)")
    direction: Literal["in", "out"]
    kind: str                      # orders, stock, postings, records:<list>, acknowledgements, purchase_orders, …
    message_id: str
    status: MessageStatus
    summary: str
    revision: int | None = None    # the company's revision it made
    source: str = ""               # a scheduled import: the job and the file or address it read
    items: list[ItemResult] = []


class MessageAnswer(Out):
    """The answer to a message: what became of it and of each item."""
    message: MessageRow
    revision: int                  # the company's latest revision after it
    held: str | None = None        # master data held for a second person's approval (the company asks for it)


def _ensure(c: Companies) -> None:
    if not getattr(c, "_messages_ready", False):
        c.db.executescript(SCHEMA)
        c._messages_ready = True  # type: ignore[attr-defined]


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _status(items: list[ItemResult]) -> MessageStatus:
    st = {i.status for i in items}
    if not items or st <= {"unchanged", "duplicate"}:
        return "duplicate" if st == {"duplicate"} else "unchanged"
    if "applied" in st:
        return "partly" if "refused" in st else "applied"
    return "refused"


def _summary(kind: str, items: list[ItemResult]) -> str:
    n = {s: sum(i.status == s for i in items) for s in ("applied", "unchanged", "duplicate", "refused")}
    words = {"applied": "taken", "unchanged": "as here already", "duplicate": "sent before", "refused": "refused"}
    bits = [f"{v} {words[k]}" for k, v in n.items() if v]
    what = kind.replace("records:", "").replace("_", " ")
    return f"{len(items)} {what}: " + ", ".join(bits) if bits else f"no {what}"


def _row(c: Companies, r: Any, detail: bool = True) -> MessageRow:
    return MessageRow(seq=r["seq"], at=r["at"], by=c._name(r["user_id"]), direction=r["direction"], kind=r["kind"],
                      message_id=r["message_id"], status=r["status"], summary=r["summary"], revision=r["revision"],
                      source=r["source"],
                      items=[ItemResult(**i) for i in json.loads(r["items"])] if detail else [])


def log(c: Companies, cid: str, uid: str, direction: str, kind: str, message_id: str, status: str, summary: str,
        revision: int | None, items: list[ItemResult], source: str = "") -> MessageRow:
    """Log a message (the lock is held by the caller or not needed)."""
    _ensure(c)
    cur = c.db.execute("INSERT INTO messages (company_id, at, user_id, direction, kind, message_id, status, summary, "
                       "revision, items, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (cid, _now(), uid, direction, kind, message_id, status, summary, revision,
                        json.dumps([i.model_dump(mode="json") for i in items]), source))
    return _row(c, c.db.execute("SELECT * FROM messages WHERE seq = ?", (cur.lastrowid,)).fetchone())


def history(c: Companies, user: User, cid: str, limit: int = 100, kind: str = "", status: str = "",
            before: int | None = None) -> list[MessageRow]:
    with c.lock:
        _ensure(c)
        c._need(user, cid)
        q, args = "SELECT * FROM messages WHERE company_id = ?", [cid]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        if status:
            q += " AND status = ?"
            args.append(status)
        if before:
            q += " AND seq < ?"
            args.append(before)
        q += " ORDER BY seq DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        return [_row(c, r) for r in c.db.execute(q, args)]


def read_company(c: Companies, user: User, cid: str) -> tuple[Dataset, int]:
    """The company's latest save, read for a message that only looks (orders for the ERP to take)."""
    with c.lock:
        c._need(user, cid)
        r = c.db.execute("SELECT dataset, revision FROM companies WHERE id = ?", (cid,)).fetchone()
        doc = json.loads(r["dataset"])
    ds, _, _ = lenient_checked(doc)
    return ds, r["revision"]


def changed_doc(doc: dict, before: Dataset, after: Dataset, aside_lists: set[str]) -> dict:
    """``doc`` (the company as saved) with what changed from ``before`` to ``after`` (both read from it): records
    set aside when it was read stay where they are."""
    names = {f for f in Dataset.model_fields if getattr(before, f) is not getattr(after, f)
             and getattr(before, f) != getattr(after, f)}
    if not names:
        return doc
    a = before.model_dump(mode="json", by_alias=True, include=names)
    b = after.model_dump(mode="json", by_alias=True, include=names)
    patch = make_patch(a, b)
    patch.pop("sizes", None)
    whole = set(patch.get("set") or {}) & aside_lists
    if whole:
        raise CompanyError(f"the company has unfinished records in {', '.join(sorted(whole))} that a change made here "
                           "would lose: finish or remove them first", 409)
    try:
        return apply_patch(doc, patch)
    except PatchError as e:
        raise CompanyError(f"the change does not fit the company as saved: {e}", 409) from None


def receive(c: Companies, user: User, cid: str, kind: str, message_id: str,
            change: Callable[[Dataset], tuple[Dataset, list[ItemResult]]], source: str = "") -> MessageAnswer:
    """Apply a message to the company's latest save and log it; a message id seen before gives the first answer."""
    message_id = (message_id or "").strip()[:100]
    with c.lock:
        _ensure(c)
        c._need(user, cid, *CAN_EDIT)
        if message_id:
            seen = c.db.execute("SELECT * FROM messages WHERE company_id = ? AND kind = ? AND message_id = ? AND "
                                "direction = 'in' ORDER BY seq LIMIT 1", (cid, kind, message_id)).fetchone()
            if seen is not None:
                first = _row(c, seen)
                rev = c.db.execute("SELECT revision FROM companies WHERE id = ?", (cid,)).fetchone()[0]
                again = first.model_copy(update={"status": "duplicate",
                                                 "summary": f"sent before (message {message_id}, {first.at}): "
                                                            f"{first.summary}"})
                return MessageAnswer(message=again, revision=rev)
        r = c.db.execute("SELECT dataset, revision FROM companies WHERE id = ?", (cid,)).fetchone()
        doc = json.loads(r["dataset"])
        ds, aside, _ = lenient_checked(doc)
        new, items = change(ds)
        status = _status(items)
        summary = _summary(kind, items)
        rev, held = r["revision"], None
        if any(i.status == "applied" for i in items):
            after = changed_doc(doc, ds, new, {a.collection for a in aside})
            rep = c.save(user, cid, after, r["revision"], action="received",
                         note=f"{kind.replace('_', ' ')} from {c._name(user.id)}"
                              + (f" (message {message_id})" if message_id else ""))
            rev = rep.meta.revision
            if rep.held is not None:
                held = rep.held.summary
                summary += f"; master data waiting for approval: {held}"
        row = log(c, cid, user.id, "in", kind, message_id, status, summary,
                  rev if rev != r["revision"] else None, items, source)
        return MessageAnswer(message=row, revision=rev, held=held)


def write(c: Companies, user: User, cid: str, change: Callable[[Dataset], tuple[Dataset, Any]], note: str) -> tuple[Any, int]:
    """Make a change to the company's latest save outside a message (the server's own: a reminder sent, an e-mail
    recorded on its order) and save it; returns what ``change`` returned and the revision."""
    with c.lock:
        c._need(user, cid, *CAN_EDIT)
        r = c.db.execute("SELECT dataset, revision FROM companies WHERE id = ?", (cid,)).fetchone()
        doc = json.loads(r["dataset"])
        ds, aside, _ = lenient_checked(doc)
        new, out = change(ds)
        after = changed_doc(doc, ds, new, {a.collection for a in aside})
        if after is doc:
            return out, r["revision"]
        rep = c.save(user, cid, after, r["revision"], action="saved", note=note)
        return out, rep.meta.revision
