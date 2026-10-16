"""Strategy advisor from lead times (S/4 guide §5.4): how long customers accept to wait, against how long it takes.

For each product sold, the preferred supply path is followed up from where it is sold: the delivery from the place it
is kept, the place it is made (or bought) and its parts down to the suppliers. Three times come out of it:

* from stock: the last delivery leg alone (what a customer waits when the product is kept in stock nearest them);
* to assemble (ALT): making it from parts in stock, plus the delivery from the plant to the customer;
* from scratch (CLT): making it after its parts are bought or made in turn, the longest path through the bill of
  materials, plus the delivery.

Against the days customers accept to wait (CDT, the product's ``customer_wait_days``): CDT ≥ CLT → make to order (no
stock, no forecast needed); ALT ≤ CDT < CLT → assemble to order (parts to the forecast, the product on order);
CDT < ALT → make to stock, orders consuming the forecast. A strategy that cannot meet the wait is flagged: made to
order where that takes longer than customers wait, or assembled to order where assembling does.
"""
from __future__ import annotations

from typing import Literal

from ..model import Dataset, Strategy
from ..model.common import Out
from ..network import Node, build_graph
from .leadtime import nominal_lead_time_days

Advice = Literal["MTO", "ATO", "MTS_CONSUME"]
LABEL = {"MTS": "made to stock", "MTS_CONSUME": "made to stock, orders using up the forecast", "MTO": "made to order",
         "ATO": "assembled to order", "ASSEMBLY": "made to stock, its forecast used up by its parents"}


class StrategyAdvice(Out):
    product: str
    sold_at: str                         # the place the slowest path starts from (a customer, or where it is sold)
    kept_at: str | None = None           # the place it is made, else bought
    set_at: str | None = None            # where the strategy planning its demand is read (Dataset.demand_lp_at)
    made: bool = False                   # made (has parts), not bought
    strategy: str                        # how it is planned now
    wait_days: float | None = None       # days customers accept to wait (empty: not said)
    from_stock_days: float               # the last delivery leg
    assemble_days: float | None = None   # ALT + delivery: made from parts in stock (None: bought, nothing to assemble)
    scratch_days: float                  # CLT + delivery: everything from the suppliers
    advised: Advice | None = None
    fits: bool | None = None             # the current strategy meets the wait (None: no wait given)
    reason: str = ""


class StrategyAdvisor(Out):
    rows: list[StrategyAdvice] = []
    notes: list[str] = []


def _r(x: float) -> float:
    return round(x, 1)


def strategy_advice(ds: Dataset) -> StrategyAdvisor:
    g = build_graph(ds)
    memo: dict[Node, float] = {}

    def lt(n: Node) -> float:
        opts = g.options.get(n) or []
        return (nominal_lead_time_days(ds, opts[0]) or 0.0) if opts else 0.0

    def scratch(n: Node, seen: frozenset[Node] = frozenset()) -> float:
        """Days to supply ``n`` with nothing in stock: its own lead time plus the slowest of what it is made from."""
        if n in memo:
            return memo[n]
        opts = g.options.get(n) or []
        if not opts or n in seen:
            return 0.0
        o = opts[0]
        ups = [] if o.kind == "buy" else list(o.upstream)
        v = lt(n) + max((scratch(u, seen | {n}) for u in ups), default=0.0)
        memo[n] = v
        return v

    starts: dict[str, list[Node]] = {}
    for d in ds.demand:
        # a planning material is never sold itself: its variants are
        if (d.product in ds.product_by_id and d.product not in ds.variants_of
                and ds.location_type(d.location) is not None):
            starts.setdefault(d.product, [])
            if (d.location, d.product) not in starts[d.product]:
                starts[d.product].append((d.location, d.product))
    rows: list[StrategyAdvice] = []
    for prod, nodes in sorted(starts.items()):
        best: StrategyAdvice | None = None
        for start in nodes:
            # down the preferred path: transfers until the place it is made or bought
            leg: float | None = None
            delivery = 0.0
            n, seen = start, {start}
            while True:
                opts = g.options.get(n) or []
                if not opts or opts[0].kind != "transfer":
                    break
                t = lt(n)
                leg = t if leg is None else leg
                delivery += t
                up = opts[0].upstream[0]
                if up in seen:
                    break
                seen.add(up)
                n = up
            opts = g.options.get(n) or []
            made = bool(opts) and opts[0].kind == "make"
            row = StrategyAdvice(
                product=prod, sold_at=start[0], kept_at=n[0] if opts else None, made=made,
                set_at=ds.demand_lp_at(start) or (n[0] if opts else None),
                strategy=ds.demand_lp(start).strategy.value,
                wait_days=ds.product_by_id[prod].customer_wait_days,
                from_stock_days=_r(leg or 0.0),
                assemble_days=_r(lt(n) + delivery) if made else None,
                scratch_days=_r(scratch(n) + delivery))
            if best is None or row.scratch_days > best.scratch_days:
                best = row
        if best is not None:
            rows.append(_judge(best))
    notes: list[str] = []
    if not rows:
        notes.append("Nothing is sold yet: the advisor reads the products that have orders or a forecast.")
    elif all(r.wait_days is None for r in rows):
        notes.append("Say how many days customers accept to wait for each product (its customer wait days) to see "
                     "which strategy fits.")
    return StrategyAdvisor(rows=rows, notes=notes)


def _judge(r: StrategyAdvice) -> StrategyAdvice:
    w = r.wait_days
    if w is None:
        r.reason = "Customers' wait not given."
        return r
    alt = r.assemble_days
    if w + 1e-9 >= r.scratch_days:
        r.advised = "MTO"
        r.reason = (f"Customers wait {w:g} days and it takes {r.scratch_days:g} from the suppliers: make it to order, "
                    "with no stock or forecast.")
    elif alt is not None and w + 1e-9 >= alt:
        r.advised = "ATO"
        r.reason = (f"Customers wait {w:g} days: enough to assemble it ({alt:g} days) but not to get its parts "
                    f"({r.scratch_days:g}). Keep the parts to the forecast and assemble to order.")
    else:
        r.advised = "MTS_CONSUME"
        what = f"assembling it takes {alt:g}" if alt is not None else f"getting it takes {r.scratch_days:g}"
        r.reason = (f"Customers wait {w:g} days and {what}: keep it in stock to the forecast, orders using it up.")
    s = r.strategy
    if s == Strategy.MTO.value:
        r.fits = w + 1e-9 >= r.scratch_days
    elif s == Strategy.ATO.value:
        r.fits = alt is not None and w + 1e-9 >= alt
    else:
        r.fits = w + 1e-9 >= r.from_stock_days
    now = LABEL.get(s, s)
    if not r.fits:
        took = (r.scratch_days if s == Strategy.MTO.value else alt if s == Strategy.ATO.value and alt is not None
                else r.from_stock_days)
        r.reason = f"Now {now}: that takes {took:g} days and customers wait {w:g}, so orders will be late. " + r.reason
    elif s != r.advised and not (r.advised == "MTS_CONSUME" and s in ("MTS", "ASSEMBLY")):
        r.reason = f"Now {now}, which meets the wait. " + r.reason
    return r


__all__ = ["StrategyAdvice", "StrategyAdvisor", "strategy_advice"]
