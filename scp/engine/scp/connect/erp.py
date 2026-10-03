"""What an ERP sends and takes back (Phase Q), as changes to a company's data.

Another system (SAP, Navision, Tally, a warehouse system) works in a company with an integration key: it sends
customer orders, stock and goods movements and master data, and takes back the purchase, production and transfer
orders planning made, saying which number it gave each. Every function here takes the company and a list of items and
gives back the changed company and one result per item: an item the data does not allow is refused with the reason
and the others are still taken, as an ERP's interface expects.

* **Customer orders** are matched by the ERP's order number (``erp_ref`` on the order): a new number is a new order
  (priced, promised and checked against the credit limit as one typed in), a known one is changed line by line (a line
  more is added, a line less cancelled, a quantity, date or price changed and promised again), and ``cancelled``
  cancels what is still open.
* **Stock** is the ERP's stock at a place at the end of a day: a difference is posted as a count difference.
* **Goods movements** are posted as postings typed in are (a goods receipt against an order, a transfer shipped, a
  delivery to a customer, stock moved between stock types, scrap), each taken once: the ERP's document number is kept
  on the movements it made and a second message with it is a duplicate. An order is named by its number here or by
  the ERP's (``4500001234/10``: the ERP's number of the order and the line).
* **Master data** are upserted record by record by the fields that identify a record (as a save's change does).
* **Orders back to the ERP**: purchase orders released for sending and firm production and transfer orders, each
  with a version (a short fingerprint of what the ERP needs of it). The ERP says it took one with its own number and
  the version it took; an order changed since then (a quantity, a date, a price, a line cancelled) goes to it again.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any, Literal, get_args

from pydantic import Field, TypeAdapter, ValidationError

from ..actuals.post import PostingError, count_stock, ordered_now, post
from ..actuals.stock import EPS
from ..model import Dataset, DemandKind, ReceiptKind
from ..model.actuals import StockType
from ..model.common import Model, Out
from ..promise.orders import OrderError, cancel, change
from ..sales import SalesError, _lines_of, add_lines, cancel_order, create_order
from ..versions.diff import KEYS

Status = Literal["applied", "unchanged", "duplicate", "refused"]
REFUSED = (SalesError, OrderError, PostingError, ValidationError, ValueError, KeyError)


class ItemResult(Out):
    """What became of one item of a message."""
    ref: str                       # the ERP's name for it: an order number, a document number, "place / product"
    status: Status
    message: str
    id: str | None = None          # our record it made or changed (SO-00012, GM-00031, …)


# ------------------------------------------------------------------------------------------------ what comes in
class ErpLine(Model):
    product: str = Field(min_length=1, max_length=64)
    qty: float = Field(gt=0, description="The whole quantity ordered on the line")
    date: dt.date = Field(description="Wanted on")
    price: float | None = Field(None, ge=0, description="Net price per unit; empty = the customer's price here")


class ErpOrder(Model):
    number: str = Field(min_length=1, max_length=64, description="The order's number in the ERP")
    customer: str = Field(min_length=1, max_length=64)
    order_date: dt.date | None = None
    customer_ref: str = Field("", max_length=64, description="The customer's own order number")
    payment_terms: str | None = None
    lines: list[ErpLine] = Field(default_factory=list, max_length=500)
    cancelled: bool = Field(False, description="Cancelled in the ERP: what is open here is cancelled")
    note: str = Field("", max_length=400)


class ErpStock(Model):
    location: str = Field(min_length=1, max_length=64)
    product: str = Field(min_length=1, max_length=64)
    qty: float = Field(ge=0, description="On hand at the end of the day, every stock type")


class ErpPosting(Model):
    ref: str = Field(min_length=1, max_length=64, description="The ERP's document number: a posting is taken once")
    action: Literal["receive", "ship", "deliver", "move", "scrap"]
    order: str | None = Field(None, max_length=64, description="receive / ship / deliver: the order, by our number or "
                                                               "the ERP's (4500001234/10)")
    qty: float | None = Field(None, gt=0)
    date: dt.date | None = None
    final: bool = False
    location: str | None = None
    product: str | None = None
    batch: str | None = Field(None, max_length=40)
    expires_on: dt.date | None = None
    supplier_batch: str | None = Field(None, max_length=40)
    stock_type: StockType | None = None
    to_type: StockType | None = None
    note: str = Field("", max_length=200)


class ErpAck(Model):
    kind: Literal["purchase_order", "production_order", "transfer_order"]
    id: str = Field(min_length=1, max_length=64, description="The order's number here")
    erp_ref: str = Field(min_length=1, max_length=64, description="The number the ERP gave it")
    version: str = Field(min_length=1, max_length=32, description="The version the ERP took (from the order sent)")
    sent_to_supplier: bool = Field(False, description="A purchase order: the ERP sent it to the supplier")


# ------------------------------------------------------------------------------------------------ helpers
def _n(q: float) -> str:
    return f"{q:,.0f}" if abs(q - round(q)) < 1e-9 else f"{q:,.3f}".rstrip("0").rstrip(".")


def _each(ds: Dataset, items: list, ref, apply) -> tuple[Dataset, list[ItemResult]]:
    out: list[ItemResult] = []
    for it in items:
        try:
            ds, r = apply(ds, it)
        except REFUSED as e:
            r = ItemResult(ref=ref(it), status="refused", message=_why(e))
        out.append(r)
    return ds, out


def _why(e: Exception) -> str:
    if isinstance(e, ValidationError):
        err = e.errors()[0]
        where = ".".join(str(x) for x in err.get("loc", ()))
        return f"{where}: {err.get('msg', 'not valid')}" if where else str(err.get("msg", "not valid"))
    if isinstance(e, KeyError):
        return f"there is no {e.args[0]!r}" if e.args else "not found"
    return str(e) or type(e).__name__


# ------------------------------------------------------------------------------------------------ customer orders
def apply_orders(ds: Dataset, orders: list[ErpOrder]) -> tuple[Dataset, list[ItemResult]]:
    return _each(ds, orders, lambda o: o.number, _order)


def _order(ds: Dataset, o: ErpOrder) -> tuple[Dataset, ItemResult]:
    head = next((h for h in ds.sales_orders if h.erp_ref == o.number), None)
    if head is None:
        if o.cancelled:
            return ds, ItemResult(ref=o.number, status="unchanged", message=f"order {o.number} is cancelled in the "
                                  "ERP and was never taken here")
        new, rep = create_order(ds, o.customer, [ln.model_dump() for ln in o.lines], order_date=o.order_date,
                                customer_ref=o.customer_ref or o.number, payment_terms=o.payment_terms, note=o.note)
        made = new.sales_orders[-1]
        new = new.model_copy(update={"sales_orders": [*new.sales_orders[:-1], made.model_copy(update={"erp_ref": o.number})]})
        return new, ItemResult(ref=o.number, status="applied", message=rep.message, id=made.id)
    if o.customer != head.customer:
        raise SalesError(f"{head.id} is {head.customer}'s order; an order's customer cannot change: cancel it in the "
                         "ERP and send a new one")
    open_ids = {d.id for d in ds.demand if d.kind is DemandKind.SALES_ORDER and d.order == head.id}
    if o.cancelled:
        if not open_ids:
            return ds, ItemResult(ref=o.number, status="unchanged", message=f"{head.id}: nothing is open to cancel",
                                  id=head.id)
        new, rep = cancel_order(ds, head.id, reason="cancelled in the ERP")
        return new, ItemResult(ref=o.number, status="applied", message=rep.message, id=head.id)
    lines = _lines_of(ds, head.id)
    cur, said, more = ds, [], []
    for i, ln in enumerate(o.lines):
        if i >= len(lines):
            more.append(ln.model_dump())
            continue
        lid = lines[i].id or ""
        rec = next((d for d in cur.demand if d.id == lid and d.kind is DemandKind.SALES_ORDER), None)
        if rec is None:
            if ln.product != lines[i].product or abs(ln.qty - (lines[i].ordered_qty or lines[i].qty)) > EPS:
                said.append(f"{lid} is closed (delivered or cancelled) and stays as it is")
            continue
        if ln.product != rec.product:
            raise SalesError(f"line {i + 1} ({lid}) is for {rec.product}; a line's product cannot change: send the "
                             "line cancelled and the product on a new line")
        ch: dict[str, Any] = {}
        if abs(ln.qty - ordered_now(cur, rec)) > EPS:
            ch["qty"] = ln.qty
        if ln.date != rec.date:
            ch["date"] = ln.date
        if ln.price is not None and abs(ln.price - (rec.price or 0.0)) > 1e-9:
            ch["price"] = ln.price
        if ch:
            cur, rep = change(cur, lid, ch)
            said.append(rep.message)
    if more:
        cur, rep = add_lines(cur, head.id, more)
        said.append(rep.message)
    for d in lines[len(o.lines):]:
        if d.id in open_ids:
            cur, rep = cancel(cur, d.id or "", None, "no longer on the ERP's order")
            said.append(rep.message)
    if not said:
        return ds, ItemResult(ref=o.number, status="unchanged", message=f"{head.id} is as the ERP has it", id=head.id)
    return cur, ItemResult(ref=o.number, status="applied", message=" ".join(said), id=head.id)


# ------------------------------------------------------------------------------------------------ stock
def apply_stock(ds: Dataset, rows: list[ErpStock], on: dt.date | None = None) -> tuple[Dataset, list[ItemResult]]:
    """The ERP's stock at the end of ``on`` (default the day before the planning start): differences are posted."""
    out: list[ItemResult | None] = []
    good: list[ErpStock] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        ref = f"{r.location} / {r.product}"
        if r.location not in ds.location_by_id:
            out.append(ItemResult(ref=ref, status="refused", message=f"there is no place {r.location!r}"))
        elif r.product not in ds.product_by_id:
            out.append(ItemResult(ref=ref, status="refused", message=f"there is no product {r.product!r}"))
        elif (r.location, r.product) in seen:
            out.append(ItemResult(ref=ref, status="refused", message="listed twice in the message"))
        else:
            seen.add((r.location, r.product))
            good.append(r)
            out.append(None)
    if not good:
        return ds, [x for x in out if x is not None]
    try:
        new, rep = count_stock(ds, [r.model_dump() for r in good], on, note="Stock from the ERP")
    except PostingError as e:
        return ds, [x or ItemResult(ref="", status="refused", message=str(e)) for x in out]
    made = {(m.location, m.product): m for m in new.movements if m.id in set(rep.movements)}
    it = iter(good)
    res: list[ItemResult] = []
    for x in out:
        if x is not None:
            res.append(x)
            continue
        r = next(it)
        m = made.get((r.location, r.product))
        ref = f"{r.location} / {r.product}"
        res.append(ItemResult(ref=ref, status="unchanged", message=f"{_n(r.qty)} on hand, as here") if m is None else
                   ItemResult(ref=ref, status="applied", id=m.id,
                              message=f"{_n(r.qty)} on hand: {'+' if m.signed > 0 else '−'}{_n(abs(m.signed))} "
                                      f"posted ({'opening balance' if m.type.value == 'opening' else 'count difference'})"))
    return new, res


# ------------------------------------------------------------------------------------------------ goods movements
_ERP_LINE = re.compile(r"^(.+?)[/-](\d+)$")


def resolve_order(ds: Dataset, ref: str) -> str:
    """Our number of the order the ERP names: ours as it is, else the ERP's number of a purchase order and its line
    (``4500001234/10``), of a sales order and its line, or of a production or transfer order."""
    if any(r.id == ref for r in ds.receipts) or any(d.id == ref for d in ds.demand):
        return ref
    for r in ds.receipts:
        if r.erp_ref and r.erp_ref == ref:
            return r.id
    m = _ERP_LINE.match(ref)
    if m:
        number, item = m.group(1), int(m.group(2))
        po = next((p for p in ds.purchase_orders if p.erp_ref == number), None)
        if po is not None:
            return f"{po.id}-{item}"
        so = next((s for s in ds.sales_orders if s.erp_ref == number), None)
        if so is not None:
            return f"{so.id}/{item}"
    return ref


def apply_postings(ds: Dataset, postings: list[ErpPosting]) -> tuple[Dataset, list[ItemResult]]:
    return _each(ds, postings, lambda p: p.ref, _posting)


def _posting(ds: Dataset, p: ErpPosting) -> tuple[Dataset, ItemResult]:
    done = [m.id for m in ds.movements if m.erp_ref == p.ref]
    if done:
        return ds, ItemResult(ref=p.ref, status="duplicate", id=done[0],
                              message=f"already posted as {', '.join(done[:3])}{' …' if len(done) > 3 else ''}")
    order = resolve_order(ds, p.order) if p.order else None
    new, rep = post(ds, p.action, order=order, qty=p.qty, on=p.date, final=p.final, note=p.note or f"ERP {p.ref}",
                    lot={"batch": p.batch, "expires_on": p.expires_on, "supplier_batch": p.supplier_batch or "",
                         "serials": None, "stock_type": p.stock_type},
                    location=p.location, product=p.product, to_type=p.to_type)
    ids = set(rep.movements)
    if not ids:
        return ds, ItemResult(ref=p.ref, status="unchanged", message=rep.message)
    new = new.model_copy(update={"movements": [m.model_copy(update={"erp_ref": p.ref}) if m.id in ids else m
                                               for m in new.movements]})
    return new, ItemResult(ref=p.ref, status="applied", message=rep.message, id=rep.doc or sorted(ids)[0])


# ------------------------------------------------------------------------------------------------ master data
#: lists an ERP may send record by record; orders, documents and the journal have their own messages
NOT_RECORDS = {"movements", "sales_orders", "purchase_orders", "deliveries", "invoices", "returns", "quotations",
               "supplier_invoices", "supplier_returns", "confirmations", "closed_orders", "inventory_docs", "batches",
               "allocations", "accuracy", "rolled_weeks"}


def record_lists() -> list[str]:
    return sorted(n for n, f in Dataset.model_fields.items()
                  if n not in NOT_RECORDS and getattr(f.annotation, "__origin__", None) is list
                  and isinstance(get_args(f.annotation)[0], type) and issubclass(get_args(f.annotation)[0], Model))


def _key(name: str, rec: dict) -> tuple:
    return tuple(rec.get(f) for f in KEYS.get(name, ("id",)))


def apply_records(ds: Dataset, name: str, records: list[dict[str, Any]]) -> tuple[Dataset, list[ItemResult]]:
    """Records of one list, each added or, when one with the same key is here, changed in the fields sent."""
    if name not in record_lists():
        raise ValueError(f"{name!r} is not a list of master data the ERP can send; it is one of "
                         f"{', '.join(record_lists())}")
    item = TypeAdapter(get_args(Dataset.model_fields[name].annotation)[0])
    rows = list(getattr(ds, name))
    pos = {_key(name, r.model_dump(mode="json")): i for i, r in enumerate(rows)}
    out: list[ItemResult] = []
    for raw in records:
        k = _key(name, raw)
        ref = " / ".join(str(v) for v in k if v is not None) or "?"
        if all(v is None for v in k):
            out.append(ItemResult(ref=ref, status="refused",
                                  message=f"a record of {name} is named by {', '.join(KEYS.get(name, ('id',)))}"))
            continue
        try:
            if k in pos:
                old = rows[pos[k]].model_dump(mode="json")
                merged = {**old, **raw}
                if merged == old:
                    out.append(ItemResult(ref=ref, status="unchanged", message="as here", id=ref))
                    continue
                rows[pos[k]] = item.validate_python(merged)
                changed = sorted(f for f in raw if old.get(f) != raw[f])
                out.append(ItemResult(ref=ref, status="applied", id=ref, message=f"changed: {', '.join(changed)}"))
            else:
                rows.append(item.validate_python(raw))
                pos[k] = len(rows) - 1
                out.append(ItemResult(ref=ref, status="applied", id=ref, message="added"))
        except ValidationError as e:
            out.append(ItemResult(ref=ref, status="refused", message=_why(e)))
    if not any(r.status == "applied" for r in out):
        return ds, out
    return ds.model_copy(update={name: rows}), out


# ------------------------------------------------------------------------------------------------ orders back
OutKind = Literal["purchase_order", "production_order", "transfer_order"]


class OutLine(Out):
    id: str
    item: int
    product: str
    qty: float                     # ordered
    open: float                    # still to come
    date: dt.date                  # due
    price: float | None
    cancelled: bool


class OutOrder(Out):
    """An order for the ERP to take: the ERP gives its number and the ``version`` back when it has taken it."""
    kind: OutKind
    id: str
    version: str                   # what the ERP needs of the order, fingerprinted: a new one means it changed
    change: Literal["new", "changed", "taken", "withdrawn"]   # withdrawn: deleted here, the ERP should close its copy
    erp_ref: str
    location: str
    supplier: str | None = None    # purchase: the supplier; transfer: the place it comes from
    supplier_name: str | None = None
    order_date: dt.date | None = None
    currency: str | None = None
    agreement: bool = False        # purchase: a scheduling agreement (its lines are the delivery schedule)
    sent_on: dt.date | None = None
    product: str | None = None     # production / transfer
    qty: float | None = None
    start: dt.date | None = None
    due: dt.date | None = None
    source: str | None = None      # the way it is made or the route it comes by
    lines: list[OutLine] = []


def _version(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()[:16]


def _item(lid: str) -> int:
    m = re.search(r"[-/](\d+)$", lid)
    return int(m.group(1)) if m else 0


def _change(erp_ref: str, sent: str, version: str) -> Literal["new", "changed", "taken"]:
    return "taken" if sent == version else "changed" if sent else "new"


def outbound(ds: Dataset, kind: OutKind, everything: bool = False) -> list[OutOrder]:
    """The orders of ``kind`` for the ERP: new and changed ones (``everything``: those taken too)."""
    out: list[OutOrder] = []
    if kind == "purchase_order":
        from ..purchasing import purchase_orders
        heads = {p.id: p for p in ds.purchase_orders}
        for v in purchase_orders(ds):
            h = heads.get(v.id)
            if h is None or not v.header or not h.approved or v.status == "awaiting approval":
                continue
            lines = [OutLine(id=x.id, item=_item(x.id), product=x.product, qty=x.ordered, open=x.open, date=x.due_date,
                             price=x.price, cancelled=x.closed and "cancel" in x.status) for x in v.lines]
            if not lines:
                continue
            ver = _version({"s": h.supplier, "l": h.location, "c": v.currency, "k": h.kind, "to": h.valid_to,
                            "lines": [(x.id, x.product, x.qty, x.date, x.price, x.cancelled) for x in lines]})
            ch = _change(h.erp_ref, h.erp_sent, ver)
            if everything or ch != "taken":
                out.append(OutOrder(kind=kind, id=h.id, version=ver, change=ch, erp_ref=h.erp_ref, location=h.location,
                                    supplier=h.supplier, supplier_name=ds.location_by_id[h.supplier].name
                                    if h.supplier in ds.location_by_id else h.supplier, order_date=h.order_date,
                                    currency=v.currency, agreement=h.kind == "scheduling_agreement", sent_on=h.sent_on,
                                    lines=lines))
        return out
    want = ReceiptKind.PRODUCTION if kind == "production_order" else ReceiptKind.TRANSFER
    lanes = {ln.id: ln for ln in ds.lanes}
    for r in ds.receipts:
        if r.kind is not want:
            continue
        qty = r.ordered_qty if r.ordered_qty is not None else r.qty
        origin = lanes[r.source].origin if want is ReceiptKind.TRANSFER and r.source in lanes else None
        ver = _version({"p": r.product, "l": r.location, "q": qty, "s": r.start_date, "d": r.due_date, "src": r.source})
        ch = _change(r.erp_ref, r.erp_sent, ver)
        if everything or ch != "taken":
            out.append(OutOrder(kind=kind, id=r.id, version=ver, change=ch, erp_ref=r.erp_ref, location=r.location,
                                supplier=origin, supplier_name=ds.location_by_id[origin].name
                                if origin in ds.location_by_id else origin,
                                product=r.product, qty=qty, start=r.start_date, due=r.due_date, source=r.source))
    return out


def withdrawn_version(kind: str, oid: str, erp_ref: str) -> str:
    return _version({"withdrawn": [kind, oid, erp_ref]})


def withdrawn(kind: OutKind, rows: list[dict]) -> list[OutOrder]:
    """Orders the ERP numbered that were deleted here (N137): ``rows`` as kept by the company store (kind, id,
    erp_ref, location, taken_at)."""
    return [OutOrder(kind=kind, id=r["id"], version=withdrawn_version(kind, r["id"], r["erp_ref"]),
                     change="taken" if r.get("taken_at") else "withdrawn", erp_ref=r["erp_ref"],
                     location=r.get("location") or "")
            for r in rows if r["kind"] == kind]


def acknowledge(ds: Dataset, acks: list[ErpAck], gone: dict[tuple[str, str], str] | None = None
                ) -> tuple[Dataset, list[ItemResult]]:
    """The ERP took these orders: keep the number it gave each and the version it took. ``gone``: orders deleted
    here, (kind, id) → the ERP's number; an acknowledgement of one says the ERP closed its copy."""
    current = {(k, o.id): o for k in ("purchase_order", "production_order", "transfer_order")
               for o in outbound(ds, k, everything=True)} if acks else {}
    return _each(ds, acks, lambda a: a.id, lambda d, a: _ack(d, a, current, gone or {}))


def _ack(ds: Dataset, a: ErpAck, current: dict, gone: dict[tuple[str, str], str]) -> tuple[Dataset, ItemResult]:
    if (a.kind, a.id) in gone and (a.kind, a.id) not in current:
        if gone[(a.kind, a.id)] != a.erp_ref:
            raise ValueError(f"{a.id} was {gone[(a.kind, a.id)]} in the ERP, not {a.erp_ref}")
        return ds, ItemResult(ref=a.id, status="applied", id=a.id,
                              message=f"{a.id} ({a.erp_ref}) was deleted here: the ERP closed its copy")
    now = current.get((a.kind, a.id))
    later = " The order changed since that version: it goes to the ERP again." if now and now.version != a.version else ""
    if a.kind == "purchase_order":
        h = next((p for p in ds.purchase_orders if p.id == a.id), None)
        if h is None:
            raise ValueError(f"there is no purchase order {a.id}")
        if h.erp_ref and h.erp_ref != a.erp_ref:
            raise ValueError(f"{a.id} is {h.erp_ref} in the ERP already, not {a.erp_ref}")
        upd: dict[str, Any] = {"erp_ref": a.erp_ref, "erp_sent": a.version}
        sent = ""
        if a.sent_to_supplier and h.sent_on is None and h.approved:
            upd["sent_on"] = ds.settings.planning_start
            sent = " Sent to the supplier by the ERP."
        if h.erp_ref == a.erp_ref and h.erp_sent == a.version and "sent_on" not in upd:
            return ds, ItemResult(ref=a.id, status="unchanged", message=f"{a.id} was taken as {a.erp_ref} already",
                                  id=a.id)
        new = h.model_copy(update=upd)
        return (ds.model_copy(update={"purchase_orders": [new if p is h else p for p in ds.purchase_orders]}),
                ItemResult(ref=a.id, status="applied", id=a.id, message=f"{a.id} is {a.erp_ref} in the ERP.{sent}{later}"))
    want = ReceiptKind.PRODUCTION if a.kind == "production_order" else ReceiptKind.TRANSFER
    r = next((x for x in ds.receipts if x.id == a.id and x.kind is want), None)
    if r is None:
        raise ValueError(f"there is no open {a.kind.replace('_', ' ')} {a.id}")
    if r.erp_ref and r.erp_ref != a.erp_ref:
        raise ValueError(f"{a.id} is {r.erp_ref} in the ERP already, not {a.erp_ref}")
    if r.erp_ref == a.erp_ref and r.erp_sent == a.version:
        return ds, ItemResult(ref=a.id, status="unchanged", message=f"{a.id} was taken as {a.erp_ref} already", id=a.id)
    new = r.model_copy(update={"erp_ref": a.erp_ref, "erp_sent": a.version})
    return (ds.model_copy(update={"receipts": [new if x is r else x for x in ds.receipts]}),
            ItemResult(ref=a.id, status="applied", id=a.id, message=f"{a.id} is {a.erp_ref} in the ERP.{later}"))
