"""Hypothesis strategies for the property-based suite: random companies (networks, policies, demand) as plain dicts,
exactly as a user would type them, plus a frozen clock and helpers shared by the property tests.

Everything here is deterministic for a given draw: no wall clock, no network, no global random state (each company
gets its own ``random.Random`` seeded from the draw)."""
from __future__ import annotations

import datetime as dt
import random
from datetime import date, timedelta

from hypothesis import strategies as st

START = date(2026, 3, 2)          # a Monday
FROZEN_NOW = dt.datetime(2026, 9, 28, 9, 0, tzinfo=dt.UTC)

qty = st.integers(min_value=1, max_value=400).map(float)


@st.composite
def lot_sizings(draw, *, allow_max: bool = True) -> dict:
    """A valid lot-sizing record: a base policy and any of the modifiers (minimum, rounding, maximum)."""
    policy = draw(st.sampled_from(["L4L", "FIXED", "POQ", "EOQ", "MIN_MAX"]))
    out: dict = {"policy": policy}
    if policy == "FIXED":
        out["fixed_qty"] = draw(st.sampled_from([10.0, 25.0, 40.0, 100.0]))
    if policy == "POQ":
        out["periods"] = draw(st.integers(1, 3))
    if policy == "EOQ":
        out["ordering_cost"] = draw(st.sampled_from([0.0, 100.0, 500.0]))
    mn = draw(st.sampled_from([0.0, 0.0, 20.0, 30.0, 60.0]))
    out["min_qty"] = mn
    if draw(st.booleans()):
        out["rounding_qty"] = draw(st.sampled_from([5.0, 10.0, 12.0, 25.0]))
    if allow_max and draw(st.booleans()):
        out["max_qty"] = max(mn, draw(st.sampled_from([35.0, 50.0, 80.0, 150.0, 300.0])))
    return out


def network(seed: int, lot: dict[str, dict] | None = None, *, bucket: str | None = None,
            max_stock: bool = False) -> dict:
    """A random multi-level company: suppliers → plant (RM → SFG → FG) → DCs → customers, with demand.

    ``lot`` maps a product id to the lot sizing used for it everywhere (the rest are drawn from the seed)."""
    rng = random.Random(seed)
    n_rm, n_sfg, n_fg = rng.randint(2, 5), rng.randint(0, 2), rng.randint(1, 3)
    n_dc, n_cus = rng.randint(0, 2), rng.randint(1, 3)
    bucket = bucket or rng.choice(["day", "week", "month"])
    horizon = {"day": 35, "week": 84, "month": 180}[bucket]
    locs = [{"id": "PL", "type": "plant", "calendar": "C6"}, {"id": "SUP", "type": "supplier"}]
    locs += [{"id": f"DC{i}", "type": "dc"} for i in range(n_dc)]
    locs += [{"id": f"K{i}", "type": "customer"} for i in range(n_cus)]
    rms = [f"RM{i}" for i in range(n_rm)]
    sfgs = [f"SF{i}" for i in range(n_sfg)]
    fgs = [f"FG{i}" for i in range(n_fg)]
    prods = ([{"id": p, "type": "RM", "weight_kg": 1} for p in rms] + [{"id": p, "type": "SFG"} for p in sfgs]
             + [{"id": p, "type": "FG", "weight_kg": 2} for p in fgs])
    lot = lot or {}

    def policy(p: str) -> dict:
        ls = lot.get(p) or rng.choice([{"policy": "L4L"}, {"policy": "FIXED", "fixed_qty": rng.choice([25, 100])},
                                       {"policy": "POQ", "periods": rng.randint(1, 3)},
                                       {"policy": "EOQ", "ordering_cost": 500},
                                       {"policy": "L4L", "min_qty": 30, "rounding_qty": 10, "max_qty": 200}])
        ss = rng.choice([{"method": "none"}, {"method": "fixed", "qty": rng.randint(0, 40)},
                         {"method": "days_of_supply", "days": rng.randint(2, 10)},
                         {"method": "service_level", "service_level": 0.95, "demand_cv": 0.3}])
        out = {"lot_sizing": dict(ls), "safety_stock": ss, "on_hand": rng.randint(0, 150),
               "planning_time_fence_days": rng.choice([0, 0, 3]), "gr_processing_days": rng.choice([0, 1]),
               "unit_cost": rng.randint(5, 50)}
        if ls.get("policy") == "MIN_MAX" or (max_stock and rng.random() < 0.5):
            out["max_stock"] = float(rng.choice([150, 300, 600]))
            out["reorder_point"] = float(rng.choice([0, 20, 50]))
        return out

    lps = [{"location": "PL", "product": p, **policy(p)} for p in rms + sfgs + fgs]
    lps += [{"location": f"DC{i}", "product": p, **policy(p)} for i in range(n_dc) for p in fgs]
    res = [{"id": "R1", "location": "PL", "units": rng.randint(1, 3), "efficiency": 0.8}]
    srcs = []
    for p in sfgs + fgs:
        lower = rms + (sfgs[: sfgs.index(p)] if p in sfgs else sfgs)
        comps = rng.sample(lower, k=min(len(lower), rng.randint(1, 3)))
        srcs.append({"id": f"PV-{p}", "location": "PL", "product": p,
                     "components": [{"product": c, "qty": rng.choice([1, 2, 0.5])} for c in comps],
                     "operations": [{"seq": 10, "resource": "R1", "setup_hours": rng.choice([0, 2]),
                                     "run_hours_per_unit": rng.choice([0.01, 0.05])}]})
    pur = [{"id": f"PIR-{p}", "supplier": "SUP", "product": p, "location": "PL", "price": rng.randint(1, 20),
            "lead_time_days": rng.randint(1, 10), "moq": rng.choice([0, 0, 50])} for p in rms]
    lanes = []
    for i in range(n_dc):
        lanes.append({"id": f"L-PL-DC{i}", "origin": "PL", "destination": f"DC{i}", "products": fgs,
                      "modes": [{"transit_days": rng.randint(1, 3), "cost_per_kg": 1, "cost_per_shipment": 100}]})
    for k in range(n_cus):
        origin = f"DC{rng.randrange(n_dc)}" if n_dc else "PL"
        lanes.append({"id": f"L-{origin}-K{k}", "origin": origin, "destination": f"K{k}",
                      "modes": [{"transit_days": rng.randint(0, 2)}]})
    dem = []
    for k in range(n_cus):
        for p in rng.sample(fgs, k=rng.randint(1, len(fgs))):
            for w in range(horizon // 7):
                if rng.random() < 0.8:
                    dd = START + timedelta(days=w * 7 + rng.randint(0, 6))
                    dem.append({"location": f"K{k}", "product": p, "date": dd.isoformat(),
                                "qty": rng.randint(5, 80), "kind": rng.choice(["forecast", "forecast", "sales_order"])})
    return {"settings": {"planning_start": START.isoformat(), "horizon_days": horizon, "bucket": bucket,
                         "default_calendar": "C6", "wacc": 0.1, "holding_spread": 0.1},
            "calendars": [{"id": "C6", "workdays": [0, 1, 2, 3, 4, 5]}], "locations": locs, "products": prods,
            "location_products": lps, "resources": res, "production_sources": srcs, "purchasing_sources": pur,
            "lanes": lanes, "demand": dem, "receipts": []}


@st.composite
def companies(draw, *, max_stock: bool = False) -> dict:
    """A random company whose lot sizing is drawn by Hypothesis (so it shrinks to the policy that matters)."""
    seed = draw(st.integers(0, 2**31 - 1))
    probe = network(seed)
    products = [p["id"] for p in probe["products"]]
    lot = {p: draw(lot_sizings()) for p in products}
    return network(seed, lot, max_stock=max_stock)


class FrozenClock:
    """A clock that only moves when told to: ``company_store._now`` and friends read it."""

    def __init__(self, t: dt.datetime = FROZEN_NOW) -> None:
        self.t = t

    def __call__(self) -> dt.datetime:
        return self.t

    def tick(self, minutes: float) -> None:
        self.t += dt.timedelta(minutes=minutes)
