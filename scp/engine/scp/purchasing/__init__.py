"""Procure-to-pay (Phase E, ≈ S/4 MM purchasing for a small buyer).

* **Requisitions** are the supply plan's purchases (MRP creates purchase requisitions for bought materials). Each
  lists the sources that could fill it: price for that quantity (price scales), lead time, when it would arrive and
  whether that is in time. Blocked suppliers and blocked sources are shown with the reason and never used.
* **Creating purchase orders** turns chosen requisitions into orders, one per supplier, receiving place and
  currency (≈ ME59N). A different source than planning chose can be picked per line: its minimum and rounding apply,
  and its lead time dates the line (never earlier than asked, later when it cannot make it). An order worth more
  than the approval limit starts unapproved.
* **Actions** on an order: approve, send, record the supplier's confirmation (date and quantity), receive goods
  (partial or final, within the supplier's over-delivery tolerance), change a line, cancel lines with nothing
  received. Each is a plain change to the dataset; receiving posts goods-receipt movements that the roll-forward
  books into stock and uses to close the line.
* **Views**: every order with its lines' status, and a supplier scorecard from the closed-order log.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date

from ..model import Dataset, GoodsMovement, MovementType, PurchaseOrder, ReceiptKind, ScheduledReceipt
from ..plan import PlanResult
from ..plan.costing import fx
from ..plan.leadtime import schedule_buy
from .result import (
    ActionReport, CreatedPo, CreateReport, InfoRecord, PoLine, PoView, PurchasingTotals, PurchasingView, Requisition,
    SourceChoice, VendorRow,
)

EPS = 1e-6


class PurchasingError(ValueError):
    """An action the data does not allow; the message says why in plain words."""


# ---- helpers ---------------------------------------------------------------------------------------
def next_numbers(ds: Dataset) -> dict[str, int]:
    """Highest number used per prefix (PRD, PO, STO) by receipts, closed orders and purchase order headers."""
    out: dict[str, int] = defaultdict(int)
    ids = [r.id for r in ds.receipts] + [c.id for c in ds.closed_orders] + [p.id for p in ds.purchase_orders]
    for oid in ids:
        m = re.fullmatch(r"(PRD|PO|STO)-(\d+)", oid)
        if m:
            out[m.group(1)] = max(out[m.group(1)], int(m.group(2)))
    return out


def _next_movement(ds: Dataset, taken: set[str]) -> str:
    n = 0
    for mid in [m.id for m in ds.movements] + list(taken):
        x = re.fullmatch(r"GM-(\d+)", mid)
        if x:
            n = max(n, int(x.group(1)))
    return f"GM-{n + 1:05d}"


def _currency(ds: Dataset, cur: str | None) -> str:
    return cur or ds.settings.currency


def _lot(pu, qty: float) -> float:
    q = max(qty, pu.moq)
    if pu.rounding_qty:
        q = math.ceil(q / pu.rounding_qty - 1e-9) * pu.rounding_qty
    return q


def received(ds: Dataset) -> dict[str, float]:
    """Goods received per order line: every receipt movement posted against it, whatever its date."""
    out: dict[str, float] = defaultdict(float)
    for m in ds.movements:
        if m.type is MovementType.RECEIPT and m.reference:
            out[m.reference] += m.qty
    return out


def _last_receipt(ds: Dataset) -> dict[str, date]:
    out: dict[str, date] = {}
    for m in ds.movements:
        if m.type is MovementType.RECEIPT and m.reference:
            out[m.reference] = max(out.get(m.reference, m.date), m.date)
    return out


def _supplier_of(ds: Dataset, rc: ScheduledReceipt) -> str | None:
    po = ds.purchase_order_by_id.get(rc.po or "")
    if po is not None:
        return po.supplier
    pu = ds.purchasing_source_by_id.get(rc.source or "")
    return pu.supplier if pu else rc.source


def _blocked_reason(ds: Dataset, pu) -> str:
    v = ds.vendor(pu.supplier)
    if v.blocked:
        return f"{pu.supplier} is blocked for purchasing" + (f": {v.block_reason}" if v.block_reason else "")
    if pu.blocked:
        return f"source {pu.id} is blocked in the source list"
    return ""


def _valid(pu, d: date) -> bool:
    return (pu.valid_from is None or pu.valid_from <= d) and (pu.valid_to is None or pu.valid_to >= d)


def _choice(ds: Dataset, pu, qty: float, order_date: date, need_by: date, assigned: bool) -> SourceChoice:
    q = qty if assigned else _lot(pu, qty)
    sch = schedule_buy(ds, pu.id, start=order_date)
    price = pu.price_for(q)
    return SourceChoice(source_id=pu.id, supplier=pu.supplier, price=price, currency=_currency(ds, pu.currency),
                        value=q * price * fx(ds, pu.currency) * (1.0 + pu.duty_rate), qty=q,
                        lead_time_days=pu.lead_time_days, arrives=sch.due_date,
                        days_late=max(0, (sch.available_date - need_by).days), fixed=pu.fixed, assigned=assigned,
                        blocked=_blocked_reason(ds, pu))


# ---- requisitions ----------------------------------------------------------------------------------
def requisitions(ds: Dataset, plan: PlanResult) -> list[Requisition]:
    start = ds.settings.planning_start
    window = ds.purchasing.release_window_days
    out = []
    for o in plan.orders:
        if o.kind != "buy" or not o.convertible:
            continue
        pu = ds.purchasing_source_by_id[o.source_id]
        order_on = max(o.start_date, start)
        choices = []
        for alt in ds.purchasing_sources:
            if alt.location != o.location or alt.product != o.product or not _valid(alt, o.need_date):
                continue
            choices.append(_choice(ds, alt, o.qty, order_on, o.need_date, alt.id == pu.id))
        choices.sort(key=lambda c: (not c.assigned, bool(c.blocked), c.days_late, c.value))
        price = pu.price_for(o.qty)
        out.append(Requisition(
            id=o.id, location=o.location, product=o.product, qty=o.qty, need_date=o.need_date,
            order_date=o.start_date, due_date=o.due_date, source_id=pu.id, supplier=pu.supplier, price=price,
            currency=_currency(ds, pu.currency), value=o.qty * price * fx(ds, pu.currency) * (1.0 + pu.duty_rate),
            due_now=(o.start_date - start).days <= window, late=o.start_in_past or o.start_date < start,
            choices=choices))
    out.sort(key=lambda r: (r.order_date, r.supplier, r.product, r.id))
    return out


def create_purchase_orders(ds: Dataset, plan: PlanResult, lines: list[dict] | None = None,
                           order_date: date | None = None) -> tuple[Dataset, CreateReport]:
    """Turn requisitions into purchase orders. ``lines``: ``{"id": requisition, "source_id"?: …, "qty"?: …}``;
    None = every requisition due now, on its planned source."""
    rep = CreateReport(ok=False, created=[], lines={}, skipped={})
    if not plan.ok:
        return ds, rep
    today = order_date or ds.settings.planning_start
    by_id = {o.id: o for o in plan.orders}
    if lines is None:
        lines = [{"id": r.id} for r in requisitions(ds, plan) if r.due_now]
    groups: dict[tuple[str, str, str], list[tuple[str, object, float, date, list[str]]]] = defaultdict(list)
    for ln in lines:
        rid = ln["id"]
        o = by_id.get(rid)
        if o is None:
            rep.skipped[rid] = "not in the current plan (plan again)"
            continue
        if o.kind != "buy":
            rep.skipped[rid] = f"a planned {'production' if o.kind == 'make' else 'transfer'}, not a purchase"
            continue
        sid = ln.get("source_id") or o.source_id
        pu = ds.purchasing_source_by_id.get(sid)
        if pu is None or pu.location != o.location or pu.product != o.product:
            rep.skipped[rid] = f"source {sid} does not sell {o.product} to {o.location}"
            continue
        why = _blocked_reason(ds, pu)
        if why:
            rep.skipped[rid] = why
            continue
        if not _valid(pu, o.need_date):
            rep.skipped[rid] = f"source {sid} is not valid on {o.need_date.isoformat()}"
            continue
        notes: list[str] = []
        qty = float(ln.get("qty") or o.qty)
        if qty <= EPS:
            rep.skipped[rid] = "the quantity must be more than zero"
            continue
        if sid != o.source_id:
            q2 = _lot(pu, qty)
            if q2 > qty + EPS:
                notes.append(f"{o.product}: {q2:,.0f} instead of {qty:,.0f} ({pu.supplier}'s minimum or pack size)")
            qty = q2
        due = o.due_date
        if sid != o.source_id or today > o.start_date:
            earliest = schedule_buy(ds, pu.id, start=max(today, ds.settings.planning_start)).due_date
            if earliest > due:
                notes.append(f"{o.product}: {pu.supplier} can deliver {earliest.isoformat()}, "
                             f"{(earliest - due).days} d after it is needed there")
                due = earliest
        groups[(pu.supplier, o.location, _currency(ds, pu.currency))].append((rid, pu, qty, due, notes))

    num = next_numbers(ds)
    receipts = list(ds.receipts)
    headers = list(ds.purchase_orders)
    limit = ds.purchasing.approval_limit
    for (sup, loc, cur), items in sorted(groups.items()):
        num["PO"] += 1
        pid = f"PO-{num['PO']:05d}"
        created = CreatedPo(id=pid, supplier=sup, location=loc, currency=cur, value=0.0, lines=[], approved=True,
                            notes=[])
        for i, (rid, pu, qty, due, notes) in enumerate(items, start=1):
            lid = f"{pid}-{i * 10}"
            price = pu.price_for(qty)
            receipts.append(ScheduledReceipt(id=lid, kind=ReceiptKind.PURCHASE, location=loc, product=pu.product, qty=qty,
                                             due_date=due, start_date=today, source=pu.id, po=pid, price=price))
            created.lines.append(lid)
            created.value += qty * price
            created.notes += notes
            rep.lines[rid] = lid
        company_value = created.value * fx(ds, cur if cur != ds.settings.currency else None)
        v = ds.vendor(sup)
        if v.min_order_value and company_value < v.min_order_value - EPS:
            created.notes.append(f"worth {company_value:,.0f}, below {sup}'s minimum order of {v.min_order_value:,.0f}")
        if limit is not None and company_value > limit + EPS:
            created.approved = False
            created.notes.append(f"worth {company_value:,.0f}, above the approval limit of {limit:,.0f}: approve it "
                                 "before sending")
        headers.append(PurchaseOrder(id=pid, supplier=sup, location=loc, order_date=today,
                                     currency=None if cur == ds.settings.currency else cur, approved=created.approved))
        rep.created.append(created)
    rep.ok = True
    return ds.model_copy(update={"receipts": receipts, "purchase_orders": headers}), rep


# ---- actions ---------------------------------------------------------------------------------------
def _po_lines(ds: Dataset, po_id: str) -> list[ScheduledReceipt]:
    """Open lines of an order; an open purchase receipt without a header is its own one-line order."""
    lines = [r for r in ds.receipts if r.po == po_id]
    if not lines and po_id not in ds.purchase_order_by_id:
        lines = [r for r in ds.receipts if r.id == po_id and r.kind is ReceiptKind.PURCHASE and r.po is None]
    return lines


def _header(ds: Dataset, po_id: str) -> PurchaseOrder:
    po = ds.purchase_order_by_id.get(po_id)
    if po is None:
        raise PurchasingError(f"{po_id} has no order document to approve or send")
    return po


def _replace_header(ds: Dataset, po: PurchaseOrder) -> list[PurchaseOrder]:
    return [po if p.id == po.id else p for p in ds.purchase_orders]


def _pick(lines: list[ScheduledReceipt], wanted: list[dict] | None, po_id: str) -> list[tuple[ScheduledReceipt, dict]]:
    by = {r.id: r for r in lines}
    if not by:
        raise PurchasingError(f"{po_id} has no open lines")
    if wanted is None:
        return [(r, {}) for r in lines]
    out = []
    for w in wanted:
        r = by.get(w.get("id", ""))
        if r is None:
            raise PurchasingError(f"{w.get('id')} is not an open line of {po_id}")
        out.append((r, w))
    return out


def approve(ds: Dataset, po_id: str) -> tuple[Dataset, ActionReport]:
    po = _header(ds, po_id)
    return (ds.model_copy(update={"purchase_orders": _replace_header(ds, po.model_copy(update={"approved": True}))}),
            ActionReport(ok=True, message=f"{po_id} approved"))


def send(ds: Dataset, po_id: str, on: date | None = None) -> tuple[Dataset, ActionReport]:
    po = _header(ds, po_id)
    if not po.approved:
        raise PurchasingError(f"{po_id} is above the approval limit and not approved yet")
    on = on or ds.settings.planning_start
    v = ds.vendor(po.supplier)
    msg = f"{po_id} sent to {po.supplier} on {on.isoformat()}"
    if v.confirmation_required:
        msg += f"; a confirmation is expected within {v.confirmation_days} d"
    return (ds.model_copy(update={"purchase_orders": _replace_header(ds, po.model_copy(update={"sent_on": on}))}),
            ActionReport(ok=True, message=msg))


def confirm(ds: Dataset, po_id: str, lines: list[dict] | None, reference: str = "") -> tuple[Dataset, ActionReport]:
    """The supplier's confirmation: per line a date (default: as asked) and quantity (default: all of it)."""
    got = received(ds)
    upd: dict[str, ScheduledReceipt] = {}
    short = late = 0
    for r, w in _pick(_po_lines(ds, po_id), lines, po_id):
        ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
        d = date.fromisoformat(w["date"]) if isinstance(w.get("date"), str) else (w.get("date") or r.due_date)
        q = float(w["qty"]) if w.get("qty") is not None else ordered
        if q < -EPS or q > ordered + EPS:
            raise PurchasingError(f"{r.id}: a confirmation of {q:,.0f} must be between 0 and the {ordered:,.0f} ordered")
        if q < got.get(r.id, 0.0) - EPS:
            raise PurchasingError(f"{r.id}: {got[r.id]:,.0f} are already received, more than {q:,.0f}")
        short += q < ordered - EPS
        late += d > r.due_date
        upd[r.id] = r.model_copy(update={"confirmed_date": d, "confirmed_qty": q})
    receipts = [upd.get(r.id, r) for r in ds.receipts]
    headers = list(ds.purchase_orders)
    po = ds.purchase_order_by_id.get(po_id)
    if po is not None and reference:
        headers = _replace_header(ds, po.model_copy(update={"vendor_reference": reference}))
    parts = [f"{len(upd)} line{'s' if len(upd) != 1 else ''} of {po_id} confirmed"]
    if late:
        parts.append(f"{late} later than asked")
    if short:
        parts.append(f"{short} for less than ordered: the plan now counts only what is confirmed")
    return (ds.model_copy(update={"receipts": receipts, "purchase_orders": headers}),
            ActionReport(ok=True, message="; ".join(parts)))


def receive(ds: Dataset, po_id: str, lines: list[dict] | None, on: date | None = None,
            delivery_note: str = "") -> tuple[Dataset, ActionReport]:
    """Goods receipt against an order (≈ MIGO 101): one receipt movement per line. ``lines``: ``{"id", "qty"?,
    "final"?}``; the default receives each line's open quantity. The supplier's over-delivery tolerance is enforced;
    a delivery within their under-delivery tolerance is marked final and closes the line."""
    on = on or ds.settings.planning_start
    got = received(ds)
    moves: list[GoodsMovement] = []
    taken: set[str] = set()
    notes = []
    for r, w in _pick(_po_lines(ds, po_id), lines, po_id):
        ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
        before = got.get(r.id, 0.0)
        q = float(w["qty"]) if w.get("qty") is not None else max(0.0, ordered - before)
        if q <= EPS:
            continue
        sup = _supplier_of(ds, r)
        v = ds.vendor(sup or "")
        total = before + q
        if v.over_delivery_tolerance is not None and total > ordered * (1 + v.over_delivery_tolerance) + EPS:
            raise PurchasingError(f"{r.id}: receiving {q:,.0f} makes {total:,.0f} of {ordered:,.0f} ordered, more than "
                                  f"{sup}'s over-delivery tolerance of {v.over_delivery_tolerance:.0%}")
        final = bool(w.get("final")) or (ordered - EPS > total >= ordered * (1 - v.under_delivery_tolerance) - EPS
                                         and v.under_delivery_tolerance > 0)
        mid = _next_movement(ds, taken)
        taken.add(mid)
        moves.append(GoodsMovement(id=mid, date=on, type=MovementType.RECEIPT, location=r.location, product=r.product,
                                   qty=q, reference=r.id, counterparty=sup if sup in ds.location_by_id else None,
                                   final=final, note=delivery_note[:200]))
        if final and total < ordered - EPS:
            notes.append(f"{r.id} closed {ordered - total:,.0f} short")
        elif total >= ordered - EPS:
            notes.append(f"{r.id} complete")
        else:
            notes.append(f"{r.id}: {ordered - total:,.0f} still to come")
    if not moves:
        raise PurchasingError(f"nothing to receive on {po_id}")
    msg = (f"Goods received on {po_id} ({on.isoformat()}): " + "; ".join(notes)
           + ". Stock and the order are updated when the plan moves past this date (Actuals → Start a new week).")
    return (ds.model_copy(update={"movements": [*ds.movements, *moves]}),
            ActionReport(ok=True, message=msg, movements=[m.id for m in moves]))


def change(ds: Dataset, po_id: str, lines: list[dict]) -> tuple[Dataset, ActionReport]:
    """Change a line's quantity, delivery date or price. A changed quantity or date needs a new confirmation from a
    supplier who confirms, and an order whose value rises above the approval limit needs approving again."""
    got = received(ds)
    upd: dict[str, ScheduledReceipt] = {}
    for r, w in _pick(_po_lines(ds, po_id), lines, po_id):
        ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
        before = got.get(r.id, 0.0)
        new_q = float(w["qty"]) if w.get("qty") is not None else ordered
        if new_q < before - EPS or new_q <= EPS:
            raise PurchasingError(f"{r.id}: the quantity cannot go below the {before:,.0f} already received")
        due = date.fromisoformat(w["date"]) if isinstance(w.get("date"), str) else (w.get("date") or r.due_date)
        patch: dict = {"due_date": due}
        if w.get("price") is not None:
            patch["price"] = float(w["price"])
        if abs(new_q - ordered) > EPS:
            open_q = new_q - (ordered - r.qty)       # open = new order less what was already booked off it
            patch.update(qty=max(open_q, EPS), ordered_qty=new_q if r.ordered_qty is not None else None)
        if (abs(new_q - ordered) > EPS or due != r.due_date) and ds.vendor(_supplier_of(ds, r) or "").confirmation_required:
            patch.update(confirmed_date=None, confirmed_qty=None)
        upd[r.id] = r.model_copy(update=patch)
    receipts = [upd.get(r.id, r) for r in ds.receipts]
    headers = list(ds.purchase_orders)
    msg = f"{len(upd)} line{'s' if len(upd) != 1 else ''} of {po_id} changed"
    po = ds.purchase_order_by_id.get(po_id)
    limit = ds.purchasing.approval_limit
    if po is not None and limit is not None:
        k = fx(ds, po.currency)
        old = sum(r.qty * (r.price or 0.0) for r in ds.receipts if r.po == po_id) * k
        new = sum(r.qty * (r.price or 0.0) for r in receipts if r.po == po_id) * k
        if new > limit + EPS and new > old + EPS:
            headers = _replace_header(ds, po.model_copy(update={"approved": False, "sent_on": None}))
            msg += f"; now worth {new:,.0f}, above the approval limit: approve and send it again"
    return ds.model_copy(update={"receipts": receipts, "purchase_orders": headers}), ActionReport(ok=True, message=msg)


def cancel(ds: Dataset, po_id: str, lines: list[dict] | None) -> tuple[Dataset, ActionReport]:
    """Cancel lines nothing has been received for (all open lines by default); an order left with no lines goes."""
    got = received(ds)
    drop = set()
    for r, _ in _pick(_po_lines(ds, po_id), lines, po_id):
        if got.get(r.id, 0.0) > EPS:
            raise PurchasingError(f"{r.id}: {got[r.id]:,.0f} already received; receive the last delivery as final "
                                  "instead of cancelling")
        drop.add(r.id)
    receipts = [r for r in ds.receipts if r.id not in drop]
    left = any(r.po == po_id for r in receipts) or any(c.po == po_id for c in ds.closed_orders)
    headers = ds.purchase_orders if left else [p for p in ds.purchase_orders if p.id != po_id]
    msg = f"{len(drop)} line{'s' if len(drop) != 1 else ''} of {po_id} cancelled" + ("" if left else "; the order is removed")
    return ds.model_copy(update={"receipts": receipts, "purchase_orders": headers}), ActionReport(ok=True, message=msg)


ACTIONS = {"approve", "send", "confirm", "receive", "change", "cancel"}


def act(ds: Dataset, action: str, po_id: str, *, lines: list[dict] | None = None, on: date | None = None,
        reference: str = "", note: str = "") -> tuple[Dataset, ActionReport]:
    if action == "approve":
        return approve(ds, po_id)
    if action == "send":
        return send(ds, po_id, on)
    if action == "confirm":
        return confirm(ds, po_id, lines, reference)
    if action == "receive":
        return receive(ds, po_id, lines, on, note)
    if action == "change":
        return change(ds, po_id, lines or [])
    if action == "cancel":
        return cancel(ds, po_id, lines)
    raise PurchasingError(f"unknown action {action!r}")


# ---- views -----------------------------------------------------------------------------------------
def _line(ds: Dataset, r, got: dict[str, float], last: dict[str, date], as_of: date, closed: bool) -> PoLine:
    if closed:
        ordered, rec, due = r.ordered_qty, r.delivered_qty, r.due_date
        exp = r.confirmed_date or due
        late = max(0, ((r.last_delivery or due) - due).days)
        return PoLine(id=r.id, product=r.product, ordered=ordered, received=rec, open=0.0, price=r.price,
                      value=ordered * (r.price or 0.0), due_date=due, confirmed_date=r.confirmed_date, confirmed_qty=None,
                      expected_date=exp, status="closed", days_late=late, closed=True, last_receipt=r.last_delivery)
    ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
    rec = got.get(r.id, 0.0)
    open_q = max(0.0, ordered - rec)
    v = ds.vendor(_supplier_of(ds, r) or "")
    pu = ds.purchasing_source_by_id.get(r.source or "")
    price = r.price if r.price is not None else pu.price_for(ordered) if pu else None   # an imported line: its source's price
    exp = r.expected_date
    if open_q <= EPS:
        status = "received"
    elif rec > EPS:
        status = "partly received"
    elif r.confirmed_qty is not None and r.confirmed_qty < ordered - EPS:
        status = "confirmed short"
    elif r.confirmed_date is not None and r.confirmed_date > r.due_date:
        status = "confirmed late"
    elif r.confirmed_date is not None or r.confirmed_qty is not None:
        status = "confirmed"
    elif v.confirmation_required:
        status = "awaiting confirmation"
    else:
        status = "open"
    late = max((exp - r.due_date).days, (as_of - exp).days if open_q > EPS and exp < as_of else 0, 0)
    if open_q > EPS and exp < as_of:
        status = "overdue" if rec <= EPS else status
    return PoLine(id=r.id, product=r.product, ordered=ordered, received=rec, open=open_q, price=price,
                  value=ordered * (price or 0.0), due_date=r.due_date, confirmed_date=r.confirmed_date,
                  confirmed_qty=r.confirmed_qty, expected_date=exp, status=status, days_late=late, closed=False,
                  last_receipt=last.get(r.id), source=r.source)


def purchase_orders(ds: Dataset, as_of: date | None = None) -> list[PoView]:
    as_of = as_of or ds.settings.planning_start
    got, last = received(ds), _last_receipt(ds)
    open_by: dict[str, list] = defaultdict(list)
    closed_by: dict[str, list] = defaultdict(list)
    loose = []
    for r in ds.receipts:
        if r.kind is not ReceiptKind.PURCHASE:
            continue
        if r.po:
            open_by[r.po].append(r)
        else:
            loose.append(r)
    for c in ds.closed_orders:
        if c.kind == "purchase" and c.po:
            closed_by[c.po].append(c)
    out = []
    for po in ds.purchase_orders:
        lines = ([_line(ds, r, got, last, as_of, False) for r in open_by.get(po.id, [])]
                 + [_line(ds, c, got, last, as_of, True) for c in closed_by.get(po.id, [])])
        lines.sort(key=lambda x: x.id)
        out.append(_view(ds, po.id, True, po, po.supplier, po.location, lines, as_of))
    for r in loose:
        out.append(_view(ds, r.id, False, None, _supplier_of(ds, r), r.location,
                         [_line(ds, r, got, last, as_of, False)], as_of))
    order = {"awaiting approval": 0, "to send": 1, "awaiting confirmation": 2, "partly received": 3, "sent": 4,
             "confirmed": 5, "received": 6, "closed": 7}
    out.sort(key=lambda p: (order[p.status], p.id))
    return out


def _view(ds: Dataset, pid: str, header: bool, po: PurchaseOrder | None, supplier: str | None, location: str,
          lines: list[PoLine], as_of: date) -> PoView:
    v = ds.vendor(supplier or "")
    open_lines = [x for x in lines if not x.closed]
    attention: list[str] = []
    if not open_lines:
        status = "closed"
    elif all(x.open <= EPS for x in open_lines):
        status = "received"
    elif po is not None and not po.approved:
        status = "awaiting approval"
        attention.append("approve it before it is sent")
    elif po is not None and po.sent_on is None:
        status = "to send"
        attention.append("send it to the supplier")
    elif any(x.received > EPS for x in open_lines):
        status = "partly received"
    elif any(x.status == "awaiting confirmation" for x in open_lines):
        status = "awaiting confirmation"
        if po is not None and po.sent_on is not None and (as_of - po.sent_on).days > v.confirmation_days:
            attention.append(f"confirmation overdue since {po.sent_on.isoformat()} + {v.confirmation_days} d: chase it")
    elif open_lines and all(x.confirmed_date is not None or x.confirmed_qty is not None for x in open_lines):
        status = "confirmed"
    else:
        status = "sent"
    over = [x for x in open_lines if x.open > EPS and x.expected_date < as_of]
    if over:
        attention.append(f"{len(over)} line{'s' if len(over) != 1 else ''} overdue: chase or re-date")
    late = [x for x in open_lines if x.confirmed_date is not None and x.confirmed_date > x.due_date]
    if late:
        attention.append(f"{len(late)} line{'s' if len(late) != 1 else ''} confirmed later than asked")
    short = [x for x in open_lines if x.status == "confirmed short"]
    if short:
        attention.append(f"{len(short)} line{'s' if len(short) != 1 else ''} confirmed short: the plan orders the rest "
                         "elsewhere unless you change the line")
    if v.blocked and open_lines:
        attention.append(f"{supplier} is blocked for purchasing")
    cur = (po.currency if po else None) or next(
        (ds.purchasing_source_by_id[x.source].currency for x in lines
         if x.source in ds.purchasing_source_by_id and ds.purchasing_source_by_id[x.source].currency), None)
    return PoView(id=pid, header=header, supplier=supplier, location=location, order_date=po.order_date if po else None,
                  currency=_currency(ds, cur), approved=po.approved if po else True, sent_on=po.sent_on if po else None,
                  vendor_reference=po.vendor_reference if po else "", note=po.note if po else "", status=status,
                  value=sum(x.value for x in lines), open_value=sum(x.open * (x.price or 0.0) for x in open_lines),
                  lines=lines, attention=attention)


def vendor_rows(ds: Dataset, orders: list[PoView]) -> list[VendorRow]:
    tol = ds.execution.delivery_tolerance
    sups = [loc for loc in ds.locations if loc.type.value == "supplier"]
    out = []
    for loc in sups:
        v = ds.vendor(loc.id)
        closed = [c for c in ds.closed_orders if c.kind == "purchase" and c.counterparty == loc.id]
        on_time = [c for c in closed if c.last_delivery is not None and c.last_delivery <= c.due_date
                   and c.delivered_qty >= c.ordered_qty * (1 - tol) - EPS]
        in_full = [c for c in closed if c.delivered_qty >= c.ordered_qty * (1 - max(tol, v.under_delivery_tolerance)) - EPS]
        lates = [(c.last_delivery - c.due_date).days for c in closed
                 if c.last_delivery is not None and c.last_delivery > c.due_date]
        mine = [p for p in orders if p.supplier == loc.id]
        open_lines = [x for p in mine for x in p.lines if not x.closed and x.open > EPS]
        open_value = sum(x.open * (x.price or 0.0) * fx(ds, p.currency if p.currency != ds.settings.currency else None)
                         for p in mine for x in p.lines if not x.closed and x.open > EPS)
        confirmed_late = sum(1 for p in mine for x in p.lines if x.confirmed_date is not None and x.confirmed_date > x.due_date)
        recs = [InfoRecord(source_id=pu.id, product=pu.product, location=pu.location, price=pu.price,
                           currency=_currency(ds, pu.currency), price_scales=pu.price_scales, moq=pu.moq,
                           rounding_qty=pu.rounding_qty, lead_time_days=pu.lead_time_days, valid_from=pu.valid_from,
                           valid_to=pu.valid_to, fixed=pu.fixed, blocked=pu.blocked, priority=pu.priority,
                           quota=pu.quota, vendor_material=pu.vendor_material)
                for pu in ds.purchasing_sources if pu.supplier == loc.id]
        out.append(VendorRow(
            supplier=loc.id, name=loc.name or loc.id, has_record=loc.id in ds.vendor_by_supplier, blocked=v.blocked,
            block_reason=v.block_reason, confirmation_required=v.confirmation_required,
            payment_terms_days=v.payment_terms_days, currency=_currency(ds, v.currency), open_lines=len(open_lines),
            open_value=open_value, closed_lines=len(closed),
            on_time=len(on_time) / len(closed) if closed else None, in_full=len(in_full) / len(closed) if closed else None,
            avg_days_late=sum(lates) / len(lates) if lates else None, confirmed_late=confirmed_late,
            last_delivery=max((c.last_delivery for c in closed if c.last_delivery), default=None), info_records=recs))
    return out


def purchasing_view(ds: Dataset, plan: PlanResult) -> PurchasingView:
    as_of = ds.settings.planning_start
    reqs = requisitions(ds, plan) if plan.ok else []
    orders = purchase_orders(ds, as_of)
    due = [r for r in reqs if r.due_now]
    live = [p for p in orders if p.status not in ("received", "closed")]
    totals = PurchasingTotals(
        requisitions=len(reqs), due_now=len(due), due_now_value=sum(r.value for r in due),
        late_to_order=sum(r.late for r in reqs), open_orders=len(live),
        open_value=sum(p.open_value * fx(ds, p.currency if p.currency != ds.settings.currency else None) for p in live),
        awaiting_approval=sum(p.status == "awaiting approval" for p in orders),
        to_send=sum(p.status == "to send" for p in orders),
        confirmations_overdue=sum(any(a.startswith("confirmation overdue") for a in p.attention) for p in orders),
        late_lines=sum(1 for p in live for x in p.lines if not x.closed and x.open > EPS and x.days_late > 0))
    return PurchasingView(ok=plan.ok, as_of=as_of, currency=ds.settings.currency,
                          approval_limit=ds.purchasing.approval_limit, totals=totals, requisitions=reqs, orders=orders,
                          vendors=vendor_rows(ds, orders))


__all__ = [
    "ACTIONS", "PurchasingError", "act", "approve", "cancel", "change", "confirm", "create_purchase_orders",
    "next_numbers", "purchase_orders", "purchasing_view", "receive", "requisitions", "send", "vendor_rows",
]
