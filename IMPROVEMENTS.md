# IMPROVEMENTS — Structural / Methodology Roadmap (Round 16)

Owner: Hasen · Auditor role: supply-chain + OR domain expert
Opened: 2026-05-29

**This is NOT the bug register** — see [MUST_FIX.md](MUST_FIX.md) for verified defects.
This file lists places where a segment *works as built* but a better-practice
modeling approach exists, or where a whole component is missing from the
start→end chain. Each item separates the **factual premise** (verified against
code, file:line) from the **design judgment** (my recommendation, which is
debatable). Effort/leverage is my estimate.

Legend: 🟩 verified premise · ⚖️ design judgment · ⭐ highest leverage

---

## ⭐ GAP-0 · The missing middle tier: Aggregate Planning / S&OP — ✅ IMPLEMENTED (R20)
- ✅ **Built (R20):** new [aggregate.py](aggregate.py) — Hax–Meal multi-period LP over 12 monthly
  buckets × {regular, overtime, hire/fire, inventory carry, backorder}. Endpoint
  `/api/solve/aggregate` ([app.py](app.py)); new **Aggregate Plan / S&OP** tab (`3B`) in index.html
  driving level-vs-chase with a derived-default lever form. Emits per-period plan, cost breakdown,
  a strategy classification (level / chase / hybrid via workforce-vs-inventory CoV), a
  seasonal-pre-build detector, capacity shadow prices (the GAP-5 hook), and a proportional per-SKU
  disaggregation stored in `state.aggregatePlan` for GAP-2 to forward. Verified: 5 tests in
  [tests/test_aggregate.py](tests/test_aggregate.py) — expensive labor ⇒ level+prebuild, cheap labor
  ⇒ chase, quantity-conserving disaggregation, no-backorder feasibility, binding-capacity duals.
  **Still open downstream:** GAP-2 must wire this plan in as the single demand truth (next).
- 🟩 **Premise (verified):** profitmix decision var is a single scalar per SKU —
  `q[k] = pulp.LpVariable(f'q_{k}', 0, ...)` with **no time index**
  ([profitmix.py:172](profitmix.py#L172)). Production is weekly scheduling. Nothing
  sits between annual mix and weekly schedule.
- ⚖️ **Consequence:** `demand_mode='seasonal'` ([profitmix.py:107](profitmix.py#L107))
  cannot actually pre-build — a single-period LP has no buckets to carry inventory
  across, so it can't build in the low season for a high-season peak. The seasonal
  mode only inflates a ceiling; it cannot produce the build-ahead plan its name implies.
- ⚖️ **Best way:** add a multi-period Aggregate Production Plan (the Hax–Meal /
  Nahmias textbook LP): monthly buckets × {regular time, overtime, hire/fire,
  inventory carry, backorder}, minimizing cost subject to demand and capacity. This
  is where level-vs-chase strategy and seasonal pre-build live. It also becomes the
  coherent demand/quantity source that feeds disaggregation → procurement → production.
- **Leverage:** highest. **Effort:** large (new solver + tab). Unlocks GAP-5, GAP-6.

---

## GAP-1 · Risk is descriptive, not prescriptive — and grades the wrong policy — ✅ IMPLEMENTED (R21)
- ✅ **Move 1 (R21):** [montecarlo.py](montecarlo.py) now simulates the COMMITTED plan when each
  product carries a `plan`/`production_plan` schedule — the inner loop replays that fixed schedule
  against the stochastic demand draws instead of re-deriving a base-stock target. Auto-detected
  (`params.policy='auto'`), legacy base-stock preserved when no plan is supplied. Result carries
  `policy_simulated`; the MC card badges "committed plan" vs "base-stock policy".
- ✅ **Move 2 (R21):** new [cvar.py](cvar.py) — the Rockafellar–Uryasev linear CVaR program
  (newsvendor order-up-to; `max()` linearized via overage/underage vars). Endpoint
  `/api/solve/cvar`. Procurement consumes it as a safety-stock floor via `params.ss_source='cvar'`
  (+ `cvar_beta`), surfaced by the **"CVaR-robust SS (β%)"** toggle in Optimize → constraints, so the
  PO plan is robust to the β-tail of lead-time demand by construction. Verified: 8 tests in
  [tests/test_gap1_risk.py](tests/test_gap1_risk.py) — committed under-build plan costs more / fills
  less than base-stock; CVaR order-up-to monotone in β and in shortage cost; procurement reports
  `ss_source='cvar'` with per-product levels.
- 🟩 **Premise (verified):** Monte Carlo simulates a base-stock heuristic
  `target = d + ss - inv; prod_qty = max(0, min(target, cap))`
  ([montecarlo.py:98-99](montecarlo.py#L98)) — i.e. it evaluates a base-stock policy,
  **not** the plan the procurement/production MILP produced. You optimize plan A and
  report the risk of policy B.
- 🟩 **Premise (verified):** CVaR is computed and reported ([montecarlo.py:135](montecarlo.py#L135))
  but never enters any optimization objective/constraint.
- ⚖️ **Best way (two moves):**
  1. **Simulate the actual decision** — feed the MILP's PO/production schedule into
     the MC inner loop instead of re-deriving a base-stock target, so the risk numbers
     describe the plan you'll execute.
  2. **CVaR optimization (Rockafellar–Uryasev)** — add the linear CVaR formulation
     to procurement so the plan is robust by construction, instead of optimize-then-check.
- **Leverage:** very high (coherence of the whole risk story). **Effort:** medium.

---

## GAP-2 · One-way waterfall, no feedback; no single demand truth
- 🟩 **Premise (verified):** `/api/solve/pipeline` runs profit→disaggregate→procure→produce
  strictly forward ([app.py:432-496](app.py#L432)); production results never revise the mix.
- 🟩 **Premise (verified):** demand enters four solvers independently —
  forecast.py output, profitmix `forecast`, procurement `demand`, MC `demand` — with no
  shared object, so they can silently disagree.
- ⚖️ **Best way:** (a) one consensus demand plan (ideally GAP-0's output, or the
  forecast leaderboard winner) flows to every solver; (b) a reconciliation loop — if
  production can't hit the mix quantity, feed the binding capacity back and re-solve the
  mix. That's what makes it S&OP rather than a report pipeline.
- **Leverage:** high. **Effort:** medium (orchestration, not new math).

---

## GAP-3 · Procurement emits a plan, not an inventory *policy*
- 🟩 **Premise (verified):** procurement returns a fixed-horizon PO schedule; the
  rolling-horizon endpoint that would make it a re-planning policy is the broken cyclic
  rotation (see MUST_FIX MF-6, [app.py:105](app.py#L105)). Safety stock is computed
  (Heizer) and imposed as a *floor constraint* (last session's #0), separate from the
  cost optimization rather than jointly derived.
- ⚖️ **Best way:** output an actual reorder **policy** — (s,S) or (R,Q) per part —
  derived from the cost structure + LT/demand variability, validated by rolling-horizon
  re-solves (after MF-6 is fixed to reveal *new* forecast tail, not rotate the vector).
  Operationally, planners run policies, not a frozen 26-week plan.
- **Leverage:** high. **Effort:** medium.

---

## GAP-4 · Risk model (HMM regimes) is computed and thrown away
- 🟩 **Premise (verified):** `detect_regimes` is imported only by its own endpoint
  ([app.py:33,414](app.py#L33)); **no solver** consumes regime output. Procurement *does*
  have static risk controls — `supplier_concentration_max_pct`
  ([procurement.py:1297-1306](procurement.py#L1297)) and an FX-exposure cap — but they are
  fixed percentages, not informed by detected disruption/volatility regimes.
- ⚖️ **Best way:** couple them — feed the HMM's high-vol persistence / current-regime
  probability into procurement so the concentration cap *tightens* and dual-sourcing
  splits widen when a part is in a high-volatility/disruption regime. Today the regime
  insight never changes a sourcing decision.
- **Leverage:** medium-high. **Effort:** small-medium (the controls already exist;
  this is wiring the trigger). **Note:** lateral transshipment between nodes already
  exists ([procurement.py:493-998](procurement.py#L493)) — not a gap.

---

## GAP-5 · Capital budgeting is single-period and decoupled from capacity
- 🟩 **Premise (verified):** capital.py is a single-period binary knapsack on NPV at one
  WACC; no multi-year budget, no capacity coupling. The production-sensitivity bridge that
  would value added capacity is broken under the machine-hours model (MUST_FIX MF-3).
- ⚖️ **Best way:** (a) multi-period capital plan with budget rollover and option timing
  (real-options framing for staged/deferred investment); (b) **endogenous capacity** — a
  "new line / new shift" option should add machine-hours to the production model so its NPV
  is justified by the throughput it unlocks, not a hand-set cash flow; (c) risk-adjust by
  running the existing MC on the NPV cash flows (currently deterministic).
- **Leverage:** medium-high. **Effort:** large.

---

## GAP-6 · Profit mix: deterministic, single-period, independent demand
- 🟩 **Premise (verified):** LP with deterministic margins; MAPE used only as a static
  ceiling buffer ([profitmix.py:91](profitmix.py#L91)); SKUs have independent demand;
  `fixed_daily_cost` is linear ([profitmix.py:233](profitmix.py#L233)).
- ⚖️ **Best way:** (a) two-stage stochastic or scenario LP using the MAPE distribution as
  recourse, not a point buffer; (b) **cross-elasticity / cannibalization** so substitution
  between SKUs is modeled; (c) **fixed-charge MILP** for line-opening step costs (opening a
  line is a binary fixed cost, not a linear daily rate). Largely subsumed by GAP-0 if the
  aggregate tier is multi-period and stochastic.
- **Leverage:** medium. **Effort:** medium-large.

---

## GAP-7 · Forecasting: no reconciliation, no intermittent methods, MAPE-only
- 🟩 **Premise (verified):** per-SKU independent models; MAPE masks zeros
  `mask = actual != 0` ([forecast.py:68](forecast.py#L68)); no Croston/SBA/TSB; SKU
  forecasts and the annual-mix disaggregation are never reconciled.
- ⚖️ **Best way:** (a) **hierarchical reconciliation (MinT / bottom-up)** so SKU forecasts
  are coherent with family/total and feed disaggregation directly; (b) **intermittent-demand
  models** (Croston/SBA/TSB) for lumpy/zero-inflated series, where MAPE is the wrong metric
  (use MASE/RMSSE); (c) **bias / tracking-signal** monitoring alongside MAPE (a biased-but-
  accurate forecast is the dangerous case you don't surface).
- **Leverage:** medium. **Effort:** medium.

---

## GAP-8 · Production scheduling: averaged changeover, no WIP, CBC engine
- 🟩 **Premise (verified):** changeover is a switch *count* with the matrix averaged to stay
  linear (last session's note, [production.py:221-238](production.py#L221)); multi-stage
  routing collapses to bottleneck throughput (`_route_cap`), so no WIP / lot-streaming.
- ⚖️ **Best way:** (a) **sequence-dependent setup** (asymmetric, TSP-like) for real
  changeover cost; (b) move detailed scheduling to **CP-SAT (OR-Tools)** — disjunctive /
  no-overlap / sequence constraints are its home turf and it dominates CBC MILP here;
  (c) model inter-stage WIP and transfer batches (lot-streaming) instead of bottleneck-only.
- **Leverage:** medium (only if scheduling fidelity matters to users). **Effort:** large.

---

## GAP-9 · Transport: greedy mode-choice + disconnected allocation LP
- 🟩 **Premise (verified):** per-shipment "cheapest feasible mode" is a sort
  ([transport.py:98-99](transport.py#L98)); the allocation LP uses separate
  origins/destinations/cost_matrix ([transport.py:145-155](transport.py#L145)) and is not
  connected to the mode-choice. No consolidation/bin-packing across shipments.
- ⚖️ **Best way:** one model that does **mode choice + consolidation** — LTL→FTL
  consolidation, multi-stop, container-fill bin-packing, carrier capacity/contract
  commitments. The two halves should be a single optimization, not a sort beside an LP.
- **Leverage:** medium. **Effort:** medium-large.

---

## Ranking (leverage × foundational-ness)
1. **GAP-0** Aggregate Planning tier (unlocks seasonal pre-build; the missing middle).
2. **GAP-1** Simulate the actual plan + CVaR optimization (risk becomes coherent + prescriptive).
3. **GAP-2** Closed-loop reconciliation + one demand truth (waterfall → S&OP).
4. **GAP-3** Inventory *policy* output + fix rolling horizon (operational, not one-shot).
5. **GAP-5** Capital↔capacity coupling (endogenous investment justification).
6. **GAP-4 / GAP-7 / GAP-8 / GAP-9 / GAP-6** — strong but more contained.

---

## Honest scope caveats
- These are **design judgments**, not defects — reasonable architects will disagree on
  some. Only the 🟩 premises are code-verified.
- This is a *thorough* pass, not a *proof of completeness*. The one concrete thing still
  un-swept is the per-field UI dead-input enumeration (MUST_FIX MF-18 framework) — a field
  collected in `state` but dropped by a payload-builder would surface there, not here.
- Two earlier verbal claims were corrected during verification (procurement DOES have
  concentration/FX caps and DOES have lateral transfers) — reflected above.
