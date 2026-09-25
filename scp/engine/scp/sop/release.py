"""Release the constrained plan to MRP, in two parts:

* **demand** — the LP's deliveries replace the forecast demand at each demand point, so MRP plans against
  what the network can actually supply (guide §4 pitfall: never release unconstrained consensus into MRP);
* **build-ahead** — the LP's end-of-bucket stock at every stocking node becomes a stock target MRP keeps
  (linear within each bucket, from nothing at the start). Without it MRP, which plans at infinite capacity,
  would make everything just in time and rebuild the overload the LP avoided by producing early.

The unconstrained numbers stay in the S&OP result for gap analysis, and the release is one undoable dataset
edit (earlier S&OP targets are replaced)."""
from __future__ import annotations

from datetime import timedelta

from ..model import DemandKind, DemandRecord, StockTarget
from ..model.dataset import Dataset
from .result import SopRelease, SopResult


def release_sop(ds: Dataset, res: SopResult) -> tuple[Dataset, SopRelease]:
    if not res.ok:
        raise ValueError("only a solved S&OP plan can be released")
    start = res.buckets[0].start if res.buckets else ds.settings.planning_start
    end = res.buckets[-1].end if res.buckets else start
    lines = {(d.location, d.product): d for d in res.demand}
    keep: list[DemandRecord] = []
    replaced = 0
    for d in ds.demand:
        if d.kind is DemandKind.FORECAST and (d.location, d.product) in lines and start <= d.date < end:
            replaced += 1
            continue
        keep.append(d)
    new: list[DemandRecord] = []
    for (loc, prod), line in sorted(lines.items()):
        for b, qty in zip(res.buckets, line.sales, strict=True):
            if qty <= 1e-6:
                continue
            new.append(DemandRecord(id=f"SOP-{loc}-{prod}-{b.index:03d}"[:64], location=loc, product=prod, date=b.start,
                                    qty=round(qty, 3), kind=DemandKind.FORECAST, period_days=b.days))
    targets = [t for t in ds.stock_targets if t.source != "sop"]
    nodes = 0
    for sl in sorted(res.supply, key=lambda x: (x.location, x.product)):
        if sl.role != "stocking" or max(sl.inventory, default=0.0) <= 1e-6:
            continue
        nodes += 1
        targets.append(StockTarget(location=sl.location, product=sl.product, date=start, qty=0.0))
        for b, qty in zip(res.buckets, sl.inventory, strict=True):
            targets.append(StockTarget(location=sl.location, product=sl.product, date=b.end - timedelta(days=1),
                                       qty=round(max(0.0, qty), 3)))
    out = ds.model_copy(update={"demand": keep + new, "stock_targets": targets})
    return Dataset.model_validate(out.model_dump()), SopRelease(
        nodes=len(lines), records=len(new), replaced=replaced,
        constrained_qty=sum(sum(x.sales) for x in res.demand), unconstrained_qty=sum(sum(x.demand) for x in res.demand),
        target_nodes=nodes)
