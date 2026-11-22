"""Carrier AP records and settles the same source voucher used by the dated journal."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from scp import transport
from scp.accounting import view
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
from .test_freight_billing_integrity import book, shipped_freight
from .test_freight_credit import D0, D1, D2, credit


def pay(token, company, identifier, revision, day=D2, amount=None, reference="WIRE-1", voucher="FO-1"):
    return command(token, company, identifier, "transport", "pay_bill", revision, order="FO-1",
                   voucher=voucher, reference=reference, amount=amount, date=day.isoformat())


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_freight_aging_payment_and_closed_books_reconcile(backend, request):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)

    data = shipped_freight()
    data = data.model_copy(update={"freight_orders": data.freight_orders[:1]})
    finance = data.finance.model_copy(update={"separate_payments": True, "closed_through": D0, "control_roles": {
        "billing": ["owner@integrity.example"], "transport": ["buyer@integrity.example"],
        "payments": ["owner@integrity.example", "treasury@integrity.example"], "master_data": ["owner@integrity.example"],
    }})
    owner, dispatcher, company = team(data.model_copy(update={"finance": finance}))
    treasury = signup("treasury@integrity.example")
    join(owner, company, "treasury@integrity.example", "planner")
    booked = book(owner, company, "FO-1", "book", day=D1)
    assert booked.status_code == 200, booked.text
    billed = Dataset.model_validate(booked.json()["company"]["dataset"])
    assert billed.freight_orders[0].bill_entered_by == "owner@integrity.example"
    before = view(billed, period_end=D1)
    due = billed.freight_orders[0].bill_due_on
    assert due == D1 + timedelta(days=billed.carrier_by_id["CR-A"].payment_days)
    aggregate = payables_view(billed, due + timedelta(days=1))
    assert aggregate.open_value == aggregate.overdue_value == 100
    assert [(r.kind, r.company, r.supplier, r.open) for r in aggregate.payables] == [("carrier", "E1", "CR-A", 100)]
    assert [(r.voucher, r.open) for r in aggregate.carrier_bills] == [("FO-1", 100)]

    denied = pay(dispatcher, company, "dispatch-payment", 2)
    assert denied.status_code == 403 and "payments" in denied.text
    denied = pay(owner, company, "own-payment", 2)
    assert denied.status_code == 403 and "different person" in denied.text
    assert pay(treasury, company, "too-early", 2, day=D0).status_code == 409
    assert pay(treasury, company, "too-much", 2, amount=100.01).status_code == 409
    assert pay(treasury, company, "sub-cent", 2, amount=25.001).status_code == 409
    assert pay(treasury, company, "no-reference", 2, reference=" ").status_code == 409
    proposed, _ = transport.pay_bill(billed, "FO-1", "FO-1", 30, "WIRE-1", D2)
    refused = save(treasury, company, proposed, 2)
    assert refused.status_code == 403 and "require a payment command" in refused.text

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _: pay(treasury, company, "split-first", 2, amount=30.25), range(2)))
    assert all(response.status_code == 200 for response in replies)
    assert sorted(response.json()["duplicate"] for response in replies) == [False, True]
    partially_paid = Dataset.model_validate(replies[0].json()["company"]["dataset"])
    assert view(partially_paid, period_end=D1) == before
    assert payables_view(partially_paid).open_value == 69.75
    assert balance(partially_paid, "PAYABLES", D2, "E1") == -69.75
    assert balance(partially_paid, "BANK", D2, "E1") == -30.25
    duplicate = pay(treasury, company, "new-key-same-allocation", 3, reference=" Wire-1 ", amount=30.25)
    assert duplicate.status_code == 409 and "already recorded" in duplicate.text
    refused_credit = credit(owner, company, "try-credit-with-payment", 3, day=D2)
    assert refused_credit.status_code == 409 and "recorded payments" in refused_credit.text
    raw = partially_paid.model_dump(mode="json")
    raw["freight_orders"][0]["bill_payments"] = []
    assert save(treasury, company, raw, 3).status_code == 403
    raw = partially_paid.model_dump(mode="json")
    next(row for row in raw["carriers"] if row["id"] == "CR-A")["payment_days"] = 1
    changed_terms = save(owner, company, raw, 3)
    assert changed_terms.status_code == 200, changed_terms.text
    raw["freight_orders"][0]["bill_due_on"] = D1.isoformat()
    assert save(owner, company, raw, 4).status_code == 403

    day = D2 + timedelta(days=1)
    paid = pay(treasury, company, "split-final", 4, day=day, reference="WIRE-2")
    assert paid.status_code == 200, paid.text
    cleared = Dataset.model_validate(paid.json()["company"]["dataset"])
    assert balance(cleared, "PAYABLES", day, "E1") == 0 and balance(cleared, "BANK", day, "E1") == -100
    assert cleared.movements == billed.movements
    assert payables_view(cleared).open_value == 0
    assert payables_view(cleared).carrier_bills[0].status == "paid"
    assert payables_view(cleared).carrier_bills[0].due_on == due
    ledger = view(cleared)
    assert ledger.period_end == day and all(check.ok for check in ledger.checks)
    assert {v.number for v in ledger.vouchers} == {"FO-1", "FO-1/P-1", "FO-1/P-2"}
    plan = PlanResult(ok=True, currency=billed.settings.currency, carrying_rate=0)
    assert [sum(week.by.get("freight", 0) for week in cash_view(ds, plan, weeks=12).weeks)
            for ds in (billed, partially_paid, cleared)] == [-100, -69.75, 0]
    assert pay(treasury, company, "split-first", 2, amount=30.25).json()["company"]["meta"]["revision"] == 5


def test_credited_voucher_cannot_pay_its_replacement_and_legacy_separation_requires_evidence():
    data = shipped_freight()
    legacy, _ = transport.settle(data, "FO-1", 100, "ORIG", D0)
    owner, _, company = team(legacy.model_copy(update={"finance": legacy.finance.model_copy(update={"separate_payments": True})}))
    denied = pay(owner, company, "legacy", 1)
    assert denied.status_code == 403 and "no recorded entrant" in denied.text
    assert credit(owner, company, "correct-original").status_code == 200
    assert book(owner, company, "FO-1", "replacement", 2, day=D2, reference="CORRECTED").status_code == 200
    refused = pay(owner, company, "old-voucher", 3)
    assert refused.status_code == 409 and "current carrier bill" in refused.text


def test_payment_and_full_credit_conflict_and_closed_period_stays_protected():
    data, _ = transport.settle(shipped_freight(), "FO-1", 100, "ORIG", D0)
    owner, _, company = team(data.model_copy(update={"finance": data.finance.model_copy(update={"closed_through": D0})}))
    closed = pay(owner, company, "closed", 1, day=D0)
    assert closed.status_code == 403 and "is closed" in closed.text
    with ThreadPoolExecutor(2) as pool:
        payment = pool.submit(pay, owner, company, "concurrent-payment", 1)
        correction = pool.submit(credit, owner, company, "concurrent-credit", 1, day=D2)
        payment, correction = payment.result(), correction.result()
    assert sorted([payment.status_code, correction.status_code]) == [200, 409]
    won = next(r.json()["company"] for r in (payment, correction) if r.status_code == 200)
    assert won["meta"]["revision"] == 2
    posted = Dataset.model_validate(won["dataset"])
    assert view(posted, period_end=D0) == view(data, period_end=D0)
    assert balance(posted, "PAYABLES", D2, "E1") == 0
    assert balance(posted, "BANK", D2, "E1") == (-100 if payment.status_code == 200 else 0)
    assert len(view(posted, period_end=D2).vouchers) == 2
