"""Enterprise 6.2: stock in the books at a moving average or at the standard, with the price differences an invoice
leaves; ABC cycle counting. Every figure is worked out by hand in the test from the movements, not read back from
the engine."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals import post
from scp.actuals.cycle import count_due, cycle_plan
from scp.actuals.valuation import value_stock
from scp.api.app import app
from scp.model import Dataset
from scp.purchasing import act
from scp.validate import validate

from .factory import base, ds, example_dict, lp

client = TestClient(app)
JAN = date(2026, 1, 5)


def company(control: str = "moving_average", **b) -> dict:
    """Plant P with 30 B at the start (standard 8) and PO-00001: 100 B at 10, 30 C at 5 from S; C stands at 4."""
    d = base(horizon=42)
    d["execution"] = {"price_control": control}
    d["products"][1]["standard_cost"] = 8
    d["products"][2]["standard_cost"] = 4
    d["products"][2]["price_control"] = "standard"
    d["purchase_orders"] = [{"id": "PO-00001", "supplier": "S", "location": "P", "order_date": "2026-01-02",
                             "sent_on": "2026-01-02"}]
    d["receipts"] = [
        {"id": "PO-00001-10", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
         "due_date": "2026-01-05", "source": "PIR-B", "po": "PO-00001", "price": 10},
        {"id": "PO-00001-20", "kind": "purchase", "location": "P", "product": "C", "qty": 30,
         "due_date": "2026-01-05", "source": "PIR-C", "po": "PO-00001", "price": 5},
    ]
    for k, v in b.items():
        lp(d, "P", "B")[k] = v
    return d


def move(x: Dataset, mid: str, day: str, kind: str, prod: str, qty: float, **kw) -> Dataset:
    m = {"id": mid, "date": day, "type": kind, "location": "P", "product": prod, "qty": qty, **kw}
    return Dataset.model_validate({**x.model_dump(mode="json"), "movements": [*x.model_dump(mode="json")["movements"], m]})


def row(v, prod: str, loc: str = "P"):
    return next(r for r in v.rows if r.location == loc and r.product == prod)


def test_moving_average_follows_receipts_issues_and_the_invoice_that_differs():
    x = ds(company())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}, {"id": "PO-00001-20", "qty": 30}],
               on=JAN)
    x = move(x, "GM-S1", "2026-01-06", "sale", "B", 110, reference="SO-1", counterparty="P")
    x, _ = act(x, "enter_invoice", "PO-00001", on=date(2026, 1, 7),
               lines=[{"order": "PO-00001-10", "qty": 100, "price": 11}, {"order": "PO-00001-20", "qty": 30, "price": 5.5}])
    v = value_stock(x, date(2026, 1, 7))
    # B: 30 at 8 = 240, + 100 at 10 = 1,240 for 130; 110 sold at 1,240/130 each; 20 left
    avg = 1240 / 130
    left = 1240 - 110 * avg
    # the invoice bills 100 at 11: 100 more; 20 of the 100 are still here, so 20 go to stock and 80 aside
    b = row(v, "B")
    assert b.control == "moving_average" and b.qty == 20
    assert b.value == pytest.approx(left + 20, abs=0.01)
    assert b.price == pytest.approx((left + 20) / 20, abs=1e-4)
    assert v.cost_of_sales == pytest.approx(110 * avg, abs=0.01)
    # C stands at 4: received at 5 (30 more) and billed at 5.5 (15 more), its stock stays 30 × 4
    c = row(v, "C")
    assert c.control == "standard" and c.value == 120 and c.price == 4
    diffs = sorted((d.product, d.amount) for d in v.differences)
    assert diffs == [("B", 80.0), ("C", 15.0), ("C", 30.0)]
    assert v.total_differences == 125
    # A: 10 at the start, at its rolled-up standard: 2 B at 8 + 1 C at 4 + half an hour at 100
    assert row(v, "A").value == 10 * (2 * 8 + 4 + 0.5 * 100)
    assert v.total_value == pytest.approx(left + 20 + 120 + 700, abs=0.01)
    assert b.changes == 2                         # the receipt and the invoice moved it; the sale did not


def test_a_purchase_comes_in_at_what_it_lands_at_and_the_duty_follows_the_invoice_price():
    d = company()
    d["purchasing_sources"][0]["duty_rate"] = 0.1
    d["locations"][0]["handling_cost_per_unit"] = 0.2
    d["lanes"] = [{"id": "L-SP", "origin": "S", "destination": "P",
                   "modes": [{"mode": "truck_ftl", "transit_days": 1, "cost_per_unit": 0.5}]}]
    x = ds(d)
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    b = row(value_stock(x, JAN), "B")
    # 10 with 10 % duty, 0.50 freight and 0.20 handling a unit: 11.70; with the 30 at 8
    assert b.value == pytest.approx(240 + 100 * 11.7)
    x, _ = act(x, "enter_invoice", "PO-00001", on=JAN, lines=[{"order": "PO-00001-10", "qty": 100, "price": 12}])
    # billed 2 more a unit, and the duty on it: 2.20 a unit, all still here
    assert row(value_stock(x, JAN), "B").value == pytest.approx(240 + 1170 + 220)


def test_billed_before_the_goods_they_come_in_at_the_invoice_price():
    x = ds(company())
    x, _ = act(x, "enter_invoice", "PO-00001", on=JAN, lines=[{"order": "PO-00001-10", "qty": 60, "price": 12}])
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=date(2026, 1, 6))
    b = row(value_stock(x, date(2026, 1, 6)), "B")
    # 30 at 8 + 60 at 12 (as billed) + 40 at 10 (as ordered)
    assert b.qty == 130 and b.value == pytest.approx(240 + 720 + 400)
    assert not value_stock(x, date(2026, 1, 6)).differences


def test_a_return_leaves_at_the_order_price_and_a_count_at_the_average():
    x = ds(company())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    x = move(x, "GM-R1", "2026-01-06", "return", "B", 10, reference="PO-00001-10", counterparty="S")
    x = move(x, "GM-A1", "2026-01-07", "adjustment", "B", -6)
    v = value_stock(x, date(2026, 1, 7))
    after_return = 1240 - 10 * 10                 # 120 left worth 1,140
    found = -6 * after_return / 120
    b = row(v, "B")
    assert b.qty == 114 and b.value == pytest.approx(after_return + found, abs=0.01)
    assert v.count_differences == pytest.approx(found, abs=0.01)


def test_a_transfer_arrives_at_what_it_was_worth_where_it_left():
    d = company()
    d["locations"].append({"id": "W", "type": "dc"})
    d["lanes"] = [{"id": "L-PW", "origin": "P", "destination": "W", "modes": [{"mode": "truck_ftl", "transit_days": 1}]}]
    d["location_products"].append({"location": "W", "product": "B"})
    d["receipts"].append({"id": "TR-1", "kind": "transfer", "location": "W", "product": "B", "qty": 50,
                          "due_date": "2026-01-07", "source": "L-PW"})
    x = ds(d)
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    x = move(x, "GM-T1", "2026-01-06", "transfer_out", "B", 50, reference="TR-1", counterparty="W")
    x = Dataset.model_validate({**x.model_dump(mode="json"), "movements": [*x.model_dump(mode="json")["movements"],
                                {"id": "GM-T2", "date": "2026-01-07", "type": "receipt", "location": "W", "product": "B",
                                 "qty": 50, "reference": "TR-1"}]})
    v = value_stock(x, date(2026, 1, 7))
    unit = 1240 / 130
    assert row(v, "B", "W").value == pytest.approx(50 * unit, abs=0.01)
    assert row(v, "B", "W").price == pytest.approx(unit, abs=1e-4)
    assert row(v, "B").value == pytest.approx(1240 - 50 * unit, abs=0.01)
    # moving stock between places adds nothing: B is still worth 1,240 in all
    assert row(v, "B").value + row(v, "B", "W").value == pytest.approx(1240, abs=0.01)


def test_stock_gone_below_zero_is_settled_at_the_price_it_left_and_the_rest_is_a_difference():
    x = ds(company())
    x = move(x, "GM-S1", "2026-01-05", "sale", "B", 50, reference="SO-1", counterparty="P")   # 30 there: 20 below
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=date(2026, 1, 6))
    v = value_stock(x, date(2026, 1, 6))
    b = row(v, "B")
    # out at 8: −20 worth −160; in 100 at 10: the 20 owed come in at 8 (40 aside), the other 80 at 10
    assert b.qty == 80 and b.value == pytest.approx(800)
    assert [(d.product, d.amount) for d in v.differences] == [("B", 40.0)]


def test_a_reversed_receipt_leaves_at_what_it_came_in_at():
    x = ds(company())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    gm = next(m for m in x.movements if m.type.value == "receipt" and m.product == "B")
    x, _ = post(x, "reverse", movement=gm.id, on=date(2026, 1, 6))
    b = row(value_stock(x, date(2026, 1, 6)), "B")
    assert b.qty == 30 and b.value == pytest.approx(240) and b.price == pytest.approx(8)


def test_a_subsequent_debit_and_the_invoice_freight_go_to_the_stock_still_there():
    x = ds(company())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    x = move(x, "GM-S1", "2026-01-06", "sale", "B", 65, reference="SO-1", counterparty="P")   # 65 of 130 sold
    x, _ = act(x, "enter_invoice", "PO-00001", on=date(2026, 1, 7), delivery_costs=50,
               lines=[{"order": "PO-00001-10", "qty": 100, "price": 10}])
    x, _ = act(x, "enter_invoice", "", on=date(2026, 1, 8), kind="subsequent_debit", reference="DN-1",
               lines=[{"order": "PO-00001-10", "qty": 100, "price": 1}])
    v = value_stock(x, date(2026, 1, 8))
    left = 1240 * 65 / 130
    # freight 50 for 100 received, 65 here: 32.50 to stock, 17.50 aside; the debit 100: 65 to stock, 35 aside
    assert row(v, "B").value == pytest.approx(left + 32.5 + 65, abs=0.01)
    assert v.total_differences == pytest.approx(17.5 + 35, abs=0.01)


def test_at_the_standard_nothing_moves_the_price_and_the_company_setting_reaches_every_product():
    x = ds(company("standard"))
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    x, _ = act(x, "enter_invoice", "PO-00001", on=date(2026, 1, 7), lines=[{"order": "PO-00001-10", "qty": 100,
                                                                             "price": 11}])
    v = value_stock(x, date(2026, 1, 7))
    b = row(v, "B")
    assert b.control == "standard" and b.value == 130 * 8 and b.changes == 0
    # received at 10 against 8 (200), billed at 11 against 10 (100)
    assert sorted(d.amount for d in v.differences) == [100.0, 200.0]


def test_planning_keeps_the_planned_unit_value():
    from scp.plan import run_mrp
    x = ds(company())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    x, _ = act(x, "enter_invoice", "PO-00001", on=JAN, lines=[{"order": "PO-00001-10", "qty": 100, "price": 14}])
    plan = run_mrp(x)
    assert next(n for n in plan.nodes if n.product == "B").unit_value == 8


def test_the_books_through_the_api():
    x = ds(company())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    r = client.post("/api/valuation", params={"as_of": "2026-01-05"}, json=x.model_dump(mode="json"))
    assert r.status_code == 200
    got = {(w["location"], w["product"]): w for w in r.json()["rows"]}
    assert got[("P", "B")]["value"] == 1240 and got[("P", "B")]["price"] == pytest.approx(1240 / 130, abs=1e-4)


# ---- cycle counting ---------------------------------------------------------------------------------------------
def shop() -> dict:
    """One store: five products at 10 each, used up 400, 300, 150, 100 and 50 over the year (1,000 in all)."""
    used = {"A1": 400, "A2": 300, "B1": 150, "C1": 100, "C2": 50}
    d = {"settings": {"planning_start": "2026-03-02", "horizon_days": 28},
         "locations": [{"id": "ST", "type": "store"}, {"id": "S", "type": "supplier"}],
         "products": [{"id": p, "type": "FG", "standard_cost": 10} for p in used],
         "location_products": [{"location": "ST", "product": p, "on_hand": 500} for p in used],
         "purchasing_sources": [{"id": f"B-{p}", "supplier": "S", "location": "ST", "product": p, "price": 10,
                                 "lead_time_days": 2} for p in used],
         "movements": [{"id": f"GM-{p}", "date": "2026-02-01", "type": "sale", "location": "ST", "product": p, "qty": q}
                       for p, q in used.items()]}
    return d


def test_classes_by_the_value_used_up_and_due_when_never_counted():
    p = cycle_plan(ds(shop()))
    cls = {r.product: r.cls for r in p.rows}
    # shares before each: A1 0, A2 .4, B1 .7, C1 .85, C2 .95 → A, A, A (.7 < .8), B (.85 < .95), C
    assert cls == {"A1": "A", "A2": "A", "B1": "A", "C1": "B", "C2": "C"}
    assert all(r.due and r.next_due == date(2026, 3, 2) for r in p.rows)
    assert {c.cls: (c.items, c.per_year) for c in p.classes} == {"A": (3, 12), "B": (1, 4), "C": (1, 1)}


def test_a_product_whose_share_before_it_is_exactly_the_a_share_is_not_a():
    d = shop()
    d["execution"] = {"cycle_counting": {"a_share": 0.7, "b_share": 0.95}}
    cls = {r.product: r.cls for r in cycle_plan(ds(d)).rows}
    assert cls["B1"] == "B" and cls["A2"] == "A"           # 70 % of the value came before B1: A is full


def test_counted_last_month_an_a_item_is_due_again_after_a_twelfth_of_a_year_and_a_c_item_after_a_year():
    d = shop()
    d["inventory_docs"] = [{"id": "PI-00001", "date": "2026-02-01", "status": "posted", "items": [
        {"location": "ST", "product": p, "book_qty": 500, "counted": 500 if p != "A2" else 498} for p in ("A1", "A2", "C2")]}]
    d["location_products"][4]["cycle_count"] = "none"         # C2 is never cycle counted
    p = cycle_plan(ds(d))
    r = {x.product: x for x in p.rows}
    assert r["A1"].next_due == date(2026, 2, 1).fromordinal(date(2026, 2, 1).toordinal() + 31) and not r["A1"].due
    assert r["C2"].cls == "none" and r["C2"].by_hand and r["C2"].next_due is None and not r["C2"].due
    a = next(c for c in p.classes if c.cls == "A")
    assert (a.counted, a.exact, a.accuracy) == (2, 1, 0.5)
    assert a.difference_value == -20                         # 2 short at 10
    assert p.due == 2                                        # B1 (A, never counted) and C1 (B, never counted)


def test_what_is_due_becomes_one_count_document_and_is_then_not_due():
    x, rep = count_due(ds(shop()), "ST", classes=["A"])
    doc = x.inventory_docs[-1]
    assert sorted(it.product for it in doc.items) == ["A1", "A2", "B1"]
    assert "Cycle count: 3 A." in rep.message and not doc.block
    p = cycle_plan(x)
    assert {r.product for r in p.rows if r.due} == {"C1", "C2"}
    assert {r.product: r.on_doc for r in p.rows}["A1"] == doc.id
    # through the posting endpoint, as the page does it
    r = client.post("/api/actuals/post", json={"dataset": x.model_dump(mode="json"), "action": "cycle_count",
                                               "location": "ST"})
    assert r.status_code == 200 and "Cycle count: 1 B, 1 C." in r.json()["report"]["message"]


def test_kaveri_classes_its_warehouses_by_what_their_customers_bought():
    x = Dataset.model_validate(example_dict("kitchenware_network"))
    p = cycle_plan(x, "DC-BHIWANDI")
    assert p.notes and "sales history" in p.notes[0]
    assert {r.cls for r in p.rows} == {"A"}                   # three products, each under 80 % before it
    assert not [i for i in validate(x) if i.code.startswith("CYCLE")]


def test_a_dc_whose_sales_history_is_its_own_is_classed_by_it_not_by_the_plant_that_supplies_it():
    d = shop()
    d["locations"].append({"id": "PL", "type": "plant"})
    d["location_products"] += [{"location": "PL", "product": p, "on_hand": 0} for p in ("A1", "C2")]
    d["lanes"] = [{"id": "L-PL-ST", "origin": "PL", "destination": "ST", "modes": [{"transit_days": 1}]}]
    d["history"] = [{"location": "ST", "product": m["product"], "date": "2026-02-01", "qty": m["qty"]} for m in d.pop("movements")]
    p = cycle_plan(ds(d))
    assert {r.product: r.cls for r in p.rows if r.location == "ST"} == {"A1": "A", "A2": "A", "B1": "A", "C1": "B", "C2": "C"}
    assert {r.cls for r in p.rows if r.location == "PL"} == {"C"}      # the plant sold nothing itself
