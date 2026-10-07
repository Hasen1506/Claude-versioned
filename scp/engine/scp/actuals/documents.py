"""Material documents: what every posting shares, and the postings on stock itself (Phase O).

Every posting action builds its movements, then :func:`complete` finishes them the same way:

* one material document number (``MD-00001``) for the movements posted together, which is what a reversal takes back;
* a receipt of a batch-managed product gets a batch with its expiry date (made date + shelf life unless given), and
  goes into quality inspection when the product is inspected on receipt; a transfer arrives in the batches shipped;
* an issue, sale, transfer or scrap without a batch takes the batches first expiring, first out;
* serialised products carry one serial number per unit: given, or the next ones for a receipt, or the ones in
  stock (first received, first out) for an issue; a transfer arrives with the serials shipped;
* the company's rule for stock below zero (refuse, allow, count as found) and an open physical inventory document's
  posting block are enforced.

The stock postings (≈ MIGO 321/343/344/551, MIGO cancel, MI01/MI04/MI07): move stock between stock types, scrap,
reverse a document, and physical inventory documents with a freeze.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, timedelta

from ..model import (
    Batch, CountItem, Dataset, DemandRecord, Confirmation, GoodsMovement, InventoryDoc, MovementType, NegativeStock, ReceiptKind, ScheduledReceipt,
    StockType,
)
from ..model.common import STOCKING_LOCATION_TYPES
from ..purchasing.result import ActionReport, ShortOrder
from .lots import EPS, new_batch, node_lots, pick
from .stock import before, movement_ids, pending_openings

OUT = (MovementType.ISSUE, MovementType.SALE, MovementType.TRANSFER_OUT, MovementType.SCRAP, MovementType.RETURN)
Node = tuple[str, str]


class StockError(ValueError):
    """A posting the stock does not allow; the message says why in plain words."""


def _n(q: float) -> str:
    t = f"{q:,.2f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _at(ds: Dataset, loc: str | None) -> str:
    lo = ds.location_by_id.get(loc or "")
    return (lo.name or lo.id) if lo else (loc or "?")


def _name(ds: Dataset, p: str) -> str:
    x = ds.product_by_id.get(p)
    return (x.name or x.id) if x else p


def next_doc(ds: Dataset, prefix: str = "MD") -> str:
    n = 0
    for x in [*(m.doc for m in ds.movements), *(d.id for d in ds.inventory_docs)]:
        g = re.fullmatch(prefix + r"-(\d+)", x or "")
        if g:
            n = max(n, int(g.group(1)))
    return f"{prefix}-{n + 1:05d}"


def _serials_here(movs: list[GoodsMovement], node: Node, on: date | None = None,
                  batch: str | None = None, stock_type: StockType | None = None) -> list[str]:
    """Serial numbers at a place, in the order they came in."""
    have: dict[tuple[str, str | None, StockType], float] = {}
    for m in sorted(movs, key=lambda m: (m.date, m.id)):
        if (m.location, m.product) != node or (on is not None and m.date > on):
            continue
        for sn in m.serials:
            k = (sn, m.batch, m.stock_type)
            have[k] = have.get(k, 0.0) + (1.0 if m.signed > 0 else -1.0)
    return list(dict.fromkeys(sn for (sn, b, t), v in have.items() if v > 0.5
                             and (batch is None or batch == b) and (stock_type is None or stock_type == t)))


def _next_serials(ds: Dataset, product: str, n: int, taken: set[str]) -> list[str]:
    stem = re.sub(r"[^A-Za-z0-9]", "", product)[:12].upper() or "SN"
    used = {sn for m in ds.movements if m.product == product for sn in m.serials} | taken
    k = 0
    for sn in used:
        g = re.fullmatch(re.escape(stem) + r"-(\d+)", sn)
        if g:
            k = max(k, int(g.group(1)))
    return [f"{stem}-{k + i + 1:06d}" for i in range(n)]


def blocked_by_count(ds: Dataset, node: Node) -> InventoryDoc | None:
    return next((d for d in ds.inventory_docs if d.status == "open" and d.block
                 and any((it.location, it.product) == node for it in d.items)), None)


def complete(ds: Dataset, moves: list[GoodsMovement], on: date, *, batch: str | None = None,
             expires_on: date | None = None, supplier_batch: str = "", serials: list[str] | None = None,
             stock_type: StockType | None = None, inspect: bool = True, counting: bool = False,
             per: dict[int, dict] | None = None) -> tuple[list[GoodsMovement], list[Batch], list[str]]:
    """Finish the movements of one posting (see the module docstring). ``batch``, ``expires_on``, ``supplier_batch``,
    ``serials`` and ``stock_type`` apply to the first movement (the order's own product); ``per`` gives them by
    movement index instead (``{"batch", "expires_on", "supplier_batch", "serials", "stock_type"}``). Returns the movements, the
    new batch records and notes for the message; raises :class:`StockError` when the stock does not allow it."""
    doc = next_doc(ds)
    fresh = movement_ids(ds, [m.id for m in moves])          # numbers after the posting's own, for split movements
    journal = [*ds.movements, *pending_openings(ds)]
    out: list[GoodsMovement] = []
    batches: list[Batch] = []
    notes: list[str] = []
    known = {(b.product, b.id) for b in ds.batches}
    done: dict[int, list[GoodsMovement]] = {}
    # goods leave before they arrive: a transfer received with its dispatch arrives in the batches that dispatch took
    for i in sorted(range(len(moves)), key=lambda i: moves[i].type not in OUT):
        m = moves[i]
        prod = ds.product_by_id.get(m.product)
        node = (m.location, m.product)
        if not counting and (inv := blocked_by_count(ds, node)) is not None:
            raise StockError(f"{_name(ds, m.product)} at {_at(ds, m.location)} is being counted ({inv.id}): post "
                             "the count first, or cancel it")
        o = (per or {}).get(i) or ({"batch": batch, "expires_on": expires_on, "supplier_batch": supplier_batch,
                                    "serials": serials, "stock_type": stock_type} if i == 0 else {})
        upd: dict = {"doc": doc}
        pieces: list[tuple[str | None, float]] = [(m.batch, m.qty)]
        if m.type in (MovementType.RECEIPT, MovementType.OPENING) and m.qty > 0:
            rc = next((r for r in ds.receipts if r.id == m.reference), None)
            transfer = rc is not None and rc.kind is ReceiptKind.TRANSFER and m.type is MovementType.RECEIPT
            if o.get("stock_type") is not None:
                upd["stock_type"] = StockType(o["stock_type"])
            elif inspect and prod and prod.inspect_on_receipt and not transfer and m.type is MovementType.RECEIPT:
                upd["stock_type"] = StockType.QUALITY
            if transfer and prod and m.batch is None and not o.get("batch"):
                pieces = _arriving(ds, [*journal, *out], rc, m.qty)
            elif prod and prod.batch_managed and m.batch is None:
                b = o.get("batch") or None
                if b is None or (m.product, b) not in known | {(x.product, x.id) for x in batches}:
                    rec = new_batch(ds, m.product, m.date, batches, o.get("expires_on"), o.get("supplier_batch") or "", b)
                    batches.append(rec)
                    b = rec.id
                pieces = [(b, m.qty)]
            elif prod and m.batch and (m.product, m.batch) not in known | {(x.product, x.id) for x in batches}:
                batches.append(new_batch(ds, m.product, m.date, batches, o.get("expires_on"),
                                         o.get("supplier_batch") or "", m.batch))
            if prod and prod.serial_numbers:
                sn = list(o.get("serials") or [])
                if transfer and not sn:
                    travelling: dict[str, float] = defaultdict(float)
                    for x in [*journal, *out]:
                        if x.reference != m.reference or x.product != m.product:
                            continue
                        sign = 1 if x.type is MovementType.TRANSFER_OUT else -1 if x.type is MovementType.RECEIPT else 0
                        for s in x.serials:
                            travelling[s] += sign * (-1 if x.reversal_of else 1)
                    sn = [s for s, q in travelling.items() if q > 0.5][: round(m.qty)]
                if not sn and m.type is MovementType.RECEIPT and not transfer:
                    sn = _next_serials(ds, m.product, round(m.qty), {s for x in out for s in x.serials})
                upd["serials"] = sn
        elif m.type is MovementType.ADJUSTMENT and m.qty < 0 and m.batch is None and prod is not None:
            pieces = [(b, -q) for b, q in pick(ds, [*journal, *out], node, -m.qty, m.date, stock_type=m.stock_type)]
        elif m.type in OUT and m.batch is None and prod is not None:
            pieces = pick(ds, [*journal, *out], node, m.qty, m.date, stock_type=m.stock_type)
        if m.type in OUT and o.get("batch"):
            pieces = [(o["batch"], m.qty)]
        serial_parts: dict[str | None, list[str]] = {}
        if prod and prod.serial_numbers and (m.type in OUT or m.type is MovementType.ADJUSTMENT):
            supplied = list(o.get("serials") or m.serials)
            if supplied and len(set(supplied)) != len(supplied):
                raise StockError("serial numbers must be unique within a posting")
            taken: set[str] = set()
            for b, q in pieces:
                if not math.isclose(abs(q), round(abs(q)), abs_tol=EPS):
                    raise StockError(f"{_name(ds, m.product)} is serialised: post whole units")
                n = round(abs(q))
                if m.type in OUT or q < 0:
                    available = _serials_here([*journal, *out], node, m.date, b, m.stock_type)
                    available = [sn for sn in available if sn not in taken]
                    sn = [sn for sn in supplied if sn in available] if supplied else available[:n]
                    if len(sn) != n:
                        raise StockError(f"{_name(ds, m.product)}: {n} available serial numbers are required in this lot")
                else:
                    sn = _next_serials(ds, m.product, n, taken | {s for x in out for s in x.serials})
                serial_parts[b] = sn
                taken.update(sn)
            if supplied and set(supplied) != taken:
                raise StockError("serial numbers do not match the available stock in the selected lots")
        if prod and prod.serial_numbers and m.type not in (MovementType.ADJUSTMENT, MovementType.STATUS):
            sn = [s for group in serial_parts.values() for s in group] if serial_parts else upd.get("serials", m.serials)
            if len(sn) != round(m.qty) or len(set(sn)) != len(sn):
                raise StockError(f"{_name(ds, m.product)} is serialised: give {round(m.qty)} serial numbers, one per "
                                 f"unit ({len(sn)} given)")
            if m.type is MovementType.RECEIPT:
                existing = {s for x in [*journal, *out] if x.product == m.product and x.signed > 0 for s in x.serials}
                if not transfer and any(s in existing for s in sn):
                    raise StockError("a received serial number already exists in the journal")
        first = True
        done[i] = []
        serial_offset = 0
        for b, q in pieces:
            if abs(q) <= EPS:
                continue
            x = m.model_copy(update={**upd, "batch": b, "qty": round(q, 6), "id": m.id if first else next(fresh)})
            if prod and prod.serial_numbers and m.type is not MovementType.STATUS:
                piece_serials = serial_parts.get(b) if serial_parts else upd.get("serials", m.serials)[serial_offset:serial_offset + round(abs(q))]
                x = x.model_copy(update={"serials": piece_serials})
                serial_offset += round(abs(q))
            done[i].append(x)
            out.append(x)
            first = False
    out = [x for i in range(len(moves)) for x in done.get(i, [])]
    if moves and not out:
        raise StockError("quantity is too small to post at six-decimal precision")
    notes += _negative(ds, journal, out, on)
    held = [f"{_n(x.qty)} of {_name(ds, x.product)} into quality inspection" for x in out
            if x.stock_type is StockType.QUALITY and x.type is MovementType.RECEIPT]
    notes += held
    for x in out:
        if x.batch and x.type in OUT and (x.product, x.batch) in {(b.product, b.id) for b in ds.batches}:
            rec = next(b for b in ds.batches if (b.product, b.id) == (x.product, x.batch))
            if rec.expires_on and rec.expires_on < x.date:
                notes.append(f"batch {x.batch} of {_name(ds, x.product)} expired on {rec.expires_on.isoformat()}")
    return out, batches, notes


def _arriving(ds: Dataset, journal: list[GoodsMovement], rc: ScheduledReceipt, qty: float) -> list[tuple[str | None, float]]:
    """The batches a transfer arrives in: those shipped on it and not yet received, first expiring first."""
    shipped: dict[str | None, float] = defaultdict(float)
    for x in journal:
        if x.reference == rc.id and x.product == rc.product:
            if x.type is MovementType.TRANSFER_OUT:
                shipped[x.batch] += x.net
            elif x.type is MovementType.RECEIPT and x.location == rc.location:
                shipped[x.batch] -= x.net
    exp = {b.id: b.expires_on for b in ds.batches if b.product == rc.product}
    out: list[tuple[str | None, float]] = []
    left = qty
    for b, q in sorted(shipped.items(), key=lambda kv: (kv[0] is not None, exp.get(kv[0] or "") or date.max, kv[0] or "")):
        if left <= EPS or q <= EPS:
            continue
        take = min(q, left)
        out.append((b, take))
        left -= take
    if left > EPS:
        out.append((None, left))
    return out


def _lowest(xs: list[GoodsMovement], start: date) -> float:
    """The lowest running balance of ``xs`` on any day from ``start`` on (a back-dated posting must not take a
    later day of the journal below zero either)."""
    days = sorted({x.date for x in xs if x.date >= start} | {start})
    return min(sum(x.signed for x in xs if x.date <= d) for d in days)


def _negative(ds: Dataset, journal: list[GoodsMovement], moves: list[GoodsMovement], on: date) -> list[str]:
    """Places the posting takes below zero in unrestricted stock: refused, or noted, by the company's rule. A
    back-dated posting is checked against every later day of the journal too: taking stock out on the 1st that a
    posting of the 2nd already took leaves the 2nd below zero."""
    touched = {(m.location, m.product) for m in moves if m.signed < 0 and m.stock_type is StockType.UNRESTRICTED}
    short = []
    for k in sorted(touched):
        first = min([on, *(m.date for m in moves if (m.location, m.product) == k)])
        bal = _lowest([x for x in [*journal, *moves] if (x.location, x.product) == k
                       and x.stock_type is StockType.UNRESTRICTED], first)
        if bal < -EPS:
            short.append((k, bal))
    if NegativeStock(ds.execution.negative_stock) is NegativeStock.REFUSE:
        for m in moves:
            if m.signed >= 0:
                continue
            qty = _lowest([x for x in [*journal, *moves] if x.location == m.location and x.product == m.product
                           and x.batch == m.batch and x.stock_type == m.stock_type], m.date)
            if qty < -EPS:
                raise StockError(f"not enough in stock in batch {m.batch or '(unbatched)'} of {m.product} at {m.location}: "
                                 "the company does not allow stock below zero")
    if not short:
        return []
    rule = NegativeStock(ds.execution.negative_stock)
    words = ", ".join(f"{_name(ds, p)} at {_at(ds, lo)} would go to {_n(q)}" for (lo, p), q in short[:3])
    if rule is NegativeStock.REFUSE:
        raise StockError(f"not enough in stock: {words}. Post the missing receipt or a count first (the company does "
                         "not allow stock below zero)")
    if rule is NegativeStock.FOUND:
        return [f"not enough in stock by the journal: {words.replace('would go', 'goes')} (the difference is counted as "
                "found when the week moves on)"]
    return [f"not enough in stock by the journal: {words.replace('would go', 'goes')} (post the missing receipt, or a "
            "count)"]


# ---- short receipts (R16) ------------------------------------------------------------------------------
def short_orders(ds: Dataset, parts: set[Node], on: date) -> list[ShortOrder]:
    """Firm orders that take one of ``parts`` and that it no longer covers in full: usable stock on ``on`` and the
    open receipts of the part due by an order's start go to the orders in the order they start; an order whose
    open reservation is more than what is left is short, and ``can_make`` is what the part it gets covers. When
    receipts due after its start bring the rest, ``complete_on`` says when: the order is late rather than short."""
    from .lots import planning_stock
    from .stock import open_orders
    if not parts:
        return []
    have = planning_stock(ds, before(ds, on + timedelta(days=1)), on + timedelta(days=1))
    rows = {r.id: r for r in open_orders(ds, on)}
    tol = ds.execution.delivery_tolerance
    finals = {m.reference for m in ds.movements if m.final and m.reference}
    issued: dict[tuple[str, str, str], float] = defaultdict(float)
    for m in ds.movements:
        if m.reference and m.type in (MovementType.ISSUE, MovementType.TRANSFER_OUT) and (m.location, m.product) in parts:
            issued[(m.reference, m.location, m.product)] += m.net
    out: list[ShortOrder] = []
    for node in sorted(parts):
        loc, part = node
        incoming: list[tuple[date, float]] = []
        for rc in ds.receipts:
            if (rc.location, rc.product) != node:
                continue
            row = rows.get(rc.id)
            if row is None or rc.id in finals or row.open <= row.ordered * tol + EPS:
                continue
            incoming.append([rc.expected_date, row.open])
        users = []
        for rc in ds.receipts:
            for rv in rc.reservations:
                if (rv.location, rv.product) != node:
                    continue
                need = (rv.required_qty if rv.required_qty is not None else rv.qty) - issued[(rc.id, loc, part)]
                if need > EPS:
                    users.append((rv.date, rc, need))
        users.sort(key=lambda u: (u[0], u[1].id))
        avail = have.get(node, 0.0)
        used_in = 0
        incoming.sort()
        for when, rc, need in users:
            while used_in < len(incoming) and incoming[used_in][0] <= when:
                avail += incoming[used_in][1]
                used_in += 1
            if need <= avail + EPS:
                avail -= need
                continue
            got = max(0.0, avail)
            avail = 0.0
            row = rows.get(rc.id)
            open_q = row.open if row else rc.qty
            can = open_q * got / need if need > EPS else open_q
            prod = ds.product_by_id.get(rc.product)
            if prod is not None and prod.whole:
                can = math.floor(can + 1e-9)
            # N110: the rest may still be coming, only after the order starts: it is late, not short
            rest, until, k = need - got, None, used_in
            while k < len(incoming) and rest > EPS:
                take = min(rest, incoming[k][1])
                incoming[k][1] -= take
                rest -= take
                if rest <= EPS:
                    until = incoming[k][0]
                k += 1
            out.append(ShortOrder(order=rc.id, product=rc.product, part=part, location=loc, needs=round(need, 6),
                                  available=round(got, 6), can_make=round(can, 6), qty=round(open_q, 6),
                                  starts=when, complete_on=until))
    return out


def shorten(ds: Dataset, oid: str, qty: float) -> tuple[Dataset, ActionReport]:
    """Make a firm production or transfer order smaller (≈ changing the order quantity in CO02): its open quantity
    and its reservations in proportion. What was already received stays."""
    rc = next((r for r in ds.receipts if r.id == oid), None)
    if rc is None or rc.kind is ReceiptKind.PURCHASE:
        raise StockError(f"{oid} is not an open production or transfer order (change a purchase order in Buying)")
    ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
    got = sum(m.net for m in ds.movements if m.reference == oid and m.type is MovementType.RECEIPT
              and m.product == rc.product and m.location == rc.location)
    new = float(qty)
    if new < got - EPS:
        raise StockError(f"{oid}: {_n(got)} are already received; the order cannot be less")
    if new <= EPS:
        raise StockError(f"{oid}: to make nothing, cancel the order instead")
    if new >= ordered - EPS:
        raise StockError(f"{oid} is for {_n(ordered)}: shortening makes it smaller")
    k = new / ordered
    from ..plan.structure import needs
    ps = ds.production_source_by_id.get(rc.source or "")
    bom = {n.product: n for n in needs(ds, ps, rc.start_date or ds.settings.planning_start)} if ps else {}
    rvs = []
    targets = []
    for rv in (rc.original_reservations or rc.reservations):
        used = sum(m.net for m in ds.movements if m.reference == oid and m.location == rv.location
                   and m.product == rv.product and m.type in (MovementType.ISSUE, MovementType.TRANSFER_OUT))
        part = bom.get(rv.product)
        ratio = part.qty(new) / part.qty(ordered) if part and part.qty(ordered) > EPS else k
        required = (rv.required_qty if rv.required_qty is not None else rv.qty) * ratio
        targets.append(rv.model_copy(update={"qty": required, "required_qty": required}))
        rvs.append(rv.model_copy(update={"qty": round(max(0.0, required - used), 6), "required_qty": required}))
    open_new = new - (ordered - rc.qty)
    upd = {"qty": round(max(open_new, EPS), 6), "reservations": rvs, "original_reservations": targets,
           "ordered_qty": round(new, 6) if rc.ordered_qty is not None else None}
    receipts = [r.model_copy(update=upd) if r.id == oid else r for r in ds.receipts]
    return (ds.model_copy(update={"receipts": receipts}),
            ActionReport(ok=True, message=f"{oid} shortened from {_n(ordered)} to {_n(new)}; its parts in proportion. "
                                          "Plan again to cover the rest."))


# ---- stock postings ---------------------------------------------------------------------------------------
def _stock_node(ds: Dataset, location: str, product: str) -> Node:
    if location not in ds.location_by_id or product not in ds.product_by_id:
        raise StockError(f"there is no place {location!r} or product {product!r}")
    if ds.location_type(location) not in STOCKING_LOCATION_TYPES:
        raise StockError(f"{_at(ds, location)} does not hold stock")
    return (location, product)


def move_stock(ds: Dataset, location: str, product: str, qty: float | None, from_type: StockType,
               to_type: StockType, batch: str | None = None, on: date | None = None, note: str = "",
               serials: list[str] | None = None) -> tuple[Dataset, ActionReport]:
    """Move stock between stock types at one place (≈ MIGO 321 release from inspection, 350 to blocked, 343/344
    blocked ↔ unrestricted): a pair of movements that sums to zero. ``qty`` None: all of it (in the batch). The
    default date is the end of the day before the planning start: the stock the plan starts from changes at once."""
    ds = _with_openings(ds)
    node = _stock_node(ds, location, product)
    if from_type is to_type:
        raise StockError("the stock is already of that type")

    def match(day: date) -> list:
        return [lot for lot in node_lots(ds, before(ds, day + timedelta(days=1)), node)
                if lot.stock_type is from_type and lot.qty > EPS and (batch is None or lot.batch == batch)]
    on = on or _default_day(ds, node, lambda day: sum(x.qty for x in match(day)), qty)
    lots = match(on)
    have = sum(lot.qty for lot in lots)
    q = have if qty is None else float(qty)
    if q <= EPS:
        raise StockError(f"there is no {WORDS[from_type]} stock of {_name(ds, product)} at {_at(ds, location)}"
                         + (f" in batch {batch}" if batch else ""))
    if q > have + EPS:
        raise StockError(f"only {_n(have)} of {_name(ds, product)} at {_at(ds, location)} is {WORDS[from_type]}"
                         + (f" in batch {batch}" if batch else ""))
    ids = movement_ids(ds)
    moves: list[GoodsMovement] = []
    left = q
    text = (note or f"{WORDS[from_type].capitalize()} → {WORDS[to_type]}")[:200]
    for lot in lots:
        if left <= EPS:
            break
        take = min(left, lot.qty)
        left -= take
        serial_group = list(serials or [])
        if ds.product_by_id[product].serial_numbers:
            if not math.isclose(take, round(take), abs_tol=EPS):
                raise StockError("serialised stock can only change type in whole units")
            available = _serials_here(before(ds, on + timedelta(days=1)), node, on, lot.batch, from_type)
            serial_group = [s for s in serial_group if s in available] if serial_group else available[:round(take)]
            if len(serial_group) != round(take) or len(set(serial_group)) != len(serial_group):
                raise StockError("stock type changes need one available serial number per whole unit in each lot")
        for t, sign in ((from_type, -1.0), (to_type, 1.0)):
            moves.append(GoodsMovement(id=next(ids), date=on, type=MovementType.STATUS, location=location,
                                       product=product, qty=round(sign * take, 6), batch=lot.batch, stock_type=t,
                                       note=text, serials=serial_group))
    if serials is not None and ds.product_by_id[product].serial_numbers:
        used = [s for m in moves if m.qty < 0 for s in m.serials]
        if len(set(serials)) != len(serials) or sorted(used) != sorted(serials):
            raise StockError("serial numbers do not match the stock being moved")
    moves, _, notes = complete(ds, moves, on)
    verb = {StockType.UNRESTRICTED: "released", StockType.BLOCKED: "blocked", StockType.QUALITY: "put into inspection"}
    msg = (f"{_n(q)} of {_name(ds, product)} at {_at(ds, location)} {verb[to_type]}"
           + (f" (batch {batch})" if batch else "") + f" on {on.isoformat()}" + _when(ds, on)
           + ("; " + "; ".join(notes) if notes else "") + ".")
    return (_settle(ds.model_copy(update={"movements": [*ds.movements, *moves]}), {node}, on),
            ActionReport(ok=True, message=msg, movements=[m.id for m in moves], doc=moves[0].doc if moves else None))


def _default_day(ds: Dataset, node: Node, have, qty: float | None) -> date:
    """The day a stock posting is dated when none is given: the end of the day before the planning start, so the
    stock the plan starts from changes at once; or, for goods that came in this week, the day they were last moved."""
    early = ds.settings.planning_start - timedelta(days=1)
    q0 = have(early)
    if q0 > EPS and (qty is None or q0 >= float(qty) - EPS):
        return early
    last = max((m.date for m in ds.movements if (m.location, m.product) == node), default=early)
    return max(last, ds.settings.planning_start)


def _when(ds: Dataset, on: date) -> str:
    return ("; the plan starts from it" if on < ds.settings.planning_start
            else "; it counts when the plan moves past this date")


def _settle(ds: Dataset, nodes: set[Node], on: date) -> Dataset:
    """A stock posting dated before the planning start changes the stock the plan starts from, as a count does."""
    return _sync_on_hand(ds, nodes) if on < ds.settings.planning_start else ds


WORDS = {StockType.UNRESTRICTED: "unrestricted", StockType.QUALITY: "in quality inspection",
         StockType.BLOCKED: "blocked"}


def scrap(ds: Dataset, location: str, product: str, qty: float | None, stock_type: StockType = StockType.UNRESTRICTED,
          batch: str | None = None, on: date | None = None, note: str = "", expired_only: bool = False
          ) -> tuple[Dataset, ActionReport]:
    """Scrap stock (≈ MIGO 551/553/555): of a batch, of a stock type, or with ``expired_only`` every expired batch
    at the place; ``qty`` None: all of it. The default date is the day before the planning start (see
    :func:`move_stock`)."""
    ds = _with_openings(ds)
    node = _stock_node(ds, location, product)

    def match(day: date) -> list:
        return [lot for lot in node_lots(ds, before(ds, day + timedelta(days=1)), node) if lot.qty > EPS
                and (batch is None or lot.batch == batch) and (expired_only or lot.stock_type is stock_type)
                and (not expired_only or (lot.expired(day) and lot.stock_type is not StockType.BLOCKED))]
    on = on or _default_day(ds, node, lambda day: sum(x.qty for x in match(day)), qty)
    lots = match(on)
    have = sum(lot.qty for lot in lots)
    q = have if qty is None else float(qty)
    if q <= EPS:
        raise StockError(f"there is nothing to scrap of {_name(ds, product)} at {_at(ds, location)}"
                         + (" that has expired" if expired_only else ""))
    if q > have + EPS:
        raise StockError(f"only {_n(have)} of {_name(ds, product)} at {_at(ds, location)} can be scrapped")
    ids = movement_ids(ds)
    moves = []
    left = q
    for lot in lots:
        if left <= EPS:
            break
        take = min(left, lot.qty)
        left -= take
        moves.append(GoodsMovement(id=next(ids), date=on, type=MovementType.SCRAP, location=location, product=product,
                                   qty=round(take, 6), batch=lot.batch, stock_type=lot.stock_type,
                                   note=(note or ("Expired" if expired_only or lot.expired(on) else "Scrapped"))[:200]))
    moves, _, notes = complete(ds, moves, on)
    msg = (f"{_n(q)} of {_name(ds, product)} at {_at(ds, location)} scrapped on {on.isoformat()}"
           + (f" from {len(moves)} batch{'es' if len(moves) != 1 else ''}" if any(m.batch for m in moves) else "")
           + _when(ds, on) + ("; " + "; ".join(notes) if notes else "") + ".")
    return (_settle(ds.model_copy(update={"movements": [*ds.movements, *moves]}), {node}, on),
            ActionReport(ok=True, message=msg, movements=[m.id for m in moves], doc=moves[0].doc))


def reverse(ds: Dataset, movement: str, on: date | None = None, note: str = "") -> tuple[Dataset, ActionReport]:
    """Take back a posting (≈ MIGO cancel, 102/262/…): every movement of its material document gets a reversal with
    the same quantity counted the other way. The order it was posted against opens again as far as it takes back."""
    m0 = next((m for m in ds.movements if m.id == movement), None)
    if m0 is None:
        raise StockError(f"{movement} is not in the journal")
    if m0.reversal_of:
        raise StockError(f"{movement} is itself a reversal (of {m0.reversal_of}); post the movement again instead")
    group = [m for m in ds.movements if m0.doc and m.doc == m0.doc] or [m0]
    done = {m.reversal_of for m in ds.movements if m.reversal_of}
    group = [m for m in group if m.id not in done and not m.reversal_of]
    if not group:
        raise StockError(f"{movement} is already reversed")
    refs = {m.reference for m in group if m.reference}
    missing = [c.id for c in ds.closed_orders if c.id in refs and not c.cancelled and c.source_order is None]
    if missing:
        raise StockError(f"{', '.join(missing)} closed before its original order was retained: restore the order "
                         "from a saved version before reversing its delivery")
    day = on or max(m0.date, ds.settings.planning_start)     # a week already moved on is not posted into again
    ids = movement_ids(ds)
    moves = [m.model_copy(update={"id": next(ids), "date": day, "reversal_of": m.id, "final": False,
                                  "note": (note or f"Reversal of {m.id}")[:200]}) for m in group]
    doc = next_doc(ds)
    moves = [m.model_copy(update={"doc": doc}) for m in moves]
    for m in moves:
        if (inv := blocked_by_count(ds, (m.location, m.product))) is not None:
            raise StockError(f"{_name(ds, m.product)} at {_at(ds, m.location)} is being counted ({inv.id}): post the "
                             "count first, or cancel it")
    notes = _negative(ds, [*ds.movements, *pending_openings(ds)], moves, day)
    ref = m0.reference
    msg = (f"{m0.doc or movement} reversed on {day.isoformat()}: {len(moves)} movement{'s' if len(moves) != 1 else ''} "
           "taken back" + (f"; {ref} is open again for what they carried" if ref
                           and not any(c.id == ref and c.cancelled for c in ds.closed_orders) else "")
           + ("; " + "; ".join(notes) if notes else "") + ".")
    reopened = {m.reference for m in group if m.reference}
    receipts, demand, confs = list(ds.receipts), list(ds.demand), list(ds.confirmations)
    closed = []
    for c in ds.closed_orders:
        if c.id not in reopened or c.cancelled or c.source_order is None:
            closed.append(c)
            continue
        if c.kind == "sales":
            if not any(d.id == c.id for d in demand):
                demand.append(DemandRecord.model_validate(c.source_order))
                confs.extend(Confirmation.model_validate(cf) for cf in c.source_confirmations)
        elif not any(r.id == c.id for r in receipts):
            receipts.append(ScheduledReceipt.model_validate(c.source_order))
    return (ds.model_copy(update={"movements": [*ds.movements, *moves], "receipts": receipts,
                                 "demand": demand, "confirmations": confs, "closed_orders": closed}),
            ActionReport(ok=True, message=msg, movements=[m.id for m in moves], doc=doc))


# ---- physical inventory (MI01 / MI04 / MI07) ----------------------------------------------------------------
def count_doc(ds: Dataset, nodes: list[Node], on: date | None = None, block: bool = True,
              note: str = "") -> tuple[Dataset, ActionReport]:
    """Make a physical inventory document: the places and products to count on ``on`` (default: the day before the
    planning start), each lot's book stock frozen now. With ``block``, postings for them wait until it is posted."""
    ds = _with_openings(ds)
    if not nodes:
        raise StockError("say which places and products to count")
    day = on or ds.settings.planning_start - timedelta(days=1)
    busy = {(it.location, it.product): d.id for d in ds.inventory_docs if d.status == "open" for it in d.items}
    items: list[CountItem] = []
    journal = before(ds, day + timedelta(days=1))
    for loc, prod in dict.fromkeys(nodes):
        _stock_node(ds, loc, prod)
        if (loc, prod) in busy:
            raise StockError(f"{_name(ds, prod)} at {_at(ds, loc)} is on {busy[(loc, prod)]} already")
        lots = [lot for lot in node_lots(ds, journal, (loc, prod)) if abs(lot.qty) > EPS]
        if not lots:
            items.append(CountItem(location=loc, product=prod, book_qty=0.0))
        for lot in lots:
            items.append(CountItem(location=loc, product=prod, batch=lot.batch, stock_type=lot.stock_type,
                                   book_qty=round(lot.qty, 6)))
    doc = InventoryDoc(id=next_doc(ds, "PI"), date=day, block=block, items=items, note=note[:200])
    return (ds.model_copy(update={"inventory_docs": [*ds.inventory_docs, doc]}),
            ActionReport(ok=True, doc=doc.id,
                         message=f"{doc.id}: {len(items)} line{'s' if len(items) != 1 else ''} to count on "
                                 f"{day.isoformat()}, book stock frozen"
                                 + ("; postings for them wait until it is posted" if block else "") + "."))


def _doc(ds: Dataset, did: str) -> InventoryDoc:
    d = next((x for x in ds.inventory_docs if x.id == did), None)
    if d is None:
        raise StockError(f"{did} is not a physical inventory document")
    if d.status != "open":
        raise StockError(f"{did} is {d.status} already")
    return d


def _replace(ds: Dataset, d: InventoryDoc) -> list[InventoryDoc]:
    return [d if x.id == d.id else x for x in ds.inventory_docs]


def enter_counts(ds: Dataset, did: str, counts: list[dict]) -> tuple[Dataset, ActionReport]:
    """Enter what was found (``[{"location", "product", "batch"?, "stock_type"?, "qty"}]``); a batch found that
    the book does not have gets a line of its own."""
    d = _doc(ds, did)
    items = [it.model_copy() for it in d.items]
    for c in counts:
        loc, prod = str(c.get("location") or ""), str(c.get("product") or "")
        b = c.get("batch") or None
        t = StockType(c.get("stock_type") or "unrestricted")
        q = c.get("qty")
        if q is not None and float(q) < -EPS:
            raise StockError(f"{prod} at {loc}: a count cannot be negative")
        it = next((x for x in items if (x.location, x.product, x.batch, x.stock_type) == (loc, prod, b, t)), None)
        if it is None:
            if not any((x.location, x.product) == (loc, prod) for x in items):
                raise StockError(f"{_name(ds, prod)} at {_at(ds, loc)} is not on {did}")
            it = CountItem(location=loc, product=prod, batch=b, stock_type=t, book_qty=0.0)
            items.append(it)
        it.counted = None if q is None else round(float(q), 6)
    left = sum(1 for x in items if x.counted is None)
    return (ds.model_copy(update={"inventory_docs": _replace(ds, d.model_copy(update={"items": items}))}),
            ActionReport(ok=True, message=f"{did}: counts entered" + (f"; {left} line{'s' if left != 1 else ''} still "
                                                                       "to count" if left else "; ready to post")))


def post_counts(ds: Dataset, did: str, uncounted_zero: bool = False) -> tuple[Dataset, ActionReport]:
    """Post the differences between the counts and the frozen book stock (≈ MI07), dated the count date. Lines not
    counted are posted as zero only with ``uncounted_zero``."""
    d = _doc(ds, did)
    missing = [it for it in d.items if it.counted is None]
    if missing and not uncounted_zero:
        raise StockError(f"{did}: {len(missing)} line{'s are' if len(missing) != 1 else ' is'} not counted yet "
                         "(count them, or post them as zero)")
    ids = movement_ids(ds)
    moves = []
    for it in d.items:
        found = it.counted if it.counted is not None else 0.0
        diff = round(found - it.book_qty, 6)
        if abs(diff) <= EPS:
            continue
        moves.append(GoodsMovement(id=next(ids), date=d.date, type=MovementType.ADJUSTMENT, location=it.location,
                                   product=it.product, qty=diff, batch=it.batch, stock_type=it.stock_type,
                                   note=f"Physical inventory {did}: {_n(it.book_qty)} → {_n(found)}"))
    doc_no = None
    new = ds
    if moves:
        moves, _, _ = complete(ds, moves, d.date, counting=True)
        doc_no = moves[0].doc
        new = ds.model_copy(update={"movements": [*ds.movements, *moves]})
    done = d.model_copy(update={"status": "posted", "posted_doc": doc_no})
    new = new.model_copy(update={"inventory_docs": _replace(new, done)})
    if d.date < ds.settings.planning_start:
        new = _sync_on_hand(new, {(it.location, it.product) for it in d.items})
    plus = sum(m.qty for m in moves if m.qty > 0)
    minus = -sum(m.qty for m in moves if m.qty < 0)
    msg = (f"{did} posted: " + (f"{len(moves)} difference{'s' if len(moves) != 1 else ''} (+{_n(plus)}, −{_n(minus)})"
                                if moves else "the counts match the book")
           + (" and planning's stock follows" if d.date < ds.settings.planning_start else
              "; they count when the plan moves past the count date") + ".")
    return new, ActionReport(ok=True, message=msg, movements=[m.id for m in moves], doc=doc_no)


def cancel_counts(ds: Dataset, did: str) -> tuple[Dataset, ActionReport]:
    d = _doc(ds, did)
    return (ds.model_copy(update={"inventory_docs": _replace(ds, d.model_copy(update={"status": "cancelled"}))}),
            ActionReport(ok=True, message=f"{did} cancelled; nothing posted" + (", postings are open again" if d.block
                                                                                  else "") + "."))


def _sync_on_hand(ds: Dataset, nodes: set[Node]) -> Dataset:
    """A count dated before the planning start sets planning's on-hand from the journal, as a quick count does."""
    from ..model import LocationProduct
    from .lots import planning_stock
    start = ds.settings.planning_start
    have = planning_stock(ds, before(ds, start), start)
    lps = [lp.model_copy() for lp in ds.location_products]
    by = {(lp.location, lp.product): lp for lp in lps}
    for k in sorted(nodes):
        if k not in by:
            by[k] = LocationProduct(location=k[0], product=k[1])
            lps.append(by[k])
        by[k].on_hand = max(0.0, round(have.get(k, 0.0), 6))
    return Dataset.model_validate(ds.model_copy(update={"location_products": lps}).model_dump())


def _with_openings(ds: Dataset) -> Dataset:
    openings = pending_openings(ds)
    return ds.model_copy(update={"movements": [*ds.movements, *openings]}) if openings else ds
