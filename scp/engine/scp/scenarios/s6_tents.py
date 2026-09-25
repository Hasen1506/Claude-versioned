"""S6 · Fjord Outfitters: two weeks of execution, closed into the next plan.

A wholesaler buys tents and ships them from its warehouse to a trade customer one day away. The planner
plans, promises three orders, firms the purchase orders of the next two weeks, and the warehouse then
posts what really happened: a late shipment, a short one, a late supplier delivery, a partial one and a
damaged tent. Rolling forward must turn the goods-movement journal into the new starting position and
into the measures the control tower reports (forecast accuracy, OTIF, supplier reliability), and the new
base must go through the version lifecycle (branch, edit, compare, discard, promote) with its content
immutable and its hash stable.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from ..model import Dataset
from .harness import Client, Ctx, Scenario, by, d, one

START = d("2026-05-04")
ROLL = d("2026-05-18")


def build() -> dict:
    fc = [{"location": "CUST", "product": "TENT", "date": (START + dt.timedelta(days=2 + 7 * w)).isoformat(), "qty": 70}
          for w in range(8)]                                    # Wednesdays, 6 May – 24 Jun
    so = [("SO-1", "2026-05-06", 50), ("SO-2", "2026-05-08", 30), ("SO-3", "2026-05-09", 20)]
    return {
        "settings": {"company_name": "Fjord Outfitters", "currency": "NOK", "planning_start": START.isoformat(),
                     "horizon_days": 56, "bucket": "week", "default_calendar": "CAL-7"},
        "calendars": [{"id": "CAL-7", "name": "Seven-day warehouse", "workdays": [0, 1, 2, 3, 4, 5, 6]}],
        "locations": [{"id": "WH", "name": "Bergen warehouse", "type": "warehouse"},
                      {"id": "SUP", "name": "Tent factory", "type": "supplier"},
                      {"id": "CUST", "name": "Outdoor trade customer", "type": "customer"}],
        "products": [{"id": "TENT", "name": "Two-person tent", "type": "FG", "price": 2000}],
        "location_products": [{"location": "WH", "product": "TENT", "on_hand": 100}],
        "purchasing_sources": [{"id": "PU-TENT", "supplier": "SUP", "product": "TENT", "location": "WH", "price": 800,
                                "lead_time_days": 5}],
        "lanes": [{"id": "L-WC", "origin": "WH", "destination": "CUST", "modes": [{"transit_days": 1}]}],
        "demand": fc + [{"id": i, "location": "CUST", "product": "TENT", "date": day, "qty": q, "kind": "sales_order"}
                        for i, day, q in so],
        "movements": [{"id": "M-OPEN", "date": "2026-05-01", "type": "opening", "location": "WH", "product": "TENT",
                       "qty": 100, "note": "Stock take at go-live"}],
    }


def _journal(po1: str, po2: str) -> list[dict]:
    """What the warehouse posted between 4 and 17 May (goods-issue dates; the customer receives a day later)."""
    def mv(i: str, day: str, typ: str, qty: float, **kw: object) -> dict:
        return {"id": i, "date": day, "type": typ, "location": "WH", "product": "TENT", "qty": qty, **kw}
    return [
        mv("GI-1", "2026-05-06", "sale", 50, reference="SO-1", counterparty="CUST", note="Shipped a day late"),
        mv("GI-2", "2026-05-07", "sale", 28, reference="SO-2", counterparty="CUST", final=True,
           note="Two short: customer accepts the rest"),
        mv("GI-3", "2026-05-08", "sale", 20, reference="SO-3", counterparty="CUST"),
        mv("GI-4", "2026-05-10", "sale", 5, counterparty="CUST", note="Sunday top-up, arrives Monday"),
        mv("GR-1", "2026-05-13", "receipt", 40, reference=po1, counterparty="SUP", note="A day late"),
        mv("GI-5", "2026-05-13", "sale", 38, counterparty="CUST"),
        mv("ADJ-1", "2026-05-15", "adjustment", -2, note="Two tents damaged in the racking"),
        mv("GR-2", "2026-05-17", "receipt", 60, reference=po2, counterparty="SUP", note="Partial: 10 to follow"),
        mv("GI-6", "2026-05-16", "sale", 25, counterparty="CUST"),
    ]


def _canon(ds: Dataset) -> str:
    return json.dumps(ds.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Plan the next eight weeks", "plan", "POST /api/plan",
                  "The three orders consume the Wednesday forecasts (SO-1 and SO-2 from 6 May, SO-2's last 10 and "
                  "SO-3 from 13 May). The warehouse ships a day ahead; its 100 tents cover the orders exactly, so "
                  "the first purchase order covers 13 May's remaining 40."):
        plan = c.plan(ds)
        ctx.eq("no blocking issues", [i.code for i in plan.issues if i.severity == "error"], [])
        pos = sorted((o.need_date, o.start_date, o.qty) for o in by(plan.orders, kind="buy"))
        ctx.eq("first three purchase orders (need, start, qty)", pos[:3],
               [(d("2026-05-12"), d("2026-05-07"), 40), (d("2026-05-19"), d("2026-05-14"), 70),
                (d("2026-05-26"), d("2026-05-21"), 70)],
               "Transfers to the customer leave a day before each need: 12 May for 13 May's 40, then 70 a week. "
               "Five days of supplier lead time before each.")

    with ctx.step("Promise the three orders", "promise", "POST /api/promise/commit",
                  "100 tents on hand cover 50 + 30 + 20 exactly: every order is confirmed on its requested date."):
        ds, _ = c.commit(ds)
        conf = sorted((x.order, x.ship_date, x.date, x.qty) for x in ds.confirmations)
        ctx.eq("confirmations (order, ship, deliver, qty)", conf,
               [("SO-1", d("2026-05-05"), d("2026-05-06"), 50), ("SO-2", d("2026-05-07"), d("2026-05-08"), 30),
                ("SO-3", d("2026-05-08"), d("2026-05-09"), 20)])

    with ctx.step("Firm the next two weeks", "execution", "POST /api/orders/firm",
                  "Planned orders starting before 18 May become purchase orders; deliveries to the customer are "
                  "shipped against promises, never firmed."):
        ds, rep = c.firm(ds, within_days=14)
        firmed = sorted((f.receipt_id, f.qty, f.due_date) for f in rep.firmed)
        ctx.eq("purchase orders created", firmed, [("PO-00001", 40, d("2026-05-12")), ("PO-00002", 70, d("2026-05-19"))])
        ctx.true("customer deliveries skipped with a reason", len(rep.skipped) > 0
                 and all("customer" in r for r in rep.skipped.values()), actual=sorted(set(rep.skipped.values())),
                 expect="at least one, each naming the customer")

    with ctx.step("Post two weeks of goods movements", "execution", "POST /api/actuals",
                  "Stock is never typed: it is the sum of the journal. The view flags what does not add up yet."):
        raw = json.loads(ds.model_dump_json())
        raw["movements"] += _journal("PO-00001", "PO-00002")
        ds = Dataset.model_validate(raw)
        view = c.actuals(ds, ROLL)
        row = one(view.stock, location="WH", product="TENT")
        ctx.near("stock by the journal", row.movement_stock, 100 - 50 - 28 - 20 - 5 + 40 - 38 - 2 + 60 - 25, 1e-9,
                 "Opening 100 − sales 166 + receipts 100 − 2 damaged = 32.")
        ctx.near("difference to the master record", row.difference, 32 - 100, 1e-9)
        ctx.near("by movement type", row.by_type, {"opening": 100, "sale": -166, "receipt": 100, "adjustment": -2}, 1e-9)
        po2 = one(view.open_orders, id="PO-00002")
        ctx.near("PO-00002 open after the partial receipt", (po2.delivered, po2.open), (60, 10), 1e-9)
        ctx.eq("every movement matches an order or is unreferenced", view.unmatched, [])

    with ctx.step("Roll forward to 18 May", "execution", "POST /api/actuals/roll",
                  "The journal becomes the new starting position, closes what was delivered, and logs forecast "
                  "accuracy and deliveries for the control tower."):
        rolled, rr = c.roll(ds, ROLL)
        ctx.eq("new planning start", rolled.settings.planning_start, ROLL)
        ctx.near("warehouse on hand", one(rolled.location_products, location="WH").on_hand, 32, 1e-9)
        ctx.eq("receipts left open", [(r.id, r.qty, r.ordered_qty) for r in rolled.receipts], [("PO-00002", 10, 70)])
        closed = {x.id: (x.ordered_qty, x.delivered_qty, x.due_date, x.last_delivery) for x in rr.closed}
        ctx.eq("closed orders (ordered, delivered, due, delivered on)", closed, {
            "PO-00001": (40, 40, d("2026-05-12"), d("2026-05-13")),
            "SO-1": (50, 50, d("2026-05-06"), d("2026-05-07")),
            "SO-2": (30, 28, d("2026-05-08"), d("2026-05-08")),
            "SO-3": (20, 20, d("2026-05-09"), d("2026-05-09"))},
            "A sale is delivered when the customer receives it: goods issue + 1 day of transit. SO-1 left on "
            "its due date, so it arrived late; SO-2 was closed short by its final delivery.")
        ctx.near("forecast dropped", rr.forecast_dropped, 140, 1e-9, "The 6 and 13 May forecasts have elapsed.")
        acc = [(a.start, a.forecast, a.actual) for a in rr.accuracy]
        ctx.eq("forecast vs actual per week", acc,
               [(d("2026-05-04"), 70, 98), (d("2026-05-11"), 70, 68)],
               "Sales count in the week the customer receives them: the Sunday top-up of 5 lands on Monday "
               "11 May, in week 2 (50 + 28 + 20 = 98; 5 + 38 + 25 = 68).")
        ctx.eq("sales appended to history (by arrival)",
               sorted((h.date, h.qty) for h in rolled.history),
               [(d("2026-05-07"), 50), (d("2026-05-08"), 28), (d("2026-05-09"), 20), (d("2026-05-11"), 5),
                (d("2026-05-14"), 38), (d("2026-05-17"), 25)])
        ctx.eq("confirmations of the closed orders removed", (rr.confirmations_trimmed, rolled.confirmations), (3, []))
        ctx.eq("warnings", rr.warnings, [])

    with ctx.step("Roll again: nothing changes", "execution", "POST /api/actuals/roll",
                  "Every quantity is recomputed from original quantities and the whole journal."):
        again, _ = c.roll(rolled, ROLL)
        ctx.true("rolling the rolled plan to the same date is a no-op", _canon(again) == _canon(rolled),
                 expect="the same dataset, byte for byte")
        late = json.loads(ds.model_dump_json())
        late["movements"].append({"id": "GI-7", "date": "2026-05-13", "type": "sale", "location": "WH", "product": "TENT",
                                  "qty": 2, "counterparty": "CUST", "note": "Posted late"})
        rerolled, rr2 = c.roll(Dataset.model_validate(late), ROLL)
        ctx.near("re-rolling after a late posting picks it up",
                 (one(rerolled.location_products, location="WH").on_hand, rr2.accuracy[1].actual), (30, 70), 1e-9,
                 "Roll the pre-roll version again with the late sale in the journal: stock 30, week 2 sales 70.")

    with ctx.step("Control tower after the roll", "tower", "POST /api/tower",
                  "The KPIs are computed from the closed-order and accuracy logs the roll just wrote."):
        tw = c.tower(rolled)
        k = {x.id: x for x in tw.kpis}
        ctx.near("forecast accuracy and bias", (k["forecast_accuracy"].value, k["forecast_bias"].value),
                 (1 - 30 / 166, (140 - 166) / 166), 1e-9,
                 "Σ|F − A| = 28 + 2 = 30 over Σ A = 166: WMAPE 18.1 %, accuracy 81.9 %; bias (140 − 166) ÷ 166.")
        ctx.near("OTIF to requested and to confirmed date", (k["otif_requested"].value, k["otif_confirmed"].value),
                 (1 / 3, 1 / 3), 1e-9, "SO-1 late, SO-2 short (93 % < 98 % tolerance), SO-3 on time in full.")
        ctx.near("perfect order", k["perfect_order"].value, 1 / 3, 1e-9)
        ctx.near("confirmed on requested date", k["confirmation_rate"].value, 1.0, 1e-9)
        ctx.eq("supplier reliability", (k["supplier_reliability"].value, k["supplier_reliability"].n), (0.0, 1),
               "PO-00001 arrived a day late; PO-00002 is still open, so it is not measured yet.")

    with ctx.step("Version the new base and try a scenario", "versions", "POST /api/versions …",
                  "Save the rolled plan as a base (immutable), branch a scenario with 30 tents of safety stock, "
                  "compare, discard a second scenario and promote the first."):
        base = c.save_base(rolled, "Week 21 base", "after the 18 May roll")
        expected_sha = hashlib.sha256(_canon(rolled).encode()).hexdigest()
        ctx.eq("base saved with the content hash", (base.kind, base.status, base.sha256),
               ("base", "active", expected_sha), "SHA-256 of the canonical JSON (sorted keys, compact).")
        ctx.raises("a base cannot be edited", lambda: c.update_version(base.id, rolled), 409, "immutable")
        sc = c.branch(base.id, "Safety stock 30")
        ctx.eq("the branch starts identical", (sc.kind, sc.parent_id, sc.sha256), ("scenario", base.id, base.sha256))
        edit = json.loads(rolled.model_dump_json())
        edit["location_products"][0]["safety_stock"] = {"method": "fixed", "qty": 30}
        edited = Dataset.model_validate(edit)
        sc = c.update_version(sc.id, edited)
        ctx.eq("the edit changes its hash", sc.sha256, hashlib.sha256(_canon(edited).encode()).hexdigest())
        cmp = c.compare_versions(base.id, sc.id)
        lp_diff = one(cmp.diff.collections, collection="location_products")
        ctx.eq("the comparison finds one changed record", (cmp.diff.changes, lp_diff.changed), (1, 1))
        ctx.true("safety stock costs money", cmp.plan_b.inventory_value_avg > cmp.plan_a.inventory_value_avg,
                 actual=(round(cmp.plan_a.inventory_value_avg, 2), round(cmp.plan_b.inventory_value_avg, 2)),
                 expect="(A, B) with B > A")
        other = c.branch(base.id, "Forecast −20 %")
        ctx.eq("discarded", c.discard(other.id).status, "discarded")
        ctx.raises("a discarded scenario cannot be branched", lambda: c.branch(other.id, "x"), 409, "discarded")
        new = c.promote(sc.id)
        ctx.eq("promotion creates a new base from the scenario", (new.kind, new.parent_id, new.sha256),
               ("base", sc.id, sc.sha256))
        ctx.eq("lifecycle", (c.get_version(base.id).meta.status, c.get_version(sc.id).meta.status),
               ("superseded", "promoted"))
        ctx.eq("the old base's content is untouched", c.get_version(base.id).meta.sha256, expected_sha)
        ctx.raises("a promoted scenario cannot be promoted twice", lambda: c.promote(sc.id), 409, "only an active scenario")


SCENARIO = Scenario(
    id="s6-tents", title="Month-end: execution closes the loop", company="Fjord Outfitters",
    story="Plan, promise and firm; the warehouse posts two weeks of real movements (a late shipment, a short one, "
          "a late supplier, a partial receipt, damage); the roll-forward turns the journal into the next plan and "
          "into accuracy, OTIF and supplier KPIs; the new base goes through the version lifecycle.",
    proves=["firming skips customer deliveries", "stock derived from the goods-movement journal",
            "partial and final deliveries", "deliveries dated at the customer (transit)",
            "forecast accuracy and bias per week", "OTIF, perfect order and supplier reliability",
            "idempotent roll-forward", "late postings re-rolled", "immutable, hashed versions",
            "branch, edit, compare, discard, promote"],
    stages=["plan", "promise", "execution", "tower", "versions"],
    found=["Sales counted in the week they shipped, not the week the customer received them, shifting accuracy and "
           "OTIF by the transit time"],
    build=build, run=run)
