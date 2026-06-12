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
  const setupCost = _eff(config.prodSetupCost, 50);            // ₹/lot — governed, was hardcoded 50
  const routing = config.prodRouting || {};
  // ONE opts truth: the tab's solve builds from the SAME productionOptsFromConfig the
  // loop uses — the hand-rolled opts object here had silently dropped the G-P4 labor
  // caps (and would have dropped rehireNoticeHrs); two builders, one drift. Found
  // while governing rehire_notice_hrs (open-ends close, 2026-06-11).
  const prod = useSolve('/api/solve/production', ()=>productionPayload(planning, productionOptsFromConfig(config)), { solveKey:'production' });  // LP-C hydrate from loop cache
  const { stale, ranAt } = useStale('production');
  const runProd = ()=> prod.run().then(d=>{ markSolved('production'); return d; }).catch(()=>{});
  const tabs = [
    { id:'arch',   label:'Architecture' },
    { id:'cycle',  label:'Cycle & Line' },
    { id:'sched',  label:'Schedule' },
    { id:'change', label:'Changeover' },
    { id:'profit', label:'Profit-Mix' },   // V2-7 — profit-mix result HOME (moved out of Console; one-result-one-home)
  ];
  return (
    <div>
      <StageHeader n="06" title="Production Architecture" kicker="Lines → stages → machines · OEE · bottleneck = min(stage) · cycle/line · MPS(day) · order promising"
        right={<Btn kind="accent" onClick={runProd}>{prod.solving?'⏳ Scheduling…':'⚡ Run schedule'}</Btn>}/>
      <ItemSelector onNav={onNav}/>
      {/* ① DECIDE strip (Part 3.2) — answers "can the lines build the plan?" from the SOLVED schedule only */}
      <div style={{padding:'8px 18px', borderBottom:`2px solid ${C.line}`, background:C.paper}}>
        <ProdDecideStrip res={prod && prod.result}/>
      </div>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:18}}>
        <SolverExplain id="production"/>
        {prod.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Production MILP: {prod.error}</div>}
        {sub==='arch'   && <StageSection step="1" scope="global" title="Architecture" sub="line → stage → machine tree · the slowest stage caps the line"><ProdArch prod={prod}/></StageSection>}
        {sub==='cycle'  && <StageSection step="1" scope="item" title={`Cycle & Line · ${p.name}`} sub="cycle time and line assignment are line properties (moved here from Products)"><ProdCycle p={p} prod={prod} config={config} setConfig={setConfig} onNav={onNav}/></StageSection>}
        {sub==='sched'  && <>
          <StageSection step="1" scope="global" title="Solver Parameters" sub="governed inputs — seed defaults you may override; the rate prices overtime and shutdown savings">
            <ProdParams config={config} setConfig={setConfig} prod={prod} ranAt={ranAt}/>
          </StageSection>
          {stale && <StaleMark since="(demand or cost inputs changed)" onNav={()=>runProd()} go="rerun"/>}
          <StageSection step="2" scope="global" title="Master Production Schedule" sub="time-phased quantities from the production MILP across all SKUs — weekly, with a calendar-aware day drill inside the frozen fence (toggle to the selected SKU in the card)"><ProdMPS prod={prod} planning={planning} item={item} runProd={runProd}/></StageSection>
          {/* V3-7 · VIS-4 — the Step-4 picture: the same solved gantt as a ribbon */}
          <StageSection step="3" scope="global" title="Bottleneck Gantt · where the minutes go" sub="the solved schedule as one ribbon per line — SKU slices per week, changeover slivers, the busiest line in red"><Vis4GanttRibbon res={prod && prod.result} ranAt={ranAt}/></StageSection>
          <StageSection step="4" scope="global" title="Order Promising · ATP / CTP" sub="uncommitted supply = solved production − committed demand, carried period to period"><ProdATP prod={prod} planning={planning}/></StageSection>
          <StageSection step="5" scope="global" title="Capacity Loading & Shutdown" sub="per-line utilization, overtime and idle-week shutdown candidates from the solve"><ProdCapacity prod={prod} rateIsSeed={config.prodLaborRate==null||config.prodLaborRate===''} laborRate={laborRate}/></StageSection>
        </>}
        {sub==='change' && <StageSection step="1" scope="global" title="Sequence-Dependent Changeover" sub="the matrix, plus the solver's chosen run order and the minutes it saves"><ProdChange/></StageSection>}
        {/* V2-7 — one-result-one-home: the profit-mix LP's result + glass-box explainer +
            prove-it live HERE (the tab that owns the make/drop decision). The Console keeps
            only a one-line KPI + freshness chip linking here. */}
        {sub==='profit' && <>
          <StageSection step="1" scope="global" title="Profit-Maximising Mix" sub="contribution-maximising make/drop ration under capacity + demand ceilings — with the plain-English dual explainer and 🧪 prove-it"><ResProfit/></StageSection>
          {/* V3-3 · VIS-6 — the Learn band: the same LP as a picture, 2 SKUs at a time */}
          <StageSection step="2" scope="global" title="Learn · why the optimum is a corner" sub="the live LP restricted to two SKUs you pick — real capacity lines, real demand ceilings, real margins; the toy sliders write nothing"><Vis6FeasibleRegion/></StageSection>
          {/* V3-7 · VIS-5 — Goldratt's next step: price what ELEVATING the constraint is worth */}
          <StageSection step="3" scope="global" title="Elevate the constraint — what is one more hour worth?" sub="live profit-mix dual × hours freed → real NPV solve at the governed hurdle; the capex/hours/life levers are what-ifs that write nothing"><Vis5Elevate/></StageSection>
          {/* Q7b — the deliberate open end from V2-2: margins at landed / signal-adjusted costs
              stay a SENSITIVITY (the LP keeps optimising on effUnitCost; nothing here is silent) */}
          <StageSection step="4" scope="global" title="Margin sensitivity — landed & signal-adjusted costs" sub="advisory: what each SKU's margin (and the optimal mix) would look like at cost-to-gate or signal-shocked material — the committed LP basis is untouched"><Q7bMarginSensitivity/></StageSection>
        </>}
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
      dev={{ comp:'GovField', props:'config.{prodLaborRate,prodShutdownPct,prodTimePhased,prodHoldingCost,prodSetupCost,prodCampaignMinRun,prodLaborHeadcountCap,prodLaborOtCapHrs} (token cfg.prod → production · aggregate · linecap)', state:'config.*' }}>
      <Grid cols={3}>
        <GovField label="Line labor rate" token="cfg.prod" seed={120} value={config.prodLaborRate}
          onChange={v=>setConfig({ prodLaborRate:v })} min={0} suffix="₹/hr"
          hint="prices OT + shutdown savings"
          why="Prices overtime and idle-week shutdown savings in the schedule MILP; the sequencer values a saved setup hour at the same rate."
          formula="OT cost = workers × hrs × rate × 1.5 · shutdown net = wage saved over the idle run − one-off rehire"/>
        <GovField label="Shutdown threshold" token="cfg.prod" seed={25} value={config.prodShutdownPct}
          onChange={v=>setConfig({ prodShutdownPct:v })} min={0} max={100} suffix="% util"
          hint="idle runs below this are candidates"
          why="Utilization floor below which a run of idle weeks becomes a shutdown candidate — a post-solve heuristic; it never changes the MILP itself."
          formula="candidate when util_t < threshold for consecutive weeks AND wage saved > rehire cost"/>
        <GovField label="Rehire notice" token="cfg.prod" seed={80} value={config.prodRehireNoticeHrs}
          onChange={v=>setConfig({ prodRehireNoticeHrs:v })} min={0} suffix="hrs"
          hint="one-off cost of restarting after a shutdown (80 = 2wk × 40)"
          why="The hours of paid notice it takes to bring the crew back after an idle-week shutdown — the one-off cost a shutdown must beat before the wage saving is real. Was the last ungoverned payload literal (TODO-GOV, ledgered in PAYLOAD_LITERALS.md)."
          formula="rehire cost = workers × hourly rate × notice hrs · shutdown worth it when wage saved > rehire"/>
        {timePhased && <GovField label="Holding cost" token="cfg.prod" seed={2} value={config.prodHoldingCost}
          onChange={v=>setConfig({ prodHoldingCost:v })} min={0} suffix="₹/u/wk"
          hint="penalizes building ahead of demand"
          why="With time-phasing on, this is the only force stopping the schedule from building everything in week 1 — it prices each unit-week of early build."
          formula="inv[t] = inv[t−1] + prod·yield − demand[t] ≥ 0 · cost += holding × inv[t]"/>}
        <GovField label="Campaign min-run" token="cfg.prod" seed={0} value={config.prodCampaignMinRun}
          onChange={v=>setConfig({ prodCampaignMinRun:v })} min={0} integer suffix="u/run"
          hint="PR-4 — min units per setup (0 = off)"
          why="Forces longer single-SKU runs (AAAA-then-BBBB) — fewer setups and changeovers, traded against more holding."
          formula="x[k,l,t] ≥ min_run × y[k,l,t]"/>
        <GovField label="Setup cost" token="cfg.prod" seed={50} value={config.prodSetupCost}
          onChange={v=>setConfig({ prodSetupCost:v })} min={0} suffix="₹/lot"
          hint="drives the lot-size vs holding trade; risk sim prices the same value"
          why="Fixed ₹ charged once per production lot — drives the lot-size vs holding trade; the Monte-Carlo risk sim prices the identical value."
          formula="cost += setup_cost × y[k,l,t] (one per lot started)"/>
        {/* G-P4 — optional labor envelope: headcount cap (× governed workDays×hrsPerShift regular budget) + weekly OT cap */}
        <GovField label="Labor headcount cap" token="cfg.prod" seed={0} value={config.prodLaborHeadcountCap}
          onChange={v=>setConfig({ prodLaborHeadcountCap:v })} min={0} integer suffix="heads"
          hint="G-P4 — 0 = unbounded (machine-constrained only)"
          why="Caps the regular labor pool the schedule may draw on. 0 = unbounded (machine-constrained only); a tight cap forces overtime first, then infeasibility."
          formula="regular labor hrs/wk ≤ heads × workDays × hrsPerShift"/>
        <GovField label="Weekly OT cap" token="cfg.prod" seed={0} value={config.prodLaborOtCapHrs}
          onChange={v=>setConfig({ prodLaborOtCapHrs:v })} min={0} suffix="hrs/wk"
          hint="G-P4 — 0 = unbounded"
          why="Ceiling on overtime hours per week. 0 = unbounded; with the headcount cap binding, this is the lever that tips the schedule infeasible."
          formula="Σ OT_t ≤ cap (hrs/wk)"/>
      </Grid>
      {/* V4-3 — OT purchase grain: per-hour (pay exactly the hours used, legacy) vs
          per-shift (crews are called in for whole indivisible blocks and the FULL block
          is paid even when partly used). An explicit toggle, never a silent swap. */}
      <div data-vis="v4-otmode" style={{display:'flex', alignItems:'center', gap:12, marginTop:11, flexWrap:'wrap'}}>
        <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.08em', color:C.tx3}}>OT PURCHASE</span>
        {[['per_hour','per hour · pay hours used'],['per_shift','per shift · whole crew-call blocks']].map(([id,lbl])=>{
          const cur = config.prodOtMode === 'per_shift' ? 'per_shift' : 'per_hour';
          return <button key={id} onClick={()=>setConfig({ prodOtMode:id })} style={{
            border:`2px solid ${cur===id?C.ink:C.line}`, background:cur===id?C.ink:C.paper, color:cur===id?C.ac:C.tx,
            fontFamily:F.disp, fontSize:10.5, fontWeight:700, padding:'6px 10px', cursor:'pointer'}}>{lbl}</button>;
        })}
        {config.prodOtMode==='per_shift' && <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>
          a 3-hr overflow now costs a whole shift (governed hrs/shift) — the paid-but-unused gap shows in Capacity Loading, never hidden</span>}
      </div>
      {prod && prod.result && (Number(config.prodLaborHeadcountCap)>0 || Number(config.prodLaborOtCapHrs)>0) && (()=>{
        const otHrs = (prod.result.products||[]).reduce((s,p)=>s+(Number(p.overtime_hours)||0),0);
        return <div style={{marginTop:10, display:'flex', gap:8, flexWrap:'wrap', alignItems:'center', fontFamily:F.mono, fontSize:10, color:C.tx2}}>
          <span style={{fontWeight:700, color:C.tx3}}>LABOR ENVELOPE:</span>
          {Number(config.prodLaborHeadcountCap)>0 && <><span>headcount <b style={{color:C.tx}}>{config.prodLaborHeadcountCap}</b> → <b style={{color:C.tx}}>{(Number(config.prodLaborHeadcountCap)*40).toLocaleString('en-IN')}</b> reg h/wk</span><span style={{color:C.line2}}>·</span></>}
          <span>OT used <b style={{color:otHrs>0?C.dg:C.tx}}>{otHrs.toFixed(0)} h</b></span>
          <Tag c={otHrs>0?'r':'g'}>{otHrs>0?'cap forced overtime':'within regular labor'}</Tag>
        </div>;
      })()}
      {prod && prod.result && prod.result.campaign && (()=>{ const cm = prod.result.campaign;
        return <div style={{marginTop:10, display:'flex', gap:8, flexWrap:'wrap', alignItems:'center', fontFamily:F.mono, fontSize:10, color:C.tx2}}>
          <span style={{fontWeight:700, color:C.tx3}}>CAMPAIGN:</span>
          <span>{cm.runs} runs</span><span style={{color:C.line2}}>·</span>
          <span>avg <b style={{color:C.tx}}>{cm.avg_run_units}</b> u/run</span><span style={{color:C.line2}}>·</span>
          <span>min-run {cm.min_run>0?<b style={{color:C.ac}}>{cm.min_run}u</b>:'off'}</span>
          <Tag c={cm.min_run>0?'b':'w'}>{cm.min_run>0?'campaigned':'free lots'}</Tag>
        </div>;
      })()}
      {/* V5-1 — the FG ledger netting the schedule, shown per SKU so a planner can see
          exactly which stock cut the build (scope is governed on the Network tab). */}
      {(()=>{
        const fin = ((window.M||{}).products||[]).filter(p=>p.cat==='Finished');
        const rows = fin.map(p=>({ sku:p.sku, ...fgScheduleOnHand(p.sku, config) })).filter(r=>r.qty>0);
        const scope = config.netFgScope || 'plant_wh';
        return <div data-vis="v5-fgnet" style={{marginTop:10, fontFamily:F.mono, fontSize:10, color:C.tx2, display:'flex', gap:8, flexWrap:'wrap', alignItems:'center'}}>
          <span style={{fontWeight:700, color:C.tx3}}>FG LEDGER NETS THE SCHEDULE ({scope==='off'?'OFF — gross':scope==='all'?'whole network':'plant + WH'}):</span>
          {scope!=='off' && rows.length>0 && rows.map(r=>(
            <span key={r.sku}>{r.sku} <b style={{color:C.gn}}>−{r.qty.toLocaleString('en-IN')}u</b> ({r.rows.filter(x=>r.qty && (scope==='all'||['plant','wh'].includes(x.type))).map(x=>x.loc).join('+')})</span>
          ))}
          {scope!=='off' && rows.length===0 && <span style={{color:C.tx3}}>no FG stock in scope — schedule is gross</span>}
          {scope==='off' && <span style={{color:C.tx3}}>stock ignored by choice — flip the scope on Network ▸ On-Hand</span>}
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
  const { config } = useConfig();                   // G-P3 — governed hrsPerShift
  const { planning } = usePlanning();               // G-P3 — workDaysPerWeek
  const [mode, setMode] = useState('detailed');     // 'detailed' = show OEE+workers, 'simple' = cycle-only
  const detailed = mode==='detailed';
  const lines = M.lines || [];
  // G-P3 — available MACHINE-HOURS per week for a line = Σmachines × shifts × hrs/shift ×
  // workDays × OEE. Makes machine-hours legible beside the u/mo capacity (the u/mo cap is
  // the slowest STAGE; this is the line's nameplate machine-time after OEE losses).
  const hrsPerShift = Number(planning.hrsPerShift) || 8;   // FIX: Setup writes planning.hrsPerShift — config.hrsPerShift never existed, so the field was dead here
  const workDays = Number(planning.workDaysPerWeek) || 6;
  const lineMachineHrsWk = (line)=>{
    const machines = (line.stages||[]).reduce((s,st)=>s+(Number(st.m)||0),0);
    const shifts = line.shifts!=null ? Number(line.shifts) : 1;
    return machines * shifts * hrsPerShift * workDays * (Number(line.oee)||1);
  };
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
            <div style={{padding:'8px 11px', borderTop:`2px solid ${C.line}`, background:C.bg3, display:'flex', justifyContent:'space-between', alignItems:'center', flexWrap:'wrap', gap:8}}>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>LINE CAPACITY = slowest stage{line.bottleneck&&line.bottleneck!=='—'?` (${line.bottleneck})`:''}</span>
              <div style={{display:'flex', alignItems:'center', gap:14}}>
                <span title={`${(line.stages||[]).reduce((s,st)=>s+(Number(st.m)||0),0)} machines × ${line.shifts!=null?line.shifts:1} shifts × ${hrsPerShift} h × ${workDays} days × OEE ${((line.oee||0)*100).toFixed(0)}%`}
                  style={{fontFamily:F.mono, fontSize:9, color:C.tx2}}>machine-hrs/wk <b style={{fontFamily:F.disp, fontSize:13, color:C.tx}}>{Math.round(lineMachineHrsWk(line)).toLocaleString('en-IN')}</b></span>
                {/* V2-11 — honest scope: this u/mo figure feeds the linecap dual LP and the
                    aggregate envelope; the schedule MILP does NOT read it when routing is
                    present (it binds machine-hours × OEE — SF-7). Don't imply it caps the plan. */}
                <span className="num" title="feeds linecap (capacity dual LP) + aggregate envelope — NOT the schedule MILP, which binds machine-hrs × OEE via routing (SF-7)"
                  style={{fontFamily:F.disp, fontSize:15, fontWeight:800, color:C.dg}}>{(line.cap||0).toLocaleString('en-IN')} u/mo<span style={{fontFamily:F.mono, fontSize:8, fontWeight:400, color:C.tx3, marginLeft:5}}>linecap·agg</span></span>
              </div>
            </div>
          </div>
        );})}
      </div>
      <button onClick={()=>addLine()} style={{marginTop:14, cursor:'pointer', border:`2px solid ${C.line}`, background:C.ink, color:C.paper, fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.04em', padding:'7px 16px'}}>+ Add production line</button>
      <div style={{marginTop:12}}>
        <Card icon="📉" title="Derived Capacities & Bottlenecks" badge={solvedMonthly?'min(stage) · solved load':'min(stage)'} badgeTone={solvedMonthly?'g':undefined}
          right={solvedMonthly ? <Provenance kind="solved" asOf={prod.ranAt?prod.ranAt.toLocaleTimeString():undefined}/> : null}
          info={{ what:'Each line is capped by its slowest stage; utilization is the solved schedule load when a plan exists.', flows:'Line cap (u/mo) → linecap dual LP + aggregate envelope. The schedule MILP does NOT bind on it — with routing present it sizes capacity from machine-hrs × OEE (SF-7), so this figure is a pressure/planning input, not the schedule constraint.' }}
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
          <GovField label="Cycle Time" token="cfg.prod" seed={p.cycle} value={ov.cycle}
            onChange={v=>setRoute({ cycle:v })} min={0.1} suffix="min/u" hint="re-prices throughput"
            why="Minutes of line time one unit of this SKU consumes — written to config.prodRouting and fed to the schedule MILP, profit-mix line pool and linecap."
            formula="line hrs used = Σ qty × cycle ÷ 60 · effective rate = 60 ÷ cycle × OEE"/>
          <Field label={`Assigned Line${lineSet?'':' · seed'}`}>
            <Select value={effLine} options={(M.lines||[]).map(l=>l.id)}
              onChange={v=>setRoute({ line:v })}/>
          </Field>
          {capMode==='oee'
            ? <Field label="OEE" hint="read-only here"><NumInput value={(p.oee*100).toFixed(0)} suffix="%" disabled/></Field>
            : <Field label="Run hours / day" hint="not wired yet — preview"><NumInput value="20" disabled/></Field>}
          <Field label="Effective Rate" hint="derived"><NumInput value={capMode==='oee'?effRate:flatRate} suffix="u/hr" disabled/></Field>
          <Field label="Batch Size · MOQ" span={2} hint="set on Products → Costs"><NumInput value={p.moq} disabled/></Field>
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
      <CtpQuote skus={skus} T={T} planning={planning} periods={periods}/>
    </Card>
  );
}

// V4-5 — capable-to-promise quote: "can I take qty Q of SKU S due week W?" answered by
// the REAL MILP (/api/solve/ctp test-fits the order into the live payload and re-solves
// at due, due+1, …). ATP-first (a free promise when uncommitted supply covers it), else
// the earliest feasible week + what it displaces (₹ cost-to-promise, OT bought, moved
// SKUs). ADVISORY by construction — nothing commits; the planner re-commits if accepted.
function CtpQuote({ skus, T, planning, periods }){
  const [qsku, setQsku] = useState(skus[0]||'');
  const [qty, setQty] = useState('25');
  const [due, setDue] = useState('0');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const run = async ()=>{
    if(busy || !qsku) return;
    setBusy(true);
    try{
      // ONE opts truth + time-phased forced: a date promise is meaningless without the curve.
      const pl = productionPayload(planning, { ...productionOptsFromConfig(), timePhased:true });
      pl.quote = { product:qsku, qty:Number(qty)||0, due_period:Number(due)|0 };
      setRes(await apiPost('/api/solve/ctp', pl));
    } catch(e){ setRes({ status:'Error', error:String(e && e.message || e) }); }
    finally{ setBusy(false); }
  };
  const wk = (i)=> (periods[i] && periods[i].label) || `W${i+1}`;
  const inp = { border:`2px solid ${C.line}`, padding:'5px 8px', fontFamily:F.mono, fontSize:10.5, color:C.tx, background:C.paper, outline:'none' };
  return (
    <div data-vis="v4-ctp" style={{marginTop:12, padding:'9px 11px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.ac}`, background:C.bg3}}>
      <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
        <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.08em', fontWeight:700, color:C.tx3}}>CTP QUOTE</span>
        <select value={qsku} onChange={e=>setQsku(e.target.value)} style={inp}>{skus.map(s=><option key={s} value={s}>{s}</option>)}</select>
        <input value={qty} onChange={e=>setQty(e.target.value)} style={{...inp, width:64}} aria-label="quote qty"/>
        <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>units due</span>
        <select value={due} onChange={e=>setDue(e.target.value)} style={inp}>{Array.from({length:T},(_,i)=><option key={i} value={i}>{wk(i)}</option>)}</select>
        <Btn kind="primary" sm onClick={run} disabled={busy}>{busy?'test-fitting…':'⚡ Test-fit the order'}</Btn>
        <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>re-solves the REAL schedule with the order added — advisory, commits nothing</span>
      </div>
      {res && (()=>{
        const e = res.earliest_period;
        const tone = res.status==='NoPromise'||res.status==='Error'||res.status==='BadQuote'||res.status==='BaseInfeasible' ? 'r' : res.covered_by_atp ? 'g' : res.promised ? 'g' : 'y';
        const head = res.status==='Error'||res.status==='BadQuote' ? `quote failed — ${res.error||res.status}`
          : res.status==='BaseInfeasible' ? 'baseline schedule itself is infeasible — fix capacity first'
          : res.status==='NoPromise' ? `NO PROMISE — does not fit by ${wk(res.searched_through!=null?res.searched_through:T-1)} even with all overtime`
          : res.covered_by_atp ? `PROMISE ${wk(e)} — free: covered by uncommitted supply (ATP ${res.atp_at_due}u at due)`
          : res.promised ? `PROMISE ${wk(e)} — capacity test-fit holds`
          : `SLIPS to ${wk(e)} — requested ${wk(res.quote.due_period)} does not fit`;
        return <div style={{marginTop:8}}>
          <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
            <Tag c={tone}>{res.status==='NoPromise'?'NO PROMISE':res.covered_by_atp?'ATP':res.promised?'CTP ✓':e!=null?'CTP →':'—'}</Tag>
            <span style={{fontFamily:F.mono, fontSize:10, color:C.tx, fontWeight:700}}>{head}</span>
          </div>
          {res.status==='Optimal' && !res.covered_by_atp && (
            <div style={{display:'flex', gap:14, flexWrap:'wrap', marginTop:6, fontFamily:F.mono, fontSize:10, color:C.tx2}}>
              <span>cost-to-promise <b style={{color:(res.cost_to_promise||0)>0?C.dg:C.tx}}>₹{Math.round(res.cost_to_promise||0).toLocaleString('en-IN')}</b></span>
              <span>OT bought <b style={{color:(res.ot_hours_added||0)>0?C.dg:C.tx}}>{res.ot_hours_added||0} h</b></span>
              <span>displaced {res.displaced && res.displaced.length
                ? res.displaced.slice(0,4).map(d=><b key={d.product+d.period} style={{color:C.dg, marginRight:6}}>{d.product} {wk(d.period)} {d.delta>0?'+':''}{d.delta}u</b>)
                : <b style={{color:C.gn}}>nothing — slack absorbed it</b>}</span>
            </div>
          )}
        </div>;
      })()}
    </div>
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
        {(()=>{ const perShift = res.ot_mode === 'per_shift';  // V4-3 — surface block purchases, never hide the paid-but-unused gap
        return <DataTable cols={['Line','Util','Active wks','Produced','OT hrs', ...(perShift?['OT paid']:[]), 'OT cost','Changeovers']} align={['left','right','right','right','right',...(perShift?['right']:[]),'right','right']}
          rows={res.lines.map(l=>({cells:[
            l.name,
            <span style={{fontWeight:700, color:l.utilization>95?C.dg:C.tx}}>{l.utilization}%</span>,
            l.active_periods, (l.total_produced||0).toLocaleString('en-IN'),
            l.overtime_hours,
            ...(perShift?[<span style={{color:(l.overtime_hours_paid||0)>(Number(l.overtime_hours)||0)?C.dg:C.tx}}>{l.overtime_shifts||0} sh · {l.overtime_hours_paid!=null?l.overtime_hours_paid:0} h</span>]:[]),
            `₹${(l.overtime_cost||0).toLocaleString('en-IN')}`, l.changeovers]}))}/>;
        })()}
        {/* V4-6 (Q24) — the priced failure stream: started × (1−yield) per SKU, charged at the
            product master's ₹/failed-unit rework adder inside the MILP objective. */}
        {(res.rework_cost||0) > 0 && (
          <div data-vis="v4-rework" style={{marginTop:10, padding:'8px 11px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10, color:C.tx2}}>
            <b style={{color:C.dg}}>REWORK ₹{Math.round(res.rework_cost).toLocaleString('en-IN')}</b>
            {' — failure stream priced in the objective: '}
            {(res.products||[]).filter(p=>(p.rework_cost||0)>0).map(p=>`${p.name} ${p.rework_units}u → ₹${Math.round(p.rework_cost).toLocaleString('en-IN')}`).join(' · ')}
            {' (rework ₹/failed unit is set per SKU in Products ▸ Yield & expiry)'}
          </div>
        )}
        <Reading formula={res.ot_mode==='per_shift' ? "util = active periods ÷ horizon   ·   OT cost = blocks × shift hrs × workers × rate × 1.5 (whole block paid)" : "util = active periods ÷ horizon   ·   OT cost = workers × hrs × rate × 1.5"}
          soWhat={`Overtime is priced at the governed labor rate (₹${laborRate}/hr${rateIsSeed?' · seed':''}); workers/line come from the bottleneck stage's machine count.${res.ot_mode==='per_shift'?' Per-shift purchase: crews are called for whole blocks — when OT paid exceeds OT used, that gap is idle paid time the per-hour mode would have avoided.':''} A line under the shutdown threshold for a run of weeks becomes a candidate below.`}/>
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
  const { config } = useConfig();                    // governed labor rate prices a saved setup hour
  const laborRate = _eff(config.prodLaborRate, 120);
  const skus = M.changeoverSkus || [];               // canonical FG order (data.jsx) — no stale 4-SKU literal
  const N = skus.length;
  // build the nested {from:{to:min}} matrix the sequence solver wants (skip '—' diagonal).
  const seq = useSolve('/api/solve/sequence', ()=>{
    const matrix={};
    // UNITS CONTRACT: M.changeover is authored in HOURS, but /api/solve/sequence speaks
    // MINUTES — every field is *_min, default_min=30, matching production.py & store.subMatrix.
    // Convert ×60 at the boundary (a missing pair then falls back to 30 MIN, not 30 h).
    skus.forEach((a,ri)=>{ matrix[a]={}; skus.forEach((b,ci)=>{ const v=M.changeover[ri][ci]; if(typeof v==='number') matrix[a][b]=v*60; }); });
    return { skus, changeover_matrix:matrix };
  });
  const sres = seq.result;
  const seqCost=(s)=>{ let t=0; for(let i=0;i<s.length-1;i++){ const v=M.changeover[s[i]][s[i+1]]; if(typeof v==='number') t+=v; } return t; };
  const alphaOrder = skus.map((_,i)=>i);
  // client-side fallback until the solver runs: greedy nearest-neighbour tour (so the
  // "optimized" comparison still beats alphabetical for N SKUs, not a fixed 4-permutation).
  const greedy=()=>{ const seen=[0]; while(seen.length<N){ const last=seen[seen.length-1]; let best=-1,bv=Infinity;
    for(let j=0;j<N;j++){ if(seen.indexOf(j)>=0) continue; const v=M.changeover[last][j]; if(typeof v==='number'&&v<bv){ bv=v; best=j; } }
    if(best<0){ for(let j=0;j<N;j++){ if(seen.indexOf(j)<0){ best=j; break; } } } seen.push(best); } return seen; };
  const order = greedy();
  const alpha=seqCost(alphaOrder);
  // solved sequence (sku names) → index order for the chips; fall back to the fixed order.
  const solvedOrder = sres && Array.isArray(sres.sequence) ? sres.sequence.map(s=>skus.indexOf(s)).filter(i=>i>=0) : null;
  const chosenIdx = solvedOrder && solvedOrder.length===skus.length ? solvedOrder : order;
  // solver returns MINUTES (units contract) → ÷60 back to the HOURS the UI shows;
  // the local fallbacks (seqCost/alpha) already sum M.changeover in hours.
  const opt = sres && sres.total_changeover_min!=null ? sres.total_changeover_min/60 : seqCost(order);
  const saved = sres && sres.sequence_saving_min!=null ? sres.sequence_saving_min/60 : (alpha-opt);
  return (
    <Grid cols={2}>
      <Card icon="🔀" title="Changeover Matrix" badge="editable · setup hrs" badgeTone="y" info={{ what:'Setup time (hrs) for each from→to SKU transition — editable master data. The diagonal is self-to-self (no changeover). New products get a row/col seeded from their changeover CLASS (PRC/STD/HVY class×class table) — never a silent 30-min default.', flows:'Matrix → sequencing (ATSP heuristic) & production setup.' }}
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
          {alphaOrder.map((s,i)=><React.Fragment key={i}><span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line2}`, background:C.bg3}}>{skus[s].slice(4)}</span>{i<N-1 && <span style={{color:C.tx3}}>→</span>}</React.Fragment>)}
          <span className="num" style={{marginLeft:'auto', fontFamily:F.disp, fontWeight:800}}>{alpha.toFixed(1)} hrs</span>
        </div>
        <SubLabel>{sres?`Solver-optimized · ${sres.basis||'exact'}`:'Solver-optimized'}</SubLabel>
        <div style={{display:'flex', alignItems:'center', gap:4, flexWrap:'wrap'}}>
          {chosenIdx.map((s,i)=><React.Fragment key={i}><span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line}`, background:C.ac, color:C.onAc}}>{skus[s].slice(4)}</span>{i<chosenIdx.length-1 && <span style={{color:C.tx3}}>→</span>}</React.Fragment>)}
          <span className="num" style={{marginLeft:'auto', fontFamily:F.disp, fontWeight:800}}>{opt.toFixed(1)} hrs</span>
        </div>
        <Reading formula={sres?`shortest Hamiltonian path over the changeover matrix (${sres.basis||'exact'}) vs averaged approximation`:"min Σ changeover(seqᵢ, seqᵢ₊₁) over all permutations"}
          soWhat={`Re-ordering saves ${saved.toFixed(1)} setup hours per cycle — roughly ₹${Math.round(saved*laborRate).toLocaleString('en-IN')} at the governed labor rate (₹${laborRate}/hr${config.prodLaborRate==null||config.prodLaborRate===''?' · seed':''}).${sres?'':' Press ⚡ Sequence to solve it against the live engine.'}`}/>
      </Card>
    </Grid>
  );
}
// ── V3-3 · VIS-6 — Feasible-region toy (Learn band, Profit-Mix subtab) ──────
// A 2-SKU INTERACTIVE picture of the ACTUAL LP: constraints are built from the
// same profitmixPayload() the solver receives (real line hours × OEE over the
// 12-month horizon, real demand ceilings, real firm-order floors, real unit
// margins), restricted to the two chosen SKUs. The optimal vertex is computed by
// exact 2-D vertex enumeration of that restriction, so the picture cannot drift
// from the model. HONEST framing: the full LP optimises ALL SKUs and lines
// jointly — this toy exists to show WHY the optimum sits on a corner (Step-5
// picture). The two sliders are TOY-LOCAL levers (they write nothing): margin-A
// rotates the iso-profit line; capacity× shrinks the real line hours until the
// capacity wall cuts the demand box — the same lesson SF-7 proved behaviourally
// (at TPAC volumes lines are honestly slack, so demand is the priced scarcity).
function _v6Solve(cons, lox, loy, mA, mB){
  const lines = [ ...cons.map(c=>[c.a,c.b,c.c]), [1,0,lox], [0,1,loy] ];
  const eps = 1e-6, pts = [];
  for(let i=0;i<lines.length;i++) for(let j=i+1;j<lines.length;j++){
    const [a1,b1,c1]=lines[i], [a2,b2,c2]=lines[j];
    const det = a1*b2 - a2*b1; if(Math.abs(det)<eps) continue;
    const x=(c1*b2-c2*b1)/det, y=(a1*c2-a2*c1)/det;
    if(x<lox-eps || y<loy-eps) continue;
    if(cons.every(c=>c.a*x+c.b*y <= c.c + Math.max(1,Math.abs(c.c))*1e-7)) pts.push([x,y]);
  }
  const uniq=[]; pts.forEach(p=>{ if(!uniq.some(q=>Math.abs(q[0]-p[0])<1e-3 && Math.abs(q[1]-p[1])<1e-3)) uniq.push(p); });
  if(!uniq.length) return { verts:[], best:null, bestProfit:0 };
  const cx=uniq.reduce((s,p)=>s+p[0],0)/uniq.length, cy=uniq.reduce((s,p)=>s+p[1],0)/uniq.length;
  uniq.sort((p,q)=>Math.atan2(p[1]-cy,p[0]-cx)-Math.atan2(q[1]-cy,q[0]-cx));
  let best=uniq[0], bv=-Infinity;
  uniq.forEach(p=>{ const v=mA*p[0]+mB*p[1]; if(v>bv){ bv=v; best=p; } });
  return { verts:uniq, best, bestProfit:bv };
}
// clip the line a·x+b·y=c to the [0,mx]×[0,my] view box → segment or null (off-chart)
function _v6Clip(a, b, c, mx, my){
  const pts=[];
  if(Math.abs(b)>1e-9){ const y0=c/b, ym=(c-a*mx)/b;
    if(y0>=0&&y0<=my) pts.push([0,y0]); if(ym>=0&&ym<=my) pts.push([mx,ym]); }
  if(Math.abs(a)>1e-9){ const x0=c/a, xm=(c-b*my)/a;
    if(x0>=0&&x0<=mx) pts.push([x0,0]); if(xm>=0&&xm<=mx) pts.push([xm,my]); }
  const u=[]; pts.forEach(p=>{ if(!u.some(q=>Math.abs(q[0]-p[0])<1e-6&&Math.abs(q[1]-p[1])<1e-6)) u.push(p); });
  return u.length>=2 ? [u[0], u[1]] : null;
}
function Vis6FeasibleRegion(){
  const fin = M.products.filter(p=>p.cat==='Finished');
  const [sa, setSa] = useState(fin[0]?fin[0].sku:'');
  const [sb, setSb] = useState(fin[1]?fin[1].sku:'');
  const [bump, setBump] = useState(0);        // toy-local: ±% on SKU-A margin
  const [capX, setCapX] = useState(100);      // toy-local: % of real line hours
  const payload = React.useMemo(()=>profitmixPayload(), []);
  const ia = payload.products.findIndex(p=>p.name===sa);
  const ib = payload.products.findIndex(p=>p.name===sb);
  const pick = (
    <div style={{display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end', marginBottom:10}}>
      <div><SubLabel>SKU on the X axis</SubLabel><Select value={sa} onChange={setSa} options={fin.map(p=>({value:p.sku, label:`${p.sku} · ${p.name}`}))}/></div>
      <div><SubLabel>SKU on the Y axis</SubLabel><Select value={sb} onChange={setSb} options={fin.map(p=>({value:p.sku, label:`${p.sku} · ${p.name}`}))}/></div>
      <div style={{minWidth:170}}>
        <SubLabel>margin A {bump>=0?'+':''}{bump}% · toy only</SubLabel>
        <input type="range" min={-60} max={60} step={5} value={bump} onChange={e=>setBump(Number(e.target.value))} style={{width:'100%'}}/>
      </div>
      <div style={{minWidth:170}}>
        <SubLabel>line hours ×{(capX/100).toFixed(2)} · toy only</SubLabel>
        <input type="range" min={2} max={100} step={1} value={capX} onChange={e=>setCapX(Number(e.target.value))} style={{width:'100%'}}/>
      </div>
    </div>
  );
  if(ia<0 || ib<0 || ia===ib) return (
    <Card icon="📐" title="Feasible region — the LP as a picture" badge="VIS-6 · learn" badgeTone="c">
      {pick}
      <div style={{padding:'14px', fontFamily:F.mono, fontSize:10, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3}}>pick two DIFFERENT finished SKUs to draw their 2-SKU restriction of the live LP</div>
    </Card>
  );
  const A = payload.products[ia], B = payload.products[ib];
  const months = payload.planning_horizon_months || 12, weeks = months*52/12;
  const cons = [];
  (payload.lines||[]).forEach(l=>{
    const ca = l.eligible_skus.includes(ia) ? (l.cycle_time_by_sku_min[ia]||0)/60 : 0;
    const cb = l.eligible_skus.includes(ib) ? (l.cycle_time_by_sku_min[ib]||0)/60 : 0;
    if(ca>0 || cb>0) cons.push({ a:ca, b:cb, c:l.avail_hrs_per_week*(l.oee||1)*weeks*(capX/100), name:l.name, kind:'capacity' });
  });
  cons.push({ a:1, b:0, c:A.max_quantity, name:`Max prod: ${A.name}`, kind:'demand' });
  cons.push({ a:0, b:1, c:B.max_quantity, name:`Max prod: ${B.name}`, kind:'demand' });
  const lox = Math.max(0, A.min_quantity||0), loy = Math.max(0, B.min_quantity||0);
  const mA = (A.sell_price - A.variable_cost)*(1+bump/100), mB = B.sell_price - B.variable_cost;
  const sol = _v6Solve(cons, lox, loy, mA, mB);
  const mx = A.max_quantity*1.35, my = B.max_quantity*1.35;
  const W=620, H=400, padL=52, padB=34, padT=14, padR=14;
  const X=v=>padL+(v/mx)*(W-padL-padR), Y=v=>H-padB-(v/my)*(H-padB-padT);
  const isBind = c=> sol.best ? Math.abs(c.a*sol.best[0]+c.b*sol.best[1]-c.c) <= Math.max(1,Math.abs(c.c))*1e-4 : false;
  const offChart = cons.filter(c=>c.kind==='capacity' && !_v6Clip(c.a,c.b,c.c,mx,my));
  // iso-profit dashed line through the optimal vertex
  const iso = sol.best ? _v6Clip(mA, mB, mA*sol.best[0]+mB*sol.best[1], mx, my) : null;
  const fmtL = n=> n>=1e5 ? `₹${(n/1e5).toFixed(1)}L` : `₹${Math.round(n).toLocaleString('en-IN')}`;
  return (
    <Card icon="📐" title="Feasible region — the LP as a picture" badge="VIS-6 · learn" badgeTone="c"
      info={{ what:'The 2-SKU restriction of the LIVE profit-mix LP, drawn: every constraint from the real payload (line hours × OEE, demand ceilings, firm-order floors), the iso-profit line from real margins, and the exactly-enumerated optimal corner.', flows:'learn band — explains the solver; writes nothing.' }}
      dev={{ comp:'Vis6FeasibleRegion', props:'profitmixPayload() restricted to 2 SKUs', note:'vertex enumeration, toy-local sliders' }}>
      {pick}
      <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', maxWidth:680, height:'auto', display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
        {/* feasible polygon */}
        {sol.verts.length>=3 && <polygon points={sol.verts.map(p=>`${X(p[0])},${Y(p[1])}`).join(' ')} fill={C.ac} opacity=".18"/>}
        {/* axes */}
        <line x1={padL} y1={H-padB} x2={W-padR} y2={H-padB} stroke={C.ink} strokeWidth="1.5"/>
        <line x1={padL} y1={H-padB} x2={padL} y2={padT} stroke={C.ink} strokeWidth="1.5"/>
        <text x={W-padR} y={H-8} fontSize="10" fontFamily={F.mono} fill={C.tx2} textAnchor="end" fontWeight="700">{A.name} units →</text>
        <text x={10} y={padT+2} fontSize="10" fontFamily={F.mono} fill={C.tx2} fontWeight="700">↑ {B.name}</text>
        {/* constraints */}
        {cons.map((c,i)=>{ const seg=_v6Clip(c.a,c.b,c.c,mx,my); if(!seg) return null; const bind=isBind(c);
          const col = bind?C.dg:(c.kind==='capacity'?C.a2:C.tx3);
          return <g key={i}>
            <line x1={X(seg[0][0])} y1={Y(seg[0][1])} x2={X(seg[1][0])} y2={Y(seg[1][1])} stroke={col} strokeWidth={bind?2.6:1.6} strokeDasharray={c.kind==='demand'?'':'7 4'}/>
            <text x={X((seg[0][0]+seg[1][0])/2)+4} y={Y((seg[0][1]+seg[1][1])/2)-4} fontSize="8.5" fontFamily={F.mono} fill={col} fontWeight={bind?'800':'400'}>{bind?'● ':''}{c.kind==='capacity'?`Line hrs: ${c.name}`:c.name}</text>
          </g>; })}
        {/* firm-order floors */}
        {lox>0 && <line x1={X(lox)} y1={Y(0)} x2={X(lox)} y2={padT} stroke={C.a4} strokeWidth="1.6" strokeDasharray="3 3"/>}
        {loy>0 && <line x1={padL} y1={Y(loy)} x2={W-padR} y2={Y(loy)} stroke={C.a4} strokeWidth="1.6" strokeDasharray="3 3"/>}
        {/* iso-profit through the optimum */}
        {iso && <line x1={X(iso[0][0])} y1={Y(iso[0][1])} x2={X(iso[1][0])} y2={Y(iso[1][1])} stroke={C.ink} strokeWidth="1.4" strokeDasharray="2 4"/>}
        {/* vertices + optimum */}
        {sol.verts.map((p,i)=><circle key={i} cx={X(p[0])} cy={Y(p[1])} r="3" fill={C.paper} stroke={C.ink} strokeWidth="1.5"/>)}
        {sol.best && <g>
          <circle cx={X(sol.best[0])} cy={Y(sol.best[1])} r="6" fill={C.ac} stroke={C.ink} strokeWidth="2"/>
          <text x={X(sol.best[0])+9} y={Y(sol.best[1])-8} fontSize="10" fontFamily={F.disp} fontWeight="800" fill={C.tx}>★ ({Math.round(sol.best[0]).toLocaleString('en-IN')}, {Math.round(sol.best[1]).toLocaleString('en-IN')}) · {fmtL(sol.bestProfit)}</text>
        </g>}
      </svg>
      {offChart.length>0 && (
        <div style={{marginTop:6, fontFamily:F.mono, fontSize:9, color:C.gn}}>
          🟢 {offChart.map(c=>`Line hrs: ${c.name}`).join(' · ')} — off-chart (honestly SLACK at this volume; drag “line hours ×” down to watch the capacity wall cut the demand box and the corner move)
        </div>
      )}
      <Reading formula="max mA·x + mB·y  s.t. Σ(cycle/60)·q ≤ line hrs × OEE × weeks · q ≤ demand ceiling · q ≥ firm floor — the REAL payload, restricted to 2 SKUs"
        soWhat={sol.best?`The optimum of an LP is ALWAYS a corner of the feasible region — ${sol.verts.length} corners enumerated, best = ★ (${Math.round(sol.best[0]).toLocaleString('en-IN')} ${A.name}, ${Math.round(sol.best[1]).toLocaleString('en-IN')} ${B.name}) worth ${fmtL(sol.bestProfit)}. The full solver does exactly this across ALL SKUs and lines at once; the binding edge here (red ●) is the same kind of constraint its shadow prices put a ₹/unit on.`:'no feasible corner — the floors exceed a ceiling at this capacity; ease a slider.'}/>
    </Card>
  );
}
// ── V3-7 · ① DECIDE strip (blueprint 3.2) — the tab's question + the 1–3 KPIs ──
// that answer it, read ONLY from the solved schedule (no seed bars, no fakes):
// busiest line's time-utilization, total OT hours, total changeovers.
function ProdDecideStrip({ res }){
  if(!res || !res.lines || !res.lines.length) return (
    <span style={{fontFamily:F.mono, fontSize:10, color:C.tx3}}>
      ① Can the lines build the committed plan, and where do minutes leak? — press <b style={{color:C.tx}}>⚡ Run schedule</b> to light this up
    </span>
  );
  const busiest = res.lines.reduce((a,b)=> (Number(b.utilization)>Number(a.utilization)?b:a), res.lines[0]);
  const ot = res.lines.reduce((s,l)=>s+(Number(l.overtime_hours)||0),0);
  const co = res.lines.reduce((s,l)=>s+(Number(l.changeovers)||0),0);
  const T = res.periods || 0;
  const idle = Math.max(0, T - (Number(busiest.active_periods)||0));
  return (
    <div data-vis="prod-decide" style={{display:'flex', alignItems:'center', gap:14, flexWrap:'wrap'}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.08em', color:C.tx3}}>① CAN THE LINES BUILD THE PLAN?</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>busiest <b style={{color:C.dg}}>{busiest.name}</b> <b className="num" style={{fontFamily:F.disp, color:C.tx}}>{busiest.utilization}%</b> of weeks active</span>
      <span style={{color:C.line2}}>·</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>OT <b className="num" style={{fontFamily:F.disp, color:ot>0?C.dg:C.tx}}>{ot.toFixed(0)} h</b></span>
      <span style={{color:C.line2}}>·</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}><b className="num" style={{fontFamily:F.disp, color:C.tx}}>{co}</b> changeovers</span>
      <Tag c={ot>0?'y':'g'}>{ot>0 ? 'feasible — on overtime' : (idle>0 ? `feasible — ${idle} idle wk on the busiest line` : 'feasible — fully loaded')}</Tag>
    </div>
  );
}

// ── V3-7 · VIS-4 — bottleneck Gantt ribbon (blueprint 3.4 #4, the Step-4 picture) ──
// The SOLVED gantt as one ribbon per line: each week's cell splits by the SKUs the
// MILP scheduled there (slice width = that SKU's share of the week's units on the
// line). The BUSIEST line — by the solver's own time-utilization — wears the red
// treatment: its idle weeks are minutes the factory never gets back (an hour lost
// at the bottleneck is an hour lost for the whole system). Changeover slivers (▮)
// are DERIVED for display (SKU set changed week-over-week); the authoritative
// count is the solver's own `changeovers` figure printed per row. HONEST SCOPE:
// utilization here is time-based (active weeks ÷ horizon), the same figure the
// capacity panel shows — not machine-hour saturation; linecap prices that.
function Vis4GanttRibbon({ res, ranAt }){
  if(!res || !res.gantt || !res.lines || !res.lines.length){
    return (
      <Card icon="📊" title="Bottleneck Gantt ribbon" badge="not solved"
        info={{ what:'The solved schedule as one ribbon per line — SKU slices per week, changeover slivers, busiest line highlighted.', flows:'display of prod.result.gantt — writes nothing.' }}>
        <div style={{padding:'18px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Run the schedule (⚡ top right) to draw the ribbon from the solved gantt.</div>
      </Card>
    );
  }
  const T = res.periods || 0;
  const periods = (M.periods||[]).slice(0,T);
  const skus = [...new Set(res.gantt.map(g=>g.product))].sort();
  const PAL = [C.ac, C.a2, C.gn, C.a4, C.ink, C.dg];
  const colOf = s => PAL[skus.indexOf(s) % PAL.length];
  const byLine = {};
  res.gantt.forEach(g=>{ const row = byLine[g.line] = byLine[g.line] || Array.from({length:T},()=>[]); if(row[g.period]) row[g.period].push(g); });
  const busiest = res.lines.reduce((a,b)=> (Number(b.utilization)>Number(a.utilization)?b:a), res.lines[0]);
  return (
    <Card icon="📊" title="Bottleneck Gantt ribbon" badge={`busiest ${busiest.name} · ${busiest.utilization}%`} badgeTone="r"
      right={<Provenance kind="solved" asOf={ranAt?ranAt.toLocaleTimeString():undefined}/>}
      info={{ what:'One ribbon per line from the solved gantt: SKU slices per week, ▮ changeover slivers (derived; the solver count is printed per row), red = busiest line and its idle weeks.', flows:'display of prod.result.{gantt,lines} — writes nothing.' }}
      dev={{ comp:'Vis4GanttRibbon', props:'prod.result.gantt, prod.result.lines', note:'V3-7 · VIS-4 — Step-4 picture; util is time-based (active wks ÷ horizon)' }}>
      <div data-vis="vis4" style={{display:'flex', flexDirection:'column', gap:8}}>
        <div style={{display:'flex', alignItems:'center', gap:8}}>
          <span style={{width:118}}/>
          <div style={{display:'flex', flex:1}}>
            {periods.map((w,i)=><span key={i} style={{flex:1, fontFamily:F.mono, fontSize:8, color:C.tx3, textAlign:'center'}}>{w.label}</span>)}
          </div>
          <span style={{width:168}}/>
        </div>
        {res.lines.map(l=>{
          const cells = byLine[l.name] || Array.from({length:T},()=>[]);
          const isBn = l.name===busiest.name;
          return (
            <div key={l.name} style={{display:'flex', alignItems:'center', gap:8}}>
              <span style={{width:118, fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:isBn?C.dg:C.tx2}}>
                {l.name}{isBn && <span style={{display:'block', fontSize:7.5, fontWeight:800, color:C.dg}}>BOTTLENECK</span>}
              </span>
              <div style={{display:'flex', flex:1, border: isBn?`2px solid ${C.dg}`:`1.5px solid ${C.line2}`}}>
                {cells.map((cell,t)=>{
                  const tot = cell.reduce((s,g)=>s+g.quantity,0);
                  const prev = t>0 ? cells[t-1].map(g=>g.product).sort().join('|') : null;
                  const cur = cell.map(g=>g.product).sort().join('|');
                  const co = t>0 && prev && cur && prev!==cur;
                  return (
                    <div key={t} title={tot? cell.map(g=>`${g.product} · ${g.quantity}u`).join('  ') : `${l.name} idle in ${periods[t]?periods[t].label:`W${t+1}`}`}
                      style={{flex:1, height:26, display:'flex', minWidth:0, position:'relative', borderLeft: t>0?`1px solid ${C.line2}`:'none',
                        background: tot? C.paper : (isBn? 'color-mix(in srgb,var(--dg) 12%,transparent)' : C.bg3)}}>
                      {co && <span title="changeover — the SKU set on this line changed" style={{position:'absolute', left:0, top:0, bottom:0, width:3, background:C.ink, zIndex:1}}/>}
                      {tot>0
                        ? cell.map((g,i)=><span key={i} style={{width:`${g.quantity/tot*100}%`, background:colOf(g.product), opacity:.85}}/>)
                        : (isBn ? <span style={{margin:'auto', fontFamily:F.mono, fontSize:7.5, color:C.dg, fontWeight:800}}>idle</span> : null)}
                    </div>
                  );
                })}
              </div>
              <span style={{width:168, fontFamily:F.mono, fontSize:9, color:C.tx2}}>{l.utilization}% · OT {l.overtime_hours}h · {l.changeovers} c/o</span>
            </div>
          );
        })}
        <div style={{display:'flex', gap:10, flexWrap:'wrap', alignItems:'center', marginTop:2}}>
          <span style={{fontFamily:F.mono, fontSize:8, letterSpacing:'.08em', color:C.tx3}}>SKU</span>
          {skus.map(s=><span key={s} style={{display:'inline-flex', alignItems:'center', gap:4, fontFamily:F.mono, fontSize:8.5, color:C.tx2}}><span style={{width:10, height:10, background:colOf(s), opacity:.85}}/>{s}</span>)}
          <span style={{display:'inline-flex', alignItems:'center', gap:4, fontFamily:F.mono, fontSize:8.5, color:C.tx2}}><span style={{width:3, height:10, background:C.ink}}/>changeover</span>
        </div>
      </div>
      <Reading formula="slice width = SKU share of the week's units on the line · red row = busiest line (time-utilization = active weeks ÷ horizon, the solver's own figure) · ▮ = SKU set changed (derived; solver's changeover count printed per row)"
        soWhat={`Every idle minute on ${busiest.name} is lost forever — an hour lost at the bottleneck is an hour lost for the whole system. Its red idle cells are the first place to look before buying capacity; the Profit-Mix tab's "Elevate the constraint" card prices what an added hour is actually worth.`}/>
    </Card>
  );
}

// ── V3-7 · VIS-5 — elevate-the-constraint card (blueprint 3.4 #5, Q5/Q8 bridge) ──
// Goldratt's step after "identify": price what ELEVATING the constraint is worth.
// Numbers are REAL: the ₹/hr dual comes from the live profit-mix solve (the same
// shadow_prices the explainer translates) and the NPV chain is a real
// /api/calc/npv solve at the governed blended hurdle — no local NPV math.
// HONEST BRANCH: at TPAC volume the line-hours constraints are SLACK (dual ₹0) —
// the binding duals are the demand ceilings, so the truthful advice is "win
// demand, not machines"; the capacity case still prices live (NPV of capex
// against a ₹0/hr dual = −capex) so the user SEES why. capex/hours/life are
// card-local what-ifs (write nothing); the dual and the hurdle are live.
function Vis5Elevate(){
  const { config } = useConfig();
  const pm = useSolve('/api/solve/profitmix', profitmixPayload, { solveKey:'profitmix' });   // hydrates from the cross-stage cache — never auto-runs here
  const r = pm.result;
  const [addHrs, setAddHrs] = useState(8);      // what-if: hrs/wk the elevation adds
  const [capex, setCapex]   = useState(500000); // what-if: ₹ one-off
  const [life, setLife]     = useState(5);      // what-if: years of benefit
  const hurdlePct = (typeof finBlendedHurdle==='function' ? finBlendedHurdle(config).wacc : ((window.M&&M.wacc&&M.wacc.rate)||11.4));
  const lineDuals = r ? (r.shadow_prices||[]).filter(s=>/^(Line hrs|Line:|Shared Capacity)/.test(s.constraint)) : [];
  const demBind   = r ? (r.shadow_prices||[]).filter(s=>s.binding && /^Max prod/.test(s.constraint)) : [];
  let dual = 0, dualName = null;
  lineDuals.forEach(s=>{ const v=Number(s.shadow_price)||0; if(v>dual){ dual=v; dualName=s.constraint; } });
  const annual = dual * Number(addHrs||0) * 52;
  const npv = useSolve('/api/calc/npv', ()=>({ cash_flows:[-Number(capex||0), ...Array.from({length:Math.max(1,Number(life||1))},()=>annual)], wacc:hurdlePct/100 }));
  const n = npv.result;
  const fmt = v=>`₹${Math.round(v).toLocaleString('en-IN')}`;
  if(!r) return (
    <Card icon="⛰️" title="Elevate the constraint" badge="VIS-5 · needs the mix solve"
      info={{ what:'Prices what elevating the binding constraint is worth: live profit-mix dual × hours freed → real NPV at the governed hurdle.', flows:'reads solve.profitmix.shadow_prices + /api/calc/npv — writes nothing.' }}>
      <div style={{padding:'16px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>💰 Optimize the mix (step 1 above) first — this card reads its live shadow prices.</div>
    </Card>
  );
  return (
    <Card icon="⛰️" title="Elevate the constraint" badge={dual>0?`capacity dual ₹${dual.toFixed(0)}/hr`:'lines slack — market binds'} badgeTone={dual>0?'r':'g'}
      right={<Provenance kind="solved" asOf={pm.ranAt?pm.ranAt.toLocaleTimeString?pm.ranAt.toLocaleTimeString():String(pm.ranAt):undefined}/>}
      info={{ what:'The dual is the solver’s own price of one more line-hour; the NPV is a real /api/calc/npv solve of (−capex, dual × hrs × 52 per year over the life) at the governed blended hurdle.', flows:'reads solve.profitmix.shadow_prices · /api/calc/npv on demand — writes nothing.' }}
      dev={{ comp:'Vis5Elevate', props:'profitmix shadow_prices → /api/calc/npv', note:'V3-7 · VIS-5 — what-if levers are card-local; dual + hurdle are live' }}>
      <div data-vis="vis5">
        <div style={{display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end', marginBottom:10}}>
          <Field label="Hours freed · what-if" hint="writes nothing"><NumInput value={addHrs} suffix="hrs/wk" w={110} onChange={v=>setAddHrs(v===''?0:Number(v))}/></Field>
          <Field label="Capex · what-if" hint="writes nothing"><NumInput value={capex} prefix="₹" w={120} onChange={v=>setCapex(v===''?0:Number(v))}/></Field>
          <Field label="Life · what-if" hint="writes nothing"><NumInput value={life} suffix="yrs" w={80} onChange={v=>setLife(v===''?1:Math.max(1,Number(v)))}/></Field>
          <Btn kind="accent" sm onClick={()=>npv.run().catch(()=>{})}>{npv.solving?'⏳ Pricing…':'⚡ Price it (real NPV)'}</Btn>
        </div>
        <div style={{padding:'10px 12px', border:`2px solid ${C.line}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.tx, display:'flex', gap:8, flexWrap:'wrap', alignItems:'center'}}>
          <span>dual <b className="num" style={{fontFamily:F.disp, color:dual>0?C.dg:C.tx2}}>₹{dual.toFixed(0)}/hr</b>{dualName?` (${dualName})`:' (every line slack)'}</span>
          <span style={{color:C.tx3}}>×</span>
          <span><b className="num" style={{fontFamily:F.disp}}>{addHrs}</b> hrs/wk × 52</span>
          <span style={{color:C.tx3}}>=</span>
          <span><b className="num" style={{fontFamily:F.disp, color:annual>0?C.gn:C.tx2}}>{fmt(annual)}</b>/yr unlocked</span>
          <span style={{color:C.tx3}}>→ {life}y vs {fmt(capex)} capex @ {hurdlePct.toFixed(1)}% hurdle →</span>
          {n && n.npv!=null
            ? <span>NPV <b className="num" style={{fontFamily:F.disp, fontSize:13, color:n.npv>0?C.gn:C.dg}}>{fmt(n.npv)}</b>{n.irr!=null && <span style={{color:C.tx2}}> · IRR {n.irr}%</span>} <Tag c={n.npv>0?'g':'r'}>{n.decision||(n.npv>0?'INVEST':'REJECT')}</Tag></span>
            : <span style={{color:C.tx3}}>press ⚡ to price it</span>}
          {npv.error && <span style={{color:C.dg}}>npv: {npv.error}</span>}
        </div>
        {dual<=0 && demBind.length>0 && (
          <div style={{marginTop:8, padding:'8px 12px', borderLeft:`4px solid ${C.gn}`, background:C.bg3, fontFamily:F.mono, fontSize:10, color:C.tx2}}>
            The lines are honestly SLACK — the market, not the factory, caps profit. The binding duals are demand ceilings:{' '}
            {demBind.map(s=>`${s.constraint.replace('Max prod: ','')} (₹${Number(s.shadow_price).toFixed(0)}/u)`).join(' · ')} — one more unit of WON demand is worth that much. Elevating THIS constraint means price, promotion or NPI on Demand — not machines.
          </div>
        )}
      </div>
      <Reading formula="value of elevation = dual(₹/hr) × hrs freed/wk × 52 per year · NPV = Σ CF_t ÷ (1+hurdle)^t with CF₀ = −capex — solved by /api/calc/npv, not local math"
        soWhat={dual>0
          ? `One more hour on the priced line is worth ₹${dual.toFixed(0)} of contribution — if the NPV above is positive at your real capex, capacity is the cheapest profit you can buy.`
          : 'A machine bought against a ₹0/hr dual is pure cost (NPV = −capex, as the chain shows). Spend the same money where the dual is positive — winning demand.'}/>
    </Card>
  );
}

// ── Q7b · margin sensitivity at landed / signal-adjusted costs ─────────────────
// The V2-2 cost chain left this as the deliberate remainder: the profit-mix LP
// optimises on effUnitCost (typed ≡ derived at seed) ON PURPOSE — landed cost
// (duty·freight·FX to the gate) and commodity-signal shocks must NOT silently
// move the committed mix. This card is the sensitivity that was promised instead:
//   ② the table re-prices each FG's margin on three bases with the SAME helpers
//      the solvers use — LP basis effUnitCost · landed (material → Σ qty ×
//      effLandedCost(part, getSourcing)) · signal (material × commodityFactor,
//      exactly the multiplier bomParts applies to procurement);
//   ③ ACT runs the REAL /api/solve/profitmix TWICE (current basis vs chosen
//      basis, same payload otherwise) and ④ shows where the optimal mix moves.
//   Nothing is cached, no markSolved — advisory by construction.
function Q7bMarginSensitivity(){
  useMasterRev();
  const { config } = useConfig();
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const cf = (typeof commodityFactor==='function') ? commodityFactor() : 1;
  const rows = fin.map(p=>{
    const b = unitCostBreakdown(p.sku) || { material:0, total:Number(p.cost)||0 };
    const landedMat = bomForSku(p.sku).reduce((s,ln)=>{
      const src = getSourcing(ln.part, ln);
      return s + (Number(ln.qty)||0) * effLandedCost(Number(ln.cost)||0, src);
    }, 0);
    const lp     = b.total;
    const landed = b.total - b.material + landedMat;
    const signal = b.total - b.material + b.material*cf;
    const price  = Number(p.price)||0;
    return { sku:p.sku, name:p.name, price,
      mLp: price-lp, mLanded: price-landed, mSignal: price-signal,
      cLp: lp, cLanded: landed, cSignal: signal };
  });
  const flips = rows.filter(r=> r.mLp>=0 && (r.mLanded<0 || r.mSignal<0));
  const [basis, setBasis] = useState('landed');
  const [cmp, setCmp]     = useState(null);   // { base:[], adj:[], basis, at }
  const [busy, setBusy]   = useState(false);
  const [err, setErr]     = useState(null);
  const runCompare = async ()=>{
    setBusy(true); setErr(null); setCmp(null);
    try{
      const basePay = profitmixPayload();
      const costOf = {}; rows.forEach(r=>{ costOf[r.sku] = basis==='landed' ? r.cLanded : r.cSignal; });
      const adjPay = { ...basePay, products: basePay.products.map(p=>({ ...p, variable_cost: Math.round((costOf[p.name]!=null?costOf[p.name]:p.variable_cost)*100)/100 })) };
      const [base, adj] = await Promise.all([apiPost('/api/solve/profitmix', basePay), apiPost('/api/solve/profitmix', adjPay)]);
      setCmp({ base:base.products||[], adj:adj.products||[], baseProfit:base.total_profit, adjProfit:adj.total_profit, basis, at:new Date() });
    }catch(e){ setErr(e.message||String(e)); }finally{ setBusy(false); }
  };
  const neutral = Math.abs(cf-1) < 1e-9;
  // mix delta between the two REAL solves (plain derivation — no inner component,
  // so the solved chip below traces to this component's apiPost, OBS-3)
  let cmpBy = null;
  if(cmp){
    const by = {}; cmp.base.forEach(p=>{ by[p.name] = { q0:Number(p.quantity)||0 }; });
    cmp.adj.forEach(p=>{ (by[p.name]=by[p.name]||{}).q1 = Number(p.quantity)||0; });
    const moved = Object.entries(by).map(([sku,v])=>({ sku, q0:v.q0||0, q1:v.q1||0 }))
      .filter(x=>Math.abs(x.q1-x.q0)>0.5).sort((a,b)=>Math.abs(b.q1-b.q0)-Math.abs(a.q1-a.q0));
    const dP = (cmp.adjProfit!=null && cmp.baseProfit!=null) ? cmp.adjProfit-cmp.baseProfit : null;
    cmpBy = { moved, dP };
  }
  return (
    <Card icon="🧭" title="Margin on three cost bases — LP · landed · signal" span={2} badge={flips.length?`${flips.length} flip negative`:'no sign flips'} badgeTone={flips.length?'r':'g'}
      right={<Provenance kind="derived" note="effUnitCost · effLandedCost · commodityFactor"/>}
      info={{ what:'The LP optimises contribution on effUnitCost by design. This re-prices each margin at LANDED cost (duty+freight+FX to the gate, the sourcing tab\'s own build-up) and at SIGNAL-adjusted material (the commodity index procurement already plans on) — then lets you re-solve the mix on either basis as an explicit advisory, never silently.', flows:'Q7b — sensitivity only; the committed mix basis is untouched.' }}
      dev={{ comp:'Q7bMarginSensitivity', props:'unitCostBreakdown × effLandedCost(getSourcing) × commodityFactor → 2× /api/solve/profitmix (advisory, uncached)' }}>
      <DataTable dense cols={['SKU','Price','Margin (LP basis)','@ landed','Δ landed','@ signal','Δ signal']}
        align={['left','right','right','right','right','right','right']}
        rows={rows.map(r=>({cells:[r.name, `₹${Math.round(r.price)}`,
          <span style={{fontWeight:700, color:r.mLp<0?C.dg:C.tx}}>₹{Math.round(r.mLp)}</span>,
          <span style={{fontWeight:700, color:r.mLanded<0?C.dg:C.tx}}>₹{Math.round(r.mLanded)}</span>,
          <span style={{color:r.mLanded-r.mLp<-0.5?C.dg:C.tx3}}>{Math.round(r.mLanded-r.mLp)||'—'}</span>,
          <span style={{fontWeight:700, color:r.mSignal<0?C.dg:C.tx}}>₹{Math.round(r.mSignal)}</span>,
          <span style={{color:r.mSignal-r.mLp<-0.5?C.dg:C.tx3}}>{neutral?'neutral':Math.round(r.mSignal-r.mLp)}</span>]}))}/>
      <div style={{display:'flex', gap:10, alignItems:'center', marginTop:10, flexWrap:'wrap'}}>
        <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.08em', color:C.tx3}}>RE-SOLVE THE MIX (ADVISORY) ON</span>
        {['landed','signal'].map(id=>(
          <button key={id} onClick={()=>setBasis(id)} style={{border:`2px solid ${basis===id?C.ink:C.line}`, background:basis===id?C.ink:C.paper, color:basis===id?C.ac:C.tx, fontFamily:F.disp, fontSize:10.5, fontWeight:700, padding:'4px 10px', cursor:'pointer'}}>{id==='landed'?'landed cost':'signal-adjusted'}</button>
        ))}
        <Btn kind="primary" sm onClick={runCompare}>{busy?'Solving 2×…':'🧪 Compare mixes'}</Btn>
        {neutral && basis==='signal' && <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>signals at neutral seed — identical until you move an index (Sourcing ▸ External signals)</span>}
      </div>
      {err && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.dg}}>⚠ {err}</div>}
      {cmpBy && (
        <div data-vis="q7b-compare" style={{marginTop:10, border:`2px solid ${C.line}`, borderLeft:`5px solid ${cmpBy.moved.length?C.a4:C.gn}`, padding:'9px 11px'}}>
          <div style={{display:'flex', gap:10, alignItems:'baseline', flexWrap:'wrap'}}>
            <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.08em', color:C.tx3}}>REAL LP × 2 — CURRENT vs {cmp.basis.toUpperCase()} BASIS</span>
            <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>profit ₹{((cmp.baseProfit||0)/1e5).toFixed(2)}L → ₹{((cmp.adjProfit||0)/1e5).toFixed(2)}L{cmpBy.dP!=null?` (${cmpBy.dP<0?'−':'+'}₹${Math.abs(cmpBy.dP/1e5).toFixed(2)}L)`:''}</span>
            <Provenance kind="solved" asOf={cmp.at.toLocaleTimeString()} style={{marginLeft:'auto'}}/>
          </div>
          {cmpBy.moved.length ? (
            <DataTable dense cols={['SKU','Mix now','Mix @ '+cmp.basis,'Δ units']} align={['left','right','right','right']}
              rows={cmpBy.moved.map(x=>({cells:[x.sku, Math.round(x.q0), Math.round(x.q1),
                <span style={{fontWeight:700, color:x.q1<x.q0?C.dg:C.gn}}>{x.q1>x.q0?'+':''}{Math.round(x.q1-x.q0)}</span>]}))}/>
          ) : (
            <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx3, padding:'6px 0'}}>The optimal mix does not move on this basis — the re-priced margins keep the same ranking under the same constraints.</div>
          )}
          <Reading tone={cmpBy.moved.length?C.a4:C.gn}
            formula={`same LP, same constraints — only variable_cost re-based (${cmp.basis})`}
            soWhat={cmpBy.moved.length
              ? `If costs are really ${cmp.basis==='landed'?'cost-to-gate (duty+freight+FX)':'at the shocked commodity index'}, the value-maximal mix shifts as shown — worth re-checking the committed plan against it. The committed basis stays effUnitCost; nothing was cached.`
              : 'Even on the re-priced basis the LP picks the same mix — the committed plan is robust to this cost lens. Nothing was cached.'}/>
        </div>
      )}
    </Card>
  );
}

window.StageProduction = StageProduction;
