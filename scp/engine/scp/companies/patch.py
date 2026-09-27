"""What changed between two saves of a company, as a small document (Phase L): the browser sends it instead of the
whole company (N64), and the server keeps each save as one against the save before it, so every save can be opened
and put back (R19) at a fraction of a whole copy's size.

A patch names, per list of records, the records added or changed (``upsert``, whole records) and the ones removed
(``remove``, by the fields that identify a record, as the dataset diff keys them). A list whose records cannot be
told apart that way (two records with the same key, a record with none, or a new order of the records) is sent
whole (``set``), as is every setting and anything that is not a list of records. ``sizes`` holds each list's length
after the change, so a patch applied to a different company than it was made from is caught instead of saved.

``web/src/lib/patch.ts`` makes the same patches in the browser; the keys there must stay those of
:data:`scp.versions.diff.KEYS` (a test compares them).
"""
from __future__ import annotations

from typing import Any

from ..versions.diff import KEYS, SINGLE


class PatchError(Exception):
    """The patch does not fit the company it was applied to."""


def keys_of(name: str) -> tuple[str, ...]:
    return KEYS.get(name, ("id",))


def _record_keys(rows: list, fields: tuple[str, ...]) -> list[tuple] | None:
    """Each record's key, in order; None when the list cannot be patched record by record."""
    out: list[tuple] = []
    for r in rows:
        if not isinstance(r, dict):
            return None
        k = tuple(r.get(f) for f in fields)
        if all(v is None for v in k):
            return None
        out.append(k)
    return out if len(set(map(_hashable, out))) == len(out) else None


def _hashable(k: tuple) -> tuple:
    return tuple(v if isinstance(v, (str, int, float, bool)) or v is None else repr(v) for v in k)


def make_patch(before: dict, after: dict) -> dict:
    """The patch that turns ``before`` into ``after`` (``apply_patch(before, make_patch(before, after)) == after``)."""
    lists: dict[str, dict] = {}
    sets: dict[str, Any] = {}
    drop: list[str] = []
    sizes: dict[str, int] = {}
    for name in [*after, *(k for k in before if k not in after)]:
        if name not in after:
            drop.append(name)
            continue
        a, b = before.get(name, _MISSING), after[name]
        if isinstance(b, list):
            sizes[name] = len(b)
        if a == b:
            continue
        ch = _list_change(name, a, b) if isinstance(a, list) and isinstance(b, list) and name not in SINGLE else None
        if ch is None:
            sets[name] = b
        else:
            lists[name] = ch
    out: dict[str, Any] = {"v": 1}
    if lists:
        out["lists"] = lists
    if sets:
        out["set"] = sets
    if drop:
        out["drop"] = drop
    out["sizes"] = sizes
    return out


def _list_change(name: str, a: list, b: list) -> dict | None:
    fields = keys_of(name)
    ka, kb = _record_keys(a, fields), _record_keys(b, fields)
    if ka is None or kb is None:
        return None
    ia = {_hashable(k): r for k, r in zip(ka, a, strict=True)}
    ib = {_hashable(k) for k in kb}
    # the records both have must keep their order, and new ones come last: applying appends them
    kept_a = [_hashable(k) for k in ka if _hashable(k) in ib]
    kept_b = [_hashable(k) for k in kb if _hashable(k) in ia]
    n_new = len(kb) - len(kept_b)
    if kept_a != kept_b or any(_hashable(k) in ia for k in kb[len(kb) - n_new:]):
        return None
    upsert = [r for k, r in zip(kb, b, strict=True) if ia.get(_hashable(k), _MISSING) != r]
    remove = [list(k) for k in ka if _hashable(k) not in ib]
    ch: dict[str, Any] = {}
    if upsert:
        ch["upsert"] = upsert
    if remove:
        ch["remove"] = remove
    return ch


def apply_patch(doc: dict, patch: dict) -> dict:
    """``doc`` with ``patch`` applied (a new document; ``doc`` is not changed). :class:`PatchError` when it does
    not fit."""
    if not isinstance(patch, dict) or patch.get("v") != 1:
        raise PatchError("not a patch this server understands")
    out = dict(doc)
    for name in patch.get("drop") or []:
        out.pop(name, None)
    for name, v in (patch.get("set") or {}).items():
        out[name] = v
    for name, ch in (patch.get("lists") or {}).items():
        rows = out.get(name) or []
        if not isinstance(rows, list):
            raise PatchError(f"{name} is not a list here")
        fields = keys_of(name)
        keys = _record_keys(rows, fields)
        if keys is None:
            raise PatchError(f"the records of {name} cannot be told apart here")
        pos = {_hashable(k): i for i, k in enumerate(keys)}
        new = list(rows)
        gone = set()
        for k in ch.get("remove") or []:
            h = _hashable(tuple(k))
            if h not in pos:
                raise PatchError(f"{name}: a removed record is not here")
            gone.add(pos[h])
        for r in ch.get("upsert") or []:
            if not isinstance(r, dict):
                raise PatchError(f"{name}: not a record")
            h = _hashable(tuple(r.get(f) for f in fields))
            if h in pos:
                new[pos[h]] = r
            else:
                pos[h] = len(new)
                new.append(r)
        out[name] = [r for i, r in enumerate(new) if i not in gone]
    for name, n in (patch.get("sizes") or {}).items():
        v = out.get(name)
        if not isinstance(v, list) or len(v) != n:
            raise PatchError(f"{name} does not add up after the change ({len(v) if isinstance(v, list) else 0} "
                             f"records, the sender has {n})")
    return out


_MISSING: Any = object()
