"""
Procurement & Production MILP Solver
=====================================
Minimizes total supply chain cost:
  setup + FG holding + production + expiry + shortage + RM purchase + RM holding + RM ordering

Decision variables:
  p[k,t]  = units of product k produced in period t
  r[i,t]  = units of raw material i ordered in period t
  y[k,t]  = binary: whether product k is produced in period t
  o[i,t]  = binary: whether raw material i is ordered in period t
"""
import pulp
import math
import time
import numpy as np

try:
    from .lot_sizing import run_policy, auto_select_policy
except ImportError:
    from lot_sizing import run_policy, auto_select_policy


def solve_procurement(data):
    """Main entry point. data = dict from API request."""
    t0 = time.time()
    products = data.get('products', [])
    params = data.get('params', {})
    cap_mode = data.get('capacity_mode', 'parallel')  # shared or parallel

    T = params.get('periods', 52)  # period count at configured grain
    # T8-03 — Production lines block (id, capacity, hrs_per_period, planned_maintenance, eligible_skus).
    # Used to derive per-product per-period maintenance scaling so procurement MILP doesn't schedule
    # production through line-down weeks.
    lines_block = data.get('lines', []) or []
    # T8-04 — fill-rate target (decimal, e.g. 0.95). Mode: 'soft' adds penalty term,
    # 'hard' adds constraint Σshort ≤ (1-target)·Σdemand, 'off' skips.
    fill_rate_target = float(params.get('fill_rate_target', 0.95) or 0.95)
    fill_rate_mode = (params.get('fill_rate_mode') or 'soft').lower()
    # Pillar 2 — period grain scales per-period carry cost (annual rate → per-period).
    time_grain = params.get('time_grain', 'weekly')
    periods_per_year = {'daily': 365, 'weekly': 52, 'monthly': 12}.get(time_grain, 52)
    carry_rate_annual = params.get('carry_rate', 0.24)
    # The solver accumulates holding cost once per period, so per-period rate = annual / periods-per-year.
    carry_rate = carry_rate_annual / periods_per_year * 52  # keep legacy "per-week equivalent" when weekly grain
    # Holiday list (ISO dates) — periods that overlap with a holiday are excluded from capacity & shift production.
    holidays = params.get('holidays', []) or []
    horizon_start_date = params.get('horizon_start_date', None)
    wh_max = params.get('wh_max', 5000)
    # Pillar 10 — hard working-capital constraint: Σ (inv × per-unit-value) ≤ working_capital per period.
    working_capital = params.get('working_capital', 0) or 0
    fixed_daily = params.get('fixed_daily', 0)
    bo_on = params.get('backorder_on', False)
    salvage = params.get('salvage_rate', 0.80)
    service_level = params.get('service_level', 0.95)
    budget = params.get('budget', None)  # optional budget constraint
    # #7 — extended constraint set. Each is 0 / falsy when the UI toggle is off.
    labor_hours_max = float(params.get('labor_hours_max', 0) or 0)
    co2_max_per_period = float(params.get('co2_max_per_period', 0) or 0)
    supplier_concentration_max_pct = float(params.get('supplier_concentration_max_pct', 0) or 0)
    fx_exposure_max_pct = float(params.get('fx_exposure_max_pct', 0) or 0)
    abc_service_a_min_pct = float(params.get('abc_service_a_min_pct', 0) or 0)
    budget_deflate = bool(params.get('budget_deflate', False))
    inflation_pct_annual = float(params.get('inflation_pct_annual', 0) or 0)
    # Per-period inflation factor for budget deflation. (1+annual_infl) ^ (t / periods_per_year).
    # T6-08 — Logistics (transport) budget gate. Three modes:
    #   'hard'          → Σ part.trans_rate × r[gidx,t] ≤ logistics_budget (constraint).
    #   'soft'          → adds 10× penalty per ₹ over budget into objective via auxiliary slack var.
    #   'unconstrained' → no-op (UI shows warning).
    # Combined cost feeds Tab 09 KPI variance.
    logistics_budget = params.get('logistics_budget', None)
    logistics_mode = (params.get('logistics_mode') or 'soft').lower()
    # T6 — locked POs from PoReleasePlanCard (Tab 5). Modelled as SCHEDULED RECEIPTS at the
    # arrival period (release + lead_time), NOT as forced order-release decisions. This matches
    # MRP semantics: the buying decision is already made; the qty hits RM inventory at arrival
    # and the solver re-optimises only the residual gap. See `scheduled_receipts` build below.
    locked_pos = params.get('locked_pos', []) or []
    # P7 audit — RM warehouse 4-mode capacity (parallel to FG).
    # rm_wh_mode ∈ {units, area, volume, unlimited}. Per-part rm_footprint_area / rm_footprint_volume
    # carry the m²/u or m³/u factor. When mode in {area, volume}, an aggregate constraint
    # Σ rm_inv[gidx, t] × footprint ≤ rm_wh_limit is added per period. units mode keeps per-part rm_cap.
    rm_wh_mode = (params.get('rm_wh_mode', 'units') or 'units').lower()
    rm_wh_limit_area = float(params.get('rm_wh_limit_area', 0) or 0)
    rm_wh_limit_volume = float(params.get('rm_wh_limit_volume', 0) or 0)
    # P4 — replan from period: lock production = committed actuals for periods 0..replan_from_period-1; re-solve forward.
    # Each product may carry an `actuals_override` array (None where uncommitted).
    replan_from_period = params.get('replan_from_period', None)
    if replan_from_period is not None:
        try:
            replan_from_period = int(replan_from_period)
        except Exception:
            replan_from_period = None

    n_products = len(products)
    if not n_products:
        return {'error': 'No products provided'}

    # Pillar 5 — continuous z from inverse-normal CDF. Replaces the old 4-value z_map bucket.
    try:
        from statistics import NormalDist
        z = NormalDist().inv_cdf(max(0.5, min(0.9999, float(service_level))))
    except Exception:
        z_map = {0.85: 1.036, 0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
        z = z_map.get(round(service_level, 2), 1.645)

    # T3-08 — ABC/XYZ-driven SS policy. When a product carries abc_class + xyz_class,
    # the per-product service level (and therefore z) overrides the global default.
    # Matrix below mirrors the recommendedSSPolicy() matrix in index.html so the
    # planner UI and the solver agree on policy.
    abc_xyz_sl = {
        ('A','X'):0.99,('A','Y'):0.98,('A','Z'):0.97,
        ('B','X'):0.97,('B','Y'):0.95,('B','Z'):0.92,
        ('C','X'):0.92,('C','Y'):0.90,('C','Z'):0.85,
    }
    def per_product_z(prod):
        a = (prod.get('abc_class') or '').upper()
        x = (prod.get('xyz_class') or '').upper()
        sl = abc_xyz_sl.get((a, x))
        if sl is None:
            return z
        try:
            from statistics import NormalDist
            return NormalDist().inv_cdf(max(0.5, min(0.9999, float(sl))))
        except Exception:
            return {0.85:1.036,0.90:1.282,0.92:1.405,0.95:1.645,0.97:1.881,0.98:2.054,0.99:2.326}.get(round(sl,2), z)

    # Pillar 6 — per-period capacity factor: fraction of the period that is NOT a holiday.
    # Daily:   1.0 if the date is not a holiday, else 0.0.
    # Weekly:  (working_days_in_week - holidays_in_week) / working_days_in_week.
    # Monthly: (working_days_in_month - holidays_in_month) / working_days_in_month.
    from datetime import date, timedelta
    hol_set = set(holidays) if isinstance(holidays, list) else set()
    try:
        start = date.fromisoformat(horizon_start_date) if horizon_start_date else date.today()
    except Exception:
        start = date.today()
    def period_factor(t):
        if not hol_set:
            return 1.0
        if time_grain == 'daily':
            d = start + timedelta(days=t)
            return 0.0 if d.isoformat() in hol_set else 1.0
        if time_grain == 'monthly':
            ref = start + timedelta(days=t * 30)
            wdays = sum(1 for i in range(30) if (ref + timedelta(days=i)).weekday() < 6)
            hols = sum(1 for i in range(30) if (ref + timedelta(days=i)).isoformat() in hol_set)
            return max(0.0, (wdays - hols) / max(wdays, 1))
        # weekly (default)
        ref = start + timedelta(days=t * 7)
        wdays = sum(1 for i in range(7) if (ref + timedelta(days=i)).weekday() < 6)
        hols = sum(1 for i in range(7) if (ref + timedelta(days=i)).isoformat() in hol_set)
        return max(0.0, (wdays - hols) / max(wdays, 1))
    cap_factor = [period_factor(t) for t in range(T)]

    # T8-03 — Per-product per-period maintenance factor.
    # For each product k, find the eligible lines, build each line's per-period scale (1.0 normal,
    # 0.0 fully down weekly, fractional hourly), then take the AVG across eligible lines.
    # Avg (not min) because shared/parallel lines distribute load — losing one of three lines
    # cuts effective capacity to ~67%, not to 0.
    def _line_period_scales(line):
        scales = [1.0] * T
        hpp = float(line.get('hrs_per_period', 0) or 0)
        for w in line.get('planned_maintenance', []) or []:
            mode = (w.get('mode') or 'weekly').lower()
            if mode == 'weekly':
                fw = max(int(w.get('from_week', 0) or 0) - 1, 0)
                tw = max(int(w.get('to_week', 0) or 0) - 1, fw)
                for t in range(fw, min(tw + 1, T)):
                    scales[t] = 0.0
            elif mode == 'hourly':
                # Resolve which period the date falls in; fallback period 0.
                t_target = 0
                if horizon_start_date and w.get('date'):
                    try:
                        from datetime import date as _date
                        d = _date.fromisoformat(w['date'])
                        s_dt = _date.fromisoformat(horizon_start_date)
                        days_per_p = {'daily': 1, 'monthly': 30}.get(time_grain, 7)
                        t_target = max(0, min((d - s_dt).days // days_per_p, T - 1))
                    except Exception:
                        t_target = 0
                hrs_lost = float(w.get('hours_lost', 0) or 0)
                if hpp > 0 and hrs_lost > 0:
                    scales[t_target] = max(0.0, min(scales[t_target], 1.0 - hrs_lost / hpp))
        return scales
    # k -> [factor per t]
    maint_factor_k = {}
    if lines_block:
        line_scales = [_line_period_scales(l) for l in lines_block]
        for k in range(n_products):
            eligible_idx = [li for li, l in enumerate(lines_block) if not l.get('eligible_skus') or k in (l.get('eligible_skus') or [])]
            if not eligible_idx:
                eligible_idx = list(range(len(lines_block)))  # no constraint → all eligible
            mf = []
            for t in range(T):
                avg = sum(line_scales[li][t] for li in eligible_idx) / max(len(eligible_idx), 1)
                mf.append(avg)
            maint_factor_k[k] = mf
    # Default: 1.0 (no derate) when no lines block.
    def maint_factor(k, t):
        if k in maint_factor_k and t < len(maint_factor_k[k]):
            return maint_factor_k[k][t]
        return 1.0

    # ── Build problem ──
    prob = pulp.LpProblem("Procurement_Optimizer", pulp.LpMinimize)

    # ── Decision variables ──
    p = {}   # production
    inv = {}  # FG inventory
    short = {}  # shortages
    y = {}   # production binary
    r = {}   # RM orders
    o = {}   # RM order binary
    rm_inv = {}  # RM inventory

    all_parts = []
    part_map = {}  # (product_idx, part_idx) -> global part index

    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)
        while len(demand) < T:
            demand.append(demand[-1] if demand else 0)
        demand = demand[:T]

        cap = prod.get('capacity', 50)
        setup_cost = prod.get('setup_cost', 50)
        var_cost = prod.get('variable_cost', 0)
        shelf = prod.get('shelf_life_periods') or prod.get('shelf_life', T)
        sell_price = prod.get('sell_price', 10)
        fy = prod.get('yield_pct', 0.95)
        short_penalty = sell_price * 1.5  # lost margin + goodwill

        # Safety stock — T3-08 honors per-product ABC/XYZ class when supplied.
        # T8-05 — Heizer formula honors BOTH demand variance AND lead-time variance:
        #   SS = Z × √(LT × σ²_d + d̄² × σ²_LT)
        # where σ_LT = LT × lt_cv (using max LT-CV across BOM parts for this product, since
        # SS protects against the slowest replenishment path). Falls back to demand-only
        # when no parts/lt_cv information is available.
        demand_arr = np.array(demand, dtype=float)
        avg_d = max(demand_arr.mean(), 0.1)
        std_d = max(demand_arr.std(), 0.1)
        z_eff = per_product_z(prod)
        # Find the bottleneck part: max(LT × (1 + lt_cv)) — the path that drives SS sizing.
        _parts_for_ss = prod.get('parts', []) or []
        if _parts_for_ss:
            lt_for_ss = max(float(pt.get('lead_time', 1) or 1) for pt in _parts_for_ss)
            lt_cv_for_ss = max(float(pt.get('lt_cv', 0) or 0) for pt in _parts_for_ss)
        else:
            lt_for_ss = 1.0
            lt_cv_for_ss = 0.0
        sigma_lt = lt_for_ss * lt_cv_for_ss
        sigma_ltd = math.sqrt(max(lt_for_ss, 1.0) * std_d ** 2 + (avg_d ** 2) * (sigma_lt ** 2))
        ss = max(1, round(z_eff * sigma_ltd))

        for t in range(T):
            p[k, t] = pulp.LpVariable(f'p_{k}_{t}', 0, cap, cat='Integer')
            inv[k, t] = pulp.LpVariable(f'inv_{k}_{t}', 0)
            short[k, t] = pulp.LpVariable(f'short_{k}_{t}', 0)
            y[k, t] = pulp.LpVariable(f'y_{k}_{t}', cat='Binary')

        # BOM parts
        parts = prod.get('parts', [])
        for i, part in enumerate(parts):
            gidx = len(all_parts)
            part_map[(k, i)] = gidx
            # P6 — prefer landed_cost (home currency, FX-hedged, freight+duty+handling) when UI provides it.
            # Falls back to raw cost so the solver still works for older payloads without supplier profiles.
            _base_cost = part.get('landed_cost')
            if _base_cost is None:
                _base_cost = part.get('cost', 1.0)
            # T5-09 — VMI parts bypass MOQ / MaxOrder / ord_cost. Supplier replenishes
            # to target stock-days; solver treats supply as ∞ within RM cap and books
            # zero ordering admin cost. The PO output flags these as vmi=True.
            is_vmi = bool(part.get('vmi', False))
            all_parts.append({
                'name': part.get('name', f'Part_{k}_{i}'),
                'cost': _base_cost,
                'qty_per': part.get('qty_per', 1.0),
                'lt': part.get('lead_time', 1),
                'moq': 0 if is_vmi else part.get('moq', 1),
                'max_order': 999999 if is_vmi else part.get('max_order', 9999),
                'hold_pct': part.get('hold_pct', carry_rate * 100),
                'rm_cap': 999999 if is_vmi else part.get('rm_capacity', 9999),
                'ord_cost': 0 if is_vmi else part.get('ordering_cost', 50),
                'rm_shelf': part.get('rm_shelf', T),
                'product_k': k,
                'part_i': i,
                'scrap': part.get('scrap_factor', 0),
                'vol_disc': part.get('vol_disc', []),
                'trans_tiers': part.get('trans_tiers', []),
                'trans_rate': part.get('trans_rate', 0.0),
                'pay_term_days': part.get('pay_term_days', 30),
                'early_pay_disc': part.get('early_pay_disc', 0),
                'proc_policy': (part.get('proc_policy') or 'milp').lower(),
                'rm_footprint_area': float(part.get('rm_footprint_area', 0.05) or 0.05),
                'rm_footprint_volume': float(part.get('rm_footprint_volume', 0.02) or 0.02),
                # #2 — UoM-aware capacity. uom = recipe unit (g/ml/L/kg/pcs); purchase_pack = qty per pack
                # in same uom (e.g. 100 L per drum). Footprint is per-PACK (one drum = one slot), so
                # rm_inv (in recipe-uom) is divided by purchase_pack to get pack count for capacity check.
                'uom': str(part.get('uom') or 'u'),
                'purchase_pack': max(float(part.get('purchase_pack', 1) or 1), 1e-9),
                # NEW — Fixed-rate transport contract. When True, tier discounts/transport tiers are bypassed.
                'trans_contract_fixed': bool(part.get('trans_contract_fixed', False)),
                'trans_contract_rate': float(part.get('trans_contract_rate', 0) or 0),
                # #7 — per-part CO₂ factor (kg per recipe-uom). Used by CO2_max_per_period constraint.
                'co2_factor': float(part.get('co2_factor', 0) or 0),
                # #7 — FX-exposure flag. True when supplier currency ≠ home currency. Used by fx_exposure_max_pct.
                'is_foreign_currency': bool(part.get('is_foreign_currency', False)),
                # T5-01/05/09 — supplier master metadata threaded through to PO output.
                'supplier_name': part.get('supplier_name', '') or '',
                'supplier_state': part.get('supplier_state', '') or '',
                'supplier_country': part.get('supplier_country', 'IN') or 'IN',
                'vmi': is_vmi,
                'vmi_target_stock_days': float(part.get('vmi_target_stock_days', 14) or 14),
                'vmi_review_freq_days': float(part.get('vmi_review_freq_days', 7) or 7),
                # raw_unit_cost preserves the un-landed cost so PO output can show both.
                'raw_unit_cost': part.get('cost', _base_cost),
                'landed_unit_cost': _base_cost,
            })

            for t in range(T):
                r[gidx, t] = pulp.LpVariable(f'r_{gidx}_{t}', 0, cat='Integer')
                o[gidx, t] = pulp.LpVariable(f'o_{gidx}_{t}', cat='Binary')
                rm_inv[gidx, t] = pulp.LpVariable(f'rminv_{gidx}_{t}', 0)

    # ── Objective function ──
    obj = []

    # Helper — expand scalar base into period-indexed series, applying cost_events.
    # Cost events are stepwise: from_month m onwards, param switches to new value.
    def _period_series(base, events, param_key, weeks_per_month=4):
        series = [base] * T
        if not events:
            return series
        ev = sorted(
            [e for e in events if e.get('param') == param_key],
            key=lambda e: e.get('from_month', 0),
        )
        for e in ev:
            fm_week = int(e.get('from_month', 0)) * weeks_per_month
            new_val = e.get('value', base)
            for t in range(fm_week, T):
                series[t] = new_val
        return series

    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)[:T]
        setup_base = prod.get('setup_cost', 50)
        vc_base = prod.get('variable_cost', 0)
        sp_base = prod.get('sell_price', 10)
        events = prod.get('cost_events', [])
        setup_series = _period_series(setup_base, events, 'setupCost')
        vc_series = _period_series(vc_base, events, 'variableCost')
        sp_series = _period_series(sp_base, events, 'sellPrice')
        shelf = prod.get('shelf_life_periods') or prod.get('shelf_life', T)
        fy = prod.get('yield_pct', 0.95)
        unit_cost = sum(
            pt.get('cost', 1) * pt.get('qty_per', 1)
            for pt in prod.get('parts', [])
        )
        fg_hold = unit_cost * carry_rate / 52  # weekly holding cost per unit
        # v3.6 — Milk-run inbound consolidation cost (fixed per period when active).
        # Wired from JS payload milk_run_per_period (computed via milkRunPerPeriod in index.html).
        milk_run_pp = float(prod.get('milk_run_per_period', 0) or 0)

        for t in range(T):
            # Setup cost (period-varying)
            obj.append(setup_series[t] * y[k, t])
            # Variable production cost (period-varying)
            obj.append(vc_series[t] * p[k, t])
            # FG holding
            obj.append(fg_hold * inv[k, t])
            # Shortage penalty (period-varying via sell_price events)
            obj.append(sp_series[t] * 1.5 * short[k, t])
            # v3.6 — Milk run fixed cost per period
            if milk_run_pp:
                obj.append(milk_run_pp)

    # RM costs — with volume discount & transport tier support via effective unit cost.
    # Strategy: for each part compute effective per-unit cost at the MAX applicable tier
    # (assumes solver will tend toward larger batches when discount dominates holding).
    # For piecewise-linear exact MILP discount modelling, we use tier-indicator binaries.
    tier_indicators = {}  # (gidx,t,tier_i) -> binary
    for gidx, part in enumerate(all_parts):
        base_cost = part['cost']
        # NEW — Fixed-rate transport contract bypass. When a part has a signed fixed-rate contract,
        # volume tiers and transport-tier discounts are inert: the contract rate applies regardless of qty.
        # This matches reality (carrier signed off on a flat rate, won't honour any tiers).
        contract_fixed = bool(part.get('trans_contract_fixed', False))
        contract_rate = float(part.get('trans_contract_rate', 0) or 0)
        if contract_fixed:
            tiers = []
            trans_tiers = []
            default_trans = contract_rate
        else:
            tiers = sorted(part.get('vol_disc', []) or [], key=lambda x: x.get('minQty', 0))
            trans_tiers = sorted(part.get('trans_tiers', []) or [], key=lambda x: x.get('minQty', 0))
            default_trans = part.get('trans_rate', 0.0) or 0.0
        has_vol = len(tiers) > 1
        has_trans = len(trans_tiers) > 0
        for t in range(T):
            if has_vol or has_trans:
                # Build tier break points combining both discount and transport tiers
                break_qtys = sorted(set(
                    [x.get('minQty', 0) for x in tiers]
                    + [x.get('minQty', 0) for x in trans_tiers]
                    + [0]
                ))
                # Indicator binaries: exactly one active per period
                inds = {}
                seg_costs = []
                for si, q_lo in enumerate(break_qtys):
                    q_hi = break_qtys[si + 1] if si + 1 < len(break_qtys) else None
                    # Effective unit cost at this tier
                    disc_pct = 0
                    for vd in tiers:
                        if vd.get('minQty', 0) <= q_lo:
                            disc_pct = max(disc_pct, vd.get('pct', 0))
                    eff_cost = base_cost * (1 - disc_pct / 100.0)
                    trans_rate_eff = default_trans
                    for tt in trans_tiers:
                        if tt.get('minQty', 0) <= q_lo:
                            trans_rate_eff = tt.get('rate', default_trans)
                    seg_costs.append((q_lo, q_hi, eff_cost + trans_rate_eff))
                    inds[si] = pulp.LpVariable(f'tier_{gidx}_{t}_{si}', cat='Binary')
                tier_indicators[(gidx, t)] = inds
                # Exactly one segment active when ordering; zero if not ordering
                prob += pulp.lpSum(inds[si] for si in inds) == o[gidx, t], \
                    f"TierOne_{gidx}_{t}"
                # Force r within selected segment bounds
                M = part.get('max_order', 9999)
                for si, (q_lo, q_hi, _) in enumerate(seg_costs):
                    prob += r[gidx, t] >= q_lo * inds[si], f"TierLo_{gidx}_{t}_{si}"
                    if q_hi is not None:
                        prob += r[gidx, t] <= q_hi * inds[si] + M * (1 - inds[si]), \
                            f"TierHi_{gidx}_{t}_{si}"
                # Cost contribution: sum of (segment_cost × qty × ind) — linearize via
                # auxiliary: r_seg[si] = r * ind[si]. To keep linear, approximate with
                # segment cost × minQty as baseline plus marginal at that tier rate.
                # Simplification: weight each segment's effective rate by indicator × r cap.
                # Since r is bounded by max_order, we use effective cost of the binding tier:
                # total = sum(seg_cost[si] × inds[si] × r[t]) — nonlinear; use McCormick/big-M
                # Introduce auxiliary r_seg ≥ 0, r_seg ≤ M*ind, r_seg ≤ r, r_seg ≥ r - M*(1-ind)
                for si, (q_lo, q_hi, eff_rate) in enumerate(seg_costs):
                    r_seg = pulp.LpVariable(f'rseg_{gidx}_{t}_{si}', 0, M)
                    prob += r_seg <= M * inds[si], f"RsegUB1_{gidx}_{t}_{si}"
                    prob += r_seg <= r[gidx, t], f"RsegUB2_{gidx}_{t}_{si}"
                    prob += r_seg >= r[gidx, t] - M * (1 - inds[si]), f"RsegLB_{gidx}_{t}_{si}"
                    obj.append(eff_rate * r_seg)
            else:
                # No tiers — base cost + simple per-unit transport
                obj.append((base_cost + default_trans) * r[gidx, t])
            # Ordering admin cost
            obj.append(part['ord_cost'] * o[gidx, t])
            # RM holding (use base cost as proxy for holding valuation)
            rm_hold = base_cost * (part['hold_pct'] / 100) / 52
            obj.append(rm_hold * rm_inv[gidx, t])

    # Fixed overhead
    obj.append(fixed_daily * T)

    prob += pulp.lpSum(obj), "Total_Cost"

    # ── Constraints ──

    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)[:T]
        cap = prod.get('capacity', 50)
        shelf = prod.get('shelf_life_periods') or prod.get('shelf_life', T)
        fy = prod.get('yield_pct', 0.95)
        init_inv = prod.get('init_inventory', 0)
        demand_mode = prod.get('demand_mode', 'mts-weekly')
        # P4 — actuals_override: per-product, per-period committed production (e.g. demand-sensing replan).
        # When (replan_from_period is set) AND (actuals_override[t] is not None) AND (t < replan_from_period),
        # the LP fixes p[k,t] to that committed value. Periods >= replan_from_period stay free.
        actuals_override = prod.get('actuals_override') or []

        # T8-05 — Heizer SS formula (LT-aware) for the MTO no-build cap below.
        demand_arr = np.array(demand, dtype=float)
        avg_d_c = max(demand_arr.mean(), 0.1)
        std_d_c = max(demand_arr.std(), 0.1)
        _parts_c = prod.get('parts', []) or []
        if _parts_c:
            lt_c = max(float(pt.get('lead_time', 1) or 1) for pt in _parts_c)
            ltcv_c = max(float(pt.get('lt_cv', 0) or 0) for pt in _parts_c)
        else:
            lt_c, ltcv_c = 1.0, 0.0
        sigma_ltd_c = math.sqrt(max(lt_c, 1.0) * std_d_c ** 2 + (avg_d_c ** 2) * ((lt_c * ltcv_c) ** 2))
        ss = max(1, round(z * sigma_ltd_c))

        for t in range(T):
            d = demand[t] if t < len(demand) else demand[-1]

            # C1: Inventory balance
            prev_inv = inv[k, t - 1] if t > 0 else init_inv
            good_prod = p[k, t]  # simplified: yield applied at BOM consumption
            prob += inv[k, t] == prev_inv + good_prod - d + short[k, t], \
                f"InvBal_{k}_{t}"

            # C2: Capacity (scaled by per-period working-day factor — Pillar 6 holiday exclusion)
            # T8-03 — also scaled by line-maintenance factor (1.0 = no derate, 0.0 = all eligible lines down).
            eff_cap = cap * (cap_factor[t] if t < len(cap_factor) else 1.0) * maint_factor(k, t)
            prob += p[k, t] <= eff_cap * y[k, t], f"Cap_{k}_{t}"

            # C3: Min production (if producing, produce at least 1)
            prob += p[k, t] >= y[k, t], f"MinProd_{k}_{t}"

            # P4 — C-LOCK: if a replan anchor is set, force production for committed actuals.
            if replan_from_period is not None and t < replan_from_period and t < len(actuals_override):
                ato = actuals_override[t]
                if ato is not None:
                    try:
                        ato_v = int(round(float(ato)))
                        prob += p[k, t] == ato_v, f"LockActual_{k}_{t}"
                    except Exception:
                        pass

            # C4: Warehouse limit (shared across products)
            # Added below as aggregate

            # C5: No backorder if disabled
            if not bo_on:
                prob += short[k, t] == 0, f"NoBO_{k}_{t}"

            # Pillar 13 — demand_mode variants
            # MTO: no inventory build-ahead. FG inv capped at safety stock; production tracks demand each period.
            if demand_mode == 'mto':
                prob += inv[k, t] <= ss, f"MTO_NoBuild_{k}_{t}"
                prob += p[k, t] <= d + ss, f"MTO_TrackDemand_{k}_{t}"

        # Simultaneous: total horizon demand must be met by total horizon production + init_inv
        if demand_mode == 'simultaneous':
            total_d = sum(demand)
            prob += pulp.lpSum(p[k, tt] for tt in range(T)) + init_inv >= total_d, f"Simul_HorizonMeet_{k}"

    # Aggregate warehouse constraint
    for t in range(T):
        prob += pulp.lpSum(
            inv[k, t] for k in range(n_products)
        ) <= wh_max, f"WH_{t}"

    # Pillar 10 — working-capital hard constraint. Sum of (FG inv × selling-price) + (RM inv × base-cost) per period ≤ working_capital.
    if working_capital and working_capital > 0:
        for t in range(T):
            fg_value = [inv[k, t] * (products[k].get('sell_price') or 100) for k in range(n_products)]
            # rm_inv populated later; add RM value terms when we enter the RM loop (lazy add below).
            prob += pulp.lpSum(fg_value) <= working_capital, f"WC_FG_{t}"

    # Shared capacity constraint (scaled by holiday cap factor)
    if cap_mode == 'shared':
        shared_cap = params.get('shared_capacity', 100)
        for t in range(T):
            eff_shared = shared_cap * (cap_factor[t] if t < len(cap_factor) else 1.0)
            prob += pulp.lpSum(
                p[k, t] for k in range(n_products)
            ) <= eff_shared, f"SharedCap_{t}"

    # T6 — Build scheduled_receipts[gidx][t]: already-purchased POs that arrive in-horizon.
    # Each locked PO carries {part, qty, releaseDate}. Arrival period = (release - horizon_start)/dpp + lead_time.
    # Negative arrive_t (PO already arrived before horizon start) is dropped — its qty is assumed already in
    # init_inventory. Out-of-horizon arrivals (≥ T) are dropped — solver can't act on them.
    # Backward-compat: if a lock carries an integer `period` field (legacy shape), it's treated as
    # release_period directly; otherwise the date math runs.
    from datetime import date as _date
    name_to_gidx = {part['name']: gidx for gidx, part in enumerate(all_parts)}
    scheduled_receipts = {gidx: [0] * T for gidx in range(len(all_parts))}
    if locked_pos and horizon_start_date:
        try:
            hz_start = _date.fromisoformat(horizon_start_date)
        except Exception:
            hz_start = None
    else:
        hz_start = None
    days_per_period = {'daily': 1, 'monthly': 30}.get(time_grain, 7)
    for lk in locked_pos:
        nm = lk.get('part_name') or lk.get('part') or ''
        if nm not in name_to_gidx:
            continue
        gidx = name_to_gidx[nm]
        lt = all_parts[gidx]['lt']
        qty = int(lk.get('qty') or 0)
        if qty <= 0:
            continue
        # Resolve release period from explicit `period`, then `releaseDate` against horizon start.
        rel_p = None
        if lk.get('period') is not None:
            try:
                rel_p = int(lk.get('period'))
            except Exception:
                rel_p = None
        if rel_p is None and hz_start and lk.get('releaseDate'):
            try:
                rel_dt = _date.fromisoformat(str(lk['releaseDate'])[:10])
                rel_p = (rel_dt - hz_start).days // days_per_period
            except Exception:
                rel_p = None
        if rel_p is None:
            continue
        arrive_p = rel_p + lt
        if 0 <= arrive_p < T:
            scheduled_receipts[gidx][arrive_p] += qty

    # RM constraints
    for gidx, part in enumerate(all_parts):
        k = part['product_k']
        i = part['part_i']
        prod = products[k]
        demand = prod.get('demand', [0] * T)[:T]
        lt = part['lt']
        moq = part['moq']
        max_ord = part['max_order']
        rm_cap = part['rm_cap']
        qty_per = part['qty_per']
        scrap = part['scrap']
        fy = prod.get('yield_pct', 0.95)
        # #5 — Yield carry-forward. When yield_actual > yield_pct, prior period's RM had buffer
        # that wasn't consumed (better-than-expected yield ⇒ less RM needed). Surplus carries
        # forward as extra inventory entering the next period. yield_carry_frac is the fraction
        # of prior-period CONSUMED RM that becomes surplus: 1 - yield_pct/yield_actual.
        # Defensive: planning still uses predicted yield baseline; carry-fwd is a credit on top.
        y_act = prod.get('yield_actual')
        y_act = float(y_act) if (y_act is not None) else None
        yield_carry_frac = 0.0
        if y_act is not None and y_act > fy and y_act > 0:
            yield_carry_frac = 1.0 - (fy / y_act)
        effective_qty = qty_per * (1 + scrap) / max(fy, 0.01)
        # Default init RM: enough for lead_time periods of avg demand
        avg_demand_per_t = sum(demand[:T]) / T if T > 0 else 10
        default_init_rm = max(0, round(avg_demand_per_t * effective_qty * (lt + 1)))
        init_rm = part.get('init_inventory', default_init_rm)

        for t in range(T):
            # RM arrives lt periods after ordering
            arrive_t = t - lt
            arrived = r[gidx, arrive_t] if arrive_t >= 0 else 0

            # T6 — Scheduled receipts: already-released POs that arrive at this period.
            # Treated as exogenous inventory bumps; solver re-optimises around them.
            sched_rcpt = scheduled_receipts[gidx][t]

            # RM consumption = production * effective qty per unit
            consumed = p[k, t] * effective_qty

            # #5 — yield carry-forward into period t from period t-1's surplus
            yield_carry_in = (p[k, t - 1] * effective_qty * yield_carry_frac) if (t > 0 and yield_carry_frac > 0) else 0

            prev_rm = rm_inv[gidx, t - 1] if t > 0 else init_rm
            prob += rm_inv[gidx, t] == prev_rm + arrived + sched_rcpt + yield_carry_in - consumed, \
                f"RMBal_{gidx}_{t}"

            # RM non-negative (redundant with var bounds but explicit)
            prob += rm_inv[gidx, t] >= 0, f"RMNonNeg_{gidx}_{t}"

            # MOQ: if ordering, order at least MOQ
            prob += r[gidx, t] >= moq * o[gidx, t], f"MOQ_{gidx}_{t}"
            prob += r[gidx, t] <= max_ord * o[gidx, t], f"MaxOrd_{gidx}_{t}"

            # RM warehouse capacity (per-part units cap — always active)
            prob += rm_inv[gidx, t] <= rm_cap, f"RMCap_{gidx}_{t}"

    # P7 / #2 — aggregate RM warehouse cap (area or volume mode). Footprint is per-PACK
    # (one drum = one slot), so we divide rm_inv (in recipe-uom) by purchase_pack to get
    # pack count, then multiply by footprint. For legacy parts where pack=1, behaviour is identical.
    if rm_wh_mode == 'area' and rm_wh_limit_area > 0:
        for t in range(T):
            prob += pulp.lpSum(
                rm_inv[gidx, t] * (part['rm_footprint_area'] / part['purchase_pack'])
                for gidx, part in enumerate(all_parts)
            ) <= rm_wh_limit_area, f"RMWHArea_{t}"
    elif rm_wh_mode == 'volume' and rm_wh_limit_volume > 0:
        for t in range(T):
            prob += pulp.lpSum(
                rm_inv[gidx, t] * (part['rm_footprint_volume'] / part['purchase_pack'])
                for gidx, part in enumerate(all_parts)
            ) <= rm_wh_limit_volume, f"RMWHVol_{t}"

    # Pillar 10 — add RM inventory value into per-period working capital sum. Combined FG+RM ≤ WC.
    if working_capital and working_capital > 0:
        for t in range(T):
            rm_value = [part['cost'] * rm_inv[gidx, t] for gidx, part in enumerate(all_parts)]
            fg_value = [inv[k, t] * (products[k].get('sell_price') or 100) for k in range(n_products)]
            prob += pulp.lpSum(fg_value + rm_value) <= working_capital, f"WC_Combined_{t}"

    # Budget constraint (optional)
    if budget and budget > 0:
        if budget_deflate and inflation_pct_annual > 0:
            # #7 — Inflation-deflated budget. Per-period cap is divided by (1+infl)^(t/periods_per_year).
            # Real purchasing power: Σ_per_period spend ≤ budget / (1+infl)^t. Total horizon stays bounded.
            ann_infl = inflation_pct_annual / 100.0
            for t in range(T):
                deflate = (1 + ann_infl) ** (t / max(periods_per_year, 1))
                period_cap = (budget / max(T, 1)) / max(deflate, 1e-9)
                prob += pulp.lpSum(
                    part['cost'] * r[gidx, t]
                    for gidx, part in enumerate(all_parts)
                ) <= period_cap, f"BudgetDeflated_{t}"
        else:
            prob += pulp.lpSum(
                part['cost'] * r[gidx, t]
                for gidx, part in enumerate(all_parts)
                for t in range(T)
            ) <= budget, "Budget"

    # #7 — Labor hours constraint. Σ_t (p[k,t] × labor_per_unit) ≤ labor_hours_max per period.
    if labor_hours_max > 0:
        labor_per_u_by_k = [float(products[k].get('labor_per_unit', 0) or 0) for k in range(n_products)]
        if any(lp > 0 for lp in labor_per_u_by_k):
            for t in range(T):
                prob += pulp.lpSum(
                    p[k, t] * labor_per_u_by_k[k] for k in range(n_products)
                ) <= labor_hours_max, f"LaborHrs_{t}"

    # #7 — CO₂ per-period cap. Σ_part r[gidx,t] × co2_per_unit ≤ co2_max_per_period.
    # co2_per_unit comes from part-level co2_factor (kg per recipe-uom). Falls back to 0 if not set.
    if co2_max_per_period > 0:
        co2_by_g = [float(p_.get('co2_factor', 0) or 0) for p_ in all_parts]
        if any(c > 0 for c in co2_by_g):
            for t in range(T):
                prob += pulp.lpSum(
                    r[gidx, t] * co2_by_g[gidx] for gidx in range(len(all_parts))
                ) <= co2_max_per_period, f"CO2_{t}"

    # #7 — Single-supplier concentration cap. Anti-concentration risk control:
    # Σ spend with supplier S over horizon ≤ (cap%) × total spend over horizon.
    # We approximate by aggregating all_parts by supplier_name. Linear because both sides scale with r.
    if supplier_concentration_max_pct > 0 and supplier_concentration_max_pct < 100:
        sup_to_gidx = {}
        for gidx, part in enumerate(all_parts):
            sup = part.get('supplier_name') or 'unknown'
            sup_to_gidx.setdefault(sup, []).append(gidx)
        if len(sup_to_gidx) > 1:  # only meaningful with >1 supplier
            cap_frac = supplier_concentration_max_pct / 100.0
            total_spend = pulp.lpSum(
                part['cost'] * r[gidx, t]
                for gidx, part in enumerate(all_parts)
                for t in range(T)
            )
            for sup, gidxs in sup_to_gidx.items():
                sup_spend = pulp.lpSum(
                    all_parts[gidx]['cost'] * r[gidx, t]
                    for gidx in gidxs
                    for t in range(T)
                )
                # sup_spend ≤ cap_frac × total_spend  ⇒  sup_spend - cap_frac*total_spend ≤ 0
                prob += sup_spend - cap_frac * total_spend <= 0, f"SupConc_{sup[:20]}"

    # #7 — FX exposure cap. Σ_foreign-spend ≤ cap × Σ_total-spend across the horizon.
    # is_foreign_currency is derived JS-side from supplierProfiles[name].currency vs config.currency.
    if fx_exposure_max_pct > 0 and fx_exposure_max_pct < 100:
        foreign_gidxs = [gidx for gidx, part in enumerate(all_parts) if part.get('is_foreign_currency')]
        if foreign_gidxs:
            cap_frac_fx = fx_exposure_max_pct / 100.0
            total_spend_fx = pulp.lpSum(
                part['cost'] * r[gidx, t]
                for gidx, part in enumerate(all_parts)
                for t in range(T)
            )
            foreign_spend = pulp.lpSum(
                all_parts[gidx]['cost'] * r[gidx, t]
                for gidx in foreign_gidxs
                for t in range(T)
            )
            prob += foreign_spend - cap_frac_fx * total_spend_fx <= 0, "FXExposureCap"

    # #7 — ABC service-level for A-class SKUs. When set, Σ_short across A-class products ≤
    # (1 - target_a) × Σ_demand across A-class products. Tighter than the global service_level.
    # is_class_a comes per-product from JS (p.abcClass === 'A').
    if abc_service_a_min_pct > 0 and abc_service_a_min_pct < 100 and bo_on:
        a_class_ks = [k for k in range(n_products) if str(products[k].get('abc_class', '')).upper() == 'A']
        if a_class_ks:
            target_a = abc_service_a_min_pct / 100.0
            total_demand_a = sum(
                sum((products[k].get('demand', [0] * T) or [0] * T)[:T]) for k in a_class_ks
            )
            if total_demand_a > 0:
                short_cap_a = (1.0 - target_a) * total_demand_a
                total_short_a = pulp.lpSum(short[k, t] for k in a_class_ks for t in range(T))
                prob += total_short_a <= short_cap_a, "ABCServiceA"

    # T8-04 — Fill-rate constraint. Only meaningful when backorders are allowed (else short==0
    # and fill rate is implicitly 100%). Two modes:
    #   'hard'  : Σshort ≤ (1 − target) × Σdemand     (infeasible if RM/capacity can't meet)
    #   'soft'  : aux fr_slack ≥ Σshort − cap; penalty 100× into objective.
    #   'off'   : skip
    # The target is a horizon-wide aggregate (matches APO/IBP CTM behavior). Per-period
    # fill-rate would over-constrain because demand can be 0 in some periods.
    if bo_on and fill_rate_mode != 'off' and fill_rate_target > 0:
        total_demand_h = sum(
            sum((products[k].get('demand', [0] * T) or [0] * T)[:T]) for k in range(n_products)
        )
        if total_demand_h > 0:
            short_cap = (1.0 - fill_rate_target) * total_demand_h
            total_short = pulp.lpSum(short[k, t] for k in range(n_products) for t in range(T))
            if fill_rate_mode == 'hard':
                prob += total_short <= short_cap, "FillRateHard"
            else:  # soft
                fr_slack = pulp.LpVariable('fill_rate_slack', 0)
                prob += total_short - fr_slack <= short_cap, "FillRateSoft"
                # Penalty rate scales with weighted average sell price so it is meaningful.
                avg_sp = (sum(products[k].get('sell_price', 100) for k in range(n_products))
                          / max(n_products, 1))
                prob.objective = prob.objective + 100.0 * avg_sp * fr_slack

    # T6-08 — Logistics (transport) budget gate. Total transport spend = Σ part.trans_rate × r[gidx,t].
    # This is the inbound-RM transport leg (matches what the JS UI accumulates as freight_spend
    # for the active lanes touching each part). Outbound transport is layered on top in profitmix
    # but for procurement we enforce the inbound side only.
    if logistics_budget is not None and logistics_mode != 'unconstrained':
        log_spend_terms = [
            part.get('trans_rate', 0.0) * r[gidx, t]
            for gidx, part in enumerate(all_parts)
            for t in range(T)
            if part.get('trans_rate', 0.0) > 0
        ]
        if log_spend_terms:
            log_spend = pulp.lpSum(log_spend_terms)
            if logistics_mode == 'hard' and logistics_budget > 0:
                prob += log_spend <= logistics_budget, "LogisticsBudgetHard"
            elif logistics_mode == 'soft':
                # Slack variable for over-budget; multiplied by 10× into objective.
                # This makes the budget visible without going infeasible.
                cap = logistics_budget if logistics_budget > 0 else 0
                slack = pulp.LpVariable('logistics_overrun', 0)
                prob += log_spend - slack <= cap, "LogisticsBudgetSoft"
                # Update existing objective in-place (don't re-emit — PuLP would treat it as a new constraint).
                prob.objective = prob.objective + 10.0 * slack

    # T6 — Locked POs are now handled as scheduled_receipts in the RM balance loop above.
    # The earlier forced-release-decision constraint (r[gidx, t] == q) was wrong on two counts:
    # (1) the JS payload sends releaseDate, not period, so period was always None and locks
    #     were silently dropped; (2) modelling as a forced release ignored the fact that the
    #     buying decision is already made — the planner only wants the qty to land in inventory
    #     at the arrival period, not to constrain the solver's release decision (which would
    #     double-count if the PO was released before horizon start).

    # ── Solve ──
    solver = pulp.PULP_CBC_CMD(
        msg=0,
        timeLimit=90,
        gapRel=0.02
    )
    status = prob.solve(solver)

    solve_time = time.time() - t0

    if status != pulp.constants.LpStatusOptimal:
        return {
            'status': pulp.LpStatus[status],
            'error': f'Solver returned: {pulp.LpStatus[status]}',
            'solve_time': round(solve_time, 2)
        }

    # ── Extract results ──
    total_cost = pulp.value(prob.objective)

    product_results = []
    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)[:T]
        prod_schedule = [int(pulp.value(p[k, t]) or 0) for t in range(T)]
        inv_levels = [round(pulp.value(inv[k, t]) or 0, 1) for t in range(T)]
        shortages = [round(pulp.value(short[k, t]) or 0, 1) for t in range(T)]
        setups = [int(pulp.value(y[k, t]) or 0) for t in range(T)]

        total_prod = sum(prod_schedule)
        total_demand = sum(demand[:T])
        total_short = sum(shortages)
        fill_rate = round((1 - total_short / max(total_demand, 1)) * 100, 1)

        product_results.append({
            'name': prod.get('name', f'Product_{k}'),
            'production': prod_schedule,
            'inventory': inv_levels,
            'shortages': shortages,
            'setups': setups,
            'total_produced': total_prod,
            'total_demand': total_demand,
            'total_shortage': round(total_short),
            'fill_rate': fill_rate,
            'num_batches': sum(setups),
        })

    material_results = []
    for gidx, part in enumerate(all_parts):
        orders = [int(pulp.value(r[gidx, t]) or 0) for t in range(T)]
        rm_levels = [round(pulp.value(rm_inv[gidx, t]) or 0, 1) for t in range(T)]
        order_flags = [int(pulp.value(o[gidx, t]) or 0) for t in range(T)]

        # Build PO list — T5-01/06/09 metadata: supplier_name, payment_term_days, landed_cost,
        # vmi flag. UI's PoReleasePlanCard reads these directly.
        po_list = []
        for t in range(T):
            if orders[t] > 0:
                po_list.append({
                    'period': t,
                    'arrive_period': t + part['lt'],
                    'quantity': orders[t],
                    'cost': round(orders[t] * part['raw_unit_cost'], 2),
                    'landed_cost': round(orders[t] * part['landed_unit_cost'], 2),
                    'unit_cost': part['raw_unit_cost'],
                    'unit_landed_cost': part['landed_unit_cost'],
                    'supplier_name': part['supplier_name'],
                    'supplier_state': part['supplier_state'],
                    'supplier_country': part['supplier_country'],
                    'payment_term_days': part['pay_term_days'],
                    'vmi': part['vmi'],
                })

        # v3.2 — compute MILP's realized per-part cost for comparison
        milp_cost = round(
            sum(orders) * part['cost']
            + sum(order_flags) * part['ord_cost']
            + sum(rm_levels) * part['cost'] * (part['hold_pct'] / 100) / 52,
            2,
        )

        # v3.2 — run alternative closed-form / heuristic policies on the part's
        # derived demand (production × qty_per × effective_qty_mult) for ranking.
        k = part['product_k']
        prod = products[k]
        fy = prod.get('yield_pct', 0.95)
        qty_per = part['qty_per']
        scrap = part['scrap']
        eff_mult = qty_per * (1 + scrap) / max(fy, 0.01)
        prod_schedule = product_results[k]['production']
        part_demand = [int(round(q * eff_mult)) for q in prod_schedule]

        lp_params = {
            'unit_cost': part['cost'],
            'ord_cost': part['ord_cost'],
            'hold_rate_annual': part['hold_pct'] / 100,
            'hold_rate_weekly': (part['hold_pct'] / 100) / 52,
            'lead_time': part['lt'],
            'z': z,
            'init_inv': 0,
            'max_shortage': 0,
        }
        alt = auto_select_policy(part_demand, lp_params)
        leaderboard = alt['leaderboard']
        # Prepend MILP for ranking visibility (flagged separately)
        leaderboard = [{
            'policy': 'milp',
            'label': 'MILP (joint solver)',
            'total_cost': milp_cost,
            'order_cost': round(sum(order_flags) * part['ord_cost'], 2),
            'hold_cost': round(
                sum(rm_levels) * part['cost'] * (part['hold_pct'] / 100) / 52,
                2,
            ),
            'num_orders': sum(order_flags),
            'shortage': 0,
            'feasible': True,
        }] + leaderboard
        leaderboard.sort(key=lambda x: (not x['feasible'], x['total_cost']))
        cheapest_policy = leaderboard[0]['policy'] if leaderboard else 'milp'

        # Honor per-part procPolicy setting
        policy_pref = part.get('proc_policy', 'milp')
        if policy_pref == 'auto':
            chosen = cheapest_policy
        elif policy_pref in ('milp', None, ''):
            chosen = 'milp'
        else:
            chosen = policy_pref

        material_results.append({
            'name': part['name'],
            'product': products[part['product_k']].get('name', ''),
            'orders': orders,
            'inventory': rm_levels,
            'purchase_orders': po_list,
            'total_ordered': sum(orders),
            'total_cost': round(sum(orders) * part['cost'], 2),
            'total_landed_cost': round(sum(orders) * part['landed_unit_cost'], 2),
            'num_orders': sum(order_flags),
            # T5-01/05/09 metadata
            'supplier_name': part['supplier_name'],
            'supplier_state': part['supplier_state'],
            'supplier_country': part['supplier_country'],
            'payment_term_days': part['pay_term_days'],
            'vmi': part['vmi'],
            'vmi_target_stock_days': part['vmi_target_stock_days'],
            # v3.2 additions
            'proc_policy_pref': policy_pref,
            'proc_policy_chosen': chosen,
            'cheapest_policy': cheapest_policy,
            'milp_cost': milp_cost,
            'policy_leaderboard': leaderboard,
            'winner_vs_milp_savings': round(
                milp_cost - (leaderboard[0]['total_cost'] if leaderboard else milp_cost),
                2,
            ),
        })

    # Cost breakdown
    cost_breakdown = {
        'total': round(total_cost, 2),
        'material_purchase': round(sum(
            sum(int(pulp.value(r[g, t]) or 0) * all_parts[g]['cost']
                for t in range(T))
            for g in range(len(all_parts))
        ), 2),
        'ordering_admin': round(sum(
            sum(int(pulp.value(o[g, t]) or 0) * all_parts[g]['ord_cost']
                for t in range(T))
            for g in range(len(all_parts))
        ), 2),
        'production_setup': round(sum(
            sum(int(pulp.value(y[k, t]) or 0) * products[k].get('setup_cost', 50)
                for t in range(T))
            for k in range(n_products)
        ), 2),
        'production_variable': round(sum(
            sum(int(pulp.value(p[k, t]) or 0) * products[k].get('variable_cost', 0)
                for t in range(T))
            for k in range(n_products)
        ), 2),
        'fixed_overhead': round(fixed_daily * T, 2),
        # v3.6 — milk run inbound consolidation cost (per-product * T periods).
        'milk_run': round(sum(
            float(products[k].get('milk_run_per_period', 0) or 0) * T
            for k in range(n_products)
        ), 2),
    }

    return {
        'status': 'Optimal',
        'total_cost': round(total_cost, 2),
        'cost_breakdown': cost_breakdown,
        'products': product_results,
        'materials': material_results,
        'solve_time': round(solve_time, 2),
        'periods': T,
        'solver': 'CBC',
        # P4 — echo replan context so UI knows the solver honoured the lock.
        'replan_from_period': replan_from_period,
        'actuals_locked': sum(
            1 for k, prod in enumerate(products)
            for t in range((replan_from_period or 0))
            if t < len((prod.get('actuals_override') or []))
            and (prod.get('actuals_override') or [])[t] is not None
        ) if replan_from_period else 0,
    }
