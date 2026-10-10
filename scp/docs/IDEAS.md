# Ideas (recorded, not implemented)

Ideas met while implementing the roadmap from the UX audit of 7 Oct 2026 (PRs A–H). None of these is built; each is a
candidate for a later PR. Newest at the bottom of each group.

## Promising and planning
- **Promise against a P90 demand view.** Run ATP with the forecast's upper interval so sales sees a "safe" date beside
  the expected one.
- **Plan around a loop instead of blocking.** Data check blocks the whole plan for one circular route; plan the rest
  and mark the loop's nodes.

## Data entry
- **"Repeat last 4 weeks" in the demand grid.** One action that copies the last four weeks' demand of the selected
  rows forward over the empty weeks to the horizon (one undo step), for a planner who has no forecast yet.

## Security and accounts
- **A strength meter and re-authentication.** Show a zxcvbn-style score as the password is typed, and ask for the
  current password again before an e-mail or password change made from an old session.

## Connections and mail
- **Mail reminders follow the company time zone.** Imports run on the company's own clock since roadmap C
  (`settings.timezone`), but worklist reminder mails are still sent on the server's clock; send them at the
  company's morning.

## What-if side by side
- **Keep a scenario as a version.** A what-if that wins should become a stored scenario of the current base in one
  click (its chips written into the data), so it can be promoted like any other version.
- **More chips.** A machine down for N days, a price change for one customer, safety stock in days, an FX move on
  imported parts: each is one small edit of the dataset, like the five chips there are.
- **Sweep one chip.** Run demand −20 % … +40 % in steps and draw cost against service, so the planner sees where the
  next point of service gets expensive instead of four single points.
- **Stored versions in the side by side.** The API already takes a whole dataset per scenario; the page only builds
  scenarios from chips. Let a column be a stored version as well.

## Example cases
- **Port congestion as a calendar, not a flat delay.** The monsoon chip adds days to every route through the port;
  a port that closes on given days (cyclone warnings) would be a calendar on the lane, so a shipment that just misses
  the window waits for the next one.
- **A teaching mode for cases.** Hide the answers, let a class change the data and compare, then reveal the
  instructor's scenarios and a short debrief per question.
- **Tally and Zoho imports (roadmap G, not started).** Import masters and open orders from Tally Prime and Zoho
  Inventory exports, so an Indian SME can load its own data instead of a case. Deferred on purpose.

## Exception inbox
- **Do the action, then show the delta.** The inbox's action links to the page where it is done; a one-click version
  would branch the plan, apply it (expedite, switch supplier, add overtime) and re-plan, showing the money at risk
  before and after instead of the estimate.
- **Money at risk over time.** Keep the inbox total per run and draw it beside the KPIs, so a weekly review sees
  whether the exposure is falling.
- **Late-delivery penalties per customer.** `tower.late_revenue_factor` is one share for every sale; a contract's own
  penalty (or a lost-sale probability by customer segment) would price late orders more fairly.

## S/4 guide backtest, part B (§6 order capture, §7 aATP, §8 MRP, §9 PP/DS)
Found while backtesting the engine against the S/4HANA supply-chain guide (8 Oct 2026). Ranked by value; none built.
- **Outbound handling times in delivery scheduling (fig. 6.2).** The promised date is scheduled back from the requested
  delivery date by transit and goods-receipt time only. Add pick/pack and loading time at the shipping location (and a
  transport-planning lead time on the lane), so the material availability date and goods-issue date the guide draws
  are real: today every warehouse that needs a day to pick confirms a day too early.
- **A rescheduling horizon (§8.1).** MRP pulls a firm receipt in only when a new order could not arrive sooner, so a PO
  due a week late is duplicated by a new PR (now reported as RECEIPT_NOT_NEEDED). Within a horizon per product, propose
  "reschedule in" first and create new supply only beyond it. Plan-changing: needs a documented differential entry.
- **DDMRP as a planning type, not only an analysis (§8.7 pitfall).** `ddmrp_buffer` sizes zones and a net-flow
  recommendation on the inventory page, but MRP still plans the same item by net requirements: the two competing signals
  the guide warns about. An MRP type `ddmrp` would let the buffer (TOG − NFP when NFP ≤ TOY) drive the planned orders,
  with buffer-status (red/yellow) items in the inbox.
- **Configurable rescheduling tolerance.** `RESCHEDULE_OUT` uses a fixed 3-day tolerance; make it a planning setting
  (per MRP group) as S/4 does.
- **Firming types 2–4 (§8.5).** Only type 1 exists (new proposals move to the fence end). Add "no proposals inside the
  fence, report the shortage" (type 2) and manual firming, for plants that must not get automatic late orders.
- **Fences and GR time in working days.** Safety time now counts working days (S4-B2); the planning time fence and the
  goods-receipt processing time still count calendar days, while S/4 counts all three in working days. Changing them
  changes saved data's meaning: needs a migration note.
- **Allocation hierarchy and sequence (§7.4).** Allocations cap one product × customer set × period. A product-family
  cap checked before the customer cap, carry-forward of unused allocation, and a catch-all bucket are missing.
- **Optimising lot sizes (§8.3).** Part-period balancing / least unit cost / Groff for lumpy demand, beside EOQ.
- **Fixed pegging (§9.2).** Hard-link a firm supply to a sales order (MTO traceability) so replanning cannot reassign it.
- **Multi-item single delivery (§7.2).** Confirm the lines of one order together (all on the date the last is
  available) for kits, instead of line by line.

## S/4 guide backtest, part C (§10–16, §18.2)
Found while backtesting the engine against the S/4HANA supply-chain guide, sections 10–16 and 18.2 (findings matrix
kept with the audit, outside the repository). The first three were small and are built in the same PR; the rest are
recorded only.
- **Inspection stock is not promisable (built).** §10.3: stock in quality inspection is invisible to ATP unless the
  scope of check includes it. Planning may count it (`execution.quality_in_planning`, as SAP's MRP does), but the
  promise used the same on-hand and confirmed orders from stock that cannot ship. New `promising.quality_in_promise`
  (off by default, like checking rule A); the goods-issue message names stock waiting in inspection or blocked.
- **Purchasing processing time (built).** §11 TIP / §17.1: requisition → PO is the buyers' time, separate from the
  supplier's planned delivery time. New `purchasing.processing_workdays`: planning releases requisitions that many
  working days before the PO date; a PO placed today does not wait for it again.
- **Schedule adherence counts orders still open past their week (built).** §18.2: finished in the planned period ÷
  orders *planned*; the KPI divided by closed orders only, so a plant whose orders run late showed only those that made it.
- **Sales-order stock for make to order (segment E).** §16.2: supply made for one MTO order is reserved to it and
  cannot be consumed by another. Planning nets MTO anonymously (free stock first, any order's receipt); give firm
  receipts an optional sales-order assignment and peg/issue only to it. High value for job shops; large.
- **Moving-average valuation and actual GR prices.** §12.4: stock is valued at one planned price per place (≈ price
  control S). A moving-average option fed by goods-receipt and invoice prices would make inventory value and margin
  follow what was paid (price differences on invoices currently go nowhere).
- **Inventory turns and cash-to-cash.** Not in §18.2's list, but the money view the guide closes with (§15): DIO from
  stock value ÷ COGS per day, DSO from open receivables, DPO from open payables (both already in Selling/Buying),
  cash-to-cash = DIO + DSO − DPO, on the KPI page with numerator and denominator like the others.
- **Availability re-check at delivery creation.** §13: the delivery re-checks availability (rule A) before picking.
  Today a delivery is created whatever the stock, and the shortfall only shows at goods issue.
- **OTIF blind spot for orders not shipped yet.** §18.2 OTIF is delivery-based, as the app's; add the count (and
  value) of open lines already past their requested/confirmed date to the KPI note so a late backlog is not invisible.
- **Re-pricing of lines without an agreed price.** §15 PITFALL (pricing type B vs G): a line taken through Selling
  carries its price forward, but an imported line with no price is billed at today's list price (without its quantity
  scale). Freeze the price on such a line at goods issue.
- **Third-party (drop-ship) orders.** §16.3 TAS: a sales line bought from a supplier who ships straight to the
  customer: a requisition from the sales line, no stock, billing on the supplier-invoiced quantity.
- **Cycle counting by ABC.** §12.4: propose count documents by ABC class (A monthly, B quarterly, C yearly) from the
  demand ABC the forecast already computes, and a low-stock count when a pick empties a place.
- **Job-work subcontracting with component provision.** §10.1/§16.3 (item category L, movements 541/543): parts
  sent to the job worker are tracked as stock at the supplier (special stock O) and consumed when the finished part
  comes back; today a subcontracted step only adds days and a price, and the parts never leave the plant's stock.
  High value for Indian manufacturers (job work under GST); large.
- **Supplier lead-time deviation.** §11 outputs / §18.2: actual (PO date → goods receipt) vs planned lead time per
  supplier and product, shown beside supplier reliability and offered as `lead_time_std_days`, so safety stock uses a
  measured spread.

## S/4 guide backtest, part A (§1–5, §17, §20.1)
Found while backtesting the engine against the S/4HANA supply-chain guide (8 Oct 2026). Ranked by value to a
small or mid-sized planner. None is built.
- **Reduce the forecast at goods issue across a roll — BUILT (8 Oct 2026, option (b)).** It was a confirmed defect: the
  roll-forward dropped elapsed forecast by time only, so an order delivered early in a period did not reduce what
  was left of the forecast it consumed. Forecast 100 for four weeks, with 80 ordered and delivered in week one, rolled
  after two weeks: 50 forecast left and 130 planned (guide §5.1/§17.2, §20.1 #1). A per-record "reduced" quantity
  broke the rule "a week then another = two weeks at once" (s9). The build takes option (b):
  - The roll keeps the forecast as entered on the record (`original_date`/`original_period_days`/`original_qty`,
    written once, when the period begins).
  - Every plan recomputes consumption from scratch. Delivered orders (the delivered part of open orders, plus the
    closed-order log) consume the original forecasts. The record keeps what neither the elapsed days nor those
    deliveries took, whichever took more. Open orders then consume the rest, matched by the original periods.
  - Composition holds by construction. The example now plans 20.
  - Tests: `tests/test_forecast_reduction.py`. Recorded in `test_differential.INTENTIONAL`.
  Follow-ups:
  - Show the reduction: the requirement carries only open-order consumption today. A "reduced by deliveries"
    figure on the requirement and in the roll report would explain why less forecast is planned.
  - An S&OP release that splits a begun forecast makes its pieces new forecasts, without the original. Deliveries
    made before the split then stop reducing the pieces.
  - A begun forecast edited by hand keeps its original. Decide whether an edit should start a new original.
- **Planning at a common platform (strategies 60/63 "planning material") (high, L).** Many SMEs sell variants (sizes,
  colours, voltages) of one base: forecast the base once, let each variant's orders consume it with a conversion
  factor. Today each variant needs its own forecast.
- **Forecast on an assembly consumed by dependent demand (strategy 70/74) (med, M).** A forecast on a sub-assembly
  is planned on top of the dependent requirements from its parents instead of being consumed by them, so pre-building
  long-lead sub-assemblies to forecast double-counts.
- **Strategy advisor from lead times (§5.4 deep dive) (med, S).** CDT ≥ CLT+ALT → make to order; ALT ≤ CDT <
  CLT+ALT → assemble to order; CDT < ALT → make to stock consuming forecast. The engine knows ALT and CLT (lead-time
  model); with a "customer accepts N days" per product it can flag a strategy that cannot meet it.
- **Consumption mode: forward first, and windows in working days (med, S).** Orders always look back first, then
  forward (SAP mode 2). SAP also has forward-then-backward (4); and SAP counts the windows in working days, the app in
  calendar days (the field help now says so).
- **Make-to-order stock kept apart (sales-order stock, special stock E) (med, L).** MTO orders use free stock first
  (by design, and the form says so); an order-specific stock segment would let a business keep customer-specific
  goods from being shipped to someone else.
- **GR processing in working days (§17.1) (low, S).** GR days are counted in calendar days, so goods can become
  usable on a day the receiving place is closed (SAP counts GR time in working days). The buyers' processing time
  arrived with part C.
- **Exceptions per planner and per material class (§17.6) (low, S).** The tower ages exceptions; grouping their age
  by MRP controller and product type would point at master-data root causes, as the guide recommends.

## Working capital on the Performance page (8 Oct 2026)
Inventory turns, DIO, DSO, DPO and the cash-to-cash cycle are built from data the app already holds: goods issued to
customers at unit value, on-hand, customer invoices and supplier invoices with their payments. A flow with fewer than
28 days of records shows "not enough data". Not built yet:
- **Average stock instead of closing stock (med, S).** DIO and turns use stock on the planning start. The journal can
  rebuild the daily stock over the window, so an average would not swing with a single large receipt.
- **Targets for the working-capital measures (low, S).** They are ungraded until a company sets a target. A
  suggested target from the company's own last quarter would grade them from day one.
- **DSO by the count-back method, and invoice-ageing buckets (med, S).** Seasonal sellers read a truer DSO from
  count-back. The receivables table could show 0–30 / 31–60 / 60+ days overdue beside it.
- **Cash-to-cash trend (med, M).** Keep each week's value from the base versions, as plan stability does, and chart
  it.
