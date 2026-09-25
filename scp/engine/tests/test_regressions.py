"""Regression tests for the defects the end-to-end scenarios (scp.scenarios) exposed. Each test is the
smallest dataset that shows the defect; the scenario named in the docstring shows it in context."""
from __future__ import annotations

import math
from datetime import date

import pytest

from scp.actuals import firm_orders
from scp.actuals.stock import accuracy_records
from scp.inventory import ddmrp, run_inventory
from scp.model import Dataset, DemandRecord, InventorySettings
from scp.network import build_graph
from scp.plan import run_mrp
from scp.plan.safety import SSInputs, statistical_ss
from scp.promise import check_order
from scp.validate import blocks_demand, validate

from .factory import base, demand, ds, lp

D = date.fromisoformat


def _node(r, loc, prod):
    return next(n for n in r.nodes if (n.location, n.product) == (loc, prod))


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


def test_demand_rate_is_forecast_after_consumption_plus_orders():
    """S5: inventory took max(forecast, orders); orders beyond the consumption window add demand."""
    d = base(horizon=28)
    d["demand"] = [demand("P", "A", "2026-01-05", 70), demand("P", "A", "2026-01-26", 30, "sales_order", id="SO")]
    n = next(n for n in run_inventory(ds(d)).nodes if (n.location, n.product) == ("P", "A"))
    assert n.direct_mean_daily == pytest.approx(100 / 28)                    # 26 Jan is 21 days after the forecast


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
