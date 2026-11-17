"""Persisted order-to-cash / intercompany counterexamples and independent ledger oracles."""
from __future__ import annotations

import copy
from datetime import date

import pytest

from scp import intercompany as ic, sales
from scp.accounting import view
from scp.companies.patch import make_patch
from scp.model import Dataset, NegativeStock
from scp.purchasing import PurchasingError, act

from .test_companies import h, join, signup
from .test_enterprise_integrity import balance, client, team
from .test_intercompany import add, group, received, ship
from .test_order_to_cash import taken
from .test_procure_to_pay import JAN, ordered


def shipped():
    x, _ = taken()
    x, _ = sales.create_deliveries(x)
    return sales.issue(x, x.deliveries[0].id)[0]


def billed():
    return sales.create_invoices(shipped(), on=JAN)[0]


def save(token, cid, x, revision=1):
    return client.put(f"/api/companies/{cid}", headers=h(token), json={
        "base_revision": revision, "dataset": x.model_dump(mode="json") if isinstance(x, Dataset) else x})


@pytest.mark.parametrize("route", ["whole", "patch", "merge"])
@pytest.mark.parametrize("attack", ["delete", "reprice", "overpay", "backdate", "duplicate_id"])
def test_customer_financial_facts_and_settlement_are_guarded_on_every_save_route(route, attack):
    x = billed()
    owner, planner, cid = team(x)
    before = x.model_dump(mode="json")
    doc = copy.deepcopy(before)
    if attack == "delete":
        doc["invoices"] = []
    elif attack == "reprice":
        doc["invoices"][0]["lines"][0]["price"] = 1
    elif attack == "duplicate_id":
        doc["invoices"].append(copy.deepcopy(doc["invoices"][0]))
    else:
        doc["invoices"][0]["payments"] = [{"date": "2026-01-04" if attack == "backdate" else "2026-02-10",
                                            "amount": 1 if attack == "backdate" else 999999}]
    if route == "merge":
        response = client.post(f"/api/companies/{cid}/merge", headers=h(planner), json={
            "base": before, "dataset": doc, "base_revision": 1})
    else:
        body = {"patch": make_patch(before, doc)} if route == "patch" else {"dataset": doc}
        response = client.put(f"/api/companies/{cid}", headers=h(planner), json={"base_revision": 1, **body})
    assert response.status_code == 403, response.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 1


def test_sales_cancel_retains_the_original_period_and_posts_a_balanced_dated_reversal():
    x = billed()
    original = view(x, period_end=JAN).model_dump(mode="json")
    cancelled, _ = sales.cancel_invoice(x, x.invoices[0].id, on=date(2026, 2, 1))
    assert view(cancelled, period_end=JAN).model_dump(mode="json") == original
    report = view(cancelled, period_end=date(2026, 2, 1))
    assert all(c.ok for c in report.checks)
    assert balance(cancelled, "RECEIVABLES", date(2026, 2, 1)) == 0
    assert any(v.number == f"{x.invoices[0].id}/REV" and v.date == date(2026, 2, 1) for v in report.vouchers)
    with pytest.raises(sales.SalesError, match="nothing shipped"):
        sales.create_invoices(cancelled, on=date(2026, 1, 15))
    owner, _, cid = team(x)
    assert save(owner, cid, cancelled).status_code == 200
    assert save(owner, cid, x, 2).status_code == 403  # history restore cannot resurrect a cancellation


def test_intercompany_cancel_preserves_each_entitys_past_and_reverses_both_sides():
    x = add(received(group()), ship("GM-T1", "2026-01-06", 50))
    x, _ = ic.bill(x, date(2026, 1, 7))
    before = view(x, period_end=date(2026, 1, 7)).model_dump(mode="json")
    x, _ = ic.cancel(x, x.intercompany_invoices[0].id, date(2026, 2, 1))
    assert view(x, period_end=date(2026, 1, 7)).model_dump(mode="json") == before
    report = view(x, period_end=date(2026, 2, 1))
    assert all(c.ok for c in report.checks)
    reversals = [v for v in report.vouchers if v.number.endswith("/REV")]
    assert {v.company for v in reversals} == {"", "TR"}
    assert all(v.debit == v.credit for v in reversals)
    with pytest.raises(ic.IntercompanyError, match="nothing is due"):
        ic.bill(x, date(2026, 1, 15))


def test_new_billing_is_replayed_against_shipment_and_tax_facts():
    x = shipped()
    owner, _, cid = team(x)
    invoice, _ = sales.create_invoices(x, on=JAN)
    forged = invoice.model_dump(mode="json")
    forged["invoices"][0]["lines"][0]["qty"] += 1
    assert save(owner, cid, forged).status_code == 403
    response = save(owner, cid, invoice)
    assert response.status_code == 200, response.text
    actual = response.json()["dataset"]
    assert actual["invoices"][0]["entered_by"] == "owner@integrity.example"
    actual["demand"][0]["price"] = 1
    assert save(owner, cid, actual, 2).status_code == 403


def test_intercompany_new_and_existing_invoice_prices_cannot_be_forged():
    x = add(received(group()), ship("GM-T1", "2026-01-06", 50))
    owner, _, cid = team(x)
    bill, _ = ic.bill(x, date(2026, 1, 7))
    doc = bill.model_dump(mode="json")
    doc["intercompany_invoices"][0]["lines"][0]["price"] = 1
    assert save(owner, cid, doc).status_code == 403
    response = save(owner, cid, bill)
    assert response.status_code == 200, response.text
    doc = response.json()["dataset"]
    doc["intercompany_invoices"][0]["seller"] = "TR"
    assert save(owner, cid, doc, 2).status_code == 403


def test_a_named_permissions_matrix_and_maker_checker_payment_survive_direct_saves():
    x = shipped()
    owner, buyer, cid = team(x)
    treasury = signup("treasury@integrity.example")
    join(owner, cid, "treasury@integrity.example", "planner")
    doc = x.model_dump(mode="json")
    doc["finance"]["control_roles"] = {"billing": ["buyer@integrity.example"], "payments": ["treasury@integrity.example"]}
    doc["finance"]["separate_payments"] = True
    assert save(owner, cid, doc).status_code == 200
    invoice, _ = sales.create_invoices(Dataset.model_validate(doc), on=JAN)
    assert save(owner, cid, invoice, 2).status_code == 403  # owner is not a billing bypass
    response = save(buyer, cid, invoice, 2)
    assert response.status_code == 200, response.text
    persisted = Dataset.model_validate(response.json()["dataset"])
    paid, _ = sales.pay(persisted, persisted.invoices[0].id, on=date(2026, 2, 10))
    assert save(buyer, cid, paid, 3).status_code == 403
    assert save(treasury, cid, paid, 3).status_code == 200
    escalated = paid.model_dump(mode="json")
    escalated["finance"]["control_roles"]["payments"].append("buyer@integrity.example")
    assert save(buyer, cid, escalated, 4).status_code == 403


@pytest.mark.parametrize("rate,account,expected", [(85, "FX_LOSS", 5000), (75, "FX_GAIN", -5000)])
def test_foreign_settlement_clears_ap_at_the_posted_rate_and_bank_at_the_settlement_rate(rate, account, expected):
    d = ordered(tax_rate=0)
    d["settings"]["fx_rates"] = {"USD": 80}
    d["purchase_orders"][0]["currency"] = "USD"
    d["payment_terms"] = []
    d["vendors"][0].pop("payment_terms")
    x, _ = act(Dataset.model_validate(d), "receive", "PO-00001", on=JAN,
               lines=[{"id": "PO-00001-10", "qty": 100}])
    x, _ = act(x, "enter_invoice", "PO-00001", on=JAN)
    assert x.supplier_invoices[0].total == 1000 and x.supplier_invoices[0].fx_rate == 80
    missing = x.model_copy(update={"settings": x.settings.model_copy(update={"fx_rates": {}})})
    with pytest.raises(PurchasingError, match="exchange rate"):
        act(missing, "pay_invoice", x.supplier_invoices[0].id, on=date(2026, 2, 10))
    x = x.model_copy(update={"settings": x.settings.model_copy(update={"fx_rates": {"USD": rate}})})
    x, _ = act(x, "pay_invoice", x.supplier_invoices[0].id, on=date(2026, 2, 10))
    assert balance(x, "PAYABLES", date(2026, 2, 10)) == 0
    assert balance(x, "BANK", date(2026, 2, 10)) == -1000 * rate
    assert balance(x, account, date(2026, 2, 10)) == expected
    assert balance(x, "SUSPENSE", date(2026, 2, 10)) == 0
    assert all(c.ok for c in view(x, period_end=date(2026, 2, 10)).checks)
    before = view(x, period_end=date(2026, 2, 10)).model_dump(mode="json")
    changed = x.model_copy(update={"settings": x.settings.model_copy(update={"fx_rates": {"USD": 999}})})
    assert view(changed, period_end=date(2026, 2, 10)).model_dump(mode="json") == before


def test_closing_a_period_also_protects_customer_payments():
    x = billed()
    x = x.model_copy(update={"finance": x.finance.model_copy(update={"closed_through": date(2026, 1, 31)})})
    owner, _, cid = team(x)
    paid, _ = sales.pay(x, x.invoices[0].id, on=date(2026, 1, 12))
    assert save(owner, cid, paid).status_code == 403


def test_direct_stock_writes_use_the_saved_negative_stock_policy_and_opening_quantity():
    x, _ = taken()
    x = x.model_copy(update={"execution": x.execution.model_copy(update={"negative_stock": NegativeStock.REFUSE})})
    owner, _, cid = team(x)
    doc = x.model_dump(mode="json")
    doc["location_products"][0]["on_hand"] = 10000
    doc["execution"]["negative_stock"] = "allow"
    doc["movements"].append({"id": "FORGED-SCRAP", "type": "scrap", "date": JAN.isoformat(),
                             "location": "P", "product": "A", "qty": 1000})
    response = save(owner, cid, doc)
    assert response.status_code == 403 and "stock" in response.text


def test_a_credit_block_cannot_be_bypassed_with_a_direct_sale_movement():
    x, _ = taken(limit=1000)
    owner, _, cid = team(x)
    doc = x.model_dump(mode="json")
    doc["movements"].append({"id": "FORGED-SALE", "type": "sale", "date": JAN.isoformat(),
                             "location": "P", "product": "A", "qty": 1, "reference": "SO-00001/10"})
    response = save(owner, cid, doc)
    assert response.status_code == 403 and "credit is blocked" in response.text


def test_named_controller_can_close_but_cannot_reopen_or_grant_themself_other_rights():
    x = billed()
    owner, controller, cid = team(x)
    doc = x.model_dump(mode="json")
    doc["finance"]["control_roles"] = {"period_close": ["buyer@integrity.example"]}
    assert save(owner, cid, doc).status_code == 200
    doc["finance"]["closed_through"] = "2026-01-31"
    assert save(owner, cid, doc, 2).status_code == 403
    response = save(controller, cid, doc, 2)
    assert response.status_code == 200, response.text
    doc["finance"]["closed_through"] = None
    assert save(controller, cid, doc, 3).status_code == 403


def test_separation_is_enforced_even_when_one_person_has_both_named_grants():
    x = shipped()
    owner, buyer, cid = team(x)
    doc = x.model_dump(mode="json")
    doc["finance"]["control_roles"] = {"billing": ["buyer@integrity.example"], "payments": ["buyer@integrity.example"]}
    doc["finance"]["separate_payments"] = True
    assert save(owner, cid, doc).status_code == 200
    invoice, _ = sales.create_invoices(Dataset.model_validate(doc), on=JAN)
    response = save(buyer, cid, invoice, 2)
    assert response.status_code == 200, response.text
    paid, _ = sales.pay(Dataset.model_validate(response.json()["dataset"]), invoice.invoices[0].id,
                        on=date(2026, 2, 10))
    result = save(buyer, cid, paid, 3)
    assert result.status_code == 403 and "different person" in result.text


def test_transfer_price_edits_do_not_reprice_posted_stock_or_the_billing_still_due():
    from scp.actuals.post import receive, ship as dispatch
    x = received(group())
    x, _ = dispatch(x, "TR-1", on=date(2026, 1, 6))
    x, _ = receive(x, "TR-1", on=date(2026, 1, 7))
    assert next(m for m in x.movements if m.type.value == "transfer_out").transfer_price == 12
    old_books = view(x, period_end=date(2026, 1, 7)).model_dump(mode="json")
    updated = x.model_copy(update={"transfer_prices": [p.model_copy(update={"price": 20}) for p in x.transfer_prices]})
    assert view(updated, period_end=date(2026, 1, 7)).model_dump(mode="json") == old_books
    billed, _ = ic.bill(updated, date(2026, 1, 7))
    assert billed.intercompany_invoices[0].net == 600  # 50 × the posted 12, not today's 20
    assert all(c.ok for c in view(billed, period_end=date(2026, 1, 7)).checks)


def test_legacy_transfer_prices_are_frozen_from_the_saved_basis_before_a_rule_edit():
    from scp.actuals.post import receive, ship as dispatch
    x = received(group())
    x, _ = dispatch(x, "TR-1", on=date(2026, 1, 6))
    x, _ = receive(x, "TR-1", on=date(2026, 1, 7))
    legacy = x.model_dump(mode="json")
    for movement in legacy["movements"]:
        movement.pop("transfer_price", None)
    legacy = Dataset.model_validate(legacy)
    old_books = view(legacy, period_end=date(2026, 1, 7)).model_dump(mode="json")
    owner, _, cid = team(legacy)
    updated = legacy.model_copy(update={"transfer_prices": [p.model_copy(update={"price": 20}) for p in legacy.transfer_prices]})
    response = save(owner, cid, updated)
    assert response.status_code == 200, response.text
    saved = Dataset.model_validate(response.json()["dataset"])
    assert view(saved, period_end=date(2026, 1, 7)).model_dump(mode="json") == old_books
    forged = saved.model_dump(mode="json")
    next(m for m in forged["movements"] if m["type"] == "transfer_out")["transfer_price"] = 20
    assert save(owner, cid, forged, 2).status_code == 403
