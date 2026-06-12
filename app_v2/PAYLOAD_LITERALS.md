# PAYLOAD_LITERALS.md — the registered hardcode ledger (V2-12)

Enforced by `tools/payload_literal_lint.js` (gate layer 2): every bare numeric
literal on a snake_case payload key in app_v2 jsx must have a backticked
`key: value` row here, or the gate fails. Governing a value (turning the literal
into an expression) removes it from the scan — the lint then flags the row as
prunable. **Changing a value re-fails until re-registered: drift is a decision.**

Classification: **SEED** = the canonical seed-default the GovField pattern shows
and lets you override (legit literal — it IS the registry value) · **DEMO** =
illustrative master-data rows (proposals/examples), not solver knobs · **STRUCT**
= structural zero/identity, no economics · **TODO-GOV** = a real knob that still
bypasses Setup — the open remainder of the V2 hardcode hunt.

## 1 · Aggregate S&OP seed table (plan.jsx PLAN_PARAMS — SEED)

The one place the Hax-Meal cost levers are seeded; every row surfaces as a
governed field on Plan (V2-4 aligned store fallbacks to THESE numbers).

| pair | note |
|---|---|
| `init_workforce: 42` | heads at horizon start |
| `rate_per_worker: 30` | u/worker/period productivity |
| `reg_cost_per_unit: 820` | ₹/u regular production |
| `ot_cost_per_unit: 1230` | ₹/u overtime production |
| `holding_cost_per_unit: 45` | ₹/u/mo UI seed — store derives carryRate×blended cost (V2-4); override wins |
| `backorder_cost_per_unit: 1500` | ₹/u/period backorder penalty |
| `hire_cost: 18000` · `fire_cost: 25000` | ₹/head one-time |
| `wage_per_worker: 22000` | ₹/head/mo |
| `max_ot_pct: 0.25` | FRACTION (suffix lies — see UNITS.md §1) |
| `min_workforce: 30` · `max_workforce: 60` | heads, labor envelope |
| `backorder_sigma_weight: 0` | V4-1/Q10 rider — 0 = σ-blind legacy; governed GovField on Plan scales backorder ₹ by (1 + w × demand-CV from real per-SKU MAPE) |
| `machine_resources: false` | V4-2 — off = single-resource (worker-time) legacy; ON adds per-line machine-hour ceilings (aggMachineResources) to the aggregate LP |

## 2 · Capital-budget demo proposals (console.jsx CAPEX_PROPOSALS — DEMO)

Illustrative CapEx master rows the knapsack ranks (budget + WACC are governed
from Finance; these are the candidate projects, i.e. data not knobs).

`annual_cash_flow: 3500000` · `useful_life: 10` · `residual_value: 1800000` ·
`annual_cash_flow: 1784000` · `residual_value: 900000` ·
`annual_cash_flow: 2213000` · `residual_value: 1200000`

## 3 · Finance card examples & NPV defaults (finance.jsx)

| pair | class | note |
|---|---|---|
| `credit_spread_slope: 6.0` | SEED | capital-structure curve slope (pp per unit leverage) |
| `max_debt_ratio: 0.8` | SEED | leverage search ceiling |
| `useful_life: 8` · `earliest_period: 0` · `latest_period: 4` · `horizon_periods: 5` | DEMO | timing-flex NPV example card |
| `npv_mc_runs: 400` · `driver_cv: 0.20` | SEED | NPV Monte-Carlo depth/vol seeds |
| `residual_value: 0` · `useful_life: 6` | DEMO | buy-vs-lease buy-leg terms (FIN-1 card inputs) |

## 4 · Store payload builders (store.jsx)

| pair | class | note |
|---|---|---|
| `changeover_mins: 30` | SEED | per-line default for pairs ABSENT from the matrix — V2-6 class-seeds new SKUs so this is now a last-resort only; matches sequencing.py default contract (UNITS.md §2) |
| `cost_cv: 0.05` | SEED | MC part-cost volatility when master has no cost_cv |
| `init_inventory: 0` | STRUCT | MC greenfield start |
| `periods_per_year: 52` | STRUCT | weekly-grain annualisation constant (calendar, not a knob) |


*(`rehire_notice_hrs` (seed 80) — the last TODO-GOV — was GOVERNED 2026-06-11: config.prodRehireNoticeHrs
GovField on Production, token cfg.prod, carried by productionOptsFromConfig; the payload's 80 is now
a seed-fallback expression, no longer a registered literal.)*

## 5 · Sourcing & scenarios (sourcing.jsx / scenarios.jsx / console.jsx)

| pair | class | note |
|---|---|---|
| `hold_pct: 24` | SEED | PERCENT (true-percent family, UNITS.md §1) — fallback when a part has no master `hold` |
| `lead_time: 1` | SEED | single-period fallback in the policy mini-payload |
| `joint_major_cost: 2500` | SEED | joint-replenishment shared truck/admin ₹/cycle (SS-B) |
| `n_scenarios: 300` | SEED | CVaR scenario depth (CI-speed default) |
| `port_handling: 0` | STRUCT | landed-cost leg absent for domestic lanes |
| `planning_horizon_months: 12` | STRUCT | profit-mix annual basis — matches p.demand units/YEAR (UNITS.md §3) |

---
Out of the lint's reach (stated, not hidden): literals inside expressions
(`Number(80)`), camelCase staging objects, and python-side defaults — covered
instead by the per-solver contract tables (blueprint Part 6) and pytest layer.
