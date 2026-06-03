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

// ── HOME · LIVE STATE-OF-PLAN BOARD ───────────────────────────────────────────
// Restructured (R13): Home answers one question on load — "is my committed plan
// current, and is anything on fire?". The KPI strip reads the cross-stage solve
// cache (solveResults) with a freshness stamp; "—" until solved (never faked). One
// primary action re-plans the whole model (runFullLoop). It absorbs the monitoring
// surfaces that used to live in Scenarios — the D8 exception inbox and the D2 value
// ledger (rendered from their global defs) — and keeps the pre-flight readiness
// gate. The duplicated SolverNetwork graph now lives ONLY on Console.
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
  const freshLine = anySolve ? (staleN? `${staleN} SOLVE${staleN>1?'S':''} STALE — RE-PLAN TO REFRESH` : `PLAN FRESH · LAST SOLVED ${_agoH(lastRan).toUpperCase()}`) : 'NOT SOLVED YET — RE-PLAN THE WHOLE MODEL TO POPULATE';

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
  const readiness = [
    { solver:'Profit Mix', inputs:['Demand fc','Prices','Capacity'], ready: has.demand&&has.prices&&has.capacity },
    { solver:'Procurement', inputs:['BOM','Suppliers'], ready: has.bom&&has.suppliers },
    { solver:'Production', inputs:['Lines','Changeover'], ready: has.capacity&&has.changeover },
    { solver:'Transport', inputs:['Lanes','3PL'], ready: has.lanes&&has.tpl },
    { solver:'Monte Carlo', inputs:['Distributions'], ready: has.distributions },
    { solver:'Capital', inputs:['Assets','WACC'], ready: has.assets&&has.wacc },
    { solver:'S&OP', inputs:['Aggregate','Consensus'], ready: has.aggregate&&has.consensus },
  ].map(r=> r.ready ? r : { ...r, missing:r.inputs.join(' + '), fixGo: r.solver==='Monte Carlo'?'scenarios':'network', fixLabel: r.solver==='Monte Carlo'?'Scenarios':'Network' });

  // per-stage freshness panel — fresh / stale / not-run from the recompute DAG.
  const stageRows = [['Demand','forecast','demand'],['Plan / S&OP','aggregate','plan'],
    ['Procurement','procurement','sourcing'],['Production','production','production'],
    ['Line capital','linecap','plan'],['Risk · Monte Carlo','montecarlo','scenarios']];

  return (
    <div>
      <StageHeader n="00" title="Command Center" kicker="Live state of the committed plan · what needs your attention · one re-plan action"
        right={<div style={{display:'flex', gap:8}}>
          <Btn kind="accent" onClick={runLoop} style={running?{opacity:.6}:undefined}>{running?`Re-planning… ${okN}/${stepN}`:'▶ Re-plan whole model'}</Btn>
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
          <Blk label="Plan cost" value={ag?_lkH(ag.total_cost):'—'} sub={ag?(ag.strategy||'solved'):'run loop'} tone={ag?'c':'k'}/>
          <Blk label="Scheduled" value={prodUnits!=null?prodUnits.toLocaleString('en-IN')+' u':'—'} sub={pr?(pr.status||'solved'):'run loop'} tone={pr?'g':'k'}/>
          <Blk label="Mean fill" value={mc&&mc.avg_fill!=null?mc.avg_fill+'%':'—'} sub={mc?`policy ${mc.policy_simulated}`:'run loop'} accent={mc&&mc.avg_fill<95?C.dg:(mc?C.gn:undefined)}/>
          <Blk label="Risk CVaR95" value={mc?_lkH(mc.cvar95):'—'} sub={mc?`mean ${_lkH(mc.avg_cost)}`:'run loop'} accent={mc?C.dg:undefined}/>
          <Blk label="Binding lines" value={bind==null?'—':String(bind)} sub={bind!=null?(bind?'capacity tight':'all slack'):'run loop'} accent={bind?C.dg:undefined}/>
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

          {/* pre-flight readiness gate */}
          <Card icon="✅" title="Solver Input Readiness" badge={`${readiness.filter(r=>r.ready).length}/${readiness.length} ready`}
            info={{ what:'Pre-flight gate: a missing input BLOCKS its solver and names what to enter + where. Derived from actual data presence.', flows:'Gates the Console run button per mode.' }}
            dev={{ comp:'ReadinessGrid', props:'derived from M data presence', note:'Not a passive checkmark — computed from whether each solver’s inputs actually exist.' }}>
            <div style={{display:'flex', flexDirection:'column', gap:6}}>
              {readiness.map((r,i)=>(
                <div key={i} style={{border:`2px solid ${r.ready?C.line:C.dg}`, background: r.ready?C.paper:'color-mix(in srgb,var(--dg) 7%,transparent)', padding:'7px 9px', display:'flex', alignItems:'center', gap:9}}>
                  <span style={{width:16, height:16, flexShrink:0, display:'grid', placeItems:'center', background:r.ready?C.gn:C.dg, color:'#fff', fontFamily:F.disp, fontWeight:900, fontSize:11}}>{r.ready?'✓':'!'}</span>
                  <div style={{minWidth:0, flex:1}}>
                    <div style={{display:'flex', alignItems:'center', gap:7}}>
                      <span style={{fontFamily:F.disp, fontSize:12, fontWeight:800}}>{r.solver}</span>
                      {!r.ready && <Tag c="r">blocked</Tag>}
                    </div>
                    {r.ready ? (
                      <div style={{display:'flex', gap:4, marginTop:3, flexWrap:'wrap'}}>
                        {r.inputs.map((inp,j)=><Tag key={j} c="w">{inp}</Tag>)}
                      </div>
                    ) : (
                      <div style={{fontFamily:F.mono, fontSize:9.5, color:C.dg, marginTop:3, fontWeight:600}}>
                        missing: {r.missing} — enter in {r.fixLabel}
                      </div>
                    )}
                  </div>
                  {!r.ready && <button onClick={()=>onNav(r.fixGo)} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline', whiteSpace:'nowrap'}}>fix in {r.fixLabel} →</button>}
                </div>
              ))}
            </div>
          </Card>

          {/* per-stage freshness — fresh / stale / not-run from the recompute DAG */}
          <Card icon="🧭" title="Plan freshness · drill to a stage" badge={anySolve?(staleN?`${staleN} stale`:'all fresh'):'not solved'} badgeTone={anySolve?(staleN?'y':'g'):'k'}
            right={<Provenance kind="derived" note="recompute DAG"/>}
            info={{ what:'Each planning stage’s freshness from the recompute DAG — fresh, stale (an input changed since it ran), or not yet run. Click a stage to open the owning tab.', flows:'Freshness → re-plan or drill.' }}
            dev={{ comp:'HomePlanStatus', props:'solves[] · solveResults' }}>
            <DataTable dense cols={['Stage','Solve','State','As of']} align={['left','left','left','right']}
              rows={stageRows.map(([label,key,go])=>{ const st=(solves||{})[key]||{}; const has=!!R(key);
                const state = st.stale?'STALE':(has?'fresh':'not run');
                const col = state==='STALE'?C.dg:state==='fresh'?C.gn:C.tx3;
                return { cells:[
                  <span style={{cursor:'pointer', textDecoration:'underline', textDecorationColor:C.line2}} onClick={()=>onNav&&onNav(go)}>{label}</span>,
                  <span style={{fontFamily:F.mono, fontSize:9}}>{key}</span>,
                  <span style={{color:col, fontWeight:700}}>{state}</span>,
                  st.ranAt?_agoH(st.ranAt):'—'] };
              })}/>
            <Reading tone={anySolve?(staleN?C.a4:C.gn):C.tx3}
              formula={`${stageRows.filter(([,k])=>!!R(k)).length}/${stageRows.length} stages solved · ${staleN} stale`}
              soWhat={anySolve?(staleN?'A stale stage means an input changed since it last solved — re-plan the whole model to bring every stage back onto one consistent dataset.':'Every solved stage is fresh and off the same committed dataset — the plan is internally consistent.'):'Nothing solved yet — re-plan the whole model to populate every stage from one dataset.'}/>
          </Card>

          {/* D2 · value ledger — the tool measuring its own ROI (moved from Scenarios) */}
          <ValueLedger/>
        </Grid>
      </div>
    </div>
  );
}
window.StageHome = StageHome;
