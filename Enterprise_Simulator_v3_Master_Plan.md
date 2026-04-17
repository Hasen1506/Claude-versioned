# Enterprise Simulator v3.0 — Master Plan
**A complete rearchitecture.** Scraps the tab-oriented structure of v2.0 in favor of a product-centric flow that mirrors how a supply chain engineer actually thinks. Eliminates every duplicate input, wires every control to downstream state, and makes every formula explicit and editable.

> Author's note to the user: this document is the contract. Every one of your 25 critique points is addressed below with a specific resolution. Sections tagged **[BROKEN → FIX]** identify the v2.0 defect and the v3.0 repair. Sections tagged **[NEW]** are features v2.0 lacked entirely.

---

## 0. Diagnosis — Why v2.0 Failed

| v2.0 Defect | Root Cause | v3.0 Resolution |
|---|---|---|
| Duplicate inputs (variable cost, carry rate, production mode) | Bolt-on UI with no single source of truth | **Single source of truth registry**: every field has one owner tab; downstream tabs read-only |
| Dead toggles (industry preset, line type, ref mode, cost events) | UI added without backend wiring | **Audit checkbox**: every UI control must trace to a `dispatch` + a solver payload field + a formula consuming it |
| Orphan globals (production lines defined before any product exists) | Tab-first thinking, not workflow-first | **Product-centric routing**: lines & operations are declared *inside* the product, then aggregated into global capacity pool |
| MPS/MRP results mismatched with forecast (different numbers) | Tabs recompute in isolation; no pipeline hash | **Deterministic pipeline**: one `/api/solve/pipeline` endpoint produces demand → MPS → MRP → PO in a single transaction with shared input hash |
| No day-level granularity | Arrays sized to 12 months only | **Adaptive time grid**: all data stored at day-grain; aggregated to W/M on display based on user-selected view |
| Forecast chart stuck "loading" | Recharts bundle not guaranteed; no fallback | **Canvas-based charts** with SSR-friendly data + "no chart library" plain-SVG fallback |
| No Excel import with messy data | CSV-only, strict schema | **Paste/upload → column mapper → preview → accept**: works on any Excel tab |
| Capacity modeled as `units/day × days` | Ignores availability, performance, quality | **OEE model**: `Capacity = Machines × Shifts × Hrs/shift × WorkDays × Availability × Performance × Quality` |
| One-step production | BOM flat; ignores routing, sub-assemblies, QC | **Multi-operation routing**: each op consumes specific BOM parts, has cycle time, station, setup, labor, yield, parallelism |

---

## 1. User Mental Model — The Flow v3.0 Enforces

A supply chain engineer's work is **top-down from a product**:

1. "I'm planning *this product*."
2. "Here's *its* BOM (raw materials with sources)."
3. "Here's *its* routing (how I make it — stations, operations, cycle times)."
4. "Here's *its* demand (history + forecast + orders + promotions)."
5. "Here's *its* inventory policy (safety stock, reorder point, lot sizing rule)."
6. "Solve it: what do I produce each day, what do I buy, when, how much, at what cost?"
7. "Stress test: Monte Carlo, sensitivity, what-if."

Global concerns (company, calendar, currencies, WACC, service-level target) are **setup**. Everything else **lives inside the product**.

v2.0 fought this by forcing you to define production lines *globally before any product existed*. v3.0 flips it: you define lines **as stations inside a product's routing**, and the app aggregates them into a plant-wide capacity pool automatically.

---

## 2. Tab Architecture (v3.0)

```
┌─ TAB 1: COMPANY & CALENDAR ────────────────────────────┐
│  Company profile · Fiscal calendar · Work calendar     │
│  Currencies & FX · Tax & compliance defaults           │
│  Planning horizon & time grid                          │
│  WACC & service-level defaults (global, overridable)   │
└────────────────────────────────────────────────────────┘

┌─ TAB 2: PRODUCTS (the heart) ──────────────────────────┐
│  Per-product accordion. Sub-sections:                  │
│    2A. Identity (SKU, category, UoM, pack, shelf life) │
│    2B. Commercial (price, variable cost breakdown ONCE)│
│    2C. Demand (history → forecast → overrides → events)│
│    2D. BOM (materials with sources, inline)            │
│    2E. Routing (operations/stations, cycle times)      │
│    2F. Inventory policy (SS, ROP, lot sizing rule)     │
│    2G. Quality & risk (yield, rework, scrap, CTQ)      │
└────────────────────────────────────────────────────────┘

┌─ TAB 3: SUPPLIERS & NETWORK ───────────────────────────┐
│  Supplier master (registration, scorecard, audits)     │
│  Contracts (rate, blanket, tiered — the missing piece) │
│  Import/export (Incoterms, HS, landed cost)            │
│  Hedging (forward contracts)                           │
│  Lanes: supplier → plant → DC → customer (freight tbl) │
│  Multi-echelon toggle (plant only / plant+DC / full)   │
└────────────────────────────────────────────────────────┘

┌─ TAB 4: PLANT & CAPACITY ──────────────────────────────┐
│  Auto-built from all products' routings                │
│  Station registry (read-only; edit via Product.2E)     │
│  OEE: Availability · Performance · Quality             │
│  Shift calendar · Overtime rules · Labor pool          │
│  Maintenance windows                                    │
└────────────────────────────────────────────────────────┘

┌─ TAB 5: FINANCE ───────────────────────────────────────┐
│  Cost rollup (read-only from other tabs; shows sources)│
│  Working capital (CCC) · Cash timeline                 │
│  Asset register · Depreciation (SLM/WDV/UoP)           │
│  NPV/IRR · Buy vs Lease · Make vs Buy                  │
│  Budgets & variance (EVM for project-mode)             │
└────────────────────────────────────────────────────────┘

┌─ TAB 6: OPTIMIZE & SOLVE ──────────────────────────────┐
│  Single "Solve Pipeline" button (end-to-end)           │
│  OR individual solver runs with locked upstream inputs │
│  Deterministic / Rolling-Horizon / Stochastic modes    │
│  Live-rendered MILP formulation with YOUR values       │
│  Every input editable inline (changes flow back)       │
│  Solver results: MPS, MRP, POs, Gantt — D/W/M views    │
└────────────────────────────────────────────────────────┘

┌─ TAB 7: RISK & SCENARIOS ──────────────────────────────┐
│  Monte Carlo · Sensitivity · Auto-researcher           │
│  What-if bot · Disruption simulator (supplier down)    │
│  Scenario save/compare (full snapshots)                │
│  Control tower (live alerts on current plan)           │
└────────────────────────────────────────────────────────┘

┌─ TAB 8: LEARNING LAB ──────────────────────────────────┐
│  All v78 sections preserved + new import/export,       │
│  MILP formulation, OEE, multi-echelon, routing         │
└────────────────────────────────────────────────────────┘

┌─ TAB 9: SAP MODE [NEW] ────────────────────────────────┐
│  Multi-echelon (plant → DC → retail)                   │
│  Multi-plant coordination                              │
│  ML-based demand sensing (XGBoost on POS)              │
│  10k+ SKU scale (CSV-driven, batch MILP)               │
│  ERP-like T-code simulator (ME21N, MIGO, MD04…)        │─────────────────────────────────────────────────────┘
```

---

## 3. Resolution Map — Your 25 Critiques, Point by Point

### (1) "GST registered Yes/No — what does 'No' even do?"
**v3.0 fix:** In Tab 1 → Tax & Compliance:
- `Yes` → IGST on imports is recoverable as ITC; net landed cost excludes IGST. `GSTIN` field becomes required. E-invoice threshold triggers warnings.
- `No` → IGST becomes a sunk cost (added to landed cost and inventory value). Help panel explains: *"Without GST registration, you can't claim Input Tax Credit. Your effective cost of imported goods rises by ~18%. Register if turnover >₹40 lakh (goods) or ₹20 lakh (services)."*
- Field gets an info icon with a link to Tab 8 → Learning Lab → GST & ITC walkthrough.

### (2) "Service level has only 4 options"
**v3.0 fix:** Free-text numeric input, 50–99.99%. On entry, app computes and displays:
- `z` value (inverse normal) — e.g., 92.5% → z=1.44
- expected safety stock change from current
- expected cost impact (from Monte Carlo)
Every product can override global default; panel shows Kraljic quadrant-driven recommendation (Strategic → 98%; Non-critical → 85%).

### (3) "Corporate tax rate section is confusing"
**v3.0 fix:** Renamed to **"Effective Tax Rate (for NPV & depreciation tax shield)"** with inline tooltip: *"Used only for after-tax cash flow calculations and WACC. If unsure, use 25% (Indian corporate rate FY25). This does NOT affect GST."* Default autoset based on turnover (MSME benefit auto-applied).

### (4) "Planning horizon / workdays don't affect anything"
**v3.0 fix:** Both flow through the single `/api/solve/pipeline` payload:
- `periods` = `ceil(horizon_months × working_days_per_month)` at day-grain.
- Capacity = `Machines × Shifts × Hrs × WorkingDays × OEE` — workdays now appear in every capacity line item.
- MRP net-requirements horizon bounded by `periods`.
- Calendar respects Indian holiday list (editable) + Sundays (if 6-day) or weekends (if 5-day).

### (5) "What do Plan Months and Periods mean?"
**v3.0 fix:** Single field: **"Planning horizon"** with dropdown for unit (weeks/months/quarters) and numeric length. Internal conversion to days happens silently. No more two fields saying similar things. Info icon: *"13 weeks = one quarter is typical for operational plans; 12 months for S&OP; 36 months for capex."*

### (6) "Supply Chain Network Topology — presets do nothing, name-reference does nothing, why is it duplicating product info?"
**v3.0 fix:** The whole "network topology" subsection is deleted from Tab 1. Its function splits:
- **Industry preset** becomes a *project kickstart wizard* on first app load only, and seeds realistic defaults (BOM templates, OEE benchmarks, typical MOQs, duty rates) across all tabs. Selecting "Automotive" pre-populates: IATF 16949 quality flags, 6-day work week, 85% OEE target, 3-week safety stock, JIT inclination. Demonstrable preset-application diff shown.
- **Reference by name** is deleted (was cosmetic). Part numbers are primary; names are secondary labels.
- **Cost/unit** input is consolidated into Tab 2B (Commercial). No input duplicated.

### (7) "Production Lines shouldn't exist as a global section when no product is defined"
**v3.0 fix:** Deleted from Tab 1. Moved to **Tab 2E (Routing)** per product: you declare operations/stations *inside* each product. Tab 4 (Plant & Capacity) then **auto-aggregates** all stations across products into a read-only capacity pool. Shared stations (used by >1 product) are flagged for contention analysis. You never define a line without product context.

### (8) "Line Type toggle does nothing; should ask how many parallel units"
**v3.0 fix:** Each station has explicit fields:
- `parallelism` = integer (how many identical units run concurrently)
- `mode` = {Shared / Dedicated / Flexible-sequential / Flexible-parallel} — each has distinct solver logic in `production.py` v2:
  - **Shared**: capacity pool contested; sequencing matters (MILP with sequence-dependent setups)
  - **Dedicated**: one product per station; no contention
  - **Flexible-sequential**: one product at a time, any product
  - **Flexible-parallel**: multiple products simultaneously up to parallelism
- All 4 modes have production-side MILP variables + constraints documented in the live formula view (Tab 6).

### (9) Skipped in your numbering.

### (10) "Variable cost defined twice — once as single field, once as breakdown"
**v3.0 fix:** Single source of truth in Tab 2B:
- `variableCostPerUnit` is the **computed total** (read-only, displayed).
- Components (electricity, packaging, consumables, direct labor, other) are **the only editable inputs** and sum to the total.
- Same pattern for `carryRate`: components (capital opportunity, storage, insurance, obsolescence, handling, shrinkage) are editable; total is computed.
- Tab 5 (Finance) reads totals only — no separate inputs there.

### (11) "Target utilization — should we use OEE instead?"
**v3.0 fix:** `targetUtilization` is deleted as an independent input. **Capacity formula:**

```
Effective Capacity (units/day) =
    Machines × Shifts/day × Hours/shift × (Good Parts per Hour)
  × OEE_factor

OEE = Availability × Performance × Quality
  Availability = (Planned Production Time − Downtime) / Planned Production Time
  Performance = (Ideal Cycle Time × Total Count) / Run Time
  Quality     = Good Count / Total Count
```

User inputs:
- Planned downtime % (maintenance, breaks, setup) → drives Availability
- Speed loss % (micro-stops, slow running) → drives Performance
- First-pass yield % → drives Quality

World-class: >85% OEE. Typical Indian mfg: 55–70%. App shows benchmark bar with your position.

### (12) "Historical demand — Excel upload with daily data"
**v3.0 fix:** Redesigned data entry:
1. **Paste from Excel** — detect delimiters, headers.
2. **Column mapper** — drag detected columns onto semantic fields (date / SKU / qty / customer / channel / promo-flag).
3. **Granularity detector** — identifies Day/Week/Month data; app asks "keep daily" or "aggregate to weekly."
4. **Data cleaner** — flags negatives, blanks, duplicates, returns (negative signed quantities), outliers (>3σ). User accepts/rejects each.
5. **Transaction store** — raw rows persisted; app aggregates on demand to any granularity.
6. **Seed datasets** — ships with 3 realistic sample datasets (automotive weekly 52 weeks; FMCG daily 365 days; heavy-eng order-based project shipments).

### (13) "Forecast comparison says charts loading, refresh if stuck"
**v3.0 fix:** Charts reimplemented with Recharts **or** a plain SVG fallback (150 LoC, no dependency). App picks dynamically. Loading state times out at 3s and auto-switches to fallback. No "refresh if stuck" message.

### (14) "Demand planning overrides placed far from demand"
**v3.0 fix:** Overrides move directly below the forecast chart — both inside Tab 2C. Override flow: click a point on the forecast chart → inline editor → value saved → FVA (Forecast Value Add) recomputed and displayed on-screen. FVA = MAPE(base) − MAPE(base+override). If FVA < 0 the override *hurt* accuracy; UI flags it amber.

### (15) "BOM feels far from product; is procurement policy inside?"
**v3.0 fix:** Tab 2D (BOM) sits right after Tab 2B (Commercial) and 2C (Demand). Each BOM row expands to reveal:
- Sources (primary + backup suppliers with allocation %)
- **Procurement policy** (EOQ / Fixed-lot / Min-max / JIT-Kanban / VMI / Consignment)
- Inventory policy (safety stock, reorder point, review period)
- MOQ, lead time, lead time CV
- Volume discount tiers (tier → qty → unit price)
- Shelf life & FEFO flag
- Yield at supplier (scrap factor)
- Transport tier (mode → cost table)
Every field named above now has a solver consumer — no orphan inputs.

### (16) "Demand sensing lacks M/W/D granularity; wrong position"
**v3.0 fix:** Demand sensing lives in Tab 6 (Optimize) right beside the MPS output, because it's the trigger for **replanning**. User inputs actual-vs-forecast for any time bucket (D/W/M auto-detected from history granularity). Statistical test (CUSUM or a 3-run sequential χ²) fires a replan trigger when `|deviation| > 2σ` for N buckets. Trigger can escalate to transport optimizer for mode upgrade (air vs sea) with cost-benefit side-by-side.

### (17) "Missing volume/transport discount tiers; repetitive product params"
**v3.0 fix:**
- **Volume discount tiers** added to every BOM row (supplier side) and to every customer demand row (sales side).
- **Transport discount tiers** added to each lane (per mode): e.g., sea 0–20 CBM ₹X/CBM, 20–40 CBM ₹Y/CBM, ≥40 CBM ₹Z/CBM. FTL/LCL threshold auto-computed.
- **Repetitive product params section** deleted. All product params live in Tab 2 subsections only.

### (18) "Production modes toggle does nothing"
**v3.0 fix:** `production_mode` in {MTS, MTO, ATO, ETO, Seasonal-build} is now a **per-product switch** at the top of Tab 2 and it drives:
- MTS: demand triggers MPS; solver produces to forecast + safety stock
- MTO: customer orders trigger MPS; no forecast consumption; ATP = backlog + committed capacity
- ATO: sub-assemblies MTS, final assembly MTO
- ETO: solver treats each order as a project with unique BOM + routing
- Seasonal-build: campaign-mode; capacity used to build inventory pre-season

Each mode gates which sub-sections of Tab 2 are visible/required, so the user can't input contradictory data.

### (19) "Outbound/distribution section redundant with transport"
**v3.0 fix:** Distribution deleted as a standalone section. Lanes (supplier→plant, plant→DC, DC→customer) live in Tab 3 with **multi-echelon toggle**:
- **Plant-only** (1 echelon): plant ships direct to customer.
- **Plant + DC** (2 echelons): intermediate DC; base-stock policy.
- **Full** (3 echelons): plant → regional DC → retail; multi-echelon inventory optimization (Clark-Scarf / METRIC).
Each lane carries its own freight tiers.

### (20) "Cost events / rolling horizon placed randomly"
**v3.0 fix:** Cost events move to Tab 6 under **Rolling Horizon Planning** because they're about *temporal changes to inputs across the plan*. They're now wired to:
- `procurement.py` (price changes at future dates)
- `production.py` (labor rate changes)
- `finance.py` (WACC shifts)
Each event has `fromDate`, `paramPath` (dotted path into the state tree), `newValue`, and `affects` (list of solvers). Rolling-horizon mode re-solves at each rollover period with updated realized data.

### (21) "Optimize should let me edit every input and show the solver formula"
**v3.0 fix:** Tab 6 has three panes:

**Left pane — Inputs (all editable inline, flow back to source tab on save):**
```
Products ▼
  SKU-1 ▼
    Demand plan        [12x editable cells, D/W/M toggle]
    Unit cost          ₹[edit]
    Selling price      ₹[edit]
    Yield %            [edit]
    Shelf life         [edit]
    Capacity/day       [edit, sourced from Tab 4]
  SKU-2 ▼ …

Parts ▼
  RM-01 ▼
    Unit cost          [edit]
    MOQ                [edit]
    Lead time (μ, σ)   [edit, edit]
    …

Constraints ▼
  Budget cap           [edit]
  Warehouse cap        [edit]
  Service level target [edit]
```

**Middle pane — Live MILP formulation rendered with your values:**
```
Minimize:  Σ_i Σ_t (c_it · x_it + h_i · I_it + s_i · B_it)
         + Σ_k Σ_t (setup_k · y_kt)

Where:
  c_it  = 85 ₹/unit  (your value: RM-01 × qty_per = 5 × ₹17)
  h_i   = 0.0166 ₹/unit/day  (your carry rate 20%/yr ÷ 365 × cost)
  setup_k = ₹2000   (your SKU-1 setup cost)

Subject to:
  Inventory balance:  I_{it} = I_{i,t-1} + x_{i,t-L_i} − d_{it}
  Capacity:           Σ_k α_{kl} · q_{kt} ≤ Cap_{lt}
  Service level:      P(I_it ≥ 0) ≥ 95%
  Budget:             Σ_i c_i · x_it ≤ B_t = ₹5,00,000
  Non-negativity:     x, I, B, q ≥ 0
  Integer:            y ∈ {0,1}
```
(Rendered with KaTeX; user sees their actual numbers in place.)

**Right pane — Outputs (MPS, MRP, PO schedule, Gantt):**
All views support D/W/M toggle. MPS shows **all horizon days** (scrollable), not truncated to 5. The forecast values displayed here are **guaranteed identical** to Tab 2C's via shared hash.

Solver modes:
- **Deterministic** (default) — point forecasts, no variance
- **Rolling-horizon** — solves week 1, locks, rolls forward, resolves
- **Stochastic (2-stage)** — recourse variables for demand uncertainty
- **Robust** (CVaR) — minimize worst-case expected cost

### (22) "Production is multi-stage, not one step. Parallelism matters."
**v3.0 fix:** Each product's routing (Tab 2E) is a DAG of operations:

```
Operation node:
  id: OP-01
  name: "Press subassembly A"
  station_id: STN-PRESS-1
  consumes: [RM-01 × 2, RM-02 × 1]    ← BOM parts attached HERE, not flat
  produces: SUBA
  cycle_time_sec: 45
  setup_time_min: 20
  parallelism: 2
  yield_pct: 98
  predecessors: []                     ← start-of-line op

Operation node:
  id: OP-02
  name: "Weld subassembly B"
  station_id: STN-WELD-1
  consumes: [RM-03 × 3, RM-04 × 1, SUBA × 1]
  produces: SUBB
  cycle_time_sec: 60
  predecessors: [OP-01]

… until OP-N produces the finished good.
```

Routing supports:
- Multi-level sub-assemblies
- Parallel branches (e.g., painting happens while QC runs)
- Rework loops (op → QC → op-rework fail path)
- Labor requirements per op (skilled/unskilled hours)
- Tool/fixture dependencies (block concurrent ops sharing a tool)

Solver (`production.py` v2) is a **job-shop scheduler MILP** with:
- `x_{j,s,t} = 1` if op j starts on station s at time t
- Precedence constraints across predecessors
- Resource capacity (station × time)
- Labor capacity
- Changeover matrix
- Minimum makespan / minimum WIP / max on-time objective

### (23) Skipped in your numbering.

### (24) "Choosing location modes + freight rates per mode for transport"
**v3.0 fix:** Tab 3 → Lanes sub-section per lane carries:
- Origin, destination (city/port/ICD)
- Available modes per lane (a checkbox list; e.g., Mumbai→Pune: road✔, rail✔, sea✘, air✘)
- Rate table per mode with tiered breaks (as in #17)
- Transit time (μ, σ) per mode
- Reliability (on-time %) per mode
- Sustainability (CO₂/kg) per mode — optional
- Capacity per mode (how much can ship in one period)

Transport optimizer LP decides allocation across modes per lane per period, respecting demand deadlines. It also receives the demand-sensing replan trigger from Tab 6 to choose air over sea under spike conditions.

### (25) "We need SAP Mode — multi-echelon, ML sensing, multi-plant, 10k SKU"
**v3.0 fix:** **Tab 9 — SAP Mode** (new). See §7 below.

---

## 4. Data Model — Single Source of Truth

```typescript
state = {
  // Tab 1 — global
  company: { name, fiscalYearStart, baseCurrency, gstRegistered, gstin, industry, orgSize },
  calendar: { horizon: { unit: 'weeks', length: 13 }, workDaysPerWeek, holidays: Date[] },
  fx: { [currency]: rate, hedges: Hedge[] },
  tax: { effectiveRate, gstRates: { [cat]: rate }, igstItcRecoverable: bool },
  global: { wacc, defaultServiceLevel, discountRate },

  // Tab 2 — products (heart of the app)
  products: [{
    id, sku, name, category, uom, packSize, shelfLifeDays,
    productionMode: 'MTS'|'MTO'|'ATO'|'ETO'|'Seasonal',
    commercial: {
      sellingPrice,
      variableCost: { electricity, packaging, consumables, directLabor, other },
      carryRate: { capital, storage, insurance, obsolescence, handling, shrinkage },
      // totals computed: variableCost_total = Σ components
    },
    demand: {
      history: Transaction[],          // day-grain, raw
      forecast: {
        models: { [modelName]: { values, errors, weight } },
        consensus: number[],
        overrides: { [date]: { value, reason, fva } },
        promotions: Promotion[],
        customerOrders: Order[],       // MTO/ATO
      },
    },
    bom: [{
      partId, partNo, name, qtyPer, scrapFactor, source: 'buy'|'make',
      suppliers: [{ supplierId, allocationPct, volumeTiers: Tier[],
                    moq, leadTime: { mean, cv }, ppmTarget }],
      policy: { method: 'EOQ'|'FixedLot'|'MinMax'|'JIT'|'VMI'|'Consignment',
                safetyStockDays, reorderPoint, reviewPeriod },
      inventory: { current, committed, inTransit },
    }],
    routing: {
      operations: [{
        id, name, stationId, consumes: [{partId, qty}], producesSubassy,
        cycleTimeSec, setupTimeMin, parallelism, yieldPct,
        laborHours: { skilled, unskilled },
        predecessors: OperationId[],
      }],
    },
    inventory: { current, safetyStockTarget, reorderPoint, maxStock },
    quality: { pfmaRisk, cpk, ppmTarget, appearanceCritical },
  }],

  // Tab 3 — network
  suppliers: Supplier[],
  contracts: Contract[],
  lanes: [{
    laneId, origin, destination, modes: {
      [mode]: { tiers: [{minQty, maxQty, ratePerUnit}],
                transitDays: {mean,cv}, reliability, capacity }
    }
  }],
  echelonMode: 'plant' | 'plant+DC' | 'full',

  // Tab 4 — plant & capacity (derived, read-mostly)
  stations: Station[],   // auto-aggregated from routing
  oee: { [stationId]: { availability, performance, quality } },
  shiftCalendar, laborPool, maintenanceWindows,

  // Tab 5 — finance
  assets: Asset[], depreciationPolicy, npvInputs, budgets,

  // Tab 6 — solve
  solverMode: 'deterministic'|'rolling'|'stochastic'|'robust',
  solverResults: { pipelineHash, mps, mrp, poSchedule, gantt, cost, timestamp },
  costEvents: CostEvent[],

  // Tab 7 — risk
  mcResults, sensitivityResults, scenarios: Scenario[],

  // Tab 9 — SAP mode
  sapMode: { enabled, plants: Plant[], dcs: DC[], retailPoints: Retail[],
             echelonPolicy, demandSensingML, skuCountLimit },
}
```

**Every input has one owner.** If you see the same concept in two places, the downstream place is a read-only projection of the upstream.

---

## 5. Solver Architecture (v3.0)

### 5.1 Pipeline solver (`POST /api/solve/pipeline`)
Runs the end-to-end chain in a single transaction:
1. **Forecast** → consensus demand per product per period.
2. **Profit-mix LP** → if capacity-constrained, determine optimal product mix (shadow prices of capacity).
3. **MPS MILP** → production qty per product per period honoring lot-sizing rule (Wagner-Whitin, SM, LFL, EOQ, POQ).
4. **MRP explosion** → net RM requirements from MPS × BOM (with scrap).
5. **Procurement MILP** → PO quantities per supplier per period minimizing `Σ(unit_cost + order_cost + carry + shortage_penalty)` subject to MOQ, capacity, budget, tiered pricing, lead time.
6. **Job-shop scheduler MILP** → start times per operation per station minimizing weighted (makespan, tardiness, setup).
7. **Transport LP** → lane/mode allocation minimizing freight+duty+demurrage subject to transit constraints.

Every stage's output is hashed; Tab 6 displays the **same** hash everywhere, eliminating the v2.0 bug where MPS numbers disagreed with forecast inputs.

### 5.2 Deterministic / Rolling / Stochastic / Robust modes
| Mode | When | Solver difference |
|---|---|---|
| Deterministic | Default, stable demand | Point estimates, single solve |
| Rolling-horizon | Monthly replan | Solve full horizon, commit first period, advance window with updated actuals |
| 2-stage stochastic | Lumpy demand | Demand scenarios (ω); 1st-stage decisions (PO) pre-ω, 2nd-stage (production) post-ω; minimize `E[cost]` |
| Robust (CVaR) | Tail-risk-sensitive | Minimize `CVaR_α(cost)` at α=0.95 |

### 5.3 Formulas — explicit, rendered in Tab 6

**Safety stock (per part):**
```
SS = z(σ_LTD)            where σ_LTD = √(L · σ_d² + d̄² · σ_L²)
z   from inverse-normal of service level
```

**Reorder point:**
```
ROP = d̄ · L + SS
```

**EOQ:**
```
EOQ = √(2 · D · S / H)
```

**Wagner-Whitin optimal lot sizing:** dynamic program, `F(t) = min_{1≤j≤t} [F(j-1) + S + Σ_{k=j}^{t-1} (k-j) · h · d_k]`.

**Landed cost (India import):**
```
AV  = CIF = FOB + Freight + Insurance          (on exchange rate)
BCD = AV × BCD_rate
SWS = BCD × 10%
IGST= (AV + BCD + SWS) × IGST_rate
Total_duty = BCD + SWS + IGST
Net_landed  = AV + BCD + SWS + (IGST if !gst_registered else 0) + CHA + THC + lastMile
```

**OEE capacity:**
```
Cap_day = M · S · H · 3600 / CT_ideal · OEE
OEE     = Availability · Performance · Quality
```

**Newsvendor critical ratio:**
```
q* = F⁻¹( (p − c) / (p − s) )
```

**CCC:**
```
CCC = DIO + DSO − DPO
```

**VaR / CVaR:**
```
VaR_α = inf{ x : P(L > x) ≤ 1 − α }
CVaR_α = E[L | L > VaR_α]
```

All formulas are rendered live in Tab 6 with the user's actual values substituted — so they can see exactly what the solver is computing.

---

## 6. UX Principles (v3.0)

1. **Every input has a tooltip** explaining (a) what it is, (b) what it affects downstream, (c) typical benchmark.
2. **Every toggle must have a visible effect.** If a control has no downstream consumer, it's deleted.
3. **No numbers appear without provenance.** Every computed value hovers to show its formula + inputs.
4. **No truncation without affordance.** If MPS has 90 days, show all 90 with scroll/virtualization — never silently cut to 5.
5. **Consistent granularity toggle.** D/W/M switch persists across all time-series views.
6. **Units visible everywhere.** Every number label shows unit (₹, kg, units, days, %).
7. **Provenance badge** on Tab 6 results pane: "Computed from Tab 2 / SKU-1 / Consensus forecast / Last solve 12:04 · hash c8f2a1". Clicking jumps to source.

---

## 7. SAP Mode (Tab 9) — Enterprise-Scale Features

Opt-in mode (toggle in Tab 1). Changes app behavior across the board:

### 7.1 Multi-echelon inventory optimization
- Plant → Regional DC → Retail
- Base-stock levels per echelon optimized via METRIC (Sherbrooke) or Clark-Scarf
- Echelon inventory = on-hand + in-transit + downstream holdings
- Risk pooling: upstream SS < Σ(downstream SS)
- Solver extension: `/api/solve/multi-echelon` returns per-echelon base-stock targets

### 7.2 Multi-plant coordination
- Define N plants with their own capacity, BOMs, costs
- Inter-plant transfer lanes (with transit + cost)
- Network-flow MILP minimizes total system cost:
  - Which plant produces which SKU
  - Transfer volumes
  - Second-sourcing of intermediate goods
- Supports plant-specialization strategies

### 7.3 ML-based demand sensing
- POS upload (date × location × SKU × qty × price × promo flag)
- XGBoost model with features: lag-7, lag-28, lag-365, rolling means, day-of-week, holidays, promotions
- Short-horizon forecast (1–4 weeks) blended with consensus long-horizon
- Out-of-sample MAPE displayed; falls back to statistical forecasts if ML MAPE worse

### 7.4 10k+ SKU scale
- CSV-driven bulk operations
- Batch MILP: one solve per commodity group (not per SKU)
- ABC-XYZ auto-classification; policy assignment by class
- Solver runs async; progress stream via SSE

### 7.5 ERP T-code simulator
Simulates the workflow of SAP MM/PP/WM:
- **ME51N / ME21N / ME23N** — PR → PO creation/display
- **MIGO** — Goods receipt with movement types (101, 122, 103, 261, 301, 101K)
- **MIRO** — 3-way match (PO × GRN × Invoice), blocks & releases
- **MD04** — Stock/Requirements list (planner's dashboard)
- **MD01 / MD02** — MRP run (total / single-item)
- **CO01** — Production order with status flow (created/released/confirmed/closed)
- **ME61 / ME62 / ME63** — Vendor evaluation

Each T-code has a minimal realistic screen, reads/writes the unified state model, and produces material/accounting document IDs. Learning Lab links directly to each from the T-code help.

### 7.6 Scale & performance
- Code path diverges: below 50 SKUs → standard solver; above → aggregated solver + disaggregation heuristic.
- Caching: solver inputs hashed; identical re-runs return cached results.
- Backend moved to async worker queue (Celery + Redis) on Render.

---

## 8. Build Phases & Execution Order (v3.0)

| Phase | Scope | Blocks | Deliverable |
|---|---|---|---|
| **P0 · Foundation** | Delete v2.0 dead UI (lines tab, topology duplication, cost events orphan, industry preset stub, ref-by-name). Collapse duplicated fields to single source. | — | Clean slate with no orphan inputs |
| **P1 · Tab restructure** | New tab order: Company → Products → Suppliers → Plant → Finance → Optimize → Risk → Learn → SAP. Move sections to their correct homes. | P0 | All sections in right place |
| **P2 · Product-centric routing** | Move production lines into per-product routing. Auto-aggregate into Plant tab. | P1 | Stations owned by products |
| **P3 · Data integrity** | Day-grain time store. Excel import with column mapper. Overrides below forecast. | P1 | Real historical data usable |
| **P4 · Formula surfacing** | Every computed value hoverable with formula + inputs. OEE, SS, ROP, EOQ rendered live. | P3 | User sees math |
| **P5 · Routing DAG** | Multi-operation routing with consumes/produces graph. Job-shop MILP backend. | P2 | Multi-stage production solved |
| **P6 · Contracts & tiers** | Volume discount tiers (supplier side), transport tiers (per mode). Wired to procurement+transport solvers. | P1 | Tiered pricing respected |
| **P7 · Pipeline integration** | Single `/api/solve/pipeline` with hashed outputs across all stages. Tab 6 displays consistent numbers. | P4, P5, P6 | No more mismatched MPS vs forecast |
| **P8 · Rolling / stochastic modes** | Solver modes + Tab 6 mode selector. Cost events wired into rolling solves. | P7 | Temporal cost changes honored |
| **P9 · Multi-echelon & Lanes** | Supplier→Plant→DC→Customer lanes with mode-specific tiers. Multi-echelon inventory optimization. | P6 | Real network realism |
| **P10 · Risk & scenarios polish** | MC with VaR/CVaR on pipeline. Disruption simulator (supplier down N days). Scenario comparison. | P7 | Tail-risk visible |
| **P11 · SAP Mode** | Tab 9 — multi-plant, ML sensing, T-code simulator, 10k scale. | P9 | Enterprise mode live |
| **P12 · Learning Lab refresh** | New sections (OEE, routing, multi-echelon, MILP formulation, import duty worked example from PDF). | P7 | Teaching matches app |
| **P13 · Polish** | Tooltips everywhere. Provenance badges. D/W/M toggle persistence. Export (PDF, CSV, MILP .py). | All | Finish |

---

## 9. Acceptance Criteria (to declare v3.0 done)

Run this checklist before declaring each phase done:

- [ ] No input appears in two tabs as an editable field.
- [ ] Every UI toggle maps to a `dispatch` action AND at least one solver payload field AND a consuming formula.
- [ ] Changing `workDaysPerWeek` changes effective capacity in Tab 4 and all downstream solver outputs.
- [ ] Changing service level from 90% → 98% increases safety stock in the MPS and raises total cost in the Cost Pane.
- [ ] MPS view shows ALL planning days (not truncated to 5); D/W/M toggle works.
- [ ] Forecast number displayed in Tab 2 matches the forecast number used by the Procurement MILP (hash-verified).
- [ ] Excel paste with 500 rows of messy daily data succeeds and produces a clean history.
- [ ] Overriding a single-month forecast shifts the MPS and the PO schedule; FVA is displayed.
- [ ] Adding a second supplier to a BOM part with 30% allocation produces two PO streams in the solver output.
- [ ] Declaring a 4-operation routing for a product produces a Gantt with 4 bars and the correct makespan.
- [ ] Setting `productionMode = MTO` hides the Demand Plan Overrides sub-section and activates the Customer Orders sub-section.
- [ ] Cost event (price +10% from day 90) changes unit cost in rolling-horizon solves after day 90.
- [ ] Tab 6 → MILP pane shows the objective function with user's actual numerical coefficients substituted.
- [ ] SAP Mode toggle unlocks multi-plant definition; adding a 2nd plant changes the pipeline solver to a network-flow MILP.

---

## 10. What v3.0 Deliberately Keeps From v2.0

Not everything v78/v2.0 had was bad. **Preserve as-is:**
- All 17 forecast models (SMA, SES, DES, HW-add/mul, ARIMA, SARIMA, Croston, …)
- Auto-selection by MAPE/MAD/RMSE/WMAPE/TS
- Monte Carlo 500–1000 runs with VaR/CVaR/fragility
- Auto-researcher 150 experiments
- What-if bot (Claude API-backed)
- PDF export
- MILP export (ready-to-run PuLP code)
- CSV scenario save/load

These are re-wired, not re-implemented, in v3.0.

---

## 11. What v3.0 Deliberately Excludes

Respecting scope:
- Real-time IoT/MES integration (SAP Mode only simulates T-codes; no live ERP connection)
- Finite-element production simulation (we're planning, not simulating shop floor physics)
- Workflow/BPMN designer (out of scope)
- User management & RBAC (single-user tool)
- Mobile-native app (responsive web only)

---

## 11.5 User Q&A Clarifications (v3.1 Addendum — April 2026)

This section answers eleven specific questions raised by the user post-v3.0 delivery. Each answer explains the current state, the mathematical/domain reasoning, and the fix (if any) being pushed.

---

### Q1 — Backup suppliers, lead times, and Kraljic fallback

**Current state** ([index.html:913](index.html#L913), [index.html:942](index.html#L942)): Each BOM row has ONE `backupSupplier` text field, one `backupCost`, one `backupLeadTime`, and a `backupActivation` mode (`manual`/`auto_otd`/`auto_lt`/`auto_price`). Kraljic matrix ([index.html:~4350](index.html#L4350)) classifies parts into Strategic/Leverage/Bottleneck/Non-critical using *profit impact* (cost × volume) vs *supply risk* (import flag + LT > 4w + no-backup).

**Why one backup isn't enough:** A real procurement team carries 2–4 qualified alternates per strategic part, each with its own LT, cost, qualification date, and risk score. Kraljic Strategic quadrant *mandates* dual-source or more.

**Fix in v3.1:** Promote `backupSupplier` to `backupSuppliers: []` — an array where each entry has `{name, cost, leadTime, ltCV, qualified, priority}`. Kraljic renderer counts `backupSuppliers.length` when scoring supply risk: 0 backups → high risk, 1 backup → medium, ≥2 qualified → low. Procurement MILP uses the lowest-cost *qualified* alt when primary LT exceeds `2 × primary.leadTime` or when activation mode triggers.

**How to apply:** Inside each product's BOM row, a stacked list of backups with + Add Backup button; Kraljic classification automatically reflects count.

---

### Q2 — Why does capacity use the "whole working days"?

**Current formula** ([index.html:533](index.html#L533), [index.html:1156-1160](index.html#L1156-L1160)):
```
Effective Capacity = Machines × Shifts × Hours/shift × WorkDays × OEE
```
**WorkDays** is the count of *productive* days in your planning period — typically 26 per month (6-day week × 4.33) or 22 (5-day week), *not* 365 or 30. It already excludes weekends and national holidays.

**Why not 365?** Because equipment is idle on non-work days by policy, not by the physics of the shop floor. Running 24/7 would require 3-shift rotation *and* weekend operations — if you choose that, set `workDays=30`, `shifts=3`. The formula doesn't assume "8h × 5d" — those are your inputs, not hardcoded.

**What WorkDays does NOT capture:** Per-day variability (some Mondays you lose 2h to startup, some Fridays you lose 1h to cleanup). Those go into **Availability %** (OEE's first lever), not into WorkDays.

**No fix needed — intentional separation of concerns.** The plan doc ([Section 2](#section-2)) explicitly says: "WorkDays = calendar-level policy; Availability = station-level physics."

---

### Q3 — Daily variability: unplanned vs planned maintenance

**Current state:** Only Availability % ([index.html:791](index.html#L791)) absorbs downtime — it's a *static, aggregate* percentage (default 85%). Its tooltip says "Captures breakdowns, setups, breaks" but this conflates three distinct things:

| Type | Predictability | Correct modeling |
|---|---|---|
| **Micro-stops** (jams, setup, breaks) | Statistical | Folded into **Performance %** (OEE 2nd lever) |
| **Unplanned downtime** (breakdown) | Stochastic | Reduce **Availability %**; model as Poisson arrivals with MTBF/MTTR in Monte Carlo |
| **Scheduled maintenance** (PM, overhaul) | Known in advance | Block specific weeks on that line's calendar |

**What's missing:** A per-line **maintenance calendar** — UI to say "Line 2 is down weeks 18–19 for overhaul" so the MILP zeros that line's capacity for those periods, NOT buried inside the aggregate 85% Availability.

**Fix in v3.1:** Add `plannedMaintenance: [{fromWeek, toWeek, reason, hoursLost}]` to each production line. Production solver reads this and caps `cap[l][t] = 0` (or reduced pro-rata) for maintenance weeks. Learning Lab gets a new explainer distinguishing the three types.

**For unplanned downtime:** Monte Carlo already randomizes capacity by `availability_cv` (coeff. of variation). No new field needed — just document it in the tooltip.

**How to apply:** Plant & Capacity tab → per-line section → "Maintenance Windows" mini-table with + Add button; weeks are subtracted from that line's available capacity before the MILP runs.

---

### Q4 — Effective Tax Rate section (better definition)

**Current field** ([index.html:524](index.html#L524)): Single number, default 25%, hint says "Indian corporate FY25."

**What it actually is:** The *blended after-tax rate applied to incremental taxable income* for financial optimization (NPV, WACC, depreciation tax shield, lease-vs-buy). It is **distinct** from:
- **GST/IGST** (indirect tax on goods; flows through working capital and ITC recovery, not NPV)
- **Statutory rate** (what the law quotes — 22%/25%/30% for Indian corp. depending on scheme)
- **Marginal rate** (rate on the *next* rupee of profit — matters for surcharge kicks)

**Why "effective" is the right one to use:** Because it already nets out deductions (80JJAA, depreciation, R&D credits, export incentives). A company with 25% statutory but heavy R&D claim might see 18% effective. NPV is sensitive to this — a 7pp difference compounds over 5 years.

**Where it's used in the app:**
- **NPV calc** ([index.html:~2483](index.html#L2483)): `cashFlow_after_tax = cashFlow × (1 - taxRate) + depreciation × taxRate`
- **WACC form** ([index.html:~2589](index.html#L2589)): `WACC = E/V × Re + D/V × Rd × (1 - taxRate)`
- **Buy-vs-Lease** ([index.html:~2483](index.html#L2483)): Lease payments deductible at full rate, ownership gets depreciation shield

**Default 25% is the FY25 domestic company rate under Section 115BAA (no concessional).** For new manufacturing (115BAB) it's 15%; for MSME it's 22% without surcharge on ≤₹1cr profit.

**Fix in v3.1:** Expanded tooltip + a "Preset" dropdown (115BAA / 115BAB / MSME / Custom) that auto-fills. The rate is still user-editable.

---

### Q5 — Probability Lab shows negative demand values

**Why it happens** ([index.html:3331](index.html#L3331)): The lab samples `x ∈ [μ − 3.5σ, μ + 3.5σ]` — when σ is large relative to μ (high CV, e.g., CV=40% and μ=1000, σ=400 → left tail reaches −400), the X-axis dips below zero. The normal distribution is mathematically symmetric around μ and *does* assign non-zero probability to negative outcomes.

**Domain reality:** Demand can't be negative. The normal distribution is an *approximation* that works well when CV ≤ 20%. For high-variability SKUs you should use:
- **Truncated normal** — clip the tail at 0
- **Lognormal** — if demand is multiplicative/strictly positive
- **Gamma** — flexible right-skewed alternative

**Fix in v3.1 (two parts):**
1. **Clip X-axis to `max(0, μ − 3.5σ)`** so the chart stops at zero — mathematically the PMF is still there but visually honest for demand.
2. **Add a warning banner** when CV > 25%: "High variability detected — normal approx gives P(demand < 0) > 2.5%. Consider lognormal for safety stock."
3. **Add a distribution selector** (Normal / Lognormal / Gamma) so power users can see each shape.

---

### Q6 — Learning Lab "wasn't populated with live data"

**Current state** ([index.html:3329](index.html#L3329)): The Probability Lab *does* read live data — `avgMonthly` and `stdDem` come from `state.products[active].history[]`. Z-score table and confidence intervals all use the live μ and σ.

**What may have looked static:** Sections that are purely explanatory — like EOQ formulas, transport-mode comparison, Kraljic quadrant *theory* — show formula walkthroughs with example numbers rather than live data. This is by design: those sections *teach the concept*, and swapping in live values would obscure the formula's structure.

**Fix in v3.1:** For every conceptual section, add a **"Try with your data"** footer that injects the active product's values into the worked example. E.g., the EOQ card already shows `EOQ = √(2DS/H)` — add a second line "With your SKU A: D=12,000, S=75, H=0.24 × 50 = 12 → EOQ = √(150,000) = 387 units".

---

### Q7 — How does /api/solve/pipeline actually chain?

**Exact execution order** ([app.py:334-398](app.py#L334-L398)):

1. **Step 1 — Profit Mix (LP)** runs first on `profit_data`. Outputs optimal annual quantity per SKU that maximizes contribution margin subject to shared-capacity & demand-ceiling constraints.
2. **Step 2 — Disaggregation** takes each SKU's optimal annual qty and spreads it to *weekly* quantities using the forecast as a seasonal profile (preserves shape, scales to new total).
3. **Step 3 — Procurement (MILP)** runs on `procurement_data` with demand *overwritten* by the disaggregated weekly series. Outputs PO schedule (which week, how many units, which supplier).
4. **Step 4 — Production (MILP)** runs on `production_data` with `required_qty` set to the profit-mix quantities. Outputs Gantt schedule across lines.

All four results come back as one JSON under `{profit_mix, disaggregation, procurement, production, pipeline_status}`.

**Why this order?** Profit mix has the *fewest* degrees of freedom (one number per SKU) and sets strategic direction. Procurement and production are both downstream of "how much to make." Production could theoretically run before procurement if materials are guaranteed, but in the current wiring procurement runs second so any capacity-driven shortfalls surface before scheduling.

**Shadow prices — still present:**
- `profitmix.py` and `capital.py` both extract LP duals (`constraint.pi` from PuLP)
- `solve_profitmix` returns `shadow_prices[]` with `{constraint, shadow_price, slack, binding, interpretation}`
- `solve_capital` returns budget shadow price (= NPV per extra ₹ of budget)
- Procurement MILP uses integer variables so *true* shadow prices don't exist; the solver instead reports per-constraint slack and a "marginal cost" approximation
- `app.py` doesn't strip shadow_prices — they flow through untouched

**No change needed.** Shadow prices are still in every LP result. Documented clearer in the v3.1 result renderer.

---

### Q8 — Demand sensing: the 0.3 multiplier, the 2σ rule, and SAP-style MPS sensing

**Three separate things you've seen:**

**(a) α = 0.3 in exponential smoothing** ([index.html:985-993](index.html#L985-L993)):
```
sensedForecast = α × lastActual + (1 − α) × priorForecast
```
This is **exponential smoothing** (classic Holt/Winters family). α ∈ [0, 1] controls how reactive the sensed forecast is:
- α = 0 → ignore recent actuals (pure forecast)
- α = 1 → next = last actual (fully reactive, no damping)
- α = 0.3 → 70% weight on prior forecast, 30% on latest actual. This is the Box-Jenkins rule-of-thumb for monthly data with moderate noise.

**Why 0.3 specifically?** It's a *default*, not a physical constant. For stable demand use 0.1–0.2; for trending/volatile use 0.4–0.6. Should be user-tunable.

**(b) 2σ threshold in the transport mode override** ([index.html:3253](index.html#L3253)):
> "Sensing compares actual vs forecast. When |deviation| > 2σ for 2+ consecutive periods, replan is triggered."

This is a **statistical process control (SPC)** rule — Shewhart-style 2-sigma tripwire. 95% of points should fall within μ ± 2σ under normal variation; two consecutive breaches = the process shifted (very unlikely by chance, p < 0.0025). "2σ for 2 periods" is the standard *Western Electric Rule #1-plus-persistence*.

**Why not 1σ?** Too many false alarms (32% of points). Why not 3σ? Too slow — you miss real regime changes. 2σ is the industry compromise.

**(c) The 0.3 inside `transport.py:91`** is a completely separate number — a **lost-revenue-penalty multiplier** used to justify air override. It says "count stockout cost at 30% of daily revenue × shortage days." It shares the digits with α=0.3 by coincidence.

**SAP's real-time demand sensing:** SAP IBP (Integrated Business Planning) — and its "Demand Sensing" module specifically — reads *actual POS, shipments, and orders* every few hours and nudges the short-horizon forecast (typically 0–6 weeks) using pattern-based ML (not just α-smoothing). It feeds the short-term MPS, while the traditional statistical forecast still drives medium/long horizon.

**Our sim's gap:** We have (a) wired to the weekly MPS re-plan, but the 2σ SPC rule is only documented for the *transport* override. For SAP-like MPS sensing we'd need: a daily actuals intake, a pattern-match layer, and a handoff rule between short-horizon sensed forecast and medium-horizon statistical forecast.

**Fix in v3.1:**
1. Expose `sensingAlpha` as a slider (default 0.3) with tooltip showing the α-interpretation table.
2. Move the 2σ rule from the transport-only Learning Lab card into a dedicated "MPS Demand Sensing" card that fires weekly replans (not just air overrides).
3. Rename the 0.3 transport penalty to `stockoutRevenuePct` and expose it separately.
4. Add a v3.2 roadmap note for "SAP-IBP-style pattern sensing" (ML-based, not statistical).

---

### Q9 — MTO vs MTS and concurrent demand/consumption

**Current state** ([index.html:1560-1561](index.html#L1560-L1561), [profitmix.py:26](profitmix.py#L26)): A `demandMode` dropdown exists with four options (mts / mto / ato / seasonal). The profit mix solver branches:
- **MTS** — demand ceiling = forecast × (1 + MAPE buffer); all unfilled forecast is an opportunity cost
- **MTO** — demand ceiling = sum of confirmed MTO orders only; no speculation
- **ATO** (assemble-to-order) — components forecasted, final assembly built only on order
- **Seasonal** — uses full forecast with explicit seasonal index

**Where it's incomplete:** Procurement and production solvers *ignore* the mode and treat all demand as MTS-style (forecast-driven). In a true MTO shop:
- There's no RM pre-build (parts ordered only when order lands)
- Inventory holding cost is near-zero (work-in-progress only)
- Capacity planning uses *order arrival rate* (Poisson), not forecast
- Lead-time-to-quote becomes the binding constraint, not fill rate

**Concurrent demand/consumption** — what the user is getting at:
- In MTS the app assumes *demand arrives and is consumed in the same period* (instant fulfillment from stock). Safety stock exists for this reason.
- In MTO you can't fulfill in the demand period; you quote a due date (= today + manufacturing LT). The app currently still treats MTO demand as period-t consumption — that's the bug.
- In MTS+MTO hybrid (most real companies) some SKUs stock, some ship-to-order — same simulator needs to handle per-SKU mode.

**Fix in v3.1:**
1. Propagate `demandMode` from product state to procurement & production solvers (currently only profit mix uses it).
2. For MTO SKUs: consume demand at `period + manufacturing_LT`, not `period`. Procurement triggers on firm orders, not forecast.
3. Add `engineerToOrder (ETO)` mode for fully custom product flow.
4. Learning Lab card: "Understanding demand fulfillment — instant vs lead-time-gated."

---

### Q10 — Incoterms: only 4 shown, there should be more

**Current state** ([index.html:912](index.html#L912)): Dropdown has 4 options (EXW, FOB, CIF, DDP). You're right — that's incomplete.

**Incoterms 2020 — full set (11 rules):**

**Any mode of transport (7):**
| Code | Name | Responsibility transfers at |
|---|---|---|
| **EXW** | Ex Works | Seller's premises (buyer handles everything) |
| **FCA** | Free Carrier | Named place of delivery to carrier |
| **CPT** | Carriage Paid To | Carrier at origin; seller pays freight |
| **CIP** | Carriage and Insurance Paid | Same as CPT + seller's insurance |
| **DAP** | Delivered at Place | Named place; seller handles transit |
| **DPU** | Delivered at Place Unloaded (new in 2020; replaces DAT) | Named place, unloaded |
| **DDP** | Delivered Duty Paid | Buyer's door, all duties paid by seller |

**Sea and inland waterway only (4):**
| Code | Name | Responsibility transfers at |
|---|---|---|
| **FAS** | Free Alongside Ship | Ship's side at origin port |
| **FOB** | Free on Board | On board vessel at origin port |
| **CFR** | Cost and Freight | On board vessel; seller pays to destination |
| **CIF** | Cost, Insurance, Freight | CFR + seller's insurance |

**Why mode matters:** You can't use FOB for air freight — FOB is *specifically* about ships crossing the rail. Airfreight uses FCA. Picking the wrong Incoterm for the wrong mode is a real compliance issue.

**Fix in v3.1:**
1. Expand dropdown from 4 → 11 rules.
2. Grey out sea-only rules when `transMode !== 'sea'`.
3. Show a one-line tooltip for each selected rule: "Who pays freight/insurance/duty, where risk transfers."
4. Landed-cost calc already handles CIF → duty correctly; extend to compute CIP/CFR/FAS/DAP equivalents.

---

### Q11 — The 17 forecasting models: can you see the math? Are alpha/beta user inputs?

**Current state** ([index.html:153-236](index.html#L153-L236)): Seventeen models all defined in one `forecasters` object. Each model is a pure function `(history[]) => forecast[]`. Parameters are hardcoded:
- SES, Adaptive SES: α = 0.3 (Adaptive auto-tunes by grid search)
- DES (Holt): α = 0.3, β = 0.1
- Brown's DES: two-component with internal α
- HW Add/Mul: α = 0.3, β = 0.1, γ = 0.1, seasonal period = 12
- ARIMA/SARIMA: simplified AR(1) + drift / AR(1)×seasonal
- Croston's: α = 0.1 (for intermittent demand)

**User input today:** None. You can't tune α, β, γ, period. You can't see the math either — models run silently and only their MAPE shows up in the competition.

**Why α/β aren't blindly user inputs in industry:** Most practitioners let **auto-tuning** find them (minimize in-sample MAPE via grid search on [0.05, 0.10, …, 0.95]). Manual tuning is for when you have strong priors (e.g., "demand definitely has a weekly pattern, γ should be high"). The exposed UX compromise: default = auto-tune, advanced users unlock a slider.

**Fix in v3.1 (two parts):**
1. **"Explain this model" button** next to each model row in the Forecast Competition table → pops a modal showing:
   - The formula (rendered in MathJax)
   - The worked recurrence on the current product's history (first 3 steps)
   - Each parameter's current value and sensitivity (e.g., "increase α by 0.1 → MAPE shifts by +2.3%")
2. **Parameter override panel** (collapsible, "Advanced") per model — sliders for α, β, γ, p, d, q, seasonal period. Runs the full competition with overrides applied.

**Alpha/beta meaning for non-experts:**
- **α (level smoothing)** — how much weight recent actuals get. High α = reactive, low α = smooth.
- **β (trend smoothing)** — how much weight recent trend changes get. Only in double/triple exponential smoothing.
- **γ (seasonality smoothing)** — how much weight recent seasonal patterns get. Only in Holt-Winters.
- **p, d, q (ARIMA)** — autoregressive order, differencing order, moving-average order.
- **P, D, Q, s (SARIMA)** — seasonal counterparts + season length.

---

## 11.6 User Q&A — Second Round (Q12–Q16)

### Q12 — Maintenance: a few hours on a specific date, not weeks

**Current state (v3.1):** Per-line `plannedMaintenance: [{fromWeek, toWeek, reason}]` — granularity is whole weeks. Solver zeros capacity `cap[l][t] = 0` for covered weeks ([production.py:~80](production.py#L80)).

**User's real need:** "Line 3 is down 14:00–18:00 on 2026-05-12 for bearing replacement." Four hours on one day, not a week. Zeroing the entire week overstates the disruption by 40× and corrupts the plan.

**Fix (v3.1.1):** Upgrade the struct to
```
plannedMaintenance: [{ date: 'YYYY-MM-DD', fromHour: 14, toHour: 18, reason: '', hoursLost: 4 }]
```
- Solver reduces `cap[l][t]` proportionally: `cap_effective = cap × (1 − hoursLost / totalAvailableHoursInPeriod)` for the week containing that date.
- If `hoursLost ≥ totalHoursInWeek`, capacity = 0 (equivalent to old behavior).
- UI: date picker + "from/to hour" or "total hours" shortcut. Both weekly and hourly modes coexist (radio toggle per entry).

**Why this is exactly right:** OEE's Availability % captures the *statistical* downtime pattern. Hourly maintenance calendar captures the *known, scheduled* events. Together they cover both classes without double-counting.

---

### Q13 — SAP IBP-style pattern sensing: implemented?

**Honest answer: No.** What we have is classical α-smoothing (`sensed = α × actual + (1−α) × forecast`) — single parameter, single signal, no pattern layer.

**What SAP IBP Demand Sensing actually does** (for reference, not promised):
1. **Multi-signal intake** — POS, shipments, orders, weather, promotions, web traffic. Each signal has its own lag and correlation weight.
2. **Pattern library** — learned templates for recurring shapes (promo lift curve, holiday ramp, weekend dip, post-outage bounce).
3. **ML matching layer** — each new actual is matched against patterns using gradient-boosted trees or neural nets; the closest-match template nudges the short-horizon forecast.
4. **Horizon handoff** — sensed forecast drives weeks 0–6, statistical forecast drives 7+. There's a soft blend in the overlap zone.
5. **Confidence scoring** — every sensed value comes with a posterior uncertainty that feeds downstream safety-stock calcs.

**What would be required to implement** (v3.2 roadmap):
- Multi-signal ingestion endpoints (POS, orders, ops events)
- Pattern library (~10 canonical shapes) with parametric form
- Pattern-match scoring using cosine similarity / DTW on residual series
- Blended handoff logic between short-term sensed and medium-term statistical forecasts
- Posterior variance propagation

**Non-goal for v3.1:** We're labeling this feature as "Roadmap v3.2 — Not Yet Implemented" in the Learning Lab to avoid pretending it exists. The α-smoother is kept as a *baseline* for the simpler use case.

---

### Q14 — Why does profit mix optimize over a yearly scope?

**Current state** ([index.html:1320](index.html#L1320), [profitmix.py:52-53](profitmix.py#L52-L53)): The payload sends `forecast: p.history` — the *full* 24-month history. The solver does `period_demand = sum(forecast)`, which aggregates everything. When `state.planning.periods = 26` (weeks = ~6 months), the UI says "plan 6 months" but the solver optimizes against 24 months of demand. That's the mismatch.

**Additional bug:** `shared_capacity = capacity × periods` uses `periods` in **weeks**, while `demand` is in **months/units**. The resulting LP has mismatched time units — the capacity side inflates unless you realize periods were meant as weeks.

**The correct scoping:**
1. Convert planning horizon to the same time unit as the forecast (monthly → months; weekly → weeks).
2. Slice the forecast to *exactly* the horizon length.
3. Express capacity in the same unit: `capacity_per_period × number_of_periods`.

**Fix in v3.1.1:**
- Derive `horizon_months = ceil(planning.periods × 7 / 30.5)` if periods is in weeks.
- Send `forecast: p.history.slice(-horizon_months)` — the last N months, not all 24.
- Add an explicit `planning_horizon_months` field to the payload so profitmix.py doesn't guess.
- Document the convention at the top of `profitmix.py`: "Scope = planning.periods. Not yearly. Not historical horizon."

---

### Q15 — Daily granularity for disaggregation and procurement

**Current state:**
- `disaggregate.py` already computes a `daily[]` series ([disaggregate.py:117-127](disaggregate.py#L117-L127)) but it's currently ignored by the procurement solver.
- `procurement.py` runs at `T = periods = 26` weeks. Every PO timing, every inventory balance, every yield/lead-time constraint — all weekly.

**Why it was weekly:** Procurement MILP complexity scales roughly `O(T × n_materials × n_suppliers × n_policies)`. Going from T=26 to T=180 multiplies variable count by ~7× and constraint count by ~7×. On a laptop, CBC solves weekly in 2–10s and daily in 60–300s for the same problem size.

**When daily is necessary:**
- FMCG with daily POS variability
- Short-shelf-life (perishables, pharma) where RM shelf life < 7 days
- High-velocity SKUs where a 1-week bucket masks real stockout risk
- Multi-shift scheduling where shift-to-shift handoff matters

**When weekly is fine:**
- Discrete manufacturing with LT > 2 weeks
- Stable MTS flow where intra-week variability < MAPE
- Traditional MPS/MRP environments (SAP PP runs weekly MRP by default)

**Fix in v3.1.1 (two-track):**
1. **New payload parameter:** `time_grain: 'daily' | 'weekly' | 'monthly'`. Default = `weekly`. The solver expands `T` accordingly (`T = horizon_days` if daily) and treats the demand/capacity arrays as daily.
2. **Daily disaggregation wiring:** When `time_grain='daily'`, pipeline uses `disagg.daily` instead of `disagg.weekly` to feed procurement.
3. **Solver warning:** If `T > 120`, surface a banner: "Daily grain on 6-month horizon = 180 periods. Solve may take 60–300s. Consider weekly + look-ahead heuristic."

**What we're NOT doing (yet):** Rolling daily re-plan inside the MILP. That's a v3.2 concern (scenario tree).

**Failure modes we might be missing** (verification checklist for the solver review):
- [ ] **Shelf life truncation** — procurement currently enforces `inventory[t] ≤ shelf_life × avg_usage`. When daily, the constraint set explodes; easy to index wrong and get off-by-1 errors.
- [ ] **Lead-time modular arithmetic** — when converting weekly LT to daily LT, rounding direction matters. `LT_days = ceil(LT_weeks × 7)` is safe; floor risks under-ordering.
- [ ] **MOQ vs daily usage** — an MOQ of 500 units on a daily usage of 20 units is a 25-day supply. That's fine for weekly; for daily, it creates lumpy inventory that the linear holding cost misrepresents.
- [ ] **Changeover time on sub-day granularity** — production solver's changeover variable is per-period; on daily grain, a 4-hr changeover spans half a "period" — need fractional.
- [ ] **Yield stage-accumulation** — routing DAG cascaded yield is already in place; daily grain just multiplies the number of times it's evaluated.
- [ ] **Holidays inside the horizon** — weekly T=26 elides holidays into reduced workdays. Daily T=180 needs explicit zero-capacity days.

---

### Q16 — Lot-sizing rules: only 5 options, are they wired?

**Current state** ([index.html:908](index.html#L908)): `procPolicy` dropdown has 6 options — **MILP, JIT, EOQ, MRP, Lot-for-Lot, Kanban**. In `procurement.py`, a grep for `proc_policy`/`procPolicy` returns **zero matches**. The field is captured in state but never read by the solver — it's cosmetic.

**Truthful statement:** Today the MILP alone decides order quantities. The `procPolicy` dropdown has no effect.

**Full lot-sizing taxonomy (the 10+ you mentioned):**
| Rule | How it decides |
|---|---|
| **Lot-for-Lot (LFL)** | Order exactly the net requirement each period. Zero inventory between orders. |
| **EOQ** | Fixed quantity = √(2 D S / H). Best when demand is steady. |
| **Fixed Order Quantity (FOQ)** | Always order X units. User-defined X (often MOQ). |
| **Fixed Order Period (FOP / POQ)** | Always order every N periods. Quantity = sum of demand over N. |
| **Min-Max** | When inventory ≤ Min, order up to Max. Reorder-point style. |
| **Economic Production Quantity (EPQ)** | EOQ variant for in-house production; accounts for production rate. |
| **Wagner-Whitin (WW)** | Dynamic programming — optimal cost-minimizing lot sequence for deterministic demand over a horizon. |
| **Silver-Meal** | Heuristic — pick horizon that minimizes average cost per period. |
| **Part-Period Balancing (PPB)** | Pick horizon where cumulative holding cost ≈ setup cost. |
| **Least Unit Cost (LUC)** | Extend the horizon as long as unit cost (setup + holding) keeps dropping. |
| **Least Total Cost (LTC)** | Similar to PPB with stricter convergence. |
| **Just-In-Time (JIT) / Kanban** | Pull-based; order only when consumed. Zero setup cost and near-zero inventory assumed. |
| **MRP** | Not a lot-sizing rule per se — it's the framework that calls one of the above for each part. |
| **MILP (what we do)** | Solve the full ILP including MOQ, volume discounts, and shelf life in one shot. Generalizes *all* of the above if setup cost is modeled. |

**Do companies really use them all?** Yes — different parts get different policies. A cheap bolt gets EOQ (stable demand, low admin per order). A high-value strategic part gets Wagner-Whitin or LFL (every order expensive, high holding cost). A Kanban-fed line-side bin gets JIT. A perishable gets Silver-Meal (respects the horizon). Running MILP on thousands of SKUs is too slow — so companies use heuristic lot-sizing per part and solve MILP only for strategic SKUs.

**Is MILP alone enough?** For a 1–50 SKU simulator, yes. For 10,000 SKUs, no — even CBC on 10,000 parts × 180 days is infeasible on a laptop. That's why SAP PP runs MRP with per-part lot-sizing rules, not a single global MILP.

**Fix in v3.1.1:**
1. **Expand the dropdown** to all 13 rules above.
2. **Wire `proc_policy` through to the solver** — `procurement.py` branches per-part:
   - LFL, EOQ, FOQ, FOP, Min-Max → closed-form per-part calc, bypasses MILP for that part
   - WW, Silver-Meal, PPB, LUC, LTC → heuristic DP/greedy, bypasses MILP
   - MILP → include in global MILP as before
   - JIT/Kanban → zero lot size, zero setup, consumed-as-needed
3. **Show which parts ran under which rule** in the result panel — a column "Policy Applied".

**What's missing if we don't do this:** The dropdown is lying to the user today. A cheap cosmetic fix to preserve honesty is to hide the dropdown entirely for now; the right fix is to wire it.

---

## 12. Immediate Execution (starting now, no approvals)

Auto-mode active — executing P0 and P1 in this same turn. Specifically:
1. Delete the orphan "Supply Chain Network Topology" subsection in SetupTab.
2. Delete the global "Production Lines" subsection in SetupTab.
3. Collapse duplicate variable-cost + carry-rate inputs to single source in ProductsTab.
4. Replace target-utilization with OEE trio (Availability × Performance × Quality) in state + capacity formulas.
5. Make service level a free-form numeric input (50–99.99).
6. Add tooltips to GST-registered, effective-tax-rate, planning-horizon, workdays to explain downstream effects.
7. Fix the "industry preset" selector to actually seed defaults (and remove the broken automotive/pharma stubs).
8. Remove "reference by name" cosmetic toggle.
9. Wire cost events to procurement solver payload.
10. Expose all MPS days (not just 5) with D/W/M toggle.

Deeper phases (P2 routing, P3 Excel import, P5 job-shop DAG, P9 multi-echelon, P11 SAP mode) require multi-session effort; their full implementation is scheduled across subsequent turns but v3.0's *architecture* is locked in by this plan.

---

_End of Master Plan — v3.0_
