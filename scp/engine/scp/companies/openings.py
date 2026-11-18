"""Materialize previously known setup stock before a financial basis can change."""
from __future__ import annotations

from ..actuals.stock import pending_openings
from ..actuals.valuation import standards
from ..model import Dataset, MovementType


def retain_openings(before: dict, after: dict, old: Dataset, proposed: Dataset) -> tuple[dict, dict, Dataset, Dataset]:
    proposed_ids = {m.id for m in proposed.movements}
    retained = [m for m in old.movements if m.type is MovementType.OPENING
                and m.id.startswith("OP-") and m.id not in proposed_ids]
    if retained:
        restored = list(proposed.movements)
        missing = {m.id for m in retained}
        anchor = None
        for m in reversed(old.movements):
            if m.id in missing:
                index = next((i for i, row in enumerate(restored) if row.id == anchor), len(restored))
                restored.insert(index, m)
            anchor = m.id
        after_rows = {m["id"]: m for m in after.get("movements") or []}
        after = {**after, "movements": [after_rows.get(m.id, m.model_dump(mode="json")) for m in restored]}
        proposed = proposed.model_copy(update={"movements": restored})
    financial = ("movements", "supplier_invoices", "invoices", "intercompany_invoices")
    if not any(before.get(name) or after.get(name) for name in financial):
        return before, after, old, proposed
    openings = pending_openings(old)
    if not any(before.get(name) for name in financial):
        # The first independently authorized stock count can establish an opening
        # instead of the still-unposted setup estimate. Other setup stock is retained.
        established = {(m.location, m.product) for m in proposed.movements
                       if m.type is MovementType.OPENING and m.date < old.settings.planning_start}
        openings = [m for m in openings if (m.location, m.product) not in established]
    if not openings:
        return before, after, old, proposed
    prices = standards(old)
    for move in old.movements:
        for location, products in move.opening_standards.items():
            for product, price in products.items():
                prices[location, product] = price
    openings = [m.model_copy(update={"standard_price": prices.get((m.location, m.product),
                    old.product_by_id[m.product].standard_cost or 0.0)}) for m in openings]
    old_ids = {m.id for m in old.movements}
    new_ids = {m.id for m in proposed.movements}
    if any(m.id in old_ids for m in openings):
        raise ValueError("a setup opening identifier is already used by another material document")
    old_rows = [*(before.get("movements") or []), *(m.model_dump(mode="json") for m in openings)]
    additions = [m for m in openings if m.id not in new_ids]
    new_rows = list(after.get("movements") or [])
    index = next((i for i, m in enumerate(new_rows) if m["id"] not in old_ids), len(new_rows))
    new_rows[index:index] = [m.model_dump(mode="json") for m in additions]
    return ({**before, "movements": old_rows}, {**after, "movements": new_rows},
            old.model_copy(update={"movements": [*old.movements, *openings]}),
            proposed.model_copy(update={"movements": [*proposed.movements[:index], *additions,
                                                       *proposed.movements[index:]]}))
