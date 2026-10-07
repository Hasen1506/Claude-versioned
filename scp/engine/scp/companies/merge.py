"""Merge two people's changes to a company (Phase I): the working copy (*mine*) and the latest save (*theirs*), both
made from the same earlier save (*base*).

Record by record, keyed as the dataset diff keys them: what only one side changed is taken from that side, what
both changed the same way is kept once, and what both changed differently keeps the latest save's version and is
reported, with both versions side by side (a *clash*), so the person can choose per record (``choose``: a clash's id
→ ``"mine"``) and merge again (N65). A record only one side removed stays removed unless the other side changed it.
Settings are merged field by field the same way.

Two people taking an order (or a purchase order, a goods movement, …) at the same time give it the same next
number. Such a record *mine* added under a number *theirs* also added is renumbered to the next free number of its
series, and the records *mine* added that point at it (its promises, its deliveries) follow it.
"""
from __future__ import annotations

import re
import json
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from ..model.common import Out
from ..model import Dataset
from ..versions.diff import KEYS, SINGLE, _flat, _key

# fields of a record that point at another record by its number
REF_FIELDS = ("order", "reference", "po", "purchase_order", "source_order")
NUMBERED = re.compile(r"^(.*?)(\d+)$")


class FieldClash(Out):
    path: str                 # "qty", "lines[0].qty"; "" for the whole record or value
    base: Any = None          # before either change
    mine: Any = None
    theirs: Any = None


class Clash(Out):
    id: str                   # "products B", "settings.company_name": what ``choose`` names
    list: str                 # the dataset's list or settings the record is in
    record: str               # the record's key, "B", or the setting's name
    mine_removed: bool = False
    theirs_removed: bool = False
    fields: list[FieldClash]  # where the two versions differ
    kept: str                 # "theirs" | "mine": which one this merge kept
    group: str = ""           # records that belong together (an order and its promises: "SO-00012"): chosen as one


class MergeReport(Out):
    mine: int                 # records (or settings) taken from the working copy
    theirs: int               # taken from the latest save
    conflicts: list[str]      # changed on both sides differently: the version kept is in ``clashes``
    renumbered: list[str]     # "SO-00004 → SO-00005"
    summary: str
    clashes: list[Clash] = []


def _keys_of(name: str) -> tuple[str, ...]:
    return KEYS.get(name, ("id",))


def _index(rows: list, fields: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    groups: dict[str, list] = {}
    for i, r in enumerate(rows or []):
        key = _key(r, fields, i) if isinstance(r, dict) else f"#{i}"
        groups.setdefault(key, []).append(r)
    for key, group in groups.items():
        values = sorted(group, key=lambda r: json.dumps(r, sort_keys=True)) if len(group) > 1 else group
        for i, r in enumerate(values):
            out[key if i == 0 else f"{key} | observation {i + 1}"] = r
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
    renames: dict[tuple[str, str], str] = {}
    for name in set(mine) & set(theirs):
        m, t = mine[name], theirs[name]
        if name in SINGLE or not isinstance(m, list) or not isinstance(t, list) or "id" not in _keys_of(name):
            continue
        ib = {r.get("id") for r in base.get(name) or [] if isinstance(r, dict)}
        tb = {r.get("id"): r for r in t if isinstance(r, dict)}
        taken = {str(x) for x in tb} | {str(r.get("id")) for r in m if isinstance(r, dict)}
        for r in m:
            i = r.get("id") if isinstance(r, dict) else None
            if isinstance(i, str) and i not in ib and i in tb and tb[i] != r and (name, i) not in renames:
                new = _next_free(i, taken | set(renames.values()))
                renames[(name, i)] = new
                taken.add(new)
                rep.renumbered.append(f"{i} → {new}")
    # CV-H09: a document's lines are numbered after it ("SO-00002/10" belongs to "SO-00002"): when the header moves,
    # every line the working copy added under it moves with it ("SO-00003/10"), never on a number of its own
    roots = {old: new for (_, old), new in renames.items() if "/" not in old}
    if roots:
        for name, rows in mine.items():
            if name in SINGLE or not isinstance(rows, list) or "id" not in _keys_of(name):
                continue
            ib = {r.get("id") for r in base.get(name) or [] if isinstance(r, dict)}
            for r in rows:
                i = r.get("id") if isinstance(r, dict) else None
                if not isinstance(i, str) or "/" not in i or i in ib:
                    continue
                root, rest = i.split("/", 1)
                if root in roots:
                    new = f"{roots[root]}/{rest}"
                    was = renames.get((name, i))
                    if was is not None and f"{i} → {was}" in rep.renumbered:
                        rep.renumbered.remove(f"{i} → {was}")
                    renames[(name, i)] = new
                    rep.renumbered.append(f"{i} → {new}")
    if not renames:
        return mine
    schema = _dataset_schema()
    domains = {"product": "products", "location": "locations", "resource": "resources", "calendar": "calendars"}

    def follow(value: Any, spec: dict, owner: str) -> Any:
        if "$ref" in spec:
            spec = schema["$defs"][spec["$ref"].rsplit("/", 1)[-1]]
        if "anyOf" in spec:
            spec = {**next((s for s in spec["anyOf"] if s.get("type") != "null"), {}),
                    **({"x-ref": spec["x-ref"]} if "x-ref" in spec else {})}
            return follow(value, spec, owner)
        domain = domains.get(spec.get("x-ref"))
        if domain and isinstance(value, str):
            return renames.get((domain, value), value)
        if isinstance(value, list):
            return [follow(v, spec.get("items", {}), owner) for v in value]
        if not isinstance(value, dict):
            return value
        out = {k: follow(v, spec.get("properties", {}).get(k, {}), owner) for k, v in value.items()}
        if isinstance(out.get("id"), str):
            out["id"] = renames.get((owner, out["id"]), out["id"])
        for f in REF_FIELDS:
            if not isinstance(out.get(f), str):
                continue
            candidates = ["demand", "sales_orders"] if f == "order" else ["purchase_orders"] if f in ("po", "purchase_order") else ["receipts", "demand"]
            for target in candidates:
                out[f] = renames.get((target, out[f]), out[f])
        if isinstance(out.get("source"), str):
            target = {"production": "production_sources", "purchase": "purchasing_sources", "transfer": "lanes"}.get(out.get("kind"))
            if target:
                out["source"] = renames.get((target, out["source"]), out["source"])
        return out

    out: dict[str, Any] = {}
    for name, rows in mine.items():
        if name in SINGLE or not isinstance(rows, list):
            out[name] = rows
            continue
        out[name] = follow(rows, schema.get("properties", {}).get(name, {}), name)
    return out


@lru_cache(maxsize=1)
def _dataset_schema() -> dict:
    return Dataset.model_json_schema()


def merge(base: dict, mine: dict, theirs: dict, choose: dict[str, str] | None = None,
          prefer_mine: bool = False) -> tuple[dict, MergeReport]:
    """``choose``: per clash id, ``"mine"`` keeps the working copy's version (else the latest save's is kept).
    ``prefer_mine``: every clash keeps the working copy's version (both saves are the same person's)."""
    rep = MergeReport(mine=0, theirs=0, conflicts=[], renumbered=[], summary="")
    _chosen.set((choose or {}, prefer_mine))
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
            v = _pick(name, b, m, t, rep, name, "")
            if v is not _MISSING:
                out[name] = v
    parts = []
    if rep.mine:
        parts.append(f"{rep.mine} of your changes")
    if rep.theirs:
        parts.append(f"{rep.theirs} of theirs")
    n_mine = sum(c.kept == "mine" for c in rep.clashes)
    rep.summary = ("kept " + " and ".join(parts) if parts else "nothing to merge") + (
        f"; {len(rep.conflicts)} changed on both sides ("
        + ("theirs kept" if not n_mine else "yours kept" if n_mine == len(rep.conflicts)
           else f"yours kept for {n_mine}, theirs for {len(rep.conflicts) - n_mine}") + ")"
        if rep.conflicts else "") + (
        "; renumbered " + ", ".join(rep.renumbered) if rep.renumbered else "")
    return out, rep


_MISSING: Any = object()
_chosen: ContextVar[tuple[dict[str, str], bool]] = ContextVar("chosen", default=({}, False))


def _choice(cid: str) -> str | None:
    """Whose version the person chose for this clash (every clash is theirs to decide when both saves were theirs)."""
    choose, prefer_mine = _chosen.get()
    return "mine" if prefer_mine else choose.get(cid)


def _clash(cid: str, where: str, record: str, b: Any, m: Any, t: Any, rep: MergeReport, default: str = "theirs") -> Any:
    """Both sides changed this differently: note it, with both versions, and keep the chosen one (``default`` when
    nothing was chosen)."""
    keep_mine = (_choice(cid) or default) == "mine"
    fm = _flat(m, "") if isinstance(m, dict) else {"": None if m is _MISSING else m}
    ft = _flat(t, "") if isinstance(t, dict) else {"": None if t is _MISSING else t}
    fb = (_flat(b, "") if isinstance(b, dict) else {"": b}) if b is not _MISSING else {}
    paths = sorted(p for p in set(fm) | set(ft) if fm.get(p) != ft.get(p))
    if m is _MISSING or t is _MISSING:
        paths = [p for p in paths if p]
    rec = next((x for x in (m, t, b) if isinstance(x, dict)), {})
    group = str(rec["order"]) if rec.get("order") else str(rec["id"]) if where == "demand" and rec.get("id") else cid
    rep.clashes.append(Clash(id=cid, list=where, record=record, group=group, mine_removed=m is _MISSING,
                             theirs_removed=t is _MISSING, kept="mine" if keep_mine else "theirs",
                             fields=[FieldClash(path=p.lstrip("."), base=fb.get(p), mine=fm.get(p), theirs=ft.get(p))
                                     for p in paths[:40]]))
    return m if keep_mine else t


def _list(x: Any) -> list:
    return x if isinstance(x, list) else []


def _dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _pick(what: str, b: Any, m: Any, t: Any, rep: MergeReport, where: str = "", record: str = "") -> Any:
    if m == t:
        return t
    if m == b:
        rep.theirs += 1
        return t
    if t == b:
        rep.mine += 1
        return m
    rep.conflicts.append(what)
    return _clash(what, where or what, record, b, m, t, rep)


def _merge_dict(name: str, b: dict, m: dict, t: dict, rep: MergeReport) -> dict:
    out: dict[str, Any] = {}
    for k in [*t, *(k for k in m if k not in t)]:
        v = _pick(f"{name}.{k}", b.get(k, _MISSING), m.get(k, _MISSING), t.get(k, _MISSING), rep, name, k)
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
                cid = f"{name} {k}"
                if _clash(cid, name, k, ib[k], _MISSING, tv, rep) is not _MISSING:
                    out.append(tv)
                rep.conflicts.append(f"{cid} (removed here, changed there: "
                                     + ("kept)" if rep.clashes[-1].kept == "theirs" else "removed)"))
        elif k in im:
            out.append(_pick(f"{name} {k}", ib.get(k, _MISSING), im[k], tv, rep, name, k))
        else:
            out.append(tv)
    for k, mv in im.items():                                   # records only the working copy has
        if k in it:
            continue
        if k in ib:
            if mv != ib[k]:
                cid = f"{name} {k}"
                if _clash(cid, name, k, ib[k], mv, _MISSING, rep, default="mine") is not _MISSING:
                    out.append(mv)
                rep.conflicts.append(f"{cid} (changed here, removed there: "
                                     + ("kept)" if rep.clashes[-1].kept == "mine" else "removed)"))
            else:
                rep.theirs += 1                                # removed there
            continue
        rep.mine += 1
        out.append(mv)
    return out
