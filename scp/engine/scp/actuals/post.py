"""Posting what happened against firm orders and stock (≈ MIGO, VL02N, CO11N and MI07 for a small company).

Each action adds goods movements to the journal and nothing else; the roll-forward books them into stock and uses
them to close orders. So an action is always safe to undo and never double counts.

* **Ship a transfer**: a goods issue at the sending place (the goods are then in transit).
* **Receive** an order:
  - a purchase line goes through Buying's goods receipt (the supplier's delivery tolerances apply);
  - a transfer posts its arrival, and the goods issue at the sending place for whatever was not shipped first, so
    the same goods are never in two places;
  - a production order posts the quantity made, issues its parts (backflush: the order's reservations in proportion
    to what is made, or the actual usage when given) and receives any co-products.
* **Deliver** a sales order: a goods issue to the customer from the place it ships from (its promise, else the
  customer's first route, else the order's own place), for what is still open or part of it; *final* closes it short.
* **Count stock**: set the stock at a place. Where the journal has nothing yet this is the opening balance, otherwise a
  count difference; on-hand in the planning policies follows, so planning, the journal and the count agree.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import TypedDict

from ..model import (
    Dataset, DemandKind, DemandRecord, GoodsMovement, LocationProduct, MovementType, ReceiptKind, ScheduledReceipt,
    StockType,
)
from ..model.common import STOCKING_LOCATION_TYPES
from ..purchasing import PurchasingError, receive as receive_purchase
from ..purchasing.result import ActionReport
from .documents import (
    StockError, cancel_counts, complete, count_doc, enter_counts, move_stock, post_counts, reverse, scrap, short_orders,
    shorten,
)
from .lots import planning_stock
from .stock import EPS, counterparty, movement_ids, pending_openings
from ..plan.structure import needs


class PostingError(ValueError):
    """A posting the data does not allow; the message says why in plain words."""


def _order(ds: Dataset, oid: str) -> ScheduledReceipt:
    rc = next((r for r in ds.receipts if r.id == oid), None)
    if rc is None:
        raise PostingError(f"{oid} is not an open purchase, production or transfer order")
    return rc


def _posted(ds: Dataset, oid: str) -> tuple[dict, dict, dict]:
    """Quantity already received, shipped (transfer goods issue) and issued (components) per (location, product)."""
    got: dict[tuple[str, str], float] = defaultdict(float)
    shipped: dict[tuple[str, str], float] = defaultdict(float)
    issued: dict[tuple[str, str], float] = defaultdict(float)
    for m in ds.movements:
        if m.reference != oid:
            continue
        k = (m.location, m.product)
        if m.type is MovementType.RECEIPT:
            got[k] += m.net
        elif m.type is MovementType.TRANSFER_OUT:
            shipped[k] += m.net
        elif m.type is MovementType.ISSUE:
            issued[k] += m.net
    return got, shipped, issued


def _ordered(rc: ScheduledReceipt) -> float:
    return rc.ordered_qty if rc.ordered_qty is not None else rc.qty


def origin(ds: Dataset, rc: ScheduledReceipt) -> str | None:
    """Where a transfer ships from: its reservation at the origin, else its lane's origin."""
    rv = next((r for r in rc.reservations if r.product == rc.product and r.location != rc.location), None)
    return rv.location if rv else counterparty(ds, rc)


def _on(ds: Dataset, on: date | None) -> date:
    return on or ds.settings.planning_start


def _q(q: float) -> float:
    return round(q, 6)


def _n(q: float) -> str:
    """A quantity for a message: thousands separated, at most two decimals."""
    t = f"{q:,.2f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _at(ds: Dataset, loc: str | None) -> str:
    lo = ds.location_by_id.get(loc or "")
    return (lo.name or lo.id) if lo else (loc or "?")


def ship(ds: Dataset, oid: str, qty: float | None = None, on: date | None = None, lot: Lot | None = None
         ) -> tuple[Dataset, ActionReport]:
    """Dispatch a stock transfer: a goods issue at the sending place, referenced to the transfer (the batches first
    expiring first, unless one is given)."""
    rc = _order(ds, oid)
    if rc.kind is not ReceiptKind.TRANSFER:
        raise PostingError(f"{oid} is a {rc.kind.value} order; only a stock transfer is shipped from one place to another")
    frm = origin(ds, rc)
    if not frm or frm not in ds.location_by_id:
        raise PostingError(f"{oid} has no sending place: give it a route (lane) or a reservation at the origin")
    got, shipped, _ = _posted(ds, oid)
    left = _ordered(rc) - shipped[(frm, rc.product)]
    q = float(qty) if qty is not None else left
    if q <= EPS:
        raise PostingError(f"everything on {oid} has already been shipped")
    on = _on(ds, on)
    ids = movement_ids(ds)
    m = GoodsMovement(id=next(ids), date=on, type=MovementType.TRANSFER_OUT, location=frm, product=rc.product, qty=_q(q),
                      reference=oid, counterparty=rc.location, note="Shipped", batch=(lot or {}).get("batch"))
    moves, _, notes = _complete(ds, [m], on, lot)
    transit = shipped[(frm, rc.product)] + q - got[(rc.location, rc.product)]
    return (ds.model_copy(update={"movements": [*ds.movements, *moves]}),
            ActionReport(ok=True, movements=[x.id for x in moves], doc=moves[0].doc,
                         message=f"{oid}: {_n(q)} shipped from {_at(ds, frm)} on {on.isoformat()}{_batches(moves)}; "
                                 f"{_n(transit)} now in transit to {_at(ds, rc.location)}"
                                 + ("; " + "; ".join(notes) if notes else "") + "."))


def _bom_parts(ds: Dataset, rc: ScheduledReceipt, made: float, first: bool) -> list[tuple[str, str, float]]:
    """Parts for ``made`` good units from the production source's BOM (orders without reservations, e.g. imported)."""
    ps = ds.production_source_by_id.get(rc.source or "")
    if ps is None:
        return []
    day = rc.start_date or ds.settings.planning_start
    out = []
    for c in needs(ds, ps, day):
        q = c.per_unit * made + (c.per_order if first else 0.0)
        if q > EPS:
            out.append((rc.location, c.product, q))
    return out


def _production_parts(ds: Dataset, rc: ScheduledReceipt, total: float, made: float, before_q: float,
                      issued: dict) -> tuple[list[tuple[str, str, float]], str]:
    """The default backflush, shared by posting and its read-only preview."""
    if not (rc.reservations or rc.original_reservations):
        return _bom_parts(ds, rc, made, first=before_q <= EPS), "from the bill of materials"
    parts = []
    ordered = _ordered(rc)
    ps = ds.production_source_by_id.get(rc.source or "")
    bom = {n.product: n for n in needs(ds, ps, rc.start_date or ds.settings.planning_start)} if ps else {}
    for rv in (rc.original_reservations or rc.reservations):
        req = rv.required_qty if rv.required_qty is not None else rv.qty
        part = bom.get(rv.product)
        planned = part.qty(ordered) if part else 0.0
        target = part.qty(total) * req / planned if planned > EPS else req * total / ordered
        n = target - issued.get((rv.location, rv.product), 0.0)
        if n > EPS:
            parts.append((rv.location, rv.product, n))
    return parts, "in proportion to what was made"


def production_usage(ds: Dataset, oid: str, qty: float | None = None) -> list[dict]:
    """Preview components for this receipt, including fixed parts, effective BOMs and net reversals."""
    rc = _order(ds, oid)
    if rc.kind is not ReceiptKind.PRODUCTION:
        raise PostingError(f"{oid} is not a production order")
    got, _, issued = _posted(ds, oid)
    before_q = got[(rc.location, rc.product)]
    q = _q(float(qty) if qty is not None else _ordered(rc) - before_q)
    if q <= EPS:
        raise PostingError(f"nothing is left to receive on {oid}")
    parts, _ = _production_parts(ds, rc, before_q + q, q, before_q, issued)
    amounts = {(loc, prod): _q(n) for loc, prod, n in parts}
    keys = dict.fromkeys([(rv.location, rv.product) for rv in (rc.original_reservations or rc.reservations)]
                         + list(amounts))
    return [{"location": loc, "product": prod, "qty": amounts.get((loc, prod), 0.0)} for loc, prod in keys]


class Lot(TypedDict, total=False):
    """What a posting says about the goods: the batch (and, received, its expiry and the supplier's number), the
    serial numbers, and the stock type it goes to or comes from."""

    batch: str | None
    expires_on: date | None
    supplier_batch: str
    serials: list[str] | None
    stock_type: StockType | None


def _complete(ds: Dataset, moves: list[GoodsMovement], on: date, lot: Lot | None, **kw
              ) -> tuple[list[GoodsMovement], list, list[str]]:
    lot = lot or {}
    try:
        return complete(ds, moves, on, batch=lot.get("batch"), expires_on=lot.get("expires_on"),
                        supplier_batch=lot.get("supplier_batch") or "", serials=lot.get("serials"),
                        stock_type=lot.get("stock_type"), **kw)
    except StockError as e:
        raise PostingError(str(e)) from e


def _batches(moves: list[GoodsMovement]) -> str:
    bs = list(dict.fromkeys(m.batch for m in moves[:1] + [x for x in moves[1:] if x.product == moves[0].product
                                                            and x.type is moves[0].type] if m.batch))
    return f" (batch{'es' if len(bs) != 1 else ''} {', '.join(bs)})" if bs else ""


def receive(ds: Dataset, oid: str, qty: float | None = None, on: date | None = None, final: bool = False,
            usage: list[dict] | None = None, note: str = "", lot: Lot | None = None) -> tuple[Dataset, ActionReport]:
    """Goods receipt against a firm order (see the module docstring). ``usage``: ``[{"product", "qty"}]`` actual parts
    used by a production order, instead of the backflush."""
    rc = _order(ds, oid)
    on = _on(ds, on)
    if rc.kind is ReceiptKind.PURCHASE:
        try:
            new, rep = receive_purchase(ds, rc.po or rc.id, [{"id": rc.id, "qty": qty, "final": final}], on, note,
                                        lot=dict(lot or {}))
        except PurchasingError as e:
            raise PostingError(str(e)) from e
        return new, rep
    got, shipped, issued = _posted(ds, oid)
    ordered = _ordered(rc)
    before_q = got[(rc.location, rc.product)]
    q = float(qty) if qty is not None else ordered - before_q
    if q <= EPS:
        raise PostingError(f"nothing is left to receive on {oid}")
    ids = movement_ids(ds)
    moves: list[GoodsMovement] = []
    notes: list[str] = []

    def add(typ: MovementType, loc: str, prod: str, n: float, text: str, **kw) -> None:
        moves.append(GoodsMovement(id=next(ids), date=on, type=typ, location=loc, product=prod, qty=_q(n),
                                   reference=oid, note=text[:200], **kw))

    total = before_q + q
    closes = final or total >= ordered - EPS
    add(MovementType.RECEIPT, rc.location, rc.product, q, note or ("Received" if rc.kind is ReceiptKind.TRANSFER else
                                                                     "Production confirmed"), final=bool(final))
    if rc.kind is ReceiptKind.TRANSFER:
        frm = origin(ds, rc)
        in_transit = max(0.0, shipped[(frm, rc.product)] - before_q) if frm else 0.0
        missing = q - in_transit
        if frm and missing > EPS:
            add(MovementType.TRANSFER_OUT, frm, rc.product, missing, "Shipped on arrival (no dispatch was posted)",
                counterparty=rc.location)
            notes.append(f"{_n(missing)} taken out of {_at(ds, frm)}, which had not shipped them yet")
    elif rc.kind is ReceiptKind.PRODUCTION:
        parts: list[tuple[str, str, float]] = []
        if usage is not None:
            for u in usage:
                p, n = u.get("product"), float(u.get("qty") or 0)
                if n < -EPS:
                    raise PostingError(f"{oid}: a used quantity cannot be negative ({p})")
                if n > EPS:
                    rv = next((r for r in rc.reservations if r.product == p), None)
                    parts.append((rv.location if rv else rc.location, str(p), n))
            how = "as used"
        else:
            parts, how = _production_parts(ds, rc, total, q, before_q, issued)
        for loc, prod, n in parts:
            add(MovementType.ISSUE, loc, prod, n, "Backflush" if usage is None else "Actual usage")
        if parts:
            notes.append(f"{len(parts)} part{'s' if len(parts) != 1 else ''} issued {how}")
        ps = ds.production_source_by_id.get(rc.source or "")
        if ps is not None:
            for co in ps.co_products:
                n = co.qty * q / ps.output_qty
                if n > EPS:
                    add(MovementType.RECEIPT, rc.location, co.product, n, f"Co-product of {rc.product}")
            if ps.co_products:
                notes.append(f"{len(ps.co_products)} co-product{'s' if len(ps.co_products) != 1 else ''} received")
    moves, batches, more = _complete(ds, moves, on, lot)
    notes += more
    left = ordered - total
    status = ("closed short" if left > EPS else "complete") if closes else f"{_n(left)} still to come"
    msg = (f"{oid}: {_n(q)} {'made' if rc.kind is ReceiptKind.PRODUCTION else 'received'} at {_at(ds, rc.location)} on "
           f"{on.isoformat()}{_batches(moves)} ({status})"
           + ("; " + "; ".join(notes) if notes else "")
           + ". Stock and the order are updated when the plan moves past this date.")
    new = ds.model_copy(update={"movements": [*ds.movements, *moves], "batches": [*ds.batches, *batches]})
    rep = ActionReport(ok=True, message=msg, movements=[m.id for m in moves], doc=moves[0].doc)
    return new, with_short(new, rep, {(rc.location, rc.product)}, on)


def with_short(ds: Dataset, rep: ActionReport, parts: set[tuple[str, str]], on: date) -> ActionReport:
    """A receipt that leaves firm orders short of the part names them (R16)."""
    short = short_orders(ds, parts, on)
    if not short:
        return rep
    names = ", ".join(s.order for s in short[:4]) + ("…" if len(short) > 4 else "")
    return rep.model_copy(update={"short_orders": short, "message": rep.message + (
        f" {len(short)} firm order{'s' if len(short) != 1 else ''} can no longer run in full: {names}; shorten "
        f"{'them' if len(short) != 1 else 'it'} to what the parts cover, or find the rest.")})


def sales_order(ds: Dataset, oid: str) -> DemandRecord:
    d = next((d for d in ds.demand if d.kind is DemandKind.SALES_ORDER and d.id == oid), None)
    if d is None:
        raise PostingError(f"{oid} is not an open sales order")
    return d


def delivered(ds: Dataset, oid: str) -> float:
    """What the journal has delivered on a sales order (every posting, before and after the planning start)."""
    return sum(m.net for m in ds.movements if m.type is MovementType.SALE and m.reference == oid)


def ordered_now(ds: Dataset, d: DemandRecord) -> float:
    """A sales order's whole quantity: its ordered quantity once a roll has booked deliveries, else its quantity."""
    return d.ordered_qty if d.ordered_qty is not None else d.qty


def ship_point(ds: Dataset, d: DemandRecord) -> str | None:
    """Where a sales order ships from: where it was promised from, else the customer's first route, else the order's
    own place when it is one that holds stock."""
    cf = sorted((c for c in ds.confirmations if c.order == d.id), key=lambda c: (c.ship_date, c.date))
    if cf:
        return cf[0].ship_from
    lanes = sorted((ln for ln in ds.lanes if ln.destination == d.location
                    and (not ln.products or d.product in ln.products)
                    and ds.location_type(ln.origin) in STOCKING_LOCATION_TYPES), key=lambda ln: ln.priority)
    if lanes:
        return lanes[0].origin
    return d.location if ds.location_type(d.location) in STOCKING_LOCATION_TYPES else None


def deliver(ds: Dataset, oid: str, qty: float | None = None, on: date | None = None, final: bool = False,
            ship_from: str | None = None, note: str = "", lot: Lot | None = None) -> tuple[Dataset, ActionReport]:
    """Goods issue of a sales order to its customer (≈ VL01N + PGI)."""
    d = sales_order(ds, oid)
    frm = ship_from or ship_point(ds, d)
    if not frm or ds.location_type(frm) not in STOCKING_LOCATION_TYPES:
        raise PostingError(f"{oid} has no place to ship from: give {_at(ds, d.location)} a route from a plant or "
                           "warehouse, or promise the order first")
    ordered = ordered_now(ds, d)
    done = delivered(ds, oid)
    q = float(qty) if qty is not None else ordered - done
    if q <= EPS:
        raise PostingError(f"everything on {oid} has already been delivered")
    on = _on(ds, on)
    m = GoodsMovement(id=next(movement_ids(ds)), date=on, type=MovementType.SALE, location=frm, product=d.product,
                      qty=_q(q), reference=oid, counterparty=d.location, final=bool(final),
                      note=(note or ("Delivered, rest cancelled" if final else "Delivered"))[:200],
                      batch=(lot or {}).get("batch"))
    left = ordered - done - q
    status = ("closed short" if left > EPS else "complete") if final or left <= EPS else f"{_n(left)} still open"
    moves, _, notes = _complete(ds, [m], on, lot)
    msg = (f"{oid}: {_n(q)} delivered to {_at(ds, d.location)} from {_at(ds, frm)} on {on.isoformat()}{_batches(moves)} "
           f"({status})" + ("; " + "; ".join(notes) if notes else "")
           + ". Stock and the order are updated when the plan moves past this date.")
    return (ds.model_copy(update={"movements": [*ds.movements, *moves]}),
            ActionReport(ok=True, message=msg, movements=[x.id for x in moves], doc=moves[0].doc))


def count_stock(ds: Dataset, counts: list[dict], on: date | None = None, note: str = "") -> tuple[Dataset, ActionReport]:
    """Stock counted at places (``[{"location", "product", "qty"}]``) at the end of ``on`` (default: the day before the
    planning start, i.e. the stock the plan starts from). A place with nothing in the journal gets an opening balance,
    any other a count difference. A count before the planning start replaces stock typed at setup and sets on-hand in
    the planning policies from the journal; a later one takes effect when the plan moves past it."""
    start = ds.settings.planning_start
    day = on or start - timedelta(days=1)
    early = day < start
    journal = list(ds.movements) if early else [*ds.movements, *pending_openings(ds)]
    ids = movement_ids(ds)
    moves: list[GoodsMovement] = []
    at: list[tuple[str, str]] = []
    for c in counts:
        if c.get("qty") is None:
            continue
        loc, prod, n = str(c.get("location") or ""), str(c.get("product") or ""), float(c.get("qty") or 0)
        if loc not in ds.location_by_id or prod not in ds.product_by_id:
            raise PostingError(f"there is no place {loc!r} or product {prod!r}")
        if n < -EPS:
            raise PostingError(f"{prod} at {loc}: a count cannot be negative")
        at.append((loc, prod))
        mine = [m for m in journal if (m.location, m.product) == (loc, prod) and m.date <= day]
        have = sum(m.signed for m in mine)
        diff = n - have
        if abs(diff) <= EPS:
            continue
        if not mine and diff > 0:
            moves.append(GoodsMovement(id=next(ids), date=day, type=MovementType.OPENING, location=loc, product=prod,
                                       qty=_q(diff), note=(note or "Opening balance")[:200]))
        else:
            moves.append(GoodsMovement(id=next(ids), date=day, type=MovementType.ADJUSTMENT, location=loc, product=prod,
                                       qty=_q(diff), note=(note or f"Stock count: {_n(have)} → {_n(n)}")[:200]))
    if moves:
        moves, _, _ = _complete(ds, moves, day, None)
    new = ds.model_copy(update={"movements": [*ds.movements, *moves]})
    if early:
        # the plan starts from the journal: on-hand at every counted place follows it (the stock it may use)
        bal = planning_stock(new, [m for m in new.movements if m.date < start], start)
        lps = [lp.model_copy() for lp in ds.location_products]
        by = {(lp.location, lp.product): lp for lp in lps}
        for k in dict.fromkeys(at):
            if k not in by:
                by[k] = LocationProduct(location=k[0], product=k[1])
                lps.append(by[k])
            by[k].on_hand = max(0.0, _q(bal.get(k, 0.0)))
        new = new.model_copy(update={"location_products": lps})
    opened = sum(m.type is MovementType.OPENING for m in moves)
    msg = (f"{len(at)} count{'s' if len(at) != 1 else ''} as of {day.isoformat()}: "
           + (f"{opened} opening balance{'s' if opened != 1 else ''} and {len(moves) - opened} count "
              f"difference{'s' if len(moves) - opened != 1 else ''} posted" if moves else "the journal already agrees")
           + ("." if early else "; they count when the plan moves past this date."))
    return (Dataset.model_validate(new.model_dump()),
            ActionReport(ok=True, message=msg, movements=[m.id for m in moves], doc=moves[0].doc if moves else None))


def post(ds: Dataset, action: str, *, order: str | None = None, qty: float | None = None, on: date | None = None,
         final: bool = False, usage: list[dict] | None = None, counts: list[dict] | None = None,
         note: str = "", ship_from: str | None = None, lot: Lot | None = None, location: str | None = None,
         product: str | None = None, to_type: StockType | None = None, movement: str | None = None,
         doc: str | None = None, nodes: list[tuple[str, str]] | None = None, block: bool = True,
         uncounted_zero: bool = False) -> tuple[Dataset, ActionReport]:
    lot = lot or {}
    if qty is not None and action in {"receive", "deliver", "ship", "move", "scrap"}:
        qty = round(float(qty), 6)
        if qty <= EPS:
            raise PostingError("quantity is too small to post at six-decimal precision")
    try:
        if action == "count":
            return count_stock(ds, counts or [], on, note)
        if action == "move":
            return move_stock(ds, location or "", product or "", qty, lot.get("stock_type") or StockType.UNRESTRICTED,
                              to_type or StockType.UNRESTRICTED, lot.get("batch"), on, note, lot.get("serials"))
        if action == "scrap":
            return scrap(ds, location or "", product or "", qty, lot.get("stock_type") or StockType.UNRESTRICTED,
                         lot.get("batch"), on, note)
        if action == "scrap_expired":
            return scrap(ds, location or "", product or "", None, on=on, note=note, expired_only=True)
        if action == "reverse":
            return reverse(ds, movement or "", on, note)
        if action == "count_doc":
            return count_doc(ds, nodes or [], on, block, note)
        if action == "count_enter":
            return enter_counts(ds, doc or "", counts or [])
        if action == "count_post":
            return post_counts(ds, doc or "", uncounted_zero)
        if action == "count_cancel":
            return cancel_counts(ds, doc or "")
        if action == "shorten":
            if qty is None:
                raise PostingError("say how many the order should be for")
            return shorten(ds, order or "", qty)
    except StockError as e:
        raise PostingError(str(e)) from e
    if not order:
        raise PostingError("say which order to post against")
    if action == "ship":
        return ship(ds, order, qty, on, lot)
    if action == "receive":
        return receive(ds, order, qty, on, final, usage, note, lot)
    if action == "deliver":
        return deliver(ds, order, qty, on, final, ship_from, note, lot)
    raise PostingError(f"unknown posting {action!r}")
