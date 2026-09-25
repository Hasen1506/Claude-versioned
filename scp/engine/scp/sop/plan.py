"""S&OP constrained supply plan: a time-phased network-flow LP over the planning master data
(blueprint §6, phase P4).

Variables per S&OP bucket t
    make[s,t]    good units of production source s available in t (started ⌊lead⌉ buckets earlier)
    buy[p,t]     units of purchasing source p received in t (ordered lead buckets earlier)
    ship[l,k,t]  units of product k on lane l arriving in t (dispatched lead buckets earlier)
    inv[n,t]     end-of-bucket stock at node n (0 at customers)
    sales[n,t]   deliveries against demand at demand node n
    back[n,t]    demand carried late into the next bucket;  lost[n,t]  demand never served
    ot[r,t]      overtime hours;  gap[n,t]  shortfall below the safety-stock target

Constraints
    stock balance    inv[t−1] + arrivals(t) + firm receipts(t) − dispatches(t) − issues(t) − sales(t) = inv[t]
    demand balance   back[t−1] + demand(t) − sales(t) − lost(t) = back[t]
    capacity         Σ hours·started(make) ≤ regular(t) + ot[t],  ot ≤ overtime limit
    supplier / lane  quantity ordered / dispatched in t ≤ weekly capacity × days/7
    storage          Σ volume·inv ≤ m³ capacity;   shelf life  inv[t] ≤ outflow over the next shelf-life window
    safety stock     inv[t] + gap[t] ≥ target

Objective
    cost mode    min purchase + conversion + transport + handling + holding + overtime
                     + backlog penalty (by priority) + lost-sale penalty + safety-stock shortfall penalty
    profit mode  max price·sales − the same costs, with demand an upper bound (no lost-sale penalty)

Shadow prices are the LP duals: the value of one more unit of each binding limit, valid over the
right-hand-side range HiGHS reports. Setups and lot sizes are left to MRP and scheduling.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from ..model import DemandKind, SopMode
from ..model.dataset import Dataset
from ..network import Node, build_graph
from ..plan import costing
from ..plan.leadtime import lead_time_std_days, nominal_lead_time_days, resource_calendar
from ..plan.rates import bucket_days, horizon_flows, node_role, policy_safety_stock
from ..time import Buckets
from ..validate import has_errors, validate
from .lp import INF, LinearProgram
from .result import (
    Binding, DemandLine, Economics, Flow, ResourceLine, SolverStats, SopBucket, SopKpis, SopResult, SupplyLine,
)


def _bucket_offset(days: float, mean_bucket: float) -> int:
    return max(0, int(round(days / mean_bucket))) if mean_bucket > 0 else 0


def _prio_factor(p: float) -> float:
    """Priority 1 (highest) → 1.8×, 5 → 1×, 9 → 0.2× the backlog penalty."""
    return (10.0 - p) / 5.0


def run_sop(ds: Dataset, *, time_limit: float = 60.0) -> SopResult:
    s = ds.settings
    cfg = ds.sop
    profit = cfg.mode is SopMode.PROFIT
    res = SopResult(ok=False, mode=cfg.mode, currency=s.currency, carrying_rate=s.carrying_rate)
    res.issues = validate(ds)
    if has_errors(res.issues):
        return res
    g = build_graph(ds)
    val = costing.roll_up(ds, g)
    bk = Buckets(s.model_copy(update={"bucket": cfg.bucket}))
    T = len(bk)
    mean_bd = s.horizon_days / max(1, T)
    start = s.planning_start
    res.buckets = [SopBucket(index=b.index, start=b.start, end=b.end, label=b.label, days=b.days) for b in bk]
    nodes = list(g.order)
    role = {n: node_role(ds, n) for n in nodes}
    is_cust = {n: role[n] == "customer" for n in nodes}
    rate = {n: (lp.holding_rate if (lp := ds.location_product_by_key.get(n)) and lp.holding_rate is not None
                else s.carrying_rate) for n in nodes}

    # ---- demand per node and bucket: max(forecast, orders), orders past due land in bucket 0 ----------
    fc: dict[Node, list[float]] = defaultdict(lambda: [0.0] * T)
    so: dict[Node, list[float]] = defaultdict(lambda: [0.0] * T)
    pw: dict[Node, list[float]] = defaultdict(lambda: [0.0] * T)   # Σ qty·priority
    for d in ds.demand:
        n = (d.location, d.product)
        if n not in role:
            continue
        if d.kind is DemandKind.FORECAST:
            span = d.period_days or 1
            for b in bk:
                ov = (min(d.date + timedelta(days=span), b.end) - max(d.date, b.start)).days
                if ov > 0:
                    q = d.qty * ov / span
                    fc[n][b.index] += q
                    pw[n][b.index] += q * d.priority
        else:
            i = 0 if d.date < start else bk.index_of(d.date)
            if 0 <= i < T:
                so[n][i] += d.qty
                pw[n][i] += d.qty * d.priority
    dem: dict[Node, list[float]] = {}
    prio: dict[Node, list[float]] = {}
    for n in set(fc) | set(so):
        row = [max(fc[n][t], so[n][t]) * cfg.demand_factor for t in range(T)]
        if sum(row) <= 0:
            continue
        dem[n] = row
        tot = [fc[n][t] + so[n][t] for t in range(T)]
        prio[n] = [pw[n][t] / tot[t] if tot[t] > 0 else 5.0 for t in range(T)]
    demand_nodes = [n for n in nodes if n in dem]

    def price(n: Node) -> float:
        p = ds.product_by_id.get(n[1])
        return p.price if p and p.price is not None else val.unit_value.get(n, 0.0)

    no_price = sorted({n[1] for n in demand_nodes if (p := ds.product_by_id.get(n[1])) is None or p.price is None})

    lp = LinearProgram()
    # ---- columns ---------------------------------------------------------------------------------------
    inv = {n: [lp.var(f"inv|{n}|{t}", val.unit_value.get(n, 0.0) * rate[n] * bk[t].days / 365.0,
                      0.0, 0.0 if is_cust[n] else INF) for t in range(T)] for n in nodes}
    sales: dict[Node, list[int]] = {}
    back: dict[Node, list[int]] = {}
    lost: dict[Node, list[int]] = {}
    for n in demand_nodes:
        ref = price(n)
        sales[n] = [lp.var(f"sales|{n}|{t}", -ref if profit else 0.0) for t in range(T)]
        back[n] = [lp.var(f"back|{n}|{t}", ref * cfg.backlog_rate_per_day * bk[t].days * _prio_factor(prio[n][t])
                          # demand still open when the horizon ends is demand lost
                          + (0.0 if profit or t < T - 1 else ref * cfg.lost_sale_rate))
                   for t in range(T)]
        lost[n] = [lp.var(f"lost|{n}|{t}", 0.0 if profit else ref * cfg.lost_sale_rate) for t in range(T)]

    arrivals: dict[Node, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))  # node → t → {col: coef}
    departs: dict[Node, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))

    def add(target: dict[Node, dict[int, dict[int, float]]], n: Node, t: int, col: int, coef: float) -> None:
        cell = target[n][t]
        cell[col] = cell.get(col, 0.0) + coef

    flows: list[tuple[Flow, list[int | None]]] = []
    res_load: dict[str, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))  # resource → start t → {col: h}
    sup_load: dict[str, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    lane_load: dict[str, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    cost_of: dict[int, tuple[str, float]] = {}   # column → (economics bucket, unit cost)

    for n in nodes:
        for opt in g.options.get(n) or []:
            if opt.kind == "make":
                ps = ds.production_source_by_id[opt.source_id]
                lt = nominal_lead_time_days(ds, opt) or 0.0
                off = _bucket_offset(lt, mean_bd)
                uc = costing.conversion_unit_cost(ds, ps.id)
                started = 1.0 / (1.0 - ps.assembly_scrap)
                cols: list[int | None] = []
                for t in range(T):
                    t0 = t - off
                    if t0 < 0 or not _valid(ps.valid_from, ps.valid_to, bk[t].start, bk[t].end):
                        cols.append(None)
                        continue
                    j = lp.var(f"make|{ps.id}|{t}", uc)
                    cost_of[j] = ("production", uc)
                    cols.append(j)
                    add(arrivals, n, t, j, 1.0)
                    for c in ps.components:
                        add(departs, (ps.location, c.product), t0, j, costing.component_factor(ds, ps.id, c.product))
                    for op in ps.operations:
                        if op.run_hours_per_unit > 0:
                            cell = res_load[op.resource][t0]
                            cell[j] = cell.get(j, 0.0) + op.run_hours_per_unit * started
                        if op.labor_resource and op.labor_hours_per_unit > 0:
                            cell = res_load[op.labor_resource][t0]
                            cell[j] = cell.get(j, 0.0) + op.labor_hours_per_unit * started
                flows.append((Flow(kind="make", source_id=ps.id, location=n[0], product=n[1], origin=None, qty=[],
                                   unit_cost=uc, lead_buckets=off), cols))
            elif opt.kind == "buy":
                pu = ds.purchasing_source_by_id[opt.source_id]
                lt = nominal_lead_time_days(ds, opt) or 0.0
                off = _bucket_offset(lt, mean_bd)
                uc = costing.landed_unit_cost(ds, pu.id)
                cols = []
                for t in range(T):
                    t0 = t - off
                    if t0 < 0 or not _valid(pu.valid_from, pu.valid_to, bk[t].start, bk[t].end):
                        cols.append(None)
                        continue
                    j = lp.var(f"buy|{pu.id}|{t}", uc)
                    cost_of[j] = ("purchase", uc)
                    cols.append(j)
                    add(arrivals, n, t, j, 1.0)
                    if pu.capacity_per_week:
                        sup_load[pu.id][t0][j] = 1.0
                flows.append((Flow(kind="buy", source_id=pu.id, location=n[0], product=n[1], origin=pu.supplier, qty=[],
                                   unit_cost=uc, lead_buckets=off), cols))
            else:
                ln = ds.lane_by_id[opt.source_id]
                mode = ln.planning_mode
                lt = nominal_lead_time_days(ds, opt) or 0.0
                off = _bucket_offset(lt, mean_bd)
                uc = costing.freight_per_unit(ds, mode, n[1]) + (0.0 if is_cust[n] else costing.handling(ds, n[0]))
                origin = (ln.origin, n[1])
                cols = []
                for t in range(T):
                    t0 = t - off
                    if t0 < 0:
                        cols.append(None)
                        continue
                    j = lp.var(f"ship|{ln.id}|{n[1]}|{t}", uc)
                    cost_of[j] = ("transport", uc)
                    cols.append(j)
                    add(arrivals, n, t, j, 1.0)
                    add(departs, origin, t0, j, 1.0)
                    if mode.capacity_units_per_week:
                        lane_load[ln.id][t0][j] = 1.0
                flows.append((Flow(kind="transfer", source_id=ln.id, location=n[0], product=n[1], origin=ln.origin, qty=[],
                                   unit_cost=uc, lead_buckets=off), cols))

    # firm receipts (past due land in bucket 0)
    firm: dict[Node, list[float]] = defaultdict(lambda: [0.0] * T)
    for r in ds.receipts:
        i = 0 if r.due_date < start else bk.index_of(r.due_date)
        if 0 <= i < T:
            firm[(r.location, r.product)][i] += r.qty
        for rv in r.reservations:      # still to be issued: components, or a transfer's goods at its origin
            j = 0 if rv.date < start else bk.index_of(rv.date)
            if 0 <= j < T:
                firm[(rv.location, rv.product)][j] -= rv.qty

    # ---- safety-stock targets (the node's configured policy, as MRP holds it) --------------------------
    horizon = horizon_flows(ds, g)
    per_bucket = bucket_days(ds, len(Buckets(s)))
    ss_target: dict[Node, float] = {}
    gap: dict[Node, list[int]] = {}
    for n in nodes:
        if role[n] != "stocking":
            ss_target[n] = 0.0
            continue
        opts = g.options.get(n) or []
        lt = (nominal_lead_time_days(ds, opts[0]) or 0.0) if opts else 0.0
        q = policy_safety_stock(ds, g, n, mean_daily=horizon.mean[n], lead_time=lt,
                                lead_time_std=lead_time_std_days(ds, opts[0]) if opts else 0.0,
                                unit_value=val.unit_value.get(n, 0.0), days_per_bucket=per_bucket).qty
        ss_target[n] = q
        if q > 0:
            uv = val.unit_value.get(n, 0.0)
            gap[n] = [lp.var(f"gap|{n}|{t}", uv * cfg.ss_shortfall_rate_per_day * bk[t].days) for t in range(T)]

    # ---- rows --------------------------------------------------------------------------------------------
    bal_row: dict[Node, list[int]] = {}
    dem_row: dict[Node, list[int]] = {}
    lp_on_hand = {n: (0.0 if is_cust[n] else (x.on_hand if (x := ds.location_product_by_key.get(n)) else 0.0))
                  for n in nodes}
    for n in nodes:
        rows = []
        for t in range(T):
            coef: dict[int, float] = {}
            for j, v in arrivals[n][t].items():
                coef[j] = coef.get(j, 0.0) + v
            for j, v in departs[n][t].items():
                coef[j] = coef.get(j, 0.0) - v
            if n in sales:
                coef[sales[n][t]] = -1.0
            coef[inv[n][t]] = coef.get(inv[n][t], 0.0) - 1.0
            if t > 0:
                coef[inv[n][t - 1]] = coef.get(inv[n][t - 1], 0.0) + 1.0
            if firm[n][t] < -1e-9:
                # a firm reservation the plan cannot cover: allowed, at more than a lost sale costs
                coef[lp.var(f"rsv|{n}|{t}", max(val.unit_value.get(n, 0.0), 1.0) * cfg.lost_sale_rate * 2)] = 1.0
            rhs = -firm[n][t] - (lp_on_hand[n] if t == 0 else 0.0)
            rows.append(lp.row(f"bal|{n}|{t}", coef, rhs, rhs))
        bal_row[n] = rows
        if n in gap:
            for t in range(T):
                lp.row(f"ss|{n}|{t}", {inv[n][t]: 1.0, gap[n][t]: 1.0}, ss_target[n], INF)
    for n in demand_nodes:
        rows = []
        for t in range(T):
            coef = {sales[n][t]: 1.0, lost[n][t]: 1.0, back[n][t]: 1.0}
            if t > 0:
                coef[back[n][t - 1]] = -1.0
            rows.append(lp.row(f"dem|{n}|{t}", coef, dem[n][t], dem[n][t]))
        dem_row[n] = rows

    binding_rows: list[tuple[int, str, str, int, str, str]] = []  # row, kind, id, t, label, unit
    ot_cols: dict[str, list[int | None]] = {}
    cap_rows: dict[str, list[int | None]] = {}
    capacity: dict[str, list[float]] = {}
    ot_limit: dict[str, list[float]] = {}
    for r in ds.resources:
        cal = resource_calendar(ds, r.id)
        f = cfg.capacity_factor
        extra = cfg.capacity_add_hours_per_week.get(r.id, 0.0)
        capacity[r.id] = [max(0.0, cal.workdays_between(b.start, b.end) * r.hours_per_workday * f + extra * b.days / 7.0)
                          for b in bk]
        ot_limit[r.id] = [cal.workdays_between(b.start, b.end) * r.overtime_hours_per_day * r.units * f
                          if cfg.allow_overtime else 0.0 for b in bk]
        ot_cols[r.id] = []
        cap_rows[r.id] = []
        for t in range(T):
            loads = res_load[r.id][t]
            if not r.finite or not loads:
                ot_cols[r.id].append(None)
                cap_rows[r.id].append(None)
                continue
            coef = dict(loads)
            if ot_limit[r.id][t] > 0:
                o = lp.var(f"ot|{r.id}|{t}", r.overtime_cost_per_hour, 0.0, ot_limit[r.id][t])
                cost_of[o] = ("overtime", r.overtime_cost_per_hour)
                coef[o] = -1.0
                ot_cols[r.id].append(o)
            else:
                ot_cols[r.id].append(None)
            i = lp.row(f"cap|{r.id}|{t}", coef, -INF, capacity[r.id][t])
            cap_rows[r.id].append(i)
            binding_rows.append((i, "resource", r.id, t, f"{r.id} hours", "hour"))
    for pid, per_t in sup_load.items():
        pu = ds.purchasing_source_by_id[pid]
        for t, coef in per_t.items():
            cap = (pu.capacity_per_week or 0.0) * bk[t].days / 7.0
            i = lp.row(f"sup|{pid}|{t}", coef, -INF, cap)
            binding_rows.append((i, "supplier", pid, t, f"{pu.supplier} → {pu.product}", "unit"))
    for lid, per_t in lane_load.items():
        mode = ds.lane_by_id[lid].planning_mode
        for t, coef in per_t.items():
            cap = (mode.capacity_units_per_week or 0.0) * bk[t].days / 7.0
            i = lp.row(f"lane|{lid}|{t}", coef, -INF, cap)
            binding_rows.append((i, "lane", lid, t, f"lane {lid}", "unit"))
    for loc in ds.locations:
        if loc.storage_capacity_m3 is None:
            continue
        here = [n for n in nodes if n[0] == loc.id and not is_cust[n]]
        vol = {n: (p.volume_m3 or 0.0) if (p := ds.product_by_id.get(n[1])) else 0.0 for n in here}
        if not any(vol.values()):
            continue
        for t in range(T):
            i = lp.row(f"store|{loc.id}|{t}", {inv[n][t]: vol[n] for n in here if vol[n] > 0}, -INF, loc.storage_capacity_m3)
            binding_rows.append((i, "storage", loc.id, t, f"{loc.id} storage", "m³"))
    for n in nodes:
        p = ds.product_by_id.get(n[1])
        if is_cust[n] or not p or not p.shelf_life_days:
            continue
        for t in range(T):
            # stock at the end of t must leave within the shelf life: covered by outflow of the next buckets
            end = bk[t].end + timedelta(days=p.shelf_life_days)
            if end > bk[T - 1].end:
                continue  # the window runs past the horizon: what happens after it cannot be judged
            ahead = [u for u in range(t + 1, T) if bk[u].start < end]
            coef: dict[int, float] = {inv[n][t]: 1.0}
            for u in ahead:
                share = min(1.0, (end - bk[u].start).days / bk[u].days)
                for j, v in departs[n][u].items():
                    coef[j] = coef.get(j, 0.0) - v * share
                if n in sales:
                    coef[sales[n][u]] = coef.get(sales[n][u], 0.0) - share
            i = lp.row(f"shelf|{n}|{t}", coef, -INF, 0.0)
            binding_rows.append((i, "shelf_life", f"{n[0]}/{n[1]}", t, f"{n[1]} at {n[0]} shelf life", "unit"))

    sol = lp.solve(ranging=True, time_limit=time_limit)
    m, ncols = lp.shape
    res.solver = SolverStats(status=sol.status, rows=m, columns=ncols, iterations=sol.iterations, seconds=sol.seconds)
    if sol.status != "optimal":
        res.notes = [f"The LP did not solve to optimality: {sol.status}."]
        return res
    x = sol.x

    def xv(j: int | None) -> float:
        return float(x[j]) if j is not None else 0.0

    def clean(v: float) -> float:
        return 0.0 if abs(v) < 1e-7 else v

    # ---- report -----------------------------------------------------------------------------------------
    for n in demand_nodes:
        res.demand.append(DemandLine(
            location=n[0], product=n[1], price=price(n), demand=dem[n],
            sales=[clean(xv(j)) for j in sales[n]], backlog=[clean(xv(j)) for j in back[n]],
            lost=[clean(xv(j)) for j in lost[n]],
            # the balance-row dual is ∂objective/∂demand; in profit mode the objective carries −price·sales
            marginal_cost=[clean(float(sol.dual[i]) + (price(n) if profit else 0.0)) for i in dem_row[n]]))
    for fl, cols in flows:
        fl.qty = [clean(xv(j)) for j in cols]
    res.flows = [fl for fl, _ in flows]
    by_node: dict[Node, dict[str, list[float]]] = defaultdict(lambda: {k: [0.0] * T for k in ("make", "buy", "in", "out")})
    for fl, _ in flows:
        n = (fl.location, fl.product)
        key = {"make": "make", "buy": "buy", "transfer": "in"}[fl.kind]
        for t, q in enumerate(fl.qty):
            by_node[n][key][t] += q
        if fl.kind == "transfer":
            o = (fl.origin, fl.product)
            for t, q in enumerate(fl.qty):
                if q and t - fl.lead_buckets >= 0:
                    by_node[o]["out"][t - fl.lead_buckets] += q
    for n in nodes:
        consumed = [0.0] * T
        for t in range(T):
            consumed[t] = clean(sum(v * xv(j) for j, v in departs[n][t].items()) - by_node[n]["out"][t])
        res.supply.append(SupplyLine(
            location=n[0], product=n[1], role="customer" if is_cust[n] else "stocking",
            make=by_node[n]["make"], buy=by_node[n]["buy"], transfer_in=by_node[n]["in"], transfer_out=by_node[n]["out"],
            consumed=consumed, inventory=[clean(xv(j)) for j in inv[n]], ss_target=ss_target[n],
            ss_shortfall=[clean(xv(j)) for j in gap[n]] if n in gap else [0.0] * T, unit_value=val.unit_value.get(n, 0.0)))
    for r in ds.resources:
        load = [sum(v * xv(j) for j, v in res_load[r.id][t].items()) for t in range(T)]
        ot = [xv(j) for j in ot_cols[r.id]]
        sp, up, dn = [], [], []
        for t in range(T):
            i = cap_rows[r.id][t]
            sp.append(clean(-float(sol.dual[i])) if i is not None else 0.0)
            up.append(_finite(sol.rhs_up[i]) if i is not None else None)
            dn.append(_finite(sol.rhs_dn[i]) if i is not None else None)
        res.resources.append(ResourceLine(
            resource=r.id, location=r.location, finite=r.finite, capacity=capacity[r.id], load=[clean(v) for v in load],
            overtime=[clean(v) for v in ot], overtime_limit=ot_limit[r.id],
            utilization=[(load[t] / capacity[r.id][t]) if capacity[r.id][t] > 0 else (0.0 if load[t] < 1e-9 else math.inf)
                         for t in range(T)],
            shadow_price=sp, valid_up=up, valid_down=dn))
    for i, kind, oid, t, label, unit in binding_rows:
        price_ = -float(sol.dual[i])
        if abs(price_) < 1e-7:
            continue
        res.binding.append(Binding(kind=kind, id=oid, bucket=t, label=f"{label} · {bk[t].label}", limit=float(lp.row_hi[i]),
                                   used=float(sol.activity[i]), shadow_price=price_, unit=unit,
                                   valid_up=_finite(sol.rhs_up[i]), valid_down=_finite(sol.rhs_dn[i])))
    for r in ds.resources:  # an overtime ceiling that binds is worth reporting too
        for t, j in enumerate(ot_cols[r.id]):
            if j is None:
                continue
            i = cap_rows[r.id][t]
            if i is None or xv(j) < ot_limit[r.id][t] - 1e-6:
                continue
            value = -float(sol.dual[i]) - r.overtime_cost_per_hour
            if value > 1e-7:
                res.binding.append(Binding(kind="overtime", id=r.id, bucket=t, label=f"{r.id} overtime · {bk[t].label}",
                                           limit=ot_limit[r.id][t], used=xv(j), shadow_price=value, unit="hour",
                                           valid_up=None, valid_down=None))
    res.binding.sort(key=lambda b: -abs(b.shadow_price))

    # ---- economics & KPIs --------------------------------------------------------------------------------
    econ = defaultdict(float)
    for j, (k, c) in cost_of.items():
        econ[k] += c * xv(j)
    for n in nodes:
        econ["holding"] += sum(lp.cost[j] * xv(j) for j in inv[n])
        if n in gap:
            econ["ss"] += sum(lp.cost[j] * xv(j) for j in gap[n])
    for n in demand_nodes:
        econ["revenue"] += sum(price(n) * xv(j) for j in sales[n])
        econ["backlog"] += sum(lp.cost[j] * xv(j) for j in back[n])
        econ["lost"] += sum(lp.cost[j] * xv(j) for j in lost[n])
    total = sum(econ[k] for k in ("purchase", "production", "transport", "holding", "overtime", "backlog", "lost", "ss"))
    res.economics = Economics(
        revenue=econ["revenue"], purchase=econ["purchase"], production=econ["production"], transport=econ["transport"],
        holding=econ["holding"], overtime=econ["overtime"], backlog_penalty=econ["backlog"], lost_penalty=econ["lost"],
        ss_penalty=econ["ss"], total_cost=total, profit=econ["revenue"] - total)
    d_tot = sum(sum(v) for v in dem.values())
    s_tot = sum(sum(dl.sales) for dl in res.demand)
    on_time = sum(min(dl.demand[t], max(0.0, dl.sales[t] - (dl.backlog[t - 1] if t else 0.0)))
                  for dl in res.demand for t in range(T))
    util = [u for rl in res.resources if rl.finite for u in rl.utilization if math.isfinite(u)]
    res.kpis = SopKpis(demand=d_tot, sales=s_tot, lost=sum(sum(dl.lost) for dl in res.demand),
                       backlog_end=sum(dl.backlog[-1] for dl in res.demand) if T else 0.0,
                       fill_rate=s_tot / d_tot if d_tot else 1.0, on_time_rate=on_time / d_tot if d_tot else 1.0,
                       max_utilization=max(util, default=0.0))
    res.notes = [
        f"{T} {cfg.bucket.value} buckets; lead times are rounded to whole buckets "
        f"(mean bucket {mean_bd:.1f} days), so a lead time under half a bucket is same-bucket.",
        "Demand per bucket is the larger of forecast and sales orders; overdue orders are due in the first bucket.",
        "Setups, lot sizes and minimum order quantities are left to MRP and scheduling: the LP plans volumes.",
        "Safety-stock targets are each node's configured policy; falling below costs the shortfall penalty.",
    ]
    if profit and no_price:
        res.notes.append(f"No selling price for {', '.join(no_price)}: valued at cost, so serving it earns no margin.")
    res.ok = True
    return res


def _valid(frm: date | None, to: date | None, b_start: date, b_end: date) -> bool:
    return (frm is None or frm < b_end) and (to is None or to >= b_start)


def _finite(v: float) -> float | None:
    return float(v) if v is not None and math.isfinite(v) and abs(v) < 1e29 else None


__all__ = ["run_sop"]
