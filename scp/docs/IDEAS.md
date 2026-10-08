# Ideas (recorded, not implemented)

Ideas met while implementing the roadmap from the UX audit of 7 Oct 2026 (PRs A–H). None of these is built; each is a
candidate for a later PR. Newest at the bottom of each group.

## Promising and planning
- **"Why this date" on every promise.** Show the chain behind a confirmed date (component X arrives D, production
  finishes D+2, transit 1 day). The engine already projects `projected_available_date` per planned order; expose the
  limiting component on `ScheduleLine`.
- **Promise against a P90 demand view.** Run ATP with the forecast's upper interval so sales sees a "safe" date beside
  the expected one.
- **Plan around a loop instead of blocking.** Data check blocks the whole plan for one circular route; plan the rest
  and mark the loop's nodes.

## Data entry
- **"Repeat last 4 weeks" in the demand grid.** One action that copies the last four weeks' demand of the selected
  rows forward over the empty weeks to the horizon (one undo step), for a planner who has no forecast yet.

## Security and accounts
- **Drop the token from sign-in replies for browser requests.** Since roadmap D the web client signs in with the
  HttpOnly cookie, yet the sign-in, sign-up and reset answers still carry `token` (for scripts). When the request asks
  for a cookie (`X-SCP-Session: cookie`), answer with an empty token, so a script injected into the page at sign-in
  time never sees one.
- **Require the double-submit token on sign-in too (login CSRF).** A forged form could sign a browser into the
  attacker's account; mint the `scp_csrf` cookie on the first page load and check it on sign-in/sign-up.
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
