"""Family limits use both ownership states; nested count documents stay inside their plants/groups."""
from __future__ import annotations

from scp.actuals.documents import cancel_counts, count_doc, enter_counts, post_counts
from scp.model import Dataset

from .test_companies import h, join
from .test_commercial_integrity import save
from .test_enterprise_integrity import client, team
from .test_material_integrity import persisted
from .test_order_to_cash import taken
from .test_procure_to_pay import JAN


def grouped():
    doc = taken()[0].model_dump(mode="json")
    for product in doc["products"]:
        product["family"] = "FG" if product["id"] == "A" else "RM"
    return Dataset.model_validate(doc)


def test_family_scope_cannot_be_widened_by_renaming_someone_elses_product_family():
    x = grouped()
    owner, planner, cid = team(x)
    join(owner, cid, "buyer@integrity.example", "planner", families=["FG"])
    forged = x.model_dump(mode="json")
    next(p for p in forged["products"] if p["id"] == "B").update(family="FG", price=777)
    response = save(planner, cid, forged)
    assert response.status_code == 403 and "product" in response.text.lower(), response.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 1


def test_a_family_member_can_create_within_their_group_but_cannot_move_a_product_out():
    x = grouped()
    owner, planner, cid = team(x)
    join(owner, cid, "buyer@integrity.example", "planner", families=["FG"])
    doc = x.model_dump(mode="json")
    next(p for p in doc["products"] if p["id"] == "A")["family"] = "RM"
    assert save(planner, cid, doc).status_code == 403
    doc = x.model_dump(mode="json")
    doc["products"].append({"id": "NEW-FG", "family": "FG", "type": "FG", "price": 5})
    assert save(planner, cid, doc).status_code == 200


def test_scoped_warehouse_member_can_complete_a_count_for_its_own_plant_and_group():
    x = count_doc(grouped(), [("P", "A")], JAN, block=False)[0]
    x = cancel_counts(x, x.inventory_docs[0].id)[0]  # approved opening balances already recorded
    owner, planner, cid = team(x)
    join(owner, cid, "buyer@integrity.example", "planner", places=["P"], families=["FG"])
    counted, _ = count_doc(x, [("P", "A")], JAN, block=True)
    counted = persisted(planner, cid, counted)
    did = counted.inventory_docs[-1].id
    entered, _ = enter_counts(counted, did, [{"location": "P", "product": "A", "qty": 95}])
    entered = persisted(planner, cid, entered, 2)
    posted, _ = post_counts(entered, did)
    assert save(planner, cid, posted, 3).status_code == 200


def test_a_count_that_includes_another_plant_is_not_authorized_by_one_owned_item():
    doc = grouped().model_dump(mode="json")
    doc["locations"].append({"id": "Q", "type": "dc"})
    doc["location_products"].append({"location": "Q", "product": "A", "on_hand": 10})
    x = count_doc(Dataset.model_validate(doc), [("P", "A")], JAN, block=False)[0]
    x = cancel_counts(x, x.inventory_docs[0].id)[0]
    owner, planner, cid = team(x)
    join(owner, cid, "buyer@integrity.example", "planner", places=["P"], families=["FG"])
    counted, _ = count_doc(x, [("P", "A"), ("Q", "A")], JAN, block=True)
    assert save(planner, cid, counted).status_code == 403
