// ════════════════════════════════════════════════════════════════════════
// console.jsx — Optimize & Solve (OptimizeTab) — the god-tab, split per P1:
//   · CARTESIAN SOLVER-MAP (priority layout): 7 solvers plotted on a
//     horizon × decision-domain plane, edges = data hand-offs.
//   · RUN CONSOLE: mode picker + constraint toggles + solve + status.
//   · RESULT SUB-TABS grouped by solver.
// ════════════════════════════════════════════════════════════════════════
// (Removed the bespoke CartesianSolverMap — Console now renders the SAME
// <SolverNetwork/> component as Home, from the same data, per handoff v2 §1.3.)

function StageConsole({ onNav }) {
  const [sel, setSel] = useState('procurement');          // selected engine (graph ↔ results)
  const [modes, setModes] = useState(()=>M.solverModes.filter(m=>m.sel).map(m=>m.id));
  const [cons, setCons] = useState(()=>Object.fromEntries(M.constraints.map(c=>[c.id,c.on])));
  const resultKey = { profitmix:'profit', procurement:'procurement', production:'production', sequencing:'production', transport:'transport', allocation:'transport', consolidate:'transport', montecarlo:'risk', cvar:'risk', capital:'capital', capital_capacity:'capital', sop:'sop', forecast:'profit', aggregate:'sop', disaggregate:'sop', reconcile:'sop', lotsizing:'procurement' }[sel] || 'procurement';
  const sections = M.consoleResults[resultKey] || [];
  const selSolver = M.solvers.find(s=>s.id===sel);

  return (
    <div>
      <StageHeader n="10" title="Optimize & Solve Console" kicker={`${M.solverLabel} on one shared network · run control · solver-grouped results that deep-link to stages`}
        right={<Btn kind="accent">⚡ Solve all queued</Btn>}/>

      {/* PLANNING SPINE (handoff v2 §7.1) — the ordered solve chain, conditional on profile */}
      <div style={{padding:'14px 14px 0'}}>
        <Card icon="🧬" title="Planning Spine" badge="9 steps · profile-gated" badgeTone="k"
          info={{ what:'The order solvers run in — with steps your profile makes unnecessary greyed out.', flows:'Profit-mix only exists to ration scarce capacity; ample capacity skips it.' }}
          dev={{ comp:'PlanningSpine', props:'M.spine, profileGate', note:'A step’s gate references a profile answer (e.g. capacity ample → skip Profit-mix).' }}>
          <PlanningSpine onNav={onNav}/>
        </Card>
      </div>

      <div style={{padding:14, display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:14}}>
        {/* SHARED SOLVER NETWORK (same component as Home) */}
        <Card icon="🧭" title="Solver Network" badge={M.solverLabel} badgeTone="y" info={{ what:'The same 5-family network shown on Home; click a node to load its run mode + results.', flows:'One graph, one data source.' }}
          dev={{ comp:'SolverNetwork', props:'solvers, edges, sel, onSelect', note:'Identical to Home (handoff v2 §1.3).' }}>
          <div style={{overflowX:'auto'}}><SolverNetwork sel={sel} onSelect={setSel}/></div>
          <div style={{marginTop:8, display:'flex', gap:8, alignItems:'center'}}>
            <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>selected:</span>
            <Tag c="k">{selSolver?selSolver.name:sel}</Tag>
            {selSolver && <button onClick={()=>onNav(selSolver.go)} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>open {selSolver.go} →</button>}
          </div>
        </Card>

        {/* RUN CONSOLE */}
        <div style={{display:'flex', flexDirection:'column', gap:14}}>
          <Card icon="⚡" title="Run Console" badge="mode + constraints" info={{ what:'Pick solver mode(s), toggle constraints, solve.', flows:'POSTs to /api/solve/*.' }}
            dev={{ comp:'OptimizeTab', props:'state, dispatch(SOLVE_FINISHED)', state:'solve.mode, solve.constraints', note:'Run control only — results split out per P1.' }}>
            <SubLabel>Solver mode</SubLabel>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:5}}>
              {M.solverModes.map(m=>{ const on=modes.includes(m.id);
                return (
                  <button key={m.id} onClick={()=>setModes(s=> on?s.filter(x=>x!==m.id):[...s,m.id])} style={{
                    textAlign:'left', padding:'6px 8px', border:`2px solid ${C.line}`, cursor:'pointer',
                    background: on?C.ink:C.paper, color: on?C.ac:C.tx, fontFamily:F.disp, fontSize:10, fontWeight:700,
                    display:'flex', alignItems:'center', gap:6,
                  }}>
                    <span style={{width:9, height:9, flexShrink:0, background: on?C.ac:'transparent', border:`1.5px solid ${on?C.ac:C.line2}`}}/>
                    {m.label}
                  </button>
                );
              })}
            </div>
            <div style={{marginTop:10}}><SubLabel>Constraints</SubLabel></div>
            <div style={{display:'flex', flexWrap:'wrap', gap:5}}>
              {M.constraints.map(c=>{ const on=cons[c.id];
                return (
                  <button key={c.id} onClick={()=>setCons(s=>({...s,[c.id]:!s[c.id]}))} style={{
                    padding:'4px 8px', border:`2px solid ${C.line}`, cursor:'pointer', fontFamily:F.mono, fontSize:9.5, fontWeight:700,
                    background: on?C.ac:C.paper, color: on?C.onAc:C.tx3, textTransform:'uppercase',
                  }}>{on?'✓ ':'○ '}{c.label}</button>
                );
              })}
            </div>
            <div style={{marginTop:12, display:'flex', gap:8}}>
              <Btn kind="primary" style={{flex:1, justifyContent:'center'}}>▶ SOLVE ({modes.length})</Btn>
              <Btn kind="secondary">Reset</Btn>
            </div>
          </Card>

          <Card icon="📡" title="Solve Status" badge={selSolver?selSolver.status:'idle'} badgeTone="k" info={{ what:'Objective, runtime and binding constraints of the last solve.', flows:'Status → pipeline ribbon.' }}
            dev={{ comp:'SolveStatus', props:'solve.result' }}>
            <KpiRow cols={3}>
              <Blk label="Status" value={selSolver?selSolver.status:'—'} tone={selSolver&&selSolver.status==='done'?'y':'c'}/>
              <Blk label="Objective" value={selSolver?selSolver.obj:'—'}/>
              <Blk label="Runtime" value={selSolver&&selSolver.t?`${selSolver.t}s`:'—'}/>
            </KpiRow>
            <div style={{marginTop:10}}><SubLabel>Shadow prices · binding</SubLabel></div>
            <DataTable dense cols={['Resource','Dual','Status']} align={['left','right','left']}
              rows={M.shadow.filter(s=>s.binding).map(s=>[s.res, `₹${s.dual.toFixed(0)}`, <Tag c="k">BIND</Tag>])}/>
            <SolverIO id={sel}/>
          </Card>
        </div>
      </div>

      {/* RESULT SUB-TABS grouped by solver */}
      <div style={{padding:'0 14px 14px'}}>
        <div style={{border:`2px solid ${C.line}`, background:C.bg2}}>
          <div style={{display:'flex', flexWrap:'wrap', borderBottom:`2px solid ${C.line}`}}>
            {[['profitmix','Profit'],['procurement','Procurement'],['production','Production'],['transport','Transport'],['montecarlo','Risk/MC'],['capital','Capital'],['sop','S&OP']].map(([id,lbl])=>{
              const a=sel===id;
              return (
                <button key={id} onClick={()=>setSel(id)} style={{
                  padding:'8px 14px', border:'none', borderRight:`2px solid ${C.line}`, cursor:'pointer',
                  background: a?C.ac:'transparent', color:C.tx, fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.04em', textTransform:'uppercase',
                }}>{lbl}</button>
              );
            })}
            <span style={{marginLeft:'auto', alignSelf:'center', padding:'0 14px', fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>{sections.length} result sections</span>
          </div>
          <div style={{padding:14}}>
            <ConsoleResults solver={sel} sections={sections}/>
          </div>
        </div>
      </div>
    </div>
  );
}

// result sections — hero example fully built per group + section grid
function ConsoleResults({ solver, sections }) {
  return (
    <div>
      {solver==='procurement'  && <ResProcure/>}
      {solver==='production'  && <ResProduce/>}
      {solver==='profitmix'   && <ResProfit/>}
      {solver==='transport'&& <ResTransport/>}
      {solver==='montecarlo'&& <ResRisk/>}
      {solver==='capital'  && <ResCapital/>}
      {solver==='sop'      && <ResSOP/>}
    </div>
  );
}

// Console procurement: run the MILP on the primary finished SKU + shared BOM,
// driven by the keystone demand series. (Console isn't item-scoped, so it shows
// the representative item's joint PO plan.)
function consoleProcurePayload(){
  const fin = M.products.filter(p=>p.cat==='Finished');
  const p = fin[0] || {}; const sku = p.sku || 'TPA-4471';
  const dem = getItemDemand(sku, 12);
  return { products:[{ name:sku, demand:dem, capacity:Math.max(400, Math.ceil(Math.max(...dem)*1.5)),
    variable_cost:p.cost||1190, sell_price:p.price||1850, yield_pct:p.yield||0.97, parts:bomParts(30) }],
    params:{ periods:12, time_grain:'monthly' } };
}
function ResProcure() {
  const proc = useSolve('/api/solve/procurement', consoleProcurePayload);
  const r = proc.result;
  const poRows = r ? [].concat(...(r.materials||[]).map((m,mi)=>(m.purchase_orders||[]).map((po,pi)=>
    [`PO-${String(mi+1).padStart(2,'0')}${pi+1}`, m.name, m.supplier_name||'—',
     po.quantity.toLocaleString('en-IN'), `P${po.period}`, `₹${(po.cost/1000).toFixed(0)}K`]))) : null;
  const pols = r ? (r.inventory_policies||[]) : null;
  return (
    <Grid cols={2}>
      <Card icon="📦" title="Procurement MILP Results" badge={r?`₹${(r.total_cost/1e7).toFixed(2)} Cr`:'₹3.12 Cr'} badgeTone="y"
        right={r ? <Provenance kind="solved" asOf={proc.ranAt}/> : <Btn kind="accent" sm onClick={()=>proc.run().catch(()=>{})}>{proc.solving?'⏳ Planning…':'📦 Run MILP'}</Btn>}
        info={{ what:'Optimal PO plan minimising inventory + ordering cost.', flows:'POs → Sourcing release plan.' }} span={2}
        dev={{ comp:'ProcurementResults', props:'solve.procurement' }}>
        {proc.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>procurement error: {proc.error}</div>}
        <DataTable dense cols={['PO','Part','Supplier','Qty','Release','Value']} align={['left','left','left','right','left','right']}
          rows={r ? (poRows.length?poRows:[['—','no orders in horizon','—','—','—','—']])
                  : M.poRegister.map(p=>[p.po, p.part, p.sup, p.qty.toLocaleString('en-IN'), p.wk, `₹${(p.val/1000).toFixed(0)}K`])}
          foot={r ? ['TOTAL','','','—','',`₹${(r.total_cost/1e5).toFixed(1)}L`] : ['TOTAL','','','—','','₹11.4L']}/>
      </Card>
      <Card icon="📋" title="Reorder Policy (s,S) / (R,Q)" badge={pols?`${pols.length} parts · solved`:'per part'} badgeTone={pols?'g':undefined} span={2}
        right={pols ? <Provenance kind="solved" asOf={proc.ranAt}/> : undefined}
        info={{ what:'Computed reorder point & order-up-to / qty.', flows:'Policy → MRP.' }}
        dev={{ comp:'ReorderPolicyCard', props:'solve.procurement.policy' }}>
        <DataTable dense cols={['Part','Policy','s (ROP)','S / Q','Review']} align={['left','left','right','right','left']}
          rows={pols ? pols.map(p=>{ const rq=/R,Q/.test(p.recommended_policy||'');
                 return [p.part, p.recommended_policy||'(s,S)',
                   Math.round((rq?p.rq_reorder_point:p.reorder_point_s)||0).toLocaleString('en-IN'),
                   Math.round((rq?p.rq_order_qty:p.order_up_to_S)||0).toLocaleString('en-IN'),
                   rq?`every ${Math.round(p.review_period_periods||0)}p`:'continuous']; })
               : [['RM-STL42','(s,S)','2,400','4,800','continuous'],['RM-BRG18','(R,Q)','—','1,500','weekly'],['CN-SEAL9','(s,S)','1,200','6,000','continuous']]}/>
      </Card>
    </Grid>
  );
}

// Transform the solver's flat gantt [{line,period,quantity,product}] into the
// per-line lane shape the chart draws; colour by the line's overall utilisation.
function GanttChart({ gantt, lines }) {
  let lanes;
  if(gantt){
    const utilOf = {}; (lines||[]).forEach(l=>{ utilOf[l.name]=(l.utilization||0)/100; });
    const byLine = {};
    gantt.forEach(g=>{ (byLine[g.line] = byLine[g.line] || []).push({ s:g.period, d:1, sku:g.product, util:utilOf[g.line]??0.7 }); });
    lanes = Object.keys(byLine).map(line=>({ line, jobs:byLine[line] }));
  } else { lanes = M.gantt; }
  const wk=18;
  return (
    <svg viewBox={`0 0 720 ${Math.max(150, 24+lanes.length*40+10)}`} style={{width:'100%', height:Math.max(150, 24+lanes.length*40+10), display:'block'}}>
      {[...Array(wk)].map((_,i)=>(<line key={i} x1={70+i*36} y1="10" x2={70+i*36} y2={24+lanes.length*40} stroke={C.line2} strokeWidth=".6"/>))}
      {lanes.map((ln,li)=>{ const y=24+li*40;
        return (<g key={li}>
          <text x="8" y={y+16} fontFamily={F.mono} fontSize="9.5" fontWeight="700" fill={C.tx}>{ln.line}</text>
          {ln.jobs.map((j,ji)=>(
            <g key={ji}>
              <rect x={70+j.s*36} y={y} width={j.d*36-3} height="26" fill={j.util>.85?C.ink:j.util>.7?C.ac:C.bg4} stroke={C.line} strokeWidth="1.5"/>
              <text x={70+j.s*36+4} y={y+16} fontFamily={F.mono} fontSize="8" fill={j.util>.85?C.ac:C.tx} fontWeight="700">{String(j.sku).slice(4)}</text>
            </g>
          ))}
        </g>);
      })}
    </svg>
  );
}

// Production MILP payload — finished goods (required_qty = total forecast demand,
// OEE, cycle) scheduled across their assigned lines.
function productionPayload(){
  const fin = M.products.filter(p=>p.cat==='Finished');
  const prods = fin.map(p=>({ name:p.sku, required_qty:getItemDemand(p.sku,12).reduce((a,b)=>a+b,0),
    oee:p.oee||0.84, cycle_time:p.cycle||4 }));
  const lineIds = [...new Set(fin.map(p=>p.line).filter(Boolean))];
  const lines = (lineIds.length?lineIds:['LINE-01']).map((id,i)=>({ id, name:`Line ${i+1}`, capacity:400 }));
  return { products:prods, lines, params:{ periods:12, hrs_per_period:160 } };
}
function ResProduce() {
  const pr = useSolve('/api/solve/production', productionPayload);
  const r = pr.result;
  return (
    <Grid cols={1}>
      <Card icon="📅" title="Production Schedule · Gantt" badge={r?`${r.lines.length} lines · ${r.periods}p · solved`:'3 lines · 18 wk'} badgeTone="y"
        right={r ? <Provenance kind="solved" asOf={pr.ranAt}/> : <Btn kind="accent" sm onClick={()=>pr.run().catch(()=>{})}>{pr.solving?'⏳ Scheduling…':'📅 Run scheduler'}</Btn>}
        info={{ what:'Sequenced jobs per line over the horizon.', flows:'Schedule → shop-floor execution.' }}
        dev={{ comp:'GanttCard', props:'solve.production.schedule' }}>
        {pr.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>production error: {pr.error}</div>}
        <GanttChart gantt={r?r.gantt:undefined} lines={r?r.lines:undefined}/>
        <div style={{marginTop:6, display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2}}>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ink}}/>util &gt;85%</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ac}}/>70–85%</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.bg4}}/>&lt;70%</span>
        </div>
      </Card>
      <Grid cols={2}>
        <Card icon="📦" title="Product Fulfillment" badge={r?'vs demand · solved':'vs demand'} badgeTone={r?'g':undefined}
          info={{ what:'Met vs unmet demand per SKU.', flows:'Gaps → lost sales.' }}
          dev={{ comp:'FulfillmentCard', props:'solve.production.fulfil' }}>
          <DataTable dense cols={['SKU','Required','Made','Fill']} align={['left','right','right','right']}
            rows={r ? r.products.map(p=>[p.name, p.required.toLocaleString('en-IN'), p.produced.toLocaleString('en-IN'),
                   `${Math.min(100, Math.round(p.produced/Math.max(p.required,1)*100))}%`])
                 : [['TPA-4471','2840','2840','100%'],['TPA-3215','4120','3980','97%'],['TPA-2188','920','840','91%']]}/>
        </Card>
        <Card icon="💤" title="Shutdown Candidates" badge={r?(r.shutdown_recommendations.length?`${r.shutdown_recommendations.length} found`:'none'):'low util'}
          info={{ what:'Lines/shifts worth idling.', flows:'Cost saving option.' }}
          dev={{ comp:'ShutdownCard', props:'solve.production.shutdown' }}>
          {r ? (
            r.shutdown_recommendations.length ? r.shutdown_recommendations.map((s,i)=>(
              <div key={i} style={{padding:'10px', border:`2px solid ${C.line}`, background:C.bg3, marginBottom:6}}>
                <div style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>{s.line||s.name||`Line ${s.line_idx}`}{s.period!=null?` · P${s.period}`:''}</div>
                <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:3}}>{s.type||'low-util'}{s.savings!=null?` · idle saves ₹${(s.savings/1e5).toFixed(1)}L`:''}</div>
              </div>
            )) : (()=>{ const low=[...r.lines].sort((a,b)=>a.utilization-b.utilization)[0];
              return <div style={{padding:'10px', border:`2px solid ${C.gn}`, background:C.bg3, fontFamily:F.mono, fontSize:11, color:C.gn}}>✓ No shutdown beats keep-running below the {r.shutdown_threshold_pct}% threshold. Lowest line: {low?low.name:'—'} at {low?low.utilization:0}% util.</div>;
            })()
          ) : (
            <div style={{padding:'10px', border:`2px solid ${C.line}`, background:C.bg3}}>
              <div style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>LINE-03 · Shift B</div>
              <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:3}}>55% util in W01–W03 · idle saves ₹2.1L</div>
            </div>
          )}
        </Card>
      </Grid>
    </Grid>
  );
}

// Build the profit-mix payload from the finished-goods master; bind shared
// capacity at ~82% of total demand-hours so the LP must ration scarce hours
// (otherwise every SKU just runs to its ceiling and there's no decision).
function profitmixPayload(){
  const fin = M.products.filter(p=>p.cat==='Finished');
  const prods = fin.map(p=>({ name:p.sku, sell_price:p.price, variable_cost:p.cost,
    max_demand:p.demand, cycle_time:p.cycle, shelf_life:p.shelf }));
  const demandHours = prods.reduce((s,p)=>s+p.max_demand*p.cycle_time, 0);
  return { products:prods, constraints:{ shared_capacity:Math.round(demandHours*0.82) } };
}
function ResProfit() {
  const pm = useSolve('/api/solve/profitmix', profitmixPayload);
  const r = pm.result;
  const fmtL = n=>`₹${(n/1e5).toFixed(1)}L`;
  return (
    <Grid cols={2}>
      <Card icon="💰" title="Profit Maximizer Results" badge={r?fmtL(r.total_profit):'₹6.84 Cr'} badgeTone="y" info={{ what:'Optimal product mix maximising contribution under a binding capacity ration.', flows:'Mix → procurement & production targets.' }} span={2}
        right={r ? <Provenance kind="solved" asOf={pm.ranAt}/> : <Btn kind="accent" sm onClick={()=>pm.run().catch(()=>{})}>{pm.solving?'⏳ Optimizing…':'💰 Optimize mix'}</Btn>}
        dev={{ comp:'ProfitResults', props:'solve.profit' }}>
        {pm.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>profit-mix error: {pm.error}</div>}
        {r ? (
          <>
            <DataTable cols={['SKU','Optimal Qty','Margin/u','Margin/hr','Profit','% of profit','Status']} align={['left','right','right','right','right','right','left']}
              rows={[...r.products].sort((a,b)=>b.margin_per_hour-a.margin_per_hour).map(p=>[
                p.name, Math.round(p.quantity).toLocaleString('en-IN'), `₹${Math.round(p.margin_per_unit)}`,
                `₹${p.margin_per_hour.toFixed(0)}`, fmtL(p.profit), `${(p.pct_of_total||0).toFixed(0)}%`,
                p.quantity>0.5 ? <Tag c="g">make</Tag> : <Tag c="r">drop</Tag>,
              ])}
              foot={['TOTAL','','','',fmtL(r.total_profit),`${r.margin_pct}% margin`,'']}/>
            {r.shadow_prices && r.shadow_prices.filter(s=>s.binding).length>0 && (
              <div style={{marginTop:10, fontFamily:F.mono, fontSize:10, color:C.tx2}}>
                Binding: {r.shadow_prices.filter(s=>s.binding).map(s=>`${s.constraint} (dual ₹${s.shadow_price.toFixed(0)}/u)`).join(' · ')} — the lowest margin/hr SKU is rationed out first.
              </div>
            )}
          </>
        ) : (
          <DataTable cols={['SKU','Optimal Qty','Price','Unit Cost','Contribution','% of profit']} align={['left','right','right','right','right','right']}
            rows={M.products.filter(p=>p.cat==='Finished').map(p=>{ const c=(p.price-p.cost)*p.demand;
              return [p.sku, p.demand.toLocaleString('en-IN'), `₹${p.price}`, `₹${p.cost}`, `₹${(c/100000).toFixed(1)}L`, `${Math.round(c/6840000*100)}%`];
            })}
            foot={['TOTAL','','','','₹68.4L','100%']}/>
        )}
      </Card>
    </Grid>
  );
}

function ResTransport() {
  const tr = useSolve('/api/solve/transport', transportPayload);
  const r = tr.result;
  const cons = r && (r.consolidation||[]).filter(c=>c.recommend_consolidate);
  return (
    <Grid cols={2}>
      <Card icon="🚛" title="Transport Results" badge={r?`₹${(r.total_cost/1e5).toFixed(1)}L · solved`:'₹24.8 L'} badgeTone={r?'g':undefined}
        right={r ? <Provenance kind="solved" asOf={tr.ranAt}/> : <Btn kind="accent" sm onClick={()=>tr.run().catch(()=>{})}>{tr.solving?'⏳ Routing…':'🚛 Optimize freight'}</Btn>}
        info={{ what:'Optimal mode/lane allocation.', flows:'Bookings → 3PL.' }}
        dev={{ comp:'TransportResults', props:'solve.transport' }}>
        {tr.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>transport error: {tr.error}</div>}
        <DataTable dense cols={['Lane','Mode','Weight','Cost']} align={['left','left','right','right']}
          rows={r ? r.shipments.map(s=>[s.name, s.recommended?s.recommended.label:'—', `${(s.weight_kg/1000).toFixed(1)} t`,
                 s.recommended?`₹${(s.recommended.total_cost/1000).toFixed(0)}K`:'—'])
               : [['CHN→BLR','FTL','42 t','₹4.8L'],['CHN→PUN','Rail','68 t','₹6.2L'],['PUN→GGN','LTL','24 t','₹8.4L'],['BLR→GGN','Air','6 t','₹5.4L']]}/>
      </Card>
      <Card icon="📦" title="Consolidation Plan" badge={r?(cons.length?`${cons.length} lanes`:'none'):'LTL→FTL'}
        right={r ? <Provenance kind="solved" asOf={tr.ranAt}/> : undefined}
        info={{ what:'Where consolidating shipments cuts cost.', flows:'Plan → carrier booking.' }}
        dev={{ comp:'ConsolidationCard', props:'solve.transport.consol' }}>
        {r ? (
          <>
            <Blk label="Consolidation saving" value={`₹ ${(r.consolidation_saving/1e5).toFixed(2)} L`} tone="y"/>
            <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2, lineHeight:1.5}}>
              {cons.length ? cons.map((c,i)=><div key={i}>{c.lane}: {c.n_shipments}×{c.individual_mode} → {c.consolidated_mode} · saves ₹{(c.saving/1000).toFixed(0)}K ({c.utilization_pct}% util)</div>)
                           : 'No lane clears a full-truckload consolidation at current volumes.'}
            </div>
          </>
        ) : (
          <>
            <Blk label="Consolidation saving" value="₹ 3.2 L/yr" tone="y"/>
            <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2, lineHeight:1.5}}>Merge 3 weekly LTL CHN→PUN into 1 FTL — 22% unit cost cut, +0.5d transit.</div>
          </>
        )}
      </Card>
    </Grid>
  );
}

// Build the Monte-Carlo payload from finished goods: spread annual demand over
// 12 monthly periods, use each SKU's MAPE as the demand CV and price/cost as the
// economics. Capacity set just above mean demand so fill-rate risk is real.
function montecarloPayload(){
  const T=12;
  const prods = M.products.filter(p=>p.cat==='Finished').map(p=>{
    const per=Math.round(p.demand/T);
    return { name:p.sku, demand:Array(T).fill(per), mape_pct:p.mape, variable_cost:p.cost,
      sell_price:p.price, capacity:Math.round(per*1.3), yield_pct:p.yield||0.96, shelf_life:T, setup_cost:5000 };
  });
  return { products:prods, params:{ periods:T, periods_per_year:12, service_level:0.95 }, n_runs:500 };
}
function McChart({ hist, mean }) {
  // real histogram (bins[21] + counts[20]) when solved, else the mock buckets
  const buckets = hist ? hist.counts.map((n,i)=>({ x:hist.bins[i], n })) : M.mcBuckets.map(b=>({x:b.x,n:b.n}));
  const mxN=Math.max(...buckets.map(x=>x.n))||1;
  const n=buckets.length, slot=440/n, w=Math.max(4,slot-3);
  const meanX = mean!=null ? mean : 518; // value at which to draw the marker / colour threshold
  const lo = buckets[0]?.x ?? 0, hi = buckets[n-1]?.x ?? 1;
  const mx = lo!==hi ? 20 + (meanX-lo)/(hi-lo)*440 : 20+n*slot/2;
  const fmt = v=> hist ? `₹${(v/1e5).toFixed(0)}L` : `mean ${v}`;
  return (
    <svg viewBox="0 0 460 160" style={{width:'100%', height:160, display:'block'}}>
      {buckets.map((x,i)=>{ const h=x.n/mxN*120, bx=20+i*slot;
        return <rect key={i} x={bx} y={140-h} width={w} height={h} fill={x.x>=meanX?C.dg:C.ink}/>;
      })}
      <line x1={mx} y1="10" x2={mx} y2="145" stroke={C.ac2} strokeWidth="2" strokeDasharray="4 2"/>
      <text x={mx+3} y="20" fontFamily={F.mono} fontSize="8.5" fill={C.tx2}>{fmt(meanX)}</text>
    </svg>
  );
}

function ResRisk() {
  const mc = useSolve('/api/solve/montecarlo', montecarloPayload);
  const r = mc.result;
  const s = M.mcStats;
  const L = n=>`₹${(n/1e5).toFixed(0)}L`;
  return (
    <Grid cols={2}>
      <Card icon="🎲" title="Monte Carlo Results" badge={r?`${r.n_runs} runs · ${r.policy_simulated}`:'1,000 runs'} badgeTone="y" info={{ what:'Total-cost distribution under uncertainty.', flows:'Risk → CVaR & hedging.' }} span={2}
        right={r ? <Provenance kind="solved" asOf={mc.ranAt}/> : <Btn kind="accent" sm onClick={()=>mc.run().catch(()=>{})}>{mc.solving?'⏳ Simulating…':'🎲 Run 500 sims'}</Btn>}
        dev={{ comp:'MonteCarloResults', props:'solve.montecarlo', note:'montecarlo.py backend.' }}>
        {mc.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>monte-carlo error: {mc.error}</div>}
        <McChart hist={r?r.histogram:undefined} mean={r?r.avg_cost:undefined}/>
        <KpiRow cols={5}>
          <Blk label="Mean" value={r?L(r.avg_cost):`₹${s.mean}L`}/>
          <Blk label="Median" value={r?L(r.p50):`₹${s.median}L`}/>
          <Blk label="P95 (VaR)" value={r?L(r.var95):`₹${s.p95}L`} accent={C.a4}/>
          <Blk label="CVaR 95%" value={r?L(r.cvar95):`₹${s.cvar95}L`} accent={C.dg}/>
          <Blk label="Fragility" value={r?(r.fragility!=null?String(r.fragility):'—'):s.fragility} tone="y"/>
        </KpiRow>
        {r && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2}}>Avg fill {r.avg_fill}% · min fill {r.min_fill}% · CVaR is the mean cost of the worst 5% of {r.n_runs} runs.</div>}
      </Card>
    </Grid>
  );
}

// Per-line CapEx proposals → capital-budget knapsack under a ₹2.5 Cr budget that
// can't fund all three, so the MILP must choose. (Mirrors Finance's PerLineCapex.)
const CAPEX_PROPOSALS = [
  { name:'Heat-Treat #2 (LINE-03)', capex:18000000, annual_cash_flow:3500000, useful_life:10, residual_value:1800000, dcap:'+38%' },
  { name:'Grinder upgrade (LINE-01)', capex:9000000, annual_cash_flow:1784000, useful_life:10, residual_value:900000, dcap:'+12%' },
  { name:'Honing cell (LINE-02)', capex:12000000, annual_cash_flow:2213000, useful_life:10, residual_value:1200000, dcap:'+9%' },
];
function capitalPayload(){
  return { investments:CAPEX_PROPOSALS.map(({dcap,...r})=>r), params:{ budget:25000000, wacc:0.1124 } };
}
function ResCapital() {
  const cap = useSolve('/api/solve/capital', capitalPayload);
  const r = cap.result;
  const dcapOf = n=>{ const p=CAPEX_PROPOSALS.find(x=>x.name===n); return p?p.dcap:'—'; };
  const all = r ? [...(r.selected||[]), ...(r.rejected||[])] : null;
  return (
    <Grid cols={2}>
      <Card icon="🏗️" title="Capital Budget Results" badge={r?`fund ${r.selected.length}/${CAPEX_PROPOSALS.length} · ₹${(r.total_capex/1e7).toFixed(2)}Cr`:'endogenous'} badgeTone="y"
        right={r ? <Provenance kind="solved" asOf={cap.ranAt}/> : <Btn kind="accent" sm onClick={()=>cap.run().catch(()=>{})}>{cap.solving?'⏳ Allocating…':'🏗️ Run capital budget'}</Btn>}
        info={{ what:'Optimal capacity investments under a binding budget.', flows:'CapEx → Finance verdict.' }} span={2}
        dev={{ comp:'CapitalResults', props:'solve.capital', note:'capital.py backend.' }}>
        {cap.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>capital error: {cap.error}</div>}
        <DataTable cols={['Investment','CapEx','ΔCapacity','NPV','IRR','Decision']} align={['left','right','right','right','right','left']}
          rows={r ? all.map(s=>[s.name, `₹${(s.capex/1e7).toFixed(2)} Cr`, dcapOf(s.name), `₹${(s.npv/1e5).toFixed(1)}L`,
                 s.irr!=null?`${s.irr}%`:'—', s.selected?<Tag c="g">FUND</Tag>:<Tag c="w">DEFER</Tag>])
               : [['Heat-Treat #2','₹1.8 Cr','+38%','₹24L','19.2%',<Tag c="g">FUND</Tag>],['Grinder upgrade','₹0.9 Cr','+12%','₹14L','16.4%',<Tag c="g">FUND</Tag>],['Honing cell','₹1.2 Cr','+9%','₹9L','13.1%',<Tag c="w">DEFER</Tag>]]}/>
        {r && <Reading formula="max Σ NPVᵢ·xᵢ  s.t.  Σ CapExᵢ·xᵢ ≤ budget,  xᵢ ∈ {0,1}"
          soWhat={`Budget ₹2.5 Cr funds ${r.selected.map(s=>s.name.split(' (')[0]).join(' + ')||'nothing'} for ₹${(r.total_npv/1e5).toFixed(1)}L NPV — the knapsack can defer a higher single-NPV item to fit two that together return more.`}/>}
      </Card>
    </Grid>
  );
}

function ResSOP() {
  return (
    <Grid cols={3}>
      <Card icon="🔁" title="Closed-loop S&OP" badge="reconciled" badgeTone="y" info={{ what:'Demand/supply/finance reconciled to one plan.', flows:'Loop back into Profit mix.' }} span={2}
        dev={{ comp:'ClosedLoopSOP', props:'solve.sop' }}>
        <KpiRow cols={4}>
          <Blk label="Vol Gap" value={`+${M.sop.volumeGap}%`} accent={C.gn}/>
          <Blk label="Rev Gap" value={`${M.sop.revGap}%`} accent={C.dg}/>
          <Blk label="Margin Gap" value={`+${M.sop.marginGap}%`} accent={C.gn}/>
          <Blk label="Inv Gap" value={`${M.sop.inventoryGap}%`} accent={C.dg}/>
        </KpiRow>
      </Card>
      <Card icon="🔗" title="Pipeline (3 steps)" badge="profit→procure→produce" info={{ what:'End-to-end chained solve.', flows:'Each step seeds the next.' }}
        dev={{ comp:'PipelineCard', props:'solve.pipeline' }}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {[['Profit Mix','₹6.84 Cr',C.gn],['Procurement','₹3.12 Cr',C.ac],['Production','₹42 L',C.tx3]].map((s,i)=>(
            <div key={i} style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${C.line}`, padding:'6px 9px'}}>
              <span style={{width:9, height:9, background:s[2], border:`1.5px solid ${C.line}`}}/>
              <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, flex:1}}>{s[0]}</span>
              <span className="num" style={{fontFamily:F.mono, fontSize:11, fontWeight:700}}>{s[1]}</span>
            </div>
          ))}
        </div>
      </Card>
    </Grid>
  );
}
window.StageConsole = StageConsole;
