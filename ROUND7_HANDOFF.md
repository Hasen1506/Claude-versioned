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

## A-7. What shipped in Round 13.6 (Tab 4 Phase 1a/1b — Backend wiring)

**Working file sizes after R13.6:** `index.html` script block ≈ 1,291,407 bytes
(R13.5: 1,288,899; net +2.5KB — three frontend payload helpers + per-line cycle/OEE
fields). `profitmix.py` +20 lines (per-(SKU, line) cycle + line OEE in capacity
constraint, OEE-derated utilization in result extraction, `cycle_hrs_per_unit`
echoed per-SKU). `production.py` +33 lines (`_line_oee` + `_cycle_min_by_sku`
helpers, routing-free path now uses cycle_time_by_sku_min × hrs × OEE / ct,
routing path now uses line.oee instead of product.oee). `procurement.py` unchanged
(does not consume cycle time or OEE).

### A-7.1 — Why R13.6 was needed

Phase 1a (R13) and Phase 1b (R13.5) shipped frontend-only — `resolveCycleTime`,
`resolveLineOEE`, and the new `skuMap` registry/topology integration all lived in
`index.html` only. The backend solvers continued to read scalar product-level
`cycle_time` and `oee` from the payload, so per-line overrides + stage-sum cycle
times + Π-of-stage OEE never reached the LP/MILP — UI showed correct provenance
but the optimizer ignored it.

R13.6 closes that gap. It is purely backend wiring + matching frontend payload
fields. No new UI, no schema migration, no behavioral change for users who haven't
populated stage tables / skuMap / per-line cycle overrides (legacy payloads still
solve identically — backward compat verified).

### A-7.2 — R13.6.A4 · Per-(SKU, line) cycle time reaches profitmix

Frontend payload (`index.html:6217+` — profitmix block) now sends per line:
```js
cycle_time_by_sku_min: cycleMinByIdxForLine(l, state.products, _topo, _skuMap)
```
where the helper (`index.html:7689+`) is:
```js
function cycleMinByIdxForLine(line, products, topo, skuMap){
  const out={};
  const eligible=eligibleSkuIdxForLine(line, products, skuMap);
  eligible.forEach(k=>{ out[k]=resolveCycleTime(products[k], line, topo, skuMap).value; });
  return out;
}
```

`profitmix.py:251+` consumes it via `_cycle_hrs_for_line(k, line)` which divides
minutes by 60. Falls back to the scalar `cycle_times[k]` when the new field is
absent. The line-hours capacity constraint and the result-extraction utilization
both use this helper — they no longer disagree.

### A-7.3 — R13.6.A5 · Per-line OEE reaches both solvers

Frontend now sends `oee: resolveLineOEE(l, _topo).value` per line in both
profitmix and production payloads. Source is whatever the resolver decides —
`Π(stage.oeePct/100)` when `oeeMode==='auto'` and stages exist, A·P·Q when
`'manual'`, default A·P·Q otherwise.

`profitmix.py`: `line_cap_hrs = avail * weeks * oee` (was `avail * weeks` flat).
**Semantic shift**: profit-mix LP now operates on OEE-derated capacity. Older
payloads without `oee` default to 1.0 (no derate) — backward-compatible. The
result `line_allocation[i].oee` field is echoed for UI display.

`production.py:69+`: New `_line_oee(l, prod)` prefers `lines[l].oee` over
`prod.oee`. Used in both:
- Routing-bottleneck path (was `oee = prod.get('oee', ...)`)
- New no-routing path (computes capacity from `cycle_time_by_sku_min[k]` × hrs ×
  OEE / ct instead of falling back to flat `lines[l].capacity` immediately)

### A-7.4 — R13.6.A2 · skuMap-aware eligibility

Frontend helper `eligibleSkuIdxForLine(line, products, skuMap)` (`index.html:7689+`)
returns the **union** of `line.eligibleProducts` and skuMap entries pointing at
this line. Both profitmix and production line payloads now use it. When neither
field is populated, falls back to "all SKUs allowed" (preserves the pre-R12
default).

This is the link that makes Phase 1a's `skuMap` actually drive the solver. Before
R13.6 you could "Map SKU A to Line 2" in the UI and the LP would still ignore it
unless Line 2's `eligibleProducts` was also populated.

### A-7.5 — R13.6.A7 · Shared-stage IDs surfaced (informational)

Both solvers now receive `shared_stage_ids: [...]` per line (frontend helper
`sharedStageIdsOnLine`). `profitmix.py` echoes the list in `line_allocation[i]`.
`production.py` echoes it in `lines[i]` results. Neither solver yet treats
shared work-centers differently — the field is plumbed for the upcoming
Phase 3 "shared-stage as pooled capacity" change so the UI can mark the affected
lines once the math lands.

### A-7.6 — R13.6 verification

1. **Babel parse**: `index.html` parses clean at 1,291,407 bytes.
2. **Profitmix smoke (new fields)**: 2-SKU 1-line problem with `oee=0.7`,
   `cycle_time_by_sku_min={0:30, 1:60}`. Result: `Optimal`, 80hrs × 13wk × 0.7 =
   728 hrs available; A=330 units × 0.5hrs + B=264 × 1.0hrs = 429 hrs used.
   Cycle map overrode the product-level scalars (1.0, 1.5) — wiring confirmed.
3. **Production smoke (no routing path)**: same shape, `oee=0.5`, A required 100,
   B required 80, periods=4 → `Optimal`, line shows `oee:0.5`,
   `shared_stage_ids:['SH-PC']`, util 100%.
4. **Production smoke (routing path)**: `oee=0.5` echoed in line result (was
   previously product-level).
5. **Backward-compat**: old-style payloads (no `cycle_time_by_sku_min`, no `oee`)
   solve `Optimal` for both solvers. Profitmix returns identical profit to pre-R13.6
   when these fields are absent. ✓

### A-7.7 — R13.6 deferred

Phase 2 / Phase 3 / Phase 4 / Phase 5 — see § A-5.6.

One Phase-3 dependency surfaced during R13.6: the `shared_stage_ids` field
is now plumbed but unused in the solver math. When Phase 3 lands the pooled-
capacity constraint, it can read this field directly without further frontend
changes.

---

## A-6. What shipped in Round 13.5 (Tab 4 Phase 1b — Cycle-time + OEE provenance + parallelism cleanup)

**Working file sizes after R13.5:** `index.html` script block ≈ 1,288,899 bytes
(R13 baseline: 1,278,520; net +10.1KB). `procurement.py` unchanged. `production.py`
unchanged (already had `op.get('parallelism', 1)` so frontend payload removal is
backwards-compatible). No backend deltas.

### A-6.1 — Why R13.5 (Phase 1b)

R13 fixed registry↔topology drift (A1–A3). The next layer of confusion in Tab 4
was that **the same conceptual quantity had three different sources of truth**:

- **Cycle time** had three: explicit override → Σ stage cycleMin → product.cycleTime
  fallback. The resolver `lineCycleMin` returned only a number, so the UI couldn't
  surface which source was being used.
- **Line OEE** had three: explicit `oeeAvailability/oeePerformance/oeeQuality` fields
  on the line, weighted-average across stages, or hardcoded 76.6%. Users entered
  values into the line-level fields not realising stages also existed and that the
  derivation ignored their inputs in some paths.
- **`op.parallelism`** had been removed from the routing UI in v3.4 (per the
  comment "parallelism is more lines"), but the field was still serialized to the
  backend at `index.html:6168` even though no UI ever set it.

### A-6.2 — R13.5.A4 · `resolveCycleTime → {value, source, stageCount}` (`index.html:7641`)

New resolver replaces the old `lineCycleMin`. Returns:
```js
{ value: <minutes>, source: 'override' | 'stageSum' | 'productFallback', stageCount: <n> }
```

`lineCycleMin` is preserved as a thin scalar wrapper (`resolveCycleTime(...).value`)
so older call sites keep working unchanged. Card ⑥ (Line × Product cycle override)
now renders a per-cell provenance badge below each input:

- **override** (yellow chip) — cell explicitly filled
- **Σ N stages** (cyan chip) — derived from card ⑤ stage sequence; N = count of
  stages on the SKU's mapped sequence
- **fallback** (grey chip) — no stage mapping yet → `product.cycleTime`

Tooltips on each cell explain which source is in use and what would be used if
the cell were blanked. Card help text rewritten to explain the badges.

### A-6.3 — R13.5.A5 · `resolveLineOEE → {value, source, stageCount}` (`index.html:7660`)

New resolver replaces the old `lineOEE`. Returns:
```js
{ value: <decimal 0..1>, source: 'lineFields' | 'stageProduct' | 'default', stageCount: <n> }
```

Resolution priority:
1. `line.oeeMode === 'manual'` and A/P/Q filled → use `(A/100)·(P/100)·(Q/100)`
2. else if line has stages in card ③ → `Π(stage.oeePct/100)` (serial composition)
3. else if A/P/Q filled → use them
4. else → 0.85·0.92·0.98 = 76.6% legacy default

Card ② Line Registry surfaces the source as a chip in the Composite cell:
- **Manual A·P·Q** (yellow) — explicit override
- **Π N stages** (cyan) — derived from topology
- **default** (grey) — no info available

Auto/Man toggle button in the Composite cell flips `oeeMode`. When Auto and
stages exist, A/P/Q columns dim (opacity 0.45) with hover tooltip "Advisory:
stages exist on this line, so the Composite is derived from Π(stage.oeePct).
Toggle Manual to use this column."

**Migration safety:** The seed has `oeeAvailability:85,oeePerformance:92,oeeQuality:98`
which under the new Π formula would jump from showing 75% (old weighted avg) to
30.5% (Π across 4 stages with oeePct of 78/72/68/80). To prevent that surprise
for users with persisted state, the seed and `addLine` now include
`oeeMode: 'manual'`, and a one-shot mount-time migration in `App` sets
`oeeMode: 'manual'` on any persisted line that has explicit A/P/Q but no
`oeeMode`. Users opt into stage-derived OEE by clicking the Auto button.

### A-6.4 — R13.5.A7 · Shared-stage changeover banner (`index.html:8085+`)

Card ⑦ (Changeover Matrix) now detects when any line in the topology has a
stage tagged to a shared work-center (`stage.sharedStageId` set). If so:

- A yellow banner at the top of the card explains the limitation: per-line
  changeover entries treat the swap as if only the host line was affected, but
  a real changeover at a shared booth (e.g. powder coat) blocks every line that
  consumes from the pool. Phase 3 (D-series) will split per-line vs per-pool
  changeover into separate fields.
- Each affected line's section header shows a "shared N" chip with the count
  of shared-stage members and a tooltip listing which stages are pooled.

This is a **transparency note**, not a functional change. The solver still uses
the per-line matrix; users can now see when that's likely an upper bound.

### A-6.5 — R13.5.A6 · `op.parallelism` removed from frontend payload (`index.html:6168`)

Profit-mix solver payload no longer includes `op.parallelism`. The field was
never set by any UI control in v3.4 (the routing card creates ops without it
since R7), so this is a dead-code cleanup. `production.py` line 90 already had
`par = max(op.get('parallelism', 1), 1)` so the backend silently defaults to 1.
Routing-DAG comment at `index.html:2096` updated to drop `parallelism` from the
op-shape gloss with a Phase-1b note explaining v3.4 semantics: "parallel
production = more lines via skuMap.lineId, not stations within a line."

### A-6.6 — R13.5 verification

1. **Babel parse**: clean at 1,288,899 bytes.
2. **Cycle provenance**: with default seed (1 line, 4 stages, no SKU↔Line stage
   sequences in card ⑤ yet), all card ⑥ cells should render `fallback` chip
   showing 19 min/u. After adding a stage sequence in card ⑤, the same cells
   re-render as `Σ 4 stages` showing the sum. After typing into a cell, that
   cell re-renders as `override` with yellow tinting.
3. **OEE provenance**: default seed → Composite shows 76.6% with `Manual A·P·Q`
   chip (because of `oeeMode:'manual'` migration). Click "Auto" → Composite
   recomputes to 30.5% with `Π 4 stages` chip and A/P/Q columns dim. Click
   "Man" → reverts to 76.6%.
4. **Shared-stage banner**: default seed has S3 Powder Coat → SH-PC shared.
   Card ⑦ shows yellow banner + "shared 1" chip on Line 1's section.
5. **No regressions**: profit-mix solver, procurement solver, production solver
   all still produce identical outputs (resolver shims preserve the scalar
   contract; payload `parallelism` field removal triggers backend default to 1
   which was the only value ever sent).

### A-6.7 — Deferred (still open after R13.5)

Phase 2 / Phase 3 / Phase 4 / Phase 5 — see § A-5.6 below.

One small Phase-1b carryover that did NOT ship: **merging cards ⑥ + ⑦ into a
single "Line × Product Throughput Matrix"** as the original plan suggested.
On reflection, the two cards have very different shapes (⑥ is SKU × Line with
a default column; ⑦ is per-line, SKU × SKU) so a forced merge would compress
two clear matrices into one cluttered one. The provenance badges already
solve the "where does the number come from" problem without merging the cards.
If a user asks for the merge later, the resolver functions are now in place to
support it cleanly.

---

## A-5. What shipped in Round 13 (Tab 4 Phase 1a — UI coherence)

**Working file sizes after R13:** `index.html` script block 1,278,520 bytes
(R12 baseline: 1,272,848; net +5.6KB). `procurement.py` unchanged at 1,639 lines.
No backend changes this round.

### A-5.1 — Why R13 was scoped narrow
The user dropped a ~19-concern brain-dump on Tab 4 (Production) covering UI
inconsistencies, missing workforce/asset/solver semantics, and a request for a
Cartesian-style live MILP playground. Doing all of it in one round would have
been ~5× a normal round. The user confirmed full scope (A+B+C+D + live
playground), but Phase-1 exploration showed every later phase reads from the
line registry → topology drift would propagate downstream. **R13 = Phase 1a
only**: pure UI coherence, no schema migrations, no solver changes. The
remaining phases are tracked in section A-5.5 below.

### A-5.2 — R13.A1 · Net hrs/week info icon (`index.html:7910`)
Added a `SectionInfo` popover next to the Net hrs/wk cell in the Line Registry
table. Shows the live formula:

```
Net hrs/day = (shifts × hrs/shift) − (breakMins × shifts / 60)
            = (1 × 8) − (30 × 1 / 60) = 7.5 hrs/day
Net hrs/wk  = net hrs/day × workDays = 7.5 × 6 = 45 hrs/week
```

Numbers are computed per-line from `state.production.lines[*].{shiftsPerDay,
hoursPerShift, breakMins}` and `state.planning.workDays`. Reuses existing
`SectionInfo` component at `index.html:2982`.

### A-5.3 — R13.A2 · Registry ↔ Topology auto-sync
Three coordinated changes fixed the "Main Line vs Line 1" / "Line 2 doesn't
appear in topology" complaints:

1. **Seed alignment** at `index.html:2222` — topology line is now
   `{id:'line1', name:'Line 1'}` matching the registry seed at `index.html:2211`.
   Old seed had `{id:'L1', name:'Main Line'}` which never matched.

2. **App mount sweep** in `App` component at `index.html:15564` — for users
   whose persisted localStorage state still has the older mismatched ids,
   re-keys orphaned topology lines to match registry ids by index, preserving
   any stages they've defined. Idempotent, runs once per mount.

3. **`renameLine` helper** at `index.html:7829` — single function that updates
   the line name in BOTH `state.production.lines[]` (registry) AND
   `state.production.topology.lines[]` (topology) atomically via a single
   `SET_PRODUCTION` dispatch. Both UI inputs (registry table at `index.html:7895`
   and topology header at `index.html:7929`) call this helper, so renames can
   never drift again.

R12-and-earlier behavior of `addLine` / `delLine` already mirrored both arrays
(verified at `index.html:7810–7823`), so no changes needed there — only the
seed and rename paths were broken.

### A-5.4 — R13.A3 · SKU↔Line bidirectional summary (`index.html:7991+`)
Added two derived read-only summary strips above the existing "Map SKUs to
Lines" editor table:

- **Per line** (cyan badge): which SKUs are mapped to this line via `skuMap`.
- **Per SKU** (green badge): which line this SKU runs on (or `(unmapped —
  falls back to first line)` if no mapping exists).

Both strips re-derive on every render from `skuMap` + `topo.lines` — no new
state. A help-text banner above the strips clarifies that current schema
allows ONE line per SKU; multi-line concurrency is a Phase-2 deferral.

### A-5.5 — R13 verification matrix

| # | Change | Path | Verification | Result |
|---|---|---|---|---|
| 1 | Seed alignment | `index.html:2222` | grep shows `{id:'line1',name:'Line 1'` | ✓ |
| 2 | Mount-time sweep | `index.html:15564` | useEffect with `[]` deps; re-keys orphan topology lines | ✓ |
| 3 | renameLine helper | `index.html:7829` | grep shows single `SET_PRODUCTION` w/ both keys | ✓ |
| 4 | Registry rename input | `index.html:7895` | onChange calls `renameLine` | ✓ |
| 5 | Topology rename input | `index.html:7929` | onChange calls `renameLine` | ✓ |
| 6 | Net-hrs info icon | `index.html:7910` | SectionInfo with live numbers | ✓ |
| 7 | A3 bidirectional strips | `index.html:7991+` | Help banner + 2 grids | ✓ |
| 8 | Babel parse | full script block | 1,278,520 chars parsed cleanly | ✓ |

No backend changes; profitmix/procurement/production solvers unchanged.

### A-5.6 — Deferred (Phases 2 → 5 still open after R13.5)

(Phase 1b shipped in R13.5 — see § A-6 below.)

**Phase 2 — Workforce + Asset → Line wiring**
- B1–B5: New `state.production.workforce` branch (`salariedHeadcount`,
  `salariedMonthlyCost`, `hourlyHeadcountCap`, `otCapHrs`, `idleSalariedFlag`).
  New `state.config.laborCostMode: 'per_unit'|'hourly'|'salaried_idle'`.
  Per-stage `laborMode: 'machine'|'labor'|'mixed'`. Defaults preserve current
  behavior. Conflict banner when Tab 2 `laborPerUnit > 0` and mode is `'hourly'`.
- C1–C4: Optional `lineId`, `stageId` on assets at `index.html:10504`.
  Per-line depreciation roll-up echoed in line registry. "Componentise" prompt
  to create asset for stage's machines. Investment Decision tab consumes
  "expand line X" CapEx proposals.

**Phase 3 — Production solver semantics**
- D1: Write `/workspaces/Claude-versioned/PRODUCTION_MILP_SPEC.md` —
  per-solver verbal model: objective, decision vars, constraints, assumptions,
  explicit "does NOT model" list.
- D2: Demand-ceiling / MTO-floor toggle in Tab 3 + echo in Tab 4 ⑧.
- D3: Low-util shutdown recommendation — post-solve heuristic in
  `production.py` returning `{period, type:'shutdown', savings, rehire_cost}`.
- D4: CapEx expansion suggester — extends sensitivity card at
  `index.html:8171` with delta-margin + payback per scenario.
  New `/api/solve/production-sensitivity` endpoint.
- D5: Objective mode toggle — `profitmix.py` param
  `objective: 'profit'|'throughput'|'margin_per_hour'`.
- D6: Per-stage worker-vs-machine cost integration via Phase-2 `laborMode`.
- D7: Explicit MPS output card at top of Tab 4 (or promote to Tab 5).

**Phase 4 — Live MILP playground (Cartesian-style)**
- New tab id `'milplab'`. Three-pane: read-only Monaco showing current
  `.py` source / live JSON input panel / live result + shadow prices +
  binding constraints + LP gap + runtime + status.
- **Hard "no" on editable code → backend execution** — arbitrary Python
  upload to a Flask server running PuLP is RCE. Engineering cost of
  sandboxing dwarfs user value.
- Curated knobs only: M-big, time limit, gap tolerance, objective weights as
  form fields with hyperlinks into highlighted source spans.
- Backend: after `prob.solve()`, iterate `prob.constraints.items()` →
  emit `{name, slack, pi}`. New `/api/source/<solver>` and
  `/api/solve/<solver>?live=1` routes.
- Monaco loaded via CDN, not bundled.

**Phase 5 (optional) — Cartesian-specific lifts**
Deferred until the user can paste screenshots. Claude has no web access in
this session and cannot browse https://cartesian.app/.

---

## A-4. What shipped in Round 12 (Honest Bucket 4 cleanup + R11 backend deferrals)

**Working file sizes after R12:** `procurement.py` 1639 lines (R11 baseline: 1539);
`index.html` script block 1,272,848 bytes (R11 baseline: 1,271,815; net +1KB).

### A-4.1 — Why R12 was needed
After R11, the user pushed back on the Bucket 4 audit: "Complete pending
deferrals 1st then continue. I dont think bucket d was done accurately."
The honest re-audit found three Bucket 4 items mis-marked as shipped:

- **D1**: R11.D had ADDED a new SOURCE & SUPPLIER section but left the same
  Source / Supplier State fields ALSO present in the TAX section below ⇒
  duplicate inputs.
- **D2**: MPS Monthly view had inline actuals (line 12710) ✓ — but the spec
  also said "remove the separate card", and the standalone Actuals Entry
  matrix at line 5947 was kept (just re-badged).
- **D3**: MTO Orders card was inside Tab 2 product detail panel ✓ — but the
  spec said "adjacent to Product Parameters", and Fixed & Setup Costs sat
  between them.
- **D1 lead-time band** (small/mid/large qty) was carried as a deferral in
  R11.A-3.7. Never built.

R11 also documented two open backend deferrals: true period-flat charge
binary, and per-node UoM utilisation reporting.

### A-4.2 — R12.A · D1 dedupe (`index.html`)
Removed the duplicate `Source` (= supplierType) and `Supplier State` fields
from the BOM expanded panel TAX section. They live exclusively in the
SOURCE & SUPPLIER section above (added by R11.D). TAX section retains only
tax-specific fields (Total GST %, CGST/SGST split, IGST, BCD/SWS for
imports).

### A-4.3 — R12.B · D2 standalone Actuals Entry card removed
Replaced the Tab 3 standalone Actuals Entry matrix with a single
breadcrumb pointing to the MPS Monthly inline column. Sole canonical
input surface for actuals is now the MPS table; all breach + replan
controls already lived there.

### A-4.4 — R12.C · D3 MTO Orders relocated
MTO Orders card now sits DIRECTLY ABOVE Product Parameters in Tab 2 (was
above Fixed & Setup Costs ⇒ Product Parameters). New order: BOM → Costs →
Forecast / Demand → Fixed & Setup Costs → **MTO Orders** → Product
Parameters.

### A-4.5 — R12.D · Lead-time band step-function (FE + BE)
**Frontend** ([index.html:4945+](index.html#L4945)) — new LEAD-TIME BAND
section in BOM expanded panel under PROCUREMENT:
```
Lead Time (wk)   — scalar fallback (used when smallMax = 0)
Small Max (qty)  — upper bound for SMALL band
Small LT (wk)    — lead time when qty ≤ smallMax
Mid Max (qty)    — upper bound for MID band
Mid LT (wk)      — lead time when smallMax < qty ≤ midMax
Large LT (wk)    — lead time when qty > midMax
```
Stored on BOM row as `b.ltBand = {smallMax, smallLt, midMax, midLt, largeLt}`.
Payload key `lead_time_band: {small_max, small_lt, mid_max, mid_lt, large_lt}`,
null when band disabled.

**Backend** ([procurement.py:401-422](procurement.py#L401-L422), receipt
cascade rewrite at [procurement.py:1080-1160](procurement.py#L1080-L1160)):
- Per-(part, period) sub-vars: `a_small`, `a_mid`, `a_large` (Integer ≥ 0)
  + binaries `b_small`, `b_mid`, `b_large` (declared only when band active).
- Constraints:
  - `a_small + a_mid + a_large == r[gidx, t]` (qty conservation)
  - `b_small + b_mid + b_large == o[gidx, t]` (one band per PO event)
  - `a_small ≤ small_max × b_small`
  - `a_mid ≤ mid_max × b_mid`
  - `a_large ≤ max_order × b_large`
  - `a_mid ≥ (small_max + 1) × b_mid` (mid band qty must exceed small_max)
  - `a_large ≥ (mid_max + 1) × b_large` (large band qty must exceed mid_max)
- Receipt cascade replaces `arrive_t = t − lt` with band-aware sum:
  `arrived = a_small[t−small_lt] + a_mid[t−mid_lt] + a_large[t−large_lt]`
- Backward compat: when `lead_time_band` is null OR small_max ≤ 0, scalar
  `lt` path applies (legacy behavior preserved).

### A-4.6 — R12.E · True flatPeriodic with activation binary (`procurement.py`)
Closed R11 deferral A-3.7 #1. Old behavior charged the flat fee once per
PO event via `o[g,t]` — when a single contract had multiple parts, each
part's PO triggered an independent flat fee in the same period. New
formulation aggregates per (contract_id, period):

- During the per-part objective loop, flatPeriodic entries are deferred
  to a `flat_periodic_pending` list (no per-part cost added).
- After the loop, entries are grouped by (contract_id, period). For each
  group, declare ONE binary `pflat[contract_id, t]` and link via
  `pflat ≥ o[gidx, t]` for every part using that contract. Charge
  `base_rate × pflat` ONCE per (contract, period).
- Result: a contract attracts exactly one flat fee per period regardless
  of how many parts on it order. Smoke test (P3 — 2 parts on TC1) pays
  the flat fee once per active period instead of twice.

### A-4.7 — R12.F · Per-node UoM utilisation reporting (`procurement.py`)
Closed R11 deferral A-3.7 #2. After the solve, for each storage node
emit a `node_uom_utilisation` block in `meio_summary`:

```python
{
  '<node_id>': {
    'caps': {'units': N, 'kg': N, 'm3': N, 'L': N},
    'per_period': [{'period': t, 'units': u, 'kg': k, 'm3': m, 'L': l,
                    'units_pct': p, 'kg_pct': p, 'm3_pct': p, 'L_pct': p}, ...],
    'peak_units_pct': max,
    'peak_kg_pct': max,
    'peak_m3_pct': max,
    'peak_L_pct': max,
  },
  ...
}
```

Caps from `node.storage_cap_*`; per-period inv from `pulp.value(inv_node[k,n,t])`;
weights / volumes from `products[k].fg_weight_kg_per_unit` / `fg_volume_m3_per_unit`
(BOM rollup, R11.A). UI can render a per-node, per-UoM heatmap directly.

### A-4.8 — Verification (R12)
Babel parse ✓ at 1,272,848 bytes. Python smoke matrix:

| # | Path | Status | Cost |
|---|---|---|---|
| 1 | Legacy bare-bones (no R8/R9/R10/R11/R12 keys) | Optimal | ₹2,695.36 |
| 2 | R12 `lead_time_band` only | Optimal | ₹2,739.76 |
| 3 | R12 flatPeriodic + activation binary, 2 parts share TC1 | Optimal | ₹3,721.81 |
| 4 | R12 per-node UoM utilisation reporting | emitted (2 nodes, peak ≤60% m³) | n/a |
| 5 | R12 all features together (band + flatP + UoM caps) | Optimal | ₹2,848.37 |

All paths Optimal · cost deltas match expectations · backward compat
preserved (legacy bare-bones identical to pre-R12 cost).

### A-4.9 — Remaining R12 deferrals
None opened. R12 closed all four R11 backend deferrals + four Bucket 4
items the user flagged as inaccurately marked.

---

## A-3. What shipped in Round 11 (Pending deferrals from R10 + Bucket 4 polish)

**Working file sizes after R11:** `procurement.py` 1539 lines (R10 baseline: 1485);
`index.html` script block 1,271,815 bytes (R10 baseline: 1,267,815; net +4KB).

### A-3.1 — Why R11 was needed
R10 closed the R8/R9 backend gap but documented three explicit deferrals
(per-node UoM caps, `flatPeriodic` basis, tighter min-charge). The user
followed up: "Complete pending deferrals 1st then continue". R11 closes
all three plus the residual Bucket 4 (UX cleanup) items.

### A-3.2 — R11.A · Per-node UoM-aware FG storage caps (procurement.py)
`network_nodes[]` payload now ships `storage_cap_units / storage_cap_kg /
storage_cap_l / storage_cap_m3` per node (rolled from `n.storageCapacity`
on the frontend; falls back to legacy `unitCapacity` / `capacity` when
absent). Per-product `fg_weight_kg_per_unit` and `fg_volume_m3_per_unit`
are rolled up from BOM (Σ `b.qty_per × b.weight_kg / b.volume_cbm`).

The MEIO node-cap block (post-balance) now emits up to **4 LP
constraints per (node, period)**:
```python
prob += Σ inv_node[k,n,t] <= cap_units              # MEIO_NodeCap_units
prob += Σ fg_weight_by_k[k] * inv_node[k,n,t] <= cap_kg   # MEIO_NodeCap_kg
prob += Σ fg_volume_by_k[k] * inv_node[k,n,t] <= cap_m3   # MEIO_NodeCap_m3
prob += Σ fg_volume_by_k[k] * 1000 * inv_node[k,n,t] <= cap_l  # MEIO_NodeCap_l
```
Each cap > 0 is honored; 0 = unconstrained in that dimension.
Backward-compat: legacy `capacity` field still works when no UoM caps set.

### A-3.3 — R11.B · `flatPeriodic` rate basis (procurement.py)
The transport-cost block now recognises `basis == 'flatPeriodic'` and
treats `base_rate` as a flat per-PO charge (mapped to `o[g,t]`). Approximation
ack: a true period-flat fee would need a per-period activation binary;
mapping to `o[g,t]` charges per PO instead — small inflation when multiple
POs land in one period, accepted as known limitation.

### A-3.4 — R11.C · Tighter min-charge enforcement via slack-var (procurement.py)
Replaced the per-basis if-elif min-charge logic with a unified slack-var
formulation that works for ALL rate bases:
```python
eff_charge = pulp.LpVariable(f'tcost_{gidx}_{t}', lowBound=0)
if per_unit_rate > 0: prob += eff_charge >= per_unit_rate * r[gidx,t]
if per_po_rate > 0:   prob += eff_charge >= per_po_rate   * o[gidx,t]
if min_ch > 0:        prob += eff_charge >= min_ch        * o[gidx,t]
obj.append(eff_charge)
```
The LP minimizes `eff_charge`, so the **tighter** of the three bounds binds.
Min-charge now correctly floors the per-shipment cost regardless of basis
(previously only `perTrip` honored min_charge).

### A-3.5 — R11.D · Bucket 4 UX cleanup status
Audit found **D1, D2, D3, D4 already shipped via R8 + R9** (the deferral
list at R10's end didn't reflect what was actually present in code):
- **D1 (BOM inline accordion)** — line 4888 `b._expanded` block already
  renders inline detail panel below row with PROCUREMENT / TAX / LOGISTICS
  / VOL-DISC TIERS / TRANS-RATE TIERS / BACKUP SUPPLIERS sections. R11
  added a top-of-panel **SOURCE & SUPPLIER** mini-section (Supplier name,
  Type, State, Source Location FK, Subcontract toggle, Subcontract Rate /
  LT) so source info is visible without scrolling.
- **D2 (Inline actuals in MPS)** — line 12689 monthly view already has
  actual qty as editable input column with live on-hand cascade.
- **D3 (MTO entry consolidation)** — line 3475 Order Book card in Tab 1
  consolidates orders read-only across products; line 5169 keeps editing
  in Tab 2 product detail (intentional — orders need a product).
- **D4 (Promote ordering-cost out of gear icon)** — line 4898 already has
  inline ▾ open button (R8 / B6) replacing the gear-icon prompt-chain.

### A-3.6 — Verification (R11)
Babel parse ✓ at 1,271,815 bytes. Python smoke matrix:
| # | Path | Status | Cost |
|---|---|---|---|
| 1 | Legacy bare-bones (no R8/R9/R10/R11 keys) | Optimal | ₹11,552 |
| 2 | R10 horizon controls only | Optimal | ₹11,552 |
| 3 | R11.A multi-UoM node caps active | Optimal | ₹11,106 |
| 4 | R11.B flatPeriodic basis | Optimal | ₹11,757 |
| 5 | R11.C tonneKm + min_charge slack-var binding | Optimal | ₹15,388 |

All paths solve to Optimal · backward compatibility preserved · cost deltas
match expected behavior (R11.A allows tighter inventory; R11.B adds flat
fee per PO; R11.C floors freight per shipment).

### A-3.7 — Remaining deferrals after R11
- True period-flat charge for `flatPeriodic` would need a per-period
  activation binary (current approach is per-PO via `o[g,t]`).
- Per-node, per-UoM **kg/L/m³ output reporting** — solver applies caps
  but doesn't emit a per-node weight/volume utilisation table (UI shows
  aggregate fill estimates only).
- Bucket 4 D1 sub-spec "Lead-time band (small/mid/large qty)" — would
  need a step-function on lead time per PO size; not built.

---

## A-2. What shipped in Round 10 (Backend wiring for R8/R9 — `procurement.py`)

**Working file size after R10:** `procurement.py` 1485 lines (R9 baseline: 1328).
**Frontend payload size after R10:** index.html script block 1,267,815 bytes
(R9 baseline: 1,266,505; net +1.3KB — minimal because R8/R9 already shaped most fields).

### A-2.1 — Why R10 was needed
R8 (Bucket 2 — transport coherence) and R9 (Bucket 3 — horizon controls)
shipped UI + payload-only. The Python solver `procurement.py` ignored every
new key. The user flagged this directly: "All 3 buckets and you are
explicitly marking implemented only on UI, wtf?". R10 closes the loop.

### A-2.2 — `procurement.py` param parsing block (top, after legacy parse)
- New params (with safe defaults so legacy payloads still solve):
  `committed_periods`, `effective_periods`, `horizon_buffer`,
  `enable_terminal_anchor`, `enable_min_coverage`,
  `transport_modes`, `transport_contracts`, `transport_disruptions`,
  `default_lane_km`, `transport_fill_threshold`.
- New helper closures (Python ports of the JS R8 helpers):
  - `_qty_in_uom(part, qty, uom)` ≡ JS `partQtyIn`
  - `_shipment_cost(part, qty, distance_km, mode, contract)` ≡ JS `transportShipmentCost`
  - `_pick_mode(part, qty)` ≡ JS `pickTransportMode` (with disruption fallback)
- T (horizon length for MILP) is SET TO `effective_periods` when supplied —
  the solver "sees" buffer demand. `T_committed` defines the output window.

### A-2.3 — Per-part R10 fields read in BOM loop
Added to `all_parts.append({...})`:
- `terminal_anchor_units` (R9 / C1.b)
- `min_coverage_periods` (R9 / C1.d)
- `default_trans_mode_code`, `fallback_trans_mode_code`,
  `transport_contract_id`, `source_location_id`, `distance_km`,
  `weight_kg`, `volume_cbm`, `density_kg_per_l` (R8 / B3-B5)

### A-2.4 — Terminal-anchor MILP constraint (R10.3)
```python
if enable_terminal_anchor:
    ta = float(part.get('terminal_anchor_units', 0) or 0)
    if ta > 0:
        anchor_t = max(0, T_committed - 1)
        prob += rm_inv[gidx, anchor_t] >= ta, f"TermAnchor_{gidx}"
```
Anchored at `T_committed - 1` (NOT `T - 1`) so the buffer window doesn't
dilute the anchor. Without this, MILP drives ending inv → 0 even when the
buffer is present.

### A-2.5 — Min-coverage MILP constraint (R10.4)
```python
if enable_min_coverage:
    mcp = int(part.get('min_coverage_periods', 0) or 0)
    if mcp > 0:
        cov_min = float(avg_demand_per_t * effective_qty * mcp)
        if cov_min > 0:
            prob += r[gidx, t] >= cov_min * o[gidx, t], f"MinCov_{gidx}_{t}"
```
Per-period: each PO must cover ≥ `avg_demand × min_coverage_periods × qty_per`
in recipe-uom. Suppresses tiny tail-end POs.

### A-2.6 — Mode-aware transport cost (R10.5)
After the legacy tier/freight objective terms, when a part has
`transport_contract_id` wired to a known contract:
- **tonneKm**: `per_unit_rate = base_rate × km × (weight_kg / 1000)`
- **m3Km**: `per_unit_rate = base_rate × km × volume_cbm`
- **unitKm**: `per_unit_rate = base_rate × km`
- **perTrip**: `per_po_rate = base_rate` (added to `o[g,t]` coefficient)
- **flatPeriodic**: skipped (handled at periodic level — TODO)
Then: `obj.append(per_unit_rate × r[g,t])` and/or `obj.append(per_po_rate × o[g,t])`.
`min_charge` enforced as a per-PO floor when basis is perTrip.
**Additive to legacy `trans_rate`** — to avoid double-count, set
`b.trans_rate=0` OR use the UI's "↺ Freight from mode" button (R9 / C1.e).

### A-2.7 — Output trimming to T_committed (R10.6)
`T_out = min(T_committed, T)`. All result extraction loops now use
`range(T_out)` instead of `range(T)`:
- `prod_schedule`, `inv_levels`, `shortages`, `setups` per product
- `node_inventory`, `lane_flows`, `lane_in_transit` (MEIO)
- `orders`, `rm_levels`, `order_flags`, `po_list` per material
Top-level result returns `'periods': T_out` plus the new diagnostic keys
`effective_periods`, `committed_periods`, `horizon_buffer`,
`r10_terminal_anchor`, `r10_min_coverage`. PO releases scheduled in the
buffer window are simply not emitted.

### A-2.8 — Frontend payload now sends transport state (R10.7)
The procurement payload at the Command Center call site now includes:
- `transport_modes[]` from `state.transportModes` (id, code, name, rate, truck caps)
- `transport_contracts[]` from `state.transportContracts` (id, basis, mult, min_charge)
- `transport_disruptions[]` from active `state.disruptions` filtered to mode-scope
- `default_lane_km` and `transport_fill_threshold` from config
And per-BOM:
- `default_trans_mode_code`, `fallback_trans_mode_code`,
  `transport_contract_id`, `source_location_id`, `distance_km`,
  `weight_kg`, `volume_cbm`, `density_kg_per_l`

### A-2.9 — Verification (R10)
- Babel parse ✓ at 1,267,815 bytes
- Python `import procurement` ✓
- Smoke solve with R10 toggles ON: `Optimal`, periods returned = 10
  (committed), effective = 12, buffer = 2, both r10 flags True, total cost ~₹13,330
- Legacy payload (no R10 keys): `Optimal`, periods = 8, total cost ~₹353
  → backward compatible

### A-2.10 — Known limitations / deferred from R10
- **Per-node UoM-aware storage caps** from `state.network.nodes[i].storageCapacity`
  ({units, kg, L, m³}) are NOT enforced as per-node MILP constraints in R10.
  R6 MEIO uses an aggregate cap; we still send `network_nodes[].capacity`
  via existing MEIO path. Per-UoM, per-node caps deferred to R11.
- **`flatPeriodic` rate basis** is ignored in objective (would need a
  periodic charge variable). Documented; not wired.
- **Min-charge for non-`perTrip` bases** is approximated; tighter min-charge
  enforcement would need a slack variable per PO.

---

## A-1. What shipped in Round 9 (Bucket 3 — Solver / Forecasting / Horizon coherence)

**Working file size after R9:** 1,266,505 bytes (R8 baseline: 1,232,850; net +33KB).

### A-1.1 — C1.a · Effective horizon vs committed horizon
- New helpers: `maxBomLeadTimePeriods(state)`, `effectiveHorizonInfo(state)`,
  `padDemandToLength(arr, L, history)` — top-level near `periodCount`.
- `state.planning.useEffectiveHorizon: false` (default), `eoqBufferPeriods: 2`.
- Tab 1 Setup gets a new "🛡️ End-of-Horizon Distortion Controls" mini-card
  with 4 toggles + live committed/buffer/effective chip.
- Procurement payload `params.periods = effective` when ON; sends
  `committed_periods`, `effective_periods`, `horizon_buffer` so backend (or
  post-processing) can hide buffer-period POs.
- Demand arrays padded with SES forecast (NOT zeros — zero-padding causes its
  own distortion).

### A-1.2 — C1.b · Terminal inventory anchor
- Helper `terminalAnchorUnits(part, product, state)` =
  `SS_part + avg_part_demand × LT_periods`. Uses existing
  `safetyStockUnits` + `effQtyPer`.
- Toggle `state.planning.enableTerminalAnchor` (default OFF). When ON, each
  BOM part in the procurement payload carries `terminal_anchor_units`.

### A-1.3 — C1.c · Setup cost as fixed-charge in MILP (verified)
- `procurement.py:438` (product setup): `obj.append(setup_series[t] * y[k,t])`
- `procurement.py:529` (part ord cost): `obj.append(part['ord_cost'] * o[gidx,t])`
- Both binary-indicator-anchored. **No code change needed** — formulation
  was already correct. Verification documented here for future audits.

### A-1.4 — C1.d · Min-coverage gate
- Per-part `b.minCoverageDays` field added in BOM editor (PROCUREMENT block,
  default 0 = no gate).
- Toggle `state.planning.enableMinCoverageGate` (default OFF). When ON, each
  BOM part's `min_coverage_periods = ceil(minCoverageDays / periodDays)` is
  sent in the payload.

### A-1.5 — C1.e · Composite mode-dependent ordering cost
- BOM ordBreakdown editor (R8 B6) gains a "↺ Freight from mode" button that
  pulls `freightFixed` from the chosen transport mode + contract via
  `transportShipmentCost(...)` helper (R8 B4). Bridges B2/B3 contracts to
  lot-sizing.

### A-1.6 — C2 · MTO + MTS hybrid per SKU
- Helpers `mtoQtyByPeriod(product, planning)` and `effectiveDemand(...)`.
  Hybrid mode opt-in per product via `prod.mtoOnTop = true`.
- MTO orders distribute by `dueMonth` to the matching grain-period
  (mid-month placement for weekly/daily).
- Tab 2 MTO card has a hybrid toggle + live total breakdown (MTS + MTO = total).
- Procurement payload's `weeklyDemand(p)` now uses `effectiveDemand`.

### A-1.7 — C3 · Lost-sales proxy (simple, not Tobit)
- Helper `inferredLostSales(product, planning)`: when actual/forecast < 0.7,
  treats the gap as inferred lost sales. Returns `{byPeriod, total, count}`.
- New "🩸 Lost Sales (Proxy)" card on Tab 9 Analysis showing per-product:
  periods with lost, total units, lost revenue, % of demand.
- Threshold (0.7) is heuristic — not a statistical inference. True Tobit /
  censored-demand estimator deferred indefinitely (see section E).

### A-1.8 — C4 · Drift-detector-light + retrain cadence
- Helper `detectDriftLight(product, planning, opts)`. Compares last-N
  residual std-dev to historical std-dev. Ratio > 1.5 → flags drift.
- Per-product fields: `retrainCadence` (daily/weekly/monthly),
  `lastRetrained` (ISO date).
- Tab 3 forecast competition card gets a drift chip with cadence selector
  and "↻ Retrain Now" button. Button POSTs to `/api/forecast/retrain`
  (already accepts `{sku_id, cadence}`).

### A-1.9 — C5 · Demand-sensing breach chip + sigma explainer
- Helper `countSensingBreaches(state)` — # SKUs with last-window deviation
  > k×σ or > pct% (lightweight version of MPS sensing logic).
- Masthead chip "📡 SENSE × N" appears when breaches > 0; click → jump to
  Tab 9 Analysis. Hidden when 0.
- Tab 9 Demand Sensing card gets a "📐 Why 2σ?" explainer paragraph
  citing α, threshold, full-resolve cadence (`sensingResolveAfter`).

### A-1.10 — C6 · Tab 4 MPS unified drill-down
- New 4th `mpsGran` mode `'unified'` alongside monthly/weekly/daily.
- Single hierarchical table: month rows → click ▸ to expand into 4 weeks →
  click ▸ on a week to expand into `workDays` days. Reuses existing
  `expandedWeek` state + new `expandedMonth` state.
- Working-day rendering skips weekends + holidays via parent calendar logic.

### A-1.11 — C7 · Lifecycle curve clarification
- Tab 3 Lifecycle Curve card now shows a 5-stage flow diagram:
  History → Statistical → Lifecycle × → Promo → Override → Consensus.
- Override-conflict gate: warns when override exists in a period with
  lifecycle ≠ 1.0 (override replaces, not multiplies — design intent).
- Card title gains "(Forecast Pipeline · stage 3 of 5)" to set context.

### A-1.12 — C8 · Solver result transparency panel
- New "🔍 WHAT THE SOLVER SAW" card under Command Center Results Summary.
- 8 transparency tiles: procurement budget used/cap, WC binding,
  logistics mode + over-spend, R9/C1 horizon, terminal anchor, min-coverage
  gate, active disruptions count, MTO+MTS hybrid SKU count.
- Reads `state.solverResults` + `eh` + state toggles. Empty fields mean
  backend didn't echo that key back.

### A-1.13 — Top-level helpers added (R9)
- `maxBomLeadTimePeriods(state)` → number
- `effectiveHorizonInfo(state)` → `{committed, buffer, effective, maxLT, eoqBuf, enabled}`
- `padDemandToLength(arr, L, history)` → array (SES-extended)
- `terminalAnchorUnits(part, product, state)` → number
- `mtoQtyByPeriod(product, planning)` → array
- `effectiveDemand(product, planning, rollingPatch)` → array
- `inferredLostSales(product, planning)` → `{byPeriod, total, count}`
- `detectDriftLight(product, planning, opts)` → `{drifted, recentStd, histStd, ratio, enoughData}`
- `countSensingBreaches(state)` → number

### A-1.14 — Verification (R9)
- Babel parse: ✓ at 1,266,505 bytes
- 6 smoke tests pass (effective horizon math, demand padding, MTO grain placement)
- All toggles default OFF — backward compatible. Existing payloads unchanged
  unless user opts in via Tab 1 controls.

### A-1.15 — Backend wiring status (✅ SHIPPED IN R10 — see section A-2)

R10 wired the previously frontend-only R8/R9 features into `procurement.py`.
Earlier R8/R9 commits sent the payload keys but the solver ignored them; R10
adds the actual MILP constraints + output trimming + transport-cost objective
terms.

### A-1.16 — NOT shipped in R9 (legitimately deferred)
- ML weather/exogenous-feature forecasting (parked indefinitely; section E1)
- True Tobit lost-sales estimator (parked; section E2)
- Air-fallback spot-market pricing (parked; section E3)
- True drift detector with concept-drift tests (parked; section E4)
- Per-node UoM-aware storage caps from `state.network.nodes[i].storageCapacity`
  enforced as MILP constraints (R10 sends the data only as MEIO `network_nodes`
  capacity; per-UoM caps still rely on legacy `rm_wh_mode` aggregate cap)

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

## C. Bucket 3 — Solver / Forecasting / Horizon coherence (✅ SHIPPED IN R9 — see section A-1)

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
