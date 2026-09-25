# End-to-end scenarios: the proof

Unit tests check each module against its author's idea of the answer. The scenarios check the whole product
against a planner's: eight small fictional companies, each worked out by hand before the engine ran, driven
through the same API calls the web client makes, from master data to the books.

```bash
cd scp/engine
python -m scp.scenarios                          # all eight, in-process
python -m scp.scenarios s5-paints -v             # one scenario, every checkpoint with its derivation
python -m scp.scenarios --url http://localhost:8000   # against a running server
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

## The eight companies

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

## Semantics the scenarios settled

The scenarios found fourteen defects (listed on the Proof page and in `tests/test_regressions.py`). Several
were two modules disagreeing about a definition. These are now one definition each:

- **Demand rate** (`plan/rates.py`): forecast after consumption plus sales orders, averaged per day over the
  horizon, past-due excluded, flowed up the network through BOM and sourcing shares; variances add (pooling).
  MRP and inventory read it; S&OP uses it for safety stock (its bucket demand still takes the larger of
  forecast and orders, an open item).
- **Safety stock**: one policy function for MRP, inventory and S&OP; a fill-rate policy uses the node's
  typical lot (EOQ, fixed, periodic, or a bucket of demand).
- **S&OP release** writes the constrained demand *and* stock targets; MRP nets against the targets as a
  threshold, so the build-ahead survives the hand-off.
- **A sale counts when the customer receives it** (goods issue plus lane transit) for accuracy, OTIF and
  history.
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
        ctx.near("demand at risk (bags)", sum(e.qty or 0 for e in risk), 550, 1e-6, "200 + 100 + 250 = 550.")
        ctx.eq("exceptions", sorted((e.code, e.product) for e in plan.exceptions),
               [("DEMAND_AT_RISK", "FG-BAG"), ("START_IN_PAST", "RM-GREEN"), ("STOCKOUT", "RM-GREEN")])
    with ctx.step("Reconcile the plan in money", "finance", "POST /api/finance"):
        rec = c.finance(ds).reconciliation
        ctx.true("books close", rec.reconciled, expect="every category's difference is 0",
                 actual=[(x.category, x.difference) for x in rec.lines])
```

Register it in `scenarios/__init__.py`. The test suite runs it over the engine and over HTTP, and the Proof
page lists it.
