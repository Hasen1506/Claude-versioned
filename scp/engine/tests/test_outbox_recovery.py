"""Crash-boundary mail recovery uses a local sink; no real mail is sent."""
from __future__ import annotations

import pytest

from scp.companies import get_companies, mail
from scp.connect import outbox

from .test_connections import client, h, mailing, po_mail, setup, verify, with_contacts
from .test_backup_postgres import pg_databases as pg_databases


def test_interrupted_delivery_is_visible_and_retried_once_with_the_original_mime(monkeypatch):
    owner, cid, key = setup(with_contacts())
    sent = mailing(monkeypatch)
    monkeypatch.setenv("SCP_SIGNUP", "invite")
    verify(owner)
    c = get_companies()
    user = c.whoami(owner)

    def crash_after_acceptance(msg):
        sent.append(msg)
        raise SystemExit("simulate worker death after SMTP acceptance, before result commit")

    monkeypatch.setattr(mail, "deliver", crash_after_acceptance)
    with pytest.raises(SystemExit):
        outbox.send_document(c, user, cid, outbox.MailInput.model_validate(po_mail()))
    rows = client.get(f"/api/companies/{cid}/mail/sent", headers=h(owner))
    assert rows.status_code == 200 and rows.json()[0]["status"] == "sending"
    seq = rows.json()[0]["seq"]
    payload = c.db.execute("SELECT payload FROM mail_payloads WHERE mail_seq = ?", (seq,)).fetchone()[0]
    assert b"Purchase order PO-00001" in bytes(payload) and b"Message-ID:" in bytes(payload)
    retry = f"/api/companies/{cid}/mail/{seq}/retry"
    assert client.post(retry, headers=h(owner), json={}).status_code == 409
    ack = {"acknowledge_possible_duplicate": True}
    assert client.post(retry, headers=h(owner), json=ack).status_code == 409  # not while the worker could be running
    with c.lock:
        c.db.execute("UPDATE mail_outbox SET at = '2026-01-01T00:00:00+00:00' WHERE seq = ?", (seq,))
    assert client.post(retry, headers=h(key), json=ack).status_code == 403
    monkeypatch.setattr(mail, "deliver", sent.append)
    response = client.post(retry, headers=h(owner), json=ack)
    assert response.status_code == 200 and response.json()["status"] == "sent", response.text
    assert response.json()["seq"] != seq
    assert len(sent) == 2 and sent[0]["Message-ID"] == sent[1]["Message-ID"]
    assert [a.get_content() for a in sent[0].iter_attachments()] == [a.get_content() for a in sent[1].iter_attachments()]
    assert client.post(retry, headers=h(owner), json=ack).json()["seq"] == response.json()["seq"]
    assert len(sent) == 2  # replaying the recovery request has no second SMTP effect
    assert c.db.execute("SELECT status FROM mail_outbox WHERE seq = ?", (seq,)).fetchone()[0] == "unknown"


def test_message_preparation_failure_is_recorded_without_an_external_effect(monkeypatch):
    owner, cid, _ = setup(with_contacts())
    sent = mailing(monkeypatch)
    monkeypatch.setenv("SCP_SIGNUP", "invite")
    verify(owner)

    def fail(*a, **kw):
        raise ValueError("injected MIME failure")

    monkeypatch.setattr(outbox, "_message", fail)
    response = client.post(f"/api/companies/{cid}/mail", headers=h(owner), json=po_mail())
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert "preparation" in response.json()["error"] and not sent


def test_postgres_backup_restore_keeps_exact_outbound_payload_and_retry_identity(pg_databases, tmp_path, monkeypatch):
    from scp.backup import backup_postgres
    from scp.migrate_postgres import migrate
    from scp.companies.store import Companies
    from scp.versions.store import Store
    source, destination = pg_databases(), pg_databases()
    c = Companies(Store(source))
    session = c.signup("recovery@example.test", "Recovery", "local-test-WINTER-river-3719")
    cid = c.create(session.user, with_contacts()).id
    with c.lock:
        outbox._ensure(c)
        original = outbox._record(c, cid, session.user.id, "invoice", "INV-1", ["orders@sharma.example"], [], "Invoice", "Body")
        retry = outbox._record(c, cid, session.user.id, "invoice", "INV-1", ["orders@sharma.example"], [], "Invoice", "Body")
        payload = b"Message-ID: <stable-recovery@example.test>\r\nSubject: Invoice\r\n\r\nBody\r\n"
        c.db.execute("INSERT INTO mail_payloads (mail_seq, payload, attachments) VALUES (?, ?, ?)", (retry, payload, "invoice.pdf"))
        c.db.execute("INSERT INTO mail_retries (original_seq, retry_seq) VALUES (?, ?)", (original, retry))
    artifact = backup_postgres(source, tmp_path / "backups")
    monkeypatch.setenv("DATABASE_URL", destination)
    migrate(artifact, apply=True)
    restored = Companies(Store(destination))
    assert restored.db.execute("SELECT payload FROM mail_payloads WHERE mail_seq = ?", (retry,)).fetchone()[0] == payload
    assert restored.db.execute("SELECT retry_seq FROM mail_retries WHERE original_seq = ?", (original,)).fetchone()[0] == retry
    restored.db.close()
    c.db.close()
