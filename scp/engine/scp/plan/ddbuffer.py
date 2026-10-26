"""DDMRP buffer sizing over the network, shared by the inventory screen (advice) and MRP (MRP type ``ddmrp``).

A position is decoupled when it carries a buffer: ``ddmrp_buffer`` set, or planned by MRP type ``ddmrp``. Its
decoupled lead time is its own lead time plus the longest unbuffered path back to the previous buffer or a supplier;
ADU is the network demand rate over the inventory settings' ADU window and the CV that sets the variability factor is
the horizon's (:mod:`scp.inventory.ddmrp` has the formulas).
"""
from __future__ import annotations

import math
from datetime import timedelta

from ..inventory import ddmrp
from ..model import MrpType
from ..model.dataset import Dataset
from ..network import NetworkGraph, Node
from .leadtime import nominal_lead_time_days
from .rates import SQRT7, Flow, demand_flows, node_role, upstream_mix


def positioned(ds: Dataset) -> set[Node]:
    return {(lp.location, lp.product) for lp in ds.location_products
            if lp.ddmrp_buffer or lp.mrp_type is MrpType.DDMRP}


def stock_upstream(ds: Dataset, g: NetworkGraph, role: dict[Node, str]) -> dict[Node, list[Node]]:
    out: dict[Node, list[Node]] = {}
    for n in g.order:
        ups = [u for u, _ in upstream_mix(ds, g, n) if u in role and role[u] != "customer"]
        out[n] = list(dict.fromkeys(ups))
    return out


def lead_times(ds: Dataset, g: NetworkGraph) -> dict[Node, float]:
    lt: dict[Node, float] = {}
    for n in g.order:
        opts = g.options.get(n) or []
        lt[n] = (nominal_lead_time_days(ds, opts[0]) or 0.0) if opts else 0.0
    return lt


def size_all(ds: Dataset, g: NetworkGraph, horizon: Flow, *, role: dict[Node, str] | None = None,
             stock_up: dict[Node, list[Node]] | None = None, lt: dict[Node, float] | None = None,
             only: set[Node] | None = None) -> dict[Node, ddmrp.Buffer]:
    """The buffer every stocking node would carry (``only``: just these nodes)."""
    inv = ds.inventory
    start = ds.settings.planning_start
    role = role if role is not None else {n: node_role(ds, n) for n in g.order}
    stock_up = stock_up if stock_up is not None else stock_upstream(ds, g, role)
    lt = lt if lt is not None else lead_times(ds, g)
    adu = demand_flows(ds, g, start, start + timedelta(days=inv.adu_window_days))
    pos = positioned(ds)
    dlt: dict[Node, float] = {}
    for n in reversed(g.order):
        if role[n] == "customer":
            continue
        dlt[n] = lt[n] + max((dlt.get(u, 0.0) for u in stock_up[n] if u not in pos), default=0.0)
    out: dict[Node, ddmrp.Buffer] = {}
    for n in g.order:
        if role[n] != "stocking" or (only is not None and n not in only):
            continue
        lp = ds.location_product_by_key.get(n)
        mean = horizon.mean[n]
        cv = math.sqrt(horizon.var[n]) / (mean * SQRT7) if mean > 0 else 0.0
        ls = lp.lot_sizing if lp else None
        moq = (ls.fixed_qty or ls.min_qty) if ls else 0.0
        out[n] = ddmrp.size(adu.mean[n], dlt[n], cv, moq, inv)
    return out
