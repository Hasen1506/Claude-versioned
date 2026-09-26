"""Unit values and order costs, all in company currency.

Landed cost (per base unit) of a purchase =
    price × fx × (1 + duty_rate) + freight per unit on the supplier lane + inbound handling.
It is the *unit value* for inventory valuation and holding cost. It is NOT the ordering cost:
the ordering cost is the fixed cost per order (``ordering_cost`` fields) used for lot sizing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..model import Dataset, LaneMode, TransportLane
from ..network import NetworkGraph, Node, SupplyOption
from .leadtime import supplier_lane
from .structure import entering, main_share, needs, typical_lot, unit_need


def fx(ds: Dataset, currency: str | None) -> float:
    if not currency or currency == ds.settings.currency:
        return 1.0
    return ds.settings.fx_rates.get(currency, 1.0)


def freight_per_unit(ds: Dataset, mode: LaneMode, product: str) -> float:
    p = ds.product_by_id.get(product)
    kg = (p.weight_kg or 0.0) if p else 0.0
    m3 = (p.volume_m3 or 0.0) if p else 0.0
    return mode.cost_per_unit + kg * mode.cost_per_kg + m3 * mode.cost_per_m3


def shipments_needed(ds: Dataset, mode: LaneMode, product: str, qty: float) -> int:
    """Vehicles needed for one order (≥ 1)."""
    p = ds.product_by_id.get(product)
    n = 1.0
    if p and mode.vehicle_capacity_kg and p.weight_kg:
        n = max(n, qty * p.weight_kg / mode.vehicle_capacity_kg)
    if p and mode.vehicle_capacity_m3 and p.volume_m3:
        n = max(n, qty * p.volume_m3 / mode.vehicle_capacity_m3)
    return max(1, math.ceil(n - 1e-9))


def handling(ds: Dataset, loc: str) -> float:
    lo = ds.location_by_id.get(loc)
    return lo.handling_cost_per_unit if lo else 0.0


def landed_unit_cost(ds: Dataset, src_id: str) -> float:
    pu = ds.purchasing_source_by_id[src_id]
    lane = supplier_lane(ds, pu.supplier, pu.location, pu.product)
    fr = freight_per_unit(ds, lane.planning_mode, pu.product) if lane else 0.0
    return pu.price * fx(ds, pu.currency) * (1.0 + pu.duty_rate) + fr + handling(ds, pu.location)


def conversion_unit_cost(ds: Dataset, src_id: str) -> float:
    """Variable make cost per good unit excluding materials: resource run cost, outside processing and
    conversion, each step for the units entering it (step scrap makes earlier steps handle more)."""
    ps = ds.production_source_by_id[src_id]
    enter = entering(ps)
    total = 0.0
    for op in ps.operations:
        per_unit = 0.0
        if op.subcontract is not None:
            per_unit += op.subcontract.cost_per_unit
        r = ds.resource_by_id.get(op.resource) if op.resource else None
        per_unit += op.run_hours_per_unit * (r.cost_per_hour if r else 0.0)
        if op.labor_resource:
            lr = ds.resource_by_id.get(op.labor_resource)
            per_unit += op.labor_hours_per_unit * (lr.cost_per_hour if lr else 0.0)
        total += enter[op.seq] * per_unit
    return total + ps.conversion_cost_per_unit


def setup_cost(ds: Dataset, src_id: str) -> float:
    ps = ds.production_source_by_id[src_id]
    total = 0.0
    for op in ps.operations:
        r = ds.resource_by_id.get(op.resource) if op.resource else None
        total += op.setup_hours * (r.cost_per_hour if r else 0.0)
    return total


def component_factor(ds: Dataset, src_id: str, component: str) -> float:
    """Issued component quantity per good unit of output (phantoms passed through; a fixed-quantity part
    spread over a typical lot)."""
    return unit_need(ds, ds.production_source_by_id[src_id], component)


@dataclass
class Valuation:
    unit_value: dict[Node, float]
    basis: dict[Node, str]


def roll_up(ds: Dataset, g: NetworkGraph) -> Valuation:
    """Unit value per node: override → standard cost → primary source roll-up (upstream first)."""
    value: dict[Node, float] = {}
    basis: dict[Node, str] = {}
    for node in sorted(g.order, key=lambda n: -g.llc[n]):
        loc, prod = node
        lp = ds.location_product_by_key.get(node)
        p = ds.product_by_id.get(prod)
        if lp and lp.unit_cost is not None:
            value[node], basis[node] = lp.unit_cost, "location-product unit_cost"
            continue
        if p and p.standard_cost is not None:
            value[node], basis[node] = p.standard_cost, "product standard_cost"
            continue
        opts = g.options.get(node) or []
        if not opts:
            value[node], basis[node] = 0.0, "no source: unvalued"
            continue
        value[node], basis[node] = option_unit_cost(ds, opts[0], value), f"roll-up via {opts[0].kind} {opts[0].source_id}"
        if opts[0].kind == "make":
            # co- and by-products of the run are valued at their share of its cost, unless valued otherwise
            ps = ds.production_source_by_id[opts[0].source_id]
            run = _run_cost(ds, ps, value)
            for co in ps.co_products:
                cn = (loc, co.product)
                if cn in g.llc and basis.get(cn, "").startswith("no source"):
                    per = co.qty / ps.output_qty
                    value[cn] = run * co.cost_share / per if per > 0 else 0.0
                    basis[cn] = f"co-product of {ps.id}"
    return Valuation(value, basis)


def _run_cost(ds: Dataset, ps, value: dict[Node, float]) -> float:
    """Materials and conversion of a run, per good unit of the main product."""
    lot = typical_lot(ps)
    mat = sum(value.get((ps.location, n.product), 0.0) * (n.per_unit + n.per_order / lot) for n in needs(ds, ps))
    return mat + conversion_unit_cost(ds, ps.id)


def option_unit_cost(ds: Dataset, opt: SupplyOption, value: dict[Node, float]) -> float:
    loc, prod = opt.node
    if opt.kind == "buy":
        return landed_unit_cost(ds, opt.source_id)
    if opt.kind == "transfer":
        ln: TransportLane = ds.lane_by_id[opt.source_id]
        return value.get((ln.origin, prod), 0.0) + freight_per_unit(ds, ln.planning_mode, prod) + handling(ds, loc)
    ps = ds.production_source_by_id[opt.source_id]
    return _run_cost(ds, ps, value) * main_share(ps)
