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
| I20 | Achieved service against the target, per product at a place, measured as the target is set | `inventory/policy` from the closed-order log and the journal: replenishment cycles without a miss for a cycle level, units by the requested date for a fill rate (N359) | Inventory policy → achieved, per product; orders on time per class | test_policy (hand-worked: receipts cut the window into 3 cycles, 1 clean; 36 of 50 units, 40 with a split delivery in the journal) | there (8.5) |
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
| D14 | Consensus in a monthly S&OP cycle with sign-off and a frozen snapshot | `sop` cycle (EP 4.1) | Plan → S&OP cycle (N351) | test_sop_cycle; e2e sop-cycle | there |
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
| M5 | Firm planned orders, planning time fence, firming types | `fence_end`, firming 1–4 (EP 2.3) | Supply → Firm orders (N350) | test_s4_guide_part_c | there |
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

## 4. Buying (procurement)

Read against CPIM "purchasing and supplier management", the S/4 materials management flow (requisition → order →
confirmation → receipt → invoice), and Monczka et al. *Purchasing and Supply Chain Management*. Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| B1 | Requisitions from the plan, grouped into orders per supplier | `purchasing` (E3) | Buying → To order | test_purchasing | there |
| B2 | Source list and info records: price, price scales, MOQ, rounding, lead time, fixed and blocked sources | `PurchasingSource`, vendors | Set up → buy; Buying → suppliers | test_purchasing, test_mrp | there |
| B3 | Contracts and scheduling agreements (call-offs against a quantity or value) | N2 | Buying → contracts | test_procure_to_pay | there |
| B4 | Approval (release strategy) by value, several levels; four eyes | N3, L2 | Buying → orders | test_procure_to_pay | there |
| B5 | Order confirmations, several lines; late and short confirmations into planning | E1–E2, N2 | Buying → orders; Supply plan | test_purchasing, test_mrp | there |
| B6 | Goods receipt with over- and under-delivery tolerance; quality and blocked stock | O1, tolerances | Stock & actuals | test_actuals, test_procure_to_pay | there |
| B7 | Supplier invoice, three-way match with tolerances, delivery costs, cash discount, payables | N1 | Buying → invoices; Money | test_procure_to_pay | there |
| B8 | Returns to supplier | N3 | Buying | test_procure_to_pay | there |
| B9 | Landed cost: price × exchange rate × (1 + duty) + freight + handling | `plan/costing.landed_unit_cost` | Products at places → cost | test_valuation, test_s4_guide_part_c | there |
| B10 | Supplier scorecard: on time, in full, days late, confirmed late | `purchasing` vendor rows | Buying → suppliers | test_purchasing | there |
| B11 | Supplier lead time measured from receipts, offered to planning | EP 4.4 | Buying → suppliers | test_demand_spread | there |
| B12 | Expediting: overdue and late-confirmed orders named, reschedule in | E2, EP 2.1 | Home inbox; Buying | test_purchasing, test_s4_guide_part_c | there |
| B13 | Subcontracting (job work) with parts at the supplier | EP 7.1 | Job work & drop-ship | test_outside | there |
| B14 | Supplier portal (confirm, change, dispatch) and electronic messages | EP 7.2 | Supplier portal | test_portal, test_portal_api | there |
| B15 | Price differences on receipt and invoice into valuation | EP 6.2 | Money | test_valuation | there |
| B16 | Supplier capacity in planning | P5 | Supply plan | test_planning_depth | there |
| B17 | Requests for quotation: ask several suppliers, compare their offers (price, lead time, terms) and award | — | — | — | **missing**: a new source is typed in, not chosen from offers |
| B18 | Spend analysis: spend by supplier, product group and month; ABC of spend; concentration on one supplier | `purchasing/spend`: spent (closed orders of the last year), on order and planned, per supplier and bought product, ABC by share, the biggest supplier's share | Buying → *Spend & sourcing* | test_spend (hand-worked: 1,650 and 120 of 1,770, A and B, price scale, closed-short lines); e2e spend | there (8.3): per supplier and product, not yet by month or product group |
| B19 | Weighted supplier evaluation (delivery, quality, price, service into one score, a rating) | delivery measures only | Buying → suppliers | — | partial: no quality (rejects, returns) or price measure in the score |
| B20 | Consignment stock (the supplier's stock on our premises, paid when used) | — | — | — | missing |
| B21 | Single-source risk: products with one supplier, their spend and lead time | `purchasing/spend`: usable sources per product at a place (not blocked, valid), single-sourced first with spend, lead time and the supplier's on-time | Buying → *Spend & sourcing* → Sourcing | test_spend; e2e spend | there (8.3) |
| B22 | Incoterms and who pays the freight | `incoterm` on orders | Buying → order | — | partial: carried on the document, not in the landed cost |

**What this section says** (audit): the transactional flow is complete (requisition to payment, with contracts,
approvals, portal and tolerances); what a buyer does to choose and manage suppliers is thin: 16 of 22 there, 2
partial, 4 missing. The ones that change decisions are B18 and B21 (where the money goes and where one supplier failing
would stop the plant), then B19 (a score that counts quality and price). **Next in 8.3:** B18 with B21 (one view: spend
and concentration), then B19; B17 and B20 to IDEAS.md. **After B18 and B21:** 18 of 22 there, 2 partial, 2 missing.

## 5. Selling (order to cash and order promising)

Read against CPIM "demand management and customer order management", the S/4 sales flow (quotation → order →
availability check → delivery → billing → payment) and the S/4 planning guide §6–7 (order capture, advanced ATP).
Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| S1 | Sales order header with several lines, the customer's number, order confirmation | M1, M2 | Selling → orders; Customer orders | test_order_to_cash | there |
| S2 | Pricing: customer price, quantity scales, customer and product discounts, an order's own price | `CustomerPrice`, `sales.price` | Set up → customer prices; Selling | test_order_to_cash | there |
| S3 | Quotations with validity, won (at the quoted prices) or lost (with a reason) | M2 | Selling → quotations | test_order_to_cash | there |
| S4 | Credit limit and credit check, blocked for delivery until released; sales block | M1 | Selling → customers | test_order_to_cash | there |
| S5 | Availability check: stock, firm and planned receipts, the look-ahead that protects earlier promises, inspection stock left out | `promise` | Customer orders → Check availability | test_promise, test_s4_guide_part_c | there |
| S6 | Delivery scheduling backward from the requested date: transit, loading, picking and packing, material availability | EP 2.2 | Customer orders → *Why this date* | test_s4_backtest_b | there |
| S7 | Capable-to-promise through transfer, production (capacity by day) and purchase | P6, N24 | Customer orders | test_promise | there |
| S8 | Product allocation by product and family, per customer, with carry-forward and fallback | EP 2.7 | Customer orders → allocations | test_promise, test_s4_backtest_b | there |
| S9 | Backorder processing: segments and confirmation strategies (win, gain, redistribute, fill, lose) | P6 | Customer orders → backorder processing | test_promise | there |
| S10 | Alternative shipping places when the first is short | `alternative_locations` | Customer orders | test_promise | there |
| S11 | Product substitution: another product offered for what is short, the offer taken onto the order | `Substitution`; `Promiser.substitutes`; `orders.substitute` | Customer orders → an order → *Substitute*; Set up → Substitutions | test_substitution (hand-worked: 10 of A2 and 20 of A3 for 30 short, held against the next order, given back when not offered, within allocations, not beyond lead time); e2e promise-substitute | there (8.3): offered and taken by one click, not taken automatically in backorder processing |
| S12 | Complete delivery of a line; one delivery for a whole order (kits) | EP 2.7 | Customer orders | test_promise, test_s4_backtest_b | there |
| S13 | Orders consume the forecast by planning strategy (make-to-stock, 40, make-to-order, assemble-to-order) | `plan/consumption` | Supply plan; Demand | test_planning_strategies | there |
| S14 | Order changes and cancellations, promised again, with a reason; nothing cancelled counts against OTIF | G1 | Customer orders → an order | test_orders | there |
| S15 | Deliveries: picked, packed, shipped, signed for; delivery availability check; price frozen at goods issue | M3, EP 2.6 | Selling → deliveries | test_order_to_cash | there |
| S16 | Invoices and credit notes with tax (GST as CGST and SGST or IGST) | M3, N123 | Selling → invoices | test_order_to_cash | there |
| S17 | Payments with cash discount; payment reminders by level (dunning) | M3, N124 | Selling → invoices, customers | test_order_to_cash | there |
| S18 | Customer returns into quality inspection, with a credit note | M3 | Selling → returns | test_order_to_cash | there |
| S19 | Receivables: what each customer owes, overdue, ageing, DSO | `tower/capital` | Selling → customers; Performance → working capital | test_kpi_working_capital | there |
| S20 | Customer service measures: OTIF against requested and confirmed dates, confirmation rate, perfect order | `tower/kpis` | Performance | test_tower | partial: perfect order has no documentation or damage measure (the KPI says so) |
| S21 | Cost to serve and margin per customer and product | `finance` serve rows | Money → cost to serve | test_finance | there |
| S22 | Customer segmentation: customers classed by revenue, with service targets and promising priority by class | priorities and BOP segments by hand | Customer orders → settings | — | partial: no customer ABC, segments chosen by hand |
| S23 | Quotation conversion and the order book: win rate, lost reasons, open orders by age and value | quotation status and lost reason | Selling → quotations, orders | — | partial: kept on each quotation, not counted |
| S24 | Rebates and volume agreements accrued against revenue | — | — | — | missing |
| S25 | Freight and surcharges on customer orders; minimum order value | — | — | — | missing |
| S26 | Stock at the customer: consignment and vendor-managed inventory | — | — | — | missing |

**What this section says** (audit): the order-to-cash flow and order promising are deep (S/4 aATP's availability
check, allocation, backorder processing and capable-to-promise are all there and tested against the guide); what a
seller does with customers as a whole is thinner. At the audit: 20 of 26 there, 3 partial, 3 missing (S11 among the
missing). The one that changes what customers get is S11: when the ordered product is short, a product the company
accepts in its place may be free on the date asked. **After S11:** 21 of 26 there, 3 partial (S20, S22, S23), 3 missing
(S24 to S26), all in IDEAS.md.

## 6. Warehouse

Read against CPIM "warehouse management", the S/4 guide §12 (EWM basics: storage types, bins, put-away and picking
strategies, warehouse tasks, waves, replenishment) and Bartholdi & Hackman, *Warehouse & Distribution Science*.
Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| W1 | Storage types and bins with limits by quantity and weight; blocked bins | EP 6.1 | Warehouse → stock by bin; Set up → storage bins | test_warehouse | there |
| W2 | Put-away strategies (fixed bin, add to stock, next empty), storage type search order, bins per product | EP 6.1 | Warehouse → put away | test_warehouse | there |
| W3 | Picking: picking areas before the reserve, first expiring first, first in, nearest on the walk | EP 6.1 | Warehouse → waves & picking | test_warehouse | there |
| W4 | Waves and one pick list in walk order across deliveries | EP 6.1 | Warehouse → waves & picking | test_warehouse | there |
| W5 | Warehouse tasks confirmed by scanning bin and product; short picks asked to be counted | EP 6.1 | Phone scan page; Warehouse → open tasks | test_warehouse; e2e warehouse | there |
| W6 | Stock by bin from the goods-movement journal, adding up to the place's stock | EP 6.1 | Warehouse → stock by bin | test_warehouse | there |
| W7 | Replenishment of picking bins: refilled from the reserve between a minimum and a maximum | `warehouse.propose_refill`, `create_refill`; `Bin.min_qty` | Warehouse → *Refill picking bins* | test_warehouse (hand-worked: 16 to S1, 10 of the batch expiring first then 6, open picks and refills counted, two bins never sharing stock, weight limit, a short reserve named); e2e warehouse | there (8.3); at the audit a move typed by hand |
| W8 | Slotting: fast movers placed near the start of the walk, by picks | — | — | — | missing |
| W9 | Batches with expiry; first expiring first; nothing expired picked | O1 | Stock & actuals; Warehouse | test_warehouse, test_stock | there |
| W10 | Stock types: quality inspection, blocked, in transit | O1 | Stock & actuals | test_actuals | there |
| W11 | Serial numbers | O3 | Stock & actuals | test_actuals | there |
| W12 | Physical inventory with a freeze, counts and differences posted | O3 | Stock & actuals → counts | test_actuals | there |
| W13 | Cycle counting by ABC class | EP 6.2 | Stock & actuals → cycle counts | test_valuation | there |
| W14 | Goods receipt with tolerances; advance shipping notice from the supplier | B6, EP 7.2 | Stock & actuals; Supplier portal | test_procure_to_pay, test_portal | there |
| W15 | Packing: packages and gross weight on the delivery | M3 | Selling → deliveries | test_order_to_cash | there |
| W16 | Handling units: pallets and cartons, nested and labelled | — | — | — | missing |
| W17 | Cross-docking: goods in sent straight to deliveries waiting for them | — | — | — | missing |
| W18 | Cold chain: refrigerated storage and transport | R30 | Products; lanes | test_stock | there |
| W19 | Space: bin fill and the place's storage volume against its capacity | bin fill; `storage_capacity_m3` in S&OP | Warehouse → stock by bin; S&OP | test_sop | partial: the plan's MRP does not check a place's volume |
| W20 | Warehouse measures: pick accuracy, dock-to-stock time, order to goods issue, lines a day | — | — | — | missing |
| W21 | Workload of a wave in hours by time standards | — | — | — | missing |

**What this section says** (audit): the inside of a warehouse is there as S/4's basic EWM has it (bins, strategies,
waves, scanning, batches, counts); what is thinner is how a warehouse is run and measured: slotting, handling units,
cross-docking, its measures and its workload. At the audit: 14 of 21 there, 2 partial, 5 missing. The one that
changes what the floor does every day is W7: a picking shelf emptied by the morning's picks waits until someone sees
it. **After W7:** 15 of 21 there, 1 partial (W19), 5 missing (W8, W16, W17, W20, W21), all in IDEAS.md.

## 7. Transport

Read against CPIM "distribution and transportation", the S/4 guide §14 (TM basics: freight units, load building,
carrier selection, tendering, freight settlement) and Ballou, *Business Logistics/Supply Chain Management*. Audited
23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| T1 | Lanes with modes, transit times, transit spread and costs a shipment, kilogram, cubic metre and unit | master data | Set up → lanes; Network | test_planning_depth | there |
| T2 | The mode planning uses on a lane, among several | `planning_mode` | Set up → lanes | test_transport | there |
| T3 | Carriers and their rate tables, never under a minimum, blocked carriers | EP 6.3 | Transport → carriers | test_transport | there |
| T4 | Load building by weight and volume, loads within a window sharing a vehicle | EP 6.3 | Transport → to load | test_transport | there |
| T5 | Carrier selection: the cheapest whose vehicle takes the load; the others' costs shown | EP 6.3 | Transport → to load | test_transport | there |
| T6 | Tendering, a rejection tendered to the next carrier, acceptance | EP 6.3 | Transport → freight orders | test_transport | there |
| T7 | Shipping posts the goods issue of each delivery and the dispatch of each transfer | EP 6.3 | Transport → freight orders | test_transport | there |
| T8 | Freight settlement: the bill against plan, shared by weight, owed to the carrier, in the books | EP 6.3, EP 7.4 | Transport → freight orders, carriers; Books | test_transport, test_accounting | there |
| T9 | Lane capacity in planning | P5 | Supply plan | test_planning_depth | there |
| T10 | Outbound scheduling: picking, packing, loading and transit in the promised date | EP 2.2 | Customer orders → *Why this date* | test_s4_backtest_b | there |
| T11 | Inbound transport: purchases the buyer collects (EXW, FCA, FAS, FOB) planned as freight from the supplier | `transport.collected`; `FreightOrder.purchases` | Transport → to load (*collect from the supplier*) | test_transport (hand-worked: 400 and 300 kg due on days 4 and 5 load on days 2 and 3, one truck within a day's window for 1,200; DAP and CIF not collected; confirmations, horizon, lateness; the bill in the receiving company's books); e2e transport-collect | there (8.3); at the audit nothing planned the freight Kaveri pays from Shenzhen |
| T12 | Incoterms decide who pays the freight | vendor terms read by transport | Transport | test_transport | partial: they decide what is collected, not yet the landed cost (B22) |
| T13 | Multi-stop routes: several drops on one vehicle | — | — | — | missing |
| T14 | Carrier performance: tenders accepted, picked up and delivered on time | rejections counted | Transport → carriers | test_transport | partial: no on-time measure |
| T15 | Freight cost per unit by lane and the billed freight in cost to serve | the lane's planned cost in cost to serve | Money → cost to serve | test_finance | partial: what carriers bill is not shared to customers |
| T16 | Dock appointments and yard | — | — | — | missing |
| T17 | Proof of delivery and shipment tracking | proof of delivery (M3) | Selling → deliveries | test_order_to_cash | partial: no tracking events |
| T18 | Vehicles filled too little named | `low_fill` | Transport → to load | test_transport | there |
| T19 | Stock in transit seen in stock and planning | O1 | Stock & actuals | test_stock | there |

**What this section says** (audit): outbound transport is as S/4's basic TM has it; inbound transport was missing,
and the measures of carriers and the freight in cost to serve are thin. At the audit: 12 of 19 there, 4 partial, 3
missing. The one that changes what is paid and planned is T11: on Kaveri, the Shenzhen parts are bought FOB, so the
sea freight from Shenzhen is Kaveri's to book, and nothing planned it. **After T11:** 13 of 19 there, 4 partial (T12,
T14, T15, T17), 2 missing (T13, T16), all in IDEAS.md.

## 8. Money

Read against CPIM "financial measures of supply chain performance", Horngren et al., *Cost Accounting*, and the S/4
controlling and finance basics the planning guide relies on (costing, valuation, the journal). Audited 23 October
2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| F1 | Cost rolled up through the bill of materials: parts, conversion and setup, with yield | `plan/costing.roll_up` | Products at places → cost | test_valuation | there |
| F2 | Landed cost: price, exchange rate, duty, freight and handling | `landed_unit_cost` | Products at places → cost | test_valuation | there |
| F3 | Valuation at standard or moving average, price differences | EP 6.2 | Money → stock in the books | test_valuation | there |
| F4 | The plan's cost by category, served and unabsorbed adding up | `finance.ledger` | Money → summary | test_finance | there |
| F5 | Stock value over time and its holding cost at the cost of capital | `inventory_value` | Money → inventory value | test_finance | there |
| F6 | Cost to serve and margin per customer and product | `cost_to_serve` | Money → cost to serve & margin | test_finance | there |
| F7 | Working capital: turns, DIO, DSO, DPO, cash to cash, ageing | `tower/capital` | Performance → working capital | test_kpi_working_capital | there |
| F8 | Excess, obsolete and slow-moving stock in value | `tower/kpis` | Performance | test_tower | there |
| F9 | Budget against the plan, in volume and revenue | EP 4.1 | S&OP cycle | test_sop_cycle | there |
| F10 | Capacity investment appraisal: shadow prices, a re-solve, NPV | `finance/capacity` | Money → capacity investments | test_finance | there |
| F11 | Receivables and payables with cash discounts and payment reminders | M3, N1 | Selling; Buying → invoices | test_order_to_cash, test_procure_to_pay | there |
| F12 | Double-entry journal per company, checked against its documents, exported to Tally | EP 7.4 | Money → books | test_accounting | there |
| F13 | Production order costs and their variances | P-phase costing | Stock & actuals | test_production_order_costs | there |
| F14 | Overhead absorbed by rates (on machine and labour hours, on material) | an extra cost a unit on the routing | Set up → production | — | partial: no overhead rates |
| F15 | Cash projection: what comes in and goes out week by week on everyone's payment terms, and the most cash needed | `finance/cash.cash_view` | Money → *Cash by week* | test_cash (hand-worked: 400 overdue, 100 + 600 paid in week 2 for −300 at the lowest, 900 in week 3, 2,000 after the last week; shipped lines to bill not to sell; credit notes, settled freight, supplier invoices, production and transfers when they start); e2e money-cash | there (8.3) |
| F16 | Money at risk per exception | `tower/money` | Home inbox | test_tower | there |
| F17 | Stock written down to what it can be sold for (expiring, obsolete) | expiry valued as written off in money at risk | Home inbox | test_tower | partial: no write-down posted |
| F18 | Foreign currency: purchases at a rate; open items revalued | `settings.fx_rates` | Company | test_valuation | partial: one rate, no revaluation |
| F19 | Profit and loss and balances by period from the journal | EP 7.4 | Money → books | test_accounting | there |
| F20 | Transfer prices between the companies of a group | EP 7.3 | Group | test_intercompany | there |

**What this section says** (audit): cost, value and the books are deep; what was missing is when the money moves.
At the audit: 16 of 20 there, 3 partial, 1 missing (F15). The plan says what it costs and earns, not what cash it
needs and when: on Kaveri, four weeks of production and transfers are paid before the first customer pays.
**After F15:** 17 of 20 there, 3 partial (F14, F17, F18), all in IDEAS.md.

## 9. Capacity and scheduling

Added in 8.5: the audit left capacity inside supply planning (M16, M17) and gave scheduling no rows. Read against
CPIM "capacity management" and "production activity control", the S/4 guide's PP-DS (§8), and Pinedo, *Scheduling:
Theory, Algorithms, and Systems*. Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| C1 | Work centres with shift calendars, breaks, efficiency and units in parallel | `ResourceClock`, `Resource` (B1) | Set up → Machines & shifts | test_capacity (hours by hand) | there |
| C2 | Operations with setup, run, queue and move times; batch cycles | `schedule/core.OpSpec`, routings (B2, H2) | Set up → make | test_schedule, test_structure | there |
| C3 | Capacity requirements per machine per day against what it has (CRP) | `plan/mrp` daily buckets | Supply → Levelling | test_capacity | there |
| C4 | Rough-cut capacity per month (RCCP) | `sop/plan` resource rows | Supply → Capacity plan | test_sop (LP by hand) | there |
| C5 | Levelling: moving load to earlier days within limits | `plan/level` | Supply → Levelling | test_capacity, e2e golden | there |
| C6 | Capacity-constrained material plan (orders planned where there is room) | C3 | Supply plan | test_capacity_mrp | there |
| C7 | Overtime and an added shift as decisions, with their cost | `sop` overtime, `capacity_add_hours_per_week` (P5) | Capacity plan; Machines & shifts | test_sop, test_planning_depth | there |
| C8 | The binding limit and what one more hour is worth (shadow price) | `sop/lp` duals and ranging | Capacity plan → limits | test_sop (dual by hand) | there |
| C9 | Finite scheduling forward from release and backward from due date | `schedule/heuristics` (EDD, backward) | Supply → Shop floor | test_schedule | there |
| C10 | Dispatching rules: EDD, SPT, least slack, critical ratio | `heuristics` (EDD, SPT, slack, CR, campaign) | Shop floor → rule | test_schedule_ppds (CR 2 against 10 takes the long order first, where least slack takes the short one) | there (8.5, N362) |
| C11 | Sequence-dependent setups: changeover matrix, setup groups, campaigns | `setup_rule`, campaign heuristic | Shop floor → changeovers | test_schedule | there |
| C12 | Optimised sequence with a weighted objective (lateness, changeovers, earliness) | `schedule/optimize` (CP-SAT) | Shop floor → *Best possible* | test_schedule (checker on every result) | there |
| C13 | Alternative machines; a tool or mould as a second resource; crews | `pin`, tools, `LabourDay` | Shop floor | test_schedule | there |
| C14 | Frozen zone: the next hours keep their sequence | frozen zone (D1) | Shop floor | test_schedule | there |
| C15 | Scheduling waits for parts; the schedule's dates go back into the plan and promises | C1, C2 of Phase C | Shop floor → apply | test_schedule, e2e golden | there |
| C16 | Board: drag an order, see the change, keep or reset | web board (D5) | Shop floor | e2e golden (resequence → reset) | there |
| C17 | Order release and confirmation with parts used (backflush or counted), scrap | `actuals/post.receive`, `scrap` | Stock & actuals → Goods in & out | test_actuals, e2e persona-day | there: order level, not per operation |
| C18 | Measured yield against the bill of materials | `actuals/yields` | Stock & actuals | test_actuals | there |
| C19 | Schedule adherence | `tower/kpis.schedule_adherence` | Performance → KPIs | test_tower | there |
| C20 | OEE (availability × performance × quality) measured from what ran | a planning input only (`efficiency`) | Machines & shifts | — | partial: planned with, never measured |
| C21 | Bottleneck scheduling (drum-buffer-rope: the constraint sets the pace, a time buffer before it) | — (the shadow price names the constraint) | — | — | missing |
| C22 | Rate-based (repetitive) production: a line's rate per shift, takt | — | — | — | missing |

**What this section says:** the scheduler is deep and every result is checked by an independent feasibility
checker; 18 of 22 there, 2 partial, 2 missing at the audit. What a scheduler would miss is critical ratio (C10,
cheap), OEE from records (C20) and rate-based lines (C22) for the kitchenware assembly kind of plant. **After C10:**
19 of 22 there; C20, C21 and C22 to IDEAS.md.

## 10. The S&OP process

Added in 8.5: the audit gave the monthly process one row (D14). Read against the IBP S&OP process, Wallace & Stahl,
*Sales & Operations Planning: The How-To Handbook*, and CPIM "sales and operations planning". Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| P1 | A monthly cycle of five steps (data, demand review, supply review, pre-S&OP, executive), each with an owner and a sign-off in order | `sop/cycle` (EP 4.1) | Plan → S&OP cycle | test_sop_cycle; e2e sop-cycle, persona-day | there |
| P2 | Each signed step frozen as it was signed | version store | S&OP cycle → each step's version | test_sop_cycle | there |
| P3 | Volume and revenue month by month against the budget | `cycle.figures` | S&OP cycle → figures | test_sop_cycle (hand-worked budget shares) | there |
| P4 | By product family | `FamilyFigures` | S&OP cycle | test_sop_cycle | there |
| P5 | Unconstrained demand beside the constrained supply plan, with the gap and the limits that cause it | `figures` supply steps, `limits`, `fill_rate` | S&OP cycle → supply review | test_sop_cycle | there |
| P6 | Scenarios compared in the supply review (demand up, a shift added) | `sop` levers; stored versions as columns (EP 5.3) | Capacity plan; Versions | test_sop, test_whatif | there: compared on Capacity plan, not inside the cycle page |
| P7 | Decisions recorded with the sign-off (minutes) | `MINUTES` for pre and exec | S&OP cycle | test_sop_cycle | there |
| P8 | A horizon of 18 to 24 months, monthly | `sop` buckets over `settings.horizon_days` (182 on the examples) | Capacity plan | — | partial: the S&OP plan sees only the operational horizon |
| P9 | Financial view: margin, inventory value and cash by month beside the volume plan | revenue only in the cycle; margin, stock and cash on Money | Money | test_finance | partial: the executive step shows revenue, not margin or stock |
| P10 | The month's plan released to the operational plan (build-ahead targets) | `sop/release` | Capacity plan → release | test_sop | there |
| P11 | Product review: new and dying products as a step | NPI rules, discontinuation exist in demand and MRP | Demand | — | missing as a step |
| P12 | How well S&OP works: plan stability, forecast accuracy by family, the plan against what happened | `plan_stability`, forecast KPIs | Performance | test_tower | partial: not per cycle |

**What this section says:** the process and its sign-offs are there; what an S&OP lead would object to first is P8.
A plant that decides on a new press or a second supplier needs to see a year and more ahead, and the S&OP plan stops
where the weekly plan stops. 7 of 12 there, 4 partial, 1 missing.

## 11. Performance measures

Added in 8.5. Read against SCOR level 1 (reliability, responsiveness, agility, cost, asset management) and the S/4
guide's KPI list (§18.2). Audited 23 October 2026.

| # | Concept | Engine | Page and name | Oracle | Status |
|---|---|---|---|---|---|
| K1 | Perfect order fulfilment (RL.1.1) | `perfect_order` | Performance → KPIs | test_tower | there |
| K2 | OTIF to the requested and the confirmed date | `otif_requested`, `otif_confirmed` | KPIs | test_tower | there |
| K3 | Confirmed on the requested date | `confirmation_rate` | KPIs | test_tower | there |
| K4 | Forecast accuracy (1 − WMAPE) and bias | `forecast_accuracy`, `forecast_bias` | KPIs; Demand → Value add | test_tower, test_value_add | there |
| K5 | Supplier delivery reliability | `supplier_reliability` | KPIs; Buying → suppliers | test_tower | there |
| K6 | Schedule adherence | `schedule_adherence` | KPIs | test_tower | there |
| K7 | Inventory turns, days of supply, DIO | `inventory_turns`, `days_of_supply`, `dio` | KPIs | test_tower (hand-worked) | there |
| K8 | Cash-to-cash cycle (AM.1.1) with DSO and DPO | `cash_to_cash`, `dso`, `dpo` | KPIs; Money | test_tower | there |
| K9 | Excess and obsolete stock | `excess_obsolete` | KPIs | test_tower | there |
| K10 | Cost to serve | `cost_to_serve` | KPIs; Money | test_finance | there |
| K11 | Plan stability and exception ageing | `plan_stability`, `exception_ageing` | KPIs | test_tower | there |
| K12 | Inventory record accuracy | `actuals/cycle` (exact ÷ counted, by class) | Stock & actuals → cycle counts | test_valuation | there: not on the KPI page |
| K13 | Order fulfilment cycle time (RS.1.1): order received to delivered | `order_cycle_time` (header's order date to last delivery) | KPIs → Customer service | test_tower (5 and 13 days: 9) | there (8.5, N361) |
| K14 | Unit fill rate | `fill_rate` (units by the requested date ÷ ordered; the journal splits a partly late order) | KPIs → Customer service | test_tower (240 of 350; 300 of 350 with a split delivery) | there (8.5, N361) |
| K15 | Upside flexibility and adaptability (AG.1.1–1.3) | the what-if sweep answers it on request | What-if | test_whatif | partial |
| K16 | Total supply chain management cost (CO.1.001) | Money: purchase, conversion, transport, holding | Money | test_finance | partial: not one figure |

**What this section says:** reliability, asset and cost measures are there with their definitions on the page;
responsiveness (K13) and the unit fill rate (K14) were not. 12 of 16 there at the audit, 2 partial, 2 missing.
**After K13 and K14:** 14 of 16 there, 2 partial (K15, K16).
