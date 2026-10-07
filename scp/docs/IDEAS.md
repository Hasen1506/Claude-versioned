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
