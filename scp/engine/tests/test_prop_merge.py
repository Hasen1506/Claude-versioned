"""Property-based merge: two people adding orders at once never orphan an order line (CV-H09).

The base company has some sales orders with lines (``demand`` records ``SO-…/10`` pointing at their header with
``order``). *Theirs* (the save that landed first) and *mine* (the working copy) each add orders independently, so their
numbers clash. After the merge every line still belongs to a header that exists, carries its header's number, no id
is used twice, and nothing either side added is lost."""
from __future__ import annotations

import copy
from collections import Counter

from hypothesis import given, note
from hypothesis import strategies as st

from scp.companies.merge import merge

LINE = {"location": "C1", "product": "P", "date": "2026-10-10", "kind": "sales_order", "qty": 5}


def _orders(first: int, sizes: list[int], who: str) -> tuple[list[dict], list[dict]]:
    heads, lines = [], []
    for i, n in enumerate(sizes):
        oid = f"SO-{first + i:05d}"
        heads.append({"id": oid, "customer": f"{who}{i}"})
        lines += [{**LINE, "id": f"{oid}/{10 * (j + 1)}", "order": oid, "location": f"{who}{i}", "qty": j + 1}
                  for j in range(n)]
    return heads, lines


sizes = st.lists(st.integers(1, 3), min_size=0, max_size=4)


@given(base=sizes, theirs=sizes, mine=sizes, mine_gap=st.integers(0, 2), forecasts=st.integers(0, 2),
       t_extra=st.integers(0, 2), m_extra=st.integers(0, 2))
def test_merging_orders_never_orphans_lines(base, theirs, mine, mine_gap, forecasts, t_extra, m_extra):
    bh, bl = _orders(1, base, "B")
    # both sides may also add lines to an order already in the base (the same next line numbers)
    tx = mx = []
    if bh:
        n0 = base[0]
        tx = [{**LINE, "id": f"SO-00001/{10 * (n0 + j + 1)}", "order": "SO-00001", "location": "B0", "qty": 50 + j}
              for j in range(t_extra)]
        mx = [{**LINE, "id": f"SO-00001/{10 * (n0 + j + 1)}", "order": "SO-00001", "location": "B0", "qty": 60 + j}
              for j in range(m_extra)]
    th, tl = _orders(len(base) + 1, theirs, "T")
    mh, ml = _orders(len(base) + 1 + mine_gap, mine, "M")              # the same (or nearby) numbers as theirs
    fc = [{**LINE, "kind": "forecast", "location": f"F{i}", "qty": 7} for i in range(forecasts)]
    B = {"sales_orders": bh, "demand": bl + fc}
    tl, ml = tl + tx, ml + mx
    T = {"sales_orders": bh + th, "demand": bl + fc + tl}
    M = {"sales_orders": bh + mh, "demand": bl + fc + ml}
    out, rep = merge(copy.deepcopy(B), copy.deepcopy(M), copy.deepcopy(T))
    note(f"renumbered={rep.renumbered}")
    heads = {h["id"]: h for h in out["sales_orders"]}
    ids = [d["id"] for d in out["demand"] if "id" in d]
    assert not [i for i, n in Counter(ids).items() if n > 1], "an id is used twice"
    assert len(heads) == len(out["sales_orders"]), "a header number is used twice"
    for d in out["demand"]:
        if "order" not in d:
            continue
        assert d["order"] in heads, f"{d['id']} points at {d['order']}, which does not exist"
        assert d["id"].split("/", 1)[0] == d["order"], f"{d['id']} is numbered apart from its order {d['order']}"
        # the line stays with the customer its header was taken for
        assert heads[d["order"]]["customer"] == d["location"]
    # nothing lost: every header and line either side added is there (by customer and quantity)
    want_heads = Counter(h["customer"] for h in bh + th + mh)
    assert Counter(h["customer"] for h in out["sales_orders"]) == want_heads
    want_lines = Counter((d["location"], d["qty"]) for d in bl + tl + ml)
    assert Counter((d["location"], d["qty"]) for d in out["demand"] if "order" in d) == want_lines
    assert sum(1 for d in out["demand"] if d["kind"] == "forecast") == forecasts


@given(n=st.integers(1, 4))
def test_merging_a_copy_with_itself_changes_nothing(n):
    bh, bl = _orders(1, [2] * n, "B")
    th, tl = _orders(n + 1, [1], "T")
    B = {"sales_orders": bh, "demand": bl}
    T = {"sales_orders": bh + th, "demand": bl + tl}
    out, rep = merge(copy.deepcopy(B), copy.deepcopy(T), copy.deepcopy(T))
    assert out == T and not rep.renumbered
