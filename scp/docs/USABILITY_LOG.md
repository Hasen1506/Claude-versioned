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

## Built from the ideas list (9 October 2026)

The seven next steps proposed after #20 were built in #37, one commit each, then used on the Kaveri example in a
browser the way the guide reads, input → processing → output:

* *Why this date* (Promise dates → an order): input an open order; the promise engine records where each place's
  supply comes from; output "Mon 26 Oct · Planned order TO-01266 ready with 1,155 Electric kettle 1.5 L at Bhiwandi DC
  · Wed 4 Nov · Delivered from Bhiwandi DC over LN-BHW-ECOM". A planned order that is late names the part it waits for.
* One click on *Problems* (Performance → Problems): input "Add 282.2 h of overtime on Assembly operators"; *Try it*
  plans a copy with 10 h overtime a day instead of 2 h; output money at risk ₹24.16 L → ₹22.97 L, this problem
  ₹1.19 L → gone. *Keep this change* applied it as one undo step; *Undo* took it back.
* What-if (What if… side by side): input three scenarios (assembly line down 14 days; web shop prices +10 % and USD
  +20 %; 10 days of safety stock); output line down −0.7 points of service and +701 late units; prices and USD
  +₹62.91 L of sales value and +₹11.74 L of cost at the same service; safety stock +₹1.21 Cr of stock. *Keep as a
  version* stored the first as scenario V0002 of the working copy, ready to promote.
* Working capital (Performance → KPIs): input sixteen weeks of goods issued and of customer and supplier invoices;
  output DIO on the average stock of the 91 days (with the closing stock beside it), DSO counted back (42.0 days, the
  period average beside it), receivables ₹19.04 L not yet due and ₹9.52 L 1–30 days overdue, and a 12-week
  cash-to-cash trend (329 → 269 days) drawn with its table.

| # | Finding | Severity | Status |
|---|---|---|---|
| N157 | The *web* check of #37 failed: the inbox test read the ranked table's row count after switching to *By owner and age*, when the table could already be gone (expected 0 open problems, found 22). | Serious | **Fixed.** The rows are counted before the switch. |
| N158 | A browser's sign-in answer carried the session token, and a sign-in with a cookie session needed no CSRF token (login CSRF). | Serious | **Fixed.** The token stays in the HttpOnly cookie; a cookie sign-in, sign-up or reset needs the double-submit token. |
| N159 | Panels that read once and then change (members, keys, imports, mail, held changes) each had their own guard against a late read. | Minor | **Fixed.** One `useLatest` hook: the newest answer shown wins. |
| N160 | A promise said when, not why. | Serious | **Fixed.** *Why this date* lists the chain behind the latest confirmed line: stock, a firm receipt, or the planned order and the part it waits for; beyond the lead time; the capable-to-promise steps; then the lane. |
| N161 | The inbox suggested an action and estimated what it protects, but doing it meant another page and a fresh plan to see if it worked. | Serious | **Fixed.** *Try it* on an expedite, a supplier switch or overtime: a copy is planned with the change and the money at risk is shown before and after; kept as one change. What has no one-click version says why ("nothing firm … arrives after …: the late quantity is on planned orders"). |
| N162 | A what-if that won could not be kept, and four common questions had no chip. | Minor | **Fixed.** *Keep as a version*, and chips for a machine down, one customer's prices, safety stock in days and an exchange-rate move; a sales-value row shows a price change. |
| N163 | With a machine down, *Busiest machine* read "—" with a −98 % badge: a week with load and no hours is an infinite utilisation. | Minor | **Fixed.** The busiest week that has hours, and the note names the machine with work in a week with no hours. |
| N164 | Rebuilding the daily stock backwards took Kaveri's opening balances (posted a week before the start) as receipts: before them the stock was nearly nil and the average fell to 416 K against 32.8 M closing. | Serious | **Fixed** before it shipped. An opening balance is stock already there and is not taken back. |
| N165 | DIO and turns swung with one large receipt on the last day; DSO was an average; nothing aged what was owed; no trend. | Minor | **Fixed.** Average stock of the period, count-back DSO, ageing buckets for receivables and payables, a 12-week trend on DIO, DSO, DPO, turns and cash-to-cash. |
| N166 | The CI actions ran on Node 20 (deprecated) and `ubuntu-latest` was due to move on 19 Oct. | Minor | **Fixed.** Actions on their Node 24 majors, runners pinned to Ubuntu 24.04, Node 22 for every build and the Docker image. |

## Enterprise plan, phase 1: running it (10 October 2026)

ENTERPRISE_PLAN 1.1, 1.2, 1.5 and 1.6, used against a local PostgreSQL 16 the way an administrator would:

* *Several server processes* (input: four planners saving the same company at once, ten saves each, through
  `uvicorn --workers 2` on PostgreSQL; processing: every read-then-write under the database's own lock, the save a
  compare-and-swap on the revision; output: 40 saves on 40 revisions, 2 to 41 one after another, 74 refused with
  409 and saved again over the newer revision, 41 history rows). With the lock and the compare-and-swap both taken
  out, the two-process test fails at once (`UNIQUE constraint failed: company_revisions`), so it proves something.
* *Watching it* (input: the same run with `SCP_LOG_FORMAT=json`; output: one JSON line per call with its request id,
  route pattern, status and milliseconds, never a body or a query; `/api/metrics` counted 46 PUT 409 and 21 PUT 200
  on `/api/companies/{cid}` with the time histogram; `/api/health` named the commit, the database and the uptime;
  `X-Request-ID: drive-1` came back as sent).
* *Backup and restore on PostgreSQL* (input: `scp.admin backup` against the live database while it ran; output: one
  file that `check` reads, "1 accounts, d-9 (revision 41)"; `scp.admin restore` into an empty database compared every
  table and committed; a second restore over it was refused; the owner signed in there with the same password and
  revision 13 opened as saved).

Then 1.3 and 1.4 (15 October 2026): two-step sign-in, the download and deleting a one-company account through the screens in a browser; the rest through the API, on SQLite and on PostgreSQL:

* *Two-step sign-in* (input: an owner turns it on with a code their app shows, keeps the ten recovery codes, signs
  out; processing: the password gives only a five-minute ticket, the code finishes it, each code good once; output:
  signed in only after the code, a code used once refused the second time, a recovery code signs in once and the count
  drops to 9, five wrong codes stop codes for 15 minutes). The owner could not require it of the company before having
  it; after, the history said "required of every member; not on yet for planner", the planner saw the company marked
  and was refused opening it until they turned it on, and an integration key went on working.
* *Asking again* (input: a password change, an address change, a reset link, with two steps on; output: each refused
  without the code; the address change told the old address, mailed a confirmation link to the new one and ended the
  other session; the reset link set nothing until the code came too).
* *Their own data* (input: *Download everything*, then *Delete my account* for an owner of four companies, two alone;
  output: one JSON file with each company's data, members, history and plan versions; deletion said first what would
  happen, refused until each company owned alone had a choice, undid everything when one choice could not be done,
  then handed one company to a planner, deleted the other, left the two shared ones, and the histories kept the
  actions under "Deleted account" with no address in them; the address could make a new account afterwards).

| # | Found | Severity | Outcome |
|---|---|---|---|
| N167 | A save was checked against the revision under a lock inside the process: two server processes could both pass the check, and the second wrote the same revision (an error in the log, the planner's change lost). | Serious | **Fixed.** The lock is the database's (advisory lock, or a file lock beside SQLite), and the save is a compare-and-swap. |
| N168 | The scheduled-import clock, the nightly copy and the sign-in failure counter lived in each process: with two, an import would run twice and an address would get ten wrong passwords per process. | Serious | **Fixed.** One process leads each clock (the next takes over when it stops); the counter is a table. |
| N169 | A PostgreSQL connection dropped while idle (Neon sleeps after a few minutes) failed the next request. | Serious | **Fixed.** The connection is made again when the lock is taken, before anything is under way. |
| N170 | Importing the build commit as `commit` in the API module hid the promise engine's `commit` (lint caught it before it ran). | Serious | **Fixed** before it shipped: imported as `build_commit`. |
| N171 | Nothing showed what the server was doing: no request ids, no metrics, health said only "ok". | Minor | **Fixed.** Request ids, JSON logs, `/api/metrics`, an optional Sentry DSN, commit, database and uptime in health (503 when the database is unreachable). |
| N172 | PostgreSQL could not be backed up or restored with the application's own commands, and no restore had been tried. | Serious | **Fixed.** `scp.admin backup` and `restore` work on PostgreSQL; the restore test opens every company at every kept revision. |
| N173 | A production server could start open to anyone (open sign-up, no sign-in), as the live demonstration host does. | Serious | **Fixed** for servers that say `SCP_ENV=production`; the demonstration host's own settings are its owner's to change (DEPLOY.md). |
| N174 | A password-reset link (mailed, or made by an owner) set a new password and signed in by itself: whoever could read the mailbox took the account. | Serious | **Fixed** for accounts with two-step sign-in: the reset asks for the app's code as well, and changes nothing without it. |
| N175 | The sign-in address could not be changed at all, and changing the password asked only for the old one. | Minor | **Fixed.** An address change asks for the password (and code), tells the old address, ends other sessions and leaves the new address unconfirmed until its link is opened. |
| N176 | An account could not take its data away or be deleted, and a company it alone owned would have been left without an owner. | Serious | **Fixed.** *Download everything*; *Delete my account* says first what happens and hands over or deletes each company owned alone, as the holder chooses. |
| N177 | The keys behind the app's codes are readable in the database (a code can only be checked with its key), so a stolen copy of the database gives them away. | Minor | **Open.** Said in DEPLOY.md (keep backups as private as the database); keeping them encrypted with a server key would need a key the server holds outside the database. |
| N178 | The recovery codes were centred in one narrow column, and a refused *require two steps* flicked the checkbox on and off (a browser test caught it as a race). | Minor | **Fixed** before it shipped: codes left-aligned in columns; the test clicks and waits for the box to come back unticked with the reason. |
| N179 | A PostgreSQL row could not be sliced like a SQLite row, so one older test failed when the suite ran on PostgreSQL. | Minor | **Fixed.** |

## Enterprise plan, phase 2: planning against the S/4 guide (15 October 2026)

ENTERPRISE_PLAN 2.1, used in a browser and through the API on a pump plant: 120 casings for a customer order on
Monday 12 January, and the foundry's PO-4501 for 120 due a week later, on the 19th. A new order takes 3 days.

* *Rescheduling horizon* (input: no horizon, then 10 working days on the casing's *Ordering* view, then an MRP group
  "Castings" with 3; processing: a firm order due within the horizon after a shortage is brought in to cover it before
  any new supply is planned; output: without a horizon, requisition PR-00001 for 120 on the 12th beside the PO, which
  is reported as not needed; with 10 working days, no requisition, and *Incoming order needed sooner*: "PO-4501:
  arrives 2026-01-19 but is needed 2026-01-12; expedite it by 7 d (it is due within the 10-working-day rescheduling
  horizon, so it is brought in rather than ordered again)"; with the group's 3, which ends before the 19th, the
  requisition again). The PO keeps its date: the advice is the planner's to act on.
* *Tolerance* (input: a PO six days before it is needed; output: *Incoming order could come later* at the company's
  3 days, nothing at 7, nothing with an MRP group that says 6).

ENTERPRISE_PLAN 2.2, in a browser: a towel warehouse in Bhiwandi that takes a working day to pick and pack and one to
load, shipping to Hotel Sagar 3 days away. 50 towels arrive on PO-77 on Friday 16 January; the hotel wants 10 on
Tuesday the 20th.

* *Delivery scheduling* (input: the two handling times on the warehouse, and a transport-booking time on the route
  when there is one; processing: backward from the delivery date by transit to the goods issue, then loading, then the
  longer of picking and packing and booking the transport, to the date the goods must be there; output: the order's
  lines read *There to pick* Fri 16 Jan, *Leaves* Sun 18 Jan, *Delivery* Wed 21 Jan, late, and *Why this date* says
  "Leaves Bhiwandi warehouse: picking, packing and loading take 2 working days once the goods are there"). Without
  the handling times the same order is confirmed on time, shipped the day the towels arrive. The plan schedules its
  shipments the same way, and a kept confirmation stores the day the goods leave.

ENTERPRISE_PLAN 2.3, in a browser and through the engine: the casing again, with a 10-day planning time fence (to
Thursday 15 January) and the customer's 120 on Monday the 12th.

* *Firming types* (input: the casing's firming type on its *Ordering* view; output: type 3, the default and how the
  fence behaved before, plans the requisition for the fence end, the 15th; type 4 plans nothing inside the fence, the
  product shows *Short inside the freeze window*, the Problems list says "1 product short inside the freeze window",
  and the requisition comes at the first check beyond the fence, Monday the 19th). Types 1 and 2 also firm: rolling
  a week to Monday 12 January with a 7-day fence, the order last week's plan had for the 16th became a purchase order
  due on the 16th; types 3 and 4 left it planned.
* *Working days* (input: the company setting *Time fence and goods receipt in working days*, on for new companies;
  output on a Monday–Friday plant: a 5-day fence from Monday 5 January ends Monday the 12th instead of Saturday the
  10th; goods delivered on Saturday the 10th with two days of goods receipt are there on Tuesday the 13th instead of
  Monday the 12th).

ENTERPRISE_PLAN 2.4, in a browser and through the engine: the casing bought with 10 days' lead time, used 10 a day
for six weeks, weekly CV 0.2, so its buffer is red to 87.5, yellow to 187.5 and green to 257.5.

* *A buffer that places the orders* (input: *Positioned* on *Supply → Buffers → DDMRP buffers*, then *Plans the
  orders*, which sets MRP type ddmrp, also offered on the *Ordering* view as "Demand-driven buffer (D1)"; processing:
  on every day the net flow position can move, on hand plus open supply less what is due and the spikes inside the
  decoupled lead time, and an order of top of green less NFP that day when it is at or under the top of yellow;
  output: with 120 on hand, positioned but planned by requirements, the screen says *Advice only* while the row says
  yellow, order 148; ticked, the plan buys 148 on Monday 5 January, the Problems list says "1 buffer to reorder today",
  and the red zone is the safety stock the projection shows). With 200 on hand the first order is 78 on the 6th and
  the next 80 on the 14th, where planning by requirements orders 10 a day from the 15th. 50 on hand is *Buffer in the
  red*: order 218 today and expedite. A part made to order cannot hold a buffer, and a safety stock beside one is not
  planned: the readiness check names both.

ENTERPRISE_PLAN 2.5, in a browser and through the engine: pump casings bought to order at Pune, 10 days to buy. PO-1
for 50, due Wednesday 14 January, was bought for SO-1 (50 on Tuesday the 20th); SO-2 wants 50 on Monday the 12th; 20
casings in stock are held for SO-3 (Thursday the 22nd).

* *Held for one order* (input: *Held for sales order* on the firm order, or stock held for an order; a requisition or
  production order planned for one customer order of a made-to-order product carries that order when it is firmed;
  processing: what is held for an order goes to that order first and to no other, in planning, promising and the
  journal; output: free, PO-1 went to SO-2 with "expedite it by 2 d" and SO-1 got a new requisition; held, PO-1 stays
  with SO-1, the plan buys for SO-2 (*Planned purchase … for SO-2*), the product's list shows the free stock running
  out on the 12th at −50 and, below it, *Held for sales orders* order by order; SO-1's *Why this date* says "Firm
  receipt PO-1 brings 50 to Pune plant, held for this order"; *Stock & actuals* shows "20 held for SO-3" beside the
  free stock). Received, PO-1 goes into stock held for SO-1, starting the week puts it there in the plan, and SO-1's
  delivery takes it from there; cut SO-1 to 30 and the plan says 20 are held for an order that no longer needs them.
  A held order due after its order is due is to be expedited, with nothing else planned in front of it.

ENTERPRISE_PLAN 2.6, in a browser and through the engine: 40 pump casings at Pune for Kumar Pumps. SO-0 (10, asked for
Friday 2 January), SO-1 (30, Tuesday the 6th) and SO-2 (30, Wednesday the 7th), imported without prices; the casing
sells at 1,500.

* *The delivery checks the stock* (input: *Make deliveries*; processing: unrestricted stock at the shipping place plus
  firm receipts in by the planned goods issue, less what open deliveries take, first to ship first served, stock held
  for another order left alone; output: *Due to ship* has a *Can be picked* column — SO-0 10, SO-1 30, SO-2 *none in
  stock*, left unticked; ticked anyway, the delivery is made for SO-0 and SO-1 and says "SO-2: nothing of 30 can be
  picked (Pump casing at Pune plant by Mon 5 Jan), it stays to deliver"; inspection or blocked stock is named with
  "release it first"). *Check stock when a delivery is made* in the selling settings switches it off.
* *The price is fixed when the goods leave* (input: *Ship it*, or a delivery posted on the order; output: "SO-1 had no
  agreed price: INR 1,500.00 a unit fixed at goods issue"; the line now carries that price, at its quantity scale, and
  the invoice uses it whatever the price list says on the invoice day). A line with its own price keeps it.
* *Late and not shipped* (output: the OTIF notes on *Performance* say "Not in this figure: 1 open order line worth INR
  15,000 already past the requested date and not delivered; they count once they close", and the same against the
  confirmed date).

ENTERPRISE_PLAN 2.7, in a browser and through the engine. Kumar orders a kit from Pune: a pump (10 in stock) and a motor
(none; 20 arrive on PO-7 on Wednesday 14 January); pumps and motors are the PUMPS family.

* *One delivery for a whole order* (input: *Ship the whole order together* on the order form, or `single_delivery` on an
  imported order; processing: each line is confirmed in full, then every line moves to the date the last one can come,
  or no line is promised; output: "10 Pump promised 10 on Thu 15 Jan; 20 Motor promised 20 on Thu 15 Jan. One
  delivery: every line on Thu 15 Jan"; a line the order cannot get in full keeps the whole order unpromised, and says
  so). The pump's 10 stay free for other orders until the 15th.
* *Allocations by family, the customer's own first, carried forward* (input: an allocation names a product or a
  family, and may carry forward; processing: the family's cap is checked before the product's, a customer with
  allocations of their own is held to them and not to the one for everyone else, and a period that carries forward adds
  what earlier periods left; output: *Promise dates → Allocations* shows "family PUMPS · carries forward · 30 / 100"
  beside "Motor · 20 / 50").
* *Optimising lot sizes* (input: *Part-period balancing*, *Least unit cost* or *Groff's rule* as the lot-size rule,
  with an ordering cost; processing: the lot covers the coming periods while holding stays within an order's cost, the
  cost per unit falls, or Groff's rule holds; output: for 100, 60, 40 and 100 a week at 10 an order and 0.01 a unit a
  day, part-period balancing orders 200 and 100, least unit cost 160 and 140; without an ordering cost or a value it
  orders lot for lot and says so).

| # | Found | Severity | Outcome |
|---|---|---|---|
| N183 | Only one firming rule existed: a plant that must not get automatic orders inside its fence got them moved to the fence end anyway, and nothing was firmed as the fence moved over the plan (§8.5). | Serious | **Fixed.** Firming types 1–4 on the product or MRP group; 2 and 4 plan nothing inside the fence and report the shortage; 1 and 2 firm the fence's orders at the roll, as last week's plan had them. The default, 3, is how the fence behaved before (its description called it type 1, which it was not: nothing was firmed). |
| N184 | The planning time fence and goods-receipt time counted calendar days, so a Friday receipt with two days of goods receipt was available on Sunday. | Minor | **Fixed** for companies that count working days: new companies do; saved companies keep calendar days until the setting is switched on (it moves their dates). |
| N188 | Make-to-order supply could be taken by another order: a PO bought for one customer order was expedited for an earlier one, and the first got a new order (§16.2, §9.2). | Serious | **Fixed.** Sales-order stock: firm orders and stock held for one sales order, planned, promised and issued only to it; firming carries the order from the plan; the journal keeps held stock apart from free stock. Companies without held supply plan as before. |
| N189 | The product's running list counted stock held for another order as available, so a shortage of 50 read as 30. | Minor | **Fixed** before it shipped: the list and the plan's projection are the free stock; what is held is shown order by order below it. |
| N190 | Stock planned to expire was left out of the requirements once held supply was taken out of netting. | Minor | **Fixed** before it shipped (a test caught it): requirements added while a product is being netted join both lists. |
| N186 | A DDMRP buffer only advised: its zones and order showed on the buffer screen while MRP planned the same part by net requirements, two signals that disagree (§8.7 pitfall). | Serious | **Fixed.** MRP type ddmrp (S/4 D1): the buffer's net flow places the planned orders, red and yellow buffers go to the Problems list and the inbox, and the buffer screen marks a positioned part still planned by requirements as advice only. Other MRP types plan as before. |
| N187 | The red and yellow buffer situations pointed to "Inventory → DDMRP buffers", a name the navigation does not use. | Minor | **Fixed** before it shipped: "Supply → Buffers → DDMRP buffers". |
| N185 | Automatic firming at the roll first firmed an order on time for the 16th as one moved to the new fence end, the 19th: the plan is worked out afresh, so the order last week had was gone. | Serious | **Fixed** before it shipped: the rolled company is planned with each fence ending where it ended last week, and what starts inside the new fence is firmed. |
| N191 | A delivery was made for whatever was asked, stock or not; the shortfall showed only at goods issue, after picking (§13). | Serious | **Fixed.** The delivery takes what can be picked by its goods issue and leaves the rest to deliver; the list says what can be picked before the delivery is made. |
| N192 | A line without an agreed price was billed at the list price on the invoice day, without its quantity scale (§15 pitfall, pricing type B). | Serious | **Fixed.** Its price is fixed at goods issue, at its scale, and billed at that. |
| N193 | OTIF counted only closed orders: a backlog of late lines not yet shipped was in no figure (§18.2). | Minor | **Fixed.** The OTIF notes give the count and value of open lines already past their requested and confirmed dates. |
| N194 | The deliveries list showed nothing until *Calculate*, though the company had just been imported with lines due to ship. | Minor | By design: every page with a *Calculate* button calculates on request; noted only. |
| N195 | A kit's lines were promised one by one: the pump for the 7th, the motor for the 14th, two deliveries to a customer who wanted one (§7.2). | Serious | **Fixed.** An order can ship as one delivery: every line on the date the last can come, or none. |
| N196 | Allocations had one level: no family cap, a catch-all applied to customers who had their own, and what a week left unused was lost (§7.4). | Serious | **Fixed.** Family before product, the customer's own allocations before the catch-all, carry-forward per allocation. |
| N197 | EOQ was the only optimising lot size, poor for lumpy demand (§8.3). | Minor | **Fixed.** Part-period balancing, least unit cost and Groff's rule, holding each requirement from its own date. |
| N198 | The kit test company first had no source for the pump, and taking the order said only that the data has problems. | Minor | Open: the order form could name the problem (here "Pump has no way to be supplied") instead of pointing to Home. |
| N199 | A one-click what-if waited 5 seconds in its browser test for a plan run, and failed once under load. | Minor | **Fixed** in the test: it waits as long as the other plan runs. |

| # | Found | Severity | Outcome |
|---|---|---|---|
| N180 | A firm order due a week late was duplicated by a new requisition whenever a new order could still arrive on time, and the firm order was then called not needed (§8.1). | Serious | **Fixed.** A rescheduling horizon in working days (company setting, product, MRP group): within it the firm order is brought in first. The company default is 0, as in S/4 when none is set, so saved companies plan as before until a horizon is given; the not-needed situation now points to it. The reschedule-out tolerance (3 days) is a setting too. |
| N181 | "Nothing needs them before the horizon ends" read as the new rescheduling horizon. | Minor | **Fixed.** It says *planning horizon*. |
| N182 | A warehouse that needs a day to pick confirmed every order a day too early: the promise shipped goods the day they arrived, with no picking, packing, loading or transport booking (§6.2). | Serious | **Fixed.** Picking and packing and loading times on the shipping place, transport booking on the route, all in working days (0 by default, so nothing moves until they are set); stock is checked on the material availability date, and the line and the confirmation carry the goods issue. |

## Enterprise plan, phase 3: connectors (15 October 2026)

ENTERPRISE_PLAN 3.1, in a browser and through the engine. Kaveri keeps its stock in Tally: the closing stock sheet has
Tally's item codes (`MG500`), its godown names (*Pune Works*) and quantities in dozens. A web shop sends its orders as
JSON, an order per object with its lines inside, its own customer codes and dates written `08 Jan 2026`. A warehouse
system answers page by page and can give only what changed after a time.

* *Mapping* (input: on *Connections → Scheduled imports*, *Name the fields myself*: place from `Godown` with
  `Pune Works=PLT-PUNE`, product from `Item Code` with `MG500=MG-500`, quantity from `Closing Qty (doz)` × 12; for
  the shop, records at `orders`, one row per element of `line_items`, product from `line.sku`, the date from
  `note_attributes.deliver_by` written `%d %b %Y`; processing: each field here is filled from the column or path named,
  codes translated, numbers multiplied, dates read as written, the rest as a recognised file is; output: PLT-PUNE /
  MG-500 120). A field named that is not a field here is refused with the fields there are.
* *Try it first* (input: a few lines pasted in, or nothing to read the source now; processing: the message is applied
  to the company's latest save and nothing is saved, logged or moved; output: "Dry run, nothing saved: 2 stock: 1
  taken, 1 refused", each line "would be taken" or refused with why (*there is no place 'Mumbai Depot'*), the columns
  found in what was read, and the first rows as the fields here). A saved import has *Dry run* beside *Run now*: a
  file in the folder stays where it is and the schedule is as it was.
* *A web API, page by page, only what changed* (input: from *a web API*, the next page's address at `links.next` or
  numbered pages until a flag says there are no more, `{since}` in the address; processing: the pages are read into one
  message, the key goes only to the API's own host, `{since}` is the start of the last good run; output: one message
  for every page; the next day only what changed is asked for). A failed page fails the run: half an answer is never
  taken and the time is not moved on.
* *The log keeps what was read* (output: *Messages → What was read (the start)* shows the first 2,000 characters of the
  file or answer, also for a file that could not be read).

| # | Found | Severity | Outcome |
|---|---|---|---|
| N200 | Imports recognised columns only by their names: a Tally sheet (`Item Code`, `Godown`, quantities in dozens) or a shop's nested JSON could not be read, and codes that differ from ours had to be changed in the other system first. | Serious | **Fixed.** A mapping per import: column or path, codes translated, a factor, a date format, a value when empty, one row per element of a list. |
| N201 | An import could only be tried by running it, which saves what it read. | Serious | **Fixed.** *Try it* before saving (a sample or the source) and *Dry run* for a saved import: nothing saved, logged or moved. |
| N202 | A web API that pages its answer was read one page at a time, and every run read everything again. | Serious | **Fixed.** Pages by the next page's address or by number, at most a set number (more fails the run); `{since}` is the last good run's start. |
| N203 | A refused file left no trace of what it held: the log said "not a list of records" and nothing else. | Minor | **Fixed.** The log keeps the start of what was read with the message. |
| N204 | The mapping table offered a date format and a factor for every field, the place and product included. | Minor | **Fixed** before it shipped: a factor only for numbers, a date format only for dates (any field of master data). |
| N205 | The form sends only an `Authorization` header; an API with its own header (Shopify's `X-Shopify-Access-Token`) can be set only through the API. | Minor | **Fixed** (3.2, 3.3): Zoho, Shopify and Odoo have their own credential fields, sent in each system's own way. A generic web API with its own header is still set through the API. |
| N206 | An API that names its next page in a `Link` header (Shopify) cannot be paged, since only the body is read. | Minor | **Fixed** (3.3): *Pages: the Link header names the next page*. |

### 3.2: Tally Prime and Zoho Inventory (16 October 2026)

ENTERPRISE_PLAN 3.2, through the engine and in a browser. Kaveri's books are in Tally Prime; a second company sells
through Zoho Inventory. Neither was at hand, so each was played by a server answering as its documented interface
does (Tally's XML envelopes, counts and `LINEERROR`s; Zoho's JSON with `code`, `page_context` and OAuth tokens): the
connectors are checked against those formats, not yet against a running Tally or a live Zoho organisation.

* *Tally's stock items, ledgers, stock and sales orders* (input: *Connect Tally*, Tally's address, the company's name
  in Tally, the place its stock is at, *Translate codes* `Tin White 1L=TIN`; processing: the export envelope asks for
  the collection, the answer's names become codes here, translated where the mapping says; output: products with
  Tally's stock group as family, customers and suppliers from Sundry Debtors and Creditors with address and GSTIN, the
  closing balance counted at the plant, sales order vouchers as customer orders a line per due date). *Try it* reads
  Tally now and shows each line and the rows as the fields here before anything is saved.
* *Purchase orders to Tally* (input: *What it brings: purchase orders to send*, the supplier's ledger translated;
  processing: a purchase order voucher numbered as here, with each line's due date, rate and the purchase ledger;
  output: "1 purchase order to Tally: 1 sent", *made in Tally as PO-00001* in Messages, the order taken, and the next
  run "nothing to send". Changed here: the voucher is altered; cancelled or deleted here: cancelled. Refused by Tally
  (*Ledger 'Sharma Metals' does not exist!*): said on the line, nothing kept, sent again next run).
* *Zoho Inventory* (input: *Connect Zoho*, the organisation ID, the data centre, a self client's ID, secret and refresh
  token; processing: one access token an hour, pages of 200, sales orders newest first until one older than the last
  good run, each read whole; output: as Tally's, and purchase orders made with Zoho's item and vendor IDs). The secret
  is not shown again: *Change* shows "kept as it is".

| # | Found | Severity | Outcome |
|---|---|---|---|
| N207 | A code translation with no column named was dropped when the import was saved: the form kept a row only when it named a source or a value, but for a connector "the same field" is the usual case. Found by the browser test (Tally's `Tin White 1L` reached the dry run untranslated). | Serious | **Fixed.** A row with codes is kept. |
| N208 | Connectors' rows are typed already: the mapping table offered a factor and a date format to them. | Minor | **Fixed.** Hidden for Tally and Zoho; *From* reads "the same field". |
| N209 | A new product from Tally or Zoho would have changed a product kept here: type, unit and family sent on every run. | Serious | **Fixed** before it shipped: those fields (a place's type and region too) are taken only by a new record. |
| N210 | An order sent and taken, whose answer was lost (a timeout), would have been made twice on the next run. | Serious | **Fixed** before it shipped: the connector asks Tally (an export by voucher number) or Zoho (by `purchaseorder_number`) first and then changes it. |
| N211 | Tally's stock is read item by item as one total at one place: godown-wise closing stock is not read. | Minor | Open: Tally's godown-wise closing needs a TDL report; to be done against a running Tally. |
| N212 | Zoho's stock is the item's total, not per warehouse or location (Zoho gives that only item by item, which its call limits make slow). | Minor | Open. |
| N213 | Goods movements are not read from Tally (receipt notes, delivery notes, stock journals) or Zoho (receives, packages). | Minor | Partly fixed (3.3): Shopify's fulfilments are read as deliveries. Tally, Zoho and Odoo still count stock instead. |

### 3.3: Shopify and Odoo (16 October 2026)

ENTERPRISE_PLAN 3.3, through the engine and in a browser. A second company sells online through Shopify and
keeps its books, bills of materials and purchasing in Odoo. Again neither was at hand: each was played by a server
answering as its documented interface does (Shopify's GraphQL `nodes`/`pageInfo`, `THROTTLED` errors and its token
header; Odoo's JSON-RPC `authenticate` and `execute_kw`, its domains, many-to-one pairs and errors, and the JSON API
of Odoo 19). The connectors are checked against those formats, not against a live shop or database.

* *Shopify's catalogue, locations and stock* (input: *Connect Shopify*, the shop's myshopify.com address, a custom
  app's token; processing: variants read a page at a time, the SKU (else the titles) as the code, each location's
  on-hand stock by location; output: products in the product type's family, the locations as warehouses, stock at
  the place each location is translated to, or of its own name).
* *Shopify's orders and fulfilments* (input: *What it brings: customer orders*, *Booked to the customer: Online
  shop*; processing: orders updated since the last good run, each line's quantity after edits; output: order 1001 of
  the online shop with the buyer's name as its note, a cancelled one never taken; then *fulfilments (as deliveries)*:
  2 delivered from line 10, the same fulfilment never posted twice).
* *Odoo's products, partners and BOMs* (input: *Connect Odoo*, its address, the database, a login and API key;
  processing: JSON-RPC as that user; output: products without services, customers and suppliers by rank, each BOM a
  way to make at the plant named with its components, the steps here kept).
* *Purchase and manufacturing orders to Odoo* (input: *purchase orders to send*; processing: Odoo's vendor and
  product found, *Try it* first: "would be made in Odoo (Sharma Metals)"; output: "1 purchase order to Odoo: 1 sent",
  made and confirmed with PO-00001 as its source document, kept as P00201, the next run "nothing to send". Changed:
  its line rewritten in place. A manufacturing order: made with Odoo's start field and confirmed, a new quantity
  through *change quantity*, deleted here cancelled there).

| # | Found | Severity | Outcome |
|---|---|---|---|
| N214 | A summary of one item read "1 orders: 1 taken". | Minor | **Fixed.** "1 order", "1 purchase order", "1 location". |
| N215 | On a phone the four *Connect* buttons ran off the panel. | Minor | **Fixed.** They wrap. |
| N216 | A sending job's *Try it* offered a sample box that sending never reads. | Minor | **Fixed.** Sending says what a dry run does instead. |
| N217 | An Odoo stock quant below zero (stock sold before it was received) would have refused the warehouse's whole row. | Minor | **Fixed** before it shipped: quants are summed by warehouse first, and a total below zero counts as none. |
| N218 | Shopify keeps no purchase or production orders, so nothing planned here can go to it. | Minor | By design: a shop that buys through Odoo or Zoho sends its orders there. |
| N219 | A partner in Odoo who is both a customer and a vendor becomes one place here (the bigger rank). | Minor | Open: one place can be both only with two ids; translate the second by hand. |
| N220 | Shopify's buyers are one customer here, so promises and margins are per channel, not per buyer. | Minor | By design for a shop; B2B buyers come through an ERP. |
| N221 | Odoo's lots and Shopify's per-location committed stock are not read; stock is on hand only. | Minor | Open. |

## Enterprise plan, phase 4: demand and S&OP depth (16 October 2026)

### 4.1: The monthly S&OP cycle

ENTERPRISE_PLAN 4.1, through the engine and in a browser: the Kaveri Kitchenware example in this browser, and a small
company kept on the server by a signed-in owner. The example now carries the year's budget by product family.

* *Budget* (input: Data → Budgets, a month's units and revenue for the mixer grinders and the kettles; output: a
  table with the month, what it is for and both figures).
* *The cycle* (input: Capacity plan → Monthly cycle, *Start the October 2026 cycle*; processing: five steps, each
  signed in order; output, step by step):
  1. *Data*: no blocking problems, 0 warnings, sales history to 21 September; signed.
  2. *Demand review*: the demand plan month by month against the budget. October is 20,697 units against 20,750
     (−0.3 %), but +6.2 % in revenue: more mixer grinders, fewer kettles. The six months are 4.8 % under the budget
     in units, and kettles are 5.6 % under. Signed: the company as it stood was kept as plan version V0002.
  3. *Supply review*: the capacity plan, solved by month, supplies 100 % of that demand. Signed.
  4. *Pre-S&OP* would not sign without its minutes; signed with "Kettles below budget in Q1: promotion proposed for
     January".
  5. *Executive S&OP*: signed with the decision, which closed the month.
* *Through the month* (output: a table with one row per signed step: units and revenue planned against the budget,
  how much was supplied, and the plan version each step was kept as).
* *Reopened* (input: the supply review, "Copper supplier cut its November capacity"; output: the supply review,
  pre-S&OP and the executive step open again, their versions kept, the log saying who reopened them and why).
* *In a company* (the owner names the demand review's owner from the members; the sign-offs carry their e-mail. In
  the engine: a planner cannot sign another's step, a viewer signs nothing, and an executive step with no owner takes
  an owner of the company. Next month's cycle starts with the same owners.)

| # | Found | Severity | Outcome |
|---|---|---|---|
| N222 | After a sign-off the page stayed on the signed step; the next step's button was one click away and easy to miss. | Minor | **Fixed.** A sign-off moves on to the next step. |
| N223 | Reopening a step of a closed month answered with the month still closed. | Major | **Fixed** before it shipped (a test caught it): the answer is read after the change. |
| N224 | With a demand lever on the capacity plan (demand × 1.5), the supply review showed more supply than demand. | Major | **Fixed.** The supply steps show the demand that plan supplies, and say it is scaled. |
| N225 | A plan starting on 5 October set 27 days of demand against a whole month's budget. | Major | **Fixed** before it shipped: a month partly inside the plan counts that part of its budget ("from 5 Oct 2026"), and says so. |
| N226 | On a phone the month names wrapped onto four lines. | Minor | **Fixed.** |
| N227 | An executive step without an owner can be signed only by an owner of the company. | Minor | By design: the plan the business runs on is approved by someone who answers for the company. |
| N228 | Signing a supply step solves the capacity plan again on the server; at 5,000 products a sign-off waits as long as the plan. | Minor | Open: reuse the page's last solve of the same data. |
| N229 | A budget is by month for a product, a family or the company; not by customer, region or channel. | Minor | Open. |

### 4.2: Forecast value add

ENTERPRISE_PLAN 4.2, through the engine and in a browser: the Kaveri Kitchenware example, which now carries twelve
weekly forecast releases from before its planning start (each the real forecast from the sales known that Monday,
with two planners' overrides of the time), and a small shop imported as a file whose answers were worked out by hand.

* *Kept forecasts* (input: every press of *Use this forecast in the supply plan*; output: Data → Kept forecasts, one
  row per product, place and week from the value-add lag on (default one week ahead): the naïve forecast, the
  statistical model, after events and new products, the consensus, and who overrode it. A later release replaces a
  week until it is within the lag; then it stays as kept).
* *Value add* (input: Demand → Value add; processing: each layer against the sales of the weeks that have sold;
  output, for Kaveri):
  * 99 product-weeks have sold (31,728 units, to 27 September). The consensus missed by 12.1 % and ran 5.2 % high.
  * The statistical model missed by 9.7 %, a little *worse* than the naïve forecast (9.4 %) over these weeks. Weekly
    noise near 8 % on smooth series is what naïve does well; the backtest on the Forecast tab (rolling origins over
    two years) measures something else. This is the finding the page exists for.
  * Events and new products changed nothing (no event fell in those weeks); the planners' overrides added 2.4 points
    of error.
  * *By planner*: Sales West's quarter lift on trade mixer grinders came closer to the sales in 2 of 12 weeks, added
    15.4 points and ran 22.6 % high. The e-commerce desk's tenth on the marketplace took off 0.2 points.
  * *By product family*: kettles 8.2 % after overrides (+0.3 points), mixer grinders 14.3 % (−3.9 points).
  * *The overrides that cost most*: mixer grinder 500 W at the west trade distributors, week of 14 September: 686
    against 497 sold, where the forecast before the override said 548.
* *The small shop* (by hand: 260 sold over four product-weeks; absolute misses naïve 90, statistical 35, events 30,
  consensus 37): 34.6 %, +21.2, +1.9 and −2.7 points, consensus 14.2 % and 10.4 % high; ana −15.0 points, ben +16.0,
  an override without a name under "Not named". Releasing its forecast kept the next weeks: 2 waiting became 11.

| # | Found | Severity | Outcome |
|---|---|---|---|
| N230 | An override typed without a name was not counted as an override at all: a kept week said who overrode it only by the name. | Major | **Fixed** before it shipped: a kept week says whether it was overridden; one without a name counts under "Not named". |
| N231 | The consensus grid wrote its overrides without a name, so no planner could be judged on them. | Major | **Fixed.** Signed in, an override from the grid carries the planner's e-mail. |
| N232 | Near-zero figures read "−0.0 %" and "+0.0 pts". | Cosmetic | **Fixed.** |
| N233 | The layers table repeated the same "sold" figure on every row. | Cosmetic | **Fixed.** It is in the sentence above the table. |
| N234 | The planner is the name an override carries (the e-mail of who typed it in the grid, or what an import says), not checked against the company history. | Minor | By design: the company history says who saved each change. |
| N235 | A product without sales of its own (a new product) has no naïve forecast; its naïve is its statistical forecast, so the model adds nothing over it. | Minor | By design: there is no yardstick for it. |
| N236 | Value add is judged at one lag only; the forecast one week ahead and at the lead time cannot be set side by side. Kept forecasts grow by one row per product, place and week, like the sales history, and are never trimmed. | Minor | Open. |

### 4.3: Planning material, assembly forecasts and the strategy advisor

ENTERPRISE_PLAN 4.3, through the engine and in a browser: the Kaveri Kitchenware example (two products now say how
many days their customers wait), a mixer shop imported as a file (a base mixer with a red variant and a blue twin pack
that uses two), and a pump shop in the engine tests (a pump made to order from two motor units forecast ahead).

* *Planning material* (input: a variant's *Planning material* and *Units of the planning material one of these uses
  up*, under Data → Products; processing: the variants' sales are counted in the base's series, × the factor, and their
  orders, open, delivered or closed, use up the base's forecast where they are sold; output):
  * Sixteen weeks of 30 red and 10 blue twin packs make one series for the mixer, 50 a week: 300 over the six weeks,
    one product and place. The series says "Forecast once for its variants (Mixer blue twin pack × 2, Mixer red)".
  * Against a base forecast of 100 in a week, 30 red and 20 twin packs leave 30 to plan; the motors come to 100, not
    the 170 of forecast and orders both. The mixer's own orders carry *Planning only* on the plan: they plan the
    motors the variants share and are never made themselves.
  * Checks: a variant with a forecast of its own (both are planned), a planning material that is itself a variant
    (nothing is planned through it), an override on a variant (it goes to the base).
* *Forecast on an assembly* (strategy *Forecast on an assembly, its parents' needs using it up (70)*; processing: the
  parents' dependent requirements, from planned and firm orders, use up the assembly's forecast within its
  consumption windows; output): the pump order needing 60 motor units plans 200 against a forecast of 200, not 260;
  the week's remaining 40 stay spread at 8 a working day. 260 needed in all plans 260, and an order eleven days past
  the last forecast week reaches none and is planned on top. The safety-stock rate counts the larger of the forecast
  and the parents' demand.
* *Strategy advisor* (Inventory → Strategy; input: *Days customers accept to wait* per product; processing: the
  preferred path from where it is sold, the last delivery leg, assembling plus delivery, and the longest path through
  the bill of materials plus delivery; output, for Kaveri):
  * Every finished good is judged where its slowest path starts, the north trade distributors: 1 day from stock at the
    Delhi warehouse, 7.3 to make at Pune and deliver, 53.3 from scratch. Customers of the 500 W mixer grinder and the
    kettle wait two days: made to stock, which meets the wait.
  * Typing ten days for the 750 W: "Assemble to order. Now made to stock, orders using up the forecast, which meets
    the wait. Customers wait 10 days: enough to assemble it (7.3 days) but not to get its parts (53.3)". One click on
    *Assemble to order* sets it where the north trade's demand is planned from, the Delhi warehouse.
  * Half a day: *Orders late*, and the page says one product is planned in a way that makes orders late.

| # | Found | Severity | Outcome |
|---|---|---|---|
| N237 | The advisor's button set the strategy at the plant, where the product is made, and nothing changed: Kaveri's trade demand is planned with the strategy of the nearest place upstream with a record of the product, the Delhi warehouse. | Major | **Fixed** before it shipped: the advisor says where the strategy is read (`Dataset.demand_lp_at`), the button sets it there, and the row says "set at Delhi NCR DC". |
| N238 | At phone width every Inventory tab scrolled sideways: the hidden "out of date" labels for screen readers sat outside the scrolling tab bar and widened the page. | Minor | **Fixed** for every page: those labels are pinned to the corner. |
| N239 | The series workbench heading and list showed codes ("BASE @ CU"). | Cosmetic | **Fixed.** Names: "Mixer at Trade". |
| N240 | The S&OP plan reads an assembly's forecast as demand of its own and adds its parents' needs on top: strategy 70 is planned once only by MRP and the safety-stock rates. | Minor | Open. |
| N241 | A planning material reaches one level: a variant of a variant is forecast on its own (the check says so). | Minor | By design: SAP's planning material is one level too. |
| N242 | The Kaveri example has no variants and no assembly forecast; those are shown on small imported companies. | Minor | Open. |
| N243 | The advisor follows the preferred source and nominal lead times: no queue, capacity or alternative source shortens or lengthens them. | Minor | By design: it compares the planned times the plan itself uses. |
| N244 | The Kaveri example was not the same file on every machine: OpenBLAS picks its kernel per processor, and the kept forecasts fitted on an AVX-512 machine and an AVX2 one differed by a tenth, so CI (AVX2) rounded a kettle week to 640 where this machine wrote 641. | Major | **Fixed.** The example builder sets one kernel (Haswell, single thread) on every x86 machine before numpy loads. |

### 4.4: Demand with a spread, and lead times as measured

ENTERPRISE_PLAN 4.4, through the engine and in a browser on the Kaveri Kitchenware example: its forecast used again
from the Demand page, a new order checked on the order page and on a several-line order, and the supplier scorecard
on the Buying page. Small companies in the engine tests cover the arithmetic.

* *The high end with the forecast* (input: the forecast's interval, 80 % by default; processing: each released
  period keeps the top of its interval over the part in the horizon, never below the forecast, in whole units for a
  product counted in each; output): Kaveri's Demand page reads "Customers are expected to order 92,370 units over the
  next 26 weeks, across 9 products and places, up to 1,14,798 at the high end (P90, which about one period in 10 goes
  over)". *Use this forecast in the supply plan* writes each period's high end beside its quantity.
* *A safe date beside the expected one* (input: an order checked before it is taken; processing: the order is
  checked a second time after the forecast still to be ordered up to its date is promised first, at the high end:
  what is left of each forecast once the orders, this one among them, have used it up, plus its spread, for the part
  of its period up to the date; output):
  * 400 mixer grinders 500 W for the north trade on 5 October: Delhi has 300 for that day, the rest by 11 October.
    The tile *High demand (P90)* reads "Sun 11 Oct, 245 on time, the rest by Sun 11 Oct", and the page says the second
    answer first promises the 644 more that other customers would order by 5 October if they ordered at the high end:
    a date from the first answer may cost an order later; the second is safe to give.
  * The same on Selling → New order: the line says "If demand runs high (P90): 245 on time, the rest by Sun 11 Oct".
  * Small cases: another customer's week of 60 (90 at the high end) keeps 77.1 of 100 first; the order's own
    customer's forecast is used up by the order first (34.3 kept, not 77.1); a forecast that starts after the date keeps
    nothing; made to order or no high end, no second answer; lines of one order keep it once.
* *Lead times as measured* (input: the purchase lines the roll-forward closed; processing: receipt less due date per
  line over the last year, its sample standard deviation, from the source's own lines once it has three, else from
  all its supplier's; output): Shenzhen electro-components delivered four lines, three a day early and one a week
  late: "± 4.0 d over 4 receipts of all its parts, 1.0 d late on average" beside the "± 3.0 d" planned. *Plan with
  ± 4.0 d* sets it; the switches' lead time at Pune reads 14 d ± 6.4 with the sea lane, not ± 5.8, and their safety
  stock goes from 8,647 to 9,114. The copper supplier, two lines so far, says "too few receipts yet".

| # | Found | Severity | Outcome |
|---|---|---|---|
| N245 | After *Plan with ± 4.0 d* the supplier table still showed ± 3.0 planned and the button, until the Buying page was recalculated. | Minor | **Fixed** before it shipped: the planned spread is read from the company's data, so the click shows at once. |
| N246 | "First promises the 644 other customers would still order" read as 644 customers. | Cosmetic | **Fixed:** "the 644 more that other customers would order". |
| N247 | At phone width the tile label "If demand runs high (P90)" was cut off. | Cosmetic | **Fixed:** *High demand (P90)*. |
| N248 | The Inventory stages table showed place codes, and the lead time without its spread. | Cosmetic | **Fixed:** names, and "14 d ± 6.4". |
| N249 | The safe date keeps first only the forecast of the product ordered: other products that share its parts or machines, and a planning material's forecast for an order of its variant, are not kept first. | Minor | Open. |
| N250 | Kaveri's forecast as shipped has no high end, so there is no second answer until the forecast is used again; S&OP releases and forecasts typed by hand have none unless *high_qty* is given. | Minor | By design: the high end comes with a release of the statistical forecast. |
| N251 | "Up to … at the high end" adds each period's P90; the P90 of the whole horizon is lower. | Minor | By design: the page says one period in 10 goes over, each on its own, which is what the second answer keeps. |
| N252 | The measured spread is of purchase lines only; a transfer lane's transit spread and production times are still typed in. | Minor | Open. |
| N253 | A supplier late on average (Shenzhen, a day) shows its mean delay but it is not offered as a longer lead time. | Minor | By design: the page says a mean delay needs a longer lead time and leaves the choice to the buyer. |
| N254 | A line delivered in parts is measured from its last receipt, when it was there in full. | Minor | By design: that is when the plan had it. |

### 5.1: Planning again only what a change reaches

ENTERPRISE_PLAN 5.1, in a browser on the Kaveri Kitchenware example and through the engine on the generated company
of 5,000 products at 20 places (DEPLOY.md §5). Every plan keeps its work, product by product at each place; the next
plan replays a node whose data, and whatever its consumers hand it, are as they were, and plans the rest (S/4 net
change planning). The plan made that way is the plan made from scratch, byte for byte: over the six examples and 24
random networks with random changes, and in the size test.

* *Input:* on Data, Pune plant's heater elements on hand from 14,000 to 20,000. *Processing:* the heaters at Pune and
  the part they go into are planned again; nothing else reads them. *Output:* the Plan page reads "⚠ Out of date",
  then after *Recalculate* "Only what the changes since the last plan reached was planned again: 2 of 29 products at
  their places; the rest stand as they were." One requisition for heaters (PR-0025-03) is no longer needed; every
  other order keeps its number. Planning again with nothing changed says the plan stands as it was.
* *At 5,000 × 20* (11,635 products at places; a plan from scratch takes 89–97 s): a forecast raised by half at
  one warehouse is planned again in 13.5 s, the stock of one product at a warehouse set to nothing in 11.9 s, the lead
  time of one bought part in 13.1 s; each the same plan as from scratch. What is left is reading the company: the data
  checks, each product's inputs, and comparing them with the last plan's. Keeping the work makes a plan from scratch
  about 7 % slower (86.7 s of planning before, 92.9 s now).
* *What is planned whole* (the previous plan's work is not used): capacity-constrained planning and co-products,
  where products share machines or one product's orders make another's stock; and a change everything reads
  (settings, calendars, places, machines, suppliers, MRP groups, purchasing, scheduling and inventory settings,
  contracts), or a product or place added or taken away.

| # | Found | Severity | Outcome |
|---|---|---|---|
| N255 | At 5,000 × 20 the data checks rebuilt the list of product families for every reference they checked, which grew with the square of the company: a plan from scratch took 590 s, 500 of them in the checks. | Major | **Fixed:** each check builds only the list it reads. |
| N256 | Planned orders were numbered in one sequence over the whole network, so one requisition fewer renumbered every order planned after it: a stock change at one warehouse took 68 s, most of it renaming orders in work that had not changed. | Major | **Fixed:** a planned order is numbered by its product at its place, then in turn there (PR-0025-03), so a product planned as before keeps its numbers whatever changes elsewhere. The old engine numbered that way gives the same plans (differential test). |
| N257 | Planned numbers are longer (PR-0025-03, not PR-00042); the schedule board labels orders "17-01". | Cosmetic | By design: the first part is the product at its place, the same in every plan. |
| N258 | Capacity-constrained plans and plans with co-products are always planned whole. | Minor | Open: machines and suppliers shared between products would need planning again together. |
| N259 | Deleting a demand line without an id renumbers the lines after it ("#12" becomes "#11"), so their products are planned again although nothing about them changed. | Minor | Open: the plan is right, only slower. |
| N260 | The server keeps the last plan's work beside it, one company per server process: planning another company plans from scratch and replaces it. | Minor | By design: one plan's work per process; its memory is part of the plan's peak in DEPLOY.md §5. |
| N261 | The first change after a plan of 5,000 products took 21 s, not 13: Python's collector looked through the gigabytes of kept work for cycles. | Minor | **Fixed:** the collector waits while a plan is made again from kept work. |

### 5.2: Ask the plan

ENTERPRISE_PLAN 5.2, in a browser on the Kaveri Kitchenware example (*Performance → Ask the plan*) and through the
engine on the Chennai pumps example and the generated company of 5,000 products. A question in plain words is read
by rules against the company's own names and ids (no language model, nothing leaves the server) and answered from
the plan's records: the pegging, each planned order's projected date and what holds it up, the machines' daily
load, the open worklist with its owners and money at risk. Every sentence cites the records it rests on, each a
link to where it is seen. Asking changes nothing; what an answer proposes is the inbox's own fix, tried on a copy
and kept by the person as one change, or a what-if kept as a stored scenario.

* *Why late. Input:* "Why is the 10 HP export pump late for Jebel Ali?" (the product and the customer said in part).
  *Processing:* each late demand of that product for that customer is followed down its pegging to the supply that
  reaches it latest, and down from there. *Output:* "42 units of Export end-suction pump 10 HP (PUMP-10HP-EXP) for
  Gulf distributor, Jebel Ali are projected late across 2 demands (2,184,000 INR of sales)", each demand with its
  chain: the transfer from the port that is available 10 Oct, needed 5 Oct; it should have started 23 Sep, so even
  started today 12 days of transit make it 10 Oct. For the Singapore buyer the chain runs five levels down, through
  the port, the plant's production order MO-0007-01 and the motor it waits for, to the motor's purchase that should
  have started 18 Sep (Hosur motor works takes 10 days). The late units add up to the plan's own demand at risk,
  product by product at each customer.
* *A fix kept. Input:* "Why is PUNE-WIND overloaded?" *Output:* "over its capacity and overtime on 7 more days in
  periods with room", the worst day first (31 Oct: 61.0 h of work on 48.4 h with overtime, most from MO-0020-04 and
  MO-0019-03), and the inbox's *Add 12.6 h of overtime*. *Try it* plans a copy (this problem → gone); *Keep this
  change* applies it as one change, the question is asked again on the changed data ("not over its capacity on any
  day") and one *Undo* takes it back.
* *What if. Input:* "What happens if Hindalco goes bust?" *Output:* read as *SUP-COPPER out*, planned on a copy:
  99.6 % → 69.4 % on time, 28,930 more units late, copper wire at Pune has no other supplier, and where the late
  demand lands, customer by customer. *Keep as a scenario* stores it under Versions to compare and promote. The
  numbers are the what-if page's for the same chip.
* *Who owns, what is at risk.* "Who is responsible for the mixer grinders?" names the owners of the 10 open problems
  on both mixer grinders (by owner rule), and the rule that routes new ones; "What is at risk?" is the inbox's top six
  with owner and action. A question it cannot read ("tell me a joke") is answered with questions this company's data
  can answer, each of which it reads.
* *At 5,000 × 20* (the plan kept on the server, 125 s to make here): reading the open worklist takes 12 s (10,943
  open problems), then "Why is FG-00008 late?", "Who owns FG-00008?" and "Why is anything late?" (368,825 units
  across 4,394 demands) are answered in 1–3 s, "What is at risk?" in 9 s. A what-if question plans the company
  again with the change: 3 minutes and 11 GB at the peak, as the what-if page.

| # | Found | Severity | Outcome |
|---|---|---|---|
| N262 | "Why is PUNE-WIND overloaded?" first answered "not over its capacity in any period": it looked at weekly totals only, while the inbox listed the machine's days over their hours. | Major | **Fixed:** a machine's answer counts the days over their hours inside weeks with room too, as the day-overload exception does, worst day first with the orders that load it. |
| N263 | "Why is SO-88221 late?" said it was not late: the plan covers it on time, but the promise check confirms only 600 of 800 on the requested date. | Major | **Fixed:** when the plan has it on time, the open problems on it are said too ("But 1 open problem on it says otherwise: …"), with their fixes. |
| N264 | "Who is responsible for the mixer grinders?" found no problem: the words also named *Assembly line 1 (mixer grinders)*, so it looked for problems on both the products and the line. | Major | **Fixed:** a word said names one kind of record: the kind whose names share the most of the words takes them (products before places before machines), and the next kind is read from the words left. |
| N265 | For the kettle (KT-15) and the 500 W mixer grinder the inbox's one-click *expedite* is offered, but pulling the firm transfer in by a day leaves the demand late; *Try it* says so ("stays late"). | Minor | Open: proposals are not tried before they are offered (each try is a plan of the whole company). |
| N266 | "What if the kettle line is down 3 days?" changes nothing on time: the plan does not wait for machines unless capacity-constrained planning is on. | Minor | By design: the answer says so and where the change shows (the machine's load). |
| N267 | "What if steel prices rise 10 %?" is not read: no what-if changes a supplier's price. | Minor | **Fixed in 5.3:** a purchase-price chip (a supplier's, or some products'), read by *Ask the plan* when a supplier or a bought product is named with a price and a per cent. |
| N268 | Time words are not read: "Is anything going to be late next week?" answers for the whole horizon. | Minor | Open. |
| N270 | At 5,000 × 20 a what-if question takes 3 minutes: the company is planned again whole with the change. | Minor | Open: a change to one product's demand or one supplier could be planned again from the kept work (5.1) instead. |
| N269 | "Which orders are late", "show me shortages" and "goes bust" were not read as asked (the first as *what is at risk*, the others not at all); "1 days of lead time". | Minor | **Fixed.** |

### 5.3: What-if smaller than the leaders'

ENTERPRISE_PLAN 5.3, in a browser on the Kaveri Kitchenware example (*What if… side by side*, its new tab *Sweep one
change*) and through the engine on the Chennai pumps example and the generated company of 5,000 products. One change
is planned at two to eight sizes and read against today; a stored version is a column of the side-by-side, read on
the server for the company that asks; and every scenario's sales projected late are given by the period their
demand is due.

* *Sweep a lever. Input:* safety stock at 0, 2, 5, 10 and 20 days of cover, every product at every place.
  *Processing:* the company is planned at each size; each plan is read for its cost, the plan's own on-time service
  and the service to *expect* when demand misses its forecast: at every stocking place that ships to a customer,
  β = 1 − σ·G(SS/σ)/Q with σ the spread of demand over the lead time (the same variance safety stock is sized with),
  SS the plan's safety stock, Q the typical lot and G the normal loss function, weighted by the demand each serves.
  *Output:* "expected service 93.7 % to 100.0 % (today 99.8 %), cost 63,407,292 INR to 88,955,232 INR"; "the
  cheapest service is from 0 d to 2 d: 6.0 points at 797,138 INR a point", from 2 d to 5 d a point costs
  12,074,536 INR, 10 d "costs 5,183,907 INR more than 5 d and buys no expected service", and *Not worth it: 10 d,
  20 d*. The chart puts cost against expected service, a dot a size, today as a ring and the sizes worth their money
  joined; a click on a row shows that size's money at risk over time beside today's; *Keep as a version* stores it.
* *Sweep an exposure. Input:* every supplier's lead time −7, +7, +14, +21 days on the Chennai pumps (in the
  browser, the copper supplier's on Kaveri).
  *Output:* "Service holds within half a point of today up to −7 d; at +7 d it is 96.5 % with 5,004,433 INR of sales
  projected late (today 3,686,267 INR)", the most at risk at +21 d (13,442,933 INR). No frontier is drawn: a longer
  lead time is not something bought.
* *A stored version as a column. Input:* the working copy saved as *Plan as is*, then compared with the working copy
  and *Busy season* (demand +20 %). *Output:* the column reads *stored version V0001*, with *same service* and no
  cost difference against the baseline, and no *Keep* button (it is stored already); chips can go on top of it. A
  version of another company is refused (404), as is a browser with no key of its own.
* *Money at risk over time.* Under the side-by-side, one line a scenario by week, the baseline dashed and drawn on
  top, with the figures by period: Busy season puts 10.56 L at risk in the first week and 24.42 L in the second,
  against 8.8 L today. Each scenario's periods add up to its *sales at risk* row.
* *A supplier's prices.* A new chip, *Purchase prices +10 % at SUP-COPPER*: its prices, price scales and contract
  lines (+15.01 L of cost, the same service); it can be swept, and *Ask the plan* reads "What if Hindalco raises prices
  10 %?" and "What if copper wire costs 10 % more?" as it.
* *At 5,000 × 20:* each size is a plan of the whole company; expected service adds 1.5 s. Safety stock at 0 and 7
  days (today and two sizes, three plans) took 4 min 54 s at a peak of 10.7 GB, one plan held at a time. Today's mix
  of policies gives 100.0 % expected service; none at all gives 93.6 % for 32.4 Cr less, and 7 days on every product
  costs 64.9 Cr more for no more service (*not worth it*).

| # | Found | Severity | Outcome |
|---|---|---|---|
| N271 | A sweep of safety stock had nothing to read: the plan takes the forecast as certain, so its on-time service never rises with safety stock (Kaveri: 99.6 % at 0 d and at 5 d). | Major | **Fixed:** safety stock is read against the service to expect when demand misses its forecast (the loss-function fill rate where stock meets customer demand); the plan's own service is shown beside it. |
| N272 | More safety stock *lowered* the plan's on-time service (Kaveri, 30 days: 99.6 % to 84.0 %): the whole top-up is ordered now, in one lot with the demand that falls due while it is made (12,450 mixer grinders at Pune, waiting for 23,452 motors and their copper wire), so that demand waits for the larger lot. | Major | By design in MRP (a shortfall below safety stock is a requirement today), and said in the sweep with what to do instead (raise it in steps over several weeks). Open: a raised safety stock phased in over weeks. |
| N273 | The safety stock chip replaced each product's policy whole, dropping its measured forecast error and review period. | Major | **Fixed:** both are kept; they describe the demand, not the policy. |
| N274 | A demand sweep read "Demand −10 % costs more than the step before it and buys no service: the money goes to stock". | Minor | **Fixed:** only a lever bought for service (safety stock) is read as cost against service; every other change as an exposure (how far before service falls, what it puts at risk). |
| N275 | The labels of dots at 100 % were cut off at the top of the chart; a scenario with the same money at risk as the baseline hid the baseline's line. | Minor | **Fixed:** room above the plot; the baseline is dashed and drawn last. |
| N276 | The sweep's sentences give whole amounts with the currency code (63,407,292 INR) while the page beside them compacts (₹6.34 Cr), as *Ask the plan* does. | Minor | Open: the engine's sentences take the page's money format. |
| N278 | "What if kettle prices rise 5 %?" was first read as the purchase price of the kettle body: "kettle" names the kettle we make and the body we buy. | Minor | **Fixed:** a price is read as a purchase price only when a supplier is named, or every product named is one we buy. |
| N279 | At 5,000 × 20 the first sweep ran out of memory and was stopped without a word: each scenario's plan was still held while the next was made, two plans of about 11 GB. | Major | **Fixed:** a plan is let go once its figures are read, in the side-by-side and the sweep alike: one plan in memory at a time (10.7 GB at the peak). |
| N280 | Found by CI after 5.3: two browsers planning Kaveri in turn shared the server's one kept plan. One planned the heater stock change; the other then made the same change and read "Nothing the plan reads had changed since the last plan" of its own change. Two companies planned in turn each planned everything, from scratch. | Major | **Fixed:** the plan's work is kept for each planner, by the company open and the person or browser asking. The newest is always kept, others within `SCP_KEPT_NODES`. Tested with two planners, two companies, the budget, and two browsers through the API. |
| N289 | Found by the full browser run after N280: a second browser opening Kaveri unchanged was answered with the plan the first had just made (the same data) and kept no plan work of its own, so its corrected stock figure was planned from scratch ("Only what the changes since the last plan reached" never showed). | Major | **Fixed:** whoever is answered with the kept plan keeps its work too; work held by two planners counts once in `SCP_KEPT_NODES`. Tested (and both changes mutation-checked) in tests/test_incremental.py. |
| N290 | Found by CI after N280: the variant-shop browser test pressed *Use this forecast in the supply plan* and went straight to Recalculate. Under load the plan was asked for before the release answered, so it planned the demand without the forecast and was out of date the moment the release landed. The planner was right; the test raced it. | Minor | **Fixed:** the test waits for the "Released" banner before it plans, as demand-spread.spec.ts already did. |
| N291 | Found by the full browser run: the S&OP browser test signed off the data step and checked the demand review's month row at once. The data step's panel shows the same month table, so under load the check passed on it, *Revenue* was pressed there, and the demand review then replaced the panel, showing units. | Minor | **Fixed:** the test waits for the step to move on (its sign-off button gone) after every sign-off; and the units-or-revenue choice is kept for the cycle, so the next step shows what was chosen instead of going back to units. |
| N277 | At 5,000 × 20 each size of a sweep plans the whole company again, one after another. | Minor | Open, as N270: a change to some products' or one supplier's data could be planned again from the kept work (5.1), and the sizes side by side on more cores. |

### 6.1: Bins, put-away, waves and a phone that reads the labels

ENTERPRISE_PLAN 6.1, in a browser on the Kaveri Kitchenware example (*Stock & actuals → Warehouse*, the phone page
*Scan* at 390 px, *Selling → Deliveries*), through the API, and through the engine on the generated company of 5,000
products. The Delhi DC has two areas: eight picking shelves of 300 units along the walk (*add to stock*, two shelves
a product) and eight high-rack bins of 1,800 kg behind them (*next empty*, a reserve). The rule sends every product
to the shelves, then the rack.

* *Put away. Input:* the go-live stock take, 1,500 kettles, 1,500 and 900 grinders, in no bin. *Processing:* each
  product's storage types in the rule's order, in each its strategy, within each bin's units and kilograms.
  *Output:* eleven tasks: two shelves of 300 for each product, the rest to the rack by weight (428 grinders of 4.2 kg
  fill a rack bin to 99.9 %). Opened on the phone, the first task reads *Put away · To S-01-01 · 300 Electric kettle
  1.5 L*. The 500 W grinder's label, read by mistake, is refused: "That is Mixer grinder 500 W: this task is for
  Electric kettle 1.5 L". The kettle's label is read, then 300 confirmed, and the next task is *To S-01-02*. The
  other ten are confirmed from the desk, in walk order. Stock by bin then shows every unit in a bin, and *in no bin*
  is gone. The place's stock and the plan are the same as before the moves: a bin move is a pair of movements that
  sums to zero.
* *A wave. Input:* the orders due in the next ten days put on deliveries (Selling); the one from the Delhi DC has
  two lines, 500 of the 500 W grinder (SO-88190) and 380 of the 750 W (SO-88140). *Processing:* each line is picked from the bins that hold it: the picking area before the reserve,
  first expiring, then first in, then nearest on the walk; a bin and product once for every delivery that needs it.
  *Output:* "Wave WV-0001: 1 delivery, 4 picks from 4 bins, in walk order", the pick list from S-01-03 to S-01-06,
  the grinders' shelves (the rack is not needed).
* *Pick on the phone, one short. Input:* the wrong bin is read first, then the right one; 20 fewer found than asked.
  *Output:* "That is bin R-02-04: go to S-01-03". Then: "280 Mixer grinder 500 W picked from S-01-03, 20
  short. Count bin S-01-03: the books say it still holds 20." Once the other picks are confirmed, the delivery reads
  "is picked, short: SO-88190 480 of 500: pack it and ship it". The goods issue ships the batches the picks took. It
  is refused while a pick is still open, and nothing is left staged.
* *At 5,000 × 20:* 346 products in stock at one DC with 546 bins: stock by bin in 0.16 s, the put-away proposal in
  0.6 s, making its 346 tasks 1.6 s, one task confirmed in 0.24 s.

| # | Finding | Severity | Status |
|---|---|---|---|
| N281 | The first put-away gave the kettles five of the eight picking shelves, being first in the list, and the 750 W grinders none: they would have been picked from the rack. | Major | **Fixed:** a storage type says how many of its bins one product may take (*Bins a product*). The Delhi shelves take two each, and put-away goes on to the next area. |
| N282 | Every bin move was posted with its task as its reference, and the plan's data check reported each one as "the reference matches no receipt, sales order or closed order". | Major | **Fixed:** the task keeps the movements it posted; the movements name no order. A test checks that the plan, its warnings included, is the same before and after the moves. |
| N283 | A storage type set to *mixed* never mixed: put-away only used empty bins or bins already holding the product. | Minor | **Fixed:** a mixed area takes a product beside others, once its empty bins are full. |
| N284 | Selling listed only the order lines due in the next 3 days, a company setting with no field on the page, so an order due in 5 days could not be shipped early from the screen. Changing the setting while the list was being read left the old list showing. | Major | **Fixed:** the window is a field in the list's heading ("Due to ship in the next [3] days"), and changing it reads the list again. |
| N285 | A short pick asks for a count of the bin, but the count is made on *Count stock*, by place and product, not by bin. | Minor | Open: a count by bin (a physical inventory of chosen bins, with the difference posted to the bin). |
| N286 | Stock taken out without a pick (a component issue to production, a scrap, a goods issue at a place with bins but no wave) comes off the bins first in, first out: a guess. *Stock by bin* names those postings and asks for a count if the guess is wrong. | Minor | By design, until supply to production from a bin is built (staging for the shop floor); open. |
| N287 | Reading a label with the phone's camera needs the browser's barcode reader, which Chrome on Android has and Safari on iPhone does not. A hand-held scanner works everywhere: it types the code and Enter into the field. | Minor | Open: a reader that does not depend on the browser. |
| N288 | Picking bins are refilled from the reserve by a bin move made by hand; nothing proposes it when a shelf runs low. | Minor | Open: replenishment by minimum and maximum quantities per picking bin. |

### 6.2: Stock in the books and cycle counts by ABC class

ENTERPRISE_PLAN 6.2, in a browser on the Kaveri Kitchenware example (*Money → Stock in the books*, *Buying →
Purchase orders → Supplier invoices*, *Stock & actuals → Count stock*), through the API, and through the engine on
the generated company of 5,000 products.

* *Valued at a moving average. Input:* the price control set to *a moving average of what it cost*, at the top of
  the books. The 10,000 concealed heating elements on PO-4500012871 are received at Pune. Shenzhen's invoice SZ-771
  bills 1.50 USD an element against the order's 1.35. *Processing:* the receipt goes in at what it lands at: the
  order price in rupees, the duty, the lane's freight per unit and the handling. The invoice's difference times
  (1 + duty) goes to the stock, by the share of what it bills that is still in stock; the rest is a price
  difference. *Output:* before the receipt, 14,000 elements at ₹141.65. After it, 24,000 at ₹141.65 (it cost what
  was planned). After the invoice, ₹147.97, +₹6.31 against the standard, and the invoice SI-00001 is among the
  postings. Nothing had left the stock, so there is no price difference.
* *The books as they stand.* At the standard price, on 3 Oct, Kaveri's stock is worth ₹2.93 Cr, the cost of sales
  ₹48.3 L, the count differences −₹7,835 and the scrap ₹8,831. Planning keeps its planned unit value either way.
* *A cycle count. Input:* the Delhi NCR DC, 12, 4 and 1 counts a year for A, B and C. *Processing:* the journal
  holds no issues there yet, so the products are classed by what the DC's customers bought (sales history). The two
  grinders make 63 % and 38 % of the value used up and are A; the kettle used nothing up there and is C. Nothing
  was ever counted, so all three are due. *Output:* "Cycle count: 2 A, 1 C. PI-00001: 3 lines to count on Mon 28
  Sep, book stock frozen." The 500 W grinder is counted 2 short and the differences posted. Class A then reads 2
  counted, 50 % found as booked, −₹2.7K; C 100 %. Nothing is due, and the grinders are next due on Thu 29 Oct.
* *At 5,000 × 20:* the books over 10,633 products at places in 1.7 s (0.4 s again), the cycle plan of one DC (346
  products: 171 A, 85 B, 90 C) in 0.8 s, of every place in 1.0 s.

| # | Finding | Severity | Status |
|---|---|---|---|
| N292 | At a moving average a purchase came in at the bare order price, without the duty, freight and handling the planned value includes. The heater's price fell from ₹141.65 to ₹130 on a receipt that cost exactly what was planned. | Major | **Fixed:** a purchase comes in at its landed cost, and an invoice difference takes the duty with it. |
| N293 | Unit prices in the books were rounded to the rupee (₹142), so a moving average that moved by paise looked unmoved. | Minor | **Fixed:** the books show prices to the paisa. |
| N294 | *Enter the invoice*, opened from a purchase order imported without a document header (all of Kaveri's), ticked none of its lines. A price typed on an unticked line was ignored: "Enter the invoice (₹0.00)", greyed out. | Major | **Fixed:** the order's line is ticked when it is the order itself, and typing a quantity or price on a line ticks it. |
| N295 | The invoice total on the button was always in rupees: a 15,000 USD bill read "₹15,000.00". | Major | **Fixed:** the total is in the supplier's currency when the lines share one. |
| N296 | Where sales history is recorded at the DC itself (the generated company), the cycle count followed the DC's own supply lane back to the plant: every product at the DC used nothing up and was C. | Major | **Fixed:** history at a stocking place counts for that place. Only a customer's or market's history goes to the place that ships to it. |
| N297 | A price difference is a figure on the page, not a posting to an account; a moving price cannot be revalued by hand (S/4 MR21); there is one price per product at a place, not per batch or valuation type. | Minor | Open: the account postings come with the double-entry journal (7.4); a price change by hand and split valuation, open. |
| N298 | *Roll the plan forward* kept the date it offered while the company under it changed: after a roll then an undo (or another company opened with the page still mounted) it offered the week after the roll, 19 Jan, for a plan starting on 5 Jan. The browser test failed on it in CI and passed here only because the page happened to be mounted again. | Minor | **Fixed:** the date picked belongs to the planning start it was picked from; another start offers a week after its own. The test checks the date after the undo and the redo, with the page open. |

### 6.3: Carriers, freight orders, loads by weight and volume, freight settled

ENTERPRISE_PLAN 6.3, in a browser on the Kaveri Kitchenware example (*Selling → Deliveries*, *Stock & actuals →
Transport*, at desktop and phone width), through the API, and through the engine on 2,000 deliveries. Kaveri has three
fictional carriers:
* *Sahyadri* charges 24,000 a truck plus 1.20 a kilogram from Pune to Delhi.
* *Deccan* charges a flat 32,000 a truck.
* *Northline* carries part loads on every LTL lane at 3.20 a kilogram (5 t, 30 m³ vehicles), never under 1,500.

* *Loads. Input:* the orders due in the next ten days put on deliveries; the stock transfer STO-2201, 600 kettles
  from Pune to Delhi due on 29 Sep, three days on the road, so late to leave. *Processing:* each lane's loads in
  vehicles, first fit, heaviest first, by kilograms and cubic metres; every carrier costed on its own vehicles.
  *Output:* four vehicles for ₹1.42 L:
  * The transfer goes with Sahyadri: 780 kg, 17 % of a 9 t truck, ₹24,936. Deccan's ₹32,000 is shown beside it, and
    the transfer is marked late.
  * The Delhi delivery goes with Northline: 3,962 kg and 25.78 m³, 86 % full by volume, ₹12,678.40.
  * The courier lane has no carrier, so it is costed at what planning assumes it costs.
  * A note names the low-filled truck and says a longer window lets later loads share it.
* *A freight order's life.* The transfer's order goes through each step:
  1. Tendered to Sahyadri: "FO-00004 tendered to Sahyadri Freight Carriers for INR 24,936.00."
  2. Rejected, it goes to the next carrier whose truck takes it: "tendered to Deccan Roadlines for INR 32,000.00
     (+7,064.00)".
  3. Accepted.
  4. Shipped, which dispatches the transfer: "left Pune plant (Chakan) for Delhi NCR DC on Mon 28 Sep with STO-2201".
  5. Settled against Deccan's bill DR-5521 of ₹33,150: "+1,150.00 against the planned INR 32,000.00; to pay by Wed
     28 Oct".

  The Delhi delivery's order, shipped, is its goods issue. *Carriers* then shows ₹33,150 to pay to Deccan and one
  order turned down by Sahyadri.
* *At 2,000 deliveries on four lanes, three carriers:* the vehicles planned in 0.11 s (958 of them), the freight
  orders made in 0.23 s, the page read in 0.03 s.

| # | Finding | Severity | Status |
|---|---|---|---|
| N299 | A carrier whose vehicle was too small for a delivery was proposed when it was cheapest: the delivery was marked "bigger than one vehicle", although another carrier's truck took it whole. | Major | **Fixed:** a vehicle too small for what it must carry is the last resort, whatever it costs. A test catches it. |
| N300 | The lane's assumed cost competed with the carriers' rates, so a light load went "with no carrier" at planning's estimate, where nobody carries it at that price. | Major | **Fixed:** the lane's own cost is used only where no carrier has a rate for the lane. |
| N301 | After a rejection, the freight order went to the lane's own cost (₹7,212) before the next carrier (Deccan, ₹32,000), because the cheaper one came first. | Major | **Fixed:** the next carrier first; the lane's own cost only when no carrier is left. |
| N302 | The message for new freight orders gave the fill by weight (9 %), the vehicle table the fuller of weight and volume (17 %). | Minor | **Fixed:** both give the fuller. |
| N303 | The fill bars hid their own percentage: the text sat under the bar. This also affected the bins on the Warehouse page (6.1). | Minor | **Fixed** on both pages. |
| N304 | One vehicle goes to one place: no multi-stop tours. A delivery bigger than one vehicle is named, not split. Freight is not added to a transfer's value in the books, nor to the cost to serve on Money. A settled bill is shown as to pay on *Carriers*, not in what we owe. A carrier's answer is recorded by hand. | Minor | Open: multi-stop tours and splitting, freight into the books and cost to serve (with 7.4), freight bills in payables, tendering by message. |

### 7.1: Third-party orders and job work with the GST challan

ENTERPRISE_PLAN 7.1, in a browser on the Kaveri Kitchenware example (*Buying → Job work & drop-ship*, then *Selling →
Invoices* and *Buying → Invoices*), through the API, and through the engine at 500 challans and 2,000 orders. Kaveri
gains two fictional suppliers and a firm order:
* *Bhosari winding works*, a job worker who winds motors on Kaveri's parts, with a GSTIN.
* *Vasai appliance works*, who make the 1.5 L kettle and ship it straight to marketplace warehouses.
* MO-100461, 600 motors of 750 W to make in the week of 5 Oct, while the winding machines are full.

The products carry HSN codes, and the plant and the company carry GSTINs.

* *Job work. Input:* MO-100461's parts for Bhosari, at ₹18 a motor, on lorry MH12 AB 4521. *Processing:* the parts
  are what the bill needs for 600 good motors:
  * Copper wire: 0.55 kg ÷ 0.985 (motors lost) ÷ 0.98 (wire lost) = 341.86 kg.
  * Lamination sets: 1 ÷ 0.985 ÷ 0.99 = 615.29, so 616 whole sets.

  They leave Pune as issues to the order, so its backflush never takes them again, and are held on challan JW-00001.
  The message says "Back by Tue 28 Sep 2027, or they count as supplied to the job worker (GST section 143)" and asks
  for three printed copies. *Print challan* prints them: original, duplicate and triplicate, each with both GSTINs,
  HSN codes, units and taxable values.
* *Back.* 580 motors come back on Bhosari's challan BWW/114.
  * They used 330.47 kg of wire and 594.78 sets, and are received on the order.
  * "Job charge INR 10,440.00 due" (580 × 18), waiting on *Buying → Invoices* as a line of its own, matched like an
    order line.
  * Five sets come back unused into plant stock, which takes the issue back for five.
  * Left at Bhosari: 11.40 kg of wire and 16.22 sets.
  * *Production orders with work done outside* offers the last 20 motors' five sets to Bhosari again, at ₹18.
* *Output:* stock at job workers by part and value; challans due within 30 days, and past the limit with the tax
  due on their value; the go-live check names a challan past it (JOBWORK_DUE). *ITC-04* for Apr–Sep 2026 has two
  tables:
  * Table 4 lists what was sent: HSN 85441110, KGS, value.
  * Table 5A lists what came back: 580 motors as processed goods on BWW/114, and 5 sets as inputs.

  It downloads as CSV. A loss written off is not a return.
* *Drop-ship. Input:* 500 kettles for *E-commerce marketplaces* by 16 Oct, shipped by Vasai at ₹742.
  *Processing:* taken at the kettle's ₹1,190 with ₹2,24,000 margin; sent; Vasai's dispatch advice of 300 (LR 66012).
  No stock moves and the plan does not change. *Output:*
  * 300 × 1,190 = ₹3,57,000 waits on *Selling → Invoices*, and is billed there.
  * 300 × 742 waits on *Buying → Invoices* for Vasai's invoice. A bill for 301 is blocked by the three-way match;
    their delivery costs stay out of our stock's value.
  * The last 195 close the order five short: the margin becomes 495 × 448 = ₹2,21,760.
  * An open third-party order counts against the customer's credit limit.
* *At 500 challans and 2,000 third-party orders:* the job-work page in 0.03 s, the drop-ship page in 0.04 s, what is
  to bill in 0.01 s, what is to invoice in 0.04 s, the checks in 0.02 s.

| # | Finding | Severity | Status |
|---|---|---|---|
| N305 | A production order without reservations backflushed its whole bill, whatever was already issued to it. Parts sent to a job worker, or issued by hand, were taken a second time when the order was received. | Major | **Fixed:** the backflush takes what everything made so far needs, less what was issued to the order. A test catches it. |
| N306 | Parts counted in whole units went out as fractions (615.29 lamination sets). After the last motors came back, 0.71 of a set stayed "at the job worker" for ever. | Major | **Fixed:** whole parts go out rounded up. The return that finishes the order uses up the bill's fraction of a part. The parts the job worker says they used can be given instead of the bill's. |
| N307 | A third-party order closed short kept the margin of the quantity ordered. | Minor | **Fixed:** closed short, the margin is on what was shipped. |
| N308 | An order partly at a job worker was offered again "not in the routing", with no job charge. | Minor | **Fixed:** the job worker and charge of its last challan are offered. |
| N309 | The page header counted an order closed short, not yet billed, as open. | Minor | **Fixed:** open means still to send or to dispatch. |
| N310 | The job charge is not in the motors' cost or stock value. Tax on deemed supplies is shown, not invoiced. ITC-04 is a CSV, not the GST portal's file. There is no e-way bill. The job worker's own challans are not checked. Planning does not count parts at a job worker as available for the order. A third-party order is a document of its own, not a line of a sales order, and is sent without a printed order. | Minor | Open: the job charge and postings with 7.4, the portal file and e-way bill, the planning view of stock at job workers, third-party lines on sales orders and their order document (with 7.2). |

### 7.2: Supplier portal and UBL messages

ENTERPRISE_PLAN 7.2, in two browsers on the Kaveri Kitchenware example kept on the server: the buyer's (*Buying →
Supplier portal*) and the supplier's, opened from the link with no account. Also through the API and the engine.
The example data is unchanged: copper wire from *Hindalco copper (Silvassa)* costs ₹905 a kg, ₹890 from 2,000 kg, on
a 2-day lane, with 10 % over-delivery allowed.

* *Input:* a new purchase order for 2,000 kg wanted Mon 12 Oct, at ₹890, released at each level and sent. *Make a
  link* gives `…#/portal/scp_sp_…` once, for 90 days. The supplier's page shows that one line and nothing else of
  Kaveri's (not the lamination order sent to another supplier), with the order as UBL XML to download.
* *Processing:*
  * The supplier changes the line: 1,200 kg on Fri 9 Oct and 800 kg on Fri 16 Oct, their reference SC/OC/3381. It is
    the order's confirmation, so the plan expects 1,200 on the 9th and 800 on the 16th.
  * They send dispatch advice: 1,200 kg in batch CU-7781 left on Sat 10 Oct (LR 40417). On the 2-day lane it
    arrives Mon 12 Oct. The first delivery is now expected on the 12th, three days late; the 800 keep the 16th.
  * Their system sends a UBL DespatchAdvice for the other 800 kg, dispatched Wed 14 Oct, arriving Fri 16 Oct. Buying
    pastes it in when it comes by mail; through the link it arrives by itself.
  * Each step is saved straight to the company as the link maker's change: "dispatch advice from Hindalco copper
    (Silvassa) on the supplier portal (link L0001)". The buyer's page shows *Show their changes* at once when they
    come back to the tab.
* *Output:*
  * *Goods received* on ASN-00001, Mon 12 Oct, receives 1,200 kg on the order with the advised batch; 800 are still
    on the way.
  * The link list says it was used twice. Withdrawn, the supplier's page opens nothing.
  * A lorry that will not come is cancelled; its quantity is expected again on the line's last date.
  * Rejected UBL lines confirm nothing. A message for another supplier's order is refused and nothing is saved, and
    so is a message with a document type declaration.
* *At a supplier with 2,000 open lines:* their page in 0.03 s, confirming all of them in 0.03 s, a notice of 200
  lines in 0.01 s, received in 0.06 s, the order as UBL (1.8 MB) in 0.06 s.

| # | Finding | Severity | Status |
|---|---|---|---|
| N311 | A dispatch advice moved every quantity already on the way to the new lorry's arrival date, so an earlier lorry's goods looked later than advised. | Major | **Fixed:** each notice keeps its own arrival. A new lorry counts against the earliest delivery still confirmed, and what it does not carry of that delivery stays late on its date. Hand-worked tests cover lorries early, late and partly. |
| N312 | Over-delivery inside the tolerance left the confirmation lines adding up to more than the quantity confirmed. | Minor | **Fixed:** the confirmation follows what is on the way when that is more; planning still counts no more than is open. |
| N313 | The buyer saw the supplier's save only at the next check for a newer save, up to a minute later. | Minor | **Fixed:** coming back to the tab checks at once. |
| N314 | Confirming 2,000 lines took 1.1 s: each line looked through every receipt again. | Minor | **Fixed:** the supplier's lines are indexed once (0.03 s). |
| N315 | The supplier's batch is kept on the notice but not on the receipt of a product without batches. The link is not e-mailed from the server. Messages come over HTTPS with the link's secret, not through the Peppol network (AS4). The supplier cannot send their invoice through the portal or print the dispatch advice. | Minor | Open. |

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
