"""Material-document invariants and independently replayed physical inventory."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date
import json

from ..actuals.documents import cancel_counts, capture_count_book, count_doc, enter_counts, post_counts
from ..actuals.stock import pending_openings, stock
from ..model import Dataset, MovementType

POSTING_META = {"id", "doc", "standard_price", "transfer_price", "opening_standards"}


def _signature(movement) -> str:
    return json.dumps(movement.model_dump(mode="json", exclude=POSTING_META), sort_keys=True)


def protect_materials(old: Dataset, proposed: Dataset, open_period: Callable[[date], None]) -> None:
    from .reversals import protect_reversals
    protect_reversals(old, proposed)
    old_ids = {m.id for m in old.movements}
    additions = [m for m in proposed.movements if m.id not in old_ids]
    original_order, proposed_order = defaultdict(list), defaultdict(list)
    for m in old.movements:
        original_order[m.date].append(m.id)
    for m in proposed.movements:
        if m.id in old_ids:
            proposed_order[m.date].append(m.id)
    if original_order != proposed_order:
        raise ValueError("the posting order of existing material documents within a day is retained")
    disabled = {p.id for p in old.products if p.serial_numbers and p.id in proposed.product_by_id
                and not proposed.product_by_id[p.id].serial_numbers}
    if disabled and any(product in disabled and abs(qty) > 1e-6 for (_location, product), qty
                        in stock([*old.movements, *pending_openings(old)]).items()):
        raise ValueError("a serial-number profile cannot be disabled while its stock is held; use a controlled migration")
    statuses = defaultdict(float)
    for m in additions:
        if m.type is MovementType.STATUS:
            statuses[(m.doc or "", m.date, m.location, m.product, m.sales_order)] += m.signed
    if any(abs(q) > 1e-6 for q in statuses.values()):
        raise ValueError("a stock-status transfer must conserve quantity in each material document")

    original = {d.id: d for d in old.inventory_docs}
    targets = {d.id: d for d in proposed.inventory_docs}
    if original.keys() - targets.keys():
        raise ValueError("physical inventory documents are retained; cancel an open count instead of deleting it")
    busy = {}
    for target in targets.values():
        if target.status == "open":
            for item in target.items:
                node = (item.location, item.product)
                if node in busy and busy[node] != target.id:
                    raise ValueError(f"{item.product} at {item.location} is already on {busy[node]}")
                busy[node] = target.id
    count_movements = set()
    opening_allowance = Counter()
    old_docs = {m.doc for m in old.movements if m.doc}
    for did, target in targets.items():
        prior = original.get(did)
        if prior is not None and prior.status != "open":
            if prior.model_dump(exclude={"note"}) != target.model_dump(exclude={"note"}):
                raise ValueError(f"{did}: a completed physical inventory document is immutable")
            continue
        if prior is None:
            nodes = list(dict.fromkeys((i.location, i.product) for i in target.items))
            working, _ = count_doc(old, nodes, target.date, target.block, target.note, book_basis=target.book_basis)
            made = working.inventory_docs[-1].model_copy(update={"id": did})
            working = working.model_copy(update={"inventory_docs": [*working.inventory_docs[:-1], made]})
            opening_allowance.update(_signature(m) for m in working.movements if m.id not in old_ids
                                     and m.type is MovementType.OPENING)
        else:
            working = old
        if target.counted_on is not None and (prior is None or prior.counted_on != target.counted_on):
            working, _ = capture_count_book(working, did, target.counted_on)
        if target.book_basis == "frozen" or target.counted_on is not None:
            working, _ = enter_counts(working, did, [
                {"location": i.location, "product": i.product, "batch": i.batch, "stock_type": i.stock_type.value,
                 "qty": i.counted} for i in target.items])
        expected = next(d for d in working.inventory_docs if d.id == did)
        frozen = {"status", "posted_doc", "note"}
        if expected.model_dump(exclude=frozen) != target.model_dump(exclude=frozen):
            raise ValueError(f"{did}: physical inventory retains its dates, book policy, block and book quantities")
        if target.status == "posted":
            open_period(target.posting_date)
            result, _ = post_counts(working, did, uncounted_zero=any(i.counted is None for i in target.items))
            done = next(d for d in result.inventory_docs if d.id == did)
            expected_moves = [m for m in result.movements if done.posted_doc and m.doc == done.posted_doc
                              and m.id not in {x.id for x in working.movements}]
            actual_moves = [m for m in additions if target.posted_doc and m.doc == target.posted_doc]
            if (bool(done.posted_doc) != bool(target.posted_doc) or target.posted_doc in old_docs
                    or Counter(map(_signature, expected_moves)) != Counter(map(_signature, actual_moves))):
                raise ValueError(f"{did}: the posted count differences do not match the recorded book and physical counts")
            count_movements.update(m.id for m in actual_moves)
        elif target.status == "cancelled":
            cancel_counts(working, did)
            if target.posted_doc is not None:
                raise ValueError(f"{did}: a cancelled count has no material posting")
        elif target.posted_doc is not None:
            raise ValueError(f"{did}: an open count has no material posting")

    blocks = [d for d in old.inventory_docs if d.status == "open" and d.block
              and targets.get(d.id) is not None and targets[d.id].status != "cancelled"]
    blocks += [d for d in proposed.inventory_docs if d.id not in original and d.status == "open" and d.block]
    for m in additions:
        if m.id in count_movements:
            continue
        if any(any((i.location, i.product) == (m.location, m.product) for i in d.items) for d in blocks):
            signature = _signature(m)
            if m.type is MovementType.OPENING and opening_allowance[signature]:
                opening_allowance[signature] -= 1
                continue
            raise ValueError(f"{m.product} at {m.location} is blocked by physical inventory; post or cancel the count first")

    # A serial can be at only one place/stock type and must be there before issue.
    touched = {(m.product, serial) for m in additions for serial in m.serials}
    for m in additions:
        serialised = any(ds.product_by_id.get(m.product) and ds.product_by_id[m.product].serial_numbers
                         for ds in (old, proposed))
        if (serialised or m.serials) and (abs(abs(m.qty) - len(m.serials)) > 1e-6):
            raise ValueError(f"{m.id}: a serialised movement requires one serial per whole unit")
    slots = defaultdict(int)
    grouped = {}
    for m in sorted(proposed.movements, key=lambda m: m.date):
        if any((m.product, serial) in touched for serial in m.serials):
            key = (m.date, m.doc or m.id, m.id not in old_ids)
            grouped.setdefault(key, []).append(m)
    earliest = min((m.date for m in additions if m.serials), default=None)
    for (day, _document, _new), moves in grouped.items():
        for m in moves:
            direction = 1 if m.signed > 0 else -1
            for serial in m.serials:
                if (m.product, serial) in touched:
                    slots[(m.product, serial, m.location, m.stock_type)] += direction
        if earliest is not None and day >= earliest:
            totals = defaultdict(int)
            for (product, serial, _location, _stock_type), qty in slots.items():
                if qty not in (0, 1):
                    raise ValueError(f"{product}/{serial}: a serial is issued from stock it does not have or received twice")
                totals[(product, serial)] += qty
            if any(qty not in (0, 1) for qty in totals.values()):
                raise ValueError("a serial number cannot be held in two places or stock types at once")
