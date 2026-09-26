"""Lead-time model and order scheduling (S/4 guide §17.1 "where lead time lives").

Date semantics of every planned order:

* ``start_date``      — PO placed / production started / goods shipped
* ``due_date``        — goods physically arrive at (or finish in) the receiving location
* ``available_date``  — ``due_date`` + GR processing: usable for requirements (the netting date)

Buy:      start --supplier lead_time_days--> dispatch --lane transit--> due --GR--> available
          (the order is placed on a working day of the receiving location, whose buyers place it:
          backward scheduling moves it earlier, so the goods can arrive before they are needed, never after)
Transfer: start (ship at origin) --lane transit--> due --GR--> available
Make:     start --operations (working days of the plant calendar)--> due --GR--> available
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from ..model import Calendar, Dataset, LocationProduct, ProductionSource, TransportLane
from ..network import SupplyOption
from ..time import WorkCalendar
from ..time.capacity import day_capacity
from .structure import entering, needs, started_factor

DEFAULT_CALENDAR = Calendar(id="SYS-MON-FRI", name="Mon–Fri", workdays=[0, 1, 2, 3, 4])


def location_calendar(ds: Dataset, loc_id: str) -> WorkCalendar:
    loc = ds.location_by_id.get(loc_id)
    cal_id = (loc.calendar if loc else None) or ds.settings.default_calendar
    return WorkCalendar(ds.calendar_by_id.get(cal_id) if cal_id else DEFAULT_CALENDAR)


def resource_calendar(ds: Dataset, resource_id: str) -> WorkCalendar:
    r = ds.resource_by_id[resource_id]
    if r.calendar and r.calendar in ds.calendar_by_id:
        return WorkCalendar(ds.calendar_by_id[r.calendar])
    return location_calendar(ds, r.location)


def supplier_lane(ds: Dataset, supplier: str, location: str, product: str) -> TransportLane | None:
    """The freight lane a purchase travels on (first matching by priority), if modelled."""
    lanes = [ln for ln in ds.lanes
             if ln.origin == supplier and ln.destination == location and ln.carries(product)]
    return min(lanes, key=lambda ln: (ln.priority, ln.id)) if lanes else None


def gr_days(lp: LocationProduct | None) -> float:
    return lp.gr_processing_days if lp else 0.0


def _days(x: float) -> timedelta:
    return timedelta(days=math.ceil(x - 1e-9))


# ---------------------------------------------------------------------------------------------
@dataclass
class OpWindow:
    seq: int
    resource: str | None     # None: done outside by a supplier
    labor_resource: str | None
    start: date          # first working day of the operation
    end: date            # exclusive
    machine_hours: float
    labor_hours: float


@dataclass
class Schedule:
    start_date: date
    due_date: date
    available_date: date
    ops: list[OpWindow]
    ship_date: date | None = None      # transfer/purchase dispatch
    component_dates: dict[str, date] | None = None


def started_qty(ps: ProductionSource, good_qty: float) -> float:
    """Units an order starts to end with ``good_qty`` good ones (step scrap and whole-order scrap)."""
    return good_qty * started_factor(ps)


def _op_workdays(ds: Dataset, ps: ProductionSource, good_qty: float) -> list[tuple[int, float, float, float]]:
    """(seq, duration in workdays, machine hours, labor hours) per operation, each step sized for the units
    entering it. A step done outside by a supplier takes its agreed working days and loads nothing here."""
    enter = entering(ps)
    out = []
    for op in ps.operations:
        q = good_qty * enter[op.seq]
        if op.subcontract is not None:
            out.append((op.seq, op.subcontract.workdays, 0.0, 0.0))
            continue
        res = ds.resource_by_id.get(op.resource or "")
        hours = op.setup_hours + op.run_hours_per_unit * q
        units = min(op.parallel_units or res.units, res.units) if res else 1
        rate = res.hours_per_workday_per_unit * units if res else 8.0
        out.append((op.seq, hours / rate if rate > 0 else 0.0, hours, op.labor_hours_per_unit * q))
    return out


def _shaped(ds: Dataset, rid: str | None) -> bool:
    r = ds.resource_by_id.get(rid) if rid else None
    return bool(r and (r.shifts or r.capacity_changes))


def _span(ds: Dataset, op, d: float, hours: float, cal: WorkCalendar, day: date, forward: bool) -> int:
    """Working days of ``cal`` an operation occupies, from ``day`` forward (or ending on ``day`` backward). A
    resource with the same capacity every working day takes ceil(duration); one with named shifts or capacity
    changes is walked day by day, so a shutdown week or a Saturday half shift lengthens or shortens the
    operation where it falls."""
    if op.subcontract is not None or not _shaped(ds, op.resource):
        return math.ceil(d - 1e-9)
    if hours <= 1e-9:
        return 0
    res = ds.resource_by_id[op.resource]
    rcal = resource_calendar(ds, op.resource)
    left, n, cur = hours, 0, day
    for _ in range(3660):
        if cal.is_workday(cur):
            n += 1
            dc = day_capacity(res, rcal, cur)
            units = min(op.parallel_units or dc.units, dc.units)
            left -= dc.clock_hours * dc.efficiency * units
            if left <= 1e-9:
                return n
        cur += timedelta(days=1 if forward else -1)
    return n


def _margins(ds: Dataset, ps: ProductionSource) -> tuple[float, float]:
    lp = ds.location_product_by_key.get((ps.location, ps.product))
    return (lp.float_before_workdays, lp.float_after_workdays) if lp else (0.0, 0.0)


def production_workdays(ds: Dataset, ps: ProductionSource, good_qty: float) -> float:
    before, after = _margins(ds, ps)
    if ps.fixed_lead_time_workdays is not None:
        return ps.fixed_lead_time_workdays + before + after
    durs = _op_workdays(ds, ps, good_qty)
    days = [math.ceil(d - 1e-9) for _, d, _, _ in durs]
    total = 0.0
    for i, op in enumerate(ps.operations):
        nxt = ps.operations[i + 1] if i + 1 < len(ps.operations) else None
        if op.send_ahead_qty and nxt is not None:
            # overlapped: the next step starts after the send-ahead batch; it still ends after this step
            share = _share(op, good_qty, ps)
            total += max(math.ceil(durs[i][1] * share - 1e-9), days[i] - days[i + 1]) + op.queue_workdays
        else:
            total += days[i] + op.queue_workdays
    return total + before + after


def _share(op, good_qty: float, ps: ProductionSource) -> float:
    q = good_qty * entering(ps)[op.seq]
    return min(1.0, op.send_ahead_qty / q) if op.send_ahead_qty and q > 0 else 1.0


def _forward(ds: Dataset, ps: ProductionSource, good_qty: float, cal: WorkCalendar, st: date,
             durs: list[tuple[int, float, float, float]]) -> tuple[list[OpWindow], date]:
    """Operations one after the other from ``st``; an overlapped step lets the next one start once its
    send-ahead batch (and the queue after it) is through, but the next one never ends before it does."""
    windows: list[OpWindow] = []
    cursor = st
    prev: tuple | None = None    # (op, start, d)
    for (seq, d, mh, lh), op in zip(durs, ps.operations, strict=True):
        n = _span(ds, op, d, mh, cal, cal.next_workday(cursor), True)
        op_start = cal.next_workday(cursor)
        min_end = None
        if prev is not None and prev[0].send_ahead_qty:
            pop, pstart, pd = prev
            share = _share(pop, good_qty, ps)
            batch = cal.add_workdays(pstart, math.ceil(pd * share - 1e-9))
            early = cal.add_workdays(cal.next_workday(batch), pop.queue_workdays) if pop.queue_workdays else batch
            op_start = min(op_start, cal.next_workday(early))
            n = _span(ds, op, d, mh, cal, op_start, True)
            tail = math.ceil(d * share - 1e-9)
            min_end = cal.add_workdays(cal.next_workday(cursor), tail - 1) + timedelta(days=1) if tail > 0 else cursor
        op_end = cal.add_workdays(op_start, n - 1) + timedelta(days=1) if n > 0 else op_start
        if min_end is not None and min_end > op_end:
            op_end = min_end
        windows.append(OpWindow(seq, op.resource, op.labor_resource, op_start, op_end, mh, lh))
        cursor = cal.add_workdays(cal.next_workday(op_end), op.queue_workdays) if op.queue_workdays else op_end
        prev = (op, op_start, d)
    return windows, cursor


def _backward(ds: Dataset, ps: ProductionSource, cal: WorkCalendar, due: date,
              durs: list[tuple[int, float, float, float]]) -> list[OpWindow]:
    windows: list[OpWindow] = []
    cursor = due
    ops_by_seq = {op.seq: op for op in ps.operations}
    for (seq, d, mh, lh) in reversed(durs):
        op = ops_by_seq[seq]
        op_end = cal.add_workdays(cursor, -op.queue_workdays) if op.queue_workdays else cursor
        n = _span(ds, op, d, mh, cal, cal.prev_workday(op_end - timedelta(days=1)), False)
        op_start = cal.add_workdays(cal.prev_workday(op_end - timedelta(days=1)), -(n - 1)) if n > 0 else op_end
        windows.append(OpWindow(seq, op.resource, op.labor_resource, op_start, op_end, mh, lh))
        cursor = op_start
    windows.reverse()
    return windows


def schedule_make(ds: Dataset, ps: ProductionSource, good_qty: float, *, available: date | None = None,
                  start: date | None = None) -> Schedule:
    """Backward from ``available`` or forward from ``start`` (exactly one must be given).

    The order's start is its release: the scheduling margin's float before production comes first, then the
    operations, then the float after production, then goods-receipt processing. Components are needed when
    the step that consumes them starts."""
    cal = location_calendar(ds, ps.location)
    gr = gr_days(ds.location_product_by_key.get((ps.location, ps.product)))
    before, after = _margins(ds, ps)
    durs = _op_workdays(ds, ps, good_qty)
    ops_by_seq = {op.seq: op for op in ps.operations}
    windows: list[OpWindow] = []
    if ps.fixed_lead_time_workdays is not None or not ps.operations:
        lt = ps.fixed_lead_time_workdays or 0.0
        if available is not None:
            due = available - _days(gr)
            end = cal.add_workdays(due, -after) if after else due
            prod = cal.add_workdays(cal.prev_workday(end), -lt) if lt > 0 else end
            st = cal.add_workdays(prod, -before) if before else prod
        else:
            st = cal.next_workday(start)
            prod = cal.add_workdays(st, before) if before else st
            end = cal.add_workdays(prod, lt) if lt > 0 else prod
            due = cal.add_workdays(end, after) if after else end
        # routing present but lead time fixed: spread operations evenly over the fixed window
        if ps.operations:
            span = max(1, cal.workdays_between(prod, end))
            cur = prod
            per = span / len(ps.operations)
            for i, (seq, _, mh, lh) in enumerate(durs):
                nxt = cal.add_workdays(prod, round(per * (i + 1))) if i < len(durs) - 1 else end
                op = ops_by_seq[seq]
                windows.append(OpWindow(seq, op.resource, op.labor_resource, cur, max(nxt, cur), mh, lh))
                cur = max(nxt, cur)
        return Schedule(st, due, due + _days(gr), windows,
                        component_dates=_component_dates(ds, ps, windows, prod))
    overlapped = any(op.send_ahead_qty for op in ps.operations[:-1])
    if available is not None:
        due = available - _days(gr)
        end = cal.add_workdays(due, -after) if after else due
        windows = _backward(ds, ps, cal, end, durs)
        if overlapped:
            # overlap only shortens: from the plain backward start, move later while the order still ends in time
            st0 = windows[0].start
            for _ in range(400):
                nxt = cal.add_workdays(st0, 1)
                w2, e2 = _forward(ds, ps, good_qty, cal, nxt, durs)
                if e2 > end:
                    break
                st0 = nxt
            windows, _ = _forward(ds, ps, good_qty, cal, st0, durs)
        prod = windows[0].start
        st = cal.add_workdays(prod, -before) if before else prod
    else:
        st = cal.next_workday(start)
        prod = cal.add_workdays(st, before) if before else st
        windows, end = _forward(ds, ps, good_qty, cal, prod, durs)
        due = cal.add_workdays(cal.next_workday(end), after) if after else end
    return Schedule(st, due, due + _days(gr), windows, component_dates=_component_dates(ds, ps, windows, prod))


def _component_dates(ds: Dataset, ps: ProductionSource, windows: list[OpWindow], start: date) -> dict[str, date]:
    by_seq = {w.seq: w.start for w in windows}
    first = windows[0].start if windows else start
    return {n.product: by_seq.get(n.operation, first) if n.operation else first for n in needs(ds, ps)}


def schedule_buy(ds: Dataset, src_id: str, *, available: date | None = None, start: date | None = None) -> Schedule:
    pu = ds.purchasing_source_by_id[src_id]
    gr = gr_days(ds.location_product_by_key.get((pu.location, pu.product)))
    lane = supplier_lane(ds, pu.supplier, pu.location, pu.product)
    transit = lane.planning_mode.transit_days if lane else 0.0
    buyer = location_calendar(ds, pu.location)
    if available is not None:
        latest = available - _days(gr) - _days(transit) - _days(pu.lead_time_days)
        st = buyer.prev_workday(latest)
    else:
        st = buyer.next_workday(start)
    ship = st + _days(pu.lead_time_days)
    due = ship + _days(transit)
    return Schedule(st, due, due + _days(gr), [], ship_date=ship)


def schedule_transfer(ds: Dataset, lane_id: str, product: str, *, available: date | None = None,
                      start: date | None = None) -> Schedule:
    ln = ds.lane_by_id[lane_id]
    gr = gr_days(ds.location_product_by_key.get((ln.destination, product)))
    transit = ln.planning_mode.transit_days
    ship_cal = location_calendar(ds, ln.origin)  # goods leave on the origin's working days
    if available is not None:
        st = ship_cal.prev_workday(available - _days(gr) - _days(transit))
    else:
        st = ship_cal.next_workday(start)
    due = st + _days(transit)
    return Schedule(st, due, due + _days(gr), [], ship_date=st)


def schedule(ds: Dataset, opt: SupplyOption, qty: float, *, available: date | None = None,
             start: date | None = None) -> Schedule:
    if opt.kind == "make":
        return schedule_make(ds, ds.production_source_by_id[opt.source_id], qty, available=available, start=start)
    if opt.kind == "buy":
        return schedule_buy(ds, opt.source_id, available=available, start=start)
    return schedule_transfer(ds, opt.source_id, opt.node[1], available=available, start=start)


# ---------------------------------------------------------------------------------------------
def nominal_lead_time_days(ds: Dataset, opt: SupplyOption, qty: float = 1.0) -> float | None:
    """Calendar-day replenishment lead time of an option (for safety stock and checks)."""
    loc, prod = opt.node
    gr = gr_days(ds.location_product_by_key.get(opt.node))
    if opt.kind == "buy":
        pu = ds.purchasing_source_by_id.get(opt.source_id)
        if not pu:
            return None
        lane = supplier_lane(ds, pu.supplier, loc, prod)
        return pu.lead_time_days + (lane.planning_mode.transit_days if lane else 0.0) + gr
    if opt.kind == "transfer":
        ln = ds.lane_by_id.get(opt.source_id)
        return (ln.planning_mode.transit_days + gr) if ln else None
    ps = ds.production_source_by_id.get(opt.source_id)
    if not ps:
        return None
    cal = location_calendar(ds, loc)
    wd = production_workdays(ds, ps, qty)
    per_week = max(1, sum(1 for d in range(7) if d in cal._workdays))  # noqa: SLF001 — same package
    return wd * 7.0 / per_week + gr


def lead_time_std_days(ds: Dataset, opt: SupplyOption) -> float:
    loc, prod = opt.node
    if opt.kind == "buy":
        pu = ds.purchasing_source_by_id.get(opt.source_id)
        if not pu:
            return 0.0
        lane = supplier_lane(ds, pu.supplier, loc, prod)
        lane_sd = lane.planning_mode.transit_std_days if lane else 0.0
        return math.sqrt(pu.lead_time_std_days ** 2 + lane_sd ** 2)
    if opt.kind == "transfer":
        ln = ds.lane_by_id.get(opt.source_id)
        return ln.planning_mode.transit_std_days if ln else 0.0
    return 0.0
