"""Tiny dataset builders for tests. Every builder returns a plain dict so tests can mutate it
before validation, exactly as a user editing JSON would."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from scp.model import Dataset

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
START = "2026-01-05"  # Monday


def load_example(name: str) -> Dataset:
    return Dataset.model_validate_json((EXAMPLES / f"{name}.json").read_text())


def example_dict(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def ds(d: dict) -> Dataset:
    return Dataset.model_validate(copy.deepcopy(d))


def base(horizon: int = 28, bucket: str = "week", workdays: list[int] | None = None) -> dict:
    """Plant P (7-day calendar unless ``workdays`` given), product A made from 2×B + 1×C,
    B and C bought from supplier S. No demand yet."""
    return {
        "settings": {"planning_start": START, "horizon_days": horizon, "bucket": bucket, "default_calendar": "CAL",
                     "wacc": 0.1, "holding_spread": 0.1},
        "calendars": [{"id": "CAL", "workdays": workdays if workdays is not None else [0, 1, 2, 3, 4, 5, 6]}],
        "locations": [{"id": "P", "type": "plant"}, {"id": "S", "type": "supplier"}],
        "products": [{"id": "A", "type": "FG"}, {"id": "B", "type": "RM"}, {"id": "C", "type": "RM"}],
        "location_products": [
            {"location": "P", "product": "A", "on_hand": 10},
            {"location": "P", "product": "B", "on_hand": 30, "lot_sizing": {"policy": "FIXED", "fixed_qty": 50}},
            {"location": "P", "product": "C", "on_hand": 0},
        ],
        "resources": [{"id": "M1", "location": "P", "efficiency": 1.0, "hours_per_shift": 8, "cost_per_hour": 100}],
        "production_sources": [{"id": "PV-A", "location": "P", "product": "A", "fixed_lead_time_workdays": 2,
                                "components": [{"product": "B", "qty": 2}, {"product": "C", "qty": 1}],
                                "operations": [{"seq": 10, "resource": "M1", "setup_hours": 2,
                                                "run_hours_per_unit": 0.5}]}],
        "purchasing_sources": [
            {"id": "PIR-B", "supplier": "S", "product": "B", "location": "P", "price": 10, "lead_time_days": 3},
            {"id": "PIR-C", "supplier": "S", "product": "C", "location": "P", "price": 5, "lead_time_days": 1},
        ],
        "lanes": [],
        "demand": [],
        "receipts": [],
    }


def demand(loc: str, prod: str, day: str, qty: float, kind: str = "forecast", **kw) -> dict:
    return {"location": loc, "product": prod, "date": day, "qty": qty, "kind": kind, **kw}


def lp(d: dict, loc: str, prod: str) -> dict:
    for x in d["location_products"]:
        if x["location"] == loc and x["product"] == prod:
            return x
    x = {"location": loc, "product": prod}
    d["location_products"].append(x)
    return x
