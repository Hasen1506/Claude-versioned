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
from .result import Kpi, KpiRow, WorkItem

EPS = 1e-9
OUTBOUND = {MovementType.ISSUE, MovementType.SALE, MovementType.TRANSFER_OUT}


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
        self.closed = [c for c in ds.closed_orders if self.since <= c.closed_on <= self.as_of]
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
            if c.kind == "sales" and c.promised_date is not None:
                rows.append((c.location, c.ordered_qty, c.ordered_qty if c.promised_date <= c.due_date else 0.0))
        conf: dict[str, list] = defaultdict(list)
        for cf in self.ds.confirmations:
            conf[cf.order].append(cf)
        for d in self.ds.demand:
            if d.kind.value == "sales_order" and d.id in conf:
                on = sum(cf.qty for cf in conf[d.id] if cf.date <= d.date)
                rows.append((d.location, d.qty, min(on, d.qty)))
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
                     source="Closed-order log (deliveries vs last confirmed date)", value=v, numerator=num,
                     denominator=den, n=len(conf), breakdown_by="customer", breakdown=brk,
                     note="" if conf else "No closed, confirmed sales orders in the window yet."))
        v, num, den, brk = self._share(sales, lambda c: self._in_full(c) and on_time(c, c.due_date), lambda c: 1.0,
                                       lambda c: c.location)
        self.add(Kpi(id="otif_requested", name="OTIF to requested date", unit="ratio", direction="up",
                     definition="Sales orders delivered in full by the customer's requested date ÷ orders closed in "
                                "the window", source="Closed-order log (deliveries vs requested date)", value=v,
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
        v, num, den, brk = self._share(
            mos, lambda c: c.last_delivery is not None and week(c.last_delivery) == week(c.due_date),
            lambda c: 1.0, lambda c: c.location)
        self.add(Kpi(id="schedule_adherence", name="Schedule adherence", unit="ratio", direction="up",
                     definition="Production orders finished in their planned week (neither early nor late) ÷ "
                                "production orders closed in the window",
                     source="Closed-order log (last goods receipt vs due date)", value=v, numerator=num,
                     denominator=den, n=len(mos), breakdown_by="plant", breakdown=brk,
                     note="" if mos else "No production orders closed in the window yet."))

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
