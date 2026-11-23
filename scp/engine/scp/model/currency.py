"""Currency units for material accounting, with the existing currency guard for other postings."""
from __future__ import annotations

from dataclasses import dataclass
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

    def prorated_minor(self, booked: int, quantity: float, original_quantity: float) -> int:
        value = Decimal(booked) * Decimal(str(round(quantity, 6))) / Decimal(str(round(original_quantity, 6)))
        return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def material_units(currency: str) -> CurrencyUnits:
    return CurrencyUnits(NON_TWO_DECIMAL[currency]) if currency in MATERIAL_CURRENCIES else CurrencyUnits()


def require_posting_currency(currency: str) -> None:
    digits = NON_TWO_DECIMAL.get(currency.upper(), 2)
    if digits != 2:
        raise CurrencyPrecisionError(f"{currency} uses {digits} decimal places; this operation supports two-decimal currencies only")


def require_material_ledger(ds: Dataset) -> CurrencyUnits:
    """Accept the tested material ledgers. Keep invoice, cash and manufacturing books guarded."""
    currency = ds.settings.currency
    if currency not in MATERIAL_CURRENCIES:
        require_posting_currency(currency)
        return CurrencyUnits()

    from .actuals import MovementType
    from ..purchasing.payables import lines_index
    if (ds.entities or ds.invoices or ds.supplier_invoices or ds.intercompany_invoices or ds.production_cost_postings
            or ds.third_party_orders or ds.challans or ds.carrier_bank_accounts or ds.carrier_bank_lines
            or ds.carrier_bank_periods or any(f.settled_on or f.bill_credits or f.bill_events or f.bill_payments
                                            for f in ds.freight_orders)):
        raise CurrencyPrecisionError(f"{currency} currently supports the material ledger only; "
                                     "invoice, cash, manufacturing and group books require a two-decimal currency")
    if any((po.currency and po.currency != currency) or po.fx_rate not in (None, 1.0) for po in ds.purchase_orders):
        raise CurrencyPrecisionError(f"{currency} material postings require purchase orders in the company currency at rate 1")
    if any(basis.currency != currency for basis in ds.purchase_valuation):
        raise CurrencyPrecisionError(f"{currency} material postings require valuation terms in the company currency")

    lines = lines_index(ds, outside=False)
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
    return material_units(currency)
