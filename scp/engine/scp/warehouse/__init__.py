"""The warehouse inside a place (Enterprise 6.1, S/4 guide §12.2–12.3): stock by bin, put-away, waves, pick lists and
warehouse tasks confirmed with a scanner.

Stock by bin is read from the goods-movement journal: a movement naming a bin puts its quantity there or takes it from
there; one naming none moves stock in no bin (goods in after a receipt, staged after a pick). A posting that takes
stock out without naming a bin (a goods issue without a pick, a component issue, a scrap) takes what is in no bin
first, then from the bins, first in, first out, and the stock view says so. A change of stock type (a release from
inspection) stays in the bins the stock was in.

Put-away follows the place's rules: the storage types named for the product (or for every product), in order, else
every storage type by its sequence; in each, its strategy: the product's fixed bins, a bin already holding it with
room, or the next empty bin along the walk. A bin holds one product unless its storage type is mixed, and no more than
its quantity and weight allow.

A wave takes the open deliveries of a place and makes a pick task for each part of each line from the bins that hold
it, first expiring first (FEFO), then first in, then nearest on the walk; the pick list is those tasks in walk order,
a bin and product picked once for every delivery that needs it. Confirming a task (bin and product read by the
scanner, the quantity found) posts the pair of movements that moves the stock, and when a delivery's picks are all
confirmed its lines are picked: the goods issue then ships the batches picked.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from ..actuals.documents import StockError, complete
from ..actuals.stock import before, movement_ids
from ..model import (
    Bin, Dataset, GoodsMovement, MovementType, Putaway, StockType, StorageType, TaskKind, WarehouseTask, Wave,
)
from ..model.common import Out

EPS = 1e-6
QKey = tuple[str, str | None, StockType]          # product, batch, stock type


class WarehouseError(ValueError):
    """A warehouse step the stock or the bins do not allow; the message says why in plain words."""


@dataclass
class Quant:
    bin: str
    product: str
    batch: str | None
    stock_type: StockType
    qty: float
    since: date


# ------------------------------------------------------------------------------------------------ reading
def has_bins(ds: Dataset, location: str) -> bool:
    return any(b.location == location for b in ds.bins)


def _name(ds: Dataset, pid: str) -> str:
    p = ds.product_by_id.get(pid)
    return p.name or pid if p else pid


def _n(q: float) -> str:
    return f"{q:,.0f}" if abs(q - round(q)) < EPS else f"{q:,.3f}".rstrip("0").rstrip(".")


def _bins(ds: Dataset, location: str) -> dict[str, Bin]:
    return {b.id: b for b in ds.bins if b.location == location}


def _types(ds: Dataset, location: str) -> dict[str, StorageType]:
    return {t.id: t for t in ds.storage_types if t.location == location}


def _day(ds: Dataset, location: str, on: date | None) -> date:
    """The day stock is read on: today, the planning start, as every posting is dated by default."""
    return on or ds.settings.planning_start


def _walk(bins: dict[str, Bin], b: str | None) -> tuple[int, int, str]:
    """Walk order: bins along the walk, then stock in no bin (goods in)."""
    if b is None or b not in bins:
        return (1, 0, b or "")
    return (0, bins[b].walk, b)


class Stock:
    """Stock by bin at one place on one day, from the journal (see the module docstring)."""

    def __init__(self, ds: Dataset, location: str, on: date | None = None) -> None:
        self.ds, self.location = ds, location
        self.on = _day(ds, location, on)
        self.bins = _bins(ds, location)
        self.quants: dict[tuple[str, QKey], Quant] = {}
        self.free: dict[QKey, float] = defaultdict(float)        # in no bin: goods in, or staged to ship
        self.untasked: list[str] = []                            # postings that took stock out of bins without a task
        moved: dict[tuple[str | None, str, str | None], list[tuple[str, float]]] = defaultdict(list)
        journal = [m for m in before(ds, self.on + timedelta(days=1)) if m.location == location]
        for m in sorted(journal, key=lambda m: m.date):         # (stable: postings of one day in journal order)
            k: QKey = (m.product, m.batch, m.stock_type)
            q = m.signed
            if m.bin:
                self._add(m.bin, k, q, m.date)
            elif m.type is MovementType.STATUS and q > 0 and moved.get((m.doc, m.product, m.batch)):
                # a change of stock type stays in the bins the stock was taken from
                left = q
                for b, took in moved.pop((m.doc, m.product, m.batch)):
                    put = min(left, took)
                    self._add(b, k, put, m.date)
                    left -= put
                self.free[k] += left
            else:
                self.free[k] += q
                if self.free[k] < -EPS:
                    took = self._take(k, -self.free[k])
                    if took:
                        self.free[k] += sum(t for _, t in took)
                        if m.type is MovementType.STATUS:
                            moved[(m.doc, m.product, m.batch)] += took
                        else:
                            self.untasked.append(m.id)

    def _add(self, b: str, k: QKey, q: float, on: date) -> None:
        x = self.quants.get((b, k))
        if x is None:
            x = self.quants[(b, k)] = Quant(b, k[0], k[1], k[2], 0.0, on)
        if x.qty <= EPS < q:
            x.since = on
        x.qty += q
        if abs(x.qty) <= EPS:
            del self.quants[(b, k)]

    def _take(self, k: QKey, q: float) -> list[tuple[str, float]]:
        """Take ``q`` of ``k`` out of the bins, first in first out (a posting that named no bin)."""
        out = []
        for x in sorted((x for (_, kk), x in self.quants.items() if kk == k and x.qty > EPS),
                        key=lambda x: (x.since, _walk(self.bins, x.bin))):
            if q <= EPS:
                break
            t = min(q, x.qty)
            out.append((x.bin, t))
            q -= t
        for b, t in out:
            self._add(b, k, -t, self.on)
        return out

    def in_bin(self, b: str) -> list[Quant]:
        return [x for (bb, _), x in self.quants.items() if bb == b and x.qty > EPS]

    def qty(self, b: str | None, k: QKey) -> float:
        if b is None:
            return self.free.get(k, 0.0)
        x = self.quants.get((b, k))
        return x.qty if x else 0.0


# ------------------------------------------------------------------------------------------------ the view
class BinRow(Out):
    bin: str
    storage_type: str
    walk: int
    product: str | None = None          # None: an empty bin
    batch: str | None = None
    stock_type: StockType | None = None
    qty: float = 0.0
    since: date | None = None
    expires_on: date | None = None
    fill: float | None = None           # share of the bin's limit used (its quantity or weight)
    blocked: bool = False
    fixed_for: str | None = None


class LooseRow(Out):
    product: str
    batch: str | None = None
    stock_type: StockType
    qty: float                           # positive: in no bin, to put away; negative: more left than came in
    to_put_away: float = 0.0             # less what open put-away tasks already move


class WarehouseView(Out):
    location: str
    on: date
    bins: list[BinRow]
    loose: list[LooseRow]
    tasks_open: int
    notes: list[str]


def _fill(ds: Dataset, b: Bin, held: list[tuple[str, float]]) -> float | None:
    shares = []
    if b.max_qty:
        shares.append(sum(q for _, q in held) / b.max_qty)
    if b.max_kg:
        kg = sum(q * (ds.product_by_id[p].weight_kg or 0) for p, q in held if p in ds.product_by_id)
        shares.append(kg / b.max_kg)
    return round(max(shares), 4) if shares else None


def view(ds: Dataset, location: str, on: date | None = None) -> WarehouseView:
    """Every bin of a place with what it holds (an empty bin once), stock in no bin and what the journal says."""
    if ds.location_by_id.get(location) is None:
        raise WarehouseError(f"there is no place {location}")
    st = Stock(ds, location, on)
    exp = {(b.product, b.id): b.expires_on for b in ds.batches}
    rows: list[BinRow] = []
    for b in sorted(st.bins.values(), key=lambda b: (b.walk, b.id)):
        qs = st.in_bin(b.id)
        fill = _fill(ds, b, [(x.product, x.qty) for x in qs])
        base = {"bin": b.id, "storage_type": b.storage_type, "walk": b.walk, "blocked": b.blocked,
                "fixed_for": b.product, "fill": fill}
        if not qs:
            rows.append(BinRow(**base))
        for x in sorted(qs, key=lambda x: (x.product, x.batch or "", x.stock_type.value)):
            rows.append(BinRow(**base, product=x.product, batch=x.batch, stock_type=x.stock_type, qty=round(x.qty, 6),
                               since=x.since, expires_on=exp.get((x.product, x.batch or ""))))
    for (b, _), x in st.quants.items():          # stock in a bin no longer kept: shown, never lost
        if b not in st.bins and x.qty > EPS:
            rows.append(BinRow(bin=b, storage_type="?", walk=10**9, product=x.product, batch=x.batch,
                               stock_type=x.stock_type, qty=round(x.qty, 6), since=x.since))
    moving = defaultdict(float)
    for t in ds.warehouse_tasks:
        if t.location == location and t.status == "open" and t.from_bin is None:
            moving[(t.product, t.batch, t.stock_type)] += t.qty
    loose = [LooseRow(product=k[0], batch=k[1], stock_type=k[2], qty=round(q, 6),
                      to_put_away=round(max(0.0, q - moving[k]), 6))
             for k, q in sorted(st.free.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2].value))
             if abs(q) > EPS]
    notes = []
    if st.untasked:
        notes.append(f"{len(st.untasked)} posting{'s' if len(st.untasked) != 1 else ''} took stock out of bins "
                     "without a pick (" + ", ".join(st.untasked[:5]) + ("…" if len(st.untasked) > 5 else "")
                     + "): the bins were emptied first in, first out; count them if that is not where it came from")
    short = [r for r in loose if r.qty < -EPS]
    if short:
        notes.append("more left than came in: " + ", ".join(f"{_n(-r.qty)} {_name(ds, r.product)}" for r in short)
                     + " (the books are below zero here)")
    if not st.bins:
        notes.append("no bins at this place yet: create its storage types and bins")
    return WarehouseView(location=location, on=st.on, bins=rows, loose=loose,
                         tasks_open=sum(1 for t in ds.warehouse_tasks if t.location == location and t.status == "open"),
                         notes=notes)


# ------------------------------------------------------------------------------------------------ put-away
class Room:
    """What each bin of a place holds, with the open tasks into it, as put-away fills it."""

    def __init__(self, ds: Dataset, st: Stock) -> None:
        self.ds, self.st = ds, st
        self.held: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for x in st.quants.values():
            if x.qty > EPS:
                self.held[x.bin][x.product] += x.qty
        for t in ds.warehouse_tasks:
            if t.location == st.location and t.status == "open":
                if t.to_bin:
                    self.held[t.to_bin][t.product] += t.qty
                if t.from_bin:
                    self.held[t.from_bin][t.product] -= t.qty

    def products(self, b: str) -> set[str]:
        return {p for p, q in self.held[b].items() if q > EPS}

    def count(self, t: StorageType, product: str) -> int:
        """Bins of storage type ``t`` holding ``product``."""
        return sum(1 for b in self.st.bins.values() if b.storage_type == t.id and product in self.products(b.id))

    def left(self, b: Bin, product: str) -> float:
        """How much more of ``product`` fits in ``b`` (inf: no limit)."""
        room = math.inf
        h = self.held[b.id]
        if b.max_qty:
            room = min(room, b.max_qty - sum(h.values()))
        w = self.ds.product_by_id[product].weight_kg if product in self.ds.product_by_id else None
        if b.max_kg and w:
            kg = sum(q * (self.ds.product_by_id[p].weight_kg or 0) for p, q in h.items() if p in self.ds.product_by_id)
            room = min(room, (b.max_kg - kg) / w)
        return max(0.0, room)

    def fits(self, b: Bin, t: StorageType | None, product: str) -> bool:
        if b.blocked or (b.product and b.product != product):
            return False
        others = self.products(b.id) - {product}
        return not others or bool(t and t.mixed)


def _search(ds: Dataset, location: str, product: str) -> list[StorageType]:
    """The storage types put-away looks at for ``product``, in order."""
    types = _types(ds, location)
    rule = next((r for r in ds.putaway_rules if r.location == location and r.product == product), None) or \
        next((r for r in ds.putaway_rules if r.location == location and not r.product), None)
    if rule is not None:
        return [types[s] for s in rule.storage_types if s in types]
    return sorted(types.values(), key=lambda t: (t.sequence, t.id))


def _candidates(ds: Dataset, room: Room, t: StorageType, product: str) -> list[Bin]:
    """The bins of storage type ``t`` that may take ``product``, in the order its strategy fills them."""
    bins = sorted((b for b in room.st.bins.values() if b.storage_type == t.id and room.fits(b, t, product)),
                  key=lambda b: (b.walk, b.id))
    if t.putaway is Putaway.FIXED:
        return [b for b in bins if b.product == product]
    empty = [b for b in bins if not room.products(b.id) and b.product in (None, product)]
    # a mixed area also takes it beside other products, once the empty bins are full
    beside = [b for b in bins if t.mixed and room.products(b.id) and product not in room.products(b.id)]
    if t.putaway is Putaway.ADD:
        return [b for b in bins if product in room.products(b.id)] + empty + beside
    return empty + beside


def _whole(ds: Dataset, product: str, q: float) -> float:
    return float(math.floor(q + EPS)) if ds.whole(product) else round(q, 6)


class ProposedTask(Out):
    product: str
    batch: str | None = None
    stock_type: StockType
    qty: float
    to_bin: str
    storage_type: str


class PutawayProposal(Out):
    location: str
    tasks: list[ProposedTask]
    notes: list[str]


def propose_putaway(ds: Dataset, location: str, on: date | None = None) -> PutawayProposal:
    """Where the stock in no bin goes, by the place's rules and strategies (nothing is changed)."""
    if not has_bins(ds, location):
        raise WarehouseError(f"{location} has no bins: create its storage types and bins first")
    st = Stock(ds, location, on)
    room = Room(ds, st)
    v = view(ds, location, st.on)
    out: list[ProposedTask] = []
    notes: list[str] = []
    for r in v.loose:
        left = _whole(ds, r.product, r.to_put_away)
        if left <= EPS:
            continue
        for t in _search(ds, location, r.product):
            for b in _candidates(ds, room, t, r.product):
                if left <= EPS:
                    break
                if t.bins_per_product and r.product not in room.products(b.id) and \
                        room.count(t, r.product) >= t.bins_per_product:
                    continue                      # it has its share of this area's bins
                q = _whole(ds, r.product, min(left, room.left(b, r.product)))
                if q <= EPS:
                    continue
                out.append(ProposedTask(product=r.product, batch=r.batch, stock_type=r.stock_type, qty=q, to_bin=b.id,
                                        storage_type=t.id))
                room.held[b.id][r.product] += q
                left -= q
            if left <= EPS:
                break
        if left > EPS:
            notes.append(f"no bin has room for {_n(left)} {_name(ds, r.product)}"
                         + (f" (batch {r.batch})" if r.batch else "") + ": add bins, or a storage type to its rule")
    return PutawayProposal(location=location, tasks=out, notes=notes)


def _task_ids(ds: Dataset):
    n = max((int(m.group(1)) for t in ds.warehouse_tasks if (m := re.fullmatch(r"WT-(\d+)", t.id))), default=0)
    while True:
        n += 1
        yield f"WT-{n:04d}"


class WarehouseReport(Out):
    message: str
    tasks: list[str] = []
    wave: str | None = None
    movements: list[str] = []
    next_task: str | None = None


def create_putaway(ds: Dataset, location: str, on: date | None = None) -> tuple[Dataset, WarehouseReport]:
    """Make the put-away tasks :func:`propose_putaway` proposes."""
    p = propose_putaway(ds, location, on)
    if not p.tasks:
        raise WarehouseError("nothing to put away" + (": " + "; ".join(p.notes) if p.notes else ""))
    day = on or ds.settings.planning_start
    ids = _task_ids(ds)
    made = [WarehouseTask(id=next(ids), location=location, kind=TaskKind.PUTAWAY, product=x.product, batch=x.batch,
                          stock_type=x.stock_type, qty=x.qty, to_bin=x.to_bin, created_on=day) for x in p.tasks]
    msg = (f"{len(made)} put-away task{'s' if len(made) != 1 else ''} at {location}: "
           + ", ".join(f"{_n(t.qty)} {_name(ds, t.product)} to {t.to_bin}" for t in made[:6])
           + (", …" if len(made) > 6 else ".") + (" " + "; ".join(p.notes).capitalize() + "." if p.notes else ""))
    return (ds.model_copy(update={"warehouse_tasks": [*ds.warehouse_tasks, *made]}),
            WarehouseReport(message=msg, tasks=[t.id for t in made], next_task=made[0].id))


# ------------------------------------------------------------------------------------------------ waves and picking
def _picks_of(ds: Dataset, did: str) -> list[WarehouseTask]:
    return [t for t in ds.warehouse_tasks if t.kind is TaskKind.PICK and t.delivery == did and t.status != "cancelled"]


def create_wave(ds: Dataset, location: str, deliveries: list[str] | None = None, on: date | None = None
                ) -> tuple[Dataset, WarehouseReport]:
    """Pick the open deliveries from ``location`` together (``deliveries``; None = every one due to leave by ``on``
    and not picked yet): a pick task for each part of each line, from the bins that hold it."""
    if not has_bins(ds, location):
        raise WarehouseError(f"{location} has no bins: pick its deliveries on the delivery itself")
    day = on or ds.settings.planning_start
    open_ = {d.id: d for d in ds.deliveries if d.ship_from == location and d.issued_on is None}
    if deliveries is None:
        chosen = [d for d in open_.values() if (d.planned_on or day) <= day and not _picks_of(ds, d.id)
                  and all(x.picked is None for x in d.lines)]
        if not chosen:
            raise WarehouseError(f"no delivery from {location} is due to be picked by {day.isoformat()}")
    else:
        chosen = []
        for did in dict.fromkeys(deliveries):
            if did not in open_:
                raise WarehouseError(f"{did} is not an open delivery from {location}")
            if _picks_of(ds, did):
                raise WarehouseError(f"{did} is already in a wave")
            chosen.append(open_[did])
    chosen.sort(key=lambda d: (d.planned_on or day, d.id))
    st = Stock(ds, location, day)
    types = _types(ds, location)
    exp = {(b.product, b.id): b.expires_on for b in ds.batches}
    taken: dict[tuple[str | None, QKey], float] = defaultdict(float)
    for t in ds.warehouse_tasks:                  # what open tasks already take
        if t.location == location and t.status == "open":
            taken[(t.from_bin, (t.product, t.batch, t.stock_type))] += t.qty
    n = max((int(m.group(1)) for w in ds.waves if (m := re.fullmatch(r"WV-(\d+)", w.id))), default=0)
    wid = f"WV-{n + 1:04d}"
    ids = _task_ids(ds)
    made: list[WarehouseTask] = []
    short: list[str] = []
    for d in chosen:
        gi = d.planned_on or day
        for ln in d.lines:
            need = ln.qty
            sources: list[tuple[tuple, str | None, QKey, float]] = []
            for (b, k), x in st.quants.items():
                if k[0] != ln.product or k[2] is not StockType.UNRESTRICTED or (ln.batch and k[1] != ln.batch):
                    continue
                bn = st.bins.get(b)
                if bn is None or bn.blocked:
                    continue
                e = exp.get((k[0], k[1] or ""))
                if e is not None and e < gi:
                    continue                      # expired by the goods issue
                reserve = not (types.get(bn.storage_type) and types[bn.storage_type].picking)
                sources.append(((reserve, e or date.max, x.since, _walk(st.bins, b)), b, k, x.qty))
            for k, q in st.free.items():          # last: in no bin yet (goods in)
                if k[0] == ln.product and k[2] is StockType.UNRESTRICTED and (not ln.batch or k[1] == ln.batch):
                    e = exp.get((k[0], k[1] or ""))
                    if e is None or e >= gi:
                        sources.append(((True, date.max, date.max, _walk(st.bins, None)), None, k, q))
            for _, b, k, have in sorted(sources, key=lambda s: s[0]):
                if need <= EPS:
                    break
                q = _whole(ds, ln.product, min(need, have - taken[(b, k)]))
                if q <= EPS:
                    continue
                taken[(b, k)] += q
                need -= q
                made.append(WarehouseTask(id=next(ids), location=location, kind=TaskKind.PICK, product=ln.product,
                                          batch=k[1], stock_type=k[2], qty=q, from_bin=b, wave=wid, delivery=d.id,
                                          order=ln.order, created_on=day))
            if need > EPS:
                short.append(f"{d.id} {ln.order}: {_n(need)} of {_n(ln.qty)} {_name(ds, ln.product)} not found in "
                             f"{location}'s bins")
    if not made:
        raise WarehouseError("nothing can be picked: " + "; ".join(short))
    wave = Wave(id=wid, location=location, created_on=day, deliveries=[d.id for d in chosen])
    n_bins = len({t.from_bin for t in made})
    msg = (f"Wave {wid}: {len(chosen)} deliver{'ies' if len(chosen) != 1 else 'y'}, {len(made)} pick"
           f"{'s' if len(made) != 1 else ''} from {n_bins} bin{'s' if n_bins != 1 else ''}, in walk order."
           + (" Short: " + "; ".join(short) + "." if short else ""))
    out = ds.model_copy(update={"warehouse_tasks": [*ds.warehouse_tasks, *made], "waves": [*ds.waves, wave]})
    first = pick_list(out, wid).rows[0].tasks[0]
    return out, WarehouseReport(message=msg, tasks=[t.id for t in made], wave=wid, next_task=first)


class PickFor(Out):
    delivery: str
    order: str
    qty: float
    task: str
    status: str


class PickRow(Out):
    bin: str | None                      # None: goods in (not put away yet)
    walk: int | None = None
    product: str
    name: str
    batch: str | None = None
    qty: float                           # still to pick
    picked: float = 0.0
    tasks: list[str]
    deliveries: list[PickFor]


class PickList(Out):
    wave: str
    location: str
    rows: list[PickRow]
    done: bool


def pick_list(ds: Dataset, wave: str) -> PickList:
    """A wave's picks in walk order: each bin, product and batch once, with the deliveries it is for."""
    w = next((x for x in ds.waves if x.id == wave), None)
    if w is None:
        raise WarehouseError(f"there is no wave {wave}")
    bins = _bins(ds, w.location)
    groups: dict[tuple, list[WarehouseTask]] = defaultdict(list)
    for t in ds.warehouse_tasks:
        if t.wave == wave and t.status != "cancelled":
            groups[(t.from_bin, t.product, t.batch)].append(t)
    rows = []
    for (b, p, batch), ts in sorted(groups.items(), key=lambda kv: (_walk(bins, kv[0][0]), kv[0][1], kv[0][2] or "")):
        rows.append(PickRow(bin=b, walk=bins[b].walk if b in bins else None, product=p, name=_name(ds, p), batch=batch,
                            qty=round(sum(t.qty for t in ts if t.status == "open"), 6),
                            picked=round(sum(t.done_qty or 0 for t in ts if t.status == "done"), 6),
                            tasks=[t.id for t in ts],
                            deliveries=[PickFor(delivery=t.delivery or "", order=t.order or "", qty=t.qty, task=t.id,
                                                status=t.status) for t in ts]))
    return PickList(wave=wave, location=w.location, rows=rows, done=all(r.qty <= EPS for r in rows))


# ------------------------------------------------------------------------------------------------ confirming
def _code(ds: Dataset, scanned: str) -> str | None:
    """The product a scanned code names: its id or its barcode."""
    s = scanned.strip()
    if s in ds.product_by_id:
        return s
    return next((p.id for p in ds.products if p.barcode and p.barcode.strip().lower() == s.lower()), None)


def _task(ds: Dataset, tid: str) -> WarehouseTask:
    t = next((x for x in ds.warehouse_tasks if x.id == tid), None)
    if t is None:
        raise WarehouseError(f"there is no warehouse task {tid}")
    if t.status != "open":
        raise WarehouseError(f"{tid} is {t.status} already")
    return t


def next_task(ds: Dataset, after: WarehouseTask) -> str | None:
    """The next open task to do after ``after``: in its wave along the walk, else at its place."""
    bins = _bins(ds, after.location)
    pool = [t for t in ds.warehouse_tasks if t.status == "open" and t.location == after.location and t.id != after.id]
    same = [t for t in pool if after.wave and t.wave == after.wave] or [t for t in pool if t.kind is after.kind] or pool
    if not same:
        return None
    key = (lambda t: _walk(bins, t.from_bin)) if after.kind is TaskKind.PICK else (lambda t: _walk(bins, t.to_bin))
    return min(same, key=lambda t: (key(t), t.id)).id


def confirm_task(ds: Dataset, tid: str, qty: float | None = None, scanned_bin: str | None = None,
                 scanned_product: str | None = None, on: date | None = None, by: str = ""
                 ) -> tuple[Dataset, WarehouseReport]:
    """Confirm a task: the bin read (the one picked from, or put into: another bin with room may be chosen for a
    put-away), the product read (its id or barcode) and the quantity moved (less is short). Posts the bin move."""
    t = _task(ds, tid)
    if scanned_product is not None:
        got = _code(ds, scanned_product)
        if got != t.product:
            what = f"{_name(ds, got)}" if got else f"code {scanned_product.strip()!r}, no product of ours"
            raise WarehouseError(f"that is {what}: {tid} is for {_name(ds, t.product)}")
    bins = _bins(ds, t.location)
    to_bin = t.to_bin
    if scanned_bin is not None:
        s = scanned_bin.strip()
        if t.kind is TaskKind.PICK or (t.kind is TaskKind.MOVE and s == t.from_bin):
            if s != (t.from_bin or ""):
                raise WarehouseError(f"that is bin {s}: {tid} picks from {t.from_bin or 'goods in'}")
        elif s != t.to_bin:
            b = bins.get(s)
            if b is None:
                raise WarehouseError(f"{s} is not a bin at {t.location}")
            st = Stock(ds, t.location, on)
            room = Room(ds, st)
            if t.to_bin:
                room.held[t.to_bin][t.product] -= t.qty          # this task no longer goes there
            if not room.fits(b, _types(ds, t.location).get(b.storage_type), t.product) or \
                    room.left(b, t.product) < (qty if qty is not None else t.qty) - EPS:
                raise WarehouseError(f"bin {s} cannot take {_n(qty if qty is not None else t.qty)} "
                                     f"{_name(ds, t.product)}: " + ("it is blocked" if b.blocked else
                                                                    "it holds another product" if not room.fits(
                                                                        b, _types(ds, t.location).get(b.storage_type),
                                                                        t.product) else "not enough room"))
            to_bin = s
    q = t.qty if qty is None else float(qty)
    if not math.isfinite(q) or q < -EPS or q > t.qty + EPS:
        raise WarehouseError(f"{tid}: move between 0 and {_n(t.qty)}")
    if ds.whole(t.product) and abs(q - round(q)) > EPS:
        raise WarehouseError(f"{_name(ds, t.product)} is counted in whole units")
    day = on or ds.settings.planning_start
    moves: list[GoodsMovement] = []
    if q > EPS:
        st = Stock(ds, t.location, day)
        have = st.qty(t.from_bin, (t.product, t.batch, t.stock_type))
        if have < q - EPS:
            where = f"bin {t.from_bin}" if t.from_bin else "goods in"
            raise WarehouseError(f"{where} holds only {_n(max(have, 0.0))} {_name(ds, t.product)}"
                                 + (f" (batch {t.batch})" if t.batch else "") + ": confirm what you found")
        ids = movement_ids(ds)
        note = {TaskKind.PUTAWAY: "Put away", TaskKind.PICK: f"Picked for {t.delivery}", TaskKind.MOVE: "Bin move"}
        for b, sign in ((t.from_bin, -1.0), (to_bin, 1.0)):
            moves.append(GoodsMovement(id=next(ids), date=day, type=MovementType.STATUS, location=t.location,
                                       product=t.product, qty=round(sign * q, 6), batch=t.batch,
                                       stock_type=t.stock_type, bin=b,
                                       note=f"{note[t.kind]} ({t.id})"))
        try:
            moves, _, _ = complete(ds, moves, day)
        except StockError as e:
            raise WarehouseError(str(e)) from e
    done = t.model_copy(update={"status": "done", "done_qty": round(q, 6), "done_on": day, "done_by": by[:120],
                                "to_bin": to_bin, "movements": [m.id for m in moves]})
    tasks = [done if x is t else x for x in ds.warehouse_tasks]
    out = ds.model_copy(update={"warehouse_tasks": tasks, "movements": [*ds.movements, *moves]})
    short = q < t.qty - EPS
    what = {TaskKind.PUTAWAY: f"put away in {to_bin}", TaskKind.PICK: f"picked from {t.from_bin or 'goods in'}",
            TaskKind.MOVE: f"moved to {to_bin}"}[t.kind]
    msg = f"{tid}: {_n(q)} {_name(ds, t.product)} {what}" + (f", {_n(t.qty - q)} short" if short else "") + "."
    if t.kind is TaskKind.PICK and short and t.from_bin:
        left = Stock(out, t.location, day).qty(t.from_bin, (t.product, t.batch, t.stock_type))
        msg += (f" Count bin {t.from_bin}: the books say it still holds {_n(left)}." if left > EPS else
                f" Bin {t.from_bin} is empty by the books.")
    if t.kind is TaskKind.PICK and t.delivery:
        out, said = _picked(out, t.delivery)
        msg += said
    elif t.kind is TaskKind.PUTAWAY and short:
        msg += " The rest stays in goods in, to put away again."
    return out, WarehouseReport(message=msg, tasks=[tid], wave=t.wave, movements=[m.id for m in moves],
                                next_task=next_task(out, done))


def _picked(ds: Dataset, did: str) -> tuple[Dataset, str]:
    """When every pick of a delivery is confirmed, its lines are picked as confirmed."""
    picks = _picks_of(ds, did)
    if any(p.status == "open" for p in picks):
        return ds, ""
    dl = next(d for d in ds.deliveries if d.id == did)
    lines, short = [], []
    for x in dl.lines:
        mine = [p for p in picks if p.order == x.order]
        got = round(sum(p.done_qty or 0 for p in mine), 6)
        batches = {p.batch for p in mine if (p.done_qty or 0) > EPS}
        lines.append(x.model_copy(update={"picked": min(got, x.qty),
                                          "batch": next(iter(batches)) if len(batches) == 1 else x.batch}))
        if got < x.qty - EPS:
            short.append(f"{x.order} {_n(got)} of {_n(x.qty)}")
    new = dl.model_copy(update={"lines": lines})
    out = ds.model_copy(update={"deliveries": [new if d is dl else d for d in ds.deliveries]})
    return out, (f" {did} is picked" + (f", short: {', '.join(short)}" if short else " in full")
                 + ": pack it and ship it.")


def cancel_task(ds: Dataset, tid: str) -> tuple[Dataset, WarehouseReport]:
    t = _task(ds, tid)
    gone = t.model_copy(update={"status": "cancelled"})
    out = ds.model_copy(update={"warehouse_tasks": [gone if x is t else x for x in ds.warehouse_tasks]})
    msg = f"{tid} cancelled: nothing was moved."
    if t.kind is TaskKind.PICK and t.delivery:
        out, said = _picked(out, t.delivery)
        msg += said
    return out, WarehouseReport(message=msg, tasks=[tid], wave=t.wave, next_task=next_task(out, gone))


def picked_batches(ds: Dataset, did: str) -> dict[str, dict[str | None, float]]:
    """Per order line of delivery ``did``: what its confirmed picks took, by batch (the goods issue ships these)."""
    out: dict[str, dict[str | None, float]] = defaultdict(lambda: defaultdict(float))
    for p in _picks_of(ds, did):
        if p.status == "done" and (p.done_qty or 0) > EPS and p.order:
            out[p.order][p.batch] += p.done_qty or 0
    return out


def open_picks(ds: Dataset, did: str) -> list[str]:
    return [p.id for p in _picks_of(ds, did) if p.status == "open"]


def move_task(ds: Dataset, location: str, product: str, qty: float, from_bin: str, to_bin: str,
              batch: str | None = None, stock_type: StockType = StockType.UNRESTRICTED, on: date | None = None
              ) -> tuple[Dataset, WarehouseReport]:
    """A task to move stock from one bin to another (a refill of a picking bin from the reserve, a tidy-up)."""
    bins = _bins(ds, location)
    for b in (from_bin, to_bin):
        if b not in bins:
            raise WarehouseError(f"{b} is not a bin at {location}")
    if from_bin == to_bin:
        raise WarehouseError("the stock is in that bin already")
    st = Stock(ds, location, on)
    have = st.qty(from_bin, (product, batch, stock_type))
    if qty <= EPS or qty > have + EPS:
        raise WarehouseError(f"bin {from_bin} holds {_n(have)} {_name(ds, product)}" + (f" (batch {batch})" if batch else ""))
    room = Room(ds, st)
    b = bins[to_bin]
    if not room.fits(b, _types(ds, location).get(b.storage_type), product) or room.left(b, product) < qty - EPS:
        raise WarehouseError(f"bin {to_bin} cannot take {_n(qty)} {_name(ds, product)}")
    t = WarehouseTask(id=next(_task_ids(ds)), location=location, kind=TaskKind.MOVE, product=product, batch=batch,
                      stock_type=stock_type, qty=round(qty, 6), from_bin=from_bin, to_bin=to_bin,
                      created_on=on or ds.settings.planning_start)
    return (ds.model_copy(update={"warehouse_tasks": [*ds.warehouse_tasks, t]}),
            WarehouseReport(message=f"{t.id}: move {_n(qty)} {_name(ds, product)} from {from_bin} to {to_bin}.",
                            tasks=[t.id], next_task=t.id))
