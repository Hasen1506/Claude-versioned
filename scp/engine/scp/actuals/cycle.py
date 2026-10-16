"""Cycle counting by ABC class (Enterprise 6.2, ≈ S/4 MICN with the cycle counting indicator).

Each place's products are put in a class by the value they used up over the look-back: issues to production, sales
and transfers out, at their value in the books. The products that make up the first ``a_share`` of that value are
A, up to ``b_share`` B, the rest C (and anything that used nothing up). A class is counted so many times a year: a
product is due when its last posted count is that long ago, or when it was never counted. A class set by hand on
the product at the place goes before the computed one ('none': never counted by the cycle).

What is due becomes physical inventory documents (scp.actuals.documents.count_doc), one per place, entered and
posted as any count: the accuracy by class is read from the posted ones.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from ..model import Dataset, MovementType
from ..model.common import STOCKING_LOCATION_TYPES, Out
from ..network import Node, build_graph
from ..purchasing.result import ActionReport
from .documents import StockError, count_doc
from .stock import before
from .valuation import value_stock

USED = {MovementType.ISSUE, MovementType.SALE, MovementType.TRANSFER_OUT}
EPS = 1e-9


class CycleRow(Out):
    location: str
    product: str
    cls: str                                 # A, B, C or none
    by_hand: bool
    used_value: float                        # value used up over the look-back
    share: float                             # of the place's value used up
    per_year: int
    last_counted: date | None
    next_due: date | None                    # None: never (class none, or 0 counts a year)
    due: bool
    overdue_days: int
    on_doc: str | None                       # an open count document holding it


class CycleClass(Out):
    cls: str
    items: int
    per_year: int
    due: int
    counted: int                             # count lines posted over the look-back
    exact: int                               # of those, found as the books said
    accuracy: float | None                   # exact / counted
    difference_value: float                  # value of what the counts found more (+) or less (−)


class CyclePlan(Out):
    as_of: date
    location: str | None
    rows: list[CycleRow]
    classes: list[CycleClass]
    due: int
    currency: str
    notes: list[str] = []


def cycle_plan(ds: Dataset, location: str | None = None, as_of: date | None = None) -> CyclePlan:
    """Every stocked product at each place (or one), with its class, its last count and when it is next due."""
    day = as_of or ds.settings.planning_start
    cc = ds.execution.cycle_counting
    if location is not None and location not in ds.location_by_id:
        raise StockError(f"there is no place {location}")
    places = {lo.id for lo in ds.locations if lo.type in STOCKING_LOCATION_TYPES and (location is None or lo.id == location)}
    books = value_stock(ds, day)
    price = {(r.location, r.product): (r.price or r.standard) for r in books.rows}
    journal = before(ds, day + timedelta(days=1))
    since = day - timedelta(days=cc.lookback_days)
    used: dict[Node, float] = defaultdict(float)
    nodes: set[Node] = set()
    for m in journal:
        if m.location not in places:
            continue
        nodes.add((m.location, m.product))
        if m.type in USED and m.date > since:
            used[(m.location, m.product)] += m.net
    for lp in ds.location_product_by_key.values():
        if lp.location in places:
            nodes.add((lp.location, lp.product))
    notes: list[str] = []
    quiet = places - {loc for loc, _ in used}
    if quiet and ds.history:
        # no issues in the journal yet at these places: what their customers bought (sales history) instead
        try:
            g = build_graph(ds)
        except Exception:
            g = None
        from_hist: set[str] = set()
        for h in ds.history if g is not None else []:
            if not since < h.date <= day:
                continue
            opts = g.options.get((h.location, h.product)) or []
            src = next((o for o in opts if o.kind == "transfer"), None)
            ship = ds.lane_by_id[src.source_id].origin if src is not None else h.location
            if ship in quiet:
                used[(ship, h.product)] += h.qty
                nodes.add((ship, h.product))
                from_hist.add(ship)
        if from_hist:
            names = ", ".join(sorted(ds.location_by_id[x].name or x for x in from_hist))
            notes.append(f"{names}: classed by what customers bought (sales history): the journal holds no issues there yet.")
    value = {n: max(0.0, used.get(n, 0.0)) * price.get(n, 0.0) for n in nodes}

    computed: dict[Node, tuple[str, float]] = {}
    for loc in places:
        mine = sorted((n for n in nodes if n[0] == loc), key=lambda n: (-value[n], n[1]))
        total = sum(value[n] for n in mine)
        cum = 0.0
        for n in mine:
            before_share = cum / total if total > 0 else 1.0
            cum += value[n]
            cls = "C" if value[n] <= 0 else "A" if before_share < cc.a_share else "B" if before_share < cc.b_share else "C"
            computed[n] = (cls, value[n] / total if total > 0 else 0.0)

    last: dict[Node, date] = {}
    open_doc: dict[Node, str] = {}
    lines: dict[Node, list[tuple[float, float]]] = defaultdict(list)   # posted (book, counted) over the look-back
    for d in ds.inventory_docs:
        for it in d.items:
            n = (it.location, it.product)
            if d.status == "posted" and d.date <= day:
                last[n] = max(last.get(n, d.date), d.date)
                if d.date > since and it.counted is not None:
                    lines[n].append((it.book_qty, it.counted))
            elif d.status == "open":
                open_doc[n] = d.id

    rows: list[CycleRow] = []
    for n in sorted(nodes):
        lp = ds.location_product_by_key.get(n)
        hand = lp.cycle_count if lp is not None else None
        cls, share = computed.get(n, ("C", 0.0))
        if hand:
            cls = hand
        per = cc.per_year(cls)
        prev = last.get(n)
        if per <= 0:
            nxt = None
        else:
            nxt = prev + timedelta(days=math.ceil(365 / per)) if prev else day
        due = nxt is not None and nxt <= day and n not in open_doc
        rows.append(CycleRow(location=n[0], product=n[1], cls=cls, by_hand=bool(hand), used_value=round(value[n], 2),
                             share=round(share, 4), per_year=per, last_counted=prev, next_due=nxt, due=due,
                             overdue_days=(day - nxt).days if due and nxt else 0, on_doc=open_doc.get(n)))
    classes = []
    for cls in ("A", "B", "C", "none"):
        mine = [r for r in rows if r.cls == cls]
        if not mine:
            continue
        posted = [(b, c, price.get((r.location, r.product), 0.0)) for r in mine for b, c in lines.get((r.location, r.product), [])]
        exact = sum(1 for b, c, _ in posted if abs(c - b) <= 1e-6)
        classes.append(CycleClass(cls=cls, items=len(mine), per_year=cc.per_year(cls), due=sum(r.due for r in mine),
                                  counted=len(posted), exact=exact, accuracy=round(exact / len(posted), 4) if posted else None,
                                  difference_value=round(sum((c - b) * p for b, c, p in posted), 2)))
    return CyclePlan(as_of=day, location=location, rows=rows, classes=classes, due=sum(r.due for r in rows),
                     currency=ds.settings.currency, notes=notes)


def count_due(ds: Dataset, location: str, as_of: date | None = None, classes: list[str] | None = None,
              ) -> tuple[Dataset, ActionReport]:
    """A physical inventory document for what is due at ``location`` (only ``classes``, when named)."""
    plan = cycle_plan(ds, location, as_of)
    due = [r for r in plan.rows if r.due and (not classes or r.cls in classes)]
    if not due:
        raise StockError("nothing is due for a count here" + (f" in class {', '.join(classes)}" if classes else ""))
    by = defaultdict(int)
    for r in due:
        by[r.cls] += 1
    what = ", ".join(f"{by[c]} {c}" for c in ("A", "B", "C") if by[c])
    new, rep = count_doc(ds, [(r.location, r.product) for r in due], on=plan.as_of,
                         block=ds.execution.cycle_counting.block, note=f"Cycle count {plan.as_of.isoformat()}: {what}")
    return new, rep.model_copy(update={"message": f"Cycle count: {what}. {rep.message}"})
