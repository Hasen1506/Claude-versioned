"""Company controls on inventory variances use the posted journal and independent count evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from scp.accounting import view
from scp.actuals.documents import post_counts
from scp.actuals.post import count_stock
from scp.companies import get_companies
from scp.companies import commands
from scp.companies.patch import make_patch
from scp.model import Dataset
from scp.versions import Store, set_store

from .factory import base, lp
from .test_backup_postgres import pg_databases as pg_databases
from .test_companies import h
from .test_company_commands import command
from .test_enterprise_integrity import client, team

DAY = "2026-01-04"
ACTORS = ["owner@integrity.example", "buyer@integrity.example"]


def warehouse(item=1234, document=1234, currency="KWD"):
    raw = base()
    raw["settings"]["currency"] = currency
    raw["execution"] = {"price_control": "standard"}
    raw["finance"] = {"inventory_count_limits": {"item_minor": item, "document_minor": document, "reviewers": ACTORS},
                      "control_roles": {"warehouse": ACTORS, "inventory_adjustment": ACTORS, "master_data": ACTORS[:1]}}
    raw["movements"] = [
        {"id": f"OPEN-{product}", "type": "opening", "date": DAY, "location": "P", "product": product,
         "qty": 10, "standard_price": 1.234} for product in ("A", "B")
    ]
    raw["movements"][0]["opening_standards"] = {"P": {"A": 1.234, "B": 1.234}}
    for product in ("A", "B"):
        lp(raw, "P", product)["on_hand"] = 10
    return Dataset.model_validate(raw)


def counts(**quantities):
    return [{"location": "P", "product": product, "qty": amount} for product, amount in quantities.items()]


def open_count(actor, cid, quantities):
    opened = command(actor, cid, "begin", "stock", "count_doc", date=DAY, block=False,
                     nodes=[{"location": row["location"], "product": row["product"]} for row in quantities])
    assert opened.status_code == 200, opened.text
    request = {"doc": opened.json()["result"]["report"]["doc"], "counts": quantities}
    entered = command(actor, cid, "entry", "stock", "count_enter", 2, date=DAY, **request)
    assert entered.status_code == 200, entered.text
    d = entered.json()["company"]["dataset"]["inventory_docs"][0]
    actor_id = client.get("/api/auth/me", headers=h(actor)).json()["user"]["id"]
    assert {row["counted_by"] for row in d["items"]} == {actor_id}
    return request


@pytest.mark.parametrize(("per_item", "per_document", "status"), [(1235, 1235, 200), (1234, 1234, 200), (1233, 1234, 403)])
def test_count_posting_compares_exact_journal_minor_units(per_item, per_document, status):
    owner, counter, cid = team(warehouse(per_item, per_document))
    args = open_count(counter, cid, counts(B=9))
    posted = command(counter, cid, "normal", "stock", "count_post", 3, date=DAY, **args)
    assert posted.status_code == status, posted.text
    if status == 200:
        ds = Dataset.model_validate(posted.json()["company"]["dataset"])
        books = view(ds, period_end=date.fromisoformat(DAY))
        assert next(row.balance for row in books.balances if row.account == "COUNT_DIFF") == 1.234
        assert all(check.ok for check in books.checks)
    else:
        assert "KWD 1.234" in posted.text
        assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 3


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_gains_and_losses_do_not_net_against_document_limit_and_reviewer_posts_once(backend, request, monkeypatch):
    if backend == "postgresql":
        source = Store(request.getfixturevalue("pg_databases")())
        set_store(source)
        request.addfinalizer(source.db.close)
    owner, counter, cid = team(warehouse(document=2467))
    args = open_count(counter, cid, counts(A=11, B=9))
    denied = command(counter, cid, "post", "stock", "count_post", 3, date=DAY, **args)
    assert denied.status_code == 403 and "KWD 2.468" in denied.text
    review = {**args, "review_reason": "Rechecked both stock lines independently"}
    self_review = command(counter, cid, "post", "stock", "count_post", 3, date=DAY, **review)
    assert self_review.status_code == 403 and "did not enter the count" in self_review.text
    wrong_counts = {**review, "counts": counts(A=12, B=9)}
    stale = command(owner, cid, "post", "stock", "count_post", 3, date=DAY, **wrong_counts)
    assert stale.status_code == 409 and "saved counts changed" in stale.text
    checked = client.get(f"/api/companies/{cid}", headers=h(owner)).json()

    def failed_receipt(*args, **kwargs):
        raise OSError("approval receipt could not be committed")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "_record", failed_receipt)
        with pytest.raises(OSError, match="approval receipt"):
            command(owner, cid, "post", "stock", "count_post", 3, date=DAY, **review)
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json() == checked
    def approve():
        return command(owner, cid, "post", "stock", "count_post", 3, date=DAY, **review)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [pool.submit(approve) for _ in range(2)]
        first, second = (reply.result(timeout=20) for reply in responses)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert {first.json()["duplicate"], second.json()["duplicate"]} == {False, True}
    assert first.json()["revision"] == second.json()["revision"] == 4
    accepted = first
    saved = accepted.json()["company"]["dataset"]
    assert [m["qty"] for m in saved["movements"] if m["type"] == "adjustment"] == [1, -1]
    receipt = client.get(f"/api/companies/{cid}/commands", params={"id": "post"}, headers=h(owner)).json()
    assert receipt["revision"] == 4 and receipt["parameters"]["review_reason"] == review["review_reason"]
    db = get_companies().db
    poster = db.execute("SELECT email FROM users JOIN company_commands ON users.id = company_commands.user_id "
                        "WHERE company_id = ? AND command_id = ?", (cid, "post")).fetchone()[0]
    assert poster == ACTORS[0]


@pytest.mark.parametrize("path", ["document", "quick", "patch", "merge", "opening", "unmatched receipt"])
def test_other_saved_write_paths_cannot_post_an_over_limit_adjustment(path):
    owner, counter, cid = team(warehouse(item=1233, currency="INR" if path == "unmatched receipt" else "KWD"))
    args = open_count(counter, cid, counts(B=9))
    saved = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    ds = Dataset.model_validate(saved)
    if path == "document":
        changed, _ = post_counts(ds, args["doc"])
    else:
        changed, _ = count_stock(ds, counts(B=9), date.fromisoformat(DAY))
    proposed = changed.model_dump(mode="json")
    if path == "opening":
        proposed["movements"][-1].update({"type": "opening", "qty": 100_000})
    if path == "unmatched receipt":
        proposed["movements"][-1].update({"type": "receipt", "qty": 100_000})
    if path == "merge":
        refused = client.post(f"/api/companies/{cid}/merge", headers=h(owner),
                              json={"base_revision": 3, "dataset": proposed, "base": saved})
    else:
        change = {"patch": make_patch(saved, proposed)} if path == "patch" else {"dataset": proposed}
        refused = client.put(f"/api/companies/{cid}", headers=h(owner), json={"base_revision": 3, **change})
    assert refused.status_code == 403 and "exceeds inventory posting limits" in refused.text, refused.text
    assert client.get(f"/api/companies/{cid}", headers=h(owner)).json()["meta"]["revision"] == 3


def test_count_provenance_and_same_write_policy_edit_are_refused():
    owner, counter, cid = team(warehouse(item=1233))
    args = open_count(counter, cid, counts(B=9))
    saved = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    ds = Dataset.model_validate(saved)
    saved["inventory_docs"][0]["items"][0]["counted_by"] = ACTORS[0]
    forged = client.put(f"/api/companies/{cid}", headers=h(owner), json={"base_revision": 3, "dataset": saved})
    assert forged.status_code == 403 and "server-recorded count entrants" in forged.text
    changed, _ = post_counts(ds, args["doc"])
    proposed = changed.model_dump(mode="json")
    proposed["finance"].pop("inventory_count_limits")
    for token, message in ((counter, "only a company owner"), (owner, "save changes to inventory posting limits separately")):
        refused = client.put(f"/api/companies/{cid}", headers=h(token), json={"base_revision": 3, "dataset": proposed})
        assert refused.status_code == 403 and message in refused.text


def test_split_rows_still_use_the_same_physical_line_limit():
    owner, _, cid = team(warehouse(item=1233, document=4000))
    saved = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    saved["movements"] += [{"id": f"SPLIT-{i}", "doc": f"OTHER-{i}", "date": DAY,
                            "type": "adjustment", "location": "P", "product": "B", "qty": -0.5}
                           for i in (1, 2)]
    refused = client.put(f"/api/companies/{cid}", headers=h(owner), json={"base_revision": 1, "dataset": saved})
    assert refused.status_code == 403 and "KWD 1.234" in refused.text, refused.text


def test_first_count_materializes_the_saved_opening_without_treating_it_as_a_new_variance():
    data = warehouse(item=0, document=0).model_copy(update={"movements": []})
    owner, counter, cid = team(data)
    args = open_count(counter, cid, counts(B=9))
    live = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    assert live["dataset"]["inventory_docs"][0]["items"][0]["book_qty"] == 10
    assert any(move["type"] == "opening" for move in live["dataset"]["movements"])
    rejected = command(counter, cid, "post", "stock", "count_post", 3, date=DAY, **args)
    assert rejected.status_code == 403 and "exceeds inventory posting limits" in rejected.text


def test_quick_count_observes_limits_and_commits_only_an_accepted_count():
    owner, counter, cid = team(warehouse())
    excessive = command(counter, cid, "quick", "stock", "count", 1, date=DAY, counts=counts(B=8))
    assert excessive.status_code == 403 and "KWD 2.468" in excessive.text, excessive.text
    accepted = command(counter, cid, "quick", "stock", "count", 1, date=DAY, counts=counts(B=9))
    assert accepted.status_code == 200 and accepted.json()["revision"] == 2, accepted.text
    saved = client.get(f"/api/companies/{cid}", headers=h(owner)).json()
    assert [m["qty"] for m in saved["dataset"]["movements"] if m["type"] == "adjustment"] == [-1]


def test_imported_open_counts_require_new_attribution_for_above_limit_posting():
    data = warehouse(item=1233).model_dump(mode="json")
    data["inventory_docs"] = [{"id": "PI-00001", "date": DAY, "items": [
        {"location": "P", "product": "B", "book_qty": 10, "counted": 9, "counted_by": "SOME-OTHER-COMPANY"},
    ]}]
    owner, counter, cid = team(Dataset.model_validate(data))
    saved = client.get(f"/api/companies/{cid}", headers=h(owner)).json()["dataset"]
    assert "counted_by" not in saved["inventory_docs"][0]["items"][0]
    args = {"doc": "PI-00001", "counts": counts(B=9)}
    review = {**args, "review_reason": "Count checked independently"}
    missing = command(owner, cid, "post", "stock", "count_post", 1, date=DAY, **review)
    assert missing.status_code == 403 and "record every quantity" in missing.text
    entered = command(counter, cid, "entry", "stock", "count_enter", 1, date=DAY, **args)
    assert entered.status_code == 200 and entered.json()["revision"] == 2
    posted = command(owner, cid, "post", "stock", "count_post", 2, date=DAY, **review)
    assert posted.status_code == 200 and posted.json()["revision"] == 3
