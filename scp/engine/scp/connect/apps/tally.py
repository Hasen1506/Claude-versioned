"""Tally Prime (ENTERPRISE_PLAN 3.2): XML over Tally's HTTP port.

Tally answers on its port (9000 unless set otherwise in F1 Help → Settings → Connectivity) to an XML envelope: an
*Export* of a collection with the fields asked for (stock items, ledgers, vouchers of a type over a date range), and
an *Import Data* of vouchers, answered with how many it created, altered or cancelled and the errors line by line.
The connector asks the company named (``SVCURRENTCOMPANY``; empty: the one open) and reads

* stock items as products (the name as the product's name and, untranslated, its code; the stock group as the family
  and the base unit as the unit of a new product), and their closing balance as the stock at the place the job names;
* ledgers under Sundry Debtors and Sundry Creditors as customers and suppliers (address, state as the region of a new
  one, GSTIN);
* vouchers of the sales order type, of the days back the job reads, as customer orders: a line's due date
  (``ORDERDUEDATE``) is its date, a line due in parts is a line per part, a cancelled voucher cancels the order here,
  an optional one is not read;

and makes purchase order vouchers numbered as the order here (an order changed here alters it, one cancelled or
deleted here cancels it). Quantities go without a unit, so Tally takes them in the stock item's own unit.

Tally sits on the company's own network, so the server's administrator allows its host by name
(``SCP_IMPORT_HOSTS=tally-pc``) for the server to reach it; an answer with a document type (entities) is refused.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from . import AppSettings, slug, today

SECRETS: list[str] = []
SAFE = re.compile(r'^[^"<>&\\\x00-\x1f]*$')     # a name inside a TDL formula: no quote, no markup


def check(source: str, s: AppSettings, secrets: dict[str, str]) -> None:
    for what, v in (("the company", s.company), ("the order voucher type", s.order_type),
                    ("the purchase voucher type", s.purchase_type), ("the purchase ledger", s.purchase_ledger)):
        if not SAFE.match(v):
            raise ValueError(f"{what} {v!r} has a character Tally's request cannot carry (\" < > & \\)")


# ------------------------------------------------------------------------------------------------ asking
def _vars(s: AppSettings, extra: str = "") -> str:
    company = f"<SVCURRENTCOMPANY>{escape(s.company)}</SVCURRENTCOMPANY>" if s.company else ""
    return f"<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{company}{extra}</STATICVARIABLES>"


def _export(name: str, body: str, s: AppSettings, extra: str = "") -> bytes:
    return ("<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>"
            f"<ID>{name}</ID></HEADER><BODY><DESC>{_vars(s, extra)}<TDL><TDLMESSAGE>{body}</TDLMESSAGE></TDL></DESC>"
            "</BODY></ENVELOPE>").encode()


def _tdate(d: dt.date) -> str:
    return d.strftime("%d-%b-%Y")


def request(kind: str, s: AppSettings, on: dt.date | None = None) -> bytes:
    """The envelope that asks Tally for ``kind``."""
    on = on or today()
    period = (f'<SVFROMDATE TYPE="Date">{_tdate(on - dt.timedelta(days=s.days_back))}</SVFROMDATE>'
              f'<SVTODATE TYPE="Date">{_tdate(on)}</SVTODATE>')
    if kind in ("records:products", "stock"):
        return _export("SCPItems", '<COLLECTION NAME="SCPItems" ISMODIFY="No"><TYPE>StockItem</TYPE>'
                                   "<FETCH>Name, Parent, BaseUnits, ClosingBalance</FETCH></COLLECTION>", s, period)
    if kind == "records:locations":
        return _export("SCPParties",
                       '<COLLECTION NAME="SCPParties" ISMODIFY="No"><TYPE>Ledger</TYPE>'
                       "<FETCH>Name, Parent, Address, LedStateName, PartyGSTIN, LedGSTRegDetails</FETCH>"
                       "<COMPUTE>SCPDebtor: $$IsBelongsTo:$$GroupSundryDebtors</COMPUTE>"
                       "<COMPUTE>SCPCreditor: $$IsBelongsTo:$$GroupSundryCreditors</COMPUTE>"
                       "<FILTER>SCPParty</FILTER></COLLECTION>"
                       '<SYSTEM TYPE="Formulae" NAME="SCPParty">$$IsBelongsTo:$$GroupSundryDebtors OR '
                       "$$IsBelongsTo:$$GroupSundryCreditors</SYSTEM>", s)
    if kind == "orders":
        return _export("SCPOrders",
                       '<COLLECTION NAME="SCPOrders" ISMODIFY="No"><TYPE>Voucher</TYPE>'
                       "<FETCH>Date, VoucherNumber, VoucherTypeName, PartyLedgerName, Reference, IsCancelled, "
                       "IsOptional, Narration, AllInventoryEntries</FETCH><FILTER>SCPType</FILTER></COLLECTION>"
                       f'<SYSTEM TYPE="Formulae" NAME="SCPType">$VoucherTypeName = "{escape(s.order_type)}"</SYSTEM>',
                       s, period)
    raise ValueError(f"Tally gives no {kind}")


def read(job: dict, s: AppSettings, secrets: dict[str, str], headers: dict[str, str]) -> bytes:
    from .. import imports
    status, raw = imports.http("POST", job["source"], {**headers, "Content-Type": "text/xml"}, request(job["kind"], s))
    if status >= 400:
        raise ValueError(f"Tally answered {status}: {_text(raw)[:200]}")
    root = _xml(raw)
    errors = [e.text.strip() for e in root.iter() if _tag(e) == "LINEERROR" and e.text and e.text.strip()]
    if errors:
        raise ValueError(f"Tally says: {'; '.join(errors)}")
    return raw


# ------------------------------------------------------------------------------------------------ reading
def _text(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def _xml(raw: bytes) -> ET.Element:
    text = _text(raw)
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("Tally's answer has a document type: it is not read")
    # Tally writes control characters as references XML does not allow (&#4; in a name)
    text = re.sub(r"&#(x[0-9a-f]+|\d+);", lambda m: "" if _control(m.group(1)) else m.group(0), text, flags=re.I)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    try:
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"Tally's answer is not XML Tally writes ({e})") from None


def _control(ref: str) -> bool:
    n = int(ref[1:], 16) if ref[:1] in "xX" else int(ref)
    return n < 32 and n not in (9, 10, 13)


def _tag(e: ET.Element) -> str:
    return e.tag.rsplit("}", 1)[-1].upper()


def _kids(e: ET.Element, *tags: str) -> list[ET.Element]:
    return [k for k in e if _tag(k) in tags]


def _val(e: ET.Element, *tags: str) -> str:
    for k in e:
        if _tag(k) in tags:
            return "".join(k.itertext()).strip()
    return ""


def _name(e: ET.Element) -> str:
    n = e.get("NAME") or e.get("name") or ""
    if not n:
        for lst in _kids(e, "NAME.LIST", "LANGUAGENAME.LIST"):
            n = _val(lst, "NAME") or next((_val(x, "NAME") for x in _kids(lst, "NAME.LIST")), "")
            if n:
                break
    return (n or _val(e, "NAME")).strip()


def _num(v: str) -> float | None:
    """The number in Tally's '1,200.50 Nos', '450.00/Nos' or '-12 Nos = 1 Box'."""
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+", v or "")
    return float(m.group(0).replace(",", "")) if m else None


def _date(v: str) -> str | None:
    v = (v or "").strip()
    for f in ("%Y%m%d", "%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(v, f).date().isoformat()
        except ValueError:
            continue
    return None


def _yes(v: str) -> bool:
    return v.strip().lower() in ("yes", "y", "1", "true")


def _all(root: ET.Element, tag: str) -> list[ET.Element]:
    return [e for e in root.iter() if _tag(e) == tag]


def rows(kind: str, raw: bytes, s: AppSettings) -> list[dict[str, Any]]:
    root = _xml(raw)
    out: list[dict[str, Any]] = []
    if kind == "records:products":
        for e in _all(root, "STOCKITEM"):
            name = _name(e)
            if not name:
                continue
            r: dict[str, Any] = {"id": name, "name": name}
            parent = _val(e, "PARENT")
            if parent and parent.lower() != "primary":
                r["family"] = parent
            unit = _val(e, "BASEUNITS")
            if unit:
                r["base_uom"] = unit[:12]
            out.append(r)
    elif kind == "stock":
        for e in _all(root, "STOCKITEM"):
            name, bal = _name(e), _val(e, "CLOSINGBALANCE")
            if name and bal:                    # an item Tally gives no balance for has never had stock
                out.append({"product": name, "qty": _num(bal) or 0.0})
    elif kind == "records:locations":
        for e in _all(root, "LEDGER"):
            name = _name(e)
            parent = _val(e, "PARENT").lower()
            debtor = _yes(_val(e, "SCPDEBTOR")) or "debtor" in parent
            creditor = _yes(_val(e, "SCPCREDITOR")) or "creditor" in parent
            if not name or not (debtor or creditor):
                continue
            r = {"id": name, "name": name, "type": "customer" if debtor else "supplier"}
            lines = [x.text.strip() for lst in _kids(e, "ADDRESS.LIST") for x in lst if x.text and x.text.strip()]
            if lines:
                r["address"] = "\n".join(lines)[:400]
            state = _val(e, "LEDSTATENAME", "STATENAME")
            if state:
                r["region"] = state
            gstin = _val(e, "PARTYGSTIN") or next((_val(x, "GSTIN") for x in _kids(e, "LEDGSTREGDETAILS.LIST")), "")
            if gstin:
                r["tax_id"] = gstin[:40]
            out.append(r)
    elif kind == "orders":
        for v in _all(root, "VOUCHER"):
            if _yes(_val(v, "ISOPTIONAL")):
                continue
            head: dict[str, Any] = {"number": _val(v, "VOUCHERNUMBER"), "customer": _val(v, "PARTYLEDGERNAME")}
            day = _date(_val(v, "DATE") or v.get("DATE", ""))
            if day:
                head["order_date"] = day
            for f, tag, n in (("customer_ref", "REFERENCE", 64), ("note", "NARRATION", 400)):
                if _val(v, tag):
                    head[f] = _val(v, tag)[:n]
            if _yes(_val(v, "ISCANCELLED")):
                head["cancelled"] = True
            lines = _kids(v, "ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST")
            if not lines:
                out.append(head)
            for ln in lines:
                product = _val(ln, "STOCKITEMNAME")
                price = _num(_val(ln, "RATE").split("/")[0]) if _val(ln, "RATE") else None
                parts = [(abs(_num(_val(b, "BILLEDQTY") or _val(b, "ACTUALQTY")) or 0.0),
                          _date(_val(b, "ORDERDUEDATE"))) for b in _kids(ln, "BATCHALLOCATIONS.LIST")
                         if _val(b, "BILLEDQTY") or _val(b, "ACTUALQTY")]
                if not parts:
                    parts = [(abs(_num(_val(ln, "BILLEDQTY") or _val(ln, "ACTUALQTY")) or 0.0), None)]
                for qty, due in parts:
                    r = {**head, "product": product, "qty": qty, "date": due or day}
                    if price is not None:
                        r["price"] = abs(price)
                    out.append(r)
    return out


# ------------------------------------------------------------------------------------------------ sending
def voucher(o: Any, s: AppSettings, party: str, items: dict[str, str], godowns: dict[str, str]) -> bytes:
    """A purchase order voucher: made (new), altered (changed) or cancelled (cancelled or deleted here)."""
    tdate = o.order_date or today()
    number = o.erp_ref or o.id
    vtype = quoteattr(s.purchase_type)
    if o.change == "withdrawn" or o.cancelled or not any(not ln.cancelled for ln in o.lines):
        body = (f'<VOUCHER DATE="{_tdate(tdate)}" TAGNAME="Voucher Number" TAGVALUE={quoteattr(number)} '
                f'VCHTYPE={vtype} ACTION="Cancel"><NARRATION>Cancelled in planning ({escape(o.id)})</NARRATION>'
                "</VOUCHER>")
    else:
        action = (f'TAGNAME="Voucher Number" TAGVALUE={quoteattr(number)} ACTION="Alter"' if o.erp_ref
                  else 'ACTION="Create"')
        lines, total = [], 0.0
        for ln in o.lines:
            if ln.cancelled:
                continue
            amount = round(ln.qty * ln.price, 2) if ln.price is not None else None
            total += amount or 0.0
            rate = f"<RATE>{ln.price:.2f}</RATE>" if ln.price is not None else ""
            money = f"<AMOUNT>{-amount:.2f}</AMOUNT>" if amount is not None else ""
            godown = f"<GODOWNNAME>{escape(godowns[o.location])}</GODOWNNAME>" if o.location in godowns else ""
            lines.append(
                f"<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{escape(items[ln.product])}</STOCKITEMNAME>"
                f"<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>{rate}<ACTUALQTY>{_q(ln.qty)}</ACTUALQTY>"
                f"<BILLEDQTY>{_q(ln.qty)}</BILLEDQTY>{money}<BATCHALLOCATIONS.LIST>{godown}"
                f"<ORDERNO>{escape(number)}</ORDERNO><ORDERDUEDATE>{_tdate(ln.date)}</ORDERDUEDATE>"
                f"<ACTUALQTY>{_q(ln.qty)}</ACTUALQTY><BILLEDQTY>{_q(ln.qty)}</BILLEDQTY>{money}"
                "</BATCHALLOCATIONS.LIST>"
                f"<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>{escape(s.purchase_ledger)}</LEDGERNAME>"
                f"<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>{money}</ACCOUNTINGALLOCATIONS.LIST>"
                "</ALLINVENTORYENTRIES.LIST>")
        body = (f'<VOUCHER VCHTYPE={vtype} {action}><DATE>{tdate:%Y%m%d}</DATE>'
                f"<VOUCHERTYPENAME>{escape(s.purchase_type)}</VOUCHERTYPENAME>"
                f"<VOUCHERNUMBER>{escape(number)}</VOUCHERNUMBER><REFERENCE>{escape(o.id)}</REFERENCE>"
                f"<PARTYLEDGERNAME>{escape(party)}</PARTYLEDGERNAME><PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>"
                f"<LEDGERENTRIES.LIST><LEDGERNAME>{escape(party)}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>"
                f"<AMOUNT>{total:.2f}</AMOUNT></LEDGERENTRIES.LIST>{''.join(lines)}</VOUCHER>")
    company = f"<SVCURRENTCOMPANY>{escape(s.company)}</SVCURRENTCOMPANY>" if s.company else ""
    return ("<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC>"
            f"<REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES>{company}</STATICVARIABLES></REQUESTDESC>"
            f'<REQUESTDATA><TALLYMESSAGE xmlns:UDF="TallyUDF">{body}</TALLYMESSAGE></REQUESTDATA></IMPORTDATA>'
            "</BODY></ENVELOPE>").encode()


def _q(q: float) -> str:
    return f"{q:.3f}".rstrip("0").rstrip(".")


def taken(raw: bytes) -> None:
    """Tally's answer to a voucher: nothing raised when it made, altered or cancelled it."""
    root = _xml(raw)
    counts = {t: int(_num(e.text or "") or 0) for e in root.iter()
              for t in ("CREATED", "ALTERED", "CANCELLED", "ERRORS") if _tag(e) == t}
    errors = [e.text.strip() for e in root.iter() if _tag(e) == "LINEERROR" and e.text and e.text.strip()]
    if errors or counts.get("ERRORS", 0):
        raise ValueError("Tally says: " + ("; ".join(errors) or f"{counts['ERRORS']} error(s)"))
    if not (counts.get("CREATED", 0) + counts.get("ALTERED", 0) + counts.get("CANCELLED", 0)):
        raise ValueError("Tally took nothing (no voucher made, altered or cancelled)")


class Sender:
    """Purchase orders to Tally, one voucher a request (Tally's answer counts, it does not name, what it took)."""

    def __init__(self, job: dict, s: AppSettings, secrets: dict[str, str], headers: dict[str, str]) -> None:
        self.job, self.s, self.headers = job, s, headers

    def codes(self, ds: Any, kind: str, here: str) -> str:
        """The name Tally knows a product or a supplier by when the mapping does not translate it: the name here
        when the code here was made from it, else the code."""
        rec = ds.product_by_id.get(here) if kind == "product" else ds.location_by_id.get(here)
        name = getattr(rec, "name", "") or ""
        if kind == "supplier":
            return name or here
        return name if name and slug(name) == here else here

    def exists(self, number: str) -> bool:
        """Whether Tally has a purchase order voucher numbered so (made before, and its answer lost)."""
        from .. import imports
        if not SAFE.match(number):
            return False
        ask = _export("SCPFind", '<COLLECTION NAME="SCPFind" ISMODIFY="No"><TYPE>Voucher</TYPE>'
                                 "<FETCH>VoucherNumber</FETCH><FILTER>SCPNumber</FILTER></COLLECTION>"
                                 f'<SYSTEM TYPE="Formulae" NAME="SCPNumber">$VoucherNumber = "{escape(number)}" AND '
                                 f'$VoucherTypeName = "{escape(self.s.purchase_type)}"</SYSTEM>', self.s)
        status, raw = imports.http("POST", self.job["source"], {**self.headers, "Content-Type": "text/xml"}, ask)
        if status >= 400:
            raise ValueError(f"Tally answered {status}: {_text(raw)[:200]}")
        return any(_val(v, "VOUCHERNUMBER") == number for v in _all(_xml(raw), "VOUCHER"))

    def payload(self, o: Any, party: str, items: dict[str, str], godowns: dict[str, str]) -> bytes:
        if not o.erp_ref and o.change == "new" and self.exists(o.id):
            o = o.model_copy(update={"erp_ref": o.id})      # it is there: altered, not made twice
        return voucher(o, self.s, party, items, godowns)

    def send(self, o: Any, payload: bytes) -> str:
        from .. import imports
        status, raw = imports.http("POST", self.job["source"], {**self.headers, "Content-Type": "text/xml"}, payload)
        if status >= 400:
            raise ValueError(f"Tally answered {status}: {_text(raw)[:200]}")
        taken(raw)
        return o.erp_ref or o.id
