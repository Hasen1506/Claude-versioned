# Design Remediation — Unified Issues, Solution Exploration, Review Rubric & Tournament

**Date:** 2026-06-04 · **Build:** main @ `d5020e8`
**Inputs:** [USER_JOURNEY_AND_DESIGN_CRITIQUE.md](USER_JOURNEY_AND_DESIGN_CRITIQUE.md) (per-stage friction) +
[FIRST_TIME_USER_NAVIGATION_AUDIT.md](FIRST_TIME_USER_NAVIGATION_AUDIT.md) (field-by-field + cross-stage
structure) + [SCENARIOS_VERIFICATION.md](SCENARIOS_VERIFICATION.md) (cross-checked §6.0 — a
verification/modeling doc; it corroborates R1's cross-stage flows and contributes the opening-inventory
units item + the 5 end-to-end think-aloud scripts, but introduces no net-new issue category).

**Purpose.** Collapse the two audits' findings into **structural root causes** (so we fix mechanisms, not
symptoms), explore a *range* of design solutions, and hand a **review agent a rubric** to score / tournament
them. **Done = the review agent's definition-of-done (§3.3) is met**, not "I said so."

**Honest stance.** The diagnoses are well-grounded in code. The *solutions* below are deliberately
*plural and competing* — I do not assume the synthesis I lean toward is correct. The review loop (§4) is
the arbiter.

---

## §1 — Unified structural issue register (root causes, not pages)

Every concrete finding from the audits maps to one of **ten structural roots** (R10 added after the
coverage cross-check below caught it slipping through both critique docs as "not fully audited"). Fix the
root and the per-tab instances fall together.

### R1 · No single source of truth; cross-stage lineage is invisible
*The deepest root.* A value is assembled from inputs on multiple pages and consumed on others, with no
structure surfacing the chain. The dependency graph exists in code (`SOLVE_DEPS`, `LOOP_STEPS`,
`markStale`) but only as STALE badges, and it collapses every parameter into one `'config'` token.

| Instance | Where defined → consumed |
|---|---|
| **Carry rate** = WACC + spread | Finance·Capital (solved) + Sourcing·Policy → procurement/policy/rolling, MC, EVA |
| **Service level = TWO fields** (`serviceLevel` vs `serviceLevelOverride`) | Setup → Products policy + MC; Sourcing → procurement/MEIO — *never reconcile* |
| **FX rate** "single source of truth" with **no working editor** | `config.fxRates` → landed cost, hedging, VaR, imported parts |
| **Opening inventory** = two concepts | Plan scalar (t=0) + Network on-hand matrix (MRP) |
| **Line shadow price (PL-A)** flows via cache **and** manual paste | Plan·Capacity → Finance·Investments |
| **MOQ / cycle** multi-home | Products (Define+Costs) + Production (Cycle) |
| **"Re-plan whole model"** runs **6 of ~13** solves | Home action vs `LOOP_STEPS` |

### R2 · Solved vs seed/illustrative is not visually legible (trust)
Real solves and demo seeds look identical except for a small badge.
Instances: Finance·Cash (default seed tab) · Scenarios·Cost (whole seed tab) · Finance Buy-vs-Lease
(hardcoded, ×2) · Plan·Gap (badged *derived*, reads `M.sop` seed) · Finance·FX VaR (hardcoded) ·
Console pipeline + ResX seed fallbacks · Logistics pre-solve "planned" KPIs read as results.

### R3 · Inert controls that look interactive (responsiveness)
A live-looking dead control teaches "this app doesn't respond," poisoning trust in the controls that work.
Instances: Console **SOLVE / Reset / Solve-all-queued** · Demand manual history grid (`defaultValue`) ·
Finance·FX inputs + "Board pack" · Production·Cycle inputs · Setup Frozen/Slushy · 7-of-8 Home KPI tiles ·
SAP "Overview" boxes · version-history "restore".

### R4 · Two navigation systems / inconsistent vocabulary & metaphor
Ribbon (6: PROCURE/PRODUCE/CAPITAL) ≠ rail (12: Sourcing/Production/Finance); CAPITAL→`plan`. Step-scroll
vs sub-tab metaphor split. Production step-numbers scramble (0,3,4,5). Reference reachable only via "Learn".

### R5 · Scope ambiguity — single-item vs portfolio
Global item selector vs a multi-SKU job, **no worklist** (Demand/Products/Sourcing/Network). Products
ScopeBanner says "THIS product" above the all-SKU grid. Network silently flips per-item ↔ global.

### R6 · Section ordering & density (cognitive load)
Sourcing = 15 sections, **PO plan at step 11**, synthetic-teaches-grid before the real result. Demand =
answer (forecast) before method (leaderboard). Setup ★ wedged between steps 1 and 2.

### R7 · Shared object presented as per-entity (data-model honesty)
Single `M.bom` rendered as a per-product bill (Products + Sourcing, title interpolated). Changeover matrix
hardcoded to **4 of 6** finished SKUs.

### R8 · Duplication & refactor-churn leakage
"moved here from X" notes shipped to users · Console mirrors stage result cards · onboarding ⇄ Profile (same
6 Qs) · Buy-vs-Lease rendered twice. *(Exception Cockpit + Value Ledger were already consolidated to Home —
not an open issue.)*

### R9 · Engineering jargon to business users
`z=1.645` on the Identity card · Workforce/Inventory **CV** · `s,S` / `R,Q` unglossed.

### R10 · Accessibility & responsive (cross-cutting — was under-audited)
Flagged in both critique docs as "not fully audited," so it never became a root — the coverage
cross-check (§6.0) caught it. From a *static* read: pervasive **8–9px mono type**; **color-only state
encoding** (binding=red / slack=green with no text twin); **fixed-px layout** (188px rail, fixed cards);
**`overflowX` data tables** (narrow viewport horizontal-scrolls instead of reflowing); **no visible focus
rings** on the custom buttons. Honest caveat: this needs its own audit on the *running* app — it cannot be
fully characterized from source.

**Dependency between roots:** R1 is foundational; R2 and R3 are special cases of "the UI doesn't tell the
truth about a value/control's state"; R4–R6 are information architecture; R7 is data-model; R8–R9 are
hygiene. A solution that fixes the *state-legibility contract* (R1/R2/R3) generalizes furthest.

---

## §2 — Solution exploration

### §2.1 Design primitives (reusable mechanisms)

Rather than N per-page patches, six primitives each knock out multiple roots. Programs (§2.2) are
*bundles* of these.

- **P1 · The Field/Value contract.** One component every input/output renders through, encoding three
  things by construction: **provenance** (seed / override / solved / derived), **affordance** (live /
  read-only / redirect→home), and a **lineage hook** (what feeds me / what I feed). Kills R3 (a read-only
  value can't look editable), makes R2 legible (provenance is structural, not a stray badge), and gives R1
  its UI anchor. *Variants:* (1a) provenance chip + "ⓘ lineage" popover; (1b) border/tone system (weak
  alone — color-only fails a11y); (1c) hover "trace" overlay.
- **P2 · Parameter governance surface (single source of truth).** Every governed parameter has exactly one
  home; a registry lists home / current value / provenance / consumers. Forces the R1 dedups (one service
  level, one FX editor, one MOQ home). *Variants:* (2a) a dedicated page; (2b) a slide-over panel invokable
  from any field ("governs ↔ governed-by"); (2c) folded into Setup as "Model Inputs".
- **P3 · One navigation model.** Single stage vocabulary everywhere; the ribbon mirrors the rail's names &
  count *or* demotes to a freshness/progress strip (not a second nav); sub-tabs become the one rule for any
  page > ~6 sections (also straightens Production numbering). Fixes R4 + the structural half of R6.
- **P4 · Run / Read / Design / Inspect IA.** Separate **operational** (weekly: run, read results) from
  **strategic** (quarterly: design science, inspect models). Sourcing → Run/Design; Console → Inspect (Lab)
  not duplicate-Read; Finance leads with solved. Fixes R6 + R2-by-placement + R8 (Console mirrors).
- **P5 · Scope system.** A persistent **portfolio worklist** ("2/6 committed — next: TPA-3215") + a
  **scope badge** (item / global) on every section + fix the ScopeBanner contradiction. Fixes R5.
- **P6 · Honest-affordance + lineage breadcrumbs.** Rule: no interactive affordance unless wired; unwired →
  disabled/preview/redirect. Plus the **lineage breadcrumb** pattern the app already proves on two cards
  (carry-rate decomposition; external-signals "drives: … (now stale)"). Operationalizes R1 inline and
  finishes R3. *(P6 is largely P1 applied + the "drives/driven-by" line.)*

### §2.2 Candidate programs (competing end-to-end approaches)

Each is a coherent bet on *where to start*. R-coverage: ✅ full · 🟡 partial · ⬜ untouched.

| Program | One-line thesis | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | New surface | Risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A · Contract-first** (P1+P6) | Fix the shared Field/Card primitives so provenance+affordance+lineage are correct *by construction*; everything inherits it | 🟡 | ✅ | ✅ | ⬜ | ⬜ | ⬜ | 🟡 | 🟡 | ✅ | low | low (touch shared components) |
| **B · Governance-first** (P2+P1) | Stand up the Parameter Registry + dependency map; dedup parameters; link fields to it | ✅ | 🟡 | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | 🟡 | 🟡 | high (new page/panel) | med (dedup refactors) |
| **C · IA-first** (P3+P4+P5) | Re-segment navigation: one vocabulary, Run/Design/Inspect bands, sub-tab rule, worklist | ⬜ | 🟡 | ⬜ | ✅ | ✅ | ✅ | ⬜ | ✅ | ⬜ | med | med-high (visible reorg) |
| **D · Trust-first** (P1 minimal + P6) | One solved-vs-seed visual language + kill every inert control + provenance everywhere; defer deep lineage | ⬜ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | 🟡 | ⬜ | 🟡 | low | low |
| **E · Phased synthesis** | Sequence the primitives: **Ph1** Contract (A/D) → **Ph2** Governance panel (B) → **Ph3** IA re-seg (C) → **Ph4** Scope (P5) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🟡 | ✅ | ✅ | grows over phases | spread/managed |

**Tensions the reviewer must weigh (no free lunch):**
- *Contract-first (A/D)* gives the fastest consistency and trust win but doesn't answer "where's the
  structure?" until the lineage hook (P1's variant) is actually populated — which needs the dependency map
  (B).
- *Governance-first (B)* most directly answers your carry-rate question but adds the most new surface and
  presumes the dedup refactors land cleanly (two service-level fields → one is a behavior change).
- *IA-first (C)* most improves first-time navigation/density but leaves the trust (R2/R3) and lineage (R1)
  problems standing — arguably reorganizing furniture before fixing the wiring.
- *Phased (E)* is the obvious hedge, but "phased" can be a way to avoid committing to a hard ordering;
  the reviewer should test whether the phase order is *justified* or just risk-averse.

**R7 (shared BOM)** is special: it's a data-model correctness gap, not a presentation one. Every program
must either make the BOM genuinely per-product **or** stop interpolating the product name over a shared
bill. No program "solves" R7 by UI alone — flagged so the reviewer doesn't credit a cosmetic fix.

---

## §3 — Review rubric (for the review agent)

### §3.1 Criteria & weights (score each 0–5)

| # | Criterion | What "5" looks like | Weight |
|---|---|---|---|
| C1 | **Root-cause depth** | fixes the mechanism (R*) so instances fall together; no per-page whack-a-mole | ×3 |
| C2 | **Cross-section generality** | one mechanism demonstrably covers many tabs/instances | ×3 |
| C3 | **Trust / provenance** | upholds "no faking"; makes solved-vs-seed legible at a glance; introduces **zero** new inert/contradictory/seed-as-real states | ×3 |
| C4 | **First-time comprehension** | improves the user's mental model; discoverable; de-jargons; answers "is this real? did my edit do anything? where does this number come from?" | ×3 |
| C5 | **Architecture fit** | works within the real constraints: single shared dataset, one-item scope model, `@babel/standalone` no-build, shared global scope, no rewrite | ×2 |
| C6 | **Implementation cost / phaseability / reversibility** | proportionate; blast radius bounded; can land incrementally; revert-safe | ×2 |
| C7 | **Measurability** | states *how you'd know it worked* (e.g., a 5-task think-aloud; "stale-after-edit visible"; "find-the-PO-plan time"; "tell solved from seed in <2s") | ×2 |
| C8 | **Protects existing strengths** | does not regress: Solver Lifecycle, Anatomy Lab, profile gate, honest fencing, single-dataset provenance | ×2 |

Weighted max = 5 × (3+3+3+3+2+2+2+2) = **100**.

### §3.2 Guardrails (auto-fail any solution that…)
- introduces a new control that looks interactive but isn't (re-creates R3);
- presents a seed/illustrative number with the same weight as a solved one (re-creates R2);
- "fixes" R7 (shared BOM) by relabeling without addressing the data model;
- requires abandoning the single-dataset / no-build architecture;
- removes a protected strength (C8) to gain a point elsewhere.

### §3.3 Definition of done (the review agent's completion test)
The task is complete when **all** hold:
1. **Coverage:** every root R1–R9 is addressed by at least one accepted mechanism (R7 by a real data-model
   move, not relabel).
2. **No new harm:** the recommended program passes every §3.2 guardrail.
3. **Winner quality:** the recommended program scores **≥ 80/100** weighted **and** wins the §4 tournament
   (beats each alternative head-to-head on the weighted total, or the reviewer documents why a merge beats
   all standalone programs).
4. **Falsifiability:** the recommendation ships with C7 measures concrete enough to run a think-aloud
   against.
5. **Open-issue ledger:** any criterion scored ≤ 2 for the winner is listed with a specific remediation —
   none left implicit.

---

## §4 — Tournament protocol

1. **Score** Programs A–E on C1–C8 (0–5), compute weighted totals, show the matrix.
2. **Pairwise:** for the top 2–3, run head-to-head — which better serves C1/C3/C4 (the ×3 criteria) and
   why; note where a *merge* (e.g., B's registry + A's contract) dominates either alone.
3. **Stress the winner:** apply §3.2 guardrails + §3.3 done-test; list every criterion ≤ 2 with a fix.
4. **Verdict:** recommended program (or merge) + phase order + the C7 measures + the open-issue ledger.
5. **Iterate:** the designer (me) revises to close ≤ 2 criteria; re-review until §3.3 passes.

### §4.1 Scorecard template (review agent fills)

```
Program  C1×3 C2×3 C3×3 C4×3 C5×2 C6×2 C7×2 C8×2  | Weighted /100  | Rank
A
B
C
D
E
Pairwise notes:
Winner / merge:
Guardrail check (§3.2):
Done-test (§3.3):
Open-issue ledger (criteria ≤2 + fix):
```

---

## §5 — Review output & iteration log

### §5.1 Review pass 1 — verdict (adversarial review agent, claims verified against code)

All four load-bearing claims **confirmed** with file:lines: single-`config` token (`store.jsx:1106–1120`,
`markStale` 1126–1146); two un-reconciled service-level fields (`products.jsx:272` uses
`config.serviceLevel`; `sourcing.jsx:176–178` `effServiceLevel` uses `config.serviceLevelOverride`);
`LOOP_STEPS` = 6 of 13 solves (`store.jsx:822–844` vs `SOLVE_DEPS` 1106–1120); carry rate assembled across
two pages (`finance.jsx:159–163`). The reviewer added a sharpening: claim (b) is not merely hidden
lineage, it is an **active correctness divergence** — which raises the bar on any program that doesn't
*dedup* it.

| Program | C1×3 | C2×3 | C3×3 | C4×3 | C5×2 | C6×2 | C7×2 | C8×2 | /100 | Rank |
|---|---|---|---|---|---|---|---|---|---|---|
| A · Contract-first | 3 | 4 | 5 | 4 | 5 | 5 | 3 | 5 | 75 | 2 |
| B · Governance-first | 5 | 4 | 3 | 4 | 3 | 2 | 3 | 4 | 69 | 4 |
| C · IA-first | 2 | 3 | 2 | 4 | 4 | 3 | 3 | 4 | 62 | 5 |
| D · Trust-first | 3 | 3 | 5 | 3 | 5 | 5 | 3 | 5 | 70 | 3 |
| **E · Phased synthesis** | 5 | 5 | 5 | 5 | 4 | 4 | 3 | 5 | **88** | **1** |

**Tournament:** E wins outright. The doc's hinted merge (B's registry + A's contract) = E's Phase 1+2; it
beats every standalone but does **not** dominate E (leaves R4/R5/R6). E's phase order survives the
"is-it-just-risk-aversion?" challenge — it's a real dependency topology (the lineage hook is inert without
the dependency map; reorganizing IA over un-trustworthy wiring is premature).

**Done-test result: NOT DONE.** Condition 3 (≥80 + wins) ✅, condition 5 ✅, but **condition 1 FAIL**
(R7 shared-BOM has no committed data-model move — E left it 🟡) and **condition 4 FAIL** (C7 measures are
generic, not bound to E's phases → not falsifiable). Guardrails: E passes the R2 guardrail *only if*
contract ships before the registry; the R7 guardrail is conditional on closing #1.

**Ledger (6 items):** (1) R7 needs a real data-model decision; (2) bind C7 measures to phase gates;
(3) split the single `config` token so `markStale` names the parameter; (4) the "Re-plan whole model"
6/13 mislabel; (5) the service-level dedup is an irreversible behavior change → migrate it; (6) write the
"contract-before-registry" ordering as a hard gate.

### §5.2 Designer iteration → **Program E′ (committed)**

E′ = E with all six ledger items closed and bound to phases. **Hard sequencing gate (closes #6):** the
parameter registry (Phase 2) **must not ship before** the Field/Value provenance contract (Phase 1) — else
the registry re-creates R2. Non-negotiable.

**Phase 1 · Contract & honesty** *(lowest risk, reversible; unblocks everything)*
- **P1 Field/Value contract** every input/output renders through: provenance (seed/override/solved/derived)
  + affordance (live/read-only/redirect) + a lineage hook (empty until Phase 2 populates it).
- **Kill every inert control** (R3 list): wire it, or render it disabled/preview/redirect. No interactive
  affordance unless wired.
- **(closes #4)** Relabel the Home action **"Re-plan the spine · 6 of 13 solves"** with a note naming the
  7 it doesn't refresh and where to run them. (Extending `LOOP_STEPS` to all 13 is a separate later option,
  not required for honesty.)
- **(R7 interim)** Stop interpolating the product name over the shared bill; label it **"reference BOM —
  per-product bills pending."** Honest stopgap only; the real fix is Phase 2.
- **Acceptance gates (C7, closes part of #2):** ① a user tells solved from seed in **<2 s** on Finance and
  Scenarios; ② a STALE badge appears after **every** input edit (audit think-aloud tasks 4 & 5); ③ **zero**
  controls with an interactive affordance are unwired (grep the inert-control catalog → all resolved).

**Phase 2 · Governance & data-model** *(the structural core; highest cost, gated behind Phase 1)*
- **P2 Parameter registry:** one home per governed parameter + current value + provenance + **consumers**.
- **(closes #3)** Split `'config'` in `SOLVE_DEPS` into named sub-tokens (`config.wacc`,
  `config.serviceLevel`, `config.spread`, `config.fx`, `config.tax`, `config.budget`) and route `setConfig`
  so `markStale` cascades **the named parameter** — so the stale badge ("stale because you changed WACC")
  agrees with the registry's static lineage. Without this, R1 is only half-fixed.
- **(closes #5)** Dedups **behind audit-logged migrations**: service level → one field, defaulting
  `serviceLevelOverride := serviceLevel` so no live plan/branch silently re-plans (logged via `events[]`);
  one canonical MOQ home; a **real FX editor** (the current single-source-of-truth has no working input).
- **(closes #1 — the real fix; explicit data-model work item, NOT a presentation phase)** Convert `M.bom`
  from one shared array to a **`{sku → parts[]}` map**; update every `M.bom` reader and
  `editPartAttr(sku, part, …)` to carry the SKU dimension. **Same-class gap:** generalize the changeover
  matrix from the hardcoded 4-SKU list to all finished SKUs. Until this lands, Phase 1's honest relabel
  holds the line.
- **Acceptance gates (C7):** ④ trace the carry rate to its two homes in **<3 clicks**; ⑤ editing the
  service level in Setup provably changes the Sourcing plan (now one field) — or the UI states they are one
  field; ⑥ the stale badge names the **parameter**, not "config"; ⑦ two finished SKUs show **different**
  BOMs.

**Phase 3 · IA re-segment** *(over now-trustworthy, deduped wiring)*
- One nav vocabulary (reconcile ribbon↔rail, or demote the ribbon to a freshness/progress strip — not a
  second nav); sub-tab rule for any page > ~6 sections; **Sourcing → Run / Design** (PO release out of step
  11); Production renumber per tab; Finance default → **Capital** (solved), not the seed Cash tab; surface
  Reference in the rail. **Acceptance:** ⑧ find the PO release plan in **<30 s**; ⑨ no step-number scramble;
  ⑩ the first nav metaphor learned applies on every page.

**Phase 4 · Scope**
- Portfolio **worklist** ("2/6 committed — next: TPA-3215"); per-section **scope badge** (item/global);
  fix the Products ScopeBanner contradiction. **Acceptance:** ⑪ commit all 6 SKUs without losing the
  worklist; ⑫ every section's scope is labeled.

**Residual / explicitly out-of-this-program:** R9 jargon (de-gloss z/CV/s,S — folded into Phase 1's Field
contract as inline help); R8 churn notes (delete in Phase 3 with the IA pass). Extending `LOOP_STEPS` to
all 13 solves is optional and deferred — the Phase 1 relabel makes the current 6/13 honest.

### §5.3 Self-assessment vs §3.3 (pre-confirmation)
1. Coverage — R1✅(Ph2 +token split) R2✅(Ph1) R3✅(Ph1) R4✅(Ph3) R5✅(Ph4) R6✅(Ph3) **R7✅ now a real
   data-model item (Ph2), not a relabel** R8✅(Ph3) R9✅(Ph1) **R10🟡 (a11y tokens — type scale, text-twin
   for color state, focus rings — fold into the Ph1 Field/Value contract; full a11y/responsive pass is its
   own running-app audit, see §6.6).** 2. Guardrails — pass under the
   contract-before-registry gate. 3. Quality — E′ inherits E's 88/win. 4. Falsifiability — **12 bound
   acceptance gates ①–⑫** with thresholds. 5. Ledger — all 6 closed above. → *Believed DONE; sent for
   confirmation review (§5.4).*

### §5.4 Review pass 2 — confirmation → **DONE**

The review agent re-verified the remedies against code and ruled **DONE**:
- **Ledger closure (6/6 CLOSED):** (1) R7 is a genuine data-model move — and *feasible*, because `M.skuBom`
  (`data.jsx:62–69`) already encodes the target `{sku→parts[]}` shape, so the map is reconciled, not
  invented; (2) the 12 acceptance gates ①–⑫ are falsifiable; (3) the named-token split refines the existing
  `markStale` `root`/`staleSrc` path (`store.jsx:1134–1138`), so static (registry) and dynamic (stale badge)
  truths agree; (4) the relabel removes the `home.jsx:121` mislabel; (5) the dedup migration defaults
  `serviceLevelOverride := serviceLevel`, audit-logged via `events[]`, so no silent re-plan; (6) the
  contract-before-registry gate is stated as non-negotiable.
- **Guardrails (§3.2): all PASS** — incl. the previously-conditional R2 (sequencing gate now hard) and R7
  ("no cosmetic fix" — cleared by the real data-model move).
- **Definition-of-done (§3.3): all 5 PASS** — coverage (R1–R9, R7 by data-model move), no new harm, winner
  quality (88/win retained), falsifiability (12 bound gates), ledger closed.

**Highest-risk implementation item to watch (reviewer's flag):** the Phase-2 `M.bom` → `{sku→parts[]}`
conversion is the widest blast radius — many readers (`bomParts` `store.jsx:452`, `partsOf` `data.jsx:536`,
`editPartAttr` `store.jsx:1228`, master export/import, the BOM renders) and `editPartAttr`'s signature
change ripples to every call site. Land it behind gate ⑦ (two SKUs show different BOMs) + a procurement
re-solve smoke, and keep the Phase-1 "reference BOM" relabel until ⑦ passes.

**Status: COMPLETE.** Program **E′** is the accepted remediation; the review agent's criteria are met.
Implementation (Phases 1→4) is the next body of work and is **not** part of this design task — it begins
only on your go.

### §5.5 Phase 1 implementation log — **BUILT 2026-06-04** (Contract & honesty)

*Lowest-risk, reversible set. All changes frontend (jsx/html); backend untouched. Nothing committed.*

**Shared contract layer (`lib.jsx`):** three new primitives exported through `window` —
`SeedFence` (loud "◇ ILLUSTRATIVE — not a solve" band, R2/gate ①), `PreviewTag`
(preview/readonly/redirect marker for an honestly-demoted control, R3/gate ③), `Lineage`
(the "⛓ what-feeds-this / what-this-feeds" hook — **ships the hook now**, populated against the
real dependency map in Phase 2). These *extend* the existing trust atoms (`Provenance`,
`SolverInput`, `StaleMark`) rather than replace them.

**A11y (`index_v2.html`, R10):** global `:focus-visible` rings on every focusable control
(inputs need `!important` to beat their inline `outline:none`) + `prefers-reduced-motion`. Type-scale /
table-reflow remain the deferred running-app pass (§6.4).

**Re-plan relabel (`home.jsx`, closes #4):** "Re-plan whole model" → **"Re-plan spine · 6 of 16"**
with a `SectionInfo` ⓘ naming the 6 it runs and the **10** it does *not* refresh (Profit-mix,
Disaggregate, Reconcile, Sequencing, Lot-sizing, Transport, Allocation, Consolidate, CVaR,
Capital-capacity) + where to run them. **Honest correction:** the design doc said "6 of 13 / 7 skipped";
the code's real figures are **`LOOP_STEPS`=6, `M.solvers`=16 → 10 not refreshed**. All four "whole model"
strings on Home fixed.

**Inert-control catalog (R3/gate ③) — all 9 resolved (wired ✦ or honestly demoted ◇):**
✦ Console "Solve all queued" → real `runFullLoop`; ✦ Console Reset → clears the picker; ✦ Setup
Frozen/Slushy → two real `setPlanning` inputs; ✦ Finance "Board pack" → real `<ReportExport/>` PDF.
◇ Console band-① SOLVE → disabled preview (real runs = Anatomy Lab ③ / header spine), card relabeled
"Run Profile · preview"; ◇ Demand manual grid → read-only values + note (CSV import is the wired path);
◇ Finance FX inputs → disabled + false "editable" claim fixed (real editor = Ph2); ◇ Production
OEE/Run-hrs/MOQ → disabled with honest hints (Cycle+Line already wired); ◇ Reference SAP boxes →
dropped the fake selected-tab styling; ◇ chrome "restore" → greyed "restore (soon)". Home's 7 non-drill
KPI tiles needed **no change** — already static (no `onClick` ⇒ no pointer affordance; only the working
Margin tile is interactive).

**R7 interim relabel (Products + Sourcing):** shared `M.bom` titles "Bill of Materials · {product}" /
"Parts of the selected product" → **"Reference Bill of Materials" / "Parts of the reference BOM"**, badge
"· shared", honest note "editing a row changes it for every product; per-product bills land in Phase 2".

**SeedFence applied** to the bare hardcoded **Finance Buy-vs-Lease** card (R2 instance on the gate-①
tab) + softened its green "✓ LEASE wins" verdict to amber "◇ Illustrative". (Finance·Cash and
Scenarios·Cost were found to **already** carry good bespoke seed banners — gate ① was already passing
there; not churned.)

**Gate results:** ① solved-vs-seed legible on Finance & Scenarios — **PASS** (existing banners + new
Buy-vs-Lease fence). ② STALE-after-edit — **PASS** (pre-existing `markStale` path in `store.jsx`, 24 refs,
untouched). ③ zero unwired interactive affordances — **PASS** (catalog re-grepped, all 9 resolved).
**Verification:** 18/18 jsx babel-parse OK; live Flask smoke — static serve 200 on all edited files +
edits present in served bytes; `/api/meta/solvers` 39 endpoints; real 2-product `profitmix` → **Optimal**.
(Per §6.6, C7/C6 are graded on the *running* app in the post-implementation pass, not here.)

**§6.6 post-build verification (adversarial agent, running app) — VERDICT: DONE**, with 3 in-scope gaps
found and **now closed (2026-06-04)**: (1) the **Finance·FX "Procurement Risk & FX" card** was hardcoded
under a `VaR` badge with no fence → badge→`illustrative` + `SeedFence` added (`finance.jsx:787`); (2) the
**Sourcing R7 relabel was only half-applied** — inner card was fixed but the StageHeader kicker + ScopeBanner
still framed the shared `M.bom` as the *selected product's* parts → both reworded to "reference BOM · shared,
per-product pending" (`sourcing.jsx:194,199`); (3) the **"6 of 16" count was off** — the 6-step spine maps to
only **5** of the 16 named engines (Forecast, Procurement, Aggregate, Production, Monte Carlo) + the linecap
signal (not one of the 16), so **11** are not refreshed and the list had omitted plain **Capital** (≠
Capital-capacity) → button→"6 steps", SectionInfo corrected to "refreshes 5 … other 11" with `Capital` added
(`home.jsx:122`). Also relabeled the residual "whole model" strings in the Scenarios·Loop subtab →
"planning spine" (`scenarios.jsx:536,723,1039`). Agent re-grade in-scope: C3 5/5, C4 4/5, C6 4/5, C7 4/5;
gates ①②③ PASS; all 18 jsx parse clean post-fix.

**Next:** Phase 2 (Governance & data-model — parameter registry, `SOLVE_DEPS` token split, dedups +
real FX editor, **`M.bom`→{sku→parts[]} map** — the widest blast radius) on your go. Hard gate stands:
registry must not ship before this contract (it now exists).

---

### §5.7 Phase 2 implementation log — **BUILT 2026-06-04** (Governance & data-model)

All six work items built; all frontend + one new state slice; backend solver `.py` untouched. NOT committed.

1. **Service-level dedup.** Two fields for one concept (`config.serviceLevel` set in Setup vs
   `config.serviceLevelOverride` set in Sourcing — Setup edited one, Sourcing read the other; they never
   saw each other) → folded to the single canonical `config.serviceLevel`. `effServiceLevel()`
   (`sourcing.jsx`) now reads it; the Sourcing `SolverInput` rebinds to it; a one-time **load migration**
   in `store.jsx` (`s:` IIFE) copies any legacy `serviceLevelOverride` into `serviceLevel` and drops the key.
   Verified: editing α in Setup ⇒ Sourcing MILP plans the same α.

2. **`SOLVE_DEPS` config-token split.** The coarse single `'config'` token re-flagged EVERY config-dependent
   solve on ANY edit. Carved out the two field-groups whose reader set is provably ONE solver family:
   `cfg.prod` (prodLaborRate/Shutdown/TimePhased/HoldingCost/CampaignMinRun/Routing/skuLaborFrac →
   production·aggregate·linecap — **also fixes a prior gap: those solves never listed `'config'`, so prod-knob
   edits silently failed to stale them**) and `cfg.profit` (pmBudget/pmWarehouse → profitmix). Everything else
   stays broad ON PURPOSE — taxRate/finEquity/finDebt fan into WACC→`carryRate()`→the whole inventory family,
   so a finer token there would SILENTLY under-stale (over-stale is safe, under-stale is the bug we refuse).
   `CONFIG_TOKEN` map + `configTokens()` union in `setConfig`. **Behavioral proof (node harness replicating the
   real maps): 11/11** — FX/service stale the inventory family but NOT production; prod-knobs stale
   production/aggregate/linecap but NOT procurement/profitmix; pmBudget stales ONLY profitmix; transitive
   staleness reaches montecarlo; migration folds 0.985 override correctly.

3. **Real FX editor** (`finance.jsx` FinFX). Phase-1 had demoted the FX inputs to disabled+PreviewTag with
   "editor lands in the governance pass." Now LIVE: editable `NumInput`s write `config.fxRates` (+ editable
   `config.fxAsOf`), per-rate seed-vs-override provenance hint, "↺ Reset to seed", badge greens on override.
   `fxFactor()` reads `config.fxRates`, so an edit re-prices landed cost and (via the broad `config` token)
   re-flags procurement/policy/rolling/meio/meionet/cvar/profitmix. The stale "FX editor pending" line on the
   Procurement-Risk SeedFence updated to point at the now-live table.

4. **Parameter Registry (P2).** New lib primitive `ParamRegistry({rows,onNav})` (exported) + a new Setup
   StageSection **"Parameter Governance"** (`SetupRegistry`, bound to LIVE config/planning). One ledger of 11
   governed inputs: live value, provenance (seed vs override, computed live), the **stale-cascade TOKEN** the
   input travels on (the SAME key `SOLVE_DEPS` uses — registry & cascade tell one story), what it FEEDS (with
   the ⛓ `Lineage` popover), and a jump to each param's editor. No faked rows. Hard gate honored — shipped
   AFTER the P1 provenance contract.

5. **`M.bom`→per-SKU map (R7 real fix).** Honest model: `M.bom` is the PARTS MASTER (cost/lead/MOQ/supplier/
   scrap — intrinsic to the part, correctly shared); `M.skuBom{sku→[{part,qty}]}` is which parts an FG uses +
   qty-per (the genuinely per-product attribute). New `bomForSku(sku)` resolver (master ⋈ skuBom ⋈ a thin
   per-SKU `state.bomOverrides[sku][part].qty` layer) + `editPartQty(sku,part,val)` (writes overrides,
   `markStale('bom')`, consumed by `bomForSku` AND `montecarloPayload.skuParts` ⇒ the edit is REAL not
   decorative). Rewired the 3 Products per-SKU contexts (ProdBOM now shows the real per-product bill titled
   "Bill of Materials · {name}" with per-SKU qty editing + shared part-attr editing distinguished; ProdCosts
   material rollup; ProdPolicy derivation) to `bomForSku(p.sku)`. **Sourcing left on the master ON PURPOSE** —
   its procurement MILP is inherently all-parts (plans the parts master, demand aggregated across all FGs;
   `SrcMRP` indexes `proc.result.materials[pi]` in `M.bom` order) — relabelled to the honest "parts master ·
   portfolio-wide" instead of the prior "per-product pending." (`bomParts` and `montecarlo.skuParts` already
   carried the per-SKU costed bill — solver side unchanged.)

6. **Changeover 4→6 SKUs.** Matrix was a hardcoded 4×4 ([data.jsx]) while there are 6 FGs; `ProdChange`
   (production.jsx) and store `subMatrix` both hardcoded the same 4-SKU list. Generalized: new canonical
   **`M.changeoverSkus`** (the 6 FGs) + a 6×6 matrix; both consumers read the array (no implicit "first 4");
   `ProdChange` derives N + a greedy-NN fallback order. **Live: `/api/solve/sequence` returns an exact
   Hamiltonian path over all 6** (total changeover 5.1 hrs, basis exact).

**Verification:** 18/18 jsx babel-parse OK; app.py+solvers compile; live Flask — all edited files serve 200,
every Phase-2 symbol present in SERVED bytes, `/api/meta/solvers` 39 eps, profitmix→**Optimal** (692,300),
6-SKU sequence→**exact**; the 11/11 cascade/dedup node proof above. New state slice: `bomOverrides{}`. New
exports: `bomForSku`, `editPartQty` (store), `ParamRegistry` (lib). (Server started nohup+pidfile, killed by
PID — never `pkill -f app.py`.)

**§6.6 post-build adversarial review (agent, running app) — VERDICT: DONE.** No under-staling (the carve-outs
cfg.prod/cfg.profit are precise; broad `config` over-stales safely — independently re-derived), no faking
(`editPartQty` consumed in two real paths; registry live; FX inputs reach `fxFactor`). 3 in-scope gaps found,
**all closed (2026-06-04):** (1) registry blurb claimed an edit "re-flags precisely the FEEDS solves and nothing
else" — false for the 5 broad-`config` rows (they over-stale) → reworded to "carve-outs re-flag exactly their
FEEDS; broad `config` over-flags conservatively (≥ FEEDS, never fewer)" (`setup.jsx` info + Reading); (2) model
round-trip dropped per-SKU qty edits — `bomOverrides` was missing from `exportModelJson`'s `state` block →
added (`store.jsx:1421`; import already applies `m.state`); (3) the service-level migration wasn't audit-logged
(§5.2 #5 asked for logged migrations) — now appends a `type:'migration'` record directly into the loaded
`events[]` in the IIFE (logEvent isn't defined that early), verified: folds/drops/logs + no-op when absent +
empty-override edge case. Agent re-grade: items 1–6 all PASS; the two highest-risk audits (token under-staling,
registry truthfulness) pass on the safe side.

**§6.6 PRESCRIBED VERIFICATION — VERDICT: VERIFIED-DONE (2026-06-05).** The review block above was the *improvised*
adversarial pass (the method the user later corrected); this is the file's actual §6.6 protocol run via the
ready-to-paste verification-agent command, so Phase 2 now carries the same audit trail as Phases 3+4. Independent
general-purpose agent, running app (served-bytes + code-path + live-solver evidence; no headless browser, so click
counts are read from the code path — same honest limit Ph3/4 noted). **Owned gates ④⑤⑥⑦ all PASS:** **④** carry
rate → two homes — `carryRate()`/`carryRateParts()` (finance.jsx:161-173) surfaced in Finance AND the Sourcing
"Inventory carry rate 24.0%/yr" card, reachable in ≤2 navs via the registry ⛓Lineage/Finance jump; **⑤** single
canonical `config.serviceLevel` (no live `serviceLevelOverride`; migration store.jsx:177-188), `effServiceLevel()`
reads it, **live policy solve α 0.80→0.99: z 0.842→2.326, safety-stock 38.1→105.2** (plan provably moves);
**⑥** `cfg.prod`/`cfg.profit` carve-outs precise (node harness on the REAL CONFIG_TOKEN/SOLVE_DEPS maps: prod-knob→
production/aggregate/linecap NOT procurement/profitmix; pmBudget→profitmix only), broad `config` over-stales
conservatively and the UI says so (setup.jsx:421/425); **⑦** TPA-3215 {RM-STL42,CN-SEAL9,CN-BLT04} vs TPA-9904
{RM-BRG18,CN-LUB02} = **zero part overlap**, `editPartQty` read back by BOTH `bomForSku` and montecarlo `skuParts`.
**C6→5** (wide-blast `M.bom`→map landed additively — `partsOf`/`bomParts`/export-import/master readers all intact,
`bomOverrides` in the round-trip, 0 `.py` touched), **C7→5** (gates pass on the running app, cascade re-derived not
trusted) ⇒ weighted **94** (E′ row off the 88 paper ceiling). **Smoke:** procurement Optimal (both α), `/api/solve/
sequence` **exact 6-SKU Hamiltonian total 5.1 hrs** (not 4), profitmix Optimal — **zero numeric drift structurally
guaranteed** (no solver .py changed; profitmix payload doesn't read bomForSku/skuParts). **Scenario S4** (carry-rate /
service-level across pages) reproducible by clicking (Setup registry → Finance/Sourcing jump), solve driven by API
only because no headless click. **One in-scope ④ nicety closed (2026-06-05):** added a *literal* "Inventory carry
rate" registry row (`setup.jsx:408`, `prov:'derived'`, FED-BY WACC+spread, FEEDS inventory family + Capital) so ④'s
"two homes" is one explicit row, not inferred from the holding-spread component — verified in served bytes + parse OK.

**Next:** Phase 3 (IA re-segment — one nav vocab; sub-tab rule >6 sections; Sourcing Run/Design; Finance
default→Capital) then Phase 4 (Scope worklist + badges) on your go.

### §5.8 Phase 3 implementation log — **BUILT 2026-06-05** (IA re-segment)

Frontend-only (no `.py` touched). Owns gates **⑧ ⑨ ⑩**.
1. **One nav vocabulary (R4 / gate ⑩).** The pipeline ribbon carried a SECOND taxonomy
   (DEMAND/PROCURE/PRODUCE/CAPITAL/RISK) that competed with the rail's page names. `chrome.jsx` demotes it to a
   **freshness strip**: header "SOLVE FRESHNESS · N/6 FRESH"; each cell's bold label is now the RAIL page name,
   derived via `_ribbonPage(go)=M.stages.find(id===go).name` (the ribbon and rail can't drift to two names), with
   the solve phase/method kept as a thin sub. Two cells legitimately open **Plan** (S&OP aggregate + capital
   dual) — honest, both surface there. Active page's cell is highlighted (`active` threaded from `Chrome`).
2. **Sourcing → Run / Design (gate ⑧) + sub-tab rule (R6).** Sourcing was a ~14-section single scroll with the
   **PO Release Plan buried at step 11**. Split into two `SubTabNav` tabs: **Run** (default) = the selected
   item's buy plan you read weekly — Solver Params(1) · **PO Release & Shortages(2, promoted from 11)** · Per-Part
   MRP(3) · Stepwise Freight(4) · Exceptions(5); **Design** = the parts-master governance + inventory science you
   tune quarterly — External signals(1) · Incoterms(2) · Sourcing Terms(3) · Landed(4) · Policy(5) · Rolling(6) ·
   MEIO(7) · Network Pooling(8) · Newsvendor(9) · Postpone(10). Two positional cross-refs reworded ("Release plan
   below"→"in the Run tab"; "solver-parameters card above"→"Run tab · Solver Parameters").
3. **Production renumber per tab (gate ⑨).** The Schedule sub-tab scrambled 0→3→4→5; every sub-tab now numbers
   1..n locally (arch 1 · cycle 1 · sched 1·2·3·4 · change 1).
4. **Finance leads with Capital.** `financeSubtabs` reordered so the **solved Capital** tab is first (a/b/c…),
   `StageFinance` defaults to `'capital'` — a CFO no longer lands on the illustrative-seed Cash & WC tab.
5. **Reference surfaced in the rail.** New `M.stages` entry under a **LEARN** band (was masthead-"Learn"-only,
   undiscoverable); already wired in `main.jsx` registry, so it renders.

### §5.9 Phase 4 implementation log — **BUILT 2026-06-05** (Scope system)

Frontend-only. Owns gates **⑪ ⑫**.
1. **Portfolio worklist (gate ⑪).** New `PortfolioWorklist` rendered inside `ItemSelector` (so it's persistent on
   every item-scoped page: Products/Demand/Network/Production/Sourcing). "N/6 committed" + a per-SKU pill row +
   "next: TPA-XXXX →". **"Committed" reuses the REAL definition** — a SKU with a live committed-demand series
   (`appStore.demand[sku]` non-empty), the same test Demand's All-SKU Consensus uses (NOT a fabricated flag). It
   reads live store state, so committing a SKU climbs the count in place and the strip never resets/disappears.
   "next →" selects the SKU + opens Demand to run its forecast (`onNav` threaded into `ItemSelector` at all 5
   call sites).
2. **Per-section scope badge (gate ⑫).** New `ScopeBadge` + a `scope` prop on `StageSection` → a small
   `◧ THIS ITEM` / `▦ PORTFOLIO` chip. Applied to **every section on all 5 item-scoped pages** with an HONEST
   item/global split derived from the code, not the label: e.g. Products `Define`/`MTO` = portfolio, yield/BOM/
   costs/policy = item; Sourcing buy-plan outputs (procurement is solved for the selected FG) = item, parts-master
   governance + Network pooling = portfolio; Production MILP is multi-SKU → portfolio, Cycle & Line = item;
   Network's per-item↔global "flip" (R5) is now LABELED per section (Flow/On-Hand = item; Nodes/Suppliers/
   Contracts = portfolio). Selector-less pages (Setup/Plan/Logistics/Finance/Console/Scenarios/Home/Reference)
   have no item scope and are unambiguously portfolio, so ⑫ is scoped to the pages where the R5 ambiguity exists.
3. **Products ScopeBanner contradiction fixed (R5).** The banner claimed "every card below … is for THIS product"
   while sitting above the all-SKU Catalog (and the all-SKU MTO order book). Reworded to "yield, BOM, costs &
   policy are for THIS product — the ▦ Catalog and ▦ Make-to-Order cards are portfolio-wide (each section is
   scope-tagged)", and those two sections carry `scope="global"`. The Sourcing banner likewise now states
   "procurement is solved for THIS item … the parts master is portfolio-wide — every section is scope-tagged."

**Static verification:** 18/18 jsx parse · app.py+solvers compile · live Flask all-200 with every Ph3/Ph4 symbol
present in served bytes · procurement endpoint **Optimal** (Run-tab solve unchanged — only its render home moved).

**§6.6 post-build verification (independent general-purpose agent, the file's §6.6 spin-up command, running app) —
VERDICT: VERIFIED-DONE.** Ran the OWNED gates against the live served bytes (not ad-hoc scoring): **⑧** PASS — PO
Release Plan now at Sourcing→Run→step 2 (default tab), 0 extra clicks (was step 11); **⑨** PASS — no scramble in
any sub-tab (Production 1·1·1234·1; Sourcing Run 1–5, Design 1–10); **⑩** PASS — ribbon labels = rail page names
via `_ribbonPage`, Reference a rail stage; **⑪** PASS — `PortfolioWorklist` committed-ness = live
`demand[sku]` non-empty (the SAME real test Demand uses, not hardcoded), persistent in `ItemSelector`; **⑫** PASS
— every visible `<StageSection>` on all 5 item-scoped pages scope-tagged, assignments spot-checked HONEST vs code
(Products Define/MTO global; Sourcing buy-plan item / master+pooling global; Production MPS global). **C7 3→5**
(gates validated on the running app) and **C6 4→5** (frontend-only — `git status` 0 `.py` changed,
`procurementPayload` not in any diff hunk; revert-safe) earned with evidence → re-graded **~95+ (98 on the row)**.
**§3.2 guardrails all PASS** (R3: `ScopeBadge` pure label, both `SubTabNav` + worklist controls wired; R2: ribbon
`done` only on real `solveResults`, worklist "committed" only on a live series; C8: useSolve/markStale/SeedFence/
Provenance/stageGate intact). Scenario 4 (commodity-spike → re-plan procurement → PO release) reproducible by
CLICKING (the split *improved* it). Procurement smoke **Optimal**, byte-stable. **3 non-blocking gaps; 2 closed
2026-06-05:** (1) a scope-less `<StageSection>` in the UNREACHABLE non-`bare` branch of `SrcExternalSignals.Wrap`
(dead code, never rendered) → gave it `step="1" scope="global"` so the ⑫ grep is clean (now 17/17 sourcing
sections scoped); (2) masthead button "❓ Learn" vs the rail stage "Reference" (two words, one place) → relabeled
"❓ Reference" for strict ⑩ vocabulary unity. (3, NOT closed — pre-existing, not Ph3/Ph4) the agent noted §5.1's
E′ scorecard ROW sums to 92 but is labeled 88 (§6.1 "12 lost points"); left as frozen evidence — graded against
the doc's stated *mechanism* (C6→5/C7→5 by evidence), which is unambiguous regardless of the baseline label.

---

## §6 — Per-tab remediation (the NEXT process, after the E′ structural phases)

*Recorded before compaction so the per-tab pass + its review staffing survive.*

### §6.0 Coverage cross-check (does this cover ALL issues across the source docs?)
- **`FIRST_TIME_USER_NAVIGATION_AUDIT.md` — fully mapped.** Part 0 nav→R4; Part 1 per-page→R1–R9 + §6.4;
  Part 2 inert controls→R3; Part 3 IA→R4/R6; Part 4 merges→R8; Part 5 contradictions→R1/R2/R7; Part 8
  structure→R1; Part 9 onboarding→R8, changeover-4/6→R7, **accessibility→was uncovered → now R10**.
- **`USER_JOURNEY_AND_DESIGN_CRITIQUE.md` — fully mapped.** C1–C14 all resolve to R1–R9; its "still didn't
  audit: accessibility" is the same gap → R10.
- **`SCENARIOS_VERIFICATION.md` — a verification/modeling doc, not an issue inventory.** Part A proves the
  recent wiring correct (all ✓); Part B models 5 end-to-end problems. It introduces **no net-new issue
  category**, but contributes: (a) the **opening-inventory units** clarity item (Plan step-0 number is in
  *labor-weighted aggregate units* ≈ physical, separate from Network on-hand → an R1 instance; local Plan
  fix added to §6.4); (b) it **corroborates R1** — its scenarios literally walk carry-rate-across-pages
  (S4), the line-shadow→Finance hand-off (S2), the budget-shadow→raise-capital (S5); (c) its 5 scenarios
  are **ready-made end-to-end think-aloud scripts** for the §6.6 verification step. One honest meta-flag it
  raises: those scenarios were proven via **direct API payloads, not by driving the seed-data UI** — so
  "can a user reproduce them by clicking, not curling?" becomes a §6.6 acceptance test.

**Verdict:** with R10 added and the opening-inventory units item slotted, every issue across all three docs
is now covered by a root (R1–R10) and an owning phase (E′) or the per-tab backlog (§6.4).

### §6.1 Why E′ scored 88, not 100 (and why 100 would be wrong)
The 12 lost points sit on two criteria that are **deliberately capped at the design stage**:
- **C7 measurability = 3/5** — the 12 gates ①–⑫ are *defined* but not *validated*. C7→5 is earned only by
  running the think-aloud and watching the gates pass; asserting it now = faking confidence.
- **C6 cost/risk = 4/5** — a real refactor with a wide-blast item (the `M.bom` map) carries inherent risk;
  5/5 would claim zero risk, which is false.

A rubric that can hit 100 on paper has stopped discriminating (we gamed it, or deleted the honest
criteria). **88 = "fully specified, not yet validated" is the correct ceiling for a design doc.** Score
rises to ~95+ **by evidence** (C7→5 when Phase-1 gates pass with users; C6→5 when the BOM conversion lands
clean) — not by rewriting. Pursuing 100 pre-implementation would violate the same no-faking discipline we
audit the app for.

### §6.2 Reviewer staffing — structural vs per-tab
- **Structural pass (done):** a sharp generalist + code access. The roots were UI/state *mechanics*, so no
  deep domain knowledge was required.
- **Per-tab pass (next):** needs **two lenses**, because per-tab fixes are domain *semantics*, not just
  mechanics:
  - **Domain reviewer** — supply-chain / S&OP / inventory-optimization (and finance for the Finance tab).
    Gates: is the fix *semantically correct* and would a *real planner/CFO/plant-lead trust and act on it
    correctly*? (e.g. leaderboard-before-forecast workflow; MEIO decoupling story; carry-rate
    decomposition; EVA-destroyer logic; level-vs-chase framing.)
  - **Design reviewer** — the persona used for the structural pass. Gates: IA, flow, visual clarity,
    first-time comprehension, provenance/no-faking.
  - **Both must pass.** Use **two specialized agents, not one dual-persona** (a combined persona averages
    and goes soft on the weaker lens). Domain reviewer is **mandatory** for the domain-heavy tabs
    (Demand, Plan, Sourcing, Finance) and **light/optional** for chrome-y ones (Home, Setup-identity,
    Reference).

### §6.3 Per-tab rubric delta (extend §3.1 for the per-tab pass)
Keep C3 (trust), C4 (comprehension), C5 (arch fit), C6 (cost), C7 (measurability), C8 (protect strengths).
**Down-weight C2** (cross-section generality is largely the structural pass's job). **Add two domain
criteria (×3 each):**
- **C9 · Domain correctness** — the number/flow means what it says; a professional would not be misled.
- **C10 · Workflow fit** — matches how that role actually works (the planner's day, the CFO's question).
Per-tab done-test: every *local* (non-structural) issue for the tab is addressed; **C9 and C10 ≥ 4**;
no §3.2 guardrail re-created; the design reviewer AND the domain reviewer both sign off.

### §6.4 Per-tab residual backlog (LOCAL issues only — what E′ does *not* already fix)
E′ fixes the cross-cutting roots; the per-tab pass handles what's left *after* it. Don't re-do E′ work.

| Tab | Local fixes the per-tab pass owns (post-E′) | Already covered by E′ (skip) |
|---|---|---|
| Home | margin-drill over-promise (drill all 8 KPIs or none); 2+1 grid asymmetry | inert KPI tiles → R3/Ph1; "spine 6/13" relabel → Ph1 |
| Setup | ★-template placement (step 0?); onboarding⇄Profile merge; z=1.645 gloss | Frozen/Slushy inert → Ph1; service-level dedup → Ph2 |
| Products | Define-grid editable/read-only split; target-vs-realized margin clarity | ScopeBanner contradiction → Ph4; shared BOM → R7/Ph2 |
| Demand | leaderboard↔forecast ordering; history-vs-forecast import distinction; cold-start polish | manual-grid inert → Ph1; portfolio worklist → R5/Ph4 |
| Plan | CV→"stability/swing" gloss; hands-on% education; "did I need S&OP?" transparency; **label opening-FG-inventory as "aggregate (labor-weighted) units ≈ physical" + reconcile/cross-link with Network on-hand** (from SCENARIOS_VERIFICATION A1) | Gap card seed-as-derived → R2/Ph1; opening-inv two-concepts → R1/Ph2 |
| *(cross-cutting)* | **R10 accessibility/responsive:** type scale ≥ readable min; text-twin for every color-coded state; focus rings; reflow (not just overflow-x) on key tables — applied through the Ph1 Field/Value contract, then a dedicated running-app a11y pass | — |
| Production | step renumber per tab; "moved here" churn note; OEE simple/detailed default | cycle inert inputs → Ph1; step-scramble structural → Ph3 |
| Sourcing | synthetic-MRP-before-real ordering; incoterms placement; section grouping detail | Run/Design split → Ph3; shared BOM → R7/Ph2; FX editor → Ph2 |
| Logistics | pre-solve "planned" labeling; CoG hardcoded "~18% km cut" empty-state | (mostly local) |
| Finance | Buy-vs-Lease seed×2 (one home + flag/solve); Board-pack wire/remove; Cash seed cards behind banner | default→Capital → Ph3; FX editor → Ph2 |
| Console | dead run-control band (wire/remove); result-mirror dedup (link to stages); "live solve 6/16" honesty | (band ① dead control → R3/Ph1) |
| Scenarios | Cost seed tab (fence/wire); two-what-ifs disambiguation | (illustrative-fencing already good) |
| Reference | discoverability (rail vs Learn-only); SAP "Overview" inert boxes | nav vocab → Ph3 |

### §6.5 Agent spin-up commands (ready to paste — per tab, after E′)
Run per tab: design reviewer always; domain reviewer for domain-heavy tabs. Both verdicts must pass §6.3.

**Domain reviewer (supply-chain / ops / finance):**
```
subagent_type: general-purpose
prompt:
You are a 20-year supply-chain practitioner — S&OP, MRP/MILP procurement, multi-echelon inventory
optimization, and (for the Finance tab) corporate finance/WACC/EVA. You are reviewing the proposed
per-tab fixes for the <TAB> tab of app_v2 (a supply-chain planning product). Read app_v2/<tab>.jsx,
app_v2/DESIGN_REMEDIATION.md §6.4 (this tab's local backlog), and the two audit docs. Do NOT judge
visual design — judge DOMAIN CORRECTNESS and WORKFLOW FIT:
 1) Is every number/flow/label semantically correct — would it mislead a professional? (cite the
    component + the solver it reads, e.g. <solver>.py, and whether the framing matches the math.)
 2) Would a real <planner/CFO/plant-lead> trust this and act CORRECTLY on it in their actual workflow?
 3) Is the proposed fix the right one for the domain, or does it fix the UI while leaving a domain lie?
Score C9 (domain correctness) and C10 (workflow fit) 0–5 with justification. List any domain error the
fix misses or introduces. Verdict: PASS (both ≥4) or NOT — with the specific domain gaps to close.
Verify claims against the real code/solvers; do not rubber-stamp.
```

**Design reviewer (per-tab — reuse the structural persona):**
```
subagent_type: general-purpose
prompt:
You are an adversarial product-design reviewer. Review the proposed per-tab fixes for the <TAB> tab of
app_v2 against the rubric in DESIGN_REMEDIATION.md §3.1 + §6.3 (C3 trust, C4 comprehension, C5 arch fit,
C6 cost, C7 measurability, C8 protect-strengths; C2 down-weighted). Read app_v2/<tab>.jsx, §6.4 (this
tab's local backlog), and the two audit docs. For each local fix: does it close the issue without
re-creating R2 (seed-as-real) or R3 (inert control)? Score each criterion 0–5 with justification; run
the §3.2 guardrails; rule on the §6.3 per-tab done-test. Verdict: DONE / NOT DONE + an actionable gap
ledger. Constraints: @babel/standalone no-build, one shared global scope, single dataset. Verify
against code; high bar; do not pass to be agreeable.
```

**Gate:** a tab's per-tab pass is DONE only when the design reviewer rules DONE **and** (for domain-heavy
tabs) the domain reviewer rules PASS. Disagreement → iterate the fix, re-review, until both pass.

### §6.6 Post-implementation verification & grading (answers "C7 must be verified & graded after build")
The design/domain reviews above gate the **plan** (pre-build). They are necessary but **not sufficient** —
two criteria are *earned by evidence only after implementation*: **C7 measurability** (the 12 gates ①–⑫
must actually pass on the running app) and **C6 cost/risk** (the BOM conversion must land without
regression). So every phase and every per-tab pass has a **third, post-build gate** before it's truly DONE:

1. **Run the gates on the running app.** Drive the built UI and check each acceptance gate that the phase
   owns (e.g. Ph1: gates ①②③; Ph2: ④⑤⑥⑦; Ph3: ⑧⑨⑩; Ph4: ⑪⑫; per-tab: C9/C10 observations). Record
   pass/fail with the observed value vs the threshold.
2. **Re-grade C6 + C7 with evidence** and update the §4.1 scorecard — the score moves off "88 on paper"
   only here (C7→5 when gates pass; C6→5 when the conversion lands clean). This is the *graded-after-build*
   step you asked about; it is now an explicit part of the process, not an afterthought.
3. **Run the 5 SCENARIOS_VERIFICATION scripts as end-to-end think-alouds — *through the UI, not via curl*.**
   Each scenario (CPG S&OP / automotive mix+capacity / pharma buffer / electronics lot-sizing / D2C cash)
   becomes a task: can a user reproduce the decision by *clicking*? This directly tests the meta-flag from
   §6.0 (the scenarios were originally proven by API payload, not by driving the seed-data UI).
4. **Regression smoke** on the solvers the change touches (esp. procurement/policy/MEIO after the BOM map),
   so no silent numeric drift hides behind a clean-looking UI.

A phase/tab is **VERIFIED-DONE** only when its gates pass on the running app, C6/C7 are re-graded with
evidence, the relevant scenario script is reproducible through the UI, and the smoke is clean.

**Verification agent (spin-up command — run after each phase/tab is built):**
```
subagent_type: general-purpose   (or invoke the /verify or /run skill to drive the live app)
prompt:
You are a verification & QA agent. Phase/tab <X> of app_v2 has just been implemented. Start the Flask
app (nohup python app.py > /tmp/es_server.log 2>&1 & echo $! > /tmp/es_server.pid; sleep 6 — kill by
PID, NEVER pkill -f app.py, the pattern self-matches the launching shell). Then verify against
DESIGN_REMEDIATION.md:
 1) Run each acceptance gate this phase/tab owns (gates ①–⑫ / C9–C10) on the RUNNING app; record
    observed value vs threshold, pass/fail.
 2) Re-grade C6 (cost/risk: did the change land without regression?) and C7 (measurability: did the
    gates pass?) 0–5 WITH the evidence; report the updated weighted score.
 3) Reproduce the relevant SCENARIOS_VERIFICATION.md scenario END-TO-END THROUGH THE UI (not curl) —
    can a user reach the decision by clicking? Note any step that only works via API.
 4) Solver regression smoke on the touched endpoints (esp. procurement/policy/meio after the BOM map):
    POST a known payload, confirm Optimal + no numeric drift vs the pre-change result.
Verdict: VERIFIED-DONE or NOT, with the specific failing gates / regressions to fix. Do not pass to be
agreeable; a clean-looking UI over drifted numbers is a fail.
```

## §6.7 — Per-tab implementation log (the per-tab pass, after E′)

Ran **domain-heavy 4, one tab at a time** (Demand → Plan → Sourcing → Finance), each: §6.5 design **and** domain
reviewer audit → §6.4 local-backlog fixes → §6.6 verification (design reviewer DONE + domain reviewer PASS C9/C10≥4
+ running-app smoke). Frontend-only; backend `.py` untouched. NOTHING committed.

### §6.7.1 Demand tab — **BUILT + VERIFIED-DONE (2026-06-05)**

Both reviewers first ruled **NOT DONE** (domain **C9 3 / C10 2**, design **C4 3** with a borderline-R2). Nine local gaps
(D-1…D-9) — the three §6.4 seeds confirmed + six more found. Fixes (demand.jsx unless noted):
1. **D-1 · silent auto-commit decoupled (the load-bearing one).** Merely VIEWING a SKU ran the mount-effect forecast
   and `setItemDemand` → it counted as "committed" with no human action. New store helpers `isDemandCommitted` /
   `demandCommitEvent` (`store.jsx`) define COMMITTED = an explicit commit-class event (`forecast_commit` / override /
   replan / lifecycle / npi_likemodel), NOT "demand[sku] non-empty". `DemCommit` now has three states (not-run /
   **proposed**-amber / **committed**) + an explicit "✓ Commit as consensus" button (logs `forecast_commit`); the
   consensus count + "Set by" column key on the event. `PortfolioWorklist` (`lib.jsx`) `isCommitted` now reads the
   event log. The auto-forecast still writes the WORKING series so downstream MILPs always have a number — only the
   commit LABEL/count changed (verified the feed is intact + the worklist stays completable).
2. **D-2 · model quality before override + bridge.** `DemForecast` shows the winner's holdout MAPE + IN/OUT-OF-CONTROL
   inline and a "why this model? ↓ leaderboard" scroll-link to a new `#demand-leaderboard` anchor.
3. **D-3 · import targets collapsed to the wired truth.** Killed the inert `<Btn>⤓ Choose file</Btn>` drop-zone (R3);
   history-mode → scroll to the real CSV importer (step 1b), forecast-mode → states it BYPASSES the competition + navs
   to Setup (the real flag home).
4. **D-4 · cold-start honesty.** DATA-TIER note depth-aware (ML/DL gated <24 pts) + tags SEED (illustrative) vs imported
   history; NPI commit carries `npi_likemodel` provenance into "Set by".
5. **D-5** PI label → σ = out-of-sample holdout error (was "σ_resid"). **D-6** reconciliation flags single-SKU runs +
   "does not re-incorporate overrides". **D-7** promo-blind-winner callout (empty attribution ≠ "no promo effect").
   **D-8** segmentation surfaces the engine's LIVE intermittence (`prod.intermittence.label/adi/cv2`) for the selected
   item, flags disagreement with the seed XYZ, badges the 9-box "seed class". **D-9** MAPE target labeled a seed, not an
   SLA. Ride-alongs: CV/(s,S) gloss; month-aware `futureLabel` stepping.

**§6.6 re-review → domain PASS (C9 4 / C10 4), design DONE.** The design lens **caught a real bug I introduced**:
`<Provenance kind="seed"/>` was an undefined kind that fell back to `_PROV.solved` → rendered pre-run seed history with a
green SOLVED chip (a FRESH R2 auto-fail). Fixed by adding a real **`seed` kind** to the `_PROV` trust atom (`lib.jsx`:686,
muted `◇ SEED`, additive — no caller regresses); design re-verified **DONE** (R2 PASS, C3 2→5). This is the two-lens gate
working as designed — the structural pass would not have caught a silent auto-commit, and the domain pass would not have
caught the chip mislabel. **CSV upload path verified end-to-end** (the path G3 now points users to): ran the VERBATIM
`parseHistoryCsv`+`bucketHistory` against 4 real on-disk files — dated-monthly (same-month rows summed 120+30=150),
value-only (file order), tab-delimited, semicolon+thousands-comma (`1,200`→1200) — all parsed correctly; the CSV-derived
24-month series fed to live `/api/forecast` returned winner **hybrid @ 4.13% MAPE**, smooth class, a 12-mo forecast that
continues the YoY growth + Dec seasonal peak. **CSV thousands-comma mis-split FIXED** (user flagged "should we fix the
misspent one?"): `parseHistoryCsv` (`store.jsx`) is now **RFC-4180 quote-aware** (`_split` respects `"1,200"` so Excel/Sheets
exports parse correctly) + **date-disambiguated** (a real date in column 0 ⇒ the remainder is the value, so an UNQUOTED
`2024-01-01,1,200` → 1200 not 200) + tightened `_date` (a bare int is never misread as a date). Re-verified vs 8 real
on-disk files: 4 original formats UNCHANGED (no regression) + comma-dated-unquoted-thousands 200→**1200** + Excel-quoted →
1200 + value-only-quoted → 1200; the only RESIDUAL is an unquoted value-ONLY grouped number (`1,200` alone, genuinely
ambiguous) — surfaced in the importer hint ("quote it or drop the thousands comma").

**Multi-SKU / unified ingestion ADDED (user-chosen "full long-format" + then "is 3 columns how most software works?").** Real ERP/BI exports
arrive UNIFIED in two shapes, both now auto-detected by `parseMultiSkuCsv` (`store.jsx`) and written per-SKU by `importManyHistory` →
`histImports[each known sku]` in ONE paste, with a per-SKU known/unknown preview + "Import N products" in `DemImport` (`demand.jsx`): **(1) WIDE / pivot**
(sku down the side, dates across the top — how planners live in Excel/IBP); **(2) LONG / tidy** (`sku,date,value`) where EXTRA dimension columns
(plant/channel/customer) are ignored and multiple rows per sku+date SUM to total demand (correct aggregation), and the value column prefers a
QUANTITY name (units/qty/demand) over revenue/amount. Unknown codes are matched against the product master and SKIPPED with a visible warning (not
silently dropped); a plain ≤2-col date,value/value-only file does NOT trip multi-detection (single-series path still owns it). Verified VERBATIM on real
on-disk files: wide pivot → correct per-SKU series; long+extra-dims → picks units-not-revenue, sums dup sku+month (80+40=120), skips unknown ZZZ-0000;
single-series falls back. Verify: 18/18 jsx parse + py compile + live 200s + new symbols in served bytes. Touched: demand.jsx (commit/ordering/import/
cold-start/PI/reconciliation/segmentation/promo + multi-SKU import UI), store.jsx (commit helpers + CSV parser + `parseMultiSkuCsv`/`importManyHistory`),
lib.jsx (worklist + `_PROV.seed`).

### §6.7.2 Plan tab — **BUILT + simple-tested (2026-06-05)**

Both reviewers first ruled **NOT DONE/NOT PASS** (domain **C9 3 / C10 3**, design **C3 2** with a real PlanGap R2 BLOCKER / **C4 3**). Nine local gaps **PL-G1…PL-G9** (verified every claim against code before fixing). Fixes (plan.jsx unless noted):
1. **PL-G1 (BLOCKER) PlanGap seed-as-derived → fenced.** The S&OP gap card showed `M.sop` SEED numbers with a green `kind="derived"` chip + a fabricated `asOf` timestamp (live R2). Now `kind="seed"` + a `SeedFence` ("illustrative until the consensus reconcile runs" → Scenarios). The §6.4 row wrongly called this "already fixed by E′" — design reviewer proved it was never closed; fixed here.
2. **PL-G2 FAMILIES banner bug.** Counted `_finP.map(p=>p.family)` which is ALWAYS undefined on `M.products` (no `.family`), so it always read 0 families. Now counts via `M.items` (carries `_FAMILY`) ⇒ **6 families**; relabeled `VIEWING ▸ PORTFOLIO AGGREGATE`, copy clarifies it's ONE pooled plan, not per-family.
3. **PL-G3+G4 strategy gloss.** CV MiniBar rescaled `v*4`→`v/0.10` (full bar = CV 0.10, pivot 0.05 mid-bar); caption states the rule (wf-CV<0.05 ⇒ LEVEL, ≥0.05 ⇒ CHASE) instead of a hardcoded "⇒level"; added a **"DID I NEED S&OP?"** callout (flat/seasonal/chase from `res.workforce_cv`/`inventory_cv`) + a CV=σ÷μ gloss.
4. **PL-G5′ opening-FG-inventory ⇄ Network (the one the user pushed on).** Was 0 (greenfield) while Network holds **1,260 u** → plan told you to re-build stock you own. Now **auto-reconciles from Network FG on-hand** (`networkOpeningInv`/`planOpeningInv`, store.jsx; override wins; loop path too). The solver consumes the **labor-weighted** equivalent (**1,124 u**, the unit aggregate.py InvBal carries — Σ qty·weight), but the UI **headlines the physical 1,260** ("you hold 1,260") and frames 1,124 as the worker-time yardstick, **explicitly "a conversion, NOT a reduction"** (user was alarmed it "undermined" on-hand → first reverted to physical-feed, then restored labor-weighted-feed once the concept landed; final = labor-weighted feed + physical headline). Replaces the earlier "nag-note" with a real auto-default.
5. **PL-G6 hands-on% education** (worked example: 6.0-min cycle @30% = 1.8 worker-min vs manual 3.0-min = 3.0). **PL-G7 capacity units** note (columns are labor-weighted ≈ physical). **PL-G8** routed the 5 hardcoded `PLAN_PARAMS` (init_workforce/backorder cost/max_ot/min_wf + `allow_backorder` via new `planBool`) to the editable governed surface + exposed Allow-backorder checkbox & Max-overtime. **PL-G9** PlanWorkforce period-0 uses governed init_workforce; PlanDisagg `kind="seed"` when unsolved.

**Verification — SIMPLE test (user relaxed the loop, see note below):** 18/18 jsx parse; server GET / → 200, served bytes carry all new symbols; `/api/solve/aggregate` Optimal; **seasonal** wf_cv 0.0 / inv_cv 0.98 → level+prebuild; **flat** wf_cv 0 / inv_cv 0 (S&OP-moot branch); `allow_backorder` TRUE shorts 12,000u vs FALSE → Infeasible (lever real); **opening-inv end-to-end** init_inv 0 → P0 reg 541.4 vs init_inv 1,124 → P0 reg 385.3 (consumes held stock; cost ₹4.58M→₹3.47M). Labor-weight check on real seeds: phys 1,260 → weighted 1,124 (−10.8%, because on-hand skews to labor-light TPA-3215 w=0.733).

### §6.7.3 Sourcing tab — **BUILT + simple-tested (2026-06-05)**

§6.5 dual-lens review (spend-limit recovered; both agents ran). **Domain NOT PASS (C9 3 / C10 4); design NOT DONE** (two §3.2 guardrails failed pre-solve). Consolidated 5-item ledger, all fixed (sourcing.jsx unless noted):
1. **SR-1 (CRITICAL, domain) — buy plan was exploding the wrong BOM.** `partsWithSourcing` mapped the shared master `M.bom` (all 5 parts at master qty) for the SELECTED single FG → procurement/policy/MRP/freight/exceptions/postpone planned & costed parts the FG never uses (TPA-4471 was buying the Grade-10.9 bolt). Now takes `sku`, overrides each part's `qty_per` from `bomForSku(sku)` (the real per-FG bill, per-SKU qty), and sets **qty_per 0 for parts not in the bill** — index-safe (still iterates the full master in `M.bom` order so every card's `proc.result.materials[pi] ↔ M.bom[pi]` alignment holds; procurement.py emits a materials entry per part unconditionally). Reverses the prior "left on master ON PURPOSE" call (the payload passes ONE FG's demand, not a portfolio aggregate, so all-parts was a genuine MRP error). ScopeBanner reworded ("the parts it actually consumes").
2. **SR-2/3/4 (R2/R3 guardrails, design) — pre-solve seed honesty.** Added `SeedFence` to (a) the **synthetic MRP grid** (persistent — it's a teaching artifact, not just a post-solve footnote), (b) the **PO Release Plan** pre-solve `M.poRegister` rows (+ `kind="seed"` chip, badge "illustrative"), (c) the **Shortage Forecast** pre-solve hardcoded rows (+ seed chip, badge fixed from a fake "2 risks"). **Removed the inert `⚡ Expedite both` button** (no handler → R3).
3. **SR-5 (medium, domain) — Landed Cost FX disconnect.** Card used a frozen `LANDED_INPUTS.fx=84.20` while `SrcExternalSignals` one card up reads governed `config.fxRates.USD` — a contradiction. Now reads the governed `config.fxRates.USD` (fallback 84.2) + an honest note that FX is governed while FOB/freight/duties stay a worked example (badge kept).

**Verification — SIMPLE test:** 3/3 jsx parse; inert button grep → 0; 3 SeedFences present; **SR-1 solver smoke (the headline fix)** via `/api/solve/procurement` on TPA-4471 — OLD (master, CN-BLT04 qty_per 6.0) ordered **14,807 bolts**; NEW (per-FG, CN-BLT04 qty_per 0) ordered **0**, and RM-BRG18 moved to its real per-unit qty (1,500 → 2,468 @ qty 1.0 vs master 0.32); all 5 materials still returned in order (alignment intact). Data confirmed `M.skuBom['TPA-4471']` excludes CN-BLT04.

> **METHODOLOGY CHANGE (user-enforced, 2026-06-05):** the heavy §6.6 **second full re-review is DROPPED** — "we can't do a full review fix then do a full review again." Per-tab loop is now **§6.5 first review (still mandated for domain-heavy tabs) → fix → SIMPLE test** (parse + served-bytes + a solver smoke on the touched endpoint), not a second two-agent pass. Plan + Sourcing above followed this.

### §6.7.4 Finance tab — **BUILT + simple-tested (2026-06-05)**

§6.5 dual-lens review (both agents ran). **Domain = PASS (C9 4 / C10 4)** but with a ledger beyond §6.4; **Design = NOT DONE** (R2 blocker: EVM/CCC `derived` chips over seed + the Buy-vs-Lease **double render**). Consolidated 8-item ledger, all fixed (finance.jsx unless noted):
1. **FIN-1 (BLOCKER + domain lie) — Buy-vs-Lease was hardcoded "LEASE wins by ₹5L" rendered TWICE** (FinValue + FinInvest). De-duplicated (single home = **FinInvest**) **and** rewired `FinBVL` into a **real two-leg NPV-of-costs solve**: BUY = −upfront − maint(1−t) + dep·t (+ salvage at end); LEASE = −rental(1−t); both discounted via `/api/calc/npv` at the live blended hurdle; lower PV wins. Inputs are an editable worked-example asset (`config.bvl{price,life,maint,lease,salvage}`); the math is live — `PreviewTag`/hardcoded verdict removed. (Two `useSolve('/api/calc/npv')` in one component is safe — per-call local state, no `solveKey` → no cache collision.)
2. **FIN-2 (R2 BLOCKER) — EVM + CCC wore `kind="derived"` chips + fabricated `asOf`/`run` over data that is a flat seed (`M.evm`) / hardcoded JSX literals (DIO/DSO/DPO 52/28/39).** `derived` = "computed from other fields"; these are read verbatim. Changed both to `kind="seed"`, dropped the timestamps.
3. **FIN-3 (MATERIAL domain) — NPV tax-shield double-taxed the seed.** `M.npv.cf` are ALREADY after-tax free cash flows; the toggle applied `cf·(1−t) + dep·t`, re-taxing them (NPV ₹101.7L→₹61.5L, IRR 26.9%→21.1%) and the soWhat ("off drops NPV") was backwards. Fixed: shield now **ADDS only `dep·t`** to the after-tax CF (shield ON ⇒ higher NPV, the saving is real cash). Relabeled badge ("after-tax + dep shield"), checkbox, formula, soWhat; added a clarifying comment in data.jsx that `cf` is after-tax.
4. **FIN-4 (moderate domain) — two unreconciled costs of equity on one subtab.** Hurdle card = source-weighted Ke 13.92%→hurdle 11.15%; Min-WACC structure card = CAPM Ke (rf+βᵤ·ERP)≈12.5%→min-WACC 12.36%, sitting inches apart with no bridge. Added a note: this curve prices Ke off the market CAPM to trace leverage; gate projects on the source-weighted hurdle; use the curve only for target debt ratio; the gap = idiosyncratic-vs-market equity premium.
5. **FIN-5 (moderate domain) — FinFX VaR card was dimensionally incoherent** ("If ₹→86.5 +₹1.8L cost" on a €12K exposure). Replaced with coherent figures (exposure ₹10.8L @ ₹90/€; +₹5/€ adverse move → +₹0.6L), still SeedFenced illustrative.
6. **FIN-6 (minor domain) — Cash seed cards asserted hard specifics** (43B(h) risk tag, EVM EAC). Added `kind="seed"` chips to Working Capital / Payment Ledger / Budget cards and an inline "* illustrative — needs the posted AP ledger" note on the 43B flag.
7. **FIN-7 (minor honest-gap) — EVA invested capital omits RM/WIP cycle stock** → ROIC overstated. Labeled the capital base "excludes RM/WIP cycle stock, so it's a floor and ROIC an upper bound."
8. **FIN-8 (cosmetic) — carryRate/carryRateParts fallback magic constants (0.1124/11.24)** drifted from the solved hurdle; now derive from `M.wacc.rate`. (Live path unchanged — fallback only.)

Confirmed already-closed by E′ (no rework): Board-pack = real `<ReportExport/>` in the header; Cash illustrative banner; FX live editor; default→Capital.

**Verification — SIMPLE test:** finance.jsx + data.jsx parse OK; server GET / → 200 (5,467 b shell); **FIN-1 solver smoke** via `/api/calc/npv` — buy leg PV-of-costs −₹80.3L vs lease leg −₹55.1L → **LEASE cheaper by ₹25L** (real computed verdict, matches `winner` logic; replaces the hardcoded ₹5L).

> **DOMAIN-HEAVY 4 COMPLETE (2026-06-05):** Demand ✅ · Plan ✅ · Sourcing ✅ · Finance ✅ — all via the relaxed loop (§6.5 first review → fix → simple test). Per-tab pass remaining = the chrome-y / lighter tabs (Home, Setup, Products, Production, Logistics, Console, Scenarios, Reference) if/when the user wants them; the four domain-critical tabs are done.
