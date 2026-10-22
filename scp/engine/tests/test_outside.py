"""Enterprise 7.1: third-party (drop-ship) orders and job work on Kaveri, against hand-worked figures.

Kaveri's 750 W motor (PV-MOT-750) takes 0.55 kg of copper wire (2 % component scrap) and one lamination set (1 %)
per motor, with 1.5 % of started motors lost: wire per good motor = 0.55 / 0.985 / 0.98, sets = 1 / 0.985 / 0.99.
MO-100461 makes 600 of them.
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from scp import dropship as dsh
from scp import jobwork as jw
from scp import sales
from scp.actuals.documents import StockError, reverse
from scp.actuals.post import _posted
from scp.actuals.valuation import value_stock
from scp.model import Customer
from scp.plan import run_mrp
from scp.purchasing import payables as ap
from scp.validate import validate

from .factory import load_example

WIRE = 0.55 / 0.985 / 0.98
SETS = 1 / 0.985 / 0.99
SENT_ON = date(2026, 10, 5)


@pytest.fixture(scope="module")
def kaveri():
    return load_example("kitchenware_network")


def _plant(ds, product: str) -> float:
    return sum(m.signed for m in ds.movements if m.location == "PLT-PUNE" and m.product == product)


def _sent(ds):
    return jw.send(ds, "MO-100461", "SUP-WIND", on=SENT_ON, charge=18, vehicle="MH12 AB 4521")


# ------------------------------------------------------------------------------------------------ job work
def test_parts_to_send_are_the_bill_for_what_is_left(kaveri):
    parts = {p["product"]: p["qty"] for p in jw.parts_to_send(kaveri, "MO-100461")}
    assert parts["RM-CU-WIRE"] == pytest.approx(600 * WIRE, abs=1e-5)      # 341.86 kg: weighed, not counted
    assert parts["RM-STAMP"] == math.ceil(600 * SETS) == 616                 # 615.29 sets: whole ones go out


def test_send_issues_the_parts_to_the_order_and_holds_them_at_the_job_worker(kaveri):
    before = {p: _plant(kaveri, p) for p in ("RM-CU-WIRE", "RM-STAMP")}
    ds, rep = _sent(kaveri)
    c = ds.challans[-1]
    assert rep.challan == c.id == "JW-00001" and c.job_worker == "SUP-WIND" and c.order == "MO-100461"
    assert _plant(ds, "RM-CU-WIRE") == pytest.approx(before["RM-CU-WIRE"] - 600 * WIRE, abs=1e-5)
    assert _plant(ds, "RM-STAMP") == pytest.approx(before["RM-STAMP"] - 616)
    _, _, issued = _posted(ds, "MO-100461")          # the order's backflush sees them as issued
    assert issued[("PLT-PUNE", "RM-STAMP")] == pytest.approx(616)
    assert {m.counterparty for m in ds.movements if m.id in rep.movements} == {"SUP-WIND"}
    v = jw.view(ds, SENT_ON)
    row = v.challans[0]
    assert row.status == "at job worker" and row.due == date(2027, 10, 5)    # one year for inputs
    assert row.value_sent == pytest.approx(sum(ln.qty * ln.value for ln in c.lines), abs=0.01)
    assert row.job_worker_gstin == "27AAKFB4417M1Z5" and row.ship_from_gstin == "27AAJCK4821M1Z3"
    assert {(s.product, round(s.qty, 4)) for s in v.stock} == {("RM-CU-WIRE", round(600 * WIRE, 4)),
                                                              ("RM-STAMP", 616)}
    assert "Back by Tue 5 Oct 2027" in rep.message and "three copies" in rep.message
    assert validate(ds) == []


def test_send_refuses_what_is_not_a_job_worker_or_an_open_order(kaveri):
    with pytest.raises(jw.JobWorkError, match="not a supplier"):
        jw.send(kaveri, "MO-100461", "DC-DELHI")
    with pytest.raises(jw.JobWorkError, match="not an open production order"):
        jw.send(kaveri, "PO-4500012871", "SUP-WIND")
    with pytest.raises(jw.JobWorkError, match="routing has no step done outside"):
        jw.send(kaveri, "MO-100461")
    ds, _ = _sent(kaveri)
    with pytest.raises(jw.JobWorkError, match="needs no more parts"):
        jw.send(ds, "MO-100461", "SUP-WIND")                  # everything is out there already


def test_processed_goods_use_up_the_parts_and_are_received_on_the_order(kaveri):
    ds, _ = _sent(kaveri)
    stock_wire = _plant(ds, "RM-CU-WIRE")
    ds, rep = jw.receive(ds, "JW-00001", 580, on=date(2026, 10, 12), reference="BWW/114")
    c = ds.challans[-1]
    r = c.returns[-1]
    assert r.kind == "processed" and r.product == "MOT-750" and r.qty == 580
    assert r.used["RM-CU-WIRE"] == pytest.approx(580 * WIRE, abs=1e-5)
    assert r.used["RM-STAMP"] == pytest.approx(580 * SETS, abs=1e-5)
    assert c.at_job_worker("RM-STAMP") == pytest.approx(616 - 580 * SETS, abs=1e-5)
    posted = [m for m in ds.movements if m.id in rep.movements]
    assert [(m.type.value, m.product, m.qty) for m in posted] == [("receipt", "MOT-750", 580)]
    assert _plant(ds, "RM-CU-WIRE") == pytest.approx(stock_wire)          # not taken a second time
    assert "Job charge INR 10,440.00 due" in rep.message                    # 580 × 18
    # the last 20: the wire is exactly used up; 0.71 of a set left over is the bill's fraction, used up with them
    ds, rep = jw.receive(ds, "JW-00001", 20, on=date(2026, 10, 14))
    c = ds.challans[-1]
    assert c.at_job_worker("RM-CU-WIRE") == pytest.approx(0, abs=1e-6)
    assert c.at_job_worker("RM-STAMP") == pytest.approx(0, abs=1e-6)
    assert c.closed_on == date(2026, 10, 14) and "is closed" in rep.message
    assert not any(x.id == "MO-100461" for x in ds.receipts) or _posted(ds, "MO-100461")[0][
        ("PLT-PUNE", "MOT-750")] == pytest.approx(600)


def test_a_plain_receipt_of_the_order_does_not_take_the_sent_parts_again(kaveri):
    from scp.actuals.post import receive
    ds, _ = _sent(kaveri)
    wire = _plant(ds, "RM-CU-WIRE")
    ds, rep = receive(ds, "MO-100461", 600, on=date(2026, 10, 12))
    assert _plant(ds, "RM-CU-WIRE") == pytest.approx(wire, abs=1e-6)
    assert [m.product for m in ds.movements if m.id in rep.movements] == ["MOT-750"]


def test_unused_parts_come_back_as_a_partial_reversal(kaveri):
    ds, _ = _sent(kaveri)
    sets = _plant(ds, "RM-STAMP")
    ds, rep = jw.return_unused(ds, "JW-00001", "RM-STAMP", 16, on=date(2026, 10, 8), reference="BWW/101")
    back = [m for m in ds.movements if m.id in rep.movements]
    assert len(back) == 1 and back[0].reversal_of in ds.challans[-1].lines[1].movements and back[0].qty == 16
    assert _plant(ds, "RM-STAMP") == pytest.approx(sets + 16)
    assert _posted(ds, "MO-100461")[2][("PLT-PUNE", "RM-STAMP")] == pytest.approx(600)
    assert ds.challans[-1].at_job_worker("RM-STAMP") == pytest.approx(600)
    with pytest.raises(jw.JobWorkError, match="only 600"):
        jw.return_unused(ds, "JW-00001", "RM-STAMP", 601)
    # the same issue taken back twice, in parts: what is left of it is tracked
    ds, _ = jw.return_unused(ds, "JW-00001", "RM-STAMP", 100, on=date(2026, 10, 9))
    assert _plant(ds, "RM-STAMP") == pytest.approx(sets + 116)


def test_the_send_is_not_reversed_behind_the_challans_back(kaveri):
    ds, rep = _sent(kaveri)
    with pytest.raises(StockError, match="challan JW-00001"):
        reverse(ds, rep.movements[0])


def test_cancel_takes_every_part_back_and_lost_parts_stay_used(kaveri):
    ds, _ = _sent(kaveri)
    wire, sets = _plant(kaveri, "RM-CU-WIRE"), _plant(kaveri, "RM-STAMP")
    ds2, _ = jw.cancel(ds, "JW-00001", on=date(2026, 10, 6))
    assert _plant(ds2, "RM-CU-WIRE") == pytest.approx(wire, abs=1e-6) and _plant(ds2, "RM-STAMP") == pytest.approx(sets)
    assert ds2.challans[-1].cancelled and jw.view(ds2).challans[0].value_out == 0
    ds3, rep = jw.write_off(ds, "JW-00001", "RM-STAMP", 4, on=date(2026, 10, 8), reference="spoiled in varnishing")
    assert ds3.challans[-1].at_job_worker("RM-STAMP") == pytest.approx(612)
    assert _plant(ds3, "RM-STAMP") == pytest.approx(sets - 616)           # no stock comes back
    with pytest.raises(jw.JobWorkError, match="take back the rest as unused"):
        jw.cancel(ds3, "JW-00001")


def test_gst_limit_names_the_challan_then_counts_it_as_supplied(kaveri):
    ds, _ = _sent(kaveri)
    ds = ds.model_copy(update={"products": [p.model_copy(update={"tax_rate": 0.18}) if p.id == "RM-CU-WIRE" else p
                                            for p in ds.products]})
    ds, _ = jw.receive(ds, "JW-00001", 500, on=date(2026, 11, 2))
    c = ds.challans[-1]
    wire_left = 600 * WIRE - 500 * WIRE
    soon = jw.view(ds, date(2027, 9, 10))
    assert soon.challans[0].status == "due soon" and soon.challans[0].days_left == 25 and soon.deemed == []
    late = jw.view(ds, date(2027, 10, 6))
    assert late.challans[0].status == "overdue"
    d = {x.product: x for x in late.deemed}
    wire_value = next(ln.value for ln in c.lines if ln.product == "RM-CU-WIRE")
    assert d["RM-CU-WIRE"].qty == pytest.approx(wire_left, abs=1e-5)
    assert d["RM-CU-WIRE"].tax == pytest.approx(round(round(wire_left * wire_value, 2) * 0.18, 2), abs=0.01)
    assert d["RM-STAMP"].tax == 0                          # Kaveri's company rate is 0 %
    # the go-live check names it once the plan has moved past the limit
    rolled = ds.model_copy(update={"settings": ds.settings.model_copy(update={"planning_start": date(2027, 10, 11)})})
    assert [(i.code, i.object_id) for i in validate(rolled) if i.code == "JOBWORK_DUE"] == [("JOBWORK_DUE", "JW-00001")]


def test_capital_goods_have_three_years(kaveri):
    ds, _ = jw.send(kaveri, "MO-100461", "SUP-WIND", [{"product": "RM-STAMP", "qty": 1, "capital_goods": True}],
                    on=SENT_ON)
    assert jw.view(ds, SENT_ON).challans[0].lines[0].due == date(2029, 10, 4)   # 1,095 days: 2028 is a leap year


def test_itc04_lists_what_went_out_and_what_came_back_in_the_half_year(kaveri):
    ds, _ = _sent(kaveri)
    ds, _ = jw.receive(ds, "JW-00001", 580, on=date(2026, 10, 12), reference="BWW/114")
    ds, _ = jw.return_unused(ds, "JW-00001", "RM-STAMP", 5, on=date(2026, 10, 12), reference="BWW/114")
    ds, _ = jw.write_off(ds, "JW-00001", "RM-CU-WIRE", 1, on=date(2026, 10, 12))
    v = jw.view(ds, date(2026, 10, 20))
    assert (v.period, v.period_start, v.period_end) == ("Oct 2026–Mar 2027", date(2026, 10, 1), date(2027, 3, 31))
    rows = [(x.table, x.product, x.hsn, x.uqc, round(x.qty, 2), x.goods, x.their_challan) for x in v.itc04]
    assert rows == [("4", "RM-CU-WIRE", "85441110", "KGS", round(600 * WIRE, 2), "inputs", ""),
                    ("4", "RM-STAMP", "85030010", "NOS", 616, "inputs", ""),
                    ("5A", "MOT-750", "85013119", "NOS", 580, "processed goods", "BWW/114"),
                    ("5A", "RM-STAMP", "85030010", "NOS", 5, "inputs", "BWW/114")]       # the loss is no return
    assert {x.job_worker_state for x in v.itc04} == {"Maharashtra"}                     # GSTIN state 27
    assert jw.view(ds, date(2026, 9, 30)).period == "Apr–Sep 2026"
    assert jw.view(ds, date(2026, 9, 30)).itc04 == []


def test_the_job_charge_is_matched_like_an_order_line_and_stays_out_of_stock_value(kaveri):
    ds, _ = _sent(kaveri)
    ds, _ = jw.receive(ds, "JW-00001", 580, on=date(2026, 10, 12))
    due = [x for x in ap.to_invoice(ds) if x.order == "JW-00001"]
    assert [(x.supplier, x.product, x.qty, x.price, x.value) for x in due] == [("SUP-WIND", "MOT-750", 580, 18, 10440)]
    books = value_stock(ds, date(2026, 10, 14))
    ok, rep = ap.enter_invoice(ds, None, [{"order": "JW-00001"}], on=date(2026, 10, 14), reference="BWW/INV/88",
                               delivery_costs=650)
    assert ok.supplier_invoices[-1].blocks == [] and "matches the order" in rep.message
    after = value_stock(ok, date(2026, 10, 14))
    assert (after.rows, after.differences) == (books.rows, books.differences)
    over, _ = ap.enter_invoice(ds, None, [{"order": "JW-00001", "qty": 600}], on=date(2026, 10, 14))
    assert over.supplier_invoices[-1].blocks == ["quantity: JW-00001 bills 600; 580 received and not yet invoiced"]
    with pytest.raises(ap.PayablesError, match="did not come into our stock"):
        ap.return_goods(ds, "JW-00001", 1)


def test_validation_names_a_challan_that_no_longer_fits(kaveri):
    ds, _ = _sent(kaveri)
    c = ds.challans[-1]
    bad = ds.model_copy(update={"challans": [c.model_copy(update={"order": "MO-999"})],
                                "movements": [m for m in ds.movements if m.id not in c.lines[0].movements]})
    found = {(i.code, i.object_id, i.message.split(",")[0]) for i in validate(bad) if i.code == "OUTSIDE_MISFIT"}
    assert found == {("OUTSIDE_MISFIT", "JW-00001", "is for MO-999"),
                     ("OUTSIDE_MISFIT", "JW-00001", f"sent its parts with {c.lines[0].movements[0]}")}


# ------------------------------------------------------------------------------------------------ drop-ship
def _tp(ds, qty=500, **kw):
    return dsh.create(ds, "CUS-ECOM", "KT-15", qty, date(2026, 10, 16), "SUP-VASAI", cost=742,
                      customer_ref="FK-PO-55120", on=SENT_ON, **kw)


def test_a_third_party_order_takes_the_customers_price_and_planning_never_sees_it(kaveri):
    ds, rep = _tp(kaveri)
    t = ds.third_party_orders[-1]
    assert (t.id, t.price, t.cost, t.currency) == ("TP-00001", 1190, 742, None)        # KT-15's list price
    assert "INR 224,000.00 margin" in rep.message                                      # 500 × (1,190 − 742)
    a, b = run_mrp(kaveri), run_mrp(ds)
    assert a.orders and [o.model_dump() for o in a.orders] == [o.model_dump() for o in b.orders]
    assert validate(ds) == []


def test_dispatches_are_billed_and_matched_and_close_short(kaveri):
    ds, _ = _tp(kaveri)
    with pytest.raises(dsh.DropShipError, match="not been sent"):
        dsh.dispatch(ds, "TP-00001", 10)
    ds, _ = dsh.send(ds, "TP-00001", on=SENT_ON)
    with pytest.raises(dsh.DropShipError, match="more than Vasai appliance works may send"):
        dsh.dispatch(ds, "TP-00001", 511)                   # 2 % over 500 is 510
    stock = value_stock(ds, date(2026, 10, 10)).rows
    ds, _ = dsh.dispatch(ds, "TP-00001", 300, on=date(2026, 10, 9), reference="LR 66012")
    assert value_stock(ds, date(2026, 10, 10)).rows == stock                    # no stock moves
    due = [b for b in sales.to_bill(ds) if b.order == "TP-00001"]
    assert [(b.qty, b.price, b.value, b.movements) for b in due] == [(300, 1190, 357000, ["TP-00001#1"])]
    ds, _ = sales.create_invoices(ds, ["TP-00001"], on=date(2026, 10, 9))
    assert ds.invoices[-1].net == 357000 and not [b for b in sales.to_bill(ds) if b.order == "TP-00001"]
    owed = [x for x in ap.to_invoice(ds) if x.order == "TP-00001"]
    assert [(x.supplier, x.qty, x.price, x.value, x.location) for x in owed] == [
        ("SUP-VASAI", 300, 742, 222600, "CUS-ECOM")]
    blocked, _ = ap.enter_invoice(ds, None, [{"order": "TP-00001", "qty": 301}], on=date(2026, 10, 10))
    assert blocked.supplier_invoices[-1].blocks[0].startswith("quantity: TP-00001 bills 301")
    books = value_stock(ds, date(2026, 10, 10))
    ds, _ = ap.enter_invoice(ds, None, [{"order": "TP-00001", "qty": 300}], on=date(2026, 10, 10),
                             reference="VAW/2210", delivery_costs=1800)
    after = value_stock(ds, date(2026, 10, 10))
    assert (after.rows, after.differences) == (books.rows, books.differences)  # their freight is no cost of our stock
    ds, rep = dsh.dispatch(ds, "TP-00001", 195, on=date(2026, 10, 14), final=True)
    assert "closed 5 short" in rep.message
    row = dsh.view(ds, date(2026, 10, 14)).orders[0]
    assert (row.status, row.shipped, row.billed, row.supplier_invoiced) == ("dispatched", 495, 300, 300)
    assert row.margin == 495 * (1190 - 742)                 # closed short: what was shipped
    with pytest.raises(dsh.DropShipError, match="complete"):
        dsh.dispatch(ds, "TP-00001", 5)
    with pytest.raises(dsh.DropShipError, match="close it with a final dispatch"):
        dsh.cancel(ds, "TP-00001")


def test_open_third_party_orders_count_against_credit(kaveri):
    ds, _ = _tp(kaveri)
    open_v, _, _ = sales.exposure(ds, "CUS-ECOM")
    base_v, _, _ = sales.exposure(kaveri, "CUS-ECOM")
    assert open_v - base_v == pytest.approx(500 * 1190)            # Kaveri charges no tax on these lines
    _, unbilled, owed = sales.exposure(kaveri, "CUS-ECOM")
    room = 400_000                                          # less than 500 × 1,190 = 595,000
    tight = kaveri.model_copy(update={"customers": [Customer(customer="CUS-ECOM",
                                                             credit_limit=base_v + unbilled + owed + room)]})
    assert tight.sales.credit_check
    with pytest.raises(dsh.DropShipError, match="credit limit"):
        _tp(tight)
    ds, _ = _tp(tight, qty=300)                             # 357,000 fits


def test_cancelled_before_dispatch_carries_no_margin(kaveri):
    ds, _ = _tp(kaveri)
    ds, rep = dsh.cancel(ds, "TP-00001")
    row = dsh.view(ds).orders[0]
    assert row.status == "cancelled" and row.margin == 0 and dsh.view(ds).margin == 0 and "cancelled" in rep.message


def test_goods_back_after_parts_came_back_unused_never_take_the_gap_from_the_plant(kaveri):
    ds, _ = _sent(kaveri)
    ds, _ = jw.return_unused(ds, "JW-00001", "RM-STAMP", 100, on=date(2026, 10, 8))    # 516 sets left there
    sets = _plant(ds, "RM-STAMP")
    ds, rep = jw.receive(ds, "JW-00001", 580, on=date(2026, 10, 12))                  # the bill says 571.2
    assert _plant(ds, "RM-STAMP") == pytest.approx(sets)
    assert ds.challans[-1].returns[-1].used["RM-STAMP"] == pytest.approx(516)
    assert f"{580 * SETS - 516:,.2f} Stator/rotor lamination set more than was sent" in rep.message


def test_through_the_api(kaveri):
    from fastapi.testclient import TestClient

    from scp.api.app import app
    client = TestClient(app)
    d = kaveri.model_dump(mode="json")
    r = client.post("/api/outside/parts", json={"dataset": d, "order": "MO-100461"})
    assert r.status_code == 200 and [p["qty"] for p in r.json()][1] == 616
    r = client.post("/api/outside/act", json={"dataset": d, "action": "send_parts", "production_order": "MO-100461",
                                              "supplier": "SUP-WIND", "charge": 18, "date": "2026-10-05"})
    assert r.status_code == 200 and r.json()["id"] == "JW-00001"
    d2 = r.json()["dataset"]
    r = client.post("/api/outside", json=d2, params={"as_of": "2026-10-05"})
    assert r.status_code == 200 and r.json()["job_work"]["challans"][0]["status"] == "at job worker"
    r = client.post("/api/outside/act", json={"dataset": d2, "action": "back_unused", "id": "JW-00001",
                                              "product": "RM-STAMP", "qty": 700})
    assert r.status_code == 409 and "only 616" in r.json()["detail"]
    r = client.post("/api/outside/act", json={"dataset": d, "action": "order", "customer": "CUS-ECOM",
                                              "product": "KT-15", "qty": 500, "wanted": "2026-10-16",
                                              "supplier": "SUP-VASAI", "cost": 742})
    assert r.status_code == 200 and r.json()["id"] == "TP-00001"
    r = client.post("/api/outside/act", json={"dataset": d, "action": "dispatch", "id": "TP-00001"})
    assert r.status_code == 409 and "no third-party order" in r.json()["detail"]
