"""Who owns a place, under which tax registration, and what one company charges another for a transfer (Enterprise
7.3). Kept apart from the inter-company view so the stock valuation can price a shipment without importing it."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..model import Dataset, GoodsMovement, MovementType, TransferPrice

EPS = 1e-9


@dataclass(frozen=True)
class Party:
    id: str                                # "" = the company itself
    name: str
    tax_id: str
    region: str
    address: str


def entity_of(ds: Dataset, loc: str | None) -> str:
    lo = ds.location_by_id.get(loc or "")
    return (lo.entity or "") if lo is not None else ""


def party(ds: Dataset, eid: str) -> Party:
    e = ds.entity_by_id.get(eid) if eid else None
    if e is None:
        s = ds.settings
        return Party("", s.company_name, s.company_tax_id, s.company_region, s.company_address)
    return Party(e.id, e.name or e.id, e.tax_id, e.region, e.address)


def registration(ds: Dataset, loc: str | None) -> tuple[str, str]:
    """The (tax id, region) a place ships or receives under: its own registration, else its company's. With a GSTIN
    the state is the GSTIN's (a place's region is a sales region); without one, the company's region."""
    lo = ds.location_by_id.get(loc or "")
    p = party(ds, entity_of(ds, loc))
    tax = (lo.tax_id.strip() if lo is not None else "") or p.tax_id.strip()
    return (tax.upper(), "") if tax else ("", p.region)


def crossing(ds: Dataset, frm: str | None, to: str | None) -> str:
    """What a transfer from ``frm`` to ``to`` is: "entity" between two companies, "registration" between two GST
    registrations of one company (still a taxable supply), "" inside one registration."""
    if not frm or not to or frm == to:
        return ""
    if entity_of(ds, frm) != entity_of(ds, to):
        return "entity"
    a, b = registration(ds, frm)[0], registration(ds, to)[0]
    return "registration" if a and b and a != b else ""


def destination(ds: Dataset, m: GoodsMovement) -> str | None:
    """Where a transfer's goods issue goes: the place it names, else the transfer's receiving place."""
    if m.counterparty:
        return m.counterparty
    rc = next((r for r in ds.receipts if r.id == m.reference), None)
    if rc is not None:
        return rc.location
    co = next((c for c in ds.closed_orders if c.id == m.reference and c.kind == "transfer"), None)
    return co.location if co is not None else None


def source_of(ds: Dataset, m: GoodsMovement) -> str | None:
    """Where a transfer's receipt comes from: the place it names, else the transfer's sending place."""
    from .stock import counterparty
    if m.counterparty:
        return m.counterparty
    rc = next((r for r in ds.receipts if r.id == m.reference), None)
    if rc is not None:
        rv = next((r for r in rc.reservations if r.product == rc.product and r.location != rc.location), None)
        return rv.location if rv else counterparty(ds, rc)
    co = next((c for c in ds.closed_orders if c.id == m.reference and c.kind == "transfer"), None)
    return co.counterparty if co is not None else None


def _score(r: TransferPrice) -> tuple[int, int, int]:
    return (r.product is not None, r.seller is not None, r.buyer is not None)


def rule(ds: Dataset, seller: str, buyer: str, product: str, on: date) -> TransferPrice | None:
    """The transfer price rule for a shipment: the most specific that fits (a product's before all products, a named
    seller, then a named buyer), the latest valid on the day among equals."""
    fits = [r for r in ds.transfer_prices
            if (r.seller is None or r.seller == seller) and (r.buyer is None or r.buyer == buyer)
            and (r.product is None or r.product == product) and (r.valid_from is None or r.valid_from <= on)]
    if not fits:
        return None
    return max(fits, key=lambda r: (_score(r), r.valid_from or date.min))


def cost(ds: Dataset, std: dict, loc: str, product: str) -> float:
    v = std.get((loc, product))
    if v is None:
        p = ds.product_by_id.get(product)
        v = p.standard_cost if p is not None and p.standard_cost is not None else 0.0
    return float(v)


def price(ds: Dataset, std: dict, frm: str, to: str, product: str, on: date) -> tuple[float, str]:
    """The price per base unit of a shipment from ``frm`` to ``to`` on ``on``, and how it was found, in words. With no
    rule it is the planned unit value where it leaves: the value GST takes for a supply to a registration of one's own
    (rule 28) and no profit between companies."""
    seller, buyer = entity_of(ds, frm), entity_of(ds, to)
    c = cost(ds, std, frm, product)
    r = rule(ds, seller, buyer, product, on) if seller != buyer else None
    if r is None:
        return round(c, 2), "at cost: no transfer price" if seller != buyer else "at cost"
    if r.method == "fixed":
        return round(float(r.price or 0.0), 2), f"fixed ({r.id})"
    if r.method == "resale_minus":
        p = ds.product_by_id.get(product)
        if p is None or p.price is None:
            return round(c, 2), f"at cost: {product} has no selling price for {r.id}"
        return round(p.price * (1.0 - r.markup), 2), f"selling price less {r.markup:.1%} ({r.id})"
    return round(c * (1.0 + r.markup), 2), f"cost plus {r.markup:.1%} ({r.id})"


def shipments(ds: Dataset, journal: list[GoodsMovement] | None = None) -> list[tuple[GoodsMovement, str, float]]:
    """Transfers' goods issues that cross a company or a registration: (the issue, where it goes, quantity net of
    reversals)."""
    movs = ds.movements if journal is None else journal
    back: dict[str, float] = {}
    for m in movs:
        if m.reversal_of and m.type is MovementType.TRANSFER_OUT:
            back[m.reversal_of] = back.get(m.reversal_of, 0.0) + abs(m.qty)
    out = []
    for m in movs:
        if m.type is not MovementType.TRANSFER_OUT or m.reversal_of:
            continue
        to = destination(ds, m)
        if crossing(ds, m.location, to):
            out.append((m, to or "", max(0.0, abs(m.qty) - back.get(m.id, 0.0))))
    return out


def billed(ds: Dataset) -> dict[str, tuple[float, float]]:
    """Per shipment: (quantity billed net of credit notes, the last price billed)."""
    out: dict[str, tuple[float, float]] = {}
    for inv in ds.intercompany_invoices:
        if inv.cancelled:
            continue
        for ln in inv.lines:
            q, p = out.get(ln.movement, (0.0, ln.price))
            out[ln.movement] = (q + inv.sign * ln.qty, ln.price if inv.kind == "invoice" else p)
    return out


def shipment_prices(ds: Dataset, std: dict, journal: list[GoodsMovement] | None = None) -> dict[str, float]:
    """The price each shipment between two companies is booked at: what it was billed at, else its transfer price."""
    bills = billed(ds)
    out = {}
    for m, to, _q in shipments(ds, journal):
        if crossing(ds, m.location, to) != "entity":
            continue
        b = bills.get(m.id)
        out[m.id] = b[1] if b is not None else price(ds, std, m.location, to, m.product, m.date)[0]
    return out
