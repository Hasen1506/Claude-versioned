"""The supplier's side of a purchase order (Enterprise 7.2, ≈ S/4 Ariba supplier collaboration, kept small).

A supplier given a link sees the lines of the orders sent to them that are still open, and only those. For each line
they confirm the quantity and date, or change them (a smaller quantity, a later date, or several deliveries); the
confirmation is the one Buying records, so planning counts on what they confirm. When goods leave them they send a
dispatch advice (a shipping notice): what is on the lorry, its batches, when it arrives. The arrival date becomes the
lines' confirmed date, and the goods are received against the notice in one step.

The same steps come as standard messages (see :mod:`scp.portal.ubl`): an Order out, an OrderResponse and a
DespatchAdvice in.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from ..model import Dataset, ReceiptKind, ScheduledReceipt
from ..model.common import Out
from ..model.portal import NoticeLine, ShippingNotice
from ..model.transactional import ConfirmedDelivery

EPS = 1e-6


class PortalError(ValueError):
    """A step the data does not allow; the message says why in plain words."""


def _name(ds: Dataset, oid: str) -> str:
    x = ds.location_by_id.get(oid) or ds.product_by_id.get(oid)
    return (x.name or oid) if x else oid


def _n(q: float) -> str:
    return f"{q:,.0f}" if abs(q - round(q)) < 1e-6 else f"{q:,.2f}"


def _day(d: date) -> str:
    return d.strftime("%a %d %b").replace(" 0", " ")


def _today(ds: Dataset, on: date | None) -> date:
    return on or ds.settings.planning_start


def _lines(ds: Dataset, supplier: str) -> list[ScheduledReceipt]:
    """Open lines of purchase orders sent to the supplier."""
    out = []
    for r in ds.receipts:
        if r.kind is not ReceiptKind.PURCHASE or not r.po:
            continue
        po = ds.purchase_order_by_id.get(r.po)
        if po is not None and po.supplier == supplier and po.sent_on is not None:
            out.append(r)
    return out


def _line(ds: Dataset, supplier: str, lid: str) -> ScheduledReceipt:
    r = next((x for x in _lines(ds, supplier) if x.id == lid), None)
    if r is None:
        raise PortalError(f"{lid} is not an open line of an order sent to {_name(ds, supplier)}")
    return r


def _their_part(ds: Dataset, r: ScheduledReceipt) -> str:
    pu = ds.purchasing_source_by_id.get(r.source or "")
    return pu.vendor_material if pu else ""


def notified(ds: Dataset) -> dict[str, float]:
    """Quantity on shipping notices not received or cancelled yet, per order line."""
    out: dict[str, float] = defaultdict(float)
    for n in ds.shipping_notices:
        if n.received_on is None and not n.cancelled:
            for ln in n.lines:
                out[ln.order] += ln.qty
    return out


# ------------------------------------------------------------------------------------------------ view
class PortalLine(Out):
    order: str                         # the order line
    po: str
    product: str
    product_name: str
    their_part: str
    unit: str
    ordered: float
    received: float
    on_the_way: float                  # on shipping notices not received yet
    open: float
    price: float | None
    due_date: date
    confirmed_date: date | None
    confirmed_qty: float | None
    confirmations: list[ConfirmedDelivery]
    deliver_to: str
    deliver_to_name: str
    status: str                        # to confirm | confirmed | changed | on the way


class PortalNotice(Out):
    id: str
    reference: str
    shipped_on: date
    arrives_on: date
    lines: list[NoticeLine]
    status: str                        # on the way | received | cancelled


class PortalView(Out):
    company: str
    supplier: str
    supplier_name: str
    as_of: date
    currency: str
    lines: list[PortalLine]
    notices: list[PortalNotice]


def view(ds: Dataset, supplier: str, on: date | None = None) -> PortalView:
    from ..purchasing import received
    if supplier not in ds.location_by_id:
        raise PortalError(f"{supplier} is not a supplier of {ds.settings.company_name or 'this company'}")
    got, way = received(ds), notified(ds)
    rows = []
    for r in sorted(_lines(ds, supplier), key=lambda x: (x.due_date, x.id)):
        ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
        po = ds.purchase_order_by_id[r.po or ""]
        p = ds.product_by_id.get(r.product)
        rec = got.get(r.id, 0.0)
        if way.get(r.id, 0.0) > EPS:
            st = "on the way"
        elif r.confirmed_date is None:
            st = "to confirm"
        elif (r.confirmed_qty is not None and r.confirmed_qty < ordered - EPS) or r.confirmed_date != r.due_date \
                or r.confirmations:
            st = "changed"
        else:
            st = "confirmed"
        rows.append(PortalLine(order=r.id, po=po.id, product=r.product, product_name=_name(ds, r.product),
                               their_part=_their_part(ds, r), unit=p.base_uom if p else "EA", ordered=ordered,
                               received=round(rec, 6), on_the_way=round(way.get(r.id, 0.0), 6),
                               open=round(max(0.0, (r.confirmed_qty if r.confirmed_qty is not None else ordered) - rec),
                                          6),
                               price=r.price, due_date=r.due_date, confirmed_date=r.confirmed_date,
                               confirmed_qty=r.confirmed_qty, confirmations=r.confirmations, deliver_to=r.location,
                               deliver_to_name=_name(ds, r.location), status=st))
    notes = [PortalNotice(id=n.id, reference=n.reference, shipped_on=n.shipped_on, arrives_on=n.arrives_on, lines=n.lines,
                          status="cancelled" if n.cancelled else "received" if n.received_on else "on the way")
             for n in sorted(ds.shipping_notices, key=lambda x: x.id, reverse=True) if n.supplier == supplier]
    cur = ds.vendor(supplier).currency or ds.settings.currency
    return PortalView(company=ds.settings.company_name or "", supplier=supplier, supplier_name=_name(ds, supplier),
                      as_of=_today(ds, on), currency=cur, lines=rows, notices=notes)


# ------------------------------------------------------------------------------------------------ steps
class PortalReport(Out):
    message: str
    id: str | None = None


def respond(ds: Dataset, supplier: str, lines: list[dict], reference: str = "") -> tuple[Dataset, PortalReport]:
    """The supplier's answer to their order lines: ``[{"order", "qty"?, "date"?, "parts"?}]``, each confirmed as asked
    (no quantity or date) or changed. Recorded as the order's confirmation (Buying)."""
    from ..purchasing import PurchasingError, confirm
    if not lines:
        raise PortalError("say which lines you confirm")
    per_po: dict[str, list[dict]] = defaultdict(list)
    for w in lines:
        r = _line(ds, supplier, str(w.get("order") or ""))
        per_po[r.po or ""].append({**w, "id": r.id})
    said = []
    for po, ws in per_po.items():
        try:
            ds, rep = confirm(ds, po, ws, reference)
        except PurchasingError as e:
            raise PortalError(str(e)) from e
        said.append(rep.message)
    return ds, PortalReport(message=f"{_name(ds, supplier)}: " + "; ".join(said) + ".")


def _next_id(ds: Dataset) -> str:
    n = max((int(x.id[4:]) for x in ds.shipping_notices if x.id.startswith("ASN-") and x.id[4:].isdigit()), default=0)
    return f"ASN-{n + 1:05d}"


def _arrival(ds: Dataset, supplier: str, r: ScheduledReceipt, shipped_on: date) -> date:
    from ..plan.leadtime import supplier_lane
    lane = supplier_lane(ds, supplier, r.location, r.product)
    return shipped_on + timedelta(days=math.ceil(lane.planning_mode.transit_days)) if lane else shipped_on


def _on_the_way(ds: Dataset, lid: str) -> list[tuple[date, float]]:
    """Each open shipping notice's quantity for the line, on its arrival date."""
    return [(n.arrives_on, x.qty) for n in ds.shipping_notices if n.received_on is None and not n.cancelled
            for x in n.lines if x.order == lid]


def _reconfirm(r: ScheduledReceipt, shipped: list[tuple[date, float]], total: float,
               freed: tuple[date, float] | None = None, new: tuple[date, float] | None = None) -> ScheduledReceipt:
    """The line's confirmation once ``shipped`` (the open notices already counted in it) and ``new`` (a notice just
    sent) are on their way: each notice arrives on its own date and the rest keeps the dates the supplier confirmed.
    A new notice's goods count against the earliest delivery still confirmed (what it does not carry of that one is
    late, not early); a cancelled notice's quantity (``freed``) goes back to the line's last date. What was received
    counts against the earliest line, as confirmations do (:meth:`ScheduledReceipt.expected_parts`)."""
    parts = r.expected_parts()
    if freed is not None:
        i = next((k for k, (d, _q) in enumerate(parts) if d == freed[0]), None)
        take = min(freed[1], parts[i][1]) if i is not None else 0.0
        if i is not None:
            parts[i] = (parts[i][0], parts[i][1] - take)
        parts = [(d, q) for d, q in parts if q > EPS]
        if take > EPS:
            parts.append((max([r.due_date, *(d for d, _q in parts)]), take))
    # what the notices carry no longer arrives on the dates it was confirmed for: a notice already counted is matched
    # to its own date first, a new one is taken from the earliest
    pool = [[d, q] for d, q in sorted(parts)]
    for when, q, counted in [*((d, q, True) for d, q in shipped), *([(*new, False)] if new else [])]:
        for p in sorted(pool, key=lambda x: (counted and x[0] != when, x[0])):
            take = min(q, p[1])
            p[1] -= take
            q -= take
            if q <= EPS:
                break
    lines: dict[date, float] = defaultdict(float)
    for d, q in [*shipped, *([new] if new else []), *((p[0], p[1]) for p in pool if p[1] > EPS)]:
        lines[d] += q
    if not lines:
        return r
    got = r.target_qty - r.qty
    first = min(lines)
    lines[first] += max(0.0, got)
    out = [ConfirmedDelivery(date=d, qty=round(q, 6)) for d, q in sorted(lines.items())]
    # more than ordered within the supplier's tolerance: they confirm it by sending it (planning still counts no more
    # than is open)
    return r.model_copy(update={"confirmed_date": out[-1].date,
                                "confirmed_qty": round(max(total, sum(x.qty for x in out)), 6),
                                "confirmations": out if len(out) > 1 else []})


def dispatch(ds: Dataset, supplier: str, lines: list[dict], shipped_on: date | None = None,
             arrives_on: date | None = None, reference: str = "", source: str = "entered",
             note: str = "") -> tuple[Dataset, PortalReport]:
    """A shipping notice: ``[{"order", "qty"?, "batch"?, "expires_on"?}]`` (no quantity: what is open and not on the
    way yet). ``arrives_on`` defaults to the dispatch plus the lane's transit days. The arrival becomes the lines'
    confirmed date for what is on the lorry; the rest keeps its date."""
    from ..purchasing import received
    if not lines:
        raise PortalError("say what is on the way")
    day = shipped_on or ds.settings.planning_start
    got, way = received(ds), notified(ds)
    out: list[NoticeLine] = []
    arrive: list[date] = []
    upd: dict[str, ScheduledReceipt] = {}
    for w in lines:
        r = _line(ds, supplier, str(w.get("order") or ""))
        if r.id in upd:
            raise PortalError(f"{r.id} is on the notice twice")
        ordered = r.ordered_qty if r.ordered_qty is not None else r.qty
        total = r.confirmed_qty if r.confirmed_qty is not None else ordered
        left = total - got.get(r.id, 0.0) - way.get(r.id, 0.0)
        q = left if w.get("qty") is None else float(w["qty"])
        if not math.isfinite(q) or q <= EPS:
            raise PortalError(f"{r.id}: nothing is left to send" if w.get("qty") is None
                              else f"{r.id}: the quantity sent must be more than 0")
        over = ds.vendor(supplier).over_delivery_tolerance
        if over is not None and got.get(r.id, 0.0) + way.get(r.id, 0.0) + q > ordered * (1 + over) + EPS:
            raise PortalError(f"{r.id}: {_n(q)} more makes {_n(got.get(r.id, 0.0) + way.get(r.id, 0.0) + q)} of the "
                              f"{_n(ordered)} ordered, more than the order allows")
        exp = w.get("expires_on")
        out.append(NoticeLine(order=r.id, product=r.product, qty=round(q, 6), batch=w.get("batch") or None,
                              expires_on=date.fromisoformat(exp) if isinstance(exp, str) and exp else exp or None))
        when = arrives_on or _arrival(ds, supplier, r, day)
        arrive.append(when)
        upd[r.id] = _reconfirm(r, _on_the_way(ds, r.id), total, new=(when, q))
    if arrives_on is not None and arrives_on < day:
        raise PortalError("goods cannot arrive before they leave")
    nid = _next_id(ds)
    n = ShippingNotice(id=nid, supplier=supplier, reference=reference[:64], shipped_on=day, arrives_on=max(arrive),
                       lines=out, source=source if source in ("portal", "message", "entered") else "entered",
                       note=note[:400])
    new = ds.model_copy(update={"shipping_notices": [*ds.shipping_notices, n],
                                "receipts": [upd.get(r.id, r) for r in ds.receipts]})
    what = ", ".join(f"{_n(x.qty)} {_name(ds, x.product)} ({x.order})" for x in out[:4]) + (
        f" and {len(out) - 4} more" if len(out) > 4 else "")
    return new, PortalReport(id=nid, message=(
        f"{nid}: {_name(ds, supplier)} dispatched {what} on {_day(day)}" + (f" (their {reference})" if reference else "")
        + f", arriving {_day(n.arrives_on)}. The plan counts on that date; receive it against {nid} when it comes."))


def receive(ds: Dataset, nid: str, on: date | None = None, lines: list[dict] | None = None,
            delivery_note: str = "") -> tuple[Dataset, PortalReport]:
    """Goods arrived as notified: each line received on its order with its batch (``lines``: ``[{"order", "qty"}]``
    for what really came, default all of it)."""
    from ..purchasing import PurchasingError
    from ..purchasing import receive as receive_po
    n = next((x for x in ds.shipping_notices if x.id == nid), None)
    if n is None:
        raise PortalError(f"there is no shipping notice {nid}")
    if n.cancelled or n.received_on is not None:
        raise PortalError(f"{nid} is {'cancelled' if n.cancelled else 'received already'}")
    said = {str(w.get("order")): w for w in (lines or [])}
    unknown = [o for o in said if not any(x.order == o for x in n.lines)]
    if unknown:
        raise PortalError(f"{unknown[0]} is not on {nid}")
    day = _today(ds, on)
    per_po: dict[str, list[dict]] = defaultdict(list)
    for x in n.lines:
        r = next((y for y in ds.receipts if y.id == x.order), None)
        if r is None:
            raise PortalError(f"{x.order} is no longer open: receive the rest on Buying")
        q = float(said[x.order]["qty"]) if x.order in said and said[x.order].get("qty") is not None else x.qty
        if q > EPS:
            per_po[r.po or r.id].append({"id": r.id, "qty": q, "batch": x.batch, "expires_on": x.expires_on,
                                         "supplier_batch": x.batch or ""})
    msgs = []
    for po, ws in per_po.items():
        try:
            ds, rep = receive_po(ds, po, ws, day, delivery_note or n.reference or nid)
        except PurchasingError as e:
            raise PortalError(str(e)) from e
        msgs.append(rep.message.split(". Stock and the order")[0])
    ds = ds.model_copy(update={"shipping_notices": [x.model_copy(update={"received_on": day}) if x.id == nid else x
                                                    for x in ds.shipping_notices]})
    return ds, PortalReport(id=nid, message=f"{nid} received: " + "; ".join(msgs) + ".")


def cancel(ds: Dataset, nid: str) -> tuple[Dataset, PortalReport]:
    """A notice that will not come: its quantity is expected again on the line's last confirmed date."""
    n = next((x for x in ds.shipping_notices if x.id == nid), None)
    if n is None:
        raise PortalError(f"there is no shipping notice {nid}")
    if n.received_on is not None or n.cancelled:
        raise PortalError(f"{nid} is {'cancelled' if n.cancelled else 'received'} already")
    rest = ds.model_copy(update={"shipping_notices": [x.model_copy(update={"cancelled": True}) if x.id == nid else x
                                                      for x in ds.shipping_notices]})
    upd = {}
    for x in n.lines:
        r = next((y for y in ds.receipts if y.id == x.order), None)
        if r is not None and r.confirmed_qty is not None:
            upd[r.id] = _reconfirm(r, _on_the_way(rest, r.id), r.confirmed_qty, freed=(n.arrives_on, x.qty))
    rest = rest.model_copy(update={"receipts": [upd.get(r.id, r) for r in ds.receipts]})
    when = sorted({_day(r.expected_date) for r in upd.values()})
    return rest, PortalReport(id=nid, message=f"{nid} cancelled: its goods are expected again "
                              + (f"on {', '.join(when)}" if when else "as the order says") + ". Ask "
                              + f"{_name(ds, n.supplier)} for a new date if that is wrong.")


__all__ = ["PortalError", "PortalLine", "PortalNotice", "PortalReport", "PortalView", "cancel", "dispatch",
           "notified", "receive", "respond", "view"]
