# MUST-FIX — Correctness & Coherence Audit (Round 16)

Owner: Hasen · Auditor role: supply-chain + MILP domain expert
Opened: 2026-05-29 · Status legend: 🔴 broken/misleading · 🟠 grain/methodology · 🟡 polish · ✅ fixed

This file tracks **pending** defects found while tracing every solver end-to-end
against the Flask API layer (`app.py`) and the UI payloads (`index.html`). Each
item is verified against the code (file:line), not recalled. Last session's 8
fixes (procurement #0/#1/#2/#3, capital #15+dedup, production #11/#13) are NOT
relisted here — they are committed.

---

## ⭐ SYSTEMIC — Perishability & salvage (R17: now modeled in MC + profitmix; procurement pending)
This is the headline finding and it spans three solvers + the researcher. **Decision (2026-05-30):
model it for real.** Batch 1 (R17) made shelf_life + salvage genuine levers in Monte Carlo and
profitmix; procurement's cohort model is still pending (next batch).

| Solver | `shelf_life` | `salvage_rate` | Status |
|---|---|---|---|
| profitmix.py | ✅ horizon-scaled holding + shelf<horizon spoilage gate (MF-5) | ✅ write-off `unit_cost·(1−salvage)` on excess now in objective (MF-2) | **FIXED R17** |
| procurement.py | **dead** — read L358/581/798, never in any constraint/cost | **dead** — read L58, never used | pending |
| montecarlo.py | ✅ FIFO/FEFO cohort aging, expire past shelf (MF-1) | ✅ salvage-adjusted write-off on expired lots | **FIXED R17** |

procurement's docstring (L5) even advertises "**+ expiry**" as a cost component
that **does not exist** in the objective (L596-612: setup + FG holding + variable
+ shortage + milk-run only). For a tool aimed at FMCG/perishable supply chains,
shelf-life and salvage are surfaced in the UI, swept by the auto-researcher, and
described in docstrings — but **change no result anywhere.** This should be the
first decision: either model expiry/salvage for real (cohort aging + write-off at
`unit_cost·(1-salvage)`, plus a `inv ≤ Σ demand over next shelf periods` cap), or
strip the inputs and the claims. MF-1/MF-2/MF-5 are the per-site instances.

---

## ✅ Batch 1 — RESOLVED (R17, 2026-05-30) · MF-1 … MF-12

Fixed in this pass (verified by AST parse + functional smoke-tests that each lever now *moves*):

- **MF-1** ✅ montecarlo.py — FIFO/FEFO cohort aging; lots past `shelf_life` written off at
  `(var+mat)·(1−salvage)`. Verified: short shelf +940 cost vs long; zero-salvage +241 more.
- **MF-2** ✅ profitmix.py — expiry write-off now added to the objective on `excess[k]`. Verified:
  low salvage lowers total_profit vs high salvage.
- **MF-3** ✅ app.py production-sensitivity — scenarios now scale the target line's
  `cycle_time_by_sku_min` (1/cap_factor), the basis `LineCapHrs`/`_route_cap` actually read.
  Verified: Δthroughput=60 where the old flat-capacity perturbation gave 0.
- **MF-4** ✅ montecarlo.py — holding divides by `periods_per_year` (was hardcoded /52).
- **MF-5** ✅ profitmix.py — excess holding scaled by `horizon_months`; shelf unified to months;
  `planning_mode` demoted to documented fallback behind `planning_horizon_months`.
- **MF-6** ✅ app.py `/api/solve/rolling` — slides the horizon forward + pads with a trailing-mean
  naive forecast instead of cyclically wrapping the tail to the front.
- **MF-7** ✅ montecarlo.py — `NormalDist().inv_cdf` for exact z at any service level (was 4-bucket).
- **MF-8** ✅ profitmix.py — `margin_per_hour`/`capacity_hours_used`/crossover use realized per-line
  cycle hours (`_cycle_hrs_for_line`), not the scalar `cycle_time` the LP ignores.
- **MF-9** ✅ transport.py — allocation LP checks `LpStatus` before reading values; infeasible
  (Σsupply<Σdemand) returns a real status+error instead of a `round(None)` 500. Verified.
- **MF-10** ✅ transport.py — one reconciled stockout price: both the mode-ranking penalty and the
  air-vs-sea decision risk-adjust the same gross lost-revenue by `stockout_risk_factor` (param, def 0.3).
- **MF-11** ✅ app.py `/api/whatif` — labelled advisory-only (`advisory_only/applied:false/parsed`);
  it parses intent, does not apply or re-solve.
- **MF-12** ✅ production.py — shared line capped at 1 product/period, a 2nd allowed only when
  `switch[l,t]=1` (a real changeover). Verified shared-line solve stays Optimal.

Detailed original write-ups for each retained below for provenance.

---

## Severity 🔴 — actively misleading (presents inert/stale results as real)

### MF-1 · Monte Carlo `shelf_life` is inert, and the auto-researcher sells it as a lever
- **Where:** [montecarlo.py:110-112](montecarlo.py#L110) — only post-read use of `shelf` is `pass`.
- **Symptom:** Shelf life has zero effect on simulated cost. The researcher "upgrade"
  mode ([app.py:228-231](app.py#L228)) sweeps `shelf_values=[4,8,12,26,52]` and reports
  `savings_pct` per config — but every shelf value yields an identical cost, so the
  shelf-life sensitivity shown to the user is fabricated.
- **Fix direction:** Implement cohort/expiry write-off in the MC inner loop (track
  inventory age, expire stock older than `shelf`, charge `unit_cost·(1-salvage)` on
  expired units), OR remove `shelf_life` from the researcher sweep and the upgrade UI.
- **Verified:** `grep shelf montecarlo.py` → used at L56 (read) and L111 (`pass`).

### MF-2 · profitmix `salvage_rate` is a dead input
- **Where:** [profitmix.py:223-224](profitmix.py#L223) computes `expiry_penalty` and never uses it.
- **Symptom:** UI collects Salvage % ([index.html:5355](index.html#L5355), hint claims
  "write-off cost"), sends `salvage_rate` ([index.html:6349](index.html#L6349)); the LP
  drops it. Only `holding_penalty` (salvage-independent) touches excess.
- **Fix direction:** Either add the expiry/write-off term to the objective on `excess[k]`
  (e.g. blend holding + salvage-adjusted write-off over the horizon), or stop advertising it.
- **Verified:** `grep expiry_penalty profitmix.py` → single hit, assignment only.

### MF-3 · production-sensitivity (CapEx suggester) silently no-ops under the machine-hours model
- **Where:** [app.py:340-345](app.py#L340) perturbs the flat `capacity`/`shifts_per_day`
  fields; [production.py:320-323](production.py#L320) (`LineCapHrs`) and `_route_cap`
  ([production.py:128](production.py#L128)) derive bounds from `hrs_per_period·OEE` and
  ignore `capacity`/`shifts_per_day` once `cycle_time_by_sku_min` is present.
- **Symptom:** "add shift / add machine / add worker" scenarios return
  `delta_throughput = 0` for any modern payload that carries cycle data → payback `None`.
  This is a **regression interaction** from last session's #11 fix; the suggester was
  built against the old flat-capacity model.
- **Fix direction:** Make the scenario perturb the hours basis the solver actually reads:
  scale `hrs_per_period` (shift = +hrs), or inject/scale `cycle_time_by_sku_min`, or add a
  per-line machine-count multiplier into `_route_cap`/`LineCapHrs`. Keep the flat-capacity
  perturbation only for the legacy no-cycle fallback.
- **Verified:** by tracing — neither `_route_cap` nor `LineCapHrs` reads `capacity`/`shifts` in the cycle path.

---

## Severity 🟠 — grain / methodology correctness

### MF-4 · Monte Carlo holding rate hardcoded weekly
- **Where:** [montecarlo.py:84](montecarlo.py#L84) `unit_mat_cost*carry_rate/52`.
- **Symptom:** Same grain bug we fixed in procurement (#1) and lot_sizing (#3); MC never
  reconciled. `T` defaults to 52 but procurement passes `periods=26`; MC has no
  `periods_per_year`, so holding is weekly regardless of true grain.
- **Fix direction:** Pass/derive `periods_per_year` and divide by it (mirror lot_sizing `_per_period_hold_rate`).

### MF-5 · profitmix excess-holding penalty is grain-blind + dead `planning_mode` branch + mixed units
- **Where:** [profitmix.py:217](profitmix.py#L217) `unit_cost*carry_rate/12` charges exactly
  ONE month of carry on excess regardless of `planning_horizon_months`.
- **Also:** UI never sends `planning_mode` ([index.html:6343](index.html#L6343) sends only
  `planning_horizon_months`) → the quarterly/annual `horizon_days` branch
  ([profitmix.py:230](profitmix.py#L230)) is dead. And `shelf < 12`
  ([profitmix.py:219](profitmix.py#L219)) compares a value defaulting to **52 weeks** against
  literal **12 months** — mixed units in the spoilage factor.
- **Fix direction:** Scale excess holding by horizon periods; unify shelf-life units
  (weeks vs months) with an explicit grain; either wire `planning_mode` from the UI or delete the branch.

### MF-6 · `/api/solve/rolling` is a cyclic rotation, not a rolling horizon
- **Where:** [app.py:105](app.py#L105) `demand[w*shift:] + demand[:w*shift]` wraps the tail to the front.
- **Symptom:** A real rolling re-plan reveals NEW future demand; this permutes the same
  vector, so "nervousness" measures churn from a permutation, not re-forecasting. Number is meaningless as labeled.
- **Fix direction:** Extend the horizon with fresh forecast tail (or accept a forecast-update
  array per wave) instead of rotating; recompute nervousness against the genuinely re-planned overlap window.

---

## Severity 🟡 — polish / fragility

### MF-7 · Monte Carlo z-table is a 4-bucket lookup (deferred #19, confirmed live)
- [montecarlo.py:24](montecarlo.py#L24): any `service_level ∉ {0.85,0.90,0.95,0.99}` snaps to z=1.645.
  Procurement uses `NormalDist().inv_cdf`; MC doesn't. → use `inv_cdf`.

### MF-8 · profitmix `margin_per_hour` & crossover use scalar `cycle_time` (deferred #7, confirmed live)
- [profitmix.py:415](profitmix.py#L415), [498](profitmix.py#L498) use product `cycle_time`
  while the LP optimized on per-line `_cycle_hrs_for_line`. Headline KPI disagrees with the LP basis.

### MF-9 · transport allocation LP has no feasibility guard
- [transport.py:150-153](transport.py#L150): demand `>=`, supply `<=`; if Σsupply<Σdemand →
  infeasible → `round(pulp.value(None),2)` throws → bare 500. Add a status check like the other solvers.

### MF-10 · transport stockout valued two ways
- Option loop applies `×0.3` haircut ([transport.py:91](transport.py#L91)); spike-alert path uses
  full lost revenue ([transport.py:114](transport.py#L114)). Same event, two prices — reconcile.

### MF-11 · `/api/whatif` is a regex stub presented as functional
- [app.py:557+](app.py#L557) returns prose "changes" and never applies them; wired in UI at
  [index.html:12358](index.html#L12358). Either implement parameter application or label it clearly as advisory-only.

### MF-12 · production shared-line "max 1 product" is actually `≤ 2` with no changeover tie
- [production.py:337](production.py#L337) `≤ 2` every period; the sequential-mode semantics in the comment aren't enforced.

### MF-13 · pattern_sensing aligns the same two arrays two different ways
- `match_patterns` compares `actuals[-n:]` (latest) against `baseline_forecast[:n]` (earliest)
  ([pattern_sensing.py:119-121](pattern_sensing.py#L119)) — a temporal mismatch if baseline covers
  the future horizon. But `posterior_variance` aligns `actuals[i] - baseline[i]` from index 0
  ([pattern_sensing.py:172](pattern_sensing.py#L172)). Two functions, same inputs, **incompatible
  time alignment** → residual shape-matching and σ are computed on different windows. Pick one alignment.

### MF-14 · forecast lag features are daily-centric but default grain is monthly
- [forecast.py:116-118](forecast.py#L116) hardcode lag-1/lag-7/lag-30 period offsets; default
  `time_grain='monthly'` ([forecast.py:306](forecast.py#L306)) makes lag-30 = "30 months ago",
  requiring 30 months of history before the feature is real. Lags should scale with grain (e.g.
  seasonal lag = `season_length`), or the feature names/semantics should be grain-aware.

### MF-15 · PDF report treats `sum(history)` as "annual demand" / "projected revenue"
- [report.py:46-54](report.py#L46) sums **all** history (past actuals, arbitrary length) and labels it
  "total annual demand" and multiplies by price for "projected revenue." Multi-year history
  double-counts; past actuals aren't a projection. Use forecast/horizon-scoped demand and relabel.

### MF-16 · calendar: hardcoded year 2026 + `custom_holidays` unreachable via API
- [calendar.py:80-81](calendar.py#L80) iterates 2026 only; [app.py:661-674](app.py#L661) never passes
  `custom_holidays`, so the function's custom-holiday support is dead through the endpoint.

### MF-17 · doc drift: procurement stale `/52` comment after the #1 fix
- [procurement.py:589](procurement.py#L589) comment still says node holding is `… inv_node/52`, but
  the live code at [procurement.py:604](procurement.py#L604) correctly divides by `periods_per_year`.
  Code is right; comment is stale and will mislead the next reader. (Trivial, but it's exactly the
  kind of drift that reintroduces grain bugs.)

### MF-19 · 🔴 Two divergent payload builders per solver — neither procurement path is complete
- **Where:** the primary `solverMode` dispatcher ([index.html:6150-6315](index.html#L6150)) and the
  "✅ Solver Input Readiness" dashboard, whose per-row ⚡ Run buttons call `runSolver(...)` with a
  **separate** payload ([index.html:14164-14211](index.html#L14164), live via `onClick={s.run}`).
- **Symptom (verified by line-number divergence):**
  - **Procurement is split, not duplicated.** `lead_time_band` / `terminal_anchor_units` /
    `min_coverage_periods` / `transport_modes` / `committed_periods` appear **only** at
    [index.html:14182-14189](index.html#L14182) (dashboard). MEIO `network_nodes`/`network_lanes` +
    risk constraints (`supplier_concentration_max_pct`, `fx_exposure_max_pct`, `co2_max_per_period`,
    `fill_rate_target`, `budget_deflate`, `inflation_pct_annual`) appear **only** at
    [index.html:6190-6250](index.html#L6190) (primary). → **No single Run button sends a complete
    procurement model;** each path drops a different half of R5–R12 wiring.
  - **Dashboard production is degraded** ([index.html:14197](index.html#L14197)): sends only
    name/required_qty/setup_cost/yield_pct/cycle_time + capacity/type/shifts. Drops **all** R13–R15
    wiring — `workforce`, `labor_cost_mode`, per-line OT (`workers_per_shift`/`hourly_rate`/
    `max_ot_hrs_per_worker_per_week`), `cycle_time_by_sku_min`, `oee`, `changeover_matrix`,
    `planned_maintenance`. Result silently falls back to flat-capacity with no labor/OT cost.
  - **Dashboard profitmix is dimensionally broken** ([index.html:14201](index.html#L14201)): sends
    `cycle_time:p.cycleTime||19` (raw **minutes**) against `constraints.shared_capacity` built in
    **units** (`Σ capacity×periods`). The primary path sends cycle_time as **hours** (`168/capacity`).
    So the dashboard's shared-capacity constraint is off by ~60× and unit-incoherent; it also omits the
    line pool, `planning_horizon_months`, `labor_cost_mode`, `time_grain`, and `history`.
- **Fix direction:** one canonical payload-builder per solver, consumed by both surfaces (the dashboard
  should call the same builder the primary path uses). This is the concrete instance of MF-18.
- **Verified:** grep line-number divergence above; both builders read in full.

### MF-20 · Solver params never sent → hardcoded defaults masquerading as configurable
- `makespan_weight` — **0** occurrences in index.html ([production.py:26](production.py#L26) default 0.1);
  never tunable.
- `shutdown_threshold_pct` / `rehire_notice_hrs` — appear in index.html **only** as result-display /
  tooltip text ([index.html:7120,7130,7146](index.html#L7120)) that *describes* them as
  `params.*` knobs, but **no payload sends them** → production.py always uses 25% / 80h
  ([production.py:451-452](production.py#L451)). The tooltip implies tunability that doesn't exist.
- `planning_mode` — **0** occurrences (already noted in MF-5; the quarterly/annual branch is dead).
- **Fix direction:** either expose real inputs that flow into the payload, or drop the tooltips/branches
  that imply configurability.

### MF-21 · 🟠 Transport: the entire demand-sensing feature + allocation LP are unreachable from the UI
- **Where:** transport payload builder ([index.html:6380-6398](index.html#L6380)).
- **Symptom (verified, 0 occurrences):**
  - `demand_spike:false` is **hardcoded** ([index.html:6393](index.html#L6393)); `current_stock`,
    `spike_qty` are **never sent**; `daily_consumption` never sent. transport.py's whole
    demand-sensing path — stockout cost, the air-vs-sea `spike_alert`, the "USE AIR / ACCEPT RISK"
    decision ([transport.py:70-128](transport.py#L70)) — is gated on `spike and daily_use>0`, so it
    **never fires**. The module's headline feature always returns "cheapest feasible mode" and never
    flags a stockout risk.
  - `origins` / `destinations` / `cost_matrix` are **never sent** → the transportation **allocation
    LP** ([transport.py:144-155](transport.py#L144)) **never runs** from the UI.
  - `current_mode` **is** sent ([index.html:6393](index.html#L6393)) but transport.py never reads it
    → dead input.
  - Shipments are auto-derived from `import || leadTime>2` BOM parts, not a user shipment table, so
    domestic short-LT freight is never optimized.
- **Fix direction:** wire `daily_consumption`/`current_stock`/`demand_spike` from product demand +
  on-hand so spike detection can fire; expose origins/destinations/cost_matrix (or drop the alloc LP);
  drop `current_mode` or make transport.py honor it.

### MF-22 · 🟠 Capital: exclusivity / dependency / max-count modeling unreachable; investments are synthetic
- **Where:** capital payload builder ([index.html:6406-6415](index.html#L6406)).
- **Symptom (verified, 0 occurrences):** `exclusivity_groups`, `dependencies`, `max_investments` are
  **never sent** → capital.py's mutual-exclusivity ([capital.py:85-87](capital.py#L85)), dependency
  ([capital.py:88-92](capital.py#L88)), and max-count constraints are inert. Investments are
  **synthetically generated** from production lines (`capex = capacity×10000`, heuristic cash flow),
  not from a user-entered investment/asset table — so real CapEx options can't be evaluated, and the
  buy-vs-lease framing in the module docstring is unreachable.
- **Fix direction:** feed a real investment list + optional exclusivity/dependency groups from the UI.

### MF-23 · 🟡 `/api/forecast/retrain` is a 404 (no backend route)
- [index.html:5916](index.html#L5916) POSTs to `/api/forecast/retrain`; **app.py has no such route**
  (only `/api/forecast`). The call silently fails. Either add the route or remove the call.

### MF-24 · 🟡 Finance calc endpoints are shadow-computed client-side; WACC backend response is discarded
- NPV / depreciation / WACC are computed **client-side** (`npvLocal`/`deprLocal`/inline WACC) as the
  authoritative result; the backend `/api/calc/*` calls are "optional audit." WACC explicitly
  **fetches then throws away** the server response ([index.html:10914](index.html#L10914): "keep
  client-side result authoritative, just log"). → the WACC round-trip is pure waste, and maintaining
  two copies of each finance formula risks client/server divergence (no test pins them equal).
- **Fix direction:** pick one source of truth — either drop the redundant endpoints or render the
  backend result and delete the JS duplicates.

### MF-18 · systemic key-contract boundary (camelCase state ↔ snake_case payloads)
- Solvers consume snake_case (`sell_price`, `qty_per`, `hold_pct`…); the UI transforms camelCase
  state → snake_case per call. But [report.py](report.py) reads **raw camelCase** state
  (`sellPrice`, `qtyPer`, `shelfLife`, `yieldPct`, `leadTime`, `moq`, `supplierType`). Two contracts
  exist with no shared schema, so any field the per-call transform forgets silently becomes a solver
  default (this is the mechanism behind dead-input bugs). Worth a single canonical
  payload-builder + a contract test asserting every UI field reaches its solver key.

---

## Inputs that shouldn't exist as free inputs (conceptual, not plumbing)

These are not dead inputs (collected-then-dropped) — they are inputs that, from a
domain standpoint, should not be hand-entered at all: a measured *output* exposed as
a guessable field, an input naming a method that was never built, a label collision,
and single-source values left editable in two places.

### MF-25 · 🔴 MAPE is a manual input, but forecast accuracy is *measured*, not chosen
- `prod.mape` is a free `NumInput` defaulting to 15 ([index.html:5331](index.html#L5331),
  default [index.html:2078](index.html#L2078)). The forecast leaderboard already backtests and
  computes a real holdout MAPE (`computeMetrics` [index.html:1001](index.html#L1001) →
  `bestModel.mape` [index.html:5908](index.html#L5908)) — but that measured value is **never
  written back** to `prod.mape`. The hint *"Auto from winner → SS → ROP → MC noise"* is therefore
  false; nothing auto-populates it.
- **Why it's wrong:** MAPE is an output of validation that then drives safety stock (`z × σ_LTD`),
  ROP, and MC noise. A user hand-typing MAPE = 5% silently fabricates a tighter safety stock than
  their data supports.
- **Fix direction:** make the field read-only, sourced from the winning model, with at most an
  explicit "manual override" flag (and a banner when override diverges from the measured value).

### MF-26 · 🔴 Salvage % hint advertises a Newsvendor model that doesn't exist
- The Salvage % hint ([index.html:5355](index.html#L5355)) claims it feeds the *"Newsvendor critical
  ratio and write-off cost."* Grep across all solvers: **no newsvendor / critical-ratio code exists.**
  The value is also inert (see Systemic + MF-2). So the input names a method that was never built,
  feeding solvers that ignore it.
- **Fix direction:** either implement the salvage/newsvendor path (ties to the Systemic perishability
  fix) or correct the hint and gate the field behind the feature that actually uses it.

### MF-27 · 🟠 Two different inputs both labeled "Demand Mode," with colliding values
- Per-SKU, Tab 02: `prod.demandMode` ∈ {mts-weekly, simultaneous, daily, mto} — "schedule *shape*"
  ([index.html:5333](index.html#L5333)).
- Global, Tab 03: `config.demandMode` ∈ {mts, mto} — "quantity-*level* behavior"
  ([index.html:5697](index.html#L5697)).
- Same label, two state homes, **overlapping value sets** ('mts'/'mto' appear in both), two distinct
  meanings. The card needs a paragraph to disambiguate them — the tell that the naming is the bug.
- **Fix direction:** rename one (e.g. per-SKU → "Schedule Shape", global → "Demand Policy") and make
  the value sets disjoint so they can't be confused.

### MF-28 · 🟡 Single-source values left editable in two places
- **Effective Tax Rate** is an editable field in two tabs — [index.html:3083](index.html#L3083)
  (`upC('taxRate')`) and [index.html:3852](index.html#L3852) (`SET_CONFIG`), both writing
  `config.taxRate`; the second's own hint says "Set in Company Profile" yet it stays editable.
- **Shelf Life** is editable on both Tab 02 ([index.html:4645](index.html#L4645)) and the forecast
  tab ([index.html:5334](index.html#L5334)), both writing `prod.shelfLife`.
- The correct pattern already exists in this app: the WACC field on downstream tabs is read-only with
  "edit on Tab 1… changes here would bypass the single-source-of-truth"
  ([index.html:11338](index.html#L11338)). Tax rate and shelf life just didn't follow it.
- **Fix direction:** make the secondary surface a read-only echo, matching the WACC pattern.

---

## Angles A–D · Output fidelity, failure modes, persistence, test coverage

The earlier sweeps all traced **forward** (input → solver). These four trace the
other direction and the edges. Net: the output surface and persistence are
**mostly faithful** — the defects below are the specific leaks, not a systemic rot.

### A · Output fidelity — displayed number vs solver-returned
Mostly clean: status badges, profitmix (`total_profit/revenue/margin_pct`), production
(`total_cost`), capital, and the MEIO **units** badge all read keys the solvers actually
emit. Two concrete leaks, both **masked by a `|| 0` fallback** so a real figure silently
renders as zero:

### MF-29 · 🔴 Dashboard VaR₉₅ is always 0 — key-name mismatch (`var_95` vs `var95`)
- Monte Carlo emits `var95` / `cvar95` ([montecarlo.py:139](montecarlo.py#L139)). The two main
  MC panels read them correctly ([index.html:7375](index.html#L7375), [index.html:11991](index.html#L11991)).
  But the **Solver Input Readiness dashboard** reads `v.var_95` (underscore)
  ([index.html:14218](index.html#L14218)) — a key that is never emitted — so it always prints
  `VaR₉₅: <cur>0`.
- **Fix direction:** read `var95` (and surface `cvar95`) in the dashboard line.

### MF-30 · 🔴 MEIO "WC tied up/period" is always $0 — `avg_in_transit_value` never emitted
- The MEIO panel prints `~{avg_in_transit_units}u in motion · ${avg_in_transit_value||0} WC tied up/period`
  ([index.html:6870](index.html#L6870)). procurement emits `avg_in_transit_units`
  ([procurement.py:1742](procurement.py#L1742)) but **never** `avg_in_transit_value` → the
  working-capital figure is permanently $0.
- **Fix direction:** emit `avg_in_transit_value` (units × unit cost) from procurement, or drop the
  half of the badge that can't be computed.

### B · Failure-mode behavior (infeasible / timeout / exception)
Four of five MILP solvers guard correctly — `if status != LpStatusOptimal: return {status, error}`
([capital.py:100](capital.py#L100), [production.py:373](production.py#L373),
[profitmix.py:387](profitmix.py#L387), [procurement.py:1420](procurement.py#L1420)). Two gaps:

### MF-31 · 🔴 transport reports `'status':'Optimal'` unconditionally — no status guard
- The allocation LP calls `prob.solve()` with **no status check** ([transport.py:152](transport.py#L152)),
  then reads `pulp.value(prob.objective)` / `pulp.value(x[i,j])` — which return `None` if the solve is
  infeasible/unbounded — and the outer function **hardcodes `'status':'Optimal'`**
  ([transport.py:157](transport.py#L157)) regardless of the real status. So an over-constrained
  transport problem is reported as Optimal with `round(None)` (crash) or garbage allocations.
- **Fix direction:** check `LpStatus[prob.status]`; return the real status + error like the other four.

### MF-32 · 🟠 MC / sensitivity / researcher swallow failures silently (empty `catch`)
- `setMcResult(await r.json())` etc. sit inside **empty catch blocks** with no `r.ok` check —
  Monte Carlo ([index.html:11805](index.html#L11805)), sensitivity ([index.html:11811](index.html#L11811)),
  researcher ([index.html:11823](index.html#L11823)). On a 500 / network drop / non-JSON body, nothing is
  shown and the panel stays blank or stale. The core solver console does this right
  (`if(data.error){setError(...)}`, [index.html:6471](index.html#L6471)) — the inconsistency is the bug.
- **Fix direction:** check `r.ok`, surface `data.error` / the exception in a visible error state.

### C · State persistence & scenario integrity
Mostly solid: debounced auto-save to `localStorage` excluding `solverResults`/`audit`
([index.html:16100](index.html#L16100)), a real `migrateState` v0→v1 ([index.html:16047](index.html#L16047)),
schema-version key, quota handling, and a reset that clears storage. Scenario restore clears
`solverResults` so a stale solve can't masquerade ([index.html:2747](index.html#L2747)). One real defect:

### MF-33 · 🟠 Full-state *export* but lossy *import* — silent data loss on round-trip
- "Save State (JSON)" writes the **entire** `state` ([index.html:7757](index.html#L7757); also
  [12464](index.html#L12464) labelled `full_state_backup.json`). But "Load State"
  ([index.html:7760](index.html#L7760)) only re-hydrates `config` (via `SET_CONFIG`) and `products`
  (via `UPDATE_PRODUCT`, and only `if(i < state.products.length)`). It **silently drops** `planning`,
  `budget`, `production`, `network`, `scenarios`, and any products beyond the current count.
  A save→load round-trip therefore loses most of the model while claiming success ("State loaded").
- **Fix direction:** make import reconstruct the full state (the same key set the auto-save persists),
  or route it through the same hydration path as `loadPersistedState`.

### D · Test coverage (meta-risk)
### MF-34 · 🟡 Zero automated tests — nothing pins any of MF-1…33 against regression
- No test files, no `pytest`/`unittest`, no `def test_` anywhere in the repo (verified). Every fix to
  the 33 findings above risks silently breaking another, and the two key-mismatch bugs (MF-29/30) plus
  the dual-payload defect (MF-19) are exactly what a contract test would have caught.
- **Highest-value tests to add (in order):** (1) a **UI-field → solver-key contract test** (the MF-18
  ask — asserts every state field reaches its payload key and every UI `result.*` read exists in the
  solver's return); (2) **solver golden-output tests** per module (fixed input → pinned objective/plan);
  (3) **grain-scaling unit tests** (daily/weekly/monthly holding & lead-time conversions, the MF-4/5/14 class).

---

## Parked methodology calls (need a product decision, not a bug fix)

- **#4** Working capital valued at sell-price vs cost (procurement).
- **#18** Three different safety-stock formulas across modules (procurement Heizer vs MC std-dev vs lot_sizing).
- (#7 → MF-8, #8 → MF-5, #12 → MF-3/MF-5, #19 → MF-7 now tracked above.)

---

## Sections audited
- [x] app.py (API layer, pipeline, rolling, researcher, sensitivity, whatif) — MF-3/6/11
- [x] profitmix.py — MF-2/5/8
- [x] production.py — MF-3 (interaction)/12
- [x] procurement.py — residual scan: grain clean (no live /52); dead shelf+salvage (Systemic); MF-17
- [x] montecarlo.py — MF-1/4/7
- [x] transport.py — MF-9/10
- [x] disaggregate.py — clean (rounding reconciled, totals balanced)
- [x] finance.py — clean (minor: `effective_duty_pct` includes non-duty costs — cosmetic label)
- [x] capital.py — clean (fixed last session)
- [x] lot_sizing.py — clean (fixed last session; EOQ-family correctly use annual rate)
- [x] forecast.py — MF-14 (otherwise sound: holdout MAPE, graceful degradation)
- [x] risk.py — clean (correct log-space HMM/Viterbi; trivial: `seed_mu` computed then discarded)
- [x] pattern_sensing.py — MF-13
- [x] calendar.py — MF-16
- [x] report.py — MF-15/18

## Forward UI sweep — DONE
- [x] Enumerated all UI call paths: 17 direct `fetch('/api…')` sites + a `runSolver()` registry.
- [x] Found TWO payload builders per core solver (primary `solverMode` dispatcher vs "Solver Input
      Readiness" dashboard) → MF-19 (the headline plumbing defect).
- [x] Identified solver params no payload ever sends → MF-20.
- [x] Spot-checked UI-only fields that are *intentionally* not consumed (e.g.
      `active_disruption_count`, [index.html:6243](index.html#L6243)) — documented, not defects.
- [x] Non-core endpoint field-by-field diff — DONE. Findings: MF-21 (transport demand-sensing +
      alloc LP dead), MF-22 (capital exclusivity/dependency/synthetic investments), MF-23
      (`/api/forecast/retrain` 404), MF-24 (finance shadow-compute + discarded WACC call).
- [x] Verified-clean endpoints (no dead inputs): `/api/forecast` ([index.html:4458](index.html#L4458) —
      only optional `season_length`/`holdout_periods` defaulted), `/api/demand/sense`
      ([index.html:12830](index.html#L12830) — fully wired), `/api/risk/regimes`
      ([index.html:9958](index.html#L9958) — `{rows,n_iter}` matches `detect_many`).

- [x] Conceptual-input pass (inputs that shouldn't be *collected*, distinct from dead inputs) →
      MF-25 (MAPE manual vs measured), MF-26 (salvage names a non-existent newsvendor), MF-27 (two
      "Demand Mode" inputs collide), MF-28 (tax rate + shelf life editable in two places).

- [x] Reverse + edge sweep (angles A–D): output fidelity → MF-29/30 (always-zero key mismatches);
      failure modes → MF-31 (transport unconditional Optimal) / MF-32 (silent empty catches);
      persistence → MF-33 (lossy import); test coverage → MF-34 (zero tests).

**The sweep is now complete in both directions: forward (input → solver: backend logic across 15
modules + API, UI→backend plumbing across all 17 call sites + 2 runSolver registries, and the
conceptual-input layer) and reverse + edges (solver → display output fidelity, failure-mode behavior,
state persistence, and test coverage). 34 findings + the systemic perishability header.**
