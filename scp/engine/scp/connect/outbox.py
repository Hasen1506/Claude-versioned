"""E-mail sent from the application (Phase Q), each one kept in the company's outbox.

* **Documents.** A purchase order or delivery schedule to the supplier, an order confirmation, invoice or credit note
  to the customer: the browser builds the document (the same page it prints) and its text; the server sends it from
  the server's address with the document attached, replies going to whoever sent it. It goes only to addresses the
  company knows (a supplier's or customer's e-mail in their purchasing or sales data, or a member), so the server
  never becomes anyone's way to mail strangers, and no more than :data:`DAILY` a day per company.
* **Worklist reminders.** On the days and at the time an owner sets, each person who owns open exceptions gets one
  e-mail with them: how many, which are past their time, the oldest first, and a link to the worklist. An owner is
  found by e-mail address or by a member's name.

Nothing is sent when the server has no mail set up (``SCP_SMTP_HOST``): the browser's own *E-mail* button opens the
planner's mail program instead.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any, Literal

from pydantic import Field

from ..companies import CompanyError, Companies, User, mail
from ..companies.store import EMAIL
from ..model.common import Model, Out
from ..model.tower import CATEGORIES
from .imports import _zone, next_run, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_outbox (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, at TEXT NOT NULL, user_id TEXT NOT NULL,
  kind TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '', recipients TEXT NOT NULL, cc TEXT NOT NULL DEFAULT '[]',
  subject TEXT NOT NULL, body TEXT NOT NULL, attachment TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS mail_outbox_by_company ON mail_outbox (company_id, seq);
CREATE TABLE IF NOT EXISTS mail_settings (
  company_id TEXT PRIMARY KEY, reminders INTEGER NOT NULL DEFAULT 0, at TEXT NOT NULL DEFAULT '08:00',
  weekdays TEXT NOT NULL DEFAULT '[0,1,2,3,4]', next_run TEXT, last_run TEXT, set_by TEXT
);
"""
DAILY = 500
MailKind = Literal["purchase_order", "delivery_schedule", "confirmation", "invoice", "credit_note", "reminder"]


class MailInput(Model):
    kind: Literal["purchase_order", "delivery_schedule", "confirmation", "invoice", "credit_note"]
    ref: str = Field(min_length=1, max_length=64, description="The document's number (PO-00001, SO-00003, INV-00002)")
    to: list[str] = Field(min_length=1, max_length=10)
    cc: list[str] = Field(default_factory=list, max_length=10)
    subject: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000, description="The e-mail's text")
    html: str = Field("", max_length=2_000_000, description="The document as a page, attached as <ref>.html")


class MailRow(Out):
    seq: int
    at: str
    by: str                        # a name, or "the server" for reminders
    kind: str
    ref: str
    to: list[str]
    cc: list[str]
    subject: str
    status: Literal["sent", "failed"]
    error: str
    attachment: str                # the attached file's name, if any


class ReminderSettings(Model):
    on: bool = False
    at: str = Field("08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], max_length=7)


class MailSetup(Out):
    mail: bool                     # the server sends mail
    sender: str                    # the address it sends from
    timezone: str
    reminders: ReminderSettings
    next_reminder: str | None
    last_reminder: str | None


def _ensure(c: Companies) -> None:
    if not getattr(c, "_outbox_ready", False):
        c.db.executescript(SCHEMA)
        c._outbox_ready = True  # type: ignore[attr-defined]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).replace(microsecond=0).isoformat()


def addresses(text: str) -> list[str]:
    """The e-mail addresses in a field (several may be separated by commas or semicolons)."""
    return [a.strip() for a in re.split(r"[,;\s]+", text or "") if EMAIL.match(a.strip())]


def known(c: Companies, cid: str) -> set[str]:
    """Addresses the company knows: its suppliers', its customers' and its members'."""
    r = c.db.execute("SELECT dataset FROM companies WHERE id = ?", (cid,)).fetchone()
    doc = json.loads(r["dataset"]) if r else {}
    out = {a.lower() for v in (doc.get("vendors") or []) + (doc.get("customers") or []) if isinstance(v, dict)
           for a in addresses(str(v.get("email") or ""))}
    out |= {m["email"].lower() for m in c.db.execute(
        "SELECT u.email FROM members m JOIN users u ON u.id = m.user_id WHERE m.company_id = ? AND u.kind != 'key'",
        (cid,))}
    return out


def _row(c: Companies, r: Any) -> MailRow:
    return MailRow(seq=r["seq"], at=r["at"], by="the server" if r["user_id"] == "" else c._name(r["user_id"]),
                   kind=r["kind"], ref=r["ref"], to=json.loads(r["recipients"]), cc=json.loads(r["cc"]),
                   subject=r["subject"], status=r["status"], error=r["error"], attachment=r["attachment"])


def _send(c: Companies, cid: str, uid: str, kind: str, ref: str, to: list[str], cc: list[str], subject: str, text: str,
          reply_to: str = "", html: str = "", filename: str = "") -> MailRow:
    msg = EmailMessage()
    msg["From"] = mail.from_address()
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="scp.local")
    msg.set_content(text)
    if html:
        msg.add_attachment(html.encode("utf-8"), maintype="text", subtype="html", filename=filename)
    status, error = "sent", ""
    try:
        mail.deliver(msg)
    except Exception as e:  # noqa: BLE001 - the outbox says why
        status, error = "failed", (str(e) or type(e).__name__)[:300]
    cur = c.db.execute("INSERT INTO mail_outbox (company_id, at, user_id, kind, ref, recipients, cc, subject, body, "
                       "attachment, status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (cid, _iso(_now()), uid, kind, ref, json.dumps(to), json.dumps(cc), subject, text,
                        filename if html else "", status, error))
    return _row(c, c.db.execute("SELECT * FROM mail_outbox WHERE seq = ?", (cur.lastrowid,)).fetchone())


def send_document(c: Companies, user: User, cid: str, body: MailInput) -> MailRow:
    """Send a document from the server, to addresses the company knows."""
    if not mail.mail_on():
        raise CompanyError("this server sends no mail (it has no mail server set up): use E-mail to open your own "
                           "mail program", 409)
    with c.lock:
        _ensure(c)
        c._need(user, cid, "owner", "planner")
        if c.is_key(user):
            raise CompanyError("a key sends data, not e-mail: send documents from the application", 403)
        ok = known(c, cid)
        bad = [a for a in [*body.to, *body.cc] if not EMAIL.match(a.strip()) or a.strip().lower() not in ok]
        if bad:
            raise CompanyError(f"{', '.join(bad)} {'is' if len(bad) == 1 else 'are'} not an address of this company's "
                               "suppliers, customers or members: add it to their purchasing or sales data first (and "
                               "let the change save)", 422)
        day = _iso(_now())[:10]
        n = c.db.execute("SELECT COUNT(*) FROM mail_outbox WHERE company_id = ? AND at >= ?", (cid, day)).fetchone()[0]
        if n >= DAILY:
            raise CompanyError(f"this company has sent {n} e-mails today, the most a day; send the rest tomorrow", 429)
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", body.ref) + ".html"
        return _send(c, cid, user.id, body.kind, body.ref, [a.strip() for a in body.to], [a.strip() for a in body.cc],
                     body.subject, body.text, reply_to=formataddr((user.name, user.email)), html=body.html,
                     filename=name)


def outbox(c: Companies, user: User, cid: str, limit: int = 100, ref: str = "", before: int | None = None) -> list[MailRow]:
    with c.lock:
        _ensure(c)
        c._need(user, cid)
        q, args = "SELECT * FROM mail_outbox WHERE company_id = ?", [cid]
        if ref:
            q += " AND ref = ?"
            args.append(ref)
        if before:
            q += " AND seq < ?"
            args.append(before)
        q += " ORDER BY seq DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        return [_row(c, r) for r in c.db.execute(q, args)]


# ------------------------------------------------------------------------------------------------ reminders
def _setup(c: Companies, cid: str) -> MailSetup:
    r = c.db.execute("SELECT * FROM mail_settings WHERE company_id = ?", (cid,)).fetchone()
    rs = ReminderSettings(on=bool(r["reminders"]), at=r["at"], weekdays=json.loads(r["weekdays"])) if r else ReminderSettings()
    return MailSetup(mail=mail.mail_on(), sender=mail.from_address(), timezone=timezone(), reminders=rs,
                     next_reminder=r["next_run"] if r else None, last_reminder=r["last_run"] if r else None)


def setup(c: Companies, user: User, cid: str) -> MailSetup:
    with c.lock:
        _ensure(c)
        c._need(user, cid)
        return _setup(c, cid)


def _next(rs: ReminderSettings, after: dt.datetime) -> str | None:
    if not rs.on or not rs.weekdays:
        return None
    t = after
    for _ in range(8):
        t = next_run("day", rs.at, 0, t)
        if t.astimezone(_zone()).weekday() in rs.weekdays:
            return _iso(t)
    return None


def set_reminders(c: Companies, user: User, cid: str, rs: ReminderSettings, now: dt.datetime | None = None) -> MailSetup:
    now = now or _now()
    rs = rs.model_copy(update={"weekdays": sorted({d for d in rs.weekdays if 0 <= d <= 6})})
    with c.lock:
        _ensure(c)
        c._need(user, cid, "owner")
        c.db.execute("INSERT INTO mail_settings (company_id, reminders, at, weekdays, next_run, set_by) VALUES "
                     "(?, ?, ?, ?, ?, ?) ON CONFLICT (company_id) DO UPDATE SET reminders = excluded.reminders, "
                     "at = excluded.at, weekdays = excluded.weekdays, next_run = excluded.next_run, set_by = excluded.set_by",
                     (cid, int(rs.on), rs.at, json.dumps(rs.weekdays), _next(rs, now), user.id))
        days = ", ".join(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[d] for d in rs.weekdays)
        c._log(cid, None, user.id, "member", f"worklist reminders {'on: ' + days + ' at ' + rs.at if rs.on else 'off'}")
        return _setup(c, cid)


def _owners(c: Companies, cid: str) -> dict[str, str]:
    """Each member's name and e-mail (lower case) → their e-mail."""
    out: dict[str, str] = {}
    for m in c.db.execute("SELECT u.email, u.name FROM members m JOIN users u ON u.id = m.user_id WHERE "
                          "m.company_id = ? AND u.kind != 'key'", (cid,)):
        out[m["email"].lower()] = m["email"]
        if m["name"]:
            out.setdefault(m["name"].strip().lower(), m["email"])
    return out


def _items(c: Companies, cid: str) -> tuple[list[dict], str, dict[str, int]]:
    """The company's open worklist items (as the last look at the worklist left them), its name and SLA days."""
    r = c.db.execute("SELECT name, dataset FROM companies WHERE id = ?", (cid,)).fetchone()
    doc = json.loads(r["dataset"]) if r else {}
    settings = doc.get("settings") or {}
    sla = {**{"coverage": 2, "capacity": 5, "inventory": 10, "orders": 3, "delivery": 1, "demand": 7},
           **((doc.get("tower") or {}).get("sla_days") or {})}
    try:
        as_of = dt.date.fromisoformat(settings.get("planning_start", ""))
    except ValueError:
        as_of = _now().date()
    try:
        rows = c.db.execute("SELECT * FROM tower_items WHERE company = ? AND status IN ('open', 'acknowledged')",
                            (f"@{cid}",)).fetchall()
    except Exception:  # noqa: BLE001 - nobody has looked at the worklist yet
        rows = []
    items = []
    for x in rows:
        age = max(0, (as_of - dt.date.fromisoformat(x["first_seen"])).days)
        s = sla.get(x["category"])
        items.append({"owner": x["owner"], "category": x["category"], "severity": x["severity"], "message": x["message"],
                      "age": age, "over": age - s if s is not None and age > s else 0, "status": x["status"]})
    return items, settings.get("company_name") or (r["name"] if r else "") or cid, sla


def remind(c: Companies, cid: str, now: dt.datetime | None = None) -> list[MailRow]:
    """Send each owner of open exceptions one e-mail with them; returns what was sent (or failed)."""
    now = now or _now()
    with c.lock:
        _ensure(c)
        items, company, _ = _items(c, cid)
        who = _owners(c, cid)
        by: dict[str, list[dict]] = {}
        for it in items:
            o = it["owner"].strip()
            to = o if EMAIL.match(o) else who.get(o.lower())
            if to:
                by.setdefault(to, []).append(it)
        link = mail.public_url()
        out = []
        for to, mine in sorted(by.items()):
            mine.sort(key=lambda x: (-x["over"], -x["age"], CATEGORIES.index(x["category"])
                                     if x["category"] in CATEGORIES else 99))
            late = sum(1 for x in mine if x["over"])
            lines = [f"- {x['message']} ({x['category']}, open {x['age']} day{'' if x['age'] == 1 else 's'}"
                     + (f", {x['over']} past its time" if x["over"] else "") + ")" for x in mine[:50]]
            if len(mine) > 50:
                lines.append(f"… and {len(mine) - 50} more")
            text = "\n".join([
                "Hello,", "",
                f"You own {len(mine)} open exception{'' if len(mine) == 1 else 's'} on the worklist of {company}"
                + (f", {late} past {'its' if late == 1 else 'their'} time:" if late else ":"), "",
                *lines, "",
                f"Open the worklist: {link}/#/tower" if link else "Open the worklist on the Performance page.", "",
                "You get this because your company's owner switched worklist reminders on.",
            ])
            subject = f"Worklist: {len(mine)} open" + (f", {late} past their time" if late else "") + f" · {company}"
            out.append(_send(c, cid, "", "reminder", "", [to], [], subject, text))
        r = c.db.execute("SELECT * FROM mail_settings WHERE company_id = ?", (cid,)).fetchone()
        if r is not None:
            rs = ReminderSettings(on=bool(r["reminders"]), at=r["at"], weekdays=json.loads(r["weekdays"]))
            c.db.execute("UPDATE mail_settings SET last_run = ?, next_run = ? WHERE company_id = ?",
                         (_iso(now), _next(rs, now), cid))
        return out


def remind_now(c: Companies, user: User, cid: str) -> list[MailRow]:
    if not mail.mail_on():
        raise CompanyError("this server sends no mail (it has no mail server set up)", 409)
    with c.lock:
        _ensure(c)
        c._need(user, cid, "owner")
    return remind(c, cid)


def remind_due(c: Companies, now: dt.datetime | None = None) -> dict[str, list[MailRow]]:
    """Send the reminders whose time has come (none when the server sends no mail)."""
    if not mail.mail_on():
        return {}
    now = now or _now()
    with c.lock:
        _ensure(c)
        due = [r["company_id"] for r in c.db.execute(
            "SELECT s.company_id FROM mail_settings s JOIN companies co ON co.id = s.company_id WHERE s.reminders = 1 "
            "AND co.deleted = 0 AND s.next_run IS NOT NULL AND s.next_run <= ?", (_iso(now),))]
    return {cid: remind(c, cid, now) for cid in due}
