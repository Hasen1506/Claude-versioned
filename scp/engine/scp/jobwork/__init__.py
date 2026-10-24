"""Job work (Enterprise 7.1, S/4 guide §10.1 subcontracting): a production order's parts sent to a job worker who does
the work and sends the goods back.

* **Send** (≈ components provided to the vendor, movement 541; GST: the delivery challan of rule 55 for goods sent
  under section 143). The parts leave the plant as issues to the production order, so the order's backflush does
  not take them again; the challan holds them as stock at the job worker, at their planned value when they left.
  By default it sends what the bill of materials needs for what is left to make, less what is already out there.
* **Back processed** (≈ the subcontracting receipt, 101 with 543): the order's goods come back and are received on
  the order. The parts the bill of materials says they took are used up at the job worker; any other part of the
  order (one the plant adds) is backflushed at the plant as usual. The job charge per unit is then due: the job
  worker's invoice is entered against the challan in Buying's invoices and matched like an order line.
* **Back unused** takes the issue back for that much: the parts are in plant stock again. **Written off** records
  parts the job worker spoiled or lost (they stay used up on the order).
* **Deadlines** (section 143): inputs not back within a year, capital goods (moulds, dies, tools) within three, count
  as supplied to the job worker on the day they were sent: tax is due on their value. The view names challans close
  to their limit and what is past it, with the tax.
* **ITC-04**: what was sent (table 4) and what came back (table 5A) in a return period, as the GST return asks.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from ..model import Dataset, GoodsMovement, LocationType, MovementType, ReceiptKind, ScheduledReceipt
from ..model.common import Out
from ..model.outside import ChallanLine, ChallanReturn, JobWorkChallan

EPS = 1e-6
_UQC = {"KG": "KGS", "G": "GMS", "T": "TON", "L": "LTR", "ML": "MLT", "M": "MTR", "EA": "NOS", "PC": "PCS",
        "PCS": "PCS", "NOS": "NOS", "BOX": "BOX", "SET": "SET", "PAIR": "PRS", "ROLL": "ROL", "BAG": "BAG"}


class JobWorkError(ValueError):
    """A step the data does not allow; the message says why in plain words."""


def _name(ds: Dataset, oid: str) -> str:
    x = ds.location_by_id.get(oid) or ds.product_by_id.get(oid)
    return (x.name or oid) if x else oid


def _n(q: float) -> str:
    return f"{q:,.0f}" if abs(q - round(q)) < 1e-6 else f"{q:,.2f}"


def _qty(ds: Dataset, product: str, q: float) -> str:
    p = ds.product_by_id.get(product)
    unit = (p.base_uom if p else "EA").lower()
    return f"{_n(q)} {unit + ' ' if unit not in ('ea', 'pc', 'pcs', 'nos') else ''}{_name(ds, product)}"


def _money(ds: Dataset, v: float) -> str:
    return f"{ds.settings.currency} {v:,.2f}"


def _day(d: date) -> str:
    return d.strftime("%a %d %b %Y").replace(" 0", " ")


def _today(ds: Dataset, on: date | None) -> date:
    return on or ds.settings.planning_start


def uqc(ds: Dataset, product: str) -> str:
    """The GST unit quantity code of the product's unit."""
    p = ds.product_by_id.get(product)
    u = (p.base_uom if p else "EA").upper()
    return _UQC.get(u, "OTH")


def _next_id(ds: Dataset) -> str:
    n = max((int(c.id[3:]) for c in ds.challans if c.id.startswith("JW-") and c.id[3:].isdigit()), default=0)
    return f"JW-{n + 1:05d}"


def _challan(ds: Dataset, cid: str) -> JobWorkChallan:
    c = next((c for c in ds.challans if c.id == cid), None)
    if c is None:
        raise JobWorkError(f"there is no job-work challan {cid}")
    return c


def _put(ds: Dataset, c: JobWorkChallan) -> Dataset:
    return ds.model_copy(update={"challans": [c if x.id == c.id else x for x in ds.challans]})


def _order(ds: Dataset, oid: str) -> ScheduledReceipt:
    rc = next((r for r in ds.receipts if r.id == oid), None)
    if rc is None or rc.kind is not ReceiptKind.PRODUCTION:
        raise JobWorkError(f"{oid} is not an open production order")
    return rc


def order_product(ds: Dataset, oid: str) -> str | None:
    """The product an order makes, open or closed."""
    rc = next((r for r in ds.receipts if r.id == oid), None)
    if rc is not None:
        return rc.product
    c = next((c for c in ds.closed_orders if c.id == oid), None)
    return c.product if c else None


def _outside_op(ds: Dataset, rc: ScheduledReceipt):
    ps = ds.production_source_by_id.get(rc.source or "")
    return next((op.subcontract for op in sorted(ps.operations, key=lambda o: o.seq) if op.subcontract), None) \
        if ps else None


def _needs(ds: Dataset, rc: ScheduledReceipt) -> dict:
    from ..plan.structure import needs
    ps = ds.production_source_by_id.get(rc.source or "")
    if ps is None:
        return {}
    ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
    return {n.product: n for n in needs(ds, ps, rc.start_date or ds.settings.planning_start, qty=ordered)}


def _made(ds: Dataset, oid: str, product: str) -> float:
    return sum(m.net for m in ds.movements if m.reference == oid and m.type is MovementType.RECEIPT
               and m.product == product)


def _part_location(ds: Dataset, rc: ScheduledReceipt, product: str) -> str:
    rv = next((r for r in rc.reservations if r.product == product), None)
    if rv is not None:
        return rv.location
    n = _needs(ds, rc).get(product)
    return (n.location if n is not None and n.location else None) or rc.location


def _out_there(ds: Dataset, order: str) -> dict[str, float]:
    """Parts of the order at job workers now, over its open challans."""
    out: dict[str, float] = defaultdict(float)
    for c in ds.challans:
        if c.order == order and not c.cancelled:
            for ln in c.lines:
                out[ln.product] += c.at_job_worker(ln.product)
    return out


def parts_to_send(ds: Dataset, order: str) -> list[dict]:
    """What the order's bill of materials needs for what is left to make, less what is already at job workers."""
    rc = _order(ds, order)
    ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
    made = _made(ds, order, rc.product)
    left = max(0.0, ordered - made)
    there = _out_there(ds, order)
    out = []
    for p, n in _needs(ds, rc).items():
        q = n.per_unit * left + (n.per_order if made <= EPS else 0.0) - there.get(p, 0.0)
        if ds.whole(p):
            q = math.ceil(q - 1e-6)
        if q > EPS:
            out.append({"product": p, "qty": round(q, 6), "location": n.location or _part_location(ds, rc, p)})
    return out


def _unit_values(ds: Dataset) -> dict:
    from ..actuals.valuation import standards
    return standards(ds)


def _value(ds: Dataset, std: dict, loc: str, product: str) -> float:
    v = std.get((loc, product))
    if v is None:
        p = ds.product_by_id.get(product)
        v = (p.standard_cost if p and p.standard_cost is not None else 0.0)
    return round(float(v), 4)


def due_date(ds: Dataset, c: JobWorkChallan, ln: ChallanLine) -> date:
    jw = ds.job_work
    return c.sent_on + timedelta(days=jw.capital_goods_days if ln.capital_goods else jw.inputs_days)


class JobWorkReport(Out):
    message: str
    challan: str | None = None
    movements: list[str] = []
    doc: str | None = None


# ------------------------------------------------------------------------------------------------ steps
def send(ds: Dataset, order: str, job_worker: str | None = None, lines: list[dict] | None = None, *,
         on: date | None = None, charge: float | None = None, vehicle: str = "", note: str = "",
         challan_id: str | None = None) -> tuple[Dataset, JobWorkReport]:
    """Send the order's parts to a job worker on a challan. ``lines``: ``[{"product", "qty", "capital_goods"?,
    "location"?}]``; empty: :func:`parts_to_send`. ``job_worker`` and ``charge`` default to the routing's outside
    step."""
    from ..actuals.post import PostingError, _complete
    from ..actuals.stock import movement_ids
    rc = _order(ds, order)
    sub = _outside_op(ds, rc)
    jw = job_worker or (sub.supplier if sub else None)
    if not jw:
        raise JobWorkError(f"say which job worker {order} goes to: its routing has no step done outside")
    lo = ds.location_by_id.get(jw)
    if lo is None or lo.type is not LocationType.SUPPLIER:
        raise JobWorkError(f"{jw} is not a supplier")
    if ds.vendor(jw).blocked:
        raise JobWorkError(f"{_name(ds, jw)} is blocked for purchasing")
    cid = (challan_id or _next_id(ds)).strip()
    if not cid or len(cid) > 16:
        raise JobWorkError("a challan number has 1 to 16 characters")
    if any(c.id == cid for c in ds.challans):
        raise JobWorkError(f"challan {cid} already exists")
    want = lines if lines else parts_to_send(ds, order)
    if not want:
        raise JobWorkError(f"{order} needs no more parts: everything is made or already at a job worker")
    day = _today(ds, on)
    rate = charge if charge is not None else (sub.cost_per_unit if sub else 0.0)
    if not math.isfinite(rate) or rate < 0:
        raise JobWorkError("the job charge cannot be negative")
    std = _unit_values(ds)
    ids = movement_ids(ds)
    moves: list[GoodsMovement] = []
    plan: list[tuple[str, str, float, bool]] = []
    seen: set[str] = set()
    for w in want:
        p = str(w.get("product") or "")
        if p not in ds.product_by_id:
            raise JobWorkError(f"{p or 'a line'} is not a product")
        if p in seen:
            raise JobWorkError(f"{_name(ds, p)} is on the challan twice")
        seen.add(p)
        q = float(w.get("qty") or 0)
        if not math.isfinite(q) or q <= EPS:
            raise JobWorkError(f"{_name(ds, p)}: the quantity sent must be more than 0")
        loc = str(w.get("location") or _part_location(ds, rc, p))
        plan.append((p, loc, round(q, 6), bool(w.get("capital_goods"))))
        moves.append(GoodsMovement(id=next(ids), date=day, type=MovementType.ISSUE, location=loc, product=p,
                                   qty=round(q, 6), reference=order, counterparty=jw,
                                   note=f"Sent to {_name(ds, jw)} on challan {cid}"[:200]))
    try:
        moves, _, notes = _complete(ds, moves, day, None)
    except PostingError as e:
        raise JobWorkError(str(e)) from e
    got = []
    for p, loc, q, cap in plan:
        got.append(ChallanLine(product=p, qty=q, value=_value(ds, std, loc, p), capital_goods=cap, location=loc,
                               movements=[m.id for m in moves if m.product == p and m.location == loc]))
    c = JobWorkChallan(id=cid, job_worker=jw, ship_from=rc.location, order=order, sent_on=day, lines=got,
                       charge=round(rate, 4), vehicle=vehicle[:40], note=note[:400])
    total = sum(x.qty * x.value for x in got)
    first_due = min(due_date(ds, c, x) for x in got)
    what = ", ".join(_qty(ds, x.product, x.qty) for x in got[:4]) + (f" and {len(got) - 4} more" if len(got) > 4
                                                                       else "")
    msg = (f"Challan {cid}: {what} sent to {_name(ds, jw)} for {order} on {_day(day)}, worth {_money(ds, total)}. "
           f"Back by {_day(first_due)}, or they count as supplied to the job worker (GST section 143). Print it in "
           "three copies: the original goes with the goods, the duplicate with the transporter, the triplicate "
           "stays here." + (" " + "; ".join(notes) + "." if notes else ""))
    return (ds.model_copy(update={"movements": [*ds.movements, *moves], "challans": [*ds.challans, c]}),
            JobWorkReport(message=msg, challan=cid, movements=[m.id for m in moves], doc=moves[0].doc))


def _open(ds: Dataset, cid: str) -> JobWorkChallan:
    c = _challan(ds, cid)
    if c.cancelled:
        raise JobWorkError(f"{cid} is cancelled")
    if c.closed_on is not None:
        raise JobWorkError(f"{cid} is closed")
    return c


def _with_return(c: JobWorkChallan, r: ChallanReturn, day: date) -> JobWorkChallan:
    new = c.model_copy(update={"returns": [*c.returns, r]})
    if all(new.at_job_worker(x.product) <= EPS for x in new.lines):
        new = new.model_copy(update={"closed_on": day})
    return new


def _left(ds: Dataset, c: JobWorkChallan) -> str:
    rest = [(x.product, c.at_job_worker(x.product)) for x in c.lines]
    rest = [(p, q) for p, q in rest if q > EPS]
    if not rest:
        return f"nothing is left at {_name(ds, c.job_worker)}: {c.id} is closed"
    return f"still at {_name(ds, c.job_worker)}: " + ", ".join(_qty(ds, p, q) for p, q in rest)


def receive(ds: Dataset, cid: str, qty: float, *, on: date | None = None, reference: str = "", final: bool = False,
            post: bool = True, used: dict[str, float] | None = None) -> tuple[Dataset, JobWorkReport]:
    """The order's goods back from the job worker: the parts they took are used up there, and (``post``) the goods
    are received on the order, its other parts backflushed at the plant. ``used``: the parts the job worker says
    they used, instead of what the bill of materials says. When the order is done, less than one unit left of a part
    counted in whole units is used up too (the bill's fractions rounded)."""
    from ..actuals.post import PostingError, _posted, _production_parts
    from ..actuals.post import receive as receive_order
    c = _open(ds, cid)
    q = float(qty)
    if not math.isfinite(q) or q <= EPS:
        raise JobWorkError("the quantity back must be more than 0")
    rc = next((r for r in ds.receipts if r.id == c.order and r.kind is ReceiptKind.PRODUCTION), None)
    if rc is None and post:
        raise JobWorkError(f"{c.order} is no longer open: record the goods without receiving them on it")
    day = _today(ds, on)
    first = c.processed <= EPS
    need = _needs(ds, rc) if rc is not None else {}
    said = used or {}
    unknown = [p for p in said if not any(x.product == p for x in c.lines)]
    if unknown:
        raise JobWorkError(f"{_name(ds, unknown[0])} is not on {cid}")
    ordered = (rc.ordered_qty if rc.ordered_qty is not None else rc.qty) if rc is not None else 0.0
    done = final or (rc is not None and _made(ds, rc.id, rc.product) + q >= ordered - EPS)
    took: dict[str, float] = {}
    over: list[str] = []
    for ln in c.lines:
        have = c.at_job_worker(ln.product)
        if ln.product in said:
            want = float(said[ln.product])
            if not math.isfinite(want) or want < 0:
                raise JobWorkError(f"{_name(ds, ln.product)}: the quantity used cannot be negative")
        else:
            n = need.get(ln.product)
            if n is None:
                continue                   # a tool or a mould: it comes back
            want = n.per_unit * q + (n.per_order if first else 0.0)
            if done and ds.whole(ln.product) and 0 < have - want < 1 - EPS:
                want = have                # the bill's fraction of a whole part
        if want > have + EPS:
            over.append(f"{_qty(ds, ln.product, want - have)} more than was sent")
        take = min(want, have)
        if take > EPS:
            took[ln.product] = round(take, 6)
    movements: list[str] = []
    doc = None
    tail = ""
    new_ds = ds
    if post and rc is not None:
        got, _, issued = _posted(ds, rc.id)
        before_q = got[(rc.location, rc.product)]
        parts, _ = _production_parts(ds, rc, before_q + q, q, before_q, issued)
        on_challan = {x.product for x in c.lines}
        usage = [{"product": p, "qty": round(n, 6)} for _loc, p, n in parts if p not in on_challan]
        try:
            new_ds, rep = receive_order(ds, rc.id, q, day, final=final, usage=usage,
                                        note=f"Back from {_name(ds, c.job_worker)} on challan {cid}")
        except PostingError as e:
            raise JobWorkError(str(e)) from e
        movements, doc = rep.movements, rep.doc
        tail = " " + rep.message.split(". Stock and the order")[0] + "."
    made = rc.product if rc is not None else (order_product(ds, c.order) or c.lines[0].product)
    r = ChallanReturn(date=day, kind="processed", product=made, qty=round(q, 6), reference=reference[:64],
                      movements=movements, used=took)
    new = _with_return(c, r, day)
    use = ", ".join(_qty(ds, p, n) for p, n in took.items()) or "no parts on the challan"
    msg = (f"{cid}: {_qty(ds, r.product, q)} back from {_name(ds, c.job_worker)} on {_day(day)}"
           + (f" (their {reference})" if reference else "") + f", made from {use}"
           + (f"; they used {'; '.join(over)}: put the challan right with what really came back" if over else "")
           + f"; {_left(ds, new)}." + tail
           + (f" Job charge {_money(ds, c.charge * q)} due: enter their invoice against {cid}." if c.charge else ""))
    return _put(new_ds, new), JobWorkReport(message=msg, challan=cid, movements=movements, doc=doc)


def _issues_left(ds: Dataset, c: JobWorkChallan, ln: ChallanLine) -> list[tuple[GoodsMovement, float]]:
    """The challan's issues of a part with what is not taken back yet, the latest first."""
    back: dict[str, float] = defaultdict(float)
    for m in ds.movements:
        if m.reversal_of:
            back[m.reversal_of] += m.qty
    out = []
    for m in ds.movements:
        if m.id in ln.movements and not m.reversal_of:
            left = m.qty - back.get(m.id, 0.0)
            if left > EPS:
                out.append((m, left))
    return sorted(out, key=lambda x: (x[0].date, x[0].id), reverse=True)


def _take_back(ds: Dataset, c: JobWorkChallan, ln: ChallanLine, q: float, day: date, text: str) -> list[GoodsMovement]:
    from ..actuals.documents import next_doc
    from ..actuals.stock import movement_ids
    ids = movement_ids(ds)
    doc = next_doc(ds)
    out, left = [], q
    for m, free in _issues_left(ds, c, ln):
        if left <= EPS:
            break
        take = min(left, free)
        left -= take
        out.append(m.model_copy(update={"id": next(ids), "date": day, "qty": round(take, 6), "reversal_of": m.id,
                                        "final": False, "doc": doc, "note": text[:200]}))
    if left > EPS:
        raise JobWorkError(f"only {_qty(ds, ln.product, q - left)} of the issue on {c.id} can be taken back")
    return out


def return_unused(ds: Dataset, cid: str, product: str, qty: float | None = None, *, on: date | None = None,
                  reference: str = "") -> tuple[Dataset, JobWorkReport]:
    """Parts back from the job worker as they were sent: the issue is taken back for that much, so they are plant
    stock again and the order's backflush may take them."""
    from ..actuals.documents import blocked_by_count
    c = _open(ds, cid)
    ln = next((x for x in c.lines if x.product == product), None)
    if ln is None:
        raise JobWorkError(f"{_name(ds, product)} is not on {cid}")
    there = c.at_job_worker(product)
    q = there if qty is None else float(qty)
    if not math.isfinite(q) or q <= EPS:
        raise JobWorkError(f"no {_name(ds, product)} of {cid} is at the job worker" if qty is None
                           else "the quantity back must be more than 0")
    if q > there + EPS:
        raise JobWorkError(f"only {_qty(ds, product, there)} of {cid} is at {_name(ds, c.job_worker)}")
    if (inv := blocked_by_count(ds, (ln.location, product))) is not None:
        raise JobWorkError(f"{_name(ds, product)} at {_name(ds, ln.location)} is being counted ({inv.id}): post the "
                           "count first, or cancel it")
    day = _today(ds, on)
    moves = _take_back(ds, c, ln, q, day, f"Back unused from {_name(ds, c.job_worker)} on challan {cid}")
    r = ChallanReturn(date=day, kind="unused", product=product, qty=round(q, 6), reference=reference[:64],
                      movements=[m.id for m in moves])
    new = _with_return(c, r, day)
    msg = (f"{cid}: {_qty(ds, product, q)} back unused from {_name(ds, c.job_worker)} on {_day(day)}"
           + (f" (their {reference})" if reference else "") + f", in stock at {_name(ds, ln.location)} again; "
           + _left(ds, new) + ".")
    return (_put(ds.model_copy(update={"movements": [*ds.movements, *moves]}), new),
            JobWorkReport(message=msg, challan=cid, movements=[m.id for m in moves], doc=moves[0].doc))


def write_off(ds: Dataset, cid: str, product: str, qty: float | None = None, *, on: date | None = None,
              reference: str = "") -> tuple[Dataset, JobWorkReport]:
    """Parts the job worker spoiled or lost: they stay used up on the order and leave the job worker's stock."""
    c = _open(ds, cid)
    if not any(x.product == product for x in c.lines):
        raise JobWorkError(f"{_name(ds, product)} is not on {cid}")
    there = c.at_job_worker(product)
    q = there if qty is None else float(qty)
    if not math.isfinite(q) or q <= EPS:
        raise JobWorkError(f"no {_name(ds, product)} of {cid} is at the job worker" if qty is None
                           else "the quantity written off must be more than 0")
    if q > there + EPS:
        raise JobWorkError(f"only {_qty(ds, product, there)} of {cid} is at {_name(ds, c.job_worker)}")
    day = _today(ds, on)
    r = ChallanReturn(date=day, kind="lost", product=product, qty=round(q, 6), reference=reference[:64])
    new = _with_return(c, r, day)
    msg = (f"{cid}: {_qty(ds, product, q)} written off at {_name(ds, c.job_worker)} on {_day(day)}"
           + (f" ({reference})" if reference else "") + "; the order carries them as used. Recover them from the "
           f"job worker or tax them as supplied to them; {_left(ds, new)}.")
    return _put(ds, new), JobWorkReport(message=msg, challan=cid)


def cancel(ds: Dataset, cid: str, on: date | None = None) -> tuple[Dataset, JobWorkReport]:
    """Call the challan off before anything came back: every part is taken back into plant stock."""
    c = _challan(ds, cid)
    if c.cancelled:
        raise JobWorkError(f"{cid} is already cancelled")
    if c.returns:
        raise JobWorkError(f"goods have come back on {cid}: take back the rest as unused instead")
    day = _today(ds, on)
    moves: list[GoodsMovement] = []
    work = ds
    for ln in c.lines:
        got = _take_back(work, c, ln, ln.qty, day, f"Challan {cid} cancelled")
        moves += got
        work = work.model_copy(update={"movements": [*work.movements, *got]})
    if moves:
        doc = moves[0].doc
        moves = [m.model_copy(update={"doc": doc}) for m in moves]
    new = c.model_copy(update={"cancelled": True, "closed_on": day})
    return (_put(ds.model_copy(update={"movements": [*ds.movements, *moves]}), new),
            JobWorkReport(message=f"{cid} cancelled: its parts are back in stock at {_name(ds, c.ship_from)}.",
                          challan=cid, movements=[m.id for m in moves], doc=moves[0].doc if moves else None))


# ------------------------------------------------------------------------------------------------ view
class ChallanLineRow(Out):
    product: str
    product_name: str
    hsn: str
    unit: str
    location: str
    qty: float
    value: float                   # per unit when sent
    capital_goods: bool
    used: float
    unused: float
    lost: float
    at_job_worker: float
    due: date
    days_left: int


class ChallanRow(Out):
    id: str
    job_worker: str
    job_worker_name: str
    job_worker_gstin: str
    ship_from: str
    ship_from_name: str
    ship_from_gstin: str
    order: str
    order_product: str | None
    order_product_name: str
    order_open: bool
    sent_on: date
    vehicle: str
    charge: float
    processed: float
    status: str                    # at job worker | due soon | overdue | closed | cancelled
    due: date | None               # the first limit of what is still out there
    days_left: int | None
    value_out: float               # what is at the job worker, at its value when sent
    value_sent: float
    lines: list[ChallanLineRow]
    returns: list[ChallanReturn]
    note: str


class StockAtJobWorker(Out):
    job_worker: str
    job_worker_name: str
    product: str
    product_name: str
    unit: str
    qty: float
    value: float
    challans: list[str]
    first_due: date


class DeemedSupply(Out):
    challan: str
    job_worker: str
    job_worker_name: str
    product: str
    product_name: str
    qty: float
    value: float
    tax_rate: float
    tax: float
    sent_on: date
    due: date


class OrderToSend(Out):
    order: str
    product: str
    product_name: str
    location: str
    qty: float                     # left to make
    start: date | None
    job_worker: str | None
    job_worker_name: str
    charge: float
    parts: list[dict]
    on_challans: list[str]


class Itc04Row(Out):
    table: str                     # 4: sent to a job worker; 5A: back from one
    challan: str
    date: date
    job_worker: str
    job_worker_gstin: str
    job_worker_state: str
    their_challan: str
    product: str
    description: str
    hsn: str
    uqc: str
    qty: float
    value: float | None            # taxable value (table 4)
    goods: str                     # inputs | capital goods | processed goods
    kind: str                      # sent | processed | unused


class JobWorkView(Out):
    as_of: date
    currency: str
    company_gstin: str
    challans: list[ChallanRow]
    stock: list[StockAtJobWorker]
    deemed: list[DeemedSupply]
    to_send: list[OrderToSend]
    period: str
    period_start: date
    period_end: date
    itc04: list[Itc04Row]
    value_out: float
    deemed_tax: float


def _half_year(day: date) -> tuple[date, date, str]:
    """The ITC-04 period (half-yearly, the Indian financial year from April) the day falls in."""
    fy = day.year if day.month >= 4 else day.year - 1
    if 4 <= day.month <= 9:
        return date(fy, 4, 1), date(fy, 9, 30), f"Apr–Sep {fy}"
    return date(fy, 10, 1), date(fy + 1, 3, 31), f"Oct {fy}–Mar {fy + 1}"


def _tax_rate(ds: Dataset, product: str) -> float:
    p = ds.product_by_id.get(product)
    return p.tax_rate if p and p.tax_rate is not None else ds.sales.tax_rate


def _state(lo) -> str:
    """The job worker's state for ITC-04: from the GSTIN's state code, else the place's region."""
    from ..sales import _GST_STATES
    if lo is None:
        return ""
    t = lo.tax_id.strip()
    if len(t) >= 2 and t[:2] in _GST_STATES:
        return _GST_STATES[t[:2]][0]
    return lo.region


def itc04(ds: Dataset, start: date, end: date) -> list[Itc04Row]:
    out = []
    for c in ds.challans:
        if c.cancelled:
            continue
        lo = ds.location_by_id.get(c.job_worker)
        gstin, state = (lo.tax_id if lo else ""), _state(lo)
        if start <= c.sent_on <= end:
            for ln in c.lines:
                p = ds.product_by_id.get(ln.product)
                out.append(Itc04Row(table="4", challan=c.id, date=c.sent_on, job_worker=c.job_worker,
                                    job_worker_gstin=gstin, job_worker_state=state, their_challan="",
                                    product=ln.product, description=_name(ds, ln.product), hsn=p.hsn if p else "",
                                    uqc=uqc(ds, ln.product), qty=ln.qty, value=round(ln.qty * ln.value, 2),
                                    goods="capital goods" if ln.capital_goods else "inputs", kind="sent"))
        for r in c.returns:
            if r.kind == "lost" or not start <= r.date <= end:
                continue
            p = ds.product_by_id.get(r.product)
            out.append(Itc04Row(table="5A", challan=c.id, date=r.date, job_worker=c.job_worker,
                                job_worker_gstin=gstin, job_worker_state=state, their_challan=r.reference,
                                product=r.product, description=_name(ds, r.product), hsn=p.hsn if p else "",
                                uqc=uqc(ds, r.product), qty=r.qty, value=None,
                                goods="processed goods" if r.kind == "processed" else (
                                    "capital goods" if any(x.capital_goods for x in c.lines if x.product == r.product)
                                    else "inputs"), kind=r.kind))
    return sorted(out, key=lambda x: (x.table, x.date, x.challan, x.product))


def view(ds: Dataset, on: date | None = None, period_start: date | None = None,
         period_end: date | None = None) -> JobWorkView:
    day = _today(ds, on)
    warn = ds.job_work.warn_days
    rows: list[ChallanRow] = []
    stock: dict[tuple[str, str], StockAtJobWorker] = {}
    deemed: list[DeemedSupply] = []
    for c in sorted(ds.challans, key=lambda x: (x.sent_on, x.id), reverse=True):
        jw, sf = ds.location_by_id.get(c.job_worker), ds.location_by_id.get(c.ship_from)
        prod = order_product(ds, c.order)
        lines = []
        for ln in c.lines:
            used, unused, lost = c.back(ln.product)
            there = c.at_job_worker(ln.product)
            due = due_date(ds, c, ln)
            p = ds.product_by_id.get(ln.product)
            lines.append(ChallanLineRow(product=ln.product, product_name=_name(ds, ln.product), hsn=p.hsn if p else "",
                                        unit=p.base_uom if p else "EA", location=ln.location, qty=ln.qty,
                                        value=ln.value, capital_goods=ln.capital_goods, used=used, unused=unused,
                                        lost=lost, at_job_worker=there, due=due, days_left=(due - day).days))
            if there > EPS:
                k = (c.job_worker, ln.product)
                s = stock.get(k)
                if s is None:
                    s = stock[k] = StockAtJobWorker(job_worker=c.job_worker, job_worker_name=_name(ds, c.job_worker),
                                                    product=ln.product, product_name=_name(ds, ln.product),
                                                    unit=p.base_uom if p else "EA", qty=0.0, value=0.0, challans=[],
                                                    first_due=due)
                s.qty = round(s.qty + there, 6)
                s.value = round(s.value + there * ln.value, 2)
                s.challans.append(c.id)
                s.first_due = min(s.first_due, due)
                if due < day:
                    rate = _tax_rate(ds, ln.product)
                    v = round(there * ln.value, 2)
                    deemed.append(DeemedSupply(challan=c.id, job_worker=c.job_worker,
                                               job_worker_name=_name(ds, c.job_worker), product=ln.product,
                                               product_name=_name(ds, ln.product), qty=there, value=v, tax_rate=rate,
                                               tax=round(v * rate, 2), sent_on=c.sent_on, due=due))
        out_lines = [x for x in lines if x.at_job_worker > EPS]
        first = min((x.due for x in out_lines), default=None)
        left = (first - day).days if first else None
        if c.cancelled:
            st = "cancelled"
        elif c.closed_on is not None or not out_lines:
            st = "closed"
        elif left is not None and left < 0:
            st = "overdue"
        elif left is not None and left <= warn:
            st = "due soon"
        else:
            st = "at job worker"
        rows.append(ChallanRow(
            id=c.id, job_worker=c.job_worker, job_worker_name=_name(ds, c.job_worker),
            job_worker_gstin=jw.tax_id if jw else "", ship_from=c.ship_from, ship_from_name=_name(ds, c.ship_from),
            ship_from_gstin=(sf.tax_id if sf and sf.tax_id else ds.settings.company_tax_id), order=c.order,
            order_product=prod, order_product_name=_name(ds, prod) if prod else "",
            order_open=any(r.id == c.order for r in ds.receipts), sent_on=c.sent_on, vehicle=c.vehicle,
            charge=c.charge, processed=c.processed, status=st, due=first if st not in ("closed", "cancelled") else None,
            days_left=left if st not in ("closed", "cancelled") else None,
            value_out=round(sum(x.at_job_worker * x.value for x in lines), 2) if not c.cancelled else 0.0,
            value_sent=round(sum(x.qty * x.value for x in lines), 2), lines=lines, returns=c.returns, note=c.note))
    to_send = []
    on_challan: dict[str, list[str]] = defaultdict(list)
    for c in ds.challans:
        if not c.cancelled:
            on_challan[c.order].append(c.id)
    for rc in sorted((r for r in ds.receipts if r.kind is ReceiptKind.PRODUCTION),
                     key=lambda r: (r.start_date or r.due_date, r.id)):
        sub = _outside_op(ds, rc)
        if sub is None and rc.id not in on_challan:
            continue
        try:
            parts = parts_to_send(ds, rc.id)
        except JobWorkError:
            parts = []
        if not parts:
            continue
        ordered = rc.ordered_qty if rc.ordered_qty is not None else rc.qty
        last = max((c for c in ds.challans if c.order == rc.id and not c.cancelled), key=lambda c: (c.sent_on, c.id),
                   default=None)
        who = sub.supplier if sub else (last.job_worker if last else None)     # the routing's, else who has it now
        to_send.append(OrderToSend(order=rc.id, product=rc.product, product_name=_name(ds, rc.product),
                                   location=rc.location, qty=round(max(0.0, ordered - _made(ds, rc.id, rc.product)), 6),
                                   start=rc.start_date, job_worker=who, job_worker_name=_name(ds, who) if who else "",
                                   charge=sub.cost_per_unit if sub else (last.charge if last else 0.0), parts=parts,
                                   on_challans=on_challan.get(rc.id, [])))
    s0, s1, label = _half_year(day)
    if period_start and period_end:
        s0, s1, label = period_start, period_end, f"{_day(period_start)} – {_day(period_end)}"
    return JobWorkView(
        as_of=day, currency=ds.settings.currency, company_gstin=ds.settings.company_tax_id, challans=rows,
        stock=sorted(stock.values(), key=lambda s: (s.job_worker, s.product)),
        deemed=sorted(deemed, key=lambda d: (d.due, d.challan)), to_send=to_send, period=label, period_start=s0,
        period_end=s1, itc04=itc04(ds, s0, s1), value_out=round(sum(r.value_out for r in rows), 2),
        deemed_tax=round(sum(d.tax for d in deemed), 2))


def challan_held(ds: Dataset) -> dict[str, str]:
    """Issue movements a challan holds (taken back only through the challan), by movement id."""
    return {m: c.id for c in ds.challans if not c.cancelled for ln in c.lines for m in ln.movements}


__all__ = ["ChallanLineRow", "ChallanRow", "DeemedSupply", "Itc04Row", "JobWorkError", "JobWorkReport", "JobWorkView",
           "OrderToSend", "StockAtJobWorker", "cancel", "challan_held", "due_date", "itc04", "order_product",
           "parts_to_send", "receive", "return_unused", "send", "uqc", "view", "write_off"]
