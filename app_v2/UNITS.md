# UNITS.md — the units contract ledger (V2-5)

One table per boundary. **Rule #1: do not trust the suffix** — `yield_pct` is a
FRACTION, `hold_pct` is a PERCENT. Trust this ledger; `tools/units_lint.js`
enforces it (every unit-suffixed key a jsx file sends across the JS→Python
boundary must have a backticked row here, or the gate's lint layer fails).

Conventions: "fraction" = 0–1 used raw by python; "percent" = python divides
by 100 (or multiplies ₹ by pct/100). "Converted where" names the ONE sanctioned
conversion site — converting anywhere else is a bug even if the math agrees.

## 1 · Percent vs fraction at the python boundary (the trap table)

| key | meaning | sent as | python proof |
|---|---|---|---|
| `tax_rate` | corporate tax | **PERCENT** (25) | capital_structure.py:34 & finance.py:220 `/100` |
| `hold_pct` | annual holding, % of unit cost | **PERCENT** (18–24, from part `b.hold`) | meio.py:113, procurement.py:438 `/100` |
| `mape_pct` | forecast error | **PERCENT** (8–15, from `p.mape`) | profitmix.py:65, montecarlo.py:89 `/100` |
| `bcd_pct` `sws_pct` `igst_pct` `insurance_pct` | customs duty stack, % of base | **PERCENT** (10 / 10 / 18 / 0.5) | finance.py:38–47 `×pct/100` |
| `shutdown_threshold_pct` | line-shutdown utilisation trigger | **PERCENT** (25) | production.py:525 default 25 |
| `carry_rate_pct` | per-NODE carry (meio network nodes) | **PERCENT** (24) | procurement.py:613 |
| `yield_pct` | process yield — **fraction despite the name** | **FRACTION** (0.95–0.98, `skuYield`) | procurement.py:377 `0.95` raw |
| `max_ot_pct` | OT ceiling, share of regular hrs — **fraction despite the name** | **FRACTION** (0.25) | aggregate.py:118 default `0.25` |
| `carry_rate` | annual cost of frozen money (WACC + spread) | **FRACTION** (~0.2395, `carryRate(cfg)`) | procurement.py:53 `0.24` raw |
| `premium_pct` | V5-3 backup-lane spot uplift on landed cost (`parts[].backup`) | **PERCENT** (12, governed `config.supBackupPremiumPct`) | procurement.py `bk_unit_cost = cost × (1 + premium_pct/100)` |
| `split_bridge_buffer_pct` | V5-4 safety over-sizing of the fast-lane bridge in a deadline mode split | **PERCENT** (15, governed `config.splitBridgeBufferPct`) | transport.py `_deadline_split` `need_kg = gap_days × burn × (1 + buffer_pct/100)` |
| `salvage_rate` | recoverable share of obsolete stock | **FRACTION** (0.8) | montecarlo.py:131 raw |
| `wdv_rate` | written-down-value depreciation | **FRACTION** (0.20) | finance.py:168 raw |

## 2 · Time

| key / field | unit | converted where |
|---|---|---|
| `M.changeover` matrix (UI, data.jsx) | **HOURS** | store.jsx `subMatrix` ×60 → API minutes (the ONE site); ProdChange sends ×60 / displays ÷60 (T3 contract: **UI=hours, API=minutes**) |
| `changeover_matrix` values, `changeover_mins`, sequencing.py `*_min` (`default_min` 30, `mean_co_min`, `total_changeover_min`) | **MINUTES** | consumed raw; sequencing.py docstring declares the contract |
| `cycle_time_by_sku_min` | **MINUTES/unit** | routing `e.cyc` is already minutes (data.jsx); console.jsx profitmixPayload passes through, no conversion |
| `p.cycle` (products) | **MINUTES/unit** | production payload converts to hrs where needed (÷60 inside solvers' hour math) |
| `hrs_per_period`, `ot_cap_hrs`, `wf_ot_cap_hrs`, `avail_hrs_per_week`, `line_cap_hrs` | **HOURS** | from governed `planning.hrsPerShift` × shifts × workdays (hours audit, V2-13 follow-up) |
| `labor_week_hrs` | **HOURS/worker/week** | store.jsx productionPayload = wdays × hrsPerShift; production.py:385 |
| `capacity_hours` · `hours_per_agg_unit` | **MACHINE-HOURS/period** · **HOURS per weighted agg unit** | V4-2 aggMachineResources (plan.jsx) = wd × hrsPerShift × shifts × 4.33 × OEE · Σ(cyc/60)·demand ÷ Σ lw·demand; aggregate.py consumes raw ((P+O)·h ≤ H) |
| `rehire_notice_hrs` | **HOURS** (80 = 2wk×40) | production.py:526 — governed via config.prodRehireNoticeHrs (Production GovField, 2026-06-11); payload 80 is the seed fallback |
| `frozen_weeks`, `shift_weeks` | **WEEKS** | app.py rolling re-plan (:116, :115) |
| `deadline_days`, `pay_term_days`, `vmi_target_stock_days`, shelf life | **DAYS** | transport.py / policy raw; shelf days↔weeks handled in policy sizing |
| `planning_horizon_months` | **MONTHS** (12) | profitmix.py:39 slices the forecast; `p.demand` is ANNUAL so weekly MPS ≈ demand/52 (V2-1) |

## 3 · Demand & horizon grain (V2-13 contract)

| field | unit | contract |
|---|---|---|
| `p.demand` (products) | **units/YEAR** | every per-period use must convert via a rate, never `/T` of an arbitrary horizon |
| `getItemDemand` seed | units/period = `annual × periodDays/364`, periodDays = horizonDays/T | store.jsx (V2-13a) — rate is horizon-invariant |
| schedule basis | **WEEKS regardless of grain** | `productionScheduleHorizon` converts grain→weeks pre-fence; daily series Σ7, monthly ÷4.33 |
| aggregate plan periods | **MONTHS** (`M.aggregate.months`) | fixed by construction; see §4 holding ÷12 coupling |
| `M.lines[].cap` | units/**MONTH** | store.jsx:1195 ÷4.33 → u/week for production payload; the per-line `cap` itself is DEAD to production.py (linecap is its consumer — V2-11) |

## 4 · Money

| key / field | unit | contract |
|---|---|---|
| all API money | **₹ (INR, absolute)** | ₹L / ₹Cr are DISPLAY formatting only — never sent |
| `holding_cost_per_unit` (aggregate) | **₹/unit/MONTH** | `aggHoldingPerUnit` = carryRate × demand-weighted blended effUnitCost ÷ 12 (V2-4). The ÷12 is COUPLED to aggregate periods being months — if periods ever change, this divisor must follow the period length |
| `ordering_cost` | **₹/PO** | per order placed, not per unit (master `S`; the 120 literal at store.jsx:825 is V2-9) |
| `exchange_rate` | **₹ per unit of foreign currency** (84) | finance.py:24 landed-cost; FX scenario factor applies in store `fxFactor` |
| `hire_cost` / `fire_cost` | ₹/worker EVENT | aggregate.py one-time per headcount change |
| `reg_cost_per_unit` / `ot_cost_per_unit` / `backorder_cost` | ₹/unit | aggregate; seeds live in plan.jsx PLAN_PARAMS (V2-4 aligned store fallbacks) |
| `rework_cost_per_unit` | **₹ per FAILED unit** (not per unit started) | V4-6 (Q24): production.py charges `rw × (1 − fy) × x[k,l,t]` — the ₹/fail × fail-share fold happens in PYTHON; JS sends the raw master `p.rework` (₹/fail) |
| `opening_inventory` (production) / `init_inventory` (procurement parts) | item's OWN unit (FG u / part uom) | V5-1: both now come from the network.onHand LEDGER (onHandFor) — FG scoped by config.netFgScope (plant+wh default, DRP), RM at plant+wh. Absent part key ⇒ procurement.py FABRICATES avg×(lt+1) — the ledger send exists to kill that path |
| cost definitions | typed `p.cost` ⊂ `effUnitCost` (ONE truth, V2-2) ⊂ landed (sourcing, +duty+freight+FX) | margin chain documented in blueprint Q7/Q12 |

## 5 · Mass & quantity

| key / field | unit | contract |
|---|---|---|
| `weight_kg`, `monthly_weight_kg` | **KG** | store transport payload via `skuWeightKg` (mix-accurate, LG-2); tonnage = display ÷1000 |
| `cost_per_kg` | **₹ per KG** | mode tariff (V3-4): Logistics GovField `config.modeTariffs[mode]` → `params.mode_overrides[mode].cost_per_kg`; same unit as transport.py MODE_SPECS — NO conversion. Distinct from lane `rate` (₹ per KM, cost_matrix = rate × km) |
| aggregate plan units | **labor-weighted units** (cycle × hands-on %, demand-weighted mean-normalised) | NOT physical units — the 1,260 physical vs 1,124 weighted opening-FG case; conversion at `aggLaborWeights`, headline UI shows PHYSICAL |
| production gantt / linecap / profitmix quantities | **physical units** | no weighting |

*Lint scope (honest):* `units_lint.js` requires a row for unit-suffixed **payload
keys written in jsx** (bare, quoted, or ES6-shorthand object keys). Member-access
reads of result fields (`r.equity_weight_pct` — percent, capital_structure.py:79)
and python-internal fields don't trip it but may be documented here anyway.
