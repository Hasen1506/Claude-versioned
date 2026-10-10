"""Working-capital KPIs on the Performance page: inventory turns, DIO, DSO, DPO and the cash-to-cash cycle, each
against a hand calculation, and each showing no value ("not enough data") rather than a guess when the data the
system holds does not support one."""
from __future__ import annotations

import pytest

from scp.tower import run_tower

from .factory import base, ds, lp


def company() -> dict:
    """Planning start Mon 5 Jan 2026, KPI window 91 days. Stock: 10 A at 50 + 30 B at 10 + 0 C = 800."""
    d = base()
    d["locations"].append({"id": "K", "type": "customer"})
    lp(d, "P", "A")["unit_cost"] = 50
    lp(d, "P", "B")["unit_cost"] = 10
    lp(d, "P", "C")["unit_cost"] = 5
    # goods issued to customers: 20 + 12 A = 32 × 50 = 1,600 of COGS, the first on 4 Nov (62 days before the start)
    d["movements"] = [
        {"id": "g1", "date": "2025-11-04", "type": "sale", "location": "P", "product": "A", "qty": 20, "counterparty": "K"},
        {"id": "g2", "date": "2025-12-15", "type": "sale", "location": "P", "product": "A", "qty": 12, "counterparty": "K"},
    ]
    inv = lambda i, day, due, q, kind="invoice", pays=(): {  # noqa: E731
        "id": i, "kind": kind, "customer": "K", "date": day, "due_date": due,
        "lines": [{"product": "A", "qty": q, "price": 100}], "payments": [{"date": p, "amount": a} for p, a in pays]}
    d["invoices"] = [
        inv("INV1", "2025-11-10", "2025-12-10", 20, pays=[("2025-12-08", 2000)]),          # 2,000, paid
        inv("INV2", "2025-12-20", "2026-01-19", 12, pays=[("2026-01-02", 200),             # 1,200, 1,000 open
                                                          ("2026-01-06", 100)]),           # after the start: not yet
        inv("CN1", "2025-12-22", "2025-12-22", 1, kind="credit_note"),                     # 100 still to pay back
        {**inv("INV0", "2025-12-01", "2025-12-31", 5), "cancelled": True},                  # cancelled: never counts
    ]
    sup = lambda i, day, q, pays=(), **kw: {  # noqa: E731
        "id": i, "supplier": "S", "date": day, "due_date": day, "lines": [{"order": "PO1", "product": "B", "qty": q,
                                                                           "price": 10}],
        "payments": [{"date": p, "amount": a} for p, a in pays], **kw}
    d["supplier_invoices"] = [
        sup("SI1", "2025-11-01", 50, pays=[("2025-12-01", 500)]),        # 500, paid
        sup("SI2", "2025-12-10", 100),                                    # 1,000 open
        sup("SI3", "2025-12-11", 10, currency="USD"),                     # no USD rate: left out, and said so
    ]
    return d


def kpis(d: dict) -> dict:
    res = run_tower(ds(d), record=False)
    return {k.id: k for k in res.kpis}


# the average stock over the 62 days from the first goods issue: 22 A for the 41 days before the second issue (15 Dec),
# 10 A for the 21 days after it, and 30 B throughout
AVG = (22 * 41 + 10 * 21) / 62 * 50 + 30 * 10
# DSO counted back from 4 Jan: 13 days with no billing, 22 Dec (a 100 credit: 1,000 left), 21 Dec, then 1,000 of the
# 1,200 billed on 20 Dec
DSO = 15 + 1000 / 1200


def test_working_capital_against_hand_calculation():
    k = kpis(company())
    assert k["dio"].value == pytest.approx(AVG / 1600 * 62)                     # 46.4 days
    assert k["dio"].numerator == pytest.approx(AVG)
    assert "on the planning start 800" in k["dio"].note                         # the closing stock, for reference
    assert k["inventory_turns"].value == pytest.approx(1600 / 62 * 365 / AVG)
    assert k["inventory_turns"].unit == "times"
    # receivables 1,000 − 100 = 900; billed 2,000 + 1,200 − 100 = 3,100 over 56 days (first invoice 10 Nov)
    assert k["dso"].value == pytest.approx(DSO)
    assert k["dso"].numerator == pytest.approx(900) and k["dso"].denominator == pytest.approx(3100)
    assert f"by the average of the period {900 / 3100 * 56:,.1f} days" in k["dso"].note
    # payables 1,000; billed 500 + 1,000 = 1,500 over 65 days (first supplier invoice 1 Nov); the USD one left out
    assert k["dpo"].value == pytest.approx(1000 / 1500 * 65)
    assert "1 supplier invoice(s) in a currency without an exchange rate" in k["dpo"].note
    assert k["cash_to_cash"].value == pytest.approx(AVG / 1600 * 62 + DSO - 1000 / 1500 * 65)
    for i in ("inventory_turns", "dio", "dso", "dpo", "cash_to_cash"):
        assert k[i].definition and k[i].source            # every formula is stated on the page


def test_a_foreign_supplier_invoice_counts_at_the_company_rate():
    d = company()
    d["settings"]["fx_rates"] = {"USD": 80}
    k = kpis(d)                                            # SI3: 100 USD × 80 = 8,000, open
    assert k["dpo"].value == pytest.approx(9000 / 9500 * 65)
    assert "exchange rate" not in k["dpo"].note


def test_breakdowns_add_up():
    k = kpis(company())
    by = {r.label: r for r in k["dso"].breakdown}
    assert by["K"].value == pytest.approx(k["dso"].value)
    assert {r.label for r in k["cash_to_cash"].breakdown} == {"DIO", "DSO", "DPO"}


def test_no_records_shows_not_enough_data_never_a_number():
    d = company()
    d["movements"], d["invoices"], d["supplier_invoices"] = [], [], []
    k = kpis(d)
    for i in ("inventory_turns", "dio", "dso", "dpo", "cash_to_cash"):
        assert k[i].value is None, i
        assert k[i].note.startswith("Not enough data"), (i, k[i].note)
        assert k[i].status == "none"
    assert "DIO, DSO, DPO have no value yet" in k["cash_to_cash"].note


def test_too_short_a_history_shows_not_enough_data():
    """Two weeks of invoices would make a DSO from a fraction of the period: no value until four weeks of records."""
    d = company()
    for i in d["invoices"]:
        i["date"] = "2025-12-26"
        for p in i["payments"]:
            p["date"] = max(p["date"], "2025-12-26")
    k = kpis(d)
    assert k["dso"].value is None
    assert k["dso"].note == "Not enough data: customer invoices only for 10 days; at least 28 are needed."
    assert k["cash_to_cash"].value is None and k["dio"].value is not None and k["dpo"].value is not None


def test_records_older_than_the_window_still_count_as_open_but_not_as_billed():
    """An invoice billed before the window still owes money on the planning start, but sales billed are the window's."""
    d = company()
    d["invoices"].append({"id": "OLD", "customer": "K", "date": "2025-06-02", "due_date": "2025-07-02",
                          "lines": [{"product": "A", "qty": 3, "price": 100}]})
    k = kpis(d)
    assert k["dso"].numerator == pytest.approx(1200) and k["dso"].denominator == pytest.approx(3100)
    # counted back: 1,100 left after 20 Dec takes 1,200 ... the 100 more reach back to the 2,000 billed on 10 Nov
    assert k["dso"].value == pytest.approx(55 + 100 / 2000)


def test_a_large_receipt_just_before_the_start_barely_moves_the_average_stock():
    """Closing stock would triple DIO with one receipt on the last day; the average of the days moves by a day's worth."""
    d = company()
    lp(d, "P", "A")["on_hand"] = 310
    d["movements"].append({"id": "r1", "date": "2026-01-04", "type": "receipt", "location": "P", "product": "A",
                           "qty": 300})
    k = kpis(d)
    assert k["dio"].numerator == pytest.approx(AVG + 300 * 50 / 62)        # one day of the 62 holds the 300
    assert "on the planning start 15,800" in k["dio"].note


def test_receivables_and_payables_are_aged_by_days_past_due():
    d = company()
    d["invoices"].append({"id": "LATE", "customer": "K", "date": "2025-10-01", "due_date": "2025-10-31",
                          "lines": [{"product": "A", "qty": 4, "price": 100}]})          # 66 days overdue
    d["invoices"].append({"id": "MID", "customer": "K", "date": "2025-11-01", "due_date": "2025-11-20",
                          "lines": [{"product": "A", "qty": 2, "price": 100}]})          # 46 days overdue
    k = kpis(d)
    age = {r.label: (r.value, r.numerator) for r in k["dso"].ageing}
    assert age == {"not yet due": (1000, 1), "31–60 days overdue": (200, 1), "over 60 days overdue": (400, 1),
                   "credit to settle": (-100, 1)}
    assert sum(v for v, _ in age.values()) == pytest.approx(k["dso"].numerator)
    pay = {r.label: (r.value, r.numerator) for r in k["dpo"].ageing}
    assert pay == {"1–30 days overdue": (1000, 1)}                          # SI2 due 10 Dec: 26 days late


def test_the_cash_to_cash_trend_is_weekly_and_ends_on_the_planning_start():
    k = kpis(company())
    tr = k["cash_to_cash"].trend
    assert len(tr) == 12 and [p.as_of.isoformat() for p in tr][-2:] == ["2025-12-29", "2026-01-05"]
    assert tr[-1].value == pytest.approx(k["cash_to_cash"].value, abs=1e-3)
    # early weeks have under 28 days of invoices or goods issued: no value, never a guess
    assert tr[0].value is None and any(p.value is not None for p in tr)
    assert len(k["dso"].trend) == len(k["dio"].trend) == len(k["dpo"].trend) == 12
