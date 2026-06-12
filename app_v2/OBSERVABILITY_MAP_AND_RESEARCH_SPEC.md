# app_v2 — Observability Map & Deep-Research Spec
**A single living document that (a) draws the whole machine as a picture, (b) names every technique inside it, (c) catalogues the mistakes we keep making and the blind spots we haven't checked, (d) turns "this is my company, what am I here to do" into one structured end-to-end test question with sub-flows, and (e) benchmarks us against the industry and lists what to build next.**

> Status: **SPEC — not yet implemented.** Authored 2026-06-05 from ground-truth reads of the codebase (24 engine modules, 43 routes, 18 jsx pages). Intended to be picked up and implemented **after compaction**. Nothing here changes runtime behaviour by itself; it is the map + the plan.
>
> How this was assembled (so it can be trusted, not rubber-stamped): the solver inventory came from `M.solvers` (16) and `ls *.py` (24 modules); the routes from `grep @app.route app.py` (43); the page→endpoint wiring from `grep useSolve/apiPost app_v2/*.jsx`; the named methods from the solver docstrings themselves. Every claim below is checkable against a file:line. Where I'm inferring intent rather than reading it, I say so.

---

## Part 0 — Orientation: what "observability" means here

This is **not** runtime observability (logs/metrics/traces). It is **model observability**: can a human (or the next session) *see*, for any number on screen —

1. **Where did this input come from?** (a Setup parameter? a seed? a prior solve? typed?)
2. **Which formula consumed it?** (which solver, which equation, which textbook method)
3. **Which API carried it?** (one of the 16 solver families)
4. **What did it produce, and who downstream eats that output?** (the lineage chain)
5. **Is it honest?** (solved vs derived vs seed vs illustrative — the provenance contract)

When any of those five is broken, we get a *class* of bug we have now hit repeatedly: a seed wearing a "solved" chip, a labor-weighted number headlined as physical, a buy-plan exploding the wrong bill of materials, an after-tax cash flow taxed twice. **Part 3 is the ledger of those.** The rest of the document exists so that ledger stops growing.

---

## Part 1 — The company and the operator (the framing the user asked for)

### 1.1 "This is my company"
**Tata Precision Auto Components Pvt. Ltd. (TPAC)** — a Chennai (Tamil Nadu) **MSME** precision-machining job shop supplying engine components to OEM and Tier-1 auto customers. Turnover ₹38.4 Cr; plant & machinery ₹9.4 Cr (drives the MSMED-Act tier). GST-registered. Capital stack ≈ ₹15 Cr (62% equity / 38% debt), blended hurdle ≈ **11.15%**.

**Plant:** three lines (LINE-01/02/03), four capital assets (DMG Mori CNC Lathe, Studer Grinder, Vacuum Heat Furnace, Zeiss CMM). Six-day week, holiday calendar.

**Six finished SKUs (the portfolio I choose across):**

| SKU | Product | ABC | Line | Note |
|---|---|---|---|---|
| TPA-4471 | Crankshaft Bearing | A | LINE-01 | high-value runner |
| TPA-3215 | Piston Ring Assembly | A | LINE-02 | **labor-light** (worker-weight 0.733) — the one that made the aggregate units diverge |
| TPA-9904 | Valve Seat Insert | A | LINE-01 | shares LINE-01 with 4471 (changeover coupling) |
| TPA-2188 | Connecting Rod | B | LINE-03 | |
| TPA-5540 | Oil Pump Housing | B | LINE-02 | |
| TPA-7722 | Timing Chain Tensioner | C | LINE-03 | tail SKU, EVA-destroyer candidate |

**Parts master (shared across SKUs — the source of the "shared BOM" hazard):** RM-STL42 Chromoly Steel Bar, RM-BRG18 Bearing Alloy Billet, CN-SEAL9, CN-LUB02, CN-BLT04 Grade-10.9 Bolt. Suppliers: Bharat Forge, Sundaram (MSME), POSCO (USD import), Kalyani (MSME), SUP-012. **Key fact:** parts are *shared* but each FG consumes a *different subset at different quantities* (`M.skuBom`) — TPA-4471 does **not** use the Grade-10.9 bolt. Treating the master bill as one FG's bill is the SR-1 bug.

### 1.2 "What am I here to do" — the operator's job
I am the **planner/owner-operator**. My job, every S&OP cycle, is to answer six linked questions and have the answers *agree with each other*:

1. **How much will sell?** (demand) → 2. **Can the plant make it, and with how many people?** (aggregate + production) → 3. **Which mix maximises profit under the binding constraint?** (profit-mix) → 4. **What do I buy, when, and how much safety stock?** (procurement + inventory) → 5. **How risky is the committed plan, and where does it break?** (Monte-Carlo/CVaR/stress) → 6. **Does any of this clear my cost of capital — and how do I fund it?** (finance/EVA/capital).

The product's pitch is that all six are **one connected model with a glass box**, not six disconnected spreadsheets — and that the answer to #6 can *re-plan* #1–#5 (the ops↔finance wedge).

### 1.3 Product relationships I must reason about (so I can choose)
- **Shared lines** → TPA-4471 and TPA-9904 both run LINE-01: sequencing/changeover couples them; expanding LINE-01 helps both.
- **Shared parts** → risk-pooling: the same steel bar feeds several SKUs, so safety stock pooled upstream is cheaper than per-FG (square-root law).
- **Shared capital** → every SKU draws on the same ₹15 Cr stack at the same 11.15% hurdle; an EVA-destroyer tail SKU (TPA-7722) may still be *load-bearing* on a shared line — pruning it can *raise* cost. That tension is the whole point.

---

## Part 2 — THE OBSERVABILITY MAP (the visual architecture)

### 2.1 The machine at a glance — params in, decisions out, loops back

```
                          ┌──────────────────────────────────────────────────┐
                          │           SETUP / PARAMETER GOVERNANCE            │
                          │  config.* (taxRate, serviceLevel, invHoldingSpread│
                          │  fxRates, finEquity/finDebt, planParams, prod*)   │
                          │  planning.* (grain, horizon, frozen/slushy, days) │
                          │  ── governed once, fanned out via SOLVE_DEPS ──   │
                          └───────────────┬──────────────────────────────────┘
                                          │ (markStale tokens: config / cfg.prod /
                                          │  cfg.profit / bom / demand …)
        ┌─────────────────────────────────┼─────────────────────────────────────┐
        ▼                                  ▼                                     ▼
┌───────────────┐   forecast        ┌───────────────┐   aggregate        ┌───────────────┐
│   DEMAND      │──/api/forecast───►│     PLAN       │──/api/solve/──────►│  PRODUCTION   │
│ history, NPI, │   demand/sense    │ S&OP level/   │     aggregate       │ schedule MILP │
│ promo, CSV    │                   │ chase, linecap │   linecap           │ sequence      │
└──────┬────────┘                   └──────┬─────────┘                    └──────┬────────┘
       │ committed demand                  │ aggregate plan                     │ time-phased
       │ (explicit event)                  │ (labor-weighted units!)            │ build + inv
       ▼                                   ▼                                    ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                         PROFIT-MIX (true LP, duals/shadow prices)                       │
│                            /api/solve/profitmix  ── the glass box                        │
└──────────────┬───────────────────────────────────────────────────────────┬────────────┘
               │ binding constraint, shadow ₹/unit, crossover               │
               ▼                                                            ▼
┌───────────────┐  procurement  ┌───────────────┐  meio / meio-network ┌───────────────┐
│  SOURCING     │──/api/solve/──►│  INVENTORY    │──/api/solve/────────►│  LOGISTICS    │
│ buy plan MILP │  procurement   │ (s,S), lot-   │  meio, meio-network  │ transport LP  │
│ per-FG BOM!   │  policy        │ sizing, pool  │  policy, cvar        │ allocation    │
└──────┬────────┘  rolling       └──────┬────────┘                      └──────┬────────┘
       │                                │                                      │
       └────────────────┬───────────────┴──────────────────────────────────────┘
                        ▼
        ┌───────────────────────────────┐        ┌──────────────────────────────┐
        │  SCENARIOS / RISK              │        │   FINANCE / CAPITAL          │
        │  /api/solve/montecarlo, cvar,  │◄──────►│  /api/calc/hurdle, npv,      │
        │  sensitivity, /api/whatif      │  EVA   │  wacc-structure, depreciation│
        │  stress-to-failure, cockpit    │  prune │  /api/solve/capital-capacity │
        └───────────────┬────────────────┘  branch└──────────────┬───────────────┘
                        │                                         │
                        └───────────►  re-plan loop  ◄────────────┘
                          (runFullLoop / runScenario: forecast→aggregate→
                           production→linecap→montecarlo, byte-restored)
```

**Read it as:** Setup governs the knobs → Demand seeds the chain → Plan sizes people → Production schedules → Profit-mix prices the binding constraint → Sourcing/Inventory/Logistics execute it → Scenarios stress it → Finance judges it against the hurdle and can *push a re-plan back up the chain*. The dashed feedback arrows are the differentiator (control-tower-on-the-committed-plan + concurrent what-if).

### 2.2 The 16 solvers — family, page, formula, named method, key inputs

| # | Solver (API) | Page(s) | Named method / formula | Key inputs (← param) | Emits / who consumes |
|---|---|---|---|---|---|
| 1 | **Forecast** `/api/forecast`, `/api/demand/sense` | Demand | **11-model leaderboard** (naive · Holt-Winters · ARIMA · RandomForest · GradientBoost · XGBoost · MLP · HW+RF hybrid · **Croston/SBA/TSB** for intermittent), each scored MAPE/RMSE/MAE on an out-of-sample holdout, MASE-ranked per-SKU winner (V1-1 doc fix 2026-06-10 — was understated as "HW+RF") | history (CSV/seed), season, promo, holidays | committed demand → Plan, Profit-mix, Sourcing |
| 2 | **Aggregate** `/api/solve/aggregate` | Plan | **Hax–Meal / Holt–Modigliani–Muth–Simon** aggregate planning; level-vs-chase LP; InvBal in **labor-weighted units** | demand, `planParams` (init_inventory, init_workforce, hire/fire/OT, allow_backorder), worker-weights | aggregate plan → Disaggregate, Production |
| 3 | **Disaggregate** `/api/calc/disaggregate` | Plan | Hierarchical disaggregation (proportional to physical demand share) | aggregate plan, per-SKU shares | SKU-level plan |
| 4 | **Reconcile** `/api/solve/sop` | Plan | top-down ⇄ bottom-up consensus reconciliation (`run_sop_pipeline`, reconcile.py) | family vs SKU forecasts | consensus number |
| 5 | **Profit Mix** `/api/solve/profitmix` | Console, (Plan) | **True LP** (not greedy margin/hr); **shadow prices + reduced costs + crossover** | prices, costs, capacity, demand ceilings | binding constraint, duals → DecisionExplainer, Finance |
| 6 | **Procurement** `/api/solve/procurement`, `/rolling` | Sourcing, Console | multi-period **MILP**; SS = **Heizer z·σ_LTD** OR **CVaR (Rockafellar–Uryasev)**; per-FG **bomForSku** | per-FG BOM, lead, MOQ, `serviceLevel`, `carryRate`, fxRates | buy plan, (s,S) policy → Inventory, Finance |
| 7 | **Production** `/api/solve/production`, `/production-sensitivity` | Production, Console | scheduling MILP; **bottleneck/throughput (Theory of Constraints)**; campaign min-run | routings, OEE, line caps, demand | time-phased build + projected inventory → Finance EVA capital base |
| 8 | **Sequencing** `/api/solve/sequence` | Production | changeover-min **Hamiltonian path** (TSP-like) over 6 SKUs | 6×6 changeover matrix | optimal run order |
| 9 | **Lot Sizing** `/api/solve/lotsizing` | (Sourcing/Inventory) | **EOQ (Wilson)**, **Wagner-Whitin (DP, optimal)**, **Silver-Meal**, **(s,S) Min-Max** | demand, order/holding cost | lot policy |
| 10 | **Transport** `/api/solve/transport` | Logistics, Console | **transportation problem LP** (min-cost flow) | DC/demand nodes, ship costs, capacities | shipment plan, allocation |
| 11 | **Allocation (MEIO)** `/api/solve/meio` | Sourcing | **Graves–Willems guaranteed-service model (GSM)** — *where* to place SS in RM→WIP→FG tree | assembly tree, service times, stage costs | SS placement |
| 12 | **Consolidate (Network MEIO)** `/api/solve/meio-network` | Sourcing | **square-root-law risk pooling** + echelon placement on shared parts | per-part SKU cohorts (skuBom), ρ matrix, echelons | pooled SS, capital freed |
| 13 | **Monte Carlo** `/api/solve/montecarlo` | Scenarios, Console | simulation w/ **lead-time lag**; per-SKU bill | committed plan, demand/lead CV, skuParts | fill%, CVaR tail → control tower, stress |
| 14 | **CVaR** `/api/solve/cvar` | Scenarios, Sourcing | **Rockafellar–Uryasev LP**; newsvendor order-up-to (critical ratio) | loss scenarios, β, under/over costs | CVaR-robust SS / stocking level |
| 15 | **Capital** `/api/solve/capital`, `/calc/hurdle`, `/wacc-structure`, `/npv`, `/depreciation` | Finance | **CAPM + Hamada re-levering** βL=βU(1+(1−t)D/E); **blended hurdle**; **NPV/IRR + dep shield (SLM/WDV)**; DSCR | finEquity/finDebt, taxRate, rf/β/erp, cashflows | hurdle → every gate; EVA |
| 16 | **Capital Capacity** `/api/solve/capital-capacity` | Finance | endogenous-capacity capital plan; CapEx justified by **bottleneck shadow price** (×units/hr) | line CapEx, added hrs, budget, linecap dual | fund/defer line expansion, risk-adj NPV |

*(Also live but outside the curated 16: `pattern_sensing` `/api/demand/patterns` + `/risk/regimes`, `risk` `/api/solve/sensitivity`, `report` `/api/report/pdf`, `plant_calendar` `/api/calc/calendar`, `finance.calc_wacc`, `/api/ai/insights`, `/api/solve/researcher`, `/api/whatif`, `/api/solve/pipeline`, `/api/solve/consolidate`. 24 engine modules, 43 routes total.)*

### 2.3 The named-concept legend (the "Hax-Meal, Graves, …" the user asked to see pinned)

| Concept | Where it lives | One-line meaning |
|---|---|---|
| **Hax–Meal hierarchical planning** | `aggregate.py:10`, `disaggregate.py` | Plan at the aggregate (family/worker-time) level, then disaggregate to SKUs — the classic 2-tier S&OP. |
| **Holt–Modigliani–Muth–Simon** | `aggregate.py:10` | The LP form of level-vs-chase: trade hire/fire/OT vs inventory/backorder cost. |
| **Holt-Winters** | `forecast.py:317` | Triple exponential smoothing (level+trend+season). |
| **Croston / SBA / TSB** | `forecast.py:142-194` | Intermittent-demand forecasting (separates demand size from interval; TSB handles obsolescence). |
| **Hybrid HW + RandomForest** | `forecast.py:391` | HW baseline + ML residual correction. |
| **MASE / MAPE backtest** | `forecast.py:529+` | Out-of-sample model selection; depth-gated (don't fit DL on <24 pts). |
| **Graves–Willems GSM (MEIO)** | `meio.py:10` | Guaranteed-service multi-echelon SS *placement* in one assembly tree. |
| **Square-root law risk pooling** | `meio_network.py:11` | Pooling N SKUs' demand for a shared part cuts SS by ~√N; place the pooled buffer at min-holding echelon. |
| **EOQ (Wilson) / Wagner-Whitin / Silver-Meal / (s,S)** | `lot_sizing.py:9-15` | Lot-sizing family: closed-form, DP-optimal, heuristic, continuous-review. |
| **Rockafellar–Uryasev CVaR** | `cvar.py:8` | Tail-risk as an LP: CVaR_β = min_α α + 1/((1−β)S)Σ[L−α]⁺. |
| **Heizer z·σ_LTD** | `procurement.py`, `policy.py` | Textbook single-echelon safety stock = z(service) × σ of lead-time demand. |
| **Newsvendor critical ratio** | `cvar.py:13` | Single-period order-up-to where Cu/(Cu+Co) sets the fractile. |
| **Theory of Constraints / bottleneck throughput** | `production.py:136`, `capital_capacity.py:18` | The slowest op governs the line; expand where the schedule actually binds. |
| **CAPM + Hamada re-levering** | `capital_structure.py:22,106` | Ke=rf+βL·ERP, βL=βU(1+(1−t)D/E) — equity cost rises with leverage. |
| **Transportation problem LP** | `transport.py` | Min-cost flow from sources to sinks under capacity. |
| **True LP profit-mix w/ duals** | `profitmix.py:4` | Shadow price = ₹ value of one more unit of the binding resource; reduced cost = why a SKU is left out. |

---

## Part 3 — The mistake & blind-spot ledger (observability of OUR errors)

This is the part the user explicitly wanted: *"what sort of mistakes we have made, and what else are we not looking close."* These are **patterns**, drawn from the actual fixes logged in `DESIGN_REMEDIATION.md`. Each is a recurring failure mode + the detector that should have caught it earlier.

### 3.1 Mistake patterns we have repeated (each hit ≥2×)

| Pattern | Concrete instances | Root cause | The detector that would catch it |
|---|---|---|---|
| **P-A · Seed wearing a "solved/derived" chip (R2)** | Demand pre-run green history; Plan PlanGap `derived`+fake asOf; Finance EVM/CCC `derived` over flat seeds; Finance FX VaR; Buy-vs-Lease hardcoded | provenance kind chosen by habit, not by data origin | a lint that asserts: a `<Provenance kind="solved\|derived">` must trace to a `useSolve` result or a computed expression in the same component, never a literal/`M.*` seed |
| **P-B · Wrong scope of a shared object** | SR-1 buy plan exploded the **master BOM** for one FG (bought 14,807 bolts a SKU never uses); Products ScopeBanner claimed all cards were per-item | "shared master" silently reused as "this item's" | every solver payload must declare scope (`item` vs `portfolio`); a per-item payload may not read a portfolio master without a per-item filter (`bomForSku`) |
| **P-C · Unit mismatch across a boundary** | Plan opening inventory: physical 1,260 vs labor-weighted 1,124 fed to an InvBal that nets Σqty·weight | two tiers (physical vs worker-time) share a field name | a units annotation on every cross-solver field; assert dimensional consistency at the API boundary |
| **P-D · Double-counting / double-transform** | FIN-3 NPV shield taxed already-after-tax CF twice (cf·(1−t)+dep·t) | the seed's economic meaning (pre- vs post-tax) was undocumented | label every cash-flow seed with its tax/ível stage; a transform asserts its input stage |
| **P-E · Two models of the same quantity, unreconciled** | FIN-4 source-weighted Ke (13.92%) vs CAPM Ke (12.5%) side by side; two service-level fields (fixed in Ph2) | two correct methods, no bridge note | when two cards compute "the same" quantity, require an explicit reconciliation note or a single source |
| **P-F · Inert control that looks live (R3)** | Sourcing "⚡ Expedite both"; Console dead SOLVE band; Demand dropzone; many Ph1 inputs | a button/input with no handler shipped as decoration | a lint: every interactive element has an onClick/onChange or a `PreviewTag` |
| **P-G · Magic constant drifting from its governed source** | carryRate fallback 0.1124/11.24 vs solved 11.15; hardcoded 0.24 carry (fixed earlier); landed FX 84.20 vs config | a literal copied instead of read | grep for numeric literals that duplicate a `config`/`M.wacc` value; require a `_effNum(config.x, seed)` read |
| **P-H · Duplicate render of one artifact** | Buy-vs-Lease rendered in **both** FinValue and FinInvest | copy-paste placement, no "home" rule | a component-usage count; decision cards render once, with an owning subtab |
| **P-I · Self-imposed rule that wasn't asked for** | the "frozen solver logic" rule (dropped); improvised review scoring (corrected) | over-caution / not following the written methodology | when in doubt, read the methodology doc; don't invent constraints |

### 3.2 Blind spots — what we have NOT looked at closely yet

1. **Cross-solver numerical consistency.** We verify each solver *in isolation* (one smoke per tab). We have **never** asserted that the *same* quantity agrees across solvers in one end-to-end run: does Forecast's committed demand equal Aggregate's input equal Profit-mix's demand ceiling equal Procurement's gross requirement? Part 4's golden path is designed to test exactly this. **This is the biggest gap.**
2. **The 8 lighter tabs never got the §6.5 two-lens review.** Only the domain-heavy 4 (Demand/Plan/Sourcing/Finance) did. Home, Setup, Products, Production, Logistics, Console, Scenarios, Reference have only had the cross-cutting E′ pass — local domain lies may remain (e.g., Production's OEE provenance, Logistics' "~18% km cut" empty-state, Console's result-mirror dedup).
3. **Units discipline is ad-hoc.** P-C was fixed *locally* on Plan. No global units contract exists; the next unit-bearing field (e.g., kg vs units in transport, ₹ vs ₹L vs ₹Cr in finance) is unprotected.
4. **Provenance is enforced by review, not by code.** Every R2 was caught by a human/agent reading chips. There is no automated check; P-A will recur on the next new card.
5. **The feedback loops are asserted, not measured.** `runFullLoop`/`runScenario` chain five solvers, but we don't surface *whether the loop converged* or *how much each KPI moved* in a single observable — the "value ledger" is the closest, but it's per-decision, not per-loop.
6. **No single "scenario regression" harness.** Each tab's smoke is bespoke. There is no one script that runs the golden path end-to-end and diffs against a known-good snapshot — so a change in solver A that silently breaks solver B's input would pass all current tests.
7. **Setup→solver coverage is unverified.** The parameter registry lists 11 governed inputs, but we haven't proven that *every* solver input is either governed (registry) or honestly seeded — there may be ungoverned knobs hard-coded in payloads.

---

## Part 4 — THE STRUCTURED END-TO-END QUESTION (the master test, framed the way you described)

> This is the "this is my company / what am I here to do / here's my problem / here's how I'd approach it with the tools I have" narrative, turned into a **step-by-step, multi-line test script**. Run it as one *golden path* first, then the *sub-flows*. At every step it names: the **page**, the **input ⇄ Setup param**, the **solver + formula**, the **API**, the **expected output**, and — crucially — the **observability check** (does the number agree with the upstream number?) and the **industry-benchmark question** (how would IBP/Kinaxis/o9 do this, and are we better/worse?).

### 4.0 The operator's standing problem (one paragraph, in the user's voice)
*"I run TPAC. Next quarter an OEM is ramping the Crankshaft Bearing (TPA-4471) and the Piston Ring (TPA-3215) while my tail SKU (Timing Chain Tensioner, TPA-7722) is barely breaking even. Steel (POSCO, USD) just moved on FX, one of my MSME suppliers is aging past 45 days, and LINE-01 — which both my A-runners share — is my suspected bottleneck. I have ₹15 Cr of capital at an 11.15% hurdle. **Tell me: what to sell, make, buy, hold, and fund next quarter — and prove every number to me, show me where it breaks, and show me it clears my cost of capital.**"*

### 4.1 GOLDEN PATH — one full all-use scenario (12 steps)

```
STEP 1 · SETUP — set the knobs once.
  Page: Setup ▸ Parameter Governance
  Inputs ⇄ params: taxRate 25.17, serviceLevel 0.95, invHoldingSpread 12.8,
                   fxRates{USD 84.20, EUR 91.40}, planning{grain, horizon, frozen/slushy, 6-day week}
  Solver/API: /api/calc/calendar (working days)
  Observability check: every downstream solver that reads serviceLevel/fxRates/carryRate
                       must go STALE when I edit here (SOLVE_DEPS).  ← verify the cascade
  Industry Q: IBP/Kinaxis call this "planning master data / parameter governance." Do we have
              one source of truth with lineage?  (We do — registry + tokens. Benchmark: GOOD.)

STEP 2 · DEMAND — how much will sell?
  Page: Demand
  Inputs ⇄ params: history (seed or CSV import), season, promo, NPI like-model for the ramp
  Solver/API: Forecast /api/forecast  — 11-model leaderboard (naive/HW/ARIMA/RF/GB/XGB/MLP/hybrid
              + Croston/SBA/TSB for the intermittent tail), MASE/MAPE holdout backtest picks the
              per-SKU winner; /api/demand/sense auto-flags regime breaks
  Output: committed demand per SKU (EXPLICIT commit event — not silent auto-commit, post D-1 fix)
  Observability: winner model + out-of-sample MAPE shown; PI band σ = holdout error.
  Industry Q: o9/Blue Yonder demand sensing uses external signals + ML. We have hybrid+Croston+
              external-signal drivers (D6). Gap: no true causal/ML-at-scale. Benchmark: COMPETITIVE.

STEP 3 · PLAN — can the plant make it, with how many people?
  Page: Plan ▸ Aggregate (S&OP)
  Inputs ⇄ params: committed demand (STEP 2), planParams{init_inventory ← auto-reconciled from
                   Network on-hand in LABOR-WEIGHTED units, init_workforce, hire/fire/OT, allow_backorder}
  Solver/API: Aggregate /api/solve/aggregate — Hax–Meal level-vs-chase LP
  Output: aggregate plan (worker-time units), strategy label (level/chase/hybrid), opening stock 1,260 phys
  Observability: ★ THE unit check — UI headlines physical 1,260, solver nets labor-weighted 1,124.
                 Does the disaggregate tier reconcile back to physical demand?  ← assert
  Industry Q: SAP IBP's aggregate planning is the textbook. Are our level-vs-chase economics
              (hire/fire/OT vs holding/backorder) real levers? (Yes — allow_backorder flips
              feasibility.) Benchmark: GOOD; gap = no multi-resource (just worker-time).

STEP 4 · PRODUCTION — schedule it and find the bottleneck.
  Page: Production ▸ Schedule + Sequence
  Inputs ⇄ params: aggregate plan (STEP 3), routings, OEE, line capacities, 6×6 changeover matrix
  Solver/API: Production /api/solve/production (MILP, TOC bottleneck) + Sequence /api/solve/sequence
              (Hamiltonian min-changeover over the 6 SKUs)
  Output: time-phased build, projected_inventory (← feeds Finance EVA capital base!), bottleneck=LINE-01?
  Observability: does projected_inventory × unit cost = the working capital Finance charges? ← cross-check
  Industry Q: Kinaxis RapidResponse concurrent scheduling. We have MILP+TOC+campaign min-run.
              Benchmark: GOOD for an MSME; gap = no finite-capacity APS at op level.

STEP 5 · PROFIT-MIX — which mix maximises profit under the binding constraint?
  Page: Console ▸ Profit (the glass box)
  Inputs ⇄ params: prices, costs, capacity (STEP 4 bottleneck), demand ceilings (STEP 2)
  Solver/API: Profit Mix /api/solve/profitmix — TRUE LP; shadow_prices, reduced_costs, crossover
  Output: optimal mix + DecisionExplainer: 🔴 bottleneck ₹/unit, ⬜ dropped SKU (reduced cost),
          💡 crossover price, 🧪 "Prove it" re-solve
  Observability: the shadow price on LINE-01 here must equal the linecap dual Finance uses to value
                 expansion (FV-C).  ← THE single most important cross-solver identity in the app
  Industry Q: This glass-box dual explanation is our WEDGE — IBP/o9 hide the LP. Benchmark: DIFFERENTIATED.

STEP 6 · SOURCING — what to buy, when, how much.
  Page: Sourcing ▸ Run
  Inputs ⇄ params: per-FG BOM (bomForSku — NOT the master!), lead, MOQ, serviceLevel (STEP 1),
                   carryRate (= WACC STEP 11 + spread), fxRates (STEP 1)
  Solver/API: Procurement /api/solve/procurement (MILP) + /rolling; SS = Heizer z·σ_LTD OR
              CVaR (Rockafellar–Uryasev) per ss_source
  Output: time-phased PO plan + (s,S)/(R,Q) policy per part
  Observability: ★ THE BOM check (SR-1) — buy plan must explode ONLY parts the selected FG uses;
                 carryRate must move when WACC moves (STEP 11).  ← assert both
  Industry Q: SAP MRP / o9 supply planning. We have MILP+CVaR-robust SS + FX-aware landed cost.
              Benchmark: GOOD; gap = no supplier capacity/allocation optimization across the network.

STEP 7 · INVENTORY / MEIO — place safety stock where it's cheapest.
  Page: Sourcing ▸ Design ▸ MEIO + Pooling
  Inputs ⇄ params: assembly tree, per-part SKU cohorts (skuBom), ρ correlation matrix, echelons
  Solver/API: meio /api/solve/meio (Graves–Willems GSM) + meio-network /api/solve/meio-network
              (square-root-law pooling)
  Output: SS placement (RM vs WIP vs FG), pooled buffer, CAPITAL FREED
  Observability: pooled SS < Σ decentralised SS (the √N dividend) — show the delta as ₹ freed.
  Industry Q: This is the o9/Llamasoft MEIO crown jewel. We have real GSM + pooling. Benchmark:
              STRONG for the category; gap = no stochastic-service or guaranteed-service hybrid.

STEP 8 · LOGISTICS — move it.
  Page: Logistics
  Inputs ⇄ params: DC/demand nodes, ship costs, capacities, SKU weights (kg)
  Solver/API: Transport /api/solve/transport (transportation LP) → allocation + consolidation
  Output: min-cost shipment plan, lane flows, tonnage
  Observability: allocation flows must sum to the demand from STEP 2.  ← conservation check
  Industry Q: Blue Yonder transportation. Benchmark: BASIC (single-echelon min-cost); gap = no
              multi-leg / mode / time-windowed routing. (Lighter tab — not yet domain-reviewed.)

STEP 9 · RISK — how robust is the committed plan, and where does it break?
  Page: Scenarios ▸ Risk + Stress
  Inputs ⇄ params: the COMMITTED plan (STEP 4 cached), demand/lead CV, per-SKU bill (skuParts)
  Solver/API: Monte Carlo /api/solve/montecarlo (lead-time lag) + CVaR + ResilienceStress
              (ramp one lever, re-solve MC per step → "survives to X / breaks at Y")
  Output: fill% distribution, CVaR95 tail, degradation curve
  Observability: MC replays the SAME committed gantt (cross-stage cache) — not a fresh plan. ← verify
  Industry Q: Kinaxis/o9 scenario simulation. Our stress-to-failure on the committed plan is
              DIFFERENTIATED (control tower on the real plan). Benchmark: DIFFERENTIATED.

STEP 10 · WHAT-IF — concurrent branch without disturbing the live plan.
  Page: Scenarios ▸ Cockpit / What-If
  Inputs ⇄ params: clone base → perturb demand/cost/service → RE-SOLVE affected solvers
  Solver/API: /api/whatif + runScenario (transparent: save inputs+solves, apply branch, run loop,
              capture KPIs, BYTE-RESTORE live)
  Output: KPI Δ vs base, saved scenario to compare/merge
  Observability: live working set is byte-identical after the branch.  ← the concurrency guarantee
  Industry Q: Kinaxis concurrent planning is the benchmark. We approximate it client-side.
              Benchmark: COMPETITIVE concept; gap = not server-side concurrent at scale.

STEP 11 · FINANCE — does it clear the hurdle, and how do I fund it?
  Page: Finance ▸ Capital → Value → Investments
  Inputs ⇄ params: finEquity/finDebt sources, taxRate, rf/β/erp, production projected_inventory (STEP 4),
                   pooled SS value (STEP 7), net-block assets, line CapEx + linecap dual (STEP 5)
  Solver/API: hurdle (blended Ke/Kd) + wacc-structure (CAPM+Hamada) + npv (after-tax + DEP SHIELD,
              post-FIN-3) + depreciation + capital-capacity (CapEx justified by bottleneck shadow price)
              + Buy-vs-Lease (real two-leg NPV, post-FIN-1)
  Output: hurdle 11.15%, EVA/ROIC per SKU (TPA-7722 = destroyer?), required-sales bridge,
          fund/defer line expansion verdict
  Observability: ★ the hurdle here = the carryRate WACC in STEP 6; the EVA capital base = STEP 4
                 projected_inventory + STEP 7 pooled SS + net assets (NOT double-counted, excl RM/WIP).
  Industry Q: This ops↔finance closed loop is BEYOND IBP/Kinaxis (they stop at cost, not EVA/capital).
              Benchmark: DIFFERENTIATED — but watch the two-Ke reconciliation (FIN-4).

STEP 12 · CLOSE THE LOOP — finance re-plans ops.
  Page: Finance ▸ Value ▸ EVA-Prune Branch
  Inputs ⇄ params: the value-destroyer SKUs (STEP 11)
  Solver/API: scenarioPruneSkus → runScenario (zero destroyer demand, full loop re-solve, byte-restore)
  Output: does dropping TPA-7722 LOWER company cost/CVaR, or was it LOAD-BEARING on LINE-01/shared parts?
  Observability: the honest answer can be "ops proves finance wrong" (pruning RAISES cost). ← the wedge
  Industry Q: No mainstream IBP tool turns an EVA verdict into a transparent ops re-plan.
              Benchmark: SIGNATURE differentiator.
```

**The golden-path observability assertions (the 6 cross-solver identities to test as one harness):**
1. Forecast committed demand `=` Aggregate input `=` Profit-mix ceiling `=` Procurement gross req `=` Transport allocation total. *(currently UNTESTED end-to-end — blind spot #1 & #6)*
2. Profit-mix LINE-01 shadow price `=` linecap dual `=` Finance capital-capacity margin/hr (FV-C).
3. Sourcing carryRate WACC `=` Finance blended hurdle (STEP 6 ⇄ 11).
4. Production projected_inventory × unit cost `=` Finance EVA working-capital base (STEP 4 ⇄ 11).
5. Aggregate labor-weighted total `≈` physical total after disaggregation (the unit reconciliation).
6. MEIO pooled SS `<` Σ decentralised SS (the √N dividend is positive).

### 4.2 SUB-FLOWS (the disruptions — run each as a what-if branch off the golden path)

| Sub-flow | Trigger | Solvers re-fired | The question it answers | Watch (mistake risk) |
|---|---|---|---|---|
| **SF-1 · OEM ramp** | TPA-4471 +40% demand | Forecast→Aggregate→Production→Profit-mix→Procurement→Finance | Do I add a shift (capital-capacity) or lose the order? | bottleneck shadow price must drive the CapEx case (P-E) |
| **SF-2 · FX shock** | USD +₹5 (POSCO steel) | landed-cost→Procurement→policy→MEIO→CVaR→Finance | How much does my buy plan + VaR move? | carryRate/landed FX must read config, not a literal (P-G) |
| **SF-3 · Supplier aging** | Kalyani (MSME) hits 47d | Payment ledger→43B(h) risk→Finance | Tax disallowance exposure? | the 43B flag is illustrative until a real AP ledger (P-A) |
| **SF-4 · Commodity spike** | steel idx +20% | External signals→Procurement→Profit-mix→EVA | Which SKU flips to value-destroyer? | per-FG BOM, not master (P-B) |
| **SF-5 · Demand collapse** | TPA-7722 −50% | Forecast→Aggregate→EVA-prune | Drop the tail SKU — or is it load-bearing? | pruning may RAISE cost (the honest wedge) |
| **SF-6 · Lead-time stretch** | RM-STL42 +2 wk | port-delay→Procurement→MEIO→MC | Where to hold more buffer (echelon)? | pooled placement must move, not just raise SS |
| **SF-7 · Capacity loss** | LINE-01 down 1 wk | Production→Sequence→Profit-mix→MC | Re-sequence + which SKU sheds first (reduced cost) | sequencing over 6 SKUs, not implicit first-4 |

Each sub-flow is *already* runnable via the existing what-if/stress/prune machinery — **the spec's job is to wire them into one named, repeatable harness** (see Part 6).

---

## Part 5 — Industry benchmark & best-practices to implement

### 5.1 Capability scorecard vs the market (IBP = SAP IBP; KX = Kinaxis; o9; BY = Blue Yonder)

| Capability | TPAC app today | Market leader | Verdict | Best-practice to add |
|---|---|---|---|---|
| Demand forecasting | 11-model leaderboard (classical+ML+intermittent), MASE backtest, ext-signal drivers | o9/BY demand sensing | **Competitive** | causal ML, hierarchical reconciliation at scale |
| Aggregate S&OP | Hax–Meal level/chase LP, worker-time | IBP | **Good** | multi-resource (not just labor), seasonal pre-build polish |
| Production scheduling | MILP + TOC bottleneck + campaign + sequencing | KX concurrent / BY APS | **Good (MSME)** | finite-capacity op-level APS, setup matrices per work-center |
| Inventory / MEIO | Graves–Willems GSM + √N pooling + echelon placement + CVaR SS | o9 / Llamasoft | **Strong** | guaranteed-vs-stochastic hybrid, multi-echelon across the supplier network |
| Procurement | multi-period MILP, FX landed cost, (s,S)/(R,Q) | IBP / Ariba | **Good** | supplier capacity & allocation optimization, dual-sourcing |
| Risk / scenarios | MC on committed plan, CVaR, stress-to-failure, concurrent what-if | KX | **Differentiated** | server-side concurrency, automated playbooks |
| Finance / capital | CAPM+Hamada hurdle, NPV+shield, EVA/ROIC, capital-capacity, EVA-prune loop | *(none integrate this)* | **Signature** | reconcile the two Ke models, add RM/WIP to capital base |
| Logistics | transportation LP, allocation | BY TMS | **Basic** | multi-leg/mode/time-window routing |
| **Glass-box / provenance** | duals explained in plain English, provenance chips, lineage | *(all are black boxes)* | **Signature** | automate provenance as a code check (Part 6 #1) |
| **Observability of own errors** | manual review only | *(N/A)* | **Gap** | the harness + lints in Part 6 |

**The honest thesis (carried from §7 differentiation track):** we do **not** have a feature gap against IBP/Kinaxis/o9 for an MSME — we have a *packaging + assurance* gap. The wedge is **glass-box duals + provenance + control-tower-on-the-committed-plan + concurrent what-if + ops↔finance EVA loop + low TCO**. The risk is **trust**: every R2/P-A instance erodes exactly the differentiator we're selling. So the #1 best practice is to make provenance and cross-solver consistency *machine-checked*, not review-checked.

### 5.2 Best practices to implement (ranked)
1. **Machine-checked provenance** — a build-time lint that fails if a `solved/derived` chip can't be traced to a solve/computation. Kills P-A permanently.
2. **One end-to-end scenario regression harness** — runs the golden path (Part 4.1) and asserts the 6 cross-solver identities; snapshots KPIs and diffs on every change. Kills blind spots #1 & #6.
3. **A units contract** — annotate every cross-solver field with its unit/level; assert at the API boundary. Kills P-C, P-D.
4. **Scope declaration on every payload** — `item` vs `portfolio`; forbid a per-item payload reading a portfolio master unfiltered. Kills P-B.
5. **Reconciliation rule for twin quantities** — two cards computing "the same" number need a bridge note or a single source. Kills P-E (and closes FIN-4 systemically).
6. **Finish the per-tab pass on the 8 lighter tabs** — Production/Logistics/Console most likely hide local lies (blind spot #2).

---

## Part 6 — Implementation backlog (what to build after compaction)

> Concrete, ordered, each a discrete unit. None require new solver math — they make the existing machine *observable and trustworthy*, which is the whole point of this document.

> **BUILD STATUS (2026-06-05, round 2):** Tier-1 (OBS-1/2/3) + HARNESS-1 **BUILT**. Building them surfaced 6 findings (B-1…B-6) — see **`app_v2/DIRECTION_AFTER_OBSERVABILITY.md`** for the merge + the directed next moves. HARNESS-2 + the §6 lighter-tab pass are **deferred** (spec'd in the DIRECTION doc §4).

**TIER 1 — make the machine self-observable (the actual "observability map" as a feature)**
- [x] **OBS-1 · Live architecture map page** — ✅ **BUILT** (`reference.jsx` `ModelMap`, new **Reference ▸ Model Map** subtab; `lib.jsx` `SolverNetwork` now takes a live `freshness`/`liveObj` prop and colours by `useStale` instead of the seed `status` field — finding **B-2**). Node drill-down = SOLVE_DEPS inputs → `_OBS_METHOD` formula → `_OBS_API` endpoint → last cached result + provenance.
- [x] **OBS-2 · Cross-solver consistency panel** — ✅ **BUILT** (`reference.jsx` `ConsistencyPanel`, same subtab). 5 identities on the live cache (I-5 unit reconcile · I-3 carry=hurdle · #5 MC-on-committed-plan · I-2 bottleneck dual · I-6 pooling), honest "—" when a solve hasn't run. *The full 5-way demand conservation + dual chain need HARNESS-1b (payload fixtures) — they aren't visible from the partial cache (finding **B-3**: only 6/16 solvers persist).*
- [x] **OBS-3 · Provenance lint** — ✅ **BUILT** (`app_v2/tools/provenance_lint.js`; AST walk + `prov-ok:` escape hatch; proven to bite). Found+fixed **B-1** (DemCommit claimed `solved` for hand-overridden/imported demand → now lineage-aware via `COMMIT_PROV`).

**TIER 2 — the named end-to-end harness (the "structured question" as runnable test)**
- [x] **HARNESS-1 · Model-integrity harness** — ✅ **BUILT** (`app_v2/tools/model_check.js`): parse 18 jsx + run the lint + assert all 16 solver endpoints registered + served-bytes — **one smoke replacing the 18 bespoke ones** (4 pass/0 fail). Caught **B-4** on first run (`/api/solve/reconcile` doesn't exist → real route `/api/solve/sop`). *The full golden-path replay (steps 1→12 with the 6 identities) = HARNESS-1b, needs payload fixtures captured from the app — deferred.*
- [ ] **HARNESS-2 · Sub-flow runners** — **DEFERRED** (spec in DIRECTION §4B). In-app `SubflowHarness` (behavioral — needs the real `runScenario` loop): 4 runnable (SF-1/5 demand→planCost, SF-4/2 cost/FX→procCost) + 3 honestly blocked (SF-7 capacity is **B-5** — `prodArch` not in the scenario snapshot; SF-3 finance-only; SF-6 KPI coupling). Groundwork landed: `procCost` added to `_captureKpis` (**B-6**).

**TIER 3 — close the systemic gaps**
- [ ] **GAP-1 · Units contract** (P-C/P-D) — `field-units.md` registry + boundary asserts.
- [ ] **GAP-2 · Scope declaration** (P-B) — `scope:'item'|'portfolio'` on every solver payload + a guard.
- [ ] **GAP-3 · Twin-quantity reconciliation** (P-E) — finish FIN-4 as a pattern (Ke bridge) and apply to any future duplicate.
- [ ] **GAP-4 · Per-tab pass on the 8 lighter tabs** (blind spot #2) — Production, Logistics, Console first (most likely to hide local lies), then Home/Setup/Products/Scenarios/Reference.

**TIER 4 — industry-parity additions (only if the wedge needs them)**
- [ ] Multi-resource aggregate; op-level finite-capacity APS; supplier capacity/allocation; multi-leg transport. *(Defer — these chase parity, not the differentiator; the §7 track argues against feature-chasing.)*

---

### Appendix A — Quick reference: page ⇄ endpoint (verified `grep`, 2026-06-05)
```
setup.jsx      → /api/calc/calendar
demand.jsx     → /api/forecast, /api/demand/sense
products.jsx   → /api/solve/policy
plan.jsx       → /api/solve/aggregate, /api/solve/linecap
production.jsx → /api/solve/production, /api/solve/sequence
sourcing.jsx   → /api/solve/procurement, /rolling, /policy, /meio, /meio-network, /cvar, /api/calc/landed-cost
logistics.jsx  → /api/solve/transport
finance.jsx    → /api/calc/hurdle, /wacc-structure, /npv, /depreciation, /api/solve/capital-capacity
scenarios.jsx  → /api/solve/montecarlo, /cvar, /sensitivity, /api/whatif
console.jsx    → /api/solve/{profitmix,production,procurement,transport,capital,montecarlo}  (mirror)
reference.jsx  → /api/meta/solvers
```

### Appendix B — Engine modules (24) and the curated 16
24 `.py` engines: aggregate, capital, capital_capacity, capital_structure, cvar, disaggregate, finance, forecast, linecap, lot_sizing, meio, meio_network, montecarlo, pattern_sensing, plant_calendar, policy, procurement, production, profitmix, reconcile, report, risk, sequencing, transport. The UI curates **16** as the headline inventory (`M.solvers`, §2.2). 43 Flask routes total (`grep @app.route app.py`).

### Appendix C — How to keep this document honest
Every time a bug is fixed, add its *pattern* to §3.1 (not just the instance). Every time a new card ships, check it against the 6 detectors in §3.1. Every time a solver's input changes, re-run HARNESS-1. This file is the memory of *how we go wrong* — its value is proportional to how ruthlessly §3 is kept current.
