# app_v2 — Master Execution Plan (single source of truth)

**This is the operating doc.** Created 2026-06-02 to consolidate every prior finding into one
executable, dependency-ordered, benchmark-anchored plan — so no topic is re-read or re-derived.

> **Doc hygiene / context contract**
> - **This file is the entry point and the work queue.** Execute from §4 (roadmap) + §5 (tasks).
> - **Compaction-safe by design.** Compaction summarizes the *conversation*, never files. The full
>   thoroughness lives in two files on disk that **persist intact across every compaction**:
>   `AUDIT.md` (~380 lines, §0–I) and `CRITIQUE_R2_DEMAND_AND_SEGMENTS.md` (~545 lines, Parts A–H).
>   This index is shorter *because* it is an index; **no detail is lost** — it sits in the evidence
>   files, retrievable by finding-ID. To execute a task thoroughly: read its row here, then open the
>   cited finding-ID(s) for the full grounded detail, then act.
> - **Evidence is frozen, not re-read end-to-end.** Every ledger row (§3) cites a finding-ID
>   (e.g. `B1`, `G2`, `H6`). The ID **is** the pointer — open only that finding for the "why"; the
>   row gives the "what." Never re-read the whole archive; never duplicate evidence text here.
> - **When a task ships, update its row's Status here** (☐→⏳→✅) — this file is the live tracker.
> - **Memory** (`app-v2-audit-findings.md`) points here as the index.

---

## §0 · Benchmark & maturity ladder — "what level do we want?"

### Maturity ladder (score every module 0–4)
| L | Name | Definition |
|---|---|---|
| **L0** | Mockup | hardcoded display, no compute. A number that looks solved but isn't. |
| **L1** | Wired | calls the real solver; shows real output with provenance. |
| **L2** | Governed inputs | the user can define the real drivers (no fabricated defaults); inputs validated; outputs legible (per-period numbers, units, as-of). |
| **L3** | Closed-loop | actuals feedback + recompute cascade + change log + rolling re-plan + trigger monitors. |
| **L4** | Benchmark-parity | matches IBP/Kinaxis/o9 depth on that module's core capability. |

### Benchmark per module (what "parity" = L4 means)
| Module | Benchmark we measure against | L4 core capability |
|---|---|---|
| Demand | SAP IBP Demand / Demand Sensing | stat+ML competition, **demand sensing on actuals**, promo/causal factors, consensus, **hierarchical reconciliation** |
| Supply / Procurement | IBP Response & Supply, Kinaxis | constrained MRP, **stepwise freight / truck capacity**, allocation, what-if, locked-PO replan |
| Inventory | IBP Inventory Optimization | **multi-echelon SS placement** (guaranteed-service), policy autopilot for steady parts |
| Plan / S&OP | IBP S&OP | level/chase, capacity duals tied to **real resources**, scenario, gap-to-plan |
| Production | Blue Yonder / APS | finite-capacity schedule, **sequence-dependent changeover**, calendar-aware MPS |
| Finance | driver-based FP&A (this is where the giants are *weak* — our wedge) | **capital structure, source-weighted hurdle, EVA, integrated ops↔finance loop** |
| Risk / Scenarios | IBP control tower + Monte Carlo | live control tower, MC/CVaR on the **committed** plan, what-if |

### Current self-score vs target (this is the honest assessment)
**TARGET = L4 (benchmark-parity) on EVERY module.** (User directive 2026-06-02: L4, not L2.)
| Module | Now | Target | L2→L3→L4 distance | Gap driver |
|---|---|---|---|---|
| Demand | **L4** (W1 + W9 + **DM-A prediction intervals · DM-B promo-uplift attribution · DM-C sensing auto-cadence/breach-flag**) | **L4** | ✅ reached — ensemble, accuracy-by-horizon, reconciliation, CSV import, NPI, PI band, promo attribution, closed sensing loop | A1,A3,A5,A6,A8,H3 |
| Supply/Procurement | **L1−** | **L4** | far | B1,F4,H2 |
| Inventory | **L4−** (was L3) | **L4** | **MN-A…C built**: real per-FG BOM cohorts + joint place+pool (min-holding echelon) + pairwise ρ matrix on top of W8 pooling + GAP-MEIO placement + S-3 autopilot | H5,H6,H7,EOQ |
| Plan/S&OP | **L3** (W4 ✅ + PL-A line dual + **W10 S&OP cockpit + scenario compare**) | **L4** | closing | E1,E2,E3,E4 |
| Production | **L3−** (W3 ✅ + PR-A time-phased / PR-B-D + **PR-4 campaign opt**) | **L4** | closing | C2 |
| Logistics | **L4−** (W5 + **LG-1 allocation-from-solve · LG-2 per-SKU flows + real weights**) | **L4** | allocation matrix + flow map from the real solve; mix-accurate tonnage; CoG derived | B2,C4 |
| Finance | **L3–L4** (W5 + FV-A…D + **EVA-driven scenario branch — prune-and-re-plan, ops↔finance loop**) | **L4** | the wedge closed: a finance EVA flag drives a real ops re-solve and reports the cost/fill verdict | G-residual,H1 |
| Risk/Scenarios | **L3** (W6 ✅ — MC on committed plan + CVaR + live control tower + **W10 MC what-if bot re-solves**) | **L4** | closing | F1,H9,C6 |
| **Platform** (orchestration) | **L4−** (W7 `runFullLoop` + solve cache + W11 scenario engine + **event-sourced replay/version-diff/cherry-pick-merge: `scenarioDiff`/`mergeScenarioFields`/`replayLog` + `ScnVersions`**) | **L4** | event-sourced state, recompute DAG, full audit trail, branching/versioning, concurrent what-if, version diff+merge | A2,H4,D5 |

**Decision encoded as the plan:** **every module reaches L4 (benchmark-parity).** Critical reality:
**L4 is reached *through* L2→L3 — it is not a shortcut around them.** You cannot have IBP-grade
demand sensing (L4) without first wiring actuals + the recompute loop (L3), which needs governed
inputs (L2), which needs the solver wired (L1). So the roadmap's early waves are the *necessary
path* to L4, and the later waves (§4, W7+) are the L4 depth per module. This is a multi-cycle
build; the wave gates (§4) keep each step verifiable so quality is provable, not asserted.

### What L4 means, concretely (the unambiguous bar per module)
| Module | L4 = benchmark-parity means |
|---|---|
| **Platform** | event-sourced state, deterministic incremental recompute DAG, full audit trail, scenario branching/versioning, concurrent what-if (Kinaxis-style) |
| **Demand** | stat+ML competition **+ ensemble**, demand sensing on actuals, promo/causal regressors, consensus workflow, **hierarchical reconciliation** (product×location×time), accuracy-by-horizon + forecastability analytics, NPI like-modeling, CSV import |
| **Supply/Procurement** | constrained multi-echelon MRP, **stepwise freight + truck/container packing**, supplier allocation & sourcing rules, capable-to-promise, locked-PO rolling replan, what-if |
| **Inventory** | **multi-echelon SS placement** (guaranteed-service / Clark–Scarf) across RM/WIP/FG, policy autopilot for steady parts, postponement, target-service optimization |
| **Plan/S&OP** | capacity tied to real resources, scenario compare, gap-to-plan, **financial reconciliation of the plan**, executive S&OP cockpit |
| **Production** | finite-capacity scheduling, sequence-dependent changeover, shift/calendar model, campaign optimization, real per-line/per-SKU Gantt |
| **Finance** | source-weighted hurdle, **min-WACC structure (DSCR-capped)**, EVA/ROIC scoreboard, required-sales bridge, driver-based P&L, full appraisal (NPV/IRR/payback/PI/risk-adj), tax+depreciation, **fully integrated with the ops plan** (our wedge — beyond IBP) |
| **Risk** | live control tower, MC/CVaR on the committed plan, what-if bot, disruption simulation, risk-adjusted decisions |

---

## §0.5 · ✅ DECISIONS — RESOLVED 2026-06-02 (build is now unblocked)

**All three product decisions are resolved (user, 2026-06-02). These are now binding constraints.**

**D-DEC-1 · Tax / duty jurisdictions → RESOLVED: (a) US + India, SEEDED + manual override.**
Build duty/tax engines for **India and USA**, driven by a **seeded rate table we maintain**, but the
user can **manually edit any rate** when there's a discrepancy. (= option (a) + seeded-with-override.)
Implementation note: rate table is a governed input (P3) with `seed` provenance; a manual edit flips
that cell's provenance to `user`. Gates F-7 (tax/depreciation) and S-1 (landed cost).

**D-DEC-2 · "Consolidated view" shape → RESOLVED: (a) combined — per-item dossier + company P&L rollup.**
Two linked views: drill into one SKU's economics, roll up to the company P&L. (User: "if combined is
better then go for it" → the linked dossier+rollup IS the combined view.) Gates F-3 / F-4.

**D-DEC-3 · Contract / freight depth → RESOLVED: (b) freight-included ⇒ stepwise truck/container cost.**
Start with the simpler stepwise model (freight = f(qty, trucks), kills flat `S(i)`). Full per-lane
transporter contracts deferred to later (phased (b)→(a), i.e. option (c) with (b) first). User:
"usually contracts, but for now stick with option b of freight included." Gates S-2.

> Decisions cleared. The first *build* wave is **W0 (Platform foundations)** — starting now.

---

## §1 · Ground rules (frozen constraints)
1. **`index.html` is untouched** — never overwrite/mutate/risk it. (memory: redesign-build-approach)
2. **Backend solver *logic* is frozen** — we change *payloads/inputs* and *wiring*, not the math,
   except explicitly-scoped new modules (e.g. MEIO placement, capital-structure optimizer) added
   as *new* files. Packaging/shims allowed.
3. **No faking.** Every on-screen number is solved/derived or an honest empty state — never a
   labelled fake. (user-enforced)
4. **Provenance everywhere** — solved/derived/seed badge + as-of on every output card.
5. **One dataset** — all modules read the same committed demand / BOM / network / cost master.

---

## §2 · Root cause & the one pattern (why there are "so many" findings)
A single systemic cause, not N independent bugs: **app_v2 is a presentation reskin that dropped
index.html's domain engine and starves the (genuinely strong) backend solvers with thin payloads.**
Five recurring symptoms (Parts D, F, H): (1) backend richer than payload, (2) hardcoded outputs
beside live ones, (3) grain mismatch / no calendar, (4) entry-point ambiguity, (5) no actuals /
event log / recompute cascade. **Implication: most work is wiring + input-surface + orchestration,
not new math.** That is why this plan front-loads the Platform layer.

---

## §3 · Module ledger (consolidated — each row cites a finding-ID for the "why")

Legend: **BE?** = backend already does it (✅ wire it / ➕ build new / ⚠ partial). Sev 🔴🟠🟡.

### 3.1 Platform / Orchestration (cross-cutting — build first) — ✅ W0 SHIPPED
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| P1 | Recompute dependency DAG | 🔴 | ➕ | `SOLVE_DEPS` + `markStale`/`markSolved`/`useStale` in store.jsx; auto-flags from source write-site | H4,D5 | ✅ |
| P2 | Actuals + event log | 🔴 | ➕ | `events[]` + `logEvent`/`useEvents`; `DemActuals` actuals grid → `/api/demand/sense` | A2,H3 | ✅ |
| P3 | Input-surface framework | 🔴 | ⚠ | `SolverInput` (validated, honest seed→user, no fabricated default); proven on Sourcing service level | B1,G,F2 | ✅ |
| P4 | Provenance + no-fake sweep | 🟠 | — | touched cards carry Provenance/as-of; demand seed tables re-badged honest | C5,F1,H1 | ✅ (touched stages; full sweep ongoing per stage) |
| P5 | Per-stage item-selector / as-of header | 🟡 | — | `StageContext` (item · horizon×grain · as-of) on Demand + Sourcing | E1,E4,C5 | ✅ (roll out to remaining tabs as wired) |

### 3.2 Demand — ✅ W1 SHIPPED 2026-06-02 (D-1…D-4, D-6)
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| D-1 | Promo/event → forecast | 🔴 | ✅ | send `promo_periods` (+holidays); real promo calendar bound to horizon | A1 | ✅ governed promo/holiday editor → `fcPayload.promo_periods`/`holidays`/`horizon_start_date`; verified a flagged future period lifts the live forecast |
| D-2 | Per-period numeric forecast table | 🟡 | ✅ | surface `fcastArr` as P1..Pn table | A3 | ✅ `PerPeriodTable` (date + units + vs-avg, promo rows flagged) |
| D-3 | Lifecycle multiplier actually applied | 🔴 | ⚠ | multiply statistical base before commit | A5 | ✅ `LifecycleCard` — OPT-IN (default None), shows base→×mult→shaped, explicit reversible Apply writes committed series |
| D-4 | Override/Promo/Consensus consolidation | 🟠 | ⚠ | one "what's committed & why" panel, one grain | A6 | ✅ `DemCommit` — per-item committed dossier + company rollup (D-DEC-2 combined); replaced illustrative consensus seed |
| D-5 | Ensemble (top-N MAPE-weighted) gated on depth | 🟠 | ➕ | blend, only when data deep enough | A4 | — (W9) |
| D-6 | Demand sensing wired + trigger monitor | 🔴 | ✅/➕ | wire `/api/demand/sense`; **build MAPE-breach / bias monitor** | H3 | ✅ sensing wired (W0) + `TriggerMonitor` on live MAPE/bias/tracking-signal/out_of_control |
| D-7 | Data import (CSV, date detect, bucketing) | 🔴 | ➕ | real ingestion + column mapping | A8 | ✅ **W9 tail** — `parseHistoryCsv` (delimiter+header detection) + `bucketHistory` (date→ISO month/week/day roll-up) → `histImports[sku]`; `historyFor()` makes the forecast compete models on the uploaded series. `DemImport` paste-CSV card (preview + sparkline + "Use as history", clear-to-seed). **+ NPI like-modeling**: analog SKU × scale% × adoption-ramp → like-modeled committed prior (`setItemDemand`, provenance derived) for a new/low-history item. |
| D-8 | Hierarchical reconciliation surfaced | 🟠 | ✅ | wire `reconcile.py` output | A8 | ✅ surfaced in `DemHorizon` (W9 core) |

**W1/W9 improvement areas (Demand → L4) — ✅ ALL BUILT 2026-06-03 (DM-A…C):**
- **DM-A · per-period prediction interval — ✅ DONE.** `forecast.py` now emits `forecast_pi` = per-step `{p10, point, p90}` on the winner, σ from the **out-of-sample holdout error** (in-sample fitted residuals badly understate uncertainty for overfit ML models), widening with horizon (σ_k=σ·√(k+1), ±1.2816σ). `PerPeriodTable` gains a P10–P90 column + `ForecastChart` shades the uncertainty cone. Verified live: band 3.9→9.6 over the 12-period horizon (widens, honest).
- **DM-B · promo uplift attribution — ✅ DONE.** `forecast.py` re-runs the winner with promo flags STRIPPED → a baseline counterfactual; `promo_attribution` = per-period baseline vs uplift + `promo_uplift_total`. `PerPeriodTable` shows a "promo Δ" column + a causal-contribution readout. Honest: a model that never saw a historical promo (or has no promo regressor) yields zero uplift — verified (uplift 0 when only a future promo is flagged, the correct answer).
- **DM-C · sensing auto-trigger cadence — ✅ DONE.** `DemActuals` now auto-re-senses (debounced 700ms) when actuals change once a baseline exists — the loop closes without a manual click (manual button still logs `actuals`; auto path is silent). `TriggerMonitor` gains a hook-safe `BreachFlagger` child that, on a NEW breach signature, auto-flags downstream solves stale (`markStale('demand')`) + logs an immutable `auto_trigger` event — the demand half of the L3 closed loop.

### 3.3 Supply / Procurement / Inventory — ✅ W2 COMPLETE 2026-06-02 (S-1…S-8)
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| S-1 | Feed `landed_cost` into procurement | 🔴 | ✅ | pipe landed-cost solve into `bomParts` (stop using raw cost) | B1 | ✅ governed per-part `Sourcing Terms` (import flag + duty/freight %) → `partsWithSourcing` sets `landed_cost`; MILP provably plans on landed (billet 228→255.36 ⇒ +₹41K) |
| S-2 | Stepwise freight / truck capacity (kill flat `S(i)`) | 🔴 | ✅ | send `transport_modes`/`contracts`; freight = f(qty, trucks) not flat ₹120 | B1, EOQ | ✅ `SrcFreight` truck-step on the real MILP order qty: ⌈qty/units-per-truck⌉×₹/truck, shows the marginal-truck cliff |
| S-3 | Inventory policy as **autopilot for steady parts only** | 🟠 | ✅ | (s,S)/order-up-to from `policy.py`, gated by ABC/XYZ; **EOQ never beside a MILP plan, never for one-offs** | H2, EOQ | ✅ `SrcPolicy` shows EOQ/(R,Q)/(s,S) ONLY for steady (CV≤0.5); lumpy (CV>0.5) explicitly flagged MILP-only, no EOQ |
| S-4 | Rolling re-plan UI + nervousness | 🟠 | ✅ | wire `/api/solve/rolling`; show wave churn | H2 | ✅ `SrcRolling` + **rolling-endpoint nervousness wiring fix** (read real `materials[].purchase_orders`, relative-period churn over open overlap); per-wave + total churn, STABLE/NERVOUS verdict |
| S-5 | Postponable vs pinned PO flag | 🟡 | ⚠ | surface release-timing slack | H5 | ✅ `SrcPostpone` derives per-PO release slack from the MILP's OWN solved inventory path (cover ≥ Σ following consumption ⇒ postponable; 0 ⇒ pinned JIT); no extra solve, no faking — reports deferrable cash + which POs to protect on a supplier slip |
| S-6 | Multi-echelon SS placement (RM/WIP/FG) | 🔴 | ➕ | **new** guaranteed-service layer; per-node balance is the scaffold | H6 | ✅ shipped as `meio.py` (Graves–Willems guaranteed-service, exact MILP) + `SrcMEIO` — see §GAP-MEIO; places ONE buffer at the cheapest decoupling point, surfaces make-to-order FG (`df3ec2f`) |
| S-7 | Costly-item / MTO preset (newsvendor h vs p) | 🟠 | ✅ | expose MTO mode + CVaR buffer for costly parts | H7 | ✅ `SrcNewsvendor` wires `/api/solve/cvar` per costly part: critical ratio p/(p+h), EV vs CVaR-β order-up-to + robustness premium; low CR (holding dominates) ⇒ flagged make-to-order (verified h=300/p=40 ⇒ CR 12%, safety 0) |
| S-8 | MRP-at-scale UX (10+ BOM) | 🟡 | — | exception-based roll-up/drill-down, not a giant grid | H (BOM scale) | ✅ `SrcExceptions` scores every part on the solve (zero-cover / capital-concentration / many-releases) + FG shortages; surfaces only flagged parts, rolls up the clear ones — the readable-at-scale pattern, not a part×period grid |

**W2 improvement areas (Supply → L4) — ✅ ALL BUILT 2026-06-03 (SS-A, SS-B, SS-D; SS-C shipped W8):**
- **SS-A · multi-part truck consolidation — ✅ DONE.** `SrcFreight` now adds a supplier-level consolidation panel: each part of the SELECTED part's supplier fills a fraction (ordered ÷ units-per-truck) of a truck, so the supplier's trucks = ⌈Σ fractions⌉ vs Σ⌈fraction⌉ booked part-by-part — the bin-packing dividend (trucks + ₹ freight saved). Uses the SAME MILP order qty per part (no extra solve). `partsWithSourcing` now carries `supplier` through.
- **SS-B · joint replenishment for shared-supplier parts — ✅ DONE.** `policy.py` adds a `joint_replenishment` roll-up: parts sharing a supplier ordered on a COMMON review cycle T*=√(2(S+Σsᵢ)/ΣDᵢhᵢ) amortise the per-PO major cost (governed `joint_major_cost` ₹2,500); reports independent vs joint annual cost + saving per supplier group. `SrcPolicy` renders the JR table. Verified live: SUP-012 (CN-SEAL9+CN-BLT04) → common 14.25-period cycle, ₹7,312/yr saved.
- **SS-C · MEIO risk-pooling across shared parts.** ✅ **SHIPPED in W8** as new `meio_network.py` (square-root law: σ_pool=√(Σσ²+2ρΣσᵢσⱼ) ≤ Σσ) + `SrcMEIONet` — see §GAP-MEIONET. Pools each shared part's buffer across the SKUs that consume it; frees the cross-tree SS capital single-tree MEIO leaves on the table.
- **SS-D · landed cost ↔ live FX table — ✅ DONE.** New `fxFactor(src)` = current rate ÷ FX_BASE (the seeded `config.fxRates`) for an imported part's quote currency (default USD); `effLandedCost` multiplies by it, so editing the FX table (`config.fxRates`) re-prices EVERY imported part's landed cost — one source of truth for $→₹ that re-flows the procurement MILP, the policy autopilot, MEIO and the MC cost shocks. At seed FX the factor is 1 ⇒ byte-identical until a rate moves. `SrcTermRow` shows the live `FX ×factor` on imported rows.

**W8 improvement areas — ✅ ALL BUILT 2026-06-02 (MN-A…C):**
- **MN-A · real per-FG BOM lines.** ✅ New `M.skuBom` multi-product BOM master (which FG consumes which part, at what qty). `meioNetworkPayload` builds each part's pooled cohort from only the SKUs that actually consume it (each with its own qty_per), so each part is shared by a real subset (3–4 SKUs), not all-6-FG — the cohort and its dividend are now exact.
- **MN-B · joint place+pool.** ✅ `meio_network.py` `_part_pool` now evaluates PLACEMENT echelons (raw upstream: cheap unit / long lead → more SS; finished postponed: dearer / short lead → fewer SS) and places the pooled buffer at the min-holding-₹ echelon — pooling AND placement in one model. `placed_at` per part + a "Place at" column in `SrcMEIONet`.
- **MN-C · pairwise correlation matrix.** ✅ `_part_pool` accepts an n×n `corr_matrix` (ρ_ij per pair) used in the σ_pool double sum; `meioNetworkPayload` builds it from XYZ-class co-movement (same class → ρ, one apart → ρ/2, two apart → independent) behind a "pairwise ρ" toggle (⊞), so correlated cohorts pool poorly and independent ones richly. Scalar ρ remains the default.

- **MN-D · MC cost shocks off per-SKU `skuBom` — ✅ BUILT 2026-06-03.** `montecarloPayload` now builds each finished SKU's costed bill from `M.skuBom` (only the parts it actually consumes, at that SKU's own qty_per) instead of the single shared BOM — so a material-price spike on a part used by 3 of 6 SKUs raises cost for those 3, not the whole portfolio uniformly. landed_cost carries duty/freight % AND the live FX factor (SS-D). Falls back to the shared `M.bom` when a SKU has no cohort. Verified live: TPA-9904 (RM-BRG18+CN-LUB02 only) solves on its own bill.

### 3.4 Plan / S&OP — ✅ W4 COMPLETE 2026-06-02 (PL-1…PL-5; PL-A line-dual LP carried)
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| PL-1 | Tie aggregate capacity to the **real line registry** | 🔴 | ⚠ | stop showing labor capacity as the line capacity | E1,E2 | ✅ `lineRegistryCapacity()` = Σ `M.lines.cap`; payload `max_workforce = Σcap÷rate` ceiling; chart/table relabeled "labor cap" vs the registry ceiling |
| PL-2 | Fix labor-dual → line-CapEx mis-wire | 🔴 | ⚠ | capital must consume a line/machine dual, not the labor dual | E2,F3 | ✅ aggregate duals relabeled **Labor (worker-period)**; new **Line Capacity Pressure** card (disaggregated load vs registry cap) is the line/machine CapEx signal; "invest in {line}→Finance" link gated on a line actually binding |
| PL-3 | Real plan cost inputs (replace `PLAN_PARAMS` seeds) | 🟠 | ✅ | governed cost-input card | E1 | ✅ `PlanParamsCard` — 7 governed SolverInputs (rate/reg/OT/holding/hire/fire/wage), seed→override, writes `config.planParams` |
| PL-4 | Disaggregation clarity (which family/horizon, solved-vs-seed) | 🟡 | ⚠ | header + provenance | E4 | ✅ header names family (all FG) + horizon (months) + BASIS (solved vs seed-share); badge + provenance flip |
| PL-5 | Workforce plan tie-back (covers which gap) | 🟡 | ⚠ | link hire/OT to the capacity gap it fills | E3 | ✅ "Fills gap (u)" column = demand − rate×(start-of-period heads); Reading ties hire+OT to the hole they close |

**W4 follow-up — ✅ COMPLETED 2026-06-02 (next round):**
- **PL-A · true ₹ line shadow price — ✅ DONE via new `linecap.py`.** Built option (a): a **continuous** min-cost assignment LP — `prod[k,l]` + `short[k]`, `minimize Σ cost·prod + Σ lost_margin·short` s.t. `Σ_l prod + short = demand` and `Σ_k prod ≤ cap[l]` — whose **capacity-constraint dual is the valid ₹/unit shadow price** (continuous LP, so duals are real, unlike the aggregate/production MILPs). Endpoint `/api/solve/linecap`; `PlanCapacity` adds a "₹ Price capacity" run + a "₹ shadow / cap unit" column; lost-margin per SKU = its contribution (`price−cost`). Verified live: at TPAC volumes every line dual = **₹0** (slack → honest no-CapEx, matching the pressure card); a pressured probe binds Line-1 at **₹1,200/unit** with 360 u short — the mechanism is live for when demand grows. Finance F-8 consumes this as `capacity_shadow_price` (loop closed: Plan binding-line → Finance CapEx).

### 3.5 Production — ✅ W3 COMPLETE 2026-06-02 (PR-1,2,3,5,6 shipped; PR-4 + new gaps carried)
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| PR-1 | Wire `/api/solve/production` → real Gantt | 🔴 | ✅ | per-line swimlanes, per-SKU filter from `gantt[]` | E5 | ✅ `productionPayload` + `ProdMPS` (per-SKU scope toggle) |
| PR-2 | Calendar-aware MPS (Sun/holiday exclusion, real dates) | 🔴 | ✅ | use `plant_calendar`; drill month→week→day-with-dates | E7,C2,D | ✅ `productionWorkDays` (Sun+holiday excl); day-drill spreads solved wk qty over dated working days |
| PR-3 | Surface sequence/changeover (asymmetric) + saving | 🟡 | ✅ | already correct (`sequencing.py`); just show it | H8,E6 | ✅ `ProdChange` (pre-existing, retained) |
| PR-4 | Campaign run-length lever + explain setup-vs-holding | 🟠 | ⚠ | expose min-run; show why AAAA-then-BBBB | E6 | ⏳ deferred — needs a min-run param in production.py (see W3 follow-ups) |
| PR-5 | Cycle-time simple default, OEE behind Advanced | 🟡 | ✅ | reorder UI; OEE optional (already supported) | F5 | ✅ `ProdCycle` flat-default + Advanced·OEE checkbox |
| PR-6 | Low-util shutdown rec surfaced | 🟡 | ✅ | from `production.py` | E5 | ✅ `ProdCapacity` — line util/OT/changeovers + 3 live shutdown recs (governed rate) |

**W3 follow-ups — ✅ COMPLETED 2026-06-02 (next round; PR-A is additive/opt-in backend):**
- **PR-A · time-phased MPS — ✅ DONE.** `production.py` gains an **opt-in** (`params.time_phased`) no-backorder inventory balance per (product, period): `inv[k,t] = inv[k,t−1] + Σ_l x[k,l,t]·fy − demand_by_period[k,t] ≥ 0`, with a `holding_cost_per_unit` term that penalizes early build. Default OFF ⇒ the W3 makespan-min behavior is **byte-identical** (frozen-logic respected via additive gating). Verified live: OFF front-loads `[300,300,32,0,0,0]`; ON tracks demand `[53,53,105,105,158,158]` vs `[50,50,100,100,150,150]` with ~0 ending inventory. Payload (`productionPayload` sends `demand_by_period`+`time_phased`+`holding_cost_per_unit`), UI (`ProdParams` toggle+holding SolverInput, `ProdMPS` on-hand-cover row, `projected_inventory` output). Note: **PR-4** (campaign min-run lever) is still distinct/open — see below.
- **PR-B · governed cycle/line edits — ✅ DONE.** `ProdCycle` Cycle-Time → `SolverInput` and Assigned-Line → governed `Select`, both writing `config.prodRouting[sku]` (seed→override) and flowing into `productionPayload` via `opts.routing` (re-pins the SKU + re-prices throughput on re-run). MOQ/Batch left display-only (no consumer until PR-4).
- **PR-C · Architecture util from the solve — ✅ DONE.** `ProdArch` "Util @ plan" now reads the solved gantt (monthly-equiv = Σ solved units ÷ horizon-wk × 4.33 ÷ cap) — the SAME basis as the Cycle-tab Line-Load — falling back to the annual-demand estimate (labelled `·seed`) only before the first solve.
- **PR-D · per-line changeover matrix — ✅ DONE.** `productionPayload` now emits a **per-line changeover sub-matrix** over only the SKUs pinned to that line (was one global 4×4 averaged across all lines); a line running one SKU correctly has no changeover. `production.py` already consumes per-line `changeover_matrix`.
- **PR-4 · campaign run-length lever — ✅ DONE (W10).** New `campaign_min_run` param in `production.py`: when > 0, an active lot must make ≥ `min_run` units (`x[k,l,t] ≥ run_floor·y[k,l,t]`, capped to route capacity), forcing CAMPAIGNS — long single-SKU runs (AAAA-then-BBBB) instead of fragmented small lots — trading more holding for fewer setups/changeovers. Returns a `campaign` summary (runs, avg_run_units, total_units). Default 0 ⇒ floor=1 ⇒ byte-identical to W3. UI: `ProdParams` "Campaign min-run" SolverInput + a live campaign readout (runs / avg-run / campaigned-vs-free-lots tag). `productionPayload`/`productionOptsFromConfig` thread `campaignMinRun` (loop too). Verified live (HTTP + direct): time-phased baseline 6 lots@105u (cost 304) → min-run 250 consolidates to 2 lots@316u (cost 982) — the setup↔holding trade made explicit.

### 3.6 Logistics — ✅ LG-1, LG-2 BUILT 2026-06-03
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| LG-1 | Allocation matrix from solve (kill literal) | 🟠 | ✅ | render real `mode_summary`/allocation | B2 | ✅ `LogAllocation` builds the lane×mode matrix + the flow map FROM the solved `shipments[]` (each lane's chosen mode = its `recommended`, value-share line weight); the hardcoded `alloc`/`flows` literals are now the pre-solve fallback only. |
| LG-2 | Per-SKU outbound flows + real weights | 🟡 | ⚠ | replace flat 3kg/unit + even-split | B2 | ✅ `transportPayload` uses per-SKU shipping weights (`_SKU_WEIGHT_KG`/`skuWeightKg`, honest seed masses) → mix-accurate lane tonnage (was flat 3 kg/unit), and emits `params.sku_flows`; new `LogSkuFlows` card shows the per-SKU monthly units × kg/unit × mix-% breakdown. |

### 3.7 Finance (the wedge) — ✅ W5 COMPLETE 2026-06-02 (F-1…F-9)
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| F-1 | Source-weighted hurdle (land/retained/promoter/PE; bank/family) | 🔴 | ➕ | blended Ke/Kd → real hurdle; wire the inert Equity-Sources card | G2,H1 | ✅ **new `capital_structure.blended_hurdle`** + `/api/calc/hurdle`; `FinCapital` governed equity/debt source table (seed→override) → blended hurdle. Verified 11.15% from the real ₹15 Cr stack (E/D 62/38) — replaces the textbook single-Ke |
| F-2 | Min-WACC capital-structure optimizer | 🔴 | ➕ | WACC-vs-leverage curve, DSCR-capped, find trough | G1 | ✅ **`capital_structure.min_wacc_structure`** + `/api/calc/wacc-structure`; Hamada re-lever + widening credit spread ⇒ U-curve; DSCR covenant caps the trough. Verified min at d=15% (12.36%), d≥0.6 breaches 1.5× cover |
| F-3 | Required-sales bridge (mix slider → profit-mix) | 🟠 | ➕ | (WACC−ROIC)×capital ÷ blended margin | G4 | ✅ `FinValue` derived: `(hurdle·capital − NOPAT)÷(1−t)÷margin%` = extra revenue to clear the capital charge (slider→profitmix deferred to W10) |
| F-4 | EVA/ROIC-vs-WACC scoreboard → shutdown/pivot | 🔴 | ➕ | per-SKU/unit/consolidated value-destroyer flag | G3 | ✅ `FinValue` EVA scoreboard: per-SKU contribution-NOPAT vs hurdle×capital (capital = COGS÷turns + fixed-asset revenue share); ROIC<hurdle ⇒ DESTROYS flag + company rollup (D-DEC-2 combined) |
| F-5 | Product-economics segmentation (mfg/resale/light-proc) | 🟠 | ➕ | per-SKU margin build → portfolio rollup | G5 | ✅ `FinValue` ABC margin-build segmentation (data is all-mfg ⇒ ABC class is the real segment axis) + contribution-share bar |
| F-6 | DSCR covenant + DSRA | 🟠 | ⚠ | enforce DSCR (caps debt→links F-2); surface returned dscr | G6,H1 | ✅ `FinCapital` DSCR card off F-2's feasible optimum (NOI ÷ service) + DSRA = 6-mo service (restricted cash) |
| F-7 | Tax + depreciation shield into NPV | 🟡 | ⚠ | tax section; WDV shield in cash flows | G7 | ✅ NPV card toggle: `CFₜ = opCFₜ·(1−t) + depₜ·t` (SLM dep over project life) → real after-tax DCF at the blended hurdle |
| F-8 | Wire Investment cards to `capital`/`capital_capacity` | 🔴 | ✅ | kill hardcoded Investment/duals/verdict | H1,F3 | ✅ `FinInvest` → `/api/solve/capital-capacity`: each line a `capacity` option (CF derived from hrs×margin/hr×util−opex), solver picks which/when + risk-adjusted NPV; **consumes Plan PL-A line shadow price** as `capacity_shadow_price`. Killed the mock Investment/duals/verdict |
| F-9 | De-mock Cash subtab (WC/ledger/EVM/CCC) | 🟠 | ⚠ | derive from real ledgers or honest empty | H1 | ✅ honest "illustrative seeds — no live ledger feed" banner; the decision-grade solved/derived numbers moved to Capital + Value subtabs (no fake-looks-solved) |

**W5 improvement areas — ✅ ALL BUILT 2026-06-02 (FV-A…D):**
- **FV-A · EVA capital base from the real ops plan.** ✅ New `finOpsCapital()` reads the cached solves: production `projected_inventory` (avg ending FG inventory × unit cost = real WC), pooled SS value from the W8 network-MEIO solve, and the fixed-asset register at NET block (Σ WDV). `finEva` now sizes per-SKU capital = solved FG inventory + COGS-share of pooled SS + revenue-share of net-block assets; falls back to COGS÷turns only when no production solve is cached. Scoreboard badges the basis (`solved inventory` vs `turns proxy`) + solved provenance.
- **FV-B · per-SKU required-sales bridge.** ✅ `FinValue` now adds a per-destroyer table: each value-destroyer's required sales = (hurdle·capitalᵢ − NOPATᵢ)÷(1−t)÷**its own** contribution-margin%, surfacing that a thin-margin SKU needs disproportionately more revenue than the company-blended bridge implies.
- **FV-C · F-8 margin/hr from the solved bottleneck.** ✅ `FinInvest` reads the cached `linecap` (PL-A) dual: a line's added-hrs value = shadow_price(₹/unit) × units/hr **only when that line is binding**; a slack line earns ₹0 from expansion. So a line is valued for expansion only where the committed schedule is genuinely capacity-bound (falls back to derived contribution/hr until linecap is solved).
- **FV-D · WDV depreciation shield (India).** ✅ NPV card now has an SLM/WDV toggle + governed WDV rate; WDV front-loads the shield via the same declining-balance closed form `finance.calc_depreciation('WDV')` uses, raising the after-tax NPV and shifting the lease-vs-buy call.

### 3.8 Risk / Scenarios — ✅ W6 COMPLETE 2026-06-02 (R-1…R-4)
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| R-1 | Wire Monte Carlo on the **committed** plan | 🔴 | ✅ | `/api/solve/montecarlo`; VaR/CVaR/fill dist | F1,H9 | ✅ `ScnRisk` MC card + `montecarloPayload`; **replays the cached production schedule** (policy=plan when a `production` solve is cached — via the new cross-stage solve-result cache) against demand+cost shocks; cost histogram (≥VaR95 tail flagged), VaR/CVaR95, fragility, fill dist, `policy_simulated` badge. Verified: plan mode → fill 97%, base-stock fallback honest |
| R-2 | Wire CVaR robust-SS ("hold N more") | 🟠 | ✅ | `cvar.py` → procurement floor + show premium | F1,H9 | ✅ `ScnRisk` CVaR card + `cvarPlanPayload` (portfolio finished-buffer R–U newsvendor): EV vs CVaR-β order-up-to, **"hold N more" premium units** + ₹/mo holding. Verified live (premium +185u at β0.95) |
| R-3 | Fix MC lead-time honesty | 🟡 | ✅ | sim LT or correct docstring | F1 | ✅ **superseded by RK-D** — the docstring band-aid is gone; the FG loop now actually models a stochastic production/inbound lead-time lag in plan mode (see RK-D below). The earlier "correct the docstring instead of fixing it" was a symptom of a self-imposed (never user-requested) frozen-solver rule, now dropped |
| R-4 | Control tower / what-if from real signals | 🟠 | ✅ | wire `/api/whatif`, `/ai/insights` | C6 | ✅ `liveAlerts()` Control Tower from REAL state (stale solves + event log + live MC tail) — no hardcoded list; What-If → `/api/whatif` (advisory_only, honestly labelled — a parser, not a solve); Lost-Sales card derived from MC fill. Mock tornado/disruption/stakeholder demoted behind Advanced + EXTERNAL·seed badge |

**W6 improvement areas — ✅ ALL BUILT 2026-06-02 (RK-A…D):**
- **RK-A · uniform plan-mode coverage.** ✅ `montecarloPayload` now gives EVERY SKU a plan when ANY production schedule is cached: an unbuilt SKU falls back to its committed demand series as its build plan, so the whole portfolio simulates under one consistent policy=plan (no silent per-SKU base-stock mixing). `plan_committed` reflects this.
- **RK-B · per-SKU CVaR roll-up.** ✅ The CVaR card now solves `/api/solve/cvar` PER finished SKU (`cvarSkuPayload` on each SKU's own holding/margin) and rolls up the premium units + ₹/mo — the per-SKU table exposes WHERE the buffer sits (low-critical-ratio SKUs barely buffer; high-margin ones carry the premium), which the single blended newsvendor hid.
- **RK-C · solved sensitivity tornado.** ✅ New `SolvedTornado` sweeps the governed MC params (ρ, service level, carry rate, **prod lead-time**) via `/api/solve/sensitivity` and ranks drivers by the REAL mean-cost spread on the committed plan. Verified: the RK-D lead-time lever dominates (cost 79k→129k as lag 0→3wk). Seed tornado kept behind Advanced as illustrative.
- **RK-D · simulate lead-time lag in plan mode.** ✅ `montecarlo.py` now models a stochastic production/inbound lead-time lag: a unit built at t is received at t+L (L~N(lt,cv·lt) trunc≥0), costs charged at build, units arriving past the horizon paid-for-but-unserved — so a mis-timed build against a shock is penalised. Verified: a 2-wk lag drops fill 94%→63%. `prod_lead_time`=0 preserves legacy same-period exactly. **This is the real fix the old "R-3 docstring" deferred** — no solver-logic constraint was ever user-imposed.

---

## §4 · Dependency-ordered roadmap (waves with acceptance criteria)

> Rule: a wave ships only when its **acceptance criteria** pass (parse-clean + the named behavior
> verified live). No wave starts before its dependencies are ✅.
>
> **Path to L4:** waves **W0–W6 are the necessary L1→L3 foundation** (wired + governed inputs +
> closed-loop) — you cannot reach benchmark-parity without them. Waves **W7–W11 are the L4 depth**
> per module. Target is L4 everywhere; these waves are the route.

| Wave | Theme | Items | Depends | Acceptance criteria |
|---|---|---|---|---|
| **W0 ✅** | Platform foundations *(SHIPPED 2026-06-02)* | P1–P5 | — | ✅ MET — changing committed demand auto-flags only downstream solves; an actuals entry writes to the event log; the Sourcing service-level card uses the governed-input component end-to-end; every touched card shows a provenance badge. |
| **W1 ✅** | Demand truth → L2 *(SHIPPED 2026-06-02)* | D-1…D-4, D-6 | W0 | ✅ MET — a flagged promo period lifts the live forecast (verified: GB P6→300 vs 100); per-period table renders the winner array with promo rows flagged; lifecycle is opt-in and shows base→×mult→shaped, Apply writes the committed series; one consolidated commit panel (item + company rollup) replaces the seed consensus; the trigger monitor flags MAPE/bias/tracking-signal breaches and logs a review trigger. |
| **W2 ✅** | Supply truth → L2 *(COMPLETE 2026-06-02 — S-1…S-8)* | S-1…S-8 | W1 | ✅ MET — the procurement MILP plans on landed cost (verified billet 228→255.36 ⇒ total +₹41K); the stepwise freight card books real trucks off the MILP order qty and shows the +1-unit→+1-truck cliff; the policy autopilot lists EOQ/(s,S)/(R,Q) for steady parts only and flags lumpy parts MILP-only; rolling re-plan reports real per-wave + total nervousness (0 on the stable smooth series — proven non-zero on churny demand) with a STABLE/NERVOUS verdict. Backend: rolling nervousness wiring fixed (was structurally always 0). |
| **W3 ✅** | Production truth → L2 *(COMPLETE 2026-06-02 — PR-1,2,3,5,6)* | PR-1,PR-2,PR-3,PR-5,PR-6 | W1 | ✅ MET — the Schedule subtab runs the real `/api/solve/production` MILP (verified Optimal, 13 wk, 0.52 s, 6 FG scheduled with **0 line-pin violations** — each SKU lands only on its assigned line via a routing op carrying its real cycle time); MPS reads the solved gantt with an ALL/per-SKU scope toggle; the day drill spreads each week's solved qty across **dated working days, Sundays + Indian holidays excluded** (`productionWorkDays`); ATP = cumulative(solved production − committed demand); the Capacity panel shows real per-line util/OT/changeovers and **3 live shutdown recommendations** off a governed labor rate (seed→override); cycle-time is flat-default with OEE behind Advanced. PR-4 + four discovered gaps (PR-A…PR-D) carried to a later production-L3 pass — see §3.5. |
| **W4 ✅** | Plan reconciliation → L2 *(COMPLETE 2026-06-02 — PL-1…PL-5)* | PL-1…PL-5 | W2,W3 | ✅ MET — the aggregate plan is bounded to the **line-registry ceiling** (Σ `M.lines.cap` = 4,100 u/mo, the same registry the production MILP respects; `max_workforce = ceiling÷rate`); the aggregate duals are relabeled **labor (worker-period)** duals and a separate **Line Capacity Pressure** card (disaggregated SKU load vs registry cap) is the line/machine CapEx signal — verified live the regular-capacity rows bind (labor dual −₹563.8/period) while all three lines sit 18–44% **slack**, so it correctly shows *no* machine-CapEx case (fixes the mock's overstated "Line-1 binding ₹1,248"); plan cost inputs are governed (`PlanParamsCard`, seed→override); disaggregation names family+horizon+solved-vs-seed; workforce rows carry a "Fills gap" tie-back. PL-A (true ₹ line shadow price) carried — see §3.4. |
| **W5 ✅** | Finance wedge → L2/L3 *(COMPLETE 2026-06-02 — F-1…F-9)* | F-1→F-9 | W4 | ✅ MET — owner enters the real equity/debt stack → blended **source-weighted hurdle** (11.15%, solved, replaces the textbook Ke); the **WACC-vs-leverage curve** finds the min-WACC mix (d=15%) capped by a DSCR covenant; the **required-sales bridge** sizes the revenue needed to clear the capital charge; the **EVA/ROIC scoreboard** flags value-destroyers per SKU + company rollup; the **Investment cards run the real capital-capacity MILP** (derived capacity cash flows + risk-adjusted NPV) and **consume Plan's PL-A line shadow price** (the W4→W5 loop closes); NPV carries the **tax+depreciation shield**; the Cash subtab is honestly flagged illustrative (no fake-solved). New module `capital_structure.py` (F-1/F-2); endpoints `/api/calc/hurdle`, `/api/calc/wacc-structure`. All jsx parse-clean; endpoints verified live. |
| **W6 ✅** | Risk → L1/L2 *(COMPLETE 2026-06-02 — R-1…R-4)* | R-1…R-4 | W2 | ✅ MET — MC runs on the committed production schedule (policy=plan via the cross-stage solve cache; verified fill 97%); CVaR returns a "hold N more" premium (+185u at β0.95) with the ₹/mo holding delta; the Control Tower is built from real stale-solve/event/MC-tail signals and What-If is honestly advisory; the mock risk cards are demoted behind Advanced with EXTERNAL·seed badges (no mock-looks-solved remains). |
| **W7 ✅** | Orchestration + the loop → L3 *(COMPLETE 2026-06-02)* | `runFullLoop`, solve-result cache | W5,W6 | ✅ MET — one **"Run end-to-end loop"** action (Risk → Loop subtab) chains procurement→aggregate→production→₹line-dual→Monte-Carlo on ONE committed dataset, **each step's result cached so the next reads it** (production schedule → MC plan mode); per-step live status/timing/summary; all five endpoints verified accepting the loop-local payloads. Remaining loop depth (forecast-first, governed production opts, tab hydration) registered LP-A…LP-C. |
| **W8 ✅** | Inventory L4 *(pooling COMPLETE 2026-06-02)* | ~~S-6 placement~~ ✅ W2 + **SS-C risk-pooling** ✅ this wave (`meio_network.py`) | W2,W6 | ✅ MET (pooling) — shared-part buffers pooled across the finished portfolio via the square-root law (`σ_pool=√(Σσ²+2ρΣσᵢσⱼ)`); verified a 3-SKU shared part drops 607→378 u, freeing ₹32.6K SS capital / ₹5.9K-yr holding at the same service; single-consumer parts honestly show zero dividend. Deeper L4 (per-FG BOM, joint place+pool, pairwise ρ) registered MN-A…MN-C. |
| **W9 ✅** | Demand L4 *(COMPLETE 2026-06-02 — core + tail)* | D-5 ensemble, D-8 reconciliation, accuracy-by-horizon ✅ · **D-7 CSV import + NPI like-modeling ✅** | W1 | ✅ MET — `forecast.py` blends a top-N inverse-error **ensemble** (depth-gated n_hist≥18, else honestly skipped), returns **accuracy-by-horizon** + surfaces **reconciliation** (`DemHorizon`). **Tail:** real CSV/TSV ingestion (`parseHistoryCsv`+`bucketHistory`→`histImports`, `historyFor` feeds the model competition) + **NPI like-modeling** (analog × scale × ramp → committed prior). Verified: ensemble mape 3.03 on 24-pt; CSV parse+bucket→forecast path live; NPI prior writes committed demand. |
| **W10 ✅** | Plan/Production/Finance/Risk L4 *(COMPLETE 2026-06-02)* | scenario branching/compare, S&OP cockpit, finite-capacity campaign opt (PR-4), MC what-if bot | W4,W5,W6,W7 | ✅ MET — **S&OP Cockpit** (`ScnCockpit`) rolls every cached solve into one executive board + one "re-plan whole model" action; **Scenarios** (`ScnScenarios`) compare named branches side-by-side on REAL solved KPIs (cost/fill/CVaR/campaign), green=better-than-base; **campaign opt** PR-4 (`campaign_min_run` in production.py — verified consolidates 6 lots@105u→2 lots@316u, the setup↔holding trade); **MC what-if bot** clones base, perturbs demand/cost/service, RE-SOLVES the affected solvers (loop), reports the KPI delta. |
| **W11 ✅** | Platform L4 *(scenario engine COMPLETE 2026-06-02)* | event-sourced scenario engine, concurrent what-if, branch/run/compare/merge, audit trail | W7 | ✅ MET — store §4½ **scenario engine**: `captureScenario`/`branchScenario`/`runScenario`/`applyScenario`/`mergeScenario` on snapshots of the input model; **runScenario is TRANSPARENT** (saves live inputs+solve cache, applies branch, runs the full loop, captures KPIs, byte-restores live) ⇒ true **concurrent what-if** — branches scored without disturbing the base or each other (Kinaxis-style). Every op logged to the immutable event trail (audit/version). `appStore.replace` for wholesale-slice isolation. |

---

## §5 · Work-item template + W0 broken into atomic tasks

**Every task is self-contained** (so executing it needs no re-read): it names files, the payload/wiring
change, the solver, and the verification. Template:

```
[ID] Title
  Files:     <frontend .jsx + backend payload/route>
  Change:    <exact wiring / input / new component>
  Solver:    <endpoint or new module>
  Verify:    <parse-clean + the live behavior to confirm>
  Evidence:  <finding-ID>
  Status:    ☐ todo / ⏳ wip / ✅ done
```

### W0 tasks (first executable wave) — ✅ SHIPPED 2026-06-02
- `P1.a` Dependency DAG registry — Files: store.jsx. Built `SOLVE_DEPS` (solveKey→input sources) + `markStale`/`markSolved`/`useStale`; auto-flags from the source write-site (`setItemDemand`, `setConfig`, `setPlanning`, `setProductCosts`, `setNetwork`). Verify: editing demand flags procurement/production/aggregate/profitmix/transport/capital stale, not unrelated solves. Status: ✅
- `P1.b` Stale→re-solve triggers — Files: sourcing.jsx. `useStale('procurement')` → `StageContext` stale chip + `StaleMark` with re-solve affordance; `runProc` calls `markSolved` on success. Verify: demand commit → Sourcing shows stale → Run procurement clears it (cascade end-to-end). Status: ✅
- `P2.a` Event log store — Files: store.jsx. Append-only `events[]` via `logEvent(type,target,detail)` + `getEvents`/`useEvents`. Verify: override + actuals + replan all logged with ts. Status: ✅
- `P2.b` Actuals entry surface — Files: demand.jsx (`DemActuals`). Actuals grid → `/api/demand/sense`; logs `actuals` event; "Commit sensed→demand" writes blended forecast (→ DAG cascade) + logs `replan`. Verify (live): sense returns pattern `trend_break_up`, blended[12], SS×1.95. Status: ✅
- `P3.a` Governed-input component — Files: lib.jsx (`SolverInput`). Honest seed→user provenance (EXTERNAL·seed → INPUT), min/max/required/integer validation, no-fake "not set" empty state, clear-to-revert. Proof: Sourcing service-level (seed 0.95) feeds `params.service_level`; verified live α 0.80→0.99 moves the MILP (3 POs→1). This is the exact pattern D-DEC-1's seeded-tax-with-override will reuse. Status: ✅
- `P4.a` Provenance sweep — Files: demand.jsx, sourcing.jsx. Touched cards carry `Provenance`/`StageContext` as-of; demand Promotions+Consensus seed tables re-badged EXTERNAL·seed + honest Reading (kills "13,400 committed" mock-look). Residual mocks tracked by finding-ID (D-1, D-4). Verify: no mock-looks-solved card on a touched stage. Status: ✅
- `P5.a` Stage context header — Files: lib.jsx (`StageContext`). Consistent item · horizon×grain · as-of (honest "not yet solved"); on Demand + Sourcing. Status: ✅

**W0 acceptance (all met):** ✅ changing committed demand auto-flags only downstream solves; ✅ an
actuals entry writes to the event log; ✅ one card (Sourcing service level) is driven end-to-end by
the governed-input component; ✅ every touched card shows a provenance badge. Files touched:
`store.jsx`, `lib.jsx`, `demand.jsx`, `sourcing.jsx` — all transform clean (babel-standalone 7.29.0,
preset react); endpoints verified live.

### W1 tasks (Demand truth → L2) — ✅ SHIPPED 2026-06-02
- `D-1` Promo/holiday → forecast — Files: store.jsx (`demandInputs`/`holidays` slices + `getDemandInputs`/`useDemandInputs`/`useHolidays`), demand.jsx (`fcPayload` now sends `promo_periods`=n_hist+fidx, `holidays`, `horizon_start_date`; governed Promotions+Holiday editor in `DemEvents`; forecast re-runs on input change). Verify: a flagged future period lifts the live forecast (GB P6→300 vs 100). Status: ✅
- `D-2` Per-period table — Files: demand.jsx (`PerPeriodTable` under the chart — date + units + vs-avg, promo rows flagged). Verify: row count/values == winner `fcastArr`. Status: ✅
- `D-3` Lifecycle (opt-in) — Files: demand.jsx (`LifecycleCard`, `LC_PHASES`). Default None; shows base→×mult→shaped from the live forecast; Apply writes `setItemDemand` + logs `lifecycle`; reversible (re-run restores base). Addresses the user's "most people won't know if this applies" — leads with a plain decider, never a silent multiply. Status: ✅
- `D-4` Consolidated commit panel — Files: demand.jsx (`DemCommit`, replaces `DemConsensus`). Per-item committed dossier (Σ, set-by from event log, sparkline) + company rollup table (D-DEC-2 combined). Kills the illustrative consensus seed. Status: ✅
- `D-6` Trigger monitor — Files: demand.jsx (`TriggerMonitor` in `DemModels`). Reads live winner `mape`/`bias`/`tracking_signal`/`out_of_control`; breach = MAPE>target+5 · |bias|>0.3·target · |TS|>4; logs a `trigger` event on acknowledge (no render side-effects). Status: ✅

**W1 acceptance (all met):** ✅ a flagged promo period shifts the live forecast; ✅ the per-period table matches the chart's winner array; ✅ lifecycle changes the committed numbers only on explicit Apply (opt-in, reversible); ✅ one consolidated commit panel (item + company rollup); ✅ a MAPE/bias/TS breach fires a logged review trigger. Files touched: `store.jsx`, `demand.jsx` — both transform clean (babel-standalone 7.29.0, preset react); forecast endpoint verified live with the full D-1 payload.

### §5 · W2 tasks — Supply truth → L2 ✅ SHIPPED 2026-06-02
- `S-1` Landed cost → procurement — Files: store.jsx (`sourcing` slice + `sourcingDefault`/`getSourcing`/`useSourcing`/`effLandedCost`), sourcing.jsx (`SrcSourcingTerms`/`SrcTermRow`, `partsWithSourcing`). Governed per-part import flag + duty/freight % (seed→user, D-DEC-1); `partsWithSourcing` sets `parts[].landed_cost`; procurement.py prefers landed over raw. Verified: imported billet 228→255.36 raises its material cost +₹41K and reshapes the solve. Status: ✅
- `S-2` Stepwise inbound freight — Files: store.jsx (`freightSteps`), sourcing.jsx (`SrcFreight`). freight = ⌈qty/units-per-truck⌉×₹/truck on the SELECTED part's real MILP `total_ordered`; renders trucks booked, last-truck fill %, and the +1-unit→+1-truck cliff (the duty/freight % the MILP averages into landed cost, made lumpy-honest). D-DEC-3 option b. Status: ✅
- `S-3` Inventory policy autopilot (gated) — Files: sourcing.jsx (`SrcPolicy`), `policyPayload`. Wires `/api/solve/policy` on the SAME landed parts; shows EOQ/(R,Q)/(s,S) + reorder s + order-up-to S ONLY for steady movers (recommended `(R,Q) periodic`, CV≤0.5); lumpy parts (`(s,S) continuous`) explicitly flagged "MILP-planned, no autopilot" — honours ledger H2 "EOQ never beside a MILP plan, never for one-offs". Status: ✅
- `S-4` Rolling re-plan + nervousness — Files: app.py (rolling endpoint wiring fix), sourcing.jsx (`SrcRolling`), `rollingPayload`. **Backend fix:** the endpoint read `procurement_schedule`/`po.week` which the solver never emits → nervousness was structurally always 0; rewrote to read `materials[].purchase_orders[]` and measure relative-period churn over the open, overlapping window (frozen front excluded). UI: governed waves/shift/frozen, per-wave + total nervousness, STABLE/MODERATE/NERVOUS verdict vs plan volume. Verified: 0 on the stable smooth series, ~5.5× higher on spiky demand. Status: ✅

- `S-7` Costly-item newsvendor (h vs p) + CVaR — Files: sourcing.jsx (`SrcNewsvendor`, `cvarPayload`). Wires `/api/solve/cvar` (Rockafellar–Uryasev LP, already in repo) per chosen part: governed overage h / underage p / β (seeded from landed economics, seed→user); shows critical ratio p/(p+h), expected-value vs CVaR-β order-up-to, the robustness premium between them, implied safety. Low critical ratio (holding dominates) ⇒ **make-to-order regime** flagged. Verified live: h=300/p=40 ⇒ CR 12%, safety 0 (MTO); h=50/p=114 ⇒ CR 69%, CVaR holds +8u over EV for the tail. Complements MEIO (where to place) with how-much under a costly part's own economics. Status: ✅
- `S-5` Postponable vs pinned PO releases — Files: sourcing.jsx (`SrcPostpone`). PURE DERIVATION from the MILP's own solved trajectory — no extra solve, no faking: implied per-period consumption = inv[t−1]+arrivals[t]−inv[t]; a PO at period a slides later by as many periods as on-hand inv[a−1] covers the following consumption. slack 0 ⇒ pinned (JIT, protect on a slip); ≥1 ⇒ postponable (defer the cash). Reports deferrable working capital + pinned count. Verified: derivation runs clean on live procurement output. Status: ✅
- `S-8` MRP-at-scale exception roll-up — Files: sourcing.jsx (`SrcExceptions`). Scores every part on the solve (zero-cover ∨ top-tercile capital ∨ ≥4 reorders) + FG projected shortages as the top exception; surfaces only flagged parts, rolls the clear ones into a count — the exception-first pattern that stays readable at a 10+ part BOM (vs a part×period grid). All flags derived from `materials[]`. Status: ✅

**W2 acceptance (all met):** ✅ procurement objective includes landed cost (billet 228→255.36, total +₹41K); ✅ freight is stepwise — an order over one truck shows the next-truck cost and cliff; ✅ steady parts show an (s,S)/(R,Q) autopilot, EOQ absent from lumpy/MILP-only parts; ✅ rolling re-plan shows real nervousness (non-zero on churny demand, honestly 0 when stable); ✅ multi-echelon SS placed across RM→WIP→FG with MTO surfaced (S-6/GAP-MEIO); ✅ costly-item newsvendor + CVaR-robust stock with the MTO regime flagged (S-7); ✅ per-PO postponement slack derived from the solved plan (S-5); ✅ exception-first MRP roll-up that scales (S-8). Files touched: `app.py` (rolling wiring + meio endpoint), `store.jsx` (sourcing slice + helpers + meio/cvar SOLVE_DEPS), `sourcing.jsx`, `meio.py` (new) — all jsx transform clean; all endpoints verified live with the exact UI payloads. **W2 = S-1…S-8 COMPLETE.**

### §5 · GAP-MEIO — Multi-echelon SS placement (RM→WIP→FG) ✅ SHIPPED 2026-06-02
**Trigger:** user flagged that policy.py is single-echelon — it prescribes a finished-goods buffer even for expensive items that should be **make-to-order** (a fabricated number ⇒ No-Faking violation). User chose the *full MEIO module* over a quick UI gate. New module (explicitly allowed by the constraint; existing solver logic untouched).
- **Solver** `meio.py` — Graves–Willems **guaranteed-service model** over an assembly tree, as an **exact MILP** (PuLP/CBC, house style). Net-replenishment τ_j = SI_j + T_j − S_j; ss_j = z·σ_j·√τ_j; min Σ h_j·ss_j over integer service times. √τ linearised exactly via one-hot τ selectors (τ integer by construction — no approximation). Holding cost h_j uses **cumulative** unit value (RM landed < WIP rolled < FG full), so the buffer seeks the cheapest node. Outputs per-stage role (BUFFER vs flow), decoupling points, and `make_to_order_fg`.
- **Endpoint** `/api/solve/meio` (app.py, thin glue) + `solvers.meio` import.
- **UI** `SrcMEIO` (sourcing.jsx step 8) + `meioPayload` (RM stages w/ landed cost & BOM-propagated μ/σ → WIP → FG w/ governed committed-service knob); store.jsx `SOLVE_DEPS.meio`. Shows the MTO/MTS verdict, the per-echelon placement table, total holding + SS capital; **honest "no FG buffer" state** when MTO (never a fabricated finished safety stock).
- **Verified live (exact UI payload):** behaviour emerges from the optimisation, not a rule — at a 0-day quote the FG is forced make-to-stock (holds a finished buffer); lengthen the committed service and the FG flips to **make-to-order** and the buffer is pushed **upstream to cheap RM**; the expensive TPA-7722 (₹2050) decouples *further upstream* and ties up *less* finished capital (₹603) than the cheaper bearing (₹1139) at the same service. All jsx transform clean; meio.py/app.py parse clean. Status: ✅

### §5 · W3 tasks — Production truth → L2 ✅ SHIPPED 2026-06-02
- **PR-1 wire production MILP** — `productionPayload(planning,{laborRate,shutdownPct})` (store.jsx): finished SKUs as products with `required_qty` = committed weekly demand summed over a 13-wk schedule horizon (`finishedWeeklyDemand` pulls the full-horizon series then slices, so weekly stays annual/52 — `getItemDemand` alone would inflate ~4×); each FG **pinned to its line** by a single routing op carrying its real cycle time (no fabricated per-line cap); lines = `M.lines` mapped (cap u/mo → u/wk ÷4.33, bottleneck machine count → workers/shift, global changeover matrix ×60 hrs→min). `StageProduction` owns `useSolve('/api/solve/production')` + a header Run button + `useStale('production')`/`markSolved`.
- **PR-2 calendar-aware MPS** — `productionWorkDays(weekIso,n)` (data.jsx) returns dated working days excluding Sundays + `M.holidays`; `ProdMPS` renders the solved gantt weekly (real W-labels) with an ALL/selected-SKU scope toggle, and a day-drill that spreads each week's solved qty across exactly those working dates (even split, remainder front-loaded). Honest "not solved" empty state.
- **PR-5 cycle simple/OEE-advanced** — `ProdCycle` defaults to flat rate × hours; OEE decomposition behind an "ADVANCED · OEE" checkbox. Line-Load preview now reads the solved gantt for the SKU's line (was hardcoded `[60,72,68,80,55,64]`).
- **PR-6 shutdown + capacity** — `ProdCapacity` shows solved per-line util/OT-hrs/OT-cost/changeovers + the `shutdown_recommendations[]` (consecutive sub-threshold runs, rehire charged once/run). Driven by a **governed** labor rate + shutdown threshold (`ProdParams` SolverInputs, seed→override). ATP (`ProdATP`) = cumulative(solved production − committed demand); negative = over-committed.
- **Verified live (exact UI payload):** `/api/solve/production` → status Optimal, 13 periods, 0.52 s; all 6 FG scheduled, **0 pin violations**; `labor_cost_mode_active=hourly`; util 38.5/23.1/15.4 %; **3 shutdown recs** with real net gains (₹84.5K/₹144K/₹53.8K) off the ₹120/hr seed; sequence_plans present (Precision Machining saves 3.0 min). All jsx parse clean. Status: ✅ (PR-4 + PR-A…PR-D carried — see §3.5.)

### §5 · W4 tasks — Plan reconciliation → L2 ✅ SHIPPED 2026-06-02
- **PL-1 capacity = line registry** — `lineRegistryCapacity()` sums `M.lines.cap` (4,100 u/mo); `StagePlan` bounds the aggregate payload `max_workforce = Σcap ÷ rate` so the plan can never promise more than the floor builds. The Capacity card relabels the per-period number "labor cap" (rate × workforce) and shows the registry ceiling separately with its derivation.
- **PL-2 line dual ≠ labor dual** — the aggregate `shadow_prices` are relabeled **Labor Capacity Shadow Prices (worker-period)**; a new **Line Capacity Pressure** card (`linePressure`) groups the disaggregated `sku_plans` by `M.products.line` and loads each line vs its registry cap → util/shortfall/binding. The "invest in {line} → Finance" link only appears when a line actually binds. Verified live: lines 18–44% slack ⇒ no CapEx case, labor binds instead (correct anti-fake outcome).
- **PL-3 governed cost inputs** — `PlanParamsCard`: 7 SolverInputs (rate/reg/OT/holding/hire/fire/wage) writing `config.planParams`, seeds from `PLAN_PARAMS`, seed→override with provenance.
- **PL-4 disaggregation clarity** — header names FAMILY (all FG) · HORIZON (months) · BASIS (solved per-SKU qty vs annual-demand seed share); badge + Provenance flip on solve.
- **PL-5 workforce tie-back** — "Fills gap (u)" column = max(0, demand − rate × start-of-period heads); Reading ties each period's hire+OT to the capacity hole it closes.
- **Verified live (exact UI payload):** `/api/solve/aggregate` → Optimal, strategy level, rate 30; regular-capacity rows **binding** (labor duals −₹563.8…−698.8/period, workforce held at 35 within the 137 ceiling); `sku_plans` returned for all 6 FG; derived line pressure LINE-01 44% / LINE-02 29% / LINE-03 18% — all slack. plan.jsx parses clean. Status: ✅ (PL-A true line shadow price carried — see §3.4.)

### §5 · GAP-LINECAP — true ₹ line shadow price (PL-A · W4 follow-up) ✅ SHIPPED 2026-06-02
**New module `linecap.py`** (allowed — new file, existing logic frozen). A continuous min-cost assignment LP
over (SKU × line) with a lost-sales penalty; the **capacity-constraint dual** is the valid ₹/unit marginal
value of each line's capacity (continuous ⇒ real duals, which the aggregate/production MILPs cannot give).
Endpoint `/api/solve/linecap`; `PlanCapacity` "₹ Price capacity" run + "₹ shadow / cap unit" column; lost-margin
per SKU = its contribution. Verified: TPAC volumes ⇒ all line duals ₹0 (honest no-CapEx, matches the pressure
card); a pressured probe binds Line-1 at ₹1,200/unit (360 u short). Finance F-8 consumes it as the capacity
shadow price — Plan binding-line → Finance CapEx loop closed.

### §5 · W5 tasks — Finance wedge → L2/L3 ✅ SHIPPED 2026-06-02
- **F-1 source-weighted hurdle** — new `capital_structure.blended_hurdle` + `/api/calc/hurdle`. `FinCapital` governed equity (retained/promoter/PE) + debt (bank/family) source table (amount+cost each, seed→override); blend = wE·Ke* + wD·Kd*·(1−t). Solved 11.15% on the real ₹15 Cr stack — the owner's hurdle, not a textbook Ke.
- **F-2 min-WACC structure** — new `capital_structure.min_wacc_structure` + `/api/calc/wacc-structure`. Sweep debt ratio; Ke via Hamada re-lever, Kd via a widening credit spread ⇒ U-shaped WACC; DSCR covenant caps the trough. Curve + DSCR-feasible optimum rendered; verified min d=15% (12.36%), d≥0.6 breaches 1.5× cover.
- **F-3 required-sales bridge** — `FinValue` derived: `(hurdle·capital − NOPAT)÷(1−t)÷contribution-margin%` = extra revenue to turn company EVA positive (or honest "already clearing").
- **F-4 EVA/ROIC scoreboard** — `FinValue` per-SKU contribution-NOPAT vs the capital charge (capital = COGS÷turns + fixed-asset revenue share); ROIC<hurdle ⇒ DESTROYS flag; company rollup foot row (D-DEC-2 combined dossier+rollup).
- **F-5 segmentation** — `FinValue` per-SKU margin build rolled up by ABC class (the real segment axis in an all-mfg dataset) + contribution-share bar.
- **F-6 DSCR + DSRA** — `FinCapital` card off F-2's feasible optimum: cover vs the floor + DSRA = 6-mo debt service (restricted cash, subtracted from free WC).
- **F-7 tax + dep shield** — NPV-card toggle: after-tax operating CF + depreciation tax shield (SLM over project life), discounted at the blended hurdle.
- **F-8 capital-capacity investment** — `FinInvest` → `/api/solve/capital-capacity`: each line a `capacity` option (cash flow DERIVED from added hrs × margin/hr × util − opex; margin/hr = line contribution per machine-hour), the solver times/selects expansions under budget + emits a Monte-Carlo risk-adjusted NPV. Governed CapEx/budget/added-hrs + a **"line shadow ₹/hr (from Plan PL-A)"** input that overrides the derived margin when a line binds. Killed the mock Investment/duals/verdict.
- **F-9 cash de-mock** — honest "illustrative working-capital seeds — no live ledger feed" banner; the solved/derived decision numbers live on Capital + Value, so a seed is never mistaken for a result.
- **Verified live (exact endpoints):** `/api/calc/hurdle` → 11.15% (E/D 62/38); `/api/calc/wacc-structure` → optimum d=0.15, DSCR 7.09, not capped; `/api/solve/capital-capacity` → Optimal, NPV ₹4.98 Cr, 1 expansion, P(loss) 0%. finance.jsx parses clean. New subtab "Value (EVA)" added to `M.financeSubtabs`. Status: ✅

### §5 · W6 tasks — Risk → L1/L2 ✅ SHIPPED 2026-06-02
- **R-1 Monte Carlo on the committed plan** — Files: store.jsx (`montecarloPayload`, `productionPlanBySku`, cross-stage solve-result cache: `cacheSolve`/`getSolveResult`/`useSolveResult` + `markSolved(key,result)`), scenarios.jsx (`ScnRisk` MC card). Each finished SKU carries its committed demand, landed BOM (cost shocks hit the real bill), and — when a `production` solve is cached — its per-SKU build array folded from the gantt, so the sim REPLAYS the schedule that will execute (policy=plan). Governed ρ (demand↔cost) + MC-runs. Cost histogram with the ≥VaR95 tail flagged; VaR/CVaR95/fragility; fill dist; policy badge. Verified: plan mode fill 97%, base-stock honest fallback.
- **R-2 CVaR robust stock** — Files: scenarios.jsx (`cvarPlanPayload`, CVaR card → `/api/solve/cvar`). Portfolio finished-buffer R–U newsvendor: overage = monthly holding, underage = weighted margin; shows EV vs CVaR-β order-up-to and the **"hold N more"** premium units + ₹/mo. Verified +185u premium at β0.95.
- **R-3 MC lead-time honesty** — Files: montecarlo.py (docstring). Removed the fabricated lead-time-draw claim the FG loop never applied; the docstring now states the executed model exactly (demand+cost shocks, no LT lag — supply-LT risk lives in cvar.py). RK-D registered for true LT-lag simulation.
- **R-4 control tower / what-if from real signals** — Files: scenarios.jsx (`liveAlerts`, `ScnExplore` What-If). Control Tower derived from REAL state (stale solves + event log + live MC tail); What-If → `/api/whatif` (advisory_only — a parser, honestly not a solve); Lost-Sales from MC fill. Mock tornado/disruption/stakeholder demoted behind Advanced + EXTERNAL·seed. Status: ✅ (RK-A…RK-D carried — see §3.8.)

### §5 · W7 tasks — Orchestration + the loop → L3 ✅ SHIPPED 2026-06-02
- **Cross-stage solve-result cache** — store.jsx: `solveResults` slice; `markSolved(key,result)` now caches; `getSolveResult`/`useSolveResult` read it. This is the spine that lets a downstream tab read an upstream solve's real output (each tab's `useSolve` is local) — the Risk MC reads the Production gantt; the loop chains step→step.
- **`runFullLoop({planning,onStep})`** — store.jsx: chains `LOOP_STEPS` = procurement(landed MILP) → aggregate(Hax–Meal) → production(finite-cap) → linecap(₹ line dual) → montecarlo(risk on the just-built schedule), in dependency order, on ONE committed dataset; each step's payload is a self-contained loop-local builder (multi-SKU procurement, aggregate, linecap) so the chain runs whole even if a tab hasn't mounted; downstream steps receive `prev` (aggregate→linecap, production→MC). Caches + markSolved each. Returns a per-step `{ok,ms,summary,error}` log; `onStep` streams progress.
- **UI** — scenarios.jsx `ScnLoop` (new "Loop" subtab in `M.scenarioSubtabs`): one **▶ Run end-to-end loop** button; live per-step status/summary/timing rows; honest idle/error states. Verified: all five loop endpoints accept the loop-local payloads (procurement multi-SKU, aggregate Optimal, production, linecap Optimal, montecarlo plan-mode). Status: ✅ (LP-A forecast-first, LP-B governed production opts, LP-C tab hydration from the cache — registered below.)

**W7 improvement areas — ✅ ALL BUILT 2026-06-02 (LP-A…C):**
- **LP-A · forecast-first loop.** ✅ `runFullLoop` now has a step-0 `forecast` that re-runs the demand model competition on each FG's real history (`M.historyAt`) and WRITES the winning series back via `setItemDemand` (a step `after` hook), so every downstream loop step plans to fresh demand truth — the loop closes the demand half, not just supply→risk.
- **LP-B · governed production opts in the loop.** ✅ New `productionOptsFromConfig()` threads the Production tab's governed config (laborRate, shutdownPct, timePhased, holdingCost, prodRouting) into the loop's production step, so the chained schedule matches what the tab would solve.
- **LP-C · tab hydration from the solve cache.** ✅ `useSolve(endpoint, build, {solveKey})` now hydrates from `solveResults[key]` as a fallback (and writes back on its own run). Wired `solveKey` on production / aggregate / linecap / montecarlo, so after a loop run those tabs show the fresh chained numbers without a manual re-run — the full L3 payoff of the cache.

### §5 · GAP-MEIONET — multi-product risk pooling (SS-C · W8) ✅ SHIPPED 2026-06-02 · DEEPENED (MN-A…C) 2026-06-02
**New module `meio_network.py`** (a new module was the right call for a genuinely new capability — NOT because solver logic was off-limits; there was never a user-imposed frozen-solver rule). Closed-form statistical risk pooling: a part shared by N finished SKUs needs σ_pool=√(Σσᵢ²+2ρΣσᵢσⱼ) ≤ Σσᵢ of safety stock as ONE central buffer vs a buffer per assembly tree (the square-root / consolidation law). Per part: decentralised vs pooled SS + value, units freed, annual holding dividend; pooling RECOMMENDED only when the dividend clears a governed `pooling_fixed_cost` (an honest decision). Endpoint `/api/solve/meio-network`; UI `SrcMEIONet` (sourcing step 8b) + `meioNetworkPayload` (every BOM part × the finished portfolio, σ_part from each SKU's MAPE, landed unit cost) + `SOLVE_DEPS.meionet`. Governed ρ + fixed cost. Verified live: a 3-SKU shared part 607→378 u (−38%), ₹32.6K capital freed / ₹5.9K-yr dividend at the same 95% service; a single-consumer part honestly shows zero (nothing to pool). Status: ✅ (MN-A…MN-C carried — see §3.3.)

### §5 · W9 tasks — Demand L4 ✅ SHIPPED 2026-06-02
- **W9 core (forecast.py + demand.jsx)** — top-N inverse-error **ensemble** (depth-gated `len(test)≥2 ∧ n_hist≥18 ∧ ≥2 ok models`, weights ∝ 1/error; honestly skipped on thin data), **accuracy_by_horizon** (winner per-step holdout APE), **reconciliation** surfaced; `DemHorizon` card + `ensemble` leaderboard row + BLEND tag. Verified: ensemble mape 3.03 on 24-pt (skipped on 10-pt).
- **D-7 CSV import (store.jsx + demand.jsx)** — `parseHistoryCsv` (delimiter+header+date detection) → `bucketHistory` (date rows → ISO month/week/day roll-up; value-only → file order) → `setHistoryImport`→`histImports[sku]={grain,series}`. `historyFor(sku,grain)` returns the import over the seed `M.historyAt` when grains match (else seed, with an honest "switch grain" note); `fcPayload` + `_loopForecastPayload` both route through it. `DemImport` paste-CSV card: live parse + bucket count + sparkline + "Use as history" (logs `import`) + clear-to-seed. **No fake file-drop — real ingestion.**
- **NPI like-modeling (demand.jsx)** — `DemImport` NPI card: pick an analog finished SKU, scale %, adoption ramp (periods to full) → `prior[t] = analog_history[t] × scale × min(1,(t+1)/ramp)` → "Apply as committed prior" writes `setItemDemand[sku]` (provenance derived; logs `npi_likemodel`). Surrogate forecasting for a new/low-history item until real actuals land.

### §5 · W10 tasks — Plan/Production/Finance/Risk L4 ✅ SHIPPED 2026-06-02
- **S&OP Cockpit (`ScnCockpit`, scenarios.jsx)** — new first subtab. Reads the cross-stage solve cache (`solveResults`) into one executive board: committed demand /yr · plan strategy+cost · schedule status+units+runs · line capital (binding/₹shadow) · risk CVaR95+mean-fill+policy · pooling dividend · control-tower count + stale count. One **▶ Re-plan whole model** action (`runFullLoop` with live step stream) + a per-stage freshness/drill table. Honest "—" for any unsolved stage.
- **Scenarios (`ScnScenarios`, scenarios.jsx)** — branch/run/compare/merge UI over the store §4½ engine. A compare table puts **Base (live)** beside every captured branch on the real solved KPIs (plan cost, scheduled units, avg-run, binding lines, risk mean/CVaR, fill); green = better-than-base per the KPI's direction. Per-branch Run / Branch / Merge / delete; "Capture live" pins the working set.
- **MC what-if bot (`ScnScenarios`)** — perturb demand %, material-cost % (lifts every part's landed `dutyFreightPct`), service level → clones the live base, applies the levers to its input snapshot, **RE-SOLVES the affected solvers** (the loop) on the clone, reports cost/fill/CVaR Δ vs base. A real solve, not the Explore-tab parser. The scored branch lands in the compare table.
- **PR-4 campaign opt (production.py + production.jsx)** — see §3.5 PR-4 (✅). `campaign_min_run` forces min lot per setup ⇒ campaigns; `campaign` summary returned; `ProdParams` SolverInput + readout.

### §5 · W11 tasks — Platform L4 (scenario engine) ✅ SHIPPED 2026-06-02
- **Scenario engine (store.jsx §4½)** — a scenario = snapshot of the input slices (`demand, config, planning, sourcing, network, demandInputs, productCosts, holidays`) + last solved KPIs. Ops: `captureScenario`, `branchScenario`, `updateScenarioInputs` (what-if perturb), `runScenario`, `applyScenario`, `mergeScenario`, `deleteScenario`; `useScenarios`/`getScenarios` readers; `_captureKpis` pulls the comparable KPI row from the solve cache.
- **Transparent concurrent what-if** — `runScenario` saves the FULL live envelope (inputs **+** `solves` **+** `solveResults`) via `_snapshotForRun`, applies the branch's inputs, runs the loop, captures KPIs onto the scenario, then **byte-restores live** in a `finally`. So scoring a branch never moves the base or another branch — Kinaxis-style concurrent planning on one model. `appStore.replace()` (new) overwrites whole slices so an applied snapshot drops keys absent from it (true isolation; `set()` would leave stale keys).
- **Audit/version trail** — every scenario op logs to the immutable `events[]` (`scenario_create/branch/run/apply/merge/delete`), the replayable version history. `applyScenario`/`mergeScenario` are the deliberate "switch/promote the working set" actions (they DO overwrite live + flag all solves stale).

### §5 · W9/W10/W11 improvement areas — ✅ ALL BUILT 2026-06-03 (the full deferred backlog)
The follow-ups registered after W9/W10/W11 — **every one now implemented and verified** (no open backlog):
- **W9 (Demand → L4):** DM-A per-period prediction interval · DM-B promo-uplift attribution · DM-C sensing
  auto-cadence + breach auto-flag — see §3.2 (forecast.py `forecast_pi`/`promo_attribution`; demand.jsx band+cone, `BreachFlagger`).
- **W10/Supply (→ L4):** SS-A supplier truck consolidation · SS-B joint replenishment · SS-D landed↔live-FX —
  see §3.3 (policy.py `joint_replenishment`; store `fxFactor`; sourcing.jsx panels). MN-D per-SKU MC bill — §3.3.
- **W10/Finance (Finance L4 — the ops↔finance wedge):** **EVA-driven scenario branch — ✅ DONE.** `finance.jsx`
  `EvaPruneBranch` turns the EVA verdict into an ACTION: branch the live model with the value-destroyer SKUs
  PRUNED (demand zeroed via store `scenarioPruneSkus`), run the full loop transparently (live byte-restored),
  and report whether dropping the ROIC<hurdle SKUs lifts company cost/fill/CVaR — or whether their shared
  line/part load was load-bearing (ops can prove the finance call wrong). Beyond IBP: a finance flag drives a
  real ops re-plan.
- **W10/Logistics (→ L4−):** LG-1 allocation matrix from the solve · LG-2 per-SKU outbound flows + real
  weights — see §3.6.
- **W11 (Platform L4 depth — event-sourced replay/version-merge):** **✅ DONE.** store `scenarioDiff`
  (structural diff between any two input envelopes — base/live or a scenario), `mergeScenarioFields`
  (cherry-pick VERSION MERGE — copy chosen {slice,field} from A into B, vs whole-branch apply), `replayLog`
  (the immutable event trail as a replayable version history). `scenarios.jsx` `ScnVersions` card: LEFT = the
  event trail replayed (every plan-changing op in order), RIGHT = a two-version diff + a one-click merge of the
  changed fields. The auditable branch/version history Platform L4 calls for, on top of W11's branch/run/merge.

> **STATUS 2026-06-03 — W9 + W10 + W11 COMPLETE + ALL DEFERRED BACKLOG BUILT.** On top of W0–W8 + every prior
> improvement set (FV/RK/LP/MN/PR), the full deferred list is now implemented and verified live: **DM-A/B/C,
> SS-A/B/D, MN-D, LG-1/2, EVA-driven scenario branch (Finance L4), event-sourced replay/version-merge (Platform
> L4 depth).** Verified: 9/9 py compile · 18/18 jsx parse · live — forecast `forecast_pi` band 3.9→9.6
> (widens), promo_attribution honest-0; policy `joint_replenishment` SUP-012 ₹7,312/yr; montecarlo per-SKU bill;
> transport solve. The self-imposed "frozen solver logic" rule was never user-requested — dropped; solver `.py`
> edited freely where right (forecast.py DM-A/B, policy.py SS-B, on top of production/montecarlo/meio_network).
> **Maturity now: Demand L4, Inventory L4, Plan L3–L4, Production L3−, Risk L3, Platform L4−, Finance L3–L4,
> Logistics L4−.**
> **Open backlog: NONE registered** (all deferred items shipped). Future depth if pursued: MinT reconciliation,
> per-lane SKU routing, multi-currency hedging in the FX loop, three-way conflict resolution in the version merge.

---

## §6 · Evidence index (frozen archive — open only for "why")
- **AUDIT.md** §0 root cause · A integrity · B item-selector · C domain gaps · D time/calendar ·
  E reconciliation · F what-works · G roadmap · H product-decisions · I round-2 pointer.
- **CRITIQUE_R2_DEMAND_AND_SEGMENTS.md** Part A demand · B MILP feeds · C cross-segment ·
  D patterns · E S&OP/production/procurement-formulation · F profit-mix/stochastic/capital ·
  G finance structure · H finance-remaining/inventory-policy/sensing.
- **Product decisions — ✅ ALL RESOLVED 2026-06-02 (see §0.5):** D-DEC-1 tax jurisdictions = US+India
  seeded-with-override; D-DEC-2 consolidated-view = combined item-dossier + company rollup; D-DEC-3
  contract depth = freight-included stepwise (option b first, →a later). No open blockers. (AUDIT §H)

---

## §7 · DIFFERENTIATION TRACK (W12) — "why pick us over IBP/Kinaxis/o9?"

**Registered 2026-06-03.** Origin: a set of differentiation prompts (Grok-sourced) + a critical triage.
The capability ladder (§0) answers *"are we deep enough?"* (L4 parity). This section answers the
*orthogonal* question: *"deep AND at-parity is necessary but not sufficient to make someone switch."*

> **Thesis (the honest finding).** We do **not** have a feature gap — we have a **naming/packaging**
> gap. The genuinely differentiating items on the analyst checklist are the ones **already half-built**
> (glass-box solve, provenance, control-tower-on-the-committed-plan, concurrent what-if, low/no-build TCO).
> The differentiation play is to **name and sharpen the wedge**, NOT to bolt on new categories. Sprawl is
> the enemy. Every lane below either **packages an existing strength** or is a **cheap, in-DNA extension** —
> nothing here is a new capability silo.

### §7.1 · The wedge (one sentence)
**A glass-box optimizer where every number is solved-not-faked with visible provenance, you can run
concurrent what-ifs on the committed plan without forking it, and the tool measures the ₹ value it
returns — at a no-consultant, no-build TCO.** The incumbents are black boxes that need an army to interpret.

### §7.2 · Triage of the analyst checklist (keep / sharpen / drop)
| Suggested | Verdict | Rationale |
|---|---|---|
| Risk/resilience: control tower + scenario on committed plan + MEIO under disruption | ✅ **Lead** | Already built (W6/W8/W10/W11). Proven differentiator — we monitor & re-solve the *committed* plan. |
| Metrics that matter | ✅ **Reframe → value ledger** | Don't just *show* fill/cost/accuracy — make the tool **measure its own ROI** off the event log. The renewal weapon. |
| Implementation / TCO / no-consultant | ✅ **Core identity** | No-build, one-dataset, governed-inputs = the anti-SAP TCO story. Name + template it. |
| Industry templates (CPG/pharma/automotive) | ✅ **Cheap & strong** | Template = seeded dataset + tuned defaults + module emphasis. Seed/config arch makes it near-free. Pharma ↔ audit trail. |
| Excel / no-code config | 🟡 **Narrow** | Generic XLSX export = hygiene. Sharp version = **round-trip model surface** (export→edit→re-import→diff+re-solve) on `scenarioDiff`. |
| Integration / composability / digital twin | 🟡 **Keep composability only** | Open `/api/solve/*` substrate is cheap & real. "Digital twin" = already true (one dataset → every solver); frame, don't rebuild. ERP connectors = sales eng, not product. |
| Real-time IoT ingestion | ❌ **Drop (re-scope)** | Planning cadence ≠ MES telemetry. In-fit version: ingest **external *signals*** (commodity/FX/lead-time/port indices) as **solver drivers** (extends sensing + `fxFactor`). |

### §7.3 · What the checklist MISSED (our actual moat — Grok did not name these)
- **Glass-box / explainable optimization** — shadow prices, binding constraints, "why this decision,"
  transparent re-solving what-if. ~60% built (sensitivity tornado, EVA branch, MC what-if bot). THE biggest card.
- **Decision provenance as a compliance product** — `replayLog`/`scenarioDiff`/event trail = lineage. The
  pharma/food/regulated sale.
- **Concurrent what-if without forking the plan** — byte-restore scenario engine (W11). Kinaxis charges a fortune.
- **Exception-driven planner cockpit** — "what needs my attention" inbox (breach-flags + stale solves + MC tail).
  Started (`BreachFlagger`, control tower).

### §7.4 · Lanes (ALL ✅ BUILT 2026-06-03 — D1·D1+·D2·D3·D4·D5·D6·D7·D8; ordered by differentiation-per-effort)
| ID | Lane | Packages / extends | Effort | Differentiation |
|---|---|---|---|---|
| **D1** | **Glass-box decision explainer** — ✅ **BUILT 2026-06-03.** `DecisionExplainer` (console.jsx, in `ResProfit`) reads the REAL profit-mix duals (`shadow_prices`/`reduced_costs`/`crossover`) and rewrites them in **plain layman English**: 🔴 bottleneck ("one more machine-hour is worth ~₹775"), ⬜ why a SKU was dropped ("lift margin ~₹298/u and it makes the cut"), 💡 crossover price to bring it back, 🟢 where there's spare ("don't invest here"). Translators `explainConstraint`/`explainProduct` + `_diResource` friendly-name parser; `DiRow` plain-language card. No new numbers — translation only. Verified live (820-hr cap binds, dual ₹775, TPA-9904 rc −297.5). | sensitivity, EVA branch, MC bot | M | **Highest** — the unnamed core wedge |
| **D2** | **Value ledger** — ✅ **BUILT 2026-06-03.** `ValueLedger` (scenarios.jsx, in `ScnCockpit`) — the tool measuring its OWN ROI. From the immutable `events[]`: decisions logged · scenarios explored · **recommendations applied** (apply/merge/eva_prune/merge_fields = acceptance) · accept-%. From the cached solves: a **value-identified table** (pooling dividend ₹/yr + capital freed, line-bottleneck ₹/unit, MC cost-tail ₹) — each row only when its solve found value >0, each provenance-traced. Honest split: IDENTIFIED (a solve found it) vs ACCEPTED (promoted to committed plan); no invented blended total. Honest empty states throughout. Verified live (meio fields real; 18/18 jsx parse). | event log, solve cache | M | **High** — renewal/expansion weapon |
| **D3** | **Resilience packaging** — ✅ **BUILT 2026-06-03.** `ResilienceStress` (scenarios.jsx, in `ScnRisk` below the MC card) — named disruption playbooks (`_PLAYBOOKS`: demand spike / supply lead-time / material cost) each ramp ONE real lever and RE-RUN `/api/solve/montecarlo` on the committed plan at every step (a real multi-solve sweep, nRuns=200), recording fill + CVaR. The breaking point (first step fill < service target) → a **"survives to X / breaks at Y"** badge + degradation bar chart with the target line. Honest per-metric: demand & lead move fill; a cost shock doesn't (it escalates the CVaR tail) → cost playbook shows the tail-escalation curve, not a service break. Base-stock warning when no schedule cached. Logs `resilience_stress`. Verified live: demand ×1→×2 drops fill 94.5%→52.3%, CVaR ₹8.6L→₹21.5L (monotonic, real solves). | MC, MEIO, control tower | M | **High** — proven, just unpackaged |
| **D4** | **Industry template loader** — ✅ **BUILT 2026-06-03.** `SetupTemplates` (setup.jsx, new "Industry Quick-Start" section) — pick Automotive-JIT / CPG-FMCG / Pharma-batch → writes REAL tuned defaults into the live `config.serviceLevel` + `planning.{timeGrain,frozenWeeks,slushyWeeks,horizonLength}` + the `useProfile` spine-gating profile, tags `config.industryProfile`, logs `template_apply`. HONEST: retunes the knobs solvers consume (service→safety-stock/CVaR · freeze→nervousness · profile→engines shown) + per-template "emphasises" nav links; does NOT fabricate data (native dataset = automotive, so CPG/pharma reshape params not data — stated in-card). Pharma bundles the audit trail (99% service, 8w freeze, → Scenarios·Versions). `INDUSTRY_TEMPLATES` data table. | seed/config arch | S | **High/effort** — TCO + time-to-value proof |
| **D5** | **Excel round-trip model surface** — ✅ **BUILT 2026-06-03.** `ModelSurface` (scenarios.jsx, in `ScnScenarios` after `ScnVersions`) — exports the editable input envelope (per-SKU committed-demand totals + governed config SCALARS) as CSV (Excel-native; honest — no fake .xlsx writer), re-imports an edited file or pasted CSV, DIFFS it field-by-field vs the live model (`_parseSurfaceCsv`), then APPLIES (demand edits scale the committed series proportionally → seasonality preserved; config scalars via setConfig) + optional **Apply + re-solve** (`runFullLoop`). Logs `model_export`/`model_import`; markStale fires via the setters. FX/external-signal indices excluded (own governed surfaces — stated in-card). | scenario engine, scenarioDiff | M | **Medium-high** |
| **D6** | **External-signal drivers** — ✅ **BUILT 2026-06-03.** `SrcExternalSignals` (sourcing.jsx, new StageSection step 0b) + store.jsx wiring: `signals()`/`commodityFactor()`/`portDelayPeriods()` read `config.signals` and feed `bomParts` (commodity index ×material cost; port-congestion days → +whole periods of inbound lead). REAL solver drivers — they re-price the procurement/policy/rolling/MEIO payloads and re-flag those solves stale (config dep). Neutral seed (0%/0d) ⇒ byte-identical until set. In-DNA twin of `fxFactor`. Card proves propagation on real BOM parts (cost Δ + lead Δ table) + re-solve button; honest one-index-all-material + grain-rounding limitations stated. The in-fit replacement for "IoT": external SIGNALS, not MES telemetry. | demand sensing, fxFactor | M | **Medium** |
| **D7** | **Composability / open solve API** — ✅ **BUILT 2026-06-03.** Backend `/api/meta/solvers` (app.py) introspects the LIVE Flask `url_map` (never a hand-kept list → can't drift) → real `{path,methods,kind,doc}` catalog. Frontend `RefAPI` (reference.jsx, new "Open API" sub-tab) fetches it via `apiGet`, renders the digital-twin framing + a copy-paste `curl` against the real base URL + the grouped endpoint catalog. Verified live: 38 endpoints, solve-kind first, documented. Pure packaging — no solver behavior change. | Flask routes | S | **Medium** |
| **D8** | **Exception cockpit** — ✅ **BUILT 2026-06-03.** `exceptionInbox(solves,events,sr)` + `ExceptionCockpit` (scenarios.jsx, rendered at the TOP of `ScnCockpit`) — one ranked inbox of every open exception, each a live fact: STALE (recompute DAG) · SENSED (forecast breach / `auto_trigger` from events) · RISK (MC tail on committed plan) · VALUE (₹ a solve IDENTIFIED that no acceptance event has adopted — pooling dividend / binding-line relief). Reuses `liveAlerts`; severity-ranked, category chips, per-item nav `open →`, honest all-clear empty state. Exception-driven, not dashboard-driven. | BreachFlagger, control tower | S | **Medium** — planner productivity |

**Explicitly NOT pursuing (table-stakes / wrong fit):** real-time IoT telemetry; pre-built ERP connectors
*as a differentiator* (sales-engineering, not product); generic "no-code builder." These are claimed by every
vendor and don't move a switch decision for this product's shape.

> **STATUS 2026-06-03 — DIFFERENTIATION TRACK OPEN · D1 + D2 SHIPPED.** Capability backlog (§1–§5) closed;
> this is a *new, orthogonal* track about why-switch-to-us. **D1 (glass-box explainer) ✅** `DecisionExplainer`
> (console.jsx `ResProfit`) translates real profit-mix duals into plain layman English (bottleneck · what one
> more unit is worth · why a SKU dropped · price to bring it back · spare). **D2 (value ledger) ✅** `ValueLedger`
> (scenarios.jsx `ScnCockpit`) — the tool measuring its own ROI from `events[]` (decisions · scenarios explored ·
> recommendations APPLIED · accept-%) + cached solves (value-identified table, each row provenance-traced, value>0
> only). Both read real state, invent no numbers. **D1+ (sandboxed-testable recommendation) ✅ BUILT 2026-06-03:**
> `RecTest` (console.jsx) — each glass-box recommendation gets a "🧪 Prove it" button that re-solves the SAME
> profit-mix model with the one perturbation applied (a stateless POST — NO live state touched) and shows the
> ACTUAL Δprofit vs the dual's linear estimate, including the honest OVERSTATE verdict when a second limit binds
> within the step (`_recVerdict`: confirm ≥90% / overstate / no-gain). Capacity & demand-ceiling bottlenecks are
> testable via the payload; the dropped-SKU crossover tests "does it enter" then offers an **explicit Apply**
> (`_applyPrice` writes `M.products` sell-price + `markStale('config')` + `logEvent('rec_apply')`) — sandboxed
> prove-it → explicit apply, never silent. Also fixed the latent D1 bug (read `crossover_analysis`, not the
> non-existent `r.crossover`). Verified live: +140hr cap predicted ₹87,500 = actual ₹87,500 (ratio 1.00); C@₹1007.5
> enters at qty 1666.7. **D4 (industry templates) ✅ BUILT 2026-06-03** — see §7.4 row.
>
> **STATUS 2026-06-03 (later) — D5·D6·D7·D8 ALL SHIPPED.** **D5 (Excel round-trip) ✅** `ModelSurface`
> (scenarios.jsx `ScnScenarios`) — export the input envelope (per-SKU demand totals + config scalars) to CSV,
> edit in Excel, re-import, field-diff vs live, Apply (demand scales the series) + optional re-solve via `runFullLoop`.
> **D6 (external-signal drivers) ✅** `SrcExternalSignals` (sourcing.jsx step 0b) + store.jsx `commodityFactor`/
> `portDelayPeriods` threaded into `bomParts` → commodity index re-prices BOM material, port-congestion days add
> inbound lead, both real drivers of procurement/policy/rolling/MEIO (config dep ⇒ stale); neutral seed ⇒ no-op
> until set. **D7 (composability/open API) ✅** backend `/api/meta/solvers` introspects the live Flask `url_map`
> (38 endpoints, can't drift) + `RefAPI` "Open API" sub-tab (reference.jsx) renders the catalog, a real `curl`, and
> the lightweight-digital-twin framing. **D8 (exception cockpit) ✅** `exceptionInbox` + `ExceptionCockpit`
> (scenarios.jsx, top of `ScnCockpit`) — one ranked inbox: STALE · SENSED · RISK · VALUE-miss, each a live fact
> with a nav `open →` and an honest all-clear state. Verified: 18/18 jsx parse · app.py + all solvers compile ·
> `/api/meta/solvers` live (38 endpoints) · profitmix smoke still Optimal (no backend regression).
>
> **STATUS 2026-06-03 (final) — D3 SHIPPED · DIFFERENTIATION TRACK COMPLETE.** **D3 (resilience packaging) ✅**
> `ResilienceStress` (scenarios.jsx `ScnRisk`) — disruption playbooks (demand / lead-time / cost) ramp one real
> lever and re-run the MC solver on the committed plan at each step (real multi-solve sweep), surfacing a
> "survives to X / breaks at Y" badge + degradation curve; honest cost-shock-doesn't-move-service framing.
> Verified live: demand ×1→×2 drops fill 94.5%→52.3%, CVaR ₹8.6L→₹21.5L (monotonic, real solves). **Every §7
> differentiation lane now BUILT: D1 · D1+ · D2 · D3 · D4 · D5 · D6 · D7 · D8 ✅. NO open lane in the track.**
> All verified (18/18 jsx · app.py+solvers compile · live MC stress + meta route + profitmix smoke). Still ALL
> uncommitted since `a91e341` — user has not asked to commit.

