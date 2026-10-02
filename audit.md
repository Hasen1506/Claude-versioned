# Claude-versioned functional audit and repairs

Latest continuation: 2 October 2026. The merged total remains **69 logic repairs plus one native runtime mitigation**, through [PR #15](https://github.com/Hasen1506/Claude-versioned/pull/15). Two additional production-cost repairs, BH075–BH076, have passed focused regressions and are awaiting publication CI and merge. They are not yet included in the merged count.

Updated 30 September 2026. Audited baseline: `ee0f7d136a25f1f30246fcd886f15db8d5985694`. Fixes merged to main as `aae75e872ac6ae8c419939295d7ad8b0ec82d977` through [PR #6](https://github.com/Hasen1506/Claude-versioned/pull/6).

The continuation covered spreadsheet decoding, save/recovery races and capacity-option appraisal, then repaired the confirmed functional defects. The first continuation added BH041–BH047; merge preparation found seven more logic defects, BH048–BH054. In total, **49 logic defects are repaired and one native runtime failure has a verified mitigation**. These are production application fixes with regression tests. All changes are committed and merged to main through [PR #6](https://github.com/Hasen1506/Claude-versioned/pull/6).

## Verification after repairs

### 2 October continuation: actual production-order costs

**BH075 (P1):** MRP records an operation on an alternative machine but prices its run and setup on the primary machine. Eight run hours and two setup hours assigned to a 25/hour alternative are charged 800 + 200 at the primary's 100/hour rate, instead of 200 + 50. Expensive alternatives similarly appear artificially cheap. The finance overlay reconciles internally but propagates the wrong cost and margin. Concrete orders now use their recorded step-resource assignments for both machine run and setup rates.

**BH076 (P1):** production orders use the nominal full-batch average to price partly filled batches, despite loading and dating whole batch hours. With capacity 10 and three machine hours per batch, an eleven-unit order loads two batches (six hours) but charges 3.3 hours. Scrap can similarly turn ten good units into 12.5 entering units and two batches while the cost remains prorated. A new order-cost calculation prices exact run work after scrap, whole batches and per-unit work, plus labor, outside processing and conversion overhead. Nominal unit valuation and aggregate planning retain their documented full-batch averages.

Fifteen persistent regression cases cover cheaper/more expensive alternatives with constrained/unconstrained planning, batch boundaries, operation scrap, labor/subcontract/overhead, nominal valuation and the finance API. All fifteen run against exact main costing/MRP files at `eb709ec5469e1101f5ad27bb664698b67ade3481` reproduce **12 failures and 3 passing controls**. The repaired cases and existing finance/manufacturing checks pass (**29 focused tests**), with lint passing. An additional **48 independently calculated quantity/rate/scrap cases** reconcile machine workload, order run/setup costs and the finance overlay, including fractional quantities. The complete **632-test engine suite** and lint pass locally. Publication CI and merge are pending. These are production calculation fixes with regression tests.

### 2 October continuation: unavailable production capacity

**BH073 (P1):** when the primary machine has zero units permanently from planning start, the date walker exhausts its 3,660-day search and returns the elapsed days as if production finished. An eight-hour order needed on 6 January 2026 is reported available on 13 January 2036; it also generates component purchases for an impossible make order. A non-finite machine with the same shutdown produces a customer CTP confirmation on that invented date. An open alternative machine or second production source does not rescue the order. The walker now raises a specific capacity failure, lead-time dating tries declared machine alternatives, and MRP retries valid sources with their own lot modifiers before reporting unavailable supply. Failed make attempts create no fictitious orders, component requirements or load, while independent purchases remain usable. CTP refuses the unavailable production attempt without committing tentative capacity/material actions. Firm load dating respects the recorded step resource and reports capacity failure without inventing load; entered firm receipt dates remain planner promises.

**BH074 (P1):** detailed scheduling raises on the first unavailable machine or one-unit trial, so an open alternative or a feasible two-unit split is never considered. Both schedule and comparison APIs return HTTP 500 for impossible firm work, and applying the schedule raises. Trials now skip only capacity-infeasible candidates, consider all allowed split counts and machines, and return `ok: false` with a `NO_WORKING_TIME` issue when none can complete. Manual machine pins remain binding. Overlap tail dating considers declared alternatives; infeasible local-search moves and optimizer proposals preserve the feasible incumbent. Applying an impossible result preserves its input.

Twenty-one persistent engine cases cover finite/non-finite shutdowns, independent purchases, source fallback and lot modifiers, constrained/unconstrained alternative placement, parallel units, API refusal, safe apply, manual pins, recorded firm resources, send-ahead alternatives and selected-machine efficiency, solver fallback, CTP and temporary reopening. All twenty-one run against the exact seven production files at main `d0548139e0cad1805d6ad25a201a27f5282836b1` reproduce **18 failures and 3 passing controls**. All **55 focused unavailable-capacity, calendar and detailed-scheduling tests** pass locally. [PR #15](https://github.com/Hasen1506/Claude-versioned/pull/15) merged both production repairs at `df610aa227833407f57d815104b6d3c4b8fe444f` after [full CI run 37016792438](https://github.com/Hasen1506/Claude-versioned/actions/runs/37016792438) passed **617 engine tests and 79 browser tests**, lint, reproducible examples, API type checks and the production build. The tested synthetic merge and actual merged commit share tree `edc96fa21047df6f9f6068a2691cc3eecf127a96`. Twelve additional plan → firm → schedule/apply → manufacture → shipment → roll journeys preserve alternative-machine assignments and reconcile component/finished stock across three quantities and finite/constrained settings. Eighteen independent final-batch bounds pass across machine efficiencies, send-ahead quantities and finite/non-finite machines. During repair verification, a slow manually selected machine was found using a faster alternative's tail bound; the final implementation dates each candidate and checks the selected machine's bound, with an explicit regression guard. These are production logic repairs with regression tests. The existing bounded lookahead remains 3,660 calendar days; exhaustion means capacity cannot complete within that search, not proof it can never reopen after it. The cumulative merged count is now **69 logic repairs plus one native runtime mitigation**; the audit remains open.

### 2 October continuation: resource calendars and overlapping production

**BH071 (P1):** a resource's own holidays/weekends were ignored by make-order dating unless it also had named shifts or capacity changes. The same eight-hour machine capacity expressed with a named shift produced different dates. On a Monday machine holiday, an eight-hour make order was reported available Tuesday, although the shop floor could only run Tuesday and make it available Wednesday. Forward/backward holiday and weekend reproductions fail on main. Date-dependent lead-time walking now includes an explicit resource calendar, preserving the existing fast path for inherited constant capacity.

**BH072 (P1):** send-ahead overlap prorated the first operation's setup with the batch quantity and used nominal days across machine shutdowns. Eight hours of setup plus two hours for the first four units was treated as a one-day handoff rather than two. The final batch could also be reported complete while its next machine was closed. Partial-batch work now includes the entire first setup, exact batch run work, and date-dependent resource capacity at both the first handoff and final completion; nominal production duration shares the corrected setup calculation.

Fourteen persistent engine cases cover named-shift equivalence, both date directions, holidays/weekends, MRP/shop-floor agreement, full setup and the final-machine shutdown. Running these against the exact main lead-time source at `ca73120118383de3e11315b34cfac5110a0494ee` reproduces nine failures (five calendar and four overlap boundaries); five existing-behavior controls pass. All fourteen and the complete **596-test engine suite** pass locally, alongside lint and the focused capacity/promising/routing checks. [PR #13](https://github.com/Hasen1506/Claude-versioned/pull/13) merged both production repairs at `fb006b481c4c0f8069995d3ed951df6adfe4b427`. [Full CI run 36962983628](https://github.com/Hasen1506/Claude-versioned/actions/runs/36962983628) passed all **596 engine tests and 79 browser tests**, lint, example reproducibility, API type checks and the production build. The tested synthetic merge and actual merged commit share tree `0c4441bbb91a976f06a04e8165f4aef731807db3`. An additional 48 independently calculated forward-date cases pass across weekends, two holidays, partial days and multiple workdays. The cumulative merged count is now **67 logic repairs plus one native runtime mitigation**; the audit remains open for areas without sufficient evidence.

### 1 October continuation: live-data transitions, restoration and concurrent reads

**BH067 (P1):** returning from a saved version to live data discarded unsaved stock 35 without acknowledgement. Its delayed document also replaced a newer import or stock edit. "Make this the live data" applied its company-A lookup to company B's version when B was opened meanwhile. Live-data return now acknowledges unsaved version/live edits, validates the original context and revision before replacement, and reports failed reads with retry available. Publishing a version validates that the confirmed working copy is still current after the revision lookup.

**BH068 (P1):** a history-restoration document or an explicit merge completing after company B was imported reopened company A. Restoring while newer stock edits were made similarly discarded those edits. Every server-company document replacement now requires a captured original context, enforced by the store API and checked at intervening history request boundaries. Restoration stops when existing edits could not be saved. History queries/comparisons belong to their original company and working copy; obsolete results cannot populate another company's history or replace its data.

**BH069 (P1):** a reload refresh for company A's newer live stock 25 replaced the deliberately opened saved version with stock 10, even though the company ID was unchanged. Server-only-storage recovery also reopened A after sign-out. An automatic merge finishing after a version open sent an additional merge using the version as the new working data. Recovery, periodic refresh, save retry and automatic/manual merge callbacks now check load epoch, account, company, version and the appropriate edit revision. Automatic merges may reconcile further edits in the same working copy, but stop when that working copy is replaced; a superseded callback cannot publish another copy or mark its save/conflict state.

**BH070 (P1):** concurrent browser workflows exposed HTTP 500s from account configuration and company-reference validation: a shared SQLite query returned no count row, and another raised `InterfaceError`. The public account-count and role reads bypassed the lock used by other database access. Controlled overlapping-transaction tests also reproduced an uncommitted account count and a false "company not found" response. Both reads now use the shared reentrant lock through execution and fetching. Two persistent regressions verify they wait for a writer's rollback and return the committed count/owner role; 41 focused company/version/reference tests and lint pass.

The creation audit also extends **BH065**, without counting a new defect: a delayed blank-company success or failed-create fallback overwrote a new import with the blank document. New-company/example opening now honors the original context and latest selection, including on failure. An ordinary create failure still retains the intended blank company locally.

Twelve browser reproductions and two corrected engine concurrency reproductions verified the original failures, grouped into four new findings plus the BH065 follow-up. Seventeen persistent browser cases pass in focused checks, alongside the account/version regressions. Merge reproductions were independently confirmed on a rebuilt main-branch client; their server used the isolated database-read repair to avoid the separately identified concurrency failure. [PR #12](https://github.com/Hasen1506/Claude-versioned/pull/12) merged the production repairs at `5ff6bfcfd2def9b4dbfa4145099276a2c04f960c`. [Full CI run 36827273837](https://github.com/Hasen1506/Claude-versioned/actions/runs/36827273837) passed all **582 engine tests and 79 browser tests**, along with lint, reproducible examples, API-type checks and the production build. The CI-tested synthetic merge and actual merged commit have the identical tree `a84094aa9b8ef16deeba6bf62881fc2430ff4e35`. All 17 new browser checks also passed in a fresh isolated local run.

Local Windows follow-up: an earlier single-worker rerun of three established golden workflows timed out during example bootstrap. Direct requests on the same server later passed (validation 0.17 s, network 0.065 s, forecast 1.286 s), and fresh reruns passed all three established workflows: versions in 21.6 s, then collaboration and four-eyes approval in 120.27 s. No source cause for the earlier delay is established; it remains an intermittent timing observation rather than an additional confirmed defect or a claim that every platform passes. The cumulative merged count at PR #12 is **65 logic repairs plus one native runtime mitigation**. Remaining product-audit gates are open.

### 1 October continuation: account and company request ordering

**BH065 (P1):** "Keep it on the server" saved the submitted stock-10 snapshot, then reopened it over stock 35 edited while either the creation response or the following document read was delayed. A late creation response also replaced newly imported company B with company A. The upload now captures its original working copy and checks company/account/version/revision before reading and applying the saved document. Newer edits or imports remain in the browser, including after reload; the submitted snapshot remains available separately on the server.

**BH066 (P1):** delayed company-open responses overwrote a newer import, reopened a company after sign-out, and selected company A after the user had subsequently opened B. Company opening now validates its starting context and edit revision, ignores superseded selections, and cancels obsolete completions when the account changes or the component unmounts. Company-list refreshes also ignore obsolete responses; an opening error leaves the list available for retry. Context capture supports an empty browser so signing back in and opening a saved company still works.

Six original browser reproductions demonstrated the failures, grouped into these two findings. An initial selection-test failure used the wrong session-storage key; it is excluded from application findings, and the corrected test reproduced the real wrong-company result. Ten persistent checks cover both upload request boundaries, edits/imports/sign-out during requests, selections completing in either order, and opening a saved company from an empty browser. All ten pass locally; the twelve existing version regressions and two collaboration/approval workflows also pass. Full [CI run 36822575171](https://github.com/Hasen1506/Claude-versioned/actions/runs/36822575171) passed **580 engine tests and all 62 browser workflows**, lint, examples, API type checking and the production build. Its tested tree `a1c5ebed4592ca2a81afcbd39f3de15c3679d4da` exactly matches the merged production tree. These two repairs bring the merged cumulative count to **61 repaired logic defects plus one native runtime mitigation**. Deployed account recovery, broader workload measurements and the remaining product-audit gates are still open.

Additional API workload checks passed at 25, 250 and 1,000 purchased products. Every product starts with stock 10 against demand 100 and unit purchase price INR10: each produces exactly one 90-unit order, with no missing/duplicate products, and total costs INR22,500, INR225,000 and INR900,000 respectively. Local HTTP elapsed times were 0.241, 0.454 and 2.311 seconds, including serialization/response transfer. This is a single-plant synthetic purchasing workload, not a manufacturing/solver/concurrent-user or deployed performance guarantee.

The previously blocked deployed read-only component check was retried after automatic approval became available. Its first HTTP attempt timed out after 45 seconds; the next returned **200** and independently expected **B16/C5** for partial production of 8 with fixed C5. The fixture is generated test data, with blank addresses/tax IDs and no accounts, secrets or real customer records. No deployed company/account/stock posting was created. This verifies the public component-preview behavior and resolves that particular tooling limitation; deployed signup, recovery, persistence and exact revision identification remain unverified.

### 1 October continuation: version snapshots, branches and promotion

**BH062 (P2):** saving opening stock 10, then changing it to 25 while the response was delayed, marked the working copy saved even though the stored version contained 10. A late save also attached company A's version metadata to a newly imported company B. Discarding a scenario similarly cleared the dirty marker without saving its edited data. Version saves now remember the submitted revision and mark subsequent edits unsaved, including after reload. Status changes retain the existing saved revision, and metadata is applied only to the company/version/session the action started from.

**BH063 (P1):** a branch response finishing after company B was imported reopened company A and persisted it as the current dataset. An ordinary version-open response also replaced a stock edit made while it was in flight (35 became the stored 10). Version document loads now require the original working context and revision. Multi-request branch/save/promotion actions check that context before their next request as well as before applying the result. A delayed branch document read for server company A no longer replaces or detaches live server company B. Working-copy comparisons reject a result when their inputs were edited during calculation.

**BH064 (P1):** branching or promoting a scenario with unsaved opening stock 45 silently opened the saved stock 40 and discarded the unsaved changes. Both actions now explain the replacement and require acknowledgement when they will open a saved snapshot over unsaved edits. Canceling preserves 45 and the dirty state; acknowledging deliberately opens saved stock 40. Promoting a different scenario does not replace the current working copy.

Seven browser reproductions confirmed these failures on the original production build, grouped as three findings rather than seven separately counted defects. Twelve persistent browser checks pass after repair: the independently calculated scenario journey, save/reload dirty-state accuracy, late save after import, delayed branch after import, branch/promotion cancellation and acknowledgement, discard dirty-state retention, edits during a version open or comparison, and a delayed document after a live-server-company switch. For forecast 100 at INR10/unit, opening stock 10 requires purchasing 90 at INR900; scenario stock 40 requires 60 at INR600. Comparison displays the INR300 reduction and the exact stock change. Promotion preserves the baseline fingerprint and reopens stock 40 after reload. A saved-10/working-25 comparison separately reports INR900 versus INR750. The existing version workflow also passes alongside the new journey with two workers, using actual created IDs so parallel tests cannot collide with hard-coded version numbers. Full [CI run 36801525468](https://github.com/Hasen1506/Claude-versioned/actions/runs/36801525468) passed **580 engine tests and all 52 browser workflows**, lint, reproducible examples, API type checking and the production build. Its tested tree `c35e01f7dd55bc39920d9c459f73c55cd894b66e` matches the production-fix tree.

The merged cumulative count is **59 repaired logic defects plus one native runtime mitigation**. This advances the version/scenario and collaboration coverage. It does not verify deployed account recovery, backup restoration, realistic-scale latency or every optional workflow, which remain open in the product audit.

Public-host recheck on 1 October: Pages still returns 404. Initial Render entry/health/config reads timed out after 35 seconds; later reads returned 200, with health `status=ok, version=0.1.0` and frontend asset `index-D_GBrJam.js`, matching the previous verified manufacturing build's filename. The public account configuration reports `signup=open`, `require_signin=false`, `first_account=true`, `mail=false`, `sso=null`. This establishes the advertised configuration at that time, not signup/recovery/persistence functionality or an exact backend commit. No production account or company was created. A proposed read-only production-component preview with the generated synthetic test fixture was not executed: automatic approval first could not establish data sensitivity/destination authorization, and after fixture/provenance/host inspection, approval review could not run because its usage limit was exhausted (reported retry 10:26 AM). These are tool-review limitations, not recorded application failures. Deployed preview verification remains outstanding.

### 1 October continuation: complete manufacturing browser journey

**BH060 (P1):** the partial-production form calculated components independently of the posting engine. For an order of 20 A with a fixed five-unit C component, confirming 8 A displayed/defaulted C2, while automatic posting correctly used C5. Selecting "parts actually used" turned the incorrect default into a stock posting. The form also counted reversed issues as consumption, omitted effective BOM parts on imported orders without reservations, and rounded small defaults to three decimals. It now reads the same component calculation used by production confirmation, including fixed quantities, net reversals, scrap and phantoms, retains six-decimal component defaults and the full open quantity, and offers retry after preview failure. Confirmation waits for a preview matching the current dataset and quantity; late previews are ignored.

**BH061 (P2):** in Asia/Kolkata, the new-order form suggested 11 January for a planning start of 5 January, despite intending seven days later. Its local-midnight-to-UTC conversion shifted the calendar date. It now uses the existing calendar-day helper and suggests 12 January in the tested timezone.

Both original browser reproductions failed before repair. The automated browser manufacturing journey now passes through JSON import, forecast and financial plan, sales promise, three firm orders, two purchase receipts, partial production of 8, weekly roll, remaining production of 12, shipment of 20 and final roll. Independent assertions check B40/C20, a 9–12 January production window, INR1,700 cost, INR2,000 revenue and INR300 margin; the fixture's setup and run rates require 12 machine hours. Exported stocks after the partial roll are A8/B24/C12; final stocks are all zero, with four closed orders and no remaining receipt or sales order. Separate browser checks verify fixed parts after a material-document reversal, the 0.0004-unit production default, preview retry after HTTP failure and rejection of a delayed preview for an older quantity. All four new browser workflows and 62 focused engine cases passed locally, including six new engine/API cases. Full [CI run 36798759112](https://github.com/Hasen1506/Claude-versioned/actions/runs/36798759112) passed **580 engine tests and all 40 browser workflows**, lint, reproducible examples, generated API type checking and the production build. The tested tree `8010459f3f4047b7ec8929ca096c0e2cb9a39389` exactly matches the production-fix tree. Tests overlap; do not sum them as unique coverage.

These two repairs bring the merged cumulative total to **56 logic defects plus one native runtime mitigation**. The small-quantity and reversal corrections are grouped under BH060 rather than counted as additional findings. Two additional independent engine probes verify company and machine calendars: 12 hours at four hours/day, with Friday 9 January a holiday and weekends closed, load Tuesday 6 through Thursday 8. Firming and shop-floor scheduling preserve those dates, all 12 productive hours and zero schedule violations. The imported-fixture browser proof and calendar probes advance the execution/correctness gates; beginner manufacturing setup from scratch, calendar editing through the UI and deployed account recovery remain open.

### 1 October continuation: execution context and manufacturing reconciliation

Two additional production fixes address the working copy used by engine actions. **BH058 (P2):** the roll report previously remained visible after Undo and could appear in another company's roll page. Reports now belong to the exact resulting dataset; navigation retains the report, Undo hides it and Redo restores it, while a different dataset never displays it. **BH059 (P1):** a delayed roll response previously replaced a newly imported company or discarded a stock edit made during the request. Every one of the 15 engine-result replacement call sites now supplies the dataset the action started from. The store refuses a changed working copy with an actionable message instead of overwriting it. This covers buying, stock postings, firming, forecast/S&OP release, promises, scheduling, levelling and buffer application.

Both original browser reproductions failed before repair. Three persistent browser regressions now pass: report ownership/undo/redo, company switching during a delayed roll, and a concurrent stock edit surviving the response and reload. TypeScript checking and the production Vite build pass. This brings the cumulative total to **54 repaired logic defects plus one native runtime mitigation**. [CI run 36795517184](https://github.com/Hasen1506/Claude-versioned/actions/runs/36795517184) passed **574 engine tests and all 36 browser workflows**, lint, reproducible examples, API type checking and the production build on the exact code merged in PR #8. The planner's place/product-group scope regression also passed independently.

Three independent manufacturing chain cases use partial receipts of 1, 8 and 19.5 units. For a 20-unit sales order, 2 B + 1 C per A and a 2-hour setup plus 0.5 hours per A, the plan requires B40/C20 and 12 machine hours. B at INR10, C at INR5 and machine time at INR100/hour produce INR1,700 cost against INR2,000 revenue and INR300 margin. Firming reproduces the plan without duplicate proposals. Purchase receipts, a partial production roll, completion and shipment leave all three stock balances at zero. Reversing the shipment restores A20 and the sales order while B/C remain consumed; repeating the roll is idempotent. All three cases passed, as did the existing password recovery and unused-session expiry checks (five focused cases total). These are engine/API proofs; the entire manufacturing journey has not yet been completed manually through the UI.

The in-app browser's confirmation handling interrupted the manual walkthrough. An isolated automated browser run reproduced and verified the two client defects; the browser tooling interruption is not recorded as an application defect.

### User-perspective continuation

The next pass reproduced and repaired BH055–BH057 in guided setup: stale displayed values after undo, silent coercion of invalid product values, and loss of explicit zero prices/costs. These production fixes are merged to main through [PR #7](https://github.com/Hasen1506/Claude-versioned/pull/7), merge `bac9d8892484279ecda92ea7268234c316719b98`. The cumulative count is **52 repaired logic defects and one native runtime mitigation**. Four new browser regressions passed locally. Full [CI run 36739886592](https://github.com/Hasen1506/Claude-versioned/actions/runs/36739886592) passed **571 engine tests and 33 browser workflows**, lint, reproducible examples, API type drift checking and the production build. The earlier PR #6 counts below remain historical evidence for that repair pass.

The public Pages URL also returned 404; its deployment workflow failed before building because the Pages site was not configured. The Render host opened the app. This operational issue remains open. The [user workflow/product audit](scp/docs/PRODUCT_AUDIT.md) records direct walkthrough evidence, remaining section coverage, official competitor references and a proposed target-market hypothesis.

| Verification | Result |
|---|---|
| Full engine suite | 571 passed on Windows and in Linux CI; zero failures/errors/skips |
| Earlier focused functional/API/file regressions | 369 passed; 11 unrelated authorization/SSO cases deselected |
| New persistent regressions | 37 passed across the two repair passes; included in the current 571-case engine suite |
| Inventory/S&OP solver checks | 35 passed, including comparison against brute-force optima |
| Actual TypeScript state/date tests | 5 passed |
| Save/recovery races and controls | 6 passed |
| Full browser suite | All 29 workflows passed in Linux CI, including all nine Proof scenarios |
| Static checks | Python lint and TypeScript build check passed |
| Production client | Vite build passed; large-chunk advisory only |
| API types and examples | API schema regenerated; example generator produced no changes |

Interaction and solver cases overlap the full engine suite; do not sum them as unique coverage. The focused import/file gates run the actual TypeScript code in Chrome. The final publication run tested the complete 29-workflow browser suite. Testing is not exhaustive.

Before-repair evidence remains in the earlier audit archives and repair logs. The last pre-mitigation engine run terminated with a native Windows exception; the passing result above is a separate run after the solver change. The mitigation uses the documented [HiGHS thread limit](https://github.com/ERGO-Code/HiGHS/blob/master/docs/src/options/definitions.md#threadsid-option-threads); its explanation of the native failure is an inference from the observed stack and successful retests.

## What changed

- Merge identities now follow the proper supplier/order keys, retain repeated observations and update nested foreign references when an added object is renumbered.
- Malformed patches, non-finite inputs and bad company names return client errors; warm and cold reference reads enforce the same patch sizes.
- Reversals cancel final flags and restore original orders after closure. Snapshots preserve full component targets and promises across partial rolls. Sales reversals undo the original history/accuracy contribution.
- Production consumption uses the effective BOM, including scrap, phantoms and fixed quantities. Shortening retains already-used quantities; cumulative purchase receipts and fractional firm quantities are preserved.
- Inventory postings preserve setup stock, enforce selected-lot balances and keep serial identities through issues, counts, transfers and stock type changes. Closed transfers still show unreceived goods in transit.
- Forecast roll-forward/accuracy uses MRP workdays. S&OP release preserves forecast outside its window. Actual delivery dates use the same lane priority as promising.
- Finance values served quantities at their originating order prices. S&OP tracks price/priority segments so constrained profit plans choose the correct order values, including explicit zero prices.
- Schedule feedback updates components when a start crosses engineering validity, preserves existing targets on ordinary date moves and refuses engineering revision changes after components have been issued.
- CSV/XLSX decoding, routing exports and partial multi-mode lane imports preserve their data. Save/load and overlapping planning responses are guarded against stale results. Setup dates use the local calendar.

## Finding status

Additional merged findings from the user walkthrough:

| ID | Priority | Finding | Current status |
|---|---|---|---|
| BH055 | P2 | Guided setup shows edited values after undo restores different saved values | Repaired in PR #7; browser regressions passed |
| BH056 | P2 | Product creation silently discards negative prices and rounds fractional shelf lives | Repaired in PR #7; browser regressions passed |
| BH057 | P2 | Guided product creation and edits lose explicit zero prices and costs | Repaired in PR #7; browser regressions passed |

| ID | Priority | Finding | Current status |
|---|---|---|---|
| BH001 | P1 | Reordering supplier records loses a purchasing block | Repaired; regression passed |
| BH002 | P1 | Concurrent rescheduling duplicates a sales order | Repaired; regression passed |
| BH003 | P1 | A renamed product's stock stays attached to the other product | Repaired; regression passed |
| BH004 | P2 | Infinite opening stock passes readiness and suppresses supply | Repaired; regression passed |
| BH005 | P2 | A malformed company name produces an HTTP 500 | Repaired; regression passed |
| BH006 | P2 | An @-prefixed local company cannot manage its worklist | Repaired; regression passed |
| BH007 | P2 | An older planning request overwrites a newer completed result | Repaired; regression passed |
| BH008 | P2 | The suggested Monday becomes Sunday in eastern timezones | Repaired; regression passed |
| BH013 | P1 | Serial postings accept duplicate and nonexistent serial numbers | Repaired; regression passed |
| BH014 | P1 | Automatic shipment chooses a serial held in quality inspection | Repaired; regression passed |
| BH015 | P1 | An issue spanning batches repeats the complete serial list on every movement | Repaired; regression passed |
| BH016 | P2 | Malformed save patches cause HTTP 500 | Repaired; regression passed |
| BH017 | P2 | A cached planning read skips unchanged-list size checks | Repaired; regression passed |
| BH018 | P1 | Reversing a final partial delivery still closes its order | Repaired; regression passed |
| BH019 | P1 | An order closed by roll-forward never reopens after reversal | Repaired; regression passed |
| BH020 | P1 | Early stock postings discard the initial setup balance | Repaired; regression passed |
| BH021 | P1 | A sales reversal on a later date crashes roll-forward | Repaired; regression passed |
| BH022 | P1 | Imported production orders use a different BOM from planning | Repaired; regression passed |
| BH023 | P1 | Shortening a partially rolled order overstates its open reservations | Repaired; regression passed |
| BH024 | P2 | Repeated purchase-line entries evade the total receipt tolerance | Repaired; regression passed |
| BH025 | P2 | Small positive postings crash after quantity rounding removes every movement | Repaired; regression passed |
| BH026 | P1 | Receiving an un-dispatched transfer changes the goods serial numbers | Repaired; regression passed |
| BH027 | P2 | Firming fractional supply rounds quantities to zero or leaves new shortages | Repaired; regression passed |
| BH028 | P1 | Rolling period forecasts changes the workday demand distribution | Repaired; regression passed |
| BH029 | P1 | S&OP release duplicates or erases forecasts crossing its horizon | Repaired; regression passed |
| BH030 | P2 | Delivery actuals choose a different shipping lane from the promise | Repaired; regression passed |
| BH031 | P1 | Reservation backflush miscalculates fixed parts and extra production | Repaired; regression passed |
| BH032 | P2 | Physical counts change quantities without updating serial identities | Repaired; regression passed |
| BH033 | P1 | Closing a short transfer hides goods still in transit | Repaired; regression passed |
| BH034 | P1 | Negative-stock refusal allows an overdrawn selected batch | Repaired; regression passed |
| BH035 | P1 | Finance and S&OP ignore the accepted sales-order prices | Repaired; regression passed |
| BH036 | P1 | Moving production across an engineering date keeps the obsolete components | Repaired; regression passed |
| BH037 | P2 | The routing spreadsheet export cannot pass its own import preview | Repaired; regression passed |
| BH038 | P1 | Importing a lane update silently deletes its alternative transport modes | Repaired; regression passed |
| BH039 | P2 | Version comparison drops valid history rows with the same date | Repaired; regression passed |
| BH040 | P2 | Closing a split-promised order changes the quantity confirmation KPI | Repaired; regression passed |
| BH041 | P2 | CSV delimiter detection misreads punctuation inside quoted headers | Repaired; regression passed |
| BH042 | P2 | Excel 1904 date system imports dates about four years early | Repaired; regression passed |
| BH043 | P2 | Valid relative worksheet paths fail to open | Repaired; regression passed |
| BH044 | P1 | Late save/adopt response replaces a newly opened working copy | Repaired; regression passed |
| BH045 | P1 | Merge discards valid duplicate observations | Repaired; regression passed |
| BH046 | P1 | Stock type changes lose serialized inventory identities | Repaired; regression passed |
| BH047 | P1 | Repeated native solver calls can terminate the Windows process | Mitigation verified |

| BH048 | P1 | Restoring the previous database overwrites its recovery source | Repaired; regression passed |
| BH049 | P1 | An interrupted restore truncates the current database | Repaired; regression passed |
| BH050 | P2 | Recovery to a new server directory fails | Repaired; regression passed |
| BH051 | P2 | Backup paths containing URI punctuation cannot be checked | Repaired; regression passed |
| BH052 | P1 | The recovery copy drops committed WAL pages | Repaired; regression passed |
| BH053 | P2 | Repeated placement selections inflate the inventory value change | Repaired; regression passed |
| BH054 | P2 | Forecast release rounds away valid fractional demand | Repaired; regression passed |

## Newly uncovered findings

### BH041 — CSV delimiter detection misreads punctuation inside quoted headers

**Before:** Export comma-separated columns with semicolons or tabs in a quoted header. The reader selected the punctuation in the header as the delimiter.

**Repair:** Count delimiter characters only outside quoted cells; quote semicolons/tabs on export. All 13 file-decoding gates pass.

### BH042 — Excel 1904 date system imports dates about four years early

**Before:** Open stored and deflated XLSX workbooks with date1904 enabled. A 5 January 2026 date was decoded using the 1900 epoch.

**Repair:** Read workbookPr.date1904 and choose the correct date epoch, including Excel’s 1900 leap-year offset.

### BH043 — Valid relative worksheet paths fail to open

**Before:** A worksheet relationship points to worksheets/./sheet1.xml. The file exists but the ZIP lookup fails.

**Repair:** Resolve dot segments in the worksheet relationship before looking up the sheet.

### BH044 — Late save/adopt response replaces a newly opened working copy

**Before:** Begin saving company A, then open B, reopen A, load a scenario or close the company before the response returns. Four of six save/recovery cases fail before repair.

**Repair:** Guard success, failure and server-save adoption with the working-copy load epoch. All six save/recovery gates pass.

### BH045 — Merge discards valid duplicate observations

**Before:** Merge unchanged history or anonymous demand with two same-date rows of quantities 10 and 20, with one input reordered. The original merge retains only 20.

**Repair:** Index every observation using stable occurrence keys. Both rows survive merges and reordering; regression evidence retained for both collections.

### BH046 — Stock type changes lose serialized inventory identities

**Before:** Release one unit of quality stock into unrestricted stock. Both status movements carry no serial numbers, leaving identities attached to the wrong stock type.

**Repair:** Select and carry the same available serial on both status movements; reject fractional quantities, duplicate serials and identities outside the selected lots.

### BH047 — Repeated native solver calls can terminate the Windows process

**Before:** An engine run ends with Windows access-violation exit -1073741819 inside SciPy MILP. Prior logs sometimes emitted the same diagnostic while completing.

**Repair:** Limit HiGHS to one native thread per solve while retaining Python-level independent-group concurrency. The worker-lifecycle regression, 35 solver cases and full engine suite pass after the change. Thread oversubscription/lifecycle is an inferred cause of the original native crash. The final suite passes on both Windows and Linux; the additional initialization regression is described below.

## Compatibility and limits

Existing datasets remain readable. Newly closed orders retain snapshots and delivered schedule lines so they can be reopened correctly. Older imported closed-order records that lack an original-order snapshot cannot reconstruct missing source metadata automatically; the repair does not invent that metadata.

New persistent regressions are in `scp/engine/tests/test_functional_repairs.py`, `test_recovery_edges.py`, `test_release_edges.py` and `test_solver_startup.py`. Unfixed authorization/SSO findings BH009–BH012 are outside the requested functional scope. Windows and Linux engine runs and the full Linux browser suite are verified. macOS and the optional real TimesFM model are not newly exercised.


## Merge preparation and additional logic audit

The publication pass found and repaired seven more defects, BH048–BH054. All are changes to application code, supported by 16 new persistent regressions: eight recovery checks, seven forecast/placement checks and a fresh-process solver sequence. The final expanded engine suite passed all 571 cases locally. The corrected live Proof workflow also passed, exercising all nine scenarios; final publication CI passed the complete 29-workflow browser suite.

### BH048 — Restoring the previous database overwrites its recovery source

**Before:** Restore a backup, then restore the returned `.before-restore` file to undo it. The function copied the current database over that same source before reading it, so the undo restored the wrong data.

**Repair:** Stage and validate the incoming backup first. Preserve every existing recovery file by choosing a new destination suffix. Restoring the previous copy now restores its original contents.

### BH049 — An interrupted restore truncates the current database

**Before:** Inject a disk-write failure while copying the replacement: the live file contains only `partial database` afterwards.

**Repair:** Complete and validate a temporary copy on the target filesystem before atomically replacing the destination. Fault tests cover an interrupted copy and a refused final installation; both preserve the current database and clean staging files. This tests I/O failures, not every possible OS/power-loss boundary.

### BH050 — Recovery to a new server directory fails

**Before:** Restore a valid backup into a target whose parent directories do not exist. The operation raises `FileNotFoundError` instead of rebuilding the server state.

**Repair:** Create the destination directory after validating the source.

### BH051 — Backup paths containing URI punctuation cannot be checked

**Before:** Check a valid database named `company #1.sqlite`. The SQLite URI treats the filename punctuation as a URI fragment and opens the wrong path.

**Repair:** Convert the resolved filesystem path with `Path.as_uri()` before adding the read-only query, preserving its filename.

### BH052 — The recovery copy drops committed WAL pages

**Before:** A stopped writer leaves a committed company update in SQLite's WAL. Restore another backup: the kept previous database contains the earlier company name because only its main file was copied and the WAL was removed.

**Repair:** Use SQLite's backup API to snapshot the previous database, including its committed WAL pages, before replacement. The regression uses a deliberately stopped writer against an isolated temporary database.

### BH053 — Repeated placement selections inflate the inventory value change

**Before:** Apply the same stocking-stage key two, three or five times. The final stock policy is identical but the reported value change is multiplied: a 750 change becomes 1,500, 2,250 or 3,750.

**Repair:** Preserve selection order while deduplicating keys before applying/reporting recommendations.

### BH054 — Forecast release rounds away valid fractional demand

**Before:** Release constant weekly forecasts for a product measured in kilograms. A 0.0004 weekly forecast disappears, while other valid six-decimal quantities are rounded to three decimals. Independent constant-history expectations distinguish this from the intentional whole-unit policy for EA products.

**Repair:** Write the computed released quantity without the extra three-decimal rounding. Whole-unit forecast rounding remains controlled by the product's base unit.

### BH047 follow-up — Native solver initialization depends on call order

Publication CI passed all 555 engine tests and 28 browser workflows, but the Proof workflow exposed an interaction introduced by the thread-limit mitigation. In a fresh server, the S3 scenario's independent SciPy LP initialized the global scheduler with automatic threads; later inventory MILPs requesting one thread returned `HiGHS Status 0: Not Set`. S5 and S9 then failed nine checkpoints despite being valid problems. A fresh-process S3→S5→S9 sequence reproduces the failure independently of browser timing.

The independent LP now uses the same single-thread setting. Inventory propagates native solver errors as errors rather than labeling an uninitialized solver as an infeasible planning problem. The added fresh-process sequence passes. This is a correction to BH047's mitigation, not an additional inflated bug count.


Final verification: [GitHub Actions run 36733258631](https://github.com/Hasen1506/Claude-versioned/actions/runs/36733258631) passed engine and web jobs on the code merged by PR #6. The final documentation update changes only this audit.
