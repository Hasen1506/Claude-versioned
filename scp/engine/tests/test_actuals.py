"""P7 orders & actuals: stock is the sum of goods movements, firming keeps the plan, the roll-forward is
idempotent, and the elapsed weeks produce a forecast-accuracy report."""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from scp.actuals import accuracy_report, actuals_view, firm_orders, roll_forward, stock
from scp.model import Dataset, GoodsMovement
from scp.plan import run_mrp
from scp.validate import validate

from .factory import base, demand, ds


def mv(i, day, typ, loc, prod, qty, **kw) -> dict:
    return {"id": f"GM{i}", "date": day, "type": typ, "location": loc, "product": prod, "qty": qty, **kw}


def net() -> dict:
    """Plant P with a customer K served over a 1-day lane; weekly forecast at K and one sales order."""
    d = base(horizon=56)
    d["locations"].append({"id": "K", "type": "customer"})
    d["lanes"] = [{"id": "PK", "origin": "P", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["demand"] = [demand("K", "A", "2026-01-05", 70, period_days=7), demand("K", "A", "2026-01-12", 70, period_days=7),
                   demand("K", "A", "2026-01-19", 70, period_days=7),
                   demand("K", "A", "2026-01-09", 40, "sales_order", id="SO1")]
    d["receipts"] = [{"id": "PO-00001", "kind": "purchase", "location": "P", "product": "B", "qty": 100,
                      "due_date": "2026-01-07", "source": "PIR-B"}]
    d["confirmations"] = [{"order": "SO1", "ship_from": "P", "ship_date": "2026-01-08", "date": "2026-01-09", "qty": 25},
                          {"order": "SO1", "ship_from": "P", "ship_date": "2026-01-12", "date": "2026-01-13", "qty": 15}]
    return d


# ---- stock = Σ movements --------------------------------------------------------------------------
def test_stock_is_the_sum_of_movements_for_random_journals():
    rnd = random.Random(7)
    types = ["opening", "receipt", "issue", "sale", "transfer_out", "scrap", "adjustment"]
    for _ in range(40):
        d = base(horizon=56)
        movs, expect = [], {}
        for i in range(rnd.randint(1, 30)):
            t = rnd.choice(types)
            prod = rnd.choice(["A", "B", "C"])
            q = round(rnd.uniform(1, 50), 2) * (rnd.choice([-1, 1]) if t == "adjustment" else 1)
            day = (date(2025, 12, 1) + timedelta(days=rnd.randint(0, 45))).isoformat()
            movs.append(mv(i, day, t, "P", prod, q))
            if day < "2026-01-20":
                sign = 1 if t in ("opening", "receipt", "adjustment") else -1
                expect[prod] = expect.get(prod, 0.0) + sign * abs(q) * (1 if t != "adjustment" else (1 if q > 0 else -1))
        d["movements"] = movs
        x = ds(d)
        got = stock([GoodsMovement.model_validate(m) for m in movs if m["date"] < "2026-01-20"])
        assert {p: pytest.approx(v) for (_, p), v in got.items()} == expect
        new, rep = roll_forward(x, date(2026, 1, 20))
        for p, v in expect.items():
            assert next(y for y in new.location_products if y.product == p).on_hand == pytest.approx(max(0.0, v))
        assert rep.ok and not [i for i in validate(new) if i.code == "STOCK_NOT_SYNCED"]


def test_stock_view_reconciles_and_flags_negative_stock():
    d = net()
    d["movements"] = [mv(1, "2026-01-01", "opening", "P", "A", 10), mv(2, "2026-01-02", "sale", "P", "A", 14,
                                                                        counterparty="K")]
    v = actuals_view(ds(d))
    row = next(r for r in v.stock if (r.location, r.product) == ("P", "A"))
    assert row.movement_stock == -4 and row.difference == -10 and row.negative_on == date(2026, 1, 2)
    assert {i.code for i in validate(ds(d))} >= {"STOCK_NOT_SYNCED", "NEGATIVE_STOCK"}


# ---- roll-forward -------------------------------------------------------------------------------------
def _journal() -> list[dict]:
    return [
        mv(1, "2026-01-04", "opening", "P", "A", 10),
        mv(2, "2026-01-04", "opening", "P", "B", 30),
        mv(3, "2026-01-06", "receipt", "P", "B", 60, reference="PO-00001", counterparty="S"),
        mv(4, "2026-01-08", "sale", "P", "A", 25, reference="SO1", counterparty="K"),
        mv(5, "2026-01-07", "sale", "P", "A", 5, counterparty="K"),          # a walk-in sale, no order
        mv(6, "2026-01-10", "adjustment", "P", "B", -2, note="cycle count"),
    ]


def test_roll_forward_derives_stock_reduces_orders_and_trims_confirmations():
    d = net()
    d["movements"] = _journal()
    new, rep = roll_forward(ds(d), date(2026, 1, 12))
    assert rep.ok and new.settings.planning_start == date(2026, 1, 12)
    on = {(x.location, x.product): x.on_hand for x in new.location_products}
    assert on[("P", "A")] == 0 and on[("P", "B")] == 88                   # 10 − 25 − 5 → 0 (warned); 30 + 60 − 2
    assert any("Negative stock" in w for w in rep.warnings)
    po = next(r for r in new.receipts if r.id == "PO-00001")
    assert (po.qty, po.ordered_qty) == (40, 100)
    so = next(x for x in new.demand if x.id == "SO1")
    assert (so.qty, so.ordered_qty) == (15, 40)
    assert [(c.ship_date.isoformat(), c.qty) for c in new.confirmations] == [("2026-01-12", 15)]   # 25 delivered off the first line
    # forecast: week 1 elapsed and dropped, week 2 starts on the new start, week 3 untouched
    fc = sorted((x.date.isoformat(), x.qty, x.period_days) for x in new.demand if x.kind.value == "forecast")
    assert fc == [("2026-01-12", 70, 7), ("2026-01-19", 70, 7)] and rep.forecast_dropped == 70
    # sales became history at the customer, and the elapsed week was logged against the forecast
    assert sorted((h.location, h.date.isoformat(), h.qty) for h in new.history) == [("K", "2026-01-07", 5), ("K", "2026-01-08", 25)]
    assert [(a.start.isoformat(), a.end.isoformat(), a.forecast, a.actual) for a in new.accuracy] == [
        ("2026-01-05", "2026-01-12", 70, 30)]
    assert not [i for i in validate(new) if i.code == "STOCK_NOT_SYNCED"]


def test_roll_forward_is_idempotent():
    d = net()
    d["movements"] = _journal()
    once, _ = roll_forward(ds(d), date(2026, 1, 12))
    twice, rep = roll_forward(once, date(2026, 1, 12))
    assert twice.model_dump() == once.model_dump()
    assert rep.orders == [] or all(o.open_before == o.open_after for o in rep.orders)


def test_completion_closes_orders_with_delivery_performance():
    d = net()
    d["movements"] = _journal() + [
        mv(7, "2026-01-09", "receipt", "P", "B", 39, reference="PO-00001"),     # 99 of 100: within 2 % tolerance
        mv(8, "2026-01-11", "sale", "P", "A", 10, reference="SO1", counterparty="K", final=True),   # short, final
    ]
    new, rep = roll_forward(ds(d), date(2026, 1, 12))
    assert not new.receipts and not [x for x in new.demand if x.id == "SO1"] and not new.confirmations
    c = {x.id: x for x in new.closed_orders}
    po, so = c["PO-00001"], c["SO1"]
    assert (po.kind, po.counterparty, po.ordered_qty, po.delivered_qty, po.last_delivery) == (
        "purchase", "S", 100, 99, date(2026, 1, 9))
    assert (so.kind, so.ordered_qty, so.delivered_qty, so.due_date, so.promised_date, so.last_delivery) == (
        "sales", 40, 35, date(2026, 1, 9), date(2026, 1, 13), date(2026, 1, 11))


def test_accuracy_report_over_weeks():
    d = net()
    d["movements"] = [mv(1, "2026-01-06", "sale", "P", "A", 60, counterparty="K"),
                      mv(2, "2026-01-13", "sale", "P", "A", 90, counterparty="K")]
    a, _ = roll_forward(ds(d), date(2026, 1, 12))
    b, _ = roll_forward(a, date(2026, 1, 19))
    r = accuracy_report(b.accuracy)
    assert r.periods == 2 and len(r.series) == 1
    s = r.series[0]
    assert (s.forecast, s.actual, s.abs_error) == (140, 150, 30)          # |70 − 60| + |70 − 90|
    assert s.wmape == pytest.approx(30 / 150) and s.bias == pytest.approx(-10 / 150)
    assert r.accuracy == pytest.approx(1 - 30 / 150)


def test_cannot_roll_back():
    new, rep = roll_forward(ds(net()), date(2026, 1, 1))
    assert not rep.ok and new.settings.planning_start == date(2026, 1, 5)


# ---- firming ----------------------------------------------------------------------------------------
def _plannable() -> dict:
    d = base(horizon=42)
    d["demand"] = [demand("P", "A", f"2026-01-{day:02d}", 20) for day in (14, 21, 28)]
    return d


def test_firming_everything_reproduces_the_plan_with_no_new_orders():
    x = ds(_plannable())
    plan = run_mrp(x)
    assert plan.ok and plan.orders and all(not o.start_in_past for o in plan.orders)
    firmed, rep = firm_orders(x, plan, within_days=365)
    assert rep.ok and len(rep.firmed) == len(plan.orders)
    make = next(f for f in rep.firmed if f.kind == "production")
    assert make.receipt_id.startswith("PRD-") and make.reservations == 2
    again = run_mrp(firmed)
    assert again.orders == []
    proj = lambda p: {(n.location, n.product): [round(b.projected_on_hand, 6) for b in n.buckets] for n in p.nodes}  # noqa: E731
    assert proj(again) == proj(plan)
    assert again.kpis.on_time_fill_rate == pytest.approx(plan.kpis.on_time_fill_rate)


def test_firm_zone_and_explicit_ids():
    x = ds(_plannable())
    plan = run_mrp(x)
    zone = x.settings.planning_start + timedelta(days=x.execution.firm_zone_days)
    _, rep = firm_orders(x, plan)
    assert {f.planned_id for f in rep.firmed} == {o.id for o in plan.orders if o.start_date < zone}
    _, rep = firm_orders(x, plan, ids=[plan.orders[-1].id, "MO9999"])
    assert [f.planned_id for f in rep.firmed] == [plan.orders[-1].id] and "MO9999" in rep.skipped


def test_component_issues_draw_down_reservations():
    x = ds(_plannable())
    firmed, rep = firm_orders(x, run_mrp(x), within_days=365)
    prd = next(f for f in rep.firmed if f.kind == "production")
    rc = next(r for r in firmed.receipts if r.id == prd.receipt_id)
    need_b = next(rv.qty for rv in rc.reservations if rv.product == "B")
    d = firmed.model_dump(mode="json")
    d["movements"] = [mv(1, "2026-01-04", "opening", "P", p, q) for p, q in (("A", 10), ("B", 30), ("C", 0.001))] + [
        mv(2, "2026-01-05", "issue", "P", "B", need_b / 2, reference=prd.receipt_id)]
    new, _ = roll_forward(Dataset.model_validate(d), date(2026, 1, 6))
    rc2 = next(r for r in new.receipts if r.id == prd.receipt_id)
    b = next(rv for rv in rc2.reservations if rv.product == "B")
    assert (b.qty, b.required_qty) == (pytest.approx(need_b / 2), need_b)
    view = actuals_view(new)
    assert next(o for o in view.open_orders if o.id == prd.receipt_id).reservations_open == pytest.approx(
        need_b / 2 + next(rv.qty for rv in rc2.reservations if rv.product == "C"))


def test_transfer_in_transit():
    d = net()
    d["locations"].append({"id": "D", "type": "dc"})
    d["lanes"].append({"id": "PD", "origin": "P", "destination": "D", "modes": [{"transit_days": 3}]})
    d["receipts"].append({"id": "STO-00001", "kind": "transfer", "location": "D", "product": "A", "qty": 20,
                          "due_date": "2026-01-09", "source": "PD",
                          "reservations": [{"location": "P", "product": "A", "date": "2026-01-06", "qty": 20}]})
    d["movements"] = [mv(1, "2026-01-06", "transfer_out", "P", "A", 20, reference="STO-00001")]
    v = actuals_view(ds(d), date(2026, 1, 8))
    sto = next(o for o in v.open_orders if o.id == "STO-00001")
    assert (sto.in_transit, sto.reservations_open, sto.counterparty) == (20, 0, "P")
    # MRP reserved the goods at P while the STO was open and unshipped
    plan = run_mrp(ds(net() | {"receipts": d["receipts"], "lanes": d["lanes"], "locations": d["locations"]}))
    assert any(r.id == "RV:STO-00001:P:A" and r.kind == "transfer" for r in plan.requirements)


# ---- example -------------------------------------------------------------------------------------------
def test_example_journal_rolls_forward_a_week():
    from .factory import load_example
    ex = load_example("kitchenware_network")
    assert all(r.difference == 0 for r in actuals_view(ex).stock)            # opening balances = on-hand
    new, rep = roll_forward(ex, date(2026, 10, 5))
    assert rep.ok and not rep.warnings
    before = {c.id for c in ex.closed_orders}                                 # the example's eight weeks of history
    closed = {c.id: c for c in new.closed_orders if c.id not in before}
    assert set(closed) == {"SO-88121", "MO-100455", "STO-2201"}
    assert next(x for x in new.demand if x.id == "SO-88190").qty == 500     # 700 of 1 200 delivered
    r = accuracy_report(new.accuracy[len(ex.accuracy):])
    assert r.periods == 1 and r.accuracy is not None and 0 < r.accuracy < 1
    assert run_mrp(new).ok
    again, _ = roll_forward(new, date(2026, 10, 5))
    assert again.model_dump() == new.model_dump()
