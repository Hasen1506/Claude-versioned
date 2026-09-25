"""S4 · Corner Grocer: demand planning on series whose right answers are known.

Seven products at one store, each built to test one thing: a flat line, a straight trend, a pure 4-week
season, an intermittent item, a product with two flagged promotions, a series with one freak order, and a
new product launched from a like product. The competition must pick the model that fits exactly, cleansing
must remove the promotion and the spike, the measured promotion lift must be applied to a future promotion,
the launch must ramp and cannibalise its like product, a planner's override must win, and the release must
prorate the partial first and last weeks of the horizon. Meanwhile the warehouse's supply is still being
set up: demand planning must not wait for it.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np

from ..model import Dataset
from .harness import Client, Ctx, Scenario, d, one

START = dt.date(2026, 6, 3)          # a Wednesday: the first forecast week is 5/7 inside the horizon
FIRST = dt.date(2025, 11, 3)         # 30 weeks of history, through the week of 25 May
N = 30
NOISE = [-4, 3, -1, 5, -2, 0, 2, -3]
PRICES = {"FLAT": 2, "TREND": 3, "SEASON": 1, "INTERMIT": 50, "PROMO": 1, "SPIKE": 1, "NEW": 2}


def _history() -> list[dict]:
    out = []
    for w in range(N):
        day = (FIRST + dt.timedelta(weeks=w)).isoformat()
        rows = {"FLAT": 100, "TREND": 50 + 5 * w, "SEASON": [80, 120, 100, 100][w % 4],
                "INTERMIT": 12 if w % 4 == 2 else 0, "PROMO": 300 if w in (10, 20) else 200,
                "SPIKE": 1000 if w == 15 else 100 + NOISE[w % 8]}
        for p, q in rows.items():
            row = {"location": "STORE", "product": p, "date": day, "qty": q}
            if p == "PROMO" and w in (10, 20):
                row["promo"] = True
            out.append(row)
    return out


def build() -> dict:
    return {
        "settings": {"company_name": "Corner Grocer", "currency": "GBP", "planning_start": START.isoformat(),
                     "horizon_days": 42, "bucket": "week"},
        "locations": [{"id": "STORE", "name": "High Street store", "type": "store", "lat": 51.45, "lon": -2.59},
                      {"id": "WH", "name": "Regional warehouse", "type": "warehouse", "lat": 51.54, "lon": -2.41}],
        "products": [{"id": p, "type": "FG", "price": pr} for p, pr in PRICES.items()],
        "location_products": [{"location": "STORE", "product": p} for p in PRICES]
        + [{"location": "WH", "product": p} for p in PRICES],
        "lanes": [{"id": "L-WS", "origin": "WH", "destination": "STORE", "modes": [{"transit_days": 1}]}],
        "history": _history(),
        "forecasting": {"season_length": 4, "backtest_origins": 4, "backtest_horizon": 2},
        "events": [{"id": "EV-SUMMER", "name": "Summer promotion", "kind": "promo", "products": ["PROMO"],
                    "start": "2026-06-15", "end": "2026-06-21"}],
        "npi": [{"location": "STORE", "product": "NEW", "like_product": "FLAT", "scale": 0.5,
                 "launch_date": "2026-06-15", "ramp_periods": 2, "cannibalisation": 0.2}],
        "overrides": [{"location": "STORE", "product": "TREND", "date": "2026-06-10", "qty": 999,
                       "reason": "Listing at a key account", "author": "KAM"}],
    }


def _revenue() -> dict[str, float]:
    out: dict[str, float] = {}
    for r in _history():
        out[r["product"]] = out.get(r["product"], 0.0) + r["qty"] * PRICES[r["product"]]
    return out


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Check the master data", "readiness", "POST /api/validate",
                  "The warehouse has no supplier yet: supply planning is blocked, demand planning is not."):
        codes = sorted({i.code for i in c.validate(ds) if i.severity == "error"})
        ctx.eq("blocking errors", codes, ["NO_SOURCE"])

    with ctx.step("Run the forecast competition", "demand", "POST /api/forecast",
                  "Rolling-origin backtest (4 origins × 2 weeks), champion by MASE, simplest model on a tie."):
        fr = c.forecast(ds)
        ctx.eq("forecast runs despite the supply gaps", fr.ok, True)
        s = {x.product: x for x in fr.series}
        ctx.eq("champions", {p: (s[p].champion.value if s[p].champion else None) for p in sorted(s)},
               {"FLAT": "naive", "INTERMIT": "sba", "NEW": None, "PROMO": "naive", "SEASON": "seasonal_naive",
                "SPIKE": "holt_winters", "TREND": "regression"},
               "FLAT, PROMO (once cleansed) and SEASON are fitted exactly by several models: the simplest wins the "
               "tie (naïve; seasonal naïve). TREND is a straight line only regression reproduces. INTERMIT is "
               "intermittent, so only baselines, SES and the intermittent family compete.")
        ctx.near("TREND statistical forecast", [p.statistical for p in s["TREND"].forecast],
                 [200, 205, 210, 215, 220, 225, 230], 1e-6, "50 + 5t continued: t = 30 is the week of 1 Jun.")
        ctx.near("SEASON continues its cycle", [p.statistical for p in s["SEASON"].forecast],
                 [100, 100, 80, 120, 100, 100, 80], 1e-9, "Week 30 of the 80/120/100/100 cycle is position 2.")
        seg = s["INTERMIT"].segment
        ctx.eq("INTERMIT demand pattern (ADI, CV²)", (seg.pattern, seg.adi, seg.cv2), ("intermittent", 4.0, 0.0),
               "One sale of 12 every 4 weeks: ADI = 30 ÷ 7.5… = 4 ≥ 1.32, sizes identical → CV² = 0.")
        ctx.near("INTERMIT forecast (SBA)", s["INTERMIT"].forecast[1].statistical, 0.95 * 12 / 4, 1e-9,
                 "Croston size 12 ÷ interval 4 = 3, SBA removes the bias: × (1 − 0.1/2).")
        promo_flags = [(h.start, h.flag) for h in s["PROMO"].history if h.flag]
        ctx.eq("promotion weeks flagged and cleansed", promo_flags,
               [(d("2026-01-12"), "event"), (d("2026-03-23"), "event")])
        ctx.near("measured promotion lift", s["PROMO"].lifts.get("promo"), 0.5, 1e-9,
                 "300 sold in each promo week against a baseline of 200 from the neighbouring weeks.")
        spike = [(h.start, h.flag) for h in s["SPIKE"].history if h.flag]
        ctx.eq("the freak order is flagged as an outlier", spike, [(d("2026-02-16"), "outlier")])
        cleaned = one(s["SPIKE"].history, start=d("2026-02-16")).cleaned
        ctx.true("…and clipped near the local level", 100 < cleaned < 125, actual=cleaned,
                 why="Clipped to the rolling median (100) + 4 robust σ of the ±5 noise.")
        ctx.near("SPIKE forecast stays near 100", float(np.mean([p.statistical for p in s["SPIKE"].forecast])), 100, 3)
        rev = _revenue()
        total = sum(rev.values())
        ctx.near("revenue shares", {p: s[p].segment.revenue_share for p in rev}, {p: v / total for p, v in rev.items()},
                 1e-9, "Raw history × price: TREND 11,025, PROMO 6,200, FLAT 6,000, INTERMIT 4,200, SPIKE 3,904, "
                       "SEASON 3,000 of 34,329.")
        ctx.eq("ABC classes", {p: s[p].segment.abc for p in sorted(rev)},
               {"FLAT": "A", "INTERMIT": "A", "PROMO": "A", "SEASON": "B", "SPIKE": "A", "TREND": "A"},
               "Cumulative share before each product: SPIKE starts at 79.9 % (< 80 %: A), SEASON at 91.3 % (B).")

    with ctx.step("Consensus: event, launch, override", "demand", "POST /api/forecast",
                  "The summer promotion has no lift typed in, so the measured +50 % applies; NEW launches on "
                  "15 Jun at half of FLAT's volume over two ramp weeks and takes 20 % of what it sells from FLAT; "
                  "the key account manager overrides TREND in the week of 8 Jun."):
        ctx.near("PROMO in the promotion week", (s["PROMO"].forecast[2].event_factor, s["PROMO"].forecast[2].final),
                 (1.5, 300), 1e-9)
        ctx.near("NEW by week", [p.final for p in s["NEW"].forecast], [0, 0, 25, 50, 50, 50, 50], 1e-9,
                 "Launch week: 100 × 0.5 × ½ ramp = 25, then 50.")
        ctx.near("FLAT after cannibalisation", [p.final for p in s["FLAT"].forecast], [100, 100, 95, 90, 90, 90, 90], 1e-9,
                 "20 % of NEW's 25 and 50.")
        ctx.near("TREND override", s["TREND"].forecast[1].final, 999, 1e-9)

    with ctx.step("Release the consensus", "demand", "POST /api/forecast/release",
                  "Each week becomes a forecast record; the partial weeks at both ends are prorated by days."):
        rel_ds, rel = c.release_forecast(ds)
        ctx.eq("records released", rel.records, 7 * 7 - 2, "NEW has nothing before its launch.")
        flat = sorted((r.date, round(r.qty, 3), r.period_days) for r in rel_ds.demand if r.product == "FLAT")
        ctx.eq("FLAT first and last records", [flat[0], flat[-1]],
               [(d("2026-06-03"), 71.429, 5), (d("2026-07-13"), 25.714, 2)],
               "Wed 3 Jun – Sun 7 Jun is 5 of the week's 7 days: 100 × 5/7. The horizon ends Wed 15 Jul, so the "
               "last week holds 13–14 Jul: 90 × 2/7.")
        released = {p: sum(r.qty for r in rel_ds.demand if r.product == p) for p in PRICES}

    with ctx.step("Complete the supply side and plan", "plan", "POST /api/plan",
                  "Buying sets up a supplier for the warehouse; MRP then plans exactly the released volumes."):
        raw = json.loads(rel_ds.model_dump_json())
        raw["locations"].append({"id": "SUP", "name": "Wholesaler", "type": "supplier"})
        raw["purchasing_sources"] = [{"id": f"PU-{p}", "supplier": "SUP", "product": p, "location": "WH",
                                      "price": pr / 2, "lead_time_days": 3} for p, pr in PRICES.items()]
        ready = Dataset.model_validate(raw)
        ctx.eq("no blocking errors now", [i.code for i in c.validate(ready) if i.severity == "error"], [])
        plan = c.plan(ready)
        ind = {p: sum(r.qty for r in plan.requirements if r.product == p and r.location == "STORE"
                      and r.kind == "forecast") for p in PRICES}
        ctx.near("store requirements = released forecast", ind, released, 1e-6)
        wh = {p: sum(o.qty for o in plan.orders if o.product == p and o.location == "WH") for p in PRICES}
        ctx.near("warehouse purchases = store demand", wh, released, 1e-6,
                 "No stock anywhere, lot-for-lot: every unit the store sells is bought by the warehouse.")


SCENARIO = Scenario(
    id="s4-grocer", title="Forecasting with known answers", company="Corner Grocer",
    story="Seven products at one store, each built to test one thing: a flat line, a trend, a pure season, an "
          "intermittent item, a promoted product, a series with a freak order and a new launch. The right model, "
          "cleansing, lift, ramp, cannibalisation, override and prorated release are all known in advance. The "
          "warehouse's supply is still being set up, and demand planning must not wait for it.",
    proves=["champion selection with tie-breaks", "exact trend and season", "intermittent pattern and SBA",
            "promotion cleansing and measured lift", "outlier clipping", "NPI ramp and cannibalisation",
            "consensus override", "ABC by revenue", "prorated release of partial weeks",
            "demand planning not blocked by supply gaps", "released volumes reach MRP intact"],
    stages=["readiness", "demand", "plan"],
    build=build, run=run)
