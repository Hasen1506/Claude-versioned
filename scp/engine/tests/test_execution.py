"""Phase F: execution you can trust. Setup stock is the opening balance (Q1), a transfer ships and arrives (Q2), a
production order issues its parts when it is received (Q3), stock counts post openings or differences (Q13)."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals.stock import before
from scp.actuals import PostingError, actuals_view, count_stock, firm_orders, receive, roll_forward, ship
from scp.api.app import app
from scp.model import MovementType
from scp.plan import run_mrp
from scp.validate import validate

from .factory import base, demand, ds, lp

START = date(2026, 1, 5)
NEXT = date(2026, 1, 12)


def on_hand(x, loc: str, prod: str) -> float:
    return next((y.on_hand for y in x.location_products if (y.location, y.product) == (loc, prod)), 0.0)


def journal(x, loc: str, prod: str, until: date) -> float:
    """Stock by the journal, setup stock not yet journalled included."""
    return sum(m.signed for m in before(x, until) if (m.location, m.product) == (loc, prod))


def mv(i, day, typ, loc, prod, qty, **kw) -> dict:
    return {"id": f"GM-{i:05d}", "date": day, "type": typ, "location": loc, "product": prod, "qty": qty, **kw}


def network() -> dict:
    """Plant P makes A (2×B + 1×C) and ships it to warehouse W over a 2-day lane; demand is at W."""
    d = base(horizon=42)
    d["locations"].append({"id": "W", "type": "warehouse"})
    d["lanes"] = [{"id": "PW", "origin": "P", "destination": "W", "modes": [{"transit_days": 2}]}]
    lp(d, "W", "A")["on_hand"] = 0
    d["demand"] = [demand("W", "A", "2026-01-08", 40), demand("W", "A", "2026-01-15", 40)]
    return d


def firmed(d: dict):
    x = ds(d)
    new, rep = firm_orders(x, run_mrp(x), within_days=10)
    assert rep.ok
    return new, rep


# ---- Q1: setup stock is the opening balance ---------------------------------------------------------------
def test_setup_stock_survives_the_first_movement():
    d = base()
    lp(d, "P", "A")["on_hand"] = 900
    d["movements"] = [mv(1, "2026-01-06", "receipt", "P", "A", 25.9)]
    x = ds(d)
    row = next(r for r in actuals_view(x).stock if (r.location, r.product) == ("P", "A"))
    assert row.movement_stock == pytest.approx(900) and row.difference == 0 and row.opening_from_setup
    assert not [i for i in validate(x) if i.code == "STOCK_NOT_SYNCED"]
    new, rep = roll_forward(x, NEXT)
    assert on_hand(new, "P", "A") == pytest.approx(925.9)
    op = [m for m in new.movements if m.type is MovementType.OPENING and m.product == "A"]
    assert len(op) == 1 and op[0].qty == 900 and op[0].date == date(2026, 1, 4)
    assert on_hand(new, "P", "B") == 30                          # untouched place: its opening is journalled too
    again, _ = roll_forward(new, NEXT)                            # idempotent: no second opening
    assert len(again.movements) == len(new.movements) and on_hand(again, "P", "A") == pytest.approx(925.9)
    later, _ = roll_forward(new, date(2026, 1, 19))
    assert on_hand(later, "P", "A") == pytest.approx(925.9)


def test_a_place_with_earlier_movements_keeps_the_journal_as_truth():
    d = base()
    lp(d, "P", "A")["on_hand"] = 900
    d["movements"] = [mv(1, "2026-01-01", "opening", "P", "A", 10)]
    row = next(r for r in actuals_view(ds(d)).stock if (r.location, r.product) == ("P", "A"))
    assert row.movement_stock == 10 and row.difference == -890 and not row.opening_from_setup


# ---- Q13: counting stock ---------------------------------------------------------------------------------
def test_count_replaces_setup_stock_and_posts_the_opening_balance():
    d = base()
    lp(d, "P", "A")["on_hand"] = 900
    x, rep = count_stock(ds(d), [{"location": "P", "product": "A", "qty": 850},
                                 {"location": "P", "product": "B", "qty": 0},
                                 {"location": "P", "product": "C", "qty": 12}])
    assert on_hand(x, "P", "A") == 850 and on_hand(x, "P", "B") == 0 and on_hand(x, "P", "C") == 12
    assert journal(x, "P", "A", START) == 850 and journal(x, "P", "C", START) == 12
    kinds = {(m.product, m.type.value) for m in x.movements}
    assert kinds == {("A", "opening"), ("C", "opening")} and "2 opening balances" in rep.message
    assert not [i for i in validate(x) if i.code in ("STOCK_NOT_SYNCED", "NEGATIVE_STOCK")]
    new, _ = roll_forward(x, NEXT)
    assert on_hand(new, "P", "A") == 850 and on_hand(new, "P", "B") == 0


def test_count_on_a_place_with_a_journal_posts_the_difference():
    d = base()
    d["movements"] = [mv(1, "2026-01-01", "opening", "P", "A", 10), mv(2, "2026-01-02", "sale", "P", "A", 4)]
    lp(d, "P", "A")["on_hand"] = 6
    x, _ = count_stock(ds(d), [{"location": "P", "product": "A", "qty": 5}])
    adj = x.movements[-1]
    assert adj.type is MovementType.ADJUSTMENT and adj.qty == -1 and on_hand(x, "P", "A") == 5
    # a count during the week counts when the plan moves past it, from what the journal says by then
    d["movements"].append(mv(3, "2026-01-07", "sale", "P", "A", 2))
    y, rep = count_stock(ds(d), [{"location": "P", "product": "A", "qty": 3}], on=date(2026, 1, 8))
    assert y.movements[-1].qty == -1 and on_hand(y, "P", "A") == 6 and "moves past" in rep.message
    assert on_hand(roll_forward(y, NEXT)[0], "P", "A") == 3
    with pytest.raises(PostingError):
        count_stock(ds(d), [{"location": "P", "product": "A", "qty": -1}])


# ---- Q2: a transfer ships and arrives ----------------------------------------------------------------------
def test_transfer_ships_then_arrives_with_stock_in_transit():
    d = network()
    lp(d, "P", "A")["on_hand"] = 100
    x, rep = firmed(d)
    sto = next(f for f in rep.firmed if f.kind == "transfer")
    x, r1 = ship(x, sto.receipt_id, on=date(2026, 1, 5))
    row = next(o for o in actuals_view(x, NEXT).open_orders if o.id == sto.receipt_id)
    assert row.in_transit == pytest.approx(sto.qty) and "in transit" in r1.message
    x, _ = receive(x, sto.receipt_id, on=date(2026, 1, 7))
    assert journal(x, "P", "A", NEXT) == pytest.approx(100 - sto.qty)
    assert journal(x, "W", "A", NEXT) == pytest.approx(sto.qty)
    new, _ = roll_forward(x, NEXT)
    assert on_hand(new, "P", "A") + on_hand(new, "W", "A") == pytest.approx(100)
    assert sto.receipt_id not in {r.id for r in new.receipts}
    with pytest.raises(PostingError):
        ship(x, sto.receipt_id)                                   # everything shipped already


def test_receiving_an_unshipped_transfer_takes_it_out_of_the_origin():
    d = network()
    lp(d, "P", "A")["on_hand"] = 100
    x, rep = firmed(d)
    sto = next(f for f in rep.firmed if f.kind == "transfer")
    x, r = receive(x, sto.receipt_id, qty=10, on=date(2026, 1, 6))
    kinds = [(m.type.value, m.location) for m in x.movements if m.reference == sto.receipt_id]
    assert kinds == [("receipt", "W"), ("transfer_out", "P")] and "taken out of P" in r.message
    # ship the rest, then receive it: nothing is issued twice
    x, _ = ship(x, sto.receipt_id, on=date(2026, 1, 6))
    x, _ = receive(x, sto.receipt_id, on=date(2026, 1, 8))
    out = sum(m.qty for m in x.movements if m.reference == sto.receipt_id and m.type is MovementType.TRANSFER_OUT)
    got = sum(m.qty for m in x.movements if m.reference == sto.receipt_id and m.type is MovementType.RECEIPT)
    assert out == pytest.approx(sto.qty) == pytest.approx(got)


# ---- Q3: production issues its parts ------------------------------------------------------------------------
def test_production_receipt_backflushes_its_parts():
    d = base()
    lp(d, "P", "B")["on_hand"] = 200
    lp(d, "P", "C")["on_hand"] = 100
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [demand("P", "A", "2026-01-09", 40)]
    x, rep = firmed(d)
    prd = next(f for f in rep.firmed if f.kind == "production")
    x, r = receive(x, prd.receipt_id, qty=prd.qty / 2, on=date(2026, 1, 8))
    issued = {m.product: m.qty for m in x.movements if m.type is MovementType.ISSUE}
    assert issued == {"B": pytest.approx(prd.qty), "C": pytest.approx(prd.qty / 2)} and "issued" in r.message
    x, _ = receive(x, prd.receipt_id, on=date(2026, 1, 9))
    tot = {p: sum(m.qty for m in x.movements if m.type is MovementType.ISSUE and m.product == p) for p in "BC"}
    assert tot == {"B": pytest.approx(2 * prd.qty), "C": pytest.approx(prd.qty)}
    new, _ = roll_forward(x, NEXT)
    assert on_hand(new, "P", "B") == pytest.approx(200 - 2 * prd.qty)
    assert on_hand(new, "P", "C") == pytest.approx(100 - prd.qty)
    assert prd.receipt_id not in {r.id for r in new.receipts}


def test_actual_usage_replaces_the_backflush_and_bom_serves_imported_orders():
    d = base()
    lp(d, "P", "B")["on_hand"] = 200
    lp(d, "P", "C")["on_hand"] = 100
    d["receipts"] = [{"id": "WO-1", "kind": "production", "location": "P", "product": "A", "qty": 10,
                      "due_date": "2026-01-07", "source": "PV-A"}]
    d["products"].append({"id": "D", "type": "FG"})
    d["production_sources"][0]["co_products"] = [{"product": "D", "qty": 0.1}]
    x = ds(d)
    y, _ = receive(x, "WO-1", usage=[{"product": "B", "qty": 23}])
    assert [(m.type.value, m.product, m.qty) for m in y.movements] == [
        ("receipt", "A", 10), ("issue", "B", 23), ("receipt", "D", pytest.approx(1))]
    z, _ = receive(x, "WO-1")                                     # no reservations: parts from the BOM
    assert {m.product: m.qty for m in z.movements if m.type is MovementType.ISSUE} == {"B": 20, "C": 10}


def test_receive_a_purchase_goes_through_buying():
    d = network()
    d["purchasing_sources"][0]["lead_time_days"] = 1
    x, rep = firmed(d)
    buy = next(f for f in rep.firmed if f.kind == "purchase")
    y, r = receive(x, buy.receipt_id, qty=5)
    assert y.movements[-1].reference == buy.receipt_id and "still to come" in r.message
    with pytest.raises(PostingError):
        ship(x, buy.receipt_id)


def test_posting_api_round_trip():
    client = TestClient(app)
    d = base()
    lp(d, "P", "A")["on_hand"] = 900
    r = client.post("/api/actuals/post", json={"dataset": d, "action": "count",
                                               "counts": [{"location": "P", "product": "A", "qty": 880}]})
    assert r.status_code == 200 and r.json()["report"]["movements"]
    r = client.post("/api/actuals/post", json={"dataset": d, "action": "ship", "order": "NOPE"})
    assert r.status_code == 409 and "NOPE" in r.json()["detail"]


# ---- Q15: a late posting shows ------------------------------------------------------------------------------
def test_a_late_posting_is_reported_until_the_start_is_booked_again():
    d = network()
    lp(d, "W", "A")["on_hand"] = 100
    x = ds(d)
    assert not actuals_view(x).unbooked.needed                      # setup stock alone is not a late posting
    new, _ = roll_forward(x, NEXT)
    assert not actuals_view(new).unbooked.needed
    raw = new.model_dump(mode="json")
    raw["movements"].append(mv(900, "2026-01-07", "sale", "W", "A", 30))   # posted after the week was rolled
    late = ds(raw)
    u = actuals_view(late).unbooked
    assert u.needed and u.stock == 1 and u.accuracy_weeks == 1 and u.history_days == 1
    fixed, _ = roll_forward(late, NEXT)
    assert on_hand(fixed, "W", "A") == 70 and not actuals_view(fixed).unbooked.needed


# ---- Q9: a planned purchase that an open order would cover says so -------------------------------------------------
def test_planned_buy_names_the_open_order_that_arrives_too_late():
    from scp.purchasing import requisitions
    d = base(horizon=42)
    d["demand"] = [demand("P", "B", "2026-01-09", 70)]
    d["receipts"] = [{"id": "PO-00009-10", "kind": "purchase", "location": "P", "product": "B", "qty": 200,
                      "due_date": "2026-01-08", "confirmed_date": "2026-01-20", "source": "PIR-B"}]
    x = ds(d)
    plan = run_mrp(x)
    buy = next(o for o in plan.orders if o.kind == "buy" and o.product == "B")
    assert buy.open_later == ["PO-00009-10"]
    assert next(r for r in requisitions(x, plan) if r.id == buy.id).open_later == ["PO-00009-10"]


def test_rolling_keeps_history_imported_from_before_the_journal():
    """Accuracy weeks and closed orders that came with the data (before the journal began) are not re-read from a journal
    that knows nothing about them: a roll used to wipe their actuals and deliveries to zero."""
    from datetime import timedelta

    from .factory import load_example
    x = load_example("kitchenware_network")
    assert not actuals_view(x).unbooked.needed
    new, _ = roll_forward(x, x.settings.planning_start + timedelta(days=7))
    old_acc = {(a.location, a.product, a.start): a.actual for a in x.accuracy}
    assert {(a.location, a.product, a.start): a.actual for a in new.accuracy if (a.location, a.product, a.start) in old_acc} == old_acc
    old_closed = {c.id: c.delivered_qty for c in x.closed_orders}
    assert {c.id: c.delivered_qty for c in new.closed_orders if c.id in old_closed} == old_closed


def test_confirming_production_warns_when_its_parts_are_not_in_stock():
    d = base()
    lp(d, "P", "B")["on_hand"] = 5
    lp(d, "P", "C")["on_hand"] = 100
    d["receipts"] = [{"id": "WO-1", "kind": "production", "location": "P", "product": "A", "qty": 10,
                      "due_date": "2026-01-07", "source": "PV-A"}]
    _, r = receive(ds(d), "WO-1")
    assert "B at P goes to -15" in r.message and "C at" not in r.message
