"""Invoice verification, paying suppliers, returns to suppliers and contracts (Phase N, ≈ MIRO, F-53, movement 122,
outline agreements).

* **Supplier invoices** are entered against purchase order lines. Each line is checked when entered (three-way
  match): the quantity against what was received and not yet invoiced, the price against the order's. A difference
  beyond the company's tolerances blocks the invoice for payment, saying why. A quantity block lifts by itself once
  the goods arrive; a price block stays until someone releases the invoice. The same supplier's invoice number is
  never entered twice.
* **Payments** follow the supplier's payment terms; a payment in full by the cash discount date takes the discount.
  A blocked invoice is not paid.
* **Returns** take goods back out of stock against the order line they came on, so the line counts that much less
  received. The supplier either replaces them (the line is open again for them) or credits them: then the order line
  is reduced and a credit memo is expected, entered like an invoice.
* **What is owed to whom**: open invoices per supplier (overdue, due within a week, blocked), and goods received but
  not invoiced yet (≈ the GR/IR account), so the month-end accrual is visible.
* **Contracts**: what was ordered against each contract line and its target, and contracts that ran out or are about
  to.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from ..model import (
    Dataset, GoodsMovement, MovementType, Payment, ReceiptKind, StockType, SupplierInvoice,
    SupplierInvoiceLine, SupplierReturn,
)
from ..plan.costing import contract_for, fx
from .result import (
    ActionReport, ContractLineView, ContractView, InvoiceLineView, PayableRow, PayablesView, SupplierInvoiceView,
    SupplierReturnView, ToInvoice,
)

EPS = 1e-6


class PayablesError(ValueError):
    """An action the data does not allow; the message says why in plain words."""


def _money(v: float, cur: str) -> str:
    return f"{cur} {v:,.2f}"


def _next(ds: Dataset, prefix: str, ids: list[str]) -> str:
    n = 0
    for x in ids:
        m = re.fullmatch(rf"{prefix}-(\d+)", x)
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}-{n + 1:05d}"


# ---- order lines --------------------------------------------------------------------------------------------
class LineInfo:
    """A purchase order line, open or closed: who it is from, what it is, what was ordered and at what price."""

    def __init__(self, id: str, supplier: str, product: str, location: str, ordered: float, price: float | None,
                 po: str | None, currency: str, open_receipt: bool, contract: str | None):
        self.id, self.supplier, self.product, self.location = id, supplier, product, location
        self.ordered, self.price, self.po, self.currency = ordered, price, po, currency
        self.open_receipt, self.contract = open_receipt, contract


def lines_index(ds: Dataset, wanted: set[str] | None = None) -> dict[str, LineInfo]:
    """Every purchase order line, open or closed (or only ``wanted``), by id."""
    from . import _supplier_of
    out: dict[str, LineInfo] = {}
    for c in ds.closed_orders:
        if c.kind == "purchase" and (wanted is None or c.id in wanted):
            po = ds.purchase_order_by_id.get(c.po or "")
            supplier = po.supplier if po else (c.counterparty or "")
            src = c.source_order or {}
            out[c.id] = LineInfo(c.id, supplier, c.product, c.location, c.ordered_qty, c.price, c.po,
                                 (po.currency if po else None) or ds.settings.currency, False, src.get("contract"))
    for r in ds.receipts:
        if r.kind is ReceiptKind.PURCHASE and (wanted is None or r.id in wanted):
            po = ds.purchase_order_by_id.get(r.po or "")
            pu = ds.purchasing_source_by_id.get(r.source or "")
            ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
            price = r.price if r.price is not None else (pu.price_for(ordered) if pu else None)
            cur = (po.currency if po else None) or (ds.price_currency(pu) if pu else None) or ds.settings.currency
            out[r.id] = LineInfo(r.id, _supplier_of(ds, r) or "", r.product, r.location, ordered, price, r.po, cur,
                                 True, r.contract)
    return out


def line_info(ds: Dataset, lid: str) -> LineInfo | None:
    return lines_index(ds, {lid}).get(lid)


def received(ds: Dataset) -> dict[str, float]:
    """Goods received per order line, less what went back to the supplier."""
    out: dict[str, float] = defaultdict(float)
    for m in ds.movements:
        if m.reference and m.type in (MovementType.RECEIPT, MovementType.RETURN):
            out[m.reference] += m.net if m.type is MovementType.RECEIPT else -m.net
    return out


def returned(ds: Dataset) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for m in ds.movements:
        if m.reference and m.type is MovementType.RETURN:
            out[m.reference] += m.net
    return out


def invoiced(ds: Dataset, skip: str | None = None) -> dict[str, float]:
    """Quantity invoiced per order line: invoices less credit memos, none cancelled."""
    out: dict[str, float] = defaultdict(float)
    for inv in ds.supplier_invoices:
        if inv.cancelled or inv.id == skip or not inv.bills_goods:
            continue
        sign = -1.0 if inv.kind == "credit_memo" else 1.0
        for ln in inv.lines:
            out[ln.order] += sign * ln.qty
    return out


def _last_receipt(ds: Dataset) -> dict[str, date]:
    out: dict[str, date] = {}
    for m in ds.movements:
        if m.type is MovementType.RECEIPT and m.reference:
            out[m.reference] = max(out.get(m.reference, m.date), m.date)
    return out


# ---- invoice verification -----------------------------------------------------------------------------------
def _price_block(ds: Dataset, ln: SupplierInvoiceLine, order_price: float | None) -> str | None:
    if order_price is None:
        return None
    tol = ds.purchasing
    over = ln.price - order_price
    if over > order_price * tol.price_tolerance + EPS and over * ln.qty > tol.amount_tolerance + EPS:
        return (f"price: {ln.order} invoiced at {ln.price:,.2f}, the order says {order_price:,.2f} "
                f"({over / order_price:+.1%} each, {over * ln.qty:,.2f} in all)" if order_price else
                f"price: {ln.order} invoiced at {ln.price:,.2f}, the order has no price")
    return None


def _qty_blocks(ds: Dataset, lines: list[SupplierInvoiceLine], skip: str | None = None) -> list[str]:
    got = received(ds)
    billed = invoiced(ds, skip)
    return _quantity_blocks(lines, got, billed)


def _quantity_blocks(lines: list[SupplierInvoiceLine], got: dict[str, float],
                     billed: dict[str, float]) -> list[str]:
    quantities: dict[str, float] = defaultdict(float)
    for ln in lines:
        quantities[ln.order] += ln.qty
    out = []
    for order, qty in quantities.items():
        free = got.get(order, 0.0) - billed.get(order, 0.0)
        if qty > free + EPS:
            out.append(f"quantity: {order} bills {qty:,.0f}; {max(0.0, free):,.0f} received and not yet "
                       f"invoiced")
    return out


def still_blocked(ds: Dataset, inv: SupplierInvoice) -> list[str]:
    """What stands in the way of paying it now: its price blocks, and quantity blocks while the goods are still
    missing (counting every invoice entered before it)."""
    if inv.credit or inv.cancelled or inv.released_on is not None or not inv.blocks:
        return []
    price = [b for b in inv.blocks if b.startswith("price:")]
    if inv.kind == "subsequent_debit":
        return price
    got = received(ds)
    billed: dict[str, float] = defaultdict(float)
    for other in ds.supplier_invoices:
        if other.cancelled or not other.bills_goods or other.id >= inv.id and other.kind == "invoice":
            continue
        sign = -1.0 if other.kind == "credit_memo" else 1.0
        for ln in other.lines:
            billed[ln.order] += sign * ln.qty
    return price + _quantity_blocks(inv.lines, got, billed)


def to_invoice(ds: Dataset) -> list[ToInvoice]:
    got, billed, last = received(ds), invoiced(ds), _last_receipt(ds)
    refs = {lid for lid in set(got) | set(billed) if abs(got.get(lid, 0.0) - billed.get(lid, 0.0)) > EPS}
    index = lines_index(ds, refs)
    out = []
    for lid in sorted(refs):
        q = got.get(lid, 0.0) - billed.get(lid, 0.0)
        li = index.get(lid)
        if li is None:
            continue            # a production order or transfer
        out.append(ToInvoice(order=lid, po=li.po, supplier=li.supplier, product=li.product, location=li.location,
                             received=got.get(lid, 0.0), invoiced=billed.get(lid, 0.0), qty=q, price=li.price,
                             value=round(q * (li.price or 0.0), 2), currency=li.currency, last_receipt=last.get(lid)))
    return out


def enter_invoice(ds: Dataset, supplier: str | None, lines: list[dict] | None, *, on: date | None = None,
                  reference: str = "", tax: float | None = None, kind: str = "invoice", po: str | None = None,
                  return_id: str | None = None, note: str = "", delivery_costs: float = 0.0
                  ) -> tuple[Dataset, ActionReport]:
    """Enter a supplier's invoice (or credit memo). ``lines``: ``{"order": line, "qty"?, "price"?}``; empty with
    ``po``: everything received on that order and not yet invoiced, at the order's prices; empty with
    ``return_id`` (a credit memo): the goods sent back, at the price they were invoiced at (else the order's).
    ``delivery_costs``: freight and other costs billed that the order did not plan. A ``subsequent_debit`` or
    ``subsequent_credit`` corrects the price of what was invoiced: each line gives the difference per unit as
    ``price`` and the quantity it applies to (default: all invoiced on that line so far)."""
    on = on or ds.settings.planning_start
    if kind not in ("invoice", "credit_memo", "subsequent_debit", "subsequent_credit"):
        raise PayablesError(f"{kind} is not a kind of supplier invoice")
    if delivery_costs < 0:
        raise PayablesError("delivery costs cannot be negative")
    if kind.startswith("subsequent"):
        return _subsequent(ds, supplier, lines, kind, on=on, reference=reference, tax=tax, note=note,
                           delivery_costs=delivery_costs)
    credit = kind == "credit_memo"
    ret = None
    if return_id:
        ret = next((r for r in ds.supplier_returns if r.id == return_id), None)
        if ret is None:
            raise PayablesError(f"there is no return {return_id}")
        if ret.credit_memo:
            raise PayablesError(f"{return_id} is already credited by {ret.credit_memo}")
        credit = True
        supplier = supplier or ret.supplier
        if not lines:
            lines = [{"order": ret.order, "qty": ret.qty}]
    if not lines and po:
        open_ = [x for x in to_invoice(ds) if x.po == po and x.qty > EPS]
        if not open_:
            raise PayablesError(f"nothing received on {po} is waiting for an invoice")
        lines = [{"order": x.order, "qty": x.qty} for x in open_]
    if not lines:
        raise PayablesError("say which order lines the invoice is for")
    got_lines: list[SupplierInvoiceLine] = []
    blocks: list[str] = []
    cur = None
    for w in lines:
        li = line_info(ds, w.get("order") or "")
        if li is None:
            raise PayablesError(f"{w.get('order')} is not a purchase order line")
        if supplier and li.supplier != supplier:
            raise PayablesError(f"{li.id} is on an order with {li.supplier}, not {supplier}")
        supplier = li.supplier
        if cur is not None and li.currency != cur:
            raise PayablesError("one invoice is in one currency: enter the other lines on an invoice of their own")
        cur = li.currency
        q = float(w["qty"]) if w.get("qty") is not None else None
        if q is None:
            q = max(0.0, received(ds).get(li.id, 0.0) - invoiced(ds).get(li.id, 0.0))
        if q <= EPS:
            raise PayablesError(f"{li.id}: there is nothing received to invoice; give the quantity billed")
        price = float(w["price"]) if w.get("price") is not None else (
            _invoiced_price(ds, li.id) if credit else None) or li.price
        if price is None:
            raise PayablesError(f"{li.id} has no price on the order: give the price invoiced")
        ln = SupplierInvoiceLine(order=li.id, product=li.product, qty=round(q, 6), price=price)
        got_lines.append(ln)
        if not credit and (b := _price_block(ds, ln, li.price)):
            blocks.append(b)
    assert supplier is not None
    dup = next((i for i in ds.supplier_invoices if reference and i.supplier == supplier and not i.cancelled
                and i.kind == ("credit_memo" if credit else "invoice")
                and i.reference.strip().lower() == reference.strip().lower()), None)
    if dup is not None:
        who = ds.location_by_id[supplier].name if supplier in ds.location_by_id else supplier
        raise PayablesError(f"{who or supplier}'s {dup.reference} is already entered as {dup.id}")
    if not credit:
        blocks = _qty_blocks(ds, got_lines) + blocks
    terms = ds.vendor_terms(supplier)
    net = round(sum(x.amount for x in got_lines) + delivery_costs, 2)
    v = ds.vendor(supplier)
    rate = v.tax_rate if v.tax_rate is not None else ds.purchasing.tax_rate
    tax_amt = round(net * rate, 2) if tax is None else round(float(tax), 2)
    iid = _next(ds, "CM" if credit else "SI", [i.id for i in ds.supplier_invoices])
    inv = SupplierInvoice(
        id=iid, kind="credit_memo" if credit else "invoice", supplier=supplier, reference=reference[:64], date=on,
        due_date=on if credit else on + timedelta(days=terms.net_days),
        discount_date=on + timedelta(days=terms.discount_days) if terms.discount and not credit else None,
        discount=0.0 if credit else terms.discount, currency=None if cur == ds.settings.currency else cur,
        lines=got_lines, delivery_costs=round(delivery_costs, 2), tax=tax_amt, blocks=blocks, return_id=return_id,
        note=note[:400])
    rets = ds.supplier_returns
    if ret is not None:
        rets = [r.model_copy(update={"credit_memo": iid}) if r.id == ret.id else r for r in rets]
    c = cur or ds.settings.currency
    name = ds.location_by_id[supplier].name if supplier in ds.location_by_id else supplier
    their = f" (their {reference})" if reference else ""
    if credit:
        msg = (f"Credit memo {iid} from {name}{their}: {_money(inv.total, c)}"
               + (f" for return {return_id}" if return_id else "") + ".")
    else:
        lines_txt = f"{len(got_lines)} line{'s' if len(got_lines) != 1 else ''}"
        if inv.delivery_costs:
            lines_txt += f" and {_money(inv.delivery_costs, c)} delivery costs"
        msg = f"{iid} from {name}{their}: {_money(inv.total, c)}, {lines_txt}; "
        if blocks:
            msg += "blocked for payment: " + "; ".join(b.split(": ", 1)[1] for b in blocks) + "."
        else:
            msg += (f"matches the order and the goods received; due {inv.due_date.isoformat()}"
                    + (f", {inv.discount:.0%} off if paid by {inv.discount_date.isoformat()}"
                       if inv.discount_date else "") + ".")
    return (ds.model_copy(update={"supplier_invoices": [*ds.supplier_invoices, inv], "supplier_returns": rets}),
            ActionReport(ok=True, message=msg, id=iid))


def _subsequent(ds: Dataset, supplier: str | None, lines: list[dict] | None, kind: str, *, on: date,
                reference: str, tax: float | None, note: str, delivery_costs: float) -> tuple[Dataset, ActionReport]:
    """A subsequent debit or credit (≈ MIRO's subsequent debit/credit): the price of goods already invoiced put
    right, without a quantity. A debit that takes the price beyond the tolerance is blocked like an invoice."""
    debit = kind == "subsequent_debit"
    if not lines:
        raise PayablesError("say which invoiced order lines the price difference is for, and by how much each")
    billed = invoiced(ds)
    taken: dict[str, float] = defaultdict(float)     # per order line, over the lines of this note
    got_lines: list[SupplierInvoiceLine] = []
    blocks: list[str] = []
    cur = None
    for w in lines:
        li = line_info(ds, w.get("order") or "")
        if li is None:
            raise PayablesError(f"{w.get('order')} is not a purchase order line")
        if supplier and li.supplier != supplier:
            raise PayablesError(f"{li.id} is on an order with {li.supplier}, not {supplier}")
        supplier = li.supplier
        if cur is not None and li.currency != cur:
            raise PayablesError("one invoice is in one currency: enter the other lines on an invoice of their own")
        cur = li.currency
        done = billed.get(li.id, 0.0)
        if done <= EPS:
            raise PayablesError(f"{li.id} is not invoiced yet: a subsequent debit or credit corrects an invoice")
        if w.get("price") is None or float(w["price"]) <= 0:
            raise PayablesError(f"{li.id}: give the price difference per unit, more than zero")
        q = float(w["qty"]) if w.get("qty") is not None else done - taken[li.id]
        if q <= EPS or taken[li.id] + q > done + EPS:
            raise PayablesError(f"{li.id}: the difference applies to at most the {done:,.0f} invoiced")
        taken[li.id] += q
        ln = SupplierInvoiceLine(order=li.id, product=li.product, qty=round(q, 6), price=float(w["price"]))
        got_lines.append(ln)
        paid = _invoiced_price(ds, li.id)
        if debit and paid is not None and (b := _price_block(ds, ln.model_copy(update={"price": paid + ln.price}),
                                                             li.price)):
            blocks.append(b)
    assert supplier is not None
    if reference.strip():
        dup = next((i for i in ds.supplier_invoices if i.supplier == supplier and not i.cancelled and i.kind == kind
                    and i.reference.strip().lower() == reference.strip().lower()), None)
        if dup is not None:
            who = ds.location_by_id[supplier].name if supplier in ds.location_by_id else supplier
            raise PayablesError(f"{who or supplier}'s {dup.reference} is already entered as {dup.id}")
    terms = ds.vendor_terms(supplier)
    net = round(sum(x.amount for x in got_lines) + delivery_costs, 2)
    v = ds.vendor(supplier)
    rate = v.tax_rate if v.tax_rate is not None else ds.purchasing.tax_rate
    tax_amt = round(net * rate, 2) if tax is None else round(float(tax), 2)
    iid = _next(ds, "SD" if debit else "SC", [i.id for i in ds.supplier_invoices])
    inv = SupplierInvoice(
        id=iid, kind=kind, supplier=supplier, reference=reference[:64], date=on,
        due_date=on + timedelta(days=terms.net_days) if debit else on, currency=None if cur == ds.settings.currency
        else cur, lines=got_lines, delivery_costs=round(delivery_costs, 2), tax=tax_amt, blocks=blocks,
        note=note[:400])
    c = cur or ds.settings.currency
    name = ds.location_by_id[supplier].name if supplier in ds.location_by_id else supplier
    their = f" (their {reference})" if reference else ""
    what = ", ".join(f"{x.order} {x.price:,.2f} on {x.qty:,.0f}" for x in got_lines)
    msg = (f"Subsequent {'debit' if debit else 'credit'} {iid} from {name}{their}: {_money(inv.total, c)} "
           f"({'more' if debit else 'less'} per unit: {what})")
    msg += ("; blocked for payment: " + "; ".join(b.split(": ", 1)[1] for b in blocks) + ".") if blocks else "."
    return (ds.model_copy(update={"supplier_invoices": [*ds.supplier_invoices, inv]}),
            ActionReport(ok=True, message=msg, id=iid))


def _invoiced_price(ds: Dataset, lid: str) -> float | None:
    """The price a line was last invoiced at, with the subsequent debits and credits since: goods sent back are
    credited at what was paid for them."""
    adjust = 0.0
    for inv in reversed(ds.supplier_invoices):
        if inv.cancelled:
            continue
        for ln in inv.lines:
            if ln.order != lid:
                continue
            if inv.kind == "invoice":
                return round(ln.price + adjust, 6)
            if not inv.bills_goods:
                adjust += ln.price if inv.kind == "subsequent_debit" else -ln.price
    return None


def _invoice(ds: Dataset, iid: str) -> SupplierInvoice:
    inv = next((i for i in ds.supplier_invoices if i.id == iid), None)
    if inv is None:
        raise PayablesError(f"there is no supplier invoice {iid}")
    return inv


def _replace(ds: Dataset, inv: SupplierInvoice) -> Dataset:
    return ds.model_copy(update={"supplier_invoices": [inv if i.id == inv.id else i for i in ds.supplier_invoices]})


def release_invoice(ds: Dataset, iid: str, by: str = "", on: date | None = None,
                    note: str = "") -> tuple[Dataset, ActionReport]:
    inv = _invoice(ds, iid)
    if inv.cancelled:
        raise PayablesError(f"{iid} is cancelled")
    if not inv.blocks or inv.released_on is not None:
        raise PayablesError(f"{iid} is not blocked for payment")
    on = on or ds.settings.planning_start
    upd = {"released_by": by[:200], "released_on": on}
    if note:
        upd["note"] = (inv.note + ("; " if inv.note else "") + note)[:400]
    return (_replace(ds, inv.model_copy(update=upd)),
            ActionReport(ok=True, message=f"{iid} released for payment" + (f" by {by}" if by else "")
                         + f"; due {inv.due_date.isoformat()}.", id=iid))


def pay_invoice(ds: Dataset, iid: str, amount: float | None = None, on: date | None = None,
                reference: str = "") -> tuple[Dataset, ActionReport]:
    """Pay a supplier invoice (or record the refund of a credit memo). Paid in full by the discount date, the cash
    discount is taken."""
    inv = _invoice(ds, iid)
    on = on or ds.settings.planning_start
    cur = inv.currency or ds.settings.currency
    if inv.cancelled:
        raise PayablesError(f"{iid} is cancelled")
    if inv.open <= EPS:
        raise PayablesError(f"{iid} is already settled")
    why = still_blocked(ds, inv)
    if why:
        raise PayablesError(f"{iid} is blocked for payment ({'; '.join(b.split(': ', 1)[1] for b in why)}): "
                            "release it first")
    disc = 0.0
    if not inv.credit and inv.discount and inv.discount_date and on <= inv.discount_date and not inv.payments:
        disc = round(inv.total * inv.discount, 2)
    due = round(inv.open - disc, 2)
    amt = due if amount is None else round(float(amount), 2)
    if amt <= EPS:
        raise PayablesError("the amount must be more than zero")
    if amt > due + 0.005:
        raise PayablesError(f"{_money(amt, cur)} is more than the {_money(due, cur)} still open on {iid}")
    if amt < due - 0.005:
        disc = 0.0          # the discount is for paying in full in time
    new = inv.model_copy(update={"payments": [*inv.payments, Payment(date=on, amount=amt, discount=disc,
                                                                     reference=reference[:64])]})
    verb = "refund received for" if inv.credit else "paid on"
    msg = (f"{_money(amt, cur)} {verb} {iid}" + (f", cash discount {_money(disc, cur)}" if disc else "")
           + ("; settled." if new.open <= 0.005 else f"; {_money(new.open, cur)} still open."))
    return _replace(ds, new), ActionReport(ok=True, message=msg, id=iid)


def cancel_invoice(ds: Dataset, iid: str) -> tuple[Dataset, ActionReport]:
    inv = _invoice(ds, iid)
    if inv.cancelled:
        raise PayablesError(f"{iid} is already cancelled")
    if inv.payments:
        raise PayablesError(f"{iid} has payments against it and cannot be cancelled")
    rets = [r.model_copy(update={"credit_memo": None}) if r.credit_memo == iid else r for r in ds.supplier_returns]
    new = _replace(ds, inv.model_copy(update={"cancelled": True})).model_copy(update={"supplier_returns": rets})
    return new, ActionReport(ok=True, message=f"{iid} cancelled: its lines can be invoiced again.", id=iid)


# ---- returns to the supplier --------------------------------------------------------------------------------
def return_goods(ds: Dataset, order: str, qty: float, *, on: date | None = None, reason: str = "",
                 stock_type: StockType | str | None = None, batch: str | None = None,
                 replace: bool = False) -> tuple[Dataset, ActionReport]:
    """Send goods received on an order line back to the supplier (≈ movement 122). They leave the stock type they
    are in (blocked by default: goods going back are usually held first)."""
    from ..actuals.documents import WORDS, StockError, _settle, _with_openings, complete
    from ..actuals.lots import node_lots
    from ..actuals.stock import before, movement_ids
    on = on or ds.settings.planning_start
    ds = _with_openings(ds)
    li = line_info(ds, order)
    if li is None:
        raise PayablesError(f"{order} is not a purchase order line")
    have = received(ds).get(order, 0.0)
    q = float(qty)
    if q <= EPS:
        raise PayablesError("the quantity must be more than zero")
    if q > have + EPS:
        raise PayablesError(f"{order}: only {have:,.0f} received and not sent back yet")
    st = StockType(stock_type) if stock_type else StockType.BLOCKED
    lots = [lot for lot in node_lots(ds, before(ds, on + timedelta(days=1)), (li.location, li.product))
            if lot.qty > EPS and lot.stock_type is st and (batch is None or lot.batch == batch)]
    if sum(x.qty for x in lots) < q - EPS:
        raise PayablesError(f"only {sum(x.qty for x in lots):,.0f} of {li.product} at {li.location} is {WORDS[st]}"
                            + (f" in batch {batch}" if batch else "")
                            + ": choose where the goods are, or block them first")
    ids = movement_ids(ds)
    moves, left = [], q
    for lot in lots:
        if left <= EPS:
            break
        take = min(left, lot.qty)
        left -= take
        moves.append(GoodsMovement(id=next(ids), date=on, type=MovementType.RETURN, location=li.location,
                                   product=li.product, qty=round(take, 6), reference=order,
                                   counterparty=li.supplier if li.supplier in ds.location_by_id else None,
                                   batch=lot.batch, stock_type=lot.stock_type, note=(reason or "Returned")[:200]))
    try:
        moves, _, notes = complete(ds, moves, on)
    except StockError as e:
        raise PayablesError(str(e)) from e
    rid = _next(ds, "RS", [r.id for r in ds.supplier_returns])
    ret = SupplierReturn(id=rid, supplier=li.supplier, order=order, product=li.product, location=li.location, qty=q,
                         date=on, reason=reason[:200], stock_type=st, batch=batch, replace=replace,
                         movement=moves[0].id)
    receipts = ds.receipts
    tail = ""
    if li.open_receipt:
        rc = next(r for r in receipts if r.id == order)
        target = rc.target_qty
        booked = target - rc.qty
        reversed_ids = {m.reversal_of for m in ds.movements if m.reversal_of}
        active = [(m, (m.date, i)) for i, m in enumerate(ds.movements) if m.reference == order and m.date <= on
                  and not m.reversal_of and m.id not in reversed_ids]
        replacement_ids = {r.movement for r in ds.supplier_returns if r.replace}
        last_final = max((when for m, when in active if m.type is MovementType.RECEIPT and m.final), default=None)
        last_return = max((when for m, when in active if m.id in replacement_ids), default=None)
        final = last_final is not None and (last_return is None or last_final > last_return)
        # A final short receipt cancelled the undelivered remainder. Reopen only what can be replaced,
        # keeping the original quantity for history. Repeated returns keep the same delivery target.
        if replace and final:
            target = min(target, have)
        elif not replace:
            target = max(target - q, EPS)
        # A backdated return is booked into opening stock by _settle below. It also takes back that much
        # booked receipt; a current/future posting stays in the journal until the next roll.
        if on < ds.settings.planning_start:
            booked -= q
        patch = {"qty": max(target - booked, EPS), "ordered_qty": li.ordered if replace else max(li.ordered - q, EPS)}
        if rc.delivery_target_qty is not None or replace:
            patch["delivery_target_qty"] = target
        receipts = [r.model_copy(update=patch) if r.id == order else r for r in receipts]
    if li.open_receipt and not replace:
        # credited: the line was for that much less, so it closes on what is kept
        tail = f" {order} is now for {li.ordered - q:,.0f}; a credit memo is expected."
    elif not replace:
        tail = " A credit memo is expected."
    elif li.open_receipt:
        tail = f" {order} is open again for the {q:,.0f} to be replaced."
    else:
        tail = f" {order} was already closed: the plan orders the replacement if it is still needed."
    name = ds.location_by_id[li.supplier].name if li.supplier in ds.location_by_id else li.supplier
    msg = (f"Return {rid}: {q:,.0f} of {li.product} sent back to {name} from {li.location} on {on.isoformat()}"
           + (f" ({reason})" if reason else "") + "." + tail + ("; " + "; ".join(notes) if notes else ""))
    new = ds.model_copy(update={"movements": [*ds.movements, *moves], "receipts": receipts,
                                "supplier_returns": [*ds.supplier_returns, ret]})
    return _settle(new, {(li.location, li.product)}, on), ActionReport(ok=True, message=msg, id=rid,
                                                                       movements=[m.id for m in moves],
                                                                       doc=moves[0].doc)


# ---- contracts ----------------------------------------------------------------------------------------------
def _ordered_on(ds: Dataset) -> dict[tuple[str, str], tuple[float, float]]:
    """(contract, product) → (quantity, value) on order lines that name the contract, open and closed."""
    out: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in ds.receipts:
        if r.contract:
            q = r.ordered_qty if r.ordered_qty is not None else r.qty
            out[(r.contract, r.product)][0] += q
            out[(r.contract, r.product)][1] += q * (r.price or 0.0)
    for c in ds.closed_orders:
        k = (c.source_order or {}).get("contract")
        if c.kind == "purchase" and k:
            out[(k, c.product)][0] += c.delivered_qty
            out[(k, c.product)][1] += c.delivered_qty * (c.price or 0.0)
    return {k: (v[0], v[1]) for k, v in out.items()}


def contract_views(ds: Dataset, as_of: date) -> list[ContractView]:
    done = _ordered_on(ds)
    out = []
    for k in ds.contracts:
        lines, value, notes = [], 0.0, []
        for ln in k.lines:
            q, v = done.get((k.id, ln.product), (0.0, 0.0))
            value += v
            left = None if ln.target_qty is None else ln.target_qty - q
            if left is not None and left < -EPS:
                notes.append(f"{ln.product}: {-left:,.0f} ordered beyond the {ln.target_qty:,.0f} agreed")
            lines.append(ContractLineView(product=ln.product, price=ln.price, target_qty=ln.target_qty, ordered=q,
                                          left=left))
        used = (k.target_value is not None and value >= k.target_value - EPS) or (
            all(x.left is not None and x.left <= EPS for x in lines))
        if k.target_value is not None and value > k.target_value + EPS:
            notes.append(f"ordered {value:,.0f}, beyond the {k.target_value:,.0f} agreed")
        status = ("expired" if k.valid_to < as_of else "not started" if k.valid_from > as_of
                  else "used up" if used else "active")
        if status == "active" and (k.valid_to - as_of).days <= 30:
            notes.append(f"ends on {k.valid_to.isoformat()}: agree the next one")
        out.append(ContractView(id=k.id, supplier=k.supplier, location=k.location, valid_from=k.valid_from,
                                valid_to=k.valid_to, currency=k.currency or ds.settings.currency,
                                target_value=k.target_value, ordered_value=round(value, 2), status=status, lines=lines,
                                attention=notes, supplier_reference=k.supplier_reference, note=k.note))
    return out


# ---- views --------------------------------------------------------------------------------------------------
def invoice_view(ds: Dataset, inv: SupplierInvoice, as_of: date, got: dict[str, float],
                 billed: dict[str, float]) -> SupplierInvoiceView:
    still = still_blocked(ds, inv)
    if inv.cancelled:
        status = "cancelled"
    elif inv.credit:
        status = "credited" if inv.open <= 0.005 else "credit open"
    elif inv.open <= 0.005:
        status = "paid"
    elif still:
        status = "blocked"
    elif inv.blocks and inv.released_on is not None:
        status = "released"
    else:
        status = "to pay"
    lines = []
    index = lines_index(ds, {ln.order for ln in inv.lines})
    for ln in inv.lines:
        li = index.get(ln.order)
        lines.append(InvoiceLineView(order=ln.order, product=ln.product, qty=ln.qty, price=ln.price, amount=ln.amount,
                                     order_price=li.price if li else None, received=got.get(ln.order, 0.0),
                                     invoiced=billed.get(ln.order, 0.0)))
    overdue = (as_of - inv.due_date).days if status in ("to pay", "released", "blocked") and inv.due_date < as_of \
        else 0
    return SupplierInvoiceView(
        id=inv.id, kind=inv.kind, supplier=inv.supplier, reference=inv.reference, date=inv.date,
        due_date=inv.due_date, discount_date=inv.discount_date, discount=inv.discount,
        currency=inv.currency or ds.settings.currency, net=inv.net, delivery_costs=inv.delivery_costs, tax=inv.tax, total=inv.total, settled=inv.settled,
        open=inv.open, status=status, blocks=inv.blocks, still=still, released_by=inv.released_by,
        released_on=inv.released_on, days_overdue=max(0, overdue), lines=lines, payments=inv.payments,
        return_id=inv.return_id, note=inv.note)


def payables_view(ds: Dataset, as_of: date | None = None) -> PayablesView:
    as_of = as_of or ds.settings.planning_start
    got, billed = received(ds), invoiced(ds)
    invs = [invoice_view(ds, i, as_of, got, billed) for i in ds.supplier_invoices]
    order = {"blocked": 0, "to pay": 1, "released": 1, "credit open": 2, "paid": 3, "credited": 4, "cancelled": 5}
    invs.sort(key=lambda x: (order[x.status], x.due_date, x.id))
    gr = to_invoice(ds)
    rows: dict[str, PayableRow] = {}

    def row(sup: str) -> PayableRow:
        if sup not in rows:
            loc = ds.location_by_id.get(sup)
            rows[sup] = PayableRow(supplier=sup, name=(loc.name if loc else "") or sup, open=0.0, overdue=0.0,
                                   due_soon=0.0, blocked=0.0, not_invoiced=0.0, next_due=None,
                                   terms=ds.vendor_terms(sup).name or ds.vendor_terms(sup).id)
        return rows[sup]

    for x in invs:
        if x.status in ("cancelled", "paid", "credited"):
            continue
        k = fx(ds, x.currency if x.currency != ds.settings.currency else None)
        r = row(x.supplier)
        amt = x.open * k * (-1 if x.kind in ("credit_memo", "subsequent_credit") else 1)
        r.open += amt
        if x.kind in ("invoice", "subsequent_debit"):
            if x.status == "blocked":
                r.blocked += amt
            if x.due_date < as_of:
                r.overdue += amt
            elif (x.due_date - as_of).days <= 7:
                r.due_soon += amt
            if x.status != "blocked" and (r.next_due is None or x.due_date < r.next_due):
                r.next_due = x.due_date
    for g in gr:
        if g.qty > EPS:
            row(g.supplier).not_invoiced += g.value * fx(ds, g.currency if g.currency != ds.settings.currency else None)
    for r in rows.values():
        for f in ("open", "overdue", "due_soon", "blocked", "not_invoiced"):
            setattr(r, f, round(getattr(r, f), 2))
    payables = sorted(rows.values(), key=lambda r: (-r.overdue, -r.open, r.supplier))
    rets = []
    cms = {i.id: i for i in ds.supplier_invoices if not i.cancelled}
    for r in ds.supplier_returns:
        if r.replace:
            li = line_info(ds, r.order)
            status = "replacement due" if li is not None and li.open_receipt else "replaced"
        else:
            status = "credited" if r.credit_memo and r.credit_memo in cms else "to credit"
        rets.append(SupplierReturnView(id=r.id, supplier=r.supplier, order=r.order, product=r.product,
                                       location=r.location, qty=r.qty, date=r.date, reason=r.reason, replace=r.replace,
                                       stock_type=r.stock_type.value, batch=r.batch, status=status,
                                       credit_memo=r.credit_memo))
    return PayablesView(
        invoices=invs, to_invoice=gr, payables=payables, contracts=contract_views(ds, as_of), returns=rets,
        blocked=sum(x.status == "blocked" for x in invs),
        open_value=round(sum(r.open for r in payables), 2), overdue_value=round(sum(r.overdue for r in payables), 2),
        not_invoiced_value=round(sum(r.not_invoiced for r in payables), 2))


__all__ = [
    "PayablesError", "cancel_invoice", "contract_for", "contract_views", "enter_invoice", "invoiced", "line_info",
    "pay_invoice", "payables_view", "received", "release_invoice", "return_goods", "still_blocked", "to_invoice",
]
