"""A small sparse LP builder over HiGHS (highspy): named columns and rows, then optimal values,
row duals (shadow prices) and right-hand-side ranging."""
from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field

import highspy
import numpy as np

INF = math.inf


@dataclass
class Solution:
    status: str
    objective: float
    x: np.ndarray
    activity: np.ndarray
    dual: np.ndarray               # ∂objective / ∂(row bound): HiGHS convention, minimisation
    rhs_up: np.ndarray             # row bound can rise to this before the dual changes
    rhs_dn: np.ndarray             # … or fall to this
    iterations: int
    seconds: float


@dataclass
class LinearProgram:
    col_name: list[str] = field(default_factory=list)
    cost: list[float] = field(default_factory=list)
    lower: list[float] = field(default_factory=list)
    upper: list[float] = field(default_factory=list)
    row_name: list[str] = field(default_factory=list)
    row_lo: list[float] = field(default_factory=list)
    row_hi: list[float] = field(default_factory=list)
    rows: list[dict[int, float]] = field(default_factory=list)

    def var(self, name: str, cost: float = 0.0, lo: float = 0.0, hi: float = INF) -> int:
        self.col_name.append(name)
        self.cost.append(cost)
        self.lower.append(lo)
        self.upper.append(hi)
        return len(self.col_name) - 1

    def row(self, name: str, coefs: dict[int, float], lo: float = -INF, hi: float = INF) -> int:
        self.row_name.append(name)
        self.rows.append({j: v for j, v in coefs.items() if v != 0.0})
        self.row_lo.append(lo)
        self.row_hi.append(hi)
        return len(self.row_name) - 1

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.row_name), len(self.col_name)

    def solve(self, *, ranging: bool = True, time_limit: float = 60.0) -> Solution:
        t0 = time.perf_counter()
        m, n = self.shape
        cols: dict[int, list[tuple[int, float]]] = defaultdict(list)
        for i, coefs in enumerate(self.rows):
            for j, v in coefs.items():
                cols[j].append((i, v))
        start, index, value = [0], [], []
        for j in range(n):
            for i, v in sorted(cols.get(j, ())):
                index.append(i)
                value.append(v)
            start.append(len(index))
        inf = highspy.kHighsInf
        clip = lambda xs: np.array([inf if x == INF else -inf if x == -INF else x for x in xs], dtype=float)  # noqa: E731
        lp = highspy.HighsLp()
        lp.num_col_, lp.num_row_ = n, m
        lp.col_cost_ = np.array(self.cost, dtype=float)
        lp.col_lower_, lp.col_upper_ = clip(self.lower), clip(self.upper)
        lp.row_lower_, lp.row_upper_ = clip(self.row_lo), clip(self.row_hi)
        lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
        lp.a_matrix_.start_ = np.array(start, dtype=np.int32)
        lp.a_matrix_.index_ = np.array(index, dtype=np.int32)
        lp.a_matrix_.value_ = np.array(value, dtype=float)
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.setOptionValue("time_limit", float(time_limit))
        h.passModel(lp)
        h.run()
        status = h.modelStatusToString(h.getModelStatus()).lower()
        sol = h.getSolution()
        x = np.array(sol.col_value, dtype=float) if n else np.zeros(0)
        act = np.array(sol.row_value, dtype=float) if m else np.zeros(0)
        dual = np.array(sol.row_dual, dtype=float) if m else np.zeros(0)
        up = np.full(m, np.nan)
        dn = np.full(m, np.nan)
        if ranging and status == "optimal" and m:
            st, rg = h.getRanging()
            if st == highspy.HighsStatus.kOk:
                up = np.array(rg.row_bound_up.value_[:m], dtype=float)
                dn = np.array(rg.row_bound_dn.value_[:m], dtype=float)
        info = h.getInfo()
        return Solution(status, float(info.objective_function_value) if status == "optimal" else math.nan, x, act,
                        dual, up, dn, int(info.simplex_iteration_count), time.perf_counter() - t0)
