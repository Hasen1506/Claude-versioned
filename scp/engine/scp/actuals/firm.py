"""Firming (S/4 conversion of planned orders): planned orders become firm receipts that MRP keeps.

A make order becomes a production order that reserves its components; a transfer becomes a stock
transport order that reserves the goods at its origin until they are issued; a buy becomes a purchase
order. Re-planning after firming everything therefore reproduces the same projection with no new orders.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from ..model import Dataset, LocationType, ReceiptKind, Reservation, ScheduledReceipt
from ..plan import PlanResult
from .result import FirmedOrder, FirmReport

PREFIX = {"make": ("PRD", ReceiptKind.PRODUCTION), "buy": ("PO", ReceiptKind.PURCHASE),
          "transfer": ("STO", ReceiptKind.TRANSFER)}


def _next_numbers(ds: Dataset) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for oid in [r.id for r in ds.receipts] + [c.id for c in ds.closed_orders]:
        m = re.fullmatch(r"(PRD|PO|STO)-(\d+)", oid)
        if m:
            out[m.group(1)] = max(out[m.group(1)], int(m.group(2)))
    return out


def firm_orders(ds: Dataset, plan: PlanResult, ids: list[str] | None = None,
                within_days: int | None = None) -> tuple[Dataset, FirmReport]:
    rep = FirmReport(ok=False, firmed=[], skipped={})
    if not plan.ok:
        return ds, rep
    horizon = ds.settings.planning_start + timedelta(days=ds.execution.firm_zone_days if within_days is None
                                                     else within_days)
    wanted = set(ids) if ids is not None else None
    reqs = defaultdict(list)
    for rq in plan.requirements:
        if rq.parent_order:
            reqs[rq.parent_order].append(rq)
    num = _next_numbers(ds)
    receipts = list(ds.receipts)
    for o in plan.orders:
        if wanted is not None:
            if o.id not in wanted:
                continue
        elif o.start_date >= horizon:
            continue
        if not o.convertible:
            rep.skipped[o.id] = "forecast-driven supply of an assemble-to-order product: firmed by the sales order"
            continue
        if ds.location_type(o.location) is LocationType.CUSTOMER:
            rep.skipped[o.id] = "a delivery to a customer: promised and shipped, not firmed"
            continue
        prefix, kind = PREFIX[o.kind]
        num[prefix] += 1
        rid = f"{prefix}-{num[prefix]:05d}"
        rvs = [Reservation(location=r.location, product=r.product, date=r.date, qty=r.qty) for r in reqs.get(o.id, [])]
        receipts.append(ScheduledReceipt(id=rid, kind=kind, location=o.location, product=o.product, qty=o.qty,
                                         due_date=o.due_date, start_date=o.start_date, source=o.source_id,
                                         reservations=rvs))
        rep.firmed.append(FirmedOrder(planned_id=o.id, receipt_id=rid, kind=kind.value, location=o.location,
                                      product=o.product, qty=o.qty, start_date=o.start_date, due_date=o.due_date,
                                      reservations=len(rvs)))
    if wanted is not None:
        for oid in sorted(wanted - {f.planned_id for f in rep.firmed} - set(rep.skipped)):
            rep.skipped[oid] = "not in the current plan (re-run supply planning)"
    rep.ok = True
    return ds.model_copy(update={"receipts": receipts}), rep
