# Full-site design audit — app_v2 (phase iii)

**Date:** 2026-06-12 · **Build:** local main on top of 6135c32 · **Method:** live site at `localhost:5000`,
headless Chromium 1440×900, every stage screenshotted in **fresh-boot** (empty/pre-solve), **guided** and
**solved** (after one real ▶ Re-plan spine run) states, scroll-tiled so nothing below the fold was skipped.
All screenshots in [`assets/`](assets/) — `00-onboarding-wizard`, `fresh-<stage>_pN`, `guided-<stage>`,
`solved-<stage>_pN` (+ production subtabs). Zero pageerrors on every page in every state.

Two personas judged each page **without consulting any docs**:

- **P1 — first-day senior design lead.** Has never seen the product. Can they understand what the page is
  for, trust what it shows, and finish the core action?
- **P2 — experienced design lead.** Knows the product domain (planning tools) and judges craft:
  hierarchy, consistency, states, conversion paths.

Issue tags: `[understanding]` `[trust]` `[conversion]` — plus a specific fix on every issue.
Severity: **H** (blocks/breaks the core promise) · **M** (slows or confuses) · **L** (polish).

---

## 1 · Verdict in one paragraph

The product's bones are unusually strong for a pre-design-pass tool: every page states what it is in plain
English, empty states are honest (dashes + "re-plan to fill", never fake numbers), provenance is everywhere
(SEED / DERIVED / SOLVED chips, USED-BY chips, the Parameter Registry), and the solved state genuinely
answers each tab's headline question. The failures are not visual taste — they are **state-vocabulary
failures**: the same action has three names, the same count appears as 6, 8, 9 and 16, and the app's own
one-click success path immediately yells STALE at the user eight times. P1 can find the Run button and get
a plan in under a minute (excellent), but the first thing the product tells them after succeeding is that
eight things are now wrong — and the suggested remedy (re-plan) won't fix them. That single loop is the
biggest conversion risk in the product.

---

## 2 · Fixed on the spot (5 fixes, all verified live after the change)

| ID | Where | What was wrong | Fix |
|----|-------|----------------|-----|
| DA-1 **H/trust** | `plan.jsx:170` | "VIEWING ▸ PORTFOLIO AGGREGATE" chip rendered **black-on-black** in the default MONO theme (`color:C.onAc` on `background:C.ink`; both resolve `#0a0a0a`) — an unreadable black rectangle opened the Plan page (see old `solved-plan_p0`) | `color:C.paper` (matches the k-tone pattern in lib.jsx) |
| DA-2 **H/trust** | `console.jsx` ×5 | Interpret cards (Procurement, Reorder Policy, Production Gantt, Monte-Carlo, Capital) rendered **hard-coded seed tables pre-solve with no seed marking** — "₹3.12 Cr", a 5-row PO register, 3 investments with FUND/DEFER verdicts, all indistinguishable from live results | `<Provenance kind="seed"/>` chip added to every unsolved branch (the established house pattern) |
| DA-3 **M/understanding** | `home.jsx` ×5 | KPI empty-state sub-copy said **"run loop"** while the only button says **"Re-plan spine"** — two names for one action on one screen | sub-copy → "re-plan to fill" |
| DA-4 **M/conversion** | `data.jsx` guidedChecklist.home | Guided checklist step 1 was "work the exception inbox — red first" — a first-run user **has no exceptions and no solves**; the checklist pointed at the wrong first action | reordered: re-plan first, freshness second, inbox third |
| DA-5 **M/understanding** | `chrome.jsx` ribbon | Two ribbon chips were both labelled **"PLAN"** (aggregate→Plan and linecap→Plan) — reads as a duplicate/bug | linecap chip labelled **LINE CAPITAL** (matches Home's lifecycle card name); nav unchanged |

---

## 3 · The one systemic issue (H — recommendation, not spot-fixed)

**Running the spine immediately marks 8 solves stale — and the banner's remedy is wrong.**
Observed (`solved-home_p0/p1`): after a clean 6/6 run, Home shows "8 SOLVES STALE — RE-PLAN TO REFRESH",
the exception cockpit shows 8 amber "stale because you changed committed demand" rows drowning the one real
red RISK exception, the lifecycle footer reads the impossible-looking "8/8 have inputs · 6 fresh · 8 stale",
and Plan/Scenarios each open with their own amber STALE banner. Cause: the loop's own demand-commit (LP-A)
legitimately stales every **non-spine** consumer (policy, rolling, meio, meionet, cvar, profitmix,
transport…) — but none of those 8 are in the spine, so "re-plan to refresh" cannot fix them, and a user who
obeys the banner loops forever.

- `[trust]` The product's success state looks like a failure state. First-session abandonment risk.
- `[understanding]` 6 vs 8 vs 16 counts collide in one viewport with no key.

**Specific fix (recommended):** split staleness into two classes at the derivation layer —
*spine-stale* (re-plan fixes it) vs *advisory-stale* (open that tab / run that engine). Banner copy becomes
"N advisory solves out of date — open their tabs to refresh"; exception cockpit collapses mechanical
post-loop staleness into ONE row ("8 advisory engines follow the new committed demand — refresh on open");
the lifecycle footer states the denominator ("6 fresh of 6 spine · 8 advisory stale of 10 tracked").
This touches `markStale`/freshness maps and exception derivation — too load-bearing for a spot fix.

---

## 4 · Page-by-page findings

Legend: ✔ = strength worth keeping · numbered = issue `[tag·severity]` → fix.

### 00 Onboarding wizard (`00-onboarding-wizard`)
✔ Six plain-language questions, defaults preselected, consequence note ("Your answers keep every engine
on"), skip hatch, "change any time in Setup" reduces commitment anxiety. Best-in-class first screen.
1. `[understanding·L]` "Right-size the **workspace**… keep every **engine** on" — both nouns are insider
   vocabulary on the very first screen. → "Six quick answers so you only see the planning steps your
   operation needs."

### Home / Command Center (`fresh-home`, `guided-home`, `solved-home`)
✔ Honest empty KPIs; run-log with per-step ms; value ledger empty states; exception cockpit concept.
2. `[understanding·M]` Spine-count chaos: "6 STEPS" (Home button), "RUN SPINE · 6 OF 16" (Console button),
   "9 STEPS · PROFILE-GATED" (Console spine card), "8/8 READY" (lifecycle). Each is locally true; nothing
   reconciles them. → one sentence under the lifecycle header: "The spine re-plans 6 of these; Profit-Mix
   and Line-capital refresh from their own tabs," and pick ONE public count for buttons.
3. `[trust·M]` Value ledger: "VALUE IDENTIFIED" table shows ₹2,06,344 (Monte-Carlo) while the headline
   card "ANNUAL VALUE SURFACED" still reads "— · run the loop" — value below, "no value yet" above.
   → if exposure-quantification deliberately doesn't count as surfaced value, say so in the card sub
   ("savings only — risk quantification listed below").
4. See §3 (systemic staleness).

### 01 Setup (`fresh-setup_p0–p3`)
✔ MSME tier derived card (formula + the 43B(h) payables consequence) is a superb domain trust signal;
TN holiday table solved by `calendar.py` with RECOMPUTE; **Parameter Registry is the app's best surface**
(value · SEED/DERIVED · n-solves feeds · jump-to-editor).
5. `[understanding·M]` One card mixes two input affordances: white bordered inputs (name, currency, state)
   beside grey GovField boxes (tax, service level). Grey reads "disabled" to P1. → unify field chrome, or
   add the ◇SEED chip to the white inputs too so grey ≠ special.
6. `[understanding·L]` Kicker says "WACC/CAC live in Finance" — CAC is never defined on the page. → spell
   it or drop it.
7. `[layout·L]` p2: large blank region right of the FROZEN/SLUSHY/SCHEDULE-fence column under the workday
   bar — visibly unbalanced. → move the HORIZON CONTRACT explainer card into that slot.

### 02 Products (`fresh-products_p0–p3`)
✔ Editable catalog grid with OPTIMIZED (LP/MILP) vs AUTOPILOT (S,S) method badges; yield card's
"NO DATA — USING TYPED SEED → log a batch to switch ASSUMPTION → MEASUREMENT"; unit-cost rollup with live
derivation and a double-count guard; MTO order book with the profit-mix floor formula.
8. `[understanding·M]` **USED-BY chip walls** (here, Finance worst, Logistics, Plan): ~12 repeated chips
   under every cost field; provenance noise drowns the input. → collapse to one pill "→ feeds 12 solvers"
   that expands on click; keep full chips in EXPERT only.

### 03 Network (`fresh-network_p0–p4`)
✔ True-topology SVG (explicitly "not a linear chain"); lane grid; supplier master with OTIF + risk chips;
contract step-price sparklines with "solver buys ahead of the step" notes; on-hand matrix with active-row
highlight + netting-scope toggle; scheduled receipts with arrives = release + lead.
9. `[understanding·L]` Trunk-cap column renders as empty boxes; "blank = uncapped" exists only in a
   footnote below the table. → placeholder "∞" in the empty input (needs a NumInput placeholder prop —
   small component change, queued not spot-fixed).
10. `[understanding·L]` Node capacity shows "0 · —" for customers/suppliers (capacity is meaningless for
    them). → render "n/a" for node types without storage.

### 04 Demand (`guided-demand`, `solved-demand_p0–p6`)
✔ The strongest stage. Winner strip (ARIMA · holdout 5.7% · EASY TO FORECAST · COMMIT OPEN); DATA TIER
honesty ("on seed history the winner's MAPE is illustrative, not earned on your demand"); import-target vs
override-grid distinction; sensing card (pattern CANNIBALIZATION conf 71% → commit rewrites near-term
demand); FVA bars (naive 11.7% vs winner 5.7%); control triggers; 9-box ABC/XYZ; lifecycle shaping with
"NO CHANGE TO APPLY" honesty.
11. `[understanding·M]` Freshness widget reads "0/6 FRESH · 5 stale" — 0+5≠6 (the 6th is idle/never-run);
    P1 reads it as a bug. → "5 stale · 1 never run" or "0 fresh of 6".
12. `[trust·M]` After the loop runs, Home's exceptions say "you changed **committed demand**" while
    Demand's portfolio strip still shows "0/6 committed" — two meanings of "committed" (loop-written
    series vs planner consensus commit). → rename the strip "0/6 consensus-committed", or have LP-A's
    write show as "auto-committed by loop" chips per SKU.
13. `[understanding·L]` Five stacked full-width banners before the first actionable card (product bar,
    portfolio, item, question, WHAT IS THIS). Each earns its place individually; together they push the
    fold. → merge the item strip into the product bar.

### 05 Plan (`fresh/solved-plan`, `guided-plan`)
✔ "WHAT IS THIS?" explainer is the best plain-language solver framing in the app; 13 GovFields with units
and seeds; labor-content table with the automated-SKU worked example; VIS-1 thermometer; capacity & duals
section with the "no binding rows — workforce slack everywhere" honest empty.
14. *(was the DA-1 black-on-black chip — fixed.)*
15. `[understanding·L]` Capacity-vs-demand chart: capacity dashed line sits far above near-zero production
    bars (opening stock covers demand, production ≈ 0 except P6) — honest but reads as a broken chart at a
    glance. → annotate "opening stock covers P1–P5; first build P6" directly on the chart when
    production≈0.

### 06 Production (`fresh/solved-production*`)
✔ Question strip answers itself solved ("FEASIBLE — 10 IDLE WK ON THE BUSIEST LINE"); stage tree with
BOTTLENECK chips and slowest-stage capacity footers; derived-capacities table; VIS-6 feasible region with
the real-payload 2-SKU restriction.
16. `[hierarchy·L]` Red "× line" delete is the most prominent control on each line card while "+ Add
    stage" is a dashed ghost — destructive > constructive. → demote delete to ghost, promote add.
17. `[polish·L]` VIS-6 optimum label "(2,840, 4,120) · ₹33._" clips at the chart edge. → clamp label
    inside the viewBox.

### 07 Sourcing (`fresh/solved-sourcing`)
✔ RUN/DESIGN split with counts; MILP inputs governed; BOM lead-time ladder with critical path; exception-
based MRP framing ("not a giant grid — only the exceptions surfaced").
18. `[trust·H]` **Loop-solved procurement never hydrates the tab.** After the spine ran (ribbon: SOURCING
    "30 parts", fresh), PO RELEASE PLAN and SHORTAGE FORECAST still show "◇ ILLUSTRATIVE — demo rows, not
    your plan. Run procurement (⚡ above)", and TRUCK-STEP FREIGHT says "RUN PROCUREMENT FIRST". The user
    just ran it; the product denies it. → cards should read the cached portfolio solve (filter to the
    selected item) exactly like the ribbon does; if the per-item view truly needs a per-item solve, the
    copy must say "solved portfolio-wide — open the buy plan, or re-run scoped to this item".
19. `[consistency·M]` Service level renders **0.95** here (and in Scenarios' What-If bot) but **95 %** in
    Setup — same governed token, two display conventions; Products copy says "98% service" while the field
    shows 0.98. → one display convention (percent) with a single conversion at the GovField layer; the
    UNITS.md ledger already defines the boundary.
20. `[understanding·L]` RM-SPEND BUDGET shows "₹ 0" with caption "0 / blank = unbounded"; the registry
    calls the same value "unbounded". A zero that means infinity is a trap. → render "∞ unbounded" in the
    box when 0/blank.

### 08 Logistics (`fresh/solved-logistics`)
✔ PREREQ banner routing master-data edits to Network; levers grouped BY MODEL TERM with the formula
footer; India CoG map; lane×mode matrix with verdict copy ("Rail wins CHN→PUN on cost; Air only survives
on BLR→GGN where the SLA forces speed").
21. `[conversion·L]` MODE SPLIT card is OFF-default with an "ARM MODE SPLIT" button — "arm" undersells
    what it does and sounds dangerous. → "Enable split recommendations (off = one mode per lane)".

### 09 Finance (`fresh/solved-finance`)
✔ Question strip (blended hurdle · carry · EVA, fDERIVED); A–F section tabs with counts; capital stack
visual; WACC-curve and covenant cards with instructive empty states.
22. = issue 8 (chip walls — worst instance: ~60% of the equity/debt card area is chips).
23. `[understanding·L]` NPV headline slot shows "run hurdle" styled like a value in the yellow box —
    reads as a label, acts as nothing (the real button is "COMPUTE HURDLE" a screen up). → make it a
    link that scrolls to the hurdle card.

### 10 Console (`fresh/solved-console`)
✔ Spine cards with skip conditions; solver network; Anatomy Lab is a flagship surface ("does every term
have a source?", "MODELLED BUT NOT WIRED — the 'too much stuff'", "8/8 core terms fed · 9 unwired").
24. *(was DA-2 unlabelled seed results — fixed.)*
25. = issue 2 (count chaos: this page contributes "6 OF 16" and "9 STEPS").

### 11 Scenarios (`fresh/solved-scenarios`)
✔ Branch lab + What-If bot with "a real re-solve, not a parser" note; SF harness lists HONEST COVERAGE
GAPS; question strip carries committed-plan stats with both SOLVED and STALE chips (see §3).
26. = issue 19 (0.95 fraction in the What-If service lever).

### 12 Reference (`fresh-reference`)
✔ Live model map coloured by what actually ran, with the untracked-engines caveat spelled out.
No issues beyond global ones.

---

## 5 · Conversion & onboarding risks — and rectifications

1. **The success-state-looks-stale loop (top risk).** New user follows the wizard → presses the one yellow
   button → gets "8 SOLVES STALE" + 8 amber exceptions + amber banners on the next two tabs they open.
   They cannot distinguish "your plan is fine, advisory engines lag" from "it broke".
   *Rectify:* §3 fix; until then the DA-4 checklist reorder at least sequences the first session correctly.
2. **Sourcing denies the loop's work (top-3).** The most procurement-curious persona (a planner) runs the
   spine, opens Sourcing, and is told their plan is illustrative demo data. They conclude the Run button
   doesn't really work. *Rectify:* issue 18.
3. **Vocabulary tax.** spine/loop/re-plan/solve; committed (two meanings); 6/8/9/16. Every synonym is a
   little withdrawal from the trust account at the exact moment (first session) the balance is lowest.
   *Rectify:* DA-3/DA-5 done; issues 2, 11, 12 remain — worth a single "one name per concept" copy pass.
4. **Seed-vs-real blur at the edges.** The core discipline (◇seed everywhere) is real, but the places it
   slipped (DA-2, issue 18) were exactly the high-stakes result surfaces. *Rectify:* DA-2 done; add a
   model_check rule "every DataTable with literal rows must sit under a seed/illustrative Provenance" so
   the class stays closed.
5. **Expert density as the only mode that's really built.** Guided mode = checklist + fold law, but the
   law folds zero fields today (broad-config coupling) — so P1 sees the full expert wall either way.
   *Rectify:* the chip-wall collapse (issue 8) is the highest-leverage density cut and is mode-independent.

## 6 · What NOT to change

The hard-edged mono aesthetic (2px ink borders, mono labels, yellow accent) is coherent and differentiating
— this audit found zero pages where the *style* was the problem. The honesty furniture (SEED/DERIVED/SOLVED,
USED-BY, formulas-on-cards, honest empties, "ILLUSTRATIVE" labels, Anatomy Lab) is the product's moat;
every recommendation above tightens it rather than sanding it off. Keep the question-strip pattern ("CAN THE
LINES BUILD THE PLAN?") — it is the single best understanding device in the app.

---

*Verification: every claim above was observed in the screenshots in `assets/` (no reasoning-only findings);
the 5 spot fixes were re-verified live in Chromium after the change (probe: ribbon label, KPI copy, guided
order, chip computed-colors, console seed chips) and the touched surfaces re-shot. Gate run after fixes —
see PRODUCT_BLUEPRINT_V3.md phase-iii record.*
