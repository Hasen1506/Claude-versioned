"""Enterprise 6.1: storage types and bins, put-away, waves, pick lists and warehouse tasks (S/4 guide §12.2–12.3).

Oracles are worked by hand on a small plant: which bin each quantity goes to by the rules, the order picks are walked
in, the batches first expiring. Invariants: a bin move never changes the stock of the place nor the plan; stock by
bin always adds up to the place's stock."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp import sales
from scp import warehouse as wh
from scp.actuals.documents import move_stock
from scp.actuals.stock import before, stock
from scp.api.app import app
from scp.model import Dataset, StockType
from scp.plan.mrp import plan_again
from scp.validate import validate

from .factory import START, base, demand, ds, example_dict

DAY = date.fromisoformat(START)


def plant(**kw) -> dict:
    """Plant P with A (10 on hand, 2 kg a unit) and B (30 on hand); a shelf area (add to stock, 20 a bin) on the walk
    first, a high rack (next empty, 100 kg a bin) behind it; every product to the shelves, then the rack."""
    d = base()
    d["products"][0]["weight_kg"] = 2.0
    d["products"][0]["barcode"] = "4006381333931"
    d["storage_types"] = [
        {"location": "P", "id": "SHELF", "putaway": "add_to_stock", "sequence": 10, **kw.get("shelf", {})},
        {"location": "P", "id": "RACK", "putaway": "next_empty", "picking": False, "sequence": 20}]
    d["bins"] = [
        {"location": "P", "id": "S1", "storage_type": "SHELF", "walk": 10, "max_qty": 20},
        {"location": "P", "id": "S2", "storage_type": "SHELF", "walk": 20, "max_qty": 20},
        {"location": "P", "id": "R1", "storage_type": "RACK", "walk": 100, "max_kg": 100},
        {"location": "P", "id": "R2", "storage_type": "RACK", "walk": 110, "max_kg": 100}]
    d["putaway_rules"] = [{"location": "P", "product": "", "storage_types": ["SHELF", "RACK"]}]
    return d


def held(D: Dataset, loc: str = "P") -> dict[tuple[str, str], float]:
    v = wh.view(D, loc)
    return {(r.bin, r.product): r.qty for r in v.bins if r.product}


def put_all(D: Dataset, loc: str = "P") -> Dataset:
    D, rep = wh.create_putaway(D, loc)
    for tid in rep.tasks:
        D, _ = wh.confirm_task(D, tid)
    return D


def place_stock(D: Dataset, loc: str = "P") -> dict:
    return {k: round(v, 6) for k, v in stock(before(D, DAY.replace(year=DAY.year + 1))).items() if k[0] == loc}


def plan_text(D: Dataset) -> str:
    return plan_again(D, None)[0].model_dump_json(exclude={"planned_again"})


# ---- put-away -----------------------------------------------------------------------------------------------------

def test_put_away_fills_the_shelves_first_one_product_a_bin_then_the_rack():
    D = ds(plant())
    p = wh.propose_putaway(D, "P")
    # A (10) to the first empty shelf; B (30): S1 holds A and shelves are not mixed, so S2 (20), the rest to the rack
    assert [(t.product, t.qty, t.to_bin) for t in p.tasks] == [("A", 10, "S1"), ("B", 20, "S2"), ("B", 10, "R1")]
    D2 = put_all(D)
    assert held(D2) == {("S1", "A"): 10, ("S2", "B"): 20, ("R1", "B"): 10}
    assert wh.view(D2, "P").loose == []
    # a bin move changes neither the place's stock nor the plan
    assert place_stock(D2) == place_stock(D)
    assert plan_text(D2) == plan_text(D)


def test_add_to_stock_tops_up_the_bin_holding_the_product_and_weight_limits_the_rack():
    D = put_all(ds(plant()))
    d = D.model_dump(mode="json")
    d["movements"].append({"id": "GM-90001", "date": START, "type": "adjustment", "location": "P", "product": "A",
                           "qty": 70})
    p = wh.propose_putaway(ds(d), "P")
    # S1 holds 10 A (room 10); S2 holds B; the rack: R1 holds B, R2 empty takes 100 kg / 2 kg = 50; 10 have no room
    assert [(t.product, t.qty, t.to_bin) for t in p.tasks] == [("A", 10, "S1"), ("A", 50, "R2")]
    assert p.notes == ["no bin has room for 10 A: add bins, or a storage type to its rule"]
    # with an empty shelf too: the bin holding A is topped up first, then the empty one, then the rack
    d["bins"].append({"location": "P", "id": "S3", "storage_type": "SHELF", "walk": 30, "max_qty": 20})
    assert [(t.product, t.qty, t.to_bin) for t in wh.propose_putaway(ds(d), "P").tasks] == \
        [("A", 10, "S1"), ("A", 20, "S3"), ("A", 40, "R2")]


def test_fixed_bins_mixed_areas_blocked_bins_and_a_share_of_the_area():
    d = plant(shelf={"putaway": "fixed"})
    d["bins"][1]["product"] = "B"                               # S2 kept for B; S1 for nobody: no fixed bin for A
    D = ds(d)
    assert [(t.product, t.qty, t.to_bin) for t in wh.propose_putaway(D, "P").tasks] == \
        [("A", 10, "R1"), ("B", 20, "S2"), ("B", 10, "R2")]
    d = plant(shelf={"mixed": True})
    d["bins"][1]["blocked"] = True
    assert [(t.product, t.qty, t.to_bin) for t in wh.propose_putaway(ds(d), "P").tasks] == \
        [("A", 10, "S1"), ("B", 10, "S1"), ("B", 20, "R1")]     # a mixed shelf takes B beside A, up to its 20
    d = plant()
    d["bins"][0]["blocked"] = True
    assert [(t.product, t.qty, t.to_bin) for t in wh.propose_putaway(ds(d), "P").tasks] == \
        [("A", 10, "S2"), ("B", 30, "R1")]
    d = plant(shelf={"bins_per_product": 1})
    d["location_products"][1]["on_hand"] = 50
    # B may take one shelf only: S2 (20), the rest to the rack: R1 and R2 have no weight for B (no limit)
    assert [(t.product, t.qty, t.to_bin) for t in wh.propose_putaway(ds(d), "P").tasks] == \
        [("A", 10, "S1"), ("B", 20, "S2"), ("B", 30, "R1")]


def test_a_rule_for_the_product_goes_before_the_rule_for_every_product():
    d = plant()
    d["putaway_rules"].append({"location": "P", "product": "B", "storage_types": ["RACK"]})
    assert [(t.product, t.qty, t.to_bin) for t in wh.propose_putaway(ds(d), "P").tasks] == \
        [("A", 10, "S1"), ("B", 30, "R1")]


def test_a_put_away_may_go_to_another_bin_with_room_but_not_to_one_of_another_product():
    D = ds(plant())
    D, rep = wh.create_putaway(D, "P")
    a = rep.tasks[0]                                            # A to S1
    with pytest.raises(wh.WarehouseError, match="not a bin"):
        wh.confirm_task(D, a, scanned_bin="X9")
    D1, _ = wh.confirm_task(D, rep.tasks[1])                    # B into S2
    with pytest.raises(wh.WarehouseError, match="holds another product"):
        wh.confirm_task(D1, a, scanned_bin="S2")
    D2, r = wh.confirm_task(D1, a, scanned_bin="R2")
    assert "put away in R2" in r.message and held(D2)[("R2", "A")] == 10


def test_a_short_put_away_leaves_the_rest_in_goods_in_to_put_away_again():
    D = ds(plant())
    D, rep = wh.create_putaway(D, "P")
    D, r = wh.confirm_task(D, rep.tasks[0], qty=4)
    assert "6 short" in r.message and "stays in goods in" in r.message
    loose = {x.product: (x.qty, x.to_put_away) for x in wh.view(D, "P").loose}
    assert loose["A"] == (6, 6)


# ---- waves and picking --------------------------------------------------------------------------------------------

def _shop(d: dict, lines: list[tuple[str, str, float]], dl: str = "DL-1") -> dict:
    """Customer C with sales orders and an open delivery from P of ``lines`` (order, product, qty)."""
    d["locations"].append({"id": "C", "type": "customer"})
    for o, p, q in lines:
        d["demand"].append(demand("C", p, START, q, kind="sales_order", id=o))
    d.setdefault("deliveries", []).append({"id": dl, "customer": "C", "ship_from": "P", "created_on": START,
                                           "planned_on": START,
                                           "lines": [{"order": o, "product": p, "qty": q} for o, p, q in lines]})
    return d


def test_a_wave_picks_from_the_picking_area_in_walk_order_one_row_per_bin_for_every_delivery():
    D = put_all(ds(plant()))                                    # A 10 in S1; B 20 in S2, 10 in R1
    d = _shop(D.model_dump(mode="json"), [("SO-1", "B", 12), ("SO-2", "A", 3)])
    d = _shop(d, [("SO-3", "B", 15)], dl="DL-2")
    D, rep = wh.create_wave(ds(d), "P")
    pl = wh.pick_list(D, rep.wave)
    # SO-1 takes 12 of S2; SO-3 the other 8 of S2, then 7 from the rack (a reserve: after the picking area)
    assert [(r.bin, r.product, r.qty, [(f.delivery, f.qty) for f in r.deliveries]) for r in pl.rows] == [
        ("S1", "A", 3, [("DL-1", 3)]),
        ("S2", "B", 20, [("DL-1", 12), ("DL-2", 8)]),
        ("R1", "B", 7, [("DL-2", 7)])]
    assert rep.next_task == pl.rows[0].tasks[0]
    with pytest.raises(wh.WarehouseError, match="already in a wave"):
        wh.create_wave(D, "P", ["DL-1"])


def test_picks_take_the_batch_expiring_first_and_never_an_expired_one():
    d = plant()
    d["products"][1]["shelf_life_days"] = 60
    d["location_products"][1]["on_hand"] = 0
    d["batches"] = [{"product": "B", "id": "LATE", "expires_on": "2026-03-01"},
                    {"product": "B", "id": "SOON", "expires_on": "2026-01-20"},
                    {"product": "B", "id": "GONE", "expires_on": "2026-01-02"}]
    d["movements"] = [
        {"id": f"GM-0000{i}", "date": "2026-01-04", "type": "opening", "location": "P", "product": "B", "qty": q,
         "batch": b, "bin": bn} for i, (b, q, bn) in enumerate((("LATE", 10, "S1"), ("SOON", 6, "S2"),
                                                                 ("GONE", 9, "S2")), 1)]
    d = _shop(d, [("SO-1", "B", 12)])
    D, rep = wh.create_wave(ds(d), "P")
    picks = [(t.from_bin, t.batch, t.qty) for t in D.warehouse_tasks if t.wave == rep.wave]
    assert picks == [("S2", "SOON", 6), ("S1", "LATE", 6)]     # first expiring first; GONE expired before 5 Jan


def test_confirming_picks_reads_the_bin_and_the_product_then_the_goods_issue_ships_the_batches_picked():
    d = plant()
    d["products"][1]["shelf_life_days"] = 60
    d["location_products"][1]["on_hand"] = 0
    d["batches"] = [{"product": "B", "id": "B0", "expires_on": "2026-01-25"},
                    {"product": "B", "id": "B1", "expires_on": "2026-02-01"},
                    {"product": "B", "id": "B2", "expires_on": "2026-03-01"}]
    d["bins"][3]["blocked"] = True                              # R2: damaged racking, nothing picked from it
    d["movements"] = [
        {"id": "GM-00003", "date": "2026-01-04", "type": "opening", "location": "P", "product": "B", "qty": 30,
         "batch": "B0", "bin": "R2"},
        {"id": "GM-00001", "date": "2026-01-04", "type": "opening", "location": "P", "product": "B", "qty": 5,
         "batch": "B1", "bin": "S1"},
        {"id": "GM-00002", "date": "2026-01-04", "type": "opening", "location": "P", "product": "B", "qty": 20,
         "batch": "B2", "bin": "S2"}]
    d = _shop(d, [("SO-1", "B", 9), ("SO-2", "A", 2)])
    D, rep = wh.create_wave(ds(d), "P")
    first = rep.next_task
    t = next(x for x in D.warehouse_tasks if x.id == first)
    assert (t.from_bin, t.batch, t.qty) == ("S1", "B1", 5)
    with pytest.raises(wh.WarehouseError, match="that is bin S2"):
        wh.confirm_task(D, first, scanned_bin="S2")
    with pytest.raises(wh.WarehouseError, match="is for B"):
        wh.confirm_task(D, first, scanned_bin="S1", scanned_product="4006381333931")      # A's barcode
    with pytest.raises(sales.SalesError, match="picks still open"):
        sales.issue(D, "DL-1")
    D, r = wh.confirm_task(D, first, scanned_bin="S1", scanned_product="B")
    nxt = next(x for x in D.warehouse_tasks if x.id == r.next_task)
    assert (nxt.from_bin, nxt.batch, nxt.qty) == ("S2", "B2", 4)
    D, r = wh.confirm_task(D, nxt.id, scanned_bin="S2", scanned_product="B")
    a = next(x for x in D.warehouse_tasks if x.order == "SO-2")
    assert a.from_bin is None                                   # A was never put away: picked from goods in
    D, r = wh.confirm_task(D, a.id, scanned_product="4006381333931")    # read by its barcode
    assert "DL-1 is picked in full" in r.message and r.next_task is None
    line = {x.order: x for x in D.deliveries[0].lines}
    assert line["SO-1"].picked == 9 and line["SO-1"].batch is None      # two batches: on the picks
    D, rep2 = sales.issue(D, "DL-1")
    shipped = defaultdict(float)
    for m in D.movements:
        if m.id in rep2.movements:
            shipped[(m.product, m.batch)] += m.qty
    assert dict(shipped) == {("B", "B1"): 5, ("B", "B2"): 4, ("A", None): 2}
    v = wh.view(D, "P")
    assert {(x.bin, x.batch): x.qty for x in v.bins if x.product == "B"} == {("S2", "B2"): 16, ("R2", "B0"): 30}
    assert all(x.product != "B" for x in v.loose) and v.notes == []


def test_a_short_pick_ships_what_was_found_and_asks_for_a_count():
    D = put_all(ds(plant()))
    D, rep = wh.create_wave(ds(_shop(D.model_dump(mode="json"), [("SO-1", "B", 12)])), "P")
    D, r = wh.confirm_task(D, rep.next_task, qty=10)
    assert "2 short" in r.message and "Count bin S2: the books say it still holds 10" in r.message
    assert "short: SO-1 10 of 12" in r.message
    assert D.deliveries[0].lines[0].picked == 10


def test_a_cancelled_pick_leaves_its_stock_and_the_delivery_ships_the_rest():
    D = put_all(ds(plant()))
    D, rep = wh.create_wave(ds(_shop(D.model_dump(mode="json"), [("SO-1", "B", 25)])), "P")
    s2, r1 = rep.tasks
    D, _ = wh.confirm_task(D, s2)
    D, r = wh.cancel_task(D, r1)
    assert "DL-1 is picked, short: SO-1 20 of 25" in r.message
    assert held(D)[("R1", "B")] == 10


# ---- the journal by bin -------------------------------------------------------------------------------------------

def test_stock_by_bin_adds_up_to_the_places_stock_and_a_posting_without_a_pick_takes_first_in_first_out():
    D = put_all(ds(plant()))
    d = D.model_dump(mode="json")
    d["movements"].append({"id": "GM-90001", "date": START, "type": "scrap", "location": "P", "product": "B",
                           "qty": 25, "note": "water damage"})
    D2 = ds(d)
    v = wh.view(D2, "P")
    assert held(D2) == {("S1", "A"): 10, ("R1", "B"): 5}        # S2 went in first (both on one day: walk order)
    assert "1 posting took stock out of bins without a pick (GM-90001)" in v.notes[0]
    by_place = place_stock(D2)
    for prod in ("A", "B"):
        assert sum(q for (b, p), q in held(D2).items() if p == prod) == pytest.approx(by_place[("P", prod)])


def test_a_release_from_inspection_stays_in_its_bin():
    d = plant()
    d["location_products"][1]["on_hand"] = 0
    d["movements"] = [{"id": "GM-00001", "date": "2026-01-04", "type": "opening", "location": "P", "product": "B",
                       "qty": 8, "stock_type": "quality", "bin": "S2"}]
    D, _ = move_stock(ds(d), "P", "B", None, StockType.QUALITY, StockType.UNRESTRICTED, on=DAY)
    v = wh.view(D, "P")
    assert [(r.bin, r.stock_type, r.qty) for r in v.bins if r.product] == [("S2", StockType.UNRESTRICTED, 8)]
    assert [x for x in v.loose if x.product == "B"] == []


def test_a_bin_move_refills_the_picking_area_and_refuses_what_does_not_fit():
    D = put_all(ds(plant()))
    with pytest.raises(wh.WarehouseError, match="cannot take"):
        wh.move_task(D, "P", "B", 10, "R1", "S1")              # S1 holds A
    D, rep = wh.move_task(D, "P", "B", 10, "R1", "R2")
    D, _ = wh.confirm_task(D, rep.next_task, scanned_bin="R2")
    assert held(D)[("R2", "B")] == 10 and ("R1", "B") not in held(D)


def test_a_count_in_progress_stops_bin_moves():
    D = ds(plant())
    D, rep = wh.create_putaway(D, "P")
    d = D.model_dump(mode="json")
    d["inventory_docs"] = [{"id": "PI-1", "date": START, "block": True,
                            "items": [{"location": "P", "product": "A", "book_qty": 10}]}]
    with pytest.raises(wh.WarehouseError, match="being counted"):
        wh.confirm_task(ds(d), rep.tasks[0])


def test_warehouse_records_that_do_not_fit_are_warnings_and_planning_goes_on():
    d = plant()
    d["bins"].append({"location": "P", "id": "Z1", "storage_type": "COLD"})
    d["putaway_rules"][0]["storage_types"].append("COLD")
    d["movements"] = [{"id": "GM-00001", "date": "2026-01-04", "type": "opening", "location": "P", "product": "A",
                       "qty": 1, "bin": "GONE"}]
    msgs = [(i.severity, i.object_type, i.message) for i in validate(ds(d)) if i.code == "WH_MISFIT"]
    assert ("warning", "bin", "bin Z1 is in storage type COLD, which P does not have") in msgs
    assert any(t == "putaway_rule" for _, t, _ in msgs) and any(t == "movement" for _, t, _ in msgs)
    assert plan_again(ds(d), None)[0].ok
    d["bins"].append(dict(d["bins"][0]))
    assert any(i.code == "DUP_ID" and i.object_id == "P/S1" for i in validate(ds(d)))


def test_a_place_without_bins_says_so():
    d = base()
    with pytest.raises(wh.WarehouseError, match="no bins"):
        wh.propose_putaway(ds(d), "P")
    assert wh.view(ds(d), "P").notes == ["no bins at this place yet: create its storage types and bins"]


# ---- through the API, on Kaveri's Delhi DC ------------------------------------------------------------------------

def test_kaveri_delhi_through_the_api_put_away_wave_scan_and_ship():
    c = TestClient(app, headers={"X-Browser-Key": "warehouse-tests-browser-0001"})
    d = example_dict("kitchenware_network")
    v = c.post("/api/warehouse", params={"location": "DC-DELHI"}, json=d).json()
    assert {r["product"]: r["to_put_away"] for r in v["loose"]} == {"KT-15": 1500, "MG-500": 1500, "MG-750": 900}
    r = c.post("/api/warehouse/act", json={"dataset": d, "action": "putaway", "location": "DC-DELHI"}).json()
    d = r["dataset"]
    for t in r["report"]["tasks"]:
        task = next(x for x in d["warehouse_tasks"] if x["id"] == t)
        d = c.post("/api/warehouse/act", json={"dataset": d, "action": "confirm", "task": t,
                                               "bin": task["to_bin"]}).json()["dataset"]
    shelves = {(b["bin"], b["product"]): b["qty"] for b in c.post("/api/warehouse", params={"location": "DC-DELHI"},
                                                                  json=d).json()["bins"] if b["product"]}
    # two shelves of 300 each for every product (bins_per_product 2), the rest in the rack by weight
    assert sum(1 for (b, _p) in shelves if b.startswith("S-")) == 6
    assert sum(shelves.values()) == 3900
    r = c.post("/api/sales/act", json={"dataset": d, "action": "create_deliveries",
                                       "lines": [{"order": "SO-88140"}, {"order": "SO-88190"}]})
    d = r.json()["dataset"]
    r = c.post("/api/warehouse/act", json={"dataset": d, "action": "wave", "location": "DC-DELHI"}).json()
    rows = r["picks"]["rows"]
    walks = [x["walk"] for x in rows]
    assert walks == sorted(walks) and {x["product"] for x in rows} == {"MG-500", "MG-750"}
    d = r["dataset"]
    bad = c.post("/api/warehouse/act", json={"dataset": d, "action": "confirm", "task": r["report"]["next_task"],
                                             "product": "8906011250029"})          # the kettle's barcode
    assert bad.status_code == 409 and "Electric kettle" in bad.json()["detail"]
    assert c.post("/api/warehouse/picks", params={"wave": "WV-9"}, json=d).status_code == 409


def test_the_picking_area_goes_before_an_older_reserve():
    d = plant()
    d["location_products"][1]["on_hand"] = 0
    d["movements"] = [
        {"id": "GM-00001", "date": "2026-01-01", "type": "opening", "location": "P", "product": "B", "qty": 10, "bin": "R1"},
        {"id": "GM-00002", "date": "2026-01-04", "type": "opening", "location": "P", "product": "B", "qty": 10, "bin": "S2"}]
    D, rep = wh.create_wave(ds(_shop(d, [("SO-1", "B", 12)])), "P")
    # first in first out would take the rack's (in since 1 January); a reserve is picked from after the shelves
    assert [(t.from_bin, t.qty) for t in D.warehouse_tasks] == [("S2", 10), ("R1", 2)]


def test_open_put_away_tasks_hold_their_room():
    D, _ = wh.create_putaway(ds(plant()), "P")                 # A 10 to S1, B 20 to S2, B 10 to R1: not done yet
    d = D.model_dump(mode="json")
    d["movements"].append({"id": "GM-90001", "date": START, "type": "adjustment", "location": "P", "product": "A",
                           "qty": 70})
    p = wh.propose_putaway(ds(d), "P")
    # the 10 A on their way to S1 count: S1 has room for 10 more; R1 is spoken for by B
    assert [(t.product, t.qty, t.to_bin) for t in p.tasks] == [("A", 10, "S1"), ("A", 50, "R2")]


def test_a_pick_from_a_bin_emptied_meanwhile_is_refused():
    D = put_all(ds(plant()))
    D, rep = wh.create_wave(ds(_shop(D.model_dump(mode="json"), [("SO-1", "B", 12)])), "P")
    d = D.model_dump(mode="json")
    d["movements"].append({"id": "GM-90001", "date": START, "type": "scrap", "location": "P", "product": "B",
                           "qty": 25, "note": "water damage"})
    with pytest.raises(wh.WarehouseError, match="bin S2 holds only 0"):
        wh.confirm_task(ds(d), rep.next_task)
