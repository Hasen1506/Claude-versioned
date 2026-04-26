# ARCHITECTURE.md

> **Status:** v1 — design mandate for the 8-pillar refactor. This document is *prescriptive*, not descriptive: it defines the target architecture that subsequent UI and solver changes must conform to. No isolated patches. No hardcoded data. Every fix propagates across front-end **and** relevant solver.

---

## 0. Governing principles

1. **Single source of truth per domain.** One state key, one read path, one write path. If the same quantity appears in two places with two values, one of them is a bug.
2. **State → view, never view → view.** UI reads from `state`; UI never computes a value that another UI node will re-compute independently. Derived values live in selectors, not in component bodies that are peers of other component bodies.
3. **Cascades are explicit.** When a config input changes, every downstream solver payload and every downstream display must recompute. No "this section is stale, refresh" semantics.
4. **Solver payloads are pure functions of state.** The `runSolver(...)` call sites in [index.html:2435-2558](index.html#L2435-L2558) are contracts. If a field is in state, it must be in the payload.
5. **No placeholders, no hardcoded demo data in production paths.** A function that fabricates randomness in place of `state.*` is a defect.

---

## 1. Currency registry

### Current state (problem)

- Symbol is stored at `state.config.currency` ([index.html:785](index.html#L785), [index.html:819](index.html#L819)).
- Dozens of sites read it correctly via `const cur=state.config.currency` (e.g. [1405](index.html#L1405), [1495](index.html#L1495), [1615](index.html#L1615), [2378](index.html#L2378), [3497](index.html#L3497), [3917](index.html#L3917), [4374](index.html#L4374), [4903](index.html#L4903), [5327](index.html#L5327), [5628](index.html#L5628), [5717](index.html#L5717), [5978](index.html#L5978), [6046](index.html#L6046), [6225](index.html#L6225)).
- But many sites **hardcode `₹`** in labels, tooltips, freight tables, the landed-cost scratchpad, and KPI strings — e.g. freight rate table [index.html:3568](index.html#L3568), import landed-cost breakdown [index.html:3744](index.html#L3744), Landed-cost scratchpad KPIs [index.html:3841-3860](index.html#L3841-L3860), FX hedging copy [index.html:5030](index.html#L5030), Asset Register energy hint [index.html:4019](index.html#L4019), freight transport mode table [index.html:3568](index.html#L3568).
- `state.config.currencyRate` and `currencyName` exist but are unused.

### Target architecture

**One registry. One hook. Zero hardcoded symbols anywhere in JSX string literals.**

```
state.config.currency      = '₹' | '$' | '€' | ...    // symbol used in rendering
state.config.currencyCode  = 'INR' | 'USD' | 'EUR'    // ISO-4217 code; drives locale formatting
state.config.currencyRate  = number (units of currency per 1 INR base)  // optional FX anchor
```

**Selector contract** — a single helper `useCurrency()` (or top-level `const cur = state.config.currency`) must be the only surface. Any `₹` seen in a string literal outside of:

- `Enterprise_Simulator_v3_Master_Plan.md` (reference doc)
- `ARCHITECTURE.md` (this doc)
- Educational copy that names the rupee explicitly as the subject ("IGST of 18%" *without* the symbol is fine; "+₹5,000 CHA" is not)

…is a defect.

**Formatters** — introduce two utilities co-located near `zVal`/`landedCost` at the top of the `<script type="text/babel">` block:

```js
const fmtCur = (v, c) => `${c}${(+v||0).toLocaleString(undefined,{maximumFractionDigits:2})}`;
const fmtCurK = (v, c) => `${c}${Math.round((+v||0)/1000).toLocaleString()}k`;
```

Every tooltip, KPI, and table cell that currently interpolates `₹` inline switches to `fmtCur(v, cur)`.

**Freight/tax reference tables** — the transport-mode reference ([index.html:3568](index.html#L3568)) and landed-cost scratchpad ([index.html:3826+](index.html#L3826)) embed `₹/t·km` as part of the unit string. These are **units of account**, not currency amounts. Separate concerns: the *rate* is a number in `state.config.currency`-per-tonne-km; the string `₹/t·km` must become `${cur}/t·km`.

**Change propagation** — because all read sites resolve `state.config.currency` at render time, a single `SET_CONFIG` dispatch re-renders everything. No explicit subscription needed — React's `useReducer` delivers this for free. The audit fix *is* the architecture: delete every hardcoded symbol.

**Acceptance test** — `grep -nF '₹' index.html | grep -v '// '` returns zero lines inside JSX.

---

## 2. Planning horizon cascade

### Current state (problem)

- Editable horizon input exists at [index.html:1166](index.html#L1166) (`horizonLength` + `horizonUnit`). Yet `state.planning.periods` (hardcoded 52 at [791](index.html#L791), [829](index.html#L829)) is what every solver payload reads ([2435](index.html#L2435), [2451](index.html#L2451), [2488](index.html#L2488), [2514](index.html#L2514), [2535](index.html#L2535), [2538](index.html#L2538), [2543](index.html#L2543), [2552](index.html#L2552), [2558](index.html#L2558), [6287](index.html#L6287), [6299](index.html#L6299)). `horizonLength` is written but **never consumed**. That is why "horizon is not editable" *in effect* even though the input exists.
- `startMonth` (line [1167](index.html#L1167)) and `horizonStartDate` (line [1174](index.html#L1174)) both exist — redundant, confusing, only `horizonStartDate` is passed to the scheduler.
- No validation that `frozenWeeks ≤ slushyWeeks ≤ horizonLength`. State allows frozen=40, slushy=8, horizon=5 today.
- `state.planning.timeGrain` is cascaded to the production scheduler ([2451](index.html#L2451)) but **not** to the procurement solver ([2435](index.html#L2435), [6287](index.html#L6287)) — procurement always runs weekly.
- MPS Viz ([index.html:5309](index.html#L5309)) generates 52-week synthetic data regardless of configured horizon.
- Procurement solver ([procurement.py:37](procurement.py#L37)) accepts `periods` and `service_level` but has no `time_grain` param.

### Target architecture

**Single horizon contract**

```
state.planning = {
  horizonLength: number,        // integer ≥ 1
  horizonUnit:   'days'|'weeks'|'months',
  horizonStartDate: ISO-date,   // required; defaults to today on first mount
  timeGrain: 'daily'|'weekly'|'monthly',
  frozenWeeks: number,          // normalized to periods via periodCount()
  slushyWeeks: number,
  // REMOVED: startMonth, periods (legacy)
}
```

**Derived selector** — `periodCount(planning)` returns the integer period count used by every solver:

```js
const periodCount = pl => {
  const len = +pl.horizonLength || 52;
  const unit = pl.horizonUnit || 'weeks';
  const grain = pl.timeGrain || 'weekly';
  const days = unit==='days'?len:unit==='weeks'?len*7:len*30;
  return grain==='daily'?days:grain==='weekly'?Math.ceil(days/7):Math.ceil(days/30);
};
```

This function is the **only** place `periods` is computed. Every solver payload replaces `state.planning.periods` with `periodCount(state.planning)`.

**Validation rule** — reducer case `SET_PLANNING` must enforce:

```
0 ≤ frozenWeeks ≤ slushyWeeks ≤ periodCount(state.planning)   (normalized to same grain)
```

On violation: keep prior value, surface error via `state.ui.errors.planning` banner. Rule shown inline: *"Planning ≥ Slushy ≥ Frozen. Reduce slushy to ≤ planning (N) to save."*

**Start-date anchor** — delete the `Start Month` dropdown at [index.html:1167](index.html#L1167). `horizonStartDate` is the only anchor. Place it immediately under `Planning Horizon`. Initial value = `new Date().toISOString().slice(0,10)`.

**MPS window binding** — `MPSVizCard` ([index.html:5309](index.html#L5309)) must generate exactly `periodCount(state.planning)` buckets starting at `horizonStartDate`, labelled by grain. No `52` literals; no synthetic-random data generation — see Pillar 7 for demand source.

**Time-grain cascade to procurement solver**

Front-end: add `time_grain: state.planning.timeGrain` and `horizon_start_date: state.planning.horizonStartDate` to every procurement call site — at minimum [2435](index.html#L2435), [6287](index.html#L6287), [6299](index.html#L6299). Also the `wh_max` and `shared_capacity` scaling must adapt to grain (capacity per *period*, not per week).

Back-end: `solve_procurement` in [procurement.py:24](procurement.py#L24) accepts `time_grain` and scales:
- carry cost per period = `carry_rate * {1/365 if daily, 1/52 if weekly, 1/12 if monthly}`
- lead-time and `rmShelf` convert from days/weeks to periods via `ceil(lt_native / grain_factor)`
- holiday exclusion (Pillar 6) strikes holiday periods from the production calendar before building decision variables.

**Legacy `periods` field** — remove from `defaultState` at [791](index.html#L791) and [829](index.html#L829). During the migration, `SET_PLANNING` silently re-derives it from `periodCount` for any dead read that still references `state.planning.periods`; then those reads get deleted in the same PR that lands the migration.

---

## 3. GST / landed-cost architecture

### Current state (problem)

- `state.config.gstRegistered` boolean exists ([1153](index.html#L1153)); `gstin` exists but is unused by any calculation.
- Each BOM part carries `supplierType` ('domestic' | 'import'), `country`, `incoterm`, `hsCode` ([771](index.html#L771), [917](index.html#L917)) — good.
- Landed-cost breakdown **inside the BOM row** at [index.html:1993-2026](index.html#L1993-L2026) computes `cost + freight·(1+fuel%) + cost·insurance% + (cost+freight)·duty% + handling`. **Does not branch on domestic vs import. Does not apply GST at all.**
- Separate **Landed Cost scratchpad** at [index.html:3499-3860](index.html#L3499-L3860) (isolated section, not inside transport design). Calls `/api/calc/landed-cost` with hardcoded GST fields. Duplicates the BOM-inline calculation.
- `landedCost(b)` helper ([index.html:698](index.html#L698)) is invoked by solver payloads ([2483](index.html#L2483), [2500](index.html#L2500)) — *this is the only path that reaches the solver*. Scratchpad values never leave their local state.
- **Non-registered IGST is not flowed into landed cost** anywhere. The `c.gstRegistered` flag only toggles a tooltip at [1153](index.html#L1153).
- No SGST/CGST path for domestic intrastate. No interstate/import IGST branching. No intra- vs inter-state detection (no supplier state, no plant state).
- Outbound plant → DC cost is not captured at all. No field for it.

### Target architecture

**The BOM row is the single source of landed cost.** The scratchpad at [3499-3860](index.html#L3499-L3860) becomes a *learning / worked-example panel* inside the transport design section — read-only math exposition, not an editable parallel universe. Its form state is deleted. Its UI reads the selected BOM part and displays the breakdown using the same `landedCost()` helper.

**Part-level fields** (extend the existing BOM schema — no new `state.transport` root):

```
bom.item = {
  ...existing fields,
  supplierType: 'domestic' | 'import',
  supplierState: 'TN' | 'MH' | ... ,   // required if domestic; drives intra vs interstate
  country: ISO country                   // required if import
  incoterm: 'EXW'|'FCA'|'FAS'|'FOB'|'CFR'|'CIF'|'CPT'|'CIP'|'DAP'|'DPU'|'DDP',
  transMode: 'road'|'rail'|'sea'|'air'|'courier',
  contractType: 'spot'|'rate-contract'|'annual',
  // Incoterm-conditional inputs (see "Conditional fields" below)
  freight: number,           // from seller if CFR/CIF/CPT/CIP/DAP/DPU/DDP, else buyer
  insurance: number,         // shown only when CIF / CIP
  bcdPct: number,            // shown only for import
  swsPct: number,            // shown only for import (default 10% of BCD)
  igstPct: number,           // 18 default
  gstPct: number,            // shown only for domestic; default 18
  handling: number,
}

plant.state: 'TN' | 'MH' | ...  // new top-level state.plant field, mirror of existing outbound plant
```

**Tax branching (definitive)**

```
if supplierType === 'import':
    landed = CIF + BCD + SWS(on BCD) + IGST(on CIF+BCD+SWS) + CHA + port + localTransport
    if gstRegistered:  igst_effective = 0         // recovered via ITC
    else:              igst_effective = full      // sunk into landed cost

elif supplierType === 'domestic':
    intrastate = (bom.supplierState === state.plant.state)
    if intrastate:
        tax = cost * (CGST + SGST)/100            // usually 9+9 = 18
    else:
        tax = cost * IGST/100                      // usually 18
    if gstRegistered:  tax_effective = 0          // full ITC
    else:              tax_effective = tax
    landed = cost + freight·(1+fuel%) + insurance + tax_effective + handling
```

**Conditional Incoterm fields** — the BOM row renders input fields based on Incoterm, not all-at-once:

| Incoterm    | Buyer pays (fields shown)                                       | Seller pays (fields hidden)        |
|-------------|-----------------------------------------------------------------|-------------------------------------|
| EXW         | freight, insurance, duty, CHA, port, local                      | none                                |
| FOB / FCA   | freight, insurance, duty, CHA, port, local                      | origin-port handling                |
| CFR / CPT   | insurance, duty, CHA, port, local                               | freight                             |
| **CIF / CIP** | duty, CHA, port, local                                        | freight + insurance                 |
| DAP / DPU   | duty                                                            | everything else                     |
| DDP         | none                                                            | everything incl. duty               |

Implementation: a small `incotermFields(ic)` selector returns the set of visible input keys; the BOM row reads it and conditionally renders `<Field>` elements.

**Inbound transport definition wizard** (new UX — lives in the Transport tab, not Products):

```
Step 1: pick product
Step 2: pick BOM subpart
Step 3: pick supplier — name + location (state/country) — pulled from existing part.backupSuppliers
Step 4: pick mode → auto-suggest Incoterms (sea → CIF/FOB; air → CIP/FCA; road → CPT/DAP)
Step 5: pick contract type
Step 6: fill Incoterm-conditional fields
```

Each step writes back into the same `bom.item` record — no parallel `state.transport.inbound[]` store.

**Inbound network topology view** — a new visualization in the Transport tab, mirroring the outbound topology. Renders one node per distinct `(supplier, country|state)`, one edge per `(supplier → plant)` weighted by annual inbound volume (`weeklyDemand(p) * qtyPer * 52`). Uses the same SVG renderer that outbound uses today.

**Outbound plant → DC cost** — *not* an optimization variable; it is an allocation cost after the primary production plan is fixed. Recommendation: leave it out of the procurement and production MILPs (do not add as a new constraint). Compute it as a post-solve **display** on the outbound network view using existing `transMode` rates. If the user wants it to influence solving, the right place is the distribution MILP (separate solver), not an extra term in procurement's objective. **Architectural decision: do not add `plant_to_dc_cost` as a solver parameter.**

**Dedup** — delete these duplicates:
- The scratchpad form state at [index.html:3499](index.html#L3499) (`lcForm`, `lcResult`) — converted to read-only exposition as described above.
- The freight rate reference table at [index.html:3568](index.html#L3568) is kept (reference) but its rates are moved into a `TRANSPORT_RATES` constant at module scope; any BOM part that doesn't override uses it.

**Solver flow** — `landedCost(b)` (helper at [index.html:698](index.html#L698)) is updated to apply the tax branching above. Procurement payloads ([2483](index.html#L2483), [2500](index.html#L2500)) continue to read `landed_cost: landedCost(b)`. No new solver plumbing required — the helper is the single contract.

---

## 4. Zero-prefix input fields

### Current state (problem)

Every `<input type="number" value={someNumber}/>` in the codebase (184 matches) shows `0` when the bound value is `0`, and when the user types a digit the cursor behavior depends on browser default: Chrome keeps the leading `0` (giving `05` interpreted as `5`) but visually the user sees `0`-prefix garbage. This affects **Effective Tax Rate, WACC, Service Level, solver budgets, Q/OTD/Rel scores, landed-cost components, everything.**

Service Level is editable at [index.html:1157](index.html#L1157) but the user reports it as "not editable" — almost certainly because the 0-prefix UX makes it appear so when the underlying value is defaulted and typing prepends rather than replaces.

### Target architecture

**One component. One behavior. App-wide substitution.**

```jsx
function NumInput({value, onChange, min, max, step=1, placeholder, style, ...rest}){
  const [local, setLocal] = React.useState(String(value ?? ''));
  React.useEffect(()=>{ setLocal(String(value ?? '')); }, [value]);
  return <input
    type="number" inputMode="decimal" step={step} min={min} max={max}
    value={local}
    placeholder={placeholder ?? (value===0 || value==null ? '0' : '')}
    style={style}
    onFocus={e=>{ if(local==='0') setLocal(''); e.target.select(); }}
    onChange={e=>{ const v=e.target.value; setLocal(v); if(v==='' || v==='-') return; const n=+v; if(!isNaN(n)) onChange(n); }}
    onBlur={()=>{ if(local===''||local==='-') { setLocal('0'); onChange(0); } }}
    {...rest}
  />;
}
```

Behavior guarantees:
1. Displays `0` as placeholder (grey), not as value → typing replaces.
2. On focus: if the local string is literally `'0'`, clear it and select-all. Otherwise select-all (standard spreadsheet ergonomic).
3. On blur with empty string: coerce to `0` so downstream math never sees `NaN`.
4. Negative entry allowed if `min` is unset.
5. Controlled value still tracks parent state via `useEffect`.

**Rollout** — a sed-style codemod replaces every `<input type="number" value={X} onChange={e=>...(+e.target.value)}/>` with `<NumInput value={X} onChange={v=>...(v)}/>`. The 184 hit sites get one commit per logical section; each section verified visually before merging.

Acceptance test: typing in any numeric field with current value 0 yields exactly the typed digits (no leading 0).

---

## 5. Service level cascade

### Current state

- Editable at [index.html:1157](index.html#L1157) with continuous `zVal` lookup.
- Cascades to every solver payload that carries `service_level` ([2435](index.html#L2435), [2514](index.html#L2514), [2538](index.html#L2538), [2558](index.html#L2558), [4393](index.html#L4393), [6287](index.html#L6287), [6299](index.html#L6299)) — good.
- **Solver-side**, however, [procurement.py:37-45](procurement.py#L37-L45) buckets service level to a 4-value lookup `{0.85, 0.90, 0.95, 0.99}`. Any continuous UI input between those rounds down. A user setting 0.97 effectively gets 0.95 in the solve. That is why the front-end cascade looks broken from the outside.
- UI-side safety-stock displays ([index.html:5629](index.html#L5629), [6055](index.html#L6055), [6227](index.html#L6227)) use the **same** 4-value bucket table — so what the user sees for SS matches what the solver used, but neither reflects the continuous z.

### Target architecture

**Continuous z everywhere.** Both front-end and back-end use the inverse-standard-normal CDF.

Front-end: the `zVal()` helper already exists (used at [index.html:1157](index.html#L1157) tooltip). Apply it at the 3 safety-stock display sites above, replacing the 4-value bucket.

Back-end: `solve_procurement` computes z via `statistics.NormalDist().inv_cdf(service_level)` (Python 3.8+) or a stock erfinv approximation — no table. Pillar 5 change is a one-line patch in [procurement.py](procurement.py) plus the three display patches.

**Plus Pillar 4 fix** — once Service Level goes through `NumInput`, the "can't edit" report disappears. Pillar 5's own work is verifying the solver math matches.

---

## 6. Gazetted holidays

### Current state

- A single yes/no toggle at [index.html:1169](index.html#L1169) (`state.planning.indianHolidays`).
- No date list. No locale gate. "22 Indian national/state holidays" is a magic constant referenced in the tooltip [index.html:1169](index.html#L1169) and working-calendar display [index.html:1183](index.html#L1183) (`holDays` computed as a fixed 11 days for TN gazetted).
- MPS ([index.html:5309](index.html#L5309)) does not consult holidays. Procurement solver has no holiday param. Scheduler has no holiday param.
- Visible on every profile regardless of locale.

### Target architecture

**Explicit locale + date list.**

```
state.config.locale = 'IN' | 'US' | 'EU' | 'CUSTOM'   // explicit, not inferred from currency
state.planning.holidays = [
  { date: '2026-01-26', name: 'Republic Day' },
  { date: '2026-08-15', name: 'Independence Day' },
  ...
]
```

- Replace the toggle at [index.html:1169](index.html#L1169) with a **date-list editor**, visible only when `state.config.locale === 'IN'` (or 'CUSTOM').
- Pre-seed `holidays` from a `HOLIDAYS_IN_2026` constant (22 entries) on profile init.
- Auto-detect locale default: `₹` currency symbol + `gstRegistered` field implies 'IN', but the UI shows the selector and lets the user override.

**Exclusion cascade**

- **MPS viz** ([index.html:5309](index.html#L5309)) — when building the period axis, skip any date in `state.planning.holidays`. Under weekly grain, a week containing a holiday shrinks to `(workDays - holidaysInThatWeek)/workDays` capacity; under daily grain the day is dropped entirely.
- **Production scheduler** ([index.html:2451](index.html#L2451), payload build) — pass `holidays: state.planning.holidays.map(h => h.date)` to the backend.
- **Procurement solver** — receives the same `holidays` list. The solver's `hrs_per_period` calc ([procurement.py] lot_sizing.py params) scales per period by `(workingDaysInPeriod - holidaysInPeriod) / workingDaysInPeriod`. Working calendar display [index.html:1183](index.html#L1183) reads from the same list (length of `holidays` array, not a magic 11).
- **S&OP release-date generator** — if we ship a release-date grid for POs (currently `weekly_demand` array of integers), snap any release week whose reference date is a holiday forward to the next working day.

**Single source of truth**: `state.planning.holidays` is consulted by every downstream. No parallel "TN gazetted" constant.

---

## 7. Demand plan — single source

### Current state (problem)

Three competing sources:

- `weeklyDemand(p)` defined at [index.html:2407](index.html#L2407) — splits monthly history as 27/27/23/23% across 4 weeks. Used by all top-level procurement/production/montecarlo payloads ([2429](index.html#L2429), [2513](index.html#L2513), [2535](index.html#L2535), [2552](index.html#L2552)).
- **Second, different `weeklyDemand(p)` defined at [index.html:6238](index.html#L6238)** — uses `Math.round(m/4)` for 3 weeks and a remainder — a *different algorithm* — and feeds a *different* procurement payload at [6287](index.html#L6287), [6299](index.html#L6299).
- MPS Viz ([5309](index.html#L5309)) generates its own synthetic/random series.
- S&OP gap analysis section ([4736](index.html#L4736)) and its section-15 recommendations ([6193](index.html#L6193)) read yet another set of fabricated values.

These are guaranteed to disagree and the user correctly identifies this as a major defect.

### Target architecture

**One selector. One store. Every consumer reads it.**

```
state.demandPlan = {
  // ground truth: user-editable monthly history
  history: { [productId]: number[] }   // existing: state.products[i].history
  // per-period disaggregated demand, derived not stored
  byPeriod(productId, planning) -> number[]
}
```

**Single canonical helper**, defined once near the top of the `<script type="text/babel">` block:

```js
function demandByPeriod(product, planning){
  const hist = product.history || [];
  const N = periodCount(planning);
  const grain = planning.timeGrain || 'weekly';
  if (grain === 'monthly') return hist.slice(-N);
  if (grain === 'weekly')  return hist.slice(-Math.ceil(N/4)).flatMap(m => {
    const w1=Math.round(m*0.27), w2=Math.round(m*0.27), w3=Math.round(m*0.23);
    return [w1, w2, w3, m - w1 - w2 - w3];
  }).slice(0, N);
  if (grain === 'daily')   return hist.slice(-Math.ceil(N/30)).flatMap(m => {
    const d=Math.floor(m/30), r=m-30*d;
    return Array.from({length:30}, (_,i) => i<r ? d+1 : d);
  }).slice(0, N);
}
```

**Rollout**:

1. Delete the duplicate `weeklyDemand` at [index.html:6238](index.html#L6238). Replace with `const weeklyDemand = p => demandByPeriod(p, state.planning);`.
2. Keep the one at [index.html:2407](index.html#L2407), rewrite to call `demandByPeriod`.
3. MPS Viz ([5309](index.html#L5309)) consumes `state.products.map(p => demandByPeriod(p, state.planning))` — no random synthesis.
4. S&OP Gap Analysis ([4736](index.html#L4736), [6193](index.html#L6193)) compares `demandByPeriod(p, state.planning)` against the fulfilled plan from the last solver run.

All three sections now report the same numbers. Changing a product's `history` propagates to every display.

---

## 8. State persistence & auto-restore

### Current state (problem)

- `skin` is persisted to `localStorage` ([index.html:822](index.html#L822), [892](index.html#L892)).
- A manual "Download full_state_backup.json" button at [index.html:4867](index.html#L4867). No auto-restore; no upload.
- On page refresh, the user loses everything except the chosen theme.

### Target architecture

**Auto-save + auto-restore via localStorage, with schema versioning for forward migration.**

```
localStorage key: 'esim.state.v1'
localStorage key: 'esim.schemaVersion' → '1'
```

**Persistence hook**:

```js
React.useEffect(() => {
  const tid = setTimeout(() => {
    try {
      localStorage.setItem('esim.state.v1', JSON.stringify(state));
      localStorage.setItem('esim.schemaVersion', CURRENT_SCHEMA);
    } catch(e) { /* quota-exceeded: fall back to IndexedDB, see below */ }
  }, 500);  // debounce 500ms
  return () => clearTimeout(tid);
}, [state]);
```

**Hydration** happens once at `useReducer` init:

```js
const [state, dispatch] = React.useReducer(reducer, undefined, () => {
  try {
    const v = localStorage.getItem('esim.schemaVersion');
    const raw = localStorage.getItem('esim.state.v1');
    if (!raw) return defaultState;
    const loaded = JSON.parse(raw);
    return migrate(loaded, v);   // see below
  } catch(e) { return defaultState; }
});
```

**Schema migration** — a pure function `migrate(state, fromVersion) -> stateInCurrentSchema`. Each breaking change adds a step. E.g. when Pillar 2 lands and `periods` is removed, the migration for `v0→v1` maps:

```js
if (v === '0') {
  s.planning.horizonLength = s.planning.horizonLength || s.planning.periods || 52;
  s.planning.horizonUnit = s.planning.horizonUnit || 'weeks';
  delete s.planning.periods;
  delete s.planning.startMonth;
}
```

**Quota safety** — state JSON for realistic scenarios (10 products × 24-month history × solver results) is < 200 KB; localStorage's 5-10 MB budget covers it. Nonetheless, wrap all `setItem` in try/catch; on failure, degrade to a **session-scoped in-memory cache** with a `⚠ Changes not persisted` banner so the user knows.

**Solver outputs** — keep the `solverResults` substate inside persisted state, but clear on a new solve of the same key. Do not persist blob responses > 500 KB (i.e. large MILP solutions); keep only the summary. The last solve per solver type is retained.

**Export/import** — the existing "Download full state" button at [index.html:4867](index.html#L4867) stays (for cross-browser transfer, pre-demo resets), and a new **"Restore from file"** companion reads a JSON and dispatches a single `{type:'HYDRATE', payload:state}` action.

**Reset** — a new "Reset to default" button clears `localStorage` keys and reloads. Guarded by a `confirm()` to avoid fat-finger data loss.

**Why not a backend store?** For this app's current scope (single-user, desktop), localStorage is the lowest-friction solution and requires no auth/session architecture. If/when multi-user collaboration is in scope, the right move is adding a backend `/api/state/{userId}` endpoint that this same persistence hook also calls (debounced) alongside localStorage — the hook becomes the single write point, backend becomes a second destination. **Do not** introduce backend persistence in this refactor pass.

---

## Cross-pillar dependencies

- **Pillar 2 must land before Pillar 6 and Pillar 7** — holiday exclusion and demand disaggregation both depend on `periodCount(planning)` being the canonical period source.
- **Pillar 4 (NumInput) must land first among UI fixes** — every other pillar surfaces through number inputs; fixing them independently and then re-writing them is wasted work. Land NumInput, then sweep.
- **Pillar 3 (GST / landed cost) must extend the existing `landedCost()` helper** at [index.html:698](index.html#L698) — that helper is already on the solver path, so the tax branching lands in solvers for free once the helper is updated.
- **Pillar 8 (persistence) should land last** — schema migration needs stable schemas to migrate from; if we persist early, we will be writing migrations against churning shapes.

## Order of work (prescriptive)

1. **Pillar 4** — NumInput + sweep. (No behavior change, sets up everything else.)
2. **Pillar 1** — currency registry cleanup. (Pure find-and-replace; builds trust in the new invariants.)
3. **Pillar 2** — horizon cascade. (Deepest state-shape change; unlocks 6 and 7.)
4. **Pillar 6** — holidays cascade. (Depends on 2.)
5. **Pillar 7** — demand-plan unification. (Depends on 2.)
6. **Pillar 5** — service-level continuous z in solver. (Independent; small.)
7. **Pillar 3** — GST / landed cost / Incoterm / inbound topology. (Largest UX surface.)
8. **Pillar 8** — persistence + migration. (Last, after shape stabilizes.)

## Non-goals

- We do **not** introduce a new state management library (Redux, Zustand). `useReducer` suffices.
- We do **not** split `index.html` into modules in this pass. The JSX-in-HTML approach is load-bearing for the zero-build demo posture; splitting is a separate refactor.
- We do **not** add a backend store in this pass (see Pillar 8 rationale).
- We do **not** add plant→DC cost as a solver variable (see Pillar 3 architectural decision).

---

*Sign-off required on this document before any of the 8 pillars is implemented. Every PR that lands must cite the pillar it closes and show the grep-level acceptance test passing (e.g. for Pillar 1: `grep -nF '₹' index.html | grep -v '//'` returns zero JSX-string matches).*

---

# ROUND 2 — Pillars 9–15 (Finance, Production, MILP, Working Capital)

> **Status**: appended after Round 1 (pillars 1–8) landed and validated. Same rules apply: prescriptive not descriptive; every pillar extends a single helper or registry, no parallel implementations. Round 1 helpers (`periodCount`, `demandByPeriod`, `landedCost`, `NumInput`, `zVal`, `migrateState`) are contracts other pillars consume — do not bypass.

## 9. WACC — redesign as a registry

### Current state (problem)

- WACC lives in two unrelated surfaces.
  - Simple field `config.wacc` at [index.html:1292](index.html#L1292) (Company Profile, a single number 11.5).
  - "Master Budget & Capital Structure" section at [index.html:4219+](index.html#L4219) (Finance tab) with `state.finance = {equity, debt, costOfEquity, costOfDebt, interestRate, reserve}` and a full WACC computation.
  - Scratchpad at [index.html:4110](index.html#L4110): `waccForm = {equity_pct, debt_pct, cost_equity, cost_debt, tax_rate}` + `calcWACC` fetch to `/api/calc/wacc`. **Fetch's `catch(e){}` silently swallows offline-backend errors, so the button "does nothing" visually.**
  - [finance.py:208](finance.py#L208) `calc_wacc` exists and is correct.
- Buy-vs-Lease form at [index.html:4112](index.html#L4112) has its own `wacc:10` hardcoded in `bvl` local state. Seed is 10, overridden only when user clicks "Apply to Buy-vs-Lease".
- Capital-budget solver call at [index.html:2692](index.html#L2692) reads `state.config.wacc/100` directly (correct).
- No multi-debt-instrument model. No inflation adjustment. No explicit "Calculate" action that writes the computed WACC back to `config.wacc`.

### Target architecture

**Single WACC registry** at `state.config.wacc` (number, percent, e.g. `11.5`). All downstream reads go through this. Nothing hardcodes 10. The registry is **derived-and-persisted** — user can override the derivation, but when they edit the capital-structure inputs the derivation recomputes and writes back.

```
state.finance = {
  masterBudget: number,             // total ₹ Round 2 Pillar 10
  equityPct:   number,              // 0–100
  debtPct:     number,              // 0–100 (equityPct + debtPct === 100 enforced)
  costOfEquity: number,             // Ke %
  costOfDebt:   number,             // Kd % (pre-tax, simple mode)
  debtInstruments: [                // complex mode — list of instruments
    { id, kind: 'bank-loan'|'bond'|'nc-debenture'|'wc-line', principal, ratePct, tenorYears, notes }
  ],
  mode: 'simple' | 'complex',       // which debt model is authoritative
  inflationAdjust: boolean,
  inflationPct: number,             // monthly inflation rate, manual or API-seeded
  inflationSeries: number[]         // optional: 12-month sequence for erosion curve
}
```

**Derived WACC** — a single pure selector:

```js
function computeWACC(finance, config) {
  const wE = (finance.equityPct||0) / 100;
  const wD = (finance.debtPct||0) / 100;
  const ke = (finance.costOfEquity||0) / 100;
  const kd = finance.mode === 'complex' && finance.debtInstruments?.length
    ? weightedAvg(finance.debtInstruments, i => i.ratePct, i => i.principal) / 100
    : (finance.costOfDebt||0) / 100;
  const t  = (config.taxRate||0) / 100;
  const nominalWACC = wE*ke + wD*kd*(1-t);
  if (!finance.inflationAdjust) return nominalWACC * 100;
  const infl = (finance.inflationPct||0) / 100 * 12;   // annualized
  // Fisher real-rate: (1+nominal)/(1+infl) − 1
  return (((1+nominalWACC)/(1+infl)) - 1) * 100;
}
```

**Location** — move the WACC card from Finance tab to **Setup tab (Tab 1), immediately below Company Profile and above Planning Calendar** per the user's mandate ("first financial input"). Finance tab keeps a mirrored read-only summary tile so existing users can still see it there.

**UI composition** (single card, Tab 1):
1. Master Budget total (number, ₹).
2. Equity % / Debt % sliders — linked (editing one updates the other so they sum to 100).
3. Mode toggle: **Simple** (single `costOfDebt`) vs **Complex** (debt instruments table — add row / remove row / editable interest rate per row).
4. Cost of Equity input with tooltip: *"Opportunity cost — return a shareholder could earn on equivalent-risk alternative (Nifty, corporate bond, etc). CAPM: Ke = Rf + β·(Rm−Rf)."*
5. Cost of Debt input with tooltip (simple mode): *"Pre-tax interest rate on corporate debt. For complex mode, this is computed as weighted average across all instruments."*
6. Inflation Adjust checkbox → reveals monthly inflation input + optional "Fetch current RBI CPI" button (graceful fallback to manual if API unavailable).
7. **Calculate WACC** button → runs `computeWACC`, shows:
   - Numeric result
   - Formula explanation: `WACC = wE·Ke + wD·Kd·(1−t) = 0.40·13% + 0.60·8.5%·(1−0.25) = 9.03%`
   - Inflation-adjusted line if on: `Real WACC = (1+0.0903)/(1+0.072)−1 = 1.71%`
   - Dispatch: `SET_CONFIG {wacc: result}` — this writes the number into the registry.
8. Below: a small "Downstream consumers" strip showing live values — "NPV calculator: **{cur}** @ {wacc}%", "Buy-vs-Lease: {wacc}%", "Capital-Budget MILP: {wacc}%", "Inventory capital charge: {wacc}%". All read from `state.config.wacc`.

**Backend**:
- [finance.py:208](finance.py#L208) `calc_wacc` extended to accept `debt_instruments` list and `inflation_pct`. Returns `{wacc_nominal, wacc_real, kd_weighted, breakdown}`.
- `calcWACC` in UI keeps the fetch for an authoritative backend result; but the **primary computation is client-side** so the button works offline. Backend is optional audit source.

**Cascade** (delete all direct-WACC reads that bypass registry):
- [index.html:2692](index.html#L2692) — already correct (`state.config.wacc/100`), keep.
- [index.html:4112](index.html#L4112) Buy-vs-Lease — rip the `wacc:10` from `bvl` state; always read `state.config.wacc`.
- [index.html:2407](index.html#L2407) — product-level `crCapital` field stays (per-SKU override, valid use case), but its default should seed from `state.config.wacc` on product creation.
- Capital charge in inventory cost formulas — any hardcoded 10/12/15% → `state.config.wacc`.

**Acceptance tests**:
- `grep -nE "wacc[^:]*:\s*10[^0-9]" index.html` returns zero JSX state-init sites (only the global registry default in `defaultState`).
- Clicking "Calculate WACC" with offline backend still updates `state.config.wacc` via client-side math.
- Changing `state.config.wacc` to 14% immediately changes Buy-vs-Lease NPV number without a page reload.

## 10. Master Budget — canonical 5-head breakdown + envelope wiring

### Current state (problem)

- `state.budget = {procurement, capex, workingCapital}` at [index.html:888, 944](index.html#L888) — only 3 heads.
- Finance tab's "Master Budget" panel has 4 heads (procurement, capex, workingCapital, reserve) at [index.html:4252-4255](index.html#L4252-L4255), which disagree with `state.budget` schema.
- Envelope card at [index.html:1359-1363](index.html#L1359-L1363) (Setup tab) has the same 3 heads.
- No logistics, marketing/sales, or SCM-opex budget heads.
- Working-capital limit shown in UI but **not wired as a hard constraint** into procurement MILP. [procurement.py:33](procurement.py#L33) reads `wh_max` (a *quantity* ceiling, not value). There is no `working_capital` parameter in the solver payload.

### Target architecture

**Single budget schema** (replaces the two disagreeing copies):

```
state.budget = {
  master: number,                 // total, ₹ — feeds Pillar 9 capital structure
  procurement:  number,           // PO spend cap (MILP hard constraint)
  capex:        number,           // buying/leasing decisions
  logistics:    number,           // transport/freight/3PL opex
  marketing:    number,           // CAC, promotions, co-op spend
  scmOpex:      number,           // planner + scheduler + WMS + ERP license + overhead
  workingCapital: number,         // AR+Inv−AP envelope cap; HARD CONSTRAINT in procurement MILP
  reserve:      number,           // contingency buffer
  // Pillar 10 extension — Marketing head includes CAC & payback
  marketingDetail: {
    cac: number,                  // cost to acquire a customer
    monthlyPayback: number,       // derived: lifetime gross margin / CAC months
    promoSpend: number,
    channelSplit: { [channel: string]: number }
  }
}
```

**Other recommended heads** (research-backed for an Indian mid-cap mfg): the 5 chosen above are the canonical opex/capex heads. Additional heads seen at enterprise scale — R&D, HR/talent acquisition, quality/compliance (audit fees, testing), IT/digital — can be added but should live under `scmOpex` or a dedicated `otherOpex` bucket to avoid UI overflow. **Decision for this pass: 5 heads + reserve + master-total. R&D folded into capex; HR/IT folded into scmOpex.** Document the rollup so users know where those sit.

**Envelope (constraint) integration** — the "Budget Envelope" card at [index.html:1359](index.html#L1359) becomes a **display of the same registry** with small toggles for "enforce as MILP constraint" per head. Editing still happens on the Finance tab (single-edit surface).

**Solver wiring**:
- [procurement.py:42](procurement.py#L42) already reads `budget` param. Keep.
- Add `working_capital` param to `solve_procurement`. Enforce as:
  ```
  Σ_{t,k} (inv[k,t] * holding_value[k]) + Σ_{t,i} (rm_inv[i,t] * base_cost[i]) ≤ working_capital
  ```
  Per-period constraint (not sum-over-horizon) — binding when inventory peaks.
- UI payload at every procurement call site: add `working_capital: state.budget.workingCapital`.

**Marketing/CAC**:
- New card in Finance tab: "Customer Acquisition Economics".
- Inputs: CAC, average customer lifetime (months), monthly gross margin per customer.
- Derived:
  - `payback_months = CAC / monthly_gross_margin_per_customer`
  - `ltv = lifetime_months * monthly_gross_margin_per_customer`
  - `ltv/cac ratio` (healthy ≥ 3×)
- Formula tooltip + "Apply to marketing budget" button that writes `budget.marketing = CAC × target_customers_per_quarter × 1.1`.

**Acceptance tests**:
- `grep -n "state.budget.procurement\|state.budget.capex" index.html` returns sites consistent with the new schema; `grep -n "state.budget\." index.html` shows only the 7 keys (master, procurement, capex, logistics, marketing, scmOpex, workingCapital, reserve, marketingDetail).
- Running the procurement solver with `workingCapital = 1000000` produces a binding-constraint shadow price on at least one period when inventory would otherwise exceed this.

## 11. NPV / IRR + Depreciation — functional buttons + MPS-driven advanced mode

### Current state (problem)

- [index.html:4119](index.html#L4119) `calcNPV`, [index.html:4114](index.html#L4114) `calcDepr`, [index.html:4122](index.html#L4122) `calcWACC` — all fetch `/api/calc/*`, silently catch errors. If Flask is offline (zero-build demo mode) the buttons do nothing.
- Backends exist at [finance.py:76, 143, 208](finance.py#L76) and are correct.
- NPV input is a single `cash_flows` comma-string like `'-200,15,22,30,...'` — years only, no monthly option.
- No advanced mode wiring MPS output → NPV.
- Depreciation: residual-value input is a free number; no guidance on SLM vs WDV vs market-based.

### Target architecture

**Dual-path calculation** — each `/api/calc/*` button computes **client-side first**, then optionally validates against the backend:

```js
async function calcNPVSafe(flows, wacc, periodsPerYear=1) {
  const client = npvLocal(flows, wacc, periodsPerYear);   // pure JS
  try {
    const r = await fetch('/api/calc/npv', ...);
    const server = await r.json();
    return { ...client, serverNPV: server.npv, match: Math.abs(client.npv - server.npv) < 0.01 };
  } catch(e) {
    return client;   // offline — client result is authoritative
  }
}
```

**Client helpers** (new, module-scope near `zVal`):

```js
function npvLocal(flows, waccPct, periodsPerYear=1) {
  const r = (waccPct/100) / periodsPerYear;
  const npv = flows.reduce((a, cf, t) => a + cf/Math.pow(1+r, t), 0);
  const irr = irrLocal(flows, periodsPerYear);
  return { npv, irr, flows, waccPct, periodsPerYear };
}
function irrLocal(flows, periodsPerYear=1) {
  // Newton-Raphson, seed 10%, 30 iters
  let r = 0.1;
  for (let i=0; i<30; i++) {
    let f=0, fp=0;
    flows.forEach((cf,t) => { f += cf/Math.pow(1+r,t); fp += -t*cf/Math.pow(1+r,t+1); });
    if (Math.abs(fp) < 1e-9) break;
    const dr = f/fp; r -= dr;
    if (Math.abs(dr) < 1e-6) break;
  }
  return r * 100 * periodsPerYear;
}
function deprLocal(params) {
  const {purchase_price:P, residual_value:R, useful_life:N, method} = params;
  const base = P - R;
  if (method === 'SLM') return { schedule: Array.from({length:N}, (_,y) => ({year:y+1, depr: base/N, book: P - (base/N)*(y+1)})), depreciable_amount: base, method };
  if (method === 'WDV') { let b=P; const rate=(params.wdv_rate||0.2); return { schedule: Array.from({length:N}, (_,y) => { const d = b*rate; b-=d; return {year:y+1, depr:d, book:Math.max(b,R)}; }), depreciable_amount: base, method }; }
  if (method === 'UoP') { const u=params.annual_units||[]; const tot=params.total_units||u.reduce((a,b)=>a+b,0); return { schedule: u.map((un,y)=>({year:y+1, units:un, depr: base*un/tot, book: P - base*u.slice(0,y+1).reduce((a,b)=>a+b,0)/tot})), depreciable_amount: base, method }; }
}
```

**Horizon flexibility** — NPV form gets a "Period" selector: **Monthly / Quarterly / Yearly**. `periodsPerYear ∈ {12, 4, 1}`. Label the cashflow input accordingly.

**Advanced NPV (new, separate subcard — stays on Finance tab, not a new tab, to avoid tab sprawl)**:
- Title: "📈 Plan NPV — MPS-driven".
- Reads: `demandByPeriod(each product)` × `sellPrice − variableCost − material`, minus `budget.procurement` outflow schedule, minus `budget.capex` year-1, discounted at `state.config.wacc`.
- Output: Plan NPV, break-even period, sensitivity bars vs WACC ±2%, Material cost ±10%, Demand ±20%.
- Formula exposition: `Plan NPV = Σ_{t} (revenue_t − cogs_t − opex_t) / (1+WACC/periodsPerYear)^t − CAPEX_0`.
- Button "Apply to Master Budget" — writes suggested split back to `state.budget` based on the plan.

**Depreciation — residual-value guidance**:
- Tooltip on the residual field shows 3 recommended methods:
  1. **Market quote**: use a current used-equipment listing price (best when liquid market).
  2. **Salvage convention**: Indian tax statute — 5% of original cost (common fallback).
  3. **Engineering estimate**: residual = book value after `0.9 × useful_life` years with WDV at industry-standard rate (conservative).
- Add a small "Suggest" button that offers values from each convention based on current `purchase_price`.

**Acceptance tests**:
- Disable network (block `/api/`); all three Calculate buttons still produce results.
- Result pane shows both "Computed locally" and "Backend verified ✓" when online.
- Advanced Plan NPV updates when any product's history, sellPrice, or WACC changes.

## 12. Production Architecture — new dedicated tab

### Current state (problem)

- Production fields are scattered:
  - Product capacity (per-SKU, weekly max) at [index.html:2050+](index.html#L2050) (Products tab).
  - OEE (availability/performance/quality) per-product at default state ([918-924](index.html#L918)) — fed into `oeeTarget` config. **Single global figure**, user notes this is wrong.
  - Lines defined in `state.production.lines[]` at [index.html:964+](index.html#L964) with capacity/shifts/hoursPerShift/breakMins — but no multi-stage, no machines-per-stage, no worker count, no outsourcing flag.
  - Line-SKU mapping implicit (via `products:[idx]` on each line). No stage-level cycle time.
  - Shared-capacity display in procurement solver results shows `0.317 × product` — that's `cycleTime/60 = 19/60 = 0.317 h/unit`, real data but badly labeled.
  - Min/max production bounds are either implicit (cap × periods) or hardcoded — not derived from the line physics.
  - Labor cost exists as a free-form number; no shift schedule, overtime policy, or peak-season contract labor model.
- "Adding labor / machines / extra hours — will it help?" question: no sensitivity surfacing.

### Target architecture

**New tab: "Production Setup"** (Tab 1.5 — between Setup and Products, since the mandate says "nothing can be accurately computed without this foundation"). Wizard-style with 6 steps. Output is a **normalized production topology** that every downstream solver reads from.

```
state.production = {
  // existing
  lines: [...],
  // NEW — canonical production topology
  topology: {
    lines: [
      {
        id: 'L1', name: 'Assembly Line 1',
        stages: [
          {
            id: 'S1', name: 'Cut',
            machines: 2,
            workers: 4,
            cycleMin: 3.2,                  // per unit
            oee: { availability: 0.88, performance: 0.94, quality: 0.99 },  // per-stage
            canOutsource: false,
            outsource: null,                // { cost_per_unit, min_batch, return_lt_days }
            bomConsumption: ['rawSteel-1', 'fixture-12']   // part ids this stage consumes
          },
          { id: 'S2', name: 'Weld', ... },
          { id: 'S3', name: 'Paint', canOutsource: true, outsource: {cost: 12, min_batch: 200, return_lt_days: 4}, ... },
        ],
        shifts: 2,
        hoursPerShift: 8,
        breakMins: 30,
        contractLaborAllowed: true,
        laborRatePerHour: 250,              // ₹
        overtimeMultiplier: 1.5,
        overtimeThresholdPct: 80,
      }
    ],
    skuMap: [
      { productId: 'sku-1', lineId: 'L1', stageSequence: ['S1','S2','S3'] }
    ],
    capacityMode: 'derived' | 'manual',     // Step 4 choice
    manualUtilization: 0.90                 // used if mode === 'manual'
  }
}
```

**Derivation formula** (Step 4a — derive from physics):

```
effective_hours_per_period = shifts × (hoursPerShift − breakMins/60) × workDaysInPeriod × (1 − weekend_adj) × holidayFactor
bottleneck_stage = argmax over stages of: cycle_min_per_unit / (machines × workers_available)
line_capacity_per_period = (effective_hours_per_period × 60) / cycleMin_bottleneck × oee_bottleneck
```

When `capacityMode === 'derived'`, the per-line capacity displayed in the Products tab becomes read-only and recomputed. When `capacityMode === 'manual'`, the user sets target utilization; effective capacity = theoretical × utilization.

**OEE per stage, not global** — each stage has its own `{availability, performance, quality}`. Line OEE is the weighted product. Global `oeeTarget` stays as an *aspiration* in the Industry Preset (marker for targeting), but actual calculation uses per-stage OEE. If mode is "derived" we do NOT double-apply OEE (user's question): the derivation bakes it in.

**Stage-level outsourcing** (Step 5):
- `canOutsource: true` surfaces inputs for `cost_per_unit` (3rd party), `min_batch_size` (qty dispatched in one go), `return_lt_days`.
- Solver treats outsourced stages as an **OR decision**: `x[stage] = inhouse_qty OR outsource_qty`, with outsource qty constrained to ≥ min_batch and adding `return_lt_days` to effective lead time for subsequent stages.
- Transport cost for the dispatch-and-return flows into landed cost of the WIP after that stage.

**Shift/Labor** (Step 6): already mostly modeled, just surfaced. Overtime policy feeds the scheduler's `ot_mult` and `ot_threshold` at [index.html:2553](index.html#L2553).

**Min/Max derivation for MILP**: `max[k, t] = line_capacity_per_period × stageAllocationFactor[k]` (auto-populated, not user-entered). User cannot manually set a max that exceeds physics — validation error.

**"Will adding X help?" sensitivity** (Step 4 footer):
- Three one-click simulations:
  1. **+1 shift** — recompute with `shifts+1`, show delta capacity and delta opex.
  2. **+1 machine at bottleneck stage** — show delta capacity vs incremental CAPEX amortized.
  3. **+2 workers at bottleneck stage** — delta capacity vs incremental labor cost/year.
- Output: which lever moves capacity most per rupee. This is a simple `Δcapacity / Δcost` table — not a full solver run.

**Cascade into solvers**:
- Procurement MILP: `cap` per product = `derived line_capacity × skuAllocation`.
- Production scheduler: already reads `state.production.lines`; extend to read `topology` when present.
- Cost waterfall: sum labor + outsourced costs per stage into COGS.

**Acceptance tests**:
- Products-tab capacity field is read-only when `topology.capacityMode === 'derived'`.
- "+1 shift" sensitivity produces a number (not a spinner).
- Shared-capacity label in solver output reads `"<cycle_minutes> min/unit × <qty> = <hours>"` instead of the raw decimal.

## 13. MILP solver — logic + label fixes

### Current state (problem)

- **Ordering cost**: [procurement.py:273](procurement.py#L273) is correct (`obj.append(part['ord_cost'] * o[gidx, t])`). But the UI tooltip for Ord Cost at [index.html:2030](index.html#L2030) and the EOQ explanation at [index.html:5157](index.html#L5157) say *"S = ordering cost per PO — admin + transport"* — conflating transport with admin. Real fix: relabel to exclude transport; transport is a per-unit variable and already separate.
- **Shared capacity display** "0.317 × product": real data (minutes-to-hours conversion) but the label hides it. User reads it as placeholder.
- **Demand ceiling**: [profitmix.py:238+](profitmix.py#L238) uses annual demand with no explicit mode flag. Need to support `demand_mode ∈ {simultaneous, daily, weekly, mto, mts}` explicitly. MTS = push to demand forecast; MTO = pull from confirmed orders; daily = strict per-period ≤ demand; simultaneous = all products produced in parallel without sequence cost.
- **Safety buffer `forecast × (1+MAPE%)`**: current usage is valid for deterministic MILP under a robust-optimization interpretation. User is right that this must be labeled clearly and contrasted against rolling-horizon stochastic approaches.
- **Shelf life formula `avg_d[k] / 7`**: at [procurement.py] treats shelf life in weeks, dividing by 7 to get days. If periods are weekly this is correct; if daily, this is a bug. Audit for grain-dependence.
- **MILP formulation display order**: out of order in the explanation block. Profit-mix `≥ 0` non-negativity is correct but needs explanation. Need variant displays for each demand mode.
- **Shadow prices / dual variables**: already implemented in Round 1 Pillar's Solver Diagnostics enhancement. Keep.

### Target architecture

**Label fixes** (non-code changes):
- [index.html:2030](index.html#L2030) Ord Cost tooltip → *"Fixed admin cost per PO (processing, approval, receipt). Transport cost is a separate per-unit variable modeled via Trans Rate Tiers. Do NOT roll transport into this field."*
- [index.html:5158](index.html#L5158) EOQ line → split "S (ordering cost)" from "transport" explicitly.
- Solver output "0.317 × product" → display as `"{cycleTimeMin} min/unit = {cycleTimeHrs.toFixed(3)} h/unit; constraint: Σ(h/u × qty) ≤ {availHours} per {grainLabel}"`.

**Demand mode state**:

```
state.products[k].prodMode ∈ {'mts','mto','hybrid'}                      // already exists; surface it clearly
state.planning.demandMode ∈ {'simultaneous','period-daily','period-weekly'}
```

Solver accepts `demand_mode` per product. Constraint variants:

```
# simultaneous (current default)
Σ_k p[k,t] ≤ shared_cap_t     ∀ t

# daily (strict per-period)
p[k,t] ≤ demand[k,t]          ∀ k,t   // no inventory carry across periods

# weekly MTS
inv[k,t] = inv[k,t-1] + p[k,t] - demand[k,t]   // inventory absorbs

# MTO
p[k,t] ≥ confirmed_orders[k,t]   // produce exactly what's ordered; no stock
```

MILP display block gets a mode selector that swaps the rendered constraint set to match.

**Safety buffer labeling** (UI only — no logic change):
- Tooltip: *"Deterministic robust-optimization: plan = forecast × (1+MAPE%). Solve once per horizon, no re-plan in flight. For true stochastic / rolling-horizon use Advanced → Rolling MPS."*
- Label the Rolling MPS runner as **"Stochastic — re-solves each wave"**, contrast vs the deterministic default.

**Shelf life audit**:
- [procurement.py] introduce `shelf_periods = shelf_life / (days_per_period)` where `days_per_period = {daily:1, weekly:7, monthly:30}` based on `time_grain`. Replace all `shelf_life/7` literals.

**Formulation display order**:
- New component `<MILPFormulationCard/>` that renders constraints in a fixed order: Objective → Vars → C1 Inventory Balance → C2 Capacity → C3 Warehouse → C4 Budget → C5 Shelf Life → C6 MOQ → C7 Tier Selection → C8 Safety Stock → C9 Non-negativity → (mode-specific) → Dual outputs.

**Acceptance tests**:
- `grep -nE "shelf_life\s*/\s*7" procurement.py` returns zero hits after the audit.
- Switching `demand_mode` from `mts` to `mto` in the Products tab changes the constraint set shown in the Complete MILP Formulation card.

## 14. Buy-vs-Lease — registry-wired WACC

### Current state (problem)

Local state at [index.html:4112](index.html#L4112): `bvl = {..., wacc: 10}`. Header "Buy vs Lease Comparison · {bvl.wacc}% WACC" at [index.html:4278](index.html#L4278). Only refreshes via a manual "Apply to Buy-vs-Lease" button at [index.html:4457](index.html#L4457).

### Target architecture

Delete `wacc` from `bvl` local state. Every `bvl.wacc` read becomes `state.config.wacc`. Any BVL formula that computed NPV with `bvl.wacc` now uses registry. Remove the "Apply to Buy-vs-Lease" button (no longer meaningful) OR re-purpose as "Reset taxrate override" if users want a local override (low value — delete).

**Acceptance test**: change `state.config.wacc` in Tab 1; BVL NPV numbers update within one render without clicking anything.

## 15. Working capital — payment-terms confirmation workflow

### Current state (problem)

- `state.workingCapital = {dso, dpo}` at [index.html:924](index.html#L924) — two numbers, DSO and DPO, global.
- Payment terms per BOM part: `payTermDays` and `earlyPayDisc` at [index.html:886](index.html#L886) — defined but there's no *event trail*. When a PO is released, there is no record of when the payment was actually made.
- Cash-tied-up calculation is a heuristic: `AR + Inventory − AP ≈ (Revenue × DSO/365) + (Inv_days × COGS/365) − (COGS × DPO/365)` — no per-PO granularity.

### Target architecture

**Event-log state addition**:

```
state.workingCapital.paymentEvents = [
  {
    id, poId, partId, supplierName,
    releaseDate: ISO,                 // PO issued
    invoiceDate: ISO,                 // invoice received
    termsDays: number,                // e.g. 60
    dueDate: ISO,                     // invoiceDate + termsDays
    paidDate: ISO | null,             // actual payment date, null = unpaid
    status: 'pending' | 'on-time' | 'early' | 'late',
    amount: number,
    notes: string
  }
]
```

**Default assumption** when a new PO release is detected (from solver output or manual input):
- `paidDate` is **auto-set** to `dueDate` (last day of terms). Status: `'pending'`.
- UI shows a "Confirm payment" prompt on the PO row. User clicks:
  - **On time** → no change (default stands).
  - **Early** → date picker, sets `paidDate` before `dueDate`, status `'early'`, applies `earlyPayDisc` to amount.
  - **Late** → date picker, sets `paidDate` after `dueDate`, status `'late'`.
  - **Override** → free date picker + notes.

**Cash-tied-up calculation** (deterministic, per-PO):

```js
function accountsPayableAsOf(asOfDate, events) {
  return events
    .filter(e => {
      const invoice = new Date(e.invoiceDate);
      const paid = e.paidDate ? new Date(e.paidDate) : null;
      return invoice <= asOfDate && (!paid || paid > asOfDate);
    })
    .reduce((sum, e) => sum + e.amount, 0);
}
function cashTiedUpAsOf(asOfDate, state) {
  const ap = accountsPayableAsOf(asOfDate, state.workingCapital.paymentEvents || []);
  const inv = inventoryValueAsOf(asOfDate, state);
  const ar = accountsReceivableAsOf(asOfDate, state);
  return ar + inv - ap;
}
```

**UI** — new card in Finance tab "Payment Ledger":
- Table: PO / Supplier / Invoice / Due / Paid / Status / Amount / [Confirm].
- Filter by: pending / overdue / supplier.
- Footer: "Accounts Payable as of today = {cur}X,XXX,XXX" (live).
- Feeds the Cash Conversion Cycle KPIs which currently use approximate DSO/DPO.

**Procurement solver** gets per-period `working_capital` constraint (Pillar 10) that uses this deterministic AP, not the DPO heuristic. Payload passes `outstanding_ap` as a constant to offset the constraint.

**Acceptance tests**:
- After running a procurement solve, the Payment Ledger shows one row per PO with `paidDate = dueDate` and `status = pending`.
- Clicking "Paid early" on a row with `earlyPayDisc > 0` reduces `amount` and moves `paidDate` forward.
- Cash-tied-up KPI matches `Σ(AR) + Σ(Inv) − Σ(AP)` computed from the ledger (not from the DSO/DPO formula) — the formula is shown only as a fallback tooltip.

---

## Round 2 cross-pillar dependencies

- **Pillar 9 (WACC) must land before Pillar 14 (BVL)** — BVL depends on the registry.
- **Pillar 12 (Production Architecture) must land before Pillar 13** — shared-capacity label clarity depends on having a stage-level cycle-time definition.
- **Pillar 10 (Master Budget) must land before Pillar 11's Advanced NPV** — Plan NPV reads `budget.capex`, `budget.procurement`, etc. from the new schema.
- **Pillar 8 migration (Round 1) must be extended** — Pillars 9, 10, 15 introduce new state shape (`state.finance.debtInstruments`, `state.budget.logistics/marketing/scmOpex`, `state.workingCapital.paymentEvents`). The `migrateState` function gains a v1→v2 step: copy old `config.wacc` into `state.finance` if empty, default new heads to 0, initialize `paymentEvents` to `[]`.

## Round 2 order of work (prescriptive)

1. **Pillar 9** — WACC registry + Tab-1 relocation + functional Calculate button. Client-side math; backend optional. Writes `state.config.wacc`.
2. **Pillar 14** — Buy-vs-Lease rips local `wacc:10`, reads registry. Trivial change, land same PR as 9.
3. **Pillar 10** — Master Budget 5-head schema + MIGRATION. Envelope becomes a display of the registry.
4. **Pillar 11** — NPV/IRR/Depreciation client-side dual-path + horizon selector + residual guidance + Advanced Plan NPV.
5. **Pillar 13** — MILP label/tooltip fixes + shelf-life audit. No behavior change (safe).
6. **Pillar 12** — Production Architecture new tab. Largest UX.
7. **Pillar 15** — Payment ledger + cash-tied-up calc. Depends on PO event firing from procurement solver output.

## Round 2 non-goals

- No ML demand forecasting integration (stays a separate future arc).
- No real-time RBI CPI API integration — manual inflation input with a note. If/when the backend gets an RBI connector, Pillar 9's inflation input becomes a read-only display.
- Production Architecture stays on a single page (wizard-style) — no multi-step modal dialogs, no route changes.
- Payment ledger is local-state only in Pillar 15. Multi-user shared ledger is a backend concern, deferred.

---

*Sign-off on Round 2 pillars before implementation. Acceptance tests in each pillar section are the verification gates.*

---

# Round 3 — Final Fix Pass (P1-P9) — RESUME LOG

> **Purpose:** This section is a hand-off log so a future session (after `/compact`) can pick up exactly where work paused. Read this first if you join mid-stream.
>
> **Format per batch:** Goal · Subtasks · Status · Files touched · Wiring notes · Resume hints.

## Round 3 master plan (9 batches)

| Batch | Title | Status |
|-------|-------|--------|
| **P1** | UI hygiene (13 items) | ✅ COMPLETE |
| **P2** | Supplier consolidation | ✅ COMPLETE |
| **P3** | Forecasting overhaul | ✅ COMPLETE |
| **P4** | Demand sensing in MPS | ✅ COMPLETE |
| **P5** | Control tower + frozen horizon | ✅ COMPLETE |
| **P6** | Procurement risk + currency hedging | ✅ COMPLETE (HMM deferred) |
| **P7** | Inventory & cost cleanup | ✅ COMPLETE |
| **P8** | RCCP + scenarios + EVM + risk matrix | ✅ COMPLETE (scenario-program wiring deferred) |
| **P9** | Network design + Learning Lab cleanup | ✅ COMPLETE (Lab content move deferred) |

## Scope flags resolved with user

- **ML stack**: real models, server-side via `forecast.py` mirroring `procurement.py` pattern. NOT browser TF.js. `forecast.py` uses scikit-learn + statsmodels + xgboost with try/except so missing libs degrade gracefully. **DL tier** = sklearn `MLPRegressor` (no TF/PyTorch — RAM-friendly for Render free tier).
- **Google Maps**: stub with great-circle from lat/lon + manual override (no API key in single-file HTML). Implement in P9.
- **Excel import**: SheetJS via existing CDN at `index.html:10`.

---

## P1 — UI hygiene (DONE)

13 items shipped. Key facts to remember:

- **CSS grid bug**: `grid6/7/8` were used in JSX but had **no CSS rules** → silent stacking. Fixed at `index.html:292-300` (added `.grid5..grid8` with breakpoints `<1100px → 4-col`, `<768px → 2-col`).
- **`SectionInfo` component** at `index.html:~1390`: pattern for section-level info icons (large `ⓘ` with click/hover popup). `CollapsibleCard` accepts an `info` prop; non-collapsible cards inline `<SectionInfo>...</SectionInfo>`. **18 of ~110 cards instrumented**; rest can be filled in incrementally using same pattern.
- **`shelfLifeToPeriods`**: now `Math.floor` (was `ceil`), `max(0, …)` (was `max(1, …)`). Daily grain → exact; weekly/monthly → conservative floor. See `index.html:710-718`.
- **`milkRunPerPeriod(prod)` helper** at `index.html:~720`: returns 0 / cost·freq / cost / cost·freq·supCount based on mode.
- **Demo dataset clear**: `RESET_DEMO` reducer was incomplete (only cleared products+suppliers). Now wipes config.companyName, production.lines, network, budget. `index.html:~1336`.
- **India map collision-avoidance**: `IndiaSupplyMapPanel` at `index.html:~8003` — co-located nodes fan around centroid; foreign nodes (Tokyo) clamp to bbox edge with `⚑` flag.
- **Parameter Cascade** at `index.html:~7746`: 3-column dependency map (Inputs → Derived → Consumers) with hover-to-trace. **Not** the random chip layout it had before.
- **MPS daily view**: now uses real calendar dates from `horizonStartDate`, skips weekends per `workDays`, excludes gazetted holidays. `index.html:~6400`.
- **InventoryProjectionCard**: reads from `state.solverResults.procurement.products[k].production` (was reading non-existent `production_per_period`). `index.html:~6635`.
- **TransportAllocationCard**: reads `state.network.nodes` (was reading `state.config.networkNodes` — a stale duplicate that always returned `[]`). Rates seeded from defined lane `ratePerUnit` (was `Math.random()`).
- **Cost waterfall** at `index.html:~5550`: split transport into `Inbound Trans` (BOM trans-rate × qty) + `Outbound Trans` (FG outRate × qty), added Quality Loss derived from `yieldPct`.
- **Milk run** at `index.html:~2843`: 4 modes (off/perTrip/perPeriod/perSupplier). Wired into solver — see "Solver wiring" below.

## P1 → Solver wiring audit (DONE)

| Field | JS payload | Solver consumes? | Gap |
|-------|-----------|-----------------|-----|
| `holidays`, `horizon_start_date` | All 9 procurement payloads send both | YES — `procurement.py:67-88` builds `cap_factor` for Pillar 6 holiday-exclusion | none |
| `policy_leaderboard` | n/a (output) | EMITTED at `procurement.py:544` — per-material in `result.materials[i].policy_leaderboard` + `proc_policy_chosen` | UI traversal fixed (was looking at non-existent top-level path) |
| `production[]` / `inventory[]` | n/a (output) | EMITTED at `procurement.py:445-446` — per-product in `result.products[k]` | UI traversal fixed |
| `milk_run_per_period` | NEW field, batch-injected into all 9 procurement product payloads | NEW — `procurement.py:200-220` adds to objective per period; `cost_breakdown.milk_run` line at `procurement.py:586+` | Wired |

## P2 — Supplier consolidation (DONE)

Built `SupplierManagementCard` at `index.html:~4344` — single Tab 3 card replacing 3 prior sections:

1. **📊 Roster + Scorecard** — auto-derived from BOM `supplierName`. Editable per-supplier `quality / otd / reliability` (defaults: quality = avg `partYield` from BOM, OTD/reliability = 90/88). Composite = weighted by `state.supplierWeights` (Σ=100 with editable inputs).
2. **🧮 Should-Cost** — per BOM item: `material / labor / otherProc / ohPct / marginPct` (stored on `b.shouldCost`). Variance vs supplier quote with traffic-light coloring.
3. **📝 Contract Definitions** — per supplier: `currency / contractType / paymentTerms / hedgeRatio / startDate / endDate / notes`.

**State additions**:
- `state.supplierProfiles = {}` — keyed by supplier name.
- Reducer cases `SET_SUPPLIER_PROFILE`, `DEL_SUPPLIER_PROFILE` at `index.html:~1295`.
- BOM rows now have optional `shouldCost: {material, labor, otherProc, ohPct, marginPct}`.

**Removed duplicates**: Command-Center "Supplier Scorecard Methodology" + "Should-Cost Modeling" docs — replaced with a single redirect note pointing to Tab 3.

**Solver wiring**: none yet. `supplierProfiles.currency` + `hedgeRatio` will be consumed by P6 (currency hedging into landed cost). `supplierProfiles.otd` will be auto-populated from PO history in P4.

## P3 — Forecasting Overhaul (DONE)

**New file [`forecast.py`](forecast.py)** (~310 lines) — 8 models, holdout-MAPE leaderboard.

Models: `naive`, `holt_winters`, `arima`, `random_forest`, `gradient_boost`, `xgboost`, `mlp` (sklearn neural net = "DL"), `hybrid` (HW + RF residuals).

Feature pipeline (ML/DL/Hybrid only): lag-1, lag-7, lag-30, roll-mean(3), roll-mean(7), DOW, month, quarter, holiday flag, promo flag.

Bucket recommender:
- `<12 obs` → `[naive, holt_winters, arima]`
- `12-36` → `[holt_winters, arima, random_forest, hybrid]`
- `>36` → `[random_forest, gradient_boost, xgboost, mlp, hybrid]`

Returns `env: {sklearn, statsmodels, xgboost}` so UI shows installed-package status.

**Wired into Flask** [`app.py:341+`](app.py#L341) at `POST /api/forecast`.

**Requirements bumped** [`requirements.txt`](requirements.txt): `scikit-learn>=1.4.0`, `statsmodels>=0.14.0`, `xgboost>=2.0.0` — install via `pip install -r requirements.txt` on Render redeploy. Each is wrapped in try/except in forecast.py so partial install still works.

**New UI: `ServerForecastCard`** at `index.html:~2185` — sits between client-side Forecast Model Competition and Demand Plan Overrides. Tier selector (auto/classical/ml/hybrid/dl/all), Run-on-Server button, leaderboard with per-model "📥 Apply" → writes forecast into `prod.overrides` and back-syncs `prod.mape`.

**Excel import** at `index.html:~1664`: added `📋 Format` button (column spec dialog) + preview-before-commit confirm with summary (rows accepted, granularity, monthly buckets, neg/zero counts, promo-flagged buckets, total/min/mean/max, head+tail). Promo column auto-creates `events` of type `promo`.

**Promotions card** at `index.html:~2710`: added "Include / Exclude uplift in baseline" toggle (`prod.promoBaseline`).

**ADD_EVENT reducer** extended to accept custom `event` payload (for Excel import auto-promo-flagging).

---

## P4 — Demand Sensing in MPS (DONE)

**Shipped**:

- Standalone Demand Sensing card consolidated → small redirect note + actuals matrix; full breach detection / alerts / actions live in `MPSVizCard`.
- `MPSVizCard` breach banner now shows 2 alert-action buttons:
  - **🔁 Re-run MILP from {period}** — sets `state.planning.replanFromPeriod` + `sensingActionMode='rerun-milp'`. User then runs procurement in Tab 9; payload sends `actuals_override` per-product + `replan_from_period` in params.
  - **🩹 Rolling-horizon adjust (Np)** — writes exponentially-smoothed adjustment into next N periods via new `SET_MPS_ROLLING_PATCH` reducer. NO solver re-run. Patch surfaces in MPS Monthly view "Adj Plan" column.
- Default policy logic: `consecutive` breach counter reading filled actuals back-to-front. ≥ `state.planning.sensingResolveAfter` (default 4) → recommend full re-solve; otherwise rolling-horizon. Recommendation surfaced as the "RECOMMENDED ACTION" line in the breach banner.
- New reducers: `UPDATE_PRODUCT_ACTUALS` (bulk write), `SET_MPS_ROLLING_PATCH`, `CLEAR_MPS_ROLLING_PATCH`. Located near `UPDATE_ACTUAL` in the reducer.
- New state shape: `state.mpsRollingPatch = { [productId]: { [periodIdx]: number } }`.
- `procurement.py` extended: accepts `params.replan_from_period` + per-product `actuals_override: [num|null]`. When the anchor is set, `LockActual_{k}_{t}` constraints fix `p[k,t] = round(actuals_override[t])` for `t < replan_from_period`. Result echoes `replan_from_period` + `actuals_locked` count.
- `actuals_override` injected into all 9 procurement payloads via the shared `milk_run_per_period:milkRunPerPeriod(p),` anchor (replace_all).
- `replan_from_period` added to procurement params at `index.html:~3223` (main solve dialog) and `index.html:~7731` (SolverPipelineTab readiness card).

**Verified**: smoke-tested with `replan_from_period=3` + `actuals_override=[12,11,9,None…]` — solver returns `actuals_locked: 3` and production = `[12, 11, 9, 50, 33, 0, ...]`.

---

## P5 — Control Tower + Frozen Horizon (DONE)

**Shipped** (located in `AnalysisTab` Tab 6, not Command Center — alert generator + Control Tower card live there):

- Alert generator now produces tagged alerts: `{sev, msg, period?, zone, actions?, source}`. Zones: `frozen | slushy | open | global`.
- Static (config) alerts: short shelf life, single-source BOM, long lead time, missing Incoterm, capacity vs avg-demand gap. Each carries `actions` with impact-estimate strings.
- Solver-driven alerts: reads `state.solverResults.procurement.products[k]`:
  - `fill_rate < 100` → horizon-wide alert with action recommendations.
  - per-period `shortage[t] > 0` → period-tagged alert; severity scales with zone (frozen=critical, slushy=warn, open=info).
  - per-period at-capacity (production ≥ 99% cap AND demand > cap) → period-tagged "at-capacity" alert with shift+outsource recommendations.
- Replan-anchor banner: when `state.planning.replanFromPeriod` is set, surfaces an info-alert tagged with the anchor period.
- Scope filter UI: 5 buttons (All / Frozen / Slushy / Open / Global) with live counts.
- Each alert renders zone badge + period number + urgency tag (URGENT-UNACTIONABLE / ACTIONABLE-WITH-APPROVAL / ACTIONABLE).
- Source tag (`[config]` or `[solver]`) helps users spot which alerts react to a re-solve.
- `useEffect` deps include `state.solverResults` so alerts refresh after every solver run.

---

## P6 — Procurement Risk + Currency Hedging (DONE; HMM deferred)

**Shipped**:

- New helper [`effectiveFX`](index.html) computes hedged FX = `spot × (1 − h) + forward × h`, returning 1 when supplier currency = home currency or rates missing.
- `landedCost(b, config, plant, profiles)` extended with 4th arg. When the BOM row's supplier has a profile with non-home currency, the base cost is multiplied by the hedged FX before transport overlays. All 4 callers updated via replace_all.
- `state.config.fxRates = {USD, EUR, JPY, GBP, CNY, SGD}` seeded in both Tata and generic `defaultState`. Editable in the new Procurement Risk card.
- Per-supplier `forwardRate` field added to Contract Definitions row alongside existing `hedgeRatio`. Live-computed "Effective FX" column shows the resulting multiplier.
- New [`ProcurementRiskCard`](index.html) component placed in FinanceTab after `PaymentLedgerCard`. Three sections:
  1. **Spot-price volatility** — z-score per BOM row using `b.priceHistory[]` (4+ points) or `b.costCV` fallback (≥ 15% → soft flag). Threshold `|z| ≥ 1.5σ` raises an alert with 4 release options (Release / Delay / Trigger backup / Hedge).
  2. **FX exposure rollup** — per-supplier table of annual spend in supplier currency, spot, forward, hedge %, effective FX, annual at effective rate, and Δ (hedge gain/loss). Only shows foreign-ccy suppliers.
  3. **Backup-supplier auto-check** — flags long-LT parts (>2 wk) with no qualified backup; for parts WITH qualified backup, shows LT gap, cost premium, and quality of best alternative.

**HMM regime detection deferred** to a future `risk.py` module — low-priority; user said "research-then-decide" and the existing volatility z-score covers the immediate need.

---

## P7 — Inventory & Cost Cleanup (DONE)

**Shipped**:

- **Yield variance**: new `prod.yieldActual` field next to `prod.yieldPct` in Product Parameters. When non-null, a side-by-side variance card shows `(actual − predicted) pp` colored by threshold (>5pp red, >2pp amber, else green).
- **WH 4-mode capacity**: new `state.budget.warehouseMode ∈ {units, area, volume, unlimited}` selectable in Setup → Budget. Plus `state.budget.warehouseLimitArea` (m²) and `state.budget.warehouseLimitVolume` (m³).
- Per-product `prod.footprintArea` (m²/u) + `prod.footprintVolume` (m³/u) added to Product Parameters.
- New helper `effectiveWhMaxUnits(state, defaultUnits)` translates the configured mode into a unit count for the solver:
  - `units` → `state.budget.warehouseLimitUnits || defaultUnits`
  - `area` / `volume` → weighted-avg footprint × demand-weighted denominator
  - `unlimited` → 999999
- All 4 procurement / Monte Carlo / sensitivity payload sites updated to use `effectiveWhMaxUnits()` and pass `wh_mode` for echo/audit.
- Live-effective preview chip next to the WH mode selector shows the resulting unit count with the weighted-avg footprint denominator.

**Not changed** (already correct):

- `procurement.py` `eff_mult` already implements scrap/yield hierarchy `(1 + scrap) / (partYield × yieldPct)`. Verified against the resume log.
- TCO quality loss in cost waterfall already uses `annMat × (1 − yieldPct)` (P1.12). Now if user fills `yieldActual`, that variance is visible — the waterfall keeps using predicted (planning view) which is the expected behavior.

---

## P8 — RCCP + Scenarios + EVM + Risk Matrix (DONE; scenario-program wiring deferred)

**Shipped**:

- **EVM bug fix**: the four `setEvm(v=>({...v, key:v}))` setters had a variable-shadowing bug — the inner `v` shadowed the `NumInput`'s new value, so updates wrote the entire previous `evm` object into `bac`/`pctPlanned`/`pctActual`/`actualCost`. Fixed by renaming the outer parameter to `nv` and the updater arg to `prev`.
- **RCCP overhaul** ([`RCCPLoadPanel`](index.html)): replaced random+heuristic load% with real math reading `state.production.topology.lines[L].stages[S]`. Stage capacity = `machines × 60/cycleMin × OEE × availHrsPerPeriod`; demand per stage = aggregated history. Bottleneck stage flagged. Available hours derived from `hoursPerShift × shifts − breaks`. Shutdown opportunity banner appears when avg load < 30%.
- **RiskMatrixCard** (new component, placed after EVM in AnalysisTab): 5×5 P×I grid coloured by score (LOW 1-4, MEDIUM 5-9, HIGH 10-14, CRITICAL 15-25). Risks plotted as chips inside their cell. Below the grid, a register table allows editing name / P / I / owner / status / mitigation.
- New state: `state.risks=[]` with 4 seed entries (supplier default, FX surge, demand surge, cyber). Reducers `ADD_RISK / UPDATE_RISK / DELETE_RISK`.

**Deferred** to a future round:

- **Scenario programming wiring** (turning saved scenarios into solver perturbations: supply-delay → leadTime, price-spike → cost_event, etc.) — the existing scenario save/load/delete is already in place; deferred wiring affects multiple solvers and would need a dedicated round.
- **+10% product size scenario** — superseded by the cost_event mechanism that already exists for many of the relevant params.

---

## P9 — Network Design + Learning Lab (DONE; Lab content move deferred)

**Shipped**:

- **LTL vs FTL math** in Lanes table: new "L/F suggest" column. Rule: util = unitsPerShip / truckCapacity; util > 60% → FTL recommendation, else LTL. Mode mismatch flagged with ⚠ + amber badge. Default truckCapacity = 1000u (configurable per-lane via `lane.truckCapacity`).
- **Manual distance override**: new editable "Distance (km)" column on each lane. Falls back to great-circle Haversine stub when `lane.distanceKm` is null. Override is yellow-coloured to distinguish from the stub default.
- **Mode-aware suggested rate** already existed (great-circle × ratePerTKm × weight); now correctly recomputes when distance is overridden.
- **Sparse demand confirmation** (no code change needed): manually verified — `procurement.py` does the right thing with `demand=[0,0,0,0,0,0,0,200,0,0,0,0]`. MILP minimizes cost so it doesn't force production where demand is 0; safety stock floor still respected. Documented in this section.

**Deferred**:

- **Center-of-gravity ML toggle** — current Haversine-weighted COG is already a useful first cut. Adding k-means + ML weighting needs lifecycle data we don't have (lane-frequency over time). Will be re-evaluated when traffic-pattern history is captured.
- **Contract types → Learning Lab move** — content currently lives in Tab 3 SupplierManagementCard "Contract Definitions" footer. Moving it would require splitting the educational text out into a Learning Lab section; deferred as a presentation-only change.
- **Restaurant short-shelf example preset** — would need a separate "Load preset" button in the LearningLab tab with a curated state snapshot. Defer to a UX polish round.

---

## State shape additions across Round 3

These have already shipped in P1-P3 — keep them in mind when reading state in P4+:

```js
state.config = {
  // ... existing
  // (no Round 3 additions to config so far)
}

state.production = {
  // ... existing
  topology: { lines: [{stages: [{...,canOutsource,outsourceCostPerUnit,outsourceLeadDays}]}] }, // P1.12
}

state.products[k] = {
  // ... existing
  promoBaseline: 'include' | 'exclude',  // P3.6
  milkRunMode: 'off' | 'perTrip' | 'perPeriod' | 'perSupplier',  // P1.13
  milkRunCost: number,
  milkRunFreq: number,
  bom: [{
    // ... existing
    shouldCost: { material, labor, otherProc, ohPct, marginPct },  // P2
    backupSuppliers: [...],  // existing, used by P6
  }],
}

state.supplierProfiles = {  // P2 — keyed by supplierName
  [name]: { quality, otd, reliability, hedged, currency, contractType, paymentTerms, hedgeRatio, startDate, endDate, notes }
}

state.workingCapital = {
  // ... existing
  paymentEvents: [...],  // P15 (Round 2)
}
```

## Helper functions added in Round 3

```js
// All in <script type="text/babel"> block, top-of-file
shelfLifeToPeriods(days, planning)  // floor(days / daysPerPeriod), max(0, ...)
effectiveShelfDays(days, planning)  // periods × daysPerPeriod (UI hint of rounding loss)
milkRunPerPeriod(prod)              // mode-dependent per-period cost contribution
SectionInfo                         // <span> with click/hover info popup
```

## Solver pipeline diagram

```
[index.html JS] --(/api/forecast)--> forecast.py     # P3
[index.html JS] --(/api/solve/procurement)--> procurement.py  # main MILP
[index.html JS] --(/api/solve/profitmix)--> profitmix.py
[index.html JS] --(/api/solve/transport)--> transport.py
                ... etc                        # see app.py:21-33 for full list
```

`app.py` imports use `from solvers.<module> import ...` — but actual files live at repo root with `__init__.py`. Deployment must ensure the package is importable as `solvers` (likely via PYTHONPATH or rename on Render — verify before P4 if anything backend-touching breaks).

## Resume checklist for next session

1. Read this section of ARCHITECTURE.md.
2. Run `node -e ...` JSX validator (snippet in conversation history) — confirm `index.html` parses.
3. Run `python3 -c "import ast; ast.parse(open('procurement.py').read())"` for each Python file.
4. `git status` should show 5 modified files (index.html, procurement.py, profitmix.py, app.py, .gitignore, requirements.txt) + new file (forecast.py) + ARCHITECTURE.md modifications.
5. Pick up at P4 — see "P4 subtasks" above.
6. **Don't redo P1-P3** — they're complete. State and helpers are in place; just keep adding.

## Things NOT to forget

- **Currency**: always use `state.config.currency` — never hardcode `₹` (per Section 1 of this doc).
- **Single source of truth**: solver outputs are read from canonical paths (e.g. `state.solverResults.procurement.products[k].production`, NOT a fabricated top-level array).
- **Holidays + horizon_start_date**: every procurement payload sends both. Don't drop them when modifying payloads.
- **Decimals**: `NumInput` accepts step/min/max — use `step="0.01"` for currency, `step="1"` for unit counts, `step="0.1"` for percentages.
- **Reducers**: when adding new dispatch types, place near similar reducers (e.g. SUPPLIER_PROFILE next to SUPPLIER_WEIGHTS).
- **JSX validation**: every meaningful edit should be followed by the `@babel/parser` validation snippet. Don't ship without parsing.

---

*End of Round 3 resume log. Update this section as P4-P9 land so the document stays current.*

---

## Round 3 Post-Audit — wh_max + landed_cost + retail/subcontract bypass

After P9 the user requested an audit of solver wiring for the 4-mode warehouse capacity (FG vs RM) and an evaluation of retail-only / subcontract-only SKUs. Three real gaps were found and fixed:

### Gap 1 — FX hedging didn't reach procurement / Monte Carlo

**Found**: `landed_cost` was only consumed in `profitmix.py`. `procurement.py` and `montecarlo.py` were minimising against raw `b.cost` (supplier currency, no FX hedge, no freight/duty).

**Fixed**:
- All 10 procurement / MC / sensitivity payload sites now send `landed_cost` per BOM row alongside `cost`.
- `procurement.py:144` and `montecarlo.py:53` now prefer `landed_cost` when present, fall back to raw `cost` for older payloads.
- Smoke-tested: importing a `landed_cost: 85` part now raises `material_purchase` in the cost breakdown to ~9000 (vs ~120 raw) — FX hedge correctly flows.

### Gap 2 — RM warehouse only had per-part units cap (no 4-mode)

**Found**: `wh_max` 4-mode (units/area/volume/unlimited) shipped in P7 was FG-only. RM cap was just per-part `b.rmCapacity` in units.

**Fixed**:
- Setup → Budget block now has a second selector for RM mode + RM area / volume limit inputs.
- Per-BOM-row `b.rmFootprintArea` (m²/u) + `b.rmFootprintVolume` (m³/u) added with sensible defaults (0.05 / 0.02).
- `procurement.py` reads `params.rm_wh_mode` + `rm_wh_limit_area` + `rm_wh_limit_volume` and adds an aggregate constraint per period:
  - `area` → `Σ rm_inv[gidx, t] × rm_footprint_area[gidx] ≤ rm_wh_limit_area`
  - `volume` → similar with rm_footprint_volume
  - `units` / `unlimited` → no aggregate (per-part cap remains).
- Smoke-tested: aggregate area cap of 50 m² holds against a 2-part BOM with footprints 1 + 2 m²/u.

### Gap 3 — `prodMode='retailer'` was UI-only; subcontract-full didn't exist

**Found**:
- `prodMode='retailer'` rendered in the dropdown but solver treated the SKU as manufactured.
- Subcontract was only at part level (`b.subcontract`); no SKU-level "this whole SKU is subcontracted" mode.

**Fixed (UI + JS bypass)**:
- New `prodMode='subcontract-full'` option.
- New per-SKU fields: `prod.purchaseCost` / `prod.purchaseLT` (retailer); `prod.subcontractFullRate` / `prod.subcontractFullLT` (subcontract-full). Conditionally rendered when prodMode is one of these.
- New JS helpers `effectiveCapacity / effectiveSetupCost / effectiveVariableCost / effectiveBom` adapt the SKU payload:
  - capacity → 999999 (unbounded)
  - setup_cost → 0 (no batching)
  - variable_cost → original VC + buy-in cost (purchaseCost or subcontractFullRate)
  - parts → `[]` (BOM excluded)
- `prod_mode` is also sent so future solver-side logic can branch (currently informational).
- Applied to the main solver dialog procurement payload + SolverPipelineTab procurement + montecarlo.
- Smoke-tested: retailer SKU with VC=50, demand 30×12 returned status=Optimal, fill_rate=100%, total_cost=18000 (= 50 × 360u, no setup or BOM cost).

### Side effect

The `landed_cost` injection used a generic anchor `name:b.name,cost:b.cost,qty_per:b.qtyPer,` (10 occurrences) so all procurement-adjacent payloads get the FX hedge by default — including the lot-sizing and shadow-price replicas.

### Still NOT solver-wired (intentionally deferred)

- **Scenario programming** (P8): saved scenarios still need a per-type perturbation pipeline (supply-delay → leadTime, price-spike → cost_event, etc.). The hooks are in place; needs a future round.
- **HMM regime detection** (P6): low-vol vs high-vol price-time-series classification. Volatility z-score covers the immediate need.
- **Center-of-gravity ML** (P9): k-means + ML weighting needs traffic-pattern history we don't capture.

