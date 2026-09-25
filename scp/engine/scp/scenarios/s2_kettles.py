"""S2 · Northwind Kettles: distribution requirements and order promising, worked by hand.

A plant ships kettles to two DCs, which serve two customers; the southern DC can also serve the northern
customer over a longer lane. Customer forecasts are weekly buckets split over working days, and four sales
orders consume them. The DRP must carry every unit from the customers back to the plant with the right
offsets. Then the promising workflow: confirm the order book from stock and a transfer in transit, persist
it, quote a new order (partly from the alternative DC, partly capable-to-promise through new production),
and, after the transfer is delayed and a key-account order arrives, run backorder processing so the key
accounts win and the low-priority order loses.
"""
from __future__ import annotations

import json

from ..model import Dataset, DemandRecord
from .harness import Client, Ctx, Scenario, by, d, one

START = "2026-03-02"   # a Monday; 4 weekly buckets to 30 March
WEEKS = ["2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"]


def _fc(loc: str, day: str, qty: float) -> dict:
    return {"location": loc, "product": "KETTLE", "date": day, "qty": qty, "kind": "forecast", "period_days": 7}


def _so(oid: str, loc: str, day: str, qty: float, prio: int, **kw) -> dict:
    return {"id": oid, "location": loc, "product": "KETTLE", "date": day, "qty": qty, "kind": "sales_order",
            "priority": prio, **kw}


def build() -> dict:
    return {
        "settings": {"company_name": "Northwind Kettles", "currency": "EUR", "planning_start": START,
                     "horizon_days": 28, "bucket": "week", "default_calendar": "CAL-5D"},
        "calendars": [{"id": "CAL-5D", "name": "Mon–Fri", "workdays": [0, 1, 2, 3, 4]}],
        "locations": [
            {"id": "PLANT", "name": "Kettle plant", "type": "plant", "region": "Central", "lat": 52.37, "lon": 9.73},
            {"id": "DC-N", "name": "North DC", "type": "dc", "region": "North", "lat": 53.55, "lon": 9.99},
            {"id": "DC-S", "name": "South DC", "type": "dc", "region": "South", "lat": 48.14, "lon": 11.58},
            {"id": "CUST-A", "name": "Retailer A (north)", "type": "customer", "region": "North", "lat": 53.08,
             "lon": 8.80},
            {"id": "CUST-C", "name": "Retailer C (south)", "type": "customer", "region": "South", "lat": 48.37,
             "lon": 10.90},
            {"id": "SUP-EL", "name": "Heating element supplier", "type": "supplier", "lat": 51.23, "lon": 6.78},
        ],
        "products": [{"id": "KETTLE", "name": "1.7 l kettle", "type": "FG", "price": 40, "family": "Kettles"},
                     {"id": "ELEMENT", "name": "Heating element", "type": "RM"}],
        "location_products": [
            {"location": "DC-N", "product": "KETTLE", "on_hand": 120},
            {"location": "DC-S", "product": "KETTLE", "on_hand": 120},
            {"location": "PLANT", "product": "KETTLE", "on_hand": 0},
            {"location": "PLANT", "product": "ELEMENT", "on_hand": 500},
        ],
        "resources": [{"id": "LINE", "location": "PLANT", "efficiency": 1.0, "hours_per_shift": 8, "cost_per_hour": 50}],
        "production_sources": [{"id": "PS-K", "location": "PLANT", "product": "KETTLE",
                                "components": [{"product": "ELEMENT", "qty": 1}],
                                "operations": [{"seq": 10, "resource": "LINE", "run_hours_per_unit": 0.02}]}],
        "purchasing_sources": [{"id": "PU-EL", "supplier": "SUP-EL", "product": "ELEMENT", "location": "PLANT",
                                "price": 10, "lead_time_days": 7}],
        "lanes": [
            {"id": "L-PN", "origin": "PLANT", "destination": "DC-N", "modes": [{"transit_days": 2, "cost_per_unit": 1}]},
            {"id": "L-PS", "origin": "PLANT", "destination": "DC-S", "modes": [{"transit_days": 3, "cost_per_unit": 1.5}]},
            {"id": "L-NA", "origin": "DC-N", "destination": "CUST-A", "modes": [{"transit_days": 1, "cost_per_unit": 0.5}]},
            {"id": "L-SC", "origin": "DC-S", "destination": "CUST-C", "modes": [{"transit_days": 1, "cost_per_unit": 0.5}]},
            {"id": "L-SA", "origin": "DC-S", "destination": "CUST-A", "priority": 2,
             "modes": [{"transit_days": 2, "cost_per_unit": 0.8}]},
        ],
        "demand": [_fc("CUST-A", w, 100) for w in WEEKS] + [_fc("CUST-C", w, 50) for w in WEEKS] + [
            _so("SO-A1", "CUST-A", "2026-03-04", 60, 3),
            _so("SO-C1", "CUST-C", "2026-03-10", 30, 5),
            _so("SO-A2", "CUST-A", "2026-03-06", 100, 7),
            _so("SO-A3", "CUST-A", "2026-03-12", 80, 1, complete_delivery=True),
        ],
        "receipts": [{"id": "STO-900", "kind": "transfer", "location": "DC-N", "product": "KETTLE", "qty": 100,
                      "due_date": "2026-03-11", "source": "L-PN"}],
        # scope of check: stock and firm receipts only (planned orders are not promised)
        "promising": {"include_planned_orders": False},
    }


def _lines(o) -> list[tuple]:
    return [(x.ship_from, x.ship_date, x.date, x.qty, x.method) for x in o.lines]


def run(ctx: Ctx, c: Client, ds: Dataset) -> None:
    with ctx.step("Check the master data", "readiness", "POST /api/validate",
                  "A plant, two DCs and two customer regions with lanes between them: nothing should block."):
        ctx.eq("readiness issues", [f"{i.code} {i.object_id}" for i in c.validate(ds)], [])

    with ctx.step("Read the network", "network", "POST /api/network",
                  "Customers are leaves served over lanes; the south DC is a second source for retailer A."):
        net = c.network(ds)
        opts = one(net.nodes, location="CUST-A", product="KETTLE").options
        ctx.eq("sources of retailer A, in priority order", [(o.kind, o.source_id) for o in opts],
               [("transfer", "L-NA"), ("transfer", "L-SA")])
        llc = {(n.location, n.product): n.llc for n in net.nodes}
        ctx.eq("low-level codes customer → DC → plant → element",
               [llc[("CUST-A", "KETTLE")], llc[("DC-N", "KETTLE")], llc[("PLANT", "KETTLE")], llc[("PLANT", "ELEMENT")]],
               [0, 1, 2, 3])

    with ctx.step("Run DRP / MRP", "plan", "POST /api/plan",
                  "Forecast is consumed by the orders, split over working days, and pulled back through the DCs "
                  "to the plant with each lane's transit."):
        plan = c.plan(ds)
        fc_a = {}
        for r in plan.requirements:
            if r.location == "CUST-A" and r.kind == "forecast":
                wk = next(w for w in reversed(WEEKS) if r.date >= d(w))
                fc_a[wk] = fc_a.get(wk, 0) + r.qty
        ctx.near("retailer A forecast left per week after consumption", [fc_a.get(w, 0) for w in WEEKS],
                 [0, 0, 60, 100], 1e-9,
                 "SO-A1 60 (4 Mar) takes 60 of week 1; SO-A2 100 (6 Mar) takes the last 40 backward and 60 of week 2 "
                 "forward; SO-A3 80 (12 Mar) takes week 2's last 40 backward and 40 of week 3 forward.")
        ctx.near("week-3 forecast is split over its 5 working days",
                 sorted(r.qty for r in plan.requirements if r.location == "CUST-A" and r.kind == "forecast"
                        and d("2026-03-16") <= r.date < d("2026-03-23")), [12] * 5, 1e-9)
        dcn = sorted(by(plan.orders, location="DC-N"), key=lambda o: o.need_date)
        ctx.eq("north DC replenishment (need, ship, qty)", [(o.need_date, o.start_date, o.qty) for o in dcn], [
            (d("2026-03-05"), d("2026-03-03"), 40), (d("2026-03-16"), d("2026-03-13"), 4),
            (d("2026-03-17"), d("2026-03-13"), 12), (d("2026-03-18"), d("2026-03-16"), 12),
            (d("2026-03-19"), d("2026-03-17"), 12), (d("2026-03-20"), d("2026-03-18"), 20),
            (d("2026-03-23"), d("2026-03-20"), 20), (d("2026-03-24"), d("2026-03-20"), 20),
            (d("2026-03-25"), d("2026-03-23"), 20), (d("2026-03-26"), d("2026-03-24"), 20)],
            "Deliveries to A leave the DC a day early (5 Mar: 100 for SO-A2): 120 on hand − 60 − 100 → short 40 "
            "on 5 Mar, shipped from the plant 3 Mar (2 days' transit). STO-900 (100, 11 Mar) then covers SO-A3's 80 "
            "and 8 more; from 16 Mar each day's shipment is replaced, shipped two days earlier on plant working days "
            "(a Monday need ships the Friday before). Σ = 400 − 120 − 100 = 180.")
        dcs = by(plan.orders, location="DC-S")
        ctx.near("south DC replenishment total", sum(o.qty for o in dcs), 200 - 120, 1e-9,
                 "Retailer C needs 200 (SO-C1 inside the forecast); 120 on hand; 8 shipments of 10 from 17 Mar.")
        make = by(plan.orders, location="PLANT", kind="make")
        ctx.near("plant production", sum(o.qty for o in make), 180 + 80, 1e-9, "Every unit shipped to the DCs.")
        ctx.eq("no element purchases (500 on hand ≥ 260)", len(by(plan.orders, product="ELEMENT")), 0)
        first = min(make, key=lambda o: o.need_date)
        ctx.eq("first production order (need, start, qty)", (first.need_date, first.start_date, first.qty),
               (d("2026-03-03"), d("2026-03-02"), 40))
        ctx.eq("demand at risk", [(e.location, e.qty) for e in plan.exceptions if e.code == "DEMAND_AT_RISK"],
               [("CUST-C", 10.0)],
               "Retailer C's Monday 2 Mar share (10) needs a shipment on Friday 27 Feb: before today, so it lands "
               "3 Mar. Retailer A has no requirement that Monday (its week 1 forecast is consumed).")
        ctx.near("on-time fill rate", plan.kpis.on_time_fill_rate, 590 / 600, 1e-9)

    with ctx.step("Promise the order book", "promise", "POST /api/promise",
                  "Available-to-promise over stock and the firm transfer, orders in entry sequence, the south DC "
                  "as the alternative for retailer A."):
        pr = c.promise(ds)
        got = {o.order: _lines(o) for o in pr.orders}
        ctx.eq("SO-A1", got["SO-A1"], [("DC-N", d("2026-03-03"), d("2026-03-04"), 60, "atp")])
        ctx.eq("SO-C1", got["SO-C1"], [("DC-S", d("2026-03-09"), d("2026-03-10"), 30, "atp")])
        ctx.eq("SO-A2 (split over both DCs)", got["SO-A2"],
               [("DC-S", d("2026-03-04"), d("2026-03-06"), 40, "atp"), ("DC-N", d("2026-03-05"), d("2026-03-06"), 60, "atp")],
               "North: 120 − 60 = 60 left on 5 Mar; the other 40 ship from the south DC on 4 Mar (2 days' transit).")
        ctx.eq("SO-A3 (complete delivery from the transfer)", got["SO-A3"],
               [("DC-N", d("2026-03-11"), d("2026-03-12"), 80, "atp")],
               "The north DC is empty until STO-900 lands 11 Mar with 100; the whole 80 ships that day.")
        ctx.eq("KPIs (orders on time, alternative lines)", (pr.kpis.on_time_orders, pr.kpis.alternative_lines), (4, 1))

    with ctx.step("Persist the confirmations", "promise", "POST /api/promise/commit",
                  "Committing stores the schedule lines in the dataset, so later checks and BOP start from them."):
        ds2, _ = c.commit(ds)
        ctx.eq("schedule lines stored", len(ds2.confirmations), 5)

    with ctx.step("Quote a new order", "promise", "POST /api/promise/check",
                  "Retailer A asks for 150 on Monday 9 Mar."):
        q = c.check(ds2, DemandRecord(location="CUST-A", product="KETTLE", date=d("2026-03-09"), qty=150,
                                      kind="sales_order")).checked
        ctx.eq("quote", _lines(q), [("DC-N", d("2026-03-06"), d("2026-03-09"), 100, "ctp"),
                                    ("DC-S", d("2026-03-06"), d("2026-03-09"), 50, "atp")],
               "North has nothing free until 11 Mar; the south DC has 120 − 40 − 30 = 50. The other 100 are "
               "capable-to-promise: 100 elements in stock, 2 h on the line on 2 Mar, 2 days to the north DC by 5 Mar. "
               "Both lines arrive by the requested Monday, so they are confirmed for the Monday, not the weekend.")
        ctx.eq("CTP chain", [(s.kind, s.location, s.start, s.end) for s in q.ctp], [
            ("component", "PLANT", d("2026-03-02"), None), ("capacity", "PLANT", d("2026-03-02"), d("2026-03-03")),
            ("make", "PLANT", d("2026-03-02"), d("2026-03-03")), ("transfer", "DC-N", d("2026-03-03"), d("2026-03-05"))])

    raw = json.loads(ds2.model_dump_json())
    raw["receipts"][0]["due_date"] = "2026-03-20"
    raw["demand"].append(_so("SO-A4", "CUST-A", "2026-03-10", 70, 2))
    ds3 = Dataset.model_validate(raw)

    with ctx.step("The transfer slips to 20 March", "promise", "POST /api/promise",
                  "STO-900 is delayed nine days and key account A orders 70 more. Which promises are now at risk?"):
        pr3 = c.promise(ds3)
        ctx.eq("promises at risk", sorted(o.order for o in pr3.orders if o.at_risk), ["SO-A3"],
               "North stock: 120 − 60 (3 Mar) − 60 (5 Mar) = 0, so SO-A1 and SO-A2 still ship from stock on the shelf. "
               "Only SO-A3 (80 on 11 Mar) waited for the transfer.")

    with ctx.step("Backorder processing without CTP", "promise", "POST /api/promise/bop",
                  "Key accounts (priority 1–2) win, standard orders are redistributed, low priority may lose."):
        raw["promising"]["ctp"] = False
        bop = c.bop(Dataset.model_validate(raw))
        rows = {r.order: r for r in bop.bop}
        ctx.eq("outcomes", {k: rows[k].outcome for k in sorted(rows)},
               {"SO-A1": "changed", "SO-A2": "lost", "SO-A3": "unchanged", "SO-A4": "gained", "SO-C1": "unchanged"},
               "SO-A3 keeps 80 of the 120 on the shelf; SO-A4 takes the other 40 and 30 from the south DC; SO-A1 "
               "moves to the south DC; SO-C1 keeps its 30; SO-A2 (priority 7) finds nothing until the replenishment "
               "lead time and ships 13 Mar, a week late.")
        a2 = one(bop.orders, order="SO-A2")
        ctx.eq("SO-A2 after BOP", _lines(a2), [("DC-N", d("2026-03-13"), d("2026-03-14"), 100, "rlt")])
        ctx.near("on-time quantity after BOP", bop.kpis.on_time_qty, 240, 1e-9, "340 ordered − SO-A2's 100.")

    with ctx.step("Backorder processing with CTP", "promise", "POST /api/promise/bop",
                  "With capable-to-promise on, the plant can make SO-A2's 100 in time."):
        raw["promising"]["ctp"] = True
        bop2 = c.bop(Dataset.model_validate(raw))
        a2 = one(bop2.orders, order="SO-A2")
        ctx.eq("SO-A2 rescued by new production", _lines(a2), [("DC-N", d("2026-03-05"), d("2026-03-06"), 100, "ctp")])

    with ctx.step("See it in the control tower", "tower", "POST /api/tower",
                  "The order put at risk by the slipped transfer must land on the worklist, in the delivery category."):
        tw = c.tower(ds3)
        items = sorted((w.code, w.order_id) for w in tw.worklist if w.code == "PROMISE_AT_RISK")
        ctx.eq("worklist: promise at risk", items, [("PROMISE_AT_RISK", "SO-A3")])
        cat = {w.code: w.category for w in tw.worklist}
        ctx.eq("category", cat.get("PROMISE_AT_RISK"), "delivery")


SCENARIO = Scenario(
    id="s2-kettles", title="Distribution and order promising", company="Northwind Kettles",
    story="A plant supplies two DCs that serve two retailers; the south DC can also reach the north retailer. "
          "Weekly forecasts are consumed by four sales orders and split over working days. The order book is "
          "promised from stock and a transfer in transit, a new order is quoted partly by capable-to-promise, and "
          "when the transfer slips and a key account orders more, backorder processing decides who wins.",
    proves=["forecast consumption across weeks", "PIR splitting over working days", "multi-echelon DRP offsets",
            "cumulative ATP with look-ahead", "alternative shipping location", "complete delivery",
            "capable-to-promise through production and transfer", "at-risk detection after a delay",
            "backorder processing: win, redistribute, lose", "control-tower worklist"],
    stages=["readiness", "network", "plan", "promise", "tower"],
    build=build, run=run)
