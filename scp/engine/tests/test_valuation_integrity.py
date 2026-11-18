"""Posted inventory methods and landed costs survive planning/master-data edits."""
from copy import deepcopy
from datetime import date

from hypothesis import given, strategies as st
import pytest

from scp.accounting import view
from scp.actuals.valuation import value_stock
from scp.companies.patch import make_patch
from scp.model import Dataset
from scp.purchasing import act

from .test_companies import h
from .test_enterprise_integrity import client, team
from .test_valuation import company

DAY = date(2026, 1, 5)


def posted(control="standard"):
    x = Dataset.model_validate(company(control, on_hand=0))
    return act(x, "receive", "PO-00001", lines=[{"id": "PO-00001-10", "qty": 100}], on=DAY)[0]


def fetch(token, cid):
    return client.get(f"/api/companies/{cid}", headers=h(token)).json()


def save(token, cid, raw, revision=1, route="whole", base=None):
    if route == "merge":
        return client.post(f"/api/companies/{cid}/merge", headers=h(token), json={
            "base_revision": revision, "base": base, "dataset": raw})
    delta = {"patch": make_patch(base, raw)} if route == "patch" else {"dataset": raw}
    return client.put(f"/api/companies/{cid}", headers=h(token), json={"base_revision": revision, **delta})


def amounts(raw, end=DAY):
    return {r.account: r.balance for r in view(Dataset.model_validate(raw), period_end=end).balances}


@pytest.mark.parametrize("route", ["whole", "patch", "merge"])
@pytest.mark.parametrize("layer", ["company", "product"])
@pytest.mark.parametrize("closed", [False, True])
def test_a_posted_valuation_method_cannot_restate_an_earlier_period(route, layer, closed):
    x = posted()
    if closed:
        x = x.model_copy(update={"finance": x.finance.model_copy(update={"closed_through": DAY})})
    owner, _, cid = team(x)
    initial = fetch(owner, cid)
    raw = deepcopy(initial["dataset"])
    if layer == "company":
        raw["execution"]["price_control"] = "moving_average"
    else:
        next(p for p in raw["products"] if p["id"] == "B")["price_control"] = "moving_average"
    result = save(owner, cid, raw, route=route, base=initial["dataset"])
    assert result.status_code == 403 and "valuation method" in result.text, result.text
    current = fetch(owner, cid)
    assert current["meta"]["revision"] == 1
    assert amounts(current["dataset"]) == {"STOCK": 1500, "GRIR": -1000, "OPENING": -700, "PRICE_DIFF": 200}


@pytest.mark.parametrize("route", ["whole", "patch", "merge"])
@pytest.mark.parametrize("setting", ["duty", "handling", "freight"])
def test_legacy_purchase_costs_are_frozen_before_a_planning_master_edit(route, setting):
    x = posted()
    x = x.model_copy(update={"finance": x.finance.model_copy(update={"closed_through": DAY})})
    owner, _, cid = team(x)
    initial = fetch(owner, cid)
    raw = deepcopy(initial["dataset"])
    if setting == "duty":
        raw["purchasing_sources"][0]["duty_rate"] = .2
    elif setting == "handling":
        raw["locations"][0]["handling_cost_per_unit"] = 2
    else:
        raw["lanes"].append({"id": "SUPPLIER-FREIGHT", "origin": "S", "destination": "P",
                             "modes": [{"mode": "truck_ftl", "transit_days": 1, "cost_per_unit": 2}]})
    before = view(x, period_end=DAY).model_dump()
    result = save(owner, cid, raw, route=route, base=initial["dataset"])
    assert result.status_code == 200, result.text
    kept = Dataset.model_validate(fetch(owner, cid)["dataset"])
    assert view(kept, period_end=DAY).model_dump() == before
    basis = kept.purchase_valuation_by_id["PO-00001-10"]
    assert (basis.base, basis.duty, basis.freight, basis.handling) == (10, 0, 0, 0)


@pytest.mark.parametrize("field,value", [("base", 999), ("duty", .2), ("freight", 2), ("handling", 2),
                                         ("currency", "USD"), ("location", "S")])
def test_a_caller_cannot_forge_a_posted_purchase_valuation_basis(field, value):
    owner, _, cid = team(posted())
    raw = fetch(owner, cid)["dataset"]
    raw["locations"][0]["handling_cost_per_unit"] = 2
    assert save(owner, cid, raw).status_code == 200
    raw = fetch(owner, cid)["dataset"]
    raw["purchase_valuation"][0][field] = value
    result = save(owner, cid, raw, 2)
    assert result.status_code == 403, result.text
    assert fetch(owner, cid)["meta"]["revision"] == 2


def test_omitting_server_metadata_does_not_erase_it_or_apply_new_planning_costs():
    owner, _, cid = team(posted())
    raw = fetch(owner, cid)["dataset"]
    raw["locations"][0]["handling_cost_per_unit"] = 2
    first = save(owner, cid, raw)
    assert first.status_code == 200, first.text
    raw = fetch(owner, cid)["dataset"]
    del raw["purchase_valuation"]
    raw["purchasing_sources"][0]["duty_rate"] = .4
    result = save(owner, cid, raw, 2)
    assert result.status_code == 200, result.text
    kept = fetch(owner, cid)["dataset"]
    assert kept["purchase_valuation"][0]["duty"] == 0 and kept["purchase_valuation"][0]["handling"] == 0
    assert amounts(kept) == {"STOCK": 1500, "GRIR": -1000, "OPENING": -700, "PRICE_DIFF": 200}


def test_an_invoice_before_goods_freezes_terms_and_protects_its_order_line():
    x = Dataset.model_validate(company("moving_average", on_hand=0))
    x, _ = act(x, "enter_invoice", "PO-00001", on=DAY, lines=[{"order": "PO-00001-10", "qty": 100}])
    owner, _, cid = team(x)
    raw = fetch(owner, cid)["dataset"]
    raw["receipts"][0]["price"] = 999
    assert save(owner, cid, raw).status_code == 403
    raw = fetch(owner, cid)["dataset"]
    raw["purchasing_sources"][0]["duty_rate"] = .2
    result = save(owner, cid, raw)
    assert result.status_code == 200, result.text
    current = Dataset.model_validate(fetch(owner, cid)["dataset"])
    received, _ = act(current, "receive", "PO-00001", on=date(2026, 1, 6),
                      lines=[{"id": "PO-00001-10", "qty": 100}])
    result = save(owner, cid, received.model_dump(mode="json"), 2)
    assert result.status_code == 200, result.text
    kept = Dataset.model_validate(fetch(owner, cid)["dataset"])
    assert view(kept, period_end=DAY).model_dump() == view(x, period_end=DAY).model_dump()
    stock = value_stock(kept, date(2026, 1, 6))
    assert next(r for r in stock.rows if r.product == "B").value == 1000


def test_new_lines_use_new_costs_while_existing_postings_keep_their_basis():
    owner, _, cid = team(posted())
    raw = fetch(owner, cid)["dataset"]
    raw["locations"][0]["handling_cost_per_unit"] = 2
    result = save(owner, cid, raw)
    assert result.status_code == 200, result.text
    current = Dataset.model_validate(fetch(owner, cid)["dataset"])
    new, _ = act(current, "receive", "PO-00001", on=date(2026, 1, 6),
                 lines=[{"id": "PO-00001-20", "qty": 10}])
    result = save(owner, cid, new.model_dump(mode="json"), 2)
    assert result.status_code == 200, result.text
    kept = fetch(owner, cid)["dataset"]
    bases = {r["id"]: r for r in kept["purchase_valuation"]}
    assert bases["PO-00001-10"]["handling"] == 0 and bases["PO-00001-20"]["handling"] == 2
    assert amounts(kept, date(2026, 1, 6)) == {
        "STOCK": 1540, "GRIR": -1050, "OPENING": -700, "DELIVERY": -20, "PRICE_DIFF": 230}


@pytest.mark.parametrize("control", ["standard", "moving_average"])
@given(duty=st.decimals(0, 1, places=3), handling=st.decimals(0, 10, places=2))
def test_planning_cost_edits_preserve_the_entire_previous_journal(control, duty, handling):
    # The invariant is historical immutability, independently of how a new plan values its inputs.
    from scp.versions import Store, set_store
    set_store(Store(":memory:"))
    x = posted(control)
    owner, _, cid = team(x)
    raw = fetch(owner, cid)["dataset"]
    raw["purchasing_sources"][0]["duty_rate"] = float(duty)
    raw["locations"][0]["handling_cost_per_unit"] = float(handling)
    result = save(owner, cid, raw)
    assert result.status_code == 200, result.text
    kept = Dataset.model_validate(fetch(owner, cid)["dataset"])
    assert view(kept, period_end=DAY).model_dump() == view(x, period_end=DAY).model_dump()


def test_effective_methods_can_be_represented_differently_without_changing_posted_products():
    owner, _, cid = team(posted())
    raw = fetch(owner, cid)["dataset"]
    raw["execution"]["price_control"] = "moving_average"
    for p in raw["products"]:
        if p["id"] in ("A", "B"):
            p["price_control"] = "standard"
    result = save(owner, cid, raw)
    assert result.status_code == 200, result.text
    assert amounts(fetch(owner, cid)["dataset"]) == {
        "STOCK": 1500, "GRIR": -1000, "OPENING": -700, "PRICE_DIFF": 200}


@pytest.mark.parametrize("setting", ["on_hand", "planning_start", "resource_cost"])
def test_setup_openings_become_retained_facts_before_planning_inputs_change(setting):
    x = posted()
    owner, _, cid = team(x)
    raw = fetch(owner, cid)["dataset"]
    if setting == "on_hand":
        next(lp for lp in raw["location_products"] if lp["product"] == "A")["on_hand"] = 999
    elif setting == "planning_start":
        raw["settings"]["planning_start"] = "2026-01-12"
    else:
        raw["resources"][0]["cost_per_hour"] = 200
    result = save(owner, cid, raw)
    assert result.status_code == 200, result.text
    kept = Dataset.model_validate(fetch(owner, cid)["dataset"])
    assert view(kept, period_end=DAY).model_dump() == view(x, period_end=DAY).model_dump()
    opening = next(m for m in kept.movements if m.type.value == "opening" and m.product == "A")
    assert opening.qty == 10 and opening.standard_price == 70 and opening.date == date(2026, 1, 4)


def test_product_weight_and_volume_edits_do_not_rewrite_freight():
    raw = company("standard", on_hand=0)
    raw["products"][1].update(weight_kg=2, volume_m3=1)
    raw["lanes"].append({"id": "SUPPLIER-FREIGHT", "origin": "S", "destination": "P",
                         "modes": [{"mode": "truck_ftl", "transit_days": 1, "cost_per_kg": 1, "cost_per_m3": 3}]})
    x, _ = act(Dataset.model_validate(raw), "receive", "PO-00001", on=DAY,
               lines=[{"id": "PO-00001-10", "qty": 100}])
    owner, _, cid = team(x)
    raw = fetch(owner, cid)["dataset"]
    raw["products"][1].update(weight_kg=4, volume_m3=2)
    result = save(owner, cid, raw)
    assert result.status_code == 200, result.text
    kept = fetch(owner, cid)["dataset"]
    assert kept["purchase_valuation"][0]["freight"] == 5
    assert amounts(kept) == {"STOCK": 1500, "GRIR": -1000, "OPENING": -700,
                            "DELIVERY": -500, "PRICE_DIFF": 700}


@pytest.mark.parametrize("malformed", [None, {}, [None]])
def test_malformed_valuation_records_are_refused_without_an_internal_error(malformed):
    owner, _, cid = team(posted())
    raw = fetch(owner, cid)["dataset"]
    raw["purchase_valuation"] = malformed
    result = save(owner, cid, raw)
    assert result.status_code in (403, 422), result.text
    assert fetch(owner, cid)["meta"]["revision"] == 1


def test_unposted_valuation_records_are_refused():
    x = Dataset.model_validate(company("standard", on_hand=0))
    owner, _, cid = team(x)
    raw = fetch(owner, cid)["dataset"]
    raw["purchase_valuation"] = [{"id": "PO-00001-10", "supplier": "S", "location": "P", "product": "B",
                                  "currency": "INR", "base": 10, "duty": 0, "freight": 0, "handling": 0}]
    assert save(owner, cid, raw).status_code == 403


def test_duplicate_valuation_records_are_refused():
    x = posted()
    owner, _, cid = team(x)
    raw = fetch(owner, cid)["dataset"]
    raw["locations"][0]["handling_cost_per_unit"] = 2
    assert save(owner, cid, raw).status_code == 200
    raw = fetch(owner, cid)["dataset"]
    raw["purchase_valuation"] *= 2
    assert save(owner, cid, raw, 2).status_code == 403


def test_omitted_openings_are_retained_and_explicit_rewrites_are_refused():
    owner, _, cid = team(posted())
    raw = fetch(owner, cid)["dataset"]
    raw["locations"][0]["handling_cost_per_unit"] = 2
    assert save(owner, cid, raw).status_code == 200
    raw = fetch(owner, cid)["dataset"]
    original = deepcopy(raw)
    raw["movements"] = [m for m in raw["movements"] if not m["id"].startswith("OP-")]
    assert save(owner, cid, raw, 2).status_code == 200
    current = fetch(owner, cid)
    assert amounts(current["dataset"]) == amounts(original)
    raw = current["dataset"]
    next(m for m in raw["movements"] if m["id"].startswith("OP-"))["qty"] = 999
    result = save(owner, cid, raw, current["meta"]["revision"])
    assert result.status_code == 403, result.text


def test_a_foreign_receipt_retains_its_base_when_the_header_is_removed_and_planning_fx_changes():
    raw = company("standard", on_hand=0)
    raw["settings"]["fx_rates"] = {"USD": 80}
    raw["purchase_orders"][0].update(currency="USD", fx_rate=80)
    raw["purchasing_sources"][0]["currency"] = "USD"
    x, _ = act(Dataset.model_validate(raw), "receive", "PO-00001", on=DAY,
               lines=[{"id": "PO-00001-10", "qty": 100}])
    owner, _, cid = team(x)
    raw = fetch(owner, cid)["dataset"]
    raw["purchase_orders"] = []
    raw["settings"]["fx_rates"]["USD"] = 90
    result = save(owner, cid, raw)
    assert result.status_code == 200, result.text
    kept = fetch(owner, cid)["dataset"]
    assert kept["purchase_valuation"][0]["base"] == 800
    assert amounts(kept) == {"STOCK": 1500, "GRIR": -80000, "OPENING": -700, "PRICE_DIFF": 79200}
