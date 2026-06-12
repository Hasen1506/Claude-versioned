// ════════════════════════════════════════════════════════════════════════
// scenarios.jsx — Risk & Scenarios (AnalysisTab). Sub-tabbed: Risk · Loop ·
// Cost · Explore.
//
// W6 (Risk → L1/L2) wires the REAL stochastic solvers on the COMMITTED plan:
//   R-1  Monte Carlo (/api/solve/montecarlo) replays the committed production
//        schedule against demand+cost shocks → cost dist, VaR/CVaR, fill dist.
//   R-2  CVaR robust stock (/api/solve/cvar, Rockafellar–Uryasev) → "hold N more"
//        finished units + the robustness premium over the expected-value plan.
//   R-3  MC lead-time honesty — fixed in montecarlo.py (no fabricated LT draw).
//   R-4  Control Tower + What-If from REAL signals (stale solves, the event log,
//        the live MC tail) — no hardcoded alerts; What-If → /api/whatif (advisory).
// W7 (the loop → L3) adds the "Loop" subtab: runFullLoop() chains
//   procurement→aggregate→production→line-capital→risk on ONE dataset.
// ════════════════════════════════════════════════════════════════════════
// R13 · Scenarios is now the LAB — branch/compare/what-if + risk/stress + the loop.
// The monitoring half (S&OP cockpit board, D8 exception inbox, D2 value ledger) moved
// to Home, which is where you check "is the plan current & healthy?". Here you EXPLORE
// alternatives and STRESS them. Default opens on the what-if branches.
function StageScenarios({ onNav }) {
  const [sub, setSub] = useState('scenarios');
  const tabs = M.scenarioSubtabs.map(t=>({ id:t.id, n:t.n, label:t.label, count:t.count }));
  return (
    <div>
      <StageHeader n="11" title="Scenario & Risk Lab" kicker="Branch · compare on solved KPIs · what-if re-solve · Monte Carlo + resilience stress · end-to-end loop"
        right={<ReportExport/>}/>
      {/* V3-14 — ① DECIDE strip (Part 3.2): solve-gated, from the CACHED Monte-Carlo only */}
      <div style={{padding:'8px 18px', borderBottom:'2px solid '+C.line, background:C.paper}}>
        <ScenariosDecideStrip/>
      </div>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='scenarios' && <ScnScenarios onNav={onNav}/>}
        {sub==='risk'      && <ScnRisk onNav={onNav}/>}
        {sub==='loop'      && <ScnLoop onNav={onNav}/>}
        {sub==='cost'      && <ScnCost/>}
        {sub==='explore'   && <ScnExplore/>}
      </div>
    </div>
  );
}

// ── derive live control-tower alerts from REAL app state (R-4) ──────────────
// No hardcoded alert list: each alert is a fact about the current model — a
// stale solve, a logged trigger/replan event, or a live MC tail signal.
// Batch 4 — friendly name for the ROOT source that staled a solve (markStale records
// it as solves[k].staleSrc). Turns "inputs changed" into "stale because you edited X".
const STALE_SRC_LABEL = {
  demand:'committed demand', network:'the network (nodes / lanes / on-hand)',
  productCosts:'product costs', config:'a setup / config value', planning:'the planning calendar',
  bom:'the BOM', sourcing:'sourcing terms', prodArch:'the production line / stage setup',
  procurement:'the procurement solve re-ran', aggregate:'the S&OP aggregate re-ran',
  production:'the production schedule re-ran', linecap:'the line-capital solve re-ran',
  montecarlo:'the Monte-Carlo run', meionet:'the inventory-pooling solve re-ran',
};
function liveAlerts(solves, events, mc){
  const out = [];
  const STAGE = { procurement:'Sourcing', production:'Production', aggregate:'Plan',
                  montecarlo:'Risk', linecap:'Plan', cvar:'Sourcing', meio:'Sourcing' };
  Object.entries(solves||{}).forEach(([k,v])=>{
    if(v && v.stale){ const why = v.staleSrc ? (STALE_SRC_LABEL[v.staleSrc]||v.staleSrc) : null;
      out.push({ sev:'M', area:'Stale',
        msg:`${k} plan is stale — ${why?`because you changed ${why}`:'inputs changed since last solve'}`,
        go:STAGE[k], t: v.staleAt?_ago(v.staleAt):'now' }); }
  });
  (events||[]).slice(-4).reverse().forEach(e=>{
    if(e.type==='trigger') out.push({ sev:'H', area:'Demand', msg:`Forecast review trigger fired on ${e.target||'an item'}`, go:'demand', t:_ago(e.ts) });
    else if(e.type==='replan') out.push({ sev:'M', area:'Supply', msg:`Re-plan committed on ${e.target||'demand'}`, go:'sourcing', t:_ago(e.ts) });
  });
  if(mc){
    if(mc.avg_fill!=null && mc.avg_fill < 95) out.push({ sev:'H', area:'Service', msg:`MC mean fill ${mc.avg_fill}% — below 95% target on the committed plan`, go:'sourcing', t:'live' });
    if(mc.fragility!=null && mc.fragility > 1.2) out.push({ sev:'M', area:'Cost', msg:`Cost fragility ${mc.fragility}× (VaR95/mean) — fat right tail`, go:null, t:'live' });
  }
  return out;
}
function _ago(ts){ try{ const s=Math.round((Date.now()-new Date(ts))/60000); return s<1?'just now':s<60?`${s}m ago`:`${Math.round(s/60)}h ago`; }catch(e){ return ''; } }

// ── D8 · EXCEPTION COCKPIT — the unified "what needs my attention" inbox ───────
// One ranked list of EVERY open exception, each a real fact about live state:
//   · STALE   — a solve whose inputs changed (recompute DAG)
//   · SENSED  — a forecast-quality breach / auto-trigger from the event log
//   · RISK    — a Monte-Carlo tail signal on the COMMITTED plan
//   · VALUE   — ₹ a solve IDENTIFIED that no decision has yet adopted (the miss)
// Nothing invented: stale flags from solves[], triggers from events[], risk from
// the cached montecarlo, value-misses from the cached pooling/linecap solves cross-
// referenced against the acceptance events. This is the planner-productivity moat —
// exception-driven, not dashboard-driven. Reuses liveAlerts for stale/trigger/risk.
function exceptionInbox(solves, events, sr){
  const out = liveAlerts(solves, events, sr ? (sr.montecarlo ? sr.montecarlo.result : null) : null)
    .map(a=>({ sev:a.sev, cat:a.area==='Stale'?'STALE':a.area==='Demand'?'SENSED':(a.area==='Service'||a.area==='Cost')?'RISK':'OTHER',
               msg:a.msg, go:a.go, t:a.t }));
  // sensed: recent auto-triggers from BreachFlagger (forecast out of control)
  (events||[]).slice(-6).reverse().forEach(e=>{
    if(e.type==='auto_trigger') out.push({ sev:'H', cat:'SENSED',
      msg:`Forecast out of control on ${e.target||'an item'}${e.detail&&e.detail.breaches?` (${e.detail.breaches.join(', ')})`:''} — downstream auto-flagged stale`, go:'demand', t:_ago(e.ts) });
  });
  // VALUE misses — ₹ a solve found that no decision has adopted yet
  const mn = sr && sr.meionet ? sr.meionet.result : null;
  const lc = sr && sr.linecap ? sr.linecap.result : null;
  const adopted = (events||[]).filter(e=>['scenario_apply','scenario_merge','scenario_eva_prune','scenario_merge_fields','rec_apply'].includes(e.type)).length;
  if(mn){
    const div = mn.total_annual_dividend;
    if(div!=null && div>0 && adopted===0) out.push({ sev:'M', cat:'VALUE',
      msg:`Risk pooling identified ₹${_N(div)}/yr of freed safety-stock holding — no recommendation adopted yet`, go:'sourcing', t:'open' });
  }
  if(lc && lc.lines){
    const bind = lc.lines.filter(x=>x.binding).length;
    const shadowMax = Math.max(0,...lc.lines.map(x=>+x.shadow_price||0));
    if(bind>0 && shadowMax>0) out.push({ sev:'M', cat:'VALUE',
      msg:`${bind} line${bind>1?'s':''} binding — relieving capacity is worth ₹${Math.round(shadowMax)}/unit, no expansion decision logged`, go:'production', t:'open' });
  }
  // V2-3 PROFITABILITY GATE — the aggregate LP meets demand at min COST (margin is not in
  // its objective), so it will happily schedule a value-destroying SKU; the profit-mix LP is
  // where that SKU gets dropped, but nothing forces S&OP to consult it. This gate is the
  // forcing function: cross the COMMITTED production schedule (what we will build) against
  // the cached profit-mix solve (what is worth building) and raise an exception on conflict.
  const pm = sr && sr.profitmix ? sr.profitmix.result : null;
  const pr2 = sr && sr.production ? sr.production.result : null;
  if(pm && Array.isArray(pm.products) && pr2 && Array.isArray(pr2.gantt)){
    const built = {};                       // sku → committed units across the schedule
    pr2.gantt.forEach(g=>{ built[g.product] = (built[g.product]||0) + (+g.quantity||0); });
    pm.products.forEach(p=>{
      const planned = built[p.name] || 0;
      if(planned < 0.5) return;             // schedule doesn't build it — no conflict
      if((+p.quantity||0) < 0.01){
        const rc = (pm.reduced_costs||[]).find(r=>r.variable===p.name);
        out.push({ sev:'H', cat:'PROFIT',
          msg:`Profitability gate: the schedule builds ${Math.round(planned)}u of ${p.name} but the profit-mix LP DROPS it${rc&&rc.reduced_cost?` (margin must rise ₹${Math.abs(Math.round(rc.reduced_cost))}/u to enter the mix)`:''} — demand is a promise, not an obligation`,
          go:'console', t:'open' });
      } else if((+p.margin_per_unit||0) < 0){
        out.push({ sev:'H', cat:'PROFIT',
          msg:`Profitability gate: ${p.name} is built (${Math.round(planned)}u scheduled) at a NEGATIVE margin of ₹${Math.abs(p.margin_per_unit)}/u — a demand floor forces a value-destroying build`,
          go:'console', t:'open' });
      }
    });
  }
  const rank = { H:0, M:1, L:2 };
  out.sort((a,b)=>(rank[a.sev]??3)-(rank[b.sev]??3));
  return out;
}
const _EXC_CAT = { STALE:{c:'y', icon:'♻'}, SENSED:{c:'k', icon:'📡'}, RISK:{c:'k', icon:'🎲'}, VALUE:{c:'g', icon:'₹'}, PROFIT:{c:'k', icon:'⛔'}, OTHER:{c:'w', icon:'•'} };
function ExceptionCockpit({ onNav }){
  const { state:solves } = useStore(s=>s.solves||{});
  const { state:sr }     = useStore(s=>s.solveResults||{});
  const { events } = useEvents();
  const items = exceptionInbox(solves, events, sr);
  const hi = items.filter(i=>i.sev==='H').length;
  const byCat = items.reduce((m,i)=>{ m[i.cat]=(m[i.cat]||0)+1; return m; }, {});
  return (
    <Card icon={items.length?(hi?'🚨':'📥'):'✅'} title="Exception Cockpit — what needs my attention" span={2}
      badge={items.length?`${items.length} open${hi?` · ${hi} high`:''}`:'all clear'} badgeTone={items.length?(hi?'k':'y'):'g'}
      right={<Provenance kind="derived" note="solves · events · cached solves"/>}
      info={{ what:'One ranked inbox of every open exception — stale solves, forecast breaches, risk-tail signals, and ₹ a solve identified that no decision has adopted. Each item is a live fact, click to act on it.', flows:'Exception-driven planning — work the list, not the dashboard.' }}
      dev={{ comp:'ExceptionCockpit (D8)', props:'exceptionInbox(solves,events,solveResults)' }}>
      {items.length>0 ? (
        <React.Fragment>
          <div style={{display:'flex', gap:8, flexWrap:'wrap', marginBottom:10}}>
            {Object.entries(byCat).map(([k,n])=>(
              <div key={k} style={{display:'flex', alignItems:'center', gap:5, border:`2px solid ${C.line}`, padding:'3px 9px', fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>
                <span>{(_EXC_CAT[k]||_EXC_CAT.OTHER).icon}</span><span style={{fontWeight:700}}>{n}</span><span style={{color:C.tx3}}>{k.toLowerCase()}</span>
              </div>
            ))}
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:5}}>
            {items.map((it,i)=>{ const cat=_EXC_CAT[it.cat]||_EXC_CAT.OTHER;
              return (
                <div key={i} style={{display:'flex', alignItems:'center', gap:9, padding:'7px 10px', border:`2px solid ${C.line}`,
                  borderLeft:`5px solid ${it.sev==='H'?C.dg:it.sev==='M'?C.a4:C.line2}`, background:C.paper}}>
                  <Tag c={cat.c}>{it.cat}</Tag>
                  <span style={{flex:1, fontSize:11, color:C.tx}}>{it.msg}</span>
                  <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{it.t||''}</span>
                  {it.go && <Btn kind="ghost" sm onClick={()=>onNav&&onNav(it.go)}>open →</Btn>}
                </div>
              );
            })}
          </div>
          <Reading tone={hi?C.dg:C.a4}
            formula={`${items.length} open · ${byCat.STALE||0} stale · ${byCat.SENSED||0} sensed · ${byCat.RISK||0} risk · ${byCat.VALUE||0} value · ${byCat.PROFIT||0} profit`}
            soWhat={hi
              ? `${hi} high-severity exception(s) need action now — a forecast is out of control, the committed plan misses its service target, or the schedule builds a SKU the profit-mix LP rejects. Work the red items first.`
              : 'Open exceptions are advisory — stale solves to refresh and ₹ a solve found but no decision has banked. Nothing is breaching, but there is value on the table.'}/>
        </React.Fragment>
      ) : (
        <div style={{padding:'12px 14px', border:`2px dashed ${C.line2}`, fontFamily:F.mono, fontSize:11, color:C.tx3, lineHeight:1.5}}>
          ✅ Nothing needs your attention — every solve is fresh, the forecast is in control, the committed plan holds its service target, and no identified ₹ is sitting unadopted. Re-plan or change an input and any new exception surfaces here.
        </div>
      )}
    </Card>
  );
}

// ── CVaR-plan payload (R-2) — portfolio finished-buffer newsvendor ──────────
// Aggregate the committed FG monthly series into a portfolio lead-time-demand
// distribution; overage = monthly holding (carry/12 × weighted unit cost),
// underage = weighted contribution margin lost on a stockout. The R–U LP then
// returns the CVaR-β-robust order-up-to vs the expected-value level — the gap is
// "hold N more" finished units to protect the β-tail.
function cvarPlanPayload(beta){
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  // total FG units per month across the committed series (12 buckets)
  const monthly = Array(12).fill(0);
  let wCost=0, wMargin=0, wUnits=0;
  fin.forEach(p=>{
    const s = getItemDemand(p.sku, 12);
    s.forEach((v,i)=>{ monthly[i]+=v; });
    const u = s.reduce((a,b)=>a+b,0);
    const _uc=(typeof effUnitCost==='function'?effUnitCost(p):(p.cost||0));   // V2-2 derived cost
    wUnits += u; wCost += u*_uc; wMargin += u*Math.max(0,(p.price||0)-_uc);
  });
  const mean = monthly.reduce((a,b)=>a+b,0)/12;
  const variance = monthly.reduce((a,b)=>a+(b-mean)*(b-mean),0)/12;
  const std = Math.sqrt(variance);
  const unitCost = wUnits ? wCost/wUnits : 1000;
  const margin = wUnits ? wMargin/wUnits : 500;
  const holding = Math.max(1, unitCost * 0.24/12);     // monthly holding ₹/unit
  return { mean:Math.round(mean), std:Math.max(1,Math.round(std)),
    holding_cost:Math.round(holding), shortage_cost:Math.round(margin),
    beta:Number(beta)||0.95, n_scenarios:300, _holding:Math.round(holding) };
}
// RK-B · per-SKU CVaR payload — each finished SKU stocked on ITS OWN economics
// (overage = its monthly holding, underage = its OWN contribution margin), so the
// "hold N more" buffer is sized per item, not on one portfolio-blended h/p that
// hides a cheap high-volume SKU's low critical ratio behind a costly one's high one.
function cvarSkuPayload(p, beta){
  const s = getItemDemand(p.sku, 12);
  const mean = s.reduce((a,b)=>a+b,0)/12;
  const variance = s.reduce((a,b)=>a+(b-mean)*(b-mean),0)/12;
  const std = Math.sqrt(variance);
  const _c = (typeof effUnitCost==='function'?effUnitCost(p):(Number(p.cost)||0));   // V2-2 derived cost
  const holding = Math.max(1, _c * 0.24/12);          // its own monthly holding ₹/u
  const margin = Math.max(1, (Number(p.price)||0) - _c); // its own lost margin
  return { mean:Math.round(mean), std:Math.max(1,Math.round(std)),
    holding_cost:Math.round(holding), shortage_cost:Math.round(margin),
    beta:Number(beta)||0.95, n_scenarios:300, _holding:Math.round(holding) };
}

// ── D3 · RESILIENCE PACKAGING — stress-to-failure on the COMMITTED plan ────────
// Packages an existing strength (Monte-Carlo on the committed schedule) into the
// "how much shock does my plan survive?" answer the incumbents can't give simply.
// A named disruption playbook ramps ONE real lever (demand surge / supply lead-time /
// material cost) and RE-RUNS the MC solver at each step — a real multi-solve sweep,
// not a formula — recording fill and cost-tail. The breaking point (first step where
// fill drops below the service target) becomes a "survives to X" badge on the plan.
// Demand & lead-time move service; a cost shock doesn't (honest — it escalates the
// cost tail, not fill), so the cost playbook reports the CVaR exposure curve instead.
const _PLAYBOOKS = [
  { id:'demand', name:'Demand spike', icon:'📈', metric:'fill',
    levels:[0,10,20,30,40,50,60,80,100], fmt:m=>`+${m}%`,
    apply:(pl,m)=>({ ...pl, products: pl.products.map(p=>({ ...p, demand:(p.demand||[]).map(d=>Math.round(d*(1+m/100))) })) }) },
  { id:'lead', name:'Supply lead-time (port strike)', icon:'⏱', metric:'fill',
    levels:[0,1,2,3,4,5,6,8], fmt:m=>`+${m}wk`,
    apply:(pl,m)=>({ ...pl, params:{ ...pl.params, prod_lead_time:(Number(pl.params.prod_lead_time)||0)+m } }) },
  { id:'cost', name:'Material cost shock', icon:'💸', metric:'cvar',
    levels:[0,10,20,30,40,60,80,100], fmt:m=>`+${m}%`,
    apply:(pl,m)=>({ ...pl, products: pl.products.map(p=>({ ...p,
      variable_cost:Math.round((p.variable_cost||0)*(1+m/100)),
      parts:(p.parts||[]).map(pt=>({ ...pt, landed_cost:Math.round((pt.landed_cost||0)*(1+m/100)*100)/100 })) })) }) },
];
function ResilienceStress({ planning, config, onNav }){
  const [pbId, setPbId] = useState('demand');
  const [busy, setBusy] = useState(false);
  const [prog, setProg] = useState(0);
  const [rows, setRows] = useState(null);   // [{m, fill, cvar, mean}]
  const [at, setAt]     = useState(null);
  const [err, setErr]   = useState(null);
  const pb = _PLAYBOOKS.find(x=>x.id===pbId) || _PLAYBOOKS[0];
  const target = Math.round((Number(config.serviceLevel)||0.95)*100);
  const planned = !!(montecarloPayload(planning,{}).params.plan_committed);

  const run = async ()=>{
    setBusy(true); setErr(null); setRows(null); setProg(0);
    try{
      const base = montecarloPayload(planning, { nRuns:200, serviceLevel:config.serviceLevel });
      const out = [];
      for(let i=0;i<pb.levels.length;i++){
        const m = pb.levels[i];
        const res = await apiPost('/api/solve/montecarlo', pb.apply(base, m));
        out.push({ m, fill:Number(res.avg_fill), cvar:Number(res.cvar95), mean:Number(res.avg_cost), minFill:Number(res.min_fill) });
        setProg(Math.round((i+1)/pb.levels.length*100));
        setRows([...out]);
      }
      setAt(new Date());
      if(typeof logEvent==='function') logEvent('resilience_stress', pb.id, { target, levels:pb.levels.length });
    }catch(e){ setErr(e.message||String(e)); } finally{ setBusy(false); }
  };

  // breaking point: first level where fill drops below the service target
  let survivesTo=null, breaksAt=null;
  if(rows && pb.metric==='fill'){
    for(const r of rows){ if(r.fill>=target) survivesTo=r.m; else { breaksAt=r.m; break; } }
  }
  const baseRow = rows && rows[0];
  const lastRow = rows && rows[rows.length-1];
  const fmax = rows ? 100 : 100;
  const cmax = rows ? Math.max(1,...rows.map(r=>r.cvar||0)) : 1;

  return (
    <Card icon="🛡" title="Resilience — stress the committed plan to failure" span={2}
      badge={rows ? (pb.metric==='fill' ? (breaksAt!=null?`breaks at ${pb.fmt(breaksAt)}`:`survives all ${pb.fmt(pb.levels[pb.levels.length-1])}`) : 'cost-exposure curve') : 'not run'}
      badgeTone={rows ? (pb.metric!=='fill'?'y':breaksAt!=null?'k':'g') : 'k'}
      right={<Btn kind="primary" sm onClick={run} style={busy?{opacity:.6}:undefined}>{busy?`Stressing… ${prog}%`:'▶ Run stress test'}</Btn>}
      info={{ what:'Ramps a named disruption (demand / lead-time / cost) and re-runs the Monte-Carlo solver at each step on the committed plan — a real multi-solve sweep. The breaking point (fill below the service target) is the "survives to X" badge.', flows:'Resilience proof for the committed plan → buffers, dual-sourcing, hedges.' }}
      dev={{ comp:'ResilienceStress (D3)', props:'montecarloPayload + N× /api/solve/montecarlo', note:'Stress-to-failure on the committed schedule — packages MC into a survivability answer.' }}>
      <div style={{display:'flex', gap:8, flexWrap:'wrap', marginBottom:10}}>
        {_PLAYBOOKS.map(p=>(
          <button key={p.id} onClick={()=>{ setPbId(p.id); setRows(null); }} style={{
            display:'flex', alignItems:'center', gap:6, border:`2px solid ${p.id===pbId?C.ink:C.line}`, cursor:'pointer',
            background:p.id===pbId?C.ink:C.paper, color:p.id===pbId?C.ac:C.tx, padding:'6px 11px', fontFamily:F.disp, fontSize:11, fontWeight:700}}>
            <span>{p.icon}</span>{p.name}</button>
        ))}
      </div>
      {!planned && <div style={{marginBottom:9, padding:'7px 11px', border:`2px solid ${C.a4}`, background:C.bg3, fontFamily:F.mono, fontSize:9.5, color:C.a4, lineHeight:1.5}}>
        No production schedule cached — the stress runs against a base-stock policy. Run Production / the Loop first to stress the schedule that will actually EXECUTE{onNav?<span> · <span style={{textDecoration:'underline', cursor:'pointer'}} onClick={()=>onNav('production')}>open Production</span></span>:null}.</div>}
      {err && <div style={{marginBottom:9, fontFamily:F.mono, fontSize:10, color:C.dg}}>⚠ {err}</div>}

      {rows && pb.metric==='fill' && (
        <KpiRow cols={3}>
          <Blk label="Survives to" value={survivesTo!=null?pb.fmt(survivesTo):'breaks immediately'} tone={survivesTo!=null?'g':'k'} accent={survivesTo!=null?C.gn:C.dg} sub={`fill ≥ ${target}% target`}/>
          <Blk label="Breaking point" value={breaksAt!=null?pb.fmt(breaksAt):'—'} accent={breaksAt!=null?C.dg:undefined} sub={breaksAt!=null?'service drops below target':'holds across the ramp'}/>
          <Blk label="Worst-case fill" value={lastRow?`${lastRow.fill}%`:'—'} sub={`at ${pb.fmt(pb.levels[pb.levels.length-1])} · CVaR ${lastRow?(lastRow.cvar/1e5).toFixed(1)+'L':'—'}`} tone="y"/>
        </KpiRow>
      )}
      {rows && pb.metric==='cvar' && (
        <KpiRow cols={3}>
          <Blk label="Base CVaR95" value={baseRow?`₹${(baseRow.cvar/1e5).toFixed(2)}L`:'—'}/>
          <Blk label="Stressed CVaR95" value={lastRow?`₹${(lastRow.cvar/1e5).toFixed(2)}L`:'—'} accent={C.dg} sub={`at ${pb.fmt(pb.levels[pb.levels.length-1])}`}/>
          <Blk label="Tail escalation" value={baseRow&&lastRow&&baseRow.cvar?`${(lastRow.cvar/baseRow.cvar).toFixed(2)}×`:'—'} tone="y" sub="cost tail, not service"/>
        </KpiRow>
      )}

      {rows && (
        <svg viewBox="0 0 700 130" style={{width:'100%', height:130, display:'block', marginTop:10}}>
          {pb.metric==='fill' && <line x1="0" y1={120-target/fmax*110} x2="700" y2={120-target/fmax*110} stroke={C.a4} strokeWidth="1" strokeDasharray="4 3"/>}
          {rows.map((r,i)=>{ const w=700/pb.levels.length;
            const val = pb.metric==='fill' ? r.fill/fmax : r.cvar/cmax;
            const h = Math.max(1, val*110);
            const broke = pb.metric==='fill' && r.fill<target;
            return <rect key={i} x={i*w+3} y={120-h} width={w-6} height={h} fill={broke?C.dg:pb.metric==='cvar'?C.a4:C.ac}/>;
          })}
          <line x1="0" y1="120" x2="700" y2="120" stroke={C.line} strokeWidth="1"/>
        </svg>
      )}
      {rows && (
        <div style={{display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx3, marginTop:2}}>
          {pb.metric==='fill' ? <><span style={{color:C.a4}}>┄ {target}% service target</span><span style={{color:C.dg}}>◼ below target</span></> : <span style={{color:C.a4}}>◼ CVaR95 by stress level</span>}
          <span style={{flex:1}}/>
          <span>{pb.levels.map(pb.fmt).join(' · ')}</span>
        </div>
      )}

      {!rows && !busy && <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'12px 0'}}>
        Pick a disruption playbook and run — each step re-solves the Monte-Carlo on the committed plan, ramping the shock until {pb.metric==='fill'?'fill drops below the service target':'the cost tail is fully stressed'}. {pb.levels.length} solves.</div>}

      {rows && <Reading tone={pb.metric!=='fill'?C.a4:(breaksAt!=null?C.dg:C.gn)}
        formula={`${pb.name}: ${pb.levels.length} MC re-solves on the committed plan · target fill ${target}%`}
        soWhat={pb.metric==='fill'
          ? (breaksAt!=null
              ? `The committed plan holds its ${target}% service target up to a ${pb.fmt(survivesTo!=null?survivesTo:0)} shock, then breaks at ${pb.fmt(breaksAt)} (fill falls to ${(rows.find(r=>r.m===breaksAt)||{}).fill}%). That is your resilience headroom — buffer or dual-source before a disruption of that size, and note the cost tail rises to ₹${lastRow?(lastRow.cvar/1e5).toFixed(1):'—'}L at the extreme.`
              : `The committed plan survives the entire ramp to ${pb.fmt(pb.levels[pb.levels.length-1])} without dropping below the ${target}% target — a genuinely robust plan against this disruption (worst-case fill ${lastRow?lastRow.fill:'—'}%).`)
          : `A material cost shock doesn't move service (fill is supply-timing, not price) — it escalates the cost tail. CVaR95 rises ${baseRow&&lastRow&&baseRow.cvar?(lastRow.cvar/baseRow.cvar).toFixed(2):'—'}× from base to a ${pb.fmt(pb.levels[pb.levels.length-1])} shock. Hedge the spend, not the schedule.`}/>}
    </Card>
  );
}

function ScnRisk({ onNav }) {
  const { planning } = usePlanning();
  const { config } = useConfig();
  const { state:solves } = useStore(s=>s.solves||{});
  const { events } = useEvents();
  const [corr, setCorr] = useState('');
  const [nRuns, setNRuns] = useState('');
  const [beta, setBeta] = useState('');
  const [lt, setLt] = useState('');             // RK-D — production lead-time lag (weeks), plan mode
  const [skuRho, setSkuRho] = useState('');     // V4-7 — cross-SKU demand co-movement (0 = independent legacy)
  const mc = useSolve('/api/solve/montecarlo', ()=>montecarloPayload(planning,
    { serviceLevel:config.serviceLevel, corr:(corr===''?undefined:corr), nRuns:(nRuns===''?undefined:nRuns),
      prodLeadTime:(lt===''?undefined:lt), demandRho:(skuRho===''?undefined:skuRho) }), { solveKey:'montecarlo' });   // LP-C hydrate from loop cache
  const cvB = beta===''?0.95:Number(beta);
  const r = mc.result;
  // RK-B — per-SKU CVaR solved and rolled up (replaces the single blended newsvendor).
  const [cvRows, setCvRows] = useState(null);
  const [cvRun, setCvRun]   = useState(false);
  const [cvAt, setCvAt]     = useState(null);
  const [cvErr, setCvErr]   = useState(null);
  const runCvar = async ()=>{
    setCvRun(true); setCvErr(null);
    try{
      const fin = (M.products||[]).filter(p=>p.cat==='Finished');
      const rows = await Promise.all(fin.map(p=>{ const pl = cvarSkuPayload(p, cvB);
        return apiPost('/api/solve/cvar', pl)
          .then(res=>({ sku:p.sku, name:p.name, premium:res.robustness_premium_units,
            ev:res.expected_value_order_up_to, q:res.order_up_to, cr:res.critical_ratio, hold:pl._holding }))
          .catch(e=>({ sku:p.sku, name:p.name, error:e.message||String(e) })); }));
      setCvRows(rows); setCvAt(new Date()); markSolved('cvar');
    }catch(e){ setCvErr(e.message||String(e)); }
    finally{ setCvRun(false); }
  };
  const cvOk   = (cvRows||[]).filter(x=>!x.error);
  const cvTotU = cvOk.reduce((s,x)=>s+Math.max(0,x.premium||0),0);
  const cvTotMo= cvOk.reduce((s,x)=>s+Math.max(0,x.premium||0)*(x.hold||0),0);
  const planned = !!(montecarloPayload(planning,{}).params.plan_committed);
  const alerts = liveAlerts(solves, events, r);
  const runMc = ()=> mc.run().then(d=>{ markSolved('montecarlo', d); return d; }).catch(()=>{});

  // cost histogram geometry
  const hist = r && r.histogram;
  const hmax = hist ? Math.max(1, ...hist.counts) : 1;

  return (
    <>
    <Grid cols={2}>
      {/* R-1 · Monte Carlo on the committed plan */}
      <Card icon="🎲" title="Monte Carlo — committed plan" span={2}
        badge={r?`${r.n_runs} runs · ${r.solve_time}s`:'not run'} badgeTone={r?'g':'k'}
        right={<Btn kind="primary" sm onClick={runMc}>{mc.solving?'Running…':'Run Monte Carlo'}</Btn>}
        info={{ what:'Replays the committed production schedule against demand + material-cost shocks (ρ-correlated). Reports the cost distribution, VaR/CVaR95 and the fill-rate distribution.', flows:'Tail risk → hedging, buffers, service tuning.' }}
        dev={{ comp:'ScnRisk·MC', props:'montecarloPayload(planning)', note:'/api/solve/montecarlo — policy=plan when a production solve is cached.' }}>
        <div style={{display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end', marginBottom:10}}>
          <SolverInput label="Demand↔cost ρ" seed={0.4} value={corr} onChange={setCorr} min={-0.95} max={0.95} w={92} hint="shock correlation"/>
          <SolverInput label="Cross-SKU ρ" seed={0.5} value={skuRho} onChange={setSkuRho} min={0} max={0.95} w={92} hint="V4-7 — XYZ co-movement; 0 = independent"/>
          <SolverInput label="MC runs" seed={500} value={nRuns} onChange={setNRuns} min={100} max={5000} integer w={92}/>
          <SolverInput label="Prod lead-time wk" seed={1} value={lt} onChange={setLt} min={0} max={8} w={104} hint="RK-D — plan-mode build→land lag"/>
          <div style={{flex:1}}/>
          <Provenance kind={r?'solved':'derived'} asOf={mc.ranAt?mc.ranAt.toLocaleTimeString():'not yet solved'} stale={!r}/>
        </div>
        {mc.error && <div style={{fontFamily:F.mono, fontSize:10, color:C.dg, marginBottom:8}}>⚠ {mc.error}</div>}
        {!r && !mc.solving && <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'14px 0'}}>Run to simulate the committed plan. {planned?'A production schedule is cached → policy = plan (the schedule that will execute).':'No production solve cached → falls back to a base-stock policy; run Production (or the Loop) first to simulate the real schedule.'}</div>}
        {r && <>
          <KpiRow cols={4}>
            <Blk label="Mean cost" value={`₹${(r.avg_cost/1e5).toFixed(2)}L`}/>
            <Blk label="VaR 95" value={`₹${(r.var95/1e5).toFixed(2)}L`} tone="y"/>
            <Blk label="CVaR 95" value={`₹${(r.cvar95/1e5).toFixed(2)}L`} accent={C.dg}/>
            <Blk label="Fragility" value={`${r.fragility}×`} sub="VaR/mean"/>
          </KpiRow>
          {/* V4-7 — systemic-demand mode echo: tails now include cross-SKU co-movement */}
          <div data-vis="v4-mccorr" style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color:C.tx3, padding:'6px 9px', border:`1px solid ${C.line2}`, background:C.bg3}}>
            {r.demand_correlation && r.demand_correlation.active
              ? <>SYSTEMIC DEMAND RISK ON — {r.demand_correlation.n_skus} SKUs co-move (XYZ heuristic, mean ρ̄ {r.demand_correlation.mean_offdiag_rho}{r.demand_correlation.psd_clipped?' · matrix eigen-repaired to PSD':''}); the cost tail above includes recession/festival weeks hitting every SKU TOGETHER. Set Cross-SKU ρ = 0 to see the (optimistic) independent-draws tail.</>
              : <>Cross-SKU ρ = 0 — every SKU draws independently, so portfolio bad weeks √N-diversify away. Real demand co-moves (recessions, seasons): raise Cross-SKU ρ to price the systemic tail.</>}
          </div>
          <svg viewBox="0 0 700 150" style={{width:'100%', height:150, display:'block', marginTop:10}}>
            {hist && hist.counts.map((n,i)=>{ const w=700/hist.counts.length, h=n/hmax*120;
              const tail = hist.bins[i] >= r.var95;
              return <rect key={i} x={i*w+1} y={140-h} width={w-2} height={h} fill={tail?C.dg:C.ac}/>;
            })}
            <line x1="0" y1="140" x2="700" y2="140" stroke={C.line} strokeWidth="1"/>
          </svg>
          <div style={{display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx3, marginTop:2}}>
            <span>◼ body</span><span style={{color:C.dg}}>◼ ≥VaR95 tail (worst 5%)</span>
            <span style={{flex:1}}/><span>p10 ₹{(r.p10/1e5).toFixed(2)}L · p90 ₹{(r.p90/1e5).toFixed(2)}L</span>
          </div>
          <KpiRow cols={3}>
            <Blk label="Mean fill" value={`${r.avg_fill}%`} accent={r.avg_fill<95?C.dg:C.gn}/>
            <Blk label="Worst-case fill" value={`${r.min_fill}%`} tone="y"/>
            <Blk label="Policy simulated" value={r.policy_simulated==='plan'?'committed plan':'base-stock'} tone={r.policy_simulated==='plan'?'g':'k'}/>
          </KpiRow>
          {/* V3-14 · VIS-9 — the service-risk picture from the solver's own fill histogram */}
          <Vis9FillDist r={r} target={Math.round((Number(config.serviceLevel)||0.95)*100)}/>
          <Reading tone={r.policy_simulated==='plan'?C.gn:C.a4}
            formula={`CVaR95 = E[cost | cost ≥ VaR95] = ₹${(r.cvar95/1e5).toFixed(2)}L over the worst 5% of ${r.n_runs} runs`}
            soWhat={r.policy_simulated==='plan'
              ? `Risk of the schedule that will EXECUTE${r.prod_lead_time>0?`, with a ${r.prod_lead_time}-wk stochastic build→land lag (RK-D) — a mis-timed build against a shock is penalised`:''}. The β-tail costs ₹${((r.cvar95-r.avg_cost)/1e5).toFixed(2)}L over the mean; mean fill ${r.avg_fill}%.`
              : `No committed schedule cached — this simulates a re-derived base-stock policy. Run Production / the Loop to price the actual plan (R-1).`}/>
        </>}
      </Card>

      {/* D3 · Resilience packaging — stress-to-failure on the committed plan */}
      <ResilienceStress planning={planning} config={config} onNav={onNav}/>

      {/* R-2 · CVaR robust finished buffer — per-SKU rolled up (RK-B) */}
      <Card icon="🛡" title="CVaR-robust stock — hold N more (per SKU)"
        badge={cvRows?`β=${cvB} · ${cvOk.length} SKUs`:'not run'} badgeTone={cvRows?'g':'k'}
        right={<Btn kind="primary" sm onClick={runCvar}>{cvRun?'…':'Solve CVaR'}</Btn>}
        info={{ what:'Rockafellar–Uryasev CVaR newsvendor solved PER finished SKU on its own holding/margin economics, then rolled up — not one portfolio-blended h/p. Each row is the order-up-to robust to that SKU\'s β-tail vs its expected-value level.', flows:'Premium units → a per-SKU procurement/production floor.' }}
        dev={{ comp:'ScnRisk·CVaR', props:'cvarSkuPayload(p,beta) × finished SKUs', note:'/api/solve/cvar (cvar.py) — RK-B per-SKU roll-up.' }}>
        <div style={{display:'flex', gap:10, alignItems:'flex-end', marginBottom:8}}>
          <SolverInput label="Tail β" seed={0.95} value={beta} onChange={setBeta} min={0.5} max={0.999} w={88} hint="worst (1−β) avg"/>
          <div style={{flex:1}}/>
          <Provenance kind={cvRows?'solved':'derived'} asOf={cvAt?cvAt.toLocaleTimeString():'not solved'} stale={!cvRows}/>
        </div>
        {cvErr && <div style={{fontFamily:F.mono, fontSize:10, color:C.dg, marginBottom:8}}>⚠ {cvErr}</div>}
        {cvRows ? <>
          <KpiRow cols={2}>
            <Blk label="Σ hold N more" value={`+${Math.round(cvTotU)}u`} accent={C.dg}/>
            <Blk label="Extra holding ₹/mo" value={`₹${Math.round(cvTotMo).toLocaleString('en-IN')}`} tone="y"/>
          </KpiRow>
          <div style={{marginTop:8}}>
            <DataTable dense cols={['SKU','Crit. ratio','EV up-to','CVaR up-to','Hold N more']} align={['left','right','right','right','right']}
              rows={cvOk.map(x=>({cells:[x.name, `${(x.cr*100).toFixed(0)}%`, `${Math.round(x.ev)}u`, `${Math.round(x.q)}u`,
                <span style={{fontWeight:700, color:x.premium>0?C.dg:C.tx3}}>{x.premium>0?'+':''}{Math.round(x.premium)}u</span>]}))}/>
          </div>
          <Reading formula="per SKU: critical ratio p/(p+h) on its OWN holding vs margin · premium = Q*_CVaR − Q_EV"
            soWhat={`Rolled up across the portfolio, the β=${cvB} tail-robust plan holds +${Math.round(cvTotU)} finished units (≈ ₹${Math.round(cvTotMo).toLocaleString('en-IN')}/mo) — but the table shows WHERE: low-critical-ratio SKUs (holding dominates) barely buffer, high-margin ones carry the premium. A single blended newsvendor hid that split.`}/>
        </> : <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'10px 0'}}>Solve to size the CVaR-robust finished buffer per SKU and roll it up.</div>}
      </Card>

      {/* R-4 · live Control Tower from real signals */}
      <Card icon="🚨" title="Control Tower — live signals" badge={`${alerts.length} live`} badgeTone={alerts.length?'r':'g'}
        info={{ what:'Alerts derived from REAL model state: stale solves, logged triggers/replans, and the live Monte-Carlo tail. Not a hardcoded list.', flows:'Drill into the owning stage.' }}
        dev={{ comp:'ControlTower', props:'liveAlerts(solves,events,mc)', state:'appStore.solves/events' }}>
        {alerts.length ? <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {alerts.map((a,i)=>{ const sc=a.sev==='H'?C.dg:a.sev==='M'?C.a4:C.tx3;
            return (<div key={i} onClick={()=>a.go&&onNav&&onNav(a.go)} style={{display:'flex', alignItems:'center', gap:9, border:`2px solid ${C.line}`, padding:'7px 9px', borderLeft:`5px solid ${sc}`, cursor:a.go?'pointer':'default'}}>
              <span style={{width:20, height:20, flexShrink:0, display:'grid', placeItems:'center', background:sc, color:'#fff', fontFamily:F.disp, fontWeight:900, fontSize:10}}>{a.sev}</span>
              <span style={{fontFamily:F.body, fontSize:11.5, fontWeight:600, flex:1}}>{a.msg}</span>
              <Tag c="w">{a.area}</Tag><span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{a.t}</span>
            </div>);
          })}
        </div> : <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'14px 0'}}>✓ No live alerts — all solves fresh, no open triggers, MC fill ≥ 95%. (Edit an input or run MC to populate.)</div>}
      </Card>

      {/* lost sales — real from MC fill, honest empty until run */}
      <Card icon="🩸" title="Lost Sales (from MC fill)" badge={r?'live':'run MC'} badgeTone={r?'g':'k'}
        info={{ what:'Expected unmet demand at the mean fill rate from the Monte-Carlo run on the committed plan.', flows:'Lost margin → service-level tuning.' }}
        dev={{ comp:'LostSalesCard', props:'mc.avg_fill' }}>
        {r ? (()=>{ const fin=(M.products||[]).filter(p=>p.cat==='Finished');
          const T = Math.max(4, Math.min(planning.horizonLength||13,13));
          const totUnits = fin.reduce((s,p)=>s+getItemDemand(p.sku,T).reduce((a,b)=>a+b,0),0);
          const lostU = Math.round(totUnits*(100-r.avg_fill)/100);
          const avgMargin = fin.length? fin.reduce((s,p)=>s+Math.max(0,(p.price||0)-(typeof effUnitCost==='function'?effUnitCost(p):(p.cost||0))),0)/fin.length:0;   // V2-2
          const lostMargin = lostU*avgMargin;
          return <><KpiRow cols={2}>
            <Blk label="Units lost (mean)" value={`${lostU.toLocaleString('en-IN')} u`} accent={C.dg}/>
            <Blk label="Lost margin" value={`₹${(lostMargin/1e5).toFixed(2)} L`} tone="c"/>
          </KpiRow>
          <Reading formula={`(1 − fill) × Σ committed units = ${((100-r.avg_fill)/100).toFixed(3)} × ${totUnits.toLocaleString('en-IN')} = ${lostU}u`}
            soWhat={`At ${r.avg_fill}% mean fill the committed plan leaves ≈ ₹${(lostMargin/1e5).toFixed(2)}L of margin on the table over ${T} weeks.`}/></>;
        })() : <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'14px 0'}}>Run Monte Carlo above to quantify expected lost sales from the fill distribution.</div>}
      </Card>

      {/* RK-C · SOLVED sensitivity — drivers ranked by real MC cost deltas */}
      <SolvedTornado planning={planning} config={config}/>
    </Grid>

    {/* governance / illustrative garnish — explicitly seed-badged, not solved */}
    <Advanced label="Sensitivity ranking · disruption registry · stakeholder map (illustrative — not solved)" count={M.tornado.length}>
      <Grid cols={2}>
        <Card icon="📊" title="Sensitivity (Tornado)" badge="illustrative" badgeTone="k"
          right={<Provenance kind="external" run="seed"/>}
          dev={{ comp:'SensitivityCard', props:'M.tornado', note:'Driver ranking seed — wire /api/solve/sensitivity for the solved version.' }}>
          <Tornado/>
        </Card>
        <Card icon="⚡" title="Disruption Registry" badge={`${M.disruptions.length}`} right={<Provenance kind="external" run="seed"/>}
          dev={{ comp:'DisruptionRegistryCard', props:'M.disruptions' }}>
          <DataTable dense cols={['Event','Prob','Impact','Mitigation']} align={['left','left','right','left']}
            rows={M.disruptions.map(d=>[d.event, d.prob, d.impact, d.mitig])}/>
        </Card>
        <Card icon="👥" title="Stakeholder Power × Interest" badge={`${M.stakeholders.length}`} right={<Provenance kind="external" run="seed"/>}
          dev={{ comp:'StakeholderMatrixCard', props:'M.stakeholders' }}>
          <DataTable dense cols={['Stakeholder','Power','Interest','Strategy']} align={['left','center','center','left']}
            rows={M.stakeholders.map(s=>[s.name, s.power, s.interest, s.q])}/>
        </Card>
      </Grid>
    </Advanced>
    </>
  );
}

// ── W7 · end-to-end loop ────────────────────────────────────────────────────
function ScnLoop({ onNav }) {
  const { planning } = usePlanning();
  const [log, setLog] = useState(null);
  const [running, setRunning] = useState(false);
  const [doneAt, setDoneAt] = useState(null);
  const run = async ()=>{
    setRunning(true); setLog(null);
    try{ const final = await runFullLoop({ planning, onStep:(l)=>setLog([...l]) }); setLog(final); setDoneAt(new Date()); }
    finally{ setRunning(false); }
  };
  const steps = (typeof LOOP_STEPS!=='undefined'?LOOP_STEPS:[]);
  const okCount = (log||[]).filter(s=>s.ok).length;
  return (
    <Grid cols={1}>
      <Card icon="🔗" title="Run the whole loop — one dataset" span={1}
        badge={log?`${okCount}/${steps.length} solved`:'idle'} badgeTone={log? (okCount===steps.length?'g':'y') :'k'}
        right={<Btn kind="primary" sm onClick={run}>{running?'Running…':'▶ Run end-to-end loop'}</Btn>}
        info={{ what:'Chains the planning solvers in dependency order on the same committed dataset: procurement → aggregate S&OP → production schedule → ₹ line-capacity dual → Monte-Carlo risk on the just-built schedule. Each step feeds the next.', flows:'One action re-plans the planning spine (Kinaxis-style) — the other engines keep their last result.' }}
        dev={{ comp:'ScnLoop', props:'runFullLoop({planning})', note:'store.jsx — caches each result so downstream tabs read it.' }}>
        <Provenance kind={log?'solved':'derived'} asOf={doneAt?doneAt.toLocaleTimeString():'not yet run'} stale={!log} style={{marginBottom:10}}/>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {steps.map((st,i)=>{ const e=(log||[]).find(x=>x.key===st.key);
            const status = e ? (e.ok?'ok':(e.error?'err':'run')) : (running?'wait':'idle');
            const col = status==='ok'?C.gn:status==='err'?C.dg:status==='run'?C.ac:C.line2;
            const ico = status==='ok'?'✓':status==='err'?'✕':status==='run'?'…':(i+1);
            return (<div key={st.key} style={{display:'flex', alignItems:'center', gap:10, border:`2px solid ${C.line}`, borderLeft:`5px solid ${col}`, padding:'8px 10px'}}>
              <span style={{width:22, height:22, flexShrink:0, display:'grid', placeItems:'center', background:col, color:'#fff', fontFamily:F.disp, fontWeight:900, fontSize:11}}>{ico}</span>
              <div style={{flex:1, minWidth:0}}>
                <div style={{fontFamily:F.body, fontSize:12, fontWeight:700}}>{st.label}</div>
                <div style={{fontFamily:F.mono, fontSize:9.5, color: e&&e.error?C.dg:C.tx3, marginTop:1}}>{e ? (e.error?('⚠ '+e.error):e.summary) : (running?'queued…':'not run')}</div>
              </div>
              {e && e.ok && <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>{e.ms}ms</span>}
            </div>);
          })}
        </div>
        {log && <Reading tone={okCount===steps.length?C.gn:C.a4}
          formula={`chained ${okCount}/${steps.length} solves on one committed dataset · Σ ${ (log.reduce((s,x)=>s+(x.ms||0),0))}ms`}
          soWhat={okCount===steps.length
            ? 'The full plan re-solved end-to-end: each downstream solver consumed the upstream result (committed demand → POs → workforce → schedule → line dual → risk). Tabs now show these fresh numbers.'
            : 'Some steps failed — see the red rows; the chain continues so you can see which link broke.'}/>}
      </Card>
    </Grid>
  );
}

// RK-C · solved sensitivity — sweep each governed MC param over a range via
// /api/solve/sensitivity (which re-runs Monte Carlo per value on the SAME committed
// base payload) and rank drivers by the REAL cost spread they produce, vs the
// illustrative seed tornado (kept behind Advanced). Only params.* scalars are
// sweepable through the endpoint's dotted-path (products are a list it can't index),
// so this ranks the policy/correlation/lead-time levers on the committed plan.
const SENS_LABEL = { 'params.corr_demand_cost':'Demand↔cost ρ', 'params.service_level':'Service level',
  'params.carry_rate':'Carry rate', 'params.prod_lead_time':'Prod lead-time (RK-D)' };
function SolvedTornado({ planning, config }){
  const [rows, setRows] = useState(null);
  const [run, setRun]   = useState(false);
  const [at, setAt]     = useState(null);
  const [err, setErr]   = useState(null);
  const solve = async ()=>{
    setRun(true); setErr(null);
    try{
      const base = montecarloPayload(planning, { serviceLevel:config.serviceLevel });
      const param_ranges = {
        'params.corr_demand_cost':[0, 0.4, 0.8],
        'params.service_level':[0.90, 0.95, 0.99],
        'params.carry_rate':[0.18, 0.24, 0.30],
        'params.prod_lead_time':[0, 1, 3],
      };
      const res = await apiPost('/api/solve/sensitivity', { base_data:base, param_ranges });
      const byParam = {};
      (res.results||[]).forEach(r=>{ (byParam[r.param]=byParam[r.param]||[]).push(r); });
      const out = Object.entries(byParam).map(([param,vals])=>{
        const sorted = vals.slice().sort((a,b)=>a.value-b.value);
        const costs = sorted.map(v=>v.avg_cost);
        const baseC = costs[Math.floor(costs.length/2)] || costs[0] || 1;
        const lo = Math.min(...costs), hi = Math.max(...costs);
        return { param:SENS_LABEL[param]||param,
          low:+(((lo-baseC)/baseC)*100).toFixed(1), high:+(((hi-baseC)/baseC)*100).toFixed(1),
          range:hi-lo };
      }).sort((a,b)=>b.range-a.range);
      setRows(out); setAt(new Date());
    }catch(e){ setErr(e.message||String(e)); }
    finally{ setRun(false); }
  };
  const mx = rows && rows.length ? Math.max(1, ...rows.flatMap(r=>[Math.abs(r.low), Math.abs(r.high)]))*1.1 : 1;
  return (
    <Card icon="📊" title="Sensitivity (solved)" badge={rows?`${rows.length} drivers`:'not run'} badgeTone={rows?'g':'k'} span={2}
      right={rows ? <Provenance kind="solved" asOf={at}/> : <Btn kind="primary" sm onClick={solve}>{run?'Sweeping…':'Solve sensitivity'}</Btn>}
      info={{ what:'Each governed MC parameter swept over a range; the bar is the % change in mean cost it produces on the committed plan (worst vs best in the sweep). Ranked by spread — the real "which lever moves cost most".', flows:'/api/solve/sensitivity → driver ranking → where to harden the plan.' }}
      dev={{ comp:'SolvedTornado', props:'/api/solve/sensitivity ← montecarloPayload base × param sweeps', note:'RK-C — replaces the seed tornado for the policy levers.' }}>
      {err && <div style={{fontFamily:F.mono, fontSize:10, color:C.dg, marginBottom:8}}>⚠ {err}</div>}
      {!rows ? <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'12px 0'}}>Sweep the governed risk parameters and rank them by the real mean-cost spread each produces on the committed plan.</div> : (<>
        <svg viewBox={`0 0 480 ${rows.length*30+16}`} style={{width:'100%', height:rows.length*30+16, display:'block'}}>
          <line x1="240" y1="6" x2="240" y2={rows.length*30+6} stroke={C.line} strokeWidth="1.5"/>
          {rows.map((r,i)=>{ const y=16+i*30;
            const lw=Math.abs(r.low)/mx*210, hw=Math.abs(r.high)/mx*210;
            const lx = r.low<0?240-lw:240, hx = r.high<0?240-hw:240;
            return (<g key={i}>
              <rect x={lx} y={y-9} width={lw} height="9" fill={C.dg}/>
              <rect x={hx} y={y+1} width={hw} height="9" fill={C.gn}/>
              <text x="236" y={y-1} fontFamily={F.mono} fontSize="8.5" fill={C.tx} textAnchor="end">{r.low}%</text>
              <text x="244" y={y+9} fontFamily={F.mono} fontSize="8.5" fill={C.tx}>{r.high>0?'+':''}{r.high}%</text>
              <text x="4" y={y+2} fontFamily={F.mono} fontSize="9" fill={C.tx2}>{r.param}</text>
            </g>);
          })}
        </svg>
        <Reading formula="bar = (max − base)/base and (min − base)/base of mean MC cost across each param's sweep"
          soWhat={`${rows[0].param} moves committed-plan cost most (spread ${rows[0].range.toFixed(0)} ₹), so it's the first lever to harden. Unlike the illustrative tornado below, these deltas are SOLVED — each is a real Monte-Carlo re-run on the committed payload.`}/>
      </>)}
    </Card>
  );
}

function Tornado() {
  const t=M.tornado, mx=Math.max(...t.flatMap(r=>[Math.abs(r.low),r.high]))*1.1;
  return (
    <svg viewBox={`0 0 480 ${t.length*26+20}`} style={{width:'100%', height:t.length*26+20, display:'block'}}>
      <line x1="240" y1="6" x2="240" y2={t.length*26+6} stroke={C.line} strokeWidth="1.5"/>
      {t.map((r,i)=>{ const y=14+i*26;
        const lw=Math.abs(r.low)/mx*220, hw=r.high/mx*220;
        return (<g key={i}>
          <rect x={240-lw} y={y-8} width={lw} height="16" fill={C.dg}/>
          <rect x="240" y={y-8} width={hw} height="16" fill={C.gn}/>
          <text x="234" y={y+4} fontFamily={F.mono} fontSize="8.5" fill={C.tx} textAnchor="end" style={{display:lw>40?'block':'none'}}>{r.low}%</text>
          <text x="246" y={y+4} fontFamily={F.mono} fontSize="8.5" fill="#fff" style={{display:hw>40?'block':'none'}}>+{r.high}%</text>
        </g>);
      })}
    </svg>
  );
}

function ScnCost() {
  // G-SC1 — both cards now read SOLVED / DERIVED rollups, not the M.* seed.
  useStore(s=>s.solveResults||{});   // re-render when a solve caches
  useConfig();                        // re-render when carry rate / cover changes
  useMasterRev && useMasterRev();
  const live = (typeof costWaterfallLive==='function') ? costWaterfallLive() : null;   // null until procurement cached
  const tco  = (typeof tcoPerSku==='function') ? tcoPerSku() : [];
  const cw = live ? [...live.cats, { k:'TOTAL', v:live.total, total:true }]
                  : M.costWaterfall;
  const mx = Math.max(...cw.map(d=>d.v), 1);
  const sumCats = live ? live.cats.reduce((s,c)=>s+c.v,0) : null;   // == live.total by construction
  const L = v=> v>=1e7 ? `₹${(v/1e7).toFixed(2)}Cr` : v>=1e5 ? `₹${(v/1e5).toFixed(1)}L` : `₹${Math.round(v).toLocaleString('en-IN')}`;
  const n = cw.length, slot = 660/n, bw = Math.min(80, slot-12);
  // prov-ok: the solved chip reflects the cached procurement + transport solves read via costWaterfallLive() (cross-stage cache, not a local useSolve); seed when uncached
  const wfProv = live ? <Provenance kind="solved" note="procurement + transport"/> : <Provenance kind="external" run="seed"/>;
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Cost Waterfall" badge={live?'solved · live':'illustrative'} badgeTone={live?'g':'k'} span={2}
        right={wfProv}
        info={{ what:'Build-up of total cost by category. When procurement is solved this reads the live cost_breakdown (+ transport); Holding is the residual carrying cost, so the bars sum to the solved total.', flows:'Cost structure → savings hunt.' }}
        dev={{ comp:'CostWaterfallCard', props:'costWaterfallLive() ?? M.costWaterfall' }}>
        {!live && <SeedFence what="Illustrative cost structure for layout. Run procurement (Sourcing ⚡) — and optionally transport — and this becomes the solved category roll-up."/>}
        <svg viewBox="0 0 700 170" style={{width:'100%', height:170, display:'block'}}>
          {(()=>{ let cum=0;
            return cw.map((d,i)=>{ const x=20+i*slot, h=d.v/mx*120;
              const bar = d.total ? <rect x={x} y={150-h} width={bw} height={h} fill={C.ink}/>
                                  : <rect x={x} y={150-(cum+d.v)/mx*120} width={bw} height={d.v/mx*120} fill={C.ac}/>;
              const yTop = d.total?150-h:150-(cum+d.v)/mx*120;
              const out=(<g key={i}>{bar}
                <text x={x+bw/2} y="163" fontFamily={F.mono} fontSize="8" fill={C.tx2} textAnchor="middle">{d.k}</text>
                <text x={x+bw/2} y={yTop-4} fontFamily={F.disp} fontSize="8.5" fontWeight="700" fill={C.tx} textAnchor="middle">{live?L(d.v):`₹${d.v}`}</text>
              </g>);
              if(!d.total) cum+=d.v; return out;
            });
          })()}
        </svg>
        {live && <Reading formula="Σ category bars = solved total   ·   Holding = total − (material+ordering+setup+conversion+overhead+milk-run+expiry)"
          soWhat={`The ${live.cats.length} categories sum to ${L(sumCats)} = the solved total${live.hasTransport?' (incl. transport)':' (run transport to add the freight bar)'}. Holding is the carrying cost the MILP charged but didn't itemise — surfaced here as the residual.`}/>}
      </Card>
      <Card icon="🏗️" title="TCO per SKU" badge="derived" badgeTone="g" span={2}
        right={<Provenance kind="derived" note="unit+hold+order+quality+obsol"/>}
        info={{ what:'Total cost of ownership per unit: product cost + carrying (solved carry rate × cover) + amortised ordering (master S) + quality loss (measured yield) + obsolescence (salvage write-down when shelf < cover). TCO is the exact sum of the five.', flows:'TCO → true profitability.' }}
        dev={{ comp:'TCOCard', props:'tcoPerSku()', note:'G-SC1 — derived from carryRate (WACC) · master S · measured yield, not M.tco seed.' }}>
        <DataTable cols={['SKU','Unit','Holding','Ordering','Quality','Obsol.','TCO/u']} align={['left','right','right','right','right','right','right']}
          rows={tco.map(t=>({cells:[t.sku, `₹${t.unit.toLocaleString('en-IN')}`, `₹${t.hold.toLocaleString('en-IN')}`, `₹${t.order.toLocaleString('en-IN')}`, `₹${t.quality.toLocaleString('en-IN')}`, `₹${t.obsol.toLocaleString('en-IN')}`, <span style={{fontWeight:700, color:C.dg}}>₹{t.tco.toLocaleString('en-IN')}</span>]}))}/>
        <Reading formula="TCO/u = unit + (carry × unit × cover) + (Σ master S ÷ annual demand) + unit·(1/yield − 1) + salvage write-down"
          soWhat="Quality cost rises with a worse MEASURED yield, holding moves with the solved carry rate (WACC + spread), ordering uses the real per-PO S — so TCO reacts to the actual plan, not a frozen seed. Durable parts (shelf ≫ cover) carry ₹0 obsolescence, correctly."/>
      </Card>
    </Grid>
  );
}

function ScnExplore() {
  const wf = useSolve('/api/whatif', null);
  const [q, setQ] = useState('Material cost up 20% for Q3');
  const res = wf.result;
  return (
    <Grid cols={2}>
      <Card icon="🤖" title="What-If parser" badge="advisory" badgeTone="y" span={2}
        info={{ what:'Maps a plain-language scenario to the parameter knobs it would touch. This is a PARSER, not a solver — it does not change inputs or re-solve (apply the changes in the owning tab, then re-run).', flows:'Scenario → which levers to pull.' }}
        dev={{ comp:'WhatIfBot', props:'/api/whatif', note:'advisory_only=true — honest: no solve is run here.' }}>
        <div style={{border:`2px solid ${C.line}`, padding:'8px 10px', display:'flex', alignItems:'center', gap:8, background:C.paper}}>
          <span style={{fontFamily:F.mono, fontSize:11, color:C.tx3}}>›</span>
          <input value={q} onChange={e=>setQ(e.target.value)} style={{flex:1, border:'none', outline:'none', fontFamily:F.mono, fontSize:11, background:'transparent', color:C.tx}}/>
          <Btn kind="primary" sm onClick={()=>wf.run({query:q, context:{}}).catch(()=>{})}>{wf.solving?'…':'Parse'}</Btn>
        </div>
        <div style={{marginTop:8, display:'flex', flexWrap:'wrap', gap:5}}>
          {M.whatif.map((w,i)=><span key={i} onClick={()=>setQ(w)} style={{fontFamily:F.mono, fontSize:9, padding:'3px 7px', border:`1.5px solid ${C.line2}`, color:C.tx2, cursor:'pointer'}}>{w}</span>)}
        </div>
        {wf.error && <div style={{fontFamily:F.mono, fontSize:10, color:C.dg, marginTop:8}}>⚠ {wf.error}</div>}
        {res && <div style={{marginTop:10}}>
          <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx, marginBottom:6}}>{res.interpretation}</div>
          <DataTable dense cols={['Parameter','Change','Why']} align={['left','left','left']}
            rows={(res.changes||[]).map(c=>[c.param, c.change, c.reason])}/>
          <div style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color:C.tx3, lineHeight:1.5}}>{res.impact}</div>
        </div>}
      </Card>
      <Card icon="📋" title="Multi-SKU Comparison" badge="derived" badgeTone="g" span={2}
        right={<Provenance kind="derived"/>}
        info={{ what:'Side-by-side SKU economics derived from the product master + committed demand.', flows:'Portfolio view.' }}
        dev={{ comp:'MultiSKU', props:'M.products + committed demand' }}>
        <DataTable dense cols={['SKU','ABC/XYZ','Committed/yr','Margin %','Service','Fill']} align={['left','left','right','right','right','right']}
          rows={M.products.filter(p=>p.cat==='Finished').map(p=>{ const cy=getItemDemand(p.sku,12).reduce((a,b)=>a+b,0);
            return [p.sku, `${p.abc}${p.xyz}`, cy.toLocaleString('en-IN'), `${Math.round((1-p.cost/p.price)*100)}%`, `${p.sl}%`, p.abc==='A'?'100%':p.abc==='B'?'94%':'88%'];
          })}/>
      </Card>
    </Grid>
  );
}
// ════════════════════════════════════════════════════════════════════════
// W10 · S&OP COCKPIT — executive rollup of every cached solve on ONE model.
// Reads the cross-stage solve cache (solveResults) — the SAME real outputs the
// owning tabs show — into one board: committed demand → plan → schedule → line
// capital → risk → pooling, with a single "re-plan the planning spine" action and
// the live control-tower count. Honest "—" for any stage not yet solved.
// ════════════════════════════════════════════════════════════════════════
const _L = v => (v==null||isNaN(v)) ? '—' : '₹'+(v/1e5).toFixed(2)+'L';
const _N = v => (v==null||isNaN(v)) ? '—' : Math.round(v).toLocaleString('en-IN');
function _R(sr,key){ const e=sr[key]; return e ? e.result : null; }
// ── D2 · VALUE LEDGER ────────────────────────────────────────────────────────
// The renewal/expansion weapon: a tool that MEASURES ITS OWN ROI. Everything here
// is real — decisions counted from the immutable event log, ₹ value read from the
// cached solves that surfaced it. It deliberately separates value IDENTIFIED (a
// solve found it) from recommendations ACCEPTED (applied/merged into the committed
// plan, per the event log). No invented "₹X saved" — every figure traces to a
// solve or a logged event, with provenance shown.
function ValueLedger(){
  const { state:sr } = useStore(s=>s.solveResults||{});
  const { events } = useEvents();
  const evs = events||[];
  const cnt = t => evs.filter(e=>e.type===t).length;
  const explored = cnt('scenario_create')+cnt('scenario_branch');
  const applied  = cnt('scenario_apply')+cnt('scenario_merge')+cnt('scenario_eva_prune')+cnt('scenario_merge_fields');
  const replans  = cnt('replan')+cnt('scenario_run');
  const sensed   = cnt('actuals')+cnt('import')+cnt('npi_likemodel')+cnt('auto_trigger')+cnt('trigger');
  const sinceTs  = evs.length ? evs[0].ts : null;
  const acceptPct = explored>0 ? Math.round(applied/explored*100) : null;

  // ₹ value SURFACED — read only from solves that are actually cached
  const mn=_R(sr,'meionet'), lc=_R(sr,'linecap'), mc=_R(sr,'montecarlo');
  const dividend  = mn && mn.total_annual_dividend!=null ? mn.total_annual_dividend : null;
  const capFreed  = mn && mn.total_capital_freed!=null ? mn.total_capital_freed : null;
  const shadowMax = lc && lc.lines ? Math.max(0,...lc.lines.map(x=>+x.shadow_price||0)) : null;
  const bindN     = lc && lc.lines ? lc.lines.filter(x=>x.binding).length : null;
  const tailGap   = mc && mc.cvar95!=null && mc.avg_cost!=null ? (mc.cvar95-mc.avg_cost) : null;

  // only surface value a solve ACTUALLY found (>0) — a ₹0 pooling result means
  // "nothing to pool", an honest non-event, not a line in the ROI ledger.
  const rows = [];
  if(dividend!=null && dividend>0)   rows.push({ src:'Risk pooling (MEIO)', what:'Safety-stock holding freed by central buffers', amt:`₹${_N(dividend)}/yr`, prov:'meio-network solve' });
  if(capFreed!=null && capFreed>0)   rows.push({ src:'Risk pooling (MEIO)', what:'Working capital released (one-time)',           amt:`₹${_N(capFreed)}`,    prov:'meio-network solve' });
  if(shadowMax!=null && shadowMax>0) rows.push({ src:'Line capacity',       what:`Worth of relieving the binding line${bindN>1?'s':''}`, amt:`₹${Math.round(shadowMax)}/unit`, prov:'linecap dual' });
  if(tailGap!=null && tailGap>0)     rows.push({ src:'Risk (Monte Carlo)',  what:'Cost-tail exposure the plan now quantifies',       amt:`₹${_N(tailGap)}`,     prov:'montecarlo CVaR95−mean' });

  const annualSurfaced = (dividend!=null && dividend>0) ? dividend : null;   // like-typed ₹/yr only — no dishonest blended total

  return (
    <Card icon="📈" title="Value Ledger — what the platform has returned" span={2}
      badge={evs.length?`${_N(evs.length)} decisions logged`:'no activity yet'} badgeTone={evs.length?'g':'k'}
      right={<Provenance kind={evs.length?'solved':'derived'} note="event log + solves"/>}
      info={{ what:'The tool measuring its OWN ROI — decisions taken (immutable event log) and ₹ value surfaced (cached solves). Separates value IDENTIFIED by a solve from recommendations ACCEPTED into the committed plan. No invented totals.', flows:'The renewal / expansion business case.' }}
      dev={{ comp:'ValueLedger (D2)', props:'events[] · solveResults cache' }}>
      <KpiRow cols={4}>
        <Blk label="Decisions logged" value={evs.length?_N(evs.length):'—'} sub={sinceTs?`first ${_ago(sinceTs)}`:'no events'} tone={evs.length?'c':'k'}/>
        <Blk label="Scenarios explored" value={_N(explored)} sub={`${replans} re-plans · ${sensed} sensed`}/>
        <Blk label="Recommendations applied" value={_N(applied)} sub={acceptPct!=null?`${acceptPct}% of explored`:'none applied yet'} tone={applied?'g':'k'} accent={applied?C.gn:undefined}/>
        <Blk label="Annual value surfaced" value={annualSurfaced!=null?`₹${_N(annualSurfaced)}/yr`:'—'} sub={annualSurfaced!=null?'pooling dividend':'run the loop'} tone={annualSurfaced!=null?'g':'k'}/>
      </KpiRow>

      <div style={{marginTop:10}}><SubLabel>Value identified by the platform (each traced to a solve)</SubLabel></div>
      {rows.length>0 ? (
        <DataTable dense cols={['Source','What','Amount','From']} align={['left','left','right','left']}
          rows={rows.map(r=>[r.src, r.what, r.amt, <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>{r.prov}</span>])}/>
      ) : (
        <div style={{padding:'9px 11px', border:`2px dashed ${C.line2}`, fontFamily:F.mono, fontSize:10.5, color:C.tx3}}>
          No solved value surfaced yet — run the end-to-end loop (or the pooling, line-capacity and risk solves) and the ₹ opportunities each one finds appear here, each traceable to its solve.
        </div>
      )}

      <Reading tone={applied?C.gn:(evs.length?C.a4:C.tx3)}
        formula={`${_N(evs.length)} decisions · ${explored} scenarios explored · ${applied} applied${acceptPct!=null?` (${acceptPct}%)`:''}${annualSurfaced!=null?` · ₹${_N(annualSurfaced)}/yr surfaced`:''}`}
        soWhat={evs.length
          ? `Value the platform has SURFACED and decisions it has RECORDED — traced to solves and the audit log, not a claim of cash banked. ${applied} recommendation(s) have been promoted into the committed plan. This is the evidence a renewal conversation runs on: decision throughput, acceptance rate, and identified ₹ — all from real solves.`
          : 'No decisions logged yet. As you run solves, branch scenarios and apply recommendations, the ledger accrues the audit trail and the ₹ value each solve surfaced — the ROI case for the tool.'}/>
    </Card>
  );
}

// (R13) ScnCockpit REMOVED — the S&OP cockpit board, the D8 ExceptionCockpit and
// the D2 ValueLedger now live on Home (the "is my plan current & healthy?" surface).
// ExceptionCockpit + ValueLedger remain defined above and are rendered from Home.

// ════════════════════════════════════════════════════════════════════════
// W10/W11 · SCENARIOS — branch · run (concurrent what-if) · compare · merge.
// Each scenario is a snapshot of the input model; Run scores it through the FULL
// loop transparently (live is byte-restored after), so branches are compared on
// REAL solved KPIs without disturbing each other. The What-If bot clones the base,
// perturbs governed levers (demand %, material cost %, service level), runs the
// AFFECTED solvers via the loop, and reports the KPI delta — "rerun affected
// solvers on a what-if." Merge promotes a branch to the working set (audit-logged).
// ════════════════════════════════════════════════════════════════════════
const _KPI_ROWS = [
  { k:'planCost',     label:'Plan cost',        fmt:_L, better:'lo' },
  { k:'prodUnits',    label:'Scheduled units',  fmt:_N, better:'hi' },
  { k:'avgRunUnits',  label:'Avg run (units)',  fmt:_N, better:'hi' },
  { k:'bindingLines', label:'Binding lines',    fmt:v=>v==null?'—':String(v), better:'lo' },
  { k:'mcMeanCost',   label:'Risk mean cost',   fmt:_L, better:'lo' },
  { k:'cvar95',       label:'Risk CVaR95',      fmt:_L, better:'lo' },
  { k:'avgFill',      label:'Mean fill %',      fmt:v=>v==null?'—':v+'%', better:'hi' },
];
// ════════════════════════════════════════════════════════════════════════
// HARNESS-2 · DISRUPTION SUB-FLOW RUNNER — the BEHAVIORAL regression test
// ────────────────────────────────────────────────────────────────────────
// HARNESS-1 (tools/model_check.js) proves the app PARSES and its endpoints
// EXIST — a static check. HARNESS-2 proves the app BEHAVES: that perturbing one
// real planning lever moves the right KPI in the right DIRECTION through the
// actual solve chain. It can only live in-app because it needs the byte-restored
// runScenario re-solve loop (the same concurrent what-if the Scenarios tab runs),
// not a node script. Each sub-flow: solve the live base once → clone it → perturb
// ONE lever in the clone's input snapshot → runScenario (full loop; live restored
// after) → assert the KPI direction vs the base → delete the clone — all QUIET, so
// these throwaway runs never touch the audit log or the ValueLedger's ROI count.
// Verdicts are HONEST: PASS (moved as expected) · FLAT (didn't move ≥½% — a wiring
// smell) · FAIL (moved the WRONG way — a model bug) · ERR (threw / KPI absent).
// Levers traced to their solver (2026-06-06):
//   demand → getItemDemand → loop aggregate            ⇒ planCost = ag.total_cost
//   dutyFreightPct + fxRates.USD → effLandedCost
//                → partsWithSourcing → loop procurement ⇒ procCost = pc.total
//   prodArch.lines[].cap → linecapPayload → loop linecap ⇒ lineShadowMax (B-5, 2026-06-06)
const _SUBFLOWS = [
  { id:'SF-1', name:'OEM ramp', lever:'4471+3215 demand ×1.4', kpi:'planCost', dir:'up',
    why:'two A-class OEM programmes surge → more to build → aggregate plan cost rises',
    xf:(inp)=>{ const dem={ ...(inp.demand||{}) }; const pins={ ...(inp.demandPinned||{}) };
      ['TPA-4471','TPA-3215'].forEach(s=>{ const b=(dem[s]&&dem[s].length)?dem[s]:getItemDemand(s,52);
        dem[s]=b.map(v=>Math.max(0,Math.round(v*1.4))); pins[s]=true; });   // V5-2b pin — else loop re-forecast undoes the lever
      inp.demand=dem; inp.demandPinned=pins; return inp; } },
  { id:'SF-5', name:'Demand collapse', lever:'all FG ×0.6', kpi:'planCost', dir:'down',
    why:'downturn — every finished good ×0.6 → less to build → aggregate plan cost falls',
    xf:(inp)=>{ const dem={ ...(inp.demand||{}) }; const pins={ ...(inp.demandPinned||{}) };
      (M.products||[]).filter(p=>p.cat==='Finished').forEach(p=>{ const b=(dem[p.sku]&&dem[p.sku].length)?dem[p.sku]:getItemDemand(p.sku,52);
        dem[p.sku]=b.map(v=>Math.max(0,Math.round(v*0.6))); pins[p.sku]=true; });   // V5-2b pin
      inp.demand=dem; inp.demandPinned=pins; return inp; } },
  { id:'SF-4', name:'Commodity spike', lever:'parts landed +20%', kpi:'procCost', dir:'up',
    why:'duty+freight uplift compounds +20% on every part → higher landed cost → procurement spend rises',
    xf:(inp)=>{ const src={ ...(inp.sourcing||{}) };
      (M.bom||[]).forEach(b=>{ const cur=getSourcing(b.part,b); const oldPct=Number(cur.dutyFreightPct)||0;
        const newPct=((1+oldPct/100)*1.2-1)*100;
        src[b.part]={ ...(src[b.part]||{}), imported:cur.imported, dutyFreightPct:Math.round(newPct*10)/10 }; });
      inp.sourcing=src; return inp; } },
  { id:'SF-2', name:'FX shock', lever:'USD/₹ +₹5', kpi:'procCost', dir:'up',
    why:'rupee weakens ₹5/$ → imported parts (RM-BRG18) re-price up in ₹ → procurement spend rises',
    xf:(inp)=>{ const cfg={ ...(inp.config||{}) }; const fx={ ...(cfg.fxRates||{}) };
      fx.USD=Math.round(((Number(fx.USD)||84.2)+5)*100)/100; cfg.fxRates=fx; inp.config=cfg; return inp; } },
  { id:'SF-7', name:'Capacity loss', lever:'all lines cap ×0.1', kpi:'lineShadowMax', dir:'up',
    why:"lines crippled (×0.1 registry cap) cross from slack into BINDING → the ₹ line-capacity dual rises off ₹0. At real TPAC volumes capacity is honestly slack (linecap returns ₹0), so the cut is deliberately deep — this confirms prodArch is now a LIVE, byte-restorable scenario lever reaching linecap (B-5), NOT that ₹0 was wrong. (Production is unaffected — it sizes capacity off OEE/hours, not this units field; only linecap reads cap.)",
    xf:(inp)=>{ const pa=inp.prodArch||{};
      const lines=(pa.lines||[]).map(l=>({ ...l, cap:Math.max(1, Math.round((Number(l.cap)||0)*0.1)) }));
      inp.prodArch={ ...pa, lines }; return inp; } },
];
// Honest coverage gaps — sub-flows that CANNOT be byte-restored / asserted yet.
const _BLOCKED_SF = [
  { id:'SF-3', name:'Supplier aging',    why:'a finance-only effect (DSO / working capital) — no committed-plan loop KPI to assert on' },
  { id:'SF-6', name:'Lead-time stretch', why:'couples demand + risk KPIs — exercised via Risk ▸ stress-to-failure instead' },
];
const _SF_TONE = { PASS:C.gn, FAIL:C.dg, ERR:C.dg, FLAT:C.hl };
const _SF_EPS = 0.005;   // ½% — a move below this reads as FLAT (no real direction)
function _sfVerdict(base, val, dir){
  if(base==null || val==null) return { tag:'ERR', why:'a required KPI was null — the solve was absent' };
  if(base===0) return val>0 ? { tag:(dir==='up'?'PASS':'FAIL'), why:'base was 0' } : { tag:'FLAT', why:'base was 0 and it stayed 0' };
  const rel = (val-base)/Math.abs(base);
  if(Math.abs(rel) < _SF_EPS) return { tag:'FLAT', why:'the lever did not move the KPI (within ½%) — check the wiring' };
  return ((rel>0?'up':'down')===dir) ? { tag:'PASS', why:'' } : { tag:'FAIL', why:'moved the WRONG way — a model bug' };
}
function SubflowHarness(){
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(null);
  const [rows, setRows] = useState([]);
  const [msg, setMsg]   = useState(null);

  const run = async ()=>{
    setBusy(true); setMsg(null); setRows([]);
    try{
      // 1 · baseline — solve the LIVE inputs once (transparent; restored after). QUIET.
      setStep('baseline');
      const baseId = captureScenario('▸ harness baseline', '', true);
      let bk;
      try{ ({ kpis: bk } = await runScenario(baseId, { quiet:true })); }
      finally{ deleteScenario(baseId, true); }
      if(bk.planCost==null && bk.procCost==null){
        setMsg('⚠ Baseline solve returned no plan/proc cost — is the server up? Run the Loop tab once, then retry.');
        setBusy(false); setStep(null); return;
      }
      // 2 · each sub-flow — clone → perturb ONE lever → run → assert direction → delete. QUIET.
      const out = [];
      for(const sf of _SUBFLOWS){
        setStep(sf.id);
        let kpis=null, err=null;
        const id = captureScenario('▸ '+sf.id+' '+sf.name, '', true);
        try{ updateScenarioInputs(id, sf.xf); ({ kpis } = await runScenario(id, { quiet:true })); }
        catch(e){ err = e.message||String(e); }
        finally{ deleteScenario(id, true); }
        const b = bk[sf.kpi], v = kpis ? kpis[sf.kpi] : null;
        const verdict = err ? { tag:'ERR', why:err } : _sfVerdict(b, v, sf.dir);
        out.push({ ...sf, base:b, val:v, verdict }); setRows([...out]);
      }
      const np = out.filter(r=>r.verdict.tag==='PASS').length;
      // ONE honest audit line — NOT a scenario_* event, so the ValueLedger stays truthful.
      try{ if(typeof logEvent==='function') logEvent('harness_run', null, { pass:np, total:out.length }); }catch(e){}
      setMsg(`${np}/${out.length} sub-flows passed — live working set restored, base untouched.`);
    }catch(e){ setMsg('⚠ '+(e.message||String(e))); }
    finally{ setBusy(false); setStep(null); }
  };

  const npass  = rows.filter(r=>r.verdict.tag==='PASS').length;
  const anyBad = rows.some(r=>['FAIL','ERR','FLAT'].includes(r.verdict.tag));

  return (
    <Card icon="🧪" title="Sub-flow harness — does the model BEHAVE?" span={2}
      badge={rows.length?`${npass}/${rows.length} pass`:'HARNESS-2'} badgeTone={rows.length?(anyBad?'k':'y'):'k'}
      info={{ what:"A behavioral regression test: each row perturbs ONE real lever and asserts the right KPI moves the right DIRECTION through the actual solve chain (not a parser). Runs are transparent — the live working set is byte-restored after each, and QUIET (no audit / ValueLedger pollution). HARNESS-1 checks the app parses; this checks it behaves.", flows:'Run → read PASS / FLAT / FAIL per disruption.' }}
      dev={{ comp:'SubflowHarness (HARNESS-2)', props:'captureScenario(quiet) → updateScenarioInputs → runScenario(quiet) → assert → deleteScenario(quiet)', note:'DIRECTION §4B — 4 runnable sub-flows; 3 honest coverage gaps below.' }}
      right={<Btn kind="primary" sm onClick={run}>{busy?(step?`Solving ${step}…`:'Solving…'):'▶ Run harness'}</Btn>}>
      <div style={{overflowX:'auto'}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontSize:10.5}}>
          <thead><tr>
            {['Sub-flow','Lever','KPI','Expect','Base','Perturbed','Verdict'].map((h,i)=>(
              <th key={i} style={{textAlign:i>3?'right':'left', padding:'5px 8px', fontFamily:F.mono, fontSize:9, color:C.tx3, borderBottom:`2px solid ${C.line}`}}>{h}</th>))}
          </tr></thead>
          <tbody>
            {_SUBFLOWS.map(sf=>{ const r = rows.find(x=>x.id===sf.id);
              const v = r?r.verdict:null; const fmt = (sf.kpi==='planCost'||sf.kpi==='procCost') ? _L : _N;
              return (<tr key={sf.id} title={(v&&v.why)?v.why:sf.why}>
                <td style={{padding:'4px 8px', fontFamily:F.body, fontWeight:700, fontSize:10.5}}>{sf.id} <span style={{color:C.tx2, fontWeight:400}}>{sf.name}</span></td>
                <td style={{padding:'4px 8px', fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>{sf.lever}</td>
                <td style={{padding:'4px 8px', fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>{sf.kpi}</td>
                <td style={{padding:'4px 8px', fontFamily:F.mono, fontSize:11, color:C.tx2}}>{sf.dir==='up'?'↑':'↓'}</td>
                <td style={{padding:'4px 8px', textAlign:'right', fontFamily:F.mono, fontSize:10}}>{r?fmt(r.base):'—'}</td>
                <td style={{padding:'4px 8px', textAlign:'right', fontFamily:F.mono, fontSize:10}}>{r?fmt(r.val):'—'}</td>
                <td style={{padding:'4px 8px', textAlign:'right', fontFamily:F.disp, fontSize:10, fontWeight:700, color: v?(_SF_TONE[v.tag]||C.tx):C.tx3}}>{v?v.tag:'—'}</td>
              </tr>);
            })}
          </tbody>
        </table>
      </div>
      {msg && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10.5, color: msg[0]==='⚠'?C.dg:C.tx, lineHeight:1.5, border:`2px solid ${C.line}`, padding:'8px 10px', background:C.paper}}>{msg}</div>}

      <div style={{marginTop:10}}><SubLabel>Honest coverage gaps — not runnable yet</SubLabel></div>
      <div style={{display:'flex', flexDirection:'column', gap:4, marginTop:5}}>
        {_BLOCKED_SF.map(b=>(
          <div key={b.id} style={{display:'flex', gap:8, alignItems:'baseline', fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>
            <span style={{fontFamily:F.body, fontWeight:700, color:C.tx2, minWidth:118}}>{b.id} {b.name}</span>
            <span style={{flex:1}}>{b.why}</span>
          </div>))}
      </div>

      <Reading tone={anyBad?C.dg:(rows.length?C.gn:C.tx3)}
        formula="per sub-flow: clone live → perturb one lever → run the full loop on the clone → assert the KPI direction vs base"
        soWhat={rows.length
          ? `${npass}/${rows.length} disruptions moved the right KPI the right way through a REAL re-solve. FLAT = the lever didn't reach the solver (a wiring smell); FAIL = it moved the wrong way (a model bug). The base never moved — every run was byte-restored.`
          : "Run the harness to prove each disruption flows through the solver and moves the plan the way it should — the behavioral complement to HARNESS-1's static parse/endpoint check."}/>
    </Card>
  );
}
function ScnScenarios({ onNav }){
  const { planning } = usePlanning();
  const sc = useScenarios();
  const order = sc.order||[]; const list = sc.list||{};
  const [busy, setBusy]   = useState(null);     // scenario id currently running
  const [name, setName]   = useState('');
  const [allBusy, setAllBusy] = useState(false);   // V5-2 — server fan-out in flight
  const [srvMeta, setSrvMeta] = useState(null);    // V5-2 — last fan-out timing/meta
  // what-if levers
  const [demPct, setDemPct] = useState('');
  const [costPct, setCostPct] = useState('');
  const [sl, setSl] = useState('');
  const [wifBusy, setWifBusy] = useState(false);
  const [wifMsg, setWifMsg] = useState(null);
  const baseKpis = _captureKpis();             // live working set, for the base column

  const doRun = async (id)=>{ setBusy(id);
    try{ await runScenario(id); } catch(e){ /* surfaced via row */ } finally{ setBusy(null); } };
  const doCapture = ()=>{ const id = captureScenario(name||undefined); setName(''); };
  // V5-2 — score EVERY branch in one server-side concurrent fan-out (3 batched
  // phases, ThreadPool on the backend) instead of N sequential full-loop runs.
  const doRunAll = async ()=>{ setAllBusy(true); setSrvMeta(null);
    try{ setSrvMeta(await runScenariosServer(order)); }
    catch(e){ setSrvMeta({ error: e.message||String(e) }); }
    finally{ setAllBusy(false); } };

  // What-If bot — clone the live base, perturb the governed levers in its input
  // snapshot, run the affected solvers (the loop), surface the KPI delta.
  const runWhatIf = async ()=>{
    setWifBusy(true); setWifMsg(null);
    try{
      const dp = demPct===''?0:Number(demPct), cp = costPct===''?0:Number(costPct), s = sl===''?null:Number(sl);
      const parts = [];
      if(dp) parts.push(`demand ${dp>0?'+':''}${dp}%`);
      if(cp) parts.push(`material cost ${cp>0?'+':''}${cp}%`);
      if(s!=null) parts.push(`service ${(s*100).toFixed(0)}%`);
      const label = `What-if: ${parts.length?parts.join(', '):'no change'}`;
      const id = captureScenario(label);
      updateScenarioInputs(id, (inputs)=>{
        // demand %: seed each FG series from live committed demand, then scale.
        if(dp){ const dem = { ...(inputs.demand||{}) }; const pins = { ...(inputs.demandPinned||{}) };
          (M.products||[]).filter(p=>p.cat==='Finished').forEach(p=>{
            const base = (dem[p.sku] && dem[p.sku].length) ? dem[p.sku] : getItemDemand(p.sku, 52);
            dem[p.sku] = base.map(v=>Math.max(0, Math.round(v*(1+dp/100))));
            pins[p.sku] = true;   // V5-2b — without the pin, the loop's re-forecast silently undid this lever
          });
          inputs.demand = dem; inputs.demandPinned = pins; }
        // material cost %: lift every part's landed multiplier (dutyFreightPct) so the
        // procurement MILP + the MC cost shocks both plan on the higher landed cost.
        if(cp){ const src = { ...(inputs.sourcing||{}) };
          (M.bom||[]).forEach(b=>{
            const cur = getSourcing(b.part, b); const oldPct = Number(cur.dutyFreightPct)||0;
            const newPct = ((1+oldPct/100)*(1+cp/100) - 1)*100;
            src[b.part] = { ...(src[b.part]||{}), dutyFreightPct: Math.round(newPct*10)/10 };
          });
          inputs.sourcing = src; }
        if(s!=null){ inputs.config = { ...(inputs.config||{}), serviceLevel: s }; }
        return inputs;
      });
      setBusy(id);
      const { kpis } = await runScenario(id);
      const d = (a,b)=> (a==null||b==null)?null : a-b;
      setWifMsg(`Scored "${label}" — plan cost ${_L(kpis.planCost)} (Δ ${_dl(d(kpis.planCost,baseKpis.planCost))}), CVaR95 ${_L(kpis.cvar95)} (Δ ${_dl(d(kpis.cvar95,baseKpis.cvar95))}), fill ${kpis.avgFill!=null?kpis.avgFill+'%':'—'}.`);
    }catch(e){ setWifMsg('⚠ '+(e.message||String(e))); }
    finally{ setWifBusy(false); setBusy(null); }
  };

  // compare columns: base (live) + every captured scenario
  const cols = [{ id:'base', name:'Base (live)', kpis:baseKpis, ranAt:'live', active:sc.active==='base' }]
    .concat(order.map(id=>({ id, name:list[id].name, kpis:list[id].kpis, ranAt:list[id].ranAt, active:sc.active===id, note:list[id].note })));

  return (
    <Grid cols={2}>
      {/* manage + compare */}
      <Card icon="🌿" title="Scenario branches — compare on real solved KPIs" span={2}
        badge={`${order.length} saved`} badgeTone={order.length?'g':'k'}
        right={<div style={{display:'flex', gap:6, alignItems:'center'}}>
          <input value={name} onChange={e=>setName(e.target.value)} placeholder="name…" style={{border:`2px solid ${C.line}`, padding:'4px 7px', fontFamily:F.mono, fontSize:10, width:120, outline:'none'}}/>
          <Btn kind="secondary" sm onClick={doCapture}>+ Capture live</Btn>
          {order.length>0 && <Btn kind="primary" sm onClick={()=>{ if(!allBusy) doRunAll(); }}>{allBusy?'… fanning out':'⚡ Run all (server)'}</Btn>}
        </div>}
        info={{ what:'Each branch is a snapshot of the input model. "Run" scores it through the full loop transparently — live is restored after, so branches are compared on REAL solved numbers without disturbing each other (Kinaxis-style concurrent planning). "⚡ Run all" scores EVERY branch in one server-side concurrent fan-out (a thread pool solves the branches in parallel — CBC runs as subprocesses). "Apply" switches the working set to a branch; "Merge" promotes it.', flows:'Branch → run (or ⚡ run all) → compare → merge.' }}
        dev={{ comp:'ScnScenarios', props:'useScenarios() · runScenario/runScenariosServer/branch/merge', note:'W10/W11 — store.jsx §4½ scenario engine · V5-2 /api/solve/branches fan-out.' }}>
        {order.length===0 ? <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'10px 0'}}>
          No branches yet. <b>Capture live</b> to pin the current inputs as a base, then branch + edit a tab (or use the What-If bot below) to create alternatives, and Run each to compare.
        </div> : (
          <div style={{overflowX:'auto'}}>
            <table style={{borderCollapse:'collapse', width:'100%', fontSize:10.5}}>
              <thead><tr>
                <th style={{textAlign:'left', padding:'5px 8px', fontFamily:F.mono, fontSize:9, color:C.tx3, borderBottom:`2px solid ${C.line}`}}>KPI</th>
                {cols.map(c=>(<th key={c.id} style={{textAlign:'right', padding:'5px 8px', fontFamily:F.disp, fontSize:10, borderBottom:`2px solid ${C.line}`, borderLeft:`1px solid ${C.line}`, color:c.active?C.ac:C.tx}}>
                  {c.name}{c.active?' ●':''}<div style={{fontFamily:F.mono, fontSize:8, color:C.tx3, fontWeight:400}}>{c.ranAt?(c.ranAt==='live'?'live':'scored'):'not run'}</div>
                </th>))}
              </tr></thead>
              <tbody>
                {_KPI_ROWS.map(row=>{
                  const baseV = baseKpis[row.k];
                  return (<tr key={row.k}>
                    <td style={{textAlign:'left', padding:'4px 8px', fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>{row.label}</td>
                    {cols.map(c=>{ const v = c.kpis ? c.kpis[row.k] : null;
                      let dcol = C.tx;
                      if(c.id!=='base' && v!=null && baseV!=null && v!==baseV){
                        const better = row.better==='lo' ? v<baseV : v>baseV; dcol = better?C.gn:C.dg; }
                      return <td key={c.id} style={{textAlign:'right', padding:'4px 8px', fontFamily:F.mono, fontSize:10, borderLeft:`1px solid ${C.line}`, color:dcol, fontWeight:dcol!==C.tx?700:400}}>{c.kpis?row.fmt(v):'—'}</td>;
                    })}
                  </tr>);
                })}
              </tbody>
            </table>
          </div>
        )}
        {order.length>0 && <div style={{marginTop:10, display:'flex', flexDirection:'column', gap:5}}>
          {order.map(id=>{ const s=list[id];
            return (<div key={id} style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${C.line}`, borderLeft:`5px solid ${sc.active===id?C.ac:C.line2}`, padding:'6px 9px'}}>
              <span style={{flex:1, minWidth:0}}>
                <span style={{fontFamily:F.body, fontSize:11.5, fontWeight:700}}>{s.name}</span>
                {s.parent && <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, marginLeft:6}}>↳ from {list[s.parent]?list[s.parent].name:'?'}</span>}
                <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, marginLeft:6}}>{s.ranAt?('scored '+_ago(s.ranAt)):'not scored'}</span>
              </span>
              <Btn kind="secondary" sm onClick={()=>doRun(id)}>{busy===id?'…':'▶ Run'}</Btn>
              <Btn kind="secondary" sm onClick={()=>branchScenario(id)}>⑂ Branch</Btn>
              <Btn kind="secondary" sm onClick={()=>{ mergeScenario(id); }}>Merge</Btn>
              <span onClick={()=>deleteScenario(id)} style={{cursor:'pointer', fontFamily:F.mono, fontSize:12, color:C.tx3, padding:'0 4px'}} title="delete">✕</span>
            </div>);
          })}
        </div>}
        {srvMeta && (()=>{ // V5-2 — honest fan-out telemetry: what ran where, how concurrent, what failed
          if(srvMeta.error) return <div data-vis="v5-branches" style={{marginTop:8, border:`2px solid ${C.dg}`, padding:'7px 10px', fontFamily:F.mono, fontSize:9.5, color:C.dg}}>⚠ SERVER FAN-OUT failed — {srvMeta.error}</div>;
          const n = Object.keys(srvMeta.scenarios||{}).length;
          const fails = Object.values(srvMeta.scenarios||{}).reduce((a,s)=>a+(s.log||[]).filter(x=>!x.ok).length,0);
          return <div data-vis="v5-branches" style={{marginTop:8, border:`2px solid ${C.line}`, borderLeft:`5px solid ${fails?C.hl:C.gn}`, padding:'7px 10px', fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.7}}>
            <b style={{color:C.tx}}>SERVER FAN-OUT</b> — {n} branch{n===1?'':'es'} × {LOOP_STEPS.length} steps = {n*LOOP_STEPS.length} solves in 3 batched phases (forecast → procurement∥aggregate∥production → linecap∥MC) ·
            wall <b style={{color:C.tx}}>{(srvMeta.wallMs/1000).toFixed(1)}s</b> vs {(srvMeta.solverMs/1000).toFixed(1)}s solver time on the pool{srvMeta.speedup!=null?<> · <b style={{color:C.gn}}>{srvMeta.speedup}× concurrent</b></>:null}
            <span style={{color:C.tx3}}> · phases {(srvMeta.phases||[]).map((m,i)=>m?`${i+1}:${m.jobs}j ${(m.wall_ms/1000).toFixed(1)}s`:'').join(' · ')}</span>
            {fails>0 ? <span style={{color:C.hl}}> · ⚠ {fails} step{fails===1?'':'s'} failed (isolated per branch — that branch's KPI row shows what's missing)</span>
                     : <span style={{color:C.gn}}> · all steps OK</span>}
          </div>; })()}
        {order.length>0 && <Reading tone={C.gn}
          formula="each column = the full loop solved on that branch's inputs; green = better than base on that KPI (cost ↓ / fill ↑)"
          soWhat="Branches are scored concurrently — running one restores live afterward, so the base column never moves while you explore. Merge promotes a winner to the working set (logged to the audit trail)."/>}
      </Card>

      {/* What-If bot — perturb levers, run affected solvers, show the delta */}
      <Card icon="🤖" title="What-If bot — perturb & re-solve" span={2} badge="solves" badgeTone="g"
        info={{ what:'Clones the live base, applies the lever changes to its input snapshot, and RUNS the affected solvers (procurement → schedule → line dual → risk) on the clone — then shows the KPI delta vs base. Unlike the Explore-tab parser, this one actually re-solves.', flows:'Stress a lever → see cost/fill move → keep the branch or discard.' }}
        dev={{ comp:'WhatIfBot', props:'captureScenario → updateScenarioInputs → runScenario', note:'W10 — rerun affected solvers on a what-if (real solve, transparent to live).' }}>
        <div style={{display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end', marginBottom:8}}>
          <SolverInput label="Demand shock %" seed={0} value={demPct} onChange={setDemPct} min={-50} max={100} w={108} hint="scale committed demand"/>
          <SolverInput label="Material cost %" seed={0} value={costPct} onChange={setCostPct} min={-30} max={80} w={108} hint="lift landed cost"/>
          <SolverInput label="Service level" seed={0.95} value={sl} onChange={setSl} min={0.8} max={0.999} w={100} hint="target α"/>
          <div style={{flex:1}}/>
          <Btn kind="primary" sm onClick={runWhatIf}>{wifBusy?'Solving…':'▶ Run what-if'}</Btn>
        </div>
        {wifMsg && <div style={{fontFamily:F.mono, fontSize:10.5, color: wifMsg[0]==='⚠'?C.dg:C.tx, lineHeight:1.5, border:`2px solid ${C.line}`, padding:'8px 10px', background:C.paper}}>{wifMsg}</div>}
        {!wifMsg && <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx3, padding:'4px 0'}}>Set one or more levers and run — the bot creates a scored branch (it appears in the table above) and reports the cost/fill delta vs base.</div>}
        <Reading formula="clone base → apply levers to inputs → run loop on the clone → Δ vs base"
          soWhat="A real re-solve, not a parser: the demand/cost/service change flows through the same payload builders the tabs use, so the delta is the plan's actual sensitivity to that shock."/>
      </Card>

      {/* HARNESS-2 — behavioral sub-flow regression (does the model behave?) */}
      <SubflowHarness/>

      {/* Event-sourced replay + version diff/merge (W11 · Platform L4 depth) */}
      <ScnVersions sc={sc}/>

      {/* D5 — Excel round-trip model surface */}
      <ModelSurface/>
    </Grid>
  );
}
function _dl(v){ return (v==null||isNaN(v)) ? '—' : (v>=0?'+':'−')+'₹'+(Math.abs(v)/1e5).toFixed(2)+'L'; }

// ── D5 · EXCEL ROUND-TRIP MODEL SURFACE ───────────────────────────────────────
// The sharp version of "Excel config": not a dead XLSX dump, but a round-trip model
// surface — export the editable input envelope (per-SKU committed-demand totals +
// governed config scalars) as a spreadsheet, edit it in Excel, re-import, DIFF the
// change field-by-field, then APPLY + re-solve. The diff is the same field set the
// version-merge reasons over. Honest format: CSV (Excel opens it natively) — we don't
// claim a native .xlsx writer we don't have. Demand edits scale the series
// proportionally (seasonality preserved); a stated assumption, shown in-card.
function _parseSurfaceCsv(text){
  const env = { demand:{}, config:{} };
  const lines = String(text||'').split(/\r?\n/).map(l=>l.trim()).filter(l=>l.length);
  let n = 0;
  lines.forEach(ln=>{
    const c = ln.split(',').map(x=>x.trim());
    if(c.length<3) return;
    if(c[0].toLowerCase()==='slice') return;   // header
    const slice=c[0], field=c[1], raw=c[2];
    if(slice!=='demand' && slice!=='config') return;
    const num = Number(String(raw).replace(/[, ]/g,''));
    env[slice][field] = (raw!=='' && isFinite(num)) ? num : raw;
    n++;
  });
  return { env, n };
}
function ModelSurface(){
  const { config, setConfig } = useConfig();
  const { planning } = usePlanning();
  const fileRef = useRef(null);
  const [paste, setPaste] = useState('');
  const [diff, setDiff] = useState(null);     // [{slice,field,live,imp}]
  const [msg, setMsg]   = useState(null);
  const [busy, setBusy] = useState(false);
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const liveTotal = sku => getItemDemand(sku,12).reduce((a,b)=>a+b,0);

  const exportCsv = ()=>{
    const lines = ['slice,field,value'];
    fin.forEach(p=> lines.push(`demand,${p.sku},${Math.round(liveTotal(p.sku))}`));
    Object.entries(config||{}).forEach(([k,v])=>{ if(v!==null && (typeof v==='number'||typeof v==='string')) lines.push(`config,${k},${v}`); });
    const csv = lines.join('\n');
    try{ const blob=new Blob([csv],{type:'text/csv'}); const url=URL.createObjectURL(blob);
      const a=document.createElement('a'); a.href=url; a.download='model_surface.csv'; document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    }catch(e){ setMsg('⚠ download blocked — copy the table below instead'); }
    if(typeof logEvent==='function') logEvent('model_export', null, { rows: lines.length-1 });
  };

  const computeDiff = (text)=>{
    const { env, n } = _parseSurfaceCsv(text);
    if(!n){ setMsg('⚠ no slice,field,value rows found — export first, edit the value column, re-import'); setDiff(null); return; }
    const rows = [];
    fin.forEach(p=>{ const imp=env.demand[p.sku]; if(imp==null) return;
      const live=Math.round(liveTotal(p.sku)); if(Math.round(imp)!==live) rows.push({ slice:'demand', field:p.sku, live, imp:Math.round(imp) }); });
    Object.entries(env.config||{}).forEach(([k,v])=>{ const live=config[k];
      if(String(live)!==String(v)) rows.push({ slice:'config', field:k, live:live==null?'—':live, imp:v }); });
    setDiff(rows); setMsg(rows.length?`${rows.length} change(s) detected`:'no changes vs the live model');
  };
  const onFile = (e)=>{ const f=e.target.files&&e.target.files[0]; if(!f) return;
    const r=new FileReader(); r.onload=()=>{ setPaste(String(r.result||'')); computeDiff(String(r.result||'')); }; r.readAsText(f); };

  const apply = async (reSolve)=>{
    if(!diff || !diff.length) return; setBusy(true);
    try{
      diff.forEach(r=>{
        if(r.slice==='demand'){ const series=getItemDemand(r.field,12); const lt=series.reduce((a,b)=>a+b,0); const tgt=Number(r.imp)||0;
          const scaled = lt>0 ? series.map(v=>v*tgt/lt) : Array(series.length).fill(tgt/series.length);
          setItemDemand(r.field, scaled, 'planner'); }   // V5-2b — pins, else the reSolve loop's re-forecast undoes the import
        else if(r.slice==='config'){ const num=Number(r.imp); setConfig({ [r.field]: (r.imp!==''&&isFinite(num))?num:r.imp }); }
      });
      if(typeof logEvent==='function') logEvent('model_import', null, { changed: diff.length, reSolve: !!reSolve });
      if(reSolve){ await runFullLoop({ planning }); }
      setMsg(`✓ applied ${diff.length} change(s)${reSolve?' and re-solved the planning spine':' — solves now stale, re-plan to refresh'}`);
      setDiff(null);
    }catch(e){ setMsg('⚠ '+(e.message||String(e))); } finally{ setBusy(false); }
  };

  return (
    <Card icon="📑" title="Excel round-trip — model surface" span={2} badge={diff?`${diff.length} change(s)`:'export ↔ edit ↔ re-import'} badgeTone={diff&&diff.length?'y':'k'}
      right={<Provenance kind="input" note="input envelope ⇄ CSV"/>}
      info={{ what:'Export the editable model (per-SKU committed-demand totals + config scalars) to a spreadsheet, edit in Excel, re-import. The change is diffed field-by-field, then applied and re-solved. Round-trip config without leaving Excel.', flows:'Export → edit in Excel → re-import → diff → apply + re-solve.' }}
      dev={{ comp:'ModelSurface (D5)', props:'config · getItemDemand/setItemDemand · runFullLoop', note:'CSV (Excel-native); demand edits scale the series proportionally.' }}>
      <div style={{display:'flex', gap:8, flexWrap:'wrap', alignItems:'center', marginBottom:8}}>
        <Btn kind="accent" sm onClick={exportCsv}>⬇ Export model (.csv)</Btn>
        <Btn kind="secondary" sm onClick={()=>fileRef.current&&fileRef.current.click()}>⬆ Re-import edited file</Btn>
        <input ref={fileRef} type="file" accept=".csv,.tsv,.txt" style={{display:'none'}} onChange={onFile}/>
        <span style={{flex:1}}/>
        {diff && diff.length>0 && <React.Fragment>
          <Btn kind="primary" sm onClick={()=>apply(false)} style={busy?{opacity:.5}:undefined}>{busy?'…':'Apply'}</Btn>
          <Btn kind="primary" sm onClick={()=>apply(true)} style={busy?{opacity:.5}:undefined}>{busy?'Solving…':'Apply + re-solve'}</Btn>
        </React.Fragment>}
      </div>

      <textarea value={paste} onChange={e=>{ setPaste(e.target.value); }} onBlur={()=>paste&&computeDiff(paste)}
        placeholder={'…or paste the edited CSV here (slice,field,value). Export first to get the template.'}
        style={{width:'100%', minHeight:64, border:`2px solid ${C.line}`, background:C.paper, color:C.tx2,
          fontFamily:F.mono, fontSize:9.5, padding:8, outline:'none', boxSizing:'border-box', resize:'vertical'}}/>

      {msg && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10.5, color: msg[0]==='⚠'?C.dg:msg[0]==='✓'?C.gn:C.tx2}}>{msg}</div>}

      {diff && diff.length>0 && (
        <div style={{marginTop:8}}>
          <SubLabel>Changes vs the live model</SubLabel>
          <DataTable dense cols={['Slice','Field','Live','Imported','Δ']} align={['left','left','right','right','right']}
            rows={diff.map(r=>{ const dl = (typeof r.live==='number'&&typeof r.imp==='number') ? r.imp-r.live : null;
              return [<Tag c={r.slice==='demand'?'c':'w'}>{r.slice}</Tag>, <span style={{fontFamily:F.mono, fontSize:9.5}}>{r.field}</span>,
                String(r.live), <span style={{fontWeight:700}}>{String(r.imp)}</span>,
                <span style={{fontFamily:F.mono, fontSize:9.5, color: dl==null?C.tx3:(dl>0?C.dg:C.gn)}}>{dl==null?'—':(dl>0?'+':'')+Math.round(dl).toLocaleString('en-IN')}</span>]; })}/>
        </div>
      )}

      <Reading tone={diff&&diff.length?C.a4:C.tx3}
        formula="export envelope → edit in Excel → re-import → field diff → apply (demand scales the series) → re-solve"
        soWhat={diff&&diff.length
          ? `${diff.length} field(s) differ from the live model. Apply writes them back through the same setters the tabs use (demand totals scale the committed series, preserving seasonality) and flags the dependent solves stale — Apply + re-solve runs the full loop so you see the new plan immediately. The whole edit happened in Excel.`
          : 'Round-trip the model through Excel: export the envelope, edit demand or a config scalar in any spreadsheet, re-import, and the diff shows exactly what changed before you commit it. FX & external-signal indices have their own governed surfaces.'}/>
    </Card>
  );
}

// ── Event-sourced replay + version diff/merge (W11 · Platform L4 depth) ──────
// LEFT: the immutable event trail replayed as a version history — every plan-changing
// op in order (the auditable "what changed, when"). RIGHT: a structural DIFF between
// any two input envelopes (Base/live or a scenario) over the fields a planner reasons
// about, with a cherry-pick VERSION MERGE that copies the changed fields from A into B.
const _EV_LABEL = {
  override:'override', actuals:'actuals logged', replan:'re-plan', commit:'commit', trigger:'review trigger',
  auto_trigger:'auto trigger (breach)', import:'history import', import_clear:'import cleared', npi_likemodel:'NPI like-model',
  lifecycle:'lifecycle', promo:'promo flag', scenario_create:'scenario created', scenario_branch:'scenario branched',
  scenario_run:'scenario run', scenario_apply:'scenario applied', scenario_merge:'scenario merged',
  scenario_merge_fields:'fields merged', scenario_delete:'scenario deleted', scenario_eva_prune:'EVA prune branch',
};
function ScnVersions({ sc }){
  const { events } = useEvents();
  const order = sc.order||[]; const list = sc.list||{};
  const opts = [{ id:'base', name:'Base (live)' }].concat(order.map(id=>({ id, name:(list[id]||{}).name||id })));
  const [a,setA] = useState('base');
  const [b,setB] = useState(order[0]||'base');
  const diff = (typeof scenarioDiff==='function') ? scenarioDiff(a,b) : [];
  const evs = (events||[]).slice(-50);
  const merge = ()=>{ if(b==='base' || a===b || !diff.length) return;
    mergeScenarioFields(b, a, diff.map(d=>({ slice:d.slice, field:d.field }))); };
  const nameOf = id=> id==='base'?'Base (live)':((list[id]||{}).name||id);
  return (
    <Card icon="🧬" title="Version history — replay & merge" span={2} badge={`${(events||[]).length} events`} badgeTone={events&&events.length?'g':'k'}
      info={{ what:'The immutable event log replayed as a version history, plus a structural diff/merge between any two input versions. Every plan-changing op is recorded; a merge cherry-picks changed fields from one version into another (logged itself).', flows:'Audit → diff → cherry-pick merge → re-run.' }}
      dev={{ comp:'ScnVersions', props:'useEvents() · scenarioDiff · mergeScenarioFields', note:'W11 — event-sourced replay + version merge.' }}>
      <Grid cols={2}>
        <div>
          <SubLabel>Replay — append-only event trail (newest last)</SubLabel>
          <div style={{maxHeight:220, overflowY:'auto', border:`2px solid ${C.line}`, marginTop:4}}>
            {evs.length===0 ? <div style={{padding:'12px', fontFamily:F.mono, fontSize:10, color:C.tx3}}>No events yet — edit a forecast/sourcing input or run a scenario to populate the trail.</div>
              : evs.map(e=>(
              <div key={e.id} style={{display:'flex', alignItems:'center', gap:8, borderTop:`1px solid ${C.line2}`, padding:'4px 8px', fontFamily:F.mono, fontSize:9.5}}>
                <span style={{color:C.tx3, width:26, textAlign:'right'}}>#{e.id}</span>
                <Tag c={String(e.type).startsWith('scenario')?'b':e.type==='auto_trigger'||e.type==='trigger'?'r':'w'}>{_EV_LABEL[e.type]||e.type}</Tag>
                <span style={{flex:1, minWidth:0, color:C.tx2, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{e.target||'—'}</span>
                <span style={{color:C.tx3}}>{new Date(e.ts).toLocaleTimeString()}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <SubLabel>Diff & merge — compare two versions</SubLabel>
          <div style={{display:'flex', gap:6, alignItems:'center', margin:'4px 0 8px'}}>
            <select value={a} onChange={e=>setA(e.target.value)} style={{fontFamily:F.mono, fontSize:10, padding:'3px 5px', border:`2px solid ${C.line}`}}>{opts.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select>
            <span style={{fontFamily:F.mono, fontSize:11, color:C.tx3}}>→</span>
            <select value={b} onChange={e=>setB(e.target.value)} style={{fontFamily:F.mono, fontSize:10, padding:'3px 5px', border:`2px solid ${C.line}`}}>{opts.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select>
          </div>
          <div style={{border:`2px solid ${C.line}`, maxHeight:170, overflowY:'auto'}}>
            {a===b ? <div style={{padding:'10px', fontFamily:F.mono, fontSize:10, color:C.tx3}}>Pick two different versions to diff.</div>
              : diff.length===0 ? <div style={{padding:'10px', fontFamily:F.mono, fontSize:10, color:C.gn}}>✓ Identical on the compared fields (demand totals · config scalars · sourcing overrides).</div>
              : (<table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:9.5}}>
                  <thead><tr style={{background:C.ink}}>{['slice','field',nameOf(a),nameOf(b)].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i>1?'right':'left', padding:'4px 7px', fontSize:8.5}}>{h}</th>)}</tr></thead>
                  <tbody>{diff.map((d,i)=>(
                    <tr key={i} style={{borderTop:`1px solid ${C.line2}`}}>
                      <td style={{padding:'3px 7px', color:C.tx3}}>{d.slice}</td>
                      <td style={{padding:'3px 7px', fontWeight:700}}>{d.field}</td>
                      <td style={{padding:'3px 7px', textAlign:'right', color:C.tx2}}>{String(d.a)}</td>
                      <td style={{padding:'3px 7px', textAlign:'right', color:C.ac}}>{String(d.b)}</td>
                    </tr>
                  ))}</tbody>
                </table>)}
          </div>
          {diff.length>0 && b!=='base' && a!==b &&
            <div style={{marginTop:8, display:'flex', alignItems:'center', gap:8}}>
              <Btn kind="secondary" sm onClick={merge}>⇲ Merge {diff.length} field{diff.length===1?'':'s'} {nameOf(a)} → {nameOf(b)}</Btn>
              <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>cherry-picks {nameOf(a)}'s values into {nameOf(b)} (re-run to re-score)</span>
            </div>}
          {b==='base' && a!==b && diff.length>0 && <div style={{marginTop:8, fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>Target is Base (live) — merge into a saved branch instead (Base is the live working set; use Apply to switch to a branch).</div>}
        </div>
      </Grid>
    </Card>
  );
}

// ── V3-14 · ① DECIDE strip (blueprint 3.2) — "does the committed plan survive ──
// its shocks — and at what tail cost?" Solve-gated (Sourcing pattern): every
// number is read from the CACHED montecarlo solve; before one exists the strip
// honestly prompts instead of faking. Stale flag rides solves.montecarlo (its
// SOLVE_DEPS: demand·procurement·production·sourcing·productCosts·bom).
function ScenariosDecideStrip(){
  const { state:sr } = useStore(s=>s.solveResults||{});
  const { state:solves } = useStore(s=>s.solves||{});
  const { config } = useConfig();
  const r = sr && sr.montecarlo ? sr.montecarlo.result : null;
  const target = Math.round((Number(config.serviceLevel)||0.95)*100);
  if(!r) return (
    <span data-vis="scenarios-decide" style={{fontFamily:F.mono, fontSize:10, color:C.tx3}}>
      ① DOES THE COMMITTED PLAN SURVIVE ITS SHOCKS — AND AT WHAT TAIL COST? — run <b style={{color:C.tx}}>🎲 Monte Carlo</b> (Risk tab) or the Loop to light this up
    </span>
  );
  const stale = !!(solves && solves.montecarlo && solves.montecarlo.stale);
  const plan = r.policy_simulated==='plan';
  return (
    <div data-vis="scenarios-decide" style={{display:'flex', alignItems:'center', gap:14, flexWrap:'wrap'}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.08em', color:C.tx3}}>① DOES THE COMMITTED PLAN SURVIVE ITS SHOCKS?</span>
      <Tag c={plan?'g':'k'}>{plan?'committed plan':'base-stock proxy'}</Tag>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>mean fill <b className="num" style={{fontFamily:F.disp, color:r.avg_fill<target?C.dg:C.tx}}>{r.avg_fill}%</b> vs α {target}%</span>
      <span style={{color:C.line2}}>·</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>CVaR95 <b className="num" style={{fontFamily:F.disp, color:C.tx}}>₹{(r.cvar95/1e5).toFixed(2)}L</b></span>
      <span style={{color:C.line2}}>·</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>fragility <b className="num" style={{fontFamily:F.disp, color:C.tx}}>{r.fragility}×</b></span>
      {stale && <Tag c="y">→ STALE — inputs changed, re-run</Tag>}
      <Provenance kind="solved" style={{padding:'0 4px', fontSize:7.5}}/>
    </div>
  );
}

// ── V3-14 · VIS-9 — fill-rate distribution (blueprint 3.4 #9) ──────────────
// The solver's OWN fill histogram drawn as the service-risk picture: bars from
// fill_histogram, the worst-5% tail (≤ fill_p5) shaded red with its CVaR₅
// marker, the service target α as the dashed gate, and the mean fill as the
// ▼ committed-plan marker — green when policy_simulated='plan' (the schedule
// that will EXECUTE), amber when the run fell back to a base-stock proxy.
// Pure renderer of solver fields — cannot exist before a real MC run.
function Vis9FillDist({ r, target }){
  const fh = r && r.fill_histogram;
  if(!fh || !fh.counts || !fh.counts.length) return null;
  const b0 = Number(fh.bins[0]);
  const span = Math.max(0.1, 100 - b0);
  const X = v => Math.max(0, Math.min(700, (v-b0)/span*700));
  const hmax = Math.max(1, ...fh.counts);
  const plan = r.policy_simulated==='plan';
  const w = 700/fh.counts.length;
  return (
    <div data-vis="vis9" style={{marginTop:12, border:`2px solid ${C.line}`, borderLeft:`5px solid ${plan?C.gn:C.a4}`, padding:'10px 12px', background:C.paper}}>
      <div style={{display:'flex', alignItems:'baseline', gap:10, flexWrap:'wrap'}}>
        <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.08em', color:C.tx3}}>VIS-9 · FILL-RATE DISTRIBUTION — {r.n_runs} RUNS</span>
        <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>worst-5% tail averages <b style={{color:C.dg}}>{r.fill_cvar5}%</b> fill (CVaR₅) · floor {r.min_fill}%</span>
        <span style={{flex:1}}/>
        <Tag c={plan?'g':'k'}>{plan?'▼ committed plan':'▼ base-stock proxy'}</Tag>
      </div>
      <svg viewBox="0 0 700 120" style={{width:'100%', height:120, display:'block', marginTop:8}}>
        {r.fill_p5!=null && <rect x="0" y="0" width={X(r.fill_p5)} height="104" fill={C.dg} opacity="0.07"/>}
        {fh.counts.map((n,i)=>{
          const h = n/hmax*92;
          const mid = (Number(fh.bins[i])+Number(fh.bins[i+1]))/2;
          const tail = r.fill_p5!=null && mid <= r.fill_p5;
          return <rect key={i} x={i*w+1} y={104-h} width={w-2} height={Math.max(n>0?2:0, h)} fill={tail?C.dg:C.ac}/>;
        })}
        <line x1={X(target)} y1="0" x2={X(target)} y2="104" stroke={C.a4} strokeWidth="1.5" strokeDasharray="4 3"/>
        {r.fill_cvar5!=null && <line x1={X(r.fill_cvar5)} y1="0" x2={X(r.fill_cvar5)} y2="104" stroke={C.dg} strokeWidth="1.5"/>}
        <path d={`M ${X(r.avg_fill)-6} 0 L ${X(r.avg_fill)+6} 0 L ${X(r.avg_fill)} 10 Z`} fill={plan?C.gn:C.a4}/>
        <line x1={X(r.avg_fill)} y1="10" x2={X(r.avg_fill)} y2="104" stroke={plan?C.gn:C.a4} strokeWidth="1.5"/>
        <line x1="0" y1="104" x2="700" y2="104" stroke={C.line} strokeWidth="1"/>
      </svg>
      <div style={{display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx3, marginTop:3, flexWrap:'wrap'}}>
        <span style={{color:plan?C.gn:C.a4}}>▼ mean fill {r.avg_fill}%</span>
        <span style={{color:C.a4}}>┄ target α {target}%</span>
        <span style={{color:C.dg}}>│ CVaR₅ {r.fill_cvar5}% · ◼ worst-5% tail (≤ {r.fill_p5}%)</span>
        <span style={{flex:1}}/>
        <span>x: {b0.toFixed(0)}% → 100% fill</span>
      </div>
    </div>
  );
}

window.StageScenarios = StageScenarios;
