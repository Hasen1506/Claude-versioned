"""Foreign partial payments clear the original liability in company currency."""
from datetime import date

import pytest

from scp.accounting import view
from scp.model import Dataset
from scp.purchasing import act

from .test_accounting import tb
from .test_procure_to_pay import ordered


@pytest.mark.parametrize("second_rate,bank,exchange", [(82.35, -16471.64, 0), (83.45, -16581.65, 110.01)])
def test_two_foreign_partial_payments_clear_a_rounded_liability(second_rate, bank, exchange):
    raw = ordered(tax_rate=0)
    raw["settings"]["fx_rates"] = {"USD": 82.35}
    raw["purchase_orders"][0].update(currency="USD", fx_rate=82.35)
    raw["receipts"][0].update(qty=2, price=100.01)
    raw["receipts"] = raw["receipts"][:1]
    ds, _ = act(Dataset.model_validate(raw), "receive", "PO-00001", on=date(2026, 1, 5),
                lines=[{"id": "PO-00001-10", "qty": 2}])
    ds, _ = act(ds, "enter_invoice", "PO-00001", on=date(2026, 1, 6), tax=0)
    assert tb(ds, end=date(2026, 1, 6))["PAYABLES"] == -16471.65

    ds, _ = act(ds, "pay_invoice", "SI-00001", on=date(2026, 1, 20), amount=100.01)
    interim = view(ds, period_end=date(2026, 1, 20))
    assert {row.account: row.balance for row in interim.balances}["PAYABLES"] == -8235.82
    changed = ds.settings.model_copy(update={"fx_rates": {"USD": second_rate}})
    ds, _ = act(ds.model_copy(update={"settings": changed}), "pay_invoice", "SI-00001",
                on=date(2026, 1, 21), amount=100.01)

    assert ds.supplier_invoices[0].open == 0
    assert view(ds, period_end=date(2026, 1, 20)) == interim
    results = tb(ds, end=date(2026, 1, 21))
    assert results.get("PAYABLES", 0) == results.get("SUSPENSE", 0) == 0
    assert results["BANK"] == bank
    assert results["SETTLEMENT_ROUNDING"] == -.01
    assert results.get("FX_LOSS", 0) == exchange
    assert "FX_GAIN" not in results
