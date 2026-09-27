"""Merge two people's changes to a company (Phase I): the working copy (*mine*) and the latest save (*theirs*), both
made from the same earlier save (*base*).

Record by record, keyed as the dataset diff keys them: what only one side changed is taken from that side, what
both changed the same way is kept once, and what both changed differently keeps the latest save's version and is
reported. A record only one side removed stays removed unless the other side changed it. Settings are merged field
by field the same way.

Two people taking an order (or a purchase order, a goods movement, …) at the same time give it the same next
number. Such a record *mine* added under a number *theirs* also added is renumbered to the next free number of its
series, and the records *mine* added that point at it (its promises, its deliveries) follow it.
"""
from __future__ import annotations

import re
from typing import Any

from ..model.common import Out
from ..versions.diff import KEYS, SINGLE, _key

# fields of a record that point at another record by its number
REF_FIELDS = ("order", "reference", "po", "purchase_order", "source_order")
NUMBERED = re.compile(r"^(.*?)(\d+)$")


class MergeReport(Out):
    mine: int                 # records (or settings) taken from the working copy
    theirs: int               # taken from the latest save
    conflicts: list[str]      # changed on both sides differently: the latest save's version was kept
    renumbered: list[str]     # "SO-00004 → SO-00005"
    summary: str


def _keys_of(name: str) -> tuple[str, ...]:
    return KEYS.get(name, ("id",))


def _index(rows: list, fields: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for i, r in enumerate(rows or []):
        out.setdefault(_key(r, fields, i) if isinstance(r, dict) else f"#{i}", r)
    return out


def _next_free(old: str, taken: set[str]) -> str:
    m = NUMBERED.match(old)
    if not m:
        n = 2
        while f"{old}-{n}" in taken:
            n += 1
        return f"{old}-{n}"
    prefix, digits = m.group(1), m.group(2)
    top = max((int(x.group(2)) for t in taken if (x := NUMBERED.match(t)) and x.group(1) == prefix), default=int(digits))
    return f"{prefix}{top + 1:0{len(digits)}d}"


def _renumber(base: dict, mine: dict, theirs: dict, rep: MergeReport) -> dict:
    """The working copy with each record it added under a number the latest save also added (differently) moved to
    the next free number, and the records it added that point at one following it."""
    renames: dict[str, str] = {}
    for name in set(mine) & set(theirs):
        m, t = mine[name], theirs[name]
        if name in SINGLE or not isinstance(m, list) or not isinstance(t, list) or "id" not in _keys_of(name):
            continue
        ib = {r.get("id") for r in base.get(name) or [] if isinstance(r, dict)}
        tb = {r.get("id"): r for r in t if isinstance(r, dict)}
        taken = {str(x) for x in tb} | {str(r.get("id")) for r in m if isinstance(r, dict)}
        for r in m:
            i = r.get("id") if isinstance(r, dict) else None
            if isinstance(i, str) and i not in ib and i in tb and tb[i] != r and i not in renames:
                new = _next_free(i, taken | set(renames.values()))
                renames[i] = new
                taken.add(new)
                rep.renumbered.append(f"{i} → {new}")
    if not renames:
        return mine
    out: dict[str, Any] = {}
    for name, rows in mine.items():
        if name in SINGLE or not isinstance(rows, list):
            out[name] = rows
            continue
        fields = _keys_of(name)
        old = _index(base.get(name) or [], fields)
        new_rows = []
        for i, r in enumerate(rows):
            if isinstance(r, dict) and _key(r, fields, i) not in old:        # added here: follows the renumbering
                r = dict(r)
                if "id" in fields and r.get("id") in renames:
                    r["id"] = renames[r["id"]]
                for f in REF_FIELDS:
                    if isinstance(r.get(f), str) and r[f] in renames:
                        r[f] = renames[r[f]]
            new_rows.append(r)
        out[name] = new_rows
    return out


def merge(base: dict, mine: dict, theirs: dict) -> tuple[dict, MergeReport]:
    rep = MergeReport(mine=0, theirs=0, conflicts=[], renumbered=[], summary="")
    mine = _renumber(base, mine, theirs, rep)
    out: dict[str, Any] = {}
    for name in [*theirs, *(k for k in mine if k not in theirs)]:
        b, m, t = base.get(name, _MISSING), mine.get(name, _MISSING), theirs.get(name, _MISSING)
        present = [x for x in (b, m, t) if x is not _MISSING and x is not None]
        if present and all(isinstance(x, list) for x in present) and name not in SINGLE:
            out[name] = _merge_list(name, _list(b), _list(m), _list(t), rep)
        elif present and all(isinstance(x, dict) for x in present):
            out[name] = _merge_dict(name, _dict(b), _dict(m), _dict(t), rep)
        else:
            v = _pick(name, b, m, t, rep)
            if v is not _MISSING:
                out[name] = v
    parts = []
    if rep.mine:
        parts.append(f"{rep.mine} of your changes")
    if rep.theirs:
        parts.append(f"{rep.theirs} of theirs")
    rep.summary = ("kept " + " and ".join(parts) if parts else "nothing to merge") + (
        f"; {len(rep.conflicts)} changed on both sides (theirs kept)" if rep.conflicts else "") + (
        "; renumbered " + ", ".join(rep.renumbered) if rep.renumbered else "")
    return out, rep


_MISSING: Any = object()


def _list(x: Any) -> list:
    return x if isinstance(x, list) else []


def _dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _pick(what: str, b: Any, m: Any, t: Any, rep: MergeReport) -> Any:
    if m == t:
        return t
    if m == b:
        rep.theirs += 1
        return t
    if t == b:
        rep.mine += 1
        return m
    rep.conflicts.append(what)
    return t


def _merge_dict(name: str, b: dict, m: dict, t: dict, rep: MergeReport) -> dict:
    out: dict[str, Any] = {}
    for k in [*t, *(k for k in m if k not in t)]:
        v = _pick(f"{name}.{k}", b.get(k, _MISSING), m.get(k, _MISSING), t.get(k, _MISSING), rep)
        if v is not _MISSING:
            out[k] = v
    return out


def _merge_list(name: str, b: list, m: list, t: list, rep: MergeReport) -> list:
    fields = _keys_of(name)
    ib, im, it = _index(b, fields), _index(m, fields), _index(t, fields)
    out: list = []
    for k, tv in it.items():                                   # the latest save's records, in its order
        if k in ib and k not in im:
            if tv == ib[k]:
                rep.mine += 1                                  # removed here, left alone there
            else:
                rep.conflicts.append(f"{name} {k} (removed here, changed there: kept)")
                out.append(tv)
        elif k in im:
            out.append(_pick(f"{name} {k}", ib.get(k, _MISSING), im[k], tv, rep))
        else:
            out.append(tv)
    for k, mv in im.items():                                   # records only the working copy has
        if k in it:
            continue
        if k in ib:
            if mv != ib[k]:
                rep.conflicts.append(f"{name} {k} (changed here, removed there: kept)")
                out.append(mv)
            else:
                rep.theirs += 1                                # removed there
            continue
        rep.mine += 1
        out.append(mv)
    return out
