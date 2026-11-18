"""Authoritative commands: atomic effects, replay identity and departmental authority."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from scp.companies import get_companies
from scp.companies import commands
from scp.model import Dataset
from scp.purchasing import act

from .test_companies import h, join, new_company, signup
from .test_enterprise_integrity import balance, client, team
from .test_procure_to_pay import JAN, ordered, received
from .test_backup_postgres import pg_databases as pg_databases


def command(token, cid, identifier, kind, action, revision=1, **parameters):
    posting_date = parameters.pop("date", JAN.isoformat())
    return client.post(f"/api/companies/{cid}/commands", headers=h(token), json={
        "id": identifier, "kind": kind, "action": action, "posting_date": posting_date,
        "base_revision": revision, "parameters": parameters})


def test_command_posts_against_saved_state_and_replay_returns_current_state():
    x = received(b=100, c=0)
    owner, _, cid = team(x)
    first = command(owner, cid, "enter-1", "purchasing", "enter_invoice", po="PO-00001", date=JAN.isoformat())
    assert first.status_code == 200, first.text
    one = first.json()
    assert one["revision"] == 2 and not one["duplicate"]
    assert len(one["company"]["dataset"]["supplier_invoices"]) == 1
    paid = command(owner, cid, "pay-1", "purchasing", "pay_invoice", revision=2,
                   po="SI-00001", date="2026-02-10")
    assert paid.status_code == 200, paid.text
    replay = command(owner, cid, "enter-1", "purchasing", "enter_invoice", po="PO-00001", date=JAN.isoformat())
    assert replay.status_code == 200, replay.text
    again = replay.json()
    assert again["duplicate"] and again["revision"] == 2 and again["company"]["meta"]["revision"] == 3
    current = Dataset.model_validate(again["company"]["dataset"])
    assert len(current.supplier_invoices) == 1 and current.supplier_invoices[0].payments
    assert balance(current, "BANK", date(2026, 2, 10)) == -1100


def test_reused_command_identifier_with_changed_parameters_and_stale_new_command_are_refused():
    owner, _, cid = team(received(b=100, c=0))
    first = command(owner, cid, "same-id", "purchasing", "enter_invoice", po="PO-00001", date=JAN.isoformat())
    assert first.status_code == 200, first.text
    assert command(owner, cid, "same-id", "purchasing", "enter_invoice", po="PO-00001", tax=999).status_code == 409
    stale = command(owner, cid, "new-id", "purchasing", "pay_invoice", po="SI-00001", date="2026-02-10")
    assert stale.status_code == 409 and stale.json()["revision"] == 2
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 2


def test_receipt_write_failure_rolls_back_business_revision_and_audit(monkeypatch):
    owner, _, cid = team(received(b=100, c=0))
    before = client.get(f"/api/companies/{cid}", headers=h(owner)).json()

    def fail(*args, **kwargs):
        raise OSError("injected command receipt failure")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail)
        with pytest.raises(OSError, match="injected command receipt"):
            command(owner, cid, "retry-1", "purchasing", "enter_invoice", po="PO-00001")
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json() == before
    c = get_companies()
    assert c.db.execute("SELECT COUNT(*) FROM company_commands WHERE company_id = ?", (cid,)).fetchone()[0] == 0
    assert c.db.execute("SELECT COUNT(*) FROM company_revisions WHERE company_id = ?", (cid,)).fetchone()[0] == 1
    result = command(owner, cid, "retry-1", "purchasing", "enter_invoice", po="PO-00001")
    assert result.status_code == 200 and not result.json()["duplicate"], result.text


def test_concurrent_repeated_command_has_one_payment_effect():
    x, _ = act(received(b=100, c=0), "enter_invoice", "PO-00001", on=JAN)
    owner, _, cid = team(x)
    with ThreadPoolExecutor(2) as pool:
        answers = list(pool.map(lambda _: command(owner, cid, "bank-transaction-1", "purchasing", "pay_invoice",
                                                 po="SI-00001", date="2026-02-10"), range(2)))
    assert all(r.status_code == 200 for r in answers), [r.text for r in answers]
    assert sorted(r.json()["duplicate"] for r in answers) == [False, True]
    current = Dataset.model_validate(answers[-1].json()["company"]["dataset"])
    assert len(current.supplier_invoices[0].payments) == 1
    assert balance(current, "BANK", date(2026, 2, 10)) == -1100


def test_minimal_saved_document_does_not_gain_defaults_requiring_unrelated_master_grants():
    receiver = signup("receiver@commands.example")
    biller = signup("billing@commands.example")
    payer = signup("treasury@commands.example")
    doc = ordered(tax_rate=0.1)
    doc["receipts"] = doc["receipts"][:1]
    doc["finance"] = {"control_roles": {"warehouse": ["receiver@commands.example"],
                                         "billing": ["billing@commands.example"], "payments": ["treasury@commands.example"]},
                        "separate_payments": True}
    cid = new_company(receiver, doc)
    join(receiver, cid, "billing@commands.example", "planner")
    join(receiver, cid, "treasury@commands.example", "planner")
    response = command(receiver, cid, "receipt-1", "purchasing", "receive", po="PO-00001", date=JAN.isoformat())
    assert response.status_code == 200, response.text
    assert "forecasting" not in response.json()["company"]["dataset"]  # schema defaults are not operational edits
    response = command(biller, cid, "invoice-1", "purchasing", "enter_invoice", revision=2,
                       po="PO-00001", date=JAN.isoformat())
    assert response.status_code == 200, response.text
    response = command(payer, cid, "payment-1", "purchasing", "pay_invoice", revision=3,
                       po="SI-00001", date="2026-02-10")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("attack", ["viewer", "other_company", "replace_dataset", "unknown_parameter"])
def test_command_cannot_escape_membership_or_replace_authoritative_inputs(attack):
    owner, planner, cid = team(received(b=100, c=0))
    token = planner
    extra = {"po": "PO-00001"}
    if attack == "viewer":
        client.post(f"/api/companies/{cid}/members", headers=h(owner), json={
            "email": "buyer@integrity.example", "role": "viewer"})
    elif attack == "other_company":
        outsider = signup("outsider@commands.example")
        cid = new_company(outsider, received(b=100, c=0).model_dump(mode="json"))
    elif attack == "replace_dataset":
        extra["dataset"] = {"movements": []}
    else:
        extra["invented_parameter"] = True
    response = command(token, cid, "bad-command", "purchasing", "enter_invoice", **extra)
    assert response.status_code in (403, 404, 422), response.text


def test_company_command_receipts_are_in_the_accounts_data_export():
    owner, _, cid = team(received(b=100, c=0))
    assert command(owner, cid, "data-export-command", "purchasing", "enter_invoice", po="PO-00001").status_code == 200
    c = get_companies()
    exported = c.export_account(c.whoami(owner), password="correct horse")
    company = next(item for item in exported["companies"] if item["id"] == cid)
    assert company["your_commands"][0]["id"] == "data-export-command"


def test_material_command_replay_cannot_resurrect_stock_after_an_intervening_scrap():
    owner = signup("stock@commands.example")
    cid = new_company(owner, ordered())
    first = command(owner, cid, "goods-receipt-1", "purchasing", "receive", po="PO-00001", date=JAN.isoformat(),
                    lines=[{"id": "PO-00001-10", "qty": 100}])
    assert first.status_code == 200, first.text
    scrapped = command(owner, cid, "scrap-1", "stock", "scrap", revision=2, location="P", product="B", qty=10,
                       date="2026-01-06")
    assert scrapped.status_code == 200, scrapped.text
    replay = command(owner, cid, "goods-receipt-1", "purchasing", "receive", po="PO-00001", date=JAN.isoformat(),
                     lines=[{"id": "PO-00001-10", "qty": 100}])
    assert replay.status_code == 200 and replay.json()["duplicate"], replay.text
    from scp.actuals.stock import before, stock
    ds = Dataset.model_validate(replay.json()["company"]["dataset"])
    assert stock(before(ds, date(2026, 1, 7)))[("P", "B")] == 120  # opening 30 + receipt 100 - scrap 10


def test_concurrent_distinct_commands_based_on_one_revision_cannot_both_post():
    owner, _, cid = team(received(b=100, c=0))
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda key: command(owner, cid, key, "stock", "scrap", location="P", product="B",
                                                      qty=1, date=JAN.isoformat()), ("scrap-a", "scrap-b")))
    assert sorted(r.status_code for r in responses) == [200, 409]
    c = get_companies()
    assert c.db.execute("SELECT COUNT(*) FROM company_commands WHERE company_id = ?", (cid,)).fetchone()[0] == 1


def test_explicit_posting_date_is_required_and_the_completed_request_can_be_reconciled():
    owner, _, cid = team(received(b=100, c=0))
    response = client.post(f"/api/companies/{cid}/commands", headers=h(owner), json={
        "id": "missing-date", "kind": "purchasing", "action": "enter_invoice", "base_revision": 1,
        "parameters": {"po": "PO-00001"}})
    assert response.status_code == 422
    assert command(owner, cid, "explicit-date", "purchasing", "enter_invoice", po="PO-00001").status_code == 200
    receipt = client.get(f"/api/companies/{cid}/commands", params={"id": "explicit-date"}, headers=h(owner))
    assert receipt.status_code == 200, receipt.text
    record = receipt.json()
    assert record["posting_date"] == JAN.isoformat() and record["parameters"] == {"po": "PO-00001"}
    assert record["revision"] == 2 and len(record["request_hash"]) == 64
    assert command(owner, cid, "explicit-date", "purchasing", "enter_invoice", po="PO-00001",
                   date="2026-01-06").status_code == 409


def test_a_command_does_not_commit_physical_effects_while_a_required_master_change_is_held():
    from .test_order_to_cash import taken
    owner, _, cid = team(taken()[0])
    response = client.put(f"/api/companies/{cid}/approval", headers=h(owner), json={"approval": True})
    assert response.status_code == 200, response.text
    before = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    response = command(owner, cid, "count-needs-master", "stock", "count", date="2026-01-04",
                       counts=[{"location": "P", "product": "A", "qty": 95}])
    assert response.status_code == 409 and "approved" in response.text, response.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json() == before
    c = get_companies()
    assert c.db.execute("SELECT COUNT(*) FROM company_commands WHERE company_id = ?", (cid,)).fetchone()[0] == 0
    assert c.db.execute("SELECT COUNT(*) FROM change_requests WHERE company_id = ?", (cid,)).fetchone()[0] == 0


def test_combined_invoice_entry_and_payment_requires_both_department_grants():
    ds = received(b=100, c=0)
    ds = ds.model_copy(update={"finance": ds.finance.model_copy(update={"control_roles": {
        "billing": ["owner@integrity.example"]}})})
    owner, _, cid = team(ds)
    changed, _ = act(ds, "enter_invoice", "PO-00001", on=JAN)
    changed, _ = act(changed, "pay_invoice", "SI-00001", on=JAN)
    response = client.put(f"/api/companies/{cid}", headers=h(owner), json={
        "base_revision": 1, "dataset": changed.model_dump(mode="json")})
    assert response.status_code == 403 and "payments" in response.text, response.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 1


def test_postgres_command_atomicity_concurrent_replay_and_restored_receipt(pg_databases, tmp_path, monkeypatch):
    from scp.backup import backup_postgres
    from scp.companies.store import Companies
    from scp.migrate_postgres import migrate
    from scp.versions.store import Store

    url = pg_databases()
    c = Companies(Store(url))
    owner = c.signup("commands@pg.example", "Treasury", "independent-river-horse-725").user
    ds, _ = act(received(b=100, c=0), "enter_invoice", "PO-00001", on=JAN)
    cid = c.create(owner, ds.model_dump(mode="json")).id
    req = commands.CommandRequest(id="bank-729", base_revision=1, posting_date=date(2026, 2, 10),
                                  kind="purchasing", action="pay_invoice", parameters={"po": "SI-00001"})

    def operation(saved):
        changed, result = act(saved, "pay_invoice", "SI-00001", on=req.posting_date)
        return changed, result.model_dump(mode="json")

    def fail(*args, **kwargs):
        raise OSError("injected PostgreSQL receipt failure")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", fail)
        with pytest.raises(OSError, match="PostgreSQL receipt failure"):
            commands.execute(c, owner, cid, req, operation)
    assert c.open(owner, cid).meta.revision == 1
    assert c.db.execute("SELECT COUNT(*) FROM company_commands").fetchone()[0] == 0
    assert c.db.execute("SELECT COUNT(*) FROM company_revisions").fetchone()[0] == 1
    other = Companies(Store(url))
    try:
        with ThreadPoolExecutor(2) as pool:
            answers = list(pool.map(lambda store: commands.execute(store, owner, cid, req, operation), (c, other)))
        assert sorted(r.duplicate for r in answers) == [False, True]
        assert c.open(owner, cid).meta.revision == 2
        assert len(Dataset.model_validate(c.open(owner, cid).dataset).supplier_invoices[0].payments) == 1
    finally:
        other.db.close()
    saved = backup_postgres(url, tmp_path)
    target = pg_databases()
    monkeypatch.setenv("DATABASE_URL", target)
    migrate(saved, apply=True)
    restored = Companies(Store(target))
    try:
        answer = commands.execute(restored, owner, cid, req, operation)
        receipt = commands.record(restored, owner, cid, req.id)
        assert answer.duplicate and answer.revision == receipt.revision == 2
        assert receipt.parameters == {"po": "SI-00001"} and receipt.posting_date == req.posting_date
        assert balance(Dataset.model_validate(answer.company.dataset), "BANK", req.posting_date) == -1100
        assert restored.db.execute("SELECT COUNT(*) FROM company_commands").fetchone()[0] == 1
    finally:
        c.db.close()
        restored.db.close()
