"""P5 detailed scheduling: shift-window time arithmetic, the setup rule and changeover matrix, the
campaign local search on a hand case, and an independent feasibility checker that every decoded
schedule (EDD, improved, random manual sequences) must pass on random instances."""
from __future__ import annotations

import copy
import random
from datetime import date

import pytest

from scp.model import Calendar, Dataset
from scp.schedule import run_schedule
from scp.schedule.clock import ResourceClock, after_queue
from scp.schedule.core import Instance, Job, OpSpec, Res, check, complete, decode, edd, improve, setup_rule
from scp.time import WorkCalendar

from .factory import base, demand, ds as make_ds, load_example, lp

MON = date(2026, 1, 5)
WEEKDAYS = WorkCalendar(Calendar(id="W", workdays=[0, 1, 2, 3, 4]))
ALLDAYS = WorkCalendar(Calendar(id="A", workdays=[0, 1, 2, 3, 4, 5, 6]))


def clock(span: float = 8.0, eff: float = 1.0, cal: WorkCalendar = WEEKDAYS) -> ResourceClock:
    return ResourceClock(cal, MON, 6.0, span, eff)


# ---- time model -------------------------------------------------------------------------------
def test_advance_pauses_overnight_and_weekend():
    c = clock()
    assert c.advance(0.0, 4.0) == (6.0, 10.0)                  # Monday 06:00–10:00
    assert c.advance(12.0, 4.0) == (12.0, 24 + 8.0)             # 2 h Mon, 2 h Tue from 06:00
    fri = 4 * 24.0
    s, e = c.advance(fri + 10.0, 8.0)                            # 4 h Fri, rest Monday
    assert (s, e) == (fri + 10.0, 7 * 24.0 + 6.0 + 4.0)
    assert c.work_between(s, e) == pytest.approx(8.0)


def test_efficiency_stretches_clock_time():
    c = clock(eff=0.5)
    assert c.advance(0.0, 2.0) == (6.0, 10.0)
    assert c.work_between(6.0, 10.0) == pytest.approx(2.0)


def test_queue_moves_to_later_workday():
    # op ends Friday 10:00; one queue workday (Monday) → next op from Tuesday 00:00
    assert after_queue(WEEKDAYS, MON, 4 * 24.0 + 10.0, 1) == 8 * 24.0
    # op ends Monday 10:00; queue Tuesday → Wednesday 00:00; ending exactly at midnight counts as Monday
    assert after_queue(WEEKDAYS, MON, 10.0, 1) == 2 * 24.0
    assert after_queue(WEEKDAYS, MON, 24.0, 1) == 2 * 24.0
    assert after_queue(WEEKDAYS, MON, 30.0, 0) == 30.0


# ---- setup rule ---------------------------------------------------------------------------------
def _op(product: str, group: str, setup: float = 1.0, run: float = 2.0, resource: str = "R", order: str = "J",
        seq: int = 10, **kw) -> OpSpec:
    return OpSpec(key=f"{order}:{seq}", order=order, seq=seq, resource=resource, product=product, group=group,
                  qty=10, setup=setup, run=run, **kw)


def test_setup_rule():
    fn = setup_rule({("R", "A", "B"): 3.0, (None, "B", "A"): 5.0}, 0.2)
    a1, a2, b = _op("A1", "A"), _op("A2", "A"), _op("B1", "B")
    assert fn("R", None, a1) == 1.0                              # nothing before: full setup
    assert fn("R", ("A1", "A"), a1) == 0.0                       # same product
    assert fn("R", ("A1", "A"), a2) == pytest.approx(0.2)        # same group, minor setup
    assert fn("R", ("A1", "A"), b) == 3.0                        # resource-specific matrix
    assert fn("R2", ("A1", "A"), b) == 1.0                       # other resource: no entry → full
    assert fn("R2", ("B1", "B"), a1) == 5.0                      # generic matrix entry


# ---- hand case: campaign ------------------------------------------------------------------------
def _instance(jobs: list[Job], units: dict[str, int], changeovers=None, *, cal: WorkCalendar = ALLDAYS,
              span: float = 16.0, minor: float = 0.2, tw: float = 1.0, sw: float = 1.0) -> Instance:
    res = {r: Res(r, u, ResourceClock(cal, MON, 6.0, span, 1.0)) for r, u in units.items()}
    return Instance(res, {j.id: j for j in jobs}, setup_rule(changeovers or {}, minor),
                    lambda op, t: after_queue(cal, MON, t, op.queue_workdays), tw, sw)


def test_campaign_merges_setup_groups():
    """A, B, A, B due in that order with a 2 h changeover: EDD alternates (3 changeovers); with a
    loose due date the search groups them into AABB (1 changeover) and no order becomes late."""
    groups = ["A", "B", "A", "B"]
    jobs = [Job(f"J{i}", f"P{g}{i}", 0.0, 500.0 + i, [_op(f"P{g}{i}", g, 0.5, 2.0, order=f"J{i}")])
            for i, g in enumerate(groups)]
    inst = _instance(jobs, {"R": 1}, {("R", "A", "B"): 2.0, ("R", "B", "A"): 2.0})
    base = decode(inst, edd(inst))
    assert base.changeovers == 3
    seqs, best, st = improve(inst, edd(inst))
    order = [inst.op(k).group for k in seqs["R"]]
    assert order in (["A", "A", "B", "B"], ["B", "B", "A", "A"])
    assert best.changeovers == 1
    assert best.tardiness == 0.0
    assert best.objective < base.objective
    assert check(inst, best) == []


def test_due_dates_outweigh_changeovers():
    """Tight due dates: grouping would make the second A late by more than the setup it saves."""
    jobs = [Job("J0", "PA0", 0.0, 9.0, [_op("PA0", "A", 0.0, 2.0, order="J0")]),
            Job("J1", "PB1", 0.0, 11.0, [_op("PB1", "B", 0.0, 2.0, order="J1")]),
            Job("J2", "PA2", 0.0, 50.0, [_op("PA2", "A", 0.0, 2.0, order="J2")])]
    inst = _instance(jobs, {"R": 1}, {("R", "A", "B"): 1.0, ("R", "B", "A"): 1.0}, tw=100.0)
    seqs, best, _ = improve(inst, edd(inst))
    assert seqs["R"][:2] == ["J0:10", "J1:10"]                   # B stays ahead of the late A
    assert best.tardiness == 0.0


def test_tardiness_and_completion():
    jobs = [Job("J0", "P", 0.0, 8.0, [_op("P", "G", 0.0, 4.0, order="J0")]),
            Job("J1", "P", 0.0, 8.0, [_op("P", "G", 0.0, 4.0, order="J1")])]
    d = decode(_instance(jobs, {"R": 1}), {"R": ["J0:10", "J1:10"]})
    assert d.completion == {"J0": 10.0, "J1": 14.0}               # 06:00 + 4 h, then + 4 h
    assert d.tardiness == pytest.approx(2.0 + 6.0)
    assert d.late_jobs == 2 and d.max_lateness == pytest.approx(6.0)


def test_parallel_units_split_long_operation():
    jobs = [Job("J0", "P", 0.0, 1000.0, [_op("P", "G", 0.0, 24.0, order="J0")])]
    inst = _instance(jobs, {"R": 2}, span=8.0)
    d = decode(inst, edd(inst))
    assert len(d.blocks) == 2 and {b.unit for b in d.blocks} == {0, 1}
    assert d.completion["J0"] == pytest.approx(24 + 6 + 4)      # 12 h each: 8 h day 1, 4 h day 2
    one = copy.deepcopy(jobs)
    one[0].ops[0].parallel = 1
    d1 = decode(_instance(one, {"R": 2}, span=8.0), {"R": ["J0:10"]})
    assert len(d1.blocks) == 1 and d1.completion["J0"] == pytest.approx(48 + 6 + 8)


def test_split_not_worth_its_setup():
    # a 1 h run with a 4 h setup: splitting saves 0.5 h but adds 4 h of setup → stay on one unit
    jobs = [Job("J0", "P", 0.0, 1000.0, [_op("P", "G", 4.0, 1.0, order="J0")])]
    d = decode(_instance(jobs, {"R": 2}), {"R": ["J0:10"]})
    assert len(d.blocks) == 1


def test_crossed_sequences_do_not_deadlock():
    """R1 wants J1's 2nd op before J0's; R2 wants J0's 1st op after J1's — the decoder falls back to
    the earliest-ranked ready operation instead of waiting forever."""
    jobs = [Job("J0", "P", 0.0, 99.0, [_op("P", "G", 0, 1, "R1", "J0", 10), _op("P", "G", 0, 1, "R2", "J0", 20)]),
            Job("J1", "Q", 0.0, 99.0, [_op("Q", "G", 0, 1, "R2", "J1", 10), _op("Q", "G", 0, 1, "R1", "J1", 20)])]
    inst = _instance(jobs, {"R1": 1, "R2": 1})
    d = decode(inst, {"R1": ["J1:20", "J0:10"], "R2": ["J0:20", "J1:10"]})
    assert check(inst, d) == []
    assert set(d.completion) == {"J0", "J1"}


def test_checker_catches_overlap_and_bad_setup():
    jobs = [Job(f"J{i}", f"P{i}", 0.0, 99.0, [_op(f"P{i}", f"G{i}", 1.0, 2.0, order=f"J{i}")]) for i in range(2)]
    inst = _instance(jobs, {"R": 1})
    d = decode(inst, edd(inst))
    assert check(inst, d) == []
    bad = copy.deepcopy(d)
    b = bad.blocks[1]
    b.setup_start, b.run_start, b.end = bad.blocks[0].setup_start, bad.blocks[0].run_start, bad.blocks[0].end
    v = check(inst, bad)
    assert any("overlap" in x for x in v)
    bad2 = copy.deepcopy(d)
    bad2.blocks[1].setup_work = 0.0
    assert any("setup rule" in x for x in check(inst, bad2))


# ---- random instances -----------------------------------------------------------------------
def _random_instance(rng: random.Random) -> Instance:
    resources = {f"R{i}": rng.randint(1, 3) for i in range(rng.randint(1, 3))}
    groups = ["A", "B", "C"][: rng.randint(1, 3)]
    co = {(None, a, b): rng.choice([0.5, 1.0, 3.0]) for a in groups for b in groups if a != b}
    jobs = []
    for j in range(rng.randint(2, 9)):
        g = rng.choice(groups)
        prod = f"{g}{rng.randint(1, 2)}"
        rel = rng.choice([0.0, 24.0, 50.0])
        ops = [_op(prod, g, rng.choice([0.0, 1.0]), rng.uniform(0.5, 30.0), rng.choice(list(resources)), f"J{j}",
                   10 * (k + 1), queue_workdays=rng.choice([0, 0, 1]), parallel=rng.choice([None, 1]))
               for k in range(rng.randint(1, 3))]
        if jobs and rng.random() < 0.4:
            # parts from an earlier order (acyclic), or a fixed arrival
            rng.choice(ops).waits_on.append((rng.choice(jobs).id, rng.choice([0, 1])))
        if rng.random() < 0.3:
            rng.choice(ops).parts_ready = rng.choice([30.0, 80.0])
        jobs.append(Job(f"J{j}", prod, rel, rel + rng.uniform(10, 150), ops, weight=rng.choice([1.0, 2.0])))
    return _instance(jobs, resources, co, cal=rng.choice([WEEKDAYS, ALLDAYS]), span=rng.choice([8.0, 16.0]))


def test_random_instances_are_feasible_and_search_never_worsens():
    rng = random.Random(7)
    for _ in range(60):
        inst = _random_instance(rng)
        base_seq = edd(inst)
        base = decode(inst, base_seq)
        assert check(inst, base) == []
        seqs, best, _ = improve(inst, base_seq, time_limit=2.0)
        assert check(inst, best) == []
        assert best.objective <= base.objective + 1e-9
        shuffled = {r: rng.sample(s, len(s)) for r, s in base_seq.items()}
        d = decode(inst, shuffled)
        assert check(inst, d) == []
        assert set(d.completion) == set(inst.jobs)


# ---- parts --------------------------------------------------------------------------------------
def test_step_waits_for_parts_from_another_order():
    """J1's second step uses what J0 makes: it starts when J0 finishes (plus a receiving day), not before; its first
    step does not wait. A fixed arrival holds a step the same way, and the checker catches a step moved earlier."""
    j0 = Job("J0", "SUB", 0.0, 99.0, [_op("SUB", "G", 0, 10, "R1", "J0", 10)])
    j1 = Job("J1", "FG", 0.0, 99.0, [_op("FG", "G", 0, 1, "R2", "J1", 10),
                                     _op("FG", "G", 0, 1, "R2", "J1", 20, waits_on=[("J0", 0)])])
    inst = _instance([j0, j1], {"R1": 1, "R2": 1})
    d = decode(inst, edd(inst))
    assert d.completion["J0"] == pytest.approx(16.0)             # 06:00 + 10 h
    step2 = next(b for b in d.blocks if b.key == "J1:20")
    assert step2.setup_start == pytest.approx(16.0)
    assert d.held["J1:20"] == pytest.approx(16.0 - 7.0)          # could have started at 07:00
    assert "J1:10" not in d.held
    assert check(inst, d) == []
    # one receiving day: the part is there from the next working day
    inst.receive = lambda order, t, days: after_queue(ALLDAYS, MON, t, days)
    j1.ops[1].waits_on = [("J0", 1)]
    d = decode(inst, edd(inst))
    assert next(b for b in d.blocks if b.key == "J1:20").setup_start == pytest.approx(48.0 + 6.0)
    bad = copy.deepcopy(d)
    b = next(b for b in bad.blocks if b.key == "J1:20")
    b.setup_start, b.run_start, b.end = 7.0, 7.0, 8.0
    assert any("parts" in v for v in check(inst, bad))
    j1.ops[1].waits_on = []
    j1.ops[1].parts_ready = 30.0
    d = decode(inst, edd(inst))
    assert next(b for b in d.blocks if b.key == "J1:20").setup_start == pytest.approx(30.0)


def _made_sub() -> dict:
    """A (on M2) is made from SUB (on M1), made in the same schedule from bought C."""
    d = base(horizon=28)
    d["products"].append({"id": "SUB", "type": "SFG"})
    d["resources"].append({"id": "M2", "location": "P", "efficiency": 1.0, "hours_per_shift": 8})
    d["production_sources"] = [
        {"id": "PV-A", "location": "P", "product": "A", "fixed_lead_time_workdays": 1,
         "components": [{"product": "SUB", "qty": 1}],
         "operations": [{"seq": 10, "resource": "M2", "setup_hours": 0, "run_hours_per_unit": 0.1}]},
        {"id": "PV-SUB", "location": "P", "product": "SUB", "fixed_lead_time_workdays": 1,
         "components": [{"product": "C", "qty": 1}],
         "operations": [{"seq": 10, "resource": "M1", "setup_hours": 0, "run_hours_per_unit": 0.4}]},
    ]
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "SUB")["on_hand"] = 0
    lp(d, "P", "C")["on_hand"] = 1000
    d["demand"] = [demand("P", "A", "2026-01-12", 40)]
    return d


def test_schedule_waits_for_a_subassembly_made_in_the_same_schedule():
    """SUB takes 16 h of M1 (two 8 h days) where MRP allowed one working day: A waits for it and finishes late.
    Without waiting for parts it would start on its MRP day as if SUB were there."""
    d = _made_sub()
    d["scheduling"] = {"improve": False}
    r = run_schedule(make_ds(d))
    assert r.ok and r.violations == []
    a = next(o for o in r.orders if o.product == "A")
    sub = next(o for o in r.orders if o.product == "SUB")
    assert [p.supply for p in a.parts_from] == [sub.id] and a.parts_from[0].scheduled
    a_start = min(op.setup_start for op in r.ops if op.order == a.id)
    assert a_start >= sub.completion - 1e-6
    assert a.held_for_parts > 0 and r.kpis.waiting_for_parts == 1
    d["scheduling"] = {"improve": False, "wait_for_parts": False}
    r2 = run_schedule(make_ds(d))
    a2 = next(o for o in r2.orders if o.product == "A")
    assert min(op.setup_start for op in r2.ops if op.order == a2.id) < a_start
    assert a2.parts_from == [] and r2.kpis.waiting_for_parts == 0


def test_schedule_waits_for_a_late_firm_purchase():
    """C comes only on an open purchase order due day 6 (a new one would take 20 days): MRP pegs A's parts to it,
    and the schedule holds A until it is there; the finish and available dates report the slip."""
    d = base(horizon=28)
    d["purchasing_sources"][1]["lead_time_days"] = 20
    lp(d, "P", "A")["on_hand"] = 0
    lp(d, "P", "B")["on_hand"] = 1000
    d["demand"] = [demand("P", "A", "2026-01-08", 10)]
    d["receipts"] = [{"id": "PO-1", "kind": "purchase", "location": "P", "product": "C", "qty": 10,
                      "due_date": "2026-01-11"}]
    d["scheduling"] = {"improve": False}
    r = run_schedule(make_ds(d))
    assert r.ok and r.violations == []
    a = r.orders[0]
    assert [(p.supply, p.product, p.scheduled) for p in a.parts_from] == [("PO-1", "C", False)]
    assert a.parts_ready == pytest.approx(6 * 24.0)
    assert min(op.setup_start for op in r.ops) >= 6 * 24.0
    assert a.tardy and a.days_late >= 1
    assert a.available_date is not None and a.available_date > a.mrp_due_date


def test_complete_manual_sequence():
    jobs = [Job(f"J{i}", "P", 0.0, 10.0 * i, [_op("P", "G", order=f"J{i}")]) for i in range(3)]
    inst = _instance(jobs, {"R": 1})
    assert complete(inst, {"R": ["J2:10", "bogus"]})["R"] == ["J2:10", "J0:10", "J1:10"]


# ---- dataset ----------------------------------------------------------------------------------
def test_example_schedule():
    ds = load_example("kitchenware_network")
    r = run_schedule(ds)
    assert r.ok and r.violations == []
    assert r.kpis.objective <= r.baseline.objective + 1e-9
    assert r.kpis.orders == len(r.orders) > 10
    firm = [o for o in r.orders if o.firm]
    assert [o.id for o in firm] == ["MO-100455"] and firm[0].release == 0.0
    assert {x.id for x in r.resources} >= {"PUNE-L1", "PUNE-TEST", "PUNE-WIND"}
    # every order: operations sum to its started quantity, and completion is not before release
    for o in r.orders:
        assert o.completion >= o.release
    assert r.labour and all(x.resource == "PUNE-LABOUR" for x in r.labour)
    # the matrix is applied: a W750 → W500 switch on the winders costs 2.5 h
    sw = [op for op in r.ops if op.resource == "PUNE-WIND" and op.setup_from == "W750" and op.group == "W500"]
    assert all(op.setup_hours == pytest.approx(2.5) for op in sw)


def test_manual_sequence_is_honoured():
    ds = load_example("kitchenware_network")
    r = run_schedule(ds)
    seq = list(reversed(next(x for x in r.resources if x.id == "PUNE-L2").sequence))
    m = run_schedule(ds, {"PUNE-L2": seq})
    assert m.search.mode == "manual" and m.violations == []
    assert next(x for x in m.resources if x.id == "PUNE-L2").sequence == seq


def test_edd_only_and_horizon():
    ds = load_example("kitchenware_network")
    d = ds.model_dump()
    d["scheduling"] = {"improve": False, "horizon_days": 14}
    r = run_schedule(Dataset.model_validate(d))
    assert r.search.mode == "edd" and r.kpis == r.baseline
    assert r.beyond_horizon > 0
    assert all(o.release < 14 * 24 for o in r.orders)


def test_blocked_dataset():
    ds = load_example("kitchenware_network")
    d = ds.model_dump()
    d["changeovers"] = [{"resource": "NOPE", "from_group": "A", "to_group": "B", "hours": 1}]
    r = run_schedule(Dataset.model_validate(d))
    assert not r.ok and any(i.code == "REF_UNKNOWN" for i in r.issues)
