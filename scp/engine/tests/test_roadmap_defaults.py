"""Roadmap PR C: defaults that were set without being shown become settings (UX audit, section 2)."""
from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from scp.companies import get_companies
from scp.connect import imports
from scp.demand.pipeline import SERVICE_LEVEL, service_level
from scp.model import Dataset

from .factory import base, ds, example_dict
from .test_connections import company, setup


# ---- the ABC-XYZ service-level table ------------------------------------------------------------------------------
def test_the_service_level_table_is_editable_per_cell_and_defaults_to_the_old_table():
    d = base()
    plain = ds(d).forecasting
    assert all(service_level(plain, a, x) == SERVICE_LEVEL[(a, x)] for a, x in SERVICE_LEVEL)
    d["forecasting"] = {"service_levels": {"AX": 0.995, "CZ": 0.85}}
    fs = ds(d).forecasting
    assert service_level(fs, "A", "X") == 0.995 and service_level(fs, "C", "Z") == 0.85
    assert service_level(fs, "B", "Y") == SERVICE_LEVEL[("B", "Y")]


@pytest.mark.parametrize("bad", [{"AQ": 0.9}, {"AX": 1.0}, {"AX": 0.2}])
def test_the_service_level_table_rejects_unknown_cells_and_impossible_levels(bad):
    d = base()
    d["forecasting"] = {"service_levels": bad}
    with pytest.raises(ValidationError):
        ds(d)


def test_the_forecast_suggests_the_companys_own_service_level():
    from scp.demand import run_forecast
    d = example_dict("kitchenware_network")
    own = {f"{a}{x}": 0.5 + 0.01 * i for i, (a, x) in enumerate(SERVICE_LEVEL)}
    d.setdefault("forecasting", {})["service_levels"] = own
    r = run_forecast(ds(d))
    assert r.series and all(s.segment.suggested_service_level == own[f"{s.segment.abc}{s.segment.xyz}"] for s in r.series)


# ---- a per-company time zone for scheduled imports -----------------------------------------------------------------
def test_a_company_time_zone_must_be_a_real_zone():
    d = base()
    d["settings"]["timezone"] = "Asia/Kolkata"
    assert ds(d).settings.timezone == "Asia/Kolkata"
    d["settings"]["timezone"] = "Mars/Olympus"
    with pytest.raises(ValidationError):
        Dataset.model_validate(d)


def test_next_run_uses_the_zone_it_is_given():
    after = dt.datetime(2026, 1, 5, 0, 0, tzinfo=dt.UTC)
    assert imports.next_run("day", "06:00", 0, after, "Asia/Kolkata") == dt.datetime(2026, 1, 5, 0, 30, tzinfo=dt.UTC)
    assert imports.next_run("day", "06:00", 0, after, "UTC") == dt.datetime(2026, 1, 5, 6, 0, tzinfo=dt.UTC)


def test_a_06_00_import_of_a_chennai_company_runs_at_06_00_in_chennai(monkeypatch, tmp_path):
    monkeypatch.delenv("SCP_TIMEZONE", raising=False)
    monkeypatch.setenv("SCP_IMPORT_DIR", str(tmp_path))
    doc = company()
    doc["settings"]["timezone"] = "Asia/Kolkata"
    owner, cid, _ = setup(doc)
    c = get_companies()
    user = c.whoami(owner)
    job = imports.JobInput(name="Stock", kind="stock", source_type="folder", source="stock.csv", at="06:00")
    out = imports.save_job(c, user, cid, job, now=dt.datetime(2026, 1, 5, 0, 0, tzinfo=dt.UTC))
    assert out.timezone == "Asia/Kolkata"
    assert out.jobs[0].next_run.startswith("2026-01-05T00:30")      # 06:00 IST, not 06:00 UTC
