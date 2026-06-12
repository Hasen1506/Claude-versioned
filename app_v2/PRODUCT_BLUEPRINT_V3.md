x# PRODUCT BLUEPRINT V3 — Design System · Input Architecture · Enterprise Readiness

**Date:** 2026-06-10 · **Inputs fused:** `Exploring.docx` (26 questions) + `supply_chain_12_steps (1).html`
(truncated at Step 10 — Steps 11/12 missing from the upload) + `OBSERVABILITY_MAP_AND_RESEARCH_SPEC.md`
+ `GOLDEN_JOURNEY_SPEC.md` gap backlog + fresh code survey (2026-06-10).

**What this document is:** the single blueprint that answers (1) every question in Exploring.docx,
(2) what "enterprise grade" means for this product and where we differentiate, (3) a bold but
clutter-free design-system overhaul, (4) the per-module input-architecture audit with the concrete
mistakes found, (5) per-solver input contracts (too many? wrong? missing?), (6) the data-science
position, (7) the console-vs-per-page results decision, (8) the verification-stack verdict, and
(9) a phased execution program with assert criteria — so it does not get redone.

**The anti-rot contract (Appendix C discipline, restated):** every claim in here that names a file
carries a `file:line`-class anchor that was verified by grep/read on 2026-06-10. When a phase ships,
its section gets a ✅ + date, never deleted. New gaps get appended to Part 9, never to a new document.

---

## Part 1 — ANSWERS: every question in Exploring.docx

Numbered by paragraph. ✅ = app already does this · ⚠ = partially / with a defect · ❌ = genuine gap
(every ❌/⚠ has a fix item in Part 9).

**Q1–Q2 (the aggregate + production narrative — SKUs, lines, stages, cycle times, bottleneck,
machine vs worker hours, OT per hour vs per shift, capacity confirmation, level-vs-chase,
build-ahead, prioritisation, demand ceiling, safety stock by service class, on-hand FG by location,
holding-cost balance).**
Your narrative IS the app's Steps 3→5→6→7, and most of it is wired:
- *"1st question: do I have enough resources"* ✅ = aggregate solve feasibility + linecap duals. ⚠ The
  aggregate LP is **single-resource (worker-time)** — a plan can be labour-feasible but
  machine-infeasible (the 12-steps doc names this gap too). Fix: multi-resource aggregate (Part 9 · V4-2).
- *Level vs chase, build-ahead in idle periods* ✅ = Hax-Meal LP with hire/fire/OT/holding/backorder
  levers; `allow_backorder` flips peak feasibility.
- *"if capacity can't extend → profit mix with a demand ceiling"* ✅ profitmix has per-SKU
  `max_demand` ceilings and firm-order floors (`_firmOrderFloor`). ⚠ but see Q3 — the hours basis is wrong.
- *OT per hour vs per shift (+8 hrs)* ⚠ aggregate prices OT **per unit** (`ot_cost_per_unit`, seed 180)
  and production prices it per hour (`hourly_rate`). Nothing models per-SHIFT blocks (a shift is an
  8-hr indivisible purchase). Fix: OT mode toggle `per_hour | per_shift(8h block)` (V4-3).
- *Safety stock per service-level class* ✅ per-part `ss_source` Heizer z·σ vs CVaR; service level is governed.
- *On-hand FG at separate locations / stores / DCs* ❌ single-site on-hand only. This is the parked
  multi-site gap (G-N2/G-I3). MEIO/meionet reason about echelons; the **transaction layer** (on-hand
  per location consumed by netting) doesn't exist. Stays parked but now has a named shape (V5-1).
- *"some products sell daily, some don't"* ✅ intermittence is detected (`_intermittence`) and routed
  to Croston/SBA/TSB.

**Q3 — "Profit mix margin/hr off cycle time alone? What about OEE?"**
You found a real defect. `profitmixPayload` (console.jsx:479) sends `cycle_time: p.cycle` **raw — OEE
is not applied**, and worse, capacity is `shared_capacity: Math.round(demandHours*0.82)` — i.e.
**capacity is defined as 82% of demand-hours**. That is circular: capacity scales WITH demand, so
"Shared Capacity" always binds at ~the same place no matter what your factory looks like, and the
0.82 is a magic number imitating OEE. Correct form: effective hours per unit = `cycle / OEE` (or
capacity = Σ line netHours × OEE from the REAL production architecture `M.lines`), and the demand
ceiling stays as is. **This is the headline solver-input fix (V2-1).** What else belongs in margin/hr:
changeover amortisation per run (currently only sequencing sees it) and yield (already in via
`yield_pct` ✅).

**Q4 — "how risky is the committed plan, where does it break — at 5th?"**
At **Step 9**, not 5: Monte Carlo replays the committed Gantt (not a re-optimised plan) → fill
distribution + CVaR95, and ResilienceStress ramps a lever until it breaks ("survives +25%, breaks
+35%"). ✅ built and differentiated (the 12-steps doc rates this DIFFERENTIATED). The 5th step is
where *economic* fragility shows (reduced costs/duals), risk fragility is 9th.

**Q5 — product relationships: shared lines, add a machine, more workers?**
The decision chain exists: profit-mix dual prices the bottleneck hour → linecap dual prices a line
hour → capital solver NPVs "buy the machine". ⚠ What's missing is the **bridge UI**: nothing says
"this dual = ₹X/hr × H hours freed by 1 machine = ₹Y/yr vs machine cost ₹Z → NPV". That's the
"Elevate the constraint" explainer card (V3-VIS-5).

**Q6 — pooled upstream SS cheaper (√N).** ✅ `meio_network.py`, capital-freed surfaced, asserted
pooled < Σ decentralised (identity I-6 in the harness).

**Q7 — how are margins defined? unit costs incl. imported subparts? cost spikes → expected margins?**
Today: margin = `price − cost` where `p.cost` is a typed unit variable cost. ⚠ Three honesty gaps:
(a) `p.cost` is NOT derived from the BOM roll-up + landed cost (the sourcing tab computes real landed
costs incl. FX/duty but products carry an independent typed cost — two sources of truth);
(b) commodity signals (D6) flow into procurement but NOT into margin shown in profit-mix; (c) carry
cost is correctly EXCLUDED from contribution margin (it's charged in EVA — that's the right
accounting). Fix: **cost provenance chain** — `p.cost` becomes `derived (BOM roll-up + landed)` with
typed override badge (V2-2). Expected-vs-current margins: keep current margin in the LP, show a
"margin at signal-adjusted costs" sensitivity column, don't silently optimise on speculative costs.

**Q8 — line/stage/machine/worker detail: needed? Unprofitable SKU with a forecast — does it just
build? OT ₹5000/shift vs ₹3000 margin? Machine purchase NPV — do big orgs define all this?**
- Stage detail is needed for exactly three things: bottleneck identity, changeover, labour pricing.
  Beyond that it's cost; don't force more granularity (Part 3's progressive disclosure keeps stages
  behind "Advanced").
- **Unprofitable build: you found a real semantic trap.** The aggregate LP treats demand as a HARD
  constraint (meet it, cheapest way) — it will happily build a margin-negative SKU because
  profitability isn't in its objective. The profit-mix LP is where the SKU gets dropped (negative
  reduced cost). The two run side by side but nothing forces S&OP to consult the mix. Fix: the
  **profitability gate** — when profit-mix drops/red-flags a SKU that the aggregate plan builds,
  raise an exception in the inbox ("you are planning to build a value-destroying SKU; demand is a
  promise, not an obligation") (V2-3). The OT-vs-margin case is the same family: if OT ₹5000/shift
  buys units worth ₹3000 margin, a *profit-aware* aggregate (max contribution − cost instead of
  min cost s.t. demand) is the structural answer — offered as an objective toggle, not a silent swap (V4-1).
- Machine NPV: yes — dual ₹/hr × hours/yr ≥ annualised machine cost, then NPV>0 via the capital
  solver. **Big orgs do define these intricacies** — SAP routings, work centers, standard costing,
  activity rates — but maintained by a master-data team and budget cycles, not per-decision. Our
  wedge is making the same rigour usable by one planner (see Part 2).

**Q9 — hurdle rate in invHoldingSpread and build-ahead? Is the money frozen? Do big orgs earn yield?**
Conceptually right: `carryRate = WACC + spread`, and the WACC term IS the hurdle — cash in inventory
can't repay debt/equity, so it's charged the opportunity cost (big orgs don't literally earn yield on
it; the charge represents the foregone alternative). ✅ procurement/policy use carryRate. ⚠ **But the
build-ahead decision does NOT**: aggregate's `holding_cost_per_unit` is a free-standing seed (₹24,
store.jsx:1344) with no link to `carryRate × unit cost`. So S&OP and procurement currently price
frozen money differently — exactly the inconsistency the 12-steps Step-1 cascade warns about. Fix:
derive aggregate holding cost from carryRate × blended unit cost (typed override allowed, badge shows
divergence) (V2-4).

**Q10 — do objective-function inputs need data-science model outputs?**
Only one already does and it's wired: forecast σ (holdout error) → SS sizing and MC draws. The
objectives themselves are deterministic LPs/MILPs — that is correct design, not a gap (stochastic
programming is a research project, not a differentiator at this tier). Worth ADDING from DS, cheap:
(a) demand σ per SKU into aggregate's backorder weighing, (b) price elasticity (if price history
exists) to validate crossover prices. NOT worth it: learned objective weights, black-box "AI
optimisation" (it would destroy the glass-box wedge). Full DS position: Part 7.

**Q11 — units flow through solvers clearly?** ⚠ Partially. The changeover hours↔minutes contract was
fixed (T3 units contract) and labour-weighted vs physical units is documented at the S&OP boundary
(the 1,260 vs 1,124 case), but there is no single **UNITS ledger**. Fix: a `UNITS.md` contract table
(every solver field: name, unit, converted-where) + a lint that flags `*_min`/`*_hrs`/`*_pct` fields
crossing files without a conversion comment (V2-5).

**Q12 — margin definitions passed through clearly?** ⚠ No — see Q7: products carry typed cost,
sourcing computes landed cost, finance computes EVA margin; three definitions. V2-2 unifies.

**Q13–Q15 — forecasting data: columns, long format.** ✅ The CSV ingestion (`parseHistoryCsv` →
`histImports`) takes long-format date/SKU/qty. ⚠ Exogenous columns are limited to promo flags +
holidays; **price is not an ingestable feature column** even though `_build_features` could carry it.
Fix: optional `price` (and free-form regressor) columns in the import → ML features (V4-4).

**Q16 — does it understand price dynamics ($10 → $20)?** ❌ Today no — price isn't a feature (Q13).
After V4-4 the ML models (RF/GB/XGB) would learn the level shift if price history is supplied.
Classical models (HW/ARIMA) never will — that's inherent, and the leaderboard would route such SKUs
to ML automatically. Holiday-day-shift across years: ✅ handled IF holidays are supplied as dates —
they're calendar features in `_build_features`, so a holiday landing on a different weekday is
represented; HW only sees it as seasonality noise (again: leaderboard routes).

**Q17–Q18 — competitor launches, a new apartment next to the shop: how do you model that?**
Honest answer: **you don't model structural breaks from history — no tool does** (o9/BY market this
as "demand sensing" but it's leading-indicator regression, not clairvoyance). The right product
mechanics, all of which we have in primitive form: (a) NPI like-modelling (analog × scale × ramp) for
a competitor-entry analog ✅; (b) manual uplift/downlift override on the committed series with an
audit log ✅ (override is logged); (c) demand-sense regime-break flag when actuals diverge 2σ ✅
(BreachFlagger); (d) a scenario branch to quantify "what if −15%" ✅. The gap is FRAMING, not maths:
a "Structural events" card that packages those four as the workflow for exactly this question (V3-VIS-2).

**Q19 — promos: pre-flagging future promos? what does output look like, an updated CSV?**
Both: historical promo flags are features; future promo periods enter the forecast horizon as
regressors; output is the committed in-app series (NOT a CSV — the CSV round-trip is the D5
ModelSurface export if you want a file) plus the DM-B attribution card ("of the total, +N units is
promo uplift, winner-counterfactual"). ✅ built; ⚠ if the winning model is promo-blind (HW), uplift
honestly reads 0 with an explanation — already handled (demand.jsx:326).

**Q20 — intermittent output? MTO mid-cycle batch, infeasible date?**
Croston/SBA/TSB output a demand RATE (smooth per-period expectation) — correct for planning,
deliberately not a lumpy replay. For MTO: firm orders already flow as floors (`_firmOrderFloor`,
forecast-consumption `max(forecast, firm)` G-D1 ✅). Mid-horizon new batch → rolling re-solve picks
it up ⚠ but **nothing answers "can I promise this date?"** — that's ATP/CTP (available/capable-to-
promise), the standard mechanism: netting uncommitted supply (ATP) or test-fitting into capacity
(CTP) and answering with the earliest feasible date + what it displaces. Genuine gap, named (V4-5).
Infeasible today → it shows as backorder/shortfall in the solve, no order-level answer.

**Q21 — "16 forecasting methods but the observability file says HW+RF?"**
The observability map is WRONG (stale simplification), the code is richer: **11 models** compete —
naive, Holt-Winters, ARIMA, RandomForest, GradientBoost, XGBoost, MLP, hybrid(HW+RF), Croston, SBA,
TSB (forecast.py:482–494), each gated by library availability and history depth. Doc fix V1-1.

**Q22 — "shouldn't each model output on its own (MAPE)?"** It does ✅ — every model produces its own
forecast + MAPE/RMSE/MAE on a held-out tail; the leaderboard ranks by MASE/MAPE and crowns a winner
per SKU; demand tab renders it (`DemModels`). If you haven't SEEN it, that's a discoverability
problem — Part 3's page anatomy puts the leaderboard one click from the commit button.

**Q23 — "did we introduce a 6×6 matrix because we have 6 SKUs? I may have n SKUs."**
Yes — and you found a real bug. `M.changeoverSkus` is a hardcoded 6-FG list (data.jsx:188) and
**`addProduct` (store.jsx:1901) does not extend it** — a newly added SKU silently falls back to
`default_min` (30) in sequencing and never appears in the matrix editor. Pairwise N×N also doesn't
scale (n SKUs = n² cells nobody maintains). Industry-standard fix: **changeover CLASSES** — each
product gets a setup class (colour/size/material family); the matrix is class×class (stays small
regardless of n); per-pair overrides allowed on top. addProduct assigns a class → instantly priced
(V2-6).

**Q24 — wastage/rework: how do big orgs configure it? our yield-in-parts vs FG-yield vs scrap?**
Big orgs use three distinct knobs, attached at different places: **component scrap %** on the BOM
line (order extra: qty/(1−scrap)), **operation yield** on the routing step (compounds down the
routing), **rework loops** as alternate routings (usually simplified to a cost adder). We have the
first two (part `scrap_factor` ✅, FG `skuYield` measured-or-typed ✅) but no per-STAGE yield
compounding and no rework adder. The honest design: keep two knobs (component scrap, FG yield),
document that FG yield = compounded operation yield (one number, measured from actuals when
available), add optional rework cost adder ₹/unit — don't build routing-level yield until stages
have real data behind them (V4-6).

**Q25 — stage-level part consumption (each stage consumes different parts at different times) —
when should the user define stages properly?**
Big orgs assign BOM components to operations and backflush at the operation. It matters ONLY when
WIP duration is long enough that buying everything for run-start materially overstates capital
(weeks-long cycle times). At current cycle times it's noise. Decision: stay FG-level consumption,
state that assumption in the Sourcing tab's method note, revisit if a user has multi-week routings.
(No build item — a documented non-goal, which is also an answer.)

**Q26 — the meta-question (deep research, blueprint, design system, verification).**
This document; Parts 2–9.

---

## Part 2 — WHAT "ENTERPRISE GRADE" MEANS HERE + the differentiation thesis

Enterprise grade is NOT feature count. For a planning tool it is six properties — incumbents are
weak at the last three, which is exactly where we differentiate:

| # | Property | Definition | Our state |
|---|----------|-----------|-----------|
| 1 | **Governed single source of truth** | every economic assumption lives once, versioned; edits cascade STALE to consumers | ✅ strong (registry + SOLVE_DEPS + freshness) — keep investing in *coverage* (Q9's holding-cost miss shows the cascade has holes) |
| 2 | **Auditability** | every number traces to a solve, an input, or a person; overrides logged | ✅ provenance chips + events[] — best-in-class for this tier |
| 3 | **Reconciliation** | plans from different solvers agree on shared quantities (the 6 identities) | ✅ unique — incumbents reconcile manually in spreadsheets |
| 4 | **Glass-box decisions** | the WHY of every recommendation visible (duals, reduced costs, crossover, Prove-It) | ✅ THE wedge — IBP/o9 hide LP internals |
| 5 | **Committed-plan realism** | risk is tested on the plan you actually committed, not a re-optimised fantasy | ✅ differentiated (MC replays the cached Gantt) |
| 6 | **One-planner usability** | the rigour of an SAP implementation without the master-data team | ⚠ THIS IS THE CURRENT WEAKNESS — Part 3 exists to fix it |

**The thesis in one line:** *SAP-grade planning maths, spreadsheet-grade honesty about it, usable by
one person.* Items 1–5 are built. Item 6 — the design system, input architecture, handholding — is
the remaining work, and it is product design work, not solver work. That is why this blueprint
spends most of its weight there.

What we deliberately do NOT chase (recorded so it stops resurfacing): IoT/real-time feeds,
operation-level APS, VRP logistics, server-side multi-user concurrency, causal-ML "demand sensing at
scale". Each is a funded-team project at incumbents; none moves our wedge.

---

## Part 3 — THE DESIGN SYSTEM OVERHAUL (bold, clutter-free)

The diagnosis you gave is correct and the survey confirms it: **every tab has its own input style**
(13 inputs in setup vs 2 in demand vs 0 in logistics; ad-hoc `Inp`/`NumInput`/raw `<input>` mixes),
**read-only walls** (finance 12 readonly-ish blocks, scenarios 13), and **hardcoded economics the
user never sees** (₹120 ordering cost, ₹24 holding, ₹8000 hire, ₹12000 fire, ₹22000 wage, 0.82
capacity factor, nRuns 500 — all in store.jsx payload builders, invisible to every screen).

### 3.1 THE GOVERNED FIELD — one input component to rule every tab

Every number a solver consumes is rendered by exactly one component, `<GovField>`, with five faces:

```
┌─────────────────────────────────────────────────────────────┐
│ Ordering cost            ₹ [ 120 ]  /order      ⓘ  ◦seed    │
│ used by: Procurement · Policy(EOQ) · Joint-replenishment    │
└─────────────────────────────────────────────────────────────┘
```

1. **Value + unit** — the unit is rendered, never implied (kills the Q11 class of bug at the UI).
2. **Source badge** — `◦seed` (illustrative default) · `✎typed` (user override) · `ƒderived`
   (computed; click shows the formula and its inputs) · `▣solved` (a solver wrote it). One glance =
   "is this MY number or the demo's?" — the single highest-leverage handholding feature.
3. **Used-by line** — which solvers consume it (generated from SOLVE_DEPS, so it can't lie). Answers
   "is this information indeed needed?" — and a field with an EMPTY used-by line fails the lint and
   must be removed (the mechanical answer to "do we need as many inputs?").
4. **ⓘ why** — one sentence of meaning + the formula it enters ("Carried into EOQ: √(2·D·S/H)").
5. **Stale ripple** — editing pulses the affected solver chips in the page header (cascade made visible).

**Migration rule:** no new bespoke inputs anywhere; tabs convert one at a time (V3 phases). The
hardcoded payload constants become governed config fields rendered with GovField (`◦seed` badge) —
*that alone* converts the "user may not know how they are being utilized" complaint into a feature.

### 3.2 PAGE ANATOMY — one skeleton for all 12 tabs

Every tab renders the same five bands, top to bottom. This is the boldest single change and the one
that kills "every section has its own weird style":

```
① DECIDE strip   — what question this tab answers, in one sentence, + the 1–3 KPIs
                   that answer it (and their freshness chips)
② INPUTS         — GovFields, grouped; "Advanced" groups collapsed by default
③ ACT            — the solve button(s) with plain-language labels ("Find cheapest
                   workforce plan"), preconditions stated when disabled
④ RESULT         — the solver result, AT the point of decision (see Part 4),
                   each result block: number → viz → DecisionExplainer sentence
⑤ LEARN          — method note ("what the solver does", named method), gaps/honesty
                   notes, link to Reference deep-dive
```

Handholding without clutter comes from the ① DECIDE strip (the user always knows why they're here)
plus collapsed-by-default depth — NOT from wizards or tooltips-everywhere. The existing journey rail
(steps within a tab) stays; it conforms to the skeleton.

### 3.3 TWO MODES, ONE TRUTH — Guided vs Expert

A single toggle in the chrome (persisted):
- **Guided** — band ② shows only fields whose used-by includes the tab's primary solver AND that are
  `◦seed/✎typed` (i.e. things the user should look at); derived/solved fields fold into "computed
  from your inputs (n)". Each tab shows its "do these 3 things" mini-checklist.
- **Expert** — everything visible, denser grid, keyboard-first.
This replaces the scattered per-card "Advanced" buttons with ONE consistent disclosure law.

### 3.4 VISUALIZERS & EXPLAINERS — the named set (build in this order)

Each is a reusable component, fed only by already-solved numbers (no faking):

1. **VIS-1 Feasibility thermometer** (Plan ①): demand-hours vs capacity-hours per period as one
   bar pair — the literal answer to "do I have enough resources", currently buried in tables.
2. **VIS-2 Structural-events card** (Demand): packages NPI-analog/override/sense-flag/branch as the
   "competitor launched / market changed" workflow (Q17–18).
3. **VIS-3 Level-vs-chase strip** (Plan): workforce line vs demand line vs inventory area, the
   12-steps Step-3 picture, from the real aggregate solution.
4. **VIS-4 Bottleneck Gantt ribbon** (Production): existing gantt + a red "every idle minute is
   lost forever" highlight on the binding line, changeover slivers visible (Step-4 picture).
5. **VIS-5 Elevate-the-constraint card** (Console/Production): dual ₹/hr × freed hrs → vs machine
   cost → NPV chain in one card (Q5/Q8 bridge; numbers from profitmix dual + capital solver).
6. **VIS-6 Feasible-region toy** (Profit mix, Learn band): 2-SKU interactive of the actual LP
   (capacity line, demand ceilings, iso-profit, optimal vertex) — the Step-5 SVG, live.
7. **VIS-7 BOM explosion tree** (Sourcing): FG → subasm → RM with per-node lead-time bars and SS
   buffers (Step-6 picture; the data already exists in `bomForSku`).
8. **VIS-8 √N pooling picture** (Inventory): decentralised vs pooled side-by-side with capital-freed
   ₹ (Step-7 picture).
9. **VIS-9 Fill-rate distribution** (Risk): MC histogram + CVaR shading + committed-plan marker
   (Step-9 picture; today it's mostly numbers).
10. **VIS-10 Cascade ripple** (global): on any governed edit, the affected solver chips pulse in
    sequence — Step-1's STALE cascade made kinetic, the single best trust-builder we can ship.

---

## Part 4 — CONSOLE vs PER-PAGE RESULTS: the decision

**Decision: results live at the point of decision (band ④ of each tab). The Console stops being a
results page and becomes the CONTROL TOWER. Reference keeps the model map.**

Rationale: a planner deciding "what do I buy" needs procurement results IN sourcing; walking to a
console breaks the decide-act loop and creates the duplicate-rendering class of bug we've already
hit (FIN-1 Buy-vs-Lease rendered twice; profitmix cards in console AND fragments elsewhere). The
console's unique value is CROSS-solver: nothing else can show freshness, exceptions, and identities
in one place.

Concretely:
- **Move:** profit-mix result cards + DecisionExplainer + Prove-It → the Profit-mix/Production tab
  (they are per-decision artefacts). Capital/NPV cards → Finance. Transport card → Logistics.
- **Console keeps (and is reduced to):** the run-all loop button + run ledger · solver fabric/
  freshness wall · ExceptionCockpit (inbox) · ValueLedger · cross-solver ConsistencyPanel summary
  (full panel stays in Reference▸Model Map).
- **Rule going forward:** a solver's result renders ONCE, in the tab that owns the decision; the
  console may show a one-line KPI + freshness chip linking there. (Enforced by a model_check rule:
  no two components bind the same solve key's result table — V2-7.)

---

## Part 5 — INPUT-ARCHITECTURE AUDIT (per module, the mistakes found)

Survey evidence (2026-06-10): input-field count vs read-only blocks per tab — setup 13/4,
products 12/6, network 9/2, demand 2/8, sourcing 13/11, plan 5/2, production 7/4, console 2/4,
finance 4/12, logistics **0**/2, scenarios 3/13, reference 4/6.

| Module | Mistakes / smells | Fix (Part 9 ref) |
|---|---|---|
| **Setup** | Good shape (registry exists) — but the registry doesn't hold everything it claims to govern: aggregate cost seeds (hire/fire/OT/holding/wage), MC nRuns, profit-mix 0.82, ordering-cost 120 all bypass it (store.jsx:815,1344-46; console.jsx:494). The cascade has holes where it matters most | V2-4, V3-1 |
| **Products** | `p.cost` typed, not BOM-derived (two truths — Q7); `p.cycle` raw vs OEE ambiguity (Q3); shelf-days→weeks conversion hidden in a payload comment; new product doesn't enter changeover matrix (Q23) | V2-1/2/6 |
| **Network** | scheduled receipts absent (MRP nets on-hand only — Tier-1 #4); on-hand single-site (Q1) | V2-8, V5-1 |
| **Demand** | Strongest tab; only 2 typed inputs by design (right!). Smells: leaderboard discoverability; price not ingestable (Q16); seed-history "illustrative" warning good but winner-MAPE>30% review gate (12-steps Step-2) not enforced | V3-2, V4-4 |
| **Sourcing** | Best input coverage but heaviest read-only wall (11 blocks); ordering_cost 120 hardcoded vs master S (Tier-1 #3); supplier capacity unmodelled (12-steps Step-6 gap — accepted non-goal for now, documented) | V2-9 |
| **Plan (S&OP)** | All 7 Hax-Meal cost levers are payload seeds, only some surfaced; holding cost not carryRate-linked (Q9); single-resource (Q1); 13-wk fence hardcode (Tier-1 #1) | V2-4, V2-10, V4-2 |
| **Production** | OT per-shift mode missing (Q1); changeover class model (Q23); per-line `cap` field dead to production.py (SF-7 finding) still rendered as if it mattered — label or remove | V2-6, V4-3, V2-11 |
| **Profit mix (console)** | THE 0.82 circular capacity + raw cycle (Q3); results live in wrong place (Part 4) | V2-1, V3-3 |
| **Inventory** | sound (MEIO/meionet); multi-site parked | V5-1 |
| **Logistics** | ZERO editable inputs — lane costs/weights are master-data only; outbound-only framing now documented but the tab can't be steered at all | V3-4 |
| **Finance** | 12 read-only blocks — correct (finance DERIVES), but WC ledger still seeded (T3.9, already queued) | T3.9 |
| **Scenarios** | good; SubflowHarness quiet-mode done; clutter — cockpit hosts too many cards (Part 4 trims) | V3-5 |

**The global input laws** (new, enforced):
L1 — every solver-consumed number is a GovField (no payload-builder literals; lint V2-12 greps
builders for numeric defaults not sourced from config/master).
L2 — every field shows its used-by; empty used-by ⇒ delete the field.
L3 — derived beats typed: where both exist, derived is default + typed is a badged override.
L4 — units rendered, conversions at ONE boundary per pair, recorded in UNITS.md.

---

## Part 6 — SOLVER INPUT CONTRACTS ("do we need as many? have I made mistakes?")

Verdict per solver (16): inputs are broadly RIGHT-SIZED — the mistakes are (a) wrong basis (OEE),
(b) ungoverned seeds, (c) two-sources-of-truth, not over-parameterisation. Nothing should be cut
except where noted; the real fixes are bindings.

| Solver | Inputs verdict | Defects → fix |
|---|---|---|
| calendar | ✅ minimal | — |
| forecast | ✅ rich & right (11 models, holdout, grain-aware lags) | price/exog column (V4-4) |
| aggregate | ⚠ 7 cost levers correct per Hax-Meal, but seeds ungoverned + holding≠carryRate·cost (Q9) + single-resource | V2-4, V4-2 |
| production | ⚠ `M.lines[].cap` dead (routing supersedes) — mislabelled input | V2-11 |
| sequence | ⚠ matrix doesn't scale/grow (Q23) | V2-6 |
| profitmix | ❌ capacity basis wrong (0.82 circular, no OEE) — the one outright mathematical mistake found | **V2-1** |
| procurement | ⚠ ordering_cost literal; supplier capacity non-goal documented | V2-9 |
| policy / joint | ✅ | — |
| meio / meionet | ✅ (GSM + √N honest) | — |
| transport | ✅ for the declared single-mode scope; zero UI steering | V3-4 |
| montecarlo | ⚠ independent draws (no demand correlation matrix — 12-steps Step-9 enhancement); nRuns seed | V4-7 |
| whatif | ✅ | — |
| capital / capital_structure | ✅ | — |
| linecap | ✅ (its `cap` input is the legitimate consumer) | — |
| npv | ✅ (FIN-3 shield fixed) | — |

**Units & margin flow (Q11/12):** one boundary table to write (UNITS.md, V2-5) covering: hours↔min
(changeover, DONE), days↔weeks (shelf), physical↔labour-weighted units (S&OP), ₹↔₹L (display only),
typed-cost↔BOM-landed (margin chain V2-2), carryRate %→₹/unit/period (V2-4).

---

## Part 7 — DATA SCIENCE: have / add / refuse

**Have (and it's more than the docs admit):** 11-model competition with per-model holdout
MAPE/RMSE/MAE + MASE ranking; intermittency detection & routing; PI cone (σ per period from holdout);
promo counterfactual attribution; NPI analog modelling; regime-break sensing; external commodity/
port-delay signal drivers into procurement.

**Add (cheap, on-thesis):**
1. Price & custom exogenous columns in history import → ML features (V4-4 — unlocks Q16).
2. Demand-correlation matrix in MC (systemic-risk tails; we already have pairwise ρ machinery from
   MN-C) (V4-7).
3. Forecastability score per SKU (CoV + intermittence + history depth → "trust this forecast?"
   badge feeding the winner-MAPE review gate) (V3-2).
4. σ-aware backorder weighting in aggregate (Q10) (V4-1 rider).

**Refuse (recorded):** causal-ML demand sensing networks, learned objective weights, LLM-generated
plans, black-box AutoML — they all trade away the glass-box wedge for incumbents' marketing language.

---

## Part 8 — VERIFICATION STACK: is provenance + H1 + H1b + H2 the best way?

The four layers are the RIGHT architecture (static lint → static model check → booted golden path →
behavioural subflows) — each has caught a bug class the others missed (OBS-3: untraced chips;
HARNESS-1: shadowing/_excluded; HARNESS-1b: B-16 blank-app; HARNESS-2: B-13/B-14). Do not replace.
Three real improvements:

1. **V1-2 One gate:** `tools/gate.sh` runs lint → model_check → golden_path in order, one
   command, one PASS/FAIL line each. (HARNESS-2 stays in-app/behavioural, invoked from scenarios.)
2. **V1-3 Solver unit tests:** the genuinely missing layer — pytest fixtures per `.py` solver with
   golden numeric cases (the B-14/B-15 field-contract class would be caught in python, before the
   browser). ~1 file per solver, tiny.
3. **V1-4 Assertion ratchet:** the 54 assert-now items from GOLDEN_JOURNEY_SPEC become Layer-A
   checks in golden_path.js incrementally (already the plan) — gate.sh runs them all.

Verdict: not "too many subsections" — too many ENTRY POINTS. One command fixes the experience.

---

## Part 9 — THE EXECUTION PROGRAM (phased; each item has an assert)

Discipline per item: one item at a time → fix → probe (browser-boot where UI) → `gate.sh` green
(HARNESS-1b stays 9/9; baseline byte-identical unless the item is explicitly baseline-moving).

**V1 — TRUTH & TOOLING (days):** ✅ BUILT 2026-06-10
V1-1 ✅ obs-map forecast claim corrected in 3 places (11-model leaderboard, was "HW+RF") ·
V1-2 ✅ `tools/gate.sh` — ONE command, 4 layers in depth order (pytest → OBS-3 lint → HARNESS-1 →
HARNESS-1b boot), auto-starts the server the sanctioned way (nohup+pidfile) ·
V1-3 ✅ **honest correction to Part 8: a pytest suite ALREADY existed** (`tests/`, May-30 era,
15 files — Part 8's "genuinely missing layer" claim was wrong). It ran 72/73 after five weeks of
solver edits; the 1 failure was an over-strict TEST (asserted the intermittent family must WIN;
the honest contract is winner = lowest MASE whoever earns it, the steered field is
`recommended_model` — test fixed, not the code). Added `tests/test_v1_contracts.py` covering the
8 uncovered solvers (transport, meio, meio_network, linecap, capital budget, capital_structure,
finance.npv, sequencing.evaluate_line) with HAND-verified goldens (annuity NPV 243.43/516.31,
z·σ·√τ 46.5, √N pooling 41.11/0.71, 2×2 transport 20, Hamiltonian 30 min, after-tax WACC 0.0965)
+ the B-14/B-15 field contracts + I-6 identity at unit level. Two UNITS findings for V2-5's
UNITS.md: `tax_rate` and `hold_pct` are PERCENT at the python boundary (store already complies) ·
V1-4 ✅ ratchet recorded: GOLDEN_JOURNEY_SPEC's 54 assert-now items land incrementally as Layer-A
checks in golden_path.js, one per V2/V3 item touched, never as a separate suite — gate.sh is the
single entry point and stays so.
*Assert: `bash app_v2/tools/gate.sh` → 4/4 layers green (run 2026-06-10).*

**V2 — CORRECTNESS OF INPUTS (the mistake list — do before any visual polish):**
V2-1 profitmix capacity = real architecture hours × OEE; cycle/OEE basis — **✅ BUILT 2026-06-10**:
profitmixPayload sends profitmix.py's REAL line pool (M.lines → `lines[]`: `avail_hrs_per_week`
= workDays×8×shifts, per-line OEE, routing-pinned `eligible_skus` + `cycle_time_by_sku_min`, same
eff-routing rule as productionPayload) + `planning_horizon_months:12` (master `p.demand` is ANNUAL
— MPS weekly ≈ demand/52) + real per-SKU `mape_pct` + `max_quantity` (so a binding demand ceiling
is PRICED as a "Max prod:" dual), replacing circular `shared_capacity=demandHours×0.82`. RecTest
capacity prove-it now perturbs the named line's weekly hours (+5%×weeks×OEE), not the dead scalar.
**NEW GOLDEN declared in golden_path.js (gate 4/4):** at TPAC volumes lines are HONESTLY slack
(pm util max 16%; linecap 0/3 bind agrees) → priced scarcity is DEMAND (dual ₹930/u = top unit
margin); I-2 additionally asserts line-dual ⇄ utilization consistency (binding ⇔ ~100%). ·
**V2-2 cost provenance chain — ✅ BUILT 2026-06-10 (gate 4/4, observed probe):** new store
`unitCostBreakdown(sku)`/`effUnitCost(p)` = THE one unit-cost: live BOM material (bomForSku, incl.
qty overrides) + labour/unit + setup/lot (productCosts, seeds 18%·₹4200) + conversion&OH residual
anchored to a ONE-TIME seed-part-cost snapshot (`_seedPartCost`) so total ≡ typed `p.cost` at seed
(observed 6/6 FGs exact) and an edit MOVES the total (first attempt anchored to the live master and
a +₹50 part edit moved NOTHING — probe caught it; fixed). Rewired consumers: profitmixPayload +
single-SKU whatif (console), montecarloPayload, cvar payload, linecap lost-margin (plan.jsx +
_loopLinecapPayload), tcoPerSku, reportPdf, finEva/finOpsCapital/margin-per-hr (finance), what-if
bot + cockpit weighting (scenarios). ProdCosts (products.jsx) now RENDERS the shared breakdown
(its old local residual had the absorb bug) + a ≡/⚠-diverged provenance line vs typed std cost.
SOLVE_DEPS: +bom→profitmix/linecap, +productCosts+bom→montecarlo. Observed: RM-STL42 +₹50 moved
profit-mix variable_cost for exactly the 4 FGs whose bills carry it. OPEN remainder (Q7b): landed/
signal-adjusted margin stays a SENSITIVITY view to build (not silently in the LP — by design). ·
**V2-3 profitability gate — ✅ BUILT 2026-06-10 (gate 4/4, observed probe, both branches):**
`exceptionInbox` (scenarios.jsx) now crosses the COMMITTED production gantt (what we will build)
against the cached profit-mix solve (what is worth building) — new H-severity `PROFIT` category
(⛔). Two branches: (1) schedule builds N units of a SKU the LP DROPS (qty≈0; message quotes the
reduced cost: "margin must rise ₹X/u to enter") — observed: TPA-2188 price cut below cost → "the
schedule builds 288u … LP DROPS it (₹500/u) — demand is a promise, not an obligation"; (2) a firm-
order demand FLOOR forces a negative-margin build (LP can't drop it) — observed: TPA-4471 (480u
floor) → "built at a NEGATIVE margin of ₹500/u — a demand floor forces a value-destroying build".
Baseline silent (0 PROFIT items, all 6 FGs profitable). Q8's structural fix (profit-aware aggregate
objective toggle) stays V4-1. ·
**V2-4 aggregate holding = carry-anchored — ✅ BUILT 2026-06-10 (gate 4/4, observed probe;
BASELINE-MOVING for the aggregate plan):** new store `aggHoldingPerUnit(cfg)` = carryRate (WACC +
holding spread, annual) × demand-weighted blended `effUnitCost` ÷ 12 (aggregate periods are months;
blended is dimensionally right because aggregate units are demand-weighted mean-normalised labor
units ≈ one average physical unit) + `aggHoldingParam(cfg)` (typed planParams override WINS).
Observed: 23.95% × ₹976 ÷ 12 = ₹19/u/mo (was the free-standing ₹45 placeholder — S&OP build-ahead
and procurement priced frozen money differently, Q9); loop payload carries 19; override 99 wins;
solve Optimal. Both builders rewired (plan.jsx StagePlan + _loopAggregatePayload); Holding-cost
SolverInput seed now shows the derived value + provenance hint. Aggregate-seed governance audit:
the other params (reg/ot/backorder/hire/fire/wage/rate/init_wf/min_wf/max_ot/allow_bo/init_inv)
were ALREADY governed (PLAN_PARAMS seeds + SolverInput fields + planParam overrides) — the real
finding was store's last-resort fallback literals (120/180/24/300/8000/12000) silently DISAGREEING
with plan.jsx's live seeds (820/1230/45/1500/18000/25000); aligned. SOLVE_DEPS: aggregate
+config+bom. ·
**V2-5 UNITS.md + units lint — ✅ BUILT 2026-06-10 (gate 4/4; lint negative-tested):**
`app_v2/UNITS.md` = the ledger (5 tables: percent-vs-fraction trap table · time · demand/grain ·
money · mass/quantity; ONE sanctioned conversion site named per boundary). HEADLINE FINDING: the
suffixes LIE — `yield_pct` (0.95) and `max_ot_pct` (0.25) are FRACTIONS despite `_pct`, while
`hold_pct`/`tax_rate`/`mape_pct` are true PERCENTS (python ÷100) and `carry_rate` (0.24 fraction)
coexists with `carry_rate_pct` (24 percent, meio nodes) — all python-verified line-by-line.
`tools/units_lint.js` makes the ledger SELF-ENFORCING: scans app_v2/*.jsx for unit-suffixed keys
(bare/quoted/ES6-shorthand — shorthand added after `cycle_time_by_sku_min` escaped the first
regex) crossing the JS→Python boundary; each must have a backticked UNITS.md row or exit 1.
25 boundary keys ledgered; negative-tested (planted `bogus_test_pct` → FAIL names key+file:line →
restored PASS). Wired into gate.sh layer 2 (provenance + units lints in one step — gate stays the
single 4-layer entry). Honest scope in both files: member-access result reads + python-internal
fields not required. The V2-4 ÷12-coupled-to-monthly-periods caveat recorded in §4. ·
**V2-6 changeover classes — ✅ BUILT 2026-06-10 (gate 4/4; probe observed):** `M.changeoverClasses`
(data.jsx) = class×class HOURS table over `order:['PRC','STD','HVY']`; each FG carries `coClass`
(4471/9904 PRC · 3215/5540 STD · 2188/7722 HVY, by line family). `classChangeoverHrs(a,b)` (store,
exported) derives any pair via coClass (STD fallback; null only if the table is absent). `addProduct`
now EXTENDS `changeoverSkus`+`changeover` with a class-derived row+col ('—' diag, markStale prodArch)
— pre-fix a new SKU had no row, subMatrix skipped its pairs, and the scheduler silently used the
30-min default for a product that may need a 2-hr heat-treat purge. `_snapshotProdArch`/`_restore`
now carry `changeoverSkus` (the matrix can GROW, so sku order must travel with it or a scenario
restore would misalign rows). Probe (real browser, real addProduct, HVY probe SKU): 6×6→7×7,
HVY→PRC 2.0 / HVY→STD 1.8 / HVY→HVY 1.6 exact, productionPayload emits 96 min (1.6h×60) for the
new SKU's LINE-03 pairs, master byte-restored. ·
**V2-7 one-result-one-home — ✅ BUILT 2026-06-10 (gate 4/4; rule negative-tested; render probe):**
the Part-4 moves executed: ResProfit (+DecisionExplainer+RecTest+SingleProductCheck) → NEW
Production ▸ Profit-Mix subtab (the make/drop decision's home — it had none) · ResCapital →
Finance ▸ Investments (beside lease-vs-buy; FinInvest's capital-CAPACITY card is a different
solver) · console's ResTransport DELETED (its tables were a 2nd render of the solve Logistics
already owns; its GlassBoxExplainer moved to Logistics step 2). Console's three slots are now
`ResultHomeLink` cards (cached one-line KPI + stale chip + open-tab nav) — control tower, not a
second copy. ENFORCED: model_check `one-result-one-home (V2-7)` — every `<Res[A-Z]*` component
JSX-mounted at most once across all jsx + RESULT_HOMES pins ResProfit→production.jsx,
ResCapital→finance.jsx; negative-tested (2nd `<ResProfit/>` in console → FAIL names both mounts).
Render probe (real clicks past the onboarding wizard): Profit Maximizer Results in Production ✓,
Capital Budget Results in Finance ✓, console shows link card NOT the table ✓. ·
**V2-8 scheduled receipts — ✅ ALREADY BUILT (G-N1), CLOSED 2026-06-10 with tests (gate 4/4):**
the full path pre-existed uncommitted: data.jsx seed POs → Network editor → `network.scheduledReceipts`
slice → `scheduledReceiptsLocked()` (code→name translation — procurement.py matches by payload
`name`) → `locked_pos` in BOTH procurement payloads → procurement.py T6 books each at release+lead
as exogenous RM arrival. What was MISSING was any test: added `tests/test_v2_scheduled_receipts.py`
(3 GOLDEN contracts, hand-reasoned 160-demand/60-locked ⇒ buy nets 160→100 EXACTLY, on both the
legacy `period` path and the `releaseDate` date-math path; unknown-part + out-of-horizon locks
ignored). Live probe: real `_loopProcurementPayload` carries both seed POs name-translated +
horizon_start_date. pytest 82→85. ·
**V2-9 ordering_cost — ✅ ALREADY GOVERNED, CLOSED 2026-06-10 (probe observed):** all 5 master
BOM rows carry S (1200/900/140/60/80); store.jsx:825 sends `ordering_cost:(Number(b.S)||120)`;
probe read the REAL loop payload — all 5 parts emit exactly master S. The ||120 fallback is only
for an S-less row (registered in PAYLOAD_LITERALS.md). ·
**V2-10 13-wk fence — ✅ ALREADY GOVERNED, CLOSED 2026-06-10 (probe observed):** `planning.
productionScheduleWeeks` (seed 13) + Setup "Schedule Fence" field + registry row + clamp in
productionScheduleHorizon. Probe: default 13; override 8 → horizon 8 AND productionPayload
params.periods 8. ·
**V2-11 dead `lines[].cap` — ✅ LABELLED HONESTLY 2026-06-10 (gate 4/4):** confirmed in
production.py: C5 binds MACHINE-HOURS × OEE whenever cycle data/routing is present (always, from
this UI); `capacity` is read only in the legacy no-cycle fallback — the REAL consumers of l.cap
are linecap (dual LP) + the aggregate envelope (SF-7). Fixed the lying surfaces: ProdArch footer
u/mo figure now tagged `linecap·agg` + tooltip; "Derived Capacities" card flows-text corrected
(was "→ aggregate & production MILP"); store.jsx payload comment states the legacy-fallback-only
truth. Display-only change — gate baseline identical. ·
**V2-12 payload-literal lint — ✅ BUILT 2026-06-10 (gate 4/4; double negative-tested):**
`tools/payload_literal_lint.js` + `PAYLOAD_LITERALS.md`. Discriminator: solver payload keys are
snake_case, UI props camelCase ⇒ any `snake_case_key: <bare numeric>` in app_v2 jsx is a payload
literal by construction; governed values are EXPRESSIONS and never match. Every pair must be
backtick-registered in the ledger (41 found: PLAN_PARAMS seed table · CAPEX demo proposals ·
finance card examples · store/sourcing seeds · STRUCT zeros · `rehire_notice_hrs: 80` explicitly
TODO-GOV) — a NEW literal fails the gate AND a value CHANGE on a registered one fails until
re-registered (drift is a decision). Negative-tested both ways (planted `bogus_magic_cost: 999` →
FAIL; drifted 80→120 → FAIL; restored → PASS). Wired into gate layer 2 (3 lints, one step).
**→ V2 QUEUE COMPLETE.** Still open from the V2 era: Tier-1 #2 pure-MTO verify-close · Q7b
landed/signal-margin sensitivity view · `rehire_notice_hrs` TODO-GOV (ledgered). · **V2-13 horizon/grain
basis correctness — ✅ BUILT 2026-06-10 (gate 4/4, observed via re-run probe):** (a) getItemDemand's
seed is now a RATE — `annual × periodDays/364` where periodDays = horizonDays/T (T buckets span the
horizon, same convention as firmOrderDemand); at the 52-wk default this is exactly `annual/T`
(byte-identical baseline), at any other horizon the rate no longer moves — observed required_qty
52wk 1,140 / 30wk 1,140 (was 1,620, +42% bug). (b) schedule basis is WEEKS whatever the grain:
productionScheduleHorizon converts horizonLength grain→weeks before fence-clamping (50 days → 8
weekly periods, was 13); finishedWeeklyDemand resamples committed DAILY series by 7-day sums and
MONTHLY series by /4.33 spread (volume-conserving) and sizes the seed path in week-equivalents.
Observed: 50 days → 8 periods × 48 weekly hrs (capacity and demand on the same clock).
**+ HOURS/HARDCODE AUDIT (user ask "is hrs/day hardcoded to 8?") — fixed same day:** Setup's
`planning.hrsPerShift` field existed but was DEAD at every consumer — store.jsx productionPayload
hardcoded `hrsPerShift=8`, console.jsx profitmix lines hardcoded `×8`, production.jsx read the
nonexistent `config.hrsPerShift` — all three now read the governed `planning.hrsPerShift` (probe:
8→10 moves hrs_per_period 48→60 and pm avail_hrs 48→60). `setup_cost:50` (production + montecarlo
payloads) → governed `config.prodSetupCost` (ProdParams field, cfg.prod stale token; MC prices the
SAME value). production.py labor budget `headcount×40.0` → governed `params.labor_week_hrs` =
workDays×hrsPerShift (40 only as no-param fallback). SOLVE_DEPS gap: profitmix now depends on
`planning`+`prodArch` (its V2-1 payload reads both).
*Assert per item: a named identity or probe; V2-1's new golden recorded in goldens file.*

**V3 — DESIGN SYSTEM (the overhaul, tab by tab):**

**V3-0 ✅ BUILT 2026-06-10 — GovField + source badges + used-by from SOLVE_DEPS.**
NOT a restyle: GovField (lib.jsx, after SolverInput) consolidates the EXISTING language —
SolverInput's validation core, the `_PROV` badge set (◇seed/⌨input/ƒderived/⚙solved), C/F tokens.
Five faces per Part 3.1: value+UNIT always rendered · source badge (value==seed ⇒ ◇seed, like the
registry's ov() compare; clearing reverts to seed) · used-by chips GENERATED from new store helper
`solversUsing(token)` over SOLVE_DEPS (cannot lie; empty ⇒ loud ⚠ NO CONSUMER) · ⓘ why popover
(sentence + formula) · edit ripple (chips pulse amber + "→ STALE" for 900ms; the real markStale
still fires in the caller's setX). Pilot mounts (Setup): Service Level (token `config`, seed 95%)
+ Net Hrs/Shift (token `planning`, seed 8h). Enforcement: model_check §2c¾ `GovField tokens ⊂
SOLVE_DEPS` (token extracted from the REAL SOLVE_DEPS object; mounts in lib.jsx excluded) —
negative-tested BOTH branches (bogus token "plannning" FAILs at file:line; missing token= FAILs).
Observed: browser probe 11/11 — boots clean, ◇SEED badge, used-by(config) chips == the 9
SOLVE_DEPS consumers exactly, edit 95→97 ripples + flips to ⌨INPUT + writes config.serviceLevel
0.97 + procurement goes stale, ripple decays, typing the seed value reads ◇seed again. Gate 4/4.
**USER DIRECTIVE (2026-06-10, governs all V3 conversions): no scattered hardcoded data — ONE
sample problem (the TPAC seed dataset) prefilled throughout as the example, every prefilled number
wearing the ◇seed badge and overridable. GovField is the carrier of that rule.**

**V3-1 ✅ BUILT 2026-06-10 — Setup fully converted to GovField.** All six remaining numeric
solver-feeding inputs converted (setup.jsx): Effective Tax (token `config`, seed 25.17%) ·
Horizon (token `planning`, seed 52, integer) · Work Days/Wk (`planning`, seed 6) · Frozen Wks
(`planning`, seed 4) · Slushy Wks (`planning`, seed 12) · Schedule Fence (`planning`, seed 13)
— each with why+formula, joining the two V3-0 pilots = 8 GovFields on Setup. HONESTY CALL:
investmentCr/annualTurnoverCr stay plain NumInputs — they feed ONLY the derived MSME tier, no
SOLVE_DEPS consumer, so used-by chips would lie (GovField requires a real token). Non-numeric
inputs (name/currency/state/GST/CIN/date/grain segments) keep their controls. Observed: probe
15/15 (all 8 mount with the ◇SEED face at boot — values==seeds — Frozen Wks 4→6 ripples
"→ STALE", flips ⌨INPUT, writes planning.frozenWeeks, production goes stale; revert reads
◇SEED). Gate 4/4 (model_check now validates 8 mounts' tokens).

**V3-2 ✅ BUILT 2026-06-10 — Demand: forecastability + the enforced MAPE review gate.**
(demand.jsx) `forecastability(series, intc)` = CoV + intermittence (engine read wins over the
zero-share proxy) + history depth → EASY/MODERATE/HARD badge, shown in the step-2 winner strip.
`mapeReviewGate(winMape, fab)` (REVIEW_MAPE=30, 12-steps Step-2) is ENFORCED at the consensus
commit: >30% swaps the one-click "✓ Commit as consensus" for "⚠ Reviewed — commit anyway" which
logs `mape_review` + `forecast_commit{reviewed:true}`; the gate message uses the badge (a 35% on a
HARD SKU is expected; on an EASY one it's a data red flag). Override/lifecycle/sensing stay ungated
(those ARE planner judgement). Leaderboard surfaced at the winner: "beat <runner-up> by X pts of N
models" + the existing ↓-leaderboard link. Observed probe 12/12 — BOTH branches live (seed history
5.7% MAPE ⇒ ungated; erratic CSV import ⇒ 132.3% MAPE, HARD, gate bites, events logged). Gate 4/4.

**V3-3 ✅ BUILT 2026-06-10 — VIS-6 feasible-region toy (the V2-7 move already gave profit-mix its
home).** (production.jsx ▸ Profit-Mix, Learn band step 2) `Vis6FeasibleRegion` draws the 2-SKU
restriction of the LIVE LP — constraints from the same profitmixPayload() the solver receives
(line hrs × OEE × horizon weeks, demand ceilings, firm floors, real margins), optimal corner by
exact 2-D vertex enumeration (`_v6Solve`), iso-profit line through it. Toy-local sliders (write
NOTHING): margin-A rotates the objective; "line hours ×" shrinks real capacity until the wall cuts
the demand box — the SF-7 lesson interactive. Slack capacity honestly annotated off-chart. Probe
10/10 incl. golden: baseline corner == BOTH demand ceilings exactly (lines slack at TPAC volume);
×0.04 ⇒ 2 lines bind and the corner moves (2840,4120)→(1198,1565). Gate 4/4.

**V3-4 ✅ BUILT 2026-06-10 (restructured per user) — Logistics steering = a TAXONOMY of model
terms, not an honesty disclaimer.** First draft governed all 5 outbound lane rates → probe showed
3 of them never move the solve (mode-booked legs are priced from MODE_SPECS ₹/kg, not lane rate);
user pushed: "how should the section be structured properly?" Final shape (logistics.jsx
`LogSteering`, 7 GovFields in 3 groups = one lever per model term, every leg priced by exactly one
lever): **A Service policy** — `config.slaDeadlineDays` (seed 7d) → `deadline_days` (store.jsx;
transport dep +config; literal pruned from PAYLOAD_LITERALS). **B Mode tariffs ₹/kg** —
`config.modeTariffs{road_ftl·road_ltl·rail·air_standard}` (seeds = transport.py MODE_SPECS) →
`params.mode_overrides[mode].cost_per_kg` (NEW wire; UNITS.md row added: ₹/kg, no conversion,
distinct from lane rate ₹/km) — the proper lever for PLANT→WH / WH→DC legs. **C Final-leg lane
rates ₹/km** — the 2 DC→customer lanes' `network.lanes[].rate` → allocation `cost_matrix = rate ×
km`. Probe 15/15 observed: LTL tariff 3.5→30 moves mode-LP total ₹11,476→₹81,568 (FTL/rail
honestly inadmissible at 529 kg/shipment); lane rate 22→200 reroutes CUST-GGN Pune→Bengaluru DC;
all ◇SEED faces, ripple, stale cascade, seed reverts. Gate 4/4.

**V3-5 ✅ BUILT 2026-06-10 — Console reduced to the Part-4 control tower.** (console.jsx) REMOVED:
the inert Run-Profile picker (composed a profile nothing consumed; ▶ SOLVE permanently disabled)
and the SEED Solve-Status card (selSolver.status/obj + static M.shadow dual table — seed numbers
wearing a live face). REPLACED with live-state-only surfaces: `EngineStatus` (freshness +
last cached objective + ranAt from solverFreshnessMaps/_OBS_KEY, with "stale because you edited
<root>") and `TowerRow` — the Part-4 one-line-summary+link rule applied to NON-result surfaces
too: exception-inbox count (live `exceptionInbox()`) → Scenarios cockpit · last events from the
audit log → ValueLedger · fresh/stale/never counts → Reference Model Map (identities NOT
recomputed — the OBS-2 panel is gate-pinned to the harness, a second computation could drift).
Probe 16/16 observed: reductions verified absent; boots honest (0/16 fresh, "not run"); a REAL
▶ Run spine flips 5+ engines fresh, Engine Status shows the cached objective, tower chip updates;
identities → navigates (no duplicate panel). Gate 4/4.

**V3-6 ✅ BUILT 2026-06-10 — Plan tab to the Part-3 skeleton + VIS-1 + VIS-3.**
(plan.jsx + store.jsx) THE TOKEN CARVE-OUT FIRST: new `cfg.plan` token — `config.planParams` and
the G-P2 end-cover pair are read by exactly two builders (StagePlan payload +
`_loopAggregatePayload`), both /api/solve/aggregate, so they earn a scoped token like
cfg.prod/cfg.profit. On the broad 'config' token a planParams edit falsely staled the whole
inventory family AND GovField chips would have claimed 9 consumers; planEndCover* previously sat
on cfg.prod, falsely staling production+linecap (neither reads it). CONFIG_TOKEN remapped,
SOLVE_DEPS.aggregate +cfg.plan. CONVERSION: PlanParamsCard's 11 SolverInputs + the max-OT
NumInput + the end-cover NumInput → 13 GovFields (token cfg.plan), each with why+formula
(max-OT's why states the UNITS.md trap: UI percent, solver consumes the FRACTION; holding-cost
seed stays the V2-4 derived ₹/u/mo; opening-FG seed stays the Network-reconciled labor-weighted
value). allow-backorder + end-cover toggles stay checkboxes (non-numeric); the step-0b hands-on %
table stays a table (a structured per-SKU editor like the changeover matrix, not a scalar field).
VIS-1 feasibility thermometer (① DECIDE strip, blueprint 3.4 #1): one bar pair per period,
demand ÷ deployable capacity (rate×heads +governed OT) FROM THE SOLVED PLAN ONLY — unsolved ⇒
honest prompt, never seed bars; over-100% periods annotate the lever the solve actually used
(PB build-ahead / BO backorder). VIS-3 level-vs-chase strip (Strategy card, 3.4 #3): crew-
capacity line vs demand line vs inventory area from res.periods — the Step-3 picture, read by
SHAPE. Probe 15/15 observed: 12 mounts ◇SEED (13th appears with the end-cover toggle), chips say
exactly "aggregate", VIS-1 pre-solve prompt → solved peak 126% @ P3 == recomputed from the cached
solve (covered by build-ahead), VIS-3 renders, rate 30→33 ripples + writes + stales aggregate but
NOT procurement (token precision observed), revert reads ◇SEED. Gate 4/4.

**V3-7 ✅ BUILT 2026-06-11 — Production tab to the Part-3 skeleton + VIS-4 + VIS-5.**
(production.jsx only — no token work needed: all 8 scheduler knobs already sat on cfg.prod, whose
SOLVE_DEPS consumers are exactly production · aggregate · linecap, so the chips are honest as-is.)
CONVERSION: ProdParams' 7 SolverInputs (labor rate, shutdown threshold, conditional holding cost,
campaign min-run, setup cost, G-P4 headcount + OT caps) + ProdCycle's cycle-time SolverInput →
8 GovFields (token cfg.prod), each with why+formula (shutdown's why states it is a POST-SOLVE
heuristic that never changes the MILP; holding's why states it is the only force stopping the
time-phased schedule front-loading). The time-phased checkbox + line Select stay non-GovField
(non-numeric, honest). ① DECIDE strip (3.2): "can the lines build the plan?" — busiest line's
time-utilization + total OT hrs + changeovers, FROM THE SOLVED SCHEDULE ONLY (unsolved ⇒ honest
prompt). VIS-4 bottleneck Gantt ribbon (3.4 #4, Schedule step 3): one ribbon per line from
res.gantt, SKU slices per week (width = share of the week's units), busiest line in red with its
idle weeks marked ("every idle minute is lost forever"); changeover slivers DERIVED (SKU set
changed) with the solver's own `changeovers` count printed per row as the authoritative figure;
honesty note: util is time-based (active wks ÷ horizon), machine-hour saturation is linecap's
job. VIS-5 elevate-the-constraint (3.4 #5, Profit-Mix step 3): live profit-mix dual ₹/hr × hours
freed × 52 → REAL /api/calc/npv solve at the governed blended hurdle (no local NPV math);
capex/hours/life are card-local what-ifs that write nothing. HONEST BRANCH built for the TPAC
truth (I-2/SF-7): lines slack ⇒ dual ₹0/hr ⇒ NPV = −capex ⇒ REJECT, and the card lists the
ACTUALLY-binding demand-ceiling duals ("win demand, not machines"). Probe 19/19 observed: 6
mounts ◇SEED (7th holding appears with time-phasing), chips name production+aggregate+linecap,
DECIDE strip + VIS-4 honest pre-solve → light from the real solve, strip busiest (Precision
Machining 53.8%) == recomputed from the cached solve, VIS-5 took the slack branch live and the
real NPV solve returned REJECT on the ₹0 dual, labor-rate 120→150 ripples + writes + stales
production NOT procurement, revert reads ◇SEED. Gate 4/4 (HARNESS-1 9/9 with 32 GovField mounts;
HARNESS-1b 9/9).

**V3-8 ✅ BUILT 2026-06-11 — Products tab to the Part-3 skeleton.**
(products.jsx + store.jsx) NEW `seedMaster(kind,id,field)` (store.jsx, beside `_seedPartCost`):
one-time lazy boot snapshot of product {yield,shelf,salvage,moq} + part {scrap,cost,lt} master
attributes, so GovField can tell ◇seed (untouched TPAC sample) from ⌨input (edited master)
without polluting M — V2-2's snapshot discipline extended to master data. CONVERSION: 7 GovField
literals = yield/shelf/salvage (token productCosts via editProductAttr; yield's why states the
UNITS.md percent→fraction trap + G-I1 measured-override; salvage's why states it is INERT while
shelf ≥ horizon) + setup/labour/MOQ (productCosts via useProductCosts/editProductAttr; labour
seeded 18% of typed std cost) + per-part scrap (.map, token bom via editPartAttr). HONESTLY left
as tables: the FG catalog inline editors (structured per-SKU grid like the changeover matrix) and
the BOM qty/cost/lead cells (structured per-part grid). productCosts honestly fans to 13 solvers
— the chips are long because the product master really does feed nearly everything; transport is
the one non-consumer and the probe uses it as the staleness negative. ① DECIDE strip (3.2):
"what do you make — and what does a unit really cost?" — FG count + blended CM at the DERIVED
effUnitCost + firm-MTO floor, all live from master (ƒderived chip, no solve, nothing faked).
Probe 12/12 observed: strip CM 35% == in-page recompute from effUnitCost, 6 mounts ◇SEED →
10 when the Advanced part-master group opens, yield UI 90% writes FRACTION 0.9, production
stales while transport does NOT (productCosts precision), scrap edit stales procurement via bom
with the same transport negative, revert reads ◇SEED. Gate 4/4 (HARNESS-1 9/9, 39 GovField
mounts; HARNESS-1b 9/9).

**V3-9 ✅ BUILT 2026-06-11 — Network tab to the Part-3 skeleton.**
(network.jsx) Network is a pure master-data tab: every numeric rides a structured per-row grid
(lane terms · node master · per-class storage caps · on-hand matrix · scheduled receipts), which
per the V3-6/V3-8 rule is the HONEST editor for row-shaped data — so this tab deliberately has
ZERO scalar GovFields, and the strip says why. ① DECIDE strip (3.2): "where does material flow —
and can the nodes hold it?" — node+lane counts, the TIGHTEST storage class across wh/dc nodes
(same nodeStorageUtil math as the util card; "no class caps set" when nothing is declared), and
total inbound units on open POs — all ƒderived live from the master, no solve, nothing faked.
Probe 6/6 observed: strip counts 8/8 == store recompute (probe had to replicate useNetwork's
seed-merge — the appStore network slice starts empty and lazily merges window.M), tightest store
0% DC-BLR == nodeStorageUtil recompute, a lane-rate edit through the REAL Lane-terms table writes
state (18→25) and stales transport but NOT production (network-token precision observed). Gate
4/4.

**V3-10 ✅ BUILT 2026-06-11 — Demand tab to the Part-3 skeleton + VIS-2.**
(demand.jsx) Demand was already the most-complete tab (real engine auto-run, leaderboard, V3-2
gate, governed promos/holidays) — what the skeleton was missing was the ① band and the Q17–18
packaging. ① DECIDE strip: "what will sell — and do you trust the number?" reads ONLY the live
/api/forecast result for the selected item: winner model + holdout MAPE, the forecastability
read of the item's REAL history (same fab as the banner), and the V3-2 review-gate verdict
(commit open / REVIEW GATED). VIS-2 structural-events card (3.4 #2, step 6b): "competitor
launched / market changed" is FOUR levers, not one, and the card is structured BY MODEL TERM per
the V3-4 discipline — NPI like-modeling (history ← analog×scale×ramp), consensus override
(committed[t] ←, event-logged), actuals breach (auto_trigger → markStale(demand)), scenario
branch (runScenario transparent re-solve); each row links to the LIVE tool (anchors added on
DemForecast/DemActuals; the branch button does a real onNav to Scenarios). Card computes and
writes nothing; the Reading honestly positions promos as the fifth, lighter lever already wired
into promo_periods. NPI Scale/Ramp SolverInputs honestly NOT converted to GovField — they are
one-shot transform parameters of the import ACTION, not standing solver inputs on a token.
Probe 8/8 observed: strip lights from the auto-run solve, strip MAPE 5.7% == winner-banner MAPE
(two independent renders of one live result), EASY badge + commit-open verdict, VIS-2's 4 rows
name their model terms, branch button REALLY navigates (es_stage → scenarios). Gate 4/4.

**V3-11 ✅ BUILT 2026-06-11 — Sourcing tab to the Part-3 skeleton + VIS-7.**
(sourcing.jsx) CONVERSION: Run-tab Solver Parameters → 5 GovFields on the broad `config` token
(deliberately broad — under-staling refused): service level α (why states ONE shared field with
Setup, % there / fraction here), RM-spend budget, and the G-I2 ABC class A/B/C targets (one
.map literal, seeds .98/.95/.90). MEIONet ρ + pooling-fixed-cost stay SolverInput HONESTLY:
card-local sandbox state, not token-riding config. ① DECIDE strip (3.2): "what do I buy — and
when?" — PO count + RM spend Σ'd from the SAME purchase_orders rows the release plan lists (no
second total to drift) + shortage verdict; honest pre-solve prompt. VIS-7 BOM explosion tree
(3.4 #7, Run step 3b): the FG's REAL bill (bomForSku) as a lead-time ladder — bar = part lead vs
the max lead, critical path flagged; SS/s columns fill from a REAL /api/solve/policy run
(⚙ button), honest "derive ⚙ for SS" before; the card states the TPAC bill is FLAT (no invented
sub-assembly level). CONTRACT TRAP REFOUND: policy.py keys rows by payload part NAME (bomParts
sends M.bom[].name — same contract scheduledReceiptsLocked translates for), so the SS lookup
indexes by b.name, not the code. Probe 14/14 observed: 5 mounts ◇SEED, chips name
procurement+policy, critical path 18d RM-BRG18 == bomForSku recompute, ⚙ fills SS from the live
engine, strip lights (2 POs · ₹1,64,444) == release-plan badge, α edit 0.95→0.98 ripples + stales
procurement, revert ◇SEED. Gate 4/4 (HARNESS-1 9/9, 42 GovField mounts; HARNESS-1b 9/9).

**V3-12 ✅ BUILT 2026-06-11 — Inventory science to the skeleton + VIS-8 √N pooling picture.**
(sourcing.jsx ▸ Design) "Inventory" is not a stage — the inventory science lives in Sourcing ▸
Design (carry rate · policy autopilot · rolling · MEIO · pooling · newsvendor), and V3-11's
DECIDE strip already covers the stage. What the skeleton was missing: CONVERSION of the ONE
token-riding inventory knob — CarryRateControl's holding spread (config.invHoldingSpread, seed
12.8%/yr, broad config token) → GovField; why states it composes carry h = WACC + spread that
every inventory solve prices holding at; '' clear is safe (finance.jsx _effNum → seed). SrcMEIO
maxSvc and MEIONet ρ/fixed stay card-local SolverInputs HONESTLY (sandbox state, not tokens).
VIS-8 √N pooling picture (3.4 #8, Step-7): inside SrcMEIONet's result branch (cannot exist
before a real solve) — per poolable part, TWO bars on one ₹ scale (N-buffers-decentralised grey
vs one-pooled green, widths from the solver's own ss_value_decentralised/ss_value_pooled rows,
nothing recomputed) + header ₹dec → ₹pooled + capital-freed Tag (total_capital_freed) + √N-law
caption. Probe 14/14 observed: spread mounts ◇SEED w/ broad chips, carry Tag 24% == WACC
11.15% + spread 12.8% golden recompute (tolerance = the display's 0.1 rounding), VIS-8 absent
pre-solve → lights from the REAL meio-network solve, capital freed ₹2,435 == solver total ==
dec ₹5,930 − pooled ₹3,495, pooled < decentralised on ALL 5 poolable parts (the I-6 invariant
now DRAWN), 5 bar-pairs == 5 poolable rows, spread edit 12.8→20 ripples + stales solved meionet
+ carry moves to 31.1%, revert ◇SEED. Gate 4/4 (HARNESS-1 9/9, 43 GovField mounts; HARNESS-1b
9/9 — I-6 prints the same ₹2,435 the card draws).

**V3-13 ✅ BUILT 2026-06-11 — Finance tab to the Part-3 skeleton.**
(finance.jsx) ① DECIDE strip "what does capital cost — and is the plan earning it?" between
StageHeader and SubTabNav — honestly ƒDERIVED (Provenance chip): blended hurdle %, carry rate
%/yr, EVA ₹L/yr + value-destroyer Tag, computed by the SAME hook-free helpers every card
charges (finBlendedHurdle · carryRateParts · finEva — one formula, two renders) and carrying
finEva's own capital-basis honesty ("solved inventory" vs "turns proxy"). CONVERSION (all on
broad config token, 14 new GovField literals / 21 runtime mounts): Capital — equity stack .map (amount+cost, seeds
FIN_EQUITY) + debt stack .map (amount+rate, seeds FIN_DEBT) + WDV rate (0.25, shown only in
WDV mode); Investments — per-line CapEx .map (seedCapex||1e7) + budget/yr (2.5Cr) + added
hrs/yr (2400) + line shadow ₹/hr (seed 0 = honest: slack lines earn nothing) + Buy-vs-Lease 5
terms (config.bvl.*, seeds 84L/5yr/6L/20L/25L). Cash & WC subtab stays seed-fenced ILLUSTRATIVE
(no ledger feed — F-9 honesty unchanged); FX table rows stay master-data grid. Probe 15/15
observed: strip golden ×3 (hurdle 11.15 / carry 24 / EVA +13.5L each == in-page recompute),
REAL /api/calc/hurdle 11.146% == strip's derived blend (the F-1 solved≡derived identity), 10
mounts ◇SEED on Capital + 11 on Investments, PE-round cost edit 18→25 ripples + writes config
+ moves the derived hurdle 11.15→11.61 live + stales procurement (broad token), revert ◇SEED,
0 page errors throughout. Gate 4/4 (HARNESS-1 9/9, 57 GovField mounts; HARNESS-1b 9/9).

**V3-14 ✅ BUILT 2026-06-11 — Scenarios tab to the Part-3 skeleton + VIS-9.**
① ScenariosDecideStrip (scenarios.jsx, data-vis="scenarios-decide") between StageHeader and
SubTabNav — SOLVE-GATED (Sourcing pattern): "does the committed plan survive its shocks?" read
verbatim from the CACHED montecarlo solve (policy tag committed-plan/base-stock-proxy · mean
fill vs α · CVaR95 ₹L · fragility ×, zero recompute) + a → STALE tag riding solves.montecarlo;
pre-solve it honestly prompts. ② INPUTS honestly unchanged: ρ/runs/lead-time/β stay card-local
SolverInputs — montecarlo's SOLVE_DEPS (demand·procurement·production·sourcing·productCosts·bom)
has NO config token to ride (V3-12 precedent). VIS-9 (Vis9FillDist, data-vis="vis9") inside the
MC result branch: the solver's OWN fill_histogram as bars, worst-5% tail shaded red, dashed α
gate, red CVaR₅ line, ▼ mean-fill marker green when policy_simulated='plan' / amber base-stock.
Backend additive: montecarlo.py now returns fill_p5 + fill_cvar5 (left-tail VaR/CVaR of fill —
service risk is a LEFT tail; cost risk was already the right tail). Probe /tmp/v3_14_probe.js
17/17 observed: pre-solve strip prompts + VIS-9 absent; REAL solve → strip == solver verbatim
(92% / ₹74.06L / 1.06×), 11 rects == 10 bins + tail shade, cvar5 86.7 ≤ p5 87.9 ≤ avg 92;
markStale('demand') flips → STALE; full Loop run flips strip + VIS-9 marker to ▼ committed plan
(both branches OBSERVED). Gate 4/4 (HARNESS-1b 9/9 incl. policy='plan' #5).

**V3-15 ✅ BUILT 2026-06-11 — Guided/Expert toggle (3.3).** ONE persisted chrome toggle
(UiModeSwitch in the masthead, localStorage es_ui_mode; default resolves ONCE at first read:
fresh visitor → GUIDED, preset/onboarded session → EXPERT, so every probe/harness sees today's
UI). Guided = (a) per-tab "do these 3 things" checklist strip (M.guidedChecklist seed copy,
GuidedChecklist in chrome.jsx, session-dismissable); (b) the fold LAW in GovField itself: a
field folds to a click-to-reveal pill when its used-by misses the tab's primary solve
(GUIDED_PRIMARY map in SOLVE_DEPS vocabulary, lib.jsx) or when its face is derived/solved;
NO-CONSUMER warnings stay loud in both modes. HONEST FINDING: the law folds ZERO fields today —
every mounted token's consumers include its tab's primary (broad-config coupling is REAL:
equity→WACC→carry→procurement), so Guided's visible delta is the checklist+toggle; the law
engages as tokens get scoped (cfg.plan/cfg.prod precedent). Expert "denser grid / keyboard-
first" NOT built (recorded, not claimed). Probe /tmp/v3_15_probe.js 15/15 observed: expert
default for preset sessions + UI byte-identical (10 Finance mounts, 0 pills); guided checklist
+ fold-law count == in-page truthful recompute (0==0); both fold branches OBSERVED by rendering
the REAL GovField in the live runtime (ƒ derived + ◇ off-primary pills, click reveals); mode
persists across reload; fresh visitor defaults GUIDED. Gate 4/4.

**V3-16 ✅ BUILT 2026-06-11 — VIS-10 global cascade ripple (3.4 #10). V3 QUEUE COMPLETE.**
markStale (store.jsx) now records its walk ORDER (only newly-staled solves) and broadcasts
`es-cascade {root, order}` after the store write — the model's real staleness wave, not an
animation script. PipelineRibbon (chrome.jsx) listens and pulses the affected solver chips in
that sequence (180ms apart, 650ms decay, amber inset + dot scale; `data-cascade-pulse=key`);
new wave cancels pending timers. Probe /tmp/v3_16_probe.js 9/9 OBSERVED: one event per edit,
event order == independent in-page SOLVE_DEPS walk (procurement→montecarlo→policy→…→capital);
the ribbon wave WATCHED live at 40ms sampling — procurement→montecarlo→aggregate, exactly the
walk ∩ ribbon keys; non-affected chips never pulse; wave decays; an already-stale edit fires
NO event (only newly-staled ride). Gate 4/4.

**V3 PART-9 QUEUE: ALL DONE (V3-0..V3-16; VIS-1..10 built).**
*Assert held throughout: per-tab — gate green + an observed probe; global — lints in gate.*

**V2-ERA OPEN ENDS ✅ CLOSED 2026-06-11 (all three, observed, gate 4/4):**
· **rehire_notice_hrs governed** — config.prodRehireNoticeHrs GovField (Production ▸ Schedule,
  token cfg.prod, ◇seed 80 = 2wk×40); CONFIG_TOKEN routed; productionOptsFromConfig carries it;
  PAYLOAD_LITERALS row pruned (lint clean), UNITS.md updated. **BONUS BUG FIXED:** the production
  tab's useSolve hand-rolled its opts and silently DROPPED the G-P4 labor caps (and would have
  dropped rehire) — tab + loop now share ONE productionOptsFromConfig. Probe: payload 80→120 with
  the edit + production stales + revert ◇SEED.
· **Tier-1 #2 pure-MTO verify-closed** — G-D1 floor observed END-TO-END through the REAL
  /api/solve/production: TPA-3215's firm 1,200u floors its due-date bucket (dem 1200 ≫ seed 317),
  required_qty 2,148 with the order vs 1,027 without (counterfactual Δ1,121), gantt 2,397 covers
  required with 0 shortage. /tmp/open_ends_probe.js 11/11.
· **Q7b landed/signal-margin sensitivity** — Q7bMarginSensitivity (Production ▸ Profit-Mix step 4):
  margins re-priced on three bases with the solvers' OWN helpers (effUnitCost · landed via
  effLandedCost(getSourcing) · signal via commodityFactor); 🧪 Compare runs the REAL profitmix LP
  ×2 (current vs chosen basis) and shows the mix delta — advisory by construction (no markSolved,
  cache asserted byte-identical). Observed: landed drops EXACTLY for the 4 RM-BRG18 carriers
  (−27/−16/−14/−11 ₹/u), signal neutral at seed and moves at +20% index, profit ₹56.11L→₹54.89L
  with mix unmoved (robust). /tmp/q7b_probe.js 10/10. The LP's committed basis stays effUnitCost
  — exactly the Q7 design ("don't silently optimise on speculative costs").

**V4 — DEPTH (planner-grade upgrades, each optional-on):**
V4-1 profit-aware aggregate objective toggle · V4-2 multi-resource aggregate (machine-hrs per line
class) · V4-3 OT per-shift mode · V4-4 price/exog forecast columns · V4-5 ATP/CTP order-promise ·
V4-6 rework cost adder + yield doc · V4-7 correlated MC.

**PHASE-III ✅ 2026-06-12 — full-site design audit → `docs/design-audit/README.md` + `assets/` (~95 screenshots).**
Method: live site, headless Chromium 1440×900, every stage captured fresh-boot + guided + solved (one real
▶ Re-plan spine run), scroll-tiled (the app scrolls an inner container — `fullPage` captures only the first
viewport; tiler finds the max-scrollHeight element and steps 820px). Two personas (first-day + experienced
senior design lead), every issue tagged understanding/trust/conversion + specific fix. **5 safe-small fixes
applied on the spot, all probe-verified live then re-shot:** DA-1 plan.jsx:170 "VIEWING ▸ PORTFOLIO
AGGREGATE" chip was black-on-black in MONO (`C.onAc`==`C.ink`==#0a0a0a) → `C.paper` · DA-2 console.jsx ×5
Interpret cards (procurement/policy/production/MC/capital) showed hard-coded seed tables pre-solve with no
marking → `Provenance kind="seed"` chips · DA-3 home.jsx ×5 "run loop" → "re-plan to fill" (one name per
action) · DA-4 guidedChecklist.home reordered (re-plan first — fresh user has no exceptions) · DA-5 ribbon
linecap chip relabelled LINE CAPITAL (was a second "PLAN" chip). **Top systemic finding (recommendation,
NOT spot-fixed):** the loop's own LP-A demand-commit stales all 8 non-spine engines, so the success state
shows "8 SOLVES STALE — RE-PLAN TO REFRESH" — but re-plan can't refresh non-spine engines; fix = split
spine-stale vs advisory-stale in freshness derivation + collapse the 8 mechanical exception rows to one.
Other H findings: Sourcing PO-release/shortage/freight cards stay "ILLUSTRATIVE — run procurement" even
after the loop solved procurement (cache never hydrates the tab cards); service-level renders 0.95
(Sourcing/Scenarios) vs 95% (Setup) for the SAME token. Screenshot-byte gotcha: Read renders PNGs >~150 KB
as thumbnails — quantize viewing copies to 128 colors. Gate 4/4 after fixes (128 pytest · lints · 7/7 ·
9/9). Audit explicitly protects the style + honesty furniture ("what NOT to change").

**PHASE-II-R ✅ REBUILT 2026-06-12 — `app_v2/mastery_guide.html` (user rejected the first guide's design; full rewrite).**
User verdict on solver_expert_guide.html: poorly designed, "based off V1–V5" framing wrong — wanted the WHOLE app
in exact user-flow order with visuals/interactivity, per-section mastery + built/missing/wrong + step-by-step
worked problems with all inputs. Delivered as `mastery_guide.html` (~162 KB, self-contained, light "engineering
paper" style — deliberately opposite of the dark first guide and matched to the app's 2px-ink aesthetic):
clickable 12-stage flow map mirroring M.stages (DEFINE/PLAN/DECIDE/LEARN) · Foundations section (LP geometry
with a live SVG widget, duality rules, B&B, exact-vs-heuristic, 4-step solve-reading discipline) · one section
per stage (01 Setup … 12 Reference) each with SIX TABS: CONCEPT (mastery track) / FLOW & INPUTS (every field,
units) / SOLVER (obj·vars·constraints as written, + FULL PAYLOAD CONTRACT details block — every key the engine
reads, verified by grep: aggregate, production, procurement 50+, transport, capital, cvar, montecarlo, profitmix,
meio, linecap) / OUTPUTS (named VIS-1..10 + data-vis ids) / VERDICT (built✓/missing✗/wrong⚠ with audit grades) /
WALKTHROUGH (numbered TPAC-seed steps) · 7 interactive widgets (LP vertex-snap SVG · forecast-family regimes
incl. <18-refusal · level-vs-chase pricing · shadow-price bind/slack flip · WW-vs-POQ with irregular-spike
demand — periodic mask gifted POQ a fake tie, fixed · bridge-split with the observed 12-day/1,380 kg case ·
critical fractile) · 7 hand-checkable DONE PROBLEMs (2-month aggregate hybrid ₹303,500 beats chase/level ·
1-week CLSP 264 starts/₹792 rework/1-minute-over infeasibility · 3-period WW DP ₹1,000 · deadline split
₹64,000→₹32,167 · capital NPV −₹9.8 L with ₹752/hr break-even dual · 5-scenario CVaR=₹400=LP obj · 3-point
holdout MAPE championing) · Honest Ledger (explanation-coverage audit table A…C, problem-class coverage,
benchmark stack CBC/HiGHS/CP-SAT/Gurobi/Hexaly + where-CBC-falls-short-for-us + marketing decoder, 5 ranked
structural debts). VERIFIED OBSERVED: HTML parser balanced/0 dangling anchors; Chromium probe 12/12 (boot
structure, all 7 widgets exercised through regime flips, tab-strip pane switching, flow-map scroll, contracts/
done-problems/benchmarks render, details expand, 0 pageerrors); screenshots eyeballed (hero, demand, plan-solver
pane — first blank shot was a smooth-scroll race, re-shot with scrollBehavior:auto). Gate 4/4 after. Server
restarted (codespace wipe) → PID in /tmp/appserver.pid. solver_expert_guide.html kept on disk, superseded.

**PHASE-II ✅ BUILT 2026-06-12 — `app_v2/solver_expert_guide.html` (goal phase ii, user-expanded). [SUPERSEDED by PHASE-II-R above]**
One standalone HTML (~84 KB, no deps, served live at /solver_expert_guide.html) delivering all 8
user-specified items: §1 expert-track solver concepts (variables/objective/constraints with
profitmix as the textbook; LP geometry → VIS-6; duality/shadow prices incl. the MIP-duals-are-
invalid gotcha that capital.py:69–133 handles via LP relaxation; B&B/gap; 4 linearization moves
incl. meio.py's exact one-hot √τ and production.py's mean-changeover + sequencing.py repair;
MC/newsvendor/CVaR with the real Rockafellar–Uryasev LP from cvar.py; exact-vs-heuristic table;
forecast tournament + MAPE>30 gate; reading status/infeasibility/binding sets) · §2 Gurobi-style
problem-class taxonomy — 20 named classes mapped to engines with honest COVERED/PARTIAL/NOT BUILT
(production.py is CLSP not job-shop; JSSP/VRP/facility-location/recourse-SP flagged NOT BUILT) ·
§3 honest benchmark CBC vs HiGHS vs Gurobi vs Hexaly vs CP-SAT + upgrade ladder (HiGHS free swap →
CP-SAT for scheduling lane → Gurobi only on evidence; "optimality" marketing decoded) · §4
differentiation (provenance, finance spine, closed loop, verified honesty, branching, India-native)
+ 8 adoption gaps ranked (persistence/auth/data-onboarding = fatal; backtest > demo) · §5 unhinged
free-view (explanation engine is the moat; ship the backtest; disruption lane = killer demo;
LLM-drives-payloads; 5-point self-critique incl. localStorage debt + weekly-bucket limits) · §6
reasoning-surfaced audit — verdict NO, ~⅓ meets the bar; per-engine grades (transport/aggregate/
forecast A-tier; production/procurement C — reasons computed then DISCARDED at the response
boundary); fix = uniform decisions[] {what, because, binding_constraints, marginal_value,
alternatives_rejected} · §7 SIX end-to-end TPAC walkthroughs (Diwali spike → SPLIT FAST+SLOW
₹64k→₹32,167; supplier cap cut → V5-3 backup; 70t unserveable → ₹93k rail bin-pack; cash crunch →
WACC→carry_rate ripple; cannibalizing launch; port congestion +10d) all runnable today, observed
numbers ◇-flagged · §8 disruption/reshuffle DESIGN (explicitly NOT BUILT): typed event log where
every event compiles to a constraint delta the solvers already accept (no-show→line-shift hours via
V4-3 routing; crane→maint_scale which EXISTS; late material→receipt shift), 3 entry doors, pinned-
past + recovery-family branch fan-out (V5-2 repurposed) ranked by profit objective, closure
attribution (disruption vs plan error), honest grain note: MILP for plan-of-record + CP-SAT for
minute-level reflexes · §9 20-term glossary. VERIFIED: HTML parser balanced/0 errors; headless
Chromium OBSERVED — 0 pageerrors, 10 sections, 10 tables, SVG renders, #s6 anchor jump scrollY
1001, screenshots eyeballed. Gate 4/4 after (128 pytest · lints 29/40/clean · model_check 9/9 ·
golden path 9/9, I-5 0.91). Companion/successor to supply_chain_12_steps (1).html.

**V5-4 ✅ BUILT 2026-06-12 — multi-mode logistics (mode SPLIT on capacity/deadline binds).**
transport.py's per-shipment pick was all-or-nothing: one mode carries the whole lane. Two binds
made that wrong: (a) CAPACITY — a shipment heavier than every mode's max_kg returned rec=None and
silently contributed ₹0 (an unserveable lane reported as FREE); (b) DEADLINE — a demand spike
forced the ENTIRE shipment to air when only the consumption bridge needs to fly. Now
`params.mode_split` (default OFF ⇒ byte-identical baseline) allows split plans: `_capacity_split`
bin-packs n full loads of a bulk mode + a remainder leg (cheapest combination, every leg priced
with the SAME chargeable-weight + reliability formula as the single-mode ranking);
`_deadline_split` flies only `bridge_kg = (slow_days − DoS) × burn × (1+buffer%)` on the fast lane
(governed `config.splitBridgeBufferPct`, seed 15%) and sails the rest, carrying any residual
stockout exposure at the SAME risk factor as the ranking — chosen only when it beats both full-air
and full-slow+risk; the spike alert decision then reads `SPLIT FAST+SLOW`. Split legs are
family-sane (`_split_families`: lanes in TRANSIT_DB split across the families that physically
serve them + air; unknown lanes import⇒sea/air, domestic⇒road/rail/air — the single-mode ranking
keeps its pre-existing deadline-only filter, baseline picks untouched). Output per shipment:
`split {reason, legs[] (per-mode, loads collapsed), total_cost, single_cost, saving, bridge_kg,
residual_stockout_cost, recommended}`; top-level `mode_split_active / n_splits / split_saving`;
mode_summary counts split legs per mode. UI: Logistics §1b `LgModeSplit` card (arm/disarm toggle →
`config.modeSplitEnabled` → payload `mode_split`, bridge-buffer GovField, `data-vis="v5-modesplit"`
strip: per-lane bind reason + legs + saving, UNSERVEABLE-rescue marker, honest "no binds" line).
GOTCHA found: the pre-existing is_import inference (`origin ∉ [Domestic,Factory,Warehouse]`)
classifies Delhi→Mumbai — and every tab node-id lane — as an IMPORT; the TRANSIT_DB family lookup
absorbs this for known lanes. PROBE-OBSERVED (/tmp/v5_4_probe.js 8/8): toggle-off byte-identical;
armed seed flows honestly report "no binds" (lanes 529 kg); SLA 30 + ×56.7 planner-pinned surge →
5 lanes split FCL-40 26,700 kg + LCL 3,309 kg, ₹3.31L→₹1.30L (−₹2.01L vs single-mode rail); spike
case USE AIR→SPLIT FAST+SLOW, 1,380 kg bridge, ₹64,000→₹32,167; disarm cleans payload, 0
pageerrors. pytest tests/test_v5_multimode_transport.py 4/4 (suite 128). Gate 4/4 (I-5 0.91).
V5 COMPLETE (V5-1 netting · V5-2 server branching · V5-2b pins · V5-3 supplier caps · V5-4 split).

**V5-3 ✅ BUILT 2026-06-12 — supplier-capacity allocation (finite suppliers + backup overflow).**
Suppliers were modeled as infinite: nothing bounded how much a supplier could fulfil per period,
and the SrcMRP "backup supplier" was UI decoration. Now: `params.supplier_capacity = {code: ₹
landed spend/period}` (₹ is the deliberate common unit — a basket mixes kg/pcs/L; spend is what a
supplier's throughput honestly bounds). procurement.py adds `SupCap_{sup}_{t}`: Σ primary spend +
backup INFLOW ≤ cap × period_factor(t) (holiday-aware; VMI exempt). Parts may carry `backup:
{supplier, premium_pct, lead_time}` — a relief lane the MILP buys through ONLY when the primary
binds: it keeps the part's OWN MOQ + ordering admin (probe-caught: a no-MOQ spot lane became an
MOQ-EVASION loophole — CBC bought 4,545-unit bolt "spot lots" at +12% to dodge the 10,000 MOQ,
"saving" 3.7%; with lot discipline the premium is the only differentiator and seeds-vs-free match
to ₹69). Output: `supplier_allocation` (spend/period, peak util, binding@≥95% — integer lots
rarely land on the cap to the rupee — overflow/inflow ₹) + per-material `backup_orders/
backup_supplier/backup_spend` + cost_breakdown.backup_purchase. Client: M.suppliers gain
◇capPerPeriod (sized from the OBSERVED baseline loop plan: SUP-012 peak ₹168k/p · SUP-031 ₹204k/p
· ≥1 MOQ lot of every part — a cap below one lot bricks the lane); M.backupSuppliers promoted
from the SrcMRP hardcode (which mapped CN-LUB02 and CN-BLT04 to their OWN primaries — re-pointed,
plus a self-backup guard); `supplierCapacityParams()` threads caps into BOTH the tab payload and
_loopProcurementPayload only while config.supCapEnabled (OFF default ⇒ byte-identical legacy);
Sourcing ▸ Design ▸ "Finite supplier capacity" card (arm toggle · 6 cap GovFields · premium
GovField · v5-supcap allocation strip with BINDING markers + backup-buys line). HONEST EDGE
(probe-pinned): a cap physically too slow for demand timing (SUP-031 ₹140k = 2 lube lots/period
vs 3 needed early, POSCO relief lead 6wk can't bridge t≤1) returns Infeasible — diagnosable, not
fabricated. pytest +4 (124: baseline byte-identical · binding cap allocates with 0 shortage ·
overflow→backup restores feasibility where capped-primary-alone is Infeasible · premium lane
untouched at slack). Probe /tmp/v5_3_probe.js 7/7 OBSERVED. Gate 4/4 (124 pytest · 3 lints ·
model_check 9/9 · golden path 9/9, I-5 0.91). KNOWN LIMIT: the loop payload duplicates the shared
parts list per product (6 copies), so each copy carries its own MOQ/init — caps act on the summed
copies; per-part dedup is the documented one-BOM limitation, not a V5-3 regression.

**V5-2b ✅ BUILT 2026-06-12 — demand PINS: planner-authored demand survives re-forecasts.**
The V5-2 parity note was a real UX trap, wider than branches: the loop's phase-1 re-forecast
(LP-A `setItemDemand(winner)`) silently overwrote EVERY planner-authored committed-demand number
before downstream payloads read it — branch demand levers (What-If bot demand%, SF-1/SF-5
sub-flows), EVA prune branches (zeroed destroyers were RESURRECTED mid-run, so the prune branch
never actually pruned), CSV model-surface imports with re-solve, and even tab overrides (the
on-mount auto-forecast clobbered an override on the next visit). Fix: `setItemDemand(sku, series,
source)` — `'planner'` (override / sensing replan / lifecycle / NPI prior / CSV import) PINS the
SKU in a new `demandPinned` slice; `'loop'` (LP-A after, server fan-out patch, on-mount
auto-forecast) is SKIPPED while pinned; `'model'` / accepting the forecast (forecast_commit)
UNPINS. Pins travel with scenario envelopes (`_SCN_INPUT_KEYS` += demandPinned) so a pinned
branch lever survives both runScenario and the V5-2 server fan-out; scenarioPruneSkus +
What-If demand% + SF-1/SF-5 now pin their edits. UI: 📌 badge + "unpin → model" button on the
Override card (data-vis="demand-pin"). GOTCHA found: `appStore.set()` shallow-merges per slice,
which RESURRECTS a deleted pin key — pin writes use `appStore.replace()` (full-copy slices).
KNOWN EDGE (pre-existing, now exposed): a pinned daily-grain override series survives into the
weekly/monthly loop where supplier contract minimums can make procurement honestly Infeasible
(isolated per step; loop continues 5/6) — the old clobber semantics merely HID the grain mix.
Probe /tmp/v5_2b_probe.js 7/7 OBSERVED: real UI override → pin+badge · full loop respects pin
while unpinned SKU is refreshed · unpin via badge works · +30% pinned-demand branch moves
planCost ₹44.07L→₹51L through the server fan-out (was byte-equal = the trap) · prune branch
drops units 2,415→1,077 + cost strictly (was ≡ base) · live byte-identical · no pageerrors.
Gate 4/4 (120 pytest · 3 lints · model_check 9/9 · golden path 9/9, I-5 0.91).

**V5-2 ✅ BUILT 2026-06-11 — server-side concurrent branching (/api/solve/branches fan-out).**
The scenario engine scored branches strictly SEQUENTIALLY (each branch = 6 chained HTTP solves
around an apply/restore of the live store). Now: app.py `/api/solve/branches` takes a BATCH of
independent jobs `{id, solver∈{forecast,procurement,aggregate,production,linecap,montecarlo},
payload}` and fans them out on a ThreadPoolExecutor (max_workers 1..8, default 4; ≤48 jobs/batch;
CBC solves are SUBPROCESSES ⇒ real parallelism, no GIL contention) — registry maps to the SAME
callables the dedicated routes call (montecarlo keeps its n_runs handling); per-job failure is
ISOLATED (ok:false + error on that entry, batch still 200); meta echoes honest
{wall_ms, solver_ms_sum, speedup}. Store: `runScenariosServer(ids, opts)` batches by the loop's
TRUE dependency phases — 1: forecast (N jobs) → per-branch demand PATCH from the winner (the same
write LOOP_STEPS.after does, branch-scoped) → 2: procurement∥aggregate∥production (3N jobs) →
3: linecap∥montecarlo (2N jobs, consuming each branch's phase-2 results; absent upstream falls to
the sequential loop's own fallbacks). Payloads stay CLIENT-built with each branch's envelope
applied (the same builders the tabs use — one truth; `withEnv` byte-restores live around every
build window; setItemDemand/cacheSolve only touch slices inside the restore envelope, so zero
event/staleness leakage); KPI capture mirrors runScenario exactly (apply → cacheSolve →
_captureKpis → restore); writes back kpis+ranAt+runScenario-compatible loopLog per branch.
Scenarios tab: "⚡ Run all (server)" button + `data-vis="v5-branches"` telemetry strip (branches ×
steps, wall vs Σ solver-time, ×concurrency, per-phase jobs, failed-step count isolated). PARITY
NOTE (probe-learned): a raw committed-demand edit is NOT a surviving branch lever — phase-1
re-forecast overwrites committed demand before downstream payloads read it, IDENTICAL to
sequential runScenario; sourcing/config levers (the What-If bot's) survive. Tests
tests/test_v5_branch_fanout.py (4): batched result == dedicated solver's (same objective);
concurrency observed (wall < Σ/1.4, locally ~2.8×); failure isolation (bad payload + unknown
solver beside a good job); envelope validation (empty/oversize → 400). Probe /tmp/v5_2_probe.js
7/7 OBSERVED: button · both branches 6/6 steps scored · live store byte-identical after fan-out ·
duty +25% branch lands proc ₹37.1L vs ₹34.5L base · wall 131s vs Σ263s (2.0× on the live TPAC
model) · UI strip + scored columns · no pageerrors. Gate 4/4 (120 pytest · 3 lints · model_check ·
golden_path I-5 0.91).

**V5-1 ✅ BUILT 2026-06-11 — multi-site on-hand/netting (G-N2/G-I3 transaction layer).** The
network.onHand ledger is now CONSUMED, not decorative. Store: `onHandFor(item, locTypes)` ONE
resolver (rows carry node type); `fgScheduleOnHand(sku)` scopes FG netting by config.netFgScope —
'plant_wh' default (DRP discipline: DC stock is positioned downstream serving its region; netting
it against the plant build without a per-location demand split would double-count), 'all', 'off'.
productionPayload: required_qty netted + opening_inventory sent (time-phased InvBal serves the
EARLIEST weeks from stock); solve_ctp ATP balance now OPENS at opening_inventory (was
under-promising by exactly the warehouse stock). bomParts: parts WITH a ledger row send
init_inventory (plant+WH Σ); parts with NO row omit the key — NOT TRACKED ≠ zero (hard 0 starves
t=0 consumption → honest Infeasible; found by the gate's golden chain, fixed to conditional send).
procurement.py BUG FIXED: the rebuilt all_parts dict DROPPED init_inventory, so any payload value
was silently ignored and the avg×(lt+1) fabricated default ALWAYS won — key now carried, explicit
ledger (0 included) always wins, absent = legacy fallback (pytest-pinned both branches).
SOLVE_DEPS: production+aggregate += 'network' (ledger edits now stale them — aggregate read the
ledger via planOpeningInv but never staled, pre-existing gap closed); CONFIG_TOKEN netFgScope →
cfg.prod. UI: Network ▸ On-Hand netting-policy strip (data-vis="v5-net": where each row nets +
3-way scope toggle); Production ▸ Schedule per-SKU netting strip (data-vis="v5-fgnet").
UNITS.md row (item's own unit; absent ⇒ fabricated). G-N2 lateral transshipment / where-to-stock
deliberately STILL out (next frontier — needs per-location demand split). pytest +5 (116:
opening serves earliest weeks ≤token-run; gross−netted == ledger exactly; ATP opens at ledger;
+60 plant stock cuts buy by 60; absent key keeps fabricated 120). Probe /tmp/v5_1_probe.js 8/8
OBSERVED (policy strip; WH-340-not-DC-120 netting; RM-STL42 4200 in parts payload; scope→all
nets 460 + stales cfg.prod; ledger edit 340→500 stales via network token; live contrast gross
665u → netted 150u; schedule strip). Gate 4/4.

**V4-7 ✅ BUILT 2026-06-11 — cross-SKU correlated Monte-Carlo (systemic-risk tails) = V4 COMPLETE.**
montecarlo.py: optional params.demand_corr_matrix (n×n over products order) switches per-run demand
z-scores to Z = chol(R)·ε — each SKU's MARGINAL stays N(0,1) (per-SKU stats untouched), only the
JOINT moves, so portfolio bad weeks stop √N-diversifying away; non-PSD heuristic matrices are
eigen-clipped to the nearest valid correlation matrix (psd_clipped echoed), never a crash; absent
matrix ⇒ the legacy independent draw sequence byte-identical (pytest fixtures untouched). T8-10
demand↔cost ρ coupling unchanged on top. Result echoes demand_correlation {active, n_skus,
mean_offdiag_rho, max, psd_clipped}. Store: ONE shared `xyzCorrMatrix(skus,ρ)` (same class ρ, one
apart ρ/2, two apart 0 — the MN-C co-movement heuristic) now used by BOTH meioNetworkPayload
(sourcing.jsx corrMatrix delegated, dup deleted) and montecarloPayload (opts.demandRho default 0.5
→ 6×6 matrix in params; 0 ⇒ key omitted ⇒ legacy). Scenarios ▸ Risk & Stress: "Cross-SKU ρ"
SolverInput (seed 0.5) + systemic strip (data-vis="v4-mccorr") with honest BOTH branches (active:
n SKUs/mean ρ̄/PSD-repair note; off: "independent draws √N-diversify — raise ρ to price the
systemic tail"). pytest +4 (111 total: absent-matrix determinism+inactive echo; ρ=0.9 widens
std ≥1.25× and CVaR−mean ≥1.2× while mean Δ<8%; non-PSD chain eigen-clipped not crashed; echo
structure). Probe /tmp/v4_7_probe.js 7/7 OBSERVED (seed input; default payload 6×6 == shared
heuristic on XYXYZZ classes {0,.25,.5}; UI run → ACTIVE strip mean ρ̄ 0.233; live contrast std
₹2.36L→₹2.81L (1.19×), CVaR−mean ₹5.02L→₹5.94L, mean Δ 0.1%; override ρ→0 flips branch; no
pageerrors). Gate 4/4.

**V4-6 ✅ BUILT 2026-06-11 — rework cost adder + yield method doc (Q24).** production.py: x[k,l,t]
counts units STARTED, so the failure stream x·(1−fy) was built but never priced — now each product
takes optional `rework_cost_per_unit` (₹ per FAILED unit) charged in the objective as rw×(1−fy) per
unit started (linear; fy mirrors the Demand constraint exactly — routing-cascaded when a routing
exists, else yield_pct — so the priced stream and the quantity gross-up agree). Default 0 ⇒
objective byte-identical. Result: total `rework_cost` + per-product `rework_units`/`rework_cost`.
Store: productionPayload sends `rework_cost_per_unit: Number(p.rework)||0`; seedMaster carries
`rework`; TPAC seeds added to all 6 FGs (≈30% of make-cost/fail: 350/180/270/450/340/620 — the ONE
sample problem demonstrates the lever). Products ▸ Yield & expiry: 4th GovField "Rework ₹/failed
unit" (token productCosts, ◇seed + overridable) AND the Q24 yield METHOD doc block (data-vis=
"v4-yielddoc"): two knobs with data behind them (BOM scrap %, FG yield = COMPOUNDED op yield,
measured-replaces-typed via G-I1) + rework as a cost adder; per-stage routing yield deliberately
NOT built until stages have measured data. Production ▸ Schedule: REWORK strip (data-vis=
"v4-rework") under Capacity Loading shows total + per-SKU units→₹ when priced. UNITS.md Money row
(₹/FAIL, fold happens in python). pytest +3 (default byte-identical; 0.8-yield 100 started→20 fail
→₹1,000 lands in objective; routing-cascaded fy drives the adder, not the ignored yield_pct).
Probe /tmp/v4_6_probe.js 8/8 OBSERVED (seed field ◇350; doc block; payload all-6 seeded; live
solve ₹50,115 rework of ₹56,335 total with per-SKU units×₹ consistency; tab-solve strip; override
350→0 marks production STALE staleSrc=productCosts; re-solve drops total to ₹37,801; no pageerrors
— probe gotcha: addInitScript re-runs on reload and resets es_stage, so stage-2 needed a fresh
context). Gate 4/4 (107 pytest).

**V4-5 ✅ BUILT 2026-06-11 — ATP/CTP order promise ("can I promise this date?").** production.py
`solve_ctp(payload+quote{product,qty,due_period,search_weeks})` + app.py /api/solve/ctp: the
standard CTP ladder against the REAL MILP — (1) ATP first: LOOK-AHEAD available balance
(min over τ≥due of cum production·yield − cum demand — naive cumulative would promise away the
PRE-BUILD later weeks consume; probe caught exactly that and forced the fix) ⇒ free promise;
(2) else test-fit: add qty to required_qty + demand_by_period[w], re-solve at due, due+1, … —
first Optimal = EARLIEST promise, diff vs baseline = WHAT IT DISPLACES (₹ cost-to-promise
clamped ≥0 against CBC MIP-gap noise, OT hours bought, moved (sku,week) cells); (3) honest
NoPromise with the tried[] ladder. Advisory by construction — input payload never mutated
(pytest-pinned). Frontend: CtpQuote strip in the ATP card (Production ▸ Schedule, data-vis=
"v4-ctp"): SKU/qty/due-week pickers + ⚡ Test-fit → live endpoint with productionPayload(
…timePhased:true) ONE-opts-truth; verdict strip (ATP free / CTP ✓ / SLIPS → / NO PROMISE) +
priced displacement row; commits nothing (cache asserted byte-identical). pytest +6 (OT bought
to promise ≈₹1,200@8h; slip ladder Infeasible→Optimal W2; honest NoPromise; ATP covers
without re-solve; look-ahead reservation — 30u on the 16u prebuild buys ~6 OT hrs, never
skims; payload immutability). Probe /tmp/v4_5_probe.js 9/9 OBSERVED (UI click → live verdict
~60s on the full 13-wk payload — honest latency; advisory cache check; squeezed-payload slip
W1→W3 ladder ["Infeasible","Infeasible","Optimal"]; priced ₹2,792 + 7.7h OT + 10 displaced
cells; NoPromise; ATP-first 17u free). Gate 4/4 (104 pytest).

**V4-4 ✅ BUILT 2026-06-11 — price/exog forecast columns (unlocks Q16).** forecast.py:
products[].exog = {name:[values aligned with history]} — each numeric column rides into the
ML/hybrid feature matrix (_build_features/_future_features grew an ordered `exog` tail) for
RF/GB/XGB/MLP/hybrid; classical models never see it (inherent — the leaderboard routes).
Holdout backtests feed the ACTUAL historical exog over the test window (it IS history — honest,
no target peeking); future values from products[].exog_future[name] (a planned price change)
else last-known carry-forward; the promo-uplift counterfactual replays the same exog; result
surfaces `exog_features` (None when none). Frontend: parseHistoryCsv named-header mode — a
≥3-column pure-text header with a recognizable qty column (date,qty,price[,footfall…]) captures
every other named column as rows[].exog (legacy ≤2-col/headerless reads byte-identical);
bucketExog = bucket MEAN (a regressor is a LEVEL, not a flow), 1:1 with bucketHistory's buckets;
histImports[sku].exog stored on apply; exogFor(sku,grain) = ONE resolver feeding BOTH fcPayload
(demand tab) and _loopForecastPayload; winner strip shows a "+ price" Tag from the live result's
exog_features; importer preview/placeholder announce the column. pytest +4 (price-driven series:
exog_features surface; price column beats lag-only holdout MAPE; SAME model, planned future
₹10 vs ₹20 moves mean forecast >30u; short/junk columns degrade gracefully). Probe
/tmp/v4_4_probe.js 10/10 OBSERVED (live parser/buckets; real textarea paste → preview; apply
stores exog + production staled via demand cascade; live /api/forecast exog_features=['price'];
LIVE scenario contrast mean fcst 200 @₹10 vs 100 @₹20 — the model literally learned
demand = 300 − 10·price; legacy 2-col guard). Gate 4/4 (98 pytest).

**V4-3 ✅ BUILT 2026-06-11 — OT per-shift purchase mode (+ routed-hours fix).** production.py:
`ot_mode` 'per_hour' (default, byte-identical legacy — pay exactly the hours used) | 'per_shift' —
integer crew-call blocks ots[l,t] gate usable OT (ot ≤ shift_len·ots, OtShiftBlock) and the WHOLE
block is charged (blocks × hrs_per_shift × workers × rate × 1.5); lumpiness surfaced honestly via
line_results overtime_shifts / overtime_hours_paid (None in per_hour), never hidden. TWO REAL MODEL
BUGS found by the new tests: (a) LineCapHrs keyed off `cycle_time_by_sku_min` ONLY, so ROUTED
products (the real payload) had NO shared per-line hours constraint and per-line OT was never
purchasable — fixed with `_machine_cycle_min` (line map → routing bottleneck max ct/par, the same
resolution G-P4's _labor_cycle_min already used, hours basis == _route_cap); (b) the Link big-M
(`_route_cap`) excluded legal OT headroom, so a 43-unit week on a 40u-regular line went INFEASIBLE
instead of buying 3 OT hours — ceiling now hrs·OEE + line_max_ot (actual hours still governed by
LineCapHrs). Frontend: OT PURCHASE toggle on ProdParams (config.prodOtMode, token cfg.prod added
to CONFIG_TOKEN; productionOptsFromConfig otMode → payload params.ot_mode — ONE opts truth);
Capacity Loading grows an 'OT paid' column (blocks · hrs, red when paid > used) + per-shift
Reading in per_shift mode. pytest +3 (per_hour ~3h@₹450; per_shift 1 block 8h ₹1,200 with the
3h-used/8h-paid gap visible; never cheaper). Probe /tmp/v4_3_probe.js 10/10 OBSERVED (default
payload+solve per_hour with shifts:null; toggle click → config + production staled root=cfg.prod;
per-shift payload/solve echo; TPAC lines honestly slack at 0 OT, so 7b SQUEEZES the real payload
(week→10h) until OT binds: 5 blocks/line, 40h paid vs ~39h used, OT bill ₹36,000 ≥ ₹33,631
per-hour). Gate 4/4 (94 pytest · lints · model_check 9 · golden_path 4/4).

**V4-2 ✅ BUILT 2026-06-11 — multi-resource aggregate (machine-hour feasibility).** aggregate.py:
optional `resources` rows {name, hours_per_agg_unit, capacity_hours} add (P_t+O_t)·h_c ≤ H_c per
period beside labour — a labour-feasible plan can no longer promise machine-infeasible volume
(the Q1 gap); binding machine rows are PRICED (cap_rows → shadow_prices "Machine LINE-X P_t");
result.resources carries util_by_period + peak_util from the solved plan; no rows ⇒ byte-identical
legacy (resources:null). Frontend: aggMachineResources(config,planning) — per line, h = Σ(cyc/60)·
demand ÷ Σ lw·demand on the SAME effective routing the schedule uses (prodRouting override →
master), H = wd × hrsPerShift × shifts × 4.33 × OEE; planParams.machine_resources checkbox
(off=legacy); per-line peak-util strip (data-vis="v4-resources", red ≥99.9% "machine-bound");
ONE truth — tab + _loopAggregatePayload share the builder. pytest +1 (machine ceiling 60h caps
production where labour allowed 100u, overflow → backorder, peak_util ≥99.9, dual row priced).
Probe /tmp/v4_2_probe.js 11/11 (default solve resources:null; builder == independent recompute
LINE-01 0.0319 h/u·174.6H ··· ; toggle stales; REAL solve utils 20.6/16.7/9.4% pk == (P+O)·h/H
zero-drift; strip renders). Gate 4/4 (capacity_hours ledgered in UNITS.md).

**V4-1 ✅ BUILT 2026-06-11 — profit-aware aggregate objective (+ Q10 σ rider).** aggregate.py:
`objective_mode` 'min_cost' (default, byte-identical) | 'max_profit' — lost-sales L_t ≤ demand_t
priced at `revenue_per_unit` (SEMANTIC FIX mid-build: first cut priced lost sales at NET
contribution, which double-charges production cost the LP already levies via reg/OT and shed
6,499u at −₹36.6L; the correct coefficient in this formulation is REVENUE — min(cost+rev·L) ≡
max contribution. Caught by the probe's profit-identity assert). Result: profit block
{revenue_per_unit · lost_units · lost_revenue · total_revenue · profit}; per-period 'lost';
contribution<=0 rejected loudly. Q10 rider: `backorder_sigma_weight` (seed 0 = legacy) scales
backorder ₹ ×(1 + w × demand_cv), cv demand-weighted from REAL per-SKU MAPE. Frontend: objective
toggle + Revenue/unit GovField (seed = Σ price·demand ÷ Σ lw·demand = ₹1,507/wu) + σ-weight
GovField on PlanParamsCard (token cfg.plan); profit KpiRow from the solve only; ONE params truth
— plan.jsx payload + _loopAggregatePayload carry identical fields. pytest +5 (shed when OT ₹500 >
revenue ₹300; keep when revenue dominates; identity; loud reject; σ scales only backorder and
makes the plan MORE backorder-averse 380→180). Probe /tmp/v4_1_probe.js 14/14 (min-cost solve
byte-identical legacy; toggle stales via cfg.plan; REAL max-profit solve profit +₹14.05L lost 0
on TPAC — revenue dominates; identity within rounding; loop payload == tab payload). Gate 4/4
(payload literal registered).

**V5 — PARKED (named, not forgotten):** V5-1 multi-site on-hand/netting (G-N2/G-I3) · server-side
concurrent branching · supplier-capacity allocation · multi-mode logistics.

**Sequencing rationale:** truth before paint (V2 before V3) — repainting screens over a wrong
capacity basis would be the exact "presentation reskin" failure this project exists to avoid; but
V3-0 (GovField) can be built in parallel since V2 items will want it for their badges.

---

### Appendix — Concrete hardcode register (found 2026-06-10, all → V2)
`store.jsx:815` ordering_cost 120 · `store.jsx:1344-46` ot 180/holding 24/backorder 300/hire 8000/
fire 12000/wage 22000 · `console.jsx:494` shared_capacity = demandHours×0.82 (✅ V2-1) · `store.jsx:1104`
changeover_mins:30 default · `store.jsx:1199` nRuns 500 (governed via opts.nRuns; 500 = seed) ·
`data.jsx:188` changeoverSkus 6-FG literal (+ addProduct store.jsx:1901 doesn't extend it) · 13-wk
fence store.jsx:693 (✅ governed planning.productionScheduleWeeks).
**Audit additions (2026-06-10, hours sweep):** ✅ FIXED: hrsPerShift=8 ×3 sites (store/console/
production.jsx wrong-slice read) · setup_cost:50 ×2 (production+MC payloads → config.prodSetupCost) ·
production.py headcount×40.0 labor week (→ params.labor_week_hrs). STILL OPEN (→ V2-12 lint catches
the class): `rehire_notice_hrs:80` (store productionPayload params) · MC per-period capacity
heuristic `avg demand ×3` (montecarloPayload) · MC `prodLeadTime` default 1 wk / cv 0.5 (UI-settable
in ScnRisk, defaults undeclared elsewhere) · `workers_per_shift` fallback 1 · declared constants
(documented, fine): 364-day planning year (=52wk, seed convention) · 4.33 wk/mo · periods_per_year:52
(correct — schedule basis is weeks by contract).
