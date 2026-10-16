"""Ask the plan (enterprise plan 5.2): questions answered from the plan's own records, each answer citing them, with
fixes a person tries and keeps (scp/tower/ask.py)."""
from __future__ import annotations

from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from scp.api.app import app
from scp.plan import run_mrp
from scp.tower import open_items, try_inbox_fix
from scp.tower.ask import ask
from scp.tower.fix import apply_edits
from scp.whatif import DemandChip, ScenarioIn, SupplierOutChip, WhatIfRequest, compare_scenarios

from .factory import base, demand, ds as make, load_example


def _ask(d, q):
    plan = run_mrp(d)
    return ask(d, plan, open_items(d, plan, scope="anon:-"), q), plan


def _cites_resolve(d, plan, items, a):
    """Every record an answer cites is one the company or its plan has."""
    known = {
        "product": {p.id for p in d.products},
        "order": {o.id for o in plan.orders},
        "receipt": {r.id for r in d.receipts} | {p.id for p in d.purchase_orders},
        "resource": {r.id for r in d.resources},
        "exception": {w.key for w in items},
    }
    places = {loc.id for loc in d.locations}
    demands = {r.id.split("~", 1)[0] for r in plan.requirements if r.kind in ("forecast", "sales_order")}
    cites = [c for f in a.findings for c in [*f.cites, *(c for s in f.chain for c in s.cites)]]
    for c in cites:
        if c.kind in known:
            assert c.id in known[c.kind], c
        elif c.kind in ("location", "customer", "supplier"):
            assert c.id in places, c
        elif c.kind == "demand":
            assert c.id in demands, c
    return cites


# ------------------------------------------------------------------------------------------------ a known root cause
@pytest.fixture
def slow_part():
    """A made from 2 B + 1 C; C takes 20 days to buy, so an order of A due on day 4 cannot be made in time."""
    d = base()
    d["purchasing_sources"][1]["lead_time_days"] = 20
    d["demand"] = [demand("P", "A", "2026-01-09", 30, "sales_order", id="SO-1")]
    return d


def test_why_late_follows_the_pegging_down_to_the_part_that_takes_too_long(slow_part):
    d = make(slow_part)
    a, plan = _ask(d, "Why is SO-1 late?")
    assert a.intent == "why_late" and "SO-1" in a.understood
    late = sum(e.qty for e in plan.exceptions if e.code == "DEMAND_AT_RISK")
    assert a.answer.startswith(f"{late:,.6g} units of SO-1")
    (f,) = a.findings
    chain = f.chain
    # demand → the order of A → it waits for C → C's purchase should have started 20 days before it is needed
    mo = next(o for o in plan.orders if o.product == "A")
    pr = next(o for o in plan.orders if o.product == "C")
    assert chain[0].cites[0].id == mo.id and mo.projected_available_date > mo.need_date
    assert "waits for C" in chain[1].text
    assert chain[-1].cites[0].id == pr.id and pr.start_in_past
    assert "should have started" in chain[-1].text and "20 d" in chain[-1].text
    assert pr.id in a.answer
    _cites_resolve(d, plan, open_items(d, plan, scope="anon:-"), a)


def test_a_late_firm_receipt_is_the_root_and_its_fix_is_kept_by_a_person(slow_part):
    slow_part["receipts"] = [{"id": "PO-7", "kind": "purchase", "location": "P", "product": "C", "qty": 20,
                              "due_date": "2026-01-20", "source": "PIR-C"}]
    d = make(slow_part)
    a, plan = _ask(d, "why is SO-1 late")
    assert "Firm receipt PO-7" in a.findings[0].chain[-1].text and "arrives 2026-01-20" in a.findings[0].chain[-1].text
    fix = next(p for p in a.proposals if p.kind == "fix")
    assert fix.one_click and fix.key
    # asking changed nothing; the person tries the fix on a copy and keeps it
    assert next(r for r in d.receipts if r.id == "PO-7").due_date.isoformat() == "2026-01-20"
    tried = try_inbox_fix(d, fix.key)
    kept = apply_edits(d, tried.edits)
    b, plan2 = _ask(kept, "why is SO-1 late")
    # the receipt is no longer the root; what is left late waits for the next one (B: 30 on hand, 40 needed)
    late = [sum(x.late for x in p._late) for p in (plan, plan2)]
    assert 0 < late[1] < late[0]
    root = b.findings[0].chain[-1]
    assert "PO-7" not in root.text and root.cites[0].id == next(o.id for o in plan2.orders if o.product == "B")


def test_an_order_and_a_receipt_can_be_asked_about_by_their_number(slow_part):
    d = make(slow_part)
    plan = run_mrp(d)
    mo = next(o for o in plan.orders if o.product == "A")
    a, _ = _ask(d, f"why is {mo.id} late?")
    assert a.understood == f"Why is {mo.id} late?" and f"{mo.delay_days:g} days late" in a.answer
    assert a.findings[0].chain[-1].cites[0].id == next(o.id for o in plan.orders if o.product == "C")


def test_nothing_late_says_so(slow_part):
    slow_part["purchasing_sources"][1]["lead_time_days"] = 1
    slow_part["demand"][0]["date"] = "2026-01-20"
    a, _ = _ask(make(slow_part), "Why is A late?")
    assert a.answer.startswith("A is not projected late") and not a.proposals


# ------------------------------------------------------------------------------------------------ on the examples
@pytest.mark.parametrize("name", ["kitchenware_network", "chennai_port_pumps"])
def test_why_late_adds_up_to_the_plans_demand_at_risk(name):
    d = load_example(name)
    plan = run_mrp(d)
    items = open_items(d, plan, scope="anon:-")
    risk = defaultdict(float)
    for e in plan.exceptions:
        if e.code == "DEMAND_AT_RISK":
            risk[(e.location, e.product)] += e.qty
    late = defaultdict(float)
    for x in plan._late:
        late[(x.location, x.product)] += x.late
    assert late.keys() == risk.keys() and all(late[k] == pytest.approx(risk[k]) for k in risk)
    a = ask(d, plan, items, "why is anything late?")
    assert a.answer.startswith(f"{sum(risk.values()):,.6g} units are projected late")
    assert len(a.findings) + a.more == len({x.requirement.split("~")[0] for x in plan._late})
    _cites_resolve(d, plan, items, a)
    # every order a chain cites as holding a demand up is late against the date it is needed
    for f in a.findings:
        for s in f.chain:
            for c in s.cites:
                if c.kind == "order" and "is available" in s.text and s.cites[0] is c:
                    o = next(x for x in plan.orders if x.id == c.id)
                    assert o.projected_available_date is None or o.projected_available_date > o.need_date or \
                        o.available_date > o.need_date
    # proposals are the inbox's own actions for the items the chains reach
    keys = {w.key for w in items}
    assert a.proposals and all(p.key in keys for p in a.proposals)


def test_a_name_said_in_part_finds_the_product_and_the_customer():
    d = load_example("chennai_port_pumps")
    a, _ = _ask(d, "Why is the 10 HP export pump late for Jebel Ali?")
    assert a.understood == "Why is Export end-suction pump 10 HP (PUMP-10HP-EXP) for Gulf distributor, Jebel Ali late?"
    assert {c.id for f in a.findings for c in f.cites} >= {"PUMP-10HP-EXP", "CUS-JEBEL-ALI"}
    assert all(c.id in ("PUMP-10HP-EXP", "CUS-JEBEL-ALI") for f in a.findings for c in f.cites if c.kind != "demand")


def test_an_overloaded_machine_names_the_orders_that_load_it():
    d = load_example("chennai_port_pumps")
    a, plan = _ask(d, "why is the asm line overloaded")
    rp = next(r for r in plan.resources if r.resource == "ASM-LINE")
    over = [b for b in rp.buckets if b.load_hours > b.capacity_hours + b.overtime_hours + 1e-6]
    assert a.answer.startswith(f"ASM-LINE is over its capacity and overtime in {len(over)} periods and on ")
    assert all(any(c.kind == "order" for c in f.cites) for f in a.findings)
    assert any(p.kind == "fix" and "overtime" in p.label for p in a.proposals)


def test_a_machine_over_its_hours_on_single_days_is_named_and_its_overtime_fix_clears_it():
    d = load_example("kitchenware_network")
    a, plan = _ask(d, "why is PUNE-WIND overloaded?")
    (e,) = [x for x in plan.exceptions if x.code == "CAPACITY_DAY_OVERLOAD" and x.resource == "PUNE-WIND"]
    n = int(e.message.split(": ", 1)[1].split(" day")[0])
    assert a.answer == f"PUNE-WIND is over its capacity and overtime on {n} more days in periods with room."
    worst = a.findings[0].text.split(":")[0]
    assert worst == e.message.rsplit(" on ", 1)[1]                       # the worst day first, as the exception says
    fix = next(p for p in a.proposals if p.kind == "fix")
    kept = apply_edits(d, try_inbox_fix(d, fix.key).edits)
    b, _ = _ask(kept, "why is PUNE-WIND overloaded?")
    assert b.answer.startswith("PUNE-WIND is not over its capacity on any day")


def test_what_if_is_the_what_if_page_planned_once():
    d = load_example("kitchenware_network")
    a, _ = _ask(d, "What if demand rises 20%?")
    assert a.intent == "what_if" and a.understood == "What if: Demand +20 %?"
    side = compare_scenarios(WhatIfRequest(base=d, scenarios=[ScenarioIn(label="now"),
                                                             ScenarioIn(label="up", chips=[DemandChip(pct=20)])]))
    want = side.scenarios[1]
    assert a.scenario.service == pytest.approx(want.service) and a.scenario.total_cost == pytest.approx(want.total_cost)
    assert a.scenario.service_delta == pytest.approx(want.service_delta)
    (p,) = a.proposals
    assert p.kind == "scenario" and p.chips == [DemandChip(pct=20)]


@pytest.mark.parametrize("q, chip", [
    ("what if demand falls 10 %", {"kind": "demand", "pct": -10.0, "products": []}),
    ("what if demand for KT-15 doubles", {"kind": "demand", "pct": 100.0, "products": ["KT-15"]}),
    ("what if Hindalco copper is out?", {"kind": "supplier_out", "supplier": "SUP-COPPER"}),
    ("what if lead times are 2 weeks longer", {"kind": "lead_time", "days": 14.0, "supplier": None}),
    ("suppose PUNE-WIND breaks down for 3 days", {"kind": "machine_down", "resource": "PUNE-WIND", "days": 3,
                                                  "start": None}),
    ("what if we add a shift on PUNE-WIND", {"kind": "add_shift", "resource": "PUNE-WIND"}),
    ("what if USD is 5% dearer", {"kind": "fx", "currency": "USD", "pct": 5.0}),
    ("what if safety stock is 10 days", {"kind": "safety_days", "days": 10.0, "products": []}),
])
def test_what_if_reads_each_kind_of_change(q, chip):
    d = load_example("kitchenware_network")
    if chip["kind"] == "fx" and "USD" not in d.settings.fx_rates:
        pytest.skip("no USD rate in the example")
    a, _ = _ask(d, q)
    assert a.intent == "what_if" and a.proposals, a.answer
    assert [c.model_dump(mode="json") for c in a.proposals[0].chips] == [chip]


def test_what_if_says_when_the_plan_does_not_wait_for_the_machine():
    a, _ = _ask(load_example("chennai_port_pumps"), "what if the assembly line is down for 2 weeks")
    assert a.understood == "What if: ASM-LINE down 14 d?"
    assert "capacity-constrained planning is off" in a.answer


def test_a_change_it_cannot_read_is_answered_with_what_it_can():
    a, _ = _ask(load_example("chennai_port_pumps"), "what if steel prices rise 10%")
    assert a.intent == "what_if" and not a.proposals and a.suggestions


def test_who_owns_follows_the_owner_rules():
    d = load_example("kitchenware_network")
    plan = run_mrp(d)
    items = open_items(d, plan, scope="anon:-")
    a = ask(d, plan, items, "Who owns KT-15?")
    on = [w for w in items if w.product == "KT-15"]
    owners = {w.owner for w in on}
    named = {f.text.split(" owns ")[0] for f in a.findings if " owns " in f.text}
    assert named == owners and a.answer.startswith(max(owners, key=lambda o: sum(w.money_at_risk for w in on
                                                                                  if w.owner == o)))
    assert sum(len(f.cites) for f in a.findings if " owns " in f.text) <= len(on)
    assert a.findings[-1].text == f"Anything no rule matches goes to {d.tower.default_owner}"


def test_at_risk_is_the_inbox_top():
    d = load_example("kitchenware_network")
    plan = run_mrp(d)
    items = open_items(d, plan, scope="anon:-")
    a = ask(d, plan, items, "What is at risk?")
    assert [f.cites[0].id for f in a.findings] == [w.key for w in items[:len(a.findings)]]
    assert f"{sum(w.money_at_risk for w in items):,.0f}" in a.answer
    assert a.more == len(items) - len(a.findings)


def test_every_suggested_question_is_understood():
    for name in ("kitchenware_network", "chennai_port_pumps"):
        d = load_example(name)
        a, _ = _ask(d, "hello there")
        assert a.intent == "unknown" and len(a.suggestions) >= 4
        for q in a.suggestions:
            b, _ = _ask(d, q)
            assert b.intent != "unknown" and "could not tell" not in b.answer, (q, b.answer)


def test_asking_over_the_api_changes_nothing():
    d = load_example("kitchenware_network")
    c = TestClient(app)
    r = c.post("/api/ask", json={"dataset": d.model_dump(mode="json"), "question": "What if Hindalco copper is out?"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["intent"] == "what_if" and out["proposals"][0]["chips"] == [SupplierOutChip(supplier="SUP-COPPER")
                                                                          .model_dump(mode="json")]
    assert c.post("/api/ask", json={"dataset": d.model_dump(mode="json"), "question": ""}).status_code == 422


@pytest.mark.parametrize("q, intent, understood", [
    ("which orders are late", "why_late", "Why is anything late?"),
    ("show me shortages", "why_late", "Why is anything late?"),
    ("what happens if Hindalco goes bust", "what_if", "What if: SUP-COPPER out?"),
    ("what if demand for mixer grinders rises 15%", "what_if", "What if: Demand +15 % (MG-500, MG-750)?"),
    # the products, not the assembly line named after them
    ("who is responsible for the mixer grinders", "who_owns",
     "Who owns the problems on Mixer grinder 500 W (MG-500), Mixer grinder 750 W (MG-750)?"),
])
def test_everyday_phrasings_are_read(q, intent, understood):
    a, _ = _ask(load_example("kitchenware_network"), q)
    assert (a.intent, a.understood) == (intent, understood), a.answer


def test_on_time_in_the_plan_but_an_open_problem_on_it_says_so():
    d = load_example("kitchenware_network")
    a, plan = _ask(d, "why is SO-88221 late")
    assert not [x for x in plan._late if x.requirement.startswith("D:SO-88221")]
    assert a.answer.startswith("SO-88221 is not projected late") and "But 1 open problem on it" in a.answer
    assert a.findings[1].cites[0].id.startswith("PROMISE_LATE|") and a.proposals[0].key == a.findings[1].cites[0].id
