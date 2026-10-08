"""Stock by batch and stock type from the goods-movement journal (≈ MCHB/MARD for a small company).

A place holds a product in lots: one per batch (``None`` for stock without a batch, such as an opening balance typed at
setup) and stock type (unrestricted, in quality inspection, blocked). Movements post to one lot each; this module sums
them, picks the lots an issue takes (first expiring, first out), numbers new batches, and says which stock planning
may count on: unrestricted stock that has not expired, and stock in quality inspection when the company says so.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from ..model import Batch, Dataset, GoodsMovement, StockType

EPS = 1e-6
Node = tuple[str, str]
LotKey = tuple[str | None, StockType]          # (batch, stock type)


@dataclass
class Lot:
    batch: str | None
    stock_type: StockType
    qty: float
    expires_on: date | None = None

    def expired(self, on: date) -> bool:
        """Past its last day of use on ``on``."""
        return self.expires_on is not None and self.expires_on < on


def batch_index(ds: Dataset) -> dict[tuple[str, str], Batch]:
    return {(b.product, b.id): b for b in ds.batches}


def lots(movs: Iterable[GoodsMovement]) -> dict[Node, dict[LotKey, float]]:
    """Signed quantity per place and product, per (batch, stock type)."""
    out: dict[Node, dict[LotKey, float]] = defaultdict(lambda: defaultdict(float))
    for m in movs:
        out[(m.location, m.product)][(m.batch, m.stock_type)] += m.signed
    return out


def node_lots(ds: Dataset, movs: Iterable[GoodsMovement], node: Node) -> list[Lot]:
    """The lots at one place, with their expiry dates, in the order an issue takes them: stock without a batch first
    (it is the oldest: typed in before the journal began), then by expiry date, then by batch number."""
    bi = batch_index(ds)
    have: dict[LotKey, float] = defaultdict(float)
    for m in movs:
        if (m.location, m.product) == node:
            have[(m.batch, m.stock_type)] += m.signed
    out = [Lot(b, t, q, bi[(node[1], b)].expires_on if b and (node[1], b) in bi else None)
           for (b, t), q in have.items() if abs(q) > EPS]
    return sorted(out, key=fefo)


def fefo(x: Lot) -> tuple:
    return (x.batch is not None, x.expires_on or date.max, x.batch or "")


def usable(ds: Dataset, lot: Lot, on: date) -> bool:
    """Stock planning counts on: unrestricted and not expired, or in quality inspection when the company counts it."""
    if lot.expired(on):
        return False
    return lot.stock_type is StockType.UNRESTRICTED or (
        lot.stock_type is StockType.QUALITY and ds.execution.quality_in_planning)


def pick(ds: Dataset, movs: list[GoodsMovement], node: Node, qty: float, on: date,
         batch: str | None = None, stock_type: StockType = StockType.UNRESTRICTED) -> list[tuple[str | None, float]]:
    """The lots an issue of ``qty`` on ``on`` takes: the batch asked for, else unrestricted, unexpired stock first
    expiring, first out. What the lots do not cover comes out of stock without a batch (and so shows below zero)."""
    if batch is not None:
        return [(batch, qty)]
    prod = ds.product_by_id.get(node[1])
    if prod is None or not prod.batch_managed:
        return [(None, qty)]
    out: list[tuple[str | None, float]] = []
    left = qty
    for lot in node_lots(ds, [m for m in movs if m.date <= on], node):
        if left <= EPS:
            break
        if lot.stock_type is not stock_type or lot.qty <= EPS or lot.expired(on):
            continue
        take = min(left, lot.qty)
        out.append((lot.batch, take))
        left -= take
    if left > EPS:
        out.append((None, left))
    return out


def new_batch(ds: Dataset, product: str, made_on: date, taken: Iterable[Batch] = (), expires_on: date | None = None,
              supplier_batch: str = "", batch: str | None = None) -> Batch:
    """A batch record for a receipt of a batch-managed product: the number given, or the next one for the day
    (``260927-1``, ``260927-2``, …); the expiry given, else the made date plus the product's shelf life."""
    prod = ds.product_by_id[product]
    if expires_on is None and prod.shelf_life_days:
        expires_on = made_on + timedelta(days=prod.shelf_life_days)
    if batch is None:
        stem = made_on.strftime("%y%m%d")
        n = 0
        for b in [*ds.batches, *taken]:
            x = re.fullmatch(re.escape(stem) + r"-(\d+)", b.id)
            if x and b.product == product:
                n = max(n, int(x.group(1)))
        batch = f"{stem}-{n + 1}"
    return Batch(product=product, id=batch, made_on=made_on, expires_on=expires_on, supplier_batch=supplier_batch)


def planning_stock(ds: Dataset, movs: list[GoodsMovement], on: date) -> dict[Node, float]:
    """Stock planning starts from on ``on``, per place: usable lots (see :func:`usable`). Stock without a batch is
    never expired; negative unrestricted stock lowers it (a posting ahead of its receipt)."""
    bi = batch_index(ds)
    out: dict[Node, float] = defaultdict(float)
    for node, by in lots(movs).items():
        for (b, t), q in by.items():
            exp = bi[(node[1], b)].expires_on if b and (node[1], b) in bi else None
            if usable(ds, Lot(b, t, q, exp), on):
                out[node] += q
    return dict(out)


def quality_stock(ds: Dataset, movs: list[GoodsMovement], on: date) -> dict[Node, float]:
    """Stock in quality inspection on ``on``, per place: unexpired inspection lots (≈ MARD-INSME). Planning counts it
    when the company says so; promising and goods issue never take it until it is released."""
    bi = batch_index(ds)
    out: dict[Node, float] = defaultdict(float)
    for node, by in lots(movs).items():
        for (b, t), q in by.items():
            if t is not StockType.QUALITY or q <= EPS:
                continue
            exp = bi[(node[1], b)].expires_on if b and (node[1], b) in bi else None
            if not Lot(b, t, q, exp).expired(on):
                out[node] += q
    return dict(out)


def expiring(ds: Dataset, horizon_end: date) -> dict[Node, list[tuple[date, float, str]]]:
    """Usable batch stock at the planning start that expires before ``horizon_end``, per place: (last day, quantity,
    batch), soonest first. Planning counts what the requirements before that day do not use as gone the day after."""
    if not any(p.batch_managed for p in ds.products) or not ds.batches:
        return {}
    from .stock import before
    start = ds.settings.planning_start
    bi = batch_index(ds)
    out: dict[Node, list[tuple[date, float, str]]] = defaultdict(list)
    for node, by in lots(before(ds, start)).items():
        for (b, t), q in by.items():
            if not b or q <= EPS or (node[1], b) not in bi:
                continue
            exp = bi[(node[1], b)].expires_on
            if exp is None or exp >= horizon_end:
                continue
            lot = Lot(b, t, q, exp)
            if lot.stock_type is StockType.BLOCKED or (lot.stock_type is StockType.QUALITY
                                                        and not ds.execution.quality_in_planning):
                continue
            out[node].append((max(exp, start - timedelta(days=1)), q, b))
    for v in out.values():
        v.sort()
    return dict(out)


def spoilage(lots_: list[tuple[date, float, str]], on_hand: float, used_by: dict[date, float]) -> list[tuple[date, float, str]]:
    """What of each expiring batch is left unused on its last day, first expiring, first out: a batch is used by
    the requirements up to its last day, after the stock without a batch and the batches that expire before it
    (receipts come later, so on-hand is used first). ``used_by``: requirement quantity per day. Returns (the day it
    is gone, quantity, batch)."""
    days = sorted(used_by)
    total = sum(q for _, q, _ in lots_)
    plain = max(0.0, on_hand - total)                # stock without an expiry is used first (it is the oldest)
    out = []
    held = plain
    wasted = 0.0
    for exp, q, b in lots_:
        held = min(held + q, on_hand)              # the journal's lots, as far as the plan's on-hand has them
        used = sum(used_by[d] for d in days if d <= exp)
        left = held - wasted - used
        if left > EPS:
            gone = min(q, left)
            out.append((exp + timedelta(days=1), gone, b))
            wasted += gone
    return out
