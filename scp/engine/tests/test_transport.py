"""Enterprise 6.3: carriers, freight orders, load building by weight and volume, freight cost and its settlement.

The oracles are worked by hand: first fit heaviest first into vehicles of so many kilograms and cubic metres, each
vehicle costed at its rate (never under its minimum), the cheapest carrier chosen, the bill shared by weight.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from scp import transport as tm
from scp.api.app import app
from scp.model import Dataset
from scp.sales import create_deliveries, to_deliver
from scp.transport import TransportError
from scp.validate import validate

from .factory import example_dict

client = TestClient(app)
D0 = date(2026, 3, 2)


def company(kg: list[float], days: list[int] | None = None, carriers: list[dict] | None = None, **lane) -> dict:
    """A DC W shipping to customer C on lane L (a 1,000 kg, 10 m³ truck): one delivery of product X (1 kg, 0.001 m³ a
    unit) per weight in ``kg``, planned ``days`` after the start."""
    days = days or [0] * len(kg)
    mode = {"mode": "truck_ftl", "transit_days": 1, "vehicle_capacity_kg": 1000, "vehicle_capacity_m3": 10,
            "cost_per_shipment": 200, "cost_per_kg": 2, **lane}
    return {
        "settings": {"planning_start": D0.isoformat(), "horizon_days": 28},
        "locations": [{"id": "W", "type": "dc"}, {"id": "C", "type": "customer"}, {"id": "S", "type": "supplier"}],
        "products": [{"id": "X", "type": "FG", "weight_kg": 1, "volume_m3": 0.001},
                     {"id": "Y", "type": "FG", "weight_kg": 0.1, "volume_m3": 0.04}],
        "location_products": [{"location": "W", "product": "X", "on_hand": 10000}],
        "purchasing_sources": [{"id": "B-X", "supplier": "S", "location": "W", "product": "X", "price": 1,
                                "lead_time_days": 2}],
        "lanes": [{"id": "L", "origin": "W", "destination": "C", "modes": [mode]}],
        "deliveries": [{"id": f"DL-{i + 1:05d}", "customer": "C", "ship_from": "W", "created_on": D0.isoformat(),
                        "planned_on": (D0 + timedelta(days=d)).isoformat(),
                        "lines": [{"order": f"SO-{i + 1}", "product": "X", "qty": q}]}
                       for i, (q, d) in enumerate(zip(kg, days, strict=True))],
        "carriers": carriers or [],
    }


def ds(d: dict) -> Dataset:
    return Dataset.model_validate(d)


def loads(x: Dataset) -> list[list[str]]:
    return [v.deliveries for g in tm.plan_loads(x)[0] for v in g.vehicles]


# ---- load building ----------------------------------------------------------------------------------------------
def test_first_fit_heaviest_first_into_vehicles_of_a_tonne():
    # 600, 500, 300, 200 kg: 600 → 1; 500 → 2 (1,100 > 1,000); 300 → 1 (900); 200 → 2 (1,100 in 1, 700 in 2)
    assert loads(ds(company([600, 500, 300, 200]))) == [["DL-00001", "DL-00003"], ["DL-00002", "DL-00004"]]


def test_volume_fills_a_vehicle_before_weight_does():
    d = company([1, 1, 1])
    for dl in d["deliveries"]:
        dl["lines"] = [{"order": dl["lines"][0]["order"], "product": "Y", "qty": 100}]   # 10 kg but 4 m³ each
    g = tm.plan_loads(ds(d))[0][0]
    assert [len(v.deliveries) for v in g.vehicles] == [2, 1]          # 8 m³ fits, 12 m³ does not
    assert g.vehicles[0].fill == pytest.approx(0.8)                    # the fuller of 2 % by weight and 80 % by volume


def test_a_load_bigger_than_a_vehicle_goes_alone_and_is_named():
    v = tm.plan_loads(ds(company([1200, 100])))[0][0].vehicles
    assert [(x.deliveries, x.over) for x in v] == [(["DL-00001"], True), (["DL-00002"], False)]


def test_a_packed_delivery_weighs_what_the_scale_said():
    d = company([300])
    d["deliveries"][0] |= {"packages": 3, "gross_kg": 345}
    assert tm.plan_loads(ds(d))[0][0].vehicles[0].weight_kg == 345


def test_loads_within_the_window_share_a_vehicle_and_the_later_one_goes_early():
    d = company([300, 300], days=[0, 2])
    assert len(tm.plan_loads(ds(d))[0]) == 2                           # no window: a vehicle each day
    d["transport"] = {"window_days": 2}
    g = tm.plan_loads(ds(d))[0]
    assert len(g) == 1 and g[0].vehicles[0].early == ["DL-00002"] and g[0].planned_on == D0


def test_what_loads_after_the_horizon_waits_and_a_shipped_or_carried_delivery_is_not_planned_again():
    d = company([100, 100, 100], days=[0, 3, 9])                       # the default horizon is 7 days
    d["deliveries"][1]["issued_on"] = D0.isoformat()
    assert loads(ds(d)) == [["DL-00001"]]


# ---- what it costs and who carries it ----------------------------------------------------------------------------
TWO = [{"id": "CR-A", "name": "Flat", "rates": [{"lane": "L", "per_shipment": 1000}]},
       {"id": "CR-B", "name": "By weight", "rates": [{"lane": "L", "per_shipment": 400, "per_kg": 1}]}]


@pytest.mark.parametrize(("kg", "carrier", "cost"), [(500, "CR-B", 900), (900, "CR-A", 1000), (600, "CR-A", 1000)])
def test_the_cheapest_carrier_carries_it(kg, carrier, cost):
    # by weight 400 + kg; flat 1,000: by weight is cheaper below 600 kg, and a tie goes to the first carrier
    g = tm.plan_loads(ds(company([kg], carriers=TWO)))[0][0]
    assert (g.vehicles[0].carrier, g.cost) == (carrier, cost)
    assert [c.carrier for c in g.choices] == [carrier, "CR-B" if carrier == "CR-A" else "CR-A"]


def test_a_minimum_charge_and_a_blocked_carrier():
    c = [dict(TWO[0]), {**TWO[1], "rates": [{"lane": "L", "per_shipment": 400, "per_kg": 1, "min_charge": 1100}]}]
    g = tm.plan_loads(ds(company([500], carriers=c)))[0][0]
    assert (g.vehicles[0].carrier, g.cost) == ("CR-A", 1000)           # 900 by weight, but never under 1,100
    c[0]["blocked"] = True
    assert tm.plan_loads(ds(company([500], carriers=c)))[0][0].cost == 1100


def test_the_lanes_own_cost_only_where_no_carrier_has_a_rate():
    g = tm.plan_loads(ds(company([500])))[0][0]
    assert (g.vehicles[0].carrier, g.cost) == (None, 200 + 2 * 500)
    g = tm.plan_loads(ds(company([500], carriers=TWO)))[0][0]
    assert None not in [c.carrier for c in g.choices]                  # what planning assumes is no carrier


def test_a_rate_for_every_lane_of_a_mode_and_its_own_vehicle():
    c = [{"id": "CR-L", "rates": [{"mode": "truck_ftl", "per_kg": 1, "capacity_kg": 400}]},
         {"id": "CR-R", "rates": [{"mode": "rail", "per_kg": 0.1}]}]  # no rail on L
    g = tm.plan_loads(ds(company([300, 300], carriers=c)))[0][0]
    assert [c.carrier for c in g.choices] == ["CR-L"] and len(g.vehicles) == 2 and g.cost == 600


# ---- the freight order's life -------------------------------------------------------------------------------------
def test_tendered_rejected_to_the_next_carrier_whose_vehicle_takes_it_accepted():
    c = [*TWO, {"id": "CR-S", "name": "Small", "rates": [{"lane": "L", "per_shipment": 100, "capacity_kg": 400}]}]
    # CR-S's 100 is the cheapest, but its 400 kg vehicle cannot take the 500 kg delivery: the last resort
    assert tm.plan_loads(ds(company([500], carriers=c)))[0][0].choices[-1].model_dump(include={"carrier", "too_small"}) \
        == {"carrier": "CR-S", "too_small": True}
    x, rep = tm.create(ds(company([500], carriers=c)))
    assert x.freight_orders[0].carrier == "CR-B" and rep.orders == ["FO-00001"]
    x, _ = tm.tender(x, "FO-00001")
    x, rep = tm.reject(x, "FO-00001")
    f = x.freight_orders[0]
    # CR-S would be cheapest (100) but its 400 kg vehicle does not take 500 kg: the flat 1,000 of CR-A
    assert (f.carrier, f.planned_cost, f.status, f.rejected_by) == ("CR-A", 1000, "tendered", ["CR-B"])
    assert "+100.00" in rep.message
    x, _ = tm.reject(x, "FO-00001")
    f = x.freight_orders[0]
    assert (f.carrier, f.status, f.planned_cost) == (None, "planned", 200 + 2 * 500)   # no carrier left: the lane's
    with pytest.raises(TransportError, match="no carrier"):
        tm.tender(x, "FO-00001")


def test_steps_out_of_order_are_refused():
    x, _ = tm.create(ds(company([500], carriers=TWO)))
    with pytest.raises(TransportError, match="only a tendered"):
        tm.accept(x, "FO-00001")
    with pytest.raises(TransportError, match="tender it"):
        tm.ship(x, "FO-00001")
    with pytest.raises(TransportError, match="only a shipped"):
        tm.settle(x, "FO-00001", 900)
    x, _ = tm.cancel(x, "FO-00001")
    assert loads(x) == [["DL-00001"]]                                  # waiting to be loaded again
    with pytest.raises(TransportError, match="cancelled"):
        tm.cancel(x, "FO-00001")


def test_the_bill_is_shared_by_weight_and_the_difference_shown():
    d = company([600, 300], carriers=[{**TWO[0], "payment_days": 45}, TWO[1]])
    d["deliveries"][0] |= {"packages": 6, "gross_kg": 700}           # packed: 700 kg on the scale, 600 units
    x, _ = tm.create(ds(d))
    f = x.freight_orders[0].model_copy(update={"status": "shipped", "shipped_on": D0})
    x = x.model_copy(update={"freight_orders": [f]})
    assert f.planned_cost == 1000
    x, rep = tm.settle(x, "FO-00001", 1350, "B-7")
    row = tm.view(x).orders[0]
    # by weight 700 : 300 of 1,350 (by units it would be 600 : 300: 900 and 450)
    assert {ln.id: ln.cost for ln in row.lines} == {"DL-00001": 945, "DL-00002": 405}
    assert row.difference == 350 and row.pay_by == D0 + timedelta(days=45)
    assert "+350.00 against the planned INR 1,000.00" in rep.message
    c = next(c for c in tm.view(x).carriers if c.carrier == "CR-A")
    assert (c.orders, c.billed, c.to_pay) == (1, 1350, 1350)


def test_without_weights_the_bill_is_shared_by_units():
    f = tm.FreightOrder(id="FO-1", lane="L", mode="truck_ftl", ship_from="W", ship_to="C", planned_on=D0,
                        deliveries=["A", "B"], units={"A": 1, "B": 3}, planned_cost=100)
    assert [ln.cost for ln in tm._lines(f)] == [25, 75]


# ---- on Kaveri: deliveries and a stock transfer, shipped and settled ---------------------------------------------------
def kaveri() -> Dataset:
    x = Dataset.model_validate(example_dict("kitchenware_network"))
    due = to_deliver(x, x.settings.planning_start + timedelta(days=10))
    x, _ = create_deliveries(x, [{"order": t.order} for t in due if t.order in ("SO-88190", "SO-88140")])
    return x


def test_kaveri_the_transfer_goes_light_with_sahyadri_and_the_delhi_delivery_by_part_load():
    x = kaveri()
    groups, _ = tm.plan_loads(x)
    by = {g.lane: g for g in groups}
    sto = by["LN-PUNE-DEL"].vehicles[0]
    # 600 kettles of 1.3 kg: Sahyadri 24,000 + 1.2 × 780 = 24,936 against Deccan's flat 32,000
    assert (sto.carrier, sto.weight_kg, sto.cost, sto.late) == ("CR-SAHYADRI", 780, 24936, ["STO-2201"])
    north = by["LN-DEL-NORTH"].vehicles[0]
    # 500 × 4.2 + 380 × 4.9 = 3,962 kg at 3.2 a kg; 500 × 0.028 + 380 × 0.031 = 25.78 m³ of 30
    assert (north.carrier, north.weight_kg, north.cost, north.fill) == ("CR-NORTHLINE", 3962, 12678.4,
                                                                         pytest.approx(25.78 / 30, abs=1e-4))


def test_kaveri_shipping_posts_the_goods_issue_and_the_transfer_dispatch():
    x, _ = tm.create(kaveri())
    fo = {f.lane: f.id for f in x.freight_orders}
    for step in (tm.tender, tm.accept, tm.ship):
        x, rep = step(x, fo["LN-DEL-NORTH"])
    assert "left Delhi NCR DC for North trade distributors" in rep.message
    dl = next(d for d in x.deliveries if d.id == "DL-00001")
    assert dl.issued_on == x.settings.planning_start and set(rep.movements) == set(dl.movements)
    for step in (tm.tender, tm.accept, tm.ship):
        x, rep = step(x, fo["LN-PUNE-DEL"])
    out = [m for m in x.movements if m.reference == "STO-2201" and m.type.value == "transfer_out"]
    assert sum(m.qty for m in out) == 600 and out[0].location == "PLT-PUNE"
    x, rep = tm.settle(x, fo["LN-PUNE-DEL"], 25500, "SFC-88")
    assert "+564.00 against the planned INR 24,936.00; to pay by Tue 13 Oct" in rep.message
    assert not [i for i in validate(x) if i.code == "TM_MISFIT"]


def test_a_carrier_rate_for_a_lane_that_does_not_exist_is_named():
    d = company([100], carriers=[{"id": "CR-X", "rates": [{"lane": "NOPE", "per_shipment": 1}]}])
    assert [i.object_id for i in validate(ds(d)) if i.code == "TM_MISFIT"] == ["CR-X"]


def test_through_the_api():
    d = company([600, 300], carriers=TWO)
    r = client.post("/api/transport", json=d)
    assert r.status_code == 200 and r.json()["groups"][0]["cost"] == 1000
    r = client.post("/api/transport/act", json={"dataset": d, "action": "plan"})
    assert r.status_code == 200 and r.json()["report"]["orders"] == ["FO-00001"]
    r = client.post("/api/transport/act", json={"dataset": d, "action": "accept", "order": "FO-00001"})
    assert r.status_code == 409 and "no freight order FO-00001" in r.json()["detail"]


def test_a_rejected_load_goes_to_the_next_carrier_even_where_the_lane_is_assumed_cheaper():
    x, _ = tm.create(ds(company([500], carriers=TWO, cost_per_shipment=50, cost_per_kg=0)))
    x, _ = tm.tender(x, "FO-00001")
    x, _ = tm.reject(x, "FO-00001")                                     # CR-B (900) turns it down
    f = x.freight_orders[0]
    assert (f.carrier, f.planned_cost) == ("CR-A", 1000)               # not the lane's assumed 50: no one carries that


# ---- collections: purchases whose carriage the buyer pays (Enterprise 8.3, CONFORMANCE §7, T19) ----------------
def _collect(terms: str = "FCA Pune", lines: tuple = ((400, 4), (300, 5)), sent: bool = True, **mode) -> dict:
    """W buys X from S on terms ``terms``; lane LS from S to W takes 2 days in a 1,000 kg truck (500 a vehicle, 1 a
    kilogram). Each of ``lines`` is a purchase order line of (kg, days after the start it is due)."""
    d = company([100])
    d["vendors"] = [{"supplier": "S", "incoterms": terms}]
    d["lanes"].append({"id": "LS", "origin": "S", "destination": "W", "modes": [
        {"mode": "truck_ftl", "transit_days": 2, "vehicle_capacity_kg": 1000, "cost_per_shipment": 500,
         "cost_per_kg": 1, **mode}]})
    d["purchase_orders"] = [{"id": "PO-1", "supplier": "S", "location": "W", "order_date": D0.isoformat(),
                             **({"sent_on": D0.isoformat()} if sent else {})}]
    d["receipts"] = [{"id": f"PO-1-{10 * (i + 1)}", "kind": "purchase", "location": "W", "product": "X", "qty": q,
                      "due_date": (D0 + timedelta(days=due)).isoformat(), "source": "B-X", "po": "PO-1", "price": 1}
                     for i, (q, due) in enumerate(lines)]
    return d


def collections(x: Dataset) -> list[tuple[str, list[str], str, float]]:
    return [(g.lane, v.purchases, v.planned_on.isoformat(), v.cost) for g in tm.plan_loads(x)[0] for v in g.vehicles
            if v.purchases]


def test_a_purchase_the_buyer_collects_is_loaded_at_the_supplier_its_transit_before_it_is_due():
    d = _collect()
    d["transport"] = {"window_days": 1}
    # due on days 4 and 5, 2 days in transit: they load on days 2 and 3, within a day: one truck of 700 kg,
    # 500 + 700 × 1 = 1,200 (the later one sent a day early)
    assert collections(ds(d)) == [("LS", ["PO-1-10", "PO-1-20"], "2026-03-04", 1200.0)]
    assert collections(ds(_collect())) == [("LS", ["PO-1-10"], "2026-03-04", 900.0),
                                           ("LS", ["PO-1-20"], "2026-03-05", 800.0)]


@pytest.mark.parametrize("terms", ["DAP Pune", "CIF Nhava Sheva", "", "fob shenzhen"])
def test_only_terms_that_leave_the_carriage_to_the_buyer_are_collected(terms):
    got = collections(ds(_collect(terms)))
    assert bool(got) == (terms.split()[:1] == ["fob"])          # FOB in any case; DAP and CIF are the seller's


def test_an_unsent_order_a_received_line_or_a_carried_one_is_not_planned_and_no_lane_is_named():
    assert collections(ds(_collect(sent=False))) == []
    late = collections(ds(_collect(lines=((400, 1),))))       # due tomorrow, 2 days in transit: loads today, late
    assert late == [("LS", ["PO-1-10"], "2026-03-02", 900.0)]
    assert [v.late for g in tm.plan_loads(ds(_collect(lines=((400, 1),))))[0] for v in g.vehicles if v.purchases] == [
        ["PO-1-10"]]
    assert collections(ds(_collect(lines=((400, 12),)))) == []   # loads on day 10, past the 7-day horizon
    d = _collect(lines=((400, 4),))
    d["receipts"][0].update(confirmed_date=(D0 + timedelta(days=6)).isoformat())
    assert [x[2] for x in collections(ds(d))] == ["2026-03-06"]   # the supplier confirmed day 6: loads on day 4
    d = _collect(lines=((400, 4),))
    d["receipts"][0].update(confirmed_qty=150)                # the supplier confirmed 150 of 400: 150 come
    assert [(v.weight_kg, v.cost) for g in tm.plan_loads(ds(d))[0] for v in g.vehicles if v.purchases] == [(150, 650)]
    d["receipts"][0].update(confirmed_qty=0.0)                # confirmed none: nothing to collect
    assert collections(ds(d)) == []
    x, rep = tm.create(ds(_collect(lines=((400, 4),))))
    (fo,) = [f for f in x.freight_orders if f.purchases]
    assert (fo.ship_from, fo.ship_to, fo.purchases, fo.planned_cost) == ("S", "W", ["PO-1-10"], 900)
    assert collections(x) == []                               # on a freight order now
    d = _collect()
    d["lanes"] = [ln for ln in d["lanes"] if ln["id"] != "LS"]
    _, out = tm.plan_loads(ds(d))
    assert [(u.kind, u.id) for u in out] == [("purchase", "PO-1-10"), ("purchase", "PO-1-20")]
    assert "no lane goes from there to" in out[0].why


def test_a_collection_ships_without_a_posting_and_its_freight_bill_is_the_buyers():
    from scp.accounting import journal
    x, _ = tm.create(ds(_collect(lines=((400, 4),))))
    fid = next(f.id for f in x.freight_orders if f.purchases)
    x2, rep = tm.ship(x, fid)
    assert rep.movements == [] and "PO-1-10 (collected)" in rep.message
    assert x2.receipts == x.receipts and x2.movements == x.movements     # received later, against the order
    x3, _ = tm.settle(x2, fid, 950, "LR-77")
    (row,) = [r for r in tm.view(x3).orders if r.order.id == fid]
    assert row.difference == 50 and [(ln.kind, ln.id, ln.cost) for ln in row.lines] == [("purchase", "PO-1-10", 950)]
    d = x3.model_dump(mode="json")                        # W belongs to company E1: the bill is in E1's books
    d["entities"] = [{"id": "E1", "name": "West"}]
    next(lo for lo in d["locations"] if lo["id"] == "W")["entity"] = "E1"
    vs, _ = journal(ds(d), D0 + timedelta(days=30))
    (v,) = [v for v in vs if v.document == fid]
    assert v.company == "E1" and v.debit == v.credit == 950
    from scp.accounting import view as books
    owed = [c for c in books(ds(d), period_end=D0 + timedelta(days=30)).checks if "suppliers" in c.what.lower()]
    assert owed and all(c.ok for c in owed)               # what E1 owes includes the carrier's bill
