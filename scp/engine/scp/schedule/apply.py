"""Schedule dates back into the plan (S/4 PP/DS: fixing the scheduled orders so MRP keeps their dates).

Every order the schedule sequenced becomes a production order dated by the schedule: it starts the day its first step
sets up, and it is due the day after its last step ends (the same "due" the plan uses: goods are there from that day,
plus goods-receipt days). A planned order is firmed; a production order already released is re-dated. Each part is
reserved for the day the step that uses it starts. The receipt is marked ``scheduled``, so re-planning counts it where
it is needed and reports a late one (``SCHEDULE_LATE``) instead of adding an order in front of it; promising and
finance read the same dates.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from ..actuals.firm import _next_numbers
from ..model import Dataset, ReceiptKind, Reservation, ScheduledReceipt
from ..model.common import Out
from ..plan import run_mrp
from ..plan.structure import needs
from .result import ScheduledOp, ScheduleResult
from .run import run_schedule


class AppliedOrder(Out):
    order: str                  # the scheduled order (planned order id, or the production order's own id)
    receipt: str                # the production order that now carries the dates
    product: str
    location: str
    qty: float
    start_date: date
    due_date: date
    was_start: date | None
    was_due: date
    new: bool                   # a planned order firmed now (else a released order re-dated)


class ApplyReport(Out):
    ok: bool
    applied: list[AppliedOrder] = []
    skipped: dict[str, str] = {}   # order id → why it was left alone


def _day(origin: date, hours: float, *, up: bool) -> date:
    days = math.ceil(hours / 24.0 - 1e-9) if up else math.floor(hours / 24.0 + 1e-9)
    return origin + timedelta(days=max(0, days))


def apply_schedule(ds: Dataset, sequence: dict[str, list[str]] | None = None, ids: list[str] | None = None,
                   hold: dict[str, float] | None = None) -> tuple[Dataset, ApplyReport]:
    """Date the orders by the schedule. Pass the sequence (and holds) the schedule shows to fix exactly that schedule;
    without them the schedule is run again under the settings."""
    plan = run_mrp(ds)
    sch = run_schedule(ds, sequence, plan, hold)
    rep = ApplyReport(ok=False)
    if not plan.ok or not sch.ok:
        return ds, rep
    return apply_result(ds, plan, sch, ids)


def apply_result(ds: Dataset, plan, sch: ScheduleResult, ids: list[str] | None = None) -> tuple[Dataset, ApplyReport]:
    origin = ds.settings.planning_start
    rep = ApplyReport(ok=True)
    wanted = set(ids) if ids is not None else None
    planned = {o.id: o for o in plan.orders}
    firm = {r.id: r for r in ds.receipts}
    ops: dict[str, list[ScheduledOp]] = defaultdict(list)
    for op in sch.ops:
        ops[op.order].append(op)
    reqs: dict[str, list] = defaultdict(list)
    for rq in plan.requirements:
        if rq.parent_order and rq.kind == "dependent":
            reqs[rq.parent_order].append(rq)
    num = _next_numbers(ds)
    receipts = list(ds.receipts)
    index = {r.id: i for i, r in enumerate(receipts)}

    for so in sch.orders:
        if wanted is not None and so.id not in wanted:
            continue
        mine = ops.get(so.id, [])
        if not mine:
            rep.skipped[so.id] = "no scheduled steps"
            continue
        start = _day(origin, min(o.setup_start for o in mine), up=False)
        due = _day(origin, so.completion, up=True)
        rc = firm.get(so.id)
        ps = ds.production_source_by_id.get(rc.source if rc else planned[so.id].source_id if so.id in planned else "")
        if ps is None:
            rep.skipped[so.id] = "its production source is gone"
            continue
        used_on = _part_days(ds, ps, start, mine, origin)
        own = {op.seq: op.resource for op in ps.operations}
        steps = {o.seq: o.resource for o in mine if o.resource != own.get(o.seq)}

        if rc is not None:
            rvs = [rv.model_copy(update={"date": used_on(rv.product)}) if rv.location == rc.location else rv
                   for rv in rc.reservations]
            receipts[index[rc.id]] = rc.model_copy(update={"start_date": start, "due_date": due, "reservations": rvs,
                                                           "step_resources": steps, "scheduled": True})
            rep.applied.append(AppliedOrder(order=so.id, receipt=rc.id, product=rc.product, location=rc.location,
                                            qty=rc.qty, start_date=start, due_date=due, was_start=rc.start_date,
                                            was_due=rc.due_date, new=False))
            continue
        o = planned.get(so.id)
        if o is None:
            rep.skipped[so.id] = "not in the current plan (re-run supply planning)"
            continue
        if not o.convertible:
            rep.skipped[so.id] = "forecast-driven supply of an assemble-to-order product: firmed by the sales order"
            continue
        num["PRD"] += 1
        rid = f"PRD-{num['PRD']:05d}"
        rvs = [Reservation(location=r.location, product=r.product, date=used_on(r.product), qty=r.qty)
               for r in reqs.get(o.id, [])]
        receipts.append(ScheduledReceipt(id=rid, kind=ReceiptKind.PRODUCTION, location=o.location, product=o.product,
                                         qty=o.qty, due_date=due, start_date=start, source=o.source_id,
                                         reservations=rvs, step_resources=steps, scheduled=True))
        rep.applied.append(AppliedOrder(order=so.id, receipt=rid, product=o.product, location=o.location, qty=o.qty,
                                        start_date=start, due_date=due, was_start=o.start_date, was_due=o.due_date,
                                        new=True))
    if wanted is not None:
        for oid in sorted(wanted - {a.order for a in rep.applied} - set(rep.skipped)):
            rep.skipped[oid] = "not on the schedule"
    return ds.model_copy(update={"receipts": receipts}), rep


def _part_days(ds: Dataset, ps, start: date, mine: list[ScheduledOp], origin: date):
    """The day each part is used: the day the step that consumes it starts (a part for a step done outside, or
    after the last scheduled step, goes to the next scheduled step, else the last)."""
    step_of = {n.product: n.operation for n in needs(ds, ps, start)}
    first = {}
    for o in mine:
        first[o.seq] = min(first.get(o.seq, o.setup_start), o.setup_start)
    seqs = sorted(first)

    def used_on(product: str) -> date:
        seq = step_of.get(product)
        s = next((x for x in seqs if seq is None or x >= seq), seqs[-1])
        return _day(origin, first[s], up=False)
    return used_on


__all__ = ["AppliedOrder", "ApplyReport", "apply_result", "apply_schedule"]
