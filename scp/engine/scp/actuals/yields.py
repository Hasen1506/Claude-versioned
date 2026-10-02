"""Measured yield: what production orders really used against what the bill of materials says (R17).

A bill of materials carries each part's loss (component scrap: issue = need ÷ (1 − scrap)), so the plan buys the
part with the loss in it. Nobody knows the loss up front; the journal does. Every production order whose parts were
posted as used (not backflushed, which only repeats the bill of materials) shows how much of each part one good unit
really took. Over those orders this module works out the loss each part had, beside the loss the bill of materials
plans with, and says where they differ enough to change it.

Parts that come through a phantom assembly are left out: their loss belongs to the phantom's own bill of materials.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..model import Dataset, MovementType, ProductionSource
from ..plan.structure import needs
from .result import YieldRow

EPS = 1e-9
NOTICE = 0.005        # half a percentage point: a difference smaller than this is noise


def _source(ds: Dataset, oid: str, location: str, product: str, on: date) -> ProductionSource | None:
    """The production version an order was made with: the open order's, the closed order's, else the one planning
    would use on that day."""
    rc = next((r for r in ds.receipts if r.id == oid), None)
    sid = rc.source if rc is not None else None
    if sid is None:
        co = next((c for c in ds.closed_orders if c.id == oid and c.kind == "production"), None)
        if co is not None:
            sid = (co.source_order or {}).get("source") or co.counterparty
    ps = ds.production_source_by_id.get(sid or "")
    if ps is not None and ps.location == location and ps.product == product:
        return ps
    cands = [p for p in ds.production_sources if p.location == location and p.product == product
             and (p.valid_from is None or p.valid_from <= on) and (p.valid_to is None or on <= p.valid_to)]
    return min(cands, key=lambda p: (p.priority, p.id)) if cands else None


def measured_yields(ds: Dataset) -> list[YieldRow]:
    """Per production version and part: the loss the bill of materials plans with and the loss the orders posted with
    actual usage had. Orders whose parts were backflushed say nothing about the loss and are left out."""
    made: dict[str, list] = defaultdict(lambda: [None, None, 0.0, None])   # order → [location, product, good, first day]
    used: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    backflushed: set[str] = set()
    for m in ds.movements:
        if not m.reference:
            continue
        if m.type is MovementType.RECEIPT:
            x = made[m.reference]
            if x[1] is None or (x[0], x[1]) == (m.location, m.product):
                x[0], x[1] = m.location, m.product
                x[2] += m.net
                x[3] = m.date if x[3] is None else min(x[3], m.date)
        elif m.type is MovementType.ISSUE:
            used[m.reference][m.product] += m.net
            if m.note == "Backflush":
                backflushed.add(m.reference)
    acc: dict[tuple[str, str], list] = {}        # (source, part) → [planned without loss, used, orders, good]
    for oid, parts in used.items():
        loc, prod, good, day = made.get(oid, [None, None, 0.0, None])
        if oid in backflushed or prod is None or good <= EPS:
            continue
        ps = _source(ds, oid, loc, prod, day)
        if ps is None:
            continue
        lines = {c.product: c for c in ps.components if c.valid_on(day)}
        for n in needs(ds, ps, day):
            c = lines.get(n.product)
            if c is None or n.via or n.product not in parts:
                continue
            planned = n.qty(good) * (1.0 - c.scrap)      # the need before the part's own loss
            a = acc.setdefault((ps.id, n.product), [0.0, 0.0, 0, 0.0])
            a[0] += planned
            a[1] += parts[n.product]
            a[2] += 1
            a[3] += good
    out = []
    for (sid, part), (planned, actual, orders, good) in sorted(acc.items()):
        if planned <= EPS or actual <= EPS:
            continue
        ps = ds.production_source_by_id[sid]
        line = next(c for c in ps.components if c.product == part)
        loss = max(0.0, 1.0 - planned / actual)
        now = line.scrap
        out.append(YieldRow(source=sid, location=ps.location, product=ps.product, part=part, orders=orders,
                            made=round(good, 6), planned=round(planned / (1.0 - now), 6), used=round(actual, 6),
                            scrap_now=now, scrap_measured=round(min(loss, 0.95), 4),
                            change=abs(loss - now) >= NOTICE))
    return out


__all__ = ["measured_yields"]
