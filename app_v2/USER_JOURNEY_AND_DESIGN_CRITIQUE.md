# User-Journey Walkthrough & Design Critique — app_v2

**Date:** 2026-06-04 · **Build:** main @ `d5020e8`
**Method:** I read the *actual* shipped `.jsx` for **every one of the 12 stages**, section by section,
field by field — the way a real user meets the product. This document grills each page on the
questions you asked: *can the user navigate? do they understand the inputs and outputs? does the flow
carry from page to page? is anything stale or decorative? did they even need this section?* — then
draws the systemic problems together and proposes how to simplify. It closes with a self-critique
that **corrects two things my first pass got wrong**.

Severity key on every flag: 🟥 blocking · 🟧 confusing · 🟨 polish. "GOOD" marks things to protect.

---

## 0 · The shape of the product (the two facts that govern every journey)

The spine: `Home · Setup · Products · Network · Demand · Plan · Production · Sourcing · Logistics ·
Finance · Console · Scenarios` (+ Reference via a "Learn" button), banded DEFINE → PLAN → DECIDE.

1. **The interaction model is split in two.** Setup, Products, Network, Demand, Plan, Sourcing and
   Logistics are **long step-scroll pages** (numbered sections you scroll). Production, Finance,
   Console, Scenarios and Reference are **sub-tab pages** (a tab bar). A user learns one metaphor on
   five pages, then must re-learn the other. **⚠ 🟧**
2. **One global "active item" selector.** Products, Demand, Network and Sourcing all act on **one
   selected SKU at a time**; the cross-SKU rollups are the only whole-portfolio views. This is the
   biggest recurring "am I doing this right?" risk. **⚠ 🟥**

---

# Part A — Every stage, grilled section by section

---

## 00 · Home — "Command Center"

**Sections:** live KPI strip · Exception Cockpit · Solver Lifecycle · Value Ledger. One action:
**▶ Re-plan whole model**.

**Inputs/outputs walked:**
- **KPI strip (8 tiles):** Revenue/COGS/Margin are *derived* from price×demand (real). Plan cost,
  Scheduled units, Mean fill, Risk CVaR95, Binding lines read the cross-stage solve cache and show an
  honest **`—`** until solved, with a freshness stamp. **GOOD** — never fakes a result.
- **Solver Lifecycle strip:** every solver as BLOCKED → READY → FRESH → STALE, with the missing input
  named and a jump link. **GOOD** — this is the best "what do I do next" surface in the app.
- **Exception Cockpit** + **Value Ledger**: ranked attention inbox + the tool's own ROI.

**⚠ Friction**
- 🟨 **The margin drill over-promises.** The drill header advertises "company → family → SKU →
  location → period," but `KPI_DRILL` only contains `margin` and only drills **one** level (by
  family). And only the Margin tile is clickable — the other seven tiles look identical but do
  nothing. A user clicks them expecting a drill and gets silence.
- 🟨 **Exception Cockpit and Value Ledger render on *both* Home and Scenarios.** Same components,
  two homes. Harmless but duplicative — which is the canonical place to triage exceptions?

---

## 01 · Setup — Identity & Calendar (step-scroll: 1 · ★ · 2 · 3)

**Inputs walked:** company name · base currency · plant state · effective tax % · service level % ·
GST on/off · CIN · plant-&-machinery ₹Cr · annual-turnover ₹Cr → **derived MSME tier** (step 1);
industry quick-start presets auto/cpg/pharma (step ★); the six **Planning Profile** toggles (step 2);
time grain · horizon · start date · work-days/week · frozen/slushy · holiday add/remove (step 3).

**GOOD** — the MSME tier is *derived, not chosen*; the "what this switches off" live preview is
honest; the calendar recomputes from a real `/api/calc/calendar` solve and says "showing seed
figures" until it does.

**⚠ Friction**
- 🟧 **Onboarding duplicates step 2.** The first-run wizard (`ONB_Q`) asks the *same six profile
  questions* as `SetupProfile`. A new user answers them at "Welcome," then meets them again here with
  no acknowledgement they're the same thing.
- 🟧 **Frozen/Slushy is shown read-only** (`4w / 12w` in a plain `TextInput`) — only the industry
  preset writes it, so it looks broken when you try to edit it here.
- 🟨 **MSME figures are double-homed:** labelled *"your figure · also sourced from Finance."* Before
  the user has seen Finance, this reads like an unexplained double-entry.

---

## 02 · Products — Define → Yield → BOM → Costs → Policy → MTO (step-scroll under the item selector)

**Inputs walked:** the **Define catalog** (per row: name, family, make/buy, mode, sell ₹, target %,
demand/yr, wt, vol, shelf, yield, lifecycle, method); **yield % / shelf-life / salvage %** (1a); the
**BOM** (part, qty/u, unit cost, lead time + advanced commercial terms + per-part scrap %) (2); setup
cost, labour/unit, lot size → **derived unit-cost rollup** + contribution margin (3); the **derived
(s,S)/(R,Q) policy** from `/api/solve/policy` (4); **MTO firm orders** as a profit-mix floor (5).

**GOOD** — material cost is genuinely summed from the BOM (not a fake %); the policy card says plainly
*"this is COMPUTED… not an input you type"* and re-derives on a real solve; the yield/expiry card is
exemplary honesty (*"shelf ≥ horizon, so salvage is inert for this SKU… it only bites if you shorten
shelf-life below 52 weeks"*).

**⚠ Friction**
- 🟥 **The BOM is a single shared `M.bom` presented as per-product.** The section title interpolates
  the selected product (*"Bill of Materials · Piston Ring Assembly"*) but the parts are *always* the
  one seed BOM (TPA-4471's). Switch the selector → the title changes, the parts don't. Material cost
  (step 3) and the policy parts (step 4) inherit the same shared BOM, so they're effectively
  identical across products bar a "conversion & overhead" residual. For a real 6-SKU shop with
  different bills, this is wrong, and nothing on screen admits it. *(Confirmed: exactly one `bom:[`
  in `data.jsx`.)*
- 🟨 **The 14-column Define grid mixes editable and read-only cells.** Name/make/mode/price/target/
  demand are editable in place; Wt/Vol/Shelf/Yield/Lifecycle/Method are read-only here and edited in a
  *different* card. A helper line explains it, but it's a "why won't this cell take my click?" moment.
- 🟨 **Two margin concepts side by side:** "target %" (a goal) and the realised profit-mix margin.
  Honestly labelled, but easy to conflate.

---

## 03 · Network — Flows → Nodes → Suppliers → Contracts → On-Hand (step-scroll, A–E)

**Inputs walked:** the **per-item directed lane graph** + an **editable lane table** (mode, ₹/unit,
lead, trunk capacity) (A); the **editable Node Master** (add/rename/resize/delete) + **derived
storage utilisation** (B); the **Supplier Master** table (C); the **time-varying Contract Ledger**
with step-price charts (D); the **item × location On-Hand matrix** (E).

**GOOD** — the flow graph is a true directed topology (not a linear chain); contracts model a mid-
horizon price step instead of averaging; storage utilisation is really `Σ(vol×on-hand)/cube`.

**⚠ Friction**
- 🟧 **Scope silently changes within the page.** Flows (A) and On-Hand (E) are filtered to the
  *selected item*; Nodes (B), Suppliers (C), Contracts (D) are *global*. Nothing marks the switch, so
  a user editing the per-item flow may think the node table is item-scoped too (or vice-versa).
- 🟧 **The On-Hand matrix only lists items that already have a row** (`items = unique(onHand.item)`).
  A freshly added SKU with no opening stock can't be given opening stock here — it isn't a row.
- 🟨 **Supplier Master is read-only while Node Master is fully editable.** Inconsistent: why can I add
  a node but not a supplier? Plus another **"moved here from Sourcing"** churn note.

---

## 04 · Demand — Ingest → Import/NPI → Forecast → Actuals → Models → Segment → Promos → Commit (step-scroll 1·1b·2·3·4·5·6·7)

**Inputs walked:** a 3-way **ingestion mode** picker + manual history grid (1); **CSV/TSV import** +
**NPI analog like-modeling** (1b); the **winning-model forecast + override grid** (2); **actuals →
demand sensing** (3); the **model-competition leaderboard** (MAPE/RMSE/MAE) + accuracy-by-horizon +
FVA (4); **ABC/XYZ → method** (5); **planned promos + holiday calendar → forecast** (6); **committed
demand + All-SKU consensus** with a `committed N/6` badge (7).

**GOOD** — the model competition is a real engine run on the user's history; the "warming up — not a
failure" cold-start banner is kind and honest; NPI for a no-history SKU is real, not faked.

**⚠ Friction**
- 🟥 **Single-item workflow, multi-SKU job, no worklist.** The user must cycle the global selector
  through all six SKUs (run → forecast → commit each), and the *only* place the whole portfolio
  appears is the step-7 rollup at the bottom. Nothing pins "2 of 6 committed — next: TPA-3215" where
  they can act on it.
- 🟧 **The two import targets (history vs forecast) are subtle but consequential.** History feeds the
  model competition; a supplied forecast bypasses it. They look alike; pasting into the wrong one
  silently changes everything downstream.
- 🟨 **Answer before method.** The forecast curve (step 2) sits *above* the leaderboard that produced
  it (step 4). Defensible, but it surprises analysts and there's no "why this model? ↓" cross-link.

---

## 05 · Plan — S&OP (step-scroll 0·0b·1·2·3·4·5)

**Inputs walked:** governed cost inputs incl. **opening FG inventory** (0); per-SKU **hands-on %**
worker-time weighting (0b); **Level vs Chase** strategy word + note + workforce/inventory CV (1);
capacity vs the line-registry ceiling + the labor dual (2); hire/fire/overtime by period (3);
disaggregation back to SKUs (4); **Gap to target** (5).

**GOOD** — opening inventory enters the t=0 balance correctly (separately verified); the strategy
headline is a plain human word (LEVEL / CHASE / HYBRID) with the solver's plain-English note.

**⚠ Friction**
- 🟧 **"CV" jargon flanks the plain answer.** Beside "LEVEL" sit **Workforce CV** and **Inventory CV**
  bars and the line *"low workforce-CV + non-trivial inventory-CV ⇒ level."* The manager understands
  the word and the note; the two coefficients-of-variation justifying it are never expanded.
- 🟧 **Hands-on % (0b) is conceptually heavy and easy to skip.** It's correct and well-explained, but
  a user who doesn't read the popover leaves every SKU at 100% and never learns automation should
  lower the weight.
- 🟨 **"moved here from Scenarios"** churn on step 5; and **no breadcrumb** that the plan's input is
  the committed demand from stage 04.
- 🟨 **"Did you even need S&OP?"** For a flat-demand, MTO, single-line shop the aggregate plan is
  ceremony — and the profile gate already *hides* it, but **silently**. Transparency ("we
  de-emphasised S&OP because your demand is flat/MTO") would beat invisible gating.

---

## 06 · Production (sub-tabs: Architecture · Cycle & Line · Schedule · Changeover)

**Inputs walked:** editable line→stage→machine tree, bottleneck = slowest stage (Architecture);
**cycle time & line assignment** (Cycle); governed **Production-MILP inputs** — labor rate, shutdown
threshold, holding cost, **campaign min-run**, **time-phased MPS** toggle — then MPS, ATP/CTP, and
capacity-loading/shutdown (Schedule, steps 0·3·4·5); **sequence-dependent changeover** matrix
(Changeover).

**GOOD** — the schedule runs the real production MILP; the params are honest overridable seeds; the
campaign min-run and time-phased toggles are genuine levers with the trade-off spelled out.

**⚠ Friction**
- 🟧 **Step numbers scramble across the sub-tabs.** The Schedule tab shows steps **0, 3, 4, 5** —
  steps 1 and 2 live behind *other* tabs (Architecture, Cycle). A user clicking "Schedule" sees a
  sequence that starts at 0, jumps to 3, and never shows 1–2. The numbering implies a linear scroll
  that the tab structure breaks.
- 🟧 **Cycle time's canonical home is ambiguous** — edited here ("moved here from Products"), read by
  Plan (worker-min = cycle × hands-on %). The churn note ships to the user, and it's unclear which
  page "owns" it.

---

## 07 · Sourcing — fifteen sections on one scroll (0·0b·1·2·3·4·5·6·7·8·8b·9·10·11·12)

**Sections:** solver params (0) · external-signal drivers (0b) · per-part MRP (1) · incoterms (2) ·
sourcing terms (3) · landed cost (4) · truck-step freight (5) · reorder autopilot (6) · rolling
re-plan & nervousness (7) · MEIO buffer placement (8) · network risk-pooling (8b) · newsvendor + CVaR
(9) · postpone/pin releases (10) · **PO release & shortages (11)** · MRP exception roll-up (12).

**GOOD** — almost every section is a *real* solve, honestly badged: the procurement MILP, the external
signals that genuinely re-drive cost/lead time, MEIO/pooling/newsvendor/CVaR, the exception roll-up
that "scales to a 10-part BOM." The supply science here is the deepest part of the product.

**⚠ Friction**
- 🟥 **Overload.** Fifteen sections — a graduate inventory-theory course as one scroll — interleave
  *operational* outputs a planner needs weekly (PO releases, shortages, exceptions) with *strategic*
  science touched quarterly (MEIO, newsvendor, pooling, rolling). The thing most users came for, the
  **PO Release Plan, is step 11**, near the bottom.
- 🟧 **The MRP grid is synthetic-teaches-then-real.** The prominent gross→net→PO table is explicitly
  *"synthetic… teaches the mechanic"*; the **real** joint-MILP releases are in a smaller green box
  below it. The honesty is there, but the eye lands on the synthetic grid first.
- 🟧 **Shared-BOM again:** the part picker iterates the same `M.bom`, so "parts of the selected
  product" are the same parts for every product (ties to the Products 🟥).

---

## 08 · Logistics — Allocation · Consolidation · Center-of-Gravity (step-scroll, gated)

**Inputs/outputs walked:** the DC→customer **allocation flow map** + lane×mode matrix + per-SKU
tonnage (1); **LTL→FTL consolidation** plan (2); the **center-of-gravity** hub (closed-form weighted
centroid) (3). Gated off entirely for single-site profiles, with a clear GateNote.

**GOOD** — CoG is a real derivation (not a mock endpoint); consolidation honestly says "none beat FTL"
when nothing clears a truckload; the per-SKU tonnage uses real kg/unit.

**⚠ Friction**
- 🟨 **Pre-solve "planned" numbers look like results.** Before the transport solve, the allocation
  KPIs show ₹24.8L / ₹1,420 / 96.4% — subtitled "planned," but they read as outputs at a glance.
- 🟨 **Empty-state CoG shows a hardcoded "~18% km cut"** (the `cog.mock` branch) until real nodes
  drive it; the real branch correctly drops the specific savings claim.

---

## 09 · Finance (sub-tabs: Cash · Capital · Value · Invest · Assets · FX)

**Outputs walked:** working-capital / cash-conversion dashboard (Cash); source-weighted hurdle,
min-WACC structure, DSCR covenant (Capital); **EVA/ROIC scoreboard with a destroyers count** +
required-sales bridge + product-economics segmentation (Value); NPV/IRR program DCF +
endogenous-capacity capital plan + risk-adjusted NPV + verdict (Invest); WDV depreciation (Assets);
FX hedging (FX).

**GOOD** — Capital, Value and Invest are genuinely solved and honestly badged; the **destroyer
call-outs and EVA capital base** are exactly the decision-grade numbers a CFO wants, with provenance.

**⚠ Friction**
- 🟧 **The default tab is the illustrative one.** `sub` defaults to **Cash**, and the code is explicit:
  *"there is no live AR/AP/inventory ledger feed… the working-capital, payables and budget figures
  below are ILLUSTRATIVE seeds."* So a CFO landing on Finance sees **seeds first**; the solved
  Capital/Value tabs are one click away. Lead with the solved tabs.
- 🟨 **The "📄 Board pack" button has no handler** — a decorative control that does nothing on click.

---

## 10 · Console — Orchestrate · Interpret · Anatomy Lab (sub-tabs / job bands)

**Walked:** the planning-spine run control + solver network (①); the selected solver's result cards
+ the plain-English explainer & prove-it (②); the **Anatomy Lab** — model type/objective/vars/
constraints, a **read-only live source view** (`/api/meta/solver-source`), the **term → source audit**
(✓ WIRED / ⚠ DEFAULT + `extras`), and a **live solve** (③).

**GOOD** — the **Anatomy Lab is the product's signature differentiator**: a real glass box, with the
actual `.py` source and an honest "does every term have a source?" audit. Nothing else in the category
shows this.

**⚠ Friction**
- 🟨 **The "live solve" pane only truly live-solves 6 of 16 engines** (`builders` covers forecast,
  aggregate, procurement, production, transport, montecarlo). The rest read cache or nothing, though
  the band is billed universally as "a live solve."
- 🟨 **Console re-renders result cards** (Procurement, Production Gantt, Transport, Capital, Reorder)
  that already live on Sourcing/Production/Logistics/Finance — blurring whether Console is where you
  *read* results or only *run* them.

---

## 11 · Scenarios (sub-tabs: Cockpit · Branches · Risk · Cost · Explore · Loop · Value · Versions)

**Walked:** exception cockpit + re-plan (Cockpit); branch compare on solved KPIs (Branches);
**Monte-Carlo, CVaR, resilience stress, and a SOLVED tornado** (Risk); cost waterfall + TCO (Cost);
what-if surfaces (Explore); end-to-end loop (Loop); value ledger (Value); version replay/merge
(Versions).

**GOOD** — Risk is genuinely solved (MC, CVaR, resilience-to-failure, a real `/api/solve/sensitivity`
tornado); the **illustrative tornado/disruption/stakeholder cards are responsibly fenced behind an
`Advanced` collapsible explicitly labelled "illustrative — not solved"** with the solved tornado as
the primary; the Loop chains real solves; the Value Ledger splits identified-vs-accepted honestly.

**⚠ Friction**
- 🟧 **The Cost sub-tab is wholly illustrative.** Cost Waterfall and TCO-per-SKU are both
  `badge="illustrative"` / `kind="external" run="seed"` — an entire sub-tab of seed visuals that
  never become the user's data. Honestly badged, but a user clicking "Cost" gets a dead tab.
- 🟨 **Two what-if surfaces with different powers:** an **advisory parser** ("does not change inputs
  or re-solve") and a **what-if bot that actually solves**. Which one does the user trust to change
  the plan?
- 🟨 **Exception Cockpit + Value Ledger duplicated with Home.**

---

## 12 · Reference (sub-tabs: Learning Lab · SAP Mode · Open API) — secondary, via "Learn"

**Walked:** the **live EOQ playground** (computes from your inputs); **SAP T-code crib** + a CVaR card
that reads the **real cached MC solve** (honest "not run" otherwise); the **Open API** catalog
introspected live from `/api/meta/solvers`.

**GOOD** — exemplary honesty: every figure computes or reads a real solve; nothing here is a stored
answer.

**⚠ Friction**
- 🟨 **SAP "Overview" shows six bordered boxes that look like tabs but are inert** — only the first is
  "active," none responds to a click.

---

# Part B — Five user journeys (how the grilled pages thread together)

The per-stage flags above land differently depending on *who* is walking. Five real personas:

1. **Asha — first-time single-line MTO owner.** Onboarding → Setup → Products → (gated spine hides
   Plan/Sequencing/Transport/Landed) → Sourcing → Finance. *Hits:* the onboarding⇄profile
   duplication (01🟧), the shared-BOM illusion the moment she adds her second product (02🟥), and
   Sourcing's 15-section wall when all she wants is a PO list (07🟥). *Saved by:* the profile gate,
   which is the best thing in the app for her. **80% valuable, 20% intimidating.**
2. **Ravi — 6-SKU demand planner.** Lives in Demand. *Hits:* the single-item selector with no
   portfolio worklist (04🟥) and the history-vs-forecast target subtlety (04🟧). Comprehension of any
   single chart is fine; **orchestration across SKUs is the pain.**
3. **Meena — S&OP manager.** Plan. *Hits:* CV jargon beside the plain LEVEL word (05🟧), the heavy
   hands-on % card (05🟧), and the unanswered "did I need this plan?" (05🟨). The opening-inventory
   and strategy outputs themselves are clear.
4. **Karthik — plant + procurement lead.** Production + Sourcing. *Hits:* the nav paradigm split and
   the step-number scramble across Production's sub-tabs (06🟧), the cycle-time canonical-home
   ambiguity (06🟧), and Sourcing's overload (07🟥). Notices Console mirrors results he already saw.
5. **Divya — skeptical CFO.** Finance + Scenarios. *Hits:* Finance opening on the **illustrative Cash
   tab** (09🟧) and the dead Board-pack button (09🟨); in Scenarios, a dead **Cost tab** (11🟧) and
   two what-ifs (11🟨). *Reassured by:* the solved Capital/Value/EVA tabs and the honestly-fenced
   illustrative cards in Risk — the badging mostly earns her trust back.

---

# Part C — Cross-cutting critique (the systemic patterns)

| # | Pattern | Severity | Where | Root cause |
|---|---|---|---|---|
| C1 | Two navigation metaphors (step-scroll vs sub-tabs) | 🟧 | every transition | organic growth, no single nav rule |
| C2 | Global single-item selector vs multi-SKU job, no worklist | 🟥 | Demand, Sourcing, Products, Network | per-item pages, portfolio reality |
| C3 | **Shared `M.bom` presented as per-product** | 🟥 | Products, Sourcing | one seed BOM, title interpolated per item |
| C4 | Sourcing overload (15 sections, run + science mixed) | 🟥 | Sourcing | every engine got its own step |
| C5 | Whole illustrative sub-tabs **as the default/with no live path** | 🟧 | Finance Cash (default), Scenarios Cost | no ledger feed / never wired |
| C6 | Onboarding ⇄ Profile duplication (6 Qs twice) | 🟧 | Setup | wizard reused questions, not the card |
| C7 | Jargon flanking plain answers (CV, z, s/S, R/Q) | 🟧 | Plan, Products | engineering labels shown to business users |
| C8 | Step-number scramble across sub-tabs | 🟧 | Production | steps split behind tabs |
| C9 | Mixed scope/editability within one page | 🟧 | Network (per-item vs global; suppliers read-only), Products grid | inconsistent affordances |
| C10 | Synthetic-teaches-then-real grids shown first | 🟨 | Sourcing MRP, Sourcing landed cost | pedagogy placed above the real result |
| C11 | Provenance churn shipped as UI copy ("moved here from X") | 🟨 | Plan, Production, Network | refactor notes leaked to users |
| C12 | Dead / decorative controls | 🟨 | Finance "Board pack", SAP "Overview" boxes, 7 non-drillable Home KPIs | placeholders never wired or removed |
| C13 | Duplicated surfaces across pages | 🟨 | Exception Cockpit + Value Ledger (Home ⇄ Scenarios), Console result mirrors | components reused without a single home |
| C14 | "Live solve" billed for all engines, true for 6/16 | 🟨 | Console Anatomy Lab | only 6 have shared payload builders |

**What's genuinely strong (protect):** the profile gate; "derived / not an input you type" labelling;
the yield/expiry inertness honesty; the solver-lifecycle strip; the Anatomy Lab glass box; the
honestly-fenced illustrative cards in Risk; the Value Ledger's identified-vs-accepted split; the
plain-English Level-vs-Chase note; the cold-start "warming up, not a failure" banner. **The engine and
the honesty discipline are excellent. The problems are packaging, consistency, a single data-model
gap (shared BOM), and a few demo leftovers — not the math.**

---

# Part D — How to simplify (prioritised, concrete)

**P0 — correctness & trust (do first)**
1. **Fix the shared-BOM illusion (C3).** Either make the BOM genuinely per-product, or — until then —
   stop interpolating the product name over a shared bill and label it honestly ("reference BOM —
   per-product bills coming"). A user must never think they edited Piston Ring's BOM when they edited
   the shared one.
2. **Stop leading with illustrative tabs (C5/C12).** Default Finance to **Capital** (solved), not
   Cash; put the seed Cash dashboard behind a "needs a ledger feed" banner. Move the Scenarios **Cost**
   tab's Waterfall/TCO behind the same `Advanced` fence the Risk tab already uses, or wire them. Wire
   or delete the dead Board-pack button and the inert SAP Overview boxes; make all 8 Home KPIs
   drillable or none.

**P1 — navigation (highest daily friction)**
3. **Split Sourcing into "Run" and "Design" sub-tabs (C4)** — Run = MRP · PO release · shortages ·
   exceptions; Design = terms · landed · MEIO · newsvendor · pooling · rolling. Adopt sub-tabs as the
   **one** nav rule for any page over ~6 sections (C1, C8), which also straightens Production's
   step numbering.
4. **Add a portfolio worklist (C2)** pinned to Demand (and Sourcing): "2 / 6 SKUs committed — next:
   TPA-3215," click to switch the selector. Single highest-leverage fix for the multi-SKU confusion.

**P2 — clarity**
5. **De-jargon (C7):** Workforce/Inventory **CV → "stability / swing"**; gloss s,S/R,Q as "reorder
   rule." 6. **De-duplicate onboarding ⇄ Profile (C6)** into one card. 7. **Strip "moved here from…"
   notes (C11).** 8. **Mark scope on Network (C9):** badge per-item sections vs global ones; make
   Supplier Master editable like Node Master. 9. **Put the real result above the synthetic grid (C10)**
   in Sourcing MRP & landed cost.

**P3 — honesty about scope**
10. **Make gating transparent (Plan):** when S&OP is trivial for the profile, say so instead of
    hiding it. 11. **Reposition Console** as run-control + Anatomy Lab + explainer; link to stages for
    results (C13). 12. **Scope the Lab's "live solve" claim** to the 6 engines that can, or extend the
    payload builders (C14).

---

# Part E — Self-critique (could this be better? — and what I got wrong)

- **I corrected myself twice this pass.** My first draft claimed Scenarios had "illustrative cards
  sitting beside solved KPIs" as the top trust risk. Reading the code properly, the illustrative
  **tornado is responsibly fenced behind `Advanced` with an explicit "not solved" label**, and a
  *solved* tornado is primary — that's good design, not a trap. The *real* stale surfaces are
  narrower and different: the **default Finance Cash tab** and the **Scenarios Cost tab**. I'd rather
  flag the precise thing than repeat a dramatic-but-wrong claim.
- **My severities are judgement, not measurement.** Every 🟥/🟧/🟨 is a grounded hypothesis about
  confusion, not a result from watching users. The honest next step is a scripted think-aloud (define
  a 2nd SKU and notice the shared BOM; commit all 6 SKUs; read Level-vs-Chase; find the PO plan;
  tell solved from illustrative on Finance and Scenarios) and count the stalls.
- **I may over-weight expert complaints.** Karthik's nav gripes and Divya's illustrative-tab catches
  are real, but Asha (first user) is hurt most by C2/C3/C4 — which is why those are P0/P1.
- **What I still didn't do at full depth:** the Home solver-network graph, the FX sub-tab, the
  changeover matrix internals, and *any* responsive/accessibility audit. Those are genuine gaps in
  this critique.
- **If I could ship one thing:** **P1 (sub-tab the long pages + a portfolio worklist).** Navigation
  and "am I done with all my SKUs?" cause more confusion than any single label — and the engine
  underneath is strong enough to deserve a calmer surface.

---

### Provenance note
Every section, field, badge and behaviour cited here was read from the live `.jsx` in `app_v2/` at
`main @ d5020e8`: the shared BOM from a single `bom:[` in `data.jsx` + `ProdBOM`/`SrcMRP` reading
`M.bom`; the illustrative defaults from `badge="illustrative"`/`run="seed"` props and the `FinCash`
"ILLUSTRATIVE seeds" comment; the dead Board-pack button from a handler-less `<Btn>`; the Lab's
six live-solvable engines from the `builders` map; the onboarding/profile duplication from `ONB_Q`
vs `SetupProfile`. No issue here is invented; each is traceable to a real component.
