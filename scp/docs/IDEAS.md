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

## Exception inbox
- **Do the action, then show the delta.** The inbox's action links to the page where it is done; a one-click version
  would branch the plan, apply it (expedite, switch supplier, add overtime) and re-plan, showing the money at risk
  before and after instead of the estimate.
- **Money at risk over time.** Keep the inbox total per run and draw it beside the KPIs, so a weekly review sees
  whether the exposure is falling.
- **Late-delivery penalties per customer.** `tower.late_revenue_factor` is one share for every sale; a contract's own
  penalty (or a lost-sale probability by customer segment) would price late orders more fairly.
