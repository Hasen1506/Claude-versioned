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
