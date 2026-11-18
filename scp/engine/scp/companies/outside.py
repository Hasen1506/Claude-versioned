"""Retain posted outside-work facts and reconcile custody with material effects."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
import math

from .. import jobwork as jw
from .. import dropship as tp
from ..model import Dataset, MovementType, ReceiptKind, LocationType

EPS = 1e-6


def protect_outside(old: Dataset, proposed: Dataset, open_period: Callable[[date], None]) -> None:
    protect_jobwork(old, proposed, open_period)
    original = {t.id: t for t in old.third_party_orders}
    targets = {t.id: t for t in proposed.third_party_orders}
    billed = {ln.order for inv in old.supplier_invoices for ln in inv.lines}
    billed |= {ln.order for inv in old.invoices for ln in inv.lines if ln.order}
    for tid, prior in original.items():
        if tid not in targets and (prior.sent_on is not None or prior.shipments or tid in billed):
            raise ValueError(f"{tid}: a sent or billed direct-ship order is retained; cancel an unshipped order instead")
    for tid, target in targets.items():
        prior = original.get(tid)
        if prior is None:
            if tid in billed:
                raise ValueError(f"{tid}: a new direct-ship order cannot reclassify an already posted invoice")
            previous_shipments = []
        else:
            immutable = {"shipments", "cancelled", "note", "sent_on"}
            if ((prior.sent_on is not None or prior.shipments or tid in billed)
                    and prior.model_dump(exclude=immutable) != target.model_dump(exclude=immutable)):
                raise ValueError(f"{tid}: sent direct-ship prices, quantities, parties and currency are posted facts")
            if prior.sent_on is not None and target.sent_on != prior.sent_on:
                raise ValueError(f"{tid}: the original supplier-order dispatch date is retained")
            previous_shipments = prior.shipments
            if target.shipments[:len(previous_shipments)] != previous_shipments:
                raise ValueError(f"{tid}: supplier dispatch facts cannot be removed or rewritten")
            if prior.cancelled and not target.cancelled:
                raise ValueError(f"{tid}: a cancelled direct-ship order cannot be restored as open")
        if target.sent_on is not None and target.sent_on < target.ordered_on:
            raise ValueError(f"{tid}: the supplier order cannot be sent before it was taken")
        if target.cancelled and target.shipments:
            raise ValueError(f"{tid}: dispatched goods cannot be cancelled; use the financial correction process")
        if prior is None or prior.sent_on is None:
            if target.sent_on is not None:
                open_period(target.sent_on)
        working = proposed.model_copy(update={"third_party_orders": [
            target.model_copy(update={"shipments": previous_shipments, "cancelled": prior.cancelled if prior else False})
            if t.id == tid else t for t in proposed.third_party_orders]})
        for shipment in target.shipments[len(previous_shipments):]:
            minimum = max([target.ordered_on, *([target.sent_on] if target.sent_on else []),
                           *(s.date for s in next(t for t in working.third_party_orders if t.id == tid).shipments)])
            if shipment.date < minimum:
                raise ValueError(f"{tid}: dispatch cannot precede its supplier order or previous dispatch")
            open_period(shipment.date)
            working, _ = tp.dispatch(working, tid, shipment.qty, shipment.date, shipment.reference, shipment.final)


def protect_jobwork(old: Dataset, proposed: Dataset, open_period: Callable[[date], None]) -> None:
    original = {c.id: c for c in old.challans}
    targets = {c.id: c for c in proposed.challans}
    if original.keys() - targets.keys():
        raise ValueError("posted job-work challans are retained; return the unused parts or cancel the challan")
    old_ids = {m.id for m in old.movements}
    moves = {m.id: m for m in proposed.movements}
    additions = {mid: m for mid, m in moves.items() if mid not in old_ids}
    claimed: set[str] = set()
    allowed_reversals: set[str] = set()
    held = {mid for c in [*old.challans, *proposed.challans] if not c.cancelled
            for ln in c.lines for mid in ln.movements}
    standards = None

    def claim(ids: list[str], day: date):
        if len(set(ids)) != len(ids) or any(mid not in additions or mid in claimed for mid in ids):
            raise ValueError("a job-work operation must identify its own new material movements exactly once")
        rows = [additions[mid] for mid in ids]
        if any(m.date != day for m in rows):
            raise ValueError("job-work records and their material movements keep the same business date")
        claimed.update(ids)
        return rows

    for cid, target in targets.items():
        prior = original.get(cid)
        lifecycle = {"returns", "closed_on", "cancelled", "note"}
        if prior is not None:
            if prior.model_dump(exclude=lifecycle) != target.model_dump(exclude=lifecycle):
                raise ValueError(f"{cid}: sent quantities, values, worker, order and agreed charge are posted facts")
            if target.returns[:len(prior.returns)] != prior.returns:
                raise ValueError(f"{cid}: recorded job-work returns and consumption cannot be removed or rewritten")
            if prior.closed_on is not None or prior.cancelled:
                if prior.model_dump(exclude={"note"}) != target.model_dump(exclude={"note"}):
                    raise ValueError(f"{cid}: a closed or cancelled challan is retained unchanged")
                continue
            pending = target.returns[len(prior.returns):]
        else:
            open_period(target.sent_on)
            order = next((r for r in proposed.receipts if r.id == target.order and r.kind is ReceiptKind.PRODUCTION), None)
            worker = proposed.location_by_id.get(target.job_worker)
            if order is None or order.location != target.ship_from:
                raise ValueError(f"{cid}: a challan names its open production order and issuing plant")
            if worker is None or worker.type is not LocationType.SUPPLIER or proposed.vendor(worker.id).blocked:
                raise ValueError(f"{cid}: the job worker must be an unblocked supplier")
            if any(ln.order == cid for inv in old.supplier_invoices for ln in inv.lines):
                raise ValueError(f"{cid}: adding a challan cannot reclassify a previously posted supplier charge")
            if standards is None:
                standards = jw._unit_values(proposed)
            for ln in target.lines:
                rows = claim(ln.movements, target.sent_on)
                if (not rows or any(m.type is not MovementType.ISSUE or m.reversal_of or m.product != ln.product
                        or m.location != ln.location or m.reference != target.order
                        or m.counterparty != target.job_worker for m in rows)
                        or abs(sum(m.qty for m in rows) - ln.qty) > EPS):
                    raise ValueError(f"{cid}: the parts sent must match their material issues")
                if abs(ln.value - jw._value(proposed, standards, ln.location, ln.product)) > EPS:
                    raise ValueError(f"{cid}: the sent value comes from the company's posting basis")
            pending = target.returns

        lines = {ln.product: ln for ln in target.lines}
        consumed = {p: 0.0 for p in lines}
        previous_day = target.sent_on
        for ret in target.returns:
            if ret.date < previous_day:
                raise ValueError(f"{cid}: a return or loss is dated on or after dispatch and the previous custody event")
            previous_day = ret.date
            if ret.kind == "processed":
                if ret.product != jw.order_product(proposed, target.order):
                    raise ValueError(f"{cid}: processed goods must identify the production order's product")
                if any(p not in lines or not math.isfinite(q) or q < 0 for p, q in ret.used.items()):
                    raise ValueError(f"{cid}: consumed quantities must be nonnegative parts on the challan")
                for p, q in ret.used.items():
                    consumed[p] += q
            else:
                if ret.product not in lines or ret.used:
                    raise ValueError(f"{cid}: unused or lost parts identify a sent part without processed consumption")
                consumed[ret.product] += ret.qty
            if any(q > lines[p].qty + EPS for p, q in consumed.items()):
                raise ValueError(f"{cid}: the worker cannot consume, return or lose more parts than were sent")

        for ret in pending:
            open_period(ret.date)
            rows = claim(ret.movements, ret.date)
            if ret.kind == "processed" and rows:
                if (any(m.reference != target.order or m.reversal_of or m.type not in (
                        MovementType.RECEIPT, MovementType.ISSUE) for m in rows)
                        or abs(sum(m.qty for m in rows if m.type is MovementType.RECEIPT
                                   and m.product == ret.product and m.location == target.ship_from) - ret.qty) > EPS):
                    raise ValueError(f"{cid}: processed returns must match their production receipt")
            elif ret.kind == "unused":
                line = lines[ret.product]
                if (not rows or any(m.reversal_of not in line.movements for m in rows)
                        or abs(sum(abs(m.qty) for m in rows) - ret.qty) > EPS):
                    raise ValueError(f"{cid}: unused returns must match reversals of their original issues")
                allowed_reversals.update(ret.movements)
            elif ret.kind == "lost" and rows:
                raise ValueError(f"{cid}: a loss at the worker does not return parts into plant stock")

        if target.cancelled:
            if target.returns or target.closed_on is None or target.closed_on < target.sent_on:
                raise ValueError(f"{cid}: cancel an unreturned challan with a date on or after dispatch")
            open_period(target.closed_on)
            for line in target.lines:
                rows = [m for m in additions.values() if m.reversal_of in line.movements]
                if any(m.id in claimed for m in rows) or abs(sum(abs(m.qty) for m in rows) - line.qty) > EPS:
                    raise ValueError(f"{cid}: cancellation must return all sent parts through their material reversals")
                claim([m.id for m in rows], target.closed_on)
                allowed_reversals.update(m.id for m in rows)
        else:
            closed = previous_day if all(consumed[p] >= ln.qty - EPS for p, ln in lines.items()) else None
            if target.closed_on != closed:
                raise ValueError(f"{cid}: its closing date follows the recorded custody balance")

    if any(m.reversal_of in held and mid not in allowed_reversals for mid, m in additions.items()):
        raise ValueError("parts on a job-work challan are taken back through its unused-return or cancellation operation")
