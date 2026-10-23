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
| I18 | Safety stock for intermittent or lumpy demand (non-normal: Poisson, gamma, bootstrap) | `plan/safety` gamma (by mean and σ over L + R) and Poisson, for a cycle level and a fill rate (`safety_stock.distribution`) | Inventory policy: a note where demand over the lead time varies widely (CV over 0.5) with what a gamma spread would hold; *Give a policy* → demand spread | test_policy (hand-worked: the exponential's 4·ln 20 and 4·ln 10, Poisson s = 5 and the shortage sums); e2e inventory-policy (Chennai 5 HP pump, 18.3 → 21.3) | there (8.2): Buffer placement (multi-echelon) still sizes by the normal; no bootstrap from history |
| I19 | Measured lead-time spread fed to safety stock | EP 4.4 | Buying → suppliers | test_demand_spread | there |
| I20 | Achieved service against the target, per product at a place | `inventory/policy` from the closed-order log | Inventory policy → achieved, per product and class | test_policy (five orders: on time, late, short; a transfer not counted) | there (8.2): measured as orders in full by the requested date, the record kept; a cycle service level per replenishment cycle is not logged |
| I21 | Excess, obsolete and slow-moving stock | `tower/kpis` | Performance | test_tower | there |
| I22 | Holding cost rate and ordering cost | settings `wacc` + `holding_spread`; `ordering_cost` on lot sizing and source | Settings; Products at places | test_mrp | there |
| I23 | Cost of a shortage (to choose the service level by cost) | — | — | — | missing (the what-if sweep reads cost against service, but no shortage cost) |
| I24 | Single-period (newsvendor) buy for a season or event | — | — | — | missing |
| I25 | One place to see each product's policy | `inventory/policy` | **Supply → Inventory policy** | e2e inventory-policy (found from the menu) | there (8.2) |

**What this section says** (audit): the arithmetic was there and checked; the *policy* was not presented as one.
**After 8.2:** 23 of 25 there. Open: the cost of a shortage (I23) and a single-period buy (I24), both in IDEAS.md.

## 2. Demand planning

Read against CPIM "demand management" and "forecasting", Hyndman & Athanasopoulos *Forecasting: Principles and
Practice* (FPP), Syntetos & Boylan on intermittent demand, Gilliland on forecast value add, and the S/4 guide's demand
and consumption sections. Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| D1 | Demand history from sales, in any grain (day, week, month) | `SalesHistory` (period_days), journal sales rebuilt on each roll | Set up → Master data → history; upload reads monthly sheets | test_demand (periods), test_regressions | there |
| D2 | History cleansed: events taken out, outliers clipped | `demand/pipeline._cleanse` (event baseline from neighbours, MAD on the residual) | Demand → each series: raw against cleansed | test_demand::test_history_promos_are_cleansed…, ::test_outliers_are_clipped… | there |
| D3 | Demand pattern (smooth, erratic, intermittent, lumpy by ADI and CV²) | `_pattern` (Syntetos–Boylan cut-offs) | Demand → segment | test_demand::test_segmentation | there |
| D4 | ABC and XYZ segmentation | `_abc`, `_xyz` | Demand; Inventory policy | test_demand, test_policy | there |
| D5 | Statistical methods: naïve, seasonal naïve, moving average, SES, Holt damped, Holt–Winters, Croston/SBA/TSB, regression with seasonality | `demand/models` | Demand → methods | test_demand (constant, pure season, a line, Croston by hand) | there |
| D6 | Method chosen by rolling-origin backtest on a scaled error (MASE), simpler wins ties | `demand/competition` | Demand → leaderboard per series | test_demand::test_backtest_origins, ::test_champion… | there |
| D7 | Accuracy and bias measures (WAPE, MASE, bias) | `competition.Score` | Demand: WAPE, bias, WAPE saved over naïve | test_demand::test_metrics_by_hand | there |
| D8 | Prediction intervals; a high-end forecast | `_sigma` from backtest error, P90 released | Demand; order checks (safe date) | test_demand::test_interval_grows…, test_demand_spread | there |
| D9 | Promotions and other events, lift measured from past ones | `DemandEvent` (lift given or measured per kind) | Demand → events | test_demand::test_future_event_uses_given_or_measured_lift… | there |
| D10 | New product from a like product, ramp-up, cannibalisation | `NpiRule` | Demand → new products | test_demand::test_npi_ramp_and_cannibalisation | there |
| D11 | Planner overrides with a reason and an author | `ForecastOverride` (quantity or change) | Demand plan → override | test_demand::test_overrides_absolute_and_relative | there |
| D12 | Forecast value add: naïve, statistical, events, overrides, per family and planner | `demand/value_add` | Demand → Value add | test_value_add; e2e value-add | there |
| D13 | Forecast seen and adjusted at an aggregate (product family, region, all customers of a product) and spread down to the series | `FamilyOverride` (a total or a change, all places or one), spread over the family's series by their own forecast; a series override is a lock the rest goes around; whole units by largest remainder; `ForecastResult.families` | Demand → Consensus grid → *By product family*; Master data → Family overrides | test_demand::test_a_family_total_is_spread…, ::test_a_family_of_whole_units…; e2e demand-family | there (8.3) for families: other aggregates (a region, every customer of a product) are not offered |
| D14 | Consensus in a monthly S&OP cycle with sign-off and a frozen snapshot | `sop` cycle (EP 4.1) | Capacity plan → cycle | test_sop_cycle; e2e sop-cycle | there |
| D15 | Forecast consumed by sales orders (forward and backward windows) | `plan/consumption` | Supply plan (requirements) | test_mrp | there |
| D16 | Planning material: variants consume a base forecast; assembly forecast consumed by dependent demand | EP 4.3 | Products at places | test_planning_strategies | there |
| D17 | Demand history corrected for days out of stock (censored, unconstrained demand) | `SalesHistory.lost_qty` (demand turned away, added back) and `stockout` (read at the neighbouring periods' level when it sold less); a week's roll marks journal history where a sale emptied the shipping place | Demand → series: □ marks, the cleansing log and a note of what was put back; Sales history: *Lost*, *Out of stock*; the upload reads them | test_demand::test_stock_outs_and_lost_sales…, test_actuals::test_history_from_the_journal_is_marked_out_of_stock…; e2e demand-stockout | there (8.3): a short delivery closed on an order is not yet turned into lost demand on its own |
| D18 | Accuracy tracked after release, per series, with a tracking signal (cumulative error ÷ MAD) that flags a biased forecast | `demand/value_add._tracking`: RSFE ÷ MAD of the consensus over the last 13 measured periods, ±4 limit, at least 4 periods | Demand → Value add → *Forecasts that keep missing one way*, each series linked | test_value_add::test_a_forecast_that_keeps_missing_one_way… (hand-worked: 80 ÷ 16 = 5, cancelling misses 0, the window); e2e value-add | there (8.3) |
| D19 | Accuracy by lag (the forecast as it stood 1, 2, 3 … periods before) | `forecasting.fva_lag` (one lag) | Value add | test_value_add | partial: one lag at a time, no waterfall |
| D20 | Working-day and holiday effects (a month with fewer selling days, a festival closure) | calendars plan supply, not demand | — | — | missing |
| D21 | Price as a driver (elasticity) and other causal drivers | `SalesHistory.price` kept for value, not modelled; events stand in for price changes | Demand → events (price change kind) | — | partial |
| D22 | Customer-provided forecasts (collaborative, CPFR) taken in and compared | — | — | — | missing |
| D23 | Demand sensing: the next weeks adjusted from open orders and recent sales | — | — | — | missing (in IDEAS.md as advanced) |
| D24 | Product lifecycle: a discontinued product's demand passed to its successor | `plan/mrp._follow_up` (S/4 discontinuation) | Products at places → follow-up | test_planning_depth (follow-up) | there |
| D25 | A foundation model as a contender, licence checked | `demand/foundation` (TimesFM, off by default) | Settings | test_demand::test_foundation_model… | there |

**What this section says** (audit): the statistical core is broad and checked by hand; what a demand planner does
around it is thinner. The three that change numbers most are D13 (planners and S&OP work in families and months, and
cannot here), D17 (stock-outs teach the forecast that demand fell) and D18 (no per-series alarm when a forecast keeps
missing one way). 17 of 25 there, 3 partial, 5 missing. **Next in 8.3:** D17, D18, D13 in that order (each changes
what the plan buys); D19–D23 to IDEAS.md unless cheap. **After D17:** 18 of 25 there. **After D18:** 19 of 25 there, 2 partial. **After D13:** 20 of 25 there, 2 partial, 3 missing (D20, D22, D23).

## 3. Supply planning (MRP and DRP)

Read against the S/4 guide (§5–§9, as in the backtests), CPIM Part 1 "master scheduling" and "material requirements
planning", and Vollmann et al. *Manufacturing Planning and Control*. Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| M1 | Gross to net, time-phased, on a working calendar | `plan/mrp.plan_node` | Supply plan; Products at places → MRP view | test_mrp, test_scenarios, test_s4_backtest_b | there |
| M2 | BOM explosion by low-level code; phantoms; co- and by-products; yield and scrap | `plan/structure`, `network` (llc) | Set up → make; Supply plan | test_structure, test_planning_depth, test_s4_guide_part_a | there |
| M3 | Lead-time offset (backward scheduling), safety time in working days | `plan/leadtime`, `_create_order` | Supply plan | test_mrp, test_s4_backtest_b | there |
| M4 | Lot sizes and their modifiers (min, max, rounding, full batches) | `plan/lotsize` | Products at places | test_mrp, test_planning_depth | there |
| M5 | Firm planned orders, planning time fence, firming types | `fence_end`, firming 1–4 (EP 2.3) | Stock & actuals → firm zone | test_s4_guide_part_c | there |
| M6 | Demand time fence (master scheduling): inside it only customer orders count, the forecast is ignored | `demand_time_fence_days` on the product at a place (and its MRP group; customer channels follow it): forecast left after consumption inside it is not planned; under make to stock the orders inside it are; DEMAND_TIME_FENCE says how much | Products at places → strategy; Supply plan → messages | test_mrp::test_inside_the_demand_time_fence… (hand-worked: 30.71, 35, 70; working days); e2e demand-fence | there (8.3) |
| M7 | Exception messages: reschedule in / out, cancel, past due, below safety stock | `_reschedule_in`, `_reschedule_out`, exceptions | Home → inbox; Supply plan → situations | test_s4_backtest_b, test_mrp | there |
| M8 | Rescheduling horizon and tolerance | EP 2.1 | Settings; MRP groups | test_s4_guide_part_c | there |
| M9 | Pegging (single and full), sales-order stock, fixed pegging | `_peg`, EP 2.5 | Products at places → where needed; trace | test_mrp, test_planning_strategies | there |
| M10 | Strategies: make to stock, to order, assemble to order, planning with final assembly; consumption windows | `plan/consumption`, strategies | Products at places → strategy | test_planning_strategies, test_mrp | there |
| M11 | MRP types: time-phased, reorder point (continuous and periodic), DDMRP, no planning | `MrpType` | Products at places; Inventory policy | test_mrp, test_policy, test_inventory | there |
| M12 | Sourcing: make or buy by priority, quota arrangement, fixed source, source validity | `_choose` | Set up → sources | test_mrp, test_purchasing | there |
| M13 | Special procurement: direct production, follow-up on discontinuation, subcontracting (job work) | EP 7.1, P4 | Job work & drop-ship | test_planning_depth, test_outside | there |
| M14 | Alternative BOMs and routings; engineering change by validity date | `production_sources` validity | Set up → make | test_planning_depth | there |
| M15 | Distribution (DRP): transfers along lanes, transit time, lane capacity | `transfer` options | Supply plan; Map | test_mrp, test_network | there |
| M16 | Capacity requirements (CRP) per machine per day, and levelling | `plan/level`, capacity-constrained MRP | Supply → Levelling | test_capacity, test_capacity_mrp | there |
| M17 | Rough-cut capacity in the monthly plan (RCCP) | `sop` LP with resource rows | Supply → Capacity plan | test_sop | there |
| M18 | Supplier and lane capacity limits in planning | P5 | Supply plan | test_planning_depth | there |
| M19 | Net change (re-plan what a change reaches) beside regenerative | EP 5.1 | Plan everything | test_incremental | there |
| M20 | Shelf life: lots within it, expiry as a requirement | R15, O1 | Supply plan | test_planning_depth, test_s4_guide_part_c | there |
| M21 | Kanban (pull loops: cards, container quantity, replenish what was used) | — | — | — | missing |
| M22 | MRP areas (a storage location or a subcontractor planned on its own) | — (a place is the planning unit) | — | — | missing: places stand in for them |
| M23 | Range of coverage (safety stock and the maximum in days of demand) | days of supply on safety stock | Products at places | test_mrp | partial: no maximum or target range in days |
| M24 | Lot size by planning calendar (order on given days, covering to the next) | review calendar on a reorder point (8.2) | Inventory policy | test_policy | partial: time-phased MRP has no planning calendar |
| M25 | Planned order converted to a purchase requisition or production order, released to the floor | firming, Buying, production orders | Buying; Shop floor | test_purchasing, test_production | there |

**What this section says** (audit): supply planning is the deepest part of the app (much of it was rebuilt against the
S/4 guide and backtested), and it shows: 20 of 25 there, 2 partial, 3 missing. The gap that changes numbers is M6: the
next days are planned from forecast the customers have not ordered. **Next in 8.3:** M6; M21 and M22 to IDEAS.md;
M23 and M24 noted. **After M6:** 21 of 25 there.
