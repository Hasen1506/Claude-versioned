# Round 7 Handoff & Buckets 2/3/4 Context

> **Purpose:** Pre-`/compact` reference document. After context compaction the
> conversation summary will be lossy. This file is the durable spec a future
> session can re-enter from. Read top-to-bottom: Section A is "what shipped in
> R7", Sections B–D are "what to build next, ready-to-implement", Section E is
> the parked item, Section F is carryover.

> **Working file:** `/workspaces/Claude-versioned/index.html` — single-file
> React+JSX SPA. ~14,500 lines after R7. All edits live here.

> **Validation pattern:** After every round, run Babel parse on the main
> `<script type="text/babel">` block. The R7 main block parsed at 1,208,847 bytes.

> **Naming convention:** Round 7 features carry `// Round 7 —` comments. Future
> rounds should use `// Round 8 —` etc. so the diff timeline is readable.

---

## A0. What shipped in Round 8 (Bucket 2 — BOM ↔ Locations ↔ Transport coherence)

**Working file size after R8:** 1,232,850 bytes (R7 baseline: 1,208,847; net +24KB).

### A0.1 — B1 · Inbound/Outbound network classification
- New field `state.network.nodes[i].direction ∈ {'inbound','outbound','both'}`
- Defaults: supplier→inbound, customer→outbound, plant/wh/dc→both
- Locations Master card (Tab 1) now renders TWO tables: 📥 INBOUND NETWORK + 📤 OUTBOUND NETWORK, each filtered by direction. Nodes marked 'both' appear in both views (intentional — bidirectional sites genuinely belong in both).
- New 'Dir' column on the table; type-change auto-resets direction to the new type's default
- Reducer: ADD_NETWORK_NODE + UPDATE_NETWORK_NODE preserved (no new actions); direction is just another field on payload

### A0.2 — B2 · Per-node UoM-aware storage capacity + density
- New field `state.network.nodes[i].storageCapacity = {units, kg, L, m3}` (0 = unconstrained in that dim)
- New field `b.densityKgPerL` on BOM parts (for liquid storage L↔kg conversion when m³ isn't set)
- New top-level helpers (added near existing `landedCost`):
  - `nodeCapacityFor(node, uom)` — returns capacity for one UoM, 0 = unconstrained
  - `partQtyIn(b, qty, uom)` — converts a qty to the requested UoM via b.weightKg / b.volumeCbm / b.densityKgPerL. Returns NaN if conversion not derivable.
- UI: each storage row in Locations Master gets an expand chevron `▸/▾` that opens an inline panel below with 4 NumInputs (Units / kg / L / m³). Backed by `n._expanded` toggled via UPDATE_NETWORK_NODE.
- `partQtyIn` precedence in 'L': prefer `b.volumeCbm × 1000`; fallback to `weightKg / densityKgPerL`.

### A0.3 — B3 · Transport-contract rate basis + min-charge
- New fields on `state.transportContracts[i]`:
  - `rateBasis ∈ {'tonneKm','m3Km','unitKm','perTrip','flatPeriodic'}` (default 'tonneKm')
  - `minCharge` (₹ floor per shipment; default 0)
- New top-level helper `transportShipmentCost({qty, b, distanceKm, mode, contract})`:
  - tonneKm: `mode.ratePerTonneKm × contract.rateMult × tonnes × km` (tonnes via partQtyIn(b,qty,'kg')/1000)
  - m3Km: × m³ × km
  - unitKm: × units × km
  - perTrip: flat (mode.ratePerTonneKm × rateMult), ignores qty/distance — interpret rate as ₹/trip
  - flatPeriodic: returns 0; caller amortises subscription fee at period level
  - Final = `max(computed, minCharge)`
- UI: contract editor table gains 2 columns (Basis dropdown + Min charge NumInput)

### A0.4 — B4 · FTL/LTL auto-pick + disruption fallback
- New mode fields `truckCapacityKg, truckCapacityM3` (FTL=16000kg/80m³, Air=5000kg/30m³, LTL=0/0 = unconstrained)
- New BOM fields `defaultTransModeCode` ('LTL'), `fallbackTransModeCode` ('Air'), `airRateBandMin/Max`
- New top-level helper `pickTransportMode({qty, b, modes, defaultModeCode, fallbackModeCode, disruptions, fillThreshold=0.6})`:
  - Returns `{mode, reason, fillKg, fillM3, capacityKg, capacityM3, tripsNeeded}`
  - Reasons: `default | auto-upgrade-ftl | disruption-fallback | truck-overflow | no-truck-mode`
  - Disruption check matches `d.modeCode === def.code` OR `d.scope==='transport-mode' && d.scopeId===def.id`
  - Auto-upgrade to FTL when fill ratio ≥ 0.6 on either kg or m³ dim; truck-overflow → tripsNeeded = ceil(fillRatio)
- UI: BOM editor's transport sub-row gets 4 new fields (default mode, fallback mode, air rate min, air rate max) + an auto-pick preview chip showing what mode + reason at MOQ. Modes table gets 2 columns (Truck kg / m³).

### A0.5 — B5 · Landed-cost chip + waterfall on BOM row
- The existing 📦 Landed chip on the BOM main row was already present; B5 adds the **inline waterfall panel** that opens when chip is clicked (`b._showLanded` toggle). Panel renders 6-component breakdown (base + freight + insurance + duty + handling + GST sunk = total) using existing `landedCostBreakdown()` helper.
- New BOM fields `sourceLocationId` (FK to network.nodes filtered by inbound direction) + `transportContractId` (FK to transportContracts) — surfaced inline in the waterfall panel as 2 selects.

### A0.6 — B6 · Inline ordering-cost breakdown (replaces gear-icon prompt)
- The previous "edit ⚙" button used `prompt()` 4 times in sequence to capture admin/freight-fixed/receivingQC/setup. Replaced with inline `▾ open / ▴ hide` toggle (`b._showOrdBreakdown`) that opens a 4-NumInput grid below the procurement section. Σ auto-feeds back to `b.orderingCost` so the EOQ formula stays current.

### A0.7 — Top-level helpers added (R8)
```
nodeCapacityFor(node, uom) → number
partQtyIn(b, qty, uom) → number | NaN
transportShipmentCost({qty, b, distanceKm, mode, contract}) → ₹
pickTransportMode({qty, b, modes, defaultModeCode, fallbackModeCode, disruptions, fillThreshold}) → object
```

### A0.8 — Verification artifacts (R8)
- Babel parse: ✓ on full 1.23MB main script
- 6 unit-style smoke tests passed:
  1. transportShipmentCost(800L liquid, density 1.05 kg/L, 500km, ₹2/t·km) → 840 ✓
  2. pickTransportMode(800L LTL default) → LTL (fill 5.25%) ✓
  3. pickTransportMode(15000L LTL default) → FTL auto-upgrade (98% fill) ✓
  4. pickTransportMode(LTL blocked by disruption) → Air fallback ✓
  5. transportShipmentCost(tiny qty + minCharge 500) → 500 (floor honored) ✓
  6. transportShipmentCost(perTrip basis, rate 5000) → 5000 (flat) ✓

### A0.9 — NOT shipped in R8 (legitimately deferred)
- Solver wiring of B3/B4 helpers — `transportShipmentCost` and `pickTransportMode` are exposed at module scope but the existing solver payload at line ~5530 still uses `landedCost(b,...)` only. Bucket 3 work or a separate "wire B3/B4 into solver payload" round will integrate them. The UI preview chip (B4) demonstrates correctness.
- Joint replenishment / multi-SKU truck consolidation — flagged as Bucket 2 territory in C1.e but parked: needs a new MILP variable per (truck, period) that is too invasive for B-bucket scope.

### A0.10 — Round 8 file anchors (post-R8 line numbers — re-grep before editing)
- New helpers in main script: `grep -n 'function nodeCapacityFor\\|function partQtyIn\\|function transportShipmentCost\\|function pickTransportMode'`
- Locations Master split: search 'INBOUND NETWORK' / 'OUTBOUND NETWORK'
- Storage capacity expand-row: search 'Multi-UoM storage cap'
- Auto-pick preview chip: search 'Auto-pick @ MOQ'
- Inline ordering-cost editor: search 'ORDERING-COST S BREAKDOWN'
- Inline landed-cost waterfall: search 'LANDED COST WATERFALL'

### A0.11 — Bucket 2 → Bucket 3 bridge (still relevant for next round)
The composite, mode-dependent ordering cost discussion in C1.e is now **partially unblocked**:
- `pickTransportMode` returns the chosen mode, `transportShipmentCost` returns ₹ at that mode
- Wire `S_effective(mode) = b.ordBreakdown.admin + b.ordBreakdown.receivingQC + b.ordBreakdown.setup + transportShipmentCost(...)` in the solver payload
- That converts the previously-flat `orderingCost` into a step function (FTL break-even decisions) — exactly what big orgs do

---

## A. What shipped in Round 7 (Architecture + Finance Depth)

### A1. App-level view-mode toggle
- `state.config.viewMode ∈ {'operational' | 'finance'}` — defaults `'operational'`,
  persists via the existing localStorage path
- Reducer action `SET_VIEW_MODE` at index.html (added in R7 reducer block)
- Toggle pill in masthead `mast-right` group, sits left of skin pill
- `visibleTabs` filter in `App` component — `FINANCE_TAB_IDS = ['setup','finance','invest','command','learn']`
- `switchMode(m)` auto-redirects active tab if hidden
- `esim:setActiveTab` event handler in `App` auto-switches mode back to
  operational when nav lands on a hidden tab

### A2. New Tab: `invest` — Investment Decision
- Added to `TABS` array (id 7B, label 'INVEST', between finance and optimize)
- `renderTab()` switch case `'invest': return <InvestmentDecisionTab .../>`
- Three cards:
  1. **Cash Flow Builder** — period-by-period rows; computes `NetCF = (Rev−OpEx)·(1−tax) + Dep·tax − CapEx − ΔWC + Terminal`. State key: `state.finance.cfBuilder = {grain, horizon, rows[]}`.
  2. **Equity Sources & Opportunity Cost** — `state.finance.equitySources[]` with Fisher real-return weighted across tranches: `((1+alt)/(1+infl))−1`. Verified test: 12% alt + 6% infl → 5.6604% real.
  3. **Investment Verdict** — Two-rate NPV (WACC + opp cost), discounted payback both rates, profitability index, decision matrix (INVEST / MARGINAL / REVIEW / REJECT) with worst-tranche callout when MARGINAL.

### A3. FinanceTab sub-tab navigator
- Local `useState('cashflow')` for `activeSub`
- 7 sub-tabs: cashflow | npv | assets | capital | bvl | cac | fx
- Existing 14 cards each wrapped in `{activeSub==='X' && <>...</>}`
- Sticky nav bar at top of FinanceTab with `→ Investment Decision` deep-link

### A4. Componentised Asset Register (IAS 16 / Schedule II)
- Each asset gets optional `components[]` — `{id, name, allocationPct, usefulLife, method ('SLM'|'WDV'), wdvRate}`
- Reducer actions: `ADD_ASSET_COMPONENT`, `UPDATE_ASSET_COMPONENT`, `DELETE_ASSET_COMPONENT`
- Annual Depreciation per asset = `Σ(component depreciation)` when `components.length > 0`, else falls back to flat asset-level method (backward compatible)
- "🧩 Componentise" button on each asset row; expands inline editor with allocation-sum sanity check (must total 100%)
- Two seed-button presets: CNC components (5-part split) and Press/Crane components (4-part split)
- Total CapEx panel's `totDep` calc updated to respect components

### A5. Debt Schedule with DSCR/DSRA/CADS
- `state.finance.debtSchedule[]` — `{id, name, amount, tenureYears, repaymentType ('emi'|'bullet'|'balloon'|'step_up'|'straight'), couponPct, dsraMonths, drawdownYear}`
- Reducer actions: `ADD_DEBT_TRANCHE`, `UPDATE_DEBT_TRANCHE`, `DELETE_DEBT_TRANCHE`
- Inserted as a sub-section inside Master Budget & Capital Structure card (Tab 7 → Capital Structure & Debt sub-tab)
- EMI formula verified: 30L @ 9% × 5yr → ₹771,277/yr ✓
- DSCR table: per-year Interest, Principal, Total DS, DSRA, CADS, DSCR (color: red <1.0, amber 1.0–1.3, green ≥1.3)
- CADS sources from Cash Flow Builder via `cfBuilderFlows()`. Empty → "Build cash flow to see DSCR" placeholder.

### A6. CAC + Inflation + NPV-anchored LTV
- Tab 7 CAC card: added `inflationPct` field
- New KPIs: Payback (real, after inflation), NPV-LTV @ WACC, NPV-LTV / CAC ratio
- Geometric annuity formula for NPV-LTV: `mpc × (1−(1+r)^−lt) / r` where `r = WACC/12`. Verified: 5000 × 24mo @ 10% → ₹108,354 ✓

### A7. State shape additions (defaultState.finance + config)
```
state.config.viewMode: 'operational' | 'finance'    // default 'operational'
state.finance.equitySources[]: [{id, name, amount, sourceType, altReturnPct, inflationPct, notes}]
state.finance.debtSchedule[]: [{id, name, amount, tenureYears, repaymentType, couponPct, dsraMonths, drawdownYear}]
state.finance.cfBuilder: {grain: 'yearly'|'quarterly'|'monthly', horizon: number, rows: [{id, period, revenue, opex, capex, dWC, depreciation, terminal}]}
state.assets[i].components[]: optional [{id, name, allocationPct, usefulLife, method, wdvRate}]
state.budget.marketingDetail.inflationPct: number
```

### A8. Reducer actions added (R7)
```
SET_VIEW_MODE
ADD_EQUITY_SOURCE / UPDATE_EQUITY_SOURCE / DELETE_EQUITY_SOURCE
ADD_DEBT_TRANCHE / UPDATE_DEBT_TRANCHE / DELETE_DEBT_TRANCHE
SET_CFB / CFB_ADD_ROW / CFB_UPDATE_ROW / CFB_DELETE_ROW
ADD_ASSET_COMPONENT / UPDATE_ASSET_COMPONENT / DELETE_ASSET_COMPONENT
```
All co-located with `SET_FINANCE` in the reducer (search for `// Round 7 —`).

### A9. Top-level helpers added (R7)
- `cfBuilderFlows(cfb, taxPct)` → `[CF_0, CF_1, ...]` from CF Builder rows
- `realRet(altPct, inflPct)` → Fisher real return (decimal)
- `weightedOppCost(tranches)` → percentage-form weighted real opp cost
- `npvLocal`, `irrLocalDetailed` — pre-existing from prior rounds, reused

### A10. Verification artifacts
- Babel parse: ✓ on full 1.16MB main script block
- 6 unit-style smoke tests passed:
  1. Fisher real return: 12%/6% → 5.6604% ✓
  2. Weighted opp cost: 4M@12%/6% + 1M@7.5%/6% → 4.8113% ✓
  3. Cash flow builder formula: -50L investment + 15L rev + 4L depr → ₹850k Y1 ✓
  4. Componentised depreciation: 60% jib SLM 15yr + 40% electricals WDV 25% → ₹138,000 ✓
  5. EMI annuity: 30L × 9% × 5yr → ₹771,277/yr ✓
  6. NPV-LTV: 5000 × 24mo @ 10% WACC → ₹108,354 ✓

### A11. NOT shipped (legitimately deferred from R7 scope)
- "moved in v3.0" notice removal — only one comment exists at index.html:11176 ("removed in v3.3.3"), it's a JSX comment not visible to the user. No-op.
- Master Budget Envelope unlock — investigated, the head fields (Procurement, CAPEX, Logistics, etc.) ARE editable. Only the master TOTAL is auto-derived from Equity + Σ Debt instruments by design. The hint at line 3050 already explains this. Could be made more visible but not "locked".

---

## B. Bucket 2 — BOM ↔ Locations ↔ Transport coherence (✅ SHIPPED IN R8 — see section A0)

> **Status as of 2026-05-08:** Bucket 2 was implemented in Round 8. The
> sub-spec language below is preserved for reference; the actual deltas
> are documented in section A0. **Do not re-implement — read A0 first.**


### B1. Inbound vs Outbound location classification
**Why:** The user said "Locations master shows only outbound network — define
locations master as separate inbound and outbound." Today
`state.network.nodes[]` holds plant/dc/customer/supplier without a clean
inbound/outbound axis.

**Spec:**
- Add `direction: 'inbound'|'outbound'|'both'` to network nodes (default by
  type: supplier→inbound, customer→outbound, plant/DC/warehouse→both)
- In Tab 1 Locations Master (index.html:2824, may have shifted post-R7), split
  the rendering into two sub-cards: 📥 INBOUND NETWORK (suppliers + plants
  receiving) and 📤 OUTBOUND NETWORK (DCs + warehouses + customers)
- Lanes already have from/to — auto-classify lanes into inbound (origin is
  supplier) and outbound

### B2. UoM-aware storage capacity per part
**Why:** The user said "subparts x, y, z of product A has storage capacity
of this much in this location based on accurate unit of measurement". Today
storage capacity is `unitCapacity` (units only).

**Spec:**
- Per-node storage capacity becomes `storageCapacity: {kg: N, L: N, m3: N, units: N}`
- Each BOM part already has `uom` field — but no unit-conversion factor.
  Add `weightKgPerUnit, volumeM3PerUnit, densityKgPerL` to each BOM part.
- Capacity check at solve time: for each (node, part), sum on-hand × per-unit
  weight/volume must fit the node's storage in the same UoM.

### B3. Transport contracts UoM-aware rate basis
**Why:** Contracts are priced "₹/tonne-km" but parts are stored in litres or
units. Need conversion.

**Spec:**
- `state.transportContracts[i].rateBasis ∈ {'tonneKm','m3Km','unitKm','perTrip','flatPeriodic'}`
- At cost-compute time: convert part qty to the contract's rate basis using
  the per-part conversion factors from B2
- Add per-contract minimum charge (e.g., FTL minimum 16 tonnes; under that
  goes to LTL contract)

### B4. FTL/LTL auto-pick + air fallback on disruption
**Why:** User said "I am not sure how I can define or predefine whether ftl
or ltl... emergency we have air mode option which has its own lead time."

**Spec:**
- Truck capacity field on transport mode (e.g., FTL truck = 16 tonnes / 80m³)
- Auto-pick logic in solver/dispatcher:
  - If `qty × volPerUnit < truck × 0.6` → LTL (or consolidate across parts in same lane)
  - Else FTL
- BOM part gets `defaultTransportMode` and `fallbackTransportMode`
- When `state.disruptions[]` matches a mode (e.g., supply-delay on road), the
  fallback mode kicks in. Surface in solver result: which lanes used fallback
  and at what cost premium.
- Fallback air mode rate: `airRateBand: {min, max}` on the BOM part —
  enter once, used when fallback triggers (no spot-market simulation per the
  parked decision).

### B5. Landed cost on BOM row
**Why:** User asked "Landed cost derivation goes where? etc., I think in bom
parameter is should define like this part is procured from this place via
this mode to our plant or warehouse."

**Spec:**
- BOM row gets a "Landed Cost" derived field: `unit_price + freight_per_unit
  + duty + insurance + handling`
- Each BOM part: `sourceLocationId, transportContractId, defaultMode,
  fallbackMode` (FK to network.nodes and transportContracts)
- Helper `landedCost(part, network, contracts, modes)` already partially
  exists — extend it to use the new FK fields and return a breakdown object
  (base, freight, duty, insurance, handling, total).
- Render landed cost as a chip on each BOM row, expandable to show breakdown
  (replace the current gear-icon "ordering breakdown" with this richer view).

### B6. Drop the gear-icon "breakdown elements" panel
**Why:** User said "Breakdown elements assume is for ordering cost if so
they have to be done better other than putting them in a settings icon and
making them unusable."

**Spec:**
- Remove the gear-icon trigger; the breakdown panel is always-on as an
  expand chevron on each BOM row
- Breakdown layout: ordering cost components (admin / receivingQC / setup /
  freightFixed) **+** landed cost breakdown from B5

### B7. Verification per Bucket 2
- Trace test: define part X (litres, 1.05 kg/L density), source from supplier
  S1 (Coimbatore), road FTL contract @ ₹2/tonne-km, distance 500km. Order
  qty 800L. Assert: landed cost = 800 × unit_price + ((800 × 1.05)/1000 × 500
  × 2) + duty + insurance + handling = base + ₹840 freight + …
- Babel parse pass

### B8. File anchors for Bucket 2 (post-R7 line numbers — re-grep before editing)
- Locations Master section: `grep -n 'Locations Master'` in Tab 1 (~line 2824 pre-R7)
- BOM editor: `grep -n 'function BOMEditor\\|ADD_BOM_ITEM\\|defaultBOM'` 
- Transport modes/contracts: `grep -n 'state.transportModes\\|state.transportContracts'`
- Existing `landedCost` helper: `grep -n 'function landedCost'`

---

## C. Bucket 3 — Solver / Forecasting / Horizon coherence (READY TO BUILD)

### C1. Horizon scoping correctness — end-of-horizon distortion fix
**Why:** User said "I may have chosen period from next 3 months then what
to do? Will po schedule and qty to order will be for that period alone
meaning 3 pos released 4th po to release covers only for remaining 2 days
of period?" Plus follow-up concern: tiny tail-end POs incur heavy fixed
ordering costs and destroy economics. This is the classic **end-of-horizon
distortion** problem.

**Discussion (captured 2026-05-08):**
Pure MILP with **fixed-charge formulation** (binary `y_t ∈ {0,1}` for "PO
placed?", continuous `x_t` for qty, linking `x_t ≤ M·y_t`, objective term
`+ S·y_t`) is **theoretically sufficient** for this tool's scale (one product
line, ~12 periods). Big orgs (SAP IBP / Kinaxis / o9) layer heuristics
(Wagner-Whitin / Silver-Meal / PPB) only because pure MILP becomes NP-hard
at 10k SKUs × 52 weeks × 3 suppliers ≈ 1.5M binaries — they decompose into
strategic (annual MILP) → tactical (monthly MILP) → operational (weekly
heuristic). Heuristics are also used as MILP warm-start or SLA-fallback.
For our tool: **MILP alone, no heuristic layer needed**.

**Spec — implement all four mechanisms (they're complementary):**

#### C1.a Effective horizon ≠ committed horizon (the cleanest fix)
- Solve over `T_effective = T_user + max(BOM.leadTime in periods) + EOQ_coverage_buffer`
- Only **commit / display / release** decisions inside `T_user`. Trailing buffer
  exists purely so the solver can "see" enough forward demand to make economical
  lot-size decisions — APICS calls this **frozen / slushy / liquid time fence**.
- In `runSolver('procurement')`: compute `procurementHorizon = T_user + ceil(max(LT)/periodDays) + ceil(EOQ_days/periodDays)`
- Render solver result chip: `Effective: N periods · Committed: M periods · Buffer: K`
- Demand array is extended into the buffer using forecast (NOT zero-padded — zero-pad causes its own distortion)

#### C1.b Terminal inventory anchor (kills the symptom directly)
- Add MILP constraint: `endingInv[T_user] ≥ safetyStock + (avgDailyDemand × replenishmentLT)`
- Without this, a cost-minimizing solver drives `endingInv → 0` which forces
  the tiny last-3-days PO to barely satisfy the final periods. Anchoring
  ending inventory at SS + LT-buffer means the solver must plan for continuity.
- Surface in solver result: `Terminal anchor: ₹X tied up at horizon end`

#### C1.c Setup cost properly modeled as fixed-charge in objective
- Confirm `state.bom[i].orderingCost` (the fixed-charge `S` per PO) appears in
  the MILP objective with a binary indicator: `+ S_i · y_{i,t}` for each part i,
  period t. Today we may have orderingCost folded into per-unit cost — that's
  the bug; tiny qty × linear cost = tiny cost, no friction against tiny POs.
- Verify by inspecting the procurement solver payload at the `runSolver` call site.
- Composite `S` (see C1.e below) bridges to Bucket 2.

#### C1.d Minimum-coverage gate (guard-rail, optional)
- Hard constraint: every PO must cover ≥ `max(MOQ, 0.5×EOQ, 14_days × avgDemand)`
- Implemented as `x_t ≥ COV_min · y_t` linked to the same binary.
- Use sparingly — over-tight values can suppress legitimate small replenishments
  for slow-movers. Default OFF; enable per-part via `state.bom[i].minCoverageDays`.

#### C1.e Composite, mode-dependent ordering cost (bridges to Bucket 2)
**Why:** User flagged "ordering costs tend to involve transportation etc."
That's exactly right. Real-world `S` = `admin_per_PO + inbound_freight +
inspection + customs/duties + receiving_labor`. The dominant chunk is
**inbound freight**, which is mode-dependent and step-function:
- **FTL** — fixed cost per truck regardless of fill (large POs amortize)
- **LTL** — rate per kg/m³ (linear, no bundling benefit)
- **Air** — high per-kg, no bundling benefit
- **Joint replenishment** — multiple SKUs share a truck (Bucket 2 territory)

Classical EOQ `√(2DS/h)` assumes constant `S` — wrong when truck-fill
break-even introduces step changes. Real procurement uses **mode-dependent S**:
the lot-sizer asks "wait 4 days and ship FTL, or ship LTL now?"

**Spec for C1.e:**
- BOM row gets `orderingCost` broken into components: `{adminPerPO, inspection, customsDutyPct, receivingLabor}`
- Freight contribution comes from Bucket 2's transport contract per chosen mode (FTL/LTL/air)
- Solver reads `S_effective(mode) = sum(components) + freightFor(mode, qty)` — a step function, not a constant
- This is the formal bridge between Bucket 2 (mode/contract) and Bucket 3 (lot-sizing).
  Implementing C1.e standalone (without B3/B4 contracts) means falling back to a flat freight estimate.

**Verification:**
- 12-period horizon, max LT = 30 days = 1 period → effective horizon = 13 + EOQ buffer
- Create part with high `S` (₹50k per PO) and small last-period demand (10 units, ₹2k value)
- Pre-fix: solver releases tiny PO at period 12 (loss = ₹48k)
- Post-fix: solver bundles last-period demand into period 11 PO OR delays to outside-committed-horizon (no PO released)

### C2. MTO + MTS hybrid per SKU
**Why:** User said "A product can have multiple orders types not just one
or the other, it may have 500 mto's for the period and other is if we may
have other modes of distribution."

**Spec:**
- `product.demandMode` becomes optional/legacy. Effective demand is now:
  `effDemand = mtoQty(period) + mtsForecast(period)` where MTO comes from
  `product.mtoOrders[]` and MTS from `product.history` + forecast.
- Solver payload sums both per period
- UI: split the demand mode card into "MTO Orderbook" (order list, sums by
  period) + "MTS Forecast" (existing forecast). Both contribute to MPS.

### C3. Lost-sales estimator (simple proxy, not Tobit)
**Why:** Per user choice (Tobit/censored regression deferred), we ship a
simple proxy.

**Spec:**
- Per period: if `actuals[t] < forecast[t]` AND `onHand[t] == 0` (stock-out),
  then `inferredLost[t] = forecast[t] - actuals[t]`
- Surface as a per-product chip "₹X.XL lost sales last 3mo (estimate)"
- Add to `productAnalytics` panel

### C4. Drift-detector-light retraining cadence
**Why:** User said "I dont think orgs wait a full whole year and then retrain
period wise."

**Spec:**
- Per SKU: `lastRetrained` ISO date + `retrainCadence` ('daily'|'weekly'|'monthly')
- A "Retrain Now" button on each product
- Drift indicator badge: compare last 4 weeks of actuals vs forecast residuals;
  if std-dev of recent residuals > 1.5 × historical std-dev → flag drift
- This is NOT real ML retraining — just a flag + button. Backend `/api/forecast/retrain` already accepts SKU id.

### C5. Demand-sensing header chip + sigma explainer
**Why:** User said "I dont see the demand sensing section in the UI anymore."
It exists at index.html:10943 (5-layer pattern recognition) but is buried.

**Spec:**
- App masthead chip: count of SKUs in breach (sigma-threshold violation
  in last N consecutive periods). Click → jump to Tab 9 Demand Sensing card.
- Inline explainer panel above the demand sensing table: "Why 2σ? Forecast
  residuals are assumed Gaussian with std-dev σ. |error| > 2σ has only
  ~5% probability under that assumption — repeated 2σ breaches mean the
  model is broken, not just unlucky. Action: blend sensed signal at α =
  state.planning.sensingAlpha (today: {value})."

### C6. Tab 3 daily/weekly/monthly drill-down
**Why:** User said "Don't like the separate daily, weekly, monthly tables
each being separately markedly cat you just make it like month clicking
on it opens sub category of exact weeks and clicking on weeks opens up on
exact bit of days according to calendar year and historic working days."

**Spec:**
- One unified period table. Default shows monthly buckets.
- Click month → row expands to weeks (using `state.planning.workDays`).
- Click week → row expands to working days only (skipping holidays from
  `state.planning.holidays`).
- Each level editable; downstream code reads aggregated value at the
  current grain.

### C7. Lifecycle curve scope clarification
**Why:** User said "Don't get what lifecycle curve tries to do placed here
when it says adjust statistical forecast before override, override is in
tab 2."

**Spec:**
- Move the Lifecycle Curve card from Tab 3 to a sub-section under "Forecast
  Pipeline" so the order is clear: history → statistical baseline → lifecycle
  multiplier → promo lift → override → consensus
- Add a flow diagram at the top of Tab 3: stages with arrows
- Disable lifecycle multiplier when an override exists for the same period
  (gate against double-application)

### C8. Solver result transparency
- After solve, render a "What did the solver do?" panel:
  - Procurement budget used / remaining
  - Working capital limit hit?
  - Logistics budget mode (hard/soft/unconstrained) and any over-spend
  - Periods past horizon used for procurement window extension (C1)
  - Disruptions active and which fallback modes triggered (B4)

### C9. File anchors for Bucket 3
- `function runSolver` (~12324 pre-R7, search after R7)
- Demand sensing: `grep -n 'sensingAlpha\\|/api/demand/sense'`
- MPS card: `grep -n 'function MPS\\|Master Production Schedule'`
- Forecast pipeline: `grep -n 'forecastModelCompetition\\|consensusForecast'`

---

## D. Bucket 4 — UX cleanup (READY TO BUILD)

### D1. BOM subpart inline-accordion editor
**Why:** User said "I dont even get to define each subpart of product A,
clicking on its name to render out a new detailed section feels stupid,
try another way." User selected **inline accordion** when shown the
options.

**Spec:**
- BOM table row: click chevron / part-name → row body expands inline
- Expanded body shows:
  - Source: supplier name + location (FK from B5)
  - UoM + storage cap (from B2)
  - Default + fallback transport mode (from B4)
  - Lead-time band (small/mid/large qty if Bucket 3 C1 horizon work happens too)
  - Landed cost breakdown (from B5)
  - Backup supplier toggle
  - Subcontract toggle
- Replace the current click-name-renders-fresh-section behavior

### D2. Inline Actuals column in MPS table
**Why:** User said "The actuals entry is an editable input column that lives
integrated in mps visualisation table."

**Spec:**
- Today: separate Actuals Entry card (~index.html:5350)
- Move actuals into the MPS table itself as an editable column per period
- Remove the separate card

### D3. Consolidate MTO order entry
**Why:** User said "A separate mto order enter section meaningless placed
elsewhere here."

**Spec:**
- Today: MTO Orders card lives at index.html:4643
- Move it into the per-product detail panel adjacent to product parameters

### D4. Promote ordering-cost breakdown out of gear icon
- Same fix as B6 above (Bucket 2 has it). If Bucket 4 ships before B2, do
  it minimally now: replace gear icon with always-on chevron.

### D5. File anchors for Bucket 4
- BOM editor: `grep -n 'BOM[^A-Za-z]\\|defaultBOM\\|UPDATE_BOM_ITEM'`
- MPS: `grep -n 'Master Production Schedule\\|function MPSCard'`
- MTO Orders card: `grep -n 'mtoOrders\\|MTO Order'`

---

## E. Parked indefinitely

### E1. ML weather/exogenous-feature forecasting
**Why parked:** User selected "Park ML weather/exogenous forecasting" when
asked. This is a multi-week build (Prophet/LightGBM + per-cluster training
+ weather/festival/promo feature engineering + rolling-origin CV +
drift-triggered incremental retrain).

**If unparked later:** see plan section A6 of the original plan file at
`/home/codespace/.claude/plans/stateful-greeting-lynx.md`.

### E2. Lost-sales censored-demand (Tobit)
**Why partially parked:** Bucket 3 C3 ships a simple proxy. The full Tobit
regression is parked.

### E3. Air-fallback spot-market pricing
**Why parked:** Bucket 2 B4 uses a user-entered air rate band (min/max),
not a real spot-market simulation. Full simulation is parked.

### E4. Drift-detector retraining (true detector)
**Why partially parked:** Bucket 3 C4 ships a flag + manual button. Real
auto-trigger drift detection is parked.

---

## F. Carryover from prior rounds

### F1. Round 6 commit `eb295f1`
- Title: "Round 6 — MEIO in-transit inventory + fix orphaned r/o/rm_inv declarations"
- Status: **committed but not pushed**
- Decision (when ready): push with R7 commit, or push separately
- The user has not given push authorization yet for either round

### F2. Earlier round deferrals (still open)
- Webhook ingest for disruptions
- Screenshot-blocked items (`#3 tooltip review`, `B3 incoterm review`)
  — these were noted in earlier rounds but never fully closed; recheck
  the audit log

---

## G. How to resume

1. After `/compact`, the conversation summary will tell you Round 7 shipped
   with these features (it should preserve top-line). Read this file fully.
2. To start Bucket 2: re-grep all line anchors in section B8 (post-R7 lines
   shifted). Begin with B1 (inbound/outbound classification) — lowest-risk.
3. To start Bucket 3: begin with C5 (header chip + sigma explainer) — pure
   UI add, no algorithm risk.
4. To start Bucket 4: begin with D1 (BOM accordion) — confirmed UX choice.
5. Always run Babel parse + smoke tests after each round. Pattern in R7
   handoff section A10.
6. Always update this file with a new section "Round N — what shipped" after
   each round.

---

*Round 7 completed 2026-05-08. File: index.html (single file SPA, ~14,500 lines post-R7). All 6 helper unit tests passed. Babel parse on 1.16MB main script: ✓.*
