# Supply-Chain Planner — Design Source of Truth & UX Audit

**Purpose of this file.** A single, authoritative map of every page and every section in
`index.html`, written so a redesign tool (or a human) can re-skin / re-organize the app
**without inventing screens that don't exist**. Each page lists its real sections (with
source line numbers), what each section *asks for* and *feeds*, and a three-lens critique:

- 🧭 **Critic** — coherence, redundancy, "why is this asked here?"
- 🎨 **UI** — layout, density, discoverability, progressive disclosure
- 📦 **Domain (SCM/OR)** — is this the right model / the right input / the right place?

> **Rule for the redesign tool:** Treat *Part 4 (Section Inventory)* as canonical. Do not add
> sections that aren't listed there. You may **merge, reorder, relabel, and restyle** sections,
> and you may move a section to the page proposed in *Part 3*. Every section maps to existing
> React state and an existing solver endpoint — preserve those bindings (named per section).

App shape: one React+Babel SPA, 14 top-level tabs, ~149 cards. Backend = Flask (`app.py`)
+ PuLP/CBC solver modules. State is one reducer tree (`state.config`, `state.products`,
`state.network`, `state.production`, `state.budget`, `state.planning`, `state.aggregatePlan`, …).

---

## Part 0 — System Map (the 14 tabs as they exist today)

| # | Tab | Component @line | Owns (today) |
|---|-----|------|--------------|
| 01 | **Setup** — Company & Calendar | `SetupTab` @3080 | Identity, tax, MSME, calendar, locations, on-hand seed, transport modes, budget envelope, CAC, order book, **WACC, working capital, payment ledger, ML forecast, historical series** |
| 02 | **Products & BOM** | `ProductsTab` @4581 | BOM, fixed/setup costs, MTO orders, per-SKU parameters, cycle-time/line assignment, cost events, import/export |
| 03 | **Demand Planning** | `DemandTab` @5609 | Ceiling-vs-floor, ABC/XYZ, lifecycle, promotions, forecast competition, consensus, override |
| 3B | **Aggregate Plan / S&OP** | `AggregateTab` @6114 | Hax–Meal level-vs-chase LP, prebuild, capacity shadow prices |
| 04 | **Production Architecture** | `ProductionArchitectureTab` @8425 | Lines→stages→machines/OEE, MPS, ATP/CTP |
| 05 | **Suppliers & Procurement** | `SupplyTab` @9602 | OTIF, PO release plan, shortage forecast, supplier master, landed cost, incoterms, import tools |
| 06 | **Logistics & Network** | `LogisticsTab` @10482 | Physical network, lanes, 3PL, contracts, **Center of Gravity (×2)**, FX/risk, budget gate, MTO delivery |
| 07 | **Finance & Costs** | `FinanceTab` @11389 | **Sub-tabbed**: cashflow · capital · cac · assets · bvl · fx · npv |
| 7B | **Investment Decision** | `InvestmentDecisionTab` @11007 | Endogenous-capacity capital plan, cash-flow builder, equity/opp-cost, verdict, per-line CapEx |
| 08 | **Optimize & Solve** | `OptimizeTab` @6339 | **God-tab**: results for all 9 run modes (profit, procurement, production, pipeline, S&OP, transport, MC, capital, rolling) + every result card |
| 09 | **Risk & Scenarios** | `AnalysisTab` @12311 | Control tower, MC, sensitivity, TCO, EVM, FVA, lost sales, S&OP gap, what-if, scenarios, MPS, inventory projection, multi-SKU |
| 10 | **Command Center** | `CommandCenterTab` @14648 | Solver-comm diagram, readiness, parameter cascade, transport matrix, MRP grid, stakeholders, KPI dashboard, disruption registry, event log, risk matrix |
| 11 | **Learning Lab** | `LearningLab` | Concept explainers |
| 12 | **SAP Mode** | `SAPModeTab` @15306 | Multi-plant scenario what-if, T-codes |

**Headline:** the tab *labels* promise a clean linear workflow (Setup → Products → Demand →
Plan → Produce → Source → Ship → Finance → Optimize → Analyze). The *contents* don't honor it:
Setup and Analysis are catch-all dumping grounds, "Optimize" hoards every solver's output, and
three tabs (Analysis, Command, SAP) all do "scenarios/disruptions." Finance is the one tab that
was already refactored into audience sub-tabs — that's the template for the rest.

---

## Part 1 — Cross-Cutting Findings (fix these first; they dwarf any single card)

### F1 · "Optimize" is a god-tab; results are split from their home tabs
`OptimizeTab` (6339–8424, ~2,000 lines) renders the result cards for **all nine** run modes:
Procurement MILP results (7148), Production schedule (7162/7417), Multi-echelon (7201), PO
register (7290), Reorder policy (7344), Regime sourcing (7369), MRP explosion (7384), Profit
maximizer (7601), Transport results (7744), Monte Carlo (7785), Capital budget (7812), S&OP
(7834), Pipeline (7861), Rolling MPS (7897).
Meanwhile dedicated tabs exist for Supply, Logistics, Production, Invest — so a user who runs
procurement sees the *result* on Optimize but maintains the *inputs* on Supply. **Inputs and
outputs of the same solver live on different tabs.**
→ *Fix:* keep Optimize as the **run console** (pick mode, set constraints, hit solve, see status
+ objective + shadow prices), but **route each result card back to its domain tab** (procurement
results → Supply, production schedule → Production, transport → Logistics, capital → Invest,
profit → a dedicated Plan tab). One solver = one home.

### F2 · Same instrument rendered in 2–4 places
| Instrument | Appears on | Verdict |
|---|---|---|
| **WACC calculator** | Setup (3809), Finance/capital (12118), Finance explainer (11497) | Keep **one** editor (Finance→capital); everywhere else show the *value* read-only with a link |
| **Working Capital** | Setup period-view (4209), Finance CCC (11595), Analysis cash-tied (12767) | One WC engine, three *views* of it — consolidate the math, keep at most two views |
| **Monte Carlo** | Optimize (7785), Analysis (12530) | Pick one home (Analysis); Optimize just links to it |
| **MPS** | Production (8214), Analysis (13689), SAP MRP grid (15558) | One MPS object, surfaced where consumed; don't recompute per tab |
| **Budget envelope** | Setup (3447), Finance Master Budget (11961) | One editor; Setup shows summary |
| **CAC** | Setup (3497), Finance/cac (11543) | Setup = anchor, Finance = full economics — *intentional*, but make the split explicit |
| **Center of Gravity** | Logistics (10132 **and** 10230) | Two COG cards in one tab — collapse to input+result of a single card |
| **Transport allocation/results** | Optimize (7744), Command (15155) | Logistics is the natural home for both |
| **Scenarios / disruptions** | Analysis scenarios (13468), Command disruption registry (16083), SAP scenarios (15320) | Three scenario engines — unify into one scenario store |

### F3 · "Setup" is not setup — it's a 16-card mega-scroll
`SetupTab` mixes three unrelated jobs: **master data** (company, calendar, MSME, locations,
on-hand, transport modes, industry preset), **treasury** (budget envelope, WACC, working-capital
period view, budget plan-vs-actual, payment ledger), and **demand** (historical time series, ML
forecast). A new user opening "Company & Calendar" is hit with a payment ledger and a neural-net
forecaster. → Split per Part 3.

### F4 · No sub-navigation on the three biggest tabs
Finance was refactored into 7 audience sub-tabs (`cashflow·capital·cac·assets·bvl·fx·npv`) — clean.
Setup (16 cards), Analysis (~22 cards), Command (~11 cards) are still flat vertical scrolls.
→ Apply the Finance sub-tab pattern to all three.

### F5 · The linear "STEP 1 → 2 → 3" framing is buried
The solver chaining (Profit→Procurement→Production→Logistics) is genuinely the product's spine,
but it only appears as descriptive text inside the Optimize tab and a diagram on Command
(14672). → Promote a persistent **pipeline ribbon** (Demand ✓ → Aggregate ✓ → Profit ▷ →
Procure → Produce → Ship) that doubles as nav and readiness indicator.

---

## Part 2 — Page-by-Page Audit

> Each section is grounded to a source line. "Asks/Shows" = what the user does there.
> Verdict tags: ✅ keep · ✂️ merge/move · 🔁 reframe · ➕ add.

### 01 · Setup — Company & Calendar  (`SetupTab` @3080)
| Section | L | Asks / Shows | Verdict |
|---|---|---|---|
| 🏢 Company Profile | 3091 | Identity, currency, GST flag, plant state, tax rate, service level | ✅ true setup |
| 📅 Planning Calendar | 3110 | Horizon×unit, grain, workdays, holidays | ✅ true setup |
| 🏷️ MSME Classification | 3211 | Investment/turnover → MSME tier | ✅ but auto-derive from finance figures, don't ask twice |
| 📍 Locations Master | 3302 | Every physical node (plant/WH/DC/cust/supplier) | ✂️ this is *network* master → Logistics |
| 📦 Per-Location On-Hand | 3344 | Starting inventory per site | ✂️ inventory seed → Products or Production |
| 🚚 Transport Modes & Contracts | 3378 | Mode rates, contract types | ✂️ → Logistics |
| 💰 Master Budget Envelope | 3447 | Split capital across 5 heads | ✂️ → Finance (show summary here) |
| 🎯 CAC Summary | 3497 | Cost-to-acquire anchor | ✂️ → Finance/cac (it literally says so) |
| 📋 Order Book | 3527 | Read-only all-MTO view | ✂️ → Demand/S&OP |
| 🎯 Industry Preset | 3544 | One-shot defaults | 🔁 move to a first-run wizard, not a permanent card |
| 📊 Historical Time Series | 3615 | Demand history entry | ✂️ → Demand (this is the demand input!) |
| 💹 WACC Calculator | 3809 | Compute discount rate | ✂️ → Finance/capital (single source) |
| 📊 Working Capital — Period View | 4209 | WC per period vs limit | ✂️ → Finance |
| 📈 Budget — Plan vs Actual | 4325 | Actual vs plan variance | ✂️ → Finance |
| 📒 Payment Ledger | 4405 | PO payments, DPO | ✂️ → Finance |
| 🤖 Server-Side ML/DL Forecast | 4520 | Run forecast models | ✂️ → Demand (lives next to the competition card) |

🧭 **Critic:** only ~4 of 16 cards are actually "setup." This tab is where features landed when
no better home existed. 🎨 **UI:** a setup screen should be a short guided form, not an
infinite scroll ending in a neural net. 📦 **Domain:** master data (nodes, modes, on-hand) and
treasury (WACC, WC, ledger) are different planning horizons and different owners (planner vs.
finance) — separating them matches who actually edits them.
**Redesign move:** Setup keeps only **Company Profile + Planning Calendar + MSME + Industry
Preset (as wizard)**. Everything else routes to its domain tab (annotated above).

### 02 · Products & BOM  (`ProductsTab` @4581)
| Section | L | Asks / Shows | Verdict |
|---|---|---|---|
| 🔧 Bill of Materials | 4754 | Parts, qty/u, cost, LT, MOQ, ordering S, holding%, shelf-life, supplier | ✅ core; very wide — split "buy terms" from "physical BOM" |
| 💵 Fixed & Setup Costs | 5275 | Setup cost, labor/unit (double-count warning) | ✅ keep; surface the double-count guard inline |
| 📋 Make-to-Order (MTO) | 5333 | Per-SKU orders | ✅ keep; this is the *edit* home for Order Book |
| ⚙️ Product Parameters | 5363 | Capacity, MAPE, yield, OEE, price, shelf-life, demand mode | 🔁 OEE/capacity duplicate Production tab — derive, don't re-ask |
| 🏭 Cycle Time & Line Assignment | 5493 | Per-SKU cycle time + line | ✂️ this is *production* data → Production tab (the known three-source cycle-time tangle) |
| 📅 Cost Events — Rolling Horizon | 5567 | Period-indexed cost step-changes | ✅ powerful, keep; make discoverable (it's buried) |
| 📁 Data Import/Export | 5581 | Save/load JSON | 🔁 global utility → move to app header, not a product card |

🧭 **Critic:** Product Parameters and Cycle-Time overlap Production (OEE, capacity, cycle appear
both here and in Production Architecture) — the "three-source cycle-time resolver" problem.
🎨 **UI:** the BOM row is ~12 fields wide; split into "physical" (qty/u, scrap) vs "commercial"
(cost, S, MOQ, terms, supplier) with progressive disclosure. 📦 **Domain:** capacity & OEE are
*line/stage* properties, not SKU properties — asking them per-SKU here invites contradiction with
the factory model. Keep the SKU as the demand/cost object; let throughput come from Production.

### 03 · Demand Planning  (`DemandTab` @5609)
| Section | L | Asks / Shows | Verdict |
|---|---|---|---|
| ⚖ Demand-Ceiling vs MTO-Floor | 5764 | Per-SKU bound semantics | ✅ keep; central to the LP |
| 🏷️ ABC/XYZ Segmentation | 5791 | Value × variability classes | ✅ keep |
| 🔄 Lifecycle Curve | 5840 | NPI/growth/decline shaping | ✅ keep |
| 🎯 Promotions & Events | 5906 | Demand uplifts | ✅ keep |
| 📈 Forecast Comparison | 5929 | Methods side-by-side | ✂️ merge with Model Competition (one card) |
| 🏆 Forecast Model Competition | 5951 | Leaderboard, MASE/bias/TS, intermittent (Croston/SBA/TSB) | ✅ keep as the forecast home; pull ML card (4520) here |
| 🎯 Consensus Workflow | 6034 | Reconcile stat/sales/exec | ✅ keep |
| ✏️ Demand Override | 6078 | Manual adjust | ✅ keep; show audit trail of override vs statistical |

🧭 **Critic:** strong, coherent tab — *but the actual demand inputs (history @3615, ML forecast
@4520) live on Setup.* Bring them home so the whole demand story is in one place. 🎨 **UI:**
Forecast Comparison + Competition are two cards doing one job — unify. 📦 **Domain:** this is the
best-modeled page; the Syntetos-Boylan intermittent path + consensus + override is textbook. Add
**forecastability / addressable-error** callout so users know when *not* to trust a model.

### 3B · Aggregate Plan / S&OP  (`AggregateTab` @6114)
Sections: level-vs-chase strategy classification, seasonal prebuild detector, workforce
(hire/fire/OT) plan, capacity shadow prices, SKU disaggregation.
🧭 **Critic:** the genuinely-missing "middle" tier — keep prominent. 🎨 **UI:** it sits as tab
"3B" between Demand and Production, which is right; make the **level↔chase** result the hero
visual (it's the whole point). 📦 **Domain:** correct Hax–Meal formulation. ➕ Surface the
**shadow price → capital tab** handoff visibly (it already feeds Endogenous-Capacity @11082);
right now that linkage is invisible to users.

### 04 · Production Architecture  (`ProductionArchitectureTab` @8425)
| Section | L | Asks / Shows | Verdict |
|---|---|---|---|
| 🏭 Production Architecture | 8589 | Lines→stages→machines/cycle/OEE; derived caps | ✅ core; this should *own* all cycle-time/OEE |
| 📅 Master Production Schedule | 8214 | MPS table | ✅ keep as the MPS home (de-dup from Analysis/Command) |
| 📦 Order Promising (ATP/CTP) | 8221 | Available/Capable-to-Promise | ✅ keep |

🧭 **Critic:** clean, but it's the *true* owner of capacity/OEE/cycle that Products also asks for
— make Products defer to here. 🎨 **UI:** lines→stages→machines is a tree; render it as one (the
flat card list hides the bottleneck logic). Add the net-hrs/week tooltip (already planned in the
Round-13 plan). 📦 **Domain:** bottleneck = min(stage throughput) is correct; expose the binding
stage per line as a badge. Sequence-dependent changeover (result @7432) belongs *here*, not on
Optimize.

### 05 · Suppliers & Procurement  (`SupplyTab` @9602)
| Section | L | Asks / Shows | Verdict |
|---|---|---|---|
| 📒 OTIF Ledger | 9427 | On-time-in-full history | ✅ keep |
| 📦 PO Release Plan | 9520 | Planned releases | ✅ keep |
| ⚠ Shortage Forecast | 9567 | Projected stockouts | ✅ keep |
| 📋 Supplier Master | 9890 | Vendor records | ✅ keep |
| 🛃 Landed Cost Rollup | 9919 | Duty/freight/IGST build-up | ✅ keep |
| 🧭 Inbound Network Topology | 9962 | Supplier→plant flows | ✂️ overlaps Logistics network — link, don't duplicate |
| 🛃 Incoterm Matrix / Quick Ref | 9839/9995 | Responsibility split | 🔁 collapse the two incoterm cards into one (matrix + hover ref) |
| 🛃 Import Tools | 10010 | HS/duty helpers | ✅ keep |

🧭 **Critic:** the **procurement solver results** (PO register, reorder policy, regime sourcing,
MRP explosion) currently render on *Optimize* — they belong here next to the supplier inputs (F1).
🎨 **UI:** two incoterm cards + a topology that repeats Logistics = three cards to merge/move.
📦 **Domain:** strong landed-cost + OTIF + regime-aware sourcing story; once results come home,
this becomes the single "sourcing cockpit."

### 06 · Logistics & Network  (`LogisticsTab` @10482)
| Section | L | Asks / Shows | Verdict |
|---|---|---|---|
| 📍 Center of Gravity (×2) | 10132, 10230 | DC siting | ✂️ collapse to one card (config + result) |
| ⚠ Procurement Risk & FX Hedging | 10344 | Risk/hedge | ✂️ overlaps Finance/fx (11924) — pick one home |
| 💰 Logistics Budget Gate | 10552 | Hard/soft budget | ✅ keep |
| 🏭 Network Node Master | 10612 | Nodes | ✂️ same store as Setup Locations (3302) — unify |
| 🛣️ Multi-Hop Lane Network | 10727 | Lanes | ✅ keep |
| 📋 Transport Contract Ledger | 10795 | Contracts | ✅ keep (pull modes from Setup 3378 here) |
| 🚛 3PL Provider Master | 10865 | 3PL records | ✅ keep |
| 📅 MTO Delivery Schedule (×2) | 10939, 10943 | Delivery dates | ✂️ collapse guard+real into one |

🧭 **Critic:** network nodes are mastered in **two** places (Setup 3302 + here 10612) over the
same `state.network.nodes` — pick this tab as the owner. 🎨 **UI:** two COG cards and two MTO
cards are guard/real or input/output pairs — present as one each. 📦 **Domain:** the transport
**consolidation** (LTL→FTL, result on Optimize 7744) and **allocation matrix** (on Command 15155)
both belong here — Logistics should own mode choice *and* consolidation *and* allocation.

### 07 · Finance & Costs  (`FinanceTab` @11389, sub-tabbed) ✅ the model to copy
Sub-tabs: **cashflow** (cost structure 11577, WC/CCC 11595, projected cashflow 11893) ·
**capital** (master budget 11961, WACC 12118, NPV/IRR 12136, depreciation 12180) ·
**cac** (CAC economics 11543) · **assets** (asset register 11620, depreciation) ·
**bvl** (buy-vs-lease 11832) · **fx** (currency hedging 11924) · **npv** (NPV/IRR, plan NPV).
🧭 **Critic:** already audience-grouped — but it *also* re-hosts WACC/NPV that appear elsewhere;
make Finance the canonical owner and have other tabs read-only. 🎨 **UI:** good template — the
sub-tab navigator is what Setup/Analysis/Command need. 📦 **Domain:** sound; the only smell is
WACC/depreciation also living in Analysis (12118/12180 are *in Finance* — fine; the Analysis
duplicates at 12118? no — those ARE Finance). Verify no third WACC editor survives the cleanup.

### 7B · Investment Decision  (`InvestmentDecisionTab` @11007)
Sections: Endogenous-Capacity Capital Plan (11082, consumes aggregate shadow prices), Cash-Flow
Builder (11138), Equity Sources & Opp-Cost (11211), Investment Verdict (11261), Per-Line CapEx
Proposals (11305).
🧭 **Critic:** heavily overlaps Finance/capital + Finance/npv (NPV, WACC, cash flows). Two tabs
(7B and 07) both do capital decisions. → Either **merge 7B into Finance as a "capital
decisions" sub-tab**, or make 7B the *decision* layer (NPV verdict, ranking) and Finance the
*inputs* layer — and say so. 📦 **Domain:** the endogenous-capacity link (throughput × shadow
price → capacity CF) is the standout feature; keep it, surface its provenance.

### 08 · Optimize & Solve  (`OptimizeTab` @6339) — the god-tab
Run modes (TABS desc @6807–6815): profitmix, procurement, production, pipeline, sop, transport,
capital, montecarlo, rolling. Result cards 7148–7975 (see F1 list).
🧭 **Critic:** mixes *run control* with *every result render in the app*. 🎨 **UI:** a single tab
should not be 2,000 lines / 9 modes / 25 result cards. 📦 **Domain:** the **pipeline** itself is
the valuable concept; keep a thin **Solver Console** (choose mode → constraints toggles → solve →
status/objective/shadow-prices/gap/runtime) and **deep-link each result to its domain tab** (F1).
➕ The constraint-toggle list (CVaR, regime-aware, demand-ceiling) is good — expose *which
constraints bound* after each solve, here, as the console's payoff.

### 09 · Risk & Scenarios  (`AnalysisTab` @12311) — second mega-scroll
~22 cards: Control Tower (12453), Analysis Engine (12507), Monte Carlo (12530), Sensitivity
(12556), Auto-Researcher (12600), TCO (12617), EVM (12660), Cost Waterfall (12709), Multi-SKU
(12745), WC cash-tied (12767), FVA (12802), Lost Sales (12834), S&OP Gap (12859), What-If Bot
(12906), What-If Sensitivity (12958), Report Export (12998), Scenarios (13468), MPS (13689),
Inventory Projection (14067), Live Insight (14429), Multi-SKU 15-section (14471).
🧭 **Critic:** "Risk & Scenarios" has become a catch-all analytics drawer — MPS and inventory
projection aren't risk; TCO/EVM/FVA are finance/PM; Monte Carlo duplicates Optimize. 🎨 **UI:**
needs sub-tabs badly: **Risk** (control tower, MC, sensitivity, scenarios, lost sales) ·
**Cost** (TCO, waterfall, WC, FVA) · **Performance** (EVM, S&OP gap, KPI) · **Explore**
(what-if bot/sensitivity, auto-researcher, multi-SKU). 📦 **Domain:** Control Tower's
frozen/slushy horizon logic is excellent — make it the landing hero. Move MPS/inventory
projection to Production; move TCO/EVM/FVA to Finance or a "Cost" sub-tab.

### 10 · Command Center  (`CommandCenterTab` @14648)
Cards: Solver-comm diagram (14672), Solver Input Readiness (14706), Parameter Cascade (15082),
Transport Allocation Matrix (15155), MRP Bucket Grid (15558), Stakeholder Power×Interest (15709),
KPI Dashboard (15910), Disruption Registry (16083), Event Log (16151), Version History (16180),
Risk Matrix (16219).
🧭 **Critic:** half of this *is* the right idea for a home/landing page (readiness, cascade, KPI,
solver-comm) — the other half duplicates other tabs (transport matrix → Logistics; MRP grid →
SAP/Production; risk matrix → Analysis; disruption registry → Scenarios). 🎨 **UI:** promote the
**readiness + pipeline + KPI dashboard** to be the app's *home* (tab 00), strip the duplicates.
📦 **Domain:** the Parameter Cascade dependency graph (15082) is genuinely the best "single source
of truth" artifact in the app — feature it.

### 11 · Learning Lab  (`LearningLab`)
Concept explainers. ✅ Keep as optional help; consider folding into contextual `SectionInfo`
popovers rather than a whole tab (the `ⓘ` tooltips already carry most of this content).

### 12 · SAP Mode  (`SAPModeTab` @15306)
Multi-plant scenario what-if (15320), Overview/Network/Master-Data/Planning-Runs/T-codes
(15358–15447), MRP Bucket Grid (15640), KPI (15910 shared?).
🧭 **Critic:** a parallel app — multi-plant + scenarios + MRP that overlap Analysis scenarios and
Command MRP. 🎨 **UI:** if the goal is "show this maps to SAP T-codes," that's a *reference
overlay*, not a separate operational mode. 📦 **Domain:** the multi-echelon/multi-plant ambition
is real but currently disconnected from the single-plant solvers. Either commit to multi-plant
(and thread it through the solvers) or demote SAP Mode to a T-code cheat-sheet + mapping reference.

---

## Part 3 — Proposed Information Architecture (the redesign target)

Collapse 14 flat tabs → **8 workflow stages + a home**, each internally sub-tabbed (Finance is the
proof this works). Nothing is deleted — sections relocate to their natural owner.

```
00 HOME            Pipeline ribbon · Solver-input readiness · KPI dashboard · Parameter cascade
                   · Control tower alerts            (from Command + Analysis control tower)

01 SETUP           Company · Calendar · MSME · (Industry preset → first-run wizard)
                   ← strip the other 12 cards out of today's Setup

02 PRODUCTS        BOM (physical | commercial split) · Setup/labor costs · SKU params (cost/demand
                   only) · MTO orders · Cost events
                   ← cycle-time/OEE/capacity move OUT to Production

03 DEMAND          History · ML forecast · Model competition · ABC/XYZ · Lifecycle · Promotions
                   · Consensus · Override · Ceiling-vs-floor      ← history + ML pulled from Setup

04 PLAN (S&OP)     Aggregate level-vs-chase · Prebuild · Workforce · Capacity shadow prices
                   · Profit-mix result · Order book
                   (the missing middle, now also hosting the profit result)

05 PRODUCTION      Lines→stages→machines/OEE/cycle (sole owner) · MPS · ATP/CTP
                   · Sequence-dependent changeover · Production schedule result · Shutdown candidates

06 SOURCING        Supplier master · BOM buy-terms · Landed cost · Incoterms (one card) · OTIF
                   · PO register + reorder policy + regime sourcing + MRP explosion (results home)
                   · Import tools

07 LOGISTICS       Network nodes (sole owner) · Lanes · 3PL · Contracts+modes · Center of Gravity
                   · Transport mode/consolidation/allocation results · FX/risk

08 FINANCE         cashflow · capital (WACC/NPV/budget — sole owner) · capital-decisions (was 7B:
                   endogenous capacity, verdict, per-line CapEx) · assets · bvl · cac · fx

— REFERENCE        Learning Lab (or inline ⓘ) · SAP T-code mapping (demoted)
— CONSOLE          Solver run console (was Optimize): mode · constraints · solve · shadow prices,
                   deep-linking results into stages 04–08
— SCENARIOS        One unified scenario/disruption store (merges Analysis scenarios + Command
                   disruption registry + SAP scenarios), feeding Risk views
```

**Owner map (who edits what — resolves the duplications in F2):**
`network.nodes` → Logistics · WACC/NPV/budget → Finance/capital · MPS → Production ·
Monte Carlo → Scenarios/Risk · cycle-time/OEE → Production · transport allocation/consolidation
→ Logistics · scenarios → unified Scenarios store.

---

## Part 4 — Section Inventory (CANONICAL — do not invent beyond this list)

Every card, its source line, and its home page. `~` = guard-clause placeholder for the card above
(not a separate section). Use this as the anti-hallucination reference.

**Setup:** Company Profile (3091) · Planning Calendar (3110) · MSME Classification (3211) ·
Locations Master (3302) · Per-Location On-Hand (3344) · Transport Modes & Contracts (3378) ·
Master Budget Envelope (3447) · CAC Summary (3497) · Order Book (3527) · Industry Preset (3544) ·
Historical Time Series (3615) · WACC Calculator (3809) · Working Capital Period View (4209) ·
Budget Plan-vs-Actual (4325) · Payment Ledger (4405) · ML/DL Forecast (4520).

**Products:** Bill of Materials (4754) · Fixed & Setup Costs (5275) · Make-to-Order (5333) ·
Product Parameters (5363) · Cycle Time & Line Assignment (5493) · Cost Events (5567) ·
Data Import/Export (5581).

**Demand:** Demand-Ceiling vs MTO-Floor (5764) · ABC/XYZ Segmentation (5791) · Lifecycle Curve
(5840) · Promotions & Events (5906) · Forecast Comparison (5929) · Forecast Model Competition
(5951) · Consensus Workflow (6034) · Demand Override (6078).

**Aggregate/S&OP:** AggregateTab body @6114 (level-vs-chase, prebuild, workforce, shadow prices,
disaggregation).

**Optimize (console + results):** Optimization Engine (6864) · Procurement MILP Results (7148) ·
Production Schedule per-product (7162) · Multi-Echelon Inventory (7201) · PO Register (7290) ·
RM Timeline (7327) · Reorder Policy (s,S)/(R,Q) (7344) · Regime-Aware Sourcing (7369) · MRP
Explosion (7384) · Production Schedule Results (7417) · Sequence-Dependent Changeover (7432) ·
Production Order Register (7448) · Product Fulfillment (7485) · Shutdown Candidates (7509) ·
Line-Level Execution (7541) · Line×Period Matrix (7561) · Gantt (7584) · Profit Maximizer (7601) ·
Capacity Conflict Check (7708) · Transport Results (7744) · Monte Carlo (7785) · Capital Budget
(7812) · Closed-loop S&OP (7834) · Pipeline steps (7861) · Rolling MPS Nervousness (7897) ·
Wave Comparison (7911) · Final-Wave PO Register (7931) · MILP Export (7975).

**Production Architecture:** MPS (8214) · Order Promising ATP/CTP (8221) · Production Architecture
(8589).

**Supply:** OTIF Ledger (9427) · PO Release Plan (9520) · Shortage Forecast (9567) · Incoterm
Matrix (9839) · Supplier Master (9890) · Landed Cost Rollup (9919) · Inbound Network Topology
(9962) · Incoterms Quick Ref (9995) · Import Tools (10010).

**Logistics:** Center of Gravity (10132 + 10230 ~) · Procurement Risk & FX Hedging (10344) ·
Logistics Budget Gate (10552) · Network Node Master (10612) · Multi-Hop Lane Network (10727) ·
Transport Contract Ledger (10795) · 3PL Provider Master (10865) · MTO Delivery Schedule (10939 +
10943 ~).

**Investment Decision:** Investment Decision (11074) · Endogenous-Capacity Capital Plan (11082) ·
Cash Flow Builder (11138) · Equity Sources & Opp-Cost (11211) · Investment Verdict (11261) ·
Per-Line CapEx Proposals (11305 + 11346 ~).

**Finance (sub-tabbed):** WACC explainer (11497) · CAC Economics (11543) · Cost Structure (11577) ·
Working Capital/CCC (11595) · Asset Register (11620) · Buy-vs-Lease (11832) · Projected Cash Flow
(11893) · Currency Hedging (11924) · Master Budget & Capital Structure (11961) · WACC Calculator
(12118) · NPV/IRR (12136) · Depreciation (12180) · Plan NPV (12276).

**Analysis:** Control Tower (12453) · Analysis Engine (12507) · Monte Carlo (12530) · Sensitivity
(12556) · Auto-Researcher (12600) · TCO per SKU (12617) · EVM (12660) · Cost Waterfall (12709) ·
Multi-SKU Comparison (12745) · WC Cash-Tied (12767) · FVA (12802) · Lost Sales (12834) · S&OP Gap
(12859) · What-If Bot (12906) · What-If Sensitivity (12958) · Report Export (12998) · Scenarios
(13468) · MPS (13689) · Inventory Projection (14067) · Live Insight Engine (14429) · Multi-SKU
15-Section (14471 + 14481 ~).

**Command Center:** Solver Communication (14672) · Solver Input Readiness (14706) · Parameter
Cascade (15082) · Transport Allocation Matrix (15155 + 15160 ~) · MRP Bucket Grid (15558 + 15640
~) · Stakeholder Power×Interest (15709) · KPI Dashboard (15910) · Disruption Registry (16083) ·
Event Log (16151) · Version History (16180) · Risk Matrix (16219).

**SAP Mode:** SAP Mode header (15320) · Overview (15358) · Physical Network (15375) · Master Data
(15401) · Planning Runs (15409) · T-Code Cheatsheet (15415) · ML Demand Sensing (15439) ·
Stochastic/CVaR Solver (15447).

---

## Part 5 — Priority order (if doing this incrementally)
1. **F3/Part 3 Setup split** — biggest first-impression win, lowest risk (pure moves).
2. **F1 — route solver results to domain tabs**, leave Optimize as a console.
3. **F4 — sub-tab Analysis & Command** (copy Finance pattern); promote Home (tab 00).
4. **F2 — de-duplicate WACC / WC / MPS / MC / network nodes / scenarios** (pick one owner each).
5. **7B → Finance** merge; **SAP Mode → reference**; **unify scenarios store**.

*Every move above is relocation/relabel, not a logic change — solver bindings and state keys are
preserved. The redesign tool should restyle and reorganize against Part 4; it must not add
sections that aren't in Part 4.*
