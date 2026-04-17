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

def solve_transport(data):
    t0 = time.time()
    shipments = data.get('shipments', [])
    params = data.get('params', {})
    customs_speed = params.get('customs_clearance', 'normal')
    cust_d = CUSTOMS_DAYS.get(customs_speed, 4)
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
                so_cost = gap * daily_use * (val / max(wt, 1)) * 0.3
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
                    lost_rev = gap_days * daily_use * (val / max(wt, 1))
                    premium = air_opt['base_cost'] - (sea_opt['base_cost'] if sea_opt else 0)
                    justified = premium < lost_rev
                    spike_alert = {
                        'severity':'critical',
                        'message':f"Stock lasts {dos:.0f}d but sea takes {sea_t}d. Stockout in {max(0,dos):.0f}d. Air delivers in {air_t}d.",
                        'air_cost':air_opt['base_cost'],'sea_cost':sea_opt['base_cost'] if sea_opt else 0,
                        'premium':round(premium,2),'stockout_cost_if_sea':round(lost_rev,2),
                        'justified':justified,'decision':'USE AIR' if justified else 'ACCEPT RISK',
                        'time_saved_days':sea_t-air_t,'stock_days':round(dos,1),'sea_days':sea_t,'air_days':air_t,
                    }
                    spike_alerts.append({**spike_alert,'shipment':name})
                    if justified and air_opt: rec = air_opt
            else:
                spike_alert = {'severity':'info','message':f"Spike noted but stock ({dos:.0f}d) covers sea transit ({sea_t}d). Keep sea.",'decision':'KEEP MODE'}

        ship_cost = rec['total_cost'] if rec else 0
        total_cost += ship_cost; total_weight += wt
        if rec:
            mn = rec['mode']
            if mn not in mode_summary: mode_summary[mn] = {'label':rec['label'],'count':0,'cost':0,'weight':0}
            mode_summary[mn]['count'] += 1; mode_summary[mn]['cost'] += ship_cost; mode_summary[mn]['weight'] += wt

        tracking = list(TRACKING.items())[:4] if is_imp else [('CONCOR',TRACKING['concor']),('LDB',TRACKING['ldb'])]
        results.append({'name':name,'origin':orig,'destination':dest,'weight_kg':wt,'volume_cbm':vol,'value':val,
            'deadline_days':deadline,'urgency':urgency,'is_import':is_imp,'days_of_stock':dos if daily_use>0 else None,
            'recommended':rec,'cheapest':cheapest,'fastest':fastest,'all_options':opts[:6],'spike_alert':spike_alert,
            'tracking':[{'name':n,'url':u} for n,u in tracking]})

    # Allocation LP
    alloc = None
    origs = data.get('origins',[]); dests = data.get('destinations',[]); cmat = data.get('cost_matrix',[])
    if origs and dests and cmat:
        prob = pulp.LpProblem("Alloc", pulp.LpMinimize)
        x = {(i,j): pulp.LpVariable(f'x_{i}_{j}',0) for i in range(len(origs)) for j in range(len(dests))}
        prob += pulp.lpSum(cmat[i][j]*x[i,j] for i in range(len(origs)) for j in range(len(dests)))
        for i in range(len(origs)): prob += pulp.lpSum(x[i,j] for j in range(len(dests))) <= origs[i].get('supply',0)
        for j in range(len(dests)): prob += pulp.lpSum(x[i,j] for i in range(len(origs))) >= dests[j].get('demand',0)
        prob.solve(pulp.PULP_CBC_CMD(msg=0,timeLimit=10))
        alloc = {'total_cost':round(pulp.value(prob.objective),2),'allocation':[
            {'from':origs[i].get('name',''),'to':dests[j].get('name',''),'quantity':round(pulp.value(x[i,j]),1),'total_cost':round(pulp.value(x[i,j])*cmat[i][j],2)}
            for i in range(len(origs)) for j in range(len(dests)) if (pulp.value(x[i,j]) or 0) > 0.5]}

    return {'status':'Optimal','total_cost':round(total_cost,2),'total_weight':round(total_weight,1),
        'n_shipments':len(results),'shipments':results,'mode_summary':mode_summary,'spike_alerts':spike_alerts,
        'allocation':alloc,'tracking_portals':TRACKING,'solve_time':round(time.time()-t0,2)}
