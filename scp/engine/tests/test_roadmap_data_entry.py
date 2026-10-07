"""Roadmap PR B: data entry. A one-off purchase order, not only from requisitions (UX audit, Purchase orders row)."""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from scp.api.app import app
from scp.purchasing import create_one_off_po

from .factory import base, ds


def _d() -> dict:
    d = base(horizon=56)
    d["purchasing_sources"][0].update({"moq": 20, "rounding_qty": 10})
    return d


def test_one_off_po_makes_one_approved_line_on_the_source():
    new, rep = create_one_off_po(ds(_d()), "PIR-C", 7)
    assert rep.ok and len(rep.created) == 1
    po = rep.created[0]
    line = next(r for r in new.receipts if r.id == po.lines[0])
    assert line.product == "C" and line.location == "P" and line.qty == 7 and line.po == po.id
    assert line.due_date == date(2026, 1, 6)        # 1-day lead time from the plan start: as soon as possible
    assert any(h.id == po.id for h in new.purchase_orders)


def test_one_off_po_rounds_to_the_suppliers_minimum_and_never_promises_sooner_than_the_lead_time():
    new, rep = create_one_off_po(ds(_d()), "PIR-B", 5, due_date=date(2026, 1, 5))
    line = next(r for r in new.receipts if r.id == rep.created[0].lines[0])
    assert line.qty >= 20 and line.due_date == date(2026, 1, 8)    # 3-day lead time
    assert any("minimum" in n for n in rep.created[0].notes) and any("can deliver" in n for n in rep.created[0].notes)


def test_one_off_po_rejects_unknown_sources_and_non_positive_quantities():
    assert not create_one_off_po(ds(_d()), "NOPE", 5)[1].ok
    assert not create_one_off_po(ds(_d()), "PIR-B", 0)[1].ok


@settings(max_examples=25, deadline=None, derandomize=True)
@given(st.floats(min_value=0.001, max_value=1e6, allow_nan=False), st.sampled_from(["PIR-B", "PIR-C"]))
def test_one_off_po_numbers_never_collide(qty, src):
    d0 = ds(_d())
    d1, r1 = create_one_off_po(d0, src, qty)
    d2, r2 = create_one_off_po(d1, src, qty)
    ids = [r.id for r in d2.receipts]
    assert len(ids) == len(set(ids)) and r1.created[0].id != r2.created[0].id
    assert all(r.qty >= qty - 1e-9 for r in d2.receipts if r.po)


def test_one_off_po_endpoint():
    c = TestClient(app)
    r = c.post("/api/purchasing/one-off", json={"dataset": _d(), "source_id": "PIR-C", "qty": 12})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report"]["created"][0]["lines"]
    assert c.post("/api/purchasing/one-off", json={"dataset": _d(), "source_id": "NOPE", "qty": 1}).status_code == 409
    assert c.post("/api/purchasing/one-off", json={"dataset": _d(), "source_id": "PIR-C", "qty": 0}).status_code == 422
