"""Phase H: sensible defaults. Products counted in each are planned in whole units (Q6), the company sets how much an
order covers (Q7), a process step runs in batches (Q8), a month of sales counts over its days (Q11), a source is priced
in its supplier's currency (N40), and setup starts with the company itself (Q12)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from scp.demand import run_forecast
from scp.demand.pipeline import _aggregate
from scp.model import Dataset
from scp.model.demand import ForecastPeriod
from scp.plan import run_mrp
from scp.plan.leadtime import batch_multiple
from scp.purchasing import purchasing_view
from scp.validate import validate
from scp.validate.setup import checklist

from .factory import base, demand, ds, lp


def orders(x: Dataset, kind: str | None = None, product: str | None = None):
    return [o for o in run_mrp(x).orders if (kind is None or o.kind == kind) and (product is None or o.product == product)]


def daily(d: dict, loc: str, prod: str, qty: float, days: int = 28) -> None:
    d["demand"] = [demand(loc, prod, (date(2026, 1, 5) + timedelta(days=i)).isoformat(), qty) for i in range(days)]


# ---- Q6: whole units ----------------------------------------------------------------------------------------
def test_a_product_counted_in_each_is_planned_in_whole_units():
    d = base()
    daily(d, "P", "A", 10 / 3)
    x = ds(d)
    made = orders(x, "make", "A")
    assert made and all(o.qty == int(o.qty) for o in made)
    assert sum(o.qty for o in made) >= 28 * 10 / 3 - 10     # covers the need less the 10 on hand


def test_a_product_in_kilograms_keeps_its_fractions_and_the_flag_overrides_the_unit():
    d = base()
    d["products"][0]["base_uom"] = "KG"
    daily(d, "P", "A", 10 / 3)
    assert any(o.qty != int(o.qty) for o in orders(ds(d), "make", "A"))
    d["products"][0]["whole_units"] = True
    assert all(o.qty == int(o.qty) for o in orders(ds(d), "make", "A"))
    x = ds({**d, "products": [{"id": "A", "type": "FG", "base_uom": "box", "whole_units": False}, *d["products"][1:]]})
    assert not x.whole("A") and ds(base()).whole("A") and not x.whole("NOPE")


def test_a_forecast_for_a_product_counted_in_each_is_whole_and_keeps_its_total():
    d = base(horizon=70)
    d["history"] = [{"location": "P", "product": "A", "date": f"2025-{m:02d}-{day:02d}", "qty": q}
                    for m in range(7, 13) for day, q in ((3, 51), (12, 49.4), (20, 52.3))]
    x = ds(d)
    s = next(s for s in run_forecast(x).series if s.product == "A")
    assert all(p.released_qty == int(p.released_qty) for p in s.forecast)
    d["products"][0]["base_uom"] = "KG"
    exact = next(s for s in run_forecast(ds(d)).series if s.product == "A")
    assert abs(sum(p.released_qty for p in s.forecast) - sum(p.released_qty for p in exact.forecast)) <= 0.5
    assert any(p.released_qty != int(p.released_qty) for p in exact.forecast)


# ---- Q7: the company default lot size -------------------------------------------------------------------------
def test_the_company_default_covers_a_week_where_a_product_leaves_it_empty():
    d = base()
    daily(d, "P", "A", 10)
    exact = orders(ds(d), "make", "A")
    d["settings"]["default_lot_policy"] = "POQ"
    weekly = orders(ds(d), "make", "A")
    assert len(exact) > 20 and len(weekly) <= 4
    assert sum(o.qty for o in weekly) == pytest.approx(sum(o.qty for o in exact))
    lp(d, "P", "A")["lot_sizing"] = {"policy": "L4L"}      # a product's own rule wins
    assert len(orders(ds(d), "make", "A")) == len(exact)
    d["settings"]["default_lot_periods"] = 2
    lp(d, "P", "A")["lot_sizing"] = {"min_qty": 5}          # empty policy: the company's, its own minimum kept
    two = orders(ds(d), "make", "A")
    assert len(two) <= 2 and ds(d).planning_lp(("P", "A")).lot_sizing.min_qty == 5


def test_the_company_default_is_a_day_or_a_period():
    d = base()
    d["settings"]["default_lot_policy"] = "FIXED"
    with pytest.raises(ValidationError, match="set per product and place"):
        ds(d)


# ---- Q8: batch steps -------------------------------------------------------------------------------------------
def test_a_batch_step_takes_a_batch_s_time_however_full_and_orders_come_in_whole_batches():
    d = base()
    d["products"][0]["base_uom"] = "L"
    ps = d["production_sources"][0]
    ps["operations"] = [{"seq": 10, "resource": "M1", "setup_hours": 0, "batch_qty": 2000, "batch_hours": 3}]
    x = ds(d)
    op = x.production_sources[0].operations[0]
    assert (op.run_hours(1), op.run_hours(2000), op.run_hours(2001)) == (3, 3, 6)
    assert op.run_hours_per_unit_avg == pytest.approx(3 / 2000)
    daily(d, "P", "A", 150)
    made = orders(ds(d), "make", "A")
    assert made and all(o.qty % 2000 == 0 for o in made)
    ps["full_batches"] = False
    assert any(o.qty % 2000 for o in orders(ds(d), "make", "A"))


def test_a_batch_counts_the_units_entering_the_step():
    d = base()
    ps = d["production_sources"][0]
    ps["operations"] = [{"seq": 10, "resource": "M1", "batch_qty": 100, "batch_hours": 2, "scrap": 0.2}]
    x = ds(d)
    assert batch_multiple(x.production_sources[0]) == pytest.approx(80)     # 100 enter, 80 good come out
    daily(d, "P", "A", 7)
    made = orders(ds(d), "make", "A")
    assert made and all(o.qty % 80 == 0 for o in made)


def test_hours_per_batch_need_a_batch_size():
    d = base()
    d["production_sources"][0]["operations"] = [{"seq": 10, "resource": "M1", "batch_hours": 3}]
    with pytest.raises(ValidationError, match="batch size"):
        ds(d)


# ---- Q11: a month of sales -----------------------------------------------------------------------------------
def test_a_month_of_history_is_spread_over_its_weeks():
    d = base()
    d["history"] = [{"location": "P", "product": "A", "date": "2025-12-01", "qty": 310, "period_days": 31}]
    h = _aggregate(ds(d), ForecastPeriod.WEEK, date(2026, 1, 5))[("P", "A")]
    by_week = dict(zip(h.starts, h.raw, strict=True))
    assert by_week[date(2025, 12, 1)] == pytest.approx(70) and by_week[date(2025, 12, 29)] == pytest.approx(30)
    assert sum(h.raw) == pytest.approx(310)


# ---- N40 / Q16: supplier currency ------------------------------------------------------------------------------
def test_a_source_is_priced_in_its_supplier_s_order_currency():
    d = base()
    d["vendors"] = [{"supplier": "S", "currency": "USD"}]
    x = ds(d)
    assert x.price_currency(x.purchasing_sources[0]) == "USD"
    assert any(i.code == "FX_MISSING" for i in validate(x))
    d["settings"]["fx_rates"] = {"USD": 80}
    d["demand"] = [demand("P", "A", "2026-01-20", 100)]
    x = ds(d)
    req = next(r for r in purchasing_view(x, run_mrp(x)).requisitions if r.product == "B")
    assert req.currency == "USD" and req.value == pytest.approx(req.qty * 10 * 80)
    d["purchasing_sources"][0]["currency"] = "EUR"                       # the source's own currency wins
    assert ds(d).price_currency(ds(d).purchasing_sources[0]) == "EUR"


# ---- Q12: the company step and prices in setup -----------------------------------------------------------------
def test_setup_starts_with_the_company_and_notes_products_without_a_price():
    d = base()
    d["demand"] = [demand("P", "A", "2026-01-20", 20)]
    items = checklist(ds(d))
    first = items[0]
    assert first.step == "company" and first.status == "check" and first.action.route == ["setup", "company"]
    assert any(i.step == "prices" and "A has no selling price" in i.text for i in items)
    d["settings"].update(company_name="Kaveri Paints", currency="INR", default_lot_policy="POQ")
    d["products"][0]["price"] = 120
    items = checklist(ds(d))
    assert items[0].status == "done" and "a week's need" in items[0].text and "Kaveri Paints: INR" in items[0].text
    assert not any(i.step == "prices" for i in items)
