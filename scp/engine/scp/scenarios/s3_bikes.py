"""S3 · Summit Bikes: a capacity crunch solved by hand, then by an independent LP.

One welding cell makes road bikes (1 h each) and mountain bikes (2 h each). March demand needs 410 h
against 248 h of regular time and 62 h of overtime, so the plan must build ahead. The optimum is found by
hand: every regular hour is used, overtime is spent as late as possible, and the build-ahead is the product
that is cheapest to hold per welding hour. Shadow prices follow from what an extra hour would replace.
Profit mode with 25 % more demand is checked against an LP written independently in this file. The plan
is then released to MRP, which must keep the build-ahead instead of rebuilding the March overload, and a
weekend crew is appraised with the shadow prices, a re-solve, NPV, IRR and payback.
"""
from __future__ import annotations

import json

import numpy as np
from scipy.optimize import linprog

from ..model import Dataset
from .harness import Client, Ctx, Scenario, by, one

DAYS = [31, 28, 31]            # Jan, Feb, Mar 2027 on a 7-day calendar
RATE = 0.24                    # WACC 12 % + holding spread 12 %


def _fc(p: str, day: str, qty: float, n: int) -> dict:
    return {"location": "PLANT", "product": p, "date": day, "qty": qty, "kind": "forecast", "period_days": n}


def build() -> dict:
    return {
        "settings": {"company_name": "Summit Bikes", "currency": "USD", "planning_start": "2027-01-01",
                     "horizon_days": 90, "bucket": "month", "wacc": 0.12, "holding_spread": 0.12,
                     "default_calendar": "CAL-7"},
        "calendars": [{"id": "CAL-7", "name": "7 days", "workdays": [0, 1, 2, 3, 4, 5, 6]}],
        "locations": [{"id": "PLANT", "name": "Frame shop", "type": "plant", "lat": 39.74, "lon": -104.99}],
        "products": [{"id": "ROAD", "name": "Road bike", "type": "FG", "price": 1000, "family": "Bikes"},
                     {"id": "MTB", "name": "Mountain bike", "type": "FG", "price": 1500, "family": "Bikes"}],
        "location_products": [{"location": "PLANT", "product": "ROAD"}, {"location": "PLANT", "product": "MTB"}],
        "resources": [{"id": "WELD", "name": "Welding cell", "location": "PLANT", "efficiency": 1.0,
                       "hours_per_shift": 8, "cost_per_hour": 50, "overtime_hours_per_day": 2,
                       "overtime_cost_per_hour": 150}],
        "production_sources": [
            {"id": "PS-ROAD", "location": "PLANT", "product": "ROAD", "fixed_lead_time_workdays": 1,
             "conversion_cost_per_unit": 300, "operations": [{"seq": 10, "resource": "WELD", "run_hours_per_unit": 1.0}]},
            {"id": "PS-MTB", "location": "PLANT", "product": "MTB", "fixed_lead_time_workdays": 1,
             "conversion_cost_per_unit": 400, "operations": [{"seq": 10, "resource": "WELD", "run_hours_per_unit": 2.0}]},
        ],
        "demand": [_fc("ROAD", "2027-01-01", 150, 31), _fc("ROAD", "2027-02-01", 150, 28), _fc("ROAD", "2027-03-01", 250, 31),
                   _fc("MTB", "2027-01-01", 40, 31), _fc("MTB", "2027-02-01", 40, 28), _fc("MTB", "2027-03-01", 80, 31)],
        "finance": {"capacity_options": [{"id": "OPT-WEEKEND", "name": "Weekend crew", "resource": "WELD",
                                          "added_hours_per_week": 40, "capex": 50000, "fixed_cost_per_year": 20000,
                                          "life_years": 5}]},
    }


def _hold(value: float, t: int) -> float:
    return value * RATE * DAYS[t] / 365


def independent_lp(factor: float, profit: bool) -> tuple[float, dict]:
    """The same economics as the dataset, formulated from scratch: returns (objective, solution)."""
    P = {"ROAD": dict(h=1.0, price=1000.0, conv=350.0, dem=[150, 150, 250]),
         "MTB": dict(h=2.0, price=1500.0, conv=500.0, dem=[40, 40, 80])}
    names: list[str] = []
    cost: list[float] = []
    ub: list[float | None] = []

    def var(name: str, c: float, hi: float | None = None) -> int:
        names.append(name)
        cost.append(c)
        ub.append(hi)
        return len(names) - 1

    ix = {}
    for p, a in P.items():
        for t in range(3):
            ix[p, "make", t] = var(f"make {p} {t}", a["conv"])
            ix[p, "sales", t] = var(f"sales {p} {t}", -a["price"] if profit else 0.0)
            ix[p, "inv", t] = var(f"inv {p} {t}", _hold(a["conv"], t))
            late = a["price"] * 0.005 * DAYS[t] + (0 if profit or t < 2 else a["price"] * 2.0)
            ix[p, "back", t] = var(f"back {p} {t}", late)
            ix[p, "lost", t] = var(f"lost {p} {t}", 0.0 if profit else a["price"] * 2.0)
    for t in range(3):
        ix["ot", t] = var(f"ot {t}", 150.0, 2.0 * DAYS[t])
    n = len(names)
    a_eq, b_eq, a_ub, b_ub = [], [], [], []
    for p, a in P.items():
        for t in range(3):
            row = np.zeros(n)
            row[ix[p, "make", t]] = 1
            row[ix[p, "sales", t]] = -1
            row[ix[p, "inv", t]] = -1
            if t:
                row[ix[p, "inv", t - 1]] = 1
            a_eq.append(row)
            b_eq.append(0.0)
            row = np.zeros(n)
            row[ix[p, "sales", t]] = 1
            row[ix[p, "lost", t]] = 1
            row[ix[p, "back", t]] = 1
            if t:
                row[ix[p, "back", t - 1]] = -1
            a_eq.append(row)
            b_eq.append(a["dem"][t] * factor)
    for t in range(3):
        row = np.zeros(n)
        for p, a in P.items():
            row[ix[p, "make", t]] = a["h"]
        row[ix["ot", t]] = -1
        a_ub.append(row)
        b_ub.append(8.0 * DAYS[t])
    res = linprog(cost, A_ub=np.array(a_ub), b_ub=b_ub, A_eq=np.array(a_eq), b_eq=b_eq,
                  bounds=[(0, u) for u in ub], method="highs")
    return float(res.fun), {k: float(res.x[i]) for k, i in ix.items()}


def _irr(flows: list[float]) -> float:
    lo, hi = -0.99, 100.0
    npv = lambda r: sum(f / (1 + r) ** k for k, f in enumerate(flows))  # noqa: E731
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Check the master data", "readiness", "POST /api/validate",
                  "One plant, one welding cell, two bikes and a capacity option: nothing should block."):
        ctx.eq("readiness issues", [f"{i.code} {i.object_id}" for i in c.validate(ds)], [])

    with ctx.step("Solve the constrained plan (cost mode)", "sop", "POST /api/sop",
                  "Regular welding: 8 h/day → 248, 224, 248 h; overtime up to 2 h/day at 150/h. Demand needs "
                  "230, 230 and 410 h."):
        sop = c.sop(ds)
        ctx.eq("solved", (sop.ok, sop.solver.status if sop.solver else None), (True, "optimal"))
        make = {f.product: f.qty for f in sop.flows if f.kind == "make"}
        ctx.near("production ROAD by month", make["ROAD"], [150, 150, 250], 1e-6)
        ctx.near("production MTB by month", make["MTB"], [65, 65, 30], 1e-6,
                 "All 870 h of demand fit in 900 h, so nothing is lost and all 720 regular hours are used. March "
                 "is short by 410 − 310 = 100 h: February can give 280 − 230 = 50 h and January the other 50 "
                 "(18 h regular slack + 32 h overtime). The build-ahead is MTB: 500 of value per 2 h costs less to "
                 "hold per welding hour (250) than ROAD (350 per hour), so 25 MTB are built in each of Jan and Feb.")
        inv = {s.product: s.inventory for s in sop.supply}
        ctx.near("MTB stock at month end", inv["MTB"], [25, 50, 0], 1e-6)
        weld = one(sop.resources, resource="WELD")
        ctx.near("overtime hours", weld.overtime, [32, 56, 62], 1e-6,
                 "150 h of overtime are unavoidable (870 − 720); the 30 h left unused are January's, the ones "
                 "that would be held longest.")
        h_mtb = [_hold(500, t) for t in range(3)]
        ctx.near("shadow price of a regular hour", weld.shadow_price,
                 [150, 150 + h_mtb[0] / 2, 150 + (h_mtb[0] + h_mtb[1]) / 2], 1e-6,
                 "An extra January hour replaces a January overtime hour (150). An extra February hour also saves "
                 "holding ½ MTB through January; an extra March hour saves ½ MTB held through January and February.")
        ot = {b.bucket: b.shadow_price for b in sop.binding if b.kind == "overtime"}
        ctx.near("value of one more overtime hour", [ot.get(1), ot.get(2)], [h_mtb[0] / 2, (h_mtb[0] + h_mtb[1]) / 2],
                 1e-6, "Shadow price minus the overtime rate, where overtime is at its limit (Feb, Mar).")
        ctx.near("valid range of the March shadow price", (weld.valid_down[2], weld.valid_up[2]), (218, 280), 1e-6,
                 "Up: 32 more March hours would free all of January's overtime. Down: 30 fewer can still be met "
                 "by January's unused overtime.")
        e = sop.economics
        holding = 25 * h_mtb[0] + 50 * h_mtb[1]
        ctx.near("holding cost", e.holding, holding, 1e-6, "25 MTB at the end of Jan, 50 at the end of Feb.")
        ctx.near("total cost", e.total_cost, 550 * 350 + 160 * 500 + 150 * 150 + holding, 1e-6,
                 "Conversion (ROAD 50 + 300, MTB 100 + 400 per unit) + 150 h of overtime + holding.")
        mc = {dl.product: dl.marginal_cost for dl in sop.demand}
        ctx.near("marginal cost of one more MTB in March", mc["MTB"][2], 500 + 2 * weld.shadow_price[2], 1e-6)

    with ctx.step("Profit mode with 25 % more demand", "sop", "POST /api/sop",
                  "Demand now needs 1,087.5 h against 900 h. Checked against an LP formulated independently."):
        raw = json.loads(ds.model_dump_json())
        raw["sop"] = {"mode": "profit", "demand_factor": 1.25}
        prof = c.sop(Dataset.model_validate(raw))
        obj, sol = independent_lp(1.25, True)
        ctx.near("profit = independent LP optimum", prof.economics.profit, -obj, 1e-4)
        lost = {dl.product: sum(dl.lost) for dl in prof.demand}
        ctx.near("lost demand by product", [lost["ROAD"], lost["MTB"]], [0, 200 - (900 - 687.5) / 2], 1e-6,
                 "Margin per welding hour: ROAD 650, MTB 500. Every ROAD is served (687.5 h); the other 212.5 h make "
                 "106.25 of the 200 MTB.")
        ctx.near("all overtime used", one(prof.resources, resource="WELD").overtime, [62, 56, 62], 1e-6,
                 "Even the less profitable MTB earns 500 − 150 per overtime hour.")

    with ctx.step("Release to MRP", "sop+plan", "POST /api/sop/release → POST /api/plan",
                  "MRP plans at infinite capacity: it must be given the build-ahead, not just the demand."):
        rel_ds, rel = c.release_sop(ds)
        ctx.eq("release (records, build-ahead nodes)", (rel.records, rel.target_nodes), (6, 1))
        plan = c.plan(rel_ds)
        made: dict[tuple[str, int], float] = {}
        for o in by(plan.orders, kind="make"):
            k = (o.product, o.need_date.month)
            made[k] = made.get(k, 0.0) + o.qty
        ctx.near("MRP production by month = S&OP", [made.get(("ROAD", m), 0) for m in (1, 2, 3)]
                 + [made.get(("MTB", m), 0) for m in (1, 2, 3)], [150, 150, 250, 65, 65, 30], 1e-6)
        ctx.near("MTB projected stock at month end", [b.projected_on_hand for b in one(plan.nodes, product="MTB").buckets],
                 [25, 50, 0], 1e-6)
        ctx.eq("no capacity overload", [e.code for e in plan.exceptions if e.code == "CAPACITY_OVERLOAD"], [],
               "Without the build-ahead MRP would load March with 410 h against 310.")

    with ctx.step("Appraise a weekend crew", "finance", "POST /api/finance",
                  "+40 h/week on the welding cell for 50,000 capex and 20,000 a year, over 5 years at the 12 % WACC."):
        fin = c.finance(ds)
        a = one(fin.capacity, id="OPT-WEEKEND")
        ctx.near("shadow-price estimate", a.dual_estimate, 32 * sum(weld.shadow_price), 1e-6,
                 "Each month's shadow price holds for 32 more hours only: Σ price × 32.")
        ctx.eq("the option is beyond the valid range", a.within_range, False)
        ctx.near("re-solved saving over the 90 days", a.objective_saving, 150 * 150 + holding, 1e-6,
                 "With 514 more hours no overtime and no build-ahead are needed.")
        annual = (150 * 150 + holding) * 365 / 90
        ctx.near("annual cash", a.annual_cash, annual, 1e-6)
        flows = [-50000.0] + [annual - 20000] * 5
        npv = sum(f / 1.12 ** k for k, f in enumerate(flows))
        ctx.near("NPV at 12 %", a.npv, npv, 1e-4)
        ctx.near("IRR (bisection)", a.irr, _irr(flows), 1e-6)
        ctx.near("payback (years)", a.payback_years, 50000 / (annual - 20000), 1e-9)


SCENARIO = Scenario(
    id="s3-bikes", title="Capacity crunch: S&OP by hand", company="Summit Bikes",
    story="One welding cell makes road and mountain bikes. Spring demand exceeds regular capacity, overtime is "
          "limited, and holding stock costs 24 % a year. The optimal build-ahead, overtime and shadow prices are "
          "derived by hand; profit mode is checked against an independent LP; the plan is released to MRP, which "
          "must keep the build-ahead; and a weekend crew is appraised with NPV and IRR.",
    proves=["LP optimum matches a hand solution", "shadow prices and their valid ranges", "value of overtime",
            "profit mode = margin per bottleneck hour", "release keeps the build-ahead in MRP",
            "capacity investment: dual estimate, re-solve, NPV, IRR, payback"],
    stages=["readiness", "sop", "plan", "finance"],
    found=["Releasing the S&OP plan dropped its build-ahead, so MRP overloaded the peak month it was meant to protect"],
    build=build, run=run)
