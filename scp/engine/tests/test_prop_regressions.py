"""Regression tests for the bugs the property-based and differential suite found (TS-01 …), each the smallest
example Hypothesis shrank to: each fails on main at e40f35d and passes with the fix in the same PR."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from scp.actuals import PostingError, post
from scp.api.app import WEB_DIST, app
from scp.connect import imports
from scp.model import Dataset, NegativeStock
from scp.plan import run_mrp

from .factory import ds
from .strategies import network
from .test_stock import plant

client = TestClient(app, raise_server_exceptions=False)


# ---- TS-01: replenish-to-max splits lots off the rounding value -----------------------------------------------------
def test_ts01_replenish_to_max_split_stays_on_the_rounding_value():
    """MIN_MAX with a maximum lot of 35 and lots in tens: the plan made a lot of 35 (not a multiple of 10). The CV-M02
    fix covered apply_modifiers' own rounding, but the replenish-to-max path called it with no rounding at all."""
    lot = {"policy": "MIN_MAX", "max_qty": 35.0, "rounding_qty": 10.0}
    d = network(0, {p: lot for p in ("RM0", "RM1", "RM2", "RM3", "RM4", "SF0", "SF1", "FG0", "FG1", "FG2")})
    r = run_mrp(Dataset.model_validate(d))
    assert r.ok
    made = [o for o in r.orders if o.kind in ("buy", "make")]
    assert made and all(o.qty % 10 == 0 and o.qty <= 30 for o in made), [(o.id, o.qty) for o in made if o.qty % 10]


# ---- TS-02: a back-dated posting takes a later day of the journal below zero under "refuse" --------------------------
def test_ts02_refuse_checks_every_later_day_of_the_journal():
    x = ds(plant())
    x = x.model_copy(update={"execution": x.execution.model_copy(update={"negative_stock": NegativeStock.REFUSE})})
    x, _ = post(x, "receive", order="PO-00001", on=date(2026, 1, 1))              # 100 of B in batch 260101-1
    x, _ = post(x, "scrap", location="P", product="B", on=date(2026, 1, 2))       # all 100 scrapped on the 2nd
    with pytest.raises(PostingError, match="below zero"):
        # scrapping the same 100 again, dated the 1st: on the 1st they are there, but the 2nd would go to -100
        post(x, "scrap", location="P", product="B", on=date(2026, 1, 1))


def test_ts02_allow_still_posts_and_says_so():
    x = ds(plant())
    x, _ = post(x, "receive", order="PO-00001", on=date(2026, 1, 1))
    x, _ = post(x, "scrap", location="P", product="B", on=date(2026, 1, 2))
    _, rep = post(x, "scrap", location="P", product="B", on=date(2026, 1, 1))
    assert "goes to -100" in rep.message


# ---- TS-03: a CSV with a lone carriage return crashes the import instead of being refused ---------------------------
@pytest.mark.parametrize("raw", [b"\r\x00", b"number,qty\rSO-1,5\r", b'a,"b\rc'])
def test_ts03_an_unreadable_csv_is_refused_not_crashed_on(raw):
    try:
        items = imports.parse("orders", "csv", raw)
    except ValueError as e:                      # refused in words, like any unreadable file
        assert "CSV" in str(e)
    else:
        assert isinstance(items, list)


# ---- TS-04 / TS-05: path names too long for the file system answer 500 -----------------------------------------------
def test_ts04_an_example_name_too_long_is_not_found_not_a_server_error():
    assert client.get("/api/examples/" + "x" * 300).status_code == 404
    assert client.get("/api/examples/kitchenware_network").status_code == 200


@pytest.mark.skipif(not WEB_DIST.is_dir(), reason="the single-page app is only mounted when the web client is built")
@pytest.mark.parametrize("path", ["/" + "x" * 300, "/a/" + "x" * 5000, "/%00"], ids=["long", "deep", "nul"])
def test_ts05_the_app_page_answers_any_path(path):
    assert client.get(path).status_code == 200
