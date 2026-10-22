"""Purchase orders and the supplier's answers as standard business messages (Enterprise 7.2): UBL 2.1 documents in
the shape the Peppol BIS Ordering and Despatch Advice profiles use.

Out: an ``Order`` for a purchase order, one ``OrderLine`` per line with our line id, so the answers can name it.
In: an ``OrderResponse`` (each line accepted, changed or rejected, with the promised date) and a ``DespatchAdvice``
(what is on the lorry, the batches and when it arrives). Both are read into the same steps as the supplier portal.

Messages come from outside, so reading is strict: no document type declarations (no entities to expand), a size
limit, and only the elements named here are looked at.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

from ..model import Dataset
from . import PortalError, PortalReport, _line, _name, dispatch, respond

CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
DOC = {"Order": "urn:oasis:names:specification:ubl:schema:xsd:Order-2",
       "OrderResponse": "urn:oasis:names:specification:ubl:schema:xsd:OrderResponse-2",
       "DespatchAdvice": "urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2"}
PROFILE = {"Order": ("urn:fdc:peppol.eu:poacc:trns:order:3", "urn:fdc:peppol.eu:poacc:bis:ordering:3"),
           "OrderResponse": ("urn:fdc:peppol.eu:poacc:trns:order_response:3", "urn:fdc:peppol.eu:poacc:bis:ordering:3"),
           "DespatchAdvice": ("urn:fdc:peppol.eu:poacc:trns:despatch_advice:3",
                              "urn:fdc:peppol.eu:poacc:bis:despatch_advice:3")}
MAX_BYTES = 2_000_000
#: base units as UN/ECE recommendation 20 codes (the unitCode of a quantity)
UNITS = {"EA": "EA", "PC": "H87", "KG": "KGM", "G": "GRM", "T": "TNE", "L": "LTR", "ML": "MLT", "M": "MTR",
         "M2": "MTK", "M3": "MTQ", "BOX": "BX", "PAC": "PK", "SET": "SET"}
#: line status codes (UNCL4343 subset as Peppol uses them): 5 accepted, 3 changed, 7 rejected
ACCEPTED, CHANGED, REJECTED = "5", "3", "7"

ET.register_namespace("cbc", CBC)
ET.register_namespace("cac", CAC)


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _num(q: float) -> str:
    return f"{q:.6f}".rstrip("0").rstrip(".") or "0"


# ------------------------------------------------------------------------------------------------ out
def _party(parent: ET.Element, tag: str, name: str, tax_id: str, address: str) -> None:
    p = ET.SubElement(ET.SubElement(parent, _q(CAC, tag)), _q(CAC, "Party"))
    ET.SubElement(ET.SubElement(p, _q(CAC, "PartyName")), _q(CBC, "Name")).text = name
    if address:
        a = ET.SubElement(p, _q(CAC, "PostalAddress"))
        lines = [x.strip() for x in address.splitlines() if x.strip()]
        ET.SubElement(a, _q(CBC, "StreetName")).text = lines[0]
        if len(lines) > 1:
            ET.SubElement(a, _q(CBC, "CityName")).text = ", ".join(lines[1:])
    if tax_id:
        t = ET.SubElement(p, _q(CAC, "PartyTaxScheme"))
        ET.SubElement(t, _q(CBC, "CompanyID")).text = tax_id
        ET.SubElement(ET.SubElement(t, _q(CAC, "TaxScheme")), _q(CBC, "ID")).text = "GST" if tax_id[:2].isdigit() \
            else "VAT"


def order_xml(ds: Dataset, po_id: str) -> str:
    """The purchase order as a UBL Order: header, the buyer and seller, where to deliver, and its open lines."""
    from ..purchasing import received
    po = ds.purchase_order_by_id.get(po_id)
    if po is None:
        raise PortalError(f"there is no purchase order {po_id}")
    s = ds.settings
    cur = po.currency or ds.vendor(po.supplier).currency or s.currency
    root = ET.Element(_q(DOC["Order"], "Order"))
    cust, prof = PROFILE["Order"]
    for tag, text in (("CustomizationID", cust), ("ProfileID", prof), ("ID", po.id),
                      ("IssueDate", (po.sent_on or po.order_date).isoformat())):
        ET.SubElement(root, _q(CBC, tag)).text = text
    if po.note:
        ET.SubElement(root, _q(CBC, "Note")).text = po.note
    ET.SubElement(root, _q(CBC, "DocumentCurrencyCode")).text = cur
    to = ds.location_by_id.get(po.location)
    sup = ds.location_by_id.get(po.supplier)
    _party(root, "BuyerCustomerParty", s.company_name or "", getattr(s, "company_tax_id", "") or "",
           s.company_address or "")
    _party(root, "SellerSupplierParty", _name(ds, po.supplier), (sup.tax_id or "") if sup else "",
           (sup.address or "") if sup else "")
    d = ET.SubElement(root, _q(CAC, "Delivery"))
    loc = ET.SubElement(d, _q(CAC, "DeliveryLocation"))
    ET.SubElement(loc, _q(CBC, "ID")).text = po.location
    if to is not None and to.address:
        lines = [x.strip() for x in to.address.splitlines() if x.strip()]
        a = ET.SubElement(loc, _q(CAC, "Address"))
        ET.SubElement(a, _q(CBC, "StreetName")).text = lines[0]
        if len(lines) > 1:
            ET.SubElement(a, _q(CBC, "CityName")).text = ", ".join(lines[1:])
    got = received(ds)
    total = 0.0
    lines_out = []
    for r in sorted((x for x in ds.receipts if x.po == po.id), key=lambda x: x.id):
        ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
        if ordered - got.get(r.id, 0.0) <= 1e-9:
            continue
        lines_out.append((r, ordered))
        total += ordered * (r.price or 0.0)
    m = ET.SubElement(root, _q(CAC, "AnticipatedMonetaryTotal"))
    ET.SubElement(m, _q(CBC, "LineExtensionAmount"), currencyID=cur).text = f"{total:.2f}"
    ET.SubElement(m, _q(CBC, "PayableAmount"), currencyID=cur).text = f"{total:.2f}"
    for r, ordered in lines_out:
        p = ds.product_by_id.get(r.product)
        li = ET.SubElement(ET.SubElement(root, _q(CAC, "OrderLine")), _q(CAC, "LineItem"))
        ET.SubElement(li, _q(CBC, "ID")).text = r.id
        ET.SubElement(li, _q(CBC, "Quantity"), unitCode=UNITS.get((p.base_uom if p else "EA").upper(), "EA")).text = \
            _num(ordered)
        if r.price is not None:
            ET.SubElement(li, _q(CBC, "LineExtensionAmount"), currencyID=cur).text = f"{ordered * r.price:.2f}"
        per = ET.SubElement(ET.SubElement(li, _q(CAC, "Delivery")), _q(CAC, "RequestedDeliveryPeriod"))
        ET.SubElement(per, _q(CBC, "EndDate")).text = r.due_date.isoformat()
        if r.price is not None:
            ET.SubElement(ET.SubElement(li, _q(CAC, "Price")), _q(CBC, "PriceAmount"), currencyID=cur).text = \
                _num(r.price)
        it = ET.SubElement(li, _q(CAC, "Item"))
        ET.SubElement(it, _q(CBC, "Name")).text = _name(ds, r.product)
        pu = ds.purchasing_source_by_id.get(r.source or "")
        if pu is not None and pu.vendor_material:
            ET.SubElement(ET.SubElement(it, _q(CAC, "SellersItemIdentification")), _q(CBC, "ID")).text = \
                pu.vendor_material
        ET.SubElement(ET.SubElement(it, _q(CAC, "BuyersItemIdentification")), _q(CBC, "ID")).text = r.product
        if p is not None and p.hsn:
            cc = ET.SubElement(ET.SubElement(it, _q(CAC, "CommodityClassification")),
                               _q(CBC, "ItemClassificationCode"), listID="HS")
            cc.text = p.hsn
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


# ------------------------------------------------------------------------------------------------ in
def _read(text: str | bytes, kind: str) -> ET.Element:
    raw = text.encode() if isinstance(text, str) else text
    if len(raw) > MAX_BYTES:
        raise PortalError(f"the message is larger than {MAX_BYTES // 1_000_000} MB")
    head = raw.upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise PortalError("messages with a document type declaration are not read")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise PortalError(f"the message is not readable XML ({e})") from e
    if root.tag != _q(DOC[kind], kind):
        local = root.tag.rsplit("}", 1)[-1]
        raise PortalError(f"expected a UBL {kind}, got {local}")
    return root


def _text(el: ET.Element | None, path: str) -> str:
    if el is None:
        return ""
    x = el.find(path, {"cbc": CBC, "cac": CAC})
    return (x.text or "").strip() if x is not None else ""


def _date(s: str, what: str) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError as e:
        raise PortalError(f"{what} {s!r} is not a date") from e


def _qty(s: str, what: str) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError as e:
        raise PortalError(f"{what} {s!r} is not a number") from e


NS = {"cbc": CBC, "cac": CAC}


def read_order_response(ds: Dataset, text: str | bytes) -> tuple[str, str, list[dict]]:
    """An OrderResponse as (supplier, their reference, lines for :func:`scp.portal.respond`)."""
    root = _read(text, "OrderResponse")
    po_id = _text(root, "cac:OrderReference/cbc:ID")
    po = ds.purchase_order_by_id.get(po_id)
    if po is None:
        raise PortalError(f"the response is for order {po_id or '(none)'}, which is not ours")
    code = _text(root, "cbc:OrderResponseCode")
    lines = []
    for ol in root.findall("cac:OrderLine", NS):
        li = ol.find("cac:LineItem", NS)
        lid = _text(ol, "cac:OrderLineReference/cbc:LineID") or _text(li, "cbc:ID")
        st = _text(li, "cbc:LineStatusCode")
        if st == REJECTED:
            lines.append({"order": lid, "qty": 0})
            continue
        q = _qty(_text(li, "cbc:Quantity"), f"{lid}: the quantity")
        d = _date(_text(li, "cac:Delivery/cac:PromisedDeliveryPeriod/cbc:EndDate")
                  or _text(li, "cac:Delivery/cbc:ActualDeliveryDate"), f"{lid}: the promised date")
        w: dict = {"order": lid}
        if q is not None:
            w["qty"] = q
        if d is not None:
            w["date"] = d.isoformat()
        lines.append(w)
    if not lines:
        if code == "RE":
            lines = [{"order": r.id, "qty": 0} for r in ds.receipts if r.po == po.id]
        elif code in ("AP", ""):
            lines = [{"order": r.id} for r in ds.receipts if r.po == po.id]
        else:
            raise PortalError(f"the response changes order {po_id} but names no lines")
    for w in lines:
        _line(ds, po.supplier, w["order"])
    return po.supplier, _text(root, "cbc:ID"), lines


def read_despatch_advice(ds: Dataset, text: str | bytes) -> tuple[str, dict]:
    """A DespatchAdvice as (supplier, arguments for :func:`scp.portal.dispatch`)."""
    root = _read(text, "DespatchAdvice")
    head_po = _text(root, "cac:OrderReference/cbc:ID")
    lines, supplier = [], None
    for dl in root.findall("cac:DespatchLine", NS):
        lid = _text(dl, "cac:OrderLineReference/cbc:LineID")
        po_id = _text(dl, "cac:OrderLineReference/cac:OrderReference/cbc:ID") or head_po
        r = next((x for x in ds.receipts if x.id == lid), None)
        if r is None or (po_id and r.po != po_id):
            raise PortalError(f"despatch line {_text(dl, 'cbc:ID') or '?'} names order line {lid or '(none)'}"
                              + (f" of {po_id}" if po_id else "") + ", which is not open")
        po = ds.purchase_order_by_id.get(r.po or "")
        if po is None:
            raise PortalError(f"{lid} is not on a purchase order")
        if supplier not in (None, po.supplier):
            raise PortalError("one despatch advice is for one supplier's orders")
        supplier = po.supplier
        q = _qty(_text(dl, "cbc:DeliveredQuantity"), f"{lid}: the quantity")
        lot = dl.find("cac:Item/cac:ItemInstance/cac:LotIdentification", NS)
        w: dict = {"order": lid, "qty": q}
        if lot is not None:
            w["batch"] = _text(lot, "cbc:LotNumberID") or None
            exp = _date(_text(lot, "cbc:ExpiryDate"), f"{lid}: the expiry date")
            w["expires_on"] = exp.isoformat() if exp else None
        lines.append(w)
    if not lines or supplier is None:
        raise PortalError("the despatch advice has no lines")
    shipped = _date(_text(root, "cac:Shipment/cac:Delivery/cac:Despatch/cbc:ActualDespatchDate")
                    or _text(root, "cbc:IssueDate"), "the despatch date")
    arrives = _date(_text(root, "cac:Shipment/cac:Delivery/cac:EstimatedDeliveryPeriod/cbc:EndDate")
                    or _text(root, "cac:Shipment/cac:Delivery/cac:RequestedDeliveryPeriod/cbc:EndDate"),
                    "the arrival date")
    return supplier, {"lines": lines, "shipped_on": shipped, "arrives_on": arrives,
                      "reference": _text(root, "cbc:ID"), "note": _text(root, "cbc:Note")}


def apply(ds: Dataset, kind: str, text: str | bytes) -> tuple[Dataset, PortalReport]:
    """Read an OrderResponse or DespatchAdvice and record it, as the portal would."""
    if kind == "order_response":
        supplier, ref, lines = read_order_response(ds, text)
        return respond(ds, supplier, lines, ref)
    if kind == "despatch_advice":
        supplier, kw = read_despatch_advice(ds, text)
        return dispatch(ds, supplier, source="message", **kw)
    raise PortalError(f"{kind} is not a message read here (order_response or despatch_advice)")


def kind_of(text: str | bytes) -> str:
    """Which message it is, from its root element."""
    raw = text.encode() if isinstance(text, str) else text
    for kind, tag in (("order_response", b"OrderResponse"), ("despatch_advice", b"DespatchAdvice")):
        if b"<" + tag in raw[:4000] or b":" + tag in raw[:4000]:
            return kind
    raise PortalError("not an OrderResponse or a DespatchAdvice")


__all__ = ["apply", "kind_of", "order_xml", "read_despatch_advice", "read_order_response"]
