"""Several companies in one network (Enterprise 7.3, S/4 guide §17.5): inter-company transfers, their transfer prices,
billing and the group's view of the profit still in stock.

* A **stock transfer** between places of two companies is an inter-company order (≈ the inter-company stock
  transport order): planning moves the goods as it would inside one company, and the company that ships sells them to
  the one that receives at the **transfer price** (:mod:`scp.actuals.transfer_price`).
* **Billing** (≈ the inter-company billing document, billing type IV, and the receiver's invoice receipt): every
  shipment not yet billed is on the billing due list; billing puts the due shipments between one pair of places on
  one GST tax invoice from the seller's series. A transfer between two GST registrations of one company is billed as
  well, at cost: it is a supply between distinct persons (schedule I). A shipment taken back after billing is
  credited on a credit note at the price it was billed at.
* **Books**: each company's stock is valued in its own books (the receiver at the transfer price); the group's books
  keep the goods at what they cost the group. The difference is the profit still in stock between companies, which
  the consolidated accounts take out (≈ the elimination of inter-company profit in consolidation).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from ..actuals.post import origin
from ..actuals.transfer_price import (
    billed,
    crossing,
    entity_of,
    party,
    price,
    registration,
    rule,
    shipments,
    source_of,
)
from ..actuals.valuation import EPS, run_books, standards
from ..model import Dataset, MovementType, ReceiptKind
from ..model.common import Out
from ..model.intercompany import IntercompanyInvoice, IntercompanyLine
from ..model.sales import Payment

_MAX_ROWS = 500
_MAX_LINES = 500                           # lines on one document; more shipments go on further documents


class IntercompanyError(ValueError):
    """A step the data does not allow; the message says why in plain words."""


# ------------------------------------------------------------------------------------------------------- the view
class EntityRow(Out):
    id: str                                # "" = the company itself
    name: str
    tax_id: str
    places: list[str]
    stock: float                           # in its own books, on the day
    sales: float                           # to other companies in the period, at the transfer price
    cost: float                            # what those shipments were worth where they left
    margin: float
    purchases: float                       # from other companies in the period
    billed: float                          # net of credit notes, before tax, in the period
    tax: float
    receivable: float = 0.0                # owed to it by the other companies on the day (tax included)
    payable: float = 0.0                   # it owes the other companies


class ShipmentRow(Out):
    movement: str
    date: date
    order: str
    product: str
    product_name: str
    ship_from: str
    ship_to: str
    seller: str
    buyer: str
    crossing: str                          # entity | registration
    qty: float                             # net of reversals
    cost: float                            # per unit, where it left (the seller's books)
    price: float                           # per unit: billed at, else the transfer price
    basis: str                             # how the price was found
    amount: float
    margin: float
    billed_qty: float
    due_qty: float                         # + to bill, − to credit
    invoices: list[str]


class OrderRow(Out):
    order: str
    product: str
    product_name: str
    ship_from: str
    ship_to: str
    seller: str
    buyer: str
    due_date: date
    ordered: float
    shipped: float
    to_ship: float
    price: float
    basis: str
    value: float                           # of what is still to ship, at the price


class InvoiceLineRow(Out):
    movement: str
    order: str
    product: str
    product_name: str
    hsn: str
    unit: str
    qty: float
    price: float
    net: float
    tax_rate: float
    tax: float


class InvoiceRow(Out):
    id: str
    kind: str
    date: date
    seller: str
    seller_name: str
    seller_gstin: str
    seller_address: str
    buyer: str
    buyer_name: str
    buyer_gstin: str
    buyer_address: str
    ship_from: str
    ship_from_name: str
    ship_to: str
    ship_to_name: str
    place_of_supply: str
    split: str
    lines: list[InvoiceLineRow]
    net: float
    cgst: float
    sgst: float
    igst: float
    tax: float
    total: float
    cancelled: bool
    note: str
    paid: float = 0.0                      # settled between the companies, to the day
    open: float = 0.0


class Consolidation(Out):
    stock_entities: float                  # Σ the companies' own books
    stock_group: float                     # the group's books
    transit_entities: float
    transit_group: float
    unrealised: float                      # profit between companies still in stock or on the way
    differences_entities: float            # price differences booked aside (a standard price at the receiver)
    differences_group: float
    sales: float                           # between companies, to the day
    cost: float
    margin: float
    margin_before: float                   # on goods shipped before go-live (billed by the old system), received since
    realised: float                        # of the margin, what has left the group (sold, used, scrapped)
    cost_of_sales_entities: float
    cost_of_sales_group: float


class IntercompanyView(Out):
    as_of: date
    period_start: date
    period_end: date
    currency: str
    entities: list[EntityRow]
    shipments: list[ShipmentRow]
    orders: list[OrderRow]
    invoices: list[InvoiceRow]
    due: int                               # shipments to bill or credit
    due_value: float
    consolidation: Consolidation
    notes: list[str] = []


def _name(ds: Dataset, oid: str) -> str:
    x = ds.location_by_id.get(oid) or ds.product_by_id.get(oid)
    return (x.name or oid) if x else oid


def _n(q: float) -> str:
    return f"{q:,.0f}" if abs(q - round(q)) < 1e-6 else f"{q:,.2f}"


def _money(ds: Dataset, v: float) -> str:
    return f"{ds.settings.currency} {v:,.2f}"


def _split(ds: Dataset, frm: str, to: str) -> str:
    """CGST and SGST when both registrations are in one state, IGST across (the company's GST split only)."""
    from ..sales import _place
    if ds.sales.tax_split != "gst":
        return ""
    a, b = _place(*registration(ds, frm)), _place(*registration(ds, to))
    return "cgst_sgst" if a and a == b else "igst"


def _state(ds: Dataset, loc: str) -> str:
    from ..sales import _GST_STATES, _place
    code = _place(*registration(ds, loc))
    names = _GST_STATES.get(code)
    return f"{code} {names[0]}" if names else code


def _rate(ds: Dataset, product: str) -> float:
    p = ds.product_by_id.get(product)
    return p.tax_rate if p and p.tax_rate is not None else ds.sales.tax_rate


def _unit(ds: Dataset, product: str) -> str:
    from ..jobwork import uqc
    return uqc(ds, product)


def _period(ds: Dataset, as_of: date, start: date | None, end: date | None) -> tuple[date, date]:
    """The financial year to date (from April with the rupee, as Indian books keep it; else from January)."""
    if start is None:
        april = ds.settings.currency == "INR"
        y = as_of.year - (1 if april and as_of.month < 4 else 0)
        start = date(y, 4 if april else 1, 1)
    return start, end or as_of


def _paise(v: float) -> float:
    """A sum of amounts each rounded to the paisa: what is left under a few paise is rounding."""
    return 0.0 if abs(v) < 0.05 else round(v, 2)


def _row(ds: Dataset, inv: IntercompanyInvoice) -> InvoiceRow:
    s, b = party(ds, inv.seller), party(ds, inv.buyer)
    lines = [InvoiceLineRow(movement=ln.movement, order=ln.order, product=ln.product,
                            product_name=_name(ds, ln.product),
                            hsn=(ds.product_by_id[ln.product].hsn if ln.product in ds.product_by_id else ""),
                            unit=_unit(ds, ln.product), qty=ln.qty, price=ln.price, net=ln.net, tax_rate=ln.tax_rate,
                            tax=ln.tax) for ln in inv.lines]
    tax = inv.tax
    half = round(tax / 2, 2)
    return InvoiceRow(
        id=inv.id, kind=inv.kind, date=inv.date, seller=inv.seller, seller_name=s.name,
        seller_gstin=registration(ds, inv.ship_from)[0], seller_address=s.address, buyer=inv.buyer,
        buyer_name=b.name, buyer_gstin=registration(ds, inv.ship_to)[0], buyer_address=b.address,
        ship_from=inv.ship_from, ship_from_name=_name(ds, inv.ship_from), ship_to=inv.ship_to,
        ship_to_name=_name(ds, inv.ship_to), place_of_supply=_state(ds, inv.ship_to), split=inv.split, lines=lines,
        net=inv.net, cgst=half if inv.split == "cgst_sgst" else 0.0,
        sgst=round(tax - half, 2) if inv.split == "cgst_sgst" else 0.0, igst=tax if inv.split == "igst" else 0.0,
        tax=tax, total=round(inv.net + tax, 2), cancelled=inv.cancelled, note=inv.note,
        paid=round(sum(p.amount + p.discount for p in inv.payments), 2), open=inv.open)


def _day_of(ds: Dataset, as_of: date | None) -> date:
    return as_of or max([ds.settings.planning_start, *(m.date for m in ds.movements),
                         *(i.date for i in ds.intercompany_invoices),
                         *(p.date for i in ds.intercompany_invoices for p in i.payments)])


def view(ds: Dataset, as_of: date | None = None, period_start: date | None = None,
         period_end: date | None = None) -> IntercompanyView:
    day = _day_of(ds, as_of)
    p0, p1 = _period(ds, day, period_start, period_end)
    eb, std = run_books(ds, day, "entity")
    gb, _ = run_books(ds, day, "group")
    bills = billed(ds)
    on_inv: dict[str, list[str]] = defaultdict(list)
    for inv in ds.intercompany_invoices:
        if not inv.cancelled:
            for ln in inv.lines:
                if inv.id not in on_inv[ln.movement]:
                    on_inv[ln.movement].append(inv.id)

    journal = [m for m in ds.movements if m.date <= day]
    kinds = {r.id: r.kind.value for r in ds.receipts} | {c.id: c.kind for c in ds.closed_orders}
    rows: list[ShipmentRow] = []
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    due_value = 0.0
    for m, to, q in shipments(ds, journal):
        kind = crossing(ds, m.location, to)
        seller, buyer = entity_of(ds, m.location), entity_of(ds, to)
        cost_each = eb.at_move.get(m.id, 0.0)
        bq, bp = bills.get(m.id, (0.0, None))
        if bp is not None and bq > EPS:
            each, basis = bp, "as billed"
        else:
            each, basis = price(ds, std, m.location, to, m.product, m.date)
        due = round(q - bq, 6)
        if abs(due) > EPS:
            due_value += due * each
        rows.append(ShipmentRow(
            movement=m.id, date=m.date, order=m.reference or "", product=m.product, product_name=_name(ds, m.product),
            ship_from=m.location, ship_to=to, seller=seller, buyer=buyer, crossing=kind, qty=round(q, 6),
            cost=round(cost_each, 4), price=round(each, 4), basis=basis, amount=round(q * each, 2),
            margin=round(q * (each - cost_each), 2) if kind == "entity" else 0.0, billed_qty=round(bq, 6),
            due_qty=due, invoices=on_inv.get(m.id, [])))
        if kind == "entity" and p0 <= m.date <= p1:
            sums[seller]["sales"] += q * each
            sums[seller]["cost"] += q * cost_each
            sums[buyer]["purchases"] += q * each
    for inv in ds.intercompany_invoices:
        if not inv.cancelled and p0 <= inv.date <= p1:
            sums[inv.seller]["billed"] += inv.sign * inv.net
            sums[inv.seller]["tax"] += inv.sign * inv.tax
        if not inv.cancelled and inv.date <= day and inv.seller != inv.buyer:
            left = inv.total - sum(p.amount + p.discount for p in inv.payments if p.date <= day)
            sums[inv.seller]["receivable"] += inv.sign * left
            sums[inv.buyer]["payable"] += inv.sign * left

    stock_by: dict[str, float] = defaultdict(float)
    places: dict[str, list[str]] = defaultdict(list)
    for (loc, _p), n in eb.nodes.items():
        stock_by[entity_of(ds, loc)] += n.value
    for lo in ds.locations:
        if lo.type.value not in ("supplier", "customer"):
            places[lo.entity or ""].append(lo.id)
    ids = ["", *(e.id for e in ds.entities)]
    ents = []
    for eid in ids:
        pa, sm = party(ds, eid), sums.get(eid, {})
        ents.append(EntityRow(id=eid, name=pa.name, tax_id=pa.tax_id, places=sorted(places.get(eid, [])),
                              stock=round(stock_by.get(eid, 0.0), 2), sales=round(sm.get("sales", 0.0), 2),
                              cost=round(sm.get("cost", 0.0), 2),
                              margin=round(sm.get("sales", 0.0) - sm.get("cost", 0.0), 2),
                              purchases=round(sm.get("purchases", 0.0), 2), billed=round(sm.get("billed", 0.0), 2),
                              tax=round(sm.get("tax", 0.0), 2), receivable=round(sm.get("receivable", 0.0), 2),
                              payable=round(sm.get("payable", 0.0), 2)))

    orders = []
    shipped: dict[str, float] = defaultdict(float)
    got: dict[str, float] = defaultdict(float)
    for m in ds.movements:
        if m.type is MovementType.TRANSFER_OUT and m.reference:
            shipped[m.reference] += m.net
        elif m.type is MovementType.RECEIPT and m.reference:
            got[m.reference] += m.net
    for rc in ds.receipts:
        if rc.kind is not ReceiptKind.TRANSFER:
            continue
        frm = origin(ds, rc)
        if not frm or not crossing(ds, frm, rc.location):
            continue
        ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
        left = max(0.0, ordered - max(shipped.get(rc.id, 0.0), got.get(rc.id, 0.0)))
        if left <= EPS:
            continue
        each, basis = price(ds, std, frm, rc.location, rc.product, rc.start_date or rc.due_date)
        orders.append(OrderRow(order=rc.id, product=rc.product, product_name=_name(ds, rc.product), ship_from=frm,
                               ship_to=rc.location, seller=entity_of(ds, frm), buyer=entity_of(ds, rc.location),
                               due_date=rc.due_date, ordered=ordered, shipped=round(shipped.get(rc.id, 0.0), 6),
                               to_ship=round(left, 6), price=each, basis=basis, value=round(left * each, 2)))

    def tot(b) -> tuple[float, float]:
        return (sum(n.value for n in b.nodes.values()), sum(v for q, v in b.shipped.values() if q > EPS))
    sent = {m.reference for m in journal if m.type is MovementType.TRANSFER_OUT and m.reference}
    early_moves = [m for m in journal if m.type is MovementType.RECEIPT and not m.reversal_of and m.reference
                   and m.reference not in sent and kinds.get(m.reference) == "transfer"
                   and crossing(ds, source_of(ds, m) or "", m.location) == "entity"]
    before = sum(m.net * (price(ds, std, source_of(ds, m) or "", m.location, m.product, m.date)[0]
                          - gb.node(m.location, m.product).standard) for m in early_moves)
    se, te = tot(eb)
    sg, tg = tot(gb)
    unreal = (se + te) - (sg + tg)
    de, dg = sum(x.amount for x in eb.diffs), sum(x.amount for x in gb.diffs)
    margin = eb.ic_sales - eb.ic_cost
    cons = Consolidation(
        stock_entities=round(se, 2), stock_group=round(sg, 2), transit_entities=round(te, 2),
        transit_group=round(tg, 2), unrealised=round(unreal, 2), differences_entities=round(de, 2),
        differences_group=round(dg, 2), sales=round(eb.ic_sales, 2), cost=round(eb.ic_cost, 2),
        margin=round(margin, 2), margin_before=round(before, 2),
        realised=_paise(margin + before - unreal - (de - dg)),
        cost_of_sales_entities=round(eb.cogs, 2), cost_of_sales_group=round(gb.cogs, 2))

    notes = []
    if not ds.entities:
        notes.append("One company: add the group's other companies under Companies of the group and give their places "
                     "to them. Transfers between GST registrations of this company are billed all the same.")
    missing = sorted({(r.seller, r.buyer, r.product) for r in rows
                      if r.crossing == "entity" and r.basis.startswith("at cost: no transfer price")})
    for s, b, p in missing[:10]:
        notes.append(f"No transfer price from {party(ds, s).name} to {party(ds, b).name} for {_name(ds, p)}: it moves "
                     "at cost, with no profit to the seller.")
    early = sorted({m.reference or "" for m in early_moves})
    if early:
        notes.append(f"{', '.join(early[:5])} came from another company with no shipment in the journal (on the way "
                     "at go-live): in the books at the transfer price, and not billed here.")
    if abs(de - dg) > 0.005:
        notes.append(f"{_money(ds, de - dg)} of transfer-price profit is in price differences: the receiving place "
                     "values the product at its standard price.")
    rows.sort(key=lambda r: (r.date, r.movement), reverse=True)
    due_n = sum(1 for r in rows if abs(r.due_qty) > EPS)
    invs = sorted(ds.intercompany_invoices, key=lambda i: (i.date, i.id), reverse=True)
    return IntercompanyView(
        as_of=day, period_start=p0, period_end=p1, currency=ds.settings.currency, entities=ents,
        shipments=rows[:_MAX_ROWS], orders=sorted(orders, key=lambda o: (o.due_date, o.order)),
        invoices=[_row(ds, i) for i in invs[:_MAX_ROWS]], due=due_n, due_value=round(due_value, 2),
        consolidation=cons, notes=notes)


# ---------------------------------------------------------------------------------------------------- the actions
class IntercompanyReport(Out):
    message: str
    invoices: list[str] = []


def _prefix(ds: Dataset, eid: str) -> str:
    e = ds.entity_by_id.get(eid) if eid else None
    if e is not None and e.invoice_prefix:
        return e.invoice_prefix
    return f"IC-{eid}/"[:11] if eid else "IC/"


def _next_id(ds: Dataset, eid: str, taken: set[str]) -> str:
    pre = _prefix(ds, eid)
    n = max((int(i.id[len(pre):]) for i in ds.intercompany_invoices
             if i.id.startswith(pre) and i.id[len(pre):].isdigit()), default=0) + 1
    while f"{pre}{n:04d}" in taken:
        n += 1
    out = f"{pre}{n:04d}"
    if len(out) > 16:
        raise IntercompanyError(f"invoice numbers starting {pre} are longer than GST's 16 characters: shorten the "
                                "company's invoice prefix")
    return out


def bill(ds: Dataset, on: date | None = None, movements: list[str] | None = None, invoice_id: str | None = None,
         note: str = "") -> tuple[Dataset, IntercompanyReport]:
    """Bill what is due: the shipments not yet billed up to ``on`` (default: the planning start), one invoice per
    seller, buyer and pair of places, and a credit note for what was billed and then taken back. ``movements``: only
    these shipments. ``invoice_id``: the number, when there is one document to make."""
    on = on or ds.settings.planning_start
    journal = [m for m in ds.movements if m.date <= on]
    bills = billed(ds)
    want = set(movements) if movements else None
    std = standards(ds)
    groups: dict[tuple, list[IntercompanyLine]] = defaultdict(list)
    for m, to, q in shipments(ds, journal):
        if want is not None and m.id not in want:
            continue
        bq, bp = bills.get(m.id, (0.0, None))
        due = round(q - bq, 6)
        if abs(due) <= EPS:
            continue
        if due > 0:
            each = price(ds, std, m.location, to, m.product, m.date)[0]
            kind = "invoice"
        else:
            each = bp if bp is not None else price(ds, std, m.location, to, m.product, m.date)[0]
            kind = "credit_note"
        key = (kind, entity_of(ds, m.location), entity_of(ds, to), m.location, to)
        groups[key].append(IntercompanyLine(movement=m.id, order=m.reference or m.id, product=m.product, qty=abs(due),
                                            price=round(each, 4), tax_rate=_rate(ds, m.product)))
    if want is not None:
        unknown = want - {m.id for m, _t, _q in shipments(ds, journal)}
        if unknown:
            raise IntercompanyError(f"{', '.join(sorted(unknown)[:5])} is no shipment between two companies or "
                                    f"registrations up to {on.isoformat()}")
    if not groups:
        raise IntercompanyError("nothing is due: every shipment between companies or registrations is billed")
    docs = [(k, lines[i:i + _MAX_LINES]) for k, lines in sorted(groups.items())
            for i in range(0, len(lines), _MAX_LINES)]
    if invoice_id and len(docs) > 1:
        raise IntercompanyError(f"that makes {len(docs)} documents: give no number, or bill one pair of places")
    taken = {i.id for i in ds.intercompany_invoices}
    made: list[IntercompanyInvoice] = []
    for (kind, seller, buyer, frm, to), lines in docs:
        iid = (invoice_id or "").strip() or _next_id(ds, seller, taken)
        if len(iid) > 16:
            raise IntercompanyError("an invoice number has 1 to 16 characters")
        if iid in taken:
            raise IntercompanyError(f"invoice {iid} already exists")
        taken.add(iid)
        made.append(IntercompanyInvoice(id=iid, kind=kind, date=on, seller=seller, buyer=buyer, ship_from=frm,
                                        ship_to=to, split=_split(ds, frm, to), lines=lines, note=note))
    new = ds.model_copy(update={"intercompany_invoices": [*ds.intercompany_invoices, *made]})
    parts = []
    for inv in made:
        word = "credit note" if inv.kind == "credit_note" else "invoice"
        parts.append(f"{word} {inv.id} from {party(ds, inv.seller).name} to {party(ds, inv.buyer).name}: "
                     f"{_money(ds, inv.net)} and tax {_money(ds, inv.tax)}")
    return new, IntercompanyReport(message="Billed: " + "; ".join(parts) + ".", invoices=[i.id for i in made])


def cancel(ds: Dataset, iid: str) -> tuple[Dataset, IntercompanyReport]:
    """Cancel an inter-company invoice or credit note: its shipments are due again."""
    inv = next((i for i in ds.intercompany_invoices if i.id == iid), None)
    if inv is None:
        raise IntercompanyError(f"there is no inter-company invoice {iid}")
    if inv.cancelled:
        raise IntercompanyError(f"{iid} is already cancelled")
    later = [i.id for i in ds.intercompany_invoices if not i.cancelled and i.kind == "credit_note"
             and inv.kind == "invoice" and i.date >= inv.date and i.id != iid
             and {ln.movement for ln in i.lines} & {ln.movement for ln in inv.lines}]
    if later:
        raise IntercompanyError(f"{', '.join(later)} credits shipments on {iid}: cancel it first")
    if inv.payments:
        raise IntercompanyError(f"{iid} has been settled in part or in full: it cannot be cancelled")
    new = ds.model_copy(update={"intercompany_invoices": [i.model_copy(update={"cancelled": True}) if i.id == iid
                                                          else i for i in ds.intercompany_invoices]})
    return new, IntercompanyReport(message=f"{iid} cancelled: its shipments are on the billing due list again.",
                                   invoices=[iid])


def pay(ds: Dataset, iid: str, amount: float | None = None, on: date | None = None, reference: str = ""
        ) -> tuple[Dataset, IntercompanyReport]:
    """Settle an inter-company invoice: the buyer pays the seller (for a credit note, the seller pays back).
    ``amount`` None = what is still open."""
    inv = next((i for i in ds.intercompany_invoices if i.id == iid), None)
    if inv is None:
        raise IntercompanyError(f"there is no inter-company invoice {iid}")
    if inv.cancelled:
        raise IntercompanyError(f"{iid} is cancelled")
    if inv.seller == inv.buyer:
        raise IntercompanyError(f"{iid} is between two registrations of one company: nothing to settle")
    left = inv.open
    if left <= 0.005:
        raise IntercompanyError(f"{iid} is already settled")
    amt = left if amount is None else round(float(amount), 2)
    if not math.isfinite(amt) or amt <= 0:
        raise IntercompanyError("a payment needs an amount above zero")
    if amt > left + 0.005:
        raise IntercompanyError(f"{iid} only has {_money(ds, left)} open")
    day = on or _day_of(ds, None)
    if day < inv.date:
        raise IntercompanyError(f"{iid} is dated {inv.date.isoformat()}: it cannot be paid before")
    new = inv.model_copy(update={"payments": [*inv.payments, Payment(date=day, amount=amt, reference=reference[:64])]})
    payer, payee = (inv.buyer, inv.seller) if inv.kind == "invoice" else (inv.seller, inv.buyer)
    rest = new.open
    msg = (f"{_money(ds, amt)} paid by {party(ds, payer).name} to {party(ds, payee).name} for {iid}"
           + ("; settled." if rest <= 0.005 else f"; {_money(ds, rest)} still open."))
    return (ds.model_copy(update={"intercompany_invoices": [new if i.id == iid else i
                                                             for i in ds.intercompany_invoices]}),
            IntercompanyReport(message=msg, invoices=[iid]))


def missing_prices(ds: Dataset) -> list[tuple[str, str, str, str]]:
    """Open transfers between two companies with no transfer price rule: (order, seller, buyer, product)."""
    out = []
    for rc in ds.receipts:
        if rc.kind is not ReceiptKind.TRANSFER:
            continue
        frm = origin(ds, rc)
        if not frm or crossing(ds, frm, rc.location) != "entity":
            continue
        s, b = entity_of(ds, frm), entity_of(ds, rc.location)
        if rule(ds, s, b, rc.product, rc.start_date or rc.due_date) is None:
            out.append((rc.id, s, b, rc.product))
    return out


__all__ = ["Consolidation", "EntityRow", "IntercompanyError", "IntercompanyReport", "IntercompanyView", "InvoiceRow",
           "OrderRow", "ShipmentRow", "bill", "cancel", "missing_prices", "pay", "view"]
