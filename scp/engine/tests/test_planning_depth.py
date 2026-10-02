"""Phase P: planning depth. Lot sizes that stay within shelf life (R15, N109), measured yield written into the bill of
materials (R17), promises that make their supply (R13), demand events placed where they apply (R21), MRP groups,
special procurement, discontinuation, alternative BOMs and capacity choices."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from scp.plan import run_mrp

from .factory import base, demand, ds, lp


def daily(d: dict, loc: str, prod: str, qty: float, days: int, start: date = date(2026, 1, 5)) -> None:
    d["demand"] += [demand(loc, prod, (start + timedelta(days=k)).isoformat(), qty, kind="sales_order",
                           id=f"SO-{prod}-{k}") for k in range(days)]


def fresh_a(**ls) -> dict:
    """A keeps 7 days and is made at P; 10 a day are sold for eight weeks; no A in stock."""
    d = base(horizon=56)
    a = next(p for p in d["products"] if p["id"] == "A")
    a["shelf_life_days"] = 7
    lp(d, "P", "A").update({"on_hand": 0, "lot_sizing": ls})
    lp(d, "P", "B")["lot_sizing"] = {}
    daily(d, "P", "A", 10, 50)
    return d


# ---- lot sizes within shelf life (R15, N109) -------------------------------------------------------------
def test_a_period_lot_covers_no_more_than_the_shelf_life():
    plan = run_mrp(ds(fresh_a(policy="POQ", periods=2)))   # two weeks a lot, but A keeps a week
    made = [o for o in plan.orders if o.product == "A"]
    assert made and max(o.qty for o in made) <= 80 + 1e-6     # the day it is needed and the seven after
    assert not [e for e in plan.exceptions if e.code == "LOT_EXPIRES"]
    assert not [r for r in plan.requirements if r.kind == "expiry"]


def test_a_fixed_batch_longer_than_the_shelf_life_plans_what_it_leaves_to_expire():
    plan = run_mrp(ds(fresh_a(policy="FIXED", fixed_qty=100)))   # 100 is ten days, A keeps seven
    exp = [r for r in plan.requirements if r.kind == "expiry" and r.product == "A"]
    assert exp, "what a batch leaves after its last day expires"
    first = min(exp, key=lambda r: r.date)
    assert first.qty == pytest.approx(100 - 80)                 # used on the day it is there and the seven after
    warn = [e for e in plan.exceptions if e.code == "LOT_EXPIRES" and e.product == "A"]
    assert warn and "more than 7 days' use" in warn[0].message
    # the plan makes again for what expired: every sale is still covered
    node = next(n for n in plan.nodes if (n.location, n.product) == ("P", "A"))
    assert all(b.shortage <= 1e-6 for b in node.buckets)
    assert sum(b.expiring for b in node.buckets) == pytest.approx(sum(r.qty for r in exp))


def test_without_a_shelf_life_the_same_batch_never_expires():
    d = fresh_a(policy="FIXED", fixed_qty=100)
    next(p for p in d["products"] if p["id"] == "A")["shelf_life_days"] = None
    plan = run_mrp(ds(d))
    assert not [r for r in plan.requirements if r.kind == "expiry"]
    # and a product kept without batches is planned as before, shelf life or not
    d = fresh_a(policy="FIXED", fixed_qty=100)
    next(p for p in d["products"] if p["id"] == "A")["batches"] = False
    assert not [r for r in run_mrp(ds(d)).requirements if r.kind == "expiry"]


def test_an_economic_lot_is_cut_to_what_is_used_before_it_expires():
    d = fresh_a(policy="EOQ", ordering_cost=5000)
    plan = run_mrp(ds(d))
    made = [o for o in plan.orders if o.product == "A"]
    assert made and max(o.qty for o in made) <= 80 + 1e-6
    assert not [r for r in plan.requirements if r.kind == "expiry"]


# ---- yield in the bill of materials (R17) ----------------------------------------------------------------
def yield_plant() -> dict:
    """A made from 2 B + 1 C; two firm production orders of 10 A each, with their reservations."""
    d = base(horizon=28)
    lp(d, "P", "B")["on_hand"] = 500
    lp(d, "P", "C")["on_hand"] = 500
    d["receipts"] = [
        {"id": f"MO-{i}", "kind": "production", "location": "P", "product": "A", "qty": 10, "due_date": "2026-01-07",
         "start_date": "2026-01-05", "source": "PV-A",
         "reservations": [{"location": "P", "product": "B", "date": "2026-01-05", "qty": 20},
                          {"location": "P", "product": "C", "date": "2026-01-05", "qty": 10}]} for i in (1, 2)]
    return d


def test_parts_used_above_the_bill_of_materials_measure_the_loss_to_plan_with():
    from scp.actuals import actuals_view, measured_yields, post
    x = ds(yield_plant())
    # milk-like: B used 21 and 22 for 20 planned; C used as planned
    x, _ = post(x, "receive", order="MO-1", on=date(2026, 1, 5), usage=[{"product": "B", "qty": 21}, {"product": "C", "qty": 10}])
    x, _ = post(x, "receive", order="MO-2", on=date(2026, 1, 5), usage=[{"product": "B", "qty": 22}, {"product": "C", "qty": 10}])
    rows = {r.part: r for r in measured_yields(x)}
    b = rows["B"]
    assert b.orders == 2 and b.made == 20 and b.planned == pytest.approx(40) and b.used == pytest.approx(43)
    assert b.scrap_measured == pytest.approx(1 - 40 / 43, abs=1e-4) and b.change
    assert rows["C"].scrap_measured == 0 and not rows["C"].change
    assert {r.part for r in actuals_view(x).yields} == {"B", "C"}
    # put the measured loss in the bill of materials: the plan now buys B with it
    d = x.model_dump(mode="json")
    d["production_sources"][0]["components"][0]["scrap"] = b.scrap_measured
    y = ds(d)
    again = {r.part: r for r in measured_yields(y)}["B"]
    assert again.planned == pytest.approx(43, abs=0.01) and not again.change


def test_a_backflushed_order_says_nothing_about_the_loss():
    from scp.actuals import measured_yields, post
    x = ds(yield_plant())
    x, _ = post(x, "receive", order="MO-1", on=date(2026, 1, 5))
    assert measured_yields(x) == []


# ---- promises that make their supply (R13) and late orders named (N110) ----------------------------------
def test_a_promise_on_new_production_makes_it_firm():
    from scp.model import DemandRecord
    from scp.promise.orders import accept
    d = base(horizon=56)
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    x, rep = accept(ds(d), DemandRecord(location="K", product="A", date=date(2026, 1, 20), qty=40, kind="sales_order"))
    assert any(line.method in ("ctp", "rlt") for line in rep.promise.lines)
    made = [f for f in rep.firmed if f.kind == "production"]
    assert made and sum(f.qty for f in made) >= 30                    # 10 in stock, 30 or more made
    assert "Made firm for it" in rep.message
    # the transfer to the customer is a delivery, not firmed
    assert not [f for f in rep.firmed if f.location == "K"]


def test_a_short_receipt_says_when_the_rest_comes_for_an_order_it_leaves_late():
    from scp.actuals import post
    from .test_stock import plant
    d = plant()
    d["receipts"].append({"id": "PO-00002", "kind": "purchase", "location": "P", "product": "B", "qty": 50,
                          "due_date": "2026-01-15", "source": "PIR-B"})
    x = ds(d)
    x, rep = post(x, "receive", order="PO-00001", qty=85, on=date(2026, 1, 4), final=True)
    s = rep.short_orders[0]
    assert (s.order, s.available, s.starts, s.complete_on) == ("MO-2", 25, date(2026, 1, 8), date(2026, 1, 15))
    assert "cannot start in full on time: MO-2 (the rest on 2026-01-15)" in rep.message
    assert "can no longer run in full" not in rep.message
