"""The scenario harness: end-to-end planning problems with hand-derived answers.

A scenario is a small, complete business problem (a network, its data and a story) plus the workflow a
planner would follow through the app, stage by stage. Every step calls the same operations the web client
calls, and records *checkpoints*: a number or fact the app must produce, the value it should be, and the
derivation that value comes from. The derivations are worked out by hand (or, where a hand solution is
impractical, by an independent formulation written in the scenario itself), never by reading the engine's
own output back.

The same scenarios run three ways:

* in the engine test suite, over HTTP, so the hand-offs between API calls are what is tested;
* from the API (``POST /api/scenarios/{id}/run``) against an isolated in-memory version store;
* in the web client's Proof page, which shows every checkpoint with its derivation.
"""
from __future__ import annotations

import datetime as dt
import math
import time
import traceback
from enum import Enum
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..actuals import ActualsView, FirmReport, RollReport, actuals_view, firm_orders, roll_forward
from ..demand import ForecastResult, ReleaseResult, release, run_forecast
from ..finance import FinanceResult, run_finance
from ..inventory import InventoryResult, run_inventory
from ..model import Dataset, DemandRecord
from ..model.common import Out
from ..plan import PlanResult, run_mrp
from ..promise import PromiseResult, check_order, commit, run_bop, run_promise
from ..schedule import ScheduleResult, run_schedule
from ..sop import SopRelease, SopResult, release_sop, run_sop
from ..tower import TowerResult, run_tower
from ..tower.worklist import Tracker
from ..validate import Issue, validate
from ..versions import Comparison, Store, VersionDoc, VersionMeta, compare
from ..versions.store import VersionError


# ---- report schema ---------------------------------------------------------------------------------------
class Check(Out):
    label: str
    expected: Any
    actual: Any
    tolerance: float | None = None
    passed: bool
    why: str = ""


class StepReport(Out):
    n: int
    title: str
    stage: str                  # the app stage the step belongs to (web route id)
    call: str                   # the API operation(s) the step makes
    narrative: str
    checks: list[Check] = []
    error: str | None = None
    seconds: float = 0.0


class ScenarioInfo(Out):
    id: str
    title: str
    company: str
    story: str
    proves: list[str]
    stages: list[str]
    found: list[str] = []      # defects this scenario exposed (each has a regression test)


class ScenarioReport(Out):
    id: str
    title: str
    client: str
    ok: bool
    passed: int
    failed: int
    seconds: float
    steps: list[StepReport]


# ---- the operations a scenario may call ------------------------------------------------------------------
class ClientError(Exception):
    """A request the application refused (an HTTP 4xx): ``message`` is what the planner would be told."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Client(Protocol):
    name: str

    def validate(self, ds: Dataset) -> list[Issue]: ...
    def network(self, ds: Dataset) -> Any: ...
    def forecast(self, ds: Dataset) -> ForecastResult: ...
    def release_forecast(self, ds: Dataset, keys: list[str] | None = None) -> tuple[Dataset, ReleaseResult]: ...
    def inventory(self, ds: Dataset) -> InventoryResult: ...
    def sop(self, ds: Dataset) -> SopResult: ...
    def release_sop(self, ds: Dataset) -> tuple[Dataset, SopRelease]: ...
    def plan(self, ds: Dataset) -> PlanResult: ...
    def schedule(self, ds: Dataset, sequence: dict[str, list[str]] | None = None) -> ScheduleResult: ...
    def promise(self, ds: Dataset) -> PromiseResult: ...
    def bop(self, ds: Dataset) -> PromiseResult: ...
    def check(self, ds: Dataset, order: DemandRecord) -> PromiseResult: ...
    def commit(self, ds: Dataset, mode: str = "entry") -> tuple[Dataset, PromiseResult]: ...
    def firm(self, ds: Dataset, ids: list[str] | None = None, within_days: int | None = None) -> tuple[Dataset, FirmReport]: ...
    def actuals(self, ds: Dataset, as_of: dt.date | None = None) -> ActualsView: ...
    def roll(self, ds: Dataset, as_of: dt.date) -> tuple[Dataset, RollReport]: ...
    def finance(self, ds: Dataset) -> FinanceResult: ...
    def tower(self, ds: Dataset) -> TowerResult: ...
    def save_base(self, ds: Dataset, name: str, note: str = "") -> VersionMeta: ...
    def branch(self, vid: str, name: str, note: str = "") -> VersionMeta: ...
    def update_version(self, vid: str, ds: Dataset) -> VersionMeta: ...
    def get_version(self, vid: str) -> VersionDoc: ...
    def discard(self, vid: str) -> VersionMeta: ...
    def promote(self, vid: str, name: str | None = None) -> VersionMeta: ...
    def compare_versions(self, a: str, b: str) -> Comparison: ...


class EngineClient:
    """Calls the engine directly, with its own version store so a run never touches the user's data."""

    name = "engine"

    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store(":memory:")
        self.tracker = Tracker(self.store)

    def validate(self, ds: Dataset) -> list[Issue]:
        return validate(ds)

    def network(self, ds: Dataset) -> Any:
        from ..api.app import post_network   # the view is assembled in the API layer
        return post_network(ds)

    def forecast(self, ds: Dataset) -> ForecastResult:
        return run_forecast(ds)

    def release_forecast(self, ds: Dataset, keys: list[str] | None = None) -> tuple[Dataset, ReleaseResult]:
        res = run_forecast(ds)
        if not res.ok:
            raise RuntimeError("the readiness gate has errors; fix them before releasing a forecast")
        return release(ds, res, keys)

    def inventory(self, ds: Dataset) -> InventoryResult:
        return run_inventory(ds)

    def sop(self, ds: Dataset) -> SopResult:
        return run_sop(ds)

    def release_sop(self, ds: Dataset) -> tuple[Dataset, SopRelease]:
        res = run_sop(ds)
        if not res.ok:
            raise RuntimeError("the S&OP plan did not solve")
        return release_sop(ds, res)

    def plan(self, ds: Dataset) -> PlanResult:
        return run_mrp(ds)

    def schedule(self, ds: Dataset, sequence: dict[str, list[str]] | None = None) -> ScheduleResult:
        return run_schedule(ds, sequence)

    def promise(self, ds: Dataset) -> PromiseResult:
        return run_promise(ds)

    def bop(self, ds: Dataset) -> PromiseResult:
        return run_bop(ds)

    def check(self, ds: Dataset, order: DemandRecord) -> PromiseResult:
        return check_order(ds, order)

    def commit(self, ds: Dataset, mode: str = "entry") -> tuple[Dataset, PromiseResult]:
        new, res = commit(ds, mode)
        if not res.ok:
            raise RuntimeError("the readiness gate has errors")
        return new, res

    def firm(self, ds: Dataset, ids: list[str] | None = None, within_days: int | None = None) -> tuple[Dataset, FirmReport]:
        return firm_orders(ds, run_mrp(ds), ids, within_days)

    def actuals(self, ds: Dataset, as_of: dt.date | None = None) -> ActualsView:
        return actuals_view(ds, as_of)

    def roll(self, ds: Dataset, as_of: dt.date) -> tuple[Dataset, RollReport]:
        new, rep = roll_forward(ds, as_of)
        if not rep.ok:
            raise RuntimeError("; ".join(rep.warnings))
        return new, rep

    def finance(self, ds: Dataset) -> FinanceResult:
        return run_finance(ds)

    def tower(self, ds: Dataset) -> TowerResult:
        return run_tower(ds, tracker=self.tracker, store=self.store)

    def save_base(self, ds: Dataset, name: str, note: str = "") -> VersionMeta:
        return self._v(self.store.save_base, ds, name, note)

    def branch(self, vid: str, name: str, note: str = "") -> VersionMeta:
        return self._v(self.store.branch, vid, name, note)

    def update_version(self, vid: str, ds: Dataset) -> VersionMeta:
        return self._v(self.store.update, vid, ds)

    def get_version(self, vid: str) -> VersionDoc:
        return self._v(self.store.get, vid)

    def discard(self, vid: str) -> VersionMeta:
        return self._v(self.store.discard, vid)

    def promote(self, vid: str, name: str | None = None) -> VersionMeta:
        return self._v(self.store.promote, vid, name, "")

    def compare_versions(self, a: str, b: str) -> Comparison:
        return compare(self._v(self.store.dataset, a), self._v(self.store.dataset, b), a, b)

    @staticmethod
    def _v(fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except VersionError as e:
            raise ClientError(e.status, str(e)) from e


# ---- recording checkpoints -------------------------------------------------------------------------------
class _Abort(Exception):
    """A step failed with an error: later steps depend on it, so the scenario stops."""


def _plain(v: Any) -> Any:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {"/".join(map(str, k)) if isinstance(k, tuple) else str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, Enum) and isinstance(v.value, str):   # enums
        return v.value
    return v


def _close(a: Any, b: Any, tol: float) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], tol) for k in a)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= tol
    return a == b


class Ctx:
    def __init__(self) -> None:
        self.steps: list[StepReport] = []

    @contextmanager
    def step(self, title: str, stage: str, call: str, narrative: str = "") -> Iterator[StepReport]:
        rep = StepReport(n=len(self.steps) + 1, title=title, stage=stage, call=call, narrative=narrative)
        self.steps.append(rep)
        t0 = time.perf_counter()
        try:
            yield rep
        except _Abort:
            raise
        except Exception as e:  # noqa: BLE001 — any failure is reported, then the scenario stops
            rep.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}"
            raise _Abort from e
        finally:
            rep.seconds = time.perf_counter() - t0

    def _add(self, c: Check) -> bool:
        if not self.steps:
            raise RuntimeError("a checkpoint must be inside a step")
        self.steps[-1].checks.append(c)
        return c.passed

    def eq(self, label: str, actual: Any, expected: Any, why: str = "") -> bool:
        a, e = _plain(actual), _plain(expected)
        return self._add(Check(label=label, expected=e, actual=a, passed=a == e, why=why))

    def near(self, label: str, actual: Any, expected: Any, tol: float = 1e-6, why: str = "") -> bool:
        a, e = _plain(actual), _plain(expected)
        return self._add(Check(label=label, expected=e, actual=a, tolerance=tol, passed=_close(a, e, tol), why=why))

    def true(self, label: str, cond: bool, why: str = "", actual: Any = None, expect: str = "holds") -> bool:
        """A condition rather than a value: ``expect`` says in words what must hold, ``actual`` is the evidence."""
        shown = _plain(actual) if actual is not None else ("holds" if cond else "does not hold")
        return self._add(Check(label=label, expected=expect, actual=shown, passed=bool(cond), why=why))

    def raises(self, label: str, call: Callable[[], Any], status: int, contains: str, why: str = "") -> bool:
        """The application must refuse ``call`` with ``status`` and a message containing ``contains``."""
        expected = f"refused ({status}): …{contains}…"
        try:
            call()
        except ClientError as e:
            ok = e.status == status and contains in e.message
            return self._add(Check(label=label, expected=expected, actual=f"refused ({e.status}): {e.message}",
                                   passed=ok, why=why))
        return self._add(Check(label=label, expected=expected, actual="accepted", passed=False, why=why))


# ---- scenario definition ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    company: str
    story: str
    proves: list[str]
    stages: list[str]
    build: Callable[[], dict]
    run: Callable[[Ctx, Client, Dataset], None]
    tags: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)

    def dataset(self) -> Dataset:
        return Dataset.model_validate(self.build())

    def info(self) -> ScenarioInfo:
        return ScenarioInfo(id=self.id, title=self.title, company=self.company, story=self.story,
                            proves=self.proves, stages=self.stages, found=self.found)

    def execute(self, client: Client | None = None) -> ScenarioReport:
        client = client or EngineClient()
        ctx = Ctx()
        t0 = time.perf_counter()
        try:
            self.run(ctx, client, self.dataset())
        except _Abort:
            pass
        passed = sum(c.passed for s in ctx.steps for c in s.checks)
        failed = sum(not c.passed for s in ctx.steps for c in s.checks) + sum(1 for s in ctx.steps if s.error)
        return ScenarioReport(id=self.id, title=self.title, client=client.name, ok=failed == 0, passed=passed,
                              failed=failed, seconds=time.perf_counter() - t0, steps=ctx.steps)


# ---- small helpers the scenarios share ---------------------------------------------------------------------
def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def by(items: list, **match: Any) -> list:
    """Items whose attributes equal every keyword (``by(plan.orders, product="X", kind="make")``)."""
    return [x for x in items if all(getattr(x, k) == v for k, v in match.items())]


def one(items: list, **match: Any) -> Any:
    got = by(items, **match)
    if len(got) != 1:
        raise LookupError(f"expected exactly one item matching {match}, found {len(got)}")
    return got[0]
