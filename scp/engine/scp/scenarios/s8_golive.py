"""S8 · Crescent Preserves: the go-live readiness gate.

A jam maker's first upload of master data, with the mistakes real uploads contain: a typo'd product on a
sales order, a duplicated planning record, a return lane that makes supply flow in a circle, a currency
without a rate, a stock take that disagrees with the journal, a calendar with no working day… Each
mistake is planted once, so the gate's findings are known exactly. Then the planner works the list:
demand planning unblocks as soon as its own inputs are clean, supply planning once the errors are gone,
and the warnings that remain are the ones the business chose to accept.
"""
from __future__ import annotations

import datetime as dt
import json

from ..model import Dataset
from ..validate import RULES, blocks_demand
from .harness import Client, Ctx, Scenario, d

START = d("2026-07-06")
DAYS = 28


def build() -> dict:
    hist = [{"location": "CUST", "product": "JAM", "date": (START - dt.timedelta(weeks=w)).isoformat(), "qty": 90}
            for w in range(1, 11)]
    return {
        "settings": {"company_name": "Crescent Preserves", "currency": "GBP", "planning_start": START.isoformat(),
                     "horizon_days": DAYS, "bucket": "week"},
        "calendars": [{"id": "SHUTDOWN", "name": "Summer shutdown", "workdays": [0, 1, 2, 3, 4],
                       "holidays": [(START + dt.timedelta(days=i)).isoformat() for i in range(DAYS)]}],
        "locations": [
            {"id": "PLANT", "name": "Preserving kitchen", "type": "plant"},
            {"id": "COPACK", "name": "Co-packer", "type": "plant"},
            {"id": "DC", "name": "Distribution centre", "type": "dc"},
            {"id": "CUST", "name": "Grocery chain", "type": "customer"},
            {"id": "SUP-F", "name": "Fruit farm (US)", "type": "supplier"},
            {"id": "SUP-J", "name": "Jar & sugar merchant", "type": "supplier"},
        ],
        "products": [
            {"id": "JAM", "name": "Strawberry jam", "type": "FG", "weight_kg": 0.45, "price": 4},
            {"id": "GIFT", "name": "Gift box", "type": "FG", "price": 20},                     # no weight
            {"id": "FRUIT", "name": "Strawberries", "type": "RM", "weight_kg": 1, "shelf_life_days": 5},
            {"id": "JAR", "name": "Jar and lid", "type": "PKG", "weight_kg": 0.2},
            {"id": "SUGAR", "name": "Sugar", "type": "RM", "weight_kg": 1},
            {"id": "LABEL", "name": "Label", "type": "PKG"},
        ],
        "location_products": [
            {"location": "PLANT", "product": "JAM", "safety_stock": {"method": "fixed", "qty": 100},
             "safety_time_days": 2},
            {"location": "PLANT", "product": "FRUIT", "on_hand": 250,
             "safety_stock": {"method": "service_level", "service_level": 0.95}},
            {"location": "PLANT", "product": "SUGAR"},
            {"location": "DC", "product": "JAM", "on_hand": 40},
            {"location": "DC", "product": "JAM", "on_hand": 50, "strategy": "MTO"},              # maintained twice
            {"location": "DC", "product": "GIFT"},
            {"location": "CUST", "product": "JAM", "on_hand": 20},
            {"location": "PLANT", "product": "LABEL", "strategy": "MTO"},
        ],
        "resources": [
            {"id": "KETTLE", "location": "PLANT"}, {"id": "KETTLE", "location": "PLANT", "units": 2},
            {"id": "FILLER-2", "location": "COPACK"}, {"id": "OLD-OVEN", "location": "PLANT"},
        ],
        "production_sources": [
            {"id": "PV-JAM", "location": "PLANT", "product": "JAM",
             "components": [{"product": "FRUIT", "qty": 0.6}, {"product": "JAR", "qty": 1}, {"product": "SUGAR", "qty": 0.4}],
             "operations": [{"seq": 10, "resource": "KETTLE", "run_hours_per_unit": 0.002},
                            {"seq": 20, "resource": "FILLER-2", "run_hours_per_unit": 0.001}]},
            {"id": "PV-LABEL", "location": "PLANT", "product": "LABEL"},
        ],
        "purchasing_sources": [
            {"id": "PU-FRUIT", "supplier": "SUP-F", "product": "FRUIT", "location": "PLANT", "price": 2,
             "currency": "USD", "lead_time_days": 7},
            {"id": "PU-JAR", "supplier": "SUP-J", "product": "JAR", "location": "PLANT", "price": 0.3,
             "lead_time_days": 5, "valid_to": (START + dt.timedelta(days=14)).isoformat()},
            {"id": "PU-SUGAR", "supplier": "SUP-J", "product": "SUGAR", "location": "PLANT", "price": 0.8,
             "lead_time_days": 0, "quota": 0.5},
            {"id": "PU-SUGAR-2", "supplier": "SUP-F", "product": "SUGAR", "location": "PLANT", "price": 0.7,
             "lead_time_days": 3, "quota": 0.3},
        ],
        "lanes": [
            {"id": "L-PD", "origin": "PLANT", "destination": "DC", "products": ["JAM"], "modes": [{"transit_days": 2}]},
            {"id": "L-DC", "origin": "DC", "destination": "CUST", "modes": [{"transit_days": 1, "cost_per_kg": 0.05}]},
            {"id": "L-BACK", "origin": "DC", "destination": "PLANT", "products": ["JAM"], "modes": [{"transit_days": 2}]},
        ],
        "demand": [
            *[{"location": "CUST", "product": p, "date": (START + dt.timedelta(weeks=w)).isoformat(), "qty": q,
               "period_days": 7} for w in range(4) for p, q in (("JAM", 90), ("GIFT", 10))],
            {"location": "DC", "product": "JAM", "date": START.isoformat(), "qty": 15},        # trade counter
            {"location": "PLANT", "product": "LABEL", "date": START.isoformat(), "qty": 500},  # spare labels, MTO
            {"id": "SO-9", "location": "CUST", "product": "JAM-XL", "date": "2026-07-09", "qty": 12, "kind": "sales_order"},
            {"id": "SO-OLD", "location": "CUST", "product": "JAM", "date": "2026-07-01", "qty": 8, "kind": "sales_order"},
            {"id": "FC-FAR", "location": "CUST", "product": "JAM", "date": "2026-09-07", "qty": 90},
        ],
        "history": [*hist, {"location": "CUST", "product": "JAM", "date": START.isoformat(), "qty": 95}],
        "npi": [{"location": "CUST", "product": "GIFT", "like_product": "FRUIT", "launch_date": START.isoformat()},
                {"location": "CUST", "product": "GIFT", "like_product": "JAM", "scale": 0.1,
                 "launch_date": START.isoformat()}],
        "overrides": [{"location": "CUST", "product": "JAM", "date": "2026-09-01", "qty": 120},
                      {"location": "DC", "product": "JAM", "date": "2026-07-15", "qty": 30}],
        "confirmations": [{"order": "SO-GONE", "ship_from": "DC", "ship_date": "2026-07-07", "date": "2026-07-08",
                           "qty": 5}],
        "receipts": [{"id": "PO-77", "kind": "purchase", "location": "CUST", "product": "JAM", "qty": 10,
                      "due_date": "2026-07-10"}],
        "movements": [
            {"id": "GM-1", "date": "2026-07-01", "type": "opening", "location": "PLANT", "product": "FRUIT", "qty": 300},
            {"id": "GM-2", "date": "2026-07-02", "type": "issue", "location": "PLANT", "product": "JAR", "qty": 50,
             "reference": "PRD-404"},
        ],
    }


ERRORS = {
    ("BOM_CYCLE", "network", "DC"): "L-BACK returns jam from the DC to the kitchen, which ships it to the DC.",
    ("CALENDAR_NO_WORKDAY_IN_HORIZON", "calendar", "SHUTDOWN"): "Every day of the horizon is a holiday.",
    ("DUP_ID", "resource", "KETTLE"): "Two resources are called KETTLE.",
    ("DUP_LOCATION_PRODUCT", "location_product", "DC/JAM"): "Jam at the DC is maintained twice.",
    ("FX_MISSING", "purchasing_source", "PU-FRUIT"): "Fruit is priced in USD and there is no USD rate.",
    ("LANE_WEIGHT_MISSING", "product", "GIFT"): "L-DC is costed per kg and the gift box has no weight.",
    ("NO_SOURCE", "location_product", "DC/GIFT"): "Gift boxes are sold from the DC; nothing supplies the DC.",
    ("REF_UNKNOWN", "demand", "SO-9"): "SO-9 is for JAM-XL, which does not exist.",
    ("REF_WRONG_TYPE", "receipt", "PO-77"): "A purchase order is due at the customer.",
    ("RESOURCE_WRONG_LOCATION", "production_source", "PV-JAM"): "The kitchen's routing uses the co-packer's filler.",
    ("SS_NO_VARIABILITY", "location_product", "PLANT/FRUIT"): "A service-level policy with no demand CV.",
}
WARNINGS = {
    ("CONFIRMATION_ORPHAN", "confirmation", "#0"), ("DEMAND_OUTSIDE_HORIZON", "demand", "*"),
    ("DEMAND_PAST_DUE", "demand", "*"), ("HISTORY_AFTER_START", "history", "*"),
    ("LOCATION_PRODUCT_DEFAULTED", "location_product", "PLANT/JAR"), ("MOVEMENT_REF_UNKNOWN", "movement", "GM-2"),
    ("MTO_WITH_FORECAST", "location_product", "PLANT/LABEL"), ("NEGATIVE_STOCK", "location_product", "PLANT/JAR"),
    ("NPI_DUPLICATE", "npi", "CUST/GIFT"), ("NPI_LIKE_WITHOUT_HISTORY", "npi", "CUST/GIFT"),
    ("OVERRIDE_OUTSIDE_HORIZON", "override", "CUST/JAM@2026-09-01"),
    ("OVERRIDE_WITHOUT_FORECAST", "override", "DC/JAM@2026-07-15"),
    ("PRODUCTION_NO_LEAD_TIME", "production_source", "PV-LABEL"),
    ("PRODUCTION_NO_OPERATIONS", "production_source", "PV-LABEL"),
    ("PURCHASE_ZERO_LEAD_TIME", "purchasing_source", "PU-SUGAR"), ("QUOTA_SUM", "location_product", "PLANT/SUGAR"),
    ("RESOURCE_UNUSED", "resource", "OLD-OVEN"), ("SHELF_LIFE_VS_LEAD_TIME", "location_product", "PLANT/FRUIT"),
    ("SOURCE_NOT_VALID_IN_HORIZON", "purchasing_source", "PU-JAR"),
    ("SS_AND_SAFETY_TIME", "location_product", "PLANT/JAM"), ("STOCK_AT_CUSTOMER", "location_product", "CUST/JAM"),
    ("STOCK_NOT_SYNCED", "location_product", "PLANT/FRUIT"),
}


def _found(issues: list, severity: str) -> set[tuple[str, str, str]]:
    return {(i.code, i.object_type, i.object_id) for i in issues if i.severity == severity}


def _edit(ds: Dataset, fn) -> Dataset:
    raw = json.loads(ds.model_dump_json())
    fn(raw)
    return Dataset.model_validate(raw)


def _fix_demand(raw: dict) -> None:
    next(x for x in raw["demand"] if x.get("id") == "SO-9")["product"] = "JAM"


def _fix_supply(raw: dict) -> None:
    raw["lanes"] = [ln for ln in raw["lanes"] if ln["id"] != "L-BACK"]
    raw["calendars"][0]["holidays"] = []
    raw["resources"] = [r for r in raw["resources"] if not (r["id"] == "KETTLE" and r["units"] == 2)]
    raw["location_products"] = [lp for lp in raw["location_products"]
                                if not (lp["location"] == "DC" and lp["product"] == "JAM" and lp["on_hand"] == 50)]
    raw["settings"]["fx_rates"] = {"USD": 0.79}
    next(p for p in raw["products"] if p["id"] == "GIFT")["weight_kg"] = 1.2
    raw["production_sources"].append({"id": "PV-GIFT", "location": "PLANT", "product": "GIFT",
                                      "components": [{"product": "JAM", "qty": 3}],
                                      "operations": [{"seq": 10, "resource": "FILLER", "setup_hours": 0.5,
                                                      "run_hours_per_unit": 0.01}]})
    raw["location_products"].append({"location": "PLANT", "product": "GIFT"})
    raw["lanes"][0]["products"] = ["JAM", "GIFT"]
    raw["receipts"][0]["location"] = "DC"
    raw["resources"] = [r for r in raw["resources"] if r["id"] != "FILLER-2"] + [{"id": "FILLER", "location": "PLANT"}]
    raw["production_sources"][0]["operations"][1]["resource"] = "FILLER"
    next(lp for lp in raw["location_products"] if lp["product"] == "FRUIT")["safety_stock"]["demand_cv"] = 0.25


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Upload the master data", "readiness", "POST /api/validate",
                  "Every planted mistake must be found once, on the right object, with the right severity; nothing "
                  "else may be reported."):
        issues = c.validate(ds)
        ctx.eq("errors", sorted(_found(issues, "error")), sorted(ERRORS),
               "One per planted mistake: " + " ".join(ERRORS.values()))
        ctx.eq("warnings", sorted(_found(issues, "warning")), sorted(WARNINGS))
        ctx.true("every finding says what to do", all(i.hint for i in issues),
                 actual=[i.code for i in issues if not i.hint])
        ctx.eq("every readiness rule fires", sorted({i.code for i in issues}), sorted(RULES),
               f"{len(RULES)} rules, one planted mistake each. SO-9's unknown product is reported once: it does not "
               "also become a phantom JAM-XL node 'without a source'.")
        dup = next(i for i in issues if i.code == "DUP_LOCATION_PRODUCT")
        ctx.true("a duplicate says which record is used", "first record is used" in dup.message, actual=dup.message)

    with ctx.step("What the gate blocks", "readiness", "POST /api/forecast, /api/plan",
                  "A broken reference in demand (SO-9) blocks forecasting; any error blocks supply planning."):
        ctx.true("demand planning blocked by its own input", blocks_demand(issues))
        ctx.eq("forecast refused", c.forecast(ds).ok, False)
        ctx.eq("plan refused", c.plan(ds).ok, False)

    with ctx.step("Fix the demand side first", "readiness", "POST /api/forecast",
                  "SO-9 was for JAM. The supply-side errors remain, and forecasting may go ahead anyway."):
        ds = _edit(ds, _fix_demand)
        issues = c.validate(ds)
        ctx.eq("errors left", sorted(_found(issues, "error")),
               sorted(k for k in ERRORS if k[0] != "REF_UNKNOWN"))
        ctx.eq("forecast runs", c.forecast(ds).ok, True)
        ctx.eq("plan still refused", c.plan(ds).ok, False)

    with ctx.step("Fix the supply side", "readiness", "POST /api/validate → POST /api/plan",
                  "Drop the return lane, clear the shutdown holidays, remove the duplicate kettle and DC record, add "
                  "the USD rate, weigh the gift box and pack it at the kitchen, re-address PO-77 to the DC, give the "
                  "kitchen its own filler (retiring the co-packer's) and the fruit a demand CV."):
        ds = _edit(ds, _fix_supply)
        issues = c.validate(ds)
        ctx.eq("no errors", sorted(_found(issues, "error")), [])
        plan = c.plan(ds)
        ctx.eq("the plan runs", plan.ok, True)
        left = sorted(_found(issues, "warning"))
        ctx.eq("warnings the business accepts", left, sorted(WARNINGS),
               "Fixing the errors must not hide a warning: each one is still true and still shown.")


SCENARIO = Scenario(
    id="s8-golive", title="Go-live readiness gate", company="Crescent Preserves",
    story="A first upload of master data with the mistakes real uploads contain, each planted once. The gate must "
          "find every one, exactly once, on the right object; demand planning unblocks when its inputs are clean, "
          "supply planning when the errors are gone.",
    proves=["every readiness rule", "exact findings (no noise, no misses)", "every finding has a remedy",
            "demand-side vs supply-side blocking", "fix, re-validate, plan"],
    stages=["readiness", "demand", "plan"],
    build=build, run=run)
