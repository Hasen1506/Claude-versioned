"""Enterprise 7.3: several companies in one network. A transfer to another company is sold to it at the transfer price
and billed on a GST invoice; each company's books value its stock at what it paid, the group's at what the goods cost
the group. Every figure is worked out by hand in the test from the movements, not read back from the engine."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp import intercompany as ic
from scp.actuals.transfer_price import crossing, price, rule
from scp.actuals.valuation import standards, value_stock
from scp.api.app import app
from scp.model import Dataset
from scp.purchasing import act
from scp.validate import validate

from .factory import base, ds

client = TestClient(app)
JAN = date(2026, 1, 5)
OURS = "27AAACK1234A1Z5"                   # Maharashtra
THEIRS = "06AAACT5678B1Z2"                 # Haryana


def group(control: str = "moving_average", rules: list[dict] | None = None, w_entity: str | None = "TR",
          w_tax: str = "", qty: float = 50) -> dict:
    """Plant P of the company (GSTIN in Maharashtra) with 30 B at the start (standard 8) and PO-00001 for 100 B at 10;
    W a depot of Kaveri Trading (GSTIN in Haryana) with TR-1, a transfer of ``qty`` B from P. B carries 18 % GST."""
    d = base(horizon=42)
    d["settings"].update({"company_name": "Kaveri Kitchenware", "company_tax_id": OURS})
    d["sales"] = {"tax_rate": 0.18, "tax_split": "gst"}
    d["execution"] = {"price_control": control}
    d["products"][1]["standard_cost"] = 8
    d["products"][1]["hsn"] = "7323"
    d["entities"] = [{"id": "TR", "name": "Kaveri Trading", "tax_id": THEIRS, "invoice_prefix": "KT/"}]
    d["transfer_prices"] = rules if rules is not None else [
        {"id": "TP-B", "buyer": "TR", "product": "B", "method": "fixed", "price": 12}]
    d["locations"].append({"id": "W", "type": "dc", "entity": w_entity, "tax_id": w_tax})
    d["lanes"] = [{"id": "L-PW", "origin": "P", "destination": "W", "modes": [{"mode": "truck_ftl", "transit_days": 1}]}]
    d["location_products"].append({"location": "W", "product": "B"})
    d["purchase_orders"] = [{"id": "PO-00001", "supplier": "S", "location": "P", "order_date": "2026-01-02",
                             "sent_on": "2026-01-02"}]
    d["receipts"] = [
        {"id": "PO-00001-10", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
         "due_date": "2026-01-05", "source": "PIR-B", "po": "PO-00001", "price": 10},
        {"id": "TR-1", "kind": "transfer", "location": "W", "product": "B", "qty": qty, "due_date": "2026-01-07",
         "source": "L-PW"},
    ]
    return d


def add(x: Dataset, *moves: dict) -> Dataset:
    j = x.model_dump(mode="json")
    return Dataset.model_validate({**j, "movements": [*j["movements"], *moves]})


def ship(mid: str, day: str, q: float, **kw) -> dict:
    return {"id": mid, "date": day, "type": "transfer_out", "location": "P", "product": "B", "qty": q,
            "reference": "TR-1", "counterparty": "W", **kw}


def arrive(mid: str, day: str, q: float) -> dict:
    return {"id": mid, "date": day, "type": "receipt", "location": "W", "product": "B", "qty": q, "reference": "TR-1"}


def sell(mid: str, day: str, q: float) -> dict:
    return {"id": mid, "date": day, "type": "sale", "location": "W", "product": "B", "qty": q, "reference": "SO-1"}


def received(d: dict) -> Dataset:
    x = ds(d)
    x, _ = act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=JAN)
    return x


def row(v, loc: str, prod: str = "B"):
    return next(r for r in v.rows if r.location == loc and r.product == prod)


def test_a_transfer_to_another_company_comes_in_at_the_transfer_price_and_the_group_keeps_its_cost():
    x = received(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50), sell("GM-S1", "2026-01-07", 20))
    day = date(2026, 1, 7)
    # P: 30 at 8 + 100 at 10 = 1,240 for 130; 50 leave at 1,240/130 each
    avg = 1240 / 130
    own, grp = value_stock(x, day), value_stock(x, day, books="group")
    assert own.books == "entity" and grp.books == "group"
    # Kaveri Trading paid 12: 50 in at 600, 20 sold at 12, 30 left worth 360
    assert row(own, "W").entity == "TR" and row(own, "W").value == pytest.approx(360, abs=0.01)
    assert own.cost_of_sales == pytest.approx(240, abs=0.01)
    # the group: they came in at what they were worth at P
    assert row(grp, "W").value == pytest.approx(30 * avg, abs=0.01)
    assert grp.cost_of_sales == pytest.approx(20 * avg, abs=0.01)
    # P is the same in both books
    assert row(own, "P").value == row(grp, "P").value == pytest.approx(1240 - 50 * avg, abs=0.01)
    assert own.intercompany_sales == 600 and own.intercompany_cost == pytest.approx(50 * avg, abs=0.01)
    assert grp.intercompany_sales == 0

    v = ic.view(x, day)
    c = v.consolidation
    margin = 600 - 50 * avg                                # 123.08
    unreal = 30 * (12 - avg)                               # what is still at W: 73.85
    assert c.sales == 600 and c.margin == pytest.approx(margin, abs=0.01)
    assert c.unrealised == pytest.approx(unreal, abs=0.01)
    assert c.stock_entities - c.stock_group == pytest.approx(unreal, abs=0.01)
    # what was sold on carried its share of the margin out of the group: the two costs of sales differ by it
    assert c.realised == pytest.approx(20 * (12 - avg), abs=0.01)
    assert c.cost_of_sales_entities - c.cost_of_sales_group == pytest.approx(c.realised, abs=0.01)
    ours, theirs = v.entities
    assert (ours.id, ours.name, theirs.id) == ("", "Kaveri Kitchenware", "TR")
    assert ours.sales == 600 and ours.margin == pytest.approx(margin, abs=0.01) and theirs.purchases == 600
    assert ours.places == ["P"] and theirs.places == ["W"]
    assert theirs.stock == pytest.approx(360, abs=0.01)
    (s,) = v.shipments
    assert (s.movement, s.seller, s.buyer, s.crossing, s.qty, s.price, s.due_qty) == ("GM-T1", "", "TR", "entity", 50,
                                                                                       12, 50)
    assert s.basis == "fixed (TP-B)" and s.cost == pytest.approx(avg, abs=1e-4)
    assert v.due == 1 and v.due_value == 600


def test_goods_on_the_way_at_go_live_come_in_at_the_transfer_price_and_are_not_billed_here():
    # N316: TR-1 left P before go-live (billed by the old system); only its arrival is in the journal
    x = received(group())
    x = add(x, {**arrive("GM-T2", "2026-01-07", 50), "counterparty": "P"})
    std_w = standards(x)[("W", "B")]
    own, grp = value_stock(x, date(2026, 1, 7)), value_stock(x, date(2026, 1, 7), books="group")
    assert row(own, "W").value == pytest.approx(600, abs=0.01)
    assert row(grp, "W").value == pytest.approx(50 * std_w, abs=0.01)
    v = ic.view(x, date(2026, 1, 7))
    assert v.due == 0 and v.shipments == [] and v.orders == []        # received in full: no longer open
    c = v.consolidation
    assert c.margin == 0 and c.margin_before == pytest.approx(50 * (12 - std_w), abs=0.01)
    assert c.unrealised == pytest.approx(50 * (12 - std_w), abs=0.01) and c.realised == 0
    assert any("TR-1 came from another company with no shipment" in n for n in v.notes)
    # the company's financial year to date: Indian books from April
    assert (v.period_start, v.period_end) == (date(2025, 4, 1), date(2026, 1, 7))


def test_billing_makes_a_gst_invoice_from_the_sellers_series_and_a_credit_note_for_what_came_back():
    x = received(group(qty=60))
    x = add(x, ship("GM-T1", "2026-01-06", 50))
    x, r = ic.bill(x, date(2026, 1, 7))
    (inv,) = x.intercompany_invoices
    # the company's own series (it has no prefix of its own); Maharashtra to Haryana: IGST
    assert (inv.id, inv.kind, inv.seller, inv.buyer, inv.split) == ("IC/0001", "invoice", "", "TR", "igst")
    assert inv.net == 600 and inv.tax == 108
    assert "IC/0001" in r.message and "INR 600.00" in r.message
    with pytest.raises(ic.IntercompanyError, match="nothing is due"):
        ic.bill(x, date(2026, 1, 7))
    # 10 more go on the 8th and are billed; then that shipment is taken back
    x = add(x, ship("GM-T3", "2026-01-08", 10))
    x, _ = ic.bill(x, date(2026, 1, 8))
    assert [i.id for i in x.intercompany_invoices] == ["IC/0001", "IC/0002"]
    x = add(x, ship("GM-T3R", "2026-01-09", 10, reversal_of="GM-T3"))
    v = ic.view(x, date(2026, 1, 9))
    t3 = next(s for s in v.shipments if s.movement == "GM-T3")
    assert (t3.qty, t3.billed_qty, t3.due_qty) == (0, 10, -10)
    x, _ = ic.bill(x, date(2026, 1, 9))
    cn = x.intercompany_invoices[-1]
    assert (cn.id, cn.kind, cn.net, cn.tax) == ("IC/0003", "credit_note", 120, 21.6)
    assert ic.view(x, date(2026, 1, 9)).due == 0
    # the invoice it credits cannot go first
    with pytest.raises(ic.IntercompanyError, match="IC/0003 credits"):
        ic.cancel(x, "IC/0002")
    x, _ = ic.cancel(x, "IC/0003")
    assert ic.view(x, date(2026, 1, 9)).due == 1
    row_ = next(i for i in ic.view(x, date(2026, 1, 9)).invoices if i.id == "IC/0001")
    assert (row_.igst, row_.cgst, row_.total, row_.seller_gstin, row_.buyer_gstin) == (108, 0, 708, OURS, THEIRS)
    assert row_.place_of_supply == "06 Haryana" and row_.lines[0].hsn == "7323" and row_.lines[0].unit == "NOS"


def test_more_shipments_than_an_invoice_holds_go_on_further_invoices():
    # N317: 501 shipments between one pair of places
    x = received(group(qty=501))
    x = add(x, *[ship(f"GM-T{i:03d}", "2026-01-06", 0.1) for i in range(501)])
    y, r = ic.bill(x, date(2026, 1, 7))
    assert r.invoices == ["IC/0001", "IC/0002"]
    assert [len(i.lines) for i in y.intercompany_invoices] == [500, 1]
    with pytest.raises(ic.IntercompanyError, match="2 documents"):
        ic.bill(x, date(2026, 1, 7), invoice_id="ONE")


def test_the_buyer_bills_from_its_own_series_and_one_state_splits_into_cgst_and_sgst():
    d = group()
    d["entities"][0]["tax_id"] = "27AAACT5678B1Z9"             # Kaveri Trading in Maharashtra too
    # W sells back to P: the trading company is the seller now
    d["receipts"].append({"id": "TR-2", "kind": "transfer", "location": "P", "product": "B", "qty": 5,
                          "due_date": "2026-01-09", "source": "L-WP"})
    d["lanes"].append({"id": "L-WP", "origin": "W", "destination": "P", "modes": [{"mode": "truck_ftl",
                                                                                   "transit_days": 1}]})
    d["transfer_prices"].append({"id": "TP-BACK", "seller": "TR", "method": "cost_plus", "markup": 0.25})
    x = received(d)
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50),
            {"id": "GM-B1", "date": "2026-01-08", "type": "transfer_out", "location": "W", "product": "B", "qty": 5,
             "reference": "TR-2", "counterparty": "P"})
    x, _ = ic.bill(x, date(2026, 1, 8))
    a, b = sorted(x.intercompany_invoices, key=lambda i: i.id)
    assert (a.id, a.seller, a.split, a.net, a.tax) == ("IC/0001", "", "cgst_sgst", 600, 108)
    # cost plus 25 % on B's standard, 8 (the round trip P → W → P leaves no network to roll costs up on): 10
    assert (b.id, b.seller, b.buyer) == ("KT/0001", "TR", "")
    assert b.lines[0].price == 10 and b.net == 50
    r = next(i for i in ic.view(x, date(2026, 1, 8)).invoices if i.id == "IC/0001")
    assert (r.cgst, r.sgst, r.igst) == (54, 54, 0)


def test_the_most_specific_rule_wins_and_the_latest_valid_among_equals():
    rules = [{"id": "R-ANY", "method": "cost_plus", "markup": 0.10},
             {"id": "R-TR", "buyer": "TR", "method": "cost_plus", "markup": 0.05},
             {"id": "R-B", "buyer": "TR", "product": "B", "method": "fixed", "price": 12},
             {"id": "R-B2", "buyer": "TR", "product": "B", "method": "fixed", "price": 13, "valid_from": "2026-01-08"},
             {"id": "R-RES", "buyer": "TR", "product": "A", "method": "resale_minus", "markup": 0.2},
             {"id": "R-TRS", "seller": "TR", "method": "cost_plus", "markup": 0.3},
             {"id": "R-C", "product": "C", "method": "fixed", "price": 7}]
    x = ds(group(rules=rules))
    assert rule(x, "", "TR", "B", date(2026, 1, 7)).id == "R-B"
    assert rule(x, "", "TR", "B", date(2026, 1, 8)).id == "R-B2"
    # a product's rule before a named buyer's or seller's, a named seller before a named buyer, either before any
    assert rule(x, "", "TR", "C", date(2026, 1, 8)).id == "R-C"
    assert rule(x, "TR", "", "C", date(2026, 1, 8)).id == "R-C"
    assert rule(x, "", "TR", "A2", date(2026, 1, 8)).id == "R-TR"
    assert rule(x, "TR", "", "B", date(2026, 1, 8)).id == "R-TRS"
    assert rule(x, "X", "", "B", date(2026, 1, 8)).id == "R-ANY"
    std = standards(x)
    assert price(x, std, "P", "W", "C", date(2026, 1, 8)) == (7, "fixed (R-C)")
    j = x.model_dump(mode="json")
    j["products"].append({"id": "A2", "type": "FG", "standard_cost": 40})
    z = Dataset.model_validate(j)
    assert price(z, standards(z), "P", "W", "A2", date(2026, 1, 8)) == (42, "cost plus 5.0% (R-TR)")
    # to the paisa (N318): a cost of 8.333 plus 5 % is 8.74965, charged and shown as 8.75
    j["products"][-1]["standard_cost"] = 8.333
    w = Dataset.model_validate(j)
    assert price(w, standards(w), "P", "W", "A2", date(2026, 1, 8))[0] == 8.75
    # A has no selling price: the resale method cannot work, so it goes at cost and says why
    each, why = price(x, std, "P", "W", "A", date(2026, 1, 8))
    assert each == pytest.approx(std[("P", "A")], abs=1e-4) and "no selling price" in why
    j = x.model_dump(mode="json")
    j["products"][0]["price"] = 100
    y = Dataset.model_validate(j)
    assert price(y, standards(y), "P", "W", "A", date(2026, 1, 8)) == (80, "selling price less 20.0% (R-RES)")


def test_without_a_rule_it_moves_at_cost_and_the_check_says_so():
    x = received(group(rules=[]))
    issues = [i for i in validate(x) if i.code == "TRANSFER_PRICE_MISSING"]
    assert [(i.object_type, i.object_id) for i in issues] == [("receipt", "TR-1")]
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    v = ic.view(x, date(2026, 1, 7))
    assert v.shipments[0].basis == "at cost: no transfer price" and v.shipments[0].price == 8
    assert any("No transfer price" in n for n in v.notes)


def test_two_registrations_of_one_company_are_billed_at_cost_and_the_books_do_not_move():
    # W is the company's own depot in Haryana: a distinct person for GST, the same books
    x = received(group(w_entity=None, w_tax=THEIRS))
    assert crossing(x, "P", "W") == "registration"
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    own, grp = value_stock(x, date(2026, 1, 7)), value_stock(x, date(2026, 1, 7), books="group")
    assert row(own, "W").value == row(grp, "W").value == pytest.approx(50 * 1240 / 130, abs=0.01)
    x, _ = ic.bill(x, date(2026, 1, 7))
    (inv,) = x.intercompany_invoices
    # at the planned unit value where it left (rule 28: the value declared between distinct persons)
    assert (inv.seller, inv.buyer, inv.split, inv.net, inv.tax) == ("", "", "igst", 400, 72)
    assert ic.view(x, date(2026, 1, 7)).consolidation.unrealised == 0


def test_a_standard_price_at_the_receiver_puts_the_margin_in_price_differences():
    x = received(group(control="standard"))
    x = add(x, ship("GM-T1", "2026-01-06", 50), arrive("GM-T2", "2026-01-07", 50))
    std_w = standards(x)[("W", "B")]
    v = ic.view(x, date(2026, 1, 7))
    c = v.consolidation
    # P ships at its standard 8; W takes 50 at 12 against its own standard: the 4 a unit goes aside
    assert c.margin == pytest.approx(50 * (12 - 8), abs=0.01)
    assert c.unrealised == pytest.approx(0, abs=0.01)
    assert c.differences_entities - c.differences_group == pytest.approx(50 * (12 - std_w), abs=0.01)
    assert any("price differences" in n for n in v.notes)


def test_a_shipment_taken_back_leaves_nothing_on_the_way_and_no_sale():
    x = received(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50), ship("GM-T1R", "2026-01-06", 50, reversal_of="GM-T1"))
    own = value_stock(x, date(2026, 1, 7))
    assert own.in_transit == 0 and own.intercompany_sales == 0 and own.intercompany_cost == pytest.approx(0, abs=0.01)
    assert row(own, "P").value == pytest.approx(1240, abs=0.01)
    assert ic.view(x, date(2026, 1, 7)).shipments[0].due_qty == 0


def test_in_transit_between_companies_is_at_the_transfer_price_in_its_books():
    x = received(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50))
    assert value_stock(x, date(2026, 1, 6)).in_transit == 600
    assert value_stock(x, date(2026, 1, 6), books="group").in_transit == pytest.approx(50 * 1240 / 130, abs=0.01)
    assert ic.view(x, date(2026, 1, 6)).consolidation.unrealised == pytest.approx(600 - 50 * 1240 / 130, abs=0.01)


def test_checks_name_unknown_companies_and_invoices_that_do_not_fit():
    d = group()
    d["locations"].append({"id": "X", "type": "dc", "entity": "NOPE"})
    d["locations"][1]["entity"] = "TR"                         # the supplier S
    d["intercompany_invoices"] = [{"id": "IC/0009", "date": "2026-01-07", "seller": "TR", "buyer": "", "ship_from": "P",
                                   "ship_to": "W", "lines": [{"movement": "GM-GONE", "order": "TR-1", "product": "B",
                                                              "qty": 1, "price": 12}]}]
    issues = validate(ds(d))
    got = {(i.code, i.object_type, i.object_id) for i in issues}
    assert ("REF_UNKNOWN", "location", "X") in got
    assert ("INTERCOMPANY_MISFIT", "location", "S") in got
    msgs = [i.message for i in issues if i.code == "INTERCOMPANY_MISFIT" and i.object_id == "IC/0009"]
    assert any("GM-GONE" in m for m in msgs) and any("seller" in m for m in msgs)


def test_the_api_bills_and_cancels_and_reads_the_view():
    x = received(group())
    x = add(x, ship("GM-T1", "2026-01-06", 50))
    body = x.model_dump(mode="json")
    v = client.post("/api/intercompany?as_of=2026-01-07", json=body).json()
    assert v["due"] == 1 and v["entities"][1]["name"] == "Kaveri Trading"
    r = client.post("/api/intercompany/act", json={"dataset": body, "action": "bill", "date": "2026-01-07",
                                                     "id": "KK/IC/1"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["invoices"] == ["KK/IC/1"]
    nxt = out["dataset"] or {**body, **out["patch"]}
    r = client.post("/api/intercompany/act", json={"dataset": nxt, "action": "cancel", "id": "KK/IC/1"})
    assert r.status_code == 200 and "on the billing due list again" in r.json()["message"]
    r = client.post("/api/intercompany/act", json={"dataset": body, "action": "cancel"})
    assert r.status_code == 409 and "which invoice" in r.json()["detail"]
    g = client.post("/api/valuation?as_of=2026-01-07&books=group", json=body).json()
    assert g["books"] == "group" and g["in_transit"] == pytest.approx(50 * 1240 / 130, abs=0.01)
