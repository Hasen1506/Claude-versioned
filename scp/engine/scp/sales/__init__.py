"""Order to cash (≈ S/4 SD): orders with several lines, prices with scales and discounts, payment terms and a credit
check, quotations, deliveries picked, packed, shipped and signed for, invoices and payments, returns and credit notes.

* **Orders.** :func:`create_order` takes an order of several lines for one customer. Each line is priced (the
  customer's price at its quantity scale, else the product's, less the customer's discounts, unless the line brings
  its own), promised after every order already promised, and made firm where it needs new supply (R13). The order is
  checked against the customer's credit limit: over it, the order is still promised but not delivered until someone
  releases it (:func:`release_credit`).
* **Quotations.** :func:`create_quotation` prices an offer without promising it; :func:`win_quotation` turns it into an
  order at the quoted prices, :func:`lose_quotation` closes it.
* **Deliveries.** :func:`create_deliveries` puts order lines due to ship on deliveries, one per customer and shipping
  place; a delivery is picked (:func:`pick`), packed (:func:`pack`), shipped (:func:`issue`: the sale movements, one
  material document) and signed for (:func:`proof`).
* **Invoices.** :func:`create_invoices` bills what was shipped and not yet billed, one invoice per customer and
  payment terms, with tax; :func:`pay` records a payment (the cash discount is taken when paid in time),
  :func:`cancel_invoice` takes one back so its goods can be billed again.
* **Returns.** :func:`create_return` agrees a return; :func:`receive_return` takes the goods back into stock (a
  receipt that names the return, into quality inspection by default); :func:`credit_return` pays it back with a
  credit note.

What a customer owes (their exposure) is the value of their open order lines, what was shipped and not billed, and
their unpaid invoices less credit notes not yet paid out.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from ..actuals.documents import StockError, complete
from ..actuals.post import delivered, ordered_now, ship_point
from ..actuals.stock import EPS, movement_ids
from ..model import (
    ClosedOrder, Dataset, DemandKind, DemandRecord, GoodsMovement, LocationType, MovementType, StockType,
)
from ..model.common import STOCKING_LOCATION_TYPES
from ..model.sales import (
    Delivery, DeliveryLine, Invoice, InvoiceLine, Payment, Quotation, QuoteLine, ReturnOrder, SalesOrder,
)
from ..promise.orders import OrderError, _promise, make_supply, next_order_id
from .result import (
    CustomerRow, DeliveryView, InvoiceView, OrderLineView, OrderView, QuotationView, ReturnView, SalesReport, SalesView,
    TaxPart, ToBill, ToDeliver,
)


class SalesError(ValueError):
    """An order-to-cash action the data does not allow; the message says why in plain words."""


# ------------------------------------------------------------------------------------------------ words and numbers
def _n(q: float) -> str:
    t = f"{q:,.2f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _m(ds: Dataset, v: float) -> str:
    return f"{ds.settings.currency} {v:,.2f}"


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _name(ds: Dataset, oid: str) -> str:
    x = ds.location_by_id.get(oid) or ds.product_by_id.get(oid)
    return (x.name or x.id) if x else oid


def _next(ids: list[str], prefix: str) -> str:
    n = 0
    for x in ids:
        m = re.fullmatch(re.escape(prefix) + r"-(\d+)", x or "")
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}-{n + 1:05d}"


def _today(ds: Dataset, on: date | None) -> date:
    return on or ds.settings.planning_start


def _validated(ds: Dataset) -> Dataset:
    return Dataset.model_validate(ds.model_dump())


# ------------------------------------------------------------------------------------------------ lines and prices
def _closed_lines(ds: Dataset) -> dict[str, ClosedOrder]:
    return {c.id: c for c in ds.closed_orders if c.kind == "sales"}


def line_record(ds: Dataset, lid: str) -> DemandRecord | None:
    """A sales order line, open or closed (a closed line as it was ordered)."""
    d = next((d for d in ds.demand if d.kind is DemandKind.SALES_ORDER and d.id == lid), None)
    if d is not None:
        return d
    c = _closed_lines(ds).get(lid)
    if c is not None and c.source_order:
        try:
            return DemandRecord.model_validate(c.source_order)
        except ValueError:
            return None
    return None


def net_price(ds: Dataset, d: DemandRecord) -> float | None:
    """A line's net price per unit: its own, else the customer's or the product's, less the customer's discounts."""
    return ds.selling_price(d.location, d.product, d.price)


def price(ds: Dataset, customer: str, product: str, qty: float, own: float | None = None
          ) -> tuple[float | None, float | None, float]:
    """(net price, list price, discount) for a line: ``own`` is a net price agreed for this line."""
    base, disc = ds.list_price(customer, product, qty)
    if own is not None:
        return own, base, (1 - own / base) if base else 0.0
    if base is None:
        return None, None, 0.0
    return round(base * (1 - disc), 6), base, disc


def _lines_of(ds: Dataset, oid: str) -> list[DemandRecord]:
    """An order's lines, open and closed, in line order."""
    out = [d for d in ds.demand if d.kind is DemandKind.SALES_ORDER and d.order == oid]
    have = {d.id for d in out}
    for c in ds.closed_orders:
        if c.kind == "sales" and c.id not in have and (c.source_order or {}).get("order") == oid:
            r = line_record(ds, c.id)
            if r is not None:
                out.append(r)
    return sorted(out, key=lambda d: _line_no(d.id or ""))


def _line_no(lid: str) -> int:
    m = re.search(r"/(\d+)$", lid)
    return int(m.group(1)) if m else 0


def _header(ds: Dataset, oid: str) -> SalesOrder:
    h = next((o for o in ds.sales_orders if o.id == oid), None)
    if h is None:
        raise SalesError(f"there is no sales order {oid}")
    return h


def _header_of(ds: Dataset, d: DemandRecord) -> SalesOrder | None:
    return next((o for o in ds.sales_orders if o.id == d.order), None) if d.order else None


def _replace(items: list, old, new) -> list:
    return [new if x is old else x for x in items]


# ------------------------------------------------------------------------------------------------ credit
def _billed(ds: Dataset) -> dict[str, float]:
    """Quantity invoiced per order line (credit notes for returns do not take it back)."""
    out: dict[str, float] = defaultdict(float)
    for inv in ds.invoices:
        if inv.kind == "invoice" and not inv.cancelled:
            for ln in inv.lines:
                if ln.order:
                    out[ln.order] += ln.qty
    return out


def _billed_movements(ds: Dataset) -> set[str]:
    return {m for inv in ds.invoices if inv.kind == "invoice" and not inv.cancelled for ln in inv.lines
            for m in ln.movements}


def _sales_moves(ds: Dataset) -> list[GoodsMovement]:
    """Deliveries to customers that still count: not reversals and not reversed."""
    back = {m.reversal_of for m in ds.movements if m.reversal_of}
    return [m for m in ds.movements if m.type is MovementType.SALE and m.reference and not m.reversal_of
            and m.id not in back]


def to_bill(ds: Dataset) -> list[ToBill]:
    """What was shipped and not invoiced yet, per order line and day."""
    done = _billed_movements(ds)
    groups: dict[tuple[str, date], list[GoodsMovement]] = defaultdict(list)
    for m in _sales_moves(ds):
        if m.id not in done:
            groups[(m.reference or "", m.date)].append(m)
    out = []
    for (lid, day), ms in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        d = line_record(ds, lid)
        if d is None:
            continue
        q = round(sum(m.qty for m in ms), 6)
        p = net_price(ds, d)
        out.append(ToBill(order=lid, customer=d.location, product=d.product, qty=q, price=p,
                          value=None if p is None else round(q * p, 2), delivered_on=day, movements=[m.id for m in ms]))
    return out


def exposure(ds: Dataset, customer: str) -> tuple[float, float, float]:
    """(open order value, shipped and not billed, receivable) for a customer."""
    open_v = 0.0
    for d in ds.demand:
        if d.kind is DemandKind.SALES_ORDER and d.location == customer:
            p = net_price(ds, d) or 0.0
            open_v += max(0.0, ordered_now(ds, d) - delivered(ds, d.id or "")) * p * (1 + line_rate(ds, customer,
                                                                                                     d.product))
    unbilled = sum((b.value or 0.0) * (1 + line_rate(ds, customer, b.product)) for b in to_bill(ds)
                   if b.customer == customer)
    rec = 0.0
    for inv in ds.invoices:
        if inv.customer == customer and not inv.cancelled:
            rec += inv.open if inv.kind == "invoice" else -inv.open
    return round(open_v, 2), round(unbilled, 2), round(rec, 2)


def _tax_rate(ds: Dataset, customer: str) -> float:
    c = ds.customer_by_id.get(customer)
    return c.tax_rate if c and c.tax_rate is not None else ds.sales.tax_rate


def line_rate(ds: Dataset, customer: str, product: str) -> float:
    """The tax on a line (N123): the customer's own rate (an exemption, an export) first, then the product's, then
    the company's."""
    c = ds.customer_by_id.get(customer)
    if c and c.tax_rate is not None:
        return c.tax_rate
    p = ds.product_by_id.get(product)
    return p.tax_rate if p and p.tax_rate is not None else ds.sales.tax_rate


def _place(tax_id: str, region: str) -> str:
    """The state for the place of supply: the region, else a GSTIN's first two digits (its state code)."""
    if region.strip():
        return region.strip().lower()
    t = tax_id.strip()
    return t[:2] if len(t) >= 2 and t[:2].isdigit() else ""


def tax_split(ds: Dataset, customer: str) -> str:
    """How an invoice to this customer shows its tax (N123): with the company's GST split, CGST and SGST when the
    customer is in the company's state, IGST when in another or not known."""
    if ds.sales.tax_split != "gst":
        return ""
    loc = ds.location_by_id.get(customer)
    ours = _place(ds.settings.company_tax_id, ds.settings.company_region)
    theirs = _place(loc.tax_id, loc.region) if loc else ""
    return "cgst_sgst" if ours and ours == theirs else "igst"


def _rated(ds: Dataset, customer: str, ln: InvoiceLine) -> InvoiceLine:
    r = line_rate(ds, customer, ln.product)
    return ln if r == _tax_rate(ds, customer) else ln.model_copy(update={"tax_rate": r})


def _credit(ds: Dataset, customer: str, adding: float) -> tuple[bool, str]:
    """Would ``adding`` (with tax) take the customer over their credit limit? And the words why."""
    c = ds.customer_by_id.get(customer)
    if not ds.sales.credit_check or c is None or c.credit_limit is None:
        return False, ""
    o, u, r = exposure(ds, customer)
    total = o + u + r + adding
    if total <= c.credit_limit + 0.005:
        return False, ""
    parts = [f"this order {_m(ds, adding)}"] + [f"{w} {_m(ds, v)}" for w, v in
                                                 (("open orders", o), ("shipped, not invoiced", u), ("unpaid", r)) if v]
    return True, (f"{_name(ds, customer)} would owe {_m(ds, total)} against a credit limit of "
                  f"{_m(ds, c.credit_limit)} ({', '.join(parts)})")


def _sellable(ds: Dataset, customer: str) -> None:
    loc = ds.location_by_id.get(customer)
    if loc is None:
        raise SalesError(f"there is no customer {customer!r}")
    if loc.type is not LocationType.CUSTOMER and loc.type not in STOCKING_LOCATION_TYPES:
        raise SalesError(f"{loc.name or loc.id} is a supplier; an order comes from a customer")
    c = ds.customer_by_id.get(customer)
    if c is not None and c.blocked:
        raise SalesError(f"{_name(ds, customer)} is blocked for sales" + (f" ({c.block_reason})" if c.block_reason
                                                                          else "") + "; lift the block first")


# ------------------------------------------------------------------------------------------------ orders
def create_order(ds: Dataset, customer: str, lines: list[dict], *, order_date: date | None = None,
                 customer_ref: str = "", payment_terms: str | None = None, note: str = "",
                 quotation: str | None = None) -> tuple[Dataset, SalesReport]:
    """Take an order of several lines (``[{"product", "qty", "date", "price"?, "priority"?, "complete_delivery"?}]``)."""
    _sellable(ds, customer)
    if not lines:
        raise SalesError("an order needs at least one line")
    if payment_terms and payment_terms not in ds.payment_terms_by_id:
        raise SalesError(f"there are no payment terms {payment_terms!r}")
    oid = next_order_id(ds)
    recs: list[DemandRecord] = []
    for i, ln in enumerate(lines):
        prod = str(ln.get("product") or "")
        if prod not in ds.product_by_id:
            raise SalesError(f"line {i + 1}: there is no product {prod!r}")
        q = float(ln.get("qty") or 0)
        if q <= EPS:
            raise SalesError(f"line {i + 1}: a line needs a quantity")
        when = ln.get("date")
        if when is None:
            raise SalesError(f"line {i + 1}: say when it is wanted")
        when = date.fromisoformat(when) if isinstance(when, str) else when
        net, _, disc = price(ds, customer, prod, q, ln.get("price"))
        recs.append(DemandRecord(id=f"{oid}/{10 * (i + 1)}", order=oid, location=customer, product=prod, date=when,
                                 qty=q, kind=DemandKind.SALES_ORDER, priority=int(ln.get("priority") or 5),
                                 complete_delivery=bool(ln.get("complete_delivery")), price=net,
                                 discount=round(max(0.0, disc), 6), customer_ref=customer_ref[:64]))
    value = sum(r.qty * (r.price or 0.0) * (1 + line_rate(ds, customer, r.product)) for r in recs)
    blocked, why = _credit(ds, customer, round(value, 2))
    head = SalesOrder(id=oid, customer=customer, order_date=_today(ds, order_date), customer_ref=customer_ref[:64],
                      payment_terms=payment_terms, quotation=quotation, credit_block=blocked, credit_note=why[:200],
                      note=note[:400])
    cur = ds.model_copy(update={"sales_orders": [*ds.sales_orders, head]})
    promised = []
    for r in recs:
        try:
            p, confs = _promise(cur, r)
        except OrderError as e:
            raise SalesError(str(e)) from e
        cur = cur.model_copy(update={"demand": [*cur.demand, r], "confirmations": [*cur.confirmations, *confs]})
        promised.append((r, p))
    cur = _validated(cur)
    cur, firmed, made = make_supply(cur, promised)
    words = "; ".join(f"{_n(r.qty)} {_name(ds, r.product)} {_promised(p)}" for r, p in promised)
    msg = (f"{oid} taken for {_name(ds, customer)}: {plural(len(recs), 'line')}, {_m(ds, round(value, 2))} with tax. "
           f"{words}.{made}")
    if blocked:
        msg += f" Blocked for delivery: {why}. Release it when payment is in or the limit is raised."
    return cur, SalesReport(message=msg, documents=[oid], promises=[p for _, p in promised], firmed=firmed,
                            credit_block=blocked)


def plural(n: int, w: str) -> str:
    return f"{n} {w}{'' if n == 1 else 's'}"


def _promised(p) -> str:
    if not p.lines:
        return "cannot be promised yet"
    if p.status == "on_time":
        return "on the date asked"
    s = "promised " + ", ".join(f"{_n(x.qty)} on {_day(x.date)}" for x in p.lines)
    return s + (f", {_n(p.unconfirmed)} not yet" if p.unconfirmed > EPS else "")


def add_lines(ds: Dataset, oid: str, lines: list[dict]) -> tuple[Dataset, SalesReport]:
    """Add lines to an open order; they are priced, promised and checked against the credit limit like a new order."""
    h = _header(ds, oid)
    _sellable(ds, h.customer)
    n = max((_line_no(d.id or "") for d in _lines_of(ds, oid)), default=0)
    tmp, rep = create_order(ds, h.customer, lines, order_date=h.order_date, customer_ref=h.customer_ref,
                            payment_terms=h.payment_terms)
    made = tmp.sales_orders[-1]
    renum: dict[str, str] = {}
    for i, d in enumerate(x for x in tmp.demand if x.order == made.id):
        renum[d.id or ""] = f"{oid}/{n + 10 * (i + 1)}"
    demand = [d.model_copy(update={"id": renum[d.id or ""], "order": oid}) if d.order == made.id else d
              for d in tmp.demand]
    confs = [c.model_copy(update={"order": renum[c.order]}) if c.order in renum else c for c in tmp.confirmations]
    head = h.model_copy(update={"credit_block": h.credit_block or made.credit_block,
                                "credit_note": made.credit_note or h.credit_note})
    out = tmp.model_copy(update={"demand": demand, "confirmations": confs,
                                 "sales_orders": [head if o.id == oid else o for o in tmp.sales_orders
                                                  if o.id != made.id]})
    msg = rep.message.replace(f"{made.id} taken for {_name(ds, h.customer)}", f"{oid}: added")
    for a, b in renum.items():
        msg = msg.replace(a, b)
    return _validated(out), rep.model_copy(update={"message": msg, "documents": [oid]})


def release_credit(ds: Dataset, oid: str, by: str = "") -> tuple[Dataset, SalesReport]:
    """Release an order blocked over the credit limit: it may be delivered."""
    h = _header(ds, oid)
    if not h.credit_block:
        raise SalesError(f"{oid} is not blocked")
    note = f"Released{' by ' + by if by else ''} (was: {h.credit_note})"[:200]
    new = h.model_copy(update={"credit_block": False, "credit_note": note})
    return (ds.model_copy(update={"sales_orders": _replace(ds.sales_orders, h, new)}),
            SalesReport(message=f"{oid} released for delivery.", documents=[oid]))


def send_confirmation(ds: Dataset, oid: str, on: date | None = None) -> tuple[Dataset, SalesReport]:
    """Record that the order confirmation went to the customer."""
    h = _header(ds, oid)
    day = _today(ds, on)
    new = h.model_copy(update={"confirmation_sent_on": day})
    return (ds.model_copy(update={"sales_orders": _replace(ds.sales_orders, h, new)}),
            SalesReport(message=f"Order confirmation {oid} sent to {_name(ds, h.customer)} on {_day(day)}.",
                        documents=[oid]))


def cancel_order(ds: Dataset, oid: str, on: date | None = None, reason: str = "") -> tuple[Dataset, SalesReport]:
    """Cancel what is still open on every line of an order."""
    from ..promise.orders import cancel
    _header(ds, oid)
    open_ = [d for d in ds.demand if d.kind is DemandKind.SALES_ORDER and d.order == oid]
    if not open_:
        raise SalesError(f"nothing is open on {oid}")
    if any(dl.issued_on is None and any(x.order == d.id for x in dl.lines) for dl in ds.deliveries for d in open_):
        raise SalesError(f"{oid} has lines on a delivery not shipped yet: cancel the delivery first")
    cur = ds
    for d in open_:
        cur, _ = cancel(cur, d.id or "", on, reason)
    return cur, SalesReport(message=f"{oid} cancelled: {plural(len(open_), 'open line')} no longer wanted"
                                    + (f" ({reason})" if reason else "") + ". Their promised stock is free for other "
                                    "orders.", documents=[oid])


# ------------------------------------------------------------------------------------------------ quotations
def create_quotation(ds: Dataset, customer: str, lines: list[dict], *, on: date | None = None,
                     valid_to: date | None = None, customer_ref: str = "", payment_terms: str | None = None,
                     note: str = "") -> tuple[Dataset, SalesReport]:
    """Price an offer (``[{"product", "qty", "date", "price"?}]``); it promises and reserves nothing."""
    _sellable(ds, customer)
    if not lines:
        raise SalesError("a quotation needs at least one line")
    day = _today(ds, on)
    qid = _next([q.id for q in ds.quotations], "QT")
    out = []
    for i, ln in enumerate(lines):
        prod = str(ln.get("product") or "")
        if prod not in ds.product_by_id:
            raise SalesError(f"line {i + 1}: there is no product {prod!r}")
        q = float(ln.get("qty") or 0)
        if q <= EPS:
            raise SalesError(f"line {i + 1}: a line needs a quantity")
        net, base, _ = price(ds, customer, prod, q, ln.get("price"))
        if net is None:
            raise SalesError(f"line {i + 1}: {_name(ds, prod)} has no price for {_name(ds, customer)}: give one")
        when = ln.get("date") or day + timedelta(days=7)
        when = date.fromisoformat(when) if isinstance(when, str) else when
        out.append(QuoteLine(product=prod, qty=q, date=when, price=net, list_price=base))
    qt = Quotation(id=qid, customer=customer, quote_date=day,
                   valid_to=valid_to or day + timedelta(days=ds.sales.quotation_days), customer_ref=customer_ref[:64],
                   payment_terms=payment_terms, lines=out, note=note[:400])
    value = sum(x.qty * x.price for x in out)
    return (ds.model_copy(update={"quotations": [*ds.quotations, qt]}),
            SalesReport(message=f"Quotation {qid} for {_name(ds, customer)}: {plural(len(out), 'line')}, "
                                f"{_m(ds, round(value, 2))} before tax, valid until {_day(qt.valid_to)}.",
                        documents=[qid]))


def _quote(ds: Dataset, qid: str) -> Quotation:
    q = next((q for q in ds.quotations if q.id == qid), None)
    if q is None:
        raise SalesError(f"there is no quotation {qid}")
    if q.status != "open":
        raise SalesError(f"{qid} is already {q.status}" + (f" (order {q.order})" if q.order else ""))
    return q


def win_quotation(ds: Dataset, qid: str, on: date | None = None, customer_ref: str = "") -> tuple[Dataset, SalesReport]:
    """The customer accepts the quotation: it becomes an order at the quoted prices, promised as any order."""
    q = _quote(ds, qid)
    day = _today(ds, on)
    if q.valid_to < day:
        raise SalesError(f"{qid} ran out on {_day(q.valid_to)}: make a new quotation, or take the order directly")
    new, rep = create_order(ds, q.customer, [{"product": x.product, "qty": x.qty, "date": x.date, "price": x.price}
                                             for x in q.lines], order_date=day,
                            customer_ref=customer_ref or q.customer_ref, payment_terms=q.payment_terms,
                            quotation=qid)
    oid = rep.documents[0]
    new = new.model_copy(update={"quotations": [q.model_copy(update={"status": "won", "order": oid}) if x.id == qid
                                                else x for x in new.quotations]})
    return new, rep.model_copy(update={"message": f"{qid} won. " + rep.message, "documents": [oid, qid]})


def lose_quotation(ds: Dataset, qid: str, reason: str = "") -> tuple[Dataset, SalesReport]:
    q = _quote(ds, qid)
    new = q.model_copy(update={"status": "lost", "lost_reason": reason[:200]})
    return (ds.model_copy(update={"quotations": _replace(ds.quotations, q, new)}),
            SalesReport(message=f"{qid} lost" + (f" ({reason})" if reason else "") + ".", documents=[qid]))


# ------------------------------------------------------------------------------------------------ deliveries
def _on_open_deliveries(ds: Dataset) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for dl in ds.deliveries:
        if dl.issued_on is None:
            for x in dl.lines:
                out[x.order] += x.qty
    return out


def to_deliver(ds: Dataset, as_of: date | None = None) -> list[ToDeliver]:
    """Open order lines promised to ship within the delivery window and not on a delivery yet."""
    day = _today(ds, as_of)
    until = day + timedelta(days=ds.sales.delivery_days)
    on_dl = _on_open_deliveries(ds)
    out = []
    for d in ds.demand:
        if d.kind is not DemandKind.SALES_ORDER or not d.id:
            continue
        cf = sorted((c for c in ds.confirmations if c.order == d.id), key=lambda c: c.ship_date)
        ship = cf[0].ship_date if cf else d.date
        if ship > until:
            continue
        left = ordered_now(ds, d) - delivered(ds, d.id) - on_dl.get(d.id, 0.0)
        if left <= EPS:
            continue
        due = sum(c.qty for c in cf if c.ship_date <= until) if cf else left
        q = min(left, max(due - delivered(ds, d.id) + (ordered_now(ds, d) - d.qty), 0.0)) if cf else left
        if q <= EPS:
            continue
        h = _header_of(ds, d)
        out.append(ToDeliver(order=d.id, header=d.order or d.id, customer=d.location, product=d.product,
                             qty=round(q, 6), ship_from=ship_point(ds, d), ship_date=ship,
                             credit_block=bool(h and h.credit_block)))
    return sorted(out, key=lambda x: (x.ship_date, x.order))


def create_deliveries(ds: Dataset, lines: list[dict] | None = None, on: date | None = None
                      ) -> tuple[Dataset, SalesReport]:
    """Put order lines on deliveries (``[{"order", "qty"?, "batch"?, "ship_from"?}]``; None = every line due to ship),
    one delivery per customer and shipping place."""
    day = _today(ds, on)
    due = {t.order: t for t in to_deliver(ds, day)}
    picks = lines if lines is not None else [{"order": t.order} for t in due.values() if not t.credit_block]
    if not picks:
        raise SalesError("nothing is due to ship" if lines is None else "say which order lines to deliver")
    on_dl = _on_open_deliveries(ds)
    groups: dict[tuple[str, str], list[DeliveryLine]] = defaultdict(list)
    plan_day: dict[tuple[str, str], date] = {}
    for x in picks:
        lid = str(x.get("order") or "")
        d = next((r for r in ds.demand if r.kind is DemandKind.SALES_ORDER and r.id == lid), None)
        if d is None:
            raise SalesError(f"{lid} is not an open order line")
        h = _header_of(ds, d)
        if h is not None and h.credit_block:
            raise SalesError(f"{h.id} is blocked over the credit limit: release it first")
        left = ordered_now(ds, d) - delivered(ds, lid) - on_dl.get(lid, 0.0)
        q = float(x.get("qty") or (due[lid].qty if lid in due else left))
        if left <= EPS:
            raise SalesError(f"{lid} is already on a delivery or delivered")
        if q > left + EPS:
            raise SalesError(f"{lid}: only {_n(left)} are still to deliver")
        frm = str(x.get("ship_from") or ship_point(ds, d) or "")
        if ds.location_type(frm) not in STOCKING_LOCATION_TYPES:
            raise SalesError(f"{lid} has no place to ship from: promise it first, or give {_name(ds, d.location)} a "
                             "route from a plant or warehouse")
        key = (d.location, frm)
        groups[key].append(DeliveryLine(order=lid, product=d.product, qty=round(q, 6), batch=x.get("batch")))
        cf = [c.ship_date for c in ds.confirmations if c.order == lid]
        plan_day[key] = min(plan_day.get(key, date.max), max(day, min(cf, default=day)))
    ids = [dl.id for dl in ds.deliveries]
    made = []
    for (cust, frm), ls in groups.items():
        did = _next(ids, "DL")
        ids.append(did)
        made.append(Delivery(id=did, customer=cust, ship_from=frm, created_on=day, planned_on=plan_day[(cust, frm)],
                             lines=ls))
    msg = "; ".join(f"{m.id} to {_name(ds, m.customer)} from {_name(ds, m.ship_from)}: {plural(len(m.lines), 'line')}"
                    for m in made)
    return (ds.model_copy(update={"deliveries": [*ds.deliveries, *made]}),
            SalesReport(message=f"{msg}. Pick, pack and ship {'them' if len(made) > 1 else 'it'}.",
                        documents=[m.id for m in made]))


def _delivery(ds: Dataset, did: str, open_: bool = True) -> Delivery:
    dl = next((x for x in ds.deliveries if x.id == did), None)
    if dl is None:
        raise SalesError(f"there is no delivery {did}")
    if open_ and dl.issued_on is not None:
        raise SalesError(f"{did} has already been shipped")
    return dl


def pick(ds: Dataset, did: str, lines: list[dict] | None = None) -> tuple[Dataset, SalesReport]:
    """Record what was picked (``[{"order", "picked", "batch"?}]``; None = every line in full)."""
    dl = _delivery(ds, did)
    got = {str(x.get("order")): x for x in lines or []}
    new_lines = []
    for x in dl.lines:
        g = got.get(x.order)
        if lines is not None and g is None:
            new_lines.append(x)
            continue
        q = float(g["picked"]) if g and g.get("picked") is not None else x.qty
        if q < -EPS or q > x.qty + EPS:
            raise SalesError(f"{x.order}: pick between 0 and {_n(x.qty)}")
        new_lines.append(x.model_copy(update={"picked": round(q, 6), "batch": (g or {}).get("batch") or x.batch}))
    short = [x for x in new_lines if x.picked is not None and x.picked < x.qty - EPS]
    new = dl.model_copy(update={"lines": new_lines})
    msg = f"{did} picked" + (": " + ", ".join(f"{x.order} {_n(x.picked or 0)} of {_n(x.qty)}" for x in short)
                             + " (short: ships what was picked)" if short else " in full") + "."
    return ds.model_copy(update={"deliveries": _replace(ds.deliveries, dl, new)}), SalesReport(message=msg,
                                                                                             documents=[did])


def pack(ds: Dataset, did: str, packages: int, gross_kg: float | None = None) -> tuple[Dataset, SalesReport]:
    """Record the packages and gross weight (default: the products' weights)."""
    dl = _delivery(ds, did)
    if packages < 1:
        raise SalesError("a delivery is packed in at least one package")
    if gross_kg is None:
        w = [(ds.product_by_id[x.product].weight_kg, x.picked if x.picked is not None else x.qty) for x in dl.lines]
        gross_kg = round(sum(a * q for a, q in w if a), 3) if any(a for a, _ in w) else None
    new = dl.model_copy(update={"packages": packages, "gross_kg": gross_kg})
    return (ds.model_copy(update={"deliveries": _replace(ds.deliveries, dl, new)}),
            SalesReport(message=f"{did} packed: {plural(packages, 'package')}"
                                + (f", {_n(gross_kg)} kg" if gross_kg else "") + ".", documents=[did]))


def issue(ds: Dataset, did: str, on: date | None = None) -> tuple[Dataset, SalesReport]:
    """Goods issue: the delivery leaves; its sale movements are posted as one material document."""
    dl = _delivery(ds, did)
    day = _today(ds, on)
    ids = movement_ids(ds)
    moves, per = [], {}
    for x in dl.lines:
        d = next((r for r in ds.demand if r.kind is DemandKind.SALES_ORDER and r.id == x.order), None)
        if d is None:
            raise SalesError(f"{x.order} is no longer open (closed or cancelled): take it off {did}")
        h = _header_of(ds, d)
        if h is not None and h.credit_block:
            raise SalesError(f"{h.id} is blocked over the credit limit: release it first")
        q = x.picked if x.picked is not None else x.qty
        if q <= EPS:
            continue
        per[len(moves)] = {"batch": x.batch} if x.batch else {}
        left = ordered_now(ds, d) - delivered(ds, x.order) - q
        moves.append(GoodsMovement(id=next(ids), date=day, type=MovementType.SALE, location=dl.ship_from,
                                   product=x.product, qty=round(q, 6), reference=x.order, counterparty=dl.customer,
                                   final=x.final,
                                   note=f"Delivery {did}" + (", rest cancelled" if x.final and left > EPS else "")))
    if not moves:
        raise SalesError(f"nothing was picked on {did}")
    try:
        out, _, notes = complete(ds, moves, day, per=per)
    except StockError as e:
        raise SalesError(str(e)) from e
    new = dl.model_copy(update={"issued_on": day, "movements": [m.id for m in out]})
    msg = (f"{did} shipped to {_name(ds, dl.customer)} on {_day(day)}: "
           + ", ".join(f"{_n(m.qty)} {_name(ds, m.product)}" + (f" (batch {m.batch})" if m.batch else "") for m in out)
           + "." + (" " + "; ".join(notes) + "." if notes else "") + " It can be invoiced now.")
    return (ds.model_copy(update={"movements": [*ds.movements, *out],
                                  "deliveries": _replace(ds.deliveries, dl, new)}),
            SalesReport(message=msg, documents=[did], movements=[m.id for m in out]))


def proof(ds: Dataset, did: str, on: date | None = None, by: str = "", lines: list[dict] | None = None,
          note: str = "") -> tuple[Dataset, SalesReport]:
    """Proof of delivery: the customer signed for it (``[{"order", "received"}]`` where they signed for less)."""
    dl = _delivery(ds, did, open_=False)
    if dl.issued_on is None:
        raise SalesError(f"{did} has not been shipped yet")
    day = _today(ds, on)
    if day < dl.issued_on:
        raise SalesError(f"{did} left on {_day(dl.issued_on)}: it cannot arrive before")
    got = {str(x.get("order")): x for x in lines or []}
    new_lines, short = [], []
    for x in dl.lines:
        sent = x.picked if x.picked is not None else x.qty
        g = got.get(x.order)
        r = float(g["received"]) if g and g.get("received") is not None else None
        if r is not None and (r < -EPS or r > sent + EPS):
            raise SalesError(f"{x.order}: signed for between 0 and {_n(sent)}")
        if r is not None and r < sent - EPS:
            short.append(f"{_n(sent - r)} {_name(ds, x.product)} on {x.order}")
        new_lines.append(x.model_copy(update={"received": r}))
    new = dl.model_copy(update={"lines": new_lines, "pod_on": day, "pod_by": by[:120], "pod_note": note[:200]})
    msg = f"{did} delivered on {_day(day)}" + (f", signed by {by}" if by else "") + "."
    if short:
        msg += (f" Signed for less: {', '.join(short)}. Agree a return and credit it, or send the rest on a new "
                "order.")
    return (ds.model_copy(update={"deliveries": _replace(ds.deliveries, dl, new)}),
            SalesReport(message=msg, documents=[did]))


def cancel_delivery(ds: Dataset, did: str) -> tuple[Dataset, SalesReport]:
    dl = _delivery(ds, did)
    return (ds.model_copy(update={"deliveries": [x for x in ds.deliveries if x is not dl]}),
            SalesReport(message=f"{did} cancelled: its lines are due to deliver again.", documents=[did]))


# ------------------------------------------------------------------------------------------------ invoices
def _invoice_ids(ds: Dataset) -> list[str]:
    return [i.id for i in ds.invoices]


def _dates(ds: Dataset, customer: str, terms_id: str | None, day: date) -> tuple[str | None, date, date | None, float]:
    t = ds.terms_for(customer, terms_id)
    known = t.id if t.id in ds.payment_terms_by_id else None
    disc_on = day + timedelta(days=t.discount_days) if t.discount > 0 else None
    return known, day + timedelta(days=t.net_days), disc_on, t.discount


def create_invoices(ds: Dataset, orders: list[str] | None = None, on: date | None = None
                    ) -> tuple[Dataset, SalesReport]:
    """Bill what was shipped and not billed (``orders``: only these order lines or order headers; None = all), one
    invoice per customer and payment terms."""
    day = _today(ds, on)
    due = to_bill(ds)
    if orders is not None:
        want = set(orders)
        due = [b for b in due if b.order in want or b.order.split("/")[0] in want]
    if not due:
        raise SalesError("nothing shipped is waiting for an invoice")
    unpriced = [b for b in due if b.price is None]
    if unpriced:
        raise SalesError(f"{unpriced[0].order} has no price: give the order line or the product a price first")
    groups: dict[tuple[str, str | None], list[ToBill]] = defaultdict(list)
    for b in due:
        d = line_record(ds, b.order)
        h = _header_of(ds, d) if d else None
        groups[(b.customer, h.payment_terms if h else None)].append(b)
    ids = _invoice_ids(ds)
    made = []
    for (cust, terms), bs in groups.items():
        iid = _next(ids, "INV")
        ids.append(iid)
        known, due_on, disc_on, disc = _dates(ds, cust, terms, day)
        merged: dict[tuple[str, float], InvoiceLine] = {}
        for b in bs:
            k = (b.order, b.price or 0.0)
            if k in merged:
                x = merged[k]
                merged[k] = x.model_copy(update={"qty": round(x.qty + b.qty, 6), "movements": [*x.movements, *b.movements]})
            else:
                merged[k] = InvoiceLine(order=b.order, product=b.product, qty=b.qty, price=b.price or 0.0,
                                        movements=list(b.movements))
        made.append(Invoice(id=iid, customer=cust, date=day, due_date=due_on, discount_date=disc_on, discount=disc,
                            payment_terms=known, lines=[_rated(ds, cust, x) for x in merged.values()],
                            tax_rate=_tax_rate(ds, cust), tax_split=tax_split(ds, cust)))
    msg = "; ".join(f"{i.id} to {_name(ds, i.customer)}: {_m(ds, i.total)} due {_day(i.due_date)}" for i in made)
    return (ds.model_copy(update={"invoices": [*ds.invoices, *made]}),
            SalesReport(message=msg + ".", documents=[i.id for i in made]))


def _invoice(ds: Dataset, iid: str) -> Invoice:
    inv = next((i for i in ds.invoices if i.id == iid), None)
    if inv is None:
        raise SalesError(f"there is no invoice or credit note {iid}")
    if inv.cancelled:
        raise SalesError(f"{iid} is cancelled")
    return inv


def pay(ds: Dataset, iid: str, amount: float | None = None, on: date | None = None, reference: str = ""
        ) -> tuple[Dataset, SalesReport]:
    """A payment received for an invoice (or paid out for a credit note). Paid in full by the discount date, the cash
    discount is taken: the rest is settled. ``amount`` None = what is owed (less the cash discount when in time)."""
    inv = _invoice(ds, iid)
    day = _today(ds, on)
    left = inv.open
    if left <= 0.005:
        raise SalesError(f"{iid} is already settled")
    in_time = inv.discount > 0 and inv.discount_date is not None and day <= inv.discount_date and not inv.payments
    with_disc = round(inv.total * (1 - inv.discount), 2) if in_time else left
    amt = round(float(amount), 2) if amount is not None else with_disc
    if amt <= 0:
        raise SalesError("a payment needs an amount")
    if amt > left + 0.005:
        raise SalesError(f"{iid} only has {_m(ds, left)} open")
    disc = round(left - amt, 2) if in_time and amt >= with_disc - 0.005 else 0.0
    new = inv.model_copy(update={"payments": [*inv.payments, Payment(date=day, amount=amt, reference=reference[:64],
                                                                     discount=disc)]})
    rest = new.open
    what = "paid out" if inv.kind == "credit_note" else "received"
    msg = (f"{_m(ds, amt)} {what} for {iid} on {_day(day)}" + (f", cash discount {_m(ds, disc)}" if disc else "")
           + ("; settled." if rest <= 0.005 else f"; {_m(ds, rest)} still open."))
    return ds.model_copy(update={"invoices": _replace(ds.invoices, inv, new)}), SalesReport(message=msg,
                                                                                          documents=[iid])


def cancel_invoice(ds: Dataset, iid: str, reason: str = "") -> tuple[Dataset, SalesReport]:
    """Take an invoice back (no payment on it yet): its goods are waiting to be billed again."""
    inv = _invoice(ds, iid)
    if inv.payments:
        raise SalesError(f"{iid} has payments: put it right with a credit note instead")
    if inv.kind == "credit_note":
        rets = {ln.ret for ln in inv.lines if ln.ret}
        returns = [r.model_copy(update={"credit_note": None}) if r.id in rets else r for r in ds.returns]
    else:
        returns = ds.returns
    new = inv.model_copy(update={"cancelled": True, "note": (inv.note + (" · " if inv.note else "")
                                                             + f"Cancelled{': ' + reason if reason else ''}")[:400]})
    return (ds.model_copy(update={"invoices": _replace(ds.invoices, inv, new), "returns": returns}),
            SalesReport(message=f"{iid} cancelled" + (f" ({reason})" if reason else "")
                                + (": its goods are waiting to be billed again." if inv.kind == "invoice" else "."),
                        documents=[iid]))


# ------------------------------------------------------------------------------------------------ returns
def create_return(ds: Dataset, customer: str, product: str, qty: float, *, order: str | None = None,
                  location: str | None = None, reason: str = "", on: date | None = None,
                  stock_type: StockType = StockType.QUALITY, price: float | None = None) -> tuple[Dataset, SalesReport]:
    """Agree a customer return; the goods are expected back at ``location`` (default: where they were shipped from)."""
    if customer not in ds.location_by_id:
        raise SalesError(f"there is no customer {customer!r}")
    if product not in ds.product_by_id:
        raise SalesError(f"there is no product {product!r}")
    if qty <= EPS:
        raise SalesError("a return needs a quantity")
    sold = [m for m in _sales_moves(ds) if m.reference == order] if order else []
    if order:
        d = line_record(ds, order)
        if d is None or d.location != customer or d.product != product:
            raise SalesError(f"{order} is not an order line of {_name(ds, product)} for {_name(ds, customer)}")
        back = sum(r.qty for r in ds.returns if r.order == order)
        shipped = sum(m.qty for m in sold)
        if qty > shipped - back + EPS:
            raise SalesError(f"{_n(shipped - back)} of {order} were shipped and not returned yet")
        p = price if price is not None else net_price(ds, d)
    else:
        p = price if price is not None else ds.selling_price(customer, product)
    if p is None:
        raise SalesError("say what is paid back per unit: there is no price")
    loc = location or (sold[0].location if sold else None)
    if loc is None or ds.location_type(loc) not in STOCKING_LOCATION_TYPES:
        raise SalesError("say which plant or warehouse the goods come back to")
    rid = _next([r.id for r in ds.returns], "RET")
    batch = sold[0].batch if sold else None
    r = ReturnOrder(id=rid, customer=customer, order=order, product=product, qty=qty, price=p, location=loc,
                    reason=reason[:200], created_on=_today(ds, on), stock_type=stock_type, batch=batch)
    return (ds.model_copy(update={"returns": [*ds.returns, r]}),
            SalesReport(message=f"Return {rid}: {_n(qty)} {_name(ds, product)} from {_name(ds, customer)} expected at "
                                f"{_name(ds, loc)}" + (f" ({reason})" if reason else "") + ".", documents=[rid]))


def _ret(ds: Dataset, rid: str) -> ReturnOrder:
    r = next((x for x in ds.returns if x.id == rid), None)
    if r is None:
        raise SalesError(f"there is no return {rid}")
    return r


def receive_return(ds: Dataset, rid: str, qty: float | None = None, on: date | None = None,
                   stock_type: StockType | None = None, batch: str | None = None) -> tuple[Dataset, SalesReport]:
    """The returned goods arrive: a receipt that names the return, into the stock type agreed."""
    r = _ret(ds, rid)
    if r.received_on is not None:
        raise SalesError(f"{rid} has already been received")
    q = float(qty) if qty is not None else r.qty
    if q <= EPS or q > r.qty + EPS:
        raise SalesError(f"receive between 0 and {_n(r.qty)}")
    day = _today(ds, on)
    st = stock_type or r.stock_type
    prod = ds.product_by_id[r.product]
    serials: list[str] = []
    if prod.serial_numbers and r.order:
        out_sn = [s for m in _sales_moves(ds) if m.reference == r.order for s in m.serials]
        back_sn = {s for m in ds.movements if m.type is MovementType.RECEIPT and m.counterparty == r.customer
                   and m.product == r.product for s in m.serials}
        serials = [s for s in out_sn if s not in back_sn][: round(q)]
    m = GoodsMovement(id=next(movement_ids(ds)), date=day, type=MovementType.RECEIPT, location=r.location,
                      product=r.product, qty=round(q, 6), reference=rid, counterparty=r.customer,
                      note=f"Customer return {rid}" + (f": {r.reason}" if r.reason else ""))
    try:
        out, batches, notes = complete(ds, [m], day, batch=batch or r.batch, stock_type=st, serials=serials or None)
    except StockError as e:
        raise SalesError(str(e)) from e
    new = r.model_copy(update={"received_on": day, "received_qty": round(q, 6), "movements": [x.id for x in out],
                               "stock_type": st})
    where = {StockType.QUALITY: "quality inspection", StockType.BLOCKED: "blocked stock",
             StockType.UNRESTRICTED: "stock ready to sell"}[st]
    return (ds.model_copy(update={"movements": [*ds.movements, *out], "batches": [*ds.batches, *batches],
                                  "returns": _replace(ds.returns, r, new)}),
            SalesReport(message=f"{rid}: {_n(q)} {_name(ds, r.product)} back at {_name(ds, r.location)} into {where}"
                                + (f" ({'; '.join(notes)})" if notes else "") + ". Credit it to pay the customer back.",
                        documents=[rid], movements=[x.id for x in out]))


def credit_return(ds: Dataset, rid: str, on: date | None = None) -> tuple[Dataset, SalesReport]:
    """A credit note for a received return: what came back at the price agreed."""
    r = _ret(ds, rid)
    if r.credit_note:
        raise SalesError(f"{rid} has already been credited ({r.credit_note})")
    if r.received_on is None:
        raise SalesError(f"{rid} has not come back yet: receive it first")
    day = _today(ds, on)
    billed = next((i.id for i in ds.invoices if i.kind == "invoice" and not i.cancelled
                   for ln in i.lines if r.order and ln.order == r.order), None)
    cid = _next(_invoice_ids(ds), "CN")
    known, _, _, _ = _dates(ds, r.customer, None, day)
    cn = Invoice(id=cid, kind="credit_note", customer=r.customer, date=day, due_date=day, payment_terms=known,
                 lines=[_rated(ds, r.customer, InvoiceLine(order=r.order, product=r.product,
                                                           qty=r.received_qty or r.qty, price=r.price, ret=rid))],
                 tax_rate=_tax_rate(ds, r.customer), tax_split=tax_split(ds, r.customer), reference=billed,
                 note=f"Return {rid}")
    new = r.model_copy(update={"credit_note": cid})
    return (ds.model_copy(update={"invoices": [*ds.invoices, cn], "returns": _replace(ds.returns, r, new)}),
            SalesReport(message=f"Credit note {cid} for {_name(ds, r.customer)}: {_m(ds, cn.total)}"
                                + (f" against {billed}" if billed else "") + ".", documents=[cid, rid]))


# ------------------------------------------------------------------------------------------------ the view
def _line_view(ds: Dataset, d: DemandRecord, billed: dict[str, float], on_dl: dict[str, float],
               closed: dict[str, ClosedOrder]) -> OrderLineView:
    lid = d.id or ""
    c = closed.get(lid)
    ordered = ordered_now(ds, d)
    done = delivered(ds, lid)
    p = net_price(ds, d)
    cf = [x.date for x in ds.confirmations if x.order == lid]
    promised = max(cf, default=None) if cf else (c.promised_date if c else None)
    base = (p / (1 - d.discount)) if p is not None and d.discount and d.discount < 1 else p
    return OrderLineView(id=lid, product=d.product, qty=ordered, delivered=round(done, 6),
                         invoiced=round(billed.get(lid, 0.0), 6),
                         returned=round(sum(r.received_qty or 0.0 for r in ds.returns if r.order == lid), 6),
                         open=0.0 if c else round(max(0.0, ordered - done), 6), on_delivery=round(on_dl.get(lid, 0.0), 6),
                         date=d.date, promised=promised, ship_from=None if c else ship_point(ds, d), price=p,
                         list_price=None if base is None else round(base, 4), discount=d.discount,
                         value=None if p is None else round(ordered * p, 2), closed=c is not None,
                         cancelled=bool(c and c.cancelled))


def _status(lines: list[OrderLineView], block: bool) -> str:
    if lines and all(x.cancelled and x.delivered <= EPS for x in lines):
        return "cancelled"
    if block and any(not x.closed for x in lines):
        return "credit block"
    shipped = sum(x.delivered for x in lines)
    if lines and all(x.closed or x.open <= EPS for x in lines):
        return "invoiced" if all(x.invoiced >= x.delivered - EPS for x in lines) and shipped > EPS else "delivered"
    return "partly delivered" if shipped > EPS else "open"


def sales_view(ds: Dataset, as_of: date | None = None) -> SalesView:
    """Every order with its lines, quotations, deliveries, invoices and returns, what is due to deliver and to bill, and
    each customer's credit position."""
    day = _today(ds, as_of)
    billed = _billed(ds)
    on_dl = _on_open_deliveries(ds)
    closed = _closed_lines(ds)
    orders = []
    for h in ds.sales_orders:
        lines = [_line_view(ds, d, billed, on_dl, closed) for d in _lines_of(ds, h.id)]
        vals = [x.value for x in lines]
        orders.append(OrderView(id=h.id, customer=h.customer, order_date=h.order_date, customer_ref=h.customer_ref,
                                payment_terms=ds.terms_for(h.customer, h.payment_terms).text(), quotation=h.quotation,
                                credit_block=h.credit_block, credit_note=h.credit_note,
                                confirmation_sent_on=h.confirmation_sent_on, lines=lines,
                                value=None if any(v is None for v in vals) else round(sum(v or 0 for v in vals), 2),
                                status=_status(lines, h.credit_block)))
    for d in ds.demand:      # orders of one line without a header
        if d.kind is DemandKind.SALES_ORDER and d.id and not d.order:
            ln = _line_view(ds, d, billed, on_dl, closed)
            orders.append(OrderView(id=d.id, customer=d.location, order_date=d.date, customer_ref=d.customer_ref,
                                    payment_terms=ds.terms_for(d.location).text(), lines=[ln], value=ln.value,
                                    status=_status([ln], False), header=False))
    quotes = [QuotationView(id=q.id, customer=q.customer, quote_date=q.quote_date, valid_to=q.valid_to,
                            status="expired" if q.status == "open" and q.valid_to < day else q.status,
                            value=round(sum(x.qty * x.price for x in q.lines), 2), lines=len(q.lines), order=q.order)
              for q in ds.quotations]
    billed_moves = _billed_movements(ds)
    dels = []
    for dl in ds.deliveries:
        sent = [(x.picked if x.picked is not None else x.qty) for x in dl.lines]
        short = sum(s - x.received for s, x in zip(sent, dl.lines, strict=True) if x.received is not None)
        dels.append(DeliveryView(id=dl.id, customer=dl.customer, ship_from=dl.ship_from, planned_on=dl.planned_on,
                                 status=dl.status, qty=round(sum(sent), 6), lines=len(dl.lines), packages=dl.packages,
                                 gross_kg=dl.gross_kg, issued_on=dl.issued_on, pod_on=dl.pod_on, short=round(short, 6),
                                 invoiced=bool(dl.movements) and all(m in billed_moves for m in dl.movements)))
    invs = []
    for i in ds.invoices:
        late = (day - i.due_date).days if i.open > 0.005 and i.due_date < day else 0
        st = ("cancelled" if i.cancelled else "paid" if i.open <= 0.005 else "overdue" if late > 0
              else "part paid" if i.payments else "open")
        in_time = i.discount > 0 and i.discount_date is not None and day <= i.discount_date and not i.payments
        invs.append(InvoiceView(id=i.id, kind=i.kind, customer=i.customer, date=i.date, due_date=i.due_date, net=i.net,
                                tax=i.tax, total=i.total, open=i.open, status=st, days_overdue=max(0, late),
                                discount_until=i.discount_date if in_time else None,
                                discount_amount=round(i.total * i.discount, 2) if in_time else 0.0,
                                reminder_level=i.reminder_level, reminded_on=i.reminded_on,
                                reminder_due=_reminder_due(ds, i, day),
                                tax_parts=[TaxPart(name=n, rate=r, base=b, amount=a) for n, r, b, a in i.tax_parts]))
    rets = [ReturnView(id=r.id, customer=r.customer, product=r.product, qty=r.qty, received_qty=r.received_qty,
                       status=r.status, value=round((r.received_qty or r.qty) * r.price, 2), order=r.order,
                       credit_note=r.credit_note) for r in ds.returns]
    custs = []
    names = sorted({o.customer for o in orders} | {c.customer for c in ds.customers} | {i.customer for i in ds.invoices})
    for cu in names:
        c = ds.customer_by_id.get(cu)
        o, u, r = exposure(ds, cu)
        exp = round(o + u + r, 2)
        overdue = round(sum(i.open for i in invs if i.customer == cu and i.kind == "invoice" and i.status == "overdue"), 2)
        custs.append(CustomerRow(customer=cu, credit_limit=c.credit_limit if c else None, open_orders=o, to_bill=u,
                                 receivable=r, exposure=exp, overdue=overdue,
                                 headroom=None if not c or c.credit_limit is None else round(c.credit_limit - exp, 2),
                                 payment_terms=ds.terms_for(cu).text(), blocked=bool(c and c.blocked),
                                 reminder_due=max((i.reminder_due for i in invs if i.customer == cu), default=0)))
    return SalesView(currency=ds.settings.currency, as_of=day, orders=sorted(orders, key=lambda o: o.id, reverse=True),
                     quotations=sorted(quotes, key=lambda q: q.id, reverse=True),
                     deliveries=sorted(dels, key=lambda d: d.id, reverse=True),
                     invoices=sorted(invs, key=lambda i: (i.date, i.id), reverse=True),
                     returns=sorted(rets, key=lambda r: r.id, reverse=True), to_deliver=to_deliver(ds, day),
                     to_bill=to_bill(ds), customers=custs)


# ---- payment reminders (dunning) ----------------------------------------------------------------------------------
def _reminder_due(ds: Dataset, i, day: date) -> int:
    """The payment reminder an unpaid invoice has reached by ``day`` and not had yet: the number of the company's
    reminder days it is overdue by (0: none due)."""
    if i.kind != "invoice" or i.cancelled or i.open <= 0.005 or i.due_date >= day:
        return 0
    reached = sum(1 for d in ds.sales.reminder_days if (day - i.due_date).days >= d)
    return reached if reached > i.reminder_level else 0


def remind(ds: Dataset, customer: str, on: date | None = None, ids: list[str] | None = None) -> tuple[Dataset, SalesReport]:
    """Record a payment reminder to a customer (≈ a dunning run for one customer): every unpaid invoice that has
    reached a reminder it has not had (or only those in ``ids``) goes up to that reminder, sent on ``on``."""
    day = _today(ds, on)
    due = [(i, n) for i in ds.invoices if i.customer == customer and (ids is None or i.id in ids)
           and (n := _reminder_due(ds, i, day))]
    if not due:
        raise SalesError(f"no invoice of {_name(ds, customer)} is due a payment reminder on {_day(day)}")
    upd = {i.id: i.model_copy(update={"reminder_level": n, "reminded_on": day}) for i, n in due}
    level = max(n for _, n in due)
    said = "; ".join(f"{i.id} ({(day - i.due_date).days} days overdue, {_m(ds, i.open)})" for i, _ in due)
    return (ds.model_copy(update={"invoices": [upd.get(i.id, i) for i in ds.invoices]}),
            SalesReport(message=f"Payment reminder {level} to {_name(ds, customer)} on {_day(day)}: {said}.",
                        documents=[i.id for i, _ in due]))


ACTIONS = ("create_order", "add_lines", "release_credit", "send_confirmation", "cancel_order", "create_quotation",
           "win_quotation", "lose_quotation", "create_deliveries", "pick", "pack", "issue", "proof", "cancel_delivery",
           "create_invoices", "pay", "cancel_invoice", "create_return", "receive_return", "credit_return", "remind")


def act(ds: Dataset, action: str, *, id: str | None = None, customer: str | None = None,
        lines: list[dict] | None = None, on: date | None = None, **kw) -> tuple[Dataset, SalesReport]:
    """One order-to-cash action by name (the API's single entry point)."""
    def need(x, what: str):
        if not x:
            raise SalesError(f"say which {what}")
        return x
    if action == "create_order":
        return create_order(ds, need(customer, "customer"), lines or [], order_date=on,
                            customer_ref=kw.get("customer_ref") or "", payment_terms=kw.get("payment_terms"),
                            note=kw.get("note") or "")
    if action == "add_lines":
        return add_lines(ds, need(id, "order"), lines or [])
    if action == "release_credit":
        return release_credit(ds, need(id, "order"), kw.get("by") or "")
    if action == "send_confirmation":
        return send_confirmation(ds, need(id, "order"), on)
    if action == "cancel_order":
        return cancel_order(ds, need(id, "order"), on, kw.get("reason") or "")
    if action == "create_quotation":
        return create_quotation(ds, need(customer, "customer"), lines or [], on=on, valid_to=kw.get("valid_to"),
                                customer_ref=kw.get("customer_ref") or "", payment_terms=kw.get("payment_terms"),
                                note=kw.get("note") or "")
    if action == "win_quotation":
        return win_quotation(ds, need(id, "quotation"), on, kw.get("customer_ref") or "")
    if action == "lose_quotation":
        return lose_quotation(ds, need(id, "quotation"), kw.get("reason") or "")
    if action == "create_deliveries":
        return create_deliveries(ds, lines, on)
    if action == "pick":
        return pick(ds, need(id, "delivery"), lines)
    if action == "pack":
        return pack(ds, need(id, "delivery"), int(kw.get("packages") or 1), kw.get("gross_kg"))
    if action == "issue":
        return issue(ds, need(id, "delivery"), on)
    if action == "proof":
        return proof(ds, need(id, "delivery"), on, kw.get("by") or "", lines, kw.get("note") or "")
    if action == "cancel_delivery":
        return cancel_delivery(ds, need(id, "delivery"))
    if action == "create_invoices":
        return create_invoices(ds, kw.get("orders"), on)
    if action == "pay":
        return pay(ds, need(id, "invoice"), kw.get("amount"), on, kw.get("reference") or "")
    if action == "cancel_invoice":
        return cancel_invoice(ds, need(id, "invoice"), kw.get("reason") or "")
    if action == "create_return":
        return create_return(ds, need(customer, "customer"), need(kw.get("product"), "product"),
                             float(kw.get("qty") or 0), order=kw.get("order"), location=kw.get("location"),
                             reason=kw.get("reason") or "", on=on,
                             stock_type=StockType(kw.get("stock_type") or "quality"), price=kw.get("price"))
    if action == "receive_return":
        st = kw.get("stock_type")
        return receive_return(ds, need(id, "return"), kw.get("qty"), on, StockType(st) if st else None,
                              kw.get("batch"))
    if action == "credit_return":
        return credit_return(ds, need(id, "return"), on)
    if action == "remind":
        return remind(ds, need(customer, "customer"), on, kw.get("orders"))
    raise SalesError(f"unknown action {action!r}")


__all__ = [
    "ACTIONS", "SalesError", "act", "add_lines", "cancel_delivery", "cancel_invoice", "cancel_order", "create_deliveries",
    "create_invoices", "create_order", "create_quotation", "create_return", "credit_return", "exposure", "issue",
    "line_record", "lose_quotation", "net_price", "pack", "pay", "pick", "price", "proof", "receive_return",
    "release_credit", "remind", "sales_view", "send_confirmation", "to_bill", "to_deliver", "win_quotation",
]
