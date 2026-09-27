"""Phase S (N77): planning calls name the company kept on the server and send only what changed since its save;
the answers are the same as with the company sent whole, and a change comes back as what changed."""
from __future__ import annotations

import hashlib

import pytest

from scp.api import working
from scp.companies.patch import apply_patch, make_patch

from .test_companies import client, example, h, new_company, signup


@pytest.fixture(autouse=True)
def _fresh():
    working.forget()
    yield
    working.forget()


def ref(revision: int, patch: dict | None = None) -> dict:
    return {"$ref": {"revision": revision, **({"patch": patch} if patch else {})}}


def company(email: str = "asha@ref.example") -> tuple[str, str, dict, int]:
    tok = signup(email)
    doc = example()
    cid = new_company(tok, doc)
    rev = client.get(f"/api/companies/{cid}", headers=h(tok)).json()["meta"]["revision"]
    return tok, cid, doc, rev


def fp(ds) -> str:
    return hashlib.sha256(ds.model_dump_json().encode()).hexdigest()


def test_a_plan_of_the_kept_company_is_the_plan_of_the_company_sent_whole():
    tok, cid, doc, rev = company()
    whole = client.post("/api/plan", json=doc).json()
    by_ref = client.post("/api/plan", json=ref(rev), headers=h(tok, cid))
    assert by_ref.status_code == 200, by_ref.text
    assert by_ref.json() == whole
    # with unsaved changes: what changed goes along, and the answer is the changed company's
    changed = {**doc, "demand": [{**doc["demand"][0], "qty": doc["demand"][0]["qty"] + 50}, *doc["demand"][1:]]}
    patch = make_patch(doc, changed)
    assert len(str(patch)) < len(str(doc)) / 20
    assert client.post("/api/plan", json=ref(rev, patch), headers=h(tok, cid)).json() == client.post("/api/plan", json=changed).json()
    # in a request's dataset field too
    a = client.post("/api/actuals", json={"dataset": ref(rev)}, headers=h(tok, cid)).json()
    assert a == client.post("/api/actuals", json={"dataset": doc}).json()


def test_the_checks_of_the_kept_company_point_at_the_senders_records():
    tok, cid, doc, rev = company("ravi@ref.example")
    unfinished = {**doc, "lanes": [*doc["lanes"], {"id": "LN-NEW", "origin": doc["locations"][0]["id"], "destination": "",
                                                    "modes": []}]}
    whole = client.post("/api/validate", json=unfinished).json()
    by_ref = client.post("/api/validate", json=ref(rev, make_patch(doc, unfinished)), headers=h(tok, cid)).json()
    assert by_ref == whole
    assert [a["index"] for a in by_ref["set_aside"]] == [len(doc["lanes"])]
    assert client.post("/api/network", json=ref(rev), headers=h(tok, cid)).json() == client.post("/api/network", json=doc).json()


def test_only_a_member_names_the_company_and_the_changes_must_fit():
    tok, cid, doc, rev = company("meera@ref.example")
    other = signup("stranger@ref.example")
    assert client.post("/api/plan", json=ref(rev), headers=h(other, cid)).status_code == 404   # not even told it exists
    assert client.post("/api/plan", json=ref(rev), headers=h(tok)).status_code == 422
    unfit = {"v": 1, "lists": {"products": {"remove": [["NO-SUCH-PRODUCT"]]}}, "sizes": {}}
    r = client.post("/api/plan", json=ref(rev, unfit), headers=h(tok, cid))
    assert r.status_code == 409 and r.json()["patch"] == "unfit"


def test_a_change_to_the_kept_company_comes_back_as_what_changed():
    tok, cid, doc, rev = company("dev@ref.example")
    whole = client.post("/api/orders/firm", json={"dataset": doc, "within_days": 60}).json()
    by_ref = client.post("/api/orders/firm", json={"dataset": ref(rev), "within_days": 60}, headers=h(tok, cid))
    assert by_ref.status_code == 200, by_ref.text
    out = by_ref.json()
    assert out["dataset"] is None and out["report"] == whole["report"] and whole["report"]["firmed"]
    after = apply_patch(doc, {**out["patch"], "sizes": {}})
    assert after == whole["dataset"]
    assert len(str(out["patch"])) < len(str(whole["dataset"])) / 5


def test_changes_never_touch_the_kept_company_and_come_back_as_made():
    """The company read for one call is handed to the next: a change must make a new one, never edit it."""
    tok, cid, doc, rev = company("lena@ref.example")
    hd = h(tok, cid)
    client.post("/api/plan", json=ref(rev), headers=hd)
    r = next(iter(working._kept.values()))
    before = fp(r.ds)
    order = {**doc["demand"][0], "id": None, "kind": "sales_order", "qty": 3}
    calls = [
        ("/api/forecast/release", {}), ("/api/inventory/apply", {}), ("/api/sop/release", None),
        ("/api/schedule/apply", {}), ("/api/promise/commit", {"mode": "entry"}), ("/api/orders/firm", {"within_days": 60}),
        ("/api/purchasing/create", {}), ("/api/actuals/roll", {"as_of": doc["settings"]["planning_start"]}),
        ("/api/orders/sales", {"action": "accept", "order": order}),
        ("/api/actuals/post", {"action": "count", "counts": [{"location": doc["location_products"][0]["location"],
                                                              "product": doc["location_products"][0]["product"], "qty": 7}]}),
    ]
    done: list[str] = []
    for path, extra in calls:
        body = ref(rev) if extra is None else {"dataset": ref(rev), **extra}
        res = client.post(path, json=body, headers=hd)
        assert res.status_code in (200, 409), (path, res.text)
        assert fp(r.ds) == before, path
        # and the change that comes back is the change made to the company sent whole
        whole = client.post(path, json=doc if extra is None else {"dataset": doc, **extra})
        assert whole.status_code == res.status_code, path
        if res.status_code == 200:
            got, want = res.json(), whole.json()
            assert apply_patch(doc, {**got.pop("patch"), "sizes": {}}) == want.pop("dataset"), path
            assert {k: v for k, v in got.items() if k != "dataset"} == {k: v for k, v in want.items() if k != "patch"}, path
            done.append(path)
    assert len(done) >= 8, done


def test_the_same_call_on_the_same_data_is_answered_from_what_was_kept(monkeypatch):
    import scp.api.app as api_app
    tok, cid, doc, rev = company("kim@ref.example")
    made: list[int] = []
    real = api_app.run_forecast
    monkeypatch.setattr(api_app, "run_forecast", lambda ds: made.append(1) or real(ds))
    first = client.post("/api/forecast", json=ref(rev), headers=h(tok, cid))
    again = client.post("/api/forecast", json=ref(rev), headers=h(tok, cid))
    assert first.status_code == 200 and again.json() == first.json() and len(made) == 1
    assert first.headers.get("content-encoding") == "gzip"          # large answers travel compressed
    assert client.post("/api/forecast", json=doc).json() == first.json()
    assert len(made) == 2                                            # the company sent whole: worked out
    # other data (an unsaved change): worked out again
    changed = {**doc, "history": doc["history"][:-1]}
    client.post("/api/forecast", json=ref(rev, make_patch(doc, changed)), headers=h(tok, cid))
    assert len(made) == 3
    # the answer depends on what is asked: another date for the actuals is another answer
    a = client.post("/api/actuals", json={"dataset": ref(rev)}, headers=h(tok, cid)).json()
    b = client.post("/api/actuals", json={"dataset": ref(rev), "as_of": "2027-01-04"}, headers=h(tok, cid)).json()
    assert a != b


def unpack_rows(x):
    """What the browser does with an answer sent as rows (web/src/api/client.ts)."""
    if isinstance(x, list):
        return [unpack_rows(i) for i in x]
    if isinstance(x, dict):
        if set(x) == {"$cols", "$rows"}:
            return [{c: unpack_rows(v) for c, v in zip(x["$cols"], row, strict=True)} for row in x["$rows"]]
        return {k: unpack_rows(v) for k, v in x.items()}
    return x


def test_a_lean_plan_leaves_the_pegging_to_be_asked_for_by_order_or_product(monkeypatch):
    monkeypatch.setattr(working, "ROWS_FROM", 0)
    tok, cid, doc, rev = company("tara@ref.example")
    full = client.post("/api/plan", json=doc).json()
    lean = client.post("/api/plan?pegging=false", json=ref(rev), headers={**h(tok, cid), "X-Pack": "rows"})
    assert lean.headers.get("x-rows") == "1"
    got = unpack_rows(lean.json())
    assert "requirements" not in got and "pegs" not in got
    assert got == {k: v for k, v in full.items() if k not in ("requirements", "pegs")}
    # one product at one place: its requirements, in plan order, and what covers them
    r0 = full["requirements"][0]
    at = client.post("/api/plan/trace", json={"dataset": ref(rev), "location": r0["location"], "product": r0["product"]},
                     headers=h(tok, cid)).json()
    want = [r for r in full["requirements"] if (r["location"], r["product"]) == (r0["location"], r0["product"])]
    assert at["requirements"] == want
    ids = {r["id"] for r in want}
    assert sorted(map(str, at["pegs"])) == sorted(str(p) for p in full["pegs"] if p["requirement_id"] in ids)
    # an order: what it serves and what it depends on, both ways
    made = next(o for o in full["orders"] if o["kind"] == "make" and any(r["parent_order"] == o["id"] for r in full["requirements"]))
    tr = client.post("/api/plan/trace", json={"dataset": ref(rev), "order": made["id"]}, headers=h(tok, cid)).json()
    got_pegs = [str(p) for p in tr["pegs"]]
    assert all(str(p) in got_pegs for p in full["pegs"] if p["supply_id"] == made["id"])
    needs = [r for r in full["requirements"] if r["parent_order"] == made["id"]]
    assert needs and all(r in tr["requirements"] for r in needs)
    assert all(str(p) in got_pegs for p in full["pegs"] if p["requirement_id"] in {r["id"] for r in needs})
    assert len(tr["pegs"]) < len(full["pegs"])


def test_unsaved_changes_are_read_on_the_kept_save_and_share_the_rest():
    tok, cid, doc, rev = company("omar@ref.example")
    hd = h(tok, cid)
    client.post("/api/validate", json=ref(rev), headers=hd)                      # the save, read and kept
    base = working._kept[(cid, rev, "")]
    changed = {**doc, "demand": [{**doc["demand"][0], "qty": doc["demand"][0]["qty"] + 9}, *doc["demand"][1:]]}
    patch = make_patch(doc, changed)
    got = client.post("/api/validate", json=ref(rev, patch), headers=hd).json()
    edited = next(r for k, r in working._kept.items() if k[0] == cid and k[2])
    assert edited.ds.history is base.ds.history and edited.ds.products is base.ds.products   # shared, not read again
    assert edited.ds.demand is not base.ds.demand and edited.ds.demand[0].qty == doc["demand"][0]["qty"] + 9
    assert got == client.post("/api/validate", json=changed).json()
    assert client.post("/api/plan", json=ref(rev, patch), headers=hd).json() == client.post("/api/plan", json=changed).json()
    # a record that would be set aside: the company is read whole, and the record is set aside as ever
    working.forget()
    client.post("/api/validate", json=ref(rev), headers=hd)
    unfinished = {**doc, "lanes": [*doc["lanes"], {"id": "LN-NEW", "origin": doc["locations"][0]["id"], "destination": "", "modes": []}]}
    got = client.post("/api/validate", json=ref(rev, make_patch(doc, unfinished)), headers=hd).json()
    assert got == client.post("/api/validate", json=unfinished).json() and got["set_aside"]
