# Claude-versioned functional audit and repairs

Latest continuation: 1 October 2026. The manufacturing form repairs below are locally verified and awaiting publication checks. The preceding [PR #8](https://github.com/Hasen1506/Claude-versioned/pull/8) is merged as `1b9814113486d3aa41ab3ab00466ff77e90c0570`.

Updated 30 September 2026. Audited baseline: `ee0f7d136a25f1f30246fcd886f15db8d5985694`. Fixes merged to main as `aae75e872ac6ae8c419939295d7ad8b0ec82d977` through [PR #6](https://github.com/Hasen1506/Claude-versioned/pull/6).

The continuation covered spreadsheet decoding, save/recovery races and capacity-option appraisal, then repaired the confirmed functional defects. The first continuation added BH041–BH047; merge preparation found seven more logic defects, BH048–BH054. In total, **49 logic defects are repaired and one native runtime failure has a verified mitigation**. These are production application fixes with regression tests. All changes are committed and merged to main through [PR #6](https://github.com/Hasen1506/Claude-versioned/pull/6).

## Verification after repairs

### 1 October continuation: complete manufacturing browser journey

**BH060 (P1):** the partial-production form calculated components independently of the posting engine. For an order of 20 A with a fixed five-unit C component, confirming 8 A displayed/defaulted C2, while automatic posting correctly used C5. Selecting "parts actually used" turned the incorrect default into a stock posting. The form also counted reversed issues as consumption, omitted effective BOM parts on imported orders without reservations, and rounded small defaults to three decimals. It now reads the same component calculation used by production confirmation, including fixed quantities, net reversals, scrap and phantoms, retains six-decimal component defaults and the full open quantity, and offers retry after preview failure. Confirmation waits for a preview matching the current dataset and quantity; late previews are ignored.

**BH061 (P2):** in Asia/Kolkata, the new-order form suggested 11 January for a planning start of 5 January, despite intending seven days later. Its local-midnight-to-UTC conversion shifted the calendar date. It now uses the existing calendar-day helper and suggests 12 January in the tested timezone.

Both original browser reproductions failed before repair. The automated browser manufacturing journey now passes through JSON import, forecast and financial plan, sales promise, three firm orders, two purchase receipts, partial production of 8, weekly roll, remaining production of 12, shipment of 20 and final roll. Independent assertions check B40/C20, a 9–12 January production window, INR1,700 cost, INR2,000 revenue and INR300 margin; the fixture's setup and run rates require 12 machine hours. Exported stocks after the partial roll are A8/B24/C12; final stocks are all zero, with four closed orders and no remaining receipt or sales order. Separate browser checks verify fixed parts after a material-document reversal, the 0.0004-unit production default, preview retry after HTTP failure and rejection of a delayed preview for an older quantity. All four new browser workflows, six new engine/API cases and 62 focused engine cases passed, as did lint, TypeScript checking and the production build. Tests overlap; do not sum them as unique coverage. Full publication CI remains pending at this report revision.

These two repairs bring the implemented cumulative total to **56 logic defects plus one native runtime mitigation**, with merge status stated above. The small-quantity and reversal corrections are grouped under BH060 rather than counted as additional findings. This imported-fixture browser proof advances the execution gate; it does not establish beginner setup from scratch, holiday-calendar accuracy or deployed account recovery.

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
