"""Enterprise 4.4: demand with a spread and lead times as measured. A forecast release keeps the high end of the
forecast's interval (P90 at the default 80 %); an order check gives a safe date beside the expected one, with that
high end of the forecast still to be ordered promised first; and each supplier's receipts against their due dates
give the measured spread of its lead time, the σ_L safety stock covers."""
from __future__ import annotations

import math
from datetime import date

import pytest

from scp.demand import release, run_forecast
from scp.model import DemandKind, DemandRecord
from scp.promise import check_lines, check_order
from scp.purchasing import vendor_rows
from scp.purchasing.spread import measured_spreads

from .factory import ds, load_example, lp
from .test_demand import dataset, weekly
from .test_promise import net


# ---- the high end, released with the forecast ---------------------------------------------------
def test_a_release_keeps_the_high_end_of_each_period_in_whole_units():
    d = dataset(weekly("P", "A", [70.0, 90.0] * 15))
    d["settings"]["planning_start"] = "2026-01-07"  # Wednesday: the first period is five days of seven
    r = run_forecast(ds(d))
    new, _ = release(ds(d), r)
    fc = sorted((x for x in new.demand if x.kind is DemandKind.FORECAST), key=lambda x: x.date)
    pts = [p for p in r.series[0].forecast if p.released_qty > 0]
    assert [x.high_qty for x in fc] == [math.ceil(p.upper * p.share - 1e-6) for p in pts]
    assert fc[0].high_qty == math.ceil(pts[0].upper * 5 / 7 - 1e-6)
    assert all(x.high_qty >= x.qty for x in fc) and any(x.high_qty > x.qty for x in fc)
    assert r.summary.total_high == sum(x.high_qty for x in fc)      # the Demand page's "up to … at the high end"


# ---- the safe date ------------------------------------------------------------------------------
def _shop(on_hand: float, forecast_at: str) -> dict:
    """D holds ``on_hand`` and gets 50 more on 15 Jan; a week's forecast of 60 from 5 Jan, 90 at the high end, at
    ``forecast_at``; customers are a day from D. A is measured in litres here, so nothing is rounded."""
    d = net()
    d["products"][0]["whole_units"] = False
    lp(d, "D", "A")["on_hand"] = on_hand
    d["receipts"] = [{"id": "STO1", "kind": "transfer", "location": "D", "product": "A", "qty": 50,
                      "due_date": "2026-01-15"}]
    d["demand"] = [{"location": forecast_at, "product": "A", "date": "2026-01-05", "qty": 60, "kind": "forecast",
                    "period_days": 7, "high_qty": 90}]
    return d


def order(qty: float = 50, day: str = "2026-01-10", loc: str = "C1") -> DemandRecord:
    return DemandRecord(location=loc, product="A", date=date.fromisoformat(day), qty=qty, kind="sales_order")


def test_another_customers_high_end_forecast_comes_first_in_the_safe_date():
    r = check_order(ds(_shop(100, "C2")), order())
    c = r.checked
    # expected: the stock is free, on time
    assert c.status == "on_time" and c.confirmed == 50
    # safe: C2's 60 + its 30 of spread, six days of the seven up to the 10th (77.1), are kept first: 22.9 of the
    # stock is left, and the rest waits for the 50 coming on the 15th
    s = c.safe
    assert s.reserved == pytest.approx(90 * 6 / 7)
    assert s.on_time == pytest.approx(100 - 90 * 6 / 7) and s.confirmed == pytest.approx(50)
    assert s.status == "late" and s.date == date(2026, 1, 16)
    # the expected promise and the dataset's other orders are untouched by it
    assert r.orders == [] and [x.date for x in c.lines] == [date(2026, 1, 10)]
    # a product counted in each keeps whole units for the orders to come: 78, not 77.1
    d = _shop(100, "C2")
    d["products"][0]["whole_units"] = True
    s = check_order(ds(d), order()).checked.safe
    assert s.reserved == 78 and s.on_time == 22


def test_the_order_itself_uses_up_its_own_customers_forecast_first():
    # the 50 ordered at C1 is part of C1's forecast: 10 of the 60 is still to come, plus 30 at the high end
    s = check_order(ds(_shop(80, "C1")), order()).checked.safe
    assert s.reserved == pytest.approx(40 * 6 / 7)
    assert s.on_time == pytest.approx(80 - 40 * 6 / 7) and s.status == "late"


def test_forecast_after_the_requested_date_is_not_kept_first():
    d = _shop(100, "C2")
    d["demand"][0]["date"] = "2026-01-12"
    s = check_order(ds(d), order(day="2026-01-11")).checked.safe
    assert s.reserved == 0 and s.status == "on_time"
    s = check_order(ds(d), order(day="2026-01-12")).checked.safe      # its first day of seven is in
    assert s.reserved == pytest.approx(90 / 7)


def test_no_safe_date_without_a_high_end_or_where_the_forecast_plans_nothing():
    d = _shop(100, "C2")
    del d["demand"][0]["high_qty"]
    assert check_order(ds(d), order()).checked.safe is None
    d = _shop(100, "C2")
    lp(d, "D", "A")["strategy"] = "MTO"     # made to order: the forecast plans nothing, orders take what there is
    assert check_order(ds(d), order()).checked.safe is None


def test_make_to_stock_counts_the_order_in_its_forecast_too():
    d = _shop(80, "C1")
    lp(d, "D", "A")["strategy"] = "MTS"
    assert check_order(ds(d), order()).checked.safe.reserved == pytest.approx(40 * 6 / 7)


def test_a_variants_orders_use_up_its_planning_materials_forecast_before_it_is_kept():
    d = _shop(100, "C2")
    d["products"].append({"id": "A2", "type": "FG", "planning_material": "A", "whole_units": False})
    d["production_sources"].append({**d["production_sources"][0], "id": "PV-A2", "product": "A2"})
    d["demand"].append({"location": "C2", "product": "A2", "date": "2026-01-08", "qty": 30, "kind": "sales_order",
                        "id": "SO-A2"})
    # C2's 60 less the 30 its variant's order took, plus the 30 of spread, six days of seven
    assert check_order(ds(d), order()).checked.safe.reserved == pytest.approx(60 * 6 / 7)


def test_lines_of_one_order_keep_the_high_end_once_and_follow_each_other():
    r = check_lines(ds(_shop(100, "C2")), [order(10), order(20)])
    a, b = (x.safe for x in r.checked_lines)
    assert a.reserved == b.reserved == pytest.approx(90 * 6 / 7)
    left = 100 - 90 * 6 / 7
    assert a.on_time == pytest.approx(10) and b.on_time == pytest.approx(left - 10)
    # lines asked for on different days: the forecast is kept up to the latest of them, for every line
    r = check_lines(ds(_shop(100, "C2")), [order(10, "2026-01-06"), order(20, "2026-01-10")])
    assert [x.safe.reserved for x in r.checked_lines] == pytest.approx([90 * 6 / 7] * 2)


# ---- lead times as measured ---------------------------------------------------------------------
def closed(oid: str, late: int, product: str = "B", closed_on: str = "2025-12-20", supplier: str = "S",
           first: int | None = None) -> dict:
    due = date(2025, 12, 10)
    got = date.fromordinal(due.toordinal() + late).isoformat()
    return {"kind": "purchase", "id": oid, "location": "P", "product": product, "counterparty": supplier,
            "ordered_qty": 10, "delivered_qty": 10, "due_date": due.isoformat(),
            "first_delivery": got if first is None else date.fromordinal(due.toordinal() + first).isoformat(),
            "last_delivery": got, "closed_on": closed_on}


def test_a_source_is_measured_from_its_own_receipts_else_from_its_suppliers():
    d = net()
    # the second came in two deliveries, the last two days late: the line was there in full only then
    d["closed_orders"] = [closed("1", 0), closed("2", 2, first=0), closed("3", -1), closed("4", 6, product="C")]
    m = measured_spreads(ds(d))
    b, c = m["PIR-B"], m["PIR-C"]
    # B: three of its own, a day early to two late: mean 1/3, sample sd √(7/3)
    assert (b.basis, b.lines, b.mean_days_late, b.std_days) == ("source", 3, 0.33, round(math.sqrt(7 / 3), 2))
    # C: one of its own, so the supplier's four: 0, 2, −1, 6
    assert (c.basis, c.lines, c.mean_days_late, c.std_days) == ("supplier", 4, 1.75, round(math.sqrt(28.75 / 3), 2))
    rec = next(r for v in vendor_rows(ds(d), []) for r in v.info_records if r.source_id == "PIR-C")
    assert rec.measured == c and rec.lead_time_std_days == 0


def test_too_few_or_too_old_receipts_measure_nothing():
    d = net()
    d["closed_orders"] = [closed("1", 0), closed("2", 3), closed("3", 1, closed_on="2025-01-04")]
    assert measured_spreads(ds(d)) == {}
    d["closed_orders"][2]["closed_on"] = "2025-01-05"   # a year before the planning start is still in
    assert measured_spreads(ds(d))["PIR-B"].lines == 3


def test_kaveri_shenzhen_is_measured_from_both_its_parts():
    m = measured_spreads(load_example("kitchenware_network"))
    sw = m["PIR-SWITCH"]
    # two lines each of switches and heaters: a day early three times, a week late once
    assert (sw.basis, sw.lines, sw.mean_days_late, sw.std_days) == ("supplier", 4, 1.0, 4.0)
    assert "PIR-CU" not in m          # the copper supplier has delivered two lines so far
