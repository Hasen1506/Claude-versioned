"""Unfinished records never lock the whole dataset.

A planner builds a company one record at a time, and a record is often half-filled for a while: a lane
without a transport mode, a demand row without a location. The strict model rejects such a record, and
before this module one rejected record made the whole dataset unreadable: no data check, no map, no plan.

:func:`lenient` parses a raw dataset and sets aside each record that cannot be planned yet, with the
reason in plain words, so everything else keeps working. A record is set aside when

* it does not fit the schema (a missing mode, a negative quantity, a malformed date), or
* a reference in it is left empty (no location, product or resource chosen yet), or points at a record that was
  itself set aside.

A reference to something that does not exist at all, or to the wrong kind of place, is not "unfinished": it is a
real inconsistency, and stays an error in the readiness gate.

Only records in the transactional and sourcing collections are set aside. Locations, products and
calendars are the things everything else points at: leaving one out would silently drop every record that
uses it, so a broken one still stops planning, with a plain message on the field to fix. Settings too.

Setting aside cascades: a production source that uses a resource which was itself set aside is set aside
in the next round, with that as its reason.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError

from ..model import Dataset

# collection → the object type the readiness gate and the web client use for it
COLLECTION_TYPES: dict[str, str] = {
    "location_products": "location_product", "resources": "resource", "production_sources": "production_source",
    "purchasing_sources": "purchasing_source", "lanes": "lane", "demand": "demand", "receipts": "receipt",
    "history": "history", "events": "event", "npi": "npi", "overrides": "override", "allocations": "allocation",
    "confirmations": "confirmation", "changeovers": "changeover", "movements": "movement",
    "closed_orders": "closed_order", "accuracy": "accuracy", "rolled_weeks": "rolled_week",
    "stock_targets": "stock_target",
}
_TYPE_COLLECTION = {v: k for k, v in COLLECTION_TYPES.items()}

SINGULAR: dict[str, str] = {
    "location_products": "Planning policy", "resources": "Resource", "production_sources": "Production source",
    "purchasing_sources": "Purchasing source", "lanes": "Lane", "demand": "Demand", "receipts": "Scheduled receipt",
    "history": "Sales history", "events": "Event", "npi": "New-product rule", "overrides": "Forecast override",
    "allocations": "Allocation", "confirmations": "Confirmation", "changeovers": "Changeover",
    "movements": "Goods movement", "closed_orders": "Closed order", "accuracy": "Accuracy record",
    "rolled_weeks": "Rolled week", "stock_targets": "Stock target",
}

# validate._ref's message: "<field> refers to unknown <kind> '<value>'"
_REF_MSG = re.compile(r"(.+?) refers to unknown (\w+) '(.*)'$")
_MAX_ROUNDS = 6


class SetAside(BaseModel):
    """A record left out of planning until it is fixed."""

    collection: str
    index: int
    object_type: str
    object_id: str      # the key the web client lists the record under (id, "location/product" or "#index")
    label: str          # how a person names it: its id, else location / product, else its row number
    field: str | None
    reason: str


def label(collection: str, rec: Any, index: int) -> str:
    """How a person would name the record: its id, else location/product, else its row number."""
    if isinstance(rec, dict):
        if rec.get("id"):
            return str(rec["id"])
        loc, prod = rec.get("location"), rec.get("product")
        if loc or prod:
            return f"{loc or '?'} / {prod or '?'}"
    return f"row {index + 1}"


def client_key(collection: str, rec: Any, index: int) -> str:
    """The key the web client's tables use for a record (model/collections.ts `keyOf`)."""
    r = rec if isinstance(rec, dict) else {}
    if collection in ("location_products", "npi"):
        return f"{r.get('location')}/{r.get('product')}"
    if collection == "closed_orders":
        return f"{r.get('kind')}|{r.get('id')}"
    if collection in ("history", "confirmations", "changeovers", "overrides", "accuracy", "rolled_weeks", "stock_targets"):
        return f"#{index}"
    return str(r.get("id") or f"#{index}")


# ---------------------------------------------------------------------------------------------
FIELD_WORDS = {
    "modes": "transport modes", "transit_days": "transit days", "qty": "quantity", "lead_time_days": "lead time",
    "location": "location", "product": "product", "origin": "from", "destination": "to", "supplier": "supplier",
    "resource": "resource", "date": "date", "due_date": "due date", "price": "price", "id": "id",
    "run_hours_per_unit": "run hours per unit", "setup_hours": "setup hours", "seq": "operation number",
    "wacc": "WACC", "horizon_days": "horizon days", "planning_start": "planning start",
    "components": "part", "operations": "step", "co_products": "co-product", "shifts": "shift",
    "capacity_changes": "capacity change", "subcontract": "done outside", "send_ahead_qty": "overlap quantity",
    "break_minutes": "break", "valid_from": "valid from", "valid_to": "valid to", "workdays": "working days",
    "float_before_workdays": "float before production", "float_after_workdays": "float after production",
}


def field_words(loc: tuple[Any, ...]) -> str:
    """('lanes', 0, 'modes', 0, 'transit_days') → 'transport mode 1: transit days'."""
    parts: list[str] = []
    for p in loc:
        if isinstance(p, int):
            if parts:
                parts[-1] = f"{parts[-1]} {p + 1}"
            continue
        parts.append(FIELD_WORDS.get(str(p), str(p).replace("_", " ")))
    return ": ".join(parts) if parts else "value"


def _unit_at(loc: tuple[Any, ...]) -> str | None:
    """The ``x-unit`` of the dataset field at ``loc`` (e.g. 'fraction'), found by walking the JSON schema."""
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = Dataset.model_json_schema()
    defs = _SCHEMA.get("$defs", {})
    node: dict[str, Any] = _SCHEMA
    for p in loc:
        if p in ("body", "dataset") and "properties" in node and p not in node["properties"]:
            continue
        while True:
            if "$ref" in node:
                node = defs.get(node["$ref"].split("/")[-1], {})
            elif "anyOf" in node:
                node = next((n for n in node["anyOf"] if n.get("type") != "null"), {})
            else:
                break
        if isinstance(p, int):
            node = node.get("items", {})
        else:
            node = node.get("properties", {}).get(p, {})
    return node.get("x-unit")


_SCHEMA: dict[str, Any] | None = None


def plain(err: dict[str, Any]) -> str:
    """A pydantic error in words a planner reads, without the field name (the caller adds it)."""
    t, ctx = err.get("type", ""), dict(err.get("ctx") or {})
    if t in ("greater_than_equal", "greater_than", "less_than_equal", "less_than") and \
            _unit_at(tuple(err.get("loc", ()))) == "fraction":
        ctx = {k: f"{_n(round(float(v) * 100, 4))}%" if k in ("ge", "gt", "le", "lt") else v for k, v in ctx.items()}
    if t == "missing":
        return "is not filled in"
    if t == "too_short":
        n = ctx.get("min_length", 1)
        return "— add at least one" if n == 1 else f"— add at least {n}"
    if t == "too_long":
        return f"has too many (at most {ctx.get('max_length')})"
    if t == "string_too_short":
        return "is empty"
    if t == "string_too_long":
        return f"is too long (at most {ctx.get('max_length')} characters)"
    if t == "string_pattern_mismatch":
        return "may use only letters, digits, '.', '_' and '-', and must start with a letter or digit"
    if t == "greater_than_equal":
        return f"must be {_n(ctx.get('ge'))} or more"
    if t == "greater_than":
        return f"must be more than {_n(ctx.get('gt'))}"
    if t == "less_than_equal":
        return f"must be {_n(ctx.get('le'))} or less"
    if t == "less_than":
        return f"must be less than {_n(ctx.get('lt'))}"
    if t in ("enum", "literal_error"):
        return f"must be one of: {ctx.get('expected', '')}".rstrip(": ")
    if t.startswith("date") or t.startswith("datetime"):
        return "is not a date (write it as YYYY-MM-DD, e.g. 2026-10-05)"
    if t in ("float_parsing", "int_parsing", "float_type", "int_type", "int_from_float"):
        return "must be a whole number" if t.startswith("int") else "must be a number"
    if t == "extra_forbidden":
        return "is not a known field (check the spelling of the column)"
    if t in ("bool_parsing", "bool_type"):
        return "must be yes or no"
    if t == "value_error":  # a model rule: its message is already a sentence
        return str(err.get("msg", "")).removeprefix("Value error, ")
    msg = str(err.get("msg", "is not valid"))
    return msg[0].lower() + msg[1:] if msg else "is not valid"


def _n(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


class DatasetRejected(Exception):
    """Something that cannot be set aside is invalid; ``errors`` are pydantic-style with plain messages."""

    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__(f"{len(errors)} error(s)")
        self.errors = errors


def plain_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite each error's ``msg`` in plain words; ``loc`` and ``type`` are kept for the forms."""
    out = []
    for e in errors:
        loc = tuple(e.get("loc", ()))
        body = loc[1:] if loc[:1] == ("body",) else loc
        body = body[1:] if body[:1] == ("dataset",) else body
        where = body[2:] if len(body) > 2 and isinstance(body[1], int) else body[1:] or body
        out.append({"type": e.get("type", ""), "loc": list(loc), "msg": f"{field_words(tuple(where))} {plain(e)}"})
    return out


# ---------------------------------------------------------------------------------------------
_REF_FIELDS = ("location", "product", "supplier", "origin", "destination", "resource")


def _empty_ref(rec: Any) -> str | None:
    """The first top-level reference left empty in a raw record, if any."""
    if not isinstance(rec, dict):
        return None
    return next((f for f in _REF_FIELDS if f in rec and (rec[f] is None or str(rec[f]).strip() == "")), None)


def _readiness_id(collection: str, rec: dict[str, Any], index: int) -> str:
    """The object id the readiness gate reports for this record (see validate._references)."""
    if collection in ("location_products", "npi"):
        return f"{rec.get('location')}/{rec.get('product')}"
    if collection == "overrides":
        return f"{rec.get('location')}/{rec.get('product')}@{rec.get('date')}"
    if collection in ("history", "confirmations", "changeovers"):
        return f"#{index}"
    if collection == "demand":
        return str(rec.get("id") or f"#{index}")
    return str(rec.get("id", f"#{index}"))


def lenient(raw: dict[str, Any] | Dataset) -> tuple[Dataset, list[SetAside]]:
    """Parse ``raw``, setting aside records that cannot be planned yet.

    Raises :class:`DatasetRejected` when something that cannot be set aside is invalid (settings,
    a location, a product, a calendar). The returned list gives each set-aside record's position in ``raw``.
    """
    from . import validate  # the package imports this module lazily, so no import cycle

    if isinstance(raw, Dataset):  # already parsed (the in-process scenario client calls the endpoints directly)
        return raw, []

    work = {k: (list(v) if k in COLLECTION_TYPES and isinstance(v, list) else v) for k, v in raw.items()}
    # position of each surviving record in the caller's lists
    pos = {k: list(range(len(v))) for k, v in work.items() if k in COLLECTION_TYPES and isinstance(v, list)}
    aside: list[SetAside] = []

    def drop(coll: str, i: int, field: str | None, reason: str) -> None:
        rec = work[coll][i]
        n = pos[coll][i]
        aside.append(SetAside(collection=coll, index=n, object_type=COLLECTION_TYPES[coll], object_id=client_key(coll, rec, n),
                              label=label(coll, rec, n), field=field, reason=reason))

    def remove(marks: dict[str, set[int]]) -> None:
        for coll, idx in marks.items():
            work[coll] = [r for i, r in enumerate(work[coll]) if i not in idx]
            pos[coll] = [p for i, p in enumerate(pos[coll]) if i not in idx]

    for _ in range(_MAX_ROUNDS):
        # 1. the schema
        try:
            ds = Dataset.model_validate(work)
        except ValidationError as exc:
            marks: dict[str, set[int]] = {}
            first: dict[tuple[str, int], dict[str, Any]] = {}
            hard = []
            for e in exc.errors():
                loc = e["loc"]
                if len(loc) >= 2 and loc[0] in COLLECTION_TYPES and isinstance(loc[1], int):
                    first.setdefault((str(loc[0]), loc[1]), e)
                    marks.setdefault(str(loc[0]), set()).add(loc[1])
                else:
                    hard.append(e)
            if hard:
                raise DatasetRejected(plain_errors(hard)) from None
            for (coll, i), e in first.items():
                empty = _empty_ref(work[coll][i])
                if empty:  # a reference not chosen yet says more than whatever else fails because of it
                    drop(coll, i, empty, f"{field_words((empty,))} is not filled in")
                    continue
                f = e["loc"][2:]
                drop(coll, i, ".".join(str(x) for x in f) or None,
                     f"{field_words(tuple(f))} {plain(e)}" if f else plain(e))
            remove(marks)
            continue
        # 2. references left empty, or to a record that was itself set aside. A reference to something that does not
        #    exist at all, or to the wrong kind of place, is a real inconsistency, not an unfinished record: it stays
        #    an error in the readiness gate.
        marks = {}
        for iss in validate(ds):
            coll = _TYPE_COLLECTION.get(iss.object_type)
            if coll is None or iss.code != "REF_UNKNOWN":
                continue
            m = _REF_MSG.match(iss.message)
            if not m or (m.group(3) and not any(a.object_id == m.group(3) and a.object_type == m.group(2) for a in aside)):
                continue
            for i, rec in enumerate(work[coll]):
                if i in marks.get(coll, set()) or _readiness_id(coll, rec, i) != iss.object_id:
                    continue
                marks.setdefault(coll, set()).add(i)
                drop(coll, i, iss.field, _ref_reason(iss.message, aside))
        if not marks:
            return ds, aside
        remove(marks)
    try:
        return Dataset.model_validate(work), aside
    except ValidationError as exc:
        raise DatasetRejected(plain_errors(exc.errors())) from None


def _ref_reason(message: str, aside: list[SetAside]) -> str:
    """`resource refers to unknown resource 'R-1'` → plain words, noting when the target was itself set aside."""
    m = _REF_MSG.match(message)
    if m:
        field, kind, value = m.groups()
        field = re.sub(r"operations\[(\d+)\]\.", r"operation \1: ", field)
        field = ": ".join(FIELD_WORDS.get(w, w.replace("_", " ")) for w in field.split("."))
        if not value:
            return f"{field} is not filled in"
        if any(a.object_id == value and a.object_type == kind for a in aside):
            return f"{field} {value} is itself left out"
        return f"{field} names {kind} {value}, which does not exist"
    return message
