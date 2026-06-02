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
| Demand | **L1−** | **L4** | far | A1,A3,A5,A6,A8,H3 |
| Supply/Procurement | **L1−** | **L4** | far | B1,F4,H2 |
| Inventory | **L2** (was L0–L1) | **L4** | closing — S-3 policy autopilot + **GAP-MEIO module shipped** (RM→WIP→FG placement, MTO/MTS); remaining: pooling, multi-product shared-part network | H5,H6,H7,EOQ |
| Plan/S&OP | **L1** | **L4** | medium | E1,E2,E3,E4 |
| Production | **L0–L1** | **L4** | far | E5,E6,E7,C2 |
| Logistics | **L1** | **L4** | medium | B2,C4 |
| Finance | **L0** | **L4** | very far (mostly new build) | G1–G7,H1 |
| Risk/Scenarios | **L0** | **L4** | far | F1,H9,C6 |
| **Platform** (orchestration) | **L0** | **L4** | far (the gate for all others) | A2,H4,D5 |

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
| D-7 | Data import (CSV, date detect, bucketing) | 🔴 | ➕ | real ingestion + column mapping | A8 |
| D-8 | Hierarchical reconciliation surfaced | 🟠 | ✅ | wire `reconcile.py` output | A8 |

### 3.3 Supply / Procurement / Inventory — ✅ W2 SHIPPED 2026-06-02 (S-1…S-4)
| # | Item | Sev | BE? | What to build | Evidence | Status |
|---|---|---|---|---|---|---|
| S-1 | Feed `landed_cost` into procurement | 🔴 | ✅ | pipe landed-cost solve into `bomParts` (stop using raw cost) | B1 | ✅ governed per-part `Sourcing Terms` (import flag + duty/freight %) → `partsWithSourcing` sets `landed_cost`; MILP provably plans on landed (billet 228→255.36 ⇒ +₹41K) |
| S-2 | Stepwise freight / truck capacity (kill flat `S(i)`) | 🔴 | ✅ | send `transport_modes`/`contracts`; freight = f(qty, trucks) not flat ₹120 | B1, EOQ | ✅ `SrcFreight` truck-step on the real MILP order qty: ⌈qty/units-per-truck⌉×₹/truck, shows the marginal-truck cliff |
| S-3 | Inventory policy as **autopilot for steady parts only** | 🟠 | ✅ | (s,S)/order-up-to from `policy.py`, gated by ABC/XYZ; **EOQ never beside a MILP plan, never for one-offs** | H2, EOQ | ✅ `SrcPolicy` shows EOQ/(R,Q)/(s,S) ONLY for steady (CV≤0.5); lumpy (CV>0.5) explicitly flagged MILP-only, no EOQ |
| S-4 | Rolling re-plan UI + nervousness | 🟠 | ✅ | wire `/api/solve/rolling`; show wave churn | H2 | ✅ `SrcRolling` + **rolling-endpoint nervousness wiring fix** (read real `materials[].purchase_orders`, relative-period churn over open overlap); per-wave + total churn, STABLE/NERVOUS verdict |
| S-5 | Postponable vs pinned PO flag | 🟡 | ⚠ | surface release-timing slack | H5 |
| S-6 | Multi-echelon SS placement (RM/WIP/FG) | 🔴 | ➕ | **new** guaranteed-service layer; per-node balance is the scaffold | H6 |
| S-7 | Costly-item / MTO preset (newsvendor h vs p) | 🟠 | ✅ | expose MTO mode + CVaR buffer for costly parts | H7 |
| S-8 | MRP-at-scale UX (10+ BOM) | 🟡 | — | exception-based roll-up/drill-down, not a giant grid | H (BOM scale) |

### 3.4 Plan / S&OP
| # | Item | Sev | BE? | What to build | Evidence |
|---|---|---|---|---|---|
| PL-1 | Tie aggregate capacity to the **real line registry** | 🔴 | ⚠ | stop showing labor capacity as the line capacity | E1,E2 |
| PL-2 | Fix labor-dual → line-CapEx mis-wire | 🔴 | ⚠ | capital must consume a line/machine dual, not the labor dual | E2,F3 |
| PL-3 | Real plan cost inputs (replace `PLAN_PARAMS` seeds) | 🟠 | ✅ | governed cost-input card | E1 |
| PL-4 | Disaggregation clarity (which family/horizon, solved-vs-seed) | 🟡 | ⚠ | header + provenance | E4 |
| PL-5 | Workforce plan tie-back (covers which gap) | 🟡 | ⚠ | link hire/OT to the capacity gap it fills | E3 |

### 3.5 Production
| # | Item | Sev | BE? | What to build | Evidence |
|---|---|---|---|---|---|
| PR-1 | Wire `/api/solve/production` → real Gantt | 🔴 | ✅ | per-line swimlanes, per-SKU filter from `gantt[]` | E5 |
| PR-2 | Calendar-aware MPS (Sun/holiday exclusion, real dates) | 🔴 | ✅ | use `plant_calendar`; drill month→week→day-with-dates | E7,C2,D |
| PR-3 | Surface sequence/changeover (asymmetric) + saving | 🟡 | ✅ | already correct (`sequencing.py`); just show it | H8,E6 |
| PR-4 | Campaign run-length lever + explain setup-vs-holding | 🟠 | ⚠ | expose min-run; show why AAAA-then-BBBB | E6 |
| PR-5 | Cycle-time simple default, OEE behind Advanced | 🟡 | ✅ | reorder UI; OEE optional (already supported) | F5 |
| PR-6 | Low-util shutdown rec surfaced | 🟡 | ✅ | from `production.py` | E5 |

### 3.6 Logistics
| # | Item | Sev | BE? | What to build | Evidence |
|---|---|---|---|---|---|
| LG-1 | Allocation matrix from solve (kill literal) | 🟠 | ✅ | render real `mode_summary`/allocation | B2 |
| LG-2 | Per-SKU outbound flows + real weights | 🟡 | ⚠ | replace flat 3kg/unit + even-split | B2 |

### 3.7 Finance (the wedge — mostly build, sequenced)
| # | Item | Sev | BE? | What to build | Evidence |
|---|---|---|---|---|---|
| F-1 | Source-weighted hurdle (land/retained/promoter/PE; bank/family) | 🔴 | ➕ | blended Ke/Kd → real hurdle; wire the inert Equity-Sources card | G2,H1 |
| F-2 | Min-WACC capital-structure optimizer | 🔴 | ➕ | WACC-vs-leverage curve, DSCR-capped, find trough | G1 |
| F-3 | Required-sales bridge (mix slider → profit-mix) | 🟠 | ➕ | (WACC−ROIC)×capital ÷ blended margin | G4 |
| F-4 | EVA/ROIC-vs-WACC scoreboard → shutdown/pivot | 🔴 | ➕ | per-SKU/unit/consolidated value-destroyer flag | G3 |
| F-5 | Product-economics segmentation (mfg/resale/light-proc) | 🟠 | ➕ | per-SKU margin build → portfolio rollup | G5 |
| F-6 | DSCR covenant + DSRA | 🟠 | ⚠ | enforce DSCR (caps debt→links F-2); surface returned dscr | G6,H1 |
| F-7 | Tax + depreciation shield into NPV | 🟡 | ⚠ | tax section; WDV shield in cash flows | G7 |
| F-8 | Wire Investment cards to `capital`/`capital_capacity` | 🔴 | ✅ | kill hardcoded Investment/duals/verdict | H1,F3 |
| F-9 | De-mock Cash subtab (WC/ledger/EVM/CCC) | 🟠 | ⚠ | derive from real ledgers or honest empty | H1 |

### 3.8 Risk / Scenarios
| # | Item | Sev | BE? | What to build | Evidence |
|---|---|---|---|---|---|
| R-1 | Wire Monte Carlo on the **committed** plan | 🔴 | ✅ | `/api/solve/montecarlo`; VaR/CVaR/fill dist | F1,H9 |
| R-2 | Wire CVaR robust-SS ("hold N more") | 🟠 | ✅ | `cvar.py` → procurement floor + show premium | F1,H9 |
| R-3 | Fix MC lead-time honesty | 🟡 | ✅ | sim LT or correct docstring | F1 |
| R-4 | Control tower / what-if from real signals | 🟠 | ✅ | wire `/api/whatif`, `/ai/insights` | C6 |

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
| **W2 ✅** | Supply truth → L2 *(SHIPPED 2026-06-02)* | S-1,S-2,S-3,S-4 | W1 | ✅ MET — the procurement MILP plans on landed cost (verified billet 228→255.36 ⇒ total +₹41K); the stepwise freight card books real trucks off the MILP order qty and shows the +1-unit→+1-truck cliff; the policy autopilot lists EOQ/(s,S)/(R,Q) for steady parts only and flags lumpy parts MILP-only; rolling re-plan reports real per-wave + total nervousness (0 on the stable smooth series — proven non-zero on churny demand) with a STABLE/NERVOUS verdict. Backend: rolling nervousness wiring fixed (was structurally always 0). |
| **W3** | Production truth → L2 | PR-1,PR-2,PR-3,PR-5,PR-6 | W1 | MPS = real `/api/solve/production` Gantt, per-SKU filter, dated days excluding Sundays/holidays; changeover run-order shown with saving. |
| **W4** | Plan reconciliation → L2 | PL-1…PL-5 | W2,W3 | Aggregate capacity equals the line registry; capital consumes a line dual; disaggregation names family+horizon. |
| **W5** | Finance wedge → L2/L3 | F-1→F-9 (in that order) | W4 | Owner can enter equity/debt sources → real hurdle; WACC-curve finds min mix under DSCR; required-sales bridge drives a profit-mix target; EVA scoreboard flags a value-destroyer; Investment cards are live. |
| **W6** | Risk → L1/L2 | R-1…R-4 | W2 | MC runs on the committed plan; CVaR returns a "hold N more" with net-cost delta; no mock risk card remains. |
| **W7** | Orchestration + the loop → L3/L4 | orchestration (mix→dual→capital→risk), S-5,S-8,LG | W5,W6 | One "run the whole loop" action chains forecast→supply→plan→capital→risk on one dataset. |
| **W8** | Inventory L4 | S-6 multi-echelon SS placement (Graves–Willems / Clark–Scarf, new module) | W2,W6 | SS optimally placed across RM/WIP/FG nodes to hit network service at min cost; WIP stocked. |
| **W9** | Demand L4 | D-5 ensemble, D-7 CSV import, D-8 hierarchical reconciliation, accuracy-by-horizon, NPI like-modeling | W1 | Ensemble wins where data is deep; user imports own dataset; product×location×time reconciles; horizon-accuracy shown. |
| **W10** | Plan/Production/Finance/Risk L4 | scenario branching/versioning, S&OP cockpit, finite-capacity campaign opt, EVA-driven scenario, MC what-if bot | W4,W5,W6,W7 | Compare named scenarios side-by-side; campaign-optimized schedule; what-if bot reruns affected solvers. |
| **W11** | Platform L4 | event-sourced state, concurrent what-if, full audit/version | W7 | Branch a plan, edit, compare, merge — Kinaxis-style concurrent planning on one model. |

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

**W2 acceptance (all met):** ✅ procurement objective includes landed cost (billet 228→255.36, total +₹41K); ✅ freight is stepwise — an order over one truck shows the next-truck cost and cliff; ✅ steady parts show an (s,S)/(R,Q) autopilot, EOQ absent from lumpy/MILP-only parts; ✅ rolling re-plan shows real nervousness (non-zero on churny demand, honestly 0 when stable). Files touched: `app.py` (rolling wiring), `store.jsx` (sourcing slice + helpers), `sourcing.jsx` — all jsx transform clean; all four endpoints verified live with the exact UI payloads.

### §5 · GAP-MEIO — Multi-echelon SS placement (RM→WIP→FG) ✅ SHIPPED 2026-06-02
**Trigger:** user flagged that policy.py is single-echelon — it prescribes a finished-goods buffer even for expensive items that should be **make-to-order** (a fabricated number ⇒ No-Faking violation). User chose the *full MEIO module* over a quick UI gate. New module (explicitly allowed by the constraint; existing solver logic untouched).
- **Solver** `meio.py` — Graves–Willems **guaranteed-service model** over an assembly tree, as an **exact MILP** (PuLP/CBC, house style). Net-replenishment τ_j = SI_j + T_j − S_j; ss_j = z·σ_j·√τ_j; min Σ h_j·ss_j over integer service times. √τ linearised exactly via one-hot τ selectors (τ integer by construction — no approximation). Holding cost h_j uses **cumulative** unit value (RM landed < WIP rolled < FG full), so the buffer seeks the cheapest node. Outputs per-stage role (BUFFER vs flow), decoupling points, and `make_to_order_fg`.
- **Endpoint** `/api/solve/meio` (app.py, thin glue) + `solvers.meio` import.
- **UI** `SrcMEIO` (sourcing.jsx step 8) + `meioPayload` (RM stages w/ landed cost & BOM-propagated μ/σ → WIP → FG w/ governed committed-service knob); store.jsx `SOLVE_DEPS.meio`. Shows the MTO/MTS verdict, the per-echelon placement table, total holding + SS capital; **honest "no FG buffer" state** when MTO (never a fabricated finished safety stock).
- **Verified live (exact UI payload):** behaviour emerges from the optimisation, not a rule — at a 0-day quote the FG is forced make-to-stock (holds a finished buffer); lengthen the committed service and the FG flips to **make-to-order** and the buffer is pushed **upstream to cheap RM**; the expensive TPA-7722 (₹2050) decouples *further upstream* and ties up *less* finished capital (₹603) than the cheaper bearing (₹1139) at the same service. All jsx transform clean; meio.py/app.py parse clean. Status: ✅

> **Next wave = W3 (Production truth → L2):** PR-1 wire `/api/solve/production` → real per-line Gantt
> (per-SKU filter from `gantt[]`), PR-2 calendar-aware MPS (use `plant_calendar`, exclude Sundays/holidays,
> drill month→week→day-with-dates), PR-3 surface sequence/changeover + saving (already correct in
> `sequencing.py`), PR-5 cycle-time-simple / OEE-behind-Advanced, PR-6 low-util shutdown rec. Expand W3 into
> atomic tasks the same way. Keep the expansion **one wave ahead** — the ledger §3.5 holds the scope.

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
</content>
