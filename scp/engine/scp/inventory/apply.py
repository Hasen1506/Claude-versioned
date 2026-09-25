"""Apply the multi-echelon recommendation: write each approved stage's recommended safety stock as a fixed
policy, so MRP holds exactly that stock. One undoable dataset edit, like every release."""
from __future__ import annotations

import math

from ..model import LocationProduct, SafetyStockMethod, SafetyStockPolicy
from ..model.dataset import Dataset
from .result import InventoryResult, PlacementApplied, PlacementChange


def key(location: str, product: str) -> str:
    return f"{location}|{product}"


def recommended(qty: float) -> float:
    """Whole units, rounded up: the recommendation is a floor on the service it buys."""
    return float(math.ceil(qty - 1e-9))


def apply_placement(ds: Dataset, res: InventoryResult, keys: list[str] | None = None) -> tuple[Dataset, PlacementApplied]:
    """``keys`` ("location|product") picks the stages; None applies every stocking stage whose recommendation
    differs from what it holds today by at least one unit."""
    if not res.ok:
        raise ValueError("only a solved placement can be applied")
    stocking = {key(n.location, n.product): n for n in res.nodes if n.role == "stocking"}
    unknown = sorted(set(keys or ()) - set(stocking))
    if unknown:
        raise KeyError(f"not a stocking stage: {', '.join(unknown)}")
    chosen = [stocking[k] for k in keys] if keys is not None else \
        [n for n in stocking.values() if abs(recommended(n.meio_ss) - n.current_ss) >= 1]
    lps = [lp.model_copy() for lp in ds.location_products]
    by_key = {key(lp.location, lp.product): lp for lp in lps}
    out = PlacementApplied(changes=[], value_change=0.0)
    for n in chosen:
        q = recommended(n.meio_ss)
        lp = by_key.get(key(n.location, n.product))
        if lp is None:
            lp = LocationProduct(location=n.location, product=n.product)
            lps.append(lp)
            by_key[key(n.location, n.product)] = lp
        before = lp.safety_stock
        policy = before.model_copy(update={"method": SafetyStockMethod.FIXED, "qty": q}) if q > 0 else \
            before.model_copy(update={"method": SafetyStockMethod.NONE, "qty": None})
        lp.safety_stock = SafetyStockPolicy.model_validate(policy.model_dump())
        out.changes.append(PlacementChange(location=n.location, product=n.product, method_before=before.method.value,
                                           ss_before=n.current_ss, ss_after=q, value_change=(q - n.current_ss) * n.unit_value))
    out.value_change = sum(c.value_change for c in out.changes)
    new = ds.model_copy(update={"location_products": lps})
    return Dataset.model_validate(new.model_dump()), out
