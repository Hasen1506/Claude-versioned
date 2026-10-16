"""Forecast value add (ENTERPRISE_PLAN 4.2): every release keeps what each layer of the forecast said (naïve,
statistical, events and new products, the planners' overrides); once a period has sold, each layer is judged
against its sales, in total, per product family and per planner."""
from __future__ import annotations

import datetime as dt

import pytest

from scp.demand import release, run_forecast, value_add
from scp.model import Dataset
from scp.validate import validate

from .test_audit_fixes import client


def shop(**kw) -> dict:
    """A shop selling a pump (family Pumps) and a seal (no family), weekly, planning from Monday 19 October 2026."""
    doc = {
        "schema_version": "1",
        "settings": {"company_name": "Value add test", "planning_start": "2026-10-19", "horizon_days": 42},
        "locations": [{"id": "CU", "name": "Shop", "type": "customer"}],
        "products": [{"id": "A", "name": "Pump", "family": "Pumps", "type": "FG", "price": 10},
                     {"id": "B", "name": "Seal", "type": "FG", "price": 1}],
        "forecasting": {"models": ["moving_average"]},
    }
    doc.update(kw)
    return doc


def snap(prod: str, start: str, naive: float, stat: float, adj: float, final: float, author: str = "",
         overridden: bool | None = None) -> dict:
    s = dt.date.fromisoformat(start)
    return {"location": "CU", "product": prod, "start": start, "end": (s + dt.timedelta(days=7)).isoformat(),
            "made": (s - dt.timedelta(days=7)).isoformat(), "naive": naive, "statistical": stat, "adjusted": adj,
            "final": final, "author": author, "overridden": bool(author) if overridden is None else overridden}


def kept() -> Dataset:
    history = [{"location": "CU", "product": "A", "date": "2026-09-28", "qty": 80},
               {"location": "CU", "product": "A", "date": "2026-10-05", "qty": 100},
               {"location": "CU", "product": "A", "date": "2026-10-12", "qty": 60},
               {"location": "CU", "product": "A", "date": "2026-10-14", "qty": 50},
               {"location": "CU", "product": "B", "date": "2026-10-06", "qty": 50},
               # sold after the planning start: not a closed period, not counted
               {"location": "CU", "product": "A", "date": "2026-10-20", "qty": 999}]
    snaps = [snap("A", "2026-10-05", 80, 90, 95, 120, "ana"),
             snap("A", "2026-10-12", 1, 1, 1, 1),                  # replaced by the row after it (last wins)
             snap("A", "2026-10-12", 100, 105, 105, 105),
             snap("B", "2026-10-05", 40, 60, 60, 52, "ben"),
             snap("B", "2026-10-12", 50, 10, 10, 10, overridden=True),  # no sales: actual 0; overridden, no name
             snap("A", "2026-10-19", 110, 110, 110, 110),           # not sold yet
             snap("B", "2026-10-26", 0, 5, 5, 5)]
    return Dataset.model_validate(shop(history=history, forecast_snapshots=snaps))


# ------------------------------------------------------------------------------------------------ the analysis
def test_each_layer_is_judged_against_the_sales_of_the_periods_that_have_sold():
    va = value_add(kept())
    assert va.period == "week" and va.lag == 1
    assert va.measured_to == dt.date(2026, 10, 19) and va.measured == 4 and va.waiting == 2
    t = va.total
    assert t.periods == 4 and t.actual == 260 and t.overrides == 3 and t.improved == 1
    by = {s.layer: s for s in t.layers}
    # absolute misses over the four periods: naïve 20+10+10+50, statistical 10+5+10+10, events 5+5+10+10,
    # consensus 20+5+2+10, all over the 260 sold
    assert by["naive"].wape == pytest.approx(90 / 260)
    assert by["statistical"].wape == pytest.approx(35 / 260)
    assert by["adjusted"].wape == pytest.approx(30 / 260)
    assert by["final"].wape == pytest.approx(37 / 260)
    assert [by[k].forecast for k in ("naive", "statistical", "adjusted", "final")] == [270, 265, 270, 287]
    assert by["final"].bias == pytest.approx(27 / 260) and by["statistical"].bias == pytest.approx(5 / 260)
    assert by["naive"].value_add is None
    assert by["statistical"].value_add == pytest.approx(55 / 260)
    assert by["adjusted"].value_add == pytest.approx(5 / 260)
    assert by["final"].value_add == pytest.approx(-7 / 260)       # the overrides made it worse, in total


def test_per_family_per_planner_per_period_and_the_overrides_that_cost_most():
    va = value_add(kept())
    assert [(f.label, f.periods, f.actual) for f in va.families] == [("Pumps", 2, 210), ("No family", 2, 50)]
    pumps = {s.layer: s for s in va.families[0].layers}
    assert pumps["final"].wape == pytest.approx(25 / 210) and pumps["adjusted"].wape == pytest.approx(10 / 210)
    # each planner on the periods they overrode: ana moved 95 to 120 against 100 sold, ben 60 to 52 against 50
    ana, ben, unnamed = va.planners
    assert (ana.label, ana.periods, ana.overrides, ana.improved) == ("ana", 1, 1, 0)
    assert {s.layer: s for s in ana.layers}["final"].value_add == pytest.approx(-0.15)
    assert (ben.label, ben.overrides, ben.improved) == ("ben", 1, 1)
    assert {s.layer: s for s in ben.layers}["final"].value_add == pytest.approx(0.16)
    # an override typed without a name still counts, under "Not named" (last); with nothing sold it has no WAPE
    assert (unnamed.label, unnamed.overrides, unnamed.improved, unnamed.actual) == ("Not named", 1, 0, 0)
    assert {s.layer: s for s in unnamed.layers}["final"].wape is None
    assert [(p.start, p.actual) for p in va.periods] == [(dt.date(2026, 10, 5), 150), (dt.date(2026, 10, 12), 110)]
    assert va.periods[0].statistical_wape == pytest.approx(20 / 150) and va.periods[0].final_wape == pytest.approx(22 / 150)
    assert va.periods[1].final_wape == pytest.approx(15 / 110)
    # only an override that moved the forecast away from the sales costs; ben's helped
    assert [(c.author, c.product, c.cost) for c in va.costly] == [("ana", "A", 15)]


def test_nothing_kept_and_nothing_sold_yet_say_so():
    va = value_add(Dataset.model_validate(shop()))
    assert va.measured == 0 and va.total.layers[0].wape is None and "No forecast has been released" in va.notes[0]
    d = kept()
    d = d.model_copy(update={"history": []})
    va = value_add(d)
    assert va.measured == 0 and va.waiting == 6 and "waiting for their sales" in va.notes[0]


# ------------------------------------------------------------------------------------------------ the release keeps it
def weekly(n: int, last: str, qty: float = 100) -> list[dict]:
    """``n`` weeks of 90 and 110 in turn, ending with a week of 400: an outlier the forecast cleanses, but the naïve
    forecast takes as sold."""
    end = dt.date.fromisoformat(last)
    return [{"location": "CU", "product": "A", "date": (end - dt.timedelta(weeks=n - 1 - i)).isoformat(),
             "qty": (qty - 10 if i % 2 else qty + 10) if i < n - 1 else qty + 300} for i in range(n)]


def test_a_release_keeps_each_layer_from_the_lag_on_and_names_the_planner():
    d = Dataset.model_validate(shop(
        history=weekly(20, "2026-10-12"),
        events=[{"id": "EV", "kind": "promo", "start": "2026-11-02", "end": "2026-11-08", "lift": 0.2}],
        overrides=[{"location": "CU", "product": "A", "date": "2026-10-27", "qty": 150, "author": "ana"}]))
    fc = run_forecast(d)
    new, _ = release(d, fc)
    s = fc.series[0]
    rows = {k.start: k for k in new.forecast_snapshots}
    # lag 1: the week planning starts in is not kept; the next five are, with the planning start they were kept on
    assert sorted(rows) == [p.start for p in s.forecast[1:]]
    assert all(k.made == dt.date(2026, 10, 19) and k.end == k.start + dt.timedelta(days=7) for k in rows.values())
    assert all(k.naive == 400 for k in rows.values())               # the last week's sales, as sold
    assert s.history[-1].cleaned < 400                              # (the forecast itself cleansed them)
    w2, w3 = rows[dt.date(2026, 10, 26)], rows[dt.date(2026, 11, 2)]
    p3 = s.forecast[3]
    assert w3.statistical == pytest.approx(p3.statistical, abs=1e-3) and w3.adjusted == pytest.approx(p3.statistical * 1.2, abs=1e-3)
    assert w3.final == pytest.approx(w3.adjusted, abs=1) and w3.author == ""   # whole units, running total
    assert (w2.final, w2.author, w2.overridden) == (150, "ana", True) and not w3.overridden
    # the fingerprint of what the forecast is made from leaves the kept forecasts and the lag out
    assert not any(i.code == "FORECAST_INPUTS_CHANGED" for i in validate(new))
    lagged = new.model_copy(update={"forecasting": new.forecasting.model_copy(update={"fva_lag": 2})})
    assert not any(i.code == "FORECAST_INPUTS_CHANGED" for i in validate(lagged))


def test_a_later_release_replaces_the_far_periods_and_freezes_the_near_ones_then_they_are_judged():
    first = Dataset.model_validate(shop(history=weekly(20, "2026-10-12"),
                                        overrides=[{"location": "CU", "product": "A", "date": "2026-10-26",
                                                    "qty": 150, "author": "ana"}]))
    one, _ = release(first, run_forecast(first))
    # two weeks on: the weeks of 19 and 26 October have sold, and the forecast is released again without the override
    later = one.model_dump(mode="json")
    later["settings"]["planning_start"] = "2026-11-02"
    later["history"] += [{"location": "CU", "product": "A", "date": "2026-10-19", "qty": 90},
                         {"location": "CU", "product": "A", "date": "2026-10-26", "qty": 170}]
    later["overrides"] = []
    two_in = Dataset.model_validate(later)
    two, _ = release(two_in, run_forecast(two_in))
    rows = {k.start: k for k in two.forecast_snapshots}
    # 26 October was one week away at the first release, and is within the lag of nothing later: it stays as kept
    assert (rows[dt.date(2026, 10, 26)].made, rows[dt.date(2026, 10, 26)].final) == (dt.date(2026, 10, 19), 150)
    # 2 November is the period the second release starts in: frozen as the first release kept it
    assert rows[dt.date(2026, 11, 2)].made == dt.date(2026, 10, 19)
    # 9 November on: replaced by the second release, without the override
    assert rows[dt.date(2026, 11, 9)].made == dt.date(2026, 11, 2) and rows[dt.date(2026, 11, 9)].naive == 170
    assert dt.date(2026, 10, 19) not in rows                       # never one week away when released
    va = value_add(two)
    assert va.measured == 1 and va.measured_to == dt.date(2026, 11, 2)
    t = {s.layer: s for s in va.total.layers}
    assert va.total.actual == 170 and t["final"].wape == pytest.approx(20 / 170)   # 150 against 170 sold
    assert t["adjusted"].wape > t["final"].wape                    # the forecast without the override said less
    assert va.planners[0].label == "ana" and va.planners[0].improved == 1


def test_lag_zero_keeps_the_period_planning_starts_in():
    d = Dataset.model_validate(shop(history=weekly(20, "2026-10-12"), forecasting={"models": ["moving_average"],
                                                                                  "fva_lag": 0}))
    new, _ = release(d, run_forecast(d))
    assert min(k.start for k in new.forecast_snapshots) == dt.date(2026, 10, 19)


def test_value_add_over_http():
    r = client.post("/api/forecast/value-add", json=kept().model_dump(mode="json"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["measured"] == 4 and [p["label"] for p in body["planners"]] == ["ana", "ben", "Not named"]
    assert body["costly"][0]["cost"] == 15
