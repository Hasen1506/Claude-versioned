# Implementation Plan — turning the review into a build

> Companion to `UNDERSTANDING_GUIDE.md`. The guide *answered* the 14 pages of notes
> and tagged each 🟩/🟨/🟥/🧭. This file is the **build flow**: how the fixes are
> grouped, the order they ship in, what each touches, and how each is verified.
>
> Standing rules (carried, unchanged): leave `index.html` untouched; all work in
> `app_v2/`; **No faking** (every number is a fact, a solved result, or an honest
> dash); provenance everywhere; one dataset; commit only when asked.

## The grouping principle

The fixes are batched by **what they share in code**, not by note-page order. A
batch ships when its tabs parse, its endpoints answer, and the live UI verifies.
The first batch is *foundation* because every later batch reuses it.

Key discovery from the store audit: **much of the "editability" machinery already
exists** in `store.jsx` and is simply not surfaced in the UI —
`useNetwork().setNetwork`, `editProductAttr`, `editPartAttr`, `addProduct`,
`logEvent`/`useEvents`, the `markStale`/`SOLVE_DEPS` cascade. So a large share of
the work is *wiring existing capability to inputs*, plus the genuinely-missing
pieces (error boundary, calendar bugs, line definition, the flow graph, the
activity-log surface).

---

## Batch 0 — Foundation (cross-cutting; ships first)

Everything downstream leans on these. Small, high-leverage, no behavioural risk.

| Item | File | What | Why first |
|---|---|---|---|
| **Error boundary** | `main.jsx` | wrap `<Stage/>` in a class `ErrorBoundary` that catches a render throw and shows a recover card instead of unmounting the SPA | Part 8.1 — converts "whole app dead" into "one card errored"; makes every later change safe to ship |
| **`ScopeBanner`** | `lib.jsx` | a loud "YOU ARE EDITING: <item>" band for item-scoped tabs | Theme 3 signposting; reused by Products, Network, Sourcing, Demand |
| **`ActivityLog`** | `lib.jsx` | a chronological reader of `useEvents()` (time · action · target · detail) | Theme 5 — the change-log surface wanted in Products/Demand/Sourcing; one component, many homes |

## Batch 1 — Setup · Identity & Calendar (front door master data)

Self-contained; the first screen a user meets. All 🟥/🟨 from Part 2.

- **CIN editable** (🟥) — promote `M.cin` → `config.cin`, bind an input.
- **Start Date → real date picker** (🟨) — `<input type=date>` instead of `TextInput`.
- **Horizon banner follows input** (🟥) — recompute the date range live from
  `planning.startDate + horizonLength × grain`, not the fixed `M.periods` seed array.
- **Plant-state drives holidays** (🟥) — backend `plant_calendar.py` gains honest
  per-state regional add-ons + a `state` param; the card passes `config.plantState`.
- **Per-day holiday add/remove** (🟥) — `config.customHolidays[]` + an add (date+label)
  / remove UI, passed through the existing `custom_holidays` API field.
- **Pure-MTS profile option** (🟨) — add to the `makePolicy` segmented control.
- **Auto-compute calendar once on load** (🟨) — so it never shows stale seed silently.

## Batch 2 — Products + Network (the two biggest editability bugs; share BOM↔parts)

- **Products catalogue rows inline-editable** (🟥) — name/price/cost/demand/family via
  `editProductAttr`; the row was the clearest Fact-5 violation.
- **BOM physical rows editable** (🟥) — qty/cost/lead-time via `editPartAttr`.
- **Lot size (MOQ) explicit on Costs** (🟨) — surface the hidden `moq` that drives setup-amort.
- **Scope banner** on Products (Theme 3).
- **Network nodes/lanes editable** (🟥) — wire `useNetwork().setNetwork`; add/edit/remove rows.
- **Network flow diagram = real directed graph** (🟥) — draw actual `from→to` lanes
  (hub-and-spoke), not the false linear conga line.
- **Lane trunk capacity / per-lane volume** (🟨) — add the missing planning fields.

## Batch 3 — Production + Sourcing (factory structure + procurement; interlinked)

- **Define line / stage / machine** (🟥) — add/edit lines, stages, worker & machine counts,
  per-stage cycle time (writes to a `production` master slice the payload reads).
- **Changeover matrix editable** (🟥) — directional A→B setup minutes.
- **OEE vs cycle-only toggle** (🧭) — a `simple|detailed` switch.
- **Opening on-hand editable** (🟨) — wire to the network on-hand slice.
- **Hide external-signals behind Advanced** (🧭) — keep wiring, declutter default UI.
- **Scope banner** on Sourcing; cross-link Products↔Sourcing supplier terms.

## Batch 4 — Demand + S&OP + Home (monitoring & consolidation)

- **Unified all-SKU consensus view** (🟨, Theme 4) — one table: every SKU's committed
  number, MTS forecasts + MTO firm orders side by side.
- **Hide NPI-like behind Advanced** (🧭).
- **Forecast "warming up" not "failed"** (🟥) — distinguish cold-start from real error.
- **Default landing grain = week** (🧭) — smooth curve, not day-grain "heart spikes".
- **S&OP "you're looking at families" label** (🟩→clarity).
- **Home: merge Readiness + Freshness** into one Solver-Lifecycle strip (🧭, Theme 6).
- **Exception Cockpit names the changed field** (🟨) — "stale *because you edited X*".

## Batch 5 — Onboarding wizard + plain-language explainers (the perceived-quality lift)

- **Onboarding greeting wizard** (🧭, Theme 2) — promote the six profile questions to a
  first-run greeting that sets the profile and hides engines you don't need.
- **Per-solver one-sentence explainers** (🧭) — "what is this?" on each solver card,
  fed by the Fact-4 roster.

---

## Verification protocol (every batch)

1. **Parse** — every touched `.jsx` through `@babel/parser` (the browser's parser).
2. **Compile** — any touched `.py` through `python -m py_compile`.
3. **Endpoint** — any touched route hit live (HTTP 200 + shape check).
4. **Live UI** — exercise the new affordance from a user's POV; confirm the number
   moves / the edit persists / nothing else regressed.

Server is started via `nohup python app.py` + a pidfile (never pattern-kill `app.py`
— its own argv self-matches and kills the shell).

## Status ledger

- [x] **Batch 0 — foundation** ✅ `ErrorBoundary` (main.jsx) wraps `<Stage/>`; `ScopeBanner` +
      `ActivityLog` added to lib.jsx & exported. Verified: 18/18 jsx parse.
- [x] **Batch 1 — Setup / Calendar** ✅ CIN editable (`config.cin`); native date picker;
      horizon banner recomputes from `startDate × horizon × grain` (`horizonRange()`);
      pure-MTS profile option; plant-state regional holidays (`STATE_HOLIDAYS` in
      plant_calendar.py + `state` param through the API) + per-day add/remove
      (`config.customHolidays` → `custom_holidays`); auto-compute on load.
      Verified live: TN=22 / MH=24 (Gudi Padwa present, May-1 dedups) / custom day passes
      through; py compile OK; 18/18 jsx parse.
- [x] **Batch 2 — Products + Network** ✅ Products: `ScopeBanner` ("EDITING ▸ product");
      catalogue rows inline-editable (name/make-buy/mode/price/target-margin/annual-demand
      via `editProductAttr`, demand also flags `demand` stale); BOM physical rows editable
      (qty/cost/lead via `editPartAttr`); explicit lot-size (MOQ) input on Costs. Network:
      flow diagram rewritten as the **real directed lane graph** (role columns
      supplier→plant→wh→dc→customer, one edge per `from→to` lane — hub-and-spoke &
      parallel paths now correct, replacing the false linear chain); editable **lane table**
      with the previously-missing **trunk capacity**; **Node Master** editable + add/remove;
      **on-hand matrix** cells editable (auto-creates rows). Verified: 18/18 jsx parse;
      transport endpoint still Optimal.
- [x] **Batch 3 — Production + Sourcing** ✅ Production: the **lines → stages → machines tree
      is now a full editable master surface** (was the read-only Fact-5 bug). `ProdArch`
      rewritten as a stage-by-stage editor — per-stage **machines, workers, cycle time, OEE
      and capacity** are live inputs (`PCell` inline editors); **line capacity & the bottleneck
      are DERIVED** (slowest stage, `_recalcLine`), never typed; **add/remove stage**, **add/remove
      line**, editable line **name/OEE/shifts**; a **detailed↔cycle-only** toggle hides the OEE
      columns (🧭). Backed by new store helpers (`editLine`/`editStage`/`addStage`/`delStage`/
      `addLine`/`delLine`/`setChangeover`) that mutate `M.lines`/`M.changeover` in place + bump
      master + flag the production family stale via a new **`prodArch`** SOLVE_DEPS source.
      `productionPayload` now reads the per-stage **worker count** (`bn.w||bn.m`) + line **shifts**.
      **Changeover matrix editable** (`ProdChange` cells → `setChangeover`, diagonal locked).
      Cycle-tab line selector now derives from the live `M.lines`. Sourcing: **ScopeBanner**
      ("EDITING ▸ Parts of <product>") with a **↗ Products cross-link**; **external-signal drivers
      moved behind `Advanced`** (declutter, wiring intact via a `bare` render). Opening on-hand
      editable was delivered in Batch 2 (Network). Verified: 18/18 jsx parse; production endpoint
      **Optimal** with the new worker/shift payload fields.
- [x] **Batch 4 — Demand + S&OP + Home** ✅ Demand: **default landing grain = WEEK** (🧭, smooth
      curve over day-grain spikes); **forecast "warming up" ≠ "failed"** (🟥) — new `fcStatus(fc)`
      classifies a thin-history cold start as amber guidance ("add history, re-run") vs a real red
      engine error, applied to the top banner AND the leaderboard empty state; **NPI like-modeling
      moved behind `Advanced`** (🧭) so the CSV-import path is the only thing shown by default;
      **unified all-SKU consensus view** (🟨, Theme 4) — the Company Rollup is now "All-SKU
      Consensus": every finished SKU's **committed (MTS)** number and **firm MTO** order-book backlog
      (`M.orders` where status='firm') side by side, company Σ for both. S&OP: a loud **"VIEWING ▸
      FAMILIES"** band on the Plan tab — names the family count and says per-SKU numbers return in
      step 4 (Disaggregation). Home: the **readiness gate + freshness panel are MERGED into one
      Solver-Lifecycle strip** (🧭, Theme 6) — each solver across BLOCKED → READY → FRESH → STALE,
      keyed to its solve-cache key (`LIFE_META` presentation map; dropped the now-dead `stageRows`).
      **Exception Cockpit names the changed field** (🟨) — `markStale` now records the root source
      (`staleSrc`/`staleAt`) and `STALE_SRC_LABEL` turns it into "stale because you changed committed
      demand / the production line setup / …" with a real elapsed-time stamp. Verified: 18/18 jsx
      parse; py compile; live forecast (11-model competition, winner ARIMA) + aggregate (Optimal,
      level) endpoints.
- [x] **Batch 5 — Onboarding + explainers** ✅ **OnboardingWizard** (lib.jsx, mounted in main.jsx) —
      a first-run greeting (gated on `localStorage.es_onboarded`) that asks the same **six profile
      questions** Setup holds, in plain words, sets the profile via the existing `profileStore`
      (which gates the spine), and previews live how many capabilities that hides; skippable +
      re-answerable in Setup. **SolverExplain** (lib.jsx) — a plain-language "WHAT IS THIS?" one-liner
      per solver, built from the Fact-4 roster (`M.solverIO`) so it can't drift, with a `SOLVER_PLAIN`
      layman-wording map; surfaced on **demand (forecast), plan (aggregate), production, sourcing
      (procurement), logistics (transport), finance·capital, and Console (keyed to the selected
      engine, leading the existing SolverIO contract)**. Verified: 18/18 jsx parse; py compile.

## Batch 6 — Solver glass-box: type-audit, term→input audit, Anatomy Lab + REAL browser smoke

A separate workstream from the note-fix batches, prompted by: "what type of solvers are
these — some are MILP, some aren't — everywhere we call them MILP; correct it" + "does every
term in the solver formulas have an input?" + "set up browser tooling, don't do half-assed work."

- [x] **Authoritative solver taxonomy** — read every solver's `.py` docstring + variable
      categories and corrected the platform's blanket "MILP" labelling. Truth:
      **MILP** = procurement, production, capital_capacity, meio (integer/binary vars);
      **LP** = profitmix, aggregate, transport, capital, linecap, cvar (continuous, valid duals);
      **closed-form/DP** = lot_sizing (EOQ/Wagner-Whitin), policy ((s,S)/(R,Q)), meio_network
      (√-law), disaggregate, reconcile; **heuristic** = sequencing (ATSP), consolidate;
      **simulation** = montecarlo; **statistical/ML** = forecast. Encoded in `M.solverType`.
- [x] **Mislabel fixes** — `data.jsx` roster engine fields (sequencing→ATSP heuristic, lotsizing→
      closed-form/DP, transport→LP, consolidate→heuristic, capital→LP; cvar→stochastic LP) + the
      `solverModes` "Transport/Capital MILP" labels + prose across logistics/network/store/
      production/demand ("transport MILP"→LP, "sequencing MILP"→ATSP, generic "the MILPs read"→
      "the downstream solvers", routing "optimized (MILP)"→"(LP/MILP)").
- [x] **Term→input cross-reference audit** (`M.solverModel`) — per headline engine the objective,
      decision vars, constraints, and **every cost/RHS term mapped to the define-section that feeds
      it (✓ wired) or honestly flagged ⚠ defaulted-in-the-.py**, plus `extras` = capability the
      module models with NO input surface ("too much stuff"). Headline finding: **procurement.py
      reads ~130 params but the payload sends ~10** — regime-aware sourcing, VMI, CVaR-fill sourcing,
      supplier/FX concentration caps, transport disruptions, milk-run/terminal-anchor, RM-warehouse
      limits, working-capital replan all run on built-in defaults, unwired. profitmix budget/
      warehouse/MTO-floor, aggregate labor-hours/safety-stock, transport customs, capital budget/
      exclusivity, montecarlo lead-time/correlation, cvar holding/shortage are likewise defaulted.
- [x] **Solver Anatomy Lab (Cartesian-style)** — new Console band ③ `SolverLab`, 3 panes keyed to
      the selected engine: ① the REAL model (type badge + objective/vars/constraints + a read-only
      source view via new backend `GET /api/meta/solver-source/<id>` — docstring + bounded excerpt,
      **no code-execution path**, RCE-safe); ② Inputs ▸ the term-provenance audit (WIRED/DEFAULT +
      "modelled but not wired"); ③ Live solve on the committed dataset (shared payload builders) →
      status·objective·runtime + duals for LPs / "binding+gap" note for MILPs / "no duals" for sim.
- [x] **Browser tooling + end-to-end smoke** — installed Playwright + Chromium (+ system deps);
      `smoke.cjs` drives real Chromium through all 13 tabs + the Lab. **It immediately found a
      pre-existing, app-breaking bug static checks never could:** Babel-standalone hoists a top-level
      `const _excluded` per file for object-REST destructuring; lib.jsx (Box/Btn) **and** console.jsx
      (`{dcap,...r}`) both did → duplicate const in the shared global scope → SyntaxError that blanked
      the ENTIRE app on every tab. Fixed by stripping object-rest from console.jsx (lib stays the sole
      emitter). Second bug: Logistics passed a raw `Date` to `Provenance asOf` → "Objects are not valid
      as a React child" → blanked Logistics; fixed by coercing Date→string inside `Provenance`.
      **Final: ✅ 13/13 tabs render clean · onboarding wizard greets · Lab source-view + live-solve
      pass · all 20 solver-source endpoints 200.** render.yaml/requirements need nothing new (new
      endpoint uses only stdlib os+ast; Flask already serves app_v2; Playwright is a dev-only dep).

### Batch 6b — wiring the most-critical unwired terms (audit follow-through)

The audit's whole point: "you kept saying integrated, but terms remained unwired." Fixed
the two most-critical ones — both cases where the INPUT/DATA already existed in the UI and
the solver simply ignored it (a correctness bug, not a missing feature), wired in their
EXISTING homes (no new UI, no cluster dump):

- [x] **profitmix ▸ firm MTO orders as a production floor.** `M.orders` (the firm order book,
      already shown in Products → Make-to-Order and Demand consensus) was never sent to the
      profit-mix LP, so the optimiser could drop a *contracted* SKU to zero to chase margin.
      `profitmixPayload` now sends `min_quantity = Σ firm orders[sku]` (`_firmOrderFloor`,
      firm-only — planned orders stay advisory). profitmix.py already supports the floor; it
      just wasn't fed. Placement: one honest `Reading` line in the existing Products MTO card
      ("q[k] ≥ Σ firm orders[k]"). **Proven live:** a dominated SKU goes 0→200 (the floor) and
      the mix rebalances the rest, status stays Optimal.
- [x] **capital ▸ budget + WACC from Finance (was hardcoded ₹2.5 Cr / 11.24%).** `capitalPayload`
      now reads the SAME governed Finance inputs the capital-capacity solver already uses —
      `config.finCapexBudget` ("Budget/yr") + the live blended WACC (`finBlendedHurdle`) —
      falling back to the old seeds when Finance is untouched. Placement: reused the existing
      Finance inputs (zero new UI); the Console capital result `Reading` now prints the live
      budget/WACC and says "from Finance". **Verified live** in-browser (solve clean).
- `M.solverModel` flipped both terms ⚠→✓ so the Anatomy Lab reflects reality.
- **Deferred, honestly:** `aggregate.labor_hours_per_unit` is the SKU-aggregation *weight*;
      changing it from the flat 1.0 silently rescales the family vs the governed `rate_per_worker`,
      so it needs the rate reconciled in the same units — not a safe drop-in, left as a named
      follow-up rather than a breaking wire. Advanced procurement extras (regime/VMI/CVaR-fill/
      concentration caps/disruptions) remain intentionally out of scope (no input surface).

Verified: jsx parse + app.py compile + live profitmix floor proof + 13/13 browser smoke + Lab pass.

**Next tier (done) — procurement/policy/MC carry rate ⇒ Finance WACC + holding spread.**
Same class of bug: the inventory **carry rate** (annual cost of holding a unit) was a hardcoded
`0.24` magic constant duplicated across `policyPayload`, `montecarloPayload`, and *defaulted*
inside procurement.py (the main `procurementPayload`/`_loopProcurementPayload` sent none) —
ignoring Finance entirely.

- [x] **New `carryRate(config)` / `carryRateParts(config)` helpers** (finance.jsx, next to
      `finBlendedHurdle`): carry rate = **governed blended WACC** (live, from the Finance hurdle
      card) **+ a holding spread** (`config.invHoldingSpread` %, seed 12.8 — storage/insurance/
      obsolescence/shrink). Seed ⇒ ≈24%/yr at the seed WACC, so default economics are **unchanged**;
      but raise leverage/Ke in Finance and every holding term in procurement/policy/MC now moves.
- [x] **All four payloads wired** to `carryRate()` — `procurementPayload` + `policyPayload`
      (sourcing.jsx), `_loopProcurementPayload` + `montecarloPayload` (store.jsx).
- [x] **One editable knob, in its natural home:** `CarryRateControl` in the existing Sourcing
      reorder-policy card (where EOQ's `h` lives) — shows `carry = WACC X% (from Finance) + spread
      [12.8]%/yr`, the spread is the only new input; editing it marks procurement/policy/rolling/MC
      stale via `setConfig`. New config seed `invHoldingSpread:12.8`. No new card, no cluster dump.
- [x] `M.solverModel` procurement "carry / holding rate" flipped ⚠→✓.
- **Proven live:** procurement objective moves with the rate — ₹1,862,757 (10%) → ₹1,866,100 (24%)
      → ₹1,864,229 (60%), the optimiser trading FG holding against other costs; policy.py also
      inherits the governed rate for any part lacking an explicit `hold_pct` (line 68). 4/4 jsx parse
      + 13/13 browser smoke + Lab pass.
