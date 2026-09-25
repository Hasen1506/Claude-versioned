"""Guaranteed-service model (Graves & Willems 2000) for multi-echelon safety-stock placement.

Every stocking stage *j* quotes an outbound service time S_j to its customers and is quoted an
inbound service time SI_j ≥ S_i by each supplier stage *i*. With replenishment lead time T_j it
must cover demand over the **net replenishment time** τ_j = SI_j + T_j − S_j ≥ 0 from stock:

    SS_j = z_j · σ_j · √τ_j        (σ_j: std of daily demand at the stage)

and the problem is  min Σ_j c_j √τ_j  with  c_j = h_j · z_j · σ_j  (holding cost per √day),
subject to demand-facing stages quoting S_j ≤ their promised service time.

A fill-rate target has no single z: the k that meets it depends on how much demand the buffer covers,
so such a stage passes its cost as a function of τ (``cost_at``). The MILP below has one binary per τ
value, so any cost curve is solved exactly.

The objective is concave, so an optimum sits at an extreme point: each stage either holds a
full buffer (S_j = 0) or passes its inbound time through (S_j = SI_j + T_j). Graves–Willems solve
spanning trees by dynamic programming; networks where a component feeds several assemblies are
not trees, so this module solves the general acyclic case **exactly** as a MILP (HiGHS via
SciPy) over integer days, with one binary per candidate τ value. ``brute_force`` enumerates
every integer S vector and is the test oracle.
"""
from __future__ import annotations

import itertools
import math
import time
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


@dataclass
class Stage:
    id: Hashable
    lead_time: int                 # T_j, whole days
    cost: float                    # c_j = h_j · z_j · σ_j, money per √day
    upstream: Sequence[Hashable] = ()
    max_service: int | None = None  # upper bound on S_j (demand-facing promise, or a planner limit)
    no_stock: bool = False         # make-to-order / pass-through: τ_j is forced to 0
    cost_at: Callable[[int], float] | None = None  # holding cost at net time τ when it is not cost·√τ

    def holding(self, tau: int) -> float:
        return self.cost_at(tau) if self.cost_at is not None else self.cost * math.sqrt(tau)


@dataclass
class Solution:
    status: str                    # optimal | infeasible | time_limit | empty
    objective: float
    service: dict[Hashable, int] = field(default_factory=dict)     # S_j
    inbound: dict[Hashable, int] = field(default_factory=dict)     # SI_j
    net: dict[Hashable, int] = field(default_factory=dict)         # τ_j
    variables: int = 0
    constraints: int = 0
    seconds: float = 0.0
    message: str = ""


def _order(stages: Sequence[Stage]) -> list[Stage]:
    """Suppliers before consumers; raises on a cycle."""
    by_id = {s.id: s for s in stages}
    done: dict[Hashable, None] = {}
    visiting: set[Hashable] = set()

    def visit(s: Stage) -> None:
        if s.id in done:
            return
        if s.id in visiting:
            raise ValueError(f"cycle through stage {s.id!r}")
        visiting.add(s.id)
        for u in s.upstream:
            if u in by_id:
                visit(by_id[u])
        visiting.discard(s.id)
        done[s.id] = None

    for s in stages:
        visit(s)
    return [by_id[i] for i in done]


def cumulative_lead_times(stages: Sequence[Stage]) -> dict[Hashable, int]:
    """M_j: the longest lead-time path ending at j — the largest τ_j can ever be."""
    m: dict[Hashable, int] = {}
    for s in _order(stages):
        m[s.id] = s.lead_time + max((m[u] for u in s.upstream if u in m), default=0)
    return m


def solve(stages: Sequence[Stage], *, time_limit: float = 30.0) -> Solution:
    t0 = time.perf_counter()
    stages = _order(stages)
    if not stages:
        return Solution("empty", 0.0)
    ids = [s.id for s in stages]
    pos = {sid: k for k, sid in enumerate(ids)}
    cum = cumulative_lead_times(stages)
    n = len(stages)
    # columns: S_j (n) | SI_j (n) | u_{j,t} for t in 0..M_j (τ one-hot; only t=0 for no-stock stages)
    tcols: list[list[int]] = []
    col = 2 * n
    for s in stages:
        width = 1 if s.no_stock else cum[s.id] + 1
        tcols.append(list(range(col, col + width)))
        col += width
    nv = col
    c = np.zeros(nv)
    lb = np.zeros(nv)
    ub = np.zeros(nv)
    integrality = np.zeros(nv)
    for k, s in enumerate(stages):
        inbound_max = cum[s.id] - s.lead_time
        smax = cum[s.id] if s.max_service is None else min(cum[s.id], max(0, s.max_service))
        if s.no_stock:
            smax = cum[s.id]  # a no-stock stage quotes its full cumulative time; promises are not binding
        ub[k] = smax
        integrality[k] = 1
        ub[n + k] = inbound_max if any(u in pos for u in s.upstream) else 0
        for t, j in enumerate(tcols[k]):
            ub[j] = 1
            integrality[j] = 1
            # tiny tie-break toward shorter net times keeps solutions deterministic when c_j = 0
            c[j] = s.holding(t) + 1e-9 * t
    rows: list[tuple[dict[int, float], float, float]] = []
    for k, s in enumerate(stages):
        for u in s.upstream:
            if u in pos:
                rows.append(({n + k: 1.0, pos[u]: -1.0}, 0.0, np.inf))          # SI_j ≥ S_i
        eq = {n + k: 1.0, k: -1.0}
        for t, j in enumerate(tcols[k]):
            eq[j] = -float(t)
        rows.append((eq, -s.lead_time, -s.lead_time))                             # SI + T − S − τ = 0
        rows.append(({j: 1.0 for j in tcols[k]}, 1.0, 1.0))                         # one τ value
    a = lil_matrix((len(rows), nv))
    lo = np.empty(len(rows))
    hi = np.empty(len(rows))
    for r, (coef, l_, h_) in enumerate(rows):
        for j, v in coef.items():
            a[r, j] = v
        lo[r], hi[r] = l_, h_
    res = milp(c, constraints=LinearConstraint(a.tocsr(), lo, hi), integrality=integrality,
               bounds=Bounds(lb, ub), options={"time_limit": time_limit, "mip_rel_gap": 1e-6, "presolve": False})
    secs = time.perf_counter() - t0
    if res.x is None:
        return Solution("infeasible", math.inf, variables=nv, constraints=len(rows), seconds=secs,
                        message=res.message)
    x = res.x
    out = Solution("optimal" if res.status == 0 else "time_limit", 0.0, variables=nv, constraints=len(rows),
                   seconds=secs, message=res.message)
    for k, s in enumerate(stages):
        tau = int(round(sum(t * x[j] for t, j in enumerate(tcols[k]))))
        out.service[s.id] = int(round(x[k]))
        out.inbound[s.id] = int(round(x[n + k]))
        out.net[s.id] = tau
    out.objective = objective(stages, out.net)
    return out


def objective(stages: Sequence[Stage], net: dict[Hashable, int]) -> float:
    return sum(s.holding(net[s.id]) for s in stages)


def brute_force(stages: Sequence[Stage]) -> Solution:
    """Enumerate every integer S vector (test oracle; exponential)."""
    stages = _order(stages)
    cum = cumulative_lead_times(stages)
    ids = [s.id for s in stages]
    ranges = []
    for s in stages:
        hi = cum[s.id] if (s.max_service is None or s.no_stock) else min(cum[s.id], s.max_service)
        ranges.append(range(hi + 1))
    best: Solution | None = None
    for combo in itertools.product(*ranges):
        svc = dict(zip(ids, combo, strict=True))
        inbound: dict[Hashable, int] = {}
        net: dict[Hashable, int] = {}
        ok = True
        for s in stages:
            si = max((svc[u] for u in s.upstream if u in svc), default=0)
            tau = si + s.lead_time - svc[s.id]
            if tau < 0 or (s.no_stock and tau != 0):
                ok = False
                break
            inbound[s.id], net[s.id] = si, tau
        if not ok:
            continue
        val = objective(stages, net)
        if best is None or val < best.objective - 1e-9:
            best = Solution("optimal", val, svc, inbound, net)
    return best or Solution("infeasible", math.inf)
