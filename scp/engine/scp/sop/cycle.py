"""The monthly S&OP cycle (S/4 guide §4): data → demand review → supply review → pre-S&OP → executive S&OP.

Each step has an owner and is signed off in order. A sign-off freezes the company as it was signed (an immutable
base version in the version store) and records the step's figures: the plan month by month, volume and revenue,
against the budget. Reopening a step reopens every later one; the frozen versions stay as they were. The executive
sign-off closes the cycle. Sign-offs are events in the world, so their clock is the wall clock (not the planning
start), and they are kept outside the company's data: undoing an edit never undoes a sign-off.
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import re
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass

from ..model import Dataset
from ..model.common import BucketSize, Out
from ..plan.rates import independent_demand
from ..time import Buckets
from ..validate import validate
from ..versions import VersionError
from ..versions.store import Store, get_store
from .plan import run_sop

STEPS = ("data", "demand", "supply", "pre", "exec")
LABELS = {"data": "Data", "demand": "Demand review", "supply": "Supply review", "pre": "Pre-S&OP",
          "exec": "Executive S&OP"}
SUPPLY = {"supply", "pre", "exec"}       # steps whose figures carry the constrained plan
MINUTES = {"pre", "exec"}                # steps signed with what was decided
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sop_cycles (
  id TEXT PRIMARY KEY, scope TEXT NOT NULL, month TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
  created_at TEXT NOT NULL, created_by TEXT NOT NULL DEFAULT '', UNIQUE (scope, month)
);
CREATE TABLE IF NOT EXISTS sop_steps (
  cycle_id TEXT NOT NULL REFERENCES sop_cycles(id), step TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('open', 'signed')), signed_by TEXT NOT NULL DEFAULT '', signed_at TEXT,
  note TEXT NOT NULL DEFAULT '', version_id TEXT, figures TEXT NOT NULL DEFAULT '', PRIMARY KEY (cycle_id, step)
);
CREATE TABLE IF NOT EXISTS sop_cycle_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
);
"""


# ------------------------------------------------------------------------------------------------ figures
class MonthFigures(Out):
    month: str                      # 2026-10
    label: str                      # Oct 2026, or "from 14 Oct 2026" when the plan starts inside it
    share: float                    # part of the month inside the plan (the budget is counted by it)
    budget_qty: float
    budget_revenue: float
    demand_qty: float
    demand_revenue: float
    supply_qty: float | None = None
    supply_revenue: float | None = None


class FamilyFigures(Out):
    family: str                     # "" = products without a family, or a budget for the whole company
    budget_qty: float
    budget_revenue: float
    demand_qty: float
    demand_revenue: float
    supply_qty: float | None = None
    supply_revenue: float | None = None


class Figures(Out):
    step: str
    currency: str
    planning_start: dt.date
    months: list[MonthFigures]
    families: list[FamilyFigures]
    blocking: int                   # readiness errors (the data step cannot be signed with any)
    warnings: int
    history_to: dt.date | None = None
    fill_rate: float | None = None  # supply steps: share of demand the constrained plan serves
    limits: list[str] = []          # supply steps: the tightest limits, tightest first
    unpriced: list[str] = []        # products in the demand without a selling price: no revenue counted
    budgets: int = 0                # budget records that fall inside the plan
    notes: list[str] = []


def _months(ds: Dataset) -> Buckets:
    return Buckets(ds.settings.model_copy(update={"bucket": BucketSize.MONTH}))


def _family(ds: Dataset, product: str | None) -> str:
    p = ds.product_by_id.get(product or "")
    return p.family if p else ""


def figures(ds: Dataset, step: str) -> Figures:
    """The step's figures for ``ds``: budget, demand and (from the supply review on) the constrained plan, month by
    month and by product family. Demand is what MRP plans to: the released forecast after consumption by orders,
    plus the orders."""
    if step not in STEPS:
        raise VersionError(f"no step '{step}'", 404)
    issues = validate(ds)
    bk = _months(ds)
    T = len(bk)
    keys = [b.start.strftime("%Y-%m") for b in bk]
    month_days = [calendar.monthrange(b.start.year, b.start.month)[1] for b in bk]
    out = Figures(step=step, currency=ds.settings.currency, planning_start=ds.settings.planning_start, months=[],
                  families=[], blocking=sum(i.severity == "error" for i in issues),
                  warnings=sum(i.severity == "warning" for i in issues),
                  history_to=max((h.date for h in ds.history), default=None))
    zero = lambda: [0.0] * T  # noqa: E731
    bq, br, dq, dr = zero(), zero(), zero(), zero()
    fam: dict[str, list[float]] = defaultdict(lambda: [0.0] * 6)   # bq br dq dr sq sr

    # budget: counted for the part of each month inside the plan
    index = {k: t for t, k in enumerate(keys)}
    for b in ds.budgets:
        t = index.get(b.month.strftime("%Y-%m"))
        if t is None:
            continue
        out.budgets += 1
        share = bk[t].days / month_days[t]
        rev = b.revenue
        if rev is None and b.product is not None:
            p = ds.product_by_id.get(b.product)
            rev = b.qty * p.price if p is not None and p.price is not None else 0.0
        q, r = b.qty * share, (rev or 0.0) * share
        bq[t] += q
        br[t] += r
        f = fam[b.family if b.family is not None else _family(ds, b.product)]
        f[0] += q
        f[1] += r

    # demand, spread as the S&OP plan spreads it: a forecast over its period, an order past due in the first month
    records = {d.id or f"#{i}": d for i, d in enumerate(ds.demand)}
    unpriced: set[str] = set()
    for (loc, prod), reqs in independent_demand(ds).items():
        f = fam[_family(ds, prod)]
        for r, span in reqs:
            price = ds.selling_price(loc, prod, records[r.source_ref].price)
            if price is None:
                unpriced.add(prod)
            if r.kind == "forecast":
                parts = [(b.index, r.qty * ov / span) for b in bk
                         if (ov := (min(r.date + dt.timedelta(days=span), b.end) - max(r.date, b.start)).days) > 0]
            else:
                t = 0 if r.date < bk.start else bk.index_of(r.date)
                parts = [(t, r.qty)] if 0 <= t < T else []
            for t, q in parts:
                dq[t] += q
                dr[t] += q * (price or 0.0)
                f[2] += q
                f[3] += q * (price or 0.0)
    out.unpriced = sorted(unpriced)

    sq: list[float] | None = None
    sr: list[float] | None = None
    if step in SUPPLY:
        res = run_sop(ds.model_copy(update={"sop": ds.sop.model_copy(update={"bucket": BucketSize.MONTH})}))
        if not res.ok:
            out.notes.append("The capacity plan did not solve: " + (" ".join(res.notes) or "fix the blocking issues"))
        else:
            sq, sr = zero(), zero()
            own = {(d.location, d.product) for d in ds.demand if d.price is not None}
            for line in res.demand:
                # an unpriced line's price is its value at cost: sales of it are no revenue
                priced = (line.location, line.product) in own or ds.selling_price(line.location, line.product) is not None
                f = fam[_family(ds, line.product)]
                for t, s in enumerate(line.sales[:T]):
                    sq[t] += s
                    f[4] += s
                    if priced:
                        sr[t] += s * line.price
                        f[5] += s * line.price
            out.fill_rate = res.kpis.fill_rate if res.kpis else None
            out.limits = [b.label for b in res.binding[:3]]
            k = ds.sop.demand_factor
            if k != 1:              # the plan's scenario lever: demand here is the demand that plan supplies
                dq, dr = [x * k for x in dq], [x * k for x in dr]
                for v in fam.values():
                    v[2] *= k
                    v[3] *= k
                out.notes.append(f"Demand is scaled by {k:g} (a scenario lever of the capacity plan): demand and "
                                 "supply here are that scenario's.")
    for t, b in enumerate(bk):
        share = b.days / month_days[t]
        label = b.start.strftime("%b %Y") if share >= 1 else (
            f"from {b.start.day} {b.start:%b %Y}" if b.start.day > 1 else f"to {b.end - dt.timedelta(days=1):%d %b %Y}")
        out.months.append(MonthFigures(
            month=keys[t], label=label, share=round(share, 4), budget_qty=round(bq[t], 4),
            budget_revenue=round(br[t], 2), demand_qty=round(dq[t], 4), demand_revenue=round(dr[t], 2),
            supply_qty=None if sq is None else round(sq[t], 4), supply_revenue=None if sr is None else round(sr[t], 2)))
    for name in sorted(fam):
        v = fam[name]
        out.families.append(FamilyFigures(
            family=name, budget_qty=round(v[0], 4), budget_revenue=round(v[1], 2), demand_qty=round(v[2], 4),
            demand_revenue=round(v[3], 2), supply_qty=None if sq is None else round(v[4], 4),
            supply_revenue=None if sr is None else round(v[5], 2)))
    if not ds.budgets:
        out.notes.append("No budget in the data: add one under Data → Budgets to see the plan against it.")
    return out


# ------------------------------------------------------------------------------------------------ the cycle
@dataclass(frozen=True)
class Actor:
    """Who acts: an e-mail (empty: this browser) and their role in the company (``owner`` in one's own space)."""
    email: str
    role: str
    company: bool                   # acting in a server company (owners are then checked)


class CycleStep(Out):
    step: str
    label: str
    owner: str
    status: str                     # open | signed
    signed_by: str = ""
    signed_at: str | None = None
    note: str = ""
    version_id: str | None = None   # the company frozen at the sign-off
    figures: Figures | None = None


class CycleLog(Out):
    at: str
    actor: str
    action: str
    detail: str


class Cycle(Out):
    id: str
    month: str
    status: str                     # open | closed
    created_at: str
    created_by: str
    next: str | None                # the step to sign next (none: closed)
    steps: list[CycleStep]
    log: list[CycleLog]


class CycleSummary(Out):
    id: str
    month: str
    status: str
    next: str | None
    signed: int


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _who(a: Actor) -> str:
    return a.email or "this browser"


class Cycles:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.db = store.db
        with store.lock:
            self.db.executescript(SCHEMA)

    # ---- reading ---------------------------------------------------------------------------------------
    def _row(self, cid: str, scope: str) -> sqlite3.Row:
        r = self.db.execute("SELECT * FROM sop_cycles WHERE id = ? AND scope = ?", (cid, scope)).fetchone()
        if r is None:
            raise VersionError(f"no S&OP cycle '{cid}'", 404)
        return r

    def _steps(self, cid: str) -> dict[str, sqlite3.Row]:
        return {r["step"]: r for r in self.db.execute("SELECT * FROM sop_steps WHERE cycle_id = ?", (cid,))}

    @staticmethod
    def _next(steps: dict[str, sqlite3.Row]) -> str | None:
        return next((s for s in STEPS if steps[s]["status"] != "signed"), None)

    def _cycle(self, r: sqlite3.Row) -> Cycle:
        steps = self._steps(r["id"])
        log = [CycleLog(at=x["at"], actor=x["actor"], action=x["action"], detail=x["detail"]) for x in
               self.db.execute("SELECT * FROM sop_cycle_log WHERE cycle_id = ? ORDER BY seq", (r["id"],))]
        return Cycle(id=r["id"], month=r["month"], status=r["status"], created_at=r["created_at"],
                     created_by=r["created_by"], next=self._next(steps), log=log, steps=[CycleStep(
                         step=s, label=LABELS[s], owner=steps[s]["owner"], status=steps[s]["status"],
                         signed_by=steps[s]["signed_by"], signed_at=steps[s]["signed_at"], note=steps[s]["note"],
                         version_id=steps[s]["version_id"],
                         figures=Figures.model_validate_json(steps[s]["figures"]) if steps[s]["figures"] else None)
                         for s in STEPS])

    def list(self, scope: str) -> list[CycleSummary]:
        with self.store.lock:
            out = []
            for r in self.db.execute("SELECT * FROM sop_cycles WHERE scope = ? ORDER BY month DESC", (scope,)):
                steps = self._steps(r["id"])
                out.append(CycleSummary(id=r["id"], month=r["month"], status=r["status"], next=self._next(steps),
                                        signed=sum(s["status"] == "signed" for s in steps.values())))
            return out

    def get(self, cid: str, scope: str) -> Cycle:
        with self.store.lock:
            return self._cycle(self._row(cid, scope))

    # ---- changing --------------------------------------------------------------------------------------
    def _log(self, cid: str, actor: Actor, action: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO sop_cycle_log (cycle_id, at, actor, action, detail) VALUES (?, ?, ?, ?, ?)",
                        (cid, _now(), _who(actor), action, detail))

    def _write(self, fn):
        """Run ``fn`` in one transaction under the store's lock."""
        with self.store.lock:
            self.db.execute("BEGIN")
            try:
                out = fn()
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return out

    def create(self, month: str, scope: str, actor: Actor) -> Cycle:
        """A new cycle for ``month`` (YYYY-MM); the owners carry over from the latest earlier cycle."""
        if not MONTH.match(month):
            raise VersionError("a cycle is for a month, written YYYY-MM", 422)
        cid = hashlib.sha256(f"{scope}|{month}".encode()).hexdigest()[:16]

        def go() -> Cycle:
            if self.db.execute("SELECT 1 FROM sop_cycles WHERE scope = ? AND month = ?", (scope, month)).fetchone():
                raise VersionError(f"there is already a cycle for {month}")
            prev = self.db.execute("SELECT id FROM sop_cycles WHERE scope = ? AND month < ? ORDER BY month DESC "
                                   "LIMIT 1", (scope, month)).fetchone()
            owners = {s: r["owner"] for s, r in self._steps(prev["id"]).items()} if prev else {}
            self.db.execute("INSERT INTO sop_cycles (id, scope, month, status, created_at, created_by) VALUES "
                            "(?, ?, ?, 'open', ?, ?)", (cid, scope, month, _now(), actor.email))
            for s in STEPS:
                self.db.execute("INSERT INTO sop_steps (cycle_id, step, owner, status) VALUES (?, ?, ?, 'open')",
                                (cid, s, owners.get(s, "")))
            self._log(cid, actor, "created", f"owners from {prev['id']}" if prev and any(owners.values()) else "")
            return self._cycle(self._row(cid, scope))
        return self._write(go)

    def delete(self, cid: str, scope: str, actor: Actor) -> None:
        def go() -> None:
            self._row(cid, scope)
            if any(r["status"] == "signed" or r["version_id"] for r in self._steps(cid).values()):
                raise VersionError("a cycle with a sign-off on record stays: reopen its steps instead")
            for t in ("sop_cycle_log", "sop_steps"):
                self.db.execute(f"DELETE FROM {t} WHERE cycle_id = ?", (cid,))  # noqa: S608 (fixed names)
            self.db.execute("DELETE FROM sop_cycles WHERE id = ?", (cid,))
        self._write(go)

    def set_owner(self, cid: str, step: str, owner: str, scope: str, actor: Actor) -> Cycle:
        if step not in STEPS:
            raise VersionError(f"no step '{step}'", 404)
        if actor.company and actor.role != "owner":
            raise VersionError("only an owner of the company says who owns a step", 403)

        def go() -> Cycle:
            r = self._row(cid, scope)
            self.db.execute("UPDATE sop_steps SET owner = ? WHERE cycle_id = ? AND step = ?", (owner, cid, step))
            self._log(cid, actor, "owner", f"{LABELS[step]}: {owner or 'nobody'}")
            return self._cycle(r)
        return self._write(go)

    @staticmethod
    def _may(actor: Actor, step: str, owner: str) -> None:
        """A step is signed or reopened by its owner or a company owner; with no owner, by anyone who may change
        the company, except the executive step, which then takes a company owner."""
        if not actor.company or actor.role == "owner":
            return
        if owner:
            if actor.email.lower() != owner.lower():
                raise VersionError(f"{LABELS[step]} is {owner}'s to sign; an owner of the company may too", 403)
        elif step == "exec":
            raise VersionError("the executive step has no owner: an owner of the company signs it", 403)

    def sign(self, cid: str, step: str, ds: Dataset, note: str, scope: str, actor: Actor) -> Cycle:
        """Sign ``step`` off for ``ds``: its figures are recorded and the company frozen as a base version."""
        if step not in STEPS:
            raise VersionError(f"no step '{step}'", 404)
        note = note.strip()
        with self.store.lock:
            r = self._row(cid, scope)
            steps = self._steps(cid)
            nxt = self._next(steps)
            if steps[step]["status"] == "signed":
                raise VersionError(f"{LABELS[step]} is signed already: reopen it to sign it again")
            if nxt != step:
                raise VersionError(f"{LABELS[nxt]} comes first" if nxt else "the cycle is closed")
            self._may(actor, step, steps[step]["owner"])
        if step in MINUTES and not note:
            raise VersionError(f"say what was decided: {LABELS[step]} is signed with its minutes", 422)
        fig = figures(ds, step)                      # outside the lock: the supply steps solve the plan
        if step == "data" and fig.blocking:
            raise VersionError(f"the data has {fig.blocking} blocking problem{'s' * (fig.blocking > 1)}: fix them "
                               "before the data is signed")
        if step in SUPPLY and fig.fill_rate is None:
            raise VersionError(" ".join(fig.notes) or "the capacity plan did not solve")
        meta = self.store.save_base(ds, f"S&OP {r['month']} · {LABELS[step]}",
                                    f"signed by {_who(actor)}" + (f": {note}" if note else ""), scope)

        def go() -> Cycle:
            again = self._steps(cid)
            if again[step]["status"] == "signed" or self._next(again) != step:
                raise VersionError(f"{LABELS[step]} was signed meanwhile")
            self.db.execute("UPDATE sop_steps SET status = 'signed', signed_by = ?, signed_at = ?, note = ?, "
                            "version_id = ?, figures = ? WHERE cycle_id = ? AND step = ?",
                            (_who(actor), _now(), note, meta.id, fig.model_dump_json(), cid, step))
            self._log(cid, actor, "signed", f"{LABELS[step]} → {meta.id}")
            if step == STEPS[-1]:
                self.db.execute("UPDATE sop_cycles SET status = 'closed' WHERE id = ?", (cid,))
                self._log(cid, actor, "closed")
            return self._cycle(self._row(cid, scope))
        return self._write(go)

    def reopen(self, cid: str, step: str, note: str, scope: str, actor: Actor) -> Cycle:
        """Reopen ``step`` and every later signed step; their frozen versions stay on record."""
        if step not in STEPS:
            raise VersionError(f"no step '{step}'", 404)
        note = note.strip()
        if not note:
            raise VersionError("say why it is reopened", 422)

        def go() -> Cycle:
            self._row(cid, scope)
            steps = self._steps(cid)
            if steps[step]["status"] != "signed":
                raise VersionError(f"{LABELS[step]} is not signed")
            self._may(actor, step, steps[step]["owner"])
            later = [s for s in STEPS[STEPS.index(step):] if steps[s]["status"] == "signed"]
            for s in later:
                self.db.execute("UPDATE sop_steps SET status = 'open' WHERE cycle_id = ? AND step = ?", (cid, s))
            self.db.execute("UPDATE sop_cycles SET status = 'open' WHERE id = ?", (cid,))
            self._log(cid, actor, "reopened", f"{', '.join(LABELS[s] for s in later)}: {note}")
            return self._cycle(self._row(cid, scope))
        return self._write(go)


_cycles: Cycles | None = None
_cycles_lock = threading.Lock()


def get_cycles() -> Cycles:
    """The process-wide cycles, made once per store (their tables are made when they are)."""
    global _cycles
    store = get_store()
    with _cycles_lock:
        if _cycles is None or _cycles.store is not store:
            _cycles = Cycles(store)
        return _cycles
