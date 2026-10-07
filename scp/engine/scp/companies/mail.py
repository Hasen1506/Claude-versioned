"""E-mail the server sends: a password reset link (Phase L); documents to suppliers and customers and the worklist's
reminders (Phase Q, :mod:`scp.connect.outbox`). Set up by the server's environment:

* ``SCP_SMTP_HOST`` (no host: the server sends no mail, and a reset link comes from a company owner or the server's
  administrator instead), ``SCP_SMTP_PORT`` (587), ``SCP_SMTP_USER``, ``SCP_SMTP_PASSWORD``, ``SCP_SMTP_FROM``
  (default the user), ``SCP_SMTP_TLS`` (``starttls``, the default, ``ssl`` or ``none``);
* ``SCP_PUBLIC_URL``: where people open the application (``https://plan.example.com``), for links in mail.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from collections.abc import Callable

Sender = Callable[[str, str, str], None]


def mail_on() -> bool:
    return bool(os.environ.get("SCP_SMTP_HOST", "").strip())


def public_url() -> str:
    return os.environ.get("SCP_PUBLIC_URL", "").strip().rstrip("/")


def from_address() -> str:
    return os.environ.get("SCP_SMTP_FROM", "").strip() or os.environ.get("SCP_SMTP_USER", "").strip()


def _smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = from_address()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    deliver(msg)          # the module's deliver, so what tests replace catches account mail too


def _deliver(msg: EmailMessage) -> None:
    host = os.environ["SCP_SMTP_HOST"].strip()
    tls = os.environ.get("SCP_SMTP_TLS", "starttls").strip().lower()
    port = int(os.environ.get("SCP_SMTP_PORT", "465" if tls == "ssl" else "587"))
    user, password = os.environ.get("SCP_SMTP_USER", ""), os.environ.get("SCP_SMTP_PASSWORD", "")
    if not msg["From"]:
        msg["From"] = from_address()
    ctx = ssl.create_default_context()
    with (smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) if tls == "ssl"
          else smtplib.SMTP(host, port, timeout=20)) as s:
        if tls == "starttls":
            s.starttls(context=ctx)
        if user:
            s.login(user, password)
        s.send_message(msg)


# tests replace these to see what would be sent
send: Sender = _smtp
deliver: Callable[[EmailMessage], None] = _deliver
