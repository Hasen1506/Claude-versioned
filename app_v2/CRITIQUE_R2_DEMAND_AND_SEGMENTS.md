# app_v2 — Round-2 Domain Critique (demand-led + cross-segment)

Recorded 2026-06-02 in response to the user's second brain-dump. Companion to
[AUDIT.md](AUDIT.md). Every claim below is grounded in a file:line read, not assumed.
Severity: 🔴 correctness/feeds-the-wrong-number · 🟠 capability gap · 🟡 legibility/UX · ⚪ note.

---

## PART A — Demand forecasting, question by question

### A1 · "How does it know past events/promotions and their impact? How do I schedule a future event and have the model react?" 🔴
- **Backend already supports it.** `forecast.py` accepts `promo_periods` in the payload and
  builds a binary `promo` feature into every ML/DL model (`_build_features` line 263,
  `_future_features` line 299), plus a `holiday` feature.
- **Frontend never sends it.** `fcPayload` (demand.jsx:28) sends only `{history, h_periods,
  time_grain, season_length}`. So the live model is **blind to promotions**.
- The **Promotions & Events** card (`DemEvents`, demand.jsx:454) renders `M.promos` and a
  **hardcoded SVG polyline** (line 466, `points="0,45 120,42 180,20…"`) — the lift % is
  decorative and reaches nothing.
- **No future-event scheduler** bound to the forecast horizon. No "I expect a promo in P-7,
  size +30%" → the engine has the hook (`promo_periods` = period indices), but no UI writes it.

### A2 · "MTO: I define xx/yy orders for a period; an order cancels midway — does everything re-update? Should every change be recorded?" 🔴
- **None of this exists.** There is no order entity, no order book, no cancellation event,
  no recompute-on-change cascade, and no audit/event log anywhere in app_v2.
- The Override card (demand.jsx:223) writes a single period's number to committed demand with
  a free-text "reason", but that is **not an event log** and **nothing downstream auto-reruns** —
  the user must manually re-press Run procurement / Solve aggregate, etc.
- "MTO" appears only as a label in ATP ("MTO acceptance"); there is no make-to-order lifecycle.

### A3 · "How do I even see the exact forecast result per period? I can see the graph." 🟡
- Correct — **there is no numeric per-period forecast table.** You get the chart
  (`ForecastChart`), the winner label, and the leaderboard MAPE. The forecast array
  (`fcastArr`) exists and the Override card shows the value for the *one* period you pick,
  but never the full "P1=…, P2=…" readout. The data is in hand; it is simply not surfaced.

### A4 · "Why no ensemble forecast?" 🟠
- `forecast.py` runs a competition and picks **one winner by holdout MAPE.** There is a
  `hybrid` model (HW + ML residuals) but **no true ensemble** (no weighted blend of top-N,
  no stacking). So: not built.
- **"Will ensemble win every time? Do we still need the others?"** No on both. Ensembles need
  enough history and can overfit; on short or intermittent series a single classical model or
  Croston/SBA/TSB routinely beats a blend. The competition + intermittent models are exactly
  what protects the short-data case — an ensemble does not replace them, it sits on top when
  data is deep enough.
- **"Short timeframe of data?"** The engine already degrades gracefully: intermittent models
  are always available; ML/DL are skipped when history is too thin (status noted in the
  leaderboard). But there is **no explicit "you have N points → trust these, not those"**
  guidance beyond the one DATA TIER line.

### A5 · "How does the lifecycle curve affect outputs?" 🔴
- **It does not.** The Lifecycle card (demand.jsx:428) shows `phase → multiplier ×v`, but the
  multiplier is **never applied** to the forecast or committed demand. The code comment is
  honest about it ("it's a choice, not a claim of a fit"). Today it is a pure tag with zero
  downstream effect. Either wire it (multiply the statistical base before commit) or say so.

### A6 · "Override+Schedule in one place, Promotions and Consensus separate — is that proper? What's actually applied / fed?" 🟡🔴
- Three different mechanisms adjust the committed number, shown in two places:
  - **Override** (step 2) — manual per-period edit; **this is the only one that writes** to
    committed demand (`setItemDemand`).
  - **Promotions** (step 5) — per-event lift; **display only, feeds nothing.**
  - **Consensus** (step 5) — cross-functional reconciliation; the "Committed = 13,400" Reading
    (demand.jsx:485) is **hardcoded** and writes nothing.
- So the honest answer to "what gets fed?" is **only the override.** The user's discomfort is
  correct: the arrangement implies three live adjusters; only one is real.
- **Grain mismatch:** the forecast is daily, but Consensus shows a single aggregate number per
  function — not a day/period curve. "Combined consensus for the whole period, not phases/days"
  is a real inconsistency.

### A7 · "ABC/XYZ — would a new user understand what they're looking at?" 🟡
- The 9-box is now derived from real products, with a per-item method-routing list. But the
  leap from "AX cell" → "therefore (s,S) + Holt-Winters, tight review" lives in a single dense
  Reading line. For a newcomer it is **not self-evident**; it needs a plain-language
  "what this means for how you stock and forecast this item."

### A8 · "Is this ready for a user to port their own dataset, auto-segment by date, and other metrics? Should it be programmable? What do we offer that's different? What's missing?" 🔴
- **Not port-ready.** Ingestion is a mock drop-zone — no CSV/XLSX parse, no column mapping,
  no date-column detection, no auto-bucketing by date, no SKU-master reconciliation. The
  "manual" grid edits an uncontrolled `defaultValue` input not wired to state.
- The engine's real levers (promo periods, holidays, season length, grain) are **not exposed
  as import columns or settings** — so even the capability that exists can't be driven by a
  user's data.
- **What's genuinely different (the moat, if wired):** not the forecaster itself — it's the
  **end-to-end chain**: one forecast → committed demand → procurement / production / aggregate
  / finance MILPs on the *same* dataset. Point forecasting tools stop at the forecast. That
  chain is the differentiator, and it is only **partially** wired (demand→procurement/aggregate
  works; promo/landed/actuals don't).
- **Missing vs "lots of forecasting software":** ensemble, event/promo modelling exposed,
  data import, per-period numeric output, accuracy-by-horizon, hierarchical reconciliation
  surfaced (the backend has `reconcile.py` but the UI shows nothing).

---

## PART B — MILP feeds: "what exactly gets fed? is transport / truck capacity in it?"

### B1 · Inbound (procurement) is fed a thin slice; the rich machinery is dormant 🔴
`procurement.py` is a deep model: setup + FG holding + production + expiry + shortage + RM
purchase + RM holding + RM ordering, MOQ, max-order, VMI, **landed_cost per part**, holiday
capacity factor, AND a full transport block (`transport_modes[]`, `transport_contracts[]`,
per-shipment freight, mode selection, disruptions, fill-threshold).

But `bomParts` (store.jsx:196) — the actual payload — sends per part only:
`{name, cost: b.cost (RAW, not landed), qty_per, lead_time, moq, hold_pct,
ordering_cost: 120 (a FLAT constant for every part), scrap_factor, rm_shelf, max_order, rm_capacity}`

Consequences:
- **Customs duty / landed cost is ignored by the order decision.** `SrcLanded` computes a real
  landed cost via `/api/calc/landed-cost`, but it's a standalone worked example — **its result
  is never fed back** into `bomParts`/procurement. (Confirms AUDIT C2.)
- **Ordering cost is a flat ₹120 for every part**, regardless of supplier, lane, or transport.
- **Zero inbound transport awareness.** No freight in the objective, no **truck/container
  capacity**, no FTL/LTL split — so the exact scenario you described ("extra unit needs another
  truck / order cut into FTL+LTL / may be infeasible") is **not modelled inbound**, even though
  the backend can.

### B2 · Outbound (logistics) transport IS wired and truck-aware ✅ (with caveats) 🟡
`transportPayload` (store.jsx:213) sends real `shipments[]` with `weight_kg`, `volume_cbm`,
`value`, `deadline_days`. `transport.py` `MODE_SPECS` encode **truck/container capacity**
(`road_ftl` 3,000–25,000 kg, `sea_fcl_*`, air, etc.) and `consolidate_shipments` **bin-packs
into full loads** and compares all-LTL vs consolidated-FTL — exactly your "cut into FTL+LTL"
case. Logistics renders the real consolidation result.
Caveats: weight is a **flat 3 kg/unit assumption** (`_UNIT_WEIGHT_KG`), flow is **spread evenly
across lanes** (not demand-routed), and it's **one aggregate FG flow, not per-SKU**. The
allocation **matrix** visual (logistics.jsx:79–82) is still a hardcoded `lanes/modes/alloc`
literal even though the KPI blocks beside it read the live solve.

### B3 · "Linking actual sales would help?" — yes, and there's nothing 🔴
MILPs plan to the forecast→committed curve and are **never corrected by actuals.** The backend
has `/api/demand/sense` and `pattern_sensing.py` but **no UI wires it** — no actuals entry,
no forecast-vs-actual variance, no re-plan trigger. (Your SAP-style "enter actuals at day
level, omit Sundays/holidays" point lands here and is unbuilt.)

---

## PART C — Same lens on every other segment

Angles per segment: **[Depth]** big-org modelling honesty · **[Output]** can you read the exact
result · **[Inputs→Outputs]** do inputs actually flow · **[Cards]** grouping/arrangement ·
**[Entry]** if you land here cold, do you know what (which SKU/period) you're looking at.

### C1 · Plan / S&OP (plan.jsx) — the *most* honest tab
- **Depth** 🟢 Real aggregate MILP (level/chase, hire/fire/OT, prebuild, **live shadow prices/
  duals**, SKU disaggregation). This is the reference for what "wired" looks like.
- **Inputs→Outputs** 🟡 Economics (`PLAN_PARAMS`, plan.jsx:8) are **seed placeholders** —
  rates, costs, hire/fire all fixed constants pending a "cost inputs" card. Duals are real but
  rest on assumed costs. The S&OP **Gap** card (`PlanGap`) is **hardcoded** (`M.sop`).
- **Output** 🟢 Capacity table + duals are readable and labelled BINDING/slack.
- **Entry** 🔴 **No item selector**, yet it's a family/aggregate view — fine conceptually, but
  the Strategy "DETECTED/none" and prebuild numbers don't say *which* family or horizon at a glance.

### C2 · Production (production.jsx)
- **Depth** 🟠 Architecture + bottleneck = min(stage) is real and util is now derived. Sequence/
  changeover is a **real solver** (`/api/solve/sequence`). But the **MPS daily split is synthetic**
  (`dq = round(wq/5 + …)`, production.jsx:173) — **not calendar-aware**: no Sunday/holiday
  exclusion, "frozen fence = first 10 days" is hardcoded. `plant_calendar.py` exists and is
  unused here. Line-Load preview (`[60,72,68,80,55,64]`) and **ATP table (`M.mps`/`atp`)** are
  mock.
- **Output** 🟡 MPS is readable by day, but the numbers aren't the production MILP's output —
  they're `weeklyMPS ÷ 5`. ATP "promisable" totals are mock.
- **Inputs→Outputs** 🔴 `/api/solve/production` exists but the **MPS card doesn't call it** — the
  schedule shown is not solved.
- **Entry** 🟢 Has item selector; **but** ProdMPS/ATP show all SKUs (`M.mps`) regardless of the
  selected item — selector and content disagree (AUDIT B-class pattern).

### C3 · Sourcing (sourcing.jsx)
- **Depth** 🟠 Procurement MILP is real and demand-driven; per-part MRP lens is good. But the
  MRP grid itself (`gross=[0,0,1200,…]`, sourcing.jsx:53) is a **synthetic teaching table**; the
  real MILP result is shown in a separate green box below it. Landed/incoterm/transport gaps per B1.
- **Output** 🟢 PO register + shortages render from the live solve when run.
- **Inputs→Outputs** 🔴 Landed cost computed but not fed (B1). Backup-supplier map is a hardcoded
  literal (sourcing.jsx:49).
- **Entry** 🟢 Selector present and the per-part sub-selector is clear.

### C4 · Logistics (logistics.jsx) — see B2. Outbound solve real; allocation matrix + CoG-fallback labels mock; consolidation real.

### C5 · Finance (finance.jsx) — **mostly hardcoded** 🔴
- **Real:** WACC (CAPM→`/api/calc/wacc`), NPV/IRR (`/api/calc/npv`), depreciation
  (`/api/calc/depreciation`). These solve and are labelled.
- **Hardcoded outputs:** Plan NPV `₹11.2 L / −18%`, Investment Decision (CapEx/NPV/IRR/payback
  all literals), Endogenous-capacity duals table, Verdict "APPROVE", Buy-vs-Lease, Per-line CapEx,
  Equity sources, EVM (CPI/SPI/EAC), CCC (52/28/39), FX VaR (`₹2.4 L`, "+₹1.8L"), payment ledger,
  budget variance. The "consolidated total cost per product" you asked for **does not exist** —
  there is no per-SKU fully-loaded cost roll-up here; cost lives as a fake `₹12.64 Cr` waterfall
  in Scenarios.
- **Inputs→Outputs** 🔴 "Plan NPV (MPS-driven)" and "Endogenous-capacity from duals" claim to
  consume the Plan solve but read literals.
- **Entry** 🔴 No selector; sub-tabbed; many SKU-specific-sounding numbers with no SKU anchor.

### C6 · Scenarios (scenarios.jsx) — **almost entirely mock** 🔴
- **Depth/Inputs→Outputs** 🔴 Control tower, tornado, risk matrix, disruption registry, **Lost
  Sales** (`220 u / ₹1.6 L`), **Cost waterfall `₹12.64 Cr`**, **TCO per SKU**, What-If deltas,
  Live Insight, Auto-Researcher, Multi-SKU table — all read `M.*` mock or literals. The Monte
  Carlo / CVaR / what-if **endpoints exist** (`/api/solve/montecarlo`, `/cvar`, `/whatif`,
  `/ai/insights`, `/solve/researcher`) but **none are wired** (cards self-label "preview").
- This is the tab furthest from real, and it's where your "Monte Carlo needs distributions"
  blocker (AUDIT) bites — no per-input distributions exist to simulate over.

---

## PART D — The five recurring patterns (the meta-findings)

1. **Backend richer than the payload.** The solvers model promo regressors, landed cost,
   inbound transport + truck capacity, demand sensing, Monte Carlo, CVaR, reconciliation,
   production scheduling — and the frontend sends a thin slice or doesn't call them. The
   work is mostly *wiring*, not *building*. (forecast promo, procurement landed/transport,
   /demand/sense, scenarios/* all idle.)
2. **Hardcoded outputs sit beside live ones**, visually identical. Finance and Scenarios are
   the worst; the risk is a user trusting a fabricated number that looks solved. (Provenance
   badges help where present but aren't everywhere.)
3. **Grain mismatch across the chain.** Forecast = daily; Consensus = one aggregate; MPS day-
   split = weekly÷5 (not calendar-aware); Plan = monthly. Nothing enforces a consistent
   calendar, and Sundays/holidays are excluded **nowhere** despite `plant_calendar.py`.
4. **Entry-point ambiguity.** Plan, Finance, Scenarios have **no item selector** but show
   SKU-shaped numbers; Production/Sourcing **have** a selector that some cards ignore. A user
   landing cold often can't tell *which product / which period / as-of when* they're reading.
5. **No actuals, no event log, no recompute cascade.** Nothing records changes, nothing
   reconciles forecast vs actual, nothing re-solves automatically when an input (override,
   cancellation, cost) changes. This blocks MTO order-cancellation, demand sensing, and any
   audit trail.

## Suggested sequencing (for when we move from record → fix)
- **P3a Demand depth:** send `promo_periods` + holidays from a real promo calendar; add a
  per-period numeric forecast table; make the lifecycle multiplier actually multiply; add an
  ensemble (top-N MAPE-weighted blend) gated on data depth; collapse override/promo/consensus
  into one "what's committed and why" panel at one grain.
- **P3b Procurement truth:** feed `landed_cost` (from the landed solver) + `transport_modes`/
  `transport_contracts` into `bomParts`; replace flat ₹120 ordering cost; surface inbound
  truck/FTL-LTL like outbound already does.
- **P4 Calendar bridge:** real working-day MPS (exclude Sundays/holidays via `plant_calendar`).
- **P5 De-fake Finance + Scenarios:** wire NPV-from-plan, duals-from-aggregate, Monte Carlo/
  CVaR/what-if; build the consolidated per-SKU fully-loaded cost roll-up the user asked for.
- **Cross-cutting:** actuals entry + forecast-vs-actual + recompute trigger + change log;
  consistent item-selector/as-of header on every stage.

---

## PART E — Round-2b: S&OP / Production / solver-formulation (added 2026-06-02, batch 2)

Grounded in reads of `aggregate.py`, `production.py`, and `procurement.py` (1923 lines).

### E1 · S&OP shows capacity you haven't defined yet 🟠🟡
Plan (stage 05) renders a capacity table/chart, but capacity is *defined* later in Production
(stage 06). Worse, the two aren't the same object: the aggregate solver's "capacity" is
**labor** (`rate_per_worker × workforce`, from `PLAN_PARAMS` seed constants, plan.jsx:8) — it
does **not** read the line registry the user fills in on Production. So a user defines lines in
06 and the 05 capacity number never reflects them. Define-before-display + two disconnected
capacity models.

### E2 · Capacity **shadow prices** — what they really are 🔴 (answers the user's question directly)
The duals are **output of the AGGREGATE (S&OP) solver**, not the production solver.
`aggregate.py:172` names the rows `Regular capacity P{t+1}` from `P_t ≤ rate · W_t`, and
`shadow_prices` is the marginal value of **one more worker-period**. Consequences:
- The user's instinct ("did I ever define the lines?") is right to be confused — **the shadow
  price is on labor capacity, computed from seed `PLAN_PARAMS`, with zero connection to the
  lines/stages defined in Production.** It is triggered by **Solve Aggregate**, needs a forecast
  + workforce/cost params, and is a real LP dual — but it does **not** price the line capacity
  the Finance tab then claims to "invest against."
- So "invest against this dual → Heat-Treat #2" (the Finance hand-off) is **conceptually
  mis-wired**: a labor dual is being used to justify a machine-line CapEx.

### E3 · Workforce plan — purpose + period-awareness 🟡
It **is** period-aware: `PlanWorkforce` maps `res.periods` to per-period base heads / hire /
fire / OT (plan.jsx:166). What's missing is **actionability and linkage**: it's a labor-
headcount plan disconnected from the line/stage labor in Production (C2) and from any cost the
user can edit. A new user can't tell what to *do* with "+3 hires in P2" — there's no "this
covers the P2 capacity gap on Line-X" tie-back.

### E4 · SKU disaggregation — legibility 🟡
`PlanDisagg` does derive the split from the solver's `sku_plans` when solved (plan.jsx:201).
But it never says **which family** is being split or **over what horizon**, and the mock
fallback (`familyQty=13400`) looks identical to a real solve. "What product's plan am I looking
at" is genuinely unclear — needs a family/SKU/horizon header and a solved-vs-seed marker.

### E5 · Production solver output — it already exists, just unwired 🔴 (answers the user's question)
`production.py` (`/api/solve/production`) already returns exactly the per-line/per-SKU view the
user wants: **`gantt[]` (Gantt blocks), `sequence_plans[]` (run order per line via
`sequencing.py`), utilization, and a low-util line-shutdown recommendation.** But **app_v2 never
calls it** — `ProdMPS` synthesizes `weeklyMPS ÷ 5` and the console Gantt is illustrative. So the
"separate proper output view per SKU/line" is a **wiring** job, not a build. The right output
shape: per-line swimlanes, each a sequence of SKU run-blocks with start/end periods + qty, plus
a per-SKU filter — which is what `gantt[]` already encodes.

### E6 · Campaign / run-length vs holding-cost tradeoff 🟠 (answers the user's question)
The user's "bulk-produce one SKU for a long run, then switch" vs "switch often" tension **is
already in the math**: high `setup_cost`(y) pushes toward long campaigns; `fg_hold × inv`
penalizes the finished-goods build-up those long runs create — that setup-vs-holding balance is
the classic lot-sizing tradeoff and the MILP optimizes it. `production.py` adds sequence-
dependent changeover on top. **What's missing:** (a) no exposed **min-run-length / campaign**
lever, (b) the tradeoff is never *explained* on screen (a planner can't see "we run AAAA then
BBBB because changeover ₹ > holding ₹"), (c) build-up-vs-demand risk (over-building a short-
shelf SKU) is modeled (FIFO expiry + shelf life) but those inputs aren't user-editable in v2.
So: modeled, not surfaced, not steerable.

### E7 · Drill-down grain for the production/plan output 🟡
The user wants monthly → (click) weekly → (click) daily-with-exact-dates. Today: Plan is
monthly only; MPS has a day/week toggle but day = weekly÷5 (not calendar-dated, no real dates,
no Sunday/holiday exclusion). The backend supports `time_grain` + `holidays` + `horizon_start_date`
(procurement.py:270 `period_factor`), so dated, holiday-aware buckets are achievable — unwired.

### E8 · Procurement formulation — verification verdict 🟢/🟠
**Read in full. It is a correct, linear, capacitated lot-sizing MILP (CLSP + MRP), solved by
CBC via PuLP.** Specifics:
- **Decision vars:** `p[k,t]` production (int, 0..cap), `inv[k,t]` FG (cont ≥0), `short[k,t]`
  (cont ≥0), `y[k,t]` production setup (binary), `r[g,t]` RM order (int), `o[g,t]` order
  (binary), `rm_inv[g,t]` RM (cont ≥0), `expire[k,t]` spoilage; auxiliaries: tier-select
  binaries, `r_seg` (McCormick), `eff_charge` (freight), `pflat` (period-flat fee), lead-time-
  band sub-vars, MEIO `inv_node`/`transfer`/`short_node`.
- **Objective (min):** setup + variable production + FG holding + shortage penalty (sell×1.5) +
  RM purchase (volume/transport-tiered) + ordering admin + RM holding + freight + flat-periodic
  + SS-floor penalty + salvage-adjusted spoilage write-off + fixed overhead.
- **Core constraints:** inventory balance (C1), FIFO perishability (C1b, Nahmias), capacity with
  holiday + maintenance derate (C2), min-production (C3), warehouse (C4), no-backorder (C5), MTO
  no-build ceiling, SS floor (soft/hard), RM material balance with lead-time receipt lag, MOQ /
  max-order, RM cap, working capital, budget, plus gated MEIO multi-echelon, labor, CO₂, FX,
  supplier-concentration.
- **Linear or nonlinear?** **Linear MILP.** Genuinely nonlinear pieces are pre-resolved or
  linearized: the bilinear qty×tier-cost is McCormick/big-M'd (`r_seg` with the four bounds,
  procurement.py:705), tier choice via exactly-one binaries, min-charge via two-lower-bound
  `eff_charge`, and the √ in safety stock (z·σ_LTD) is **computed in Python before the LP** so it
  enters as a constant, not a variable. No nonlinear terms reach the solver.
- **Is it correct / how big orgs do it?** Structurally yes — CLSP with setup binaries +
  multi-period inventory + capacity is the textbook master-planning model (SAP IBP / Kinaxis /
  o9 / Blue Yonder do this class). SS via z·σ_LTD (Heizer/King), ABC-XYZ service differentiation,
  CVaR-robust SS, FIFO perishability are all legitimate OR methods. Evidence of real auditing
  (the `Audit #0/#1/#2` fixes, e.g. the MEIO `short_node` fix preventing forced full demand
  satisfaction).
- **Over-defined?** Not *mathematically* (every advanced subsystem is gated behind a falsy
  default, so the active model stays well-posed). But it is **heavily over-scoped**: ~1923 lines,
  30+ optional subsystems (MEIO, lead-time bands, 5 transport-rate bases, regime-aware HMM
  sourcing, CVaR SS, in-transit WC, milk-run, replan anchor, terminal anchor…), and **app_v2
  feeds essentially none of them** (`bomParts` sends 11 fields, flat ₹120 ord-cost, raw cost).
  The risk isn't infeasibility; it's a monolith whose capability is invisible and unmaintainable
  relative to what the UI lets a user drive.
- **Are inputs placed where a user can define them?** **No — this is the real gap.** Service
  level, ABC/XYZ class, shelf life, salvage, MOQ, lead time, carry rate, fill-rate target/mode,
  SS mode/source, transport contracts, working capital, budget are all solver params with
  sensible defaults, but app_v2 exposes almost none of them as editable inputs. The formulation
  is big-org-grade; the **input surface is missing**, so the user can't actually use the depth.

**Net:** the math is sound and ambitious; the work is to (a) wire `/api/solve/production` for the
real Gantt, (b) expose a governed input surface for the procurement levers, (c) reconcile the
labor-dual-vs-line-CapEx mismatch (E2), and (d) decide how much of the 30-subsystem scope this
product actually needs vs. trims.

---

## PART F — Round-2c: profit-mix, stochastic risk, capital decisions (batch 3, 2026-06-02)

Grounded in full reads of `profitmix.py`, `cvar.py`, `montecarlo.py`, `capital_capacity.py`.
**Headline: the backend already implements the decision architecture the user is describing.**
The gaps are integration (separate solvers, not one) + wiring (app_v2 calls almost none) +
honesty (one docstring overclaims).

### F1 · Stochastic risk — how to avoid the costly stochastic-MILP (answers the user directly) 🟢/🟠
The user is right that a full scenario-based stochastic MILP (binaries × demand-CV × LT-CV
scenarios) is expensive. The backend **already uses the standard decomposition instead of brute
force**, in three cooperating pieces:
1. **Monte Carlo (`montecarlo.py`) = DESCRIPTIVE.** Simulates the *committed* plan (GAP-1: it
   replays the MILP's production schedule, not a re-derived policy) under correlated demand+cost
   shocks (Cholesky ρ, default 0.4) with FIFO perishability, and reports the **cost distribution,
   VaR95, CVaR95, fragility, fill-rate distribution**. This is "information to digest" — exactly
   the user's framing. It does NOT prescribe; it stress-reports a chosen plan.
2. **CVaR LP (`cvar.py`) = PRESCRIPTIVE, and cheap.** Rockafellar–Uryasev CVaR is a *single small
   LP* (no scenario binaries) that returns the β-tail-optimal order-up-to and a **CVaR-robust
   safety stock = Q* − mean**. `solve_cvar` even returns **`robustness_premium_units`** — literally
   "hold THIS many more units than the expected-value plan to protect the worst-(1−β) tail." This
   is the actionable "hold more" answer: higher holding cost, but the tail shortage penalty it
   removes is larger, so net cost drops. **This is the answer to "does stochastic give useful
   info like hold-more" — yes, quantified.**
3. **Deterministic MILP plans against the robust floor.** `procurement.py ss_source='cvar'` takes
   the CVaR safety stock as the inventory floor, so the cheap deterministic solve is *robust by
   construction* — no combinatorial blow-up.
- **"Worst of extremes?"** Planning to the *absolute* worst (worst demand-CV ∧ worst LT-CV
   simultaneously) is over-conservative and paralysing. CVaR_95 = average over the **worst 5%**,
   which is the right target — protective without being absurd. So: don't plan to the max; plan to
   the CVaR.
- 🟠 **Honesty gap:** `montecarlo.py`'s docstring claims it randomizes **lead times**, but the
   sim loop samples only demand + cost (no LT draw). LT-CV is NOT simulated. Fix the code or the
   docstring.

### F2 · Profit-mix — verified; this IS the capacity-constrained mix optimizer 🟢 (answers the user)
`profitmix.py` is a **true LP** (`LpMaximize`, CBC) that is precisely the user's 2-product/2-line
example: per-SKU `q[k]`, per-line allocation `x[k,l]` with eligibility (what can be made where),
shared OR per-line capacity in **machine-hours**, OEE derate, and **margin/hour as the ranked
metric** (results sorted by margin/hr). It correctly captures "don't chase the high-unit-margin
SKU if its cycle time eats the bottleneck." It emits:
- **Shadow prices** (constraint duals) — the marginal value of the binding bottleneck (line-hours,
  budget, material, warehouse).
- **Crossover analysis** — for each *excluded* SKU, the exact price at which it would enter the
  mix → "what to prioritise next."
- **Reduced costs / range-of-optimality**, a **±MAPE robustness band**, cannibalization-aware
  ceilings, and a **fixed-charge line-opening binary** (so it's a MILP when a line has a one-time
  open cost).
- **Seller case (no manufacturing):** send no capacity/cycle; the binding constraint becomes
  **budget / warehouse / material / transport**, and the LP still picks the mix — "what to sell on
  a limited budget against demand ceilings" = max margin per binding-resource unit (the dual). So
  the same engine serves pure sellers; the only difference is which constraint binds. ✅ answers
  "for just sellers… what to prioritise."
- **Economies of scale / loose capacity:** when nothing binds (all shadow prices 0 / slack), every
  profitable SKU is made to its ceiling — the LP shows this naturally; that's the signal that the
  constraint isn't capacity but demand, and growth/marketing (not scheduling) is the lever.
- 🔴 **app_v2 wiring:** the Profit-mix tab sends a thin payload; line allocation, crossover,
  duals, labor modes are mostly unsurfaced.

### F3 · "Who decides hire vs machine vs OT, and is the ₹X machine worth it?" 🟠 (answers the user)
There is a dedicated solver: **`capital_capacity.py`** — a multi-period 0/1 MILP that picks **which**
capacity option (new line/shift/machine) and **when** (within each option's earliest/latest window)
under **budget rollover**, maximising portfolio **NPV**, and reports **NPV, IRR, payback schedule,
and a risk-adjusted NPV** (MC perturbs margin/hour & utilisation → **P(NPV<0)**). Crucially its
**endogenous capacity** values a machine by the throughput it unlocks: annual CF = `capacity_hours
× margin_per_hour × utilisation − opex`, where **`margin_per_hour` defaults to the capacity shadow
price** handed up from profit-mix/aggregate. So the decision chain is real:
`profit-mix/aggregate → bottleneck dual → capital_capacity → invest & when`.
- **The gap:** hire/OT/machine are in **three separate models** — OT + hire/fire in `aggregate.py`
  (period-resolved S&OP), labor cost in `profitmix.py`, machine CapEx in `capital_capacity.py`.
  **No single solver compares "₹X on a machine vs N hires vs OT hours" head-to-head.** That
  comparison today requires reading the aggregate plan's OT/hire cost against capital_capacity's
  machine NPV by hand. A unified "capacity-step" decision (or at least a side-by-side) is the
  missing integration. This also ties back to **E2** (the dual driving capital is currently the
  *labor* dual from aggregate, not a line/machine dual).
- 🔴 **app_v2 wiring:** `/api/solve/capital-capacity` exists; Finance shows hardcoded Investment
  numbers instead.

### F4 · Schedule extension / "last order shouldn't be too small but correct" 🟢 (answers the user)
This is already modelled in `procurement.py` (the logic the user remembers from index.html):
- **Horizon buffer / time fence (R10 Bucket 3):** solve over `effective_periods > committed_periods`
  so the MILP "sees" demand beyond the committed window, then **zero the buffer-window POs in the
  output** → kills the end-of-horizon distortion where cost-min drives the final order to a tiny
  sliver because ending inventory wants to be 0.
- **`terminal_anchor_units`:** forces ending RM ≥ SS + LT·avg-demand, so the horizon doesn't end
  empty.
- **`min_coverage_periods`:** forces each PO ≥ avg-demand × min_coverage — suppresses tiny
  tail-end orders. **This is exactly "last order shouldn't be too small."**
So "if my period is only 3 months, the last order is sized correctly" is solved by
`min_coverage` + `terminal_anchor` + `horizon_buffer`. 🔴 app_v2 sends none of these params → the
distortion is live in v2. Wire them + expose a "time fence / coverage" input.

### F5 · Cycle time simplified vs OEE — already optional 🟢
Both `profitmix.py` and `production.py` treat **OEE as OPTIONAL** ("Both fields are OPTIONAL"),
and `ProdCycle` already has an OEE/FLAT toggle. The user's ask (simple cycle-time default, OEE as
advanced) is the existing design intent — it just needs to be the clear **default** with OEE
behind "Advanced," not co-equal.

### F6 · Lines / shared capacity / labor / bottleneck — how it's modelled (answers the user) 🟢/🟠
- **What gets made where:** `profitmix.py` `x[k,l]` with per-line `eligible_skus` — the LP assigns
  each SKU to eligible lines; **shared capacity** = the line-hours constraint shared across SKUs,
  so a contended line forces the margin/hr trade-off. ✅
- **Worker count / salary / hiring:** split across models — `profitmix` carries labor-cost modes
  (`per_unit` / `hourly` line-wage / `salaried_idle` envelope) + an org headcount-hours cap;
  `aggregate.py` carries the period-resolved **hire / fire / overtime** plan. Hiring *decisions*
  live in S&OP (aggregate); labor *costing* in profit-mix. (Integration gap per F3.)
- **Bottleneck stage:** `production.py` sets line throughput = **min(stage throughput)** — so
  "define each stage to find the bottleneck" is exactly the model; the slowest stage caps the line
  and is what the capacity dual prices.

### F7 · Recurring (extends Part D): the decision solvers exist but are siloed + unwired
The advanced decision layer (profit-mix LP, capital-capacity MILP, CVaR LP, Monte Carlo) is built
and individually correct, but (a) **siloed** — no orchestration that runs mix → dual → capital →
risk as one flow; (b) **mostly unwired** in app_v2 (Profit-mix thin, Scenarios all mock,
capital-capacity uncalled); (c) one **overclaiming docstring** (montecarlo LT). The build work is
orchestration + wiring + input surface, not new math.

---

## PART G — Round-2d: Finance / capital-structure / hurdle-rate (batch 4, 2026-06-02)

Grounded in full reads of `finance.py` (calc_wacc / calc_npv / calc_depreciation / landed) and
`capital.py`. **This is the batch where the backend is genuinely THIN** — most of what the user
wants is a real build, not just wiring. The user's reasoning is correct and points at a clean
seven-piece expansion.

### G1 · Capital-structure optimizer (min-WACC mix) — NOT built 🔴 (the user's "main step")
`finance.py:calc_wacc` only **computes** WACC from given weights (`e·re + d·rd·(1−t)`). It does
**not** optimise the equity/debt mix. The owner's question — "what mix minimises my WACC" — needs
a new model: WACC is U-shaped in leverage (debt's tax shield lowers WACC at first; past a point
financial-distress risk raises both Kd and Ke, and DSCR covenants cap debt), so there's a trough.
Build = sweep debt% 0→cap, raise Kd with leverage, re-lever β (Hamada) to raise Ke, respect the
DSCR cap (G6), pick the minimum-WACC point. **This is the structural centrepiece.**

### G2 · Source-weighted cost of equity + the opportunity-cost / land example 🔴 (the crux)
The user's land example is exactly right and the backend doesn't model it: if an equity tranche is
funded by liquidating land compounding at 7–10%, **that 7–10% IS the cost of that tranche** (the
foregone return), not CAPM. The true hurdle rate = WACC built from **source-weighted** equity
(land-opportunity-cost · retained-Ke(CAPM) · promoter · PE) and **source-weighted** debt
(bank-rate · family-rate). If a project returns 8% but the liquidated land would have grown 10%,
value was **destroyed** even though accounting profit is positive. `finance.jsx` has an "Equity
Sources & Opportunity Cost" card (Retained 14.2 / Promoter 12 / PE 18%) but it's **hardcoded and
never blended into Ke**. Build = editable equity/debt tranches, each with its own cost → blended
Ke → WACC → the owner's real hurdle. **This + G1 is "the main step: what hurdle must I beat, and
how much revenue do I need."**

### G3 · Hurdle scoreboard: EVA / ROIC vs WACC → consolidate/shutdown trigger 🔴
The user's "when do I see I'm not crossing my hurdle and should shut down or inject new products"
is **EVA**: `EVA = NOPAT − WACC × invested_capital`; equivalently flag when `ROIC < WACC`. Backend
computes **none** of this (no NOPAT, ROIC, or EVA anywhere). `production.py` has a *low-utilisation*
shutdown heuristic, but not the *strategic* "this product/unit destroys value vs the hurdle" call.
Build = a per-SKU / per-unit / consolidated ROIC-vs-WACC panel that flags value-destroyers and
routes them to {fix margin · drop · new customers · new products}. This is the "this year we made
8% on our capital, here's whether that beats the hurdle and what to do" view.

### G4 · "You must generate ₹X more sales" — the required-sales bridge 🟠 (answers the user)
Yes, computable, and it's the **inverse** of the hurdle: required incremental NOPAT =
`(WACC − current ROIC) × invested_capital`; required Δsales = `ΔNOPAT / blended_contribution_margin`.
Because each SKU has its own margin, the user's "combined slider of all SKUs" intuition is exactly
the right UI — either a blended portfolio margin or per-SKU sliders that roll up to the target, and
the **mix matters** (hitting it via high-margin SKUs needs less volume). This connects directly to
`profit-mix` (which already finds the margin-maximising mix) — so the bridge is: hurdle gap →
required ΔNOPAT → profit-mix tells you which SKUs to grow to get there. Not built; high value.

### G5 · Product-economics segmentation (manufactured vs resale vs light-processing) 🟠
The user is right that industries differ. Model = a per-SKU **cost-to-serve type**:
(a) *manufactured* → BOM + conversion (procurement/production margin), (b) *pure resale* → buy +
landed + handling, (c) *light-processing/kitting* → buy + value-add. `profit-mix` already computes
`margin = sell − var_cost − mat_cost − labor`; the type only changes how cost is built. So segment
each SKU by procurement type, compute its margin, roll up to the portfolio margin that feeds G4.
A clean "product economics" layer, currently absent.

### G6 · Debt sources + DSCR covenant 🟠 (answers the user)
Banks **do** require **DSCR** (typically ≥ 1.2–1.5) and often a **DSRA** (debt-service reserve,
~1–2 quarters); family/promoter debt usually doesn't. So debt is **source-weighted** (rate +
covenant) just like equity. `finance.py:calc_npv` already **returns DSCR** = NOI / debt_service —
but only as a reported ratio, **not enforced** and **not linked** to structure. It interlinks
exactly where the user suspected: a DSCR ≥ 1.5 covenant **caps how much debt the cash flows can
service → caps leverage → constrains the G1 min-WACC mix**, and sets a floor on required earnings
(ties to G4). Build = DSCR as a constraint on max debt + DSRA as a reserve in working capital.

### G7 · Tax + depreciation shield 🟡; and investment appraisal (already built) 🟢
- **Depreciation** exists (`calc_depreciation`: SLM / WDV / UoP). **Tax** is only the WACC shield
  `Kd·(1−t)`. Add a tax section: effective tax / MAT, the **depreciation tax shield** feeding NPV
  cash flows, and WDV-vs-book deferred-tax timing. Depreciation belongs in Finance for both the
  asset register and the shield. So: yes, put tax in Finance.
- **"Is buying an asset for ₹X worth it?"** — already answered by `capital.py` + `capital_capacity.py`:
  **NPV** (>0 invest), **IRR** (vs WACC hurdle), **payback** (simple + discounted), **profitability
  index** (NPV/capex + 1), budget dual (from the LP relaxation), and risk-adjusted NPV (P(NPV<0)).
  Decision rule: NPV>0 ∧ IRR>WACC ∧ payback ≤ tolerance ∧ (for capacity) the bottleneck dual
  justifies it ∧ (if debt-funded) DSCR holds. Built; needs wiring + buy-vs-lease.

### G-summary · Finance structural expansion order
B/G2 (source-weighted hurdle) → A/G1 (min-WACC mix, DSCR-capped) → G4 (required-sales bridge,
mix slider) → G3 (EVA/ROIC scoreboard → shutdown/pivot) → G5 (product-economics types) →
G6 (DSCR covenant + DSRA) → G7 (tax shield). Appraisal (NPV/IRR/payback/PI) already exists — wire
it. This sequence delivers the owner's loop: **real hurdle → revenue target → are we beating it →
what to do.**

---

## PART H — Round-2e: remaining Finance cards + inventory-policy / replan / demand-sensing (batch 5)

### H1 · Remaining Finance sections — card-by-card (real vs mock)
Finance subtabs (finance.jsx). **Real/wired:** WACC (`/api/calc/wacc`), NPV-IRR (`/api/calc/npv`),
Depreciation (`/api/calc/depreciation`), FX rate table (editable single-source). **Everything else
is mock**, despite backends existing to power it:
- **Cash subtab — 100% mock.** Working-Capital bars (`M.cashflow`), Payment Ledger (hardcoded
  rows), Budget-vs-Actual (hardcoded), **EVM** (`M.evm` — CPI/SPI/EAC are real concepts on fake
  numbers), **CCC** (hardcoded 52/28/39). 🔴 No provenance → a planner can't tell these aren't solved.
- **Capital subtab — half real.** WACC + NPV/IRR solve ✅. Cap Structure (₹9.3Cr/5.7Cr hardcoded),
  **Plan NPV "MPS-driven"** (reads a literal ₹11.2L — claims endogeneity it doesn't have 🔴).
- **Invest subtab — mock, and this is the painful one.** Investment Decision (hardcoded LINE-03),
  **Endogenous-Capacity "from duals"** (hardcoded table — yet `capital_capacity.py` exists and
  produces exactly this 🔴), Verdict (hardcoded APPROVE), Cash-Flow Builder (from `M.npv`),
  **Equity Sources & Opportunity Cost** (hardcoded — this is the G2 hurdle card, inert), Per-line
  CapEx (hardcoded), Buy-vs-Lease (hardcoded). `/api/solve/capital` + `/api/solve/capital-capacity`
  are both unused.
- **Assets subtab — real.** Register roll-up + Depreciation solve ✅.
- **FX subtab — mixed.** Rate table real/editable ✅; Hedging (`M.fxHedge`) + **Procurement VaR
  ₹2.4L** mock (montecarlo.py could power it). 
- **DSCR:** `calc_npv` already returns it; **no Finance card surfaces it** (ties to G6).
- **Angles:** Output 🔴 mock-looks-solved (no provenance on EVM/CCC/VaR); Inputs→Outputs — the
  WACC→NPV chain is genuinely live (good template), but Investment/duals claim Plan/aggregate
  coupling they fake; Entry 🔴 no item selector under SKU-shaped numbers (Plan NPV, per-line CapEx).

### H2 · Inventory policy vs the MILP schedule — the user's core confusion, resolved 🟢
Both exist and are complementary; the docstrings say it outright:
- **Procurement MILP** = the **cost-optimal PO schedule for the *expected* (forecast) demand** over
  a fixed horizon. A frozen plan. The "predicted demand" the user noticed *is* the committed
  forecast it plans against.
- **`policy.py`** derives, per part, the **executable reorder policy**: EOQ `Q*=√(2DK/h)`, safety
  stock `ss=z·σ_LTD`, reorder point `s=μ_L+ss`, **order-up-to `S=s+Q*`**, and recommends **(s,S)
  continuous** for lumpy parts vs **(R,Q) periodic** for steady movers. Its own docstring: *"Procurement
  returns a fixed-horizon PO schedule. Planners don't run a frozen 26-week plan — they run a reorder
  POLICY."*
- **`lot_sizing.py`** has **13 policies** (LFL, EOQ, FOQ, POQ, MIN_MAX=(s,S), EPQ, **Wagner-Whitin**
  DP-optimal, Silver-Meal, PPB, LUC, LTC, JIT, Kanban) + `auto_select` picks the cheapest.
- **The relationship (the answer):** the MILP gives the *optimal plan*; the *policy* (order-up-to S)
  is the *rule you execute* so you don't re-solve on every demand wiggle — when inventory position
  hits `s`, order up to `S`. The two are reconciled by **rolling re-solve** (`/api/solve/rolling`):
  freeze the first `frozen_weeks`, slide the horizon forward, re-solve each wave, and measure
  **nervousness** (plan churn). A good policy keeps nervousness low as the forecast tail reveals.

### H3 · Actuals, demand sensing, and re-plan triggers 🟠 (answers the user)
- **Where actuals enter:** `/api/demand/sense` → `pattern_sensing.py` (SAP-IBP style). It takes
  recent **actuals** + the baseline forecast, **matches a pattern** (promo / holiday ramp / weekend
  dip / post-outage bounce / trend-break / cannibalization via cosine similarity), produces a
  **sensed** forecast for weeks 0–6, **blends** to statistical for 7+, and **propagates posterior
  variance → an amplified SS multiplier** (`z·(1+cv)`). Built; **unwired in app_v2**.
- **The trigger logic the user wants (MAPE breach 1.5–2×, or consistent bias over N periods) is
  NOT built.** That governance layer — monitor rolling MAPE & tracking-signal bias, fire a re-sense
  /re-forecast/re-solve when breached — is a genuine gap. pattern_sensing gives the *sensing*; the
  *when-to-act* monitor is missing.
- **MTO + rolling + surprise orders:** the architecture supports it — `procurement.py` has
  `replan_from_period` + `actuals_override` (lock committed/released periods, re-solve forward) and
  `locked_pos` (already-released POs become scheduled receipts). So a surprise order = add to demand
  /order-book → lock what's frozen → re-solve forward. Small deviations are absorbed by the
  order-up-to policy without re-solving; big ones trigger a rolling re-plan.

### H4 · "Do we rerun ALL solvers when forecast/period changes?" 🟠 (answers the user)
No — only the **dependency chain downstream of the changed input.** Forecast change → committed
demand → re-solve procurement / production / aggregate / profit-mix (the demand consumers). Horizon
/period change → everything horizon-parameterised. **There is no orchestration / dependency graph
today** (the Part-D "no recompute cascade" finding) — each tab is re-run by hand. Building a
declared dependency DAG (input → affected solvers) is the fix, and it also answers "what gets
re-run."

### H5 · Postponable vs non-postponable orders 🟡 (answers the user)
The MILP already releases each PO **as late as feasible** (JIT — release = need − lead time). An
order's **postponability = the slack on its release-timing**: long-lead / binding-capacity parts
are pinned; short-lead / slack parts are flexible. The information exists in the solve (timing
slack) but **isn't surfaced** — a "pinned vs flexible" flag per PO would directly answer "which of
these can I push."

### H6 · MEIO safety stock across RM / WIP / FG 🔴 (answers the user)
`procurement.py` has per-node FG inventory + lane transfers (MEIO **balance**), and single-echelon
SS exists (policy.py / cvar.py / Heizer z·σ_LTD). But **true multi-echelon SS *placement*** — how
much buffer to hold at RM vs WIP vs FG so the *network* hits service at min cost (Graves–Willems
guaranteed-service / Clark–Scarf) — is **NOT modelled.** WIP isn't stocked at all. So "we have SS
formulas separately, how do we wire them across echelons" = build a guaranteed-service MEIO layer
that places SS by echelon; the per-node balance is the scaffold, the placement optimizer is the gap.

### H7 · Costly low-volume items (transformers) + "how much excess to buy" 🟢 (answers the user)
For expensive MTO items you **don't hold FG safety stock** (holding a transformer is ruinous) — you
make-to-order (`demand_mode='mto'`: `inv ≤ ss` ceiling, production tracks demand). The "how much
excess component to buy" question **is exactly the newsvendor** (`cvar.py`): overage cost `h`
(holding a costly core) vs underage cost `p` (lost order / penalty / **user willingness to risk a
stockout**). High unit cost → high `h` → low order-up-to → near-zero buffer, buy on confirmation.
So: cost AND willingness, formalised as `h` vs `p` in the CVaR newsvendor. ✅ the engine is right;
it just needs the MTO/costly-item preset exposed.

### H8 · Sequence-dependent setup A→B ≠ B→A — is it correct? 🟢 (answers the user)
Yes. `sequencing.py` treats the changeover matrix as **asymmetric** ("A→B ≠ B→A") and finds the
**shortest open Hamiltonian path** (open ATSP) — *exact* for ≤8 SKUs (permutation), nearest-
neighbour + reinsertion above. Note the **two-stage design**: the production MILP charges changeover
as `switch_count × mean(matrix)` to stay linear, then `sequencing.py` runs **post-solve** to compute
the true asymmetric optimum + the run order + the saving vs the averaged approximation. Correct and
honest; just unsurfaced in app_v2 beyond the changeover card.

### H9 · "What's the point of a stochastic MILP if SS already handles demand/LT variability?" 🟢 (the key answer)
The user's instinct is right — **for most cases you don't need a full stochastic MILP.** The
practical, industry-standard stack is: **deterministic MILP** (optimal plan for expected demand) +
**a robust SS floor** (z·σ_LTD, or the CVaR floor for the tail) + **rolling re-solve** as actuals
arrive + **demand sensing** to correct the near-term. That captures ~all the value cheaply. A
scenario-based stochastic MILP (binaries × demand-CV × LT-CV scenarios) is expensive and only earns
its keep when risk interactions are non-separable and the buffer-then-replan loop genuinely can't
cope — rare. So: SS = cheap local buffer; CVaR = cheap tail-robust buffer; rolling re-solve = the
feedback loop; stochastic MILP = the expensive last resort you usually skip. **Don't build the
stochastic MILP by default.**
</content>
</invoke>
