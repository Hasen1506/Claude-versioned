// ════════════════════════════════════════════════════════════════════════
// plan.jsx — Aggregate Plan / S&OP (AggregateTab). Sub-tabs: Strategy ·
// Capacity · Workforce · Disaggregation.
// ════════════════════════════════════════════════════════════════════════
function StagePlan({ onNav }) {
  return (
    <div>
      <StageHeader n="05" title="Plan · Sales & Operations" kicker="Level-vs-chase strategy · seasonal prebuild · workforce plan · capacity duals · SKU disaggregation"
        right={<Btn kind="accent" onClick={()=>onNav('console')}>⚡ Solve Aggregate</Btn>}/>
      <div style={{padding:18}}>
        <StageSection step="1" title="Strategy" sub="level vs chase, and the seasonal prebuild it implies"><PlanStrategy/></StageSection>
        <StageSection step="2" title="Capacity & Duals" sub="demand vs capacity, and the shadow price of each binding resource"><PlanCapacity onNav={onNav}/></StageSection>
        <StageSection step="3" title="Workforce" sub="hire / fire / overtime by period"><PlanWorkforce/></StageSection>
        <StageSection step="4" title="Disaggregation" sub="family plan split back to SKUs by mix"><PlanDisagg/></StageSection>
      </div>
    </div>
  );
}

function CapacityChart() {
  const A=M.aggregate.months, W=720, H=200, pad=30;
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

function PlanStrategy() {
  const a=M.aggregate;
  return (
    <Grid cols={3}>
      <Card icon="⚖" title="Level vs Chase" badge={a.strategy} badgeTone="y" info={{ what:'Classifies the optimal aggregate strategy: level production vs chase demand.', flows:'Strategy → workforce & inventory plan.' }} span={2}
        dev={{ comp:'AggregateTab', props:'state.aggregatePlan', state:'aggregatePlan.strategy' }}>
        <div style={{display:'flex', gap:14, alignItems:'center'}}>
          <div style={{flex:1}}>
            <div style={{fontFamily:F.disp, fontSize:34, fontWeight:900, color:C.ac, letterSpacing:-1, WebkitTextStroke:`1px ${C.line}`}}>LEVEL</div>
            <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx2, marginTop:4, lineHeight:1.5}}>Steady output with inventory buffering beats chasing demand — lower hire/fire churn, OEE held high.</div>
          </div>
          <div style={{width:200}}>
            {[['Level fit',a.levelScore,C.gn],['Chase fit',a.chaseScore,C.tx3]].map(([k,v,c],i)=>(
              <div key={i} style={{marginBottom:8}}>
                <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:3}}><span>{k}</span><span className="num" style={{fontWeight:700}}>{(v*100).toFixed(0)}%</span></div>
                <MiniBar v={v} max={1} color={c} h={14}/>
              </div>
            ))}
          </div>
        </div>
        <div style={{marginTop:12}}><CapacityChart/></div>
      </Card>
      <Card icon="📦" title="Seasonal Prebuild Detector" badge={a.prebuild.detected?'DETECTED':'none'} badgeTone="k" info={{ what:'Flags months where demand exceeds capacity → prebuild earlier.', flows:'Prebuild qty → inventory plan.' }}
        dev={{ comp:'PrebuildCard', props:'state.aggregatePlan.prebuild' }}>
        <Blk label="Prebuild Month" value={a.prebuild.month} tone="y"/>
        <div style={{marginTop:8}}><Blk label="Prebuild Qty" value={`${a.prebuild.units} u`}/></div>
        <div style={{marginTop:10, padding:'9px 10px', border:`2px solid ${C.line}`, background:C.bg3, fontFamily:F.mono, fontSize:10, lineHeight:1.5}}>
          ◆ {a.prebuild.reason}. Build {a.prebuild.units}u in {a.prebuild.month}, hold to Jun.
        </div>
      </Card>
    </Grid>
  );
}

function PlanCapacity({ onNav }) {
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Capacity vs Demand" badge="6 periods" info={{ what:'Monthly demand against available capacity and planned production.', flows:'Shortfalls → prebuild & overtime.' }} span={2}
        dev={{ comp:'CapacityPlanCard', props:'state.aggregatePlan.months' }}>
        <CapacityChart/>
        <DataTable dense cols={['Month','Demand','Capacity','Production','Net Inv']} align={['left','right','right','right','right']}
          rows={M.aggregate.months.map(m=>({cells:[m.m, m.dem, m.cap, m.prod, <span style={{color:m.inv<0?C.dg:C.tx, fontWeight:700}}>{m.inv>0?'+':''}{m.inv}</span>]}))}/>
      </Card>
      <Card icon="🔑" title="Capacity Shadow Prices" badge="duals" badgeTone="y" info={{ what:'Marginal value of one more unit of each binding resource.', flows:'Duals → capital budget solver (where to invest).' }} span={2}
        right={<button onClick={()=>onNav&&onNav('finance')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>invest against this dual →</button>}
        dev={{ comp:'ShadowPriceCard', props:'state.aggregatePlan.shadow', note:'Consumed by Capital solver.' }}>
        <DataTable cols={['Resource','Dual (₹/u)','Slack','Status']} align={['left','right','right','left']}
          rows={M.shadow.map(s=>({__hl:s.binding, cells:[s.res, s.dual?`₹${s.dual.toFixed(2)}`:'—', s.slack, <Tag c={s.binding?'k':'w'}>{s.binding?'BINDING':'slack'}</Tag>]}))}/>
        <Reading formula="dual λ = ∂(objective) / ∂(capacity)  — ₹ saved per extra unit"
          soWhat="Line-1 is worth ₹1,248/u and binding — that’s the strongest case for the Heat-Treat #2 CapEx in Finance."/>
      </Card>
    </Grid>
  );
}

function PlanWorkforce() {
  return (
    <Card icon="👷" title="Workforce Plan · Hire / Fire / OT" badge="4 quarters" info={{ what:'Period workforce decisions: base heads, hire, fire, overtime.', flows:'Labour capacity → production MILP.' }}
      dev={{ comp:'WorkforceCard', props:'state.aggregatePlan.workforce', state:'aggregatePlan.workforce[]' }}>
      <DataTable cols={['Period','Base Heads','Hire','Fire','Overtime (hrs)']} align={['left','right','right','right','right']}
        rows={M.aggregate.workforce.map(w=>({cells:[w.period, w.base, <span style={{color:w.hire?C.gn:C.tx3, fontWeight:700}}>{w.hire?`+${w.hire}`:'—'}</span>, <span style={{color:w.fire?C.dg:C.tx3, fontWeight:700}}>{w.fire?`-${w.fire}`:'—'}</span>, w.ot]}))}/>
      <div style={{marginTop:12}}>
        <SubLabel>Headcount trajectory</SubLabel>
        <div style={{display:'flex', alignItems:'flex-end', gap:10, height:80}}>
          {M.aggregate.workforce.map((w,i)=>(
            <div key={i} style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:4}}>
              <div style={{width:'70%', height:`${w.base/52*100}%`, background:C.ink, border:`2px solid ${C.line}`}}/>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx2}}>{w.period}·{w.base}</span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function PlanDisagg() {
  const split=[['TPA-4471',32],['TPA-3215',46],['TPA-9904',12],['TPA-2188',6],['TPA-5540',4]];
  return (
    <Card icon="🔀" title="SKU Disaggregation" badge="aggregate → SKU" info={{ what:'Splits the aggregate family plan back to individual SKUs by mix.', flows:'SKU-level plan → MPS & procurement.' }}
      dev={{ comp:'DisaggregateCard', props:'state.aggregatePlan, mix', note:'disaggregate.py backend.' }}>
      <div style={{display:'flex', height:30, border:`2px solid ${C.line}`, marginBottom:14}}>
        {split.map(([s,w],i)=>(
          <div key={i} style={{width:`${w}%`, background:[C.ink,C.ac,C.a2,C.gn,C.a4][i], color: i===1?C.onAc:'#fff', display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, fontWeight:700, borderRight:i<4?`1px solid ${C.paper}`:'none'}}>{w}%</div>
        ))}
      </div>
      <DataTable cols={['SKU','Mix %','Family Qty','SKU Qty','Line']} align={['left','right','right','right','left']}
        rows={split.map(([s,w],i)=>[s, `${w}%`, '13,400', Math.round(13400*w/100).toLocaleString('en-IN'), M.products.find(p=>p.sku===s)?.line||'—'])}/>
    </Card>
  );
}
window.StagePlan = StagePlan;
