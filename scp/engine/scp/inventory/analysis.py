"""Inventory optimisation over the planning network (blueprint §5, phase P3).

1. **Demand at every node.** Direct demand (forecast or orders, whichever is larger per node) is
   averaged per calendar day over the horizon, then flowed up the network in low-level-code order:
   a customer passes its demand to the stocking locations that ship to it, a stocking node passes
   its demand to its supply option (split by quota where quotas exist), and a make option passes
   component usage × BOM factor. Variances add (independent demand streams), so the upstream CV
   falls: that is risk pooling. A node's own ``demand_cv`` (measured forecast error) overrides the
   modelled value; otherwise the inventory default CV applies at the demand points.
2. **Single-echelon baseline.** Every stage buffers its own replenishment lead time:
   SS = z · √((L + R)·σ_d² + d̄²·σ_L²).
3. **Multi-echelon placement.** The guaranteed-service model (:mod:`.gsm`) chooses the service
   times; recommended SS = z · √(τ·σ_d² + d̄²·σ_L²) where the stage holds stock (τ > 0).
4. **DDMRP.** Buffer zones and the net-flow position for every stocking node (:mod:`.ddmrp`).
5. **Pooling.** For each product, the stock needed at the demand-facing locations separately
   versus one pooled position (the square-root law).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import NormalDist

from ..model import DemandKind, LocationType, SafetyStockMethod, Strategy
from ..model.dataset import Dataset
from ..network import NetworkGraph, Node, SupplyOption, build_graph
from ..plan import costing
from ..plan.leadtime import lead_time_std_days, nominal_lead_time_days
from ..plan.safety import SSInputs, statistical_ss
from ..validate import has_errors, validate
from . import ddmrp, gsm
from .result import (
    DdmrpRow, InventoryResult, NodeInventory, NodeRef, PoolingRow, SolverInfo, Totals,
)

_N = NormalDist()
SQRT7 = math.sqrt(7.0)


@dataclass
class _Flow:
    direct: dict[Node, float] = field(default_factory=dict)      # mean daily direct demand
    mean: dict[Node, float] = field(default_factory=dict)        # mean daily total demand
    var: dict[Node, float] = field(default_factory=dict)         # variance of daily demand
    cv_source: dict[Node, str] = field(default_factory=dict)


def _overlap(rec_start: date, rec_days: int, lo: date, hi: date) -> float:
    """Fraction of a record's window [start, start + days) that falls inside [lo, hi)."""
    end = rec_start + timedelta(days=rec_days)
    inside = (min(end, hi) - max(rec_start, lo)).days
    return max(0, inside) / rec_days


def _direct(ds: Dataset, lo: date, hi: date) -> dict[Node, float]:
    fc: dict[Node, float] = defaultdict(float)
    so: dict[Node, float] = defaultdict(float)
    for d in ds.demand:
        days = d.period_days or 1
        share = _overlap(d.date, days, lo, hi)
        if share <= 0:
            continue
        (fc if d.kind is DemandKind.FORECAST else so)[(d.location, d.product)] += d.qty * share
    span = max(1, (hi - lo).days)
    return {n: max(fc.get(n, 0.0), so.get(n, 0.0)) / span for n in set(fc) | set(so)}


def _upward(ds: Dataset, g: NetworkGraph, node: Node) -> list[tuple[Node, float]]:
    """(upstream node, units per unit of this node's demand) for the planned sourcing mix."""
    opts: list[SupplyOption] = g.options.get(node) or []
    if not opts:
        return []
    quota = [o for o in opts if o.quota]
    mix = [(o, o.quota / sum(q.quota for q in quota)) for o in quota] if quota else [(opts[0], 1.0)]
    out: list[tuple[Node, float]] = []
    for o, w in mix:
        if o.kind == "buy":
            continue  # suppliers are outside the planned network
        if o.kind == "transfer":
            out.append((o.upstream[0], w))
        else:
            for up in o.upstream:
                out.append((up, w * costing.component_factor(ds, o.source_id, up[1])))
    return out


def _flows(ds: Dataset, g: NetworkGraph, lo: date, hi: date) -> _Flow:
    f = _Flow(direct=_direct(ds, lo, hi))
    default_cv = ds.inventory.default_demand_cv
    inflow_mean: dict[Node, float] = defaultdict(float)
    inflow_var: dict[Node, float] = defaultdict(float)
    for node in g.order:  # ascending LLC: all consumers of a node come before it
        lp = ds.location_product_by_key.get(node)
        cv = lp.safety_stock.demand_cv if lp else None
        mu_d = f.direct.get(node, 0.0)
        mean = mu_d + inflow_mean[node]
        if cv is not None:
            var, src = (cv * mean * SQRT7) ** 2, "policy"
        else:
            var = (default_cv * mu_d * SQRT7) ** 2 + inflow_var[node]
            src = "pooled" if inflow_var[node] > 0 else ("default" if mu_d > 0 else "none")
        f.mean[node], f.var[node], f.cv_source[node] = mean, var, src
        for up, k in _upward(ds, g, node):
            inflow_mean[up] += k * mean
            inflow_var[up] += (k * k) * var
    return f


def _role(ds: Dataset, node: Node) -> str:
    if ds.location_type(node[0]) is LocationType.CUSTOMER:
        return "customer"
    lp = ds.location_product_by_key.get(node)
    if lp and lp.strategy is Strategy.MTO:
        return "no_stock"
    return "stocking"


def _current_ss(ds: Dataset, node: Node, role: str, mean: float, lt: float, lt_sd: float) -> tuple[str, float]:
    lp = ds.location_product_by_key.get(node)
    if lp is None or role != "stocking":
        return ("none", 0.0)
    pol = lp.safety_stock
    m = pol.method
    if m is SafetyStockMethod.NONE:
        return ("none", 0.0)
    if m is SafetyStockMethod.FIXED:
        return ("fixed", pol.qty or 0.0)
    if m is SafetyStockMethod.DAYS_OF_SUPPLY:
        return ("days_of_supply", mean * (pol.days or 0.0))
    sl = pol.service_level or ds.settings.default_service_level
    ls = lp.lot_sizing
    q = ls.fixed_qty or max(ls.min_qty, mean * 7.0)
    return (m.value, statistical_ss(pol, SSInputs(mean, lt, lt_sd, sl, q)).qty)


def _ref(n: Node) -> NodeRef:
    return NodeRef(location=n[0], product=n[1])


def run_inventory(ds: Dataset, *, time_limit: float = 30.0) -> InventoryResult:
    s = ds.settings
    base = InventoryResult(ok=False, currency=s.currency, carrying_rate=s.carrying_rate,
                           planning_start=s.planning_start, horizon_days=s.horizon_days)
    issues = validate(ds)
    base.issues = issues
    if has_errors(issues):
        return base
    g = build_graph(ds)
    val = costing.roll_up(ds, g)
    start = s.planning_start
    flow = _flows(ds, g, start, start + timedelta(days=s.horizon_days))
    inv = ds.inventory

    # ---- per-node inputs ---------------------------------------------------------------
    role = {n: _role(ds, n) for n in g.order}
    lt: dict[Node, float] = {}
    lt_sd: dict[Node, float] = {}
    for n in g.order:
        opts = g.options.get(n) or []
        lt[n] = (nominal_lead_time_days(ds, opts[0]) or 0.0) if opts else 0.0
        lt_sd[n] = lead_time_std_days(ds, opts[0]) if opts else 0.0
    stock_up: dict[Node, list[Node]] = {}
    for n in g.order:
        ups = [u for u, _ in _upward(ds, g, n) if u in role and role[u] != "customer"]
        stock_up[n] = list(dict.fromkeys(ups))
    feeds_customer: set[Node] = set()
    for n in g.order:
        if role[n] == "customer":
            feeds_customer.update(stock_up[n])
    demand_facing = {n for n in g.order if role[n] != "customer"
                     and (flow.direct.get(n, 0.0) > 0 or n in feeds_customer)}

    def service_level(n: Node) -> float:
        lp = ds.location_product_by_key.get(n)
        return (lp.safety_stock.service_level if lp and lp.safety_stock.service_level else None) \
            or s.default_service_level

    def rate(n: Node) -> float:
        lp = ds.location_product_by_key.get(n)
        return lp.holding_rate if lp and lp.holding_rate is not None else s.carrying_rate

    # ---- guaranteed-service placement --------------------------------------------------
    stages: list[gsm.Stage] = []
    max_service: dict[Node, int | None] = {}
    for n in g.order:
        if role[n] == "customer":
            continue
        lp = ds.location_product_by_key.get(n)
        bound: float | None = lp.max_service_days if lp else None
        if n in demand_facing:
            bound = inv.customer_service_days if bound is None else min(bound, inv.customer_service_days)
        max_service[n] = None if bound is None else int(math.floor(bound + 1e-9))
        z = _N.inv_cdf(service_level(n))
        sd = math.sqrt(flow.var[n])
        cost = val.unit_value.get(n, 0.0) * rate(n) * max(z, 0.0) * sd
        stages.append(gsm.Stage(n, int(math.ceil(lt[n] - 1e-9)), cost, stock_up[n], max_service[n],
                                no_stock=role[n] == "no_stock"))
    sol = gsm.solve(stages, time_limit=time_limit)
    cum_real: dict[Node, float] = {}
    for n in reversed(g.order):  # suppliers first (descending LLC)
        if role[n] == "customer":
            continue
        cum_real[n] = lt[n] + max((cum_real.get(u, 0.0) for u in stock_up[n]), default=0.0)

    # ---- node table --------------------------------------------------------------------
    nodes: list[NodeInventory] = []
    for n in g.order:
        mean, var = flow.mean[n], flow.var[n]
        sd = math.sqrt(var)
        sl = service_level(n)
        z = _N.inv_cdf(sl)
        uv = val.unit_value.get(n, 0.0)
        r = rate(n)
        lp = ds.location_product_by_key.get(n)
        review = lp.safety_stock.review_period_days if lp else 0.0
        method, cur = _current_ss(ds, n, role[n], mean, lt[n], lt_sd[n])
        if role[n] == "stocking":
            single = max(0.0, z) * math.sqrt((lt[n] + review) * var + (mean * lt_sd[n]) ** 2)
        else:
            single = 0.0
        si = sol.inbound.get(n, 0)
        so = sol.service.get(n, 0)
        tau = sol.net.get(n, 0)
        meio = max(0.0, z) * math.sqrt(tau * var + (mean * lt_sd[n]) ** 2) if role[n] == "stocking" and tau > 0 else 0.0
        decision = ("customer" if role[n] == "customer" else "no_stock" if role[n] == "no_stock"
                    else "buffer" if tau > 0 else "pass_through")
        nodes.append(NodeInventory(
            location=n[0], product=n[1], role=role[n], demand_facing=n in demand_facing,
            upstream=[_ref(u) for u in stock_up[n]],
            direct_mean_daily=flow.direct.get(n, 0.0), mean_daily=mean, sd_daily=sd,
            cv_weekly=(sd / (mean * SQRT7)) if mean > 0 else 0.0, cv_source=flow.cv_source[n],
            lead_time_days=lt[n], lead_time_std_days=lt_sd[n], cumulative_lead_time_days=cum_real.get(n, 0.0),
            unit_value=uv, holding_rate=r, service_level=sl, z=z,
            current_method=method, current_ss=cur, current_cost=cur * uv * r,
            single_ss=single, single_cost=single * uv * r,
            max_service_days=max_service.get(n), meio_inbound_days=si, meio_service_days=so, meio_net_days=tau,
            meio_ss=meio, meio_cost=meio * uv * r, decision=decision))

    ddmrp_rows = _ddmrp(ds, g, role, stock_up, lt, flow, val.unit_value)
    pooling = _pooling(ds, nodes, demand_facing, s.default_service_level)

    stocking = [x for x in nodes if x.role == "stocking"]
    tot = Totals(
        stocking_nodes=len(stocking),
        buffers_placed=sum(1 for x in stocking if x.meio_net_days > 0),
        ddmrp_positions=sum(1 for d in ddmrp_rows if d.positioned),
        current_ss_value=sum(x.current_ss * x.unit_value for x in stocking),
        single_ss_value=sum(x.single_ss * x.unit_value for x in stocking),
        meio_ss_value=sum(x.meio_ss * x.unit_value for x in stocking),
        current_cost=sum(x.current_cost for x in stocking),
        single_cost=sum(x.single_cost for x in stocking),
        meio_cost=sum(x.meio_cost for x in stocking),
        saving_vs_single=0.0, saving_vs_current=0.0)
    tot.saving_vs_single = tot.single_cost - tot.meio_cost
    tot.saving_vs_current = tot.current_cost - tot.meio_cost
    notes = [
        f"Demand is averaged over the {s.horizon_days}-day horizon; the larger of forecast and sales orders "
        "counts per node. Variability flows upstream as independent streams (variances add).",
        f"Nodes without a measured demand_cv use the default weekly CV {inv.default_demand_cv:g} at the demand point.",
        f"Customers are promised {inv.customer_service_days:g} day(s) service: demand-facing stages must quote "
        "at most that (a location-product's max_service_days can tighten it).",
        "The guaranteed-service model optimises on demand variability over whole-day lead times; lead-time "
        "variability (σ_L) is then added to the recommended stock of every stage that holds a buffer.",
        "Holding cost = unit value × carrying rate per year; unit values come from the cost roll-up.",
    ]
    if sol.status not in ("optimal", "empty"):
        notes.append(f"Placement solver: {sol.status} — {sol.message}")
    return InventoryResult(
        ok=sol.status in ("optimal", "empty", "time_limit"), currency=s.currency, carrying_rate=s.carrying_rate,
        planning_start=start, horizon_days=s.horizon_days, nodes=nodes, ddmrp=ddmrp_rows, pooling=pooling,
        totals=tot, solver=SolverInfo(status=sol.status, objective=sol.objective if math.isfinite(sol.objective) else 0.0,
                                      variables=sol.variables, constraints=sol.constraints,
                                      seconds=sol.seconds, message=sol.message),
        notes=notes, issues=issues)


def _ddmrp(ds: Dataset, g: NetworkGraph, role: dict[Node, str], stock_up: dict[Node, list[Node]],
           lt: dict[Node, float], horizon: _Flow, unit_value: dict[Node, float]) -> list[DdmrpRow]:
    inv = ds.inventory
    start = ds.settings.planning_start
    adu_flow = _flows(ds, g, start, start + timedelta(days=inv.adu_window_days))
    positioned = {n for n in g.order if (lp := ds.location_product_by_key.get(n)) and lp.ddmrp_buffer}
    dlt: dict[Node, float] = {}
    for n in reversed(g.order):
        if role[n] == "customer":
            continue
        dlt[n] = lt[n] + max((dlt.get(u, 0.0) for u in stock_up[n] if u not in positioned), default=0.0)
    open_supply: dict[Node, float] = defaultdict(float)
    for r in ds.receipts:
        open_supply[(r.location, r.product)] += r.qty
    rows: list[DdmrpRow] = []
    for n in g.order:
        if role[n] != "stocking":
            continue
        lp = ds.location_product_by_key.get(n)
        mean = horizon.mean[n]
        cv = math.sqrt(horizon.var[n]) / (mean * SQRT7) if mean > 0 else 0.0
        ls = lp.lot_sizing if lp else None
        moq = (ls.fixed_qty or ls.min_qty) if ls else 0.0
        b = ddmrp.size(adu_flow.mean[n], dlt[n], cv, moq, inv)
        spike_end = start + timedelta(days=max(1, math.ceil(dlt[n])))
        qualified = 0.0
        for d in ds.demand:
            if (d.location, d.product) != n or d.kind is DemandKind.FORECAST:
                continue
            if d.date <= start or (d.date < spike_end and d.qty > inv.spike_factor * b.tor):
                qualified += d.qty
        on_hand = lp.on_hand if lp else 0.0
        nfp = on_hand + open_supply[n] - qualified
        uv = unit_value.get(n, 0.0)
        avg = b.red + b.green / 2
        rows.append(DdmrpRow(
            location=n[0], product=n[1], positioned=n in positioned, adu=b.adu, dlt=b.dlt, ltf=b.ltf,
            lt_band=b.lt_band, vf=b.vf, var_band=b.var_band, red_base=b.red_base, red_safety=b.red_safety,
            red=b.red, yellow=b.yellow, green=b.green, tor=b.tor, toy=b.toy, tog=b.tog, on_hand=on_hand,
            open_supply=open_supply[n], qualified_demand=qualified, nfp=nfp, zone=ddmrp.zone(nfp, b),
            priority=(nfp / b.tog) if b.tog > 0 else 0.0, order_qty=ddmrp.order_qty(nfp, b), unit_value=uv,
            average_on_hand=avg, average_value=avg * uv))
    rows.sort(key=lambda r: (not r.positioned, r.priority, r.location, r.product))
    return rows


def _pooling(ds: Dataset, nodes: list[NodeInventory], facing: set[Node], service: float) -> list[PoolingRow]:
    z = max(0.0, _N.inv_cdf(service))
    by_product: dict[str, list[NodeInventory]] = defaultdict(list)
    for x in nodes:
        if x.role == "stocking" and (x.location, x.product) in facing and x.mean_daily > 0:
            by_product[x.product].append(x)
    rows: list[PoolingRow] = []
    for prod, xs in sorted(by_product.items()):
        if len(xs) < 2:
            continue
        total = sum(x.mean_daily for x in xs)
        lbar = sum(x.lead_time_days * x.mean_daily for x in xs) / total
        sep = sum(z * x.sd_daily * math.sqrt(x.lead_time_days) for x in xs)
        pooled = z * math.sqrt(sum(x.sd_daily ** 2 for x in xs)) * math.sqrt(lbar)
        uv = sum(x.unit_value * x.mean_daily for x in xs) / total
        rows.append(PoolingRow(
            product=prod, locations=[x.location for x in xs], lead_time_days=lbar, separate_ss=sep,
            pooled_ss=pooled, saving_qty=sep - pooled, saving_value=(sep - pooled) * uv,
            saving_pct=(1 - pooled / sep) if sep > 0 else 0.0, unit_value=uv))
    rows.sort(key=lambda r: -r.saving_value)
    return rows


__all__ = ["run_inventory"]
