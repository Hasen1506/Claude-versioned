# End-to-end scenarios: the proof

Unit tests check each module against its author's idea of the answer. The scenarios check the whole product
against a planner's: eight small fictional companies, each worked out by hand before the engine ran, driven
through the same API calls the web client makes, from master data to the books. A ninth runs one generated
workflow over many random companies and holds every run to properties instead of hand-worked values (see
[One flow, many companies](#one-flow-many-companies)).

```bash
cd scp/engine
python -m scp.scenarios                          # all nine, in-process
python -m scp.scenarios s5-paints -v             # one scenario, every checkpoint with its derivation
python -m scp.scenarios --url http://localhost:8000   # against a running server
python -m scp.scenarios s9-generated --seeds 500 # the generated flow over 500 companies
python -m scp.scenarios s9-generated --seed 17 -v   # one generated company; its data is generated.company(17)
pytest tests/test_scenarios.py tests/test_regressions.py
```

In the app, open **Proof** (`#/proof`, also reachable before any dataset is open). It runs each scenario
against a private in-memory version store, shows the coverage of scenarios × stages, and lists every step with
its API call, what should happen and why, and each checkpoint's hand-worked value beside the engine's.
**Open starting data** loads a scenario's dataset so it can be followed by hand.

## The rules

1. **An independent oracle.** Every expected value comes from a closed form, a full enumeration, a brute-force
   search, a second solver or a ledger kept by hand, never from the engine's own code.
2. **The planner's workflow.** Each step is one thing a planner does (validate, forecast, release, plan,
   promise, firm, post movements, roll, version) and makes the API call the app makes for it.
3. **Twice.** Each scenario runs in-process (`EngineClient`) and over HTTP (`HttpClient`); every dataset is
   parsed back into typed models between calls, so nothing is lost on the wire.
4. **The arithmetic travels with the answer.** A checkpoint is `expected · actual · why`. A failure says what
   was expected, what came back, and how the expected value was reached.
5. **Every defect is pinned.** A defect a scenario finds gets the smallest dataset that shows it in
   `tests/test_regressions.py`, failing on the old code and passing on the new, and a line in the scenario's
   `found` list, which the Proof page shows.
6. **Declared stages are checked stages.** A test keeps a scenario's `stages` equal to the stages its steps
   check, so the coverage matrix cannot overstate.

## The eight hand-worked companies

| | Company | What it tests | Checked against |
|---|---|---|---|
| S1 | Lighthouse Coffee Roasters | Three-level MRP: consumption, three lot rules, scrap on two levels, a holiday, a 26-day import that cannot arrive in time, landed cost, finance reconciliation, firming | Hand MRP tables and cost arithmetic |
| S2 | Northwind Kettles | DRP to two DCs, cumulative ATP with look-ahead, alternative shipping, CTP, a transfer that slips, backorder processing with and without CTP, the control tower | Hand ATP, the CTP chain, each BOP outcome |
| S3 | Summit Bikes | S&OP under a capacity crunch: build-ahead, overtime, shadow prices and ranges, profit mode, release to MRP, a weekend crew's NPV and IRR | A hand LP solution and a second LP in SciPy; closed-form NPV |
| S4 | Corner Grocer | The forecast competition on seven series with known answers: trend, season, intermittent, promotion lift, an outlier, a launch with cannibalisation, override, release | Series built from known components |
| S5 | Harbour Paints | Safety stock: pooling, lead-time variance, single- vs multi-echelon placement, the square-root law, fill rate with EOQ, one number in MRP and inventory, DDMRP | Full GSM enumeration; closed forms; normal loss; zone arithmetic |
| S6 | Fjord Outfitters | Month-end: plan, promise, firm, two weeks of goods movements, roll-forward, accuracy, OTIF, supplier reliability, idempotence, late postings, the version lifecycle | A hand stock ledger; KPI arithmetic; SHA-256 of canonical JSON |
| S7 | Oakleaf Bakery | Scheduling through allergen changeovers: EDD, the improved sequence, a manual override, labour against headcount | All 720 sequences on an independent shift clock |
| S8 | Crescent Preserves | The go-live gate: one planted mistake per readiness rule, found once on the right object; demand unblocks before supply | The planted list, exactly |
| S9 | Generated companies | The whole flow, gate to saved version, over random companies (12 in the suite; any number from the CLI) | Invariants, agreements between modules, metamorphic relations |

## One flow, many companies

Why are S1–S8 eight separate companies rather than one flow with the inputs varied? Because each checkpoint
there is a *value* worked out by hand, and a hand derivation only stays followable on a company built for it:
three items to show consumption, one import that cannot arrive in time, a shift clock small enough to
enumerate. Vary the inputs and the hand answer is gone. Those scenarios catch what no relation can: a number
that is wrong while every module agrees with every other (the fill-rate placement priced as a cycle-service
level was internally consistent; only a closed form caught it).

S9 (`scenarios/generated.py`) is the other half. `company(seed)` builds a random but valid company: a plant
with one or two BOM levels, up to two DCs and three customers, random lot rules, safety-stock methods (with
review periods), lead times and their spread, weekly history, forecasts, sales orders and opening stock. `flow`
takes each through the planner's workflow: validate → forecast + release → S&OP + release → MRP → placement +
apply → MRP → promise + commit → firm → post a journal (late and short receipts, the issues they draw, shipped
lines, some short) → roll a week, and another → finance → the tower → a saved version. Nobody knows the right
plan for a random company, so every run is held to what must be true of any plan:

- **Invariants**: MRP's projection is the running balance; pegging never over-allocates; an order is its pegged
  quantity plus what is not pegged, and splits into demand, buffer and lot size; dates run in order and a
  purchase order starts on a working day; dependent requirements are sized by their order. Confirmed lines plus
  unconfirmed equal what was ordered, nothing is delivered before it was asked for, and what is committed is
  what was promised. Stock after a roll is the journal's sum. The books close. A version's hash is the hash of
  what it stores, and it reads back byte for byte.
- **Agreements**: S&OP plans the demand MRP plans, node by node; after the S&OP release MRP plans each week's
  S&OP sales in that week; MRP holds the safety stock the inventory screen reports; the single-echelon
  recommendation at a node's own target is its policy's stock; MRP holds an applied placement; the optimal
  placement never costs more than buffering every stage.
- **Metamorphic relations**: the same company with every table in another order, or started whole weeks
  later, gets the same plan; firming every planned order and planning again changes nothing; promising again
  after a commit keeps every confirmation; rolling twice to a date changes nothing; rolling a week and then
  another ends where rolling two weeks does; a movement posted after its week was rolled ends where posting it
  on time does; more safety stock at a lot-for-lot node never means less supply.

A failing property names the seeds it fails for. Sweeps over 600 companies found eight defects the hand-worked
scenarios had not (the S9 `found` list): three ways firming a plan and planning again changed it, a buffer
sized on one-off requirements, a placement that rounded lead times up, and three ways the roll-forward's result
depended on how it was reached. One relation was wrong rather than the engine: under any minimum lot (EOQ, a fixed lot, a
minimum or rounding quantity, a supplier's MOQ) a bigger buffer can absorb a small later shortfall that would
otherwise be ordered as a whole lot, so total supply can rightly fall. That relation now holds only where
nothing imposes a minimum lot.

## Semantics the scenarios settled

Twenty-nine defects are listed on the Proof page and pinned in `tests/test_regressions.py`: twenty-eight the scenarios found, one an outside test found (S1 now shows it). Several
were two modules disagreeing about a definition. These are now one definition each:

- **Independent demand** (`plan/rates.py`): forecast after consumption by sales orders plus the orders, by
  planning strategy. A forecast covers `[date, date + period_days)`, and an order consumes the forecast whose
  window it falls in. MRP plans it, S&OP plans it bucket by bucket (past-due orders in the first bucket), and
  the demand rate is it averaged per day over the horizon, flowed up the network through BOM and sourcing
  shares; variances add (pooling).
- **Safety stock**: one policy function for MRP, inventory and S&OP, on the shared rate (a node only firm or
  one-off requirements draw on has no forecast error and holds no statistical buffer). A fill-rate target is
  sized as a fill rate everywhere, placement included: the `k` with σ·G(k) = (1 − β)·Q against the node's
  typical lot (EOQ, fixed, periodic, or a bucket of demand), over the lead time plus the review period. The
  placement's cost curve per stage carries that `k` at each net replenishment time, charged on the demand
  the stage really covers (whole-day service times round a lead time up; the stock does not).
- **Lateness is a quantity, not an order**: MRP's projected availability says how much of each order is
  available by when. When an input is only partly late, the share its on-time inputs cover stays on time and
  only the rest slips, which is what promising confirms for the same demand. (Found by an outside test,
  Meridian Filters: a 50-unit shipment with 35 in stock was all reported late; promising confirmed 35 on time.)
- **Placement is applied, not retyped**: `POST /api/inventory/apply` writes the recommended buffers as fixed
  safety stock, and MRP then holds exactly them.
- **S&OP release** writes the constrained demand *and* stock targets; MRP nets against the targets as a
  threshold, so the build-ahead survives the hand-off. The threshold is checked where requirements fall,
  buckets start and targets are set, never on a date where only a receipt lands.
- **Firm supply is pulled in before new supply is planned** when a new order could not land sooner, judged for
  the lot that would replace it (its size sets its production time). Firming a plan and planning again
  therefore changes nothing.
- **An order says what it is for**: its quantity splits into requirements, the buffer (`for_buffer`) and lot
  size rounding (`for_lot_size`). A purchase order starts on the buyer's working day.
- **A sale counts when the customer receives it** (goods issue plus lane transit) for accuracy, OTIF and
  history.
- **The journal is the record**: every roll recomputes from original quantities and the whole journal, so a
  movement posted late for an elapsed day reaches stock, history, every closed week's accuracy and the
  closed-order log on the next roll; rolling twice ends where rolling once does.
- **ABC ranks on cleansed revenue**, the history the forecast uses.
- **A confirmed delivery is never before the requested date.**
- **Readiness blocks by consumer**: an error in demand's own inputs blocks forecasting; any error blocks
  supply planning.

## Writing a scenario

A scenario is a module in `engine/scp/scenarios` exporting `SCENARIO = Scenario(...)`. Abridged from S1:

```python
def build() -> dict: ...                       # the starting dataset, as JSON
def run(ctx: Ctx, c: Client, ds: Dataset):
    with ctx.step("Run MRP", "plan", "POST /api/plan", "The first import cannot arrive in time."):
        plan = c.plan(ds)
        risk = [e for e in plan.exceptions if e.code == "DEMAND_AT_RISK"]
        ctx.near("demand at risk (bags)", sum(e.qty or 0 for e in risk), 100, 1e-6, "Of the 2 Feb order's 350, 150 are on time; 100 of the rest reach 2 Feb late.")
        ctx.eq("exceptions", sorted((e.code, e.product) for e in plan.exceptions),
               [("DEMAND_AT_RISK", "FG-BAG"), ("START_IN_PAST", "RM-GREEN"), ("STOCKOUT", "RM-GREEN")])
    with ctx.step("Reconcile the plan in money", "finance", "POST /api/finance"):
        rec = c.finance(ds).reconciliation
        ctx.true("books close", rec.reconciled, expect="every category's difference is 0",
                 actual=[(x.category, x.difference) for x in rec.lines])
```

Register it in `scenarios/__init__.py`. The test suite runs it over the engine and over HTTP, and the Proof
page lists it.
