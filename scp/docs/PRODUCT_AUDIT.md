# User workflow and product audit

Updated 30 September 2026. Starting main revision: `ff76b1a7126495abfc532e39e59f82703a435ec4`. This is a continuing audit, not a claim of exhaustive testing or enterprise readiness. The preceding repair evidence is in [audit.md](../../audit.md).

## Goal and acceptance gates

Make the app usable and accurate from a new user's first visit through a complete planning and execution cycle. A section passes only when its inputs, actions, results and saved state agree; opening a page alone is insufficient.

| Gate | Evidence needed before acceptance |
|---|---|
| Public entry and accounts | One documented working URL; deliberate open/invite signup policy; signup, sign-in, sign-out, expired session and recovery tested against deployment configuration; deployment revision identifiable. |
| First useful plan | An unfamiliar user can create/import a company, resolve missing data and explain the first supply plan without editing JSON or getting help from the developer. |
| Planning correctness | Independently calculated quantities, dates, capacities, stock, prices and margins agree across demand, supply, promising, buffers and scheduling. Include fractional units, calendars and partial operations. |
| Execution and collaboration | Purchase, manufacture, transfer and sales postings reconcile after week roll and reversal; owner/planner/viewer access and concurrent saves preserve the same company history. |
| Usability | Each principal section and optional tab has a clear purpose, next action, empty/error/loading state and freshness indication; keyboard and narrow-screen use tested. |
| Operational and commercial fit | Persistent storage and recovery demonstrated on the deployed host; realistic scale and latency measured; pilot users confirm the proposed problem and value. |

## This pass: direct user evidence

The Render host was inspected without creating an account or changing company data there. Mutating tests used a separate local server, SQLite file and synthetic `example.invalid` account, with sign-in required and signup open. This verifies that configuration locally; it does not establish the deployed service's signup policy, persistence or revision.

The local walkthrough created Audit Foods, a plant, a supplier and a saleable Coffee pack, priced at INR 250. Its supplier charged INR 100 with two days' lead time. Entering 100 units of second-week demand produced one purchase proposal worth INR 10,000. Creating the order, marking it sent and recording all 100 units received succeeded. The received order and company survived browser reload. The receipt's message correctly directs the user to Actuals to move the planning start before expecting opening stock to change. A base version was saved and displayed as V0001.

| Area | Direct observation in this pass | Still to test in this continuing audit |
|---|---|---|
| Entry/account | Fresh local account and server-kept company created; deployed account page rendered. | Production signup/recovery; expired sessions; role switching and cross-company journeys. |
| Home/setup | Empty Home gives a network setup link; places, products and supply wizard lead to a valid buying plan. | Manufacturing and distribution setup from scratch; interrupted setup/import recovery. |
| Demand | Added a product/place row and entered 100 units; supply consumes the value. | New-user forecasting, overrides, release and accuracy after actual sales. |
| Supply/buying | INR 10,000 proposal, purchase creation, sent state, receipt and reload verified. | Approvals, short/late/repeated receipts and multi-currency purchase documents through the UI. |
| Actuals | Stock view and receipt explanation inspected. | Full roll-forward, inventory reconciliation, sales/production/transfer and reversal as one user journey. |
| Money/performance | Revenue INR 25,000 and about INR 15,000 margin displayed; stale performance data shows a warning and recalculation action. | Independent financial reconciliation after mixed postings; KPI ownership and follow-up closure. |
| Products at places/machines | Product policy list opens; no-machine state explains where to add a resource. | MRP 1–4 edits, calendars/shifts, alternative resources and constrained manufacturing journey. |
| Versions | New base saved and visible. | Branch/edit/compare/promote and recovery while other users edit. |
| Network/master data | Navigation to product details verified stored INR 250 after undo while the old setup field incorrectly showed INR 300. | Large-network discovery, import mapping and rejected-record correction. |
| Optional supply tabs/Proof | Earlier 29-workflow browser suite covers these; they were not re-walked manually in this pass. | Beginner discoverability and complete task walkthrough for buffers, capacity plan, levelling, shop floor and Proof. |

## Confirmed findings and repairs

| ID | Reproduction before the change | Result after the change |
|---|---|---|
| BH055 | Setup product price 250 → 300 → Undo: field still shows 300, while Master data shows 250. Nine setup inputs use uncontrolled defaults, also affecting group, shelf life, cost, route days and stock rules. | Draft inputs follow saved values on undo/redo and other dataset updates. Invalid inline edits report an error and restore the saved value. |
| BH056 | Add a product with price -10 and shelf life 1.5: product is created without a price and with shelf life 2, silently changing the user's inputs. | Creation reports field-specific validation and creates nothing until corrected. Shelf life requires a positive whole number; optional prices accept nonnegative values. |
| BH057 | Add a product with explicit selling price 0: its resulting selling-price field is blank. Inline price/cost 0 also becomes an absent override. | Explicit zero survives creation and inline edits; blank still means absent. Master data confirms both price and standard cost remain 0. |

Four persistent browser regressions cover product undo/redo, creation validation, saved zero values, inline invalid values, route dates and stock edits. All four passed locally; TypeScript checking and the production Vite build passed. The Windows test server needed manual termination during Playwright shutdown; the recorded test run then exited successfully. This shutdown delay is test infrastructure evidence, not a measured application latency.

### Deployment issue still open

`https://hasen1506.github.io/Claude-versioned/` returned GitHub's "There isn't a GitHub Pages site here" 404. The configured API/container host, `https://claude-versioned.onrender.com/`, opened SCP. The Pages workflow [run 36734734286](https://github.com/Hasen1506/Claude-versioned/actions/runs/36734734286) failed at `actions/configure-pages@v5` before building: its log reports that the Pages site was not found and asks for Pages to be enabled with GitHub Actions as its source. This is a confirmed repository deployment configuration gap, not a solver defect.

Choose and document the canonical entry URL. If Pages is retained, enable its GitHub Actions publishing configuration and verify the frontend origin, API access, authentication and deep links together. A successful merge is not evidence that either public host has deployed the new revision. No production account or host configuration was changed in this pass.

## Benchmark: capability references, not a ranking

These are current official vendor descriptions inspected on 30 September 2026. Competitor software was not installed or performance-tested, so this comparison cannot establish numerical accuracy, relative speed, total cost or implementation effort.

| Reference | Relevant documented capability | What to prove or add in SCP |
|---|---|---|
| [SAP IBP](https://www.sap.com/uk/products/scm/integrated-business-planning/features.html) | Integrated demand/supply/finance planning, scenario comparison, multistage inventory, constrained supply planning, contextual exceptions and integrations. | Demonstrate one reconciled decision flow across these areas; add deliberate review/approval steps, not just separate calculation screens. |
| [Kinaxis Maestro](https://www.kinaxis.com/en/solutions/platform) | Continuous synchronization of data, plans and decisions; governed enterprise workflows and connected operational actions. | Stale indicators and reference-based saves are useful foundations. Measure recomputation and concurrent edits, and supply an integration/recovery contract before claiming comparable concurrency. |
| [Odoo 19 replenishment](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment.html), [manufacturing](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing.html) | Forecast-based MPS recommendations, sales-order-linked make-to-order replenishment, manufacturing execution, work centres and shop-floor operations. | Keep planning connected to real purchase/production/sales records. Prioritize reliable ERP import/export and reconciliation over attempting to recreate an entire ERP. |
| [frePPLe editions](https://frepple.com/editions/), [ERP integration](https://frepple.com/docs/current/erp-integration/index.html) | Open-source finite material/capacity planning, forecasts, scenarios, CSV/Excel/API exchange and ERP connectors. | Open source, what-ifs and finite planning alone are not unique. Prove a simpler first useful plan and clearer explanation of why an order is late and what to do about it. |

## Proposed market and differentiation

Working hypothesis: small and mid-sized discrete manufacturers with a small network of plants/warehouses, repeated products, shared resources and planning spread across spreadsheets plus an existing ERP. The buyer is an operations manager; daily users are planners and buyers. This is inferred from the app's workflows and examples, not validated customer research. A specific SKU count, price or cost advantage would require measured pilots.

Proposed promise: "See which orders will be late, explain the constraint, compare a practical change, and carry the chosen plan into purchasing and production." Existing pegging, readable setup, plan versions and purchase/actuals workflows support this direction. Their usefulness and distinctiveness still need user testing against the four references above.

Early pilot acceptance: a planner brings their own anonymized data, reaches the first reconciled plan, investigates a known late order, compares two remedies and exports agreed actions back to their operating system. Measure assistance needed, time to first useful plan, missed/confusing actions and quantity/date/money reconciliation. Compare against their existing process rather than inventing a vendor league table.

## Ordered next work

1. Finish public entry and access verification, including the Pages gap and deployed persistence/revision. Demonstrate account recovery and owner/planner/viewer journeys on an isolated instance.
2. Walk a manufactured product through forecast, BOM/routing, resource calendar, constrained supply, promise, purchase, production confirmation, shipment, weekly roll and financial/KPI reconciliation. Keep an independently calculated fixture beside the journey.
3. Test every optional tab and the scenario branch/compare/promote flow; repeat with missing data, fractional units, partial receipts and interrupted/concurrent saves.
4. Run keyboard and narrow-screen tasks. Record actual missed actions and blocked flows; prioritize observed friction over adding more screens.
5. Build one reliable ERP data exchange with record identities, validation preview, repeatable imports, run status and export reconciliation. Select the ERP from pilot needs.
6. Measure realistic workloads and concurrent users against declared latency/memory budgets; verify backup restore on deployment. Then run pilots and revise the market hypothesis using observed adoption and outcomes.

The goal remains open until these acceptance gates have evidence. Passing the existing suite or finding three more defects does not make the audit exhaustive.
