"""Spend and sourcing (Enterprise 8.3; CONFORMANCE §4, B18 and B21): where the buying money goes, each supplier's
share and class, and which bought products at a place have one usable source. Every figure is worked by hand."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from scp.purchasing.spend import spend_view

from .factory import base, ds


def shop() -> dict:
    """Plant P buys B from S at 10 (and from S2 at 12) and C from S at 5; S3 would sell C but is blocked, and an S4
    source for C expired before the planning start (Monday 5 January 2026)."""
    d = base()
    d["locations"] += [{"id": x, "type": "supplier"} for x in ("S2", "S3", "S4")]
    d["purchasing_sources"] += [
        {"id": "PIR-B2", "supplier": "S2", "product": "B", "location": "P", "price": 12, "lead_time_days": 5,
         "priority": 2},
        {"id": "PIR-C3", "supplier": "S3", "product": "C", "location": "P", "price": 4, "lead_time_days": 1,
         "blocked": True},
        {"id": "PIR-C4", "supplier": "S4", "product": "C", "location": "P", "price": 4, "lead_time_days": 1,
         "valid_to": "2025-12-31"}]

    def closed(i, prod, sup, qty, on, ordered=None):
        return {"kind": "purchase", "id": f"PO-{i}", "location": "P", "product": prod, "counterparty": sup,
                "ordered_qty": ordered or qty, "delivered_qty": qty, "due_date": on, "first_delivery": on,
                "last_delivery": on, "closed_on": on}
    # B from S costs 9 from 110 up (a price scale): the 100 delivered of 120 ordered pay 10, so 1,000
    d["purchasing_sources"][0]["price_scales"] = [{"from_qty": 110, "price": 9}]
    d["closed_orders"] = [closed(1, "B", "S", 100, "2025-12-01", ordered=120),
                          closed(2, "C", "S", 50, "2025-11-15"),      # 50 × 5 = 250
                          closed(3, "B", "S", 999, "2024-12-01"),     # more than a year before: not counted
                          closed(4, "A", "S", 7, "2025-12-10")]       # no source for A: left out, said
    return d


def test_spend_per_supplier_and_product_with_the_single_sourced_named():
    # committed: an open line of 20 C at 5 = 100. Planned: 30 B from S at 10 = 300 and 10 B from S2 at 12 = 120.
    # S: 1,000 + 250 + 100 + 300 = 1,650; S2: 120; total 1,770. S opens the ranking (A); S2 starts at 1,650 / 1,770 =
    # 0.932, past 0.8 and before 0.95: B. B has two usable sources; C one (S3 blocked, S4 expired): single, 350 of
    # 1,770 = 19.8 % of the spend
    reqs = [NS(qty=30, price=10, currency=None, supplier="S", location="P", product="B"),
            NS(qty=10, price=12, currency=None, supplier="S2", location="P", product="B")]
    orders = [NS(supplier="S", currency="INR", location="P",
                 lines=[NS(closed=False, open=20, price=5, product="C"),
                        NS(closed=True, open=5, price=5, product="C")])]     # closed short: its 5 never come
    vendors = [NS(supplier="S", on_time=0.9), NS(supplier="S2", on_time=None)]
    v = spend_view(ds(shop()), reqs, orders, vendors)
    s = {x.supplier: x for x in v.suppliers}
    assert (s["S"].spent, s["S"].committed, s["S"].planned, s["S"].total) == (1250, 100, 300, 1650)
    assert (s["S2"].total, s["S2"].abc, s["S"].abc) == (120, "B", "A")
    assert s["S"].share == pytest.approx(1650 / 1770) and v.top_supplier == "S"
    assert (v.total, v.spent, v.committed, v.planned) == (1770, 1250, 100, 420)
    p = {x.product: x for x in v.sourcing}
    assert (p["B"].sources, p["B"].single, p["B"].suppliers, p["B"].total) == (2, False, ["S", "S2"], 1420)
    assert (p["C"].sources, p["C"].single, p["C"].suppliers, p["C"].total) == (1, True, ["S"], 350)
    assert (p["C"].lead_time_days, p["C"].on_time) == (1, 0.9)
    assert [x.product for x in v.sourcing][:1] == ["C"]               # the single-sourced first
    assert (v.single_products, v.products) == (1, 2) and v.single_share == pytest.approx(350 / 1770)
    assert (s["S"].products, s["S"].sole_for, s["S2"].sole_for) == (2, 1, 0)
    assert v.notes == ["1 closed purchase order had no source at its place to price it by, and is left out of the "
                       "spend"]
    assert v.since == "2025-01-05"
