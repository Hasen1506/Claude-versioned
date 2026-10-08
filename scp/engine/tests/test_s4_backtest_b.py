"""Backtest against the S/4HANA supply-chain guide, PART B: §6 order capture and scheduling, §7 advanced ATP, §8 MRP and
§9 PP/DS. Each test turns one rule, formula or worked mechanic of the guide into a hand-calculated case and runs it
through the engine. The findings matrix (what passes, what was fixed, what is out of scope) lives with the audit; the
tests marked *regression* failed on main before the fix named in their docstring.

All cases are offline and deterministic: one plant P, one bought part B from supplier S (a 3-day purchase lead time)
unless the test says otherwise, planning from Monday 2026-01-05.
"""
from __future__ import annotations

import copy
import math
from datetime import date

import pytest

from scp.inventory import ddmrp
from scp.inventory.analysis import run_inventory
from scp.model import Dataset, InventorySettings
from scp.plan import run_mrp
from scp.promise.run import run_bop, run_promise
from scp.schedule.core import OpSpec, setup_rule
from scp.validate import validate

from .factory import base, demand as fdemand, ds as make_ds

START = "2026-01-05"   # Monday
WEEKDAYS = [0, 1, 2, 3, 4]


# ------------------------------------------------------------------------------------------------ builders
def buy(*, on_hand: float = 0.0, lt: float = 3, horizon: int = 42, bucket: str = "day", workdays=None, **lp) -> dict:
    return {
        "settings": {"planning_start": START, "horizon_days": horizon, "bucket": bucket, "default_calendar": "CAL",
                     "wacc": 0.1, "holding_spread": 0.1},
        "calendars": [{"id": "CAL", "workdays": workdays or [0, 1, 2, 3, 4, 5, 6]}],
        "locations": [{"id": "P", "type": "plant"}, {"id": "S", "type": "supplier"}],
        "products": [{"id": "B", "type": "RM"}],
        "location_products": [{"location": "P", "product": "B", "on_hand": on_hand, **lp}],
        "resources": [], "production_sources": [],
        "purchasing_sources": [{"id": "PIR-B", "supplier": "S", "product": "B", "location": "P", "price": 10,
                                "lead_time_days": lt}],
        "lanes": [], "demand": [], "receipts": [],
    }


def dem(d: dict, day: str, qty: float, kind: str = "sales_order", **kw) -> str:
    rid = kw.pop("id", f"D{len(d['demand']) + 1}")
    d["demand"].append({"location": kw.pop("location", "P"), "product": "B", "date": day, "qty": qty, "kind": kind,
                        "id": rid, **kw})
    return rid


def rec(d: dict, day: str, qty: float, **kw) -> str:
    rid = kw.pop("id", f"PO{len(d['receipts']) + 1}")
    d["receipts"].append({"id": rid, "kind": "purchase", "location": "P", "product": "B", "qty": qty, "due_date": day,
                          "source": "PIR-B", **kw})
    return rid


def plan(d: dict):
    res = run_mrp(Dataset.model_validate(copy.deepcopy(d)))
    assert res.ok, res.issues
    return res


def orders(res, product: str = "B"):
    return sorted((o for o in res.orders if o.product == product), key=lambda o: (o.need_date, o.id))


def codes(res) -> list[str]:
    return [e.code for e in res.exceptions]


def promising(d: dict, **cfg) -> dict:
    """Scope of check: stock and firm receipts only, no planned orders, no capable-to-promise (the classic check)."""
    d["location_products"][0]["mrp_type"] = "none"
    d["promising"] = {"include_planned_orders": False, "confirm_beyond_rlt": False, "ctp": False, **cfg}
    return d


def lines(o) -> list[tuple[str, float, str]]:
    return [(x.ship_date.isoformat(), round(x.qty, 6), x.method) for x in o.lines]


def by_order(res) -> dict:
    return {o.order: o for o in res.orders}


# ================================================================================================ §8.1 net requirements
def test_net_requirements_formula_with_safety_stock_and_scheduled_receipt():
    """§8.1: AvailQty(d) = AvailQty(d−1) + Receipts(d) − Requirements(d); a shortage exists when AvailQty < SafetyStock
    and the shortage quantity SafetyStock − AvailQty is what lot sizing works on.
    100 on hand, SS 20, −50 on 8 Jan, +30 (PO) on 13 Jan, −70 on 15 Jan: 100 → 50 → 80 → 10 < 20, shortage 10."""
    d = buy(on_hand=100, safety_stock={"method": "fixed", "qty": 20})
    dem(d, "2026-01-08", 50)
    rec(d, "2026-01-13", 30)
    dem(d, "2026-01-15", 70)
    [o] = orders(plan(d))
    assert (o.qty, o.need_date) == (10, date(2026, 1, 15))
    assert o.for_buffer == pytest.approx(10)          # all of it restores the safety stock: stock stays ≥ 0 anyway
    # one unit less demand: AvailQty = 20 = SafetyStock is not a shortage
    d["demand"][-1]["qty"] = 60
    assert orders(plan(d)) == []


def test_safety_stock_is_untouchable_demand_before_any_requirement():
    """§8.1: safety stock is treated as demand: 5 on hand against SS 20 is a 15 shortage on day one."""
    d = buy(on_hand=5, safety_stock={"method": "fixed", "qty": 20})
    [o] = orders(plan(d))
    assert o.qty == pytest.approx(15) and o.need_date == date(2026, 1, 5)


def test_safety_time_counts_working_days_regression():
    """Regression (S4-B2). §8.1: safety time 'shifts requirement dates earlier by n WORK days'. A Monday 19 Jan
    requirement with two days of safety time on a Monday–Friday calendar is due Thursday 15 Jan. Before the fix it
    went two calendar days back, to Saturday 17 Jan, a day the plant is closed."""
    d = buy(workdays=WEEKDAYS, safety_time_days=2)
    dem(d, "2026-01-19", 10)
    [o] = orders(plan(d))
    assert o.need_date == date(2026, 1, 15)
    assert o.available_date == date(2026, 1, 15)


def test_safety_stock_and_safety_time_together_are_flagged_as_double_buffer():
    """§8.1: 'combining both double-buffers': the readiness check says so."""
    d = buy(safety_time_days=2, safety_stock={"method": "fixed", "qty": 5})
    assert "SS_AND_SAFETY_TIME" in [i.code for i in validate(Dataset.model_validate(d))]


def test_coverage_profile_breathes_with_demand():
    """§8.1 coverage profile (dynamic safety stock): the buffer is the requirements of the next N days from each
    bucket's start, so it moves with demand. Weekly buckets, 7 days of cover, 70 due in week 2 and 140 in week 3: the
    buffer is 0, 70, 140, 0."""
    d = buy(bucket="week", horizon=28, safety_stock={"method": "days_of_supply", "days": 7})
    for k in range(7):
        dem(d, f"2026-01-{12 + k:02d}", 10, kind="forecast")
        dem(d, f"2026-01-{19 + k:02d}", 20, kind="forecast")
    nb = plan(d).nodes[0].buckets
    assert [round(b.safety_stock) for b in nb] == [0, 70, 140, 0]


def test_firm_receipt_keeps_its_date_and_reschedule_in_is_proposed():
    """§8.1 firmed receipts are never moved by MRP; within the rescheduling check MRP proposes 'reschedule in'
    (exception 10) rather than a duplicate order when a new order could not arrive sooner (10-day lead time)."""
    d = buy(lt=10)
    dem(d, "2026-01-08", 50)
    rec(d, "2026-01-12", 50)
    res = plan(d)
    assert orders(res) == []                                           # no duplicate supply
    assert "RESCHEDULE_IN" in codes(res)
    assert [r.date for r in res.receipts] == [date(2026, 1, 12)]   # the receipt itself is not moved


def test_reschedule_out_and_cancel_proposals_regression():
    """Regression (S4-B3). §8.1/§8.6: exceptions 15 (reschedule out) and 20 (cancel process). Before the fix a firm
    receipt nothing needs, or one arriving three weeks before it is needed, produced no message at all."""
    d = buy()
    rec(d, "2026-01-10", 50)
    res = plan(d)
    [e] = [e for e in res.exceptions if e.code == "RECEIPT_NOT_NEEDED"]
    assert e.order_id == "PO1"

    d = buy()
    rec(d, "2026-01-07", 50)
    dem(d, "2026-01-30", 50)
    [e] = [e for e in plan(d).exceptions if e.code == "RESCHEDULE_OUT"]
    assert (e.order_id, e.date) == ("PO1", date(2026, 1, 30))
    assert "by 23 d" in e.message


def test_reschedule_out_respects_tolerance_and_safety_stock():
    """A receipt two days early stays (tolerance); one that holds the stock at safety stock is needed now."""
    d = buy()
    rec(d, "2026-01-13", 50)
    dem(d, "2026-01-15", 50)
    assert not {"RESCHEDULE_OUT", "RECEIPT_NOT_NEEDED"} & set(codes(plan(d)))
    d = buy(on_hand=10, safety_stock={"method": "fixed", "qty": 20})
    rec(d, "2026-01-07", 10)
    dem(d, "2026-01-30", 5)
    assert not {"RESCHEDULE_OUT", "RECEIPT_NOT_NEEDED"} & set(codes(plan(d)))


# ================================================================================================ §8.2 MRP types
def test_no_planning_type_creates_nothing():
    """§8.2 ND: excluded from MRP; a shortage is projected but never replenished."""
    d = buy(mrp_type="none")
    dem(d, "2026-01-10", 10)
    res = plan(d)
    assert orders(res) == []
    assert "STOCKOUT" in codes(res)


def test_reorder_point_triggers_below_the_reorder_point():
    """§8.2 VB: 50 on hand, reorder point 20. Taking 30 leaves exactly 20, no order (SAP orders when stock falls
    BELOW the reorder point; the guide's '≤' is looser than SAP); taking 31 leaves 19 and orders up to 20."""
    d = buy(on_hand=50, mrp_type="reorder_point", reorder_point=20)
    dem(d, "2026-01-10", 30)
    assert orders(plan(d)) == []
    d["demand"][0]["qty"] = 31
    [o] = orders(plan(d))
    assert o.qty == pytest.approx(1)


# ================================================================================================ §8.3 lot sizing
def test_lot_for_lot_orders_exactly_the_shortage():
    d = buy(lot_sizing={"policy": "L4L"})
    dem(d, "2026-01-15", 37)
    assert [o.qty for o in orders(plan(d))] == [37]


def test_fixed_lot_size_repeats_the_lot_regression():
    """Regression (S4-B1). §8.3: 'FX = repeated fixed lots until covered'. A shortage of 120 in fixed lots of 50 is
    three orders of 50 (three batches, three order costs), not one order of 150 as before the fix."""
    d = buy(lot_sizing={"policy": "FIXED", "fixed_qty": 50})
    dem(d, "2026-01-15", 120)
    os_ = orders(plan(d))
    assert [o.qty for o in os_] == [50, 50, 50]
    assert sum(o.for_lot_size for o in os_) == pytest.approx(30)


def test_fixed_lot_applies_rounding_to_the_lot_itself():
    """A fixed lot of 50 with a supplier rounding of 20 becomes lots of 60 (the lot is rounded, then repeated)."""
    d = buy(lot_sizing={"policy": "FIXED", "fixed_qty": 50})
    d["purchasing_sources"][0]["rounding_qty"] = 20
    dem(d, "2026-01-15", 100)
    assert [o.qty for o in orders(plan(d))] == [60, 60]


def test_replenish_to_maximum_stock():
    """§8.3 HB, the min/max policy: 50 on hand, −60 on 15 Jan, SS 10, max stock 200: available −10 → the order brings
    stock back to 200, so 200 − (−10) = 210."""
    d = buy(on_hand=50, max_stock=200, lot_sizing={"policy": "MIN_MAX"}, safety_stock={"method": "fixed", "qty": 10})
    dem(d, "2026-01-15", 60)
    [o] = orders(plan(d))
    assert o.qty == pytest.approx(210)


def test_periodic_lot_groups_the_bucket():
    """§8.3 periodic (WB): weekly buckets, one period per order: Tue/Wed/Fri of week 2 → one order of 30 on the first
    requirement date (period start of the shortage); week 3's 10 is its own order."""
    d = buy(bucket="week", horizon=28, lot_sizing={"policy": "POQ", "periods": 1})
    for day in ("2026-01-13", "2026-01-14", "2026-01-16", "2026-01-20"):
        dem(d, day, 10)
    assert [(o.qty, o.need_date) for o in orders(plan(d))] == [(30, date(2026, 1, 13)), (10, date(2026, 1, 20))]


def test_economic_order_quantity_by_hand():
    """§8.3 optimising family (EOQ): √(2·D·S/H). 10 a day for the whole 28-day horizon → D = 3650 a year, S = 100 per
    order, H = 10 × (0.1 wacc + 0.1 spread) = 2 a year → EOQ = √(2·3650·100/2) = 604.15, ordered as 605 whole units
    (a part counted in each is never ordered as a fraction)."""
    d = buy(horizon=28, lot_sizing={"policy": "EOQ", "ordering_cost": 100})
    for k in range(28):
        day = date.fromordinal(date(2026, 1, 5).toordinal() + k).isoformat()
        dem(d, day, 10, kind="forecast")
    first = orders(plan(d))[0]
    assert first.qty == math.ceil(math.sqrt(2 * 3650 * 100 / 2))


def test_minimum_then_rounding():
    """§8.3 modifiers after the base: 32 → minimum 30 keeps 32 → rounding value 25 → 50."""
    d = buy(lot_sizing={"policy": "L4L", "min_qty": 30, "rounding_qty": 25})
    dem(d, "2026-01-15", 32)
    assert [o.qty for o in orders(plan(d))] == [50]


def test_maximum_lot_splits_into_several_orders_on_the_same_date():
    """§8.3: 'Max lot size splits one requirement into several orders on the same date — expected'."""
    d = buy(lot_sizing={"policy": "L4L", "max_qty": 40})
    dem(d, "2026-01-15", 100)
    os_ = orders(plan(d))
    assert [o.qty for o in os_] == [40, 40, 20]
    assert {o.need_date for o in os_} == {date(2026, 1, 15)}


# ================================================================================================ §8.5 firming / dates
def test_backward_scheduling_and_forward_from_today():
    """Fig. 8.1 ⑤: backward from the requirement date (start = 15 Jan − 3 d = 12 Jan); when that start would be in the
    past, forward from today (exception 06 'start date in the past')."""
    d = buy()
    dem(d, "2026-01-15", 10)
    [o] = orders(plan(d))
    assert (o.start_date, o.available_date) == (date(2026, 1, 12), date(2026, 1, 15))
    d = buy(lt=10)
    dem(d, "2026-01-08", 10)
    res = plan(d)
    [o] = orders(res)
    assert (o.start_date, o.available_date, o.start_in_past) == (date(2026, 1, 5), date(2026, 1, 15), True)
    assert "START_IN_PAST" in codes(res)


def test_planning_time_fence_shifts_new_proposals_to_the_fence_end():
    """§8.5 firming type 1: inside a 10-day fence no new proposal; the requirement of 8 Jan is covered at the fence end
    (15 Jan, late) and the move is reported."""
    d = buy(lt=1, planning_time_fence_days=10)
    dem(d, "2026-01-08", 10)
    res = plan(d)
    [o] = orders(res)
    assert o.fence_shifted and o.available_date == date(2026, 1, 15)
    assert "FENCE_SHIFT" in codes(res)


# ================================================================================================ §8.6 exceptions
def test_exception_triggers():
    """§8.6: 96 below safety stock, 26 excess stock, 53 no source (≈ no production version / source)."""
    d = buy(on_hand=5, lt=10, safety_stock={"method": "fixed", "qty": 20})
    assert "BELOW_SAFETY_STOCK" in codes(plan(d))
    d = buy(on_hand=150, max_stock=100)
    assert "EXCESS_STOCK" in codes(plan(d))
    d = buy()
    d["purchasing_sources"][0]["valid_to"] = "2026-01-10"     # the only source ends before it is needed
    dem(d, "2026-01-20", 10)
    assert "NO_VALID_SOURCE" in codes(plan(d))


# ================================================================================================ fig. 8.1 ⑥ explosion
def test_dependent_requirements_from_the_parent_planned_order():
    """Fig. 8.1 ⑥: the parent is planned first (low-level code); its planned order explodes 2 B and 1 C per A, dated on
    the order's start."""
    d = base()
    d["demand"].append(fdemand("P", "A", "2026-01-20", 30, kind="sales_order"))
    res = run_mrp(make_ds(d))
    [mo] = [o for o in res.orders if o.product == "A"]
    deps = {r.product: r for r in res.requirements if r.parent_order == mo.id}
    assert deps["B"].qty == pytest.approx(2 * mo.qty) and deps["C"].qty == pytest.approx(mo.qty)
    assert deps["B"].date == mo.start_date


# ================================================================================================ §8.7 DDMRP
def test_ddmrp_zone_math_by_hand():
    """§8.7 (Ptak & Smith): ADU 10, DLT 10 d (short → LTF 0.7), weekly CV 0.2 (low → VF 0.25), order cycle 7 d.
    red base 70, red safety 17.5 → TOR 87.5; yellow 100 → TOY 187.5; green max(70, 70, 0) = 70 → TOG 257.5.
    Net flow 150 is yellow and orders up to the top of green: 107.5."""
    b = ddmrp.size(10, 10, 0.2, 0, InventorySettings())
    assert (b.red, b.yellow, b.green) == pytest.approx((87.5, 100, 70))
    assert (b.tor, b.toy, b.tog) == pytest.approx((87.5, 187.5, 257.5))
    assert (ddmrp.zone(150, b), ddmrp.order_qty(150, b)) == ("yellow", pytest.approx(107.5))
    assert (ddmrp.zone(200, b), ddmrp.order_qty(200, b)) == ("green", 0)
    assert ddmrp.zone(87.5, b) == "red"


def test_ddmrp_net_flow_counts_what_released_orders_reserve_regression():
    """Regression (S4-B5). §8.7: net flow = on hand + on order − qualified demand. A released production order that
    still draws 40 B today is qualified demand on the buffered part B: before the fix the net flow ignored it and showed
    those 40 as free stock."""
    d = base()
    for x in d["location_products"]:
        if x["product"] == "B":
            x.update(ddmrp_buffer=True, on_hand=100)
    d["receipts"].append({"id": "MO1", "kind": "production", "location": "P", "product": "A", "qty": 20,
                          "due_date": "2026-01-08", "source": "PV-A",
                          "reservations": [{"location": "P", "product": "B", "date": START, "qty": 40}]})
    row = next(r for r in run_inventory(make_ds(d), time_limit=5).ddmrp if r.product == "B")
    assert row.qualified_demand == pytest.approx(40)
    assert row.nfp == pytest.approx(100 + row.open_supply - 40)


# ================================================================================================ §7.1 classic ATP
def test_cumulative_atp_protects_a_later_promise():
    """§7.1 ATP(d) = Σ inflows(≤ d) − Σ outflows(≤ d), checked with look-ahead so a new order cannot take what an
    earlier-entered later order holds. 100 on hand, +30 on 13 Jan; D1 (entered first) wants 80 on 15 Jan, D2 wants 70
    on 10 Jan: on 10 Jan only min(100, 130, 130 − 80) = 50 is free, and no later date frees more (130 in, 130 promised).
    The guide's formula without the look-ahead would show 100 free on 10 Jan and break D1's promise."""
    d = promising(buy(on_hand=100, lt=30))
    dem(d, "2026-01-15", 80)
    dem(d, "2026-01-10", 70)
    rec(d, "2026-01-13", 30)
    o = by_order(run_promise(Dataset.model_validate(d)))
    assert lines(o["D1"]) == [("2026-01-15", 80, "atp")]
    assert lines(o["D2"]) == [("2026-01-10", 50, "atp")]
    assert o["D2"].unconfirmed == 20


def test_partial_versus_complete_delivery():
    """Fig. 7.1: partial allowed → split schedule lines; complete delivery → one line on the first date the full
    quantity exists. 60 on hand, +60 on 20 Jan, order of 100 for 10 Jan."""
    d = promising(buy(on_hand=60, lt=30))
    dem(d, "2026-01-10", 100)
    rec(d, "2026-01-20", 60)
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert lines(o) == [("2026-01-10", 60, "atp"), ("2026-01-20", 40, "atp")]
    d["demand"][0]["complete_delivery"] = True
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert lines(o) == [("2026-01-20", 100, "atp")]


def test_replenishment_lead_time_confirms_unconditionally_beyond_it():
    """§7.1 ②: with the RLT check, beyond today + RLT everything is confirmed (30-day purchase → 4 Feb); without it the
    rest stays unconfirmed, a backorder for BOP."""
    d = promising(buy(on_hand=100, lt=30), confirm_beyond_rlt=True)
    dem(d, "2026-01-10", 150)
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert lines(o) == [("2026-01-10", 100, "atp"), ("2026-02-04", 50, "rlt")]
    d["promising"]["confirm_beyond_rlt"] = False
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert (o.confirmed, o.unconfirmed, o.status) == (100, 50, "partial")


# ================================================================================================ §7.4 product allocation
def test_allocation_caps_confirmation_at_min_of_atp_and_allocation():
    """§7.4: confirmable = min(ATP, remaining allocation). 100 in stock, 30 allocated for the week of 5 Jan and 50 for
    the next: an order of 60 gets 30 now and 30 in the next period (fallback next period), or only 30 (reject)."""
    d = promising(buy(on_hand=100, lt=60))
    d["allocations"] = [{"id": "W1", "product": "B", "start": "2026-01-05", "end": "2026-01-12", "qty": 30},
                        {"id": "W2", "product": "B", "start": "2026-01-12", "end": "2026-01-19", "qty": 50}]
    dem(d, "2026-01-07", 60)
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert lines(o) == [("2026-01-07", 30, "atp"), ("2026-01-12", 30, "atp")]
    d["allocations"][0]["fallback"] = "reject"
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert lines(o) == [("2026-01-07", 30, "atp")]


def test_allocation_without_a_period_confirms_nothing():
    """§7.4 failure mode, reproduced on purpose: a combination with allocations but no quantity in the periods the
    order can reach confirms zero, although stock exists ('looks like a stock problem, is not'); the result says the
    allocation capped it. With a later period that has quantity, the order is confirmed there (late)."""
    d = promising(buy(on_hand=100, lt=60))
    d["allocations"] = [{"id": "W1", "product": "B", "start": "2026-01-05", "end": "2026-01-12", "qty": 0,
                         "fallback": "reject"}]
    dem(d, "2026-01-07", 10)
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert (o.confirmed, o.allocation_capped) == (0, 10)
    d["allocations"] = [{"id": "MAR", "product": "B", "start": "2026-03-02", "end": "2026-03-09", "qty": 30}]
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert lines(o) == [("2026-03-02", 10, "atp")]


# ================================================================================================ §7.3 BOP
def _bop_case(segments: list[dict]) -> dict:
    d = promising(buy(on_hand=100, lt=60), bop_segments=segments)
    return d


def test_bop_cascade_as_in_figure_7_2():
    """Fig. 7.2: segments claim supply in sequence. 100 in stock. Key account (WIN) wants 50 and held 0; contracted
    (FILL) held 30 of 40; standard (REDISTRIBUTE) held 40 of 40; internal (LOSE) held 30 of 30.
    WIN takes 50 from what is free and what LOSE/REDISTRIBUTE give back; FILL keeps its 30 and tops up from leftovers;
    REDISTRIBUTE gets what is left; LOSE gets nothing new."""
    d = _bop_case([{"name": "Key", "priorities": [1], "strategy": "win"},
                   {"name": "Contracted", "priorities": [2], "strategy": "fill"},
                   {"name": "Standard", "priorities": [5], "strategy": "redistribute"},
                   {"name": "Internal", "priorities": [9], "strategy": "lose"}])
    dem(d, "2026-01-10", 50, priority=1, id="KEY")
    dem(d, "2026-01-10", 40, priority=2, id="CON")
    dem(d, "2026-01-10", 40, priority=5, id="STD")
    dem(d, "2026-01-10", 30, priority=9, id="INT")
    d["confirmations"] = [{"order": "CON", "ship_from": "P", "ship_date": "2026-01-10", "date": "2026-01-10", "qty": 30},
                          {"order": "STD", "ship_from": "P", "ship_date": "2026-01-10", "date": "2026-01-10", "qty": 40},
                          {"order": "INT", "ship_from": "P", "ship_date": "2026-01-10", "date": "2026-01-10", "qty": 30}]
    o = by_order(run_bop(Dataset.model_validate(d)))
    # supply 100: CON's 30 is held; KEY takes 50 of the other 70; CON tops up 10; STD gets the last 10; INT nothing
    assert (o["KEY"].confirmed, o["CON"].confirmed, o["STD"].confirmed, o["INT"].confirmed) == (50, 40, 10, 0)


@pytest.mark.parametrize("strategy", ["win", "gain", "fill"])
def test_bop_no_lose_strategy_keeps_its_confirmation_after_a_redistribute_segment_regression(strategy):
    """Regression (S4-B4). §7.3: Win, Gain and Fill 'may lose? No'. The guide places Gain 'later in the sequence', so a
    no-lose segment may come after a Redistribute one. Before the fix the earlier Redistribute order took the supply the
    protected order held, and the protected order lost all of it."""
    d = _bop_case([{"name": "Standard", "priorities": [5], "strategy": "redistribute"},
                   {"name": "Protected", "priorities": [2], "strategy": strategy}])
    dem(d, "2026-01-10", 100, priority=5, id="STD")
    dem(d, "2026-01-12", 100, priority=2, id="VIP")
    d["confirmations"] = [{"order": "VIP", "ship_from": "P", "ship_date": "2026-01-12", "date": "2026-01-12",
                           "qty": 100}]
    res = run_bop(Dataset.model_validate(d))
    o = by_order(res)
    assert o["VIP"].confirmed == 100 and o["STD"].confirmed == 0
    assert {b.order: b.outcome for b in res.bop}["VIP"] != "lost"


def test_bop_lose_strategy_never_gains():
    d = _bop_case([{"name": "Internal", "priorities": [9], "strategy": "lose"}])
    dem(d, "2026-01-10", 80, priority=9, id="INT")
    d["confirmations"] = [{"order": "INT", "ship_from": "P", "ship_date": "2026-01-10", "date": "2026-01-10", "qty": 20}]
    [o] = run_bop(Dataset.model_validate(d)).orders
    assert o.confirmed == 20


# ================================================================================================ §6.2 scheduling
def _customer(d: dict, transit: float = 3) -> dict:
    d["locations"].append({"id": "CU", "type": "customer"})
    d["lanes"].append({"id": "L1", "origin": "P", "destination": "CU", "modes": [{"transit_days": transit}]})
    return d


def test_backward_scheduling_from_the_requested_delivery_date():
    """Fig. 6.2: the ship (goods-issue) date is scheduled back from the requested delivery date by the transit time:
    delivery 20 Jan, 3 days on the road → ship 17 Jan, delivered on the requested date."""
    d = _customer(promising(buy(on_hand=100, lt=30)))
    dem(d, "2026-01-20", 10, location="CU")
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert [(x.ship_date, x.date) for x in o.lines] == [(date(2026, 1, 17), date(2026, 1, 20))]
    assert o.status == "on_time"


def test_forward_scheduling_when_the_date_is_past_and_says_why_regression():
    """Regression (S4-B6). Fig. 6.2 + note: a computed date in the past switches to forward scheduling from today and
    returns a later confirmed delivery date; 'the fix is completely different' for a lead-time cause than for a stock
    cause. Delivery wanted 6 Jan, 3 days transit: shipped today (5 Jan) it arrives 8 Jan, with stock to spare. Before
    the fix the late confirmation came with no reason at all, so it read as a stock problem."""
    d = _customer(promising(buy(on_hand=100, lt=30)))
    dem(d, "2026-01-06", 10, location="CU")
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert [(x.ship_date, x.date) for x in o.lines] == [(date(2026, 1, 5), date(2026, 1, 8))]
    assert o.status == "late"
    assert "Not a stock shortage" in o.reason and "2026-01-08" in o.reason


# ================================================================================================ §9 PP/DS
def _op(product: str, group: str, setup: float = 2.0) -> OpSpec:
    return OpSpec(key=f"{product}:10", order=product, seq=10, resource="R", product=product, group=group, qty=1,
                  setup=setup, run=1.0)


def test_setup_matrix_sequence_dependent_and_asymmetric():
    """§9.2: setup groups and a matrix of transition times between them (light → dark is short, dark → light needs a
    full clean). Same product: no setup; same group: the minor share; first on the machine: full setup."""
    fn = setup_rule({(None, "LIGHT", "DARK"): 0.5, (None, "DARK", "LIGHT"): 3.0, ("R", "DARK", "LIGHT"): 4.0}, 0.25)
    assert fn("R", None, _op("X", "LIGHT")) == 2.0
    assert fn("R", ("X", "LIGHT"), _op("X", "LIGHT")) == 0.0
    assert fn("R", ("Y", "LIGHT"), _op("X", "LIGHT")) == 0.5            # 0.25 × 2 h
    assert fn("R", ("X", "LIGHT"), _op("Z", "DARK")) == 0.5
    assert fn("R", ("Z", "DARK"), _op("X", "LIGHT")) == 4.0             # the resource's own matrix wins
    assert fn("R2", ("Z", "DARK"), _op("X", "LIGHT")) == 3.0


def test_dynamic_pegging_is_first_in_first_out():
    """§9.2 dynamic pegging: receipts are linked to requirements by date; stock covers the earliest requirement."""
    d = buy(on_hand=30)
    first = dem(d, "2026-01-08", 30)
    second = dem(d, "2026-01-15", 20)
    res = plan(d)
    pegs = {(p.requirement_id.split(":")[-1], p.supply_kind) for p in res.pegs}
    assert (first, "on_hand") in pegs and (second, "order") in pegs


def test_an_early_receipt_is_priced_for_the_days_it_comes_early():
    """The inbox prices a reschedule-out at the carrying cost of the days it is early, not a year of excess stock."""
    import datetime as dt

    from scp.tower.money import price_items
    from scp.tower.result import WorkItem

    data = Dataset.model_validate(buy())
    msg = "PO1: arrives 2026-01-07 but is first needed 2026-01-30; push it out by 23 d"
    w = WorkItem(id="k", key="k", code="RESCHEDULE_OUT", category="orders", severity="warning", message=msg,
                 location="P", product="B", order_id="PO1", qty=50, owner="Unassigned", owner_source="default",
                 status="open", first_seen=dt.date(2026, 1, 5), last_seen=dt.date(2026, 1, 5))
    price_items(data, None, [w])
    assert w.money_at_risk == pytest.approx(round(50 * 10 * 0.2 * 23 / 365, 2))
    assert w.action is not None and w.action.kind == "push_out"
