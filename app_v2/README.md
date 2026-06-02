# app_v2 — the redesigned frontend (in progress)

The new UI, ported from the v4 prototype (`design/incoming/`) and being re-wired
to the **real** backend (`app.py` + the PuLP/CBC solvers). The live
`index.html` stays untouched until this is finished and bundled.

- **Entry:** [index_v2.html](index_v2.html) — open in a browser (in-browser Babel,
  same as the prototype). Modules load flat from this folder.
- **Build form:** multi-file during the port; concatenate into a single
  `index_v2.html` only when done (matching how `index.html` ships).
- **Backend:** unchanged. Every engine maps to a real route — `/api/solve/<x>`
  (profitmix, procurement, production, transport, capital, montecarlo, cvar,
  aggregate, sequence, lotsizing, consolidate, sop, pipeline, rolling,
  capital-capacity, policy) and `/api/calc/<x>` (landed-cost, npv, depreciation,
  wacc, disaggregate, calendar), plus `/api/forecast`, `/api/whatif`,
  `/api/ai/insights`, `/api/demand/*`, `/api/risk/regimes`.

## Port status

| Module | Ported | Wired to real API | Notes |
|---|---|---|---|
| lib.jsx | ✅ | n/a (pure UI) | DevNote gated off; **trust primitives added** |
| data.jsx | ✅ (copied) | ⬜ | still the mock store `M`; becomes real state per-stage |
| chrome.jsx | ✅ (copied) | ⬜ | solve-chain "zoom levels" relabel pending |
| main.jsx | ✅ (copied) | n/a | router/mount |
| home · setup · products · network · demand · plan · production · sourcing · logistics · finance · console · scenarios · reference | ✅ (copied) | ⬜ | per-stage UX surgery + API wiring pending |

Order of the wiring pass (dependency-first): **setup → products → network →
demand → plan → production → sourcing → logistics → finance → console →
scenarios → reference**.

## Trust layer (the BI atom every figure declares against)

Added to `lib.jsx`, exported on `window`:

- **`<Provenance kind asOf run stale/>`** — labels a number `input` / `derived` /
  `solved` / `external`, with an as-of stamp and a `stale` flag.
- **`<AsOf t/>`** — bare timestamp chip for panel headers.
- **`<StaleMark since go onNav/>`** — amber banner when a result's inputs changed
  after the last solve; deep-links to re-solve.

These complete the existing trust set already in the prototype and kept as-is:
`Reading` (formula + "so what"), `SolverIO` (answers/from/feeds), the Readiness
gate (blocks a solve + names the missing input), `SectionInfo`.

## Decisions ledger (UI-expert pass)

Applied or scheduled during the port — not yet all executed:

- **DevNote `</Component>` chips → OFF in production.** Done (gated by
  `BUILD.devNotes`; turn on with `localStorage.setItem('es_dev','1')`).
- **Finance regrouped 7 → 5 sub-tabs** — `Cash & WC · Capital · Investments ·
  Assets · FX & Hedging`. **Done.** EVM **moved in** from Scenarios·Performance
  (beside Budget vs Actual) + got a `Reading`; CCC **moved in** from
  Scenarios·Cost; Buy-vs-Lease **folded into** Investments; CAC **demoted**
  behind `Advanced ▸` (weak fit — flagged for removal). Scenarios left a
  "MOVED →" breadcrumb where EVM was.
- **Scenarios·Performance dissolved.** **Done.** S&OP Gap → **Plan** (step 5,
  "Gap to Target", + Reading); FVA → **Demand** (Model Competition, + Reading);
  KPI Dashboard → **cut** (duplicated Home); Version History → **masthead**
  (`VersionMenu` popover with restore). Scenarios is now Risk · Cost · Explore.
- **CAC kept** (your call) — stays behind `Advanced ▸` in Cash & WC.
### Round 2 — per-tab corrections (all DONE)

- **Logistics map rewritten** — projected lat/long, India silhouette drawn in the
  same projection, marker + label de-overlap. No more stacked nodes.
- **Setup**: MSME now **derived** (Micro/Small/Medium → else **NOT MSME**, with
  43B(h) shown only when it applies); currency reads the **FX table** (no `84.20`
  literal); **Planning Profile promoted** to step 2 (above Calendar).
- **Home**: pipeline list removed from Control Tower (the ribbon is the pipeline).
- **Console**: dead "All N result sections" pill grid **cut**.
- **Scenarios**: Stakeholder matrix → `Advanced ▸`; mock-AI cards (What-If Bot,
  Live Insight, Auto-Researcher) tagged **preview** (they map to real
  `/api/whatif`, `/api/ai/insights`, `/api/solve/researcher`).
- **Reference**: **demoted** off the planning rail → reached via a masthead
  **❓ Learn** button (still registered in `main.jsx`, renders when active).
- **Production**: split the 5-section wall into **4 sub-tabs** (Architecture ·
  Cycle & Line · Schedule[MPS+ATP] · Changeover) to tame density.

### Deferred to the per-stage WIRING pass (need real data, not structure)

These are honesty/trust gaps that only close when mock `M` → real state:
- Products: BOM must follow the active item; cost-rollup % must derive from BOM.
- Network: flow SVG needs a real layout for >4 hops.
- Demand: reconcile 24-month history vs 52-week axis (grain).
- Plan: disaggregation split must derive from Profit-mix, not a literal. **(DONE
  in wiring — now derives from the aggregate solver's `sku_plans`.)**
- Finance: dedupe NPV / Plan-NPV / Investment-Decision overlap across Capital +
  Investments.
- Reference: move the orphaned **CVaR** card to Scenarios when wired.
- Home: reconcile the 3 solve-chain views (ribbon 6 / spine 9 / network 16) into
  labelled zoom levels.

## Wiring pass (mock `M` → real state + `/api/*`)

The substrate every stage reuses now exists in **`store.jsx`** (loaded after
`lib.jsx`, before `data.jsx`):

- **`apiPost` / `apiGet`** — one fetch wrapper; normalized errors + safe JSON.
- **`useSolve(endpoint, buildPayload)`** — the `{solving, result, error, ranAt,
  run, reset}` pattern `index.html` repeats ~20×, as one hook.
- **`appStore` + `useStore` / `useConfig` / `usePlanning` / `useCalendar`** — live
  app state in the **real backend shape** (a subset of `index.html`'s
  `defaultState`). Same external-store idiom as `profileStore` (plain object +
  subscriber `Set` + `localStorage` key `es_state`) — **no React context /
  provider needed**, so every standalone stage function can read/write it.
- **`msmeTier(invCr, toCr)`** — the single derived MSME fact, shared by Setup /
  Sourcing / Finance.

To make binding possible, `lib.jsx`'s `NumInput` / `TextInput` / `Select` gained
an optional **`onChange`** → controlled mode. **Omit `onChange` ⇒ unchanged
uncontrolled `defaultValue`**, so every not-yet-wired call site is untouched
(zero regression to unwired stages).

The state grows **slice by slice** — a field stays on mock `M` until its stage's
pass moves it into `appStore`.

| Stage | Wired | What |
|---|---|---|
| **setup** | ✅ | Company name/currency/tax/service/GST → `config`; MSME tier **derived live** via `msmeTier()` (incl. NOT-MSME) from editable turnover/investment; Calendar grain/horizon/start/workdays → `planning`; **`⚙ Compute calendar` calls the real `/api/calc/calendar`** → live working-days/holiday list/availability bar with `Provenance`+`AsOf`. |
| **products** | ✅ | Cost rollup: **material genuinely derived from the BOM** (Σ qty·cost — the old 70/18/7/5 split was fake) + editable+persisted setup/labour (`productCosts` slice) + labelled conversion residual; contribution/CM re-derive live. Inventory policy: **`⚙ Derive policies` calls the real `/api/solve/policy`** → per-part EOQ/SS/(s,S)/(R,Q) table with `Provenance` (replaces hardcoded FG figures). |
| **network** | ✅ | Master-data DEFINE stage (no solver of its own — it *feeds* transport/procurement). Nodes/lanes/suppliers/contracts/on-hand promoted to a live **`appStore.network`** slice via `useNetwork()` / `getNetwork()`, **seeded lazily from mock `M`** (no figure duplication) and writable. Supplier footer totals (qty/spend/OTIF) now **derived** from the rows (qty-weighted OTIF), replacing the hardcoded `6 / 35,900 / ₹85.0L / 92.4%`. `getNetwork()` is the hook-free reader so Sourcing/Logistics `buildPayload()` pull the same topology. |
| **demand** | ✅ | **`🤖 Run Forecast` calls the real `/api/forecast`** (lifted to `StageDemand`, fed to chart + leaderboard). History+Forecast chart overlays the **winning model's live forward series**; the Model Competition table renders the **engine's real leaderboard** (MAPE/RMSE/MAE/status, sorted, winner ★, failed-fit models greyed not hidden) with `Provenance solved`. Falls back to the mock curve/competition until a solve lands; surfaces engine errors inline. (`run_forecast` verified by direct import — 4 models avail here w/o sklearn/statsmodels, naive wins, 12-period forecast.) |
| **plan** | ✅ | **`⚡ Solve Aggregate` calls the real `/api/solve/aggregate`** (Hax–Meal). Payload feeds each finished SKU a monthly forecast (mock 6-mo family demand split by annual share) + seed planning-economics params (`PLAN_PARAMS`). Result threads into all four cards: **Capacity vs Demand** (chart+table from `periods`, capacity = rate×workforce), **Level/Chase strategy** (real `strategy`+`strategy_note`, workforce/inventory CV), **Seasonal prebuild** (`seasonal_prebuild`/`peak_inventory`/`total_backorder`), **Workforce** (`periods` heads/hire/fire/OT), and **SKU Disaggregation now DERIVED from `sku_plans`** (closes the deferred "disagg split must derive" item). Real **capacity shadow prices** (per-period regular-capacity duals) replace the mock; empty-state when no row binds. Mock fallback until solved. (`solve_aggregate` verified by direct import — Optimal, 6 binding duals, sku_plans reconcile.) **Seed cost params are placeholders** pending a Plan cost-inputs card. |
| **production** | ✅ (sequencing) | Changeover **`⚡ Sequence` calls the real `/api/solve/sequence`** (shortest Hamiltonian path over the changeover matrix). The "Chosen Run Order" card now renders the **solver's actual sequence + total/saving/basis** (was a hardcoded `order=[0,2,1,3]`); client-side brute-force remains the fallback until solved. `Provenance solved` + run button. (`evaluate_line` verified by direct import — exact basis, saving vs averaged-approx.) **Deferred:** the full production MILP behind MPS/ATP/line-capacity (Architecture/Cycle/MPS/ATP stay master-data/derived display — wiring `/api/solve/production` needs the line+stage+demand payload assembly, a separate lift). |
| **sourcing** | ✅ (landed cost **+ procurement MILP**) | Landed-cost rollup **`🛃 Compute landed cost` → real `/api/calc/landed-cost`** (POSCO billet: FOB USD→FX→freight→insurance→CIF→BCD→SWS→IGST→CHA→inland→net-of-ITC; reproduces the mock's ₹28.1L to the rupee). **NEW — `⚡ Run procurement` → real `/api/solve/procurement`**: the selected item's **keystone demand series** exploded through the BOM (`bomParts()`, day-leads converted to periods, order/storage caps sized off MOQ). **PO Release Plan** = real per-part `purchase_orders` (release→arrive, qty, value); **Shortage Forecast** = real per-period unmet demand (or a ✓ no-shortage state); **Per-Part MRP** keeps its pedagogical gross→net mechanic and adds a real MILP-orders strip for the selected part. `Provenance solved` throughout. (Verified Optimal, 5 POs across parts, 100% fill.) |
| **logistics** | ✅ (transport + CoG) | **`⚡ Solve Transport` → real `/api/solve/transport`** (`transportPayload()` builds outbound shipments from the network's outbound lanes × the FG flow × an assumed 3 kg unit weight — the one documented assumption). **Allocation** KPIs (total freight, avg cost/shipment, on-time %, mode mix) and **Consolidation** (real `consolidation_saving` + per-lane recommend/empty-state) now come from the solver. **Center-of-Gravity** is a **real client-side weighted-centroid** (`computeCoG()`: Σwᵢxᵢ/Σwᵢ over DC+customer nodes, weighted by throughput → nearest-city label) replacing the hardcoded `M.cog` — there is no backend endpoint because CoG is a closed-form formula, not an optimisation. `Provenance` on all three. |
| **finance** | ✅ (WACC + NPV **+ depreciation**) | **`💹 Recompute` chains real `/api/calc/wacc` → `/api/calc/npv`** in FinCapital (Ke via CAPM; exposed a mock contradiction — KPI said ₹13.7L vs real DCF ₹100.9L, IRR 26.9%). **NEW — FinAssets `📉 Compute schedule` → real `/api/calc/depreciation`**: the asset register aggregated at its portfolio WDV rate (Σdep÷Σcost = 9.2%) → real declining net-block curve replaces the fabricated `[238,183,142,…]` bars; register footer totals now derived from `M.assets`. `Provenance solved`. **Deferred:** Plan-NPV/Investment-Decision (need plan cash-flow assembly). |
| **console** | ✅ (**all 6 result sections**) | Every Optimize-console result section now runs a real solver. **ResProfit → `/api/solve/profitmix`** (capacity-rationed mix, margin/hr ranking, binding dual, make/drop). **ResRisk → `/api/solve/montecarlo`** (cost histogram + **CVaR-95**, VaR, fill). **ResProcure → `/api/solve/procurement`** (joint PO register + real `(s,S)/(R,Q)` reorder policies). **ResProduce → `/api/solve/production`** (real Gantt from the schedule, per-line utilisation, fulfilment, shutdown candidates). **ResTransport → `/api/solve/transport`** (per-lane mode/weight/cost + consolidation). **ResCapital → `/api/solve/capital`** (budget-constrained knapsack — defers a higher single-NPV item to fit two that together return more). All `Provenance solved` + mock fallback; all five new payloads verified Optimal by direct import. **Deferred:** ResSOP (closed-loop reconciliation needs the cross-solver loop). |
| **scenarios** | ⬜ (mostly catalogued — empirically confirmed) | Catalogued risk/cost data (Control Tower / Risk Matrix / Disruptions / Cost Waterfall / TCO / What-if). CVaR is live in console ResRisk. The one solver candidate — Tornado via `/api/solve/sensitivity` — was **tested and left illustrative on purpose**: in this MC the total cost is dominated by deterministic variable cost, so sweeping service-level/carry-rate/MAPE moves `avg_cost` only 0.0–0.1% → a real tornado-on-cost would be a misleadingly flat chart. Honest call: keep the illustrative version. |
| **reference** | n/a (static) | Learning Lab + SAP T-code cheatsheet — **educational/reference content by design**, no solver wiring applicable. |

**KEYSTONE (`store.jsx`):** a shared **`demand` slice** is the single source the MILPs plan to. The Demand stage's `🤖 Run Forecast` now **persists the winning forecast** per SKU (`setItemDemand`); `getItemDemand(sku,T)` / `getFinishedDemand(T)` resample it (falling back to `M.products[].demand` spread evenly), and `bomParts()` / `transportPayload()` build the procurement/transport payloads from it — so forecast → procurement → production → transport → capital all plan the **same** demand curve. This is what unblocked the four MILPs in one move.

**Still deferred (need real per-item data):** per-item BOM (`M.bom` is one shared illustrative BOM that doesn't sum to the item's standard cost — surfaced honestly as a "conversion & overhead" residual); real per-period demand series for policy variability (flat seed → σ=0; the Demand stage will feed it).

### ⚠ Backend packaging finding (blocks end-to-end run)

`app.py` does `from solvers.X import …`, but the solver modules sit at **repo
root** with **no `solvers/` package** — so `python3 app.py` fails with
`ModuleNotFoundError: No module named 'solvers'`. The route *contracts* are
verified directly (e.g. `build_calendar()` returns `total_working_days`,
`total_holidays`, `holiday_list:[{month,day,name}]` ✓), but the wired frontend
can't talk to a live server until this is resolved (a thin `solvers/` shim
package re-exporting the root modules, or moving them under `solvers/`). Not
touched yet — it's a backend-structure change, pending user direction.

## Compact / bundle readiness

- All 17 modules parse clean (`@babel/parser` + jsx). Open `index_v2.html`.
- Bundle step (later): concatenate the `.jsx` in load order into one
  `<script type="text/babel">` inside a single `index_v2.html`. Safe — modules
  share one global lexical scope already (no duplicate top-level `const`), so
  concatenation won't collide. Do this only when the port is finished.

## Provenance of the source

15 of 17 prototype `.jsx` are byte-clean originals from `origin/main`; `lib.jsx`
and `chrome.jsx` were transcribed. Spec = `design/REDESIGN_BLUEPRINT_v2.md`
(Parts 0–7).
