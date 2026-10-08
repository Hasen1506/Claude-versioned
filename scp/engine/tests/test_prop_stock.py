"""Property-based stock postings: inventory is never negative unless the company allows it (R17).

Random sequences of goods movements — receipts (partial, back-dated), production that issues components, scrap,
stock-type moves and reversals — are posted against a small plant. With the rule *refuse*, every posting either goes
through leaving no balance anywhere in the journal below zero (on any day, at any batch), or is refused and changes
nothing. With *allow* (backorders/negative stock permitted) a posting is never refused for lack of stock."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from hypothesis import given, note
from hypothesis import strategies as st

from scp.actuals import PostingError, post
from scp.model import NegativeStock, StockType

from .factory import ds
from .test_stock import plant

EPS = 1e-6
DAY0 = date(2026, 1, 1)

receipt = st.tuples(st.just("receive"), st.sampled_from(["PO-00001", "MO-1", "MO-2"]),
                    st.one_of(st.none(), st.integers(1, 120)), st.integers(0, 12))
action = st.one_of(
    receipt,
    st.tuples(st.just("scrap"), st.just("B"), st.one_of(st.none(), st.integers(1, 120)), st.integers(0, 12)),
    st.tuples(st.just("block"), st.just("B"), st.integers(1, 120), st.integers(0, 12)),
    st.tuples(st.just("reverse"), st.integers(0, 20), st.none(), st.integers(0, 12)),
)


def _do(x, a):
    kind, what, qty, day = a
    on = DAY0 + timedelta(days=day)
    if kind == "receive":
        return post(x, "receive", order=what, qty=qty, on=on)
    if kind == "scrap":
        return post(x, "scrap", location="P", product=what, qty=qty, on=on)
    if kind == "block":
        return post(x, "move", location="P", product=what, qty=qty, to_type=StockType.BLOCKED, on=on)
    movs = [m for m in x.movements if not m.reversal_of and not any(r.reversal_of == m.id for r in x.movements)]
    if not movs:
        raise PostingError("nothing to reverse")
    return post(x, "reverse", movement=movs[what % len(movs)].id, on=on)


def _balances(x) -> list[tuple]:
    """Every (place, product, batch, stock type) running balance that is below zero on some day of the journal."""
    by = defaultdict(list)
    for m in x.movements:
        by[(m.location, m.product, m.batch, m.stock_type)].append(m)
        by[(m.location, m.product, "*", m.stock_type)].append(m)          # the place as a whole too
    bad = []
    for k, ms in by.items():
        for d in sorted({m.date for m in ms}):
            bal = sum(m.signed for m in ms if m.date <= d)
            if bal < -EPS:
                bad.append((k, d, bal))
    return bad


@given(st.lists(action, min_size=1, max_size=10))
def test_refuse_never_leaves_stock_below_zero(actions):
    x = ds(plant())
    x = x.model_copy(update={"execution": x.execution.model_copy(update={"negative_stock": NegativeStock.REFUSE})})
    for a in actions:
        before = x.model_dump_json()
        try:
            x, _ = _do(x, a)
        except PostingError:
            assert x.model_dump_json() == before            # a refused posting changes nothing
            continue
        note(f"after {a}: {[(m.id, m.type.value, m.date.isoformat(), m.batch, m.stock_type.value, m.signed) for m in x.movements]}")
        assert not _balances(x), _balances(x)


@given(st.lists(receipt, min_size=1, max_size=6))
def test_allow_never_refuses_for_lack_of_stock(actions):
    x = ds(plant())
    assert NegativeStock(x.execution.negative_stock) is NegativeStock.ALLOW
    for a in actions:
        try:
            x, _ = _do(x, a)
        except PostingError as e:
            assert "below zero" not in str(e) and "not enough in stock" not in str(e), str(e)
