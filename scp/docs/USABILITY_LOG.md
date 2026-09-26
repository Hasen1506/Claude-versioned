# Usability log

What a planner hits when using the app for real, found by building companies from an empty dataset through the
screens (not by opening the prepared examples). Each entry: what happened, why it matters, and what was done.
Open items name the roadmap phase that addresses them.

Phases: **A** get your own company in · **B** master-data depth · **C** capacity and material together ·
**D** PP/DS-class scheduling · **E** procure-to-pay. Proposed after the second reality check: **F** execution you
can trust · **G** order to cash · **H** defaults and onboarding · **I** a real place to keep the company · **J** polish.

## Found in the reality check (before Phase A)

| # | Finding | Severity | Status |
|---|---|---|---|
| R1 | A new transport lane starts with no mode; the engine rejected it and the whole dataset became unreadable ("List should have at least 1 item…"). New demand rows had the same trap. | Critical | **Fixed (A).** Unfinished records are set aside with a plain reason and the rest keeps planning (`engine/scp/validate/lenient.py`); new lanes start with a truck mode and single-choice references are pre-filled. |
| R2 | No way to build a network: 22 unordered tables, six of them needed in the right order for one product. | Critical | **Fixed (A).** *Set up*: places and routes (click two places on the map to connect them), products, and a product wizard (made here from these parts on this line / bought from / shipped from, plus stock and ordering rules). |
| R3 | No file format for demand (or anything): only forms or one whole-company JSON. | Critical | **Fixed (A).** Every table uploads from CSV, Excel (.xlsx) or pasted cells, with a template, a preview of what is added, updated or skipped and why, names accepted for ids, and one-click creation of missing products. BOM lines and routing steps upload in long format. |
| R4 | The Demand page ignored entered demand ("customers will order 0"). | Critical | **Fixed (A).** *Demand plan* is the first tab: product × place × week, editable in place, with upload; the forecast is one way to fill it. |
| R5 | The data check said "Ready to plan" with no demand or sources; it spoke in codes (`LOCATION_PRODUCT_DEFAULTED`). | Critical | **Fixed (A).** A "What's missing" checklist in setup order, each line with its button (`engine/scp/validate/setup.py`); rules shown by plain title, records by name. |
| R6 | Shop floor said every run finishes on time while the supply plan had the parts arriving late. | Critical | **Fixed (C).** Each step starts only once the parts it uses are there, along the pegging: from stock, an incoming order, or the order on the same schedule that makes them (and when that one finishes). Orders show what they waited for and for how long. |
| R7 | Home said "the forecast is 100% accurate" with no history, and "All 1 measures". | Serious | **Fixed (A).** |
| R8 | A raw engine message: "STOCKOUT (1) … worst 1,000.0", without product or place. | Serious | **Fixed (A).** Translated, with product and place; no exception code can reach the page untranslated. |
| R9 | Master-data search count wrapped onto three lines. | Minor | **Fixed (A).** |
| R10 | "Plan everything" lit up when there was nothing to plan. | Minor | **Fixed (A).** It stays plain until the checklist has nothing left to do. |

## Found while building Phase A

| # | Finding | Severity | Status |
|---|---|---|---|
| N1 | Saving a version with an unfinished record would be refused by the version store with a schema error. | Serious | **Fixed (A).** Saving is disabled with a plain reason and a link to the records to finish. |
| N2 | The Capacity plan said "the network can supply all of demand" while the supply plan had 43% on time. The monthly model cannot see lead times shorter than a month. | Serious | **Addressed (C).** The supply plan itself can now plan within capacity, day by day (*Levelling*); the monthly capacity plan stays a rate model and its answer still says "month by month". |
| N3 | The forecast tab showed an empty dashboard ("0 series", "0 units") and an active "Use this forecast" button when there was no history. | Serious | **Fixed (A).** It explains what a forecast needs and points to the demand plan. |
| N4 | Readiness hints used planner-internal words (location-product, node, horizon, L4L). | Serious | **Fixed (A).** Rewritten in plain words; the link opens the product's setup page. |
| N5 | The network map led with ids (SUPPLIER-A) instead of names. | Minor | **Fixed (A).** |
| N6 | Data-check problems for a product at a place that has no planning record linked to a record that does not exist. | Minor | **Fixed (A).** Links to that product's setup page, where the record is made. |
| N7 | A company with no opening stock gets 11 purchase orders "should already have started" on day one. True, but alarming for a first plan. | Minor | **Fixed (A).** Home says the plan starts every place from zero and links to entering today's stock. |
| N8 | Forecast records that cover a month are shown spread over its weeks by calendar days, while the engine spreads them over working days. Totals agree; single weeks can differ slightly. | Minor | Open (documented in the grid's code). |
| N10 | Opening *Set up* before the first data check had answered froze the page (a selector returned a new empty list on every render). Found only at phone width, where the page opened first. | Critical | **Fixed (A).** |
| N11 | At phone width the places and routes tables ran past their panel. | Minor | **Fixed (A).** |
| N9 | Lanes created by the wizard carry all products. Right for most companies, but a lane for one product needs Master data. | Minor | **Fixed (B).** The wizard asks whether a new route is for every product or only this one. |

## Found while building Phase B

| # | Finding | Severity | Status |
|---|---|---|---|
| N12 | Editing how a product is made in the setup wizard rebuilt its parts and steps from the few fields the form shows, silently dropping queue times, labour, the step a part is used at, and anything set in Master data. Present since Phase A. | Serious | **Fixed (B).** Each row keeps the record it came from; only what the form shows is changed. Checked in the browser: queue time, alternative machines and a change number survive an unchanged save. |
| N13 | Forms showed stored codes in dropdowns (“any”, “L4L”, “MTS_CONSUME”) and field names like “Float before workdays”. | Minor | **Fixed (B).** Plain choices with the SAP code in brackets where a planner knows it (“Make to stock, orders consume the forecast (40)”). |
| N14 | MRP scheduled make orders with a typical day's hours even across a week the line is shut, so the plan and the capacity check disagreed about the same week. | Serious | **Fixed (B).** Lead times walk the actual days when a machine has named shifts or capacity changes; the shutdown test pins it. |
| N15 | Alternative machines are used by the shop floor schedule only; MRP's load and the capacity plan still put all of a step's hours on its main machine. | Minor | **Fixed (C).** Planning within capacity puts a step on its alternative machine when its own is full; the choice is kept when the order is firmed or dated by the schedule, and the shop floor starts from it. (Phase D: choosing machines by cost in the optimiser.) |
| N16 | A fixed-quantity part (a mould, a fixed charge) is exact per order in MRP, promising and the schedule, but the monthly capacity plan and unit costs spread it over a typical run (the minimum lot or the base quantity). | Minor | Stated in the code. Still open after C: the supply plan and levelling are exact per order; only the monthly capacity plan and unit costs spread it. |
| N17 | The “plan needs” column on Machines & shifts is filled only when the plan works in weeks or days; with monthly buckets it shows a dash. | Minor | **Fixed (C).** The plan reports each machine's load by day, and the weekly column sums it whatever bucket the plan uses. |

## Found while building Phase C

| # | Finding | Severity | Status |
|---|---|---|---|
| N18 | A released production order did not load its machines in the supply plan: only planned orders did. Firming every order emptied the capacity plan, and capable-to-promise could promise machine time a released order already had. | Serious | **Fixed (C).** Released orders load their machines from their start date (else backward from their due date), before any planned order; a test checks that firming everything keeps every machine's total load. |
| N19 | The weekly capacity check hid overloaded days: on the kitchenware example no week is over 100 %, yet Assembly line 1 is asked for 321 % of a day on 5 Nov and five machines are over on 56 days. | Serious | **Fixed (C).** *Levelling* shows each machine day by day with the orders on any day, and planning within capacity takes those days to none. The exception list still checks by bucket; the daily view is where overloads show. |
| N20 | An order levelled onto an alternative machine lost that machine when it was firmed: the production order had nowhere to keep it, so its load fell back on the full machine. | Serious | **Fixed (C).** Production orders carry the steps that run on an alternative machine; firming, schedule dates, MRP load and the shop floor all keep it. |
| N21 | With levelling on and the schedule's dates applied, the page said the orders still over capacity "could fit nowhere". They were released orders, which levelling never moves. | Minor | **Fixed (C).** The answer says levelling leaves released orders where they are, and a day's order list marks them. |
| N22 | Using the schedule's dates could have made MRP add a duplicate order in front of every late one, because a new order planned at unlimited capacity always looks faster. | Serious | **Prevented (C).** Orders dated by the schedule are counted where they are needed and reported (*Scheduled to finish late*); a test shows an ordinary late production order gets a new order in front of it and a schedule-dated one does not. |
| N23 | Levelling fills from the need date backwards and can pull an order a long way forward (18 days for a motor assembly on the example), building stock early, where a planner might rather use overtime or accept a day late. | Minor | **Fixed (D).** Levelling can try finishing later before building ahead, and a company setting limits how many days ahead it may build; past the limit an order goes later instead. Both are on the Levelling panel, and tests cover both directions and the limit. |
| N24 | Capable-to-promise checks free capacity per plan bucket, so it can confirm a date on a machine that is free that week but not on the days it needs. | Minor | **Fixed (D).** CTP books each step in the free hours of the days it runs, step after step, on its own machine or the alternative that finishes it first. A test has a machine full Monday to Thursday with 17 h free that week: the promise moves two days, and an alternative machine brings it back. |

## Found while building Phase D

| # | Finding | Severity | Status |
|---|---|---|---|
| N25 | The optimiser's solver (OR-Tools) and the S&OP and placement solver (HiGHS) each ship their own copy of the HiGHS library, in different versions, and whichever loads first into a process breaks the other. On the server, running the optimiser once would have broken S&OP until a restart, or the other way round. | Serious | **Fixed (D).** The optimiser's model runs in a worker process of its own, fed plain numbers; the server never loads OR-Tools. Found because the full test suite failed only when the S&OP tests ran first. |
| N26 | Any edit marked every result out of date: changing a shop-floor profile or a changeover time asked for the demand plan, supply plan, promises and money to be recalculated, though none of them reads those settings. | Minor | **Fixed (D).** Staleness follows the part of the data that changed. The shop floor's settings and changeover matrix leave the other results fresh; the day start hour, which the plan and promising read too, still marks them. |
| N27 | With the optimiser the same data can give a different (equally good) schedule each run, because the solver searches in parallel. *Use these dates in the plan* scheduled again before writing, so the dates written could differ from the ones on screen. | Serious | **Fixed (D).** The page sends back the schedule it shows: every machine's sequence and each order's not-before time. A test checks this reproduces the shown schedule exactly. |
| N28 | After a hand change to the sequence the banner said to use “Reset to optimised”, a button that does not exist (it is *Undo my changes to the order*). | Minor | **Fixed (D).** The banner names the real button and says what was moved and how late orders, changeovers and the score changed. |
| N29 | *Shortest job first* and *least slack first*, taken literally, left machines idle waiting for an order whose parts or earlier step were not ready, and made 19 to 21 of 24 orders late on the example. | Serious | **Fixed (D).** Both rules dispatch without delay: a machine that comes free takes the most urgent step that can start then. On the example they now leave 10 late. |
| N30 | The optimiser's first model averaged each step's time and never beat the local search on the example (it proposed schedules 4× worse once timed on the shifts). | Serious | **Fixed (D).** The model takes each step's elapsed time from the starting schedule, sequences single machines with changeovers and parallel units as a pool, and is run in rounds from the best schedule so far. On the example it wins: 1669 against 1728 for the local search. It still only proposes; the shift-calendar timing decides and keeps it only if better. |
| N31 | The kitchenware example has no alternative machines, so dragging a step onto another machine and the optimiser's choice of machine cannot be seen on it. | Minor | Open. Covered by engine tests; an example with alternative machines would show it. |
| N32 | *Campaigns by setup group* gains little on the example: its orders are spread over weeks, so few same-group orders are ready at once. | By design | The comparison on *Methods & profiles* shows this for each company; campaigns win where many orders of a group are ready together. |
| N33 | A phone cannot drag a bar on the board: a drag there scrolls the board. | By design | A tap selects the order; its panel moves a step earlier or later, or onto another machine that can run it. |

## Found while building Phase E

| # | Finding | Severity | Status |
|---|---|---|---|
| N34 | Copying a dataset (firming, rolling forward, applying a schedule, any engine write) kept the copy's lookup tables from the original, so code that changed a list and then looked a record up by id in the copy could find the old record, or none. Found when a purchase order approved in the copy still read as unapproved. Present since the first engine writes. | Serious | **Fixed (E).** A dataset copy drops its lookup tables and builds them again from its own data. |
| N35 | The supply plan chose a purchasing source by priority and quota only: there was no way to stop buying from a supplier, to name the one source planning must use, or to pay less for a larger order. | Serious | **Fixed (E).** A purchasing block on the supplier, fixed and blocked flags on the source (the source list), and price scales; planning follows S/4's order: quota, then the fixed source, then priority. A node whose only sources are blocked is reported with their names. |
| N36 | A firm purchase was a receipt with a number and nothing else: no supplier document, approval, send date or confirmation, so the plan could only assume the supplier delivers everything on the date asked. | Serious | **Fixed (E).** *Buying* turns requisitions into purchase orders and runs them through approval, sending, the supplier's confirmation and goods receipt; the plan expects a confirmed line on its confirmed date and counts no more than confirmed. Firming a purchase in *Actuals* now creates its order document too. |
| N37 | An open purchase order imported without a price (the example's heater order) showed as worth nothing in the order list. | Minor | **Fixed (E).** A line without a price is valued at its source's price for that quantity. |
| N38 | A goods receipt posted today shows on the purchase order at once, but stock only changes when the plan moves past that day. | By design | Stock is derived from movements before the planning start, so today's plan already expects the order; the receipt's message says where stock updates (*Actuals → Start a new week*). |
| N39 | Refusals (receiving more than the supplier's tolerance) come back as an HTTP 409 that the browser also logs as a failed request. | Minor | The page shows the reason; the end-to-end tests accept a 409 as they already did a 422. |
| N40 | A supplier's order currency is recorded but not applied: a purchase order is priced in its source's currency. | Minor | Open. Keep a source's price in the currency the supplier invoices in. |

## Found in the second reality check (after Phase E)

A new company built from an empty start through the screens only: a paint maker with one plant, a distribution
centre, a depot, three suppliers (one importing), two customer channels, three finished goods, one bulk
intermediate, four raw materials and three packs. Demand came in as a monthly spreadsheet, stock as an upload. Then
one full cycle: plan everything, create and send purchase orders, record a late confirmation, firm the next two
weeks, post the week's production, transfers and sales, move the plan forward a week, re-plan, and read every page,
on a desktop and at phone width. Phases F–J are the proposal at the end of this section.

| # | Finding | Severity | Status |
|---|---|---|---|
| Q1 | Stock typed in during setup (the product wizard's *On hand today*, or an upload of stock) never becomes an opening movement. As soon as a place gets its first movement, its stock is recomputed from the journal alone: after one transfer arrived, the Mumbai warehouse went from 900 tins to 25.9, and after the week's sales every stocked place read negative. | Critical | Open (**F**). Setup stock should post an opening balance on the planning start (go-live), so both paths agree. |
| Q2 | *Receive* on a stock transfer posts only its arrival: nothing takes the goods out of the sending place, and there is no *Ship* button for a transfer. The same tins then sit in the plant and the warehouse at once. | Critical | Open (**F**). One action posts both sides (or dispatch now, arrival later, in transit between). |
| Q3 | *Receive* on a production order adds the product but never issues its parts: resin, pigment and tins stay at their opening stock however much is made, unless each issue is posted by hand in the journal. | Critical | Open (**F**). Confirming a production order issues its parts (backflush, S/4 style), with the option to post actual usage instead. |
| Q4 | The goods-movement upload refuses a file without an *id* column, which no dispatch register or stock report has. | Critical | Open (**F**). Number new movements automatically, as the journal form does. |
| Q5 | There is no way to take a customer order. *Check a new order* is a simulation ("Nothing is saved"); an order has to be typed into *Master data → Demand* with its kind set to sales order. | Critical | Open (**G**). Accept a checked order as a sales order; an order list to change, cancel and deliver. |
| Q6 | Products counted in each are planned in fractions: production orders for 25.9 tins, a transfer of 2.22 pails, 203.23 pails a week in the demand grid. | Serious | Open (**H**). Whole units for products counted in each (or any unit marked as whole), everywhere quantities are planned. |
| Q7 | The default lot size is exactly what's needed, day by day: 2,032 planned orders over 26 weeks for four products (573 production runs, 1,184 shipments), four batches of base in four days, 61 orders to start in one week. | Serious | Open (**H**). A sensible default (a week's need per order) and a setup question about it. |
| Q8 | A process plant cannot be described: a batch of paint is mixed in fixed batches (e.g. 2,000 L in 3 hours whatever the fill), but a step only takes minutes per unit and setup hours. | Serious | Open (**H**). Batch size and time per batch on a step, and batch multiples on the order. |
| Q9 | Two roads to a purchase order disagree. *Buying* groups lines per supplier and applies approval and minimum order value; *Actuals → firm zone* firms each purchase as its own order and skips both. Firming "everything" there also re-ordered 200 kg of pigment already on order (the confirmed-late line), without saying so. | Serious | Open (**F**). The firm zone hands purchases to Buying's requisitions (or groups them the same way) and marks lines that duplicate an open order. |
| Q10 | *Capacity plan* reports revenue of ₹4.01 Cr when no selling price is set (it values each sale at its cost), while *Money* says revenue ₹0 and a margin of −₹4.19 Cr. | Serious | Open (**G**). Without prices, show no revenue or margin anywhere; say which products need a price. |
| Q11 | The demand upload does not read the columns a sales spreadsheet has: *Customer* is not taken as the place, *Month* is not taken as the date, and "Oct 2026" is "not a date". A monthly forecast needs an ISO date plus a *period_days* column that nothing mentions. | Serious | Open (**H**). Month values become a month-long forecast bucket; more column names recognised. |
| Q12 | An empty company never asks its name, currency, planning start or working week (the header says "My Company", Monday to Saturday is imposed), and setup never asks for selling prices or costs. | Serious | Open (**H**). A first step for the company itself, and prices and costs in the product setup. |
| Q13 | *Enter stock on hand* opens an empty planning-policy table (the side list shows a warning count of 15 next to it). Stock can only be typed once a policy row exists for each product and place. | Serious | Open (**F**). A stock grid of every product at every place it is kept, which posts the opening balance (Q1). |
| Q14 | The working company exists only in this browser's local storage: no sign-in, nothing shared with a colleague, gone if site data is cleared. A real company with a year of history will outgrow the browser's roughly 5 MB, and a failed save is swallowed without a word. | Serious | Open (**I**). Companies stored on the server, with sign-in, autosave and an audit trail. |
| Q15 | A late posting goes nowhere visible. Sales posted after the week was rolled are dated before the new start, so forecast accuracy still reads "0 units sold vs 2,732 forecast" and nothing asks for a re-roll. Home kept saying 98% on time while four places disagreed with the journal; the data check calls that a warning. | Serious | Open (**F**). Offer the re-roll when postings land in a rolled week; Home leads with stock that disagrees with the journal. |
| Q16 | The buy form takes a price only in the company currency, so the importer's USD pigment has to be converted by hand. | Minor | Open (**H**, with N40). |
| Q17 | Raw ids are still on screen: the data check's problem text ("EMULSION-WHITE-20-L at VAPI-PAINT-PLANT is needed…"), the shop-floor board's rows, legend and busiest-resource tile, *Buying*'s "PO-00001 to PIGMENT-IMPORTER", the firm zone's *From* column (truncated source ids), and the new-order drop-downs, which lead with the id. | Minor | Open (**J**). |
| Q18 | An import preview marks every row "added" while a required column is missing and the import button is disabled; the reason is one line above the table. | Minor | Open (**J**). |
| Q19 | *Machines & shifts* at phone width: the detail panel stays beside the list, one word per line. | Minor | Open (**J**). |
| Q20 | *Performance* shows "Days of supply 9.28 d" graded "No data". | Minor | Open (**J**). |
| Q21 | Three pages give three utilisations with no word on why: the supply plan's busiest machine 65%, the capacity plan's peak 15%, the shop floor's 29%. | Minor | Open (**J**). Name the measure on each (day vs month, regular hours vs window). |
| Q22 | Planned-order numbers are handed out again on every plan (PR-00006 was later a different requisition), and firming renames them (MO-00430 became PRD-00008), so the shop-floor board, the firm zone and *Actuals* don't match up. | Minor | Open (**J**). Show "was MO-00430" on firm orders; say planned numbers are temporary. |
| Q23 | *Mark as sent* only records a date: there is no purchase order document to download, print or send. | Minor | Open (**J**). |
| Q24 | A late requisition shows "Order by Mon 28 Sep · late", which is today, not the date it should have been ordered. | Minor | Open (**J**). |
| Q25 | The new-route form keeps the previous route's days in transit. | Minor | Open (**J**). |

What held up: the network builder, product wizard, stock and demand uploads (once the columns matched), the
checklist, plan everything, requisitions to a purchase order with a late confirmation that planning used at once, the
roll-forward report, and every page at phone width except *Machines & shifts* (no page scrolls sideways).

### Proposed next phases

- **F: execution you can trust** (Q1–Q4, Q9, Q13, Q15). Setup stock becomes the opening balance. A production
  order confirms with its parts issued. A transfer ships and arrives, with stock in transit between. Movements
  upload without ids. There is one road to a purchase order. Late postings offer a re-roll. Home leads with stock
  that disagrees with the journal.
- **G: order to cash, first steps** (Q5, Q10). Accept a checked order. A sales-order list to change, cancel and
  deliver from. Customer prices and terms. Revenue and margin appear only where prices exist.
- **H: sensible defaults and a second onboarding pass** (Q6–Q8, Q11, Q12, Q16, N40). The company's own settings
  come first. Whole units. A weekly default lot size. Batch steps. Monthly demand upload. Prices and costs in
  setup. Supplier currency.
- **I: a real place to keep the company** (Q14). Server-side storage, sign-in and roles, autosave, an audit trail.
- **J: polish sweep** (Q17–Q25, N8, N31).

## Gaps against SAP recorded for later phases

- MRP views: MRP controller, procurement type (E/F/X), phantom (special procurement 50) and the scheduling margin
  (float before and after production) are in (**B**). Still missing: MRP groups, other special procurement keys
  (withdrawal from another plant, direct production), discontinuation with a follow-up material, availability check
  groups.
- Work centres: named shifts with breaks and weekdays, capacity changes over time, per-unit availability (**B**, done).
- BOM and routing: date-effective lines (engineering change), fixed quantities, phantoms, co- and by-products with
  cost shares, step scrap, overlap (send-ahead), steps done outside by a supplier and alternative machines (**B**,
  done). Still missing: BOM usage/alternative BOMs separate from production versions, routing alternative sequences,
  change-number history.
- Capacity: material-aware scheduling along the pegging, schedule dates back into supply and promising, a levelling
  view by day and week, and capacity-constrained MRP with alternative machines (**C**, done). Still missing:
  interactive levelling by dragging orders between days, overtime as a levelling choice, capacity-constrained
  planning for suppliers and lanes.
- PP/DS: strategy profiles, a heuristics catalogue (due date, shortest first, least slack, campaigns, backward),
  a local search, a constraint-solver optimiser choosing machines and sequence, a frozen zone and a drag-and-drop
  board (**D**, done). Still missing: overtime and shift changes as optimiser choices, setup matrices by product
  (not only group), multi-resource steps (machine and tool together), pegging-aware re-scheduling of dependent
  orders when one moves.
- MM: supplier purchasing data with a purchasing block, info records with price scales, the source list (fixed
  and blocked), requisitions from MRP, purchase orders with an approval limit, supplier confirmations that planning
  uses, and goods receipts with delivery tolerances (**E**, done). Still missing: invoice verification (three-way
  match) and payment, outline agreements (contracts and scheduling agreements), several confirmation lines per
  order line, quality inspection stock, returns to the supplier, and a release strategy with more than one level.
