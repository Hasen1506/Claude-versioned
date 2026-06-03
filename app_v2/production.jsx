// ════════════════════════════════════════════════════════════════════════
// production.jsx — Production (stage 06, handoff v2 §3.06). 0 sub-tabs guided
// scroll under the item selector. MPS gains a day/week grain toggle (default
// day inside the frozen fence). ATP/CTP & changeover interpreted inline.
// Now OWNS Cycle Time & Line Assignment (moved out of Products).
// ════════════════════════════════════════════════════════════════════════
// W3 — effective governed value: the user's override, else the seed (matches the
// service-level pattern — a seed is always the effective default until overridden).
const _eff = (v, seed)=> (v!=null && v!=='') ? Number(v) : seed;

function StageProduction({ onNav }) {
  const { item } = useActiveItem();
  const { planning } = usePlanning();
  const { config, setConfig } = useConfig();
  const p = M.products.find(x=>x.sku===(item&&item.id)) || M.products[0];
  // sub-tabbed to tame density — this was the busiest single-scroll stage
  const [sub, setSub] = useState('arch');
  // W3 · PR-1 — the schedule subtab now runs the REAL production MILP (was a
  // hand-synthesised grid). The labor rate + shutdown threshold are governed
  // seeds (SolverInput) that price overtime and the idle-week shutdown heuristic.
  const laborRate  = _eff(config.prodLaborRate, 120);
  const shutdownPct = _eff(config.prodShutdownPct, 25);
  // PR-A — opt-in time-phased MPS (tracks the demand curve vs front-loading); the holding
  // cost penalizes building early. PR-B — governed per-SKU cycle/line overrides flow in.
  const timePhased = !!config.prodTimePhased;
  const holdingCost = _eff(config.prodHoldingCost, 2);
  const campaignMinRun = _eff(config.prodCampaignMinRun, 0);   // PR-4 — campaign min-run lever
  const routing = config.prodRouting || {};
  const prod = useSolve('/api/solve/production', ()=>productionPayload(planning, { laborRate, shutdownPct, timePhased, holdingCost, campaignMinRun, routing }), { solveKey:'production' });  // LP-C hydrate from loop cache
  const { stale, ranAt } = useStale('production');
  const runProd = ()=> prod.run().then(d=>{ markSolved('production'); return d; }).catch(()=>{});
  const tabs = [
    { id:'arch',   label:'Architecture' },
    { id:'cycle',  label:'Cycle & Line' },
    { id:'sched',  label:'Schedule' },
    { id:'change', label:'Changeover' },
  ];
  return (
    <div>
      <StageHeader n="06" title="Production Architecture" kicker="Lines → stages → machines · OEE · bottleneck = min(stage) · cycle/line · MPS(day) · order promising"
        right={<Btn kind="accent" onClick={runProd}>{prod.solving?'⏳ Scheduling…':'⚡ Run schedule'}</Btn>}/>
      <ItemSelector/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:18}}>
        <SolverExplain id="production"/>
        {prod.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Production MILP: {prod.error}</div>}
        {sub==='arch'   && <StageSection step="1" title="Architecture" sub="line → stage → machine tree · the slowest stage caps the line"><ProdArch prod={prod}/></StageSection>}
        {sub==='cycle'  && <StageSection step="2" title={`Cycle & Line · ${p.name}`} sub="cycle time and line assignment are line properties (moved here from Products)"><ProdCycle p={p} prod={prod} config={config} setConfig={setConfig} onNav={onNav}/></StageSection>}
        {sub==='sched'  && <>
          <StageSection step="0" title="Solver Parameters" sub="governed inputs — seed defaults you may override; the rate prices overtime and shutdown savings">
            <ProdParams config={config} setConfig={setConfig} prod={prod} ranAt={ranAt}/>
          </StageSection>
          {stale && <StaleMark since="(demand or cost inputs changed)" onNav={()=>runProd()} go="rerun"/>}
          <StageSection step="3" title="Master Production Schedule" sub="time-phased quantities from the production MILP — weekly, with a calendar-aware day drill inside the frozen fence"><ProdMPS prod={prod} planning={planning} item={item} runProd={runProd}/></StageSection>
          <StageSection step="4" title="Order Promising · ATP / CTP" sub="uncommitted supply = solved production − committed demand, carried period to period"><ProdATP prod={prod} planning={planning}/></StageSection>
          <StageSection step="5" title="Capacity Loading & Shutdown" sub="per-line utilization, overtime and idle-week shutdown candidates from the solve"><ProdCapacity prod={prod} rateIsSeed={config.prodLaborRate==null||config.prodLaborRate===''} laborRate={laborRate}/></StageSection>
        </>}
        {sub==='change' && <StageSection step="6" title="Sequence-Dependent Changeover" sub="the matrix, plus the solver's chosen run order and the minutes it saves"><ProdChange/></StageSection>}
      </div>
    </div>
  );
}

// W3 · PR-1/PR-6 — governed production-MILP inputs. The labor rate is a SEED
// (EXTERNAL·seed badge until overridden, D-DEC-1) that prices OT + shutdown
// savings; the shutdown threshold sets the utilization floor for a candidate.
function ProdParams({ config, setConfig, prod, ranAt }){
  // PR-A — time-phased toggle. OFF (default) = minimize makespan+setup ⇒ each SKU front-loads
  // into 1–2 weeks (the W3 behavior). ON = add a no-backorder inventory balance per period so
  // production TRACKS the committed demand curve; the holding rate prices early build.
  const timePhased = !!config.prodTimePhased;
  return (
    <Card icon="🎛️" title="Production MILP inputs" badge="governed" badgeTone="y"
      right={prod && prod.result ? <Provenance kind="solved" asOf={ranAt?ranAt.toLocaleTimeString():undefined}/> : null}
      info={{ what:'Line labor rate prices overtime and idle-week shutdown savings; the threshold sets the utilization below which an idle run is a shutdown candidate. Time-phasing makes the schedule track the demand curve instead of front-loading. All seeds you may override.', flows:'→ production MILP labor_cost_mode + shutdown heuristic + inventory balance.' }}
      dev={{ comp:'SolverInput', props:'config.{prodLaborRate,prodShutdownPct,prodTimePhased,prodHoldingCost}', state:'config.*' }}>
      <Grid cols={3}>
        <SolverInput label="Line labor rate" seed={120} value={config.prodLaborRate}
          onChange={v=>setConfig({ prodLaborRate:v })} min={0} suffix="₹/hr"
          hint="prices OT + shutdown savings"/>
        <SolverInput label="Shutdown threshold" seed={25} value={config.prodShutdownPct}
          onChange={v=>setConfig({ prodShutdownPct:v })} min={0} max={100} suffix="% util"
          hint="idle runs below this are candidates"/>
        {timePhased && <SolverInput label="Holding cost" seed={2} value={config.prodHoldingCost}
          onChange={v=>setConfig({ prodHoldingCost:v })} min={0} suffix="₹/u/wk"
          hint="penalizes building ahead of demand"/>}
        <SolverInput label="Campaign min-run" seed={0} value={config.prodCampaignMinRun}
          onChange={v=>setConfig({ prodCampaignMinRun:v })} min={0} integer suffix="u/run"
          hint="PR-4 — min units per setup (0 = off)"/>
      </Grid>
      {prod && prod.result && prod.result.campaign && (()=>{ const cm = prod.result.campaign;
        return <div style={{marginTop:10, display:'flex', gap:8, flexWrap:'wrap', alignItems:'center', fontFamily:F.mono, fontSize:10, color:C.tx2}}>
          <span style={{fontWeight:700, color:C.tx3}}>CAMPAIGN:</span>
          <span>{cm.runs} runs</span><span style={{color:C.line2}}>·</span>
          <span>avg <b style={{color:C.tx}}>{cm.avg_run_units}</b> u/run</span><span style={{color:C.line2}}>·</span>
          <span>min-run {cm.min_run>0?<b style={{color:C.ac}}>{cm.min_run}u</b>:'off'}</span>
          <Tag c={cm.min_run>0?'b':'w'}>{cm.min_run>0?'campaigned':'free lots'}</Tag>
        </div>;
      })()}
      <label style={{display:'flex', alignItems:'center', gap:7, marginTop:10, fontFamily:F.mono, fontSize:10, fontWeight:700, color:C.tx2, cursor:'pointer'}}>
        <input type="checkbox" checked={timePhased} onChange={e=>setConfig({ prodTimePhased:e.target.checked })}/>
        TIME-PHASED MPS · production tracks the weekly demand curve (no-backorder inventory balance)
        <span style={{fontWeight:400, color:C.tx3}}>{timePhased?'— on: schedule follows demand':'— off: minimize makespan (SKUs front-load)'}</span>
      </label>
      <Reading formula="OT cost = workers × hrs × rate × 1.5   ·   shutdown net = wage saved over an idle run − one-off rehire   ·   time-phased: inv[t] = inv[t−1] + prod·yield − demand[t] ≥ 0   ·   campaign: x[k,l,t] ≥ min_run·y[k,l,t]"
        soWhat={timePhased
          ? "Time-phased ON: the MPS below tracks committed weekly demand and the on-hand cover row stays near zero — re-run to see it. Holding cost is what stops it building everything early."
          : "The rate is seeded — enter your real ₹/hr and re-run; the overtime bill and shutdown savings move with it. Turn on time-phasing to make the schedule follow the demand curve instead of front-loading. Campaign min-run forces longer single-SKU runs (AAAA-then-BBBB) — fewer setups/changeovers, more holding."}/>
    </Card>
  );
}

// compact inline cell editor for the architecture table (raw input, tight)
function PCell({ value, onChange, w, step, suffix, text, align }){
  const [v, setV] = useState(value);
  React.useEffect(()=>{ setV(value); }, [value]);
  return (
    <span style={{display:'inline-flex', alignItems:'center', gap:2}}>
      <input type={text?'text':'number'} value={v} step={step||1}
        onChange={e=>setV(e.target.value)}
        onBlur={()=>{ if(String(v)!==String(value)) onChange(text?v:(v===''?value:Number(v))); }}
        onKeyDown={e=>{ if(e.key==='Enter') e.target.blur(); }}
        style={{ width:w||52, fontFamily:F.mono, fontSize:10.5, textAlign:align||'right', padding:'2px 4px',
          border:`1px solid ${C.line}`, background:C.paper, color:C.tx }}/>
      {suffix && <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{suffix}</span>}
    </span>
  );
}

// Batch 3 — the line → stage → machine tree is now EDITABLE master data (was a
// read-only Fact-5 bug). Each stage's machines/workers/cycle/OEE/capacity is a
// real input; line capacity & the bottleneck are DERIVED (slowest stage), so the
// "min(stage)" rule is enforced, not typed. A simple/detailed toggle hides the OEE
// decomposition for shops that only track cycle time.
function ProdArch({ prod }) {
  useMasterRev();                                   // re-render on any line/stage edit
  const [mode, setMode] = useState('detailed');     // 'detailed' = show OEE+workers, 'simple' = cycle-only
  const detailed = mode==='detailed';
  const lines = M.lines || [];
  // PR-C — line utilization now reads the SOLVED gantt (same basis as the Cycle tab's
  // Line-Load preview) when a schedule exists: monthly-equivalent volume on the line
  // = Σ(solved units) / horizon_weeks × 4.33, ÷ line cap. Falls back to the annual-demand
  // mock (demand/12) only before the first solve — labelled accordingly, never a fake-solved.
  const res = prod && prod.result;
  let solvedMonthly = null;
  if(res && res.gantt){
    const T = res.periods || 1; solvedMonthly = {};
    res.gantt.forEach(g=>{ solvedMonthly[g.line] = (solvedMonthly[g.line]||0) + g.quantity; });
    Object.keys(solvedMonthly).forEach(k=>{ solvedMonthly[k] = solvedMonthly[k] / T * 4.33; });
  }
  const cols = detailed
    ? ['Stage','Machines','Workers','Cycle','OEE','Capacity','',''  ]
    : ['Stage','Machines','Cycle','Capacity','',''];
  return (
    <div>
      <ScopeBanner kind="factory" name="Production architecture"
        code={`${lines.length} line${lines.length===1?'':'s'} · ${lines.reduce((s,l)=>s+(l.stages||[]).length,0)} stages`}
        sub="lines → stages → machines · line capacity = its slowest stage"
        right={<div style={{display:'flex', border:`2px solid ${C.ac}`}}>
          {[['detailed','OEE'],['simple','CYCLE-ONLY']].map(([v,l],i)=>(
            <button key={v} onClick={()=>setMode(v)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'3px 8px',
              border:'none', borderRight:i===0?`2px solid ${C.ac}`:'none', cursor:'pointer',
              background:mode===v?C.ac:'transparent', color:mode===v?C.onAc:C.paper}}>{l}</button>
          ))}
        </div>}/>
      <div style={{display:'flex', flexDirection:'column', gap:14}}>
        {lines.map(line=>{
          const stages = line.stages || [];
          return (
          <div key={line.id} style={{border:`2px solid ${C.line}`, background:C.bg2}}>
            <div style={{padding:'9px 11px', background:C.ink, color:C.paper, display:'flex', alignItems:'center', gap:10, flexWrap:'wrap'}}>
              <span style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>{line.id}</span>
              <PCell text value={line.name} w={150} align="left" onChange={v=>editLine(line.id,{name:v})}/>
              <label style={{display:'flex', alignItems:'center', gap:4, fontFamily:F.mono, fontSize:9, color:C.ac}}>OEE
                <PCell value={Math.round((line.oee||0)*100)} w={42} suffix="%" onChange={v=>editLine(line.id,{oee:Math.max(0,Math.min(100,v))/100})}/></label>
              <label style={{display:'flex', alignItems:'center', gap:4, fontFamily:F.mono, fontSize:9, color:C.ac}}>Shifts
                <PCell value={line.shifts!=null?line.shifts:1} w={36} onChange={v=>editLine(line.id,{shifts:Math.max(1,v)})}/></label>
              <button onClick={()=>{ if(lines.length>1) delLine(line.id); }} disabled={lines.length<=1}
                title={lines.length<=1?'keep at least one line':'remove line'}
                style={{marginLeft:'auto', cursor:lines.length<=1?'not-allowed':'pointer', border:`1.5px solid ${C.dg}`, background:'transparent', color:C.dg, fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'2px 7px', opacity:lines.length<=1?.4:1}}>✕ line</button>
            </div>
            <div style={{padding:11}}>
              <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
                <thead><tr style={{background:C.bg3}}>
                  {cols.map((h,i)=><th key={i} style={{textAlign:i===0?'left':(i>=cols.length-2?'center':'right'), padding:'4px 7px', fontSize:8.5, color:C.tx3, textTransform:'uppercase', borderBottom:`1.5px solid ${C.line2}`}}>{h}</th>)}
                </tr></thead>
                <tbody>
                  {stages.map((st,i)=>(
                    <tr key={st.id} style={{borderTop:`1px solid ${C.line2}`, background: st.bottleneck?'color-mix(in srgb,var(--ac) 14%,transparent)':C.paper}}>
                      <td style={{padding:'4px 7px'}}>
                        <PCell text value={st.name} w={120} align="left" onChange={v=>editStage(line.id,st.id,{name:v})}/>
                        <div style={{fontSize:8, color:C.tx3}}>{st.id}</div>
                      </td>
                      <td style={{padding:'4px 7px', textAlign:'right'}}><PCell value={st.m} w={40} onChange={v=>editStage(line.id,st.id,{m:Math.max(0,v)})}/></td>
                      {detailed && <td style={{padding:'4px 7px', textAlign:'right'}}><PCell value={st.w!=null?st.w:st.m} w={40} onChange={v=>editStage(line.id,st.id,{w:Math.max(0,v)})}/></td>}
                      <td style={{padding:'4px 7px', textAlign:'right'}}><PCell value={st.ct} w={46} step={0.1} suffix="min" onChange={v=>editStage(line.id,st.id,{ct:Math.max(0.1,v)})}/></td>
                      {detailed && <td style={{padding:'4px 7px', textAlign:'right'}}><PCell value={Math.round((st.oee||0)*100)} w={42} suffix="%" onChange={v=>editStage(line.id,st.id,{oee:Math.max(0,Math.min(100,v))/100})}/></td>}
                      <td style={{padding:'4px 7px', textAlign:'right'}}><PCell value={st.cap} w={64} step={10} suffix="u/mo" onChange={v=>editStage(line.id,st.id,{cap:Math.max(0,v)})}/></td>
                      <td style={{padding:'4px 7px', textAlign:'center'}}>{st.bottleneck && <span style={{fontFamily:F.mono, fontSize:8, fontWeight:700, background:C.dg, color:'#fff', padding:'1px 5px'}}>BOTTLENECK</span>}</td>
                      <td style={{padding:'4px 7px', textAlign:'center'}}>
                        <button onClick={()=>{ if(stages.length>1) delStage(line.id,st.id); }} disabled={stages.length<=1}
                          title={stages.length<=1?'keep at least one stage':'remove stage'}
                          style={{cursor:stages.length<=1?'not-allowed':'pointer', border:'none', background:'transparent', color:C.dg, fontSize:12, opacity:stages.length<=1?.3:1}}>✕</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button onClick={()=>addStage(line.id)} style={{marginTop:8, cursor:'pointer', border:`2px dashed ${C.line2}`, background:'transparent', color:C.tx2, fontFamily:F.mono, fontSize:9.5, fontWeight:700, padding:'4px 10px'}}>+ Add stage</button>
            </div>
            <div style={{padding:'8px 11px', borderTop:`2px solid ${C.line}`, background:C.bg3, display:'flex', justifyContent:'space-between', alignItems:'center'}}>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>LINE CAPACITY = slowest stage{line.bottleneck&&line.bottleneck!=='—'?` (${line.bottleneck})`:''}</span>
              <span className="num" style={{fontFamily:F.disp, fontSize:15, fontWeight:800, color:C.dg}}>{(line.cap||0).toLocaleString('en-IN')} u/mo</span>
            </div>
          </div>
        );})}
      </div>
      <button onClick={()=>addLine()} style={{marginTop:14, cursor:'pointer', border:`2px solid ${C.line}`, background:C.ink, color:C.paper, fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.04em', padding:'7px 16px'}}>+ Add production line</button>
      <div style={{marginTop:12}}>
        <Card icon="📉" title="Derived Capacities & Bottlenecks" badge={solvedMonthly?'min(stage) · solved load':'min(stage)'} badgeTone={solvedMonthly?'g':undefined}
          right={solvedMonthly ? <Provenance kind="solved" asOf={prod.ranAt?prod.ranAt.toLocaleTimeString():undefined}/> : null}
          info={{ what:'Each line is capped by its slowest stage; utilization is the solved schedule load when a plan exists.', flows:'Line cap → aggregate & production MILP.' }}
          dev={{ comp:'BottleneckTable', props:'lines, prod.result.gantt' }}>
          <DataTable cols={['Line','Bottleneck Stage','Bottleneck Cap','Line OEE','Util @ plan']} align={['left','left','right','right','right']}
            rows={M.lines.map(l=>{
              // PR-C — util from the SOLVED gantt (monthly-equiv) when available; else the annual-demand mock.
              const monthly = solvedMonthly
                ? (solvedMonthly[l.name] || 0)
                : M.products.filter(p=>p.cat==='Finished'&&p.line===l.id).reduce((s,p)=>s+p.demand/12,0);
              const util = l.cap ? monthly/l.cap : 0;
              return {cells:[l.id, l.bottleneck, `${l.cap.toLocaleString('en-IN')} u/mo`, `${(l.oee*100).toFixed(0)}%`,
                <span style={{fontWeight:700, color: util>0.95?C.dg:C.tx}}>{(util*100).toFixed(0)}%{solvedMonthly?'':' ·seed'}</span>]};
            })}/>
          <Reading formula={solvedMonthly?"util = (Σ solved units on line ÷ horizon weeks × 4.33) ÷ line capacity":"util = Σ(monthly demand of SKUs on the line) ÷ line capacity (pre-solve estimate)"} soWhat={solvedMonthly?"This is the same solved load the Cycle-tab preview shows — a line over ~95% has no slack and its capacity dual turns positive on Plan.":"Run the schedule (⚡) to replace this annual-demand estimate with the solved per-line load; a line over ~95% earns added capacity on Plan."}/>
        </Card>
      </div>
    </div>
  );
}

function ProdCycle({ p, prod, config, setConfig, onNav }) {
  // PR-5 — flat rate (rate x run-hours) is the SIMPLE default; the OEE
  // decomposition is opt-in behind "Advanced" for shops that measure the losses.
  const [advanced, setAdvanced] = useState(false);
  const capMode = advanced ? 'oee' : 'flat';
  // PR-B — cycle time + assigned line are now GOVERNED (seed→override, written to
  // config.prodRouting[sku]) and flow straight into productionPayload. Editing them
  // and re-running re-pins the SKU and re-prices its throughput — no longer display-only.
  const route = config.prodRouting || {};
  const ov = route[p.sku] || {};
  const setRoute = (patch)=> setConfig({ prodRouting: { ...route, [p.sku]: { ...ov, ...patch } } });
  const cycSet = ov.cycle != null && ov.cycle !== '';
  const lineSet = ov.line != null && ov.line !== '';
  const effCycle = cycSet ? Number(ov.cycle) : p.cycle;
  const effLine  = lineSet ? ov.line : p.line;
  const flatRate = (60/effCycle).toFixed(1);
  const effRate = (60/effCycle*p.oee).toFixed(1);
  // Line-load preview reads the REAL solve: this SKU's assigned line, util/week
  // = sum(scheduled units on the line) / weekly capacity (cap / 4.33).
  const line = M.lines.find(l=>l.id===effLine);
  const wkCap = line ? line.cap/4.33 : 0;
  const res = prod && prod.result;
  let load = null;
  if(res && res.gantt && line){
    const T = res.periods||0; const per = Array(T).fill(0);
    res.gantt.filter(g=>g.line===line.name).forEach(g=>{ per[g.period]+=g.quantity; });
    load = per.map(q=> wkCap ? Math.round(q/wkCap*100) : 0);
  }
  return (
    <Grid cols={2}>
      <Card icon="🏭" title="Cycle Time & Line Assignment" badge={p.line} info={{ what:'Per-SKU cycle time + line assignment (a line property, owned here).', flows:'Cycle/line → production MILP & MPS.' }}
        dev={{ comp:'CycleEditor', props:'prod.cycle, prod.line, capMode', state:'products[id].{cycle,line,capMode}', note:'OEE is OPTIONAL — flat rate (rate×hours) is allowed for shops that don\u2019t track OEE.' }}
        right={<label style={{display:'flex', alignItems:'center', gap:5, marginRight:8, fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.tx2, cursor:'pointer'}}>
          <input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)}/>ADVANCED · OEE
        </label>}>
        <Grid cols={2} gap={8}>
          <SolverInput label="Cycle Time" seed={p.cycle} value={ov.cycle}
            onChange={v=>setRoute({ cycle:v })} min={0.1} suffix="min/u" hint="re-prices throughput"/>
          <Field label={`Assigned Line${lineSet?'':' · seed'}`}>
            <Select value={effLine} options={(M.lines||[]).map(l=>l.id)}
              onChange={v=>setRoute({ line:v })}/>
          </Field>
          {capMode==='oee'
            ? <Field label="OEE"><NumInput value={(p.oee*100).toFixed(0)} suffix="%"/></Field>
            : <Field label="Run hours / day"><NumInput value="20"/></Field>}
          <Field label="Effective Rate"><NumInput value={capMode==='oee'?effRate:flatRate} suffix="u/hr" disabled/></Field>
          <Field label="Batch Size · MOQ" span={2}><NumInput value={p.moq}/></Field>
        </Grid>
        {capMode==='oee'
          ? <Reading formula={`theoretical ${flatRate} u/hr × OEE ${(p.oee*100).toFixed(0)}% = ${effRate} u/hr effective`}
              soWhat="OEE decomposes capacity into availability × performance × quality — use it when you measure those losses."/>
          : <Reading formula={`flat capacity = ${flatRate} u/hr × run hours (no OEE decomposition)`}
              soWhat="If you don\u2019t track OEE, a flat rate × hours is a valid capacity input — the MILP doesn\u2019t require the decomposition."/>}
      </Card>
      <Card icon="📅" title="Line Load Preview" badge={line?line.name:'—'} info={{ what:'Where this SKU’s line sits on the solved schedule — weekly utilization from the MILP.', flows:'Shared with the schedule + capacity panel.' }}
        right={res ? <Provenance kind="solved"/> : null}
        dev={{ comp:'LineLoadMini', props:'prod.result.gantt, line.cap' }}>
        {load ? (
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {M.periods.slice(0,8).map((wk,i)=> i<load.length ? (
              <div key={i} style={{display:'flex', alignItems:'center', gap:8}}>
                <span style={{fontFamily:F.mono, fontSize:10, width:42, color:C.tx2}}>{wk.label}</span>
                <MiniBar v={load[i]} max={100} color={load[i]>95?C.dg:C.ink} h={12}/>
                <span className="num" style={{fontFamily:F.mono, fontSize:10, width:36, textAlign:'right', color:load[i]>95?C.dg:C.tx}}>{load[i]}%</span>
              </div>
            ) : null)}
            <div style={{marginTop:4, fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>util = sum(units on {line&&line.name}) / {Math.round(wkCap).toLocaleString('en-IN')} u/wk</div>
          </div>
        ) : (
          <div style={{padding:'18px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10, color:C.tx3, border:`2px dashed ${C.line2}`}}>Run the schedule (⚡ above) to see this line’s solved weekly load.</div>
        )}
      </Card>
    </Grid>
  );
}

function ProdMPS({ prod, planning, item }){
  const [grain, setGrain] = useState('week');
  const [scope, setScope] = useState('all');
  const res = prod && prod.result;
  if(!res || !res.gantt){
    return (
      <Card icon="📅" title="Master Production Schedule (MPS)" badge="not solved"
        info={{ what:'Time-phased production quantities per SKU, straight from the production MILP.', flows:'MPS → MRP explosion & order promising.' }}>
        <div style={{padding:'22px 12px', textAlign:'center', fontFamily:F.mono, fontSize:11, color:C.tx3, border:`2px dashed ${C.line2}`}}>
          No schedule yet — press <b style={{color:C.tx}}>⚡ Run schedule</b> (top right) to solve the production MILP.<br/>The MPS, day drill, ATP and capacity panels all read its output.
        </div>
      </Card>
    );
  }
  const T = res.periods || 0;
  const periods = (M.periods || []).slice(0, T);
  // per-SKU weekly quantities from the solved gantt (g.product = the SKU code we passed).
  const bySku = {};
  res.gantt.forEach(g=>{ (bySku[g.product] = bySku[g.product] || Array(T).fill(0))[g.period] += g.quantity; });
  const skus = Object.keys(bySku);
  // PR-A — solved per-period ending inventory (only present when time-phased was requested).
  const invBy = {}; (res.projected_inventory || []).forEach(pi=>{ invBy[pi.name] = pi.ending_inventory; });
  const timePhased = !!res.time_phased;
  const selSku = item && item.id;
  const shown = (scope==='selected' && selSku && bySku[selSku]) ? [selSku] : skus;
  // calendar-aware day drill across the frozen fence (Sundays + Indian holidays excluded).
  const frozen = Math.max(1, Math.min(Number(planning.frozenWeeks) || 2, T));
  const dayCols = [];   // [{wk, iso, label, dow}]
  periods.slice(0, frozen).forEach((wk, wi)=>{
    (window.productionWorkDays(wk.iso, planning.workDaysPerWeek) || []).forEach(d=>dayCols.push({ ...d, wk:wi }));
  });
  // spread a week's solved qty across its working days (even split, remainder front-loaded).
  const spread = (total, nDays)=>{
    if(nDays<=0) return [];
    const base = Math.floor(total/nDays); let rem = total - base*nDays;
    return Array.from({ length:nDays }, ()=>{ const e = rem>0?1:0; if(rem>0) rem--; return base+e; });
  };
  const dayQ = {};
  shown.forEach(sku=>{
    const arr = [];
    for(let wi=0; wi<frozen; wi++){
      const nd = dayCols.filter(d=>d.wk===wi).length;
      spread(bySku[sku][wi] || 0, nd).forEach(v=>arr.push(v));
    }
    dayQ[sku] = arr;
  });
  const maxWk = Math.max(1, ...shown.flatMap(s=>bySku[s]));
  return (
    <Card icon="📅" title="Master Production Schedule (MPS)" badge={grain==='day'?`frozen ${frozen}w · daily`:'weekly'}
      info={{ what:'Time-phased production quantities per SKU, straight from the production MILP gantt.', flows:'MPS → MRP explosion & order promising.' }}
      dev={{ comp:'MPSVizCard', props:'prod.result.gantt, grain, scope' }}
      right={<div style={{display:'flex', gap:8, marginRight:8, alignItems:'center'}}>
        {selSku && bySku[selSku] && <div style={{display:'flex', border:`2px solid ${C.line}`}}>
          {[['all','ALL'],['selected',selSku.slice(4)]].map(([v,l],i)=><button key={v} onClick={()=>setScope(v)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'3px 9px', border:'none', borderRight:i===0?`2px solid ${C.line}`:'none', cursor:'pointer', background:scope===v?C.ink:C.paper, color:scope===v?C.paper:C.tx}}>{l}</button>)}
        </div>}
        <div style={{display:'flex', border:`2px solid ${C.line}`}}>
          {['day','week'].map((g,i)=><button key={g} onClick={()=>setGrain(g)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'3px 9px', border:'none', borderRight:i===0?`2px solid ${C.line}`:'none', cursor:'pointer', background:grain===g?C.ac:C.paper, color:grain===g?C.onAc:C.tx, textTransform:'uppercase'}}>{g}</button>)}
        </div>
        <Provenance kind="solved" asOf={prod.ranAt?prod.ranAt.toLocaleTimeString():undefined}/>
      </div>}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>SKU</th>
            {grain==='week'
              ? periods.map(w=><th key={w.id} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{w.label}</th>)
              : dayCols.map((d,i)=><th key={i} title={d.iso} style={{color:C.paper, textAlign:'right', padding:'6px 7px', fontSize:8.5, background:d.wk%2?C.ink:'#000'}}>{d.dow} {d.label.slice(0,2)}</th>)}
          </tr></thead>
          <tbody>
            {shown.map((sku,ri)=>(
              <React.Fragment key={sku}>
              <tr style={{borderTop:`1px solid ${C.line2}`, background: ri%2?C.bg3:C.paper}}>
                <td style={{padding:'5px 9px', fontWeight:700}}>{sku}</td>
                {grain==='week'
                  ? bySku[sku].map((q,i)=>(
                      <td key={i} className="num" style={{textAlign:'right', padding:'5px 9px', position:'relative', color:q?C.tx:C.tx3}}>
                        <span style={{position:'relative', zIndex:1}}>{q||'·'}</span>
                        {q>0 && <span style={{position:'absolute', right:4, bottom:3, height:3, width:`${q/maxWk*40}px`, background:C.ac}}/>}
                      </td>
                    ))
                  : (dayQ[sku]||[]).map((q,i)=>(
                      <td key={i} className="num" style={{textAlign:'right', padding:'5px 7px', color: q?C.tx:C.tx3, background: dayCols[i] && dayCols[i].wk%2?'transparent':C.bg4}}>{q||'·'}</td>
                    ))}
              </tr>
              {timePhased && grain==='week' && invBy[sku] && (
                <tr style={{background: ri%2?C.bg3:C.paper}}>
                  <td style={{padding:'2px 9px 5px', fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>↳ on-hand cover</td>
                  {invBy[sku].slice(0,T).map((v,i)=>(
                    <td key={i} className="num" style={{textAlign:'right', padding:'2px 9px 5px', fontSize:9, color:C.tx3}}>{Math.round(v)||'·'}</td>
                  ))}
                </tr>
              )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <Reading formula={grain==='day'?"daily qty = solved weekly MPS spread across that week's working days (Sundays + Indian holidays excluded)":(timePhased?'time-phased MPS = production MILP tracking committed weekly demand (inv ≥ 0 each week)':'weekly MPS = production MILP gantt, summed per SKU per week')}
        soWhat={grain==='day'?`Inside the ${frozen}-week frozen fence the schedule is executable by dated working day — ${dayCols.length} real working days, holidays already removed.`:(timePhased?'The on-hand cover row stays near zero — production follows demand week by week instead of front-loading. Turn time-phasing off (Solver Parameters) to see the makespan-minimizing build.':'Each cell is solved output, not a target — switch to day to release dated work inside the fence. Turn on time-phasing (Solver Parameters) to make the schedule follow the demand curve.')}/>
    </Card>
  );
}

function ProdATP({ prod, planning }){
  const res = prod && prod.result;
  if(!res || !res.gantt){
    return (
      <Card icon="📦" title="Order Promising · ATP / CTP" badge="not solved"
        info={{ what:'Uncommitted supply = solved production − committed demand.', flows:'ATP → quoting & MTO acceptance.' }}>
        <div style={{padding:'18px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Run the schedule to derive available-to-promise from the solved MPS.</div>
      </Card>
    );
  }
  const T = res.periods || 0;
  const periods = (M.periods || []).slice(0, T);
  const bySku = {};
  res.gantt.forEach(g=>{ (bySku[g.product] = bySku[g.product] || Array(T).fill(0))[g.period] += g.quantity; });
  const skus = Object.keys(bySku);
  // projected available balance = running cumulative(solved production − committed demand).
  const atpRows = skus.map(sku=>{
    const dem = finishedWeeklyDemand(sku, planning, T);
    let bal = 0; const atp = bySku[sku].map((q,t)=>{ bal += q - (dem[t]||0); return Math.round(bal); });
    return { sku, atp };
  });
  return (
    <Card icon="📦" title="Order Promising · ATP / CTP" badge="available-to-promise"
      right={<Provenance kind="derived"/>}
      info={{ what:'Projected available balance = cumulative(solved production − committed demand). Negative ⇒ over-committed.', flows:'ATP → quoting & MTO acceptance.' }}
      dev={{ comp:'ATPCard', props:'prod.result.gantt, finishedWeeklyDemand' }}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9}}>SKU</th>
            {periods.map(w=><th key={w.id} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{w.label}</th>)}
          </tr></thead>
          <tbody>
            {atpRows.map((row)=>(
              <tr key={row.sku} style={{borderTop:`1px solid ${C.line2}`}}>
                <td style={{padding:'5px 9px', fontWeight:700}}>{row.sku}</td>
                {row.atp.map((q,i)=>(
                  <td key={i} className="num" style={{textAlign:'right', padding:'5px 9px', background: q<0?'color-mix(in srgb,var(--dg) 16%,transparent)': q<6?C.bg4:'color-mix(in srgb,var(--gn) 12%,transparent)', fontWeight:700, color: q<0?C.dg:C.tx}}>{q}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Reading formula="ATP(t) = Σ≤t (solved production − committed demand)   ·   CTP = ATP + what the line could still produce in time"
        soWhat={atpRows.length?`${atpRows[0].sku}: a negative cell means demand has outrun the schedule by that week — expedite, pull a later batch forward, or quote the next positive week.`:'Run the schedule to populate.'}/>
    </Card>
  );
}

function ProdCapacity({ prod, rateIsSeed, laborRate }){
  const res = prod && prod.result;
  if(!res || !res.lines){
    return (
      <Card icon="⚙️" title="Capacity Loading & Shutdown" badge="not solved"
        info={{ what:'Per-line utilization, overtime and idle-week shutdown candidates from the solve.', flows:'Shutdowns → workforce + capital plans.' }}>
        <div style={{padding:'18px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Run the schedule to load the lines and evaluate idle-week shutdowns.</div>
      </Card>
    );
  }
  const recs = res.shutdown_recommendations || [];
  const totGain = recs.reduce((s,r)=>s+(r.net_gain||0), 0);
  return (
    <div style={{display:'flex', flexDirection:'column', gap:12}}>
      <Card icon="⚙️" title="Capacity Loading" badge={`${res.lines.length} lines`}
        right={<Provenance kind="solved" asOf={prod.ranAt?prod.ranAt.toLocaleTimeString():undefined}/>}
        info={{ what:'Per-line active periods, utilization, solver-chosen overtime and changeovers.', flows:'Loading → capacity duals on Plan.' }}
        dev={{ comp:'DataTable', props:'prod.result.lines' }}>
        <DataTable cols={['Line','Util','Active wks','Produced','OT hrs','OT cost','Changeovers']} align={['left','right','right','right','right','right','right']}
          rows={res.lines.map(l=>({cells:[
            l.name,
            <span style={{fontWeight:700, color:l.utilization>95?C.dg:C.tx}}>{l.utilization}%</span>,
            l.active_periods, (l.total_produced||0).toLocaleString('en-IN'),
            l.overtime_hours, `₹${(l.overtime_cost||0).toLocaleString('en-IN')}`, l.changeovers]}))}/>
        <Reading formula="util = active periods ÷ horizon   ·   OT cost = workers × hrs × rate × 1.5"
          soWhat={`Overtime is priced at the governed labor rate (₹${laborRate}/hr${rateIsSeed?' · seed':''}); workers/line come from the bottleneck stage's machine count. A line under the shutdown threshold for a run of weeks becomes a candidate below.`}/>
      </Card>
      <Card icon="🛑" title="Idle-Week Shutdown Candidates" badge={recs.length?`${recs.length} · net ₹${Math.round(totGain).toLocaleString('en-IN')}`:'none'} badgeTone={recs.length?'y':undefined}
        info={{ what:'Post-solve heuristic: consecutive sub-threshold weeks where wage saved over the run beats the one-off rehire cost.', flows:'Shutdowns → workforce + S&OP.' }}
        dev={{ comp:'ShutdownTable', props:'prod.result.shutdown_recommendations' }}>
        {recs.length ? (
          <DataTable cols={['Line','Idle weeks','Avg util','Wage saved','Rehire cost','Net gain']} align={['left','left','right','right','right','right']}
            rows={recs.map(r=>({cells:[
              r.line_name, `W${r.from_period+1}–W${r.to_period+1} (${r.idle_periods})`,
              `${r.avg_util_pct}%`, `₹${r.savings.toLocaleString('en-IN')}`, `₹${r.rehire_cost.toLocaleString('en-IN')}`,
              <span style={{fontWeight:700, color:C.gn}}>₹{r.net_gain.toLocaleString('en-IN')}</span>]}))}/>
        ) : (
          <div style={{padding:'14px 12px', fontFamily:F.mono, fontSize:10, color:C.tx3, border:`2px dashed ${C.line2}`}}>
            No shutdown beats its rehire cost at {res.shutdown_threshold_pct}% threshold and ₹{laborRate}/hr{rateIsSeed?' (seed)':''} — every line earns its idle wages back. Lower the threshold or enter your real rate to re-test.
          </div>
        )}
        <Reading formula="net = (workers × shifts × hrs × rate) × idle weeks − (workers × rate × 80 hr notice)"
          soWhat={recs.length?`Shutting the flagged runs nets ₹${Math.round(totGain).toLocaleString('en-IN')} over paying idle wages — rehire is charged once per run, not per week.`:'When a line sits idle long enough the wage saved outruns the one-off rehire cost; none cross that line here.'}/>
      </Card>
    </div>
  );
}

function ProdChange() {
  useMasterRev();                                    // re-render on matrix edits
  const skus=['TPA-4471','TPA-3215','TPA-9904','TPA-2188'];
  // build the nested {from:{to:min}} matrix the sequence solver wants (skip '—' diagonal).
  const seq = useSolve('/api/solve/sequence', ()=>{
    const matrix={};
    skus.forEach((a,ri)=>{ matrix[a]={}; skus.forEach((b,ci)=>{ const v=M.changeover[ri][ci]; if(typeof v==='number') matrix[a][b]=v; }); });
    return { skus, changeover_matrix:matrix };
  });
  const sres = seq.result;
  // client-side fallback (brute-force the fixed order) until the solver runs.
  const order=[0,2,1,3];
  const seqCost=(s)=>{ let t=0; for(let i=0;i<s.length-1;i++){ const v=M.changeover[s[i]][s[i+1]]; if(typeof v==='number') t+=v; } return t; };
  const alpha=seqCost([0,1,2,3]);
  // solved sequence (sku names) → index order for the chips; fall back to the fixed order.
  const solvedOrder = sres && Array.isArray(sres.sequence) ? sres.sequence.map(s=>skus.indexOf(s)).filter(i=>i>=0) : null;
  const chosenIdx = solvedOrder && solvedOrder.length===skus.length ? solvedOrder : order;
  const opt = sres && sres.total_changeover_min!=null ? sres.total_changeover_min : seqCost(order);
  const saved = sres && sres.sequence_saving_min!=null ? sres.sequence_saving_min : (alpha-opt);
  return (
    <Grid cols={2}>
      <Card icon="🔀" title="Changeover Matrix" badge="editable · setup hrs" badgeTone="y" info={{ what:'Setup time (hrs) for each from→to SKU transition — editable master data. The diagonal is self-to-self (no changeover).', flows:'Matrix → sequencing (ATSP heuristic) & production setup.' }}
        dev={{ comp:'ChangeoverMatrix', props:'M.changeover', state:'M.changeover[from][to] via setChangeover' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              <th style={{color:C.paper, padding:'5px 7px', fontSize:8.5}}>FROM ↓ TO →</th>
              {skus.map(s=><th key={s} style={{color:C.paper, padding:'5px 7px', fontSize:8.5}}>{s.slice(4)}</th>)}
            </tr></thead>
            <tbody>
              {M.changeover.map((row,ri)=>(
                <tr key={ri} style={{borderTop:`1px solid ${C.line2}`}}>
                  <td style={{padding:'5px 7px', fontWeight:700, background:C.bg3}}>{skus[ri].slice(4)}</td>
                  {row.map((v,ci)=>(
                    <td key={ci} className="num" style={{textAlign:'center', padding:'3px 5px', background: ri===ci?C.bg4: typeof v==='number'&&v>2?'color-mix(in srgb,var(--dg) 16%,transparent)':C.paper, fontWeight:700}}>
                      {ri===ci ? '—' : <PCell value={v} w={44} step={0.1} onChange={nv=>setChangeover(ri,ci,nv)}/>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Red = high penalty — the sequencer avoids these transitions. Edit a cell and re-run the schedule to see the run order shift.</div>
      </Card>
      <Card icon="⚡" title="Chosen Run Order" badge={`−${saved.toFixed(1)} hrs`} badgeTone="y" info={{ what:'The sequence the solver picks and the setup time it saves vs alphabetical.', flows:'Order → production schedule.' }}
        right={sres ? <Provenance kind="solved" asOf={seq.ranAt?seq.ranAt.toLocaleTimeString():undefined}/> : <Btn kind="primary" sm onClick={()=>seq.run().catch(()=>{})}>{seq.solving?'⏳ …':'⚡ Sequence'}</Btn>}
        dev={{ comp:'SequenceResult', props:'solve.sequencing' }}>
        {seq.error && <div style={{marginBottom:8, fontFamily:F.mono, fontSize:9.5, color:C.dg}}>Sequencer: {seq.error}</div>}
        <SubLabel>Alphabetical</SubLabel>
        <div style={{display:'flex', alignItems:'center', gap:4, flexWrap:'wrap', marginBottom:10}}>
          {[0,1,2,3].map((s,i)=><React.Fragment key={i}><span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line2}`, background:C.bg3}}>{skus[s].slice(4)}</span>{i<3 && <span style={{color:C.tx3}}>→</span>}</React.Fragment>)}
          <span className="num" style={{marginLeft:'auto', fontFamily:F.disp, fontWeight:800}}>{alpha.toFixed(1)} hrs</span>
        </div>
        <SubLabel>{sres?`Solver-optimized · ${sres.basis||'exact'}`:'Solver-optimized'}</SubLabel>
        <div style={{display:'flex', alignItems:'center', gap:4, flexWrap:'wrap'}}>
          {chosenIdx.map((s,i)=><React.Fragment key={i}><span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line}`, background:C.ac, color:C.onAc}}>{skus[s].slice(4)}</span>{i<chosenIdx.length-1 && <span style={{color:C.tx3}}>→</span>}</React.Fragment>)}
          <span className="num" style={{marginLeft:'auto', fontFamily:F.disp, fontWeight:800}}>{opt.toFixed(1)} hrs</span>
        </div>
        <Reading formula={sres?`shortest Hamiltonian path over the changeover matrix (${sres.basis||'exact'}) vs averaged approximation`:"min Σ changeover(seqᵢ, seqᵢ₊₁) over all permutations"}
          soWhat={`Re-ordering saves ${saved.toFixed(1)} setup hours per cycle — roughly ₹${Math.round(saved*4200).toLocaleString('en-IN')} at the setup rate.${sres?'':' Press ⚡ Sequence to solve it against the live engine.'}`}/>
      </Card>
    </Grid>
  );
}
window.StageProduction = StageProduction;
