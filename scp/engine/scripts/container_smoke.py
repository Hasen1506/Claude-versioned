"""Disposable-container release check, using HTTP and literal ledger expectations.

Requires SCP_SIGNUP=open in the disposable test container. Creates synthetic local
data, sends no external messages, and needs only the Python standard library.
"""
from __future__ import annotations

import copy
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    token = ""
    base_url = os.environ.get("SCP_SMOKE_URL", "http://127.0.0.1:8000").rstrip("/")
    def request(path, body=None, method=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(base_url + path, data=None if body is None else json.dumps(body).encode(),
                      headers=headers, method=method)
        try:
            response = urlopen(req, timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            assert response.status == expected, (path, response.status, raw[:1000])
            return json.loads(raw) if "json" in response.headers.get("Content-Type", "") else raw.decode()

    assert os.geteuid() != 0, "the deployed application must run as nonroot"
    health = request("/api/health")
    assert health["commit"] == os.environ["SCP_COMMIT"]
    assert "<html" in request("/").lower()
    session = request("/api/auth/signup", {"email": "release-smoke@example.test", "name": "Release smoke",
                                            "password": "local-test-WINTER-river-9741"})
    token = session["token"]
    doc = {"settings": {"planning_start": "2026-01-05", "horizon_days": 28, "currency": "INR"},
           "locations": [{"id": "P", "type": "plant"}, {"id": "S", "type": "supplier"}],
           "products": [{"id": "B", "type": "RM", "standard_cost": 10}],
           "location_products": [{"location": "P", "product": "B", "on_hand": 0}],
           "purchasing_sources": [{"id": "BUY-B", "supplier": "S", "location": "P", "product": "B",
                                   "price": 10, "lead_time_days": 1}], "purchasing": {"tax_rate": 0.1},
           "purchase_orders": [{"id": "PO-1", "supplier": "S", "location": "P", "order_date": "2026-01-02",
                                "sent_on": "2026-01-02"}],
           "receipts": [{"id": "PO-1-10", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
                          "due_date": "2026-01-05", "source": "BUY-B", "po": "PO-1", "price": 10}]}
    cid = request("/api/companies", {"dataset": doc})["id"]
    revision = 1

    def persist(document):
        nonlocal revision
        saved = request(f"/api/companies/{cid}", {"dataset": document, "base_revision": revision}, method="PUT")
        revision = saved["meta"]["revision"]
        return request(f"/api/companies/{cid}")["dataset"]

    def act(document, action, **extra):
        return request("/api/purchasing/act", {"dataset": document, "action": action, "po": "PO-1",
                                              "date": "2026-01-05", **extra})["dataset"]

    received = persist(act(doc, "receive", lines=[{"id": "PO-1-10", "qty": 100}]))
    invoiced = persist(act(received, "enter_invoice"))
    paid = persist(act(invoiced, "pay_invoice", po="SI-00001"))
    books = request("/api/accounting", paid)
    balances = {r["account"]: r["balance"] for r in books["balances"] if r["company"] == ""}
    for account, expected in {"STOCK": 1000, "INPUT_TAX": 100, "BANK": -1100, "PAYABLES": 0, "GRIR": 0}.items():
        assert abs(balances.get(account, 0) - expected) < .005, (account, balances)
    assert all(check["ok"] for check in books["checks"])

    blocked = act(received, "enter_invoice", lines=[{"order": "PO-1-10", "qty": 100, "price": 11}])
    request("/api/purchasing/act", {"dataset": blocked, "action": "pay_invoice", "po": "SI-00001"}, expected=409)
    blocked_id = request("/api/companies", {"dataset": blocked})["id"]
    forged = copy.deepcopy(blocked)
    forged["supplier_invoices"][0]["payments"] = [{"date": "2026-01-05", "amount": 1210, "fx_rate": 1}]
    request(f"/api/companies/{blocked_id}", {"dataset": forged, "base_revision": 1}, method="PUT", expected=403)
    assert request(f"/api/companies/{blocked_id}")["meta"]["revision"] == 1
    print(json.dumps({"commit": health["commit"], "uid": os.geteuid(), "health": "passed", "web": "passed",
                      "persisted_procure_to_pay": "passed", "company_revision": revision,
                      "ledger": {k: balances.get(k, 0) for k in ("STOCK", "INPUT_TAX", "BANK", "PAYABLES", "GRIR")},
                      "blocked_payment_action": 409, "forged_payment_save": 403}, indent=2))


if __name__ == "__main__":
    main()
