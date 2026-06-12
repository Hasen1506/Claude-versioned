// ════════════════════════════════════════════════════════════════════════
// home.jsx — Home (landing, stage 00). Drill-down KPI tiles (handoff v2 §1.5),
// the ONE shared <SolverNetwork/> graph (§1.3, identical to Console), readiness
// grid, and a control-tower SUMMARY that reads the same alerts[] as Scenarios.
// ════════════════════════════════════════════════════════════════════════
// margin drill — DERIVED per family from product price/cost/demand (was hardcoded).
function marginDrill(){
  const byFam={};
  M.products.filter(p=>p.cat==='Finished').forEach(p=>{
    const fam=(M.itemById(p.sku)||{}).family||'General';
    const f=byFam[fam]||(byFam[fam]={rev:0,cogs:0}); f.rev+=p.price*p.demand; f.cogs+=p.cost*p.demand;
  });
  return { unit:'%', rows:Object.entries(byFam).sort((a,b)=>b[1].rev-a[1].rev).map(([fam,f])=>[fam, (f.rev?((f.rev-f.cogs)/f.rev*100):0).toFixed(1)+'%']) };
}
const KPI_DRILL = { margin: marginDrill() };
function KpiDrill({ kpi, onClose }) {
  const d = KPI_DRILL[kpi]; if(!d) return null;
  return (
    <div className="animate-in" style={{marginTop:10, border:`2px solid ${C.line}`, background:C.bg2}}>
      <div style={{display:'flex', alignItems:'center', gap:8, padding:'7px 11px', borderBottom:`2px solid ${C.line}`, background:C.card}}>
        <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, textTransform:'uppercase', letterSpacing:'.04em'}}>Drill · {kpi}</span>
        <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>company → family → SKU → location → period</span>
        <button onClick={onClose} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:10, fontWeight:700, border:'none', background:'transparent', cursor:'pointer', color:C.tx3}}>✕ close</button>
      </div>
      <div style={{padding:11, display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))', gap:8}}>
        {d.rows.map((r,i)=>(
          <div key={i} style={{border:`2px solid ${C.line2}`, padding:'8px 10px', background:C.paper, display:'flex', justifyContent:'space-between', alignItems:'center'}}>
            <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>{r[0]}</span>
            <span className="num" style={{fontFamily:F.disp, fontSize:14, fontWeight:800}}>{r[1]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// freshness helper — minutes since an ISO timestamp, in words.
function _agoH(ts){ if(!ts) return ''; try{ const m=Math.round((Date.now()-new Date(ts))/60000);
  return m<1?'just now':m<60?`${m}m ago`:`${Math.round(m/60)}h ago`; }catch(e){ return ''; } }
const _crH = n => (n==null||isNaN(n)) ? '—' : '₹ '+(n/1e7).toFixed(2)+' Cr';
const _lkH = n => (n==null||isNaN(n)) ? '—' : '₹'+(n/1e5).toFixed(1)+'L';
// Batch 4 — lifecycle-state presentation map (one source for the merged strip).
const LIFE_META = {
  blocked: { tag:'r', label:'BLOCKED', col:'var(--dg)' },
  ready:   { tag:'w', label:'READY',   col:'var(--tx3)' },
  fresh:   { tag:'g', label:'FRESH',   col:'var(--gn)' },
  stale:   { tag:'y', label:'STALE',   col:'var(--a4)' },
};
const _capH = s => s ? s.charAt(0).toUpperCase()+s.slice(1) : s;

// ── HOME · LIVE STATE-OF-PLAN BOARD ───────────────────────────────────────────
// Restructured (R13): Home answers one question on load — "is my committed plan
// current, and is anything on fire?". The KPI strip reads the cross-stage solve
// cache (solveResults) with a freshness stamp; "—" until solved (never faked).
// One primary action re-plans the 6-step spine via runFullLoop (LOOP_STEPS) — NOT all
// 16 engines; the button + ⓘ name what it skips (R4 honesty). It absorbs the monitoring
// surfaces that used to live in Scenarios — the D8 exception inbox and the D2 value
// ledger (rendered from their global defs). The pre-flight readiness gate and the
// per-stage freshness panel are now MERGED into one Solver-Lifecycle strip (Batch 4):
// BLOCKED → READY → FRESH → STALE per solver. The SolverNetwork graph lives on Console.
function StageHome({ onNav }) {
  const [drill, setDrill] = useState(null);
  const { planning } = usePlanning();
  const { state:sr }     = useStore(s=>s.solveResults||{});
  const { state:solves } = useStore(s=>s.solves||{});
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState(null);
  const [doneAt, setDoneAt] = useState(null);

  // DERIVED consolidated KPIs (price/cost/demand) — real arithmetic on master data.
  const fin = M.products.filter(p=>p.cat==='Finished');
  const revenue = fin.reduce((s,p)=>s+p.price*p.demand,0);
  const cogs = fin.reduce((s,p)=>s+p.cost*p.demand,0);
  const margin = revenue ? (revenue-cogs)/revenue : 0;

  // SOLVED KPIs — read straight from the cross-stage cache; null ⇒ honest "—".
  const R = k => sr[k] ? sr[k].result : null;
  const ag=R('aggregate'), pr=R('production'), lc=R('linecap'), mc=R('montecarlo');
  const prodUnits = pr&&pr.gantt ? pr.gantt.reduce((a,e)=>a+(Number(e.quantity)||0),0) : null;
  const bind = lc&&lc.lines ? lc.lines.filter(x=>x.binding).length : null;
  const anySolve = !!(ag||pr||lc||mc);
  const staleN = Object.values(solves||{}).filter(v=>v&&v.stale).length;
  const lastRan = Object.values(sr).map(e=>e&&e.ranAt).filter(Boolean).sort().slice(-1)[0];
  const freshLine = anySolve ? (staleN? `${staleN} SOLVE${staleN>1?'S':''} STALE — RE-PLAN TO REFRESH` : `PLAN FRESH · LAST SOLVED ${_agoH(lastRan).toUpperCase()}`) : 'NOT SOLVED YET — RE-PLAN THE SPINE (6 SOLVES) TO POPULATE';

  const runLoop = async ()=>{ setRunning(true); setLog(null);
    try{ const fl = await runFullLoop({ planning, onStep:(l)=>setLog([...l]) }); setLog(fl); setDoneAt(new Date()); }
    finally{ setRunning(false); } };
  const okN = (log||[]).filter(s=>s.ok).length, stepN = (typeof LOOP_STEPS!=='undefined'?LOOP_STEPS.length:6);

  // readiness DERIVED from actual data presence (was a static ready/blocked seed).
  const has = {
    demand: fin.length>0, prices: fin.every(p=>p.price>0), capacity: M.lines.length>0,
    bom: M.bom.length>0, suppliers: M.suppliers.length>0, lanes: M.lanes.length>0, tpl: M.tpl.length>0,
    changeover: M.changeover.length>0, assets: M.assets.length>0, wacc: !!M.wacc,
    aggregate: !!M.aggregate, consensus: M.consensus.length>0, distributions: false,
  };
  // Batch 4 (🧭, Theme 6) — ONE solver-lifecycle model, merging the old readiness gate
  // (are the inputs present?) with plan freshness (did it run, is it stale?), keyed by
  // each solver's solve-cache key. Lifecycle per solver: BLOCKED → READY → FRESH → STALE.
  const _life = [
    { solver:'Demand',         key:'forecast',   go:'demand',    inputs:['History'],                       ready: has.demand },
    { solver:'Profit Mix',     key:'profitmix',  go:'plan',      inputs:['Demand fc','Prices','Capacity'], ready: has.demand&&has.prices&&has.capacity },
    { solver:'S&OP Aggregate', key:'aggregate',  go:'plan',      inputs:['Aggregate','Consensus'],         ready: has.aggregate&&has.consensus },
    { solver:'Procurement',    key:'procurement',go:'sourcing',  inputs:['BOM','Suppliers'],               ready: has.bom&&has.suppliers },
    { solver:'Production',     key:'production', go:'production', inputs:['Lines','Changeover'],            ready: has.capacity&&has.changeover },
    { solver:'Line capital',   key:'linecap',    go:'finance',   inputs:['Assets','WACC'],                 ready: has.assets&&has.wacc },
    { solver:'Transport',      key:'transport',  go:'logistics', inputs:['Lanes','3PL'],                   ready: has.lanes&&has.tpl },
    { solver:'Monte Carlo',    key:'montecarlo', go:'scenarios', inputs:['Committed plan'],                ready: has.demand&&has.capacity },
  ];
  const lifecycle = _life.map(r=>{ const st=(solves||{})[r.key]||{}; const hasRes=!!R(r.key);
    const state = !r.ready ? 'blocked' : st.stale ? 'stale' : hasRes ? 'fresh' : 'ready';
    return { ...r, state, asOf: st.ranAt }; });
  const readyN  = lifecycle.filter(r=>r.ready).length;
  const freshN  = lifecycle.filter(r=>r.state==='fresh').length;
  const blockedN= lifecycle.filter(r=>r.state==='blocked').length;

  return (
    <div>
      <StageHeader n="00" title="Command Center" kicker="Live state of the committed plan · what needs your attention · one re-plan action"
        right={<div style={{display:'flex', gap:8, alignItems:'center'}}>
          <Btn kind="accent" onClick={runLoop} title="Runs the 6-step planning spine only — not all 16 engines. See ⓘ for what it skips." style={running?{opacity:.6}:undefined}>{running?`Re-planning… ${okN}/${stepN}`:'▶ Re-plan spine · 6 steps'}</Btn>
          <SectionInfo
            what="Runs the 6-step planning spine on one dataset: Demand forecast → Procurement (landed-cost MILP) → Aggregate S&OP → Production schedule → Capital (line-capacity) signal → Monte-Carlo risk. Of the 16 named engines, this refreshes 5 — Forecast, Procurement, Aggregate, Production, Monte Carlo — plus the line-capacity signal (not one of the 16)."
            flows="Does NOT refresh the other 11 engines — Profit-mix, Disaggregate, Reconcile, Sequencing, Lot-sizing, Transport, Allocation, Consolidate, CVaR, Capital, Capital-capacity. They keep their last result; run them from Console or their own tab."/>
          <Btn kind="secondary" onClick={()=>onNav('console')}>⚡ Console</Btn>
        </div>}/>

      {/* LIVE KPI strip — derived economics + cached solved KPIs with a freshness stamp */}
      <div style={{padding:14, borderBottom:`2px solid ${C.line}`}}>
        <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:8}}>
          <span style={{width:8, height:8, background: anySolve?(staleN?C.a4:C.gn):C.tx3, border:`1.5px solid ${C.line}`}}/>
          <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.1em', color: staleN?C.a4:C.tx3}}>{freshLine}</span>
          {anySolve && <span onClick={()=>onNav('scenarios')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.a2, cursor:'pointer', textDecoration:'underline'}}>scenarios & risk →</span>}
        </div>
        <KpiRow cols={8}>
          <Blk label="Revenue" value={_crH(revenue)} sub="price × demand" tone="k"/>
          <Blk label="COGS" value={_crH(cogs)} sub="cost × demand"/>
          <Blk label="Margin ▸" value={(margin*100).toFixed(1)+'%'} accent={C.gn} onClick={()=>setDrill('margin')}/>
          <Blk label="Plan cost" value={ag?_lkH(ag.total_cost):'—'} sub={ag?(ag.strategy||'solved'):'re-plan to fill'} tone={ag?'c':'k'}/>
          <Blk label="Scheduled" value={prodUnits!=null?prodUnits.toLocaleString('en-IN')+' u':'—'} sub={pr?(pr.status||'solved'):'re-plan to fill'} tone={pr?'g':'k'}/>
          <Blk label="Mean fill" value={mc&&mc.avg_fill!=null?mc.avg_fill+'%':'—'} sub={mc?`policy ${mc.policy_simulated}`:'re-plan to fill'} accent={mc&&mc.avg_fill<95?C.dg:(mc?C.gn:undefined)}/>
          <Blk label="Risk CVaR95" value={mc?_lkH(mc.cvar95):'—'} sub={mc?`mean ${_lkH(mc.avg_cost)}`:'re-plan to fill'} accent={mc?C.dg:undefined}/>
          <Blk label="Binding lines" value={bind==null?'—':String(bind)} sub={bind!=null?(bind?'capacity tight':'all slack'):'re-plan to fill'} accent={bind?C.dg:undefined}/>
        </KpiRow>
        {drill && <KpiDrill kpi={drill} onClose={()=>setDrill(null)}/>}
        {log && <div style={{marginTop:10, display:'flex', flexDirection:'column', gap:3}}>
          {log.map(e=>(<div key={e.key} style={{display:'flex', alignItems:'center', gap:8, fontFamily:F.mono, fontSize:9.5}}>
            <span style={{width:12, color:e.ok?C.gn:e.error?C.dg:C.tx3}}>{e.ok?'✓':e.error?'✕':'…'}</span>
            <span style={{flex:1, color:C.tx2}}>{e.label}</span>
            <span style={{color:e.error?C.dg:C.tx3}}>{e.error?('⚠ '+e.error):e.summary}{e.ms?` · ${e.ms}ms`:''}</span>
          </div>))}
        </div>}
      </div>

      <div style={{padding:14}}>
        <Grid cols={2}>
          {/* D8 · exception inbox — the "what needs my attention" list (moved from Scenarios) */}
          <ExceptionCockpit onNav={onNav}/>

          {/* MERGED solver-lifecycle strip — readiness gate + plan freshness on ONE
              card (Batch 4 🧭, Theme 6). Each solver shows its full lifecycle state. */}
          <Card icon="✅" title="Solver Lifecycle" badge={`${readyN}/${lifecycle.length} ready · ${freshN} fresh`} badgeTone={blockedN?'r':(staleN?'y':'g')}
            right={<Provenance kind="derived" note="readiness + recompute DAG"/>}
            info={{ what:'Every solver across its whole lifecycle on one strip: BLOCKED (an input is missing) → READY (inputs present, not yet run) → FRESH (solved, current) → STALE (an input changed since it ran). Merges the pre-flight input gate with plan freshness.', flows:'Blocked → enter the input · Stale → re-plan · drill any row to its tab.' }}
            dev={{ comp:'SolverLifecycle', props:'has(data presence) + solves(DAG) + solveResults', note:'One source replacing the separate readiness + freshness cards.' }}>
            <div style={{display:'flex', flexDirection:'column', gap:6}}>
              {lifecycle.map((r,i)=>{ const m=LIFE_META[r.state]; const blocked=r.state==='blocked';
                return (
                <div key={i} style={{border:`2px solid ${blocked?C.dg:C.line}`, borderLeft:`5px solid ${m.col}`, background: blocked?'color-mix(in srgb,var(--dg) 7%,transparent)':C.paper, padding:'7px 9px', display:'flex', alignItems:'center', gap:9}}>
                  <Tag c={m.tag}>{m.label}</Tag>
                  <div style={{minWidth:0, flex:1}}>
                    <div style={{display:'flex', alignItems:'center', gap:7}}>
                      <span style={{fontFamily:F.disp, fontSize:12, fontWeight:800}}>{r.solver}</span>
                      <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{r.key}</span>
                    </div>
                    {blocked ? (
                      <div style={{fontFamily:F.mono, fontSize:9.5, color:C.dg, marginTop:3, fontWeight:600}}>missing: {r.inputs.join(' + ')} — enter in {_capH(r.go)}</div>
                    ) : (
                      <div style={{display:'flex', gap:4, marginTop:3, flexWrap:'wrap', alignItems:'center'}}>
                        {r.inputs.map((inp,j)=><Tag key={j} c="w">{inp}</Tag>)}
                        {r.state==='stale' && <span style={{fontFamily:F.mono, fontSize:9, color:C.a4, fontWeight:700}}>· input changed since last run</span>}
                        {r.state==='ready' && <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>· ready, not yet run</span>}
                      </div>
                    )}
                  </div>
                  <div style={{display:'flex', flexDirection:'column', alignItems:'flex-end', gap:2, whiteSpace:'nowrap'}}>
                    {r.asOf && !blocked && <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{_agoH(r.asOf)}</span>}
                    <button onClick={()=>onNav(r.go)} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>{blocked?'fix':r.state==='stale'?'re-plan':'open'} →</button>
                  </div>
                </div>
              );})}
            </div>
            <Reading tone={blockedN?C.dg:(staleN?C.a4:C.gn)}
              formula={`${readyN}/${lifecycle.length} have inputs · ${freshN} fresh · ${staleN} stale · ${blockedN} blocked`}
              soWhat={(blockedN?`${blockedN} solver(s) blocked on missing inputs — enter them to unlock the run. `:'')+(staleN?`${staleN} solved stage(s) went stale after an edit — re-plan the spine (6 solves) to realign the planning stages on one dataset.`:(freshN?'Every solved stage is fresh and off the same committed dataset — the plan is internally consistent.':'Nothing solved yet — re-plan the spine (6 solves) to populate the planning stages from one dataset.'))}/>
          </Card>

          {/* D2 · value ledger — the tool measuring its own ROI (moved from Scenarios) */}
          <ValueLedger/>
        </Grid>
      </div>
    </div>
  );
}
window.StageHome = StageHome;
