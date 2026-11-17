"""Persistence-side replay of customer and inter-company financial commands."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

from .. import intercompany as ic, sales, transport
from ..actuals.post import delivered, ordered_now, ship_point
from ..model import Dataset, MovementType


def protect_commercial(old: Dataset, proposed: Dataset, open_period: Callable[[date], None]) -> None:
    # Sales prices remain authoritative after shipment, including after roll-forward.
    for movement in old.movements:
        if movement.type is not MovementType.SALE or not movement.reference:
            continue
        prior = sales.line_record(old, movement.reference)
        following = sales.line_record(proposed, movement.reference)
        if prior is not None and (following is None or any(getattr(prior, k) != getattr(following, k)
                for k in ("location", "product", "price"))):
            raise ValueError(f"{movement.reference}: shipped sales facts are retained; use a credit note")
    old_ids = {m.id for m in old.movements}
    for movement in proposed.movements:
        if movement.id in old_ids or movement.type is not MovementType.SALE or not movement.reference:
            continue
        line = sales.line_record(proposed, movement.reference)
        header = next((h for h in proposed.sales_orders if line and h.id == line.order), None)
        if header is not None and header.credit_block:
            raise ValueError(f"{header.id}: credit is blocked; release it before shipping")
        if line is not None and (movement.product != line.product or movement.location != ship_point(proposed, line)
                or delivered(proposed, movement.reference) > ordered_now(proposed, line) + 1e-6):
            raise ValueError(f"{movement.reference}: shipment exceeds or does not match its sales order")

    for name, module in (("invoices", sales), ("intercompany_invoices", ic)):
        original = {i.id: i for i in getattr(old, name)}
        targets = {i.id: i for i in getattr(proposed, name)}
        if original.keys() - targets.keys():
            raise ValueError(f"{name}: posted documents are retained; use a dated cancellation")
        working = proposed.model_copy(update={name: list(original.values())})
        lifecycle = {"payments", "cancelled", "cancelled_on", "note", "sent_on", "reminder_level", "reminded_on"}
        for iid, target in targets.items():
            if iid in original:
                prior = original[iid]
                if prior.model_dump(exclude=lifecycle) != target.model_dump(exclude=lifecycle):
                    raise ValueError(f"{iid}: posted invoice facts are immutable; use a credit note")
            else:
                open_period(target.date)
                if name == "intercompany_invoices":
                    generated, _ = ic.bill(working, target.date, [ln.movement for ln in target.lines], iid, target.note)
                elif target.kind == "invoice":
                    generated, _ = sales.create_invoices(working, [ln.order for ln in target.lines if ln.order], target.date)
                else:
                    returns = {ln.ret for ln in target.lines if ln.ret}
                    if len(returns) != 1:
                        raise ValueError(f"{iid}: a credit note must identify its received return")
                    rid = next(iter(returns))
                    working = working.model_copy(update={"returns": [
                        r.model_copy(update={"credit_note": None}) if r.id == rid else r for r in working.returns]})
                    generated, _ = sales.credit_return(working, rid, target.date)
                prior = next((i.model_copy(update={"id": iid}) for i in getattr(generated, name)
                              if i.id not in {j.id for j in getattr(working, name)}
                              and i.model_dump(exclude=lifecycle | {"id", "entered_by"})
                              == target.model_dump(exclude=lifecycle | {"id", "entered_by"})), None)
                if prior is None:
                    raise ValueError(f"{iid}: saved billing does not match delivered goods, prices, tax and ownership")
                working = working.model_copy(update={name: [*getattr(working, name), prior]})
            if target.payments[:len(prior.payments)] != prior.payments:
                raise ValueError(f"{iid}: posted payments cannot be removed or changed")
            for payment in target.payments[len(prior.payments):]:
                open_period(payment.date)
                working, _ = module.pay(working, iid, payment.amount, payment.date, payment.reference)
                actual = next(i for i in getattr(working, name) if i.id == iid).payments[-1]
                if actual != payment:
                    raise ValueError(f"{iid}: payment, discount or settlement metadata does not match the amount due")
            if (target.cancelled, target.cancelled_on) != (prior.cancelled, prior.cancelled_on):
                if prior.cancelled or not target.cancelled or target.cancelled_on is None:
                    raise ValueError(f"{iid}: cancellation requires a date and cannot be undone")
                open_period(target.cancelled_on)
                if name == "invoices":
                    working, _ = sales.cancel_invoice(working, iid, on=target.cancelled_on)
                else:
                    working, _ = ic.cancel(working, iid, target.cancelled_on)

    # Shipped/settled carrier facts drive the ledger and cannot be rewritten as a draft.
    freight = {f.id: f for f in proposed.freight_orders}
    for prior in old.freight_orders:
        if prior.status not in ("shipped", "settled"):
            continue
        target = freight.get(prior.id)
        if target is None:
            raise ValueError(f"{prior.id}: shipped freight is retained")
        if prior.status == "settled":
            expected = prior
        elif target.status == "settled":
            if target.settled_on is None or target.billed is None:
                raise ValueError(f"{prior.id}: settlement requires a date and amount")
            open_period(target.settled_on)
            base = proposed.model_copy(update={"freight_orders": [
                prior if f.id == prior.id else f for f in proposed.freight_orders]})
            result, _ = transport.settle(base, prior.id, target.billed, target.bill, target.settled_on)
            expected = next(f for f in result.freight_orders if f.id == prior.id)
        else:
            expected = prior
        if target.model_dump(exclude={"note"}) != expected.model_dump(exclude={"note"}):
            raise ValueError(f"{prior.id}: shipped freight and posted settlement facts cannot be replaced")
    for target in proposed.freight_orders:
        prior = next((f for f in old.freight_orders if f.id == target.id), None)
        if target.status == "settled" and (prior is None or prior.status not in ("shipped", "settled")):
            raise ValueError(f"{target.id}: save the shipment before settling its carrier bill")
