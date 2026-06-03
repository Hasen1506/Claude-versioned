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
function StageScenarios({ onNav }) {
  const [sub, setSub] = useState('cockpit');
  const tabs = M.scenarioSubtabs.map(t=>({ id:t.id, n:t.n, label:t.label, count:t.count }));
  return (
    <div>
      <StageHeader n="11" title="Risk & Scenarios" kicker="Monte Carlo on the committed plan · CVaR robust stock · end-to-end loop · what-if (W6/W7)"
        right={<Btn kind="secondary">📄 Report export</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='cockpit'   && <ScnCockpit onNav={onNav}/>}
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
function liveAlerts(solves, events, mc){
  const out = [];
  const STAGE = { procurement:'Sourcing', production:'Production', aggregate:'Plan',
                  montecarlo:'Risk', linecap:'Plan', cvar:'Sourcing', meio:'Sourcing' };
  Object.entries(solves||{}).forEach(([k,v])=>{
    if(v && v.stale) out.push({ sev:'M', area:'Stale', msg:`${k} plan is stale — inputs changed since last solve`, go:STAGE[k], t:'now' });
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
    wUnits += u; wCost += u*(p.cost||0); wMargin += u*Math.max(0,(p.price||0)-(p.cost||0));
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
  const holding = Math.max(1, (Number(p.cost)||0) * 0.24/12);          // its own monthly holding ₹/u
  const margin = Math.max(1, (Number(p.price)||0) - (Number(p.cost)||0)); // its own lost margin
  return { mean:Math.round(mean), std:Math.max(1,Math.round(std)),
    holding_cost:Math.round(holding), shortage_cost:Math.round(margin),
    beta:Number(beta)||0.95, n_scenarios:300, _holding:Math.round(holding) };
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
  const mc = useSolve('/api/solve/montecarlo', ()=>montecarloPayload(planning,
    { serviceLevel:config.serviceLevel, corr:(corr===''?undefined:corr), nRuns:(nRuns===''?undefined:nRuns),
      prodLeadTime:(lt===''?undefined:lt) }), { solveKey:'montecarlo' });   // LP-C hydrate from loop cache
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
          <Reading tone={r.policy_simulated==='plan'?C.gn:C.a4}
            formula={`CVaR95 = E[cost | cost ≥ VaR95] = ₹${(r.cvar95/1e5).toFixed(2)}L over the worst 5% of ${r.n_runs} runs`}
            soWhat={r.policy_simulated==='plan'
              ? `Risk of the schedule that will EXECUTE${r.prod_lead_time>0?`, with a ${r.prod_lead_time}-wk stochastic build→land lag (RK-D) — a mis-timed build against a shock is penalised`:''}. The β-tail costs ₹${((r.cvar95-r.avg_cost)/1e5).toFixed(2)}L over the mean; mean fill ${r.avg_fill}%.`
              : `No committed schedule cached — this simulates a re-derived base-stock policy. Run Production / the Loop to price the actual plan (R-1).`}/>
        </>}
      </Card>

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
          const avgMargin = fin.length? fin.reduce((s,p)=>s+Math.max(0,(p.price||0)-(p.cost||0)),0)/fin.length:0;
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
        info={{ what:'Chains the planning solvers in dependency order on the same committed dataset: procurement → aggregate S&OP → production schedule → ₹ line-capacity dual → Monte-Carlo risk on the just-built schedule. Each step feeds the next.', flows:'One action re-plans the whole model (Kinaxis-style).' }}
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
  const cw=M.costWaterfall;
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Cost Waterfall" badge="illustrative" badgeTone="k" span={2}
        right={<Provenance kind="external" run="seed"/>}
        info={{ what:'Build-up of total cost by category (seed structure — wire to the solved cost roll-up to make it live).', flows:'Cost structure → savings hunt.' }}
        dev={{ comp:'CostWaterfallCard', props:'M.costWaterfall' }}>
        <svg viewBox="0 0 700 170" style={{width:'100%', height:170, display:'block'}}>
          {(()=>{ let cum=0; const mx=12.64;
            return cw.map((d,i)=>{ const x=30+i*112, h=d.v/mx*130;
              const bar = d.total ? <rect x={x} y={150-h} width="80" height={h} fill={C.ink}/> : <rect x={x} y={150-(cum+d.v)/mx*130} width="80" height={d.v/mx*130} fill={C.ac}/>;
              const out=(<g key={i}>{bar}
                <text x={x+40} y="163" fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{d.k}</text>
                <text x={x+40} y={(d.total?150-h:150-(cum+d.v)/mx*130)-4} fontFamily={F.disp} fontSize="10" fontWeight="700" fill={C.tx} textAnchor="middle">₹{d.v}</text>
              </g>);
              if(!d.total) cum+=d.v; return out;
            });
          })()}
        </svg>
      </Card>
      <Card icon="🏗️" title="TCO per SKU" badge="illustrative" badgeTone="k" span={2}
        right={<Provenance kind="external" run="seed"/>}
        info={{ what:'Unit + holding + ordering + quality + obsolescence (seed — wire to solved TCO).', flows:'TCO → true profitability.' }}
        dev={{ comp:'TCOCard', props:'M.tco' }}>
        <DataTable cols={['SKU','Unit','Holding','Ordering','Quality','Obsol.','TCO/u']} align={['left','right','right','right','right','right','right']}
          rows={M.tco.map(t=>({cells:[t.sku, `₹${t.unit}`, `₹${t.hold}`, `₹${t.order}`, `₹${t.quality}`, `₹${t.obsol}`, <span style={{fontWeight:700, color:C.dg}}>₹{t.tco}</span>]}))}/>
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
// capital → risk → pooling, with a single "re-plan the whole model" action and
// the live control-tower count. Honest "—" for any stage not yet solved.
// ════════════════════════════════════════════════════════════════════════
const _L = v => (v==null||isNaN(v)) ? '—' : '₹'+(v/1e5).toFixed(2)+'L';
const _N = v => (v==null||isNaN(v)) ? '—' : Math.round(v).toLocaleString('en-IN');
function _R(sr,key){ const e=sr[key]; return e ? e.result : null; }
function ScnCockpit({ onNav }){
  const { planning } = usePlanning();
  const { state:sr }     = useStore(s=>s.solveResults||{});
  const { state:solves } = useStore(s=>s.solves||{});
  const { events } = useEvents();
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState(null);
  const [doneAt, setDoneAt] = useState(null);
  const ag = _R(sr,'aggregate'), pr = _R(sr,'production'), lc = _R(sr,'linecap'),
        mc = _R(sr,'montecarlo'), pc = _R(sr,'procurement'), mn = _R(sr,'meionet');
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const committedYr = fin.reduce((s,p)=>s+getItemDemand(p.sku,12).reduce((a,b)=>a+b,0),0);
  const prodUnits = pr && pr.gantt ? pr.gantt.reduce((a,e)=>a+(Number(e.quantity)||0),0) : null;
  const bind = lc && lc.lines ? lc.lines.filter(x=>x.binding).length : null;
  const shadowMax = lc && lc.lines ? Math.max(0,...lc.lines.map(x=>Number(x.shadow_price)||0)) : null;
  const dividend = mn ? (mn.total_annual_dividend != null ? mn.total_annual_dividend : null) : null;
  const staleCount = Object.values(solves||{}).filter(v=>v&&v.stale).length;
  const alerts = liveAlerts(solves, events, mc);
  const runLoop = async ()=>{ setRunning(true); setLog(null);
    try{ const fl = await runFullLoop({ planning, onStep:(l)=>setLog([...l]) }); setLog(fl); setDoneAt(new Date()); }
    finally{ setRunning(false); } };
  const okN = (log||[]).filter(s=>s.ok).length, stepN = (typeof LOOP_STEPS!=='undefined'?LOOP_STEPS.length:6);
  // freshness of the whole plan
  const anySolve = !!(ag||pr||lc||mc||pc);
  return (
    <Grid cols={2}>
      <Card icon="🛰" title="S&OP Cockpit — the whole plan at a glance" span={2}
        badge={anySolve ? (staleCount?`${staleCount} stale`:'all fresh') : 'not solved'} badgeTone={anySolve?(staleCount?'y':'g'):'k'}
        right={<Btn kind="primary" sm onClick={runLoop}>{running?'Re-planning…':'▶ Re-plan whole model'}</Btn>}
        info={{ what:'Every stage of the committed plan, read from the cross-stage solve cache — the same solved numbers each tab shows. One button re-runs the end-to-end loop; the board refreshes from the cache.', flows:'Executive S&OP review → drill into any stage.' }}
        dev={{ comp:'ScnCockpit', props:'solveResults cache', note:'W10 — rollup of aggregate/production/linecap/montecarlo/procurement/meionet.' }}>
        <Provenance kind={anySolve?'solved':'derived'} asOf={doneAt?doneAt.toLocaleTimeString():(anySolve?'from cached solves':'not yet solved')} stale={staleCount>0} style={{marginBottom:10}}/>
        <KpiRow cols={4}>
          <Blk label="Committed demand /yr" value={`${_N(committedYr)} u`} sub={`${fin.length} FG`}/>
          <Blk label="Plan strategy" value={ag?(ag.strategy||'—'):'—'} sub={ag?`cost ${_L(ag.total_cost)}`:'run aggregate'} tone={ag?'c':'k'}/>
          <Blk label="Schedule" value={pr?(pr.status||'—'):'—'} sub={pr?`${_N(prodUnits)} u · ${pr.campaign?pr.campaign.runs+' runs':''}`:'run production'} tone={pr?'g':'k'}/>
          <Blk label="Line capital" value={bind==null?'—':`${bind} binding`} sub={bind!=null?(shadowMax>0?`₹${Math.round(shadowMax)}/u max`:'all slack'):'run linecap'} accent={bind?C.dg:undefined}/>
        </KpiRow>
        <KpiRow cols={4}>
          <Blk label="Risk · CVaR95" value={mc?_L(mc.cvar95):'—'} sub={mc?`mean ${_L(mc.avg_cost)}`:'run MC'} accent={mc?C.dg:undefined}/>
          <Blk label="Mean fill" value={mc?`${mc.avg_fill}%`:'—'} accent={mc&&mc.avg_fill<95?C.dg:(mc?C.gn:undefined)} sub={mc?`policy ${mc.policy_simulated}`:'—'}/>
          <Blk label="Pooling dividend" value={dividend==null?'—':`₹${_N(dividend)}/yr`} sub={dividend!=null?'SS holding freed':'run pooling'} tone={dividend?'g':'k'}/>
          <Blk label="Control tower" value={`${alerts.length} live`} sub={`${staleCount} stale solves`} accent={alerts.length?C.dg:undefined}/>
        </KpiRow>
        {log && <div style={{marginTop:10, display:'flex', flexDirection:'column', gap:4}}>
          {log.map((e)=>(<div key={e.key} style={{display:'flex', alignItems:'center', gap:8, fontFamily:F.mono, fontSize:10}}>
            <span style={{width:14, color:e.ok?C.gn:e.error?C.dg:C.tx3}}>{e.ok?'✓':e.error?'✕':'…'}</span>
            <span style={{flex:1, color:C.tx2}}>{e.label}</span>
            <span style={{color:e.error?C.dg:C.tx3}}>{e.error?('⚠ '+e.error):e.summary}{e.ms?` · ${e.ms}ms`:''}</span>
          </div>))}
        </div>}
        <Reading tone={anySolve?(staleCount?C.a4:C.gn):C.tx3}
          formula={`committed ${_N(committedYr)}u/yr · plan ${ag?_L(ag.total_cost):'—'} · risk CVaR95 ${mc?_L(mc.cvar95):'—'} @ ${mc?mc.avg_fill+'%':'—'} fill`}
          soWhat={anySolve
            ? (staleCount ? `${staleCount} solve(s) are stale — an input changed since they ran. Re-plan to refresh the board.` : 'The committed model is internally consistent — every stage solved off the same demand. This is the executive view a Kinaxis S&OP cockpit gives.')
            : 'Nothing solved yet. Re-plan the whole model (or run each tab) to populate the cockpit from real solves.'}/>
      </Card>

      {/* drill links */}
      <Card icon="🧭" title="Stage status & drill" span={2}
        info={{ what:'Per-stage freshness from the recompute DAG. Click to open the owning tab.', flows:'Cockpit → stage.' }}
        dev={{ comp:'ScnCockpit·drill', props:'solves[] freshness' }}>
        <DataTable dense cols={['Stage','Solve','State','As of']} align={['left','left','left','right']}
          rows={[['Demand','—',null,null],
            ['Plan / S&OP','aggregate','plan'],['Production','production','produce'],
            ['Line capital','linecap','plan'],['Procurement','procurement','sourcing'],
            ['Pooling','meionet','sourcing'],['Risk','montecarlo','analysis']].map(([label,key,go])=>{
            const st = (solves||{})[key]||{}; const has = key!=='—' && _R(sr,key);
            const state = key==='—' ? 'derived' : (st.stale?'STALE':(has?'fresh':'not run'));
            const col = state==='STALE'?C.dg:state==='fresh'?C.gn:C.tx3;
            return { cells:[
              go ? <span style={{cursor:'pointer', textDecoration:'underline', textDecorationColor:C.line2}} onClick={()=>onNav&&onNav(go)}>{label}</span> : label,
              key, <span style={{color:col, fontWeight:700}}>{state}</span>,
              st.ranAt?_ago(st.ranAt):'—'] };
          })}/>
      </Card>
    </Grid>
  );
}

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
function ScnScenarios({ onNav }){
  const { planning } = usePlanning();
  const sc = useScenarios();
  const order = sc.order||[]; const list = sc.list||{};
  const [busy, setBusy]   = useState(null);     // scenario id currently running
  const [name, setName]   = useState('');
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
        if(dp){ const dem = { ...(inputs.demand||{}) };
          (M.products||[]).filter(p=>p.cat==='Finished').forEach(p=>{
            const base = (dem[p.sku] && dem[p.sku].length) ? dem[p.sku] : getItemDemand(p.sku, 52);
            dem[p.sku] = base.map(v=>Math.max(0, Math.round(v*(1+dp/100))));
          });
          inputs.demand = dem; }
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
        </div>}
        info={{ what:'Each branch is a snapshot of the input model. "Run" scores it through the full loop transparently — live is restored after, so branches are compared on REAL solved numbers without disturbing each other (Kinaxis-style concurrent planning). "Apply" switches the working set to a branch; "Merge" promotes it.', flows:'Branch → run → compare → merge.' }}
        dev={{ comp:'ScnScenarios', props:'useScenarios() · runScenario/branch/merge', note:'W10/W11 — store.jsx §4½ scenario engine.' }}>
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

      {/* Event-sourced replay + version diff/merge (W11 · Platform L4 depth) */}
      <ScnVersions sc={sc}/>
    </Grid>
  );
}
function _dl(v){ return (v==null||isNaN(v)) ? '—' : (v>=0?'+':'−')+'₹'+(Math.abs(v)/1e5).toFixed(2)+'L'; }

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

window.StageScenarios = StageScenarios;
