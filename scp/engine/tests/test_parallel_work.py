"""Detailed scheduling must retain the physical quantity and work of every sublot."""
import copy
import math

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.plan import run_mrp
from scp.schedule import apply_schedule, run_schedule
from scp.schedule.core import check, decode, edd
from scp.schedule.run import build_instance

from .factory import base, demand, ds, lp


def parallel_company(qty=30, units=2, *, per_unit=0, batch_qty=10, batch_hours=3, whole=True):
    raw = base()
    raw["resources"][0]["units"] = units
    raw["products"][0]["whole_units"] = whole
    source = raw["production_sources"][0]
    source.pop("fixed_lead_time_workdays")
    source["full_batches"] = False
    source["operations"][0].update(setup_hours=0, run_hours_per_unit=per_unit,
                                   batch_qty=batch_qty, batch_hours=batch_hours)
    for product in ("B", "C"):
        lp(raw, "P", product)["on_hand"] = 1000
    lp(raw, "P", "A")["on_hand"] = 0
    raw["demand"] = [demand("P", "A", "2026-01-05", qty)]
    raw["scheduling"] = {"improve": False}
    return raw


def decoded(raw):
    data = ds(raw)
    inst, _, _, _ = build_instance(data, run_mrp(data))
    return data, inst, decode(inst, edd(inst))


@pytest.mark.parametrize("qty,units,expected", [
    (30, 2, [10, 20]), (25, 2, [10, 15]), (1, 4, [1]), (40, 3, [20, 20]),
    (10, 4, [10]), (11, 4, [1, 10]),
])
def test_parallel_batch_lots_keep_whole_cycles(qty, units, expected):
    data, inst, result = decoded(parallel_company(qty, units))
    assert sorted(b.qty for b in result.blocks) == expected
    op = data.production_sources[0].operations[0]
    for block in result.blocks:
        assert block.run_work == pytest.approx(3 * math.ceil(block.qty / 10))
        assert block.run_work == pytest.approx(op.run_hours(block.qty))
    assert sum(b.run_work for b in result.blocks) == pytest.approx(op.run_hours(qty))
    assert result.completion[next(iter(inst.jobs))] >= 9
    assert check(inst, result) == []


@pytest.mark.parametrize("qty,units,expected", [(5, 2, [2, 3]), (1, 4, [1]), (7, 3, [2, 2, 3])])
def test_whole_pieces_are_not_divided_between_machines(qty, units, expected):
    _, inst, result = decoded(parallel_company(qty, units, per_unit=1, batch_qty=None, batch_hours=0))
    assert sorted(b.qty for b in result.blocks) == expected
    assert sum(b.run_work for b in result.blocks) == pytest.approx(qty)
    assert check(inst, result) == []


def test_continuous_products_may_still_split_fractionally():
    _, inst, result = decoded(parallel_company(5, 2, per_unit=1, batch_qty=None, batch_hours=0, whole=False))
    assert [b.qty for b in result.blocks] == [2.5, 2.5]
    assert check(inst, result) == []


@pytest.mark.parametrize("whole,qty,batch_qty", [(False, 2.5, 1), (True, 3, 0.5), (True, 13, 2.5)])
def test_fractional_batch_capacities_charge_actual_cycles(whole, qty, batch_qty):
    data, inst, result = decoded(parallel_company(qty, 2, per_unit=0.2, batch_qty=batch_qty, whole=whole))
    assert sum(b.qty for b in result.blocks) == pytest.approx(qty)
    for b in result.blocks:
        assert b.run_work == pytest.approx(0.2 * b.qty + 3 * math.ceil(b.qty / batch_qty))
        if whole:
            assert b.qty == int(b.qty)
    assert check(inst, result) == []


def test_operation_scrap_preserves_fractional_entering_quantity():
    raw = parallel_company(10)
    raw["production_sources"][0]["operations"][0]["scrap"] = 0.2
    _, inst, result = decoded(raw)
    assert sum(b.qty for b in result.blocks) == pytest.approx(12.5)
    assert sum(b.run_work for b in result.blocks) == pytest.approx(6)
    assert check(inst, result) == []


@pytest.mark.parametrize("qty,per_unit,first,completion", [(30, 0, 9, 34), (30, 0.2, 11, 58),
                                                         (25, 0.2, 11, 57)])
def test_batch_send_ahead_waits_for_full_first_and_final_cycles(qty, per_unit, first, completion):
    raw = parallel_company(qty, 1, per_unit=per_unit)
    raw["resources"].append({"id": "M2", "location": "P", "hours_per_shift": 8, "efficiency": 1})
    ops = raw["production_sources"][0]["operations"]
    ops[0]["send_ahead_qty"] = 1
    ops.append({"seq": 20, "resource": "M2", "batch_qty": 10, "batch_hours": 3,
                "run_hours_per_unit": per_unit})
    _, inst, result = decoded(raw)
    second = next(b for b in result.blocks if b.key.endswith(":20"))
    assert second.setup_start == pytest.approx(first)
    assert second.end == pytest.approx(completion)
    assert check(inst, result) == []


@pytest.mark.parametrize("damage", ["run", "qty"])
def test_checker_rejects_physical_work_and_whole_piece_violations(damage):
    raw = parallel_company(20, 1) if damage == "run" else parallel_company(6, 2)
    if damage == "qty":
        raw["production_sources"][0]["operations"][0].update(batch_qty=None, batch_hours=0,
                                                          run_hours_per_unit=1)
    _, inst, result = decoded(raw)
    broken = copy.deepcopy(result)
    if damage == "run":
        # A shorter block can be clock-consistent yet fail to run two full batches.
        b = next(b for b in broken.blocks if b.qty == 20)
        b.run_work = 4.5
        b.end = b.run_start + 4.5
        assert any("whole batch cycles" in v for v in check(inst, broken))
    else:
        broken.blocks[0].qty += 0.5
        broken.blocks[1].qty -= 0.5
        assert any("whole piece" in v for v in check(inst, broken))


def test_schedule_api_and_apply_preserve_physical_batch_work():
    raw = parallel_company(30)
    with TestClient(app) as client:
        response = client.post("/api/schedule", json={"dataset": raw})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["violations"] == []
    assert sorted(o["qty"] for o in body["ops"]) == [10, 20]
    assert sorted(o["run_hours"] for o in body["ops"]) == [3, 6]
    applied, report = apply_schedule(ds(raw))
    assert report.ok and len(report.applied) == 1
    again = run_schedule(applied)
    assert again.ok and again.violations == []
    assert sorted(o.qty for o in again.ops) == [10, 20]
    assert sorted(o.run_hours for o in again.ops) == [3, 6]
