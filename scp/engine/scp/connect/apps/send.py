"""Purchase orders to Tally or Zoho (ENTERPRISE_PLAN 3.2): the orders an ERP would take (:func:`scp.connect.erp
.outbound`) sent one by one, and what the other system took acknowledged as an ERP acknowledges, so each keeps the
number it was given there and goes again only when it changes here.

A run logs what went out (each order: made, changed or cancelled there, or refused with the other system's reason)
with the start of what was sent, and the acknowledgement as the message it is (a revision of the company). A dry
run builds what would be sent and sends nothing. An order cancelled here that the other system never took is not
sent: there is nothing there to cancel.
"""
from __future__ import annotations

import json
from typing import Any

from ...companies import Companies, User
from ..erp import ErpAck, ItemResult, OutOrder, acknowledge, outbound, withdrawn
from ..mapping import inverse
from ..messages import MessageRow, _now, log, read_company, receive
from . import NAMES, fingerprint, module, settings_of

KIND = "purchase_order"


def _gone(c: Companies, cid: str) -> list[dict[str, Any]]:
    with c.lock:
        return [dict(r) for r in c.db.execute("SELECT * FROM erp_withdrawn WHERE company_id = ? AND kind = ? AND "
                                              "taken_at IS NULL ORDER BY at, id", (cid, KIND))]


def _ended(o: OutOrder) -> bool:
    return o.change == "withdrawn" or o.cancelled or not any(not ln.cancelled for ln in o.lines)


def pending(ds: Any, gone_rows: list[dict[str, Any]]) -> list[OutOrder]:
    """What goes out now: new and changed orders, and ones cancelled or deleted here that the other system has."""
    orders = [o for o in outbound(ds, KIND) if not (_ended(o) and not o.erp_ref)]
    return orders + [o for o in withdrawn(KIND, gone_rows) if o.change == "withdrawn"]


def run(c: Companies, job: dict, runner: User, dry: bool = False) -> list[tuple[MessageRow, bytes]]:
    from ..imports import _failed, _mapping, sample
    app, cid = job["source_type"], job["company_id"]
    name = NAMES[app]
    source = f"{job['id']} {job['name']}: {job['source']}"
    s, m = settings_of(job), _mapping(job)
    ds, rev = read_company(c, runner, cid)
    gone_rows = _gone(c, cid)
    orders = pending(ds, gone_rows)
    if not orders:
        quiet = MessageRow(seq=0, at=_now(), by=c._name(runner.id), direction="out", kind=KIND, message_id="",
                           status="unchanged", summary=f"nothing to send: every purchase order is in {name} as it is "
                                                       "here", source=source, dry_run=dry)
        return [(quiet, b"")]
    secrets = json.loads(job["headers"]) if app == "zoho" else {}
    headers = {} if app == "zoho" else json.loads(job["headers"])
    try:
        sender = module(app).Sender(job, s, secrets, headers)
    except ValueError as e:
        with c.lock:
            return [(_failed(c, job, job["source"], str(e), dry), b"")]
    products, suppliers, places = inverse(m, "product"), inverse(m, "supplier"), inverse(m, "location")
    results: list[ItemResult] = []
    acks: list[ErpAck] = []
    sent: list[bytes] = []
    for o in orders:
        what = "cancelled" if _ended(o) else {"new": "made", "changed": "changed"}.get(o.change, o.change)
        try:
            party = suppliers.get(o.supplier or "") or sender.codes(ds, "supplier", o.supplier or "")
            items = {ln.product: products.get(ln.product) or sender.codes(ds, "product", ln.product) for ln in o.lines}
            body = sender.payload(o, party, items, places)
            sent.append(body)
            if dry:
                results.append(ItemResult(ref=o.id, status="applied", id=o.id,
                                          message=f"would be {what} in {name} ({party})"))
                continue
            ref = sender.send(o, body)
        except ValueError as e:
            results.append(ItemResult(ref=o.id, status="refused", id=o.id, message=str(e)))
            continue
        except OSError as e:          # the other system cannot be reached: the next run sends it
            results.append(ItemResult(ref=o.id, status="refused", id=o.id,
                                      message=f"{name} could not be reached: {e}"))
            continue
        acks.append(ErpAck(kind=KIND, id=o.id, erp_ref=ref, version=o.version))
        results.append(ItemResult(ref=o.id, status="applied", id=o.id, message=f"{what} in {name} as {ref}"))
    ok = sum(r.status == "applied" for r in results)
    status = "sent" if ok == len(results) else "partly" if ok else "refused"
    word = "would go" if dry else "sent"
    summary = f"{len(results)} purchase order{'' if len(results) == 1 else 's'} to {name}: {ok} {word}" + (
        f", {len(results) - ok} refused" if ok < len(results) else "")
    with c.lock:
        out = log(c, cid, runner.id, "out", KIND, "", status, summary, rev, results, source=source,
                  sample=sample(b"\n".join(sent)), dry_run=dry)
    if dry or not acks:
        return [(out, b"\n".join(sent))]
    gone = {(KIND, o.id): o for o in withdrawn(KIND, gone_rows)}
    generations = {r["id"]: r.get("generation", "") for r in gone_rows}
    answer = receive(c, runner, cid, "acknowledgements",
                     f"{job['id']}:{fingerprint([a.model_dump() for a in acks])}",
                     lambda d: acknowledge(d, acks, gone), source=source)
    closed = [i.id for i, a in zip(answer.message.items, acks, strict=False)
              if i.status == "applied" and (KIND, a.id) in gone and "deleted here" in i.message]
    if closed and answer.message.status != "duplicate":
        with c.lock:
            c.db.executemany("UPDATE erp_withdrawn SET taken_at = ? WHERE company_id = ? AND kind = ? AND id = ? AND "
                             "generation = ? AND taken_at IS NULL",
                             [(answer.message.at, cid, KIND, oid, generations.get(oid, "")) for oid in closed])
    return [(answer.message, b""), (out, b"\n".join(sent))]
