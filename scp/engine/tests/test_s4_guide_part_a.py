"""Backtests against the S/4HANA supply-chain guide, part A (§1–5, §17, §20.1).

Each test takes a rule the guide states (a worked figure where it gives numbers, a hand-calculated case where it
does not) and runs it through the engine or the API. The four marked REGRESSION failed before the fix that came
with them; the rest pin behaviour that already matched the guide so it cannot drift. Findings matrix:
audits/s4-backtest/part-a.md (outside the repo).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals.roll import roll_forward
from scp.actuals.stock import accuracy_report
from scp.api.app import app
from scp.model import AccuracyRecord, DemandRecord, Strategy
from scp.plan import run_mrp
from scp.plan.consumption import effective_demand
from scp.validate import validate

from .factory import base, demand, ds, lp

client = TestClient(app, headers={"X-Browser-Key": "tests-browser-key-0001"})


# ---- §5.4 figure 5.2: consumption ------------------------------------------------------------------------------
def _fig52() -> list[tuple[str, DemandRecord]]:
    """Order 100 on 15 Mar; forecast 60 open on 10 Mar and 80 open on 17 Mar."""
    rows = [("F10", date(2027, 3, 10), 60, "forecast"), ("F17", date(2027, 3, 17), 80, "forecast"),
            ("SO", date(2027, 3, 15), 100, "sales_order")]
    return [(rid, DemandRecord(location="P", product="A", date=d, qty=q, kind=k)) for rid, d, q, k in rows]


def _left(out) -> dict[str, float]:
    return {r.source_ref: r.qty for r in out if r.kind == "forecast"}


def test_fig_5_2_backward_then_forward():
    """Guide: 60 consumed from 10 Mar, 40 from 17 Mar; 40 of the 17 Mar forecast still produces stock."""
    out = effective_demand(_fig52(), Strategy.MTS_CONSUME, 7, 7)
    assert _left(out) == {"F17": 40}
    assert sum(r.qty for r in out) == 140  # the order 100 + unconsumed forecast 40: max(forecast, orders)


def test_fig_5_2_backward_only():
    """Mode 1: only the 10 Mar bucket is in reach; the 40 above it is planned on top of the forecast."""
    out = effective_demand(_fig52(), Strategy.MTS_CONSUME, 7, 0)
    assert _left(out) == {"F17": 80}


def test_fig_5_2_forward_only():
    """Mode 3 in SAP's numbering (the guide calls it 4): only 17 Mar is in reach and it is eaten whole."""
    out = effective_demand(_fig52(), Strategy.MTS_CONSUME, 0, 7)
    assert _left(out) == {"F10": 60}


def test_fig_5_2_zero_windows_is_the_double_demand_triangle():
    """Pitfall ②: windows of 0 with spot forecasts: nothing meets, forecast and order are both planned."""
    out = effective_demand(_fig52(), Strategy.MTS_CONSUME, 0, 0)
    assert _left(out) == {"F10": 60, "F17": 80} and sum(r.qty for r in out) == 240


@pytest.mark.parametrize("strategy, total", [(Strategy.MTS, 140), (Strategy.MTS_CONSUME, 140), (Strategy.ATO, 140),
                                             (Strategy.MTO, 100)])
def test_strategy_table_5_2(strategy, total):
    """10: orders are not planning-relevant (forecast only); 40/50: max(forecast, orders); 20: orders only."""
    out = effective_demand(_fig52(), strategy, 7, 7)
    assert sum(r.qty for r in out) == total
    kinds = {r.kind for r in out}
    assert kinds == ({"forecast"} if strategy is Strategy.MTS else {"sales_order"} if strategy is Strategy.MTO
                     else {"forecast", "sales_order"})


def test_forecast_consumed_exactly_once():
    """§20.1 #1: two orders competing for one bucket never consume more than the bucket holds."""
    recs = [("F", DemandRecord(location="P", product="A", date=date(2027, 3, 8), qty=100, period_days=7)),
            ("S1", DemandRecord(location="P", product="A", date=date(2027, 3, 9), qty=70, kind="sales_order")),
            ("S2", DemandRecord(location="P", product="A", date=date(2027, 3, 11), qty=70, kind="sales_order"))]
    out = effective_demand(recs, Strategy.MTS_CONSUME, 3, 3)
    assert _left(out) == {} and sum(r.qty for r in out) == 140   # 100 consumed once, 40 above forecast


def test_demand_above_forecast_increases_production():
    """Strategy 40: an order above the forecast raises supply by the excess."""
    d = base()
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [demand("P", "A", "2026-01-19", 50, period_days=7), demand("P", "A", "2026-01-20", 80, "sales_order",
                                                                              id="SO")]
    made = sum(o.qty for o in run_mrp(ds(d)).orders if o.product == "A")
    assert made == pytest.approx(80)


def test_strategy_50_forecast_supply_is_not_convertible():
    """Strategy 50: supply for the unconsumed forecast is flagged non-convertible (SAP order type VP); the order's
    own supply is convertible."""
    d = base()
    lp(d, "P", "A").update(strategy="ATO", on_hand=0)
    d["demand"] = [demand("P", "A", "2026-01-15", 30), demand("P", "A", "2026-01-16", 10, "sales_order", id="SO")]
    orders = sorted((o.qty, o.convertible) for o in run_mrp(ds(d)).orders if o.product == "A")
    assert orders == [(10, True), (20, False)]


# ---- REGRESSION: an MRP group's strategy also governs the customer channels it supplies (§3.2 MRP 1 / MRP 3) -----
def _channel(d: dict) -> dict:
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "L1", "origin": "P", "destination": "K", "modes": [{"mode": "truck_ftl", "transit_days": 1}]}]
    return d


def test_mrp_group_strategy_reaches_customer_channel():
    d = _channel(base())
    d["mrp_groups"] = [{"id": "G", "strategy": "MTO", "consumption_backward_days": 3}]
    lp(d, "P", "A").update(mrp_group="G", on_hand=0)
    d["demand"] = [demand("K", "A", "2026-01-20", 30, id="F")]
    x = ds(d)
    assert x.demand_lp(("K", "A")).strategy is Strategy.MTO
    assert x.demand_lp(("K", "A")).consumption_backward_days == 3
    assert not [o for o in run_mrp(x).orders if o.product == "A"]   # a forecast on a make-to-order product: ignored
    assert any(i.code == "MTO_WITH_FORECAST" for i in validate(x))


# ---- §2 ② stock is a projection of the movement journal --------------------------------------------------------
def test_stock_is_derived_from_the_journal_on_roll():
    """Opening 200, 80 sold: after the roll the plan starts from 120, read from the journal, never typed."""
    d = _channel(base(horizon=56))
    lp(d, "P", "A").update(on_hand=200)
    d["demand"] = [demand("P", "A", "2026-01-07", 80, "sales_order", id="SO1")]
    d["movements"] = [{"id": "m1", "date": "2026-01-04", "type": "opening", "location": "P", "product": "A", "qty": 200},
                      {"id": "m2", "date": "2026-01-07", "type": "sale", "location": "P", "product": "A", "qty": 80,
                       "reference": "SO1", "counterparty": "K"}]
    new, rep = roll_forward(ds(d), date(2026, 1, 19))
    a = next(x for x in new.location_products if (x.location, x.product) == ("P", "A"))
    assert a.on_hand == pytest.approx(120) and [c.id for c in rep.closed] == ["SO1"]


# ---- REGRESSION: consumption windows that cannot bridge spot forecasts are flagged (§5.4, pitfall ②) -------------
def test_consumption_gap_is_warned():
    d = base(horizon=70)
    d["demand"] = [demand("P", "A", "2026-01-05", 100), demand("P", "A", "2026-02-05", 100)]
    gap = [i for i in validate(ds(d)) if i.code == "CONSUMPTION_GAP"]
    assert len(gap) == 1 and gap[0].severity == "warning" and "2026-01-13" in gap[0].message


@pytest.mark.parametrize("change", ["period", "windows", "strategy", "weekly"])
def test_consumption_gap_not_warned_when_reachable(change):
    d = base(horizon=70)
    d["demand"] = [demand("P", "A", "2026-01-05", 100), demand("P", "A", "2026-02-05", 100)]
    if change == "period":       # each monthly forecast says what it covers
        for x in d["demand"]:
            x["period_days"] = 31
    elif change == "windows":    # at least half the spacing each way
        lp(d, "P", "A").update(consumption_backward_days=16, consumption_forward_days=16)
    elif change == "strategy":   # strategy 10: orders do not consume, nothing to bridge
        lp(d, "P", "A")["strategy"] = "MTS"
    else:                        # weekly spot forecasts reach with the default 7/7
        d["demand"] = [demand("P", "A", f"2026-01-{day:02d}", 25) for day in (5, 12, 19, 26)]
    assert not [i for i in validate(ds(d)) if i.code == "CONSUMPTION_GAP"]


# ---- REGRESSION: the consumption windows explain themselves in the form (UI wording) -----------------------------
def test_consumption_fields_are_described_in_the_schema():
    schema = client.get("/api/schema").json()
    for obj in ("LocationProduct", "MrpGroup"):
        props = schema["$defs"][obj]["properties"]
        for f in ("consumption_backward_days", "consumption_forward_days"):
            text = props[f].get("description", "")
            assert "calendar days" in text.lower(), (obj, f)
    assert "MTS_CONSUME" in schema["$defs"]["LocationProduct"]["properties"]["consumption_backward_days"]["description"]


# ---- §4 trap ① calendar semantics: a monthly forecast is split over working days ---------------------------------
def test_monthly_forecast_split_over_working_days():
    d = base(horizon=35, workdays=[0, 1, 2, 3, 4])
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [demand("P", "A", "2026-01-05", 100, id="F", period_days=28)]
    reqs = [r for r in run_mrp(ds(d)).requirements if r.product == "A" and r.location == "P"]
    assert len(reqs) == 20 and all(r.qty == pytest.approx(5) for r in reqs)   # 4 weeks × 5 days, no saw-tooth
    assert all(r.date.weekday() < 5 for r in reqs)


# ---- §4 trap ③ version discipline: a re-release overwrites, it never adds ------------------------------------------
def test_forecast_release_overwrites_not_adds():
    from .factory import example_dict
    d = example_dict("kitchenware_network")
    fc = client.post("/api/forecast", json=d).json()
    once = client.post("/api/forecast/release", json={"dataset": d, "result": fc}).json()["dataset"]
    twice = client.post("/api/forecast/release", json={"dataset": once, "result": fc}).json()["dataset"]
    total = lambda x: round(sum(r["qty"] for r in x["demand"] if r.get("kind", "forecast") == "forecast"), 3)  # noqa: E731
    assert total(once) == total(twice)


# ---- §4 forecast-error measurement: WMAPE and bias by hand ----------------------------------------------------------
def test_wmape_and_bias_hand_calculated():
    weeks = [(100, 80), (50, 70), (0, 10)]
    recs = [AccuracyRecord(location="P", product="A", start=date(2026, 1, 5 + 7 * i), end=date(2026, 1, 12 + 7 * i),
                           forecast=f, actual=a) for i, (f, a) in enumerate(weeks)]
    rep = accuracy_report(recs)
    assert rep.wmape == pytest.approx(50 / 160)          # Σ|f−a| / Σa
    assert rep.bias == pytest.approx((150 - 160) / 160)  # under-forecast is negative
    assert rep.accuracy == pytest.approx(1 - 50 / 160)


# ---- §17.1 lead-time model: replenishment lead time = supplier time + GR processing --------------------------------
def test_buy_lead_time_arithmetic():
    """Need 30 on 20 Jan, supplier 3 days, GR 2 days, 7-day calendar: order 15 Jan, arrives 18 Jan, usable 20 Jan."""
    d = base()
    lp(d, "P", "C")["gr_processing_days"] = 2
    d["purchasing_sources"][1]["lead_time_days"] = 3
    d["production_sources"] = []
    lp(d, "P", "C")["on_hand"] = 0
    d["demand"] = [demand("P", "C", "2026-01-20", 30)]
    o = next(o for o in run_mrp(ds(d)).orders if o.product == "C")
    assert (o.start_date, o.due_date, o.available_date) == (date(2026, 1, 15), date(2026, 1, 18), date(2026, 1, 20))


def test_transfer_lead_time_arithmetic():
    """A DC fed from the plant over a 2-day lane with GR 1 day: ship 17 Jan for a need on 20 Jan."""
    d = base()
    d["locations"].append({"id": "DC", "type": "dc"})
    d["lanes"] = [{"id": "P-DC", "origin": "P", "destination": "DC", "modes": [{"mode": "truck_ftl", "transit_days": 2}]}]
    d["location_products"].append({"location": "DC", "product": "A", "gr_processing_days": 1})
    d["demand"] = [demand("DC", "A", "2026-01-20", 5)]
    o = next(o for o in run_mrp(ds(d)).orders if o.location == "DC")
    assert (o.start_date, o.due_date, o.available_date) == (date(2026, 1, 17), date(2026, 1, 19), date(2026, 1, 20))


# ---- §3.2 material-master fields that drive planning --------------------------------------------------------------
def test_mrp_type_none_is_never_replenished():
    d = base()
    lp(d, "P", "A").update(mrp_type="none", on_hand=0)
    d["demand"] = [demand("P", "A", "2026-01-20", 50)]
    p = run_mrp(ds(d))
    assert not [o for o in p.orders if o.product == "A"] and any(e.code == "STOCKOUT" for e in p.exceptions)


def test_reorder_point_triggers_below_the_point():
    d = base()
    lp(d, "P", "A").update(mrp_type="reorder_point", reorder_point=20, on_hand=25)
    d["demand"] = [demand("P", "A", "2026-01-12", 10)]
    orders = [o for o in run_mrp(ds(d)).orders if o.product == "A"]
    assert [o.qty for o in orders] == [5] and orders[0].need_date == date(2026, 1, 12)


def test_expired_production_version_is_not_used_silently():
    """§3 deep dive: no valid production version for the date: no order is planned and the plan says why."""
    d = base()
    d["production_sources"][0]["valid_to"] = "2026-01-08"
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [demand("P", "A", "2026-01-20", 30)]
    p = run_mrp(ds(d))
    assert not [o for o in p.orders if o.product == "A"]
    assert {"NO_VALID_SOURCE"} <= {e.code for e in p.exceptions}
    assert any(i.code == "SOURCE_NOT_VALID_IN_HORIZON" for i in validate(ds(d)))


def test_safety_stock_and_safety_time_double_buffer_warned():
    d = base()
    lp(d, "P", "A").update(safety_time_days=2, safety_stock={"method": "fixed", "qty": 5})
    assert any(i.code == "SS_AND_SAFETY_TIME" for i in validate(ds(d)))
