"""The optimiser (≈ the PP/DS optimiser): a CP-SAT model chooses each step's machine and every machine's sequence to
lower the weighted objective, and the exact decoder then times that choice on the shift calendars.

The model works in elapsed hours: a step's run takes its work hours times the elapsed-per-work ratio its machine
works (its shifts, breaks, efficiency and days off averaged over the window, or the step's own elapsed time in the
starting schedule when it stays on the same machine); a changeover between two steps on a machine costs the setup rule's
hours the same way. Precedence, queues, receiving days, parts, release and hold times are constraints; tardiness,
earliness, changeover hours and makespan are the objective. Sublots over parallel units, send-ahead overlap and labour
are left to the decoder.

Because the model's times are an average, the solver's answer is only a proposal: the decoder re-times its machines
and sequences exactly, a short local search polishes that, and it is kept only when it beats the schedule it started
from. The optimiser never returns a worse schedule.

The solver runs in a worker process of its own: OR-Tools and HiGHS (the S&OP and placement LPs) each ship a native
HiGHS library of a different version, and whichever loads first into a process breaks the other.
"""
from __future__ import annotations

import atexit
import math
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field, replace

from .core import EPS, Decoded, Instance, OpSpec, Res, improve

SCALE = 10                  # model time unit: 6 minutes
MAX_PER_MACHINE = 150       # candidate steps on one machine (the sequence model grows with the square)
MAX_STEPS = 800


@dataclass
class OptInfo:
    status: str = "not run"          # optimal | feasible | no solution | too big | not installed | not better
    seconds: float = 0.0
    model_objective: float | None = None
    model_bound: float | None = None
    steps: int = 0
    machines_changed: int = 0        # steps the optimiser moved to another machine than the start
    kept: bool = False               # the optimiser's schedule beat the start and was kept
    note: str = ""
    trace: list[float] = field(default_factory=list)


def _share(inst: Instance, rid: str, span: float) -> float:
    """The share of the clock a machine works over the window."""
    res = inst.resources[rid]
    clk = res.at(0 if res.finite else -1)
    open_ = clk.work_between(0.0, span)
    return max(open_ / span, 1e-3) if span > 0 else 1.0


_POOL: ProcessPoolExecutor | None = None


def _pool() -> ProcessPoolExecutor:
    """One solver worker, started on first use and kept for later solves (starting one costs about a second)."""
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        atexit.register(_POOL.shutdown, wait=False, cancel_futures=True)
    return _POOL


def solve(inst: Instance, warm: Decoded, hold: dict[str, float], time_limit: float
          ) -> tuple[dict[str, list[str]], dict[str, float], OptInfo] | OptInfo:
    """The CP-SAT proposal: sequences per resource (to decode pinned) and not-before times, or why there is none.
    Solved in the worker process (see the module note)."""
    global _POOL
    lite, share = _portable(inst, warm)
    try:
        return _pool().submit(_solve, lite, warm, hold, time_limit, share).result(timeout=time_limit + 120.0)
    except (BrokenProcessPool, TimeoutError, OSError) as e:
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
            _POOL = None
        return OptInfo(status="no solution", note=f"The solver worker stopped ({type(e).__name__}); the local search "
                                                  "result is used.")


class _Setup:
    """The setup rule as a table: (resource, what ran before, step) -> hours, for the pairs the model can meet."""
    def __init__(self, table: dict) -> None:
        self.table = table

    def __call__(self, r: str, prev: tuple[str, str] | None, o: OpSpec) -> float:
        return self.table[(r, prev, o.key)]


class _After:
    """Queue time after each step, at the end the starting schedule gave it."""
    def __init__(self, table: dict[str, float]) -> None:
        self.table = table

    def __call__(self, o: OpSpec, end: float) -> float:
        return self.table[o.key]


class _Receive:
    """When parts made by an order are there, at the completion the starting schedule gave it."""
    def __init__(self, table: dict) -> None:
        self.table = table

    def __call__(self, order: str, t: float, workdays: float) -> float:
        return self.table[(order, workdays)]


def _portable(inst: Instance, warm: Decoded) -> tuple[Instance, dict[str, float]]:
    """The instance as plain data for the worker: the setup, queue and receiving rules (closures over calendars) as
    tables of the values the model asks for, and each machine's shift share instead of its clock."""
    ops = [o for j in inst.jobs.values() for o in j.ops]
    on: dict[str, list[OpSpec]] = {}
    for o in ops:
        for r in (o.resource, *o.alternatives):
            if r in inst.resources:
                on.setdefault(r, []).append(o)
    setup: dict = {}
    for r, mops in on.items():
        res = inst.resources[r]
        for b in mops:
            setup[(r, None, b.key)] = inst.setup(r, None, b)
            if res.finite and res.units == 1 and len(mops) <= MAX_PER_MACHINE:
                for a in mops:
                    if a.key != b.key:
                        setup[(r, (a.product, a.group), b.key)] = inst.setup(r, (a.product, a.group), b)
    after = {o.key: inst.after(o, warm.op_end[o.key]) for o in ops if o.key in warm.op_end}
    receive = {(src, lag): inst.receive(src, warm.completion[src], lag)
               for o in ops for src, lag in o.waits_on if src in warm.completion}
    span = _span(inst, warm)
    share = {r: _share(inst, r, span) for r in inst.resources}
    lite = replace(inst, resources={r: Res(r, x.units, None, x.finite) for r, x in inst.resources.items()},  # type: ignore[arg-type]
                   setup=_Setup(setup), after=_After(after), receive=_Receive(receive))
    return lite, share


def _span(inst: Instance, warm: Decoded) -> float:
    return max(warm.makespan, max((j.due for j in inst.jobs.values()), default=0.0), 24.0 * 7)


def _solve(inst: Instance, warm: Decoded, hold: dict[str, float], time_limit: float,
           share: dict[str, float] | None = None) -> tuple[dict[str, list[str]], dict[str, float], OptInfo] | OptInfo:
    info = OptInfo()
    try:
        from ortools.sat.python import cp_model
    except ImportError:   # pragma: no cover - ortools is a dependency; a trimmed install falls back
        info.status, info.note = "not installed", "OR-Tools is not installed; the local search result is used."
        return info
    t0 = time.perf_counter()
    jobs = list(inst.jobs.values())
    ops: list[OpSpec] = [o for j in jobs for o in j.ops]
    info.steps = len(ops)
    blocks: dict[str, list] = {}
    for b in warm.blocks:
        blocks.setdefault(b.key, []).append(b)
    span = _span(inst, warm)
    horizon = int(math.ceil((span * 2 + 24 * 14) * SCALE))
    frozen_res = {o.key: blocks[o.key][0].resource for o in ops if o.order in inst.frozen and o.key in blocks}
    # elapsed hours per work hour on each machine, as the starting schedule saw it (else its shift share)
    ratio: dict[str, float] = {}
    for r in inst.resources:
        bl = [b for b in warm.blocks if b.resource == r and b.run_work + b.setup_work > EPS]
        work = sum(b.run_work + b.setup_work for b in bl)
        ratio[r] = (sum(b.end - b.setup_start for b in bl) / work) if work > EPS else 1.0 / (share[r] if share else _share(inst, r, span))

    def cands(o: OpSpec) -> list[str]:
        if o.key in frozen_res:
            return [frozen_res[o.key]]
        return [o.resource, *(a for a in o.alternatives if a in inst.resources and a != o.resource)]

    def single(r: str) -> bool:
        res = inst.resources[r]
        return res.finite and res.units == 1

    on: dict[str, list[OpSpec]] = {}
    for o in ops:
        for r in cands(o):
            on.setdefault(r, []).append(o)
    worst = max((len(v) for r, v in on.items() if single(r)), default=0)
    if worst > MAX_PER_MACHINE or len(ops) > MAX_STEPS:
        info.status = "too big"
        info.note = (f"{len(ops)} steps, up to {worst} on one machine: more than the optimiser takes "
                     f"({MAX_STEPS} steps, {MAX_PER_MACHINE} per machine); the local search result is used.")
        return info

    def hours(o: OpSpec, r: str, work: float) -> int:
        """Elapsed model time for ``work`` hours of the step on ``r``."""
        bl = blocks.get(o.key, [])
        if len(bl) == 1 and bl[0].resource == r and bl[0].run_work > EPS:
            k = (bl[0].end - bl[0].run_start) / bl[0].run_work
        else:
            k = ratio[r]
        return int(math.ceil(work * k * SCALE - 1e-9))

    def span_on(o: OpSpec, r: str) -> tuple[int, int, float]:
        """A step on a machine with several units: (elapsed incl. setup, units it takes, setup work hours)."""
        bl = [b for b in blocks.get(o.key, []) if b.resource == r]
        if bl:
            d = max(b.end for b in bl) - min(b.setup_start for b in bl)
            return int(math.ceil(d * SCALE - 1e-9)), len(bl), sum(b.setup_work for b in bl)
        full = inst.setup(r, None, o)
        return hours(o, r, full + o.run), 1, full

    m = cp_model.CpModel()
    s: dict[str, cp_model.IntVar] = {}
    e: dict[str, cp_model.IntVar] = {}
    ready: dict[str, cp_model.IntVar] = {}
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    cum: dict[str, tuple[list, list]] = {}
    setup_terms: list[tuple] = []
    for o in ops:
        s[o.key] = m.NewIntVar(0, horizon, f"s{o.key}")
        e[o.key] = m.NewIntVar(0, horizon, f"e{o.key}")
        ready[o.key] = m.NewIntVar(0, horizon, f"r{o.key}")
        m.Add(s[o.key] >= ready[o.key])
        lits = []
        for r in cands(o):
            lit = m.NewBoolVar(f"x{o.key}@{r}")
            x[(o.key, r)] = lit
            lits.append(lit)
            res = inst.resources[r]
            if single(r):
                d = hours(o, r, o.run)                     # the setup comes before, by what ran last
                m.NewOptionalIntervalVar(s[o.key], d, e[o.key], lit, f"i{o.key}@{r}")
            elif res.finite:
                d, k, su = span_on(o, r)
                iv = m.NewOptionalIntervalVar(s[o.key], d, e[o.key], lit, f"i{o.key}@{r}")
                cum.setdefault(r, ([], []))
                cum[r][0].append(iv)
                cum[r][1].append(min(k, res.units))
                if su > EPS:
                    setup_terms.append((lit, int(round(su * SCALE))))
            else:
                full = inst.setup(r, None, o)
                d = hours(o, r, full + o.run)
                if full > EPS:
                    setup_terms.append((lit, int(round(full * SCALE))))
            m.Add(e[o.key] == s[o.key] + d).OnlyEnforceIf(lit)
        m.AddExactlyOne(lits)
    for r, (ivs, dem) in cum.items():
        m.AddCumulative(ivs, dem, inst.resources[r].units)

    def lag_after(o: OpSpec) -> int:
        end = warm.op_end.get(o.key)
        if end is None:
            return 0
        return int(math.ceil((inst.after(o, end) - end) * SCALE - 1e-9))

    completion: dict[str, cp_model.IntVar] = {}
    for j in jobs:
        if not j.ops:
            continue
        rel = max(j.release, hold.get(j.id, 0.0), inst.frozen.get(j.id, 0.0))
        m.Add(ready[j.ops[0].key] >= int(math.floor(rel * SCALE + 1e-9)))
        for a, b in zip(j.ops, j.ops[1:], strict=False):
            m.Add(ready[b.key] >= e[a.key] + lag_after(a))
        last = j.ops[-1]
        c = m.NewIntVar(0, horizon * 2, f"c{j.id}")
        m.Add(c == e[last.key] + lag_after(last))
        completion[j.id] = c
    for o in ops:
        if o.parts_ready > EPS:
            m.Add(ready[o.key] >= int(math.floor(o.parts_ready * SCALE + 1e-9)))
        for src, lag in o.waits_on:
            if src in completion and src in warm.completion:
                t = warm.completion[src]
                gap = int(math.ceil((inst.receive(src, t, lag) - t) * SCALE - 1e-9))
                m.Add(ready[o.key] >= completion[src] + gap)

    # sequence-dependent setups on single machines: a circuit over the steps that may run there
    for r, mops in on.items():
        if not single(r):
            continue
        arcs = []
        for i, b in enumerate(mops, start=1):
            arcs.append((i, i, x[(b.key, r)].Not()))
            first = m.NewBoolVar("")
            arcs.append((0, i, first))
            full = inst.setup(r, None, b)
            m.Add(s[b.key] >= ready[b.key] + hours(b, r, full)).OnlyEnforceIf(first)
            if full > EPS:
                setup_terms.append((first, int(round(full * SCALE))))
            arcs.append((i, 0, m.NewBoolVar("")))
            for k, a in enumerate(mops, start=1):
                if a.key == b.key or (a.order == b.order and a.seq > b.seq):
                    continue
                h = inst.setup(r, (a.product, a.group), b)
                lit = m.NewBoolVar("")
                arcs.append((k, i, lit))
                dh = hours(b, r, h)
                m.Add(s[b.key] >= e[a.key] + dh).OnlyEnforceIf(lit)
                m.Add(s[b.key] >= ready[b.key] + dh).OnlyEnforceIf(lit)
                if h > EPS:
                    setup_terms.append((lit, int(round(h * SCALE))))
        m.AddCircuit(arcs)

    w = lambda v: int(round(v * 100))   # noqa: E731
    terms = []
    makespan = m.NewIntVar(0, horizon * 2, "makespan")
    for j in jobs:
        if j.id not in completion:
            continue
        c = completion[j.id]
        due = int(round(j.due * SCALE))
        m.Add(makespan >= c)
        if inst.tardiness_weight > 0:
            t = m.NewIntVar(0, horizon * 2, f"t{j.id}")
            m.Add(t >= c - due)
            terms.append(w(inst.tardiness_weight * j.weight) * t)
        if inst.earliness_weight > 0:
            ea = m.NewIntVar(0, horizon * 2, f"ea{j.id}")
            m.Add(ea >= due - c)
            terms.append(w(inst.earliness_weight * j.weight) * ea)
    if inst.makespan_weight > 0:
        terms.append(w(inst.makespan_weight) * makespan)
    if inst.setup_weight > 0:
        terms += [w(inst.setup_weight) * h * lit for lit, h in setup_terms]
    m.Minimize(sum(terms))

    # warm start: the starting schedule's machines and times
    for o in ops:
        bl = blocks.get(o.key)
        if not bl:
            continue
        b0 = min(bl, key=lambda b: b.run_start)
        first = min(b.setup_start for b in bl)
        m.AddHint(s[o.key], int(round((b0.run_start if single(b0.resource) else first) * SCALE)))
        for r in cands(o):
            m.AddHint(x[(o.key, r)], int(r == b0.resource))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.5, time_limit)
    solver.parameters.num_workers = max(1, min(8, os.cpu_count() or 1))
    status = solver.Solve(m)
    info.seconds = time.perf_counter() - t0
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        info.status = "no solution"
        info.note = "The solver found no schedule in its time; the local search result is used."
        return info
    info.status = "optimal" if status == cp_model.OPTIMAL else "feasible"
    info.model_objective = solver.ObjectiveValue() / 100 / SCALE
    info.model_bound = solver.BestObjectiveBound() / 100 / SCALE

    placed: dict[str, list[tuple]] = {r: [] for r in inst.resources}
    for (k, r), lit in x.items():
        if solver.Value(lit):
            placed[r].append((solver.Value(s[k]), solver.Value(e[k]), k))
    seqs = {r: [t[-1] for t in sorted(v)] for r, v in placed.items()}
    new_hold: dict[str, float] = {}
    if inst.earliness_weight > 0:
        for j in jobs:
            if j.ops and j.id not in inst.frozen:
                first = j.ops[0]
                r = next(r for r, v in seqs.items() if first.key in v)
                t = (solver.Value(s[first.key]) - (hours(first, r, first.setup) if single(r) else 0)) / SCALE
                if t > j.release + EPS:
                    new_hold[j.id] = t
    was = {k: bl[0].resource for k, bl in blocks.items()}
    info.machines_changed = sum(1 for r, v in seqs.items() for k in v if was.get(k, r) != r)
    return seqs, new_hold, info


def optimize(inst: Instance, seqs: dict[str, list[str]], hold: dict[str, float], time_limit: float,
             searched: tuple[dict[str, list[str]], Decoded, list[float]] | None = None
             ) -> tuple[dict[str, list[str]], Decoded, dict[str, float], bool, OptInfo]:
    """The local search from the start rule (or its result, ``searched``), then rounds of: CP-SAT proposal from the
    best schedule so far (its times calibrate the model), re-timed exactly and polished, within ``time_limit``. The
    best schedule wins; the solver's is kept only when it beats the local search. Returns (sequences, decoded, hold,
    pinned, info)."""
    if searched is None:
        ls_seqs, ls_best, st = improve(inst, seqs, time_limit=time_limit, hold=hold)
        searched = (ls_seqs, ls_best, st.trace)
    t0 = time.perf_counter()
    budget = max(1.0, time_limit)
    ls_seqs, ls_best, trace = searched
    best = (ls_seqs, ls_best, hold, False)
    info = OptInfo()
    trace = list(trace)
    rounds = 0
    while rounds < 6:
        left = budget - (time.perf_counter() - t0)
        if left < 0.3:
            break
        rounds += 1
        got = solve(inst, best[1], best[2], left * 0.7)
        if isinstance(got, OptInfo):
            if rounds == 1:
                info = got
            break
        cp_seqs, cp_hold, r_info = got
        use_hold = {**hold, **cp_hold} if inst.earliness_weight > 0 else hold
        left = budget - (time.perf_counter() - t0)
        pol_seqs, pol, _ = improve(inst, cp_seqs, time_limit=max(0.1, left * 0.5), hold=use_hold, pin=True)
        r_info.seconds += info.seconds
        r_info.kept = info.kept
        info = r_info
        if pol.objective < best[1].objective - 1e-7:
            best = (pol_seqs, pol, use_hold, True)
            info.kept = True
            trace.append(pol.objective)
        else:
            break
    info.seconds = time.perf_counter() - t0
    info.trace = trace
    if not info.kept and not info.note:
        info.note = ("The solver's schedule, timed on the shift calendar, was no better than the local search's; "
                     "the local search result is used.")
    return (*best, info)


__all__ = ["OptInfo", "optimize", "solve"]
