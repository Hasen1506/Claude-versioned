# SCP: supply chain planning for small and mid-sized organisations

An SAP S/4HANA / IBP / Kinaxis-style planning system you run on your own network: model locations, products,
bills of material, routings on machines and labour, suppliers and transport lanes, check the data, and plan
it end to end.

**Read [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) first.** It covers the scope, the data model, the planning
flow, how correctness is proven, and the phased roadmap. This directory is independent of the legacy app in
the repository root.

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

## What is here (P0–P7)

| Area | Where | What it does |
|---|---|---|
| Data model | `engine/scp/model` | Typed master and transactional data. Fractions are 0–1, and quantities are in base UoM. Units are enforced by the schema, not by convention. |
| Readiness gate | `engine/scp/validate` | 34 coded master-data and execution-data checks with fix hints. Errors block planning. |
| Network | `engine/scp/network` | Supply options per (location, product), low-level codes across BOM and transport edges, cycle detection. |
| Supply planning | `engine/scp/plan` | Network MRP/DRP: forecast consumption by strategy, PIR splitting, safety stock (fixed / coverage / α / β), lot sizing (L4L / FIXED / EOQ / POQ / MIN_MAX + MOQ / rounding / max split), quota sourcing, working-day scheduling, firming fence, BOM explosion with scrap, capacity / supplier / lane load, pegging, delay propagation, exceptions, cost KPIs. |
| Demand planning | `engine/scp/demand` | History to periods, cleansing (event baseline, robust outliers), ABC/XYZ and demand-pattern segmentation, a 12-model competition on a rolling backtest (MASE / WAPE / bias / value added), prediction ranges, events with measured lifts, NPI like-modelling with ramp and cannibalisation, consensus overrides, and release as forecast demand. Google TimesFM is an optional candidate model ([docs/TIMESFM.md](docs/TIMESFM.md)). |
| Inventory optimisation | `engine/scp/inventory` | Demand and its variability flowed up the network (risk pooling), the single-echelon α baseline with lead-time variance, multi-echelon placement with the Graves–Willems guaranteed-service model solved exactly as a MILP (HiGHS), DDMRP buffer zones and net-flow position, and a pooling (square-root law) analysis. Recommendations reach the plan only after the planner approves them. |
| S&OP | `engine/scp/sop` | A time-phased network LP over the same master data (HiGHS): production, purchases, transfers, stock, late and lost demand, overtime; limits on resource hours, overtime, suppliers, lanes, storage and shelf life; cost or profit mode; shadow prices with their validity ranges; demand and capacity scenario levers; release of the constrained volumes to MRP. |
| Detailed scheduling | `engine/scp/schedule` | Finite sequencing of the MRP make orders inside a scheduling window, plus firm production orders, in clock time on each resource's shift windows (OEE, parallel units with sublots, queue times). Setups depend on sequence: a changeover matrix per resource, minor setups inside a setup group, and none for the same product. An EDD baseline is improved by campaign and insertion moves on a weighted tardiness + changeover objective, and an independent feasibility checker verifies every schedule. Planners can also give their own sequence. Labour pools are load-checked per day. |
| Order promising | `engine/scp/promise` | aATP-style promising: cumulative ATP with look-ahead over stock, firm and (optionally) MRP planned receipts net of MRP dependent demand and earlier promises; complete or partial delivery with split schedule lines; total replenishment lead time with unconditional confirmation beyond it (or backorders); product allocations per period and customer group with next-period or reject fallback; alternative shipping locations; multi-level capable-to-promise through transfers, production (components and finite free capacity) and purchasing; persisted confirmations with at-risk detection; backorder processing by segment with Win / Gain / Redistribute / Fill / Lose and a gain/loss log. |
| Orders & actuals | `engine/scp/actuals` | A goods-movement journal (opening, receipt, component issue, sale, transfer issue, scrap, count adjustment) from which on-hand is derived; firm receipts that keep their original quantity and their reservations (production components, or a transfer's goods at its origin); firming of planned orders in a firm zone into production, purchase and stock-transfer orders; an idempotent roll-forward to a new planning start that reduces and closes orders, trims confirmations, drops elapsed forecast, appends sales to history and logs forecast vs actual per series-week; forecast accuracy (WMAPE, bias) and a closed-order log with due and delivery dates. |
| API | `engine/scp/api` | `examples`, `schema`, `rules`, `validate`, `network`, `forecast`, `forecast/release`, `inventory`, `sop`, `sop/release`, `plan`, `schedule`, `promise`, `promise/check`, `promise/bop`, `promise/commit`, `actuals`, `actuals/roll`, `orders/firm` |
| Web | `web/src` | The legacy app's brutalist design language (Mono / Noir / Sepia themes, numbered stages, a planning-spine freshness strip, provenance and "reading" boxes), a network map with product trace, schema-generated editors with undo/redo, readiness, the demand workspace (leaderboards, cleansing log, consensus grid, release), the inventory workspace (service-time placement chart, approve-to-apply recommendations, DDMRP zone bars, pooling), the S&OP workspace (demand vs constrained supply, capacity with the value of an hour, shadow prices, scenario pin-and-compare, release), the plan workspace (KPIs, stock/requirements, capacity, orders with a pegging tree), and the scheduling workspace (a planning board Gantt with shift windows, changeover hatching and late flags, click-to-follow orders and move them in the sequence, the setup-matrix editor, labour load), and the promising workspace (order book with schedule-line chips, the ATP picture per shipping location, a new-order check with the CTP chain as a timeline, the BOP segment cascade with its gain/loss log, allocation consumption), and the execution workspace (stock reconciliation against the journal, open orders with quick receive / ship posts, firming from the plan, the movement journal with a posting form, roll-forward with its report, forecast accuracy by series). |

## How correctness is checked

```bash
cd scp/engine && ruff check scp tests ../examples && python -m pytest -q   # lint + all engine tests
cd scp/web && npm run gen:api && git diff --exit-code src/api/schema.d.ts   # UI types == engine
cd scp/web && npm run build && npx playwright test   # end-to-end in a real browser
```

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
- **Plan invariants:** material balance, pegging, requirement sizing and date order. These are checked on the
  examples and on 40 randomly generated networks.
- **CI** runs all of it (`.github/workflows/scp.yml`).

Regenerate the examples with `python scp/examples/build_examples.py`. CI checks that they are reproducible.
