"""Enterprise 5.1: planning again after a change plans only the nodes the change reaches (S/4 net change planning).

The oracle is planning from scratch: after any one change (or several in a row), the plan made from the previous
plan's work must be byte for byte the plan made from nothing. Changes are drawn at random over every record the
supply plan reads (and some it does not), on the example companies and on random networks."""
from __future__ import annotations

import copy
import random
from datetime import date, timedelta

import pytest

from scp.model import Dataset
from scp.plan.mrp import plan_again

from .factory import example_dict
from .strategies import network

READ = ["demand", "location_products", "receipts", "products", "purchasing_sources", "production_sources", "lanes",
        "stock_targets"]
UNREAD = ["history", "customers", "customer_prices", "budgets", "overrides"]


def _bump(v, rng: random.Random):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return max(0, v + rng.choice([-2, -1, 1, 3]))
    if isinstance(v, float):
        return round(v * rng.choice([0.0, 0.5, 0.9, 1.1, 2.0]), 4)
    if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
        return (date.fromisoformat(v) + timedelta(days=rng.choice([-7, -2, 1, 3, 10]))).isoformat()
    return None


def _fields(rec: dict, path: tuple = ()) -> list[tuple]:
    out = []
    for k, v in rec.items():
        if k in ("id", "location", "product", "supplier", "origin", "destination") and not path:
            continue
        if isinstance(v, dict):
            out += _fields(v, (*path, k))
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            for i, x in enumerate(v):
                out += _fields(x, (*path, k, i))
        elif _bump(v, random.Random(0)) is not None:
            out.append((*path, k))
    return out


def change(d: dict, rng: random.Random) -> str:
    """One random change, as a planner would make it: a number, flag or date on a record, a record added or taken
    away. Returns what was done."""
    roll = rng.random()
    if roll < 0.12 and d.get("demand"):
        i = rng.randrange(len(d["demand"]))
        rec = copy.deepcopy(d["demand"][i])
        rec.pop("id", None)
        rec["kind"] = "sales_order"
        rec["id"] = f"SO-NEW-{rng.randrange(10**6)}"
        rec.pop("period_days", None)
        d["demand"].append(rec)
        return f"added sales order {rec['id']}"
    if roll < 0.18 and d.get("demand"):
        gone = d["demand"].pop(rng.randrange(len(d["demand"])))
        return f"removed demand {gone.get('id')}"
    if roll < 0.24 and d.get("receipts"):
        gone = d["receipts"].pop(rng.randrange(len(d["receipts"])))
        return f"removed receipt {gone['id']}"
    if roll < 0.30:      # what every node reads: settings, places, calendars
        coll = rng.choice(["settings", "locations", "calendars"])
        rec = d[coll] if coll == "settings" else rng.choice(d[coll])
    else:
        coll = rng.choice([c for c in READ + UNREAD if d.get(c)])
        rec = rng.choice(d[coll])
    paths = _fields(rec)
    if not paths:
        return "nothing"
    path = rng.choice(paths)
    holder = rec
    for p in path[:-1]:
        holder = holder[p]
    old = holder[path[-1]]
    holder[path[-1]] = _bump(old, rng)
    return f"{coll}.{'.'.join(map(str, path))}: {old!r} -> {holder[path[-1]]!r}"


def text(plan) -> str:
    return plan.model_dump_json(exclude={"planned_again"})


def full(d: dict):
    return plan_again(Dataset.model_validate(d), None)


def valid_change(d: dict, rng: random.Random) -> str:
    """A random change that leaves a company the screens would accept (field types and ranges)."""
    for _ in range(50):
        before = copy.deepcopy(d)
        what = change(d, rng)
        try:
            Dataset.model_validate(d)
            return what
        except ValueError:
            d.clear()
            d.update(before)
    return "nothing"


def check(d0: dict, seed: int, steps: int) -> int:
    """Plan ``d0``, then make ``steps`` changes in a row, each planned from the previous plan's work and from
    scratch; the two must be the same. Returns how many changes were planned from the previous work."""
    rng = random.Random(seed)
    res, kept = full(d0)
    d, reused = copy.deepcopy(d0), 0
    for _ in range(steps):
        what = valid_change(d, rng)
        ds = Dataset.model_validate(d)
        inc, k2 = plan_again(ds, kept)
        ref, _ = plan_again(Dataset.model_validate(d), None)
        same = text(inc) == text(ref)    # (a bool: no diff of two long texts)
        assert same, what
        reused += bool(k2 and k2.reused)
        kept = k2
    return reused


@pytest.mark.parametrize("name", ["kitchenware_network", "chennai_port_pumps", "single_product_plant"])
def test_planning_again_after_random_changes_is_planning_from_scratch(name):
    reused = sum(check(example_dict(name), seed, 6) for seed in range(6))
    assert reused >= 12          # most changes are planned from the previous work, not from scratch


@pytest.mark.parametrize("seed", range(24))
def test_on_random_networks(seed):
    check(network(seed), seed, 5)


def again_equals_scratch(before: dict, after: dict) -> int:
    """Plan ``before``, then ``after`` from its work; the plan must be the one made from scratch. Returns how many
    nodes were planned again."""
    _, kept = full(before)
    inc, k2 = plan_again(Dataset.model_validate(after), kept)
    same = text(inc) == text(full(after)[0])
    assert inc.planned_again == (k2.planned if k2.reused else None)
    assert same, "planned again differs from planned from scratch"
    return k2.planned


def phantom_plant() -> dict:
    """Product A made at P from 2 of the phantom assembly SUB (never stocked), itself made of 3 B; demand for A."""
    from .factory import base, demand
    d = base()
    d["products"].append({"id": "SUB", "type": "SFG"})
    d["location_products"].append({"location": "P", "product": "SUB", "phantom": True})
    d["production_sources"][0]["components"] = [{"product": "SUB", "qty": 2}, {"product": "C", "qty": 1}]
    d["production_sources"].append({"id": "PV-SUB", "location": "P", "product": "SUB", "fixed_lead_time_workdays": 1,
                                    "components": [{"product": "B", "qty": 3}]})
    d["demand"] = [demand("P", "A", "2026-01-12", 40), demand("P", "A", "2026-01-19", 30)]
    return d


def test_a_phantoms_own_bill_of_material_reaches_the_product_made_from_it():
    # the change is to SUB's bill of material alone: A's records are as they were, but A now draws 4 B for each
    # SUB, so A is planned again, and B after it
    d = phantom_plant()
    d["purchasing_sources"][0]["price"] = 0      # B costs nothing: A's unit value does not show the change either
    after = copy.deepcopy(d)
    after["production_sources"][1]["components"][0]["qty"] = 4
    planned = again_equals_scratch(d, after)
    assert 0 < planned < len(Dataset.model_validate(after).location_products) + 1


def test_a_change_nothing_reads_replans_nothing():
    d = phantom_plant()
    after = copy.deepcopy(d)
    after["history"] = [{"location": "P", "product": "A", "date": "2025-12-29", "qty": 12}]
    assert again_equals_scratch(d, after) == 0


def test_a_forecast_change_replans_its_node_and_what_it_draws_on_only():
    d = example_dict("kitchenware_network")
    after = copy.deepcopy(d)
    i = next(i for i, r in enumerate(after["demand"]) if r["kind"] == "forecast")
    after["demand"][i]["qty"] *= 1.5
    planned = again_equals_scratch(d, after)
    nodes = len(full(after)[0].nodes)
    assert 0 < planned < nodes / 2


def test_an_order_the_change_does_not_reach_keeps_its_number():
    """The usability log's case: 6,000 more heater elements at Pune. The heaters and the part they go into are planned
    again; one requisition for heaters is no longer needed, and every other order keeps its number, as planned orders
    are numbered by their product at its place, not in one sequence over the network."""
    d = example_dict("kitchenware_network")
    after = copy.deepcopy(d)
    next(x for x in after["location_products"]
         if (x["location"], x["product"]) == ("PLT-PUNE", "RM-HEATER"))["on_hand"] = 20000
    assert again_equals_scratch(d, after) == 2
    was = {o.id: o for o in full(d)[0].orders}
    now = {o.id: o for o in full(after)[0].orders}
    assert sorted(set(was) - set(now)) == ["PR-0025-03"] and set(now) <= set(was)
    gone = was["PR-0025-03"]
    assert (gone.product, gone.location) == ("RM-HEATER", "PLT-PUNE")
    assert all(now[k].product == o.product and now[k].location == o.location for k, o in was.items() if k in now)


def test_a_make_to_order_plant_follows_the_order_its_shipment_now_serves():
    """The warehouse ships two orders of the same day from stock for one and a transfer for the other; which one the
    transfer serves follows their priorities. Swapping them leaves the transfer, and what the plant is asked for, as
    they were, but the plant makes for the other order now."""
    from .factory import base, demand
    d = base()
    d["locations"] += [{"id": "W", "type": "dc"}]
    d["lanes"] = [{"id": "LN", "origin": "P", "destination": "W", "modes": [{"mode": "truck_ftl", "transit_days": 1}]}]
    d["location_products"] += [{"location": "W", "product": "A", "on_hand": 10, "strategy": "MTO"}]
    d["location_products"][0].update(strategy="MTO", on_hand=0)
    d["demand"] = [demand("W", "A", "2026-01-20", 10, "sales_order", id="SO-1", priority=1),
                   demand("W", "A", "2026-01-20", 10, "sales_order", id="SO-2", priority=2)]
    after = copy.deepcopy(d)
    after["demand"][0]["priority"], after["demand"][1]["priority"] = 2, 1
    made = {o.sales_order for o in full(after)[0].orders if o.kind == "make"}
    assert made == {"SO-1"} != {o.sales_order for o in full(d)[0].orders if o.kind == "make"}
    again_equals_scratch(d, after)


@pytest.mark.parametrize("what", ["loading time at the shipping place", "a holiday"])
def test_a_change_every_node_reads_plans_everything_again(what):
    d = example_dict("kitchenware_network")
    after = copy.deepcopy(d)
    if what == "a holiday":
        after["calendars"][0].setdefault("holidays", []).append("2026-10-06")
    else:
        plant = next(x for x in after["locations"] if x["type"] == "plant")
        plant["loading_workdays"] = plant.get("loading_workdays", 0) + 2
    assert full(after)[0].model_dump_json() != full(d)[0].model_dump_json()
    assert again_equals_scratch(d, after) == len(full(after)[0].nodes)


# --- the work kept by who plans (CI found two browsers planning the same company in turn: the second read "nothing
# changed" of its own change, because the first had planned the changed data just before)

def _heater(d: dict, qty: float) -> dict:
    d = copy.deepcopy(d)
    lp = next(x for x in d["location_products"] if x["location"] == "PLT-PUNE" and x["product"] == "RM-HEATER")
    lp["on_hand"] = qty
    return d


def _as(owner: str, d: dict):
    from scp.plan.mrp import plan_owner, run_mrp
    tok = plan_owner.set(owner)
    try:
        return run_mrp(Dataset.model_validate(d))
    finally:
        plan_owner.reset(tok)


@pytest.fixture
def no_kept(monkeypatch):
    from collections import OrderedDict

    import scp.plan.mrp as mrp
    monkeypatch.setattr(mrp, "_kept", OrderedDict())
    monkeypatch.setattr(mrp, "_last", None)
    monkeypatch.setattr(mrp, "_last_work", None)
    return mrp


def test_each_planner_plans_again_from_their_own_last_plan(no_kept):
    d = example_dict("kitchenware_network")
    _as("a", d)
    _as("b", d)
    _as("b", _heater(d, 20000))                 # b plans the change first
    mine = _as("a", _heater(d, 20000))          # a's own last plan is still the one before the change
    assert mine.planned_again and 0 < mine.planned_again < len(mine.nodes) / 2
    again = _as("a", _heater(d, 20000))
    assert again.planned_again == 0             # and now nothing has changed since a's last plan


def test_two_companies_planned_in_turn_each_plan_again_from_their_own_work(no_kept):
    k, c = example_dict("kitchenware_network"), example_dict("chennai_port_pumps")
    _as("kaveri", k)
    _as("chennai", c)
    assert _as("kaveri", _heater(k, 20000)).planned_again       # not from scratch (None): Chennai's work is apart
    assert _as("chennai", c).planned_again == 0


def test_the_newest_work_is_kept_and_older_ones_within_the_budget(no_kept, monkeypatch):
    d = example_dict("kitchenware_network")
    _as("a", d)
    n = len(no_kept._kept["a"].memo)
    monkeypatch.setattr(no_kept, "KEPT_NODES", 2 * n)
    _as("b", d)
    _as("a", d)                                        # a plans again: now the newer of the two
    _as("c", d)
    assert list(no_kept._kept) == ["a", "c"]           # b, the oldest, made way
    monkeypatch.setattr(no_kept, "KEPT_NODES", 1)
    _as("a", d)
    assert list(no_kept._kept) == ["a"]                # over the budget alone: the newest is still kept
    assert _as("c", _heater(d, 20000)).planned_again is None     # c's work was dropped: planned from scratch


def test_a_planner_answered_with_anothers_kept_plan_keeps_its_work_too(no_kept, monkeypatch):
    # e2e plan-again: two browsers open the same example; the second is answered with the first one's plan (the
    # same data), and its own correction must still be planned again only where it reaches, not from scratch
    monkeypatch.setattr(no_kept, "_KEEP_AFTER_S", 0.0)
    d = example_dict("kitchenware_network")
    first = _as("a", d)
    assert _as("b", d) is first                         # the kept plan, not planned again
    mine = _as("b", _heater(d, 20000))
    assert mine.planned_again and 0 < mine.planned_again < len(mine.nodes) / 2
    assert list(no_kept._kept) == ["a", "b"] and len({id(k) for k in no_kept._kept.values()}) == 2


def test_one_plans_work_held_by_two_planners_counts_once_in_the_budget(no_kept, monkeypatch):
    monkeypatch.setattr(no_kept, "_KEEP_AFTER_S", 0.0)
    d = example_dict("kitchenware_network")
    _as("a", d)
    monkeypatch.setattr(no_kept, "KEPT_NODES", len(no_kept._kept["a"].memo))
    _as("b", d)                                          # answered with a's plan: the same work, held once
    assert list(no_kept._kept) == ["a", "b"]
    _as("c", _heater(d, 20000))                          # c's own work: over the budget, so a's goes, and b still
    assert list(no_kept._kept) == ["c"]                  # holds the same work: dropping a frees nothing till b goes


def test_two_browsers_planning_through_the_api_keep_apart(no_kept):
    from fastapi.testclient import TestClient

    from scp.api.app import app
    a = TestClient(app, headers={"X-Browser-Key": "incremental-browser-a-0001"})
    b = TestClient(app, headers={"X-Browser-Key": "incremental-browser-b-0001"})
    d = example_dict("kitchenware_network")
    a.post("/api/plan", json=d)
    b.post("/api/plan", json=_heater(d, 20000))
    got = a.post("/api/plan", json=_heater(d, 20000)).json()
    assert got["ok"] and 0 < got["planned_again"] < len(got["nodes"]) / 2
