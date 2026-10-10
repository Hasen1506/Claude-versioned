"""The KPI set of the S/4 guide §18.2, each computed from data this system holds and graded against a target.

Every KPI names its definition and source, carries its numerator and denominator, and says so when it has
no data yet (``value`` None) rather than showing a flattering default.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable

from ..actuals.stock import accuracy_report
from ..finance.result import ServeRow
from ..model import Dataset, LocationType, MovementType
from ..model.actuals import ClosedOrder
from ..plan.result import PlanResult
from .capital import BUCKETS, CREDIT, Capital, capital_at, stocking_on_hand
from .result import Kpi, KpiPoint, KpiRow, WorkItem

EPS = 1e-9
OUTBOUND = {MovementType.ISSUE, MovementType.SALE, MovementType.TRANSFER_OUT}
# a working-capital flow (goods issued, invoices) needs at least this many days of records to give a value
MIN_DAYS = 28
TREND_WEEKS = 12                 # weekly points of the working-capital trend, the planning start the last


def grade(value: float | None, target: float | None, direction: str, unit: str) -> str:
    if value is None or target is None or direction == "none":
        return "none"
    band = 0.05 if unit == "ratio" else 0.25 * abs(target)
    if direction == "up":
        return "good" if value >= target - EPS else "warning" if value >= target - band else "critical"
    v = abs(value) if direction == "zero" else value
    return "good" if v <= target + EPS else "warning" if v <= target + band else "critical"


class Kpis:
    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.cfg = ds.tower
        self.as_of = ds.settings.planning_start
        self.since = self.as_of - dt.timedelta(days=self.cfg.kpi_window_days)
        # an order cancelled before anything was delivered is not a delivery to measure
        self.closed = [c for c in ds.closed_orders if self.since <= c.closed_on <= self.as_of
                       and not (c.cancelled and c.delivered_qty <= EPS)]
        self.out: list[Kpi] = []

    def add(self, k: Kpi) -> Kpi:
        k.target = self.cfg.targets.get(k.id)
        k.status = grade(k.value, k.target, k.direction, k.unit)
        self.out.append(k)
        return k

    # ---- helpers -----------------------------------------------------------------------------------
    @staticmethod
    def _share(rows: list, ok: Callable[[object], bool], weight: Callable[[object], float],
               label: Callable[[object], str]) -> tuple[float | None, float, float, list[KpiRow]]:
        num = den = 0.0
        by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            w = weight(r)
            den += w
            by[label(r)][1] += w
            if ok(r):
                num += w
                by[label(r)][0] += w
        value = num / den if den > EPS else None
        brk = [KpiRow(label=k, value=(v[0] / v[1] if v[1] > EPS else None), numerator=v[0], denominator=v[1])
               for k, v in sorted(by.items())]
        return value, num, den, brk

    def _in_full(self, c: ClosedOrder) -> bool:
        if c.cancelled:     # the rest was cancelled: what was delivered is what the customer still wanted
            return True
        return c.delivered_qty >= c.ordered_qty * (1.0 - self.ds.execution.delivery_tolerance) - EPS

    # ---- demand ------------------------------------------------------------------------------------
    def forecast(self) -> None:
        recs = [r for r in self.ds.accuracy if r.end > self.since and r.start < self.as_of]
        rep = accuracy_report(recs)
        brk = sorted((KpiRow(label=f"{s.location} · {s.product}", value=s.accuracy, numerator=s.abs_error,
                             denominator=s.actual) for s in rep.series), key=lambda r: (r.value is None, r.value or 0))
        self.add(Kpi(id="forecast_accuracy", name="Forecast accuracy", unit="ratio", direction="up",
                     definition="1 − WMAPE = 1 − Σ|forecast − actual| ÷ Σ actual, over the series-weeks in the window",
                     source="Accuracy log written by the roll-forward (forecast vs sales per series-week)",
                     value=rep.accuracy, numerator=rep.actual - sum(s.abs_error for s in rep.series),
                     denominator=rep.actual, n=len(recs), breakdown_by="series", breakdown=brk,
                     note="" if recs else "No weeks measured yet: roll forward past elapsed weeks."))
        brk_b = sorted((KpiRow(label=f"{s.location} · {s.product}", value=s.bias, numerator=s.forecast - s.actual,
                               denominator=s.actual) for s in rep.series), key=lambda r: -abs(r.value or 0))
        self.add(Kpi(id="forecast_bias", name="Forecast bias", unit="ratio", direction="zero",
                     definition="(Σ forecast − Σ actual) ÷ Σ actual: > 0 over-forecast, < 0 under-forecast",
                     source="Accuracy log", value=rep.bias, numerator=rep.forecast - rep.actual, denominator=rep.actual,
                     n=len(recs), breakdown_by="series", breakdown=brk_b))

    # ---- customer service ----------------------------------------------------------------------------
    def confirmation(self) -> None:
        rows: list[tuple[str, float, float]] = []   # (customer, requested qty, confirmed on the requested date)
        for c in self.closed:
            if c.kind == "sales" and c.promised_date is not None and not c.cancelled:
                on = c.confirmed_on_time_qty
                if on is None:
                    on = c.ordered_qty if c.promised_date <= c.due_date else 0.0
                rows.append((c.location, c.ordered_qty, min(on, c.ordered_qty)))
        conf: dict[str, list] = defaultdict(list)
        for cf in self.ds.confirmations:
            conf[cf.order].append(cf)
        for d in self.ds.demand:
            if d.kind.value == "sales_order" and (d.id in conf or d.fulfilled_confirmations):
                on = sum(cf.qty for cf in [*conf[d.id], *d.fulfilled_confirmations] if cf.date <= d.date)
                ordered = d.ordered_qty if d.ordered_qty is not None else d.qty
                rows.append((d.location, ordered, min(on, ordered)))
        den = sum(r[1] for r in rows)
        num = sum(r[2] for r in rows)
        value = num / den if den > EPS else None
        by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for cus, req, on in rows:
            by[cus][0] += on
            by[cus][1] += req
        brk = [KpiRow(label=k, value=v[0] / v[1] if v[1] > EPS else None, numerator=v[0], denominator=v[1])
               for k, v in sorted(by.items())]
        self.add(Kpi(id="confirmation_rate", name="Confirmed on requested date", unit="ratio", direction="up",
                     definition="Quantity confirmed on or before the first requested date ÷ requested quantity",
                     source="Confirmations of open sales orders and the last confirmed date of closed ones",
                     value=value, numerator=num, denominator=den, n=len(rows), breakdown_by="customer", breakdown=brk,
                     note="" if rows else "No promises yet: check and commit orders in Promising."))

    def otif(self) -> None:
        sales = [c for c in self.closed if c.kind == "sales"]

        def on_time(c: ClosedOrder, date: dt.date | None) -> bool:
            return c.last_delivery is not None and date is not None and c.last_delivery <= date

        conf = [c for c in sales if c.promised_date is not None]
        v, num, den, brk = self._share(conf, lambda c: self._in_full(c) and on_time(c, c.promised_date), lambda c: 1.0,
                                       lambda c: c.location)
        self.add(Kpi(id="otif_confirmed", name="OTIF to confirmed date", unit="ratio", direction="up",
                     definition="Sales orders delivered in full (within the delivery tolerance) by the confirmed date ÷ "
                                "orders closed in the window that had a confirmation",
                     source="Closed-order log (deliveries vs last confirmed date; a delivery counts on the day the customer "
                            "signed for it, else on goods issue plus the lane's transit)", value=v, numerator=num,
                     denominator=den, n=len(conf), breakdown_by="customer", breakdown=brk,
                     note="" if conf else "No closed, confirmed sales orders in the window yet."))
        v, num, den, brk = self._share(sales, lambda c: self._in_full(c) and on_time(c, c.due_date), lambda c: 1.0,
                                       lambda c: c.location)
        self.add(Kpi(id="otif_requested", name="OTIF to requested date", unit="ratio", direction="up",
                     definition="Sales orders delivered in full by the customer's requested date ÷ orders closed in "
                                "the window", source="Closed-order log (deliveries vs requested date; signed-for day, else issue plus transit)", value=v,
                     numerator=num, denominator=den, n=len(sales), breakdown_by="customer", breakdown=brk,
                     note="" if sales else "No sales orders closed in the window yet: roll forward to log deliveries."))
        v, num, den, brk = self._share(
            sales, lambda c: (on_time(c, c.due_date) and c.delivered_qty >= c.ordered_qty - EPS
                              and c.first_delivery == c.last_delivery), lambda c: 1.0, lambda c: c.location)
        self.add(Kpi(id="perfect_order", name="Perfect order", unit="ratio", direction="up",
                     definition="Delivered by the requested date ∧ the full ordered quantity (no tolerance) ∧ in one "
                                "delivery",
                     source="Closed-order log", value=v, numerator=num, denominator=den, n=len(sales),
                     breakdown_by="customer", breakdown=brk,
                     note="Documentation, damage and invoicing are outside this system, so perfect order here is "
                          "the delivery part of the composite."))

    # ---- supply -------------------------------------------------------------------------------------
    def supplier(self) -> None:
        pos = [c for c in self.closed if c.kind == "purchase"]
        v, num, den, brk = self._share(
            pos, lambda c: self._in_full(c) and c.last_delivery is not None and c.last_delivery <= c.due_date,
            lambda c: 1.0, lambda c: c.counterparty or "(unknown supplier)")
        self.add(Kpi(id="supplier_reliability", name="Supplier delivery reliability", unit="ratio", direction="up",
                     definition="Purchase orders received in full by their due date ÷ purchase orders closed in the "
                                "window", source="Closed-order log (goods receipts vs due date)", value=v, numerator=num,
                     denominator=den, n=len(pos), breakdown_by="supplier", breakdown=brk,
                     note="" if pos else "No purchase orders closed in the window yet."))

    def adherence(self) -> None:
        ws = self.ds.settings.week_start

        def week(d: dt.date) -> dt.date:
            return d - dt.timedelta(days=(d.weekday() - ws) % 7)

        mos = [c for c in self.closed if c.kind == "production"]
        # S/4 guide §18.2: orders finished in the planned period ÷ orders PLANNED. A production order whose planned
        # week is over and that is still open did not finish in it: it counts against adherence now, not only
        # once it finally closes (else a plant whose orders run late shows only the few that made it)
        this_week = week(self.as_of)
        late_open = [r for r in self.ds.receipts if r.kind.value == "production" and self.since <= r.due_date
                     and week(r.due_date) < this_week]
        rows = [(c.location, c.last_delivery is not None and week(c.last_delivery) == week(c.due_date)) for c in mos]
        rows += [(r.location, False) for r in late_open]
        v, num, den, brk = self._share(rows, lambda x: x[1], lambda x: 1.0, lambda x: x[0])
        self.add(Kpi(id="schedule_adherence", name="Schedule adherence", unit="ratio", direction="up",
                     definition="Production orders finished in their planned week (neither early nor late) ÷ "
                                "production orders planned to finish in the window: closed ones, and open ones whose "
                                "planned week is over",
                     source="Closed-order log (last goods receipt vs due date) and open production orders",
                     value=v, numerator=num, denominator=den, n=len(rows), breakdown_by="plant", breakdown=brk,
                     note=(f"{len(late_open)} open order{'s' if len(late_open) != 1 else ''} past its planned week "
                           "counted as missed." if late_open else "")
                          or ("" if mos else "No production orders closed in the window yet.")))

    # ---- inventory ----------------------------------------------------------------------------------
    def inventory(self, plan: PlanResult) -> None:
        ds = self.ds
        horizon = ds.settings.horizon_days
        cover_end = self.as_of + dt.timedelta(days=self.cfg.excess_cover_days)
        req_cover: dict[tuple[str, str], float] = defaultdict(float)
        for r in plan.requirements:
            if r.date < cover_end:
                req_cover[(r.location, r.product)] += r.qty
        last_out: dict[tuple[str, str], dt.date] = {}
        first_mov: dict[tuple[str, str], dt.date] = {}
        for m in ds.movements:
            if m.date >= self.as_of:
                continue
            k = (m.location, m.product)
            first_mov[k] = min(first_mov.get(k, m.date), m.date)
            if m.type in OUTBOUND:
                last_out[k] = max(last_out.get(k, m.date), m.date)
        slow_cut = self.as_of - dt.timedelta(days=self.cfg.slow_moving_days)
        stock_v = daily_v = obsolete = excess = slow = 0.0
        dos_by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        eo_rows: list[KpiRow] = []
        n_nodes = 0
        for node in plan.nodes:
            if ds.location_type(node.location) is LocationType.CUSTOMER or node.on_hand <= EPS:
                continue
            n_nodes += 1
            key = (node.location, node.product)
            v = node.on_hand * node.unit_value
            total_req = sum(b.gross_independent + b.gross_dependent for b in node.buckets)
            p = ds.product_by_id.get(node.product)
            ptype = p.type.value if p else "?"
            stock_v += v
            if total_req <= EPS:
                obsolete += v
                eo_rows.append(KpiRow(label=f"{node.location} · {node.product} (no demand)", value=v, numerator=v))
            else:
                daily = total_req / horizon * node.unit_value
                daily_v += daily
                dos_by[ptype][0] += v
                dos_by[ptype][1] += daily
                over = max(0.0, node.on_hand - req_cover.get(key, 0.0)) * node.unit_value
                if over > EPS:
                    excess += over
                    eo_rows.append(KpiRow(label=f"{node.location} · {node.product} (excess)", value=over, numerator=over))
            if key in first_mov and first_mov[key] <= slow_cut and last_out.get(key, dt.date.min) < slow_cut:
                slow += v
        self.add(Kpi(id="days_of_supply", name="Days of supply", unit="days", direction="none",
                     definition="Stock value ÷ average daily requirement value over the horizon, stocking nodes "
                                "that have requirements", source="On-hand and the supply plan's gross requirements",
                     value=(stock_v - obsolete) / daily_v if daily_v > EPS else None, numerator=stock_v - obsolete,
                     denominator=daily_v, n=n_nodes, breakdown_by="product type",
                     breakdown=[KpiRow(label=k, value=v[0] / v[1] if v[1] > EPS else None, numerator=v[0],
                                       denominator=v[1]) for k, v in sorted(dos_by.items())]))
        self.add(Kpi(id="excess_obsolete", name="Excess & obsolete", unit="ratio", direction="down",
                     definition=f"(Stock with no requirement in the horizon + stock above {self.cfg.excess_cover_days} "
                                "days of requirements) at unit value ÷ total stock value",
                     source="On-hand, the supply plan's requirements, the movement journal (slow-moving)",
                     value=(obsolete + excess) / stock_v if stock_v > EPS else None, numerator=obsolete + excess,
                     denominator=stock_v, n=len(eo_rows), breakdown_by="node",
                     breakdown=sorted(eo_rows, key=lambda r: -(r.value or 0))[:25],
                     note=f"Obsolete {obsolete:,.0f} · excess {excess:,.0f} · slow-moving (no issue or sale for "
                          f"{self.cfg.slow_moving_days} days) {slow:,.0f}, in {ds.settings.currency}."))

    # ---- working capital (inventory turns, DIO, DSO, DPO, cash-to-cash) -----------------------------------------------
    def working_capital(self, plan: PlanResult) -> None:
        """Turns, DIO, DSO, DPO and the cash-to-cash cycle from what the system holds (tower/capital.py): the stock at
        the plan's unit values, averaged over the days of the period from the journal; goods issued to customers (cost
        of goods sold at that value); customer invoices and credit notes with their payments (receivables, counted
        back through the billing for DSO); supplier invoices and credit memos with theirs (payables). Each flow is
        measured over the KPI window, or from its first record when that is later; a flow with less than MIN_DAYS of
        records, or none, gives no value ("not enough data"), never a guessed one. Each has a weekly trend over the
        last TREND_WEEKS weeks, worked out the same way from the records dated before each week's end."""
        ds, as_of = self.ds, self.as_of
        cur = ds.settings.currency
        val = {(n.location, n.product): n.unit_value for n in plan.nodes}
        stock = stocking_on_hand(ds, plan.nodes)
        window = self.cfg.kpi_window_days
        c = capital_at(ds, val, stock, as_of, window, MIN_DAYS)
        win, need = window, c.need
        past = [capital_at(ds, val, stock, as_of - dt.timedelta(weeks=k), window, MIN_DAYS)
                for k in range(TREND_WEEKS - 1, 0, -1)] + [c]

        def trend(get: Callable[[Capital], float | None]) -> list[KpiPoint]:
            return [KpiPoint(as_of=x.as_of, value=None if (v := get(x)) is None else round(v, 4)) for x in past]

        def ageing(age: dict[str, list[float]]) -> list[KpiRow]:
            return [KpiRow(label=b, value=round(age[b][0], 2), numerator=age[b][1]) for b in (*BUCKETS, CREDIT)
                    if b in age]

        def short(what: str, days: int, total: float) -> str:
            if days <= 0:
                return f"Not enough data: no {what} before the planning start."
            if total <= EPS:
                return f"Not enough data: no {what} in the last {win} days."
            return f"Not enough data: {what} only for {days} days; at least {need} are needed."

        def rows(by: dict[str, list[float]], days: int) -> list[KpiRow]:
            return [KpiRow(label=k, value=v[0] / v[1] * days if v[1] > EPS else None, numerator=v[0], denominator=v[1])
                    for k, v in sorted(by.items())]

        cogs, cogs_days, inv = c.cogs, c.cogs_days, c.inv_avg
        cogs_note = (f"Cost of goods sold {cogs:,.0f} {cur} over {cogs_days} days (goods issued to customers at unit "
                     f"value); average stock {inv:,.0f} {cur} over those days (on the planning start "
                     f"{c.inv_close:,.0f} {cur})."
                     + (f" {c.unvalued} goods issue(s) of products without a unit value count as 0." if c.unvalued else ""))
        dio, turns = c.dio, c.turns
        self.add(Kpi(id="inventory_turns", name="Inventory turns", unit="times", direction="up",
                     definition="Cost of goods sold per year ÷ average stock value = (COGS over the period ÷ its days × "
                                "365) ÷ the stock of every day of the period averaged, both at unit value",
                     source="The movement journal (goods issued to customers; every movement for the daily stock) and "
                            "on-hand at the plan's unit values",
                     value=turns, numerator=cogs / cogs_days * 365 if c.cogs_ok else cogs, denominator=inv,
                     n=c.n_sales, trend=trend(lambda x: x.turns),
                     note=cogs_note if turns is not None else
                     short("goods issued to customers", cogs_days, cogs) if not c.cogs_ok else
                     "Not enough data: no stock with a unit value in the period."))
        self.add(Kpi(id="dio", name="Days inventory outstanding (DIO)", unit="days", direction="down",
                     definition="Average stock value ÷ cost of goods sold × days in the period = how many days of sales "
                                "the stock would last at the recent rate",
                     source="The movement journal (the daily stock and goods issued to customers) at unit value",
                     value=dio, numerator=inv, denominator=cogs, n=c.n_sales,
                     breakdown_by="product type" if dio is not None else "",
                     breakdown=rows(c.inv_by, cogs_days) if dio is not None else [], trend=trend(lambda x: x.dio),
                     note=cogs_note if dio is not None else short("goods issued to customers", cogs_days, cogs)))
        dso, ar, billed, ar_days = c.dso, c.ar, c.billed, c.ar_days
        avg = c.dso_average
        self.add(Kpi(id="dso", name="Days sales outstanding (DSO)", unit="days", direction="down",
                     definition="Count-back: what customers still owe on the planning start (invoices less payments, "
                                "less open credit notes) set against the billing of the most recent days, day by day "
                                "back, until it is used up; the days counted are DSO",
                     source="Customer invoices, credit notes and their payments (Selling → Billing)",
                     value=dso, numerator=ar, denominator=billed, n=c.n_inv,
                     breakdown_by="customer" if dso is not None else "",
                     breakdown=[KpiRow(label=k, value=c.dso_of(k), numerator=v[0], denominator=v[1])
                                for k, v in sorted(c.ar_by.items())] if dso is not None else [],
                     trend=trend(lambda x: x.dso), ageing=ageing(c.ar_age),
                     note=(f"Receivables {ar:,.0f} {cur}; billed {billed:,.0f} {cur} over {ar_days} days; by the "
                           f"average of the period {avg:,.1f} days." if dso is not None and avg is not None
                           else short("customer invoices", ar_days, billed))))
        dpo, ap, bought, ap_days = c.dpo, c.ap, c.bought, c.ap_days
        fx_note = (f" {c.foreign} supplier invoice(s) in a currency without an exchange rate are left out."
                   if c.foreign else "")
        self.add(Kpi(id="dpo", name="Days payables outstanding (DPO)", unit="days", direction="none",
                     definition="Payables ÷ purchases billed × days in the period. Payables: what is still owed to "
                                "suppliers on the planning start (invoices and debits less payments, less open credit "
                                "memos); purchases billed: supplier invoices and debits less credit memos in the period, "
                                "with tax, in the company currency",
                     source="Supplier invoices, credit memos and their payments (Buying → Invoices)",
                     value=dpo, numerator=ap, denominator=bought, n=c.n_sup,
                     breakdown_by="supplier" if dpo is not None else "",
                     breakdown=rows(c.ap_by, ap_days) if dpo is not None else [],
                     trend=trend(lambda x: x.dpo), ageing=ageing(c.ap_age),
                     note=(f"Payables {ap:,.0f} {cur}; billed {bought:,.0f} {cur} over {ap_days} days." + fx_note
                           if dpo is not None else short("supplier invoices", ap_days, bought) + fx_note)))
        parts = [("DIO", dio), ("DSO", dso), ("DPO", dpo)]
        missing = [n for n, v in parts if v is None]
        ccc = c.ccc
        self.add(Kpi(id="cash_to_cash", name="Cash-to-cash cycle", unit="days", direction="down",
                     definition="DIO + DSO − DPO: the days between paying suppliers and being paid by customers",
                     source="The three measures above; the trend is each week's end worked out from the records "
                            "before it, at today's unit values",
                     value=ccc, numerator=(dio or 0) + (dso or 0), denominator=dpo or 0, n=3 - len(missing),
                     breakdown_by="measure" if ccc is not None else "",
                     breakdown=[KpiRow(label=n, value=v if n != "DPO" else -v, numerator=v or 0.0)
                                for n, v in parts] if ccc is not None else [],
                     trend=trend(lambda x: x.ccc),
                     note=(f"DIO {dio:,.1f} + DSO {dso:,.1f} − DPO {dpo:,.1f} days." if ccc is not None else
                           f"Not enough data: {', '.join(missing)} {'has' if len(missing) == 1 else 'have'} no value yet.")))

    # ---- plan & process -----------------------------------------------------------------------------
    def stability(self, value: float | None, n: int, matched: int, versus: str, brk: list[KpiRow]) -> None:
        self.add(Kpi(id="plan_stability", name="Plan stability", unit="ratio", direction="up",
                     definition="Planned orders that kept their date and quantity (±1 %) since the previous base plan ÷ "
                                "planned orders due in the overlapping horizon",
                     source=f"Supply plan of the working copy vs {versus}" if versus else "Base versions in the store",
                     value=value, numerator=matched, denominator=n, n=n, breakdown_by="order type", breakdown=brk,
                     note="" if versus else "Save base versions week by week (Versions) to measure stability."))

    def ageing(self, items: list[WorkItem]) -> None:
        live = [i for i in items if i.status in ("open", "acknowledged")]
        by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for i in live:
            by[i.category][0] += i.age_days
            by[i.category][1] += 1
        breached = sum(1 for i in live if i.breached)
        self.add(Kpi(id="exception_ageing", name="Exception ageing", unit="days", direction="down",
                     definition="Average age (planning days since first seen) of open and acknowledged exceptions",
                     source="Control-tower worklist history in the version store",
                     value=sum(i.age_days for i in live) / len(live) if live else None,
                     numerator=sum(i.age_days for i in live), denominator=len(live), n=len(live),
                     breakdown_by="category",
                     breakdown=[KpiRow(label=k, value=v[0] / v[1], numerator=v[0], denominator=v[1])
                                for k, v in sorted(by.items())],
                     note=f"{breached} of {len(live)} past their SLA." if live else "No open exceptions."))

    def cost_to_serve(self, serve: list[ServeRow]) -> None:
        by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in serve:
            by[r.location][0] += r.costs.get("transport", 0.0) + r.costs.get("handling", 0.0)
            by[r.location][1] += r.served
        num = sum(v[0] for v in by.values())
        den = sum(v[1] for v in by.values())
        self.add(Kpi(id="cost_to_serve", name="Cost to serve", unit="money_per_unit", direction="none",
                     definition="Freight + handling pegged to a customer's demand ÷ units served (plan)",
                     source="Finance overlay: plan costs followed along the pegging",
                     value=num / den if den > EPS else None, numerator=num, denominator=den, n=len(serve),
                     breakdown_by="customer",
                     breakdown=[KpiRow(label=k, value=v[0] / v[1] if v[1] > EPS else None, numerator=v[0],
                                       denominator=v[1]) for k, v in sorted(by.items())]))
