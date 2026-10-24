"""Third-party orders (Enterprise 7.1, S/4 guide §16.3, item category TAS): a sale the supplier ships straight to the
customer.

The order is taken for a customer, a product, a quantity and a date, at the customer's price (or one given), from a
supplier at the supplier's price (the purchasing source's, or one given). It is not demand at any of our places and
it is no supply to any of them, so planning, promising and deliveries never see it. Sent, it is the purchase order
to the supplier. Each dispatch advice from the supplier is at once its goods receipt (statistical: no stock moves)
and its delivery to the customer: it is billed to the customer with the other shipped lines (Selling's invoices), and
the supplier's invoice is matched against what was dispatched (Buying's three-way match). What is left on the order
after a final dispatch is closed short.
"""
from __future__ import annotations

import math
from datetime import date

from ..model import Dataset, LocationType, ThirdPartyOrder
from ..model.common import Out
from ..model.outside import DropShipment

EPS = 1e-9


class DropShipError(ValueError):
    """A step the data does not allow; the message says why in plain words."""


def _name(ds: Dataset, lid: str) -> str:
    lo = ds.location_by_id.get(lid) or ds.product_by_id.get(lid)
    return (lo.name or lid) if lo else lid


def _n(q: float) -> str:
    return f"{q:,.0f}" if abs(q - round(q)) < 1e-6 else f"{q:,.2f}"


def _money(cur: str, v: float) -> str:
    return f"{cur} {v:,.2f}"


def _day(d: date) -> str:
    return d.strftime("%a %d %b").replace(" 0", " ")


def _today(ds: Dataset, on: date | None) -> date:
    return on or ds.settings.planning_start


def _next_id(ds: Dataset) -> str:
    n = max((int(t.id[3:]) for t in ds.third_party_orders if t.id.startswith("TP-") and t.id[3:].isdigit()), default=0)
    return f"TP-{n + 1:05d}"


def _tp(ds: Dataset, tid: str) -> ThirdPartyOrder:
    t = next((t for t in ds.third_party_orders if t.id == tid), None)
    if t is None:
        raise DropShipError(f"there is no third-party order {tid}")
    return t


def _put(ds: Dataset, t: ThirdPartyOrder) -> Dataset:
    return ds.model_copy(update={"third_party_orders": [t if x.id == t.id else x for x in ds.third_party_orders]})


def billed(ds: Dataset) -> dict[str, float]:
    """Quantity invoiced to the customer per third-party order."""
    ids = {t.id for t in ds.third_party_orders}
    out: dict[str, float] = {}
    for inv in ds.invoices:
        if inv.kind == "invoice" and not inv.cancelled:
            for ln in inv.lines:
                if ln.order in ids:
                    out[ln.order] = out.get(ln.order, 0.0) + ln.qty
    return out


def shipment_key(tid: str, i: int) -> str:
    """What an invoice line lists for the dispatch it bills (as it lists the sale movements of a delivery)."""
    return f"{tid}#{i + 1}"


def to_bill(ds: Dataset) -> list[tuple[ThirdPartyOrder, int, DropShipment]]:
    """Dispatches not billed yet: (order, its index, the dispatch)."""
    done = {m for inv in ds.invoices if inv.kind == "invoice" and not inv.cancelled for ln in inv.lines
            for m in ln.movements}
    return [(t, i, s) for t in ds.third_party_orders if not t.cancelled for i, s in enumerate(t.shipments)
            if shipment_key(t.id, i) not in done]


def supplier_cost(ds: Dataset, supplier: str, product: str, qty: float) -> tuple[float | None, str | None]:
    """The supplier's price and currency for the product: its purchasing source (any of our places), else none."""
    for pu in ds.purchasing_sources:
        if pu.supplier == supplier and pu.product == product and not ds.source_blocked(pu):
            return pu.price_for(qty), ds.price_currency(pu)
    return None, None


# ------------------------------------------------------------------------------------------------ steps
class DropShipReport(Out):
    message: str
    orders: list[str] = []


def create(ds: Dataset, customer: str, product: str, qty: float, wanted: date, supplier: str, *,
           price: float | None = None, cost: float | None = None, customer_ref: str = "", note: str = "",
           on: date | None = None) -> tuple[Dataset, DropShipReport]:
    from ..sales import SalesError, _credit, _sellable, line_rate
    from ..sales import price as sale_price
    day = _today(ds, on)
    c = ds.location_by_id.get(customer)
    if c is None or c.type is not LocationType.CUSTOMER:
        raise DropShipError(f"{customer} is not a customer")
    s = ds.location_by_id.get(supplier)
    if s is None or s.type is not LocationType.SUPPLIER:
        raise DropShipError(f"{supplier} is not a supplier")
    if ds.vendor(supplier).blocked:
        raise DropShipError(f"{_name(ds, supplier)} is blocked for purchasing")
    if product not in ds.product_by_id:
        raise DropShipError(f"{product} is not a product")
    if not math.isfinite(qty) or qty <= 0:
        raise DropShipError("the quantity must be more than 0")
    try:
        _sellable(ds, customer)
    except SalesError as e:
        raise DropShipError(str(e)) from e
    if price is None:
        price = sale_price(ds, customer, product, qty)[0]
        if price is None:
            raise DropShipError(f"{_name(ds, product)} has no price for {_name(ds, customer)}: give one")
    cur = None
    if cost is None:
        cost, cur = supplier_cost(ds, supplier, product, qty)
        if cost is None:
            raise DropShipError(f"{_name(ds, supplier)} has no price for {_name(ds, product)}: give the cost")
    if price < 0 or cost < 0:
        raise DropShipError("prices cannot be negative")
    over, why = _credit(ds, customer, qty * price * (1 + line_rate(ds, customer, product)))
    if over:
        raise DropShipError(why + ": take payment first or raise the limit")
    cur = cur or ds.vendor(supplier).currency
    tid = _next_id(ds)
    t = ThirdPartyOrder(id=tid, customer=customer, product=product, qty=qty, date=wanted, price=round(price, 4),
                        supplier=supplier, cost=round(cost, 4),
                        currency=None if not cur or cur == ds.settings.currency else cur,
                        customer_ref=customer_ref, ordered_on=day, note=note)
    co = ds.settings.currency
    margin = _margin(ds, t)
    return (ds.model_copy(update={"third_party_orders": [*ds.third_party_orders, t]}),
            DropShipReport(orders=[tid], message=(
                f"{tid}: {_n(qty)} {_name(ds, product)} for {_name(ds, customer)} by {_day(wanted)}, shipped by "
                f"{_name(ds, supplier)}: sold at {_money(co, price)}, bought at "
                f"{_money(t.currency or co, cost)}"
                + (f", {_money(co, margin)} margin" if margin is not None else "") + ". Send it to the supplier.")))


def _margin(ds: Dataset, t: ThirdPartyOrder) -> float | None:
    from ..plan.costing import fx
    try:
        rate = fx(ds, t.currency)
    except Exception:          # a currency without a rate: no margin to show
        return None
    q = 0.0 if t.cancelled else (t.shipped if t.closed else t.qty)     # closed short: what was shipped
    return round(q * (t.price - t.cost * rate), 2)


def send(ds: Dataset, tid: str, on: date | None = None) -> tuple[Dataset, DropShipReport]:
    t = _tp(ds, tid)
    if t.cancelled:
        raise DropShipError(f"{tid} is cancelled")
    if t.sent_on is not None:
        raise DropShipError(f"{tid} went to {_name(ds, t.supplier)} on {_day(t.sent_on)}")
    day = _today(ds, on)
    return (_put(ds, t.model_copy(update={"sent_on": day})),
            DropShipReport(orders=[tid], message=f"{tid} sent to {_name(ds, t.supplier)} on {_day(day)}: ship "
                                                 f"{_n(t.qty)} {_name(ds, t.product)} to {_name(ds, t.customer)}."))


def dispatch(ds: Dataset, tid: str, qty: float | None = None, on: date | None = None, reference: str = "",
             final: bool = False) -> tuple[Dataset, DropShipReport]:
    """The supplier's dispatch advice: the goods receipt and the delivery to the customer at once (no stock moves)."""
    t = _tp(ds, tid)
    if t.cancelled:
        raise DropShipError(f"{tid} is cancelled")
    if t.sent_on is None:
        raise DropShipError(f"{tid} has not been sent to {_name(ds, t.supplier)} yet")
    if t.closed:
        raise DropShipError(f"{tid} is complete")
    left = t.qty - t.shipped
    q = left if qty is None else float(qty)
    if not math.isfinite(q) or q <= EPS:
        raise DropShipError("the quantity dispatched must be more than 0")
    over = ds.vendor(t.supplier).over_delivery_tolerance
    if over is not None and q > left + t.qty * over + EPS:
        raise DropShipError(f"{tid} has {_n(left)} left; {_n(q)} is more than {_name(ds, t.supplier)} may send")
    day = _today(ds, on)
    shp = DropShipment(date=day, qty=round(q, 6), reference=reference, final=final)
    new = t.model_copy(update={"shipments": [*t.shipments, shp]})
    rest = new.qty - new.shipped
    state = ("complete" if rest <= EPS else f"closed {_n(rest)} short") if new.closed else f"{_n(rest)} still to come"
    return (_put(ds, new), DropShipReport(orders=[tid], message=(
        f"{tid}: {_name(ds, t.supplier)} dispatched {_n(q)} {_name(ds, t.product)} to {_name(ds, t.customer)} on "
        f"{_day(day)}" + (f" (their {reference})" if reference else "") + f" ({state}). Ready to bill; their invoice "
        "is matched against it.")))


def cancel(ds: Dataset, tid: str) -> tuple[Dataset, DropShipReport]:
    t = _tp(ds, tid)
    if t.cancelled:
        raise DropShipError(f"{tid} is already cancelled")
    if t.shipments:
        raise DropShipError(f"{_name(ds, t.supplier)} has dispatched on {tid}: close it with a final dispatch instead")
    tell = f" Tell {_name(ds, t.supplier)}." if t.sent_on else ""
    return (_put(ds, t.model_copy(update={"cancelled": True})),
            DropShipReport(orders=[tid], message=f"{tid} cancelled.{tell}"))


# ------------------------------------------------------------------------------------------------ view
class ThirdPartyRow(Out):
    id: str
    customer: str
    customer_name: str
    product: str
    product_name: str
    supplier: str
    supplier_name: str
    qty: float
    date: date
    price: float
    cost: float
    currency: str                  # the purchase currency
    margin: float | None           # in the company's currency
    ordered_on: date
    sent_on: date | None
    shipped: float
    billed: float                  # to the customer
    supplier_invoiced: float
    status: str                    # to send | sent | partly dispatched | dispatched | billed | cancelled
    late: bool                     # not all dispatched and past the date wanted
    shipments: list[DropShipment]
    customer_ref: str
    note: str


class DropShipView(Out):
    as_of: date
    currency: str
    orders: list[ThirdPartyRow]
    open_value: float              # still to dispatch, at the sale price
    margin: float                  # on every order not cancelled


def view(ds: Dataset, on: date | None = None) -> DropShipView:
    from ..purchasing.payables import invoiced
    day = _today(ds, on)
    bl = billed(ds)
    sup = invoiced(ds)
    rows = []
    for t in sorted(ds.third_party_orders, key=lambda x: x.id, reverse=True):
        b = round(bl.get(t.id, 0.0), 6)
        if t.cancelled:
            st = "cancelled"
        elif t.sent_on is None:
            st = "to send"
        elif not t.shipments:
            st = "sent"
        elif not t.closed:
            st = "partly dispatched"
        else:
            st = "billed" if b >= t.shipped - EPS else "dispatched"
        rows.append(ThirdPartyRow(
            id=t.id, customer=t.customer, customer_name=_name(ds, t.customer), product=t.product,
            product_name=_name(ds, t.product), supplier=t.supplier, supplier_name=_name(ds, t.supplier), qty=t.qty,
            date=t.date, price=t.price, cost=t.cost, currency=t.currency or ds.settings.currency, margin=_margin(ds, t),
            ordered_on=t.ordered_on, sent_on=t.sent_on, shipped=t.shipped, billed=b,
            supplier_invoiced=round(sup.get(t.id, 0.0), 6), status=st,
            late=not t.closed and t.date < day, shipments=t.shipments, customer_ref=t.customer_ref, note=t.note))
    live = [t for t in ds.third_party_orders if not t.cancelled]
    return DropShipView(as_of=day, currency=ds.settings.currency, orders=rows,
                        open_value=round(sum((t.qty - t.shipped) * t.price for t in live if not t.closed), 2),
                        margin=round(sum(m for t in live if (m := _margin(ds, t)) is not None), 2))


__all__ = ["DropShipError", "DropShipReport", "DropShipView", "ThirdPartyRow", "billed", "cancel", "create",
           "dispatch", "send", "shipment_key", "supplier_cost", "to_bill", "view"]
