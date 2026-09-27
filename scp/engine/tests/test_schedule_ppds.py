"""Phase D: PP/DS-class scheduling.

* Machine choice by sequence: a step listed on an alternative runs there; a schedule handed back as its own
  sequences (the board, the optimiser, "use these dates") is re-timed to exactly the same schedule.
* Not-before times (just in time) and the objective's earliness and makespan terms.
* The frozen zone: orders dated by an earlier schedule keep their place and machine.
* The heuristics catalogue and profiles; every rule gives a feasible schedule, each does what it says on a case
  built for it; the optimiser is never worse than the local search, and wins where machine choice and setups
  interact.
"""
from __future__ import annotations

import random

import pytest

from scp.schedule import HEURISTICS, PROFILES, apply_schedule, compare_schedules, run_schedule
from scp.schedule.core import Job, check, complete, decode, edd, improve, objective
from scp.schedule.heuristics import start
from scp.schedule.optimize import optimize

from .factory import ds, load_example
from .test_schedule import ALLDAYS, _instance, _op, _random_instance
from .test_schedule_apply import _late_sub


def _two_machines(n: int = 4, groups: str = "ABAB") -> list[Job]:
    return [Job(f"J{i}", f"P{g}{i}", 0.0, 400.0, [_op(f"P{g}{i}", g, 0.5, 3.0, "R", f"J{i}", alternatives=["S"])])
            for i, g in enumerate(groups[:n])]


# ---- machine choice ------------------------------------------------------------------------------
def test_a_step_listed_on_an_alternative_runs_there():
    inst = _instance(_two_machines(2), {"R": 1, "S": 1})
    d = decode(inst, {"R": ["J0:10"], "S": ["J1:10"]}, pin=True)
    assert {b.key: b.resource for b in d.blocks} == {"J0:10": "R", "J1:10": "S"}
    assert check(inst, d) == []
    # pinned on its own machine: both wait for R; auto: the second goes to the free alternative
    both = decode(inst, {"R": ["J0:10", "J1:10"]}, pin=True)
    assert {b.resource for b in both.blocks} == {"R"}
    auto = decode(inst, {"R": ["J0:10", "J1:10"]})
    assert {b.resource for b in auto.blocks} == {"R", "S"}
    # a machine that cannot run the step is ignored; the step goes back to its own
    assert complete(inst, {"X": ["J0:10"], "S": ["J1:10", "J1:10"]}) == {"R": ["J0:10"], "S": ["J1:10"]}


def test_a_schedule_handed_back_as_its_sequences_is_the_same_schedule():
    rng = random.Random(11)
    for _ in range(40):
        inst = _random_instance(rng)
        for j in inst.jobs.values():                       # give some steps an alternative
            for o in j.ops:
                if rng.random() < 0.4:
                    o.alternatives = [r for r in inst.resources if r != o.resource][:1]
        seqs, d, _ = improve(inst, edd(inst), time_limit=0.3)
        again = decode(inst, complete(inst, d.realized), pin=True)
        assert again.completion == pytest.approx(d.completion)
        assert sorted((b.key, b.resource) for b in again.blocks) == sorted((b.key, b.resource) for b in d.blocks)
        assert check(inst, again) == []


# ---- hold, earliness, makespan -------------------------------------------------------------------
def test_hold_delays_an_order_and_earliness_is_scored():
    jobs = [Job("J0", "P", 0.0, 100.0, [_op("P", "G", 0.0, 4.0, order="J0")])]
    inst = _instance(jobs, {"R": 1})
    d = decode(inst, edd(inst))
    assert d.completion["J0"] == pytest.approx(10.0) and d.earliness == pytest.approx(90.0)
    late = decode(inst, edd(inst), hold={"J0": 90.0})
    assert late.blocks[0].setup_start == pytest.approx(90.0) and late.earliness == pytest.approx(6.0)
    assert check(inst, late) == []
    inst.earliness_weight, inst.makespan_weight, inst.tardiness_weight, inst.setup_weight = 0.5, 2.0, 1.0, 1.0
    assert objective(inst, late) == pytest.approx(0.5 * 6.0 + 2.0 * 94.0)


# ---- start rules ---------------------------------------------------------------------------------
def test_every_rule_gives_a_feasible_schedule():
    rng = random.Random(3)
    for _ in range(30):
        inst = _random_instance(rng)
        for rule in ("edd", "spt", "slack", "campaign", "backward"):
            seqs, hold = start(inst, rule)
            d = decode(inst, seqs, hold)
            assert check(inst, d) == [], rule
            assert set(d.completion) == set(inst.jobs)


def test_campaign_rule_groups_ready_orders():
    """Eight orders, all ready now, alternating groups: due-date order changes over seven times; campaigns twice."""
    groups = "ABABABAB"
    jobs = [Job(f"J{i}", f"P{g}", 0.0, 200.0 + i, [_op(f"P{g}", g, 0.5, 2.0, "R", f"J{i}")])
            for i, g in enumerate(groups)]
    inst = _instance(jobs, {"R": 1}, {("R", "A", "B"): 2.0, ("R", "B", "A"): 2.0})
    assert decode(inst, edd(inst)).changeovers == 7
    seqs, hold = start(inst, "campaign")
    assert decode(inst, seqs, hold).changeovers == 1


def test_shortest_job_first_and_dispatching_skip_an_order_waiting_for_parts():
    """The shortest order's parts come at hour 50: the machine does the others first instead of idling."""
    jobs = [Job("J0", "P", 0.0, 60.0, [_op("P", "G", 0.0, 1.0, order="J0", parts_ready=50.0)]),
            Job("J1", "P", 0.0, 60.0, [_op("P", "G", 0.0, 5.0, order="J1")]),
            Job("J2", "P", 0.0, 60.0, [_op("P", "G", 0.0, 6.0, order="J2")])]
    inst = _instance(jobs, {"R": 1})
    seqs, _ = start(inst, "spt")
    assert seqs["R"] == ["J1:10", "J2:10", "J0:10"]
    assert decode(inst, seqs).late_jobs == 0


def test_backward_starts_just_in_time():
    """Due in four days: forward builds it on day one; backward holds it to finish the day before it is due."""
    jobs = [Job("J0", "P", 0.0, 96.0, [_op("P", "G", 0.0, 4.0, order="J0")])]
    inst = _instance(jobs, {"R": 1})
    fwd = decode(inst, edd(inst))
    seqs, hold = start(inst, "backward", buffer_days=1.0)
    jit = decode(inst, seqs, hold)
    assert fwd.earliness == pytest.approx(86.0)
    assert jit.tardiness == 0 and jit.earliness < 30.0 and jit.completion["J0"] > 48.0


# ---- optimiser -----------------------------------------------------------------------------------
def test_optimiser_never_worse_and_feasible_on_random_instances():
    rng = random.Random(5)
    for _ in range(12):
        inst = _random_instance(rng)
        for j in inst.jobs.values():
            for o in j.ops:
                if rng.random() < 0.3:
                    o.alternatives = [r for r in inst.resources if r != o.resource][:1]
        _, ls, _ = improve(inst, edd(inst), time_limit=0.25)
        seqs, d, hold, pinned, info = optimize(inst, edd(inst), {}, 1.0)
        assert check(inst, d) == []
        assert d.objective <= ls.objective + 1e-6
        assert info.status in ("optimal", "feasible", "not run")
        if pinned:   # the pinned sequences reproduce what is reported
            assert decode(inst, seqs, hold, pin=True).objective == pytest.approx(d.objective)


def test_optimiser_uses_the_alternative_machine_to_keep_campaigns():
    """A, B, A, B on R (alternative S) with a 4 h changeover and a loose due date: the greedy decoder alternates the
    two machines and changes over; the optimiser puts each group on one machine."""
    inst = _instance(_two_machines(4), {"R": 1, "S": 1}, {(None, "A", "B"): 4.0, (None, "B", "A"): 4.0},
                     cal=ALLDAYS, span=24.0)
    _, ls, _ = improve(inst, edd(inst), time_limit=0.5)
    seqs, d, _, pinned, info = optimize(inst, edd(inst), {}, 2.0)
    assert d.changeovers == 0 and d.objective <= ls.objective + 1e-9
    by = {}
    for b in d.blocks:
        by.setdefault(b.resource, set()).add(inst.op(b.key).group)
    assert all(len(g) == 1 for g in by.values())


def test_frozen_zone_keeps_place_and_machine():
    """Apply a schedule, then reverse the order on its machine with a frozen zone covering it: the frozen orders
    keep their scheduled order; without the zone they follow the new sequence."""
    d = _late_sub()
    new, rep = apply_schedule(ds(d))
    sch = run_schedule(new)
    frozen = new.model_copy(update={"scheduling": new.scheduling.model_copy(update={"frozen_days": 30})})
    fz = run_schedule(frozen)
    assert all(o.frozen for o in fz.orders)
    rev = {r.id: list(reversed(r.sequence)) for r in fz.resources}
    kept = run_schedule(frozen, rev)
    assert {r.id: r.sequence for r in kept.resources} == {r.id: r.sequence for r in fz.resources}
    assert not any(o.frozen for o in sch.orders)


# ---- catalogue, profiles and the run --------------------------------------------------------------
def test_profiles_set_known_fields_and_every_rule_is_catalogued():
    fields = set(type(load_example("kitchenware_network").scheduling).model_fields)
    for p in PROFILES:
        assert set(p.settings) <= fields, p.id
    ids = {h.id for h in HEURISTICS}
    assert {"edd", "spt", "slack", "campaign", "backward", "improve", "optimize"} <= ids


def test_run_with_a_profile_and_compare_on_the_example():
    ex = load_example("kitchenware_network")
    best = next(p for p in PROFILES if p.id == "best")
    opt = ex.model_copy(update={"scheduling": ex.scheduling.model_copy(update={**best.settings, "profile": "best",
                                                                                 "time_limit_seconds": 3.0})})
    r = run_schedule(opt)
    assert r.ok and r.violations == [] and r.search.mode == "optimized" and r.profile == "best"
    assert r.search.optimizer is not None and r.search.optimizer.status in ("optimal", "feasible")
    ls = run_schedule(ex.model_copy(update={"scheduling": ex.scheduling.model_copy(update={"time_limit_seconds": 1.0})}))
    assert r.kpis.objective <= ls.kpis.objective + 1e-6
    # what the page shows can be handed back and is the same schedule
    again = run_schedule(opt, {x.id: x.sequence for x in r.resources}, hold=r.holds)
    assert again.kpis.objective == pytest.approx(r.kpis.objective)
    assert [o.completion for o in again.orders] == pytest.approx([o.completion for o in r.orders])
    c = compare_schedules(ex.model_copy(
        update={"scheduling": ex.scheduling.model_copy(update={"time_limit_seconds": 1.0})}))
    assert c.ok and [x.method for x in c.rows] == ["edd", "spt", "slack", "campaign", "backward", "improve",
                                                   "optimize"]
    assert sum(x.best for x in c.rows) >= 1
    low = min(x.kpis.objective for x in c.rows)
    assert next(x for x in c.rows if x.method == "optimize").kpis.objective <= \
        next(x for x in c.rows if x.method == "improve").kpis.objective + 1e-6
    assert all(x.kpis.objective >= low for x in c.rows)
