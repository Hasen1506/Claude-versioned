// ════════════════════════════════════════════════════════════════════════
// home.jsx — Home (landing, stage 00). Drill-down KPI tiles (handoff v2 §1.5),
// the ONE shared <SolverNetwork/> graph (§1.3, identical to Console), readiness
// grid, and a control-tower SUMMARY that reads the same alerts[] as Scenarios.
// ════════════════════════════════════════════════════════════════════════
// drill breakdowns: company → family → SKU → location → period
const KPI_DRILL = {
  margin:{ unit:'%', rows:[['Bearings','24.1%'],['Rings','37.6%'],['Valvetrain','36.3%'],['Rods','32.6%'],['Pumps','32.1%']] },
  fillRate:{ unit:'', rows:[['A items','99.2%'],['B items','94.1%'],['C items','86.4%'],['DC-BLR','97.0%'],['DC-PUN','92.5%']] },
  otif:{ unit:'', rows:[['SUP-001','96.2%'],['SUP-007','94.8%'],['SUP-018','89.1%'],['SUP-024','82.4%']] },
  inventoryDoh:{ unit:'d', rows:[['Raw mat','34 d'],['WIP','9 d'],['FG · WH','21 d'],['FG · DC','28 d']] },
};
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
  const k = M.kpis;
  const [drill, setDrill] = useState(null);
  return (
    <div>
      <StageHeader n="00" title="Command Center" kicker="Drill-down KPIs · one solver network · control-tower summary — the operational home"
        right={<div style={{display:'flex', gap:8}}><Btn kind="accent" onClick={()=>onNav('console')}>⚡ Open Console</Btn><Btn kind="secondary">Export brief</Btn></div>}/>

      {/* drill-down KPI strip — every tile is a button (handoff v2 §1.5) */}
      <div style={{padding:14, borderBottom:`2px solid ${C.line}`}}>
        <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:8}}>
          <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.1em', color:C.tx3}}>CONSOLIDATED KPIs · CLICK A TILE TO DRILL</span>
        </div>
        <KpiRow cols={8}>
          <Blk label="Revenue" value={k.revenue} sub="FY 26-27" tone="k"/>
          <Blk label="Total Cost" value={k.totalCost} sub="planned"/>
          <Blk label="Savings" value={k.savings} sub="vs baseline" tone="y"/>
          <Blk label="Margin ▸" value={k.margin} accent={C.gn} onClick={()=>setDrill('margin')}/>
          <Blk label="Fill Rate ▸" value={k.fillRate} accent={C.gn} onClick={()=>setDrill('fillRate')}/>
          <Blk label="OTIF ▸" value={k.otif} accent={C.a2} onClick={()=>setDrill('otif')}/>
          <Blk label="Inv DOH ▸" value={k.inventoryDoh} sub="days" onClick={()=>setDrill('inventoryDoh')}/>
          <Blk label="Cash Cycle" value={k.cashCycle} sub="CCC"/>
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
        <Card icon="✅" title="Solver Input Readiness" badge={`${M.readiness.filter(r=>r.ready).length}/${M.readiness.length} ready`}
          info={{ what:'Pre-flight gate: a missing input BLOCKS its solver and names what to enter + where.', flows:'Gates the Console run button per mode.' }}
          dev={{ comp:'ReadinessGrid', props:'state', note:'Not a passive checkmark — a not-ready row disables its solve and deep-links to the fix.' }}>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {M.readiness.map((r,i)=>(
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
          <div style={{marginTop:10}}>
            <SubLabel>Pipeline · one end-to-end solve</SubLabel>
            <div style={{display:'flex', flexDirection:'column', gap:0, border:`2px solid ${C.line}`}}>
              {M.pipeline.map((p,i)=>{
                const sc = p.status==='done'?C.gn:p.status==='running'?C.ac:C.tx3;
                return (
                  <div key={p.id} onClick={()=>onNav(p.go)} style={{display:'flex', alignItems:'center', gap:10, padding:'7px 10px', borderTop:i?`1px solid ${C.line2}`:'none', cursor:'pointer', background: p.status==='running'?C.bg3:C.paper}}>
                    <span style={{fontFamily:F.mono, fontSize:10, color:C.tx3, width:16}}>{i+1}</span>
                    <span style={{width:10, height:10, background:sc, borderRadius:p.status==='running'?'50%':0, border:`1.5px solid ${C.line}`}}/>
                    <span style={{fontFamily:F.disp, fontSize:12, fontWeight:800, flex:1}}>{p.stage}</span>
                    <span className="num" style={{fontFamily:F.mono, fontSize:11, fontWeight:600}}>{p.val}</span>
                    <Tag c={p.status==='done'?'g':p.status==='running'?'y':'w'}>{p.status}</Tag>
                  </div>
                );
              })}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
window.StageHome = StageHome;
