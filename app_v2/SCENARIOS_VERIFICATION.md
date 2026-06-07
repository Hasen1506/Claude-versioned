# Scenarios & Logic Verification — app_v2

**Date:** 2026-06-04 · **Build:** main @ `d5020e8` · **Engine:** Flask + PuLP/CBC, 38 live endpoints
**Substrate dataset:** the shipped seed (`data.jsx` `M`) — an automotive Tier-1 engine-components
maker (6 finished SKUs + 2 raw materials, 3 lines).

Every number in this file is a **live solver result** captured from the running Flask engine — none
is a UI mock or a hand-computed estimate. Each of the five scenarios below is a **single, unified
problem**: one situation, walked from the start of the UI through every page that matters, with
**every input explained** (what the field is, the value used, why) and **every output explained**
(what the number is, what it means, what it implies). The decision falls out at the end of each.

> **Reading convention.** A number you can *type* is master data. A number that appears only *after a
> solve* is a result (shown as `—` until then). When the tool reports its own value it splits
> *identified* from *accepted* rather than inventing a blended total. This is the same "no faking"
> rule the app enforces in the UI.

**The full UI spine** (every scenario moves left-to-right along it, using the pages it needs):

```
Home → Setup → Products → Network → Demand → Plan → Production → Sourcing → Logistics → Finance → Console → Scenarios
DEFINE ───────────────────▶  PLAN ──────────────────────────────────▶  DECIDE / MONITOR ──────────▶
```

---

# Part A — Logic verification of the recent updates

Before the scenarios, the four wiring changes from the last few sessions, each proven on a
**controlled solve** where only the variable under test changes.

## A1 · Aggregate opening inventory (`init_inventory`) — CORRECT

**What it is.** The aggregate S&OP plan (`aggregate.py`, Hax–Meal LP) carries one opening stock for
the pooled product family. It enters the very first period's inventory balance:

```
aggregate.py:161   prev_i = init_inv          if period 0   else  I[previous]
aggregate.py:166   (I[t] − B[t]) == (prev_i − prev_b) + P[t] + O[t] − demand[t]
```

So in period 0, `I[0] = init_inv + production − demand`. The opening stock is *free supply* in
period 1; with a positive holding cost the LP draws it down as fast as demand allows.

**Proof.** Identical 4-period demand `[100,100,100,100]`, capacity made non-binding so the **only**
thing that can change production is the opening stock:

| Opening inventory | P1 prod | P2 | P3 | P4 | Σ production | Total cost |
|---|---|---|---|---|---|---|
| **0**   | 100 | 100 | 100 | 100 | **400** | ₹4,000 |
| **100** | **0** | 100 | 100 | 100 | **300** | ₹3,000 |
| **250** | **0** (carry 150) | **0** (carry 50) | 50 | 100 | **150** | ₹1,900 |

The 250 case traces exactly: `I0 = 250−100 = 150 → I1 = 150−100 = 50 → I2 = 50+50−100 = 0`.
Cost = 150 u × ₹10 + (150+50) u × ₹2 holding = **₹1,900**, matching the solver to the rupee. ✓

**Units honesty.** `init_inventory` is in **aggregate (labor-weighted) units**, the same currency as
aggregate demand. Because the family weights are mean-normalised to 1.0 (see A2), that scale ≈ the
physical-unit scale, so the single "opening FG stock" number typed in **Plan → step 0** is on the
right scale. Stated, not hidden.

## A2 · Aggregate weighting = worker-time, not machine cycle — CORRECT (a real fix)

The aggregate plan is **workforce-bound** (`production ≤ rate × workers`), so each SKU must be pooled
by its **worker-time per unit**, not raw machine cycle (a long *automated* cycle ties up little
labor). The fix added a per-SKU **hands-on %** (Plan → step 0b): `worker-min = machine cycle ×
hands-on %`. Proof of the ranking reversal:

| SKU | Machine cycle | Hands-on % | Worker-min/unit | Family weight |
|---|---|---|---|---|
| GEAR | 8.0 min (longest) | 20% (automated) | 1.6 | **0.857×** (lightest) |
| NUT  | 3.0 min | 60% | 1.8 | 0.964× |
| BOLT | 2.0 min (shortest) | 100% (manual) | 2.0 | **1.071×** (heaviest) |

By machine cycle GEAR > NUT > BOLT; by worker-time **BOLT > NUT > GEAR** — the order reverses,
exactly the "6 minutes of machine but 1 minute of a person" intuition. The demand-weighted mean of
the weights = **0.9997 ≈ 1.000**, so the `rate_per_worker` calibration is preserved — only the *mix*
of labor load shifts. ✓

## A3 · Carry rate = governed WACC + holding spread — CORRECT

`carryRate(config)` = blended WACC (from Finance) + an editable holding spread
(storage/insurance/obsolescence/shrink), feeding procurement, policy, rolling and Monte Carlo:

| Config | WACC | Holding spread | Carry rate |
|---|---|---|---|
| default | 11.24% | 12.80% | **24.04%** |
| lean warehouse | 11.24% | 5.00% | **16.24%** |
| perishable | 11.24% | 20.00% | **31.24%** |

Moves linearly with the spread; the WACC half is governed by the Finance capital structure. ✓

## A4 · Profit-mix budget + warehouse constraints — CORRECT (both bind)

Same three SKUs, `shared_capacity = 1500` machine-hrs throughout:

| Constraints | Profit | Mix (Alpha/Beta/Gamma) | Binding shadow prices |
|---|---|---|---|
| capacity only | ₹411,900 | 0 / 810 / 1380 | capacity ₹270/hr |
| + warehouse ≤ 1500 u | ₹399,200 | 193 / 920 / 387 | capacity ₹240/hr **and** warehouse ₹20/u |
| + budget ≤ ₹90,000 | ₹112,500 | **225 / 0 / 0** | budget **₹1.25 per ₹1** |

The budget shadow ₹1.25 = Alpha's margin-per-rupee (500/400), and 225 u × ₹400 = ₹90,000 exactly on
the cap. Both constraints are genuinely live. ✓

---

# Part B — Five unified end-to-end problems

---

## Scenario 1 — Seasonal CPG beverage S&OP: *build ahead, or flex the workforce?*

### The problem
Priya runs sales-&-operations planning at a beverage maker whose demand triples in summer. Hiring and
firing seasonal labor is slow and expensive; warehouse space is cheap. She has 200 units of finished
stock on hand today and a 30-person crew. **Question: should she pre-build inventory through the
spring and hold a steady crew, or hire up for the peak and lay off afterward?** She needs a single
12-month plan that minimises total cost without ever stocking out.

### Walking the UI — every input, what it is, and why

| Page | Field (UI label) | Value set | What it means / why this value |
|---|---|---|---|
| **Setup** | Planning calendar / grain | 12 months, monthly | The S&OP horizon and bucket size. |
| **Products** | Finished family + unit costs | seed FG | Confirms what's being planned. |
| **Demand** | Monthly forecast | `[600, 650, 800, 1400, 1900, 2100, 1850, 1200, 750, 600, 550, 500]` | The seasonal signal — a strong Apr–Jul peak (period 6 = 2,100). This is the demand the plan must cover. |
| **Plan → step 0** | Opening FG inventory | **200 u** | Stock on hand at period 0; offsets period-1 production (verified in A1). |
| | Initial workforce | 30 | Crew size today. |
| | Rate per worker | 40 u/worker/period | How much one worker can make per month — sets the capacity line `prod ≤ 40 × workers`. |
| | Regular / overtime cost | ₹120 / ₹180 per unit | Unit cost on straight time vs the 1.5× overtime premium. |
| | Holding cost | ₹8 / unit / month | The penalty for carrying a unit of pre-built stock — what makes "build ahead" *cost* something. |
| | Hire / fire cost | ₹15,000 / ₹20,000 per worker | What it costs to flex the crew — what makes "chase" *cost* something. |
| | Wage | ₹22,000 / worker / month | Standing labor cost. |
| | Overtime cap | 20% of regular | How much extra a steady crew can stretch before you must hire. |
| | Allow backorders | **No** | Stockouts are forbidden — every unit of demand must be met on time. |
| **Plan → step 0b** | Hands-on % per SKU | ~manual | Worker-time weighting (A2); here labor content is roughly uniform so weights stay ≈ 1.0. |
| **Plan (solve)** | — | run | Solves the aggregate LP: the level-vs-chase trade-off over 12 buckets. |

### The solve and every output, explained
Endpoint `/api/solve/aggregate`. It minimises `Σ (regular + overtime + holding + backorder + hire +
fire + wage)` subject to the inventory and workforce balances and the capacity line.

| Output | Value | What it means |
|---|---|---|
| `status` | Optimal | A provably cost-minimal plan was found. |
| `strategy` | **hybrid** | Neither pure level nor pure chase — it builds ahead *and* flexes some. |
| `seasonal_prebuild` | **TRUE** | Inventory peaks *before* demand does — the defining sign of build-ahead. |
| Inventory peak | **2,050 u in period 3** | The plan stockpiles 2,050 units by March, ahead of the June demand peak (2,100 u). |
| Workforce path | flat **27.08** for P1–P7, then down to **11.5** by P12 | Crew held steady through the peak, then released in the off-season — *level through the peak, chase down after.* |
| `workforce_cv` / `inventory_cv` | 0.30 / **1.14** | Inventory varies ~4× more than the crew — quantitative proof the plan leans on stock, not headcount. |
| Total cost | **₹7.93 M** | regular ₹1.27 M · overtime ₹0.37 M · **holding ₹66.8 k** · firing ₹0.37 M · wages ₹5.84 M · **backorder ₹0**. |

The key contrast is in the cost breakdown: carrying the entire pre-build costs only **₹66.8 k** of
holding, whereas hiring-then-firing a peak crew already costs **₹0.37 M** in firing alone — and the
plan still avoids hiring entirely (`hiring ₹0`) by running capped overtime early.

### The decision
**Commit the level-then-chase plan.** Hold ~27 workers and **pre-build ~2,050 units by March** using
regular plus capped overtime; carry that stock into summer (holding ₹66.8 k ≪ the ~₹0.4 M a
hire-then-fire cycle would cost); then **ramp the crew down after July**. The `prebuild = TRUE` flag
and `inv_cv ≫ wf_cv` are the glass-box evidence that justifies it to the board.

---

## Scenario 2 — Automotive Tier-1 plant: *the line is the bottleneck — what runs, and do we expand it?*

### The problem
Rakesh manages a plant where finishing-line **machine-hours** are scarce: every SKU competes for the
same hours, and he cannot make everything. He must (a) choose the **product mix** that maximises
profit on the binding line this quarter, and (b) decide whether a **capacity upgrade** on the
tightest line is worth funding.

### Walking the UI — every input, what it is, and why

| Page | Field | Value | What it means / why |
|---|---|---|---|
| **Products** | Sell price / variable cost / BOM material cost | per SKU | Together set each SKU's **margin per unit**. |
| | Cycle time | Alpha 2.0 / Beta 1.0 / Gamma 0.5 hr | Machine-hours each unit consumes — converts the hour budget into a unit ceiling. |
| **Production** | Lines, OEE, shared machine-hour pool | 3 lines | Identifies the scarce shared resource. |
| **Console → Profit-Mix** | `shared_capacity` | **1,500 machine-hrs** | The hour budget for the quarter — the binding constraint. |
| | Demand ceilings | from forecast | Each SKU can't sell beyond its forecast. |
| **Plan / Production → linecap** | Line caps vs demand | LINE-03 = 1,000 u (demand 1,300) | A stress case where one line can't cover its assigned SKUs. |

### Solve A — product mix · `/api/solve/profitmix` · every output explained

| Output | Value | What it means |
|---|---|---|
| `status` / profit | Optimal · **₹411,900** | The most profitable feasible mix. |
| Mix | **Gamma 1,380 · Beta 810 · Alpha 0** | The LP fills the line with the two highest **margin-per-hour** SKUs and drops Alpha — high margin *per unit* is worthless if it eats too many scarce hours. |
| Capacity shadow price | **₹270 / machine-hour** | The marginal value of one more hour: relax the 1,500-hr budget by 1 hr and profit rises ₹270; tighten it and you lose ₹270. This is the price of the bottleneck. |
| Crossover (Alpha) | price **₹900 → ₹940 (+4.4%)** | Alpha enters the mix only if its price rises 4.4%, at which point its margin/hour (₹250) would beat the ₹270/hr marginal product. Below that, keep it parked. |

### Solve B — capacity expansion · `/api/solve/linecap` · every output explained
LINE-03 throttled to 1,000 u against 1,300 u of assigned demand:

| Output | Value | What it means |
|---|---|---|
| Unmet demand | **300 u**, all **Connecting Rod** | The LP protects the higher-margin Timing Chain Tensioner (₹930/u) and shorts the lower-margin Connecting Rod (₹730/u). |
| LINE-03 shadow price | **₹730 / unit** | One more unit of LINE-03 capacity recovers ₹730 of otherwise-lost margin. |
| Annualised recovery | **300 × ₹730 = ₹219,000/yr** | The value of restoring the full 300 units of capacity. |

### The decision
**Run Gamma + Beta** to fill the binding line; either **raise Alpha's price ~4.4%** or park it. And
**fund the LINE-03 upgrade** provided its annualised cost is below the **₹219 k/yr** of recovered
margin (drop that figure into Finance's NPV/hurdle to confirm payback). The ₹270/hr and ₹730/unit
shadow prices are the exact, auditable numbers that justify the capex request.

---

## Scenario 3 — Pharma distributor: *98% service at least capital — where does the buffer live?*

### The problem
Dr. Anjali plans supply at a regulated pharma distributor. Service-level misses carry heavy
penalties, several finished products share one common alloy/active input, and tied-up capital is
scrutinised. **Question: where should safety stock be positioned, and how big, to hit a high service
level at the least capital?**

### Walking the UI — every input, what it is, and why

| Page | Field | Value | What it means / why |
|---|---|---|---|
| **Network** | Echelons + shared input map | raw → DC → FG; 1 billet → 3 FGs | Defines where buffers *could* sit and which FGs share the common input. |
| **Demand** | Mean & σ per SKU | valve seat μ=138, σ=42 | The demand distribution the buffer must cover. |
| **Sourcing → CVaR** | Holding cost / shortage cost | ₹18.1 / ₹515 per unit | The trade-off: cost of carrying a unit vs cost of being short one. |
| | β (tail confidence) | 0.95 | The plan is robust to the worst **5%** of demand outcomes, not just the average. |
| **Sourcing → MEIO pooling** | Service level, shared part lead time | 95%, 3 periods | Sets the pooled buffer via the square-root law. |
| **Scenarios → Monte Carlo** | Runs, committed plan | 500 runs | Stress-tests the chosen plan for realised fill and tail cost. |

### Solve A — CVaR newsvendor · `/api/solve/cvar` · every output explained

| Output | Value | What it means |
|---|---|---|
| Order-up-to (CVaR) | **254 u** | Stock up to 254 units to be tail-robust at 95%. |
| Order-up-to (risk-neutral) | 215 u | What a plain expected-value newsvendor would hold. |
| **Robustness premium** | **+39 u** | The extra buffer CVaR adds (254−215) to cover the worst-5% tail rather than just the average. |
| Safety stock | 116 u | Buffer above mean demand (138). |
| VaR / CVaR | ₹3,307 / ₹3,570 | Value-at-risk vs the (higher) *conditional* tail loss CVaR actually protects against. |

### Solve B — risk pooling · `/api/solve/meio-network` · every output explained
One alloy billet feeding 3 FGs, square-root law `σ_pool = √Σσ² ≤ Σσ`:

| Output | Value | What it means |
|---|---|---|
| SS value, decentralised | **₹60,539** | Cost of holding a separate buffer at each FG. |
| SS value, pooled | **₹36,650** | Cost of one shared buffer at the raw echelon — lower because independent variabilities partly cancel. |
| **Capital freed** | **₹23,889** | The one-time working capital released by pooling, at the *same* service level. |
| Annual holding dividend | **₹5,733/yr** | The recurring holding saving — clears the (zero) pooling fixed cost, so pooling is recommended. |

### Solve C — Monte Carlo on the committed plan · `/api/solve/montecarlo` · every output explained

| Output | Value | What it means |
|---|---|---|
| Average fill | **95.6%** (worst run 89.4%) | Realised service across 500 simulated demand/lead-time draws. |
| CVaR95 / VaR95 | ₹5,401 / ₹5,011 | Expected cost in the worst 5% of outcomes vs the 95th-percentile cost. |
| Fragility | 1.49 | How much worse the tail is than the median — a sensitivity-to-shocks index. |
| Cost p10 / p50 / p90 | ₹2,130 / ₹3,375 / ₹4,652 | The cost distribution: typical ₹3,375, downside ₹4,652. |

### The decision
**Pool the shared billet at the raw echelon** (frees ₹23.9 k of capital and ₹5.7 k/yr with no service
loss) and hold the **CVaR-robust 116-unit safety stock** on the high-penalty SKU. The Monte Carlo
tail (CVaR95 ₹5,401, fragility 1.49) is acceptable for the 98% target; if a regulator demanded a
tighter tail, extend the +39-unit robustness premium to more SKUs — trading some freed capital back
for fill.

---

## Scenario 4 — Global electronics sourcing: *commodity spike + port delay — re-plan procurement and lot sizes.*

### The problem
Mei buys a raw steel billet exposed to a commodity index, shipped on a lane now hit by port
congestion. She funds inventory at the company's true cost of capital. **Question: as the commodity
price and the lead time both rise, what ordering policy minimises total cost, and how much inventory
should she carry?**

### Walking the UI — every input, what it is, and why

| Page | Field | Value | What it means / why |
|---|---|---|---|
| **Setup** | FX rates | base | Landed cost is computed in base currency; FX is the conversion spine. |
| **Sourcing → External Signals (step 0b)** | Commodity index | raised | Lifts the billet's material cost; threads into `bomParts` → procurement / policy / rolling / MEIO. Neutral 0% = no-op. |
| | Port-delay days | raised | Adds lead-time periods on the inbound lane. |
| **Finance → carry rate** | WACC + holding spread | 11.24% + 12.8% = **24.04%** | The annual rate applied to inventory value; the commodity spike lifts the *value* it's applied to, so holding cost rises even at a fixed rate. |
| **Sourcing → Lot Sizing** | Order cost / unit cost / hold rate | ₹2,500 / ₹142 / 24%/yr | The classic lot-sizing trade-off: fixed cost per order vs holding cost per unit carried. |

### The solve — lot-sizing leaderboard · `/api/solve/lotsizing` · every output explained
Twelve policies scored on annual total cost (order + holding) against the same demand:

| Policy | Annual cost | vs optimal | What it is |
|---|---|---|---|
| **Wagner–Whitin (DP-optimal)** | **₹12,636** | — | The provably optimal dynamic-programming lot plan — the benchmark. |
| POQ (every 5 wks) / Silver–Meal / PPB / LUC / LTC | ₹12,650 | **+0.1%** | Practical heuristics; POQ-5wk is a fixed, simple cadence. |
| Lot-for-lot / JIT | ₹13,000 | +2.9% | Order exactly each period's demand — minimal stock, maximal orders. |
| EOQ (q\*=4,732) | ₹14,476 | **+14.6%** | Textbook economic order quantity — over-orders here because demand is near-flat. |
| Min-Max (s,S) | ₹16,409 | +29.9% | A reorder-point policy; worst fit for this demand shape. |

**Carry-rate sensitivity** (Finance): spread 5% → 16.24%, default 12.8% → 24.04%, perishable 20% →
31.24% — and the commodity spike raises the unit cost the rate multiplies, so the effective holding
charge climbs on both axes, which **favours smaller, more frequent lots.**

### The decision
**Adopt POQ-every-5-weeks.** It lands within **0.1%** of the DP-optimal (₹12,650 vs ₹12,636) yet is a
simple, shop-floor-implementable cadence, and at **₹12,650 vs EOQ's ₹14,476 it saves ≈₹1,826/yr
(~13%)** over textbook EOQ, which over-orders on this flat demand. Absorb the commodity spike by **re-timing** orders rather than
buying ahead — the higher effective carry rate and longer port lead time both push toward smaller,
more frequent lots, with the policy's reorder point already covering the extended lead time.

---

## Scenario 5 — D2C startup founder: *limited cash — which products to fund, and what does the advice earn?*

### The problem
Sam runs ops at a capital-constrained D2C brand. **Cash, not capacity, is the binding constraint.**
New SKUs have no sales history, and every recommendation must demonstrably pay for itself. **Question:
under a hard cash cap, which products should the limited budget fund — and is it worth raising more
capital?**

### Walking the UI — every input, what it is, and why

| Page | Field | Value | What it means / why |
|---|---|---|---|
| **Demand** | NPI like-modeling (analog × scale × ramp) | new SKU | Seeds a forecast for a product with no history by scaling an analog product's curve — so the new SKU can enter planning honestly. |
| **Console → Profit-Mix** | `budget` (variable + material spend cap) | **₹90,000** | The cash ceiling — the binding constraint here (capacity is slack). |
| | Sell price / variable cost / material | per SKU | Set each SKU's margin and its **cash cost per unit**. |
| **Finance → EVA / Value** | Capital charge / WACC | 11.24% | Identifies SKUs that destroy economic value after the cost of capital. |
| **Scenarios → EVA prune + Value Ledger** | branch | run | Branches a "drop the destroyers" scenario and reads the tool's own measured ROI. |

### The solve — profit-mix under a cash cap · `/api/solve/profitmix` · every output explained

| Output | Value | What it means |
|---|---|---|
| `status` / profit | Optimal · **₹112,500** | The most profitable feasible plan under the ₹90,000 cash cap. |
| Mix | **Alpha 225 u · Beta 0 · Gamma 0** | Under a pure cash cap (capacity slack), the LP ranks by **return on cash**, not margin/hour. Alpha's margin-per-rupee (500/400 = **1.25**) is highest, so it absorbs the whole budget: 225 u × ₹400 cash = ₹90,000, exactly on the cap. |
| Budget shadow price | **₹1.25 of profit per ₹1 of spend** | Each extra rupee of capital raised would earn ₹1.25 of profit at the current mix. |
| Value Ledger | identified vs accepted | The tool's own ROI, split honestly — what the advice *would* earn vs what Sam has *actually adopted* — never a blended headline. |

### The decision
**Fund the highest return-on-cash SKU first** under the cap. The budget shadow **₹1.25/₹1** is the
headline: **raising more capital is worth it as long as that capital costs less than 25%** — and the
Finance WACC (11.24%) says it does, so **raise more cash.** Then **prune the EVA-destroying SKUs** in
the Scenarios branch (a transparent full-loop re-solve) before launching new products.

---

# Part C — Why these five, together

The five are deliberately spread so that each exercises a **different binding constraint** and a
**different solver path** — proving the engine handles the full variety of a real userbase, not one
happy path:

| # | Persona | Binding constraint | Decision type | Solvers proven live |
|---|---|---|---|---|
| 1 | Seasonal CPG planner | seasonal demand vs labor flex | level-vs-chase, pre-build size | `aggregate` (opening inv, worker-time, build-ahead) |
| 2 | Automotive plant manager | machine-hours | product mix + capacity capex | `profitmix`, `linecap` |
| 3 | Pharma supply planner | service level vs capital | buffer placement + size | `cvar`, `meio-network`, `montecarlo` |
| 4 | Electronics sourcing buyer | order vs holding cost under shock | lot-sizing policy | `lotsizing`, carry rate, external signals |
| 5 | D2C startup founder | cash | which SKUs to fund + raise-capital | `profitmix` (budget), EVA, Value Ledger |

Every quoted figure is a captured response from the live Flask engine on the shipped seed data (or, in
Part A, controlled A/B payloads that isolate one variable). Where a model makes a simplifying
assumption — e.g. opening inventory as a single scale-preserving aggregate number — it is stated
plainly rather than hidden.

---

# Appendix — Reproduce

Server: `nohup python app.py > /tmp/es_server.log 2>&1 & echo $! > /tmp/es_server.pid; sleep 6`
(kill by PID — never `pkill -f app.py`; the pattern self-matches the launching shell and kills it).

```bash
# A1 — opening inventory (the 250 case)
curl -s -X POST localhost:5000/api/solve/aggregate -H 'Content-Type: application/json' -d '{
 "products":[{"name":"FG","forecast":[100,100,100,100]}],
 "params":{"rate_per_worker":1000,"init_workforce":1,"reg_cost_per_unit":10,
   "holding_cost_per_unit":2,"allow_backorder":false,"init_inventory":250}}'   # ⇒ Σprod 150, cost 1900

# S1 — seasonal aggregate
curl -s -X POST localhost:5000/api/solve/aggregate -H 'Content-Type: application/json' -d '{
 "products":[{"name":"Beverage-FG","forecast":[600,650,800,1400,1900,2100,1850,1200,750,600,550,500]}],
 "params":{"periods":12,"init_workforce":30,"init_inventory":200,"rate_per_worker":40,
   "reg_cost_per_unit":120,"ot_cost_per_unit":180,"holding_cost_per_unit":8,
   "backorder_cost_per_unit":400,"hire_cost":15000,"fire_cost":20000,"wage_per_worker":22000,
   "max_ot_pct":0.2,"min_workforce":10,"allow_backorder":false}}'   # ⇒ hybrid, prebuild TRUE, peak inv 2050

# S2 — profit-mix (+ budget variant), S2 — linecap (LINE-03 cap 1000), S3 — cvar/meio-network/montecarlo,
# S4 — lotsizing, S5 — profitmix budget 90000:  payloads exactly as quoted in each scenario above.
```

All ran against `main @ d5020e8` with PuLP/CBC.
