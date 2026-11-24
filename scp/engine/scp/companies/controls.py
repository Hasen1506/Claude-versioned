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
    "production_cost_postings": "production_cost", "carrier_bank_accounts": "master_data",
    "carrier_bank_lines": "payments", "carrier_bank_periods": "payments",
    "history": "planning", "accuracy": "planning", "rolled_weeks": "planning", "closed_orders": "planning",
    "confirmations": "planning", "allocations": "planning", "forecast_snapshots": "planning",
    "events": "planning", "overrides": "planning", "family_overrides": "planning", "stock_targets": "planning",
}


def authorize(before: dict, after: dict, email: str, *, count_projection: bool = False) -> dict:
    finance = before.get("finance") or {}
    roles = finance.get("control_roles") or {}
    actor = email.strip().lower()
    required = set()
    newly_billed = set()
    invoices = ("supplier_invoices", "invoices", "intercompany_invoices")
    receipts = [*(before.get("receipts") or []), *(after.get("receipts") or [])]
    production_orders = {r.get("id") for r in receipts if r.get("kind") == "production" and r.get("id")}
    stock_references = {r.get("id") for r in [*receipts, *(after.get("returns") or [])] if r.get("id")}
    for name, _key, old, new in changed_records(before, after):
        if name == "purchase_valuation":
            continue  # server-derived immutable metadata, checked independently by transactions.protect
        if count_projection and name == "location_products":
            continue  # the official count posting computes on-hand from the journal
        if name in invoices:
            a, b = old or {}, new or {}
            if not old or not new:
                required.add("billing")
            else:
                lifecycle = {"payments", "released_by", "released_on", "note", "sent_on", "reminded_on", "reminder_level"}
                if {k: v for k, v in a.items() if k not in lifecycle} != {
                        k: v for k, v in b.items() if k not in lifecycle}:
                    required.add("billing")
            # A combined entry/payment or entry/release needs both grants too.
            if (a.get("payments") or []) != (b.get("payments") or []):
                required.add("payments")
            if (a.get("released_by") or "", a.get("released_on")) != (b.get("released_by") or "", b.get("released_on")):
                required.add("invoice_release")
            if len(b.get("payments") or []) > len(a.get("payments") or []) and finance.get("separate_payments"):
                entrant = str(a.get("entered_by") or (actor if not old else "")).lower()
                releaser = str(b.get("released_by") or "").lower()
                if not entrant:
                    raise ValueError("legacy invoice has no independently recorded entrant; review it before enabling payment")
                if actor in (entrant, releaser):
                    raise ValueError("payment requires a different person from the invoice entrant and releaser")
        elif name == "freight_orders":
            a, b = old or {}, new or {}
            booked = b.get("status") == "settled" and a.get("status") != "settled"
            credited = (a.get("bill_credits") or []) != (b.get("bill_credits") or [])
            paid = (a.get("bill_payments") or []) != (b.get("bill_payments") or [])
            recorded = (a.get("bill_events") or []) != (b.get("bill_events") or [])
            events = b.get("bill_events") or []
            appended = events[-1] if recorded and isinstance(events, list) and events and isinstance(events[-1], dict) else {}
            kind = appended.get("kind")
            if recorded:
                required.add("payments" if kind in ("match_bank", "refund_bill", "reverse_bank_cash") else "billing")
            if kind == "reverse_bank_cash" and appended.get("late_reason"):
                required.add("period_close")
            if booked:
                if str(b.get("bill_entered_by") or actor).strip().lower() != actor:
                    raise ValueError("a carrier bill entrant is recorded from the signed-in identity")
                newly_billed.add(b.get("id"))
            if booked or credited:
                required.add("billing")
            if paid or kind in ("refund_bill", "reverse_bank_cash"):
                required.add("payments")
                if finance.get("separate_payments") and (b.get("bill_payments") or kind in ("refund_bill", "reverse_bank_cash")):
                    entrant = str(a.get("bill_entered_by") or "").lower()
                    if not entrant:
                        raise ValueError("legacy carrier bill has no recorded entrant; reconcile it before payment")
                    if actor == entrant:
                        raise ValueError("carrier payment requires a different person from the bill entrant")
            if not (booked or credited or paid or recorded):
                required.add("transport")
        elif name == "finance":
            a, b = old or {}, new or {}
            if a.get("closed_through") != b.get("closed_through"):
                required.add("period_close")
            admin = {"closed_through", "control_roles", "separate_payments", "inventory_count_limits"}
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
        elif name == "purchase_orders" and old and new and {k: v for k, v in old.items() if k != "fx_rate"} == {
                k: v for k, v in new.items() if k != "fx_rate"}:
            continue  # server-validated posting metadata, not a purchasing exposure edit
        else:
            department = "master_data" if name in MASTER else DEPARTMENTS.get(name, "master_data")
            if name == "receipts" and (new or {}).get("kind") == "production":
                department = "manufacturing"
            required.add(department)
            if name == "challans":
                previous = (old or {}).get("returns") or []
                returns = (new or {}).get("returns") or []
                if not isinstance(previous, list) or not isinstance(returns, list) or any(
                        not isinstance(r, dict) for r in returns):
                    raise ValueError("job-work returns must be a list of custody records")
                if any(r.get("kind") == "lost" for r in returns[len(previous):]):
                    required.add("inventory_adjustment")
            if name == "third_party_orders" and (new or {}).get("sent_on") != (old or {}).get("sent_on"):
                required.add("purchasing")
            if name == "movements" and ((new or {}).get("type") == "issue"
                    or (new or {}).get("reference") in production_orders):
                required.add("manufacturing")
            if name == "movements" and (new or {}).get("type") in ("adjustment", "opening", "scrap"):
                required.add("inventory_adjustment")
            if (name == "movements" and (new or {}).get("type") == "receipt"
                    and (new or {}).get("reference") not in stock_references):
                required.add("inventory_adjustment")
    if roles:
        missing = sorted(op for op in required if actor not in {str(e).strip().lower() for e in roles.get(op, [])})
        if missing:
            raise ValueError(f"{email} has no grant for {', '.join(missing)}")
    result = after
    if newly_billed:
        result = {**result, "freight_orders": [
            {**row, "bill_entered_by": actor} if isinstance(row, dict) and row.get("id") in newly_billed else row
            for row in after["freight_orders"]
        ]}
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
