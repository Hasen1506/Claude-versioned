# Closing the gaps to enterprise planning tools

Written 10 October 2026, from the section-by-section benchmark against SAP S/4HANA with IBP, Kinaxis Maestro and o9
(and, below them, Netstock, Prediko, Odoo and frePPLe). Each phase is one pull request, built, used in the app the
guide's way (input → processing → output), logged in USABILITY_LOG and merged before the next starts. Items found
along the way go to IDEAS.md, not into the running phase.

Order: the live service first (nothing else matters if it is not safe to run), then the planning defects against the
S/4 guide, then what customers buy (connectors), then depth.

## Phase 1: Running it (production hardening)
Done: 1.1 (one connection per process, made again when dropped, under a lock the database holds for every process;
no pool was needed), 1.2, 1.5, 1.6 (USABILITY_LOG N167–N173), 1.3 and 1.4 (N174–N179). Phase 1 is complete.

| # | Gap | Build |
|---|---|---|
| 1.1 | One server process only: saves are checked under a lock inside the process | Save as a compare-and-swap in the database (`UPDATE … WHERE revision = ?`), one connection per request from a pool, idempotent schema setup; `--workers N` on PostgreSQL proven by a test with two processes saving at once |
| 1.2 | No monitoring | Request id and JSON logs, `/api/metrics` (requests, latency, plan runs, queue), an optional error-reporting DSN, the build commit in `/api/health` |
| 1.3 | No two-factor sign-in | TOTP with recovery codes, required per company by its owner; re-authentication for e-mail and password changes |
| 1.4 | No export or deletion of an account | Download everything an account holds; delete an account (companies it alone owns are handed over or deleted, said first) |
| 1.5 | Open settings on a live host | `SCP_ENV=production` refuses to start with open signup and no sign-in unless told so in a setting; the Render settings themselves are the owner's to change (DEPLOY.md lists them) |
| 1.6 | Backup restore never rehearsed on PostgreSQL | `scp.admin` dump and restore for PostgreSQL, and a test that restores into an empty database and opens every company |

## Phase 2: Planning defects against the S/4 guide
Done: 2.1 (USABILITY_LOG N180–N181), 2.2 (N182), 2.3 (N183–N185), 2.4 (N186–N187), 2.5 (N188–N190),
2.6 (N191–N194), 2.7 (N195–N199). Phase 2 is complete.

| # | Gap (guide §) | Build |
|---|---|---|
| 2.1 | A late firm order gets a duplicate requisition (§8.1) | Rescheduling horizon per product / MRP group: reschedule in first, new supply only beyond it; tolerance as a setting |
| 2.2 | Promises a day early where picking takes a day (§6.2) | Pick/pack and loading time at the shipping place, transport-planning time on the lane; material-availability and goods-issue dates on the promise |
| 2.3 | Only firming type 1 (§8.5); fences and GR time in calendar days | Firming types 2–4; fences and GR time in working days (a migration note for saved data) |
| 2.4 | DDMRP advises but does not plan (§8.7) | MRP type `ddmrp`: the buffer drives planned orders; red and yellow buffers in the inbox |
| 2.5 | Make-to-order supply can be taken by another order (§16.2, §9.2) | Sales-order stock and fixed pegging: a firm receipt assigned to one order is planned and issued only to it |
| 2.6 | Delivery does not re-check stock; imported lines re-priced; late open lines invisible in OTIF (§13, §15, §18.2) | Availability check at delivery creation, price frozen at goods issue, open-late count and value in the OTIF note |
| 2.7 | Allocation is one level; kits confirmed line by line; only EOQ beside fixed lots (§7.2, §7.4, §8.3) | Allocation hierarchy with carry-forward, single delivery for a whole order, part-period balancing / least unit cost / Groff |

## Phase 3: Connectors
Done: 3.1 (N200–N206), 3.2 (N207–N213; godown and warehouse stock and goods movements open), 3.3 (N214–N221; Odoo's lots and a partner both customer and vendor open).

| # | Gap | Build |
|---|---|---|
| 3.1 | No packaged connectors (Netstock lists 30+) | A connector framework on top of the existing keys and imports: mapping, dry run, schedule, message log |
| 3.2 | Indian SMEs live in Tally and Zoho | Tally Prime (XML over its HTTP port: masters, stock, vouchers) and Zoho Inventory (REST: items, stock, sales and purchase orders) |
| 3.3 | Online sellers and ERPs | Shopify (orders, stock, locations) and Odoo (JSON-RPC: products, BOMs, stock, orders); outbound purchase and production orders to each |

## Phase 4: Demand and S&OP depth
Done: 4.1 (N222–N229; budgets by customer or region, and reusing the page's solve at sign-off, open); 4.2 (N230–N236;
value add at several lags side by side, and trimming old kept forecasts, open); 4.3 (N237–N244; strategy 70 in the S&OP
plan, and variants in the example, open); 4.4 (N245–N254; keeping a variant's and other products' high end first, and
the spread on transfers and production, open). Phase 4 is done.

| # | Gap (guide §) | Build |
|---|---|---|
| 4.1 | No consensus cycle (§4) | A monthly S&OP cycle: data → demand review → supply review → pre-S&OP → executive, each with an owner, sign-off and a frozen snapshot; volume and revenue against budget |
| 4.2 | No forecast value add | Accuracy and bias of the statistical forecast against each override layer, per planner and product group |
| 4.3 | Variants forecast one by one (§5, strategies 60/63, 70) | Planning material: one base forecast consumed by its variants with a factor; a sub-assembly forecast consumed by dependent demand; a strategy advisor from lead times |
| 4.4 | One demand number (no spread) | P90 demand and promise against it; measured supplier lead-time deviation fed into safety stock |

## Phase 5: Speed and an assistant
Done: 5.1 (N255–N261; capacity-constrained plans and co-products planned whole, open); 5.2 (N262–N270; fixes offered
before they are tried and time words, open; a supplier price change done in 5.3); 5.3 (N271–N279, with N267; a raised
safety stock phased in over weeks, the engine's money format and sizes planned from the kept work, open).

| # | Gap | Build |
|---|---|---|
| 5.1 | 66–78 s supply plan at 5,000 × 20 | Incremental planning: re-plan only the parts of the network a change reaches (by low-level code and component), cache the rest; target under 15 s for a single change |
| 5.2 | No AI assistant (every leader shipped agents in 2026) | "Ask the plan": a question answered from the plan's own records (why late, what if, who owns), each answer citing the items; proposes one-click fixes that a person keeps |
| 5.3 | What-if smaller than the leaders' | Sweep one chip (cost against service), stored versions as columns, money at risk over time |

## Phase 6: Warehouse and transport (EWM and TM, small)
Done: 6.1 (N281–N288; counts by bin, staging for production, a camera reader for every phone and replenishment of
picking bins, open).
Done: 6.2 (N292–N297; postings to accounts with 7.4, a price change by hand and split valuation, open).
Done: 6.3 (N299–N304; multi-stop tours, freight into the books and cost to serve, freight bills in payables and
tendering by message, open). Phase 6 done.

| # | Gap (guide §) | Build |
|---|---|---|
| 6.1 | No bins (§12.2–12.3) | Storage types and bins, put-away rules, pick lists by bin and waves, a phone page that reads a barcode |
| 6.2 | One planned price; no cycle counts (§12.4) | Moving-average valuation with price differences from invoices; ABC cycle counting |
| 6.3 | No transport planning (§14) | Carriers, freight orders that group deliveries, load building by weight and volume, freight cost and its settlement |

## Phase 7: Wider supply and money
Done: 7.1 (N305–N310; the job charge goes into work in progress with 7.4; the GST portal file and e-way bill, stock at job
workers in planning and third-party lines on sales orders, open).
Done: 7.2 (N311–N315; the link by e-mail, Peppol transport and supplier invoices on the portal, open).
Done: 7.3 (N316–N320; a currency per company and planning per company, open; settlement between them done in 7.4).
Done: 7.4 (N321–N327; sales invoices per company of the group, customs and forwarders' bills, reversing vouchers for
cancellations and year-end closing, open).

| # | Gap (guide §) | Build |
|---|---|---|
| 7.1 | No drop-ship; job work only adds days (§16.3, §10.1) | Third-party orders; job-work subcontracting with parts sent out as stock at the supplier (GST job-work challan) |
| 7.2 | Suppliers confirm by mail only | Supplier portal: a signed link to confirm or change a PO line; order and dispatch messages in a standard format |
| 7.3 | One company per network (§17.5) | Several companies in one network with inter-company orders and transfer prices |
| 7.4 | No accounting shadow (§15.1) | A double-entry journal from movements and invoices (stock, GR/IR, receivables, payables, COGS), exported to Tally |

Done after phase 7: N198 (an order the data stops names the problem and its fix).

## Phase 8: Conformance (checking the app against the books, not against itself)
Phases 1–7 closed the gaps a benchmark written here found, and each was checked against hand-worked numbers. That
proves the sums, not that the right things are there or can be found: inventory policy, for one, is in the engine (five
safety-stock methods, multi-echelon, DDMRP, reorder point, min-max, ABC-XYZ service levels) but spread over "Buffers"
(an optional tab) and "Products at places", with no page that says *inventory policy*. Phase 8 checks every section
against outside references, then fixes what the check finds.

In progress: 8.1 (docs/CONFORMANCE.md; section 1, inventory policy, written: 25 concepts: 12 there (two of them on a page nobody would look for), 4 buried, 2 partial, 7 missing).
Done: 8.2, first part (N329–N335): *Supply → Inventory policy*, a policy given to a class, the suggested reorder point and the service achieved; inventory policy now 21 of 25 there. Then periodic review on a calendar and a class's rule in one step (N336–N339):
22 of 25; then safety stock for demand that varies widely, by a gamma or Poisson spread (N340): 23 of 25, the other
two in IDEAS.md. Next: 8.3, the other sections.

In progress: 8.3, demand planning first (CONFORMANCE §2: 17 of 25 there at the audit). Done: stock-outs and lost sales
read as demand (N341), 18 of 25; a tracking signal per series (N342), 19 of 25; the forecast by product family (N343), 20 of
25. The other five (accuracy by lag, working-day effects, price as a driver, customer forecasts, demand sensing) go to
IDEAS.md. Then supply planning (CONFORMANCE §3: 20 of 25 there at the audit): the demand time fence (N344), 21 of 25;
kanban and MRP areas to IDEAS.md. Then buying (§4: 16 of 22 at the audit): spend and sourcing (N345), 18 of 22.
Then selling (§5: 20 of 26 at the audit): product substitution in promising (N346), 21 of 26; customer segments,
quotation conversion, rebates, freight on customer orders and customer consignment to IDEAS.md.
Then the warehouse (§6: 14 of 21 at the audit): picking bins refilled from the reserve (N347), 15 of 21; slotting,
handling units, cross-docking, space in the plan, warehouse measures and workload to IDEAS.md.
Then transport (§7: 12 of 19 at the audit): collections planned as freight from the supplier (N348), 13 of 19;
the landed cost by incoterm, multi-stop routes, carrier performance, billed freight in cost to serve, docks and
tracking to IDEAS.md.
Then money (§8: 16 of 20 at the audit): the cash the plan needs, week by week (N349), 17 of 20; overhead rates,
write-downs and currency revaluation to IDEAS.md. 8.3 is done: every section has its audit, its fixes and the rest
in IDEAS.md.

Done: 8.4 (N350–N357), one working day at Kaveri walked by a planner, a buyer, a storekeeper, an accountant and the
owner from the screens only (`e2e/persona-day.spec.ts`): firming moved to *Supply → Firm orders*, the S&OP cycle to
its own rail item, *Work waiting, by job* on Home and *To collect and pay* on Money, *Goods in & out* by place and day
for the storekeeper; firming and opening Home calculate everything again. Next: 8.5, a practitioner's review.

Done as a desk review: 8.5 (N358–N366). A desk review first, the matrix and the day read as a planner, a scheduler and an S&OP
lead would read them; a review by someone who plans for a living is still owed. It found the matrix had skipped
scheduling, the S&OP process and the measures (now CONFORMANCE §9–§11), that *Inventory policy* compared a cycle or
fill-rate target with orders on time (now measured as the target is set), and that the measures had no unit fill rate
or order cycle time, and the shop floor no critical ratio (all three added). Then the S&OP horizon in months, past the
weekly plan's (N360). Then the plan's money in the cycle (N364), and a second working day for the demand planner,
the planner's reschedule messages, the order desk and the scheduler (N363, N366; `e2e/persona-day-2.spec.ts`), with
Home's *Work waiting* gaining their jobs. Still owed: the same reading by someone who plans for a living; the matrix,
the two days and these findings are the pack to hand them.

| # | What | How |
|---|---|---|
| 8.1 | A conformance matrix (docs/CONFORMANCE.md) | Every concept from the references (S/4 guide sections; ASCM CPIM body of knowledge; Silver, Pyke & Thomas for inventory; Graves–Willems; the DDMRP standard; IBP S&OP), each with where it lives in the engine, which page shows it under which name, the test and its outside oracle; status *there*, *buried*, *partial*, *missing* |
| 8.2 | Inventory policy, the first section | One policy per product at a place in one table: segment (ABC-XYZ), review (continuous / periodic R), method and service target, safety stock, reorder point s, order-up-to S or lot Q, achieved service from actuals; a policy assigned to a whole segment; textbook worked examples as oracles |
| 8.3 | Every other section the same way | Demand, supply/MRP, capacity and scheduling, promising, buying, selling, warehouse, transport, money; each section's findings fixed in the same item |
| 8.4 | Jobs, not pages | One working day each for a planner, a buyer, a storekeeper, an accountant and an owner, done from the screens only; where a job needs a page nobody would find, the page moves |
| 8.5 | A practitioner's review | The matrix and the walkthroughs read by someone who plans for a living; their findings logged like the others |

## Pause points
The work stops after each phase (and inside a phase after every two or three items) with everything committed,
pushed and the PR updated, so the conversation can be compacted without losing anything.
