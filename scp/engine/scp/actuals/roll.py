"""Roll the plan forward to a new planning start from the goods-movement journal (blueprint P7).

What happened before ``as_of`` becomes the new starting position:

* on-hand at every node with movements = Σ movements before ``as_of`` (stock is derived, never typed); stock
  typed at setup at a place with no earlier movement is written into the journal as its opening balance first;
* firm receipts are reduced by their goods receipts and closed when complete (or marked final); their
  reservations by the component issues / transfer goods issues posted against them;
* sales orders are reduced by their deliveries and closed when complete, their confirmations trimmed;
* elapsed forecast is dropped (period records straddling ``as_of`` keep their remaining share);
* the elapsed weeks are logged as forecast-vs-actual records, and actual sales are appended to history;
* closed orders are logged with due and delivery dates — the source of OTIF and supplier reliability.

Demand dates are delivery dates at the demand location, so a sale shipped to a customer counts on the day
it arrives there (goods issue + the lane's transit): for OTIF, for accuracy weeks and for history.

Every quantity is recomputed from original quantities and the whole journal, so rolling twice to the same
date — or re-rolling after a late posting — gives the same result. That holds for what earlier rolls wrote
too: a movement posted late for a day before the current start still reaches the stock, the history, the
logged accuracy weeks and the closed-order log on the next roll.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from ..model import (
    ClosedOrder, Dataset, DemandKind, GoodsMovement, LocationProduct, MovementType, NegativeStock, RolledWeek,
    SalesHistory, StockType,
)
from .lots import batch_index, lots, planning_stock
from .result import OrderChange, RollReport, StockChange
from .stock import (
    EPS, _sum, accuracy_records, arrival, before, by_ref, counterparty, demand_keys, pending_openings, refresh_actuals,
    sale_point, stock, week_grid,
)


def roll_forward(ds: Dataset, as_of: date) -> tuple[Dataset, RollReport]:
    prev = ds.settings.planning_start
    rep = RollReport(ok=False, from_date=prev, to_date=as_of, stock=[], orders=[], closed=[], accuracy=[],
                     forecast_dropped=0.0, forecast_prorated=0, history_added=0, confirmations_trimmed=0, warnings=[])
    if as_of < prev:
        rep.warnings.append(f"Cannot roll back: {as_of.isoformat()} is before the planning start {prev.isoformat()}")
        return ds, rep
    tol = ds.execution.delivery_tolerance
    openings = pending_openings(ds)          # setup stock enters the journal as the opening balance
    found = _found(ds, openings, as_of)      # the company counts stock below zero as found (R17)
    if found:
        ds = ds.model_copy(update={"movements": [*ds.movements, *found]})
    movs = before(ds, as_of)

    # ① stock: what planning may count on (unrestricted and unexpired, and in inspection if the company says so) --
    lps = [lp.model_copy() for lp in ds.location_products]
    by_key = {(lp.location, lp.product): lp for lp in lps}
    usable_now = planning_stock(ds, movs, as_of)
    free = unrestricted(movs)
    for m in found:
        rep.warnings.append(f"{m.qty:,.2f} of {m.product} at {m.location} counted as found: stock had gone below zero "
                            "(the company's rule)")
    for node in sorted(set(stock(movs)) | set(usable_now)):
        q = usable_now.get(node, 0.0)
        lp = by_key.get(node)
        before_q = lp.on_hand if lp else 0.0
        if free.get(node, 0.0) < -EPS:
            rep.warnings.append(f"Negative stock {free[node]:,.2f} for {node[1]} at {node[0]} by the journal: the plan "
                                "starts from 0 — post the missing receipt, or count it")
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
        # a purchase closes at the supplier's under-delivery tolerance, or once what they confirmed (if less) is in
        line_tol = max(tol, ds.vendor(counterparty(ds, rc) or "").under_delivery_tolerance) \
            if rc.kind.value == "purchase" else tol
        target = min(ordered, rc.confirmed_qty) if rc.confirmed_qty is not None and delivered > EPS else ordered
        closed = open_q <= ordered * line_tol + EPS or rc.id in g_final or delivered >= target - EPS > 0
        if closed:
            rep.closed.append(ClosedOrder(kind=rc.kind.value, id=rc.id, location=rc.location, product=rc.product,
                                          counterparty=counterparty(ds, rc), ordered_qty=ordered, delivered_qty=delivered,
                                          due_date=rc.due_date, first_delivery=g_first.get(k), last_delivery=g_last.get(k),
                                          closed_on=g_last.get(k, as_of), po=rc.po, price=rc.price,
                                          confirmed_date=rc.confirmed_date))
        else:
            rvs = []
            for rv in rc.reservations:
                req = rv.required_qty if rv.required_qty is not None else rv.qty
                left = req - by_ref(iss, rc.id, rv.product, rv.location)
                if left > EPS:
                    rvs.append(rv.model_copy(update={"qty": round(left, 6), "required_qty": req}))
            # nothing received: the quantity is the order's own, unrounded, so the next roll starts from it
            receipts.append(rc.model_copy(update={"qty": round(open_q, 6) if delivered > EPS else open_q, "reservations": rvs,
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
            demand.append(d.model_copy(update={"qty": round(open_q, 6) if delivered > EPS else open_q,
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

    # ⑤ history: every journal sale before as_of on the day it arrives, rebuilt from the whole journal so a late
    # posting for an earlier day lands; imported history is kept as it is and wins on a day it covers ---------
    keys = demand_keys(ds)
    imported = [h for h in ds.history if not h.from_journal]
    have = {(h.location, h.product, h.date) for h in imported}
    was = {(h.location, h.product, h.date): h.qty for h in ds.history if h.from_journal}
    journal: dict[tuple[str, str, date], float] = defaultdict(float)
    for m in ds.movements:
        if m.type is not MovementType.SALE:
            continue
        (loc, prod), day = sale_point(ds, m, keys)
        if day < as_of and (loc, prod, day) not in have:
            journal[(loc, prod, day)] += m.net
    history = imported + [SalesHistory(location=k[0], product=k[1], date=k[2], qty=round(q, 6),
                                       price=ds.selling_price(k[0], k[1]), from_journal=True)
                          for k, q in sorted(journal.items())]
    rep.history_added = sum(1 for k, q in journal.items() if abs(was.get(k, 0.0) - round(q, 6)) > EPS)

    # ⑥ the logs: earlier weeks and closed orders re-read from the journal ---------------------------------
    now = set(week_grid(prev, as_of))
    rolled_before = {(w.start, w.end) for w in ds.rolled_weeks}
    earlier = sorted(rolled_before - now)
    # weeks logged before the journal began (imported with the history) are kept as they came: the journal has no
    # sales for them, so re-reading them would wipe their actuals
    imported_acc = [a for a in ds.accuracy if (a.start, a.end) not in rolled_before and (a.start, a.end) not in now]
    acc = sorted(imported_acc + refresh_actuals(ds, [a for a in ds.accuracy if (a.start, a.end) in rolled_before
                                                     and (a.start, a.end) not in now], earlier) + rep.accuracy,
                 key=lambda a: (a.start, a.location, a.product))
    rolled = [RolledWeek(start=w, end=we) for w, we in sorted(set(earlier) | now)]
    closed_ids = {(c.kind, c.id) for c in rep.closed}
    referenced = {m.reference for m in ds.movements if m.reference}
    closed_log = [_redeliver(ds, c, (got, g_first, g_last), (sold, s_first, s_last), referenced)
                  for c in ds.closed_orders if (c.kind, c.id) not in closed_ids] + rep.closed
    closed_log.sort(key=lambda c: (c.closed_on, c.kind, c.id))   # one order however many rolls it took
    new = ds.model_copy(update={
        "settings": ds.settings.model_copy(update={"planning_start": as_of}),
        "location_products": lps, "receipts": receipts, "demand": demand, "confirmations": keep_confs,
        "history": history, "accuracy": acc, "rolled_weeks": rolled, "closed_orders": closed_log,
        "movements": [*ds.movements, *openings],          # the found stock is in ds.movements already
    })
    gone = expired_now(ds, movs, as_of)
    if gone:
        rep.warnings.append(f"{len(gone)} batch{'es' if len(gone) != 1 else ''} expired and no longer counted: "
                            + ", ".join(f"{b} of {p} at {lo} ({q:,.2f})" for lo, p, b, q in gone[:4])
                            + ("…" if len(gone) > 4 else "") + " — scrap them")
    past_due = [r.id for r in receipts if r.due_date < as_of]
    if past_due:
        rep.warnings.append(f"{len(past_due)} open receipt(s) past due: {', '.join(past_due[:6])}"
                            + ("…" if len(past_due) > 6 else ""))
    rep.ok = True
    return Dataset.model_validate(new.model_dump()), rep


def unrestricted(movs) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = defaultdict(float)
    for m in movs:
        if m.stock_type is StockType.UNRESTRICTED:
            out[(m.location, m.product)] += m.signed
    return out


def _found(ds: Dataset, openings: list[GoodsMovement], as_of: date) -> list[GoodsMovement]:
    """With the rule "count it as found", a count difference that brings unrestricted stock below zero back to zero,
    on the day before ``as_of``: the journal and the plan then agree without waiting for a count."""
    if NegativeStock(ds.execution.negative_stock) is not NegativeStock.FOUND:
        return []
    from .stock import movement_ids
    movs = [m for m in [*ds.movements, *openings] if m.date < as_of]
    ids = movement_ids(ds, [m.id for m in openings])
    day = as_of - timedelta(days=1)
    return [GoodsMovement(id=next(ids), date=day, type=MovementType.ADJUSTMENT, location=n[0], product=n[1],
                          qty=round(-q, 6), note="Counted as found: stock had gone below zero")
            for n, q in sorted(unrestricted(movs).items()) if q < -EPS]


def expired_now(ds: Dataset, movs, as_of: date) -> list[tuple[str, str, str, float]]:
    """Batches holding stock that is past its last day on ``as_of`` (blocked stock aside): place, product, batch, qty."""
    bi = batch_index(ds)
    out = []
    for (loc, prod), by in sorted(lots(movs).items()):
        for (b, t), q in sorted(by.items(), key=lambda kv: (kv[0][0] or "", kv[0][1].value)):
            rec = bi.get((prod, b)) if b else None
            if rec and rec.expires_on and rec.expires_on < as_of and q > EPS and t is not StockType.BLOCKED:
                out.append((loc, prod, b, round(q, 6)))
    return out


def _redeliver(ds: Dataset, c: ClosedOrder, receipts: tuple[dict, dict, dict], sales: tuple[dict, dict, dict],
               referenced: set[str]) -> ClosedOrder:
    """A closed order's deliveries as the journal now has them (a late posting may add one). An order the journal has
    no movement for (closed before the journal began, imported with the log) is kept as it came."""
    if c.id not in referenced:
        return c
    if c.kind == "sales":
        sold, first, last = sales
        ks = [k for k in sold if k[0] == c.id and k[2] == c.product]
        delivered = by_ref(sold, c.id, c.product)
        lo = min((arrival(ds, k[1], c.location, c.product, first[k]) for k in ks), default=None)
        hi = max((arrival(ds, k[1], c.location, c.product, last[k]) for k in ks), default=None)
    else:
        got, first, last = receipts
        k = (c.id, c.location, c.product)
        delivered, lo, hi = got.get(k, 0.0), first.get(k), last.get(k)
    if abs(delivered - c.delivered_qty) <= EPS:
        return c
    return c.model_copy(update={"delivered_qty": delivered, "first_delivery": lo, "last_delivery": hi,
                                "closed_on": hi or c.closed_on})
