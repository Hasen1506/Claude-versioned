"""What making a product takes, after the BOM and routing rules are applied (S/4 guide §3.3–3.4).

Every module that explodes a BOM or loads a routing asks here, so they agree:

* **Engineering change**: a BOM line is used on orders that start inside its valid-from / valid-to days.
* **Fixed-quantity parts** are issued once per order, whatever its size.
* **Phantom assemblies** (``phantom`` on the part's material-at-plant record, SAP special procurement 50) are
  never stocked: their own parts go straight into the parent, at the parent's step.
* **Step scrap**: each step loses its ``scrap`` share of what enters it, so earlier steps (and the parts
  they consume) handle more; the whole-order ``assembly_scrap`` comes on top.
* **Co- and by-products** come out of the same run in proportion to the main product.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from ..model import Dataset, ProductionSource


@dataclass(frozen=True)
class Need:
    """A part one order of the parent draws: ``per_unit`` × good units made + ``per_order``."""

    product: str
    per_unit: float
    per_order: float
    operation: int | None           # the parent's step that consumes it (None: the first)
    via: tuple[str, ...] = ()       # phantom assemblies it passes through

    def qty(self, good: float) -> float:
        return self.per_unit * good + (self.per_order if good > 0 else 0.0)


def started_factor(ps: ProductionSource) -> float:
    """Units started per good unit: step scrap and the whole-order scrap."""
    kept = math.prod(1.0 - op.scrap for op in ps.operations)
    return 1.0 / (1.0 - ps.assembly_scrap) / kept


def entering(ps: ProductionSource) -> dict[int, float]:
    """Units entering each step per good unit of output."""
    q = started_factor(ps)
    out: dict[int, float] = {}
    for op in sorted(ps.operations, key=lambda o: o.seq):
        out[op.seq] = q
        q *= 1.0 - op.scrap
    return out


def typical_lot(ps: ProductionSource) -> float:
    """The order size a fixed-quantity part is spread over when a per-unit figure is needed (costing, S&OP)."""
    return max(ps.min_lot, ps.output_qty, 1.0)


def phantom_source(ds: Dataset, location: str, product: str, on: date | None) -> ProductionSource | None:
    lp = ds.location_product_by_key.get((location, product))
    if lp is None or not lp.phantom:
        return None
    cands = [ps for ps in ds.production_sources if ps.location == location and ps.product == product
             and (on is None or ((ps.valid_from is None or ps.valid_from <= on) and (ps.valid_to is None or on <= ps.valid_to)))]
    return min(cands, key=lambda p: (p.priority, p.id)) if cands else None


def needs(ds: Dataset, ps: ProductionSource, on: date | None = None, _seen: tuple[str, ...] = ()) -> list[Need]:
    """The parts one order of ``ps`` draws, phantoms passed through. ``on`` is the order's start: BOM lines not
    valid that day are left out (``None``: every line, for the network structure)."""
    ops = sorted(ps.operations, key=lambda o: o.seq)
    first = ops[0].seq if ops else None
    enter = entering(ps)
    rank = {op.seq: i for i, op in enumerate(ops)}
    out: dict[str, Need] = {}

    def add(n: Need) -> None:
        old = out.get(n.product)
        if old is None:
            out[n.product] = n
            return
        seq = min((s for s in (old.operation, n.operation) if s is not None), key=lambda s: rank.get(s, 0), default=None)
        out[n.product] = Need(n.product, old.per_unit + n.per_unit, old.per_order + n.per_order, seq,
                              old.via or n.via)

    for c in ps.components:
        if on is not None and not c.valid_on(on):
            continue
        seq = c.operation or first
        f = enter.get(seq, started_factor(ps)) if seq is not None else started_factor(ps)
        loss = 1.0 - c.scrap
        pu, po = (0.0, c.qty / loss) if c.fixed_qty else (f * c.qty / ps.output_qty / loss, 0.0)
        sub = phantom_source(ds, ps.location, c.product, on) if c.product not in _seen else None
        if sub is None:
            add(Need(c.product, pu, po, seq))
            continue
        for n in needs(ds, sub, on, (*_seen, c.product)):
            add(Need(n.product, pu * n.per_unit, po * n.per_unit + n.per_order, seq, (c.product, *n.via)))
    return list(out.values())


def unit_need(ds: Dataset, ps: ProductionSource, product: str, on: date | None = None) -> float:
    """Issued quantity of ``product`` per good unit, fixed-quantity parts spread over a typical lot."""
    lot = typical_lot(ps)
    return sum(n.per_unit + n.per_order / lot for n in needs(ds, ps, on) if n.product == product)


def co_output(ps: ProductionSource, good: float) -> list[tuple[str, float]]:
    return [(c.product, good * c.qty / ps.output_qty) for c in ps.co_products]


def main_share(ps: ProductionSource) -> float:
    """Share of a run's cost the main product carries."""
    return max(0.0, 1.0 - sum(c.cost_share for c in ps.co_products))


__all__ = ["Need", "co_output", "entering", "main_share", "needs", "phantom_source", "started_factor",
           "typical_lot", "unit_need"]
