"""Planning strategies for variants and assemblies (ENTERPRISE_PLAN 4.3, S/4 guide §5.2, §5.4).

* Planning material (strategies 60/63): variants forecast once through a base product; their orders use the base's
  forecast up, each with its conversion factor, and the base's own orders only plan the parts the variants share.
* Planning at assembly level (strategy 70): a forecast on a sub-assembly is used up by its parents' dependent
  requirements instead of being planned on top of them.
* The strategy advisor: the days customers wait against the time to deliver from stock, to assemble and to make
  from scratch.
"""
from __future__ import annotations

import datetime as dt

import pytest

from scp.demand import release, run_forecast, value_add
from scp.model import Dataset
from scp.plan import run_mrp
from scp.plan.advisor import strategy_advice
from scp.plan.rates import horizon_flows
from scp.network import build_graph
from scp.validate import validate

from .test_audit_fixes import client


def mixers(**kw) -> dict:
    """A plant making a mixer in red and blue, each from one motor bought in ten days, shipped to the trade in two.
    The base mixer (the planning material) is made of the same motor: its forecast plans the motors the variants
    share. Planning from Monday 19 October 2026."""
    doc = {
        "schema_version": "1",
        "settings": {"company_name": "Variant shop", "planning_start": "2026-10-19", "horizon_days": 42},
        "locations": [{"id": "P", "name": "Plant", "type": "plant"}, {"id": "S", "name": "Supplier", "type": "supplier"},
                      {"id": "CU", "name": "Trade", "type": "customer"}],
        "lanes": [{"id": "L1", "origin": "P", "destination": "CU", "modes": [{"mode": "truck_ftl", "transit_days": 2}]}],
        "products": [{"id": "BASE", "name": "Mixer", "type": "FG"},
                     {"id": "RED", "name": "Mixer red", "type": "FG", "planning_material": "BASE"},
                     {"id": "BLUE", "name": "Mixer blue twin pack", "type": "FG", "planning_material": "BASE",
                      "planning_factor": 2},
                     {"id": "MOTOR", "name": "Motor", "type": "RM"}],
        "production_sources": [
            {"id": f"M-{p}", "location": "P", "product": p, "fixed_lead_time_workdays": 1,
             "components": [{"product": "MOTOR", "qty": 2 if p == "BLUE" else 1}]} for p in ("BASE", "RED", "BLUE")],
        "purchasing_sources": [{"id": "B-MOTOR", "location": "P", "product": "MOTOR", "supplier": "S",
                                "lead_time_days": 10, "price": 5}],
        "location_products": [{"location": "P", "product": p, "lot_sizing": {"policy": "L4L"}}
                              for p in ("BASE", "RED", "BLUE", "MOTOR")],
        "demand": [{"location": "CU", "product": "BASE", "date": "2026-10-26", "qty": 100, "kind": "forecast",
                    "period_days": 7}],
    }
    for k, v in kw.items():
        doc[k] = doc[k] + v if isinstance(v, list) and k in doc else v
    return doc


def so(oid: str, prod: str, day: str, qty: float, **kw) -> dict:
    return {"id": oid, "location": "CU", "product": prod, "date": day, "qty": qty, "kind": "sales_order", **kw}


def total(plan, kind: str, prod: str) -> float:
    return sum(o.qty for o in plan.orders if o.kind == kind and o.product == prod)


# ------------------------------------------------------------------------------------------------ planning material
def test_variant_orders_use_up_the_base_forecast_each_with_its_factor():
    ds = Dataset.model_validate(mixers(demand=[so("SO1", "RED", "2026-10-27", 30), so("SO2", "BLUE", "2026-10-28", 20)]))
    plan = run_mrp(ds)
    # 100 base forecast; red 30 uses up 30, the blue twin pack 20 × 2 = 40: 30 base left to plan
    base = [r for r in plan.requirements if (r.location, r.product) == ("CU", "BASE")]
    assert sum(r.qty for r in base) == pytest.approx(30) and sum(r.consumed_forecast for r in base) == pytest.approx(70)
    assert total(plan, "make", "BASE") == pytest.approx(30)
    assert total(plan, "make", "RED") == pytest.approx(30) and total(plan, "make", "BLUE") == pytest.approx(20)
    # motors: 30 for the base left, 30 red and 2 × 20 blue = 100, not the 170 of forecast and orders both
    assert total(plan, "buy", "MOTOR") == pytest.approx(100)
    # the base is never made or shipped itself: its orders plan parts, they are not to be converted
    assert all(not o.convertible for o in plan.orders if o.product == "BASE")
    assert all(o.convertible for o in plan.orders if o.product != "BASE")
    # without the planning material each variant's order is planned on top of the base forecast
    plain = mixers(demand=[so("SO1", "RED", "2026-10-27", 30), so("SO2", "BLUE", "2026-10-28", 20)])
    for p in plain["products"]:
        p.pop("planning_material", None)
    assert total(run_mrp(Dataset.model_validate(plain)), "buy", "MOTOR") == pytest.approx(170)


def test_a_variant_order_outside_the_windows_uses_nothing_up_and_deliveries_reduce_the_base():
    # an order four weeks after the forecast week reaches no forecast: the whole 100 is planned beside it
    far = run_mrp(Dataset.model_validate(mixers(demand=[so("SO1", "RED", "2026-11-23", 30)])))
    assert total(far, "make", "BASE") == pytest.approx(100)
    # a red order for 50, 20 of it already delivered: the delivered 20 reduce the base, the open 30 use it up
    part = run_mrp(Dataset.model_validate(mixers(demand=[so("SO1", "RED", "2026-10-27", 30, ordered_qty=50)])))
    assert total(part, "make", "BASE") == pytest.approx(50)
    # a twin-pack order for 20, 5 delivered: 2 × 5 delivered and 2 × 15 open, 60 of the base's 100 used
    twin = run_mrp(Dataset.model_validate(mixers(demand=[so("SO1", "BLUE", "2026-10-27", 15, ordered_qty=20)])))
    assert total(twin, "make", "BASE") == pytest.approx(60)
    # and a closed blue order delivered in the week: 15 twin packs take 30
    closed = mixers(closed_orders=[{"kind": "sales", "id": "SO0", "location": "CU", "product": "BLUE", "ordered_qty": 15,
                                    "delivered_qty": 15, "due_date": "2026-10-26", "closed_on": "2026-10-19"}])
    assert total(run_mrp(Dataset.model_validate(closed)), "make", "BASE") == pytest.approx(70)


def weekly(prod: str, qty: float, weeks: int = 16) -> list[dict]:
    end = dt.date(2026, 10, 12)
    return [{"location": "CU", "product": prod, "date": (end - dt.timedelta(weeks=weeks - 1 - i)).isoformat(),
             "qty": qty} for i in range(weeks)]


def test_the_variants_sales_are_forecast_once_on_the_base_and_value_add_reads_them_there():
    d = mixers(demand=[], history=weekly("RED", 30) + weekly("BLUE", 10), forecasting={"models": ["moving_average"]})
    ds = Dataset.model_validate(d)
    fc = run_forecast(ds)
    # one series, the base's: 30 red + 2 × 10 blue = 50 a week
    assert [(s.location, s.product) for s in fc.series] == [("CU", "BASE")]
    s = fc.series[0]
    assert s.forecast[1].final == pytest.approx(50, abs=1)
    assert any("Mixer red" in n and "Mixer blue twin pack × 2" in n for n in s.notes)
    new, rel = release(ds, fc)
    assert {d.product for d in new.demand} == {"BASE"} and rel.series == 1
    # the kept forecast is judged against the variants' sales, in the base's units
    later = new.model_dump(mode="json")
    later["settings"]["planning_start"] = "2026-11-02"
    later["history"] += [{"location": "CU", "product": "RED", "date": "2026-10-26", "qty": 40},
                         {"location": "CU", "product": "BLUE", "date": "2026-10-27", "qty": 10}]
    va = value_add(Dataset.model_validate(later))
    assert va.measured == 1 and va.total.actual == pytest.approx(60)


def test_checks_name_a_chain_a_variant_forecast_and_an_override_on_a_variant():
    d = mixers(products=[{"id": "MINI", "name": "Mini red", "type": "FG", "planning_material": "RED"}],
               demand=[{"location": "CU", "product": "RED", "date": "2026-10-26", "qty": 5, "kind": "forecast"}],
               overrides=[{"location": "CU", "product": "RED", "date": "2026-10-26", "qty": 9}])
    ds = Dataset.model_validate(d)
    codes = {(i.code, i.object_id) for i in validate(ds)}
    assert ("PLANNING_MATERIAL_CHAIN", "MINI") in codes and ("VARIANT_FORECAST", "CU/RED") in codes
    assert any(i.code == "OVERRIDE_WITHOUT_FORECAST" and "planning material BASE" in i.message for i in validate(ds))
    # one level only: the mini plans through nothing; the red still plans through the base
    assert "MINI" not in ds.planning_base and ds.planning_base["RED"] == ("BASE", 1.0)
    with pytest.raises(ValueError, match="its own planning material"):
        Dataset.model_validate(mixers(products=[{"id": "X", "type": "FG", "planning_material": "X"}]))
    bad = mixers(products=[{"id": "Y", "type": "FG", "planning_material": "NOPE"}])
    assert any(i.code == "REF_UNKNOWN" and i.object_id == "Y" for i in validate(Dataset.model_validate(bad)))


# ------------------------------------------------------------------------------------------------ assembly level
def pumps(strategy: str = "ASSEMBLY", **kw) -> dict:
    """A pump (made to order) of two motor units; the motor unit is forecast 100 a week to build it ahead, and made in
    five working days from copper bought in ten."""
    doc = {
        "schema_version": "1",
        "settings": {"company_name": "Assembly shop", "planning_start": "2026-10-19", "horizon_days": 42},
        "locations": [{"id": "P", "name": "Plant", "type": "plant"}, {"id": "S", "name": "Supplier", "type": "supplier"}],
        "products": [{"id": "PUMP", "name": "Pump", "type": "FG"}, {"id": "SUB", "name": "Motor unit", "type": "SFG"},
                     {"id": "CU", "name": "Copper", "type": "RM"}],
        "production_sources": [
            {"id": "PF", "location": "P", "product": "PUMP", "fixed_lead_time_workdays": 1,
             "components": [{"product": "SUB", "qty": 2}]},
            {"id": "PS", "location": "P", "product": "SUB", "fixed_lead_time_workdays": 5,
             "components": [{"product": "CU", "qty": 1}]}],
        "purchasing_sources": [{"id": "BC", "location": "P", "product": "CU", "supplier": "S", "lead_time_days": 10,
                                "price": 1}],
        "location_products": [
            {"location": "P", "product": "PUMP", "lot_sizing": {"policy": "L4L"}, "strategy": "MTO"},
            {"location": "P", "product": "SUB", "lot_sizing": {"policy": "L4L"}, "strategy": strategy},
            {"location": "P", "product": "CU", "lot_sizing": {"policy": "L4L"}}],
        "demand": [{"location": "P", "product": "SUB", "date": "2026-11-02", "qty": 100, "kind": "forecast",
                    "period_days": 7},
                   {"location": "P", "product": "SUB", "date": "2026-11-09", "qty": 100, "kind": "forecast",
                    "period_days": 7},
                   {"id": "SO1", "location": "P", "product": "PUMP", "date": "2026-11-06", "qty": 30,
                    "kind": "sales_order"}],
    }
    for k, v in kw.items():
        doc[k] = doc.get(k, []) + v if isinstance(v, list) else v
    return doc


def test_the_parents_requirements_use_up_the_assembly_forecast():
    on_top = run_mrp(Dataset.model_validate(pumps("MTS_CONSUME")))
    used = run_mrp(Dataset.model_validate(pumps()))
    # the pump order needs 60 motor units on Thursday 5 November: planned on top of the 200 forecast (260), or
    # taken from the forecast of that week (200)
    assert total(on_top, "make", "SUB") == pytest.approx(260)
    assert total(used, "make", "SUB") == pytest.approx(200) and total(used, "buy", "CU") == pytest.approx(200)
    sub = [r for r in used.requirements if r.product == "SUB" and r.kind == "forecast"]
    wk1 = [r for r in sub if dt.date(2026, 11, 2) <= r.date < dt.date(2026, 11, 9)]
    # what is left of that week's forecast is spread evenly over its five working days
    assert sum(r.qty for r in wk1) == pytest.approx(40) and {round(r.qty, 6) for r in wk1} == {8.0}
    assert sum(r.consumed_forecast for r in sub) == pytest.approx(60)
    # the safety-stock and lot-size rate counts the larger of the two, not both: 200 forecast over the 42 days
    g = build_graph(Dataset.model_validate(pumps()))
    assert horizon_flows(Dataset.model_validate(pumps()), g).mean[("P", "SUB")] == pytest.approx(200 / 42)
    assert horizon_flows(Dataset.model_validate(pumps("MTS_CONSUME")), g).mean[("P", "SUB")] == pytest.approx(260 / 42)


def test_a_parents_need_beyond_the_forecast_is_planned_on_top_and_a_late_one_reaches_no_forecast():
    # 50 more pumps on Wednesday need 100 motor units on Tuesday: with the 60 on Thursday, 160 in the first week.
    # The first week's forecast covers 100, the next week's (forward, within seven days of Thursday) the other 60
    big = run_mrp(Dataset.model_validate(pumps(demand=[so("SO2", "PUMP", "2026-11-04", 50) | {"location": "P"}])))
    assert total(big, "make", "SUB") == pytest.approx(200)
    # 100 more pumps need 260 motor units in all, more than the 200 forecast: the rate counts the 260
    more = Dataset.model_validate(pumps(demand=[so("SO2", "PUMP", "2026-11-04", 100) | {"location": "P"}]))
    assert horizon_flows(more, build_graph(more)).mean[("P", "SUB")] == pytest.approx(260 / 42)
    # an order on Friday 27 November needs 20 on the Thursday, eleven days past the last forecast week: it reaches
    # none and is planned on top
    late = run_mrp(Dataset.model_validate(pumps(demand=[so("SO3", "PUMP", "2026-11-27", 10) | {"location": "P"}])))
    assert total(late, "make", "SUB") == pytest.approx(200 + 20)


def test_a_firm_parent_orders_reservation_uses_the_forecast_up_too():
    firm = pumps(demand=[], receipts=[{"id": "PO-PUMP", "kind": "production", "location": "P", "product": "PUMP",
                                      "qty": 20, "due_date": "2026-11-06", "source": "PF",
                                      "reservations": [{"location": "P", "product": "SUB", "qty": 40,
                                                        "date": "2026-11-05"}]}])
    firm["demand"] = [d for d in firm["demand"] if d["kind"] == "forecast"]
    assert total(run_mrp(Dataset.model_validate(firm)), "make", "SUB") == pytest.approx(200)


# ------------------------------------------------------------------------------------------------ strategy advisor
def advised(wait: float | None, strategy: str = "MTS_CONSUME", prod: str = "RED") -> object:
    d = mixers(demand=[so("SO1", "RED", "2026-10-27", 30), so("SO2", "BLUE", "2026-10-28", 20)])
    for p in d["products"]:
        if p["id"] == prod:
            p["customer_wait_days"] = wait
    for lp in d["location_products"]:
        if lp["product"] == prod:
            lp["strategy"] = strategy
    rows = {r.product: r for r in strategy_advice(Dataset.model_validate(d)).rows}
    assert "BASE" not in rows                     # the planning material is never sold itself
    return rows[prod]


def test_the_advisor_compares_the_wait_with_delivering_assembling_and_making_from_scratch():
    r = advised(20)
    # two days to deliver; a working day to make (1.4 calendar days on a five-day week), so 3.4 to assemble and
    # deliver; ten days for the motor before that: 13.4 from scratch
    assert (r.sold_at, r.kept_at, r.set_at, r.made) == ("CU", "P", "P", True)
    assert (r.from_stock_days, r.assemble_days, r.scratch_days) == (2.0, 3.4, 13.4)
    assert (r.advised, r.fits) == ("MTO", True) and "make it to order" in r.reason
    assert advised(13.4).advised == "MTO" and advised(13.3).advised == "ATO"
    assert (advised(5).advised, advised(3.4).advised, advised(3.3).advised) == ("ATO", "ATO", "MTS_CONSUME")
    # today's strategy against the wait: made to order needs 13.4 days, assembled to order 3.4, from stock 2
    assert advised(5, "MTO").fits is False and "orders will be late" in advised(5, "MTO").reason
    assert advised(5, "ATO").fits is True and advised(3, "ATO").fits is False
    assert advised(1).fits is False and advised(2).fits is True
    # no wait given: no advice
    none = advised(None)
    assert (none.advised, none.fits) == (None, None)


def test_a_bought_product_has_nothing_to_assemble():
    d = mixers(demand=[so("SO1", "MOTOR", "2026-10-27", 5)], lanes=[])
    for p in d["products"]:
        if p["id"] == "MOTOR":
            p["customer_wait_days"] = 4
    d["demand"] = [x | {"location": "P"} for x in d["demand"] if x["product"] == "MOTOR"]
    r = {x.product: x for x in strategy_advice(Dataset.model_validate(d)).rows}["MOTOR"]
    assert (r.made, r.assemble_days, r.scratch_days, r.from_stock_days) == (False, None, 10.0, 0.0)
    assert r.advised == "MTS_CONSUME" and "getting it takes 10" in r.reason


def test_advice_over_http():
    d = mixers(demand=[so("SO1", "RED", "2026-10-27", 30)])
    res = client.post("/api/plan/strategy-advice", json=d)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [r["product"] for r in body["rows"]] == ["RED"] and "customer wait days" in body["notes"][0]


def test_through_a_warehouse_from_stock_is_the_last_leg_and_assembling_adds_every_leg():
    # the plant ships to a warehouse in three days and the warehouse to the trade in two
    d = mixers(demand=[so("SO1", "RED", "2026-10-27", 30)],
               locations=[{"id": "DC", "name": "Warehouse", "type": "dc"}],
               lanes=[{"id": "L2", "origin": "P", "destination": "DC", "modes": [{"mode": "truck_ftl", "transit_days": 3}]}])
    d["lanes"] = [ln | {"origin": "DC"} if ln["id"] == "L1" else ln for ln in d["lanes"]]
    r = {x.product: x for x in strategy_advice(Dataset.model_validate(d)).rows}["RED"]
    assert (r.sold_at, r.kept_at, r.set_at) == ("CU", "P", "P")
    assert (r.from_stock_days, r.assemble_days, r.scratch_days) == (2.0, 6.4, 16.4)
    # a record of it at the warehouse: the trade's demand is planned with the warehouse's strategy, set there
    d["location_products"].append({"location": "DC", "product": "RED", "strategy": "MTO"})
    r = {x.product: x for x in strategy_advice(Dataset.model_validate(d)).rows}["RED"]
    assert (r.kept_at, r.set_at, r.strategy) == ("P", "DC", "MTO")
