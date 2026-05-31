# Redesign Blueprint — The Supply Chain Planner

**For: Claude Design (one-pass redesign brief). Author: SC/OR domain + the app's own engineer.**

This supersedes the earlier `HANDOFF_v1`. It is written the way a supply-chain professional
actually thinks about planning, because that is the root problem with the current app and with the
mockups: **the screens ask you to define things before the things they depend on exist.** You are
asked for warehouse storage and transport lanes before you have said what you make; you open
"Demand" with nowhere to enter history and no product selected; you "override" a forecast you can't
see. The fix is not prettier cards — it is to make the app follow the **dependency order of real
planning**, and to make every number answer three questions at all times: **which item? which
location? which period?**

Read Part 1 and Part 2 first. They are the contract. Parts 3–6 apply them screen by screen.

---

## PART 1 — The one mental model everything hangs on

A planner builds a plan in a fixed dependency order. Each layer can only be defined once the layer
above it exists. The app must mirror this exactly — as a guided spine, not 14 peer tabs.

```
              ┌─────────────────────────────────────────────────────────────┐
   DEFINE     │  WHO am I        →  Company · Calendar · Currency · Tax       │  (minutes)
   (master    │  WHAT I sell     →  Finished Goods (FG) — the products        │  ← MISSING TODAY
    data,     │  WHAT's inside   →  BOM: parts / sub-assemblies per FG        │
    once)     │  WHERE I operate →  Network nodes: plant · DC · supplier · cust│
              │  HOW it moves    →  Flows & lanes: inbound/part, outbound/FG  │
              │  WHERE I stand   →  On-hand inventory per item per location   │
              └───────────────────────────────┬─────────────────────────────┘
                                               │ (master data complete)
              ┌────────────────────────────────▼────────────────────────────┐
   PLAN       │  HOW MUCH will sell  →  Demand: history → forecast → consensus│
   (the       │  HOW MUCH to make    →  Aggregate S&OP (level vs chase)       │
    S&OP      │  WHICH mix is best   →  Profit-max product mix                │
    loop)     │  WHAT to buy & when  →  Procurement / MRP (per part)          │
              │  HOW to produce      →  Production schedule (per line, per day)│
              │  HOW to deliver      →  Distribution / transport optimization │
              └────────────────────────────────┬────────────────────────────┘
                                               │ (plan exists)
              ┌────────────────────────────────▼────────────────────────────┐
   DECIDE &   │  CAN I afford it   →  Finance · cash · NPV · WACC · capital   │
   MONITOR    │  WHAT could break  →  Risk · Monte Carlo · CVaR · scenarios   │
              │  HOW is it going   →  Control Tower / consolidated KPI deck   │
              └─────────────────────────────────────────────────────────────┘
```

**The golden rule for the redesign:** a screen in a lower band must be *unlockable-but-empty* until
its prerequisites exist, and must say so. "Demand" with no products shows: *"Define your products
first → [go to Products]."* It never shows an empty grid with no context.

---

## PART 2 — Six global concepts, defined ONCE, inherited by every screen

The mockups break because these were never defined globally. Define them once; every screen obeys.

### 2.1 Item identity — *"what product am I looking at?"* must never be ambiguous
Every quantity in the entire app is a triple: **(item, location, period)**.
- **item** = a Finished Good (FG) *or* a part/sub-assembly. Both have a code + name + UoM.
- The active item is always shown in a **persistent item selector** (top of every planning screen):
  `Product: [Widget-A ▾]  ·  view: [FG] [its parts]`. Sourcing, MPS, inventory, demand — all read
  that selector, so you always know whose numbers you're seeing.
- Multi-item screens (mix, dashboard) show a **roll-up with drill-down**, never a faceless total.

### 2.2 Time — grain + horizon, chosen once, honored everywhere (no hard-coded "w12")
A dedicated **Planning Horizon** definition (in Calendar) sets:
- **Grain**: day / week / month — the bucket size every solver and table uses.
- **Horizon**: number of buckets (e.g. 52 weeks, 12 months).
- **Multi-grain entry**: history/forecast can be *entered* at a finer grain and **roll up** (days→Σweeks→Σmonths); recommend days+weeks+months for short-life/fast SKUs, weeks+months otherwise. The UI states which grain improves accuracy for the data you have.
- Every period label is **derived from the calendar** (real dates: "Wk of 02-Jun", "Jun-26"), never a literal "w12". Promotions, cost events, MPS, schedules all index into the same bucket axis.

### 2.3 The four verbs — every item carries a policy for each
For each item the planner declares: **MAKE** (produce), **BUY** (procure), **MOVE** (transport),
**STORE** (hold). These policies are what the solvers consume. An FG is usually make+store+move; a
part is buy+move+store. This is the backbone that makes "for what product is what" knowable.

### 2.4 Flow is per-item and directional — not one generic plant→customer arrow
Real networks are: **inbound** (supplier → plant, *per part*) and **outbound** (plant → DC →
customer, *per FG*). The current single plant→customer flow is wrong for any multi-product firm.
The network must let you trace **one item's lane chain** end to end. Storage capacity is per
**node**, consumption of it is per **item** (volume/weight × qty), so "storage capacity and flow"
are modeled as item-aware, not a lump.

### 2.5 Drill-down everywhere — consolidation is only honest with a path down
Any aggregate KPI (margin, fill rate, OTIF, inventory, cash) must drill: **company → product
family → SKU → location → period**. A single consolidated number with no drill-down is not a
dashboard, it's a billboard. (See Part 4.1 — your dashboard question.)

### 2.6 The interpretation contract — every output states three things
No result card may show a number without: **(1) what it is** (one line), **(2) how it's computed**
(formula or source), **(3) what to do** (the action it implies). The old app had formula tooltips;
the mockups dropped them. They come back, on every output.

---

## PART 3 — The new information architecture (screen by screen, in flow order)

14 flat tabs → **3 bands, 13 stages**, walked top-to-bottom. Inside a stage, group by *sub-question*,
not by an arbitrary count of sub-tabs. **Rule: a stage gets a second sub-tab only when it answers a
genuinely different question — never "7 sub-tabs because the cards didn't fit."**

Legend per stage: **Prereq** (what must exist) · **Define** (inputs) · **See** (outputs +
interpretation) · **Item/Period** (how identity & time show up) · **Feeds** (solver/next stage).

---

### BAND A — DEFINE (master data, set once, rarely changed)

#### A0 · Company & Calendar
- **Prereq:** none (entry point).
- **Define:** legal identity, **currency**, plant state, GST, tax rate, service-level target; then
  the **Planning Horizon** (§2.2): grain, # buckets, workdays, holidays. MSME tier auto-derives
  from turnover/investment you enter once — don't ask twice.
- **See:** a one-line plan summary: *"Planning 52 weekly buckets, 02-Jun-26 → 31-May-27, ₹, 95%
  service."* That sentence is the contract every later screen cites.
- **Fix the clutter:** Company Profile today is an unreadable wall. Make it a **3-field header**
  (name, currency, home location) + an "Advanced ▸" reveal for tax/GST/service. MSME is a single
  derived badge, not a section. **No WACC, no working capital, no payment ledger here** — those are
  Finance (you were right; move them out entirely).

#### A1 · Products (Finished Goods) — **THE MISSING FIRST SCREEN**
- **Prereq:** A0.
- **Define:** *what you actually sell.* One row per FG: code, name, family/category, UoM,
  sell price, the four-verb policy (§2.3), MTO/MTS mode, shelf-life, unit volume/weight (for storage
  & freight). **This is where a new user starts after setup — not BOM.** Today the app jumps
  straight to BOM with no product declared; that is the single most disorienting thing in it.
- **See:** the product catalog as cards (name big, price, margin once costs exist, lifecycle stage).
- **Item/Period:** this screen *creates* the item identities everything else references.
- **Feeds:** every downstream screen's item selector.

#### A2 · Bill of Materials (per product)
- **Prereq:** A1 (a product is selected — the header shows *"BOM for: Widget-A"*).
- **Define:** the parts/sub-assemblies consumed per unit of the selected FG. Split the ~15-field
  row you complained about into **two clean groups behind tabs *within the row*, not new screens**:
  - **Physical:** part, qty-per, scrap/yield, UoM, sub-assembly nesting.
  - **Commercial (buy terms):** unit cost, supplier, MOQ/max, ordering cost S, lead time, holding %,
    payment terms, **time-varying price** (a small period→price schedule for contracts that change).
- **See:** an indented **BOM tree** for the selected FG (FG → sub-assembly → raw), with rolled-up
  material cost. Now "what sub-product am I looking at" is answered by position in the tree.
- **Item/Period:** part rows are items too; their buy-terms are period-aware (contract price steps).
- **Feeds:** Procurement/MRP, landed cost, profit mix.

#### A3 · Network (nodes)
- **Prereq:** A1 (so nodes can hold items).
- **Define:** physical sites — plants, DCs/warehouses, suppliers, customers/regions — each with
  location (for distance), and **per-item storage capacity** (volume or pallet, consumed by item
  volume × qty).
- **See:** a network map; click a node → what items it makes/stores/ships.
- **Item/Period:** capacity is per node; **utilization** is computed per item per period.
- **Feeds:** flows (A4), distribution (B6), center-of-gravity.

#### A4 · Flows & Transport (inbound per part, outbound per FG)
- **Prereq:** A2 (parts) + A3 (nodes).
- **Define, directionally:**
  - **Inbound lanes** — supplier → plant, *one chain per purchased part*, with mode (FTL/LTL/Sea/
    Air/Rail), rate, lead time, CO₂, and **contract type** (spot / fixed-period / volume-commit /
    take-or-pay) including **time-varying rates**.
  - **Outbound lanes** — plant → DC → customer, *per FG*, same mode/rate/contract structure.
- **See:** select an item → its full lane chain lights up end-to-end with cost & lead time per hop.
  This is the answer to "does anybody know for what product is what" — yes, because lanes are
  item-scoped and traceable.
- **Item/Period:** rates are period-indexed (contract escalation lands in the right bucket).
- **Feeds:** procurement (inbound landed cost), transport optimization & consolidation (outbound).

#### A5 · Starting Inventory (on-hand)
- **Prereq:** A1+A2 (items) + A3 (locations).
- **Define:** opening stock **per item per location** — only now does this make sense, because the
  items and locations exist. A simple matrix: rows = items (FG + parts), cols = locations.
- **See:** total opening stock value; coverage in periods of demand once demand exists.
- **Feeds:** every solver's `init_inventory` / `onHand`.

> **Why A3–A5 were broken before:** they were on the Setup tab *before* products existed. With the
> spine above, by the time you reach them the items are defined, so "storage for what / lane for
> what / on-hand of what" all have answers.

---

### BAND B — PLAN (the S&OP loop; this is where the solvers live)

#### B1 · Demand Planning
- **Prereq:** A1 (a product selected).
- **Define / enter:**
  - **History** — per selected product, at the chosen grain, with **multi-grain entry** (§2.2). The
    screen must *open with a place to enter or import history*, not an empty forecast. If history is
    thin, it says so and routes you to the right method (see below).
  - **Promotions/events** — attached to **real periods** off the calendar axis (no "w12" literals).
- **See & interpret (this is where the mockups were emptiest):**
  - **Forecast competition** — one card, each model with its **formula + plain-English note**
    (Holt-Winters, ARIMA, Croston/SBA/TSB for intermittent), ranked by **MASE / bias / tracking
    signal**, each defined inline. *"MASE < 1 ⇒ beats naïve; tracking signal outside ±4 ⇒ biased,
    re-fit."*
  - **Low-data path** — when you have <12 points the UI explains exactly what runs (classical/Croston
    only), what it can and can't promise, and shows the ML/DL tiers unlocking as data grows
    (12–36 → +RandomForest; 36+ → +XGBoost/DL). When you hit **Run ML models**, results render
    **inline right there** (leaderboard + chosen forecast overlaid on history), not on a far tab.
  - **ABC/XYZ** — states *what feeds it* (ABC = annual value Pareto; XYZ = demand CV) and *what to
    do* (AX = tight control/low stock; CZ = review or make-to-order).
  - **Lifecycle curve** — show the derivation (NPI ramp / maturity / decline coefficients) and which
    history it was fit to.
  - **Override** — only meaningful **next to the forecast it edits and the schedule it will move**;
    show statistical vs. overridden side by side with an audit trail. Never an override box with
    nothing to override.
- **Item/Period:** product selector + calendar axis throughout.
- **Feeds:** Aggregate plan, profit mix, procurement, MC.

#### B2 · Aggregate Plan / S&OP (the bridge)
- **Prereq:** B1.
- **Define:** capacity, workforce, hire/fire/OT costs, inventory vs backorder costs.
- **See:** **level vs chase** as the hero result (this is the whole point), seasonal pre-build,
  workforce ramp, and **capacity shadow prices** (₹ value of one more hour) — which visibly hand off
  to the capital screen. Interpretation: *"chase is cheaper here because holding > hire/fire; the
  binding month is Sep at ₹X/hr — candidate for capacity."*
- **Feeds:** profit mix, capital (shadow price), closed-loop reconciliation.

#### B3 · Profit Mix (what to make, how much)
- **Prereq:** B1 (demand) + A2 (costs) + A3/A4 (capacity & freight).
- **See:** optimal quantity per FG, contribution margin, **which constraint binds** (capacity /
  demand ceiling / budget / material), shadow prices, and the cannibalization/fixed-charge effects.
- **Feeds:** procurement & production receive these quantities.

#### B4 · Procurement / MRP (what to buy, when — per part)
- **Prereq:** B3 (or demand) + A2 (buy terms) + A4 (inbound lanes).
- **See, per part (selector-scoped):** MRP explosion (gross→net→planned orders) on the **calendar
  axis**, PO schedule, **(s,S)/(R,Q) reorder policy** with the EOQ/safety-stock formulas shown,
  regime-aware sourcing, landed-cost build-up. Every PO row says which part, which supplier, which
  lane, which bucket.
- **Feeds:** cash (AP timing), production (material availability).

#### B5 · Production Schedule (how to make — per line, **per day**)
- **Prereq:** B3 + the factory model (lines→stages→machines/OEE).
- **Define:** the line/stage/machine tree (sole owner of cycle-time & OEE — Products should *not*
  re-ask these; derive throughput = machines × 60/cycle × OEE, line = min(stage) bottleneck).
- **See:** **day-level** schedule (not just "some week"), Gantt, sequence-dependent changeover
  (with the minutes saved vs naïve order), line×period matrix, **ATP/CTP** explained inline:
  - **ATP** (Available-to-Promise) = uncommitted finished stock + scheduled receipts you can still
    sell. **CTP** (Capable-to-Promise) = ATP + what you could still *produce* in time given capacity.
    Show them as "you can promise N units by date D" with the date math visible.
- **Feeds:** distribution, fulfillment, control tower.

#### B6 · Distribution / Transport optimization (outbound)
- **Prereq:** B3/B5 (what's produced) + A4 (outbound lanes).
- **See:** mode selection, **allocation** (which DC serves which customer — a transportation LP),
  **consolidation** (LTL→FTL / LCL→FCL with the saving), per-lane cost. This is a *network-flow*
  result — represent it as a flow map, not a Monte-Carlo-style chart (see Part 4.4).
- **Feeds:** logistics cost into finance, OTIF into control tower.

> **Note on the "Optimize / Console" god-tab:** there is **one** end-to-end pipeline
> (Forecast→Aggregate→Mix→[Procure+Produce+Sequence]→Transport), optionally wrapped by closed-loop
> reconciliation and a risk overlay. It is **not** "6 pipelines." Keep a thin **Run Console** (pick
> a stage or "run all", set constraint toggles, hit solve, read status/objective/binding
> constraints) but **the results belong in B3–B6 above**, next to their inputs — not dumped together.

---

### BAND C — DECIDE & MONITOR

#### C1 · Finance & Capital (consolidated, single owner)
- **Prereq:** plan exists (costs, POs, schedule).
- **Owns (move here in full):** WACC (one editor), NPV/IRR, depreciation, working capital & CCC,
  payment ledger, budget vs actual, **CAC** (full economics; Setup keeps at most a read-only
  anchor), buy-vs-lease, FX hedging, **endogenous-capacity capital plan** (consumes B2 shadow
  prices). Group by audience: *Cash · Capital · Costs · Treasury* — four sub-views, because finance
  genuinely has four audiences, not seven arbitrary ones.
- **See:** each with formula + interpretation (WACC: *"discount rate = blended cost of money; raise
  it and only the strongest projects survive"*).

#### C2 · Risk & Scenarios
- **See:** **Monte Carlo** (a *simulation* — perturb demand/lead-time/price ±, re-run, show the
  distribution, VaR/CVaR, fragility — represent as a histogram/fan chart, explicitly "1000 runs"),
  **CVaR-robust** stock, sensitivity tornado, and **one unified scenario store** (supply delay /
  price spike / demand surge / quality fail → which solver input each perturbs). Today scenarios live
  in three places (Analysis, Command, SAP) — collapse to one.

#### C3 · Control Tower / Command (the consolidated deck)
- **See:** the executive roll-up — margin, fill rate, OTIF, inventory, cash — **with drill-down**
  (§2.5) and **alerts**. This is legitimately the same alert engine referenced on the Risk screen;
  surfacing it in two places is fine **only if it's literally one source** (one alert list, two
  views) — label it so, don't compute it twice.

---

## PART 4 — Direct answers to your specific questions

**4.1 Do companies really have one consolidated dashboard (margin/fill/OTIF/inv/cash)? Single vs
many products?** Yes — it's the standard S&OP / control-tower executive view, and CFO/COO decks look
exactly like that. **But it is only useful with drill-down and segmentation.** For a *single*
product the consolidated view *is* that product — fine, but still show it per period and per
location. For *many* products, a flat company total hides everything; the dashboard must drill
company → family → SKU → location → period, and segment by ABC/XYZ. So: keep the dashboard, kill the
faceless totals — every tile drills.

**4.2 Do we have 7 solvers, and is the "how they communicate" flow accurate?** No — there are ~16
engines (procurement, production, sequencing, profitmix, transport, consolidate, aggregate, cvar,
montecarlo, capital, capital-capacity, policy, reconcile, lotsizing, forecast, rolling). The "7
solvers" diagram is outdated marketing. The **real** communication graph is the BAND-B chain:
`forecast → aggregate(S&OP) → profitmix → {procurement, production→sequence} → transport`, with
**reconcile** as the closed loop and **cvar/montecarlo** as a risk overlay, **capital** consuming
aggregate's shadow prices. Draw *that*, with live arrows showing which output feeds which input.
The console's version differs from Command's because both are hand-drawn mockups — replace both with
the single generated graph above.

**4.3 What is "the pipeline"? Why 6 of them?** There is exactly **one** pipeline — the end-to-end
solve chain in 4.2. "6 pipelines" is a mockup placeholder, not a real concept. Show one pipeline
with stage badges (✓ done / ▷ ready / ◌ blocked-needs-input).

**4.4 Monte Carlo vs Transport — represent them differently.** They are different *kinds* of result:
MC is a **stochastic simulation** → fan chart / histogram + VaR/CVaR, labelled "N runs". Transport is
a **deterministic network-flow optimization** → a flow map (nodes, lanes, volumes) + a cost table.
Don't give them the same generic bar card.

**4.5 Control Tower in two places?** Acceptable **iff** it's one alert source rendered twice (a
summary on the dashboard, the full list on Risk). Not acceptable if each recomputes. Make it one
engine, two views, and say so.

**4.6 MPS / schedules only weekly?** They must support **day-level** breakdown (with weekly/monthly
roll-up via the grain control). A schedule a planner can't read day-by-day isn't executable.

**4.7 ATP / CTP / changeover unclear?** Define them inline (4 above, B5). Changeover = the
sequence-dependent setup time between products on a line; the solver finds the run order minimizing
total changeover — show the order and the minutes saved.

**4.8 WACC / CAC on Setup?** Move both to Finance entirely. If a WACC value must appear elsewhere,
show it **read-only with a link to edit in Finance**. One editor, one source.

**4.9 Why not 7–8 sub-tabs per tab?** Don't. A sub-tab is justified only by a *different question*.
Finance has four audiences (cash/capital/costs/treasury) → four sub-views. Most stages need **zero**
sub-tabs — just a clean vertical flow. The cure for a long tab is the **spine + drill-down**, not
nested tabs a newcomer has to hunt through.

**4.10 Promotions / period-awareness everywhere.** Every time-bound input (promotions, cost events,
contract prices, MPS, schedule) indexes into the **one calendar bucket axis** from A0, shown as real
dates. No hard-coded "w12" anywhere.

---

## PART 5 — Interpretation library (attach to every output; this is what the mockups dropped)

| Output | What it is | Formula / source | What to do |
|---|---|---|---|
| Safety stock | Buffer for demand/LT variability | `z·σ_LTD` (z from service level) | Raise service → more stock; tune per ABC/XYZ |
| Reorder point | When to reorder | `μ_LT + SS` | Place PO when on-hand ≤ ROP |
| EOQ | Cost-optimal order qty | `√(2DS/h)` | Batch near EOQ; respect MOQ |
| (s,S)/(R,Q) | Reorder policy | s=ROP, S=s+EOQ | Continuous (AX) vs periodic (CZ) |
| MASE | Forecast accuracy | MAE / naïve-MAE | <1 = good; >1 = use naïve |
| Tracking signal | Forecast bias | Σerror / MAD | Outside ±4 ⇒ re-fit |
| Shadow price | Value of +1 unit capacity | LP dual | Compare to cost of adding it (→ capital) |
| CVaR | Expected loss in worst β-tail | R-U LP | Robust stock vs expected-value stock |
| OTIF | On-time-in-full | orders met fully & on time / total | <95% ⇒ root-cause lane/supplier |
| ATP / CTP | Promisable now / producible-in-time | on-hand+receipts / +capacity | Quote dates to sales |
| Contribution margin | Profit per unit before fixed | price − variable cost | Mix toward high-CM under the binding constraint |

---

## PART 6 — Rules for Claude Design (so it lands in one pass)

1. **Build the spine, not 14 peer tabs.** Bands A→B→C, stages in order, with a persistent **pipeline
   ribbon** showing stage state (done / ready / blocked).
2. **Persistent item selector + period axis** on every planning screen (§2.1, §2.2). Every number
   answers item/location/period.
3. **Gate, don't dump.** A stage with unmet prerequisites shows a one-line "define X first → link",
   never an empty grid.
4. **Sub-tabs only for genuinely different questions.** Default to zero. (Finance = 4, justified.)
5. **Every output carries the interpretation contract** (§2.6) — what/formula/action. Restore the
   `SectionInfo` ⓘ pattern.
6. **Day-level where execution happens** (MPS, schedule), roll-up via the grain control.
7. **Don't touch** state keys, reducer actions, solver payload contracts (camelCase UI ↔ snake_case
   API), or component props. Restyle and re-sequence; preserve wiring. (Inventory of existing
   components & bindings: see `HANDOFF_v1_superseded.md` §3/§5 in this folder — still accurate for
   *what exists*; this blueprint defines *how it should be arranged*.)
8. **One network-flow visual, one simulation visual, one solver-graph** — generated from the real
   chain in 4.2, not redrawn by hand.

**Deliverable from design:** the same single-file React+Babel SPA, re-sequenced into this spine,
every screen honoring §2, nothing half-defined.
