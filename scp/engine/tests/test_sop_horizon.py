"""Enterprise 8.5, N360: the S&OP plan looks past the weekly plan's horizon. A plant sells 70 A a week, every week
for a year: the statistical forecast is 70 a week, whatever method wins. The weekly plan looks 28 days ahead and
holds a forecast of 280 over them; the S&OP plan looks 3 months (91 days) ahead, so the 63 days after the weekly
plan's end come from the forecast run out on the same weekly grid: 9 weeks of 70, 630, and 910 in all."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from scp.sop.cycle import figures
from scp.sop.horizon import extend, sop_days
from scp.sop.plan import run_sop

from .factory import START, base, demand, ds


def plant(months: int | None = 3, horizon: int = 28) -> dict:
    d = base(horizon=horizon)
    d["products"][0]["price"] = 100
    first = date.fromisoformat(START) - timedelta(weeks=52)
    d["history"] = [{"location": "P", "product": "A", "date": (first + timedelta(weeks=i)).isoformat(), "qty": 70}
                    for i in range(52)]
    d["demand"] = [demand("P", "A", START, 280, period_days=28)]
    d["sop"] = {"horizon_months": months}
    return d


def test_the_forecast_beyond_the_weekly_plan_is_added_on_the_same_grid():
    x = ds(plant())
    assert sop_days(x) == 91                                   # 3 × 365 / 12 = 91.25
    long, notes = extend(x)
    added = long.demand[1:]
    assert long.settings.horizon_days == 91 and x.settings.horizon_days == 28
    assert [d.date for d in added] == [date.fromisoformat(START) + timedelta(days=28 + 7 * i) for i in range(9)]
    assert all(d.period_days == 7 for d in added)
    assert sum(d.qty for d in added) == pytest.approx(630)
    assert "3 months ahead" in notes[0] and "1 series" in notes[0]


def test_a_week_the_weekly_plan_ends_inside_is_split_at_its_end():
    # a 30-day weekly plan ends on Wednesday of the fifth week: that week adds its last 5 days (50), then 8 weeks
    long, _ = extend(ds(plant(3, 30)))
    added = long.demand[1:]
    assert (added[0].date, added[0].period_days, added[0].qty) == (date.fromisoformat(START) + timedelta(days=30), 5,
                                                                   pytest.approx(50))
    assert sum(d.qty for d in added) == pytest.approx(610)                      # 61 days at 10


def test_the_sop_plan_and_the_cycle_figures_run_over_the_longer_horizon():
    r = run_sop(ds(plant()))
    assert r.ok
    # Mon 5 Jan to Mon 6 Apr: January from the 5th, February, March, and 6 April
    assert [b.label for b in r.buckets][0].startswith("Jan") and len(r.buckets) == 4
    assert r.kpis.demand == pytest.approx(910)
    assert any("3 months ahead" in n for n in r.notes)
    f = figures(ds(plant()), "demand")
    assert len(f.months) == 4 and sum(m.demand_qty for m in f.months) == pytest.approx(910)
    assert any("3 months ahead" in n for n in f.notes)


def test_no_longer_horizon_leaves_the_plan_as_it_was():
    # none set, or 1 month (30 days) against a 56-day weekly plan
    for months, horizon in ((None, 28), (1, 56)):
        x = ds(plant(months, horizon))
        assert sop_days(x) == horizon and extend(x) == (x, [])
        assert run_sop(x).kpis.demand == pytest.approx(280)


def test_a_product_made_to_order_gets_no_forecast_beyond_as_release_gives_it_none():
    d = plant()
    d["location_products"][0]["strategy"] = "MTO"
    long, _ = extend(ds(d))
    assert len(long.demand) == 1


def test_the_plans_money_month_by_month_by_hand():
    """N364: 10 A at 100 sold from the 10 in stock in January; the 30 B (bought at 10) stay all horizon and cost
    20 % a year to keep: 300 × 0.2 × 27 ÷ 365 in January's 27 days, × 1 ÷ 365 on 1 February."""
    d = base(horizon=28)
    d["products"][0]["price"] = 100
    d["demand"] = [demand("P", "A", START, 10)]
    r = run_sop(ds(d))
    jan, feb = r.money
    assert (jan.revenue, feb.revenue) == (1000, 0)
    assert jan.cost == pytest.approx(300 * 0.2 * 27 / 365) and feb.cost == pytest.approx(300 * 0.2 / 365)
    assert jan.margin == pytest.approx(1000 - 300 * 0.2 * 27 / 365)
    assert (jan.stock_value, feb.stock_value) == (300, 300)
    e = r.economics
    assert sum(m.cost for m in r.money) == pytest.approx(e.purchase + e.production + e.transport + e.holding + e.overtime)
    # the cycle's supply steps carry it, month by month; the demand review has no supply plan to cost
    f = figures(ds(d), "exec")
    assert [m.supply_margin for m in f.months] == pytest.approx([jan.margin, feb.margin], abs=0.01)
    assert [m.stock_value for m in f.months] == [300, 300]
    assert figures(ds(d), "demand").months[0].supply_margin is None
