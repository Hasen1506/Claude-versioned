"""Control tower (blueprint P10): the KPI set of the S/4 guide §18.2 graded against targets, an exception
worklist with owners, SLA and ageing kept across runs, and a separate data-quality view."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..actuals.stock import accuracy_report
from ..finance.ledger import cost_to_serve
from ..model import Dataset
from ..plan import PlanResult, run_mrp
from ..promise import run_promise
from ..validate import RULES, validate
from ..versions.store import Store, canonical, get_store, sha
from .kpis import Kpis
from .money import inbox_order, price_items
from .result import DataQualityRow, Kpi, KpiRow, TowerResult, WorkItem
from .fix import FixError, FixResult, fix_edits, try_fix
from .worklist import Raw, Tracker, collect, get_tracker

ONE_CLICK = {"expedite", "switch_supplier", "overtime"}
SEV = {"error": 0, "warning": 1, "info": 2}


def plan_stability(cur: PlanResult, prev: PlanResult, prev_end: dt.date, start: dt.date) -> tuple[float | None, int, int, list[KpiRow]]:
    """Share of the current plan's orders (due inside both horizons) that the previous plan already had with the
    same source, due date and quantity (±1 %)."""
    pool: dict[tuple, list[float]] = defaultdict(list)
    for o in prev.orders:
        pool[(o.kind, o.location, o.product, o.source_id, o.due_date)].append(o.qty)
    by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for o in cur.orders:
        if not (start <= o.due_date < prev_end):
            continue
        by[o.kind][1] += 1
        cands = pool.get((o.kind, o.location, o.product, o.source_id, o.due_date), [])
        hit = next((i for i, q in enumerate(cands) if abs(q - o.qty) <= 0.01 * max(abs(q), abs(o.qty), 1e-9)), None)
        if hit is not None:
            cands.pop(hit)
            by[o.kind][0] += 1
    n = int(sum(v[1] for v in by.values()))
    m = int(sum(v[0] for v in by.values()))
    rows = [KpiRow(label=k, value=v[0] / v[1] if v[1] else None, numerator=v[0], denominator=v[1])
            for k, v in sorted(by.items())]
    return (m / n if n else None), n, m, rows


def detect(ds: Dataset, plan: PlanResult) -> list[Raw]:
    """This run's exceptions: from the plan, promising, open orders, money owed and forecast bias."""
    promise = run_promise(ds) if plan.ok else None
    window = ds.settings.planning_start - dt.timedelta(days=ds.tower.kpi_window_days)
    acc = accuracy_report([r for r in ds.accuracy if r.end > window and r.start < ds.settings.planning_start])
    return collect(ds, plan if plan.ok else None, promise, acc)


def try_inbox_fix(ds: Dataset, key: str, *, tracker: Tracker | None = None, store: Store | None = None,
                  scope: str | None = None) -> FixResult:
    """Try the inbox item ``key``'s action on a copy of ``ds`` (tower/fix.py), recording nothing."""
    tracker = tracker or (Tracker(store) if store is not None else get_tracker())
    return try_fix(ds, key, lambda d, p: tracker.peek(d, detect(d, p), scope)[0])


def _previous_base(ds: Dataset, store: Store | None = None, scope: str | None = None) -> tuple[Dataset | None, str]:
    """The latest earlier base version of this company: of the server company ``scope`` when one is open, else the
    browser's own versions with the same company name."""
    store = store or get_store()
    own = sha(canonical(ds))
    start = ds.settings.planning_start.isoformat()
    cands = [m for m in store.list(scope or "") if m.kind == "base"
             and (scope or m.company == ds.settings.company_name) and m.planning_start <= start and m.sha256 != own]
    if not cands:
        return None, ""
    prev = max(cands, key=lambda m: (m.planning_start, m.created_at, m.id))
    return store.dataset(prev.id), f"{prev.id} ({prev.name}, start {prev.planning_start})"


def run_tower(ds: Dataset, *, tracker: Tracker | None = None, plan: PlanResult | None = None,
              store: Store | None = None, scope: str | None = None, record: bool = True) -> TowerResult:
    """``scope``: the server company the worklist and the previous plan belong to (none: the browser's own).
    ``record``: write this run into the worklist (open, refresh, clear); False shows it without changing it."""
    tracker = tracker or (Tracker(store) if store is not None else get_tracker())
    issues = validate(ds)
    out = TowerResult(ok=True, company=ds.settings.company_name, as_of=ds.settings.planning_start, issues=issues)
    by_code: dict[str, list[str]] = defaultdict(list)
    for i in issues:
        by_code[i.code].append(f"{i.object_type} {i.object_id}")
    out.data_quality = sorted(
        (DataQualityRow(code=c, severity=RULES[c][0] if c in RULES else "warning", title=RULES[c][1] if c in RULES else c,
                        count=len(v), examples=v[:5]) for c, v in by_code.items()),
        key=lambda r: (SEV.get(r.severity, 3), -r.count, r.code))

    plan = plan or run_mrp(ds)
    raws = detect(ds, plan)
    live, cleared = tracker.sync(ds, raws, scope) if record else tracker.peek(ds, raws, scope)
    order = {"open": 0, "acknowledged": 1, "resolved": 2}
    out.worklist = sorted(live, key=lambda w: (order.get(w.status, 3), not w.breached, SEV[w.severity], -w.age_days,
                                               w.category, w.key))
    out.cleared = cleared
    price_items(ds, plan if plan.ok else None, out.worklist)          # roadmap F: money at risk and one action each
    for w in out.worklist:                                            # which actions can be tried in one click
        if w.action is not None and w.action.kind in ONE_CLICK:
            try:
                fix_edits(ds, plan if plan.ok else None, w)
                w.action.one_click = True
            except FixError as e:
                w.action.why_not = str(e)
    out.inbox = inbox_order(out.worklist)
    by_id = {w.id: w for w in out.worklist}
    out.money_at_risk = round(sum(by_id[i].money_at_risk for i in out.inbox), 2)

    k = Kpis(ds)
    k.forecast()
    k.confirmation()
    k.otif()
    k.supplier()
    k.adherence()
    if plan.ok:
        k.inventory(plan)
        k.working_capital(plan)
        prev, label = _previous_base(ds, store, scope)
        if prev is not None:
            pplan = run_mrp(prev)
            end = prev.settings.planning_start + dt.timedelta(days=prev.settings.horizon_days)
            v, n, m, rows = plan_stability(plan, pplan, end, ds.settings.planning_start) if pplan.ok else (None, 0, 0, [])
            k.stability(v, n, m, label, rows)
        else:
            k.stability(None, 0, 0, "", [])
        serve, _ = cost_to_serve(ds, plan)
        k.cost_to_serve(serve)
    else:
        out.ok = False
        out.notes.append("The supply plan is blocked by readiness errors: plan-based KPIs and exceptions are missing.")
    k.ageing(live)
    order_ids = ["forecast_accuracy", "forecast_bias", "confirmation_rate", "otif_confirmed", "otif_requested",
                 "perfect_order", "supplier_reliability", "schedule_adherence", "days_of_supply", "excess_obsolete",
                 "inventory_turns", "dio", "dso", "dpo", "cash_to_cash",
                 "plan_stability", "exception_ageing", "cost_to_serve"]
    out.kpis = sorted(k.out, key=lambda x: order_ids.index(x.id) if x.id in order_ids else 99)
    return out


__all__ = ["FixError", "FixResult", "Kpi", "TowerResult", "WorkItem", "get_tracker", "plan_stability", "run_tower",
           "try_inbox_fix"]
