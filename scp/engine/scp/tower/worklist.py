"""The exception worklist: what a planner has to act on, who owns it, and how long it has been open.

Exceptions come from the supply plan, order promising, open orders past due and forecast bias. Master-data
defects are kept out of it (the S/4 guide: feed them to a data-quality view, never to planner worklists).
Each exception has a stable key, so its life — first seen, owner, acknowledged, resolved, cleared, reopened —
is tracked across runs in the version store's database. The clock is the planning start, so ageing follows the
roll-forward rather than the wall clock and is reproducible.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from dataclasses import dataclass

from ..model import Dataset
from ..plan.result import PlanResult
from ..promise.result import PromiseResult
from ..actuals.result import AccuracyReport
from ..versions import VersionError
from ..versions.store import Store, get_store
from .result import WorkItem

CATEGORY = {
    "STOCKOUT": "coverage", "BELOW_SAFETY_STOCK": "coverage", "DEMAND_AT_RISK": "coverage",
    "CAPACITY_OVERLOAD": "capacity", "CAPACITY_OVERTIME": "capacity", "SUPPLIER_CAPACITY": "capacity",
    "LANE_CAPACITY": "capacity", "EXCESS_STOCK": "inventory", "SHELF_LIFE_RISK": "inventory",
    "START_IN_PAST": "orders", "FENCE_SHIFT": "orders", "NO_VALID_SOURCE": "orders",
    "RECEIPT_OVERDUE": "orders", "ORDER_OVERDUE": "delivery", "PROMISE_AT_RISK": "delivery",
    "PROMISE_LATE": "delivery", "FORECAST_BIAS": "demand", "NO_DEMAND_STOCK": "inventory",
}
SKIP = {"EOQ_FALLBACK"}  # a parameter note for the data owner, not planner work

SCHEMA = """
CREATE TABLE IF NOT EXISTS tower_items (
  id TEXT PRIMARY KEY, company TEXT NOT NULL, key TEXT NOT NULL, code TEXT NOT NULL, category TEXT NOT NULL,
  severity TEXT NOT NULL, message TEXT NOT NULL, location TEXT, product TEXT, resource TEXT, order_id TEXT,
  date TEXT, qty REAL, owner TEXT NOT NULL, owner_source TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'resolved', 'cleared')),
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, resolved_on TEXT, reopened INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '', UNIQUE (company, key)
);
CREATE TABLE IF NOT EXISTS tower_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL REFERENCES tower_items(id), at TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
);
"""


@dataclass
class Raw:
    code: str
    severity: str
    message: str
    location: str | None = None
    product: str | None = None
    resource: str | None = None
    order_id: str | None = None
    date: dt.date | None = None
    qty: float | None = None

    @property
    def category(self) -> str:
        return CATEGORY.get(self.code, "orders")

    @property
    def key(self) -> str:
        return "|".join((self.code, self.location or "", self.product or "", self.resource or "", self.order_id or ""))


# ------------------------------------------------------------------------------------------------ collect
def collect(ds: Dataset, plan: PlanResult | None, promise: PromiseResult | None,
            accuracy: AccuracyReport | None) -> list[Raw]:
    out: dict[str, Raw] = {}

    def add(r: Raw) -> None:
        out.setdefault(r.key, r)

    start = ds.settings.planning_start
    if plan is not None and plan.ok:
        for e in plan.exceptions:
            if e.code in SKIP or e.severity == "info":
                continue
            add(Raw(e.code, e.severity, e.message, e.location, e.product, e.resource, e.order_id, e.date, e.qty))
        req = {(n.location, n.product): sum(b.gross_independent + b.gross_dependent for b in n.buckets)
               for n in plan.nodes}
        for n in plan.nodes:
            if n.on_hand > 0 and req.get((n.location, n.product), 0.0) <= 0 and n.unit_value > 0:
                add(Raw("NO_DEMAND_STOCK", "warning",
                        f"{n.on_hand:,.0f} on hand ({n.on_hand * n.unit_value:,.0f} {ds.settings.currency}) with no "
                        "requirement in the horizon", n.location, n.product, qty=n.on_hand))
    if promise is not None and promise.ok:
        for o in promise.orders:
            if o.at_risk:
                add(Raw("PROMISE_AT_RISK", "error", f"Promise for {o.order} is no longer covered by supply",
                        o.location, o.product, order_id=o.order, date=o.requested, qty=o.qty))
            elif o.status in ("late", "partial", "unconfirmed") and o.qty > 0:
                add(Raw("PROMISE_LATE", "warning",
                        f"{o.order}: {o.on_time:,.0f} of {o.qty:,.0f} can be confirmed on the requested date",
                        o.location, o.product, order_id=o.order, date=o.requested, qty=o.qty - o.on_time))
    for rc in ds.receipts:
        if rc.due_date < start:
            add(Raw("RECEIPT_OVERDUE", "warning",
                    f"{rc.kind.value} {rc.id} due {rc.due_date.isoformat()} still has {rc.qty:,.0f} open",
                    rc.location, rc.product, order_id=rc.id, date=rc.due_date, qty=rc.qty))
    for d in ds.demand:
        if d.kind.value == "sales_order" and d.date < start and d.qty > 0:
            add(Raw("ORDER_OVERDUE", "error", f"Sales order {d.id or '?'} requested {d.date.isoformat()} still has "
                                              f"{d.qty:,.0f} to deliver", d.location, d.product, order_id=d.id,
                    date=d.date, qty=d.qty))
    if accuracy is not None:
        for s in accuracy.series:
            if s.bias is not None and len(s.weeks) >= 4 and abs(s.bias) > ds.tower.bias_alert:
                add(Raw("FORECAST_BIAS", "warning",
                        f"{'Over' if s.bias > 0 else 'Under'}-forecast by {abs(s.bias):.0%} over {len(s.weeks)} weeks",
                        s.location, s.product, qty=s.forecast - s.actual))
    return list(out.values())


def owner_for(ds: Dataset, r: Raw) -> tuple[str, str]:
    family = ds.product_by_id[r.product].family if r.product and r.product in ds.product_by_id else None
    for rule in ds.tower.owners:
        if rule.categories and r.category not in rule.categories:
            continue
        if rule.locations and r.location not in rule.locations:
            continue
        if rule.products and r.product not in rule.products:
            continue
        if rule.families and family not in rule.families:
            continue
        return rule.owner, "rule"
    return ds.tower.default_owner, "default"


# ------------------------------------------------------------------------------------------------ tracker
def item_id(company: str, key: str) -> str:
    return hashlib.sha1(f"{company}\x1f{key}".encode()).hexdigest()[:12]


class Tracker:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.db = store.db
        self.db.executescript(SCHEMA)

    def _log(self, iid: str, at: str, action: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO tower_log (item_id, at, action, detail) VALUES (?, ?, ?, ?)", (iid, at, action, detail))

    def _item(self, r: sqlite3.Row, as_of: dt.date, sla: dict[str, int]) -> WorkItem:
        first = dt.date.fromisoformat(r["first_seen"])
        resolved = dt.date.fromisoformat(r["resolved_on"]) if r["resolved_on"] else None
        until = resolved if r["status"] in ("resolved", "cleared") and resolved else as_of
        age = max(0, (until - first).days)
        s = sla.get(r["category"])
        return WorkItem(id=r["id"], key=r["key"], code=r["code"], category=r["category"], severity=r["severity"],
                        message=r["message"], location=r["location"], product=r["product"], resource=r["resource"],
                        order_id=r["order_id"], date=dt.date.fromisoformat(r["date"]) if r["date"] else None,
                        qty=r["qty"], owner=r["owner"], owner_source=r["owner_source"], status=r["status"],
                        first_seen=first, last_seen=dt.date.fromisoformat(r["last_seen"]), resolved_on=resolved,
                        age_days=age, sla_days=s, breached=s is not None and age > s, reopened=r["reopened"],
                        note=r["note"])

    def sync(self, ds: Dataset, raws: list[Raw]) -> tuple[list[WorkItem], list[WorkItem]]:
        """Record this run's exceptions: new ones open, known ones refresh (or reopen), missing ones clear."""
        company = ds.settings.company_name
        as_of = ds.settings.planning_start
        day = as_of.isoformat()
        sla = ds.tower.sla_days
        with self.store.lock:
            self.db.execute("BEGIN")
            try:
                rows = {r["id"]: r for r in self.db.execute("SELECT * FROM tower_items WHERE company = ?", (company,))}
                seen: set[str] = set()
                for x in raws:
                    iid = item_id(company, x.key)
                    seen.add(iid)
                    owner, src = owner_for(ds, x)
                    vals = (x.code, x.category, x.severity, x.message, x.location, x.product, x.resource, x.order_id,
                            x.date.isoformat() if x.date else None, x.qty)
                    old = rows.get(iid)
                    if old is None:
                        self.db.execute(
                            "INSERT INTO tower_items (id, company, key, code, category, severity, message, location, "
                            "product, resource, order_id, date, qty, owner, owner_source, status, first_seen, last_seen) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                            (iid, company, x.key, *vals, owner, src, day, day))
                        self._log(iid, day, "opened", owner)
                        continue
                    status, first, reopened = old["status"], old["first_seen"], old["reopened"]
                    resolved_on = old["resolved_on"]
                    if status == "cleared" or (status == "resolved" and resolved_on and day > resolved_on):
                        status, first, reopened, resolved_on = "open", day, reopened + 1, None
                        self._log(iid, day, "reopened")
                    if old["owner_source"] == "manual":
                        owner, src = old["owner"], "manual"
                    self.db.execute(
                        "UPDATE tower_items SET code=?, category=?, severity=?, message=?, location=?, product=?, "
                        "resource=?, order_id=?, date=?, qty=?, owner=?, owner_source=?, status=?, first_seen=?, "
                        "last_seen=MAX(last_seen, ?), resolved_on=?, reopened=? WHERE id=?",
                        (*vals, owner, src, status, first, day, resolved_on, reopened, iid))
                cleared_ids = [iid for iid, r in rows.items() if iid not in seen and r["status"] != "cleared"]
                for iid in cleared_ids:
                    self.db.execute("UPDATE tower_items SET status='cleared', resolved_on=? WHERE id=?", (day, iid))
                    self._log(iid, day, "cleared", "no longer detected")
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            live = [self._item(r, as_of, sla) for r in self.db.execute(
                f"SELECT * FROM tower_items WHERE id IN ({','.join('?' * len(seen))})", tuple(seen))] if seen else []
            cleared = [self._item(r, as_of, sla) for r in self.db.execute(
                f"SELECT * FROM tower_items WHERE id IN ({','.join('?' * len(cleared_ids))})",
                tuple(cleared_ids))] if cleared_ids else []
        return live, cleared

    def update(self, iid: str, *, owner: str | None = None, status: str | None = None, note: str | None = None,
               sla: dict[str, int] | None = None) -> WorkItem:
        with self.store.lock:
            r = self.db.execute("SELECT * FROM tower_items WHERE id = ?", (iid,)).fetchone()
            if r is None:
                raise VersionError(f"no worklist item '{iid}'", 404)
            day = r["last_seen"]
            if status is not None:
                if status not in ("open", "acknowledged", "resolved"):
                    raise VersionError(f"status must be open, acknowledged or resolved, not '{status}'")
                if r["status"] == "cleared":
                    raise VersionError("a cleared exception is no longer detected; it reopens if it comes back")
                self.db.execute("UPDATE tower_items SET status=?, resolved_on=? WHERE id=?",
                                (status, day if status == "resolved" else None, iid))
                self._log(iid, day, status)
            if owner is not None:
                owner = owner.strip()
                if owner:
                    self.db.execute("UPDATE tower_items SET owner=?, owner_source='manual' WHERE id=?", (owner, iid))
                else:  # back to the rules: re-derived on the next run
                    self.db.execute("UPDATE tower_items SET owner_source='default' WHERE id=?", (iid,))
                self._log(iid, day, "assigned", owner or "(rules)")
            if note is not None:
                self.db.execute("UPDATE tower_items SET note=? WHERE id=?", (note[:500], iid))
                self._log(iid, day, "note", note[:120])
            r = self.db.execute("SELECT * FROM tower_items WHERE id = ?", (iid,)).fetchone()
            return self._item(r, dt.date.fromisoformat(r["last_seen"]), sla or {})

    def history(self, iid: str) -> list[tuple[str, str, str]]:
        return [(r["at"], r["action"], r["detail"]) for r in
                self.db.execute("SELECT at, action, detail FROM tower_log WHERE item_id = ? ORDER BY seq", (iid,))]


def get_tracker() -> Tracker:
    return Tracker(get_store())
