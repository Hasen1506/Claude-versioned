"""Ask the plan (enterprise plan 5.2): a question in plain words answered from the plan's own records.

Four kinds of question are understood, each answered with the records it rests on cited by id, so every sentence can
be checked on the page the citation opens:

* **why late**: "why is the kettle late at Ecom?", "why is MO-0003-01 late?". Each late demand is followed down its
  pegging: the supply that reaches it late, and what holds that supply up (an input it waits for, a lead time longer
  than the time left, the firm zone, a machine that is full, a firm receipt that comes late, or no supply at all),
  down to the record at the root.
* **what if**: "what if demand rises 20 %?", "what if Shree Metals is out?", "what if LINE-1 is down for a week?".
  The question becomes what-if chips (whatif.py), planned on a copy; the answer is the change in cost, service and
  late demand, and where it lands.
* **who owns**: "who owns the kettle problems?". The owners of the open exceptions on it, and the owner rules that
  route new ones.
* **what is at risk**: the exception inbox's top items, by money at risk.

An answer proposes what to do: the inbox's one-click fixes for the items the answer reaches (tried on a copy and kept
by a person, tower/fix.py), or a what-if kept as a stored scenario. Nothing is changed by asking.

The words are read by rules, not by a language model: names and ids from the company's own records, a few verbs, and
numbers with their units. A question it cannot read is answered with questions it can, built from this company.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, ValidationError

from ..model import Dataset
from ..model.common import Out
from ..plan import PlanResult
from ..plan.leadtime import resource_calendar
from ..plan.result import LateDemand, Peg, PlannedOrder, Requirement
from ..plan.trace import TraceIndex, index as trace_index
from ..time.capacity import hours_between, overtime_between
from ..whatif import (AddShiftChip, Chip, CustomerPriceChip, DemandChip, FxChip, LaneDelayChip, LeadTimeChip,
                      MachineDownChip, SafetyDaysChip, ScenarioOut, SupplierOutChip, WhatIfError, _metrics,
                      apply_chips, chip_label)
from .result import WorkItem

Intent = Literal["why_late", "what_if", "who_owns", "at_risk", "unknown"]
CiteKind = Literal["product", "location", "customer", "supplier", "resource", "order", "receipt", "demand",
                   "exception", "rule"]
DEPTH = 6               # levels of supply followed down, as the pegging tree shows
SHOWN = 6               # findings listed; the rest are counted


class Cite(Out):
    """A record an answer rests on, and where it is seen in the application."""
    kind: CiteKind
    id: str
    label: str = ""
    href: str = ""


class Step(Out):
    text: str
    cites: list[Cite] = []


class Finding(Out):
    text: str
    cites: list[Cite] = []
    chain: list[Step] = []           # why late: from the demand down to the record at the root


class Proposal(Out):
    """Something to do about the answer. A fix is tried on a copy and kept by a person (``/api/tower/fix``, then
    the edits are applied in the browser); a scenario is kept as a stored what-if (``/api/whatif/keep``)."""
    kind: Literal["fix", "scenario", "open"]
    label: str
    key: str = ""                    # fix / open: the inbox item (WorkItem.key)
    message: str = ""                # the exception it acts on
    protects: float = 0.0
    costs: float | None = None
    one_click: bool = False
    why_not: str = ""
    href: str = ""
    chips: list[Chip] = []           # scenario: the what-if to keep
    name: str = ""                   # scenario: the name it is kept under


class AskAnswer(Out):
    question: str
    intent: Intent
    understood: str                  # the question as it was read, with the records it names
    answer: str                      # the answer in one or two sentences
    findings: list[Finding] = []
    proposals: list[Proposal] = []
    suggestions: list[str] = []      # questions this company's data can answer
    scenario: ScenarioOut | None = None    # what if: the plan with the change, against the plan now (deltas set)
    currency: str = ""
    more: int = 0                    # findings not listed


class AskRequest(Out):
    question: str = Field(min_length=1, max_length=500)


# ------------------------------------------------------------------------------------------------ reading the question
@dataclass(frozen=True)
class Ent:
    kind: str                        # product, location, customer, supplier, resource, order, receipt, demand, currency
    id: str


_TOKEN = re.compile(r"[\w][\w.\-/#]*[\w#]|[\w]", re.UNICODE)
_STOP = {"the", "a", "an", "of", "for", "at", "in", "on", "to", "is", "are", "why", "what", "who", "if", "late", "and",
         "or", "with", "from", "our", "my", "we", "it", "this", "that", "be", "by", "all", "any", "out", "down", "up",
         "stock", "plan", "demand", "order", "orders", "owns", "owner", "short", "risk", "week", "weeks", "days", "day",
         "problem", "problems", "units", "how", "much", "when", "will", "does", "do", "can", "there", "not", "has",
         "have", "go", "goes", "take", "takes", "longer", "rise", "rises", "via", "through", "more", "less", "than",
         "per", "cent", "percent", "suppose", "happens", "would", "was", "were", "today", "now", "price", "prices",
         "time", "lead", "shift", "safety", "route", "routes", "whose", "responsible", "should", "first"}


def _tokens(text: str) -> list[str]:
    return [t.lower().rstrip(".") or t.lower() for t in _TOKEN.findall(text)]


class _Vocab:
    """The company's names and ids, looked up by the run of words that spells them."""

    FUZZY = ("product", "location", "customer", "supplier", "resource")

    def __init__(self, ds: Dataset, plan: PlanResult | None) -> None:
        self.phrases: dict[tuple[str, ...], set[Ent]] = defaultdict(set)
        self.words: dict[str, set[Ent]] = defaultdict(set)       # a word of a name, for names said in part
        self.longest = 1
        for p in ds.products:
            self._add(Ent("product", p.id), p.id, p.name)
        for loc in ds.locations:
            kind = {"customer": "customer", "supplier": "supplier"}.get(loc.type.value, "location")
            self._add(Ent(kind, loc.id), loc.id, loc.name)
        for r in ds.resources:
            self._add(Ent("resource", r.id), r.id, r.name)
        for cur in ds.settings.fx_rates:
            self._add(Ent("currency", cur.upper()), cur)
        for rc in ds.receipts:
            self._add(Ent("receipt", rc.id), rc.id)
        for po in ds.purchase_orders:
            self._add(Ent("receipt", po.id), po.id)
        for d in ds.demand:
            if d.id:
                self._add(Ent("demand", f"D:{d.id}"), d.id)
            if d.order:
                self._add(Ent("demand", f"O:{d.order}"), d.order)
        if plan is not None:
            for o in plan.orders:
                self._add(Ent("order", o.id), o.id)

    def _add(self, e: Ent, *names: str) -> None:
        for n in names:
            t = tuple(_tokens(n or ""))
            if t:
                self.phrases[t].add(e)
                self.longest = max(self.longest, len(t))
            if e.kind in self.FUZZY:
                for w in _words(n or ""):
                    self.words[w].add(e)

    def find(self, text: str) -> list[Ent]:
        """The records the text names: the longest run of words that spells a name or id wins. A name said in part
        ("the 10 HP export pump") names the records of a kind nothing spelled out whose names share the most of
        its words."""
        toks = _tokens(text)
        out: list[Ent] = []
        left: list[str] = []
        i = 0
        while i < len(toks):
            for n in range(min(self.longest, len(toks) - i), 0, -1):
                hit = self.phrases.get(tuple(toks[i:i + n]))
                if hit:
                    out += sorted(hit, key=lambda e: (e.kind, e.id))
                    i += n
                    break
            else:
                left.append(toks[i])
                i += 1
        have = {_family(e.kind) for e in out}
        words = {w for t in left for w in _words(t)}
        # each word names one kind of record: the kind whose names share the most words takes them (a product before
        # a place before a machine), and the next kind is read from the words left ("mixer grinders" are the products,
        # not the line named after them)
        for _ in range(3):
            best: tuple[int, int, str, list[Ent], set[str]] | None = None
            for fam in ("product", "place", "resource"):
                if fam in have:
                    continue
                score: dict[Ent, set[str]] = defaultdict(set)
                for w in words:
                    for e in self.words.get(w, ()):
                        if _family(e.kind) == fam:
                            score[e].add(w)
                cands = {e: ws for e, ws in score.items() if any(len(w) >= 3 and not w.isdigit() for w in ws)}
                if not cands:
                    continue
                n = max(len(ws) for ws in cands.values())
                top = sorted((e for e, ws in cands.items() if len(ws) == n), key=lambda e: e.id)
                order = ("product", "place", "resource").index(fam)
                if len(top) <= 12 and (best is None or (n, -order) > (best[0], best[1])):
                    best = (n, -order, fam, top, set().union(*(cands[e] for e in top)))
            if best is None:
                break
            out += best[3]
            have.add(best[2])
            words -= best[4]
        seen: set[Ent] = set()
        return [e for e in out if not (e in seen or seen.add(e))]


def _family(kind: str) -> str:
    return "place" if kind in ("location", "customer", "supplier") else kind


def _words(text: str) -> set[str]:
    """The words of a name that can say it in part: no small words; plurals as their singular."""
    out = set()
    for t in re.split(r"[^\w.]+", text.lower()):
        t = t.strip(".")
        if not t or t in _STOP or (len(t) < 2 and not t.isdigit()):
            continue
        out.add(t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t)
    return out


def _intent(low: str, ents: list[Ent]) -> Intent:
    if re.search(r"\bwhat\s+(if|happens\s+if|would\s+happen)\b|\bsuppose\b|\bimagine\b|^\s*if\b|\bif\s+we\b", low):
        return "what_if"
    if re.search(r"\bwho\b|\bowners?\b|\bowns\b|\bresponsible\b|\bwhose\b|\bassigned\b", low):
        return "who_owns"
    named = any(e.kind in ("product", "order", "receipt", "demand", "resource") for e in ents)
    if re.search(r"\bwhy\b|\blate\b|\bdelay|\bbehind\b|\bshort(ages?|falls?)?\b|\bmiss(ing|es)?\b"
                 r"|\bstock-?\s?outs?\b|\boverload", low):
        if not named and not re.search(r"\bwhy\b", low) and re.search(r"\brisk\b|\bproblems?\b|\bmoney\b", low):
            return "at_risk"
        return "why_late"
    if re.search(r"\brisk\b|\bproblems?\b|\bworst\b|\bbiggest\b|\burgent\b|\bpriorit|\bwhat should\b|\bfirst\b"
                 r"|\bexceptions?\b|\bissues?\b", low):
        return "at_risk"
    return "unknown"


# ------------------------------------------------------------------------------------------------ the answerer
class _Ask:
    def __init__(self, ds: Dataset, plan: PlanResult, items: list[WorkItem], question: str) -> None:
        self.ds, self.plan, self.items, self.q = ds, plan, items, question
        self.cur = ds.settings.currency
        self.order = {o.id: o for o in plan.orders}
        self.receipt = {r.id: r for r in plan.receipts}
        self.ds_receipt = {r.id: r for r in ds.receipts}
        self._ix: TraceIndex | None = None
        self._by_id: dict | None = None

    @property
    def ix(self) -> TraceIndex:
        if self._ix is None:
            self._ix = trace_index(self.plan)
        return self._ix

    # -------------------------------------------------------------- names and citations
    def pname(self, pid: str) -> str:
        p = self.ds.product_by_id.get(pid)
        return f"{p.name} ({pid})" if p is not None and p.name and p.name != pid else pid

    def lname(self, lid: str) -> str:
        loc = self.ds.location_by_id.get(lid)
        return loc.name if loc is not None and loc.name else lid

    def c_product(self, pid: str, loc: str | None = None) -> Cite:
        return Cite(kind="product", id=pid, label=self.pname(pid),
                    href=f"#/plan/node/{loc}/{pid}" if loc else "#/data/products")

    def c_loc(self, lid: str) -> Cite:
        loc = self.ds.location_by_id.get(lid)
        kind = {"customer": "customer", "supplier": "supplier"}.get(loc.type.value, "location") if loc else "location"
        return Cite(kind=kind, id=lid, label=self.lname(lid), href="#/network")  # type: ignore[arg-type]

    def c_order(self, o: PlannedOrder) -> Cite:
        return Cite(kind="order", id=o.id, label=f"{o.kind} {o.qty:,.6g} {o.product} at {o.location}",
                    href=f"#/plan/orders/{o.id}")

    def c_receipt(self, rid: str) -> Cite:
        r = self.receipt.get(rid)
        label = f"{r.kind} {r.qty:,.6g} {r.product} at {r.location}" if r else rid
        return Cite(kind="receipt", id=rid, label=label, href="#/buying")

    def c_res(self, rid: str) -> Cite:
        r = self.ds.resource_by_id.get(rid)
        return Cite(kind="resource", id=rid, label=(r.name or rid) if r else rid, href=f"#/plan/capacity/{rid}")

    def c_item(self, w: WorkItem) -> Cite:
        return Cite(kind="exception", id=w.key, label=w.message, href="#/tower/inbox")

    def money(self, v: float) -> str:
        return f"{v:,.0f} {self.cur}"

    # -------------------------------------------------------------- demand
    def demand_of(self, rid: str) -> tuple[str, str]:
        """A requirement's demand record: (its id as cited, words for it)."""
        base = rid.split("~", 1)[0]
        key = base[2:] if base.startswith("D:") else base
        d = self._record(base)
        if d is None:
            return base, base
        if d.kind.value == "sales_order":
            name = d.order or d.id or key
            return base, f"sales order {name}" + (f" ({d.customer_ref})" if d.customer_ref else "")
        return base, f"forecast of {d.date.isoformat()}"

    def late_rows(self, products: set[str] | None, places: set[str] | None) -> list[LateDemand]:
        return [x for x in self.plan._late if (not products or x.product in products) and (not places or x.location in places)]

    def price(self, loc: str, prod: str) -> float:
        return self.ds.selling_price(loc, prod) or 0.0

    # -------------------------------------------------------------- why late: down the pegging
    def arrival(self, p: Peg) -> dt.date | None:
        if p.supply_kind == "order":
            o = self.order.get(p.supply_id)
            return o.projected_available_date if o else None
        if p.supply_kind == "co_product":
            o = self.order.get(p.supply_id)
            return (o.projected_available_date or o.available_date) if o else None
        if p.supply_kind == "receipt":
            r = self.receipt.get(p.supply_id)
            return r.date if r else self.ds.settings.planning_start
        return self.ds.settings.planning_start

    def explain_req(self, r: Requirement, depth: int) -> list[Step]:
        """What reaches requirement ``r`` late: its latest supply, and down from there."""
        pegs = self.ix.by_requirement.get(r.id, [])
        covered = sum(p.qty for p in pegs)
        far = dt.date.max
        late = [(self.arrival(p) or far, p) for p in pegs]
        late = [(d, p) for d, p in late if d > r.date]
        steps: list[Step] = []
        if r.qty - covered > 1e-6:
            steps.append(self.uncovered(r, r.qty - covered))
            if not late:
                return steps
        if not late:
            return [Step(text=f"Everything for it of {self.pname(r.product)} at {self.lname(r.location)} is there by "
                              f"{r.date.isoformat()}", cites=[self.c_product(r.product, r.location)])]
        when, p = max(late, key=lambda x: (x[0], x[1].qty))
        if p.supply_kind in ("order", "co_product"):
            o = self.order.get(p.supply_id)
            if o is not None:
                return steps + self.explain_order(o, r.date, depth)
        if p.supply_kind == "receipt":
            return steps + [self.explain_receipt(p.supply_id, r.date)]
        return steps

    def uncovered(self, r: Requirement, qty: float) -> Step:
        node = (r.location, r.product)
        sources = [s for s in self.ds.purchasing_sources if (s.location, s.product) == node and not self.ds.source_blocked(s)]
        makes = [s for s in self.ds.production_sources if (s.location, s.product) == node]
        lanes = [ln for ln in self.ds.lanes if ln.destination == r.location and r.product in (ln.products or [r.product])]
        if not (sources or makes or lanes):
            why = "nothing supplies it there: no supplier, production or route"
        else:
            why = "no order planned within the horizon covers it"
        return Step(text=f"{qty:,.6g} of {self.pname(r.product)} needed at {self.lname(r.location)} on "
                         f"{r.date.isoformat()} has no supply: {why}",
                    cites=[self.c_product(r.product, r.location), self.c_loc(r.location)])

    def explain_order(self, o: PlannedOrder, need: dt.date, depth: int) -> list[Step]:
        cites = [self.c_order(o), self.c_product(o.product, o.location)]
        avail = o.projected_available_date
        what = {"make": "made at", "buy": "bought for", "transfer": "brought to"}.get(o.kind, o.kind)
        head = (f"{o.id} ({o.qty:,.6g} {what} {self.lname(o.location)}"
                + (f" from {self.lname(o.origin)}" if o.origin and o.kind != "make" else "") + ") is available "
                f"{avail.isoformat() if avail else 'not within the horizon'}, needed {need.isoformat()}")
        if o.kind == "buy" and o.origin:
            cites.append(self.c_loc(o.origin))
        if o.kind == "transfer" and o.origin:
            cites.append(self.c_loc(o.origin))
        steps = [Step(text=head, cites=cites)]
        # what holds it up, most specific first
        if o.limited_by and depth < DEPTH:
            ins = [r for r in self.ix.by_parent.get(o.id, ()) if r.product == o.limited_by
                   and (o.limited_at is None or r.location == o.limited_at)]
            until = o.limited_until.isoformat() if o.limited_until else "not within the horizon"
            steps.append(Step(text=f"{o.id} waits for {self.pname(o.limited_by)} at {self.lname(o.limited_at or o.location)}: "
                                   f"all of it there {until}",
                              cites=[self.c_product(o.limited_by, o.limited_at or o.location)]))
            if ins:
                worst = max(ins, key=lambda r: r.date)
                return steps + self.explain_req(worst, depth + 1)
            return steps
        if o.start_in_past:
            lt = (o.available_date - o.start_date).days
            txt = (f"{o.id} should have started {o.wanted_start.isoformat() if o.wanted_start else 'before today'}: "
                   f"started today, with {lt} day{'s' if lt != 1 else ''} of lead time it is there "
                   f"{o.available_date.isoformat()} at the earliest")
            if o.kind == "buy":
                ps = next((s for s in self.ds.purchasing_sources if s.id == o.source_id), None)
                if ps is not None:
                    txt += f" (buying from {self.lname(ps.supplier)} takes {ps.lead_time_days:g} d)"
            steps.append(Step(text=txt, cites=[self.c_order(o)]))
            return steps
        if o.capacity_shift_days > 0:
            res = sorted(set(o.step_resources.values()))
            steps.append(Step(text=f"{o.id} is moved {o.capacity_shift_days} working days later to fit the capacity of "
                                   f"{', '.join(res) or 'its machine'}", cites=[self.c_res(r) for r in res]))
            return steps
        if o.fence_shifted:
            steps.append(Step(text=f"{o.id} falls inside the firm zone, where planning may not place new orders: it is "
                                   "placed at the zone's end", cites=[self.c_order(o)]))
            return steps
        return steps

    def explain_receipt(self, rid: str, need: dt.date) -> Step:
        rc = self.receipt.get(rid)
        src = self.ds_receipt.get(rid)
        cites = [self.c_receipt(rid)]
        if rc is None:
            return Step(text=f"Firm receipt {rid} comes late", cites=cites)
        txt = f"Firm receipt {rid} ({rc.qty:,.6g}) arrives {rc.date.isoformat()}, needed {need.isoformat()}"
        if src is not None and src.confirmed_date is not None and src.confirmed_date > src.due_date:
            txt += f": the supplier confirmed {src.confirmed_date.isoformat()} against {src.due_date.isoformat()} asked"
        ps = next((s for s in self.ds.purchasing_sources if src is not None and s.id == src.source), None)
        po = next((p for p in self.ds.purchase_orders if src is not None and p.id == src.po), None)
        supplier = po.supplier if po is not None else ps.supplier if ps is not None else None
        if supplier:
            cites.append(self.c_loc(supplier))
        return Step(text=txt, cites=cites)

    # -------------------------------------------------------------- reach: the records a chain names
    @staticmethod
    def reach(chains: list[list[Step]]) -> tuple[set[str], set[tuple[str, str]], set[str], set[str]]:
        ids: set[str] = set()
        nodes: set[tuple[str, str]] = set()
        res: set[str] = set()
        prods: set[str] = set()
        for ch in chains:
            for s in ch:
                for c in s.cites:
                    if c.kind in ("order", "receipt"):
                        ids.add(c.id)
                    elif c.kind == "resource":
                        res.add(c.id)
                    elif c.kind == "product":
                        prods.add(c.id)
                        if c.href.startswith("#/plan/node/"):
                            loc = c.href.split("/")[3]
                            nodes.add((loc, c.id))
        return ids, nodes, res, prods

    def proposals_for(self, items: list[WorkItem], limit: int = 4) -> list[Proposal]:
        """The inbox's actions for ``items``: the ones that can be tried in one click first, then by money."""
        out = []
        ranked = sorted(items, key=lambda w: (not (w.action and w.action.one_click), -w.money_at_risk, w.key))
        for w in ranked[:limit]:
            a = w.action
            if a is None:
                continue
            out.append(Proposal(kind="fix" if a.one_click else "open", label=a.label, key=w.key, message=w.message,
                                protects=a.protects, costs=a.costs, one_click=a.one_click, why_not=a.why_not,
                                href=a.href))
        return out

    def items_reached(self, ids: set[str], nodes: set[tuple[str, str]], res: set[str]) -> list[WorkItem]:
        return [w for w in self.items if (w.order_id and w.order_id in ids) or (w.resource and w.resource in res)
                or (w.product and w.location and (w.location, w.product) in nodes)]

    # -------------------------------------------------------------- the four questions
    def why_late(self, ents: list[Ent]) -> AskAnswer:
        prods = {e.id for e in ents if e.kind == "product"}
        places = {e.id for e in ents if e.kind in ("customer", "location")}
        orders = [e.id for e in ents if e.kind == "order"]
        receipts = [e.id for e in ents if e.kind == "receipt"]
        demands = {e.id for e in ents if e.kind == "demand"}
        resources = [e.id for e in ents if e.kind == "resource"]
        if orders and not (prods or demands):
            return self.why_order(orders[0])
        if receipts and not (prods or demands):
            return self.why_receipt(receipts[0])
        if resources and not (prods or demands):
            return self.why_resource(resources[0])
        rows = self.late_rows(prods or None, places or None)
        if demands:
            rows = [x for x in rows if self._demand_keys(x.requirement) & demands]
        subject = self.subject(prods, places, demands)
        asked = f"Why is {subject} late?" if subject else "Why is anything late?"
        if not rows:
            ans = (f"{subject} is not projected late" if subject else "Nothing is projected late") + \
                ": every demand's supply is there by its date."
            ans = ans[0].upper() + ans[1:]
            if not subject:
                return self.done("why_late", asked, ans)
            cites = [self.c_product(p) for p in sorted(prods)] + [self.c_loc(x) for x in sorted(places)]
            # the plan has it on time, but another check (promising, an open order) may not: say which
            heads = {d.split(":", 1)[1] for d in demands}
            open_on = [w for w in self.items if w.category in ("coverage", "delivery", "orders")
                       and ((w.order_id in heads) if heads else (not prods or w.product in prods)
                            and (not places or w.location in places or w.customer in places))]
            findings = [Finding(text=ans, cites=cites)]
            if open_on:
                ans += (f" But {len(open_on)} open problem{'s' if len(open_on) != 1 else ''} on it "
                        f"{'say' if len(open_on) != 1 else 'says'} otherwise: {open_on[0].message}.")
                findings += [Finding(text=f"{w.message} (owner {w.owner})", cites=[self.c_item(w)]) for w in open_on[:SHOWN]]
            return self.done("why_late", asked, ans, findings, self.proposals_for(open_on))
        # one finding per demand record (a forecast spread over its days is one demand)
        groups: dict[str, list[LateDemand]] = defaultdict(list)
        for x in rows:
            groups[x.requirement.split("~", 1)[0]].append(x)
        ranked = sorted(groups.values(), key=lambda g: (-sum(x.late * self.price(x.location, x.product) for x in g),
                                                        min(x.date for x in g), g[0].requirement))
        findings: list[Finding] = []
        chains: list[list[Step]] = []
        for g in ranked:
            first = min(g, key=lambda x: (x.date, x.requirement))
            r = self.ix.requirement.get(first.requirement)
            chain = self.explain_req(r, 0) if r is not None else []
            chains.append(chain)
            if len(findings) >= SHOWN:
                continue
            did, words = self.demand_of(first.requirement)
            late = sum(x.late for x in g)
            qty = sum(x.qty for x in g)
            ends = [x.all_by for x in g]
            by = "not within the horizon" if any(e is None for e in ends) else max(e for e in ends if e).isoformat()
            text = (f"{words.capitalize()} for {self.lname(first.location)}: {late:,.6g} of {qty:,.6g} "
                    f"{self.pname(first.product)} late from {first.date.isoformat()}, all there {by}")
            findings.append(Finding(text=text, chain=chain, cites=[
                Cite(kind="demand", id=did, label=words, href=f"#/plan/node/{first.location}/{first.product}"),
                self.c_product(first.product, first.location), self.c_loc(first.location)]))
        late_units = sum(x.late for x in rows)
        value = sum(x.late * self.price(x.location, x.product) for x in rows)
        top = chains[0][-1].text if chains and chains[0] else ""
        ans = (f"{late_units:,.6g} units{' of ' + subject if subject else ''} are projected late across {len(groups)} "
               f"demand{'s' if len(groups) != 1 else ''}" + (f" ({self.money(value)} of sales)" if value else "") + ".")
        if top:
            ans += f" At the root of the largest: {top}."
        ids, nodes, res, _ = self.reach(chains)
        nodes |= {(x.location, x.product) for x in rows}
        props = self.proposals_for(self.items_reached(ids, nodes, res))
        out = self.done("why_late", asked, ans, findings, props)
        out.more = max(0, len(groups) - len(findings))
        return out

    def _demand_keys(self, rid: str) -> set[str]:
        """A requirement's demand record as the question can name it: the line, and its order header."""
        base = rid.split("~", 1)[0]
        d = self._record(base)
        return {base, f"O:{d.order}"} if d is not None and d.order else {base}

    def _record(self, base: str):
        key = base[2:] if base.startswith("D:") else base
        if key.startswith("#") and key[1:].isdigit() and int(key[1:]) < len(self.ds.demand):
            return self.ds.demand[int(key[1:])]
        if self._by_id is None:
            self._by_id = {x.id: x for x in self.ds.demand if x.id}
        return self._by_id.get(key)

    def subject(self, prods: set[str], places: set[str], demands: set[str]) -> str:
        """What the question names, in words: "Electric kettle (KT-15) for E-commerce"; "" when it names nothing."""
        names = sorted(d.split(":", 1)[1] for d in demands) + [self.pname(p) for p in sorted(prods)]
        s = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        if places:
            s += (" for " if s else "demand for ") + ", ".join(self.lname(x) for x in sorted(places))
        return s

    def why_order(self, oid: str) -> AskAnswer:
        o = self.order[oid]
        chain = self.explain_order(o, o.need_date, 0)
        serves = [p for p in self.ix.by_supply.get(oid, [])]
        late = o.delay_days != 0
        if late:
            ans = (f"{oid} is {'not covered within the horizon' if o.delay_days < 0 else f'{o.delay_days:g} days late'} "
                   f"against {o.need_date.isoformat()}. {chain[-1].text}.")
        else:
            ans = f"{oid} is not late: it is available {o.available_date.isoformat()}, needed {o.need_date.isoformat()}."
        findings = [Finding(text=f"{oid}: why it is {'late' if late else 'on time'}", chain=chain, cites=[self.c_order(o)])]
        if serves:
            reqs = [self.ix.requirement[p.requirement_id] for p in serves if p.requirement_id in self.ix.requirement]
            findings.append(Finding(text=f"It covers {len(reqs)} requirement{'s' if len(reqs) != 1 else ''} of "
                                         f"{self.pname(o.product)} at {self.lname(o.location)}, the first on "
                                         f"{min(r.date for r in reqs).isoformat() if reqs else '-'}",
                                    cites=[self.c_product(o.product, o.location)]))
        ids, nodes, res, _ = self.reach([chain])
        props = self.proposals_for(self.items_reached(ids | {oid}, nodes, res)) if late else []
        return self.done("why_late", f"Why is {oid} late?", ans, findings, props)

    def why_receipt(self, rid: str) -> AskAnswer:
        pegs = self.ix.by_supply.get(rid, [])
        rc = self.receipt.get(rid)
        if rc is None:
            po = next((p for p in self.ds.purchase_orders if p.id == rid), None)
            lines = [r for r in self.ds.receipts if po is not None and r.po == po.id] if po else []
            if lines:
                return self.why_receipt(lines[0].id)
            return self.done("why_late", f"Why is {rid} late?", f"{rid} is not an open receipt in the plan.")
        need = min((self.ix.requirement[p.requirement_id].date for p in pegs if p.requirement_id in self.ix.requirement),
                   default=None)
        step = self.explain_receipt(rid, need or rc.date)
        if need is not None and rc.date > need:
            ans = f"{rid} arrives {rc.date.isoformat()}, {(rc.date - need).days} days after the first need it covers ({need.isoformat()})."
        elif need is None:
            ans = f"{rid} arrives {rc.date.isoformat()} and no requirement in the plan uses it."
        else:
            ans = f"{rid} is not late: it arrives {rc.date.isoformat()}, needed first {need.isoformat()}."
        props = self.proposals_for([w for w in self.items if w.order_id == rid])
        return self.done("why_late", f"Why is {rid} late?", ans, [Finding(text=step.text, cites=step.cites)], props)

    def why_resource(self, rid: str) -> AskAnswer:
        rp = next((x for x in self.plan.resources if x.resource == rid), None)
        if rp is None:
            return self.done("why_late", f"Why is {rid} overloaded?", f"{rid} has no load in the plan.")
        bk = {b.index: b for b in self.plan.buckets}
        over = [b for b in rp.buckets if b.load_hours > b.capacity_hours + b.overtime_hours + 1e-6]
        findings = []
        for b in over[:SHOWN]:
            lo, hi = bk[b.bucket].start, bk[b.bucket].end
            loads = sorted(((sum(h for d, h in ol.hours.items() if lo <= d < hi), ol) for ol in rp.orders),
                           key=lambda x: -x[0])
            loads = [(h, ol) for h, ol in loads if h > 1e-6][:3]
            cites = [self.c_res(rid)] + [self.c_order(self.order[ol.order]) if ol.order in self.order
                                         else Cite(kind="order", id=ol.order, label=ol.product, href="#/execution")
                                         for _, ol in loads]
            findings.append(Finding(text=(f"{bk[b.bucket].label}: {b.load_hours:,.1f} h of work on "
                                          f"{b.capacity_hours:,.1f} h + {b.overtime_hours:,.1f} h overtime; most from "
                                          + ", ".join(f"{ol.order} ({h:,.1f} h)" for h, ol in loads)),
                                    cites=cites))
        # a day over its hours inside a period with room overall: the work cannot be done that day as planned (N116)
        full = {b.bucket for b in over}
        r = self.ds.resource_by_id[rid]
        cal = resource_calendar(self.ds, rid)
        days = []
        for d, h in sorted(rp.daily_load.items()):
            b = next((x for x in self.plan.buckets if x.start <= d < x.end), None)
            if b is None or b.index in full:
                continue
            room = hours_between(r, cal, d, d + dt.timedelta(days=1)) + overtime_between(r, cal, d, d + dt.timedelta(days=1))
            if h > room + 1e-6:
                days.append((d, h, room))
        for d, h, room in sorted(days, key=lambda x: x[2] - x[1])[:max(0, SHOWN - len(findings))]:
            loads = sorted(((ol.hours.get(d, 0.0), ol) for ol in rp.orders), key=lambda x: -x[0])
            loads = [(x, ol) for x, ol in loads if x > 1e-6][:3]
            findings.append(Finding(
                text=(f"{d.isoformat()}: {h:,.1f} h of work on {room:,.1f} h with overtime; most from "
                      + ", ".join(f"{ol.order} ({x:,.1f} h)" for x, ol in loads)),
                cites=[self.c_res(rid)] + [self.c_order(self.order[ol.order]) if ol.order in self.order
                                           else Cite(kind="order", id=ol.order, label=ol.product, href="#/execution")
                                           for _, ol in loads]))
        if not over and not days:
            peak = max((b.utilization for b in rp.buckets), default=0.0)
            ans = f"{rid} is not over its capacity on any day: at most {peak:.0%} loaded in a period."
        else:
            parts = []
            if over:
                parts.append(f"in {len(over)} period{'s' if len(over) != 1 else ''}")
            if days:
                parts.append(f"on {len(days)} more day{'s' if len(days) != 1 else ''} in periods with room")
            ans = f"{rid} is over its capacity and overtime {' and '.join(parts)}."
        props = self.proposals_for([w for w in self.items if w.resource == rid])
        return self.done("why_late", f"Why is {rid} overloaded?", ans, findings, props)

    def who_owns(self, ents: list[Ent]) -> AskAnswer:
        prods = {e.id for e in ents if e.kind == "product"}
        places = {e.id for e in ents if e.kind in ("customer", "location", "supplier")}
        res = {e.id for e in ents if e.kind == "resource"}
        ids = {e.id for e in ents if e.kind in ("order", "receipt")}
        named = bool(prods or places or res or ids)
        hit = [w for w in self.items if not named or (w.product in prods if prods else True)
               and (w.location in places or w.customer in places if places else True)
               and (w.resource in res if res else True) and (w.order_id in ids if ids else True)]
        subject = (self.subject(prods, places, set()) if (prods or places) else ", ".join(sorted(res | ids))) \
            if named else ""
        by: dict[str, list[WorkItem]] = defaultdict(list)
        for w in hit:
            by[w.owner].append(w)
        findings = []
        for owner, ws in sorted(by.items(), key=lambda kv: (-sum(w.money_at_risk for w in kv[1]), kv[0])):
            how = {"manual": "assigned by hand", "rule": "by an owner rule", "default": "the default owner"}
            srcs = sorted({how[w.owner_source] for w in ws})
            total = sum(w.money_at_risk for w in ws)
            findings.append(Finding(text=(f"{owner} owns {len(ws)} open problem{'s' if len(ws) != 1 else ''}"
                                          f" ({self.money(total)} at risk; {', '.join(srcs)})"
                                          + (f": {ws[0].message}" if len(ws) == 1 else "")),
                                    cites=[self.c_item(w) for w in ws[:5]]))
        rules = []
        family = {p.id: p.family for p in self.ds.products}
        for i, rule in enumerate(self.ds.tower.owners):
            touches = (bool(prods & set(rule.products)) or bool(places & set(rule.locations))
                       or bool({family.get(p) for p in prods} & set(rule.families)))
            if touches or not named:
                scope = "; ".join(x for x in (
                    f"categories {', '.join(rule.categories)}" if rule.categories else "",
                    f"places {', '.join(rule.locations)}" if rule.locations else "",
                    f"products {', '.join(rule.products)}" if rule.products else "",
                    f"families {', '.join(rule.families)}" if rule.families else "") if x) or "everything"
                rules.append(Finding(text=f"Rule {i + 1}: new problems on {scope} go to {rule.owner}",
                                     cites=[Cite(kind="rule", id=str(i + 1), label=rule.owner,
                                                 href="#/tower/settings")]))
        rules.append(Finding(text=f"Anything no rule matches goes to {self.ds.tower.default_owner}",
                             cites=[Cite(kind="rule", id="default", label=self.ds.tower.default_owner,
                                         href="#/tower/settings")]))
        on = f" on {subject}" if subject else ""
        if hit:
            names = sorted(by, key=lambda o: -sum(w.money_at_risk for w in by[o]))
            ans = (f"{names[0]} owns the most of the {len(hit)} open problem{'s' if len(hit) != 1 else ''}{on}"
                   + (f"; also {', '.join(names[1:4])}" if len(names) > 1 else "") + ".")
        else:
            ans = f"No problem{on} is open. New ones would go to the owners below."
        return self.done("who_owns", f"Who owns the problems{on}?", ans, findings + rules)

    def at_risk(self) -> AskAnswer:
        top = self.items[:SHOWN]
        total = sum(w.money_at_risk for w in self.items)
        findings = [Finding(text=(f"{self.money(w.money_at_risk)}: {w.message} (owner {w.owner}"
                                  + (f"; do: {w.action.label}" if w.action else "") + ")"),
                            cites=[self.c_item(w)] + ([self.c_product(w.product, w.location)] if w.product and w.location
                                                      else []) + ([self.c_res(w.resource)] if w.resource else []))
                    for w in top]
        if not self.items:
            ans = "No problem is open."
        else:
            ans = (f"{self.money(total)} is at risk across {len(self.items)} open problem{'s' if len(self.items) != 1 else ''}; "
                   f"the top {len(top)} hold {self.money(sum(w.money_at_risk for w in top))}.")
        out = self.done("at_risk", "What is at risk?", ans, findings, self.proposals_for(self.items))
        out.more = max(0, len(self.items) - len(top))
        return out

    # -------------------------------------------------------------- what if
    def chips(self, low: str, ents: list[Ent]) -> list[Chip]:
        pct_m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:%|per\s?cent\b|percent\b)", low)
        pct = float(pct_m.group(1)) if pct_m else None
        if pct is not None and pct > 0 and re.search(
                r"\b(down|drops?|falls?|fewer|less|lower|decreases?|shrinks?|cut|cheaper|weaker)\b", low):
            pct = -pct
        if pct is None and re.search(r"\bdoubles?\b", low):
            pct = 100.0
        if pct is None and re.search(r"\bhalves?\b|\bhalved\b", low):
            pct = -50.0
        days_m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(days?|d\b|weeks?|wks?|months?)", low)
        days = None
        if days_m:
            days = float(days_m.group(1)) * (7 if days_m.group(2).startswith("w") else
                                             30 if days_m.group(2).startswith("mo") else 1)
            if days > 0 and re.search(r"\b(shorter|quicker|faster|less|fewer|cut|earlier)\b", low):
                days = -days
        prods = [e.id for e in ents if e.kind == "product"]
        sups = [e.id for e in ents if e.kind == "supplier"]
        custs = [e.id for e in ents if e.kind == "customer"]
        places = [e.id for e in ents if e.kind == "location"]
        res = [e.id for e in ents if e.kind == "resource"]
        curs = [e.id for e in ents if e.kind == "currency"]
        out: list[Chip] = []
        if re.search(r"\bdemand\b|\bsales\b|\borders?\b|\bforecast\b|\bsell\b|\bvolume\b", low) and pct is not None \
                and not re.search(r"\bprices?\b|\bpricing\b", low) and not curs:
            out.append(DemandChip(pct=pct, products=prods))
        for s in sups:
            if days is not None and re.search(r"\blate\b|\blead\s?times?\b|\bslips?\b|\bdelay", low):
                out.append(LeadTimeChip(days=days, supplier=s))
            elif re.search(r"\bout\b|\bstops?\b|\bfails?\b|\bdown\b|\bbankrupt|\bcan'?t\b|\bcannot\b|\bno longer\b"
                           r"|\blost\b|\bloses?\b|\bstrike\b|\bclos(es|ed)\b|\bshuts?\b|\bgone\b|\bdrops? out\b"
                           r"|\bbust\b|\bgoes under\b|\bcollapses?\b|\bunavailable\b|\bstops? supplying\b", low):
                out.append(SupplierOutChip(supplier=s))
        if not sups and days is not None and re.search(r"\blead\s?times?\b|\bsuppliers?\b.*\blate\b", low):
            out.append(LeadTimeChip(days=days))
        for r in res:
            if re.search(r"\bshifts?\b", low):
                out.append(AddShiftChip(resource=r))
            elif re.search(r"\bdown\b|\bbreaks?\b|\bbroken\b|\bfails?\b|\bout\b|\bstops?\b|\bmaintenance\b"
                           r"|\brepair|\bidle\b|\boff\b", low):
                start = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low)
                n = int(round(days)) if days and days > 0 else 7
                out.append(MachineDownChip(resource=r, days=min(366, n),
                                           start=dt.date.fromisoformat(start.group(1)) if start else None))
        if days is not None and days >= 0 and re.search(
                r"\broutes?\b|\blanes?\b|\btransit\b|\bshipping\b|\bports?\b|\bfreight\b|\btrucks?\b|\btransport\b", low):
            out.append(LaneDelayChip(days=days, location=(places + custs + sups)[0] if (places + custs + sups) else None))
        if pct is not None and re.search(r"\bprices?\b|\bpricing\b", low):
            for c in custs:
                out.append(CustomerPriceChip(customer=c, pct=pct))
        if days is not None and days >= 0 and re.search(r"\bsafety\b", low):
            out.append(SafetyDaysChip(days=days, products=prods))
        if pct is not None:
            for c in curs:
                out.append(FxChip(currency=c, pct=pct))
        return out

    def what_if(self, low: str, ents: list[Ent]) -> AskAnswer:
        try:
            chips = self.chips(low, ents)
        except ValidationError as e:
            msg = e.errors()[0].get("msg", "out of range")
            return self.done("what_if", "What if …?", f"That change is out of range: {msg}.",
                             suggestions=self.suggest())
        if not chips:
            return self.done("what_if", "What if …?",
                             "I could not tell which change to try. Name one: demand up or down by a per cent, a "
                             "supplier out or late by some days, a machine down for some days or with another shift, "
                             "routes slower by some days, a customer's prices by a per cent, safety stock in days, or a "
                             "currency by a per cent.", suggestions=self.suggest())
        label = " · ".join(chip_label(c) for c in chips)
        notes: list[str] = []
        try:
            ds2 = apply_chips(self.ds, chips, notes)
        except WhatIfError as e:
            return self.done("what_if", f"What if: {label}?", f"That change cannot be tried: {e}.")
        from ..plan import run_mrp
        plan2 = run_mrp(ds2)
        base = _metrics("Plan now", self.ds, self.plan)
        sc = _metrics(label[:60], ds2, plan2)
        if notes:
            sc.note = "; ".join([*notes, *([sc.note] if sc.note else [])])
        if not (base.ok and sc.ok):
            return self.done("what_if", f"What if: {label}?", sc.note or "The plan with this change is blocked.",
                             scenario=sc)
        sc.cost_delta = round(sc.total_cost - base.total_cost, 2)
        sc.service_delta = round(sc.service - base.service, 6)
        sc.inventory_delta = round(sc.inventory_value_avg - base.inventory_value_avg, 2)
        sc.late_units_delta = round(sc.late_units - base.late_units, 6)
        sc.sales_delta = round(sc.sales_value - base.sales_value, 2)
        # where the late demand moves
        def late_by(p: PlanResult) -> dict[tuple[str, str], float]:
            out: dict[tuple[str, str], float] = defaultdict(float)
            for x in p._late:
                out[(x.location, x.product)] += x.late
            return out
        a, b = late_by(self.plan), late_by(plan2)
        moved = sorted(((k, b.get(k, 0.0) - a.get(k, 0.0)) for k in set(a) | set(b)), key=lambda kv: -abs(kv[1]))
        moved = [(k, d) for k, d in moved if abs(d) > 1e-6]
        findings = [
            Finding(text=f"Service: {base.service:.1%} → {sc.service:.1%} of demand on time "
                         f"({sc.service_delta * 100:+.1f} points)"),
            Finding(text=f"Cost: {self.money(base.total_cost)} → {self.money(sc.total_cost)} "
                         f"({sc.cost_delta:+,.0f} {self.cur})"),
            Finding(text=f"Late units: {base.late_units:,.6g} → {sc.late_units:,.6g}; average stock "
                         f"{self.money(base.inventory_value_avg)} → {self.money(sc.inventory_value_avg)}"),
            Finding(text=f"Busiest machine: {base.capacity_peak:.0%} → {sc.capacity_peak:.0%} loaded"),
        ]
        for (loc, prod), d in moved[:SHOWN]:
            findings.append(Finding(text=f"{self.pname(prod)} for {self.lname(loc)}: {abs(d):,.6g} units "
                                         f"{'more' if d > 0 else 'fewer'} late",
                                    cites=[self.c_product(prod, loc), self.c_loc(loc)]))
        verdict = ("better on service" if sc.service_delta > 1e-6 else "worse on service" if sc.service_delta < -1e-6
                   else "the same service")
        ans = (f"With {label}: {verdict} ({base.service:.1%} → {sc.service:.1%} on time), cost "
               f"{sc.cost_delta:+,.0f} {self.cur}, {sc.late_units_delta:+,.6g} late units.")
        loose = sorted({c.resource for c in chips if isinstance(c, (MachineDownChip, AddShiftChip))
                        and not (self.ds.settings.capacity_constrained
                                 and getattr(self.ds.resource_by_id.get(c.resource), "finite", False))})
        if loose:
            sc.note = "; ".join([*([sc.note] if sc.note else []), (
                f"the plan does not wait for {', '.join(loose)}: capacity-constrained planning is "
                + ("off" if not self.ds.settings.capacity_constrained else "off for it")
                + ", so the change shows in its load (Capacity), not in late demand")])
        if sc.note:
            ans += f" {sc.note[0].upper() + sc.note[1:]}."
        prop = Proposal(kind="scenario", label=f"Keep “{label[:60]}” as a scenario", chips=chips, href="#/whatif",
                        name=label[:60])
        out = self.done("what_if", f"What if: {label}?", ans, findings, [prop], scenario=sc)
        out.more = max(0, len(moved) - SHOWN)
        return out

    # -------------------------------------------------------------- what the data can answer
    def suggest(self) -> list[str]:
        out = []
        if self.plan._late:
            x = max(self.plan._late, key=lambda x: x.late * self.price(x.location, x.product))
            out.append(f"Why is {self.pname(x.product).split(' (')[0]} late for {self.lname(x.location)}?")
        out.append("What is at risk?")
        sup = next((loc for loc in self.ds.locations if loc.type.value == "supplier"), None)
        out.append("What if demand rises 20 %?")
        if sup is not None:
            out.append(f"What if {sup.name or sup.id} is out?")
        res = next(iter(self.ds.resources), None)
        if res is not None:
            out.append(f"What if {res.id} is down for a week?")
        if self.items:
            w = self.items[0]
            if w.product:
                out.append(f"Who owns {self.pname(w.product).split(' (')[0]}?")
        else:
            out.append("Who owns the open problems?")
        return out

    def done(self, intent: Intent, understood: str, answer: str, findings: list[Finding] | None = None,
             proposals: list[Proposal] | None = None, suggestions: list[str] | None = None,
             scenario: ScenarioOut | None = None) -> AskAnswer:
        return AskAnswer(question=self.q, intent=intent, understood=understood, answer=answer, findings=findings or [],
                         proposals=proposals or [], suggestions=suggestions or [], scenario=scenario, currency=self.cur)


def vocabulary(ds: Dataset, plan: PlanResult) -> _Vocab:
    """The names and ids a question is read against (kept beside the plan between questions)."""
    return _Vocab(ds, plan)


def ask(ds: Dataset, plan: PlanResult, items: list[WorkItem], question: str, ix: TraceIndex | None = None,
        vocab: _Vocab | None = None) -> AskAnswer:
    """Answer ``question`` from ``plan`` (of ``ds``) and the open worklist ``items`` (as the inbox ranks them).
    ``ix``: the plan's pegging index when one is kept (plan/trace.py), else it is built when a question needs it;
    ``vocab``: the names read, likewise."""
    a = _Ask(ds, plan, items, question.strip())
    a._ix = ix
    if not plan.ok:
        return a.done("unknown", question, "The plan is blocked by readiness errors, so there is nothing to ask it yet: "
                      + "; ".join(i.message for i in plan.issues[:3]))
    ents = (vocab or _Vocab(ds, plan)).find(question)
    low = " ".join(question.lower().split())
    intent = _intent(low, ents)
    if intent == "what_if":
        return a.what_if(low, ents)
    if intent == "who_owns":
        return a.who_owns(ents)
    if intent == "why_late":
        return a.why_late(ents)
    if intent == "at_risk":
        return a.at_risk()
    named = ", ".join(f"{e.kind} {e.id}" for e in ents[:4])
    return a.done("unknown", question, "I can answer why something is late, what happens if something changes, who owns "
                  "a problem, and what is at risk." + (f" I found {named} in the question." if named else ""),
                  suggestions=a.suggest())
