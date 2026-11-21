"""Authoritative warehouse state: counterexamples and complete persisted count/serial flows."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from scp.actuals.documents import cancel_counts, count_doc, enter_counts, move_stock, post_counts
from scp.actuals.post import receive
from scp.actuals.stock import before, stock
from scp.companies.patch import make_patch
from scp.model import Dataset, StockType

from .test_companies import h
from .test_company_commands import command
from .test_commercial_integrity import save
from .test_enterprise_integrity import client, team
from .test_order_to_cash import taken
from .test_procure_to_pay import JAN


def persisted(token, cid, ds, revision=1):
    response = save(token, cid, ds, revision)
    assert response.status_code == 200, response.text
    return Dataset.model_validate(client.get(f"/api/companies/{cid}", headers=h(token)).json()["dataset"])


@pytest.mark.parametrize("route", ["whole", "patch", "merge"])
@pytest.mark.parametrize("attack", ["unbalanced_status", "blocked_count"])
def test_material_invariants_hold_for_every_persistence_route(route, attack):
    x = taken()[0]
    if attack == "blocked_count":
        x = count_doc(x, [("P", "A")], JAN, block=True)[0]
    owner, _, cid = team(x)
    old = x.model_dump(mode="json")
    doc = x.model_dump(mode="json")
    doc["movements"].append({"id": "FORGED-STOCK", "date": JAN.isoformat(), "location": "P", "product": "A",
                             "type": "status" if attack == "unbalanced_status" else "scrap", "qty": 1})
    if route == "merge":
        response = client.post(f"/api/companies/{cid}/merge", headers=h(owner), json={
            "base": old, "dataset": doc, "base_revision": 1})
    else:
        body = {"patch": make_patch(old, doc)} if route == "patch" else {"dataset": doc}
        response = client.put(f"/api/companies/{cid}", headers=h(owner), json={"base_revision": 1, **body})
    assert response.status_code == 403, response.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 1


def test_stock_status_transfer_conserves_quantity_when_persisted():
    x = taken()[0]
    owner, _, cid = team(x)
    moved, _ = move_stock(x, "P", "A", 5, StockType.UNRESTRICTED, StockType.QUALITY, on=JAN)
    saved = persisted(owner, cid, moved)
    assert stock(before(saved, JAN + timedelta(days=1)))[("P", "A")] == 100


def test_count_book_is_server_derived_and_posted_difference_matches_the_physical_count():
    x = taken()[0]
    owner, _, cid = team(x)
    counted, _ = count_doc(x, [("P", "A")], JAN, block=True)
    counted = persisted(owner, cid, counted)
    did = counted.inventory_docs[0].id
    entered, _ = enter_counts(counted, did, [{"location": "P", "product": "A", "qty": 95}])
    forged = entered.model_dump(mode="json")
    forged["inventory_docs"][0]["items"][0]["book_qty"] = 0
    assert save(owner, cid, forged, 2).status_code == 403
    entered = persisted(owner, cid, entered, 2)
    posted, _ = post_counts(entered, did)
    saved = persisted(owner, cid, posted, 3)
    assert stock(before(saved, JAN + timedelta(days=1)))[("P", "A")] == 95
    forged = saved.model_dump(mode="json")
    forged["inventory_docs"][0]["items"][0]["counted"] = 94
    assert save(owner, cid, forged, 4).status_code == 403


def test_created_and_posted_count_is_replayed_against_the_authoritative_opening_book():
    x = taken()[0]
    owner, _, cid = team(x)
    counted, _ = count_doc(x, [("P", "A")], JAN, block=True)
    counted, _ = enter_counts(counted, counted.inventory_docs[0].id, [{"location": "P", "product": "A", "qty": 95}])
    posted, _ = post_counts(counted, counted.inventory_docs[0].id)
    saved = persisted(owner, cid, posted)
    assert stock(before(saved, JAN + timedelta(days=1)))[("P", "A")] == 95


def test_count_material_effect_cannot_differ_from_the_documented_count():
    x = count_doc(taken()[0], [("P", "A")], JAN, block=True)[0]
    owner, _, cid = team(x)
    x, _ = enter_counts(x, x.inventory_docs[0].id, [{"location": "P", "product": "A", "qty": 95}])
    x, _ = post_counts(x, x.inventory_docs[0].id)
    doc = x.model_dump(mode="json")
    next(m for m in doc["movements"] if m["type"] == "adjustment")["qty"] = -4
    assert save(owner, cid, doc).status_code == 403


def test_live_count_posts_one_reviewed_difference_without_master_data_authority():
    day = JAN - timedelta(days=1)
    original = taken()[0]
    policy = original.finance.model_copy(update={"control_roles": {
        "warehouse": ["buyer@integrity.example"], "inventory_adjustment": ["buyer@integrity.example"],
    }})
    owner, warehouse, company = team(original.model_copy(update={"finance": policy}))
    date_arg = {"date": day.isoformat()}
    begin = command(warehouse, company, "begin-count", "stock", "count_doc", 1,
                    nodes=[{"location": "P", "product": "A"}], **date_arg)
    assert begin.status_code == 200, begin.text
    doc = begin.json()["result"]["report"]["doc"]
    counts = [{"location": "P", "product": "A", "stock_type": "unrestricted", "qty": 95}]
    entered = command(warehouse, company, "enter-count", "stock", "count_enter", 2, doc=doc, counts=counts, **date_arg)
    assert entered.status_code == 200, entered.text
    approval = client.put(f"/api/companies/{company}/approval", headers=h(owner), json={"approval": True})
    assert approval.status_code == 200, approval.text
    stale_counts = [{**counts[0], "qty": 96}]
    stale = command(warehouse, company, "post-count", "stock", "count_post", 3, doc=doc, counts=stale_counts, **date_arg)
    assert stale.status_code == 409 and "saved counts changed" in stale.text
    wrong_day = command(warehouse, company, "post-count", "stock", "count_post", 3, doc=doc, counts=counts)
    assert wrong_day.status_code == 409 and "posting date" in wrong_day.text
    raw = entered.json()["company"]["dataset"]
    next(lp for lp in raw["location_products"] if (lp["location"], lp["product"]) == ("P", "A"))["on_hand"] = 99
    denied = save(warehouse, company, raw, 3)
    assert denied.status_code == 403 and "master_data" in denied.text
    posted = command(warehouse, company, "post-count", "stock", "count_post", 3, doc=doc, counts=counts, **date_arg)
    assert posted.status_code == 200, posted.text
    retry = command(warehouse, company, "post-count", "stock", "count_post", 3, doc=doc, counts=counts, **date_arg)
    assert retry.status_code == 200 and retry.json()["duplicate"]
    saved = retry.json()["company"]
    assert saved["meta"]["revision"] == 4
    dataset = Dataset.model_validate(saved["dataset"])
    assert dataset.inventory_docs[0].status == "posted"
    assert [(m.date, m.qty) for m in dataset.movements if m.type == "adjustment"] == [(day, -5)]
    assert stock(before(dataset, JAN))[("P", "A")] == 95
    assert next(lp.on_hand for lp in dataset.location_products if (lp.location, lp.product) == ("P", "A")) == 95


def test_cancelling_an_open_count_releases_its_block_without_removing_history():
    x = count_doc(taken()[0], [("P", "A")], JAN, block=True)[0]
    owner, _, cid = team(x)
    cancelled, _ = cancel_counts(x, x.inventory_docs[0].id)
    saved = persisted(owner, cid, cancelled)
    doc = saved.model_dump(mode="json")
    doc["movements"].append({"id": "SCRAP-AFTER-CANCEL", "date": JAN.isoformat(), "type": "scrap",
                             "location": "P", "product": "A", "qty": 1})
    saved = persisted(owner, cid, doc, 2)
    assert stock(before(saved, JAN + timedelta(days=1)))[("P", "A")] == 99


def serial_stock():
    doc = taken()[0].model_dump(mode="json")
    next(p for p in doc["products"] if p["id"] == "A")["serial_numbers"] = True
    next(p for p in doc["location_products"] if p["location"] == "P" and p["product"] == "A")["on_hand"] = 0
    doc["locations"].append({"id": "Q", "type": "dc"})
    doc["location_products"].append({"location": "Q", "product": "A", "on_hand": 0})
    doc["lanes"].append({"id": "PQ", "origin": "P", "destination": "Q", "modes": [{"transit_days": 1}]})
    doc["receipts"].append({"id": "SERIAL-TRANSFER", "kind": "transfer", "location": "Q", "product": "A",
                            "qty": 1, "due_date": "2026-01-07", "source": "PQ"})
    doc["movements"] = [{"id": "SERIAL-1", "date": "2026-01-06", "type": "receipt", "location": "P",
                         "product": "A", "qty": 1, "serials": ["SN-A"]}]
    return Dataset.model_validate(doc)


@pytest.mark.parametrize("attack", ["duplicate", "missing", "wrong_place", "before_receipt", "disable_profile", "duplicate_then_issue"])
def test_serials_cannot_be_duplicated_omitted_issued_elsewhere_or_backdated(attack):
    x = serial_stock()
    owner, _, cid = team(x)
    doc = x.model_dump(mode="json")
    if attack == "disable_profile":
        next(p for p in doc["products"] if p["id"] == "A")["serial_numbers"] = False
    else:
        doc["movements"].append({"id": "FORGED-SERIAL", "date": "2026-01-05" if attack == "before_receipt" else "2026-01-07",
                                 "type": "issue" if attack in ("wrong_place", "before_receipt") else "receipt",
                                 "location": "Q" if attack == "wrong_place" else "P", "product": "A", "qty": 1,
                                 "serials": [] if attack == "missing" else ["SN-A"]})
        if attack == "duplicate_then_issue":
            doc["movements"].append({"id": "LATER-ISSUE", "doc": "LATER-DOC", "date": "2026-01-07", "type": "issue",
                                     "location": "P", "product": "A", "qty": 1, "serials": ["SN-A"]})
    response = save(owner, cid, doc)
    assert response.status_code == 403, response.text


def test_the_same_serial_can_be_transferred_between_places_in_one_material_document():
    x = serial_stock()
    owner, _, cid = team(x)
    moved, _ = receive(x, "SERIAL-TRANSFER", on=date(2026, 1, 7))
    saved = persisted(owner, cid, moved)
    assert sum(m.signed for m in saved.movements if "SN-A" in m.serials and m.location == "P") == 0
    assert sum(m.signed for m in saved.movements if "SN-A" in m.serials and m.location == "Q") == 1


def test_inventory_adjustment_requires_a_separate_named_grant():
    x = count_doc(taken()[0], [("P", "A")], JAN, block=False)[0]
    x = cancel_counts(x, x.inventory_docs[0].id)[0]
    owner, picker, cid = team(x)
    doc = x.model_dump(mode="json")
    doc["finance"]["control_roles"] = {"warehouse": ["owner@integrity.example", "buyer@integrity.example"],
                                        "inventory_adjustment": ["owner@integrity.example"]}
    persisted(owner, cid, doc)
    doc["movements"].append({"id": "MANUAL-ADJUSTMENT", "date": JAN.isoformat(), "type": "adjustment",
                             "location": "P", "product": "A", "qty": -1})
    assert save(picker, cid, doc, 2).status_code == 403
    assert save(owner, cid, doc, 2).status_code == 200
