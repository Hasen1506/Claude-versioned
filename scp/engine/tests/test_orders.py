"""Phase G: customer orders from taking to closing (Q5), customer prices, and no revenue without a price (Q10)."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals import PostingError, post, roll_forward
from scp.api.app import app
from scp.finance import run_finance
from scp.model import DemandRecord
from scp.promise import run_promise
from scp.promise.orders import OrderError, accept, cancel, change, next_order_id
from scp.sop import run_sop
from scp.tower import run_tower
from scp.validate import validate

from .factory import base, ds

client = TestClient(app)


def shop(price: float | None = 100.0) -> dict:
    """Plant P holds 10 A and ships to customer K in a day; more A can be made in two days."""
    d = base()
    d["locations"].append({"id": "K", "name": "Kumar Stores", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["products"][0].update(name="Tin of white", base_uom="EA", price=price)
    return d


def order(qty: float, day: str = "2026-01-08", **kw) -> DemandRecord:
    return DemandRecord(location="K", product="A", date=date.fromisoformat(day), qty=qty, kind="sales_order", **kw)


def confirmed(x, oid: str) -> float:
    return sum(c.qty for c in x.confirmations if c.order == oid)


# ---- Q5: take a checked order -----------------------------------------------------------------------------
def test_an_accepted_order_is_a_sales_order_that_keeps_its_promise():
    x0 = ds(shop())
    x1, rep = accept(x0, order(6))
    assert rep.order == "SO-00001" and "SO-00001 taken: 6 Tin of white for Kumar Stores" in rep.message
    so = next(d for d in x1.demand if d.id == "SO-00001")
    assert so.kind == "sales_order" and so.qty == 6
    assert confirmed(x1, "SO-00001") == pytest.approx(6) and rep.promise.status == "on_time"
    # the next order is checked after it: only 4 are left in stock, the rest comes from new production
    x2, rep2 = accept(x1, order(8))
    assert rep2.order == "SO-00002" and next_order_id(x2) == "SO-00003"
    assert next_order_id(ds({**shop(), "demand": [{"id": "SO-88221", "location": "K", "product": "A", "date": "2026-01-08",
                                                   "qty": 1, "kind": "sales_order"}]})) == "SO-88222"   # the company's own
    assert confirmed(x2, "SO-00001") == pytest.approx(6)                       # the first promise is untouched
    first = run_promise(x2).orders[0]
    assert first.order == "SO-00001" and first.change == "kept" and not first.at_risk
    with pytest.raises(OrderError, match="already an order number"):
        accept(x2, order(1, id="SO-00001"))
    with pytest.raises(OrderError, match="supplier"):
        accept(x2, order(1).model_copy(update={"location": "S"}))
    assert not [i for i in validate(x2) if i.severity == "error"]


def test_an_order_made_to_order_makes_its_production_firm():
    # K (R13): a hotel order promised on new production went late at the roll: the run was only planned, never firmed
    x, from_stock = accept(ds(shop()), order(6))
    assert "only planned" not in from_stock.message and not from_stock.firmed and x.receipts == ds(shop()).receipts
    d = shop()
    next(lp for lp in d["location_products"] if lp["product"] == "A").update(strategy="MTO", on_hand=0)
    x, made = accept(ds(d), order(6))
    assert made.firmed and made.firmed[0].kind == "production" and "Made firm for it: PRD-00001" in made.message
    prd = next(r for r in x.receipts if r.id == made.firmed[0].receipt_id)
    assert prd.product == "A" and prd.qty >= 6 and prd.reservations          # it reserves its parts
    # planning again plans nothing new for the order: its production is there
    from scp.plan import run_mrp
    assert not [o for o in run_mrp(x).orders if o.product == "A" and o.kind == "make"]
    # the company can keep firming by hand
    d["execution"] = {"promise_firms": False}
    x, made = accept(ds(d), order(6))
    assert not made.firmed and not [r for r in x.receipts if r.kind.value == "production"]
    assert "It needs new supply that is only planned: make it firm (Actuals → Open orders & firming)" in made.message


def test_a_changed_order_is_promised_again_and_cannot_go_below_what_was_delivered():
    x, _ = accept(ds(shop()), order(6))
    x, rep = change(x, "SO-00001", {"qty": 9, "date": date(2026, 1, 12), "priority": 2})
    so = next(d for d in x.demand if d.id == "SO-00001")
    assert (so.qty, so.date, so.priority) == (9, date(2026, 1, 12), 2)
    assert confirmed(x, "SO-00001") == pytest.approx(9)
    assert "quantity 6 → 9" in rep.message and "priority 5 → 2" in rep.message
    x, _ = post(x, "deliver", order="SO-00001", qty=4)
    with pytest.raises(OrderError, match="4 of SO-00001 have already been delivered"):
        change(x, "SO-00001", {"qty": 3})
    with pytest.raises(OrderError, match="cannot be changed"):
        change(x, "SO-00001", {"product": "B"})


# ---- delivering -----------------------------------------------------------------------------------------------
def test_delivering_posts_a_sale_from_where_it_was_promised_and_the_roll_closes_it():
    x, _ = accept(ds(shop()), order(6))
    x, rep = post(x, "deliver", order="SO-00001", qty=2)
    m = x.movements[-1]
    assert (m.type, m.location, m.product, m.qty, m.reference, m.counterparty) == ("sale", "P", "A", 2, "SO-00001", "K")
    assert "4 still open" in rep.message
    x, rep = post(x, "deliver", order="SO-00001")
    assert x.movements[-1].qty == 4 and "complete" in rep.message
    with pytest.raises(PostingError, match="already been delivered"):
        post(x, "deliver", order="SO-00001")
    rolled, _ = roll_forward(x, date(2026, 1, 12))
    (c,) = [c for c in rolled.closed_orders if c.id == "SO-00001"]
    assert c.delivered_qty == 6 and not c.cancelled and c.last_delivery == date(2026, 1, 6)   # issued the 5th, a day's transit
    assert not any(d.id == "SO-00001" for d in rolled.demand)


def test_a_delivery_beyond_the_stock_says_so_and_an_order_without_a_route_is_refused():
    x, _ = accept(ds(shop()), order(6))
    x, rep = post(x, "deliver", order="SO-00001", qty=12)
    assert "not enough in stock" in rep.message
    d = shop()
    d["lanes"] = []
    y = ds({**d, "demand": [{"id": "SO-9", "location": "K", "product": "A", "date": "2026-01-08", "qty": 3,
                            "kind": "sales_order"}]})
    with pytest.raises(PostingError, match="no place to ship from"):
        post(y, "deliver", order="SO-9")


# ---- cancelling -----------------------------------------------------------------------------------------------
def test_a_cancelled_order_frees_its_stock_and_does_not_count_against_otif():
    x, _ = accept(ds(shop()), order(6))
    x, _ = accept(x, order(8))
    x, rep = cancel(x, "SO-00001", reason="customer changed their mind")
    assert "SO-00001 cancelled: 6 Tin of white for Kumar Stores no longer wanted" in rep.message
    assert not any(d.id == "SO-00001" for d in x.demand) and confirmed(x, "SO-00001") == 0
    (c,) = x.closed_orders
    assert c.cancelled and c.delivered_qty == 0 and c.ordered_qty == 6
    assert not [i for i in validate(x) if i.severity == "error"]
    k = {kpi.id: kpi for kpi in run_tower(x.model_copy(update={"settings": x.settings.model_copy(
        update={"planning_start": date(2026, 1, 12)})})).kpis}
    assert k["otif_requested"].n == 0


def test_cancelling_the_rest_of_a_part_delivered_order_counts_what_was_delivered_as_in_full():
    x, _ = accept(ds(shop()), order(6))
    x, _ = post(x, "deliver", order="SO-00001", qty=2, on=date(2026, 1, 5))
    x, rep = cancel(x, "SO-00001", on=date(2026, 1, 6))
    assert "2 delivered, 4 no longer wanted" in rep.message
    (c,) = x.closed_orders
    assert c.cancelled and c.delivered_qty == 2 and c.last_delivery == date(2026, 1, 6)
    k = {kpi.id: kpi for kpi in run_tower(x.model_copy(update={"settings": x.settings.model_copy(
        update={"planning_start": date(2026, 1, 12)})})).kpis}
    assert k["otif_requested"].n == 1 and k["otif_requested"].value == pytest.approx(1.0)
    # the journal's delivery keeps its order: nothing is unmatched, and a roll leaves the log as it is
    rolled, _ = roll_forward(x, date(2026, 1, 12))
    (c2,) = rolled.closed_orders
    assert c2.cancelled and c2.delivered_qty == 2


# ---- customer prices ------------------------------------------------------------------------------------------
def test_an_order_price_beats_the_customer_price_which_beats_the_product_price():
    d = shop(price=100)
    d["customer_prices"] = [{"customer": "K", "product": "A", "price": 150}]
    x = ds(d)
    assert x.selling_price("K", "A") == 150 and x.selling_price("P", "A") == 100
    assert x.selling_price("K", "A", 120) == 120 and x.selling_price("K", "B") is None
    x, rep = accept(x, order(6, price=120))
    assert rep.promise.value == pytest.approx(720)
    x, _ = accept(x, order(2))
    assert [o.price for o in run_promise(x).orders] == [120, 150]
    x, _ = change(x, "SO-00001", {"price": None})            # back to the price list
    assert run_promise(x).orders[0].value == pytest.approx(900)
    (row,) = [r for r in run_finance(x).serve if r.location == "K"]
    assert row.price == 150 and row.revenue == pytest.approx(row.served * 150)
    d["customer_prices"].append({"customer": "S", "product": "A", "price": 1})
    assert any(i.code == "REF_WRONG_TYPE" and i.object_type == "customer_price" for i in validate(ds(d)))
    d["customer_prices"][1] = {"customer": "K", "product": "A", "price": 1}
    assert any(i.code == "DUP_ID" and i.object_type == "customer_price" for i in validate(ds(d)))


# ---- Q10: no revenue without a price ---------------------------------------------------------------------------
def test_without_a_price_there_is_no_revenue_or_margin_anywhere():
    x, _ = accept(ds(shop(price=None)), order(6))
    (row,) = run_finance(x).serve
    assert row.price is None and row.revenue == 0 and row.margin is None and row.margin_pct is None
    assert run_promise(x).orders[0].value is None
    s = run_sop(x)
    assert s.economics.revenue == 0 and s.economics.unpriced == ["A"] and s.economics.valued_at_cost > 0
    assert any("No selling price for A" in n for n in s.notes)
    y, _ = accept(ds(shop(price=100)), order(6))
    s = run_sop(y)
    assert s.economics.revenue == pytest.approx(600) and s.economics.unpriced == [] and s.economics.valued_at_cost == 0


def test_a_duplicate_sales_order_number_is_flagged():
    d = shop()
    d["demand"] = [{"id": "SO-1", "location": "K", "product": "A", "date": "2026-01-08", "qty": q, "kind": "sales_order"}
                   for q in (1, 2)]
    assert any(i.code == "DUP_ID" and i.object_id == "SO-1" for i in validate(ds(d)))


# ---- the API ---------------------------------------------------------------------------------------------------
def test_the_api_takes_changes_cancels_and_delivers_an_order():
    d = ds(shop()).model_dump(mode="json")
    r = client.post("/api/orders/sales", json={"dataset": d, "action": "accept", "order": {
        "location": "K", "product": "A", "date": "2026-01-08", "qty": 6, "kind": "sales_order", "customer_ref": "PO 4471"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report"]["order"] == "SO-00001" and body["report"]["promise"]["status"] == "on_time"
    so = next(x for x in body["dataset"]["demand"] if x["id"] == "SO-00001")
    assert so["customer_ref"] == "PO 4471"
    r = client.post("/api/orders/sales", json={"dataset": body["dataset"], "action": "change", "id": "SO-00001",
                                               "changes": {"qty": 7, "price": 90}})
    assert r.status_code == 200, r.text
    ch = r.json()["dataset"]
    assert next(x for x in ch["demand"] if x["id"] == "SO-00001")["price"] == 90
    r = client.post("/api/orders/sales", json={"dataset": ch, "action": "change", "id": "SO-00001",
                                               "changes": {"price": None}})
    assert next(x for x in r.json()["dataset"]["demand"] if x["id"] == "SO-00001")["price"] is None
    r = client.post("/api/actuals/post", json={"dataset": ch, "action": "deliver", "order": "SO-00001", "qty": 3})
    assert r.status_code == 200 and "4 still open" in r.json()["report"]["message"]
    r = client.post("/api/orders/sales", json={"dataset": ch, "action": "cancel", "id": "SO-00001"})
    assert r.status_code == 200 and r.json()["dataset"]["closed_orders"][0]["cancelled"] is True
    r = client.post("/api/orders/sales", json={"dataset": ch, "action": "cancel", "id": "SO-77"})
    assert r.status_code == 409 and "not an open sales order" in r.json()["detail"]
