"""S7 · Oakleaf Bakery: sequencing one oven through allergen changeovers.

Five released production orders and one planned order share a single oven that runs 06:00–22:00 every
day. Breads belong to three setup groups: plain, seeded and nut. Cleaning down after nuts takes four
hours, so the order of the week matters: earliest-due-date sequencing makes a plain loaf late and wastes
setup; the local search should find the best sequence; a planner's manual sequence must be respected
and costed; and the independent feasibility checker must find nothing wrong with any of them.

The expected answers come from an oracle written here: its own shift clock and setup rule, and a full
enumeration of all 720 sequences.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from ..model import Dataset
from .harness import Client, Ctx, Scenario, d, one

START = d("2026-06-01")
SHIFT = (6.0, 22.0)
FULL_SETUP, MINOR = 2.0, 0.2
MATRIX = {("plain", "seeded"): 1, ("plain", "nut"): 2, ("seeded", "nut"): 1, ("seeded", "plain"): 3,
          ("nut", "plain"): 4, ("nut", "seeded"): 4}
GROUP = {"P1": "plain", "P2": "plain", "P3": "plain", "S1": "seeded", "N1": "nut"}
FIRM = [("MO-A", "N1", 400, "2026-06-02"), ("MO-B", "P1", 300, "2026-06-02"), ("MO-C", "S1", 200, "2026-06-03"),
        ("MO-D", "P2", 300, "2026-06-02"), ("MO-E", "N1", 200, "2026-06-03")]


def build() -> dict:
    return {
        "settings": {"company_name": "Oakleaf Bakery", "currency": "GBP", "planning_start": START.isoformat(),
                     "horizon_days": 14, "bucket": "day", "default_calendar": "CAL-7"},
        "calendars": [{"id": "CAL-7", "name": "Seven-day bakery", "workdays": [0, 1, 2, 3, 4, 5, 6]}],
        "scheduling": {"horizon_days": 7, "day_start_hour": SHIFT[0], "minor_setup_factor": MINOR,
                       "tardiness_weight": 4, "setup_weight": 1},
        "locations": [{"id": "BAKE", "name": "Oakleaf bakehouse", "type": "plant"},
                      {"id": "SHOPS", "name": "Farm shops", "type": "customer"}],
        "products": [{"id": p, "name": f"{g.title()} loaf {p}", "type": "FG", "setup_group": g, "price": 3}
                     for p, g in GROUP.items()],
        "location_products": [{"location": "BAKE", "product": p} for p in GROUP],
        "resources": [
            {"id": "OVEN", "name": "Deck oven", "location": "BAKE", "shifts_per_day": 2, "hours_per_shift": 8,
             "efficiency": 1.0},
            {"id": "BAKERS", "name": "Bakers", "location": "BAKE", "kind": "labor", "units": 1, "shifts_per_day": 1,
             "hours_per_shift": 8, "efficiency": 1.0},
        ],
        "production_sources": [{"id": f"PV-{p}", "location": "BAKE", "product": p,
                                "operations": [{"seq": 10, "resource": "OVEN", "setup_hours": FULL_SETUP,
                                                "run_hours_per_unit": 0.01, "labor_resource": "BAKERS",
                                                "labor_hours_per_unit": 0.01}]} for p in GROUP],
        "changeovers": [{"from_group": a, "to_group": b, "hours": h} for (a, b), h in MATRIX.items()],
        "receipts": [{"id": i, "kind": "production", "location": "BAKE", "product": p, "qty": q, "due_date": due,
                      "start_date": START.isoformat(), "source": f"PV-{p}"} for i, p, q, due in FIRM],
        "lanes": [{"id": "L-SHOPS", "origin": "BAKE", "destination": "SHOPS", "modes": [{"transit_days": 0}]}],
        # a new rye-style plain loaf for Friday: MRP plans it, the scheduler picks it up
        "demand": [{"location": "SHOPS", "product": "P3", "date": "2026-06-05", "qty": 100}],
    }


# ---- the oracle: its own clock, setup rule and exhaustive search ------------------------------------
def _open(t: float) -> float:
    day = math.floor(t / 24)
    while True:
        s, e = day * 24 + SHIFT[0], day * 24 + SHIFT[1]
        if t < e - 1e-9:
            return max(t, s)
        day += 1


def _advance(t: float, work: float) -> tuple[float, float]:
    start = cur = _open(t)
    left = work
    while left > 1e-9:
        end = math.floor(cur / 24) * 24 + SHIFT[1]
        if left <= end - cur + 1e-9:
            return start, cur + left
        left -= end - cur
        cur = _open(end)
    return start, cur


@dataclass
class J:
    id: str
    product: str
    run: float
    release: float
    due: float


def _setup(prev: J | None, j: J) -> float:
    if prev is None:
        return FULL_SETUP
    if prev.product == j.product:
        return 0.0
    if GROUP[prev.product] == GROUP[j.product]:
        return FULL_SETUP * MINOR
    return MATRIX[(GROUP[prev.product], GROUP[j.product])]


def simulate(seq: list[J]) -> dict:
    free, prev = 0.0, None
    setup = tard = 0.0
    done: dict[str, float] = {}
    baking: dict[str, float] = {}
    for j in seq:
        su = _setup(prev, j)
        _, s1 = _advance(max(free, j.release), su)
        r0, r1 = _advance(s1, j.run)
        done[j.id], baking[j.id] = r1, r0
        setup += su
        tard += max(0.0, r1 - j.due)
        free, prev = r1, j
    return {"setup": setup, "tardiness": tard, "objective": 4 * tard + setup, "completion": done, "baking": baking,
            "late": sum(1 for j in seq if done[j.id] > j.due + 1e-9), "order": [j.id for j in seq]}


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Plan: the new loaf needs one make order", "plan", "POST /api/plan",
                  "The five firm orders cover their own products; P3 has no stock, so MRP plans one oven run."):
        plan = c.plan(ds)
        (f,) = [o for o in plan.orders if o.kind == "make"]
        ctx.eq("planned make order", (f.product, f.qty, f.due_date), ("P3", 100, d("2026-06-05")))

    with ctx.step("Schedule by earliest due date", "schedule", "POST /api/schedule",
                  "EDD runs the nut order first; cleaning down to plain costs 4 h and pushes MO-D past midnight."):
        raw = ds.model_copy(update={"scheduling": ds.scheduling.model_copy(update={"improve": False})})
        edd = c.schedule(raw)
        jobs = {o.id: J(o.id, o.product, o.qty * 0.01, o.release, o.due) for o in edd.orders}
        ctx.eq("orders on the board (release, due in hours from Monday 00:00)",
               {k: (j.release, j.due) for k, j in sorted(jobs.items())},
               {"MO-A": (0, 24), "MO-B": (0, 24), "MO-C": (0, 48), "MO-D": (0, 24), "MO-E": (0, 48),
                f.id: ((f.start_date - START).days * 24, 96)},
               "Firm orders are released now; the planned order on its MRP start date, due on its MRP due date.")
        ref = simulate([jobs[k] for k in ["MO-A", "MO-B", "MO-D", "MO-C", "MO-E", f.id]])
        ctx.eq("EDD sequence", one(edd.resources, id="OVEN").sequence,
               ["MO-A:10", "MO-B:10", "MO-D:10", "MO-C:10", "MO-E:10", f"{f.id}:10"],
               "Due 24 h: A, B, D (ties by id); then C, E; then the planned order.")
        ctx.near("EDD result (setup h, tardiness h, late orders, objective)",
                 (edd.kpis.setup_hours, edd.kpis.tardiness_hours, edd.kpis.late_orders, edd.kpis.objective),
                 (ref["setup"], ref["tardiness"], ref["late"], ref["objective"]), 1e-6,
                 "A 2 h setup + 4 h (06–12); nut→plain 4 h, B 16–19; D 0.4 h minor setup, 19:24–22:00 and 0.4 h "
                 "on Tuesday: done 30.4 h, 6.4 h late; C +1 h, E +1 h, the planned order +4 h (nut→plain). "
                 "Setup 12.4 h, objective 4 × 6.4 + 12.4 = 38.")
        ctx.near("MO-D completion", one(edd.orders, id="MO-D").completion, 30.4, 1e-6)
        ctx.eq("no violations (EDD)", edd.violations, [])

    with ctx.step("Improve the sequence", "schedule", "POST /api/schedule",
                  "Campaign and swap moves. The oracle enumerates all 720 sequences: the optimum runs the plain "
                  "campaign first, then the nuts, and leaves seeded for last."):
        best = min((simulate(list(p)) for p in itertools.permutations(jobs.values())),
                   key=lambda r: (r["objective"], r["order"]))
        opt = c.schedule(ds)
        ctx.near("improved objective = enumerated optimum", opt.kpis.objective, best["objective"], 1e-6,
                 "B, D (2 + 0.4 h), plain→nut 2 h, A, E (same loaf: no setup), nut→seeded 4 h, C, then seeded→plain "
                 "3 h for the Friday order: 11.4 h of setup and nothing late.")
        ctx.near("tardiness and late orders", (opt.kpis.tardiness_hours, opt.kpis.late_orders), (0, 0), 1e-9)
        seq = [k.split(":")[0] for k in one(opt.resources, id="OVEN").sequence]
        ctx.true("the sequence is one of the optimal ones", simulate([jobs[k] for k in seq])["objective"]
                 <= best["objective"] + 1e-9, actual=seq)
        ctx.eq("changeovers (group changes)", opt.kpis.changeovers, 3,
               "plain→nut, nut→seeded, seeded→plain; plain→plain and nut→nut are not changeovers.")
        ctx.true("never worse than EDD", opt.kpis.objective <= opt.baseline.objective + 1e-9,
                 actual=(opt.baseline.objective, opt.kpis.objective))
        ctx.eq("no violations (improved)", opt.violations, [])
        a = one(opt.ops, order="MO-A")
        ctx.eq("MO-A is set up from the plain group", a.setup_from, "plain")

    with ctx.step("Labour against headcount", "schedule", "POST /api/schedule",
                  "One baker (8 h a day) tends the oven while it bakes: 0.01 h per loaf."):
        sim = simulate([jobs[k] for k in seq])
        monday = sum(max(0.0, min(sim["completion"][k], SHIFT[1]) - max(sim["baking"][k], SHIFT[0]))
                     for k in jobs if sim["baking"][k] < SHIFT[1])
        day0 = one(opt.labour, date=START)
        ctx.near("Monday: baking hours needed vs one baker", (day0.required, day0.available, day0.overload),
                 (monday, 8, True), 1e-6,
                 "B, D and A bake on Monday and E starts at 20:24: 3 + 3 + 4 + 1.6 = 11.6 h for 8 h of baker.")
        ctx.near("total baker hours = total loaves × 0.01", sum(x.required for x in opt.labour),
                 sum(j.run for j in jobs.values()), 1e-6)

    with ctx.step("The planner overrides: seeded first", "schedule", "POST /api/schedule {sequence}",
                  "A customer wants seeded loaves at 10:00. The planner drags MO-C to the front; the rest follows "
                  "in due-date order and the cost of the choice is shown."):
        man = c.schedule(ds, {"OVEN": ["MO-C:10"]})
        ref = simulate([jobs[k] for k in ["MO-C", "MO-A", "MO-B", "MO-D", "MO-E", f.id]])
        ctx.eq("sequence respected", one(man.resources, id="OVEN").sequence[:5],
               ["MO-C:10", "MO-A:10", "MO-B:10", "MO-D:10", "MO-E:10"])
        ctx.near("MO-C done by 10:00", one(man.orders, id="MO-C").completion, 10, 1e-9, "2 h setup + 2 h from 06:00.")
        ctx.near("cost of the override (objective)", man.kpis.objective, ref["objective"], 1e-6,
                 "C, then A (seeded→nut 1 h) to 15:00, B (nut→plain 4 h) to 22:00 exactly, D waits for Tuesday: "
                 "9.4 h late.")
        ctx.eq("search mode", man.search.mode, "manual")
        ctx.eq("no violations (manual)", man.violations, [])


SCENARIO = Scenario(
    id="s7-bakery", title="Sequencing through changeovers", company="Oakleaf Bakery",
    story="Six loaves' worth of orders share one oven with allergen clean-downs between plain, seeded and nut "
          "bread. Earliest-due-date makes an order late; the local search must reach the optimum found by "
          "enumerating all 720 sequences; a planner's manual sequence is respected and costed.",
    proves=["firm and planned orders on one board", "shift windows and overnight pauses",
            "sequence-dependent changeover matrix", "minor setups within a group", "EDD baseline",
            "local search reaches the exact optimum", "manual sequencing", "labour load vs headcount",
            "independent feasibility checker"],
    stages=["plan", "schedule"],
    build=build, run=run)
