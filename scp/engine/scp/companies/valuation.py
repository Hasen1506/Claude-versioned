"""Separate posted purchase valuation from editable planning assumptions."""
from __future__ import annotations

from ..actuals.valuation import control_of, purchase_basis
from ..model import Dataset, MovementType
from ..model.purchasing import PurchaseValuationBasis
from ..purchasing.payables import lines_index


def retain_basis(old: Dataset, proposed: Dataset) -> list[PurchaseValuationBasis]:
    old_lines = lines_index(old, outside=False)
    new_lines = lines_index(proposed, outside=False)

    def posted_lines(ds: Dataset, lines: dict) -> set[str]:
        refs = {m.reference for m in ds.movements if m.reference}
        refs.update(ln.order for invoice in ds.supplier_invoices for ln in invoice.lines)
        return refs & lines.keys()

    old_refs = posted_lines(old, old_lines)
    new_refs = posted_lines(proposed, new_lines)
    posted_products = {m.product for m in old.movements if m.type is not MovementType.STATUS}
    posted_products.update(old_lines[lid].product for lid in old_refs)
    for product in posted_products:
        if control_of(old, product) is not control_of(proposed, product):
            raise ValueError(f"{product}: posted stock keeps its valuation method; a change requires a controlled migration")
        prior, following = old.product_by_id.get(product), proposed.product_by_id.get(product)
        if prior is not None and following is not None and prior.base_uom != following.base_uom:
            raise ValueError(f"{product}: posted quantities keep their base unit; a change requires a controlled migration")

    bases = old.purchase_valuation_by_id
    requested = proposed.purchase_valuation_by_id
    if bases.keys() - old_refs:
        raise ValueError("purchase valuation terms must identify a posted stock purchase line")
    expected: dict[str, PurchaseValuationBasis] = {}
    for lid in sorted(old_refs):
        prior, following = old_lines[lid], new_lines.get(lid)
        if following is None or any(getattr(prior, f) != getattr(following, f)
                                   for f in ("supplier", "product", "location", "price", "currency")):
            raise ValueError(f"{lid}: a financially posted line keeps its posted price and ownership; use a dated correction")
        if old.location_by_id[prior.location].entity != proposed.location_by_id[following.location].entity:
            raise ValueError(f"{prior.location}: a place with posted purchase facts keeps its legal entity")
        # Legacy facts acquire the previously saved basis, before any master edit.
        expected[lid] = bases.get(lid) or purchase_basis(old, lid, prior)
    for lid in sorted(new_refs - old_refs):
        expected[lid] = purchase_basis(proposed, lid, new_lines[lid])
    if requested.keys() - expected.keys():
        raise ValueError("purchase valuation terms cannot be supplied for an unposted or unknown line")
    for lid, target in requested.items():
        if target != expected[lid]:
            raise ValueError(f"{lid}: posted purchase valuation terms are determined by the server and retained unchanged")
    # Omitting server metadata cannot erase it, including on pre-upgrade clients.
    return list(expected.values())
