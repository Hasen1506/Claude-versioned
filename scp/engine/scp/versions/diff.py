"""Dataset diff: what changed between two planning datasets, object by object and field by field.

Every collection is keyed by its natural identity (an id, or the fields that make a row unique), so a
re-ordered list is not a change; singletons (settings, forecasting, …) are compared as one object."""
from __future__ import annotations

from typing import Any

from ..model import Dataset
from ..model.common import Out

KEYS: dict[str, tuple[str, ...]] = {
    "calendars": ("id",), "locations": ("id",), "products": ("id",), "resources": ("id",),
    "production_sources": ("id",), "purchasing_sources": ("id",), "lanes": ("id",), "receipts": ("id",),
    "events": ("id",), "allocations": ("id",), "movements": ("id",),
    "location_products": ("location", "product"), "npi": ("location", "product"),
    "history": ("location", "product", "date"), "overrides": ("location", "product", "date"),
    "demand": ("id", "location", "product", "date", "kind"), "confirmations": ("order", "ship_from", "ship_date"),
    "changeovers": ("resource", "from_group", "to_group"), "closed_orders": ("kind", "id"),
    "accuracy": ("location", "product", "start"),
}
SINGLE = ("settings", "forecasting", "inventory", "sop", "scheduling", "promising", "execution")
MAX_FIELDS = 12


class FieldChange(Out):
    path: str
    a: Any = None
    b: Any = None


class ItemChange(Out):
    key: str
    change: str                  # added | removed | changed
    fields: list[FieldChange]    # for "changed" (first MAX_FIELDS)
    more: int = 0                # further changed fields not listed


class CollectionDiff(Out):
    collection: str
    added: int
    removed: int
    changed: int
    items: list[ItemChange]      # first 200


class DatasetDiff(Out):
    identical: bool
    collections: list[CollectionDiff]
    changes: int


def _flat(v: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        for k, x in v.items():
            out.update(_flat(x, f"{prefix}.{k}" if prefix else k))
        return out or {prefix: {}}
    if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
        out = {}
        for i, x in enumerate(v):
            out.update(_flat(x, f"{prefix}[{i}]"))
        return out
    return {prefix: v}


def _fields(a: dict, b: dict) -> tuple[list[FieldChange], int]:
    fa, fb = _flat(a), _flat(b)
    diffs = [FieldChange(path=p, a=fa.get(p), b=fb.get(p)) for p in sorted(set(fa) | set(fb)) if fa.get(p) != fb.get(p)]
    return diffs[:MAX_FIELDS], max(0, len(diffs) - MAX_FIELDS)


def _key(row: dict, fields: tuple[str, ...], i: int) -> str:
    vals = [row.get(f) for f in fields]
    if all(v is None for v in vals):
        return f"#{i}"
    return " | ".join("" if v is None else str(v) for v in vals)


def diff(a: Dataset, b: Dataset) -> DatasetDiff:
    da, db = a.model_dump(mode="json"), b.model_dump(mode="json")
    out: list[CollectionDiff] = []
    for name in SINGLE:
        fs, more = _fields(da.get(name) or {}, db.get(name) or {})
        if fs:
            out.append(CollectionDiff(collection=name, added=0, removed=0, changed=1,
                                      items=[ItemChange(key=name, change="changed", fields=fs, more=more)]))
    for name, fields in KEYS.items():
        ra = {}
        for i, r in enumerate(da.get(name) or []):
            ra.setdefault(_key(r, fields, i), r)
        rb = {}
        for i, r in enumerate(db.get(name) or []):
            rb.setdefault(_key(r, fields, i), r)
        items: list[ItemChange] = []
        added = [k for k in rb if k not in ra]
        removed = [k for k in ra if k not in rb]
        changed = [k for k in ra if k in rb and ra[k] != rb[k]]
        for k in added:
            items.append(ItemChange(key=k, change="added", fields=[]))
        for k in removed:
            items.append(ItemChange(key=k, change="removed", fields=[]))
        for k in changed:
            fs, more = _fields(ra[k], rb[k])
            items.append(ItemChange(key=k, change="changed", fields=fs, more=more))
        if items:
            out.append(CollectionDiff(collection=name, added=len(added), removed=len(removed), changed=len(changed),
                                      items=items[:200]))
    n = sum(c.added + c.removed + c.changed for c in out)
    return DatasetDiff(identical=n == 0, collections=out, changes=n)
