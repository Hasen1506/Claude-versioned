"""Cash the plan needs (Enterprise 8.3; docs/CONFORMANCE.md §8, F15): what comes in and goes out week by week, each
on the payment terms of whoever pays or is paid, in the company currency.

Coming in:

* **invoices**: customers' unpaid invoices on their due date (credit notes paid back on theirs);
* **to bill**: what was delivered and not invoiced yet, billed now and paid on the customer's terms;
* **orders** and **forecast**: what the plan sells (open sales orders less what has shipped, and the forecast left
  after they consume it, as planning has them), at the customer's price, paid on the customer's terms after the date
  it is wanted.

Going out:

* **supplier invoices**: unpaid supplier invoices on their due date (credit memos taken off theirs);
* **purchase orders**: what open order lines still bring, on the supplier's terms after they arrive (confirmed
  date, else due date), and what was received and not invoiced yet, on the supplier's terms from now;
* **planned buying**: the plan's purchases (price, freight, duty, handling and ordering), on the supplier's terms after
  they arrive;
* **production** and **transfers**: the plan's production and transfers, paid when they start;
* **freight**: open freight orders, on the carrier's terms after loading; settled bills not yet due, on their date.

What falls due before the planning start is in the first week and counted as overdue; what falls due after the last
week is counted as later. The running total starts at nothing: its lowest point is the most cash the plan needs on top
of what is in the bank. A sale without a price brings nothing and is counted, so the gap is seen.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from pydantic import Field

from ..actuals.post import delivered, ordered_now
from ..model import Dataset
from ..model.common import Out
from ..plan import PlanResult
from ..plan.costing import fx
from ..plan.rates import independent_demand

IN = ("invoices", "to_bill", "orders", "forecast")
OUT = ("supplier_invoices", "purchase_orders", "planned_buying", "production", "transfers", "freight")
EPS = 1e-6


class CashWeek(Out):
    start: date
    receipts: float
    payments: float
    net: float
    cumulative: float
    by: dict[str, float] = Field(default_factory=dict)   # by kind (IN and OUT names); payments negative


class CashView(Out):
    currency: str
    start: date
    weeks: list[CashWeek] = Field(default_factory=list)
    receipts: float = 0.0
    payments: float = 0.0
    lowest: float = 0.0                 # the lowest running total (0 or less): the most cash needed
    lowest_week: date | None = None
    overdue_in: float = 0.0             # fell due before the start
    overdue_out: float = 0.0
    later_in: float = 0.0               # falls due after the last week
    later_out: float = 0.0
    unpriced: int = 0                   # sales with no price, left out
    notes: list[str] = Field(default_factory=list)


def cash_view(ds: Dataset, plan: PlanResult, weeks: int | None = None) -> CashView:
    start = ds.settings.planning_start
    n = weeks or max(1, math.ceil(ds.settings.horizon_days / 7))
    end = start + timedelta(weeks=n)
    view = CashView(currency=ds.settings.currency, start=start)
    flows: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def add(kind: str, day: date, amount: float) -> None:
        if abs(amount) <= EPS:
            return
        out = kind in OUT
        if day < start:
            if out:
                view.overdue_out += amount
            else:
                view.overdue_in += amount
            day = start
        if day >= end:
            if out:
                view.later_out += amount
            else:
                view.later_in += amount
            return
        flows[(day - start).days // 7][kind] += -amount if out else amount

    def net_days(customer: str) -> int:
        return ds.terms_for(customer).net_days

    # ---- coming in
    for inv in ds.invoices:
        if inv.cancelled:
            continue
        left = inv.total - sum(p.amount + p.discount for p in inv.payments)
        add("invoices", inv.due_date, (-1 if inv.kind == "credit_note" else 1) * left)
    from ..sales import to_bill
    for b in to_bill(ds):
        if b.value is not None:
            add("to_bill", max(start, b.delivered_on) + timedelta(days=net_days(b.customer)), b.value)
    by_id = {d.id: d for d in ds.demand if d.id}
    for (loc, prod), reqs in independent_demand(ds).items():
        for r, _days in reqs:
            rec = by_id.get(r.source_ref) if r.kind == "sales_order" else None
            q = r.qty
            if rec is not None:          # shipped and not booked by a new week yet: it is to bill, not to sell
                q -= max(0.0, delivered(ds, rec.id or "") - (ordered_now(ds, rec) - rec.qty))
            if q <= EPS:
                continue
            price = ds.selling_price(loc, prod, rec.price if rec is not None else None)
            if price is None:
                view.unpriced += 1
                continue
            add("orders" if r.kind == "sales_order" else "forecast", r.date + timedelta(days=net_days(loc)), q * price)

    # ---- going out
    for si in ds.supplier_invoices:
        if si.cancelled:
            continue
        left = si.total - sum(p.amount + p.discount for p in si.payments)
        add("supplier_invoices", si.due_date, (-1 if si.credit else 1) * left * fx(ds, si.currency))
    from ..purchasing import purchase_orders
    for po in purchase_orders(ds, start):
        if not po.supplier:
            continue
        days = ds.vendor_terms(po.supplier).net_days
        rate = fx(ds, po.currency)
        for ln in po.lines:
            if ln.price is None:
                continue
            if not ln.closed and ln.open > EPS:
                add("purchase_orders", (ln.confirmed_date or ln.due_date) + timedelta(days=days),
                    ln.open * ln.price * rate)
            if ln.received - ln.invoiced > EPS:
                add("purchase_orders", start + timedelta(days=days), (ln.received - ln.invoiced) * ln.price * rate)
    for o in plan.orders:
        cost = o.total_cost
        if o.kind == "buy":
            add("planned_buying", o.due_date + timedelta(days=ds.vendor_terms(o.origin or "").net_days), cost)
        elif o.kind == "make":
            add("production", o.start_date, cost)
        else:
            add("transfers", o.start_date, cost)
    for f in ds.freight_orders:
        k = ds.carrier_by_id.get(f.carrier or "")
        days = k.payment_days if k else 0
        if f.status in ("planned", "tendered", "accepted", "shipped"):
            add("freight", f.planned_on + timedelta(days=days), f.planned_cost)
        elif f.status == "settled" and f.billed is not None and f.settled_on is not None:
            due = f.settled_on + timedelta(days=days)
            if due >= start:
                add("freight", due, f.billed)

    cum = 0.0
    for i in range(n):
        by = {k: round(v, 2) for k, v in flows[i].items() if abs(v) > 0.005}
        rec = round(sum(v for k, v in by.items() if k in IN), 2)
        pay = round(-sum(v for k, v in by.items() if k in OUT), 2)
        cum = round(cum + rec - pay, 2)
        view.weeks.append(CashWeek(start=start + timedelta(weeks=i), receipts=rec, payments=pay, net=round(rec - pay, 2),
                                   cumulative=cum, by=by))
        if cum < view.lowest - 0.005:
            view.lowest, view.lowest_week = cum, start + timedelta(weeks=i)
    view.receipts = round(sum(w.receipts for w in view.weeks), 2)
    view.payments = round(sum(w.payments for w in view.weeks), 2)
    for f in ("overdue_in", "overdue_out", "later_in", "later_out"):
        setattr(view, f, round(getattr(view, f), 2))
    if view.unpriced:
        one = view.unpriced == 1
        view.notes.append(f"{view.unpriced} sale{'' if one else 's'} of the plan {'has' if one else 'have'} no price "
                          "and bring nothing here: give the products or customers a price")
    if any(r.kind.value == "production" for r in ds.receipts):
        view.notes.append("firm production orders already started are not in it: what they still cost is paid as "
                          "they run")
    return view


__all__ = ["CashView", "CashWeek", "cash_view"]
