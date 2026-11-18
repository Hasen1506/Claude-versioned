"""A reversal retains its original stock identity and cannot exceed its quantity."""
from __future__ import annotations

from collections import defaultdict

from ..model import Dataset


def protect_reversals(old: Dataset, proposed: Dataset) -> None:
    old_ids = {m.id for m in old.movements}
    moves = {m.id: m for m in proposed.movements}
    positions = {m.id: i for i, m in enumerate(proposed.movements)}
    changed_originals = {m.reversal_of for m in proposed.movements if m.id not in old_ids and m.reversal_of}
    reversed_qty = defaultdict(float)
    mutable = {"id", "date", "qty", "reversal_of", "final", "doc", "note", "serials",
               "standard_price", "transfer_price", "opening_standards"}
    for movement in proposed.movements:
        if movement.reversal_of:
            reversed_qty[movement.reversal_of] += abs(movement.qty)
        if movement.id in old_ids or not movement.reversal_of:
            continue
        original = moves.get(movement.reversal_of)
        if original is None or original.reversal_of:
            raise ValueError(f"{movement.id}: a reversal identifies an original material movement, not another reversal")
        if original.date > movement.date or original.date == movement.date and positions[original.id] >= positions[movement.id]:
            raise ValueError(f"{movement.id}: a reversal cannot precede its original posting")
        if (original.model_dump(exclude=mutable) != movement.model_dump(exclude=mutable)
                or original.qty * movement.qty <= 0 or movement.final
                or not set(movement.serials) <= set(original.serials)):
            raise ValueError(f"{movement.id}: a reversal keeps its original product, place, lot, type and ownership")
    for original_id, qty in reversed_qty.items():
        original = moves.get(original_id)
        # Unchanged inconsistent imports need reviewed migration; any new reversal
        # of that original must satisfy the complete cumulative quantity bound.
        if (original is not None and qty > abs(original.qty) + 1e-6
                and original_id in changed_originals):
            raise ValueError(f"{original_id}: cumulative reversals cannot exceed the original material quantity")
