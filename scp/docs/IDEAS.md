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
