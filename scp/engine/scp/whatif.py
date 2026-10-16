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
* ``fx``: a foreign currency's rate × (1 + pct/100) (imported parts dearer or cheaper in the company currency);
* ``supplier_price``: purchase prices × (1 + pct/100): one supplier's, or some products', or every one; their price
  scales and the lines of the contracts they buy on too.

One chip can also be swept over several sizes (``sweep_chip``, enterprise plan 5.3), and a scenario can be a stored
version of the company read on the server; each scenario's money at risk is given by period.

A scenario that wins can be kept as a stored scenario of the current base (``keep_scenario``): its chips are written
into the data of a branch, which is then promoted like any other version.
"""
from __future__ import annotations

import datetime as dt
import math
from bisect import bisect_right
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import Field

from .model import Dataset
from .model.common import Out
from .model.master import CapacityChange, CustomerPrice, SafetyStockPolicy, Shift
from .model.common import SafetyStockMethod
from .network import Node, build_graph
from .plan import PlanResult, costing, rates, run_mrp
from .plan.leadtime import lead_time_std_days, nominal_lead_time_days
from .plan.safety import loss
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


class SupplierPriceChip(Out):
    kind: Literal["supplier_price"] = "supplier_price"
    pct: float = Field(ge=-90, le=500)
    supplier: str | None = None          # none: every supplier
    products: list[str] = []             # none: every product bought


Chip = Annotated[DemandChip | SupplierOutChip | LeadTimeChip | AddShiftChip | LaneDelayChip | MachineDownChip
                 | CustomerPriceChip | SafetyDaysChip | FxChip | SupplierPriceChip, Field(discriminator="kind")]


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
    if isinstance(c, SupplierPriceChip):
        return (f"Purchase prices {c.pct:+g} %" + (f" at {c.supplier}" if c.supplier else "")
                + (f" ({', '.join(c.products)})" if c.products else ""))
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
                # the forecast error and review period describe the demand, not the policy: they stay
                keep = {"demand_cv": lp.safety_stock.demand_cv, "review_period_days": lp.safety_stock.review_period_days}
                lp.safety_stock = (SafetyStockPolicy(method=SafetyStockMethod.DAYS_OF_SUPPLY, days=c.days, **keep)
                                   if c.days else SafetyStockPolicy(**keep))
        elif isinstance(c, FxChip):
            cur = c.currency.upper()
            if cur == d.settings.currency.upper():
                raise WhatIfError(f"{cur} is the company's own currency")
            if cur not in d.settings.fx_rates:
                raise WhatIfError(f"there is no exchange rate for {cur}: nothing is bought in it")
            d.settings.fx_rates = {**d.settings.fx_rates, cur: round(d.settings.fx_rates[cur] * (1 + c.pct / 100), 8)}
        elif isinstance(c, SupplierPriceChip):
            f = 1 + c.pct / 100
            hit = [ps for ps in d.purchasing_sources if (not c.supplier or ps.supplier == c.supplier)
                   and (not c.products or ps.product in c.products)]
            if not hit:
                raise WhatIfError(f"{chip_label(c)}: nothing is bought there")
            for ps in hit:
                ps.price = round(ps.price * f, 6)
                for sc in ps.price_scales:
                    sc.price = round(sc.price * f, 6)
            for k in d.contracts:
                if not c.supplier or k.supplier == c.supplier:
                    for ln in k.lines:
                        if not c.products or ln.product in c.products:
                            ln.price = round(ln.price * f, 6)
    try:
        return Dataset.model_validate(d.model_dump(mode="json"))
    except ValueError as e:
        raise WhatIfError(f"these changes make the data invalid: {str(e).splitlines()[-2:]}") from None


class ScenarioIn(Out):
    label: str = Field(min_length=1, max_length=60)
    chips: list[Chip] = []
    dataset: Dataset | None = None       # a whole dataset of its own instead of base + chips
    version: str | None = Field(None, min_length=1, max_length=64)   # a stored version's data (chips go on top)


class WhatIfRequest(Out):
    base: Dataset
    scenarios: list[ScenarioIn] = Field(min_length=2, max_length=4)


class Lever(Out):
    what: str                            # "Demand +20 %" or a changed list ("lanes: 2 changed")


class Period(Out):
    start: dt.date
    end: dt.date
    label: str


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
    at_risk: list[float] = []            # late units × price by the period their demand is due (the result's periods)
    expected_service: float | None = None   # the fill rate to expect against forecast error (sweeps of safety stock)
    # deltas against the baseline (None for the baseline itself)
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
    periods: list[Period] = []           # the baseline's planning periods: what ``at_risk`` is counted in
    best_service: str = ""
    lowest_cost: str = ""


def _metrics(label: str, ds: Dataset, plan: PlanResult | None = None) -> ScenarioOut:
    p = plan or run_mrp(ds)
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
    peak = k.max_utilization
    if not math.isfinite(peak):
        # work planned in a week with no capacity (a machine down): the busiest week that has hours, and say which
        dead = sorted({rp.resource for rp in p.resources for b in rp.buckets
                       if b.capacity_hours <= 0 < b.load_hours})
        peak = max((b.load_hours / b.capacity_hours for rp in p.resources for b in rp.buckets
                    if b.capacity_hours > 0), default=0.0)
        out.note = f"{', '.join(dead)}: work planned in a week with no hours (it waits or moves)"
    out.capacity_peak, out.late_units, out.late_revenue = peak, late, round(rev, 2)
    out.orders, out.errors = len(p.orders), sum(e.severity == "error" for e in p.exceptions)
    return out


def expected_service(ds: Dataset, plan: PlanResult) -> float | None:
    """The fill rate to expect against forecast error where stock meets customer demand: at each stocking place that
    ships to a customer (or has demand of its own), β = 1 − σ·G(SS/σ)/Q, with σ the spread of demand over its lead time
    and review period (the network rates' variance, as safety stock is sized), SS its planned safety stock (the
    plan's average), Q its typical lot and G the normal loss function; weighted by the customer demand each serves.
    The plan's own on-time service takes the forecast as certain, so safety stock never moves it: this does.
    None: no stocking place faces customer demand."""
    if not plan.ok:
        return None
    g = build_graph(ds)
    flow = rates.horizon_flows(ds, g)
    val = costing.roll_up(ds, g)
    ss = {(n.location, n.product): sum(b.safety_stock for b in n.buckets) / len(n.buckets)
          for n in plan.nodes if n.buckets}
    facing: dict[Node, float] = {}
    for node in g.order:
        role = rates.node_role(ds, node)
        if role == "customer":
            for up, k in rates.upstream_mix(ds, g, node):
                if rates.node_role(ds, up) == "stocking":
                    facing[up] = facing.get(up, 0.0) + k * flow.mean.get(node, 0.0)
        elif role == "stocking" and flow.direct.get(node, 0.0) > 0:
            facing[node] = facing.get(node, 0.0) + flow.direct[node]
    days = rates.bucket_days(ds, len(plan.buckets))
    num = den = 0.0
    for node, w in facing.items():
        if w <= 0:
            continue
        opts = g.options.get(node) or []
        lt = (nominal_lead_time_days(ds, opts[0]) or 0.0) if opts else 0.0
        lt_sd = lead_time_std_days(ds, opts[0]) if opts else 0.0
        lp = ds.location_product_by_key.get(node)
        review = lp.safety_stock.review_period_days if lp else 0.0
        mean = flow.mean.get(node, 0.0)
        sigma = math.sqrt(max(0.0, lt + review) * flow.var.get(node, 0.0) + (mean * lt_sd) ** 2)
        q = rates.typical_lot(ds, g, node, mean, val.unit_value.get(node, 0.0), days)
        beta = 1.0 if sigma <= 0 or q <= 0 else min(1.0, max(0.0, 1.0 - sigma * loss(ss.get(node, 0.0) / sigma) / q))
        num += w * beta
        den += w
    return round(num / den, 6) if den > 0 else None


def _periods(plan: PlanResult) -> list[Period]:
    return [Period(start=b.start, end=b.end, label=b.label) for b in plan.buckets]


def _at_risk(ds: Dataset, plan: PlanResult, periods: list[Period]) -> list[float]:
    """Money at risk over time: each late demand's late units at its selling price, in the period it is due. Demand due
    before the first period counts in the first, after the last in the last (another plan's periods may differ)."""
    if not plan.ok:
        return []                        # a blocked plan has no money at risk to show
    out = [0.0] * len(periods)
    starts = [p.start for p in periods]
    for x in plan._late:
        i = max(0, bisect_right(starts, x.date) - 1)
        out[i] += x.late * (ds.selling_price(x.location, x.product) or 0.0)
    return [round(v, 2) for v in out]


def _plan_service(o: ScenarioOut) -> float:
    return o.service


def _expected(o: ScenarioOut) -> float:
    return o.expected_service if o.expected_service is not None else o.service


def _against(o: ScenarioOut, b: ScenarioOut, svc: Callable[[ScenarioOut], float] = _plan_service) -> None:
    """``o``'s deltas against the baseline ``b``, its verdict and what one point of service (``svc``: the plan's
    on-time service, or the service expected against forecast error) costs it."""
    if not (o.ok and b.ok):
        return
    o.cost_delta = round(o.total_cost - b.total_cost, 2)
    o.service_delta = round(o.service - b.service, 6)
    o.inventory_delta = round(o.inventory_value_avg - b.inventory_value_avg, 2)
    o.late_units_delta = round(o.late_units - b.late_units, 6)
    o.sales_delta = round(o.sales_value - b.sales_value, 2)
    pts = (svc(o) - svc(b)) * 100
    if abs(pts) < 0.01:
        o.verdict = "same service"
    elif (o.cost_delta > 0) == (pts > 0) and o.cost_delta != 0:
        o.verdict = "trade-off"           # pay more for more service, or save by giving some up
        o.cost_per_service_point = round(o.cost_delta / pts, 2)
    else:
        o.verdict = "better on both" if pts > 0 else "worse on both"


VersionReader = Callable[[str], Dataset]


def compare_scenarios(req: WhatIfRequest, version: VersionReader | None = None) -> WhatIfResult:
    """Plan every scenario and compare it with the first. ``version`` reads a stored version's data by its id (the
    server's store, for the caller's company)."""
    built: list[tuple[ScenarioIn, Dataset, list[str]]] = []
    for s in req.scenarios:
        if s.dataset is not None and (s.chips or s.version):
            raise WhatIfError(f"{s.label}: give either a dataset, or a stored version and chips, not both")
        notes: list[str] = []
        if s.version is not None:
            if version is None:
                raise WhatIfError(f"{s.label}: stored versions are not read here")
            src = version(s.version)
        else:
            src = s.dataset if s.dataset is not None else req.base
        built.append((s, apply_chips(src, s.chips, notes) if s.chips else src, notes))
    labels = [s.label for s, _, _ in built]
    if len(set(labels)) != len(labels):
        raise WhatIfError("every scenario needs its own name")
    outs: list[ScenarioOut] = []
    base_ds = built[0][1]
    periods: list[Period] = []
    for i, (s, ds, notes) in enumerate(built):
        plan = run_mrp(ds)
        if not periods and plan.ok:
            periods = _periods(plan)      # the baseline's (or, if it is blocked, the first that plans)
        o = _metrics(s.label, ds, plan)
        o.at_risk = _at_risk(ds, plan, periods)
        o.levers = ([Lever(what=f"stored version {s.version}")] if s.version else []) + \
            [Lever(what=chip_label(c)) for c in s.chips]
        if notes:
            o.note = "; ".join([*notes, *([o.note] if o.note else [])])
        del plan                          # one plan in memory at a time: a large company's is gigabytes
        if (s.dataset is not None or s.version is not None) and i > 0:
            dd = diff(base_ds, ds)
            o.levers += [Lever(what=f"{c.collection}: {c.added} added, {c.removed} removed, {c.changed} changed")
                         for c in dd.collections if c.added or c.removed or c.changed]
        outs.append(o)
    for o in outs[1:]:
        _against(o, outs[0])
    ok = [o for o in outs if o.ok]
    return WhatIfResult(currency=req.base.settings.currency, scenarios=outs, periods=periods,
                        best_service=max(ok, key=lambda o: (o.service, -o.total_cost)).label if ok else "",
                        lowest_cost=min(ok, key=lambda o: (o.total_cost, -o.service)).label if ok else "")


# ---- a sweep: one chip at several sizes, cost against service ------------------------------------------------
SWEEP_FIELD: dict[str, str] = {"demand": "pct", "lead_time": "days", "lane_delay": "days", "machine_down": "days",
                               "customer_price": "pct", "safety_days": "days", "fx": "pct", "supplier_price": "pct"}
LEVERS = {"safety_days"}                 # bought for service (read as cost against service); the rest are exposures


class SweepRequest(Out):
    base: Dataset
    chip: Chip                           # the change to sweep: its number is replaced by each value in turn
    values: list[float] = Field(min_length=2, max_length=8)


class SweepPoint(ScenarioOut):
    value: float = 0.0
    step_cost_per_point: float | None = None   # from the point before: what each point of service gained costs
    frontier: bool = False               # a lever's value no other (nor today) matches in cost and service


class SweepResult(Out):
    currency: str
    kind: str
    field: str                           # "days" or "pct"
    lever: bool = False                  # bought for service (frontier and cost per point); else an exposure
    baseline: ScenarioOut                # today's data, as it is
    points: list[SweepPoint]             # by value, smallest first
    periods: list[Period] = []
    read: list[str] = []                 # what the sweep says, in sentences


def _dominated(o: ScenarioOut, others: list[ScenarioOut], svc: Callable[[ScenarioOut], float]) -> bool:
    # a hundredth of a point of service is no difference: a dearer value buying only that is not worth it
    return any(x is not o and x.ok and x.total_cost <= o.total_cost + 1e-6 and svc(x) >= svc(o) - 1e-4
               and (x.total_cost < o.total_cost - 1e-6 or svc(x) > svc(o) + 1e-4) for x in others)


def sweep_chip(req: SweepRequest, money: Callable[[float], str] | None = None) -> SweepResult:
    """Plan the base with one chip at each of ``values`` and read cost against service: each point's deltas against
    today, the cost of each step's points of service, and which points are on the frontier (none cheaper with as much
    service). The values are planned smallest first."""
    field = SWEEP_FIELD.get(req.chip.kind)
    if field is None:
        raise WhatIfError(f"{chip_label(req.chip)}: only a change with a number can be swept "
                          f"({', '.join(sorted(SWEEP_FIELD))})")
    vals = sorted({round(v, 6) for v in req.values})
    if len(vals) < 2:
        raise WhatIfError("give at least two different values to sweep")
    fmt = money or (lambda v: f"{v:,.0f} {req.base.settings.currency}")
    lever = req.chip.kind in LEVERS
    svc = _expected if lever else _plan_service
    base_plan = run_mrp(req.base)
    periods = _periods(base_plan) if base_plan.ok else []
    base = _metrics("As today", req.base, base_plan)
    base.at_risk = _at_risk(req.base, base_plan, periods)
    if lever:
        base.expected_service = expected_service(req.base, base_plan)
    del base_plan                         # one plan in memory at a time: a large company's is gigabytes
    if not base.ok:
        raise WhatIfError(f"today's plan is blocked: {base.note}")
    points: list[SweepPoint] = []
    for v in vals:
        raw = {**req.chip.model_dump(mode="json"), field: int(round(v)) if req.chip.kind == "machine_down" else v}
        try:
            chip = type(req.chip).model_validate(raw)
        except ValueError as e:
            raise WhatIfError(f"{v:g} is not a size this change can take: {str(e).splitlines()[-1].strip()}") from None
        notes: list[str] = []
        ds = apply_chips(req.base, [chip], notes)
        plan = run_mrp(ds)
        m = _metrics(chip_label(chip), ds, plan)
        pt = SweepPoint(**m.model_dump(), value=v)
        pt.levers = [Lever(what=chip_label(chip))]
        pt.at_risk = _at_risk(ds, plan, periods)
        if lever:
            pt.expected_service = expected_service(ds, plan)
        del plan, ds
        if notes:
            pt.note = "; ".join([*notes, *([pt.note] if pt.note else [])])
        _against(pt, base, svc)
        points.append(pt)
    every: list[ScenarioOut] = [base, *points]
    for i, pt in enumerate(points):
        pt.frontier = lever and pt.ok and not _dominated(pt, every, svc)
        prev = points[i - 1] if i else None
        if prev is not None and prev.ok and pt.ok:
            pts = (svc(pt) - svc(prev)) * 100
            if pts > 0.01:
                pt.step_cost_per_point = round((pt.total_cost - prev.total_cost) / pts, 2)
    return SweepResult(currency=req.base.settings.currency, kind=req.chip.kind, field=field,
                       lever=lever, baseline=base, points=points, periods=periods,
                       read=_read_sweep(req.chip.kind, base, points, fmt))


def _read_sweep(kind: str, base: ScenarioOut, points: list[SweepPoint], fmt: Callable[[float], str]) -> list[str]:
    ok = [p for p in points if p.ok]
    if not ok:
        return ["No value planned: " + (points[0].note if points else "nothing to sweep")]
    lo, hi = ok[0], ok[-1]
    if kind in LEVERS:
        # a lever bought for service, read against the service expected when demand misses its forecast
        e = _expected
        out = [f"From {lo.label} to {hi.label}: expected service {e(lo) * 100:.1f} % to {e(hi) * 100:.1f} % "
               f"(today {e(base) * 100:.1f} %), cost {fmt(lo.total_cost)} to {fmt(hi.total_cost)} "
               f"(today {fmt(base.total_cost)}). Expected service is what the stock covers when demand misses "
               "its forecast by the usual error; the plan itself takes the forecast as certain."]
        steps = [(ok[i - 1], p) for i, p in enumerate(ok) if i and p.step_cost_per_point is not None]
        if steps:
            x, y = min(steps, key=lambda s: s[1].step_cost_per_point or 0.0)
            cpp = y.step_cost_per_point or 0.0
            out.append(f"The cheapest service is from {x.label} to {y.label}: {(e(y) - e(x)) * 100:.1f} points"
                       + (f" at {fmt(cpp)} a point." if cpp > 0 else f", and it saves {fmt(-cpp)} a point."))
            dear = max(steps, key=lambda s: s[1].step_cost_per_point or 0.0)
            if dear is not (x, y) and (dear[1].step_cost_per_point or 0) > 2 * max(cpp, 1e-9):
                out.append(f"From {dear[0].label} to {dear[1].label} a point costs "
                           f"{fmt(dear[1].step_cost_per_point or 0)}: each point is dearer the higher it goes.")
        flat = next((p for i, p in enumerate(ok) if i and abs(e(p) - e(ok[i - 1])) * 100 < 0.1
                     and p.total_cost > ok[i - 1].total_cost + 0.5), None)
        if flat is not None:
            out.append(f"{flat.label} costs {fmt(flat.total_cost - ok[ok.index(flat) - 1].total_cost)} more than "
                       f"{ok[ok.index(flat) - 1].label} and buys no expected service: the money goes to stock.")
        if hi.service < lo.service - 0.001:
            out.append(f"The plan's own on-time service falls from {lo.service * 100:.1f} % to "
                       f"{hi.service * 100:.1f} %: it builds the extra stock now, in the first orders, with the demand "
                       "that falls due while they are made, so that demand waits for the larger lots. Raise it in "
                       "steps over several weeks instead.")
        off = [p.label for p in ok if not p.frontier]
        if off:
            out.append(f"Not worth it: {', '.join(off)} (another value, or today, is as cheap with as much "
                       "expected service).")
    else:
        # an exposure: how far it can go before service falls, and what it puts at risk
        out = [f"From {lo.label} to {hi.label}: service {lo.service * 100:.1f} % to {hi.service * 100:.1f} % "
               f"(today {base.service * 100:.1f} %), cost {fmt(lo.total_cost)} to {fmt(hi.total_cost)} "
               f"(today {fmt(base.total_cost)})."]
        holds = [p for p in ok if p.service >= base.service - 0.005]
        falls = [p for p in ok if p.service < base.service - 0.005]
        if not falls:
            out.append(f"Service holds within half a point of today across the sweep, up to {hi.label}.")
        else:
            worse = [p for p in falls if p.value > 0] or falls
            first = min(worse, key=lambda p: abs(p.value))
            out.append((f"Service holds within half a point of today up to {max(holds, key=lambda p: p.value).label}; "
                        if holds else "") + f"at {first.label} it is {first.service * 100:.1f} % with "
                       f"{fmt(first.late_revenue)} of sales projected late (today {fmt(base.late_revenue)}).")
    worst = max(ok, key=lambda p: p.late_revenue)
    if worst.late_revenue > 0:
        out.append(f"Most money at risk with {worst.label}: {fmt(worst.late_revenue)} of sales projected late.")
    return out


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
