"""Stock in the books (Enterprise 6.2): every place's stock valued from the movement journal and the supplier invoices.

A product's price control (S/4 MBEW-VPRSV) decides how:

* **standard** (S): stock is valued at the planned unit value, the one planning uses. A goods receipt at another price,
  an invoice that differs from the order, freight billed on it: all of it is a price difference, booked aside.
* **moving average** (V): a purchase receipt comes in at the order's price, a transfer at what it was worth where it
  left, production at its planned value; every issue goes out at the average. An invoice that differs from the order
  moves the average by the part of the difference still in stock; the part already gone is a price difference.

With several companies in the network (Enterprise 7.3) each keeps its own books: a transfer to another company comes
in at the transfer price (what it was billed at, else the rule's price), and the company that shipped it sold it at
that price. The group's books (``books="group"``) keep the transfer at what it was worth where it left, so the
difference between the two is the profit still in stock between companies.

Planning is not changed by any of this: it keeps valuing stock at the planned unit value (holding cost, lot sizes),
as S/4 MRP does whatever the price control.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..model import Dataset, GoodsMovement, MovementType, PriceControl
from ..model.common import Out
from ..network import Node, build_graph
from ..plan.costing import freight_per_unit, fx, handling, roll_up
from ..plan.leadtime import supplier_lane
from ..purchasing.payables import lines_index
from .stock import before
from .transfer_price import crossing, entity_of, price, shipment_prices, source_of

EPS = 1e-9
OUT_TYPES = {MovementType.ISSUE, MovementType.SALE, MovementType.TRANSFER_OUT, MovementType.SCRAP, MovementType.RETURN}


class ValuationRow(Out):
    location: str
    entity: str = ""                       # the company of the group it belongs to ("" = the company itself)
    product: str
    control: PriceControl
    qty: float
    value: float
    price: float | None                   # the value per unit now (moving average, or the standard)
    standard: float                        # the planned unit value
    changes: int                           # postings that moved the moving average


class ValuationEntry(Out):
    date: date
    location: str
    product: str
    what: str                              # receipt, issue, invoice, … in words
    reference: str | None
    qty: float                             # signed: + into stock
    amount: float                          # change in stock value
    price_before: float | None
    price_after: float | None


class PriceDifference(Out):
    date: date
    location: str
    product: str
    reference: str | None                  # the invoice, receipt or movement
    amount: float                          # + cost more than the stock took
    why: str


class ValuationView(Out):
    as_of: date
    currency: str
    control: PriceControl                  # the company's
    rows: list[ValuationRow]
    entries: list[ValuationEntry]          # the postings that changed stock value, latest first (capped)
    differences: list[PriceDifference]     # booked aside, latest first
    total_value: float
    total_differences: float
    cost_of_sales: float                   # value of what was sold, at what it was worth when it left
    count_differences: float               # value of count differences (+ found)
    scrapped: float
    books: str = "entity"                  # entity: each company's own books; group: transfers at what left
    intercompany_sales: float = 0.0        # shipped to other companies, at the transfer price
    intercompany_cost: float = 0.0         # what those shipments were worth where they left
    in_transit: float = 0.0                # shipped and not yet received, at what it will come in at
    notes: list[str] = []


@dataclass
class _Node:
    control: PriceControl
    standard: float
    qty: float = 0.0
    value: float = 0.0
    last: float | None = None              # the last price, kept through zero and negative stock
    changes: int = 0

    @property
    def price(self) -> float:
        if self.control is PriceControl.STANDARD:
            return self.standard
        if self.qty > EPS:
            return self.value / self.qty
        return self.last if self.last is not None else self.standard


@dataclass
class _Line:
    """A purchase order line through time: received, invoiced, and invoiced ahead of the goods at what price."""
    price: float                           # what a unit lands at: the order's price, duty, freight and handling
    base: float = 0.0                      # the order's price, company currency
    duty: float = 0.0                      # duty rate on the price
    received: float = 0.0
    invoiced: float = 0.0
    ahead: list[list[float]] = field(default_factory=list)   # [qty, price] invoiced before the goods came


def control_of(ds: Dataset, product: str) -> PriceControl:
    p = ds.product_by_id.get(product)
    return (p.price_control if p and p.price_control else None) or ds.execution.price_control


def standards(ds: Dataset) -> dict[Node, float]:
    """The planned unit value of every product at every place (what planning values stock at)."""
    try:
        return dict(roll_up(ds, build_graph(ds)).unit_value)
    except Exception:                      # a network that cannot be built yet: the product's own figures
        return {}


class _Books:
    def __init__(self, ds: Dataset, std: dict[Node, float]):
        self.ds = ds
        self.std = std
        self.nodes: dict[Node, _Node] = {}
        self.entries: list[ValuationEntry] = []
        self.diffs: list[PriceDifference] = []
        self.cogs = self.counts = self.scrapped = 0.0
        self.at_move: dict[str, float] = {}           # movement id → value per unit it was posted at
        self.shipped: dict[str, list[float]] = defaultdict(list)   # transfer → [qty, value] that left
        self.ic_price: dict[str, float] = {}          # shipment to another company → its transfer price
        self.entity_books = False                     # each company's own books (several companies)
        self.ic_sales = self.ic_cost = 0.0
        self.took: dict[str, tuple[float, float]] = {}   # transfer receipt → (qty, value per unit) it took off the road
        self.returns = {r.id: r.order or "" for r in ds.returns}   # a customer's return → the order line it was sold on
        self.sold_at: dict[str, float] = {}           # sales order line → value per unit its goods last left at

    def node(self, loc: str, prod: str) -> _Node:
        n = self.nodes.get((loc, prod))
        if n is None:
            p = self.ds.product_by_id.get(prod)
            st = self.std.get((loc, prod))
            if st is None:
                st = (p.standard_cost if p and p.standard_cost is not None else 0.0)
            n = self.nodes[(loc, prod)] = _Node(control_of(self.ds, prod), float(st))
        return n

    def diff(self, day: date, loc: str, prod: str, ref: str | None, amount: float, why: str) -> None:
        if abs(amount) > 0.005:
            self.diffs.append(PriceDifference(date=day, location=loc, product=prod, reference=ref,
                                              amount=round(amount, 2), why=why))

    def book(self, day: date, loc: str, prod: str, what: str, ref: str | None, qty: float, amount: float,
             before: float | None, moves: bool = True) -> None:
        """``moves``: False for goods leaving at the average, which moves it only by the rounding to paise."""
        n = self.node(loc, prod)
        after = n.price
        if n.control is PriceControl.MOVING_AVERAGE and moves and before is not None and abs(after - before) > 1e-6:
            n.changes += 1
        self.entries.append(ValuationEntry(date=day, location=loc, product=prod, what=what, reference=ref,
                                           qty=round(qty, 6), amount=round(amount, 2),
                                           price_before=round(before, 4) if before is not None else None,
                                           price_after=round(after, 4)))

    # -- into stock ------------------------------------------------------------------------------------------
    def into(self, day: date, loc: str, prod: str, q: float, unit: float, what: str, ref: str | None,
             why: str = "") -> float:
        """``q`` units in, costing ``unit`` each. Returns the value per unit the stock took them at."""
        n = self.node(loc, prod)
        before = n.price
        if n.control is PriceControl.STANDARD:
            self.diff(day, loc, prod, ref, (unit - n.standard) * q, why or f"{what} at {unit:.2f} against the standard")
            amount = round(q * n.standard, 2)
            n.qty += q
            n.value += amount
            self.book(day, loc, prod, what, ref, q, amount, before)
            return n.standard
        # moving average: what settles negative stock comes in at the price it went out at
        settle = min(q, max(0.0, -n.qty))
        if settle > EPS:
            self.diff(day, loc, prod, ref, (unit - before) * settle,
                      f"{what}: {settle:g} settled stock that had gone below zero at {before:.2f}")
        amount = round(settle * before + (q - settle) * unit, 2)
        if n.qty + q <= EPS:                   # still none (or below zero): valued at the price it had
            amount = round((n.qty + q) * before, 2) - n.value
        n.qty += q
        n.value += amount
        n.last = n.price
        self.book(day, loc, prod, what, ref, q, amount, before)
        return amount / q if q > EPS else unit

    # -- out of stock ----------------------------------------------------------------------------------------
    def out(self, day: date, loc: str, prod: str, q: float, what: str, ref: str | None,
            unit: float | None = None) -> float:
        """``q`` units out, at the current price (or ``unit``: a return to the supplier leaves at the order's price).
        Returns the value that left."""
        n = self.node(loc, prod)
        before = n.price
        if n.control is PriceControl.STANDARD:
            if unit is not None:
                self.diff(day, loc, prod, ref, (n.standard - unit) * q, f"{what} at {unit:.2f} against the standard")
            amount = round(q * n.standard, 2) if abs(n.qty - q) > EPS else n.value   # the last unit takes what is left
            n.qty -= q
            n.value -= amount
            self.book(day, loc, prod, what, ref, -q, -amount, before)
            return amount
        amount = round(q * (unit if unit is not None else before), 2)
        if unit is not None and n.qty - q > EPS and n.value - amount < 0:
            # the order's price is more than the stock is worth: what it cannot take is a price difference
            self.diff(day, loc, prod, ref, n.value - amount, f"{what} at {unit:.2f}: more than the stock was worth")
            amount = n.value
        if n.qty - q <= EPS:                   # nothing left (or below zero): valued at the price it had
            amount = n.value - round((n.qty - q) * before, 2)
        n.qty -= q
        n.value -= amount
        if abs(n.qty) <= EPS:
            n.qty = 0.0
        n.last = before if n.qty <= EPS else n.price
        self.book(day, loc, prod, what, ref, -q, -amount, before, moves=unit is not None)
        return amount

    # -- a price difference on stock ---------------------------------------------------------------------------
    def reprice(self, day: date, loc: str, prod: str, qty: float, amount: float, what: str, ref: str | None) -> None:
        """``amount`` more (or less) for ``qty`` units received earlier: to the stock while it is there (moving
        average), the rest aside."""
        n = self.node(loc, prod)
        if abs(amount) <= 0.005:
            return
        if n.control is PriceControl.STANDARD or qty <= EPS:
            self.diff(day, loc, prod, ref, amount, f"{what}: valued at the standard" if n.control is
                      PriceControl.STANDARD else what)
            return
        share = max(0.0, min(1.0, n.qty / qty)) if n.qty > EPS else 0.0
        to_stock = round(amount * share, 2)
        if share < 1.0:
            self.diff(day, loc, prod, ref, amount - to_stock,
                      f"{what}: {max(0.0, qty - max(n.qty, 0.0)):g} of {qty:g} had already gone")
        if abs(to_stock) > 0.005:
            before = n.price
            n.value += to_stock
            n.last = n.price
            self.book(day, loc, prod, what, ref, 0.0, to_stock, before)


def run_books(ds: Dataset, day: date, books: str = "entity", watch=None) -> tuple[_Books, dict[Node, float]]:
    """Every posting up to ``day`` through the books; what each movement was valued at is in ``at_move``. ``watch``
    (the accounting journal, Enterprise 7.4) is told of each movement and invoice before and after it is booked."""
    std = standards(ds)
    books_ = _Books(ds, std)
    lines = lines_index(ds, outside=False)
    po = {lid: _landed(ds, lid, ln) for lid, ln in lines.items() if ln.price is not None}
    kinds = {r.id: r.kind.value for r in ds.receipts}
    kinds.update({c.id: c.kind for c in ds.closed_orders if c.id not in kinds})
    journal = before(ds, day + timedelta(days=1))
    by_id = {m.id: m for m in journal}
    if books != "group" and ds.entities:
        books_.entity_books = True
        books_.ic_price = shipment_prices(ds, std, journal)

    events: list[tuple[date, int, int, object]] = [(m.date, 0, i, m) for i, m in enumerate(journal)]
    for i, inv in enumerate(ds.supplier_invoices):
        if not inv.cancelled and inv.date <= day:
            events.append((inv.date, 1, i, inv))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    if watch is not None:
        watch.start(books_, po, kinds, by_id)
    for _day, kind, _, ev in events:
        if watch is not None:
            watch.before(kind, ev)
        if kind == 0:
            _movement(books_, ev, po, kinds, by_id)        # type: ignore[arg-type]
        else:
            _invoice(books_, ds, ev, po, lines)
        if watch is not None:
            watch.after(kind, ev)

    return books_, std


def value_stock(ds: Dataset, as_of: date | None = None, limit: int = 500, books: str = "entity") -> ValuationView:
    """Every place's stock in the books on ``as_of`` (default: the latest posting, the planning start at the
    earliest: the week under way is in the books): its quantity, value and price, the postings that moved the value,
    and the price differences booked aside. ``books``: "entity" (each company's own) or "group" (consolidated)."""
    day = as_of or max([ds.settings.planning_start, *(m.date for m in ds.movements),
                        *(i.date for i in ds.supplier_invoices if not i.cancelled)])
    books_, std = run_books(ds, day, books)
    rows = []
    for (loc, prod), n in sorted(books_.nodes.items()):
        if abs(n.qty) <= EPS and abs(n.value) <= 0.005 and not n.changes:
            continue
        rows.append(ValuationRow(location=loc, entity=entity_of(ds, loc), product=prod, control=n.control,
                                 qty=round(n.qty, 6), value=round(n.value, 2), price=round(n.price, 4), standard=round(n.standard, 4),
                                 changes=n.changes))
    notes = []
    if not std:
        notes.append("The network cannot be built yet: standard prices are the products' standard costs.")
    ents = sorted(books_.entries, key=lambda e: e.date, reverse=True)
    return ValuationView(
        as_of=day, currency=ds.settings.currency, control=ds.execution.price_control, rows=rows,
        entries=ents[:limit], differences=sorted(books_.diffs, key=lambda x: x.date, reverse=True)[:limit],
        total_value=round(sum(r.value for r in rows), 2), total_differences=round(sum(x.amount for x in books_.diffs), 2),
        cost_of_sales=round(books_.cogs, 2), count_differences=round(books_.counts, 2), scrapped=round(books_.scrapped, 2),
        books="group" if books == "group" else "entity", intercompany_sales=round(books_.ic_sales, 2),
        intercompany_cost=round(books_.ic_cost, 2),
        in_transit=round(sum(v for q, v in books_.shipped.values() if q > EPS), 2), notes=notes)


def _landed(ds: Dataset, lid: str, ln) -> _Line:
    """A purchase line comes in at what it lands at, as planning values a purchase: the price in company currency
    with its duty, the freight per unit on the supplier's lane and the handling at the place (S/4: the delivery
    costs planned on the order are part of the receipt's value)."""
    rc = next((r for r in ds.receipts if r.id == lid), None)
    src = rc.source if rc is not None else next(((c.source_order or {}).get("source") for c in ds.closed_orders
                                                 if c.id == lid), None)
    pu = ds.purchasing_source_by_id.get(src or "")
    duty = pu.duty_rate if pu is not None else 0.0
    lane = supplier_lane(ds, ln.supplier, ln.location, ln.product) if ln.supplier else None
    fr = freight_per_unit(ds, lane.planning_mode, ln.product) if lane is not None else 0.0
    base = (ln.price or 0.0) * fx(ds, ln.currency)
    return _Line(price=base * (1.0 + duty) + fr + handling(ds, ln.location), base=base, duty=duty)


WORDS = {MovementType.OPENING: "opening balance", MovementType.RECEIPT: "receipt", MovementType.ISSUE: "issue to production",
         MovementType.SALE: "goods issue to a customer", MovementType.TRANSFER_OUT: "transfer out",
         MovementType.SCRAP: "scrap", MovementType.ADJUSTMENT: "count difference", MovementType.RETURN: "return to supplier"}


def _movement(b: _Books, m: GoodsMovement, po: dict[str, _Line], kinds: dict[str, str],
              by_id: dict[str, GoodsMovement]) -> None:
    if m.type is MovementType.STATUS:
        return                                         # between stock types or bins at one place: same value
    loc, prod, day = m.location, m.product, m.date
    what = WORDS.get(m.type, m.type.value)
    if m.reversal_of:
        orig = by_id.get(m.reversal_of)
        unit = b.at_move.get(m.reversal_of)
        q = abs(m.qty)
        ins = orig is not None and orig.signed > 0
        what = f"reversal of {m.reversal_of}"
        if ins:                                        # a receipt taken back leaves at what it came in at
            b.out(day, loc, prod, q, what, m.reversal_of, unit if b.node(loc, prod).control is not PriceControl.STANDARD
                  and unit is not None else None)
            if orig is not None and orig.type is MovementType.RECEIPT and orig.reference in po:
                po[orig.reference].received -= q
            took = b.took.get(m.reversal_of)
            if took is not None and orig is not None and orig.reference:   # a transfer receipt taken back: on the road again
                back = min(q, took[0])
                sq, sv = b.shipped.get(orig.reference, [0.0, 0.0])
                b.shipped[orig.reference] = [sq + back, sv + back * took[1]]
                b.took[m.reversal_of] = (took[0] - back, took[1])
        else:
            b.into(day, loc, prod, q, unit if unit is not None else b.node(loc, prod).price, what, m.reversal_of)
            if orig is not None and orig.type is MovementType.RETURN and orig.reference in po:
                po[orig.reference].received += q
            if orig is not None and orig.type is MovementType.TRANSFER_OUT and orig.reference in b.shipped:
                left = unit if unit is not None else b.node(loc, prod).price
                each = b.ic_price.get(orig.id, left)
                sq, sv = b.shipped[orig.reference]
                take = min(q, sq)
                b.shipped[orig.reference] = [sq - take, sv - take * each]
                if orig.id in b.ic_price:
                    b.ic_sales -= take * each
                    b.ic_cost -= take * left
        return
    q = abs(m.qty)
    if m.type is MovementType.OPENING:
        b.at_move[m.id] = b.into(day, loc, prod, q, b.node(loc, prod).standard, what, m.reference or m.id)
    elif m.type is MovementType.RECEIPT:
        ref = m.reference or ""
        kind = kinds.get(ref)
        if ref in po:
            ln = po[ref]
            unit_total, left = 0.0, q
            while left > EPS and ln.ahead:                 # invoiced before the goods: they come in at that price
                take = min(left, ln.ahead[0][0])
                unit_total += take * ln.ahead[0][1]
                ln.ahead[0][0] -= take
                left -= take
                if ln.ahead[0][0] <= EPS:
                    ln.ahead.pop(0)
            unit_total += left * ln.price
            ln.received += q
            b.at_move[m.id] = b.into(day, loc, prod, q, unit_total / q, "purchase receipt", ref,
                                     "purchase receipt at the order's price, against the standard")
        elif kind == "transfer" and b.shipped.get(ref):
            sq, sv = b.shipped[ref]
            unit = sv / sq if sq > EPS else b.node(loc, prod).price
            take = min(q, sq)
            b.shipped[ref] = [sq - take, sv - take * unit]
            b.took[m.id] = (take, unit)
            b.at_move[m.id] = b.into(day, loc, prod, q, unit, "transfer receipt", ref,
                                     "transfer at its transfer price, against the standard" if b.ic_price else
                                     "transfer at what it was worth where it left, against the standard")
        elif kind == "transfer" and b.entity_books and crossing(b.ds, frm := source_of(b.ds, m) or "", loc) == "entity":
            # from another company with no shipment in the journal (on the way at go-live): at the transfer price,
            # billed by the old system
            unit = price(b.ds, b.std, frm, loc, prod, day)[0]
            b.at_move[m.id] = b.into(day, loc, prod, q, unit, "transfer receipt", ref,
                                     "transfer from another company at its transfer price, against the standard")
        elif ref in b.returns:                             # a customer's return: back at what it left at
            sold = b.sold_at.get(b.returns[ref])
            b.at_move[m.id] = b.into(day, loc, prod, q, sold if sold is not None else b.node(loc, prod).price,
                                     "customer return", ref, "customer return at what it left at, against the standard")
            b.cogs -= q * b.at_move[m.id]
        else:                                              # production (or no order known): at the planned value
            b.at_move[m.id] = b.into(day, loc, prod, q, b.node(loc, prod).standard,
                                     "production receipt" if kind == "production" else "receipt", ref or None)
    elif m.type is MovementType.ADJUSTMENT:
        n = b.node(loc, prod)
        if m.qty > 0:
            b.at_move[m.id] = b.into(day, loc, prod, q, n.price, what, m.reference or m.id)
            b.counts += q * b.at_move[m.id]
        else:
            v = b.out(day, loc, prod, q, what, m.reference or m.id)
            b.at_move[m.id] = v / q
            b.counts -= v
    elif m.type is MovementType.RETURN and m.reference in po:
        ln = po[m.reference]
        v = b.out(day, loc, prod, q, what, m.reference, ln.price)
        ln.received -= q
        b.at_move[m.id] = v / q
    elif m.type in OUT_TYPES:
        v = b.out(day, loc, prod, q, what, m.reference or m.id)
        b.at_move[m.id] = v / q
        if m.type is MovementType.SALE:
            b.cogs += v
            if m.reference:
                b.sold_at[m.reference] = v / q
        elif m.type is MovementType.SCRAP:
            b.scrapped += v
        elif m.type is MovementType.TRANSFER_OUT and m.reference:
            sq, sv = b.shipped.get(m.reference, [0.0, 0.0])
            tp = b.ic_price.get(m.id)
            if tp is not None:                             # sold to another company: it arrives at the price
                b.ic_sales += q * tp
                b.ic_cost += v
            b.shipped[m.reference] = [sq + q, sv + (q * tp if tp is not None else v)]


def _invoice(b: _Books, ds: Dataset, inv, po: dict[str, _Line], lines) -> None:
    rate = fx(ds, inv.currency)
    total = sum(abs(ln.qty * ln.price) for ln in inv.lines) or 1.0
    for ln in inv.lines:
        info = lines.get(ln.order)
        line = po.get(ln.order)
        if info is None or line is None:
            continue
        loc, prod, day = info.location, info.product, inv.date
        freight = inv.delivery_costs * rate * abs(ln.qty * ln.price) / total
        if inv.kind in ("subsequent_debit", "subsequent_credit"):
            amount = (1 if inv.kind == "subsequent_debit" else -1) * ln.qty * ln.price * rate * (1.0 + line.duty) + freight
            b.reprice(day, loc, prod, ln.qty, amount, f"{inv.kind.replace('_', ' ')} {inv.id}", inv.id)
            continue
        sign = -1.0 if inv.kind == "credit_memo" else 1.0
        price = ln.price * rate
        per = (price - line.base) * (1.0 + line.duty)        # the duty follows the price
        if sign > 0:
            covered = min(ln.qty, max(0.0, line.received - line.invoiced))
            if ln.qty - covered > EPS:                  # billed before it came: it comes in at the invoice's price
                line.ahead.append([ln.qty - covered, line.price + per])
            line.invoiced += ln.qty
            b.reprice(day, loc, prod, covered, per * covered + freight,
                      f"invoice {inv.id} at {price:.2f} against {line.base:.2f}", inv.id)
        else:
            line.invoiced -= ln.qty
            b.reprice(day, loc, prod, ln.qty, -per * ln.qty - freight,
                      f"credit memo {inv.id} at {price:.2f} against {line.base:.2f}", inv.id)
