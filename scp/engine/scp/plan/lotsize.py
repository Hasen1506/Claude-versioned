"""Lot sizing (S/4 guide §8.3): base procedure, then modifiers (min, rounding, max split)."""
from __future__ import annotations

import math

from ..model import LotSizePolicy, LotSizing


def eoq(annual_demand: float, ordering_cost: float, unit_value: float, carrying_rate: float) -> float | None:
    """Economic order quantity √(2DS/H); None when it is undefined (no D, S or H)."""
    h = unit_value * carrying_rate
    if annual_demand <= 0 or ordering_cost <= 0 or h <= 0:
        return None
    return math.sqrt(2.0 * annual_demand * ordering_cost / h)


def base_lot(ls: LotSizing, shortage: float, *, window_requirements: float = 0.0,
             max_stock_gap: float | None = None, eoq_qty: float | None = None) -> float:
    """Base quantity before modifiers.

    ``shortage``            quantity needed now to restore the threshold
    ``window_requirements`` POQ: further requirements inside the covered window
    ``max_stock_gap``       MIN_MAX: max_stock − available
    """
    p = ls.policy
    if p is LotSizePolicy.L4L:
        return shortage
    if p is LotSizePolicy.FIXED:
        if not ls.fixed_qty:     # CV-L01: an explicit error, not an assert that python -O removes
            raise ValueError("a fixed lot size needs its fixed quantity")
        return math.ceil(shortage / ls.fixed_qty - 1e-9) * ls.fixed_qty
    if p is LotSizePolicy.EOQ:
        return max(shortage, eoq_qty) if eoq_qty else shortage
    if p is LotSizePolicy.POQ:
        return shortage + window_requirements
    if p is LotSizePolicy.MIN_MAX:
        return max(shortage, max_stock_gap or 0.0)
    raise ValueError(p)


def apply_modifiers(qty: float, *, mins: list[float], roundings: list[float | None],
                    maxes: list[float | None]) -> list[float]:
    """Raise to the largest minimum, round up to each rounding value, then split by the smallest maximum. Returns
    one or more lot quantities (max-lot splitting creates several orders).

    Every lot of a split stays within the maximum (CV-M02): the maximum is first brought down to a rounding multiple
    (a full lot is then a multiple too), and the last lot is rounded up and raised to the minimum only as far as the
    maximum allows. A minimum above the maximum cannot both hold: the maximum wins and the readiness check reports
    the conflict."""
    q = max([qty, *mins])
    for r in roundings:
        if r:
            q = math.ceil(q / r - 1e-9) * r
    cap = min([m for m in maxes if m], default=None)
    if cap is None or q <= cap + 1e-9:
        return [q]
    full = cap
    for r in roundings:
        if r:
            full = math.floor(full / r + 1e-9) * r
    if full <= 1e-9:          # a rounding value above the maximum: lots of one rounding value each
        full = max((r for r in roundings if r), default=cap)
    n_full = int(q // full + 1e-9)
    rest = q - n_full * full
    lots = [full] * n_full
    if rest > 1e-9:
        least = max(mins, default=0.0)
        if least <= full + 1e-9:
            rest = max(rest, least)
        for r in roundings:
            if r:
                rest = math.ceil(rest / r - 1e-9) * r
        lots.append(min(rest, full))
    return lots
