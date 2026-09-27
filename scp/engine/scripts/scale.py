"""Measure the engine at a real company's scale (Phase L): time and peak memory of each step on a generated company.

    python scp/engine/scripts/scale.py [--products 5000] [--places 20] [--weeks 104] [--dcs-per-fg 6]

Steps: build the company, check it (the data checks the page runs on every change), the network view, the supply
plan, the forecast (every series, the model competition), promising, saving it to the company store and saving one
changed record as a patch. Prints a table; ``--json`` prints it as JSON.
"""
from __future__ import annotations

import argparse
import gc
import json
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "examples"))


def peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", type=int, default=5000)
    ap.add_argument("--places", type=int, default=20)
    ap.add_argument("--weeks", type=int, default=104)
    ap.add_argument("--dcs-per-fg", type=int, default=6)
    ap.add_argument("--skip", default="", help="comma-separated steps to skip (forecast, promise, …)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    skip = set(filter(None, a.skip.split(",")))
    rows: list[dict] = []

    def step(name: str, fn):
        if name in skip:
            return None
        gc.collect()
        t = time.perf_counter()
        out = fn()
        rows.append({"step": name, "seconds": round(time.perf_counter() - t, 2), "peak_mb": round(peak_mb())})
        if not a.json:
            print(f"{name:<28}{rows[-1]['seconds']:>9.2f} s{rows[-1]['peak_mb']:>9.0f} MB", flush=True)
        return out

    from build_examples import scale_company
    from scp.model import Dataset

    raw = step("build", lambda: scale_company(a.products, a.places, a.weeks, dcs_per_fg=a.dcs_per_fg))
    text = step("to JSON", lambda: json.dumps(raw))
    if not a.json:
        print(f"  {len(raw['products'])} products, {len(raw['location_products'])} planning policies, "
              f"{len(raw['history'])} history rows, {len(raw['demand'])} forecast rows, {len(text) / 1e6:.0f} MB JSON")
    ds = step("read (validate types)", lambda: Dataset.model_validate_json(text))

    from scp.api.app import post_network, post_validate
    from scp.plan import run_mrp
    step("data checks (as on each change)", lambda: post_validate(raw))
    step("network view", lambda: post_network(raw))
    step("supply plan", lambda: run_mrp(ds))
    from scp.demand import run_forecast
    step("forecast", lambda: run_forecast(ds))
    from scp.promise import run_promise
    step("promising", lambda: run_promise(ds))
    # the rest of "Plan everything", in its order (each reuses the supply plan made above)
    from scp.actuals import actuals_view
    from scp.finance import run_finance
    from scp.inventory import run_inventory
    from scp.plan import run_mrp as plan_again
    from scp.purchasing import purchasing_view
    from scp.schedule import run_schedule
    from scp.sop import run_sop
    from scp.tower import run_tower
    step("safety stock", lambda: run_inventory(ds))
    step("capacity (S&OP)", lambda: run_sop(ds))
    step("schedule", lambda: run_schedule(ds))
    step("buying", lambda: purchasing_view(ds, plan_again(ds)))
    step("actuals", lambda: actuals_view(ds))
    step("money", lambda: run_finance(ds))
    step("performance", lambda: run_tower(ds))

    from scp.companies import store as cs
    from scp.companies.patch import make_patch
    from scp.versions.store import Store
    c = cs.Companies(Store(":memory:"))
    s = c.signup("scale@example.com", "Scale", "scale-test-1")
    meta = step("save to the server (new)", lambda: c.create(s.user, raw))
    changed = dict(raw)
    changed["products"] = list(raw["products"])
    changed["products"][0] = {**raw["products"][0], "price": 1}
    p = step("make a patch (1 change)", lambda: make_patch(raw, changed))
    step("save the patch", lambda: c.save(s.user, meta.id, None, 1, patch=p))
    if a.json:
        print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
