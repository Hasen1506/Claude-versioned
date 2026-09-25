"""S9 · one flow, many companies: the whole workflow over randomly generated companies, checked by properties.

The hand-built scenarios (S1–S8) check *values*: each checkpoint has an answer worked out by hand, so each
needs its own small company whose numbers a person can follow. That is what makes them strong (a wrong
number is caught even when every module agrees with every other) and what makes them few.

This scenario checks *relations* instead. ``company(seed)`` builds a random but valid company (a plant with
one or two BOM levels, 0–2 DCs, 1–3 customers, random lot-size rules, safety-stock methods, lead times,
history, orders and opening stock), and ``flow`` takes it through the same workflow a planner follows:

    readiness → forecast + release → S&OP + release → MRP → inventory placement + apply → MRP
    → promise + commit → firm → post a journal → roll forward (twice) → finance → control tower → versions

Nobody knows the right plan for a random company, but many things must hold for every one of them:

* **invariants** — material balances, orders split into what they are for, dates in order, a promise never
  confirms more than was ordered, stock after a roll is the journal's sum, the books close, a version's
  hash is the hash of what it stores;
* **agreements between modules** — S&OP plans the demand MRP plans, MRP holds the safety stock the
  inventory screen reports, a single-echelon recommendation for a node's own policy is that policy's
  safety stock, an applied placement is what MRP then holds;
* **metamorphic relations** — the same company in another order, or shifted by whole weeks, gets the same
  plan; more safety stock never means less supply; firming everything and planning again changes nothing;
  a movement posted late and rolled again ends where posting it on time would have; rolling in two steps
  ends where rolling once does.

A failed property names the seeds it fails for; ``python -m scp.scenarios s9-generated --seed 17`` re-runs
one company, and ``company(17)`` is its dataset.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import re
import traceback
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..demand import ForecastResult
from ..inventory import InventoryResult, PlacementApplied
from ..model import Dataset
from ..plan import PlanResult
from ..plan.costing import component_factor
from ..plan.leadtime import location_calendar
from ..promise import PromiseResult
from ..sop import SopResult
from ..time import Buckets
from ..versions.store import canonical, sha
from .harness import Client, Ctx, Scenario

SEEDS: Sequence[int] = range(12)
START0 = dt.date(2026, 3, 2)               # a Monday; each company starts a random number of weeks later
WEEKS = 12
EPS = 1e-6
STATISTICAL = ("service_level", "fill_rate")


# ---- the company generator ---------------------------------------------------------------------------------
def company(seed: int) -> dict:
    """A random, valid company: every choice below is one a real planner could make."""
    rng = random.Random(seed)
    start = START0 + dt.timedelta(weeks=rng.randint(0, 30))
    horizon = 7 * WEEKS
    workdays = rng.choice([[0, 1, 2, 3, 4], [0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5, 6]])
    n_rm, n_sf, n_fg = rng.randint(1, 3), rng.randint(0, 1), rng.randint(1, 2)
    n_dc, n_cus = rng.randint(0, 2), rng.randint(1, 3)
    rms = [f"RM{i}" for i in range(n_rm)]
    sfs = [f"SF{i}" for i in range(n_sf)]
    fgs = [f"FG{i}" for i in range(n_fg)]
    dcs = [f"DC{i}" for i in range(n_dc)]
    cus = [f"K{i}" for i in range(n_cus)]
    locs = ([{"id": "PL", "type": "plant"}, {"id": "SUP", "type": "supplier"}] + [{"id": x, "type": "dc"} for x in dcs]
            + [{"id": x, "type": "customer"} for x in cus])
    prods = ([{"id": p, "type": "RM", "weight_kg": 1} for p in rms] + [{"id": p, "type": "SFG"} for p in sfs]
             + [{"id": p, "type": "FG", "weight_kg": 2, "price": rng.randint(60, 200)} for p in fgs])

    def policy() -> dict:
        ls = rng.choice([{"policy": "L4L"}, {"policy": "FIXED", "fixed_qty": rng.choice([40, 100, 250])},
                         {"policy": "POQ", "periods": rng.randint(1, 3)}, {"policy": "EOQ", "ordering_cost": 300},
                         {"policy": "L4L", "min_qty": 30, "rounding_qty": 10}])
        cv = rng.choice([0.2, 0.3, 0.5])
        review = rng.choice([0, 0, 7])
        ss = rng.choice([{"method": "none"}, {"method": "fixed", "qty": rng.randint(5, 60)},
                         {"method": "days_of_supply", "days": rng.randint(2, 10)},
                         {"method": "service_level", "service_level": rng.choice([0.9, 0.95, 0.99]), "demand_cv": cv,
                          "review_period_days": review},
                         {"method": "fill_rate", "service_level": rng.choice([0.95, 0.98, 0.995]), "demand_cv": cv,
                          "review_period_days": review}])
        return {"lot_sizing": ls, "safety_stock": ss, "on_hand": rng.choice([0, rng.randint(20, 300)]),
                "unit_cost": rng.randint(5, 40)}

    lps = [{"location": "PL", "product": p, **policy()} for p in rms + sfs + fgs]
    lps += [{"location": x, "product": p, **policy()} for x in dcs for p in fgs]
    srcs = []
    for p in sfs + fgs:
        lower = rms + (sfs if p in fgs else [])
        comps = rng.sample(lower, k=rng.randint(1, len(lower)))
        srcs.append({"id": f"PV-{p}", "location": "PL", "product": p,
                     "components": [{"product": q, "qty": rng.choice([1, 2, 0.5])} for q in comps],
                     "operations": [{"seq": 10, "resource": "R1", "run_hours_per_unit": 0.01,
                                     "queue_workdays": rng.choice([0, 1, 2])}]})
    pur = [{"id": f"PU-{p}", "supplier": "SUP", "product": p, "location": "PL", "price": rng.randint(2, 20),
            "lead_time_days": rng.randint(2, 10), "lead_time_std_days": rng.choice([0, 0, 1]),
            "moq": rng.choice([0, 0, 50])} for p in rms]
    lanes = [{"id": f"L-PL-{x}", "origin": "PL", "destination": x, "products": fgs,
              "modes": [{"transit_days": rng.randint(1, 3), "cost_per_shipment": 50}]} for x in dcs]
    served_by = {k: rng.choice(dcs) if dcs else "PL" for k in cus}
    lanes += [{"id": f"L-{o}-{k}", "origin": o, "destination": k, "modes": [{"transit_days": rng.randint(0, 2)}]}
              for k, o in served_by.items()]
    demand, history = [], []
    for k in cus:
        for p in rng.sample(fgs, k=rng.randint(1, len(fgs))):
            mu = rng.randint(20, 120)
            price = next(x["price"] for x in prods if x["id"] == p)
            for w in range(26):
                history.append({"location": k, "product": p, "date": (start - dt.timedelta(weeks=26 - w)).isoformat(),
                                "qty": max(0, round(rng.gauss(mu, 0.25 * mu))), "price": price})
            for w in range(WEEKS):
                demand.append({"location": k, "product": p, "date": (start + dt.timedelta(weeks=w)).isoformat(),
                               "qty": mu, "period_days": 7})
            for w in range(4):
                if rng.random() < 0.6:
                    day = start + dt.timedelta(days=7 * w + rng.randint(0, 6))
                    demand.append({"id": f"SO-{k}-{p}-{w}", "location": k, "product": p, "date": day.isoformat(),
                                   "qty": rng.randint(max(1, mu // 4), mu), "kind": "sales_order",
                                   "priority": rng.randint(1, 9)})
    opening = [{"id": f"OPEN-{lp['location']}-{lp['product']}", "date": (start - dt.timedelta(days=1)).isoformat(),
                "type": "opening", "location": lp["location"], "product": lp["product"], "qty": lp["on_hand"]}
               for lp in lps if lp["on_hand"] > 0]
    return {
        "settings": {"company_name": f"Generated company {seed}", "planning_start": start.isoformat(),
                     "horizon_days": horizon, "bucket": rng.choice(["week", "day"]), "default_calendar": "CAL"},
        "calendars": [{"id": "CAL", "workdays": workdays}],
        "locations": locs, "products": prods, "location_products": lps,
        "resources": [{"id": "R1", "location": "PL", "units": 4, "efficiency": 1.0}],
        "production_sources": srcs, "purchasing_sources": pur, "lanes": lanes,
        "demand": demand, "history": history, "movements": opening, "sop": {"bucket": "week"},
    }


# ---- one run of the flow -------------------------------------------------------------------------------------
@dataclass
class Run:
    seed: int
    ds: Dataset | None = None
    out: dict[str, Any] = field(default_factory=dict)     # every intermediate dataset and result, by name
    error: str | None = None

    def __getitem__(self, k: str) -> Any:
        return self.out[k]


def _raw(ds: Dataset) -> dict:
    return json.loads(ds.model_dump_json())


def _with(ds: Dataset, **lists: list) -> Dataset:
    raw = _raw(ds)
    for k, v in lists.items():
        raw[k] = raw.get(k, []) + v
    return Dataset.model_validate(raw)


def journal(ds: Dataset, until: dt.date, rng: random.Random) -> list[dict]:
    """What the shop floor posts before ``until``: firm receipts (some late, some short) with the issues they
    draw, and a sale for every confirmed schedule line that ships (some short)."""
    out: list[dict] = []
    sup = {p.id: p.supplier for p in ds.purchasing_sources}

    def mv(typ: str, day: dt.date, loc: str, prod: str, qty: float, **kw: Any) -> None:
        if qty > EPS:
            out.append({"id": f"GM-{len(out) + 1:04d}", "date": day.isoformat(), "type": typ, "location": loc,
                        "product": prod, "qty": round(qty, 6), **kw})

    for rc in ds.receipts:
        day = rc.due_date + dt.timedelta(days=rng.choice([0, 0, 0, 1, 3]))
        if day >= until:
            continue
        cp = sup.get(rc.source or "") if rc.kind.value == "purchase" else None
        if rc.kind.value == "transfer":
            cp = next((ln.origin for ln in ds.lanes if ln.id == rc.source), None)
        mv("receipt", day, rc.location, rc.product, rc.qty * rng.choice([1, 1, 1, 0.5]), reference=rc.id, counterparty=cp)
        for rv in rc.reservations:
            mv("transfer_out" if rc.kind.value == "transfer" else "issue", min(rv.date, day), rv.location, rv.product,
               rv.qty, reference=rc.id)
    dem = {d.id: d for d in ds.demand if d.id}
    for c in ds.confirmations:
        if c.ship_date < until and c.order in dem:
            mv("sale", c.ship_date, c.ship_from, dem[c.order].product, c.qty * rng.choice([1, 1, 1, 0.9]),
               reference=c.order, counterparty=dem[c.order].location)
    return out


def flow(c: Client, seed: int) -> Run:
    run = Run(seed)
    o = run.out
    rng = random.Random(10_000 + seed)
    try:
        ds = run.ds = Dataset.model_validate(company(seed))
        start = ds.settings.planning_start
        o["issues"] = c.validate(ds)
        o["forecast"] = c.forecast(ds)
        ds1, o["released"] = c.release_forecast(ds)
        o["ds1"], o["plan1"] = ds1, c.plan(ds1)
        o["sop"] = c.sop(ds1)
        ds2, o["sop_release"] = c.release_sop(ds1)
        o["ds2"], o["plan2"] = ds2, c.plan(ds2)
        o["inventory"] = c.inventory(ds2)
        ds3, o["applied"] = c.apply_placement(ds2)
        o["ds3"], o["plan3"] = ds3, c.plan(ds3)
        o["promise"] = c.promise(ds3)
        ds4, o["commit"] = c.commit(ds3)
        o["ds4"], o["plan4"], o["repromise"] = ds4, c.plan(ds4), c.promise(ds4)
        o["all_ds"], o["firm_all"] = c.firm(ds4, within_days=ds.settings.horizon_days)
        o["plan_all"] = c.plan(o["all_ds"])
        ds5, o["firm"] = c.firm(ds4)
        t1, t2 = start + dt.timedelta(weeks=1), start + dt.timedelta(weeks=2)
        posted = journal(ds5, t2, rng)
        ds6 = o["ds6"] = _with(ds5, movements=posted)
        o["t1"], o["t2"], o["posted"] = t1, t2, posted
        r1, o["roll1_report"] = c.roll(ds6, t1)
        o["roll1"] = r1
        o["roll1_again"], _ = c.roll(r1, t1)
        o["roll2"], o["roll2_report"] = c.roll(r1, t2)
        o["roll_once"], _ = c.roll(ds6, t2)
        early = [m for m in posted if dt.date.fromisoformat(m["date"]) < t1]
        if early:                     # one movement posted only after the first roll
            late = rng.choice(early)
            held = Dataset.model_validate({**_raw(ds5), "movements": _raw(ds5)["movements"]
                                           + [m for m in posted if m is not late]})
            h1, _ = c.roll(held, t1)
            o["late_roll2"], _ = c.roll(_with(h1, movements=[late]), t2)
            o["late"] = late
        o["finance"] = c.finance(ds3)
        o["tower"] = c.tower(o["roll2"])
        meta = c.save_base(o["roll2"], f"Generated {seed}")
        o["version"], o["version_doc"] = meta, c.get_version(meta.id)
        o["plan_perm"] = c.plan(permuted(ds3, rng))
        o["shift"] = rng.randint(1, 8)
        o["plan_shift"] = c.plan(shifted(ds3, 7 * o["shift"]))
        node, extra = more_safety_stock(ds3, rng)
        if node:
            o["ss_node"], o["plan_ss"] = node, c.plan(extra)
    except Exception as e:  # noqa: BLE001 — a crash is a counterexample like any other
        run.error = f"{type(e).__name__}: {e} ({traceback.format_exc(limit=-1).strip().splitlines()[-2].strip()})"
    return run


# ---- the metamorphic transformations -----------------------------------------------------------------------------
def permuted(ds: Dataset, rng: random.Random) -> Dataset:
    raw = _raw(ds)
    for v in raw.values():
        if isinstance(v, list):
            rng.shuffle(v)
    for s in raw.get("production_sources", []):
        rng.shuffle(s["components"])
    return Dataset.model_validate(raw)


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def shifted(ds: Dataset, days: int) -> Dataset:
    """Every date in the dataset moved by ``days`` (a whole number of weeks keeps every weekday)."""
    def walk(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str) and _DATE.match(x):
            return (dt.date.fromisoformat(x) + dt.timedelta(days=days)).isoformat()
        return x
    return Dataset.model_validate(walk(_raw(ds)))


def more_safety_stock(ds: Dataset, rng: random.Random) -> tuple[tuple[str, str] | None, Dataset]:
    """One lot-for-lot node with a fixed or no safety stock gets more of it. Only where nothing imposes a minimum
    lot (an EOQ, a fixed lot, a minimum or rounding quantity, a supplier's MOQ or pack, a minimum production
    lot): under one, a bigger buffer can absorb a small later shortfall that would otherwise be ordered as a
    whole lot, so total supply can fall, rightly."""
    def unconstrained(lp: Any) -> bool:
        ls = lp.lot_sizing
        if ls.policy.value != "L4L" or ls.min_qty or ls.rounding_qty or ls.max_qty is not None:
            return False
        node = (lp.location, lp.product)
        return (all(not p.moq and not p.rounding_qty for p in ds.purchasing_sources if (p.location, p.product) == node)
                and all(not p.min_lot for p in ds.production_sources if (p.location, p.product) == node))
    cands = [lp for lp in ds.location_products
             if lp.safety_stock.method.value in ("none", "fixed") and lp.strategy.value != "MTO" and unconstrained(lp)]
    if not cands:
        return None, ds
    lp = rng.choice(cands)
    raw = _raw(ds)
    for x in raw["location_products"]:
        if (x["location"], x["product"]) == (lp.location, lp.product):
            x["safety_stock"] = {"method": "fixed", "qty": (lp.safety_stock.qty or 0) + rng.randint(10, 100)}
    return (lp.location, lp.product), Dataset.model_validate(raw)


# ---- properties: each returns what is wrong, as text ---------------------------------------------------------
def plan_violations(ds: Dataset, r: PlanResult) -> list[str]:
    bad: list[str] = []
    if not r.ok:
        return ["the plan did not run: " + "; ".join(i.message for i in r.issues if i.severity == "error")[:200]]
    b = Buckets(ds.settings)
    n = len(b)
    reqs: dict[tuple, list[float]] = defaultdict(lambda: [0.0] * n)
    recs: dict[tuple, list[float]] = defaultdict(lambda: [0.0] * n)
    for q in r.requirements:
        i = b.index_of(q.date)
        if 0 <= i < n:
            reqs[(q.location, q.product)][i] += q.qty
    for x in [(o.location, o.product, o.available_date, o.qty) for o in r.orders] + \
             [(rc.location, rc.product, rc.date, rc.qty) for rc in r.receipts]:
        i = b.index_of(x[2])
        if 0 <= i < n:
            recs[(x[0], x[1])][i] += x[3]
    for nd in r.nodes:
        key = (nd.location, nd.product)
        poh = nd.on_hand
        for i, bk in enumerate(nd.buckets):
            poh += recs[key][i] - reqs[key][i]
            if abs(bk.projected_on_hand - poh) > 1e-6 * max(1.0, abs(poh)):
                bad.append(f"{key[0]}/{key[1]} bucket {i}: projected {bk.projected_on_hand:g}, balance {poh:g}")
                break
    orders = {o.id: o for o in r.orders}
    pegged: dict[str, float] = defaultdict(float)
    by_req: dict[str, float] = defaultdict(float)
    for p in r.pegs:
        pegged[p.supply_id] += p.qty
        by_req[p.requirement_id] += p.qty
    req_qty = {q.id: q.qty for q in r.requirements}
    bad += [f"requirement {rid} pegged {q:g} of {req_qty[rid]:g}" for rid, q in by_req.items() if q > req_qty[rid] + EPS]
    for o in r.orders:
        tag = f"{o.id} ({o.kind} {o.location}/{o.product})"
        if abs(pegged[o.id] + o.lot_excess - o.qty) > 1e-6 * max(1.0, o.qty):
            bad.append(f"{tag}: pegged {pegged[o.id]:g} + unpegged {o.lot_excess:g} ≠ qty {o.qty:g}")
        if o.for_buffer < -EPS or o.for_lot_size < -EPS or o.for_buffer + o.for_lot_size > o.qty + EPS:
            bad.append(f"{tag}: buffer {o.for_buffer:g} + lot size {o.for_lot_size:g} exceed qty {o.qty:g}")
        if not o.start_date <= o.due_date <= o.available_date or o.start_date < ds.settings.planning_start:
            bad.append(f"{tag}: dates start {o.start_date} due {o.due_date} available {o.available_date}")
        if o.kind == "buy" and not o.start_in_past:
            pu = ds.purchasing_source_by_id[o.source_id]
            if not location_calendar(ds, pu.location).is_workday(o.start_date):
                bad.append(f"{tag}: placed on {o.start_date:%a %d %b}, not a working day")
    for q in r.requirements:
        if q.parent_order not in orders:        # none, or a firm receipt's reservation
            continue
        o = orders[q.parent_order]
        want = o.qty if q.kind == "transfer" else o.qty * component_factor(ds, o.source_id, q.product)
        if abs(q.qty - want) > 1e-6 * max(1.0, want):
            bad.append(f"{q.id}: {q.qty:g} for order {o.id} of {o.qty:g}, expected {want:g}")
    return bad


def _independent(r: PlanResult, lo: dt.date, hi: dt.date) -> dict[tuple[str, str], float]:
    tot: dict[tuple[str, str], float] = defaultdict(float)
    for q in r.requirements:
        if q.kind in ("forecast", "sales_order") and q.date < hi:
            tot[(q.location, q.product)] += q.qty
    return tot


def _by_bucket(r: PlanResult, sop: SopResult, node: tuple[str, str]) -> list[float]:
    out = [0.0] * len(sop.buckets)
    for q in r.requirements:
        if q.kind in ("forecast", "sales_order") and (q.location, q.product) == node:
            i = next((b.index for b in sop.buckets if b.start <= q.date < b.end), 0 if q.date < sop.buckets[0].start else None)
            if i is not None:
                out[i] += q.qty
    return out


def _ss0(r: PlanResult) -> dict[tuple[str, str], float]:
    return {(n.location, n.product): n.buckets[0].safety_stock for n in r.nodes if n.buckets}


def _sig(r: PlanResult, shift: int = 0) -> list[tuple]:
    d = dt.timedelta(days=shift)
    return sorted((o.kind, o.location, o.product, o.source_id, round(o.qty, 6), o.start_date - d, o.due_date - d,
                   o.available_date - d) for o in r.orders)


def _poh(r: PlanResult) -> dict[tuple[str, str], list[float]]:
    return {(n.location, n.product): [round(b.projected_on_hand, 6) for b in n.buckets] for n in r.nodes}


def _first_diff(a: Iterable, b: Iterable) -> str:
    a, b = list(a), list(b)
    for x, y in zip(a, b, strict=False):
        if x != y:
            return f"{x} ≠ {y}"
    return f"{len(a)} ≠ {len(b)} items"


def _canon_ds(ds: Dataset) -> str:
    return canonical(ds)


def _same(a: Dataset, b: Dataset) -> list[str]:
    """The top-level lists that differ (the journal compared as a set: posting order is not content)."""
    x, y = _raw(a), _raw(b)
    for raw in (x, y):
        raw["movements"] = sorted(raw["movements"], key=lambda m: m["id"])
    return [k for k in x if x[k] != y[k]]


def _near(a: float, b: float, rel: float = 1e-6) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


# ---- the scenario -----------------------------------------------------------------------------------------
def _check(ctx: Ctx, runs: list[Run], label: str, why: str, prop: Callable[[Run], list[str] | None],
           need: Sequence[str] = ()) -> None:
    """Evaluate ``prop`` on every run that got far enough; report the seeds it fails for."""
    bad: list[str] = []
    tried = 0
    for run in runs:
        if run.ds is None or any(k not in run.out for k in need):
            continue
        tried += 1
        try:
            found = prop(run) or []
        except Exception as e:  # noqa: BLE001
            found = [f"raised {type(e).__name__}: {e}"]
        bad += [f"seed {run.seed}: {x}" for x in found[:3]]
    ctx.true(label, not bad and tried > 0, why, actual=bad[:6] or f"holds for {tried} companies",
             expect=f"holds for every company ({tried} ran this far)")


def make(seeds: Sequence[int]) -> Scenario:
    seeds = list(seeds)

    def run(ctx: Ctx, c: Client, _: Dataset) -> None:
        runs: list[Run] = []
        with ctx.step("Generate the companies and run the whole flow", "readiness", "all of them",
                      f"{len(seeds)} companies from seeds {seeds[0]}–{seeds[-1]}, each through validate, forecast, "
                      "S&OP, MRP, placement, promising, firming, a posted journal, two rolls, finance, the tower "
                      "and a saved version. A crash anywhere is a counterexample."):
            runs = [flow(c, s) for s in seeds]
            crashed = [f"seed {r.seed}: {r.error}" for r in runs if r.error]
            ctx.true("every company runs the whole flow", not crashed, actual=crashed[:6] or f"{len(runs)} ran",
                     expect="no step raises")
            _check(ctx, runs, "a generated company passes the readiness gate",
                   "Every choice the generator makes is a valid one, so an error here is a false alarm of the gate.",
                   lambda r: [f"{i.code}: {i.message}" for i in r["issues"] if i.severity == "error"], ["issues"])

        with ctx.step("Forecast and release", "demand", "POST /api/forecast/release",
                      "The consensus is written as forecast demand exactly as the forecast result shows it."):
            def released(r: Run) -> list[str]:
                fc: ForecastResult = r["forecast"]
                bad = [f"{s.key} {p.label}: interval {p.lower:g}…{p.upper:g} misses {p.final:g}"
                       for s in fc.series for p in s.forecast if not (p.lower - EPS <= p.final <= p.upper + EPS)]
                bad += [f"{s.key} {p.label}: negative forecast {p.final:g}" for s in fc.series for p in s.forecast
                        if p.final < -EPS]
                keys = {(s.location, s.product) for s in fc.series}
                got = sum(d.qty for d in r["ds1"].demand if d.kind.value == "forecast" and (d.location, d.product) in keys)
                want = sum(round(p.released_qty, 3) for s in fc.series for p in s.forecast if round(p.released_qty, 3) > 0)
                if not _near(got, want):
                    bad.append(f"released {got:g}, the result shows {want:g}")
                return bad
            _check(ctx, runs, "intervals hold the forecast; the release writes what the result shows",
                   "lower ≤ final ≤ upper, final ≥ 0, and Σ released records = Σ released_qty.", released, ["ds1"])

        with ctx.step("S&OP plans the demand MRP plans", "sop", "POST /api/sop, POST /api/sop/release",
                      "Both read the same independent demand (forecast after consumption by orders, plus the "
                      "orders), so their totals agree node by node; after the release, MRP plans each bucket's "
                      "S&OP sales in that bucket."):
            def same_demand(r: Run) -> list[str]:
                sop: SopResult = r["sop"]
                if not sop.ok:
                    return ["S&OP did not solve"]
                lo, hi = sop.buckets[0].start, sop.buckets[-1].end
                mrp = {k: v for k, v in _independent(r["plan1"], lo, hi).items() if v > EPS}
                s = {(x.location, x.product): sum(x.demand) for x in sop.demand}
                return [f"{k[0]}/{k[1]}: S&OP {s.get(k, 0):g}, MRP {mrp.get(k, 0):g}" for k in sorted(set(s) | set(mrp))
                        if not _near(s.get(k, 0.0), mrp.get(k, 0.0))]
            _check(ctx, runs, "S&OP demand = MRP independent demand, per node", "Totals over the horizon.",
                   same_demand, ["plan1", "sop"])

            def sold(r: Run) -> list[str]:
                return [f"{x.location}/{x.product}: sold {sum(x.sales):g} of {sum(x.demand):g}" for x in r["sop"].demand
                        if sum(x.sales) > sum(x.demand) + 1e-6 * max(1.0, sum(x.demand))]
            _check(ctx, runs, "S&OP never sells more than the demand", "", sold, ["sop"])

            def per_bucket(r: Run) -> list[str]:
                sop: SopResult = r["sop"]
                ds1: Dataset = r["ds1"]
                bad = []
                for x in sop.demand:
                    node = (x.location, x.product)
                    orders = [0.0] * len(sop.buckets)
                    past = False
                    for d in ds1.demand:
                        if (d.location, d.product) == node and d.kind.value == "sales_order":
                            past |= d.date < sop.buckets[0].start
                            i = next((b.index for b in sop.buckets if b.start <= d.date < b.end), None)
                            if i is not None:
                                orders[i] += d.qty
                    if past or any(o > s + EPS for o, s in zip(orders, x.sales, strict=True)):
                        continue            # an order S&OP moved or cut: MRP still plans the order itself
                    got = _by_bucket(r["plan2"], sop, node)
                    for b, (g, s) in enumerate(zip(got, x.sales, strict=True)):
                        if not _near(g, round(s, 3), 1e-3):
                            bad.append(f"{node[0]}/{node[1]} week {b}: MRP plans {g:g}, S&OP sold {s:g}")
                            break
                return bad
            _check(ctx, runs, "after the release, MRP plans each week's S&OP sales in that week",
                   "Checked for every node whose orders S&OP sells in their own week (otherwise MRP still plans "
                   "the order where it was placed, as it must).", per_bucket, ["plan2"])

        with ctx.step("MRP holds together", "plan", "POST /api/plan",
                      "On every plan the flow makes: the projection is the running balance of on-hand, receipts, "
                      "orders and requirements; pegging never over-allocates; an order is its pegged quantity plus "
                      "what is not pegged, and splits into demand, buffer and lot size; dates are in order and a "
                      "purchase order is placed on a working day; every dependent requirement is sized by its "
                      "order."):
            for name, ds_key in (("plan1", "ds1"), ("plan2", "ds2"), ("plan3", "ds3"), ("plan_all", "all_ds")):
                _check(ctx, runs, f"{name} holds every plan invariant", "",
                       lambda r, n=name, k=ds_key: plan_violations(r[k], r[n]), [name])

            def firm_all(r: Run) -> list[str]:
                before, after = r["plan4"], r["plan_all"]
                skipped = set(r["firm_all"].skipped)
                left = _sig(PlanResult.model_validate({**before.model_dump(), "orders": [o.model_dump() for o in before.orders
                                                                                         if o.id in skipped]}))
                bad = [] if _sig(after) == left else [f"orders left after firming: {_first_diff(_sig(after), left)}"]
                pa, pb = _poh(after), _poh(before)
                bad += [f"{k[0]}/{k[1]}: projection {_first_diff(pa[k], pb.get(k, []))}" for k in sorted(pa) if pa[k] != pb.get(k)]
                return bad
            _check(ctx, runs, "firming every planned order and planning again changes nothing",
                   "Firm receipts replace the planned orders one for one; only deliveries to customers (never "
                   "firmed) are planned again.", firm_all, ["plan_all"])

        with ctx.step("Inventory agrees with MRP", "inventory+plan", "POST /api/inventory, POST /api/inventory/apply",
                      "The inventory screen, MRP and the placement read one safety-stock formula."):
            def current(r: Run) -> list[str]:
                inv: InventoryResult = r["inventory"]
                ss = _ss0(r["plan2"])
                return [f"{n.location}/{n.product} ({n.current_method}): inventory {n.current_ss:g}, MRP {ss.get((n.location, n.product), 0):g}"
                        for n in inv.nodes if n.role == "stocking" and n.current_method in ("fixed", *STATISTICAL)
                        and not _near(n.current_ss, ss.get((n.location, n.product), 0.0), 1e-4)]
            _check(ctx, runs, "MRP holds the safety stock the inventory screen reports as current",
                   "Fixed, service-level and fill-rate policies (days of supply breathes with demand).", current, ["inventory"])

            def single(r: Run) -> list[str]:
                inv: InventoryResult = r["inventory"]
                lps = r["ds2"].location_product_by_key
                bad = []
                for n in inv.nodes:
                    lp = lps.get((n.location, n.product))
                    if n.role != "stocking" or not lp or lp.safety_stock.method.value not in STATISTICAL:
                        continue
                    if not _near(n.single_ss, n.current_ss, 1e-4):
                        bad.append(f"{n.location}/{n.product} ({n.current_method} {n.service_level:g}): single "
                                   f"{n.single_ss:g}, the policy holds {n.current_ss:g}")
                return bad
            _check(ctx, runs, "the single-echelon recommendation for a node's own target is its policy's stock",
                   "Same target, same demand, same lead time: a cycle-service level and a fill rate each sized "
                   "their own way.", single, ["inventory"])

            def gsm(r: Run) -> list[str]:
                inv: InventoryResult = r["inventory"]
                if any(p.lead_time_std_days for p in r["ds2"].purchasing_sources) or inv.totals is None:
                    return []
                t = inv.totals
                return [] if t.meio_cost <= t.single_cost + 1e-6 * max(1.0, t.single_cost) else \
                    [f"MEIO costs {t.meio_cost:g}, buffering every stage {t.single_cost:g}"]
            _check(ctx, runs, "the optimal placement never costs more than buffering every stage",
                   "Buffering every stage on its own lead time is one of the placements GSM chooses from (checked "
                   "where lead times are certain: the placement does not model their spread).", gsm, ["inventory"])

            def applied(r: Run) -> list[str]:
                ap: PlacementApplied = r["applied"]
                ss = _ss0(r["plan3"])
                return [f"{x.location}/{x.product}: applied {x.ss_after:g}, MRP holds {ss.get((x.location, x.product), 0):g}"
                        for x in ap.changes if not _near(ss.get((x.location, x.product), 0.0), x.ss_after)]
            _check(ctx, runs, "MRP holds the placement once it is applied", "", applied, ["plan3"])

        with ctx.step("Promises add up", "promise", "POST /api/promise/commit",
                      "A promise never confirms more than was ordered or earlier than asked; what is committed is "
                      "what was promised; promising again keeps it."):
            def adds_up(r: Run) -> list[str]:
                pr: PromiseResult = r["promise"]
                bad = []
                for x in pr.orders:
                    lines = sum(ln.qty for ln in x.lines)
                    if not _near(x.confirmed + x.unconfirmed, x.qty) or not _near(lines, x.confirmed):
                        bad.append(f"{x.order}: {lines:g} in lines, {x.confirmed:g} confirmed + {x.unconfirmed:g} ≠ {x.qty:g}")
                    bad += [f"{x.order}: delivers {ln.date} before the request {x.requested}" for ln in x.lines
                            if ln.date < x.requested]
                    bad += [f"{x.order}: ships {ln.ship_date} after delivering {ln.date}" for ln in x.lines
                            if ln.ship_date > ln.date]
                return bad
            _check(ctx, runs, "lines + unconfirmed = ordered; nothing delivered before it is asked for", "", adds_up,
                   ["promise"])

            def committed(r: Run) -> list[str]:
                conf: dict[str, float] = defaultdict(float)
                for x in r["ds4"].confirmations:
                    conf[x.order] += x.qty
                pr = {x.order: x.confirmed for x in r["commit"].orders}
                return [f"{k}: committed {conf.get(k, 0):g}, promised {v:g}" for k, v in pr.items() if not _near(conf.get(k, 0.0), v)]
            _check(ctx, runs, "the committed confirmations are the promise", "", committed, ["ds4"])

            def kept(r: Run) -> list[str]:
                a = {x.order: (x.confirmed, [(ln.date, round(ln.qty, 6)) for ln in x.lines]) for x in r["commit"].orders}
                b = {x.order: (x.confirmed, [(ln.date, round(ln.qty, 6)) for ln in x.lines]) for x in r["repromise"].orders}
                return [f"{k}: {a[k]} then {b.get(k)}" for k in a if a[k] != b.get(k)]
            _check(ctx, runs, "promising again after the commit keeps every confirmation", "", kept, ["repromise"])

        with ctx.step("The journal becomes the next plan", "execution", "POST /api/orders/firm, POST /api/actuals/roll",
                      "Firm the next two weeks, post what happened (late and short receipts, the issues they draw, "
                      "shipped schedule lines, some short), and roll forward a week, then another."):
            def stock(r: Run) -> list[str]:
                t1 = r["t1"]
                tot: dict[tuple[str, str], float] = defaultdict(float)
                for m in r["ds6"].movements:
                    if m.date < t1:
                        tot[(m.location, m.product)] += m.signed
                lps = r["roll1"].location_product_by_key
                return [f"{k[0]}/{k[1]}: {lps[k].on_hand:g} on hand, journal {q:g}" for k, q in sorted(tot.items())
                        if k in lps and not _near(lps[k].on_hand, max(0.0, round(q, 6)))]
            _check(ctx, runs, "stock after the roll is the sum of the journal", "Negative sums are held at 0 with a "
                   "warning.", stock, ["roll1"])

            def idempotent(r: Run) -> list[str]:
                return [] if _canon_ds(r["roll1"]) == _canon_ds(r["roll1_again"]) else ["rolling again changed the dataset"]
            _check(ctx, runs, "rolling twice to the same date changes nothing", "", idempotent, ["roll1_again"])

            def two_steps(r: Run) -> list[str]:
                return [f"{k} differs" for k in _same(r["roll2"], r["roll_once"])]
            _check(ctx, runs, "rolling a week and then another ends where rolling two weeks at once does",
                   "Every quantity is recomputed from original quantities and the whole journal.", two_steps, ["roll_once"])

            def late(r: Run) -> list[str]:
                return [f"{r['late']['type']} {r['late']['date']} posted late: {k} differs"
                        for k in _same(r["roll2"], r["late_roll2"])]
            _check(ctx, runs, "a movement posted after its week was rolled ends where posting it on time does",
                   "Stock, history, logged accuracy and the closed-order log all re-read the journal.", late, ["late_roll2"])

        with ctx.step("Finance closes the books", "finance", "POST /api/finance",
                      "Every cost the plan spends is served to a customer or reported as unabsorbed."):
            def books(r: Run) -> list[str]:
                rec = r["finance"].reconciliation
                return [f"{x.category}: plan {x.plan:g}, served {x.served:g} + unabsorbed {x.unabsorbed:g}"
                        for x in rec.lines if abs(x.difference) > 1e-4 * max(1.0, abs(x.plan))]
            _check(ctx, runs, "the reconciliation closes line by line", "", books, ["finance"])

        with ctx.step("The tower reads the rolled plan", "tower", "POST /api/tower",
                      "Measures from the logs the roll wrote stay within their ranges."):
            def tower(r: Run) -> list[str]:
                t = r["tower"]
                if not t.ok:
                    return ["the tower did not run"]
                return [f"{k.id} = {k.value}" for k in t.kpis if k.value is not None and not math.isfinite(k.value)]
            _check(ctx, runs, "the tower runs on every rolled company with finite measures", "", tower, ["tower"])

        with ctx.step("Versions store exactly what was saved", "versions", "POST /api/versions",
                      "A version's hash is the SHA-256 of its canonical JSON, and reading it back gives the same bytes."):
            def version(r: Run) -> list[str]:
                ds = r["roll2"]
                bad = [] if r["version"].sha256 == sha(canonical(ds)) else ["stored hash is not the hash of the dataset"]
                if canonical(r["version_doc"].dataset) != canonical(ds):
                    bad.append("the stored dataset reads back different")
                return bad
            _check(ctx, runs, "hash and content round-trip", "", version, ["version_doc"])

        with ctx.step("Same company, told differently", "plan", "POST /api/plan",
                      "Metamorphic relations: nobody knows the right plan, but the same company listed in another "
                      "order, or started whole weeks later, must get the same plan, and more safety stock at a "
                      "node never means less supply there."):
            def perm(r: Run) -> list[str]:
                a, b = r["plan3"], r["plan_perm"]
                bad = [] if _sig(a) == _sig(b) else [f"orders: {_first_diff(_sig(a), _sig(b))}"]
                pa, pb = _poh(a), _poh(b)
                return bad + [f"{k[0]}/{k[1]} projection {_first_diff(pa[k], pb.get(k, []))}" for k in pa if pa[k] != pb.get(k)]
            _check(ctx, runs, "listing every table in another order gives the same plan", "", perm, ["plan_perm"])

            def shift(r: Run) -> list[str]:
                a, b, k = r["plan3"], r["plan_shift"], 7 * r["shift"]
                bad = [] if _sig(a) == _sig(b, k) else [f"orders (+{k} days): {_first_diff(_sig(a), _sig(b, k))}"]
                pa, pb = _poh(a), _poh(b)
                return bad + [f"{x[0]}/{x[1]} projection {_first_diff(pa[x], pb.get(x, []))}" for x in pa if pa[x] != pb.get(x)]
            _check(ctx, runs, "starting whole weeks later gives the same plan, shifted",
                   "Every date moves by the same number of weeks; calendars repeat weekly.", shift, ["plan_shift"])

            def more_ss(r: Run) -> list[str]:
                node = r["ss_node"]

                def supply(p: PlanResult) -> float:
                    return sum(o.qty for o in p.orders if (o.location, o.product) == node)
                a, b = supply(r["plan3"]), supply(r["plan_ss"])
                return [] if b >= a - 1e-6 * max(1.0, a) else [f"{node[0]}/{node[1]}: supply fell from {a:g} to {b:g}"]
            _check(ctx, runs, "more safety stock never means less supply", "", more_ss, ["plan_ss"])

    return Scenario(
        id="s9-generated", title="One flow, many companies", company="Generated company 0",
        story=f"The whole workflow, from the readiness gate to a saved version, over {len(seeds)} randomly generated "
              "companies. Nobody worked out their plans by hand; instead every run is held to what must be true of "
              "any plan: balances, agreements between modules, and relations between a company and the same "
              "company told differently.",
        proves=["the flow runs end to end on companies nobody hand-picked",
                "MRP invariants on every plan the flow makes",
                "S&OP, MRP and the inventory screen plan the same demand and the same safety stock",
                "firming everything and planning again changes nothing",
                "roll-forward: journal stock, idempotence, two steps = one, late = on time",
                "the books close and versions round-trip",
                "the plan does not depend on list order or on the start week"],
        stages=["readiness", "demand", "sop", "plan", "inventory", "promise", "execution", "finance", "tower",
                "versions"],
        build=lambda: company(seeds[0]), run=run, tags=["generated", "properties"],
        found=["MRP checked the buffer on the day a firm receipt landed; under a daily-ramping S&OP stock target that "
               "sized orders by when supply arrived, so firming a plan and planning again added orders",
               "Whether a late firm order was pulled in was judged by how soon an order for the shortage could land, "
               "not the lot MRP then ordered: a large lot that took as long was planned beside the firm one",
               "MRP sized a statistical safety stock on a node only one-off requirements drew on (no forecast error "
               "to protect against), where the inventory screen correctly showed none",
               "A roll rounded the open quantity of an order nothing had been received on and lost the original, so "
               "rolling a week twice did not end where rolling two weeks did",
               "The closed-order log was in the order the rolls closed orders, so the same history gave two datasets",
               "A sale posted late for a week that had logged no accuracy record at all never reached the log",
               "The placement counted a 3.5-day lead time as 4 whole days, so buffering a stage alone cost more than "
               "the single-echelon baseline for the same decision (a negative saving)",
               "A late period lot, once firmed, covered the weeks after it; the next plan sized a new order to the "
               "first week's shortage alone, found it faster, and planned it beside the firm one"])


SCENARIO = make(SEEDS)
