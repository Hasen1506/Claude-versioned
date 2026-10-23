# Conformance: the app against the books

Enterprise plan, Phase 8. The tests check the app's numbers against hand-worked ones; this file checks that the
right things are there at all, against references outside the app, and that a person can find them. One section per
area; each row is a concept a practitioner would expect, where it lives, what a person sees, and how it is checked.

**Status:** *there* (in the engine, on a page under a name a planner would look for, tested against an outside
oracle) · *buried* (works, but on a page or under a name nobody would look for) · *partial* (part of it) ·
*missing*.

**References:** S/4HANA planning guide (§ numbers as elsewhere in these docs); ASCM CPIM Part 1 and 2 body of
knowledge; Silver, Pyke & Thomas, *Inventory and Production Management in Supply Chains* (SPT); Graves & Willems
(2000) for multi-echelon service times; the Demand Driven Institute's DDMRP standard; IBP S&OP process.

## 1. Inventory policy

Read against SPT ch. 4–7 and CPIM "inventory management". Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| I1 | ABC classification by value | `demand/pipeline._abc` (cleansed history, company cut-offs) | Demand → each product's segment; Cycle counts by ABC | hand-ranked in test_demand | buried: on Demand, not beside the policy it should drive |
| I2 | XYZ (variability) and the ABC-XYZ matrix | `demand/pipeline` segment (CV², ADI) | Demand | test_demand | buried |
| I3 | Service level per segment | `demand/pipeline.SERVICE_LEVEL`, company table `forecasting.service_levels` | shown as "suggested" on Demand only | — | partial: suggested, never applied; no one place compares it with the target a product actually has |
| I4 | Policy assigned to a whole segment | MRP group shares lot size, strategy, fences | Master data → MRP groups | — | missing for safety stock and service level (an MRP group has neither) |
| I5 | Continuous review, reorder point (s, Q) | MRP type `reorder_point` + fixed or EOQ lot | Products at places → MRP 1 | test_mrp, test_s4_backtest_b | buried: never called (s, Q) or "reorder point policy" anywhere a planner looks |
| I6 | Order-up-to (s, S) | `reorder_point` + `MIN_MAX` to max stock | Products at places | test_mrp | buried |
| I7 | Periodic review (R, S), (R, s, S) | `review_period_days` widens the safety stock only; POQ covers N periods | — | — | partial: R is in the safety-stock formula but orders are not placed on a review calendar |
| I8 | Time-phased (MRP) with safety stock | MRP type `deterministic` | Supply plan | golden, S/4 backtests | there |
| I9 | Safety stock: fixed, days of cover | `plan/rates.policy_safety_stock` | Products at places → safety stock | test_mrp (fixed, days of cover) | there |
| I10 | Safety stock for a cycle service level, demand and lead-time spread: SS = z·√((L+R)σ_d² + d̄²σ_L²) | `plan/safety.statistical_ss` | Products at places; Buffers | hand-worked in test_mrp::test_service_level_safety_stock_formula | there (buried page) |
| I11 | Safety stock for a fill rate (β) via the unit normal loss G(k) | `plan/safety.k_for_fill_rate` | same | test_mrp::test_normal_loss_and_fill_rate_k | there (buried page) |
| I12 | Reorder point suggested: s = d̄·L + SS | — | — | — | missing: the reorder point is typed by hand; nothing says what it should be |
| I13 | Lot size: EOQ, fixed, lot-for-lot, periods, min-max, PPB, LUC, Groff | `plan/lotsize` | Products at places → lot size | test_mrp, test_planning_depth (hand-worked) | there |
| I14 | Multi-echelon placement (guaranteed service, Graves–Willems) | `inventory/gsm` | Supply → Buffers | test_inventory | there (optional tab) |
| I15 | DDMRP buffers | `inventory/analysis._ddmrp`, MRP type `ddmrp` | Buffers; Products at places | test_inventory, test_s4_backtest_b | there |
| I16 | Risk pooling | `inventory/analysis._pooling` | Buffers | test_inventory | there |
| I17 | Intermittent demand: Croston / SBA / TSB forecast | `demand/models` | Demand | test_demand | there |
| I18 | Safety stock for intermittent or lumpy demand (non-normal: Poisson, gamma, bootstrap) | — | — | — | missing: a normal approximation sizes slow movers too |
| I19 | Measured lead-time spread fed to safety stock | EP 4.4 | Buying → suppliers | test_demand_spread | there |
| I20 | Achieved service against the target, per product at a place | — (OTIF is per order and customer) | — | — | missing: no page says "target 95 %, achieved 88 %" |
| I21 | Excess, obsolete and slow-moving stock | `tower/kpis` | Performance | test_tower | there |
| I22 | Holding cost rate and ordering cost | settings `wacc` + `holding_spread`; `ordering_cost` on lot sizing and source | Settings; Products at places | test_mrp | there |
| I23 | Cost of a shortage (to choose the service level by cost) | — | — | — | missing (the what-if sweep reads cost against service, but no shortage cost) |
| I24 | Single-period (newsvendor) buy for a season or event | — | — | — | missing |
| I25 | One place to see each product's policy | — | — | — | missing: the policy is spread over Products at places (one product at a time) and Buffers |

**What this section says:** the arithmetic is there and checked; the *policy* is not presented as one. Fixes, in
order (Enterprise 8.2): a page called **Inventory policy** that holds I25 with I1–I3, I5–I7, I12 and I20 in one
table; assigning a policy to a segment (I4); the suggested reorder point (I12); achieved service (I20); then
periodic review on a calendar (I7) and non-normal safety stock (I18). I23 and I24 go to IDEAS.md.
