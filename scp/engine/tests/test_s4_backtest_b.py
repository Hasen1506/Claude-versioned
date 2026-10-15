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
from datetime import date, timedelta

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



def test_late_firm_order_without_a_horizon_is_duplicated_by_a_new_one():
    """The defect ENTERPRISE_PLAN 2.1 names, as the plan still behaves with no rescheduling horizon (the company's
    default, as in S/4 when none is set): a 3-day lead time could bring a new order on time, so a PO due a week late
    gets a requisition beside it, and the PO itself is reported as not needed."""
    d = buy()
    dem(d, "2026-01-12", 50)
    rec(d, "2026-01-19", 50)
    res = plan(d)
    [o] = orders(res)
    assert (o.qty, o.need_date) == (50, date(2026, 1, 12))
    assert "RECEIPT_NOT_NEEDED" in codes(res)


def test_rescheduling_horizon_brings_a_late_firm_order_in_before_new_supply():
    """ENTERPRISE_PLAN 2.1, §8.1: within the rescheduling horizon a firm receipt is proposed for 'reschedule in'
    (exception 10) and no new order is planned; beyond the horizon, new supply. Monday–Friday calendar, need on Monday
    12 Jan, PO due Monday 19 Jan: five working days later (13, 14, 15, 16, 19 Jan)."""
    d = buy(workdays=WEEKDAYS)
    d["settings"]["rescheduling_horizon_days"] = 5
    dem(d, "2026-01-12", 50)
    rec(d, "2026-01-19", 50)
    res = plan(d)
    assert orders(res) == []
    [e] = [e for e in res.exceptions if e.code == "RESCHEDULE_IN"]
    assert (e.order_id, e.date, e.qty) == ("PO1", date(2026, 1, 12), 50)
    assert "expedite it by 7 d" in e.message and "5-working-day rescheduling horizon" in e.message
    assert "RECEIPT_NOT_NEEDED" not in codes(res)
    assert [r.date for r in res.receipts] == [date(2026, 1, 19)]   # advice only: the PO keeps its date
    # four working days are one short of the PO: a new order on time, and the PO is not needed
    d["settings"]["rescheduling_horizon_days"] = 4
    res = plan(d)
    assert [(o.qty, o.need_date) for o in orders(res)] == [(50, date(2026, 1, 12))]
    assert "RESCHEDULE_IN" not in codes(res)


def test_rescheduling_horizon_takes_only_what_the_shortage_needs():
    """Two firm orders inside the horizon: the earlier one covers the shortage, the later one keeps its date and is
    checked the other way as usual."""
    d = buy()
    d["settings"]["rescheduling_horizon_days"] = 10
    dem(d, "2026-01-08", 40)
    rec(d, "2026-01-10", 40, id="PO-A")
    rec(d, "2026-01-14", 40, id="PO-B")
    dem(d, "2026-01-20", 40)
    res = plan(d)
    assert orders(res) == []
    assert [e.order_id for e in res.exceptions if e.code == "RESCHEDULE_IN"] == ["PO-A"]
    [e] = [e for e in res.exceptions if e.code == "RESCHEDULE_OUT"]
    assert (e.order_id, e.date) == ("PO-B", date(2026, 1, 20))


def test_rescheduling_horizon_and_tolerance_by_product_and_mrp_group():
    """A product's own horizon and tolerance win over the company's; an MRP group's win over the product's."""
    d = buy(rescheduling_horizon_days=10)
    dem(d, "2026-01-12", 50)
    rec(d, "2026-01-19", 50)
    assert orders(plan(d)) == []
    d["location_products"][0]["rescheduling_horizon_days"] = 0       # the product says none, over the company's 10
    d["settings"]["rescheduling_horizon_days"] = 10
    assert len(orders(plan(d))) == 1
    d["mrp_groups"] = [{"id": "G", "rescheduling_horizon_days": 7}]
    d["location_products"][0]["mrp_group"] = "G"
    assert orders(plan(d)) == []

    # tolerance: 6 days early is left alone at 7, reported at the company's 3
    d = buy()
    rec(d, "2026-01-09", 50)
    dem(d, "2026-01-15", 50)
    assert "RESCHEDULE_OUT" in codes(plan(d))
    d["settings"]["reschedule_out_tolerance_days"] = 7
    assert "RESCHEDULE_OUT" not in codes(plan(d))
    d["settings"]["reschedule_out_tolerance_days"] = 3
    d["mrp_groups"] = [{"id": "G", "reschedule_out_tolerance_days": 6}]
    d["location_products"][0]["mrp_group"] = "G"
    assert "RESCHEDULE_OUT" not in codes(plan(d))


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
    """§8.5 firming types 1 and 3 (3 is the default): inside a 10-day fence no new proposal; the requirement of 8 Jan
    is covered at the fence end (15 Jan, late) and the move is reported."""
    d = buy(lt=1, planning_time_fence_days=10)
    dem(d, "2026-01-08", 10)
    res = plan(d)
    [o] = orders(res)
    assert o.fence_shifted and o.available_date == date(2026, 1, 15)
    assert "FENCE_SHIFT" in codes(res)



def test_firming_type_2_plans_nothing_inside_the_fence_and_reports_the_shortage():
    """ENTERPRISE_PLAN 2.3, §8.5 firming types 2 and 4: inside a 10-day fence no order at all, not even one moved to
    its end; the shortage is reported, and the first check beyond the fence (15 Jan, daily buckets) covers it together
    with what is needed then."""
    for ft in (2, 4):
        d = buy(lt=1, planning_time_fence_days=10, firming_type=ft)
        dem(d, "2026-01-08", 10)
        dem(d, "2026-01-20", 5)
        res = plan(d)
        assert [(o.qty, o.need_date, o.fence_shifted) for o in orders(res)] == [
            (10, date(2026, 1, 15), False), (5, date(2026, 1, 20), False)]
        [e] = [e for e in res.exceptions if e.code == "FENCE_SHORTAGE"]
        assert (e.date, e.qty) == (date(2026, 1, 8), 10)
        assert f"firming type {ft} plans no new order there" in e.message
        assert "FENCE_SHIFT" not in codes(res)
    # an MRP group can say it for many products
    d = buy(lt=1, planning_time_fence_days=10, mrp_group="G")
    d["mrp_groups"] = [{"id": "G", "firming_type": 2}]
    dem(d, "2026-01-08", 10)
    assert "FENCE_SHORTAGE" in codes(plan(d))


def test_firming_types_1_and_2_firm_the_fence_when_the_week_rolls():
    """ENTERPRISE_PLAN 2.3, §8.5 automatic firming: rolling to Monday 12 Jan, the planned orders that start inside the
    product's 7-day fence (to 19 Jan) are firmed as last week's plan had them: the order for 16 Jan (1-day lead time)
    becomes a purchase order due on the 16th, not one moved to the new fence end; the one for 30 Jan, outside the
    fence, stays planned. Firming types 3 and 4 leave both to the planner."""
    from scp.actuals.roll import roll_forward

    def company(ft: int) -> Dataset:
        d = buy(lt=1, planning_time_fence_days=7, firming_type=ft)
        dem(d, "2026-01-16", 10, kind="forecast")
        dem(d, "2026-01-30", 20, kind="forecast")
        return Dataset.model_validate(d)

    for ft in (1, 2):
        new, rep = roll_forward(company(ft), date(2026, 1, 12))
        assert rep.ok
        assert [(f.kind, f.qty, f.planned_id.startswith("PR-")) for f in rep.firmed] == [("purchase", 10, True)]
        assert len(rep.purchase_orders) == 1
        assert [(r.kind.value, r.qty, r.due_date) for r in new.receipts] == [("purchase", 10, date(2026, 1, 16))]
        assert [(o.qty, o.need_date) for o in orders(run_mrp(new))] == [(20, date(2026, 1, 30))]
    for ft in (3, 4):
        new, rep = roll_forward(company(ft), date(2026, 1, 12))
        assert rep.firmed == [] and new.receipts == []



def test_fence_and_goods_receipt_time_count_working_days_when_the_company_says_so():
    """ENTERPRISE_PLAN 2.3: S/4 counts the planning time fence and the goods-receipt time in working days. Monday–Friday
    plant, planning from Monday 5 Jan. A 5-day fence ends Saturday 10 Jan in calendar days, Monday 12 Jan in working
    days. Two days of goods receipt after a PO arrives on Friday 9 Jan: Sunday 11 Jan in calendar days, Tuesday 13 Jan
    in working days. Off (saved companies) nothing moves."""
    d = buy(lt=1, workdays=WEEKDAYS, planning_time_fence_days=5)
    dem(d, "2026-01-07", 10)
    shift = lambda res: [e.message for e in res.exceptions if e.code == "FENCE_SHIFT"]  # noqa: E731
    assert shift(plan(d)) == ["PR-00001 moved to the planning time fence end 2026-01-10"]
    d["settings"]["working_day_fences"] = True
    assert shift(plan(d)) == ["PR-00001 moved to the planning time fence end 2026-01-12"]

    d = promising(buy(lt=30, workdays=WEEKDAYS, gr_processing_days=2))
    rec(d, "2026-01-09", 50)
    dem(d, "2026-01-12", 10)
    assert [x.ship_date for x in run_promise(Dataset.model_validate(d)).orders[0].lines] == [date(2026, 1, 12)]
    d["settings"]["working_day_fences"] = True
    assert [x.ship_date for x in run_promise(Dataset.model_validate(d)).orders[0].lines] == [date(2026, 1, 13)]

    # placed on Friday 9 Jan (the buyers' working day), delivered Saturday 10 Jan: two days of goods receipt make it
    # Monday 12 Jan in calendar days, Tuesday 13 Jan in working days
    d = buy(lt=1, workdays=WEEKDAYS, gr_processing_days=2)
    dem(d, "2026-01-14", 10)
    [o] = orders(plan(d))
    assert (o.due_date, o.available_date) == (date(2026, 1, 10), date(2026, 1, 12))
    d["settings"]["working_day_fences"] = True
    [o] = orders(plan(d))
    assert (o.due_date, o.available_date) == (date(2026, 1, 10), date(2026, 1, 13))


def test_automatic_firming_keeps_last_weeks_fence_in_working_days():
    """Rolling a week with a fence of 5 working days (Monday–Friday): last week's fence ended Monday 12 Jan, this
    week's ends Monday 19 Jan. An order for Wednesday 14 Jan is firmed on its own date, not moved to the 19th."""
    from scp.actuals.roll import roll_forward

    d = buy(lt=1, workdays=WEEKDAYS, planning_time_fence_days=5, firming_type=1)
    d["settings"]["working_day_fences"] = True
    dem(d, "2026-01-14", 10, kind="forecast")
    new, rep = roll_forward(Dataset.model_validate(d), date(2026, 1, 12))
    assert [(r.qty, r.due_date) for r in new.receipts] == [(10, date(2026, 1, 14))]


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


def steady(on_hand: float, mrp_type: str = "ddmrp") -> dict:
    """The zone-math case planned: 10 a day for six weeks, a 10-day purchase lead time, weekly CV 0.2, so the buffer is
    TOR 87.5, TOY 187.5, TOG 257.5 (``test_ddmrp_zone_math_by_hand``)."""
    d = buy(on_hand=on_hand, lt=10, bucket="week", mrp_type=mrp_type, safety_stock={"demand_cv": 0.2})
    for i in range(42):
        dem(d, (date(2026, 1, 5) + timedelta(days=i)).isoformat(), 10)
    return d


def test_ddmrp_mrp_type_lets_the_buffer_place_the_orders():
    """ENTERPRISE_PLAN 2.4, §8.7: with MRP type ddmrp the net flow position, not the net requirements, decides. 200 on
    hand: 5 Jan NFP 190 (green, no order); 6 Jan NFP 180 ≤ TOY 187.5 → order TOG − NFP = 77.5 (78 whole) that day,
    arriving 16 Jan. Supply is now 278: 13 Jan NFP 188 (no order), 14 Jan NFP 178 → 79.5 (80). Planned by its
    requirements instead, the same stock lasts to 25 Jan and MRP orders 10 at a time from 15 Jan: two signals that
    disagree, the pitfall the guide names. The red zone stands in for safety stock in the projection."""
    res = plan(steady(200))
    o = orders(res)
    assert [(x.start_date.isoformat(), x.available_date.isoformat(), x.qty) for x in o[:2]] == [
        ("2026-01-06", "2026-01-16", 78), ("2026-01-14", "2026-01-24", 80)]
    [node] = [n for n in res.nodes if n.product == "B"]
    assert node.buckets[0].safety_stock == pytest.approx(87.5)
    assert "DDMRP buffer: red to 87.5, yellow to 187.5, green to 257.5" in node.safety_stock_note
    assert not {"BUFFER_RED", "BUFFER_YELLOW"} & set(codes(res))     # green on the first day
    mrp = orders(plan(steady(200, "deterministic")))
    assert (mrp[0].start_date.isoformat(), mrp[0].qty) == ("2026-01-15", 10)


def test_ddmrp_red_and_yellow_buffers_go_to_the_inbox_and_agree_with_the_inventory_screen():
    """§8.7 buffer status: 50 on hand, NFP on 5 Jan 40 ≤ TOR 87.5: red, order 217.5 (218) today and expedite; 120 on
    hand: NFP 110, yellow, order 147.5 (148). The inventory screen's DDMRP row for the same day shows the same zone and
    the same order, so the advice and the plan are one signal."""
    for oh, code, zone, qty in ((50, "BUFFER_RED", "red", 218), (120, "BUFFER_YELLOW", "yellow", 148)):
        d = steady(oh)
        res = plan(d)
        first = orders(res)[0]
        assert (first.start_date.isoformat(), first.qty) == (START, qty)
        [e] = [e for e in res.exceptions if e.code in ("BUFFER_RED", "BUFFER_YELLOW")]
        assert (e.code, e.severity, e.order_id, e.qty) == (code, "warning", first.id, qty)
        assert f"net flow position {oh - 10:,.1f}" in e.message
        row = next(r for r in run_inventory(Dataset.model_validate(d), time_limit=5).ddmrp if r.product == "B")
        assert (row.positioned, row.zone, math.ceil(row.order_qty)) == (True, zone, qty)
    from scp.tower.worklist import CATEGORY
    assert CATEGORY["BUFFER_RED"] == CATEGORY["BUFFER_YELLOW"] == "orders"


def test_ddmrp_a_spike_inside_the_decoupled_lead_time_is_qualified_demand():
    """§8.7 qualified demand: an order of 150 on 12 Jan is over the spike threshold (0.5 × TOR) and inside the 10-day
    DLT, so on 5 Jan it already counts: NFP 200 − 10 − 150 = 40, red, and the buffer orders on the first day. The same
    150 on 25 Jan is outside the DLT on 5 Jan: NFP 190, under this bigger buffer's TOY but over its TOR, so yellow. The
    buffer itself is the formula's for the
    ADU these orders make (``ddmrp.size``)."""
    d = steady(200)
    dem(d, "2026-01-12", 150)
    res = plan(d)
    b = ddmrp.size((280 + 150) / 28, 10, 0.2, 0, InventorySettings())
    assert 150 > 0.5 * b.tor
    first = orders(res)[0]
    assert (first.start_date.isoformat(), first.qty) == (START, math.ceil(b.tog - 40))
    assert "BUFFER_RED" in codes(res)
    d["demand"][-1]["date"] = "2026-01-25"
    later = plan(d)
    assert b.tor < 190 <= b.toy
    [e] = [e for e in later.exceptions if e.code in ("BUFFER_RED", "BUFFER_YELLOW")]
    assert e.code == "BUFFER_YELLOW" and "net flow position 190.0" in e.message
    assert orders(later)[0].qty == math.ceil(b.tog - 190)


def test_ddmrp_where_no_buffer_can_be_held_is_said():
    """A make-to-order part has no stock to buffer: it is planned by its requirements and the readiness check says so;
    a safety stock beside the buffer is not planned and is named too."""
    d = steady(0)
    d["location_products"][0]["strategy"] = "MTO"
    assert "DDMRP_NOT_A_BUFFER" in [i.code for i in validate(Dataset.model_validate(d))]
    d = steady(0)
    d["location_products"][0]["safety_stock"] = {"method": "fixed", "qty": 30, "demand_cv": 0.2}
    assert "DDMRP_SAFETY_STOCK" in [i.code for i in validate(Dataset.model_validate(d))]
    assert plan(d).nodes[0].buckets[0].safety_stock == pytest.approx(87.5)


# ================================================================================================ §16.2 sales-order stock
def made_to_order(assigned: bool) -> dict:
    """A part bought to order with a 10-day lead time (a new order is there 15 Jan at the earliest). SO-1 wants 50 on
    20 Jan and PO-1 for 50, due 14 Jan, was bought for it; SO-2 wants 50 on 12 Jan."""
    d = buy(strategy="MTO", lt=10)
    dem(d, "2026-01-20", 50, id="SO-1")
    dem(d, "2026-01-12", 50, id="SO-2")
    rec(d, "2026-01-14", 50, id="PO-1", **({"sales_order": "SO-1"} if assigned else {}))
    return d


def test_a_firm_order_bought_for_one_sales_order_is_not_taken_by_another():
    """ENTERPRISE_PLAN 2.5, §16.2: make-to-order supply is that order's (S/4 sales-order segment). Free, PO-1 goes to
    the earlier order SO-2 (expedite it 2 days) and SO-1 gets a new requisition; bought for SO-1 it stays with SO-1,
    the plan buys for SO-2 instead, and that requisition is marked for SO-2 so it is firmed for it."""
    free = plan(made_to_order(False))
    assert {(p.supply_id, p.requirement_id) for p in free.pegs} == {("PO-1", "D:SO-2"), ("PR-00001", "D:SO-1")}
    assert "RESCHEDULE_IN" in codes(free)
    held = plan(made_to_order(True))
    assert {(p.supply_id, p.requirement_id) for p in held.pegs} == {("PO-1", "D:SO-1"), ("PR-00001", "D:SO-2")}
    [o] = orders(held)
    assert (o.need_date.isoformat(), o.qty, o.sales_order) == ("2026-01-12", 50, "SO-2")
    assert "RESCHEDULE_IN" not in codes(held)
    # the projection is the free stock: 20 more held for SO-3 do not soften SO-2's shortage of 50 on the 12th
    d = made_to_order(True)
    d["location_products"][0]["order_stock"] = [{"order": "SO-3", "qty": 20}]
    dem(d, "2026-01-22", 20, id="SO-3")
    [e] = [e for e in plan(d).exceptions if e.code == "STOCKOUT"]
    assert e.qty == pytest.approx(50)


def test_held_supply_that_comes_late_is_expedited_and_held_supply_not_needed_is_reported():
    """A held PO due after its order is expedited, with no other supply planned in front of it; when the order is cut
    to 30 the other 20 stay held, and the plan says so (no other order may use them)."""
    d = made_to_order(True)
    d["demand"][0]["date"] = "2026-01-12"           # SO-1 now wanted on the 12th; PO-1 comes on the 14th
    res = plan(d)
    [e] = [e for e in res.exceptions if e.code == "RESCHEDULE_IN"]
    assert (e.order_id, e.date.isoformat()) == ("PO-1", "2026-01-12")
    assert "SO-1, the sales order it is held for" in e.message and "expedite it by 2 d" in e.message
    assert all(o.sales_order != "SO-1" for o in orders(res))
    d = made_to_order(True)
    d["demand"][0]["qty"] = 30
    [e] = [e for e in plan(d).exceptions if e.code == "ORDER_STOCK_LEFT"]
    assert e.qty == pytest.approx(20) and "held for SO-1 (PO-1)" in e.message


def test_a_promise_is_made_from_what_is_held_for_the_order_and_never_from_another_orders():
    """§16.2 / §7: SO-2 now wants its 50 on the 15th, after PO-1 arrives, and was entered first, so it is checked
    first. Free, it takes PO-1 and SO-1 gets nothing; held for SO-1, SO-1 is confirmed from it and why says so, and SO-2 gets
    nothing from it."""
    def promised(assigned: bool) -> dict:
        d = promising(made_to_order(assigned))
        d["demand"][1]["date"] = "2026-01-15"
        d["demand"].reverse()
        return by_order(run_promise(Dataset.model_validate(d)))
    free = promised(False)
    assert (lines(free["SO-2"]), lines(free["SO-1"])) == ([("2026-01-15", 50, "atp")], [])
    held = promised(True)
    assert (lines(held["SO-1"]), lines(held["SO-2"])) == ([("2026-01-20", 50, "atp")], [])
    assert held["SO-1"].held and "firm receipt PO-1 is available, held for this order" in [w.note for w in held["SO-1"].why]


def test_sales_order_stock_from_firming_to_receipt_to_delivery():
    """The whole road: the requisition planned for SO-2 becomes a PO line held for SO-2; PO-1 received on the 14th is
    held stock for SO-1, not free stock; after the roll the plan covers SO-1 from it and buys nothing more for it,
    and SO-1's delivery issues it from that stock."""
    from scp.actuals.firm import firm_orders
    from scp.actuals.post import post
    from scp.actuals.roll import roll_forward
    ds = Dataset.model_validate(made_to_order(True))
    res = run_mrp(ds)
    firmed, rep = firm_orders(ds, res, ids=[orders(res)[0].id])
    [line] = [r for r in firmed.receipts if r.id != "PO-1"]
    assert line.sales_order == "SO-2"
    got, _ = post(firmed, "receive", order="PO-1", on=date(2026, 1, 14))
    [m] = [m for m in got.movements if m.reference == "PO-1"]
    assert m.sales_order == "SO-1"
    rolled, _ = roll_forward(got, date(2026, 1, 19))
    lp = rolled.location_product_by_key[("P", "B")]
    assert (lp.on_hand, [(x.order, x.qty) for x in lp.order_stock]) == (0, [("SO-1", 50)])
    after = run_mrp(rolled)
    assert [(p.supply_id, p.requirement_id) for p in after.pegs if p.requirement_id == "D:SO-1"] == [
        ("OS:P:B:SO-1", "D:SO-1")]
    assert all(o.sales_order != "SO-1" for o in after.orders)
    shipped, msg = post(rolled, "deliver", order="SO-1", on=date(2026, 1, 20))
    [sale] = [m for m in shipped.movements if m.reference == "SO-1"]
    assert (sale.sales_order, sale.qty) == ("SO-1", 50)
    assert "from the stock held for SO-1" in msg.message
    final, _ = roll_forward(shipped, date(2026, 1, 26))
    assert final.location_product_by_key[("P", "B")].order_stock == []


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



def test_picking_packing_and_loading_check_stock_before_the_goods_leave():
    """ENTERPRISE_PLAN 2.2, fig. 6.2: delivery 20 Jan, 3 days on the road → goods issue 17 Jan; a day to load after a
    day to pick and pack → the goods must be there on 15 Jan (material availability date), and stock is checked then.
    The line says both dates, and why."""
    d = _customer(promising(buy(on_hand=100, lt=30)))
    d["locations"][0].update(pick_pack_workdays=1, loading_workdays=1)
    dem(d, "2026-01-20", 10, location="CU")
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert [(x.ship_date, x.goods_issue, x.date) for x in o.lines] == [
        (date(2026, 1, 15), date(2026, 1, 17), date(2026, 1, 20))]
    assert o.status == "on_time"
    assert [(w.kind, w.date) for w in o.why][-2:] == [("handling", date(2026, 1, 17)), ("ship", date(2026, 1, 20))]
    assert o.why[-2].note == "there to pick 2026-01-15; picking, packing and loading take 2 working days, so it leaves 2026-01-17"
    assert o.why[-2].qty == 2 and o.why[-1].note == "shipped 2026-01-17 over L1, delivered 2026-01-20"


def test_a_warehouse_that_needs_a_day_to_pick_no_longer_confirms_a_day_early():
    """The defect ENTERPRISE_PLAN 2.2 names: stock arrives 16 Jan for a delivery on 20 Jan with 3 days' transit. With
    no handling time the order is confirmed on time, shipped the day the goods arrive. A day to pick and pack and a day
    to load make it there to pick on 16 Jan, leaving 18 Jan, delivered 21 Jan: one day late, and said so."""
    d = _customer(promising(buy(lt=30)))
    rec(d, "2026-01-16", 50)
    dem(d, "2026-01-20", 10, location="CU")
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert [(x.ship_date, x.goods_issue, x.date) for x in o.lines] == [(date(2026, 1, 17), None, date(2026, 1, 20))]
    assert o.status == "on_time"
    d["locations"][0].update(pick_pack_workdays=1, loading_workdays=1)
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert [(x.ship_date, x.goods_issue, x.date) for x in o.lines] == [
        (date(2026, 1, 16), date(2026, 1, 18), date(2026, 1, 21))]
    assert o.status == "late"


def test_transport_planning_runs_alongside_picking_on_working_days():
    """Fig. 6.2: booking the carrier (transportation planning, on the route) and picking both end at loading, so the
    longer counts. Monday–Friday at the warehouse: delivery Tue 20 Jan, 3 days on the road → goods issue Sat 17 is not a
    working day, so Fri 16; loading 1 → Thu 15; the longer of picking 1 and booking 2 → Tue 13 Jan."""
    d = _customer(promising(buy(on_hand=100, lt=30, workdays=WEEKDAYS)))
    d["locations"][0].update(pick_pack_workdays=1, loading_workdays=1)
    d["lanes"][0]["transport_planning_workdays"] = 2
    dem(d, "2026-01-20", 10, location="CU")
    [o] = run_promise(Dataset.model_validate(d)).orders
    assert [(x.ship_date, x.goods_issue, x.date) for x in o.lines] == [
        (date(2026, 1, 13), date(2026, 1, 16), date(2026, 1, 20))]   # delivered on the date asked, not early


def test_outbound_handling_moves_the_planned_shipment_and_is_kept_on_the_confirmation():
    """The plan schedules a shipment the same way: the stock leaves the warehouse's requirements on the material
    availability date, two working days before the goods issue. Promising and keeping the confirmation stores the
    goods issue with it."""
    from scp.promise.run import commit

    d = _customer(buy(on_hand=0, lt=1))
    d["locations"][0].update(pick_pack_workdays=1, loading_workdays=1)
    dem(d, "2026-01-20", 10, location="CU", kind="forecast")
    res = plan(d)
    [t] = [o for o in res.orders if o.kind == "transfer"]
    assert (t.start_date, t.available_date) == (date(2026, 1, 15), date(2026, 1, 20))
    [b] = [o for o in res.orders if o.kind == "buy"]
    assert b.available_date <= date(2026, 1, 15)

    d = _customer(promising(buy(on_hand=100, lt=30)))
    d["locations"][0].update(pick_pack_workdays=1, loading_workdays=1)
    dem(d, "2026-01-20", 10, location="CU", id="SO-1")
    kept, _ = commit(Dataset.model_validate(d))
    [c] = kept.confirmations
    assert (c.ship_date, c.goods_issue, c.date) == (date(2026, 1, 15), date(2026, 1, 17), date(2026, 1, 20))


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
