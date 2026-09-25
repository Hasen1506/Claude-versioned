"""S5 · Harbour Paints: where should the safety stock sit?

A serial network with a fork at the end: a supplier sells tinting base to the plant, the plant makes paint
and ships it to two distribution centres, each serving its own trade customers at 10 tins a day (weekly
forecast error 30 %). The planners' current buffers are a mix of habits: a round number at the plant, a
service-level policy at the east DC and a fill-rate policy with an economic order quantity at the west DC.

The expected answers come from closed forms computed here, independently of the engine: the square-root
safety-stock formula, the guaranteed-service model by enumerating every integer service time, the
standard-normal loss function for the fill rate, and the DDMRP zone arithmetic.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from statistics import NormalDist

from ..model import Dataset
from .harness import Client, Ctx, Scenario, one

START = dt.date(2026, 4, 6)
RATE = 0.25                                   # WACC 15 % + 10 % holding spread
CV = 0.3
SD_DC = CV * 10 * math.sqrt(7)                # σ of daily demand at a DC: 7.94
SD_PLANT = math.sqrt(2) * SD_DC               # two independent DCs pooled at the plant: 11.22
Z95, Z99 = NormalDist().inv_cdf(0.95), NormalDist().inv_cdf(0.99)
VALUE = {"BASE": 10.0, "PAINT": 30.0, "DC": 31.0}
LT = {"BASE": 10, "PAINT": 5, "DC": 3}


def _fc(cust: str) -> list[dict]:
    return [{"location": cust, "product": "PAINT", "date": (START + dt.timedelta(weeks=w)).isoformat(), "qty": 70,
             "period_days": 7} for w in range(8)]


def build() -> dict:
    dc_policy = {"method": "service_level", "service_level": 0.95, "demand_cv": CV}
    return {
        "settings": {"company_name": "Harbour Paints", "currency": "EUR", "planning_start": START.isoformat(),
                     "horizon_days": 56, "bucket": "week", "wacc": 0.15, "holding_spread": 0.10,
                     "default_service_level": 0.95, "default_calendar": "CAL-7"},
        "calendars": [{"id": "CAL-7", "name": "Seven-day operation", "workdays": [0, 1, 2, 3, 4, 5, 6]}],
        "inventory": {"default_demand_cv": CV, "customer_service_days": 0},
        "locations": [
            {"id": "SUP-BASE", "name": "Resin & base supplier", "type": "supplier"},
            {"id": "PLANT", "name": "Harbour paint works", "type": "plant", "lat": 53.35, "lon": -6.26},
            {"id": "DC-E", "name": "East DC", "type": "dc", "lat": 53.27, "lon": -6.14},
            {"id": "DC-W", "name": "West DC", "type": "dc", "lat": 53.27, "lon": -9.05},
            {"id": "CUST-E", "name": "East trade counters", "type": "customer"},
            {"id": "CUST-W", "name": "West trade counters", "type": "customer"},
        ],
        "products": [{"id": "PAINT", "name": "Harbour White 10 L", "type": "FG", "price": 60},
                     {"id": "BASE", "name": "Tinting base", "type": "RM"}],
        "location_products": [
            {"location": "PLANT", "product": "BASE", "safety_stock": {"method": "fixed", "qty": 150}},
            {"location": "PLANT", "product": "PAINT", "safety_stock": {"method": "fixed", "qty": 100}},
            {"location": "DC-E", "product": "PAINT", "on_hand": 200, "ddmrp_buffer": True, "safety_stock": dc_policy},
            {"location": "DC-W", "product": "PAINT", "on_hand": 200, "ddmrp_buffer": True,
             "safety_stock": {**dc_policy, "method": "fill_rate", "service_level": 0.99},
             "lot_sizing": {"policy": "EOQ", "ordering_cost": 50}},
            # trade customers order up to three weeks ahead: their orders consume the forecast that far forward
            {"location": "CUST-E", "product": "PAINT", "consumption_forward_days": 21},
            {"location": "CUST-W", "product": "PAINT"},
        ],
        "production_sources": [{"id": "PV-PAINT", "location": "PLANT", "product": "PAINT",
                                "fixed_lead_time_workdays": LT["PAINT"], "conversion_cost_per_unit": 20,
                                "components": [{"product": "BASE", "qty": 1}]}],
        "purchasing_sources": [{"id": "PU-BASE", "supplier": "SUP-BASE", "product": "BASE", "location": "PLANT",
                                "price": VALUE["BASE"], "lead_time_days": LT["BASE"], "lead_time_std_days": 2}],
        "lanes": [
            {"id": "L-PE", "origin": "PLANT", "destination": "DC-E", "modes": [{"transit_days": 3, "cost_per_unit": 1}]},
            {"id": "L-PW", "origin": "PLANT", "destination": "DC-W", "modes": [{"transit_days": 3, "cost_per_unit": 1}]},
            {"id": "L-EC", "origin": "DC-E", "destination": "CUST-E", "modes": [{"transit_days": 1}]},
            {"id": "L-WC", "origin": "DC-W", "destination": "CUST-W", "modes": [{"transit_days": 1}]},
        ],
        "demand": _fc("CUST-E") + _fc("CUST-W") + [
            {"id": "SO-E1", "location": "CUST-E", "product": "PAINT", "date": "2026-04-07", "qty": 30, "kind": "sales_order"},
            {"id": "SO-E2", "location": "CUST-E", "product": "PAINT", "date": "2026-04-10", "qty": 150,
             "kind": "sales_order"},
            {"id": "SO-E3", "location": "CUST-E", "product": "PAINT", "date": "2026-04-12", "qty": 40, "kind": "sales_order"},
        ],
        "receipts": [{"id": "STO-E1", "kind": "transfer", "location": "DC-E", "product": "PAINT", "qty": 100,
                      "due_date": "2026-04-08", "source": "L-PE"}],
    }


# ---- independent oracles ------------------------------------------------------------------------
def gsm_oracle() -> tuple[float, int, int]:
    """Enumerate every integer outbound service time of the base and the paint stage (the DCs must quote 0).

    τ_base = 10 − S_base; τ_paint = S_base + 5 − S_paint; τ_DC = S_paint + 3 at both DCs. The east DC and
    the plant hold z·σ·√τ; the west DC's fill-rate target needs the loss-function k for σ·√τ at each τ.
    Returns (objective, S_base, S_paint) of the cheapest plan."""
    c_base = VALUE["BASE"] * RATE * Z95 * SD_PLANT
    c_paint = VALUE["PAINT"] * RATE * Z95 * SD_PLANT
    c_dce = VALUE["DC"] * RATE * Z95 * SD_DC
    best = (math.inf, -1, -1)
    for s_base in range(LT["BASE"] + 1):
        for s_paint in range(s_base + LT["PAINT"] + 1):
            tau_dc = s_paint + LT["DC"]
            cost = (c_base * math.sqrt(LT["BASE"] - s_base) + c_paint * math.sqrt(s_base + LT["PAINT"] - s_paint)
                    + c_dce * math.sqrt(tau_dc) + VALUE["DC"] * RATE * fill_rate_ss(0.99, Q_W, SD_DC * math.sqrt(tau_dc)))
            best = min(best, (cost, s_base, s_paint))
    return best


def loss(k: float) -> float:
    n = NormalDist()
    return n.pdf(k) - k * (1 - n.cdf(k))


def fill_rate_ss(beta: float, q: float, sigma: float) -> float:
    lo, hi = -6.0, 8.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if loss(mid) > (1 - beta) * q / sigma else (lo, mid)
    return max(0.0, lo * sigma)


def eoq(annual: float, order_cost: float, unit_value: float, rate: float) -> float:
    return math.sqrt(2 * annual * order_cost / (unit_value * rate))


Q_W = eoq(3650, 50, VALUE["DC"], RATE)          # the west DC's lot: 10 a day for a year, €50 an order


def zones(adu: float, dlt: float, ltf: float, vf: float, cycle: float = 7) -> tuple[float, float, float]:
    red = adu * dlt * ltf * (1 + vf)
    yellow = adu * dlt
    green = max(adu * cycle, adu * dlt * ltf)
    return red, red + yellow, red + yellow + green


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Check the master data", "readiness", "POST /api/validate",
                  "Two DCs, one plant, one supplier: nothing should block."):
        ctx.eq("blocking errors", [i.code for i in c.validate(ds) if i.severity == "error"], [])

    with ctx.step("Measure demand and variability at every stage", "inventory", "POST /api/inventory",
                  "10 tins/day at each DC with a 30 % weekly CV; the plant sees both DCs, so the variances add."):
        inv = c.inventory(ds)
        n = {(x.location, x.product): x for x in inv.nodes}
        dce, dcw, paint, base = n["DC-E", "PAINT"], n["DC-W", "PAINT"], n["PLANT", "PAINT"], n["PLANT", "BASE"]
        ctx.near("mean daily demand (DC-E, DC-W, paint, base)",
                 [dce.mean_daily, dcw.mean_daily, paint.mean_daily, base.mean_daily], [10, 10, 20, 20], 1e-9,
                 "560 tins per customer over the 56-day horizon: the east orders (220) consume the forecast "
                 "(all of weeks 1–3 and 10 of week 4) instead of adding to it. The plant "
                 "supplies both DCs; one base per tin.")
        ctx.near("σ of daily demand", [dce.sd_daily, paint.sd_daily, base.sd_daily], [SD_DC, SD_PLANT, SD_PLANT], 1e-9,
                 "σ_d = CV·d̄·√7 = 0.3·10·√7 = 7.94 at a DC; √2 × that at the plant (independent streams: "
                 "variances add). Risk pooling: the plant's CV is 0.3/√2 = 0.21.")
        ctx.eq("where each σ comes from", [dce.cv_source, paint.cv_source, base.cv_source],
               ["policy", "pooled", "pooled"])
        ctx.near("lead times (DC, paint, base) and base σ_L",
                 [dce.lead_time_days, paint.lead_time_days, base.lead_time_days, base.lead_time_std_days],
                 [3, 5, 10, 2], 1e-9)
        ctx.near("unit values", [base.unit_value, paint.unit_value, dce.unit_value], [10, 30, 31], 1e-9,
                 "Base bought at 10; paint = 10 of base + 20 conversion; at a DC + 1 freight.")
        ctx.near("holding rate", dce.holding_rate, RATE, 1e-12, "WACC 15 % + spread 10 %.")

    with ctx.step("Single-echelon baseline", "inventory", "POST /api/inventory",
                  "Every stage buffers its own lead time: SS = z·√(L·σ_d² + d̄²·σ_L²), or for the west DC's "
                  "fill rate, the k that leaves 1 % of its lot short."):
        single = {"DC-E": Z95 * SD_DC * math.sqrt(3), "DC-W": fill_rate_ss(0.99, Q_W, SD_DC * math.sqrt(3)),
                  "PAINT": Z95 * SD_PLANT * math.sqrt(5),
                  "BASE": Z95 * math.sqrt(10 * SD_PLANT ** 2 + (20 * 2) ** 2)}
        ctx.near("single-echelon SS", [dce.single_ss, dcw.single_ss, paint.single_ss, base.single_ss],
                 list(single.values()), 1e-6,
                 "DC-E 1.645·7.94·√3 = 22.61; DC-W: 1 % of Q = 217 is 2.17 short per cycle = 13.75·G(k), k = 0.640, "
                 "8.80 (not z(99 %) = 2.326, which would hold 31.98); paint 1.645·11.22·√5 = 41.29; "
                 "base 1.645·√(10·126 + (20·2)²) = 87.97: the supplier's ±2-day lead time costs more than demand.")

    with ctx.step("Multi-echelon placement (guaranteed service)", "inventory", "POST /api/inventory",
                  "Minimise Σ h·z·σ·√τ with the DCs quoting 0 days to customers. Enumerating every integer "
                  "service time gives the optimum: hold base (τ = 10), pass the paint stage through, and cover "
                  "the 8 days from paint start to customer at each DC."):
        obj, s_base, s_paint = gsm_oracle()
        ctx.eq("oracle: the plant's service times", (s_base, s_paint), (0, 5),
               "Base quotes 0 (holds stock); paint quotes its 5-day lead time (holds none).")
        ctx.eq("decisions", {k: n[k].decision for k in sorted(n)},
               {("CUST-E", "PAINT"): "customer", ("CUST-W", "PAINT"): "customer", ("DC-E", "PAINT"): "buffer",
                ("DC-W", "PAINT"): "buffer", ("PLANT", "BASE"): "buffer", ("PLANT", "PAINT"): "pass_through"})
        ctx.eq("net replenishment times τ", [dce.meio_net_days, dcw.meio_net_days, paint.meio_net_days,
                                             base.meio_net_days], [8, 8, 0, 10])
        ctx.near("solver objective = enumerated optimum", inv.solver.objective, obj, 1e-6,
                 f"Σ c·√τ = {obj:.2f} per year; the runner-up (buffer at every stage) costs more.")
        meio = {"DC-E": Z95 * SD_DC * math.sqrt(8), "DC-W": fill_rate_ss(0.99, Q_W, SD_DC * math.sqrt(8)), "PAINT": 0.0,
                "BASE": single["BASE"]}
        ctx.near("recommended SS", [dce.meio_ss, dcw.meio_ss, paint.meio_ss, base.meio_ss], list(meio.values()), 1e-6,
                 "DC-E 1.645·7.94·√8 = 36.93; DC-W over 8 days: 2.17 = 22.45·G(k), k = 0.921, 20.67; none at the "
                 "paint stage, base as before "
                 "(σ_L added back at the buffering stage).")
        value = lambda d: d["DC-E"] * 31 + d["DC-W"] * 31 + d["PAINT"] * 30 + d["BASE"] * 10  # noqa: E731
        ctx.near("stock value: single vs multi-echelon", (inv.totals.single_ss_value, inv.totals.meio_ss_value),
                 (value(single), value(meio)), 1e-6)
        ctx.near("annual holding saving", inv.totals.saving_vs_single, (value(single) - value(meio)) * RATE, 1e-6)

    with ctx.step("Risk pooling", "inventory", "POST /api/inventory",
                  "If both DCs were served from one stock point, the square-root law applies."):
        pool = one(inv.pooling, product="PAINT")
        ctx.near("separate vs pooled SS", (pool.separate_ss, pool.pooled_ss),
                 (2 * Z95 * SD_DC * math.sqrt(3), Z95 * SD_PLANT * math.sqrt(3)), 1e-6)
        ctx.near("saving", pool.saving_pct, 1 - 1 / math.sqrt(2), 1e-9, "Two equal, independent locations: 1 − 1/√2 = 29.3 %.")

    with ctx.step("Current policies: the same number everywhere", "inventory+plan", "POST /api/plan",
                  "The inventory screen's 'current' safety stock must be the one MRP actually plans with."):
        plan = c.plan(ds)
        mrp = {(x.location, x.product): x.buckets[0].safety_stock for x in plan.nodes}
        q = Q_W
        fr = fill_rate_ss(0.99, q, SD_DC * math.sqrt(3))
        ctx.near("west DC economic order quantity", q, 217.02, 0.01, "√(2 · 3,650 · 50 ÷ (31 · 0.25)).")
        ctx.near("MRP safety stock", [mrp["PLANT", "BASE"], mrp["PLANT", "PAINT"], mrp["DC-E", "PAINT"],
                                      mrp["DC-W", "PAINT"]], [150, 100, single["DC-E"], fr], 1e-6,
                 f"Fill rate 99 % with Q = 217: expected shortage per cycle 1 % · 217 = 2.17 = σ_LT·G(k) → k = "
                 f"{fr / (SD_DC * math.sqrt(3)):.3f}, SS = {fr:.2f}.")
        ctx.near("inventory 'current' SS matches MRP", [base.current_ss, paint.current_ss, dce.current_ss, dcw.current_ss],
                 [150, 100, single["DC-E"], fr], 1e-6)

    with ctx.step("Approve the placement and plan again", "inventory+plan", "POST /api/inventory/apply",
                  "Applying writes each recommendation, rounded up to whole tins, as a fixed policy; the next MRP "
                  "run must hold exactly that. The paint stage passes through, so its buffer is removed."):
        only, one_change = c.apply_placement(ds, ["DC-E|PAINT"])
        ctx.eq("apply one stage by key", [(x.location, x.ss_after) for x in one_change.changes], [("DC-E", 37)],
               "⌈36.93⌉ = 37.")
        ctx.raises("an unknown stage is refused", lambda: c.apply_placement(ds, ["CUST-E|PAINT"]), 404,
                   "not a stocking stage")
        applied, info = c.apply_placement(ds)
        after = {"DC-E": math.ceil(meio["DC-E"]), "DC-W": math.ceil(meio["DC-W"]), "PAINT": 0,
                 "BASE": math.ceil(meio["BASE"])}
        ctx.eq("every stage that differs, with its new quantity",
               sorted((x.location, x.product, x.ss_after) for x in info.changes),
               [("DC-E", "PAINT", after["DC-E"]), ("DC-W", "PAINT", after["DC-W"]), ("PLANT", "BASE", after["BASE"]),
                ("PLANT", "PAINT", 0)], "⌈36.93⌉, ⌈20.67⌉, ⌈87.97⌉, and none at the paint stage.")
        was = {"DC-E": single["DC-E"], "DC-W": fr, "PAINT": 100, "BASE": 150}
        ctx.near("safety-stock value change", info.value_change,
                 sum((after[k] - was[k]) * {"DC-E": 31, "DC-W": 31, "PAINT": 30, "BASE": 10}[k] for k in after), 1e-6,
                 "(37 − 22.61)·31 + (21 − 8.80)·31 − 100·30 − (150 − 88)·10: the plant's round numbers were the "
                 "expensive habit.")
        replan = {(x.location, x.product): x.buckets[0].safety_stock for x in c.plan(applied).nodes}
        ctx.near("MRP now holds the recommendation", [replan["DC-E", "PAINT"], replan["DC-W", "PAINT"],
                                                     replan["PLANT", "PAINT"], replan["PLANT", "BASE"]],
                 [after["DC-E"], after["DC-W"], 0, after["BASE"]], 1e-9)
        ctx.eq("the one-stage apply left the others alone",
               [(lp.location, lp.product, lp.safety_stock.method.value) for lp in only.location_products
                if lp.location in ("PLANT", "DC-W")],
               [("PLANT", "BASE", "fixed"), ("PLANT", "PAINT", "fixed"), ("DC-W", "PAINT", "fill_rate")])

    with ctx.step("S&OP sees the demand MRP plans", "sop", "POST /api/sop",
                  "In weekly S&OP buckets the east orders replace the forecast they consume rather than competing "
                  "with it: the plan balances 560 tins a customer, as MRP and the inventory screen do."):
        raw = json.loads(ds.model_dump_json())
        raw["sop"] = {"bucket": "week"}
        sop = c.sop(Dataset.model_validate(raw))
        east, west = one(sop.demand, location="CUST-E"), one(sop.demand, location="CUST-W")
        ctx.near("east demand by week", east.demand, [220, 0, 0, 60, 70, 70, 70, 70], 1e-9,
                 "Orders 30 + 150 + 40 in week 1; they consume weeks 1–3 and 10 of week 4. Taking the larger of "
                 "forecast and orders per week would plan 220 + 7·70 = 710.")
        ctx.near("total demand per customer (east, west)", (sum(east.demand), sum(west.demand)), (560, 560), 1e-9,
                 "8 weeks × 70, orders included.")

    with ctx.step("DDMRP buffers at the DCs only", "inventory", "POST /api/inventory",
                  "Only the DCs are decoupling points, so the east DC's decoupled lead time runs all the way back "
                  "to the supplier: 3 + 5 + 10 = 18 days (medium: LTF 0.5; CV 0.3: low variability, VF 0.25)."):
        row = one(inv.ddmrp, location="DC-E")
        red, toy, tog = zones(10, 18, 0.5, 0.25)
        ctx.near("DLT, LTF, VF", (row.dlt, row.ltf, row.vf), (18, 0.5, 0.25), 1e-9,
                 "A CV of exactly 0.3 is 'low' (≤ 0.3).")
        ctx.near("zones TOR / TOY / TOG", (row.tor, row.toy, row.tog), (red, toy, tog), 1e-9,
                 "Red 10·18·0.5·1.25 = 112.5; yellow 10·18 = 180; green max(10·7, 90) = 90.")
        ctx.near("qualified demand", row.qualified_demand, 180, 1e-9,
                 "The customer orders ship from this DC one day ahead: SO-E1 ships today (qualifies), SO-E2's "
                 "150 ships on day 3, inside the DLT and above the spike threshold ½·112.5; SO-E3's 40 is below it.")
        ctx.near("net flow position", row.nfp, 200 + 100 - 180, 1e-9, "200 on hand + 100 in transit − 180.")
        ctx.eq("zone", row.zone, "yellow")
        ctx.near("recommended order", row.order_qty, tog - 120, 1e-9, "Up to top of green: 382.5 − 120.")

    with ctx.step("Decouple at the base as MEIO recommends", "inventory", "POST /api/inventory",
                  "With a DDMRP buffer on the base, the DC's decoupled lead time is only 3 + 5 = 8 days: short "
                  "(LTF 0.7), so the red zone shrinks, and so does the spike threshold: SO-E3 now counts."):
        raw = json.loads(ds.model_dump_json())
        next(lp for lp in raw["location_products"] if lp["product"] == "BASE")["ddmrp_buffer"] = True
        inv2 = c.inventory(Dataset.model_validate(raw))
        row = one(inv2.ddmrp, location="DC-E")
        red, toy, tog = zones(10, 8, 0.7, 0.25)
        ctx.near("east DC: DLT and zones", (row.dlt, row.tor, row.toy, row.tog), (8, red, toy, tog), 1e-9,
                 "Red 10·8·0.7·1.25 = 70; yellow 80; green max(70, 56) = 70.")
        ctx.near("qualified demand and NFP", (row.qualified_demand, row.nfp), (220, 80), 1e-9,
                 "Spike threshold ½·70 = 35 < 40: SO-E3 qualifies too.")
        ctx.near("recommended order", row.order_qty, 140, 1e-9, "220 − 80.")
        b = one(inv2.ddmrp, location="PLANT", product="BASE")
        bred, btoy, btog = zones(20, 10, 0.7, 0.25)
        ctx.near("base buffer", (b.adu, b.dlt, b.tor, b.toy, b.tog), (20, 10, bred, btoy, btog), 1e-9,
                 "ADU 20 (both DCs); DLT 10 (supplier); CV 0.21: low. Red 175, yellow 200, green 140.")


SCENARIO = Scenario(
    id="s5-paints", title="Safety stock placement", company="Harbour Paints",
    story="A plant makes paint from a bought-in base and ships it to two DCs. The planners' buffers are a mix of "
          "habits. Where should the stock sit, how much, and what does it cost? The answer is checked against a "
          "full enumeration of the guaranteed-service model and the DDMRP buffer arithmetic.",
    proves=["risk pooling of variances", "lead-time variability in safety stock", "cost roll-up to unit values",
            "single-echelon vs multi-echelon placement (exact optimum)", "square-root law",
            "fill-rate safety stock with an EOQ lot", "the same safety stock in MRP and inventory",
            "the same demand in S&OP as in MRP", "an approved placement is what MRP then holds",
            "DDMRP decoupled lead time, zones and qualified spikes from customer orders"],
    stages=["readiness", "inventory", "sop", "plan"],
    found=["Inventory sized a fill-rate item's lot as a week of demand while MRP used the EOQ: two safety stocks for "
           "one item",
           "The demand rate took the larger of forecast and orders instead of forecast after consumption plus orders",
           "A CV of exactly 0.3 computed as 0.30000000000000004 and fell into the medium DDMRP band",
           "DDMRP qualified demand ignored the orders of the customers a buffer ships to",
           "The placement priced the west DC's 99 % fill rate as a 99 % cycle-service level (z = 2.33): 31.98 "
           "single-echelon where MRP holds 8.80, and an optimum built on stock no screen would hold",
           "S&OP took the larger of forecast and orders per bucket: 710 tins for a customer MRP plans 560 for",
           "No API call applied a placement: only the web client could, by editing the policies itself"],
    build=build, run=run)
