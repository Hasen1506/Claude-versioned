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
| I1 | ABC classification by value | `demand/pipeline._abc` (cleansed history, company cut-offs) | Demand → each product's segment; Cycle counts by ABC; **Inventory policy** by annual usage value at each place (`inventory/policy`) | test_demand; test_policy (hand-worked usage values) | there (8.2) |
| I2 | XYZ (variability) and the ABC-XYZ matrix | `demand/pipeline` segment (CV², ADI); `inventory/policy` by the weekly CV the safety stock uses, with where it comes from | Demand; Inventory policy → class | test_demand; test_policy | there (8.2) |
| I3 | Service level per segment | `demand/pipeline.SERVICE_LEVEL`, company table `forecasting.service_levels` | Inventory policy: each target beside its class's suggestion; *By class* | test_policy | there (8.2) |
| I4 | Policy assigned to a whole segment | MRP group shares lot size, strategy, fences | Inventory policy → *Give a policy* (a class or chosen products: method, target or the class's suggestion, rule, review, reorder point) | test_policy; e2e inventory-policy | there (8.2) |
| I5 | Continuous review, reorder point (s, Q) | MRP type `reorder_point` + fixed or EOQ lot | Inventory policy → rule "Reorder point, fixed quantity (s, Q)"; Products at places → MRP 1 | test_mrp, test_s4_backtest_b, test_policy | there (8.2) |
| I6 | Order-up-to (s, S) | `reorder_point` + `MIN_MAX` to max stock | Inventory policy → "Reorder point, order up to (s, S)" | test_mrp, test_policy | there (8.2) |
| I7 | Periodic review (R, s, Q), (R, s, S) | `plan/mrp` review calendar on a reorder point (`review_period_days`, `review_from`); R also widens the safety stock | Inventory policy → "Periodic review, … (R, s, Q)", next review; *Give a policy* → ordered by a reorder point, review every R days | test_policy (hand-worked: weekly orders of 90, 70, 70, 40; order-up-to fills to S on arrival; uneven lead times); e2e inventory-policy | there (8.2) |
| I8 | Time-phased (MRP) with safety stock | MRP type `deterministic` | Supply plan | golden, S/4 backtests | there |
| I9 | Safety stock: fixed, days of cover | `plan/rates.policy_safety_stock` | Products at places → safety stock | test_mrp (fixed, days of cover) | there |
| I10 | Safety stock for a cycle service level, demand and lead-time spread: SS = z·√((L+R)σ_d² + d̄²σ_L²) | `plan/safety.statistical_ss` | Inventory policy; Products at places | hand-worked in test_mrp::test_service_level_safety_stock_formula and test_policy | there |
| I11 | Safety stock for a fill rate (β) via the unit normal loss G(k) | `plan/safety.k_for_fill_rate` | same | test_mrp::test_normal_loss_and_fill_rate_k | there |
| I12 | Reorder point suggested: s = d̄·L + SS | `inventory/policy` (s = d̄·(L + R) + SS) | Inventory policy → reorder point, suggested; a step that sets it | test_policy (hand-worked) | there (8.2) |
| I13 | Lot size: EOQ, fixed, lot-for-lot, periods, min-max, PPB, LUC, Groff | `plan/lotsize` | Products at places → lot size | test_mrp, test_planning_depth (hand-worked) | there |
| I14 | Multi-echelon placement (guaranteed service, Graves–Willems) | `inventory/gsm` | Supply → Buffer placement | test_inventory | there (optional tab) |
| I15 | DDMRP buffers | `inventory/analysis._ddmrp`, MRP type `ddmrp` | Buffer placement; Products at places | test_inventory, test_s4_backtest_b | there |
| I16 | Risk pooling | `inventory/analysis._pooling` | Buffer placement | test_inventory | there |
| I17 | Intermittent demand: Croston / SBA / TSB forecast | `demand/models` | Demand | test_demand | there |
| I18 | Safety stock for intermittent or lumpy demand (non-normal: Poisson, gamma, bootstrap) | — | — | — | missing: a normal approximation sizes slow movers too |
| I19 | Measured lead-time spread fed to safety stock | EP 4.4 | Buying → suppliers | test_demand_spread | there |
| I20 | Achieved service against the target, per product at a place | `inventory/policy` from the closed-order log | Inventory policy → achieved, per product and class | test_policy (five orders: on time, late, short; a transfer not counted) | there (8.2): measured as orders in full by the requested date, the record kept; a cycle service level per replenishment cycle is not logged |
| I21 | Excess, obsolete and slow-moving stock | `tower/kpis` | Performance | test_tower | there |
| I22 | Holding cost rate and ordering cost | settings `wacc` + `holding_spread`; `ordering_cost` on lot sizing and source | Settings; Products at places | test_mrp | there |
| I23 | Cost of a shortage (to choose the service level by cost) | — | — | — | missing (the what-if sweep reads cost against service, but no shortage cost) |
| I24 | Single-period (newsvendor) buy for a season or event | — | — | — | missing |
| I25 | One place to see each product's policy | `inventory/policy` | **Supply → Inventory policy** | e2e inventory-policy (found from the menu) | there (8.2) |

**What this section says** (audit): the arithmetic was there and checked; the *policy* was not presented as one.
**After 8.2:** 22 of 25 there. Open: safety stock for lumpy demand (I18), next; the cost of a shortage (I23) and a
single-period buy (I24) are in IDEAS.md.
