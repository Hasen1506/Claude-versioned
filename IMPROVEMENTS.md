# IMPROVEMENTS — Structural / Methodology Roadmap (Round 16)

Owner: Hasen · Auditor role: supply-chain + OR domain expert
Opened: 2026-05-29

**This is NOT the bug register** — see [MUST_FIX.md](MUST_FIX.md) for verified defects.
This file lists places where a segment *works as built* but a better-practice
modeling approach exists, or where a whole component is missing from the
start→end chain. Each item separates the **factual premise** (verified against
code, file:line) from the **design judgment** (my recommendation, which is
debatable). Effort/leverage is my estimate.

Legend: 🟩 verified premise · ⚖️ design judgment · ⭐ highest leverage · ✅ IMPLEMENTED

> **STATUS (2026-05-30):** All ten gaps implemented across Rounds 20–29 (GAP-0 R20, GAP-1 R21,
> GAP-2 R22, GAP-3 R23, GAP-5 R24, GAP-4 R25, GAP-7 R26, GAP-8 R27, GAP-9 R28, GAP-6 R29). Each
> shipped as a verified commit (Python AST + full Babel JSX parse + pytest). The suite grew from 17 to
> 73 tests. Three gaps were delivered in their highest-leverage scope with the larger rewrite explicitly
> deferred and reasoned (GAP-8 CP-SAT/WIP, GAP-9 unified MILP, GAP-6 full two-stage stochastic) — see
> each section's scope note.

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

## GAP-2 · One-way waterfall, no feedback; no single demand truth — ✅ IMPLEMENTED (R22)
- ✅ **Built (R22):** new [reconcile.py](reconcile.py) — `consensus_demand` resolves ONE per-SKU
  demand vector (priority: the GAP-0 aggregate plan → caller consensus → forecast) and stamps it onto
  every solver payload, so profit-mix / procurement / production stop disagreeing. `run_sop_pipeline`
  runs the forward chain then closes the loop: where production is capacity-bound (its demand floor C1
  is hard, so a shortfall surfaces as infeasibility), it rations the mix ceiling to the achievable
  output and re-solves, iterating until self-consistent, then procures on the reconciled quantities.
  Endpoint `/api/solve/sop`; **"🔁 Closed-loop S&OP"** mode in Optimize stamps `state.aggregatePlan`
  as the truth and renders the per-iteration reconciliation table. Verified: 5 tests in
  [tests/test_gap2_sop.py](tests/test_gap2_sop.py) — aggregate-plan demand truth + forecast fallback,
  tight line reconciles (infeasible→rationed→Optimal, procures on reconciled plan), ample capacity
  converges first iteration.
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

## GAP-3 · Procurement emits a plan, not an inventory *policy* — ✅ IMPLEMENTED (R23)
- ✅ **Built (R23):** new [policy.py](policy.py) `derive_policies` — per-part (s,S) continuous-review
  and (R,Q) periodic-review reorder policies from the cost structure + LT/demand variability:
  EOQ Q*=√(2DK/h), ss=z·σ_LTD, reorder s=μ_L+ss, order-up-to S=s+Q*, review period, orders/yr, and a
  continuous-vs-periodic recommendation by demand CV. Procurement now returns `inventory_policies`;
  endpoint `/api/solve/policy`; a **Reorder Policy** card renders the (s,S)/(R,Q) table in Optimize.
  The existing rolling-horizon endpoint (now MF-6-correct) is the named validator. Verified: 6 tests in
  [tests/test_gap3_policy.py](tests/test_gap3_policy.py) — EOQ closed-form, S=s+Q*, s≥μ_L+ss, service
  level ↑ ⇒ ss ↑, lumpy series ⇒ (s,S) recommended, procurement surfaces the policy.
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

## GAP-4 · Risk model (HMM regimes) is computed and thrown away — ✅ IMPLEMENTED (R25)
- ✅ **Built (R25):** the HMM regime signal now changes a sourcing decision. Parts carry
  `regime_high_vol` / `regime_persistence` (from risk.py); procurement (`regime_aware_sourcing`)
  computes a regime-TIGHTENED effective concentration cap per supplier — base × (1 −
  tightening·severity), severity = max regime persistence among the supplier's high-vol parts — and
  adds a SOFT penalty on spend concentrated with a high-vol supplier beyond that cap, widening
  dual-sourcing toward stabler alternatives. Soft (not a hard tighten) so a structurally single-sourced
  part can never be made infeasible. Surfaced by the **"Regime-aware sourcing (tighten%)"** toggle +
  a result card. Verified: 4 tests in [tests/test_gap4_regime.py](tests/test_gap4_regime.py) — off ⇒
  no adjustment, high-vol cap tightened (50→23%), only high-vol suppliers listed, stickier regime
  tightens more.
- **Scope note:** full dual-sourcing of ONE part across multiple suppliers is a deeper model change
  (parts are bound per product/BOM line today); this wires the trigger into the existing
  concentration-control channel, as the gap describes.
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

## GAP-5 · Capital budgeting is single-period and decoupled from capacity — ✅ IMPLEMENTED (R24)
- ✅ **Built (R24):** new [capital_capacity.py](capital_capacity.py) `solve_capital_capacity` — all
  three moves: (a) multi-period `invest[i,t]` timing within each option's [earliest,latest] window
  under a per-period budget whose unspent balance rolls forward; (b) ENDOGENOUS capacity — a
  'capacity' option's annual cash flow is derived from throughput (capacity_hours · margin_per_hour ·
  utilization − opex), with margin_per_hour defaulting to the binding capacity shadow price the
  Aggregate Plan (GAP-0) emits, directly coupling capital to the bottleneck's value; (c) a Monte Carlo
  pass perturbs the cash-flow drivers (±CV) and reports the NPV band + P(NPV<0). Endpoint
  `/api/solve/capital-capacity`; **"Endogenous-Capacity Capital Plan"** card in the Investment tab
  (pulls the live shadow price from `state.aggregatePlan`). Verified: 7 tests in
  [tests/test_gap5_capital.py](tests/test_gap5_capital.py) — throughput-derived CF, margin override,
  positive-NPV capacity selected, tight no-rollover drops the big line, rollover is a relaxation
  (NPV can't worsen) and funds the line by mid-horizon, risk band ordered with bounded P(NPV<0).
- **Note:** capital.py (legacy single-period knapsack) is retained; this is the additive multi-period
  successor, not a rewrite.
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

## GAP-6 · Profit mix: deterministic, single-period, independent demand — ✅ IMPLEMENTED (R29)
- ✅ **Built (R29):** in [profitmix.py](profitmix.py). (c) **Fixed-charge line opening** — a line's
  one-time open cost is now a BINARY decision: `open[l] ∈ {0,1}`, capacity gated on it (x ≤ cap·open),
  the fixed charge paid once per opened line (was a linear per-SKU `fixed_daily_cost`). (b)
  **Cross-elasticity / cannibalization** — a SKU's substitutes eat its ceiling: q[k] + Σ rate·q[j] ≤
  ceiling_k, so SKUs are no longer independent. (a) **MAPE robustness band** — the chosen mix is
  re-evaluated at ±MAPE demand (poor-man's recourse) → pessimistic/expected/optimistic profit, exposing
  a deterministic plan's downside. Result carries `opened_lines`, `fixed_open_cost_total`, `robustness`;
  surfaced in the profit-mix result. Verified: 5 tests in
  [tests/test_gap6_profitmix.py](tests/test_gap6_profitmix.py) — cannibalization lowers the substitute's
  output (constraint binds), no-substitutes unchanged, fixed charge opens the cheap line / declines the
  ₹500k one, robustness band ordered.
- **Scope note:** the full two-stage stochastic program is, as this gap originally noted, largely
  subsumed by the multi-period GAP-0 tier + the GAP-1 Monte Carlo on the committed plan; the ±MAPE band
  here is the lightweight in-solver robustness readout.
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

## GAP-7 · Forecasting: no reconciliation, no intermittent methods, MAPE-only — ✅ IMPLEMENTED (R26)
- ✅ **Built (R26):** all three moves in [forecast.py](forecast.py). (a) **Intermittent models** —
  Croston, SBA (bias-corrected), TSB (probability-based, obsolescence-aware), pure-numpy so always
  available; a Syntetos–Boylan classifier (ADI/CV²) labels each series smooth/intermittent/erratic/lumpy
  and, when intermittent, ranks the leaderboard by **MASE** (finite on zeros, where MAPE breaks) and
  steers the recommendation to TSB/SBA/Croston. (b) **Bias / tracking-signal** — every leaderboard row
  now carries MASE, signed `bias`, and `tracking_signal` (RSFE/MAD) with an `out_of_control` flag (|TS|>4)
  — the biased-but-accurate forecast is now surfaced. (c) **Hierarchical reconciliation** — a bottom-up
  pass sums each SKU's winning forecast into a coherent family total (`reconciliation`). UI: the
  server-side forecast card gains MASE/Bias/Track-sig columns + an intermittence/reconciliation strip.
  Verified: 8 tests in [tests/test_gap7_forecast.py](tests/test_gap7_forecast.py) — classification,
  Croston/SBA/TSB shape, SBA<Croston, MASE finite on zeros, bias/TS detect over-forecast, intermittent
  series won by an intermittent model ranked on MASE, bottom-up total = Σ winners.
- **Scope note:** MinT reconciliation needs a residual covariance estimate not carried here; bottom-up
  is the unbiased, dependency-free choice and is what the disaggregation/aggregate tiers consume.
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

## GAP-8 · Production scheduling: averaged changeover, no WIP, CBC engine — ✅ MOVE (a) IMPLEMENTED (R27)
- ✅ **Built (R27):** new [sequencing.py](sequencing.py) `optimal_sequence` — the true
  sequence-dependent changeover the MILP averages away. It solves the shortest Hamiltonian PATH over
  the asymmetric changeover matrix (A→B ≠ B→A) for the SKUs scheduled on a line: exact (permutation)
  for ≤8 SKUs, nearest-neighbour + node-reinsertion above. production.py now emits `sequence_plans`
  per line (run order + true changeover min + saving vs the averaged approximation) post-solve, no MILP
  change; endpoint `/api/solve/sequence`; a **Sequence-Dependent Changeover** card shows the run order +
  saving. Verified: 6 tests in [tests/test_gap8_sequence.py](tests/test_gap8_sequence.py) — cheapest
  path, asymmetry respected, saving vs average, single-SKU zero, heuristic for >8, production emits plans.
- ⏸️ **Moves (b) CP-SAT and (c) WIP / lot-streaming — deferred.** OR-Tools is not installed in this
  environment (CP-SAT unavailable), and inter-stage WIP/transfer-batch modelling is a large MILP
  reformulation (`_route_cap` collapses routing to bottleneck throughput today). Move (a) delivers the
  highest-fidelity win — real asymmetric setup cost + the optimal run order — without those dependencies.
- 🟩 **Premise (verified):** changeover is a switch *count* with the matrix averaged to stay
  linear (last session's note, [production.py:221-238](production.py#L221)); multi-stage
  routing collapses to bottleneck throughput (`_route_cap`), so no WIP / lot-streaming.
- ⚖️ **Best way:** (a) **sequence-dependent setup** (asymmetric, TSP-like) for real
  changeover cost; (b) move detailed scheduling to **CP-SAT (OR-Tools)** — disjunctive /
  no-overlap / sequence constraints are its home turf and it dominates CBC MILP here;
  (c) model inter-stage WIP and transfer batches (lot-streaming) instead of bottleneck-only.
- **Leverage:** medium (only if scheduling fidelity matters to users). **Effort:** large.

---

## GAP-9 · Transport: greedy mode-choice + disconnected allocation LP — ✅ CONSOLIDATION IMPLEMENTED (R28)
- ✅ **Built (R28):** `consolidate_shipments` in [transport.py](transport.py) — the consolidation the
  greedy per-shipment mode choice misses. It groups shipments by origin→dest lane, bin-packs the
  combined weight into full loads, and compares all-individual (LTL/LCL) cost against the consolidated
  (FTL/FCL) cost with the remainder taking whichever is cheaper, recommending consolidation only when it
  saves. solve_transport returns `consolidation` + `consolidation_saving`; endpoint
  `/api/solve/consolidate`; a **Consolidation opportunities** panel in the transport result. Verified: 6
  tests in [tests/test_gap9_consolidation.py](tests/test_gap9_consolidation.py) — LTL→FTL saves, tiny
  parcels not consolidated, bin-packs into multiple full loads, single-shipment lane skipped, separate
  lanes not merged, solve_transport surfaces it.
- **Scope note:** a single unified mode-choice + consolidation + multi-stop MILP (fully replacing the
  sort-beside-an-LP) is the larger rewrite the gap's ideal describes; this delivers the consolidation/
  bin-packing decision — the highest-value missing piece — alongside the existing mode heuristic.
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
