"""Bank evidence is imported once and allocated atomically across posted carrier cash vouchers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from scp import transport
from scp.accounting import view
from scp.model import Dataset
from scp.purchasing.payables import payables_view
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client, team
from .test_freight_billing_integrity import shipped_freight
from .test_transport import D0


P1, P2 = D0 + timedelta(days=1), D0 + timedelta(days=2)


def bank(token, cid, identifier, revision, kind, **data):
    return command(token, cid, identifier, "carrier_bank", "record", revision, date=P2.isoformat(), event={"kind": kind, **data})


def csv_rows(*rows):
    return "line,date,reference,amount,currency\n" + "".join(f"{line},{P1},WIRE-COMB,{amount},INR\n" for line, amount in rows)


def cash_keys(*orders):
    return [{"order": order, "voucher": f"{order}/P-1"} for order in orders]


def paid_fixture():
    ds = shipped_freight()
    for order, amount in (("FO-1", 40.25), ("FO-2", 59.75), ("FO-3", 100)):
        ds, _ = transport.settle(ds, order, amount, f"BILL-{order}", D0)
        ds, _ = transport.pay_bill(ds, order, order, amount, "WIRE-COMB", P1)
    finance = ds.finance.model_copy(update={"control_roles": {"payments": ["owner@integrity.example"],
                                                           "master_data": ["owner@integrity.example"]}, "closed_through": P2})
    return ds.model_copy(update={"finance": finance})


def saved(reply):
    assert reply.status_code == 200, reply.text
    return Dataset.model_validate(reply.json()["company"]["dataset"])


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_import_split_payment_and_release_preserve_the_ledger(backend, request):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)
    initial = paid_fixture()
    owner, dispatcher, cid = team(initial)
    csv = csv_rows(("MARCH/41", "-100.00"), ("MARCH/42", "-100"))
    payload = {"company": "E1", "account": "BANK-1", "csv": csv}
    refused = bank(dispatcher, cid, "restricted", 1, "import", **payload)
    assert refused.status_code == 403 and "payments" in refused.text
    duplicate = bank(owner, cid, "duplicate-source", 1, "import", **{**payload, "csv": csv_rows(("A", "-1"), ("a", "-1"))})
    assert duplicate.status_code == 409 and "repeats" in duplicate.text
    imported = saved(bank(owner, cid, "sheet-1", 1, "import", **payload))
    assert len(imported.carrier_bank_lines) == 2
    first, second = imported.carrier_bank_lines
    assert view(imported) == view(initial) and view(imported, period_end=P2) == view(initial, period_end=P2)
    unchanged = bank(owner, cid, "overlapping-file", 2, "import", **{**payload, "account": "bank-1"})
    assert unchanged.status_code == 200 and unchanged.json()["revision"] == 2
    conflict = bank(owner, cid, "conflict", 2, "import", **{**payload, "csv": csv_rows(("NEW", "-1"), ("MARCH/41", "-100.01"))})
    assert conflict.status_code == 409 and "conflicts" in conflict.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"] == unchanged.json()["company"]["dataset"]
    assert bank(owner, cid, "wrong-entity", 2, "match", line=first.id, version=0, targets=cash_keys("FO-3")).status_code == 409
    wrong_sum = bank(owner, cid, "wrong-total", 2, "match", line=first.id, version=0, targets=cash_keys("FO-1"))
    assert wrong_sum.status_code == 409 and "exactly" in wrong_sum.text
    legacy = command(owner, cid, "legacy-reserved", "transport", "bill_event", 2, date=P2.isoformat(), order="FO-1", voucher="FO-1",
                     event={"kind": "match_bank", "cash_voucher": "FO-1/P-1", "account": "bank-1", "statement_line": "march/41",
                            "reference": "WIRE-COMB", "amount_minor": -4025, "currency": "INR"})
    assert legacy.status_code == 409 and "was imported" in legacy.text

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _: bank(owner, cid, "bundle", 2, "match", line=first.id, version=0,
                                              targets=cash_keys("FO-2", "FO-1")), range(2)))
    matched = saved(replies[0])
    assert sorted(r.json()["duplicate"] for r in replies) == [False, True]
    assert [v.key() for v in matched.carrier_bank_lines[0].active] == [("FO-1", "FO-1/P-1"), ("FO-2", "FO-2/P-1")]
    demand = payables_view(matched)
    assert [r.voucher for r in demand.carrier_bank.unmatched_cash] == ["FO-3/P-1"]
    assert all(not r.unreconciled_cash for r in demand.carrier_bills if r.order in ("FO-1", "FO-2"))
    used = bank(owner, cid, "second-claim", 3, "match", line=second.id, version=0, targets=cash_keys("FO-1", "FO-2"))
    assert used.status_code == 409 and "unmatched" in used.text
    legacy = command(owner, cid, "legacy-cash", "transport", "bill_event", 3, date=P2.isoformat(), order="FO-1", voucher="FO-1",
                     event={"kind": "match_bank", "cash_voucher": "FO-1/P-1", "account": "OTHER", "statement_line": "L",
                            "reference": "WIRE-COMB", "amount_minor": -4025, "currency": "INR"})
    assert legacy.status_code == 409 and "already belongs" in legacy.text
    raw = matched.model_dump(mode="json")
    raw["carrier_bank_lines"][0]["reference"] = "changed"
    assert save(owner, cid, raw, 3).status_code == 403
    assert client.post("/api/companies", json={"dataset": raw}, headers=h(owner)).status_code == 422

    released = saved(bank(owner, cid, "release", 3, "release", line=first.id, version=1))
    assert len(payables_view(released).carrier_bank.unmatched_cash) == 3
    rematched = saved(bank(owner, cid, "rematch", 4, "match", line=first.id, version=2, targets=cash_keys("FO-1", "FO-2")))
    assert bank(owner, cid, "stale-release", 5, "release", line=first.id, version=1).status_code == 409
    assert [len(event.targets) for event in rematched.carrier_bank_lines[0].history] == [2, 0, 2]
    assert view(rematched) == view(initial)


def test_refund_bundle_and_identical_legacy_statement_import():
    data = paid_fixture()
    data = data.model_copy(update={"finance": data.finance.model_copy(update={"closed_through": None, "control_roles": {}})})
    owner, _, cid = team(data)

    def bill_event(identifier, revision, order, kind, **values):
        return command(owner, cid, identifier, "transport", "bill_event", revision, date=P2.isoformat(), order=order,
                       voucher=order, event={"kind": kind, **values})

    saved(bill_event("old-match", 1, "FO-1", "match_bank", cash_voucher="FO-1/P-1", account="BANK-1", statement_line="OLD/1",
                     reference="WIRE-COMB", amount_minor=-4025, currency="INR"))
    legacy_csv = csv_rows(("OLD/1", "-40.25")).replace(P1.isoformat(), P2.isoformat())
    imported = bank(owner, cid, "legacy-sheet", 2, "import", company="E1", account="bank-1", csv=legacy_csv)
    assert imported.status_code == 200 and imported.json()["revision"] == 2
    assert not saved(imported).carrier_bank_lines
    for rev, order, amount in ((2, "FO-1", 1025), (4, "FO-2", 975)):
        saved(bill_event(f"credit-{order}", rev, order, "adjust_bill", reference=f"CR-{order}", reason="Rate", amount_minor=amount))
        refunded = saved(bill_event(f"refund-{order}", rev + 1, order, "refund_bill", reference="IN-BUNDLE", amount_minor=amount))
    assert view(refunded).checks and all(x.ok for x in view(refunded).checks)
    statement = saved(bank(owner, cid, "refund-sheet", 6, "import", company="E1", account="BANK-1",
                           csv=csv_rows(("REF/1", "20.00")).replace("WIRE-COMB", "IN-BUNDLE")))
    row = statement.carrier_bank_lines[0]
    targets = [{"order": "FO-1", "voucher": "FO-1/R-3"}, {"order": "FO-2", "voucher": "FO-2/R-2"}]
    matched = saved(bank(owner, cid, "both-refunds", 7, "match", line=row.id, version=0, targets=targets))
    assert {p.voucher for p in payables_view(matched).carrier_bank.unmatched_cash} == {"FO-2/P-1", "FO-3/P-1"}
    assert view(matched) == view(refunded)
