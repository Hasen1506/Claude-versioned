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

function StageHome({ onNav }) {
  const [drill, setDrill] = useState(null);
  // DERIVED consolidated KPIs (price/cost/demand). Solve-dependent metrics
  // (savings, fill, OTIF, DOH, CCC) are shown as “—” until a real run/actuals
  // exist — never fabricated. (AUDIT A3.)
  const fin = M.products.filter(p=>p.cat==='Finished');
  const revenue = fin.reduce((s,p)=>s+p.price*p.demand,0);
  const cogs = fin.reduce((s,p)=>s+p.cost*p.demand,0);
  const margin = revenue ? (revenue-cogs)/revenue : 0;
  const cr = (n)=> '₹ '+(n/1e7).toFixed(2)+' Cr';
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
  return (
    <div>
      <StageHeader n="00" title="Command Center" kicker="Drill-down KPIs · one solver network · control-tower summary — the operational home"
        right={<div style={{display:'flex', gap:8}}><Btn kind="accent" onClick={()=>onNav('console')}>⚡ Open Console</Btn><Btn kind="secondary">Export brief</Btn></div>}/>

      {/* drill-down KPI strip — derived; solve-dependent tiles read “—” until run */}
      <div style={{padding:14, borderBottom:`2px solid ${C.line}`}}>
        <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:8}}>
          <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.1em', color:C.tx3}}>DERIVED KPIs · SOLVE-DEPENDENT TILES READ “—” UNTIL A RUN</span>
        </div>
        <KpiRow cols={8}>
          <Blk label="Revenue" value={cr(revenue)} sub="price × demand" tone="k"/>
          <Blk label="COGS" value={cr(cogs)} sub="cost × demand"/>
          <Blk label="Margin ▸" value={(margin*100).toFixed(1)+'%'} accent={C.gn} onClick={()=>setDrill('margin')}/>
          <Blk label="SKUs" value={String(fin.length)} sub="finished"/>
          <Blk label="Lines" value={String(M.lines.length)} sub="production"/>
          <Blk label="Fill Rate" value="—" sub="needs solve"/>
          <Blk label="OTIF" value="—" sub="needs actuals"/>
          <Blk label="Inv DOH" value="—" sub="needs inventory"/>
        </KpiRow>
        {drill && <KpiDrill kpi={drill} onClose={()=>setDrill(null)}/>}
      </div>

      {/* ONE solver network — same component as Console */}
      <div style={{padding:14, borderBottom:`2px solid ${C.line}`}}>
        <Card icon="🎯" title="Solver Network" badge={M.solverLabel} badgeTone="y"
          info={{ what:'All engines grouped in 5 families with their real data hand-offs.', flows:'Click a node → open that solver. Identical graph on Console.' }}
          dev={{ comp:'SolverNetwork', props:'solvers, edges, onNav', note:'ONE shared component (Home + Console).' }}>
          <div style={{overflowX:'auto'}}><SolverNetwork onNav={onNav}/></div>
          <div style={{display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2, flexWrap:'wrap', marginTop:8}}>
            <span style={{display:'flex', alignItems:'center', gap:5}}><span style={{width:9, height:9, background:C.gn}}/>solved</span>
            <span style={{display:'flex', alignItems:'center', gap:5}}><span style={{width:9, height:9, background:C.ac}}/>running</span>
            <span style={{display:'flex', alignItems:'center', gap:5}}><span style={{width:9, height:9, background:C.tx3}}/>queued / idle</span>
            <span style={{display:'flex', alignItems:'center', gap:5}}><span style={{width:14, height:2, background:C.a3}}/>feedback (reconcile ⇄ profit)</span>
            <span style={{marginLeft:'auto'}}>click a node → jump to solver</span>
          </div>
        </Card>
      </div>

      <div style={{padding:14, display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
        {/* readiness grid */}
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

        {/* control tower SUMMARY — same alerts[] as Scenarios (handoff v2 §1 / Part 5.5) */}
        <Card icon="🚨" title="Control Tower" badge={`top 3 of ${M.controlTower.length}`} badgeTone="k"
          info={{ what:'Top exceptions; the full list lives in Scenarios (one source).', flows:'Drill into the owning stage.' }}
          right={<button onClick={()=>onNav('scenarios')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>full list in Scenarios →</button>}
          dev={{ comp:'ControlTowerSummary', props:'alerts (shared)' }}>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {M.controlTower.slice(0,3).map((a,i)=>{
              const sc = a.sev==='H'?C.dg:a.sev==='M'?C.a4:C.tx3;
              return (
                <div key={i} style={{display:'flex', alignItems:'center', gap:10, border:`2px solid ${C.line}`, padding:'7px 9px', background:C.paper}}>
                  <span style={{width:22, height:22, flexShrink:0, display:'grid', placeItems:'center', background:sc, color:'#fff', fontFamily:F.disp, fontWeight:900, fontSize:11}}>{a.sev}</span>
                  <div style={{flex:1, minWidth:0}}>
                    <div style={{fontFamily:F.body, fontSize:12, fontWeight:600}}>{a.msg}</div>
                    <div style={{fontFamily:F.mono, fontSize:9, color:C.tx3, marginTop:1}}>{a.area} · {a.t}</div>
                  </div>
                  <Tag c="w">{a.kpi}</Tag>
                </div>
              );
            })}
          </div>
          <div style={{marginTop:8, fontFamily:F.mono, fontSize:8.5, color:C.tx3, letterSpacing:'.04em', lineHeight:1.5}}>
            ▸ the end-to-end solve pipeline lives in the ribbon at the top of every screen — not repeated here.
          </div>
        </Card>
      </div>
    </div>
  );
}
window.StageHome = StageHome;
