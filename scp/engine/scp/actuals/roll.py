"""Roll the plan forward to a new planning start from the goods-movement journal (blueprint P7).

What happened before ``as_of`` becomes the new starting position:

* on-hand at every node with movements = Σ movements before ``as_of`` (stock is derived, never typed);
* firm receipts are reduced by their goods receipts and closed when complete (or marked final); their
  reservations by the component issues / transfer goods issues posted against them;
* sales orders are reduced by their deliveries and closed when complete, their confirmations trimmed;
* elapsed forecast is dropped (period records straddling ``as_of`` keep their remaining share);
* the elapsed weeks are logged as forecast-vs-actual records, and actual sales are appended to history;
* closed orders are logged with due and delivery dates — the source of OTIF and supplier reliability.

Demand dates are delivery dates at the demand location, so a sale shipped to a customer counts on the day
it arrives there (goods issue + the lane's transit): for OTIF, for accuracy weeks and for history.

Every quantity is recomputed from original quantities and the whole journal, so rolling twice to the same
date — or re-rolling after a late posting — gives the same result.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from ..model import (
    ClosedOrder, Dataset, DemandKind, LocationProduct, MovementType, SalesHistory,
)
from .result import OrderChange, RollReport, StockChange
from .stock import (
    EPS, _sum, accuracy_records, arrival, before, by_ref, counterparty, demand_keys, sale_point, stock,
)


def roll_forward(ds: Dataset, as_of: date) -> tuple[Dataset, RollReport]:
    prev = ds.settings.planning_start
    rep = RollReport(ok=False, from_date=prev, to_date=as_of, stock=[], orders=[], closed=[], accuracy=[],
                     forecast_dropped=0.0, forecast_prorated=0, history_added=0, confirmations_trimmed=0, warnings=[])
    if as_of < prev:
        rep.warnings.append(f"Cannot roll back: {as_of.isoformat()} is before the planning start {prev.isoformat()}")
        return ds, rep
    tol = ds.execution.delivery_tolerance
    movs = before(ds, as_of)

    # ① stock ------------------------------------------------------------------------------------------
    lps = [lp.model_copy() for lp in ds.location_products]
    by_key = {(lp.location, lp.product): lp for lp in lps}
    for node, q in sorted(stock(movs).items()):
        lp = by_key.get(node)
        before_q = lp.on_hand if lp else 0.0
        if q < -EPS:
            rep.warnings.append(f"Negative stock {q:,.2f} for {node[1]} at {node[0]}: set to 0 — post the missing receipt "
                                "or a count adjustment")
        after_q = max(0.0, round(q, 6))
        if lp is None:
            lp = LocationProduct(location=node[0], product=node[1])
            lps.append(lp)
            by_key[node] = lp
        lp.on_hand = after_q
        if abs(after_q - before_q) > EPS:
            rep.stock.append(StockChange(location=node[0], product=node[1], before=before_q, after=after_q))

    # ② firm receipts -------------------------------------------------------------------------------------
    got, g_first, g_last, g_final = _sum(movs, {MovementType.RECEIPT})
    iss, *_ = _sum(movs, {MovementType.ISSUE, MovementType.TRANSFER_OUT})
    receipts = []
    for rc in ds.receipts:
        ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
        k = (rc.id, rc.location, rc.product)
        delivered = got.get(k, 0.0)
        open_q = ordered - delivered
        closed = open_q <= ordered * tol + EPS or rc.id in g_final
        if closed:
            rep.closed.append(ClosedOrder(kind=rc.kind.value, id=rc.id, location=rc.location, product=rc.product,
                                          counterparty=counterparty(ds, rc), ordered_qty=ordered, delivered_qty=delivered,
                                          due_date=rc.due_date, first_delivery=g_first.get(k), last_delivery=g_last.get(k),
                                          closed_on=g_last.get(k, as_of)))
        else:
            rvs = []
            for rv in rc.reservations:
                req = rv.required_qty if rv.required_qty is not None else rv.qty
                left = req - by_ref(iss, rc.id, rv.product, rv.location)
                if left > EPS:
                    rvs.append(rv.model_copy(update={"qty": round(left, 6), "required_qty": req}))
            receipts.append(rc.model_copy(update={"qty": round(open_q, 6), "reservations": rvs,
                                                  "ordered_qty": ordered if delivered > EPS else rc.ordered_qty}))
        if closed or delivered > EPS:
            rep.orders.append(OrderChange(kind=rc.kind.value, id=rc.id, location=rc.location, product=rc.product,
                                          open_before=rc.qty, open_after=0.0 if closed else round(open_q, 6), closed=closed))

    # ③ sales orders and ④ elapsed forecast -------------------------------------------------------------------
    sold, s_first, s_last, s_final = _sum(movs, {MovementType.SALE})
    confs = defaultdict(list)
    for c in ds.confirmations:
        confs[c.order].append(c)
    keep_confs = []
    demand = []
    rep.accuracy = accuracy_records(ds, prev, as_of) if as_of > prev else []
    for d in ds.demand:
        if d.kind is DemandKind.FORECAST:
            end = d.date + timedelta(days=d.period_days or 1)
            if end <= as_of:
                rep.forecast_dropped += d.qty
            elif d.date < as_of:
                n = (end - d.date).days
                left = (end - as_of).days
                rep.forecast_dropped += d.qty * (n - left) / n
                rep.forecast_prorated += 1
                demand.append(d.model_copy(update={"date": as_of, "qty": round(d.qty * left / n, 6), "period_days": left}))
            else:
                demand.append(d)
            continue
        if not d.id:
            demand.append(d)
            continue
        ordered = d.ordered_qty if d.ordered_qty is not None else d.qty
        delivered = by_ref(sold, d.id, d.product)
        ks = [k for k in sold if k[0] == d.id and k[2] == d.product]
        first = min((arrival(ds, k[1], d.location, d.product, s_first[k]) for k in ks), default=None)
        last = max((arrival(ds, k[1], d.location, d.product, s_last[k]) for k in ks), default=None)
        open_q = ordered - delivered
        closed = open_q <= ordered * tol + EPS or d.id in s_final
        if closed:
            cf = confs.get(d.id, [])
            rep.closed.append(ClosedOrder(kind="sales", id=d.id, location=d.location, product=d.product,
                                          counterparty=ks[0][1] if ks else None, ordered_qty=ordered,
                                          delivered_qty=delivered, due_date=d.date,
                                          promised_date=max((c.date for c in cf), default=None),
                                          first_delivery=first, last_delivery=last, closed_on=last or as_of))
            rep.confirmations_trimmed += len(cf)
        else:
            demand.append(d.model_copy(update={"qty": round(open_q, 6),
                                               "ordered_qty": ordered if delivered > EPS else d.ordered_qty}))
            # delivered quantity came off the earliest schedule lines
            cut = sum(c.qty for c in confs.get(d.id, [])) - open_q
            for c in sorted(confs.get(d.id, []), key=lambda c: (c.ship_date, c.date)):
                if cut > EPS:
                    take = min(cut, c.qty)
                    cut -= take
                    if c.qty - take <= EPS:
                        rep.confirmations_trimmed += 1
                        continue
                    c = c.model_copy(update={"qty": round(c.qty - take, 6)})
                keep_confs.append(c)
        if closed or delivered > EPS:
            rep.orders.append(OrderChange(kind="sales", id=d.id, location=d.location, product=d.product,
                                          open_before=d.qty, open_after=0.0 if closed else round(open_q, 6), closed=closed))
    keep_confs += [c for c in ds.confirmations if c.order not in {d.id for d in ds.demand if d.id}]

    # ⑤ history ----------------------------------------------------------------------------------------------
    keys = demand_keys(ds)
    have = {(h.location, h.product, h.date) for h in ds.history}
    new_hist: dict[tuple[str, str, date], float] = defaultdict(float)
    for m in ds.movements:
        if m.type is not MovementType.SALE:
            continue
        (loc, prod), day = sale_point(ds, m, keys)
        if prev <= day < as_of and (loc, prod, day) not in have:
            new_hist[(loc, prod, day)] += m.qty
    history = list(ds.history) + [SalesHistory(location=k[0], product=k[1], date=k[2], qty=round(q, 6),
                                               price=(p.price if (p := ds.product_by_id.get(k[1])) else None))
                                  for k, q in sorted(new_hist.items())]
    rep.history_added = len(new_hist)

    logged = {(a.location, a.product, a.start) for a in rep.accuracy}
    acc = [a for a in ds.accuracy if (a.location, a.product, a.start) not in logged] + rep.accuracy
    closed_ids = {(c.kind, c.id) for c in rep.closed}
    closed_log = [c for c in ds.closed_orders if (c.kind, c.id) not in closed_ids] + rep.closed
    new = ds.model_copy(update={
        "settings": ds.settings.model_copy(update={"planning_start": as_of}),
        "location_products": lps, "receipts": receipts, "demand": demand, "confirmations": keep_confs,
        "history": history, "accuracy": acc, "closed_orders": closed_log,
    })
    past_due = [r.id for r in receipts if r.due_date < as_of]
    if past_due:
        rep.warnings.append(f"{len(past_due)} open receipt(s) past due: {', '.join(past_due[:6])}"
                            + ("…" if len(past_due) > 6 else ""))
    rep.ok = True
    return Dataset.model_validate(new.model_dump()), rep
