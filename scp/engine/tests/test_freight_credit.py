"""A carrier credit belongs to one reviewed bill and one open accounting date."""
from datetime import timedelta

import pytest

from scp import transport
from scp.accounting import view
from scp.finance.cash import cash_view
from scp.model import Dataset
from scp.plan import PlanResult
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_company_commands import command
from .test_enterprise_integrity import balance, team
from .test_freight_billing_integrity import book, shipped_freight
from .test_transport import D0


D1, D2 = D0 + timedelta(days=1), D0 + timedelta(days=2)


def credit(token, cid, command_id, revision=1, voucher="FO-1", day=D1, reference="CR-10"):
    return command(token, cid, command_id, "transport", "credit", revision, order="FO-1", credit_of=voucher,
                   bill=reference, reason="Wrong fuel charge", date=day.isoformat())


def original_bill() -> Dataset:
    doc, _ = transport.settle(shipped_freight(), "FO-1", 100, "BILL-1", D0)
    grants = {"billing": ["owner@integrity.example"], "master_data": ["owner@integrity.example"],
              "transport": ["buyer@integrity.example"]}
    finance = doc.finance.model_copy(update={"closed_through": D0, "control_roles": grants})
    return doc.model_copy(update={"finance": finance})


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_credit_and_rebill_leave_original_period_and_shipment_intact(backend, request):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)

    doc = original_bill()
    owner, dispatcher, company = team(doc)
    prior_report = view(doc, period_end=D0)
    backdated = credit(owner, company, "early-credit", day=D0 - timedelta(days=1))
    assert backdated.status_code == 409 and "before the original bill" in backdated.text
    closed = credit(owner, company, "closed-credit", day=D0)
    assert closed.status_code == 403 and "is closed" in closed.text
    unauthorized = credit(dispatcher, company, "dispatch-credit")
    assert unauthorized.status_code == 403 and "billing" in unauthorized.text
    simulated, _ = transport.credit_bill(doc, "FO-1", "FO-1", "CR-10", "Wrong fuel charge", D1)
    unreceipted = save(owner, company, simulated)
    assert unreceipted.status_code == 403 and "require a freight credit command" in unreceipted.text

    result = credit(owner, company, "credit-once")
    assert result.status_code == 200, result.text
    saved = result.json()["company"]
    assert saved["meta"]["revision"] == 2
    reopened = Dataset.model_validate(saved["dataset"])
    assert reopened.freight_orders[0].status == "shipped"
    assert reopened.freight_orders[0].shipped_on == doc.freight_orders[0].shipped_on
    assert reopened.movements == doc.movements
    assert view(reopened, period_end=D0) == prior_report
    assert balance(reopened, "PAYABLES", D1, "E1") == 0
    assert balance(reopened, "DELIVERY", D1, "E1") == 0
    credit_report = view(reopened, period_end=D1)
    assert all(c.ok for c in credit_report.checks)
    reversal = next(v for v in credit_report.vouchers if v.number == "FO-1/REV")
    assert reversal.date == D1 and reversal.company == "E1" and "CR-10" in reversal.narration
    assert {(line.account, line.debit, line.credit) for line in reversal.lines} == {("DELIVERY", 0, 100), ("PAYABLES", 100, 0)}

    raw = reopened.model_dump(mode="json")
    raw["freight_orders"][0]["bill_credits"][0]["billed"] = 1
    assert save(owner, company, raw, 2).status_code == 403
    raw = reopened.model_dump(mode="json")
    next(row for row in raw["locations"] if row["id"] == "W")["entity"] = "E2"
    assert save(owner, company, raw, 2).status_code == 403
    too_soon = book(owner, company, "FO-1", "early-rebill", 2, day=D0)
    assert too_soon.status_code == 409 and "preceding credit" in too_soon.text
    replaced = command(owner, company, "corrected-bill", "transport", "settle", 2, order="FO-1", bill="BILL-1",
                       billed=80, date=D2.isoformat())
    assert replaced.status_code == 200, replaced.text
    latest = Dataset.model_validate(replaced.json()["company"]["dataset"])
    assert view(latest, period_end=D0) == prior_report and view(latest, period_end=D1) == credit_report
    assert balance(latest, "PAYABLES", D2, "E1") == -80 and balance(latest, "DELIVERY", D2, "E1") == 80
    assert {v.number for v in view(latest, period_end=D2).vouchers} == {"FO-1", "FO-1/REV", "FO-1/B2"}
    stale = credit(owner, company, "stale-credit", 3, day=D2, reference="CR-11")
    assert stale.status_code == 409 and "active bill changed" in stale.text
    duplicate = credit(owner, company, "different-command", 3, voucher="FO-1/B2", day=D2, reference=" cr-10 ")
    assert duplicate.status_code == 409 and "already booked" in duplicate.text
    replay = credit(owner, company, "credit-once").json()
    assert replay["duplicate"] and replay["revision"] == 2 and replay["company"]["meta"]["revision"] == 3


def test_a_credited_freight_bill_is_not_reintroduced_into_the_cash_forecast_at_its_planned_cost():
    data = original_bill()
    data = data.model_copy(update={"freight_orders": data.freight_orders[:1]})
    credited, _ = transport.credit_bill(data, "FO-1", "FO-1", "CR-10", "Full credit", D1)
    plan = PlanResult(ok=True, currency=data.settings.currency, carrying_rate=0)

    def freight(ds):
        return sum(week.by.get("freight", 0) for week in cash_view(ds, plan, weeks=8).weeks)

    assert freight(data) == -100 and freight(credited) == 0
    replaced, _ = transport.settle(credited, "FO-1", 80, "BILL-1", D2)
    assert freight(replaced) == -80
