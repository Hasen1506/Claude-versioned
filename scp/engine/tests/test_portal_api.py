"""Enterprise 7.2 over HTTP: a planner makes a link for Hindalco copper; the supplier, not signed in, sees their one
sent order, answers it and sends dispatch advice; each step is saved to the company as the link maker's change. The
link stops working when withdrawn, expired, or its maker loses the right to change the company."""
from __future__ import annotations

import datetime as dt
import json
from datetime import date

from fastapi.testclient import TestClient

from scp.api.app import app
from scp.companies import get_companies
from scp.purchasing import approve, create_one_off_po, send

from .factory import load_example
from .test_portal import _despatch, _response

PW = "kaveri-pumps-chennai-2026"
client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})
anon = TestClient(app)


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signup(email: str, name: str) -> str:
    r = client.post("/api/auth/signup", json={"email": email, "name": name, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _kaveri_with_order():
    ds, rep = create_one_off_po(load_example("kitchenware_network"), "PIR-CU", 2000, due_date=date(2026, 10, 12))
    po = rep.created[0].id
    for who in ("buyer", "head of buying", "director"):
        if not ds.purchase_order_by_id[po].approved:
            ds, _ = approve(ds, po, who, date(2026, 9, 28))
    ds, _ = send(ds, po, date(2026, 9, 28))
    # and one for another supplier, sent too: never on the copper link
    ds, rep2 = create_one_off_po(ds, "PIR-STAMP", 1000, due_date=date(2026, 10, 12))
    ds, _ = send(ds, rep2.created[0].id, date(2026, 9, 28))
    return ds, po, next(r.id for r in ds.receipts if r.po == po), rep2.created[0].id


def setup():
    asha = signup("asha@kaveri.example", "Asha")
    ds, po, line, other = _kaveri_with_order()
    r = client.post("/api/companies", headers=h(asha), json={"dataset": ds.model_dump(mode="json")})
    assert r.status_code == 200, r.text
    return asha, r.json()["id"], po, line, other


def _stored(token: str, cid: str) -> dict:
    return json.loads(client.get(f"/api/companies/{cid}", headers=h(token)).content)


def test_the_supplier_answers_and_dispatches_on_the_link_and_the_company_is_saved(monkeypatch):
    monkeypatch.setenv("SCP_REQUIRE_SIGNIN", "1")
    asha, cid, po, line, other = setup()
    r = client.post(f"/api/companies/{cid}/portal-links", headers=h(asha), json={"supplier": "SUP-COPPER"})
    assert r.status_code == 200, r.text
    link = r.json()
    token = link["token"]
    assert token.startswith("scp_sp_") and link["status"] == "live" and link["created_by"] == "Asha"
    assert (dt.datetime.fromisoformat(link["expires_at"]) - dt.datetime.fromisoformat(link["created_at"])).days == 90
    # the secret is shown once and kept only as a hash
    listed = client.get(f"/api/companies/{cid}/portal-links", headers=h(asha)).json()
    assert listed[0]["token"] is None and listed[0]["prefix"] == token[:12]
    assert token not in get_companies().db.execute("SELECT * FROM portal_links").fetchone()

    # the supplier, not signed in, on a server that needs signing in
    me = {"X-Portal-Token": token}
    v = anon.get("/api/portal", headers=me)
    assert v.status_code == 200, v.text
    v = v.json()
    assert v["supplier_name"] == "Hindalco copper (Silvassa)" and v["company"].startswith("Kaveri Kitchenware")
    assert [x["order"] for x in v["lines"]] == [line]                  # not the lamination order
    assert v["lines"][0]["status"] == "to confirm"
    assert anon.get(f"/api/portal/order?po={other}", headers=me).status_code == 404
    xml = anon.get(f"/api/portal/order?po={po}", headers=me)
    assert xml.status_code == 200 and f"<cbc:ID>{line}</cbc:ID>" in xml.text

    rev = _stored(asha, cid)["meta"]["revision"]
    a = anon.post("/api/portal/respond", headers=me, json={"reference": "SC/OC/3381", "lines": [
        {"order": line, "parts": [{"date": "2026-10-09", "qty": 1200}, {"date": "2026-10-16", "qty": 800}]}]})
    assert a.status_code == 200, a.text
    assert a.json()["view"]["lines"][0]["status"] == "changed"
    doc = _stored(asha, cid)
    assert doc["meta"]["revision"] == rev + 1
    saved = next(x for x in doc["dataset"]["receipts"] if x["id"] == line)
    assert saved["confirmed_qty"] == 2000 and [c["qty"] for c in saved["confirmations"]] == [1200, 800]
    hist = client.get(f"/api/companies/{cid}/history", headers=h(asha)).json()
    assert "order confirmation from Hindalco copper (Silvassa) on the supplier portal (link L0001)" in hist[0]["summary"]
    assert hist[0]["user"] == "Asha"

    # their system sends a DespatchAdvice
    d = anon.post("/api/portal/message", headers={**me, "Content-Type": "application/xml"},
                  content=_despatch(po, line).encode())
    assert d.status_code == 200, d.text
    assert d.json()["id"] == "ASN-00001"
    n = _stored(asha, cid)["dataset"]["shipping_notices"][0]
    assert (n["source"], n["arrives_on"], n["lines"][0]["batch"]) == ("message", "2026-10-09", "CU-7781")
    # and from the portal itself the rest, arriving with the lane's 2 days
    d2 = anon.post("/api/portal/dispatch", headers=me, json={"lines": [{"order": line}], "shipped_on": "2026-10-14",
                                                             "reference": "LR 40590"})
    assert d2.status_code == 200, d2.text
    n2 = _stored(asha, cid)["dataset"]["shipping_notices"][1]
    assert (n2["source"], n2["arrives_on"], n2["lines"][0]["qty"]) == ("portal", "2026-10-16", 800)
    # a message about another supplier's order is refused, and nothing is saved
    rev = _stored(asha, cid)["meta"]["revision"]
    bad = anon.post("/api/portal/message", headers=me, content=_response(other, "", "AP").encode())
    assert bad.status_code == 409 and "another supplier" in bad.json()["detail"]
    assert _stored(asha, cid)["meta"]["revision"] == rev
    assert client.get(f"/api/companies/{cid}/portal-links", headers=h(asha)).json()[0]["uses"] == 3


def test_a_link_stops_working_withdrawn_expired_or_with_its_makers_rights(monkeypatch):
    asha, cid, po, line, other = setup()
    ravi = signup("ravi@kaveri.example", "Ravi")
    r = client.post(f"/api/companies/{cid}/members", headers=h(asha), json={"email": "ravi@kaveri.example",
                                                                             "role": "planner"})
    invite = next(m["invite_link"] for m in r.json() if m["email"] == "ravi@kaveri.example")
    c = get_companies()
    c.accept_invite(c.whoami(ravi), token=invite.rsplit("/", 1)[1])
    nope = "this link does not work"
    assert nope in anon.get("/api/portal", headers={"X-Portal-Token": "scp_sp_guess"}).json()["detail"]
    assert anon.get("/api/portal").status_code == 401
    # not a supplier, or a viewer: no link
    assert client.post(f"/api/companies/{cid}/portal-links", headers=h(asha),
                       json={"supplier": "PLT-PUNE"}).status_code == 422

    def make(token: str) -> str:
        r = client.post(f"/api/companies/{cid}/portal-links", headers=h(token), json={"supplier": "SUP-COPPER"})
        assert r.status_code == 200, r.text
        return r.json()["token"]
    t1, t2, t3 = make(asha), make(asha), make(ravi)
    for t in (t1, t2, t3):
        assert anon.get("/api/portal", headers={"X-Portal-Token": t}).status_code == 200
    # withdrawn
    lid = next(x["id"] for x in client.get(f"/api/companies/{cid}/portal-links", headers=h(asha)).json()
               if x["prefix"] == t1[:12])
    after = client.delete(f"/api/companies/{cid}/portal-links/{lid}", headers=h(asha)).json()
    assert next(x for x in after if x["id"] == lid)["status"] == "withdrawn"
    assert anon.get("/api/portal", headers={"X-Portal-Token": t1}).status_code == 401
    assert anon.post("/api/portal/respond", headers={"X-Portal-Token": t1},
                     json={"lines": [{"order": line}]}).status_code == 401
    # expired
    c.db.execute("UPDATE portal_links SET expires_at = ? WHERE prefix = ?", ("2020-01-01T00:00:00+00:00", t2[:12]))
    assert anon.get("/api/portal", headers={"X-Portal-Token": t2}).status_code == 401
    assert next(x for x in client.get(f"/api/companies/{cid}/portal-links", headers=h(asha)).json()
                if x["prefix"] == t2[:12])["status"] == "expired"
    # Ravi made t3 and is made a viewer: his link stops with his right to change the company
    assert client.post(f"/api/companies/{cid}/members", headers=h(asha),
                       json={"email": "ravi@kaveri.example", "role": "viewer"}).status_code == 200
    assert c.role(c.whoami(ravi), cid) == "viewer"
    assert anon.get("/api/portal", headers={"X-Portal-Token": t3}).status_code == 401
    assert client.post(f"/api/companies/{cid}/portal-links", headers=h(ravi),
                       json={"supplier": "SUP-COPPER"}).status_code == 403


def test_buying_records_a_step_and_reads_a_message_on_the_working_copy():
    ds, po, line, other = _kaveri_with_order()
    doc = ds.model_dump(mode="json")
    v = client.post("/api/portal/view", json={"dataset": doc, "supplier": "SUP-COPPER"}).json()
    assert [x["order"] for x in v["lines"]] == [line]
    r = client.post("/api/portal/act", json={"dataset": doc, "action": "message", "xml": _despatch(po, line)})
    assert r.status_code == 200, r.text
    doc = r.json()["dataset"]
    assert doc["shipping_notices"][0]["id"] == "ASN-00001"
    r = client.post("/api/portal/act", json={"dataset": doc, "action": "receive", "id": "ASN-00001",
                                             "date": "2026-10-09"})
    assert r.status_code == 200, r.text
    assert "ASN-00001 received" in r.json()["message"]
    doc = r.json()["dataset"]
    assert doc["shipping_notices"][0]["received_on"] == "2026-10-09"
    assert client.post("/api/portal/act", json={"dataset": doc, "action": "cancel", "id": "ASN-00001"}).status_code == 409
    x = client.post("/api/portal/order-xml", json={"dataset": doc, "po": po})
    assert x.status_code == 200 and x.headers["content-type"].startswith("application/xml")
    assert client.post("/api/portal/act", json={"dataset": doc, "action": "message",
                                                "xml": "<!DOCTYPE x><x/>"}).status_code == 409
