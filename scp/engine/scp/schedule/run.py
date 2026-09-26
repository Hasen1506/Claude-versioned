"""Dataset → scheduling instance → detailed schedule.

The orders come from the network MRP: every planned make order that starts inside the scheduling
window is released to the shop floor on its planned start date and is due on its MRP due date
(the day goods must be finished to meet the pegged requirement). Labour pools named on operations
are not sequenced; their daily load is reported against headcount so overloads are visible.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from datetime import timedelta

from ..model import Dataset
from ..plan import run_mrp
from ..plan.leadtime import gr_days, location_calendar, resource_calendar
from ..plan.result import PlanResult
from ..plan.structure import entering, needs
from ..time.capacity import day_capacity, max_units
from ..validate import has_errors, validate
from .clock import ResourceClock, after_queue
from .core import Decoded, Instance, is_changeover, Job, OpSpec, Res, check, complete, decode, edd, improve, setup_rule
from .result import (
    LabourDay, PartSupply, ScheduledOp, ScheduledOrder, ScheduleKpis, ScheduleResource, ScheduleResult, SearchInfo,
)


def group_of(ds: Dataset, product: str) -> str:
    p = ds.product_by_id.get(product)
    return (p.setup_group if p and p.setup_group else product)


def resource_clocks(ds: Dataset, rid: str) -> Res:
    """A resource's working time, one clock per unit: its shifts, breaks and capacity changes by day."""
    r = ds.resource_by_id[rid]
    cal = resource_calendar(ds, rid)
    origin, start = ds.settings.planning_start, ds.scheduling.day_start_hour
    plain = not r.shifts and not r.capacity_changes

    def unit_clock(u: int) -> ResourceClock:
        def days(d: dt.date) -> tuple[list[tuple[float, float]], float]:
            dc = day_capacity(r, cal, d, start)
            return (list(dc.windows) if dc.units > u else []), dc.efficiency
        return ResourceClock(cal, origin, start, r.shifts_per_day * r.hours_per_shift, r.efficiency,
                             None if plain else days)

    n = max_units(r)
    clocks = [unit_clock(u) for u in range(n)] if not plain else None
    return Res(rid, n, clocks[0] if clocks else unit_clock(0), r.finite, clocks)


def build_instance(ds: Dataset, plan: PlanResult | None = None) -> tuple[Instance, dict, int, int]:
    s = ds.settings
    cfg = ds.scheduling
    origin = s.planning_start
    plan = plan or run_mrp(ds)
    window_end = origin + timedelta(days=cfg.horizon_days)
    resources: dict[str, Res] = {}

    def res(rid: str) -> Res:
        if rid not in resources:
            resources[rid] = resource_clocks(ds, rid)
        return resources[rid]

    jobs: dict[str, Job] = {}
    meta: dict[str, dict] = {}
    beyond = no_routing = 0
    def add(oid: str, ps, location: str, product: str, qty: float, start: dt.date, due: dt.date,
            firm: bool, steps: dict[int, str]) -> None:
        enter = entering(ps)
        grp = group_of(ds, product)
        cal = location_calendar(ds, location)
        release = max(0, (start - origin).days) * 24.0
        ops: list[OpSpec] = []
        lead_out = 0.0   # outside processing before the first step here
        for op in sorted(ps.operations, key=lambda x: x.seq):
            if op.subcontract is not None:
                # done by a supplier: a wait after the step before it (or before the order can start here)
                wait = op.subcontract.workdays + op.queue_workdays
                if ops:
                    ops[-1].queue_workdays += wait
                else:
                    lead_out += wait
                continue
            q = qty * enter[op.seq]
            # the plan may have put the step on one of its alternatives: start from that one, keep its own as an option
            rid = steps.get(op.seq, op.resource) if steps.get(op.seq) in ds.resource_by_id else op.resource
            alts = [a for a in [op.resource, *op.alternatives] if a != rid]
            ops.append(OpSpec(key=f"{oid}:{op.seq}", order=oid, seq=op.seq, resource=rid, product=product,
                              group=grp, qty=q, setup=op.setup_hours, run=op.run_hours_per_unit * q,
                              queue_workdays=op.queue_workdays, parallel=op.parallel_units,
                              labor_resource=op.labor_resource, labor_hours=op.labor_hours_per_unit * q,
                              alternatives=alts, send_ahead=op.send_ahead_qty))
        if lead_out:
            release = after_queue(cal, origin, release, lead_out)
        for op in ops:
            res(op.resource)
            for alt in op.alternatives:
                if alt in ds.resource_by_id:
                    res(alt)
        jobs[oid] = Job(oid, product, release, (due - origin).days * 24.0, ops)
        meta[oid] = {"location": location, "qty": qty, "start": max(start, origin), "due": due, "firm": firm,
                     "cal": cal, "ps": ps, "product": product, "missing": set(), "from": {}}

    for o in plan.orders:
        if o.kind != "make":
            continue
        if o.start_date >= window_end:
            beyond += 1
            continue
        ps = ds.production_source_by_id.get(o.source_id)
        if ps is None or not any(op.resource for op in ps.operations):
            no_routing += 1
            continue
        add(o.id, ps, o.location, o.product, o.qty, o.start_date, o.due_date, firm=False, steps=o.step_resources)

    need = _need_dates(ds, plan)
    for rc in ds.receipts:
        # firm production orders starting in the window: released at their start date (or now), due on their due
        # date or, when what they are pegged to needs them sooner, by then
        if rc.kind.value != "production" or not rc.source:
            continue
        if (rc.start_date or rc.due_date) >= window_end and not rc.scheduled:
            continue   # an order dated by an earlier schedule stays on it
        ps = ds.production_source_by_id.get(rc.source)
        if ps is None or not any(op.resource for op in ps.operations):
            continue
        due = rc.due_date
        if rc.id in need:
            gr = math.ceil(gr_days(ds.location_product_by_key.get((rc.location, rc.product))) - 1e-9)
            due = min(due, max(origin, need[rc.id] - timedelta(days=gr)))
        add(rc.id, ps, rc.location, rc.product, rc.qty, max(rc.start_date or origin, origin), due, firm=True,
            steps=rc.step_resources)

    if cfg.wait_for_parts:
        _parts(ds, plan, jobs, meta)

    changeovers = {(c.resource, c.from_group, c.to_group): c.hours for c in ds.changeovers}

    def after(op: OpSpec, t: float) -> float:
        return after_queue(meta[op.order]["cal"], origin, t, op.queue_workdays)

    def receive(order: str, t: float, workdays: float) -> float:
        return after_queue(meta[order]["cal"], origin, t, workdays)

    inst = Instance(resources, jobs, setup_rule(changeovers, cfg.minor_setup_factor), after,
                    cfg.tardiness_weight, cfg.setup_weight, receive)
    return inst, meta, beyond, no_routing


def _need_dates(ds: Dataset, plan: PlanResult) -> dict[str, dt.date]:
    """The earliest date anything pegged to each firm receipt needs it."""
    reqs = {r.id: r.date for r in plan.requirements}
    out: dict[str, dt.date] = {}
    for p in plan.pegs:
        if p.supply_kind == "receipt" and p.requirement_id in reqs:
            d = reqs[p.requirement_id]
            out[p.supply_id] = min(out.get(p.supply_id, d), d)
    return out


def _parts(ds: Dataset, plan: PlanResult, jobs: dict[str, Job], meta: dict) -> None:
    """Material-aware scheduling along the pegging: each step may start only once the parts it consumes are there.
    A part from stock is there now; from a receipt, or an order the schedule does not sequence, on its (projected)
    available day; from an order the schedule sequences, when that order finishes plus its goods-receipt days. What
    no supply covers is reported as missing and does not hold the step (the plan shows the shortage)."""
    origin = ds.settings.planning_start
    hours = lambda d: max(0, (d - origin).days) * 24.0   # noqa: E731
    orders = {o.id: o for o in plan.orders}
    rec_date = {r.id: r.date for r in plan.receipts}
    pegs: dict[str, list] = defaultdict(list)
    for p in plan.pegs:
        pegs[p.requirement_id].append(p)
    by_parent: dict[str, list] = defaultdict(list)
    for r in plan.requirements:
        if r.parent_order in jobs and r.kind == "dependent":
            by_parent[r.parent_order].append(r)

    def lag(order: str) -> float:
        m = meta[order]
        return gr_days(ds.location_product_by_key.get((m["location"], m["product"])))

    for oid, job in jobs.items():
        m = meta[oid]
        if not job.ops:
            continue
        step = {n.product: n.operation for n in needs(ds, m["ps"], m["start"])}
        for r in by_parent.get(oid, []):
            seq = step.get(r.product)
            op = next((o for o in job.ops if seq is None or o.seq >= seq), job.ops[-1])
            got = 0.0
            for p in pegs.get(r.id, []):
                got += p.qty
                sid = p.supply_id
                if p.supply_kind == "on_hand":
                    continue
                if sid in jobs and sid != oid:
                    op.waits_on.append((sid, lag(sid)))
                    m["from"].setdefault(sid, (r.product, None))
                    continue
                if p.supply_kind == "receipt":
                    t = hours(rec_date.get(sid, origin))
                else:
                    o = orders.get(sid)
                    if o is not None and o.delay_days < 0:
                        m["missing"].add(r.product)   # that order's own inputs are not covered
                    t = hours((o.projected_available_date or o.available_date) if o else origin)
                if t > op.parts_ready:
                    op.parts_ready = t
                if t > job.release + 1e-9:
                    m["from"][sid] = (r.product, t)
            if r.qty - got > 1e-6 * max(1.0, r.qty):
                m["missing"].add(r.product)
        for o in job.ops:
            o.waits_on = list(dict.fromkeys(o.waits_on))


def _kpis(inst: Instance, d: Decoded) -> ScheduleKpis:
    return ScheduleKpis(orders=len(d.completion), operations=sum(len(j.ops) for j in inst.jobs.values()),
                        late_orders=d.late_jobs, waiting_for_parts=len({k.rsplit(":", 1)[0] for k in d.held}),
                        tardiness_hours=d.tardiness, max_lateness_hours=d.max_lateness,
                        setup_hours=d.setup_hours, changeovers=d.changeovers, makespan_hours=d.makespan,
                        objective=d.objective)


def _labour(ds: Dataset, inst: Instance, d: Decoded) -> list[LabourDay]:
    ops = {o.key: o for j in inst.jobs.values() for o in j.ops}
    need: dict[tuple[str, int], float] = defaultdict(float)
    for b in d.blocks:
        o = ops[b.key]
        if not o.labor_resource or o.labor_hours <= 0 or b.end <= b.run_start:
            continue
        res = inst.resources[b.resource]
        clk = res.at(b.unit if res.finite else -1)
        share = o.labor_hours * (b.qty / o.qty)
        total = clk.work_between(b.run_start, b.end)
        if total <= 0:
            continue
        for day in range(int(b.run_start // 24), int((b.end - 1e-9) // 24) + 1):
            w = clk.work_between(max(b.run_start, day * 24.0), min(b.end, day * 24.0 + 24))
            need[(o.labor_resource, day)] += share * w / total
    out = []
    origin = ds.settings.planning_start
    for (rid, day), req in sorted(need.items()):
        r = ds.resource_by_id.get(rid)
        if r is None:
            continue
        date = origin + timedelta(days=day)
        avail = day_capacity(r, resource_calendar(ds, rid), date, ds.scheduling.day_start_hour).productive_hours
        out.append(LabourDay(resource=rid, date=date, required=req, available=avail, overload=req > avail + 1e-6))
    return out


def run_schedule(ds: Dataset, sequence: dict[str, list[str]] | None = None,
                 plan: PlanResult | None = None) -> ScheduleResult:
    s = ds.settings
    cfg = ds.scheduling
    out = ScheduleResult(ok=False, day_start_hour=cfg.day_start_hour)
    out.issues = validate(ds)
    if has_errors(out.issues):
        return out
    inst, meta, out.beyond_horizon, out.without_routing = build_instance(ds, plan)
    out.origin = dt.datetime.combine(s.planning_start, dt.time())

    base_seq = edd(inst)
    base = decode(inst, base_seq)
    out.baseline = _kpis(inst, base)
    if sequence:
        seqs = complete(inst, sequence)
        final = decode(inst, seqs)
        out.search = SearchInfo(mode="manual")
    elif cfg.improve:
        seqs, final, st = improve(inst, base_seq, time_limit=cfg.time_limit_seconds)
        out.search = SearchInfo(mode="improved", moves_tried=st.tried, moves_accepted=st.accepted,
                                passes=st.passes, seconds=st.seconds, stopped=st.stopped, trace=st.trace)
    else:
        seqs, final = base_seq, base
    out.kpis = _kpis(inst, final)
    out.violations = check(inst, final)

    ops = {o.key: o for j in inst.jobs.values() for o in j.ops}
    late_orders = {j.id for j in inst.jobs.values() if final.completion.get(j.id, 0.0) > j.due + 1e-9}
    for b in sorted(final.blocks, key=lambda b: (b.resource, b.unit, b.setup_start)):
        o = ops[b.key]
        out.ops.append(ScheduledOp(
            id=f"{b.key}/{b.sub}", key=b.key, order=o.order, seq=o.seq, sub=b.sub, product=o.product,
            group=o.group, resource=b.resource, unit=b.unit, qty=b.qty, setup_start=b.setup_start,
            run_start=b.run_start, end=b.end, setup_hours=b.setup_work, run_hours=b.run_work,
            setup_from=b.prev[1] if b.prev else None, late=o.order in late_orders))
    for j in sorted(inst.jobs.values(), key=lambda j: (j.due, j.id)):
        m = meta[j.id]
        c = final.completion[j.id]
        gr = math.ceil(gr_days(ds.location_product_by_key.get((m["location"], j.product))) - 1e-9)
        done_day = math.ceil(c / 24.0 - 1e-9)
        avail = s.planning_start + timedelta(days=done_day + gr)
        ready = max((final.parts.get(o.key, 0.0) for o in j.ops), default=0.0)
        came = []
        for sid, (prod, t) in m["from"].items():
            if t is None:
                t = inst.receive(sid, final.completion[sid], _gr(ds, meta[sid]))
            came.append(PartSupply(supply=sid, product=prod, available=t, scheduled=sid in inst.jobs))
        out.orders.append(ScheduledOrder(
            id=j.id, location=m["location"], product=j.product, group=j.ops[0].group, qty=m["qty"],
            release=j.release, due=j.due, completion=c, lateness_hours=c - j.due, tardy=j.id in late_orders,
            baseline_completion=base.completion[j.id], mrp_start_date=m["start"], mrp_due_date=m["due"],
            firm=m["firm"], parts_ready=ready, held_for_parts=sum(final.held.get(o.key, 0.0) for o in j.ops),
            parts_from=sorted((p for p in came if p.available > j.release + 1e-6), key=lambda p: -p.available),
            missing_parts=sorted(m["missing"]),
            finish_date=s.planning_start + timedelta(days=max(0, math.floor((c - 1e-9) / 24.0))),
            available_date=avail, days_late=max(0, done_day - int(j.due // 24))))

    span = max([cfg.horizon_days * 24.0, final.makespan, *(b.end for b in final.blocks)])
    out.span_hours = span
    for rid, r in sorted(inst.resources.items()):
        m = ds.resource_by_id[rid]
        bl = [b for b in final.blocks if b.resource == rid]
        wins = r.clock.windows(0.0, span)
        busy = sum(b.end - b.setup_start - _gaps(r.at(b.unit if r.finite else -1), b.setup_start, b.end) for b in bl)
        if r.finite:
            avail = sum(r.at(u).open_between(0.0, span) for u in range(r.units))
        else:
            avail = r.clock.open_between(0.0, span) * max(1, len(bl))
        out.resources.append(ScheduleResource(
            id=rid, name=m.name, kind=m.kind.value, units=r.units, finite=r.finite, efficiency=m.efficiency,
            windows=[[a, b] for a, b in wins], busy_hours=busy, setup_hours=sum(b.setup_work for b in bl),
            available_hours=avail, utilization=busy / avail if avail else 0.0,
            changeovers=sum(1 for b in bl if is_changeover(b, ops[b.key])),
            sequence=seqs.get(rid, [])))
    out.labour = _labour(ds, inst, final)
    out.ok = True
    return out


def _gaps(clk: ResourceClock, a: float, b: float) -> float:
    """Clock hours inside [a, b] that are outside shift windows (a job paused overnight or for a break)."""
    return (b - a) - clk.open_between(a, b)


def _gr(ds: Dataset, m: dict) -> float:
    return gr_days(ds.location_product_by_key.get((m["location"], m["product"])))
