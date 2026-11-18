"""Reject financial posting precision the current two-decimal ledger cannot represent.

Planning can still use these currencies. Supporting their postings requires an
approved currency/rounding implementation and migration, not silently rounding
them to cents. This is a precision guard, not a complete ISO currency master.
"""
from __future__ import annotations

NON_TWO_DECIMAL = {
    **dict.fromkeys("BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX VND VUV XAF XOF XPF".split(), 0),
    **dict.fromkeys("BHD IQD JOD KWD LYD OMR TND".split(), 3),
    **dict.fromkeys("CLF UYW".split(), 4),
}


class CurrencyPrecisionError(ValueError):
    pass


def require_posting_currency(currency: str) -> None:
    digits = NON_TWO_DECIMAL.get(currency.upper(), 2)
    if digits != 2:
        raise CurrencyPrecisionError(f"{currency} uses {digits} decimal places; financial posting and ledger export "
                                     "currently support two-decimal currencies only")
