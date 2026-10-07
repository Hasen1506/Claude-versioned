"""Property-based forecast release: releasing a forecast never changes history.

For any sales history and any demand already in the company (hand-typed forecasts, earlier releases, customer orders,
records in the past), running the forecast and releasing it:

* leaves the sales history, the stock journal and every other part of the company exactly as it was
* never touches a customer order, nor anything dated before the planning start (that is history too)
* never touches the forecast of a series it does not release
* writes nothing before the planning start and nothing negative
* is idempotent: releasing the same result again changes nothing more
* does not modify the company it reads (running the forecast is side-effect free)"""
from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, note
from hypothesis import strategies as st

from scp.demand import release, run_forecast
from scp.model import DemandKind

from .factory import START, base, ds

PLAN_START = date.fromisoformat(START)


def _history(loc: str, prod: str, values: list[float]) -> list[dict]:
    first = PLAN_START - timedelta(weeks=len(values))
    return [{"location": loc, "product": prod, "date": (first + timedelta(weeks=i)).isoformat(), "qty": v}
            for i, v in enumerate(values)]


series = st.lists(st.integers(0, 300).map(float), min_size=12, max_size=40)
record = st.fixed_dictionaries({
    "location": st.just("P"), "product": st.sampled_from(["A", "B"]),
    "date": st.integers(-30, 50).map(lambda n: (PLAN_START + timedelta(days=n)).isoformat()),
    "qty": st.integers(1, 500).map(float),
    "kind": st.sampled_from(["forecast", "forecast", "sales_order"]),
    "released": st.booleans(),
})


def _key(d) -> tuple:
    return (d.location, d.product, d.date, d.qty, d.kind.value, d.released, d.period_days)


@given(a=series, b=st.one_of(st.none(), series), existing=st.lists(record, max_size=8), only_first=st.booleans())
def test_a_forecast_release_never_changes_history(a, b, existing, only_first):
    d = base(horizon=56)
    d["products"][0]["price"] = 100
    d["history"] = _history("P", "A", a) + (_history("P", "B", b) if b is not None else [])
    for r in existing:
        if r["kind"] == "sales_order":
            r = {k: v for k, v in r.items() if k != "released"}
        d["demand"].append(r)
    x = ds(d)
    before = x.model_dump_json()
    res = run_forecast(x)
    assert x.model_dump_json() == before, "running the forecast modified the company"
    keys = [res.series[0].key] if only_first and res.series else None
    new, info = release(x, res, keys)
    note(f"released {info.records} records for {info.series} series; replaced {info.replaced}")
    # 1. every other part of the company is untouched: history, movements, orders, master data …
    for name in type(x).model_fields:
        if name in ("demand", "forecasting"):
            continue
        assert getattr(new, name) == getattr(x, name), f"release changed {name}"
    released = {(s.location, s.product) for s in res.series if keys is None or s.key in keys}
    old = [_key(r) for r in x.demand]
    kept = [_key(r) for r in new.demand]
    for r in x.demand:
        k = _key(r)
        must_stay = (r.kind is not DemandKind.FORECAST                                  # customer orders
                     or ((r.location, r.product) not in released and not (keys is None and r.released)))
        if must_stay:
            assert k in kept, f"release removed {k}"
    # 2. what it adds is a forecast, positive, flagged released, from the planning start on
    added = [r for r in new.demand if _key(r) not in old or r.released]
    for r in added:
        if r.kind is DemandKind.FORECAST and r.released and _key(r) not in old:
            assert r.date >= PLAN_START and r.qty > 0
    assert all(r.qty > 0 for r in new.demand if r.released and _key(r) not in old)
    # 3. history in the strict sense: nothing dated before the planning start changes except released forecasts the
    # same release replaces
    past_before = sorted(k for k, r in zip(old, x.demand, strict=True)
                         if r.date < PLAN_START and not (r.kind is DemandKind.FORECAST
                                                         and ((r.location, r.product) in released
                                                              or (keys is None and r.released))))
    past_after = sorted(_key(r) for r in new.demand if r.date < PLAN_START)
    assert all(k in past_after for k in past_before)
    # 4. idempotent
    again, _ = release(new, res, keys)
    assert sorted(map(_key, again.demand)) == sorted(map(_key, new.demand))
