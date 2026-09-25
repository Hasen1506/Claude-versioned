"""One demand rate, one typical lot and one safety stock for every module that needs them.

MRP holds safety stock, the inventory analysis reports the 'current' safety stock beside its
recommendation, and S&OP targets it: all three read it from here, so a planner sees the same number
on every screen.

**Demand rate.** A node's *direct* demand is what MRP plans there: forecast after consumption by sales
orders plus the orders themselves, by the node's planning strategy (MTS: forecast only; MTO: orders
only). It is averaged per calendar day over a window; past-due backlog is not a rate and is left out.
The rate then flows up the network in low-level-code order: a customer passes its demand to the
stocking locations that ship to it, a stocking node to its supply option (split by quota where quotas
exist), a make option passes component usage × BOM factor. Variances add (independent demand streams),
so the upstream CV falls: that is risk pooling. A node's own ``demand_cv`` (measured forecast error)
overrides the modelled value; otherwise the inventory default CV applies at the demand points.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..model import LocationProduct, LocationType, LotSizePolicy, SafetyStockMethod, Strategy
from ..model.dataset import Dataset
from ..network import NetworkGraph, Node, SupplyOption
from . import costing
from .consumption import effective_demand
from .lotsize import eoq
from .safety import SSInputs, statistical_ss

SQRT7 = math.sqrt(7.0)


@dataclass
class Flow:
    direct: dict[Node, float] = field(default_factory=dict)      # mean daily direct demand
    mean: dict[Node, float] = field(default_factory=dict)        # mean daily total demand
    var: dict[Node, float] = field(default_factory=dict)         # variance of daily demand
    cv_source: dict[Node, str] = field(default_factory=dict)


def _overlap(rec_start: date, rec_days: int, lo: date, hi: date) -> float:
    """Fraction of a record's window [start, start + days) that falls inside [lo, hi)."""
    end = rec_start + timedelta(days=rec_days)
    inside = (min(end, hi) - max(rec_start, lo)).days
    return max(0, inside) / rec_days


def _lp(ds: Dataset, node: Node) -> LocationProduct:
    return ds.location_product_by_key.get(node) or LocationProduct(location=node[0], product=node[1])


def direct_rates(ds: Dataset, lo: date, hi: date) -> dict[Node, float]:
    """Mean daily independent demand per node in [lo, hi), after forecast consumption."""
    recs: dict[Node, list] = defaultdict(list)
    for i, d in enumerate(ds.demand):
        recs[(d.location, d.product)].append((d.id or f"#{i}", d))
    span = max(1, (hi - lo).days)
    out: dict[Node, float] = {}
    for node, rs in recs.items():
        lp = _lp(ds, node)
        period = {rid: (r.period_days or 1) for rid, r in rs}
        total = 0.0
        for r in effective_demand(rs, lp.strategy, lp.consumption_backward_days, lp.consumption_forward_days):
            days = period[r.source_ref] if r.kind == "forecast" else 1
            total += r.qty * _overlap(r.date, days, lo, hi)
        out[node] = total / span
    return out


def upstream_mix(ds: Dataset, g: NetworkGraph, node: Node) -> list[tuple[Node, float]]:
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


def demand_flows(ds: Dataset, g: NetworkGraph, lo: date, hi: date) -> Flow:
    f = Flow(direct=direct_rates(ds, lo, hi))
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
        for up, k in upstream_mix(ds, g, node):
            inflow_mean[up] += k * mean
            inflow_var[up] += (k * k) * var
    return f


def horizon_flows(ds: Dataset, g: NetworkGraph) -> Flow:
    s = ds.settings
    return demand_flows(ds, g, s.planning_start, s.planning_start + timedelta(days=s.horizon_days))


def node_role(ds: Dataset, node: Node) -> str:
    if ds.location_type(node[0]) is LocationType.CUSTOMER:
        return "customer"
    lp = ds.location_product_by_key.get(node)
    if lp and lp.strategy is Strategy.MTO:
        return "no_stock"
    return "stocking"


def ordering_cost(ds: Dataset, lp: LocationProduct, opts: list[SupplyOption]) -> float:
    """The EOQ's fixed cost per order: the lot-sizing entry, else the purchase order or set-up cost."""
    if lp.lot_sizing.ordering_cost > 0 or not opts:
        return lp.lot_sizing.ordering_cost
    o = opts[0]
    if o.kind == "buy":
        return ds.purchasing_source_by_id[o.source_id].ordering_cost
    if o.kind == "make":
        return costing.setup_cost(ds, o.source_id)
    return 0.0


def holding_rate(ds: Dataset, lp: LocationProduct | None) -> float:
    return lp.holding_rate if lp and lp.holding_rate is not None else ds.settings.carrying_rate


def eoq_qty(ds: Dataset, g: NetworkGraph, node: Node, mean_daily: float, unit_value: float) -> float | None:
    lp = _lp(ds, node)
    return eoq(mean_daily * 365.0, ordering_cost(ds, lp, g.options.get(node) or []), unit_value, holding_rate(ds, lp))


def bucket_days(ds: Dataset, buckets: int) -> float:
    return ds.settings.horizon_days / max(1, buckets)


def typical_lot(ds: Dataset, g: NetworkGraph, node: Node, mean_daily: float, unit_value: float,
                days_per_bucket: float) -> float:
    """The order quantity a fill-rate policy is measured against: what the lot-sizing rule orders."""
    ls = _lp(ds, node).lot_sizing
    if ls.policy is LotSizePolicy.FIXED and ls.fixed_qty:
        return ls.fixed_qty
    if ls.policy is LotSizePolicy.EOQ:
        q = eoq_qty(ds, g, node, mean_daily, unit_value)
        if q:
            return q
    if ls.policy is LotSizePolicy.POQ and ls.periods:
        return mean_daily * days_per_bucket * ls.periods
    return max(mean_daily * days_per_bucket, ls.min_qty)


@dataclass
class PolicySS:
    method: str
    qty: float
    note: str


def policy_safety_stock(ds: Dataset, g: NetworkGraph, node: Node, *, mean_daily: float, lead_time: float,
                        lead_time_std: float, unit_value: float, days_per_bucket: float) -> PolicySS:
    """The safety stock a node's configured policy holds (days of supply as its average: mean × days)."""
    lp = ds.location_product_by_key.get(node)
    if lp is None or node_role(ds, node) != "stocking":
        return PolicySS("none", 0.0, "none")
    pol = lp.safety_stock
    m = pol.method
    if m is SafetyStockMethod.NONE:
        return PolicySS("none", 0.0, "none")
    if m is SafetyStockMethod.FIXED:
        return PolicySS("fixed", pol.qty or 0.0, f"fixed {pol.qty:g}")
    if m is SafetyStockMethod.DAYS_OF_SUPPLY:
        days = pol.days or 0.0
        return PolicySS("days_of_supply", mean_daily * days, f"coverage: requirements in the next {days:g} days")
    sl = pol.service_level or ds.settings.default_service_level
    q = typical_lot(ds, g, node, mean_daily, unit_value, days_per_bucket)
    res = statistical_ss(pol, SSInputs(mean_daily, lead_time, lead_time_std, sl, q))
    return PolicySS(m.value, res.qty, res.explanation)


__all__ = ["Flow", "PolicySS", "bucket_days", "demand_flows", "direct_rates", "eoq_qty", "holding_rate",
           "horizon_flows", "node_role", "ordering_cost", "policy_safety_stock", "typical_lot", "upstream_mix"]
