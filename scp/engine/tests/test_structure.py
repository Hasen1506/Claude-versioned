"""Phase B: BOM and routing depth, and the MRP views of a material at a plant. Each rule is checked
against a quantity or date worked out by hand, in every module that uses it (MRP, lead time, costing,
S&OP, finance, the scheduler)."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from scp.finance import run_finance
from scp.model import ProductionSource
from scp.network import build_graph
from scp.plan import run_mrp
from scp.plan.costing import conversion_unit_cost, roll_up
from scp.plan.leadtime import schedule_make, started_qty
from scp.plan.structure import entering, needs
from scp.schedule import run_schedule
from scp.sop import run_sop

from .factory import base, demand, ds, lp


def dep(plan, product: str) -> float:
    return sum(r.qty for r in plan.requirements if r.product == product and r.kind == "dependent")


def made(plan, product: str) -> list:
    return [o for o in plan.orders if o.product == product and o.kind == "make"]


# ---- the model refuses what cannot be ----------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    {"components": [{"product": "B", "qty": 1}, {"product": "B", "qty": 2}]},
    {"components": [{"product": "B", "qty": 1, "valid_to": "2026-02-01"},
                    {"product": "B", "qty": 2, "valid_from": "2026-01-20"}]},
    {"co_products": [{"product": "A", "qty": 1}]},
    {"components": [{"product": "B", "qty": 1}], "co_products": [{"product": "B", "qty": 1}]},
    {"co_products": [{"product": "B", "qty": 1, "cost_share": 0.7}, {"product": "C", "qty": 1, "cost_share": 0.4}]},
    {"operations": [{"seq": 10}]},
    {"operations": [{"seq": 10, "resource": "M1", "subcontract": {"supplier": "S", "workdays": 2}}]},
    {"operations": [{"seq": 10, "resource": "M1", "alternatives": ["M1"]}]},
])
def test_impossible_structures_are_refused(bad):
    with pytest.raises(ValidationError):
        ProductionSource.model_validate({"id": "X", "location": "P", "product": "A", **bad})


def test_an_engineering_change_may_follow_the_old_line():
    ps = ProductionSource.model_validate({"id": "X", "location": "P", "product": "A", "components": [
        {"product": "B", "qty": 1, "valid_to": "2026-01-15"}, {"product": "B", "qty": 2, "valid_from": "2026-01-16"}]})
    assert len(ps.components) == 2


# ---- BOM ---------------------------------------------------------------------------------------------
def _made_to_order(**ps) -> dict:
    d = base(horizon=42)
    d["production_sources"][0].update(ps)
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 0
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    return d


def test_engineering_change_switches_the_part_on_its_date():
    d = _made_to_order(components=[{"product": "B", "qty": 2, "valid_to": "2026-01-18", "change": "ECN-7"},
                                   {"product": "C", "qty": 1, "valid_from": "2026-01-19"}])
    d["demand"] = [demand("P", "A", "2026-01-10", 10), demand("P", "A", "2026-02-06", 10)]
    plan = run_mrp(ds(d))
    early, late = sorted(made(plan, "A"), key=lambda o: o.start_date)
    assert early.start_date < date(2026, 1, 19) <= late.start_date
    reqs = {(r.parent_order, r.product): r.qty for r in plan.requirements if r.kind == "dependent"}
    assert reqs == {(early.id, "B"): 20, (late.id, "C"): 10}


def test_fixed_quantity_parts_are_issued_once_per_order():
    d = _made_to_order(components=[{"product": "B", "qty": 2}, {"product": "C", "qty": 5, "fixed_qty": True}])
    d["demand"] = [demand("P", "A", "2026-01-12", 30), demand("P", "A", "2026-02-02", 7)]
    plan = run_mrp(ds(d))
    assert len(made(plan, "A")) == 2
    assert dep(plan, "B") == pytest.approx(2 * 37)
    assert dep(plan, "C") == pytest.approx(10)        # 5 per order, two orders


def test_a_phantom_is_never_planned_its_parts_go_straight_into_the_parent():
    d = _made_to_order(components=[{"product": "SUB", "qty": 2, "operation": 20}],
                       operations=[{"seq": 10, "resource": "M1", "run_hours_per_unit": 0.1},
                                   {"seq": 20, "resource": "M1", "run_hours_per_unit": 0.1}])
    d["products"].append({"id": "SUB", "type": "SFG"})
    d["production_sources"].append({"id": "PV-SUB", "location": "P", "product": "SUB", "output_qty": 4,
                                    "fixed_lead_time_workdays": 1,
                                    "components": [{"product": "B", "qty": 4}, {"product": "C", "qty": 3, "fixed_qty": True}]})
    d["location_products"].append({"location": "P", "product": "SUB", "phantom": True})
    d["demand"] = [demand("P", "A", "2026-01-20", 10)]
    ds_ = ds(d)
    ups = {u for o in build_graph(ds_).options[("P", "A")] for u in o.upstream}
    assert ups == {("P", "B"), ("P", "C")}                       # SUB is passed through
    plan = run_mrp(ds_)
    assert not made(plan, "SUB") and dep(plan, "SUB") == 0
    assert dep(plan, "B") == pytest.approx(10 * 2 * 4 / 4)       # 2 SUB per A, 1 B per SUB
    assert dep(plan, "C") == pytest.approx(3)                    # the phantom's per-order part, once
    a = made(plan, "A")[0]
    op20 = next(w for w in schedule_make(ds_, ds_.production_source_by_id["PV-A"], a.qty,
                                         available=a.available_date).ops if w.seq == 20)
    r = next(r for r in plan.requirements if r.product == "B")
    assert r.date == op20.start                                  # needed at the parent's step that used SUB
    # a phantom nobody makes here is planned as an ordinary part (and the data check says so)
    d["production_sources"] = d["production_sources"][:1]
    d["purchasing_sources"].append({"id": "PIR-SUB", "supplier": "S", "product": "SUB", "location": "P", "price": 3,
                                    "lead_time_days": 2})
    ordinary = run_mrp(ds(d))
    assert dep(ordinary, "SUB") == 20 and dep(ordinary, "B") == 0


def test_step_scrap_makes_earlier_steps_and_their_parts_handle_more():
    d = _made_to_order(components=[{"product": "B", "qty": 1, "operation": 10}, {"product": "C", "qty": 1, "operation": 20}],
                       operations=[{"seq": 10, "resource": "M1", "run_hours_per_unit": 0.1, "scrap": 0.2},
                                   {"seq": 20, "resource": "M1", "run_hours_per_unit": 0.1, "scrap": 0.5}],
                       assembly_scrap=0.0)
    d["demand"] = [demand("P", "A", "2026-01-26", 40)]
    ds_ = ds(d)
    ps = ds_.production_source_by_id["PV-A"]
    assert entering(ps) == {10: pytest.approx(2.5), 20: pytest.approx(2.0)}   # 40 good ← 80 into step 20 ← 100 started
    assert started_qty(ps, 40) == pytest.approx(100)
    plan = run_mrp(ds_)
    assert dep(plan, "B") == pytest.approx(100) and dep(plan, "C") == pytest.approx(80)
    # 100 × 0.1 h + 80 × 0.1 h of machine time at 100/h
    assert conversion_unit_cost(ds_, "PV-A") == pytest.approx((2.5 * 0.1 + 2.0 * 0.1) * 100)
    load = sum(b.load_hours for r in plan.resources if r.resource == "M1" for b in r.buckets)
    assert load == pytest.approx(10 + 8)


def _by_product(share: float) -> dict:
    d = _made_to_order(co_products=[{"product": "BYP", "qty": 0.5, "cost_share": share}])
    d["products"].append({"id": "BYP", "type": "FG"})
    d["purchasing_sources"].append({"id": "PIR-BYP", "supplier": "S", "product": "BYP", "location": "P",
                                    "price": 1, "lead_time_days": 2})
    d["demand"] = [demand("P", "A", "2026-01-20", 40), demand("P", "BYP", "2026-01-30", 30)]
    return d


def test_co_products_arrive_with_the_run_and_only_the_rest_is_bought():
    plan = run_mrp(ds(_by_product(0.0)))
    a = made(plan, "A")
    assert sum(o.qty for o in a) == 40
    buys = [o for o in plan.orders if o.product == "BYP"]
    assert sum(o.qty for o in buys) == pytest.approx(10)          # 20 come from the run, 10 bought
    pegs = [p for p in plan.pegs if p.supply_kind == "co_product"]
    assert sum(p.qty for p in pegs) == pytest.approx(20) and {p.supply_id for p in pegs} == {a[0].id}
    node = next(n for n in plan.nodes if n.product == "BYP")
    assert node.llc > next(n for n in plan.nodes if n.product == "A").llc   # planned after its main product


def test_a_run_s_cost_is_shared_with_its_co_products_and_the_books_still_close():
    raw = _by_product(0.25)
    raw["purchasing_sources"] = [p for p in raw["purchasing_sources"] if p["id"] != "PIR-BYP"]
    raw["demand"][1]["qty"] = 15
    d = ds(raw)
    val = roll_up(d, build_graph(d))
    run_cost = 2 * val.unit_value[("P", "B")] + val.unit_value[("P", "C")] + conversion_unit_cost(d, "PV-A")
    assert val.unit_value[("P", "A")] == pytest.approx(run_cost * 0.75)
    assert val.unit_value[("P", "BYP")] == pytest.approx(run_cost * 0.25 / 0.5)
    plan = run_mrp(d)
    rec = run_finance(d, plan).reconciliation
    assert rec.reconciled
    for ln in rec.lines:
        assert ln.served + ln.unabsorbed == pytest.approx(ln.plan, rel=1e-9, abs=1e-6)
    sop = run_sop(d)
    assert sop.ok


# ---- routing -----------------------------------------------------------------------------------------
def _routing(*ops) -> dict:
    d = base(horizon=42, workdays=[0, 1, 2, 3, 4])
    d["production_sources"][0].pop("fixed_lead_time_workdays")
    d["production_sources"][0]["operations"] = list(ops)
    return d


def test_work_done_outside_takes_its_days_and_loads_no_machine():
    d = _routing({"seq": 10, "resource": "M1", "run_hours_per_unit": 0.2},
                 {"seq": 20, "subcontract": {"supplier": "S", "workdays": 3, "cost_per_unit": 1.5}},
                 {"seq": 30, "resource": "M1", "run_hours_per_unit": 0.2})
    ds_ = ds(d)
    ps = ds_.production_source_by_id["PV-A"]
    sch = schedule_make(ds_, ps, 40, start=date(2026, 1, 5))       # 8 h, 3 days outside, 8 h
    assert [(w.seq, w.resource, w.start, w.end) for w in sch.ops] == [
        (10, "M1", date(2026, 1, 5), date(2026, 1, 6)),
        (20, None, date(2026, 1, 6), date(2026, 1, 9)),
        (30, "M1", date(2026, 1, 9), date(2026, 1, 10))]
    assert conversion_unit_cost(ds_, "PV-A") == pytest.approx(0.4 * 100 + 1.5)
    d["demand"] = [demand("P", "A", "2026-01-30", 50)]
    d["scheduling"] = {"horizon_days": 42, "improve": False}
    out = run_schedule(ds(d))
    assert out.ok and not out.violations
    o10, o30 = sorted((o for o in out.ops), key=lambda o: o.seq)
    assert o30.setup_start >= o10.end + 3 * 24 - 1e-6              # waits three working days for the supplier
    assert {o.resource for o in out.ops} == {"M1"}


def test_overlap_lets_the_next_step_start_before_this_one_ends():
    plain = ({"seq": 10, "resource": "M1", "run_hours_per_unit": 0.4},
             {"seq": 20, "resource": "M2", "run_hours_per_unit": 0.4})
    d = _routing(*plain)
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1.0, "hours_per_shift": 8})
    ps = ds(d).production_source_by_id["PV-A"]
    seq_ = schedule_make(ds(d), ps, 40, start=date(2026, 1, 5))          # 16 h + 16 h: four days
    assert seq_.due_date == date(2026, 1, 9)
    d["production_sources"][0]["operations"][0]["send_ahead_qty"] = 10
    over = schedule_make(ds(d), ds(d).production_source_by_id["PV-A"], 40, start=date(2026, 1, 5))
    w10, w20 = over.ops
    assert w20.start < w10.end and over.due_date == date(2026, 1, 8)     # a day saved, never ends before step 10
    back = schedule_make(ds(d), ds(d).production_source_by_id["PV-A"], 40, available=date(2026, 1, 8))
    assert back.start_date == date(2026, 1, 5)
    d["demand"] = [demand("P", "A", "2026-01-23", 50)]
    d["scheduling"] = {"horizon_days": 42, "improve": False}
    out = run_schedule(ds(d))
    assert out.ok and not out.violations
    a, b = sorted(out.ops, key=lambda o: o.seq)
    assert b.setup_start < a.end and b.end >= a.end


def test_an_alternative_machine_takes_the_order_the_busy_one_cannot():
    d = _routing({"seq": 10, "resource": "M1", "run_hours_per_unit": 0.4, "alternatives": ["M2"]})
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1.0, "hours_per_shift": 8})
    d["scheduling"] = {"horizon_days": 42, "improve": False}
    d["receipts"] = [{"id": f"FIRM-{i}", "kind": "production", "location": "P", "product": "A", "qty": 20,
                      "source": "PV-A", "start_date": "2026-01-05", "due_date": "2026-01-06"} for i in (1, 2)]
    out = run_schedule(ds(d))
    assert out.ok and not out.violations
    assert {o.resource for o in out.ops} == {"M1", "M2"}
    assert len({o.setup_start for o in out.ops}) == 1                 # side by side, both on time


# ---- the MRP views --------------------------------------------------------------------------------------
def test_procurement_type_limits_the_sources_mrp_may_use():
    d = base()
    d["purchasing_sources"].append({"id": "PIR-A", "supplier": "S", "product": "A", "location": "P", "price": 50,
                                    "lead_time_days": 2})
    kinds = lambda d_: {o.kind for o in build_graph(ds(d_)).options[("P", "A")]}  # noqa: E731
    assert kinds(d) == {"make", "buy"}
    lp(d, "P", "A")["procurement"] = "make"
    assert kinds(d) == {"make"}
    lp(d, "P", "A")["procurement"] = "external"
    assert kinds(d) == {"buy"}


def test_scheduling_margin_releases_early_and_keeps_a_buffer_before_the_due_date():
    d = _routing({"seq": 10, "resource": "M1", "run_hours_per_unit": 0.2})
    ps = ds(d).production_source_by_id["PV-A"]
    plain = schedule_make(ds(d), ps, 40, start=date(2026, 1, 5))
    lp(d, "P", "A").update(float_before_workdays=2, float_after_workdays=1)
    m = schedule_make(ds(d), ds(d).production_source_by_id["PV-A"], 40, start=date(2026, 1, 5))
    assert plain.ops[0].start == date(2026, 1, 5) and plain.due_date == date(2026, 1, 6)
    assert m.start_date == date(2026, 1, 5) and m.ops[0].start == date(2026, 1, 7)
    assert m.due_date == date(2026, 1, 9)
    back = schedule_make(ds(d), ds(d).production_source_by_id["PV-A"], 40, available=date(2026, 1, 9))
    assert back.start_date == date(2026, 1, 5) and back.ops[0].start == date(2026, 1, 7)


def test_needs_merges_a_part_reached_twice():
    d = _made_to_order(components=[{"product": "SUB", "qty": 1}, {"product": "B", "qty": 1}])
    d["products"].append({"id": "SUB", "type": "SFG"})
    d["production_sources"].append({"id": "PV-SUB", "location": "P", "product": "SUB", "fixed_lead_time_workdays": 1,
                                    "components": [{"product": "B", "qty": 3}]})
    d["location_products"].append({"location": "P", "product": "SUB", "phantom": True})
    ds_ = ds(d)
    got = {n.product: n.per_unit for n in needs(ds_, ds_.production_source_by_id["PV-A"])}
    assert got == {"B": pytest.approx(4)}
