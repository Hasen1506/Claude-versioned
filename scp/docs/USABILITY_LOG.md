# Usability log

What a planner hits when using the app for real, found by building companies from an empty dataset through the
screens (not by opening the prepared examples). Each entry: what happened, why it matters, and what was done.
Open items name the roadmap phase that addresses them.

Phases: **A** get your own company in · **B** master-data depth · **C** capacity and material together ·
**D** PP/DS-class scheduling · **E** procure-to-pay.

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
| N23 | Levelling fills from the need date backwards and can pull an order a long way forward (18 days for a motor assembly on the example), building stock early, where a planner might rather use overtime or accept a day late. | Minor | Open (Phase D: strategy profiles and an objective that weighs earliness, lateness and overtime). |
| N24 | Capable-to-promise checks free capacity per plan bucket, so it can confirm a date on a machine that is free that week but not on the days it needs. | Minor | Open (Phase D). |

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
- PP/DS: one heuristic and a short local search; no strategy profiles, heuristics catalogue, real optimiser or
  drag-and-drop board (**D**).
- MM: no vendor master, info records, source lists, requisitions, POs or goods-receipt documents (**E**).
