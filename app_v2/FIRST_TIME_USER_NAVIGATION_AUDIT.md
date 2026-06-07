# First-Time-User Navigation Audit — app_v2

**Date:** 2026-06-04 · **Build:** main @ `d5020e8`
**Companion to:** [USER_JOURNEY_AND_DESIGN_CRITIQUE.md](USER_JOURNEY_AND_DESIGN_CRITIQUE.md) (kept as-is — that pass
catalogues friction per stage; this one is a *different lens*).

**Method.** I re-read the shipped `.jsx` for all 12 stages + Reference + the chrome **field by field,
input by input**, and walked the product the way a **first-time user** meets it — scrolling each page in
render order, reading each label cold, asking four questions at every section:

1. **Should this section be *here*, after the last one?** (ordering / information architecture)
2. **Could these be *merged*?** (consolidation)
3. **Is anything *missing or contradictory*?** (does a field lie about what it does?)
4. **Is it *visually clear*?** — and does the user end up with a correct mental picture?

…then a fifth, cross-cutting question the page-by-page walk can't answer and **Part 8** takes on:
**where is the *structure*?** When a number is assembled from inputs on two pages and consumed on a third
(carry rate = WACC + spread, defined tabs apart), what makes that chain legible to the user?

Everything below is traced to a real component/line. Where I correct my own earlier document, I say so
(Part 7). Severity: 🟥 blocks comprehension · 🟧 confuses · 🟨 polish. "✓" = works well, protect it.

---

## Part 0 — The first 60 seconds (before any page)

A first-timer's eyes hit **three** navigation surfaces stacked above the content, and they don't agree:

| Surface | Where | Items | Vocabulary |
|---|---|---|---|
| **Pipeline ribbon** | under the masthead | **6** dots | DEMAND · PLAN · **PROCURE** · **PRODUCE** · **CAPITAL** · RISK |
| **Stage rail** | left edge | **12** rows | Home · Setup · Products · Network · Demand · Plan · Production · **Sourcing** · Logistics · Finance · Console · Scenarios |
| **Masthead "❓ Learn"** | top-right | 1 button | the *only* door to Reference (stage 12, hidden from the rail) |

- 🟥 **Two stage vocabularies for the same pipeline.** The ribbon says **PROCURE**, the rail says
  **Sourcing**; ribbon **PRODUCE** = rail **Production**; ribbon **CAPITAL** clicks through to
  `plan` (not Finance), ribbon **RISK** → `scenarios`. A new user cannot map the 6-dot ribbon onto the
  12-row rail — they're different names *and* different counts. (`chrome.jsx` `_RIBBON_STAGES` vs
  `data.jsx` `stages`.) Pick one set of stage names and use it everywhere.
- 🟧 **Reference is unreachable from the rail.** It's a real, well-built stage (live EOQ, Open-API
  catalog), but the only way in is a small "❓ Learn" button in the masthead. A first-timer will likely
  never discover it.
- 🟨 The footer advertises `⌘S SAVE · ⌘R SOLVE · ⌘E EXPORT` and the masthead a `⌘K` chip — keyboard
  promises a first-timer will test and (mostly) find unwired.

**Mental-model risk out of the gate:** "Is the pipeline 6 steps or 12? Why is *Capital* a pipeline stage
but *Finance* a rail stage?" The product's own chrome introduces the ambiguity before page one.

---

## Part 1 — The page-by-page first-time walk

For each page: **what I see first → every field in render order → ordering verdict → missing/contradictory
→ merge candidates → visual clarity.**

---

### 00 · Home — "Command Center"

**See first:** a freshness line ("NOT SOLVED YET — RE-PLAN…"), then an 8-tile KPI strip, then a 2-column
grid that actually holds **three** cards.

**Every element:**
- KPI strip (8 tiles): Revenue · COGS · **Margin ▸** · Plan cost · Scheduled · Mean fill · Risk CVaR95 ·
  Binding lines. Revenue/COGS/Margin are live arithmetic; the rest read the solve cache and honestly show
  `—` until solved (✓ never fakes).
- Exception Cockpit · Solver Lifecycle · Value Ledger.
- One action: **▶ Re-plan whole model**.

**Ordering:** ✓ sensible — "is my plan current, what's on fire, one button to refresh." The Solver
Lifecycle strip (BLOCKED→READY→FRESH→STALE with the missing input named) is the **best onboarding object
in the app** — protect it.

**Missing / contradictory:**
- 🟨 **Only `Margin ▸` is clickable; the other 7 tiles look identical and do nothing.** A first-timer
  clicks "Revenue," "Mean fill," etc. expecting the same drill and gets silence. (`StageHome`: `onClick`
  only on the Margin `Blk`.)
- 🟨 **The drill over-promises.** Its header reads *"company → family → SKU → location → period"* but
  `KPI_DRILL` only has `margin` and only drills one level (by family).

**Visual clarity:** 🟧 the grid is `cols={2}` but contains **3** cards (Exception, Lifecycle, Value) →
a ragged 2+1 layout. Minor, but the asymmetry reads as "something's missing."

---

### 01 · Setup — Identity & Calendar

**Render order of the step badges: `1 · ★ · 2 · 3`.**

- **Step 1 · Company Identity:** company name (big editable title ✓), Base Currency, Plant State,
  Effective Tax, **Service Level** (suffix reads `% z=1.645`), GST toggle, CIN; right card **MSME Tier**
  (✓ *derived*, not chosen — including "too big to be MSME").
- **Step ★ · Industry Quick-Start:** Auto / CPG / Pharma presets.
- **Step 2 · Planning Profile:** six segmented toggles + a live "what this switches off" preview (✓).
- **Step 3 · Planning Calendar:** Grain · Horizon · Start date · Work-days/wk · Frozen/Slushy · holiday
  add/remove; live `/api/calc/calendar` solve.

**Ordering:** 🟧 **the `★` template sits between step 1 and step 2 and breaks the count** (`1 … ★ … 2 …
3`). Worse, a template *writes* the Profile (step 2) and Service Level (step 1) when applied — so the
thing that overwrites steps 1–2 is rendered *after* step 1 and *before* step 2, with no arrow showing the
dependency. Either make it **step 0 ("start from a preset, then customise below")** or move it after the
Profile it edits.

**Missing / contradictory:**
- 🟧 **"z=1.645" leaks a z-score into the Identity card.** A first-time business user reads a statistics
  symbol on the company page. Gloss it ("≈95% service") or move it next to safety stock.
- 🟧 **Frozen/Slushy looks editable but isn't.** It's a `TextInput value={`${frozenWeeks}w /
  ${slushyWeeks}w`}` with **no `onChange`** — only a template writes it. A first-timer types in it and
  nothing happens. (`SetupCalendar`.)
- 🟧 **MSME fields point forward to a page not yet seen:** hints read *"also sourced from Finance · Asset
  Register / actuals."* Before Finance exists in the user's head, this reads like unexplained
  double-entry.

**Merge candidate:** 🟧 **the onboarding wizard asks the same six questions as step 2.** `ONB_Q` (in
`lib.jsx`) and `SetupProfile` are the identical profile set; a new user answers them at "Welcome," then
meets them again here with no "you already told us this." Merge into one card (wizard *is* the Profile
card, pre-filled).

**Visual clarity:** ✓ mostly clean. The "what this switches off" preview is excellent — it makes gating
visible instead of magic.

---

### 02 · Products

**Render order: selector → ScopeBanner → Define(1) → Yield(1a) → BOM(2) → Costs(3) → Policy(4) → MTO(5).**

**Contradiction the first-timer hits immediately:** 🟥 the **ScopeBanner says *"every card below — yield,
BOM, costs, policy — is for THIS product"* and the very next card (Define, step 1) is the *all-SKU*
catalog grid.** Step 1 is portfolio-scope; steps 1a–4 are single-item. The banner asserts single-product
scope directly above a whole-portfolio table. A first-timer can't tell whether they're editing one SKU or
all of them. (`StageProducts` renders `ScopeBanner` then `ProdDefine` (all SKUs) then the per-item cards.)

**Field-level:**
- **Define grid (14 columns):** Code · Name · Family · Make/Buy · Mode · Sell ₹ · Tgt % · Demand/yr · Wt ·
  Vol · Shelf · Yield · Lifecycle · Method. 🟨 **Mixed editability in one row:** Name/Make/Mode/Sell/Tgt/
  Demand are editable; **Wt/Vol/Shelf/Yield/Lifecycle/Method are read-only here** and edited elsewhere. A
  helper line explains it, but it's a "why won't this cell take my click?" every time.
- **BOM (step 2):** 🟥 title interpolates the selected product (*"Bill of Materials · Piston Ring
  Assembly"*) but the parts are the one shared `M.bom` (TPA-4471's bill — confirmed exactly one `bom:[` in
  `data.jsx`). Switch the selector → the title changes, the parts don't. Material cost (step 3) and the
  policy (step 4) inherit it.
- **Costs (step 3):** Setup/Run · Labour/Unit · **Lot size (MOQ)** · derived rollup ✓ · contribution.
- **Policy (step 4):** ✓ honestly says *"COMPUTED… not an input you type,"* real `/api/solve/policy`,
  honest σ=0 on the flat seed.
- **MTO (step 5):** firm orders as a profit-mix floor ✓.

**Merge candidates:**
- 🟨 **Wt/Vol/Shelf/Yield are shown read-only in Define (step 1) and edited in Yield (step 1a)** — two
  cards for one attribute set. Make the Define grid the single editable home, or drop those columns from
  Define.
- 🟨 **MOQ lives in three places:** Define (read-only), Costs (editable, step 3), and Production · Cycle
  (read-only). One canonical home.

**Visual clarity:** 🟧 the 14-column grid is the densest object a first-timer meets this early; half its
cells are inert. The scope contradiction is the real clarity failure here.

---

### 03 · Network

**Render order: Flows(A) → Nodes(B) → Suppliers(C) → Contracts(D) → On-Hand(E).**

- **A · Flow:** per-item directed lane graph (✓ true topology) + editable lane table (mode/₹/lead/trunk
  cap). Scope = **selected item**.
- **B · Node Master:** add/rename/resize/delete (✓ fully editable) + derived storage utilisation (✓).
  Scope = **global**.
- **C · Supplier Master:** a **read-only** `DataTable`. Scope = global. Carries a *"moved here from
  Sourcing"* note.
- **D · Contracts:** time-varying price ledger with step charts (✓). Global.
- **E · On-Hand matrix:** item × location, editable. Scope = **selected item** (row highlighted).

**Ordering:** ✓ defensible (topology → nodes → who supplies → contracts → opening stock).

**Missing / contradictory:**
- 🟧 **Scope silently flips mid-page** — A and E are per-item, B/C/D are global, with nothing marking the
  switch. A user who just edited a per-item lane assumes the node table is item-scoped too.
- 🟧 **Supplier Master is read-only while Node Master is fully editable** — inconsistent affordance on
  two adjacent cards ("why can I add a node but not a supplier?").
- 🟧 **The On-Hand matrix only lists items that already have a row** (`items = unique(onHand.item)`). A
  freshly added SKU with no opening stock *can't be given* opening stock here — it isn't a row.

**Merge candidate:** 🟨 make Supplier Master editable in the same pattern as Node Master so the two
"master data" cards behave identically.

**Visual clarity:** 🟨 badge each section "per-item" vs "global" so the scope flip is visible.

---

### 04 · Demand

**Render order: Ingest(1) → Import/NPI(1b) → Forecast(2) → Actuals(3) → Models(4) → Segment(5) →
Promos(6) → Commit(7).**

**The ordering problem a first-time analyst feels:** 🟧 **the forecast *answer* (step 2) is shown before
the model *competition* that produced it (step 4)** — and Actuals/Sensing (step 3) sits between them. So
the user reads "here's your forecast" (2), then "enter actuals" (3), then *finally* "here's which of 15
models won and why" (4). The justification lives two sections below the result. Put the leaderboard
adjacent to the forecast, or add a "why this model? ↓" cross-link from step 2 to step 4.

**Field-level:**
- **Step 1 · ingestion:** a 3-way mode picker (history / forecast / manual) + a manual grid.
  🟥 **the manual grid is inert** — each cell is `<input defaultValue={v}>` with **no `onChange`/`onBlur`**
  (`DemHistory`). It looks like an editable history table; typing changes nothing downstream. (The page
  *intends* the real path to be the `🤖 Run Forecast` button + CSV import, and a note says so — but the
  grid is visually indistinguishable from a live input.)
- 🟧 **two import targets — history vs forecast — look identical but do opposite things** (history feeds
  the competition; a supplied forecast bypasses it). Pasting into the wrong one silently changes
  everything.
- **Step 1b · CSV import + NPI:** ✓ real CSV ingestion is the genuine path; NPI like-modeling is
  responsibly behind Advanced.
- **Steps 2–6:** forecast+override (✓ override writes back), actuals→sensing (✓ real, auto-senses),
  leaderboard (✓ real engine, honest cold-start "warming up" banner), ABC/XYZ→method (✓), promos+holidays
  (✓ honest "lift is proportional to what the engine learned").
- **Step 7 · Commit:** per-item dossier + All-SKU consensus with a `committed N/6` badge ✓.

**Missing / contradictory:** 🟥 **single-item workflow, multi-SKU job, no worklist.** Forecast/commit run
for the *selected* SKU only; the whole portfolio appears only in the step-7 rollup at the very bottom.
Nothing pins "2 of 6 committed — next: TPA-3215" where the user can act. This is the highest daily-friction
item in Demand.

**Visual clarity:** 🟨 the inert manual grid is the clarity hazard — make it visibly a draft/override
surface or remove it.

---

### 05 · Plan (S&OP)

**Render order: Cost Inputs(0) → Labor content(0b) → Strategy(1) → Capacity(2) → Workforce(3) →
Disaggregation(4) → Gap(5).** A `VIEWING ▸ FAMILIES` banner sits above everything (✓ — names the
aggregation level explicitly; this is exactly the right move).

- **0 · Cost Inputs:** governed seeds incl. **Opening FG inventory** (✓ verified correct — enters the t=0
  balance).
- **0b · Labor content:** per-SKU hands-on % worker-time weighting (✓ correct, well-explained, but heavy
  — defaults to 100% and is easy to skip).
- **1 · Strategy:** plain **LEVEL/CHASE** word + note (✓) flanked by **Workforce CV / Inventory CV** bars
  (🟧 jargon — the coefficients of variation are never expanded).
- **2 · Capacity & Duals:** demand vs line-registry ceiling, labor dual, line-pressure (✓ strong, with
  the honest "labor binds, not lines" story).
- **3 · Workforce:** hire/fire/OT + the gap each fills (✓).
- **4 · Disaggregation:** family → SKU by mix (✓).
- **5 · Gap to Target.** 🟧 **this card is seed, but badged "derived."** Volume/Revenue/Margin/Inventory
  gaps come from `M.sop` (static constants in `data.jsx`), yet the card shows `Provenance kind="derived"`
  with an `asOf` timestamp. A first-timer reads a real reconciliation; it's a fixed example. Either derive
  it from the committed plan vs target, or badge it illustrative.

**Ordering:** ✓ logical. The "moved here from Scenarios" churn note on step 5 should go.

**Visual clarity:** 🟧 CV bars next to the plain word; otherwise clear.

---

### 06 · Production

**Sub-tabs: Architecture · Cycle & Line · Schedule · Changeover.**

🟧 **Step numbers scramble across the sub-tabs.** Architecture = step 1, Cycle = step 2, **Schedule = steps
0, 3, 4, 5**, Changeover = step 6. A first-timer clicking **Schedule** sees a sequence that **starts at 0,
jumps to 3**, and never shows 1–2 (those are behind other tabs). The numbering implies a linear scroll the
tab structure breaks.

**Field-level:**
- **Architecture:** editable line→stage→machine tree (✓), bottleneck = slowest stage (✓ derived, not
  typed), detailed/simple OEE toggle (✓).
- **Cycle & Line:** governed cycle/line overrides drive the MILP (✓). But three inputs here look editable
  and aren't: 🟨 **"Run hours / day" `value="20"`, "Effective Rate" (disabled), and "Batch Size · MOQ"
  `value={p.moq}`** all have **no `onChange`** — display-only. (MOQ is editable back in Products · Costs —
  the third home for MOQ.)
- **Schedule (0/3/4/5):** governed MILP params (✓ honest seeds, campaign min-run + time-phased toggles are
  real levers), MPS with a day-drill inside the frozen fence (✓), ATP/CTP (✓), capacity/shutdown (✓).
- **Changeover:** editable matrix (✓) + solved sequence (✓).

**Merge / ordering:** 🟧 renumber so each tab's sections read 1→n within the tab (don't split a 0–6 scroll
across four tabs). Drop the "moved here from Products" churn note.

**Visual clarity:** 🟨 the inert Cycle inputs are the hazard; the rest is strong.

---

### 07 · Sourcing — fifteen sections on one scroll

**Render order:** Solver Params (0) · External Signals (0b, behind Advanced) · **Per-Part MRP (1)** ·
Incoterms (2) · Sourcing Terms (3) · Landed Cost (4) · Stepwise Freight (5) · Inventory Policy autopilot
(6) · Rolling Re-plan (7) · MEIO (8) · Network MEIO (8b) · Newsvendor (9) · Postpone (10) · **Release &
Shortages (11)** · Exceptions (12).

🟥 **This is the page that most needs splitting.** Fifteen sections — a graduate inventory-theory course
on one scroll — interleave **operational** outputs a planner needs weekly with **strategic** science
touched quarterly:

- **The thing most users came for — the PO Release Plan — is step 11**, near the bottom, below MEIO,
  network pooling, newsvendor and rolling re-plan.
- 🟧 **Step 1 (MRP) leads with a *synthetic* grid.** The prominent gross→net→PO table is hardcoded
  (`gross=[0,0,1200,…]`, `sched=[800,…]`, `oh=1400`) and explicitly *"teaches the mechanic"*; the **real**
  joint-MILP releases are a smaller green box below it (and the full PO register is at step 11). The eye
  lands on the teaching grid first.
- 🟧 **Incoterms (step 2) is a static reference matrix** dropped between MRP and Sourcing Terms — textbook
  content interrupting the operational flow.
- 🟥 **Shared-BOM again:** every part picker iterates the same `M.bom`, so "parts of the selected product"
  are identical for every product (ties to Products 02 🟥).

**Field-level:** the science sections (Sourcing Terms, Landed Cost, Stepwise Freight + supplier
consolidation, Policy autopilot + joint replenishment, Rolling nervousness, MEIO decoupling, Network
pooling, Newsvendor/CVaR) are each a **real, honestly-badged solve** — the supply depth here is the
strongest engine work in the product. The problem is **packaging, not correctness.**

**Re-order proposal (the single highest-value change in the app):**
- **"Run" sub-tab:** Solver Params · Per-Part MRP (real first) · **PO Release & Shortages** · Exceptions.
- **"Design" sub-tab:** Sourcing Terms · Landed Cost · Freight · Incoterms (reference) · Policy · Rolling ·
  MEIO · Network MEIO · Newsvendor · Postpone · External Signals.

**Visual clarity:** 🟥 fifteen `0/0b/1…11/12` steps (with `0b` and `8b`) on one scroll is the densest page
in the product. The synthetic-before-real ordering compounds it.

---

### 08 · Logistics

**Render order: Allocation(1) → Consolidation(2) → Center-of-Gravity(3).** Gated off for single-site
profiles with a clear GateNote (✓).

- **Allocation:** flow map + lane×mode matrix + per-SKU tonnage (✓ real kg/unit).
- **Consolidation:** LTL→FTL (✓ honestly says "none beat FTL" when nothing clears a truckload).
- **CoG:** weighted centroid (✓ real closed-form).

**Missing / contradictory:**
- 🟨 **Pre-solve "planned" KPIs read like results** — before the transport solve, Allocation shows
  ₹24.8L / ₹1,420 / 96.4% subtitled "planned." At a glance they look solved.
- 🟨 **Empty-state CoG shows a hardcoded "~18% km cut"** until real nodes drive it (the real branch
  correctly drops the specific claim).

**Visual clarity:** ✓ the network-flow visuals are distinct and legible. For a gated user the whole stage
is a GateNote — clear, but it still occupies a rail slot.

---

### 09 · Finance

**Sub-tabs: Cash & WC (default) · Capital · Value · Investments · Assets · FX.**

🟧 **The default tab is the illustrative one.** `sub` defaults to **Cash & WC**, which *the card itself*
flags: *"no live AR/AP/inventory ledger… the cards below are ILLUSTRATIVE seeds."* A first-time CFO lands
on **seeds**; the solved tabs (Capital hurdle, Value/EVA, Investments) are one click right. **Lead with
Capital.**

**Field-level (what's real vs seed — a first-timer can't tell without reading every badge):**
- **Cash & WC:** Working-capital chart, Payment Ledger, Budget, EVM, CCC — **all seed or derived-from-seed**
  (`M.cashflow`, `M.evm`, hardcoded DIO/DSO/DPO 52/28/39). Honestly banner-flagged ✓, but it's the landing
  tab.
- **Capital:** ✓ genuinely solved — blended hurdle, min-WACC structure, DSCR, NPV/IRR with SLM/WDV shield.
  Decision-grade.
- **Value (EVA):** ✓ solved EVA/ROIC with destroyer call-outs, required-sales bridge, EVA-prune branch.
- **Investments:** ✓ solved capital-capacity MILP + risk-adjusted NPV.
- **Assets:** register is a read-only table (foot hardcodes "4 assets"); depreciation schedule is solved ✓.
- **FX:** 🟧 **framed as the editable "single source of truth" but the rates can't be edited.** The card
  info says *"every $→₹ reads this, nothing is hard-coded,"* yet the FX-rate `NumInput`s and the "As-of"
  field have **no `onChange`** (display-only), the hedging table is static seed, and **"Procurement Risk &
  FX" is fully hardcoded** (€12.0K / ₹2.4L / +₹1.8L) under a "VaR" badge with no illustrative flag. The
  claim and the behaviour contradict.

**Missing / contradictory / dead:**
- 🟨 **"📄 Board pack" button (header) has no `onClick`.**
- 🟨 **Buy-vs-Lease (`FinBVL`) is entirely hardcoded** (₹84L/₹71L/₹13L/₹18L/₹66L, "LEASE wins by ₹5L")
  under a "decision" badge with no illustrative flag — and it's **rendered twice** (end of Value *and*
  end of Investments).

**Merge candidates:** 🟨 collapse the all-seed Cash cards behind a single "needs a ledger feed" banner;
render Buy-vs-Lease once.

**Visual clarity:** 🟧 the real problem is *which numbers are real* — solved and seed cards look
identical except for a small badge. Leading with the seed tab makes the first impression "this is a demo."

---

### 10 · Console

**Three bands: ① Orchestrate · ② Interpret · ③ Anatomy Lab.**

🟥 **Band ① (run control) is almost entirely decorative.** The header **"⚡ Solve all queued"** has no
`onClick`; the Run Console **"▶ SOLVE (n)"** and **"Reset"** buttons have no `onClick`; the Solve-Status
shadow-price table reads `M.shadow` (static seed). A first-timer comes to "the Console" to *run things*,
clicks **SOLVE**, and nothing happens. The actual solving lives on each stage and in band ③.

- **② Interpret:** result sub-tabs (Profit/Procurement/Production/Transport/Risk/Capital/S&OP) that
  **re-render the same result cards already on Sourcing/Production/Logistics/Finance**. Some fall back to
  seed before a solve (e.g. ResSOP "Pipeline" shows hardcoded ₹6.84 Cr / ₹3.12 Cr / ₹42 L). A first-timer
  can't tell whether Console is where you *read* results or only *run* them.
- **③ Anatomy Lab:** ✓ **the product's signature differentiator** — real model type, the actual `.py`
  source (read-only), the term→source WIRED/DEFAULT audit, and a live solve. Nothing else in the category
  shows this. 🟨 the "live solve" pane truly live-solves only **6 of 16** engines (the `builders` map);
  the rest read cache.

**Ordering / merge:** 🟧 **lead with what's real.** Band ③ is the gem and should be the headline; band ②
should *link to* the stages rather than duplicate them; band ① should be wired or removed.

**Visual clarity:** 🟥 a dead "SOLVE" button on a page literally titled "Optimize & Solve Console" is the
single most misleading control in the product.

---

### 11 · Scenarios

**Sub-tabs: What-if (default) · Risk & Stress · Loop · Cost · Explore.**

- **What-if (default):** ✓ branch/compare on **solved** KPIs + Excel round-trip (`ModelSurface`) — a real,
  solved landing tab. Good default.
- **Risk & Stress:** ✓ Monte Carlo, CVaR, resilience-to-failure stress — all solved. The illustrative
  Tornado/Disruption/Stakeholder cards are **responsibly fenced behind an `Advanced` collapsible** labelled
  "illustrative — not solved," with a *solved* tornado primary. (This is good design — see Part 7.)
- **Loop:** ✓ chains real solves end-to-end.
- **Cost:** 🟧 **a whole seed sub-tab** — Cost Waterfall and TCO-per-SKU are both `badge="illustrative"`
  / `run="seed"`. A first-timer clicking "Cost" gets a dead tab that never becomes their data.
- **Explore:** 🟨 **two what-if surfaces with different powers** — an advisory parser ("does not change
  inputs or re-solve") and a bot that actually re-solves. Which one does the user trust to change the plan?

**Visual clarity:** ✓ mostly strong; the Cost tab and the two-what-ifs ambiguity are the soft spots.

---

### 12 · Reference (via "❓ Learn" only)

**Sub-tabs: Learning Lab · SAP Mode · Open API.** ✓ exemplary honesty — live EOQ playground, SAP CVaR card
that reads the **real cached MC solve** (honest "not run" otherwise), Open-API catalog introspected live
from `/api/meta/solvers`. 🟨 the SAP "Overview" row is six bordered boxes that look like tabs but are inert
(only the first is "active"). The bigger issue is discoverability (Part 0) — a first-timer rarely finds
this page at all.

---

## Part 2 — The inert-control catalog (looks interactive, isn't)

The user prioritised **visual clarity and "does the user end up with the right picture."** The single
most corrosive pattern for that is a control that *looks* live and isn't — every one teaches the user
"this app doesn't respond," which then makes them distrust the controls that *do* work.

| # | Control | Page | What a first-timer expects | Reality |
|---|---|---|---|---|
| 1 | **"▶ SOLVE (n)" / "Reset" / "⚡ Solve all queued"** | Console ① | runs solvers | no `onClick` 🟥 |
| 2 | **Manual history grid cells** | Demand step 1 | edits history | `defaultValue`, no `onChange` 🟥 |
| 3 | **FX rate inputs + "As-of"** | Finance · FX | edits the FX source of truth | no `onChange` (read-only) 🟧 |
| 4 | **"Run hours/day", "Batch Size·MOQ", "Effective Rate"** | Production · Cycle | tune throughput | no `onChange` 🟨 |
| 5 | **Frozen/Slushy** | Setup · Calendar | edits the fence | no `onChange` (template-only) 🟧 |
| 6 | **"📄 Board pack"** | Finance header | exports a pack | no `onClick` 🟨 |
| 7 | **7 of 8 KPI tiles** | Home | drill like Margin | only Margin drills 🟨 |
| 8 | **SAP "Overview" boxes** | Reference | tab between views | inert 🟨 |
| 9 | **"restore" (version history)** | masthead menu | rolls back | no `onClick` 🟨 |

**Recommendation:** either wire each, or visually demote it (no button affordance / "preview" styling /
disabled state with a tooltip). A disabled-looking control is honest; a live-looking dead one is not.

---

## Part 3 — Information architecture: "should this come *here*?"

Concrete re-ordering, highest value first:

1. **Sourcing → split Run / Design** (🟥). Run = Params · MRP(real) · **PO Release** · Shortages ·
   Exceptions. Design = Terms · Landed · Freight · Incoterms · Policy · Rolling · MEIO · Network · Newsvendor
   · Postpone · Signals. *The PO plan must not be step 11.*
2. **Demand → leaderboard next to the forecast** (🟧). Move Model Competition (4) up beside Forecast (2),
   or add a "why this model? ↓" link. Actuals/Sensing (3) is a *later-loop* step — consider after Commit.
3. **Finance → default to Capital, not Cash** (🟧). Seeds should never be the first impression of the
   money page.
4. **Console → lead with Anatomy Lab** (🟧). Make the glass-box the headline; link band ② to the stages;
   wire or cut band ①.
5. **Setup → make Templates step 0** (🟧). "Start from a preset, then customise" reads better than a `★`
   wedged between 1 and 2 that silently rewrites both.
6. **Production → renumber per tab** (🟧). Each sub-tab should read 1→n internally; no 0/3/4/5 jumps.

---

## Part 4 — Merge map: "could I merge these?"

| Merge | From → To | Why |
|---|---|---|
| Onboarding wizard ⇄ Setup Profile | two cards, identical 6 Qs → one | a first-timer answers the same questions twice |
| Products Define ⇄ Yield card | Wt/Vol/Shelf/Yield read-only in one, editable in the other → one editable home | the read-only cells invite dead clicks |
| MOQ (×3 homes) | Define / Costs / Cycle → one | which is canonical? |
| Cycle time | already moved Products→Production, but churn note remains → drop the note | the note is internal history leaking to users |
| Console ② result tabs | duplicate stage cards → link to the stages | blurs "run vs read" |
| Finance Cash cards | 5 seed cards → one "needs a ledger feed" banner | stop leading with seeds |
| Finance Buy-vs-Lease | rendered on Value *and* Invest → render once | literal duplication |
| Exception Cockpit + Value Ledger | (already consolidated to Home — see Part 7) | ✓ done |

---

## Part 5 — Contradictions & missing information

1. 🟥 **Products ScopeBanner** says "every card below is for THIS product" directly above the all-SKU
   Define grid.
2. 🟧 **Finance FX** info says "nothing is hard-coded" while its rate inputs are non-editable and its VaR
   numbers are hardcoded.
3. 🟧 **Plan · Gap** is badged `derived` but its numbers are `M.sop` seed constants.
4. 🟥 **Shared BOM** presented as per-product across Products *and* Sourcing.
5. 🟥 **Pipeline ribbon vocabulary** (PROCURE/PRODUCE/CAPITAL) ≠ rail vocabulary (Sourcing/Production/
   Finance), and CAPITAL→`plan`.
6. 🟧 **Console "live solve"** billed universally; true for 6/16 engines.
7. 🟨 Several **"planned"/illustrative numbers read as results** (Logistics pre-solve KPIs; Console
   pipeline seeds; Scenarios Cost tab; Finance Buy-vs-Lease).

---

## Part 6 — Does a first-timer end up with the right picture?

**Where the picture forms correctly (protect):** the Solver-Lifecycle strip (what's blocked/ready/fresh/
stale and where to fix it); the Plan `VIEWING ▸ FAMILIES` banner; "derived / not an input you type"
labelling; the Anatomy Lab glass-box; honest cold-start and "none beat FTL" messages; the responsibly-
fenced illustrative cards in Risk; the per-SKU provenance badges.

**Where the picture forms *wrong*:**
- **Scope** — "am I editing one SKU or all of them?" (Products banner contradiction; Network's silent
  scope flip; the single-item-vs-portfolio Demand workflow with no worklist).
- **Reality** — "is this number solved or a demo?" (Finance Cash default, Scenarios Cost, Console
  pipeline, Buy-vs-Lease, Plan Gap — all seed but not all flagged at the same volume as the genuinely-
  solved cards).
- **Responsiveness** — "did my edit do anything?" (the Part 2 inert-control catalog).
- **Structure** — "how many steps is this and what are they called?" (ribbon 6 vs rail 12, two names;
  Production's 0/3/4/5; Sourcing's 15).

The engine and the no-faking discipline are genuinely excellent. **What blurs the first-timer's picture
is packaging: scope marking, a consistent solved-vs-seed visual language, honest control affordances, and
one navigation vocabulary.** None of it is the math.

**If I could ship one change for the first-time picture:** make **"is this real?" legible at a glance** —
one consistent visual treatment that separates *solved* from *seed/illustrative* (not a small badge), so
the Finance Cash tab, the Scenarios Cost tab, the Console pipeline and every inert control read as "demo /
needs input" instantly. That single move fixes the Reality *and* Responsiveness confusions at once.

---

## Part 7 — Corrections to my prior audit & what I still didn't verify

- **Correction (vs USER_JOURNEY_AND_DESIGN_CRITIQUE.md C13):** I previously listed **Exception Cockpit +
  Value Ledger as "duplicated (Home ⇄ Scenarios)."** Re-reading `scenarios.jsx` (the explicit comment at
  the moved-out block) and `StageScenarios` (its sub-tabs are scenarios/risk/loop/cost/explore — neither
  renders those cards), they now render **only on Home**. That earlier "duplicated" claim is **stale** —
  they were consolidated, which is the right outcome. (Console *does* still mirror stage *result* cards —
  that duplication stands.)
- **Re-confirmed (not a correction):** the Risk-tab illustrative tornado **is** responsibly fenced behind
  `Advanced` with a solved tornado primary — good design, not a trap. The real seed surfaces are narrower:
  Finance Cash (default), Scenarios Cost (whole tab), Finance Buy-vs-Lease, Plan Gap, Console pipeline.
- **Severities are judgement, not measurement.** Every flag is a grounded hypothesis from reading the
  code, not from watching a user. The honest next step is a 5-task think-aloud: (1) add a 2nd product and
  notice the shared BOM; (2) commit all 6 SKUs; (3) find the PO release plan; (4) tell solved from seed on
  Finance; (5) click "SOLVE" in Console and explain what happened.
- **Previously-unverified gaps are now closed in Part 9** (onboarding branching, changeover internals, the
  `runFullLoop` step graph, accessibility from a static read).

---

## Part 8 — Cross-stage structure: where parameters live, flow, and contradict

This is the dimension the page-by-page walk (Parts 1–6) can't see, and it's the sharpest gap. The app's
hard problem isn't any single field — it's that **a number is assembled from inputs on two pages and
consumed on a third, with no structure that makes the chain legible.** Your carry-rate example is the
cleanest case; it is not the only one.

### 8.0 The structure *does* exist — in code, not in the UI

There is a real dependency graph. `store.jsx` defines **`SOLVE_DEPS`** — for each of the ~13 solves, the
input slices it depends on — and **`markStale(key)`** walks it transitively so an edit cascades a STALE
flag to every downstream solve. **`LOOP_STEPS`** + **`runFullLoop`** define the execution spine
(forecast → procurement → aggregate → production → linecap → montecarlo). So the wiring is principled.

**But the user never sees it.** The dependency graph surfaces only as three indirect shadows:
the STALE badges that pop up after an edit, the Console "Planning Spine" graph, and the Home "Solver
Lifecycle" strip. **None of them works at the *parameter* level.** In `SOLVE_DEPS`, every config value —
WACC sources, holding spread, service level, tax, FX, profit-mix budget — collapses into a single
`'config'` token. So when you edit the WACC, the engine *correctly* re-stales procurement, but it can only
tell you *"config changed"* — it **cannot** say *"WACC → carry rate → your buy plan moved."* The
granularity needed to answer "where's the structure?" is thrown away one layer below the UI.

### 8.1 The worked case — carry rate (your example), traced

```
carryRate(config)  =  finBlendedHurdle(config).wacc/100   +   config.invHoldingSpread/100
                       └── blended WACC                         └── holding spread
   INPUT A: equity/debt source table .......... Finance · Capital  (5 rows, SOLVED into a hurdle)
   INPUT B: holding spread ..................... Sourcing · Policy  (CarryRateControl, editable)
   CONSUMED BY: procurement · policy · rolling (Sourcing) · montecarlo (Scenarios) · EVA capital (Finance)
```

So a single coefficient is **assembled from two inputs on two different pages and consumed on at least
three more.** And the two inputs aren't even the same *kind* of control: the spread (B) is a plain
editable %, but the WACC (A) isn't a field at all — it's the *solved output* of a 5-row equity/debt source
table. "Go change the WACC" is not one action; it's "edit the source amounts/costs in Finance, re-solve
the hurdle, and trust that it ripples to Sourcing and Scenarios."

🟢 **The one place that handles this well is the carry-rate card itself** (`CarryRateControl`, Sourcing):
it *decomposes and attributes* — `= WACC 11.24% (from Finance · blended hurdle) + holding spread`, with
the WACC half shown read-only and pointing home. **That is exactly the missing structure** — a value that
shows its own lineage and where each part is governed. The problem is it's the *only* card that does it.

### 8.2 The same pattern, in worse forms

| Concept | Inputs (where) | Consumers (where) | Structural fault |
|---|---|---|---|
| **Carry rate** | WACC (Finance·Capital, *solved*) + spread (Sourcing·Policy) | procurement/policy/rolling, MC, EVA | assembled across 2 pages; no single home — *but* the card shows lineage ✓ |
| **Service level** | `config.serviceLevel` (Setup·Identity) **and** `config.serviceLevelOverride` (Sourcing·Params) | Setup one → Products policy + Monte-Carlo; Sourcing one → procurement/MEIO/policy/rolling/newsvendor | 🟥 **TWO independent fields for one concept**, different defaults, no cross-reference — raise Setup to 98% and procurement still plans at 0.95 |
| **FX rate** (USD→₹) | `config.fxRates.USD` — claimed single source of truth | landed cost, imported-part cost, hedging, VaR, external signals | 🟧 **no working editor** — Finance·FX inputs have no `onChange`, Setup redirects "edit in Finance", Sourcing shows it disabled. A shared input with no home you can actually change |
| **Opening inventory** | Plan·Cost-Inputs `init_inventory` (scalar, t=0) **and** Network·On-Hand (per-item matrix) | aggregate t=0 balance vs MRP net-requirements | 🟧 two unrelated "opening stock" concepts; neither references the other — do they reconcile? |
| **Line shadow price (PL-A)** | solved in Plan·Capacity (`linecap`) | Finance·Investments F-8 (binding-line margin/hr) | 🟧 flows via the solve cache **but also offered as a manual "Line shadow ₹/hr (from Plan PL-A)" paste field** — a number that should flow is hedged with hand-copy, inviting divergence |
| **MOQ / cycle time** | Products (Define + Costs) **and** Production (Cycle) | procurement, profitmix, MC, MPS | multiple homes (Part 4) — which is canonical? |

**The service-level case is the one to fix first** — it's not just hidden structure, it's a *latent
contradiction*: two fields named the same thing, governing different solves, that a user will assume are
one. (`products.jsx` policy uses `config.serviceLevel`; `sourcing.jsx` `effServiceLevel` uses
`config.serviceLevelOverride ?? 0.95` — they never reconcile.)

### 8.3 "Re-plan whole model" re-runs 6 of ~13 solves

The Home headline action runs `LOOP_STEPS` = forecast → procurement → aggregate → production → linecap →
montecarlo. It does **not** re-run policy, MEIO, network pooling, newsvendor/CVaR, rolling, transport,
profitmix or capital. So after "Re-plan whole model," the Sourcing science sections, Logistics and the
profit-mix can still read **stale**. 🟧 The label says *whole model*; the action is *the spine*. A
first-timer will believe everything is fresh when half the Sourcing page isn't.

### 8.4 The fix: make the structure a first-class object

The machinery to do this already exists — it just isn't surfaced. Two concrete moves:

1. **A Parameter / Governance registry** (one view, e.g. on Setup or Console): every governed input → its
   **single home**, current value, provenance (seed/override/solved), and **what it feeds**. This is the
   direct answer to "where's the structure?" — today that map lives only in `SOLVE_DEPS` + the payload
   builders, invisible. Collapsing the duplicate inputs (one service level, one MOQ home, a real FX
   editor) is a precondition.
2. **Lineage breadcrumbs on consuming cards**, modelled on the two cards that already do it: the
   **carry-rate decomposition** (Sourcing) and the **external-signals "drives: procurement · policy ·
   rolling · meio (now stale)"** line (Sourcing 0b). Both *show the chain*. Every cross-stage number
   (procurement's carry rate, Finance's EVA capital base, MC's service level) should carry the same
   "← assembled from X (page) + Y (page)" thread. The pattern is proven in-app; it's just not applied
   where the dependencies are longest.

**Bottom line for your question:** the structure isn't missing from the *engine* — `SOLVE_DEPS` and
`LOOP_STEPS` are a coherent DAG. It's missing from the *product*: parameters don't have single homes,
their cross-page assembly is invisible, and the one config token is too coarse to explain itself. The app
already contains the two UI patterns (lineage decomposition + downstream-drives) that would fix it — they
just live on two cards instead of being the system's backbone.

---

## Part 9 — Closing the previously-unverified gaps

- **`runFullLoop` step graph** — traced (Part 8.3): a 6-step chain that writes committed demand on step 1
  and caches each result for the next. It is the *spine*, not the full solve set — hence the "whole model"
  label overstates it.
- **Onboarding wizard** — `OnboardingWizard` / `ONB_Q` (`lib.jsx`) is **six profile questions with no
  branching** beyond setting `profile` — i.e. a thin pre-fill of the Setup·Profile card. That's the root
  of the 01🟧 duplication: it isn't a separate flow, it's the same six toggles a screen earlier.
- **Changeover matrix internals** — `ProdChange` builds a nested `{from:{to:min}}` matrix → `/api/solve/
  sequence` (shortest-Hamiltonian-path / ATSP heuristic, with an alphabetical baseline). 🟨 The SKU set is
  **hardcoded to 4** finished goods (`['TPA-4471','TPA-3215','TPA-9904','TPA-2188']`) — TPA-5540 and
  TPA-7722 are silently excluded from sequencing. A 6-SKU shop sequences only 4.
- **Accessibility / responsive (static read, not run)** — 🟨 pervasive **8–9px mono type** (`fontSize:8,
  8.5, 9` throughout), **color-only state encoding** in places (binding=red / slack=green with no text
  twin), **fixed-px layout** (188px rail, fixed card widths) and **`overflowX` data tables** (so a narrow
  viewport horizontal-scrolls rather than reflows). SVG charts scale via `viewBox`; tables don't. No
  visible focus-ring styling on the custom buttons. A proper audit needs the running app, but these are
  legible from the source.

---

### Provenance note
Every field, badge, inert control and ordering claim above was read from the live `.jsx` in `app_v2/` at
`main @ d5020e8`: the dead controls from handler-less `<Btn>`/`<input>` (Console SOLVE, Demand
`defaultValue` grid, Finance FX `NumInput`, Production Cycle inputs, Setup Frozen/Slushy, Board pack); the
two nav vocabularies from `chrome.jsx` `_RIBBON_STAGES` vs `data.jsx` `stages`; the shared BOM from the
single `bom:[` in `data.jsx`; the seed surfaces from `badge="illustrative"`/`run="seed"`/`M.sop`/`M.evm`
constants; the scope contradiction from `StageProducts` render order. The cross-stage structure (Part 8)
is from `store.jsx`: `SOLVE_DEPS` (the dependency DAG), `markStale`'s transitive cascade, `LOOP_STEPS`/
`runFullLoop` (the 6-step spine), `carryRate`/`finBlendedHurdle` (the two-page assembly), and the two
service-level fields (`config.serviceLevel` in `products.jsx` policy vs `config.serviceLevelOverride` via
`effServiceLevel` in `sourcing.jsx`). No issue is invented; each is traceable to a named component.
