"""Receiving, landed cost, carrier AP, treasury statement and refund form one dated trace."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from scp.accounting import view
from scp.actuals.valuation import value_stock
from scp.finance.cash import cash_view
from scp.model import Dataset
from scp.plan import PlanResult
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import join, signup
from .test_company_commands import command
from .test_enterprise_integrity import balance, team
from .test_transport import D0, _collect


def day(offset):
    return D0 + timedelta(days=offset)


def call(actor, company, identifier, revision, offset, kind, action, **parameters):
    return command(actor, company, identifier, kind, action, revision, date=day(offset).isoformat(), **parameters)


def saved(reply):
    assert reply.status_code == 200, reply.text
    return Dataset.model_validate(reply.json()["company"]["dataset"])


def prepare(price_control="moving_average"):
    raw = _collect(lines=((400, 4),))
    raw["entities"] = [{"id": "E1"}]
    raw["locations"][0]["entity"] = "E1"
    raw["location_products"][0]["on_hand"] = 0
    raw["deliveries"] = []
    raw["execution"] = {"price_control": price_control}
    raw["carriers"] = [{"id": "CARR", "rates": [{"lane": "LS", "per_shipment": 900}]}]
    billing = "owner@integrity.example"
    treasury = "treasury@integrity.example"
    raw["finance"] = {"separate_payments": True, "control_roles": {
        key: [billing] for key in ("billing", "transport", "purchasing", "warehouse", "inventory_adjustment", "period_close")}}
    raw["finance"]["control_roles"]["payments"] = [billing, treasury]
    owner, dispatcher, cid = team(Dataset.model_validate(raw))
    payer = signup(treasury)
    join(owner, cid, treasury, "planner")

    def post(identifier, revision, offset, kind, action, **parameters):
        return saved(call(owner, cid, identifier, revision, offset, kind, action, **parameters))

    planned = post("plan", 1, 0, "transport", "plan", lanes=["LS"])
    (order,) = planned.freight_orders
    fid = order.id
    for i, action in enumerate(("tender", "accept", "ship"), 2):
        post(action, i, 2, "transport", action, order=fid)
    received = post("receive", 5, 4, "purchasing", "receive", po="PO-1", lines=[{"id": "PO-1-10", "qty": 400}])
    receipt = next(m.id for m in received.movements if m.reference == "PO-1-10")
    post("bill", 6, 5, "transport", "settle", order=fid, bill="FRT-950", billed=950)
    cut = post("scrap", 7, 6, "stock", "scrap", location="W", product="X", qty=100, note="Spoiled")
    assert balance(cut, "STOCK", day(6), "E1") == 600
    assert receipt and cut.purchase_valuation_by_id["PO-1-10"].freight == 1
    doc = cut.model_dump(mode="json")
    original = view(cut, period_end=day(6))
    doc["finance"]["closed_through"] = day(6).isoformat()
    assert save(owner, cid, doc, 8).status_code == 200
    return owner, payer, dispatcher, cid, fid, receipt, original


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_landed_cost_credit_refund_and_bank_match_reconcile_by_date(backend, request):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    owner, payer, outsider, cid, fid, receipt, original = prepare()

    def event(actor, key, rev, offset, kind, **values):
        return call(actor, cid, key, rev, offset, "transport", "bill_event", order=fid, voucher=fid,
                    event={"kind": kind, **values})

    allocation = {"service": "SERVICE-950", "receipt": receipt, "actual_minor": 95000}
    blocked = event(owner, "closed-cost", 9, 6, "landed_cost", **allocation)
    assert blocked.status_code == 403 and "closed" in blocked.text
    assert event(outsider, "no-cost-grant", 9, 7, "landed_cost", **allocation).status_code == 403
    invalid = event(owner, "bad-receipt", 9, 7, "landed_cost", **{**allocation, "receipt": "OTHER"})
    assert invalid.status_code == 409 and "original goods receipt" in invalid.text
    allocated = saved(event(owner, "allocate", 9, 7, "landed_cost", **allocation))
    assert view(allocated, period_end=day(6)) == original
    assert balance(allocated, "STOCK", day(7), "E1") == 1012.50
    assert balance(allocated, "PRICE_DIFF", day(7), "E1") == 137.50
    assert balance(allocated, "DELIVERY", day(7), "E1") == 0
    assert value_stock(allocated).total_value == 1012.50
    assert event(owner, "dup-allocation", 10, 7, "landed_cost", **allocation).status_code == 409

    paid = saved(call(payer, cid, "wire", 10, 8, "transport", "pay_bill", order=fid, voucher=fid, reference="WIRE-950"))
    assert balance(paid, "BANK", day(8), "E1") == -950
    bank = {"cash_voucher": f"{fid}/P-1", "account": "OPERATING", "statement_line": "2026-03/L17",
            "reference": "WIRE-950", "amount_minor": -95000, "currency": "INR"}
    assert event(payer, "bad-bank", 11, 9, "match_bank", **{**bank, "amount_minor": 95000}).status_code == 409
    matched = saved(event(payer, "match-pay", 11, 9, "match_bank", **bank))
    assert view(matched) == view(paid)
    assert not payables_view(matched).carrier_bills[0].unreconciled_cash
    assert event(payer, "dup-match", 12, 9, "match_bank", **bank).status_code == 409
    refused = event(owner, "credit-before-reversal", 12, 10, "adjust_bill", reference="CR-100", reason="Disputed rate", amount_minor=10000)
    assert refused.status_code == 409 and "reverse the active" in refused.text
    undone = saved(event(owner, "reverse-cost", 12, 10, "reverse_landed", reverses=1))
    assert balance(undone, "STOCK", day(10), "E1") == 600
    credited = saved(event(owner, "credit", 13, 11, "adjust_bill", reference="CR-100", reason="Disputed rate", amount_minor=10000))
    assert balance(credited, "PAYABLES", day(11), "E1") == 100
    assert payables_view(credited).carrier_bills[0].status == "refund due"
    plan = PlanResult(ok=True, currency=credited.settings.currency, carrying_rate=0)
    assert sum(w.by.get("carrier_refunds", 0) for w in cash_view(credited, plan).weeks) == 100
    denied = event(owner, "self-refund", 14, 12, "refund_bill", reference="BACK-40", amount_minor=4000)
    assert denied.status_code == 403 and "different person" in denied.text
    assert event(payer, "too-high", 14, 12, "refund_bill", reference="BACK-40", amount_minor=10001).status_code == 409
    with ThreadPoolExecutor(2) as pool:
        two = list(pool.map(lambda _: event(payer, "refund-40", 14, 12, "refund_bill", reference="BACK-40", amount_minor=4000), range(2)))
    partial = saved(two[0])
    assert sorted(r.json()["duplicate"] for r in two) == [False, True]
    assert balance(partial, "PAYABLES", day(12), "E1") == 60
    cleared = saved(event(payer, "refund-60", 15, 13, "refund_bill", reference="BACK-60", amount_minor=6000))
    assert balance(cleared, "PAYABLES", day(13), "E1") == 0
    assert balance(cleared, "BANK", day(13), "E1") == -850
    assert payables_view(cleared).carrier_bills[0].status == "refunded"
    assert sum(w.by.get("carrier_refunds", 0) for w in cash_view(cleared, plan).weeks) == 0
    final = saved(event(owner, "allocate-net", 16, 14, "landed_cost", **{**allocation, "actual_minor": 85000}))
    assert balance(final, "STOCK", day(14), "E1") == 937.50
    assert balance(final, "PRICE_DIFF", day(14), "E1") == 112.50
    assert balance(final, "DELIVERY", day(14), "E1") == 0
    refund_bank = {**bank, "cash_voucher": f"{fid}/R-5", "amount_minor": 4000, "reference": "BACK-40"}
    assert event(payer, "bank-line-reused", 17, 15, "match_bank", **refund_bank).status_code == 409
    refund_bank["statement_line"] = "2026-03/L51"
    matched_refund = saved(event(payer, "match-refund", 17, 15, "match_bank", **refund_bank))
    assert payables_view(matched_refund).carrier_bills[0].unreconciled_cash == [f"{fid}/R-6"]
    released = saved(event(payer, "release-match", 18, 16, "release_match", cash_voucher=f"{fid}/R-5",
                           account=bank["account"], statement_line=refund_bank["statement_line"]))
    assert set(payables_view(released).carrier_bills[0].unreconciled_cash) == {f"{fid}/R-5", f"{fid}/R-6"}
    assert view(released) == view(final) and view(released, period_end=day(6)) == original
    assert all(check.ok for check in view(released).checks)
    raw = released.model_dump(mode="json")
    raw["freight_orders"][0]["bill_events"][-1]["statement_line"] = "ALTERED"
    assert save(owner, cid, raw, 19).status_code == 422
    raw = released.model_dump(mode="json")
    raw["freight_orders"][0]["bill_events"][3]["reason"] = "Rewritten"
    assert save(owner, cid, raw, 19).status_code == 403


def test_freight_delta_goes_to_variance_under_standard_cost():
    owner, _, _, cid, fid, receipt, original = prepare("standard")
    data = saved(call(owner, cid, "standard-cost", 9, 7, "transport", "bill_event", order=fid, voucher=fid,
                      event={"kind": "landed_cost", "receipt": receipt, "service": "ACCEPTED", "actual_minor": 95000}))
    assert view(data, period_end=day(6)) == original
    assert balance(data, "STOCK", day(7), "E1") == 600
    assert balance(data, "PRICE_DIFF", day(7), "E1") == 550
    assert balance(data, "DELIVERY", day(7), "E1") == 0
