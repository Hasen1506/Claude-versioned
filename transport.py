"""
Transport Optimizer v2 — Real transit database, demand sensing override, carrier tracking
"""
import pulp, time, math

TRANSIT_DB = {
    ('Shanghai','Chennai'):{'sea':18,'air':4},('Shanghai','Mumbai'):{'sea':20,'air':4},('Shanghai','JNPT'):{'sea':20,'air':4},
    ('Shenzhen','Chennai'):{'sea':16,'air':3},('Shenzhen','Mumbai'):{'sea':18,'air':3},
    ('Hamburg','Chennai'):{'sea':28,'air':5},('Hamburg','Mumbai'):{'sea':26,'air':5},('Hamburg','JNPT'):{'sea':26,'air':5},
    ('Rotterdam','Chennai'):{'sea':26,'air':5},('Rotterdam','JNPT'):{'sea':24,'air':5},
    ('Busan','Chennai'):{'sea':14,'air':4},('Singapore','Chennai'):{'sea':7,'air':2},('Singapore','Mumbai'):{'sea':10,'air':3},
    ('Dubai','Mumbai'):{'sea':5,'air':2},('Dubai','JNPT'):{'sea':5,'air':2},('Dubai','Chennai'):{'sea':7,'air':3},
    ('Colombo','Chennai'):{'sea':3,'air':1},('Yokohama','Chennai'):{'sea':20,'air':4},
    ('Los Angeles','JNPT'):{'sea':35,'air':6},('New York','JNPT'):{'sea':30,'air':6},
    ('Delhi','Mumbai'):{'road':3,'rail':4},('Delhi','Chennai'):{'road':4,'rail':5},
    ('Pune','Mumbai'):{'road':1,'rail':1},('Pune','Chennai'):{'road':3,'rail':3},
    ('Bangalore','Chennai'):{'road':1,'rail':2},('Kolkata','Chennai'):{'road':4,'rail':5},
}
CUSTOMS_DAYS = {'green_channel':2,'normal':4,'red_channel':7}
TRACKING = {
    'maersk':'https://www.maersk.com/tracking/','msc':'https://www.msc.com/en/track-a-shipment',
    'marine_traffic':'https://www.marinetraffic.com/','vessel_finder':'https://www.vesselfinder.com/',
    'concor':'https://www.concorindia.co.in/track-n-trace','ldb':'https://www.ldb.co.in/',
    'icegate':'https://www.icegate.gov.in/','pcs1x':'https://www.indianpcs.gov.in/',
}
MODE_SPECS = {
    'road_ftl':{'cost_per_kg':1.8,'min_kg':3000,'max_kg':25000,'reliability':0.88,'label':'Road FTL'},
    'road_ltl':{'cost_per_kg':3.5,'min_kg':30,'max_kg':5000,'reliability':0.85,'label':'Road LTL'},
    'rail':{'cost_per_kg':1.2,'min_kg':5000,'max_kg':60000,'reliability':0.82,'label':'Rail (CONCOR)'},
    'sea_lcl':{'cost_per_kg':0.6,'min_kg':50,'max_kg':14000,'reliability':0.87,'label':'Sea LCL'},
    'sea_fcl_20':{'cost_per_kg':0.35,'min_kg':5000,'max_kg':21700,'reliability':0.90,'label':'Sea FCL 20ft'},
    'sea_fcl_40':{'cost_per_kg':0.25,'min_kg':10000,'max_kg':26700,'reliability':0.90,'label':'Sea FCL 40ft'},
    'sea_fcl_40hc':{'cost_per_kg':0.28,'min_kg':8000,'max_kg':26500,'reliability':0.90,'label':'Sea FCL 40HC'},
    'air_standard':{'cost_per_kg':15.0,'min_kg':1,'max_kg':5000,'reliability':0.96,'label':'Air Standard'},
    'air_express':{'cost_per_kg':35.0,'min_kg':0.5,'max_kg':500,'reliability':0.99,'label':'Air Express'},
}

def _lookup_transit(origin, dest, mode_type):
    key = (origin, dest)
    rev = (dest, origin)
    db = TRANSIT_DB.get(key) or TRANSIT_DB.get(rev)
    if db:
        for k in ['sea','air','road','rail']:
            if k in mode_type and k in db: return db[k]
    if 'air' in mode_type: return 4
    if 'sea' in mode_type: return 22
    if 'rail' in mode_type: return 5
    return 3

# ── V5-4 · MULTI-MODE SPLIT ──────────────────────────────────────────────────
# The per-shipment pick above is all-or-nothing: one mode carries the whole load.
# Two binds where that is wrong:
#   · CAPACITY — a shipment heavier than every mode's max_kg gets rec=None and
#     silently contributes ₹0 to the plan (an unserveable lane reported as free);
#     even below that, the cheap bulk mode may cap out while a mixed plan
#     (n full loads + a remainder leg) is cheaper than the one mode that fits.
#   · DEADLINE — a demand spike forces the ENTIRE shipment to air when only the
#     consumption bridge (days until the cheap slow mode lands) needs to fly.
# Gated by params.mode_split (default OFF ⇒ output byte-identical to baseline).

def _mode_family(mn):
    return 'air' if 'air' in mn else ('sea' if 'sea' in mn else ('rail' if 'rail' in mn else 'road'))

def _split_families(orig, dest, is_imp):
    # Lane sanity for SPLIT legs only: when the lane is in the transit DB, split
    # across the families that physically serve it (+air, always bookable);
    # otherwise an import lane splits across sea/air, a domestic one road/rail/air.
    # (The single-mode ranking keeps its pre-existing deadline-only filter —
    # V5-4 does not change baseline picks.)
    db = TRANSIT_DB.get((orig, dest)) or TRANSIT_DB.get((dest, orig))
    if db:
        return tuple(set(db.keys()) | {'air'})
    return ('sea', 'air') if is_imp else ('road', 'rail', 'air')

def _split_leg(mn, mode, leg_kg, leg_vol, leg_val, orig, dest, is_imp, cust_d):
    """Price ONE leg with the same formula the single-mode ranking uses
    (chargeable weight + reliability surcharge) so split-vs-single compares
    apples to apples."""
    transit = _lookup_transit(orig, dest, mn)
    total_t = transit + (cust_d if is_imp else 0)
    vol_wt = leg_vol * 167 if 'air' in mn else leg_vol * 333
    chg = max(leg_kg, vol_wt)
    base = chg * mode['cost_per_kg']
    rel = (1 - mode['reliability']) * leg_val * 0.01
    return {'mode': mn, 'label': mode['label'], 'weight_kg': round(leg_kg, 1),
            'base_cost': round(base, 2), 'transit_days': transit, 'total_days': total_t,
            'cost': base + rel}

def _capacity_split(wt, vol, val, deadline, urgency, orig, dest, is_imp, cust_d, modes):
    """Capacity-bind split: bin-pack full loads of a bulk mode that can't take the
    shipment whole, remainder on the cheapest mode it fits. Returns the cheapest
    multi-leg plan or None."""
    fam = _split_families(orig, dest, is_imp)
    best = None
    for mn, mode in modes.items():
        if _mode_family(mn) not in fam:
            continue
        cap = mode['max_kg']
        if wt <= cap:                       # this mode could take it whole — no bind here
            continue
        transit = _lookup_transit(orig, dest, mn)
        if transit + (cust_d if is_imp else 0) > deadline and urgency != 'critical':
            continue
        n_full = int(wt // cap)
        rem = wt - n_full * cap
        legs = [_split_leg(mn, mode, cap, vol * cap / wt, val * cap / wt,
                           orig, dest, is_imp, cust_d) for _ in range(n_full)]
        if rem > 1e-6:
            rem_opts = []
            for rn, rm in modes.items():
                if _mode_family(rn) not in fam:
                    continue
                if rem < rm['min_kg'] or rem > rm['max_kg']:
                    continue
                rt = _lookup_transit(orig, dest, rn)
                if rt + (cust_d if is_imp else 0) > deadline and urgency != 'critical':
                    continue
                rem_opts.append(_split_leg(rn, rm, rem, vol * rem / wt, val * rem / wt,
                                           orig, dest, is_imp, cust_d))
            if not rem_opts:
                continue                    # remainder unplaceable alongside this bulk pick
            legs.append(min(rem_opts, key=lambda o: o['cost']))
        total = sum(l['cost'] for l in legs)
        if best is None or total < best['cost']:
            best = {'cost': total, 'legs': legs, 'reason': 'capacity'}
    return best

def _deadline_split(wt, vol, val, opts, modes, dos, daily_use, val_per_kg, risk,
                    buffer_pct, orig, dest, is_imp, cust_d):
    """Deadline/stockout split: fly only the consumption BRIDGE (slow-lane transit
    minus days-of-stock, plus a safety buffer) on the fast lane; the bulk rides the
    cheap slow lane. Cost carries any residual stockout exposure the bridge can't
    cover, priced with the same risk factor as the single-mode ranking."""
    if not opts or daily_use <= 0:
        return None
    fam = _split_families(orig, dest, is_imp)
    cands = [o for o in opts if _mode_family(o['mode']) in fam]
    if not cands:
        return None
    slow = min(cands, key=lambda o: o['base_cost'])
    if slow['total_days'] <= dos:
        return None                          # cheap lane lands before stockout — no bind
    fasts = [o for o in cands if o['total_days'] <= dos and o['mode'] != slow['mode']]
    if not fasts:
        return None                          # nothing arrives before the stockout
    fast = min(fasts, key=lambda o: o['base_cost'])
    fm, sm = modes[fast['mode']], modes[slow['mode']]
    need_kg = (slow['total_days'] - dos) * daily_use * (1 + buffer_pct / 100.0)
    bridge = max(fm['min_kg'], min(need_kg, fm['max_kg'], wt))
    rem = wt - bridge
    if rem <= 0 or rem < sm['min_kg'] or rem > sm['max_kg']:
        return None                          # remainder doesn't ride the slow lane whole
    legs = [_split_leg(fast['mode'], fm, bridge, vol * bridge / wt, val * bridge / wt,
                       orig, dest, is_imp, cust_d),
            _split_leg(slow['mode'], sm, rem, vol * rem / wt, val * rem / wt,
                       orig, dest, is_imp, cust_d)]
    covered = bridge / daily_use             # days the bridge actually buys (un-buffered)
    residual_gap = max(0.0, (slow['total_days'] - dos) - covered)
    resid = residual_gap * daily_use * val_per_kg * risk
    return {'cost': sum(l['cost'] for l in legs) + resid, 'legs': legs, 'reason': 'deadline',
            'bridge_kg': round(bridge, 1), 'residual_stockout_cost': round(resid, 2)}

def _split_public(split, rec):
    """Wire format for a recommended split: legs grouped per mode (n identical full
    loads collapse to one row with loads=n), plus the saving vs the single-mode pick
    (None when no single mode could serve the shipment at all)."""
    if not split:
        return None
    groups = {}
    for l in split['legs']:
        g = groups.setdefault(l['mode'], {'mode': l['mode'], 'label': l['label'], 'loads': 0,
                                          'weight_kg': 0.0, 'base_cost': 0.0,
                                          'transit_days': l['transit_days'],
                                          'total_days': l['total_days']})
        g['loads'] += 1
        g['weight_kg'] += l['weight_kg']
        g['base_cost'] += l['base_cost']
    legs = sorted(groups.values(), key=lambda g: -g['weight_kg'])
    for g in legs:
        g['weight_kg'] = round(g['weight_kg'], 1)
        g['base_cost'] = round(g['base_cost'], 2)
    single = rec['total_cost'] if rec else None
    total = round(split['cost'], 2)
    out = {'reason': split['reason'], 'legs': legs, 'total_cost': total,
           'single_cost': single,
           'saving': round(single - total, 2) if single is not None else None,
           'recommended': True}
    for k in ('bridge_kg', 'residual_stockout_cost'):
        if k in split:
            out[k] = split[k]
    return out


def consolidate_shipments(shipments, modes, params=None):
    """GAP-9 — consolidation across shipments sharing a lane.

    The per-shipment mode choice is greedy: each shipment independently picks its
    cheapest mode, so many small LTL/LCL parcels on the SAME origin→dest lane never
    combine into a full truck/container even when that is far cheaper. This pass groups
    shipments by lane, bin-packs the combined weight into full loads, and compares the
    all-individual cost against the consolidated cost, recommending the cheaper.

    Returns a list of per-lane consolidation analyses (only lanes with ≥2 shipments).
    """
    params = params or {}
    # Pick the LTL (small-parcel) and FTL (full-load) rate pair by lane type.
    road_ltl = modes.get('road_ltl', MODE_SPECS['road_ltl'])
    road_ftl = modes.get('road_ftl', MODE_SPECS['road_ftl'])
    sea_lcl = modes.get('sea_lcl', MODE_SPECS['sea_lcl'])
    sea_fcl = modes.get('sea_fcl_40', MODE_SPECS['sea_fcl_40'])

    lanes = {}
    for s in shipments:
        orig = s.get('origin', 'Domestic')
        dest = s.get('destination', 'Factory')
        is_imp = s.get('is_import', orig not in ['Domestic', 'Factory', 'Warehouse'])
        lanes.setdefault((orig, dest, is_imp), []).append(s)

    out = []
    for (orig, dest, is_imp), ships in lanes.items():
        if len(ships) < 2:
            continue
        W = sum(s.get('weight_kg', 0) for s in ships)
        if is_imp:
            ltl, ftl, full_label, part_label = sea_lcl, sea_fcl, 'FCL 40ft', 'LCL'
        else:
            ltl, ftl, full_label, part_label = road_ltl, road_ftl, 'FTL', 'LTL'
        cap = ftl['max_kg']
        truck_cost = cap * ftl['cost_per_kg']        # a booked full load is priced at its capacity
        ltl_rate = ltl['cost_per_kg']

        # Option A — everything as individual small loads.
        cost_individual = W * ltl_rate
        # Option B — bin-pack into full loads; the remainder takes whichever is cheaper.
        n_full = int(W // cap)
        rem = W - n_full * cap
        rem_cost = min(rem * ltl_rate, truck_cost) if rem > 0 else 0.0
        cost_consolidated = n_full * truck_cost + rem_cost
        saving = cost_individual - cost_consolidated

        out.append({
            'lane': f'{orig} → {dest}',
            'is_import': is_imp,
            'n_shipments': len(ships),
            'combined_weight_kg': round(W, 1),
            'individual_mode': part_label,
            'consolidated_mode': full_label,
            'full_loads': n_full,
            'remainder_kg': round(rem, 1),
            'cost_individual': round(cost_individual, 2),
            'cost_consolidated': round(cost_consolidated, 2),
            'saving': round(saving, 2),
            'recommend_consolidate': bool(saving > 0),
            'utilization_pct': round((W / (cap * max(n_full + (1 if rem > 0 else 0), 1))) * 100, 1),
        })
    out.sort(key=lambda r: r['saving'], reverse=True)
    return out


def solve_transport(data):
    t0 = time.time()
    shipments = data.get('shipments', [])
    params = data.get('params', {})
    customs_speed = params.get('customs_clearance', 'normal')
    cust_d = CUSTOMS_DAYS.get(customs_speed, 4)
    # (MF-10) ONE price for a stockout event. Both the mode-ranking penalty and the air-vs-sea
    # spike decision now risk-adjust the same gross lost-revenue figure by this factor (≈ P(stockout)),
    # instead of the old split where ranking used a 0.3 haircut and the decision used full lost
    # revenue — the same event priced two ways. Tunable via params.stockout_risk_factor.
    stockout_risk_factor = float(params.get('stockout_risk_factor', 0.3) or 0.3)
    # V5-4 — multi-mode split (capacity / deadline binds). OFF by default ⇒ the
    # whole block below is skipped and the output is byte-identical to baseline.
    split_enabled = bool(params.get('mode_split'))
    split_buffer_pct = float(params.get('split_bridge_buffer_pct', 15) or 15)
    modes = {k:{**v} for k,v in MODE_SPECS.items()}
    for mn, ov in params.get('mode_overrides', {}).items():
        if mn in modes: modes[mn].update(ov)

    results = []; total_cost = 0; total_weight = 0
    mode_summary = {}; spike_alerts = []

    for ship in shipments:
        wt = ship.get('weight_kg',100); vol = ship.get('volume_cbm',1)
        val = ship.get('value',10000); deadline = ship.get('deadline_days',30)
        urgency = ship.get('urgency','normal')
        orig = ship.get('origin','Domestic'); dest = ship.get('destination','Factory')
        name = ship.get('name','Shipment')
        is_imp = ship.get('is_import', orig not in ['Domestic','Factory','Warehouse'])
        # Demand sensing
        spike = ship.get('demand_spike', False)
        spike_qty = ship.get('spike_qty', 0)
        cur_stock = ship.get('current_stock', 0)
        daily_use = ship.get('daily_consumption', 0)
        dos = round(cur_stock / max(daily_use, 0.01), 1) if daily_use > 0 else 999

        opts = []
        for mn, mode in modes.items():
            if wt < mode['min_kg'] or wt > mode['max_kg']: continue
            transit = _lookup_transit(orig, dest, mn)
            total_t = transit + (cust_d if is_imp else 0)
            if total_t > deadline and urgency != 'critical': continue

            vol_wt = vol * 167 if 'air' in mn else vol * 333
            chg = max(wt, vol_wt)
            base = chg * mode['cost_per_kg']
            # Stockout cost
            so_cost = 0
            if daily_use > 0 and spike:
                gap = max(0, total_t - dos)
                so_cost = gap * daily_use * (val / max(wt, 1)) * stockout_risk_factor
            rel_cost = (1 - mode['reliability']) * val * 0.01
            total_c = base + so_cost + rel_cost
            opts.append({'mode':mn,'label':mode['label'],'base_cost':round(base,2),'stockout_cost':round(so_cost,2),
                'total_cost':round(total_c,2),'transit_days':transit,'customs_days':cust_d if is_imp else 0,
                'total_days':total_t,'buffer_days':deadline-total_t,'reliability':mode['reliability'],
                'chargeable_weight':round(chg,1)})
        opts.sort(key=lambda x: x['total_cost'])
        rec = opts[0] if opts else None
        cheapest = min(opts, key=lambda x: x['base_cost']) if opts else None
        fastest = min(opts, key=lambda x: x['total_days']) if opts else None

        # ─── DEMAND SENSING → MODE OVERRIDE ───
        spike_alert = None
        if spike and daily_use > 0:
            sea_t = _lookup_transit(orig, dest, 'sea') + cust_d
            air_t = _lookup_transit(orig, dest, 'air') + cust_d
            if dos < sea_t:
                # Sea WON'T arrive before stockout
                air_opt = next((m for m in opts if 'air' in m['mode']), None)
                sea_opt = next((m for m in opts if 'sea' in m['mode']), None)
                if air_opt:
                    gap_days = sea_t - dos
                    # (MF-10) Risk-adjusted expected stockout cost — same basis & factor as the
                    # mode-ranking penalty above, so one event has one price for both the ranking
                    # and the go/no-go. Compare the CERTAIN air premium against the EXPECTED loss.
                    lost_rev = gap_days * daily_use * (val / max(wt, 1)) * stockout_risk_factor
                    premium = air_opt['base_cost'] - (sea_opt['base_cost'] if sea_opt else 0)
                    justified = premium < lost_rev
                    spike_alert = {
                        'severity':'critical',
                        'message':f"Stock lasts {dos:.0f}d but sea takes {sea_t}d. Stockout in {max(0,dos):.0f}d. Air delivers in {air_t}d.",
                        'air_cost':air_opt['base_cost'],'sea_cost':sea_opt['base_cost'] if sea_opt else 0,
                        'premium':round(premium,2),'stockout_cost_if_sea':round(lost_rev,2),
                        'risk_factor':stockout_risk_factor,
                        'justified':justified,'decision':'USE AIR' if justified else 'ACCEPT RISK',
                        'time_saved_days':sea_t-air_t,'stock_days':round(dos,1),'sea_days':sea_t,'air_days':air_t,
                    }
                    spike_alerts.append({**spike_alert,'shipment':name})
                    if justified and air_opt: rec = air_opt
            else:
                spike_alert = {'severity':'info','message':f"Spike noted but stock ({dos:.0f}d) covers sea transit ({sea_t}d). Keep sea.",'decision':'KEEP MODE'}

        # ─── V5-4 · MODE SPLIT (capacity / deadline binds) ───
        chosen_split = None
        if split_enabled:
            cap_split = _capacity_split(wt, vol, val, deadline, urgency, orig, dest,
                                        is_imp, cust_d, modes)
            if cap_split and (rec is None or cap_split['cost'] < rec['total_cost'] - 1e-9):
                chosen_split = cap_split
            if spike and daily_use > 0:
                dl_split = _deadline_split(wt, vol, val, opts, modes, dos, daily_use,
                                           val / max(wt, 1), stockout_risk_factor,
                                           split_buffer_pct, orig, dest, is_imp, cust_d)
                # rec may already be the full-air spike override here — its total_cost
                # carries that mode's own stockout penalty, so this is apples-to-apples.
                if dl_split and (chosen_split is None or dl_split['cost'] < chosen_split['cost']) \
                        and (rec is None or dl_split['cost'] < rec['total_cost'] - 1e-9):
                    chosen_split = dl_split
                    if spike_alert:
                        spike_alert['decision'] = 'SPLIT FAST+SLOW'
                        spike_alert['split_cost'] = round(dl_split['cost'], 2)
                        if spike_alerts and spike_alerts[-1].get('shipment') == name:
                            spike_alerts[-1].update({'decision': 'SPLIT FAST+SLOW',
                                                     'split_cost': round(dl_split['cost'], 2)})

        ship_cost = chosen_split['cost'] if chosen_split else (rec['total_cost'] if rec else 0)
        total_cost += ship_cost; total_weight += wt
        if chosen_split:
            for l in chosen_split['legs']:
                mn = l['mode']
                if mn not in mode_summary: mode_summary[mn] = {'label':l['label'],'count':0,'cost':0,'weight':0}
                mode_summary[mn]['count'] += 1; mode_summary[mn]['cost'] += l['cost']; mode_summary[mn]['weight'] += l['weight_kg']
        elif rec:
            mn = rec['mode']
            if mn not in mode_summary: mode_summary[mn] = {'label':rec['label'],'count':0,'cost':0,'weight':0}
            mode_summary[mn]['count'] += 1; mode_summary[mn]['cost'] += ship_cost; mode_summary[mn]['weight'] += wt

        tracking = list(TRACKING.items())[:4] if is_imp else [('CONCOR',TRACKING['concor']),('LDB',TRACKING['ldb'])]
        entry = {'name':name,'origin':orig,'destination':dest,'weight_kg':wt,'volume_cbm':vol,'value':val,
            'deadline_days':deadline,'urgency':urgency,'is_import':is_imp,'days_of_stock':dos if daily_use>0 else None,
            'recommended':rec,'cheapest':cheapest,'fastest':fastest,'all_options':opts[:6],'spike_alert':spike_alert,
            'tracking':[{'name':n,'url':u} for n,u in tracking]}
        if split_enabled:
            entry['split'] = _split_public(chosen_split, rec)
        results.append(entry)

    # Allocation LP
    alloc = None
    origs = data.get('origins',[]); dests = data.get('destinations',[]); cmat = data.get('cost_matrix',[])
    if origs and dests and cmat:
        prob = pulp.LpProblem("Alloc", pulp.LpMinimize)
        x = {(i,j): pulp.LpVariable(f'x_{i}_{j}',0) for i in range(len(origs)) for j in range(len(dests))}
        prob += pulp.lpSum(cmat[i][j]*x[i,j] for i in range(len(origs)) for j in range(len(dests)))
        for i in range(len(origs)): prob += pulp.lpSum(x[i,j] for j in range(len(dests))) <= origs[i].get('supply',0)
        for j in range(len(dests)): prob += pulp.lpSum(x[i,j] for i in range(len(origs))) >= dests[j].get('demand',0)
        status = prob.solve(pulp.PULP_CBC_CMD(msg=0,timeLimit=10))
        # (MF-9) Guard the status before reading values. With demand >= and supply <=, if
        # Σsupply < Σdemand the LP is INFEASIBLE and pulp.value() returns None → round(None) threw a
        # bare 500. Report the real status (like the other solvers) instead of crashing.
        if pulp.LpStatus[status] != 'Optimal':
            total_supply = sum(o.get('supply', 0) for o in origs)
            total_demand_alloc = sum(d.get('demand', 0) for d in dests)
            alloc = {'status': pulp.LpStatus[status], 'allocation': [],
                     'error': f"Allocation {pulp.LpStatus[status]} — supply {total_supply} vs demand {total_demand_alloc}"
                              f"{' (supply < demand)' if total_supply < total_demand_alloc else ''}."}
        else:
            alloc = {'status':'Optimal','total_cost':round(pulp.value(prob.objective),2),'allocation':[
                {'from':origs[i].get('name',''),'to':dests[j].get('name',''),'quantity':round(pulp.value(x[i,j]),1),'total_cost':round(pulp.value(x[i,j])*cmat[i][j],2)}
                for i in range(len(origs)) for j in range(len(dests)) if (pulp.value(x[i,j]) or 0) > 0.5]}

    # (MF-31) The mode-choice heuristic above always produces a result, but the allocation LP is the
    # only real optimization here — and it can come back infeasible/unbounded. Previously the outer
    # return hardcoded 'Optimal' regardless, so an over-constrained allocation was reported as a clean
    # solve. Degrade the top-level status to the allocation's real status (and surface its error) when
    # an allocation was attempted and did not solve, mirroring the other four solvers' contract.
    # GAP-9 — consolidation pass across shipments sharing a lane (LTL→FTL / LCL→FCL bin-packing).
    consolidation = consolidate_shipments(shipments, modes, params)
    consolidation_saving = round(sum(c['saving'] for c in consolidation if c['recommend_consolidate']), 2)

    out_status = 'Optimal'
    out = {'total_cost':round(total_cost,2),'total_weight':round(total_weight,1),
        'n_shipments':len(results),'shipments':results,'mode_summary':mode_summary,'spike_alerts':spike_alerts,
        'allocation':alloc,'consolidation':consolidation,'consolidation_saving':consolidation_saving,
        'tracking_portals':TRACKING,'solve_time':round(time.time()-t0,2)}
    if split_enabled:
        # V5-4 — only present when the toggle is ON (off ⇒ byte-identical baseline).
        _splits = [s['split'] for s in results if s.get('split')]
        out['mode_split_active'] = True
        out['n_splits'] = len(_splits)
        out['split_saving'] = round(sum((sp['saving'] or 0) for sp in _splits
                                        if sp.get('saving') is not None and sp['saving'] > 0), 2)
    if alloc and alloc.get('status') and alloc['status'] != 'Optimal':
        out_status = alloc['status']
        out['error'] = alloc.get('error', f"Allocation {alloc['status']}.")
    out['status'] = out_status
    return out
