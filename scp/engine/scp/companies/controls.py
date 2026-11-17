"""Named business-operation grants, enforced on all company persistence routes.

An empty matrix preserves legacy membership semantics. Once configured it is
fail-closed: an omitted operation has no grantees. Membership/place/family and
domain invariants still apply. Owners administer policy; they do not bypass it.
"""
from __future__ import annotations

from .rights import MASTER, changed_records

DEPARTMENTS = {
    "sales_orders": "sales", "quotations": "sales", "demand": "sales", "deliveries": "sales", "returns": "sales",
    "third_party_orders": "sales", "purchase_orders": "purchasing", "cancelled_purchase_orders": "purchasing",
    "supplier_returns": "purchasing", "shipping_notices": "purchasing", "receipts": "purchasing",
    "challans": "manufacturing", "movements": "warehouse", "batches": "warehouse", "inventory_docs": "warehouse",
    "warehouse_tasks": "warehouse", "waves": "warehouse", "freight_orders": "transport",
    "history": "planning", "accuracy": "planning", "rolled_weeks": "planning", "closed_orders": "planning",
    "confirmations": "planning", "allocations": "planning", "forecast_snapshots": "planning",
    "events": "planning", "overrides": "planning", "family_overrides": "planning", "stock_targets": "planning",
}


def authorize(before: dict, after: dict, email: str) -> dict:
    finance = before.get("finance") or {}
    roles = finance.get("control_roles") or {}
    actor = email.strip().lower()
    required = set()
    invoices = ("supplier_invoices", "invoices", "intercompany_invoices")
    production_orders = {r.get("id") for r in [*(before.get("receipts") or []), *(after.get("receipts") or [])]
                         if r.get("kind") == "production"}
    for name, _key, old, new in changed_records(before, after):
        if name in invoices:
            a, b = old or {}, new or {}
            if not old or not new:
                required.add("billing")
            else:
                if a.get("payments", []) != b.get("payments", []):
                    required.add("payments")
                if (a.get("released_by"), a.get("released_on")) != (b.get("released_by"), b.get("released_on")):
                    required.add("invoice_release")
                lifecycle = {"payments", "released_by", "released_on", "note", "sent_on", "reminded_on", "reminder_level"}
                if {k: v for k, v in a.items() if k not in lifecycle} != {
                        k: v for k, v in b.items() if k not in lifecycle}:
                    required.add("billing")
            if len(b.get("payments") or []) > len(a.get("payments") or []) and finance.get("separate_payments"):
                entrant = str(a.get("entered_by") or (actor if not old else "")).lower()
                releaser = str(b.get("released_by") or "").lower()
                if not entrant:
                    raise ValueError("legacy invoice has no independently recorded entrant; review it before enabling payment")
                if actor in (entrant, releaser):
                    raise ValueError("payment requires a different person from the invoice entrant and releaser")
        elif name == "finance":
            a, b = old or {}, new or {}
            if a.get("closed_through") != b.get("closed_through"):
                required.add("period_close")
            admin = {"closed_through", "control_roles", "separate_payments"}
            if {k: v for k, v in a.items() if k not in admin} != {k: v for k, v in b.items() if k not in admin}:
                required.add("master_data")
        elif name == "sales_orders" and old and new and old.get("credit_block") and not new.get("credit_block"):
            required.add("credit_release")
            omit = {"credit_block", "credit_note"}
            if {k: v for k, v in old.items() if k not in omit} != {k: v for k, v in new.items() if k not in omit}:
                required.add("sales")
        elif name == "settings" and old and new and {k: v for k, v in old.items() if k != "planning_start"} == {
                k: v for k, v in new.items() if k != "planning_start"}:
            required.add("planning")
        else:
            department = "master_data" if name in MASTER else DEPARTMENTS.get(name, "master_data")
            if name == "receipts" and (new or {}).get("kind") == "production":
                department = "manufacturing"
            required.add(department)
            if name == "movements" and ((new or {}).get("type") == "issue"
                    or (new or {}).get("reference") in production_orders):
                required.add("manufacturing")
    if roles:
        missing = sorted(op for op in required if actor not in {str(e).strip().lower() for e in roles.get(op, [])})
        if missing:
            raise ValueError(f"{email} has no grant for {', '.join(missing)}")
    result = after
    for name in invoices:
        old_ids = {i.get("id") for i in before.get(name) or []}
        rows = []
        changed = False
        for row in after.get(name) or []:
            if row.get("id") not in old_ids:
                if row.get("entered_by") and row["entered_by"].strip().lower() != actor:
                    raise ValueError("an invoice entrant is recorded from the signed-in identity")
                row = {**row, "entered_by": actor}
                changed = True
            rows.append(row)
        if changed:
            result = {**result, name: rows}
    return result
