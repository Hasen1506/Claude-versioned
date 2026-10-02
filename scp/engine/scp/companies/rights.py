"""Who may change what (Phase L): a member's rights limited to some places and some product groups, master data that
needs a second person's approval, and change documents with every field's old and new value.

**Rights by place and product group.** A member may be limited to places (a plant, a warehouse) and to product
groups (a product's *family*). A save by such a member may change only records inside those limits:

* a record is at a place when one of its place fields (``location``, ``origin``, ``destination``, ``ship_from``)
  is an allowed place, or a customer or supplier that an allowed place ships to or buys from (a route between
  them), so a plant's planner can take its customers' orders and change its suppliers' purchase orders;
* a record is in a product group when every product it names is of an allowed group;
* a record with no place (a product, a supplier, the company settings) is outside a place limit, and a record
  with no product (a place, a machine) is outside a product-group limit: those belong to everyone, so to a member
  without that limit.

**Master data approval.** With it on, a change to master data (places, products, planning policies, machines, ways
to make and buy, routes, suppliers, customer prices, calendars, changeovers and the company settings) is not saved
straight away: it waits until another member who may change data approves it. Everything else in the same save
(orders, movements, forecasts) is saved as usual.
"""
from __future__ import annotations

from typing import Any

from ..versions.diff import SINGLE, _flat
from .patch import _hashable, keys_of

MASTER = ("calendars", "locations", "products", "customer_prices", "location_products", "resources",
          "production_sources", "purchasing_sources", "lanes", "vendors", "customers", "payment_terms", "changeovers",
          *SINGLE)
# settings that are working state rather than master data: moving the plan a week changes them
WORKING = {"settings": ("planning_start",), "forecasting": ("released_inputs",)}
PLACE_FIELDS = ("location", "origin", "destination", "ship_from", "supplier")
MAX_CHANGE_ROWS = 5000        # field changes kept per save (a roll can change thousands of derived rows)
NO_CHANGE_DOCS = ("history", "accuracy", "rolled_weeks")   # derived from the movements, which do get documents


def records(doc: dict, name: str) -> dict[tuple, dict]:
    """A list's records by key (records that cannot be told apart are keyed by position)."""
    rows = doc.get(name)
    if not isinstance(rows, list):
        return {}
    fields = keys_of(name)
    out: dict[tuple, dict] = {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        k = _hashable(tuple(r.get(f) for f in fields))
        if all(v is None for v in k) or k in out:
            k = ("#", i)
        out[k] = r
    return out


def changed_records(before: dict, after: dict, names: tuple[str, ...] | None = None) -> list[tuple[str, tuple, Any, Any]]:
    """Every record a save added, removed or changed: (list, key, before or None, after or None). Settings count as
    one record each, keyed ``()``."""
    out: list[tuple[str, tuple, Any, Any]] = []
    for name in names or tuple(dict.fromkeys([*before, *after])):
        a, b = before.get(name), after.get(name)
        if a == b:
            continue
        if name in SINGLE or not (isinstance(a, list) or isinstance(b, list)):
            out.append((name, (), a, b))
            continue
        ra, rb = records(before, name), records(after, name)
        for k in dict.fromkeys([*ra, *rb]):
            if ra.get(k) != rb.get(k):
                out.append((name, k, ra.get(k), rb.get(k)))
    return out


def label(name: str, key: tuple) -> str:
    from .store import LABELS
    return LABELS.get(name, name.replace("_", " ")) + (" " + " ".join(str(v) for v in key if v is not None) if key else "")


def _allowed_places(doc: dict, places: list[str]) -> set[str]:
    """The places themselves, and the customers and suppliers they ship to or buy from."""
    kind = {x.get("id"): x.get("type") for x in doc.get("locations") or [] if isinstance(x, dict)}
    out = set(places)
    for ln in doc.get("lanes") or []:
        if not isinstance(ln, dict):
            continue
        o, d = ln.get("origin"), ln.get("destination")
        if o in places and kind.get(d) in ("customer", "supplier"):
            out.add(d)
        if d in places and kind.get(o) in ("customer", "supplier"):
            out.add(o)
    for s in doc.get("purchasing_sources") or []:
        if isinstance(s, dict) and s.get("location") in places and isinstance(s.get("supplier"), str):
            out.add(s["supplier"])
    return out


def _products_of(rec: dict) -> set[str]:
    out = {rec["product"]} if isinstance(rec.get("product"), str) else set()
    for f in ("products",):
        if isinstance(rec.get(f), list):
            out |= {p for p in rec[f] if isinstance(p, str)}
    for ln in rec.get("lines") or []:
        if isinstance(ln, dict) and isinstance(ln.get("product"), str):
            out.add(ln["product"])
    return out


def out_of_scope(before: dict, after: dict, places: list[str], families: list[str]) -> list[str]:
    """The records a save changes that a member limited to ``places`` and ``families`` may not change (plain names)."""
    if not places and not families:
        return []
    allowed = _allowed_places(before, places) | _allowed_places(after, places) if places else set()
    family = {p.get("id"): p.get("family") or "" for d in (before, after) for p in d.get("products") or []
              if isinstance(p, dict)}
    bad: list[str] = []
    for name, key, a, b in changed_records(before, after):
        if name in WORKING and isinstance(a, dict) and isinstance(b, dict) and all(
                a.get(k) == b.get(k) for k in set(a) | set(b) if k not in WORKING[name]):
            continue                                             # only working state (e.g. the planning start)
        ok = True
        for rec in (a, b):
            if not isinstance(rec, dict) or name in SINGLE:
                ok = False if name in SINGLE else ok
                continue
            if places:
                at = {rec[f] for f in PLACE_FIELDS if isinstance(rec.get(f), str)}
                if name == "locations":
                    at = {rec.get("id")}
                if not at & allowed:
                    ok = False
            if families:
                prods = {rec.get("id")} if name == "products" else _products_of(rec)
                if not prods or any(family.get(p, "") not in families for p in prods):
                    ok = False
        if not ok:
            bad.append(label(name, key))
    return bad


def split_master(before: dict, after: dict) -> tuple[dict, dict]:
    """``after`` with its master-data changes taken out (as in ``before``), and those changes on their own: a
    document of just the changed master-data parts, before and after."""
    applied = dict(after)
    held_before: dict[str, Any] = {}
    held_after: dict[str, Any] = {}
    for name in MASTER:
        a, b = before.get(name), after.get(name)
        if a == b:
            continue
        if name in WORKING and isinstance(a, dict) and isinstance(b, dict):
            keep = {k: v for k, v in b.items() if k in WORKING[name]}
            if {k: v for k, v in a.items() if k not in WORKING[name]} == {k: v for k, v in b.items() if k not in WORKING[name]}:
                continue                                         # only working state changed: saved as usual
            applied[name] = {**a, **keep}
            held_before[name], held_after[name] = a, {**b, **{k: a.get(k) for k in keep if k in a}}
            continue
        if a is None:
            applied.pop(name, None)
        else:
            applied[name] = a
        held_before[name], held_after[name] = a, b
    return applied, {"before": held_before, "after": held_after}


def field_changes(before: dict, after: dict) -> list[tuple[str, str, str, Any, Any]]:
    """Every field a save changed: (list, record, field, old, new); a record added or removed is one row with the
    whole record as its new or old value."""
    out: list[tuple[str, str, str, Any, Any]] = []
    names = tuple(n for n in dict.fromkeys([*before, *after]) if n not in NO_CHANGE_DOCS)
    for name, key, a, b in changed_records(before, after, names):
        rec = " | ".join("" if v is None else str(v) for v in key) if key and key[0] != "#" else ""
        if a is None or b is None:
            out.append((name, rec, "", a, b))
            continue
        fa = _flat(a) if isinstance(a, dict) else {"": a}
        fb = _flat(b) if isinstance(b, dict) else {"": b}
        for p in sorted(set(fa) | set(fb)):
            if fa.get(p) != fb.get(p):
                out.append((name, rec, p, fa.get(p), fb.get(p)))
    return out


class Stale(Exception):
    """A held change no longer fits: a record it changes was changed since."""


def apply_held(current: dict, held: dict) -> dict:
    """``current`` with a held master-data change made: each record it adds, changes or removes, and each setting it
    changes. :class:`Stale` names what was changed since the change was asked for."""
    before, after = held.get("before") or {}, held.get("after") or {}
    out = dict(current)
    stale: list[str] = []
    for name in dict.fromkeys([*before, *after]):
        a, b = before.get(name), after.get(name)
        if name in SINGLE or not (isinstance(a, list) or isinstance(b, list)):
            cur = current.get(name)
            if isinstance(a, dict) and isinstance(b, dict) and isinstance(cur, dict):
                new = dict(cur)
                for k in set(a) | set(b):
                    if a.get(k) != b.get(k):
                        if cur.get(k) != a.get(k):
                            stale.append(label(name, ()) + f" ({k})")
                        if k in b:
                            new[k] = b[k]
                        else:
                            new.pop(k, None)
                out[name] = new
            else:
                if cur != a:
                    stale.append(label(name, ()))
                out[name] = b
            continue
        ra, rb, rc = records(before, name), records(after, name), records(current, name)
        rows = list(current.get(name) or [])
        pos = {k: i for i, k in enumerate(rc)}
        gone: set[int] = set()
        for k in dict.fromkeys([*ra, *rb]):
            old, new = ra.get(k), rb.get(k)
            if old == new:
                continue
            if rc.get(k) != old:
                stale.append(label(name, k))
                continue
            if new is None:
                gone.add(pos[k])
            elif k in pos:
                rows[pos[k]] = new
            else:
                pos[k] = len(rows)
                rows.append(new)
        out[name] = [r for i, r in enumerate(rows) if i not in gone]
    if stale:
        raise Stale("; ".join(stale[:8]) + (f"; and {len(stale) - 8} more" if len(stale) > 8 else ""))
    return out
