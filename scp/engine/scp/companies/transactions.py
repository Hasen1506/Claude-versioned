"""Validate persisted financial transitions independently of the browser action path.

Draft/master-data editing remains lenient. Posted movements and invoice facts are
immutable, while invoice lifecycle changes are replayed through the domain rules.
This applies to whole saves, patches, merges and restores alike.
"""
from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from ..model import GoodsMovement, MovementType, PurchaseOrder, SupplierInvoice
from ..plan.costing import fx
from ..purchasing.payables import (
    PayablesError, cancel_invoice, enter_invoice, invoice_entity, lines_index, pay_invoice, release_invoice,
)
from ..validate.lenient import lenient


class TransactionRefused(ValueError):
    pass


def _rows(doc: dict, name: str) -> dict[str, dict]:
    rows = doc.get(name) or []
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not r.get("id") for r in rows):
        raise TransactionRefused(f"{name}: posted records must have unique identifiers")
    out = {r["id"]: r for r in rows}
    if len(out) != len(rows):
        raise TransactionRefused(f"{name}: a posted identifier is listed twice")
    return out


def protect(before: dict, after: dict, email: str) -> dict:
    """Return a normalized document or refuse an invalid financial state transition."""
    names = ("supplier_invoices", "movements", "purchase_orders")
    # No financial records means incomplete master data can still be edited freely.
    if not any(before.get(n) or after.get(n) for n in names):
        return after
    cost_lists = ("purchasing_sources", "production_sources", "resources", "lanes")
    def product_costs(doc):
        return {p.get("id"): (p.get("standard_cost"), p.get("price_control")) for p in doc.get("products") or []
                if p.get("standard_cost") is not None or p.get("price_control") is not None}
    def location_costs(doc):
        return {(p.get("location"), p.get("product")): p["unit_cost"]
                for p in doc.get("location_products") or [] if p.get("unit_cost") is not None}
    def place_costs(doc):
        return {p.get("id"): (p.get("entity"), p.get("type"), p.get("handling_cost_per_unit", 0))
                for p in doc.get("locations") or []}
    settings = ("currency", "fx_rates")
    if (all(before.get(n) == after.get(n) for n in (*names, "receipts", "closed_orders", *cost_lists))
            and all((before.get("settings") or {}).get(k) == (after.get("settings") or {}).get(k) for k in settings)
            and product_costs(before) == product_costs(after)
            and location_costs(before) == location_costs(after)
            and place_costs(before) == place_costs(after)
            and (before.get("finance") or {}).get("closed_through") == (after.get("finance") or {}).get("closed_through")):
        return after
    try:
        old_ds = lenient(before)[0]
        ds = lenient(after)[0]
        old_inv, new_inv = _rows(before, "supplier_invoices"), _rows(after, "supplier_invoices")
        old_moves, new_moves = _rows(before, "movements"), _rows(after, "movements")
        old_pos, new_pos = _rows(before, "purchase_orders"), _rows(after, "purchase_orders")
        if old_ds.settings.currency != ds.settings.currency and (old_inv or old_moves):
            raise TransactionRefused("posted records keep their company currency; use a controlled migration to change it")
        closed = old_ds.finance.closed_through
        if closed is not None and (ds.finance.closed_through is None or ds.finance.closed_through < closed):
            raise TransactionRefused("a closed accounting period cannot be reopened by replacing the document")

        def open_period(on: date) -> None:
            if closed is not None and on <= closed:
                raise TransactionRefused(f"the accounting period through {closed} is closed")

        # Copy only lists that acquire legacy posting metadata; never mutate a caller's working copy.
        result = after
        def replace(name: str, rows: dict[str, dict]) -> None:
            nonlocal result
            result = {**result, name: list(rows.values())}

        for pid, raw in old_pos.items():
            if pid not in new_pos:
                continue  # cancellation/roll may remove headers; related invoice/movement facts stay protected
            prior = PurchaseOrder.model_validate(raw)
            following = PurchaseOrder.model_validate(new_pos[pid])
            rate = prior.fx_rate if prior.fx_rate is not None else fx(old_ds, prior.currency)
            if following.fx_rate is not None and abs(following.fx_rate - rate) > 1e-12:
                raise TransactionRefused(f"{pid}: the posting exchange rate cannot be replaced")
            if following.fx_rate is None:
                new_pos[pid] = {**new_pos[pid], "fx_rate": rate}
                replace("purchase_orders", new_pos)

        if old_moves:
            from ..actuals.valuation import standards
            prices = standards(old_ds)
            for mid, raw in old_moves.items():
                if mid not in new_moves:
                    raise TransactionRefused(f"{mid}: a posted movement is retained; post a reversal instead")
                prior = GoodsMovement.model_validate(raw)
                following = GoodsMovement.model_validate(new_moves[mid])
                # Old data is upgraded from its old cost basis before any master/rate edit is accepted.
                value = prior.standard_price
                if value is None:
                    value = prices.get((prior.location, prior.product),
                                       old_ds.product_by_id[prior.product].standard_cost or 0.0)
                expected = prior.model_copy(update={"standard_price": value})
                if following.standard_price is None:
                    following = following.model_copy(update={"standard_price": value})
                    new_moves[mid] = {**new_moves[mid], "standard_price": value}
                    replace("movements", new_moves)
                if following != expected:
                    raise TransactionRefused(f"{mid}: a posted movement is immutable; post a reversal instead")
                if old_ds.location_by_id[prior.location].entity != ds.location_by_id[prior.location].entity:
                    raise TransactionRefused(f"{prior.location}: a place with posted stock keeps its legal entity")
        new_ids = new_moves.keys() - old_moves.keys()
        if new_ids:
            from ..actuals.valuation import standards
            posting_prices = standards(ds)
        for mid in new_ids:
            movement = GoodsMovement.model_validate(new_moves[mid])
            open_period(movement.date)
            # Posting metadata is checked against the server's basis too. A
            # forged new movement must not restate earlier opening stock.
            expected_price = posting_prices.get((movement.location, movement.product),
                                        ds.product_by_id[movement.product].standard_cost or 0.0)
            if movement.reversal_of in old_moves:
                original = GoodsMovement.model_validate(old_moves[movement.reversal_of])
                expected_price = original.standard_price if original.standard_price is not None else expected_price
            if movement.standard_price is not None and abs(movement.standard_price - expected_price) > 1e-9:
                raise TransactionRefused(f"{mid}: posting prices are determined by the server, not a saved document")
            if movement.opening_standards:
                previous_basis = next((m.opening_standards for m in old_ds.movements if m.opening_standards), None)
                if previous_basis is None:
                    old_prices = standards(old_ds)
                    previous_basis = {}
                    for lp in old_ds.location_products:
                        if lp.on_hand > 1e-6:
                            previous_basis.setdefault(lp.location, {})[lp.product] = old_prices.get(
                                (lp.location, lp.product), old_ds.product_by_id[lp.product].standard_cost or 0.0)
                if movement.opening_standards != previous_basis:
                    raise TransactionRefused(f"{mid}: opening valuation must match the saved company's basis")

        # Purchase receipt tolerances also hold for direct document writes.
        from ..purchasing import received
        totals = received(ds)
        purchase_lines = lines_index(ds, outside=False)
        for mid in new_ids:
            movement = GoodsMovement.model_validate(new_moves[mid])
            line = purchase_lines.get(movement.reference or "")
            if movement.type is MovementType.RECEIPT and line is not None:
                tolerance = ds.vendor(line.supplier).over_delivery_tolerance
                if (movement.location != line.location or movement.product != line.product
                        or tolerance is not None and totals.get(line.id, 0) > line.ordered * (1 + tolerance) + 1e-6):
                    raise TransactionRefused(f"{mid}: the receipt does not match its order or over-delivery tolerance")

        # The price and ownership used by a posted receipt also survive closing
        # its open order during roll-forward. Corrections use invoice debits/credits.
        posted_lines = {m.reference for m in old_ds.movements if m.reference}
        old_lines = lines_index(old_ds, posted_lines, outside=False)
        next_lines = lines_index(ds, posted_lines, outside=False)
        for lid, prior in old_lines.items():
            following = next_lines.get(lid)
            if following is None or any(getattr(prior, f) != getattr(following, f)
                    for f in ("supplier", "product", "location", "price", "currency")):
                raise TransactionRefused(f"{lid}: a received line keeps its posted price and ownership; use a dated correction")

        for iid, raw in old_inv.items():
            if iid not in new_inv:
                raise TransactionRefused(f"{iid}: a posted supplier invoice is retained; cancel it with a date instead")
            prior = SupplierInvoice.model_validate(raw)
            following = SupplierInvoice.model_validate(new_inv[iid])
            rate = prior.fx_rate if prior.fx_rate is not None else fx(old_ds, prior.currency)
            entity = prior.entity if prior.entity is not None else invoice_entity(old_ds, prior.lines)
            if following.fx_rate is None or following.entity is None:
                new_inv[iid] = {**new_inv[iid], "fx_rate": rate, "entity": entity}
                replace("supplier_invoices", new_inv)

        # Use normalized facts, but no newly proposed invoices, as the replay base.
        ds = lenient(result)[0]
        existing = [SupplierInvoice.model_validate(new_inv[i]) for i in new_inv if i in old_inv]
        working = ds.model_copy(update={"supplier_invoices": existing})
        lifecycle = {"payments", "released_by", "released_on", "cancelled", "cancelled_on", "note"}
        for iid, raw in new_inv.items():
            target = SupplierInvoice.model_validate(raw)
            if iid in old_inv:
                prior = SupplierInvoice.model_validate(old_inv[iid])
                prior = prior.model_copy(update={
                    "fx_rate": prior.fx_rate if prior.fx_rate is not None else fx(old_ds, prior.currency),
                    "entity": prior.entity if prior.entity is not None else invoice_entity(old_ds, prior.lines)})
                if prior.model_dump(exclude=lifecycle) != target.model_dump(exclude=lifecycle):
                    raise TransactionRefused(f"{iid}: posted invoice facts cannot be replaced; use a dated correction")
                working = working.model_copy(update={"supplier_invoices": [
                    prior if i.id == iid else i for i in working.supplier_invoices]})
            else:
                open_period(target.date)
                if target.return_id:
                    working = working.model_copy(update={"supplier_returns": [
                        r.model_copy(update={"credit_memo": None}) if r.id == target.return_id else r
                        for r in working.supplier_returns]})
                working, _ = enter_invoice(working, target.supplier,
                    [ln.model_dump() for ln in target.lines], on=target.date, reference=target.reference,
                    tax=target.tax, kind=target.kind, return_id=target.return_id, note=target.note,
                    delivery_costs=target.delivery_costs)
                prior = working.supplier_invoices[-1].model_copy(update={"id": iid})
                working = working.model_copy(update={"supplier_invoices": [*working.supplier_invoices[:-1], prior]})
                if prior.model_dump(exclude=lifecycle | {"id"}) != target.model_dump(exclude=lifecycle | {"id"}):
                    raise TransactionRefused(f"{iid}: the saved invoice does not match its order, receipts and posting basis")
            if target.released_on != prior.released_on or target.released_by != prior.released_by:
                if prior.released_on is not None or target.released_on is None or target.released_by.lower() != email.lower():
                    raise TransactionRefused(f"{iid}: an invoice release is retained and names the signed-in releaser")
                open_period(target.released_on)
                working, _ = release_invoice(working, iid, email, target.released_on)
            if target.payments[:len(prior.payments)] != prior.payments:
                raise TransactionRefused(f"{iid}: posted payments cannot be removed or changed")
            for payment in target.payments[len(prior.payments):]:
                open_period(payment.date)
                working, _ = pay_invoice(working, iid, payment.amount, payment.date, payment.reference)
                if working.supplier_invoices[[i.id for i in working.supplier_invoices].index(iid)].payments[-1] != payment:
                    raise TransactionRefused(f"{iid}: the payment/discount does not match the amount due")
            if target.cancelled != prior.cancelled or target.cancelled_on != prior.cancelled_on:
                if prior.cancelled or not target.cancelled or target.cancelled_on is None:
                    raise TransactionRefused(f"{iid}: cancellation requires a date and cannot be undone by a save")
                open_period(target.cancelled_on)
                working, _ = cancel_invoice(working, iid, target.cancelled_on)
        return result
    except (PayablesError, ValidationError, KeyError, TypeError) as exc:
        raise TransactionRefused(f"financial transition refused: {exc}") from None
