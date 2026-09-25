"""Regression tests for the defects the end-to-end scenarios (scp.scenarios) exposed. Each test is the
smallest dataset that shows the defect; the scenario named in the docstring shows it in context."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from scp.actuals import firm_orders, roll_forward
from scp.actuals.stock import accuracy_records
from scp.demand import run_forecast
from scp.inventory import ddmrp, run_inventory
from scp.model import Dataset, DemandRecord, InventorySettings
from scp.network import build_graph
from scp.plan import run_mrp
from scp.plan.safety import SSInputs, statistical_ss
from scp.promise import check_order
from scp.sop import release_sop, run_sop
from scp.validate import blocks_demand, validate

from .factory import START, base, demand, ds, lp

D = date.fromisoformat


def _node(r, loc, prod):
    return next(n for n in r.nodes if (n.location, n.product) == (loc, prod))


# ---- demand ---------------------------------------------------------------------------------------------
def test_abc_ranks_on_cleansed_revenue():
    """S4: the forecast cleansed a freak order away, but the ABC class still counted it."""
    d = base()
    noise = [-4, 3, -1, 5, -2, 0, 2, -3]
    for p in d["products"]:
        p["price"] = 1
    d["history"] = [{"location": "P", "product": p, "date": (D("2025-08-04") + timedelta(weeks=w)).isoformat(),
                     "qty": q} for w in range(20) for p, q in (("A", 1000 if w == 10 else 100 + noise[w % 8]),
                                                               ("B", 110 + noise[w % 8]))]
    seg = {x.product: x.segment for x in run_forecast(ds(d)).series}
    assert seg["A"].revenue > seg["B"].revenue                 # raw: the freak order makes A the bigger item
    assert seg["A"].revenue_share < seg["B"].revenue_share     # ranked without it, B is


# ---- readiness gate ------------------------------------------------------------------------------------
def test_supplier_lane_weight_is_checked_only_for_what_that_supplier_sells():
    """S1: a per-kg sea lane from a supplier flagged every product at the plant, even ones made there."""
    d = base()
    d["products"][1]["weight_kg"] = 1.0                  # B has a weight, C does not
    d["lanes"] = [{"id": "SEA", "origin": "S", "destination": "P", "modes": [{"transit_days": 5, "cost_per_kg": 0.1}]}]
    found = [(i.code, i.object_id) for i in validate(ds(d)) if i.code == "LANE_WEIGHT_MISSING"]
    assert found == [("LANE_WEIGHT_MISSING", "C")]        # not A: it is made at P, not shipped from S


def test_supply_side_errors_do_not_block_demand_planning():
    """S4: a warehouse without a supplier stopped the forecast."""
    d = base()
    d["production_sources"] = []
    d["demand"] = [demand("P", "A", "2026-01-12", 10)]
    assert {i.code for i in validate(ds(d)) if i.severity == "error"} == {"NO_SOURCE"}
    assert not blocks_demand(validate(ds(d)))
    d["history"] = [{"location": "P", "product": "ZZ", "date": "2025-12-29", "qty": 5}]
    assert blocks_demand(validate(ds(d)))                 # a broken reference in demand's own input does


def test_a_broken_reference_is_reported_once_not_as_a_phantom_node():
    """S8: a sales order for an unknown product also produced NO_SOURCE and LOCATION_PRODUCT_DEFAULTED for it."""
    d = base()
    d["demand"] = [demand("P", "A-XL", "2026-01-12", 10, "sales_order", id="SO-9")]
    assert [(i.code, i.object_id) for i in validate(ds(d)) if i.object_id.endswith("A-XL") or i.object_id == "SO-9"] \
        == [("REF_UNKNOWN", "SO-9")]
    assert ("P", "A-XL") not in build_graph(ds(d)).nodes


def test_duplicate_location_product_says_which_record_is_used():
    d = base()
    d["location_products"].append({"location": "P", "product": "A", "on_hand": 99})
    (dup,) = [i for i in validate(ds(d)) if i.code == "DUP_LOCATION_PRODUCT"]
    assert "first record is used" in dup.message and ds(d).location_product_by_key[("P", "A")].on_hand == 10


# ---- MRP ---------------------------------------------------------------------------------------------
def _late_c() -> dict:
    """C is needed today, has no stock and takes a day to buy: the order can only arrive tomorrow."""
    d = base()
    d["demand"] = [demand("P", "C", "2026-01-05", 10)]
    return d


def test_projection_shows_demand_reached_late_as_at_risk():
    """S1: the node table showed the late demand as covered while DEMAND_AT_RISK said otherwise."""
    r = run_mrp(ds(_late_c()))
    assert _node(r, "P", "C").buckets[0].at_risk == pytest.approx(10)
    assert any(e.code == "DEMAND_AT_RISK" for e in r.exceptions)


def test_firming_a_late_order_reschedules_it_in_instead_of_duplicating_supply():
    """S1: after firming, the re-plan saw the firm PO a day after the need and planned a second one."""
    x = ds(_late_c())
    firmed, rep = firm_orders(x, run_mrp(x), within_days=14)
    assert len(rep.firmed) == 1
    again = run_mrp(firmed)
    assert not [o for o in again.orders if o.product == "C"]
    (exc,) = [e for e in again.exceptions if e.code == "RESCHEDULE_IN"]
    assert rep.firmed[0].receipt_id in exc.message


def test_stock_targets_from_sop_are_a_netting_threshold():
    """S3: releasing the S&OP plan lost its build-ahead, so MRP overloaded the peak month."""
    d = base()
    d["stock_targets"] = [{"location": "P", "product": "A", "date": "2026-01-05", "qty": 0},
                          {"location": "P", "product": "A", "date": "2026-01-11", "qty": 30}]
    r = run_mrp(ds(d))
    (mo,) = [o for o in r.orders if o.product == "A"]
    assert (mo.qty, mo.need_date) == (20, D("2026-01-11"))                  # 30 − 10 on hand, with no demand at all
    assert _node(r, "P", "A").buckets[0].target_stock == pytest.approx(30)


# ---- promising -----------------------------------------------------------------------------------------
def test_confirmed_delivery_is_never_before_the_requested_date():
    """S2: a Monday delivery must ship on Friday (Mon–Fri calendar, one-day lane); the arrival, Saturday, was
    confirmed as the delivery date although the customer asked for Monday."""
    d = base(workdays=[0, 1, 2, 3, 4])
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    r = check_order(ds(d), DemandRecord(id="SO-1", location="K", product="A", date=D("2026-01-12"), qty=5,
                                        kind="sales_order"))
    assert [(ln.ship_date, ln.date) for ln in r.checked.lines] == [(D("2026-01-09"), D("2026-01-12"))]


def test_a_customers_first_order_can_be_quoted_and_an_unconfirmed_quote_says_why():
    """Found writing the test above: a quote for a customer with no demand yet had no shipping location, so it came
    back unconfirmed with no reason although the plant had stock."""
    d = base()
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    ok = check_order(ds(d), DemandRecord(id="Q", location="K", product="A", date=D("2026-01-07"), qty=5,
                                         kind="sales_order")).checked
    assert (ok.status, ok.lines[0].ship_from, ok.reason) == ("on_time", "P", "")
    d["lanes"][0]["products"] = ["B"]
    no = check_order(ds(d), DemandRecord(id="Q", location="K", product="A", date=D("2026-01-07"), qty=5,
                                         kind="sales_order")).checked
    assert no.status == "unconfirmed" and "add a lane" in no.reason


def test_an_unconfirmed_quantity_says_the_forecast_is_not_supply():
    """Audit: ATP ignores the forecast by design (SAP semantics), which surprises newcomers; the reason says so."""
    d = base()
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["demand"] = [demand("K", "A", "2026-01-07", 500)]                  # a forecast is not supply
    d["promising"] = {"include_planned_orders": False, "ctp": False, "confirm_beyond_rlt": False}  # 10 A on hand only
    r = check_order(ds(d), DemandRecord(id="Q", location="K", product="A", date=D("2026-01-07"), qty=50,
                                        kind="sales_order")).checked
    assert r.unconfirmed > 0 and "never the forecast" in r.reason


def test_a_purchase_order_is_placed_on_a_working_day():
    """S1: the start was offset from the need by the lead time and could land on a Saturday."""
    d = base(workdays=[0, 1, 2, 3, 4])
    d["purchasing_sources"][1]["lead_time_days"] = 5
    d["demand"] = [demand("P", "C", "2026-01-15", 10, "sales_order", id="SO")]   # Thursday − 5 days = Saturday
    po = next(o for o in run_mrp(ds(d)).orders if o.product == "C")
    assert (po.start_date, po.available_date) == (D("2026-01-09"), D("2026-01-14"))   # Friday; arrives a day early
    assert po.start_date.weekday() < 5


def test_an_order_says_how_much_is_for_demand_for_the_buffer_and_for_the_lot_size():
    """Audit: lot_excess lumped rounding waste and safety-stock build into one unpegged number."""
    d = base()
    c = lp(d, "P", "C")
    c["safety_stock"] = {"method": "fixed", "qty": 20}
    c["lot_sizing"] = {"policy": "L4L", "rounding_qty": 25}
    c["on_hand"] = 20
    d["demand"] = [demand("P", "C", "2026-01-12", 30, "sales_order", id="SO")]
    # 20 on hand − 30 = −10: 10 for the order, 20 to restore the safety stock, rounded up to 2 × 25
    po = next(o for o in run_mrp(ds(d)).orders if o.product == "C")
    assert (po.qty, po.qty - po.for_buffer - po.for_lot_size, po.for_buffer, po.for_lot_size) == (50, 10, 20, 20)


def test_demand_before_the_fastest_supply_says_why_it_is_late():
    """Audit: with a one-day lead time, demand on day one is late by construction; the exception now says so."""
    d = base()
    d["purchasing_sources"][1]["lead_time_days"] = 1
    d["demand"] = [demand("P", "C", "2026-01-05", 10, "sales_order", id="SO")]
    risk = next(e for e in run_mrp(ds(d)).exceptions if e.code == "DEMAND_AT_RISK")
    assert "available 2026-01-06 at the earliest" in risk.message and "stock on hand or a firm receipt" in risk.message


# ---- one safety stock everywhere ----------------------------------------------------------------------------
def test_mrp_and_inventory_hold_the_same_fill_rate_safety_stock_with_an_eoq_lot():
    """S5: the inventory screen sized the fill-rate lot as a week of demand, MRP as the EOQ."""
    d = base(horizon=56)
    d["products"][0]["standard_cost"] = 40
    d["demand"] = [demand("P", "A", f"2026-01-{5 + 7 * w:02d}" if w < 4 else f"2026-02-{5 + 7 * w - 31:02d}", 70,
                          period_days=7) for w in range(8)]
    a = lp(d, "P", "A")
    a["safety_stock"] = {"method": "fill_rate", "service_level": 0.99, "demand_cv": 0.3}
    a["lot_sizing"] = {"policy": "EOQ", "ordering_cost": 50}
    x = ds(d)
    mrp_ss = _node(run_mrp(x), "P", "A").buckets[0].safety_stock
    inv_ss = next(n for n in run_inventory(x).nodes if (n.location, n.product) == ("P", "A")).current_ss
    q = math.sqrt(2 * 3650 * 50 / (40 * 0.2))
    expected = statistical_ss(x.location_products[0].safety_stock, SSInputs(10, 2, 0, 0.99, q)).qty
    assert mrp_ss == pytest.approx(inv_ss) == pytest.approx(expected)


def _one_stage(policy: dict) -> Dataset:
    """A plant buying B from a 5-day supplier and selling 10 a day of it."""
    d = base(horizon=56)
    d["products"] = [{"id": "B", "type": "RM", "standard_cost": 40}]
    d["production_sources"], d["resources"] = [], []
    d["purchasing_sources"] = [d["purchasing_sources"][0] | {"lead_time_days": 5}]
    d["location_products"] = [{"location": "P", "product": "B", "safety_stock": policy,
                               "lot_sizing": {"policy": "EOQ", "ordering_cost": 50}}]
    d["demand"] = [demand("P", "B", "2026-01-05", 560, period_days=56)]
    return ds(d)


def test_placement_sizes_a_fill_rate_target_as_mrp_does_not_as_a_cycle_service_level():
    """S5: MEIO priced a 99 % fill rate at z = Φ⁻¹(0.99) = 2.33, holding 3–4× what MRP holds for the policy."""
    x = _one_stage({"method": "fill_rate", "service_level": 0.99, "demand_cv": 0.3})
    n = next(n for n in run_inventory(x).nodes if n.product == "B")
    assert n.single_ss == pytest.approx(n.current_ss) == pytest.approx(_node(run_mrp(x), "P", "B").buckets[0].safety_stock)
    assert n.z < 1.0                                   # the k a 99 % fill rate needs with an EOQ of 330, not 2.33
    assert n.meio_ss == pytest.approx(n.single_ss)     # a lone stage buffers its own lead time either way


def test_a_review_period_is_covered_by_the_recommendation_too():
    """Found fixing the one above: single-echelon covered L + R, the placement only τ = L, a false saving."""
    x = _one_stage({"method": "service_level", "service_level": 0.95, "demand_cv": 0.3, "review_period_days": 7})
    n = next(n for n in run_inventory(x).nodes if n.product == "B")
    assert n.single_ss == pytest.approx(1.6448536 * 0.3 * 10 * math.sqrt(7) * math.sqrt(12), rel=1e-6)
    assert n.meio_ss == pytest.approx(n.single_ss) and n.meio_net_days == 5


def test_demand_rate_is_forecast_after_consumption_plus_orders():
    """S5: inventory took max(forecast, orders); orders beyond the consumption window add demand."""
    d = base(horizon=28)
    d["demand"] = [demand("P", "A", "2026-01-05", 70), demand("P", "A", "2026-01-26", 30, "sales_order", id="SO")]
    n = next(n for n in run_inventory(ds(d)).nodes if (n.location, n.product) == ("P", "A"))
    assert n.direct_mean_daily == pytest.approx(100 / 28)                    # 26 Jan is 21 days after the forecast


def test_sop_plans_the_demand_mrp_plans():
    """S5: S&OP took max(forecast, orders) per bucket, so an order that consumed next week's forecast was
    planned twice, and a make-to-order item planned its forecast."""
    d = base(horizon=28)
    d["sop"] = {"bucket": "week"}
    d["products"][0]["price"] = 50
    d["demand"] = [demand("P", "A", "2026-01-05", 70, period_days=7), demand("P", "A", "2026-01-12", 70, period_days=7),
                   demand("P", "A", "2026-01-08", 100, "sales_order", id="SO")]
    assert next(x for x in run_sop(ds(d)).demand if x.product == "A").demand == pytest.approx([100, 40, 0, 0])
    lp(d, "P", "A")["strategy"] = "MTO"
    assert next(x for x in run_sop(ds(d)).demand if x.product == "A").demand == pytest.approx([100, 0, 0, 0])


def test_mrp_plans_each_released_sop_bucket_in_that_bucket():
    """Found checking the fix above: a monthly release is dated the 1st; an order on the 25th sat outside the 7-day
    backward window, consumed next month's release instead, and MRP pulled 60 units into a month S&OP had not."""
    d = base(horizon=56)
    d["sop"] = {"bucket": "month"}
    d["products"][0]["price"] = 50
    d["demand"] = [demand("P", "A", "2026-01-05", 100, period_days=28), demand("P", "A", "2026-02-02", 100, period_days=28),
                   demand("P", "A", "2026-01-25", 60, "sales_order", id="SO")]
    sop = run_sop(ds(d))
    released, _ = release_sop(ds(d), sop)
    sales = next(x for x in sop.demand if x.product == "A").sales
    planned = [0.0] * len(sop.buckets)
    for q in run_mrp(released).requirements:
        if q.product == "A" and q.parent_order is None:
            planned[next(b.index for b in sop.buckets if b.start <= q.date < b.end)] += q.qty
    assert planned == pytest.approx(sales, abs=1e-2)                 # releases are rounded to 3 decimals
    assert sum(sales) == pytest.approx(200)                          # the order consumed January's forecast


# ---- DDMRP ---------------------------------------------------------------------------------------------
def test_ddmrp_band_boundaries_are_inclusive_despite_float_noise():
    """S5: a CV of exactly 0.3 computed as 0.30000000000000004 fell into the medium band."""
    s = InventorySettings()
    cv = math.sqrt((0.3 * 10 * math.sqrt(7)) ** 2) / (10 * math.sqrt(7))
    assert cv > 0.3 and ddmrp.variability_factor(cv, s) == (s.vf_low, "low")
    assert ddmrp.lead_time_factor(14 + 1e-12, s) == (s.ltf_short, "short")


def test_ddmrp_qualified_demand_includes_the_orders_of_customers_it_ships_to():
    """S5: customer orders are recorded at the customer, so the shipping buffer never saw its spikes."""
    d = base()
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    lp(d, "P", "A")["ddmrp_buffer"] = True
    d["demand"] = [demand("K", "A", "2026-01-06", 40, "sales_order", id="SO-1"),     # ships today
                   demand("K", "A", "2026-01-20", 40, "sales_order", id="SO-2")]     # beyond the spike horizon
    row = next(r for r in run_inventory(ds(d)).ddmrp if (r.location, r.product) == ("P", "A"))
    assert row.qualified_demand == pytest.approx(40)


# ---- execution ----------------------------------------------------------------------------------------------
def test_a_sale_counts_when_the_customer_receives_it():
    """S6: a Sunday shipment on a one-day lane counted in the week before the customer received it."""
    d = base()
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["demand"] = [demand("K", "A", "2026-01-05", 70, period_days=7), demand("K", "A", "2026-01-12", 70, period_days=7)]
    d["movements"] = [{"id": "GI", "date": "2026-01-11", "type": "sale", "location": "P", "product": "A", "qty": 9,
                       "counterparty": "K"}]
    recs = accuracy_records(Dataset.model_validate(d), D("2026-01-05"), D("2026-01-19"))
    assert [(r.start, r.actual) for r in recs] == [(D("2026-01-05"), 0), (D("2026-01-12"), 9)]


# ---- late postings -------------------------------------------------------------------------------------
def test_a_late_posting_reaches_what_earlier_rolls_logged():
    """S6: after a roll, a movement posted for a day before the new start reached the stock but not the history,
    the logged accuracy week or the closed-order log."""
    d = base()
    d["products"][0]["price"] = 10
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 0}]}]
    d["receipts"] = [{"id": "PO-1", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
                      "due_date": "2026-01-07", "source": "PIR-B"}]
    d["demand"] = [demand("K", "A", "2026-01-06", 10, "sales_order", id="SO-1"), demand("K", "A", "2026-01-08", 20)]
    d["movements"] = [{"id": "GR-1", "date": "2026-01-07", "type": "receipt", "location": "P", "product": "B",
                       "qty": 99, "reference": "PO-1"},
                      {"id": "GI-1", "date": "2026-01-06", "type": "sale", "location": "P", "product": "A", "qty": 10,
                       "reference": "SO-1", "counterparty": "K"}]
    rolled, rep = roll_forward(ds(d), D("2026-01-12"))
    assert {c.id for c in rep.closed} == {"PO-1", "SO-1"}             # 99 of 100 is within the 2 % tolerance
    late = rolled.model_dump(mode="json")
    late["movements"] += [{"id": "GR-2", "date": "2026-01-08", "type": "receipt", "location": "P", "product": "B",
                           "qty": 1, "reference": "PO-1"},
                          {"id": "GI-2", "date": "2026-01-09", "type": "sale", "location": "P", "product": "A", "qty": 4,
                           "counterparty": "K"}]
    nxt, _ = roll_forward(ds(late), D("2026-01-19"))
    po = next(c for c in nxt.closed_orders if c.id == "PO-1")
    assert (po.delivered_qty, po.last_delivery) == (100, D("2026-01-08"))
    assert [(h.date, h.qty) for h in nxt.history] == [(D("2026-01-06"), 10), (D("2026-01-09"), 4)]
    assert [(a.start, a.forecast, a.actual) for a in nxt.accuracy][0] == (D("2026-01-05"), 20, 14)



# ---- found by the generated flow (S9: one flow over many generated companies) -------------------------------
def _sig(r):
    return sorted((o.kind, o.location, o.product, round(o.qty, 6)) for o in r.orders)


def test_firming_the_plan_and_planning_again_adds_no_order_under_a_stock_target():
    """S9: MRP checked the buffer on every date anything happened, including a firm receipt's arrival. A stock
    target ramps daily, so a receipt landing between two requirements triggered one more minimum lot."""
    d = base(workdays=[0, 1, 2, 3, 4])
    d["purchasing_sources"][0]["lead_time_days"] = 10
    lp(d, "P", "B").update(on_hand=0, lot_sizing={"policy": "L4L", "min_qty": 30})
    d["demand"] = [demand("P", "B", "2026-01-06", 20), demand("P", "B", "2026-01-13", 20)]
    d["stock_targets"] = [{"location": "P", "product": "B", "date": "2026-01-05", "qty": 0, "source": "sop"},
                          {"location": "P", "product": "B", "date": "2026-01-25", "qty": 200, "source": "sop"}]
    plan = run_mrp(ds(d))
    firmed, rep = firm_orders(ds(d), plan, None, 28)
    assert rep.firmed and all(o.kind != "buy" for o in run_mrp(firmed).orders)
    assert [b.projected_on_hand for b in _node(run_mrp(firmed), "P", "B").buckets] == \
        [b.projected_on_hand for b in _node(plan, "P", "B").buckets]


def test_a_firm_order_is_not_duplicated_when_its_lot_takes_longer_than_the_shortage():
    """S9: whether a late firm order is pulled in was decided by how soon an order *for the shortage* could land;
    the order MRP then created was lot-sized (here 400, four days of production), just as late, and duplicated it."""
    d = base()
    lp(d, "P", "A").update(on_hand=0, lot_sizing={"policy": "FIXED", "fixed_qty": 400})
    d["production_sources"][0].pop("fixed_lead_time_workdays")
    d["production_sources"][0]["operations"][0].update(setup_hours=0, run_hours_per_unit=0.08)
    d["demand"] = [demand("P", "A", "2026-01-06", 20)]
    plan = run_mrp(ds(d))
    assert [(o.qty, o.start_in_past) for o in plan.orders if o.product == "A"] == [(400, True)]
    firmed, _ = firm_orders(ds(d), plan, None, 28)
    again = run_mrp(firmed)
    assert [o for o in again.orders if o.product == "A"] == []
    assert any(e.code == "RESCHEDULE_IN" for e in again.exceptions)


def test_mrp_holds_no_statistical_buffer_where_no_demand_flows():
    """S9: a component only a firm order draws on has no forecast error, and the inventory screen says so; MRP
    sized a service-level buffer on that one-off requirement all the same."""
    d = base()
    lp(d, "P", "B")["safety_stock"] = {"method": "service_level", "service_level": 0.95, "demand_cv": 0.3}
    d["receipts"] = [{"id": "PRD-1", "kind": "production", "location": "P", "product": "A", "qty": 50,
                      "due_date": "2026-01-10", "source": "PV-A",
                      "reservations": [{"location": "P", "product": "B", "date": "2026-01-08", "qty": 100}]}]
    inv = next(n for n in run_inventory(ds(d)).nodes if (n.location, n.product) == ("P", "B"))
    assert inv.current_ss == 0
    assert _node(run_mrp(ds(d)), "P", "B").buckets[0].safety_stock == 0


def test_rolling_in_two_steps_ends_where_rolling_once_does():
    """S9: a roll rounded the open quantity of an order nothing was received on, and lost the original (so the
    next roll started from the rounded one), and it logged closed orders in the order the rolls closed them."""
    d = base()
    d["receipts"] = [{"id": "PO-1", "kind": "purchase", "location": "P", "product": "B", "qty": 13.2814285714286,
                      "due_date": "2026-01-14", "source": "PIR-B"},
                     {"id": "PO-2", "kind": "purchase", "location": "P", "product": "C", "qty": 10,
                      "due_date": "2026-01-07", "source": "PIR-C"}]
    d["movements"] = [{"id": "GR-1", "date": "2026-01-15", "type": "receipt", "location": "P", "product": "B",
                       "qty": 13.2814285714286, "reference": "PO-1"},
                      {"id": "GR-2", "date": "2026-01-07", "type": "receipt", "location": "P", "product": "C", "qty": 10,
                       "reference": "PO-2"}]
    week, _ = roll_forward(ds(d), D("2026-01-12"))
    two, _ = roll_forward(week, D("2026-01-19"))
    once, _ = roll_forward(ds(d), D("2026-01-19"))
    assert two.model_dump() == once.model_dump()
    assert [c.id for c in once.closed_orders] == ["PO-2", "PO-1"]


def test_a_late_sale_counts_in_a_week_that_logged_nothing():
    """S9: the roll re-read only weeks that had logged a record; a week in which no series had forecast or sales
    logged none, so a sale posted late for it never reached the accuracy log."""
    d = base()
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 0}]}]
    d["demand"] = [demand("K", "A", "2026-01-14", 20)]
    rolled, rep = roll_forward(ds(d), D("2026-01-12"))
    assert rep.accuracy == [] and [(w.start, w.end) for w in rolled.rolled_weeks] == [(D("2026-01-05"), D("2026-01-12"))]
    late = rolled.model_dump(mode="json")
    late["movements"] = [{"id": "GI-1", "date": "2026-01-06", "type": "sale", "location": "P", "product": "A",
                          "qty": 10, "counterparty": "K"}]
    nxt, _ = roll_forward(ds(late), D("2026-01-19"))
    assert [(a.start, a.forecast, a.actual) for a in nxt.accuracy] == [(D("2026-01-05"), 0, 10), (D("2026-01-12"), 20, 0)]


def test_a_fractional_lead_time_is_buffered_for_what_it_is_not_rounded_up():
    """S9: the placement counts whole days, so a 3.5-day lead time became 4 and buffering the stage alone cost
    more than the single-echelon baseline for the same decision (a negative 'saving')."""
    d = base()
    d["purchasing_sources"][0]["lead_time_days"] = 3.5
    lp(d, "P", "B")["safety_stock"] = {"method": "service_level", "service_level": 0.95, "demand_cv": 0.3}
    d["demand"] = [demand("P", "B", (D(START) + timedelta(days=i)).isoformat(), 10) for i in range(28)]
    inv = run_inventory(ds(d))
    n = next(x for x in inv.nodes if (x.location, x.product) == ("P", "B"))
    assert (n.meio_net_days, n.decision) == (4, "buffer")
    assert n.meio_ss == pytest.approx(n.single_ss) and inv.totals.saving_vs_single == pytest.approx(0, abs=1e-9)


def test_a_period_lot_is_not_duplicated_when_firmed():
    """S9: a three-week lot takes five days to make, so it lands late; once firmed it covered the weeks after, the
    next plan sized a new order to the first week's shortage alone, found it faster, and planned it beside the
    firm order instead of pulling the firm order in."""
    d = base()
    lp(d, "P", "A").update(on_hand=0, lot_sizing={"policy": "POQ", "periods": 3})
    d["production_sources"][0].pop("fixed_lead_time_workdays")
    d["production_sources"][0]["operations"][0].update(setup_hours=0, run_hours_per_unit=0.08)
    d["demand"] = [demand("P", "A", day, q) for day, q in (("2026-01-06", 100), ("2026-01-13", 200), ("2026-01-20", 200))]
    plan = run_mrp(ds(d))
    assert [(o.qty, o.start_in_past) for o in plan.orders if o.product == "A"] == [(500, True)]
    firmed, _ = firm_orders(ds(d), plan, None, 28)
    assert [o for o in run_mrp(firmed).orders if o.product == "A"] == []
