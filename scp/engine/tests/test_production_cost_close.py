"""Independent amounts and live persistence for actual production costs and WIP close."""
from datetime import date

from scp.accounting import view
from scp.actuals.documents import reverse
from scp.actuals.post import receive
from scp.actuals.roll import roll_forward
from scp.model import Dataset

from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client, team
from .test_jobwork_integrity import company as jobwork_fixture

RECEIPT = date(2026, 1, 6)
BOOK = "2026-01-06"


def internal(second=False):
    raw = jobwork_fixture().model_dump(mode="json")
    raw["production_sources"][0].update(operations=[], conversion_cost_per_unit=2)
    if second:
        raw["receipts"].append({**raw["receipts"][0], "id": "MO-2"})
    ds, _ = receive(Dataset.model_validate(raw), "MO-1", 10, on=RECEIPT, final=True)
    if second:
        ds, _ = receive(ds, "MO-2", 5, on=RECEIPT, usage=[{"product": "B", "qty": 17.5}])
    return ds


def put(owner, cid, dataset, revision):
    return client.put(f"/api/companies/{cid}", headers=h(owner), json={"base_revision": revision, "dataset": dataset})


def close(owner, cid, doc, on=BOOK):
    data = {**doc["dataset"], "finance": {**doc["dataset"].get("finance", {}), "closed_through": on}}
    return put(owner, cid, data, doc["meta"]["revision"])


def saved(owner, cid):
    return client.get(f"/api/companies/{cid}", headers=h(owner)).json()


def cost(owner, cid, identifier, action, revision, on=BOOK, confirm_actuals=True, **parameters):
    if action == "settle":
        parameters["confirm_actuals"] = confirm_actuals
    return command(owner, cid, identifier, "production_cost", action, revision=revision,
                   date=on, order="MO-1", reference=identifier, **parameters)


def balances(doc, day=RECEIPT):
    report = view(Dataset.model_validate(doc["dataset"]), period_end=day)
    return report, {b.account: b.balance for b in report.balances}


def test_period_close_detects_each_completed_order_even_when_the_company_wip_nets_to_zero():
    owner, _, cid = team(internal(second=True))
    before = saved(owner, cid)
    report, total = balances(before)
    assert total.get("WIP", 0) == 0
    assert [(r.order, r.completed_on, r.balance_minor) for r in report.production_wip] == [
        ("MO-1", RECEIPT, -2000), ("MO-2", None, 2000),
    ]
    rejected = close(owner, cid, before)
    assert rejected.status_code == 403 and "MO-1" in rejected.text and "MO-2" not in rejected.text
    assert saved(owner, cid)["meta"]["revision"] == 1


def test_actual_cost_and_variance_settle_and_replay_with_literal_ledger_amounts():
    owner, member, cid = team(internal())
    blocked = cost(member, cid, "ungranted", "conversion", 1, amount_minor=2600)
    assert blocked.status_code == 403
    first = cost(owner, cid, "labor-42", "conversion", 1, amount_minor=2600)
    assert first.status_code == 200, first.text
    token = first.json()
    assert token["result"]["posting"]["amount_minor"] == 2600 and token["revision"] == 2
    report, intermediate = balances(token["company"])
    assert intermediate["WIP"] == 6 and intermediate["CONVERSION_ABSORPTION"] == -26
    assert any(line.production_order == "MO-1" and line.debit == 26 for v in report.vouchers for line in v.lines)
    repeated = cost(owner, cid, "labor-42", "conversion", 1, amount_minor=2600)
    assert repeated.status_code == 200 and repeated.json()["duplicate"]
    unreviewed = cost(owner, cid, "unreviewed", "settle", 2, confirm_actuals=False)
    assert unreviewed.status_code == 409 and "reviewed" in unreviewed.text
    strike = cost(owner, cid, "settle-42", "settle", 2)
    assert strike.status_code == 200, strike.text
    doc = strike.json()["company"]
    assert strike.json()["result"]["posting"]["amount_minor"] == -600
    report, total = balances(doc)
    assert total == {"STOCK": 420, "WIP": 0, "OPENING": -400, "CONVERSION_ABSORPTION": -26, "PRODUCTION_VARIANCE": 6}
    assert report.production_wip[0].balance_minor == 0
    assert close(owner, cid, doc).status_code == 200
    blocked = cost(owner, cid, "late", "conversion", 4, amount_minor=500)
    assert blocked.status_code == 409 and "closed" in blocked.text


def test_a_completed_order_and_posted_cost_cannot_be_removed_with_a_save():
    owner, _, cid = team(internal())
    original = saved(owner, cid)["dataset"]
    removed = {**original, "receipts": []}
    refused = put(owner, cid, removed, 1)
    assert refused.status_code == 403 and "retains its order" in refused.text
    out = cost(owner, cid, "labor-line", "conversion", 1, amount_minor=2600).json()
    revised = out["company"]["dataset"]
    forged = {**revised, "production_cost_postings": [{**revised["production_cost_postings"][0], "amount_minor": 1}]}
    refused = put(owner, cid, forged, 2)
    assert refused.status_code == 403 and "production cost postings are retained" in refused.text
    assert saved(owner, cid)["meta"]["revision"] == 2


def test_archive_and_real_receipt_reversal_preserve_wip_history():
    original = internal()
    owner, _, cid = team(original)
    rolled, _ = roll_forward(original, date(2026, 1, 7))
    response = put(owner, cid, rolled.model_dump(mode="json"), 1)
    assert response.status_code == 200, response.text
    doc = saved(owner, cid)
    report, _ = balances(doc)
    assert report.production_wip[0].completed_on == RECEIPT
    strike = cost(owner, cid, "settle", "settle", 2)
    assert strike.status_code == 200, strike.text
    doc = strike.json()["company"]
    mid = next(m.id for m in rolled.movements if m.type.value == "receipt")
    reopened, _ = reverse(Dataset.model_validate(doc["dataset"]), mid, on=date(2026, 1, 7))
    response = put(owner, cid, reopened.model_dump(mode="json"), 3)
    assert response.status_code == 200, response.text
    reopened_doc = saved(owner, cid)
    assert close(owner, cid, reopened_doc, "2026-01-07").status_code == 403
    undo = cost(owner, cid, "variance-reversal", "reverse", 4, on="2026-01-07",
                posting=strike.json()["result"]["posting"]["id"])
    assert undo.status_code == 200, undo.text
    report, _ = balances(undo.json()["company"], date(2026, 1, 7))
    assert report.production_wip[0].settlement is None and report.production_wip[0].completed_on is None
