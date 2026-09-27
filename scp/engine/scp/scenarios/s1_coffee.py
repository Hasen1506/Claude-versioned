"""S1 · Lighthouse Coffee Roasters: a three-level MRP worked by hand.

The plant packs 1 kg bags of coffee (FG) from roasted beans (SFG) and bags (PKG); roasting turns green
beans (RM, shipped by sea from a USD supplier) into roasted beans, losing weight and some batches.
Everything MRP does between a forecast and a purchase order shows up here: forecast consumption by sales
orders, a fixed safety stock, three lot-sizing rules (lot-for-lot, fixed, periodic with a pack rounding),
MOQ, component and assembly scrap, a routing lead time that depends on the batch size with a queue day, a
holiday in the factory calendar, landed cost (FX, duty, freight per kg, per-shipment freight, handling), and
a purchase that cannot arrive in time, whose delay the plan must carry down to the customer.
"""
from __future__ import annotations

from ..model import Dataset
from .harness import Client, Ctx, Scenario, by, d, one

START = "2026-01-05"   # a Monday; the plan runs 8 weekly buckets to 2 March


def _fc(day: str, qty: float) -> dict:
    return {"location": "PLANT-LH", "product": "FG-BAG", "date": day, "qty": qty, "kind": "forecast"}


def build() -> dict:
    return {
        "settings": {"company_name": "Lighthouse Coffee Roasters", "currency": "AUD", "planning_start": START,
                     "horizon_days": 56, "bucket": "week", "fx_rates": {"USD": 1.5}, "wacc": 0.10,
                     "holding_spread": 0.10, "default_calendar": "ROAST-CAL"},
        "calendars": [{"id": "ROAST-CAL", "name": "Mon–Fri, Australia Day off", "workdays": [0, 1, 2, 3, 4],
                       "holidays": ["2026-01-26"]}],
        "locations": [
            {"id": "PLANT-LH", "name": "Lighthouse roastery", "type": "plant", "calendar": "ROAST-CAL",
             "handling_cost_per_unit": 0.05, "lat": -33.87, "lon": 151.21},
            {"id": "SUP-GREEN", "name": "Green bean importer (Santos)", "type": "supplier", "lat": -23.96, "lon": -46.33},
            {"id": "SUP-PACK", "name": "Bag printer", "type": "supplier", "lat": -33.95, "lon": 151.14},
        ],
        "products": [
            {"id": "FG-BAG", "name": "Harbour Blend 1 kg", "type": "FG", "price": 30, "family": "Coffee"},
            {"id": "SFG-ROAST", "name": "Roasted beans", "type": "SFG", "base_uom": "KG"},
            {"id": "RM-GREEN", "name": "Green beans", "type": "RM", "base_uom": "KG", "weight_kg": 1.0},
            {"id": "PKG-BAG", "name": "Printed valve bag", "type": "PKG"},
        ],
        "location_products": [
            {"location": "PLANT-LH", "product": "FG-BAG", "on_hand": 300, "strategy": "MTS_CONSUME",
             "safety_stock": {"method": "fixed", "qty": 100}},
            {"location": "PLANT-LH", "product": "SFG-ROAST", "on_hand": 200,
             "lot_sizing": {"policy": "FIXED", "fixed_qty": 500}},
            {"location": "PLANT-LH", "product": "RM-GREEN", "on_hand": 1000, "gr_processing_days": 2},
            {"location": "PLANT-LH", "product": "PKG-BAG", "on_hand": 400,
             "lot_sizing": {"policy": "POQ", "periods": 2}},
        ],
        "resources": [
            {"id": "ROASTER", "location": "PLANT-LH", "shifts_per_day": 2, "hours_per_shift": 8, "efficiency": 0.75,
             "cost_per_hour": 90},
            {"id": "PACK-LINE", "location": "PLANT-LH", "shifts_per_day": 1, "hours_per_shift": 8, "efficiency": 1.0,
             "cost_per_hour": 60},
        ],
        "production_sources": [
            {"id": "PV-BAG", "location": "PLANT-LH", "product": "FG-BAG", "fixed_lead_time_workdays": 1,
             "conversion_cost_per_unit": 0.5,
             "components": [{"product": "SFG-ROAST", "qty": 1}, {"product": "PKG-BAG", "qty": 1, "scrap": 0.02}],
             "operations": [{"seq": 10, "resource": "PACK-LINE", "setup_hours": 1, "run_hours_per_unit": 0.01}]},
            {"id": "PV-ROAST", "location": "PLANT-LH", "product": "SFG-ROAST", "output_qty": 100, "assembly_scrap": 0.04,
             "conversion_cost_per_unit": 0.25, "components": [{"product": "RM-GREEN", "qty": 120}],
             "operations": [{"seq": 10, "resource": "ROASTER", "setup_hours": 2, "run_hours_per_unit": 0.02,
                             "queue_workdays": 1}]},
        ],
        "purchasing_sources": [
            {"id": "PU-GREEN", "supplier": "SUP-GREEN", "product": "RM-GREEN", "location": "PLANT-LH", "price": 6,
             "currency": "USD", "duty_rate": 0.05, "ordering_cost": 50, "moq": 600, "rounding_qty": 60,
             "lead_time_days": 10},
            {"id": "PU-BAG", "supplier": "SUP-PACK", "product": "PKG-BAG", "location": "PLANT-LH", "price": 0.40,
             "ordering_cost": 20, "rounding_qty": 500, "lead_time_days": 5},
        ],
        # the sea lane carries "all products": only what is bought from its supplier travels on it
        "lanes": [{"id": "LN-SEA", "origin": "SUP-GREEN", "destination": "PLANT-LH",
                   "modes": [{"mode": "sea", "transit_days": 14, "cost_per_kg": 0.10, "cost_per_shipment": 300,
                              "vehicle_capacity_kg": 20000}]}],
        "demand": [
            _fc("2026-01-05", 200), _fc("2026-01-12", 250), _fc("2026-01-19", 300), _fc("2026-01-26", 300),
            _fc("2026-02-02", 350), _fc("2026-02-09", 400), _fc("2026-02-16", 400), _fc("2026-02-23", 450),
            {"id": "SO-CAFE-1", "location": "PLANT-LH", "product": "FG-BAG", "date": "2026-01-14", "qty": 120,
             "kind": "sales_order"},
            {"id": "SO-CAFE-2", "location": "PLANT-LH", "product": "FG-BAG", "date": "2026-02-18", "qty": 500,
             "kind": "sales_order"},
        ],
    }


# Hand-derived plan (see the derivations in each checkpoint's `why`).
FG_ORDERS = [  # (need = due, start, qty): lot-for-lot, 1 working day of packing, finish on the need date
    ("2026-01-12", "2026-01-09", 130), ("2026-01-14", "2026-01-13", 120), ("2026-01-19", "2026-01-16", 300),
    ("2026-01-26", "2026-01-22", 300), ("2026-02-02", "2026-01-30", 350), ("2026-02-09", "2026-02-06", 400),
    ("2026-02-18", "2026-02-17", 500), ("2026-02-23", "2026-02-20", 350),
]
ROAST_ORDERS = [  # (need, start): FIXED 500 kg; 2 roasting days + 1 queue (cooling) day
    ("2026-01-13", "2026-01-08"), ("2026-01-22", "2026-01-19"), ("2026-02-06", "2026-02-03"),
    ("2026-02-17", "2026-02-12"), ("2026-02-20", "2026-02-17"),
]
GREEN_POS = [  # (need, start, available): MOQ 600; 10 d supplier + 14 d sea + 2 d goods receipt = 26 d
    ("2026-01-19", "2026-01-05", "2026-01-31"), ("2026-02-03", "2026-01-08", "2026-02-03"),
    ("2026-02-12", "2026-01-16", "2026-02-11"), ("2026-02-17", "2026-01-22", "2026-02-17"),  # 17 Jan is a Saturday
]
BAG_POS = [("2026-01-16", 500), ("2026-01-30", 1000), ("2026-02-17", 1000)]


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Check the master data", "readiness", "POST /api/validate",
                  "The sea lane is open to every product, but only green beans are bought from its supplier. "
                  "The gate must not ask for weights of products that never travel on it."):
        issues = c.validate(ds)
        ctx.eq("readiness issues", sorted(f"{i.code} {i.object_id}" for i in issues), [],
               "Every object is complete; RM-GREEN, the only product on LN-SEA, has a weight.")

    with ctx.step("Read the network", "network", "POST /api/network",
                  "Low-level codes order the planning: bags before roast before green beans."):
        net = c.network(ds)
        llc = {(n.location, n.product): n.llc for n in net.nodes}
        ctx.eq("low-level codes", {p: llc[("PLANT-LH", p)] for p in ("FG-BAG", "SFG-ROAST", "PKG-BAG", "RM-GREEN")},
               {"FG-BAG": 0, "SFG-ROAST": 1, "PKG-BAG": 1, "RM-GREEN": 2},
               "FG consumes roast and bags (1); roast consumes green (2).")

    with ctx.step("Run MRP", "plan", "POST /api/plan",
                  "Net requirements level by level, lot-size, schedule backward on the roastery calendar and "
                  "explode through the BOM."):
        plan = c.plan(ds)
        ctx.eq("plan solved", plan.ok, True)
        ind = sorted((r.date, r.qty, r.kind) for r in plan.requirements
                     if r.product == "FG-BAG" and r.kind in ("forecast", "sales_order"))
        ctx.eq("independent requirements after forecast consumption", ind, [
            (d("2026-01-05"), 200, "forecast"), (d("2026-01-12"), 130, "forecast"),
            (d("2026-01-14"), 120, "sales_order"), (d("2026-01-19"), 300, "forecast"),
            (d("2026-01-26"), 300, "forecast"), (d("2026-02-02"), 350, "forecast"),
            (d("2026-02-09"), 400, "forecast"), (d("2026-02-18"), 500, "sales_order"),
            (d("2026-02-23"), 350, "forecast")],
            "SO-CAFE-1 (120, 14 Jan) consumes backward: 250 on 12 Jan → 130. SO-CAFE-2 (500, 18 Feb) consumes "
            "all 400 on 16 Feb backward, then 100 of the 450 on 23 Feb forward. Total stays 2,650.")

        fg = sorted(by(plan.orders, product="FG-BAG"), key=lambda o: o.need_date)
        ctx.eq("FG orders (need, start, qty)", [(o.need_date, o.start_date, o.qty) for o in fg],
               [(d(a), d(b), q) for a, b, q in FG_ORDERS],
               "On hand 300 − 200 = 100 = safety stock, so every later requirement is ordered lot-for-lot. One "
               "working day of packing: start = the working day before the need. 26 Jan is a holiday, so the "
               "order for it finishes Fri 23 Jan and starts Thu 22 Jan. Σ = 2,650 − (300 − 100) = 2,450.")

        roast = sorted(by(plan.orders, product="SFG-ROAST"), key=lambda o: o.need_date)
        ctx.eq("roast orders (need, start, qty)", [(o.need_date, o.start_date, o.qty) for o in roast],
               [(d(a), d(b), 500) for a, b in ROAST_ORDERS],
               "Packing starts draw roast (200 on hand): 130, 120 → short 50 on 13 Jan → one fixed lot of 500; "
               "then short on 22 Jan, 6 Feb, 17 Feb and 20 Feb. A lot of 500 kg starts 500 ÷ 0.96 = 520.8 kg: "
               "2 h setup + 0.02 h/kg = 12.42 h on a 12 h/day roaster (2 × 8 h × 0.75) → 2 working days, "
               "then 1 queue day, finishing on the need date.")
        mo9 = roast[0]
        green_reqs = sorted((r.date, round(r.qty, 6)) for r in plan.requirements if r.product == "RM-GREEN")
        ctx.eq("green-bean requirements (date, kg)", green_reqs, [(d(b), 625.0) for _, b in ROAST_ORDERS],
               "Per kg of good roast: 1.2 kg green (120 per 100) ÷ (1 − 0.04 assembly scrap) = 1.25, so each "
               "500 kg lot needs 625 kg on its first roasting day.")
        bag_total = sum(r.qty for r in plan.requirements if r.product == "PKG-BAG")
        ctx.near("bag requirements (component scrap 2 %)", bag_total, 2450 / 0.98, 1e-6,
                 "2,450 bags packed ÷ (1 − 0.02) = 2,500 issued.")

        green = sorted(by(plan.orders, product="RM-GREEN"), key=lambda o: o.need_date)
        ctx.eq("green-bean POs (need, start, available, qty)",
               [(o.need_date, o.start_date, o.available_date, o.qty) for o in green],
               [(d(a), d(b), d(c_), 600) for a, b, c_ in GREEN_POS],
               "1,000 on hand covers 8 Jan; each later shortage (250, 275, 300, 325 kg) is raised to the MOQ of "
               "600 (a multiple of 60-kg sacks). 26 days of lead time put the first order before today, so it "
               "starts today and arrives 31 Jan, 12 days late. The third would be placed on Saturday 17 Jan; the "
               "buyers work Monday to Friday, so it goes out on Friday 16 Jan and arrives a day early.")
        ctx.eq("first green PO flagged start-in-past", green[0].start_in_past, True)

        bags = sorted(by(plan.orders, product="PKG-BAG"), key=lambda o: o.need_date)
        ctx.eq("bag POs (need, qty)", [(o.need_date, o.qty) for o in bags], [(d(a), q) for a, q in BAG_POS],
               "POQ covers the shortage plus the rest of the next bucket, rounded up to packs of 500: "
               "161.2 + 306.1 → 500; 324.5 + 408.2 → 1,000; 242.9 + 357.1 → 1,000.")

        late_roast = one(roast, need_date=d("2026-01-22"))
        ctx.eq("the 19 Jan roast: on time, then late (qty on time, last date, delay)",
               (late_roast.projected_on_time_qty, late_roast.projected_available_date, late_roast.delay_days),
               (300.0, d("2026-02-03"), 12.0),
               "It needs 625 kg green on 19 Jan; 375 kg are left on hand, the other 250 kg wait for the late PO "
               "(31 Jan, +12 days). 375 ÷ 625 = 60 % of the lot, 300 kg, finishes on time on 22 Jan; the other "
               "200 kg on 3 Feb.")
        on_time_mo = one(fg, need_date=d("2026-01-26"))
        ctx.eq("the 26 Jan packing order is covered by the on-time roast",
               (on_time_mo.projected_on_time_qty, on_time_mo.delay_days), (300.0, 0.0),
               "Its 300 kg of roast: 150 left of the first lot, then the first 150 of the on-time 300 of the second.")
        late_mo = one(fg, need_date=d("2026-02-02"))
        ctx.eq("delay carried to the 2 Feb packing order (qty on time, last date, delay)",
               (late_mo.projected_on_time_qty, late_mo.projected_available_date, late_mo.delay_days),
               (150.0, d("2026-02-06"), 4.0),
               "Its 350 kg of roast: the last 150 of the on-time 300, then the 200 kg that finish 3 Feb, 4 days "
               "after its 30 Jan start, so 200 bags slip from 2 Feb to 6 Feb.")
        risk = [e for e in plan.exceptions if e.code == "DEMAND_AT_RISK"]
        ctx.near("demand at risk (bags)", sum(e.qty or 0 for e in risk), 100, 1e-6,
                 "Pegging FIFO: 2 Feb needs 350: 100 from the 26 Jan order (on time) and 250 from the 2 Feb order, "
                 "which has 150 on time. The 200 late bags arrive 6 Feb: 100 of them go to 2 Feb, the other 100 to "
                 "9 Feb, which they still reach on time. 100 late.")
        ctx.near("on-time fill rate", plan.kpis.on_time_fill_rate, 2550 / 2650, 1e-9, "(2,650 − 100) ÷ 2,650")
        ctx.eq("exceptions", sorted((e.code, e.product) for e in plan.exceptions),
               [("DEMAND_AT_RISK", "FG-BAG"), ("START_IN_PAST", "RM-GREEN"), ("STOCKOUT", "RM-GREEN")],
               "Green beans run 250 kg short in the week of 19 Jan; nothing else is wrong.")
        fg_node = one(plan.nodes, product="FG-BAG")
        ctx.eq("FG demand at risk by bucket", [round(b.at_risk, 6) for b in fg_node.buckets],
               [0, 0, 0, 0, 100, 0, 0, 0],
               "The stock view must show the 100 late bags where they fall (week of 2 Feb), not a healthy 100 on "
               "hand, and not the whole roast lot as late when 60 % of it is on time.")

        k = plan.kpis
        ctx.near("purchase cost", k.purchase_cost, 4 * 600 * 6 * 1.5 * 1.05 + 2500 * 0.40, 1e-6,
                 "Green: 600 kg × 6 USD × 1.5 AUD/USD × 1.05 duty = 5,670 per PO × 4; bags: 2,500 × 0.40.")
        ctx.near("production cost", k.production_cost, 2450 * (0.01 * 60 + 0.5) + 2500 * (0.02 * 90 / 0.96 + 0.25), 1e-6,
                 "Packing 0.01 h × 60 + 0.50 per bag; roasting 0.02 h × 90 ÷ 0.96 + 0.25 per good kg.")
        ctx.near("setup cost", k.setup_cost, 8 * 1 * 60 + 5 * 2 * 90, 1e-6, "8 packing setups of 1 h, 5 roasts of 2 h.")
        ctx.near("ordering cost", k.ordering_cost, 4 * 50 + 3 * 20, 1e-6)
        ctx.near("transport cost", k.transport_cost, 4 * (600 * 0.10 + 300), 1e-6,
                 "0.10 per kg plus 300 per sea shipment (600 kg fits one 20 t container).")
        ctx.near("handling cost", k.handling_cost, (2400 + 2500) * 0.05, 1e-6, "0.05 per unit received from suppliers.")
        uv = {n.product: n.unit_value for n in plan.nodes}
        ctx.near("unit values (landed / rolled up)", [uv["RM-GREEN"], uv["PKG-BAG"], uv["SFG-ROAST"], uv["FG-BAG"]],
                 [9.60, 0.45, 12.0 + 2.125, 14.125 + 0.45 / 0.98 + 1.1], 1e-9,
                 "Green 9.45 + 0.10 freight + 0.05 handling; bag 0.40 + 0.05; roast 1.25 × 9.60 + 2.125; "
                 "bag of coffee 14.125 + 0.45 ÷ 0.98 + 1.10.")
        poh = {n.product: [max(0.0, b.projected_on_hand) for b in n.buckets] for n in plan.nodes}
        holding = sum(q * uv[p] * 0.20 * 7 / 365 for p, xs in poh.items() for q in xs)
        ctx.near("holding cost", k.holding_cost, holding, 1e-6,
                 "Σ end-of-week stock × unit value × 20 %/year × 7/365.")

        roaster = one(plan.resources, resource="ROASTER")
        ctx.near("roaster load by week (h)", [b.load_hours for b in roaster.buckets],
                 [12.4166667, 0, 12.4166667, 0, 12.4166667, 12.4166667, 12.4166667, 0], 1e-6)
        ctx.near("roaster capacity in the holiday week (h)", roaster.buckets[3].capacity_hours, 48, 1e-9,
                 "4 working days × 12 h.")
        ctx.eq("roast order uses its routing lead time", (mo9.start_date, mo9.due_date), (d("2026-01-08"), d("2026-01-13")))

    with ctx.step("Reconcile the plan in money", "finance", "POST /api/finance",
                  "Every cost the plan spends must land on a customer or be named as unabsorbed."):
        fin = c.finance(ds)
        rec = fin.reconciliation
        ctx.true("books close category by category", rec is not None and rec.reconciled,
                 actual=[(x.category, round(x.difference, 9)) for x in rec.lines] if rec else None,
                 expect="every category's difference is 0")
        ctx.near("total plan cost = MRP total", rec.total_plan if rec else None, plan.kpis.total_cost, 1e-6)
        ctx.near("opening inventory value", fin.inventory.start if fin.inventory else None,
                 300 * uv["FG-BAG"] + 200 * uv["SFG-ROAST"] + 1000 * 9.60 + 400 * 0.45, 1e-6)

    with ctx.step("Firm the next two weeks and re-plan", "execution", "POST /api/orders/firm → POST /api/plan",
                  "Converting planned orders to firm orders must not change the plan: no new orders, same stock."):
        firmed, rep = c.firm(ds, within_days=14)
        ctx.eq("orders firmed (start before 19 Jan)", len(rep.firmed),
               len([o for o in plan.orders if o.start_date < d("2026-01-19")]))
        again = c.plan(firmed)
        before = {(n.location, n.product): [round(b.projected_on_hand, 6) for b in n.buckets] for n in plan.nodes}
        after = {(n.location, n.product): [round(b.projected_on_hand, 6) for b in n.buckets] for n in again.nodes}
        ctx.eq("projection unchanged after firming", after, before)
        ctx.eq("planned orders left", len(again.orders), len(plan.orders) - len(rep.firmed))
        resched = [(e.order_id, e.date) for e in again.exceptions if e.code == "RESCHEDULE_IN"]
        po = next(f.receipt_id for f in rep.firmed if f.planned_id == green[0].id)
        ctx.eq("the late PO is expedited, not bought twice", resched, [(po, d("2026-01-19"))],
               "The firm PO lands 31 Jan for a 19 Jan need. A new order could not arrive before 31 Jan either, so "
               "MRP asks to expedite the PO (reschedule in) instead of ordering another 600 kg.")


SCENARIO = Scenario(
    id="s1-coffee", title="Three-level MRP by hand", company="Lighthouse Coffee Roasters",
    story="A roastery packs 1 kg bags from roasted beans and printed bags, and roasts green beans shipped by sea "
          "from Brazil. A forecast with two café orders, a fixed safety stock, three lot-sizing rules, scrap on two "
          "levels, a public holiday and a 26-day import lead time. The first import cannot arrive in time: the "
          "plan must say which bags will be late and by how much.",
    proves=["forecast consumption (backward and forward)", "lot-for-lot, fixed and periodic lots with MOQ and rounding",
            "component and assembly scrap", "routing lead time that depends on the batch", "factory calendar holiday",
            "landed cost with FX, duty and freight", "delay propagation to demand", "cost KPIs and holding cost",
            "finance reconciliation", "firming leaves the plan unchanged"],
    stages=["readiness", "network", "plan", "finance", "execution"],
    found=["A per-kg lane from a supplier flagged a missing weight on products that supplier never sells",
           "The projection showed demand reached a day late as covered, while the exception list called it at risk",
           "Firming a late order made the next run plan a second one instead of rescheduling the firm order in",
           "A purchase order was placed on a Saturday: the start was offset by lead time but not moved to a working day",
           "An order whose input was only partly late was projected late as a whole: 550 bags at risk where 100 are "
           "(found by an outside test, where promising confirmed 35 of 50 on time and MRP called all 50 late)"],
    build=build, run=run)
