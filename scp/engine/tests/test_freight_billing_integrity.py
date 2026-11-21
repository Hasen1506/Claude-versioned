"""A freight bill is a reviewed, dated payable in one set of books."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from scp import transport
from scp.accounting import view
from scp.model import Dataset
from scp.versions.store import Store, set_store

from .test_backup_postgres import pg_databases as pg_databases
from .test_commercial_integrity import save
from .test_companies import h, join, signup
from .test_company_commands import command
from .test_enterprise_integrity import balance, client, team
from .test_transport import D0, TWO, company


def shipped_freight() -> Dataset:
    raw = company([100] * 5, carriers=TWO)
    raw["location_products"][0]["on_hand"] = 0
    raw["entities"] = [{"id": "E1"}, {"id": "E2"}]
    raw["locations"][0]["entity"] = "E1"
    raw["locations"].append({"id": "W2", "type": "dc", "entity": "E2"})
    raw["lanes"].append({**raw["lanes"][0], "id": "IN", "origin": "S", "destination": "W2"})
    raw["freight_orders"] = [
        {"id": fid, "lane": lane, "mode": "truck_ftl", "carrier": "CR-A", "ship_from": origin, "ship_to": target,
         "planned_on": D0.isoformat(), "shipped_on": D0.isoformat(), "status": "shipped", "planned_cost": 90,
         "deliveries": deliveries, "purchases": purchases, "weights": {load: 100 for load in [*deliveries, *purchases]}}
        for fid, lane, origin, target, deliveries, purchases in (
            ("FO-1", "L", "W", "C", ["DL-00001", "DL-00002", "DL-00003"], []),
            ("FO-2", "L", "W", "C", ["DL-00004"], []),
            ("FO-3", "IN", "S", "W2", [], ["PO-1"]),
        )
    ]
    return Dataset.model_validate(raw)


def book(token, cid, order, identifier, revision=1, reference="INV-123", day=D0):
    return command(token, cid, identifier, "transport", "settle", revision, order=order, bill=reference,
                   billed=100, date=day.isoformat())


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_concurrent_carrier_billing_is_authorized_and_cannot_duplicate_or_move_the_payable(backend, request):
    if backend == "postgresql":
        store = Store(request.getfixturevalue("pg_databases")())
        set_store(store)

        def close():
            set_store(None)
            store.db.close()

        request.addfinalizer(close)

    original = shipped_freight()
    grants = {"transport": ["buyer@integrity.example"], "billing": ["freight@integrity.example", "owner@integrity.example"],
              "master_data": ["owner@integrity.example"]}
    original = original.model_copy(update={"finance": original.finance.model_copy(update={"control_roles": grants})})
    owner, dispatcher, cid = team(original)
    biller = signup("freight@integrity.example")
    join(owner, cid, "freight@integrity.example", "planner")
    denied = book(dispatcher, cid, "FO-1", "dispatch-only")
    assert denied.status_code == 403 and "billing" in denied.text
    changed, _ = transport.settle(original, "FO-1", 100, "INV-123", D0)
    assert save(dispatcher, cid, changed).status_code == 403

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(book, biller, cid, "FO-1", "bill-one")
        second = pool.submit(book, owner, cid, "FO-2", "bill-two")
        responses = [first.result(), second.result()]
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = responses.index(next(r for r in responses if r.status_code == 200))
    order, actor, key = [("FO-1", biller, "bill-one"), ("FO-2", owner, "bill-two")][winner]
    losing = ["FO-2", "FO-1"][winner]
    replay = book(actor, cid, order, key)
    assert replay.status_code == 200 and replay.json()["duplicate"] and replay.json()["revision"] == 2
    duplicate = book(biller, cid, losing, "fresh-duplicate", 2, reference=" inv-123 ")
    assert duplicate.status_code == 409 and f"already booked on {order}" in duplicate.text
    current = replay.json()["company"]
    raw = current["dataset"]
    raw_losing = next(row for row in raw["freight_orders"] if row["id"] == losing)
    raw_losing.update(status="settled", billed=100, bill="inv-123", settled_on=D0.isoformat())
    refused = save(biller, cid, raw, 2)
    assert refused.status_code == 403 and "already booked" in refused.text
    raw = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    raw["locations"][0]["entity"] = "E2"
    refused = save(owner, cid, raw, 2)
    assert refused.status_code == 403 and "keeps its posting company" in refused.text

    collection = book(biller, cid, "FO-3", "bill-collection", 2)
    assert collection.status_code == 200, collection.text
    saved = collection.json()["company"]
    assert saved["meta"]["revision"] == 3
    data = Dataset.model_validate(saved["dataset"])
    assert balance(data, "PAYABLES", D0, "E1") == balance(data, "PAYABLES", D0, "E2") == -100
    assert balance(data, "DELIVERY", D0, "E1") == balance(data, "DELIVERY", D0, "E2") == 100
    assert {v.number for v in view(data, period_end=D0).vouchers if v.number.startswith("FO-")} == {order, "FO-3"}


def test_freight_bill_posts_on_the_open_date_and_allocates_every_cent():
    original = shipped_freight()
    original = original.model_copy(update={"finance": original.finance.model_copy(update={"closed_through": D0})})
    owner, _, cid = team(original)
    before_ship = book(owner, cid, "FO-1", "before-shipment", day=D0 - timedelta(days=1))
    assert before_ship.status_code == 409 and "before shipment" in before_ship.text
    closed = book(owner, cid, "FO-1", "closed-day")
    assert closed.status_code == 403 and "is closed" in closed.text
    day = D0 + timedelta(days=1)
    posted = book(owner, cid, "FO-1", "open-day", day=day)
    assert posted.status_code == 200, posted.text
    data = Dataset.model_validate(posted.json()["company"]["dataset"])
    allocations = next(row.lines for row in transport.view(data).orders if row.order.id == "FO-1")
    assert [line.cost for line in allocations] == [33.34, 33.33, 33.33]
    assert balance(data, "PAYABLES", D0, "E1") == 0
    assert balance(data, "PAYABLES", day, "E1") == -100
    assert balance(data, "DELIVERY", day, "E1") == 100
