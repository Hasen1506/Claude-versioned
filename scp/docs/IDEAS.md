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

## S/4 guide backtest, part A (§1–5, §17, §20.1)
Found while backtesting the engine against the S/4HANA supply-chain guide (8 Oct 2026). Ranked by value to a
small or mid-sized planner. None is built.
- **Reduce the forecast at goods issue across a roll (high, M — a confirmed defect that needs a design decision).**
  The roll-forward drops elapsed forecast by time only, so an order delivered early in a period does not reduce what is
  left of the forecast it consumed: forecast 100 for four weeks, 80 ordered and delivered in week one, roll after two
  weeks → 50 forecast left, 130 planned for a period whose forecast was 100 (SAP: 20 left, guide §5.1/§17.2, §20.1 #1
  "PIR consumed exactly once"). A per-record "reduced" quantity taken off the front of the period fixes the simple
  case, but breaks the roll's invariant "a week then another = two weeks at once" (s9) whenever an order is delivered
  in parts across rolls or delivered forecast is time-elapsed before an order consumes it: consumption by allocation
  is path-dependent. Options: (a) drop the invariant for the reduction only; (b) keep the original forecast records
  (date, period, quantity) and recompute consumption by delivered + open orders from scratch at every plan, dropping
  only records wholly in the past; (c) reduce per node, not per record. (b) is the clean one. A tested attempt at the
  per-record version is in the audit notes.
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
- **Purchasing processing time and GR in working days (§17.1) (low, S).** The buy lead time is supplier time +
  transit + GR days, all calendar; the purchasing department's own processing time is missing and GR days can end on
  a closed day.
- **Exceptions per planner and per material class (§17.6) (low, S).** The tower ages exceptions; grouping their age
  by MRP controller and product type would point at master-data root causes, as the guide recommends.
