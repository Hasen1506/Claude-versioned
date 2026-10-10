"""Roadmap PR A: status signals must not contradict each other.

The sales-order promise counted MRP planned receipts on the date MRP *wanted* them, ignoring that their components
arrive late (UX audit, Sales orders row: 40 pumps promised "on time" with zero stock and a 21-day motor while the plan
said 0% on time)."""
from __future__ import annotations

from scp.plan import run_mrp
from scp.promise import check_order, run_promise
from scp.model import DemandRecord

from .factory import base, demand, ds, lp


def _late_motor() -> dict:
    """Plant P makes A from 2×B + C; B (the motor) takes 21 days from the supplier and nothing is in stock. Customer
    C1 orders 40 A in 12 days."""
    d = base(horizon=56)
    d["locations"].append({"id": "C1", "type": "customer"})
    d["lanes"] = [{"id": "PC1", "origin": "P", "destination": "C1", "modes": [{"transit_days": 1}]}]
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 0
    d["purchasing_sources"][0]["lead_time_days"] = 21
    d["demand"] = [demand("C1", "A", "2026-01-17", 40, "sales_order", id="SO1")]
    return d


def test_promise_respects_component_lead_time_and_zero_stock():
    D = ds(_late_motor())
    plan = run_mrp(D)
    late = [o for o in plan.orders if o.product == "A" and str(getattr(o.kind, "value", o.kind)) == "make"]
    assert late and late[0].delay_days > 0          # the plan itself says the order is late
    o = run_promise(D).orders[0]
    assert o.status != "on_time"
    assert o.on_time == 0
    assert min(x.date for x in o.lines) >= late[0].projected_available_date


def test_check_of_a_new_order_agrees_with_the_plan():
    d = _late_motor()
    d["demand"] = []
    D = ds(d)
    r = check_order(D, DemandRecord(location="C1", product="A", date="2026-01-17", qty=40, kind="sales_order", id="N1"))
    o = r.checked
    assert o.status != "on_time" and o.on_time == 0


def test_a_feasible_planned_order_still_confirms_on_time():
    d = _late_motor()
    lp(d, "P", "B")["on_hand"] = 200          # the motor is in stock now: the plan is on time, so is the promise
    o = run_promise(ds(d)).orders[0]
    assert o.status == "on_time"


# ---- Setup checklist vs Data check ------------------------------------------------------------------------------
def _reverse_route() -> dict:
    """Plant P ships A to DC D, and someone saved the reverse route D → P on the wrong card: a loop."""
    d = base()
    d["locations"].append({"id": "D", "type": "dc"})
    d["lanes"] = [{"id": "PD", "origin": "P", "destination": "D", "modes": [{"transit_days": 2}]},
                  {"id": "DP", "origin": "D", "destination": "P", "modes": [{"transit_days": 2}]}]
    d["demand"] = [demand("D", "A", "2026-01-19", 10)]
    return d


def test_checklist_is_not_done_while_the_data_check_reports_circular_sourcing():
    from scp.validate import has_errors, validate
    from scp.validate.setup import checklist, ready
    D = ds(_reverse_route())
    issues = validate(D)
    assert any(i.code == "BOM_CYCLE" for i in issues) and has_errors(issues)
    items = checklist(D)
    supply = [i for i in items if i.step == "supply"]
    assert not any(i.status == "done" for i in supply)
    assert any(i.status == "todo" and "circle" in i.text for i in supply)
    assert not ready(items)


def test_checklist_supply_is_done_when_routes_flow_one_way():
    from scp.validate.setup import checklist
    d = _reverse_route()
    d["lanes"].pop()
    supply = [i for i in checklist(ds(d)) if i.step == "supply"]
    assert any(i.status == "done" for i in supply)


# ---- "why this date" -------------------------------------------------------------------------------------------
def test_why_this_date_names_the_part_the_order_waits_for():
    d = _late_motor()
    d["promising"] = {"confirm_beyond_rlt": False, "ctp": False}
    D = ds(d)
    make = next(o for o in run_mrp(D).orders if o.product == "A" and o.location == "P"
                and str(getattr(o.kind, "value", o.kind)) == "make")
    assert make.limited_by == "B" and make.limited_until is not None
    assert make.limited_until < make.projected_available_date
    o = run_promise(D).orders[0]
    assert [w.kind for w in o.why] == ["component", "planned", "ship"]
    part, built, ship = o.why
    assert part.product == "B" and part.date == make.limited_until and part.ref == make.id
    assert built.ref == make.id and built.date == make.projected_available_date
    assert ship.ref == "PC1" and ship.date == max(x.date for x in o.lines)


def test_why_this_date_beyond_the_lead_time_and_by_ctp():
    o = run_promise(ds(_late_motor())).orders[0]          # beyond RLT is confirmable by default
    assert [w.kind for w in o.why] == ["rlt", "ship"] and "replenishment lead time" in o.why[0].note
    d = _late_motor()
    d["promising"] = {"confirm_beyond_rlt": False, "ctp": True, "include_planned_orders": False}
    o = run_promise(ds(d)).orders[0]
    assert o.ctp and [w.kind for w in o.why][-1] == "ship"
    assert [w.note for w in o.why if w.kind == "ctp"] == [s.note or s.kind for s in o.ctp]
