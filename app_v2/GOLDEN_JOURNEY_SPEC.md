# app_v2 — Golden Journey + Horizon Contract + Audit (THE testable master)

**This is the one big file.** It is the *spine the harness tests against*. It walks the app in the order a planner actually uses it — **Setup → Products → Network → Demand → Plan/S&OP → Production → Sourcing → Logistics → Finance → Console → Scenarios** — and for every tab records four things:

1. **Journey** — preconditions (what must be solved first) · user inputs (and format) · api/solver fired (in dependency order) · postconditions (state that must now exist) · **horizon basis** (period count + where it comes from). *Testable.*
2. **Assertions** — concrete pass/fail checks about what the app does **today**, including the cross-solver + horizon identities and the "logical-flaw" checks from the domain review. *Executed by the harness (Layer A headless / Layer B clicks).*
3. **Concept notes** — short prose where a term needs explaining (worker-weight, ABC routing, landed cost, EVA…), so the file is self-teaching.
4. **Gap backlog** — recommendations that **change** the model/UX. You can't test a recommendation, so each is `BUILD → then assert`: when built, it graduates into a new Assertion.

> **Why one file, not a separate "deep-dive".** An audit that never becomes an assertion rots ([[verification-depth-honesty]]: reasoned ≪ observed). Folding the domain review into the journey spec means every concern is either a check that runs or a backlog item that *becomes* a check. Nothing is left as prose-only opinion.
>
> **Companion:** `OBSERVABILITY_MAP_AND_RESEARCH_SPEC.md` is the static *architecture map* (16 solvers, routes, lineage). This file is the *dynamic* layer: the journey, the tests, and the gap backlog. **Anchor asset:** `M.solverModel` ([data.jsx:674-781](data.jsx#L674-L781)) already declares, per solver, every term's input `src` + `wired:true/false` + `extras` (modelled capability with **no input surface**) — half the "is this wired?" answers are read straight off it.
>
> **Status:** authored 2026-06-06 from the user's domain brain-dump ("extra recs"). Products tab full; other tabs seeded with the captured concerns; horizon-contract + execution plan at the end. **Nothing here changes runtime by itself.** Uncommitted.

---

## Legend

`✅ handled` · `⚠️ partial` · `❌ gap` · `🟫 narrative-only` (exists in a story, no computed effect) · `🐛 latent bug`.
Assertion ids: `Jn` journey-step, `An` assert-now, `Gn` gap (build→assert). `(reasoned)` = inferred, not yet read off code.

## Tab spine & the canonical solve order

Nav order ([data.jsx:14-28](data.jsx#L14-L28)): Setup·Products·Network · Demand·Plan·Production·Sourcing·Logistics · Finance·Console·Scenarios · Reference.
Canonical re-plan loop `runFullLoop` ([store.jsx:1029-1077](store.jsx#L1029-L1077)): **forecast → procurement → aggregate → production → linecap → montecarlo**, chained on one dataset, each `cacheSolve`'d + `markSolved`.
Dependency graph `SOLVE_DEPS` ([store.jsx:1383-1397](store.jsx#L1383-L1397)) is the precondition source of truth (e.g. `montecarlo:['demand','procurement','production','sourcing']` ⇒ MC is meaningless until production is fresh).

---

# Tab 01 — Setup (identity · calendar · profile · governance)

`StageSetup` ([setup.jsx:6](setup.jsx#L6)) — the root every other tab depends on: **1** Company Identity (+ derived MSME tier) · **★** Industry Quick-Start templates · **2** Planning Profile (gates the spine) · **3** Planning Calendar (the one clock) · **4** Parameter Governance (the registry). Engine: `/api/calc/calendar` → `plant_calendar.build_calendar`.

> **This is your "api calc for calendar feeds every section" root.** The calendar *is* defined here and the period axis genuinely propagates — but the banner **overclaims** that every solver plans to this horizon (they clamp to their own bases). That gap is the global horizon contract.

### Journey
- **J-pre:** none — Setup is the entry point.
- **J-in (user):** company identity (currency, tax regime, **service level**, plant state); **grain** (day/week/month), **horizonLength**, **startDate**, **workDaysPerWeek**, **frozen/slushy weeks**, custom holidays; the **6 profile answers** (makePolicy, capacity, imports, lines, distribution, externalForecast).
- **J-api:** `/api/calc/calendar` (work_days_per_week, holidays, start_month, year, state, custom_holidays) → `total_working_days`, `total_holidays` → **net hours → capacity basis**. Auto-recomputes on any input change ([setup.jsx:224-228](setup.jsx#L224-L228)).
- **J-post:** `planning.{timeGrain,horizonLength,startDate,…}` + `config.{currency,serviceLevel,plantState,…}` + `profile.{…}` set; `calendar.result` cached; `M.calendar.start` is the anchor `futureLabel`/all period axes step from.
- **J-horizon:** **this is where the single governed knobs live** (`planning.horizonLength`, grain, startDate). Everything downstream *should* derive from here — see the global horizon contract for where it actually does vs clamps.

### Concept notes
- **The "one clock"** — grain + horizon + startDate define a single period axis; `horizonRange` computes the true date window ([setup.jsx:195-206](setup.jsx#L195-L206)), and the calendar yields working-days → net hours → capacity. **But "renders this same horizon" means the period *axis*, not each solver's *planning depth*** — forecast runs `horizonFor(grain)`, production a 13-wk fence, aggregate 12 months. The axis re-buckets; the solver horizons don't all equal `horizonLength`.
- **Profile gating = progressive disclosure** — `M.profileGate(profile)` turns whole capabilities on/off so a new user never sees all 16 engines. The card states it: *"Pure-MTO + ample capacity hides Profit-mix; one line hides Sequencing; single-site hides Transport"* ([setup.jsx:380](setup.jsx#L380)). So profit-mix **already gates** — but off the *profile answer*, not the actual SKU count (see G-SU2).
- **Frozen / slushy weeks** — the re-plan fence: frozen = no-change, slushy = change-with-approval → the production MPS frozen fence + the rolling re-plan nervousness (`/api/solve/rolling`).
- **MSME tier is derived** (from plant & machinery, [setup.jsx:64](setup.jsx#L64)), not chosen — honest.
- **Parameter Registry** (step 4) — every governed input in one ledger with its live value, **seed-vs-override provenance**, its **SOLVE_DEPS token**, and exactly what re-solves when changed ([setup.jsx:420-421](setup.jsx#L420-L421)). This is the governance backbone the whole "glass-box" wedge rests on.

### Assertions (test now)
- **A1** calendar propagation: changing `horizonLength`/grain/`startDate` re-buckets the period axis app-wide (the `futureLabel` anchor + the banner's `horizonRange` both move; the "stuck on seed periods" bug stays fixed).
- **A2** calendar solve: `/api/calc/calendar` returns `total_working_days` consistent with `workDaysPerWeek` × weeks − holidays; net hours feed the line/aggregate capacity basis.
- **A3** profile gate: setting `makePolicy='MTO'` + ample capacity sets `profileGate.profitmix` true → the Profit-mix capability is hidden (a `GateNote`, not an empty grid).
- **A4** governance: every row in the Parameter Registry traces to a live value + a SOLVE_DEPS token + a seed/override chip (no ungoverned magic constant in the registry).

### Gap backlog (build → then assert)
- **G-SU1 (horizon overclaim ↔ contract):** the calendar banner says the whole app re-buckets to `horizonLength`, but production/procurement/linecap/MC clamp to the hardcoded **13-wk fence**, aggregate to 12 mo, forecast to `horizonFor(grain)`. **Govern the 13** (`config.productionScheduleWeeks`) and **show each solver's declared basis** beside the calendar so the claim is true/legible. *This is the global horizon contract — the single highest-value fix.* *Then assert:* each solver's `periods` == its declared basis derived from `horizonLength`+grain.
- **G-SU2 (auto single-product gate):** gating is driven by the *profile answer*, not the real portfolio — a one-SKU model with `makePolicy='MTS'` still shows Profit-mix. Auto-suggest hiding/c­ollapsing Profit-mix when `finished.length===1` (refines Profit-mix G-PM1). *Then assert:* 1-SKU portfolio nudges the profile / collapses the mix optimiser.

---

# Tab 02 — Products / SKU master

`M.products` ([data.jsx:39-48](data.jsx#L39-L48)): `{sku,name,cat,demand,mape,sl,shelf,abc,xyz,price,cost,line,cycle,oee,yield,moq}`. UI: `ProdDefine` (catalog) → `ProdYieldExpiry` → `ProdBOM` → `ProdCosts` → `ProdPolicy` → `ProdMTO`, under `ItemSelector` + `ScopeBanner` ([products.jsx:7-27](products.jsx#L7-L27)).

### Journey
- **J-pre:** Setup calendar built (grain + `horizonLength`) — Products needs the horizon to gate expiry and size the policy demand series.
- **J-in (user):** per-FG catalog (name, make/buy, mode MTS/MTO/ATO, price, target %, **annual demand seed**); per-item **yield % / shelf-days / salvage %**; per-item **BOM qty-per**; **setup + labour** cost; lot/MOQ. *Format:* numeric inline cells; demand seed is a scalar/yr (real series comes from Demand).
- **J-api:** `/api/solve/policy` (per-item (s,S)/(R,Q)), on demand ([products.jsx:271-277](products.jsx#L271-L277)).
- **J-post:** every Finished SKU has non-empty `bomForSku`; `policy.result` cached per item.
- **J-horizon:** `T = planning.horizonLength` (default 52 wk) used for the policy demand series length and the shelf<horizon expiry gate ([products.jsx:113, 269](products.jsx#L113)). No separate solver fence. **Source = Setup calendar.**

### Assertions (test now)
- **A1** every `cat==='Finished'` SKU has a non-empty `bomForSku(sku)` — no FG with an empty bill. *(guards the SR-1 class.)*
- **A2** `bomForSku(sku)` is the per-SKU **subset**, not the master bill: assert `TPA-4471` excludes `CN-BLT04` (Grade-10.9 bolt) and `TPA-7722` includes its real parts. *(the no-mixing check.)*
- **A3** **horizon propagation:** the policy payload's `demand.length === planning.horizonLength` and `periods === planning.horizonLength`.
- **A4** **expiry honesty:** the rendered expiry flag `== (ceil(shelf/7) < horizonLength)` for each SKU.
- **A5** **method routing:** `itemMethod(sku) === (abc!=='A' && xyz!=='X' ? 'autopilot' : 'optimized')` for all SKUs ([data.jsx:785-787](data.jsx#L785-L787)).
- **A6** **scope clarity (Layer B):** every item-scoped card title contains the selected SKU code; `ScopeBanner` present; `scope` tag = `item|global` on each section.

### Concept notes
- **Two different "weights"** (the question conflates them):
  - **Physical kg** — `skuWeightKg`, "Wt kg" column ([products.jsx:84](products.jsx#L84)) → Logistics tonnage + Network storage. De-duplicated to one source on purpose ([products.jsx:35-37](products.jsx#L35-L37)).
  - **Worker-time weight** — `skuWorkerMin = cycle × skuLaborFrac` normalised to the demand-weighted mean ([store.jsx:885-897](store.jsx#L885-L897)). **This is the "0.733".** The aggregate plan is workforce-bound (`P ≤ rate·workers`); a unit of a highly-automated SKU (`skuLaborFrac=0.2`, worker only loads/unloads) burns less *worker* time than a fully-manual one (`1.0`). So each SKU's labour load is weighted; aggregate inventory/capacity is in **labour-weighted units** (why 1,124 labour-wtd ≠ 1,260 physical). Default `1.0` ⇒ raw cycle.
- **ABC/XYZ has teeth** — it's the routing switch (A5), surfaced as `MethodTag`. But the classes are **typed seeds**, not computed.
- **EVA-destroyer is real compute** — `EvaPruneBranch`→`scenarioPruneSkus` zeroes a SKU's demand and re-runs the loop ([finance.jsx:204-234](finance.jsx#L204-L234)); a negative-EVA tail SKU can be **load-bearing on a shared line**, so pruning can *raise* cost. The *word* "destroyer" is narrative; the surfaced thing is an EVA number + prune button.
- **"runner / tail"** — 🟫 narrative shorthand for A-class-high-vol / C-class-low-vol. No separate state.

### Gap backlog (build → then assert)
- **G1** Derive **ABC** from `Σ price·demand` Pareto and **XYZ** from `mape`/demand-CV; write as override-able default; show the Pareto curve. *Then assert:* derived class matches Pareto buckets. **Where:** Demand tab (its subtitle already claims ABC/XYZ, [data.jsx:17](data.jsx#L17)); Catalog shows it read-only + override.
- **G2** Disambiguate the two weights. The hands-on % editor **already exists** (Plan step 0b `PlanLaborContent`, [plan.jsx:190-214](plan.jsx#L190-L214)) → so this is *not* "build an editor", it's: (a) label the catalog column **"Wt kg (ship)"** so physical weight ≠ labour load, and (b) optionally **mirror** the hands-on % beside cycle time in Production (it's a per-operation attribute that pairs with cycle). *Then assert:* worker-weight reacts to the Plan 0b field. **Where:** Catalog label + Production cycle card.
- **G3** **SKU→Line(s)** editor with **multi-line eligibility** (today `line` is a single string — can't express "runs on LINE-01 *and* LINE-03") + a **pre-solve guard** "SKU X has no eligible line → unscheduled". *Then assert:* no Finished SKU is absent from every line's `lineSkus`. **Where:** Production routing; show a line chip in the Catalog.
- **G4** Global **Parts Master + where-used** (one row per part → shared cost/lead/MOQ/supplier + the FGs that consume it). Edit a part → see blast radius. **Where:** Network or a Products "Parts" view.
- **G5** Per-SKU **storage class** (ambient/cold/hazmat) + **per-class** warehouse cap (today profit-mix `pmWarehouse` pools all space — a category error if conditions differ). **Where:** Products attr + Network/Setup cap.
- **G6** **Sticky** selected-item identity (pin "Editing TPA-4471" to the viewport) + **banded** global-vs-item layout so a co-scrolling global card is never mistaken for the item. Pure layout.

### Scorecard
| # | concern | verdict | core gap |
|---|---|---|---|
| labels | runner/tail/EVA/ABC | ✅ impact · ⚠️ assignment | ABC/XYZ typed, not derived (G1) |
| weights | two "weights" | ⚠️ partial | conflated word, buried `skuLaborFrac` (G2) |
| line-share | how to define | ⚠️/🐛 | no SKU→line editor, single-line, no guard (G3) |
| parts/SKU | per-SKU bill | ✅ | no global parts master (G4) |
| shelf/storage | per product | ⚠️ | storage capacity pooled across classes (G5) |
| which item | scope clarity | ✅ mostly | global/item co-scroll (G6) |

---

# Tab 03 — Network (nodes · lanes · contracts · on-hand)

`StageNetwork` ([network.jsx:7](network.jsx#L7)) — the physical master, defined **after** products: **A** per-item Flow (inbound/outbound lanes) · **B** Nodes (geo + capacity) · contracts + supplier master · **E** Opening On-Hand. No solver of its own — it *feeds* transport, landed cost, Plan opening stock, MRP, and storage utilisation.

> **This is where your multi-location and storage questions actually live.** Multi-site *data* is real here; multi-site *optimisation* is the gap.

### Journey
- **J-pre:** Products exist (lanes + on-hand are per-item).
- **J-in (user):** **nodes** (type plant/wh/dc/customer/supplier, geo lat/lng, `capacity` + `capacityUom`); **per-item lanes** (`direction` inbound/outbound, from→to, mode, ₹rate, lead time, **trunk capacity** = units/vehicle); **time-varying contracts** (`rateByPeriod`); **on-hand** matrix (item × location, qty, uom).
- **J-post:** `network.{nodes,lanes,contracts,onHand}` set → consumed downstream (no direct solve).

### Concept notes
- **Multi-site data exists** — a real directed topology (supplier→plant→wh→dc→customer), parallel outbound lanes (WH→DC-BLR and WH→DC-PUN), and **per-item on-hand at each node** ([network.jsx:27-80](network.jsx#L27-L80)). So the *data model* is already multi-location; what's missing is multi-site *SS optimisation* (where-to-stock, lateral transshipment) — see G-N2.
- **Inbound vs outbound both defined here** (refines §8 Logistics): inbound part lanes feed the plant + the landed-cost build-up; outbound FG lanes feed the transport LP. Per-lane **trunk capacity** feeds shipment consolidation.
- **Node storage capacity** — per node, in its own uom (m³), with **derived** utilisation = Σ(on-hand × `skuVolM3`) ÷ node cube ([network.jsx:126-133](network.jsx#L126-L133)) — replaced a hardcoded 62/74/48%. ✅ But there is no **per-storage-class** capacity (cold/ambient/hazmat) — the §1.5 category error.
- **Time-varying contracts** — `rateByPeriod` (steel steps ₹142→₹151 at W29); the procurement MILP times buys around the step.

### Assertions (test now)
- **A1** storage util derived: each node's utilisation == Σ(on-hand × `skuVolM3`) ÷ `node.capacity` (not a constant).
- **A2** on-hand propagation: `network.onHand` feeds Plan opening inventory (labor-weighted) **and** the MRP net-requirement on Sourcing.
- **A3** lane wiring: outbound lanes feed the transport `cost_matrix`; inbound lanes + contract `rateByPeriod` feed landed cost / procurement.

### Gap backlog (build → then assert)
- **G-N1 (scheduled receipts):** on-hand exists, **scheduled receipts don't** (open POs / in-transit) — MRP nets only against on-hand. *(Same gap as Production G-P5; the input belongs here: `network.scheduledReceipts[item][period]`.)*
- **G-N2 (multi-site SS):** the node-level on-hand hooks exist, but safety stock isn't optimised **across sites** (the (s,S) engine + `meio` are single-chain; `meio-network` pools across *products*). True where-to-stock / lateral transshipment is the next inventory frontier (recorded, §7 G-I3).
- **G-N3 (storage class):** per-node capacity exists; **per-storage-class** capacity does not — wire a SKU storage-class attribute (§1.5 G5) to a per-class node cap.

---

# Tab 04 — Demand

`StageDemand` ([demand.jsx:59](demand.jsx#L59)) — 7 steps under a global **grain toggle** (day/week/month) + a 🤖 **Run-Forecast** button: **1** Ingestion (`DemHistory`) · **1b** Import + NPI (`DemImport`) · **2** Forecast + Override (`DemForecast`/`OverrideCard`) · **3** Actuals + Sensing (`DemActuals`) · **4** Model Competition (`DemModels`) · **5** Segmentation (`DemSegment`) · **6** Promotions + Calendar (`DemEvents`) · **7** Committed + Consensus (`DemCommit`). Engine: `/api/forecast` (+ `/api/demand/sense`).

> **Headline: this is the most complete tab in the app — most of the brain-dump's Demand worries are already solved.** The real residual is *pure-MTO flow* (G-D1). Real dates, the MTS/MTO split, NPI placement, and promo wiring are done.

### Journey
- **J-pre:** Setup calendar (start date + grain); Products catalog (each SKU has a seed annual demand as the fallback).
- **J-in (user — four entry modes):** (1) **CSV/TSV import** — per-product *or* a unified multi-SKU `sku,date,value` dump, delimiter/header/long-vs-wide auto-detected, bucketed by date to the grain (`DemImport` step 1b, **the wired main path**); (2) **manual override grid** (`DemHistory` step 1) — **explicitly NOT wired**, a read-only preview of the last 12 committed values ([demand.jsx:165](demand.jsx#L165)); (3) **external forecast** — bypasses the competition, set in Setup → Planning Profile; (4) **NPI like-model** — analog × scale × ramp (behind `Advanced`). Plus per-period **override**, **promo flags**, **holidays**, **actuals**.
- **J-api order:** `/api/forecast` (model competition per SKU) → winner written to committed via `setItemDemand` → `markStale('demand')` cascades; `/api/demand/sense` (actuals → blended) → explicit commit. Unlocks procurement/aggregate/profitmix (all `SOLVE_DEPS:['demand',…]`).
- **J-post:** `demand[sku]` working series exists; `isDemandCommitted(sku)` true only once an explicit commit/override/accept event lands (a bare auto-forecast stays "proposed").
- **J-horizon:** forecast runs on **`M.horizonFor(grain)` = 30 (daily) / 13 (weekly) / 12 (monthly)** ([data.jsx:858](data.jsx#L858), [demand.jsx:1010](demand.jsx#L1010)) — **NOT** `planning.horizonLength`. A deliberate non-uniformity (forecast horizon ≠ planning horizon) that is currently **implicit/untested** → A1.

### Assertions (test now)
- **A1** horizon basis: a forecast run returns exactly `horizonFor(grain)` periods (30/13/12) and tracks the grain toggle.
- **A2** commit propagation (B-13 class): after forecast, the winner series is in `demand[sku]` and `getItemDemand(sku)` returns it (not the seed) — a demand what-if must move planCost.
- **A3** commit-provenance honesty: the committed chip == `COMMIT_PROV[lastEvent.type]` (override→`input`, npi→`derived`, actuals→`external`, forecast/replan→`solved`) — never unconditionally "solved" ([demand.jsx:518](demand.jsx#L518)).
- **A4** real dates: every forecast/promo period label == `futureLabel(grain,k)` = a true date stepped from `M.calendar.start` (month-aware for monthly), not "P1/01" ([demand.jsx:997-1004](demand.jsx#L997-L1004)).
- **A5** promo→forecast wiring: a flagged promo enters `fcPayload.promo_periods`; re-running re-forecasts; uplift attribution renders **only** when an ML model wins (honest empty for a classical winner).
- **A6** MTS/MTO split: the consensus table sums `demand[sku]` (MTS) and `Σ firm orders` (MTO) as **separate** columns ([demand.jsx:577-595](demand.jsx#L577-L595)).

### Concept notes
- **Where demand actually comes from** — *not* "paste into the grid". The manual grid is an honest **preview** ("Manual cell editing isn't wired yet"); you paste into the **CSV importer (1b)**, which auto-detects shape and buckets by date. The catalog `demand` scalar is only the **seed fallback** until a real series is committed.
- **MTS vs MTO flow to *different* solvers** — MTS (the statistical forecast → committed series) is what the **production/procurement MILPs read**. MTO (firm orders, `status==='firm'`) is the **profit-mix floor** (`min_quantity`). The consensus table shows them side by side but they are not the same pipe — see G-D1.
- **NPI is already de-prioritised** — behind an `Advanced` collapsible ([demand.jsx:1189](demand.jsx#L1189)) "so the default view stays the one common path". Your "NPI shouldn't always hover" ask is **already implemented**.
- **Real calendar dates everywhere it matters** — `futureLabel` produces "01 Jun '26" stepped from the calendar start, month-aware for monthly grain ([demand.jsx:997-1004](demand.jsx#L997-L1004)). The "01,02,03" fear does not apply to the forecast/promo tables.
- **Promo lift is real but model-gated and not auto** — flagging a promo writes the flag but does **not** auto-re-run; you press 🤖 again. Only ML/DL winners carry the promo regressor; a classical winner ⇒ lift can't be attributed (stated, not silently zeroed). Actuals-sensing *does* auto-re-sense on change (debounced, DM-C) — promo flagging does not.
- **Grain selection vs drill-down** — the grain toggle gives **grain-only** views (week-only or day-only across the whole horizon) ✅; it does **not** give hierarchical click-drill (month→weeks→days) — see G-D2.

### Gap backlog (build → then assert)
- **G-D1 (pure-MTO flow — the real gap):** a pure-MTO SKU (firm orders, no forecast) has an **empty `demand[sku]`** → production/procurement fall back to the **seed**, not the order book; only profit-mix sees the firm floor. Decide the model — total demand = MTS forecast **+** MTO firm, or MTO ⊂ MTS? — then wire firm orders into (or explicitly net against) the committed series. *Then assert:* a pure-MTO SKU's firm qty reaches the production schedule.
- **G-D2 (hierarchical calendar drill-down):** grain is a **global toggle** — no click-drill (click a month → expand its weeks → expand its days). Add expandable period rows. *(grain-only views and real dates already work.)*
- **G-D3 (label consistency):** the **actuals grid** and **manual override grid** label columns "W-6…W-1" (offsets), inconsistent with the forecast table's real dates. Use `futureLabel`/a past-label everywhere.
- **G-D4 (calendar source unification):** `futureLabel` anchors to `M.calendar.start`; assert it equals `planning.startDate` (Setup) so promo/forecast dates can't drift from the governed calendar.
- **G-D5 (promo co-location):** promo lives in step 6 (below the fold) yet drives the step-2 forecast. Surface a "+ add promotion" affordance beside the forecast chart so cause/effect is co-located — keep it opt-in (it already is a discrete card, not always-expanded).

---

# Tab 07 — Sourcing / landed cost

Sourcing supplies the **RM cost side** of procurement: per-part origin + duty/freight uplift, the FOB→plant-gate landed-cost build-up, incoterms, stepwise inbound freight, and the procurement/policy/rolling/MEIO solves. The procurement objective ([data.jsx:699-700](data.jsx#L699-L700)) is *"minimise setup + FG holding + production + expiry + shortage + **RM purchase** + **RM holding** + **RM ordering**"* — note RM purchase, RM holding and RM ordering are **three separate terms**.

> **Headline: the landed-cost-vs-ordering-cost question has a clean answer, and the app gets it right.** They are different things and are kept separate. The residual gaps are accuracy (coarse % vs detailed build-up) and one hardcoded constant.

### Journey
- **J-pre:** Products BOM (`bomForSku`) + committed demand (Demand). Setup FX table (`config.fxRates`) for imported parts.
- **J-in (user):** per-part `sourcing[part] = {imported, dutyFreightPct, unitsPerTruck, costPerTruck}` ([store.jsx:506](store.jsx#L506)); the governed **FX rate** (`config.fxRates.USD`); service level + carry rate (solver params). The detailed landed-cost inputs (FOB/freight/BCD/SWS/IGST/CHA) are today a **worked example seed** (`LANDED_INPUTS`, [sourcing.jsx:634](sourcing.jsx#L634)), explicitly badged "not your specific part".
- **J-api order:** `/api/calc/landed-cost` (illustrative build-up) · `/api/solve/procurement` (buy plan MILP) · `/api/solve/policy` ((s,S)/(R,Q)) · `/api/solve/rolling` (re-plan nervousness) · `/api/solve/meio` + `/api/solve/meio-network` (multi-echelon SS + pooling) · `/api/solve/cvar`.
- **J-post:** buy plan + per-part policy cached; `procurement` solve fresh ⇒ unblocks `montecarlo`.
- **J-horizon:** procurement runs on the **schedule fence** (`clamp(horizonLength,4,13)`), same basis as production/linecap/MC — see the global horizon contract.

### Concept notes
- **Landed cost ≠ ordering cost (the key clarification).** *Landed cost* = the all-in **unit purchase price** to get a part to the plant gate: FOB × FX + freight + insurance + customs duty (BCD+SWS) + clearing (CHA) + inland, with **IGST recoverable as ITC** (so `net_landed` is *net of* the recoverable tax — the correct planning value). *Ordering cost `S`* = the **fixed administrative ₹ per purchase order** (raising/receiving/inspection) that drives EOQ batch size. **Big organisations use landed cost as the unit acquisition price** (it feeds the purchase-cost and holding-cost terms), **not** as the ordering cost. The app matches this: `effLandedCost` feeds `landed_cost` (per-unit) while `S`/`ordering_cost` is a separate per-PO field. **Your instinct to question it was right; the conflation it warns against doesn't exist here.**
- **Where a tariff flows.** A dutiable part (`imported:true`, `dutyFreightPct>0`) → `effLandedCost = cost × (1+pct/100) × fxFactor` ([store.jsx:545-547](store.jsx#L545-L547)) → raises the part's **purchase price** *and* its **holding cost** (carry × landed value) in the MILP — but **not** its ordering cost `S`. That is the correct flow.
- **FX is governed, singular** — `effLandedCost` × `fxFactor = currentRate ÷ baseRate` from `config.fxRates` (SS-D), so editing the one FX table re-prices every imported part; at seed FX the factor is 1.

### Assertions (test now)
- **A1** duty flows to price not S: flipping `sourcing[part].imported`/raising `dutyFreightPct` raises `effLandedCost` (and the MILP's `landed_cost`) but leaves `ordering_cost`/`S` unchanged.
- **A2** FX propagation: editing `config.fxRates.USD` moves every imported part's `effLandedCost` via `fxFactor`; domestic parts (factor on `imported:false`) are unmoved.
- **A3** ITC honesty: the planning landed value is `net_landed` (net of recoverable IGST), not gross — assert `net_landed = landed − itc_recovery`.
- **A4** gating: with a no-imports profile, `gate.landed` hides the whole landed/FX/incoterm section ([sourcing.jsx:669-672](sourcing.jsx#L669-L672)).

### Gap backlog (build → then assert)
- **G-S1 (per-part detailed landed cost):** the rich FOB→plant-gate build-up (`/api/calc/landed-cost`) is a **single worked example**; the MILP actually plans against the **coarse flat `dutyFreightPct`** (seed 12%). Wire a per-part import-inputs card (FOB, HS/BCD/SWS, freight) so each imported part's `effLandedCost` uses its *accurate* build-up, not a flat %. *Then assert:* per-part landed cost reconciles to its detailed rollup.
- **G-S2 (hardcoded ordering cost):** one payload builder uses `ordering_cost:120` for all parts ([store.jsx:589](store.jsx#L589)) while the master carries real per-part `S` (1200/900/140/…). Verify which builder feeds the live `/api/solve/procurement` and unify on the master `S` (a wrong-but-constant ordering cost mis-sizes every EOQ). *Then assert:* the live procurement payload's `ordering_cost[part] == master S[part]`.
- **G-S3 (origin/HS master):** add an explicit per-part **country-of-origin + HS code** attribute (today only a boolean `imported` + a flat %), feeding both the duty calc and supplier/FX concentration caps (procurement `extras` lists those as unwired).

---

# Tab 05 — Plan / S&OP

`StagePlan` ([plan.jsx:45](plan.jsx#L45)) — **ONE pooled aggregate plan across the whole finished portfolio**, pooled by **worker-time**, with steps **0** Cost inputs · **0b** Labor content · **1** Strategy · **2** Capacity & Duals · **3** Workforce · **4** Disaggregation · **5** Gap to target. Engine: `/api/solve/aggregate` (Hax–Meal LP) → `/api/calc/disaggregate` → `/api/solve/sop` (reconcile). Objective ([data.jsx:727](data.jsx#L727)): *minimise regular + overtime + holding + backorder + hire + fire + wage*.

### Journey
- **J-pre:** committed demand (Demand). Line registry (Production) → workforce ceiling. Network FG on-hand → opening stock.
- **J-in (user):** `config.planParams` — `rate_per_worker`, reg/holding/backorder cost, hire/fire/wage, `init_workforce`, `min/max_workforce`, `max_ot_pct`, `allow_backorder` ([plan.jsx:127-189](plan.jsx#L127-L189)); per-SKU **hands-on %** (step 0b); opening FG inventory (auto-reconciled, override-able).
- **J-api order:** `/api/solve/aggregate` → `/api/calc/disaggregate` (family→SKU) → `/api/solve/sop` (top-down⇄bottom-up reconcile).
- **J-post:** aggregate plan (per-period production/OT/inventory/workforce + duals) cached.
- **J-horizon:** aggregate runs **12 monthly buckets** (or max forecast length), [aggregate.py:86](aggregate.py#L86) — distinct from the 13-wk schedule fence. The S&OP plan ≠ the schedule, deliberately.

### What S&OP actually hands you (the question, answered)
- **What to build & whether to go to overtime** — step 1 `PlanStrategy` (level vs chase + the seasonal prebuild it implies); step 3 `PlanWorkforce` lays out **hire / fire / overtime by period and the capacity gap each fills** ([plan.jsx:116](plan.jsx#L116)). OT *units* are surfaced per period; OT *cost* is in the objective.
- **What other constraints it outputs** — step 2 `PlanCapacity` shows demand vs the **line-registry ceiling** and the **labor dual vs the binding line** (the ₹ shadow price of a worker-hour); workforce balance `W=W₋₁+H−F`; `max_workforce` bounded by `Σ line cap ÷ rate` so the plan can never exceed the physical line ceiling (PL-1).

### Assertions (test now)
- **A1** opening-stock reconciliation: `init_inventory` (blank) == labor-weighted Network FG on-hand (`planOpeningInv`), and the headline distinguishes *physical* vs *labor-weighted* (the "conversion not reduction" honesty, [plan.jsx:177](plan.jsx#L177)).
- **A2** workforce ceiling: `max_workforce == round(Σ line cap ÷ rate_per_worker)` — plan can't exceed the line registry.
- **A3** labor-weight wiring: editing a SKU's hands-on % (step 0b) changes `aggLaborWeights` → the aggregate `labor_hours_per_unit` (a demand what-if and an automation what-if both move the plan).
- **A4** OT cap: overtime per period ≤ `max_ot_pct × regular capacity`.

### Concept notes
- **Worker-time pooling** (the §1.2 concept, here is where it's edited and consumed): the plan sizes *people*, so each SKU's demand is weighted by worker-minutes (`cycle × hands-on %`), not machine cycle. Step 0b is the editor; the aggregate constraint `P ≤ rate × workers` is what makes it bite.
- **Budgets deliberately simple** — a budget-constrained S&OP is explicitly deferred (your call). The hooks exist (`config.pmBudget`, `config.procBudget`, `config.finCapexBudget`) on the *other* solvers.

### Gap backlog (build → then assert)
- **G-P1 (OT cost laid out in ₹):** surface the overtime *rupee* cost per period beside the OT units (today the ₹ is inside the objective, not itemised in `PlanWorkforce`). *Then assert:* OT ₹ == OT units × rate × OT premium.
- **G-P2 (end-cover / safety-stock floor):** aggregate `extras` lists *"safety-stock / ending-inventory floor"* as set-a-target-to-enable; wire a service-driven ending-inventory floor so the plan doesn't run stock to zero at horizon end. (Ties to §7.)

---

# Tab 06 — Production

`StageProduction` ([production.jsx:11](production.jsx#L11)) — sub-tabs **arch · cycle · sched · change**. `ProdArch` = editable line→stage→machine tree; line capacity = slowest stage (`min(stage)` enforced, not typed). Engine: `/api/solve/production` (scheduling MILP) → `/api/solve/sequence` (changeover ATSP). Objective ([data.jsx:714](data.jsx#L714)): *minimise setup + overtime + makespan penalty + FG holding*.

### Journey
- **J-pre:** committed demand; the line/stage tree; (profit-mix mix, if multi-product).
- **J-in (user):** per **stage**: `m` machines, `w` workers, `ct` cycle (min), `oee`, `cap` (u/mo) ([production.jsx:194-198](production.jsx#L194-L198)); per **line**: name, OEE, shifts; per **SKU**: cycle + line route (`config.prodRouting`, step cycle); **ProdParams** (labor rate, holding/unit, campaign-min-run, shutdown %, time-phased).
- **J-api:** `/api/solve/production` (payload: lines with `capacity` u/wk, `oee`, `workers_per_shift`, `shifts_per_day`, per-line changeover sub-matrix; params `periods`, `hrs_per_period`, `hours_per_shift`, `labor_cost_mode`, `holding_cost_per_unit`, `campaign_min_run`, `shutdown_threshold_pct`, [store.jsx:759-766](store.jsx#L759-L766)).
- **J-post:** time-phased `gantt[]` + projected inventory → MPS/ATP/capacity-loading; feeds `montecarlo` (replays the gantt, policy='plan') and Finance EVA capital base.
- **J-horizon:** **schedule fence** `clamp(horizonLength,4,13)` weeks (the hardcoded **13**), with a calendar-aware **day drill inside the frozen fence**.

### Machine-hours vs work-hours (the question, precisely)
**Both are defined — but consumed by different solvers, and labor in the schedule is a *cost*, not a *capacity*.**
- **Machine side:** per stage `m` machines, `ct` cycle, `oee`, and a derived `cap` (u/mo); line cap = slowest stage. So machine *throughput* is fully modelled — but expressed as **u/mo capacity**, not as an explicit **machine-hours-available** figure (machines × shifts × hrs × OEE).
- **Worker side:** per stage `w` workers + `workers_per_shift` + `shifts_per_day` go into the production payload, but only to **price** labor (`labor_cost_mode='hourly'`, `hourly_rate` → OT cost). There is **no worker-hour *capacity* constraint** in the schedule (no headcount cap) — so production can't detect that *people*, not machines, are the bottleneck. That capacity question lives only in the **aggregate** plan (worker-bound).
- **Confirmed unwired** ([data.jsx:725](data.jsx#L725)): *salaried-vs-hourly mode, headcount/OT caps, shared-stage ids, parallelism, planned maintenance.*

So: the split (aggregate = people sizing, production = machine scheduling) is sound, but (a) machine-hours aren't shown as an explicit figure distinct from worker-hours, and (b) the schedule has no labor *capacity* limit.

### Assertions (test now)
- **A1** bottleneck rule: `line.cap == min(stage.cap)` for every line (derived, not typed, [production.jsx:212](production.jsx#L212)).
- **A2** routing wiring: editing `config.prodRouting[sku].cycle`/`.line` re-pins the SKU and re-prices throughput in the next solve (PR-B).
- **A3** schedule fence: production `periods == clamp(horizonLength,4,13)` — the horizon contract.
- **A4** units contract (Tier-3, done): changeover sent to `/api/solve/sequence` in **minutes** (×60), displayed in **hours** (÷60); `cap` is u/mo→u/wk (÷4.33).

### Gap backlog (build → then assert)
- **G-P3 (machine-hours figure):** surface **available machine-hours per line/period** (`m × shifts × hrs × OEE`) as an explicit number beside the u/mo capacity, so machine-hours and work-hours are both legible.
- **G-P4 (labor capacity in the schedule):** add an optional **headcount / OT-hour cap** to the production MILP (the unwired `extras`), so the schedule can be labor-constrained, not just machine-constrained.
- **G-P5 (scheduled receipts):** **MRP nets only against on-hand — there are no scheduled receipts** (open POs / in-transit due to arrive). Add a `network.scheduledReceipts[item][period]` input so net-requirement = demand − on-hand − scheduled receipts. *Then assert:* a scheduled receipt reduces the planned buy. **A real MRP gap.**
- **G-P6 (schedule ← profit-mix mix):** make explicit whether the schedule builds the profit-mix-chosen mix (multi-product) or just meets demand; today production hard-meets committed demand (`Σ ≥ req`) and profit-mix is a separate console solve — wire/declare the link.

---

# Profit-mix (Console · `ResProfit`)

`/api/solve/profitmix` — a **true LP** (continuous q[k], x[k,l]) maximising contribution margin, emitting **shadow prices + reduced costs + crossover** ([data.jsx:650](data.jsx#L650), [data.jsx:685-698](data.jsx#L685-L698)). The glass-box (DecisionExplainer/RecTest).

### Inputs required (`solverModel.profitmix`)
price, variable cost, demand ceiling (committed forecast), capacity hrs (Production cycle/line hours), material availability (BOM/yield), MTO floor (firm orders → `min_quantity`), optional budget (`config.pmBudget`), optional warehouse (`config.pmWarehouse`). All `wired:true` except the `extras` (dedicated/fixed-open line economics, shelf_life, salvage).

### Assertions (test now)
- **A1** binding-dual identity (already in golden_path I-2): a binding constraint has `shadow_price>0`; the crossover price is where a dropped SKU enters.
- **A2** MTO floor: `q[k] ≥ Σ firm orders[k]` — profit-mix can't drop a contracted SKU to zero (the `ProdMTO` floor).

### Gap backlog (build → then assert)
- **G-PM1 (single-product gating):** there is **no gate** — with one Finished SKU there is no *mix*, yet the profit-mix UI still renders (trivially: make to the binding constraint). Gate it off / collapse to a "single-product capacity check" when `finished.length === 1`. *Then assert:* 1-SKU portfolio hides the mix optimiser. **Your single-product point — confirmed missing.**

---

# Cross-cut — Inventory / yield / safety stock

Not a single tab: inventory policy is **derived** in Products (`ProdPolicy` → `/api/solve/policy`) and Sourcing (`policy`, `meio`, `meio-network`, `cvar`); on-hand is master data in Network. Yield is a per-SKU attribute in Products.

### What's built
- **Safety stock from service level ✅** — `/api/solve/policy` sizes `SS = z·σ_LTD`, `s = μ_LT + SS`, `S = s + EOQ`, per part, with `z` from `config.serviceLevel` ([products.jsx:294](products.jsx#L294)). A single-location, per-part (s,S)/(R,Q) engine — exactly the "I set a service level, build me the safety stock" ask.
- **Variability source** — flat-demand seed ⇒ σ=0 (honest: SS≈0); real σ comes from forecast holdout error (DM-A P10–P90 band) → feeds CVaR and the SS multiplier from demand-sensing.
- **Multi-echelon ✅ (vertical)** — `meio` (Graves–Willems guaranteed-service placement over the RM→WIP→FG assembly tree) + `meio-network` (square-root-law pooling across the **real subset** of SKUs sharing a part, with a pairwise ρ correlation matrix so correlated SKUs pool poorly, [sourcing.jsx:110-161](sourcing.jsx#L110-L161)).

### Concept notes
- **Yield definition (the honesty point)** — yield is a **typed seed** per SKU (0.92–0.98, [data.jsx:40-45](data.jsx#L40-L45)), editable, driving `effective_qty = qty·(1+scrap)/yield`. You're right that "assume a number" is weak: real shops compute **rolling yield from production confirmations** (good ÷ started) and feed it back. Per-part **conversion scrap** is a separate typed lever. Neither is currently *measured* — they're planning assumptions.
- **Why yield ≠ safety stock** — yield grosses up *how much you must start/buy* (a deterministic multiplier); safety stock covers *demand/supply variability* (a stochastic buffer from σ and service level). Both exist and are separate — they are not substitutes (a common confusion).
- **Single vs multi-location** — the (s,S) engine and `meio` are **single-plant** (one echelon chain). `meio-network` pools across *products*, not across *geographic sites*. True multi-**site** SS (DC1/DC2 pooling, lateral transshipment, where-to-stock) is the materially harder problem.

### Assertions (test now)
- **A1** SS climbs with service: raising `config.serviceLevel` raises `z` and every part's `safety_stock` (re-derive `/api/solve/policy`).
- **A2** pooling dividend: `meio-network` pooled SS < Σ decentralised SS (square-root law), and correlated SKUs pool less (ρ matrix wired).
- **A3** yield gross-up: raising a SKU's yield lowers procurement `effective_qty` for its parts.

### Gap backlog (build → then assert)
- **G-I1 (measured yield):** add an **actual good/started feedback** (rolling yield from production confirmations) that updates the planning yield, so it's measured not assumed. *Then assert:* a confirmation batch moves the SKU's yield.
- **G-I2 (ABC-differentiated service):** today `config.serviceLevel` is **one global number**; differentiate by ABC (A=98%, C=90%) — ties to §1.1 G1. *Then assert:* per-class z differs.
- **G-I3 (multi-site SS — record only):** geographic multi-location pooling / lateral transshipment / where-to-stock is **not modelled** and is deliberately out of scope now; recorded as the next inventory frontier (single-location is the stated assumption). Network already holds multiple nodes' on-hand — the hook exists.

---

# Tab 08 — Logistics / Transportation

`StageLogistics` ([logistics.jsx:7](logistics.jsx#L7)) — **transport optimisation OUTPUT** (nodes/lanes/contracts are master data in Network 03). Steps: **1** Allocation (per-lane mode LP) · **2** Consolidation (LTL→FTL) · **3** Center of Gravity. Engine: `/api/solve/transport` (min-cost flow), `/api/solve/consolidate`. Objective ([data.jsx:740](data.jsx#L740)): *minimise Σ lane-cost × shipment*.

### Inbound vs outbound (the question, answered)
- **Outbound (FG → customer): Logistics.** The transport LP prices **outbound** shipments only — "over {n} **outbound** shipments", lanes = the demand plan split across outbound lanes ([logistics.jsx:139-141](logistics.jsx#L139-L141)).
- **Inbound (supplier → plant): Sourcing.** Inbound RM movement is the landed-cost build-up + the **stepwise inbound freight** (`freightSteps` = ⌈qty/unitsPerTruck⌉ × costPerTruck, [store.jsx:552](store.jsx#L552)).
- So both directions exist but live in **different tabs**, and `solverModel.transport.extras` states it explicitly: *"import duty priced UPSTREAM in Sourcing — outbound FG lanes are domestic."* The split is intentional, not a gap — but it's **implicit**; a planner could miss that inbound freight is in Sourcing.

### Units of measure
- **Mass:** per-SKU **kg/unit** (`skuWeightKg`) × monthly committed demand → **mix-accurate kg/mo tonnage** (`LogSkuFlows`/LG-2, [logistics.jsx:147-172](logistics.jsx#L147-L172)) — replaced an old flat 3 kg/unit even-split.
- **Volume:** per-SKU **m³** (`skuVolM3`) → Network storage utilisation.
- **Lane cost:** `cost_matrix = lane rate (₹/km) × distance`; the LP minimises Σ rate·flow. UoM is consistent: units → kg via the one weight master, lanes priced ₹/km.

### Assertions (test now)
- **A1** mix-accurate tonnage: total outbound kg/mo == Σ(SKU monthly demand × `skuWeightKg`), not a flat per-unit constant.
- **A2** mode pick: each lane picks the cheapest mode meeting its SLA (`transit ≤ deadline`); `mode_summary` reflects the solved choice.
- **A3** consolidation: LTL→FTL merge fires by ⌈Σ truck-fractions⌉ (a packing rule, not an optimiser — labelled honestly).

### Gap backlog (build → then assert)
- **G-L1 (allocation is even-split, not assignment):** the lane split is the **demand plan spread evenly across outbound lanes**, *not* an optimised DC→customer **assignment** LP (the card says so honestly, [logistics.jsx:141](logistics.jsx#L141)). Wire the real `allocation` solver (it exists: `solverType.allocation` = "DC→customer min-cost flow") so the split is optimised. *Then assert:* allocation minimises cost vs the even split.
- **G-L2 (unified inbound+outbound view):** inbound (Sourcing) and outbound (Logistics) are correct but **scattered**; add a single network-flow view that shows both directions so the planner sees end-to-end freight in one place.
- **G-L3 (stockout/mode-risk on outbound):** `extras` lists air-vs-sea stockout-risk mode penalty as inert on plain domestic outbound lanes — only relevant once per-lane demand-sensing is wired; recorded, low priority.

---

# Tab 09 — Finance (capital · value/EVA · cash · invest · assets · FX)

`StageFinance` ([finance.jsx:6](finance.jsx#L6)) — 6 subtabs, **Capital first** (the solved landing, not the illustrative Cash seed): **a** Capital (hurdle/WACC/NPV/DSCR) · **b** Value (EVA/ROIC + prune) · **c** Cash & WC · **d** Investments · **e** Assets · **f** FX. Engines: `/api/calc/hurdle`, `/api/calc/wacc-structure`, `/api/calc/npv`, `/api/calc/depreciation`, `/api/solve/capital-capacity`, `/api/solve/capital`.

> **The "decide" tab + the ops↔finance wedge.** Mostly solved and unusually honest about the one seed subtab.

### Journey
- **J-pre:** committed demand + costs (margins); production `projected_inventory` (for the EVA working-capital base); FX table.
- **J-in (user):** capital sources (equity/debt weights, Ke/Kd), tax rate, CapEx budget, investment options (capex/cashflow/life/residual), asset register, FX rates.
- **J-api order:** `/api/calc/hurdle` + `/api/calc/wacc-structure` (cost of capital) → `/api/calc/npv` (program DCF + dep shield) → `/api/solve/capital-capacity` (endogenous expansion MILP) → `/api/calc/depreciation` (WDV). EVA derived from the above + ops outputs.
- **J-post:** hurdle/WACC/NPV/EVA cached; `EvaPruneBranch` can push a re-plan back up (`scenarioPruneSkus` → full loop).

### Concept notes
- **What's solved vs seed (honesty)** — Capital (hurdle, min-WACC structure with DSCR cap), Value (EVA/ROIC), Investments (capital-capacity MILP), Assets (WDV depreciation), FX are **solved/derived**. **Cash & WC is explicitly flagged "illustrative seed — no live AR/AP/inventory ledger connected"** ([finance.jsx:39](finance.jsx#L39)); EVM/CCC are derived from those seeds. A seed is never the first thing a CFO sees (Capital is default).
- **EVA ops↔finance loop (the wedge)** — `EvaPruneBranch` flags a value-destroying SKU, zeroes its demand, and **re-runs the full loop** to show the cost/fill/CVaR delta ([finance.jsx:441](finance.jsx#L441)) — a negative-EVA tail SKU can be load-bearing on a shared line, so pruning can *raise* cost. This is the differentiator (#6 can re-plan #1–5).
- **EVA capital base** reads production `projected_inventory` when production is solved (the B-7 wiring), else falls back to a COGS÷turns proxy — so the EVA number's quality depends on a fresh production solve.
- **NPV shield honesty** — the Capital·NPV adds the depreciation tax saving (dep×t) on already-after-tax cash flows; it does **not** re-tax them (the FIN-3 fix).
- **FX single source** — the FX Rate Table is the one live $→₹ every solver reads; editing a rate re-prices landed cost + hedge marks + procurement VaR together and marks dependent solves stale ([finance.jsx:832](finance.jsx#L832)). Ties to §2.

### Assertions (test now)
- **A1** solved-not-seed: hurdle/WACC/NPV/depreciation carry a `solved` provenance and move when their inputs change (not frozen seeds).
- **A2** EVA base wiring: with a fresh production solve, the EVA working-capital base reads `projected_inventory`; without one, it honestly shows the proxy basis (no silent fabrication).
- **A3** carry = hurdle identity (already an OBS-2 identity): `carryRate ≈ WACC + holding spread`, and Sourcing's carry rate uses it.
- **A4** FX propagation: editing `config.fxRates.USD` re-prices landed cost (§2 A2) and flags procurement/policy/MEIO/profit-mix stale.

### Gap backlog (build → then assert)
- **G-F1 (live WC ledger):** wire a real AR/AP/inventory feed to Cash & WC so EVM/CCC/CCC are live, not seeded (the one honestly-flagged seed subtab). *Then assert:* CCC moves with the ledger.
- **G-F2 (EVA base visibility):** surface *which* capital base the EVA used (live `projected_inventory` vs proxy) on the scoreboard so the number's grade is legible.

---

# Tab 10 — Console (run any solver · glass-box)

`StageConsole` ([console.jsx:22](console.jsx#L22)) — three banded jobs: **①** Orchestrate (Planning Spine · Solver Network · Run Profile · Solve Status) · **②** Interpret (the result + the plain-English `DecisionExplainer` + `RecTest` "prove it") · **③** Anatomy Lab (`SolverLab` — Cartesian-style 3-pane: real model / inputs / live solve). The home of the glass-box wedge. Results cards: `ResProcure`/`ResProduce`/`ResProfit`/`ResTransport`/`ResRisk`/`ResCapital`/`ResSOP`.

> **This is the "why switch to us" surface.** It's where duals become English and a recommendation can be re-solved before you trust it.

### Journey
- **J-pre:** the relevant inputs for whichever engine you run (Console can run **any** of the 16, in any order — it's the power-user hub, not a guided stage).
- **J-in (user):** pick a solver node → run it (or ▶ Run spine for the full loop). Optional per-solver knobs (profit-mix budget/warehouse, MC controls).
- **J-api:** any `/api/solve/*` or `/api/calc/*`; the Solver Network colours each node by **live** cache freshness.
- **J-post:** each run `cacheSolve`'d + `markSolved`; results render with solved provenance.

### Concept notes
- **The glass-box (D1/D1+):** `DecisionExplainer` translates the profit-mix duals (`shadow_prices`/`reduced_costs`/`crossover`) into plain English — 🔴 bottleneck / ⬜ dropped SKU / 💡 crossover price / 🟢 spare — with **no new numbers** ([console.jsx:653-739](console.jsx#L653-L739)). `RecTest` ("🧪 prove it") **re-solves the same profit-mix with one perturbation** → the *actual* Δprofit vs the dual's linear estimate + an honest **OVERSTATE** verdict, then an **explicit Apply** (never silent auto-apply, [console.jsx:591-636](console.jsx#L591-L636)).
- **Live freshness, not seed status** — the Solver Network node colour reads `useStale`/`solverFreshnessMaps` (green fresh / amber stale / grey not-run), the B-2 fix; Console no longer shadows store payloads (the B-7 fix — its cards call the governed `productionPayload`/`montecarloPayload`).
- **SolverLab boundary** — the Anatomy Lab exposes **curated knobs only**, not arbitrary-code→backend (that would be RCE); a deliberate boundary, not a gap.

### Assertions (test now)
- **A1** freshness honesty: a Solver Network node is green **only** when its cache is fresh (`!useStale`), grey when never run — never a seed-coloured lie (B-2).
- **A2** explainer integrity: `DecisionExplainer` renders only from `r.shadow_prices`/`reduced_costs`/`crossover_analysis` — every figure traces to a dual (no fabricated ₹).
- **A3** prove-it honesty: `RecTest` reports the *re-solved* Δ and flags it OVERSTATE when the linear dual estimate exceeds the actual; Apply writes only on explicit click (`rec_apply` event).
- **A4** no shadows: no Console-local payload builder shadows a store global (the hardened `model_check.js` check, post-B-7).

### Gap backlog (build → then assert)
- **G-C1 (explainer coverage):** `DecisionExplainer`/`RecTest` cover profit-mix; extend the plain-English + prove-it pattern to the other dual-bearing solvers (linecap, transport, capital, cvar) so every "why" is explainable, not just the mix. *Then assert:* each has an explainer + a prove-it.

---

# Tab 11 — Scenarios (risk · cost · what-if · loop · self-test)

`StageScenarios` ([scenarios.jsx:20](scenarios.jsx#L20)) — **risk** (`ScnRisk`: MC on the committed plan, CVaR-robust stock, control tower, resilience stress) · **cost** (`ScnCost`) · **explore** (`ScnExplore`: what-if parser, multi-SKU compare) · **loop** (`ScnLoop`: `runFullLoop`). Plus the platform's self-measurement (`ValueLedger`, D2) and self-test (`SubflowHarness`, HARNESS-2). Exception Cockpit + Value Ledger now render on Home (R13). Engines: `/api/solve/montecarlo`, `/api/solve/cvar`, `/api/solve/sensitivity`, `/api/whatif`.

> **Risk runs on the *committed* plan, not a fresh re-derive — the control-tower-on-the-committed-plan differentiator.**

### Journey
- **J-pre:** a cached production solve (MC replays the gantt), committed demand, costs.
- **J-in (user):** MC controls (runs, lead-time/CV, correlation), CVaR β, stress lever + ramp, what-if text.
- **J-api:** `montecarlo` (policy='plan'), `cvar` (per-plan + per-SKU), `sensitivity` (solved tornado), `whatif` (advisory + re-solve).
- **J-post:** risk KPIs (CVaR95, fill, lost sales) cached; scenarios branch/compare/merge via the engine (byte-restored).

### Concept notes
- **MC on the committed plan** — `montecarloPayload` replays the cached production gantt (`policy_simulated=='plan'`), not a re-derived base-stock policy — the #5 OBS-2 identity, and the reason "control tower" means something here.
- **Honest seed vs solved** — solved: MC, CVaR, `SolvedTornado`, `ValueLedger`, the resilience sweep. Explicitly **illustrative**: Cost Waterfall, TCO per SKU, the seed Sensitivity tornado, Disruption Registry, Stakeholder grid (all badged).
- **ValueLedger (D2)** measures the platform's *own* ROI from `events[]` + cached solves with an honest **identified-vs-accepted** split and **no blended total** ([scenarios.jsx:736-797](scenarios.jsx#L736-L797)).
- **SubflowHarness (HARNESS-2)** — the in-app behavioral test: perturb ONE lever → re-solve → assert KPI **direction**, runs **quiet** so self-tests don't inflate the ValueLedger.

### Assertions (test now)
- **A1** MC-on-plan: `/api/solve/montecarlo` returns `policy_simulated=='plan'` after a production solve (not a generic base-stock).
- **A2** ledger honesty: ValueLedger never shows a blended total; identified and accepted are separate, each ₹ provenance-traced.
- **A3** seed labelling: Cost Waterfall / TCO / seed-sensitivity carry an `illustrative` badge (no seed wears a `solved` chip).
- **A4** resilience sweep: `ResilienceStress` runs N× real `/api/solve/montecarlo` and the breaking point is where fill < service target (monotone degradation).

### Gap backlog (build → then assert)
- **G-SC1 (solved cost views):** Cost Waterfall + TCO-per-SKU are illustrative — wire them to the solved cost rollups (procurement/production/landed) so cost analysis is live. *Then assert:* TCO == Σ solved cost components.
- **G-SC2 (default to solved sensitivity):** two tornado cards exist (seed + `SolvedTornado`); default to the solved one and demote the seed.

---

# Tab 12 — Reference (model map · consistency · learning · SAP · open API)

`StageReference` ([reference.jsx:4](reference.jsx#L4)) — **map** (`ModelMap` + `ConsistencyPanel`) · **learn** (Learning Lab) · **sap** (T-code map) · **api** (`RefAPI`, open solve API). The user-facing **observability** surface (OBS-1/OBS-2) + the learning/integration framing.

> **This is the observability wedge made visible — the live machine map + the "do the engines agree?" panel.**

### Journey / Concept notes
- **ModelMap (OBS-1)** — the SolverNetwork fabric **coloured by live cache freshness** (green fresh / amber stale / grey not-run), with `ModelNodeDetail` lineage (SOLVE_DEPS inputs → method → endpoint → last result). Re-uses the one fabric (no third drawing).
- **ConsistencyPanel (OBS-2)** — cross-solver consistency ("do the engines agree?") on the live cache, **honest "—" when a solve hasn't run** ([reference.jsx:257-308](reference.jsx#L257-L308)). The *full* 5-way demand-conservation + dual chain is what `golden_path.js`/HARNESS-1 asserts headlessly — the panel displays the live subset.
- **RefAPI (D7)** — the open solve API introspects `app.url_map` (real routes, **can't drift** from the backend) — endpoint catalog + curl + digital-twin framing.
- **RefLearn** — Learning Lab; the EOQ worked example computes live.

### Assertions (test now)
- **A1** map freshness: ModelMap node colour == live `solverFreshnessMaps` state (the single shared builder, not a seed status).
- **A2** consistency honesty: ConsistencyPanel shows "—" for any identity whose inputs haven't been solved (never a fabricated agreement).
- **A3** API introspection: `/api/meta/solvers` returns the live `url_map` route set (count matches registered routes).

### Gap backlog (build → then assert)
- **G-RF1 (full identity panel):** the ConsistencyPanel displays a subset live; surface **all** the cross-solver identities (the 6–7 in `golden_path.js`) in the panel so a user sees the same checks the harness runs. *Then assert:* panel identities == harness identities.

---

# Horizon contract (the 7th cross-solver identity — global)

Single governed knob `planning.horizonLength` (52 wk, [store.jsx:99](store.jsx#L99)) + the calendar (`/api/calc/calendar`). But each solver runs its **own declared basis** — correct modelling, currently **implicit**:

| solver | basis | period count | source | note |
|---|---|---|---|---|
| forecast | `horizonFor(grain)` | 30/13/12 | [data.jsx:858](data.jsx#L858) | grain-dependent |
| production / procurement / linecap / montecarlo | **schedule fence** | `clamp(horizonLength,4,W)` | [store.jsx:693-695](store.jsx#L693) | **W = governed `planning.productionScheduleWeeks`** (default 13, Setup ▸ Schedule Fence) — G-SU1 ✅ |
| aggregate | S&OP buckets | 12 (or max forecast len) | [store.jsx:846](store.jsx#L846), [aggregate.py:86](aggregate.py#L86) | monthly |
| policy | reorder | `horizonLength` / demand len | [products.jsx:276](products.jsx#L276) | |

**Assertion (to add to golden_path):** each solver's returned `periods` equals what its **declared** basis derives from `horizonLength` + grain. **DONE (G-SU1):** the fence is now the governed `planning.productionScheduleWeeks` (default 13), editable in Setup ▸ Schedule Fence and shown in the config-audit table; the Setup banner is now an honest **horizon contract** (each solver's own basis) instead of "the whole app re-buckets."

---

# Execution plan (how this file gets *tested*)

- **Layer A — headless (build first):** extend `tools/golden_path.js` to walk this spine in `runFullLoop` order via `page.evaluate`, asserting the `An` checks + the horizon identity for all 16 solvers in `SOLVE_DEPS` order (today it exercises ~8). No `data-testid` needed. Cheap, deterministic.
- **Layer B — real clicks (build second):** same spine, drive the actual DOM via `data-testid` (added across tabs under HARNESS-1b's net). Proves wiring (input box → payload, button → solver, result → render). Because Layer A proved the math, a Layer B failure is unambiguously a DOM/binding bug.
- **Backlog graduation:** each `Gn`, when built, gets a new `An` here + in the harness.

> Recommended order: horizon identity (cheapest, highest-truth) → all-16 field-contract coverage → real-click journey. The `Gn` backlog is independent work, prioritised by you.

---

# ✅ TIER-1 FIX QUEUE — DONE (2026-06-06, all 4, frontend-only, uncommitted)

User decision: **compact, then fix Tier-1.** Done one at a time, **HARNESS-1b run after each** (`node app_v2/tools/golden_path.js` — stayed **9/9 boot + identities** throughout, the B-16 lesson). Each carries a dedicated browser-boot proof probe. HARNESS-1 stayed 6/6 (now 416 unique top-level names).

1. **G-SU1 ✅ — governed the schedule fence.** New `planning.productionScheduleWeeks` (default 13); `productionScheduleHorizon` now `clamp(horizonLength,4,W)` ([store.jsx:693-695](store.jsx#L693-L695)), no longer a hardcoded 13. Editable in **Setup ▸ Schedule Fence** ([setup.jsx](setup.jsx)), shown in the config-audit table. The Setup banner is now an honest **horizon contract** (each solver's own basis) — the old "whole app re-buckets" overclaim is gone. Baseline byte-identical (W=13 ⇒ same 13). HARNESS-1b 9/9.
2. **G-D1 ✅ — pure-MTO flow wired.** `getItemDemand` fallback now applies **forecast-consumption** — `demand[t] = max(seed-spread[t], firm-order[t])` — via new `firmOrderDemand(sku,T)` ([store.jsx:269-310](store.jsx#L269)) which buckets the **firm** (status==='firm') MTO order book by due-date (`periodDays=horizonDays/T`, grain/T-safe). A firm-order-only SKU now reaches production/procurement instead of a flat seed. The committed-forecast path is unchanged (so the golden path is byte-identical → HARNESS-1b numbers held). **Proof:** fresh-boot probe — TPA-4471 firm 480 (due 2026-06-12) lands in wk1, sum=51×55+480=3285; non-firm SKU stays flat seed (planned orders correctly excluded).
3. **G-S2 ✅ — ordering_cost unified on master S.** `bomParts` ([store.jsx:629](store.jsx#L629)) `ordering_cost:120` → `(Number(b.S)||120)`. One fix propagates to **all** procurement paths (loop, Sourcing via `partsWithSourcing`, Console, policy, rolling) — products.jsx already used `b.S`. **Proof:** live payload now carries S=1200/900/140/60/80 per part; none still 120. (Stale sourcing.jsx:63 comment corrected.)
4. **G-P5 / G-N1 ✅ — scheduled receipts wired.** New `network.scheduledReceipts` slice (seeded 2 open POs in [data.jsx](data.jsx); added to `_NET_KEYS`), surfaced as an editable **Network ▸ Scheduled Receipts** card ([network.jsx](network.jsx) `NetScheduledReceipts`). Fed to the procurement MILP as `params.locked_pos` (+`horizon_start_date`) via new `scheduledReceiptsLocked()` ([store.jsx](store.jsx)) across all three procurement payloads — **the backend already nets them** (procurement.py T6 → RM balance), so an inbound PO reduces the planned buy. **Proof (browser-boot probe, post-forecast loop procurement, Optimal both legs):** steel buy **2000→0 (saved 2000)**, bearing **1500→0 (saved 1500)** when the two seeded open POs are present (both receipts land at period 0: steel relP −2 + lt 2; bearing relP −3 + lt 3). A real bug was found & closed here: `scheduledReceiptsLocked()` must translate part **code→name** (`M.bom[].name`) because procurement.py matches `locked_pos` by the payload `name`, not the code — sending the raw code silently no-op'd the lock (name_to_gidx miss). *(Note: standalone pre-forecast `_loopProcurementPayload` is Infeasible WITH AND WITHOUT receipts — a **pre-existing** condition of solving procurement before demand is committed, not a regression; the real flow always forecasts first, and Sourcing per-SKU pre-forecast stays Optimal. RM on-hand → per-part `init_inventory` is the natural sibling follow-on — the data already exists in `network.onHand`.)*

After Tier-1: gates re-run — **HARNESS-1b 9/9 · HARNESS-1 6/6 · OBS-3 provenance lint clean** (2026-06-06). Then the **execute** phase (Layer-A `An` assertions into `golden_path.js`, incl. the horizon identity now that the fence is governed). Tier-2/3 `Gn` items follow, user-prioritised — see the **⏭ TIER-2 / TIER-3 QUEUE** below.

---

# ⏭ TIER-2 / TIER-3 QUEUE (user: "do tier 2 and tier 3 as well", 2026-06-06)

Grouping of the remaining `Gn` backlog by **value × tractability**. Same discipline as Tier-1: one at a time, browser-boot proof probe each, **HARNESS-1b after each (must stay 9/9)**, frontend-first.

**✅ TIER-2 — DONE (2026-06-06, all 9, each with a browser-boot probe + HARNESS-1b 9/9 · HARNESS-1 6/6 throughout). Frontend-only except one additive aggregate.py field (G-P1).**
1. **G-PM1 + G-SU2 ✅** — `ResProfit` ([console.jsx](console.jsx)) gates to `SingleProductCheck` (capacity check + nudge) when `finished.length===1`; `M.profileGate.profitmix` also greys it. New `profitMixSingleProduct()`. *Probe:* dormant@6 SKUs, fires@1, profile gate tracks.
2. **G-L1 ✅** — `transportPayload` ([store.jsx:707](store.jsx#L707)) now feeds `origins/destinations/cost_matrix` (DC→customer lanes, cost=rate×km) so transport.py's embedded min-cost flow LP runs; Logistics renders the optimised assignment + saving vs even-split. *Probe:* LP routes all 1001u via Pune DC (LTL), **LP ₹31.3M ≤ even-split ₹92.3M**.
3. **G-I2 ✅** — `config.abcService{A:.98,B:.95,C:.90}` + `serviceLevelForSku()` ([store.jsx](store.jsx)); `ProdPolicy` uses the SKU's class service level; ABC editor in Sourcing. Loop stays flat (byte-identical). *Probe:* class-A z=2.054 > class-C z=1.282.
4. **G-P1 ✅** — aggregate.py per-period `overtime_cost` (additive, already in objective) surfaced as an **OT ₹** column + total in `PlanWorkforce`. *Probe:* OT₹ == OT units × ot_cost_per_unit (₹123,000 = 100×1230 ×4 periods).
5. **G-P3 ✅** — governed `planning.hrsPerShift` (8, Setup ▸ Net Hrs/Shift); `ProdArch` line footer shows **machine-hrs/wk = Σm × shifts × hrs × workDays × OEE**. *Probe (renders Production tab in-browser):* LINE-01 = 403 (10×1×8×6×0.84) in the DOM, 0 page errors.
6. **G-D3 + G-D4 ✅** — new `pastLabel()` (real dates, replaces "W-6…W-1" on the actuals grid); `calendarStart()` anchors futureLabel/pastLabel to the governed `planning.startDate`; Setup `recompute` syncs `M.calendar.start ← planning.startDate`. *Probe:* past[1]=25 May '26; both labels track startDate when changed (no drift).
7. **G-SC2 ✅ (already satisfied, RK-C)** — `SolvedTornado` is already the primary card; the seed `Tornado` already sits behind a default-collapsed `Advanced` ("illustrative — not solved"). Verified, no change needed.
8. **G-F2 ✅** — `finEva` returns `capBreakdown` (FG inventory + pooled SS + fixed, each tagged solved/proxy); scoreboard shows the composition strip + total. *Probe:* components sum to `tot.cap`; basis flips `turns proxy → solved inventory` after a time-phased loop.
9. **G-S3 ✅** — `sourcingDefault` gains `origin/hsCode/quoteCcy`; `hsDuty()` grounds the duty (HS→BCD − FTA-origin concession); `originConcentration()` flags single-origin/supplier RM-spend share vs governed `config.originConcentrationCap` (0.6); Sourcing UI gains Origin/HS columns + a concentration panel. *Probe:* RM-BRG18 KR/7224.90/USD, BCD 7.5%−FTA50%→3.8%; origin IN 85% breaches the 60% cap.

**TIER-3 — structural / backend / modeling depth (IN PROGRESS):**
1. **G-P4 ✅ DONE (2026-06-06)** — production MILP labor envelope. The org labor-hours cap already existed in production.py (R14.1/D6) but was DEAD for routing payloads: it resolved cycle via `_cycle_min_by_sku` (line `cycle_time_by_sku_min` field) while the real `productionPayload` sends product `routing` → terms empty → skipped. Fixes: (a) production.py — the org cap now lets OT *relax* it (`Σ cycle_hrs·x ≤ headcount×40 + Σ ot`, mirroring `LineCapHrs`) so a tight headcount forces OT not infeasibility, and a routing-aware `_labor_cycle_min` (used only when cap>0 ⇒ golden path byte-identical); (b) `productionPayload` now sends `workforce:{hourly_headcount_cap, ot_cap_hrs}` from governed `config.prodLaborHeadcountCap`/`prodLaborOtCapHrs` (0=unbounded default); (c) `ProdParams` UI inputs + OT-used readout. *Probe (synthetic, machine-slack isolation — TPAC labor is honestly slack like SF-7):* no cap → OT=0h; headcount cap=1 (40 reg h/wk vs 60h needed) → **OT=80h forced**, demand fully met (2400u), both Optimal. Gates HARNESS-1 6/6 · HARNESS-1b 9/9. *(Probe gotcha: `overtime_hours` is on `result.lines[]`, not `result.products[]`.)*
2. **G-P2 ✅ DONE (2026-06-06)** — service-driven horizon-end cover floor in the aggregate S&OP plan. The Hax–Meal LP otherwise ran terminal stock to *exactly zero* (nothing in the objective rewards carrying end-cover). aggregate.py already had `ending_inventory_target` + `safety_stock` *params* but nothing service-driven fed them. Fix: (a) **aggregate.py** — when `params.end_cover_service` is supplied (and no explicit `ending_inventory_target` overrides), compute the floor from the LP's OWN labor-weighted demand: `I_T ≥ z(service)·σ(agg_demand)·√end_cover_periods` (NormalDist().inv_cdf, the backend's uniform z source). σ is the period-to-period std of `agg_demand` — the *only* place the labor-weighted σ exists, so it's computed backend-side, not re-derived in JS. Returns `ending_floor`/`ending_floor_basis`/`ending_inventory`. (b) **store.jsx** — new `aggEndCoverParams(cfg)` (single source for BOTH the live Plan tab and the loop) returns `{}` when `config.planEndCoverEnabled` is falsy (default) ⇒ no `end_cover_*` sent ⇒ plan still ends at zero = **byte-identical**; when ON, sends `end_cover_service=config.serviceLevel` + `end_cover_periods`. Spread into `_loopAggregatePayload` and plan.jsx's `useSolve` params. Config seed `planEndCoverEnabled:false, planEndCoverPeriods:1`; CONFIG_TOKEN→`cfg.prod` (aggregate dep). (c) **plan.jsx** — toggle + cover-periods input + live "✓ floor N u = z·σ · ends M u" readout in the cost-inputs card. *Probe (browser-boot, real loop builder):* **OFF** → no param, `ending_floor=null`, `endInv=0` (byte-identical); **ON** → `end_cover_service=0.95==serviceLevel`, `floor=172.57 = z1.6449·σ104.91`, `endInv=172.6 ≥ floor`, 0 page errors. Gates OBS-3 clean · HARNESS-1 6/6 · HARNESS-1b 9/9. *(The TPAC seed agg demand has real seasonal σ≈105 around mean≈1271, so the floor is meaningful, not degenerate.)*
3. **G-I1 ✅ DONE (2026-06-06)** — measured yield from production confirmations. Yield was a *typed seed* (0.92–0.98) assumed per SKU; a real shop measures it off the floor (good ÷ started). Now: new appStore slice `yieldConfirmations[sku]=[{started,good,ts}]`; `measuredYield(sku)` = Σgood/Σstarted (null when none); **`skuYield(p,fallback)` = measured ?? typed-seed** threaded through **every** solve-feeding payload — production (store.jsx `eff.yld`, routing override still wins first), montecarlo `skuParts`, loop procurement, live Sourcing procurement + meio + meionet + cvar, Console profit-mix + cvar, Products policy — so a worse measured yield grosses up the material you must buy / capacity you must run, consistently. `logYieldConfirmation()` appends a batch + `markStale('productCosts')` (cascades to all yield-consuming solves incl. montecarlo) + logs a `confirm` event; `clearYieldConfirmations` resets to `[]`. UI: a **Production yield confirmations** card in Products ▸ Yield&Expiry (log started/good, batch list, measured-vs-seed Reading + "drives the solvers" badge); catalog yield column shows measured% with a `*` marker + tooltip when overridden (honest — no silent seed). No confirmations ⇒ measuredYield null ⇒ every solve uses the typed seed = **byte-identical**. **REAL BUG found & fixed (appStore semantics):** `appStore.set` shallow-MERGES per slice, so `clear` via `delete cur[sku]` was undone by the merge re-spreading the old key — reset to `[]` instead (measuredYield treats empty as no-data). *Probe (browser-boot, real productionPayload + _loopProcurementPayload):* **(A)** no confirmations → measured=null, both payloads = seed 0.97 (byte-identical); **(B)** batch 700/1000 → measured=0.70 flows into **both** production AND procurement yield_pct (cross-solver); **(C)** clear → back to 0.97. Gates OBS-3 clean · HARNESS-1 6/6 · HARNESS-1b 9/9.
4. **G-S1 ✅ DONE (2026-06-07)** — per-part DETAILED landed-cost build-up. Landed cost was a **coarse flat `dutyFreightPct`** (seed 12%) per part; the rich FOB→plant-gate rollup was a single worked example (POSCO billet) that never fed the MILP. Now each imported part can carry its own build-up that **replaces** the flat % in the solve. Fix (frontend-only): (a) **store.jsx** — new `landedBuildup(src)` computes the **per-unit** net landed `= FOB×FX + freight + insurance + BCD(HS−FTA) + SWS + CHA + inland` (IGST recoverable as ITC → excluded), mirroring finance.py `calc_landed_cost` **exactly** so it reconciles to `/api/calc/landed-cost`; BCD is grounded by `hsDuty(src)` (HS heading − FTA-origin concession), FX is the live `landedRate(quoteCcy)`. `effLandedCost(rawCost,src)` now returns `landedBuildup().netLanded` when `src.landedDetail.on`, else the flat-% path. `landedDetailSeed(rawCost,src)` seeds the inputs continuously when first turned on. Opt-in via `src.landedDetail` — **absent for every seed part ⇒ golden path byte-identical**; once on, the accurate landed flows into procurement/policy/MEIO/profit-mix via the same `effLandedCost`. (b) **sourcing.jsx** — per-part **🛃 build-up** toggle on each imported Sourcing-Terms row expands `SrcLandedDetailRow` (FOB · ocean freight · insurance · CHA · inland inputs + a live CIF→BCD→SWS→CHA→inland→NET rollup + IGST-recoverable note + "revert to flat %"). The Landed ₹ cell badges **🛃 detailed** when on. (c) window manifest gains `landedRate, landedBuildup, landedDetailSeed`. *Probe (browser-boot, RM-BRG18):* **(A)** no detail → `landedBuildup`=null, flat landed ₹255.36 (byte-identical); **(B)** detail ON (FOB $300, freight ₹1500, ins 0.5%, CHA ₹200, inland ₹400) → HS 7224 BCD 7.5%−FTA50%→3.8%, CIF ₹26,886.30 → **NET ₹28,610.15**, and `effLandedCost` == backend `net_landed` **₹28,610.15 to the penny** (RECONCILES, the assertion); IGST ₹5,041.83 recoverable; **(C)** revert OFF → back to flat ₹255.36. Gates OBS-3 clean · HARNESS-1 6/6 (439 names) · HARNESS-1b 9/9.
5. **G-N3 ✅ DONE (2026-06-07)** — per-STORAGE-CLASS node capacity (the §1.5 category-error fix). Node capacity was one lump "cube" — a cold-chain SKU and an ambient SKU competed for the same m³, which is physically wrong. Now each item carries a storage class (ambient/cold/hazmat) and each node can declare capacity per class, so utilisation is computed per class. Fix (frontend-only): (a) **store.jsx** — `STORAGE_CLASSES`/`STORAGE_CLASS_LABEL`; `storageClassFor(item)` reads `config.storageClass[item]` (default ambient); `nodeClassCap(node,cls)` (with explicit `node.classCaps` use them, WITHOUT any the whole `node.capacity` is ambient & others 0 — so an un-classed node is the single-cube model exactly); `nodeStorageUtil(node)` returns per-class `{used,cap,pct}` from `onHand × skuVolM3` grouped by class. New config seed `storageClass:{}`. (b) **network.jsx** — Storage Utilization card now renders a per-class breakdown per node (each class a bar + editable m³ cap; turning on per-class caps seeds ambient from the old cube so it stays continuous; a "stored but NO class capacity" warning when used>0 & cap=0); new `NetStorageClasses` card assigns each held item's class. (c) window manifest gains the 5 helpers. Default (all ambient, no classCaps) ⇒ ambient util == the prior single-cube number, others empty ⇒ byte-identical; storage class feeds no solver (display/warehousing only) so the golden path is untouched. *Probe (browser-boot, DC-BLR holds TPA-4471 0.252 m³ + TPA-3215 0.558 m³):* **(A)** all ambient → ambient 0.81 m³/cube 3400 (0.024%) == single-cube used, cold cap 0 (byte-identical); **(B)** mark TPA-3215 cold + caps {ambient 1, cold 0.5} → TPA-3215's volume MOVES to cold (ambient 0.252 m³, cold 0.558 m³, conservation Σ==0.81), and **cold = 111.6% OVER its 0.5 m³ cube while the overall cube is at 0.024%** — the category error made visible. Gates OBS-3 clean · HARNESS-1 6/6 (445 names) · HARNESS-1b 9/9.
6. **G-C1 ✅ DONE (2026-06-07)** — glass-box explainer coverage extended past profit-mix to the other four solvers. The D1 `DecisionExplainer` translated only the profit-mix duals; linecap/transport/capital/cvar showed raw tables. Now each gets the same plain-English DiRow surface, grounded ONLY in its own solved numbers (no figures invented — the "no faking" contract). Fix (frontend-only, console.jsx): four pure top-level `explain*(r)` functions + a reusable `GlassBoxExplainer` card: **`explainLinecap`** (per line: 🔴 bottleneck with its ₹/unit capacity dual + total unmet, or 🟢 spare with idle units — a binding line is a machine-CapEx case, a ₹0 line is not), **`explainTransport`** (cheapest mode per lane + 🟢 consolidation saving or "no full-truck gain yet"), **`explainCapital`** (✅ FUND each selected = clears the WACC hurdle with its NPV/IRR · 💡/⬜ DEFER each rejected (positive-NPV-but-budget vs value-destroying) · a BUDGET BINDS/SLACK row driven by the real `budget_shadow_price` dual + `budget_utilization`), **`explainCvar`** (typical cost · 🔴 CVaR-95 worst-5% tail with a hedge action · VaR · fragility fat-tail flag · service fill). Wired: console `ResTransport`/`ResCapital`/`ResRisk` each render a `GlassBoxExplainer` below their results; plan.jsx `LinePressureTable` renders `explainLinecap` under the line-pressure table. `prov-ok:` justifies the card's solved chip (pure translator of a parent solve). *Probe (browser-boot, all four live solves):* transport 5 lane→mode rows + consolidation verdict; capital **FUND rows == selected (2) exactly**, DEFER + a BUDGET row; cvar TAIL-RISK row present (CVaR-95 ₹73.6L over 120 runs); linecap **one row per line (3==3 lines)**, all honestly SPARE at TPAC volume. Gates OBS-3 clean · HARNESS-1 6/6 (450 names) · HARNESS-1b 9/9.
7. **G-SC1 ✅ DONE (2026-06-07)** — solved cost views (Cost Waterfall + TCO-per-SKU were both `M.*` seed). Fix (frontend-only): (a) **store.jsx** `costWaterfallLive()` reads the LIVE cached **procurement `cost_breakdown` + transport `total_cost`** into category bars (Material·Ordering·Setup·Conversion·Holding·Overhead·Milk-run·Expiry·Transport); **Holding is the residual** (`total − Σ explicit`) = the carrying cost the MILP charged but doesn't itemise, so the bars **sum to the solved total by construction**; returns null until procurement is cached ⇒ honest seed fallback. (b) **store.jsx** `tcoPerSku()` derives each per-unit component from a real source — unit = product cost, **quality = unit·(1/measured-yield − 1)** (G-I1), **ordering = Σ master S ÷ committed annual demand** (G-S2), **holding = solved carryRate (WACC+spread, FIN-8) × unit × governed cover**, obsolescence = salvage write-down only when shelf < cover (₹0 for durable auto parts, correct) — TCO is the exact sum of the five. New config `tcoCoverWeeks:6` (governance knob; the *rate* is solved). (c) **scenarios.jsx** `ScnCost` rewired: waterfall renders the live category build-up (badge solved·live / seed fence when uncached) with a "Σ bars = solved total" Reading; TCO table is `derived`, with a "reacts to measured yield / solved carry rate / real S" Reading. `prov-ok:` on the waterfall's solved chip (reads the cross-stage cache, not a local useSolve). Window manifest + `costWaterfallLive, tcoPerSku`. *Probe (browser-boot, loop + transport):* **waterfall Σ cats ₹72,15,729 == solved total to the penny** (transport bar present); every SKU **TCO/u == Σ of its 5 components exactly**; G-I1 linkage — forcing TPA-4471's measured yield 0.97→0.70 raises quality ₹36.8→₹510 and TCO ₹1263→₹1737 (wired, not seed). Gates OBS-3 clean · HARNESS-1 6/6 (452 names) · HARNESS-1b 9/9.
8. **G-RF1 — full identity panel.** Surface all golden_path identities in `ConsistencyPanel`. *Assert:* panel identities == harness identities.
9. **G-F1 — live WC ledger.** AR/AP/inventory feed to Cash & WC. *Assert:* CCC moves with the ledger.
10. **G-P6 — schedule ↔ profit-mix link.** Declare/wire whether the schedule builds the mix-chosen mix.
11. **G-D2 — calendar drill-down** · **G-D5 — promo co-location** · **G-L2 — unified inbound+outbound view** (UX depth).

**PARKED (recorded out of scope):** G-N2 / G-I3 (multi-site SS / lateral transshipment — next inventory frontier, deliberately deferred); G-L3 (outbound mode-risk — inert until per-lane demand-sensing).
