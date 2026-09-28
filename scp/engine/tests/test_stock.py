"""Phase O: stock you can trace. Batches with an expiry date issued first expiring first out (R15), stock in quality
inspection and blocked, expiry in the plan, short receipts that name the orders they leave short (R16), the company's
rule for stock below zero (R17), reversal, physical inventory with a freeze, serial numbers and the cold chain (R30)."""
from __future__ import annotations

from datetime import date

import pytest

from scp.actuals import PostingError, actuals_view, post, roll_forward
from scp.actuals.stock import open_orders, stock_rows
from scp.model import MovementType, NegativeStock, StockType
from scp.plan import run_mrp
from scp.validate import validate

from .factory import base, demand, ds, lp
from .test_companies import client, example


def plant(**b_extra) -> dict:
    """Plant P with a DC fed by a 1-day lane; B bought from S, batch-managed (10 days), nothing in stock; two firm
    production orders of A draw on B."""
    d = base(horizon=56)
    d["locations"].append({"id": "DC", "type": "dc"})
    d["lanes"] = [{"id": "P-DC", "origin": "P", "destination": "DC", "modes": [{"transit_days": 1}]}]
    next(p for p in d["products"] if p["id"] == "B").update({"shelf_life_days": 10, **b_extra})
    lp(d, "P", "B")["on_hand"] = 0
    lp(d, "DC", "B")
    d["receipts"] = [
        {"id": "PO-00001", "kind": "purchase", "location": "P", "product": "B", "qty": 100, "due_date": "2026-01-05",
         "source": "PIR-B"},
        {"id": "MO-1", "kind": "production", "location": "P", "product": "A", "qty": 30, "due_date": "2026-01-08",
         "start_date": "2026-01-06", "source": "PV-A",
         "reservations": [{"location": "P", "product": "B", "date": "2026-01-06", "qty": 60}]},
        {"id": "MO-2", "kind": "production", "location": "P", "product": "A", "qty": 30, "due_date": "2026-01-10",
         "start_date": "2026-01-08", "source": "PV-A",
         "reservations": [{"location": "P", "product": "B", "date": "2026-01-08", "qty": 60}]},
    ]
    return d


def movs(x, ref: str, typ: MovementType | None = None):
    return [m for m in x.movements if m.reference == ref and (typ is None or m.type is typ)]


# ---- batches, first expiring first out (R15) -------------------------------------------------------------
def test_a_receipt_makes_a_batch_that_expires_after_the_shelf_life_and_issues_take_the_first_expiring():
    x = ds(plant())
    x, rep = post(x, "receive", order="PO-00001", qty=60, on=date(2026, 1, 2))
    b1 = x.batches[-1]
    assert b1.id == "260102-1" and b1.expires_on == date(2026, 1, 12) and "batch 260102-1" in rep.message
    assert rep.doc == "MD-00001" and all(m.doc == "MD-00001" for m in x.movements)
    # a second delivery with the supplier's batch expiring sooner
    x, _ = post(x, "receive", order="PO-00001", qty=40, on=date(2026, 1, 4),
                lot={"batch": "S-77", "expires_on": date(2026, 1, 9), "supplier_batch": "77"})
    assert x.batches[-1].id == "S-77" and x.batches[-1].supplier_batch == "77"
    # MO-1 made: its 60 of B come from S-77 first (it expires first), the rest from 260102-1
    x, rep = post(x, "receive", order="MO-1", on=date(2026, 1, 6))
    issued = [(m.batch, m.qty) for m in movs(x, "MO-1", MovementType.ISSUE)]
    assert issued == [("S-77", 40), ("260102-1", 20)]
    row = next(r for r in stock_rows(x, date(2026, 1, 7)) if (r.location, r.product) == ("P", "B"))
    assert [(lot.batch, lot.qty) for lot in row.lots] == [("260102-1", 40)]
    assert row.planning_stock == 40 and row.unrestricted == 40


def test_a_transfer_ships_the_first_expiring_batch_and_arrives_in_it():
    d = plant()
    d["receipts"].append({"id": "TO-1", "kind": "transfer", "location": "DC", "product": "B", "qty": 25,
                          "due_date": "2026-01-07", "source": "P-DC",
                          "reservations": [{"location": "P", "product": "B", "date": "2026-01-06", "qty": 25}]})
    x = ds(d)
    x, _ = post(x, "receive", order="PO-00001", qty=50, on=date(2026, 1, 3), lot={"batch": "OLD", "expires_on": date(2026, 1, 20)})
    x, _ = post(x, "receive", order="PO-00001", qty=50, on=date(2026, 1, 4), lot={"batch": "NEW", "expires_on": date(2026, 1, 30)})
    x, rep = post(x, "ship", order="TO-1", on=date(2026, 1, 5))
    assert [(m.batch, m.qty) for m in movs(x, "TO-1", MovementType.TRANSFER_OUT)] == [("OLD", 25)]
    row = next(r for r in stock_rows(x, date(2026, 1, 6)) if (r.location, r.product) == ("DC", "B"))
    assert row.in_transit == 25                     # in transit belongs to the receiving place
    x, _ = post(x, "receive", order="TO-1", on=date(2026, 1, 6))
    assert [(m.batch, m.qty) for m in movs(x, "TO-1", MovementType.RECEIPT)] == [("OLD", 25)]
    row = next(r for r in stock_rows(x, date(2026, 1, 7)) if (r.location, r.product) == ("DC", "B"))
    assert row.in_transit == 0 and [(lot.batch, lot.qty) for lot in row.lots] == [("OLD", 25)]


def test_stock_that_will_expire_unused_is_a_requirement_in_the_plan():
    d = plant()
    d["receipts"] = []
    d["movements"] = [{"id": "GM-00001", "date": "2026-01-02", "type": "receipt", "location": "P", "product": "B",
                       "qty": 80, "batch": "B1"}]
    d["batches"] = [{"product": "B", "id": "B1", "expires_on": "2026-01-12"}]
    lp(d, "P", "B")["on_hand"] = 80
    # 30 of A need 60 of B before B1 expires; the other 20 expire unused on the 12th, gone on the 13th
    d["demand"] = [demand("P", "A", "2026-01-09", 40)]
    plan = run_mrp(ds(d))
    exp = [r for r in plan.requirements if r.kind == "expiry"]
    assert len(exp) == 1 and exp[0].date == date(2026, 1, 13)
    assert exp[0].qty == pytest.approx(80 - 60)
    assert any(e.code == "STOCK_EXPIRES" and e.product == "B" for e in plan.exceptions)
    node = next(n for n in plan.nodes if (n.location, n.product) == ("P", "B"))
    assert sum(b.expiring for b in node.buckets) == pytest.approx(20)
    # every unit used before it expires: nothing is counted as lost
    d["demand"] = [demand("P", "A", "2026-01-09", 50)]
    assert not [r for r in run_mrp(ds(d)).requirements if r.kind == "expiry"]


def test_the_roll_no_longer_counts_an_expired_batch_and_scrapping_it_settles_it():
    d = plant()
    d["receipts"] = []
    d["movements"] = [{"id": "GM-00001", "date": "2026-01-02", "type": "receipt", "location": "P", "product": "B",
                       "qty": 30, "batch": "B1"},
                      {"id": "GM-00002", "date": "2026-01-03", "type": "receipt", "location": "P", "product": "B",
                       "qty": 20, "batch": "B2"}]
    d["batches"] = [{"product": "B", "id": "B1", "expires_on": "2026-01-08"},
                    {"product": "B", "id": "B2", "expires_on": "2026-02-08"}]
    lp(d, "P", "B")["on_hand"] = 50
    new, rep = roll_forward(ds(d), date(2026, 1, 12))
    assert next(x for x in new.location_products if (x.location, x.product) == ("P", "B")).on_hand == 20
    assert any("expired" in w and "B1" in w for w in rep.warnings)
    assert "STOCK_EXPIRED" in {i.code for i in validate(new)}
    new, rep = post(new, "scrap_expired", location="P", product="B")
    assert [(m.type, m.batch, m.qty) for m in new.movements[-1:]] == [(MovementType.SCRAP, "B1", 30)]
    new, _ = roll_forward(new, date(2026, 1, 12))
    assert "STOCK_EXPIRED" not in {i.code for i in validate(new)}
    assert not [i for i in validate(new) if i.code == "STOCK_NOT_SYNCED"]


# ---- stock types ---------------------------------------------------------------------------------------
def test_inspected_receipts_wait_in_quality_and_blocked_stock_is_not_planned():
    d = plant(inspect_on_receipt=True)
    x = ds(d)
    x, rep = post(x, "receive", order="PO-00001", on=date(2026, 1, 2))
    assert "quality inspection" in rep.message
    assert all(m.stock_type is StockType.QUALITY for m in movs(x, "PO-00001"))
    row = next(r for r in stock_rows(x, date(2026, 1, 5)) if (r.location, r.product) == ("P", "B"))
    assert row.quality == 100 and row.unrestricted == 0 and row.planning_stock == 100      # counted by default (SAP)
    strict = x.model_copy(update={"execution": x.execution.model_copy(update={"quality_in_planning": False})})
    assert next(r for r in stock_rows(strict, date(2026, 1, 5)) if r.product == "B" and r.location == "P").planning_stock == 0
    # an issue cannot take stock still in inspection: it would go below zero
    strict = strict.model_copy(update={"execution": strict.execution.model_copy(update={"negative_stock": NegativeStock.REFUSE})})
    with pytest.raises(PostingError, match="not enough in stock"):
        post(strict, "receive", order="MO-1", on=date(2026, 1, 6))
    # released 70, 30 blocked: planning counts the 70
    x, rep = post(x, "move", location="P", product="B", qty=70, lot={"stock_type": StockType.QUALITY},
                  to_type=StockType.UNRESTRICTED, on=date(2026, 1, 3))
    assert "released" in rep.message
    x, _ = post(x, "move", location="P", product="B", lot={"stock_type": StockType.QUALITY},
                to_type=StockType.BLOCKED, on=date(2026, 1, 3))
    row = next(r for r in stock_rows(x, date(2026, 1, 5)) if (r.location, r.product) == ("P", "B"))
    assert (row.unrestricted, row.quality, row.blocked, row.planning_stock) == (70, 0, 30, 70)
    new, _ = roll_forward(x, date(2026, 1, 5))
    assert next(y for y in new.location_products if (y.location, y.product) == ("P", "B")).on_hand == 70
    with pytest.raises(PostingError, match="only 30"):
        post(x, "move", location="P", product="B", qty=31, lot={"stock_type": StockType.BLOCKED},
             to_type=StockType.UNRESTRICTED)


# ---- short receipts (R16) --------------------------------------------------------------------------------
def test_a_short_receipt_names_the_orders_it_leaves_short_and_they_can_be_shortened():
    x = ds(plant())
    x, rep = post(x, "receive", order="PO-00001", qty=85, on=date(2026, 1, 4), final=True)
    assert "closed" in rep.message
    # 85 in stock: MO-1 (starts first) gets its 60, MO-2 only 25 of 60
    assert [(s.order, s.part, s.needs, s.available) for s in rep.short_orders] == [("MO-2", "B", 60, 25)]
    s = rep.short_orders[0]
    assert s.can_make == 12 and "MO-2" in rep.message                           # 30 × 25/60 = 12.5 → 12 whole units
    x, rep = post(x, "shorten", order="MO-2", qty=s.can_make)
    mo2 = next(r for r in x.receipts if r.id == "MO-2")
    assert mo2.qty == 12 and mo2.reservations[0].qty == pytest.approx(24)
    assert not post(x, "receive", order="MO-1", on=date(2026, 1, 6))[1].short_orders
    with pytest.raises(PostingError, match="smaller"):
        post(x, "shorten", order="MO-2", qty=40)


# ---- stock below zero (R17) ---------------------------------------------------------------------------------
def test_the_company_decides_what_stock_below_zero_does():
    d = plant()
    x = ds(d)
    x, _ = post(x, "receive", order="PO-00001", qty=40, on=date(2026, 1, 4))
    # allow (the default): posted, and the message asks for a count
    y, rep = post(x, "receive", order="MO-1", on=date(2026, 1, 6))
    assert "goes to -20" in rep.message and "count" in rep.message
    # refuse: the posting is refused and nothing changes
    no = x.model_copy(update={"execution": x.execution.model_copy(update={"negative_stock": NegativeStock.REFUSE})})
    with pytest.raises(PostingError, match="does not allow stock below zero"):
        post(no, "receive", order="MO-1", on=date(2026, 1, 6))
    # count as found: the roll counts the 20 as found, and the journal and the plan agree without a count
    found = y.model_copy(update={"execution": y.execution.model_copy(update={"negative_stock": NegativeStock.FOUND})})
    new, rep = roll_forward(found, date(2026, 1, 12))
    adj = [m for m in new.movements if m.type is MovementType.ADJUSTMENT]
    assert [(m.product, m.qty, m.date) for m in adj] == [("B", 20, date(2026, 1, 11))]
    assert any("counted as found" in w for w in rep.warnings)
    codes = {i.code for i in validate(new)}
    assert "NEGATIVE_STOCK" not in codes and "STOCK_NOT_SYNCED" not in codes
    again, _ = roll_forward(new, date(2026, 1, 12))
    assert len(again.movements) == len(new.movements)                           # the roll stays idempotent


# ---- reversal ---------------------------------------------------------------------------------------------
def test_a_reversal_takes_a_whole_posting_back():
    x = ds(plant())
    x, _ = post(x, "receive", order="PO-00001", qty=100, on=date(2026, 1, 4))
    x, rep = post(x, "receive", order="MO-1", on=date(2026, 1, 6))
    posted = rep.movements
    assert len(posted) == 2                                                     # A made, B issued
    x, rep = post(x, "reverse", movement=posted[1])
    back = x.movements[-2:]
    assert sorted(m.reversal_of for m in back) == sorted(posted) and rep.doc == "MD-00003"
    row = {r.id: r for r in open_orders(x, date(2026, 1, 7))}["MO-1"]
    assert row.delivered == 0 and row.open == 30 and row.reservations_open == 60
    b = next(r for r in stock_rows(x, date(2026, 1, 7)) if (r.location, r.product) == ("P", "B"))
    assert b.movement_stock == 100
    with pytest.raises(PostingError, match="already reversed"):
        post(x, "reverse", movement=posted[0])
    with pytest.raises(PostingError, match="itself a reversal"):
        post(x, "reverse", movement=back[0].id)
    new, _ = roll_forward(x, date(2026, 1, 8))
    assert next(r for r in new.receipts if r.id == "MO-1").qty == 30            # still open in full


# ---- physical inventory with a freeze -----------------------------------------------------------------------
def test_a_physical_inventory_freezes_the_book_blocks_postings_and_posts_the_difference():
    x = ds(plant())
    x, _ = post(x, "receive", order="PO-00001", qty=100, on=date(2026, 1, 2), lot={"batch": "L1"})
    x, rep = post(x, "count_doc", nodes=[("P", "B")], on=date(2026, 1, 4))
    doc = x.inventory_docs[-1]
    assert rep.doc == doc.id == "PI-00001" and [(i.batch, i.book_qty) for i in doc.items] == [("L1", 100)]
    assert next(r for r in stock_rows(x, date(2026, 1, 5)) if r.product == "B" and r.location == "P").counting == "PI-00001"
    with pytest.raises(PostingError, match="being counted"):
        post(x, "receive", order="MO-1", on=date(2026, 1, 6))
    with pytest.raises(PostingError, match="not counted yet"):
        post(x, "count_post", doc="PI-00001")
    x, _ = post(x, "count_enter", doc="PI-00001", counts=[{"location": "P", "product": "B", "batch": "L1", "qty": 96},
                                                         {"location": "P", "product": "B", "batch": "L9", "qty": 3}])
    x, rep = post(x, "count_post", doc="PI-00001")
    diffs = sorted((m.batch, m.qty) for m in x.movements if m.type is MovementType.ADJUSTMENT)
    assert diffs == [("L1", -4), ("L9", 3)] and all(m.date == date(2026, 1, 4) for m in x.movements[-2:])
    assert x.inventory_docs[-1].status == "posted" and "planning's stock follows" in rep.message
    assert next(y for y in x.location_products if (y.location, y.product) == ("P", "B")).on_hand == 99
    x, _ = post(x, "receive", order="MO-1", on=date(2026, 1, 6))                  # postings are open again
    x, _ = post(x, "count_doc", nodes=[("P", "B")], on=date(2026, 1, 7))
    x, rep = post(x, "count_cancel", doc="PI-00002")
    assert x.inventory_docs[-1].status == "cancelled"


# ---- serial numbers --------------------------------------------------------------------------------------------
def test_serial_numbers_are_given_at_receipt_and_leave_first_in_first_out():
    d = plant()
    next(p for p in d["products"] if p["id"] == "A").update({"serial_numbers": True})
    d["demand"] = [demand("DC", "A", "2026-01-12", 3, "sales_order", id="SO-1")]
    d["lanes"].append({"id": "P-DC-A", "origin": "P", "destination": "DC", "products": ["A"], "modes": [{"transit_days": 1}]})
    lp(d, "P", "A")["on_hand"] = 0
    x = ds(d)
    x, _ = post(x, "receive", order="PO-00001", on=date(2026, 1, 4))
    x, _ = post(x, "receive", order="MO-1", qty=5, on=date(2026, 1, 6))
    made = next(m for m in movs(x, "MO-1", MovementType.RECEIPT))
    assert made.serials == [f"A-{i:06d}" for i in range(1, 6)]
    x, _ = post(x, "deliver", order="SO-1", on=date(2026, 1, 8), ship_from="P")
    sold = next(m for m in x.movements if m.type is MovementType.SALE)
    assert sold.serials == ["A-000001", "A-000002", "A-000003"]
    row = next(r for r in stock_rows(x, date(2026, 1, 9)) if (r.location, r.product) == ("P", "A"))
    assert row.serials == ["A-000004", "A-000005"]
    with pytest.raises(PostingError, match="give 2 serial numbers"):
        post(x, "receive", order="MO-1", qty=2, on=date(2026, 1, 7), lot={"serials": ["X-1"]})


# ---- the cold chain (R30) --------------------------------------------------------------------------------------
def test_a_chilled_product_on_a_route_without_refrigeration_is_flagged():
    d = plant(cold_chain=True)
    d["location_products"].append({"location": "DC", "product": "B"})
    codes = [i for i in validate(ds(d)) if i.code == "COLD_CHAIN_LANE"]
    assert [i.object_id for i in codes] == ["P-DC"]
    d["lanes"][0]["modes"] = [{"mode": "reefer", "transit_days": 1}]
    assert not [i for i in validate(ds(d)) if i.code == "COLD_CHAIN_LANE"]


# ---- through the API, on the company kept on the server ------------------------------------------------------------
def test_stock_postings_through_the_api():
    from .test_companies import h, new_company, signup
    tok = signup("sam@stock.example")
    doc = example()
    cid = new_company(tok, doc)
    rev = client.get(f"/api/companies/{cid}", headers=h(tok)).json()["meta"]["revision"]
    lp0 = next(x for x in doc["location_products"] if x.get("on_hand", 0) > 0)
    body = {"dataset": {"$ref": {"revision": rev}}, "action": "move", "location": lp0["location"],
            "product": lp0["product"], "qty": 1, "stock_type": "unrestricted", "to_type": "blocked"}
    r = client.post("/api/actuals/post", json=body, headers=h(tok, cid))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["report"]["doc"] == "MD-00001" and "blocked" in out["report"]["message"]
    whole = client.post("/api/actuals/post", json={**body, "dataset": doc}).json()
    assert whole["report"] == out["report"]
    view = client.post("/api/actuals", json={"dataset": whole["dataset"], "as_of": "2099-01-01"}).json()
    was = client.post("/api/actuals", json={"dataset": doc, "as_of": "2099-01-01"}).json()
    at = (lp0["location"], lp0["product"])
    row = next(s for s in view["stock"] if (s["location"], s["product"]) == at)
    before = next(s for s in was["stock"] if (s["location"], s["product"]) == at)
    assert row["blocked"] == 1 and row["planning_stock"] == before["planning_stock"] - 1
    bad = client.post("/api/actuals/post", json={**body, "dataset": doc, "qty": 10 ** 9})
    assert bad.status_code == 409 and "only" in bad.json()["detail"]
    assert actuals_view(ds(plant())).stock is not None


def test_goods_received_this_week_show_in_their_batches_and_can_be_released_this_week():
    x = ds(plant(inspect_on_receipt=True))
    start = x.settings.planning_start
    x, _ = post(x, "receive", order="PO-00001", qty=40)                          # dated today: the planning start
    row = next(r for r in stock_rows(x, start) if (r.location, r.product) == ("P", "B"))
    assert row.planning_stock is None or row.planning_stock == 0                 # the plan starts from before today
    assert row.quality == 40 and [lot.stock_type for lot in row.lots] == ["quality"]  # but it is there now
    x, rep = post(x, "move", location="P", product="B", lot={"stock_type": StockType.QUALITY}, to_type=StockType.UNRESTRICTED)
    assert x.movements[-1].date == start and "when the plan moves past" in rep.message
    row = next(r for r in stock_rows(x, start) if (r.location, r.product) == ("P", "B"))
    assert (row.quality, row.unrestricted) == (0, 40)
