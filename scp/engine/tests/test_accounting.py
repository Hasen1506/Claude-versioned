"""Enterprise 7.4: the double-entry journal made from movements, invoices and payments, and its Tally file. Every
balance is worked out by hand in the test from the documents (the purchase at 10, the invoice at 10.50, the sale at
20, the transfer price 12, …), not read back from the engine."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp import accounting as acct
from scp import intercompany as ic
from scp.actuals.valuation import value_stock
from scp.api.app import app
from scp.model import Dataset

from .test_intercompany import add, arrive, group, received, ship

client = TestClient(app)


def books(d: dict, **moves) -> Dataset:
    d["location_products"][0]["on_hand"] = 0          # no A: its rolled-up standard is not worked out here
    d["locations"].append({"id": "K", "type": "customer", "name": "Kumar Stores"})
    return received(d)


def tb(x: Dataset, company: str = "", end: date | None = None) -> dict[str, float]:
    v = acct.view(x, period_end=end)
    return {b.account: b.balance for b in v.balances if b.company == company and abs(b.balance) >= 0.005}


def checks(x: Dataset, end: date | None = None) -> list:
    return [c for c in acct.view(x, period_end=end).checks if not c.ok]


def supplier_invoice(price: float = 10.5, tax: float = 189.0, payments: list | None = None, qty: float = 100,
                     **kw) -> dict:
    return {"id": "SI-1", "supplier": "S", "reference": "S/77", "date": "2026-01-06", "due_date": "2026-02-05",
            "lines": [{"order": "PO-00001-10", "product": "B", "qty": qty, "price": price}], "tax": tax,
            "payments": payments or [], **kw}


def with_docs(x: Dataset, **docs) -> Dataset:
    j = x.model_dump(mode="json")
    for k, v in docs.items():
        j[k] = [*j.get(k, []), *v]
    return Dataset.model_validate(j)


def sale(mid: str = "GM-S1", q: float = 40, day: str = "2026-01-08") -> dict:
    return {"id": mid, "date": day, "type": "sale", "location": "P", "product": "B", "qty": q, "reference": "SO-1"}


def customer_invoice(payments: list | None = None) -> dict:
    return {"id": "INV-1", "customer": "K", "date": "2026-01-08", "due_date": "2026-02-07", "tax_rate": 0.18,
            "tax_split": "cgst_sgst", "payments": payments or [],
            "lines": [{"order": "SO-1", "product": "B", "qty": 40, "price": 20, "movements": ["GM-S1"]}]}


# ---------------------------------------------------------------------------------------------- one company
def test_buy_to_pay_and_order_to_cash_moving_average():
    """30 B opening at 8 (240); 100 received at 10 (GR/IR 1,000); invoiced at 10.50 with 189 tax: the 50 more goes to
    the stock (all 130 still there, average 1,290 / 130); paid 1,239. 40 sold at the average: cost 40 × 1,290 / 130 =
    396.92; billed at 20 with 18 % GST as CGST and SGST (72 + 72), total 944, received."""
    x = books(group(w_entity=None))
    after_receipt = tb(x)
    assert after_receipt["STOCK"] == 1240.0 and after_receipt["GRIR"] == -1000.0 and after_receipt["OPENING"] == -240.0
    x = with_docs(x, supplier_invoices=[supplier_invoice(payments=[{"date": "2026-01-07", "amount": 1239}])])
    x = add(x, sale())
    x = with_docs(x, invoices=[customer_invoice(payments=[{"date": "2026-01-09", "amount": 944}])])
    t = tb(x)
    cogs = round(40 * 1290 / 130, 2)
    assert cogs == 396.92
    assert t["STOCK"] == round(1290 - cogs, 2) == 893.08
    assert "GRIR" not in t and "PAYABLES" not in t and "RECEIVABLES" not in t   # all cleared
    assert t["INPUT_TAX"] == 189.0
    assert t["OUT_CGST"] == -72.0 and t["OUT_SGST"] == -72.0
    assert t["SALES"] == -800.0 and t["COGS"] == cogs
    assert t["BANK"] == 944.0 - 1239.0
    assert sum(t.values()) == pytest.approx(0, abs=0.005)
    assert not checks(x)
    co = acct.view(x).companies[0]
    assert co.profit == round(800 - cogs, 2)


def test_open_items_match_the_documents_on_the_day():
    """Before the payments: the supplier is owed 1,239 and the customer owes 944; the checks agree on each day."""
    x = books(group(w_entity=None))
    x = with_docs(x, supplier_invoices=[supplier_invoice(payments=[{"date": "2026-01-10", "amount": 1000}])])
    x = add(x, sale())
    x = with_docs(x, invoices=[customer_invoice(payments=[{"date": "2026-01-10", "amount": 500}])])
    t = tb(x, end=date(2026, 1, 9))
    assert t["PAYABLES"] == -1239.0 and t["RECEIVABLES"] == 944.0 and "BANK" not in t
    t = tb(x, end=date(2026, 1, 10))
    assert t["PAYABLES"] == -239.0 and t["RECEIVABLES"] == 444.0 and t["BANK"] == -500.0
    assert not checks(x, date(2026, 1, 9)) and not checks(x, date(2026, 1, 10))
    parties = acct.view(x).parties
    assert {(p.account, p.party_name, p.balance) for p in parties} >= {("PAYABLES", "S", -239.0),
                                                                       ("RECEIVABLES", "Kumar Stores", 444.0)}


def test_standard_price_receipt_puts_the_difference_aside():
    """At standard 8 the 100 received at 10 come in at 800; the 200 more is a price difference, GR/IR 1,000 as the
    order. The invoice at 10.50 adds 50 to price differences (the stock stays at standard)."""
    x = books(group("standard", w_entity=None))
    t = tb(x)
    assert t["STOCK"] == 240 + 800 and t["PRICE_DIFF"] == 200.0 and t["GRIR"] == -1000.0
    x = with_docs(x, supplier_invoices=[supplier_invoice()])
    t = tb(x)
    assert t["STOCK"] == 1040.0 and t["PRICE_DIFF"] == 250.0 and t["PAYABLES"] == -1239.0 and "GRIR" not in t
    assert not checks(x)


def test_invoice_before_the_goods_clears_gr_ir_at_the_invoice_price():
    """50 of the 100 invoiced before they come (at 10.50) are a GR/IR debit; the receipt then credits GR/IR at
    that price: GR/IR ends at 0 after the remaining 50 are invoiced at 10."""
    d = group(w_entity=None)
    d["location_products"][0]["on_hand"] = 0
    x = Dataset.model_validate(d)
    x = with_docs(x, supplier_invoices=[{"id": "SI-0", "supplier": "S", "date": "2026-01-04", "due_date": "2026-02-04",
                                         "lines": [{"order": "PO-00001-10", "product": "B", "qty": 50, "price": 10.5}]}])
    assert tb(x, end=date(2026, 1, 4))["GRIR"] == 525.0
    from scp.purchasing import act
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=date(2026, 1, 5))
    t = tb(x)
    assert t["GRIR"] == -500.0                           # the other 50 at the order's 10
    assert t["STOCK"] == 240 + 525 + 500
    x = with_docs(x, supplier_invoices=[{"id": "SI-2", "supplier": "S", "date": "2026-01-06",
                                         "due_date": "2026-02-06",
                                         "lines": [{"order": "PO-00001-10", "product": "B", "qty": 50, "price": 10}]}])
    t = tb(x)
    assert "GRIR" not in t and t["PAYABLES"] == -1025.0
    assert not checks(x)


def test_reversed_receipt_and_return_to_supplier_take_gr_ir_back():
    """The receipt of 100 reversed in part (20) and 10 returned to the supplier: GR/IR is what is left, 70 × 10."""
    x = books(group(w_entity=None))
    x = add(x, {"id": "GM-R1", "date": "2026-01-06", "type": "receipt", "location": "P", "product": "B", "qty": 20,
                "reversal_of": "GM-00001", "reference": "PO-00001-10"},
            {"id": "GM-R2", "date": "2026-01-06", "type": "return", "location": "P", "product": "B", "qty": 10,
             "reference": "PO-00001-10"})
    t = tb(x)
    assert t["GRIR"] == -700.0
    assert t["STOCK"] == 240 + 700
    assert not checks(x)
    # the whole 100 invoiced at 10.50 now: 70 cleared at the order's 10, 30 billed ahead of goods that are not here
    # (a GR/IR debit at the invoice's 10.50); the 35 more on the 70 goes to the stock
    x = with_docs(x, supplier_invoices=[supplier_invoice(tax=0, date="2026-01-07")])
    t = tb(x)
    assert t["GRIR"] == 30 * 10.5 and t["PAYABLES"] == -1050.0 and t["STOCK"] == 240 + 700 + 35
    assert not checks(x)


def test_production_scrap_and_count_go_to_their_accounts():
    """10 B issued to production at the average (1,240 / 130 each), 2 scrapped, 3 found in a count."""
    x = books(group(w_entity=None))
    avg = 1240 / 130
    x = add(x, {"id": "GM-I1", "date": "2026-01-06", "type": "issue", "location": "P", "product": "B", "qty": 10,
                "reference": "MO-1"},
            {"id": "GM-X1", "date": "2026-01-06", "type": "scrap", "location": "P", "product": "B", "qty": 2},
            {"id": "GM-C1", "date": "2026-01-06", "type": "adjustment", "location": "P", "product": "B", "qty": 3})
    t = tb(x)
    assert t["WIP"] == round(10 * avg, 2) == 95.38
    assert t["SCRAP"] == round(2 * avg, 2) == 19.08
    assert t["COUNT_DIFF"] == -round(3 * avg, 2) == -28.62
    assert t["STOCK"] == pytest.approx(1240 - 95.38 - 19.08 + 28.62, abs=0.011)
    assert not checks(x)


def test_customer_credit_note_and_return_take_back_sales_and_cost():
    """A customer sends 5 back and is credited 5 × 20 + 18 % = 118. The 5 come back at what the 40 left at
    (1,240 / 130 each), not at the average the supplier's later invoice made (N323)."""
    x = books(group(w_entity=None))
    x = add(x, sale())
    # the supplier's invoice at 10.50 after the sale moves the average: 50 more, 90 of the 100 still here
    x = with_docs(x, supplier_invoices=[supplier_invoice(tax=0, date="2026-01-08")])
    x = with_docs(x, invoices=[customer_invoice()],
                  returns=[{"id": "RET-1", "customer": "K", "order": "SO-1", "product": "B", "qty": 5, "price": 20,
                            "location": "P", "created_on": "2026-01-09", "received_on": "2026-01-09"}])
    x = add(x, {"id": "GM-RT", "date": "2026-01-09", "type": "receipt", "location": "P", "product": "B", "qty": 5,
                "reference": "RET-1", "counterparty": "K"})
    x = with_docs(x, invoices=[{"id": "CN-1", "kind": "credit_note", "customer": "K", "date": "2026-01-09",
                                "due_date": "2026-01-09", "tax_rate": 0.18, "tax_split": "cgst_sgst",
                                "reference": "INV-1",
                                "lines": [{"order": "SO-1", "product": "B", "qty": 5, "price": 20, "ret": "RET-1"}]}])
    t = tb(x)
    avg = 1240 / 130
    assert t["SALES"] == -(800 - 100)
    assert t["RECEIVABLES"] == 944 - 118
    assert t["OUT_CGST"] == -(72 - 9) and t["OUT_SGST"] == -(72 - 9)
    cogs = round(40 * avg, 2) - round(5 * avg, 2)
    assert cogs == pytest.approx(333.85)
    assert t["COGS"] == pytest.approx(cogs, abs=0.001)
    assert value_stock(x).cost_of_sales == pytest.approx(cogs, abs=0.001)
    assert not checks(x)


def test_drop_ship_and_job_charge_invoices():
    """A supplier's invoice for goods it shipped to our customer is cost of goods sold; a job worker's charge is
    work in progress. Neither touches stock or GR/IR."""
    x = books(group(w_entity=None))
    x = with_docs(
        x,
        third_party_orders=[{"id": "TP-0001", "customer": "K", "product": "B", "qty": 5, "date": "2026-01-10",
                             "price": 20, "supplier": "S", "cost": 11, "ordered_on": "2026-01-05",
                             "shipments": [{"date": "2026-01-07", "qty": 5}]}],
        challans=[{"id": "JW-1", "job_worker": "S", "ship_from": "P", "order": "MO-1", "sent_on": "2026-01-05",
                   "charge": 4, "lines": [{"product": "B", "qty": 6, "value": 9.54, "location": "P"}],
                   "returns": [{"date": "2026-01-07", "kind": "processed", "product": "A", "qty": 3}]}],
        supplier_invoices=[{"id": "SI-T", "supplier": "S", "date": "2026-01-07", "due_date": "2026-02-07",
                            "lines": [{"order": "TP-0001", "product": "B", "qty": 5, "price": 11}]},
                           {"id": "SI-J", "supplier": "S", "date": "2026-01-07", "due_date": "2026-02-07",
                            "lines": [{"order": "JW-1", "product": "A", "qty": 3, "price": 4}]}])
    t = tb(x)
    assert t["COGS"] == 55.0 and t["WIP"] == 12.0 and t["PAYABLES"] == -67.0
    assert t["STOCK"] == 1240.0 and t["GRIR"] == -1000.0
    assert not checks(x)


def test_supplier_credit_memo_takes_its_freight_off_the_stock():
    """A credit memo for 10 B at the order's price with 5 of freight credited: the freight comes off the stock
    (it was added on before, N321). The stock books and the journal agree."""
    x = books(group(w_entity=None))
    x = with_docs(x, supplier_invoices=[supplier_invoice(price=10, tax=0),
                                        {"id": "SI-C", "kind": "credit_memo", "supplier": "S", "date": "2026-01-07",
                                         "due_date": "2026-01-07", "delivery_costs": 5,
                                         "lines": [{"order": "PO-00001-10", "product": "B", "qty": 10, "price": 10}]}])
    assert value_stock(x).total_value == 1240 - 5
    t = tb(x)
    assert t["PAYABLES"] == -(1000 - 105)
    assert t["GRIR"] == -100.0                           # 10 credited and kept: received and not invoiced
    assert not checks(x)


def test_freight_bill_is_owed_to_the_carrier():
    x = books(group(w_entity=None))
    x = with_docs(x, carriers=[{"id": "CR-1", "name": "Shree Roadways", "rates": [{"mode": "truck_ftl", "per_shipment": 900}]}])
    j = x.model_dump(mode="json")
    j["lanes"] = [{"id": "L-PK", "origin": "P", "destination": "K", "modes": [{"mode": "truck_ftl", "transit_days": 1}]}]
    j["freight_orders"] = [{"id": "FO-1", "lane": "L-PK", "mode": "truck_ftl", "carrier": "CR-1", "ship_from": "P",
                            "ship_to": "K", "planned_on": "2026-01-06", "status": "settled", "bill": "SR/9",
                            "billed": 950, "settled_on": "2026-01-07", "deliveries": ["DL-1"]}]
    x = Dataset.model_validate(j)
    t = tb(x)
    assert t["DELIVERY"] == 950.0 and t["PAYABLES"] == -950.0
    assert ("PAYABLES", "Shree Roadways", -950.0) in {(p.account, p.party_name, p.balance)
                                                      for p in acct.view(x).parties}
    assert not checks(x)


# ---------------------------------------------------------------------------------------------- two companies
def test_intercompany_sale_in_both_books_billed_and_settled():
    """50 B to Kaveri Trading at 12 (fixed). Ours: 50 × 1,240 / 130 = 476.92 off the stock to the cost of goods sold
    to group companies; the invoice 600 + IGST 108 (Maharashtra to Haryana) owed by Trading. Trading's: 600 on the
    road against inter-company GR/IR, then in stock; the invoice clears GR/IR, 108 input tax, 708 owed to us.
    Settled: 708 from Trading's bank to ours."""
    x = books(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50))
    t_road = tb(x, "TR")
    assert t_road["TRANSIT"] == 600.0 and t_road["IC_GRIR"] == -600.0
    assert not checks(x)
    x = add(x, arrive("GM-T2", "2026-01-07", 50))
    x, _ = ic.bill(x, date(2026, 1, 7))
    ours, theirs = tb(x), tb(x, "TR")
    cost = round(50 * 1240 / 130, 2)
    assert ours["IC_COGS"] == cost == 476.92 and ours["STOCK"] == round(1240 - cost, 2)
    assert ours["IC_SALES"] == -600.0 and ours["OUT_IGST"] == -108.0 and ours["IC_RECEIVABLES"] == 708.0
    assert theirs["STOCK"] == 600.0 and "TRANSIT" not in theirs and "IC_GRIR" not in theirs
    assert theirs["INPUT_TAX"] == 108.0 and theirs["IC_PAYABLES"] == -708.0
    assert not checks(x)
    iid = x.intercompany_invoices[0].id
    x, r = ic.pay(x, iid, on=date(2026, 1, 9), reference="NEFT-1")
    assert "paid by Kaveri Trading to Kaveri Kitchenware" in r.message and "settled" in r.message
    ours, theirs = tb(x), tb(x, "TR")
    assert ours["BANK"] == 708.0 and "IC_RECEIVABLES" not in ours
    assert theirs["BANK"] == -708.0 and "IC_PAYABLES" not in theirs
    v = ic.view(x)
    assert {e.id: (e.receivable, e.payable) for e in v.entities} == {"": (0.0, 0.0), "TR": (0.0, 0.0)}
    assert not checks(x)
    with pytest.raises(ic.IntercompanyError, match="already settled"):
        ic.pay(x, iid)
    with pytest.raises(ic.IntercompanyError, match="settled in part or in full"):
        ic.cancel(x, iid)


def test_intercompany_part_payment_is_open_in_both_views():
    x = books(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    x, _ = ic.bill(x, date(2026, 1, 7))
    iid = x.intercompany_invoices[0].id
    x, r = ic.pay(x, iid, 300, on=date(2026, 1, 8))
    assert "408.00 still open" in r.message
    v = ic.view(x)
    assert {e.id: (e.receivable, e.payable) for e in v.entities} == {"": (408.0, 0.0), "TR": (0.0, 408.0)}
    assert v.invoices[0].paid == 300.0 and v.invoices[0].open == 408.0
    assert tb(x)["IC_RECEIVABLES"] == 408.0 and tb(x, "TR")["IC_PAYABLES"] == -408.0
    with pytest.raises(ic.IntercompanyError, match="only has"):
        ic.pay(x, iid, 500)


def test_reversed_transfer_receipt_is_on_the_road_again():
    """20 of the 50 received taken back: in Trading's books they are on the way again at 12 (240), as the stock books
    say (N322)."""
    x = books(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50),
            {"id": "GM-T3", "date": "2026-01-08", "type": "receipt", "location": "W", "product": "B", "qty": 20,
             "reversal_of": "GM-T2", "reference": "TR-1"})
    assert value_stock(x).in_transit == 240.0
    t = tb(x, "TR")
    assert t["TRANSIT"] == 240.0 and t["STOCK"] == 360.0
    assert not checks(x)


def test_registration_crossing_posts_only_the_tax():
    """W of the same company with its own GSTIN in Haryana: the transfer is billed at cost between registrations;
    the journal books the tax it charges itself (input against output) and nothing else."""
    x = books(group(w_entity=None, w_tax="06AAACK1234A1Z7"))
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    x, _ = ic.bill(x, date(2026, 1, 7))
    inv = x.intercompany_invoices[0]
    t = tb(x)
    assert t["INPUT_TAX"] == inv.tax and t["OUT_IGST"] == -inv.tax
    assert "IC_SALES" not in t and "IC_RECEIVABLES" not in t
    assert not checks(x)
    with pytest.raises(ic.IntercompanyError, match="registrations of one company"):
        ic.pay(x, inv.id)


# ---------------------------------------------------------------------------------------------- Tally
def _tally(x: Dataset, company: str = "") -> ET.Element:
    return ET.fromstring(acct.tally_xml(x, company))


def test_tally_file_is_balanced_with_its_ledgers():
    x = books(group(w_entity=None))
    x = with_docs(x, supplier_invoices=[supplier_invoice(payments=[{"date": "2026-01-07", "amount": 1239}])])
    x = add(x, sale())
    x = with_docs(x, invoices=[customer_invoice()])
    j = x.model_dump(mode="json")
    j["finance"]["ledgers"] = {"STOCK": "Closing Stock", "BANK": "HDFC Bank"}
    j["finance"]["tally_company"] = "Kaveri Kitchenware 2026-27"
    x = Dataset.model_validate(j)
    root = _tally(x)
    assert root.findtext(".//SVCURRENTCOMPANY") == "Kaveri Kitchenware 2026-27"
    ledgers = {e.get("NAME"): e.findtext("PARENT") for e in root.iter("LEDGER")}
    assert ledgers["Closing Stock"] == "Stock-in-Hand" and ledgers["HDFC Bank"] == "Bank Accounts"
    assert ledgers["Kumar Stores"] == "Sundry Debtors" and ledgers["S"] == "Sundry Creditors"
    vouchers = list(root.iter("VOUCHER"))
    assert {v.get("VCHTYPE") for v in vouchers} == {"Journal", "Purchase", "Payment", "Sales"}
    for v in vouchers:
        ents = v.findall("ALLLEDGERENTRIES.LIST")
        amounts = [float(e.findtext("AMOUNT")) for e in ents]
        assert sum(amounts) == pytest.approx(0, abs=0.005), v.findtext("VOUCHERNUMBER")
        for e, a in zip(ents, amounts, strict=True):
            assert (e.findtext("ISDEEMEDPOSITIVE") == "Yes") == (a < 0)        # a debit is negative in Tally
            assert e.findtext("LEDGERNAME") in ledgers
    sale_v = next(v for v in vouchers if v.findtext("VOUCHERNUMBER") == "INV-1")
    assert sale_v.findtext("DATE") == "20260108"
    got = {e.findtext("LEDGERNAME"): float(e.findtext("AMOUNT")) for e in sale_v.findall("ALLLEDGERENTRIES.LIST")}
    assert got == {"Kumar Stores": -944.0, "Sales": 800.0, "Output CGST": 72.0, "Output SGST": 72.0}


def test_tally_file_per_company():
    x = books(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    x, _ = ic.bill(x, date(2026, 1, 7))
    ours, theirs = _tally(x), _tally(x, "TR")
    assert theirs.findtext(".//SVCURRENTCOMPANY") == "Kaveri Trading"
    names = {e.findtext("LEDGERNAME") for e in theirs.iter("ALLLEDGERENTRIES.LIST")}
    assert "Kaveri Kitchenware" in names and "Inter-company goods received, not invoiced" in names
    assert "Kaveri Trading" in {e.findtext("LEDGERNAME") for e in ours.iter("ALLLEDGERENTRIES.LIST")}
    with pytest.raises(ValueError, match="no company"):
        acct.tally_xml(x, "XX")


# ---------------------------------------------------------------------------------------------- the API
def test_api_view_and_exports():
    x = books(group(w_entity=None))
    x = add(x, sale())
    x = with_docs(x, invoices=[customer_invoice()])
    body = x.model_dump(mode="json")
    r = client.post("/api/accounting", json=body)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["period_start"] == "2025-04-01" if v["currency"] == "INR" else v["period_start"] == "2026-01-01"
    assert all(c["ok"] for c in v["checks"])
    assert {a["code"] for a in v["accounts"]} == set(acct.ACCOUNTS)
    r = client.post("/api/accounting/export?format=csv", json=body)
    assert r.status_code == 200
    lines = r.json()["text"].strip().splitlines()
    assert lines[0].startswith("company,date,voucher") and any("INV-1" in ln for ln in lines)
    r = client.post("/api/accounting/export?format=tally", json=body)
    assert r.status_code == 200 and r.json()["name"].endswith(".xml")
    ET.fromstring(r.json()["text"])
    assert client.post("/api/accounting/export?format=tally&company=XX", json=body).status_code == 404


def test_api_settle_intercompany():
    x = books(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    x, _ = ic.bill(x, date(2026, 1, 7))
    iid = x.intercompany_invoices[0].id
    r = client.post("/api/intercompany/act", json={"dataset": x.model_dump(mode="json"), "action": "pay", "id": iid,
                                                   "amount": 100, "date": "2026-01-08", "reference": "UTR-5"})
    assert r.status_code == 200, r.text
    assert "608.00 still open" in r.json()["message"]


def test_cash_discounts_on_both_sides():
    """The supplier paid 1,214.22 with 2 % of 1,239 (24.78) taken off; the customer paid 925.12 with 18.88 off."""
    x = books(group(w_entity=None))
    x = with_docs(x, supplier_invoices=[supplier_invoice(
        payments=[{"date": "2026-01-07", "amount": 1214.22, "discount": 24.78}])])
    x = add(x, sale())
    x = with_docs(x, invoices=[customer_invoice(payments=[{"date": "2026-01-09", "amount": 925.12,
                                                            "discount": 18.88}])])
    t = tb(x)
    assert "PAYABLES" not in t and "RECEIVABLES" not in t and "SUSPENSE" not in t
    assert t["DISC_RECEIVED"] == -24.78 and t["DISC_ALLOWED"] == 18.88
    assert t["BANK"] == round(925.12 - 1214.22, 2)
    assert not checks(x)


def test_intercompany_within_one_state_is_cgst_and_sgst():
    """Kaveri Trading registered in Maharashtra too: 600 at 18 % is CGST 54 and SGST 54 on both sides."""
    d = group()
    d["entities"][0]["tax_id"] = "27AAACT5678B1Z9"
    x = books(d)
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    x, _ = ic.bill(x, date(2026, 1, 7))
    ours, theirs = tb(x), tb(x, "TR")
    assert ours["OUT_CGST"] == -54.0 and ours["OUT_SGST"] == -54.0 and ours["IC_RECEIVABLES"] == 708.0
    assert theirs["INPUT_TAX"] == 108.0 and theirs["IC_PAYABLES"] == -708.0
    assert "IC_GRIR" not in theirs and "SUSPENSE" not in theirs and "SUSPENSE" not in ours
    assert not checks(x)


def test_stock_value_is_the_sum_of_its_postings_to_the_paisa():
    """Odd prices (10.333…, an average of 1,240 / 130) never leave a fraction of a paisa in the value: each posting is
    rounded, the value is their sum, and the journal's stock is the stock books' to the paisa."""
    d = group(w_entity=None)
    d["receipts"][0]["price"] = 31 / 3
    x = books(d)
    x = add(x, sale("GM-S1", 7), {"id": "GM-C1", "date": "2026-01-08", "type": "adjustment", "location": "P",
                                  "product": "B", "qty": 3},
            {"id": "GM-X1", "date": "2026-01-08", "type": "scrap", "location": "P", "product": "B", "qty": 11})
    v = value_stock(x)
    for r in v.rows:
        posted = sum(e.amount for e in v.entries if e.location == r.location and e.product == r.product)
        assert r.value == pytest.approx(posted, abs=1e-9)
    assert tb(x)["STOCK"] == pytest.approx(v.total_value, abs=1e-9)
