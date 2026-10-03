"""Phase N: procure to pay. Supplier invoices checked against the order and the goods received (three-way match),
blocked and released, paid with the cash discount; what is owed to whom and what was received but not invoiced;
returns to the supplier, credited or replaced; a release strategy with several levels; contracts and scheduling
agreements; a supplier's confirmation in several deliveries; firming that sends what it ordered (R20)."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals import firm_orders, roll_forward
from scp.api.app import app
from scp.plan import run_mrp
from scp.purchasing import (
    PurchasingError, act, create_agreement, create_purchase_orders, purchase_orders, purchasing_view, requisitions,
)
from scp.purchasing.payables import payables_view, still_blocked, to_invoice
from scp.validate import validate

from .factory import base, demand, ds, lp

client = TestClient(app)
JAN = date(2026, 1, 5)


def ordered(**purchasing) -> dict:
    """PO-00001 to supplier S: 100 B at 10 and 50 C at 5. We pay S 2 % within 10 days, net 30, with 10 % tax."""
    d = base(horizon=42)
    d["locations"][1]["name"] = "Sharma Metals"
    d["payment_terms"] = [{"id": "2-10-30", "name": "2 % 10 days, net 30", "net_days": 30, "discount_days": 10,
                           "discount": 0.02}]
    d["vendors"] = [{"supplier": "S", "payment_terms": "2-10-30"}]
    d["purchasing"] = {"tax_rate": 0.1, **purchasing}
    d["purchase_orders"] = [{"id": "PO-00001", "supplier": "S", "location": "P", "order_date": "2026-01-02",
                             "sent_on": "2026-01-02"}]
    d["receipts"] = [
        {"id": "PO-00001-10", "kind": "purchase", "location": "P", "product": "B", "qty": 100, "due_date": "2026-01-05",
         "source": "PIR-B", "po": "PO-00001", "price": 10},
        {"id": "PO-00001-20", "kind": "purchase", "location": "P", "product": "C", "qty": 50, "due_date": "2026-01-05",
         "source": "PIR-C", "po": "PO-00001", "price": 5},
    ]
    return d


def received(b: float = 100, c: float = 30, **kw):
    x = ds(ordered(**kw))
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": b}, {"id": "PO-00001-20", "qty": c}],
               on=JAN)
    return x


# ---- invoice verification -----------------------------------------------------------------------------------
def test_an_invoice_for_what_was_received_at_the_order_price_matches_and_is_paid_with_the_cash_discount():
    x = received()
    x, rep = act(x, "enter_invoice", "PO-00001", on=JAN, reference="INV-9")
    inv = x.supplier_invoices[0]
    assert inv.id == "SI-00001" and [(ln.order, ln.qty, ln.price) for ln in inv.lines] == [
        ("PO-00001-10", 100, 10), ("PO-00001-20", 30, 5)]
    assert inv.net == 1150 and inv.tax == 115 and inv.total == 1265 and not inv.blocks
    assert inv.due_date == date(2026, 2, 4) and inv.discount_date == date(2026, 1, 15)
    assert "SI-00001 from Sharma Metals (their INV-9): INR 1,265.00, 2 lines; matches the order" in rep.message
    assert "2% off if paid by 2026-01-15" in rep.message
    # the same invoice number twice is refused
    with pytest.raises(PurchasingError, match="INV-9 is already entered as SI-00001"):
        act(x, "enter_invoice", "PO-00001", on=JAN, reference="inv-9",
            lines=[{"order": "PO-00001-20", "qty": 1}])
    pv = payables_view(x)
    assert pv.payables[0].open == 1265 and pv.payables[0].next_due == date(2026, 2, 4)
    assert [g.order for g in pv.to_invoice] == []           # all received is invoiced
    x, rep = act(x, "pay_invoice", "SI-00001", on=date(2026, 1, 12), reference="NEFT-1")
    p = x.supplier_invoices[0].payments[0]
    assert p.amount == pytest.approx(1239.70) and p.discount == pytest.approx(25.30)
    assert "INR 1,239.70 paid on SI-00001, cash discount INR 25.30; settled." == rep.message
    assert payables_view(x).invoices[0].status == "paid" and not payables_view(x).payables


def test_freight_on_an_invoice_and_a_later_price_correction_by_subsequent_debit_and_credit():
    x = received()
    x, rep = act(x, "enter_invoice", "PO-00001", on=JAN, reference="INV-9", delivery_costs=80)
    inv = x.supplier_invoices[0]
    assert inv.delivery_costs == 80 and inv.net == 1230 and inv.tax == 123 and inv.total == 1353 and not inv.blocks
    assert "2 lines and INR 80.00 delivery costs; matches the order" in rep.message
    assert payables_view(x).invoices[0].delivery_costs == 80
    # the price of what was invoiced goes up 0.10 on B (within tolerance): a debit, the quantity invoiced unchanged
    x, rep = act(x, "enter_invoice", "", on=JAN, kind="subsequent_debit", reference="DN-1",
                 lines=[{"order": "PO-00001-10", "price": 0.1}])
    sd = x.supplier_invoices[1]
    assert sd.id == "SD-00001" and sd.lines[0].qty == 100 and sd.total == 11 and not sd.blocks
    assert rep.message == ("Subsequent debit SD-00001 from Sharma Metals (their DN-1): INR 11.00 "
                           "(more per unit: PO-00001-10 0.10 on 100).")
    assert [g.order for g in payables_view(x).to_invoice] == []       # still all invoiced, nothing billed twice
    # a further 0.50 takes B to 10.60, beyond the 2 % tolerance: blocked like an invoice
    y, rep = act(x, "enter_invoice", "", on=JAN, kind="subsequent_debit",
                 lines=[{"order": "PO-00001-10", "price": 0.5}])
    assert y.supplier_invoices[2].blocks and still_blocked(y, y.supplier_invoices[2])
    assert "blocked for payment: PO-00001-10 invoiced at 10.60" in rep.message
    # a credit for 0.20 on 50 units is owed to us; what we owe falls by it
    x, rep = act(x, "enter_invoice", "", on=JAN, kind="subsequent_credit",
                 lines=[{"order": "PO-00001-10", "qty": 50, "price": 0.2}])
    sc = x.supplier_invoices[2]
    assert sc.id == "SC-00001" and sc.total == 11 and sc.due_date == JAN
    assert payables_view(x).payables[0].open == pytest.approx(1353 + 11 - 11)
    # a correction needs an invoice, a difference and no more than was invoiced
    with pytest.raises(PurchasingError, match="not invoiced yet"):
        act(received(), "enter_invoice", "", kind="subsequent_debit", lines=[{"order": "PO-00001-10", "price": 1}])
    with pytest.raises(PurchasingError, match="at most the 100 invoiced"):
        act(x, "enter_invoice", "", kind="subsequent_credit", lines=[{"order": "PO-00001-10", "qty": 101,
                                                                       "price": 1}])
    with pytest.raises(PurchasingError, match="give the price difference"):
        act(x, "enter_invoice", "", kind="subsequent_debit", lines=[{"order": "PO-00001-10"}])
    # returned goods are credited at the corrected price: 10 + 0.10 − 0.20
    x, _ = act(x, "return_goods", "", lines=[{"id": "PO-00001-10", "qty": 10}], on=JAN, stock_type="unrestricted")
    x, rep = act(x, "enter_invoice", "", on=JAN, kind="credit_memo", return_id=x.supplier_returns[0].id)
    assert x.supplier_invoices[-1].lines[0].price == pytest.approx(9.9)


def test_a_price_over_tolerance_blocks_the_invoice_until_someone_releases_it():
    x = received()
    # 1 % over is within the 2 % tolerance
    y, rep = act(x, "enter_invoice", "", on=JAN, lines=[{"order": "PO-00001-10", "qty": 100, "price": 10.1}])
    assert not y.supplier_invoices[0].blocks and "matches" in rep.message
    x, rep = act(x, "enter_invoice", "", on=JAN, reference="INV-10",
                 lines=[{"order": "PO-00001-10", "qty": 100, "price": 10.5}])
    inv = x.supplier_invoices[0]
    assert inv.blocks == ["price: PO-00001-10 invoiced at 10.50, the order says 10.00 (+5.0% each, 50.00 in all)"]
    assert "blocked for payment: PO-00001-10 invoiced at 10.50" in rep.message
    with pytest.raises(PurchasingError, match="SI-00001 is blocked for payment .*release it first"):
        act(x, "pay_invoice", "SI-00001", on=JAN)
    assert payables_view(x).blocked == 1 and payables_view(x).payables[0].blocked == pytest.approx(1155)
    x, rep = act(x, "release_invoice", "SI-00001", on=JAN, by="Asha")
    assert "SI-00001 released for payment by Asha" in rep.message
    assert payables_view(x).invoices[0].status == "released"
    x, _ = act(x, "pay_invoice", "SI-00001", on=date(2026, 2, 1))
    assert x.supplier_invoices[0].payments[0].discount == 0 and x.supplier_invoices[0].open == 0


def test_billing_more_than_arrived_blocks_until_the_rest_comes_and_then_lifts_by_itself():
    x = received(c=30)
    x, rep = act(x, "enter_invoice", "", on=JAN, lines=[{"order": "PO-00001-20", "qty": 50}])
    assert x.supplier_invoices[0].blocks == ["quantity: PO-00001-20 bills 50; 30 received and not yet invoiced"]
    assert still_blocked(x, x.supplier_invoices[0])
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-20", "qty": 20}], on=date(2026, 1, 7))
    assert still_blocked(x, x.supplier_invoices[0]) == []
    assert payables_view(x).invoices[0].status == "to pay"
    x, _ = act(x, "pay_invoice", "SI-00001", on=date(2026, 1, 8))
    assert x.supplier_invoices[0].open == 0


def test_what_is_owed_to_whom_with_goods_received_and_not_invoiced_and_overdue_bills():
    x = received(b=100, c=30)
    rows = to_invoice(x)
    assert [(g.order, g.qty, g.value) for g in rows] == [("PO-00001-10", 100, 1000), ("PO-00001-20", 30, 150)]
    x, _ = act(x, "enter_invoice", "", on=date(2025, 12, 1), lines=[{"order": "PO-00001-20", "qty": 30}])
    pv = payables_view(x)            # as of 5 Jan: due 31 Dec, so overdue
    row = pv.payables[0]
    assert row.overdue == pytest.approx(165) and row.not_invoiced == pytest.approx(1000) and row.terms
    assert pv.invoices[0].days_overdue == 5 and pv.overdue_value == pytest.approx(165)
    # a cancelled invoice frees its lines for billing again
    x, rep = act(x, "cancel_invoice", "SI-00001")
    assert "can be invoiced again" in rep.message and len(to_invoice(x)) == 2


# ---- returns to the supplier --------------------------------------------------------------------------------
def test_goods_sent_back_for_credit_reduce_the_line_and_are_credited_by_a_credit_memo():
    x = received(b=100, c=0)
    x, _ = act(x, "enter_invoice", "PO-00001", on=JAN, reference="INV-11")
    x, rep = act(x, "return_goods", "", lines=[{"id": "PO-00001-10", "qty": 10}], on=JAN, note="bent",
                 stock_type="unrestricted")
    ret = x.supplier_returns[0]
    assert ret.id == "RS-00001" and ret.qty == 10 and not ret.replace and ret.movement
    assert "Return RS-00001: 10 of B sent back to Sharma Metals from P on 2026-01-05 (bent)." in rep.message
    assert "PO-00001-10 is now for 90; a credit memo is expected." in rep.message
    line = next(r for r in x.receipts if r.id == "PO-00001-10")
    assert line.ordered_qty == pytest.approx(90)
    assert [(g.order, g.qty) for g in to_invoice(x)] == [("PO-00001-10", -10)]       # invoiced ahead of the goods
    assert payables_view(x).returns[0].status == "to credit"
    x, rep = act(x, "enter_invoice", "", on=JAN, return_id="RS-00001", reference="CN-4")
    cm = x.supplier_invoices[1]
    assert cm.id == "CM-00001" and cm.kind == "credit_memo" and cm.total == pytest.approx(110)
    assert "Credit memo CM-00001 from Sharma Metals (their CN-4): INR 110.00 for return RS-00001." == rep.message
    assert to_invoice(x) == [] and payables_view(x).returns[0].status == "credited"
    assert payables_view(x).payables[0].open == pytest.approx(1100 - 110)
    # the roll closes the line on the 90 kept, and stock is 30 + 90
    y, _ = roll_forward(x, date(2026, 1, 12))
    assert not any(r.id == "PO-00001-10" for r in y.receipts)
    assert next(c for c in y.closed_orders if c.id == "PO-00001-10").delivered_qty == pytest.approx(90)
    assert lp_on_hand(y, "B") == pytest.approx(120)


def test_goods_sent_back_for_replacement_leave_the_line_open_for_them():
    x = received(b=100, c=0)
    x, rep = act(x, "return_goods", "", lines=[{"id": "PO-00001-10", "qty": 25}], on=JAN, stock_type="unrestricted",
                 replace=True)
    assert "PO-00001-10 is open again for the 25 to be replaced." in rep.message
    y, _ = roll_forward(x, date(2026, 1, 12))
    assert next(r for r in y.receipts if r.id == "PO-00001-10").qty == pytest.approx(25)
    assert payables_view(y).returns[0].status == "replacement due"
    with pytest.raises(PurchasingError, match="only 75 received and not sent back yet"):
        act(x, "return_goods", "", lines=[{"id": "PO-00001-10", "qty": 80}], on=JAN, stock_type="unrestricted")
    with pytest.raises(PurchasingError, match="is blocked: choose where the goods are"):
        act(x, "return_goods", "", lines=[{"id": "PO-00001-10", "qty": 5}], on=JAN)


def lp_on_hand(x, product: str) -> float:
    return next(r.on_hand for r in x.location_products if r.location == "P" and r.product == product)


# ---- release strategy ---------------------------------------------------------------------------------------
def test_a_release_strategy_of_two_levels_with_four_eyes():
    d = ordered(release_levels=[{"name": "Buyer", "above": 500},
                                {"name": "Director", "above": 1000, "approvers": ["dir@example.com"]}])
    d["purchase_orders"][0].update(approved=False, sent_on=None)
    x = ds(d)                                    # worth 1,250: both levels
    v = purchase_orders(x)[0]
    assert v.status == "awaiting approval" and v.levels_needed == ["Buyer", "Director"] and v.next_level == "Buyer"
    assert v.attention[0] == "release it at level Buyer"
    with pytest.raises(PurchasingError, match="not approved yet|above the approval limit"):
        act(x, "send", "PO-00001")
    x, rep = act(x, "approve", "PO-00001", by="ann@example.com")
    assert "PO-00001 released at level Buyer by ann@example.com; still to be released by Director" == rep.message
    with pytest.raises(PurchasingError, match="released at level Director only by dir@example.com, not bob"):
        act(x, "approve", "PO-00001", by="bob")
    d2 = ordered(release_levels=[{"name": "Buyer", "above": 500}, {"name": "Head", "above": 1000}])
    d2["purchase_orders"][0].update(approved=False, approvals=[{"level": "Buyer", "by": "ann", "on": "2026-01-02"}])
    with pytest.raises(PurchasingError, match="ann released PO-00001 at level Buyer: someone else releases level Head"):
        act(ds(d2), "approve", "PO-00001", by="Ann")
    x, rep = act(x, "approve", "PO-00001", by="dir@example.com")
    assert rep.message.endswith("fully released, it can be sent")
    assert x.purchase_orders[0].approved and [a.level for a in x.purchase_orders[0].approvals] == ["Buyer", "Director"]
    x, _ = act(x, "send", "PO-00001")
    # a change that raises the value needs the releases again
    x, rep = act(x, "change", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 150}])
    assert "now worth 1,750: release and send it again" in rep.message
    assert not x.purchase_orders[0].approved and x.purchase_orders[0].approvals == []


def test_new_orders_name_the_levels_they_need():
    d = base(horizon=42)
    d["purchasing"] = {"release_levels": [{"name": "Buyer", "above": 100}, {"name": "Director", "above": 400}]}
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [demand("P", "A", "2026-01-14", 40)]
    x = ds(d)
    y, rep = create_purchase_orders(x, run_mrp(x))
    assert any("to be released by Buyer, then Director before sending" in n for c in rep.created for n in c.notes)
    assert not y.purchase_orders[0].approved


# ---- contracts and scheduling agreements --------------------------------------------------------------------
def _planned(**extra) -> dict:
    d = base(horizon=42)
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 0
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    d["demand"] = [demand("P", "A", "2026-01-14", 40), demand("P", "A", "2026-01-28", 40)]
    d.update(extra)
    return d


def test_orders_take_the_contract_price_and_count_against_its_target():
    d = _planned(contracts=[{"id": "CT-00001", "supplier": "S", "valid_from": "2026-01-01", "valid_to": "2026-01-31",
                             "lines": [{"product": "B", "price": 8, "target_qty": 100}]}])
    x = ds(d)
    plan = run_mrp(x)
    req = next(r for r in requisitions(x, plan) if r.product == "B")
    assert req.price == 8 and req.contract == "CT-00001"
    # the plan's cost uses the contract price too (N131), and the info record's price without the contract
    buys = [o for o in plan.orders if o.kind == "buy" and o.product == "B"]
    assert buys and all(o.costs["purchase"] == pytest.approx(o.qty * 8) for o in buys)
    plain = run_mrp(ds({**d, "contracts": []}))
    info = ds(d).purchasing_source_by_id[buys[0].source_id].price_for(buys[0].qty)
    assert info != 8 and next(o for o in plain.orders if o.id == buys[0].id).costs["purchase"] == pytest.approx(
        buys[0].qty * info)
    y, rep = create_purchase_orders(x, plan, [{"id": r.id} for r in requisitions(x, plan)])
    lines = [r for r in y.receipts if r.product == "B"]
    assert lines and all(r.price == 8 and r.contract == "CT-00001" for r in lines)
    assert any("the price agreed in contract CT-00001" in n for c in rep.created for n in c.notes)
    k = payables_view(y).contracts[0]
    assert k.status == "used up" and k.lines[0].ordered == pytest.approx(160) and k.lines[0].left == pytest.approx(-60)
    assert "B: 60 ordered beyond the 100 agreed" in k.attention
    assert purchase_orders(y)[0].lines[0].contract == "CT-00001"
    # an expired contract does not price anything
    later = ds({**d, "settings": {**d["settings"], "planning_start": "2026-02-02"}})
    assert payables_view(later).contracts[0].status == "expired"
    bad = ds({**d, "contracts": [{**d["contracts"][0], "lines": [{"product": "ZZ", "price": 1}]}]})
    assert any(i.code == "REF_UNKNOWN" and i.object_type == "contract" for i in validate(bad))


def test_a_scheduling_agreement_takes_planning_s_purchases_as_delivery_schedule_lines():
    x = ds(_planned())
    x, rep = create_agreement(x, "S", "P", "B", valid_to=date(2026, 3, 31), target_qty=1000)
    assert x.purchase_orders[0].id == "SA-00001" and x.purchase_orders[0].kind == "scheduling_agreement"
    assert "planning's purchases of it now become delivery schedule lines on it" in rep.message
    with pytest.raises(PurchasingError, match="SA-00001 already schedules B"):
        create_agreement(x, "S", "P", "B")
    plan = run_mrp(x)
    assert next(r for r in requisitions(x, plan) if r.product == "B").agreement == "SA-00001"
    y, rep = create_purchase_orders(x, plan, [{"id": r.id} for r in requisitions(x, plan)])
    lines = sorted(r.id for r in y.receipts if r.po == "SA-00001")
    assert lines == ["SA-00001-10", "SA-00001-20"]
    assert any("2 delivery schedule lines added to scheduling agreement SA-00001" in n
               for c in rep.created for n in c.notes)
    v = next(p for p in purchase_orders(y) if p.id == "SA-00001")
    assert v.kind == "scheduling_agreement" and v.status == "to send" and v.released_qty == pytest.approx(160)
    assert v.attention[0] == "send the changed delivery schedule"
    y, rep = act(y, "send", "SA-00001")
    assert rep.message.startswith("Delivery schedule of SA-00001 sent to S")
    # C is not on the agreement: it goes on a purchase order of its own
    assert {r.po for r in y.receipts if r.product == "C"} == {"PO-00001"}


# ---- several confirmation lines -----------------------------------------------------------------------------
def test_a_confirmation_in_two_deliveries_is_planned_as_two_arrivals():
    d = base(horizon=42, bucket="day")
    lp(d, "P", "B")["on_hand"] = 0
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    d["demand"] = [demand("P", "B", "2026-01-09", 60, kind="sales_order", id="SO-1"),
                   demand("P", "B", "2026-01-16", 40, kind="sales_order", id="SO-2")]
    d["purchase_orders"] = [{"id": "PO-00001", "supplier": "S", "location": "P", "order_date": "2026-01-02",
                             "sent_on": "2026-01-02"}]
    d["receipts"] = [{"id": "PO-00001-10", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
                      "due_date": "2026-01-08", "source": "PIR-B", "po": "PO-00001", "price": 10}]
    x = ds(d)
    one, rep = act(x, "confirm", "PO-00001", lines=[{"id": "PO-00001-10", "date": "2026-01-15"}])
    two, rep = act(x, "confirm", "PO-00001", lines=[{"id": "PO-00001-10", "parts": [
        {"date": "2026-01-08", "qty": 60}, {"date": "2026-01-15", "qty": 40}]}])
    r = two.receipts[0]
    assert [(c.date, c.qty) for c in r.confirmations] == [(date(2026, 1, 8), 60), (date(2026, 1, 15), 40)]
    assert r.confirmed_qty == 100 and r.confirmed_date == date(2026, 1, 15)
    assert "PO-00001-10 in 2 deliveries (60 on 2026-01-08, 40 on 2026-01-15)" in rep.message
    late = [o for o in run_mrp(one).orders if o.product == "B"]
    assert late, "one delivery on the 15th leaves the 9th short: planning orders more"
    assert not [o for o in run_mrp(two).orders if o.product == "B"]
    # half of the first delivery in: the rest of it and the second are still expected
    part, _ = act(two, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 30}], on=date(2026, 1, 8))
    rolled, _ = roll_forward(part, date(2026, 1, 9))
    assert rolled.receipts[0].expected_parts() == [(date(2026, 1, 8), 30), (date(2026, 1, 15), 40)]
    assert purchase_orders(two)[0].lines[0].confirmations[1].qty == 40


# ---- firming sends what it ordered (R20) --------------------------------------------------------------------
def test_firming_can_send_the_purchase_orders_it_makes():
    d = _planned()
    d["execution"] = {"firm_zone_days": 14}
    x = ds(d)
    y, rep = firm_orders(x, run_mrp(x), send=True)
    assert rep.purchase_orders and rep.sent == rep.purchase_orders
    assert all(p.sent_on == date(2026, 1, 5) for p in y.purchase_orders)
    y2, rep2 = firm_orders(x, run_mrp(x))
    assert rep2.sent == [] and all(p.sent_on is None for p in y2.purchase_orders)
    y3, rep3 = act(y2, "send_all", orders=rep2.purchase_orders)
    assert rep3.sent == rep2.purchase_orders and rep3.message.startswith(f"{len(rep3.sent)} order")
    # one still to be released is left and named
    d["purchasing"] = {"approval_limit": 1}
    x = ds(d)
    y, rep = firm_orders(x, run_mrp(x), send=True)
    assert rep.sent == []
    with pytest.raises(PurchasingError, match="no order to send"):
        act(y, "send_all", orders=["PO-99999"])
    _, r = act(y, "send_all", orders=rep.purchase_orders)
    assert "to be released first" in r.message


# ---- through the API ----------------------------------------------------------------------------------------
def test_the_api_enters_pays_and_shows_what_is_owed():
    x = received()
    body = {"dataset": x.model_dump(mode="json"), "action": "enter_invoice", "po": "PO-00001", "date": "2026-01-05",
            "reference": "INV-1"}
    r = client.post("/api/purchasing/act", json=body)
    assert r.status_code == 200, r.text
    y = r.json()["dataset"]
    assert y["supplier_invoices"][0]["id"] == "SI-00001" and r.json()["report"]["id"] == "SI-00001"
    view = client.post("/api/purchasing", json=y).json()
    assert view["payables"]["payables"][0]["open"] == pytest.approx(1265)
    assert view["totals"]["blocked_invoices"] == 0 and view["totals"]["to_invoice"] == 0
    r = client.post("/api/purchasing/act", json={"dataset": y, "action": "pay_invoice", "po": "SI-00001",
                                                 "amount": 5000})
    assert r.status_code == 409 and "more than the INR 1,239.70 still open" in r.json()["detail"]
    r = client.post("/api/orders/firm", json={"dataset": ds(_planned()).model_dump(mode="json"), "send": True,
                                              "within_days": 14})
    assert r.status_code == 200 and r.json()["report"]["sent"]
    assert not purchasing_view(x, run_mrp(x)).payables.invoices


# ---- the worklist ---------------------------------------------------------------------------------------------
def test_blocked_and_overdue_bills_and_credit_holds_reach_the_worklist():
    from scp.tower.worklist import collect
    x = received()
    x, _ = act(x, "enter_invoice", "", on=JAN, lines=[{"order": "PO-00001-10", "qty": 100, "price": 11}])
    x, _ = act(x, "enter_invoice", "", on=date(2025, 11, 1), lines=[{"order": "PO-00001-20", "qty": 30}])
    items = {r.code: r for r in collect(x, None, None, None)}
    assert items["INVOICE_BLOCKED"].category == "payables" and "SI-00001" in items["INVOICE_BLOCKED"].message
    assert items["PAYABLE_OVERDUE"].order_id == "SI-00002" and "was due 2025-12-01" in items["PAYABLE_OVERDUE"].message
    y, _ = act(x, "release_invoice", "SI-00001")
    assert "INVOICE_BLOCKED" not in {r.code for r in collect(y, None, None, None)}


def test_goods_sent_back_are_credited_at_the_price_they_were_invoiced_at():
    x = received(b=100, c=0)
    x, _ = act(x, "enter_invoice", "", on=JAN, lines=[{"order": "PO-00001-10", "qty": 100, "price": 10.5}])
    x, _ = act(x, "release_invoice", "SI-00001")
    x, _ = act(x, "return_goods", "", lines=[{"id": "PO-00001-10", "qty": 10}], on=JAN, stock_type="unrestricted")
    x, rep = act(x, "enter_invoice", "", on=JAN, return_id="RS-00001")
    assert x.supplier_invoices[1].lines[0].price == 10.5 and x.supplier_invoices[1].total == pytest.approx(115.5)


# ---- PR #14 audit regressions -------------------------------------------------------------------------------
def test_invoice_quantity_match_totals_repeated_order_lines_until_all_goods_arrive():
    d = ordered()
    d["receipts"][0]["qty"] = 200
    x, _ = act(ds(d), "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    x, _ = act(x, "enter_invoice", lines=[{"order": "PO-00001-10", "qty": 100},
                                        {"order": "PO-00001-10", "qty": 100}])
    inv = x.supplier_invoices[0]
    assert inv.blocks == ["quantity: PO-00001-10 bills 200; 100 received and not yet invoiced"]
    with pytest.raises(PurchasingError, match="blocked for payment"):
        act(x, "pay_invoice", inv.id)
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 50}], on=JAN)
    assert still_blocked(x, inv) == ["quantity: PO-00001-10 bills 200; 150 received and not yet invoiced"]
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 50}], on=JAN)
    assert still_blocked(x, inv) == []
    x, _ = act(x, "pay_invoice", inv.id)
    assert x.supplier_invoices[0].open == 0


def test_duplicate_invoice_lines_within_received_quantity_are_allowed_through_the_api():
    x = received(b=100, c=0)
    r = client.post("/api/purchasing/act", json={"dataset": x.model_dump(mode="json"), "action": "enter_invoice",
        "lines": [{"order": "PO-00001-10", "qty": 60}, {"order": "PO-00001-10", "qty": 40}]})
    assert r.status_code == 200, r.text
    y = ds(r.json()["dataset"])
    assert not y.supplier_invoices[0].blocks
    assert y.supplier_invoices[0].net == 1000
    r = client.post("/api/purchasing/act", json={"dataset": x.model_dump(mode="json"), "action": "enter_invoice",
        "lines": [{"order": "PO-00001-10", "qty": 100}, {"order": "PO-00001-10", "qty": 100}]})
    assert r.status_code == 200, r.text
    r = client.post("/api/purchasing/act", json={"dataset": r.json()["dataset"], "action": "pay_invoice", "po": "SI-00001"})
    assert r.status_code == 409 and "blocked for payment" in r.json()["detail"]


@pytest.mark.parametrize(("agreement_currency", "source_currency", "matches"), [("USD", "EUR", False), (None, "INR", True)])
def test_scheduling_agreements_only_take_lines_in_their_currency(agreement_currency, source_currency, matches):
    d = base(horizon=42)
    d["settings"].update(currency="INR", fx_rates={"USD": 80, "EUR": 90})
    lp(d, "P", "B").update(on_hand=0, lot_sizing={"policy": "L4L"})
    d["demand"] = [demand("P", "B", "2026-01-14", 10)]
    d["purchasing_sources"][0].update(currency=agreement_currency, price=10, priority=2)
    d["purchasing_sources"].append({**d["purchasing_sources"][0], "id": "PIR-B-ALT", "currency": source_currency,
                                     "price": 5, "priority": 1})
    x, _ = create_agreement(ds(d), "S", "P", "B", target_qty=100)
    plan = run_mrp(x)
    req = requisitions(x, plan)[0]
    assert req.source_id == "PIR-B-ALT"
    assert req.agreement == ("SA-00001" if matches else None)
    y, rep = create_purchase_orders(x, plan, [{"id": req.id}])
    receipt = next(r for r in y.receipts if r.id == rep.lines[req.id])
    header = y.purchase_order_by_id[receipt.po]
    assert receipt.po == ("SA-00001" if matches else "PO-00001")
    assert (header.currency or y.settings.currency) == source_currency
    assert receipt.price == 5
    # Explicitly choosing the original source still takes the matching agreement.
    z, rep = create_purchase_orders(x, plan, [{"id": req.id, "source_id": "PIR-B"}])
    assert next(r for r in z.receipts if r.id == rep.lines[req.id]).po == "SA-00001"


@pytest.mark.parametrize(("on", "open_now", "stock_now"), [(JAN, 50, 70), (date(2026, 1, 6), 40, 80)])
def test_credit_return_after_partial_roll_preserves_supply_before_and_after_the_next_roll(on, open_now, stock_now):
    x, _ = roll_forward(received(b=50, c=0), date(2026, 1, 6))
    d = x.model_dump(mode="json")
    d["demand"] = [demand("P", "B", "2026-01-20", 120)]
    x, _ = act(ds(d), "return_goods", lines=[{"id": "PO-00001-10", "qty": 10}], on=on, stock_type="unrestricted")
    r = next(r for r in x.receipts if r.id == "PO-00001-10")
    assert r.ordered_qty == 90 and r.qty == open_now
    assert lp_on_hand(x, "B") == stock_now
    assert not [o for o in run_mrp(x).orders if o.product == "B"]
    y, _ = roll_forward(x, date(2026, 1, 7))
    r = next(r for r in y.receipts if r.id == "PO-00001-10")
    assert r.qty == 50 and lp_on_hand(y, "B") == 70
    assert not [o for o in run_mrp(y).orders if o.product == "B"]


@pytest.mark.parametrize("batch_managed", [False, True])
def test_serialised_returns_select_available_serials_across_lots_without_reusing_them(batch_managed):
    from scp.actuals.documents import _serials_here
    d = ordered()
    d["products"][1].update(serial_numbers=True, batches=batch_managed)
    lp(d, "P", "B")["on_hand"] = 0
    x = ds(d)
    for qty, batch in [(60, "LOT-1"), (40, "LOT-2")]:
        x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": qty,
                   **({"batch": batch} if batch_managed else {})}], on=JAN)
    x, rep = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 70}], on=JAN, stock_type="unrestricted")
    first = [sn for m in x.movements if m.id in rep.movements for sn in m.serials]
    assert len(first) == len(set(first)) == 70
    x, rep = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 10}], on=JAN, stock_type="unrestricted")
    second = [sn for m in x.movements if m.id in rep.movements for sn in m.serials]
    assert len(second) == 10 and not set(first) & set(second)
    assert len(_serials_here(x.movements, ("P", "B"))) == 20
    with pytest.raises(PurchasingError, match="whole units"):
        act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 0.5}], on=JAN, stock_type="unrestricted")


@pytest.mark.parametrize("under_tolerance", [0.0, 0.25])
def test_replacement_return_reopens_final_short_receipt_without_reviving_cancelled_supply(under_tolerance):
    d = ordered()
    d["vendors"][0]["under_delivery_tolerance"] = under_tolerance
    x, _ = act(ds(d), "receive", "PO-00001",
               lines=[{"id": "PO-00001-10", "qty": 75, "final": not under_tolerance}], on=JAN)
    original = next(m for m in x.movements if m.reference == "PO-00001-10")
    assert original.final
    x, _ = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 25}], on=JAN,
               stock_type="unrestricted", replace=True)
    y, _ = roll_forward(x, date(2026, 1, 6))
    r = next(r for r in y.receipts if r.id == "PO-00001-10")
    assert r.ordered_qty == 100 and r.target_qty == 75 and r.qty == r.expected_qty == 25
    assert payables_view(y).returns[0].status == "replacement due"
    assert next(p for p in purchase_orders(y) if p.id == "PO-00001").lines[0].open == 25
    from scp.actuals.stock import open_orders
    assert next(o for o in open_orders(y, y.settings.planning_start) if o.id == r.id).open == 25
    assert next(m for m in y.movements if m.id == original.id).final  # retain the original journal
    # A second return adds only its own replacement; the first one's target is retained.
    y, _ = act(y, "return_goods", lines=[{"id": "PO-00001-10", "qty": 10}], on=JAN,
               stock_type="unrestricted", replace=True)
    r = next(r for r in y.receipts if r.id == "PO-00001-10")
    assert r.target_qty == 75 and r.qty == r.expected_qty == 35
    y, _ = act(y, "receive", "PO-00001", lines=[{"id": "PO-00001-10"}], on=date(2026, 1, 6))
    assert y.movements[-1].qty == 35
    y, _ = roll_forward(y, date(2026, 1, 7))
    assert not any(r.id == "PO-00001-10" for r in y.receipts)
    closed = next(c for c in y.closed_orders if c.id == "PO-00001-10")
    assert closed.ordered_qty == 100 and closed.delivered_qty == 75
    assert all(r.status == "replaced" for r in payables_view(y).returns)


def test_replacement_return_uses_confirmations_and_can_be_credited_or_finished_short_later():
    x = ds(ordered())
    x, _ = act(x, "confirm", "PO-00001", lines=[{"id": "PO-00001-10", "parts": [
        {"date": "2026-01-05", "qty": 50}, {"date": "2026-01-06", "qty": 50}]}])
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 75, "final": True}], on=JAN)
    x, _ = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 25}], on=JAN,
               stock_type="unrestricted", replace=True)
    x, _ = roll_forward(x, date(2026, 1, 6))
    r = next(r for r in x.receipts if r.id == "PO-00001-10")
    assert r.expected_parts() == [(date(2026, 1, 6), 25)]
    # Returning another ten for credit cancels those ten, without cancelling the replacements.
    credited, _ = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 10}], on=JAN,
                      stock_type="unrestricted")
    r = next(r for r in credited.receipts if r.id == "PO-00001-10")
    assert r.ordered_qty == 90 and r.target_qty == 65 and r.expected_qty == 25
    # A later final receipt is still allowed to finish short explicitly.
    finished, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 10, "final": True}],
                     on=date(2026, 1, 6))
    finished, _ = roll_forward(finished, date(2026, 1, 7))
    assert not any(r.id == "PO-00001-10" for r in finished.receipts)


def test_reversed_replacement_return_does_not_override_the_original_final_delivery():
    from scp.actuals.documents import reverse
    x, _ = act(ds(ordered()), "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 75, "final": True}], on=JAN)
    x, rep = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 25}], on=JAN,
                 stock_type="unrestricted", replace=True)
    x, _ = reverse(x, rep.movements[0], on=JAN)
    x, _ = roll_forward(x, date(2026, 1, 6))
    assert not any(r.id == "PO-00001-10" for r in x.receipts)
    assert next(c for c in x.closed_orders if c.id == "PO-00001-10").delivered_qty == 75


def test_replacement_of_a_full_delivery_is_not_closed_by_the_short_delivery_tolerance():
    d = ordered()
    d["vendors"][0]["under_delivery_tolerance"] = 0.25
    x, _ = act(ds(d), "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    assert not x.movements[-1].final
    x, _ = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 25}], on=JAN,
               stock_type="unrestricted", replace=True)
    x, _ = roll_forward(x, date(2026, 1, 6))
    r = next(r for r in x.receipts if r.id == "PO-00001-10")
    assert r.qty == r.expected_qty == 25
    assert payables_view(x).returns[0].status == "replacement due"


def test_another_return_after_a_later_final_receipt_keeps_its_new_completion_target():
    x = received(b=50, c=0)
    x, _ = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 10}], on=JAN,
               stock_type="unrestricted", replace=True)
    x, _ = roll_forward(x, date(2026, 1, 6))
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 35, "final": True}],
               on=date(2026, 1, 6))
    x, _ = act(x, "return_goods", lines=[{"id": "PO-00001-10", "qty": 10}], on=date(2026, 1, 6),
               stock_type="unrestricted", replace=True)
    x, _ = roll_forward(x, date(2026, 1, 7))
    r = next(r for r in x.receipts if r.id == "PO-00001-10")
    assert r.ordered_qty == 100 and r.target_qty == 75 and r.qty == r.expected_qty == 10
