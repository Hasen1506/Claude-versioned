"""Backtest against the S/4HANA supply-chain guide, PART C: §10 Make, §11 Buy, §12 Store, §13 Deliver, §14 Transport,
§15 Bill and settle, §16 the three end-to-end scenarios and the §18.2 KPI set.

Each test turns one rule of the guide into a hand-calculated case run through the engine (and the API where the
rule is reached through it). The findings matrix is kept outside the repository (part-c.md); concepts the app does
not model are logged in docs/IDEAS.md. Every case is deterministic and offline.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp import sales
from scp.actuals import post, roll_forward
from scp.api.app import app
from scp.model import MovementType, StockType
from scp.plan import run_mrp
from scp.plan.costing import landed_unit_cost, roll_up
from scp.plan.leadtime import nominal_lead_time_days, schedule_buy
from scp.network import build_graph
from scp.promise.run import commit, run_promise
from scp.purchasing import act
from scp.purchasing.payables import to_invoice
from scp.tower import run_tower

from .factory import base, demand, ds, lp

client = TestClient(app)
JAN5 = date(2026, 1, 5)


def kpis(d) -> dict:
    return {k.id: k for k in run_tower(ds(d) if isinstance(d, dict) else d).kpis}


# =================================================================================================================
# §10 Make
# =================================================================================================================
def make_only(**ps) -> dict:
    d = base(horizon=28)
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 0
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    d["production_sources"][0].update(ps)
    d["demand"] = [demand("P", "A", "2026-01-20", 90)]
    return d


def test_10_scrap_and_yield_assembly_step_and_component_scrap_by_hand():
    """§10 PROCESSING 'yield/scrap update the order'. 90 good A with 10 % assembly scrap starts 100; a step that loses
    20 % before it means 125 start; each A takes 2 B with 20 % component scrap: 125 × 2 ÷ 0.8 = 312.5 B issued.
    (SAP multiplies, 90 × 1.1 = 99 started, which yields 89.1 good: the app divides, so the good quantity is met —
    a deliberate and better reading, recorded in part-c.md.)"""
    d = make_only(assembly_scrap=0.1)
    d["production_sources"][0]["operations"][0]["scrap"] = 0.2
    d["production_sources"][0]["components"][0]["scrap"] = 0.2
    plan = run_mrp(ds(d))
    mo = [o for o in plan.orders if o.product == "A"]
    assert sum(o.qty for o in mo) == pytest.approx(90)                 # the order is planned in good units
    dep = sum(r.qty for r in plan.requirements if r.product == "B" and r.kind == "dependent")
    assert dep == pytest.approx(90 / 0.9 / 0.8 * 2 / 0.8)
    dep_c = sum(r.qty for r in plan.requirements if r.product == "C" and r.kind == "dependent")
    assert dep_c == pytest.approx(90 / 0.9 / 0.8 * 1)


def test_10_co_product_is_valued_at_its_cost_share_and_received_with_the_main_product():
    """§10.2 movement 531 'receipt of by-product, order credited at by-product value'."""
    d = make_only()
    d["products"].append({"id": "Y", "type": "SFG"})
    d["location_products"].append({"location": "P", "product": "Y"})
    d["production_sources"][0]["co_products"] = [{"product": "Y", "qty": 0.5, "cost_share": 0.2}]
    x = ds(d)
    plan = run_mrp(x)
    uv = {(n.location, n.product): n.unit_value for n in plan.nodes}
    # run cost per good A, shared 80/20; Y comes 0.5 per A, so Y = 0.2 × run ÷ 0.5 and A = 0.8 × run
    assert uv[("P", "Y")] == pytest.approx(uv[("P", "A")] * 0.2 / 0.8 / 0.5)
    co = [r for r in plan.orders if r.product == "A"]
    assert co


def test_10_subcontracted_step_loads_no_own_machine_and_adds_its_price_and_days():
    """§10.1 subcontracting: 'outsourced operations, capacity relief'; value = service + components."""
    d = make_only()
    d["production_sources"][0].pop("fixed_lead_time_workdays")
    d["production_sources"][0]["operations"] = [
        {"seq": 10, "subcontract": {"supplier": "S", "workdays": 4, "cost_per_unit": 7}}]
    x = ds(d)
    plan = run_mrp(x)
    uv = {(n.location, n.product): n.unit_value for n in plan.nodes}
    assert uv[("P", "A")] == pytest.approx(2 * uv[("P", "B")] + uv[("P", "C")] + 7)
    assert not any(r.resource == "M1" and sum(r.daily_load.values()) > 0 for r in plan.resources)
    mo = next(o for o in plan.orders if o.product == "A")
    assert (mo.due_date - mo.start_date).days == 4                       # 7-day calendar: four working days


def test_10_3_inspection_at_production_receipt_puts_finished_goods_into_quality_stock():
    """§10.3 type 04: 'GR from production order — finished goods into QI stock; blocks delivery until UD'."""
    d = base(horizon=28)
    d["products"][0]["inspect_on_receipt"] = True
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 100
    lp(d, "P", "C")["on_hand"] = 50
    d["receipts"] = [{"id": "MO-1", "kind": "production", "location": "P", "product": "A", "qty": 20,
                      "due_date": "2026-01-05", "start_date": "2026-01-03", "source": "PV-A"}]
    x, rep = post(ds(d), "receive", order="MO-1", on=date(2026, 1, 4))
    got = [m for m in x.movements if m.type is MovementType.RECEIPT and m.product == "A"]
    assert got and all(m.stock_type is StockType.QUALITY for m in got)
    assert "quality inspection" in rep.message


# =================================================================================================================
# §11 Buy
# =================================================================================================================
def test_11_purchase_lead_time_is_processing_plus_planned_delivery_plus_gr_processing():
    """§11 TIP and §17.1: a requisition for goods needed on Fri 30 Jan (Mon–Fri plant) with 2 working days of buyers'
    processing, 5 days planned delivery, 2 days transit and 1 day GR processing: available 30 → arrive 29 → ship 27
    → PO placed Thu 22 → requisition released Tue 20 (two working days before)."""
    d = base(horizon=42, workdays=[0, 1, 2, 3, 4])
    d["purchasing"] = {"processing_workdays": 2}
    d["purchasing_sources"][0]["lead_time_days"] = 5
    d["lanes"] = [{"id": "S-P", "origin": "S", "destination": "P", "modes": [{"transit_days": 2}]}]
    lp(d, "P", "B")["gr_processing_days"] = 1
    x = ds(d)
    sch = schedule_buy(x, "PIR-B", available=date(2026, 1, 30))
    assert (sch.start_date, sch.ship_date, sch.due_date, sch.available_date) == (
        date(2026, 1, 20), date(2026, 1, 27), date(2026, 1, 29), date(2026, 1, 30))
    # a purchase order placed today does not wait for the buyers again
    po = schedule_buy(x, "PIR-B", start=date(2026, 1, 22), requisition=False)
    assert po.due_date == date(2026, 1, 29)
    # the replenishment lead time used by safety stock and ATP carries all three parts (2 workdays ≈ 2.8 days)
    opt = next(o for o in build_graph(x).options[("P", "B")] if o.kind == "buy")
    assert nominal_lead_time_days(x, opt) == pytest.approx(2 * 7 / 5 + 5 + 2 + 1)


def test_11_without_processing_time_the_dates_are_what_they_were():
    d = base(horizon=42, workdays=[0, 1, 2, 3, 4])
    d["purchasing_sources"][0]["lead_time_days"] = 5
    sch = schedule_buy(ds(d), "PIR-B", available=date(2026, 1, 30))
    assert sch.start_date == date(2026, 1, 23) and sch.due_date == date(2026, 1, 28)


def test_11_mrp_releases_the_requisition_processing_days_earlier():
    d = base(horizon=42, workdays=[0, 1, 2, 3, 4])
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    lp(d, "P", "B")["on_hand"] = 0
    d["products"].append({"id": "R", "type": "RM"})
    d["location_products"].append({"location": "P", "product": "R"})
    d["purchasing_sources"].append({"id": "PIR-R", "supplier": "S", "product": "R", "location": "P", "price": 1,
                                    "lead_time_days": 3})
    d["demand"] = [demand("P", "R", "2026-01-30", 10)]
    before = next(o for o in run_mrp(ds(d)).orders if o.product == "R")
    d["purchasing"] = {"processing_workdays": 3}
    after = next(o for o in run_mrp(ds(d)).orders if o.product == "R")
    assert before.due_date == after.due_date
    assert after.start_date == date(2026, 1, 22) and before.start_date == date(2026, 1, 27)


def ordered_po() -> dict:
    d = base(horizon=42)
    d["purchase_orders"] = [{"id": "PO-00001", "supplier": "S", "location": "P", "order_date": "2026-01-02",
                             "sent_on": "2026-01-02"}]
    d["receipts"] = [{"id": "PO-00001-10", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
                      "due_date": "2026-01-05", "source": "PIR-B", "po": "PO-00001", "price": 10}]
    return d


@pytest.mark.parametrize("qty,price,blocked", [
    (100, 10.19, False),     # +1.9 %: inside the 2 % tolerance
    (100, 10.21, True),      # +2.1 % on 100: 21.00 over, beyond both limits
    (1, 10.50, False),       # +5 % but 0.50 in all: under the 1.00 absolute limit, so no block (both must be crossed)
    (100, 9.00, False),      # a cheaper invoice is not blocked (SAP: lower limit normally not blocking)
])
def test_11_2_three_way_match_price_tolerance(qty, price, blocked):
    """§11.2 'Price: invoice price vs PO net price, blocked when the variance is beyond tolerance PP/PS'."""
    x = ds(ordered_po())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN5)
    x, _ = act(x, "enter_invoice", "PO-00001", on=JAN5, lines=[{"order": "PO-00001-10", "qty": qty, "price": price}])
    inv = x.supplier_invoices[-1]
    assert bool([b for b in inv.blocks if b.startswith("price")]) is blocked


def test_11_2_three_way_match_quantity_block_lifts_when_the_goods_arrive_and_gr_ir_shows_the_open_receipt():
    """§11.2 'Quantity: invoiced qty vs GR qty, blocked when the invoice exceeds what was received'; 'GR/IR clearing:
    received-not-invoiced balance'."""
    from scp.purchasing.payables import still_blocked
    x = ds(ordered_po())
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 60}], on=JAN5)
    # GR/IR: 60 received at 10, nothing invoiced → 600 open
    gi = to_invoice(x)
    assert [(g.order, g.qty, g.value) for g in gi] == [("PO-00001-10", 60, 600)]
    x, _ = act(x, "enter_invoice", "PO-00001", on=JAN5, lines=[{"order": "PO-00001-10", "qty": 100}])
    inv = x.supplier_invoices[-1]
    assert any(b.startswith("quantity") for b in inv.blocks)
    assert not to_invoice(x) or all(g.qty <= 0 for g in to_invoice(x))  # invoiced ahead of the goods: nothing to accrue
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 40}], on=date(2026, 1, 6))
    assert still_blocked(x, x.supplier_invoices[-1]) == []
    assert not [g for g in to_invoice(x) if abs(g.qty) > 1e-9]          # GR/IR clean


# =================================================================================================================
# §12 Store
# =================================================================================================================
def qi_company(**execution) -> dict:
    """100 A received into quality inspection last week; a customer order wants 50 tomorrow."""
    d = base(horizon=28)
    d["locations"].append({"id": "CU", "type": "customer"})
    d["lanes"] = [{"id": "P-CU", "origin": "P", "destination": "CU", "modes": [{"transit_days": 0}]}]
    lp(d, "P", "A")["on_hand"] = 0
    d["products"][0]["inspect_on_receipt"] = True
    d["execution"] = execution
    d["movements"] = [{"id": "GM-1", "date": "2026-01-02", "type": "receipt", "location": "P", "product": "A",
                       "qty": 100, "stock_type": "quality"}]
    d["demand"] = [demand("CU", "A", "2026-01-06", 50, "sales_order", id="SO-1")]
    return d


def test_12_quality_inspection_stock_is_planned_but_never_promised():
    """Regression (fails on main): §10.3 type 01/04 'stock posts to QI → invisible to ATP unless included in scope of
    check; blocks delivery until UD'. Planning counts the 100 in inspection (the company's rule, as SAP's MRP does by
    default) but the promise used the same on-hand and confirmed the order for tomorrow from stock that cannot be
    shipped."""
    x, _ = roll_forward(ds(qi_company()), JAN5)
    assert next(y for y in x.location_products if (y.location, y.product) == ("P", "A")).on_hand == 100   # planning
    res = run_promise(x)
    o = next(o for o in res.orders if o.order == "SO-1")
    assert not any(ln.method == "atp" and ln.ship_date <= date(2026, 1, 6) for ln in o.lines)
    assert o.on_time == 0
    assert all(n.on_hand == 0 for n in res.nodes if (n.location, n.product) == ("P", "A"))


def test_12_inspection_stock_can_be_promised_when_the_scope_of_check_includes_it():
    d = qi_company()
    d["promising"] = {"quality_in_promise": True}
    x, _ = roll_forward(ds(d), JAN5)
    o = next(o for o in run_promise(x).orders if o.order == "SO-1")
    assert o.on_time == 50 and o.lines[0].method == "atp"


def test_12_released_stock_is_promised_and_blocked_never_is():
    x, _ = roll_forward(ds(qi_company()), JAN5)
    x, _ = post(x, "move", location="P", product="A", qty=30, lot={"stock_type": StockType.QUALITY},
                to_type=StockType.UNRESTRICTED, on=date(2026, 1, 4))
    x, _ = post(x, "move", location="P", product="A", lot={"stock_type": StockType.QUALITY},
                to_type=StockType.BLOCKED, on=date(2026, 1, 4))
    x, _ = roll_forward(x, JAN5)
    assert next(y for y in x.location_products if (y.location, y.product) == ("P", "A")).on_hand == 30
    o = next(o for o in run_promise(x).orders if o.order == "SO-1")
    assert sum(ln.qty for ln in o.lines if ln.method == "atp" and ln.ship_date <= date(2026, 1, 6)) == 30


def test_12_planning_without_inspection_stock_and_a_promise_that_includes_it_add_it_back():
    d = qi_company(quality_in_planning=False)
    d["promising"] = {"quality_in_promise": True}
    x, _ = roll_forward(ds(d), JAN5)
    assert next(y for y in x.location_products if (y.location, y.product) == ("P", "A")).on_hand == 0
    assert next(o for o in run_promise(x).orders if o.order == "SO-1").on_time == 50


def test_12_shipping_from_inspection_stock_says_it_is_in_inspection():
    """Regression (fails on main): a goods issue that inspection stock cannot cover told the user to 'post the missing
    receipt': the goods were received; they are waiting for a usage decision."""
    x, _ = roll_forward(ds(qi_company(negative_stock="refuse")), JAN5)
    x = x.model_copy(update={"deliveries": []})
    x, _ = sales.create_deliveries(x, [{"order": "SO-1", "qty": 50, "ship_from": "P"}], on=date(2026, 1, 6))
    with pytest.raises(sales.SalesError, match="100 in quality inspection: release it first"):
        sales.issue(x, x.deliveries[0].id, on=date(2026, 1, 6))


def test_12_4_physical_inventory_posts_the_difference_against_the_frozen_book():
    """§12.4 'PI document → count → difference posting; freeze book inventory; blocking during counting'. Book 100
    frozen; counted 97 → −3 posted on the count day (Sun 4 Jan, before the planning start, so planning follows at
    once; a count dated on or after the start counts when the plan moves past it — the app's documented rule)."""
    d = base(horizon=28)
    lp(d, "P", "B")["on_hand"] = 100
    x, _ = roll_forward(ds(d), JAN5)
    x, rep = post(x, "count_doc", nodes=[("P", "B")], on=date(2026, 1, 4))
    assert x.inventory_docs[-1].items[0].book_qty == 100
    x, _ = post(x, "count_enter", doc=rep.doc, counts=[{"location": "P", "product": "B", "qty": 97}])
    x, _ = post(x, "count_post", doc=rep.doc)
    adj = [m for m in x.movements if m.type is MovementType.ADJUSTMENT]
    assert [(m.qty, m.date) for m in adj] == [(-3, date(2026, 1, 4))]
    assert next(y for y in x.location_products if (y.location, y.product) == ("P", "B")).on_hand == 97


def test_12_4_valuation_landed_cost_by_hand_and_standard_cost_override():
    """§12.4 valuation. The app values stock at one planned price per place (≈ price control S): landed cost of the
    primary source = price × fx × (1 + duty) + lane freight per unit + inbound handling, or the standard cost given.
    10 USD × 83 × 1.1 duty + 2.5 per kg × 2 kg = 918.0 per unit. There is no moving-average price (control V):
    logged as a gap."""
    d = base(horizon=28)
    d["settings"]["currency"] = "INR"
    d["settings"]["fx_rates"] = {"USD": 83}
    d["products"][1]["weight_kg"] = 2
    d["purchasing_sources"][0].update(currency="USD", price=10, duty_rate=0.1)
    d["lanes"] = [{"id": "S-P", "origin": "S", "destination": "P", "modes": [{"transit_days": 2, "cost_per_kg": 2.5}]}]
    x = ds(d)
    assert landed_unit_cost(x, "PIR-B") == pytest.approx(10 * 83 * 1.1 + 2.5 * 2)
    x = ds(d)
    assert roll_up(x, build_graph(x)).unit_value[("P", "B")] == pytest.approx(918.0)
    d["products"][1]["standard_cost"] = 900
    x = ds(d)
    assert roll_up(x, build_graph(x)).unit_value[("P", "B")] == 900


# =================================================================================================================
# §13 Deliver and §15 Bill
# =================================================================================================================
def o2c(**product) -> dict:
    d = base(horizon=28)
    d["locations"].append({"id": "CU", "type": "customer"})
    d["lanes"] = [{"id": "P-CU", "origin": "P", "destination": "CU", "modes": [{"transit_days": 1}]}]
    d["products"][0].update(price=50, **product)
    lp(d, "P", "A")["on_hand"] = 40
    return d


def test_13_pgi_reduces_stock_and_the_requirement_and_makes_the_delivery_billable():
    """§13 'What post goods issue actually does': ① stock ↓ ③ requirement reduced ④ billing-relevant."""
    x, _ = roll_forward(ds(o2c()), JAN5)
    x, rep = sales.create_order(x, "CU", [{"product": "A", "qty": 30, "date": "2026-01-07"}])
    line = x.demand[-1].id
    x, _ = sales.create_deliveries(x, on=JAN5)
    x, _ = sales.issue(x, x.deliveries[-1].id, on=JAN5)
    assert [(b.order, b.qty, b.price) for b in sales.to_bill(x)] == [(line, 30, 50)]
    x, _ = roll_forward(x, date(2026, 1, 6))
    assert next(y for y in x.location_products if (y.location, y.product) == ("P", "A")).on_hand == 10   # ①
    assert not any(d.id == line for d in x.demand)                                                      # ③ closed
    x, _ = sales.create_invoices(x, on=date(2026, 1, 6))
    assert x.invoices[-1].lines[0].qty == 30 and x.invoices[-1].net == 1500


def test_13_batch_split_sub_items_sum_to_the_parent_and_are_billed_once():
    """§13 PITFALL (b): 'batch split creates sub-items whose quantities must sum to the parent'."""
    d = o2c(batches=True, shelf_life_days=100)
    lp(d, "P", "A")["on_hand"] = 0
    d["batches"] = [{"product": "A", "id": "L1", "expires_on": "2026-02-01"},
                    {"product": "A", "id": "L2", "expires_on": "2026-03-01"}]
    d["movements"] = [
        {"id": "GM-1", "date": "2026-01-02", "type": "receipt", "location": "P", "product": "A", "qty": 20, "batch": "L1"},
        {"id": "GM-2", "date": "2026-01-02", "type": "receipt", "location": "P", "product": "A", "qty": 20, "batch": "L2"}]
    x, _ = roll_forward(ds(d), JAN5)
    x, _ = sales.create_order(x, "CU", [{"product": "A", "qty": 30, "date": "2026-01-07"}])
    x, _ = sales.create_deliveries(x, on=JAN5)
    x, _ = sales.issue(x, x.deliveries[-1].id, on=JAN5)
    out = [(m.batch, m.qty) for m in x.movements if m.type is MovementType.SALE]
    assert out == [("L1", 20), ("L2", 10)]                                    # first expiring, first out
    bills = sales.to_bill(x)
    assert sum(b.qty for b in bills) == 30
    x, _ = sales.create_invoices(x, on=JAN5)
    assert sum(ln.qty for ln in x.invoices[-1].lines) == 30


def test_15_billing_carries_the_order_price_forward_through_a_price_list_change():
    """§15 PITFALL: 're-pricing at billing (pricing type B) silently changes what the customer is charged; most want G
    (carry forward)'. Ordered at 50; the list price goes to 60 before invoicing; the invoice says 50."""
    x, _ = roll_forward(ds(o2c()), JAN5)
    x, _ = sales.create_order(x, "CU", [{"product": "A", "qty": 10, "date": "2026-01-07"}])
    x, _ = sales.create_deliveries(x, on=JAN5)
    x, _ = sales.issue(x, x.deliveries[-1].id, on=JAN5)
    prods = [p.model_copy(update={"price": 60}) if p.id == "A" else p for p in x.products]
    x = x.model_copy(update={"products": prods})
    x = type(x).model_validate(x.model_dump())
    x, _ = sales.create_invoices(x, on=JAN5)
    assert x.invoices[-1].lines[0].price == 50


def test_15_invoice_payment_with_cash_discount_closes_the_receivable():
    d = o2c()
    d["payment_terms"] = [{"id": "2-10-30", "name": "2/10 net 30", "net_days": 30, "discount_days": 10,
                           "discount": 0.02}]
    d["customers"] = [{"customer": "CU", "payment_terms": "2-10-30"}]
    x, _ = roll_forward(ds(d), JAN5)
    x, _ = sales.create_order(x, "CU", [{"product": "A", "qty": 10, "date": "2026-01-07"}])
    x, _ = sales.create_deliveries(x, on=JAN5)
    x, _ = sales.issue(x, x.deliveries[-1].id, on=JAN5)
    x, _ = sales.create_invoices(x, on=JAN5)
    inv = x.invoices[-1]
    assert inv.due_date == date(2026, 2, 4) and inv.discount_date == date(2026, 1, 15)
    x, rep = sales.pay(x, inv.id, on=date(2026, 1, 10))
    assert x.invoices[-1].payments[0].amount == pytest.approx(inv.total * 0.98)


# =================================================================================================================
# §14 Transport
# =================================================================================================================
def test_14_freight_charges_scale_by_weight_and_vehicles_by_capacity():
    """§14 'charge calculation: base rates, scales (weight/distance/pallet)'; vehicles needed by weight."""
    from scp.plan.costing import freight_per_unit, shipments_needed
    d = base(horizon=28)
    d["locations"].append({"id": "DC", "type": "dc"})
    d["products"][0]["weight_kg"] = 20
    d["lanes"] = [{"id": "P-DC", "origin": "P", "destination": "DC",
                   "modes": [{"transit_days": 1, "cost_per_unit": 1, "cost_per_kg": 0.5, "cost_per_shipment": 100,
                              "vehicle_capacity_kg": 1000}]}]
    x = ds(d)
    mode = x.lane_by_id["P-DC"].planning_mode
    assert freight_per_unit(x, mode, "A") == pytest.approx(1 + 20 * 0.5)
    assert shipments_needed(x, mode, "A", 120) == 3                      # 2,400 kg on 1,000 kg trucks


# =================================================================================================================
# §16 Scenarios
# =================================================================================================================
def test_16_1_scenario_a_make_to_stock_document_by_document():
    """§16.1 MTS (strategy 40): forecast → planned order → firm production order → GR 101 → sales order consumes the
    forecast → ATP confirm → delivery → PGI 601 → billing → payment. Each step checked for its quantity effect."""
    from scp.actuals import firm_orders
    d = o2c()
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 200
    lp(d, "P", "C")["on_hand"] = 100
    d["demand"] = [demand("CU", "A", "2026-01-15", 50)]                     # ① PIR
    x, _ = roll_forward(ds(d), JAN5)
    plan = run_mrp(x)
    mo = [o for o in plan.orders if o.product == "A" and o.location == "P"]  # ② planned order
    assert sum(o.qty for o in mo) == pytest.approx(50)
    x, frep = firm_orders(x, plan=plan, ids=[o.id for o in mo])              # ③ production order
    mo_id = next(r.id for r in x.receipts if r.product == "A")
    x, _ = post(x, "receive", order=mo_id, on=JAN5)                          # ④ GR 101 + backflush 261
    issued = sum(m.qty for m in x.movements if m.type is MovementType.ISSUE and m.product == "B")
    assert issued == pytest.approx(100)
    x, _ = roll_forward(x, date(2026, 1, 6))
    x, rep = sales.create_order(x, "CU", [{"product": "A", "qty": 30, "date": "2026-01-15"}])   # ⑥ order
    assert rep.promises[0].on_time == 30                                     # ⑦ confirmed from stock
    plan2 = run_mrp(x)
    fc = next(r for r in plan2.requirements if r.kind == "forecast" and r.product == "A")
    assert fc.consumed_forecast == pytest.approx(30)                         # consumes the PIR
    x, _ = sales.create_deliveries(x, on=date(2026, 1, 13))                  # ⑧ delivery
    x, _ = sales.issue(x, x.deliveries[-1].id, on=date(2026, 1, 13))         # ⑩ PGI
    x, _ = sales.create_invoices(x, on=date(2026, 1, 13))                    # ⑪ billing
    assert x.invoices[-1].net == 1500
    x, _ = sales.pay(x, x.invoices[-1].id, on=date(2026, 1, 20))
    x, _ = roll_forward(x, date(2026, 1, 19))
    assert next(y for y in x.location_products if (y.location, y.product) == ("P", "A")).on_hand == 20
    assert any(c.kind == "sales" and c.delivered_qty == 30 for c in x.closed_orders)


def test_16_2_scenario_b_make_to_order_plans_supply_per_order_and_ignores_the_forecast():
    """§16.2 strategy 20: 'no PIR consumption; each order creates its own supply chain'. Strategy 25 (variant
    configuration) is N/A. Gap: the app's MTO nets anonymously — no sales-order stock (segment E), so supply made for
    one order can serve another (logged)."""
    d = o2c()
    lp(d, "P", "A").update(on_hand=0, strategy="MTO")
    d["demand"] = [demand("CU", "A", "2026-01-15", 100),
                   demand("CU", "A", "2026-01-20", 7, "sales_order", id="SO-9")]
    plan = run_mrp(ds(d))
    assert sum(o.qty for o in plan.orders if o.product == "A" and o.location == "P") == pytest.approx(7)


def test_16_3_scenario_c_subcontracting_value_is_service_plus_components():
    """§16.3: 'value = service charge + provided components'. Third-party (TAS) has no equivalent: N/A/gap."""
    d = make_only()
    d["production_sources"][0].pop("fixed_lead_time_workdays")
    d["production_sources"][0]["operations"] = [
        {"seq": 10, "subcontract": {"supplier": "S", "workdays": 3, "cost_per_unit": 12}}]
    plan = run_mrp(ds(d))
    uv = {(n.location, n.product): n.unit_value for n in plan.nodes}
    assert uv[("P", "A")] == pytest.approx(2 * 10 + 1 * 5 + 12)
    # the components are still issued at the plant (no special stock O at the supplier)
    assert any(r.product == "B" and r.location == "P" and r.kind == "dependent" for r in plan.requirements)


# =================================================================================================================
# §18.2 KPI set
# =================================================================================================================
def kpi_fixture() -> dict:
    d = base()

    def co(kind, oid, ordered, delivered, due, last, promised=None, first=None, cp="P"):
        return {"kind": kind, "id": oid, "location": "P", "product": "A", "counterparty": cp, "ordered_qty": ordered,
                "delivered_qty": delivered, "due_date": due, "promised_date": promised,
                "first_delivery": first or last, "last_delivery": last, "closed_on": last}
    d["closed_orders"] = [
        co("production", "M1", 10, 10, "2025-12-24", "2025-12-26"),           # in its week (Mon 22 Dec)
        co("production", "M2", 10, 10, "2025-12-31", "2026-01-02"),           # in its week (Mon 29 Dec)
    ]
    return d


def test_18_2_schedule_adherence_counts_open_orders_whose_planned_week_is_over():
    """Regression (fails on main): §18.2 'Schedule adherence: orders finished in the planned period ÷ orders
    planned'. Two orders finished in their week; a third, due Tue 30 Dec, is still open on Mon 5 Jan. Planned 3,
    finished on plan 2 → 2/3; main showed 2/2 = 100 % because only closed orders counted."""
    d = kpi_fixture()
    d["receipts"] = [{"id": "M3", "kind": "production", "location": "P", "product": "A", "qty": 10,
                      "due_date": "2025-12-30", "start_date": "2025-12-29", "source": "PV-A"},
                     {"id": "M4", "kind": "production", "location": "P", "product": "A", "qty": 10,
                      "due_date": "2026-01-07", "start_date": "2026-01-06", "source": "PV-A"}]   # this week: not yet due
    k = kpis(d)["schedule_adherence"]
    assert (k.numerator, k.denominator) == (2, 3) and k.value == pytest.approx(2 / 3)
    assert "1 open order past its planned week" in k.note


def test_18_2_schedule_adherence_unchanged_when_nothing_is_overdue():
    k = kpis(kpi_fixture())["schedule_adherence"]
    assert (k.numerator, k.denominator) == (2, 2)


def test_18_2_days_of_supply_is_stock_value_over_average_daily_requirement_value():
    """§18.2 'Inventory days / days of supply: stock ÷ average daily requirement'. 56 A on hand, 112 required over a
    28-day horizon (4 a day) → 14 days, whatever the unit value."""
    d = base(horizon=28)
    lp(d, "P", "A")["on_hand"] = 56
    lp(d, "P", "B")["on_hand"] = 0
    d["products"][0]["standard_cost"] = 7
    d["demand"] = [demand("P", "A", f"2026-01-{day:02d}", 28) for day in (6, 13, 20, 27)]
    k = kpis(d)["days_of_supply"]
    fg = next(r for r in k.breakdown if r.label == "FG")
    assert fg.value == pytest.approx(56 / (112 / 28))


def test_18_2_otif_counts_in_full_within_tolerance_and_on_time_to_the_confirmed_date():
    """§18.2 OTIF (to the confirmed and, separately, the requested date) and perfect order (delivery part)."""
    d = base()

    def co(oid, ordered, delivered, due, last, promised):
        return {"kind": "sales", "id": oid, "location": "CU", "product": "A", "ordered_qty": ordered,
                "delivered_qty": delivered, "due_date": due, "promised_date": promised, "first_delivery": last,
                "last_delivery": last, "closed_on": last}
    d["locations"].append({"id": "CU", "type": "customer"})
    d["closed_orders"] = [co("S1", 100, 98, "2026-01-02", "2026-01-02", "2026-01-02"),    # 2 % short: in full
                          co("S2", 100, 97, "2026-01-02", "2026-01-02", "2026-01-02"),    # 3 % short: not
                          co("S3", 100, 100, "2026-01-01", "2026-01-03", "2026-01-03")]   # late to requested only
    k = kpis(d)
    assert k["otif_confirmed"].value == pytest.approx(2 / 3)
    assert k["otif_requested"].value == pytest.approx(1 / 3)
    assert k["perfect_order"].value == pytest.approx(0 / 3)               # S1 short by 2 has no tolerance here


def test_18_2_api_shows_every_kpi_with_its_definition():
    r = client.post("/api/tower", json=kpi_fixture())
    assert r.status_code == 200, r.text
    ids = {k["id"] for k in r.json()["kpis"]}
    assert {"forecast_accuracy", "forecast_bias", "confirmation_rate", "otif_confirmed", "otif_requested",
            "perfect_order", "supplier_reliability", "schedule_adherence", "days_of_supply", "excess_obsolete",
            "plan_stability", "exception_ageing", "cost_to_serve"} <= ids
    assert all(k["definition"] for k in r.json()["kpis"])


def test_promise_commit_keeps_inspection_stock_out_of_confirmations():
    """The committed confirmations (what sales sees) follow the same scope of check."""
    x, _ = roll_forward(ds(qi_company()), JAN5)
    x, _ = commit(x)
    assert not [c for c in x.confirmations if c.order == "SO-1" and c.ship_date <= date(2026, 1, 6)]
