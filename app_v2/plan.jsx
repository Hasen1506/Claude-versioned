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

function StagePlan({ onNav }) {
  // family monthly demand (mock 6-month profile) split per finished SKU by annual share,
  // so the solver can disaggregate it back — sku_plans feeds the Disaggregation card.
  const agg = useSolve('/api/solve/aggregate', ()=>{
    const fg = M.products.filter(p=>p.cat==='Finished');
    const months = M.aggregate.months;
    const totAnnual = fg.reduce((s,p)=>s+(p.demand||0),0) || 1;
    return {
      products: fg.map(p=>({
        name:p.sku,
        forecast: months.map(mo=> Math.max(0, Math.round(mo.dem * (p.demand||0)/totAnnual))),
        labor_hours_per_unit: 1,
      })),
      params: { periods: months.length, ...PLAN_PARAMS },
    };
  });
  return (
    <div>
      <StageHeader n="05" title="Plan · Sales & Operations" kicker="Level-vs-chase strategy · seasonal prebuild · workforce plan · capacity duals · SKU disaggregation"
        right={<Btn kind="accent" onClick={()=>agg.run().catch(()=>{})}>{agg.solving?'⏳ Solving…':'⚡ Solve Aggregate'}</Btn>}/>
      <div style={{padding:18}}>
        {agg.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Aggregate solver: {agg.error}</div>}
        <StageSection step="1" title="Strategy" sub="level vs chase, and the seasonal prebuild it implies"><PlanStrategy agg={agg}/></StageSection>
        <StageSection step="2" title="Capacity & Duals" sub="demand vs capacity, and the shadow price of each binding resource"><PlanCapacity onNav={onNav} agg={agg}/></StageSection>
        <StageSection step="3" title="Workforce" sub="hire / fire / overtime by period"><PlanWorkforce agg={agg}/></StageSection>
        <StageSection step="4" title="Disaggregation" sub="family plan split back to SKUs by mix"><PlanDisagg agg={agg}/></StageSection>
        <StageSection step="5" title="Gap to Target" sub="committed consensus plan vs business target — the S&OP outcome (moved here from Scenarios)"><PlanGap/></StageSection>
      </div>
    </div>
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

function PlanCapacity({ onNav, agg }) {
  const res = agg && agg.result;
  const months = aggMonths(res);
  const shadow = res && res.shadow_prices;
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Capacity vs Demand" badge={`${(months||M.aggregate.months).length} periods`} info={{ what:'Monthly demand against available capacity and planned production.', flows:'Shortfalls → prebuild & overtime.' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'CapacityPlanCard', props:'state.aggregatePlan.months' }}>
        <CapacityChart data={months}/>
        <DataTable dense cols={['Period','Demand','Capacity','Production','Net Inv']} align={['left','right','right','right','right']}
          rows={(months||M.aggregate.months).map(m=>({cells:[m.m, m.dem, m.cap, m.prod, <span style={{color:m.inv<0?C.dg:C.tx, fontWeight:700}}>{m.inv>0?'+':''}{m.inv}</span>]}))}/>
      </Card>
      <Card icon="🔑" title="Capacity Shadow Prices" badge={shadow?`${shadow.length} duals · live`:'duals'} badgeTone="y" info={{ what:'Marginal value of one more unit of each binding resource.', flows:'Duals → capital budget solver (where to invest).' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : <button onClick={()=>onNav&&onNav('finance')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>invest against this dual →</button>}
        dev={{ comp:'ShadowPriceCard', props:'state.aggregatePlan.shadow', note:'Consumed by Capital solver.' }}>
        {shadow ? (
          shadow.length ? <DataTable cols={['Constraint','Dual (₹/u)','Slack','Status']} align={['left','right','right','left']}
            rows={shadow.map(s=>({__hl:s.binding, cells:[s.constraint, s.shadow_price?`₹${Number(s.shadow_price).toFixed(2)}`:'—', s.slack==null?'—':s.slack, <Tag c={s.binding?'k':'w'}>{s.binding?'BINDING':'slack'}</Tag>]}))}/>
          : <div style={{padding:'12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>No binding capacity rows — the plan has slack everywhere (no resource is worth expanding at these costs).</div>
        ) : (
          <DataTable cols={['Resource','Dual (₹/u)','Slack','Status']} align={['left','right','right','left']}
            rows={M.shadow.map(s=>({__hl:s.binding, cells:[s.res, s.dual?`₹${s.dual.toFixed(2)}`:'—', s.slack, <Tag c={s.binding?'k':'w'}>{s.binding?'BINDING':'slack'}</Tag>]}))}/>
        )}
        <Reading formula="dual λ = ∂(objective) / ∂(capacity)  — ₹ saved per extra unit"
          soWhat={shadow?"Each binding regular-capacity period is worth its dual per extra worker-unit — the periods with the largest duals are the strongest case for a CapEx shift in Finance.":"Line-1 is worth ₹1,248/u and binding — that’s the strongest case for the Heat-Treat #2 CapEx in Finance."}/>
      </Card>
    </Grid>
  );
}

function PlanWorkforce({ agg }) {
  const res = agg && agg.result;
  // real solver gives heads (workforce) + OT in production units; mock gives heads + OT hrs.
  const wf = res && res.periods
    ? res.periods.map(p=>({ period:'P'+p.period, base:Math.round(p.workforce), hire:Math.round(p.hires), fire:Math.round(p.fires), ot:Math.round(p.overtime_production) }))
    : M.aggregate.workforce;
  const otLabel = res ? 'Overtime (u)' : 'Overtime (hrs)';
  const wfMax = Math.max(...wf.map(w=>w.base), 1);
  return (
    <Card icon="👷" title="Workforce Plan · Hire / Fire / OT" badge={res?`${wf.length} periods · live`:'4 quarters'} info={{ what:'Period workforce decisions: base heads, hire, fire, overtime.', flows:'Labour capacity → production MILP.' }}
      right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
      dev={{ comp:'WorkforceCard', props:'state.aggregatePlan.workforce', state:'aggregatePlan.workforce[]' }}>
      <DataTable cols={['Period','Base Heads','Hire','Fire',otLabel]} align={['left','right','right','right','right']}
        rows={wf.map(w=>({cells:[w.period, w.base, <span style={{color:w.hire?C.gn:C.tx3, fontWeight:700}}>{w.hire?`+${w.hire}`:'—'}</span>, <span style={{color:w.fire?C.dg:C.tx3, fontWeight:700}}>{w.fire?`-${w.fire}`:'—'}</span>, w.ot]}))}/>
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
  return (
    <Card icon="🔀" title="SKU Disaggregation" badge={res?'aggregate → SKU · live':'aggregate → SKU'} info={{ what:'Splits the aggregate family plan back to individual SKUs by mix.', flows:'SKU-level plan → MPS & procurement.' }}
      right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
      dev={{ comp:'DisaggregateCard', props:'state.aggregatePlan, mix', note:'disaggregate.py backend.' }}>
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
