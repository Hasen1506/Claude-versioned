"""Currency units for material accounting, with the existing currency guard for other postings."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dataset import Dataset

NON_TWO_DECIMAL = {
    **dict.fromkeys("BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX VND VUV XAF XOF XPF".split(), 0),
    **dict.fromkeys("BHD IQD JOD KWD LYD OMR TND".split(), 3),
    **dict.fromkeys("CLF UYW".split(), 4),
}
MATERIAL_CURRENCIES = frozenset({"JPY", "KWD"})


class CurrencyPrecisionError(ValueError):
    pass


@dataclass(frozen=True)
class CurrencyUnits:
    digits: int = 2

    def minor(self, value: float | Decimal) -> int:
        scaled = Decimal(str(value)).scaleb(self.digits)
        if not scaled.is_finite():
            raise CurrencyPrecisionError("the currency amount exceeds the exact numeric range of the ledger")
        return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))

    def major(self, minor: int) -> float:
        value = float(Decimal(minor).scaleb(-self.digits))
        if self.digits != 2 and (not isfinite(value) or self.minor(value) != minor):
            raise CurrencyPrecisionError("the currency amount exceeds the exact numeric range of the ledger")
        return value

    def add(self, before: float, delta: float) -> float:
        if self.digits == 2:
            return before + delta
        return self.major(self.minor(before) + self.minor(delta))

    def amount(self, value: float) -> float:
        return round(value + 0.0, 2) if self.digits == 2 else self.major(self.minor(value))

    def product(self, quantity: float, unit_price: float) -> float:
        if self.digits == 2:
            return self.amount(quantity * unit_price)
        return self.major(self.minor(Decimal(str(quantity)) * Decimal(str(unit_price))))

    def total(self, values: Iterable[float]) -> float:
        return self.amount(sum(values)) if self.digits == 2 else self.major(sum(self.minor(value) for value in values))


def material_units(currency: str) -> CurrencyUnits:
    return CurrencyUnits(NON_TWO_DECIMAL[currency]) if currency in MATERIAL_CURRENCIES else CurrencyUnits()


def require_posting_currency(currency: str) -> None:
    digits = NON_TWO_DECIMAL.get(currency.upper(), 2)
    if digits != 2:
        raise CurrencyPrecisionError(f"{currency} uses {digits} decimal places; this operation supports two-decimal currencies only")


def require_material_ledger(ds: Dataset) -> CurrencyUnits:
    """Accept the tested domestic material and receipt-matched supplier invoices."""
    currency = ds.settings.currency
    if currency not in MATERIAL_CURRENCIES:
        require_posting_currency(currency)
        return CurrencyUnits()

    from .actuals import MovementType
    from ..purchasing.payables import lines_index
    if (ds.entities or ds.invoices or ds.intercompany_invoices or ds.production_cost_postings
            or ds.third_party_orders or ds.challans or ds.carrier_bank_accounts or ds.carrier_bank_lines
            or ds.carrier_bank_periods or any(f.settled_on or f.bill_credits or f.bill_events or f.bill_payments
                                            for f in ds.freight_orders)):
        raise CurrencyPrecisionError(f"{currency} currently supports the material ledger only; "
                                     "sales, cash, manufacturing and group books require a two-decimal currency")
    if any((po.currency and po.currency != currency) or po.fx_rate not in (None, 1.0) for po in ds.purchase_orders):
        raise CurrencyPrecisionError(f"{currency} material postings require purchase orders in the company currency at rate 1")
    if any(basis.currency != currency for basis in ds.purchase_valuation):
        raise CurrencyPrecisionError(f"{currency} material postings require valuation terms in the company currency")

    units = material_units(currency)
    lines = lines_index(ds, outside=False)
    for sequence, invoice in enumerate(ds.supplier_invoices, 1):
        if (invoice.kind != "invoice" or invoice.currency != currency or invoice.fx_rate != 1
                or invoice.entity not in ("", None) or invoice.delivery_costs or invoice.payments or invoice.return_id
                or invoice.tax < 0 or units.amount(invoice.tax) != invoice.tax
                or invoice.cancelled and (invoice.cancelled_on is None or invoice.cancelled_after is None
                    or not sequence <= invoice.cancelled_after <= len(ds.supplier_invoices))):
            raise CurrencyPrecisionError(f"{invoice.id}: {currency} supports domestic supplier invoices without extra "
                                         "delivery charges or payments; other postings require a two-decimal currency")
        for ln in invoice.lines:
            order = lines.get(ln.order)
            basis = ds.purchase_valuation_by_id.get(ln.order)
            if (order is None or order.currency != currency or order.supplier != invoice.supplier
                    or order.product != ln.product or order.price != ln.price or round(ln.qty, 6) <= 0
                    or basis is not None and basis.base != ln.price):
                raise CurrencyPrecisionError(f"{invoice.id}: match each supplier invoice line to a local order "
                                             "at its saved price")
    movements = {move.id: move for move in ds.movements}
    ordinary = {MovementType.OPENING, MovementType.RECEIPT, MovementType.ADJUSTMENT, MovementType.SCRAP,
                MovementType.STATUS}
    for move in ds.movements:
        original = movements.get(move.reversal_of) if move.reversal_of else move
        line = lines.get(original.reference) if original and original.reference else None
        if (original is None or move.type not in ordinary or original.type not in ordinary
                or (move.reversal_of and (original.reversal_of or original.date > move.date))
                or (move.reversal_of and original.type not in (MovementType.RECEIPT, MovementType.STATUS))
                or (original.type is MovementType.RECEIPT and
                    (round(original.qty, 6) <= 0 or line is None or line.currency != currency or line.price is None))):
            raise CurrencyPrecisionError(f"{currency} material ledger cannot value movement {move.id}; "
                                         "use supported material movements and priced local purchase receipts")
    return units
