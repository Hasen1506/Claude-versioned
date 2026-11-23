"""Literal yen and fils oracles for the supported material posting scope."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest

from scp.accounting import view
from scp.model import Dataset

from .factory import base, lp
from .test_commercial_integrity import save
from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client, team


@pytest.mark.parametrize(("currency", "price", "booked", "left", "decimals"), [
    ("JPY", 600.25, "1201", "601", 0),
    ("KWD", 1.2345, "2.469", "1.235", 3),
])
def test_material_currency_receipt_and_partial_reversals_reconcile_to_the_receipt(currency, price, booked, left, decimals):
    raw = base()
    raw["settings"]["currency"] = currency
    raw["execution"] = {"price_control": "moving_average"}
    lp(raw, "P", "A")["on_hand"] = lp(raw, "P", "B")["on_hand"] = 0
    raw["purchase_orders"] = [{"id": "PO-1", "supplier": "S", "location": "P", "order_date": "2026-01-05"}]
    raw["receipts"] = [{"id": "PO-1-10", "po": "PO-1", "kind": "purchase", "product": "B", "location": "P",
                        "qty": 2, "price": price, "due_date": "2026-01-06", "source": "PIR-B"}]
    owner, _, company = team(Dataset.model_validate(raw))
    posted = command(owner, company, "receipt", "purchasing", "receive", 1, date="2026-01-06",
                     po="PO-1", lines=[{"id": "PO-1-10", "qty": 2}])
    assert posted.status_code == 200, posted.text
    current = Dataset.model_validate(posted.json()["company"]["dataset"])
    original = current.movements[0]
    assert current.purchase_valuation[0].base == price

    def assert_books(data, day, expected):
        books = view(data, period_end=day)
        assert all(check.ok for check in books.checks)
        assert all(v.debit == v.credit for v in books.vouchers)
        rows = {r.account: Decimal(str(r.balance)) for r in books.balances}
        assert rows.get("STOCK", 0) == Decimal(expected)
        assert rows.get("GRIR", 0) == -Decimal(expected)
        assert set(rows) <= {"STOCK", "GRIR"}

    assert_books(current, date(2026, 1, 6), booked)
    for revision, day in enumerate((date(2026, 1, 7), date(2026, 1, 8)), start=2):
        reversal = original.model_copy(update={"id": f"REV-{revision}", "qty": 1, "date": day, "final": False,
                                               "doc": f"MD-REV-{revision}", "reversal_of": original.id})
        changed = current.model_copy(update={"movements": [*current.movements, reversal]})
        result = save(owner, company, changed, revision)
        assert result.status_code == 200, result.text
        current = Dataset.model_validate(client.get(f"/api/companies/{company}", headers=h(owner)).json()["dataset"])
        assert_books(current, day, left if revision == 2 else "0")
        assert_books(current, date(2026, 1, 6), booked)

    export = client.post("/api/accounting/export?format=csv", json=current.model_dump(mode="json"))
    assert export.status_code == 200, export.text
    rows = list(csv.DictReader(StringIO(export.json()["text"])))
    stock = [row for row in rows if row["account"] == "STOCK"]
    assert [(row["debit"], row["credit"]) for row in stock] == [
        (booked, f"{0:.{decimals}f}"),
        (f"{0:.{decimals}f}", f"{Decimal(booked) - Decimal(left):.{decimals}f}"),
        (f"{0:.{decimals}f}", left),
    ]
    tally = client.post("/api/accounting/export?format=tally", json=current.model_dump(mode="json"))
    assert tally.status_code == 409 and "Tally precision" in tally.text

    # Existing posting facts cannot be reinterpreted by switching the company currency.
    currency_change = current.model_copy(update={"settings": current.settings.model_copy(update={"currency": "INR"})})
    rejected = save(owner, company, currency_change, 4)
    assert rejected.status_code == 403 and "controlled migration" in rejected.text


def test_standard_cost_posts_the_exact_difference_between_rounded_stock_and_receipt_amounts():
    raw = base()
    raw["settings"]["currency"] = "KWD"
    raw["location_products"] = [lp(raw, "P", "B")]
    raw["location_products"][0]["on_hand"] = 0
    raw["purchasing_sources"][0]["price"] = 1.234
    raw["receipts"] = [{"id": "ONE", "kind": "purchase", "product": "B", "location": "P", "qty": 1,
                        "price": 1.2345, "due_date": "2026-01-06", "source": "PIR-B"}]
    raw["movements"] = [{"id": "R-1", "date": "2026-01-06", "type": "receipt", "reference": "ONE",
                         "location": "P", "product": "B", "qty": 1, "standard_price": 1.234}]
    result = view(Dataset.model_validate(raw))
    assert {row.account: Decimal(str(row.balance)) for row in result.balances} == {
        "STOCK": Decimal("1.234"), "GRIR": Decimal("-1.235"), "PRICE_DIFF": Decimal("0.001"),
    }
    assert all(check.ok for check in result.checks)
    assert result.vouchers[0].debit == result.vouchers[0].credit == 1.235
