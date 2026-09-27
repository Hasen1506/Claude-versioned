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
network, or import a dataset JSON. Without signing in the company is kept in your browser (and can be exported at
any time); signed in, it is kept on the server (see Phase I below).

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

## Capacity and material together (Phase C)

- **The shop floor waits for parts.** Each step of a production order starts only once the parts it uses are there,
  following the pegging: from stock, from a purchase or transfer on its arrival day, or from the order on the same
  schedule that makes them, when that order finishes (plus goods-receipt days). Each order shows what it waited for.
- **The schedule's dates go back into the plan.** *Use these dates in the plan* makes the scheduled orders
  production orders dated by the schedule, with each part reserved for the day its step starts. The supply plan,
  promises and money then read those dates, and a late one is reported as late (`SCHEDULE_LATE`) instead of being
  covered by a duplicate order.
- **Levelling.** Each machine and crew day by day: hours asked for against hours it has, the orders on any day,
  and what planning within capacity would move. **Planning within capacity** (a company setting) places each make
  order on its own machine if the days have room, else on an alternative machine, else earlier, else later
  (reported). Released orders load their machines first and are never moved.

## Scheduling like PP/DS (Phase D)

- **Profiles.** *Shop floor → Methods & profiles* sets how to schedule in one click: balanced, protect due dates,
  fewest changeovers, just in time, finish everything soonest, or best possible (the optimiser). A profile sets the
  start rule, the search and what the score weighs (hours late, changeover hours, hours early, hours to clear the
  window); editing any of those in Settings makes them your own.
- **Heuristics and a comparison.** Earliest due date, shortest job first, least slack, campaigns by setup group and
  backward from the due date, then a local search, then a constraint solver (CP-SAT) that chooses each step's
  machine (own or alternative) and every machine's order. *Compare all methods* schedules the same orders every way
  and scores them alike; the optimiser starts from the local search's answer, so it is never worse.
- **The board.** Drag a step along its row to run it earlier or later, or onto another machine that can run it; the
  schedule is re-timed at once and the page says what changed. Orders inside the **frozen zone** (a setting) keep
  their place and machine. *Use these dates in the plan* writes exactly the schedule on screen.
- **Levelling** can prefer finishing later to building ahead, with a limit on days ahead; **promising** books
  machine hours on the days a step runs, on its own machine or an alternative.

## Buying: procure to pay (Phase E)

- **Suppliers and sources.** Each supplier can have purchasing data: contact, payment terms, whether they confirm
  orders and how soon, how much more or less than ordered a delivery may be, a minimum order value and a
  **purchasing block**. A purchasing source is the info record and source-list entry: price with **price scales**
  (quantity breaks), lead time, validity, **fixed** (planning uses it first, after any quota) and **blocked**. The
  supply plan never uses a blocked supplier or source, and prices each purchase from its scale.
- **To order.** *Buying* lists the supply plan's purchases as requisitions, due now or later, each with every source
  that could fill it: price for that quantity, when it would arrive and whether that is in time. Pick lines,
  change a line's supplier if you want (its minimum, pack size and lead time apply), and create purchase orders:
  one per supplier and receiving place. Orders worth more than the **approval limit** wait for approval.
- **Purchase orders.** Approve, mark as sent, record the supplier's **confirmation** (date and quantity), receive
  goods in parts or at once (the supplier's over-delivery tolerance is enforced, a delivery within their
  short-delivery tolerance closes the line), change a line, or cancel lines nothing has been received for. The plan
  expects a confirmed line on its confirmed date and counts no more than confirmed, and says when a supplier
  confirms late, confirms less, or hasn't confirmed in time. Firming a purchase from *Actuals* goes through the same
  order creation, so both roads give the same orders.
- **Suppliers.** A scorecard from the closed-order log (on time, in full, average days late) and each supplier's
  sources with their price scales, one click from blocking the supplier.

## Execution you can trust (Phase F)

- **Opening balances and counts.** Stock entered at setup is the opening balance of a place with no earlier
  movement; starting a new week writes it into the journal. *Actuals → Count stock* lists every product at every
  place it is kept: a count posts an opening balance or a count difference, and the plan starts from it.
- **Posting against firm orders.** A transfer is shipped (in transit) and received; receiving what was never shipped
  posts the dispatch too. Confirming a production order posts what was made, issues its parts in proportion (or the
  parts actually used), receives co-products and warns when a part goes below zero. A purchase is received through
  Buying's goods receipt. Movements upload without an id column.
- **Late postings.** A posting dated before the planning start is shown with what it would change (stock, orders,
  forecast accuracy, closed orders), counted with one click; Home leads with it, and with stock that disagrees with
  the journal.
- **One road to a purchase order.** Firming groups purchases per supplier as Buying does, and a planned purchase that
  an open order would cover if it came sooner says so.

## Sensible defaults (Phase H)

- **The company first.** A new company starts with its name, currency, planning start, working days and how much
  an order covers; *Set up → Your company* changes them and keeps the exchange rates.
- **A week's need per order.** Where a product's planning policy leaves the lot size empty, the company default
  applies: a week's need for a new company, instead of a new order for every day's need.
- **Whole units.** Products counted in pieces (EA, box, case, tin, pail, …) are planned and forecast in whole units;
  products in kg, litres or metres keep their fractions. The product list can override either way.
- **Batch steps.** A step can run in batches (a 2,000 L mixer, 3 hours a batch however full); orders come in whole
  batches and capacity, scheduling and lead times use the batch time.
- **Sales sheets as they are.** Demand and history uploads read customer, month and units-sold columns; a month or a
  week is a total spread over its days, and months across the top become one row each.
- **Prices and currencies in setup.** Selling prices and costs on the product list; a supplier's price in the
  currency it invoices in, turned into the company's with the rate kept once.

## Order to cash, first steps (Phase G)

- **Take a customer order.** *Customer orders → New order* checks availability, then *Take this order* saves it as a
  sales order (the next number in the company's series) with the promise it was given, so later orders cannot take
  its stock. It carries its own price and the customer's order number if given.
- **Deliver, change, cancel.** Each open order delivers in full or in part from where it was promised, changes
  (quantity, date, priority, price, delivery rule) and is promised again, or has the rest cancelled; a cancelled
  order stays in the closed-order log and does not count against OTIF.
- **Prices per customer.** A customer's own price beats the product's; an order's own price beats both.
- **No revenue without a price.** Money, Home and the capacity plan count revenue and margin only where a price
  exists, and name the products that have none.

## The company on the server (Phase I)

- **Sign in and keep the company on the server.** *Sign in, companies, people* makes an account (e-mail and password)
  and keeps the company open in the browser on the server; whoever does so is its owner. The top bar always says
  where the company is kept and whether the latest change is saved (*In this browser only*, *Saving…*, *Saved 10:42*,
  *Not saved*); a browser that cannot keep a browser-only company says so instead of failing silently.
- **Colleagues and roles.** An owner adds people by e-mail as *owner*, *planner* (changes the data) or *viewer*
  (looks, changes nothing); an e-mail without an account yet joins on signing up. A company always keeps an owner.
- **Saved as you go, never over a colleague unseen.** Every change is saved a moment later. A save made on top of an
  older revision than the latest is refused and the page says who saved and when; *Merge both* keeps both people's
  changes record by record (an order both took under the same number gets the next one), or either side can be kept.
  A colleague's newer save is announced within a minute.
- **History.** Every save, merge, put-back and membership change, with who, when and what changed per list (the
  records by name). Earlier states can be compared with now and put back; nothing is lost by putting back.
- **Kept per company.** Plan versions and the worklist belong to the company that is open, and only its members see them.
- **Server settings.** `SCP_DB` is the SQLite file (default `~/.scp/scp.sqlite`). `SCP_SIGNUP=open|invite|closed`
  says who may make an account (the first account can always be made). `SCP_REQUIRE_SIGNIN=1` answers nobody who is
  not signed in, and keeps nothing outside a company. Passwords are stored as salted PBKDF2 hashes and session tokens
  as SHA-256 hashes; sessions last 30 days from their last use.

What real use turned up, and what was done about it, is logged in [docs/USABILITY_LOG.md](docs/USABILITY_LOG.md).

## Polish (Phase J)

- **Names, not ids.** Messages from planning, the data check, postings and purchasing, the shop-floor board, the firm
  zone and the performance breakdowns name places, products and machines ("Emulsion white 20 L at Vapi paint plant");
  pickers lead with the name. Dates in messages read "Mon 28 Sep".
- **Which utilisation.** The supply plan, the capacity plan and the shop floor each say whose load it is and over what
  period (the busiest week, month or scheduling window), so their percentages can be told apart.
- **Order numbers that hold.** Planned numbers are marked temporary (every plan hands them out again); a firm order
  shows the planned number it came from ("was MO-00430"). A late requisition says when it should have been ordered.
- **A purchase order to send.** *Print or PDF*, *Download* and *E-mail* on a purchase order give the supplier a
  document with the lines, prices, dates and the supplier's terms.
- **Pages that keep up.** Actuals, Buying, Money and customer orders recalculate when opened out of date. A viewer sees
  the buttons and forms that change data disabled, with the reason on hover. The demand grid spreads a monthly
  forecast over working days as planning does; *Machines & shifts* stacks at phone width; the bottling example has an
  alternative line to move steps onto.

### Follow-up (J+)

- **Addresses on documents.** Places have a postal address and a tax number, the company an invoice address; the
  purchase order prints the supplier's, the delivery and the invoice address, and says which are missing (N69).
- **Viewers change nothing.** Every page was walked as a viewer: grids, levelling settings, buffers, the worklist,
  shop-floor profiles and version saves are disabled, not refused after typing (N70, N74).
- **Results that are simply missing** (after reopening the browser) are calculated when Actuals, Buying, Money or
  customer orders open (N71).

## Platform for real use (Phase L)

- **Saving you can trust.** Every save is kept and can be put back from *History*; a save sends only the records that
  changed; a reload during a save is never a clash with oneself; undo survives a reload; where two people changed the
  same record, each record is shown side by side and chosen *mine* or *theirs*.
- **Accounts and control.** *Forgot your password?* mails a one-time link when the server has mail, otherwise an
  owner gives one; single sign-on by OpenID Connect (Microsoft Entra ID, Google, Okta, Keycloak). An owner limits a
  planner to plants or product groups; master-data changes can wait for a second person's approval; change documents
  keep every field's old and new value.
- **Backups.** A nightly copy of the database with `SCP_BACKUP_DIR`, and `python -m scp.admin backup | check |
  restore | users | reset-link`.
- **Scale.** Measured at 5,000 products × 20 places with two years of history: the forecast runs one maths thread
  per worker (about 40 minutes → 2¼), the checks after each change are indexed and run once (22 s → 7 s), and the
  supply plan is made once per *Plan everything*, not six times.
- **Deployment.** A `Dockerfile`, `deploy/compose.yaml` with Caddy for HTTPS, and [docs/DEPLOY.md](docs/DEPLOY.md):
  settings, mail, single sign-on, the reverse proxy, backups and putting one back, the size of the machine, updating.

## Large companies (Phase S)

A company of 5,000 products at 20 places (two years of weekly history, 71 MB) works in the browser: it opens in
1.4 s, every page in seconds with under a gigabyte of script memory, and *Plan everything* is the server's own
calculation (5½ minutes the first time, 13 s again for the same data).

- **Planning on the server's copy.** For a company kept on the server, a planning call names the save its working copy
  was made from and sends only the unsaved changes (`{"$ref": {"revision", "patch"}}`, `engine/scp/api/working.py`);
  the server reads the company once, sharing every unchanged list between the save and the changes on it, and a change
  the engine makes comes back as what changed.
- **Answers kept and light.** Read-only answers are kept beside the data they were worked out on, written straight to
  JSON, compressed, and sent with their lists as rows (the browser unpacks them). The plan comes without its
  requirements and pegging (`/api/plan?pegging=false`); the pegging tree and the stock list ask for theirs
  (`/api/plan/trace`).
- **Pages at scale.** Long lists draw their first rows with a search; names are made once per working copy; an edit
  copies only the parts it touches; a company too large for the browser's storage is not copied there.
- **Engine.** Safety stock places buffers group by group on every core (30 s at the solver's limit → 11 s, optimal);
  a forecast after a change competes only the series whose history changed; a large company is planned one at a time.

## Stock you can trace (Phase O)

Stock is kept the way a food or parts business needs it, in `engine/scp/actuals/lots.py` and `documents.py`:

- **Batches with an expiry date.** A product with a shelf life is kept by batch (unless it says otherwise). A receipt
  makes a batch, dated and expiring after the shelf life unless told; issues, sales, transfers and scrap take the batch
  that expires first, and a transfer arrives in the batches it shipped. Stock that will expire before the plan uses it
  is a requirement of its own ("Expires unused"); expired stock is no longer counted and is flagged to scrap.
- **Stock types.** A product inspected on receipt goes into quality inspection until it is released; stock can be
  blocked and unblocked and scrapped. Planning counts free stock, and stock in inspection unless the company says
  otherwise; never blocked or expired stock. Stock in transit shows at the place it is going to.
- **Short receipts** name the firm orders the part no longer covers, with what each can still make, and shorten them.
- **Stock below zero** is a company rule: refuse the posting, allow it and ask for a count, or count it as found.
- **Material documents** number the movements posted together; a reversal takes a whole document back.
- **Physical inventory documents** freeze the book stock, hold postings for what is counted, and post the differences.
- **Serial numbers**, one per unit, given at receipt (or numbered) and leaving first in, first out.
- **The cold chain**: a refrigerated route mode, and a check for chilled products on routes without one.

The next plan (phases P, M, N, Q) is at the end of
[docs/USABILITY_LOG.md](docs/USABILITY_LOG.md#the-next-plan-after-phase-o).

## What is here (P0–P10)

| Area | Where | What it does |
|---|---|---|
| Data model | `engine/scp/model` | Typed master and transactional data. Fractions are 0–1, and quantities are in base UoM. Units are enforced by the schema, not by convention. |
| Readiness gate | `engine/scp/validate` | 44 coded master-data and execution-data checks with fix hints. Errors block planning. Unfinished records (a schema error, or a reference left empty) are set aside with a plain reason instead of rejecting the dataset (`lenient.py`), and a setup checklist says what is still missing, in setup order (`setup.py`). |
| Network | `engine/scp/network` | Supply options per (location, product), low-level codes across BOM and transport edges, cycle detection. |
| Supply planning | `engine/scp/plan` | Network MRP/DRP: forecast consumption by strategy, PIR splitting, safety stock (fixed / coverage / α / β), lot sizing (L4L / FIXED / EOQ / POQ / MIN_MAX + MOQ / rounding / max split, a company default where a product sets none, whole units, whole batches), quota sourcing, working-day scheduling, firming fence, BOM explosion with scrap, capacity / supplier / lane load, pegging, delay propagation, exceptions, cost KPIs. |
| Demand planning | `engine/scp/demand` | History to periods, cleansing (event baseline, robust outliers), ABC/XYZ and demand-pattern segmentation, a 12-model competition on a rolling backtest (MASE / WAPE / bias / value added), prediction ranges, events with measured lifts, NPI like-modelling with ramp and cannibalisation, consensus overrides, and release as forecast demand. Google TimesFM is an optional candidate model ([docs/TIMESFM.md](docs/TIMESFM.md)). |
| Inventory optimisation | `engine/scp/inventory` | Demand and its variability flowed up the network (risk pooling), the single-echelon α baseline with lead-time variance, multi-echelon placement with the Graves–Willems guaranteed-service model solved exactly as a MILP (HiGHS), DDMRP buffer zones and net-flow position, and a pooling (square-root law) analysis. Recommendations reach the plan only after the planner approves them. |
| S&OP | `engine/scp/sop` | A time-phased network LP over the same master data (HiGHS): production, purchases, transfers, stock, late and lost demand, overtime; limits on resource hours, overtime, suppliers, lanes, storage and shelf life; cost or profit mode; shadow prices with their validity ranges; demand and capacity scenario levers; release of the constrained volumes to MRP. |
| Detailed scheduling | `engine/scp/schedule` | Finite sequencing of the MRP make orders inside a scheduling window, plus firm production orders, in clock time on each resource's shift windows (OEE, parallel units with sublots, queue times). Setups depend on sequence: a changeover matrix per resource, minor setups inside a setup group, and none for the same product. An EDD baseline is improved by campaign and insertion moves on a weighted tardiness + changeover objective, and an independent feasibility checker verifies every schedule. Planners can also give their own sequence. Steps wait for their parts along the pegging, and the schedule's dates can be written back as dated production orders. Labour pools are load-checked per day. |
| Order promising | `engine/scp/promise` | aATP-style promising: cumulative ATP with look-ahead over stock, firm and (optionally) MRP planned receipts net of MRP dependent demand and earlier promises; complete or partial delivery with split schedule lines; total replenishment lead time with unconditional confirmation beyond it (or backorders); product allocations per period and customer group with next-period or reject fallback; alternative shipping locations; multi-level capable-to-promise through transfers, production (components and finite free capacity) and purchasing; persisted confirmations with at-risk detection; backorder processing by segment with Win / Gain / Redistribute / Fill / Lose and a gain/loss log. |
| Purchasing | `engine/scp/purchasing` | Requisitions from the supply plan with every source's price (scales), arrival and lateness; purchase orders grouped by supplier, receiving place and currency, with an approval limit; approve, send, confirm (date and quantity, which planning then uses), receive against the supplier's tolerances, change and cancel; the order view with each line's status and a supplier scorecard from the closed-order log. |
| Orders & actuals | `engine/scp/actuals` | A goods-movement journal (opening, receipt, component issue, sale, transfer issue, scrap, count adjustment) from which on-hand is derived, with setup stock as the opening balance; postings that ship and receive transfers, confirm production with backflush or actual usage, and count stock; a check of what late postings would change; firm receipts that keep their original quantity and their reservations (production components, or a transfer's goods at its origin); firming of planned orders in a firm zone into production, purchase and stock-transfer orders; an idempotent roll-forward to a new planning start that reduces and closes orders, trims confirmations, drops elapsed forecast, appends sales to history and logs forecast vs actual per series-week; forecast accuracy (WMAPE, bias) and a closed-order log with due and delivery dates. |
| Companies on the server | `engine/scp/companies` | Accounts and sessions, companies with members and roles (owner, planner, viewer) and invitations, saves refused when based on an older revision, a record-by-record three-way merge, every save a revision (one kept document per person per ten minutes, compressed), and an audit log of who changed what. |
| Versions & scenarios | `engine/scp/versions` | An SQLite store (`$SCP_DB`, default `~/.scp/scp.sqlite`) of immutable base versions, each kept as canonical JSON with its SHA-256 (the database refuses updates to a base), and mutable scenario branches that can be saved, discarded or promoted into a new base, with an audit log; a dataset diff keyed by object identity down to the field; side-by-side MRP KPIs for any two versions or the working copy. |
| Finance | `engine/scp/finance` | Plan cost by category, reconciled three ways (the KPI, Σ order costs and node holding, served + unabsorbed); cost to serve that follows the pegging upstream (an order's full cost includes its inputs, demand carries the pegged share, holding goes by quantity × days held, opening stock and firm receipts consumed at unit value) with revenue and margin by customer, region or product; inventory value per bucket, product type and location; capacity investment appraisal on the S&OP plan: the shadow-price estimate within its valid range, confirmed by a re-solve with the hours added, then annual cash, NPV, IRR and payback. |
| Control tower | `engine/scp/tower` | The KPI set of the S/4 guide §18.2, each with its definition, source, numerator and denominator, a breakdown and a graded target: forecast accuracy and bias, confirmation on the requested date, OTIF to the confirmed and to the requested date, perfect order (its delivery part), supplier reliability, schedule adherence, days of supply, excess & obsolete, plan stability against the previous base version, exception ageing, and cost to serve. A KPI with no data says so and is not graded. One exception worklist from the supply plan, promising, overdue orders, forecast bias and stock with no demand, with owners from rules or by hand, an SLA per category, and a life cycle (open, acknowledged, resolved, cleared, reopened) kept in the version store and aged on the planning clock. Master-data defects go to a separate data-quality view. |
| End-to-end proof | `engine/scp/scenarios` | Nine scenarios driven through the API from master data to the books, 251 checkpoints in all. Eight are fictional companies worked out by hand, each checkpoint with its expected value, the engine's and the derivation, checked against independent oracles (closed forms, full enumeration, brute force, a second LP, hand ledgers). The ninth runs the whole flow over randomly generated companies and holds each run to invariants, agreements between modules and metamorphic relations. Run with `python -m scp.scenarios`, or in the app on the Proof page. See [docs/SCENARIOS.md](docs/SCENARIOS.md). |
| API | `engine/scp/api` | `examples`, `schema`, `rules`, `validate`, `network`, `forecast`, `forecast/release`, `inventory`, `inventory/apply`, `sop`, `sop/release`, `plan`, `schedule`, `promise`, `promise/check`, `promise/bop`, `promise/commit`, `orders/sales` (accept, change, cancel), `actuals`, `actuals/roll`, `actuals/post` (ship, receive, deliver, count), `orders/firm`, `purchasing`, `purchasing/create`, `purchasing/act`, `versions` (list, save, get, save scenario, branch, discard, promote, compare), `compare`, `auth` (config, signup, signin, signout, me, password), `companies` (list, create, open, save, merge, history, revisions, restore, members, delete), `finance`, `tower`, `tower/items` (assign, acknowledge, resolve, note, history), `scenarios` (list, dataset, run) |
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
