"""Finite detailed scheduling (S/4 guide §8 PP-DS): a sequence decoder, the EDD baseline, a
campaign / swap local search and an independent feasibility checker.

The solution representation is one *priority sequence per resource* (a list of operation keys).
The decoder turns it into a semi-active schedule:

* an operation may start once its order is released and its predecessor operation (plus the
  queue time after it) is finished;
* it runs on the resource unit that finishes it earliest; long operations are split into equal
  sublots over up to ``parallel_units`` units, each sublot with its own setup;
* setup depends on what ran last on that unit: nothing → full setup; same product → none; same
  setup group → ``minor_setup_factor`` × setup; otherwise the changeover matrix, else full setup;
* work only happens inside shift windows (``ResourceClock``).

Each resource takes the operations in its sequence order. When the head of a sequence is not
ready and no other resource can move, the earliest-ranked *ready* operation is taken instead, so a
sequence produced by the local search can never deadlock.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .clock import EPS, INF, ResourceClock


@dataclass
class Res:
    id: str
    units: int
    clock: ResourceClock
    finite: bool = True
    clocks: list[ResourceClock] | None = None   # one per unit when units come and go over time

    def at(self, unit: int) -> ResourceClock:
        """The working time of one unit (an infinite resource, unit -1, works to the first unit's clock)."""
        if self.clocks is None or unit < 0:
            return self.clock
        return self.clocks[unit]


@dataclass
class OpSpec:
    key: str                 # "<order>:<seq>"
    order: str
    seq: int
    resource: str
    product: str
    group: str
    qty: float
    setup: float             # full setup, productive hours
    run: float               # run hours for the whole quantity
    queue_workdays: float = 0.0
    parallel: int | None = None
    labor_resource: str | None = None
    labor_hours: float = 0.0
    alternatives: list[str] = field(default_factory=list)   # other resources that can run it, same times
    send_ahead: float | None = None     # overlap: the next step may start once this many units are done


@dataclass
class Job:
    id: str
    product: str
    release: float           # clock hours
    due: float
    ops: list[OpSpec]
    weight: float = 1.0


SetupFn = Callable[[str, tuple[str, str] | None, OpSpec], float]
QueueFn = Callable[[OpSpec, float], float]


@dataclass
class Instance:
    resources: dict[str, Res]
    jobs: dict[str, Job]
    setup: SetupFn           # (resource, (prev product, prev group) | None, op) -> setup hours
    after: QueueFn           # (op, end) -> earliest start of the next op of the order
    tardiness_weight: float = 1.0
    setup_weight: float = 1.0

    def op(self, key: str) -> OpSpec:
        order, seq = key.rsplit(":", 1)
        return next(o for o in self.jobs[order].ops if o.seq == int(seq))


def setup_rule(changeovers: dict[tuple[str | None, str, str], float], minor: float) -> SetupFn:
    def fn(resource: str, prev: tuple[str, str] | None, op: OpSpec) -> float:
        if prev is None:
            return op.setup
        product, group = prev
        if product == op.product:
            return 0.0
        if group == op.group:
            return op.setup * minor
        for k in ((resource, group, op.group), (None, group, op.group)):
            if k in changeovers:
                return changeovers[k]
        return op.setup
    return fn


@dataclass
class Block:
    key: str
    sub: int
    resource: str
    unit: int
    qty: float
    setup_start: float
    run_start: float
    end: float
    setup_work: float
    run_work: float
    prev: tuple[str, str] | None


@dataclass
class Decoded:
    blocks: list[Block]
    op_end: dict[str, float]
    completion: dict[str, float]
    realized: dict[str, list[str]]
    tardiness: float = 0.0
    setup_hours: float = 0.0
    changeovers: int = 0
    late_jobs: int = 0
    max_lateness: float = 0.0
    makespan: float = 0.0
    objective: float = 0.0


def handoff(inst: Instance, o: OpSpec, bl: list[Block], nxt: OpSpec | None) -> tuple[float, float]:
    """When the next step of the order may start, and the earliest it may end.

    Without overlap the next step starts after this one ends (and its queue). With a send-ahead quantity it may
    start once the first sublot has made that many (plus the queue), but it cannot end before this step's end
    plus the time it needs for the last send-ahead batch."""
    end = max(b.end for b in bl)
    after_end = inst.after(o, end)
    if not o.send_ahead or nxt is None or not bl:
        return after_end, 0.0
    first = min(bl, key=lambda b: (b.run_start, b.unit))
    res = inst.resources[first.resource]
    frac = min(1.0, o.send_ahead / first.qty) if first.qty > 0 else 1.0
    _, done = res.at(first.unit if res.finite else -1).advance(first.run_start, first.run_work * frac)
    ready = min(after_end, inst.after(o, done))
    tail = nxt.run * min(1.0, o.send_ahead / nxt.qty) if nxt.qty > 0 else 0.0
    _, must = inst.resources[nxt.resource].clock.advance(after_end, tail)
    return ready, must


def is_changeover(b: Block, o: OpSpec) -> bool:
    return b.prev is not None and b.prev[1] != o.group and b.setup_work > EPS


def decode(inst: Instance, seqs: dict[str, list[str]]) -> Decoded:
    ops = {o.key: o for j in inst.jobs.values() for o in j.ops}
    prev_of: dict[str, str | None] = {}
    next_of: dict[str, OpSpec | None] = {}
    for j in inst.jobs.values():
        for a, b in zip([None, *j.ops[:-1]], j.ops, strict=True):
            prev_of[b.key] = a.key if a else None
            if a is not None:
                next_of[a.key] = b
        if j.ops:
            next_of[j.ops[-1].key] = None
    must_end: dict[str, float] = {}
    pending = {r: [k for k in s if k in ops] for r, s in seqs.items()}
    free = {r: [0.0] * (res.units if res.finite else 0) for r, res in inst.resources.items()}
    state: dict[str, list[tuple[str, str] | None]] = {r: [None] * len(free[r]) for r in free}
    ready_at: dict[str, float] = {}
    op_end: dict[str, float] = {}
    blocks: list[Block] = []
    realized: dict[str, list[str]] = {r: [] for r in inst.resources}

    def ready(k: str) -> bool:
        p = prev_of[k]
        return p is None or p in op_end

    def trial(o: OpSpec, rid: str, res: Res, t0: float, n: int) -> list[tuple]:
        """Greedy placement of ``n`` equal sublots, each on the unit that finishes it first."""
        fr = list(free[rid])
        stt = list(state[rid])
        out = []
        for _ in range(n):
            best: tuple | None = None
            for u in (range(len(fr)) if res.finite else [-1]):
                prev = stt[u] if u >= 0 else None
                su = inst.setup(rid, prev, o)
                clk = res.at(u)
                s0, s1 = clk.advance(max(t0, fr[u]) if u >= 0 else t0, su)
                r0, r1 = clk.advance(s1, o.run / n)
                if best is None or (r1, u) < best[:2]:
                    best = (r1, u, s0, r0, su, prev)
            if best[0] == INF:
                raise ValueError(f"{rid} has no working time left for {o.key}")
            if best[1] >= 0:
                fr[best[1]] = best[0]
                stt[best[1]] = (o.product, o.group)
            out.append(best)
        return out

    def place(k: str) -> None:
        o = ops[k]
        job = inst.jobs[o.order]
        p = prev_of[k]
        t0 = job.release if p is None else ready_at[p]
        must = must_end.get(k, 0.0)

        # split over parallel units only when the elapsed time saved exceeds the setup time added
        def score(pl: list[tuple]) -> float:
            return max(c[0] for c in pl) + sum(c[4] for c in pl)

        def split(rid: str, start: float) -> list[tuple]:
            res = inst.resources[rid]
            allowed = min(o.parallel or res.units, res.units) if res.finite else 1
            plan = trial(o, rid, res, start, 1)
            if o.run > EPS:
                for n in range(2, allowed + 1):
                    cand = trial(o, rid, res, start, n)
                    if score(cand) < score(plan) - 1e-6:
                        plan = cand
            return plan

        best: tuple | None = None
        for rank, rid in enumerate([o.resource, *(a for a in o.alternatives if a in inst.resources)]):
            start = t0
            plan = split(rid, start)
            for _ in range(6):   # overlapped: do not finish before the step before can hand over its last batch
                end = max(c[0] for c in plan)
                if end >= must - 1e-6 or end == INF:
                    break
                start += must - end
                plan = split(rid, start)
            key = (max(c[0] for c in plan), rank)
            if best is None or key < best[0]:
                best = (key, rid, plan)
        _, rid, plan = best
        n = len(plan)
        for sub, (r1, u, s0, r0, su, prev) in enumerate(plan):
            if u >= 0:
                free[rid][u] = r1
                state[rid][u] = (o.product, o.group)
            else:
                u = len(blocks)
            blocks.append(Block(k, sub, rid, u, o.qty / n, s0, r0, r1, su, o.run / n, prev))
        end_all = max(c[0] for c in plan)
        op_end[k] = end_all
        nxt = next_of.get(k)
        ready_at[k], m = handoff(inst, o, blocks[-n:], nxt)
        if nxt is not None and m:
            must_end[nxt.key] = m
        realized[rid].append(k)

    while any(pending.values()):
        moved = False
        for r in sorted(pending):
            q = pending[r]
            while q and ready(q[0]):
                place(q.pop(0))
                moved = True
        if moved:
            continue
        # every head waits on another resource: take the earliest-ranked ready operation
        best = min(((i, r) for r, q in pending.items() for i, k in enumerate(q) if ready(k)), default=None)
        if best is None:
            raise ValueError("operation sequence has an order whose operations are missing")
        i, r = best
        place(pending[r].pop(i))

    d = Decoded(blocks, op_end, {}, realized)
    lateness: list[float] = []
    for j in inst.jobs.values():
        if not j.ops:
            continue
        last = j.ops[-1].key
        c = ready_at[last]
        d.completion[j.id] = c
        late = c - j.due
        d.tardiness += j.weight * max(0.0, late)
        if late > EPS:
            d.late_jobs += 1
        lateness.append(late)
        d.makespan = max(d.makespan, c)
    d.max_lateness = max(lateness, default=0.0)
    for b in blocks:
        d.setup_hours += b.setup_work
        if is_changeover(b, ops[b.key]):
            d.changeovers += 1
    d.objective = inst.tardiness_weight * d.tardiness + inst.setup_weight * d.setup_hours
    return d


def edd(inst: Instance) -> dict[str, list[str]]:
    """Earliest-due-date priority per resource (ties: release, order id, operation)."""
    seqs: dict[str, list[tuple]] = {r: [] for r in inst.resources}
    for j in inst.jobs.values():
        for o in j.ops:
            seqs[o.resource].append((j.due, j.release, j.id, o.seq, o.key))
    return {r: [t[-1] for t in sorted(v)] for r, v in seqs.items()}


def complete(inst: Instance, manual: dict[str, list[str]]) -> dict[str, list[str]]:
    """A user sequence: known keys in the given order, then anything left out in EDD order."""
    base = edd(inst)
    out: dict[str, list[str]] = {}
    for r, keys in base.items():
        given = [k for k in manual.get(r, []) if k in set(keys)]
        seen = set(given)
        out[r] = list(dict.fromkeys(given)) + [k for k in keys if k not in seen]
    return out


@dataclass
class SearchStats:
    tried: int = 0
    accepted: int = 0
    passes: int = 0
    seconds: float = 0.0
    stopped: str = "converged"
    trace: list[float] = field(default_factory=list)


def _moves(inst: Instance, seq: list[str], reach: int = 4) -> list[list[str]]:
    """Campaign moves first (pull an operation behind the nearest earlier one of its setup group),
    then insertions of each operation up to ``reach`` positions earlier or later (reach 1 = swap)."""
    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = {tuple(seq)}

    def add(s: list[str]) -> None:
        t = tuple(s)
        if t not in seen:
            seen.add(t)
            out.append(s)

    group = [inst.op(k).group for k in seq]
    for i in range(2, len(seq)):
        if group[i - 1] == group[i]:
            continue
        j = next((j for j in range(i - 2, -1, -1) if group[j] == group[i]), None)
        if j is not None:
            add(seq[:j + 1] + [seq[i]] + seq[j + 1:i] + seq[i + 1:])
    for d in range(1, reach + 1):
        for i in range(len(seq)):
            for j in (i - d, i + d):
                if 0 <= j < len(seq):
                    rest = seq[:i] + seq[i + 1:]
                    add(rest[:j] + [seq[i]] + rest[j:])
    return out


def improve(inst: Instance, seqs: dict[str, list[str]], *, time_limit: float = 4.0,
            max_passes: int = 200) -> tuple[dict[str, list[str]], Decoded, SearchStats]:
    """First-improvement local search on the weighted objective. Never returns a sequence worse
    than the one it started from."""
    t0 = time.perf_counter()
    st = SearchStats()
    cur = {r: list(s) for r, s in seqs.items()}
    best = decode(inst, cur)
    st.trace.append(best.objective)
    while st.passes < max_passes:
        st.passes += 1
        found = False
        for r in sorted(cur):
            for cand in _moves(inst, cur[r]):
                if time.perf_counter() - t0 > time_limit:
                    st.stopped = "time_limit"
                    st.seconds = time.perf_counter() - t0
                    return cur, best, st
                st.tried += 1
                trial = dict(cur)
                trial[r] = cand
                d = decode(inst, trial)
                if d.objective < best.objective - 1e-7:
                    cur, best = trial, d
                    st.accepted += 1
                    st.trace.append(best.objective)
                    found = True
                    break
        if not found:
            break
    st.seconds = time.perf_counter() - t0
    return cur, best, st


def check(inst: Instance, d: Decoded) -> list[str]:
    """Independent feasibility check of a decoded schedule. Returns human-readable violations."""
    v: list[str] = []
    ops = {o.key: o for j in inst.jobs.values() for o in j.ops}
    by_unit: dict[tuple[str, int], list[Block]] = {}
    subs: dict[str, list[Block]] = {}
    for b in d.blocks:
        o = ops[b.key]
        res = inst.resources[b.resource]
        clk = res.at(b.unit if res.finite else -1)
        if abs(clk.next_open(b.setup_start) - b.setup_start) > 1e-6:
            v.append(f"{b.key}/{b.sub}: starts outside a shift window on {b.resource}")
        if b.run_start < b.setup_start - 1e-6 or b.end < b.run_start - 1e-6:
            v.append(f"{b.key}/{b.sub}: times out of order")
        if abs(clk.work_between(b.setup_start, b.run_start) - b.setup_work) > 1e-5:
            v.append(f"{b.key}/{b.sub}: setup does not fit the working time between its start and run start")
        if abs(clk.work_between(b.run_start, b.end) - b.run_work) > 1e-5:
            v.append(f"{b.key}/{b.sub}: run time does not match the working time in its window")
        if abs(inst.setup(b.resource, b.prev, o) - b.setup_work) > 1e-6:
            v.append(f"{b.key}/{b.sub}: setup {b.setup_work:.2f} h breaks the setup rule")
        if res.finite:
            by_unit.setdefault((b.resource, b.unit), []).append(b)
        subs.setdefault(b.key, []).append(b)
    for (r, u), bl in by_unit.items():
        bl.sort(key=lambda b: b.setup_start)
        for a, b in zip(bl, bl[1:], strict=False):
            if b.setup_start < a.end - 1e-6:
                v.append(f"{r} unit {u + 1}: {a.key} and {b.key} overlap")
            if b.prev != (ops[a.key].product, ops[a.key].group):
                v.append(f"{r} unit {u + 1}: {b.key} set up from the wrong predecessor")
        if bl and bl[0].prev is not None:
            v.append(f"{r} unit {u + 1}: first job {bl[0].key} claims a predecessor")
    for j in inst.jobs.values():
        prev_ready, prev_must = j.release, 0.0
        for i, o in enumerate(j.ops):
            bl = subs.get(o.key, [])
            if abs(sum(b.qty for b in bl) - o.qty) > 1e-6 * max(1.0, o.qty):
                v.append(f"{o.key}: scheduled quantity differs from the order")
                continue
            if bl and min(b.setup_start for b in bl) < prev_ready - 1e-6:
                v.append(f"{o.key}: starts before its order release / predecessor")
            if bl and prev_must and max(b.end for b in bl) < prev_must - 1e-6:
                v.append(f"{o.key}: ends before the overlapped step before it can hand over its last batch")
            if o.resource != (bl[0].resource if bl else o.resource) and bl[0].resource not in o.alternatives:
                v.append(f"{o.key}: runs on {bl[0].resource}, which is not its resource or an alternative")
            nxt = j.ops[i + 1] if i + 1 < len(j.ops) else None
            if bl:
                prev_ready, prev_must = handoff(inst, o, bl, nxt)
            else:
                prev_ready, prev_must = inst.after(o, prev_ready), 0.0
        if j.ops and abs(d.completion.get(j.id, -1) - prev_ready) > 1e-6:
            v.append(f"{j.id}: completion time inconsistent")
    return v
