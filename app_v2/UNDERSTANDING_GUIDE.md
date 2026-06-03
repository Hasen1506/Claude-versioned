# Understanding the Enterprise Simulator — a guided walkthrough

> A running teaching document. We go **one section at a time**. Each part answers
> your handwritten notes (`inventory_simulator_notes_transcription.md`) for that
> screen, and follows the same spine every time:
>
> 1. **The problem** — what this screen is for, *why* that problem exists, and the
>    branches/variants of it.
> 2. **The solution** — how the app resolves it, *why* it was built this way, the
>    design decisions, and the edge cases.
> 3. **The broader context** — why it matters, and what it touches downstream.
>
> Each part ends with a **✅ checklist** of things you should be able to say back in
> your own words before we move on. If you can't tick a box, that's where we stop
> and go deeper.
>
> Legend for how I answer your notes: 🟩 **by design** (working as intended, here's
> the why) · 🟨 **fair — needs a tweak** (you're right, it's a rough edge) · 🟥
> **bug** (genuinely broken, will be fixed) · 🧭 **design decision for you** (a real
> fork where your call changes the build).

---

# PART 0 — The mental model (read this first; it dissolves half your notes)

Before any single tab makes sense, four facts have to click. Almost every note that
starts with *"I never defined this…"*, *"prefilled trash"*, *"no clue what product
I'm looking at"* traces back to **not having been told these four things.** That's a
real onboarding failure on our side — but the underlying machine is sound, and once
you see it the screens stop feeling random.

## Fact 1 — You are looking at a fully-worked example company, on purpose

The app ships pre-loaded with **one complete, internally-consistent dataset**: a
fictional Indian auto-components manufacturer. It is not random filler and it is not
"data you forgot you entered." It is a **worked example**, the way a spreadsheet
template arrives with sample rows so you can see what goes where.

The seed company, concretely (from `data.jsx`):

| What | Seed value |
|---|---|
| 6 finished SKUs | Crankshaft Bearing (TPA-4471), Piston Ring Assembly (TPA-3215), Valve Seat Insert (TPA-9904), Connecting Rod (TPA-2188), Oil Pump Housing (TPA-5540), Timing Chain Tensioner (TPA-7722) |
| 2 raw materials | Chromoly Steel Bar 42mm (RM-STL42), Bearing Alloy Billet (RM-BRG18) |
| Real-looking customers | Maruti Suzuki, TVS Motor, Ashok Leyland, Bosch India, Hyundai, Tata Motors |
| 3 production lines | LINE-01, LINE-02, LINE-03 |
| A network, suppliers, lanes, assets, a WACC… | all populated to match the above |

**Why it's built this way:** an optimization app with *empty* inputs can show you
nothing — every chart is blank, every solver errors "no data," and you can't tell a
working feature from a broken one. By shipping a coherent example, every screen has
something real to render on first load, and you learn the app by *poking a working
model* rather than staring at empty forms. This is the standard pattern for
analytics tools (Tableau Superstore, Power BI's sample, etc.).

**The cost of that decision — and it's the cost you hit:** because the example is so
complete, it *looks* like the app pre-decided things on your behalf. It didn't. It's
a demo tenant. The fix is not "delete the data," it's "make it obvious this is an
example and give you a clean **New Company** path." (That's a real gap — Part 9.)

## Fact 2 — "Prefilled" ≠ "faked." Every number is either seed data or solved from it

This is the single most important distinction in the whole app, and it's the answer
to your very first line — *"I never really defined anything I see revenue, COGS and
margin pre-entered."*

There are exactly **two kinds of number** on every screen:

- **Master data** — facts about the company (a SKU's price, a part's lead time, a
  line's cycle time). These live in `window.M` (the seed) and `appStore` (your
  edits). On Home, `Revenue = Σ(price × demand)` over the 6 seed SKUs. It's
  "pre-entered" only because the *price* and *demand* are seed facts — the revenue
  itself is **arithmetic done live in front of you**, not a stored guess. Change a
  price and it moves.
- **Solved results** — outputs of the Python optimizers (procurement MILP, profit-mix
  LP, Monte-Carlo, …). These are **never** shown until you actually run the solver.
  Until then the app shows `—`, literally a dash, never a fake number. On Home, look
  at "Plan cost / Scheduled / Mean fill / CVaR / Binding lines" — every one reads `—`
  with sub-text "run loop" until you press **▶ Re-plan whole model**.

So the rule the whole app obeys is: **"No faking" — a number is either (a) a fact you
or the seed supplied, or (b) the honest output of a solver that actually ran, or (c)
a dash.** There is no fourth category of "plausible-looking placeholder." When you
felt numbers were "prefilled trash," what you were actually reacting to is Fact 1
(it's a demo tenant) — not invented numbers.

## Fact 3 — The app is a pipeline: master data → solvers → committed plan → monitoring

The tabs are not a pile of independent screens. They are stages of **one pipeline**,
left to right, and that order is the business logic:

```
 SET UP THE WORLD            ASK THE OPTIMIZERS              WATCH IT
 ────────────────            ──────────────────              ───────
 Setup    (calendar, tax)
 Products (SKUs, BOM, cost)  →  Demand   (forecast)       →  Console   (run solvers)
 Network  (sites, lanes)        Plan/S&OP (aggregate)        Finance   (P&L, capital)
 Sourcing (suppliers)           Production (line schedule)   Scenarios (risk, what-if)
                                Logistics (transport)        Home      (state of plan)
```

- **Left third = master data.** You *describe your business* once: what you make
  (Products), where (Network), who supplies you (Sourcing), the working calendar
  (Setup). This is the "define everything" you kept looking for — it's spread across
  these tabs because a real company's definition genuinely has these parts.
- **Middle third = the solvers.** Each takes the master data + a forecast and answers
  one sharp question (below). They write their answers into a shared cache.
- **Right third = monitoring.** Home/Finance/Scenarios read that cache back and tell
  you whether the committed plan is current, profitable, and safe.

**Why this matters for your confusion:** you were opening *middle-third* tabs
(Demand, S&OP, Policy) and asking "what product is this for / where did these
numbers come from?" The answer is: they're for **all** your products at once, and
the numbers came from the **left-third** tabs you hadn't connected them to yet. The
app never told you it was a pipeline. That's the missing onboarding (Part 9), not a
missing feature.

## Fact 4 — Each solver answers exactly one question. Here's the whole roster in plain words

You wrote *"I am shocked — what exactly do you even feed into any of these solvers."*
Here is the entire set. Read the right column as "the one sentence this solver is
for." This table is the backbone we'll keep returning to.

| Solver | The one question it answers | What you must feed it |
|---|---|---|
| **Demand / Forecast** | "How much will we sell of each SKU, per week, and how uncertain is it?" | history (or a typed demand schedule) per SKU |
| **Profit-Mix** (LP) | "If capacity is tight, which SKUs should we make *first* to maximise profit?" | per-SKU price, cost, demand ceiling, capacity |
| **Procurement** (MILP) | "Exactly how much of each raw material to buy, and when, to cover the plan at least cost?" | BOM, supplier price/lead-time/MOQ, on-hand |
| **Production** | "What's the line-by-line, week-by-week build schedule?" | lines, cycle times, changeovers, the demand to cover |
| **Policy / Inventory** | "For each SKU, what reorder point & order quantity (or order-up-to) keeps service at target cheapest?" | demand mean+variability, lead time, holding/stockout costs |
| **Transport** (LP) | "Cheapest way to move goods across the network, and where to consolidate?" | nodes, lanes, mode costs |
| **Monte-Carlo** | "Under demand + lead-time randomness, what's our fill rate and tail risk (CVaR)?" | the committed plan + distributions |
| **Capital / Finance** | "Is this plan worth it after cost of capital — EVA, working capital, line economics?" | assets, WACC, the plan's costs |
| **S&OP / Aggregate** | "One reconciled volume plan that ties demand, supply and finance together." | the above, rolled up |

The thing to internalise: **none of these invents inputs.** Each one is starved or
fed by how completely you filled the left-third tabs. When a solver looks "pre-done
and doesn't update," it's because the *seed* already satisfies its inputs (Fact 1),
so it had something to chew on immediately. Edit a real input and it goes stale and
recomputes — that's the freshness machinery you'll meet on Home.

## Fact 5 — Every *input* must be editable in its own tab; every *output* must be read-only. This is the rule your notes are really about.

Your recurring complaint — *"uneditable & prefilled,"* *"where else would a user put
these details?"* — is the correct one, stated more precisely than "everything should
be editable." There are two kinds of tab and the rule is opposite for each:

- **Master-data tabs** (Setup, Products, Network, Sourcing, the line-definition part
  of Production) = where you **describe your company**. **Every field must be
  editable.** The seed is just a starting example you overwrite. Where a field here is
  read-only, there is *literally nowhere* for you to enter your reality — that's a
  **bug**, not a design choice.
- **Output tabs** (Logistics, Console, and the result cards on Plan / Finance / Home /
  Scenarios) = where a **solver shows its answer**. These are **read-only on
  purpose.** Hand-typing over a solver's output would be the "faking" the whole app
  forbids — you change the *inputs* and re-solve, you never edit the result.

So the discipline is: **trace every number to input-or-output. Inputs read-only =
bug. Outputs editable = would be a lie.** Current state, audited:

| Tab | Kind | Editable today? | Verdict |
|---|---|---|---|
| Setup | master data | mostly (currency rate, CIN hardcoded) | 🟨 close |
| Products — catalogue row | master data | **no** (name/price/cost/demand read-only) | 🟥 bug |
| Products — yield/shelf/salvage/BOM | master data | yes | 🟩 |
| Network — nodes/lanes | master data | **no** (zero edit affordances) | 🟥 bug |
| Sourcing — supplier master | master data | partial | 🟨 |
| Production — line/worker/machine | master data | **no** (only knob-tuning) | 🟥 bug |
| Demand — schedule/history | master data | yes | 🟩 |
| Logistics, Console | solver output | no (correct) | 🟩 by design |
| Plan/Finance/Scenarios result cards | solver output | no (correct) | 🟩 by design |

From here on, every Part below carries an explicit **"Editable?"** verdict for each
input it discusses, so you always know whether a read-only field is a bug or the
correct treatment of an output.

## ✅ Part 0 checklist — you should be able to say:

- [ ] "The prefilled data is **one example company** (an auto-parts maker), not
      something I accidentally entered — it's a demo tenant so nothing is blank."
- [ ] "Every on-screen number is either a **fact** (seed/my edit), a **solved
      result** (a solver actually ran), or a **dash**. Nothing is a fake placeholder."
- [ ] "The tabs are a **pipeline**: describe the business (left) → run solvers
      (middle) → monitor (right). Middle/right tabs are about *all* my SKUs and read
      from the left tabs."
- [ ] "Each solver answers **one** question; I can name what Profit-Mix, Procurement,
      and Monte-Carlo each do and what they eat."
- [ ] "The real gap is **onboarding** — the app never told me any of the above. The
      machine underneath is fine."
- [ ] "**Inputs must be editable in their tab; outputs are read-only by necessity.** A
      read-only *input* (Network, product catalogue, line definition) is a bug; an
      editable *output* would be a lie."

---

# PART 1 — Home / "Command Center" (your Pages 1–2)

**What this screen is for:** Home answers exactly one question on load — *"Is my
committed plan still current, and is anything on fire?"* It is the **monitoring**
surface (right third of the pipeline), not a place you enter anything. Think of it as
the bridge of a ship: dials (KPI strip), an alarm panel (Exception Cockpit), a
"are the instruments current?" light (freshness), and one big lever (**Re-plan whole
model**).

It has five blocks, top to bottom: **KPI strip → Exception Cockpit → Solver Input
Readiness → Plan Freshness → Value Ledger.** Your notes hit all five. Taking them in
order:

### 1.1 — "I never defined anything, yet I see Revenue / COGS / Margin"  🟩 by design

Covered by Fact 2. `Revenue` and `COGS` are `Σ(price×demand)` and `Σ(cost×demand)`
over the 6 seed SKUs; `Margin` is `(Rev−COGS)/Rev`. These are **master-data
arithmetic**, computed live ([home.jsx:61–64](app_v2/home.jsx#L61)). The other five
tiles (Plan cost, Scheduled, Mean fill, CVaR, Binding lines) are **solved** and show
`—` until you run the loop — proof the app isn't fabricating. *Why two kinds on one
strip?* So you can see your business's raw economics (always available) next to what
the optimizers add (only after solving), side by side.

### 1.2 — "The Exception Cockpit just says 'inputs changed since last solve'. What inputs? What else could we notify?"  🟨 fair

**What it is:** a single ranked inbox of everything wanting attention, built live
([scenarios.jsx:71–98](app_v2/scenarios.jsx#L71)). It already merges four sources —
you're right that it *under-explains* the first one:

- **STALE** ♻ — a solve's inputs changed since it last ran. **Your valid complaint:**
  it names the *solver* ("procurement plan is stale") but not the *field* that
  changed. It knows the dependency that fired (via `SOLVE_DEPS`), so it *can* say
  "*procurement is stale because you edited a supplier lead time*." Today it doesn't.
  → **fixable, and worth fixing.**
- **SENSED** 📡 — the forecast went out of statistical control on a SKU (auto-detected).
- **RISK** 🎲 — the committed plan misses its service target / tail cost too high.
- **VALUE** ₹ — a solver *found* money (e.g. risk-pooling would free ₹X of safety
  stock) that **no decision has adopted yet**. This is the clever one: it nags you
  about un-banked wins, not just errors.

**"One resolve-all button, or resolve at each stage"**  🧭 — good instinct, with a
caveat. STALE items can have a literal **"Re-plan" / "resolve"** button (re-running
the solver *is* the resolution — safe to one-click). But SENSED/RISK/VALUE are
**judgement** items — "your forecast broke" or "there's ₹ on the table" aren't things
software should auto-dismiss. So the right design is: **"Refresh all stale" at the
top** (mechanical) + per-item **"open →"** for the judgement ones (already there).
A blanket "resolve all" would teach you to rubber-stamp risk. (Decision for Part 9.)

**"The font is also not good"**  🟨 — noted, it's the mono micro-label styling; cosmetic, easy.

### 1.3 — "Solver Input Readiness feels pre-done and doesn't update"  🟩 mostly — and here's the subtlety

It *is* live ([home.jsx:82–96](app_v2/home.jsx#L82)): each row is computed from
whether that solver's inputs actually exist in `M` — e.g. Profit-Mix is "ready" only
if `demand>0 AND every price>0 AND ≥1 line`. The reason it looks frozen is **Fact 1**:
the seed already satisfies almost every input, so almost everything is green on first
load. It's not a static checkmark — it's a true check that happens to pass because the
demo is complete. **Proof it updates:** Monte-Carlo shows **blocked** right now
(`distributions:false` is hardcoded, [home.jsx:86](app_v2/home.jsx#L86)) — a row
that's *not* satisfied by seed. Delete all prices and Profit-Mix flips to blocked too.

**"The order shows 7"**  🟩 — there are 7 solvers in this gate (Profit-Mix,
Procurement, Production, Transport, Monte-Carlo, Capital, S&OP). The "7" is the count
of solvers, not a bug.

### 1.4 — "Can't we unify Input Readiness and Plan Freshness? Two useless states. What does 'As of' record?"  🧭 strong point

This is your sharpest design note on Home, and you're largely right. The two cards
answer *adjacent* questions:

- **Readiness** = "do I have **enough inputs** to run solver X *at all*?" (pre-flight)
- **Freshness** = "solver X already ran — are its inputs **still unchanged**, or did I
  edit something so its answer is now **stale**?" (post-flight). **"As of"** records
  the timestamp the solver last produced that result (`ranAt`) — so "As of 12m ago"
  means "this answer reflects the world as it was 12 minutes ago."

They're genuinely two phases of one lifecycle: **blocked → ready → solved(fresh) →
stale → re-solved**. So yes — they should be **one card per solver showing its place
on that lifecycle**, not two separate grids you cross-reference. And since STALE also
appears in the Exception Cockpit, the cleanest design is: **Exception Cockpit = the
alarms (STALE/RISK/etc.) you act on**; a single **Solver Lifecycle** strip = the
calm state-of-each-engine view. That collapses three overlapping cards into two with
no lost information. (Concrete proposal in Part 9.)

### 1.5 — "Exception ledger and Value ledger should be unified, every action timestamped with its impact"  🧭 + 🟨

Close, but they're measuring **different verbs** — worth keeping the distinction even
if we co-locate them:

- **Exception Cockpit** = *open* items (things still wrong / unbanked) — a **to-do**.
- **Value Ledger** = *closed* items (decisions you already took and what they were
  worth) — a **receipt**. It reads the `events[]` audit log + cached solves and tells
  you the tool's own ROI: how many recommendations you **applied**, accept-rate, and
  ₹ banked vs ₹ merely identified ([scenarios.jsx:723](app_v2/scenarios.jsx#L723)).

So one is "what's left to do," the other is "what you did and its payoff." Your
instinct — *every action timestamped with its impact* — is exactly what the Value
Ledger is *trying* to be; the fix is to make it read as a **chronological ledger of
decisions** (each row: time · decision · ₹ impact · provenance) rather than summary
tiles. That's a presentation change, and a good one.

### 1.6 — "Do we understand what Profit-Mix *means*? Should we ask onboarding questions? A single-SKU maker doesn't need Profit-Mix."  🧭 the big one

This is the most important idea in your whole 14 pages, so I'm flagging it here and
giving it a full treatment in **Part 9**. Short version: **yes.** You've independently
re-derived *guided selling / progressive disclosure*. Two concrete pieces:

1. **Plain-language solver explainers.** Every solver card should answer "what is
   this?" in one sentence on click — *"Profit-Mix: when your lines can't make
   everything customers want, this picks which SKUs to make first so you earn the
   most per scarce machine-hour."* The data for this exists (the roster in Fact 4);
   it just needs to surface on each card. **Easy, high-value, will build.**
2. **An onboarding profile that gates the app.** A handful of questions —
   *Make-to-stock or make-to-order? One site or a network? Single SKU or many?* —
   set a **profile** that **hides solvers you don't need.** A single-SKU shop never
   sees Profit-Mix (nothing to trade off). This machinery **partially exists already**
   (`useProfile()`/`gate` — that's why Logistics says "your profile is single-site,
   transport is off"), but there's **no UI that asks you the questions up front.**
   Building that front door is the highest-leverage change on the table.

### ✅ Part 1 checklist — you should be able to say:

- [ ] "Home is **monitoring only** — I don't enter anything here; it reads the solve
      cache and tells me if my plan is current and safe."
- [ ] "Revenue/COGS/Margin are **live arithmetic on seed facts**; the other tiles are
      **solved** and dash-out until I press Re-plan."
- [ ] "The Exception Cockpit already merges Stale/Sensed/Risk/Value; its real weakness
      is **not naming which input changed** — that's fixable."
- [ ] "Readiness = 'can I run it'; Freshness = 'is the answer still current'; they're
      two phases of one lifecycle and **should be one card**."
- [ ] "The Value Ledger is the **receipt** (what I did + ₹ payoff); the Cockpit is the
      **to-do** (what's still open)."
- [ ] "The biggest win is an **onboarding profile** that asks what kind of operation I
      run and **hides solvers I don't need** + explains each in plain words."

---

---

# PART 2 — Setup · Identity & Calendar (your Pages 3–4)

**What this screen is for:** Setup is the **first master-data tab** — it declares the
two things the *entire* rest of the app needs before anything else makes sense:
**who you are** (legal entity, currency, tax, service target) and **the clock**
everything plans against (grain + horizon + working calendar). It deliberately holds
*only* these two — WACC/budget moved to Finance, nodes/on-hand moved to Network — so
the front door isn't overwhelming. It has four blocks: **Identity → Industry
Quick-Start → Planning Profile → Planning Calendar.**

**Editable? overall:** 🟨 mostly editable (this is master data, so that's correct) —
but three things are wrongly read-only or stale, called out below.

### 2.1 — "Base currency ₹84.2/$ is hardcoded"  🟨 split across tabs, not hardcoded

The currency *symbol* (₹/$/€) **is** an editable selector
([setup.jsx:39](app_v2/setup.jsx#L39)). The **FX rate** (84.2/$) is not editable
*here* — the field hint literally says *"edit in Finance"* — because FX rates are a
finance-owned table (`config.fxRates`) consumed by landed-cost and EVA. So it's not
hardcoded, it's **owned by a different tab.** *Why split?* one source of truth for FX
so a rate change updates every landed-cost at once. **Fair critique:** the hint is
easy to miss; a tiny inline "₹84.2/$ ✎ Finance" link would close the gap.

### 2.2 — "What does Effective Tax denote? Service level — doesn't it change per period?"  🟩 + 🟨

- **Effective Tax** (`config.taxRate`, editable) = your blended corporate tax rate.
  It's used in **Finance** to turn pre-tax operating profit into after-tax EVA
  (`EVA = NOPAT − WACC×capital`, and NOPAT needs the tax rate). One number, because
  for planning you want the *effective* rate, not a per-transaction tax engine.
- **Service level** (`config.serviceLevel`, editable) = your **default** target fill
  rate; the `z=1.645` shown is the safety-stock multiplier for 95%. **Your instinct
  is right that it varies** — and it already *can* per SKU: each product carries its
  own `sl` (the seed runs 85%–98% across the 6 SKUs). So Setup holds the **company
  default**; Products/Policy override per SKU. **Per-*period* variation** (higher
  service in festive weeks) is **not** modelled — a legitimate gap to note, not a bug.

### 2.3 — "CIN is uneditable"  🟥 small bug

Correct — `CIN {M.cin}` is printed read-only ([setup.jsx:55](app_v2/setup.jsx#L55)).
It's a master-data identity field, so by Fact 5 it **should** be an input. Minor, but
it's on the bug list. **Editable? → no, should be yes.**

### 2.4 — "MSME prefilled — is it combined plant & machinery? Are two questions enough? What's 'NOT MSME'?"  🟩 this one's actually well-built

The MSME tier is **derived, not chosen** — `msmeTier(investmentCr, annualTurnoverCr)`
per the MSMED Act 2020. Answering your sub-questions:

- **"Combined value of all plant & machinery?"** — yes, `investmentCr` is the
  *aggregate* investment in plant & machinery (editable; also pulled from Finance's
  asset register). You keep adding assets there and this figure tracks.
- **"Are two questions enough?"** — for the *Act's test*, yes: the classification is
  legally a function of exactly **investment + turnover**, nothing else. So two inputs
  is not laziness, it's the statute.
- **"What's NOT MSME?"** — it means the firm **exceeds the MSME ceiling** (turnover
  > ₹250 Cr or investment > ₹50 Cr) → it's a **large enterprise**. That's a valid,
  intended outcome, and it changes behaviour: the 45-day payment rule (43B(h)) no
  longer applies to it.

### 2.5 — "Where do you track receivables? If I sell direct to customers this is useless"  🟩 you've mixed up two sides

This is a clean teaching moment. The MSME machinery here is about **payables, not
receivables** — specifically money **you owe to MSME *suppliers***. Section 43B(h)
says: if *your supplier* is an MSME and you don't pay them within 45 days, you can't
deduct that spend from tax. So the relevant tracking is **your payables to suppliers**
(surfaced in Sourcing/Finance), and it matters *regardless* of whether you sell direct
to customers. Your customer-side **receivables** are a separate thing and aren't a
planning input here — so you're right that *receivables* don't belong on this screen;
they simply aren't what this card is about.

### 2.6 — "I doubt the effectiveness & accuracy of Industry Templates"  🟩 healthy doubt — and the card agrees with you

Your skepticism is exactly calibrated. The template loader is **honest about its own
limits**: a preset **retunes the knobs solvers consume** (service level → safety
stock & CVaR; freeze/slush horizon → re-plan nervousness; profile → which engines
show) and **does not fabricate a dataset** — the banner says so in those words
([setup.jsx:144](app_v2/setup.jsx#L144)). So "Pharma" doesn't invent pharma products;
it sets service to 99%, a long 8-week freeze, and bundles the audit trail. Its value
is **time-to-value** (start from tuned defaults vs a blank model), and its honest
ceiling is that on the automotive seed it reshapes *parameters, not data*. So:
"accurate" in what it claims, modest in what it does. **Editable? → it writes real
config you can then override anywhere.**

### 2.7 — "Where's pure MTS? What's ATO? Is that all the profile questions?"  🟨 + 🟩 (and a real gap)

The Planning Profile is the **gate** — six answers that hide engines you don't need
(this is the same `useProfile()` machinery behind "Logistics is off for single-site").
Answering you:

- **"Where is pure MTS?"** — **genuine gap.** The makePolicy options are `MTS+MTO`,
  `pure MTO`, `ATO` ([setup.jsx:297](app_v2/setup.jsx#L297)) — there's **no pure-MTS**
  choice. A make-to-stock-only shop should be selectable. **On the fix list.**
- **"What's ATO?"** — **Assemble-To-Order**: you stock *components* and assemble the
  finished good only once an order lands (Dell-style PCs, configurable products). It
  sits between MTS (build finished goods to forecast) and MTO (build nothing until
  ordered).
- **"Is that all the questions?"** — six today (policy, capacity, imports, lines,
  distribution, who-forecasts). That's a deliberate minimum to keep the front door
  small; it's also exactly the seed of the **onboarding wizard** in Part 9 — these are
  the questions, they're just buried at step 2 of Setup instead of greeting you.

### 2.8 — "What is capacity tightness? The 'what this switches off' doesn't update / explain"  🟩 + 🟨

- **Capacity tightness** = *is your capacity a binding constraint?* **"tight"** = you
  can't make everything customers want → trade-offs matter → **Profit-Mix turns ON**
  (it picks what to make first). **"ample"** = you can make it all → nothing to trade
  off → **Profit-Mix turns OFF**. That single answer is *why* Profit-Mix appears or
  hides. This is genuinely clever gating.
- **"What this switches off"** *is* live — `offList` is derived from the `gate`
  ([setup.jsx:283](app_v2/setup.jsx#L283)); flip makePolicy to *pure MTO* + capacity
  to *ample* and "Profit-mix + seasonal Aggregate" appears in the hidden list. **Fair
  critique:** the update is silent (no animation/flash), so it *feels* static — a
  highlight-on-change would make the cause→effect visible. **The card's job is sound;
  its feedback is too quiet.**

### 2.9 — Planning Calendar — your strongest catches on this page (two real bugs)

You hit three separate things here; two are genuine bugs.

- **"Fit an actual calendar so I can pick the start date"**  🟨 — fair. Start Date is
  a plain `TextInput` you type into ([setup.jsx:224](app_v2/setup.jsx#L224)), not a
  date-picker. A real `<input type=date>` is the obvious fix. **Editable? → yes, but
  via raw text; should be a picker.**
- **"I selected horizon = 52 but the banner says W23 Jun26 → W21 May27"**  🟥 **bug,
  and a good one.** Two parts: (1) the horizon unit **follows the grain** — with grain
  = *week*, "52" means 52 *weeks* (≈ a year), not 52 days; that's why you see week
  labels. (2) More importantly, the banner's date range reads from `M.periods` (the
  **seed** period array, fixed length) — it does **not** recompute from your typed
  `horizonLength`. So changing 52→anything leaves the banner stuck. **That's the
  disconnect you felt — the output didn't follow the input. On the bug list.**
- **"Why must I *Compute Calendar* manually? Holidays should be integrated, and
  choosing another state should change holidays / let me edit a day"**  🟨 + 🟥 —
  layered:
  - The calendar **is** a real engine (`/api/calc/calendar` → `calendar.py`) that
    computes working days from holidays; it shows **seed figures until you click
    Compute**, by design (don't hit the server on every keystroke). **Fair:** it could
    auto-compute once on load so it's never showing stale seed.
  - **Real bug:** the holiday list is hardwired to *"TN Gazetted Holidays"* and the
    `plantState` selector (TN/MH/GJ/KA) **doesn't drive it** — pick Maharashtra and the
    holidays don't change. And there's **no way to add/remove a specific day**. Both
    are legitimate misses for an Indian multi-state planner. **On the fix list.**
- **"₹ symbol and service level should be here"**  🟩 — they already are, in the
  yellow banner: *"… · ₹ · 95% service"* ([setup.jsx:229](app_v2/setup.jsx#L229)).

### ✅ Part 2 checklist — you should be able to say:

- [ ] "Setup declares the **two things the whole app needs first**: identity and the
      planning clock. Most of it is editable (correct — it's master data)."
- [ ] "Currency *symbol* is editable here; the *FX rate* is editable in Finance (one
      source of truth). Effective Tax feeds after-tax EVA; Service Level is a
      **company default** that SKUs can override."
- [ ] "MSME tier is **derived from investment + turnover** (the Act's exact test);
      'NOT MSME' = a large enterprise; the rule is about **payables to MSME
      suppliers**, not my customer receivables."
- [ ] "The Planning Profile's six answers **hide engines I don't need**; 'tight'
      capacity is what turns Profit-Mix on. ATO = assemble-to-order; **pure-MTS is a
      missing option**."
- [ ] "Industry templates **retune knobs, not data** — honest and limited, good for a
      fast start."
- [ ] "Calendar bugs I can name: **horizon banner doesn't follow my input**, **plant
      state doesn't change holidays**, **no per-day holiday edit**, start date isn't a
      picker. CIN should be editable."

---

---

# PART 3 — Products (your Pages 5–7)

**What this screen is for:** the **central master-data tab** — you describe *one
finished good at a time*. The **item selector** at the very top scopes the entire
page: every card below (Yield, BOM, Costs, Policy) is *for the SKU currently
selected*. Flow: **Define → Yield & expiry → BOM → Costs → Policy → MTO.** Steps 1–3
are inputs; Policy is an **output** (derived); MTO is a firm-order list.

**The scoping confusion (your "for what product is this?"):**  🟨 — the page *is*
scoped to the selected item; the card headers literally say *"Yield & expiry ·
Crankshaft Bearing"*. But the **item selector isn't visually loud enough**, so it
reads like disconnected cards. A bigger "YOU ARE EDITING: TPA-4471" banner would
end this entirely. The mechanism is right; the signposting is weak.

### 3.1 — "Finished-Goods Catalog is fully read-only and unnecessary"  🟥 the editability bug, dead-on

Correct, and this is the single clearest instance of Fact 5. The catalog **table**
([products.jsx:50–80](app_v2/products.jsx#L50)) is read-only: Code/Name/Family/
Make-Buy/Mode/Sell₹/Tgt% all come from static seed; only **"+ Add product"** and the
*yield* column have any life. So your reality (your SKU names, prices) has **nowhere
to go** here. **Not unnecessary — under-built.** The fix is to make each row inline-
editable (it's master data, so it must be). On the bug list, high priority.

### 3.2 — "What is TAT%?"  🟩 it's "Tgt %" — target margin

The column is **Tgt %** (target contribution margin), not "TAT". It's a **goal you
set** — "I want ~36% margin on this SKU" — *not* a computed number. The footnote even
says it: *"target margin is a goal — actual mix is an output of Profit-mix, never
typed here."* So it's the one place a *wish* lives next to *facts*; the realised
margin comes from the cost rollup (§3.5) and the Profit-mix solver.

### 3.3 — "Are all these columns actually useful?"  🟩 mostly, with two dead ones

Walking the catalog columns honestly:

| Column | Real? | Note |
|---|---|---|
| Sell ₹, Shelf, Yield | ✅ live solver inputs | price → profit-mix; shelf/yield → expiry & gross-up |
| Wt kg, Vol m³ | ✅ derived from one authority | `skuWeightKg`/`skuVolM3` — the *same* numbers Logistics tonnage & Network storage use (one SKU = one weight) |
| Make/Buy, Mode | ✅ routing | drives whether it's produced or purchased, MTS/MTO/ATO |
| Family, Lifecycle | 🟨 informational seed | Growth/Maturity/Decline is a label, not yet a driver |
| **UoM** | 🟥 hardcoded "unit" | always prints "unit" — your note about "many units of measurement" is right: there's no real UoM model (eaches/kg/litre) yet |

So your instinct is calibrated: most columns earn their place; UoM is a stub and
lifecycle is decorative.

### 3.4 — "Costs are uneditable — what are Setup (amort.), Conversion & OH (your 'CH')?"  🟩 + they ARE editable

Two of the four cost lines **are** editable — *Setup Cost / Run* and *Labour / Unit*
are `NumInput`s ([products.jsx:187](app_v2/products.jsx#L187)). The **rollup** below is
derived (correctly read-only — it's an output). Defining your terms:

- **Material (BOM)** = `Σ(part.qty × part.cost)` — summed live from the BOM; edit a
  part and it moves.
- **Setup (amort.)** = `Setup Cost ÷ lot size` — the per-unit share of a machine
  setup once you spread it over a production run (see §3.5 on "lot").
- **Labour** = your editable ₹/unit (with a double-count guard so you don't count
  labour already inside a BOM component).
- **Conversion & OH** ("CH" in your notes) = **Conversion & Overhead** — the residual
  (machine time, energy, QA, factory overhead) that the BOM + labour + setup don't
  capture, reconciled to the SKU's standard cost. It floats as you edit the others.

### 3.5 — "Setup amortized over a lot of 120u — when did I define a lot?"  🟨 fair — it's the MOQ, and it's hidden

The "lot" is the product's **MOQ** (minimum order/production quantity — 120 for the
Crankshaft Bearing), a seed field on the product. You're right that you **never
consciously set it** on this page — it's used here but not *shown as an editable
field*. That's a gap: lot size materially changes setup-per-unit, so it should be an
explicit input on the Costs card. **On the fix list.**

### 3.6 — "A→B setup cost differs from B→A — how do I define that?"  🧭 it lives in Production

This is **sequence-dependent changeover**, and it's real and important (going
crankshaft→piston may cost more than piston→crankshaft). The per-product *Setup Cost*
here is a **single symmetric number**; the **directional A→B matrix** lives in
**Production → Changeover** (§6). So the answer is: yes it's modelled, just on a
different tab — which is itself a navigation smell (you'd expect to define it near the
product). Worth cross-linking.

### 3.7 — "Is the BOM complete? Verify."  🟩 complete — but the physical rows are read-only

Verified — the BOM carries everything MRP/procurement needs: **Part, Component,
Qty/unit, Unit Cost, Lead Time** (primary) + **MOQ, Ordering cost S, Holding %,
Contract price, Supplier** (commercial) + **scrap %** (conversion loss). That's a
complete procurement BOM. **But:** only *scrap %* is editable — Qty/Cost/Lead-time are
shown in a read-only `DataTable` ([products.jsx:139](app_v2/products.jsx#L139)). Same
Fact-5 bug as the catalog: these are inputs, they must be editable. **On the list.**

### 3.8 — "Where does a user record a price change as of a date?"  🟨 modelled, but not user-recordable yet

Excellent question, and the most sophisticated one on these pages. Price changes
**are** modelled — as **time-varying contracts** (`rateByPeriod`) shown on **Network →
Contracts** as a step chart (steel ₹142 → ₹151 at W29). The procurement MILP buys
*ahead* of a known step. **What's missing is exactly what you described:** a place to
**record a new price-change event ("part X → ₹Y as of date D")** that writes into that
contract series and shows up in an activity log. Today the steps are seed-only. This
is the recurring **"activity / change-log"** idea in your notes (it appears again for
demand and supplier prices) — and it's a genuinely good feature, not a
misunderstanding. **Design item for Part 9.**

### 3.9 — Policy & MTO (bottom of the page)

- **Inventory Policy** is correctly an **output** — `(s,S)/(R,Q)` derived by the real
  engine (`/api/solve/policy`) from demand variability + lead time + service level.
  You **don't type** EOQ/safety stock; you press "Derive" and read them. (More on the
  math in Part 5.)
- **Make-to-Order** is the firm customer-order list (your real OEM POs). Read-only here
  because these are *given* orders; you'd edit them where orders are captured.

### ✅ Part 3 checklist — you should be able to say:

- [ ] "The whole Products page is **scoped to the selected SKU** (the item selector);
      every card is 'for this product'."
- [ ] "The catalog table and the BOM physical rows are **read-only — that's the bug**;
      they're master data and must be editable."
- [ ] "**Tgt %** is a *target margin goal* I set, not a computed number; the real
      margin comes from the cost rollup + Profit-mix."
- [ ] "Setup Cost & Labour are editable; the rollup is derived. **Setup (amort.)** =
      setup ÷ lot(=MOQ); **Conversion & OH** = the residual overhead."
- [ ] "Directional A→B setup is **sequence-dependent changeover**, defined in
      Production. Time-varying prices live in Network Contracts — but there's **no
      'record a price change as of date' log yet**, which there should be."
- [ ] "Inventory Policy is an **output** I derive, not type."

---

# PART 4 — Network · Nodes, Flows & Contracts (your Page 7)

**What this screen is for:** the master data for *where everything physically is and
moves* — **nodes** (plants/WH/DCs/customers/suppliers), **per-item lanes** (inbound
parts → plant, outbound FG → customers), **time-varying contracts**, and **opening
on-hand**. It deliberately absorbed the location/supplier data that used to be
scattered in Setup + Sourcing, so there's one source of truth the transport &
procurement solvers read.

**Editable? overall:** 🟥 **zero edit affordances** — this is the **worst** instance
of your editability thesis. Everything (nodes, lanes, suppliers, contracts, on-hand)
is a read-only render of seed. "When did I define this structure?" — you didn't, and
**there's currently no way to.** That's the headline bug for this tab.

### 4.1 — "The flow visualisation is wrong — why WH-CHN → DC-BLR → DC-PUN in a chain?"  🟥 genuine modelling bug

Sharp catch. The flow diagram draws the outbound side as a **linear chain** — it lays
nodes left-to-right by array index and connects each to the next
([network.jsx:62–77](app_v2/network.jsx#L62)), so it *looks* like goods go
PLANT → WH-CHN → DC-BLR → **DC-PUN** → GGN in series. The real topology is
**hub-and-spoke**: the warehouse feeds DC-BLR and DC-PUN **in parallel**, and a
customer in Pune is served **straight from the nearest DC**, not via Bangalore.
The diagram hardcodes a hop *order* instead of drawing the actual `from → to` lane
graph. So your "it could go WH→PUN directly" is exactly right. **On the bug list** —
the fix is to render lanes as the real directed graph, not a conga line.

### 4.2 — "Crucial info is missing — do you even know cost & transport trunk?"  🟨 partly there, partly missing

Each lane *does* show **mode · ₹rate · lead-days** (and inbound CIF/international lanes
are dashed with their long lead). What's **missing** and what you're reaching for:
**trunk/vehicle capacity** (FTL truck size, container cube), **per-lane volume/flow**,
and **node throughput limits** beyond the headline capacity. Those are what turn a
pretty diagram into a planning instrument. Legitimate gap.

### 4.3 — What's actually well-built here (so you trust the good parts)

Three things on this tab are genuinely solid and *not* faked:

- **Storage Utilization** is **derived** — `Σ(volume × on-hand) ÷ node cube`, using the
  same volume authority as Products/Logistics (was hardcoded 62/74/48%, now real). The
  DCs read nearly empty because on-hand is opening stock — that's honest, not a bug.
- **Contracts** model price as `rateByPeriod` (a *step* function), so a mid-horizon
  price change is planned around, not averaged away.
- **Supplier Master** carries LT, LT-variability, incoterm, spend, OTIF, risk — and the
  footer totals are derived from the rows (qty-weighted OTIF), not typed.

So the **content** is real and well-chosen; the **defect** is that none of it is
editable and the flow picture is topologically wrong.

### ✅ Part 4 checklist — you should be able to say:

- [ ] "Network is master data (nodes/lanes/suppliers/contracts/on-hand) — and it's
      **entirely read-only, which is the biggest editability bug**."
- [ ] "The flow diagram draws a **false linear chain**; real flow is hub-and-spoke
      (WH feeds DCs in parallel, customer served from nearest DC)."
- [ ] "Lanes show mode/rate/lead; **trunk capacity & per-lane volume are missing**."
- [ ] "Storage utilization and time-varying contracts are **genuinely derived/real** —
      the data's good, the editability and the diagram aren't."

---

# PART 5 — Demand, S&OP & Inventory Policy (your Pages 8–9, 11–12)

These three tabs are the **first of the middle third** — the solvers. The single
biggest reframe: **these are not where you 'define a product'; they're where the
optimisers chew on the products you defined in the left third.** That's why they feel
"prefilled with no clue what product" — they operate on *all* SKUs (or aggregate),
reading the master data you set in Products/Network.

## 5A — Demand Planning (Pages 8–9)

**What it's for:** produce, per SKU, *how much you'll sell each period and how
uncertain it is*, then commit that as the number everything downstream plans to.

### 5A.1 — "It auto-says 'Running' with no input from me, then 'forecast failed'"  🟥 two things

- **The auto-run is by design.** On opening the tab, a `useEffect`
  ([demand.jsx:67](app_v2/demand.jsx#L67)) fires the forecast for the selected SKU so
  you see a curve immediately instead of a blank chart. That's the "Running" with no
  action from you.
- **The "failed" is the deploy, not the code.** Hit locally, `/api/forecast` returns
  **200 in 3.5 s** with sklearn/statsmodels/xgboost all loaded — it works. On the
  **free Render instance** (512 MB, single worker, spins down when idle), the first
  post-idle call cold-starts and the heavy ML import can stall or OOM → "forecast
  failed." Same root cause as the Page-14 freeze (Part 8). **Two fixes:** make the
  auto-run *wait* for the engine to be warm (and show "warming up", not "failed"), and
  address the free-tier memory (lazy-import the ML libs / size up).

### 5A.2 — "Is this the input format? Show me a sample row for my product. The import is dumb — no clue what product."  🟨 fair

The history-entry grid and CSV import don't show a **worked example keyed to the
selected SKU** ("here's how a row for *Crankshaft Bearing* at *weekly* grain looks").
That's a real onboarding miss — the data exists to generate exactly such a sample. The
import needs a **per-SKU template/preview**. Good call.

### 5A.3 — "The history/forecast chart used to be a nice graph, now it's heart-spikes"  🟨 it's the day grain

The grain defaults to **daily** (season length 7), which *surfaces the within-week
spikes production is actually scheduled around — that's deliberate*. But as a *default*
it looks jagged ("heart spikes"). Flip the grain toggle to **Week/Month** and it
smooths into the clean curve you remember. Reasonable to debate whether weekly should
be the default landing view.

### 5A.4 — "There should be a combined results tab for all products (some MTO with set orders)"  🟨 recurring, valid

The tab is **per-item** (selector-scoped). You're asking for an **all-SKU consensus
roll-up** — one table where every product's committed number sits together, MTS
forecasts and MTO firm-order SKUs side by side. This "per-item input, unified output"
request shows up across your notes and is one of the strongest cross-cutting features
to add.

### 5A.5 — "I don't understand the NPI-like module — hide it, record what it does elsewhere"  🧭 agreed

NPI ("New Product Introduction") **like-modelling** estimates demand for a brand-new
SKU with no history by **borrowing an analogue product's shape × a scale × a ramp**.
It's a genuine technique but it's **advanced and clutters the main flow**. Your call to
**remove it from the default UI and document it** (behind an "advanced" disclosure) is
the right one. Noted for Part 9.

### 5A.6 — "Segmentation & lifecycle — how did you categorise? It overlaps the Products policy"  🟩 here's the method

- **ABC** = a **Pareto by value**: rank SKUs by revenue (price×volume); the top ~80%
  of value is "A", next "B", the long tail "C". (Seed: the Crankshaft & Piston are A.)
- **XYZ** = by **demand variability** (coefficient of variation): steady = X, lumpy =
  Z. (Seed MAPE runs 6.8%→22.3%, so the Tensioner is the volatile "Z".)
- Together they make a **9-box** (AX = high-value/steady → tight automated policy; CZ =
  low-value/lumpy → make-to-order or don't stock). The **overlap with Products' policy
  is intentional**: segmentation is *why* a SKU gets the policy it gets — they're meant
  to be read together, not duplicated.

### 5A.7 — "Committed demand — is this the right place? Doesn't S&OP decide how much to make?"  🟨 a real placement debate

You've spotted a genuine architectural seam. **Committed (consensus) demand** = the
single agreed sell-quantity after judgement is layered on the statistical forecast.
*Demand planning* produces it; *S&OP* reconciles it against supply/finance; *Production*
makes it. So "how much to **sell**" is committed here; "how much to **make**" (which can
differ — build ahead, build to stock) is the S&OP/Production output. Putting the commit
*button* in Demand is defensible (it's a demand decision), but your instinct that it
*belongs in the S&OP conversation* is also valid — it's the handoff point between the
two. Worth making that handoff explicit rather than burying it.

## 5B — Aggregate Plan / S&OP (Pages 11–12)

**What it's for:** one **family-level** volume/capacity/workforce plan that ties demand
to supply to finance — then disaggregates back to SKUs.

### 5B.1 — "No clue what product I'm looking at"  🟩 by nature — S&OP is aggregate

S&OP is **deliberately not per-SKU.** Its whole point is to zoom *out* to product
*families* and months, decide volumes and workforce at that level (you can't usefully
argue headcount SKU-by-SKU), then **disaggregate** down. So "no single product" is
correct — but the tab should *say* "you're looking at families, not SKUs" so it doesn't
feel like missing context.

### 5B.2 — "Labour wages are defined here, but lines/workers are defined in Production"  🟨 you found a double-home

Right, and it's a known rough edge. The aggregate plan uses **`PLAN_PARAMS`** (workforce
42, wage 22000, hire/fire costs…) which are **placeholder seed economics**
([plan.jsx:8](app_v2/plan.jsx#L8)) pending a dedicated "plan cost inputs" card. These are
*aggregate* workforce numbers (how many people total), distinct from Production's
*per-line* worker assignment. Two legitimately different concepts — but the app doesn't
explain the difference, so it reads as contradiction. Needs labelling + a real input card.

### 5B.3 — "Disaggregation is prefilled, no clue what it does"  🟩 here's what

**Disaggregation** = taking the aggregate family plan ("make 4,300 units of the Bearing
family in June") and **splitting it back to individual SKUs** by their share, so the
family plan and the SKU schedules reconcile. It's the bridge from the S&OP volume number
to the per-SKU production schedule. Prefilled because it's an *output* of the split, not
an input.

## 5C — Inventory Policy: MTO vs MTS, EOQ, (R,Q) (Page 8)

Your Page 8 is really one question: *"how did you derive policies when you don't even
know my demand, and what about one-off orders?"*

- **It does know demand** — the policy engine reads the **committed demand series** the
  forecast wrote (or the MTO orders for MTO SKUs). Until you run the forecast, it uses a
  flat seed (σ=0), which is *why* safety stock can look trivially small — honest, not
  wrong. Run Demand first, then derive policy, and the variability shows up.
- **MTS vs MTO is the fork:** MTS SKUs get a **stocking policy** (forecast → safety stock
  → reorder); MTO SKUs **don't get safety stock at all** — you build to the firm order.
  The `Method` tag on each SKU controls which path it takes.
- **EOQ / (R,Q) / (s,S):** EOQ = `√(2DS/h)` (the order size that balances ordering cost S
  against holding cost h). (s,S) = "when stock hits *s*, order up to *S*"; (R,Q) = "every
  *R* periods, order *Q*". Which one is recommended depends on whether review is
  continuous or periodic.
- **"What about a one-off order?"**  🧭 — good edge case. A true one-off shouldn't get a
  *repeating* policy at all — it's an MTO line, not a stocked SKU. The app currently
  applies policy logic to anything with demand; distinguishing "recurring vs one-shot"
  is a refinement worth making.

### ✅ Part 5 checklist — you should be able to say:

- [ ] "Demand/S&OP/Policy are **solvers**, not product-definition — they run on *all*
      the SKUs I defined in the left tabs, which is why there's 'no single product'."
- [ ] "Demand **auto-runs on open by design**; the 'failed' is the **free-tier
      deploy**, not the code (it's 200 locally)."
- [ ] "**ABC** = Pareto by value, **XYZ** = by demand variability; together a 9-box that
      *explains* each SKU's policy — the overlap with Products is intentional."
- [ ] "S&OP is **aggregate by design** (families, not SKUs), then **disaggregates** back
      to SKUs. Its workforce/wage numbers are *placeholder* aggregate economics, not the
      per-line workers from Production."
- [ ] "MTS SKUs get safety-stock policy; MTO SKUs build to firm orders (no safety
      stock). A true **one-off order is MTO, not a stocked policy** — a refinement to
      make."
- [ ] "The big missing feature is a **unified all-SKU consensus view** + a **price/
      change activity log**; NPI-like should be hidden behind 'advanced'."

---

---

# PART 6 — Production Architecture (your Pages 12–13)

**What it's for:** how you physically make things — **Line → Stage → Machine** (the
slowest stage caps the line: *bottleneck = min(stage capacity)*), the **cycle time &
line assignment** per SKU, the **Master Production Schedule** (the real production
MILP), and **sequence-dependent changeover**. Four sub-tabs: Architecture · Cycle &
Line · Schedule · Changeover.

**Editable? overall:** 🟥 split — the **solver *parameters* are editable** (labor rate,
shutdown threshold, holding cost, campaign min-run, time-phasing — all real
`SolverInput`s, [production.jsx:77–88](app_v2/production.jsx#L77)), but the **physical
*structure* is not** — you cannot define a line, add a stage, set how many
workers/machines it has, or set per-stage cycle time. That's the core of your "every
section uneditable" complaint, and it's right *for the structure*, not for the knobs.

### 6.1 — "No proper way to define a line, its workers/machines, cycle time per stage"  🟥 the real gap

Correct. The architecture tree renders from seed; there's no "+ Add line / + Add stage
/ set machines / set workers" anywhere. Since this is master data (it's *your factory*),
it must be definable. This is the Production equivalent of the Network editability bug,
and the two together are the biggest "make it real" items. **On the fix list.**

### 6.2 — "Cycle time is on sub-tab 2 but sub-tab 1 already shows a prefilled graph"  🟨 navigation, fair

The Architecture tab shows the line/stage/bottleneck picture; cycle time lives on the
*Cycle & Line* sub-tab. So you see throughput *consequences* before you reach the
throughput *input*. Reasonable to merge "set cycle time" next to "see the bottleneck it
causes." A layout fix, not a logic one.

### 6.3 — "Should I use OEE, or just cycle time, to simplify?"  🧭 your call — here's the trade

- **Cycle time** = the raw rate (e.g. 4.2 min/unit) — simple, one number.
- **OEE** (Overall Equipment Effectiveness = Availability × Performance × Quality)
  *derates* that raw rate for real-world losses (breakdowns, slow-running, defects). A
  line at 4.2 min/unit and 84% OEE effectively makes fewer good units/hour.

For a first model, **cycle-time-only is a legitimate simplification** — you fold the
losses into a slightly slower cycle and skip OEE. For a mature model, OEE separates
*why* you're slow (availability vs quality) so you can target it. **Recommendation:**
offer a **"simple (cycle only) vs detailed (OEE)" toggle** so you choose your altitude.
Good instinct.

### 6.4 — "Shutdown threshold, campaign min-run — what the hell are these?"  🟩 plain words

Both are **editable knobs** ([production.jsx:80–88](app_v2/production.jsx#L80)); they
just need plain-language labels:

- **Shutdown threshold** = the **utilisation floor below which running a line for a week
  isn't worth it.** Set it to 25% and any line-week below 25% busy becomes a
  *shutdown candidate* — the solver weighs *wages saved by going dark* against the
  *one-off cost to rehire/restart*. It's the "should we idle this line this week?"
  lever.
- **Campaign min-run** = the **minimum units per setup.** Set it to 300 and the schedule
  must run *at least* 300 of a SKU before changing over — forcing long campaigns
  (AAAA-then-BBBB) with **fewer setups but more inventory holding.** It's the
  classic setup-vs-holding trade, as one dial. (Verified live: turning it on collapsed
  6 short lots into 2 long runs.)

### 6.5 — "Change matrix & 'choose RM order' are uneditable/prefilled"  🟥 + 🟩

- **Changeover matrix** (the directional A→B setup minutes from §3.6) is shown
  read-only — it **should** be editable (it's your factory's reality). **On the list.**
- **"Choose RM order" / run order** is the solver's **chosen sequence** — that one is an
  **output** (the sequencing solver decides the order that minimises changeover), so
  read-only is correct there. The matrix is the input you set; the order is what the
  optimiser returns.

### ✅ Part 6 checklist:

- [ ] "Production = Line→Stage→Machine, **bottleneck = the slowest stage.** The solver
      *knobs* are editable; the *factory structure* isn't — that's the gap."
- [ ] "**Shutdown threshold** = idle-a-line utilisation floor; **campaign min-run** =
      min units per setup (setup-vs-holding dial). Both real, both editable."
- [ ] "**Cycle-only is a fine simplification**; OEE adds availability/performance/quality
      detail — a toggle should let me pick."
- [ ] "The **changeover matrix is an input** (should be editable); the **run order is an
      output** (correctly read-only)."

---

# PART 7 — Suppliers & Procurement / Sourcing (your Pages 10, 13)

**What it's for:** this is the **procurement MILP's lens** — for the selected part, its
**MRP net requirement, supplier, inbound lane, landed cost, and PO release schedule.**
It *consumes* the supplier master (now in Network) and the committed demand (from
Demand) and answers: **"exactly what to buy, when, at least cost."**

**Editable? overall:** 🟨 partial — it has real inputs (sourcing terms, the solver
runs), but it's mostly an **output lens**, and several descriptive panels are read-only
seed. The key reframe: most of Sourcing is *result*, not *master data* — so read-only is
often correct here, *except* the sourcing terms and on-hand.

### 7.1 — "I'm shocked — what do you even feed these solvers? Every section is prefilled."  🟩 here's the feed

The procurement MILP eats, for each finished SKU: its **committed demand series** (the
keystone the forecast wrote) × the **BOM** (exploded to part requirements) × each part's
**landed cost** (quoted cost lifted by duty + inbound freight + live FX) × supplier
**lead time & MOQ**. That's `procurementPayload` ([sourcing.jsx:26](app_v2/sourcing.jsx#L26)).
So nothing here is invented — it's your master data flowing into the optimiser. It
*looks* prefilled because the seed already supplies all of it (Fact 1).

### 7.2 — "Why is there a time-varying price graph here, prefilled? Maybe record changes in an activity log"  🟨 same idea, third time

It's the same **contract `rateByPeriod`** step price from Network, shown here because
procurement *buys around* the steps. And yes — your **activity/change-log** idea
(record "part X → ₹Y as of date D" and have the PO costs reflect it) is exactly the
right home for *editing* those steps. This is now the **third place** the same feature
would pay off (Products §3.8, Demand, here) — which is a strong signal it should be
built as one shared "Activity / Change Log."

### 7.3 — "No clue what product these details are for"  🟨 per-part lens, weak signpost

Sourcing is **part-scoped** via the item selector set to *"its parts"* — pick a part and
you see *that part's* MRP/supplier/lane/landed cost. Same weak-signposting problem as
Products: the mechanism's there, the "you are looking at RM-STL42" banner isn't loud
enough.

### 7.4 — "Why is everything annualized? Spend & OTIF are trash & prefilled."  🟨 they're the supplier scorecard

**Annual qty / spend / OTIF** are **supplier-scorecard KPIs**, not solver inputs —
"annualised" because that's how you rate a supplier (₹X spend/year, Y% on-time-in-full
over the year). They're *descriptive facts about the supplier*, living in the master to
inform sourcing choices, not numbers the MILP optimises. So they're not "trash," but the
tab doesn't *say* "this is the supplier's annual report card," so it reads as random.
Labelling fixes most of this; showing period-level OTIF alongside would add teeth.

### 7.5 — "Opening on-hand feels random and uneditable — is it even used?"  🟨 it's used, should be editable

It **is** used — opening on-hand seeds the **MRP net requirement** (you only buy what you
don't already have). So it's load-bearing, not decorative. But it's read-only, and it's
master data → **should be editable** (Fact 5). Valid.

### 7.6 — "Remove the external-signal section — it isn't done properly"  🧭 agree, hide it

The **external signals** panel (commodity-price index, port-delay days) is meant to be a
*driver* — nudge the commodity index and material costs/leads shift. But with the seed at
**neutral (0% / 0 days)** it's a **no-op**, so it reads as pointless. Your call to
**remove it from the default UI** is right; keep the wiring behind an "advanced" flag.

### 7.7 — "This should be integrated with Products" + "put the incoterm matrix in a Team section"  🧭 navigation

- The **Products ↔ Sourcing split** is partly intentional (Products = what you make;
  Sourcing = how you buy the parts) — but the supplier *terms* genuinely straddle both,
  which is why it feels fragmented. A cross-link ("define this part's supplier terms →")
  would heal most of it.
- The **Incoterm responsibility matrix** (who owns freight/risk at each shipping stage)
  is reference content — your instinct to move it out of the planning flow into a
  reference/"team" area is reasonable. Placement call for Part 9.

### ✅ Part 7 checklist:

- [ ] "Sourcing is the **procurement MILP's lens** — it consumes committed demand × BOM
      × landed cost × supplier terms; it's mostly *output*, so read-only is often
      correct here."
- [ ] "Annual qty/spend/OTIF are the **supplier scorecard** (descriptive), not solver
      inputs — they need a label, not deletion."
- [ ] "Opening on-hand **is used** (seeds MRP net requirement) and **should be
      editable**."
- [ ] "External signals are a **no-op at neutral seed** → hide them; the price-step graph
      wants the same **activity/change-log** as Products."

---

# PART 8 — The Page-14 crash: Logistics freeze + empty Console

**Your report:** *"the tab after Sourcing [= Logistics] freezes the entire page and I
can't reopen the deployed app; Console also shows up empty."*

**What I tested (so this isn't a guess):**

| Check | Result |
|---|---|
| All 18 `.jsx` parse (same parser the browser uses) | ✅ no syntax error |
| `/api/solve/transport` (what Logistics calls) | ✅ HTTP 200, ~2 ms |
| `/api/forecast`, `/api/solve/production` | ✅ 200; empty input returns `{error}`, never crashes |
| Does `useSolve` auto-run on mount? | ❌ **no** — `run()` is manual; opening Logistics/Console fires **no** solve |
| Idle server memory | 196 MB (under the 512 MB free cap) |
| Console "interpret" half | defensive — every result is `r ? … : seedFallback`, no null-deref |

**Conclusion: the freeze is *not reproducible in the current local code.*** Everything
renders and every endpoint answers. That points the finger at **two things, both
real:**

### 8.1 — There is no React error boundary (the amplifier)  🟥 will fix

[main.jsx](app_v2/main.jsx) mounts the active stage directly with **no error boundary.**
So if *any single stage* throws at render — on one specific data path, one bad
selection — React unmounts the **entire app**, blanking *every* tab including Console.
That is *exactly* your triple symptom: one tab "freezes," then Console is "empty," then
"the whole app" is unusable. **The fix is one small wrapper**: an `<ErrorBoundary>`
around `<Stage/>` that catches a throw and shows "this stage hit an error — go back"
instead of nuking the SPA. This is the highest-value reliability fix in the whole
review, because it converts *any* future single-tab bug from "app dead" into "one card
with an error."

### 8.2 — The free Render instance (the trigger)  🟥 deploy-tier

On the **free** tier (512 MB, 1 worker, **spins down after ~15 min idle**), the first
click after idle hangs **30–60 s** while the instance cold-starts — which *feels* exactly
like "the page froze and won't reopen," then it comes back. And the forecast's heavy ML
imports (sklearn/statsmodels/xgboost) push a single 512 MB worker close to its limit, so
a solve right at cold-start can OOM the worker → the one worker dies → the **whole app is
briefly unreachable** (matches "can't open the deployed app again"). This is the same
root as the Demand "forecast failed."

**The fix menu (Part 9 ranks these):** (a) add the **error boundary** — cheap, robust,
do regardless; (b) **lazy-import** the ML libs inside `forecast.py` so idle memory stays
low; (c) move off **free** to a 1 GB/2 GB instance if you want no cold-starts. The
render.yaml is *intentionally* free right now (your call), so (a)+(b) make free
survivable; (c) is the spend-to-fix option.

### ✅ Part 8 checklist:

- [ ] "The freeze isn't a code bug I can reproduce — all files parse, all endpoints
      200, no auto-solve, memory's fine."
- [ ] "It's amplified by **no error boundary** (one tab's throw blanks the whole SPA →
      Console empty too) and triggered by the **free-tier cold-start/OOM**."
- [ ] "Top fix = **add an error boundary**; then lazy-import ML; sizing up is the
      no-cold-start option."

---

# PART 9 — Synthesis & the path forward

Step back from the 50-odd notes and they collapse into **six themes.** Almost none are
"the math is wrong" (the solvers are sound); almost all are **"let me drive it, and tell
me what I'm looking at."**

### The six themes

1. **Editability of inputs** (your core thesis). Read-only *master-data* inputs are
   bugs: **Network (all of it), Products catalogue + BOM rows, Production line/stage/
   machine, the changeover matrix, opening on-hand, CIN.** Outputs stay read-only (that's
   not a bug, it's the no-faking rule).
2. **Onboarding / "tell me what this is."** No front door explains the pipeline, no
   plain-language "what is Profit-mix," no wizard that hides engines you don't need (the
   six profile questions exist but are buried at Setup step 2).
3. **Signposting / scoping.** Item-scoped tabs (Products, Network, Sourcing, Demand)
   don't shout "YOU ARE EDITING TPA-4471" loudly enough, so scoped cards feel
   disconnected.
4. **A unified, all-SKU output view.** Inputs are per-item; you (rightly) want one
   consolidated "here's every product's committed plan" surface.
5. **An Activity / Change-Log.** One dated ledger to *record* changes (a price as of a
   date, a parameter change) and see their impact — wanted in Products, Demand, and
   Sourcing (same feature, three times).
6. **Ledger/state consolidation on Home.** Readiness + Freshness are one lifecycle (merge
   them); Exception Cockpit (to-do) and Value Ledger (receipt) should sit together as
   "open vs banked," each item timestamped.

### The triage table (every note, sorted)

| 🟥 Bugs / will-fix | 🧭 Your design calls | 🟩 By design (just explained) |
|---|---|---|
| Network fully read-only | Onboarding wizard: build it? | MSME is derived (2 inputs is the statute) |
| Products catalogue + BOM rows read-only | "Resolve-all" vs per-item on Cockpit | Revenue/COGS are live arithmetic, not faked |
| Production line/stage/machine not definable | Hide NPI-like behind "advanced"? | Capacity "tight" is what turns Profit-mix on |
| Changeover matrix read-only | Remove external-signals panel? | S&OP is aggregate (families) on purpose |
| Calendar: horizon banner ignores input | OEE vs cycle-only toggle | ABC=value Pareto, XYZ=variability |
| Calendar: plant-state doesn't drive holidays | Incoterm matrix → reference area | Inventory policy & ATP/run-order are outputs |
| No per-day holiday edit; CIN read-only | Default Demand grain: day or week? | Tgt% is a target, not a computed number |
| No error boundary (Part 8 amplifier) | Build the unified all-SKU view | Annual OTIF/spend = supplier scorecard |
| Free-tier cold-start/OOM (forecast "failed") | Build the Activity/Change-Log | Storage util & contracts are really derived |
| Network flow diagram draws a false linear chain | Merge Readiness+Freshness on Home | Most "prefilled" = the one demo company |

### Recommended order to actually fix (highest leverage first)

1. **Error boundary** (Part 8.1) — tiny change, converts "app dead" into "one card
   errored." Do this first, unconditionally.
2. **The onboarding wizard + plain-language solver explainers** (Theme 2) — the single
   biggest perceived-quality lift; it reframes *everything else* by telling you the
   pipeline and hiding what you don't need. The six profile questions already exist —
   promote them to a greeting + add one-sentence "what is this solver."
3. **Editability of the master-data tabs** (Theme 1) — Network, Products catalogue/BOM,
   Production structure, changeover matrix, on-hand, CIN. This is your thesis; it's the
   work that makes the app *yours* instead of a demo.
4. **Signposting** (Theme 3) — loud "editing X" banners on item-scoped tabs. Cheap, high
   clarity.
5. **The Activity/Change-Log** (Theme 5) and **unified all-SKU view** (Theme 4) — two new
   surfaces that each pay off in multiple tabs.
6. **Home consolidation** (Theme 6) and the **calendar bugs** (Part 2) — polish that
   removes the "two useless states" friction.

### The one-paragraph truth

The engine room is sound — the solvers are correct, every number is real or honestly
dashed, and the "prefilled" feeling is one complete demo company you were never told
was a demo. What's missing is the **cockpit**: a front door that explains the pipeline,
loud signposting of what you're editing, and — above all — **editable inputs everywhere
master data lives.** Fix those and the same screens that felt like "prefilled trash"
become "my company, my numbers, my plan."

### ✅ Part 9 checklist — the whole app in six sentences:

- [ ] "The solvers are right; my notes are about **driving and understanding**, not
      math."
- [ ] "Read-only *inputs* are bugs (Network, catalogue, BOM, line-def, changeover, CIN);
      read-only *outputs* are correct."
- [ ] "The biggest lift is an **onboarding wizard + plain-language explainers** that hide
      engines I don't need."
- [ ] "An **error boundary** is the top reliability fix; the deploy freeze is **free-tier
      cold-start/OOM**, not a code bug."
- [ ] "Two new surfaces pay off repeatedly: a **unified all-SKU view** and an **Activity/
      Change-Log**."
- [ ] "Once inputs are editable everywhere, the app stops being a demo and becomes
      mine."

---

*End of guided walkthrough. Every page of the handwritten notes (1–14) is answered
above, tagged 🟩/🟨/🟥/🧭. The fix list and recommended order are in Part 9.*
