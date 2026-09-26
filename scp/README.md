# SCP: supply chain planning for small and mid-sized organisations

An SAP S/4HANA / IBP / Kinaxis-style planning system you run on your own network: model locations, products,
bills of material, routings on machines and labour, suppliers and transport lanes, check the data, and plan
it end to end.

**Read [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) first.** It covers the scope, the data model, the planning
flow, how correctness is proven, and the phased roadmap. The legacy Enterprise Simulator it replaces was removed
from the tree; it stays in git history at commit `176b26f`.

## Run it

```bash
# engine + API (Python ≥ 3.11)
cd scp/engine
pip install -e ".[dev]"
uvicorn scp.api.app:app --port 8000      # serves the API, and the web client once it is built

# web client (Node ≥ 20)
cd scp/web
npm install
npm run build                            # then open http://localhost:8000
# or, for development with hot reload:
npm run dev                              # http://localhost:5173 (proxies /api to :8000)
```

Start from an example (a fictional multi-echelon appliance maker with two years of sales history, or a
one-product plant), create a blank
network, or import a dataset JSON. The dataset is saved in your browser and can be exported at any time.

## Getting your own company in

- **Set up** builds a company the way a planner describes it: places, and the routes between them (click two places
  on the map); products; and for each product at each place how it gets there: made here from these parts on this
  line, bought from a supplier, or shipped from another place, with stock and ordering rules.
- **Every table uploads from a spreadsheet**: CSV, Excel (.xlsx) or cells pasted from one, with a template to
  download, loose column names ("Qty", "Quantity", "Item"), places and products by id or name, and a preview of
  which rows are added, updated or skipped, and why. Bills of material and routings upload as one row per
  component or step.
- **Demand → Demand plan** is the demand the supply plan works to, product × place × week, typed in place or
  uploaded; the forecast is one way to fill it.
- **The data check** starts with a "What's missing" checklist in setup order, each line with the button that fixes
  it. A record you haven't finished (a lane with no places chosen yet) is set aside with its reason and the rest
  keeps planning; it never locks the company.

## Master-data depth (Phase B)

- **Products at places** is the material master at plant level: MRP 1 (ordering, MRP controller), MRP 2 (procurement
  type, phantom, lead times, scheduling margin), MRP 3 (strategy, consumption, safety stock) and MRP 4 (production
  versions, a multi-level BOM explorer on any date, where used), with the stock/requirements list (every receipt
  and requirement by date, and the stock after it) on the same page. The index filters by who plans each product.
- **Machines & shifts**: named shifts with clock times, breaks and weekdays; capacity changes for a period (a
  shutdown, a second shift from a date, more machines, a slower run-in); a week drawn as clock bars and the hours
  week by week beside the plan's load. MRP, the capacity plan, lead times and the shop floor schedule all read the
  same day-by-day hours (`engine/scp/time/capacity.py`).
- **BOMs and routings**: date-effective lines (engineering change), fixed-quantity parts, phantom assemblies, co-
  and by-products with cost shares, step scrap, overlapping steps, steps done outside by a supplier, and
  alternative machines. One module applies the rules for every planner (`engine/scp/plan/structure.py`).

What real use turned up, and what was done about it, is logged in [docs/USABILITY_LOG.md](docs/USABILITY_LOG.md).

## What is here (P0–P10)

| Area | Where | What it does |
|---|---|---|
| Data model | `engine/scp/model` | Typed master and transactional data. Fractions are 0–1, and quantities are in base UoM. Units are enforced by the schema, not by convention. |
| Readiness gate | `engine/scp/validate` | 34 coded master-data and execution-data checks with fix hints. Errors block planning. Unfinished records (a schema error, or a reference left empty) are set aside with a plain reason instead of rejecting the dataset (`lenient.py`), and a setup checklist says what is still missing, in setup order (`setup.py`). |
| Network | `engine/scp/network` | Supply options per (location, product), low-level codes across BOM and transport edges, cycle detection. |
| Supply planning | `engine/scp/plan` | Network MRP/DRP: forecast consumption by strategy, PIR splitting, safety stock (fixed / coverage / α / β), lot sizing (L4L / FIXED / EOQ / POQ / MIN_MAX + MOQ / rounding / max split), quota sourcing, working-day scheduling, firming fence, BOM explosion with scrap, capacity / supplier / lane load, pegging, delay propagation, exceptions, cost KPIs. |
| Demand planning | `engine/scp/demand` | History to periods, cleansing (event baseline, robust outliers), ABC/XYZ and demand-pattern segmentation, a 12-model competition on a rolling backtest (MASE / WAPE / bias / value added), prediction ranges, events with measured lifts, NPI like-modelling with ramp and cannibalisation, consensus overrides, and release as forecast demand. Google TimesFM is an optional candidate model ([docs/TIMESFM.md](docs/TIMESFM.md)). |
| Inventory optimisation | `engine/scp/inventory` | Demand and its variability flowed up the network (risk pooling), the single-echelon α baseline with lead-time variance, multi-echelon placement with the Graves–Willems guaranteed-service model solved exactly as a MILP (HiGHS), DDMRP buffer zones and net-flow position, and a pooling (square-root law) analysis. Recommendations reach the plan only after the planner approves them. |
| S&OP | `engine/scp/sop` | A time-phased network LP over the same master data (HiGHS): production, purchases, transfers, stock, late and lost demand, overtime; limits on resource hours, overtime, suppliers, lanes, storage and shelf life; cost or profit mode; shadow prices with their validity ranges; demand and capacity scenario levers; release of the constrained volumes to MRP. |
| Detailed scheduling | `engine/scp/schedule` | Finite sequencing of the MRP make orders inside a scheduling window, plus firm production orders, in clock time on each resource's shift windows (OEE, parallel units with sublots, queue times). Setups depend on sequence: a changeover matrix per resource, minor setups inside a setup group, and none for the same product. An EDD baseline is improved by campaign and insertion moves on a weighted tardiness + changeover objective, and an independent feasibility checker verifies every schedule. Planners can also give their own sequence. Labour pools are load-checked per day. |
| Order promising | `engine/scp/promise` | aATP-style promising: cumulative ATP with look-ahead over stock, firm and (optionally) MRP planned receipts net of MRP dependent demand and earlier promises; complete or partial delivery with split schedule lines; total replenishment lead time with unconditional confirmation beyond it (or backorders); product allocations per period and customer group with next-period or reject fallback; alternative shipping locations; multi-level capable-to-promise through transfers, production (components and finite free capacity) and purchasing; persisted confirmations with at-risk detection; backorder processing by segment with Win / Gain / Redistribute / Fill / Lose and a gain/loss log. |
| Orders & actuals | `engine/scp/actuals` | A goods-movement journal (opening, receipt, component issue, sale, transfer issue, scrap, count adjustment) from which on-hand is derived; firm receipts that keep their original quantity and their reservations (production components, or a transfer's goods at its origin); firming of planned orders in a firm zone into production, purchase and stock-transfer orders; an idempotent roll-forward to a new planning start that reduces and closes orders, trims confirmations, drops elapsed forecast, appends sales to history and logs forecast vs actual per series-week; forecast accuracy (WMAPE, bias) and a closed-order log with due and delivery dates. |
| Versions & scenarios | `engine/scp/versions` | An SQLite store (`$SCP_DB`, default `~/.scp/scp.sqlite`) of immutable base versions, each kept as canonical JSON with its SHA-256 (the database refuses updates to a base), and mutable scenario branches that can be saved, discarded or promoted into a new base, with an audit log; a dataset diff keyed by object identity down to the field; side-by-side MRP KPIs for any two versions or the working copy. |
| Finance | `engine/scp/finance` | Plan cost by category, reconciled three ways (the KPI, Σ order costs and node holding, served + unabsorbed); cost to serve that follows the pegging upstream (an order's full cost includes its inputs, demand carries the pegged share, holding goes by quantity × days held, opening stock and firm receipts consumed at unit value) with revenue and margin by customer, region or product; inventory value per bucket, product type and location; capacity investment appraisal on the S&OP plan: the shadow-price estimate within its valid range, confirmed by a re-solve with the hours added, then annual cash, NPV, IRR and payback. |
| Control tower | `engine/scp/tower` | The KPI set of the S/4 guide §18.2, each with its definition, source, numerator and denominator, a breakdown and a graded target: forecast accuracy and bias, confirmation on the requested date, OTIF to the confirmed and to the requested date, perfect order (its delivery part), supplier reliability, schedule adherence, days of supply, excess & obsolete, plan stability against the previous base version, exception ageing, and cost to serve. A KPI with no data says so and is not graded. One exception worklist from the supply plan, promising, overdue orders, forecast bias and stock with no demand, with owners from rules or by hand, an SLA per category, and a life cycle (open, acknowledged, resolved, cleared, reopened) kept in the version store and aged on the planning clock. Master-data defects go to a separate data-quality view. |
| End-to-end proof | `engine/scp/scenarios` | Nine scenarios driven through the API from master data to the books, 251 checkpoints in all. Eight are fictional companies worked out by hand, each checkpoint with its expected value, the engine's and the derivation, checked against independent oracles (closed forms, full enumeration, brute force, a second LP, hand ledgers). The ninth runs the whole flow over randomly generated companies and holds each run to invariants, agreements between modules and metamorphic relations. Run with `python -m scp.scenarios`, or in the app on the Proof page. See [docs/SCENARIOS.md](docs/SCENARIOS.md). |
| API | `engine/scp/api` | `examples`, `schema`, `rules`, `validate`, `network`, `forecast`, `forecast/release`, `inventory`, `inventory/apply`, `sop`, `sop/release`, `plan`, `schedule`, `promise`, `promise/check`, `promise/bop`, `promise/commit`, `actuals`, `actuals/roll`, `orders/firm`, `versions` (list, save, get, save scenario, branch, discard, promote, compare), `compare`, `finance`, `tower`, `tower/items` (assign, acknowledge, resolve, note, history), `scenarios` (list, dataset, run) |
| Web | `web/src` | The legacy app's brutalist design language (Mono / Noir / Sepia themes, numbered stages, a planning-spine freshness strip, provenance and "reading" boxes), a network map with product trace, schema-generated editors with undo/redo, readiness, the demand workspace (leaderboards, cleansing log, consensus grid, release), the inventory workspace (service-time placement chart, approve-to-apply recommendations, DDMRP zone bars, pooling), the S&OP workspace (demand vs constrained supply, capacity with the value of an hour, shadow prices, scenario pin-and-compare, release), the plan workspace (KPIs, stock/requirements, capacity, orders with a pegging tree), and the scheduling workspace (a planning board Gantt with shift windows, changeover hatching and late flags, click-to-follow orders and move them in the sequence, the setup-matrix editor, labour load), and the promising workspace (order book with schedule-line chips, the ATP picture per shipping location, a new-order check with the CTP chain as a timeline, the BOP segment cascade with its gain/loss log, allocation consumption), and the execution workspace (stock reconciliation against the journal, open orders with quick receive / ship posts, firming from the plan, the movement journal with a posting form, roll-forward with its report, forecast accuracy by series), and the finance workspace (cost reconciliation with the books-close check, cost to serve and margin with a cost-composition bar per customer, region or product, inventory value by product type over time, capacity options with dual vs re-solve, NPV, IRR, payback and cash flows), and the control tower (KPI cards graded against target with an icon and label, a drill-down per KPI with its definition and breakdown, the worklist with owner, age against SLA, acknowledge / resolve, notes and item history, ageing and owner summaries, the data-quality view, and the owner-rule, SLA and target settings), and the Proof page (the end-to-end scenarios by stage, run in the app, with every checkpoint's derivation and each scenario's starting data one click away), and the versions workspace (the version tree, save as base or scenario, open, branch, discard, promote, and a compare view with plan KPIs side by side and a field-level diff), with the working copy's version and unsaved state shown in the top bar. |

## How correctness is checked

```bash
cd scp/engine && ruff check scp tests ../examples && python -m pytest -q   # lint + all engine tests
cd scp/web && npm run gen:api && git diff --exit-code src/api/schema.d.ts   # UI types == engine
cd scp/web && npm run build && npx playwright test   # end-to-end in a real browser
cd scp/engine && python -m scp.scenarios            # eight hand-worked companies + the generated flow
cd scp/engine && python -m scp.scenarios s9-generated --seeds 500   # the generated flow, 500 companies
```

- **End-to-end scenarios:** eight companies with hand-derived answers, run in-process and over HTTP; each defect they
  found has a regression test in `tests/test_regressions.py` ([docs/SCENARIOS.md](docs/SCENARIOS.md)).
- **One flow, many companies:** the whole workflow over randomly generated companies, each run held to invariants,
  agreements between modules and metamorphic relations (same company reordered or shifted in time, firm-and-replan,
  roll twice, post late) instead of hand-worked values.
- **Types:** invalid values cannot be constructed. The API answers 422 and names the field.
- **Readiness rules:** each rule has a test that makes it fire and a clean dataset that passes.
- **Golden scenarios:** hand-computed MRP cases, covering netting, lot sizing, scrap, working days, fences,
  quotas, transfers, MTO/ATO and reorder point.
- **Forecast models on known series:** constants, lines, pure seasons and intermittent patterns have
  exact answers; metrics are checked by hand; champion selection and tie-breaks are tested.
- **Multi-echelon placement:** hand-computed two-stage cases, the extreme-point property on serial lines, and
  exact agreement with brute-force enumeration on 120 random networks. DDMRP zones are checked against the formulas.
- **S&OP LP:** capacity shadow prices equal a finite-difference re-solve (cost and profit mode); a single
  resource in profit mode reproduces margin-per-bottleneck-hour ranking; pre-build, overtime, supplier limits,
  shelf life and release are tested on hand-sized cases; material balance holds on the examples.
- **Detailed scheduling:** shift-window arithmetic, the setup rule and matrix, and campaigning (A B A B → A A B B) are
  checked on hand cases. An independent checker (no unit overlap, work inside windows, release and precedence with
  queue times, setups matching the rule, quantities complete) passes on the examples and on 60 random instances for
  the EDD, improved and shuffled sequences. The improver never returns a worse objective than EDD.
- **Order promising:** the guide's §20.1 scenarios 2–5 are tests (full stock on the requested date; partial
  stock with split lines, complete delivery and RLT behaviour both ways; an allocation-capped order with both
  fallback rules; BOP after a shortage where the priority customer gains and the low-priority one loses),
  plus the ATP look-ahead, alternative locations, CTP through purchase → production → transfer, commit and
  simulation without persistence.
- **Orders & actuals:** stock equals the sum of movements on 40 random journals, before and after rolling forward;
  firming every planned order and re-planning creates no new orders and reproduces the projection bucket for bucket;
  rolling forward twice to the same date changes nothing; receipts, reservations and sales orders close by
  quantity, tolerance or a final flag with their delivery dates; WMAPE and bias are checked by hand; the example's
  first-week journal rolls forward cleanly.
- **Versions:** a base version's stored bytes and hash are identical after a scenario is branched from it, edited
  and discarded, and after a scenario is promoted over it; the database itself rejects an update to a base; stored
  datasets round-trip losslessly and survive a new connection; the diff ignores re-ordering and reports field changes.
- **Finance:** cost to serve on a two-level BOM matches a hand calculation; lot-size excess is unabsorbed pro rata;
  opening stock is valued, not spent; on both examples every plan cost category equals Σ its sources and
  served + unabsorbed to 1e-9, and inventory value reconciles to the plan KPIs; the capacity dual estimate equals
  the re-solved saving within its range (cost and profit mode), is capped beyond it, and NPV / IRR / payback are
  checked by hand.
- **Control tower:** every KPI is checked by hand on a fixture of closed orders, confirmations and accuracy records
  (tolerance, split deliveries, week boundaries included), and the inventory KPIs are checked against the plan;
  KPIs with no data are None, not a default; the grading bands are tested; the worklist ages on the planning clock,
  keeps a hand assignment, clears what is no longer detected and reopens it with a fresh age; a manual resolve holds
  for the day and reopens later; master-data issues never reach the worklist; plan stability is 1 against an
  equivalent base and drops by exactly the orders that moved.
- **Plan invariants:** material balance, pegging, requirement sizing and date order. These are checked on the
  examples and on 40 randomly generated networks.
- **CI** runs all of it (`.github/workflows/scp.yml`).

Regenerate the examples with `python scp/examples/build_examples.py`. CI checks that they are reproducible.
