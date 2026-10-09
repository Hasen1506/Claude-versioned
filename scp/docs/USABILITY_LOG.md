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
| N47 | Receiving by quantity only: there is no batch or serial number, no stock in quality inspection, and a transfer's goods in transit are a quantity on the order, not a stock type of their own. | Minor | **Fixed (O)**, found stale after Q: receipts take a batch with its expiry and the supplier's batch, serial numbers, and go into quality inspection where the product asks; stock shows by batch and stock type, and a transfer shipped and not yet received shows as in transit at the receiving place. |

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
| N63 | No password reset: a forgotten password needs the server's administrator (there is no mail sending), and an owner cannot reset a colleague's. | Minor | **Fixed (L).** *Forgot your password?* mails a one-time link (an hour) when the server has a mail server; without one, an owner gives a planner or viewer *Link to set a new password* (a day) and the administrator has `python -m scp.admin reset-link`. Single sign-on by OpenID Connect (Entra ID, Google, Okta, Keycloak). Setting a new password signs out every other session. |
| N64 | Each save sends the whole company, as every planning call already does. A company of tens of megabytes saves slowly; saving only what changed would be lighter. | Minor | **Fixed (L).** A save sends the records that changed since the save it was made from (about 1 KB for one edit on the dairy, instead of 385 KB); the whole company only when that base is not known. Planning calls still send the whole company: N77. |
| N65 | Where both people changed the same record, the merge keeps the latest save's version and lists the record; there is no side-by-side choice per record. | Minor | **Fixed (L).** A clash shows each record side by side, field by field, with *mine* or *theirs* per record (an order and its promises are chosen together), *All mine* and *All theirs*. |

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
| N76 | Screen-reader labels on the inventory placement and buffer tick-boxes still use ids ("Select PLT-PUNE RM-STAMP"). Sighted users see names. | Minor | **Fixed (L).** "Select Stamping steel at Pune plant". |

## Found while building Phase L

L was used as it was built: the dairy of K with its three people (saving, merging, history, a forgotten password,
single sign-on against a test identity provider, rights by plant, a second person approving master data, a backup
put back), a company of 5,000 products at 20 places with two years of weekly history timed step by step, and the
container built and run as the deployment guide says.

Measured on 4 cores (5,000 products, 20 places: 11,635 planning policies, 624,000 history rows, 156,000 forecast
rows, a company of 71 MB), each step as *Plan everything* and a change ask for it:

| Step | Before L | After L |
|---|---|---|
| Reading the company | 3.4 s | 3.6 s |
| Data checks (after every change) | 22.2 s | 6.7 s |
| Network view (after every change) | 16.1 s | 6.7 s |
| Supply plan | 89 s, 5.1 GB | 66–78 s, 5.5 GB |
| Forecast (6,000 series) | about 40 min (300 series: 113 s) | 136 s |
| Promising | 99 s | 3.1 s |
| Safety stock | | 30 s |
| Capacity (S&OP) | | 14 s |
| Schedule | | 4.7 s |
| Buying | 45 s | 4.0 s |
| Actuals | | 9.0 s |
| Money | 16 s | 17 s |
| Performance | 24 s | 12 s |
| Saving one change | 5.1 s | 5–7 s |

| # | Finding | Severity | Status |
|---|---|---|---|
| N77 | A large company does not fit the browser. The web client holds the whole company and every result, sends the whole company with each planning call and with the checks after every change (71 MB each time at 5,000 products), and receives every result whole: the supply plan's answer is about 131 MB at 1,000 products (requirements 50 MB, orders 36 MB, pegging 25 MB, places 19 MB) and would be about 650 MB at 5,000. The browser's storage cannot keep it ("storage is full" is shown). Saving is light since N64; planning is not. At 1,000 products (a 14 MB company) the browser still copes: opening in 2 s, the first calculation in 27 s, *Plan everything* in 64 s, at most 200 MB of script memory. | Critical (at scale) | **Fixed (S)**, see N92–N99. Planning calls name the company's save and send only unsaved changes; answers are kept on the server, compressed and sent as rows; the plan comes without its pegging, which a page asks for. At 5,000 products every page opens in seconds with under 0.9 GB of script memory. |
| N78 | The supply plan of 5,000 products at 20 places takes 66–78 s and 5.5 GB in one process, so one server plans one such company at a time and needs 8 GB. | Serious | Partly **(S)**: the plan still takes 66–78 s and 5.5 GB, but it is worked out once per data (answers kept), a large company's calculations run one at a time so two never meet in memory, and the answer to the browser is a third of its size. A worker process per plan is left for later. |
| N79 | The forecast ran 20 times slower in parallel than one series after another: each worker's maths library started a thread per core (300 series: 113 s instead of 6 s; 6,000 series would have taken about 40 minutes). | Serious | **Fixed (L).** One maths thread per worker, set before the library loads; workers as many as the cores the server may use. 6,000 series in 136 s. |
| N80 | The data checks after every change ran twice (once for the readiness gate), copied each planning policy per row and looked up sources by scanning every source for every product at every place. | Serious | **Fixed (L).** Indexed sources and routes, policies worked out once per company, the gate reuses the checks: 22 s → 6.7 s; the network view 16 s → 6.7 s. |
| N81 | *Plan everything* planned the company six times (the plan, promising, capacity, buying, money and performance each asked for it with the same data). | Serious | **Fixed (L).** The last plan that took long is kept by the data's content and handed out again for the same data only; promising 99 s → 3.1 s. |
| N82 | Buying looked at every purchasing source for each planned purchase; money and performance each followed the plan's costs to the customers again. | Serious | **Fixed (L).** Sources by place and product; the costs followed to customers are kept beside the kept plan: buying 45 s → 4.0 s, performance 24 s → 12 s. |
| N83 | The container stopped at start: single sign-on needs an HTTP client that was installed only for development. | Critical | **Fixed (L)**, found by building the container: it is a dependency of the server. |
| N84 | *Your company* kept the values it opened with after a colleague's save; saving it wrote them back over the colleague's change. | Serious | **Fixed (L).** The form takes in a newer save while it is not being edited. |
| N85 | Saving *Your company* renamed the working calendar even when the working week had not changed, so the save showed a changed record nobody touched. | Minor | **Fixed (L).** |
| N86 | Rights by product group need products to have a group, and setup never asked for one. | Minor | **Fixed (L)** with R29. |
| N87 | An edit the person's rights do not cover was refused by the server, and after a reload the page kept trying to save it while *Undo* had nothing to undo. | Minor | **Fixed (L).** The refusal offers *Drop my unsaved changes* (back to the latest save), *Undo the last change* and *Download them*. |
| N88 | Changing a member to the role they already had was logged in *History*. | Minor | **Fixed (L).** |
| N89 | Safety stock for 5,000 products at 20 places takes 30 s: the placement is one optimisation over every place and product. | Minor | **Fixed (S).** Stages that do not supply each other are solved apart, small groups bundled, on every core: 11 s, and optimal (before, the one optimisation stopped at its 30 s limit). |
| N90 | Opening another company while *Plan everything* ran for the first one: the run went on, its later steps with the new company's data, and a result that came back after the switch was taken as the new company's and shown as up to date (the bottler's Demand page listed Kaveri's nine forecast series). Opening the new company did not plan it, because a run was going. Found with the 1,000-product company, where a run takes a minute. | Serious | **Fixed (L).** Opening a company, a file or a version drops every result asked for before it and stops that run at its next step; the new company is then planned. |
| N91 | The first requests to a newly started server, arriving together (a browser asks for the sign-in settings and the company list at once), each set up the company store: both added the new columns and one failed ("duplicate column name", an error page); on an in-memory database two stores could be made, one of them lost. Seen in the end-to-end tests' server log. | Serious | **Fixed (L).** The store and the company store are made once, under a lock. |

## Found while building Phase S

S was built against L's generated company of 5,000 products at 20 places (71 MB) in a real browser: opened, planned,
every page visited, a week of demand changed on the grid and everything planned again. The kitchenware company kept on
the server is planned by reference in the browser tests.

| At 5,000 products, 20 places | Before S | After S |
|---|---|---|
| Opening the company | 3.7–22 s | 1.4 s |
| First *Plan everything* | 439 s, and the supply plan never arrived | 326–357 s, every step (the forecast 136 s and the plan about 75 s of it) |
| *Plan everything* again, nothing changed | 373 s | 13 s |
| A week of demand changed, saved and checked | not measured (each cell copied and compared the whole company) | 18 s |
| *Plan everything* after that change | as the first | 252 s (346 s before a forecast took the unchanged series' competitions from the last) |
| Safety stock | 30 s, stopped at the solver's time limit | 11 s, optimal |
| Pages | Buying crashed the tab; Demand 36 s; the orders page 4.8 s and 1.2 GB; the pegging tree never showed | every page within 5 s, most under 1 s |
| Script memory kept | up to 1.2 GB, 2.6 GB with the pegging tree | at most 0.85 GB |

| # | Finding | Severity | Status |
|---|---|---|---|
| N92 | At 5,000 products the supply plan's answer, about 600 MB, could not be read by the browser ("Unexpected end of JSON input"), and Home then said "The data changed after the last calculation": a step that failed looked like data that had changed. | Critical | **Fixed (S).** The plan comes without its requirements and pegging, its lists as rows (a third as long) and compressed (at 1,000 products 120 MB became 20 MB to read and 2 MB over the wire); Home names a step that did not finish and why, in plain words. |
| N93 | Every product or place name on a page built the names of the whole company, and a pattern over every id, afresh: a table of a thousand orders did it three thousand times (the orders page 4.8 s and 1.2 GB; the pegging tree never showed). | Serious | **Fixed (S).** Made once per working copy: the orders page in 0.9 s. |
| N94 | Long lists drew every row: the requisitions, each with its supplier choice, crashed the browser tab; the demand grid, the consensus grid and the series lists drew thousands of rows of inputs (Demand 36 s). | Serious | **Fixed (S).** The first rows (500; 200 and 100 for grids of inputs), a search to reach the others, and how many there are. The demand grid also spreads each record over its own days only. Demand: 0.9 s. |
| N95 | Each edit copied the whole company and compared it with the one before as text, twice (seconds per cell at 5,000 products); the browser tried on every change to keep the company and its base in its storage, which holds a few megabytes, and kept thirty undo steps of it in its database. | Serious | **Fixed (S).** An edit copies and compares the parts it touches. A company the server keeps that is too large for the browser is not copied there (a reload opens it from the server), and its undo steps are not kept across a reload. |
| N96 | Opening a company read it into objects on the server and wrote it out again the slow way. | Minor | **Fixed (S).** Sent as it is kept, compressed: 1.4 s at 5,000 products. |
| N97 | Every planning call sent the whole company, eleven times for *Plan everything*, and the server read it anew each time; every answer went out through the slow generic writer, uncompressed. | Serious | **Fixed (S)** with N77: a call names the save and sends the unsaved changes (a few hundred bytes); unsaved changes are read on top of the kept save, sharing every unchanged list; a change the engine makes comes back as what changed. |
| N98 | Any change made the forecast run its model competition for every series again (136 s for 6,000 series), though a week of demand or a price leaves every history as it was. | Serious | **Fixed (S).** A series whose history and settings did not change takes the last competition's outcome, and the answer is the one a fresh forecast gives. |
| N99 | Two planners' unsaved changes planned at once would each take the plan's memory (5.5 GB at 5,000 products): more than a server sized for one. | Serious | **Fixed (S).** A large company's calculations run one at a time (`SCP_LARGE_AT_ONCE`); a step that runs long shows how long it has run. |
| N100 | A large company is not kept in the browser: a change made less than the autosave's 1.2 s before a reload is lost (the page asks before closing). | Minor | Open, accepted: the window is the autosave's. |
| N101 | A change still has every other step worked out again: the answers are kept by the whole company's data, so after any change the plan (about 75 s) and the checks (7 s) are the floor at 5,000 products. | Minor | Open: keys per step by what each reads, and a plan that re-plans only what a change reaches (with P). |

## Found while building Phase O

O was built against the tests' small plants and used in a real browser on the kitchenware company, whose heating element
keeps 720 days and so is now kept by batch. The heating elements at the plant were counted to zero, the zone firmed, and
the next delivery came in short (10 of 10,000) in the supplier's batch and closed the line: the receipt named the kettle
order it left short (1,450 needing 1,462 elements, 10 there) and offered to shorten it to 9, which it did. The batch was
then found in stock, blocked, its receipt reversed from the journal, and the plant counted on a physical inventory
document that held its postings until it was cancelled.

| # | Finding | Severity | Status |
|---|---|---|---|
| N102 | Goods received today (the planning start) were not in the stock tab until the next week began: a batch received into quality inspection could not be found, let alone released, the week it came. | Serious | **Fixed (O).** The stock tab shows the batches, stock types and serial numbers there are now, this week's postings included; what the plan starts from stays as it was, beside it. |
| N103 | A stock change dated today (a release, a block, a scrap) would change the plan only a week later, though the goods were on the shelf before today. | Serious | **Fixed (O).** A stock change is dated the day before the start when the goods were there then, and the plan starts from it at once, as a count does; goods that came in this week change this week. |
| N104 | The physical inventory sat below the quick count's grid of every product at every place: at a real company, a long scroll away. | Minor | **Fixed (O).** It comes first on Count stock; the grid is the quick count. |
| N105 | Seven stock tiles left one alone on a second row. | Minor | **Fixed (O).** The least used one is gone. |
| N106 | A product with a shelf life is now kept by batch unless it says otherwise (the kitchenware heater, the jam jar maker's fruit): its receipts get batch numbers and its issues take the first expiring. | Minor | By design, recorded: SAP needs a batch for an expiry date too. *Kept by batch* on the product turns it off. |
| N107 | A quick count that finds less of a batch-managed product takes the difference from the first-expiring batches; one that finds more puts it in stock without a batch, since the count does not say which. | Minor | By design, recorded: count a batch on a physical inventory document to say which. |
| N108 | The Buying page's goods receipt had no batch, expiry or serial numbers, and did not say which orders a short delivery left short. | Serious | **Fixed (O).** The same fields and the same offer as Actuals. |
| N109 | Expired stock is dropped from the plan and flagged, but lot sizes and batch sizes still ignore shelf life (a batch covering ten days of a seven-day product). | Serious | **Fixed (P).** A period lot covers no more than the days the product keeps; an economic or min–max lot is cut to what is used before it expires; a fixed batch longer than that is kept, and what it leaves to expire is a requirement of its own with a "Lot larger than its shelf life" warning, so the plan makes again for it. |
| N110 | A short receipt names the orders it leaves short, but a late one does not: an order whose parts arrive after it starts is not named. | Minor | **Fixed (P).** A receipt that leaves a firm order short names it with the day it can run in full from later receipts ("cannot start in full on time: 2026-01-14 (the rest on …)"); Actuals' short orders show *The rest* beside it. |
| N111 | The browser tests' server log showed "cannot commit – no transaction is active" from the worklist: each Performance request made the worklist anew, and making it runs a script that commits whatever transaction the shared database connection has open, another request's included. Found in the log, not on screen; a worklist sync could be half written. | Serious | **Fixed (O).** The worklist is made once per store, its tables under the store's lock; a test holds a transaction open while another thread makes one. |

## Found while building Phase M

M was built against the tests' small shop and then used in a real browser from an imported company: an order of two
lines for a customer with a 1,000 credit limit (blocked, then released), its confirmation marked sent, a delivery picked
two drums short, packed, shipped and signed for, the invoice paid within the discount days, one tin returned into quality
inspection and credited, and a quotation won; every Selling tab was then opened at phone width.

| # | Finding | Severity | Status |
|---|---|---|---|
| N119 | There are two places to take an order: *Orders → New order* (one line, availability checked before taking it) and *Selling → New order or quotation* (several lines, prices, quotations, the credit check). | Minor | Fixed (gaps after Q): *Selling → New order or quotation* checks every line before the order is taken (*Check what can be promised*): the lines go to the promise check together, each after the orders already promised and the lines before it, so two lines of one product do not count the same stock; each line shows on time, late or how much, and the result is marked out of date when a line changes. *Orders → New order* stays as the one-product check in depth (what production could add, other places to ship from) and points to it. |
| N120 | *Mark as sent* on an order confirmation changed the order but showed nothing: its result went to a message nobody displayed. | Serious | **Fixed (M).** The document buttons report through the order's own message line. |
| N121 | Money on documents was the compact screen format: an invoice total read "₹2.1K", and so did every purchase order document since Q23. | Serious | **Fixed (M).** Documents (purchase orders, order confirmations, invoices, credit notes) and the Selling page show exact amounts (₹2,257.20); summaries keep the short form. |
| N122 | Orders held over a credit limit and overdue invoices are on *Selling* only: not in the worklist on *Performance*, not on Home. | Minor | **Fixed (N)** for the worklist: credit holds and overdue invoices are there under *receivables*, supplier invoices blocked or overdue under *payables*, each linking to its page. Home shows the worklist's count. |
| N123 | Tax is one rate per customer (or the company's): no rate per product and no split into its parts (CGST, SGST, IGST by place of supply). | Minor | Fixed (gaps after Q): products carry a tax rate; a line takes the customer's own rate first, then the product's, then the company's, and keeps it on the invoice. With *Selling settings → tax split: gst*, an invoice to a customer in the company's state (region, else the GSTIN's state code) shows CGST and SGST per rate, to one in another state IGST; the split is fixed on the invoice when billed, the documents and the credit check use the same rates. |
| N124 | Overdue invoices have no reminder (dunning) and customers no statement of account. | Minor | Fixed (gaps after Q): the company sets reminder days (default 7, 21 and 35 days past due) in *Selling settings*. *Selling → Customers* lists the payment reminders due: each has its letter to print, download, e-mail or send from the server, and sending it from the server (or *Record … as sent*) records the reminder on its invoices. A very late invoice goes straight to the reminder it has reached. Clicking a customer shows their statement of account, by document and by age, sent the same ways. |
| N125 | Proof of delivery records the day the customer signed, but on-time delivery (OTIF) still counts the shipping day plus the route's transit days. | Minor | Fixed (gaps after Q): a sales order line closed by the roll counts as delivered on the day the customer signed for it when its delivery has a proof of delivery, else on goods issue plus the lane's transit; a proof of delivery recorded after the line closed moves its dates in the closed-order log. OTIF and perfect order read those dates. |
| N126 | *Money* shows the plan's revenue, not what was invoiced. | Minor | By design, recorded: *Money* is the plan's economics; what was billed, paid and is owed is on *Selling*. |

## Found while building Phase N

N was built against the tests' small plant and then used in a real browser from an imported company: a sales order's
purchase made firm and, as R20 asks, offered to be sent at once (it waited, being worth more than two release levels);
released by the buyer and the director and sent; confirmed by the supplier in two deliveries; the first received; its
invoice entered at a price over the contract's, blocked, released and paid within the discount days; five tins sent back
and the supplier's credit memo entered; what is owed read back; a scheduling agreement made; every Buying tab opened at
phone width.

| # | Finding | Severity | Status |
|---|---|---|---|
| N127 | Goods invoiced at 9.50 and sent back were credited at the order's 9.00, leaving 2.50 a tin owed on a return. | Serious | **Fixed (N).** A credit memo for a return takes the price the goods were invoiced at, else the order's. |
| N128 | The supplier list said "30 d terms" for a supplier with 2 % / 10 days / net 30 terms. | Minor | **Fixed (N).** The terms read as they are agreed. |
| N129 | A scheduling agreement with nothing scheduled yet counted as an open purchase order in Buying's answer line. | Minor | **Fixed (N).** Only agreements with open delivery schedule lines count. |
| N130 | Releases name who gave them only when people sign in on a server; in a company kept in the browser nobody is named, so one person can release every level of an order. | Minor | By design, recorded: four eyes needs accounts. On a server the release is the signed-in account's, a level with approvers takes only them, and one account never releases two levels of one order. |
| N131 | Contract prices price the orders and requisitions, but the plan's cost on *Money* still uses the info record's price. | Minor | Fixed (gaps after Q): a planned purchase takes the price of a contract valid on its order day, as its requisition will, so the plan's purchase cost on *Money* matches what will be ordered; stock is still valued at the info record's price. |
| N132 | A supplier invoice cannot carry freight or other unplanned delivery costs, and a price difference cannot be put right with a debit or credit for the price alone (subsequent debit/credit). | Minor | Fixed (gaps after Q): an invoice carries delivery costs (freight and other costs the order did not plan), counted in its net and its tax. A subsequent debit or credit (`SD-`/`SC-`) puts the price of invoiced goods right per unit without changing the quantity invoiced; a debit beyond the price tolerance is blocked, a credit lowers what we owe, and goods sent back later are credited at the corrected price. *Buying → Invoices* has the field and a *Price put right later* form on each invoice. |
| N133 | Invoice verification books nothing in a ledger: "received, not invoiced" is a list for the month-end accrual, not a GR/IR account. | Minor | By design, recorded: there is no general ledger here; *What we owe* and *Received, not invoiced* are what an accountant posts from. |

## Found while building Phase Q

Q was built against the tests' small plant, and then used in a real browser:
- The kitchenware example was kept on the server.
- An owner made a key for "SAP", and the ERP sent two customer orders with it: one taken, one with an unknown product. The message log said which line was refused and why, and the History had the ERP's save.
- A scheduled import was set up and run, the e-mail tab read, the key withdrawn, and every tab opened at phone width.

Mail was tested in the engine with a stand-in mail server.

| # | Finding | Severity | Status |
|---|---|---|---|
| N134 | A scheduled import could name any web address, so an owner could make the server read from its own network (a database's admin page, a cloud metadata address). A redirect could lead there too, and carried the import's Authorization header along. | Critical | **Fixed (Q).** Without `SCP_IMPORT_HOSTS`, a name that resolves inside the server's own network is refused, redirects included. Headers given for an import are not sent on after a redirect. |
| N135 | Worklist reminders named the company by its id ("Worklist: 2 open · C0001") when its settings had no company name. | Minor | **Fixed (Q).** They fall back to the name the company has on the server. |
| N136 | A refusal in plain words that came back as 422 was shown in the browser as "N schema error(s)". This applied to an e-mail address the company does not know, an import that cannot be read, and the other plain refusals. | Serious | **Fixed (Q).** The browser shows the server's sentence. |
| N137 | A purchase order deleted outright here (not cancelled) disappears from the orders the ERP takes, so the ERP keeps its copy open. | Minor | Fixed (gaps after Q): an order the ERP numbered that is deleted here goes to it as `withdrawn`, with no lines, until it acknowledges with its number; then it is `taken` (listed with `all=true`). Putting the save back before the ERP closed it drops the withdrawal. |
| N138 | The ERP's stock message is per place and product. A company with batches or stock types gets its count difference posted on the stock without a batch. | Minor | Fixed (gaps after Q): rows may name a `batch` (with `expires_on` for a batch new here) and a `stock_type`. A place and product given so is counted lot by lot on a physical inventory document marked "Stock from the ERP"; a lot here the ERP does not list is counted as none. A stock file with a column per stock type (as SAP's MARD) becomes a row per stock type. |
| N139 | Firming with *send* (R20) marks the purchase orders as sent but does not e-mail them. *Send from here* is order by order. | Minor | Fixed (gaps after Q): when the server sends mail, *Firming* says "E-mail the N purchase orders to the suppliers" and sends each document from the server; an order whose supplier has no e-mail address, or whose mail fails, is named and stays unsent. |
| N140 | The document sent is the page *Print* shows, attached as an HTML file, not a PDF. | Minor | Fixed (gaps after Q): the server lays the page out as an A4 PDF itself (`engine/scp/connect/pdf.py`: header and address columns, tables sized to their contents and continued on new pages, page numbers; Helvetica, with the rupee sign as "INR"). The PDF goes first and the page beside it as the exact copy. |
| N141 | Delivery schedules of scheduling agreements have no *Send from here* yet, though the server accepts them. | Minor | Fixed (gaps after Q): *Send from here* on a scheduling agreement sends its delivery schedule. New schedule lines already mark it as not sent, so it can be sent again. |
| N142 | A host name could resolve to a public address when checked and to an inside one when read (DNS rebinding). | Minor | By design, recorded: production servers set `SCP_IMPORT_HOSTS`, as the deployment guide says. |
| N143 | *Send from here* has no browser test against a real mail server (the test server sends no mail). | Minor | Fixed (gaps after Q): the browser tests run a second server that sends to a small mail server of their own (`e2e/smtp_sink.py`). `e2e/mail.spec.ts` firms and e-mails a purchase order, sends it again with *Send from here*, has an unknown address refused and checks what the mail server took: sender, recipient, reply-to and the order attached. |
| N144 | The selling settings (default payment terms, tax, credit check, how long quotations hold, what is due to ship) had no place on screen: only a company file could change them. | Minor | Fixed (gaps after Q): *Selling settings* at the foot of *Selling → Customers*, as *Purchasing settings* is on *Buying*. A list of numbers (the reminder days) is typed as "7, 21, 35". |

## Found while building Phase P

P was built against the tests' small plants and the Capacity page used in a real browser on a two-run plant whose one
press was asked for 16 hours on one 8-hour day: one run was moved a day earlier with its date field, the other dragged
onto a day square, and both stayed firm there when the plan was recalculated.

| # | Finding | Severity | Status |
|---|---|---|---|
| N112 | "Expires unused" (from O) and "Lot larger than its shelf life" were not in the worklist's categories, so they landed under orders on Performance. | Minor | **Fixed (P).** Both are inventory; overtime planned and splits to stay within a supplier's capacity are capacity, a follow-up taking over is inventory. |
| N113 | A day on the Capacity chart could be picked only with a mouse: no keyboard or screen reader could open a day's orders. | Serious | **Fixed (P).** A strip of day squares under the chart, darker when fuller and red when over, each a button that opens its day; runs are dragged onto them, or moved with a date field. |
| N114 | Supplier and lane capacity were only flagged ("Supplier over capacity") even with planning within capacity on. | Serious | **Fixed (P).** Within capacity, what a supplier cannot make or a lane cannot carry in a week goes to the next valid source, else to earlier weeks, and only what fits nowhere is ordered over the limit (and flagged). |
| N115 | Taking a made-to-order order now makes its production firm at once (R13), so the zone's firming afterwards finds the purchases only: the manufacturing journey expected three orders to firm and found two. | Minor | By design, recorded: the saved message names the run made firm ("Made firm for it: PRD-…"); *promise_firms* off leaves it to the planner. The journey checks the new behaviour. |
| N116 | The plan's capacity exceptions are weekly: a day over capacity inside a week with room does not raise "Over capacity", though the Capacity page shows it red. | Minor | Fixed (gaps after Q): the plan checks each day of a week that has room against the day's shifts and overtime and raises "Over capacity on a day" (`CAPACITY_DAY_OVERLOAD`) with the first day, the number of days and the worst; Situations and the worklist show it under capacity and link to the Capacity page. |
| N117 | Overtime is a levelling choice in the supply plan, but not yet a choice of the shop floor optimiser, which still keeps to the shift hours. | Minor | Fixed (gaps after Q): *Schedule → Settings → overtime* lets the schedule (dispatching, local search or optimiser) use each machine's overtime hours after its last shift: the window is scheduled with and without it and the overtime schedule is kept only when it lowers the weighted objective. The result names the hours per machine, their cost and the objective without overtime; the Schedule page shows them. |
| N118 | Measured yield is worked out per production version and part from orders whose parts were posted as used; backflushed orders only repeat the bill of materials and are left out, as are parts through a phantom assembly (their loss is the phantom's). | Minor | By design, recorded: *Parts used* on Actuals says which orders it counted. |

## Found in the health check of 8 October 2026

Main at 10b00bb (after PRs #21–#36) was checked in full: the engine suite, lint, the examples, the API types, the build
and every browser test. Then the Kaveri example was opened as a signed-in owner, kept on the server, and every page
and tab was looked at on a desktop and at phone width.

| # | Finding | Severity | Status |
|---|---|---|---|
| N145 | Fourteen places in the rail, plus five links below it, and about seventy tabs inside the pages. A planner had to know whether an order lived under *Orders*, *Selling* or *Actuals*, and setting up was split over five rail entries. | Serious | **Fixed.** Nine places, one per job: Home; Plan (*Demand*, *Supply*); Run the business (*Customer orders*, *Buying*, *Stock & actuals*); Results (*Money*, *Performance*); *Set up*. A job with several pages shows them as tabs across the top: *Customer orders* is *Promise dates* and *Selling*; *Set up* is *Guided setup*, *Products at places*, *Machines & shifts*, *Map*, *Data check* and *Master data*. Routes are unchanged, so old links still work. The data-error count moved to *Set up* and to its *Data check* tab. |
| N146 | *Performance* showed the same open problems twice, as *Exception inbox* (ranked by money) and *Exception worklist* (by owner and age). | Minor | **Fixed.** One *Problems* tab, with a switch: *Ranked by money at risk* or *By owner and age*. |
| N147 | Settings tabs (*Forecast settings*, *Rules & segments*, *Scenario levers* and others) sat in the middle of the working tabs. | Minor | **Fixed.** A page's settings tab sits apart at the end of its row, in lighter type. |
| N148 | The inbox told a late *transfer* to "Bring the production order forward". Its action came from how the product is made, not from the order the problem names. | Serious | **Fixed.** The action follows the order's kind: a transfer is "Ship the transfer now", a production order is brought forward, and a purchase is expedited or switched to a quicker supplier. The overtime and switch-supplier actions name the machine and the supplier, not their ids. |
| N149 | An order shipped this week showed as *delivered* on *Selling* but as an open order with its full quantity on *Orders*. The plan counts it until the week starts and books it. | Minor | **Fixed.** *Promise dates* shows "shipped · booked at the next week start" (or how many were shipped) under the order's status. A new `shipped` field on each promised order carries it. |
| N150 | *Performance* said "5 of 10 measures" beside a tile reading "of 18 KPIs". | Minor | **Fixed.** "5 of 10 graded measures"; the tile says "of 18 measures". |
| N151 | The account, history, versions, connections and data-check pages offered "How this is calculated" for text that explains how saving, versions or messages work. | Minor | **Fixed.** Each says what it explains ("How saving works", "How versions work"...). |
| N152 | At phone width the save state was cut to "Sav", and order numbers broke in two ("SO-" / "88221"). | Minor | **Fixed.** The save state keeps its width; the plan button reads "Plan" on a phone; a document number never wraps. |
| N153 | The whole app loaded as one 1 MB script before the first screen. | Minor | **Fixed.** Pages load when first opened: the first script is 304 KB (95 KB compressed). Two browser tests asked whether the plan needed calculating before the page had loaded; they now wait for the page first. |
| N154 | A fix to the shop-floor scheduler (whole pieces and full batch cycles when an operation is split over machines, and physical send-ahead) stayed on `fix/physical-parallel-scheduling` since 2 October and was never merged. | Serious | **Fixed.** Ported with its 20 tests (`test_parallel_work.py`), alongside main's tools on operations. |
| N155 | The *GitHub Pages* workflow fails on every push to main: Pages is not switched on for the repository ("Get Pages site failed"). | Minor | **Fixed** by the repository owner: Pages is switched on (Settings → Pages → Source: GitHub Actions); the next push to main deploys it. |
| N156 | The longest browser test (a company on the server, two people merging, history, put back) takes about 50 s of its 60 s limit and timed out once on a busy machine. | Minor | **Fixed.** Marked slow, which gives it three times the limit. |

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
| R13 | A promise on new production does not make that production: the run stayed planned (Monday's firming came before the order), was never made, and the order went late at the roll. Nothing on Home pointed to backorder processing, which then brought the order on time. | Serious | **Fixed (K, P).** Taking or changing an order promised on new production, or made to order, makes that production (and the transfers bringing it) firm at once, as SAP's capable-to-promise does, and says which ("Made firm for it: PRD-…"); purchases stay with Buying. A company rule turns it off. |
| R14 | Home repeated "3 places would go below zero" every week for dips weeks old that the stock had come back from, and for dips a count had settled. | Serious | **Fixed (K).** A dip is reported while it lasts, or when it began in the week just closed and no count ended it. |
| R15 | Shelf life never limits the plan: catering paneer (7 days) made in batches of 100 covering 10 days; "May expire" is a tag, but lot sizes, batch rounding and "a week's need" ignore it, and nothing expires in stock. | Serious | **Half fixed (O):** a product with a shelf life is kept by batch with its expiry date, issued first expiring first out; stock that will expire before it is used is a requirement in the plan ("Expires unused", STOCK_EXPIRES), expired stock is no longer counted and is flagged to scrap. **Fixed (P):** lot sizes and batches stay within shelf life (N109). |
| R16 | A short milk delivery (85 %) is posted "closed 769 short", but the firm runs that needed it are not flagged; posting them in full takes raw milk to −2,307, and the roll sets it to 0. | Serious | **Fixed (O).** A receipt names the firm orders the part no longer covers, in the order they start, with what each can still make, and shortens one with a click (its parts in proportion); on Actuals and on Buying. |
| R17 | Raw milk ends every week slightly negative (−306): the plan buys exactly what the runs need and any yield or rounding takes it below zero; nothing suggests a buffer. The roll's "set to 0" leaves the journal and the plan disagreeing until someone counts. | Serious | **Half fixed (O):** stock below zero is a company rule: refuse the posting, allow it and ask for a count (the plan starts from zero and says so), or count the missing stock as found when the week moves on, so the journal and the plan agree. **Fixed (P):** each part's loss is in the bill of materials (component scrap), and *Parts used* on Actuals measures it from the orders posted with actual usage, beside what the bill of materials plans with, and writes it in with one click. |
| R18 | A person conflicts with their own save: a reload while a save is in flight is refused next time as "Ravi saved … after your changes began", shown to Ravi. | Serious | **Fixed (L).** Each browser window has its own id sent with every save; a save refused only because of saves from the same window (a reload while one was in flight) is taken as one's own, and the same person in another window is merged, never shown as a colleague. |
| R19 | History keeps a state to put back only every ~10 minutes per person, so "just before the release" was not there; *Undo* is gone after a reload. | Serious | **Fixed (L).** Every save is kept (as the changes from the one before, with a full copy every 25), so *History* can put back any of them; undo steps are kept in the browser and survive a reload. |
| R20 | Firming makes purchase orders after the day's orders were sent on *Buying*; they wait "to send" until someone goes back. | Serious | **Fixed (N).** Firming's result offers "Send the N purchase orders now"; orders still to be released wait and are named. `POST /api/orders/firm` takes `send`. |
| R21 | Demand events are entered only in Master data; *+ New event* saves at once an event on every product at every place with the measured lift. | Serious | **Fixed (P).** A series' events are on the Demand page, beside its forecast, added for that series only and starting with no lift until one is typed. |
| R22 | Two numbers called accuracy: Home "92 % accurate on past weeks" (backtest), Actuals "73 % against real sales". | Minor | **Fixed (L).** Home says "accurate on past weeks (backtest)" and, once weeks are rolled, "against real sales" separately. |
| R23 | One negative count refused all three counts; the count grid showed a negative book stock (−905) as the suggested count. | Minor | **Fixed (K).** A negative count is flagged before saving; a stock below zero is marked and suggests 0. |
| R24 | A viewer's Home said "Nothing calculated yet" while its first calculation ran. | Minor | **Fixed (K).** "Calculating the plan from the latest save…". |
| R25 | Event lift said "0.3 = +30 %" on a field typed in percent (also the override change and the forecast interval). | Minor | **Fixed (K).** |
| R26 | Backorder processing told the planner to "simulate … then commit"; the buttons are *Re-decide who gets scarce stock* and *Save these new promised dates*. | Minor | **Fixed (K).** |
| R27 | Master data tables and record headers show ids; the index shows a table's problem count where its row count goes ("Planning policies 3" for 16 rows); "Where used" truncates a source id. | Minor | **Fixed (L).** Tables show names (the id on hover), the index shows each table's row count with its problems beside it, and *Where used* names records in words. |
| R28 | Signed in, *Create the company* still makes a browser-only company; keeping it on the server is a second step. | Minor | **Fixed (L).** Signed in, *Create the company* makes it on the server. |
| R29 | Setup never asks shelf life or make to order; forecast settings are labelled "Abc a", "Xyz x" and list models by code; *Upload sales history* opens a table where the upload is another button. | Minor | **Fixed (L).** Setup asks a product's group, how many days it keeps and, for a finished good, whether it is made to order; forecast settings and models are in words; *Upload sales history* opens the upload. |
| R30 | No refrigerated route mode; the cold chain is "Truck (full load)". | Minor | **Fixed (O).** *Refrigerated truck* is a mode; a product *kept chilled* on a route planned without one is flagged (COLD_CHAIN_LANE). |
| R31 | Smaller: Actuals before a roll says movements run "up to" the start when they run to the week's end; the merge banner takes the page's own message slot; an order promised in two lines on the same day lists the day twice; a raw-milk PO line keeps 12 decimals in the data; the promotion check starts only with the first release after it existed. | Minor | **Fixed (L).** Actuals names the latest movement date and the weeks; one line per promised day; purchase quantities are rounded to three decimals. The promotion check still starts with the first release after K (by design: an older release does not record its inputs). The merge note taking a page's message slot did not come back in L's use (not reproduced). |

What held up: building a dairy from nothing (network, products with batches and a made-to-order line, suppliers with
currencies, two years of history), buying and sending every week, firming, posting a week of receipts, production and
transfers in minutes, the weekly roll, the promotion once it was in, backorder processing, the viewer on a phone (no
sideways scroll, no change buttons), and three people working on one company without losing a change once R6 was fixed.

## The next plan (after Phase O)

Every finding of the first two reality checks is fixed, and every critical one of the third (K). L made the platform
fit for a real company of a few hundred products, S for one of thousands: a company of 5,000 products at 20 places
opens in a second and a half, every page in seconds, and *Plan everything* is the server's calculation and little else.
O made stock traceable: batches that expire, stock types, short receipts, stock below zero as a rule, reversals and
physical inventory. What is left is K's open findings (R13, R15 and R17's planning halves, R20, R21) and breadth
against SAP (the gaps below). Proposed, in the order recommended:

- **K: third reality check, over weeks, not a day**: **done**, see R1–R31 above.
- **L: platform for real use**: **done**, see R18, R19, R22, R27–R29, R31, N63–N65, N76 and N77–N91. A save is never
  refused as someone else's when it is one's own (R18); every save can be put back and undo survives a reload (R19);
  saves send only what changed (N64); a clash is chosen record by record (N65); a forgotten password by e-mail or
  from the owner, and single sign-on (N63); rights by plant or product group; master data approved by a second
  person; change documents with every field's old and new value; nightly backups and a restore; a new company kept
  on the server when signed in (R28); the minor sweep (R22, R27, R29, R31, N76). At 5,000 products × 20 places the
  forecast went from about 40 minutes to 2¼, the checks after each change from 22 s to 7 s, and *Plan everything*
  plans once instead of six times. A container, Compose with HTTPS, and [the deployment guide](DEPLOY.md).
- **S: large companies**: **done**, see N77–N78, N89 and N92–N101. Planning calls name the company's save and send
  only unsaved changes; the server keeps the company read and every answer, compressed and packed; the plan comes
  without its pegging, which a page asks for; long lists draw their first rows with a search; names, edits and local
  copies no longer cost the whole company each time; safety stock by independent groups on every core; a forecast
  after a change competes only the series whose history changed; a large company is planned one at a time.
- **O: stock you can trace**: **done**, see R15–R17, R30 and N102–N110. Batches with an expiry date, issued first
  expiring first out, and stock that will expire unused a requirement in the plan (R15); a short receipt names the firm
  orders it leaves short and shortens them (R16); stock below zero as a company rule (R17); stock in quality inspection
  and blocked, released, blocked and scrapped; stock in transit shown at the place it goes to; material documents and
  their reversal; physical inventory documents with the book frozen and postings held; serial numbers; a refrigerated
  route mode and the cold-chain check (R30).
- **P: planning depth**: **done**, see R13, R15, R17, R21 and N109–N118.
  Capable-to-promise that creates the planned order it promised on, firm, as SAP does (R13); lot sizes and batches
  that stay within shelf life (R15); yield in the bill of materials so a part is bought with the loss in it (R17);
  demand events on the Demand page, a new one starting without effect (R21); MRP groups; withdrawal from another
  plant and direct production; a discontinued product with its follow-up; alternative BOMs; overtime as a levelling
  choice (the schedule's followed after Q, N117); supplier and lane capacity in planning; steps needing a machine and a tool
  together; dragging orders between days to level.
- **M: order to cash, complete**: **done**, see N119–N126. Orders with several lines, each priced from the
  customer's price at its quantity scale (else the product's) less the customer's discounts; payment terms with a cash
  discount; a credit limit that holds an order for delivery until it is released; an order confirmation to print or
  e-mail; quotations won into orders at their prices; deliveries picked, packed, shipped (one material document) and
  signed for; invoices with tax, payments and the cash discount; returns into quality inspection and credit notes;
  what each customer owes.
- **N: procure to pay, complete**: **done**, see R20 and N127–N133. Firming offers to send the purchase orders it
  created (R20); supplier invoices checked against the order and the goods received (three-way match), blocked and
  released, paid with the cash discount; what is owed to whom and what was received but not invoiced; contracts that
  price the orders made under them; scheduling agreements whose delivery schedule planning extends; a supplier's
  confirmation in several deliveries that planning expects one by one; returns to the supplier, replaced or credited;
  a release strategy of several levels with named approvers and four eyes; payables and receivables in the worklist.
- **Q: connected to the rest of the company**: **done**, see N134–N143 and [the integration guide](INTEGRATION.md).
  - Keys for an ERP or a script, in one company as a planner or a viewer.
  - Customer orders matched by the ERP's number, stock, goods movements by the ERP's own order numbers, and master records. Each is saved as a revision by the key and merged into open windows. A message sent twice is not applied twice.
  - Released purchase, production and transfer orders for the ERP to take and acknowledge with its numbers.
  - Every message logged with what became of each line.
  - Scheduled imports from a web address or a server folder (CSV with SAP column names, or JSON).
  - Documents e-mailed from the server to addresses the company knows, an outbox, and worklist reminders.

Order after O: **P, M, N, Q**. All four are done. Proposed next: a fourth reality check over a month with an ERP connected. It would be run the way K was, logged as R-findings, and would be the first to use imports and keys day to day. The breadth below would follow it. P stays ahead of M and N for K's reasons: every open serious finding of K left is about
stock that is really there (shelf life, short receipts, stock below zero) or a plan that acts on it.

## Gaps against SAP recorded for later phases

- MRP views: MRP controller, procurement type (E/F/X), phantom (special procurement 50) and the scheduling margin
  (float before and after production) are in (**B**); MRP groups, withdrawal from another plant, direct production
  and discontinuation with a follow-up material (**P**). Still missing: availability check groups, other special
  procurement keys (consignment, production in another plant).
- Work centres: named shifts with breaks and weekdays, capacity changes over time, per-unit availability (**B**, done).
- BOM and routing: date-effective lines (engineering change), fixed quantities, phantoms, co- and by-products with
  cost shares, step scrap, overlap (send-ahead), steps done outside by a supplier and alternative machines (**B**,
  done). Alternative BOMs chosen by lot size and yield measured from actual usage (**P**). Still missing: BOM usage
  (engineering, costing), routing alternative sequences, change-number history.
- Capacity: material-aware scheduling along the pegging, schedule dates back into supply and promising, a levelling
  view by day and week, and capacity-constrained MRP with alternative machines (**C**, done). Levelling by dragging
  runs between days, overtime as a levelling choice, and supplier and lane capacity in planning (**P**, done). A daily
  capacity exception in the plan (N116, done after Q).
- PP/DS: strategy profiles, a heuristics catalogue (due date, shortest first, least slack, campaigns, backward),
  a local search, a constraint-solver optimiser choosing machines and sequence, a frozen zone and a drag-and-drop
  board (**D**, done); steps holding a machine and a tool together (**P**). Overtime as a scheduling choice followed after Q
  (N117). Still missing: shift changes as optimiser choices, setup matrices by product (not only group), pegging-aware re-scheduling of dependent
  orders when one moves.
- Inventory management: opening balances, counts with differences, transfers shipped and received with stock in
  transit, production confirmations with backflush or actual usage and co-products (**F**, done). Batches with an
  expiry date (first expiring first out), serial numbers, stock types (quality inspection, blocked) with release,
  block and scrap, stock in transit at the receiving place, material documents and their reversal, physical inventory
  documents with a freeze and a posting block, stock below zero as a company rule (**O**, done). Still missing: batch
  classification and characteristics, restricted-use batches, a batch where-used list beyond the journal's search,
  storage locations and bins inside a place, handling units. Goods issue for a sales order is a posting on the order
  (**G**, done) or a delivery document picked, packed and shipped (**M**, done).
- SD: taking an order with the availability check's promise, order changes promised again, cancelling the rest with
  the order logged, deliveries in part or in full, and customer-specific prices (**G**, done). Orders with several
  lines, prices with quantity scales and discounts, payment terms with a cash discount, a credit limit with a delivery
  block and its release, quotations, an order confirmation, delivery documents (picking, packing, goods issue, proof
  of delivery), invoices with tax and payments, returns and credit notes (**M**, done). Tax per product and its
  CGST, SGST and IGST parts followed after Q (N123). Still missing: surcharges and freight conditions, contracts and
  scheduling agreements with customers, down payments, invoice lists, and consignment stock at the customer.
- MM: supplier purchasing data with a purchasing block, info records with price scales, the source list (fixed
  and blocked), requisitions from MRP, purchase orders with an approval limit, supplier confirmations that planning
  uses, and goods receipts with delivery tolerances (**E**, done). Quality inspection stock (**O**, done). Invoice
  verification (three-way match) with payment blocks and their release, payments with the cash discount, payables
  and goods received not invoiced, contracts and scheduling agreements, several confirmation lines per order line,
  returns to the supplier with credit memos, and a release strategy of several levels (**N**, done). Freight and
  unplanned delivery costs on invoices, subsequent debits or credits (N132) and contract prices in the plan's cost
  (N131) followed after Q. Still missing: evaluated receipt settlement (paying from the goods receipt without an invoice), consignment
  and subcontracting stock at the supplier, and forecast delivery schedules (JIT and forecast releases) on
  scheduling agreements.
- Users and authorisations: accounts, companies with owner, planner and viewer roles, invitations, conflict-safe saves
  with a merge, and a change log per company (**I**, done). Still missing: authorisation by object (a planner for
  one plant or product group only), approval steps (four eyes) on master data changes, single sign-on (SAML or
  OpenID Connect) and password reset by e-mail, locking a record while someone edits it, and change documents with
  every field's old and new value kept for years (the history keeps the first few per save, and a document per
  person per ten minutes).
