"""The forecast is reduced by the orders already delivered, across rolls (S/4 guide §5.1 "reduction at goods issue",
§17.2, §20.1 #1 "a PIR is consumed exactly once").

The roll-forward keeps the forecast as entered on the record (``original_*``) and every plan counts the delivered and
open orders against it again from scratch (plan/consumption.py), so:

* the guide's example plans 20, not 50: forecast 100 over four weeks, 80 ordered and delivered in week one, two weeks
  rolled (before, 130 was planned for a period whose forecast was 100);
* an order delivered in parts across rolls is counted once, whatever the rolls;
* rolling a week and then another plans exactly what rolling two weeks at once does (scenario s9's invariant), now
  with deliveries in the period: the earlier per-record "reduced quantity" broke it (s9, seed 2).
"""
from __future__ import annotations

from datetime import date, timedelta

from hypothesis import example, given
from hypothesis import strategies as st

from scp.actuals.roll import roll_forward
from scp.model import Dataset
from scp.plan import run_mrp

from .factory import base, demand, ds

D0 = date(2026, 1, 5)                      # the planning start of factory.base (a Monday); a 7-day calendar


def _company(orders: list[tuple[str, int, float]], sales: list[tuple[str, int, float]], fc: float = 100.0,
             fc_start: int = 0, period: int = 28) -> Dataset:
    """Forecast ``fc`` at P/A over ``period`` days from day ``fc_start``; sales orders (id, day, qty); deliveries
    (order id, day, qty) in the journal."""
    d = base(horizon=56)
    d["locations"].append({"id": "K", "type": "customer"})
    d["demand"] = [demand("P", "A", (D0 + timedelta(days=fc_start)).isoformat(), fc, period_days=period, id="F")]
    d["demand"] += [demand("P", "A", (D0 + timedelta(days=day)).isoformat(), q, "sales_order", id=oid)
                    for oid, day, q in orders]
    d["movements"] = [{"id": "open", "date": (D0 - timedelta(days=1)).isoformat(), "type": "opening",
                       "location": "P", "product": "A", "qty": 10_000}]
    d["movements"] += [{"id": f"m{i}", "date": (D0 + timedelta(days=day)).isoformat(), "type": "sale", "location": "P",
                        "product": "A", "qty": q, "reference": oid, "counterparty": "K"}
                       for i, (oid, day, q) in enumerate(sales)]
    return ds(d)


def _planned(x: Dataset) -> tuple[float, float]:
    """Forecast and open-order quantity the plan puts on P/A."""
    reqs = [r for r in run_mrp(x).requirements if (r.location, r.product) == ("P", "A")]
    return (round(sum(r.qty for r in reqs if r.kind == "forecast"), 6),
            round(sum(r.qty for r in reqs if r.kind == "sales_order"), 6))


def _roll(x: Dataset, *days: int) -> Dataset:
    for day in days:
        x, rep = roll_forward(x, D0 + timedelta(days=day))
        assert rep.ok, rep.warnings
    return x


# ---- the guide's example ------------------------------------------------------------------------------------------
def test_guide_example_delivered_order_reduces_the_forecast_after_a_roll():
    x = _company([("SO1", 2, 80)], [("SO1", 2, 80)])
    assert _planned(x) == (20.0, 80.0)                   # before any roll: the order consumes 80 of 100
    two = _roll(x, 14)
    f = next(d for d in two.demand if d.id == "F")
    assert (f.qty, f.original_qty, f.original_date, f.original_period_days) == (50.0, 100.0, D0, 28)
    assert not [d for d in two.demand if d.id == "SO1"]   # delivered in full: closed, in the closed-order log
    assert _planned(two) == (20.0, 0.0)                  # was 50: 80 delivered + 50 = 130 for a forecast of 100


def test_guide_example_rolled_one_week_at_a_time_plans_the_same():
    x = _company([("SO1", 2, 80)], [("SO1", 2, 80)])
    once, steps = _roll(x, 14), _roll(x, 7, 14)
    assert steps == once
    assert _planned(steps) == _planned(once) == (20.0, 0.0)


def test_slow_selling_period_keeps_the_time_share():
    """Deliveries short of the elapsed share reduce nothing: what time took is gone either way (no carry-over)."""
    x = _company([("SO1", 2, 10)], [("SO1", 2, 10)])
    assert _planned(_roll(x, 14)) == (50.0, 0.0)


# ---- partial deliveries across rolls ------------------------------------------------------------------------------
def test_partial_deliveries_across_rolls_are_counted_once():
    """80 ordered on day 2: 40 delivered on day 2, 20 on day 9, the last 20 still open. Each roll plans the forecast
    the period has left after what was sold, never the delivered part twice."""
    x = _company([("SO1", 2, 80)], [("SO1", 2, 40), ("SO1", 9, 20)])
    # day 7: 40 delivered (15 beyond the 25 of week one), 40 open → 75 − 15 = 60 left, the open 40 consume it
    assert _planned(_roll(x, 7)) == (20.0, 40.0)
    # day 14: 60 delivered (10 beyond the 50 of two weeks), 20 open → 50 − 10 = 40, the open 20 consume it
    assert _planned(_roll(x, 14)) == (20.0, 20.0)
    assert _planned(_roll(x, 7, 14)) == (20.0, 20.0)
    # day 21: 60 delivered, short of the 75 time took: 25 left, the open 20 consume it
    assert _planned(_roll(x, 21)) == (5.0, 20.0)
    assert _planned(_roll(x, 7, 14, 21)) == (5.0, 20.0)


def test_an_order_delivered_before_the_forecast_began_does_not_reduce_it():
    """A forecast released later (from day 14) is not reduced by an order of an earlier period: that order consumed a
    forecast that is gone, or none."""
    x = _company([("SO1", 2, 80)], [("SO1", 2, 80)], fc=100, fc_start=14, period=28)
    assert _planned(_roll(x, 7)) == (100.0, 0.0)
    assert _planned(_roll(x, 21)) == (75.0, 0.0)          # time took a week of it; the old order nothing


def test_a_past_due_open_order_consumes_the_period_it_belongs_to():
    """An order dated in week one, still open after the roll, consumes the forecast of its own period (matched by the
    forecast as entered, not by the rolled record that now starts later)."""
    x = _company([("SO1", 2, 30)], [])
    assert _planned(_roll(x, 14)) == (20.0, 30.0)         # 50 left by time, 30 of it ordered


# ---- the property --------------------------------------------------------------------------------------------------
order_st = st.tuples(st.integers(0, 27), st.integers(1, 60))                       # (day, qty)
part_st = st.lists(st.tuples(st.integers(0, 34), st.integers(1, 40)), max_size=3)   # deliveries (day, qty)


@given(orders=st.lists(st.tuples(order_st, part_st), min_size=1, max_size=3),
       fc=st.integers(20, 200), w1=st.integers(1, 4), gap=st.integers(1, 2))
@example(orders=[((2, 80), [(2, 80)])], fc=100, w1=1, gap=1)                  # the guide's example
@example(orders=[((2, 80), [(2, 40), (9, 20)])], fc=100, w1=1, gap=1)         # delivered in parts across the rolls
@example(orders=[((1, 30), [(1, 30)]), ((5, 50), [(6, 20), (12, 30)])], fc=60, w1=1, gap=2)
def test_rolls_compose_and_never_plan_a_delivered_unit_twice(orders, fc, w1, gap):
    """Rolled week by week (as s9 rolls; the forecast-accuracy log is kept by week), any orders delivered in any
    parts on any days, before or after a roll."""
    t1 = 7 * w1
    rows, sales = [], []
    for k, ((day, qty), parts) in enumerate(orders):
        oid = f"SO{k}"
        rows.append((oid, day, float(qty)))
        given_ = 0.0
        for pday, pq in parts:                           # never more than ordered
            q = min(float(pq), qty - given_)
            if q > 0:
                sales.append((oid, pday, q))
                given_ += q
    x = _company(rows, sales, fc=float(fc))
    t2 = t1 + 7 * gap
    once, steps = _roll(x, t2), _roll(x, t1, t2)
    # composition: the same company and the same plan, however the days were rolled
    assert steps == once
    assert run_mrp(steps).requirements == run_mrp(once).requirements
    # consumed exactly once: what is planned plus what was delivered never exceeds the larger of the forecast and the
    # orders (the forecast's whole period lies inside the horizon)
    end = D0 + timedelta(days=t2)
    delivered = sum(q for oid, day, q in sales if D0 + timedelta(days=day) < end)
    ordered = sum(q for _, _, q in rows)
    planned_fc, planned_so = _planned(once)
    assert planned_fc + planned_so + delivered <= max(float(fc), ordered) + 1e-6
    # and the forecast planned is never more than time leaves of it
    f = next((d for d in once.demand if d.id == "F"), None)
    assert planned_fc <= (f.qty if f else 0.0) + 1e-6
