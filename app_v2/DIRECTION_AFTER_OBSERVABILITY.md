# Direction — after the observability build
**The merge of (a) + (b) + (c) and every bug the build surfaced, with the way forward.**

> Context. The observability spec (`OBSERVABILITY_MAP_AND_RESEARCH_SPEC.md`) ended with a Tier-1/2 backlog and three focus areas you named — **(a)** finish the 8 lighter tabs (both-lens review + ONE solid scenario each, not all 5), **(b)** the end-to-end test, **(c)** catch provenance by code. This round **built the backlog** and, in building it, **found new mistakes** (the point of the exercise). This doc merges all of it and directs what's next.
>
> **Scope of THIS round (done):** OBS-3 (c) · OBS-1 the graphic · OBS-2 + HARNESS-1 (b).
> **Both deferred items now DONE:** item **(a)** the 8-tab pass (§6/§7, B-2/B-7…B-12) · **HARNESS-2** the sub-flow runner (§8 — found B-13/B-14, all 4 sub-flows PASS live). Specs remain in §4.
> Everything below is **frontend + tools + docs, still uncommitted.**

---

## 1 · What got built (the backlog, completed + verified)

| Artifact | Spec ref | Maps to | Verification |
|---|---|---|---|
| **`tools/provenance_lint.js`** — scans all 18 jsx; a `solved/derived` chip must trace to a solve or a computation in its component | OBS-3 | **(c)** | ran clean; **proven to bite** (fixture with a seed-as-solved chip → 2 UNBACKED, exit 1) |
| **`ModelMap`** (Reference ▸ **Model Map**) — the 16-solver fabric re-coloured by **live** freshness + node drill-down (inputs → formula → API → last result) | OBS-1 | the graphic | parses; served; reuses `SolverNetwork` (no third drawing, P-H) |
| **`ConsistencyPanel`** (same subtab) — 5 cross-solver identities asserted on the live cache, honest "—" when a solve hasn't run | OBS-2 | **(b)** in-app | parses; served |
| **`tools/model_check.js`** — one CI harness: parse 18 jsx + run the lint + assert all 16 solver endpoints registered + served-bytes | HARNESS-1 | **(b)** CI | **4 pass / 0 fail**; caught a real drift on first run (see B-4) |
| `procCost` added to `_captureKpis` (store.jsx) | — | HARNESS-2 groundwork | additive; gates green |

`model_check.js` is now the **one smoke** that replaces the 18 bespoke per-tab parse/serve checks.

---

## 2 · New bugs & blind spots the build surfaced (the discovery)

Each was found *by building the observability tools*, exactly as intended.

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-1** | `DemCommit` claimed `kind="solved"` for committed demand **even when the planner hand-overrode or imported it** (commit can come from `override`/`npi_likemodel`/`actuals`, not just the forecast). | **P-A** (seed/source-as-solved) | **FIXED** — chip is now lineage-aware via `COMMIT_PROV` (`solved` only for `forecast_commit`/`replan`; `input` for `override`; `derived` for like-models; `external` for actuals). |
| **B-2** | The headline `SolverNetwork` fabric (rendered by **Home + Console**) colours nodes by the **seed** `status` field (`done/running/queued`), so the map of the machine **lies about which engines have actually run.** | **P-A** | **FIXED for OBS-1** (live `useStale` colouring). Home/Console still pass no `freshness` → **follow-through 4C** to wire them live too. |
| **B-3** | **Only 6 of 16 solvers persist to the cross-stage cache** (`forecast, procurement, aggregate, production, linecap, montecarlo`). The other 10 run **local-only** → invisible to any cross-solver check or the value ledger. | observability gap | **RESOLVED 2026-06-06 (§10)** — added `solveKey` to profitmix/transport/capital/meionet (now **10 of 16** cache). The 5 still-local are genuinely tab-only (disaggregate, reconcile, sequencing, lot-sizing, capital-capacity), shown honestly "untracked". Exposed **B-15** (`capital.total_npv` field fix). |
| **B-4** | `/api/solve/reconcile` **does not exist** — the Reconcile solver is the S&OP pipeline at **`/api/solve/sop`** (`run_sop_pipeline`). The spec even hedged it as `…/sop(?)`. | endpoint drift | **FIXED** in the OBS-1 `_OBS_API` map, HARNESS-1, and spec Appendix A. **Caught by HARNESS-1 on its first run.** |
| **B-5** | The scenario engine's snapshot envelope `_SCN_INPUT_KEYS` **omits `prodArch`** (lines/stages/changeover live in the global production master, mutated via `bumpMaster()`, not an appStore slice). So a **capacity what-if silently no-ops** and can't be byte-restored. | P-F-adjacent (control that doesn't fully apply) | **DOC-ONLY** (architectural) — blocks SF-7; fix in **4C**. |
| **B-6** | The captured KPI row `_captureKpis` had **no procurement cost**, so cost/FX sub-flows weren't assertable. | KPI-coverage gap | **FIXED** — `procCost` (procurement `total` landed spend) added; unblocks HARNESS-2 SF-4/SF-2. |
| **B-16** | **The whole app was BLANK at runtime.** The B-5 fix added `const { prodArch, ...slices } = env` (store.jsx `_applyEnvelope`). Babel-standalone hoists a top-level `const _excluded` helper per file for object-REST destructuring; **lib.jsx (Box/Btn) is the sole sanctioned emitter** (console.jsx:897 documents the convention) — a 2nd in store.jsx collided in the shared global scope (`Identifier '_excluded' already declared`), so **store.jsx never executed** → no `appStore`/`useStore`/`runFullLoop` → every tab dead. Invisible to parse/curl/served-bytes (none boot the app); only HARNESS-1b's real-browser run surfaced it. | P-H-adjacent (transpile-helper collision) — the shadow check's BLIND SPOT (helper is injected, not in source) | **FIXED 2026-06-06 (§11)** — rewrote `_applyEnvelope` with `Object.assign`+`delete` (the documented pattern). Added a HARD static guard to HARNESS-1 (`one object-rest _excluded emitter`, AST-based, proven to bite) so a 2nd emitter fails the gate without needing a browser. |

---

## 3 · The merged area of focus

The wedge is **glass-box + provenance**; every R2/P-A erodes exactly what we sell. This round made the two biggest honesty surfaces **machine-checked** rather than review-checked:

- **provenance** → OBS-3 lint (run in CI),
- **cross-solver consistency** → OBS-2 panel (live) + HARNESS-1 (CI).

What's left un-machine-checked, and therefore the focus, is the **edges**: the 8 lighter tabs that never got the two-lens review (where local lies still hide, per blind-spot #2), and the levers the scenario engine can't yet isolate (B-3, B-5, B-6). **Unified focus: close those corners — finish the tab reviews, get every solver on the cache, make the scenario engine isolate every lever.**

---

## 4 · Directed plan (DEFERRED execution — pick-up-ready after compaction)

### 4A · Item (a) — the 8 lighter-tab pass
**Method (your constraint):** both-lens review (domain + design) **+ ONE solid scenario verification each** (not all 5). Run `node app_v2/tools/model_check.js` as the gate after each tab.
**Order — most-likely-to-hide-lies first** (blind-spot #2 named Production/Logistics/Console):

| # | Tab | The ONE scenario to verify it against |
|---|---|---|
| 1 | **Production** | golden-path STEP 4 — schedule the committed plan; assert OEE provenance is real, `projected_inventory` feeds Finance EVA, bottleneck = LINE-01, sequencing covers all 6 SKUs |
| 2 | **Console** | STEP 5 — profit-mix glass box; assert the result-mirror isn't a dedup lie and the dual explanation matches `shadow_prices` |
| 3 | **Logistics** | STEP 8 — transport LP; assert allocation flows **sum to demand** (conservation) and the "~18% km cut" empty-state is honest |
| 4 | **Home** | first-run — every KPI chip traces to a solve or carries a seed/`SeedFence`; the fabric reads live (close B-2) |
| 5 | **Setup** | STEP 1 — editing a governed param cascades `markStale` to every dependent solve (SOLVE_DEPS) |
| 6 | **Products** | the `ScopeBanner` per-item vs portfolio claim (P-B) holds for every card |
| 7 | **Scenarios** | STEP 10 — what-if branch leaves the live working set byte-identical |
| 8 | **Reference** | the new Model Map + API catalog stay truthful (already partly machine-checked by HARNESS-1) |

### 4B · HARNESS-2 — disruption sub-flow runner (spec recorded · ✅ BUILT 2026-06-06 — see §8)
**Form:** in-app `SubflowHarness` in `scenarios.jsx` (it's **behavioral** — needs the real `runScenario` re-solve loop, byte-restored — so its home is in-app, not a node script). Reuses the What-If bot's proven perturbation transforms.
**Runnable now (4)** — clone snapshot → perturb lever → `runScenario` → assert KPI direction → `deleteScenario` cleanup:

| SF | Trigger | Lever | KPI · expected |
|---|---|---|---|
| SF-1 OEM ramp | 4471+3215 demand ×1.4 | `inputs.demand` | `planCost` ↑ |
| SF-5 Demand collapse | all FG ×0.6 | `inputs.demand` | `planCost` ↓ |
| SF-4 Commodity spike | parts landed +20% | `inputs.sourcing.dutyFreightPct` | `procCost` ↑ |
| SF-2 FX shock | USD/₹ +₹5 | `inputs.config.fxRates.USD` | `procCost` ↑ |

**Not runnable — honest coverage gaps (3):** SF-7 capacity loss (**B-5** — prodArch not in the snapshot), SF-3 supplier aging (finance-only §43B, no loop KPI), SF-6 lead-time stretch (KPI coupling — run via Risk ▸ stress).
**Groundwork already landed:** `procCost` in `_captureKpis` (B-6 fix).

### 4C · Follow-through fixes the build pointed to
- [x] Wire **Home + Console** `SolverNetwork` to live `freshness` (fully close **B-2**). — **DONE** in §6 Tab 4/8 (the shared `solverFreshnessMaps`).
- [x] Give **profitmix / meionet / transport / capital** a `solveKey` so they join the cache (close **B-3**; lights up more OBS-2 identities + the value ledger). — **DONE 2026-06-06, see §10.**
- [x] Add **`prodArch`** to the scenario snapshot envelope (close **B-5**; unblocks SF-7 and all capacity what-ifs). — **DONE 2026-06-06, see §9.**
- [x] **HARNESS-1b** — golden-path with payload fixtures: the full 5-way demand conservation + profit-mix↔linecap↔finance dual chain that OBS-2 can't see from the partial cache. — **DONE 2026-06-06, see §11.** Built as a headless-Chromium replay of the REAL app loop (no node reconstruction = genuinely *observed*). **Found + fixed B-16** (an app-blanking Babel `_excluded` collision that every static/HTTP smoke missed) and added a static guard so the class can't recur. 9/9 identities PASS live.
- [x] Spec Tier-3: units contract (P-C/D), scope declaration (P-B), twin-quantity reconciliation (P-E). — **DONE 2026-06-06, see §12.** The **units contract (P-C/D)** was the genuine remainder (P-B already held — Tab 6/8 Products; P-E's concrete instance already closed as B-13). Fixed the changeover hrs-vs-`_min` boundary (UI=hours, `/api/solve/sequence`=minutes, ×60 convert), retired the `₹4200/hr` magic constant (→ governed labor rate), removed the stale 4-SKU fallbacks. Verified **under HARNESS-1b's net (9/9 still PASS, app still boots)** + a live sequence smoke (108 min → 1.8 hrs).

---

## 5 · How to run the gates

```
node app_v2/tools/provenance_lint.js     # OBS-3 — provenance honesty (exit 1 on a seed-as-real chip)
node app_v2/tools/model_check.js         # HARNESS-1 — parse 18 jsx + lint + no-shadows + no _excluded collision + 16 endpoints + served-bytes
node app_v2/tools/golden_path.js         # HARNESS-1b — boots the REAL app (headless Chromium), runs the loop + profitmix + meionet, ASSERTS the 6 cross-solver identities end-to-end (exit 1 on a violated identity)
```
HARNESS-1b is the ONLY gate that actually BOOTS the app in a browser — it caught B-16 (app-blanking) that all the static/HTTP smokes were blind to. Needs the server up + a Chromium binary (WARN+exit0 if either is absent, so CI stays green).
In-app: **Reference ▸ Model Map** — the live architecture map (OBS-1) + cross-solver consistency (OBS-2).

*Server: start via `nohup python3 app.py > /tmp/es_server.log 2>&1 & echo $! > /tmp/es_server.pid`; kill by PID. Never `pkill -f app.py` (it self-matches the launching shell).*

---

## 6 · Item (a) execution log — the 8-tab pass (started 2026-06-06)

### Tab 1/8 · **Production** — ✅ DONE (both-lens review + STEP-4 scenario)
**Domain lens surfaced the biggest bug yet, B-7 (a true shadow):**

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-7** | **`console.jsx` defined no-arg `productionPayload()` AND `montecarloPayload()` that silently SHADOWED `store.jsx`'s governed `(planning, opts)` versions.** All 18 jsx load as classic scripts into ONE global scope, and console.jsx loads *after* store.jsx (line 102 > 89) → the last declaration wins. So **every consumer got the wrong function**: `production.jsx:29` (labor-rate / shutdown / time-phasing / campaign / per-SKU routing all dropped), the **`runFullLoop` production+MC steps** (`store.jsx:1032/1038`), and **all of `scenarios.jsx`'s Risk suite** (`:237/242/343/580`). Time-phased `demand_by_period` was never sent ⇒ `projected_inventory` was never produced ⇒ **Finance EVA's working-capital base could never get real WC from the plan** (the wiring at `finance.jsx:187` was correct but starved). `params.plan_committed` was always `undefined` ⇒ "MC on committed plan" silently never engaged. No crash (console's shapes render) — *plausible-but-wrong numbers*, invisible to parse/byte/curl smokes. | **P-H** (duplicate definition) × **P-F** (governed controls inert) | **FIXED** — deleted both console twins; `ResProduce`/`ResRisk` now call store's governed versions (`usePlanning()` + `productionOptsFromConfig()`); LAB builders (`console.jsx:189/190`) now resolve to the governed globals, matching the author's own comment ("globals from store.jsx"). store.jsx is now the **sole** definer of each. |

**STEP-4 scenario verified (server up):** governed payload (`routing[]` + `changeover_matrix` minutes + `demand_by_period`) → `/api/solve/production` = **Optimal**, 6 gantt entries, `projected_inventory` **present** for both SKUs (the Finance-EVA linkage, now live), `time_phased:true` echoed. Sequencing covers all 6 FGs (`M.changeoverSkus`, the `||4-SKU` fallback is dead). Bottleneck=LINE-01 identity is a profit-mix dual → covered by OBS-2's I-2, not re-derived here.

**Hardened the gate so B-7's class can never recur:** `model_check.js` gained a **`no shared-global shadows`** HARD check — any top-level `function/const` name declared in 2+ jsx fails the build (proven to bite). Now: parse + lint + **shadow** + endpoints + bytes.

**Minor/latent, RECORDED — ✅ ALL FIXED under the Tier-3 units contract (2026-06-06, see §12):**
- ~~changeover matrix is **hours** (`data.jsx:185`) but `sequencing.py` names everything `_min` and defaults `default_min=30.0`~~ — **FIXED.** `/api/solve/sequence` now has an explicit MINUTES contract; `ProdChange` ×60 on send + ÷60 on display, so a missing pair falls back to 30 **min** (not 30 h) and `console.jsx:215`'s "X min" label is now truthful.
- ~~`₹4200/hr` setup-rate magic constant in `ProdChange` (P-G)~~ — **FIXED.** Now `saved × governed labor rate` (`config.prodLaborRate`, seed ₹120/hr) with an honest "· seed" provenance tag.
- ~~stale `||['…4 SKUs']` fallbacks (`production.jsx:520`, `store.jsx:739`)~~ — **FIXED.** Both now `|| []` (the canonical `M.changeoverSkus` is the sole source).

### Tab 2/8 · **Console** — ✅ DONE (both-lens review + STEP-5 scenario)
**STEP-5 (profit-mix glass box) verified:** `DecisionExplainer` reads the REAL duals — `r.shadow_prices` → `explainConstraint` (bottleneck/spare), `r.reduced_costs` → `explainProduct` (made/left-out), `r.crossover_analysis` → 💡 price-to-enter + a sandboxed `RecTest` re-solve. It is **translation-only and distinct from the results table** (not a dedup lie); the results card's "Binding:" line reads the *same* `shadow_prices`. Live smoke: profit-mix Optimal, `Shared Capacity` binding (dual ₹118.7/u), TPA-9904 reduced-cost −78.5 / crossover ₹1499 — all flow through faithfully. `profitmixPayload.constraints.shared_capacity` matches `specFor`'s prove-it path (wired, no bug).

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-8** | **Profit-mix seed (pre-solve) headline was a 3-way-inconsistent fabrication.** The real Σ(price−cost)·demand of the 6 FGs is **₹56.1L**, but `ResProfit` showed badge `₹6.84 Cr` (=₹684L, **12× high**), table foot `₹68.4L`, and per-row `%` denominator `6840000` — three different wrong numbers for the same total. The same wrong `₹6.84 Cr` was hardcoded again in `ResSOP`'s "Pipeline" strip (a fabricated 3-tuple with no live backing). | **P-A** (seed-as-real) + **P-G** (magic constant) | **FIXED** — `ResProfit` now derives `seedTotal` live and uses it for badge + foot + per-row %; `ResSOP` Pipeline now reads `getSolveResult(profitmix/procurement/production)` with an honest `◇ run` seed fallback + a real `seed`/`solved` provenance chip. No `₹6.84 Cr` left anywhere. |

(Not a bug: `ResProcure` badge `₹3.12 Cr` (annual landed spend) vs foot `₹11.4L` (sum of the shown seed PO rows) are different scopes and reconcile once solved.)

### Tab 3/8 · **Logistics** — ✅ DONE (both-lens review + STEP-8 scenario)
**STEP-8 (transport conservation) verified, with a framing caveat:** the live solve is Optimal, each lane picks a mode, and Σ shipped weight = Σ demand — **but conservation holds *by construction of `transportPayload`*** (it evenly splits `totalWeight / nLanes` across the network's outbound lanes), **not by an LP demand constraint.** transport.py *has* a real allocation LP (`supply ≤` / `demand ≥`, lines 225-226) but the UI never exercises it — the path it runs is **per-lane mode selection** (cheapest mode meeting each lane's SLA). The rest of the tab is genuinely solid: `LogAllocation` builds the matrix/flows from the solved shipments (illustrative literal only pre-solve), `LogSkuFlows` uses real `skuWeightKg`, `computeCoG` is a real demand-weighted centroid with a `derived` chip.

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-9** | The Allocation step was framed as a **"DC→customer assignment LP … s.t. demand met"** (kicker, step sub, Reading formula), implying an optimised allocation. Actually it is per-lane **mode** selection over a demand split the payload pre-computes — the assignment isn't optimised and "demand met" is by construction. Overclaim on a glass-box tool. | **P-A** (framing-as-more-than-it-is) | **FIXED (copy)** — kicker → "per-lane mode LP"; step sub + Reading now state "cheapest mode meeting each lane's SLA · lane volumes = the demand plan split across outbound lanes, not an assignment LP". (Wiring a real DC→customer allocation LP is a Tier-3 build, recorded, not done here.) |
| **B-10** | `LogCoG`'s `cog.mock` empty-state (no delivery nodes) showed `M.cog.saving` + "~18% km cut" as a result with **no seed marker** (the real branch correctly carries a `derived` chip). | **P-A** (seed-as-real) | **FIXED** — mock branch now carries a `seed` provenance chip. |

### Tab 4/8 · **Home** — ✅ DONE (both-lens review + first-run scenario) — **closes B-2**
**Scenario (first-run honesty) verified:** Home was restructured (R13) and **no longer renders `SolverNetwork`** — its KPI strip is derived-from-master-data (Revenue/COGS/Margin = price·demand arithmetic, labelled) + cached-solve KPIs (Plan cost/Scheduled/Mean fill/CVaR/Binding) that show **honest "—" + "run loop"** until solved, never faked. The "Solver Lifecycle" strip already reads **live** `solves`/`solveResults`/data-presence (blocked→ready→fresh→stale) with a `derived` chip. So Home passed as-is.

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-2** (the open half) | The only remaining seed-status lie was **`console.jsx`'s `SolverNetwork`** (line 52) — rendered with no `freshness`, so it coloured nodes by the seed `status` field (done/running/queued), misrepresenting which engines actually ran. (Home's copy of the graph was removed in R13, so Home never needed it — the §4C "Home + Console" item was half-moot.) | **P-A** (seed-as-real) | **FIXED & CLOSED** — extracted one shared `solverFreshnessMaps(solves, results)` builder (reference.jsx, beside `_OBS_KEY`/`_obsObj`); **both** ModelMap and Console's fabric now colour from the live cross-stage cache via that single source. Console card copy now states "colour = LIVE solve freshness", legend on Model Map. (No duplication — guarded by the new shadow check; names now 404, all unique.) |

### Tab 5/8 · **Setup** — ✅ DONE (both-lens review + STEP-1 scenario) — **clean, no new bug**
**STEP-1 (stale cascade) verified by trace:** every Setup edit routes through `setConfig` → `configTokens(patch)` → `markStale` (or `setPlanning` → `markStale('planning')`), and `markStale` walks `SOLVE_DEPS` transitively. `CONFIG_TOKEN` maps `prodLaborRate`/… → `cfg.prod`, `pmBudget`/`pmWarehouse` → `cfg.profit`, everything else → `config`; so editing service level stales procurement/policy/rolling/meio/meionet/cvar (+ profit-mix/capital as a conservative over-flag), editing a scheduler knob stales production/aggregate/linecap, etc. The **Parameter Registry** (`SetupRegistry`) is itself an honesty surface — it shows each param's live value, seed-vs-override provenance, its `SOLVE_DEPS` token, and its FEEDS, and openly documents that the broad `config` token over-stales (≥ feeds, "under-staling is the bug it refuses"). Industry templates write real tuned `config`/`planning`/`profile` (each triggering the cascade) and are honest that they retune knobs, not data. **No fix needed — the tab was already remediated and the contract holds.**

### Tab 6/8 · **Products** — ✅ DONE (both-lens review + P-B scenario) — **P-B holds**
**Scenario (per-item vs portfolio scope) verified:** the top `ScopeBanner` + every section's `scope` tag are accurate — item cards (Yield/BOM/Costs/Policy, all keyed to the selected SKU) vs global cards (Catalog of all FGs, the whole MTO order book). The BOM card makes the P-B boundary **explicit**: per-product qty edits via `editPartQty(sku, part, …)` vs shared part-master cost/lead via `editPartAttr(part, …)` ("editing them affects every FG that uses the part"). Costs roll up from the per-SKU `bomForSku` (not the shared bill) and reconcile to `p.cost` at seed (no double-count); policy is a real `/api/solve/policy` solve; MTO footer totals are derived from the rows.

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-11** | The catalog sub claimed "**every field here is editable**", but 8 of 14 columns (Family, Wt, Vol, Shelf, Yield, Lifecycle, Method) are display-only there — edited in the Yield card or derived/static. | **P-A** (overclaim) | **FIXED (copy)** — sub now names the inline-editable commercial fields and says Wt/Vol/Shelf/Yield are in the Yield card and Family/Method/Lifecycle are derived. |

### Tab 7/8 · **Scenarios** — ✅ DONE (both-lens review + STEP-10 scenario) — **clean; B-7 repairs its Risk replay**
**STEP-10 (transparent what-if) verified by trace:** `runScenario` does save → apply branch → `runFullLoop` → capture KPIs → **`finally` restore**, and the restore is byte-correct: `_snapshotForRun` deep-clones the 8 input slices **plus `solves`+`solveResults`** (the solve cache), and `appStore.replace` overwrites **only** the patched keys (starts from `{...get()}`), so the restore neither leaks the branch's solves into live nor wipes the `scenarios`/`events` slices (where the run's KPIs + audit are stored inside the try). The transparent what-ifs (`runScenario`, the WhatIf bot via `captureScenario`→`updateScenarioInputs`→`runScenario`) are isolated; the explicit-apply paths (ModelSurface CSV import, `mergeScenario`) deliberately mutate live and don't claim transparency; the multi-solve `ResilienceStress` and sensitivity tornado use **stateless `apiPost`** (no `markSolved`/`cacheSolve`) so they never pollute the live cache. **No new bug.**

**Cross-tab repair from B-7:** before the Tab-1 fix, this whole Risk suite ran console's no-arg `montecarloPayload` (no `params.plan_committed`, no per-SKU bills) — so `planned = !!(montecarloPayload(...).params.plan_committed)` (lines 237/369) was **always false** and "MC on the committed plan" silently never engaged. The B-7 fix routes these to store's governed payload, so the committed-plan replay the tab advertises now actually happens. (The only remaining limit is **B-5**: a *capacity* what-if can't be byte-restored because `prodArch` lives in global `M`, not an appStore slice — recorded, blocks SF-7, no scenarios.jsx what-if exercises it.)

### Tab 8/8 · **Reference** — ✅ DONE (both-lens review + truthfulness scenario)
**Scenario (Model Map + API catalog truthful) verified:** all 16 `_OBS_API` endpoints exist in the live route map (cross-checked vs `/api/meta/solvers`; the B-4 reconcile→`/api/solve/sop` fix holds), and `RefAPI` introspects the live Flask `url_map` (`apiGet('/api/meta/solvers')`, `external` provenance) so it **can't drift** from the real routes.

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-12** | The Model Map mislabeled two of its own nodes. `allocation` & `consolidate` are **transport sub-steps** (fam `optimize`, `go:logistics`, edges `transport→{allocation,consolidate}`, both rendered off the single `/api/solve/transport` solve in Logistics) — but `_OBS_KEY` (→`meio`/`meionet`), `_OBS_API` (→`/api/solve/meio` / `/api/solve/meio-network`), `_OBS_METHOD` (→Graves–Willems MEIO / √-law pooling), and `_obsObj` (→`total_safety_stock_value` / `total_capital_freed`) all described them as the **inventory MEIO** solvers. So the observability map — the very thing built to stop the machine lying about itself — lied about two nodes (wrong endpoint, wrong named method, wrong objective, wrong freshness key). | **P-A / endpoint-drift** (same class as B-4) | **FIXED across all four maps** — `allocation`/`consolidate` now key to the `transport` solve, point at `/api/solve/transport`, describe the transport LP allocation + LTL→FTL consolidation, and show `n_shipments` lanes / `consolidation_saving` from the real transport result. `ConsistencyPanel`'s pooling identity reads `meionet` directly, so it's unaffected. |

---

## 7 · Item (a) — pass complete (8/8 tabs) · roll-up

All eight tabs reviewed (domain + design) with one solid scenario each; the pass found **7 new bugs (B-2 closed, B-7…B-12)** — every one a *truthfulness/scope* defect, the exact class the wedge depends on:

| Finding | Tab | Pattern | Severity | Status |
|---|---|---|---|---|
| **B-7** | Production/Console | P-H shadow + P-F inert | **severe** (core solve path) | fixed + gated |
| **B-8** | Console | P-A/P-G seed-as-real | medium | fixed |
| **B-9** | Logistics | P-A framing overclaim | medium | fixed (copy) |
| **B-10** | Logistics | P-A seed-as-real | low | fixed |
| **B-2** | Home/Console | P-A seed-as-real | medium | **closed** |
| **B-11** | Products | P-A overclaim | low | fixed (copy) |
| **B-12** | Reference | endpoint/method drift | medium | fixed |

Setup, Scenarios passed clean (no new bug). The **gate was hardened** mid-pass with a `no shared-global shadows` check (caught/prevents the B-7 class permanently). **Every fix is frontend/docs, gates green (5/5 with server), still uncommitted.**

**Remaining:** none open in §4C. The Tier-3 units contract (Production changeover hrs-vs-`_min`, `₹4200/hr`) — the LAST open §4C item — is **DONE under HARNESS-1b's net (see §12)**. **HARNESS-2 is BUILT — see §8. B-5 CLOSED + SF-7 promoted — see §9. B-3 CLOSED (all 4 solvers now cache) + B-15 fixed — see §10. HARNESS-1b BUILT + B-16 (app-blanking) found+fixed + static guard added — see §11. Tier-3 units contract closed — see §12.**

---

## 8 · HARNESS-2 — disruption sub-flow runner ✅ BUILT (2026-06-06)

`SubflowHarness` (scenarios.jsx, rendered in `ScnScenarios` after the What-If bot) — the **behavioral** complement to HARNESS-1's static parse/endpoint check. Each sub-flow: solve the live base once → clone it → perturb **one** real lever in the clone's input snapshot → `runScenario` (full loop; live byte-restored after) → assert the KPI **direction** vs base → delete the clone. Verdicts are honest: **PASS** (moved as expected) · **FLAT** (didn't move ≥½% — a wiring smell) · **FAIL** (wrong way — a model bug) · **ERR** (threw / KPI absent).

**Honesty guard:** the harness churns 5 throwaway scenarios per run, so capture/run/delete were given a **`quiet`** flag (store.jsx, default-off → existing callers unchanged) that suppresses the `scenario_*` audit events — otherwise every self-test would have inflated the **ValueLedger's** "scenarios explored / re-plans" ROI counters (a self-inflicted truthfulness defect). The harness logs ONE `harness_run` event (not counted by the ledger).

**The build immediately found two real bugs** the static gate could never see (this is the point of a behavioral test):

| # | Finding | Pattern | Status |
|---|---|---|---|
| **B-13** | **The aggregate S&OP plan ignored committed demand.** `_loopAggregatePayload` built each product's `forecast` from the **static seed master** `p.demand ×` the seed month-envelope (`M.aggregate.months`), while procurement (`getItemDemand`) and production (`getItemDemand`) both read the **committed** demand slice. So a demand edit/what-if (SF-1, SF-5, *and* the existing What-If bot's demand lever) silently **never moved plan cost** — and the Model Map's own term table (`data.jsx`) documents `forecast ← "Demand → committed series", wired:true`, so the contract was a **lie**. | **P-E / twin-source-unreconciled** (master vs committed) | **FIXED** — the aggregate now consumes `getItemDemand(p.sku, periods)` whenever that SKU's slice is committed, falling back to the seed-seasonality reslice only when uncommitted ⇒ **baseline plan byte-identical**, but demand now actually drives the S&OP plan. Empirically: SF-1 (4471+3215 ×1.4) → planCost **+27.5%**, SF-5 (all ×0.6) → **−36.8%**. |
| **B-14** | **`procCost` was always null.** `_captureKpis` read `pc.total`, but `procurement.py` returns the spend as **`total_cost`** — so the B-6 "procCost added" groundwork was non-functional: every cost/FX sub-flow (and the What-If bot's cost delta) silently got `null`. | **P-?  wrong field key** (a quiet null) | **FIXED** — `procCost: pc.total_cost ?? pc.total ?? null`. Empirically: SF-4 (landed +20%) → procCost **+7.2%**, SF-2 (USD/₹ +5, imported RM-BRG18) → **+0.76%** (above the ½% ε ⇒ PASS, not FLAT). |

**Verification:** static gate **5/5** (parse 18 jsx + provenance lint + no-shadows / **410 names unique** + shell-bytes + 16 endpoints); a live-solver direction smoke confirmed **all 4 sub-flows PASS** with the right magnitudes and signs (above). 3 sub-flows are listed as **honest coverage gaps** in the card itself: SF-7 capacity loss (B-5 — `prodArch` not in the snapshot), SF-3 supplier aging (finance-only, no loop KPI), SF-6 lead-time stretch (run via Risk ▸ stress). All frontend/store/docs, **still uncommitted**.

---

## 9 · B-5 CLOSED — `prodArch` is now a first-class scenario lever · SF-7 promoted (2026-06-06)

**The gap.** The scenario engine's snapshot envelope (`_SCN_INPUT_KEYS` → `_snapshotSlices`) only ever read **appStore** slices. But the editable **lines / stages / changeover matrix live in the global production master `window.M`** (mutated via `bumpMaster()`, staled via `markStale('prodArch')`), *not* an appStore slice. So the envelope was blind to them: a **capacity what-if silently no-op'd and could not be byte-restored** — exactly why SF-7 was a coverage gap, and why `SOLVE_DEPS` could list `prodArch` as a dependency that the scenario engine could never actually vary.

**The fix (store.jsx).** `prodArch` is now mirrored in/out of `window.M` alongside the slice snapshot, peeled off so it routes to the master and never pollutes appStore:

| Piece | What it does |
|---|---|
| `_snapshotProdArch()` | deep-clone `{ lines, changeover }` out of `window.M` (each line's `stages[]` ride inside the clone) |
| `_restoreProdArch(pa)` | write them back to `window.M` + `bumpMaster()` (notify; does **not** mark solves stale) |
| `_applyEnvelope(env)` | the new single apply path — `{ prodArch, ...slices }` → `_restoreSlices(slices)` (appStore) **+** `_restoreProdArch(prodArch)` (master) |
| `_snapshotForRun()` | now returns `{ ...slices, solves, solveResults, prodArch }` — the live-restore envelope carries the master too |
| `captureScenario` | `inputs` now include `prodArch: _snapshotProdArch()` |
| `runScenario` / `applyScenario` | call `_applyEnvelope(...)` in place of bare `_restoreSlices(...)` — so a capacity branch actually switches the master AND the `finally` byte-restores it |

Old persisted scenarios (no `inputs.prodArch`) degrade safely: `_restoreProdArch(undefined)` is a no-op on apply, and the live restore always snapshots a fresh `prodArch`, so the master is byte-restored regardless. The 4 existing sub-flows are unaffected — their transforms touch only demand/sourcing/config and leave the now-present `inp.prodArch` at its unperturbed baseline.

**SF-7 promoted from gap → runnable.** Lever `prodArch.lines[].cap ×0.1`, KPI `lineShadowMax`, dir ↑.

> **Why the deep (×0.1) cut, stated honestly in the card:** with routing present, the per-line **units `cap` field is dead to the production MILP** — `production.py:_route_cap` sizes capacity off **OEE × hours / cycle**, and the demand constraint is a hard `Σ ≥ req`, so a moderate cap cut leaves `prodUnits` pinned at demand (FLAT) until it goes infeasible. The solver that *does* read `M.lines[].cap` is **linecap** (`linecapPayload` → the continuous capacity-dual LP, which never goes infeasible — `short` absorbs unmet). At real TPAC volumes every line is **honestly slack** (`π_l = 0`), so SF-7 cuts deep to cross into the **binding** regime — this is a **wiring** assertion (does the prodArch lever reach linecap, B-5), not a claim that ₹0 was wrong.

**Verified (live linecap solve):**

| | status | `lineShadowMax` | binding | unmet |
|---|---|---|---|---|
| baseline (seed caps) | Optimal | **₹0** | 0/3 | 0 |
| perturbed (caps ×0.1) | Optimal | **₹730** | 3/3 | 470 u |

→ **SF-7 PASS (₹0 → ₹730, dir up).** Per-line at the cut: L-01 cap124/load124 π₹660 · L-02 cap198/load198 π₹368 · L-03 cap88/load88 π₹730 — all binding. Static gate **5/5** (**413** top-level names unique = the 410 + exactly the 3 new store fns, no collision). The harness card now runs **5 sub-flows**, with **2 honest coverage gaps left** (SF-3 finance-only, SF-6 risk-coupled). All frontend/store/docs, **still uncommitted**.

---

## 10 · B-3 CLOSED — the last 4 consequential solvers now persist to the cross-stage cache · B-15 fixed (2026-06-06)

**The gap (B-3).** Only **6 of 16** solvers (`forecast, procurement, aggregate, production, linecap, montecarlo`) wrote their result to the cross-stage cache (`solveResults[key]`). Four more were **already in `SOLVE_DEPS` and `_OBS_KEY`** — so the machinery expected them — but their tabs ran `useSolve` **without** a `solveKey`, so `cacheSolve` never fired. Net effect: **profitmix / transport / capital** showed perpetually dark on the model map (`getSolveResult` → null) and OBS-2's binding-line-dual ↔ profit-mix-dual cross-check could never light (the panel even carried a literal `'profit-mix not in cache … give it a solveKey to cross-check'` fallback, written anticipating this). **meionet** was half-wired: it already called `markSolved('meionet')` (clearing the stale flag → map said *fresh*) but never cached the **result**, so the pooling cross-check stayed dark while the node lied green.

**The fix — pure call-site wiring (zero backend, zero store-mechanism change).** The established three-part idiom (as in plan/production/sourcing) is `useSolve(ep, payload, { solveKey })` (hydrate + cache on run) · `useStale(key)` · `run = ()=> x.run().then(d=>{ markSolved(key); return d; })` (clear the stale flag). Both halves are needed: `solveKey`→`cacheSolve` persists the **result**; `markSolved`→clears the **stale flag**. Applied at all 5 sites:

| Solver | Site(s) | Change |
|---|---|---|
| `profitmix` | console `ResProfit` | + `solveKey:'profitmix'` + `runPm` wrapper (kept the stateless `_solveProfit` RecTest sandbox **keyless** on purpose) |
| `transport` | console `ResTransport` **and** logistics `StageLogistics` | + `solveKey:'transport'` + `runTr` wrapper on **both** — they **share** the key, so a run on either tab lights the map for both |
| `capital` | console `ResCapital` | + `solveKey:'capital'` + `runCap` wrapper |
| `meionet` | sourcing `SrcMEIONet` | + `solveKey:'meionet'` **only** — its `markSolved`+`useStale` were already there; it just never cached |

None of the 4 is upstream of any other solve (`SOLVE_DEPS` lists none of them as a dependency), so `markSolved`'s downstream `markStale` cascade is a deliberate no-op — no risk of staling the loop. Hydration-on-mount (LP-C) is now a bonus: revisit Console/Logistics and the last optimized result shows without a re-run.

**B-15 (found *because* B-3 lit the node — the truthfulness payoff).** Lighting the capital node exposed a latent **field-name mismatch**: `capital.py` returns the portfolio NPV as **`total_npv`** at top level, but the map's `_obsObj` read **`r.npv`** (only present per-investment) → the node would have shown `'ran'` with no number. Same class as B-14 (`procCost`/`total_cost`). Fixed `_obsObj` to read `r.total_npv`. Live smoke confirmed `total_npv` present at top level, `npv` `None`.

**Verified.** Static gate **5/5** (parse 18 jsx · no shared-global shadows **413** unique · provenance lint · app shell 5322 B · 16 endpoints). Live field-contract smoke of all 4 — the exact headline fields the now-lit consumers read are present in real responses: `capital.total_npv` ✓ · `profitmix.total_profit` + `shadow_prices[]` ✓ · `transport.total_cost` (₹50,418 on a 2-lane probe) ✓ · `meio-network.total_ss_value_pooled 3629 < _decentralised 4745, _capital_freed 1116` (OBS-2 reads 'ok') ✓. The map's untracked list is now honestly down to the 5 genuinely local-only engines (disaggregate · reconcile · sequencing · lot-sizing · capital-capacity). All frontend/docs, **still uncommitted**.

---

## 11 · HARNESS-1b — the end-to-end golden-path identity gate · found+fixed B-16 (app-blanking) · 2026-06-06

**What it is.** `app_v2/tools/golden_path.js` — the end-to-end check HARNESS-1 explicitly deferred ("a pure-CI golden-path that replays them needs payload fixtures captured from the app"). It is the FIRST gate that actually **boots the app in a real browser**. Using the installed Playwright, it launches headless Chromium, loads `index_v2.html` (all 18 jsx transpiled live by babel-standalone), and then drives the **REAL app code** — `window.runFullLoop` (forecast→procurement→aggregate→production→linecap→montecarlo) + the two builders the loop skips (`profitmixPayload` for I-2, `meioNetworkPayload` for I-6) — against the LIVE solvers, then reads the real cross-stage cache and **asserts** the cross-solver identities OBS-2 only *displays* passively.

**Why a browser, not a node payload-rebuild (the honesty point — [[verification-depth-honesty]]).** The identities only mean something if the payloads are EXACTLY what the UI sends. Those builders read `window.M` + the live appStore + a web of helpers; rebuilding them in node would be a *reconstruction* that can drift = "a fake check dressed as a real one." Driving the real app is the only genuinely **observed** end-to-end check. Nothing is paraphrased.

**The honest pass-conditions (a naive harness gets two WRONG):**
| Identity | Asserted | The trap avoided |
|---|---|---|
| **I-5** demand ⇄ production | Σ committed demand vs Σ build, ratio∈[0.7,1.4] | — (mirrors ConsistencyPanel exactly) |
| **B-13** aggregate uses committed | `_loopAggregatePayload.forecast == getItemDemand` per SKU | catches a silent regression back to the seed master |
| **I-3** carry ⇄ hurdle | `carryRate == finBlendedHurdle().wacc + spread` | pure arithmetic via the real fns |
| **#5** MC on committed plan | `mc.ranAt ≥ prod.ranAt` AND `policy_simulated=='plan'` | the timing check alone misses B-7 (replay not engaging); assert the POLICY |
| **I-2** bottleneck priced | profit-mix yields a binding dual (`pmMax>0`); linecap dual finite | **NOT `lcMax>0`** — at TPAC volumes lines are honestly slack (π=0); requiring it would falsely FAIL the baseline (SF-7 lesson) |
| **I-6** pooling dividend | `pooled < decentralised` AND `freed>0` | — |

**The build immediately found a SEV-1 the static gate was blind to (the point of a real boot — same payoff pattern as HARNESS-2→B-13/B-14):**

**B-16 — the whole app was BLANK at runtime.** The B-5 fix (§9) had added `const { prodArch, ...slices } = env` in `_applyEnvelope`. Babel-standalone hoists a top-level `const _excluded` helper per file for object-REST destructuring, and **lib.jsx (Box/Btn) is the sole sanctioned emitter** — a documented convention (console.jsx:897 literally warns about it and uses `Object.assign`+`delete` to avoid a 2nd). The store.jsx emitter collided in the shared global scope (`Identifier '_excluded' already declared`) → **store.jsx never executed** → `appStore`/`useStore`/`runFullLoop` undefined → every tab dead (`<PipelineRibbon>`: "useStore is not defined"). It survived **every** prior check because parse, the provenance lint, the shadow check, curl and served-bytes **none boot the app**; HARNESS-1b's first real-browser run surfaced it instantly. **Fix:** rewrote `_applyEnvelope` with `Object.assign`+`delete` (the documented pattern) — app boots with **0 page errors**.

**The institutional fix — close the blind spot at the static gate too.** Added a HARD AST check to HARNESS-1 (`one object-rest _excluded emitter`): it walks each jsx AST for `ObjectPattern`+`RestElement` (so object-*spread* `{...x}` in a literal is correctly NOT flagged) and FAILs if >1 file emits `_excluded`. **Proven to bite** (a scratch 2nd emitter → `2 files emit … BLANKS the app`, exit 1; removed → PASS). This catches the B-16 class WITHOUT needing a browser — the cheap complement to HARNESS-1b's runtime boot.

**Verified.**
- HARNESS-1b: **9/9 PASS, deterministic across re-runs** (server up + Chromium). Real observed numbers: chain 6/6 steps · I-5 committed 2,660u vs build 2,799u (1.05) · B-13 all 6 SKUs match committed · I-3 carry 23.95% = 11.15% + 12.8% · #5 `policy='plan'` after the schedule (B-7 replay confirmed LIVE, not just reasoned) · I-2 profit-mix dual ₹114/u binds [Min-prod TPA-9904/TPA-5540, Shared Capacity] while linecap honestly slack (0/3) · I-6 pooled ₹3,495 < decentralised ₹5,930, freed ₹2,435.
- HARNESS-1 (with the new guard): **6/6** (parse · lint · no-shadows 413 · **one _excluded emitter (only lib.jsx)** · shell 5322 B · 16 endpoints).

**The lesson, recorded.** This is the concrete proof of the verification-depth concern ([[verification-depth-honesty]]): a SEV-1 *app-blanking* regression lived in the tree because the entire verification suite was static-parse + HTTP, **never an actual boot**. observed ≫ sampled ≫ reasoned. HARNESS-1b is now the standing observed-grade gate; Tier-3 should be done under it (re-run after each change). All frontend/tools/docs, **still uncommitted**.

---

## 12 · Tier-3 units contract — ✅ DONE (2026-06-06, under HARNESS-1b's net)

The LAST open §4C item. The `§4C` line bundled three labels but two were already
closed: **P-B** (scope declaration) held for every Products card in Tab 6/8, and
**P-E**'s concrete twin-source instance was fixed as **B-13** (aggregate master-vs-committed).
So the genuine remainder was the **units contract (P-C/D)** on the changeover path.

**The bug class — a unit boundary that was self-consistent in *display* but a latent
landmine.** `M.changeover` is authored in **hours** (`data.jsx`), and the two consumers
of it disagreed on the unit they sent across the API:
- `store.subMatrix` → `/api/solve/production` already ×60 → **minutes** (correct, matches `production.py`).
- `ProdChange` → `/api/solve/sequence` sent **raw hours**, while `sequencing.py` names
  every field `*_min` and defaults `default_min=30.0`. Display was self-consistent
  (hours in → labeled "hrs" out), so no *live* error on a full matrix — **but**:
  (i) a missing pair injected **30 h** (≈15–25× a real changeover), and
  (ii) `console.jsx:215` printed `"changeover {total_changeover_min} min"` over a value
  that was actually **hours** — a small but real truthfulness bug on a glass-box tool.

**The contract, made explicit.** One declared unit at each layer:
- **UI = hours** (human-authored matrix, "editable · setup hrs").
- **API (`/api/solve/sequence`) = minutes** — matches the `*_min` field names, matches
  `production.py` and `store.subMatrix`, and makes `default_min=30` a sane 30-**minute**
  fallback instead of 30 hours.
- `ProdChange` converts **×60 on send, ÷60 on display**. `console.jsx:215`'s "min" label
  is now truthful for free (the value really is minutes).

**Fixes (all frontend + a backend docstring; zero solver-logic change):**
| Item | Where | Change |
|---|---|---|
| P-C/D units | `production.jsx` `ProdChange` (~525) | matrix `×60` on send; `total/saving_min ÷60` on display; comment states the contract |
| P-C/D doc | `sequencing.py` `evaluate_line` docstring | declares the MINUTES contract + that hours-callers must ×60; `default_min=30` is 30 min |
| P-G magic const | `production.jsx:584` | `saved × 4200` → `saved × config.prodLaborRate` (seed ₹120/hr) + honest "· seed" tag |
| stale fallback | `production.jsx:520`, `store.jsx:739` | `||['…4 SKUs']` → `|| []` (canonical `M.changeoverSkus` is the sole source) |

**Note on the rate.** The `₹4200/hr` was an ungoverned fabrication 35× the governed
₹120/hr labor rate; a saved setup hour is now priced at the **governed labor rate**
(overridable, with a "seed" chip) rather than a hidden magic constant. This intentionally
lowers the displayed ₹ saving — the honest direction (a planner who wants a fully-loaded
rate raises `prodLaborRate`). No new state key was added (reuses the existing governed rate).

**Verified.**
- Live sequence smoke (server up): a minutes payload (`72/60/48/54/96/84`) → optimal path
  `TPA-3215→TPA-4471→TPA-9904`, `total_changeover_min = 108` → ÷60 = **1.8 hrs** (matches the
  hand-computed minimum). The endpoint genuinely speaks minutes now.
- **HARNESS-1b: 9/9 PASS** after the edits — the app still **boots** (the B-16 net held; the
  store.jsx/production.jsx changes introduced no `_excluded` regression) and all 6 cross-solver
  identities still hold (sequence is post-solve sharpening, not in the identity loop, so the
  change was identity-neutral by construction — and the harness *confirmed* it observed).
- **HARNESS-1: 6/6** (parse · lint · no-shadows · one `_excluded` emitter · shell · endpoints).

All frontend/tools/docs + one backend docstring, **still uncommitted**.

---

## 13 · NEXT (proposed) — full-path / UI-driven verification (the user's ask)

> **UPDATE 2026-06-06 — the 3 gaps below are now folded into a single living master:
> [`GOLDEN_JOURNEY_SPEC.md`](GOLDEN_JOURNEY_SPEC.md).** After the user clarified that the
> verification spec and their *domain* brain-dump ("extra recs": SKU labels, weights, line-share,
> landed cost, MTO/MTS, machine-vs-work hours, yield, safety stock, transport) should be **one
> testable file, not a separate prose deep-dive**, I built that master. It walks every tab in
> journey order with a 4-part block — **Journey** (incl. horizon basis = Gap 2) · **Assertions**
> (the checks the harness runs = Gaps 2+3) · **Concept notes** · **Gap backlog** (the domain
> recommendations, `BUILD → then assert`). 9 sections written, **32 assert-now + 28 build-then-assert**
> items, all code-grounded. Gap 2's horizon-contract table + Gap 3's all-16 coverage are the
> "Horizon contract" + "Execution plan" sections there. **The 3-gap decomposition below is still
> the correct execution order; the master is where it now lives.** What remains is *executing* it
> (Layer A headless assertions into `golden_path.js`, then Layer B clicks). See §14.

After Tier-3 the user asked for "**a entirety path fully mapped with ui clicks** … like
api calc for **calendar feeds every section** and they all follow and **plan for the horizon
period explicitly** … in the order one after the other **all apis** work, **solvers also not
just via the golden path** … everything else also has to be verified." Decomposed — these are
**three distinct gaps** (often conflated, but each needs a different tool), on top of the 4
existing gates (provenance_lint · HARNESS-1 static · HARNESS-1b boot+identities · HARNESS-2 behavioral):

**Gap 1 — UI-driven journey (real DOM clicks).** HARNESS-1b *boots* the app but calls the
builders directly in `page.evaluate` — it never clicks a button or navigates a tab. The
true "first-time user walks the whole path" test drives the real DOM **in order**: Setup
(set horizon + calendar) → Demand (forecast → commit) → Plan → Production (press ⚡ Sequence /
Schedule) → Console (profit-mix) → Sourcing → Logistics → Risk → Finance, asserting each tab
**mounts with no runtime error** and each primary solve button **produces a result**. This is
the real superset of HARNESS-1b. **Cost:** the app has **no stable selectors** (`data-testid`)
today — robust clicking needs them added across all tabs. That app-wide change is the real price
of Gap 1 (and should itself be done under HARNESS-1b's net).

**Gap 2 — Horizon / calendar consistency (a 7th cross-solver identity).** The single governed
`planning.horizonLength` + the calendar (`/api/calc/calendar` → `plant_calendar.build_calendar`:
work-days → net hrs → capacity) should flow to every solve, and each solver should plan for a
**declared** horizon basis. **Reality today (grep'd):** production/procurement/linecap/MC run a
**~13-wk fence** (`productionScheduleHorizon` = clamp(horizonLength, 4, **13**) — the 13 is a
hardcoded near-magic cap), aggregate runs **12 months**, forecast runs `horizonFor(grain)`, policy
runs **6**. Correct modeling (schedule fence ≠ S&OP plan ≠ forecast horizon) but **implicit**.
Make it explicit: a **horizon-contract table** (solver → basis → period-count → source) + an
assertion in golden_path that each solver's `periods` equals what its **declared** basis derives
from the governed inputs — **no hidden constants** (govern the 13). This is the cheapest, highest-
truth item and directly answers "plan for the horizon period explicitly." It lives in the existing
boot harness — **no DOM clicking required**.

**Gap 3 — Full solver coverage (all 16, dependency order).** HARNESS-1b exercises **8** solvers
(forecast/procurement/aggregate/production/linecap/montecarlo + profitmix + meionet). The other
**8** (disaggregate, sequence, lotsizing, transport, meio, cvar, capital, capital-capacity, sop)
are only **registration**-checked (HARNESS-1) or ad-hoc smoked. Extend the boot harness to call
**each** solver's faithful UI builder once, in SOLVE_DEPS topological order, asserting
`{valid status + the consumer-read field present}` (the B-14/B-15 field-contract class — exactly
where past bugs hid). Same harness, no clicking.

**Recommended order (cheap-high-truth → expensive-brittle):** **Gap 2** (horizon identity, ~½ day,
pins down the question raised) → **Gap 3** (all-16 field-contract coverage, ~½ day, same file) →
**Gap 1** (UI clicks — needs `data-testid` across all tabs first; the big one). All under
HARNESS-1b's net. **Now lives in [`GOLDEN_JOURNEY_SPEC.md`](GOLDEN_JOURNEY_SPEC.md) — see §14.**

---

## 14 · GOLDEN_JOURNEY_SPEC.md — the integrated journey+audit master (BUILT 2026-06-06)

The deliverable for the user's "extra recs" domain review + the 3-gap verification plan, **fused
into one testable file** (their call: an audit that never becomes an assertion rots). Per tab:
Journey · Assertions (run by the harness) · Concept notes · Gap backlog (`BUILD → then assert`).

**Headline findings from the code-grounded pass (observed, file:line in the spec):**
- **Demand is the most complete tab** — real calendar dates (`futureLabel`), MTS/MTO split, NPI behind
  Advanced, promo wiring are **already done**. The one real gap: **pure-MTO flow** (a firm-order-only
  SKU has empty `demand[sku]` → production/procurement fall back to seed; MTO only floors profit-mix).
- **Landed cost ≠ ordering cost — and the app gets it right** (the user's sharpest question). Landed
  cost feeds the per-unit purchase/holding terms; the fixed per-PO `S` is separate. Gaps: the detailed
  FOB→gate build-up is one worked example (MILP uses a flat `dutyFreightPct`), and one builder
  **hardcodes `ordering_cost:120`** vs the master `S` — verify which is live.
- **Machine-hrs vs work-hrs** — both *are* defined per stage (`m`/`w`/`ct`/`oee`/`cap`); the real gap is
  (a) machine-hours not shown as an explicit figure, (b) the **schedule has no labor *capacity*
  constraint** (labor is priced, not capped) — the worker-bound capacity lives only in aggregate.
- **Scheduled receipts genuinely absent** — MRP nets only against Network on-hand (a real MRP gap).
- **No single-product profit-mix gate** — confirmed; with 1 SKU the mix optimiser still renders.
- **Yield is a typed seed**, not measured from confirmations; **safety stock from service level is built**
  (`/api/solve/policy`); multi-**echelon** pooling exists (`meio`/`meio-network`), multi-**site** does not.
- **Transport is outbound-only**; inbound RM freight lives in Sourcing — intentional but implicit.
- Corrected an earlier overstatement: the **hands-on % editor already exists** (Plan step 0b).

**Status:** **ALL 12 TABS DEEP-DIVED** (Setup·Products·Network·Demand·Sourcing·Plan·Production·Profit-mix·
Inventory·Logistics·Finance·Console·Scenarios·Reference) + horizon-contract table + execution plan; **14
sections, 54 assert-now + 39 build-then-assert, 472 lines.** Added beyond the first 9: **Setup** (the
calendar/horizon root — found the banner *overclaims* "whole app re-buckets" vs the per-solver clamps =
the horizon contract; profile already gates profit-mix off the profile answer, not SKU count), **Network**
(multi-site *data* is real — nodes/lanes/per-node on-hand; multi-site *SS optimisation* is the gap;
storage capacity per-node but not per-class), **Finance** (mostly solved; Cash&WC honestly flagged seed;
EVA ops↔finance prune loop; FX single-source), **Console** (the glass-box wedge — DecisionExplainer/RecTest
real-dual + prove-it; live freshness not seed), **Scenarios** (MC-on-committed-plan; honest seed-vs-solved;
ValueLedger identified-vs-accepted; HARNESS-2), **Reference** (ModelMap/ConsistencyPanel = OBS-1/2; RefAPI
introspects url_map). **The user's sequencing: finish ALL tab deep-dives → FIX the gaps → THEN run the
end-to-end tests** (testing a half-mapped app would encode today's gaps as "passing"). Deep-dive phase
**COMPLETE**; next = **fix the `Gn` backlog** (frontend-only under the harness net), then execute Layer-A
(`An` assertions into `golden_path.js`) + Layer-B clicks. **All uncommitted.**
