"""Production-order WIP, conversion costs and variance settlement."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING, Literal

from ..actuals.stock import EPS, _sum
from ..actuals.transfer_price import entity_of
from ..model import Dataset, MovementType, ReceiptKind
from ..model.common import Out
from ..model.currency import require_posting_currency
from ..model.finance import ProductionCostPosting

if TYPE_CHECKING:
    from . import Voucher


class ProductionWip(Out):
    order: str
    location: str
    product: str
    company: str
    completed_on: date | None
    balance_minor: int
    other_company_wip: bool
    settlement: str | None


def production_wip(ds: Dataset, day: date, vouchers: list[Voucher]) -> list[ProductionWip]:
    """Attribute the rounded journal lines before any aggregation across orders or entities."""
    open_orders = {r.id: r for r in ds.receipts if r.kind is ReceiptKind.PRODUCTION}
    archived = {r.id: r for r in ds.closed_orders if r.kind == "production" and r.id not in open_orders}
    order_ids = open_orders.keys() | archived.keys()
    moves = [m for m in ds.movements if m.date <= day and m.reference in order_ids]
    qty, _, last, final = _sum(moves, {MovementType.RECEIPT})
    balances: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for voucher in vouchers:
        for line in voucher.lines:
            if line.production_order:
                balances[line.production_order][voucher.company] += round((line.debit - line.credit) * 100)
    posted = [p for p in ds.production_cost_postings if p.date <= day]
    reversed_ids = {p.reversal_of for p in posted if p.reversal_of}
    settled = {p.order: p.id for p in posted if p.kind == "variance" and not p.reversal_of and p.id not in reversed_ids}
    rows = []
    for order in [*open_orders.values(), *archived.values()]:
        company = entity_of(ds, order.location)
        key = (order.id, order.location, order.product)
        observed = qty.get(key, 0)
        active = open_orders.get(order.id)
        completed = None
        if active:
            ordered = active.ordered_qty if active.ordered_qty is not None else active.qty
            tolerance = ds.execution.delivery_tolerance if active.delivery_target_qty is None else 0
            if observed > EPS and (active.id in final or observed + ordered * tolerance >= active.target_qty - EPS):
                completed = last.get(key)
        else:
            closed = archived[order.id]
            still_delivered = observed > EPS and (order.id in final or observed >= closed.delivered_qty - EPS)
            if closed.closed_on <= day and (still_delivered or (key not in qty and closed.delivered_qty > EPS)):
                completed = last.get(key, closed.closed_on)
        book = balances[order.id]
        rows.append(ProductionWip(order=order.id, location=order.location, product=order.product, company=company,
                                  completed_on=completed, balance_minor=book.get(company, 0),
                                  other_company_wip=any(amount for co, amount in book.items() if co != company),
                                  settlement=settled.get(order.id)))
    return sorted(rows, key=lambda row: row.order)


def unsettled(rows: list[ProductionWip]) -> list[str]:
    return [row.order for row in rows if
            (row.completed_on is not None and (row.balance_minor or row.other_company_wip))
            or (row.completed_on is None and row.settlement)]


def protect_orders(before: Dataset, after: Dataset) -> None:
    """Keep the order identity and completion of posted production through saves and rolling."""
    if (before.receipts == after.receipts and before.closed_orders == after.closed_orders
            and before.locations == after.locations and before.execution.delivery_tolerance == after.execution.delivery_tolerance):
        return
    old_ids = {r.id for r in before.receipts if r.kind is ReceiptKind.PRODUCTION}
    old_ids.update(r.id for r in before.closed_orders if r.kind == "production")
    referenced = {m.reference for m in after.movements if m.type in (MovementType.RECEIPT, MovementType.ISSUE)}
    referenced.update(p.order for p in after.production_cost_postings)
    referenced.update(c.order for c in after.challans)
    if not old_ids.intersection(referenced):
        return
    dates = [m.date for m in after.movements if m.reference in old_ids]
    dates.extend(r.closed_on for r in [*before.closed_orders, *after.closed_orders] if r.id in old_ids)
    through = max(dates, default=after.settings.planning_start)
    # Apply the same physical events to both order sets. A real material reversal
    # can reopen the order. Editing the planned quantity cannot un-complete a receipt.
    prior = production_wip(before.model_copy(update={"movements": after.movements}), through, [])
    current = {row.order: row for row in production_wip(after, through, [])}
    for row in prior:
        if row.order not in referenced:
            continue
        target = current.get(row.order)
        if target is None or (target.company, target.location, target.product) != (row.company, row.location, row.product):
            raise ValueError(f"{row.order}: posted production retains its order, company, plant and product")
        if row.completed_on is not None and target.completed_on != row.completed_on:
            raise ValueError(f"{row.order}: posted production completion cannot be replaced by an order edit")


def post(
    ds: Dataset, action: Literal["conversion", "settle", "reverse"], order: str, day: date, reference: str, entry_id: str,
    amount_minor: int | None = None, posting: str | None = None, confirm_actuals: bool = False,
) -> tuple[Dataset, ProductionCostPosting]:
    from . import _day, journal

    require_posting_currency(ds.settings.currency)
    if ds.finance.closed_through is not None and day <= ds.finance.closed_through:
        raise ValueError(f"the accounting period through {ds.finance.closed_through} is closed")
    vouchers, _ = journal(ds, day)
    row = next((r for r in production_wip(ds, day, vouchers) if r.order == order), None)
    if row is None:
        raise ValueError(f"{order}: no production order")
    entries = ds.production_cost_postings
    last = max((p.date for p in entries if p.order == order), default=day)
    if day < last:
        raise ValueError(f"{order}: posting date is before the latest production cost posting on {last}")
    kind = "conversion"
    if action == "conversion":
        if amount_minor is None or amount_minor <= 0 or posting is not None:
            raise ValueError("enter a positive actual conversion amount")
        if row.settlement:
            raise ValueError(f"{order}: reverse its active settlement before adding a cost")
        if any(p.order == order and p.kind == kind and p.reference.casefold() == reference.casefold()
               and not p.reversal_of for p in entries):
            raise ValueError(f"{order}: this source cost reference is already posted")
    elif action == "settle":
        if amount_minor is not None or posting is not None:
            raise ValueError("settlement uses the recorded WIP balance")
        if not confirm_actuals:
            raise ValueError("confirm that the order's actual costs have been reviewed before settlement")
        if row.completed_on is None or row.settlement or row.other_company_wip:
            raise ValueError(f"{order}: settlement requires a completed order, one posting company and no active settlement")
        if not row.balance_minor:
            raise ValueError(f"{order}: WIP already balances")
        if day < _day(ds):
            later, _ = journal(ds, _day(ds))
            if any(v.date > day and any(line.production_order == order for line in v.lines) for v in later):
                raise ValueError(f"{order}: settlement must include its later WIP postings")
        kind, amount_minor = "variance", -row.balance_minor
    else:
        prior = next((p for p in entries if p.id == posting and p.order == order), None)
        if amount_minor is not None or prior is None or prior.reversal_of or any(p.reversal_of == posting for p in entries):
            raise ValueError(f"{order}: choose an original production cost posting that has not been reversed")
        if prior.kind == "conversion" and row.settlement:
            raise ValueError(f"{order}: reverse its active settlement before reversing a cost")
        kind, amount_minor = prior.kind, -prior.amount_minor
        row = row.model_copy(update={"company": prior.entity, "location": prior.location, "product": prior.product})
    entry = ProductionCostPosting(id=entry_id, order=order, date=day, location=row.location,
                                  product=row.product, entity=row.company, kind=kind, amount_minor=amount_minor,
                                  reference=reference, reversal_of=posting)
    return ds.model_copy(update={"production_cost_postings": [*entries, entry]}), entry
