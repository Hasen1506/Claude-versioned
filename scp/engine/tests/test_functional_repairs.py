"""Functional repair regressions: partial execution, identities, prices and merge references."""

import copy
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from scp.actuals import PostingError, post, roll_forward
from scp.actuals.stock import stock_rows
from scp.companies.merge import merge
from scp.model import MovementType, StockType
from scp.plan.structure import needs
from scp.inventory import gsm
from scp.sop import run_sop
from scp.tower.kpis import Kpis
from .factory import base, ds, lp
from .test_sop import mix


def production(mode="plain", reserved=False):
    d = base()
    for p in ["B", "C"]:
        lp(d, "P", p)["on_hand"] = 1000
    ps = d["production_sources"][0]
    if mode == "component-scrap":
        ps["components"][0]["scrap"] = 0.2
    elif mode == "operation-scrap":
        ps["operations"][0]["scrap"] = 0.2
    elif mode == "assembly-scrap":
        ps["assembly_scrap"] = 0.2
    elif mode == "all-scrap":
        ps["components"][0]["scrap"] = 0.2
        ps["operations"][0]["scrap"] = 0.2
        ps["assembly_scrap"] = 0.2
    elif mode == "fixed-part":
        ps["components"][0].update(fixed_qty=True, qty=3, scrap=0.2)
    elif mode == "phantom":
        d["products"].append({"id": "SUB", "type": "SFG"})
        d["location_products"].append({"location": "P", "product": "SUB", "phantom": True})
        ps["components"] = [{"product": "SUB", "qty": 2}]
        d["production_sources"].append(
            {
                "id": "PV-SUB",
                "location": "P",
                "product": "SUB",
                "components": [{"product": "B", "qty": 3}],
                "fixed_lead_time_workdays": 1,
            }
        )
    elif mode == "engineering-change":
        ps["components"] = [
            {"product": "B", "qty": 2, "valid_to": "2026-01-05"},
            {"product": "C", "qty": 3, "valid_from": "2026-01-06"},
        ]
    d["receipts"] = [
        {
            "id": "MO-1",
            "kind": "production",
            "location": "P",
            "product": "A",
            "qty": 10,
            "start_date": "2026-01-05",
            "due_date": "2026-01-07",
            "source": "PV-A",
        }
    ]
    if reserved:
        x = ds(d)
        d["receipts"][0]["reservations"] = [
            {"location": "P", "product": n.product, "date": "2026-01-05", "qty": n.qty(10)}
            for n in needs(x, x.production_source_by_id["PV-A"], date(2026, 1, 5))
        ]
    return d


def issued(x, oid="MO-1"):
    got = defaultdict(float)
    for m in x.movements:
        if m.reference == oid and m.type is MovementType.ISSUE:
            got[m.product] += m.net
    return dict(got)


def reserved_production(fixed=False, reserved=True):
    d = production()
    if fixed:
        d["production_sources"][0]["components"][0].update(qty=3, fixed_qty=True)
    if reserved:
        x = ds(d)
        d["receipts"][0]["reservations"] = [
            {"location": "P", "product": n.product, "date": "2026-01-05", "qty": n.qty(10)}
            for n in needs(x, x.production_source_by_id["PV-A"], date(2026, 1, 5))
        ]
    return ds(d)


def serial_inventory():
    d = base()
    d["products"][0]["serial_numbers"] = True
    lp(d, "P", "A")["on_hand"] = 3
    d["movements"] = [
        {
            "id": "GM-00001",
            "date": "2026-01-03",
            "type": "opening",
            "location": "P",
            "product": "A",
            "qty": 3,
            "serials": ["A-000001", "A-000002", "A-000003"],
        }
    ]
    return ds(d)


@pytest.mark.parametrize("fixed", [False, True])
def test_partial_roll_shorten_preserves_fixed_and_variable_targets(fixed):
    x = reserved_production(fixed)
    x, _ = post(x, "receive", order="MO-1", qty=4, on=date(2026, 1, 5))
    x, _ = roll_forward(x, date(2026, 1, 6))
    x, _ = post(x, "shorten", order="MO-1", qty=8)
    x, _ = post(x, "receive", order="MO-1", qty=4, on=date(2026, 1, 7))
    assert issued(x)["B"] == pytest.approx(3 if fixed else 16)


@pytest.mark.parametrize("fixed", [False, True])
def test_closed_production_reversal_restores_fully_consumed_component_targets(fixed):
    x = reserved_production(fixed)
    x, first = post(x, "receive", order="MO-1", qty=4, on=date(2026, 1, 5))
    x, _ = roll_forward(x, date(2026, 1, 6))
    x, _ = post(x, "receive", order="MO-1", qty=6, on=date(2026, 1, 7))
    x, _ = roll_forward(x, date(2026, 1, 8))
    x, _ = post(x, "reverse", movement=first.movements[0], on=date(2026, 1, 5))
    x, _ = roll_forward(x, date(2026, 1, 9))
    r = next(r for r in x.receipts if r.id == "MO-1")
    assert r.qty == 4
    assert any(rv.product == "B" for rv in r.reservations)
    x, _ = post(x, "receive", order="MO-1", qty=4, on=date(2026, 1, 10))
    assert issued(x)["B"] == pytest.approx(3 if fixed else 20)


@pytest.mark.parametrize("first_qty", [2, 6, 9])
def test_quantity_confirmation_rate_survives_partial_and_final_rolls(first_qty):
    d = base()
    d["demand"] = [dict(id="S", kind="sales_order", location="P", product="A", qty=10, date="2026-01-10")]
    d["confirmations"] = [
        dict(order="S", ship_from="P", ship_date="2026-01-10", date="2026-01-10", qty=first_qty),
        dict(order="S", ship_from="P", ship_date="2026-01-12", date="2026-01-12", qty=10 - first_qty),
    ]
    x = ds(d)
    for qty, day, next_day in [(first_qty, 10, 11), (10 - first_qty, 12, 13)]:
        x, _ = post(x, "deliver", order="S", qty=qty, on=date(2026, 1, day))
        x, _ = roll_forward(x, date(2026, 1, next_day))
        k = Kpis(x)
        k.confirmation()
        row = next(r for r in k.out if r.id == "confirmation_rate")
        assert row.value == pytest.approx(first_qty / 10)


def test_released_quality_serial_moves_with_its_identity_then_can_be_sold():
    d = serial_inventory().model_dump(mode="json")
    d["movements"][0]["stock_type"] = "quality"
    d["demand"] = [dict(id="S", kind="sales_order", location="P", product="A", qty=1, date="2026-01-06")]
    x, _ = post(
        ds(d),
        "move",
        location="P",
        product="A",
        qty=1,
        to_type=StockType.UNRESTRICTED,
        lot={"stock_type": StockType.QUALITY},
        on=date(2026, 1, 4),
    )
    status = [m for m in x.movements if m.type is MovementType.STATUS]
    assert [m.serials for m in status] == [["A-000001"], ["A-000001"]]
    x, _ = post(x, "deliver", order="S", qty=1, on=date(2026, 1, 5))
    sale = next(m for m in x.movements if m.type is MovementType.SALE)
    assert sale.serials == ["A-000001"]
    assert len(next(r for r in stock_rows(x, date(2026, 1, 6)) if r.product == "A").serials) == 2


def test_reversing_transfer_arrival_allows_the_same_serial_to_arrive_again():
    d = serial_inventory().model_dump(mode="json")
    d["locations"].append({"id": "DC", "type": "dc"})
    d["lanes"] = [{"id": "L", "origin": "P", "destination": "DC", "modes": [{"transit_days": 1}]}]
    d["receipts"] = [
        dict(id="T", kind="transfer", location="DC", product="A", qty=1, source="L", due_date="2026-01-07")
    ]
    x, _ = post(ds(d), "ship", order="T", qty=1, on=date(2026, 1, 5))
    x, r = post(x, "receive", order="T", qty=1, on=date(2026, 1, 6))
    x, _ = post(x, "reverse", movement=r.movements[0], on=date(2026, 1, 6))
    x, r = post(x, "receive", order="T", qty=1, on=date(2026, 1, 7))
    receipt = next(m for m in x.movements if m.id == r.movements[0])
    assert receipt.serials == ["A-000001"]


@pytest.mark.parametrize("supply", [1, 2, 5, 8])
def test_profit_solver_allocates_constrained_supply_to_order_specific_values(supply):
    d = mix(mode="profit", capacity_h=supply)
    d["settings"]["horizon_days"] = 7
    d["sop"]["allow_overtime"] = False
    d["demand"] = [
        dict(id="LOW", kind="sales_order", location="P", product="A", qty=2, date="2026-01-05", price=80),
        dict(id="HIGH", kind="sales_order", location="P", product="A", qty=6, date="2026-01-05", price=120),
    ]
    r = run_sop(ds(d))
    assert r.ok
    assert r.economics.revenue == pytest.approx(min(supply, 6) * 120 + max(0, supply - 6) * 80)


def test_merge_renumbers_product_references_in_nested_bom_and_retains_unrelated_ids():
    before = {"products": [], "production_sources": [], "locations": [{"id": "A", "type": "plant"}]}
    mine = copy.deepcopy(before)
    mine["products"] = [{"id": "A", "name": "Mine"}]
    mine["production_sources"] = [
        {"id": "SRC", "location": "A", "product": "A", "components": [{"product": "A", "qty": 1}]}
    ]
    theirs = copy.deepcopy(before)
    theirs["products"] = [{"id": "A", "name": "Theirs"}]
    result, _ = merge(before, mine, theirs)
    source = result["production_sources"][0]
    assert source["product"] == "A-2" and source["components"][0]["product"] == "A-2"
    assert source["location"] == "A"


@pytest.mark.parametrize("collection", ["history", "demand"])
def test_merge_preserves_multiple_observations_with_the_same_natural_key(collection):
    rows = [dict(location="P", product="A", date="2026-01-05", qty=q) for q in [10, 20]]
    original = {collection: rows}
    result, rep = merge(original, copy.deepcopy(original), {collection: list(reversed(rows))})
    assert sorted(r["qty"] for r in result[collection]) == [10, 20]
    assert not rep.conflicts


@pytest.mark.parametrize("quantity,serials", [(1.2, None), (1, ["A-000001", "UNKNOWN"]), (1, ["A-000001", "A-000001"])])
def test_serial_status_changes_refuse_fractional_or_mismatched_identities(quantity, serials):
    x = serial_inventory()
    with pytest.raises(PostingError):
        post(
            x,
            "move",
            location="P",
            product="A",
            qty=quantity,
            to_type=StockType.BLOCKED,
            lot={"serials": serials},
            on=date(2026, 1, 4),
        )


def test_solver_workers_can_be_recreated_and_keep_the_brute_force_optimum():
    networks = [[gsm.Stage("part", 2, 1 + i), gsm.Stage("final", 1, 3, ["part"], max_service=0)] for i in range(4)]
    expected = [gsm.brute_force(stages).objective for stages in networks]
    for _ in range(3):
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(gsm.solve, networks))
        assert all(r.status == "optimal" for r in results)
        assert [r.objective for r in results] == pytest.approx(expected)


def test_legacy_closed_order_requires_source_data_before_reversing():
    x = reserved_production()
    x, posting = post(x, "receive", order="MO-1", qty=10, on=date(2026, 1, 5))
    x, _ = roll_forward(x, date(2026, 1, 6))
    x = x.model_copy(update={"closed_orders": [c.model_copy(update={"source_order": None}) for c in x.closed_orders]})
    original = x.model_dump_json()
    with pytest.raises(PostingError, match="restore the order"):
        post(x, "reverse", movement=posting.movements[0], on=date(2026, 1, 5))
    assert x.model_dump_json() == original
