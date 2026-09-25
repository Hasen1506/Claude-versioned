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
    resource: str
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
    return good_qty / (1.0 - ps.assembly_scrap)


def _op_workdays(ds: Dataset, ps: ProductionSource, qty_started: float) -> list[tuple[int, float, float, float]]:
    """(seq, duration in workdays, machine hours, labor hours) per operation."""
    out = []
    for op in ps.operations:
        res = ds.resource_by_id.get(op.resource)
        hours = op.setup_hours + op.run_hours_per_unit * qty_started
        units = min(op.parallel_units or res.units, res.units) if res else 1
        rate = res.hours_per_workday_per_unit * units if res else 8.0
        out.append((op.seq, hours / rate if rate > 0 else 0.0, hours, op.labor_hours_per_unit * qty_started))
    return out


def production_workdays(ds: Dataset, ps: ProductionSource, good_qty: float) -> float:
    if ps.fixed_lead_time_workdays is not None:
        return ps.fixed_lead_time_workdays
    q = started_qty(ps, good_qty)
    return sum(math.ceil(d - 1e-9) + op.queue_workdays
               for (_, d, _, _), op in zip(_op_workdays(ds, ps, q), ps.operations, strict=True))


def schedule_make(ds: Dataset, ps: ProductionSource, good_qty: float, *, available: date | None = None,
                  start: date | None = None) -> Schedule:
    """Backward from ``available`` or forward from ``start`` (exactly one must be given)."""
    cal = location_calendar(ds, ps.location)
    gr = gr_days(ds.location_product_by_key.get((ps.location, ps.product)))
    q = started_qty(ps, good_qty)
    durs = _op_workdays(ds, ps, q)
    ops_by_seq = {op.seq: op for op in ps.operations}
    windows: list[OpWindow] = []
    if ps.fixed_lead_time_workdays is not None or not ps.operations:
        lt = production_workdays(ds, ps, good_qty)
        if available is not None:
            due = available - _days(gr)
            st = cal.add_workdays(cal.prev_workday(due), -lt) if lt > 0 else due
        else:
            st = cal.next_workday(start)
            due = cal.add_workdays(st, lt) if lt > 0 else st
        # routing present but lead time fixed: spread operations evenly over the fixed window
        if ps.operations:
            span = max(1, cal.workdays_between(st, due))
            cur = st
            per = span / len(ps.operations)
            for i, (seq, _, mh, lh) in enumerate(durs):
                nxt = cal.add_workdays(st, round(per * (i + 1))) if i < len(durs) - 1 else due
                op = ops_by_seq[seq]
                windows.append(OpWindow(seq, op.resource, op.labor_resource, cur, max(nxt, cur), mh, lh))
                cur = max(nxt, cur)
        return Schedule(st, due, due + _days(gr), windows,
                        component_dates=_component_dates(ps, windows, st))
    if available is not None:
        due = available - _days(gr)
        cursor = due
        for (seq, d, mh, lh) in reversed(durs):
            op = ops_by_seq[seq]
            op_end = cal.add_workdays(cursor, -op.queue_workdays) if op.queue_workdays else cursor
            n = math.ceil(d - 1e-9)
            op_start = cal.add_workdays(cal.prev_workday(op_end - timedelta(days=1)), -(n - 1)) if n > 0 else op_end
            windows.append(OpWindow(seq, op.resource, op.labor_resource, op_start, op_end, mh, lh))
            cursor = op_start
        windows.reverse()
        st = windows[0].start
    else:
        st = cal.next_workday(start)
        cursor = st
        for (seq, d, mh, lh) in durs:
            op = ops_by_seq[seq]
            n = math.ceil(d - 1e-9)
            op_start = cal.next_workday(cursor)
            op_end = cal.add_workdays(op_start, n - 1) + timedelta(days=1) if n > 0 else op_start
            windows.append(OpWindow(seq, op.resource, op.labor_resource, op_start, op_end, mh, lh))
            cursor = cal.add_workdays(cal.next_workday(op_end), op.queue_workdays) if op.queue_workdays else op_end
        due = cursor
    return Schedule(st, due, due + _days(gr), windows, component_dates=_component_dates(ps, windows, st))


def _component_dates(ps: ProductionSource, windows: list[OpWindow], start: date) -> dict[str, date]:
    by_seq = {w.seq: w.start for w in windows}
    first = windows[0].start if windows else start
    return {c.product: by_seq.get(c.operation, first) if c.operation else first for c in ps.components}


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
