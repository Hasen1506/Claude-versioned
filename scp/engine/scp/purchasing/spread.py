"""Measured lead-time spread (S/4 guide §11 outputs, §18.2): how far each supplier's receipts land from their due dates.

A purchase line's due date is its order date plus the planned lead time, so the days between its last goods receipt and
its due date are how much the real lead time differed from the planned one (a day early is −1). Over the lines the
roll-forward closed in the last year, their sample standard deviation is the measured spread of the lead time, the σ_L
safety stock covers (``lead_time_std_days`` on the purchasing source), and their mean is how late the supplier runs on
average, which a longer lead time covers, not safety stock.

Each source is measured from its own lines once it has ``MIN_LINES``; until then from every line its supplier
delivered, to any place and of any part, as a supplier's reliability is mostly the supplier's; with fewer than that
in all, nothing is measured.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

from ..model import Dataset
from ..model.common import Out

MIN_LINES = 3
WINDOW_DAYS = 365


class LeadTimeSpread(Out):
    lines: int                       # closed purchase lines it is measured from
    mean_days_late: float            # receipt − due, on average (negative: early)
    std_days: float                  # sample standard deviation of receipt − due: the measured σ_L
    basis: str                       # "source": this source's own lines; "supplier": all the supplier's lines


def _measure(days: list[int], basis: str) -> LeadTimeSpread:
    n = len(days)
    mean = sum(days) / n
    sd = math.sqrt(sum((d - mean) ** 2 for d in days) / (n - 1))
    return LeadTimeSpread(lines=n, mean_days_late=round(mean, 2), std_days=round(sd, 2), basis=basis)


def measured_spreads(ds: Dataset) -> dict[str, LeadTimeSpread]:
    """Per purchasing source id, its measured spread (sources with too few closed lines are left out)."""
    since = ds.settings.planning_start - timedelta(days=WINDOW_DAYS)
    by_source: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    by_supplier: dict[str, list[int]] = defaultdict(list)
    for c in ds.closed_orders:
        if c.kind != "purchase" or c.last_delivery is None or c.counterparty is None or c.closed_on < since:
            continue
        late = (c.last_delivery - c.due_date).days
        by_source[(c.location, c.product, c.counterparty)].append(late)
        by_supplier[c.counterparty].append(late)
    out: dict[str, LeadTimeSpread] = {}
    for pu in ds.purchasing_sources:
        own = by_source.get((pu.location, pu.product, pu.supplier), [])
        if len(own) >= MIN_LINES:
            out[pu.id] = _measure(own, "source")
        elif len(by_supplier.get(pu.supplier, [])) >= MIN_LINES:
            out[pu.id] = _measure(by_supplier[pu.supplier], "supplier")
    return out
