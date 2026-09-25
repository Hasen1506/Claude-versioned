"""Generate the canonical example datasets (deterministic). Run from the repo root:

    python scp/examples/build_examples.py

Both datasets are fictional. They exist to exercise every engine feature and as starting points
in the UI ("Load example"), and they are validated in the engine test suite.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))

from scp.model import Dataset  # noqa: E402

START = date(2026, 9, 28)  # a Monday


def weekly_forecast(loc: str, prod: str, base: float, weeks: int, season: dict[int, float], rng: random.Random,
                    noise: float = 0.08) -> list[dict]:
    out = []
    for w in range(weeks):
        d = START + timedelta(weeks=w)
        f = season.get(d.month, 1.0)
        q = max(0, round(base * f * (1 + rng.uniform(-noise, noise))))
        out.append({"location": loc, "product": prod, "date": d.isoformat(), "qty": q, "kind": "forecast",
                    "period_days": 7})
    return out


def kitchenware() -> dict:
    rng = random.Random(42)
    festive = {10: 1.35, 11: 1.25, 12: 0.95, 1: 0.9, 2: 0.95, 3: 1.05}
    cal = [
        {"id": "CAL-IN-6D", "name": "India Mon–Sat", "workdays": [0, 1, 2, 3, 4, 5],
         "holidays": ["2026-10-02", "2026-10-20", "2026-11-09", "2026-11-10", "2026-12-25", "2027-01-26"]},
    ]
    locations = [
        {"id": "PLT-PUNE", "name": "Pune plant (Chakan)", "type": "plant", "region": "West", "calendar": "CAL-IN-6D",
         "lat": 18.76, "lon": 73.86, "storage_capacity_m3": 2500, "handling_cost_per_unit": 2},
        {"id": "DC-BHIWANDI", "name": "Bhiwandi DC (Mumbai)", "type": "dc", "region": "West", "calendar": "CAL-IN-6D",
         "lat": 19.30, "lon": 73.06, "storage_capacity_m3": 4000, "handling_cost_per_unit": 6},
        {"id": "DC-DELHI", "name": "Delhi NCR DC", "type": "dc", "region": "North", "calendar": "CAL-IN-6D",
         "lat": 28.46, "lon": 77.03, "storage_capacity_m3": 3000, "handling_cost_per_unit": 7},
        {"id": "CUS-WEST-TRADE", "name": "West trade distributors", "type": "customer", "region": "West",
         "lat": 19.08, "lon": 72.88},
        {"id": "CUS-ECOM", "name": "E-commerce marketplaces", "type": "customer", "region": "Pan-India",
         "lat": 12.97, "lon": 77.59},
        {"id": "CUS-NORTH-TRADE", "name": "North trade distributors", "type": "customer", "region": "North",
         "lat": 28.61, "lon": 77.21},
        {"id": "SUP-COPPER", "name": "Hindalco copper (Silvassa)", "type": "supplier", "region": "West",
         "lat": 20.27, "lon": 73.02},
        {"id": "SUP-STAMP", "name": "Chakan stampings", "type": "supplier", "region": "West", "lat": 18.75, "lon": 73.85},
        {"id": "SUP-JARS", "name": "Rajkot jar works", "type": "supplier", "region": "West", "lat": 22.30, "lon": 70.80},
        {"id": "SUP-MOULD", "name": "Pune polymer moulders", "type": "supplier", "region": "West", "lat": 18.52, "lon": 73.85},
        {"id": "SUP-SHENZHEN", "name": "Shenzhen electro-components", "type": "supplier", "region": "China",
         "lat": 22.54, "lon": 114.06},
        {"id": "SUP-PACK", "name": "Bhosari corrugated boxes", "type": "supplier", "region": "West",
         "lat": 18.64, "lon": 73.84},
    ]
    products = [
        {"id": "MG-500", "name": "Mixer grinder 500 W", "type": "FG", "family": "Mixer grinders", "weight_kg": 4.2,
         "volume_m3": 0.028, "price": 2890, "setup_group": "MG"},
        {"id": "MG-750", "name": "Mixer grinder 750 W", "type": "FG", "family": "Mixer grinders", "weight_kg": 4.9,
         "volume_m3": 0.031, "price": 3990, "setup_group": "MG"},
        {"id": "KT-15", "name": "Electric kettle 1.5 L", "type": "FG", "family": "Kettles", "weight_kg": 1.3,
         "volume_m3": 0.009, "price": 1190, "setup_group": "KT"},
        {"id": "MOT-500", "name": "Motor assembly 500 W", "type": "SFG", "weight_kg": 1.6, "volume_m3": 0.004},
        {"id": "MOT-750", "name": "Motor assembly 750 W", "type": "SFG", "weight_kg": 2.0, "volume_m3": 0.005},
        {"id": "RM-CU-WIRE", "name": "Enamelled copper wire", "type": "RM", "base_uom": "KG", "weight_kg": 1.0,
         "volume_m3": 0.0002},
        {"id": "RM-STAMP", "name": "Stator/rotor lamination set", "type": "RM", "weight_kg": 0.9, "volume_m3": 0.0006},
        {"id": "RM-JARSET", "name": "Stainless jar set (3 jars)", "type": "RM", "weight_kg": 1.4, "volume_m3": 0.012},
        {"id": "RM-BODY-MG", "name": "Moulded MG body", "type": "RM", "weight_kg": 0.6, "volume_m3": 0.006},
        {"id": "RM-BODY-KT", "name": "Kettle body (SS)", "type": "RM", "weight_kg": 0.7, "volume_m3": 0.006},
        {"id": "RM-HEATER", "name": "Concealed heating element", "type": "RM", "weight_kg": 0.25, "volume_m3": 0.0005,
         "shelf_life_days": 720},
        {"id": "RM-SWITCH", "name": "Rotary switch + PCB", "type": "RM", "weight_kg": 0.08, "volume_m3": 0.0001},
        {"id": "PK-CARTON-L", "name": "Carton (large)", "type": "PKG", "weight_kg": 0.5, "volume_m3": 0.003,
         "conversions": [{"uom": "BDL", "factor": 25}]},
        {"id": "PK-CARTON-S", "name": "Carton (small)", "type": "PKG", "weight_kg": 0.2, "volume_m3": 0.0015,
         "conversions": [{"uom": "BDL", "factor": 50}]},
    ]
    resources = [
        {"id": "PUNE-WIND", "name": "Motor winding machines", "location": "PLT-PUNE", "kind": "machine", "units": 3,
         "shifts_per_day": 2, "hours_per_shift": 8, "efficiency": 0.82, "cost_per_hour": 420,
         "overtime_hours_per_day": 3, "overtime_cost_per_hour": 650},
        {"id": "PUNE-L1", "name": "Assembly line 1 (mixer grinders)", "location": "PLT-PUNE", "kind": "line",
         "units": 1, "shifts_per_day": 2, "hours_per_shift": 8, "efficiency": 0.78, "cost_per_hour": 1800,
         "overtime_hours_per_day": 4, "overtime_cost_per_hour": 2900},
        {"id": "PUNE-L2", "name": "Assembly line 2 (kettles)", "location": "PLT-PUNE", "kind": "line", "units": 1,
         "shifts_per_day": 1, "hours_per_shift": 8, "efficiency": 0.8, "cost_per_hour": 1200,
         "overtime_hours_per_day": 4, "overtime_cost_per_hour": 1900},
        {"id": "PUNE-TEST", "name": "Hi-pot & run test benches", "location": "PLT-PUNE", "kind": "machine", "units": 4,
         "shifts_per_day": 2, "hours_per_shift": 8, "efficiency": 0.85, "cost_per_hour": 250},
        {"id": "PUNE-LABOUR", "name": "Assembly operators", "location": "PLT-PUNE", "kind": "labor", "units": 36,
         "shifts_per_day": 1, "hours_per_shift": 8, "efficiency": 0.9, "cost_per_hour": 210,
         "overtime_hours_per_day": 2, "overtime_cost_per_hour": 420},
    ]

    def motor(pid: str, wire: float, run: float) -> dict:
        return {"id": f"PV-{pid}", "location": "PLT-PUNE", "product": pid, "output_qty": 1,
                "components": [{"product": "RM-CU-WIRE", "qty": wire, "scrap": 0.02},
                               {"product": "RM-STAMP", "qty": 1, "scrap": 0.01}],
                "operations": [{"seq": 10, "name": "Wind & insert", "resource": "PUNE-WIND", "setup_hours": 1.5,
                                "run_hours_per_unit": run, "labor_resource": "PUNE-LABOUR",
                                "labor_hours_per_unit": run * 0.5, "queue_workdays": 1}],
                "assembly_scrap": 0.015, "conversion_cost_per_unit": 35, "min_lot": 200}

    def grinder(pid: str, mot: str) -> dict:
        return {"id": f"PV-{pid}", "location": "PLT-PUNE", "product": pid, "output_qty": 1,
                "components": [{"product": mot, "qty": 1, "operation": 10},
                               {"product": "RM-JARSET", "qty": 1, "operation": 10},
                               {"product": "RM-BODY-MG", "qty": 1, "operation": 10, "scrap": 0.01},
                               {"product": "RM-SWITCH", "qty": 1, "operation": 10},
                               {"product": "PK-CARTON-L", "qty": 1, "operation": 20}],
                "operations": [{"seq": 10, "name": "Final assembly", "resource": "PUNE-L1", "setup_hours": 2.0,
                                "run_hours_per_unit": 0.0125, "labor_resource": "PUNE-LABOUR",
                                "labor_hours_per_unit": 0.2},
                               {"seq": 20, "name": "Test & pack", "resource": "PUNE-TEST", "setup_hours": 0,
                                "run_hours_per_unit": 0.02, "labor_resource": "PUNE-LABOUR",
                                "labor_hours_per_unit": 0.05}],
                "assembly_scrap": 0.01, "conversion_cost_per_unit": 40, "min_lot": 300}

    production_sources = [
        motor("MOT-500", 0.42, 0.045), motor("MOT-750", 0.55, 0.055),
        grinder("MG-500", "MOT-500"), grinder("MG-750", "MOT-750"),
        {"id": "PV-KT-15", "location": "PLT-PUNE", "product": "KT-15", "output_qty": 1,
         "components": [{"product": "RM-BODY-KT", "qty": 1, "scrap": 0.01}, {"product": "RM-HEATER", "qty": 1},
                        {"product": "RM-SWITCH", "qty": 1}, {"product": "PK-CARTON-S", "qty": 1, "operation": 20}],
         "operations": [{"seq": 10, "name": "Assembly", "resource": "PUNE-L2", "setup_hours": 1.0,
                         "run_hours_per_unit": 0.008, "labor_resource": "PUNE-LABOUR", "labor_hours_per_unit": 0.1},
                        {"seq": 20, "name": "Test & pack", "resource": "PUNE-TEST", "run_hours_per_unit": 0.01,
                         "labor_resource": "PUNE-LABOUR", "labor_hours_per_unit": 0.03}],
         "assembly_scrap": 0.008, "conversion_cost_per_unit": 18, "min_lot": 400},
    ]
    purchasing = [
        {"id": "PIR-CU", "supplier": "SUP-COPPER", "product": "RM-CU-WIRE", "location": "PLT-PUNE", "price": 905,
         "ordering_cost": 2500, "moq": 500, "rounding_qty": 250, "lead_time_days": 7, "lead_time_std_days": 1.5,
         "capacity_per_week": 6000},
        {"id": "PIR-STAMP", "supplier": "SUP-STAMP", "product": "RM-STAMP", "location": "PLT-PUNE", "price": 118,
         "moq": 1000, "rounding_qty": 500, "lead_time_days": 5, "lead_time_std_days": 1},
        {"id": "PIR-JARS", "supplier": "SUP-JARS", "product": "RM-JARSET", "location": "PLT-PUNE", "price": 410,
         "moq": 500, "rounding_qty": 100, "lead_time_days": 10, "lead_time_std_days": 2},
        {"id": "PIR-BODY-MG", "supplier": "SUP-MOULD", "product": "RM-BODY-MG", "location": "PLT-PUNE", "price": 96,
         "rounding_qty": 200, "lead_time_days": 4},
        {"id": "PIR-BODY-KT", "supplier": "SUP-MOULD", "product": "RM-BODY-KT", "location": "PLT-PUNE", "price": 165,
         "rounding_qty": 200, "lead_time_days": 6},
        {"id": "PIR-HEATER", "supplier": "SUP-SHENZHEN", "product": "RM-HEATER", "location": "PLT-PUNE", "price": 1.35,
         "currency": "USD", "duty_rate": 0.20, "ordering_cost": 18000, "moq": 5000, "rounding_qty": 1000,
         "lead_time_days": 14, "lead_time_std_days": 3},
        {"id": "PIR-SWITCH", "supplier": "SUP-SHENZHEN", "product": "RM-SWITCH", "location": "PLT-PUNE", "price": 0.62,
         "currency": "USD", "duty_rate": 0.20, "ordering_cost": 18000, "moq": 10000, "rounding_qty": 2000,
         "lead_time_days": 14, "lead_time_std_days": 3},
        {"id": "PIR-CART-L", "supplier": "SUP-PACK", "product": "PK-CARTON-L", "location": "PLT-PUNE", "price": 38,
         "rounding_qty": 25, "lead_time_days": 3},
        {"id": "PIR-CART-S", "supplier": "SUP-PACK", "product": "PK-CARTON-S", "location": "PLT-PUNE", "price": 19,
         "rounding_qty": 50, "lead_time_days": 3},
    ]
    lanes = [
        {"id": "LN-PUNE-BHW", "origin": "PLT-PUNE", "destination": "DC-BHIWANDI",
         "products": ["MG-500", "MG-750", "KT-15"],
         "modes": [{"mode": "truck_ftl", "transit_days": 1, "cost_per_kg": 2.1, "cost_per_shipment": 1500,
                    "vehicle_capacity_kg": 9000, "vehicle_capacity_m3": 32, "default": True}]},
        {"id": "LN-PUNE-DEL", "origin": "PLT-PUNE", "destination": "DC-DELHI", "products": ["MG-500", "MG-750", "KT-15"],
         "modes": [{"mode": "truck_ftl", "transit_days": 3, "transit_std_days": 0.7, "cost_per_kg": 5.4,
                    "cost_per_shipment": 3000, "vehicle_capacity_kg": 9000, "vehicle_capacity_m3": 32, "default": True},
                   {"mode": "rail", "transit_days": 5, "transit_std_days": 1.2, "cost_per_kg": 3.2,
                    "cost_per_shipment": 6000, "vehicle_capacity_kg": 20000}]},
        {"id": "LN-BHW-WEST", "origin": "DC-BHIWANDI", "destination": "CUS-WEST-TRADE",
         "modes": [{"mode": "truck_ltl", "transit_days": 1, "cost_per_kg": 3.5}]},
        {"id": "LN-BHW-ECOM", "origin": "DC-BHIWANDI", "destination": "CUS-ECOM",
         "modes": [{"mode": "courier", "transit_days": 2, "cost_per_unit": 55}]},
        {"id": "LN-DEL-NORTH", "origin": "DC-DELHI", "destination": "CUS-NORTH-TRADE",
         "modes": [{"mode": "truck_ltl", "transit_days": 1, "cost_per_kg": 3.8}]},
        {"id": "LN-SZ-PUNE", "origin": "SUP-SHENZHEN", "destination": "PLT-PUNE",
         "modes": [{"mode": "sea", "transit_days": 30, "transit_std_days": 5, "cost_per_m3": 6500,
                    "cost_per_shipment": 45000}]},
        {"id": "LN-CU-PUNE", "origin": "SUP-COPPER", "destination": "PLT-PUNE",
         "modes": [{"mode": "truck_ftl", "transit_days": 2, "cost_per_kg": 1.8}]},
    ]
    dc_policy = {"safety_stock": {"method": "service_level", "service_level": 0.97, "demand_cv": 0.25},
                 "lot_sizing": {"policy": "POQ", "periods": 1}, "gr_processing_days": 1}
    lps = []
    for dc, stock in (("DC-BHIWANDI", {"MG-500": 2600, "MG-750": 1700, "KT-15": 3200}),
                      ("DC-DELHI", {"MG-500": 1500, "MG-750": 900, "KT-15": 1500})):
        for p, oh in stock.items():
            lps.append({"location": dc, "product": p, "on_hand": oh, **dc_policy})
    for p, oh in (("MG-500", 1400), ("MG-750", 900), ("KT-15", 1600)):
        lps.append({"location": "PLT-PUNE", "product": p, "on_hand": oh,
                    "safety_stock": {"method": "days_of_supply", "days": 5},
                    "lot_sizing": {"policy": "POQ", "periods": 1, "rounding_qty": 50}, "planning_time_fence_days": 3})
    lps += [
        {"location": "PLT-PUNE", "product": "MOT-500", "on_hand": 2600,
         "lot_sizing": {"policy": "POQ", "periods": 1}, "safety_stock": {"method": "fixed", "qty": 500}},
        {"location": "PLT-PUNE", "product": "MOT-750", "on_hand": 1700,
         "lot_sizing": {"policy": "POQ", "periods": 1}, "safety_stock": {"method": "fixed", "qty": 300}},
        {"location": "PLT-PUNE", "product": "RM-CU-WIRE", "on_hand": 5200, "lot_sizing": {"policy": "EOQ"},
         "safety_stock": {"method": "service_level", "service_level": 0.98, "demand_cv": 0.3},
         "gr_processing_days": 1},
        {"location": "PLT-PUNE", "product": "RM-STAMP", "on_hand": 7500,
         "safety_stock": {"method": "days_of_supply", "days": 7}},
        {"location": "PLT-PUNE", "product": "RM-JARSET", "on_hand": 6500, "lot_sizing": {"policy": "POQ", "periods": 2},
         "safety_stock": {"method": "days_of_supply", "days": 10}},
        {"location": "PLT-PUNE", "product": "RM-BODY-MG", "on_hand": 6000},
        {"location": "PLT-PUNE", "product": "RM-BODY-KT", "on_hand": 4000},
        {"location": "PLT-PUNE", "product": "RM-HEATER", "on_hand": 14000,
         "lot_sizing": {"policy": "POQ", "periods": 4},
         "safety_stock": {"method": "fill_rate", "service_level": 0.99, "demand_cv": 0.3}, "gr_processing_days": 2},
        {"location": "PLT-PUNE", "product": "RM-SWITCH", "on_hand": 42000,
         "lot_sizing": {"policy": "POQ", "periods": 4},
         "safety_stock": {"method": "service_level", "service_level": 0.98, "demand_cv": 0.3}, "gr_processing_days": 2},
        {"location": "PLT-PUNE", "product": "PK-CARTON-L", "on_hand": 6000},
        {"location": "PLT-PUNE", "product": "PK-CARTON-S", "on_hand": 5000},
    ]
    demand = []
    weeks = 26
    demand += weekly_forecast("CUS-WEST-TRADE", "MG-500", 520, weeks, festive, rng)
    demand += weekly_forecast("CUS-WEST-TRADE", "MG-750", 300, weeks, festive, rng)
    demand += weekly_forecast("CUS-WEST-TRADE", "KT-15", 640, weeks, {10: 1.2, 11: 1.15, 12: 1.3, 1: 1.35}, rng)
    demand += weekly_forecast("CUS-ECOM", "MG-500", 260, weeks, {10: 1.8, 11: 1.4}, rng, 0.15)
    demand += weekly_forecast("CUS-ECOM", "MG-750", 190, weeks, {10: 1.9, 11: 1.4}, rng, 0.15)
    demand += weekly_forecast("CUS-ECOM", "KT-15", 420, weeks, {10: 1.6, 11: 1.3, 12: 1.2, 1: 1.25}, rng, 0.15)
    demand += weekly_forecast("CUS-NORTH-TRADE", "MG-500", 380, weeks, festive, rng)
    demand += weekly_forecast("CUS-NORTH-TRADE", "MG-750", 210, weeks, festive, rng)
    demand += weekly_forecast("CUS-NORTH-TRADE", "KT-15", 520, weeks, {11: 1.2, 12: 1.45, 1: 1.5, 2: 1.2}, rng)
    demand += [
        {"id": "SO-88121", "location": "CUS-WEST-TRADE", "product": "MG-500", "date": "2026-10-01", "qty": 450,
         "kind": "sales_order", "priority": 2},
        {"id": "SO-88140", "location": "CUS-NORTH-TRADE", "product": "MG-750", "date": "2026-10-06", "qty": 380,
         "kind": "sales_order", "priority": 1},
        {"id": "SO-88177", "location": "CUS-ECOM", "product": "KT-15", "date": "2026-10-09", "qty": 900,
         "kind": "sales_order", "priority": 3},
    ]
    receipts = [
        {"id": "PO-4500012871", "kind": "purchase", "location": "PLT-PUNE", "product": "RM-HEATER", "qty": 10000,
         "due_date": "2026-10-19", "source": "PIR-HEATER"},
        {"id": "MO-100455", "kind": "production", "location": "PLT-PUNE", "product": "MG-500", "qty": 800,
         "due_date": "2026-09-30", "source": "PV-MG-500"},
        {"id": "STO-2201", "kind": "transfer", "location": "DC-DELHI", "product": "KT-15", "qty": 600,
         "due_date": "2026-09-29", "source": "LN-PUNE-DEL"},
    ]
    return {
        "schema_version": "1",
        "settings": {"company_name": "Kaveri Kitchenware Pvt Ltd (fictional)", "currency": "INR",
                     "planning_start": START.isoformat(), "horizon_days": 182, "bucket": "week",
                     "fx_rates": {"USD": 84.2}, "wacc": 0.13, "holding_spread": 0.09,
                     "default_service_level": 0.95, "default_calendar": "CAL-IN-6D"},
        "calendars": cal, "locations": locations, "products": products, "location_products": lps,
        "resources": resources, "production_sources": production_sources, "purchasing_sources": purchasing,
        "lanes": lanes, "demand": demand, "receipts": receipts, "history": [],
    }


def single_product() -> dict:
    """One plant, one product sold at the factory gate — the smallest useful network."""
    rng = random.Random(7)
    return {
        "schema_version": "1",
        "settings": {"company_name": "Single-product bottler (fictional)", "currency": "INR",
                     "planning_start": START.isoformat(), "horizon_days": 84, "bucket": "week",
                     "wacc": 0.12, "holding_spread": 0.06, "default_calendar": "CAL-5D"},
        "calendars": [{"id": "CAL-5D", "name": "Mon–Fri", "workdays": [0, 1, 2, 3, 4], "holidays": ["2026-10-02"]}],
        "locations": [{"id": "PLANT", "name": "Nashik bottling plant", "type": "plant", "lat": 20.0, "lon": 73.79},
                      {"id": "SUP-PREFORM", "name": "Preform supplier", "type": "supplier", "lat": 19.99, "lon": 73.1},
                      {"id": "SUP-CAPS", "name": "Cap & label supplier", "type": "supplier", "lat": 19.2, "lon": 72.97}],
        "products": [{"id": "BTL-1L", "name": "Mineral water 1 L", "type": "FG", "weight_kg": 1.05,
                      "volume_m3": 0.0011, "price": 14, "shelf_life_days": 180},
                     {"id": "PREFORM", "name": "PET preform 1 L", "type": "RM", "weight_kg": 0.028},
                     {"id": "CAP-LABEL", "name": "Cap + label kit", "type": "RM", "weight_kg": 0.004}],
        "location_products": [
            {"location": "PLANT", "product": "BTL-1L", "on_hand": 52000,
             "safety_stock": {"method": "service_level", "service_level": 0.95, "demand_cv": 0.2},
             "lot_sizing": {"policy": "FIXED", "fixed_qty": 20000}},
            {"location": "PLANT", "product": "PREFORM", "on_hand": 60000,
             "lot_sizing": {"policy": "FIXED", "fixed_qty": 100000},
             "safety_stock": {"method": "days_of_supply", "days": 5}},
            {"location": "PLANT", "product": "CAP-LABEL", "on_hand": 80000,
             "lot_sizing": {"policy": "MIN_MAX"}, "max_stock": 200000,
             "safety_stock": {"method": "fixed", "qty": 20000}}],
        "resources": [{"id": "BLOW-FILL", "name": "Blow-fill-cap line", "location": "PLANT", "kind": "line",
                       "shifts_per_day": 2, "hours_per_shift": 8, "efficiency": 0.8, "cost_per_hour": 2200,
                       "overtime_hours_per_day": 4, "overtime_cost_per_hour": 3300}],
        "production_sources": [{"id": "PV-BTL-1L", "location": "PLANT", "product": "BTL-1L",
                                "components": [{"product": "PREFORM", "qty": 1, "scrap": 0.005},
                                               {"product": "CAP-LABEL", "qty": 1, "scrap": 0.01}],
                                "operations": [{"seq": 10, "name": "Blow, fill, cap, label", "resource": "BLOW-FILL",
                                                "setup_hours": 0.5, "run_hours_per_unit": 0.0002}],
                                "assembly_scrap": 0.003, "conversion_cost_per_unit": 0.9}],
        "purchasing_sources": [
            {"id": "PIR-PREFORM", "supplier": "SUP-PREFORM", "product": "PREFORM", "location": "PLANT", "price": 2.6,
             "moq": 50000, "lead_time_days": 6, "lead_time_std_days": 1},
            {"id": "PIR-CAPS", "supplier": "SUP-CAPS", "product": "CAP-LABEL", "location": "PLANT", "price": 0.55,
             "rounding_qty": 10000, "lead_time_days": 4}],
        "lanes": [],
        "demand": [{"location": "PLANT", "product": "BTL-1L", "date": (START + timedelta(weeks=w)).isoformat(),
                    "qty": round(38000 * (1.15 if w < 4 else 0.95) * (1 + rng.uniform(-0.1, 0.1))), "kind": "forecast",
                    "period_days": 7}
                   for w in range(12)],
        "receipts": [], "history": [],
    }


def main() -> None:
    for name, build in (("kitchenware_network", kitchenware), ("single_product_plant", single_product)):
        data = build()
        Dataset.model_validate(data)  # fail loudly if an example drifts from the schema
        (HERE / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n")
        print(f"wrote {name}.json")


if __name__ == "__main__":
    main()
