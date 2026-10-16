"""Transport (Enterprise 6.3, S/4 guide §14, a small TM): what is to be loaded, vehicles built from it by weight and
volume, the carrier that carries them cheapest, and freight orders tendered, shipped and settled.

What is to be loaded is every open delivery (not shipped, not on a freight order) and every stock transfer with
something left to ship, loading from the planning start up to ``transport.horizon_days`` ahead. A delivery loads on
its planned goods issue, a transfer its lane's transit time before it is due; what should have left already loads on
the first day, and is named late. Each goes on the lane from where it leaves to where it goes (the lane with the
highest priority when there are several).

On each lane, what loads within ``transport.window_days`` of the first shares a vehicle (the later ones sent early).
Vehicles are filled first fit, heaviest first, up to the vehicle's kilograms and cubic metres; something bigger than a
vehicle goes alone and is named. Every carrier with a rate for the lane (or for every lane of its mode) is costed on
its own vehicles; the cheapest is proposed. A vehicle costs its rate per shipment,
kilogram and cubic metre, never less than its minimum.

Where no carrier has a rate for a lane, the vehicles are costed at what planning assumes the lane costs, with no
carrier: shipped in the company's own vehicle or booked on the spot. A freight order is one vehicle. Tendered to its carrier, it is accepted or rejected; a rejection tenders it to the
next cheapest carrier whose vehicle takes the load. Shipped, it posts the goods issue of each delivery and the
dispatch of each transfer it carries. Settled with the carrier's bill, what the bill says is shared over what it
carried by weight (by units where nothing has a weight), and the difference from the planned cost is shown.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..actuals.post import PostingError, _ordered, _posted, origin
from ..actuals.post import ship as ship_transfer
from ..model import Dataset, FreightOrder, ReceiptKind, TransportLane
from ..model.common import Out, TransportMode
from ..sales import SalesError
from ..sales import issue as goods_issue

EPS = 1e-9
ACTIVE = {"planned", "tendered", "accepted"}


class TransportError(ValueError):
    """A transport step the data does not allow; the message says why in plain words."""


# ------------------------------------------------------------------------------------------------ words
def _name(ds: Dataset, lid: str) -> str:
    lo = ds.location_by_id.get(lid)
    return (lo.name or lid) if lo else lid


def _carrier(ds: Dataset, cid: str | None) -> str:
    if cid is None:
        return "the lane's own cost"
    k = ds.carrier_by_id.get(cid)
    return (k.name or cid) if k else cid


def _money(ds: Dataset, v: float) -> str:
    return f"{ds.settings.currency} {v:,.2f}"


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _kg(v: float) -> str:
    return f"{v:,.0f} kg" if v >= 100 else f"{v:,.1f} kg"


# ------------------------------------------------------------------------------------------------ what is to load
@dataclass
class Item:
    kind: str                       # delivery or transfer
    id: str
    lane: str
    ship_from: str
    ship_to: str
    day: date                       # when it should load
    kg: float
    m3: float
    units: float
    late: bool = False
    unweighed: list[str] = field(default_factory=list)


class Unplanned(Out):
    kind: str
    id: str
    why: str


def _lane(ds: Dataset, frm: str, to: str) -> TransportLane | None:
    ok = [ln for ln in ds.lanes if ln.origin == frm and ln.destination == to]
    return min(ok, key=lambda ln: (ln.priority, ln.id)) if ok else None


def _dims(ds: Dataset, lines: list[tuple[str, float]]) -> tuple[float, float, float, list[str]]:
    kg = m3 = units = 0.0
    unweighed = []
    for prod, q in lines:
        p = ds.product_by_id.get(prod)
        units += q
        if p is None or p.weight_kg is None:
            unweighed.append(prod)
        else:
            kg += q * p.weight_kg
        if p is not None and p.volume_m3 is not None:
            m3 += q * p.volume_m3
    return kg, m3, units, unweighed


def _carried(ds: Dataset) -> set[tuple[str, str]]:
    return {(k, x) for f in ds.freight_orders if f.status != "cancelled"
            for k, xs in (("delivery", f.deliveries), ("transfer", f.transfers)) for x in xs}


def to_load(ds: Dataset, on: date | None = None, days: int | None = None) -> tuple[list[Item], list[Unplanned]]:
    """Every open delivery and stock transfer not on a freight order, loading by ``on`` + ``days``."""
    day = on or ds.settings.planning_start
    last = day + timedelta(days=ds.transport.horizon_days if days is None else days)
    taken = _carried(ds)
    items: list[Item] = []
    out: list[Unplanned] = []
    for d in ds.deliveries:
        if d.issued_on is not None or ("delivery", d.id) in taken or d.planned_on > last:
            continue
        ln = _lane(ds, d.ship_from, d.customer)
        if ln is None:
            out.append(Unplanned(kind="delivery", id=d.id, why=f"no lane from {_name(ds, d.ship_from)} to "
                                 f"{_name(ds, d.customer)}"))
            continue
        kg, m3, units, unw = _dims(ds, [(x.product, x.picked if x.picked is not None else x.qty) for x in d.lines])
        if d.gross_kg:
            kg, unw = d.gross_kg, []                      # packed: the weight on the scale
        items.append(Item("delivery", d.id, ln.id, d.ship_from, d.customer, max(day, d.planned_on), kg, m3, units,
                          d.planned_on < day, unw))
    for rc in ds.receipts:
        if rc.kind is not ReceiptKind.TRANSFER or ("transfer", rc.id) in taken:
            continue
        frm = origin(ds, rc)
        if not frm:
            continue
        _, shipped, _ = _posted(ds, rc.id)
        left = _ordered(rc) - shipped[(frm, rc.product)]
        if left <= EPS:
            continue
        ln = ds.lane_by_id.get(rc.source or "") or _lane(ds, frm, rc.location)
        if ln is None or ln.origin != frm:
            out.append(Unplanned(kind="transfer", id=rc.id, why=f"no lane from {_name(ds, frm)} to "
                                 f"{_name(ds, rc.location)}"))
            continue
        load = rc.due_date - timedelta(days=math.ceil(ln.planning_mode.transit_days))
        if load > last:
            continue
        kg, m3, units, unw = _dims(ds, [(rc.product, left)])
        items.append(Item("transfer", rc.id, ln.id, frm, rc.location, max(day, load), kg, m3, units, load < day, unw))
    return items, out


# ------------------------------------------------------------------------------------------------ vehicles and cost
@dataclass
class Option:
    carrier: str | None             # None: the lane's own cost
    mode: TransportMode
    per_shipment: float
    per_kg: float
    per_m3: float
    per_unit: float
    min_charge: float
    cap_kg: float | None
    cap_m3: float | None

    def cost(self, kg: float, m3: float, units: float) -> float:
        return round(max(self.min_charge, self.per_shipment + self.per_kg * kg + self.per_m3 * m3
                         + self.per_unit * units), 2)

    def fits(self, kg: float, m3: float) -> bool:
        return (self.cap_kg is None or kg <= self.cap_kg + EPS) and (self.cap_m3 is None or m3 <= self.cap_m3 + EPS)


def options(ds: Dataset, lane: TransportLane, skip: set[str] = frozenset(), own: bool = False) -> list[Option]:
    """Every way the lane can be carried: each carrier's rate for it; the lane's own cost where no carrier has one
    (or when ``own``)."""
    modes = {m.mode: m for m in lane.modes}
    out = []
    for k in sorted(ds.carriers, key=lambda k: k.id):
        if k.blocked or k.id in skip:
            continue
        for r in k.rates:
            if (r.lane and r.lane != lane.id) or (not r.lane and r.mode not in modes):
                continue
            m = modes.get(r.mode, lane.planning_mode)
            out.append(Option(k.id, r.mode, r.per_shipment, r.per_kg, r.per_m3, 0.0, r.min_charge,
                              r.capacity_kg or m.vehicle_capacity_kg, r.capacity_m3 or m.vehicle_capacity_m3))
    if not out or own:
        m = lane.planning_mode                  # no carrier's rate: what planning assumes the lane costs
        out.append(Option(None, m.mode, m.cost_per_shipment, m.cost_per_kg, m.cost_per_m3, m.cost_per_unit, 0.0,
                          m.vehicle_capacity_kg, m.vehicle_capacity_m3))
    return out


def pack(items: list[Item], o: Option) -> list[list[Item]]:
    """First fit, heaviest first (then bulkiest), by the vehicle's kilograms and cubic metres."""
    vehicles: list[list[Item]] = []
    load: list[tuple[float, float]] = []
    for it in sorted(items, key=lambda x: (-x.kg, -x.m3, x.id)):
        for i, (kg, m3) in enumerate(load):
            if o.fits(kg + it.kg, m3 + it.m3):
                vehicles[i].append(it)
                load[i] = (kg + it.kg, m3 + it.m3)
                break
        else:
            vehicles.append([it])
            load.append((it.kg, it.m3))
    return vehicles


class Vehicle(Out):
    lane: str
    ship_from: str
    ship_to: str
    mode: TransportMode
    carrier: str | None
    planned_on: date
    deliveries: list[str]
    transfers: list[str]
    weight_kg: float
    volume_m3: float
    capacity_kg: float | None
    capacity_m3: float | None
    fill: float | None              # the fuller of weight and volume
    cost: float
    over: bool                      # bigger than one vehicle on its own
    early: list[str]                # sent before they are due, to share the vehicle
    late: list[str]                 # should have left already
    unweighed: list[str]            # products without a weight
    weights: dict[str, float]
    units: dict[str, float]


class Choice(Out):
    carrier: str | None
    name: str
    mode: TransportMode
    vehicles: int
    cost: float
    too_small: bool                 # its vehicle cannot take something on its own


class LoadGroup(Out):
    lane: str
    ship_from: str
    ship_to: str
    planned_on: date
    vehicles: list[Vehicle]
    choices: list[Choice]           # every way of carrying it, cheapest first
    cost: float


def _vehicles(ln: TransportLane, o: Option, items: list[Item], on: date) -> list[Vehicle]:
    out = []
    for v in pack(items, o):
        kg, m3, units = sum(x.kg for x in v), sum(x.m3 for x in v), sum(x.units for x in v)
        fills = [a / c for a, c in ((kg, o.cap_kg), (m3, o.cap_m3)) if c]
        out.append(Vehicle(lane=ln.id, ship_from=ln.origin, ship_to=ln.destination, mode=o.mode, carrier=o.carrier,
                           planned_on=on, deliveries=sorted(x.id for x in v if x.kind == "delivery"),
                           transfers=sorted(x.id for x in v if x.kind == "transfer"), weight_kg=round(kg, 3),
                           volume_m3=round(m3, 4), capacity_kg=o.cap_kg, capacity_m3=o.cap_m3,
                           fill=round(max(fills), 4) if fills else None, cost=o.cost(kg, m3, units),
                           over=len(v) == 1 and not o.fits(kg, m3),
                           early=sorted(x.id for x in v if x.day > on), late=sorted(x.id for x in v if x.late),
                           unweighed=sorted({p for x in v for p in x.unweighed}),
                           weights={x.id: round(x.kg, 3) for x in v}, units={x.id: round(x.units, 6) for x in v}))
    return out


def plan_loads(ds: Dataset, on: date | None = None, lanes: list[str] | None = None) -> tuple[list[LoadGroup], list[Unplanned]]:
    """What is to load, in vehicles, by lane and loading day, each group carried the cheapest way."""
    day = on or ds.settings.planning_start
    items, out = to_load(ds, day)
    by_lane: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        if lanes is None or it.lane in lanes:
            by_lane[it.lane].append(it)
    groups = []
    win = ds.transport.window_days
    for lid in sorted(by_lane):
        ln = ds.lane_by_id[lid]
        left = sorted(by_lane[lid], key=lambda x: (x.day, x.id))
        while left:
            first = left[0].day
            batch = [x for x in left if x.day <= first + timedelta(days=win)]
            left = [x for x in left if x.day > first + timedelta(days=win)]
            costed = []
            for o in options(ds, ln):
                vs = _vehicles(ln, o, batch, first)
                # a vehicle too small for something it must carry is the last resort, whatever it costs
                costed.append((any(v.over for v in vs), round(sum(v.cost for v in vs), 2), o.carrier is None,
                               o.carrier or "", o, vs))
            costed.sort(key=lambda c: c[:4])
            best = costed[0]
            groups.append(LoadGroup(lane=lid, ship_from=ln.origin, ship_to=ln.destination, planned_on=first,
                                    vehicles=best[5], cost=best[1],
                                    choices=[Choice(carrier=c[4].carrier, name=_carrier(ds, c[4].carrier),
                                                    mode=c[4].mode, vehicles=len(c[5]), cost=c[1], too_small=c[0])
                                             for c in costed]))
    return groups, out


# ------------------------------------------------------------------------------------------------ the view
class FreightLine(Out):
    kind: str
    id: str
    weight_kg: float
    share: float                    # of the freight order's cost
    cost: float                     # planned, or billed once settled


class FreightRow(Out):
    order: FreightOrder
    lines: list[FreightLine]
    difference: float | None        # billed − planned, once settled
    pay_by: date | None


class CarrierRow(Out):
    carrier: str
    name: str
    orders: int
    planned: float
    billed: float
    to_pay: float                   # settled bills not yet due or overdue: the freight we owe
    rejected: int


class TransportView(Out):
    as_of: date
    currency: str
    groups: list[LoadGroup]
    unplanned: list[Unplanned]
    orders: list[FreightRow]
    carriers: list[CarrierRow]
    planned_cost: float             # open freight orders
    billed: float
    difference: float
    notes: list[str] = []


def _lines(f: FreightOrder) -> list[FreightLine]:
    """The freight order's cost (as billed once settled) shared by weight, by units where nothing has a weight."""
    ids = [("delivery", x) for x in f.deliveries] + [("transfer", x) for x in f.transfers]
    kg = {x: f.weights.get(x, 0.0) for _, x in ids}
    un = {x: f.units.get(x, 0.0) for _, x in ids}
    tk, tu = sum(kg.values()), sum(un.values())
    cost = f.billed if f.billed is not None else f.planned_cost
    out = []
    for kind, x in ids:
        share = kg[x] / tk if tk > EPS else un[x] / tu if tu > EPS else 1 / len(ids)
        out.append(FreightLine(kind=kind, id=x, weight_kg=round(kg[x], 3), share=round(share, 4),
                               cost=round(cost * share, 2)))
    return out


def view(ds: Dataset, on: date | None = None) -> TransportView:
    day = on or ds.settings.planning_start
    groups, out = plan_loads(ds, day)
    rows = []
    per: dict[str, CarrierRow] = {}
    for f in sorted(ds.freight_orders, key=lambda f: f.id, reverse=True):
        k = ds.carrier_by_id.get(f.carrier or "")
        pay_by = f.settled_on + timedelta(days=k.payment_days) if f.settled_on and k else None
        rows.append(FreightRow(order=f, lines=_lines(f), pay_by=pay_by,
                               difference=round(f.billed - f.planned_cost, 2) if f.billed is not None else None))
        for cid in {*([f.carrier] if f.carrier else []), *f.rejected_by}:
            c = per.setdefault(cid, CarrierRow(carrier=cid, name=_carrier(ds, cid), orders=0, planned=0, billed=0,
                                               to_pay=0, rejected=0))
            if cid in f.rejected_by:
                c.rejected += 1
            if cid == f.carrier and f.status != "cancelled":
                c.orders += 1
                c.planned = round(c.planned + f.planned_cost, 2)
                c.billed = round(c.billed + (f.billed or 0.0), 2)
                if f.billed is not None:
                    c.to_pay = round(c.to_pay + f.billed, 2)
    open_ = [f for f in ds.freight_orders if f.status in ACTIVE | {"shipped"}]
    settled = [f for f in ds.freight_orders if f.billed is not None]
    notes = []
    low = [v for g in groups for v in g.vehicles if v.fill is not None and v.fill < ds.transport.low_fill]
    if low:
        notes.append(f"{len(low)} proposed vehicle{'s are' if len(low) > 1 else ' is'} filled less than "
                     f"{ds.transport.low_fill:.0%}: a longer window (Transport settings) lets later loads share one.")
    unw = sorted({p for g in groups for v in g.vehicles for p in v.unweighed})
    if unw:
        notes.append(f"{', '.join(unw[:6])} {'have' if len(unw) > 1 else 'has'} no weight: the vehicles count "
                     "them as weighing nothing. Give them a weight on the product.")
    return TransportView(as_of=day, currency=ds.settings.currency, groups=groups, unplanned=out, orders=rows,
                         carriers=sorted(per.values(), key=lambda c: c.name), notes=notes,
                         planned_cost=round(sum(f.planned_cost for f in open_), 2),
                         billed=round(sum(f.billed or 0.0 for f in settled), 2),
                         difference=round(sum((f.billed or 0.0) - f.planned_cost for f in settled), 2))


# ------------------------------------------------------------------------------------------------ steps
class TransportReport(Out):
    message: str
    orders: list[str] = []
    documents: list[str] = []       # deliveries shipped
    movements: list[str] = []


def _fill(f: FreightOrder) -> float | None:
    """The fuller of weight and volume."""
    fills = [a / c for a, c in ((f.weight_kg, f.capacity_kg), (f.volume_m3, f.capacity_m3)) if c]
    return max(fills) if fills else None


def _next_id(ds: Dataset):
    n = max((int(f.id[3:]) for f in ds.freight_orders if f.id.startswith("FO-") and f.id[3:].isdigit()), default=0)
    while True:
        n += 1
        yield f"FO-{n:05d}"


def _fo(ds: Dataset, fid: str) -> FreightOrder:
    f = next((f for f in ds.freight_orders if f.id == fid), None)
    if f is None:
        raise TransportError(f"there is no freight order {fid}")
    return f


def _put(ds: Dataset, f: FreightOrder) -> Dataset:
    return ds.model_copy(update={"freight_orders": [f if x.id == f.id else x for x in ds.freight_orders]})


def create(ds: Dataset, on: date | None = None, lanes: list[str] | None = None) -> tuple[Dataset, TransportReport]:
    """A freight order for each vehicle :func:`plan_loads` proposes, with the cheapest carrier."""
    day = on or ds.settings.planning_start
    groups, _ = plan_loads(ds, day, lanes)
    if not groups:
        raise TransportError("nothing is waiting to be loaded" + (" on these lanes" if lanes else ""))
    ids = _next_id(ds)
    made = []
    for g in groups:
        for v in g.vehicles:
            made.append(FreightOrder(id=next(ids), lane=v.lane, mode=v.mode, carrier=v.carrier, ship_from=v.ship_from,
                                     ship_to=v.ship_to, planned_on=v.planned_on, deliveries=v.deliveries,
                                     transfers=v.transfers, weight_kg=v.weight_kg, volume_m3=v.volume_m3,
                                     weights=v.weights, units=v.units,
                                     capacity_kg=v.capacity_kg, capacity_m3=v.capacity_m3, planned_cost=v.cost,
                                     note="bigger than one vehicle: split it" if v.over else ""))
    cost = sum(f.planned_cost for f in made)
    lines = "; ".join(f"{f.id} {_name(ds, f.ship_from)} to {_name(ds, f.ship_to)}, {_carrier(ds, f.carrier)}, "
                      f"{_kg(f.weight_kg)}" + (f" ({_fill(f):.0%} full)" if _fill(f) is not None else "")
                      for f in made[:6])
    return (ds.model_copy(update={"freight_orders": [*ds.freight_orders, *made]}),
            TransportReport(orders=[f.id for f in made],
                            message=f"{len(made)} freight order{'s' if len(made) > 1 else ''}, {_money(ds, cost)}: "
                                    f"{lines}" + ("; …" if len(made) > 6 else "") + "."))


def tender(ds: Dataset, fid: str, on: date | None = None) -> tuple[Dataset, TransportReport]:
    f = _fo(ds, fid)
    if f.status != "planned":
        raise TransportError(f"{fid} is {f.status}: only a planned freight order is tendered")
    if f.carrier is None:
        raise TransportError(f"{fid} has no carrier: give the lane a carrier's rate, or ship it at the lane's own cost")
    day = on or ds.settings.planning_start
    return (_put(ds, f.model_copy(update={"status": "tendered", "tendered_on": day})),
            TransportReport(orders=[fid], message=f"{fid} tendered to {_carrier(ds, f.carrier)} for "
                                                  f"{_money(ds, f.planned_cost)}."))


def accept(ds: Dataset, fid: str, on: date | None = None) -> tuple[Dataset, TransportReport]:
    f = _fo(ds, fid)
    if f.status != "tendered":
        raise TransportError(f"{fid} is {f.status}: only a tendered freight order is accepted")
    day = on or ds.settings.planning_start
    return (_put(ds, f.model_copy(update={"status": "accepted", "accepted_on": day})),
            TransportReport(orders=[fid], message=f"{_carrier(ds, f.carrier)} accepted {fid}: it loads on "
                                                  f"{_day(f.planned_on)}."))


def reject(ds: Dataset, fid: str, on: date | None = None) -> tuple[Dataset, TransportReport]:
    """The carrier turned it down: tendered to the next cheapest carrier whose vehicle takes the load."""
    f = _fo(ds, fid)
    if f.status != "tendered" or f.carrier is None:
        raise TransportError(f"{fid} is {f.status}: only a tendered freight order is rejected")
    day = on or ds.settings.planning_start
    ln = ds.lane_by_id.get(f.lane)
    if ln is None:
        raise TransportError(f"lane {f.lane} no longer exists: cancel {fid}")
    gone = [*f.rejected_by, f.carrier]
    units = sum(f.units.values())
    ok = [o for o in options(ds, ln, set(gone), own=True) if o.fits(f.weight_kg, f.volume_m3)]
    ok.sort(key=lambda o: (o.carrier is None, o.cost(f.weight_kg, f.volume_m3, units), o.carrier or ""))
    nxt = ok[0] if ok else None
    was = _carrier(ds, f.carrier)
    if nxt is None or nxt.carrier is None:
        cost = nxt.cost(f.weight_kg, f.volume_m3, units) if nxt else f.planned_cost
        new = f.model_copy(update={"status": "planned", "carrier": None, "rejected_by": gone, "tendered_on": None,
                                   "planned_cost": cost})
        return (_put(ds, new), TransportReport(orders=[fid], message=f"{was} rejected {fid}; no other carrier's "
                                               f"vehicle takes it: it is planned at the lane's own cost, "
                                               f"{_money(ds, cost)}."))
    cost = nxt.cost(f.weight_kg, f.volume_m3, units)
    new = f.model_copy(update={"carrier": nxt.carrier, "mode": nxt.mode, "rejected_by": gone, "tendered_on": day,
                               "capacity_kg": nxt.cap_kg, "capacity_m3": nxt.cap_m3, "planned_cost": cost})
    return (_put(ds, new), TransportReport(orders=[fid], message=f"{was} rejected {fid}; tendered to "
                                           f"{_carrier(ds, nxt.carrier)} for {_money(ds, cost)} "
                                           f"({cost - f.planned_cost:+,.2f})."))


def ship(ds: Dataset, fid: str, on: date | None = None) -> tuple[Dataset, TransportReport]:
    """The vehicle leaves: the goods issue of each delivery on it and the dispatch of each transfer."""
    f = _fo(ds, fid)
    if f.status not in ("accepted", "planned") or (f.status == "planned" and f.carrier is not None):
        raise TransportError(f"{fid} is {f.status}: " + ("tender it and have the carrier accept it first"
                                                          if f.status in ("planned", "tendered") else "it cannot ship"))
    day = on or ds.settings.planning_start
    docs, moves, said = [], [], []
    try:
        for did in f.deliveries:
            d = next((x for x in ds.deliveries if x.id == did), None)
            if d is None:
                raise TransportError(f"{did} is no longer a delivery: take it off {fid} (cancel and plan again)")
            if d.issued_on is not None:
                continue
            ds, rep = goods_issue(ds, did, day)
            docs.append(did)
            moves += rep.movements
            said.append(did)
        for rid in f.transfers:
            if not any(r.id == rid for r in ds.receipts):
                continue
            ds, rep = ship_transfer(ds, rid, None, day)
            moves += rep.movements
            said.append(rid)
    except (SalesError, PostingError) as e:
        raise TransportError(f"{fid} cannot ship: {e}") from e
    new = _fo(ds, fid).model_copy(update={"status": "shipped", "shipped_on": day})
    return (_put(ds, new), TransportReport(orders=[fid], documents=docs, movements=moves,
                                           message=f"{fid} left {_name(ds, f.ship_from)} for {_name(ds, f.ship_to)} "
                                                   f"on {_day(day)} with {', '.join(said) or 'nothing new'}."))


def settle(ds: Dataset, fid: str, billed: float, bill: str = "", on: date | None = None
           ) -> tuple[Dataset, TransportReport]:
    """The carrier's bill: shared over what the freight order carried, the difference from the planned cost shown."""
    f = _fo(ds, fid)
    if f.status != "shipped":
        raise TransportError(f"{fid} is {f.status}: only a shipped freight order is settled")
    if not math.isfinite(billed) or billed < 0:
        raise TransportError("the bill is an amount of 0 or more")
    day = on or ds.settings.planning_start
    new = f.model_copy(update={"status": "settled", "billed": round(billed, 2), "bill": bill, "settled_on": day})
    ds2 = _put(ds, new)
    diff = billed - f.planned_cost
    k = ds.carrier_by_id.get(f.carrier or "")
    pay = f"; to pay by {_day(day + timedelta(days=k.payment_days))}" if k else ""
    shares = ", ".join(f"{x.id} {_money(ds, x.cost)}" for x in _lines(new)[:6])
    return (ds2, TransportReport(orders=[fid], message=f"{fid} settled" + (f" (their {bill})" if bill else "") +
                                 f": {_money(ds, billed)}, {diff:+,.2f} against the planned "
                                 f"{_money(ds, f.planned_cost)}{pay}. Shared by weight: {shares}."))


def cancel(ds: Dataset, fid: str) -> tuple[Dataset, TransportReport]:
    f = _fo(ds, fid)
    if f.status in ("shipped", "settled", "cancelled"):
        raise TransportError(f"{fid} is {f.status}: it cannot be cancelled")
    return (_put(ds, f.model_copy(update={"status": "cancelled"})),
            TransportReport(orders=[fid], message=f"{fid} cancelled: what it carried is waiting to be loaded again."))
