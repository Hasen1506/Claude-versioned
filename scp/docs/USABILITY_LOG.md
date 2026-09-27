# Usability log

What a planner hits when using the app for real, found by building companies from an empty dataset through the
screens (not by opening the prepared examples). Each entry: what happened, why it matters, and what was done.
Open items name the roadmap phase that addresses them.

Phases: **A** get your own company in · **B** master-data depth · **C** capacity and material together ·
**D** PP/DS-class scheduling · **E** procure-to-pay · **F** execution you can trust · **H** defaults and onboarding ·
**G** order to cash. Proposed after the second reality check: **I** a real place to keep the company · **J** polish.
After J: **K** third reality check (six weeks, R-findings) · then **L** platform · **O** stock you can trace ·
**P** planning depth · **M** order to cash, complete · **N** procure to pay, complete · **Q** connected.

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
| N8 | Forecast records that cover a month are shown spread over its weeks by calendar days, while the engine spreads them over working days. Totals agree; single weeks can differ slightly. | Minor | **Fixed (J).** The grid spreads a forecast over the working days of its place's calendar, as planning does; totals and single weeks agree. |
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
| N31 | The kitchenware example has no alternative machines, so dragging a step onto another machine and the optimiser's choice of machine cannot be seen on it. | Minor | **Fixed (J).** The bottling example has an old second line as the alternative for its one step, so the board's machine choice and dragging onto another row can be tried. |
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
| N40 | A supplier's order currency is recorded but not applied: a purchase order is priced in its source's currency. | Minor | **Fixed (H).** A source without its own currency is priced in its supplier's order currency, in planning, costing and Buying alike (`Dataset.price_currency`); the data check asks for a rate for either. |

## Found while building Phase F

| # | Finding | Severity | Status |
|---|---|---|---|
| N41 | Every roll-forward wiped the history that came with the data: the 72 forecast-accuracy records and 68 closed orders the Kaveri example starts with were re-read from a journal that has no movements for them, so their actual sales and deliveries became zero (forecast accuracy and supplier and customer OTIF lost their past). Present since the late-posting fix of the first audit; found because the new *Not counted yet* check fired on the untouched example. | Critical | **Fixed (F).** Only weeks a roll closed and orders the journal has movements for are re-read; imported ones are kept as they came (`engine/scp/actuals/roll.py`). Regression test on the example. |
| N42 | *Open orders* counted only postings dated before the planning start, so an order received this week still showed its whole quantity open; a second *Receive* then had nothing to post. | Serious | **Fixed (F).** Open orders count every posting against them, whatever its date. |
| N43 | The posting date on *Open orders* defaulted to the day before the planning start, which made every quick post a late posting for a period already planned from. | Serious | **Fixed (F).** It defaults to the planning start; an earlier date is offered as a late posting to count. |
| N44 | The firm zone preselects everything (110 orders with the default daily lot size) and had no way to clear the selection. | Minor | **Fixed (F).** *Select none* / *Select all*. |
| N45 | Posting messages named places by id and printed six significant digits ("35.6631 still to come", "shipped from MUMBAI-WAREHOUSE"); the firm zone and open orders showed a production version's id as *From*. | Minor | **Fixed (F)** for posting and firming; the roll-forward's warnings and the firm zone's notes name places and products since **J**. |
| N46 | The product wizard's *On hand today* and the planning-policy table still set on-hand directly. At a place that already has movements this makes stock disagree with the journal until it is counted or re-booked (Home now says so at once). | Minor | **Fixed (H)** in the product wizard: at a place with goods movements *On hand today* becomes *Counted today*, which posts a count. The planning-policy table in Master data still edits on-hand directly; Home and the data check flag the difference at once (**J**). |
| N47 | Receiving by quantity only: there is no batch or serial number, no stock in quality inspection, and a transfer's goods in transit are a quantity on the order, not a stock type of their own. | Minor | Open: SAP gap below. |

## Found while building Phase H

| # | Finding | Severity | Status |
|---|---|---|---|
| N48 | A missing exchange rate for a supplier's order currency went unnoticed: the rate check looked only at a source's own currency, and money pages counted the foreign price one to one. | Serious | **Fixed (H)** with N40: the check covers the supplier's currency. |
| N49 | The supply plan's order search matched ids only: "White base" found nothing, "WHITE-BASE-BULK" found the orders. | Minor | **Fixed (H).** It matches product and place names too. |
| N50 | Company settings in Master data had no way to enter exchange rates (a map the generic form skips). | Minor | **Fixed (H).** *Your company* lists every currency a supplier prices in, with its rate. |
| N51 | Planned-order numbers still change on every plan and firm orders still get new numbers (Q22), which the week's-need default makes less noisy but does not fix. | Minor | **Fixed (J)**, see Q22. |

## Found while building Phase G

| # | Finding | Severity | Status |
|---|---|---|---|
| N52 | *Ship* on an open sales order (Actuals) posted the sale in the browser: no stock check, nothing for an order at a warehouse (no route to it), no part delivery, and it skipped the engine's posting rules. | Serious | **Fixed (G).** *Deliver* goes through the engine: from where the order was promised, else the customer's first route, else the order's own place; it says when the place goes below zero. *…* opens the order for a part delivery, a change or a cancellation. |
| N53 | An order's value counted a missing price as zero: "₹0 of sales on backorder", and a product without a price looked like a free giveaway in the backorder total. | Minor | **Fixed (G).** An order without a price has no value, and the backorder total says how many orders have none. |
| N54 | Two sales orders with the same number were not flagged by the data check (only receipts, movements and purchase orders were). | Serious | **Fixed (G).** A duplicate sales-order number is an error. |
| N55 | Removing a sales order (Master data → Demand) left its deliveries without an order and its promise as an orphan confirmation, a blocking error. | Serious | **Fixed (G)** by *Cancel*, which keeps the order in the closed-order log and drops its promise. |
| N56 | After an action on one page (taking an order), another page's earlier result (Actuals' open orders) stays until it is recalculated; its tab shows it is out of date, but the new order is not in its list yet. | Minor | **Fixed (J).** Actuals, Buying, Money and customer orders recalculate when opened out of date; edits made on the page itself keep the *out of date* mark until recalculated. |
| N57 | Posting messages give dates as 2026-09-28 while order messages say Mon 5 Oct. | Minor | **Fixed (J).** Every engine message shown (postings, orders, purchasing, the data check, the worklist) reads dates as "Mon 28 Sep". |

## Found while building Phase I

| # | Finding | Severity | Status |
|---|---|---|---|
| N58 | Two planners taking a customer order at the same time both got the next number (SO-00004), and keeping one save over the other silently dropped the colleague's order. The same holds for purchase orders and goods movements numbered in the browser. | Serious | **Fixed (I).** *Merge both* merges record by record from the save both started from; a record both added under the same number keeps the latest save's and gets the next free number for the other, and the promises and deliveries that point at it follow. *Replace theirs with mine* now says what it undoes. |
| N59 | Plan versions and the worklist were one pool on the server: anyone reaching it could list and open every version, and two companies with the same name shared one worklist. | Serious | **Fixed (I).** Both are kept per company (`X-Company`), for its members only; the browser's own stay separate. |
| N60 | A viewer's order check went through to *Take this order*; nothing was saved, but the page moved on as if it had been. | Minor | **Fixed (I).** Every engine call that changes the company is refused before it is sent, with the reason; direct edits are refused with a notice. |
| N61 | Opening a company, merging or putting back left every result empty until *Plan everything*. | Minor | **Fixed (I).** Opening a company plans it. |
| N62 | A viewer still sees the buttons that change data (they are refused with a reason, not hidden or disabled). | Minor | **Fixed (J).** Buttons and forms that change data are disabled for a viewer, with the reason on hover; anything left is still refused with a notice. |
| N63 | No password reset: a forgotten password needs the server's administrator (there is no mail sending), and an owner cannot reset a colleague's. | Minor | Open: needs a mail setup or single sign-on (SAP gap below). |
| N64 | Each save sends the whole company, as every planning call already does. A company of tens of megabytes saves slowly; saving only what changed would be lighter. | Minor | Open. |
| N65 | Where both people changed the same record, the merge keeps the latest save's version and lists the record; there is no side-by-side choice per record. | Minor | Open. |

## Found while building Phase J

| # | Finding | Severity | Status |
|---|---|---|---|
| N66 | *Performance*'s breakdown by series named them by ids ("DEALERS-WEST · EMULSION-WHITE-20-L"). | Minor | **Fixed (J)** with Q17. |
| N67 | On a phone, a list-and-detail page could still be widened by its detail (a table or chart), clipping it on the right. | Minor | **Fixed (J).** The stacked column is never wider than the screen; wide tables scroll in their own box. |
| N68 | At phone width the save chip read "This bro". | Minor | **Fixed (J).** Its short form is *Local*. |
| N69 | The purchase order document has no addresses: places have no postal address, and the supplier's contact and terms appear only when its purchasing data is filled in. | Minor | **Fixed (J+).** A place has a postal address and a tax number, the company an invoice address and a tax number (*Set up → Your company*, and the place's record). The order prints the supplier's address, where to deliver and where to invoice; the e-mail carries them; an order whose addresses are missing says which, with links to fill them in. The kitchenware example has addresses. |
| N70 | A viewer can still type into the stock count and the demand grid (they are not forms); nothing is saved, and the change is refused with a notice. | Minor | **Fixed (J+).** Every page was walked as a viewer, listing each control still enabled: the stock count, the demand and consensus grids and the others in N74 are now disabled. What stays open to a viewer changes nothing: filters, searches, ticking rows, checking an order's availability. |
| N71 | A result that was never calculated (after reopening the browser) still waits for *Plan everything* or *Calculate*; only out-of-date results recalculate on opening a page. | Minor | **Fixed (J+).** Actuals, Buying, Money and customer orders calculate a missing result on opening (about half a second on the kitchenware company), unless the data check blocks planning. |

## Found while fixing N69–N71

| # | Finding | Severity | Status |
|---|---|---|---|
| N72 | The consensus grid named its series by ids ("KT-15 CUS-ECOM"), in the rows and in the cells' labels. | Minor | **Fixed (J+)** with names. |
| N73 | The worklist's *Where* column and the setup matrix's machine buttons and title still showed ids. | Minor | **Fixed (J+).** |
| N74 | Beyond the two grids of N70, a viewer could still change the capacity levelling settings, position a DDMRP buffer, set a worklist item's owner or mark it seen or resolved (the server refused), pick a shop-floor profile or method, type into the setup matrix and save a version (refused too). | Minor | **Fixed (J+).** All shown disabled with the reason on hover. |
| N75 | Multi-line fields (the new addresses) showed one line: the input style fixed their height. | Minor | **Fixed (J+).** |
| N76 | Screen-reader labels on the inventory placement and buffer tick-boxes still use ids ("Select PLT-PUNE RM-STAMP"). Sighted users see names. | Minor | Open. |

## Found in the second reality check (after Phase E)

A new company built from an empty start through the screens only: a paint maker with one plant, a distribution
centre, a depot, three suppliers (one importing), two customer channels, three finished goods, one bulk
intermediate, four raw materials and three packs. Demand came in as a monthly spreadsheet, stock as an upload. Then
one full cycle: plan everything, create and send purchase orders, record a late confirmation, firm the next two
weeks, post the week's production, transfers and sales, move the plan forward a week, re-plan, and read every page,
on a desktop and at phone width. Phases F–J are the proposal at the end of this section.

| # | Finding | Severity | Status |
|---|---|---|---|
| Q1 | Stock typed in during setup (the product wizard's *On hand today*, or an upload of stock) never becomes an opening movement. As soon as a place gets its first movement, its stock is recomputed from the journal alone: after one transfer arrived, the Mumbai warehouse went from 900 tins to 25.9, and after the week's sales every stocked place read negative. | Critical | **Fixed (F).** Stock entered at setup at a place with no earlier movement is its opening balance, dated the day before the planning start: the stock view shows it as *opening*, and starting a new week writes it into the journal before anything else (`engine/scp/actuals/stock.py` `pending_openings`). A place kept twice gets one opening, from the record planning uses. |
| Q2 | *Receive* on a stock transfer posts only its arrival: nothing takes the goods out of the sending place, and there is no *Ship* button for a transfer. The same tins then sit in the plant and the warehouse at once. | Critical | **Fixed (F).** A transfer has *Ship* (goods issue at the sending place; the goods are in transit) and *Receive*; receiving what was never shipped posts the dispatch with it, so the same goods are never in two places (`engine/scp/actuals/post.py`). |
| Q3 | *Receive* on a production order adds the product but never issues its parts: resin, pigment and tins stay at their opening stock however much is made, unless each issue is posted by hand in the journal. | Critical | **Fixed (F).** *Confirm* on a production order posts what was made, issues its parts in proportion (its reservations, or the bill of materials for an imported order), receives co-products, and says when a part goes below zero; *…* posts part of it, closes it short, or takes the parts actually used instead. |
| Q4 | The goods-movement upload refuses a file without an *id* column, which no dispatch register or stock report has. | Critical | **Fixed (F).** The id column is optional on a movement upload; new movements are numbered GM-00001, GM-00002, … after the journal's last. |
| Q5 | There is no way to take a customer order. *Check a new order* is a simulation ("Nothing is saved"); an order has to be typed into *Master data → Demand* with its kind set to sales order. | Critical | **Fixed (G).** *Customer orders → New order*: check it, then *Take this order* saves it as a sales order with the next number in the company's own series (SO-00001, or SO-88222 after SO-88221) and keeps the promise it was given, so later orders cannot take its stock. It takes a price and the customer's own order number. Each open order has *Deliver* (all or part, from where it was promised or another place, last delivery closes it), *Change* (quantity, date, priority, price, delivery rule; promised again) and *Cancel* (the rest; logged as a cancelled closed order that OTIF leaves out). `engine/scp/promise/orders.py`, `POST /api/orders/sales`, posting action `deliver`. |
| Q6 | Products counted in each are planned in fractions: production orders for 25.9 tins, a transfer of 2.22 pails, 203.23 pails a week in the demand grid. | Serious | **Fixed (H).** A product in a unit counted in pieces (EA, box, case, tin, pail, bag, drum, …) is planned in whole units: planned orders round up, forecasts are released as whole units with the running total kept within half a unit. *Whole* on the product list overrides the unit either way (`Product.whole_units`). |
| Q7 | The default lot size is exactly what's needed, day by day: 2,032 planned orders over 26 weeks for four products (573 production runs, 1,184 shipments), four batches of base in four days, 61 orders to start in one week. | Serious | **Fixed (H).** The company says how much an order covers where a product leaves it empty (`settings.default_lot_policy`): a new company starts at a week's need. On the paint company that is 363 orders over 26 weeks instead of 1,901. The company step can move products set to *exactly what's needed* over to it. |
| Q8 | A process plant cannot be described: a batch of paint is mixed in fixed batches (e.g. 2,000 L in 3 hours whatever the fill), but a step only takes minutes per unit and setup hours. | Serious | **Fixed (H).** A step can run in batches: batch size and hours per batch, however full (`Operation.batch_qty`, `batch_hours`). Orders are planned in whole batches (counting the units entering the step) unless the production source allows part batches; scheduling, lead times, promising and capacity use the batch time. In the make form and the routing upload. |
| Q9 | Two roads to a purchase order disagree. *Buying* groups lines per supplier and applies approval and minimum order value; *Actuals → firm zone* firms each purchase as its own order and skips both. Firming "everything" there also re-ordered 200 kg of pigment already on order (the confirmed-late line), without saying so. | Serious | **Fixed (F).** Firming a purchase goes through Buying's own order creation: one order per supplier, place and currency, approval limit and minimum order value on the whole order, the supplier's earliest delivery on a late start. A planned purchase that an open order would cover if it came sooner names that order in the firm zone and on *To order*, and the firm zone leaves it unticked. |
| Q10 | *Capacity plan* reports revenue of ₹4.01 Cr when no selling price is set (it values each sale at its cost), while *Money* says revenue ₹0 and a margin of −₹4.19 Cr. | Serious | **Fixed (G).** Revenue and margin count only sales with a price (the order's own, else the customer's, else the product's). Without one, a cost-to-serve row has no margin, an order no value, and the capacity plan leaves its sales out of revenue (it still values them at cost in the model, so serving them earns nothing). *Money*, *Home* and the capacity plan name the products without a price and link to setting them. On the paint company: "Emulsion white 20 L, Emulsion white 4 L and Enamel red 1 L have no selling price". |
| Q11 | The demand upload does not read the columns a sales spreadsheet has: *Customer* is not taken as the place, *Month* is not taken as the date, and "Oct 2026" is "not a date". A monthly forecast needs an ISO date plus a *period_days* column that nothing mentions. | Serious | **Fixed (H).** A demand or history upload reads *Customer*, *Month*, *Units sold*, *Item name* and other sales-sheet columns; a month ("Oct 2026", "2026-10", "10/2026", "Oct-26") or a week ("2026-W41") is a total spread over its days (`period_days`, now on history too), and a sheet with the months across the top becomes one row per month. |
| Q12 | An empty company never asks its name, currency, planning start or working week (the header says "My Company", Monday to Saturday is imposed), and setup never asks for selling prices or costs. | Serious | **Fixed (H).** *Start with an empty company* asks the company's name, currency, planning start, working days and how much an order covers; *Set up → Your company* changes them and the exchange rates later, and the checklist starts with it. The product list takes selling prices and costs, marks the whole-unit products and shows a bought product's supplier price; the checklist notes sold products without a price. |
| Q13 | *Enter stock on hand* opens an empty planning-policy table (the side list shows a warning count of 15 next to it). Stock can only be typed once a policy row exists for each product and place. | Serious | **Fixed (F).** *Actuals → Count stock*: every product at every place it is kept (planning policies, production and its parts, purchasing, routes, the journal) with its stock now and a *Counted* column. A place with nothing recorded gets an opening balance, any other a count difference, and on-hand follows the journal; a count after the start counts at the next new week. The checklist's stock step opens it. |
| Q14 | The working company exists only in this browser's local storage: no sign-in, nothing shared with a colleague, gone if site data is cleared. A real company with a year of history will outgrow the browser's roughly 5 MB, and a failed save is swallowed without a word. | Serious | **Fixed (I).** Companies kept on the server (`engine/scp/companies`, `/api/auth/*`, `/api/companies/*`): accounts, members as owner, planner or viewer (invited by e-mail), every change saved a moment later with the top bar saying so, a save on top of an older revision refused with who saved and when, *Merge both* record by record, a history of every save with what changed, compare and put back. Plan versions and the worklist are kept per company. A browser-only company whose save fails now says so (storage full or blocked) and offers the server or a download. |
| Q15 | A late posting goes nowhere visible. Sales posted after the week was rolled are dated before the new start, so forecast accuracy still reads "0 units sold vs 2,732 forecast" and nothing asks for a re-roll. Home kept saying 98% on time while four places disagreed with the journal; the data check calls that a warning. | Serious | **Fixed (F).** The actuals view says what re-booking the current start would change (stock, orders, accuracy weeks, history, closed orders); *Actuals* shows *Not counted yet · Count them now*, and Home leads with *Is the stock the plan starts from right?* whenever postings are not counted, stock disagrees with the journal or a place would go negative. |
| Q16 | The buy form takes a price only in the company currency, so the importer's USD pigment has to be converted by hand. | Minor | **Fixed (H).** The buy form takes the price in the supplier's currency and asks for the exchange rate once. |
| Q17 | Raw ids are still on screen: the data check's problem text ("EMULSION-WHITE-20-L at VAPI-PAINT-PLANT is needed…"), the shop-floor board's rows, legend and busiest-resource tile, *Buying*'s "PO-00001 to PIGMENT-IMPORTER", the firm zone's *From* column (truncated source ids), and the new-order drop-downs, which lead with the id. | Minor | **Fixed (J).** Engine messages are shown with names for ids (places, products, machines) wherever they appear; the shop-floor board, its legend and tiles, Buying, the firm zone, panel titles and the performance breakdowns name them; pickers lead with the name. |
| Q18 | An import preview marks every row "added" while a required column is missing and the import button is disabled; the reason is one line above the table. | Minor | **Fixed (H).** While a required column is missing, no row says *added* and the counts are hidden. |
| Q19 | *Machines & shifts* at phone width: the detail panel stays beside the list, one word per line. | Minor | **Fixed (J).** List-and-detail pages stack at phone width and the detail no longer widens the page. |
| Q20 | *Performance* shows "Days of supply 9.28 d" graded "No data". | Minor | **Fixed (J).** A measure without a grade says why: *No data*, *No target*, or *For reading* (days of supply, cost to serve: neither better high nor low). |
| Q21 | Three pages give three utilisations with no word on why: the supply plan's busiest machine 65%, the capacity plan's peak 15%, the shop floor's 29%. | Minor | **Fixed (J).** Each names the machine and the period: the supply plan's busiest week, the capacity plan's busiest month, the shop floor's scheduling window. |
| Q22 | Planned-order numbers are handed out again on every plan (PR-00006 was later a different requisition), and firming renames them (MO-00430 became PRD-00008), so the shop-floor board, the firm zone and *Actuals* don't match up. | Minor | **Fixed (J).** A firm order keeps the planned number it came from (`planned_as`), shown as "was MO-00430" on Actuals and the shop floor; the plan's orders and the firm zone say planned numbers are temporary. |
| Q23 | *Mark as sent* only records a date: there is no purchase order document to download, print or send. | Minor | **Fixed (J).** *Print or PDF*, *Download* and *E-mail* on a purchase order: a document with the supplier's terms, the lines, prices and delivery dates. |
| Q24 | A late requisition shows "Order by Mon 28 Sep · late", which is today, not the date it should have been ordered. | Minor | **Fixed (J).** It reads "Now · late, should have been Mon 21 Sep" (`wanted_order_date`). |
| Q25 | The new-route form keeps the previous route's days in transit. | Minor | **Fixed (J).** The form starts from the defaults after each route. |

What held up: the network builder, product wizard, stock and demand uploads (once the columns matched), the
checklist, plan everything, requisitions to a purchase order with a late confirmation that planning used at once, the
roll-forward report, and every page at phone width except *Machines & shifts* (no page scrolls sideways).

### Proposed next phases

- **F: execution you can trust** (Q1–Q4, Q9, Q13, Q15): **done**, see the statuses above and N41–N47. Setup stock becomes the opening balance. A production
  order confirms with its parts issued. A transfer ships and arrives, with stock in transit between. Movements
  upload without ids. There is one road to a purchase order. Late postings offer a re-roll. Home leads with stock
  that disagrees with the journal.
- **G: order to cash, first steps** (Q5, Q10): **done**, see the statuses above and N52–N55. Take a checked order. A
  sales-order list to deliver, change and cancel from. Customer prices and an order's own price. Revenue and margin
  only where prices exist. Payment terms, credit checks and invoices are SAP gaps below.
- **H: sensible defaults and a second onboarding pass** (Q6–Q8, Q11, Q12, Q16, N40): **done**, see the statuses above and N48–N51. The company's own settings
  come first. Whole units. A weekly default lot size. Batch steps. Monthly demand upload. Prices and costs in
  setup. Supplier currency.
- **I: a real place to keep the company** (Q14): **done**, see the status above and N58–N65. Server-side storage,
  sign-in and roles, autosave with conflicts caught and merged, an audit trail with compare and put back.
- **J: polish sweep** (Q17–Q25, N8, N31, N56, N57, N62): **done**, see the statuses above and N66–N71; its open
  items N69–N71 are **done** too (J+), with N72–N76.

## Found in the third reality check (Phase K)

A food company built from an empty start through the screens: Godavari Dairy Foods (fictional), one dairy plant at
Nashik, a cold store at Pune, five suppliers (a milk co-op delivering daily, sugar, mango pulp, an imported culture,
packaging), three customer channels (modern trade, general trade, hotels and caterers), four finished goods (mango
yoghurt, plain dahi, paneer, and catering paneer made to order for the hotels, 7 days' shelf life), standardised milk
as an intermediate, and two years of weekly sales history. An owner (Asha, who also enters sales promotions), a
planner (Ravi) and a viewer (Meera, on a phone) were signed in at the same time. Then **six planning weeks**, each:
Home, buy what is due and send it, firm the firm zone, take the hotels' orders, post the week's receipts, production,
transfers, deliveries and a dispatch register upload, sometimes a short delivery or a count, check the stock, move the
plan a week, re-plan and read the results. Week 5 carried a mango promotion (+40 % at modern trade) that marketing
entered ahead of time; week 6 a stock count at the cold store.

How the weeks went (forecast accuracy and bias as *Actuals* shows them after each roll, over the weeks measured):

| Week | Accuracy | Bias | What happened |
|---|---|---|---|
| 1 | 73 % | +26.8 % | Sales uploaded without a customer became phantom series at the cold store and the plant (R1–R4). |
| 2 | 80 % | +7.0 % | A colleague's save silently stopped the planner's (R6); Monday demand late every week (R9). |
| 3 | 83 % | +2.7 % | Make to order supplied orders from stock and made them again (R7). |
| 4 | 85 % | −7.1 % | OTIF to confirmed date 25 % although every hotel order left on the day (R8). |
| 5 | 86 % | −8.2 % | The promotion reached the plan only once it was flagged (R10); a hotel order half late (R12). |
| 6 | 86 % | −7.7 % | OTIF to confirmed date 40 %; the late half of that order stayed late (R13); count at the cold store. |

Ranked: the critical ones first (all fixed in K), then what is open, with the phase that takes it.

| # | Finding | Severity | Status |
|---|---|---|---|
| R1 | A dispatch register's *Customer* column was dropped on upload ("Customer (not used)", *Place* had taken the location): sales lost their customer. | Critical | **Fixed (K).** A movement upload reads *Customer*, *Supplier*, *Vendor* or *Party* as the counterparty; the movement table shows it as *Customer or supplier*. |
| R2 | Sales without a customer counted as sales of the cold store and the plant: week 1 accuracy 0 % on every channel, and 42 rows of new history series at places that sell nothing. | Critical | **Fixed (K).** A sale without a counterparty, from a place with no demand of its own that ships the product to one channel only, counts as that channel's (accuracy and history). |
| R3 | Deleting the 42 wrong history rows did not stick: history is rebuilt from the journal on every roll. No bulk delete either. | Critical | **Fixed (K).** Master data deletes every row a search finds (*Delete these N*, with a confirmation); the journal's counterparty is visible and editable, which is where the fix belongs. |
| R4 | The forecast then had 13 series instead of 7, and releasing it again replaced only the series it wrote: the six phantom series stayed in demand (4,96,122 units over 26 weeks instead of about 2,52,000), with no warning. | Critical | **Fixed (K).** Released records are marked; a full release removes what earlier releases wrote for series it no longer has and names them. New check `FORECAST_TWICE`: a forecast at a place and at a customer it supplies. |
| R5 | Make to order set where setup leads (the plant) did nothing: the forecast sat at the hotels' channel, whose own default strategy passed it on, so 100 catering paneer a week were made with no order. | Critical | **Fixed (K).** A customer channel without a planning record takes its strategy from the nearest place upstream. |
| R6 | Two people at once: Asha changed one safety stock while Ravi firmed 8 orders and took 2 hotel orders. Ravi's next save was refused, and every later page kept saying "Saved"; nothing of his reached the server until he pressed *Merge*; the viewer saw none of it. Re-doing the work then took both hotel orders twice. | Critical | **Fixed (K).** A refused autosave merges by itself when no record changed on both sides and says so; only a real clash asks. The order form warns when the customer's order number is already an order. A viewer's page takes in each new save. |
| R7 | Make to order ignored stock in planning while promising used it: two hotel orders were promised from stock *and* got a new batch; catering paneer (7 days' life) reached 340 on hand. | Critical | **Fixed (K).** Make to order uses free stock first, never the forecast. |
| R8 | OTIF to confirmed date read 0 % every week though every hotel order left on the day asked: the order list showed the arrival date, the planner posted the delivery on it, and the one-day route made each arrive a day late. | Critical | **Fixed (K).** *Ship by* on the open-order list (the promise's ship date, else the date less the route) with "late if sent …". |
| R9 | Routes of half a day were rounded up to a day everywhere: Monday demand at the channels could never be met, about 1,330 units late every week. | Critical | **Fixed (K).** Up to half a day arrives the same day, in planning, promising and the journal's transit. |
| R10 | Asha entered the promotion as a demand event; Home said "Everything is up to date" and the plan's demand never had it. | Critical | **Fixed (K).** A release records what it was made with; a later change to events, new-product rules, overrides or forecast settings raises `FORECAST_INPUTS_CHANGED` and a *Not in the plan yet* banner on Demand. With it used, mango at modern trade for the promotion week went 1,968 → 2,827 (sales 2,921). |
| R11 | Using the forecast wrote a forecast for the hotels' catering paneer, made to order: ignored by the plan, a warning every week. | Critical | **Fixed (K).** A release skips products made to order where they are sold, removes what earlier releases wrote for them, and says so. |
| R12 | Capable-to-promise took a component's availability even when it came months out (standardised milk free in March) and never tried making it (milk bought today, standardised by Tuesday): 20 of a 60-unit hotel order were promised 3 days late on the lead time. | Critical | **Fixed (K).** The earlier of the component's stock and new supply. |
| R13 | A promise on new production does not make that production: the run stayed planned (Monday's firming came before the order), was never made, and the order went late at the roll. Nothing on Home pointed to backorder processing, which then brought the order on time. | Serious | **Fixed (K).** Taking an order made to order, or promised on new supply, says it must be made firm and where; Home links *Try to bring late orders forward* when an order is late. SAP's CTP creates the planned order itself: **P**. |
| R14 | Home repeated "3 places would go below zero" every week for dips weeks old that the stock had come back from, and for dips a count had settled. | Serious | **Fixed (K).** A dip is reported while it lasts, or when it began in the week just closed and no count ended it. |
| R15 | Shelf life never limits the plan: catering paneer (7 days) made in batches of 100 covering 10 days; "May expire" is a tag, but lot sizes, batch rounding and "a week's need" ignore it, and nothing expires in stock. | Serious | Open: **O** (expiry in stock, first expiring first out) and **P** (lot sizes within shelf life). |
| R16 | A short milk delivery (85 %) is posted "closed 769 short", but the firm runs that needed it are not flagged; posting them in full takes raw milk to −2,307, and the roll sets it to 0. | Serious | Open: **O**. |
| R17 | Raw milk ends every week slightly negative (−306): the plan buys exactly what the runs need and any yield or rounding takes it below zero; nothing suggests a buffer. The roll's "set to 0" leaves the journal and the plan disagreeing until someone counts. | Serious | Open: **O** (stock below zero as a policy: refuse, allow, or count), **P** (yield in the bill of materials). |
| R18 | A person conflicts with their own save: a reload while a save is in flight is refused next time as "Ravi saved … after your changes began", shown to Ravi. | Serious | Open: **L**. |
| R19 | History keeps a state to put back only every ~10 minutes per person, so "just before the release" was not there; *Undo* is gone after a reload. | Serious | Open: **L** (every save put-back-able; undo that survives a reload). |
| R20 | Firming makes purchase orders after the day's orders were sent on *Buying*; they wait "to send" until someone goes back. | Serious | Open: **N** (firming offers to send what it created). |
| R21 | Demand events are entered only in Master data; *+ New event* saves at once an event on every product at every place with the measured lift. | Serious | Open: **P** (events on the Demand page; a new event starts without effect). |
| R22 | Two numbers called accuracy: Home "92 % accurate on past weeks" (backtest), Actuals "73 % against real sales". | Minor | Open: **J-type sweep in L**. |
| R23 | One negative count refused all three counts; the count grid showed a negative book stock (−905) as the suggested count. | Minor | **Fixed (K).** A negative count is flagged before saving; a stock below zero is marked and suggests 0. |
| R24 | A viewer's Home said "Nothing calculated yet" while its first calculation ran. | Minor | **Fixed (K).** "Calculating the plan from the latest save…". |
| R25 | Event lift said "0.3 = +30 %" on a field typed in percent (also the override change and the forecast interval). | Minor | **Fixed (K).** |
| R26 | Backorder processing told the planner to "simulate … then commit"; the buttons are *Re-decide who gets scarce stock* and *Save these new promised dates*. | Minor | **Fixed (K).** |
| R27 | Master data tables and record headers show ids; the index shows a table's problem count where its row count goes ("Planning policies 3" for 16 rows); "Where used" truncates a source id. | Minor | Open: **L** sweep. |
| R28 | Signed in, *Create the company* still makes a browser-only company; keeping it on the server is a second step. | Minor | Open: **L**. |
| R29 | Setup never asks shelf life or make to order; forecast settings are labelled "Abc a", "Xyz x" and list models by code; *Upload sales history* opens a table where the upload is another button. | Minor | Open: **L** sweep. |
| R30 | No refrigerated route mode; the cold chain is "Truck (full load)". | Minor | Open: **O**. |
| R31 | Smaller: Actuals before a roll says movements run "up to" the start when they run to the week's end; the merge banner takes the page's own message slot; an order promised in two lines on the same day lists the day twice; a raw-milk PO line keeps 12 decimals in the data; the promotion check starts only with the first release after it existed. | Minor | Open: **L** sweep. |

What held up: building a dairy from nothing (network, products with batches and a made-to-order line, suppliers with
currencies, two years of history), buying and sending every week, firming, posting a week of receipts, production and
transfers in minutes, the weekly roll, the promotion once it was in, backorder processing, the viewer on a phone (no
sideways scroll, no change buttons), and three people working on one company without losing a change once R6 was fixed.

## The next plan (after Phase J)

Every finding of the first two reality checks is fixed, and every critical one of the third (K). What is left is
K's open findings (R13–R31, ranked above), breadth against SAP (the gaps below), the small open items (N63–N65,
N76) and use at a real company's scale. Proposed, in the order recommended:

- **K: third reality check, over weeks, not a day**: **done**, see R1–R31 above. Every critical finding is fixed;
  what is open is ranked there with its phase, and the phases below are re-ordered by it.
- **L: platform for real use** (R18, R19, R22, R27–R29, R31, N63–N65, N76 and the users gap). A save never
  refused as someone else's when it is one's own (R18); every save a state to put back, and undo that survives a
  reload (R19); saves that send only what changed (N64); a side-by-side choice per record when two people changed it
  (N65); password reset by e-mail and single sign-on (N63); rights by plant or product group; four eyes on
  master-data changes; change documents with every field's old and new value; a nightly backup and a restore.
  Creating a company while signed in keeps it on the server (R28). A sweep of the minor items (R22, R27, R29, R31,
  N76). A measured test at scale (5,000 products × 20 places, two years of history) with the plan's time and memory,
  and the slow parts fixed. A deployment guide (container, database, mail).
- **O: stock you can trace** (R15–R17, R30 and the inventory gaps; moved up by K). Batch numbers with an expiry
  date, and first expiring, first out, so shelf life shows in stock (R15); a short receipt names the firm orders that
  can no longer run in full, and offers to shorten them (R16); stock below zero as a company rule — refuse the
  posting, allow it and ask for a count, or count it as found — instead of the roll setting it to 0 (R17); stock in
  quality inspection and blocked; reversal of a posting; a physical inventory document with a freeze; stock in
  transit as its own stock type; a refrigerated route mode (R30); serial numbers.
- **P: planning depth** (R13, R15, R17, R21 and the remaining MRP, BOM, capacity and PP/DS gaps; moved up by K).
  Capable-to-promise that creates the planned order it promised on, firm, as SAP does (R13); lot sizes and batches
  that stay within shelf life (R15); yield in the bill of materials so a part is bought with the loss in it (R17);
  demand events on the Demand page, a new one starting without effect (R21); MRP groups; withdrawal from another
  plant and direct production; a discontinued product with its follow-up; alternative BOMs; overtime as a levelling
  and optimiser choice; supplier and lane capacity in planning; steps needing a machine and a tool together;
  dragging orders between days to level.
- **M: order to cash, complete** (SD gaps). Orders with several lines; prices with discounts and quantity scales;
  payment terms and a credit check; an order confirmation to send the customer (as the purchase order); delivery
  documents with picking, packing and proof of delivery; invoices; returns and credit notes; quotations.
- **N: procure to pay, complete** (R20 and the MM gaps). Firming offers to send the purchase orders it created
  (R20); invoice verification (three-way match) and what is owed to whom; contracts and scheduling agreements;
  several confirmation lines per order line; returns to the supplier; a release strategy with more than one level.
- **Q: connected to the rest of the company**. Scheduled imports and an API for an ERP to send orders, stock and
  movements and to take back purchase and production orders; e-mail sent from the application (orders to suppliers,
  confirmations to customers, the worklist's reminders).

Order after K: **L, O, P, M, N, Q**. L stays first: six weeks with three people showed that trust in saving and
going back (R18, R19) matters before any new process, and a year of history needs the scale work. O and P move ahead
of M and N because every open serious finding of K is about stock that is really there (shelf life, short receipts,
stock below zero) or a plan that acts on it, while none was about invoices or contracts: a food company cannot run on
a plan that ignores expiry, and it can invoice from its own system meanwhile.

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
- Inventory management: opening balances, counts with differences, transfers shipped and received with stock in
  transit, production confirmations with backflush or actual usage and co-products (**F**, done). Still missing: batch
  and serial numbers, stock types (quality inspection, blocked), stock in transit as its own stock type, physical
  inventory documents with a freeze, reversal of a posting (today: undo, or a counter-movement). Goods issue for a
  sales order is a posting on the order (**G**, done); a delivery document with picking and packing is still missing.
- SD: taking an order with the availability check's promise, order changes promised again, cancelling the rest with
  the order logged, deliveries in part or in full, and customer-specific prices (**G**, done). Still missing:
  several lines per order, pricing conditions with discounts, surcharges and quantity scales, payment terms and a
  credit check, delivery documents (picking, packing, proof of delivery), billing and invoices, returns and credit
  notes, quotations and contracts, and output (an order confirmation to send the customer).
- MM: supplier purchasing data with a purchasing block, info records with price scales, the source list (fixed
  and blocked), requisitions from MRP, purchase orders with an approval limit, supplier confirmations that planning
  uses, and goods receipts with delivery tolerances (**E**, done). Still missing: invoice verification (three-way
  match) and payment, outline agreements (contracts and scheduling agreements), several confirmation lines per
  order line, quality inspection stock, returns to the supplier, and a release strategy with more than one level.
- Users and authorisations: accounts, companies with owner, planner and viewer roles, invitations, conflict-safe saves
  with a merge, and a change log per company (**I**, done). Still missing: authorisation by object (a planner for
  one plant or product group only), approval steps (four eyes) on master data changes, single sign-on (SAML or
  OpenID Connect) and password reset by e-mail, locking a record while someone edits it, and change documents with
  every field's old and new value kept for years (the history keeps the first few per save, and a document per
  person per ten minutes).
