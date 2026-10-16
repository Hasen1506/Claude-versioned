"""Which field of another system fills which field here (ENTERPRISE_PLAN 3.1).

A scheduled import, or a connector, reads records: the rows of a CSV file (named by its header) or the objects of a
JSON answer. Without a mapping the columns are recognised by their names (:data:`scp.connect.imports.SYNONYMS`). With
one, each field here is filled from a field there that the mapping names:

* ``source`` is a column of the file, or a path in a JSON record (``customer.code``, ``lines.0.sku``);
* ``items`` is the path to the list of records in a JSON answer (``data.items``);
* ``each`` turns a record with a list inside it (an order with its ``line_items``) into one row per element: the
  element is read as ``line.<path>`` and the rest of the record as before;
* ``values`` translates codes (the other system's warehouse ``WH-01`` is the place ``P`` here; ``*`` for any other),
  ``factor`` multiplies a number (dozens to units), ``date_format`` says how dates are written, and ``value`` is used
  when the source is empty (or, with no source, always).

The rows it makes are the rows a recognised file makes, so what follows (an order's lines grouped by its number, a
stock row per stock type) is the same.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, get_args

from pydantic import Field

from ..model import Dataset
from ..model.common import Model

#: the fields of each message a row of a file fills (an order's header fields are repeated on each of its lines)
FIELDS: dict[str, list[str]] = {
    "orders": ["number", "customer", "order_date", "customer_ref", "payment_terms", "product", "qty", "date", "price",
               "cancelled", "note"],
    "stock": ["location", "product", "qty", "batch", "expires_on", "stock_type", "quality", "blocked"],
    "postings": ["ref", "action", "number", "qty", "date", "final", "location", "product", "batch", "expires_on",
                 "supplier_batch", "stock_type", "to_type", "note"],
    # a connector's purchase orders going out (ENTERPRISE_PLAN 3.2): codes there = here, read backwards
    "send:purchase_order": ["product", "supplier", "location"],
    "send:production_order": ["product", "location"],
}
LINE = "line"


class FieldMap(Model):
    source: str = Field("", max_length=200, description="The column (CSV) or the path in a record (JSON: "
                                                        "customer.code); with `each`, line.<path> is the element")
    value: str | float | bool | None = Field(None, description="Used when the source is empty or missing; with no "
                                                               "source, always")
    values: dict[str, str] = Field(default_factory=dict, max_length=500,
                                   description="Codes translated (WH-01 → P); * for any other code")
    factor: float | None = Field(None, description="A number is multiplied by this (12: dozens to units)")
    date_format: str = Field("", max_length=40, description="How dates are written, as strftime does (%d-%b-%Y); "
                                                            "empty: recognised")


class Mapping(Model):
    items: str = Field("", max_length=200, description="JSON: the path to the list of records (data.items); empty: "
                                                       "the file itself, or its list named after the kind")
    each: str = Field("", max_length=200, description="The path in each record to a list it holds (line_items): "
                                                      "one row per element, read as line.<path>")
    fields: dict[str, FieldMap] = Field(default_factory=dict, max_length=80)


def fields_of(kind: str) -> list[str]:
    """The fields a row of ``kind`` can fill: a list of master data's are its records' fields."""
    if kind in FIELDS:
        return FIELDS[kind]
    if kind.startswith("records:"):
        f = Dataset.model_fields.get(kind.split(":", 1)[1])
        if f is not None and get_args(f.annotation):
            return list(get_args(f.annotation)[0].model_fields)
    return []


def check(kind: str, m: Mapping) -> None:
    """Refuse a mapping that fills a field the kind does not have (ValueError, with the fields it has)."""
    known = fields_of(kind)
    for target in m.fields:
        if target.split(".", 1)[0] not in known:
            raise ValueError(f"{target!r} is not a field of {kind.replace('records:', '')}: it is one of "
                             f"{', '.join(known)}")
    for target, f in m.fields.items():
        if f.date_format:   # a date written this way is read back as itself: day, month and year
            day = dt.date(2026, 1, 5)
            try:
                ok = dt.datetime.strptime(day.strftime(f.date_format), f.date_format).date() == day
            except ValueError:
                ok = False
            if not ok:
                raise ValueError(f"{target}: the date format {f.date_format!r} does not give a day, month and year "
                                 "(05-Jan-2026 is %d-%b-%Y)")


# ------------------------------------------------------------------------------------------------ reading
def dig(obj: Any, path: str) -> Any:
    """The value at ``path`` (``a.b.0.c``) in a record, or None."""
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, dict):
            if part in obj:
                obj = obj[part]
            else:
                return None
        elif isinstance(obj, list) and re.fullmatch(r"-?\d+", part):
            i = int(part)
            if -len(obj) <= i < len(obj):
                obj = obj[i]
            else:
                return None
        else:
            return None
    return obj


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _pick(rec: dict[str, Any], source: str) -> Any:
    """A column by its header as written, else by the path, else by its name in any case and spacing."""
    if source in rec:
        return rec[source]
    v = dig(rec, source)
    if v is not None:
        return v
    n = _norm(source)
    for k, v in rec.items():
        if _norm(str(k)) == n:
            return v
    return None


def csv_records(text: str) -> list[dict[str, str]]:
    """The rows of a CSV file, each named by the header (comma, semicolon, tab or bar)."""
    from .imports import read_grid
    grid = read_grid(text)
    if not grid:
        return []
    head = [h.strip() for h in grid[0]]
    return [{h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(head) if h} for row in grid[1:]]


def json_items(data: Any, path: str, kind: str) -> list[dict[str, Any]]:
    """The records of a JSON answer: at ``path``, else the answer itself when it is a list, else its list named
    after the kind (``orders``, ``stock``, ``postings``, ``records``)."""
    if path:
        items = dig(data, path)
        where = f"at {path!r}"
    elif isinstance(data, list):
        items, where = data, "under 'records'"
    else:
        key = {"orders": "orders", "stock": "stock", "postings": "postings"}.get(kind, "records")
        items, where = (data.get(key, []) if isinstance(data, dict) else data), f"under {key!r}"
    if items is None:
        return []
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        if path:
            raise ValueError(f"the answer has no list of records {where} (expected a JSON list of objects)")
        raise ValueError(f"the file is not a list of records (expected a JSON list of objects, or an object with "
                         f"{where.split()[-1]}: [...])")
    return items


def records(kind: str, fmt: str, raw: bytes, m: Mapping | None) -> list[dict[str, Any]]:
    """What a file or answer holds, record by record, before any mapping."""
    text = raw.decode("utf-8-sig", errors="replace")
    if fmt == "json":
        return json_items(json.loads(text), m.items if m else "", kind)
    return csv_records(text)


def columns(recs: list[dict[str, Any]], each: str = "", limit: int = 80) -> list[str]:
    """The columns (or paths) the first records have: what a mapping can name."""
    out: list[str] = []

    def walk(obj: Any, prefix: str, depth: int) -> None:
        if len(out) >= limit:
            return
        if isinstance(obj, dict) and depth < 4:
            for k, v in obj.items():
                walk(v, f"{prefix}{k}.", depth + 1)
        elif isinstance(obj, list) and obj and depth < 4:
            walk(obj[0], f"{prefix}0.", depth + 1)
        else:
            name = prefix.rstrip(".")
            if name and name not in out:
                out.append(name)
    for r in recs[:5]:
        walk(r, "", 0)
        if each:
            for el in (dig(r, each) or [])[:3]:
                walk(el, f"{LINE}.", 1)
    return out


# ------------------------------------------------------------------------------------------------ mapping
def _value(target: str, f: FieldMap, v: Any, day_first: bool, kind: str) -> Any:
    from .imports import convert
    if isinstance(v, str):
        v = v.strip()
    if v is None or v == "":
        v = f.value
        if v is None or v == "":
            return None
    if f.values:
        key = str(v).strip()
        if key in f.values:
            v = f.values[key]
        elif "*" in f.values:
            v = f.values["*"]
    field = target.split(".")[-1]
    if f.date_format and isinstance(v, str):
        try:
            v = dt.datetime.strptime(v, f.date_format).date().isoformat()
        except ValueError:
            pass                                    # the row is refused with what the date was
    elif isinstance(v, str):
        v = convert(field, v, day_first) if kind in FIELDS else _record_value(v, day_first)
    if f.factor is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
        v = v * f.factor
    return v


def _record_value(v: str, day_first: bool) -> Any:
    from .imports import parse_date
    if re.search(r"\d[./-]\d|^\d{8}$", v) and not re.fullmatch(r"-?[\d.,]+", v):
        return parse_date(v, day_first) or v
    return v


def apply(kind: str, recs: list[dict[str, Any]], m: Mapping, day_first: bool = True) -> list[dict[str, Any]]:
    """Rows of ``kind``'s fields, one per record (per element of its ``each`` list)."""
    rows: list[dict[str, Any]] = []
    for rec in recs:
        ctxs = [rec]
        if m.each:
            inner = dig(rec, m.each)
            els = inner if isinstance(inner, list) else []
            ctxs = [{**rec, LINE: el} for el in els] or [rec]
        for ctx in ctxs:
            row: dict[str, Any] = {}
            for target, f in m.fields.items():
                v = _value(target, f, _pick(ctx, f.source) if f.source else None, day_first, kind)
                if v is None:
                    continue
                node = row
                *path, last = target.split(".") if kind.startswith("records:") else [target]
                for p in path:
                    node = node.setdefault(p, {})
                node[last] = v
            rows.append(row)
    return rows


def recode(kind: str, rows: list[dict[str, Any]], m: Mapping | None, day_first: bool = True) -> list[dict[str, Any]]:
    """A connector's rows (already named as the fields here) with the mapping's translations: a field the mapping
    names is filled from its source (empty: the field of the same name), the other fields stay as they came."""
    if m is None or not m.fields:
        return rows
    out = []
    for row in rows:
        new = dict(row)
        for target, f in m.fields.items():
            v = _value(target, f, _pick(row, f.source or target), day_first, kind)
            if v is None:
                new.pop(target, None)
            else:
                new[target] = v
        out.append(new)
    return out


def inverse(m: Mapping | None, target: str) -> dict[str, str]:
    """A field's code translation read backwards (here → there), for what goes out: the first code there that
    becomes a code here names it (``*`` is no code)."""
    out: dict[str, str] = {}
    f = m.fields.get(target) if m is not None else None
    for there, here in (f.values.items() if f is not None else []):
        if there != "*" and here not in out:
            out[here] = there
    return out


def sample(raw: bytes, limit: int = 2000) -> str:
    """The start of what was read, kept with its message so a refused line can be looked at."""
    text = raw[: limit * 4].decode("utf-8-sig", errors="replace")
    return text[:limit] + ("…" if len(text) > limit or len(raw) > limit * 4 else "")


__all__ = ["FIELDS", "FieldMap", "Mapping", "apply", "check", "columns", "csv_records", "dig", "fields_of",
           "inverse", "json_items", "recode", "records", "sample"]
