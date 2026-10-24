"""Enterprise 7.2: the supplier's side of a purchase order on Kaveri, against hand-worked figures.

Kaveri buys enamelled copper wire from Hindalco copper (Silvassa) (PIR-CU, INR 905 a kg, 890 from 2,000 kg) on a lane
of 2 days, and lets the supplier deliver up to 10 % over the order. The order: 2,000 kg wanted on Mon 12 Oct 2026, sent on Mon 28 Sep.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import pytest

from scp import portal
from scp.portal import ubl
from scp.purchasing import approve, create_one_off_po, received, send
from scp.validate import validate

from .factory import load_example

D = date
DUE = D(2026, 10, 12)


@pytest.fixture(scope="module")
def base():
    return load_example("kitchenware_network")


@pytest.fixture()
def sent(base):
    ds, rep = create_one_off_po(base, "PIR-CU", 2000, due_date=DUE)
    assert rep.ok, rep
    po = rep.created[0].id
    for who in ("buyer", "head of buying", "director"):       # INR 18.1 lakh: every release level
        if not ds.purchase_order_by_id[po].approved:
            ds, _ = approve(ds, po, who, D(2026, 9, 28))
    ds, _ = send(ds, po, D(2026, 9, 28))
    line = next(r.id for r in ds.receipts if r.po == po)
    return ds, po, line


def _r(ds, lid):
    return next(r for r in ds.receipts if r.id == lid)


def _parts(ds, lid):
    return [(c.date, c.qty) for c in _r(ds, lid).confirmations] or [(_r(ds, lid).confirmed_date,
                                                                       _r(ds, lid).confirmed_qty)]


def test_the_supplier_sees_only_their_sent_orders(base, sent):
    ds, po, line = sent
    v = portal.view(ds, "SUP-COPPER")
    assert [x.order for x in v.lines] == [line]
    x = v.lines[0]
    assert (x.po, x.ordered, x.open, x.price, x.due_date, x.status, x.unit) == (po, 2000, 2000, 890, DUE, "to confirm",
                                                                                 "KG")
    # nobody else's lines, and not an order that has not gone out
    assert portal.view(ds, "SUP-STAMP").lines == []
    unsent, rep = create_one_off_po(base, "PIR-CU", 500, due_date=DUE)
    assert portal.view(unsent, "SUP-COPPER").lines == []
    with pytest.raises(portal.PortalError, match="not an open line"):
        portal.respond(ds, "SUP-STAMP", [{"order": line}])


def test_confirmed_in_two_deliveries_is_what_planning_expects(sent):
    ds, po, line = sent
    ds, rep = portal.respond(ds, "SUP-COPPER", [{"order": line, "parts": [{"date": "2026-10-09", "qty": 1200},
                                                                           {"date": "2026-10-16", "qty": 800}]}],
                             "SC/OC/3381")
    r = _r(ds, line)
    assert (r.confirmed_qty, r.confirmed_date) == (2000, D(2026, 10, 16))
    assert r.expected_parts() == [(D(2026, 10, 9), 1200), (D(2026, 10, 16), 800)]
    assert ds.purchase_order_by_id[po].vendor_reference == "SC/OC/3381"
    assert portal.view(ds, "SUP-COPPER").lines[0].status == "changed"
    # as asked: the whole quantity on the date wanted
    ds2, _ = portal.respond(sent[0], "SUP-COPPER", [{"order": line}])
    assert (_r(ds2, line).confirmed_qty, _r(ds2, line).confirmed_date) == (2000, DUE)
    assert portal.view(ds2, "SUP-COPPER").lines[0].status == "confirmed"


def test_a_dispatch_moves_its_goods_to_the_arrival_and_keeps_the_rest(sent):
    ds, po, line = sent
    ds, _ = portal.respond(ds, "SUP-COPPER", [{"order": line, "parts": [{"date": "2026-10-09", "qty": 1200},
                                                                         {"date": "2026-10-16", "qty": 800}]}])
    # shipped Sat 10 Oct on a 2-day lane: arrives Mon 12 Oct; the 1,200 confirmed for the 9th come then
    a, rep = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 1200, "batch": "CU-7781"}],
                             shipped_on=D(2026, 10, 10), reference="LR 40417")
    assert rep.id == "ASN-00001"
    n = a.shipping_notices[0]
    assert (n.arrives_on, n.reference, n.source, n.lines[0].batch) == (D(2026, 10, 12), "LR 40417", "entered", "CU-7781")
    assert _parts(a, line) == [(D(2026, 10, 12), 1200), (D(2026, 10, 16), 800)]
    assert "arriving Mon 12 Oct" in rep.message
    assert portal.view(a, "SUP-COPPER").lines[0].on_the_way == 1200
    assert portal.view(a, "SUP-COPPER").lines[0].status == "on the way"
    # shipped on time (Wed 7th, arriving Fri 9th): the confirmation does not move
    b, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 1200}], shipped_on=D(2026, 10, 7))
    assert _parts(b, line) == [(D(2026, 10, 9), 1200), (D(2026, 10, 16), 800)]
    # no quantity: what is confirmed and not on the way yet
    c, _ = portal.dispatch(a, "SUP-COPPER", [{"order": line}], shipped_on=D(2026, 10, 14))
    assert c.shipping_notices[1].lines[0].qty == 800
    assert _parts(c, line) == [(D(2026, 10, 12), 1200), (D(2026, 10, 16), 800)]
    with pytest.raises(portal.PortalError, match="nothing is left to send"):
        portal.dispatch(c, "SUP-COPPER", [{"order": line}], shipped_on=D(2026, 10, 14))


def test_a_lorry_counts_against_the_earliest_delivery_confirmed(sent):
    ds, po, line = sent
    ds, _ = portal.respond(ds, "SUP-COPPER", [{"order": line, "parts": [{"date": "2026-10-09", "qty": 1200},
                                                                         {"date": "2026-10-16", "qty": 800}]}])
    # 800 shipped Wed 14th, arriving Fri 16th: the first delivery is 800 late, 400 of it still expected on the 9th
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 800}], shipped_on=D(2026, 10, 14))
    assert _parts(ds, line) == [(D(2026, 10, 9), 400), (D(2026, 10, 16), 1600)]
    first = ds
    # a second lorry, the 400, arriving Mon 19th: the first notice keeps its 16th, the 9th is empty
    ds, _ = portal.dispatch(first, "SUP-COPPER", [{"order": line, "qty": 400}], shipped_on=D(2026, 10, 17))
    assert _parts(ds, line) == [(D(2026, 10, 16), 1600), (D(2026, 10, 19), 400)]
    # or 100 arriving Sun 11th: from the 400 of the 9th, not from the first lorry's 16th
    ds, _ = portal.dispatch(first, "SUP-COPPER", [{"order": line, "qty": 100}], shipped_on=D(2026, 10, 9))
    assert _parts(ds, line) == [(D(2026, 10, 9), 300), (D(2026, 10, 11), 100), (D(2026, 10, 16), 1600)]
    # the first lorry will not come: its 800 are expected on the last date again, the 400 still on the 9th
    ds, _ = portal.cancel(first, "ASN-00001")
    assert _parts(ds, line) == [(D(2026, 10, 9), 400), (D(2026, 10, 16), 1600)]


def test_what_the_line_received_before_a_roll_counts_against_its_first_delivery(sent):
    ds, po, line = sent
    ds, _ = portal.respond(ds, "SUP-COPPER", [{"order": line, "parts": [{"date": "2026-10-09", "qty": 1200},
                                                                         {"date": "2026-10-16", "qty": 800}]}])
    # as after a roll past a receipt of 1,200: the line keeps 800 open of the 2,000 ordered
    ds = ds.model_copy(update={"receipts": [r.model_copy(update={"qty": 800.0, "ordered_qty": 2000.0})
                                            if r.id == line else r for r in ds.receipts]})
    assert _r(ds, line).expected_parts() == [(D(2026, 10, 16), 800)]
    # 500 arriving Wed 14th: 1,200 + 500 on the 14th as confirmation lines, 300 on the 16th
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 500}], shipped_on=D(2026, 10, 12))
    assert _parts(ds, line) == [(D(2026, 10, 14), 1700), (D(2026, 10, 16), 300)]
    assert _r(ds, line).expected_parts() == [(D(2026, 10, 14), 500), (D(2026, 10, 16), 300)]


def test_more_than_ordered_within_the_tolerance_and_not_beyond(sent):
    ds, po, line = sent
    ds, _ = portal.respond(ds, "SUP-COPPER", [{"order": line, "parts": [{"date": "2026-10-09", "qty": 1200},
                                                                         {"date": "2026-10-16", "qty": 800}]}])
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 1200}], shipped_on=D(2026, 10, 10))
    # 900 more on Mon 12th, arriving Wed 14th: 2,100 in all, inside 2,000 × 1.10 = 2,200
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 900}], shipped_on=D(2026, 10, 12))
    assert _parts(ds, line) == [(D(2026, 10, 12), 1200), (D(2026, 10, 14), 900)]
    assert _r(ds, line).confirmed_qty == 2100
    # planning still counts no more than the 2,000 open
    assert sum(q for _d, q in _r(ds, line).expected_parts()) == 2000
    with pytest.raises(portal.PortalError, match="more than the order allows"):
        portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 200}], shipped_on=D(2026, 10, 12))


def test_received_against_the_notice_with_its_batch_then_the_other_cancelled(sent):
    ds, po, line = sent
    ds, _ = portal.respond(ds, "SUP-COPPER", [{"order": line}])
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 1200, "batch": "CU-7781"}],
                            shipped_on=D(2026, 10, 10), reference="LR 40417")
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 800}], shipped_on=D(2026, 10, 12))
    assert _parts(ds, line) == [(D(2026, 10, 12), 1200), (D(2026, 10, 14), 800)]
    before = sum(m.signed for m in ds.movements if m.product == "RM-CU-WIRE" and m.location == "PLT-PUNE")
    ds, rep = portal.receive(ds, "ASN-00001", D(2026, 10, 12))
    assert received(ds)[line] == 1200
    got = [m for m in ds.movements if m.product == "RM-CU-WIRE" and m.location == "PLT-PUNE"]
    assert sum(m.signed for m in got) - before == 1200
    assert (got[-1].reference, got[-1].counterparty, got[-1].batch) == (line, "SUP-COPPER", None)   # wire: no batches
    assert "LR 40417" in got[-1].note
    assert ds.shipping_notices[0].received_on == D(2026, 10, 12)
    assert portal.view(ds, "SUP-COPPER").lines[0].on_the_way == 800
    with pytest.raises(portal.PortalError, match="received already"):
        portal.receive(ds, "ASN-00001")
    # the second lorry will not come: its 800 are expected again on the line's last date, the 12th it was wanted
    ds, rep = portal.cancel(ds, "ASN-00002")
    r = _r(ds, line)
    # the line counts its receipts when the plan moves past them: 1,200 posted + 800 still to come, all on the 12th
    assert r.expected_parts() == [(DUE, 2000)]
    assert r.confirmed_qty == 2000
    assert portal.view(ds, "SUP-COPPER").lines[0].open == 800
    assert "expected again on Mon 12 Oct" in rep.message
    assert portal.view(ds, "SUP-COPPER").lines[0].on_the_way == 0


def test_received_short_closes_the_notice_and_leaves_the_rest_open(sent):
    ds, po, line = sent
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 1200}], shipped_on=D(2026, 10, 10))
    ds, _ = portal.receive(ds, "ASN-00001", D(2026, 10, 12), [{"order": line, "qty": 1150}])
    assert received(ds)[line] == 1150
    assert portal.view(ds, "SUP-COPPER").lines[0].open == 850
    with pytest.raises(portal.PortalError, match="no shipping notice ASN-00009"):
        portal.receive(ds, "ASN-00009")
    other, _ = portal.dispatch(sent[0], "SUP-COPPER", [{"order": line, "qty": 1200}], shipped_on=D(2026, 10, 10))
    with pytest.raises(portal.PortalError, match="PO-X#1 is not on ASN-00001"):
        portal.receive(other, "ASN-00001", lines=[{"order": "PO-X#1", "qty": 5}])


# ------------------------------------------------------------------------------------------------ UBL
NS = {"cbc": ubl.CBC, "cac": ubl.CAC}


def test_the_order_goes_out_as_a_ubl_order(sent):
    ds, po, line = sent
    x = ET.fromstring(ubl.order_xml(ds, po))
    assert x.tag == "{urn:oasis:names:specification:ubl:schema:xsd:Order-2}Order"
    assert x.findtext("cbc:ID", namespaces=NS) == po
    assert x.findtext("cbc:IssueDate", namespaces=NS) == "2026-09-28"
    assert x.findtext("cbc:DocumentCurrencyCode", namespaces=NS) == "INR"
    assert x.findtext("cac:SellerSupplierParty/cac:Party/cac:PartyName/cbc:Name", namespaces=NS) == "Hindalco copper (Silvassa)"
    assert x.findtext("cac:BuyerCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", namespaces=NS) \
        == "27AAJCK4821M1Z3"
    li = x.find("cac:OrderLine/cac:LineItem", NS)
    assert li.findtext("cbc:ID", namespaces=NS) == line
    q = li.find("cbc:Quantity", NS)
    assert (q.text, q.get("unitCode")) == ("2000", "KGM")
    assert li.findtext("cac:Price/cbc:PriceAmount", namespaces=NS) == "890"
    assert li.findtext("cac:Delivery/cac:RequestedDeliveryPeriod/cbc:EndDate", namespaces=NS) == "2026-10-12"
    assert li.findtext("cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode", namespaces=NS) == "85441110"
    # 2,000 × 890
    assert x.findtext("cac:AnticipatedMonetaryTotal/cbc:PayableAmount", namespaces=NS) == "1780000.00"


def _response(po: str, lines: str, code: str = "CA") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OrderResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:OrderResponse-2"
  xmlns:cbc="{ubl.CBC}" xmlns:cac="{ubl.CAC}">
  <cbc:ID>SC/OR/118</cbc:ID><cbc:IssueDate>2026-09-29</cbc:IssueDate>
  <cbc:OrderResponseCode>{code}</cbc:OrderResponseCode>
  <cac:OrderReference><cbc:ID>{po}</cbc:ID></cac:OrderReference>
  {lines}
</OrderResponse>"""


def _rline(line: str, status: str, qty: str = "", end: str = "") -> str:
    return (f"<cac:OrderLine><cac:LineItem><cbc:ID>1</cbc:ID><cbc:LineStatusCode>{status}</cbc:LineStatusCode>"
            + (f'<cbc:Quantity unitCode="KGM">{qty}</cbc:Quantity>' if qty else "")
            + (f"<cac:Delivery><cac:PromisedDeliveryPeriod><cbc:EndDate>{end}</cbc:EndDate>"
               "</cac:PromisedDeliveryPeriod></cac:Delivery>" if end else "")
            + f"</cac:LineItem><cac:OrderLineReference><cbc:LineID>{line}</cbc:LineID></cac:OrderLineReference>"
              "</cac:OrderLine>")


def test_an_order_response_changes_the_confirmation(sent):
    ds, po, line = sent
    ds, rep = ubl.apply(ds, "order_response", _response(po, _rline(line, "3", "1500", "2026-10-14")))
    r = _r(ds, line)
    assert (r.confirmed_qty, r.confirmed_date) == (1500, D(2026, 10, 14))
    assert ds.purchase_order_by_id[po].vendor_reference == "SC/OR/118"
    # rejected: nothing confirmed
    d2, _ = ubl.apply(sent[0], "order_response", _response(po, _rline(line, "7"), "CA"))
    assert _r(d2, line).confirmed_qty == 0
    # accepted as a whole, no lines: as ordered
    d3, _ = ubl.apply(sent[0], "order_response", _response(po, "", "AP"))
    assert (_r(d3, line).confirmed_qty, _r(d3, line).confirmed_date) == (2000, DUE)
    assert ubl.kind_of(_response(po, "", "AP")) == "order_response"


def _despatch(po: str, line: str, qty: str = "1200", lot: str = "CU-7781") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<DespatchAdvice xmlns="urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2"
  xmlns:cbc="{ubl.CBC}" xmlns:cac="{ubl.CAC}">
  <cbc:ID>SC/DA/9021</cbc:ID><cbc:IssueDate>2026-10-07</cbc:IssueDate><cbc:Note>Lorry MH04 KT 3310</cbc:Note>
  <cac:OrderReference><cbc:ID>{po}</cbc:ID></cac:OrderReference>
  <cac:Shipment><cbc:ID>1</cbc:ID><cac:Delivery>
    <cac:EstimatedDeliveryPeriod><cbc:EndDate>2026-10-09</cbc:EndDate></cac:EstimatedDeliveryPeriod>
    <cac:Despatch><cbc:ActualDespatchDate>2026-10-07</cbc:ActualDespatchDate></cac:Despatch>
  </cac:Delivery></cac:Shipment>
  <cac:DespatchLine><cbc:ID>1</cbc:ID><cbc:DeliveredQuantity unitCode="KGM">{qty}</cbc:DeliveredQuantity>
    <cac:OrderLineReference><cbc:LineID>{line}</cbc:LineID></cac:OrderLineReference>
    <cac:Item><cbc:Name>Enamelled copper wire</cbc:Name><cac:ItemInstance><cac:LotIdentification>
      <cbc:LotNumberID>{lot}</cbc:LotNumberID><cbc:ExpiryDate>2028-10-01</cbc:ExpiryDate>
    </cac:LotIdentification></cac:ItemInstance></cac:Item>
  </cac:DespatchLine>
</DespatchAdvice>"""


def test_a_despatch_advice_becomes_a_shipping_notice(sent):
    ds, po, line = sent
    text = _despatch(po, line)
    assert ubl.kind_of(text) == "despatch_advice"
    ds, rep = ubl.apply(ds, "despatch_advice", text)
    n = ds.shipping_notices[0]
    assert (n.id, n.source, n.reference, n.shipped_on, n.arrives_on, n.note) == (
        "ASN-00001", "message", "SC/DA/9021", D(2026, 10, 7), D(2026, 10, 9), "Lorry MH04 KT 3310")
    assert (n.lines[0].qty, n.lines[0].batch, n.lines[0].expires_on) == (1200, "CU-7781", D(2028, 10, 1))
    # 1,200 arrive on the 9th; the other 800 keep the date wanted
    assert _parts(ds, line) == [(D(2026, 10, 9), 1200), (DUE, 800)]


def test_messages_are_read_strictly(sent):
    ds, po, line = sent
    bomb = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
            + _despatch(po, line).split("?>", 1)[1])
    with pytest.raises(portal.PortalError, match="document type declaration"):
        ubl.apply(ds, "despatch_advice", bomb)
    with pytest.raises(portal.PortalError, match="expected a UBL DespatchAdvice, got OrderResponse"):
        ubl.apply(ds, "despatch_advice", _response(po, ""))
    with pytest.raises(portal.PortalError, match="not readable XML"):
        ubl.apply(ds, "despatch_advice", "<DespatchAdvice")
    with pytest.raises(portal.PortalError, match="larger than"):
        ubl.apply(ds, "despatch_advice", " " * (ubl.MAX_BYTES + 1))
    with pytest.raises(portal.PortalError, match="which is not ours"):
        ubl.apply(ds, "order_response", _response("PO-NOPE", ""))
    with pytest.raises(portal.PortalError, match="which is not open"):
        ubl.apply(ds, "despatch_advice", _despatch(po, "PO-NOPE#1"))
    with pytest.raises(portal.PortalError, match=f"names order line {line} of PO-NOPE, which is not open"):
        ubl.apply(ds, "despatch_advice", _despatch("PO-NOPE", line))
    with pytest.raises(portal.PortalError, match="not a number"):
        ubl.apply(ds, "despatch_advice", _despatch(po, line, qty="lots"))
    assert ds.shipping_notices == []


def test_a_notice_that_no_longer_fits_its_orders_is_a_warning(sent):
    ds, po, line = sent
    ds, _ = portal.dispatch(ds, "SUP-COPPER", [{"order": line, "qty": 1200}], shipped_on=D(2026, 10, 10))
    assert not [i for i in validate(ds) if i.code == "OUTSIDE_MISFIT"]
    gone = ds.model_copy(update={"receipts": [r for r in ds.receipts if r.id != line]})
    found = [i for i in validate(gone) if i.code == "OUTSIDE_MISFIT"]
    assert [(i.object_id, i.severity) for i in found] == [("ASN-00001", "warning")]
    assert f"ships {line}, not an open order line of SUP-COPPER" in found[0].message
    # received: nothing more to say
    done, _ = portal.receive(ds, "ASN-00001", D(2026, 10, 12))
    assert not [i for i in validate(done.model_copy(update={"receipts": [r for r in done.receipts if r.id != line]})
                                    ) if i.code == "OUTSIDE_MISFIT"]
