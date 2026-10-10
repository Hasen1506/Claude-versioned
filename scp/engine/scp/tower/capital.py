"""Working capital from the records the system holds, as of any day: the stock journal rebuilds each day's stock, the
customer and supplier invoices with their payments give what is owed on that day. The Performance page shows it on
the planning start (DIO and turns on the average stock of the period, DSO counted back through the billing, ageing
buckets of what is open), and on each of the last weeks before it (the trend).

* **Average stock**: the stock at unit value on every day of the period, rebuilt from on-hand on the day and the
  movements before it, then averaged, so a single large receipt just before the day does not swing DIO and turns. An
  opening balance is stock that was already there: it is not taken back.
* **DSO by count-back**: receivables are set against the billing of the most recent days, day by day back, until they
  are used up; the days counted are DSO. A seasonal seller with a big last month reads a truer figure than from the
  average of the period (which is kept in the note).
* **Ageing**: what is open on the day by days past its due date (not yet due, 1–30, 31–60, over 60), and credit
  still to be settled.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from ..model import Dataset, LocationType, MovementType

EPS = 1e-9
BUCKETS = ("not yet due", "1–30 days overdue", "31–60 days overdue", "over 60 days overdue")
CREDIT = "credit to settle"


def bucket(as_of: dt.date, due: dt.date) -> str:
    late = (as_of - due).days
    return BUCKETS[0] if late <= 0 else BUCKETS[1] if late <= 30 else BUCKETS[2] if late <= 60 else BUCKETS[3]


def count_back(owed: float, billed_on: dict[dt.date, float], as_of: dt.date) -> float | None:
    """Days of the most recent billing that ``owed`` takes up, counted back from the day before ``as_of`` (a day with
    no billing counts whole). None when the billing runs out first."""
    if owed <= EPS:
        return 0.0
    if not billed_on:
        return None
    rem, days, d, first = owed, 0.0, as_of - dt.timedelta(days=1), min(billed_on)
    while d >= first:
        b = billed_on.get(d, 0.0)
        if b > EPS and rem <= b + EPS:
            return days + rem / b
        rem -= b
        days += 1
        d -= dt.timedelta(days=1)
    return None


@dataclass
class Capital:
    as_of: dt.date
    since: dt.date
    need: int
    inv_close: float = 0.0
    inv_avg: float = 0.0
    inv_by: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    cogs: float = 0.0
    cogs_days: int = 0
    n_sales: int = 0
    unvalued: int = 0
    ar: float = 0.0
    billed: float = 0.0
    ar_days: int = 0
    n_inv: int = 0
    ar_by: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    billed_by: dict[str, dict[dt.date, float]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))
    ar_age: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    ap: float = 0.0
    bought: float = 0.0
    ap_days: int = 0
    n_sup: int = 0
    ap_by: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    ap_age: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    foreign: int = 0

    @property
    def cogs_ok(self) -> bool:
        return self.cogs_days >= self.need and self.cogs > EPS

    @property
    def ar_ok(self) -> bool:
        return self.ar_days >= self.need and self.billed > EPS

    @property
    def ap_ok(self) -> bool:
        return self.ap_days >= self.need and self.bought > EPS

    @property
    def dio(self) -> float | None:
        return self.inv_avg / self.cogs * self.cogs_days if self.cogs_ok else None

    @property
    def turns(self) -> float | None:
        return self.cogs / self.cogs_days * 365 / self.inv_avg if self.cogs_ok and self.inv_avg > EPS else None

    @property
    def dso_average(self) -> float | None:
        return self.ar / self.billed * self.ar_days if self.ar_ok else None

    @property
    def dso(self) -> float | None:
        if not self.ar_ok:
            return None
        total: dict[dt.date, float] = defaultdict(float)
        for days in self.billed_by.values():
            for d, v in days.items():
                total[d] += v
        cb = count_back(self.ar, total, self.as_of)
        return cb if cb is not None else self.dso_average

    def dso_of(self, customer: str) -> float | None:
        owed = self.ar_by[customer][0]
        cb = count_back(max(0.0, owed), self.billed_by.get(customer, {}), self.as_of)
        if cb is not None:
            return cb
        v = self.ar_by[customer]
        return v[0] / v[1] * self.ar_days if v[1] > EPS else None

    @property
    def dpo(self) -> float | None:
        return self.ap / self.bought * self.ap_days if self.ap_ok else None

    @property
    def ccc(self) -> float | None:
        dio, dso, dpo = self.dio, self.dso, self.dpo
        return None if dio is None or dso is None or dpo is None else dio + dso - dpo


def capital_at(ds: Dataset, unit_value: dict[tuple[str, str], float], on_hand: dict[tuple[str, str], float],
               as_of: dt.date, window_days: int, min_days: int) -> Capital:
    """Working capital on ``as_of`` (the records dated before it), over the ``window_days`` before it. ``on_hand``: the
    stock of each stocking place on the planning start; the journal takes it back to ``as_of`` when that is earlier.
    ``unit_value``: what a unit of each is worth (the plan's valuation)."""
    start = ds.settings.planning_start
    since = as_of - dt.timedelta(days=window_days)
    c = Capital(as_of=as_of, since=since, need=min(min_days, window_days))
    cur = ds.settings.currency

    def span(first: dt.date | None) -> int:
        return 0 if first is None else max(0, (as_of - max(since, first)).days)

    def rate(code: str | None) -> float | None:
        if not code or code == cur:
            return 1.0
        return ds.settings.fx_rates.get(code)

    # stock on the day: on-hand on the planning start, less what moved in between
    stock = dict(on_hand)
    # an opening balance says how much there already was, not that it arrived that day: it is not taken back
    moves = [m for m in ds.movements if (m.location, m.product) in stock and m.type is not MovementType.OPENING]
    for m in moves:
        if as_of <= m.date < start:
            stock[(m.location, m.product)] -= m.signed
    # cost of goods sold: goods issued to customers before the day, in the window, at unit value
    sales = [m for m in ds.movements if m.type is MovementType.SALE and m.date < as_of]
    first_sale = min((m.date for m in sales), default=None)
    c.cogs_days = span(first_sale)
    for m in sales:
        if m.date < since:
            continue
        v = unit_value.get((m.location, m.product), 0.0)
        if v <= EPS:
            c.unvalued += 1
        c.cogs += m.net * v
        c.n_sales += 1
        p = ds.product_by_id.get(m.product)
        c.inv_by[p.type.value if p else "?"][1] += m.net * v
    # the average over the days of the period: each movement in it was not yet in the stock of the days before it
    w0 = as_of - dt.timedelta(days=c.cogs_days)
    before: dict[tuple[str, str], float] = defaultdict(float)
    if c.cogs_days > 0:
        for m in moves:
            if w0 <= m.date < as_of:
                before[(m.location, m.product)] += m.signed * (m.date - w0).days / c.cogs_days
    for key, q in stock.items():
        v = unit_value.get(key, 0.0)
        avg = max(0.0, q - before.get(key, 0.0)) if c.cogs_days > 0 else max(0.0, q)
        c.inv_close += max(0.0, q) * v
        c.inv_avg += avg * v
        p = ds.product_by_id.get(key[1])
        c.inv_by[p.type.value if p else "?"][0] += avg * v
    # receivables and sales billed, with ageing
    docs = [i for i in ds.invoices if not i.cancelled and i.date < as_of]
    c.ar_days = span(min((i.date for i in docs), default=None))
    for i in docs:
        sign = -1.0 if i.kind == "credit_note" else 1.0
        paid = sum(p.amount + p.discount for p in i.payments if p.date < as_of)
        left = max(0.0, i.total - paid)
        c.ar += sign * left
        c.ar_by[i.customer][0] += sign * left
        c.billed_by[i.customer][i.date] += sign * i.total
        if left > 0.005:
            row = c.ar_age[CREDIT if sign < 0 else bucket(as_of, i.due_date)]
            row[0] += sign * left
            row[1] += 1
        if i.date >= since:
            c.billed += sign * i.total
            c.ar_by[i.customer][1] += sign * i.total
            c.n_inv += 1
    c.ar = max(0.0, c.ar)
    # payables and purchases billed (company currency), with ageing
    sdocs = [s for s in ds.supplier_invoices if not s.cancelled and s.date < as_of]
    c.ap_days = span(min((s.date for s in sdocs), default=None))
    for s in sdocs:
        fx = rate(s.currency)
        if fx is None:
            c.foreign += 1
            continue
        sign = -1.0 if s.credit else 1.0
        paid = sum(p.amount + p.discount for p in s.payments if p.date < as_of)
        left = max(0.0, s.total - paid) * fx
        c.ap += sign * left
        c.ap_by[s.supplier][0] += sign * left
        if left > 0.005:
            row = c.ap_age[CREDIT if sign < 0 else bucket(as_of, s.due_date)]
            row[0] += sign * left
            row[1] += 1
        if s.date >= since:
            c.bought += sign * s.total * fx
            c.ap_by[s.supplier][1] += sign * s.total * fx
            c.n_sup += 1
    c.ap = max(0.0, c.ap)
    return c


def stocking_on_hand(ds: Dataset, nodes) -> dict[tuple[str, str], float]:
    """On-hand of each stocking place on the planning start (customers hold no stock of ours)."""
    return {(n.location, n.product): n.on_hand for n in nodes
            if ds.location_type(n.location) is not LocationType.CUSTOMER}
