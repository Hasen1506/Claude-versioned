// ════════════════════════════════════════════════════════════════════════
// plan.jsx — Aggregate Plan / S&OP (AggregateTab). Sub-tabs: Strategy ·
// Capacity · Workforce · Disaggregation.
// ════════════════════════════════════════════════════════════════════════
// Seed planning economics — DEFAULT cost/capacity params for the aggregate solve.
// These are placeholders pending a dedicated Plan "cost inputs" card (deferred);
// they're chosen so the solve is non-degenerate and the capacity duals are real.
const PLAN_PARAMS = {
  init_workforce: 42, rate_per_worker: 30,        // ≈1,260 u/mo regular capacity
  reg_cost_per_unit: 820, ot_cost_per_unit: 1230, // ₹/u (OT = 1.5×)
  holding_cost_per_unit: 45, backorder_cost_per_unit: 1500,
  hire_cost: 18000, fire_cost: 25000, wage_per_worker: 22000,
  max_ot_pct: 0.25, min_workforce: 30, max_workforce: 60, allow_backorder: true,
};
// aggregate result → the {m,dem,cap,prod,inv} row shape the CapacityChart/table use.
function aggMonths(res){
  if(!res || !res.periods) return null;
  const rate = res.rate_per_worker || 0;
  return res.periods.map(p=>({
    m:'P'+p.period,
    dem:Math.round(p.demand),
    cap:Math.round(rate*p.workforce),
    prod:Math.round(p.regular_production + p.overtime_production),
    inv:Math.round(p.inventory - p.backorder),
  }));
}

// W4 — effective governed plan-cost param: override (config.planParams) else seed.
function planParam(config, k){
  const v = (config.planParams || {})[k];
  return (v!=null && v!=='') ? Number(v) : PLAN_PARAMS[k];
}
// W4 · PL-1 — the line registry total monthly capacity: the SAME M.lines the
// production MILP respects. The aggregate plan must reconcile to THIS ceiling,
// not to an arbitrary labor number (was the mock's single-line 1,240 u/mo).
function lineRegistryCapacity(){
  return (M.lines || []).reduce((s,l)=>s + (Number(l.cap)||0), 0);
}

function StagePlan({ onNav }) {
  const { config, setConfig } = useConfig();
  // family monthly demand (mock 6-month profile) split per finished SKU by annual share,
  // so the solver can disaggregate it back — sku_plans feeds the Disaggregation card.
  const rate = planParam(config, 'rate_per_worker') || 1;
  const lineCap = lineRegistryCapacity();
  // PL-1 — bound the workforce so regular capacity can never exceed the line
  // registry ceiling: max regular units = rate · max_workforce ≤ Σ line cap.
  const wfCeiling = Math.max(planParam(config,'min_workforce')+1, Math.round(lineCap / rate));
  const agg = useSolve('/api/solve/aggregate', ()=>{
    const fg = M.products.filter(p=>p.cat==='Finished');
    const months = M.aggregate.months;
    const totAnnual = fg.reduce((s,p)=>s+(p.demand||0),0) || 1;
    // labor_hours_per_unit — demand-weighted, mean-normalised labor content (cycle/60),
    // so a labor-heavy SKU consumes proportionally more family capacity WITHOUT rescaling
    // the aggregate vs the governed rate_per_worker (aggLaborWeights, store.jsx). Flat 1.0
    // fallback when no cycle data ⇒ unchanged default.
    const lw = (typeof aggLaborWeights==='function') ? aggLaborWeights(fg) : {};
    return {
      products: fg.map(p=>({
        name:p.sku,
        forecast: months.map(mo=> Math.max(0, Math.round(mo.dem * (p.demand||0)/totAnnual))),
        labor_hours_per_unit: lw[p.sku] != null ? lw[p.sku] : 1,
      })),
      params: {
        periods: months.length,
        init_workforce: PLAN_PARAMS.init_workforce,
        init_inventory: planParam(config,'init_inventory') || 0,   // opening FG stock (0 = greenfield)
        rate_per_worker: rate,
        reg_cost_per_unit: planParam(config,'reg_cost_per_unit'),
        ot_cost_per_unit: planParam(config,'ot_cost_per_unit'),
        holding_cost_per_unit: planParam(config,'holding_cost_per_unit'),
        backorder_cost_per_unit: PLAN_PARAMS.backorder_cost_per_unit,
        hire_cost: planParam(config,'hire_cost'),
        fire_cost: planParam(config,'fire_cost'),
        wage_per_worker: planParam(config,'wage_per_worker'),
        max_ot_pct: PLAN_PARAMS.max_ot_pct,
        min_workforce: PLAN_PARAMS.min_workforce,
        max_workforce: wfCeiling,                 // PL-1 — line-registry ceiling
        allow_backorder: PLAN_PARAMS.allow_backorder,
      },
    };
  }, { solveKey:'aggregate' });   // LP-C hydrate from loop cache
  const { stale, ranAt } = (typeof useStale==='function') ? useStale('aggregate') : { stale:false };
  const runAgg = ()=> agg.run().then(d=>{ if(typeof markSolved==='function') markSolved('aggregate'); return d; }).catch(()=>{});
  // Batch 4 — make the level-of-aggregation explicit. The S&OP plan pools every
  // finished SKU into a family/portfolio capacity & workforce plan; SKUs come back
  // in step 4. Users kept reading the family numbers as per-SKU numbers.
  const _finP = M.products.filter(p=>p.cat==='Finished');
  const famN = [...new Set(_finP.map(p=>p.family).filter(Boolean))].length;
  return (
    <div>
      <StageHeader n="05" title="Plan · Sales & Operations" kicker="Level-vs-chase strategy · seasonal prebuild · workforce plan · capacity duals · SKU disaggregation"
        right={<Btn kind="accent" onClick={runAgg}>{agg.solving?'⏳ Solving…':'⚡ Solve Aggregate'}</Btn>}/>
      <div style={{padding:'9px 18px', borderBottom:`2px solid ${C.line}`, background:C.bg3, display:'flex', alignItems:'center', gap:10}}>
        <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.12em', color:C.onAc, background:C.ink, padding:'3px 8px', whiteSpace:'nowrap'}}>VIEWING ▸ FAMILIES</span>
        <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.4}}>
          You're looking at <b>{famN||'all'} product {famN===1?'family':'families'}</b>, not individual SKUs. The aggregate plan pools every finished SKU's committed demand into one capacity &amp; workforce plan — per-SKU numbers are recovered in <b>step 4 · Disaggregation</b>.
        </span>
      </div>
      <div style={{padding:18}}>
        <SolverExplain id="aggregate"/>
        {agg.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Aggregate solver: {agg.error}</div>}
        {stale && <StaleMark since="(demand or cost inputs changed)" onNav={runAgg} go="rerun"/>}
        <StageSection step="0" title="Plan Cost Inputs" sub="governed — seed defaults you may override; the workforce is bounded so the plan can never exceed the line registry"><PlanParamsCard config={config} setConfig={setConfig} lineCap={lineCap} rate={rate} wfCeiling={wfCeiling} agg={agg} ranAt={ranAt}/></StageSection>
        <StageSection step="1" title="Strategy" sub="level vs chase, and the seasonal prebuild it implies"><PlanStrategy agg={agg}/></StageSection>
        <StageSection step="2" title="Capacity & Duals" sub="demand vs the line-registry ceiling; the labor dual vs the binding line"><PlanCapacity onNav={onNav} agg={agg} lineCap={lineCap}/></StageSection>
        <StageSection step="3" title="Workforce" sub="hire / fire / overtime by period — and the capacity gap each fills"><PlanWorkforce agg={agg} rate={rate}/></StageSection>
        <StageSection step="4" title="Disaggregation" sub="family plan split back to SKUs by mix"><PlanDisagg agg={agg}/></StageSection>
        <StageSection step="5" title="Gap to Target" sub="committed consensus plan vs business target — the S&OP outcome (moved here from Scenarios)"><PlanGap/></StageSection>
      </div>
    </div>
  );
}

// W4 · PL-3 — governed plan cost inputs (replaces the PLAN_PARAMS hardcodes as
// the EDITABLE surface; seeds still come from PLAN_PARAMS). Seed→override with
// provenance, same pattern as the Production + Sourcing solver-parameter cards.
function PlanParamsCard({ config, setConfig, lineCap, rate, wfCeiling, agg, ranAt }){
  const set = (k,v)=> setConfig({ planParams: { ...(config.planParams||{}), [k]:v } });
  const pp = config.planParams || {};
  return (
    <Card icon="🎛️" title="Aggregate-plan cost & capacity inputs" badge="governed" badgeTone="y"
      right={agg && agg.result ? <Provenance kind="solved" asOf={ranAt?ranAt.toLocaleTimeString():undefined}/> : null}
      info={{ what:'Per-unit production/holding costs and hire/fire/wage costs the Hax–Meal aggregate LP minimizes. Seeds you may override per run.', flows:'→ /api/solve/aggregate params.' }}
      dev={{ comp:'SolverInput', props:'config.planParams', state:'config.planParams.{rate_per_worker,reg_cost_per_unit,…}' }}>
      <Grid cols={4}>
        <SolverInput label="Rate / worker" seed={PLAN_PARAMS.rate_per_worker} value={pp.rate_per_worker} onChange={v=>set('rate_per_worker',v)} min={1} suffix="u/mo"/>
        <SolverInput label="Regular cost" seed={PLAN_PARAMS.reg_cost_per_unit} value={pp.reg_cost_per_unit} onChange={v=>set('reg_cost_per_unit',v)} min={0} prefix="₹"/>
        <SolverInput label="Overtime cost" seed={PLAN_PARAMS.ot_cost_per_unit} value={pp.ot_cost_per_unit} onChange={v=>set('ot_cost_per_unit',v)} min={0} prefix="₹"/>
        <SolverInput label="Holding cost" seed={PLAN_PARAMS.holding_cost_per_unit} value={pp.holding_cost_per_unit} onChange={v=>set('holding_cost_per_unit',v)} min={0} prefix="₹"/>
        <SolverInput label="Hire cost" seed={PLAN_PARAMS.hire_cost} value={pp.hire_cost} onChange={v=>set('hire_cost',v)} min={0} prefix="₹"/>
        <SolverInput label="Fire cost" seed={PLAN_PARAMS.fire_cost} value={pp.fire_cost} onChange={v=>set('fire_cost',v)} min={0} prefix="₹"/>
        <SolverInput label="Wage / worker" seed={PLAN_PARAMS.wage_per_worker} value={pp.wage_per_worker} onChange={v=>set('wage_per_worker',v)} min={0} prefix="₹"/>
        <SolverInput label="Opening FG inventory" seed={0} value={pp.init_inventory} onChange={v=>set('init_inventory',v)} min={0} suffix="u" hint="stock on hand at period 0 (0 = greenfield); offsets early-period production"/>
      </Grid>
      <Reading formula={`line-registry ceiling = Σ line cap = ${lineCap.toLocaleString('en-IN')} u/mo  ⇒  max workforce = ${lineCap.toLocaleString('en-IN')} ÷ ${rate} = ${wfCeiling} heads`}
        soWhat={`The plan is bounded to the SAME ${(M.lines||[]).length}-line capacity the production schedule respects (${(M.lines||[]).map(l=>l.cap.toLocaleString('en-IN')).join(' + ')} u/mo) — it can never promise more than the floor can physically build. Override the rate to re-scale the ceiling.`}/>
    </Card>
  );
}

function CapacityChart({ data }) {
  const A=(data&&data.length)?data:M.aggregate.months, W=720, H=200, pad=30;
  const mx=Math.max(...A.map(m=>Math.max(m.dem,m.cap,m.prod)))*1.1;
  const bw=(W-pad-8)/A.length;
  const y=v=>H-22-(v/mx)*(H-40);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', height:H, display:'block'}}>
      {[0,1,2,3].map(i=>(<line key={i} x1={pad} x2={W-8} y1={18+i*((H-40)/3)} y2={18+i*((H-40)/3)} stroke={C.line2} strokeWidth=".8"/>))}
      {/* capacity line */}
      <polyline points={A.map((m,i)=>`${pad+bw*i+bw/2},${y(m.cap)}`).join(' ')} fill="none" stroke={C.dg} strokeWidth="2" strokeDasharray="5 3"/>
      {A.map((m,i)=>{
        const x=pad+bw*i, cx=x+bw/2;
        return (<g key={i}>
          <rect x={x+bw*0.18} y={y(m.dem)} width={bw*0.3} height={H-22-y(m.dem)} fill={C.ink}/>
          <rect x={x+bw*0.5} y={y(m.prod)} width={bw*0.3} height={H-22-y(m.prod)} fill={C.ac}/>
          <text x={cx} y={H-7} fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{m.m}</text>
        </g>);
      })}
      <text x={pad+2} y="14" fontFamily={F.mono} fontSize="9" fill={C.tx3}>■ demand  ■ production  --- capacity</text>
    </svg>
  );
}

function PlanStrategy({ agg }) {
  const a=M.aggregate;
  const res = agg && agg.result;
  const months = aggMonths(res);
  const strat = res ? (res.strategy||'').toUpperCase() : a.strategy;
  return (
    <Grid cols={3}>
      <Card icon="⚖" title="Level vs Chase" badge={strat} badgeTone="y" info={{ what:'Classifies the optimal aggregate strategy: level production vs chase demand.', flows:'Strategy → workforce & inventory plan.' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'AggregateTab', props:'state.aggregatePlan', state:'aggregatePlan.strategy' }}>
        <div style={{display:'flex', gap:14, alignItems:'center'}}>
          <div style={{flex:1}}>
            <div style={{fontFamily:F.disp, fontSize:34, fontWeight:900, color:C.ac, letterSpacing:-1, WebkitTextStroke:`1px ${C.line}`}}>{strat}</div>
            <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx2, marginTop:4, lineHeight:1.5}}>{res ? res.strategy_note : 'Steady output with inventory buffering beats chasing demand — lower hire/fire churn, OEE held high.'}</div>
          </div>
          <div style={{width:200}}>
            {(res
              ? [['Workforce CV',res.workforce_cv,C.ink],['Inventory CV',res.inventory_cv,C.gn]]
              : [['Level fit',a.levelScore,C.gn],['Chase fit',a.chaseScore,C.tx3]]
            ).map(([k,v,c],i)=>(
              <div key={i} style={{marginBottom:8}}>
                <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:3}}><span>{k}</span><span className="num" style={{fontWeight:700}}>{res?(v*100).toFixed(1)+'%':(v*100).toFixed(0)+'%'}</span></div>
                <MiniBar v={res?Math.min(1,v*4):v} max={1} color={c} h={14}/>
              </div>
            ))}
            {res && <div style={{fontFamily:F.mono, fontSize:8, color:C.tx3, lineHeight:1.4}}>classifier: low workforce-CV + non-trivial inventory-CV ⇒ level</div>}
          </div>
        </div>
        <div style={{marginTop:12}}><CapacityChart data={months}/></div>
      </Card>
      <Card icon="📦" title="Seasonal Prebuild Detector" badge={(res?res.seasonal_prebuild:a.prebuild.detected)?'DETECTED':'none'} badgeTone="k" info={{ what:'Flags months where demand exceeds capacity → prebuild earlier.', flows:'Prebuild qty → inventory plan.' }}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'PrebuildCard', props:'state.aggregatePlan.prebuild' }}>
        {res ? (<>
          <Blk label="Build-ahead" value={res.seasonal_prebuild?'detected':'not needed'} tone="y"/>
          <div style={{marginTop:8}}><Blk label="Peak Inventory" value={`${res.peak_inventory} u`}/></div>
          <div style={{marginTop:8}}><Blk label="Total Backorder" value={`${res.total_backorder} u`}/></div>
          <div style={{marginTop:10, padding:'9px 10px', border:`2px solid ${C.line}`, background:C.bg3, fontFamily:F.mono, fontSize:10, lineHeight:1.5}}>
            ◆ {res.seasonal_prebuild?`Inventory peaks (${res.peak_inventory}u) BEFORE the demand peak — the plan builds ahead.`:'No build-ahead: capacity tracks demand within the horizon.'}
          </div>
        </>) : (<>
          <Blk label="Prebuild Month" value={a.prebuild.month} tone="y"/>
          <div style={{marginTop:8}}><Blk label="Prebuild Qty" value={`${a.prebuild.units} u`}/></div>
          <div style={{marginTop:10, padding:'9px 10px', border:`2px solid ${C.line}`, background:C.bg3, fontFamily:F.mono, fontSize:10, lineHeight:1.5}}>
            ◆ {a.prebuild.reason}. Build {a.prebuild.units}u in {a.prebuild.month}, hold to Jun.
          </div>
        </>)}
      </Card>
    </Grid>
  );
}

// W4 · PL-1/PL-2 — per-line load from the disaggregated SKU plan vs the line
// REGISTRY capacity. This is the line/machine pressure signal Capital should
// consume (NOT the labor dual) — the binding line is where machine CapEx pays
// back. Honest: at low demand every line shows slack (no CapEx case).
function linePressure(res){
  if(!res || !res.sku_plans || !res.sku_plans.length) return null;
  const T = (res.periods && res.periods.length) || 1;
  const byLine = {};
  res.sku_plans.forEach(sp=>{
    const prod = M.products.find(p=>p.sku===sp.name);
    const lid = (prod && prod.line) || '—';
    byLine[lid] = (byLine[lid]||0) + (sp.total_planned||0);
  });
  return (M.lines||[]).map(l=>{
    const load = byLine[l.id] || 0;             // units planned over the horizon
    const cap  = (Number(l.cap)||0) * T;        // line capacity over the same horizon
    const util = cap ? load/cap : 0;
    return { line:l.name, id:l.id, loadPerMo:Math.round(load/T), cap:l.cap,
             util, shortfall:Math.max(0, Math.round((load-cap)/T)), binding: util>=0.95 };
  });
}

// PL-A — payload for the line-capacity shadow-price LP. Each disaggregated SKU carries its
// MONTHLY planned demand (total_planned ÷ horizon), its assigned line, and its contribution
// margin (price − cost) as the lost-margin if that line can't build it. The LP's capacity
// dual is then the true ₹/unit value of one more unit of that line's capacity.
function linecapPayload(res){
  const T = (res && res.periods && res.periods.length) || 1;
  const lines = (M.lines || []).map(l=>({ id:l.id, name:l.name, cap:Number(l.cap)||0 }));
  const skus = ((res && res.sku_plans) || []).map(sp=>{
    const prod = M.products.find(p=>p.sku===sp.name) || {};
    return { name:sp.name, line:prod.line, demand:Math.round((sp.total_planned||0)/T),
             lost_margin_per_unit:Math.max(0, (prod.price||0)-(prod.cost||0)) };
  });
  return { lines, skus, params:{} };
}

function PlanCapacity({ onNav, agg, lineCap }) {
  const res = agg && agg.result;
  const months = aggMonths(res);
  const shadow = res && res.shadow_prices;
  const press = linePressure(res);
  // PL-A — the true ₹ line shadow price (dual of the line-capacity constraint). Manual run
  // (needs the solved sku_plans first). When solved, it replaces utilization-only "binding"
  // with an economically-grounded one: a line binds iff its capacity dual > 0.
  const lc = useSolve('/api/solve/linecap', ()=>linecapPayload(res), { solveKey:'linecap' });   // LP-C hydrate from loop cache
  const lcByLine = {};
  if(lc.result && lc.result.lines) lc.result.lines.forEach(l=>{ lcByLine[l.line_id] = l; });
  const lcSolved = !!(lc.result && lc.result.lines);
  const bind = lcSolved
    ? press && press.find(p=>(lcByLine[p.id]||{}).binding)
    : press && press.find(p=>p.binding);
  const runLc = ()=> lc.run().catch(()=>{});
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Capacity vs Demand" badge={`${(months||M.aggregate.months).length} periods · ceiling ${lineCap?lineCap.toLocaleString('en-IN'):'—'} u/mo`} info={{ what:'Monthly demand against the planned regular-labor capacity (rate × workforce), bounded by the line-registry ceiling.', flows:'Shortfalls → prebuild & overtime.' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'CapacityPlanCard', props:'aggregate.periods, lineCap' }}>
        <CapacityChart data={months}/>
        <DataTable dense cols={['Period','Demand','Labor cap','Production','Net Inv']} align={['left','right','right','right','right']}
          rows={(months||M.aggregate.months).map(m=>({cells:[m.m, m.dem, m.cap, m.prod, <span style={{color:m.inv<0?C.dg:C.tx, fontWeight:700}}>{m.inv>0?'+':''}{m.inv}</span>]}))}/>
        <Reading formula={`line-registry ceiling = Σ line cap = ${lineCap?lineCap.toLocaleString('en-IN'):'—'} u/mo  ·  "Labor cap" column = rate × workforce that period`}
          soWhat="The capacity the plan deploys each period is the LABOR capacity (rate × heads); it can rise only to the line-registry ceiling above. Demand under the ceiling means the lines are not the constraint — labor is. The family demand is labor-weighted by each SKU's cycle time (mean-normalised, so the rate/worker calibration is preserved) — a labor-heavy SKU correctly consumes more of this capacity, and the family plan is split back to physical SKU units in step 4."/>
      </Card>
      <Card icon="🔑" title="Labor Capacity Shadow Prices" badge={shadow?`${shadow.length} duals · live`:'duals'} badgeTone="y" info={{ what:'Marginal value of one more WORKER-PERIOD of regular capacity (the aggregate LP dual). This is a labor dual — not a line/machine dual.', flows:'Labor duals → hire/OT decision, NOT line CapEx.' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'ShadowPriceCard', props:'aggregate.shadow_prices', note:'Worker-period duals (P_t ≤ rate·W_t).' }}>
        {shadow ? (
          shadow.length ? <DataTable cols={['Constraint','Dual (₹/worker-unit)','Slack','Status']} align={['left','right','right','left']}
            rows={shadow.map(s=>({__hl:s.binding, cells:[s.constraint, s.shadow_price?`₹${Number(s.shadow_price).toFixed(2)}`:'—', s.slack==null?'—':s.slack, <Tag c={s.binding?'k':'w'}>{s.binding?'BINDING':'slack'}</Tag>]}))}/>
          : <div style={{padding:'12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>No binding labor-capacity rows — the plan has workforce slack everywhere (no resource is worth expanding at these costs).</div>
        ) : (
          <div style={{padding:'12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Solve the aggregate plan to see the live labor duals.</div>
        )}
        <Reading formula="labor dual λ = ∂(objective) / ∂(worker-period capacity)  — ₹ saved per extra worker-unit"
          soWhat="A binding labor dual means the answer is hire/overtime, not machines. Line/machine CapEx is justified by the line-pressure table below — a different constraint."/>
      </Card>
      <Card icon="🏭" title="Line Capacity Pressure" badge={press?(bind?`${bind.line} binding`:(lcSolved?'all slack · ₹0':'all slack')):'solve first'} badgeTone="k" span={2}
        info={{ what:'The disaggregated SKU plan loaded onto each line vs its registry capacity, plus the TRUE ₹ shadow price of each line\'s capacity (PL-A, dual of a min-cost assignment LP). The binding line is where machine CapEx pays back — the line/machine signal Capital consumes (not the labor dual).', flows:'Binding line + ₹ shadow price → Capital / Investment Decision.' }}
        right={<div style={{marginLeft:'auto', display:'flex', alignItems:'center', gap:10}}>
          {res ? (lcSolved ? <Provenance kind="solved" asOf={lc.ranAt?lc.ranAt.toLocaleTimeString():undefined}/>
            : <Btn kind="primary" sm onClick={runLc}>{lc.solving?'⏳ Pricing…':'₹ Price capacity'}</Btn>) : null}
          {res && bind ? <button onClick={()=>onNav&&onNav('finance')} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>invest in {bind.line} →</button> : null}
        </div>}
        dev={{ comp:'LinePressureTable', props:'aggregate.sku_plans grouped by line vs M.lines.cap + /api/solve/linecap dual' }}>
        {lc.error && <div style={{marginBottom:8, fontFamily:F.mono, fontSize:9.5, color:C.dg}}>Line-capacity LP: {lc.error}</div>}
        {press ? (
          <DataTable cols={['Line','Planned u/mo','Registry cap','Util','Shortfall u/mo','₹ shadow / cap unit','Status']} align={['left','right','right','right','right','right','left']}
            rows={press.map(p=>{ const l = lcByLine[p.id]; const binds = lcSolved ? (l&&l.binding) : p.binding;
              return {__hl:binds, cells:[p.line, p.loadPerMo.toLocaleString('en-IN'), p.cap.toLocaleString('en-IN'),
              <span style={{fontWeight:700, color:p.util>0.95?C.dg:C.tx}}>{(p.util*100).toFixed(0)}%</span>,
              p.shortfall?`+${p.shortfall.toLocaleString('en-IN')}`:'—',
              lcSolved ? <span style={{fontWeight:700, color:(l&&l.shadow_price)?C.dg:C.tx3}}>{l&&l.shadow_price?`₹${l.shadow_price.toLocaleString('en-IN')}`:'₹0'}</span> : <span style={{color:C.tx3}}>—</span>,
              <Tag c={binds?'k':'w'}>{binds?'BINDING':'slack'}</Tag>]};})}/>
        ) : (
          <div style={{padding:'12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Solve the aggregate plan — the SKU disaggregation loads each line against its registry capacity here.</div>
        )}
        <Reading formula={lcSolved?"₹ shadow = dual of (Σ SKU load on line ≤ line cap) in a min-cost assignment LP — ₹ of contribution margin one more unit of capacity unlocks":"line util = Σ(planned SKU qty on the line) ÷ (line registry cap × horizon)"}
          soWhat={press?(bind?`${bind.line} binds at a ₹${(lcByLine[bind.id]||{}).shadow_price||'—'}/unit shadow price — every extra unit of its capacity recovers that much lost margin. THAT is the CapEx case Finance capitalizes (F-8 consumes this as the capacity shadow price).`:(lcSolved?'Priced: every line\'s capacity dual is ₹0 — they all have slack, so no machine CapEx is justified at this demand. The constraint is labor (see the duals above), not the lines. The mechanism is live: when demand pressures a line its dual turns positive here.':'Every line has slack at this demand — press "₹ Price capacity" to confirm the line duals are ₹0 (no CapEx case) vs the labor dual above.')):'—'}/>
      </Card>
    </Grid>
  );
}

function PlanWorkforce({ agg, rate }) {
  const res = agg && agg.result;
  const r = Number(rate) || PLAN_PARAMS.rate_per_worker || 1;
  // PL-5 — tie each period's hire/OT back to the capacity GAP it fills:
  // gap = demand − regular capacity at the START-of-period headcount (rate × prior heads).
  // A positive gap is exactly what the hire + overtime in that row exist to cover.
  const wf = res && res.periods
    ? res.periods.map((p,i,arr)=>{
        const priorHeads = i===0 ? PLAN_PARAMS.init_workforce : Math.round(arr[i-1].workforce);
        const gap = Math.max(0, Math.round((p.demand||0) - r*priorHeads));
        return { period:'P'+p.period, base:Math.round(p.workforce), hire:Math.round(p.hires), fire:Math.round(p.fires),
                 ot:Math.round(p.overtime_production), gap };
      })
    : M.aggregate.workforce.map(w=>({ ...w, gap:null }));
  const otLabel = res ? 'Overtime (u)' : 'Overtime (hrs)';
  const wfMax = Math.max(...wf.map(w=>w.base), 1);
  return (
    <Card icon="👷" title="Workforce Plan · Hire / Fire / OT" badge={res?`${wf.length} periods · live`:'4 quarters'} info={{ what:'Period workforce decisions: base heads, hire, fire, overtime — and the demand-vs-capacity gap each fills.', flows:'Labour capacity → production MILP.' }}
      right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
      dev={{ comp:'WorkforceCard', props:'aggregate.periods (workforce, hires, fires, OT, demand)' }}>
      <DataTable cols={['Period','Base Heads','Hire','Fire',otLabel,'Fills gap (u)']} align={['left','right','right','right','right','right']}
        rows={wf.map(w=>({cells:[w.period, w.base, <span style={{color:w.hire?C.gn:C.tx3, fontWeight:700}}>{w.hire?`+${w.hire}`:'—'}</span>, <span style={{color:w.fire?C.dg:C.tx3, fontWeight:700}}>{w.fire?`-${w.fire}`:'—'}</span>, w.ot, w.gap==null?'—':<span style={{color:w.gap>0?C.dg:C.tx3, fontWeight:700}}>{w.gap>0?`+${w.gap}`:'0'}</span>]}))}/>
      {res && <Reading formula="gap = demand − rate × (start-of-period heads)   ·   filled by hire + overtime that period"
        soWhat="A positive gap is the capacity hole the period's hire + overtime exist to close — when the gap is 0 the base workforce already covers demand and any OT is buffering, not catching up."/>}
      <div style={{marginTop:12}}>
        <SubLabel>Headcount trajectory</SubLabel>
        <div style={{display:'flex', alignItems:'flex-end', gap:10, height:80}}>
          {wf.map((w,i)=>(
            <div key={i} style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:4}}>
              <div style={{width:'70%', height:`${w.base/(res?wfMax:52)*100}%`, background:C.ink, border:`2px solid ${C.line}`}}/>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx2}}>{w.period}·{w.base}</span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function PlanDisagg({ agg }) {
  const res = agg && agg.result;
  const palette=[C.ink,C.ac,C.a2,C.gn,C.a4,C.a3,C.dg];
  // when solved, DERIVE the split from the solver's per-SKU disaggregation (sku_plans);
  // mix % = each SKU's planned share of the total planned family quantity.
  let split, familyQty;
  if(res && res.sku_plans && res.sku_plans.length){
    familyQty = res.sku_plans.reduce((s,p)=>s+(p.total_planned||0),0) || 1;
    split = res.sku_plans.map(p=>[p.name, +(100*(p.total_planned||0)/familyQty).toFixed(1), p.total_planned]);
  } else {
    familyQty = 13400;
    split = [['TPA-4471',32],['TPA-3215',46],['TPA-9904',12],['TPA-2188',6],['TPA-5540',4]].map(([s,w])=>[s,w,Math.round(13400*w/100)]);
  }
  // PL-4 — name the family + horizon explicitly so the split is not a mystery slice.
  const nFG = M.products.filter(p=>p.cat==='Finished').length;
  const horizon = (M.aggregate.months||[]).length;
  return (
    <Card icon="🔀" title="SKU Disaggregation" badge={res?'aggregate → SKU · solved':'aggregate → SKU · seed'} info={{ what:`Splits the solved aggregate family plan (${nFG} finished SKUs, ${horizon}-month horizon) back to individual SKUs by each SKU's planned share. Seed shares shown until solved.`, flows:'SKU-level plan → MPS & procurement.' }}
      right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
      dev={{ comp:'DisaggregateCard', props:'aggregate.sku_plans (total_planned share)', note:'derived from the solved aggregate plan; seed split until solved.' }}>
      <div style={{marginBottom:10, fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>FAMILY: all finished goods ({nFG} SKUs) · HORIZON: {horizon} months · BASIS: {res?'solved per-SKU planned quantity':'annual-demand seed share (not yet solved)'}</div>
      <div style={{display:'flex', height:30, border:`2px solid ${C.line}`, marginBottom:14}}>
        {split.map(([s,w],i)=>(
          <div key={i} style={{width:`${w}%`, background:palette[i%palette.length], color: i===1?C.onAc:'#fff', display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, fontWeight:700, borderRight:i<split.length-1?`1px solid ${C.paper}`:'none'}}>{w}%</div>
        ))}
      </div>
      <DataTable cols={['SKU','Mix %','Family Qty','SKU Qty','Line']} align={['left','right','right','right','left']}
        rows={split.map(([s,w,q])=>[s, `${w}%`, Math.round(familyQty).toLocaleString('en-IN'), Math.round(q).toLocaleString('en-IN'), M.products.find(p=>p.sku===s)?.line||'—'])}/>
    </Card>
  );
}
// S&OP Gap — relocated from Scenarios·Performance (app_v2). This is the
// reconciliation OUTCOME of the S&OP stage, so it belongs at the end of Plan.
function PlanGap() {
  return (
    <Card icon="📋" title="S&OP Gap · Plan vs Target" badge="reconciliation" badgeTone="y"
      info={{ what:'Where the committed consensus plan stands against the business target — volume, revenue, margin, inventory.', flows:'Gaps → next S&OP cycle re-plan & Profit-mix.' }}
      right={<Provenance kind="derived" asOf={M.updated.split('·')[1].trim()}/>}
      dev={{ comp:'SOPGapCard', props:'aggregatePlan.sopGap', note:'Relocated from Scenarios·Performance (app_v2).' }}>
      <KpiRow cols={4}>
        <Blk label="Volume" value={`+${M.sop.volumeGap}%`} accent={C.gn}/>
        <Blk label="Revenue" value={`${M.sop.revGap}%`} accent={C.dg}/>
        <Blk label="Margin" value={`+${M.sop.marginGap}%`} accent={C.gn}/>
        <Blk label="Inventory" value={`${M.sop.inventoryGap}%`} accent={C.dg}/>
      </KpiRow>
      <Reading formula="gap = committed plan − target, per dimension"
        soWhat="Volume is +4.2% to target but revenue −1.8% — the plan wins units on lower-margin SKUs; tighten the mix in Profit-mix before committing."/>
    </Card>
  );
}
window.StagePlan = StagePlan;
