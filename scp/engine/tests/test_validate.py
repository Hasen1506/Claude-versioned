"""Readiness gate: every rule fires on a minimal defect and stays silent on the clean dataset."""
import pytest

from scp.validate import RULES, has_errors, validate

from .factory import base, demand, ds, load_example, lp


def clean() -> dict:
    d = base()
    d["demand"] = [demand("P", "A", "2026-01-12", 30), demand("P", "A", "2026-01-19", 20)]
    return d


def test_clean_dataset_has_no_issues():
    assert validate(ds(clean())) == []


@pytest.mark.parametrize("name", ["kitchenware_network", "single_product_plant"])
def test_examples_are_clean(name):
    issues = validate(load_example(name))
    assert [i for i in issues] == []


# --- one minimal defect per rule --------------------------------------------------------------
def _dup_id(d):
    d["products"].append({"id": "A", "type": "RM"})


def _dup_lp(d):
    d["location_products"].append({"location": "P", "product": "A"})


def _ref_unknown(d):
    d["production_sources"][0]["components"].append({"product": "ZZZ", "qty": 1})


def _ref_wrong_type(d):
    d["purchasing_sources"][0]["supplier"] = "P"


def _fx_missing(d):
    d["purchasing_sources"][0]["currency"] = "USD"


def _calendar(d):
    d["settings"]["horizon_days"] = 7
    d["calendars"][0] = {"id": "CAL", "workdays": [0], "holidays": ["2026-01-05"]}


def _cycle(d):
    d["locations"].append({"id": "Q", "type": "plant"})
    d["lanes"] = [{"id": "PQ", "origin": "P", "destination": "Q", "products": ["A"], "modes": [{"transit_days": 1}]},
                  {"id": "QP", "origin": "Q", "destination": "P", "products": ["A"], "modes": [{"transit_days": 1}]}]
    d["demand"].append(demand("Q", "A", "2026-01-12", 5))


def _no_source(d):
    d["locations"].append({"id": "D", "type": "dc"})
    d["location_products"].append({"location": "D", "product": "B", "on_hand": 3})
    d["demand"].append(demand("D", "B", "2026-01-12", 5))


def _lane_weight(d):
    d["locations"].append({"id": "D", "type": "dc"})
    d["lanes"] = [{"id": "PD", "origin": "P", "destination": "D", "products": ["A"],
                   "modes": [{"transit_days": 1, "cost_per_kg": 2}]}]
    d["demand"].append(demand("D", "A", "2026-01-12", 5))
    d["location_products"].append({"location": "D", "product": "A"})


def _resource_location(d):
    d["locations"].append({"id": "Q", "type": "plant"})
    d["resources"].append({"id": "M2", "location": "Q"})
    d["production_sources"][0]["operations"][0]["resource"] = "M2"
    d["resources"][0]["location"] = "P"
    d["production_sources"].append({"id": "PV-Q", "location": "Q", "product": "A", "priority": 9,
                                    "operations": [{"seq": 10, "resource": "M1"}], "fixed_lead_time_workdays": 1})


def _ss_no_var(d):
    lp(d, "P", "A")["safety_stock"] = {"method": "service_level", "service_level": 0.95}


def _validity(d):
    d["purchasing_sources"][0]["valid_to"] = "2026-01-15"


def _no_ops(d):
    ps = d["production_sources"][0]
    ps["operations"] = []
    ps.pop("fixed_lead_time_workdays")


def _zero_lt(d):
    d["purchasing_sources"][1]["lead_time_days"] = 0


def _ss_and_time(d):
    x = lp(d, "P", "A")
    x["safety_stock"] = {"method": "fixed", "qty": 5}
    x["safety_time_days"] = 2


def _quota(d):
    d["locations"].append({"id": "S2", "type": "supplier"})
    d["purchasing_sources"][0]["quota"] = 0.5
    d["purchasing_sources"].append({"id": "PIR-B2", "supplier": "S2", "product": "B", "location": "P", "price": 11,
                                    "lead_time_days": 3, "quota": 0.3})


def _outside(d):
    d["demand"].append(demand("P", "A", "2026-06-01", 5))


def _past(d):
    d["demand"].append(demand("P", "A", "2025-12-20", 5))


def _mto_fc(d):
    lp(d, "P", "A")["strategy"] = "MTO"


def _stock_at_customer(d):
    d["locations"].append({"id": "K", "type": "customer"})
    d["location_products"].append({"location": "K", "product": "A", "on_hand": 5})


def _unused(d):
    d["resources"].append({"id": "M9", "location": "P"})


def _defaulted(d):
    d["location_products"] = [x for x in d["location_products"] if x["product"] != "C"]


def _shelf(d):
    d["products"][1]["shelf_life_days"] = 2


def _history_late(d):
    d["history"] = [{"location": "P", "product": "A", "date": "2026-01-06", "qty": 4}]


def _npi_like(d):
    d["npi"] = [{"location": "P", "product": "C", "like_product": "A", "launch_date": "2026-01-12"}]


def _npi_dup(d):
    d["history"] = [{"location": "P", "product": "A", "date": "2025-12-01", "qty": 4}]
    rule = {"location": "P", "product": "C", "like_product": "A", "launch_date": "2026-01-12"}
    d["npi"] = [rule, dict(rule, scale=0.5)]


def _override_outside(d):
    d["overrides"] = [{"location": "P", "product": "A", "date": "2027-01-01", "qty": 5}]


def _override_no_fc(d):
    d["overrides"] = [{"location": "P", "product": "A", "date": "2026-01-12", "change": 0.1}]


MUTATORS = {
    "DUP_ID": _dup_id, "DUP_LOCATION_PRODUCT": _dup_lp, "REF_UNKNOWN": _ref_unknown,
    "REF_WRONG_TYPE": _ref_wrong_type, "FX_MISSING": _fx_missing, "CALENDAR_NO_WORKDAY_IN_HORIZON": _calendar,
    "BOM_CYCLE": _cycle, "NO_SOURCE": _no_source, "LANE_WEIGHT_MISSING": _lane_weight,
    "RESOURCE_WRONG_LOCATION": _resource_location, "SS_NO_VARIABILITY": _ss_no_var,
    "SOURCE_NOT_VALID_IN_HORIZON": _validity, "PRODUCTION_NO_OPERATIONS": _no_ops,
    "PRODUCTION_NO_LEAD_TIME": _no_ops, "PURCHASE_ZERO_LEAD_TIME": _zero_lt, "SS_AND_SAFETY_TIME": _ss_and_time,
    "QUOTA_SUM": _quota, "DEMAND_OUTSIDE_HORIZON": _outside, "DEMAND_PAST_DUE": _past,
    "MTO_WITH_FORECAST": _mto_fc, "STOCK_AT_CUSTOMER": _stock_at_customer, "RESOURCE_UNUSED": _unused,
    "LOCATION_PRODUCT_DEFAULTED": _defaulted, "SHELF_LIFE_VS_LEAD_TIME": _shelf,
    "HISTORY_AFTER_START": _history_late, "NPI_LIKE_WITHOUT_HISTORY": _npi_like, "NPI_DUPLICATE": _npi_dup,
    "OVERRIDE_OUTSIDE_HORIZON": _override_outside, "OVERRIDE_WITHOUT_FORECAST": _override_no_fc,
}


def test_every_rule_has_a_test():
    assert set(MUTATORS) == set(RULES)


@pytest.mark.parametrize("code", sorted(MUTATORS))
def test_rule_fires(code):
    d = clean()
    MUTATORS[code](d)
    issues = validate(ds(d))
    fired = [i for i in issues if i.code == code]
    assert fired, f"{code} did not fire; got {[i.code for i in issues]}"
    assert all(i.severity == RULES[code][0] for i in fired)
    assert has_errors(issues) == any(i.severity == "error" for i in issues)
