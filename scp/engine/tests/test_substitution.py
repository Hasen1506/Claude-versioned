"""Product substitution (Enterprise 8.3; docs/CONFORMANCE.md §5, S11): an order short of one product is offered what a
substitute can ship on time, and taking the offer moves that part to a line of the substitute at the ordered price.
Hand-worked against the ATP look-ahead: free on a day is the least of the cumulative balance from that day on."""
from __future__ import annotations

from datetime import date

import pytest

from scp.model import DemandRecord
from scp.promise import check_order, run_bop, run_promise
from scp.promise.orders import OrderError, substitute

from .factory import ds, lp
from .test_promise import net, so


def shop(**sub) -> dict:
    """D holds 30 A, 50 A2 and 20 A3. C1 wants 60 A shipped on Fri 9 Jan (delivered Sat 10); C2 has 40 A2 shipped on
    Sun 11 Jan. A may ship as A2 (first) or A3."""
    d = net()
    d["products"] += [{"id": "A2", "type": "FG", "price": 120}, {"id": "A3", "type": "FG", "price": 90}]
    d["products"][0]["price"] = 100
    lp(d, "D", "A")["on_hand"] = 30
    lp(d, "D", "A2")["on_hand"] = 50
    lp(d, "D", "A3")["on_hand"] = 20
    d["purchasing_sources"] += [{"id": f"PIR-{p}", "supplier": "S", "product": p, "location": "P", "price": 50,
                                 "lead_time_days": 30} for p in ("A2", "A3")]
    d["demand"] = [so("C1", 60, "2026-01-10", "SO1"),
                   {**so("C2", 40, "2026-01-12", "SO2"), "product": "A2"}]
    d["substitutions"] = [{"product": "A", "substitute": "A2", "note": "same motor", **sub},
                          {"product": "A", "substitute": "A3"}]
    return d


def offers(o) -> list[tuple[str, float, list[str]]]:
    return [(x.product, x.qty, x.ship_from) for x in o.substitutes]


def test_a_short_order_is_offered_what_each_substitute_has_free_on_the_date_asked():
    r = run_promise(ds(shop()))
    so1, so2 = r.orders
    assert so1.on_time == 30 and so1.unconfirmed == 30
    # A2: 50 in stock, SO2's 40 ship on day 6, so free on day 4 = min(50, 50 − 40) = 10. A3 takes the next 20 of the 30.
    assert offers(so1) == [("A2", 10, ["D"]), ("A3", 20, ["D"])]
    x = so1.substitutes[0]
    assert x.price == 100 and x.own_price == 120 and x.note == "same motor"   # the ordered price; its own is 120
    assert so2.substitutes == []                                              # on time: nothing to offer
    # an offer promises nothing: the supply picture after the run still has SO2's 40 as the only A2 outflow
    a2 = next(n for n in r.nodes if (n.location, n.product) == ("D", "A2"))
    assert sum(a2.promised) == 40 and a2.available[4] == 10
    assert offers(run_bop(ds(shop())).orders[0]) == offers(so1)


def test_offers_respect_the_customer_dates_allocations_and_complete_delivery():
    assert offers(run_promise(ds(shop(customers=["C2"]))).orders[0]) == [("A3", 20, ["D"])]
    assert offers(run_promise(ds(shop(valid_to="2026-01-09"))).orders[0]) == [("A3", 20, ["D"])]
    assert offers(run_promise(ds(shop(valid_from="2026-01-10"))).orders[0])[0][0] == "A2"   # its first day counts
    d = shop()
    d["allocations"] = [{"id": "AL", "product": "A2", "customers": ["C1"], "start": "2026-01-05", "end": "2026-01-12",
                         "qty": 4}]
    assert offers(run_promise(ds(d)).orders[0]) == [("A2", 4, ["D"]), ("A3", 20, ["D"])]
    d = shop()
    d["demand"][0]["complete_delivery"] = True            # 60 in one go: neither 10 nor 20 is the whole short part
    assert run_promise(ds(d)).orders[0].substitutes == []
    lp(d, "D", "A3")["on_hand"] = 60                     # A3 can take all 60 (nothing of A is on time either)
    assert offers(run_promise(ds(d)).orders[0]) == [("A3", 60, ["D"])]


def test_an_order_check_is_offered_substitutes_too():
    r = check_order(ds(shop()), DemandRecord(location="C1", product="A", date=date(2026, 1, 10), qty=5))
    # SO1 already took A's 30: the 5 checked are short; A2 has 10 free, so it takes all 5 and A3 is not needed
    assert r.checked.on_time == 0 and offers(r.checked) == [("A2", 5, ["D"])]
    assert all(o.substitutes == [] for o in r.orders)     # a check offers for the order being checked only


def test_taking_an_offer_moves_the_short_part_to_a_line_of_the_substitute_at_the_ordered_price():
    x, rep = substitute(ds(shop()), "SO1", "A2", 10)
    so1 = next(d for d in x.demand if d.id == "SO1")
    new = next(d for d in x.demand if d.substitute_for == "SO1")
    assert so1.qty == 50 and so1.product == "A"
    assert (new.id, new.product, new.qty, new.price, new.date) == ("SO-00001", "A2", 10, 100, date(2026, 1, 10))
    assert [(c.order, c.ship_from, c.ship_date, c.date, c.qty) for c in x.confirmations if c.order == "SO-00001"] == [
        ("SO-00001", "D", date(2026, 1, 9), date(2026, 1, 10), 10)]
    assert rep.order == "SO-00001" and "ship in place of" in rep.message and "SO1 keeps 50" in rep.message
    r = run_promise(x)
    so1p = next(o for o in r.orders if o.order == "SO1")
    assert so1p.on_time == 30 and offers(so1p) == [("A3", 20, ["D"])]     # A2's 10 are now the new line's
    assert next(o for o in r.orders if o.order == "SO-00001").status == "on_time"


def test_moving_all_that_is_open_closes_the_order_and_a_header_line_stays_on_its_order():
    d = shop()
    lp(d, "D", "A")["on_hand"] = 0
    d["demand"][0]["qty"] = 8
    x, rep = substitute(ds(d), "SO1", "A2")
    assert not [r for r in x.demand if r.id == "SO1"]
    (c,) = [c for c in x.closed_orders if c.id == "SO1"]
    assert c.cancelled and "SO1 is closed (shipped as A2 instead)" in rep.message
    d = shop()
    d["sales_orders"] = [{"id": "SO-00007", "customer": "C1", "order_date": "2026-01-05"}]
    d["demand"][0].update(id="SO-00007/10", order="SO-00007")
    x, _ = substitute(ds(d), "SO-00007/10", "A3", 20)
    new = next(r for r in x.demand if r.substitute_for == "SO-00007/10")
    assert (new.id, new.order) == ("SO-00007/20", "SO-00007")


def test_only_a_substitute_that_applies_and_no_more_than_is_open():
    with pytest.raises(OrderError, match="is not a substitute for"):
        substitute(ds(shop()), "SO1", "B", 5)
    with pytest.raises(OrderError, match="is not a substitute for"):
        substitute(ds(shop(customers=["C2"])), "SO1", "A2", 5)
    with pytest.raises(OrderError, match="has 60 open"):
        substitute(ds(shop()), "SO1", "A2", 61)


def test_only_the_short_part_is_offered_and_each_offer_is_held_against_the_next_order():
    d = shop()
    lp(d, "D", "A3")["on_hand"] = 50
    assert offers(run_promise(ds(d)).orders[0]) == [("A2", 10, ["D"]), ("A3", 20, ["D"])]    # 30 short, not 60
    d = shop()
    d["demand"].append(so("C1", 5, "2026-01-10", "SO3"))     # after SO1: A is gone, and SO1's offers come first
    r = run_promise(ds(d))
    assert offers(r.orders[2]) == []                          # A2's 10 and A3's 20 are both offered to SO1
    # SO0 takes A's 30 first; SO1 wants its 60 in one go, so neither A2's 10 nor A3's 20 is offered to it, and both
    # go back: SO3 is offered A2
    d["demand"][0]["complete_delivery"] = True
    d["demand"].insert(0, so("C2", 30, "2026-01-10", "SO0"))
    r = run_promise(ds(d))
    assert r.orders[1].substitutes == [] and offers(r.orders[3]) == [("A2", 5, ["D"])]
    d["allocations"] = [{"id": "AL", "product": "A2", "customers": ["C1"], "start": "2026-01-05", "end": "2026-01-12",
                         "qty": 4}]                           # what SO1 counted of the allocation goes back too
    assert offers(run_promise(ds(d)).orders[3]) == [("A2", 4, ["D"]), ("A3", 1, ["D"])]


def test_alternative_places_add_up_and_beyond_the_lead_time_is_not_an_offer():
    d = shop()
    d["promising"]["alternative_locations"] = True
    lp(d, "D2", "A2")["on_hand"] = 5                          # D2 ships to C1 in 3 days: on Wed 7 Jan
    assert offers(run_promise(ds(d)).orders[0]) == [("A2", 15, ["D", "D2"]), ("A3", 15, ["D"])]
    d = shop()
    d["promising"]["confirm_beyond_rlt"] = True
    d["purchasing_sources"][-2]["lead_time_days"] = 1        # A2 at D: bought in 1 day at P, 2 days to D
    o = run_promise(ds(d)).orders[0]
    assert o.unconfirmed == 0 and o.on_time == 30             # A's lead time (7 days) is beyond the date asked
    assert offers(o) == [("A3", 20, ["D"])]                   # A2 can be got by then, but that is no stock to offer
