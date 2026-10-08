"""Money at risk per exception (roadmap F, UX audit section 4): the exception inbox ranks work by what it costs to
leave it, not only by status and age.

Each worklist item gets an amount in the company currency, the words that say how it was worked out, the customer it
concerns (for grouping), and one suggested action with what that action protects and, when the data says it, what it
costs. The rules, by kind of exception:

* **Late or uncovered demand** (DEMAND_AT_RISK, STOCKOUT, PROMISE_LATE, PROMISE_AT_RISK, ORDER_OVERDUE): late units ×
  selling price (the order's own, else the customer's, else the product's; the unit cost when nothing is priced) ×
  ``tower.late_revenue_factor`` (the share of a late sale counted as lost; default 1 = all of it).
* **Below safety stock**: the shortfall × unit cost × the carrying rate (the buffer's yearly cost not earned back).
* **Capacity** (CAPACITY_OVERLOAD, CAPACITY_OVERTIME, SUPPLIER_CAPACITY): the excess hours × the machine's overtime
  rate (else its hourly cost): what covering it costs.
* **Excess stock** (EXCESS_STOCK, NO_DEMAND_STOCK, and a firm receipt early or not needed: RESCHEDULE_OUT,
  RECEIPT_NOT_NEEDED): the excess × unit cost × carrying rate (a year of holding it).
* **Expiry** (SHELF_LIFE_RISK, STOCK_EXPIRES, LOT_EXPIRES): the quantity × unit cost (written off).
* **Open supply late or short** (RECEIPT_OVERDUE, PO_*, RESCHEDULE_IN, START_IN_PAST, SCHEDULE_LATE…): the quantity ×
  selling price when the product is sold, else × unit cost: the value held up.
* **Money owed** (INVOICE_BLOCKED, PAYABLE_OVERDUE, RECEIVABLE_OVERDUE): the open amount; CREDIT_BLOCK: the open
  order lines at their price.
* **Forecast bias**: the gap between forecast and actual × selling price.

Nothing is invented: an amount that cannot be worked out from the data is 0 with the reason in ``money_basis``.
"""
from __future__ import annotations

import re

from ..model import Dataset
from ..plan import PlanResult
from .result import InboxAction, WorkItem

LATE_DEMAND = {"DEMAND_AT_RISK", "STOCKOUT", "PROMISE_LATE", "PROMISE_AT_RISK", "ORDER_OVERDUE"}
CAPACITY = {"CAPACITY_OVERLOAD", "CAPACITY_OVERTIME", "CAPACITY_DAY_OVERLOAD", "SUPPLIER_CAPACITY", "LANE_CAPACITY"}
EXCESS = {"EXCESS_STOCK", "NO_DEMAND_STOCK", "RESCHEDULE_OUT", "RECEIPT_NOT_NEEDED"}
EXPIRY = {"SHELF_LIFE_RISK", "STOCK_EXPIRES", "LOT_EXPIRES"}
OWED = {"INVOICE_BLOCKED", "PAYABLE_OVERDUE", "RECEIVABLE_OVERDUE"}


class Pricer:
    """Prices and costs read once for a run."""

    def __init__(self, ds: Dataset, plan: PlanResult | None) -> None:
        self.ds = ds
        self.cost = {(n.location, n.product): n.unit_value for n in plan.nodes} if plan is not None and plan.ok else {}
        self.demand = {}
        for d in ds.demand:
            for k in (d.id, d.order):
                if k and k not in self.demand:
                    self.demand[k] = d

    def unit_cost(self, location: str | None, product: str | None) -> float | None:
        if not product:
            return None
        if (location, product) in self.cost and self.cost[(location, product)] > 0:
            return self.cost[(location, product)]
        vals = [v for (_, p), v in self.cost.items() if p == product and v > 0]
        if vals:
            return max(vals)
        pu = [s.price for s in self.ds.purchasing_sources if s.product == product and not s.blocked]
        return min(pu) if pu else None

    def sell(self, location: str | None, product: str | None, order: str | None = None) -> float | None:
        if not product:
            return None
        d = self.demand.get(order or "")
        if d is not None and d.product == product:
            p = self.ds.selling_price(d.location, product, d.price)
            if p is not None:
                return p
        if location:
            p = self.ds.selling_price(location, product)
            if p is not None:
                return p
        prod = self.ds.product_by_id.get(product)
        return prod.price if prod and prod.price else None

    def customer(self, w: WorkItem) -> str | None:
        d = self.demand.get(w.order_id or "")
        if d is not None:
            so = next((s for s in self.ds.sales_orders if s.id == (d.order or "")), None)
            return so.customer if so else d.location if self._is_customer(d.location) else None
        so = next((s for s in self.ds.sales_orders if s.id == w.order_id), None) if w.order_id else None
        if so is not None:
            return so.customer
        inv = next((i for i in self.ds.invoices if i.id == w.order_id), None) if w.order_id else None
        if inv is not None:
            return inv.customer
        return w.location if self._is_customer(w.location) else None

    def _is_customer(self, loc: str | None) -> bool:
        x = self.ds.location_by_id.get(loc or "")
        return x is not None and x.type.value == "customer"


_KIND = {"purchase": "buy", "production": "make", "transfer": "transfer"}


def order_kinds(ds: Dataset, plan: PlanResult | None) -> dict[str, str]:
    """``buy``, ``make`` or ``transfer`` for every planned and firm order, by its id."""
    out = {o.id: str(getattr(o.kind, "value", o.kind)) for o in plan.orders} if plan is not None and plan.ok else {}
    for r in ds.receipts:
        out.setdefault(r.id, _KIND.get(str(getattr(r.kind, "value", r.kind)), ""))
    for po in ds.purchase_orders:
        out.setdefault(po.id, "buy")
    return out


def _supply_action(ds: Dataset, w: WorkItem, protects: float, kind: str | None = None) -> InboxAction:
    """For late or short supply: the action that fits the order the item names (a transfer is shipped early, a
    production order brought forward); otherwise switch to a quicker supplier when one exists, else expedite."""
    if kind == "transfer":
        return InboxAction(kind="expedite", label="Ship the transfer now", protects=protects, href="#/execution")
    if kind == "make":
        return InboxAction(kind="expedite", label="Bring the production order forward", protects=protects,
                           href="#/execution")
    loc, prod, qty = w.location, w.product, abs(w.qty or 0.0)
    sources = [s for s in ds.purchasing_sources if s.product == prod and not s.blocked
               and (loc is None or s.location == loc)]
    if not sources:              # demand at a customer: the product is bought where it ships from
        sources = [s for s in ds.purchasing_sources if s.product == prod and not s.blocked]
    if len(sources) >= 2:
        cur = min(sources, key=lambda s: (s.price, s.lead_time_days))
        alt = min((s for s in sources if s is not cur), key=lambda s: (s.lead_time_days, s.price))
        if alt.lead_time_days < cur.lead_time_days:
            who = ds.location_by_id[alt.supplier].name if alt.supplier in ds.location_by_id else alt.supplier
            return InboxAction(kind="switch_supplier", label=f"Switch {qty:,.0f} to {who or alt.supplier} "
                               f"({alt.lead_time_days:g} d instead of {cur.lead_time_days:g} d)",
                               protects=protects, costs=round((alt.price - cur.price) * qty, 2), href="#/buying")
    if sources:
        return InboxAction(kind="expedite", label="Expedite the purchase order", protects=protects, href="#/buying")
    made = any(p.product == prod for p in ds.production_sources)
    if made:
        return InboxAction(kind="expedite", label="Bring the production order forward", protects=protects,
                           href="#/execution")
    return InboxAction(kind="review", label="Look at the plan for this product", protects=protects, href="#/plan")


def price_items(ds: Dataset, plan: PlanResult | None, items: list[WorkItem]) -> list[WorkItem]:
    """Fill ``money_at_risk``, ``money_basis``, ``customer`` and ``action`` on each item (in place; returned)."""
    pr = Pricer(ds, plan)
    kinds = order_kinds(ds, plan)
    cur = ds.settings.currency
    rate = ds.settings.carrying_rate
    factor = ds.tower.late_revenue_factor
    res = {r.id: r for r in ds.resources}
    for w in items:
        qty = abs(w.qty or 0.0)
        code = w.code
        w.customer = pr.customer(w)
        amount, basis, action = 0.0, "", None
        if code in LATE_DEMAND:
            p = pr.sell(w.location, w.product, w.order_id)
            what = "selling price"
            if p is None:
                p, what = pr.unit_cost(w.location, w.product), "unit cost (no selling price)"
            if p is not None and qty:
                amount = qty * p * factor
                basis = f"{qty:,.0f} late × {p:,.2f} {cur} {what}" + (f" × {factor:g} late-sale share" if factor != 1 else "")
                action = _supply_action(ds, w, amount)
            else:
                basis = "no price or cost for this product"
        elif code == "BELOW_SAFETY_STOCK":
            c = pr.unit_cost(w.location, w.product)
            if c is not None and qty:
                amount = qty * c * rate
                basis = f"{qty:,.0f} below the buffer × {c:,.2f} {cur} × {rate:.0%} a year"
                action = _supply_action(ds, w, amount)
        elif code in CAPACITY:
            r = res.get(w.resource or "")
            hr = (r.overtime_cost_per_hour or r.cost_per_hour) if r is not None else 0.0
            if hr and qty:
                amount = qty * hr
                basis = f"{qty:,.1f} h over × {hr:,.2f} {cur}/h " + ("overtime" if r and r.overtime_cost_per_hour else "machine cost")
                action = InboxAction(kind="overtime", label=f"Add {qty:,.1f} h of overtime on {r.name or r.id}",
                                     protects=amount, costs=round(amount, 2), href="#/capacity")
            else:
                basis = "no hourly cost on this machine" if r is not None else "no machine cost known"
                action = InboxAction(kind="overtime", label="Add overtime or move load", protects=0.0, href="#/capacity")
        elif code in EXCESS:
            c = pr.unit_cost(w.location, w.product)
            early = re.search(r"push it out by (\d+) d", w.message) if code == "RESCHEDULE_OUT" else None
            if c is not None and qty and early:      # held only for the days it comes early, not a year
                days = int(early.group(1))
                amount = qty * c * rate * days / 365.0
                basis = f"{qty:,.0f} early × {c:,.2f} {cur} × {rate:.0%} a year × {days} d"
                action = InboxAction(kind="push_out", label="Push out the receipt", protects=amount, href="#/buying")
            elif c is not None and qty:
                amount = qty * c * rate
                basis = f"{qty:,.0f} excess × {c:,.2f} {cur} × {rate:.0%} a year to hold"
                action = InboxAction(kind="push_out", label="Push out or cancel open receipts", protects=amount,
                                     href="#/buying")
        elif code in EXPIRY:
            c = pr.unit_cost(w.location, w.product)
            if c is not None and qty:
                amount = qty * c
                basis = f"{qty:,.0f} may expire × {c:,.2f} {cur}"
                action = InboxAction(kind="sell_first", label="Sell or use it first", protects=amount, href="#/inventory")
        elif code in OWED:
            amount = qty
            basis = f"{qty:,.2f} {cur} open"
            action = InboxAction(kind="chase" if code == "RECEIVABLE_OVERDUE" else "pay",
                                 label="Chase the payment" if code == "RECEIVABLE_OVERDUE" else "Clear and pay it",
                                 protects=amount, href="#/selling" if code == "RECEIVABLE_OVERDUE" else "#/buying")
        elif code == "CREDIT_BLOCK":
            lines = [d for d in ds.demand if d.order == w.order_id and d.qty > 0]
            for d in lines:
                p = ds.selling_price(d.location, d.product, d.price)
                amount += d.qty * (p or 0.0)
            basis = f"{len(lines)} open line(s) at their price" if amount else "the order's lines have no price"
            action = InboxAction(kind="release", label="Review the credit block", protects=amount, href="#/selling")
        elif code == "FORECAST_BIAS":
            p = pr.sell(w.location, w.product)
            if p is not None and qty:
                amount = qty * p
                basis = f"{qty:,.0f} forecast gap × {p:,.2f} {cur}"
            action = InboxAction(kind="review", label="Review the forecast", protects=amount, href="#/demand")
        elif w.product and qty:            # open supply late, short or to move: the value held up
            p = pr.sell(w.location, w.product)
            what = "selling price"
            if p is None:
                p, what = pr.unit_cost(w.location, w.product), "unit cost"
            if p is not None:
                amount = qty * p
                basis = f"{qty:,.0f} held up × {p:,.2f} {cur} {what}"
                action = _supply_action(ds, w, amount, kinds.get(w.order_id or ""))
        if not basis:
            basis = "not priced: no quantity or price to work it out from"
        w.money_at_risk = round(amount, 2)
        w.money_basis = basis
        w.action = action
    return items


def inbox_order(items: list[WorkItem]) -> list[str]:
    """The exception inbox: open and acknowledged items, the most money at risk first (then breached, then oldest)."""
    live = [w for w in items if w.status in ("open", "acknowledged")]
    live.sort(key=lambda w: (-w.money_at_risk, not w.breached, -w.age_days, w.key))
    return [w.id for w in live]
