"""Cash the plan needs, week by week (Enterprise 8.3; docs/CONFORMANCE.md §8, F15). Hand-worked: every amount, the
day it falls due on its payment terms and the week it lands in, and the running total's lowest point."""
from __future__ import annotations

from datetime import date

from scp.finance import run_finance
from scp.finance.cash import cash_view
from scp.model import Dataset
from scp.plan import run_mrp

D0 = date(2026, 3, 2)          # a Monday: weeks start 2, 9, 16, 23 March


def company(**kw) -> dict:
    """DC W holds 1,000 X (sold at 100); customer C pays net 15. Open: SO-1 for 10 X at 90 wanted 4 Mar; a forecast
    of 20 X for 20 Mar; invoice INV-1 of 500, 100 paid, due 20 Feb; PO-1 for 50 X at 2 due 5 Mar from S (paid net 7);
    freight order FO-1 of 600 loading 3 Mar with carrier K (paid in 10 days)."""
    d = {
        "settings": {"planning_start": D0.isoformat(), "horizon_days": 28},
        "locations": [{"id": "W", "type": "dc"}, {"id": "C", "type": "customer"}, {"id": "S", "type": "supplier"}],
        "products": [{"id": "X", "type": "FG", "price": 100, "weight_kg": 1}],
        "location_products": [{"location": "W", "product": "X", "on_hand": 1000}],
        "purchasing_sources": [{"id": "B-X", "supplier": "S", "location": "W", "product": "X", "price": 2,
                                "lead_time_days": 2}],
        "lanes": [{"id": "L", "origin": "W", "destination": "C", "modes": [{"mode": "truck_ftl", "transit_days": 1}]}],
        "payment_terms": [{"id": "N15", "net_days": 15}],
        "customers": [{"customer": "C", "payment_terms": "N15"}],
        "vendors": [{"supplier": "S", "payment_terms_days": 7}],
        "demand": [{"id": "SO-1", "location": "C", "product": "X", "date": "2026-03-04", "qty": 10,
                    "kind": "sales_order", "price": 90},
                   {"location": "C", "product": "X", "date": "2026-03-20", "qty": 20}],
        "invoices": [{"id": "INV-1", "customer": "C", "date": "2026-02-05", "due_date": "2026-02-20",
                      "lines": [{"product": "X", "qty": 5, "price": 100}],
                      "payments": [{"date": "2026-02-10", "amount": 100}]}],
        "purchase_orders": [{"id": "PO-1", "supplier": "S", "location": "W", "order_date": "2026-03-01",
                             "sent_on": "2026-03-01"}],
        "receipts": [{"id": "PO-1-10", "kind": "purchase", "location": "W", "product": "X", "qty": 50,
                      "due_date": "2026-03-05", "source": "B-X", "po": "PO-1", "price": 2}],
        "carriers": [{"id": "K", "payment_days": 10, "rates": [{"lane": "L", "per_shipment": 600}]}],
        "freight_orders": [{"id": "FO-1", "lane": "L", "mode": "truck_ftl", "carrier": "K", "ship_from": "W",
                            "ship_to": "C", "planned_on": "2026-03-03", "deliveries": ["DL-X"], "planned_cost": 600,
                            "status": "accepted"}],
    }
    d.update(kw)
    return d


def view(d: dict):
    ds = Dataset.model_validate(d)
    return cash_view(ds, run_mrp(ds))


def test_each_amount_falls_due_on_its_terms_in_its_week():
    v = view(company())
    # week 1 (2 Mar): INV-1's 400, overdue since 20 Feb. Week 2 (9 Mar): PO-1's 100 arrives 5 Mar, paid 12 Mar; FO-1's
    # 600 loads 3 Mar, paid 13 Mar. Week 3 (16 Mar): SO-1's 10 × 90 wanted 4 Mar, paid 19 Mar. The forecast's
    # 20 × 100 wanted 20 Mar is paid 4 Apr, after the last week.
    assert [(w.start.isoformat(), w.receipts, w.payments, w.cumulative) for w in v.weeks] == [
        ("2026-03-02", 400, 0, 400), ("2026-03-09", 0, 700, -300), ("2026-03-16", 900, 0, 600),
        ("2026-03-23", 0, 0, 600)]
    assert v.weeks[1].by == {"purchase_orders": -100, "freight": -600}
    assert v.weeks[2].by == {"orders": 900}
    assert (v.lowest, v.lowest_week) == (-300, date(2026, 3, 9))
    assert (v.overdue_in, v.overdue_out, v.later_in, v.later_out) == (400, 0, 2000, 0)
    assert (v.receipts, v.payments) == (1300, 700)


def test_credit_notes_received_lines_settled_freight_and_unpriced_sales():
    d = company()
    d["invoices"].append({"id": "CN-1", "kind": "credit_note", "customer": "C", "date": "2026-03-01",
                          "due_date": "2026-03-10", "lines": [{"product": "X", "qty": 1, "price": 100}]})
    d["freight_orders"][0].update(status="settled", billed=650, settled_on="2026-03-05")   # due 15 Mar
    d["movements"] = [{"id": "GM-1", "date": "2026-02-27", "type": "receipt", "location": "W", "product": "X",
                       "qty": 20, "reference": "PO-1-10"}]                                  # 20 in, not invoiced
    d["products"][0]["price"] = None
    v = view(d)
    by = {w.start.isoformat(): w.by for w in v.weeks}
    # the credit note pays 100 back on 10 Mar; the bill's 650 on 15 Mar; the 20 received are owed from now
    # (paid 9 Mar) and 30 still come on 5 Mar (paid 12 Mar): 40 + 60; SO-1 has its own price, the forecast none
    assert by["2026-03-09"] == {"invoices": -100, "purchase_orders": -100, "freight": -650}
    assert v.unpriced == 1 and v.later_in == 0 and "no price" in v.notes[0]


def test_the_plans_buying_production_and_transfers_are_paid_when_they_fall_due():
    d = company(freight_orders=[], invoices=[], purchase_orders=[], receipts=[])
    d["location_products"][0]["on_hand"] = 0                 # the 10 for SO-1 must be bought: 2 days, at 2
    p = run_mrp(Dataset.model_validate(d))
    buys = [(o.qty, o.due_date, sum(o.costs.values())) for o in p.orders if o.kind == "buy"]
    assert buys == [(10, date(2026, 3, 4), 20), (20, date(2026, 3, 19), 40)]   # SO-1's 10 and the forecast's 20
    v = cash_view(Dataset.model_validate(d), p)
    # they arrive 4 and 19 Mar and are paid net 7, on 11 and 26 Mar: the weeks of 9 and 23 Mar
    assert [(w.start.isoformat(), w.by.get("planned_buying")) for w in v.weeks if "planned_buying" in w.by] == [
        ("2026-03-09", -20), ("2026-03-23", -40)]
    assert run_finance(Dataset.model_validate(company())).cash is not None


def test_shipped_lines_are_to_bill_not_to_sell_and_the_weeks_end_where_they_end():
    d = company()
    d["invoices"] += [
        {"id": "INV-2", "customer": "C", "date": "2026-02-15", "due_date": "2026-03-01",      # the day before: overdue
         "lines": [{"product": "X", "qty": 1, "price": 50}]},
        {"id": "INV-3", "customer": "C", "date": "2026-03-15", "due_date": "2026-03-30",      # the day after: later
         "lines": [{"product": "X", "qty": 1, "price": 70}]}]
    d["movements"] = [{"id": "GM-2", "date": "2026-02-28", "type": "sale", "location": "W", "product": "X", "qty": 4,
                       "reference": "SO-1"}]                 # 4 of SO-1 shipped, not billed, not booked by a new week
    d["supplier_invoices"] = [{"id": "SI-1", "supplier": "S", "date": "2026-03-01", "due_date": "2026-03-11",
                               "lines": [{"order": "PO-1-10", "product": "X", "qty": 10, "price": 2}]}]
    v = view(d)
    by = {w.start.isoformat(): w.by for w in v.weeks}
    assert by["2026-03-02"] == {"invoices": 450}                                  # 400 + 50, both overdue
    assert by["2026-03-09"] == {"purchase_orders": -100, "freight": -600, "supplier_invoices": -20}
    # the 4 shipped are billed now, paid 17 Mar: 360; the 6 still to ship at 90, paid 19 Mar: 540 (not 900)
    assert by["2026-03-16"] == {"to_bill": 360, "orders": 540}
    assert (v.overdue_in, v.later_in) == (450, 2070)


def test_production_and_transfers_are_paid_when_they_start():
    from .factory import base
    d = base(horizon=28)
    d["locations"].append({"id": "D", "type": "dc"})
    d["lanes"] = [{"id": "PD", "origin": "P", "destination": "D", "modes": [{"transit_days": 2, "cost_per_unit": 3}]}]
    d["demand"] = [{"location": "D", "product": "A", "date": "2026-01-20", "qty": 30}]
    ds = Dataset.model_validate(d)
    p = run_mrp(ds)
    v = cash_view(ds, p)
    paid: dict[str, float] = {}
    for o in p.orders:
        if o.kind != "buy":
            wk = ((o.start_date - ds.settings.planning_start).days // 7)
            paid[f"{o.kind}{wk}"] = paid.get(f"{o.kind}{wk}", 0) + sum(o.costs.values())
    assert any(o.kind == "transfer" for o in p.orders) and any(o.kind == "make" for o in p.orders)
    assert next(o for o in p.orders if o.kind == "transfer").costs["transport"] == 90      # 30 × 3
    got = {f"{'make' if k == 'production' else 'transfer'}{i}": -x for i, w in enumerate(v.weeks)
           for k, x in w.by.items() if k in ("production", "transfers")}
    assert got == {k: round(x, 2) for k, x in paid.items()}
