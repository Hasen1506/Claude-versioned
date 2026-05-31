# Redesign Blueprint v2 — corrections after the prototype review

**For: Claude Design. Status: this supersedes v1 (`REDESIGN_BLUEPRINT.md`). This file is
self-contained — you do not need v1 or any other doc to act on it.**

---

## ▶ COVER NOTE — read this first (the deltas in 60 seconds)

**What you built:** a clean multi-file React prototype of v1 — `chrome.jsx` + `lib.jsx` design system
+ one Tata-Auto mock dataset + 12 stage files + router. **The architecture and design system are
right — keep them.** This pass is corrections, not a restart.

**The one root fix:** build the **global data model in Part 1 *before* touching screens.** It was
specified in v1 but never built, and its absence is what causes most of the symptoms below. It is:
(a) an **item identity + a persistent item selector** on every planning stage; (b) **one calendar →
period axis** the whole app renders against; (c) the **real solver list (16 engines, 5 families)**,
drawn once; (d) **per-item directional flow** (a node's capacity is consumed by specific items).
Build those four and half the defects disappear at the root instead of being patched per screen.

**The 12 deltas to apply** (full detail + a 25-row file-by-file register are below):
1. **Solvers: 7 → 16, in 5 families, drawn ONCE.** `data.jsx solvers[]` has 7; the masthead/console say
   "7 solvers." Fix the data and the label; render one shared graph in both Home and Console (today
   there are two different drawings).
2. **Add the missing "Define Products" screen.** Products opens straight to BOM; nothing ever asks what
   you make. Add it as Products' first section.
3. **Add the persistent item selector.** Only Products has a SKU strip — so on Demand/Sourcing you
   can't tell which item you're looking at. Lift it into `lib.jsx`, pin it to every planning stage.
4. **Delete every `'W12'`/`'W08'` literal** → bind to the calendar period axis; render real dates.
5. **Evict WACC + CAC from Setup; declutter Company** (the name field is unreadable). Setup = identity
   + calendar, **0 sub-tabs**.
6. **Pull all master data into one "Network" stage AFTER Products** (nodes, lanes, contracts, on-hand,
   suppliers) and make flow **per-item, directional** (inbound per part / outbound per FG); add
   time-varying contract prices.
7. **Drop sub-tabs** on Setup/Plan/Sourcing/Logistics — single guided scroll. Keep them only on
   Finance/Console/Scenarios.
8. **Demand:** add a **history-entry grid** (item × period, multi-grain), a **low-data path** (what
   runs + where ML output shows), **formulas on the leaderboard**, and put **override beside the
   forecast + schedule** it edits.
9. **MPS day-level** (grain toggle; frozen fence in days) — today it's weekly only.
10. **Interpret ATP/CTP/changeover inline**; show the solver's chosen run order + minutes saved.
11. **One control-tower source** (Home summary + Scenarios full, same `alerts[]`); **drill-down KPIs**;
    **MC = histogram/"N runs"** vs **transport = flow map** (distinct visuals).
12. **Mark inventory policy as derived** (show `SS=z·σ_LTD` etc.); **move Cycle/Line from Products to
    Production** (it's duplicated today).

Everything below is the same list, expanded, with exact fields, interpretation copy, and the file to
change for each.

---

You built a complete, well-architected prototype of v1 (chrome + `lib.jsx` design system + one mock
dataset + 12 stage files + router). The architecture, the brutalist themeable design system, the
`Card`/`SectionInfo`/`DevNote` anatomy, the pipeline ribbon, and the realistic Tata-Auto dataset are
all **correct — keep them**. But the prototype implemented v1's *words* and missed its *intent* in
~12 specific places, and re-introduced the "7 solvers" fiction v1 explicitly told you to kill. This
document fixes every one, concretely, file by file, so it lands in one pass.

Read Part 1 (the data model the whole app must obey — it was specified in v1 but never built). Then
Part 2 (nav), Part 3 (screen-by-screen with "prototype did X → do Y"), Part 4 (defect register),
Part 5 (answers to the owner's questions), and **Part 7 — the planning logic the prototype lacks
entirely: the solver spine + IO contract, adaptive triage (stages turn on/off by profile), item-method
routing ((s,S) autopilot vs MILP), and the two real ingestion modes that replace the toy entry grid.**
Part 7 is the difference between "16 disconnected engines" and a planning system.

---

## PART 0 — The core mistake to internalize

A supply-chain planner never sees a number in the abstract. Every figure is **"how much of WHICH
item, at WHICH location, in WHICH time bucket."** The prototype renders charts and tables that float
free of that triple — a forecast with no product selected, an MPS with no day, a warehouse with a
lump "8,200 m³" that belongs to no product. Fixing this one thing fixes half your list. The other
half is **"explain what I'm looking at"** — every output needs its formula and its "so what."

Build the spine so a new user is walked **in dependency order**: you cannot define a warehouse's
stock of a part before the part exists; you cannot forecast a product before you've said what it is.

---

## PART 1 — The global data model (specified in v1, NOT built — build it now)

### 1.1 Item identity + a PERSISTENT ITEM SELECTOR  *(prototype: missing → highest-priority fix)*
Create one identity object used everywhere:
```
item = { id, code, name, kind:'FG'|'part', uom, family }
```
Add **one global control**, `<ItemSelector/>`, pinned to the top of every *planning* stage (Demand,
Plan, Production, Sourcing, Logistics — not the master-data or finance stages). It reads/writes
`state.ui.activeItemId` and shows:
```
 PRODUCT ▸ [ Crankshaft Bearing · TPA-4471 ▾ ]   view: ( ● Finished good )( ○ its parts )
```
Every table/chart on that stage filters to the active item. **This is the answer to "what product am
I forecasting / sourcing / looking at" — it is never ambiguous again.** In the prototype only
`products.jsx` has a SKU strip; lift that concept into a shared `lib.jsx` atom and put it on every
planning stage's `StageHeader`.

### 1.2 One period axis from the calendar — DELETE every `'W12'` literal  *(prototype: violated)*
Add to the dataset a single derived axis:
```
calendar = { grain:'day'|'week'|'month', start:'2026-06-01', count:52 }
periods  = buildPeriods(calendar)   // [{ id:0, label:'W23', date:'02 Jun', iso:'2026-06-02' }, …]
```
Every time-bound thing — `promos`, `costEvents`, `mps`, `gantt`, `cashflow`, `aggregate.months` —
must store a **period id** and render `periods[id].label` (a real date), never a hand-typed `'W12'`.
A grain switch (day/week/month) re-buckets the axis app-wide. `demand.jsx` `DemEvents`,
`products.jsx` `ProdEvents`, `production.jsx` `ProdMPS` all currently hard-code week strings — replace
with the axis.

### 1.3 The REAL solver inventory — there are ~16, not 7  *(prototype: hardcodes 7 → fix the data + both diagrams)*
`data.jsx solvers[]` lists 7. The backend has these engines — model the truth, grouped into 5
families so the diagram stays legible:

| Family | Engines (real `/api/solve/*`) | Kind |
|---|---|---|
| **Forecast** | forecast (HW/ARIMA/ML/DL/Croston/SBA/TSB) | statistical/ML |
| **Plan (S&OP)** | aggregate, disaggregate, reconcile (closed-loop) | LP |
| **Optimize** | profitmix, procurement, production, sequencing, transport, consolidate, lotsizing | LP/MILP |
| **Risk** | montecarlo (SIM), cvar (robust LP) | simulation / LP |
| **Capital** | capital, capital_capacity | MILP |
| *(orchestration)* | pipeline, rolling, sop | chains the above |

**Render ONE graph**, from this data, used by **both** Home and Console (same component, same source —
delete the divergent second drawing). Nodes are the engines; group them in the 5 family lanes; edges
are real hand-offs:
```
 forecast → aggregate → disaggregate ─┐
                  └→ reconcile ⇄ profitmix → procurement → production → sequencing → transport → consolidate
                                         │                                   ▲
                            (capacity duals) └→ capital / capital_capacity    │
                          montecarlo / cvar  ……… risk overlay on the whole chain ………┘
```
Stop calling it "7 solvers" in the masthead/footer/console. Call it **"Solver Network · 16 engines,
5 families."**

### 1.4 Flow is PER-ITEM and DIRECTIONAL  *(prototype: generic node capacity → rebuild)*
A node's capacity is not a lump. Model it as consumed per item:
```
node      = { id, type:'plant'|'dc'|'wh'|'supplier'|'customer', geo, capacityUom:'m3'|'pallet', capacity }
lane      = { id, from, to, direction:'inbound'|'outbound', item, mode, rate, leadDays, contractId }
contract  = { id, type:'spot'|'fixed'|'volume'|'take-or-pay', rateByPeriod:[…] }  // time-varying price
```
On the Network screen, when an item is selected (1.1), light up **its** chain: inbound
`supplier→plant` for each purchased part, outbound `plant→DC→customer` for the FG, each hop showing
mode · cost · lead time. Node storage shows **utilization = Σ(item volume × on-hand)/capacity**, so
"storage and flow" are item-aware. This is the answer to "does anybody know for what product is what."

### 1.5 Drill-down on every consolidated KPI  *(prototype: flat totals)*
Every Home/dashboard tile (margin, fill, OTIF, inventory, cash) is a **drill button**: company →
family → SKU → location → period. A single company total with no path down is a billboard. For a
single-product firm the drill bottoms out immediately — still show per-period and per-location.

### 1.6 The interpretation contract — formula + "so what" on EVERY output  *(prototype: mostly dropped)*
`SectionInfo` carries "what/flows" — good, keep it. But each **result** also needs, inline (not hidden
in a popover): **(a)** the formula or source, **(b)** one sentence of "what to do." The forecast
leaderboard with no formulas, the ABC/XYZ with one terse line, the ATP grid with no reading guide —
all fail this. Concrete copy is given per screen in Part 3.

---

## PART 2 — Navigation & the sub-tab discipline

**Sub-tabs are not free.** A new user reads a stage top-to-bottom; a sub-tab hides half of it. v1 said
"sub-tabs only for a genuinely different question"; the prototype put 4–6 on almost every stage. Rule
of thumb the redesign must apply:

- **0 sub-tabs (single guided scroll)** for: Setup, Plan, Sourcing, Logistics. They are *one* flow.
- **Sub-tabs only where there are real parallel modes**: Finance (cash/capital/assets/fx are different
  audiences — keep), Console (result groups), Scenarios (risk/cost/perf/explore).
- **Products** uses the **item selector + a short flow** (Define → BOM → Costs), not 6 tabs.

Corrected band/stage order with **prerequisites** (a stage shows "define X first →" until met):

```
DEFINE ──────────────────────────────────────────────────────────────────────
  01 SETUP        company identity · calendar(grain+horizon)              prereq: none
  02 PRODUCTS     ▸define FG · BOM · costs                                 prereq: setup
  03 NETWORK      nodes · per-item inbound/outbound lanes · contracts ·    prereq: products
                  opening on-hand · supplier master                       (← Logistics+Sourcing master data lives here)
PLAN ────────────────────────────────────────────────────────────────────────
  04 DEMAND       history entry · forecast · ABC/XYZ · events · consensus  prereq: products
  05 PLAN/S&OP    aggregate level-vs-chase · workforce · duals            prereq: demand
  06 PRODUCTION   lines→stages→OEE · MPS(day) · ATP/CTP · changeover       prereq: products(+plan)
  07 SOURCING     MRP per part · POs · landed cost · OTIF                  prereq: network+plan
  08 LOGISTICS    transport optimize · allocation · consolidation · CoG    prereq: network+production
DECIDE/MONITOR ───────────────────────────────────────────────────────────────
  09 FINANCE      cash · capital(WACC/NPV/budget) · CAC · FX · assets      prereq: costs/plan
  10 CONSOLE      run any solver/pipeline; results deep-link to 04–09
  11 SCENARIOS    risk · cost · performance · explore (one scenario store)
  00 HOME         consolidated drill-down KPIs · solver network · control tower (landing)
  REFERENCE       learning · SAP T-code map
```
(The prototype's order puts Logistics/Finance before Sourcing and scatters master data into Setup;
the above pulls all **master data** — nodes, lanes, contracts, on-hand, suppliers — into one
**Network** stage *after* Products, which is the only order that makes sense.)

---

## PART 3 — Screen-by-screen corrections (prototype did X → do Y)

### 01 · SETUP  — `setup.jsx`
**Declutter Company; evict everything that isn't setup.**
- Company section is **one readable header**, not a cramped 7-row `KV`: the company **name is a large
  editable title** (the owner literally couldn't read it), then currency, plant state, GST toggle,
  tax rate. **MSME tier is a single auto-derived badge** computed from turnover/investment (don't make
  it its own card with a 3-box selector — derive and show "SMALL · 43B(h) 45-day terms apply").
- Calendar section: **grain selector (day/week/month)** + **horizon (count × unit)** + workdays +
  holidays, and echo the one-line plan contract: *"Planning 52 weekly buckets · 02-Jun-26 → 31-May-27
  · ₹ · 95% service."*
- **REMOVE from Setup entirely** (the owner asked for this): WACC read-only card, CAC summary,
  Locations Master, Per-Location On-Hand, Transport Modes, Master Budget. WACC/CAC/Budget → Finance;
  Locations/On-hand/Transport → Network (03). Setup ends up as **2 sections, 0 sub-tabs.**

### 02 · PRODUCTS  — `products.jsx`
**Add the missing first screen; then BOM.**
- **NEW first section "Define Products"** — the catalog the prototype assumed existed. One row per FG:
  `code · name · description · family · UoM · make/buy · MTS/MTO/ATO · sell price · target margin ·
  unit weight · unit volume · shelf-life · lifecycle stage · status`. A new user lands **here**, adds a
  product, *then* the item selector has something to select and BOM has an owner. Header reads
  *"Step 1 — tell us what you make."*
- **BOM** (per selected FG, via the item selector): keep the physical/commercial split you built
  (`ProdBOM` Advanced disclosure is good), but the commercial group must include **time-varying
  contract price** (period→price) and the supplier picked from the Network supplier master.
- **Inventory policy is DERIVED, label it so.** `ProdParams` shows an "Inventory Policy (s,S)" card with
  hard numbers as if entered — mark it **computed** (from demand CV + lead time + service level) and
  show the formula (`SS = z·σ_LTD`, `s = μ_LT+SS`, `S = s+EOQ`). It's an *output*, not an input.
- **MOVE Cycle Time & Line Assignment OUT to Production (06).** Cycle/OEE are line properties; having
  them here *and* in Production is the duplication the owner called "random inserts." Products keeps:
  Define · BOM · Costs · MTO. (4 short sections under the item selector, not 6 tabs.)

### 03 · NETWORK  *(new stage — absorbs Setup's locations/on-hand/transport + Logistics/Sourcing masters)*
- **Nodes** (plants/DC/WH/suppliers/customers) with geo + per-item-aware capacity (1.4).
- **Supplier master** (moved from Sourcing) — needed here because BOM buy-terms reference a supplier.
- **Flows**: with an item selected, the **inbound chain per part** and **outbound chain per FG**, each
  hop mode/rate/lead-time; **contracts** with spot vs fixed-period vs volume vs take-or-pay and
  **rate-by-period** for prices that change mid-horizon.
- **Opening on-hand**: item × location matrix (only meaningful now that both exist).
- This is the screen that answers the owner's whole "how do we define storage/flow/on-hand/contracts
  before products exist" paragraph: we don't — we define them **here, after Products**.

### 04 · DEMAND  — `demand.jsx`
- **History ENTRY, not just a chart.** `DemForecast` shows a forecast line but no place to put data.
  Add an editable **history grid: item × period**, with **multi-grain entry** (enter daily for
  short-life SKUs → auto-Σ to weeks/months; the UI states which grain its data supports and what that
  does to accuracy). With the item selector pinned, "what am I forecasting" is always answered.
- **Low-data path, explicit.** When history < 12 points, show a banner: *"Sparse history — running
  Croston/SBA/TSB + classical only; ML/DL unlock at 12/36 points."* When the user hits **Run ML**,
  results render **inline right there** (leaderboard + chosen forecast overlaid on the history),
  with a note of where each tier's output lives.
- **Leaderboard WITH formulas/explanations.** `DemModels` lists models with no maths. Each row gets a
  one-line formula + plain note (HW: *"trend×seasonal, multiplicative"*; Croston: *"separates demand
  size from interval — for intermittent"*; MASE: *"MAE ÷ naïve-MAE; <1 beats naïve"*; tracking signal:
  *"Σerror/MAD; outside ±4 ⇒ biased, re-fit"*).
- **ABC/XYZ — feeds + reading.** State inputs (*ABC = annual £ value Pareto; XYZ = demand CV*) and the
  action per cell (*AX → tight (s,S), HW; CZ → lean, Croston, monthly review*). **Lifecycle**: show the
  fitted coefficients and which history window produced the curve.
- **Promotions period-aware** — `DemEvents` uses `'W12'/'W26'/'W40'`; bind to the period axis (1.2)
  and render real dates.
- **Override next to what it changes.** `OverrideCard` floats alone. Put it **beside the forecast and
  the resulting schedule preview**, statistical-vs-overridden side by side, with an audit line. You
  can't override what you can't see.

### 05 · PLAN / S&OP  — `plan.jsx`
Largely good (level-vs-chase hero, capacity duals, prebuild). Two fixes: make the **shadow-price →
Capital** hand-off a visible button (*"invest against this dual →"*); and the workforce/disagg are
sections of one flow, not separate tabs.

### 06 · PRODUCTION  — `production.jsx`
- **MPS day-level.** `ProdMPS` is weekly (W01–W08). Add a **grain toggle (day/week)**; default to
  **day** inside the frozen fence, week beyond. A schedule a planner can't read by day isn't executable.
- **ATP/CTP — interpret inline.** `ProdATP` shows numbers with no reading. Add: *"ATP = on-hand +
  scheduled receipts − committed = what you can still promise. CTP = ATP + what you could still
  produce in time. Row says: you can promise N units by [date]."*
- **Changeover — show the win.** `ProdChange` shows the matrix; also show the **solver's chosen run
  order and the minutes saved** vs alphabetical, so the matrix has a payoff.
- This stage now also **owns Cycle Time & Line Assignment** (moved from Products).

### 07 · SOURCING  — `sourcing.jsx`
- **Per-part lens.** With the item selector set to a part, show *its* MRP (gross→net→planned PO on the
  period axis), *its* supplier(s), *its* inbound lane and landed cost — so "what subproduct am I looking
  at and its flow" is answered. Supplier master itself moves to Network (03); Sourcing consumes it.
- Keep the merged incoterm matrix and landed-cost worked example (those are good).

### 08 · LOGISTICS  — `logistics.jsx`
- This is **transport optimization output**, not master data (nodes/lanes/contracts now live in
  Network 03). Show **allocation** (DC→customer LP), **consolidation** (LTL→FTL saving), **CoG** — each
  as a **network-flow visual** (nodes + weighted lanes), distinct from a Monte-Carlo chart (see 1.6 /
  Part 5.4). Collapse the duplicate CoG cards into one config+result.

### 09 · FINANCE  — `finance.jsx`
Sole owner of WACC (one editor), NPV/IRR, budget, CAC, FX, assets, capital decisions (the prototype
already does this well). Just make sure Setup no longer mirrors WACC/CAC at all (the owner wants them
*out* of Setup, not mirrored).

### 10 · CONSOLE  — `console.jsx`
Keep the run console (mode + constraints + solve + status/duals). **Use the single solver-network
graph from 1.3** (delete `CartesianSolverMap` as a second, different drawing — render the same
component as Home with a `layout="cartesian"` prop if you want the plane view). Results deep-link back
to stages 04–09 rather than re-hosting everything.

### 00 · HOME  — `home.jsx`
- KPI strip → **drill-down tiles** (1.5).
- **One** solver graph (1.3), shared with Console.
- **One** control-tower source: Home shows a 3-line summary, Scenarios shows the full list, both read
  the same `alerts[]` — not two hardcoded copies. Label the summary *"top 3 of N — full list in
  Scenarios."*
- **Pipeline ribbon**: label it clearly as **one pipeline with 6 stages** (not six things). Add a tiny
  caption: *"one end-to-end solve · click a stage to open it."* Stage chips show done/running/blocked.

---

## PART 4 — Defect register (every owner concern → fix → file)

| # | Owner's concern | Fix | File(s) |
|---|---|---|---|
| 1 | "Do we have 7 solvers?" | No — 16 in 5 families; fix data + label | `data.jsx`, `chrome.jsx`, `console.jsx` |
| 2 | Solver flow in Home ≠ Console | One graph, one data source, shared component | `home.jsx`, `console.jsx`, `data.jsx` |
| 3 | MC vs transport same-looking | MC=histogram/fan ("N runs"); transport=flow map | `console.jsx`, `logistics.jsx` |
| 4 | "6 pipelines?" | One pipeline, 6 stages; add caption | `chrome.jsx` |
| 5 | Control tower in 2 places | One `alerts[]` source; Home=summary, Scenarios=full | `home.jsx`, `scenarios.jsx` |
| 6 | WACC/CAC still in Setup | Remove from Setup entirely → Finance | `setup.jsx`, `finance.jsx` |
| 7 | Company name unreadable / cluttered | Big title field; MSME = derived badge | `setup.jsx` |
| 8 | Why 4 sub-tabs in Setup | 0 sub-tabs; one short flow | `setup.jsx` |
| 9 | Locations flow not per-item | Per-item inbound/outbound lanes; item-aware capacity | new `network.jsx` |
| 10 | On-hand/transport/contracts before products | Move to Network, after Products; add rate-by-period | `setup.jsx`→`network.jsx` |
| 11 | No "define product" screen | Add Define-Products first section | `products.jsx` |
| 12 | BOM 15–20 fields | physical / commercial split + time-varying price | `products.jsx` |
| 13 | Inventory policy as input? | Mark derived; show formulas | `products.jsx` |
| 14 | Cycle/line/MTO "random inserts" | Move cycle/line → Production; Products = Define·BOM·Costs·MTO | `products.jsx`,`production.jsx` |
| 15 | No history to enter / which product? | History grid + persistent item selector | `demand.jsx`, `lib.jsx` |
| 16 | Multi-grain entry for accuracy | day/week/month entry with Σ roll-up | `demand.jsx` |
| 17 | Low-data forecasting + where ML shows | Sparse-data banner; inline ML results | `demand.jsx` |
| 18 | Override without seeing schedule | Place override beside forecast+schedule | `demand.jsx` |
| 19 | Models lack formulas | Formula + note per model; define MASE/TS | `demand.jsx` |
| 20 | ABC/XYZ & lifecycle interpretation | Feeds + action per cell; show curve derivation | `demand.jsx` |
| 21 | Promotions "W12" not period-aware | Bind to period axis; real dates | `demand.jsx`,`products.jsx` |
| 22 | MPS weekly only | Day-level + grain toggle; frozen fence by day | `production.jsx` |
| 23 | ATP/CTP/changeover unclear | Inline definitions + chosen run order/savings | `production.jsx` |
| 24 | Sourcing — which subproduct + flow | Per-part lens via item selector | `sourcing.jsx` |
| 25 | Everything period-aware, grain/horizon explicit | One calendar axis app-wide | `data.jsx` + all |

---

## PART 5 — Answers to the owner's direct questions

**5.1 Do companies really run one consolidated dashboard (margin/fill/OTIF/inv/cash)? Single vs many
products?** Yes — it's the standard S&OP / control-tower exec deck. **But only with drill-down.** One
product → the dashboard *is* that product (still show per-period, per-location). Many products → a
flat company total hides everything; every tile must drill company→family→SKU→location→period and
segment by ABC/XYZ. Keep the deck, kill the faceless totals.

**5.2 Do we have 7 solvers, and is the flow accurate?** No — **16 engines in 5 families** (Part 1.3).
The prototype's 7-node graph is incomplete (missing forecast, aggregate, disaggregate, reconcile,
cvar, sequencing, lotsizing, consolidate, rolling) and is drawn *twice, differently*. Replace with the
single family graph.

**5.3 Monte Carlo vs Transport.** Different kinds: MC is a **stochastic simulation** → fan/histogram
labelled "1,000 runs", with VaR/CVaR. Transport is a **deterministic network-flow optimization** →
a node/lane flow map + cost table. Never the same card.

**5.4 The pipeline / "6 pipelines."** There is **one** pipeline (the end-to-end solve chain); the
ribbon shows its 6 **stages**. Label it so. Stage state = done / running / blocked-needs-input.

**5.5 Control tower in two places.** Fine **iff** one `alerts[]` source rendered twice (Home summary +
Scenarios full). Not two hardcoded copies. Say "top 3 of N."

**5.6 WACC/CAC in Setup.** Remove entirely → Finance. Setup = identity + calendar only.

**5.7 Why sub-tabs everywhere.** Don't. 0 sub-tabs on Setup/Plan/Sourcing/Logistics; keep them only
where there are true parallel modes (Finance, Console, Scenarios). Flow beats tabs.

**5.8 Where do I define my products / why does it open on BOM?** Bug — add the Define-Products screen
as Products' first section; BOM follows once a product exists.

**5.9 MPS only weekly.** Add day-level with a grain toggle; frozen fence in days.

**5.10 Grain & horizon.** One calendar object (grain + horizon + start) drives one period axis the
whole app renders against (Part 1.2). No hand-typed period strings anywhere.

---

## PART 6 — Handoff rules (unchanged from v1, reinforced)
1. Build the **data model in Part 1 first** (item identity + selector, period axis, real solver list,
   per-item flow). Everything else depends on it.
2. **Spine, dependency-gated.** A stage with unmet prerequisites shows "define X first →", never an
   empty grid or a chart with no item.
3. **Every output**: formula + "so what", inline.
4. **Sub-tabs are a last resort** (Part 2).
5. Keep `lib.jsx`, the themes, `SectionInfo`, `DevNote`, the dataset realism.
6. Don't touch backend solver names / payload contracts; this is UI + mock-data structure only.

**Deliverable:** the same multi-file React prototype, re-sequenced into this spine, with the Part-1
data model actually built, every screen honoring item/period/interpretation, nothing half-defined.

---

## PART 7 — Planning logic, solver triage & the ingestion layer

*This is the layer the prototype is missing entirely. Without it the app reads as 16 disconnected
engines and a toy data-entry grid. Everything below is structural, not cosmetic — it changes what
screens exist and when they appear.*

### 7.1 The planning spine — the order, and what is CONDITIONAL

```
1 DEMAND      committed demand / item / period                         (always)
2 AGGREGATE   meet it? level-vs-chase, OT, prebuild + CAPACITY DUALS    (skip if capacity never tight)
3 PROFIT MIX  which products win scarce hours                          (ONLY if capacity binds)
4 MPS         time-phase the chosen qty (day in frozen fence)           (always)
5 MRP/PROCURE explode BOM → what/when/who to buy                        (always)
6 SEQUENCE    run order per line, changeover-min                        (skip if 1 line / no changeover)
7 TRANSPORT   move FG out                                               (skip if single-site / no dist)
8 RISK MC/CVaR stress the plan                                          (optional overlay)
9 CAPITAL     invest where a dual is high & persistent                  (optional)
```

Two principles the prototype violates:

- **Profit mix exists only to ration scarce capacity.** If 100% of demand is makeable, there is no
  mix decision — make it all, and the stage is **hidden**. Its inputs are the per-period forecast
  (the **demand ceiling**) and firm orders (the **MTO floor**); objective = max Σ(margin×qty) s.t.
  capacity, materials, ceiling, floor. The owner stated this correctly himself.
- **S&OP is where Sales' demand, Ops' capacity and Finance's margin collide.** The solvers *inform a
  human consensus*; Sales is not expected to know profit-mix a priori — the tool shows them what
  their optimism costs (the shadow prices). Forecast → solvers inform the S&OP meeting → committed
  plan → MPS → buy → make.

### 7.2 The solver IO contract — render this on every result

Each result card states, inline (use the existing `Reading` component, extended): **came from solver
X · feeds stage Y.** This kills the owner's "no clue where what occurs."

| Solver | Answers | Inputs | Output | Feeds |
|---|---|---|---|---|
| Forecast | future demand | history, events | qty/item/period + MAPE | Aggregate, Profit-mix ceiling |
| Aggregate/S&OP | meet it? level/chase | forecast, capacity, labor cost | envelope + **capacity duals** | Profit-mix, Capital, MPS |
| Profit mix | mix when capacity binds | ceiling, MTO floor, capacity, margin | qty/product + contribution | MPS, Procurement |
| MPS | time-phase qty | mix, lines, lot size | day/week schedule + **ATP** | MRP, Sequencing |
| MRP/Procure | what/when/who to buy | MPS, BOM, on-hand, contracts | PO plan + shortages | Sourcing, Cash |
| Sequence | order on line | jobs, changeover matrix | run order + setup saved | shop floor |
| Transport | ship FG | flows, lanes, modes | lane allocation + cost | 3PL |
| Monte Carlo | how fragile | distributions + base plan | cost distribution, P95, CVaR | hedging, Capital |
| Capital | add capacity? | duals, CapEx, WACC | NPV/IRR fund/defer | Finance verdict |

### 7.3 Adaptive triage — Setup captures a profile; stages turn on/off

Setup adds a **Planning Profile** block. Its answers gate the spine (don't show all 16 engines to a
new user):

| Profile input | Effect when … |
|---|---|
| Make policy (MTS / MTO / ATO mix, per-SKU) | pure MTO + ample capacity → hide Profit-mix & seasonal Aggregate |
| Capacity tightness (tight / ample) | ample → Profit-mix **hidden** (make everything) |
| Imports? (yes/no) | no → hide landed-cost, FX, incoterms |
| Lines (1 / many) | 1 → hide Sequencing |
| Distribution? (single-site / network) | single-site → hide Transport |
| **Forecast supplied externally?** (yes/no) | yes → hide Demand model-competition (see 7.5) |

Stages that are gated off are **hidden or marked "not needed for your setup,"** not left as empty
grids. This is the primary lever against the "16 engines, no idea what to run" problem.

### 7.4 Item-method routing — not everything needs MILP

The owner's sharpest catch: *"if (s,S)/ROP/EOQ are derived, why MILP?"* Answer: **they're for
different items, and the app currently MILPs everything.**

- **(s,S)/EOQ/ROP = autopilot** for independent-demand, stable, low-value items (C/Z class, MRO).
  Managed item-by-item by a rule. **No solver.**
- **MILP/MRP** for dependent demand and *coupled* decisions: shared capacity, MOQs, price breaks, a
  budget split across many parts, a contract price that steps mid-horizon. A reorder point can't
  express "the optimal buy depends on a shared budget and a steel price that jumps in W29."

**ABC/XYZ must route the method**, and each item shows its tag: `autopilot (s,S)` vs `optimized
(MILP)`. AX/AY coupled → MILP; CZ stable → (s,S). Don't drag a stable washer through the optimizer.

### 7.5 Two ingestion modes — the toy grid is replaced

The 12-cell monthly grid is the single biggest unusability. Professionals hold daily, many-SKU data
and import it. **Two distinct import targets:**

1. **History import → we forecast it.** Universal **tidy long format**:
   `date, item, location, channel, qty[, price]`. **Any length (12/24/36+ months), any grain.** Stored
   at day grain, rolled up to the planning bucket. The model competition runs *on the user's data*.
   The editable grid survives only as a small-case / override tool, never the primary path.
2. **Forecast import → we skip forecasting.** For shops that already forecast elsewhere:
   `item, location, period, qty`. Drops the user straight at Aggregate/Profit-mix; Demand's
   model-competition is bypassed and labelled "external forecast loaded" (this is the 7.3 flag).

### 7.6 Confirmed defect fixes (from the owner's second-pass review)

| Defect | Fix |
|---|---|
| FX `84.20` hardcoded | editable FX **with as-of date** (ideally a small currency table); all `$→₹` reads it |
| MSME inputs re-typed in Setup | derive the **tier** (already done) but source turnover & plant-value **from Finance actuals**, don't duplicate-enter |
| Horizon shows start, not end | show computed **end period** + count: "52 weeks · W23'26 → W22'27" |
| No proof the calendar axis feeds production | visible binding line: "MPS / Procurement / Contracts all render this same horizon" |
| Products asks user for sell/make **%** | mix % is an **output of profit-mix**, never a catalog input — remove it as input |
| Lifecycle "fitted" on 24 pts | let user **pick a phase** tag; *optionally* fit if data supports; new SKUs borrow an analogous curve; stop claiming "fitted" |
| OEE forced | OEE is an **advanced** decomposition; allow a flat capacity rate (rate×hours) |
| Per-product procurement scattered | **product drill**: click a FG → its subparts, each part's supplier + inbound lane + landed/CIF + **backup supplier**. Master data still defined once in Network; the drill *assembles the view* ("define once, surface everywhere") |
| Readiness grid is a passive checkmark | make it **block** a solver and name the missing input + where to enter it |
