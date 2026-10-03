"""Phase M: order to cash. Orders of several lines priced by scales and discounts, a credit check, quotations,
deliveries picked, packed, shipped and signed for, invoices with payment terms and a cash discount, returns and credit
notes."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals import PostingError, post, roll_forward
from scp.api.app import app
from scp.model import StockType
from scp.sales import (
    remind,
    SalesError, act, cancel_invoice, create_deliveries, create_invoices, create_order, create_quotation,
    create_return, credit_return, exposure, issue, lose_quotation, pack, pay, pick, proof, receive_return,
    release_credit, sales_view, to_bill, to_deliver, win_quotation,
)
from scp.validate import validate

from .factory import base, ds

client = TestClient(app)


def shop(limit: float | None = None) -> dict:
    """Plant P holds 100 A and 50 D and ships to customer K in a day. K pays 2 % within 10 days, net 30, with 10 % tax;
    A is 90 to K, 80 from 20 a line, and K has 5 % off everything."""
    d = base()
    d["locations"].append({"id": "K", "name": "Kumar Stores", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["products"][0].update(name="Tin of white", price=100)
    d["products"].append({"id": "D", "name": "Drum of thinner", "type": "FG", "price": 20})
    d["location_products"][0]["on_hand"] = 100
    d["location_products"].append({"location": "P", "product": "D", "on_hand": 50})
    d["purchasing_sources"].append({"id": "PIR-D", "supplier": "S", "product": "D", "location": "P", "price": 12,
                                    "lead_time_days": 5})
    d["customer_prices"] = [{"customer": "K", "product": "A", "price": 90, "scales": [{"from_qty": 20, "price": 80}]}]
    d["payment_terms"] = [{"id": "2-10-30", "name": "2 % 10 days, net 30", "net_days": 30, "discount_days": 10,
                           "discount": 0.02}]
    d["customers"] = [{"customer": "K", "payment_terms": "2-10-30", "discount": 0.05, "credit_limit": limit,
                       "tax_rate": 0.1}]
    return d


LINES = [{"product": "A", "qty": 25, "date": "2026-01-08"}, {"product": "D", "qty": 10, "date": "2026-01-08"}]


def taken(limit: float | None = None):
    return create_order(ds(shop(limit)), "K", LINES, customer_ref="PO-77")


# ---- orders of several lines, priced ---------------------------------------------------------------------------
def test_an_order_of_two_lines_is_priced_by_scale_and_discount_and_promised_line_by_line():
    x, rep = taken()
    h = x.sales_orders[0]
    assert h.id == "SO-00001" and h.customer == "K" and h.customer_ref == "PO-77" and not h.credit_block
    a, d = (next(r for r in x.demand if r.id == f"SO-00001/{n}") for n in (10, 20))
    assert a.order == d.order == "SO-00001"
    assert a.price == pytest.approx(80 * 0.95) and a.discount == pytest.approx(0.05)       # the 20+ scale, less 5 %
    assert d.price == pytest.approx(20 * 0.95)                                             # the product's price
    assert sum(c.qty for c in x.confirmations if c.order == a.id) == pytest.approx(25)
    assert sum(c.qty for c in x.confirmations if c.order == d.id) == pytest.approx(10)
    assert "SO-00001 taken for Kumar Stores: 2 lines, INR 2,299.00 with tax" in rep.message   # (1900 + 190) × 1.1
    v = sales_view(x).orders[0]
    assert v.status == "open" and [ln.id for ln in v.lines] == ["SO-00001/10", "SO-00001/20"]
    assert v.lines[0].list_price == pytest.approx(80) and v.value == pytest.approx(2090)
    assert "2 % within 10 days, net 30 days" == v.payment_terms
    assert not validate(x) or all(i.severity != "error" for i in validate(x))
    # below the scale a line pays the base price
    y, _ = create_order(x, "K", [{"product": "A", "qty": 5, "date": "2026-01-09"}])
    assert next(r for r in y.demand if r.id == "SO-00002/10").price == pytest.approx(90 * 0.95)


def test_an_order_beyond_the_credit_limit_is_promised_but_not_delivered_until_released():
    x, rep = taken(limit=1000)
    assert rep.credit_block and x.sales_orders[0].credit_block
    assert "Blocked for delivery: Kumar Stores would owe INR 2,299.00 against a credit limit of INR 1,000.00" in rep.message
    assert sum(c.qty for c in x.confirmations) == pytest.approx(35)          # still promised
    due = to_deliver(x)
    assert {t.order for t in due} == {"SO-00001/10", "SO-00001/20"} and all(t.credit_block for t in due)
    with pytest.raises(SalesError, match="nothing is due"):
        create_deliveries(x)
    with pytest.raises(SalesError, match="blocked over the credit limit"):
        create_deliveries(x, [{"order": "SO-00001/10"}])
    with pytest.raises(PostingError, match="blocked over the customer's credit limit"):
        post(x, "deliver", order="SO-00001/10", qty=1)
    assert sales_view(x).orders[0].status == "credit block"
    y, _ = release_credit(x, "SO-00001", by="Asha")
    assert not y.sales_orders[0].credit_block and "Released by Asha" in y.sales_orders[0].credit_note
    y, rep = create_deliveries(y)
    assert rep.documents == ["DL-00001"] and len(y.deliveries[0].lines) == 2


# ---- quotations -------------------------------------------------------------------------------------------------
def test_a_quotation_promises_nothing_and_once_won_is_an_order_at_the_quoted_prices():
    x, rep = create_quotation(ds(shop()), "K", [{"product": "A", "qty": 10, "date": "2026-01-12", "price": 70}])
    q = x.quotations[0]
    assert q.id == "QT-00001" and q.valid_to == date(2026, 2, 4) and q.lines[0].list_price == pytest.approx(90)
    assert not x.demand and not x.confirmations
    assert "valid until Wed 4 Feb" in rep.message
    y, rep = win_quotation(x, "QT-00001")
    assert y.quotations[0].status == "won" and y.quotations[0].order == "SO-00001"
    assert y.sales_orders[0].quotation == "QT-00001"
    assert next(r for r in y.demand if r.order == "SO-00001").price == pytest.approx(70)
    with pytest.raises(SalesError, match="already won"):
        win_quotation(y, "QT-00001")
    late, _ = create_quotation(ds(shop()), "K", [{"product": "D", "qty": 2}], valid_to=date(2026, 1, 6))
    with pytest.raises(SalesError, match="ran out"):
        win_quotation(late, "QT-00001", on=date(2026, 1, 7))
    lost, _ = lose_quotation(late, "QT-00001", "price")
    assert lost.quotations[0].status == "lost" and lost.quotations[0].lost_reason == "price"
    assert sales_view(late, date(2026, 1, 7)).quotations[0].status == "expired"


# ---- deliveries, invoices, payments -----------------------------------------------------------------------------
def test_a_delivery_is_picked_packed_shipped_and_signed_for_then_invoiced_and_paid_with_the_cash_discount():
    x, _ = taken()
    x, rep = create_deliveries(x)
    dl = x.deliveries[0]
    assert dl.id == "DL-00001" and dl.ship_from == "P" and dl.status == "to pick"
    assert [(ln.order, ln.qty) for ln in dl.lines] == [("SO-00001/10", 25), ("SO-00001/20", 10)]
    assert not to_deliver(x)                                                   # on a delivery now
    x, rep = pick(x, "DL-00001", [{"order": "SO-00001/20", "picked": 8}])
    assert "SO-00001/20 8 of 10" in rep.message
    x, _ = pick(x, "DL-00001", [{"order": "SO-00001/10", "picked": 25}])
    x, rep = pack(x, "DL-00001", 3, 410.5)
    assert x.deliveries[0].status == "packed" and "3 packages, 410.5 kg" in rep.message
    x, rep = issue(x, "DL-00001")
    moves = [m for m in x.movements if m.type.value == "sale"]
    assert {(m.reference, m.qty) for m in moves} == {("SO-00001/10", 25), ("SO-00001/20", 8)}
    assert len({m.doc for m in moves}) == 1 and x.deliveries[0].movements == [m.id for m in moves]
    assert x.deliveries[0].status == "shipped" and "It can be invoiced now" in rep.message
    with pytest.raises(SalesError, match="already been shipped"):
        pick(x, "DL-00001")
    # the 2 not picked are still to deliver
    assert [(t.order, t.qty) for t in to_deliver(x)] == [("SO-00001/20", 2)]
    x, rep = proof(x, "DL-00001", date(2026, 1, 6), by="R. Kumar", lines=[{"order": "SO-00001/10", "received": 24}])
    assert x.deliveries[0].status == "delivered" and "Signed for less: 1 Tin of white on SO-00001/10" in rep.message
    assert sales_view(x).deliveries[0].short == pytest.approx(1)
    # billing
    assert [(b.order, b.qty, b.value) for b in to_bill(x)] == [("SO-00001/10", 25, 1900), ("SO-00001/20", 8, 152)]
    x, rep = create_invoices(x, on=date(2026, 1, 7))
    inv = x.invoices[0]
    assert inv.id == "INV-00001" and inv.net == pytest.approx(2052) and inv.tax == pytest.approx(205.2)
    assert inv.total == pytest.approx(2257.2) and inv.due_date == date(2026, 2, 6) and inv.discount_date == date(2026, 1, 17)
    assert not to_bill(x) and sales_view(x).deliveries[0].invoiced
    o, u, r = exposure(x, "K")
    assert u == 0 and r == pytest.approx(2257.2) and o == pytest.approx(2 * 19 * 1.1)
    x, rep = pay(x, "INV-00001", on=date(2026, 1, 15), reference="UTR123")
    assert x.invoices[0].open == 0 and x.invoices[0].payments[0].amount == pytest.approx(2212.06)
    assert "cash discount INR 45.14" in rep.message and "settled" in rep.message
    assert sales_view(x).invoices[0].status == "paid"
    with pytest.raises(SalesError, match="already settled"):
        pay(x, "INV-00001")


def test_tax_per_product_and_its_cgst_sgst_or_igst_split_by_place_of_supply():
    d = shop()
    d["customers"][0]["tax_rate"] = None                         # K has no rate of its own
    d["sales"] = {"tax_rate": 0.18, "tax_split": "gst"}
    d["products"][-1]["tax_rate"] = 0.12                         # the thinner is taxed at 12 %, the paint at 18 %
    d["settings"]["company_tax_id"] = "27AAACM1234A1Z5"          # Maharashtra
    d["locations"][-1]["tax_id"] = "27AAFCK9876B1Z2"             # Kumar Stores, also Maharashtra
    x, _ = create_order(ds(d), "K", LINES)
    assert exposure(x, "K")[0] == pytest.approx(1900 * 1.18 + 190 * 1.12)
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")
    y, _ = create_invoices(x, on=date(2026, 1, 7))
    inv = y.invoices[0]
    assert inv.tax_split == "cgst_sgst" and [ln.tax_rate for ln in inv.lines] == [None, 0.12]
    assert inv.tax_parts == [("CGST", 0.06, 190, 11.4), ("SGST", 0.06, 190, 11.4),
                             ("CGST", 0.09, 1900, 171), ("SGST", 0.09, 1900, 171)]
    assert inv.tax == pytest.approx(364.8) and inv.total == pytest.approx(2454.8)
    assert [p.name for p in sales_view(y).invoices[0].tax_parts] == ["CGST", "SGST", "CGST", "SGST"]
    # a customer in another state (Karnataka, by region) pays IGST
    x2 = x.model_copy(update={"locations": [lo.model_copy(update={"region": "KA"}) if lo.id == "K" else lo
                                            for lo in x.locations]})
    x2 = x2.model_copy(update={"settings": x2.settings.model_copy(update={"company_region": "MH"})})
    inv = create_invoices(x2, on=date(2026, 1, 7))[0].invoices[0]
    assert inv.tax_split == "igst" and inv.tax_parts == [("IGST", 0.12, 190, 22.8), ("IGST", 0.18, 1900, 342)]
    # the customer's own rate (here an export at 0 %) goes before the product's
    x3 = x.model_copy(update={"customers": [c.model_copy(update={"tax_rate": 0.0}) for c in x.customers]})
    inv = create_invoices(x3, on=date(2026, 1, 7))[0].invoices[0]
    assert inv.tax == 0 and inv.tax_parts == [] and all(ln.tax_rate is None for ln in inv.lines)


def test_on_time_delivery_counts_the_day_the_customer_signed_when_a_proof_of_delivery_is_recorded():
    x, _ = taken()
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")                                  # shipped on 5 January, a day in transit
    plain, _ = roll_forward(x, date(2026, 1, 12))
    by = {c.id: c for c in plain.closed_orders}
    assert by["SO-00001/10"].last_delivery == date(2026, 1, 6)   # no proof of delivery: issue plus transit
    signed, _ = proof(x, "DL-00001", date(2026, 1, 9), by="R. Kumar")
    rolled, _ = roll_forward(signed, date(2026, 1, 12))
    c = next(c for c in rolled.closed_orders if c.id == "SO-00001/10")
    assert c.first_delivery == c.last_delivery == date(2026, 1, 9) and c.due_date == date(2026, 1, 8)  # a day late
    # signed for after the order closed: the closed order takes the day it was signed for
    later, _ = proof(plain, "DL-00001", date(2026, 1, 7), by="R. Kumar")
    again, _ = roll_forward(later, date(2026, 1, 19))
    assert next(c for c in again.closed_orders if c.id == "SO-00001/10").last_delivery == date(2026, 1, 7)


def test_a_late_part_payment_takes_no_discount_and_the_rest_goes_overdue():
    x, _ = taken()
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")
    x, _ = create_invoices(x)
    total = x.invoices[0].total
    x, rep = pay(x, "INV-00001", 1000, on=date(2026, 1, 20))
    assert x.invoices[0].open == pytest.approx(total - 1000) and "still open" in rep.message
    v = sales_view(x, date(2026, 2, 10)).invoices[0]
    assert v.status == "overdue" and v.days_overdue == 6 and sales_view(x, date(2026, 2, 10)).customers[0].overdue > 0
    with pytest.raises(SalesError, match="has payments"):
        cancel_invoice(x, "INV-00001")


def test_an_overdue_invoice_reaches_payment_reminders_by_the_days_it_is_overdue():
    x, _ = taken()
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")
    x, _ = create_invoices(x)
    due = x.invoices[0].due_date
    assert x.sales.reminder_days == [7, 21, 35]
    assert sales_view(x, date(2026, 2, 10)).invoices[0].reminder_due == 0          # 6 days overdue: none yet
    v = sales_view(x, date(2026, 2, 12))
    assert (v.invoices[0].reminder_due, v.customers[0].reminder_due) == (1, 1)
    x, rep = remind(x, "K", on=date(2026, 2, 12))
    assert rep.message.startswith("Payment reminder 1 to ") and "INV-00001 (8 days overdue, " in rep.message
    assert (x.invoices[0].reminder_level, x.invoices[0].reminded_on) == (1, date(2026, 2, 12))
    assert sales_view(x, date(2026, 2, 12)).invoices[0].reminder_due == 0
    with pytest.raises(SalesError, match="is due a payment reminder"):
        remind(x, "K", on=date(2026, 2, 12))
    # long overdue: straight to the last reminder reached
    assert (date(2026, 3, 15) - due).days >= 35
    x, rep = remind(x, "K", on=date(2026, 3, 15))
    assert rep.message.startswith("Payment reminder 3 to ") and x.invoices[0].reminder_level == 3
    # paid, nothing is due; a company without reminder days has none
    paid, _ = pay(x, "INV-00001", x.invoices[0].open, on=date(2026, 3, 16))
    assert sales_view(paid, date(2026, 6, 1)).invoices[0].reminder_due == 0
    none = x.model_copy(update={"sales": x.sales.model_copy(update={"reminder_days": []}), "invoices": [
        x.invoices[0].model_copy(update={"reminder_level": 0})]})
    assert sales_view(none, date(2026, 6, 1)).invoices[0].reminder_due == 0


def test_reminder_days_are_kept_in_order_once_each_and_within_a_year():
    d = shop()
    d["sales"] = {"reminder_days": [21, 7, 7]}
    assert ds(d).sales.reminder_days == [7, 21]
    d["sales"] = {"reminder_days": [0]}
    with pytest.raises(Exception, match="1 to 365 days"):
        ds(d)


def test_a_cancelled_invoice_frees_its_goods_to_be_billed_again():
    x, _ = taken()
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")
    x, _ = create_invoices(x)
    x, rep = cancel_invoice(x, "INV-00001", "wrong address")
    assert x.invoices[0].cancelled and len(to_bill(x)) == 2
    x, _ = create_invoices(x)
    assert x.invoices[1].id == "INV-00002" and x.invoices[1].net == pytest.approx(x.invoices[0].net)


def test_goods_shipped_before_a_roll_are_billed_at_the_order_price_after_the_line_has_closed():
    x, _ = taken()
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001", date(2026, 1, 5))
    x, _ = roll_forward(x, date(2026, 1, 12))
    assert not [d for d in x.demand if d.kind == "sales_order"]               # both lines closed
    assert sales_view(x).orders[0].status == "delivered"
    x, _ = create_invoices(x)
    assert x.invoices[0].net == pytest.approx(1900 + 190)
    assert sales_view(x).orders[0].status == "invoiced"


# ---- returns and credit notes -------------------------------------------------------------------------------------
def test_a_return_comes_back_into_quality_inspection_and_a_credit_note_pays_it_back():
    x, _ = taken()
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")
    x, _ = create_invoices(x)
    with pytest.raises(SalesError, match="25 of SO-00001/10 were shipped"):
        create_return(x, "K", "A", 30, order="SO-00001/10")
    x, rep = create_return(x, "K", "A", 3, order="SO-00001/10", reason="dented")
    r = x.returns[0]
    assert r.id == "RET-00001" and r.location == "P" and r.price == pytest.approx(76) and r.status == "expected"
    x, rep = receive_return(x, "RET-00001", on=date(2026, 1, 9))
    m = next(m for m in x.movements if m.reference == "RET-00001")
    assert m.type.value == "receipt" and m.stock_type is StockType.QUALITY and m.counterparty == "K" and m.qty == 3
    assert "into quality inspection" in rep.message
    before = sum(exposure(x, "K"))
    x, rep = credit_return(x, "RET-00001")
    cn = x.invoices[-1]
    assert cn.id == "CN-00001" and cn.kind == "credit_note" and cn.reference == "INV-00001"
    assert cn.total == pytest.approx(3 * 76 * 1.1) and x.returns[0].status == "credited"
    assert sum(exposure(x, "K")) == pytest.approx(before - cn.total)
    assert sales_view(x).orders[0].lines[0].returned == pytest.approx(3)
    with pytest.raises(SalesError, match="already been credited"):
        credit_return(x, "RET-00001")


# ---- orders as a whole ------------------------------------------------------------------------------------------
def test_an_order_is_cancelled_line_by_line_and_a_blocked_customer_cannot_order():
    x, _ = taken()
    x, rep = act(x, "cancel_order", id="SO-00001", reason="customer changed their mind")
    assert not [d for d in x.demand if d.kind == "sales_order"] and sales_view(x).orders[0].status == "cancelled"
    d = shop()
    d["customers"][0].update(blocked=True, block_reason="unpaid since March")
    with pytest.raises(SalesError, match="blocked for sales \\(unpaid since March\\)"):
        create_order(ds(d), "K", LINES)


def test_lines_added_to_an_order_follow_its_numbering():
    x, _ = taken()
    x, rep = act(x, "add_lines", id="SO-00001", lines=[{"product": "D", "qty": 4, "date": "2026-01-09"}])
    assert [r.id for r in x.demand if r.order == "SO-00001"] == ["SO-00001/10", "SO-00001/20", "SO-00001/30"]
    assert len(x.sales_orders) == 1 and "SO-00001: added" in rep.message
    assert sum(c.qty for c in x.confirmations if c.order == "SO-00001/30") == pytest.approx(4)


def test_the_documents_name_what_exists():
    d = shop()
    d["customers"][0]["payment_terms"] = "NOPE"
    d["demand"] = [{"id": "SO-9/10", "order": "SO-9", "location": "K", "product": "A", "date": "2026-01-08", "qty": 1,
                    "kind": "sales_order"}]
    codes = {(i.code, i.field) for i in validate(ds(d))}
    assert ("REF_UNKNOWN", "payment_terms") in codes and ("REF_UNKNOWN", "order") in codes


def test_the_api_runs_order_to_cash():
    x = ds(shop()).model_dump(mode="json")
    r = client.post("/api/sales/act", json={"dataset": x, "action": "create_order", "customer": "K", "lines": LINES})
    assert r.status_code == 200, r.text
    x = r.json()["dataset"]
    assert r.json()["report"]["documents"] == ["SO-00001"]
    r = client.post("/api/sales/act", json={"dataset": x, "action": "create_deliveries"})
    x = r.json()["dataset"]
    r = client.post("/api/sales/act", json={"dataset": x, "action": "issue", "id": "DL-00001"})
    x = r.json()["dataset"]
    r = client.post("/api/sales", json=x)
    assert r.status_code == 200 and r.json()["to_bill"][0]["order"] == "SO-00001/10"
    r = client.post("/api/sales/act", json={"dataset": x, "action": "pay", "id": "INV-1"})
    assert r.status_code == 409 and "no invoice" in r.json()["detail"]


def test_credit_holds_and_overdue_invoices_reach_the_worklist():
    from scp.tower.worklist import collect
    x, _ = taken(limit=1000)
    items = {r.code: r for r in collect(x, None, None, None)}
    assert items["CREDIT_BLOCK"].category == "receivables" and items["CREDIT_BLOCK"].order_id == "SO-00001"
    y, _ = release_credit(x, "SO-00001")
    assert "CREDIT_BLOCK" not in {r.code for r in collect(y, None, None, None)}
