# Design Handoff — Supply-Chain Planner

**This is the only file the redesign tool needs.** It is the *canonical* list of every screen and
section that exists, the design system already in use, the known layout problems to solve, and a
hard list of things that must not change. Everything here was verified against the live
`index.html` by resolving each card to the **component that actually renders it** (not where its
code happens to sit in the file).

---

## 0 · Rules for the redesign (read first)

1. **Do not invent sections.** Every section that exists is listed in §3. You may **merge,
   reorder, relabel, restyle, and group into sub-tabs**. You may not add screens or fields that
   aren't in §3 without flagging them as net-new.
2. **Preserve component invocations and their props.** Each section is rendered by a named React
   component or inline block (named in §3). When you move/regroup a section, keep its invocation
   intact — e.g. `<HistoryPanel prod={prod} … />` must still receive the same props. Changing
   props or state keys breaks the solver wiring (see §5).
3. **Reuse the existing design system** in §1. Do not introduce a new color system, spacing
   scale, or component kit — the app already has one, with light/dark/sepia themes driven by CSS
   variables. Restyle *within* it.
4. **Output target:** the same single-file React+Babel SPA. Components are plain function
   components using a shared `dispatch` reducer. No router, no CSS-in-JS library.

---

## 1 · Design system already in place (reuse, don't replace)

**Theme:** CSS custom properties, themed (dark / light / sepia). Never hard-code hex — use the vars.

| Token | Role |
|---|---|
| `--bg` `--bg2` `--bg3` `--bg4` | surfaces (page → card → inset, dark→light per theme) |
| `--br` `--br2` | borders |
| `--ac` `--ac2` | primary accent (teal `#00d4aa` in dark) |
| `--a2` `--a3` `--a4` | secondary accents (blue / violet / amber) |
| `--gn` `--dg` `--hl` `--hl2` | semantic: good / danger / highlight |
| `--tx` `--tx2` `--tx3` | text primary / secondary / muted |

**Component classes (already styled — reuse verbatim):**
`card` · `card-title` · `badge` · `data-table` · `btn` `btn-sm` `btn-primary` `btn-secondary`
`btn-danger` · `grid2` `grid3` `grid4` (responsive column grids) · `kpi-row` `kpi` `kpi-val`
`kpi-lbl` `kpi-sub` · `vgrid` · `tag` `tag-ghost` · `sep` · `animate-in` (entrance) · `num`
(tabular-figures).

**Shared building blocks (function components, reuse — do not re-implement):**
`Field` (labeled input wrapper) · `NumInput` (numeric input: `{value,onChange,min,max,step,
placeholder,disabled,title}`) · `KPI` (metric tile) · `SectionInfo` (the `ⓘ` popover that carries
"what it does / flows to" help — **keep these; they're the contextual docs**) · `Panel`/`Blk`-style
metric blocks.

**Card anatomy today:** `.card` → `.card-title` (emoji + name + optional `badge` + `SectionInfo`)
→ body (grids / `data-table` / KPIs / inputs). Keep this anatomy; improve density and grouping.

---

## 2 · Known layout problems to solve (the real ones, verified)

These are the *only* structural issues the redesign should fix. (Earlier notes about "Setup being
a 16-card finance dump" were a file-position artifact and are **not** real — see §3, Setup is 11
cards and the finance/demand cards already live on the correct tabs.)

| # | Problem | Fix the redesign should apply |
|---|---|---|
| P1 | **"Optimize & Solve" renders ~34 sections** — every solver's result lives here in one endless scroll. | Split into a **run console** (mode picker + constraint toggles + solve button + status/objective/shadow-prices) and **result sub-tabs grouped by solver** (Procurement · Production · Profit · Transport · Risk/MC · Capital · S&OP · Pipeline · Rolling). Same components, grouped under a sub-tab nav. |
| P2 | **"Risk & Scenarios" renders ~28 sections** flat. | Sub-tab by intent: **Risk** (Control Tower, Monte Carlo, Sensitivity, Scenarios, Lost Sales, Risk Matrix, Disruptions) · **Cost** (TCO, Cost Waterfall, Working-Capital, FVA) · **Performance** (EVM, S&OP Gap, KPI Dashboard) · **Explore** (What-If Bot, What-If Sensitivity, Auto-Researcher, Multi-SKU, Live Insight, Parameter Cascade). |
| P3 | **Finance already uses an audience sub-tab nav** (`cashflow·capital·cac·assets·bvl·fx·npv`). | Use Finance as the **pattern** for P1/P2. Copy its sub-tab navigator look. |
| P4 | **Two WACC editors** — one on Setup, one on Finance. | Keep the **Finance** WACC as the editor; on Setup show WACC **read-only** with a "edit in Finance →" link. (Code-side dedup is a separate decision; design should present one editor.) |
| P5 | **Card titles are wide and dense** (e.g. BOM row ≈ 12 fields). | Apply progressive disclosure: primary fields visible, advanced/commercial fields behind an "Advanced ▸" reveal. Keep all fields. |
| P6 | **The solver pipeline (Demand→Aggregate→Profit→Procure→Produce→Ship) is the product's spine but invisible.** | Add a persistent **pipeline ribbon / breadcrumb** at the top that shows stage completion and doubles as navigation. |

> **Coverage caveat for the redesign tool:** §3 counts `.card-title` sections. Two tabs —
> **Production Architecture** and **Command Center** — render rich non-card UI (line→stage→machine
> tree editors, dependency graphs, KPI grids) that isn't a `.card`. Treat those tabs' bodies as
> first-class screens to lay out, not just the cards listed.

---

## 3 · CANONICAL section inventory (per tab as actually rendered)

Format: `[ComponentThatRenders] Section name`. `(+guard)` = a second match that is an empty-state
placeholder for the same card, not a separate section — render as one. Line numbers are
indicative (pre-cleanup) anchors into `index.html`.

### 01 · Setup — Company & Calendar  (`SetupTab`)
- `[SetupTab]` 🏢 Company Profile — identity, currency, GST, plant state, tax rate, service level
- `[SetupTab]` 📅 Planning Calendar — horizon×unit, grain, workdays, holidays
- `[SetupTab]` 🏷️ MSME Classification — investment/turnover → tier (drives tax, 43B(h) terms)
- `[SetupTab]` 📍 Locations Master — physical nodes (plant/WH/DC/cust/supplier)
- `[SetupTab]` 📦 Per-Location On-Hand — starting inventory per site
- `[SetupTab]` 🚚 Transport Modes & Contracts — mode rates, contract types
- `[SetupTab]` 💰 Master Budget Envelope — split capital across 5 heads + reserve
- `[SetupTab]` 🎯 CAC Summary — cost-to-acquire anchor (full economics on Finance)
- `[SetupTab]` 📋 Order Book — read-only all-MTO view (edits on Products)
- `[SetupTab]` 🎯 Industry Preset — one-shot defaults
- `[WACCCard]` 💹 WACC Calculator — discount rate *(duplicate of Finance — see P4)*

### 02 · Products & BOM  (`ProductsTab`)
- 🔧 Bill of Materials — parts, qty/u, cost, LT, MOQ, ordering S, holding%, shelf-life, supplier
- 💵 Fixed & Setup Costs — setup cost, labor/unit (double-count guard)
- 📋 Make-to-Order (MTO) — per-SKU orders (the edit home for Order Book)
- ⚙️ Product Parameters — capacity, MAPE, yield, OEE, price, shelf-life, demand mode
- 🏭 Production — Cycle Time & Line Assignment — per-SKU cycle time + line
- 📅 Cost Events — Rolling Horizon — period-indexed cost step-changes
- 📁 Data Import/Export — save/load JSON *(consider promoting to app header)*

### 03 · Demand Planning  (`DemandTab`)
- `[HistoryPanel]` 📊 Historical Time Series — demand history entry (grain-aware cascade)
- `[ServerForecastCard]` 🤖 Server-Side ML/DL Forecast — `/api/forecast` (classical→ML→hybrid→DL)
- 📈 Forecast Comparison + 🏆 Forecast Model Competition — leaderboard, MASE/bias/tracking-signal, intermittent (Croston/SBA/TSB) *(merge these two into one)*
- ⚖ Demand-Ceiling vs MTO-Floor · 🏷️ ABC/XYZ Segmentation · 🔄 Lifecycle Curve · 🎯 Promotions & Events · 🎯 Consensus Workflow · ✏️ Demand Override

### 3B · Aggregate Plan / S&OP  (`AggregateTab`)
- Level-vs-Chase strategy classification (hero result) · Seasonal prebuild detector · Workforce (hire/fire/OT) plan · Capacity shadow prices · SKU disaggregation

### 04 · Production Architecture  (`ProductionArchitectureTab`)  *(rich non-card UI — see caveat)*
- 🏭 Production Architecture — lines→stages→machines/cycle/OEE; bottleneck = min(stage); derived caps
- `[MPSVizCard]` 📅 Master Production Schedule (MPS)
- *(plus inline line/stage/machine tree editors, ATP/CTP — not `.card`-wrapped)*

### 05 · Suppliers & Procurement  (`SupplyTab`)
- `[OTIFLedgerCard]` 📒 OTIF Ledger · `[PoReleasePlanCard]` 📦 PO Release Plan · `[ShortageForecastCard]` ⚠ Shortage Forecast
- 🛣️ Physical Network (Nodes & Lanes) · 🛃 Incoterm Responsibility Matrix · 📋 Supplier Master · 🛃 Landed Cost Rollup · 🧭 Inbound Network Topology · 📖 Incoterms Quick Reference · 🛃 Import Tools
- *(merge the two incoterm cards into one matrix+hover-ref)*

### 06 · Logistics & Network  (`LogisticsTab`)
- `[CenterOfGravityCard]` 📍 Center of Gravity (config + result — render as one)
- `[LogisticsBudgetGateCard]` 💰 Logistics Budget Gate · `[LogisticsNodeMasterCard]` 🏭 Network Node Master · `[LogisticsLaneEditorCard]` 🛣️ Multi-Hop Lane Network · `[TransportContractLedgerCard]` 📋 Transport Contract Ledger · `[ThreePlProviderCard]` 🚛 3PL Provider Master · `[MTODeliveryScheduleCard]` 📅 MTO Delivery Schedule (+guard)
- `[TransportAllocationCard]` 🚛 Transport Allocation Matrix (+guard) *(currently surfaced on Command — belongs here)*

### 07 · Finance & Costs  (`FinanceTab`) — **already sub-tabbed: `cashflow·capital·cac·assets·bvl·fx·npv`**
- `[WorkingCapitalPeriodCard]` 📊 Working Capital — Period View · `[BudgetPlanVsActualCard]` 📈 Budget — Plan vs Actual · `[PaymentLedgerCard]` 📒 Payment Ledger · `[ProcurementRiskCard]` ⚠ Procurement Risk & FX Hedging
- 📚 WACC explainer · 🎯 Customer Acquisition Economics · 📊 Cost Structure per SKU · 💳 Working Capital & CCC · 🏭 Asset Register · 🔄 Buy vs Lease · 💸 Projected Cash Flow · 🛡️ Currency Hedging · 🏦 Master Budget & Capital Structure · 📐 WACC Calculator · 💎 NPV/IRR Calculator · 📉 Asset Depreciation · 📈 Plan NPV (MPS-driven)

### 7B · Investment Decision  (`InvestmentDecisionTab`)
- 💎 Investment Decision · 🏗️ Endogenous-Capacity Capital Plan (consumes Aggregate shadow prices) · 📊 Cash Flow Builder · 🏦 Equity Sources & Opportunity Cost · ⚖️ Investment Verdict · 🏭 Per-Line CapEx Proposals (+guard)
- *(heavy overlap with Finance/capital — design may present 7B as a "Capital Decisions" sub-tab of Finance)*

### 08 · Optimize & Solve  (`OptimizeTab`) — **god-tab, apply P1**
Run control: ⚡ Optimization Engine (mode picker + constraint toggles + solve).
Results (group into solver sub-tabs):
- **Procurement:** 📦 Procurement MILP Results · 🌐 Multi-Echelon Inventory · 🧾 PO Register · 📊 RM Timeline · 📋 Reorder Policy (s,S)/(R,Q) · 🌪️ Regime-Aware Sourcing · 🔄 MRP Explosion
- **Production:** 📋 Production Schedule (per product) · 🏭 Production Schedule Results · 🔀 Sequence-Dependent Changeover · 📋 Production Order Register · 📦 Product Fulfillment · 💤 Shutdown Candidates · 🏭 Line-Level Execution · 📊 Line×Period Matrix · 📅 Gantt · 📅 MPS · 📦 Order Promising (ATP/CTP) · ⚡ Capacity Conflict Check
- **Profit:** 💰 Profit Maximizer Results
- **Other modes:** 🚛 Transport Results · 🎲 Monte Carlo Results · 🏗️ Capital Budget Results · 🔁 Closed-loop S&OP (+ reconciled-mix) · 🔗 Pipeline (3 steps) · 🔄 Rolling-Horizon MPS + Wave Comparison + Final-Wave PO Register · 📤 MILP Export

### 09 · Risk & Scenarios  (`AnalysisTab`) — **apply P2 sub-tabbing**
- `[AnalysisTab]` 🚨 Control Tower · 🔬 Analysis Engine · 🎲 Monte Carlo · 📊 Sensitivity · 🔬 Auto-Researcher · 🏗️ TCO per SKU · 📈 EVM · 📊 Cost Waterfall · 📋 Multi-SKU Comparison · 💳 Working Capital (Cash Tied) · 📐 FVA · 🩸 Lost Sales · 📋 S&OP Gap · 🤖 What-If Bot · 🎚️ What-If Sensitivity · 📄 Report Export
- `[InsightEngineCard]` 🧠 Live Insight · `[MultiSKU15]` 📋 Multi-SKU 15-Section (+guard) · `[CascadeTracker]` 🔗 Parameter Cascade · `[MrpBucketGridPanel]` 📅 MRP Bucket Grid (+guard) · `[StakeholderMatrixCard]` 👥 Stakeholder Power×Interest · `[KpiDashboardPanel]` 📊 KPI Dashboard · `[DisruptionRegistryCard]` ⚡ Disruption Registry · `[EventLogCard]` 📋 Event Log · `[VersionHistoryCard]` 📜 Version History · `[RiskMatrixCard]` ⚠ Risk Matrix
- *(also renders `[ScenariosCard]` Scenarios and `[InventoryProjectionCard]` Inventory Projection)*

### 10 · Command Center  (`CommandCenterTab`)  *(rich non-card UI — see caveat)*
- 🎯 How the 7 Solvers Communicate · ✅ Solver Input Readiness · *(plus the KPI / cascade / readiness surfaces — strong candidate to become the app HOME / landing screen)*

### 11 · Learning Lab  (`LearningLab`)
- Concept explainers *(consider folding into the inline `SectionInfo` popovers)*

### 12 · SAP Mode  (`SAPModeTab`)
- 🏢 SAP Mode header · Overview · Physical Network · Master Data · Planning Runs · T-Code Cheatsheet · ML Demand Sensing · Stochastic/CVaR Solver *(parallel multi-plant world — design as a reference/T-code overlay unless multi-plant is committed)*

---

## 4 · Target information architecture (optional — the direction, not a mandate)

If you re-organize navigation, collapse 14 flat tabs → a **Home + workflow stages**, each with the
Finance-style sub-tab nav. Nothing is deleted — sections relocate to their owner:

```
HOME        Pipeline ribbon · Solver-input readiness · KPI dashboard · Control-Tower alerts
SETUP       Company · Calendar · MSME · Industry-preset(wizard)
PRODUCTS    BOM(physical|commercial) · Costs · SKU params · MTO · Cost events
DEMAND      History · ML forecast · Competition · ABC/XYZ · Lifecycle · Promotions · Consensus · Override
PLAN(S&OP)  Aggregate level-vs-chase · Prebuild · Workforce · Shadow prices · Profit-mix result
PRODUCTION  Lines→stages→machines/OEE (sole owner of cycle/OEE) · MPS · ATP/CTP · Changeover · Schedule
SOURCING    Suppliers · BOM buy-terms · Landed cost · Incoterms(one) · OTIF · PO/Reorder/Regime/MRP results · Import
LOGISTICS   Nodes · Lanes · 3PL · Contracts+modes · Center-of-Gravity · Transport mode/consolidation/allocation
FINANCE     cashflow · capital(WACC/NPV/budget) · capital-decisions(was 7B) · assets · bvl · cac · fx
CONSOLE     Solver run console (was Optimize) — links results back into the stages above
SCENARIOS   One unified scenario/disruption store
REFERENCE   Learning Lab · SAP T-code map
```

---

## 5 · DO NOT TOUCH (these break the app)

- **State keys / shape:** `state.config`, `state.products`, `state.network.nodes`, `state.production`,
  `state.budget`, `state.planning`, `state.aggregatePlan`, etc. Reducer action types
  (`SET_FINANCE`, `SET_AGGREGATE_PLAN`, `SOLVE_FINISHED`, …) and the `dispatch(...)` calls.
- **Solver payload contract:** the UI sends **camelCase** state that maps to **snake_case** solver
  payloads. Field renames that change what's POSTed to `/api/solve/*` or `/api/forecast` break the
  backend. Restyle labels, not payload keys.
- **Component props:** keep each section's component invocation and its props (e.g.
  `prod`, `activeId`, `state`, `dispatch`). Sub-tab gating wraps a render; it must not drop props.
- **`SectionInfo` content:** the `ⓘ` help text is the contextual documentation — preserve it
  (you may restyle the popover).
- **Backend / solvers** (`app.py`, `*.py`): out of scope for the redesign.
