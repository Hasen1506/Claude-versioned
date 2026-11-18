"""Dated supplier invoice cancellations must unwind only the amounts actually matched."""
from datetime import date

import pytest

from scp.accounting import view
from scp.actuals.documents import reverse
from scp.backup import backup, backup_postgres, restore
from scp import admin
from scp.companies import get_companies
from scp.model import Dataset, MovementType
from scp.purchasing import act
from scp.versions.store import Store, set_store

from .test_accounting import checks, tb
from .test_backup_postgres import pg_databases as pg_databases
from .test_company_commands import command
from .test_companies import h, new_company, signup
from .test_enterprise_integrity import client, team
from .test_valuation import company


PO = "PO-00001"
LINE = "PO-00001-10"


def day(number):
    return date(2026, 1, number)


def buy(control="moving_average"):
    return Dataset.model_validate(company(control, on_hand=0))


def bill(ds, qty, price, on, **options):
    return act(ds, "enter_invoice", PO, on=day(on), tax=0,
               lines=[{"order": LINE, "qty": qty, "price": price}], **options)[0]


def receive(ds, qty, on):
    return act(ds, "receive", PO, on=day(on), lines=[{"id": LINE, "qty": qty}])[0]


@pytest.mark.parametrize("control,stock,price_difference", [("moving_average", 1700, 0), ("standard", 1500, 200)])
def test_cancelling_an_advance_clears_grir_and_excludes_it_from_a_later_receipt(control, stock, price_difference):
    x = bill(buy(control), 100, 12, 5)
    original = view(x, period_end=day(5))
    x, _ = act(x, "cancel_invoice", "SI-00001", on=day(6))
    assert view(x, period_end=day(5)) == original
    assert tb(x, end=day(6)) == {"STOCK": 700, "OPENING": -700}
    assert not checks(x, day(6))
    x = receive(x, 100, 7)
    expected = {"STOCK": stock, "OPENING": -700, "GRIR": -1000}
    if price_difference:
        expected["PRICE_DIFF"] = price_difference
    assert tb(x, end=day(7)) == expected
    assert not checks(x, day(7))


def test_partly_received_invoice_cancellation_restores_order_cost_and_existing_unbilled_receipts():
    x = receive(bill(buy(), 100, 12, 5), 40, 6)
    assert tb(x, end=day(6)) == {"STOCK": 1180, "OPENING": -700, "PAYABLES": -1200, "GRIR": 720}
    x, _ = act(x, "cancel_invoice", "SI-00001", on=day(7))
    assert tb(x, end=day(7)) == {"STOCK": 1100, "OPENING": -700, "GRIR": -400}
    assert not checks(x, day(7))
    x = receive(x, 60, 8)
    assert tb(x, end=day(8)) == {"STOCK": 1700, "OPENING": -700, "GRIR": -1000}


def test_cancellation_releases_receipts_to_another_advance_at_its_own_price():
    x = bill(buy(), 40, 12, 5)
    x = bill(x, 60, 14, 6)
    assert tb(x, end=day(6))["GRIR"] == 1320
    assert not checks(x, day(6))
    x = receive(x, 50, 7)
    assert tb(x, end=day(7)) == {"STOCK": 1320, "OPENING": -700, "PAYABLES": -1320, "GRIR": 700}
    x, _ = act(x, "cancel_invoice", "SI-00001", on=day(8))
    assert tb(x, end=day(8)) == {"STOCK": 1400, "OPENING": -700, "PAYABLES": -840, "GRIR": 140}
    assert not checks(x, day(8))
    x = receive(x, 50, 9)
    assert tb(x, end=day(9)) == {"STOCK": 1940, "OPENING": -700, "PAYABLES": -840, "GRIR": -400}
    assert not checks(x, day(9))


@pytest.mark.parametrize("cancel_first", [False, True])
@pytest.mark.parametrize("control", ["moving_average", "standard"])
@pytest.mark.parametrize("landed_costs", [False, True])
def test_receipt_reversal_and_invoice_cancellation_reconcile_in_both_orders(cancel_first, control, landed_costs):
    raw = buy(control).model_dump(mode="json")
    if landed_costs:
        raw["purchasing_sources"][0]["duty_rate"] = .2
        raw["locations"][0]["handling_cost_per_unit"] = 2
    x = receive(bill(Dataset.model_validate(raw), 100, 12, 5), 40, 6)
    receipt = next(m.id for m in x.movements if m.type is MovementType.RECEIPT)
    if cancel_first:
        x, _ = act(x, "cancel_invoice", "SI-00001", on=day(7))
        x, _ = reverse(x, receipt, on=day(8))
    else:
        x, _ = reverse(x, receipt, on=day(7))
        assert tb(x, end=day(7)) == {"STOCK": 700, "OPENING": -700, "PAYABLES": -1200, "GRIR": 1200}
        x, _ = act(x, "cancel_invoice", "SI-00001", on=day(8))
    assert tb(x, end=day(8)) == {"STOCK": 700, "OPENING": -700}
    assert not checks(x, day(8))


def test_receipt_reversal_reopens_two_original_advance_prices_in_order():
    x = bill(bill(buy(), 40, 12, 5), 60, 14, 6)
    x = receive(x, 50, 7)
    receipt = next(m.id for m in x.movements if m.type is MovementType.RECEIPT)
    x, _ = reverse(x, receipt, on=day(8))
    assert tb(x, end=day(8)) == {"STOCK": 700, "OPENING": -700, "PAYABLES": -1320, "GRIR": 1320}
    x = receive(x, 50, 9)
    assert tb(x, end=day(9)) == {"STOCK": 1320, "OPENING": -700, "PAYABLES": -1320, "GRIR": 700}
    assert not checks(x, day(9))


@pytest.mark.parametrize("kind,expected", [("subsequent_debit", 1730), ("subsequent_credit", 1670)])
def test_subsequent_price_correction_cancellation_reverses_delivery_costs(kind, expected):
    x = bill(receive(buy(), 100, 5), 100, 10, 6)
    original = tb(x, end=day(6))
    x = bill(x, 100, .2, 7, kind=kind, delivery_costs=10)
    assert tb(x, end=day(7))["STOCK"] == expected
    reference = x.supplier_invoices[-1].id
    x, _ = act(x, "cancel_invoice", reference, on=day(8))
    assert tb(x, end=day(8)) == original
    assert not checks(x, day(8))


def test_live_command_cancellation_and_receipt_apply_once_and_reconcile():
    owner, _, cid = team(buy())
    invoice = command(owner, cid, "advance-1", "purchasing", "enter_invoice", date="2026-01-05",
                      po=PO, tax=0, lines=[{"order": LINE, "qty": 100, "price": 12}])
    assert invoice.status_code == 200, invoice.text
    args = (owner, cid, "advance-cancel-1", "purchasing", "cancel_invoice")
    cancelled = command(*args, revision=2, po="SI-00001", date="2026-01-06")
    assert cancelled.status_code == 200, cancelled.text
    received = command(owner, cid, "receipt-1", "purchasing", "receive", revision=3, po=PO,
                       date="2026-01-07", lines=[{"id": LINE, "qty": 100}])
    assert received.status_code == 200, received.text
    replay = command(*args, revision=2, po="SI-00001", date="2026-01-06")
    assert replay.status_code == 200, replay.text
    result = replay.json()
    assert result["duplicate"] and result["revision"] == 3 and result["company"]["meta"]["revision"] == 4
    x = Dataset.model_validate(result["company"]["dataset"])
    assert tb(x, end=day(7)) == {"STOCK": 1700, "OPENING": -700, "GRIR": -1000}
    assert not checks(x, day(7))


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_recovery_replays_post_backup_commands_and_preserves_existing_receipts(backend, request, tmp_path, monkeypatch):
    make_db = request.getfixturevalue("pg_databases") if backend == "postgresql" else None
    source = make_db() if make_db is not None else str(tmp_path / "source.sqlite")
    live = Store(source)
    set_store(live)
    try:
        owner = signup("recovery@advance.example.invalid")
        raw = buy().model_dump(mode="json", exclude={"purchase_valuation"})
        cid = new_company(owner, raw)
        invoice = command(owner, cid, "advance", "purchasing", "enter_invoice", date="2026-01-05",
                          po=PO, tax=0, lines=[{"order": LINE, "qty": 100, "price": 12}])
        assert invoice.status_code == 200, invoice.text
        snapshot = (backup_postgres(source, tmp_path / "backup") if make_db is not None
                    else backup(live.db, tmp_path / "backup"))

        def replay_after_snapshot():
            cancelled = command(owner, cid, "cancel", "purchasing", "cancel_invoice", revision=2,
                                po="SI-00001", date="2026-01-06")
            assert cancelled.status_code == 200 and not cancelled.json()["duplicate"], cancelled.text
            received = command(owner, cid, "receipt", "purchasing", "receive", revision=3, po=PO,
                               date="2026-01-07", lines=[{"id": LINE, "qty": 100}])
            assert received.status_code == 200 and not received.json()["duplicate"], received.text
            return received.json()["company"]["dataset"]

        want = replay_after_snapshot()
    finally:
        live.db.close()

    if make_db is not None:
        target = make_db()
        monkeypatch.setenv("DATABASE_URL", target)
        assert admin.main(["restore", str(snapshot)]) == 0
    else:
        target = str(tmp_path / "restored.sqlite")
        restore(snapshot, target)
    recovered = Store(target)
    set_store(recovered)
    try:
        existing = command(owner, cid, "advance", "purchasing", "enter_invoice", date="2026-01-05",
                           po=PO, tax=0, lines=[{"order": LINE, "qty": 100, "price": 12}])
        assert existing.status_code == 200 and existing.json()["duplicate"], existing.text
        assert existing.json()["company"]["meta"]["revision"] == 2
        got = replay_after_snapshot()
        assert got == want
        repeated = command(owner, cid, "receipt", "purchasing", "receive", revision=3, po=PO,
                           date="2026-01-07", lines=[{"id": LINE, "qty": 100}])
        assert repeated.status_code == 200 and repeated.json()["duplicate"], repeated.text
        assert repeated.json()["company"]["meta"]["revision"] == 4
        assert tb(Dataset.model_validate(got), end=day(7)) == {"STOCK": 1700, "OPENING": -700, "GRIR": -1000}
        c = get_companies()
        assert c.db.execute("SELECT count(*) FROM company_commands WHERE company_id = ?", (cid,)).fetchone()[0] == 3
        assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"] == want
    finally:
        recovered.db.close()
