# Handoff: Enterprise Inventory Simulator — Supply-Chain OS

> NOTE (saved copy): these files were transcribed from the design handoff chat.
> Non-ASCII glyphs (₹, emoji, box-drawing comment bars, σ/μ/×/≤ …) arrived
> encoding-mangled and the `.jsx` copies preserve that mojibake. The CODE/LOGIC
> is intact and is what the port reads from. For a pixel-perfect, runnable copy,
> overwrite `app/*.jsx` + this folder with the clean originals from Claude Design.

## Overview

A planning-and-optimization workbench for a discrete manufacturer (mock tenant: *Tata
Precision Auto Components*, a Chennai auto-parts maker). It walks a planner, in strict
dependency order, from **defining what you make → modelling the network → demand →
S&OP → production → sourcing → logistics → finance**, and exposes a **solver console**
that runs 16 optimization engines (LP / MILP / simulation) grouped into 5 families.

The whole app obeys one rule: **every number is "how much of WHICH item, at WHICH
location, in WHICH time bucket,"** and **every result shows its formula + a one-line
"so what."** Build the data model first (below); the screens are projections of it.

This bundle is the **v4 build** — it implements the full `REDESIGN_BLUEPRINT_v2` including
**Part 7** (planning spine, solver-IO contract, adaptive profile gating, item-method
routing, two ingestion modes) and the **7.6 confirmed defect fixes**.

## About the Design Files

The files in this bundle are **design references built in HTML/JSX (React via in-browser
Babel)** — a clickable, high-fidelity prototype of the intended look and behaviour. They
are **not** the production codebase. The task is to **recreate these designs in the target
environment** using its established stack and patterns:

- The UI layer is React today but framework-agnostic in spirit; reimplement in the app's
  real React/Vue/Svelte/etc. with a proper bundler (Vite) instead of in-browser Babel.
- The **mock store `M`** in `app/data.jsx` stands in for real application state + API
  responses. Replace it with the codebase's state management (Redux/Zustand/RTK Query/etc.)
  and real `/api/solve/*` calls. **Do not change backend solver names or payload shapes** —
  this is a UI + mock-data-structure deliverable only.
- Every card carries a `</> ComponentName` **DevNote** chip in the prototype (click it).
  It names the **component, props, and state keys** that card should map to. Treat those
  as the canonical component inventory — they're the build checklist.

## Fidelity

**High-fidelity (hifi).** Final colours, typography, spacing, layout and interactions are
intentional and should be recreated faithfully. The "brutalist mono grid" aesthetic
(2px hard borders, 0 radius, monospace numerics, hard `5px 5px 0` shadows, three swappable
themes) is the design system — preserve it, driven by CSS variables so themes stay free.

## Architecture & File Structure

```
Enterprise Simulator.html     — entry point: theme tokens (:root + 3 themes), font links,
                                 React/Babel script tags, ordered module loads, #root mount
app/
  lib.jsx       — design-system atoms + shared logic (load FIRST). Exports to window.*
  data.jsx      — the single mock store M (load SECOND). All data + derived helpers.
  chrome.jsx    — app shell: masthead, pipeline ribbon, nav rail, footer, <Chrome>
  main.jsx      — <App>: theme + active-stage state (localStorage), stage registry, mount
  home.jsx        — 00 Home  (StageHome)
  setup.jsx       — 01 Setup (StageSetup)
  products.jsx    — 02 Products (StageProducts)
  network.jsx     — 03 Network (StageNetwork)
  demand.jsx      — 04 Demand (StageDemand)
  plan.jsx        — 05 Plan/S&OP (StagePlan)
  production.jsx  — 06 Production (StageProduction)
  sourcing.jsx    — 07 Sourcing (StageSourcing)
  logistics.jsx   — 08 Logistics (StageLogistics)
  finance.jsx     — 09 Finance (StageFinance)
  console.jsx     — 10 Console (StageConsole)
  scenarios.jsx   — 11 Scenarios (StageScenarios)
  reference.jsx   — 12 Reference (StageReference)
```

**Module contract:** each stage file defines its component(s) and assigns the stage root to
`window.StageXxx`. `lib.jsx` and `data.jsx` assign their exports to `window` (because each
`<script type="text/babel">` is transpiled in its own scope). When you move to a real
bundler, convert these `window.*` globals into normal ESM `import`/`export`.

## THE DATA MODEL (build this first — everything depends on it)

All of the following lives in `app/data.jsx` on the object `M`. These are the contracts the
real app must reproduce in its state shape / API responses.

### 1. Item identity + persistent selector
```ts
item = { id, code, name, kind:'FG'|'part', uom, family }
M.items            // finished goods
M.partsOf(sku)     // BOM parts of an FG
ui.activeItemId    // global selection (prototype: itemStore in lib.jsx, localStorage 'es_item')
```
`<ItemSelector/>` is pinned to every **planning** stage (Demand, Products, Production,
Sourcing) and writes `activeItemId`; every table/chart on that stage filters to it. View
toggle = `fg | parts`.

### 2. One period axis from the calendar (no hard-coded 'W12')
```ts
calendar = { grain:'day'|'week'|'month', start:'2026-06-01', count:52 }
periods  = buildPeriods(calendar)  // [{ id, label:'W23', date:'02 Jun', iso }]
M.pLabel(pid) / M.pDate(pid)
```
Every time-bound record stores a **period id** and renders `periods[id].label`. Changing the
grain re-buckets the whole app. `promos[].pid`, `costEvents[].pid` are already bound.

### 3. The real solver inventory — 16 engines, 5 families
```ts
M.solverFamilies   // forecast | plan | optimize | risk | capital
M.solvers[16]      // { id, name, fam, engine, status, obj, go }
M.solverEdges      // real /api/solve hand-offs (data dependencies) — drawn as edges
M.solverOrchestration  // pipeline | rolling | sop (meta-chains)
```
Rendered **once** by `<SolverNetwork/>` (lib.jsx) and reused identically on **Home** and
**Console** — do not draw two different graphs. Masthead/footer label it
**"16 engines · 5 families,"** never "7 solvers."

### 4. Per-item, directional flow
```ts
node     = { id, type:'plant'|'dc'|'wh'|'supplier'|'customer', geo, capacityUom, capacity }
lane     = { id, from, to, direction:'inbound'|'outbound', item, mode, rate, leadDays, contractId }
contract = { id, type:'spot'|'fixed'|'volume'|'take-or-pay', rateByPeriod:[[pid, price],…] }
onHand   = [{ item, loc, qty, uom }]   // item × location matrix
```
A node's capacity is consumed per item; lanes each carry ONE item in ONE direction.

### 5–6. Drill-down + interpretation contract
Every consolidated KPI is a drill button (company→family→SKU→location→period). Every result
renders `<Reading formula="…" soWhat="…">` inline — formula/source + one action sentence.

### 7. Planning logic & triage (the v4 additions)
```ts
M.planningProfile = { makePolicy, capacity, imports, lines, distribution, externalForecast }
M.profileGate(p)  // → { profitmix, sequencing, transport, landed, demandModels } (true = OFF)
M.stageGate(p)    // → { logistics } (whole-stage dim in nav)
M.spine[9]        // ordered solve chain; each step's `gate` references a profileGate key
M.solverIO[id]    // { answers, from, feeds } — the IO contract line per engine
M.itemMethod(sku) // 'autopilot' (s,S/ROP/EOQ rule) | 'optimized' (MILP) — routed by ABC/XYZ
M.ingestModes[3]  // history import (tidy long) | forecast import | manual grid
M.fxRates         // { asOf, base, rows:[{ccy,rate,src}] } — every $→₹ reads this
```
Prototype state for the profile lives in `profileStore` / `useProfile()` (lib.jsx,
localStorage `es_profile`). A gated capability renders `<GateNote>` ("not needed for your
setup — change in Setup"), **never** an empty grid. The nav rail dims stage-level gates.

## Source-of-truth references

- `REDESIGN_BLUEPRINT_v2.md` — the full design spec (Parts 0–7 + defect register).
- The in-app `ⓘ SectionInfo` (what it does / flows to) and `</> DevNote` (component wiring)
  popovers are authoritative per-card documentation.
