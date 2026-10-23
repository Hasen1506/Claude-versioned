"""The accounts (Enterprise 7.4, S/4 guide §15.1): a double-entry journal from what happens to goods and money, so
the books an accountant keeps follow from the movements and invoices instead of being typed in again.

Every posting that changes the value of stock (Enterprise 6.2's books) is a voucher here, its other side chosen by what
moved the goods:

* a purchase receipt: stock against *goods received, not invoiced* (GR/IR) at the order's price, and the freight, duty
  and handling the receipt was valued with against *freight, duty and handling*; the supplier's invoice clears GR/IR
  against what is owed to the supplier, with the input tax;
* production: what is issued goes into *work in progress*, what is made comes out of it at its value; a job worker's
  charge (Enterprise 7.1) goes into work in progress too, so the order's cost carries it;
* a delivery to a customer: stock against *cost of goods sold*; the customer's invoice is a receivable against sales
  and the output tax (CGST and SGST, or IGST); goods a customer sends back come off the cost of goods sold;
* a transfer: into *stock in transit* when shipped, out of it when received; to another company of the group
  (Enterprise 7.3) the seller's stock goes to its *cost of goods sold to group companies* and the buyer's goods on the
  way come in at the transfer price against *inter-company goods received, not invoiced*, which the inter-company
  invoice clears: a receivable in the seller's books, a payable in the buyer's, both settled by paying;
* a count difference, scrap and a price difference each to an account of their own; the opening balances against
  *opening balances*;
* payments, received and made, against the bank, a cash discount to its own account; a carrier's freight bill
  (Enterprise 6.3) is owed to the carrier.

Each company of the group keeps its own journal. The journal checks itself against the figures it was made from: stock
against the stock books, goods in transit, what customers owe against the open invoices, what is owed to suppliers
against the open supplier invoices and freight bills, GR/IR against the goods received and not invoiced. It is exported
as Tally's import file (an XML envelope of ledgers and vouchers), one per company.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from xml.sax.saxutils import escape, quoteattr

from ..actuals.transfer_price import destination, entity_of, party
from ..actuals.valuation import EPS, run_books
from ..model import Dataset, GoodsMovement, MovementType, SupplierInvoice
from ..model.common import Out
from ..plan.costing import fx

# code → (name, Tally group, nature)
ACCOUNTS: dict[str, tuple[str, str, str]] = {
    "STOCK": ("Stock", "Stock-in-Hand", "asset"),
    "TRANSIT": ("Stock in transit", "Current Assets", "asset"),
    "WIP": ("Work in progress", "Current Assets", "asset"),
    "RECEIVABLES": ("Customers", "Sundry Debtors", "asset"),
    "IC_RECEIVABLES": ("Group companies (owed to us)", "Sundry Debtors", "asset"),
    "INPUT_TAX": ("Input tax credit", "Duties & Taxes", "asset"),
    "BANK": ("Bank", "Bank Accounts", "asset"),
    "PAYABLES": ("Suppliers", "Sundry Creditors", "liability"),
    "IC_PAYABLES": ("Group companies (owed by us)", "Sundry Creditors", "liability"),
    "GRIR": ("Goods received, not invoiced", "Current Liabilities", "liability"),
    "IC_GRIR": ("Inter-company goods received, not invoiced", "Current Liabilities", "liability"),
    "OUT_CGST": ("Output CGST", "Duties & Taxes", "liability"),
    "OUT_SGST": ("Output SGST", "Duties & Taxes", "liability"),
    "OUT_IGST": ("Output IGST", "Duties & Taxes", "liability"),
    "OUT_TAX": ("Output tax", "Duties & Taxes", "liability"),
    "OPENING": ("Opening balances", "Capital Account", "equity"),
    "SALES": ("Sales", "Sales Accounts", "income"),
    "IC_SALES": ("Sales to group companies", "Sales Accounts", "income"),
    "DISC_RECEIVED": ("Cash discount received", "Indirect Incomes", "income"),
    "COGS": ("Cost of goods sold", "Direct Expenses", "expense"),
    "IC_COGS": ("Cost of goods sold to group companies", "Direct Expenses", "expense"),
    "DELIVERY": ("Freight, duty and handling", "Direct Expenses", "expense"),
    "PRICE_DIFF": ("Price differences", "Direct Expenses", "expense"),
    "COUNT_DIFF": ("Stock count differences", "Indirect Expenses", "expense"),
    "SCRAP": ("Scrap", "Indirect Expenses", "expense"),
    "DISC_ALLOWED": ("Cash discount allowed", "Indirect Expenses", "expense"),
    "SUSPENSE": ("Suspense (to put right)", "Suspense A/c", "asset"),
}
PARTY_ACCOUNTS = {"RECEIVABLES", "IC_RECEIVABLES", "PAYABLES", "IC_PAYABLES"}
TAX_OUT = {"cgst_sgst": None, "igst": "OUT_IGST", "": "OUT_TAX"}


class JournalLine(Out):
    account: str
    party: str = ""                        # a customer, supplier, carrier or group company: its id
    location: str = ""
    product: str = ""
    debit: float = 0.0
    credit: float = 0.0


class Voucher(Out):
    number: str
    date: date
    company: str                           # "" = the company itself
    type: str                              # Tally's voucher type: Journal, Sales, Purchase, Credit Note, …
    document: str                          # what it was made from: a movement, an invoice, a payment
    narration: str
    lines: list[JournalLine]

    @property
    def debit(self) -> float:
        return round(sum(ln.debit for ln in self.lines), 2)

    @property
    def credit(self) -> float:
        return round(sum(ln.credit for ln in self.lines), 2)


class AccountRow(Out):
    code: str
    name: str
    group: str                             # Tally's group it belongs under
    nature: str                            # asset, liability, equity, income, expense
    ledger: str                            # its ledger name in Tally


class AccountBalance(Out):
    company: str
    account: str
    name: str
    group: str
    nature: str
    party: str = ""
    party_name: str = ""
    debit: float                           # in the period
    credit: float
    balance: float                         # on the period's last day, + debit


class AccountCheck(Out):
    company: str
    what: str
    journal: float                         # what the journal says
    expected: float                        # what the documents it was made from say
    ok: bool
    why: str = ""


class BooksCompany(Out):
    id: str
    name: str
    tally_name: str
    vouchers: int                          # in the period
    profit: float                          # income less expenses, to the day


class AccountingView(Out):
    as_of: date
    period_start: date
    period_end: date
    currency: str
    companies: list[BooksCompany]
    accounts: list[AccountRow]
    balances: list[AccountBalance]                # per company and account, parties added up
    parties: list[AccountBalance]                 # per company, account and party
    vouchers: list[Voucher]                # in the period, latest first (capped)
    voucher_count: int
    checks: list[AccountCheck]
    notes: list[str] = []


def ledger(ds: Dataset, code: str) -> str:
    return (ds.finance.ledgers.get(code) or "").strip() or ACCOUNTS[code][0]


def _r(v: float) -> float:
    return round(v + 0.0, 2)


def _name(ds: Dataset, pid: str) -> str:
    lo = ds.location_by_id.get(pid)
    if lo is not None:
        return lo.name or pid
    ca = next((c for c in ds.carriers if c.id == pid), None)
    if ca is not None:
        return ca.name or pid
    if pid in ds.entity_by_id or pid == "":
        return party(ds, pid).name
    return pid


# ------------------------------------------------------------------------------------------------ the journal
class _Journal:
    """Watches the stock books post (``run_books``) and writes each posting as a voucher; documents that move money
    only are added after."""

    def __init__(self, ds: Dataset):
        self.ds = ds
        self.vouchers: list[Voucher] = []
        self.contra: dict[str, list[tuple[str, str, str, float]]] = {}   # movement → its other side, for a reversal
        self.state: dict[str, list] = {}   # purchase line → [received, invoiced, [[qty, GR/IR per unit] ahead]]
        self.returns = {r.id for r in ds.returns}
        self.third = {t.id for t in ds.third_party_orders}
        self.jobs = {c.id for c in ds.challans}

    # -- the watch protocol of run_books ----------------------------------------------------------------------------
    def start(self, b, po, kinds, by_id) -> None:
        self.b, self.po, self.kinds, self.by_id = b, po, kinds, by_id
        from ..purchasing.payables import lines_index
        self.lines = lines_index(self.ds, outside=False)
    def _road(self, ref: str | None) -> float:
        return round(self.b.shipped.get(ref or "", [0.0, 0.0])[1], 2)

    def before(self, kind: int, ev) -> None:
        self.n_entries, self.n_diffs = len(self.b.entries), len(self.b.diffs)
        self.road = None
        if kind == 0:
            ref = ev.reference
            if ev.reversal_of and ev.reversal_of in self.by_id:
                ref = self.by_id[ev.reversal_of].reference
            self.road = (ref, self._road(ref))

    def after(self, kind: int, ev) -> None:
        lines: list[tuple[str, str, str, float, str, str]] = []   # (account, company, party, debit+, location, product)
        for e in self.b.entries[self.n_entries:]:         # each posting to the stock, in paise
            lines.append(("STOCK", entity_of(self.ds, e.location), "", e.amount, e.location, e.product))
        for x in self.b.diffs[self.n_diffs:]:
            lines.append(("PRICE_DIFF", entity_of(self.ds, x.location), "", x.amount, x.location, x.product))
        if kind == 0:
            self._movement(ev, lines)
        else:
            self._invoice(ev, lines)

    # -- a goods movement ----------------------------------------------------------------------------------------
    def _movement(self, m: GoodsMovement, lines: list) -> None:
        if m.type is MovementType.STATUS:
            return
        ds, co = self.ds, entity_of(self.ds, m.location)
        q = abs(m.qty)
        road = self._road(self.road[0]) - self.road[1] if self.road and self.road[0] else 0.0
        own: list[tuple[str, str, str, float, str, str]] = []   # the other side, kept for a reversal
        rest, what = "SUSPENSE", m.type.value
        ref = m.reference or ""
        if m.reversal_of:
            orig = self.by_id.get(m.reversal_of)
            f = q / abs(orig.qty) if orig is not None and abs(orig.qty) > EPS else 0.0
            for acc, c, pa, amt in self.contra.get(m.reversal_of, []):
                own.append((acc, c, pa, -amt * f, m.location, m.product))
            if orig is not None and orig.reference in self.state:
                st = self.state[orig.reference]
                st[0] += -q if orig.type is MovementType.RECEIPT else q
            rest, what = "PRICE_DIFF", f"reversal of {m.reversal_of}"
        elif m.type is MovementType.OPENING:
            rest, what = "OPENING", "opening balance"
        elif m.type is MovementType.RECEIPT:
            kind = self.kinds.get(ref)
            if ref in self.po:
                st = self.state.setdefault(ref, [0.0, 0.0, []])
                left, g = q, 0.0
                while left > EPS and st[2]:
                    take = min(left, st[2][0][0])
                    g += take * st[2][0][1]
                    st[2][0][0] -= take
                    left -= take
                    if st[2][0][0] <= EPS:
                        st[2].pop(0)
                g += left * self.po[ref].base
                st[0] += q
                own.append(("GRIR", co, self._supplier(ref), -g, m.location, m.product))
                rest, what = "DELIVERY", f"purchase receipt on {ref}"
            elif kind == "transfer" and abs(road) > 0.004:
                own.append(("TRANSIT", co, "", road, m.location, m.product))
                rest, what = "COUNT_DIFF", f"transfer receipt on {ref}"
            elif kind == "transfer":
                rest, what = "OPENING", f"transfer receipt on {ref}, on the way at go-live"
            elif kind == "production":
                rest, what = "WIP", f"production receipt on {ref}"
            elif ref in self.returns:
                rest, what = "COGS", f"customer return {ref}"
            else:
                what = "receipt" + (f" on {ref}" if ref else "")
        elif m.type is MovementType.ISSUE:
            rest, what = "WIP", "issue to production" + (f" on {ref}" if ref else "")
        elif m.type is MovementType.SALE:
            rest, what = "COGS", "goods issue to a customer" + (f" on {ref}" if ref else "")
        elif m.type is MovementType.SCRAP:
            rest, what = "SCRAP", "scrap"
        elif m.type is MovementType.ADJUSTMENT:
            rest, what = "COUNT_DIFF", "count difference"
        elif m.type is MovementType.RETURN:
            what = "return to supplier" + (f" on {ref}" if ref else "")
            if ref in self.po:
                st = self.state.setdefault(ref, [0.0, 0.0, []])
                st[0] -= q
                own.append(("GRIR", co, self._supplier(ref), q * self.po[ref].base, m.location, m.product))
                rest = "DELIVERY"
        elif m.type is MovementType.TRANSFER_OUT:
            what = "transfer out" + (f" on {ref}" if ref else "")
            to = destination(ds, m) if ref else None
            to_co = entity_of(ds, to) if to else co
            if m.id in self.b.ic_price:              # sold to another company of the group
                own.append(("TRANSIT", to_co, "", road, to or "", m.product))
                own.append(("IC_GRIR", to_co, co, -road, to or "", m.product))
                rest, what = "IC_COGS", f"transfer on {ref} to {party(ds, to_co).name}"
            elif abs(road) > 0.004:
                own.append(("TRANSIT", to_co, "", road, to or "", m.product))
                rest = "PRICE_DIFF"                  # what is left is the rounding of the value on the road
        self.contra[m.id] = [(a, c, pa, amt) for a, c, pa, amt, _l, _p in own]
        self._post(m.date, m.id, "Journal", m.id, f"{what}: {_n(q)} {m.product} at {_name(ds, m.location)}",
                   lines + own, rest, m.location, m.product)

    def _supplier(self, lid: str) -> str:
        info = self.lines.get(lid)
        return info.supplier if info is not None else ""

    # -- a supplier invoice --------------------------------------------------------------------------------------
    def _invoice(self, inv: SupplierInvoice, lines: list) -> None:
        ds = self.ds
        rate = fx(ds, inv.currency)
        sign = -1.0 if inv.credit else 1.0
        from ..purchasing.payables import lines_index
        every = lines_index(ds, {ln.order for ln in inv.lines})
        first = next((every[ln.order] for ln in inv.lines if ln.order in every), None)
        co = entity_of(ds, first.location) if first is not None and _ours(ds, first.location) else ""
        own = []
        for ln in inv.lines:
            amt = ln.qty * ln.price * rate
            info = every.get(ln.order)
            loc = info.location if info is not None else ""
            if ln.order in self.po and inv.bills_goods:
                st = self.state.setdefault(ln.order, [0.0, 0.0, []])
                base = self.po[ln.order].base
                if sign > 0:
                    covered = min(ln.qty, max(0.0, st[0] - st[1]))
                    if ln.qty - covered > EPS:
                        st[2].append([ln.qty - covered, ln.price * rate])
                    st[1] += ln.qty
                    own.append(("GRIR", co, inv.supplier, covered * base + (ln.qty - covered) * ln.price * rate, loc,
                                ln.product))
                else:
                    st[1] -= ln.qty
                    own.append(("GRIR", co, inv.supplier, -ln.qty * base, loc, ln.product))
            elif ln.order in self.po:
                pass                                 # a subsequent debit or credit: on the stock, or a price difference
            elif ln.order in self.third:             # bought for a customer, shipped by the supplier: cost of a sale
                own.append(("COGS", co, "", sign * amt, "", ln.product))
            elif ln.order in self.jobs:              # a job worker's charge: the production order's cost
                own.append(("WIP", co, "", sign * amt, loc, ln.product))
            else:
                own.append(("SUSPENSE", co, "", sign * amt, loc, ln.product))
        if inv.tax:
            own.append(("INPUT_TAX", co, "", sign * inv.tax * rate, "", ""))
        own.append(("PAYABLES", co, inv.supplier, -sign * (inv.net + inv.tax) * rate, "", ""))
        kind = {"invoice": "Purchase", "credit_memo": "Debit Note", "subsequent_debit": "Purchase",
                "subsequent_credit": "Debit Note"}[inv.kind]
        words = inv.kind.replace("_", " ")
        self._post(inv.date, inv.id, kind, inv.id,
                   f"{words} {inv.reference or inv.id} from {_name(ds, inv.supplier)}", lines + own, "DELIVERY", "", "")

    # -- writing a voucher ---------------------------------------------------------------------------------------
    def _post(self, day: date, number: str, vtype: str, doc: str, narration: str, lines: list, rest: str,
              loc: str = "", prod: str = "") -> None:
        by_co: dict[str, list[JournalLine]] = defaultdict(list)
        sums: dict[str, float] = defaultdict(float)
        for acc, c, pa, amt, lo, pr in lines:
            a = _r(amt)
            if abs(a) < 0.005:
                continue
            by_co[c].append(JournalLine(account=acc, party=pa, location=lo, product=pr, debit=max(a, 0.0),
                                        credit=max(-a, 0.0)))
            sums[c] += a
        for c, total in sums.items():
            left = _r(-total)
            if abs(left) >= 0.005:
                by_co[c].append(JournalLine(account=rest, location=loc, product=prod, debit=max(left, 0.0),
                                            credit=max(-left, 0.0)))
        for c, ls in by_co.items():
            if ls:
                self.vouchers.append(Voucher(number=number, date=day, company=c, type=vtype, document=doc,
                                             narration=narration[:240], lines=ls))

    # -- documents that move money only --------------------------------------------------------------------------
    def money(self, day: date) -> None:
        ds = self.ds
        for inv in ds.supplier_invoices:
            if inv.cancelled or inv.date > day:
                continue
            rate = fx(ds, inv.currency)
            sign = -1.0 if inv.credit else 1.0
            co = self._company_of_supplier_invoice(inv)
            for k, p in enumerate(inv.payments, 1):
                if p.date > day:
                    continue
                self._post(p.date, f"{inv.id}/{k}", "Payment" if sign > 0 else "Receipt", inv.id,
                           f"{'paid to' if sign > 0 else 'refund from'} {_name(ds, inv.supplier)} for "
                           f"{inv.reference or inv.id}" + (f", {p.reference}" if p.reference else ""),
                           [("PAYABLES", co, inv.supplier, sign * (p.amount + p.discount) * rate, "", ""),
                            ("BANK", co, "", -sign * p.amount * rate, "", ""),
                            ("DISC_RECEIVED", co, "", -sign * p.discount * rate, "", "")], "SUSPENSE")
        moves = {m.id: m for m in ds.movements}
        by_ret = {r.id: r for r in ds.returns}
        by_inv: dict[str, str] = {}
        for inv in sorted(ds.invoices, key=lambda i: (i.kind != "invoice", i.date)):
            if inv.cancelled or inv.date > day:
                continue
            co = ""
            for ln in inv.lines:
                loc = next((moves[x].location for x in ln.movements if x in moves), None)
                if loc is None and ln.ret in by_ret:
                    loc = by_ret[ln.ret].location
                if loc is not None:
                    co = entity_of(ds, loc)
                    break
            else:
                co = by_inv.get(inv.reference or "", "")
            by_inv[inv.id] = co
            s = -1.0 if inv.kind == "credit_note" else 1.0
            ls = [("RECEIVABLES", co, inv.customer, s * inv.total, "", "")]
            ls += [("SALES", co, "", -s * ln.amount, "", ln.product) for ln in inv.lines]
            for name, _rate, _base, t in inv.tax_parts:
                acc = {"CGST": "OUT_CGST", "SGST": "OUT_SGST", "IGST": "OUT_IGST"}.get(name, "OUT_TAX")
                ls.append((acc, co, "", -s * t, "", ""))
            self._post(inv.date, inv.id, "Sales" if s > 0 else "Credit Note", inv.id,
                       f"{'invoice' if s > 0 else 'credit note'} {inv.id} to {_name(ds, inv.customer)}", ls, "SUSPENSE")
            for k, p in enumerate(inv.payments, 1):
                if p.date > day:
                    continue
                self._post(p.date, f"{inv.id}/{k}", "Receipt" if s > 0 else "Payment", inv.id,
                           f"{'received from' if s > 0 else 'paid back to'} {_name(ds, inv.customer)} for {inv.id}"
                           + (f", {p.reference}" if p.reference else ""),
                           [("BANK", co, "", s * p.amount, "", ""), ("DISC_ALLOWED", co, "", s * p.discount, "", ""),
                            ("RECEIVABLES", co, inv.customer, -s * (p.amount + p.discount), "", "")], "SUSPENSE")
        for inv in ds.intercompany_invoices:
            if inv.cancelled or inv.date > day:
                continue
            s = inv.sign
            out = self._tax_lines(inv.split, inv.seller, -s * inv.tax)
            if inv.seller == inv.buyer:              # between two registrations of one company: the tax only
                self._post(inv.date, inv.id, "Journal", inv.id,
                           f"tax on the transfer {inv.id}, {_name(ds, inv.ship_from)} to {_name(ds, inv.ship_to)}",
                           [("INPUT_TAX", inv.buyer, "", s * inv.tax, "", ""), *out], "SUSPENSE")
                continue
            word = "invoice" if s > 0 else "credit note"
            self._post(inv.date, inv.id, "Sales" if s > 0 else "Credit Note", inv.id,
                       f"inter-company {word} {inv.id} to {party(ds, inv.buyer).name}",
                       [("IC_RECEIVABLES", inv.seller, inv.buyer, s * inv.total, "", ""),
                        ("IC_SALES", inv.seller, "", -s * inv.net, "", ""), *out], "SUSPENSE")
            self._post(inv.date, inv.id, "Purchase" if s > 0 else "Debit Note", inv.id,
                       f"inter-company {word} {inv.id} from {party(ds, inv.seller).name}",
                       [("IC_GRIR", inv.buyer, inv.seller, s * inv.net, "", ""),
                        ("INPUT_TAX", inv.buyer, "", s * inv.tax, "", ""),
                        ("IC_PAYABLES", inv.buyer, inv.seller, -s * inv.total, "", "")], "SUSPENSE")
            for k, p in enumerate(inv.payments, 1):
                if p.date > day:
                    continue
                note = f"settled {inv.id}" + (f", {p.reference}" if p.reference else "")
                self._post(p.date, f"{inv.id}/{k}", "Receipt" if s > 0 else "Payment", inv.id,
                           f"{note}: from {party(ds, inv.buyer).name}" if s > 0 else
                           f"{note}: paid back to {party(ds, inv.buyer).name}",
                           [("BANK", inv.seller, "", s * p.amount, "", ""),
                            ("IC_RECEIVABLES", inv.seller, inv.buyer, -s * p.amount, "", "")], "SUSPENSE")
                self._post(p.date, f"{inv.id}/{k}", "Payment" if s > 0 else "Receipt", inv.id,
                           f"{note}: to {party(ds, inv.seller).name}" if s > 0 else
                           f"{note}: paid back by {party(ds, inv.seller).name}",
                           [("IC_PAYABLES", inv.buyer, inv.seller, s * p.amount, "", ""),
                            ("BANK", inv.buyer, "", -s * p.amount, "", "")], "SUSPENSE")
        for fo in ds.freight_orders:
            if fo.status != "settled" or fo.billed is None or fo.settled_on is None or fo.settled_on > day:
                continue
            co = entity_of(ds, fo.ship_from)
            carrier = fo.carrier or ""
            self._post(fo.settled_on, fo.id, "Journal", fo.id,
                       f"freight bill {fo.bill or fo.id} from {_name(ds, carrier) or 'the carrier'}: "
                       f"{_name(ds, fo.ship_from)} to {_name(ds, fo.ship_to)}",
                       [("DELIVERY", co, "", fo.billed, fo.ship_from, ""),
                        ("PAYABLES", co, carrier, -fo.billed, "", "")], "SUSPENSE")

    def _tax_lines(self, split: str, co: str, amt: float) -> list:
        if abs(amt) < 0.005:
            return []
        if split == "cgst_sgst":
            half = round(amt / 2, 2)
            return [("OUT_CGST", co, "", half, "", ""), ("OUT_SGST", co, "", amt - half, "", "")]
        return [(TAX_OUT.get(split) or "OUT_TAX", co, "", amt, "", "")]

    def _company_of_supplier_invoice(self, inv: SupplierInvoice) -> str:
        from ..purchasing.payables import lines_index
        every = lines_index(self.ds, {ln.order for ln in inv.lines})
        first = next((every[ln.order] for ln in inv.lines if ln.order in every), None)
        return entity_of(self.ds, first.location) if first is not None and _ours(self.ds, first.location) else ""


def _ours(ds: Dataset, loc: str) -> bool:
    lo = ds.location_by_id.get(loc)
    return lo is not None and lo.type.value not in ("supplier", "customer")


def _n(q: float) -> str:
    return f"{q:,.0f}" if abs(q - round(q)) < 1e-6 else f"{q:,.3f}".rstrip("0").rstrip(".")


def journal(ds: Dataset, day: date) -> tuple[list[Voucher], object]:
    """Every voucher up to ``day``, in date order, and the stock books they were made with."""
    j = _Journal(ds)
    b, _std = run_books(ds, day, "entity", watch=j)
    j.money(day)
    order = {"Journal": 0, "Purchase": 1, "Debit Note": 1, "Sales": 2, "Credit Note": 2, "Receipt": 3, "Payment": 3}
    j.vouchers.sort(key=lambda v: (v.date, order.get(v.type, 4)))
    return j.vouchers, b


def _day(ds: Dataset) -> date:
    return max([ds.settings.planning_start, *(m.date for m in ds.movements),
                *(i.date for i in ds.supplier_invoices if not i.cancelled), *(i.date for i in ds.invoices),
                *(i.date for i in ds.intercompany_invoices),
                *(p.date for i in [*ds.invoices, *ds.supplier_invoices, *ds.intercompany_invoices] for p in i.payments),
                *(f.settled_on for f in ds.freight_orders if f.settled_on is not None)])


def _period(ds: Dataset, end: date, start: date | None) -> date:
    if start is not None:
        return start
    first = 4 if ds.settings.currency == "INR" else 1          # the financial year: April in India
    y = end.year if end.month >= first else end.year - 1
    return date(y, first, 1)


def view(ds: Dataset, period_start: date | None = None, period_end: date | None = None,
         limit: int = 500) -> AccountingView:
    """The journal and the balances of every company of the group on ``period_end`` (default: the latest document),
    the vouchers of the period (default: the financial year to that day), and the checks against the documents."""
    end = period_end or _day(ds)
    start = _period(ds, end, period_start)
    if start > end:
        start = end
    vs, b = journal(ds, end)
    ids = ["", *(e.id for e in ds.entities)]
    bal: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])   # debit, credit, balance
    count: dict[str, int] = defaultdict(int)
    for v in vs:
        inside = start <= v.date <= end
        if inside:
            count[v.company] += 1
        for ln in v.lines:
            row = bal[(v.company, ln.account, ln.party if ln.account in PARTY_ACCOUNTS else "")]
            if inside:
                row[0] += ln.debit
                row[1] += ln.credit
            row[2] += ln.debit - ln.credit

    def bal_row(co: str, acc: str, pa: str, x: list[float], named: bool = False) -> AccountBalance:
        name, group, nature = ACCOUNTS[acc]
        return AccountBalance(company=co, account=acc, name=name, group=group, nature=nature, party=pa,
                       party_name=_name(ds, pa) if named else "",
                       debit=_r(x[0]), credit=_r(x[1]), balance=_r(x[2]))

    parties = [bal_row(co, acc, pa, x, True) for (co, acc, pa), x in sorted(bal.items()) if acc in PARTY_ACCOUNTS]
    totals: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for (co, acc, _pa), x in bal.items():
        t = totals[(co, acc)]
        for i in range(3):
            t[i] += x[i]
    order = list(ACCOUNTS)
    balances = [bal_row(co, acc, "", x) for (co, acc), x in sorted(totals.items(), key=lambda kv: (
        ids.index(kv[0][0]) if kv[0][0] in ids else 99, order.index(kv[0][1])))
        if abs(x[0]) + abs(x[1]) + abs(x[2]) >= 0.005]
    companies = []
    for co in ids:
        profit = -sum(x[2] for (c, acc), x in totals.items() if c == co and ACCOUNTS[acc][2] in ("income", "expense"))
        pa = party(ds, co)
        tally = (ds.finance.tally_company if co == "" else "") or pa.name
        companies.append(BooksCompany(id=co, name=pa.name, tally_name=tally, vouchers=count.get(co, 0),
                                    profit=_r(profit)))
    checks = _checks(ds, end, b, totals, vs)
    notes = []
    if any(x.account == "SUSPENSE" and abs(x.balance) >= 0.005 for x in balances):
        notes.append("Something is on the suspense account: stock moved without an order the journal knows (a receipt "
                     "or a transfer with no order, a return with no purchase order, an invoice line for an order it "
                     "does not know). It stays there until it is put right.")
    for x in balances:
        if x.account == "DELIVERY" and x.balance < -0.005:
            notes.append(f"{ds.settings.currency} {-x.balance:,.2f} of freight, duty and handling was taken into the stock "
                         f"of {party(ds, x.company).name} with its purchases and is not billed here yet: the customs "
                         "duty paid and the forwarders' and carriers' bills clear it.")
        if x.account == "WIP" and x.balance < -0.005:
            notes.append(f"Work in progress of {party(ds, x.company).name} is below zero ({ds.settings.currency} "
                         f"{x.balance:,.2f}): goods were made without their parts issued to the order (receipts with "
                         "no backflush, or made before go-live), so what they cost is not matched yet.")
    from ..sales import to_bill
    due = [b for b in to_bill(ds) if b.delivered_on <= end]
    if due:
        worth = sum(b.value or 0.0 for b in due)
        notes.append(f"{len(due)} deliveries are not invoiced yet" + (f" ({ds.settings.currency} {worth:,.2f} at their "
                     "prices)" if worth else "") + ": their cost of goods sold is in the books, their sales are not.")
    if not vs:
        notes.append("Nothing posted yet: the journal fills from stock movements, invoices and payments.")
    vs_period = [v for v in vs if start <= v.date <= end]
    return AccountingView(
        as_of=end, period_start=start, period_end=end, currency=ds.settings.currency, companies=companies,
        accounts=[AccountRow(code=k, name=v[0], group=v[1], nature=v[2], ledger=ledger(ds, k))
                  for k, v in ACCOUNTS.items()],
        balances=balances, parties=parties, vouchers=list(reversed(vs_period))[:limit],
        voucher_count=len(vs_period), checks=checks, notes=notes)


def _checks(ds: Dataset, day: date, b, totals, vs: list[Voucher]) -> list[AccountCheck]:
    """The journal against the documents it was made from, company by company."""
    ids = ["", *(e.id for e in ds.entities)]
    out: list[AccountCheck] = []

    def bal(co: str, acc: str) -> float:
        return totals.get((co, acc), [0.0, 0.0, 0.0])[2]

    def add(co: str, what: str, journal: float, expected: float, why: str) -> None:
        ok = abs(journal - expected) < 0.05
        out.append(AccountCheck(company=co, what=what, journal=_r(journal), expected=_r(expected), ok=ok,
                         why="" if ok else why))

    stock: dict[str, float] = defaultdict(float)
    for (loc, _p), n in b.nodes.items():
        stock[entity_of(ds, loc)] += round(n.value, 2)
    road: dict[str, float] = defaultdict(float)
    for ref, (q, v) in b.shipped.items():
        if q > EPS:
            to = _to_of(ds, ref)
            road[entity_of(ds, to)] += v
    rec: dict[str, float] = defaultdict(float)
    by_inv = {}
    for v in vs:
        if v.type in ("Sales", "Credit Note") and any(ln.account == "RECEIVABLES" for ln in v.lines):
            by_inv[v.document] = v.company
    for inv in ds.invoices:
        if not inv.cancelled and inv.date <= day:
            left = inv.total - sum(p.amount + p.discount for p in inv.payments if p.date <= day)
            rec[by_inv.get(inv.id, "")] += left if inv.kind == "invoice" else -left
    pay: dict[str, float] = defaultdict(float)
    j = _Journal(ds)
    for inv in ds.supplier_invoices:
        if not inv.cancelled and inv.date <= day:
            left = inv.total - sum(p.amount + p.discount for p in inv.payments if p.date <= day)
            pay[j._company_of_supplier_invoice(inv)] += (-1 if inv.credit else 1) * left * fx(ds, inv.currency)
    for fo in ds.freight_orders:
        if fo.status == "settled" and fo.billed is not None and fo.settled_on is not None and fo.settled_on <= day:
            pay[entity_of(ds, fo.ship_from)] += fo.billed
    grir: dict[str, float] = defaultdict(float)
    from ..purchasing.payables import lines_index
    lines = lines_index(ds, outside=False)
    got: dict[str, float] = defaultdict(float)
    for m in ds.movements:
        if m.date <= day and m.reference in lines and m.type in (MovementType.RECEIPT, MovementType.RETURN):
            got[m.reference] += m.net if m.type is MovementType.RECEIPT else -m.net
    billed: dict[str, float] = defaultdict(float)
    billed_at: dict[str, float] = {}                   # the price the line was last invoiced at
    for inv in sorted(ds.supplier_invoices, key=lambda i: i.date):
        if not inv.cancelled and inv.date <= day and inv.bills_goods:
            for ln in inv.lines:
                billed[ln.order] += (-1 if inv.kind == "credit_memo" else 1) * ln.qty
                if inv.kind == "invoice":
                    billed_at[ln.order] = ln.price * fx(ds, inv.currency)
    for lid in set(got) | set(billed):
        info = lines.get(lid)
        if info is None or info.price is None:
            continue
        open_ = got[lid] - billed[lid]                 # + received, not invoiced; − invoiced ahead of the goods
        at = info.price * fx(ds, info.currency) if open_ >= 0 else billed_at.get(lid, info.price * fx(ds, info.currency))
        grir[entity_of(ds, info.location)] -= open_ * at
    ic_rec: dict[str, float] = defaultdict(float)
    ic_pay: dict[str, float] = defaultdict(float)
    for inv in ds.intercompany_invoices:
        if not inv.cancelled and inv.date <= day and inv.seller != inv.buyer:
            left = inv.total - sum(p.amount + p.discount for p in inv.payments if p.date <= day)
            ic_rec[inv.seller] += inv.sign * left
            ic_pay[inv.buyer] += inv.sign * left
    off = [v for v in vs if abs(v.debit - v.credit) >= 0.005]
    for co in ids:
        add(co, "Debits equal credits", sum(v.debit for v in vs if v.company == co),
            sum(v.credit for v in vs if v.company == co),
            f"{len([v for v in off if v.company == co])} vouchers do not balance")
        add(co, "Stock against the stock books", bal(co, "STOCK"), stock.get(co, 0.0),
            "a stock posting without a voucher")
        add(co, "Stock in transit against the transfers on the way", bal(co, "TRANSIT"), road.get(co, 0.0),
            "a transfer shipped or received without its voucher")
        add(co, "Customers against the open invoices", bal(co, "RECEIVABLES"), rec.get(co, 0.0),
            "an invoice or payment without its voucher")
        add(co, "Suppliers against the open invoices and freight bills", -bal(co, "PAYABLES"), pay.get(co, 0.0),
            "a supplier invoice, payment or freight bill without its voucher")
        add(co, "GR/IR against the goods received and not invoiced", bal(co, "GRIR"), grir.get(co, 0.0),
            "a receipt or invoice without its voucher, or goods invoiced ahead at more than one price")
        if ds.entities:
            add(co, "Group companies owe it, against the open inter-company invoices", bal(co, "IC_RECEIVABLES"),
                ic_rec.get(co, 0.0), "an inter-company invoice or settlement without its voucher")
            add(co, "It owes group companies, against the open inter-company invoices", -bal(co, "IC_PAYABLES"),
                ic_pay.get(co, 0.0), "an inter-company invoice or settlement without its voucher")
    return out


def _to_of(ds: Dataset, ref: str) -> str:
    rc = next((r for r in ds.receipts if r.id == ref), None)
    if rc is not None:
        return rc.location
    co = next((c for c in ds.closed_orders if c.id == ref), None)
    return co.location if co is not None else ""


# ------------------------------------------------------------------------------------------------ Tally
def _amt(v: float) -> str:
    return f"{v:.2f}"


def _td(d: date) -> str:
    return d.strftime("%Y%m%d")


def tally_xml(ds: Dataset, company: str = "", period_start: date | None = None,
              period_end: date | None = None) -> str:
    """One company's ledgers and vouchers of the period as Tally's import file (Gateway of Tally → Import →
    Vouchers). A debit is a negative amount marked deemed positive, a credit a positive one, as Tally keeps them."""
    v = view(ds, period_start, period_end, limit=10**9)
    if company and company not in ds.entity_by_id:
        raise ValueError(f"there is no company {company}")
    row = next(c for c in v.companies if c.id == company)
    vs = [x for x in reversed(v.vouchers) if x.company == company]

    def lname(ln: JournalLine) -> str:
        if ln.account in PARTY_ACCOUNTS and (ln.party or ln.account.startswith("IC_")):
            return _name(ds, ln.party)
        return ledger(ds, ln.account)

    masters: dict[str, str] = {}
    for x in vs:
        for ln in x.lines:
            masters.setdefault(lname(ln), ACCOUNTS[ln.account][1])
    out = ["<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC>"
           "<REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES>"
           f"<SVCURRENTCOMPANY>{escape(row.tally_name)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>"
           "<REQUESTDATA>"]
    for name, group in sorted(masters.items()):
        out.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME={quoteattr(name)} ACTION="Create">'
                   f"<NAME.LIST><NAME>{escape(name)}</NAME></NAME.LIST><PARENT>{escape(group)}</PARENT>"
                   + ("<ISBILLWISEON>Yes</ISBILLWISEON>" if group in ("Sundry Debtors", "Sundry Creditors") else "")
                   + "</LEDGER></TALLYMESSAGE>")
    for x in vs:
        ents = []
        merged: dict[str, float] = defaultdict(float)
        for ln in x.lines:
            merged[lname(ln)] += ln.debit - ln.credit
        for name, net in merged.items():
            if abs(net) < 0.005:
                continue
            ents.append(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(name)}</LEDGERNAME>"
                        f"<ISDEEMEDPOSITIVE>{'Yes' if net > 0 else 'No'}</ISDEEMEDPOSITIVE>"
                        f"<AMOUNT>{_amt(-net)}</AMOUNT></ALLLEDGERENTRIES.LIST>")
        out.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE={quoteattr(x.type)} ACTION="Create">'
                   f"<DATE>{_td(x.date)}</DATE><VOUCHERTYPENAME>{escape(x.type)}</VOUCHERTYPENAME>"
                   f"<VOUCHERNUMBER>{escape(x.number)}</VOUCHERNUMBER><REFERENCE>{escape(x.document)}</REFERENCE>"
                   f"<NARRATION>{escape(x.narration)}</NARRATION>{''.join(ents)}</VOUCHER></TALLYMESSAGE>")
    out.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return "".join(out)


def csv_rows(v: AccountingView, ds: Dataset) -> list[list[str]]:
    """The period's vouchers, one row per line, for a spreadsheet."""
    rows = [["company", "date", "voucher", "type", "document", "narration", "account", "ledger", "party", "location",
             "product", "debit", "credit"]]
    for x in reversed(v.vouchers):
        for ln in x.lines:
            rows.append([party(ds, x.company).name, x.date.isoformat(), x.number, x.type, x.document, x.narration,
                         ln.account, ledger(ds, ln.account), _name(ds, ln.party) if ln.party else "", ln.location,
                         ln.product, _amt(ln.debit), _amt(ln.credit)])
    return rows


__all__ = ["ACCOUNTS", "AccountRow", "AccountingView", "AccountBalance", "AccountCheck", "BooksCompany", "JournalLine", "Voucher",
           "csv_rows", "journal", "ledger", "tally_xml", "view"]

