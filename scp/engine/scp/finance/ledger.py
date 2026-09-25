"""Plan cost reconciliation, inventory value and cost to serve.

Cost to serve rolls plan cost down the pegging, upstream first. An order's full cost is its own cost
(``PlannedOrder.costs``) plus the full cost of its inputs (the requirements it created). A requirement's cost
is, for each peg, the pegged share of the supplying order's full cost — or, for opening stock and firm
receipts, the pegged quantity at unit value (the ``stock`` / ``firm`` categories: already committed, so not
plan spend) — plus a share of its node's holding cost weighted by quantity × days held. Whatever no
independent demand absorbs (lot-size excess, stock left at the horizon end, inputs to firm orders) is kept
as *unabsorbed*, so served + unabsorbed equals the plan cost in every category.
"""
from __future__ import annotations

import math
from collections import defaultdict

from ..model import Dataset, LocationType
from ..plan.result import PlanResult, Requirement
from .result import (
    PLAN_COSTS, CostLine, InventoryValue, LocationValue, Reconciliation, ServeRow, ValueBucket,
)

Vec = dict[str, float]
INDEPENDENT = ("forecast", "sales_order")


def _add(acc: Vec, v: Vec, f: float = 1.0) -> None:
    for k, x in v.items():
        if x:
            acc[k] = acc.get(k, 0.0) + x * f


def _is_customer(ds: Dataset, loc: str) -> bool:
    return ds.location_type(loc) is LocationType.CUSTOMER


# ----------------------------------------------------------------------------------------------- inventory
def inventory_value(ds: Dataset, plan: PlanResult) -> InventoryValue:
    horizon = ds.settings.horizon_days
    days = [(b.end - b.start).days for b in plan.buckets]
    types = sorted({p.type.value for p in ds.products})
    value = [0.0] * len(plan.buckets)
    by_type = [defaultdict(float) for _ in plan.buckets]
    loc_rows: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # start, end, avg·horizon, holding
    for node in plan.nodes:
        if _is_customer(ds, node.location):
            continue
        p = ds.product_by_id.get(node.product)
        ptype = p.type.value if p else "?"
        row = loc_rows[node.location]
        row[0] += node.on_hand * node.unit_value
        for i, b in enumerate(node.buckets):
            v = max(0.0, b.projected_on_hand) * node.unit_value
            value[i] += v
            by_type[i][ptype] += v
            row[2] += v * days[i]
            row[3] += b.holding_cost
        if node.buckets:
            row[1] += max(0.0, node.buckets[-1].projected_on_hand) * node.unit_value
    out = InventoryValue(types=types)
    out.buckets = [ValueBucket(bucket=b.index, label=b.label, start=b.start, days=days[i], value=value[i],
                               by_type={t: by_type[i].get(t, 0.0) for t in types}) for i, b in enumerate(plan.buckets)]
    out.locations = sorted(
        (LocationValue(location=loc, type=(ds.location_type(loc) or LocationType.PLANT).value, start=r[0], end=r[1],
                       avg=r[2] / horizon, holding=r[3]) for loc, r in loc_rows.items()),
        key=lambda x: -x.avg)
    out.start = sum(r.start for r in out.locations)
    out.end = sum(r.end for r in out.locations)
    out.avg = sum(r.avg for r in out.locations)
    return out


# ----------------------------------------------------------------------------------------------- cost to serve
class _Ledger:
    def __init__(self, ds: Dataset, plan: PlanResult) -> None:
        self.ds, self.plan = ds, plan
        self.orders = {o.id: o for o in plan.orders}
        self.reqs = {r.id: r for r in plan.requirements}
        self.node = {(n.location, n.product): n for n in plan.nodes}
        self.receipt_date = {r.id: r.date for r in plan.receipts}
        self.receipts_by_node: dict[tuple[str, str], list] = defaultdict(list)
        for rc in plan.receipts:
            self.receipts_by_node[(rc.location, rc.product)].append(rc)
        self.order_pegged: dict[str, float] = defaultdict(float)
        for p in plan.pegs:
            if p.supply_kind == "order":
                self.order_pegged[p.supply_id] += p.qty
        self.pegs_by_req: dict[str, list] = defaultdict(list)
        for p in plan.pegs:
            self.pegs_by_req[p.requirement_id].append(p)
        self.inputs: dict[str, list[Requirement]] = defaultdict(list)
        for r in plan.requirements:
            if r.parent_order:
                self.inputs[r.parent_order].append(r)
        self.start = ds.settings.planning_start
        self.end = plan.buckets[-1].end if plan.buckets else self.start
        self.full: dict[str, Vec] = {}
        self.req_cost: dict[str, Vec] = {}
        self.unabsorbed: Vec = {}
        self.reasons: dict[str, float] = defaultdict(float)
        self.holding_share: dict[str, float] = {}
        self._allocate_holding()

    def _supply_date(self, p) -> object:
        if p.supply_kind == "order":
            return self.orders[p.supply_id].available_date
        if p.supply_kind == "receipt":
            return self.receipt_date.get(p.supply_id, self.start)
        return self.start

    def _allocate_holding(self) -> None:
        """Spread each node's holding cost over what sat in stock: pegs by qty × days from availability to need,
        supply left unpegged by qty × days to the horizon end (that share is unabsorbed)."""
        reqs_by_node: dict[tuple[str, str], list[Requirement]] = defaultdict(list)
        for r in self.plan.requirements:
            reqs_by_node[(r.location, r.product)].append(r)
        for key, n in self.node.items():
            holding = sum(b.holding_cost for b in n.buckets)
            if holding <= 0:
                continue
            weights: list[tuple[str | None, float]] = []
            pegged: dict[tuple[str, str], float] = defaultdict(float)
            for r in reqs_by_node.get(key, []):
                for p in self.pegs_by_req.get(r.id, []):
                    days = max(1, (r.date - self._supply_date(p)).days)
                    weights.append((r.id, p.qty * days))
                    pegged[(p.supply_kind, p.supply_id)] += p.qty
            supplies: list[tuple[str, str, float, object]] = []
            if n.on_hand > 0:
                supplies.append(("on_hand", f"OH:{key[0]}:{key[1]}", n.on_hand, self.start))
            for rc in self.receipts_by_node.get(key, []):
                supplies.append(("receipt", rc.id, rc.qty, rc.date))
            for oid in n.order_ids:
                o = self.orders[oid]
                supplies.append(("order", oid, o.qty, o.available_date))
            for kind, sid, q, d in supplies:
                left = q - pegged.get((kind, sid), 0.0)
                if left > 1e-9:
                    weights.append((None, left * max(1, (self.end - d).days)))
            total = sum(w for _, w in weights)
            if total <= 0:
                self._unabsorb({"holding": holding}, "stock held at the horizon end")
                continue
            for rid, w in weights:
                share = holding * w / total
                if rid is None:
                    self._unabsorb({"holding": share}, "stock held at the horizon end")
                else:
                    self.holding_share[rid] = self.holding_share.get(rid, 0.0) + share

    def _unabsorb(self, v: Vec, reason: str, f: float = 1.0) -> None:
        _add(self.unabsorbed, v, f)
        self.reasons[reason] += sum(x for k, x in v.items() if k in PLAN_COSTS) * f

    def order_full(self, oid: str) -> Vec:
        if oid in self.full:
            return self.full[oid]
        o = self.orders[oid]
        v: Vec = dict(o.costs)
        for r in self.inputs.get(oid, []):
            _add(v, self.requirement(r.id))
        self.full[oid] = v
        # the share of the order no requirement is pegged to (lot sizing, safety stock) is unabsorbed
        left = o.qty - self.order_pegged.get(oid, 0.0)
        if o.qty > 0 and left > 1e-9:
            self._unabsorb(v, "lot-size and safety-stock excess", left / o.qty)
        return v

    def requirement(self, rid: str) -> Vec:
        if rid in self.req_cost:
            return self.req_cost[rid]
        r = self.reqs[rid]
        v: Vec = {}
        uv = self.node[(r.location, r.product)].unit_value if (r.location, r.product) in self.node else 0.0
        for p in self.pegs_by_req.get(rid, []):
            if p.supply_kind == "order":
                o = self.orders[p.supply_id]
                if o.qty > 0:
                    _add(v, self.order_full(o.id), p.qty / o.qty)
            elif p.supply_kind == "receipt":
                _add(v, {"firm": p.qty * uv})
            else:
                _add(v, {"stock": p.qty * uv})
        if rid in self.holding_share:
            _add(v, {"holding": self.holding_share[rid]})
        self.req_cost[rid] = v
        return v

    def run(self) -> list[ServeRow]:
        for oid in self.orders:
            self.order_full(oid)
        rows: dict[tuple[str, str], ServeRow] = {}
        for r in self.plan.requirements:
            v = self.requirement(r.id)
            if r.kind in INDEPENDENT:
                key = (r.location, r.product)
                if key not in rows:
                    loc = self.ds.location_by_id.get(r.location)
                    prod = self.ds.product_by_id.get(r.product)
                    rows[key] = ServeRow(location=r.location, location_type=loc.type.value if loc else "",
                                         region=loc.region if loc else "", product=r.product, demand=0.0, served=0.0,
                                         price=prod.price if prod else None, revenue=0.0, costs={})
                row = rows[key]
                row.demand += r.qty
                row.served += sum(p.qty for p in self.pegs_by_req.get(r.id, []))
                costs = dict(row.costs)
                _add(costs, v)
                row.costs = costs
            elif r.parent_order not in self.orders:
                self._unabsorb(v, "inputs to firm orders")   # reservations of released production / transfers
        out = []
        for row in rows.values():
            row.revenue = row.served * (row.price or 0.0)
            row.plan_cost = sum(x for k, x in row.costs.items() if k in PLAN_COSTS)
            row.total_cost = sum(row.costs.values())
            row.cost_per_unit = row.total_cost / row.served if row.served > 0 else 0.0
            row.margin = row.revenue - row.total_cost
            row.margin_pct = row.margin / row.revenue if row.revenue > 0 else None
            out.append(row)
        return sorted(out, key=lambda x: (x.region, x.location, x.product))


def cost_to_serve(ds: Dataset, plan: PlanResult) -> tuple[list[ServeRow], Reconciliation]:
    led = _Ledger(ds, plan)
    rows = led.run()
    k = plan.kpis
    source = defaultdict(float)
    for o in plan.orders:
        for c, x in o.costs.items():
            source[c] += x
    source["holding"] = sum(b.holding_cost for n in plan.nodes for b in n.buckets)
    rec = Reconciliation(unabsorbed_reasons={r: v for r, v in sorted(led.reasons.items()) if abs(v) > 1e-9})
    for c in PLAN_COSTS:
        planned = getattr(k, f"{c}_cost")
        served = sum(r.costs.get(c, 0.0) for r in rows)
        un = led.unabsorbed.get(c, 0.0)
        rec.lines.append(CostLine(category=c, plan=planned, sources=source[c], served=served, unabsorbed=un,
                                  difference=planned - served - un))
    rec.total_plan = k.total_cost
    rec.total_served = sum(r.plan_cost for r in rows)
    rec.total_unabsorbed = sum(led.unabsorbed.get(c, 0.0) for c in PLAN_COSTS)
    tol = 1e-6 * max(1.0, abs(k.total_cost))
    rec.reconciled = all(abs(ln.difference) <= tol and abs(ln.plan - ln.sources) <= tol for ln in rec.lines) and \
        math.isclose(sum(ln.plan for ln in rec.lines), k.total_cost, rel_tol=1e-9, abs_tol=tol)
    return rows, rec
