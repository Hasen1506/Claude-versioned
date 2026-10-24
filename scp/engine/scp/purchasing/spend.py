"""Spend and sourcing (Enterprise 8.3; docs/CONFORMANCE.md §4, B18 and B21).

Where the buying money goes and where one supplier failing would stop a place. Three amounts per supplier and per
bought product at a place, in the company currency at the supplier's price (duty and freight are the landed cost's, not
spend with the supplier):

* **spent**: what the closed purchase orders of the last year took in, at the source's price for that quantity;
* **committed**: what the open purchase orders still have to deliver;
* **planned**: what the plan's requisitions over its horizon would buy.

Suppliers are classed A, B, C by their share of the total (the company's ABC cut-offs). A bought product with one
usable source at its place (not blocked, valid on the planning start) is single-sourced: its spend, its supplier's
delivery record and lead time say how exposed the place is.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from pydantic import Field

from ..model.common import Out
from ..model.dataset import Dataset
from ..plan.costing import fx

EPS = 1e-9
YEAR = 365


class SupplierSpend(Out):
    supplier: str
    spent: float
    committed: float
    planned: float
    total: float
    share: float                       # of every supplier's total
    abc: str
    products: int                      # bought products at places it supplies
    sole_for: int                      # of them, the ones it is the only usable source for
    on_time: float | None = None       # its closed lines fully delivered by their due date


class ProductSourcing(Out):
    location: str
    product: str
    sources: int                       # usable sources at the place (not blocked, valid on the planning start)
    suppliers: list[str]
    spent: float
    committed: float
    planned: float
    total: float
    single: bool
    lead_time_days: float | None = None   # the main source's
    on_time: float | None = None          # the main source's supplier's


class SpendView(Out):
    currency: str
    since: str                         # the first day the spent amounts count from
    total: float = 0.0
    spent: float = 0.0
    committed: float = 0.0
    planned: float = 0.0
    top_supplier: str | None = None
    top_share: float = 0.0             # the biggest supplier's share of the total
    single_products: int = 0           # bought products at a place with one usable source
    products: int = 0
    single_share: float = 0.0          # share of the total spent on single-sourced products
    suppliers: list[SupplierSpend] = Field(default_factory=list)
    sourcing: list[ProductSourcing] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def spend_view(ds: Dataset, requisitions: list, orders: list, vendors: list) -> SpendView:
    """``requisitions``, ``orders`` and ``vendors`` are the buying view's own (scp.purchasing.purchasing_view)."""
    start = ds.settings.planning_start
    since = start - timedelta(days=YEAR)
    view = SpendView(currency=ds.settings.currency, since=since.isoformat())
    sup_amt: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    prod_amt: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    by_key = defaultdict(list)                        # (supplier, product, location) → its sources
    for pu in ds.purchasing_sources:
        by_key[(pu.supplier, pu.product, pu.location)].append(pu)
    unpriced = 0
    for c in ds.closed_orders:
        if c.kind != "purchase" or not c.counterparty or c.closed_on is None or not since <= c.closed_on < start:
            continue
        pus = by_key.get((c.counterparty, c.product, c.location))
        if not pus or c.delivered_qty <= EPS:
            unpriced += c.delivered_qty > EPS
            continue
        pu = pus[0]
        v = c.delivered_qty * pu.price_for(c.delivered_qty) * fx(ds, ds.price_currency(pu))
        sup_amt[c.counterparty][0] += v
        prod_amt[(c.location, c.product)][0] += v
    for po in orders:
        if not po.supplier:
            continue
        rate = fx(ds, po.currency)
        for ln in po.lines:
            if ln.closed or ln.open <= EPS or ln.price is None:
                continue
            v = ln.open * ln.price * rate
            sup_amt[po.supplier][1] += v
            prod_amt[(po.location, ln.product)][1] += v
    for r in requisitions:
        v = r.qty * r.price * fx(ds, r.currency)
        sup_amt[r.supplier][2] += v
        prod_amt[(r.location, r.product)][2] += v

    on_time = {v.supplier: v.on_time for v in vendors}
    # the bought products at places, with the sources usable on the planning start
    usable: dict[tuple[str, str], list] = defaultdict(list)
    for pu in ds.purchasing_sources:
        v = ds.vendor(pu.supplier)
        ok = not pu.blocked and not v.blocked and (pu.valid_from is None or pu.valid_from <= start) \
            and (pu.valid_to is None or pu.valid_to >= start)
        usable.setdefault((pu.location, pu.product), [])
        if ok:
            usable[(pu.location, pu.product)].append(pu)
    total = sum(sum(a) for a in sup_amt.values())
    for key in sorted(set(usable) | set(prod_amt)):
        pus = sorted(usable.get(key, []), key=lambda p: (p.priority, p.id))
        a = prod_amt.get(key, [0.0, 0.0, 0.0])
        main = pus[0] if pus else None
        view.sourcing.append(ProductSourcing(
            location=key[0], product=key[1], sources=len(pus), suppliers=sorted({p.supplier for p in pus}),
            spent=a[0], committed=a[1], planned=a[2], total=sum(a), single=len(pus) == 1,
            lead_time_days=main.lead_time_days if main else None,
            on_time=on_time.get(main.supplier) if main else None))
    view.sourcing.sort(key=lambda s: (not s.single, -s.total, s.location, s.product))

    fs = ds.forecasting
    cum = 0.0
    sole: dict[str, int] = defaultdict(int)
    supplied: dict[str, int] = defaultdict(int)
    for s in view.sourcing:
        for sp in s.suppliers:
            supplied[sp] += 1
            sole[sp] += s.single
    for sp, a in sorted(sup_amt.items(), key=lambda kv: (-sum(kv[1]), kv[0])):
        t = sum(a)
        before = cum / total if total > EPS else 1.0
        cum += t
        view.suppliers.append(SupplierSpend(
            supplier=sp, spent=a[0], committed=a[1], planned=a[2], total=t, share=t / total if total > EPS else 0.0,
            abc="A" if before < fs.abc_a else "B" if before < fs.abc_b else "C", products=supplied.get(sp, 0),
            sole_for=sole.get(sp, 0), on_time=on_time.get(sp)))
    view.total = total
    view.spent = sum(a[0] for a in sup_amt.values())
    view.committed = sum(a[1] for a in sup_amt.values())
    view.planned = sum(a[2] for a in sup_amt.values())
    if view.suppliers:
        view.top_supplier, view.top_share = view.suppliers[0].supplier, view.suppliers[0].share
    view.products = len(view.sourcing)
    view.single_products = sum(s.single for s in view.sourcing)
    view.single_share = (sum(s.total for s in view.sourcing if s.single) / total) if total > EPS else 0.0
    if unpriced:
        one = unpriced == 1
        view.notes.append(f"{unpriced} closed purchase order{'' if one else 's'} had no source at {'its' if one else 'their'} "
                          f"place to price {'it' if one else 'them'} by, and {'is' if one else 'are'} left out of the spend")
    return view


__all__ = ["ProductSourcing", "SpendView", "SupplierSpend", "spend_view"]
