"""Customer orders from taking to closing (≈ VA01 / VA02 with the availability check, and a rejection reason).

* **Accept** a checked order: it becomes a sales order with the next number (SO-00001, …) and keeps what the check
  promised, as confirmed schedule lines, so later orders cannot take its stock.
* **Change** an order's quantity, date, priority, price or delivery rule: it is checked again against everything
  else already promised, and its promise replaced.
* **Cancel** an order: what is still open is dropped, and the order is logged as closed and cancelled (with whatever
  was delivered), so the journal's deliveries keep their order and nothing cancelled counts against OTIF.

Delivering an order is a goods posting (:func:`scp.actuals.post.deliver`).
"""
from __future__ import annotations

import datetime as dt
import re

from ..actuals.post import PostingError, delivered, ordered_now, sales_order
from ..actuals.stock import EPS, arrival
from ..model import ClosedOrder, Dataset, DemandKind, DemandRecord, LocationType, MovementType, Strategy
from ..model.common import STOCKING_LOCATION_TYPES, Out
from ..model.promise import Confirmation
from .result import OrderPromise
from .run import check_order


class OrderError(ValueError):
    """An order action the data does not allow; the message says why in plain words."""


class SalesOrderReport(Out):
    ok: bool
    order: str
    message: str
    promise: OrderPromise | None = None


def next_order_id(ds: Dataset) -> str:
    """The next free sales-order number: SO-00001, … after the highest in open and closed orders."""
    n = 0
    for oid in [d.id for d in ds.demand if d.id] + [c.id for c in ds.closed_orders if c.kind == "sales"]:
        m = re.fullmatch(r"SO-(\d+)", oid or "")
        if m:
            n = max(n, int(m.group(1)))
    return f"SO-{n + 1:05d}"


def _n(q: float) -> str:
    t = f"{q:,.2f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _name(ds: Dataset, kind: str, oid: str) -> str:
    x = (ds.location_by_id if kind == "location" else ds.product_by_id).get(oid)
    return (x.name or x.id) if x else oid


def _day(d: dt.date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _promised(ds: Dataset, p: OrderPromise) -> str:
    if not p.lines:
        return "nothing can be promised yet" + (f" ({p.reason})" if p.reason else "")
    parts = [f"{_n(x.qty)} on {_day(x.date)}" for x in p.lines]
    head = "all on the date asked" if p.status == "on_time" else "promised " + ", ".join(parts)
    if p.status == "on_time" and len(p.lines) > 1:
        head = "all on the date asked (" + ", ".join(parts) + ")"
    return head + (f"; {_n(p.unconfirmed)} not promised yet" if p.unconfirmed > EPS else "")


def _new_supply(ds: Dataset, rec: DemandRecord, p: OrderPromise) -> str:
    """A note when the promise stands on supply nobody has ordered yet: a product made to order, or lines promised on
    new production (capable-to-promise) or on the replenishment lead time. Planned orders are only a plan; unless the
    run is made firm it is not made, and the promise goes late at the next roll."""
    new = [x for x in p.lines if x.method in ("ctp", "rlt")]
    mto = any((lp := ds.demand_lp((x.ship_from, rec.product))) is not None and lp.strategy is Strategy.MTO
              for x in p.lines if ds.location_type(x.ship_from) is not None)
    if not (new or mto):
        return ""
    return (" It needs new supply that is only planned: make it firm (Actuals → Open orders & firming) after the "
            "plan is recalculated, or it is not made.")


def _promise(ds: Dataset, rec: DemandRecord) -> tuple[OrderPromise, list[Confirmation]]:
    """Check ``rec`` after every order already promised, and its schedule lines as confirmations to keep."""
    res = check_order(ds, rec)
    if not res.ok or res.checked is None:
        raise OrderError("the data has problems that stop planning; fix them first (Home lists them)")
    p = res.checked
    confs = [Confirmation(order=rec.id or "", ship_from=x.ship_from, ship_date=x.ship_date, date=x.date, qty=x.qty,
                          method=x.method) for x in p.lines]
    return p, confs


def _check_parties(ds: Dataset, location: str, product: str) -> None:
    loc = ds.location_by_id.get(location)
    if loc is None:
        raise OrderError(f"there is no customer {location!r}")
    if loc.type is not LocationType.CUSTOMER and loc.type not in STOCKING_LOCATION_TYPES:
        raise OrderError(f"{loc.name or loc.id} is a supplier; an order comes from a customer")
    if product not in ds.product_by_id:
        raise OrderError(f"there is no product {product!r}")


def accept(ds: Dataset, order: DemandRecord) -> tuple[Dataset, SalesOrderReport]:
    """Take a customer order with the promise the availability check gives it."""
    _check_parties(ds, order.location, order.product)
    if order.qty <= EPS:
        raise OrderError("an order needs a quantity")
    taken = {d.id for d in ds.demand if d.id} | {c.id for c in ds.closed_orders if c.kind == "sales"}
    oid = order.id or next_order_id(ds)
    if oid in taken:
        raise OrderError(f"{oid} is already an order number; leave the number empty to get the next one")
    rec = order.model_copy(update={"id": oid, "kind": DemandKind.SALES_ORDER, "ordered_qty": None,
                                   "period_days": None})
    p, confs = _promise(ds, rec)
    new = ds.model_copy(update={"demand": [*ds.demand, rec], "confirmations": [*ds.confirmations, *confs]})
    msg = (f"{oid} taken: {_n(rec.qty)} {_name(ds, 'product', rec.product)} for {_name(ds, 'location', rec.location)}, "
           f"asked for {_day(rec.date)}; {_promised(ds, p)}.{_new_supply(ds, rec, p)}")
    return Dataset.model_validate(new.model_dump()), SalesOrderReport(ok=True, order=oid, message=msg, promise=p)


CHANGEABLE = ("qty", "date", "priority", "price", "complete_delivery", "customer_ref")


def change(ds: Dataset, oid: str, changes: dict) -> tuple[Dataset, SalesOrderReport]:
    """Change an open order and promise it again. ``changes`` holds any of :data:`CHANGEABLE`; ``qty`` is the whole
    ordered quantity (what has been delivered included), ``price`` None clears the order's own price."""
    d = _open(ds, oid)
    unknown = set(changes) - set(CHANGEABLE)
    if unknown:
        raise OrderError(f"an order's {', '.join(sorted(unknown))} cannot be changed; cancel it and take a new one")
    ordered = ordered_now(ds, d)
    booked = ordered - d.qty                   # delivered and already booked by a roll
    done = delivered(ds, oid)
    upd = {k: v for k, v in changes.items() if k != "qty"}
    if "qty" in changes and changes["qty"] is not None:
        q = float(changes["qty"])
        if q < done - EPS:
            raise OrderError(f"{_n(done)} of {oid} have already been delivered; the order cannot be for less")
        if q - done <= EPS:
            raise OrderError(f"that is what has been delivered: close {oid} with Cancel the rest instead")
        upd["qty"] = round(q - booked, 6)
        if d.ordered_qty is not None:
            upd["ordered_qty"] = q
    rec = d.model_copy(update=upd)
    rec = DemandRecord.model_validate(rec.model_dump())
    rest = ds.model_copy(update={"demand": [x for x in ds.demand if x is not d],
                                 "confirmations": [c for c in ds.confirmations if c.order != oid]})
    p, confs = _promise(rest, rec)
    new = ds.model_copy(update={"demand": [rec if x is d else x for x in ds.demand],
                                "confirmations": [*rest.confirmations, *confs]})
    what = ", ".join(_said(ds, d, rec)) or "nothing changed"
    msg = f"{oid} changed ({what}); {_promised(ds, p)}."
    return Dataset.model_validate(new.model_dump()), SalesOrderReport(ok=True, order=oid, message=msg, promise=p)


def _said(ds: Dataset, a: DemandRecord, b: DemandRecord) -> list[str]:
    out = []
    if ordered_now(ds, a) != ordered_now(ds, b):
        out.append(f"quantity {_n(ordered_now(ds, a))} → {_n(ordered_now(ds, b))}")
    if a.date != b.date:
        out.append(f"date {_day(a.date)} → {_day(b.date)}")
    if a.priority != b.priority:
        out.append(f"priority {a.priority} → {b.priority}")
    if a.price != b.price:
        out.append("price " + (f"{_n(b.price)}" if b.price is not None else "from the price list"))
    if a.complete_delivery != b.complete_delivery:
        out.append("complete delivery only" if b.complete_delivery else "part deliveries allowed")
    if a.customer_ref != b.customer_ref:
        out.append(f"customer's number {b.customer_ref or '(none)'}")
    return out


def _open(ds: Dataset, oid: str) -> DemandRecord:
    try:
        return sales_order(ds, oid)
    except PostingError as e:
        raise OrderError(str(e)) from e


def cancel(ds: Dataset, oid: str, on: dt.date | None = None, reason: str = "") -> tuple[Dataset, SalesOrderReport]:
    """Cancel what is still open on an order; it is logged as closed (cancelled) with what was delivered."""
    d = _open(ds, oid)
    ordered = ordered_now(ds, d)
    sales = [m for m in ds.movements if m.type is MovementType.SALE and m.reference == oid]
    done = sum(m.qty for m in sales)
    arrive = [arrival(ds, m.location, d.location, d.product, m.date) for m in sales]
    cf = [c for c in ds.confirmations if c.order == oid]
    closed = ClosedOrder(kind="sales", id=oid, location=d.location, product=d.product,
                         counterparty=sales[0].location if sales else None, ordered_qty=ordered, delivered_qty=done,
                         due_date=d.date, promised_date=max((c.date for c in cf), default=None),
                         first_delivery=min(arrive, default=None), last_delivery=max(arrive, default=None),
                         closed_on=on or ds.settings.planning_start, cancelled=True)
    new = ds.model_copy(update={"demand": [x for x in ds.demand if x is not d],
                                "confirmations": [c for c in ds.confirmations if c.order != oid],
                                "closed_orders": [*ds.closed_orders, closed]})
    rest = ordered - done
    msg = (f"{oid} cancelled" + (f": {_n(done)} delivered, {_n(rest)} no longer wanted" if done > EPS
                                 else f": {_n(rest)} {_name(ds, 'product', d.product)} for "
                                      f"{_name(ds, 'location', d.location)} no longer wanted")
           + (f" ({reason})" if reason else "") + ". Its promised stock is free for other orders.")
    return Dataset.model_validate(new.model_dump()), SalesOrderReport(ok=True, order=oid, message=msg)
