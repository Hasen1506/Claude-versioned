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
* **Count stock**: set the stock at a place. Where the journal has nothing yet this is the opening balance, otherwise a
  count difference; on-hand in the planning policies follows, so planning, the journal and the count agree.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from ..model import Dataset, GoodsMovement, LocationProduct, MovementType, ReceiptKind, ScheduledReceipt
from ..purchasing import PurchasingError, receive as receive_purchase
from ..purchasing.result import ActionReport
from .stock import EPS, counterparty, movement_ids, pending_openings


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
            got[k] += m.qty
        elif m.type is MovementType.TRANSFER_OUT:
            shipped[k] += m.qty
        elif m.type is MovementType.ISSUE:
            issued[k] += m.qty
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


def ship(ds: Dataset, oid: str, qty: float | None = None, on: date | None = None) -> tuple[Dataset, ActionReport]:
    """Dispatch a stock transfer: a goods issue at the sending place, referenced to the transfer."""
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
                      reference=oid, counterparty=rc.location, note="Shipped")
    transit = shipped[(frm, rc.product)] + q - got[(rc.location, rc.product)]
    return (ds.model_copy(update={"movements": [*ds.movements, m]}),
            ActionReport(ok=True, movements=[m.id],
                         message=f"{oid}: {_n(q)} shipped from {_at(ds, frm)} on {on.isoformat()}; {_n(transit)} now in "
                                 f"transit to {_at(ds, rc.location)}."))


def _bom_parts(ds: Dataset, rc: ScheduledReceipt, made: float, first: bool) -> list[tuple[str, str, float]]:
    """Parts for ``made`` good units from the production source's BOM (orders without reservations, e.g. imported)."""
    ps = ds.production_source_by_id.get(rc.source or "")
    if ps is None:
        return []
    started = made / (1.0 - ps.assembly_scrap)
    day = rc.start_date or ds.settings.planning_start
    out = []
    for c in ps.components:
        if not c.valid_on(day):
            continue
        if c.fixed_qty:
            q = c.qty / (1.0 - c.scrap) if first else 0.0
        else:
            q = c.qty * started / ps.output_qty / (1.0 - c.scrap)
        if q > EPS:
            out.append((rc.location, c.product, q))
    return out


def _below_zero(ds: Dataset, moves: list[GoodsMovement], on: date) -> list[tuple[tuple[str, str], float]]:
    """Places an issue in ``moves`` takes below zero on ``on``, by the journal (setup stock included)."""
    out = []
    for m in moves:
        if m.type not in (MovementType.ISSUE, MovementType.TRANSFER_OUT):
            continue
        k = (m.location, m.product)
        bal = sum(x.signed for x in [*ds.movements, *pending_openings(ds), *moves]
                  if (x.location, x.product) == k and x.date <= on)
        if bal < -EPS and k not in dict(out):
            out.append((k, bal))
    return out


def receive(ds: Dataset, oid: str, qty: float | None = None, on: date | None = None, final: bool = False,
            usage: list[dict] | None = None, note: str = "") -> tuple[Dataset, ActionReport]:
    """Goods receipt against a firm order (see the module docstring). ``usage``: ``[{"product", "qty"}]`` actual parts
    used by a production order, instead of the backflush."""
    rc = _order(ds, oid)
    on = _on(ds, on)
    if rc.kind is ReceiptKind.PURCHASE:
        try:
            return receive_purchase(ds, rc.po or rc.id, [{"id": rc.id, "qty": qty, "final": final}], on, note)
        except PurchasingError as e:
            raise PostingError(str(e)) from e
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
        elif rc.reservations:
            share = min(1.0, total / ordered) if ordered > EPS else 1.0
            for rv in rc.reservations:
                req = rv.required_qty if rv.required_qty is not None else rv.qty
                n = req * share - issued[(rv.location, rv.product)]
                if n > EPS:
                    parts.append((rv.location, rv.product, n))
            how = "in proportion to what was made"
        else:
            parts = _bom_parts(ds, rc, q, first=before_q <= EPS)
            how = "from the bill of materials"
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
    short = _below_zero(ds, moves, on)
    if short:
        notes.append("not enough in stock by the journal: " + ", ".join(
            f"{ds.product_by_id[p].name or p} at {_at(ds, lo)} goes to {_n(q)}" for (lo, p), q in short[:3])
            + " (post the missing receipt, or a count)")
    left = ordered - total
    status = ("closed short" if left > EPS else "complete") if closes else f"{_n(left)} still to come"
    msg = (f"{oid}: {_n(q)} {'made' if rc.kind is ReceiptKind.PRODUCTION else 'received'} at {_at(ds, rc.location)} on "
           f"{on.isoformat()} ({status})"
           + ("; " + "; ".join(notes) if notes else "")
           + ". Stock and the order are updated when the plan moves past this date.")
    return (ds.model_copy(update={"movements": [*ds.movements, *moves]}),
            ActionReport(ok=True, message=msg, movements=[m.id for m in moves]))


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
    new = ds.model_copy(update={"movements": [*ds.movements, *moves]})
    if early:
        # the plan starts from the journal: on-hand at every counted place follows it
        bal: dict[tuple[str, str], float] = defaultdict(float)
        for m in new.movements:
            if m.date < start and (m.location, m.product) in set(at):
                bal[(m.location, m.product)] += m.signed
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
    return Dataset.model_validate(new.model_dump()), ActionReport(ok=True, message=msg, movements=[m.id for m in moves])


def post(ds: Dataset, action: str, *, order: str | None = None, qty: float | None = None, on: date | None = None,
         final: bool = False, usage: list[dict] | None = None, counts: list[dict] | None = None,
         note: str = "") -> tuple[Dataset, ActionReport]:
    if action == "count":
        return count_stock(ds, counts or [], on, note)
    if not order:
        raise PostingError("say which order to post against")
    if action == "ship":
        return ship(ds, order, qty, on)
    if action == "receive":
        return receive(ds, order, qty, on, final, usage, note)
    raise PostingError(f"unknown posting {action!r}")
