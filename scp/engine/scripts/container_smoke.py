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

    live_id = request("/api/companies", {"dataset": doc})["id"]
    live_revision = 1

    def command(identifier, action, **parameters):
        nonlocal live_revision
        result = request(f"/api/companies/{live_id}/commands", {
            "id": identifier, "kind": "purchasing", "action": action, "posting_date": "2026-01-05",
            "base_revision": live_revision, "parameters": parameters})
        live_revision = result["company"]["meta"]["revision"]
        return result

    command("goods-receipt-1", "receive", po="PO-1", lines=[{"id": "PO-1-10", "qty": 100}])
    command("invoice-1", "enter_invoice", po="PO-1")
    command("payment-1", "pay_invoice", po="SI-00001")
    replay = command("invoice-1", "enter_invoice", po="PO-1")
    assert replay["duplicate"] and replay["revision"] == 3 and live_revision == 4
    live_books = request("/api/accounting", replay["company"]["dataset"])
    assert live_books == books
    receipt = request(f"/api/companies/{live_id}/commands?id=payment-1")
    assert receipt["revision"] == 4 and receipt["engine_commit"] == health["commit"]

    # Independent outsourced-production fixture: 20 components at 4 sent,
    # nine finished units at 10 returned, two components returned unused,
    # and a service charge of 9 * 2. The remaining stock is 418 and WIP clears.
    job_doc = {"settings": {"planning_start": "2026-01-05", "horizon_days": 28, "currency": "INR"},
               "locations": [{"id": "P", "type": "plant"}, {"id": "S", "type": "supplier"}],
               "products": [{"id": "A", "type": "FG", "standard_cost": 10},
                            {"id": "B", "type": "RM", "standard_cost": 4}],
               "location_products": [{"location": "P", "product": "A", "on_hand": 0},
                                     {"location": "P", "product": "B", "on_hand": 100}],
               "production_sources": [{"id": "MAKE-A", "location": "P", "product": "A", "output_qty": 1,
                   "components": [{"product": "B", "qty": 2}],
                   "operations": [{"seq": 10, "subcontract": {"supplier": "S", "workdays": 1, "cost_per_unit": 2}}]}],
               "receipts": [{"id": "MO-1", "kind": "production", "location": "P", "product": "A", "qty": 10,
                             "start_date": "2026-01-05", "due_date": "2026-01-06", "source": "MAKE-A"}]}
    job_id = request("/api/companies", {"dataset": job_doc})["id"]
    job_revision = 1

    def job_command(identifier, kind, action, day, **parameters):
        nonlocal job_revision
        result = request(f"/api/companies/{job_id}/commands", {
            "id": identifier, "kind": kind, "action": action, "posting_date": day,
            "base_revision": job_revision, "parameters": parameters})
        job_revision = result["company"]["meta"]["revision"]
        return result

    job_command("send-1", "outside", "send_parts", "2026-01-05", production_order="MO-1")
    job_command("processed-1", "outside", "back_processed", "2026-01-06", id="JW-00001", qty=9)
    job_command("unused-1", "outside", "back_unused", "2026-01-07", id="JW-00001", product="B", qty=2)
    job_command("job-invoice-1", "purchasing", "enter_invoice", "2026-01-07", lines=[{"order": "JW-00001"}])
    job_command("job-payment-1", "purchasing", "pay_invoice", "2026-01-08", po="SI-00001")
    replay = job_command("send-1", "outside", "send_parts", "2026-01-05", production_order="MO-1")
    assert replay["duplicate"] and job_revision == 6
    job_saved = replay["company"]["dataset"]
    job_books = request("/api/accounting?period_end=2026-01-09", job_saved)
    job_balances = {r["account"]: r["balance"] for r in job_books["balances"] if r["company"] == ""}
    for account, expected in {"STOCK": 418, "WIP": 0, "PAYABLES": 0, "BANK": -18, "SUSPENSE": 0, "PRICE_DIFF": 0}.items():
        assert abs(job_balances.get(account, 0) - expected) < .005, (account, job_balances)
    removed = {**job_saved, "challans": []}
    request(f"/api/companies/{job_id}", {"dataset": removed, "base_revision": job_revision}, method="PUT", expected=403)

    blocked = act(received, "enter_invoice", lines=[{"order": "PO-1-10", "qty": 100, "price": 11}])
    request("/api/purchasing/act", {"dataset": blocked, "action": "pay_invoice", "po": "SI-00001"}, expected=409)
    blocked_id = request("/api/companies", {"dataset": blocked})["id"]
    forged = copy.deepcopy(blocked)
    forged["supplier_invoices"][0]["payments"] = [{"date": "2026-01-05", "amount": 1210, "fx_rate": 1}]
    request(f"/api/companies/{blocked_id}", {"dataset": forged, "base_revision": 1}, method="PUT", expected=403)
    assert request(f"/api/companies/{blocked_id}")["meta"]["revision"] == 1
    print(json.dumps({"commit": health["commit"], "uid": os.geteuid(), "health": "passed", "web": "passed",
                      "persisted_procure_to_pay": "passed", "company_revision": revision,
                      "authoritative_commands_and_replay": "passed", "command_revision": live_revision,
                      "jobwork_commands_and_replay": "passed", "jobwork_revision": job_revision,
                      "jobwork_ledger": {k: job_balances.get(k, 0) for k in
                                        ("STOCK", "WIP", "PAYABLES", "BANK", "SUSPENSE", "PRICE_DIFF")},
                      "posted_challan_removal": 403,
                      "ledger": {k: balances.get(k, 0) for k in ("STOCK", "INPUT_TAX", "BANK", "PAYABLES", "GRIR")},
                      "blocked_payment_action": 409, "forged_payment_save": 403}, indent=2))


if __name__ == "__main__":
    main()
