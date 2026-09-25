"""Inventory optimisation over the planning network (blueprint §5, phase P3).

1. **Demand at every node.** The network demand rate MRP and S&OP also use (:mod:`scp.plan.rates`):
   forecast after consumption plus sales orders, averaged per day over the horizon and flowed up the
   network; variances add, so the upstream CV falls (risk pooling). A node's own ``demand_cv``
   overrides the modelled value; otherwise the inventory default CV applies at the demand points.
2. **Single-echelon baseline.** Every stage buffers its own replenishment lead time:
   SS = z · √((L + R)·σ_d² + d̄²·σ_L²).
3. **Multi-echelon placement.** The guaranteed-service model (:mod:`.gsm`) chooses the service
   times; recommended SS = z · √((τ + R)·σ_d² + d̄²·σ_L²) where the stage holds stock (τ > 0).
   A fill-rate target is sized the way MRP sizes it (the loss function against the node's typical
   lot) at every candidate τ, so the placement is priced on the stock the node would really hold.
   Service times are whole days, so a fractional lead time is rounded up in the model; a stage's
   stock covers τ less that rounding, so buffering every stage costs exactly the single-echelon baseline.
4. **DDMRP.** Buffer zones and the net-flow position for every stocking node (:mod:`.ddmrp`).
5. **Pooling.** For each product, the stock needed at the demand-facing locations separately
   versus one pooled position (the square-root law).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import NormalDist

from ..model import DemandKind, SafetyStockMethod
from ..model.dataset import Dataset
from ..network import NetworkGraph, Node, build_graph
from ..plan import costing
from ..plan.leadtime import lead_time_std_days, nominal_lead_time_days
from ..plan.rates import (
    SQRT7, Flow, bucket_days, demand_flows, node_role, policy_safety_stock, typical_lot, upstream_mix,
)
from ..plan.safety import buffer as size_buffer
from ..time import Buckets
from ..validate import has_errors, validate
from . import ddmrp, gsm
from .result import (
    DdmrpRow, InventoryResult, NodeInventory, NodeRef, PoolingRow, SolverInfo, Totals,
)

_N = NormalDist()


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
    flow = demand_flows(ds, g, start, start + timedelta(days=s.horizon_days))
    inv = ds.inventory
    per_bucket = bucket_days(ds, len(Buckets(s)))

    # ---- per-node inputs ---------------------------------------------------------------
    role = {n: node_role(ds, n) for n in g.order}
    lt: dict[Node, float] = {}
    lt_sd: dict[Node, float] = {}
    for n in g.order:
        opts = g.options.get(n) or []
        lt[n] = (nominal_lead_time_days(ds, opts[0]) or 0.0) if opts else 0.0
        lt_sd[n] = lead_time_std_days(ds, opts[0]) if opts else 0.0
    stock_up: dict[Node, list[Node]] = {}
    for n in g.order:
        ups = [u for u, _ in upstream_mix(ds, g, n) if u in role and role[u] != "customer"]
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

    def review(n: Node) -> float:
        lp = ds.location_product_by_key.get(n)
        return lp.safety_stock.review_period_days if lp else 0.0

    # a fill-rate target is measured against the lot the node orders (as in MRP); None: a z target
    lot: dict[Node, float | None] = {}
    for n in g.order:
        lp = ds.location_product_by_key.get(n)
        fr = lp is not None and lp.safety_stock.method is SafetyStockMethod.FILL_RATE
        lot[n] = typical_lot(ds, g, n, flow.mean[n], val.unit_value.get(n, 0.0), per_bucket) if fr else None

    def buffer(n: Node, days: float, lt_std: float) -> float:
        """The stock n's service target needs to cover ``days`` of demand plus lead-time variability."""
        sigma = math.sqrt(max(0.0, days) * flow.var[n] + (flow.mean[n] * lt_std) ** 2)
        return size_buffer(lot[n] is not None, service_level(n), sigma, lot[n] or 0.0)

    def whole_days(n: Node) -> int:
        return int(math.ceil(lt[n] - 1e-9))

    def exposure(n: Node, tau: int) -> float:
        """Days of demand a stage covers at net time τ (whole days): τ less the rounding up of its lead time."""
        return max(0.0, tau - max(0.0, whole_days(n) - lt[n]))

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
        h = val.unit_value.get(n, 0.0) * rate(n)
        cost = h * max(_N.inv_cdf(service_level(n)), 0.0) * math.sqrt(flow.var[n])
        # demand variability over τ, plus the review period once the stage holds stock; σ_L is added after.
        # The model counts whole days, so a lead time is rounded up; the stage is charged for the demand it
        # really covers, τ less that rounding, so buffering at every stage costs what single-echelon does
        curve = lambda t, n=n, h=h: h * buffer(n, exposure(n, t) + review(n), 0.0) if t > 0 else 0.0  # noqa: E731
        stages.append(gsm.Stage(n, whole_days(n), cost, stock_up[n], max_service[n],
                                no_stock=role[n] == "no_stock", cost_at=curve))
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
        uv = val.unit_value.get(n, 0.0)
        r = rate(n)
        own = math.sqrt((lt[n] + review(n)) * var + (mean * lt_sd[n]) ** 2)
        pol = policy_safety_stock(ds, g, n, mean_daily=mean, lead_time=lt[n], lead_time_std=lt_sd[n],
                                  unit_value=uv, days_per_bucket=per_bucket)
        method, cur = pol.method, pol.qty
        single = buffer(n, lt[n] + review(n), lt_sd[n]) if role[n] == "stocking" else 0.0
        # z for a service level; for a fill rate, the k it takes over the node's own lead time
        z = _N.inv_cdf(sl) if lot[n] is None else (single / own if own > 0 else 0.0)
        si = sol.inbound.get(n, 0)
        so = sol.service.get(n, 0)
        tau = sol.net.get(n, 0)
        meio = buffer(n, exposure(n, tau) + review(n), lt_sd[n]) if role[n] == "stocking" and tau > 0 else 0.0
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
        f"Demand is averaged over the {s.horizon_days}-day horizon: forecast after consumption by sales orders, "
        "plus the orders. Variability flows upstream as independent streams (variances add).",
        "A fill-rate target is sized with the normal loss function against the node's typical lot, at every "
        "net replenishment time the placement considers; z shows the equivalent factor over its own lead time.",
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
           lt: dict[Node, float], horizon: Flow, unit_value: dict[Node, float]) -> list[DdmrpRow]:
    inv = ds.inventory
    start = ds.settings.planning_start
    adu_flow = demand_flows(ds, g, start, start + timedelta(days=inv.adu_window_days))
    positioned = {n for n in g.order if (lp := ds.location_product_by_key.get(n)) and lp.ddmrp_buffer}
    dlt: dict[Node, float] = {}
    for n in reversed(g.order):
        if role[n] == "customer":
            continue
        dlt[n] = lt[n] + max((dlt.get(u, 0.0) for u in stock_up[n] if u not in positioned), default=0.0)
    # Sales orders by the stocking node that ships them: its own, and those of the customers it serves,
    # dated when they must leave (due date − the customer lane's transit), split by quota where quotas exist.
    orders: dict[Node, list[tuple[date, float]]] = defaultdict(list)
    for d in ds.demand:
        if d.kind is DemandKind.FORECAST:
            continue
        node = (d.location, d.product)
        if role.get(node) != "customer":
            orders[node].append((d.date, d.qty))
            continue
        ship = d.date - timedelta(days=math.ceil(lt.get(node, 0.0) - 1e-9))
        for up, k in upstream_mix(ds, g, node):
            orders[up].append((ship, d.qty * k))
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
        for ship, qty in orders.get(n, ()):
            if ship <= start or (ship < spike_end and qty > inv.spike_factor * b.tor):
                qualified += qty
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


__all__ = ["demand_flows", "node_role", "run_inventory", "upstream_mix"]
