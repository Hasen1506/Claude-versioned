"""Validate persisted financial transitions independently of the browser action path.

Draft/master-data editing remains lenient. Posted movements and invoice facts are
immutable, while invoice lifecycle changes are replayed through the domain rules.
This applies to whole saves, patches, merges and restores alike.
"""
from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from ..model import GoodsMovement, MovementType, PurchaseOrder, SupplierInvoice
from ..purchasing.payables import (
    cancel_invoice, enter_invoice, invoice_entity, lines_index, pay_invoice, posting_rate, release_invoice,
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
    names = ("supplier_invoices", "movements", "purchase_orders", "invoices", "intercompany_invoices", "freight_orders",
             "inventory_docs", "challans", "third_party_orders", "purchase_valuation")
    # No financial records means incomplete master data can still be edited freely.
    if not any(before.get(n) or after.get(n) for n in names):
        return after
    cost_lists = ("purchasing_sources", "production_sources", "resources", "lanes", "transfer_prices", "vendors", "entities")
    def product_costs(doc):
        display = {"id", "name", "family", "price", "tax_rate", "barcode", "shelf_life_days", "batches",
                   "inspect_on_receipt", "cold_chain", "whole_units"}
        return [(p.get("id"), relevant) for p in doc.get("products") or []
                if (relevant := {k: v for k, v in p.items() if k not in display})]
    def location_costs(doc):
        # Procurement/phantom policy changes the graph used by the cost roll-up.
        # Preserve row order too: collapsing duplicates could hide the row the engine uses.
        return doc.get("location_products") or []
    def place_costs(doc):
        return [(p.get("id"), p.get("entity"), p.get("type"), p.get("handling_cost_per_unit", 0))
                for p in doc.get("locations") or []]
    settings = ("currency", "fx_rates", "planning_start")
    if (all(before.get(n) == after.get(n) for n in (*names, "receipts", "closed_orders", *cost_lists))
            and all((before.get("settings") or {}).get(k) == (after.get("settings") or {}).get(k) for k in settings)
            and product_costs(before) == product_costs(after)
            and location_costs(before) == location_costs(after)
            and place_costs(before) == place_costs(after)
            and (before.get("execution") or {}).get("price_control") == (after.get("execution") or {}).get("price_control")
            and (before.get("finance") or {}).get("closed_through") == (after.get("finance") or {}).get("closed_through")):
        if any(before.get(n) != after.get(n) for n in ("demand", "sales_orders", "returns")):
            from .commercial import protect_commercial
            try:
                protect_commercial(lenient(before)[0], lenient(after)[0], lambda day: None)
            except (ValueError, KeyError, TypeError) as exc:
                raise TransactionRefused(f"financial transition refused: {exc}") from None
        return after
    try:
        old_ds = lenient(before)[0]
        ds = lenient(after)[0]
        from .openings import retain_openings
        before, after, old_ds, ds = retain_openings(before, after, old_ds, ds)
        from ..model.currency import require_posting_currency
        require_posting_currency(ds.settings.currency)
        for invoice in ds.supplier_invoices:
            require_posting_currency(invoice.currency or ds.settings.currency)
        from ..model.sales import Invoice
        from ..model.intercompany import IntercompanyInvoice
        from ..model.transport import FreightOrder
        from ..model.actuals import InventoryDoc
        from ..model.outside import JobWorkChallan, ThirdPartyOrder
        from ..model.purchasing import PurchaseValuationBasis
        for name, model in (("invoices", Invoice), ("intercompany_invoices", IntercompanyInvoice), ("freight_orders", FreightOrder),
                            ("inventory_docs", InventoryDoc), ("challans", JobWorkChallan),
                            ("third_party_orders", ThirdPartyOrder), ("purchase_valuation", PurchaseValuationBasis)):
            for raw in [*_rows(before, name).values(), *_rows(after, name).values()]:
                model.model_validate(raw)
        old_inv, new_inv = _rows(before, "supplier_invoices"), _rows(after, "supplier_invoices")
        old_moves, new_moves = _rows(before, "movements"), _rows(after, "movements")
        old_pos, new_pos = _rows(before, "purchase_orders"), _rows(after, "purchase_orders")
        if old_ds.settings.currency != ds.settings.currency and (old_inv or old_moves or any(
                t.sent_on is not None or t.shipments for t in old_ds.third_party_orders)):
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

        from .valuation import retain_basis
        basis = retain_basis(old_ds, ds)
        if basis or after.get("purchase_valuation"):
            values = [b.model_dump(mode="json") for b in basis]
            if after.get("purchase_valuation") != values:
                result = {**result, "purchase_valuation": values}
            ds = ds.model_copy(update={"purchase_valuation": basis})

        from ..sales import posting_entity
        normalized = [i.model_copy(update={"entity": posting_entity(old_ds, i.lines, i.reference)})
                      if i.entity is None else i for i in old_ds.invoices]
        old_ds = old_ds.model_copy(update={"invoices": normalized})
        existing_sales = {i.id: i for i in normalized}
        invoices = _rows(after, "invoices")
        for iid, raw in invoices.items():
            if iid in existing_sales and raw.get("entity") is None:
                invoices[iid] = {**raw, "entity": existing_sales[iid].entity}
                replace("invoices", invoices)

        for pid, raw in old_pos.items():
            if pid not in new_pos:
                continue  # cancellation/roll may remove headers; related invoice/movement facts stay protected
            prior = PurchaseOrder.model_validate(raw)
            following = PurchaseOrder.model_validate(new_pos[pid])
            rate = prior.fx_rate if prior.fx_rate is not None else posting_rate(old_ds, prior.currency)
            if following.fx_rate is not None and abs(following.fx_rate - rate) > 1e-12:
                raise TransactionRefused(f"{pid}: the posting exchange rate cannot be replaced")
            if following.fx_rate is None:
                new_pos[pid] = {**new_pos[pid], "fx_rate": rate}
                replace("purchase_orders", new_pos)

        for pid in new_pos.keys() - old_pos.keys():
            order = PurchaseOrder.model_validate(new_pos[pid])
            rate = posting_rate(ds, order.currency)
            if order.fx_rate is not None and abs(order.fx_rate - rate) > 1e-12:
                raise TransactionRefused(f"{pid}: the order exchange rate is determined by the saved company")
            if order.fx_rate is None:
                new_pos[pid] = {**new_pos[pid], "fx_rate": rate}
                replace("purchase_orders", new_pos)

        if old_moves:
            from ..actuals.valuation import standards
            from ..actuals.transfer_price import posting_price, shipment_prices
            prices = standards(old_ds)
            transfer_prices = shipment_prices(old_ds, prices)
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
                transfer = prior.transfer_price if prior.transfer_price is not None else (
                    transfer_prices.get(mid) if mid in transfer_prices else posting_price(old_ds, prices, prior))
                expected = prior.model_copy(update={"standard_price": value, "transfer_price": transfer})
                if following.transfer_price is None and transfer is not None:
                    following = following.model_copy(update={"transfer_price": transfer})
                    new_moves[mid] = {**new_moves[mid], "transfer_price": transfer}
                    replace("movements", new_moves)
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
            from ..actuals.documents import _negative
            from ..actuals.stock import pending_openings
            additions = [GoodsMovement.model_validate(raw) for mid, raw in new_moves.items() if mid in new_ids]
            opening_nodes = {(m.location, m.product) for m in additions if m.type is MovementType.OPENING}
            pending = [m for m in pending_openings(old_ds) if (m.location, m.product) not in opening_nodes]
            # Inventory rules use the saved policy and opening balances, never a
            # simultaneously inflated planning balance or relaxed stock policy.
            _negative(old_ds, [*old_ds.movements, *pending], additions, min(m.date for m in additions))
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
            from ..actuals.transfer_price import posting_price
            expected_transfer = posting_price(ds, posting_prices, movement)
            if movement.reversal_of in old_moves:
                expected_transfer = new_moves[movement.reversal_of].get("transfer_price")
            if movement.transfer_price is not None and movement.transfer_price != expected_transfer:
                raise TransactionRefused(f"{mid}: transfer posting prices are determined by the server")
            if movement.transfer_price is None and expected_transfer is not None:
                new_moves[mid] = {**new_moves[mid], "transfer_price": expected_transfer}
                replace("movements", new_moves)
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
            rate = prior.fx_rate if prior.fx_rate is not None else posting_rate(old_ds, prior.currency)
            entity = prior.entity if prior.entity is not None else invoice_entity(old_ds, prior.lines)
            if following.fx_rate is None or following.entity is None:
                new_inv[iid] = {**new_inv[iid], "fx_rate": rate, "entity": entity}
                replace("supplier_invoices", new_inv)
            # Pre-upgrade payments have no independently known bank rate. Retain
            # their original invoice-rate treatment; only new settlements use today's rate.
            payments = [p.model_copy(update={"fx_rate": p.fx_rate if p.fx_rate is not None else rate})
                        for p in prior.payments]
            if following.payments[:len(payments)] == prior.payments and payments != prior.payments:
                new_inv[iid] = {**new_inv[iid], "payments": [
                    p.model_dump(mode="json") for p in [*payments, *following.payments[len(payments):]]]}
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
                    "fx_rate": prior.fx_rate if prior.fx_rate is not None else posting_rate(old_ds, prior.currency),
                    "entity": prior.entity if prior.entity is not None else invoice_entity(old_ds, prior.lines)})
                prior = prior.model_copy(update={"payments": [p.model_copy(update={
                    "fx_rate": p.fx_rate if p.fx_rate is not None else prior.fx_rate}) for p in prior.payments]})
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
                if prior.model_dump(exclude=lifecycle | {"id", "entered_by"}) != target.model_dump(exclude=lifecycle | {"id", "entered_by"}):
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
        from .commercial import protect_commercial
        protect_commercial(old_ds, ds, open_period)
        from .outside import protect_outside
        protect_outside(old_ds, ds, open_period)
        from .materials import protect_materials
        protect_materials(old_ds, ds, open_period)
        if ds.finance.closed_through is not None and ds.finance.closed_through != closed:
            from ..accounting import view
            books = view(ds, period_end=ds.finance.closed_through)
            if any(not check.ok for check in books.checks) or any(
                    row.account == "SUSPENSE" and abs(row.balance) >= .005 for row in books.balances):
                raise TransactionRefused("reconcile the books and clear suspense before closing the accounting period")
        return result
    except (ValueError, ValidationError, KeyError, TypeError) as exc:
        raise TransactionRefused(f"financial transition refused: {exc}") from None
