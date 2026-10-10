"""One-click fixes from the exception inbox (roadmap F follow-up): try the inbox's suggested action on a copy of the
company, plan it again and show the money at risk before and after, instead of the estimate the inbox prints.

Three actions can be done in one click, each as a few field edits the planner can keep (one undo step) or leave:

* **expedite**: firm receipts of the product that come after the date it is needed are pulled in to that date (the
  receipt the item names when it names one: a confirmation later than requested is brought back to the requested
  date, a receipt needed earlier to the date it is needed). Receipts at another place come in ahead of the need by
  the quickest route's transit time. A planned order is not a receipt: when nothing firm comes late, there is nothing
  to pull in and the plan already orders as early as the lead time allows.
* **switch_supplier**: the quicker supplier the inbox names becomes the fixed source for the product at that place.
* **overtime**: the machine's overtime a day is raised to cover the worst overload of capacity + overtime, within
  what is left of its day.

Anything else (chase a payment, sell first, review) needs a person: it has no one-click version.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from ..model import Dataset
from ..model.common import Out
from ..model.master import _day_hours
from ..plan import PlanResult, run_mrp
from ..plan.leadtime import resource_calendar
from ..time.capacity import hours_between, overtime_between
from .money import LATE_DEMAND, inbox_order, price_items
from .result import WorkItem


class FixError(ValueError):
    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


class FixEdit(Out):
    """One field of one record, as the fix changes it."""
    collection: str                   # the dataset list: receipts, purchasing_sources, resources
    id: str
    field: str
    before: Any = None
    value: Any = None
    note: str = ""                    # in plain words


class FixResult(Out):
    key: str
    action: str                       # the inbox action's kind
    label: str                        # what was tried, in words
    edits: list[FixEdit] = []
    before_total: float = 0.0         # money at risk in the inbox, now
    after_total: float = 0.0          # and planned again with the edits
    before_item: float = 0.0          # this item, now
    after_item: float | None = None   # and after (None: it is gone)
    costs: float | None = None        # what the action costs when the data says (overtime hours, a dearer supplier)
    cleared: list[str] = []           # other exceptions it clears, with their money
    opened: list[str] = []            # exceptions it brings
    plan_ok: bool = True
    note: str = ""


# ------------------------------------------------------------------------------------------------ edits
def _transit(ds: Dataset, origin: str, dest: str) -> float:
    days = [m.transit_days for ln in ds.lanes if ln.origin == origin and ln.destination == dest for m in ln.modes]
    return min(days) if days else 0.0


def _pull_in(rc, when: dt.date, why: str) -> list[FixEdit]:
    out = [FixEdit(collection="receipts", id=rc.id, field="due_date", before=rc.due_date.isoformat(),
                   value=when.isoformat(), note=f"{rc.id}: due {when.isoformat()} instead of {rc.expected_date.isoformat()} ({why})")]
    if rc.confirmed_date is not None:
        out.append(FixEdit(collection="receipts", id=rc.id, field="confirmed_date",
                           before=rc.confirmed_date.isoformat(), value=when.isoformat(),
                           note=f"{rc.id}: the supplier confirms {when.isoformat()}"))
    if rc.confirmations:
        out.append(FixEdit(collection="receipts", id=rc.id, field="confirmations",
                           before=[c.model_dump(mode="json") for c in rc.confirmations], value=[],
                           note=f"{rc.id}: one delivery instead of {len(rc.confirmations)}"))
    return out


def _expedite(ds: Dataset, w: WorkItem) -> list[FixEdit]:
    start = ds.settings.planning_start
    named = next((r for r in ds.receipts if r.id == w.order_id), None) if w.order_id else None
    if named is not None:
        if w.code == "PO_CONFIRMED_LATE" and named.confirmed_date and named.confirmed_date > named.due_date:
            return _pull_in(named, max(start, named.due_date), "the date asked for")
        if w.code == "RESCHEDULE_IN" and w.date and w.date < named.expected_date:
            return _pull_in(named, max(start, w.date), "the date it is needed")
        if named.expected_date < start:
            raise FixError(f"{named.id} is already overdue: the plan counts it as arriving today; chase it instead")
        raise FixError(f"{named.id} is not late against a date the plan needs it: nothing to pull in")
    if not (w.product and w.date and w.qty):
        raise FixError("this exception names no product, date and quantity to expedite for")
    need, left = w.date, abs(w.qty)
    cands = []
    for rc in ds.receipts:
        if rc.product != w.product or rc.expected_qty <= 0:
            continue
        here = rc.location == w.location
        lead = 0.0 if here else _transit(ds, rc.location, w.location or "")
        target = max(start, need - dt.timedelta(days=math.ceil(lead)))
        if rc.expected_date > target:
            cands.append((not here, rc.expected_date, rc.id, rc, target, lead))
    if not cands:
        raise FixError(f"nothing firm of {w.product} arrives after {need.isoformat()}: the late quantity is on planned "
                       "orders, which the plan already starts as early as their lead time allows. Switch supplier, "
                       "shorten the lead time or take stock from elsewhere")
    out: list[FixEdit] = []
    for _, _, _, rc, target, lead in sorted(cands, key=lambda c: c[:3]):
        arrives = target + dt.timedelta(days=math.ceil(lead))
        why = f"needed {need.isoformat()}" + (f"; the earliest it can reach {w.location} is {arrives.isoformat()}"
                                               if arrives > need else "")
        out += _pull_in(rc, target, why)
        left -= rc.expected_qty
        if left <= 1e-9:
            break
    return out


def _switch(ds: Dataset, w: WorkItem) -> list[FixEdit]:
    loc, prod = w.location, w.product
    sources = [s for s in ds.purchasing_sources if s.product == prod and not ds.source_blocked(s)
               and (loc is None or s.location == loc)]
    if not sources:
        sources = [s for s in ds.purchasing_sources if s.product == prod and not ds.source_blocked(s)]
    if len(sources) < 2:
        raise FixError(f"{prod} has no second supplier to switch to")
    cur = min(sources, key=lambda s: (s.price, s.lead_time_days))
    alt = min((s for s in sources if s is not cur), key=lambda s: (s.lead_time_days, s.price))
    if alt.lead_time_days >= cur.lead_time_days:
        raise FixError(f"no supplier of {prod} is quicker than {cur.supplier}")
    out = [FixEdit(collection="purchasing_sources", id=alt.id, field="fixed", before=alt.fixed, value=True,
                   note=f"{alt.supplier} becomes the fixed source of {prod} at {alt.location} "
                        f"({alt.lead_time_days:g} d instead of {cur.lead_time_days:g} d)")]
    for s in ds.purchasing_sources:
        if s is not alt and s.fixed and s.product == alt.product and s.location == alt.location:
            out.append(FixEdit(collection="purchasing_sources", id=s.id, field="fixed", before=True, value=False,
                               note=f"{s.supplier} is no longer the fixed source"))
    return out


def _overtime(ds: Dataset, plan: PlanResult | None, w: WorkItem) -> list[FixEdit]:
    if w.code not in ("CAPACITY_OVERLOAD", "CAPACITY_DAY_OVERLOAD"):
        raise FixError("the plan already counts on this overtime: it needs no change, only someone to approve the hours")
    r = ds.resource_by_id.get(w.resource or "")
    rp = next((x for x in plan.resources if x.resource == w.resource), None) if plan is not None else None
    if r is None or rp is None:
        raise FixError("the machine is not in the plan")
    cal = resource_calendar(ds, r.id)
    one = r.model_copy(update={"overtime_hours_per_day": 1.0})
    # the windows over capacity and overtime: the plan's buckets, or (a day overload) single working days
    if w.code == "CAPACITY_OVERLOAD":
        spans = [(bk.start, bk.end, b.load_hours) for b in rp.buckets
                 for bk in plan.buckets if bk.index == b.bucket]
    else:
        spans = [(d, d + dt.timedelta(days=1), h) for d, h in rp.daily_load.items()]
    need = 0.0
    for a, b, load in spans:
        excess = load - hours_between(r, cal, a, b) - overtime_between(r, cal, a, b)
        per = overtime_between(one, cal, a, b)            # what one hour a day of overtime gives in the window
        if excess > 1e-6 and per > 0:
            need = max(need, excess / per)
    if need <= 0:
        raise FixError(f"{r.id}: nothing is over capacity and overtime any more")
    day = _day_hours(r.shifts) if r.shifts else r.shifts_per_day * r.hours_per_shift
    new = min(24.0 - day, math.ceil((r.overtime_hours_per_day + need) * 2) / 2)
    if new <= r.overtime_hours_per_day + 1e-9:
        raise FixError(f"{r.id} has no hours left in its day for more overtime: move load or add a machine")
    note = f"{r.name or r.id}: {new:g} h overtime a day instead of {r.overtime_hours_per_day:g} h"
    if new < r.overtime_hours_per_day + need - 1e-9:
        note += " (all that is left of its day; it does not cover all of the overload)"
    return [FixEdit(collection="resources", id=r.id, field="overtime_hours_per_day", before=r.overtime_hours_per_day,
                    value=new, note=note)]


def fix_edits(ds: Dataset, plan: PlanResult | None, w: WorkItem) -> list[FixEdit]:
    """The edits that carry out ``w``'s suggested action; FixError when it has no one-click version."""
    a = w.action
    if a is None:
        raise FixError("this exception has no suggested action")
    if a.kind == "expedite":
        return _expedite(ds, w)
    if a.kind == "switch_supplier":
        return _switch(ds, w)
    if a.kind == "overtime":
        return _overtime(ds, plan, w)
    raise FixError(f"'{a.label}' needs a person: it has no one-click version")


def apply_edits(ds: Dataset, edits: list[FixEdit]) -> Dataset:
    d = ds.model_dump(mode="json")
    for e in edits:
        rows = d.get(e.collection)
        row = next((x for x in rows or [] if x.get("id") == e.id), None)
        if row is None:
            raise FixError(f"there is no {e.collection} record '{e.id}'", 409)
        row[e.field] = e.value
    try:
        return Dataset.model_validate(d)
    except ValueError as err:
        raise FixError(f"the change makes the data invalid: {str(err).splitlines()[-2:]}") from None


# ------------------------------------------------------------------------------------------------ try it
def _inbox(ds: Dataset, plan: PlanResult, peek) -> list[WorkItem]:
    items = peek(ds, plan)
    price_items(ds, plan if plan.ok else None, items)
    by = {w.id: w for w in items}
    return [by[i] for i in inbox_order(items)]


def try_fix(ds: Dataset, key: str, peek) -> FixResult:
    """Carry out the suggested action of the inbox item ``key`` on a copy of ``ds`` and plan again. ``peek(ds, plan)``
    gives the worklist items of a dataset as the inbox lists them (recording nothing)."""
    plan = run_mrp(ds)
    before = _inbox(ds, plan, peek)
    w = next((x for x in before if x.key == key), None)
    if w is None:
        raise FixError("this exception is no longer open: refresh the list", 404)
    edits = fix_edits(ds, plan if plan.ok else None, w)
    ds2 = apply_edits(ds, edits)
    plan2 = run_mrp(ds2)
    after = _inbox(ds2, plan2, peek)
    cur = ds.settings.currency
    a_by = {x.key: x for x in after}
    b_by = {x.key: x for x in before}
    out = FixResult(key=key, action=w.action.kind if w.action else "", label=w.action.label if w.action else "",
                    edits=edits, before_total=round(sum(x.money_at_risk for x in before), 2),
                    after_total=round(sum(x.money_at_risk for x in after), 2), before_item=w.money_at_risk,
                    after_item=a_by[key].money_at_risk if key in a_by else None, plan_ok=plan2.ok,
                    costs=w.action.costs if w.action else None)
    out.cleared = [f"{x.message} ({x.money_at_risk:,.0f} {cur})" for x in before if x.key not in a_by and x.key != key]
    out.opened = [f"{x.message} ({x.money_at_risk:,.0f} {cur})" for x in after if x.key not in b_by]
    if not plan2.ok:
        out.note = "the plan is blocked with this change: " + "; ".join(i.message for i in plan2.issues[:2])
    elif key in a_by and a_by[key].money_at_risk >= w.money_at_risk - 0.005:
        out.note = ("the receipts pulled in do not reach the demand in time: it stays late" if w.code in LATE_DEMAND
                    else "the change does not lower what this exception puts at risk")
    return out
