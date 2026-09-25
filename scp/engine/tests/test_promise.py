"""P6 order promising against the S/4 guide §20.1 scenarios 2–5 (full stock, partial stock with split
schedule lines and RLT behaviour, allocation-constrained order with its fallback rule, backorder
processing after a shortage), plus alternative-based confirmation, capable-to-promise across
transfer → production → purchase, the ATP look-ahead and commit."""
from __future__ import annotations

from datetime import date

import pytest

from scp.model import DemandRecord
from scp.promise import check_order, commit, run_bop, run_promise
from scp.promise.atp import AtpSeries

from .factory import base, demand, ds, load_example, lp


def net(**promising) -> dict:
    """Plant P (base: A from 2 B + C) → DC D (2 days) and DC D2 (2 days); customers C1 served by D
    (1 day, first) or D2 (3 days, alternative) and C2 served by D. Promising checks stock and firm
    receipts only, with no RLT, no CTP and no alternatives unless a test turns them on."""
    d = base(horizon=56)
    d["locations"] += [{"id": "D", "type": "dc"}, {"id": "D2", "type": "dc"},
                       {"id": "C1", "type": "customer"}, {"id": "C2", "type": "customer"}]
    d["lanes"] = [
        {"id": "PD", "origin": "P", "destination": "D", "modes": [{"transit_days": 2}]},
        {"id": "PD2", "origin": "P", "destination": "D2", "modes": [{"transit_days": 2}]},
        {"id": "DC1", "origin": "D", "destination": "C1", "modes": [{"transit_days": 1}], "priority": 1},
        {"id": "D2C1", "origin": "D2", "destination": "C1", "modes": [{"transit_days": 3}], "priority": 2},
        {"id": "DC2", "origin": "D", "destination": "C2", "modes": [{"transit_days": 1}]},
    ]
    lp(d, "D", "A")["on_hand"] = 0
    lp(d, "D2", "A")["on_hand"] = 0
    d["promising"] = {"include_planned_orders": False, "confirm_beyond_rlt": False, "ctp": False,
                      "alternative_locations": False, **promising}
    return d


def so(loc: str, qty: float, day: str, oid: str, **kw) -> dict:
    return demand(loc, "A", day, qty, "sales_order", id=oid, **kw)


def lines(o):
    return [(x.ship_from, x.ship_date.isoformat(), x.date.isoformat(), x.qty, x.method) for x in o.lines]


# ---- the ATP series ---------------------------------------------------------------------------
def test_look_ahead_protects_later_promises():
    s = AtpSeries(10)
    s.add_in(0, 100)
    s.add_out(5, 80)           # a later promise
    assert s.available(0) == 20 and s.available(5) == 20
    s.add_in(7, 50)
    assert s.available(7) == 70 and s.available(2) == 20
    r = AtpSeries(10, rlt_day=4)
    r.add_in(0, 10)
    assert r.available(3) == 10 and r.available(4) == float("inf") and r.unconditional(6)


# ---- §20.1 scenario 2: full stock -------------------------------------------------------------
def test_order_with_full_stock_confirms_on_requested_date():
    d = net()
    lp(d, "D", "A")["on_hand"] = 100
    d["demand"] = [so("C1", 40, "2026-01-12", "SO1")]
    r = run_promise(ds(d))
    o = r.orders[0]
    assert o.status == "on_time"
    assert lines(o) == [("D", "2026-01-11", "2026-01-12", 40, "atp")]
    atp = next(n for n in r.nodes if n.location == "D")
    assert atp.promised[6] == 40 and atp.available[0] == 60   # the promise is an outflow at the ship date


# ---- §20.1 scenario 3: partial stock, split lines, RLT ----------------------------------------
def _partial(**kw) -> dict:
    d = net(**kw)
    lp(d, "D", "A")["on_hand"] = 30
    d["receipts"] = [{"id": "STO1", "kind": "transfer", "location": "D", "product": "A", "qty": 50,
                      "due_date": "2026-01-15"}]
    d["demand"] = [so("C1", 60, "2026-01-10", "SO1")]
    return d


def test_partial_stock_splits_schedule_lines():
    o = run_promise(ds(_partial())).orders[0]
    assert lines(o) == [("D", "2026-01-09", "2026-01-10", 30, "atp"), ("D", "2026-01-15", "2026-01-16", 30, "atp")]
    assert o.status == "late" and o.on_time == 30


def test_complete_delivery_waits_for_the_full_quantity():
    d = _partial()
    d["demand"][0]["complete_delivery"] = True
    o = run_promise(ds(d)).orders[0]
    assert lines(o) == [("D", "2026-01-15", "2026-01-16", 60, "atp")]


def test_rlt_confirms_unconditionally_or_leaves_a_backorder():
    d = _partial()
    d["receipts"] = []
    o = run_promise(ds(d)).orders[0]
    assert o.status == "partial" and o.unconfirmed == 30              # RLT check off: backorder
    d["promising"]["confirm_beyond_rlt"] = True
    r = run_promise(ds(d))
    o = r.orders[0]
    # RLT at D = transit 2 + P's production 2 days + longest component (B, 3 days) = 7 days
    assert next(n.rlt_days for n in r.nodes if n.location == "D") == 7
    assert lines(o) == [("D", "2026-01-09", "2026-01-10", 30, "atp"), ("D", "2026-01-12", "2026-01-13", 30, "rlt")]


# ---- §20.1 scenario 4: allocation ---------------------------------------------------------------
def _allocated(fallback: str) -> dict:
    d = net()
    lp(d, "D", "A")["on_hand"] = 1000
    d["allocations"] = [
        {"id": "AL1", "product": "A", "customers": ["C1"], "start": "2026-01-05", "end": "2026-01-12", "qty": 50,
         "fallback": fallback},
        {"id": "AL2", "product": "A", "customers": ["C1"], "start": "2026-01-12", "end": "2026-01-19", "qty": 40,
         "fallback": fallback},
    ]
    d["demand"] = [so("C1", 80, "2026-01-08", "SO1"), so("C2", 500, "2026-01-08", "SO2")]
    return d


def test_allocation_caps_and_next_period_fallback():
    r = run_promise(ds(_allocated("next_period")))
    o = r.orders[0]
    assert o.allocation_capped == 30
    assert lines(o) == [("D", "2026-01-07", "2026-01-08", 50, "atp"), ("D", "2026-01-12", "2026-01-13", 30, "atp")]
    assert {a.id: a.used for a in r.allocations} == {"AL1": 50, "AL2": 30}
    assert r.orders[1].status == "on_time"                               # C2 is not allocated


def test_allocation_reject_fallback():
    o = run_promise(ds(_allocated("reject"))).orders[0]
    assert lines(o) == [("D", "2026-01-07", "2026-01-08", 50, "atp")] and o.status == "partial"


# ---- alternative-based confirmation --------------------------------------------------------------
def test_alternative_location_confirms_on_time():
    d = net(alternative_locations=True)
    lp(d, "D2", "A")["on_hand"] = 100
    d["demand"] = [so("C1", 50, "2026-01-10", "SO1")]
    r = run_promise(ds(d))
    assert lines(r.orders[0]) == [("D2", "2026-01-07", "2026-01-10", 50, "atp")]
    assert r.kpis.alternative_lines == 1
    d["promising"]["alternative_locations"] = False
    assert run_promise(ds(d)).orders[0].status == "unconfirmed"


# ---- capable-to-promise -----------------------------------------------------------------------
def test_ctp_through_transfer_production_and_purchase():
    d = net(ctp=True)
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [so("C1", 10, "2026-01-08", "SO1")]
    o = run_promise(ds(d)).orders[0]
    # C bought today (1 day) → make A from day 1 (2 workdays) → ship P→D (2 days) → ship to C1 (1 day)
    assert lines(o) == [("D", "2026-01-10", "2026-01-11", 10, "ctp")]
    assert [s.kind for s in o.ctp] == ["component", "buy", "capacity", "make", "transfer"]
    d["promising"]["ctp"] = False
    assert run_promise(ds(d)).orders[0].status == "unconfirmed"


def test_ctp_uses_source_stock_before_building():
    d = net(ctp=True)
    lp(d, "P", "A")["on_hand"] = 40
    d["demand"] = [so("C1", 25, "2026-01-08", "SO1")]
    o = run_promise(ds(d)).orders[0]
    assert [s.kind for s in o.ctp] == ["stock", "transfer"]
    assert lines(o) == [("D", "2026-01-07", "2026-01-08", 25, "ctp")]   # stock at P arrives at D in time


# ---- commit, risk and §20.1 scenario 5: BOP after a shortage ---------------------------------------
def _bop_case() -> dict:
    d = net()
    lp(d, "D", "A")["on_hand"] = 100
    d["demand"] = [so("C2", 80, "2026-01-10", "SO-LOW", priority=8), so("C1", 80, "2026-01-10", "SO-HIGH", priority=1)]
    return d


def test_commit_persists_confirmations_and_entry_keeps_them():
    d = _bop_case()
    new, res = commit(ds(d))
    assert {c.order: c.qty for c in new.confirmations} == {"SO-LOW": 80, "SO-HIGH": 20}
    r = run_promise(new)
    assert [o.change for o in r.orders] == ["kept", "kept"] and r.kpis.at_risk_orders == 0


def test_bop_after_shortage_priority_gains_low_priority_loses():
    new, _ = commit(ds(_bop_case()))            # first come, first served: LOW 80, HIGH 20
    d = new.model_dump(mode="json")
    lp(d, "D", "A")["on_hand"] = 90              # a shortage: promises (100) exceed supply (90)
    r = run_promise(ds(d))
    assert r.kpis.at_risk_orders == 2
    b = run_bop(ds(d))
    by = {o.order: o for o in b.orders}
    assert by["SO-HIGH"].confirmed == 80 and by["SO-HIGH"].change == "gained"   # WIN segment
    assert by["SO-LOW"].confirmed == 10 and by["SO-LOW"].change == "lost"       # LOSE segment
    log = {x.order: x for x in b.bop}
    assert (log["SO-HIGH"].before_confirmed, log["SO-HIGH"].after_confirmed) == (20, 80)
    assert log["SO-LOW"].segment == "Low priority" and log["SO-LOW"].strategy == "lose"
    committed, _ = commit(ds(d), "bop")
    assert {c.order: c.qty for c in committed.confirmations} == {"SO-LOW": 10, "SO-HIGH": 80}


def test_lose_never_gains_and_fill_keeps_its_lines():
    d = _bop_case()
    d["demand"][0]["priority"] = 5               # LOW becomes "Standard" (redistribute)
    new, _ = commit(ds(d))
    x = new.model_dump(mode="json")
    x["promising"]["bop_segments"] = [
        {"name": "Keep", "priorities": [5], "strategy": "fill"},
        {"name": "Give back", "priorities": [1], "strategy": "lose"},
    ]
    lp(x, "D", "A")["on_hand"] = 200             # more supply: LOSE may not take it, FILL may top up
    b = {o.order: o for o in run_bop(ds(x)).orders}
    assert b["SO-HIGH"].confirmed == 20          # lose: capped at what it had
    assert b["SO-LOW"].confirmed == 80 and lines(b["SO-LOW"])[0][1] == "2026-01-09"


def test_check_simulates_without_persisting():
    d = _bop_case()
    r = check_order(ds(d), DemandRecord(location="C1", product="A", date=date(2026, 1, 10), qty=5))
    assert r.mode == "check" and r.checked is not None and r.checked.status == "unconfirmed"  # all 100 taken
    assert ds(d).confirmations == []


# ---- example -------------------------------------------------------------------------------
def test_example_promising():
    ex = load_example("kitchenware_network")
    r = run_promise(ex)
    assert r.ok and r.kpis.orders == 9
    assert r.kpis.confirmed_qty == pytest.approx(r.kpis.qty)
    kt = next(o for o in r.orders if o.order == "SO-88221")
    assert kt.allocation_capped > 0                  # the e-commerce kettle allocation binds
    for n in r.nodes:
        assert all(a is None or a >= 0 for a in n.available)
    b = run_bop(ex)
    assert b.ok and len(b.bop) == 9
