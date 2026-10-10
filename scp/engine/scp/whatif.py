"""What-if side by side (roadmap E, UX audit section 4): plan 2–4 scenarios and compare them in one table, with each
scenario's cost, service, inventory and capacity and its deltas against the first (the baseline), the cost of one
point of service, and the levers it changed.

A scenario is the baseline dataset with **chips** applied (quick changes made in one click), or a whole dataset of its
own (a stored version). Chips:

* ``demand``: every forecast and sales-order quantity × (1 + pct/100), optionally only some products;
* ``supplier_out``: a supplier's purchasing sources blocked, so planning buys elsewhere; where it is the only
  supplier, nothing it sells arrives inside the horizon (open orders still do) and the shortage shows as demand at risk;
* ``lead_time``: purchasing lead times + days (one supplier, or all);
* ``add_shift``: one more shift on a machine or line (one more of the usual length, with overtime trimmed to what is
  left of the day; or a named shift added after the last one), while the day still has room;
* ``lane_delay``: transit days + days on every route from or to a place (a port held up by the monsoon);
* ``machine_down``: a machine or line out for N days from a date (planning start by default): no units in that period;
* ``customer_price``: one customer's prices × (1 + pct/100): its own prices, its open orders' own prices, and the
  product's price as its own where it had none;
* ``safety_days``: safety stock as N days of forward cover (all products at their places, or some products);
* ``fx``: a foreign currency's rate × (1 + pct/100) (imported parts dearer or cheaper in the company currency).

A scenario that wins can be kept as a stored scenario of the current base (``keep_scenario``): its chips are written
into the data of a branch, which is then promoted like any other version.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field

from .model import Dataset
from .model.common import Out
from .model.master import CapacityChange, CustomerPrice, SafetyStockPolicy, Shift
from .model.common import SafetyStockMethod
from .plan import run_mrp
from .versions.diff import diff
from .versions.store import Store, VersionMeta


class DemandChip(Out):
    kind: Literal["demand"] = "demand"
    pct: float = Field(ge=-90, le=500, description="Change in per cent: 20 = +20 %")
    products: list[str] = []


class SupplierOutChip(Out):
    kind: Literal["supplier_out"] = "supplier_out"
    supplier: str


class LeadTimeChip(Out):
    kind: Literal["lead_time"] = "lead_time"
    days: float = Field(ge=-365, le=365)
    supplier: str | None = None


class AddShiftChip(Out):
    kind: Literal["add_shift"] = "add_shift"
    resource: str


class LaneDelayChip(Out):
    kind: Literal["lane_delay"] = "lane_delay"
    days: float = Field(ge=0, le=365)
    location: str | None = None          # routes from or to this place; none: every route


class MachineDownChip(Out):
    kind: Literal["machine_down"] = "machine_down"
    resource: str
    days: int = Field(ge=1, le=366)
    start: dt.date | None = None         # first day out; none: the planning start


class CustomerPriceChip(Out):
    kind: Literal["customer_price"] = "customer_price"
    customer: str
    pct: float = Field(ge=-90, le=500)


class SafetyDaysChip(Out):
    kind: Literal["safety_days"] = "safety_days"
    days: float = Field(ge=0, le=365)    # 0 = no safety stock
    products: list[str] = []


class FxChip(Out):
    kind: Literal["fx"] = "fx"
    currency: str = Field(min_length=3, max_length=3)
    pct: float = Field(ge=-90, le=500)


Chip = Annotated[DemandChip | SupplierOutChip | LeadTimeChip | AddShiftChip | LaneDelayChip | MachineDownChip
                 | CustomerPriceChip | SafetyDaysChip | FxChip, Field(discriminator="kind")]


class WhatIfError(ValueError):
    pass


def chip_label(c: Chip) -> str:
    if isinstance(c, DemandChip):
        return f"Demand {c.pct:+g} %" + (f" ({', '.join(c.products)})" if c.products else "")
    if isinstance(c, SupplierOutChip):
        return f"{c.supplier} out"
    if isinstance(c, LeadTimeChip):
        return f"Lead time {c.days:+g} d" + (f" at {c.supplier}" if c.supplier else "")
    if isinstance(c, AddShiftChip):
        return f"Add a shift on {c.resource}"
    if isinstance(c, MachineDownChip):
        return f"{c.resource} down {c.days} d" + (f" from {c.start.isoformat()}" if c.start else "")
    if isinstance(c, CustomerPriceChip):
        return f"Prices {c.pct:+g} % for {c.customer}"
    if isinstance(c, SafetyDaysChip):
        return f"Safety stock {c.days:g} d" + (f" ({', '.join(c.products)})" if c.products else "")
    if isinstance(c, FxChip):
        return f"{c.currency.upper()} {c.pct:+g} %"
    return f"Routes {'via ' + c.location + ' ' if c.location else ''}+{c.days:g} d"


def apply_chips(ds: Dataset, chips: list[Chip], notes: list[str] | None = None) -> Dataset:
    """A copy of ``ds`` with every chip applied in turn (the original is untouched). What a chip could only
    approximate is added to ``notes``."""
    d = ds.model_copy(deep=True)
    for c in chips:
        if isinstance(c, DemandChip):
            f = 1 + c.pct / 100
            for r in d.demand:
                if r.kind.value in ("forecast", "sales_order") and (not c.products or r.product in c.products):
                    r.qty = round(r.qty * f, 6)
        elif isinstance(c, SupplierOutChip):
            hit = [s for s in d.purchasing_sources if s.supplier == c.supplier]
            if not hit:
                raise WhatIfError(f"no product is bought from {c.supplier}")
            sole: list[str] = []
            for s in hit:
                others = [o for o in d.purchasing_sources if o is not s and o.supplier != c.supplier
                          and o.location == s.location and o.product == s.product and not d.source_blocked(o)]
                if others:
                    s.blocked = True             # planning buys from the other supplier instead
                    s.fixed = False
                else:
                    # blocking a sole source would stop the whole plan with a data error; a supplier that is out
                    # delivers nothing inside the horizon instead, so the shortage shows up as demand at risk
                    s.lead_time_days = float(d.settings.horizon_days + 1)
                    sole.append(f"{s.product} at {s.location}")
            if sole and notes is not None:
                notes.append(f"No other supplier for {', '.join(sorted(set(sole)))}: nothing from {c.supplier} "
                             "arrives within the horizon (open orders still do)")
        elif isinstance(c, LeadTimeChip):
            hit = [s for s in d.purchasing_sources if c.supplier is None or s.supplier == c.supplier]
            if not hit:
                raise WhatIfError(f"no product is bought from {c.supplier}")
            for s in hit:
                s.lead_time_days = max(0.0, s.lead_time_days + c.days)
        elif isinstance(c, AddShiftChip):
            r = next((x for x in d.resources if x.id == c.resource), None)
            if r is None:
                raise WhatIfError(f"there is no machine or line {c.resource}")
            if not r.shifts:
                n = r.shifts_per_day + 1
                if n > 4 or n * r.hours_per_shift > 24 + 1e-9:
                    raise WhatIfError(f"{c.resource} has no room in its day for another shift")
                r.shifts_per_day = n
                # the new shift takes the hours overtime used to cover: overtime only fills what is left of the day
                r.overtime_hours_per_day = max(0.0, min(r.overtime_hours_per_day, 24 - n * r.hours_per_shift))
            else:
                first, last = r.shifts[0], r.shifts[-1]
                if sum(s.length_hours for s in r.shifts) + first.length_hours > 24 + 1e-9:
                    raise WhatIfError(f"{c.resource} has no room in its day for another shift")
                start = last.end
                h, m = map(int, start.split(":"))
                mins = (h * 60 + m + round(first.length_hours * 60)) % (24 * 60)
                r.shifts = [*r.shifts, Shift(name="Added", start=start, end=f"{mins // 60:02d}:{mins % 60:02d}",
                                             break_minutes=first.break_minutes, weekdays=first.weekdays)]
        elif isinstance(c, LaneDelayChip):
            hit = [ln for ln in d.lanes if c.location is None or c.location in (ln.origin, ln.destination)]
            if not hit:
                raise WhatIfError(f"no route goes from or to {c.location}")
            for ln in hit:
                for m in ln.modes:
                    m.transit_days = m.transit_days + c.days
        elif isinstance(c, MachineDownChip):
            r = next((x for x in d.resources if x.id == c.resource), None)
            if r is None:
                raise WhatIfError(f"there is no machine or line {c.resource}")
            first = c.start or d.settings.planning_start
            # appended last: later rows win over the machine's other periods while it is out
            r.capacity_changes = [*r.capacity_changes, CapacityChange(
                valid_from=first, valid_to=first + dt.timedelta(days=c.days - 1), units=0, note="down (what-if)")]
        elif isinstance(c, CustomerPriceChip):
            if d.location_by_id.get(c.customer) is None:
                raise WhatIfError(f"there is no customer {c.customer}")
            f = 1 + c.pct / 100
            sold = {r.product for r in d.demand if r.location == c.customer}
            own = {cp.product for cp in d.customer_prices if cp.customer == c.customer}
            for cp in d.customer_prices:
                if cp.customer == c.customer:
                    cp.price = round(cp.price * f, 6)
                    for sc in cp.scales:
                        sc.price = round(sc.price * f, 6)
            for prod in sorted(sold - own):
                p = d.product_by_id.get(prod)
                if p is not None and p.price:
                    d.customer_prices.append(CustomerPrice(customer=c.customer, product=prod, price=round(p.price * f, 6)))
            for r in d.demand:
                if r.location == c.customer and r.price is not None:
                    r.price = round(r.price * f, 6)
            if not sold and notes is not None:
                notes.append(f"{c.customer} has no demand in the data: its prices change nothing in this plan")
        elif isinstance(c, SafetyDaysChip):
            hit = [lp for lp in d.location_products if not c.products or lp.product in c.products]
            if not hit:
                raise WhatIfError(f"no product is planned at a place for {', '.join(c.products)}")
            for lp in hit:
                lp.safety_stock = (SafetyStockPolicy(method=SafetyStockMethod.DAYS_OF_SUPPLY, days=c.days) if c.days
                                   else SafetyStockPolicy())
        elif isinstance(c, FxChip):
            cur = c.currency.upper()
            if cur == d.settings.currency.upper():
                raise WhatIfError(f"{cur} is the company's own currency")
            if cur not in d.settings.fx_rates:
                raise WhatIfError(f"there is no exchange rate for {cur}: nothing is bought in it")
            d.settings.fx_rates = {**d.settings.fx_rates, cur: round(d.settings.fx_rates[cur] * (1 + c.pct / 100), 8)}
    try:
        return Dataset.model_validate(d.model_dump(mode="json"))
    except ValueError as e:
        raise WhatIfError(f"these changes make the data invalid: {str(e).splitlines()[-2:]}") from None


class ScenarioIn(Out):
    label: str = Field(min_length=1, max_length=60)
    chips: list[Chip] = []
    dataset: Dataset | None = None       # a whole dataset of its own (a stored version) instead of base + chips


class WhatIfRequest(Out):
    base: Dataset
    scenarios: list[ScenarioIn] = Field(min_length=2, max_length=4)


class Lever(Out):
    what: str                            # "Demand +20 %" or a changed list ("lanes: 2 changed")


class ScenarioOut(Out):
    label: str
    ok: bool
    levers: list[Lever] = []
    total_cost: float = 0.0
    service: float = 0.0                 # on-time fill rate of independent demand (0–1)
    inventory_value_avg: float = 0.0
    capacity_peak: float = 0.0           # the busiest machine's utilisation (0–1+)
    late_units: float = 0.0
    late_revenue: float = 0.0            # late units at their selling price
    sales_value: float = 0.0             # the plan's independent demand at the customer's (else product's) price
    orders: int = 0
    errors: int = 0
    # against the first scenario (the baseline): None on the baseline itself
    cost_delta: float | None = None
    service_delta: float | None = None   # in points of service (0.05 = +5 points)
    inventory_delta: float | None = None
    late_units_delta: float | None = None
    sales_delta: float | None = None
    cost_per_service_point: float | None = None   # cost per point of service traded (None: no trade-off)
    verdict: str = ""                    # "trade-off", "better on both", "worse on both", "same service"
    note: str = ""


class WhatIfResult(Out):
    currency: str
    scenarios: list[ScenarioOut]
    best_service: str = ""
    lowest_cost: str = ""


def _metrics(label: str, ds: Dataset) -> ScenarioOut:
    p = run_mrp(ds)
    k = p.kpis
    out = ScenarioOut(label=label, ok=p.ok)
    if not p.ok:
        out.note = "the plan is blocked by data errors: " + "; ".join(i.message for i in p.issues[:3])
        return out
    late = max(0.0, k.independent_demand - k.on_time_qty)
    rev = 0.0
    for e in p.exceptions:
        if e.code == "DEMAND_AT_RISK" and e.qty and e.product:
            price = ds.selling_price(e.location or "", e.product)
            rev += e.qty * (price or 0.0)
    sales = 0.0
    for n in p.nodes:
        dem = sum(b.gross_independent for b in n.buckets)
        if dem > 0:
            sales += dem * (ds.selling_price(n.location, n.product) or 0.0)
    out.sales_value = round(sales, 2)
    out.total_cost, out.service, out.inventory_value_avg = k.total_cost, k.on_time_fill_rate, k.inventory_value_avg
    out.capacity_peak, out.late_units, out.late_revenue = k.max_utilization, late, round(rev, 2)
    out.orders, out.errors = len(p.orders), sum(e.severity == "error" for e in p.exceptions)
    return out


def compare_scenarios(req: WhatIfRequest) -> WhatIfResult:
    """Plan every scenario and compare it with the first."""
    built: list[tuple[ScenarioIn, Dataset, list[str]]] = []
    for s in req.scenarios:
        if s.dataset is not None and s.chips:
            raise WhatIfError(f"{s.label}: give either a dataset or chips, not both")
        notes: list[str] = []
        built.append((s, s.dataset if s.dataset is not None else apply_chips(req.base, s.chips, notes), notes))
    labels = [s.label for s, _, _ in built]
    if len(set(labels)) != len(labels):
        raise WhatIfError("every scenario needs its own name")
    outs: list[ScenarioOut] = []
    base_ds = built[0][1]
    for i, (s, ds, notes) in enumerate(built):
        o = _metrics(s.label, ds)
        o.levers = [Lever(what=chip_label(c)) for c in s.chips]
        if notes:
            o.note = "; ".join([*notes, *([o.note] if o.note else [])])
        if s.dataset is not None and i > 0:
            dd = diff(base_ds, ds)
            o.levers += [Lever(what=f"{c.collection}: {c.added} added, {c.removed} removed, {c.changed} changed")
                         for c in dd.collections if c.added or c.removed or c.changed]
        outs.append(o)
    b = outs[0]
    for o in outs[1:]:
        if not (o.ok and b.ok):
            continue
        o.cost_delta = round(o.total_cost - b.total_cost, 2)
        o.service_delta = round(o.service - b.service, 6)
        o.inventory_delta = round(o.inventory_value_avg - b.inventory_value_avg, 2)
        o.late_units_delta = round(o.late_units - b.late_units, 6)
        o.sales_delta = round(o.sales_value - b.sales_value, 2)
        pts = o.service_delta * 100
        if abs(pts) < 0.01:
            o.verdict = "same service"
        elif (o.cost_delta > 0) == (pts > 0) and o.cost_delta != 0:
            o.verdict = "trade-off"           # pay more for more service, or save by giving some up
            o.cost_per_service_point = round(o.cost_delta / pts, 2)
        else:
            o.verdict = "better on both" if pts > 0 else "worse on both"
    ok = [o for o in outs if o.ok]
    return WhatIfResult(currency=req.base.settings.currency, scenarios=outs,
                        best_service=max(ok, key=lambda o: (o.service, -o.total_cost)).label if ok else "",
                        lowest_cost=min(ok, key=lambda o: (o.total_cost, -o.service)).label if ok else "")


class KeepRequest(Out):
    base: Dataset
    label: str = Field(min_length=1, max_length=60)
    chips: list[Chip] = Field(min_length=1)
    parent: str | None = None            # the stored version the working copy is; none: the base is stored first
    base_name: str = ""


class KeepResult(Out):
    version: VersionMeta                 # the new scenario, with the chips written into its data
    base: VersionMeta | None = None      # the base stored first, when the working copy had none
    notes: list[str] = []


def keep_scenario(req: KeepRequest, store: Store, scope: str = "") -> KeepResult:
    """A scenario that wins becomes a stored scenario of the current base: a branch of ``parent`` (or of the base
    stored now) holding the base with the chips applied, to be opened, compared and promoted like any other."""
    notes: list[str] = []
    data = apply_chips(req.base, req.chips, notes)
    saved = None
    parent = req.parent
    if parent is None:
        saved = store.save_base(req.base, req.base_name or f"Plan of {req.base.settings.planning_start.isoformat()}",
                                "stored to keep a what-if scenario", scope)
        parent = saved.id
    note = "what-if: " + " · ".join(chip_label(c) for c in req.chips)
    b = store.branch(parent, req.label, note[:500], scope or None)
    return KeepResult(version=store.update(b.id, data, scope or None), base=saved, notes=notes)
