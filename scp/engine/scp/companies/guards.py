"""Business rules a save of the company re-checks on the server (CV-H04).

The engine's actions (``/api/purchasing/act``, ``/api/sales/act``) are stateless: the browser posts the company,
takes the changed company back and saves it. A save could therefore carry any change those actions guard, written by
hand. The rules that matter for segregation of duties are checked again here, against the company as saved and the
signed-in person who saves:

* **Purchase order releases (≈ ME29N).** Every release a save adds to an order is recorded under the name of the
  person who saves it; it must be the next level the order's value needs, by one of that level's named approvers, and
  one person never releases two levels of the same order. An order is marked released only when every level its value
  needs has a release. The release strategy itself is read from the company as saved, so the same save cannot
  loosen it first.
* **Credit block release.** Who released a blocked sales order is recorded from the session, never from the document.

Other state machines (invoice release and payment of supplier invoices) have no named-approver rule in the engine;
they are not re-checked here.
"""
from __future__ import annotations

from typing import Any

from ..model.purchasing import PurchasingSettings

EPS = 1e-6


class ReleaseRefused(Exception):
    pass


def _levels(purchasing: Any) -> list[dict]:
    try:
        ps = PurchasingSettings.model_validate(purchasing if isinstance(purchasing, dict) else {})
    except Exception:  # noqa: BLE001 - an unreadable strategy guards nothing less: every release is refused below
        raise ReleaseRefused("the company's buying settings cannot be read: fix them before releasing orders") from None
    if ps.release_levels:
        return [lv.model_dump() for lv in sorted(ps.release_levels, key=lambda lv: lv.above)]
    if ps.approval_limit is not None:
        return [{"name": "Approval", "above": ps.approval_limit, "approvers": []}]
    return []


def _num(v: Any) -> float:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0.0


def _value(doc: dict, po: dict) -> float | None:
    """What the order is worth in company currency (None: cannot be told from the document alone)."""
    if po.get("kind") == "scheduling_agreement":
        return None
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    cur = po.get("currency")
    rate = 1.0
    if cur and cur != settings.get("currency"):
        rate = _num((settings.get("fx_rates") or {}).get(cur, 1.0)) or 1.0
    total = 0.0
    for r in doc.get("receipts") or []:
        if isinstance(r, dict) and r.get("po") == po["id"]:
            qty = r.get("ordered_qty") if r.get("ordered_qty") is not None else r.get("qty")
            total += _num(qty) * _num(r.get("price"))
    return total * rate


def _agreement_value(doc: dict, po: dict) -> float:
    from ..model import Dataset
    from ..purchasing import _agreement_value as engine_value
    from ..validate.lenient import lenient
    ds = lenient(doc)[0] if not isinstance(doc, Dataset) else doc
    header = ds.purchase_order_by_id.get(po["id"])
    return engine_value(ds, header) if header is not None else 0.0


def _approvals(po: dict | None) -> list[dict]:
    return [a for a in (po or {}).get("approvals") or [] if isinstance(a, dict)]


def _released(po: dict | None) -> bool:
    return bool((po or {}).get("approved", True))


def check_releases(before: dict, after: dict, email: str) -> None:
    """Refuse (:class:`ReleaseRefused`) a save that adds a purchase-order release the person saving may not give, or
    marks an order released without every release its value needs."""
    old = {p["id"]: p for p in before.get("purchase_orders") or [] if isinstance(p, dict) and isinstance(p.get("id"), str)}
    who = (email or "").strip().lower()
    levels: list[dict] | None = None
    for po in after.get("purchase_orders") or []:
        if not isinstance(po, dict) or not isinstance(po.get("id"), str):
            continue
        prev = old.get(po["id"])
        mine, theirs = _approvals(po), _approvals(prev)
        if prev is not None and _released(po) == _released(prev) and mine == theirs:
            continue                                   # nothing about its release changed
        if prev is None and not _released(po) and not mine:
            continue                                   # a new order waiting for release
        if prev is not None and not _released(po) and all(a in theirs for a in mine):
            continue                                   # a release taken back (an order changed): never a bypass
        if levels is None:
            levels = _levels(before.get("purchasing") if "purchasing" in before else after.get("purchasing"))
        value = _value(after, po)
        if value is None:
            value = _agreement_value(after, po)
        need = [lv for lv in levels if value > _num(lv.get("above")) + EPS]
        kept = [a for a in mine if a in theirs]
        done = {a.get("level") for a in kept}
        by = {str(a.get("by") or "").strip().lower() for a in kept}
        for a in (a for a in mine if a not in theirs):
            todo = [lv for lv in need if lv["name"] not in done]
            if not todo:
                raise ReleaseRefused(f"{po['id']} needs no further release")
            lv = todo[0]
            if a.get("level") != lv["name"]:
                raise ReleaseRefused(f"{po['id']} is released next at level {lv['name']}, not {a.get('level')}")
            giver = str(a.get("by") or "").strip().lower()
            if not who or giver != who:
                raise ReleaseRefused(f"a release of {po['id']} is recorded under the name of who gives it: "
                                     f"{email or 'sign in'}, not {a.get('by') or 'nobody'}")
            approvers = {x.strip().lower() for x in lv.get("approvers") or []}
            if approvers and who not in approvers:
                raise ReleaseRefused(f"{po['id']} is released at level {lv['name']} only by "
                                     f"{', '.join(lv.get('approvers') or [])}, not {email}")
            if who in by:
                raise ReleaseRefused(f"{email} already released {po['id']} at another level: someone else releases "
                                     f"level {lv['name']}")
            done.add(lv["name"])
            by.add(who)
        if _released(po):
            missing = [lv["name"] for lv in need if lv["name"] not in done]
            if missing:
                raise ReleaseRefused(f"{po['id']} is worth {value:,.0f} and still needs a release by "
                                     f"{', then '.join(missing)}: release it from Buying")


def record_credit_releases(before: dict, after: dict, email: str) -> dict:
    """``after`` with who released each credit-blocked sales order taken from the session (CV-H04)."""
    old = {o["id"]: o for o in before.get("sales_orders") or [] if isinstance(o, dict) and isinstance(o.get("id"), str)}
    rows = after.get("sales_orders")
    if not isinstance(rows, list):
        return after
    out, changed = [], False
    for o in rows:
        prev = old.get(o.get("id")) if isinstance(o, dict) else None
        if prev is not None and prev.get("credit_block") and not o.get("credit_block"):
            note = f"Released by {email} (was: {prev.get('credit_note') or ''})"[:200]
            if o.get("credit_note") != note:
                o = {**o, "credit_note": note}
                changed = True
        out.append(o)
    return {**after, "sales_orders": out} if changed else after
