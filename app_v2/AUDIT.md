# app_v2 — Domain + UX Correctness Audit

**Date:** 2026-05-31 · **Reviewer role:** supply-chain domain expert + UI/UX expert
**Scope:** the new `app_v2/` build, reviewed against the live `index.html` (the
richer original) and the Flask solver backend, with the server actually running.

This is the **record-first** deliverable. It captures what is wrong or missing,
grounded in `file:line` evidence and (where possible) live backend tests — *before*
any fixing. It deliberately expands well beyond the issues raised verbally, with a
domain + UX lens. Nothing here changes `index.html` or solver logic.

---

## 0. The one root cause

`app_v2/` is a **presentation-layer reskin**. It ported `index.html`'s *screens*
but dropped `index.html`'s *domain engine* (Pillars 3/6/7/11/13/15 — landed cost,
holiday calendar, disaggregation, NPV, ordering-cost breakdown, payment ledger).
What replaced the engine is **mock data dressed up as live output**: global series
shown as if per-product, hardcoded numbers shown as if derived, and a solver status
board shown as if real.

So the app *looks* finished and *is* partly wired (the MILPs do call real solvers),
but the **inputs to those solvers, and most of what's on screen, are fabricated or
mis-bound.** A user who clicks through it will, as you said, "find tonnes of mistakes."

**Severity legend:** 🔴 correctness/integrity (misleads the user) · 🟠 major gap
(core domain feature absent) · 🟡 fidelity (right idea, wrong/loose math) · ⚪ polish.

### Fixes already applied this session (backend, verified live)
1. **ML stack installed** (`scikit-learn`, `statsmodels`, `xgboost`). `/api/forecast`
   now runs **11 real models**; on TPA-4471 the winner is **`xgboost` @ MAPE 2.48%**
   (beating naive 3.05). Resolves the *backend* half of A1. (Frontend half — fake
   "Run ML" widget, grain, env banner — still open.)
2. **🔴 NEW infra bug found + fixed: `calendar.py` stdlib collision.** The repo's own
   `calendar.py` solver shadowed Python's stdlib `calendar` (repo root is on
   `sys.path` via the `solvers/` shim). Dormant until the ML libs pulled in `pandas`,
   which does `import calendar` → **backend crashed on boot** with
   `module 'calendar' has no attribute 'day_abbr'`. Renamed `calendar.py` →
   `plant_calendar.py` (one importer updated, no logic change).
3. **🔴 NEW infra bug found + fixed: dead calendar route.** `/api/calc/calendar` was
   defined *after* `app.run()` inside the `__main__` guard, so it never registered
   when launched via `python app.py` (returned 405). Moved the block above the guard;
   endpoint now returns 200 (292 working days, holiday-aware).

These three are packaging/wiring fixes — `index.html` and solver *logic/payloads*
remain untouched.

### Phase 1 honesty pass — Demand stage (done, `demand.jsx`, parses clean)
Directive: **do not label fakes as "illustrative" — replace them with real computed
values or delete them.** Applied:
- **Forecast grain fixed** (A2): sends `monthly / season 12` (history is monthly-
  canonical) instead of `weekly / 13`. Live winner is now `xgboost @ 2.48%`, not `naive`.
- **Engine auto-runs** on mount + item change — the stage shows live results, not a
  mock board.
- **Leaderboard is live-only** (A1): the hardcoded 15-row `M.forecastModels` fallback
  is gone; before a run it shows an honest *running…/press Run/engine-error* state.
- **Engine-availability read-out** added from the backend `env` — says "all engines
  available" or names which are offline. (No more silent ML degradation.)
- **Fake "Run ML" widget deleted** (A1) — the `setRan` theater with hardcoded
  `MAPE 6.8% / 7.5% / locked` cards is removed; replaced by a truthful data-tier note.
- **FVA is real** (A6): `naive MAPE − winner MAPE`, both read from the live leaderboard
  (was hardcoded `24.1 / 6.8 / 6.2` with a fabricated "consensus").
- **Override card is functional**: edits a forecast period and **writes back to the
  committed demand slice** via `setItemDemand` (was hardcoded `2,840 / 3,120 u`).
- **Chart mock removed**: the forecast line draws only from a live run (was falling
  back to `M.forecast12`); history-only otherwise.
- **ABC/XYZ 9-box derived** from the actual products — and this exposed the static
  table was *wrong* (claimed 2 C·Z items; only 1 exists).

### Phase 1 (continued) — grain + Home + status board (done, all parse clean)
- **User-selectable grain, default DAY** (`data.jsx` + `demand.jsx`): the forecast
  no longer hard-codes monthly. A Day/Week/Month toggle drives the engine; **day =
  finest, the grain that exposes demand spikes for production planning** (the user's
  point). Week/Month are roll-ups of the daily signal.
- **Real per-item DAILY history** (`M.dailyHistoryFor`, `M.historyAt`): a seeded
  generator (weekend dip + drift + promo spikes + noise) per SKU. Verified live:
  daily/180-pt → **winner `xgboost` @ 6.69% MAPE over a 30-day horizon, naive demoted
  to 6th** (so ML earns its keep, FVA +3.2 pts). Chart history + forecast now share
  the chosen grain.
- **Home KPIs derived** (A3): Revenue/COGS/Margin/SKUs/Lines computed from
  price·cost·demand; the margin drill is per-family. Solve-dependent tiles
  (Fill Rate, OTIF, Inv DOH) read **"—"** until a real run — not fabricated. (Real
  revenue ≈ ₹1.59 Cr vs the old hardcoded ₹38.4 Cr — the fake wasn't even consistent
  with the product data.)
- **Readiness grid derived** (A5): ready/blocked computed from actual data presence
  per solver (Monte-Carlo honestly blocked — no distributions seeded).
- **Solver-status board neutralised** (A4): the pipeline ribbon + network nodes no
  longer claim "running · 128 POs / ₹6.84 Cr"; engine TYPE stays, result reads "—"
  until a live run. (A session run-registry to flip them to "done" with real numbers
  is the proper Phase-2 fix.)
- **Production line-util derived** (A6): `Σ(monthly demand on line) ÷ capacity`
  replaces hardcoded `94/88/96%`. Side effect: the honest values (30/20/12%) surface
  a real **mock-data unit inconsistency** (annual demand vs monthly capacity) — that's
  audit finding E2 made visible, not a code bug.

**Still fake — genuinely needs later-phase scaffolding (NOT fabricated in place):**
- 🟡 Production day-MPS (B2/D2) — synthetic per-day split with no Sun/holiday
  exclusion; needs the minute→period calendar-aware capacity bridge (Phase 4).
- 🟠 Other stages (finance cash/WACC, scenarios tornado, sourcing landed cost,
  logistics flows) still carry seed/fabricated values — they are de-faked as part of
  their own domain phases (3–5), since making them real *is* that domain work.

---

## A. Integrity — output that misrepresents itself (🔴 highest priority)

### A1 🔴 The ML forecast stack is not installed — and the UI hides it
Live test of `/api/forecast` with the real payload returned:
```
env: { sklearn: False, statsmodels: False, xgboost: False }
leaderboard: naive, croston, tsb, sba   (4 models)
winner: naive   (mape 7.11)
warning: None
```
- `statsmodels:False` ⇒ **no Holt-Winters, no ARIMA/SARIMA**. `sklearn:False` ⇒
  **no Random Forest / Gradient Boost / MLP / LinReg**. `xgboost:False` ⇒ no XGBoost.
- The engine silently degrades to 4 trivial numpy models and the **winner is always
  `naive`** for smooth series. The backend sets `warning: None` — it does not even
  tell the user the ML stack is absent.
- Meanwhile the UI advertises **"17 models"**, **"ML unlocks at 12 · DL at 36"**
  ([demand.jsx:133](demand.jsx#L133)), and a **fake "Run ML" button**
  ([demand.jsx:135](demand.jsx#L135)) that sets `ran=true` and shows three
  **hardcoded** cards (`MAPE 6.8%`, `LightGBM 7.5%`, `N-BEATS locked`) unrelated to
  the real call. When the real call *hasn't* run, [demand.jsx:241](demand.jsx#L241)
  shows the full 15-row `M.forecastModels` mock leaderboard.
- **Answer to "did we check the ML actually works?": No. It does not run, the winner
  is the dumbest model, and the UI fabricates a leaderboard that conceals this.**
- Fix track: (1) install `scikit-learn statsmodels xgboost` (or surface a real
  capability banner when absent), (2) delete the fake "Run ML" widget, (3) make the
  leaderboard render *only* live results (with an honest "engine offline" state when
  the call fails), (4) surface `product.warning` and `env`.

### A2 🔴 Forecast grain is mismatched to the data
`history24` is **monthly-shaped seasonal data** (annual cycle), but
[demand.jsx:29-33](demand.jsx#L29) sends it as `time_grain:'weekly',
season_length:13`. Even with `statsmodels` present, seasonality would be detected
at the wrong period. Live winner is `naive` partly because of this.

### A3 🔴 Headline KPIs are fiction
Every Home tile is a hardcoded string from `M.kpis` — `totalCost:'₹ 12.64 Cr'`,
`revenue:'₹ 38.4 Cr'`, `margin:'22.6%'`, `otif:'94.2%'`
([home.jsx:35](home.jsx#L35), [data.jsx:40](data.jsx#L40)). None is derived from
products or solver output. The drill-downs (`KPI_DRILL`,
[home.jsx:7](home.jsx#L7)) are hardcoded tables. **Your "the metrics on the first
page being derived properly per product and consolidated" — they are not derived at
all.**

### A4 🔴 Solver-network status board is theater
`procurement: status:'running'`, `production:'queued'`, `transport:'queued'`
([data.jsx:316](data.jsx#L316)) are static strings shown on Home + Console
regardless of whether anything ran. The pipeline ribbon ("128 POs", "MAPE 6.8%",
[data.jsx:30](data.jsx#L30)) is likewise fixed.

### A5 🔴 Readiness grid lies by its own admission
Its dev-note says *"Not a passive checkmark — a not-ready row disables its solve"*
([home.jsx:80](home.jsx#L80)), but `ready:true/false` is a static field in
`M.readiness` ([data.jsx:461](data.jsx#L461)); it checks nothing.

### A6 🟠 Illustrative numbers wear a "solved/derived" badge
FVA (`Naive 24.1 / Statistical 6.8 / Consensus 6.2`,
[demand.jsx:319](demand.jsx#L319)) carries `Provenance kind="derived"`; line-util
`94%/88%/96%` ([production.jsx:87](production.jsx#L87)) is presented as computed.
Fabricated values should be tagged **illustrative**, not derived/solved.

---

## B. The item selector is decorative — outputs aren't bound to a product (🔴/🟠)

Every stage shows `<ItemSelector/>` and headers like *"all for the selected item"*,
but the data underneath usually does **not** vary by selection. This is the single
biggest trust break, and it is exactly your "wait — for what product am I forecasting
/ viewing the MPS?" instinct.

### B1 🔴 Demand runs on one global history regardless of SKU
`fc` always sends `history:M.history24` ([demand.jsx:31](demand.jsx#L31)). The
history grid uses `M.history24.slice(-12)` ([demand.jsx:64](demand.jsx#L64)); the
override is hardcoded `3120 u` / `"Festive OEM ramp"` ([demand.jsx:204](demand.jsx#L204));
ABC/XYZ counts are static `M.abcxyz`. Switch the SKU dropdown → identical numbers.
There is no per-SKU history in the mock at all (only one 24-point series exists).

### B2 🔴 MPS / ATP ignore the selector and show only 4 of 8 SKUs
`ProdMPS` / `ProdATP` render `M.mps.map(...)` ([production.jsx:157](production.jsx#L157),
[:193](production.jsx#L193)) — the fixed 4-SKU table. The selected item is never
referenced. Two finished SKUs (5540, 7722) and all raw materials silently have no
row. No "viewing MPS for X" context header anywhere.

### B3 🟠 Procurement explodes a single BOM
Only `TPA-4471` has a BOM in the mock ([data.jsx:56](data.jsx#L56)); every other
product shares none. So multi-product MRP **netting across shared parts** (e.g.
`RM-STL42` feeds several FGs) is not modeled — each SKU is procured in isolation,
which is not how MRP works.

### B4 🟠 No consolidated vs per-item view
You asked "should there be a consolidated full version?" — yes. There is currently
neither a clean **per-item dossier** (one SKU's demand → MPS → BOM → POs → landed
cost → margin) nor a **consolidated P&L** that sums them. Home pretends to be the
consolidated view but is hardcoded (A3).

---

## C. Domain model dropped from index.html (🟠 major gaps)

### C1 🟠 Landed cost is one frozen example, not computed per part
`index.html` has a full engine: `landedCost(b,config,plant,profiles)` +
`landedCostBreakdown` + `incotermBuyerPays` ([index.html:1300-1380](../index.html#L1300)),
with **per-part `country`, `supplierType='import'`, `incoterm`, `bcdPct`, `swsPct`,
`transDutyPct`**, GST-registration ITC recovery (IGST sunk if unregistered), and
intrastate vs interstate routing. `app_v2` dropped all of it:
- `bom[]` entries are `{part,name,qty,cost,lt,moq,S,hold,shelf,sup}` — **no country,
  no incoterm, no import flag** ([data.jsx:56](data.jsx#L56)).
- Sourcing shows **one hardcoded** `M.landedCost` table (POSCO billet,
  [data.jsx:196](data.jsx#L196)); the landed-cost card posts fixed `LANDED_INPUTS`,
  not per-part values.
- **The procurement MILP uses raw `b.cost`, never landed cost** — so the "cheapest
  supplier" decision **ignores customs duty entirely.** For a sourcing tool this is
  a correctness bug, not a cosmetic one.
- Your requirement: per-subpart origin → country → (tariff-free as-of-date?) →
  duty/IGST breakdown that feeds unit cost. **Build US + India jurisdictions first**
  (HS code → BCD/IGST for IN; HTS → duty for US; FTA/GSP zero-duty flags with an
  *as-of date*). None of this exists in app_v2.

### C2 🟠 Ordering cost is a flat scalar; the breakdown + contract path are gone
`index.html` Pillar 13 `orderingCostS(b)` sums `b.ordBreakdown` components (admin,
inspection, inbound freight, customs filing…) and falls back to scalar
([index.html:736-747](../index.html#L736)). `app_v2` keeps only the scalar `S`
([data.jsx:57](data.jsx#L57)). Your two scenarios are both unrepresented:
- ordering cost **as a breakdown** of its cost legs, and
- **"predefined transporter contract to my doorstep" ⇒ a single ordering cost** —
  `index.html` even has `transportShipmentCost({qty,b,distanceKm,mode,contract})`
  with `rateBasis` tonneKm/m3Km/unitKm/perTrip/flatPeriodic + minCharge
  ([index.html:1259](../index.html#L1259)); `app_v2` ignores contracts in costing.

### C3 🟠 No actuals / demand-sensing loop
`index.html` has the demand-sensing breach detector + rolling-horizon patches
(`SET_MPS_ROLLING_PATCH`, [index.html:2637](../index.html#L2637)) and
`calcErrors` (MAPE/MAD/bias/tracking-signal of **actual vs forecast**,
[index.html:983](../index.html#L983)). `app_v2`'s Demand stage is forecast-only —
**no way to enter period actuals, no actual-vs-forecast tracking, no re-sense.**
Your SAP-style "constantly enter actuals for the period, watch tracking signal" has
no home in app_v2.

### C4 🟠 Safety stock / service level never used
Products carry `sl` (service level) and `mape` ([data.jsx:45](data.jsx#L45)) but
nothing computes `safety_stock = z(sl)·σ_LT·√LT` or a reorder point from them. The
ABC/XYZ → policy table ([data.jsx:1993 in index.html]) is dropped. `sl` is decorative.

### C5 🟡 Shelf life constrains nothing
`bom.shelf` and `product.shelf` exist; `index.html` enforces them via
`shelfLifeToPeriods` ([index.html:801](../index.html#L801)). In app_v2 the shelf-life
constraint toggle defaults **off** ([data.jsx:358](data.jsx#L358)) and no wired
solver passes shelf to the backend. Short-shelf SKUs (TPA-7722 @ 180 d, CN-LUB02 @
365 d) get no expiry handling. Your "short shelf lives, perishability" point is unmet.

### C6 🟡 Time-varying contracts & cost events are inert
`contracts[].rateByPeriod` step changes ([data.jsx:234](data.jsx#L234)) and
`costEvents` (W08 steel +6.5%, [data.jsx:75](data.jsx#L75)) are rendered but never
flow into any solver cost. Procurement/profit always use flat costs.

### C7 🟡 Transport runs on fabricated flows
All 5 outbound lanes carry `TPA-4471` only ([data.jsx:227](data.jsx#L227)); unit
weight is hardcoded `3.0 kg` (`_UNIT_WEIGHT_KG`, store.jsx). No per-SKU weight/volume,
no real outbound demand split. CoG and consolidation optimize over fiction. Your
"outbound network definitions, total cost per product and consolidated" is unmet.

---

## D. Time / calendar fidelity (🟡 — your "hour vs minute" question)

### D1 🟠 No consistent time base bridging cycle-time → capacity
`cycle` is `min/u`, line/stage `cap` is `u/mo` ([data.jsx:151](data.jsx#L151)), but
the bridge — *working hours/day × workdays/period × OEE ÷ cycle* — is **never
computed**; the `cap` values are static and `ProdArch` only *prints* the formula
([production.jsx:88](production.jsx#L88)). So changing cycle time or OEE changes
nothing downstream. **Recommended accuracy:** define capacity at **minute**
granularity (cycle min/u, shift = net minutes/day after breaks), aggregate to the
chosen grain — daily for the frozen fence, weekly/monthly beyond. Lines/stages
should be modeled in **minutes**; plan outputs in the period grain.

### D2 🟠 MPS day-view is not calendar-aware
The "10 working days" are `Array.from({length:10})` with synthetic per-day noise
`wq/5 + ((i%3)-1)*2` ([production.jsx:141,167](production.jsx#L141)) — **Sundays,
Saturdays and the 12 gazetted holidays (`M.holidays`, [data.jsx:460](data.jsx#L460))
are not excluded.** `index.html` has `holidaysInRange` for exactly this
([index.html:597](../index.html#L597)). Your "period has actual dates, day-level
opening with leaves/Sundays omitted" is unmet. Daily demand vs irregular patterns
(some SKUs daily, some lumpy) is not modeled either — one global monthly series.

### D3 🟡 Frozen / slushy fence not enforced
`index.html` has frozen/slushy horizon validation ([index.html:3118](../index.html#L3118));
app_v2 shows "frozen · daily" as a label only — no lock, no validation.

---

## E. Metrics don't reconcile across stages (🟠/🟡)

### E1 🟠 The same SKU shows three different MAPEs
Live forecast `naive 7.11` (or mock winner `6.8`), pipeline ribbon `MAPE 6.8%`,
and `product.mape: 8.2` ([data.jsx:45](data.jsx#L45)) — three numbers for TPA-4471,
none reconciled.

### E2 🟠 Capacity numbers don't agree
Line cap `1240 u/mo` (data.lines), aggregate `cap:1240` (data.aggregate.months),
and the profit-mix payload's `~82% demand-hrs` heuristic are three independent
capacity figures that never reconcile to one source of truth.

### E3 🟡 Stage MPS ≠ Console schedule
`ProdMPS` (synthetic) and the Console production Gantt (real MILP) are two different
fabrications of "the schedule," shown on different screens, never reconciled.

### E4 🟡 Console re-runs solvers with different payloads than the stages
e.g. procurement is built once in Sourcing and again in Console with a different
SKU/params → the same engine yields different answers depending on where you click.

---

## F. What actually works (be fair)

- The **MILP wirings are genuine**: procurement, production, transport, capital,
  depreciation, profit-mix, montecarlo, sequencing all call real endpoints and parse
  real results (verified Optimal by direct import in the prior pass). The plumbing is
  real; the **inputs** are the problem.
- The **forecast leaderboard table** renders live results correctly *when* the engine
  returns them — it's the surrounding narrative (A1) that's dishonest.
- **CoG** is a correct closed-form weighted centroid (just fed fictional flows, C7).
- **Method routing** (autopilot vs MILP by ABC/XYZ, [demand.jsx:356](demand.jsx#L356))
  is real and correct.
- Provenance atoms, gating, and the design system are solid foundations to build on.

---

## G. Remediation roadmap (proposed order)

Phased so each phase is shippable and unblocks the next. Phases 1–2 are mostly
**de-faking** (high trust ROI, low risk); 3–5 are **new domain build**.

**Phase 1 — Stop lying (🔴, ~1 session).** Install ML libs (or honest "offline"
banner); delete the fake "Run ML" widget; leaderboard live-only; surface
`warning`/`env`; tag every illustrative number as illustrative; fix forecast grain
(A2); make readiness + solver-status reflect real state.

**Phase 2 — Bind to the selected product (🔴, ~1–2 sessions).** Per-SKU history in
the mock; Demand/MPS/ATP read the selected item; "viewing X" context header on every
output; a **per-item dossier** page and a **consolidated P&L** that actually sums
per-SKU derived cost/margin (replaces hardcoded Home KPIs).

**Phase 3 — Restore the costing engine (🟠, ~2–3 sessions).** Port `landedCost` +
`incoterm` + `orderingCostS` breakdown; add per-part `country`/`incoterm`/HS; build
**US + India** duty/tax (BCD/IGST for IN, HTS duty for US, FTA/GSP zero-duty with
as-of date); feed **landed cost into procurement** (fixes C1 correctness bug);
contract-based ordering-cost path (C2); time-varying contract rates (C6).

**Phase 4 — Calendar & actuals (🟠, ~2 sessions).** Calendar-aware day MPS
(exclude Sun/Sat/holidays); minute-based capacity bridge (D1); frozen-fence
enforcement; actuals entry + demand-sensing/tracking-signal loop (C3); per-SKU
demand patterns incl. intermittent/short-shelf.

**Phase 5 — Network realism (🟡, ~1–2 sessions).** Per-SKU outbound flows/weights;
real consolidation & CoG inputs; safety-stock/service-level policy engine (C4);
shelf-life constraints (C5); cross-stage metric reconciliation (E1–E4).

---

## H. Decisions needed before fixing (product calls, not engineering)

1. **Tax jurisdictions:** confirm US + India first; which others later; source of
   duty rates (manual entry vs a rate table we seed)?
2. **ML stack:** install `scikit-learn/statsmodels/xgboost` in this environment, or
   keep it numpy-only and make the UI honestly say "classical models only"?
3. **Scope of "consolidated full version":** a per-item dossier + a company P&L
   rollup — is that the shape you want, or a single giant printable report?
4. **Contract model depth:** do you want full per-lane transporter contracts
   (rate basis, min charge, take-or-pay) like `index.html`, or a simpler
   "freight-included ⇒ one ordering cost" toggle to start?

---

*This audit records the state as of 2026-05-31. `index.html` and solver logic remain
untouched. Addressing begins per the roadmap above once Section H is settled.*

---

## I. Round-2 critique (2026-06-02) — see companion doc

A second domain pass, demand-led + cross-segment, is recorded in full in
**[CRITIQUE_R2_DEMAND_AND_SEGMENTS.md](CRITIQUE_R2_DEMAND_AND_SEGMENTS.md)**. It answers the
user's forecasting questions (events/promos, MTO cancellation, ensemble, lifecycle effect,
override-vs-consensus, data portability) and applies the same lens to every tab.

**Five recurring patterns it surfaces (grounded in file:line):**
1. **Backend richer than the payload** — `forecast.py` has a `promo` regressor but `fcPayload`
   never sends `promo_periods`; `procurement.py`+`transport.py` model landed cost + inbound
   truck/FTL-LTL but `bomParts` sends raw cost + a flat ₹120 ordering cost and no transport;
   `/api/demand/sense`, `/montecarlo`, `/cvar`, `/whatif` all idle. Work is mostly *wiring*.
2. **Hardcoded outputs beside live ones** — Finance (Plan-NPV, Investment, EVM, CCC, FX VaR)
   and Scenarios (cost waterfall ₹12.64Cr, TCO, lost sales, what-if) are mock.
3. **Grain mismatch** — forecast daily, consensus aggregate, MPS = weekly÷5 (not calendar-
   aware), plan monthly; Sundays/holidays excluded nowhere despite `plant_calendar.py`.
4. **Entry-point ambiguity** — Plan/Finance/Scenarios have no item selector but show SKU-shaped
   numbers; Production/Sourcing have one some cards ignore.
5. **No actuals / no event log / no recompute cascade** — blocks MTO cancellation, demand
   sensing, audit trail; MILPs plan to forecast, never corrected by actuals.

Outbound transport (logistics) is the counter-example: genuinely wired, truck-capacity-aware
FTL/LTL consolidation. The doc ends with a P3a→P5 fix sequence. **Record-only — no fixes this pass.**
</content>
</invoke>
