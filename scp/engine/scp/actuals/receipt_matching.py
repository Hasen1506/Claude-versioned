"""Domestic GR/IR matching in minor units, with stable receipt allocations."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..model import Dataset, GoodsMovement, MovementType, SupplierInvoice
from ..model.currency import CurrencyPrecisionError, CurrencyUnits


def _quantity(value: float) -> int:
    return round(Decimal(str(value)).scaleb(6))


def _slice_value(booked: int, quantity: int, left: int, right: int) -> int:
    # Cumulative half-up rounding allocates every minor unit exactly once.
    twice = 2 * booked
    return ((twice * right + quantity) // (2 * quantity)
            - (twice * left + quantity) // (2 * quantity))


@dataclass(frozen=True)
class ReceiptSlice:
    receipt: str
    start: int
    end: int


@dataclass
class Receipt:
    movement: GoodsMovement
    booked: int
    quantity: int
    free: list[tuple[int, int]]

    def value(self, left: int, right: int) -> int:
        return _slice_value(self.booked, self.quantity, left, right)

    def take(self, quantity: int, *, newest: bool = False) -> list[ReceiptSlice]:
        out = []
        index = -1 if newest else 0
        while quantity and self.free:
            start, end = self.free[index]
            consumed = min(quantity, end - start)
            a, b = (end - consumed, end) if newest else (start, start + consumed)
            out.append(ReceiptSlice(self.movement.id, a, b))
            if consumed == end - start:
                self.free.pop(index)
            else:
                self.free[index] = (start, a) if newest else (b, end)
            quantity -= consumed
        return out


@dataclass
class MaterialMatches:
    movements: dict[str, int] = field(default_factory=dict)
    reversed: dict[str, tuple[ReceiptSlice, ...]] = field(default_factory=dict)
    invoices: dict[str, tuple[tuple[ReceiptSlice, ...], ...]] = field(default_factory=dict)
    invoice_values: dict[str, tuple[int, ...]] = field(default_factory=dict)
    accruals: dict[tuple[str, str], int] = field(default_factory=dict)

    def reversed_cost(self, movement: str, booked: int, quantity: float) -> int:
        return sum(_slice_value(booked, _quantity(quantity), item.start, item.end)
                   for item in self.reversed[movement])


def match_receipts(ds: Dataset, units: CurrencyUnits, prices: dict[str, float],
                   through: date | None = None) -> MaterialMatches:
    """Match dated bills FIFO. Cancellations release the exact original slices."""
    events: list[tuple[date, int, int, GoodsMovement | SupplierInvoice, bool]] = [
        (m.date, 0, i, m, False) for i, m in enumerate(ds.movements)
        if m.type is MovementType.RECEIPT and (m.reference in prices or m.reversal_of)]
    for i, inv in enumerate(ds.supplier_invoices):
        if not inv.cancelled or inv.cancelled_on is not None:
            events.append((inv.date, 1, 2 * i, inv, False))
        if inv.cancelled_on is not None:
            order = 2 * (inv.cancelled_after or len(ds.supplier_invoices)) - 1
            events.append((inv.cancelled_on, 1, order, inv, True))
    receipts: dict[str, Receipt] = {}
    by_order: dict[str, list[Receipt]] = defaultdict(list)
    out = MaterialMatches()

    def value(slices: tuple[ReceiptSlice, ...]) -> int:
        return sum(receipts[s.receipt].value(s.start, s.end) for s in slices)

    for day, _, _, event, cancellation in sorted(events, key=lambda row: row[:3]):
        if through is not None and day > through:
            break
        if isinstance(event, GoodsMovement):
            if event.reversal_of:
                receipt = receipts.get(event.reversal_of)
                if receipt is None:
                    raise CurrencyPrecisionError(f"{event.id}: the original purchase receipt is unavailable")
                needed = _quantity(abs(event.qty))
                slices = tuple(receipt.take(needed, newest=True))
                if sum(s.end - s.start for s in slices) != needed:
                    raise CurrencyPrecisionError(f"{event.id}: cancel the matched supplier invoice before reversing billed stock")
                out.reversed[event.id] = slices
                out.movements[event.id] = value(slices)
            elif (order := event.reference) is not None:
                qty = _quantity(event.qty)
                booked = units.minor(units.product(event.qty, prices[order]))
                receipt = Receipt(event, booked, qty, [(0, qty)])
                receipts[event.id] = receipt
                by_order[order].append(receipt)
                out.movements[event.id] = booked
        elif cancellation:
            for line in out.invoices[event.id]:
                for s in line:
                    free = receipts[s.receipt].free
                    free.append((s.start, s.end))
                    free.sort()
        else:
            allocated = []
            for line in event.lines:
                qty = _quantity(line.qty)
                slices = []
                for receipt in by_order[line.order]:
                    taken = receipt.take(qty)
                    slices.extend(taken)
                    qty -= sum(s.end - s.start for s in taken)
                    if not qty:
                        break
                if qty:
                    raise CurrencyPrecisionError(f"{event.id}: invoice only quantities on unbilled receipts dated on or before the invoice")
                allocated.append(tuple(slices))
            out.invoices[event.id] = tuple(allocated)
            out.invoice_values[event.id] = tuple(value(line) for line in allocated)
    accrued: dict[tuple[str, str], int] = defaultdict(int)
    for order, ordered in by_order.items():
        for receipt in ordered:
            accrued[order, receipt.movement.location] += sum(receipt.value(a, b) for a, b in receipt.free)
    out.accruals = dict(accrued)
    return out
