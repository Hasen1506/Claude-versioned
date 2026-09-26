"""Phase E: procure-to-pay.

* Source determination: a blocked supplier or source is never planned; the source list's fixed source comes before
  priority, the quota arrangement before both; price scales price a planned purchase by its quantity.
* Supplier confirmations: planning expects a confirmed line on the confirmed date and counts no more than confirmed.
* Requisitions → purchase orders (grouped by supplier), another source per line, the approval limit.
* Send, confirm, receive (tolerances), change and cancel; the roll-forward closes lines and keeps the order link;
  the order view and the supplier scorecard read it all back.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals import roll_forward
from scp.api.app import app
from scp.plan import run_mrp
from scp.purchasing import PurchasingError, act, create_purchase_orders, purchase_orders, purchasing_view, requisitions
from scp.validate import validate

from .factory import base, demand, ds, lp


def _buying(qty: float = 40) -> dict:
    """A needs 2×B + 1×C; B and C bought from S. A second supplier T sells B too (priority 2, 5 days)."""
    d = base(horizon=42)
    d["locations"].append({"id": "T", "type": "supplier", "name": "Tessa Metals"})
    d["purchasing_sources"].append({"id": "PIR-B-T", "supplier": "T", "product": "B", "location": "P", "price": 9,
                                    "lead_time_days": 5, "priority": 2, "moq": 100})
    lp(d, "P", "B")["on_hand"] = 0
    lp(d, "P", "B")["lot_sizing"] = {"policy": "L4L"}
    lp(d, "P", "A")["on_hand"] = 0
    d["demand"] = [demand("P", "A", "2026-01-14", qty)]
    return d


def _buys(p, product: str):
    return [o for o in p.orders if o.kind == "buy" and o.product == product]


# ---- source determination -------------------------------------------------------------------------
def test_a_blocked_supplier_or_source_is_never_planned():
    d = _buying()
    assert {o.source_id for o in _buys(run_mrp(ds(d)), "B")} == {"PIR-B"}
    d["vendors"] = [{"supplier": "S", "blocked": True, "block_reason": "quality hold"}]
    d["purchasing_sources"].append({"id": "PIR-C-T", "supplier": "T", "product": "C", "location": "P", "price": 6,
                                    "lead_time_days": 2})
    assert {o.source_id for o in _buys(run_mrp(ds(d)), "B")} == {"PIR-B-T"}
    d["vendors"] = []
    d["purchasing_sources"][0]["blocked"] = True
    assert {o.source_id for o in _buys(run_mrp(ds(d)), "B")} == {"PIR-B-T"}
    d["purchasing_sources"][2]["blocked"] = True
    no = [i for i in validate(ds(d)) if i.code == "NO_SOURCE"]
    assert no and "blocked (PIR-B, PIR-B-T)" in no[0].message


def test_fixed_source_before_priority_and_quota_before_both():
    d = _buying()
    d["purchasing_sources"][2]["fixed"] = True
    assert {o.source_id for o in _buys(run_mrp(ds(d)), "B")} == {"PIR-B-T"}
    d["purchasing_sources"][0]["quota"] = 1.0
    assert {o.source_id for o in _buys(run_mrp(ds(d)), "B")} == {"PIR-B"}


def test_price_scales_price_a_purchase_by_its_quantity():
    d = _buying(qty=40)                  # 80 of B
    d["purchasing_sources"][0]["price_scales"] = [{"from_qty": 50, "price": 8}, {"from_qty": 500, "price": 6}]
    b = _buys(run_mrp(ds(d)), "B")[0]
    assert b.qty == pytest.approx(80) and b.costs["purchase"] == pytest.approx(80 * 8)
    d["demand"] = [demand("P", "A", "2026-01-14", 20)]   # 40 of B: below the first scale
    assert _buys(run_mrp(ds(d)), "B")[0].costs["purchase"] == pytest.approx(40 * 10)


# ---- confirmations in planning ---------------------------------------------------------------------
def _open_po(d: dict, qty: float = 80, due: str = "2026-01-09", **line) -> dict:
    d["purchase_orders"] = [{"id": "PO-00001", "supplier": "S", "location": "P", "order_date": "2026-01-02",
                             "sent_on": "2026-01-02"}]
    d["receipts"] = [{"id": "PO-00001-10", "kind": "purchase", "location": "P", "product": "B", "qty": qty,
                      "due_date": due, "source": "PIR-B", "po": "PO-00001", "price": 10, **line}]
    return d


def test_planning_expects_a_confirmed_line_on_its_date_and_counts_only_what_is_confirmed():
    d = _open_po(_buying())
    p = run_mrp(ds(d))
    assert not _buys(p, "B") and p.receipts[0].date == date(2026, 1, 9)
    late = _open_po(_buying(), confirmed_date="2026-01-11", confirmed_qty=80)
    p = run_mrp(ds(late))
    assert p.receipts[0].date == date(2026, 1, 11)
    assert [e.order_id for e in p.exceptions if e.code == "PO_CONFIRMED_LATE"] == ["PO-00001-10"]
    short = _open_po(_buying(), confirmed_qty=50)
    p = run_mrp(ds(short))
    assert p.receipts[0].qty == pytest.approx(50)
    assert sum(o.qty for o in _buys(p, "B")) == pytest.approx(30)      # the rest is bought again
    assert [e.qty for e in p.exceptions if e.code == "PO_CONFIRMED_SHORT"] == [pytest.approx(30)]


def test_an_unconfirmed_order_past_its_confirmation_time_is_reported():
    d = _open_po(_buying())
    d["vendors"] = [{"supplier": "S", "confirmation_required": True, "confirmation_days": 2}]
    e = [x for x in run_mrp(ds(d)).exceptions if x.code == "PO_NOT_CONFIRMED"]
    assert [x.order_id for x in e] == ["PO-00001-10"] and "2026-01-04" in e[0].message
    d["receipts"][0]["confirmed_date"] = "2026-01-15"
    assert not [x for x in run_mrp(ds(d)).exceptions if x.code == "PO_NOT_CONFIRMED"]


# ---- requisitions → purchase orders ----------------------------------------------------------------
def test_requisitions_list_every_source_with_its_terms():
    dset = ds(_buying())
    reqs = requisitions(dset, run_mrp(dset))
    b = next(r for r in reqs if r.product == "B")
    assert [c.source_id for c in b.choices] == ["PIR-B", "PIR-B-T"] and b.choices[0].assigned
    t = b.choices[1]
    assert t.qty == pytest.approx(100) and t.price == pytest.approx(9) and t.lead_time_days == 5 and not t.blocked


def test_create_orders_groups_by_supplier_and_replanning_buys_nothing_more():
    dset = ds(_buying())
    plan = run_mrp(dset)
    reqs = requisitions(dset, plan)
    new, rep = create_purchase_orders(dset, plan, [{"id": r.id} for r in reqs])
    assert rep.ok and not rep.skipped and len(rep.created) == 1
    po = rep.created[0]
    assert po.id == "PO-00001" and po.supplier == "S" and po.lines == ["PO-00001-10", "PO-00001-20"] and po.approved
    assert {r.po for r in new.receipts} == {"PO-00001"} and [h.id for h in new.purchase_orders] == ["PO-00001"]
    assert validate(new) == []
    again = run_mrp(new)
    assert not [o for o in again.orders if o.kind == "buy"]
    assert again.kpis.on_time_fill_rate == pytest.approx(plan.kpis.on_time_fill_rate)


def test_another_source_on_a_line_applies_its_minimum_and_its_lead_time():
    dset = ds(_buying())
    plan = run_mrp(dset)
    b = next(r for r in requisitions(dset, plan) if r.product == "B")
    new, rep = create_purchase_orders(dset, plan, [{"id": b.id, "source_id": "PIR-B-T"}], order_date=date(2026, 1, 20))
    po = rep.created[0]
    assert po.supplier == "T"
    line = next(r for r in new.receipts if r.po == po.id)
    assert line.qty == pytest.approx(100) and line.price == pytest.approx(9)
    assert line.due_date == date(2026, 1, 25)                # ordered on the 20th, five days
    assert any("minimum or pack size" in n for n in po.notes) and any("after it is needed" in n for n in po.notes)


def test_blocked_supplier_is_refused_when_ordering():
    dset = ds(_buying())
    plan = run_mrp(dset)
    b = next(r for r in requisitions(dset, plan) if r.product == "B")
    blocked = dset.model_copy(update={"vendors": [*dset.vendors, dset.vendor("T").model_copy(update={"blocked": True})]})
    _, rep = create_purchase_orders(blocked, plan, [{"id": b.id, "source_id": "PIR-B-T"}])
    assert "T is blocked for purchasing" in rep.skipped[b.id]


def test_an_order_above_the_approval_limit_is_approved_before_it_is_sent():
    d = _buying()
    d["purchasing"] = {"approval_limit": 500}
    dset = ds(d)
    plan = run_mrp(dset)
    new, rep = create_purchase_orders(dset, plan)
    po = rep.created[0]
    assert not po.approved and po.value > 500
    with pytest.raises(PurchasingError, match="not approved"):
        act(new, "send", po.id)
    new, _ = act(new, "approve", po.id)
    new, r = act(new, "send", po.id, on=date(2026, 1, 5))
    assert new.purchase_order_by_id[po.id].sent_on == date(2026, 1, 5) and "sent to S" in r.message
    assert purchase_orders(new)[0].status == "sent"


# ---- confirm, receive, roll, change, cancel -----------------------------------------------------------
def _ordered(**vendor) -> tuple:
    d = _buying()
    if vendor:
        d["vendors"] = [{"supplier": "S", **vendor}]
    dset = ds(d)
    new, rep = create_purchase_orders(dset, run_mrp(dset))
    new, _ = act(new, "send", rep.created[0].id)
    return new, rep.created[0].id


def test_confirm_then_receive_in_parts_then_roll_closes_the_order():
    new, pid = _ordered(confirmation_required=True, over_delivery_tolerance=0.05)
    assert purchase_orders(new)[0].status == "awaiting confirmation"
    b_line = next(r for r in new.receipts if r.product == "B")
    new, rep = act(new, "confirm", pid, lines=[{"id": b_line.id, "date": "2026-01-14"}], reference="AB-77")
    assert new.purchase_order_by_id[pid].vendor_reference == "AB-77" and "1 line" in rep.message
    new, rep = act(new, "confirm", pid)
    assert purchase_orders(new)[0].status == "confirmed"
    with pytest.raises(PurchasingError, match="over-delivery tolerance"):
        act(new, "receive", pid, lines=[{"id": b_line.id, "qty": b_line.qty * 1.1}])
    new, rep = act(new, "receive", pid, lines=[{"id": b_line.id, "qty": 30}], on=date(2026, 1, 8), note="DN-1")
    assert len(rep.movements) == 1 and "still to come" in rep.message
    view = purchase_orders(new)[0]
    assert view.status == "partly received"
    assert next(x for x in view.lines if x.id == b_line.id).received == pytest.approx(30)
    new, rep = act(new, "receive", pid, on=date(2026, 1, 9))        # everything still open
    assert "complete" in rep.message
    rolled, _ = roll_forward(new, date(2026, 1, 12))
    assert not [r for r in rolled.receipts if r.po == pid]
    closed = [c for c in rolled.closed_orders if c.po == pid]
    assert len(closed) == 2 and all(c.counterparty == "S" for c in closed)
    view = purchase_orders(rolled)[0]
    assert view.status == "closed" and all(x.closed for x in view.lines)
    s = next(v for v in purchasing_view(rolled, run_mrp(rolled)).vendors if v.supplier == "S")
    assert s.closed_lines == 2 and s.on_time == pytest.approx(1.0) and s.in_full == pytest.approx(1.0)


def test_under_delivery_tolerance_and_a_short_confirmation_close_the_line():
    new, pid = _ordered(under_delivery_tolerance=0.1)
    b_line = next(r for r in new.receipts if r.product == "B")
    new, rep = act(new, "receive", pid, lines=[{"id": b_line.id, "qty": b_line.qty * 0.95}])
    assert "short" in rep.message and new.movements[-1].final
    rolled, _ = roll_forward(new, date(2026, 1, 6))
    assert b_line.id not in {r.id for r in rolled.receipts}
    # a supplier who confirmed less: receiving what they confirmed closes the line
    new, pid = _ordered()
    c_line = next(r for r in new.receipts if r.product == "C")
    new, _ = act(new, "confirm", pid, lines=[{"id": c_line.id, "qty": 10}])
    new, _ = act(new, "receive", pid, lines=[{"id": c_line.id, "qty": 10}])
    rolled, _ = roll_forward(new, date(2026, 1, 6))
    assert c_line.id not in {r.id for r in rolled.receipts}


def test_change_needs_a_new_confirmation_and_cannot_go_below_what_is_received():
    new, pid = _ordered(confirmation_required=True)
    new, _ = act(new, "confirm", pid)
    b_line = next(r for r in new.receipts if r.product == "B")
    new, _ = act(new, "change", pid, lines=[{"id": b_line.id, "qty": 120}])
    line = next(r for r in new.receipts if r.id == b_line.id)
    assert line.qty == pytest.approx(120) and line.confirmed_date is None and line.confirmed_qty is None
    new, _ = act(new, "receive", pid, lines=[{"id": b_line.id, "qty": 50}])
    with pytest.raises(PurchasingError, match="already received"):
        act(new, "change", pid, lines=[{"id": b_line.id, "qty": 40}])
    with pytest.raises(PurchasingError, match="already received"):
        act(new, "cancel", pid, lines=[{"id": b_line.id}])


def test_cancel_removes_lines_and_an_empty_order():
    new, pid = _ordered()
    new, rep = act(new, "cancel", pid)
    assert not [r for r in new.receipts if r.po == pid] and not new.purchase_orders and "removed" in rep.message
    assert [o for o in run_mrp(new).orders if o.kind == "buy"]     # needed again


def test_an_open_purchase_without_an_order_document_is_its_own_order():
    d = _buying()
    d["receipts"] = [{"id": "PO-OLD", "kind": "purchase", "location": "P", "product": "B", "qty": 80,
                      "due_date": "2026-01-02", "source": "PIR-B"}]
    dset = ds(d)
    view = purchase_orders(dset)
    assert [(p.id, p.header, p.supplier, p.status) for p in view] == [("PO-OLD", False, "S", "sent")]
    assert view[0].lines[0].status == "overdue" and view[0].lines[0].days_late == 3
    new, _ = act(dset, "receive", "PO-OLD")
    assert new.movements[-1].reference == "PO-OLD" and new.movements[-1].counterparty == "S"


# ---- API --------------------------------------------------------------------------------------------
def test_purchasing_api_round_trip():
    client = TestClient(app)
    d = _buying()
    v = client.post("/api/purchasing", json=d).json()
    assert v["ok"] and v["totals"]["requisitions"] == 2 and v["totals"]["due_now"] == 2
    r = client.post("/api/purchasing/create", json={"dataset": d}).json()
    assert [p["id"] for p in r["report"]["created"]] == ["PO-00001"]
    d2 = r["dataset"]
    r = client.post("/api/purchasing/act", json={"dataset": d2, "action": "approve", "po": "NOPE"})
    assert r.status_code == 409 and "no order document" in r.json()["detail"]
    r = client.post("/api/purchasing/act", json={"dataset": d2, "action": "receive", "po": "PO-00001",
                                                 "date": "2026-01-07", "note": "DN-9"}).json()
    assert len(r["report"]["movements"]) == 2 and r["dataset"]["movements"][0]["note"] == "DN-9"


def test_firming_a_purchase_gives_it_an_order_document():
    from scp.actuals import firm_orders
    d = _buying()
    d["purchasing"] = {"approval_limit": 500}
    dset = ds(d)
    new, rep = firm_orders(dset, run_mrp(dset), within_days=30)
    buys = [f for f in rep.firmed if f.kind == "purchase"]
    assert buys and {h.id for h in new.purchase_orders} == {f.receipt_id for f in buys}
    b = next(f for f in buys if f.product == "B")
    assert new.purchase_order_by_id[b.receipt_id].approved is False           # 80 × 10 = 800 > 500
    line = next(r for r in new.receipts if r.id == b.receipt_id)
    assert line.po == b.receipt_id and line.price == pytest.approx(10)
    views = {p.id: p for p in purchase_orders(new)}
    assert views[b.receipt_id].header and views[b.receipt_id].status == "awaiting approval"
    assert validate(new) == []
