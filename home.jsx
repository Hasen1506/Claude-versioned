// ════════════════════════════════════════════════════════════════════════
// home.jsx — Command Center (landing). Pipeline · solver-comms graph ·
// readiness grid · control tower · KPI dashboard.  [CommandCenterTab]
// ════════════════════════════════════════════════════════════════════════
function SolverCommsGraph({ onNav }) {
  // hand-placed flow diagram of the 7 solvers + their data hand-offs
  const W=760, H=300;
  const N = {
    demand:   { x:70,  y:60,  l:'DEMAND',    s:'17 models',  t:'done' },
    sop:      { x:70,  y:210, l:'S&OP',       s:'aggregate',  t:'done' },
    profit:   { x:250, y:135, l:'PROFIT MIX', s:'LP',         t:'done' },
    procure:  { x:430, y:60,  l:'PROCURE',    s:'MILP',       t:'run' },
    produce:  { x:430, y:210, l:'PRODUCE',    s:'MILP',       t:'queue' },
    transport:{ x:610, y:135, l:'TRANSPORT',  s:'MILP',       t:'queue' },
    capital:  { x:430, y:330, l:'CAPITAL',    s:'MILP',       t:'idle' },
  };
  const E = [
    ['demand','profit'],['sop','profit'],['demand','sop'],
    ['profit','procure'],['profit','produce'],
    ['procure','produce'],['produce','transport'],['procure','transport'],
    ['profit','capital'],['produce','capital'],
  ];
  const col = { done:C.gn, run:C.ac, queue:C.tx3, idle:C.tx3 };
  const node = (k)=>{ const n=N[k]; return {cx:n.x+58, cy:n.y+20}; };
  return (
    <svg viewBox={`0 0 ${W} ${H+80}`} style={{width:'100%', height:'100%', display:'block'}}>
      <defs>
        <marker id="ah" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0 0 L6 3 L0 6 Z" fill={C.tx2}/>
        </marker>
      </defs>
      {E.map(([a,b],i)=>{ const p=node(a), q=node(b);
        return <line key={i} x1={p.cx} y1={p.cy} x2={q.cx} y2={q.cy} stroke={C.tx2} strokeWidth="1.4" markerEnd="url(#ah)" opacity=".55"/>;
      })}
      {Object.keys(N).map(k=>{ const n=N[k];
        return (
          <g key={k} style={{cursor:'pointer'}} onClick={()=>onNav(k==='capital'||k==='profit'||k==='procure'||k==='produce'||k==='transport'?'console':k==='sop'?'plan':'demand')}>
            <rect x={n.x} y={n.y} width="116" height="40" fill="var(--paper)" stroke="var(--br)" strokeWidth="2"/>
            <rect x={n.x} y={n.y} width="5" height="40" fill={col[n.t]}/>
            <text x={n.x+14} y={n.y+18} fontFamily="var(--disp)" fontWeight="800" fontSize="11" fill="var(--tx)">{n.l}</text>
            <text x={n.x+14} y={n.y+31} fontFamily="var(--mono)" fontSize="8.5" fill="var(--tx3)">{n.s}</text>
          </g>
        );
      })}
    </svg>
  );
}

function StageHome({ onNav }) {
  const k = M.kpis;
  return (
    <div>
      <StageHeader n="00" title="Command Center" kicker="Solver-input readiness · pipeline status · control tower — the operational home"
        right={<div style={{display:'flex', gap:8}}><Btn kind="accent" onClick={()=>onNav('console')}>⚡ Open Console</Btn><Btn kind="secondary">Export brief</Btn></div>}/>

      {/* KPI strip */}
      <div style={{padding:14, borderBottom:`2px solid ${C.line}`}}>
        <KpiRow cols={8}>
          <Blk label="Revenue" value={k.revenue} sub="FY 26-27" tone="k"/>
          <Blk label="Total Cost" value={k.totalCost} sub="planned"/>
          <Blk label="Savings" value={k.savings} sub="vs baseline" tone="y"/>
          <Blk label="Margin" value={k.margin} accent={C.gn}/>
          <Blk label="Fill Rate" value={k.fillRate} accent={C.gn}/>
          <Blk label="OTIF" value={k.otif} accent={C.a2}/>
          <Blk label="Inv DOH" value={k.inventoryDoh} sub="days"/>
          <Blk label="Cash Cycle" value={k.cashCycle} sub="CCC"/>
        </KpiRow>
      </div>

      <div style={{padding:14, display:'grid', gridTemplateColumns:'1.55fr 1fr', gap:14}}>
        {/* solver comms graph */}
        <Card icon="🎯" title="How the 7 Solvers Communicate" badge="LIVE" badgeTone="y"
          info={{ what:'Directed data-flow between solvers: each writes state the next reads.', flows:'Demand→S&OP→Profit→Procure→Produce→Transport; Capital consumes duals.' }}
          dev={{ comp:'CommandCenterTab', props:'state, dispatch', note:'Non-card rich UI — first-class screen.' }}
          style={{minHeight:380}}>
          <div style={{height:340}}><SolverCommsGraph onNav={onNav}/></div>
          <div style={{display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2, flexWrap:'wrap'}}>
            <span style={{display:'flex', alignItems:'center', gap:5}}><span style={{width:9, height:9, background:C.gn}}/>solved</span>
            <span style={{display:'flex', alignItems:'center', gap:5}}><span style={{width:9, height:9, background:C.ac}}/>running</span>
            <span style={{display:'flex', alignItems:'center', gap:5}}><span style={{width:9, height:9, background:C.tx3}}/>queued / idle</span>
            <span style={{marginLeft:'auto'}}>click a node → jump to solver</span>
          </div>
        </Card>

        {/* readiness grid */}
        <Card icon="✅" title="Solver Input Readiness" badge={`${M.readiness.filter(r=>r.ready).length}/${M.readiness.length}`}
          info={{ what:'Pre-flight check: are all inputs each solver needs present & valid?', flows:'Gates the Console run button per mode.' }}
          dev={{ comp:'ReadinessGrid', props:'state', state:'state.* completeness' }}>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {M.readiness.map((r,i)=>(
              <div key={i} style={{border:`2px solid ${C.line}`, background: r.ready?C.paper:C.bg3, padding:'7px 9px', display:'flex', alignItems:'center', gap:9}}>
                <span style={{width:16, height:16, flexShrink:0, display:'grid', placeItems:'center', background:r.ready?C.gn:C.dg, color:'#fff', fontFamily:F.disp, fontWeight:900, fontSize:11}}>{r.ready?'✓':'!'}</span>
                <div style={{minWidth:0, flex:1}}>
                  <div style={{fontFamily:F.disp, fontSize:12, fontWeight:800}}>{r.solver}</div>
                  <div style={{display:'flex', gap:4, marginTop:3, flexWrap:'wrap'}}>
                    {r.inputs.map((inp,j)=><Tag key={j} c={r.ready?'w':'r'}>{inp}</Tag>)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div style={{padding:'0 14px 14px', display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
        {/* control tower */}
        <Card icon="🚨" title="Control Tower" badge={`${M.controlTower.length} alerts`} badgeTone="k"
          info={{ what:'Exception monitor across supply, demand, capacity, finance.', flows:'Drill into the owning stage.' }}
          dev={{ comp:'ControlTowerCard', props:'alerts, dispatch' }}>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {M.controlTower.map((a,i)=>{
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
        </Card>

        {/* pipeline detail + KPI dashboard */}
        <Card icon="🔗" title="Pipeline Status" badge="3/6 done" badgeTone="y"
          info={{ what:'Stage-by-stage completion of the solver spine.', flows:'Each links to its solver in Console.' }}
          dev={{ comp:'PipelineRibbon', props:'pipeline, onNav' }}>
          <div style={{display:'flex', flexDirection:'column', gap:0, border:`2px solid ${C.line}`}}>
            {M.pipeline.map((p,i)=>{
              const sc = p.status==='done'?C.gn:p.status==='running'?C.ac:C.tx3;
              return (
                <div key={p.id} onClick={()=>onNav(p.go)} style={{display:'flex', alignItems:'center', gap:10, padding:'8px 10px', borderTop:i?`1px solid ${C.line2}`:'none', cursor:'pointer', background: p.status==='running'?C.bg3:C.paper}}>
                  <span style={{fontFamily:F.mono, fontSize:10, color:C.tx3, width:16}}>{i+1}</span>
                  <span style={{width:10, height:10, background:sc, borderRadius:p.status==='running'?'50%':0, border:`1.5px solid ${C.line}`}}/>
                  <span style={{fontFamily:F.disp, fontSize:12, fontWeight:800, flex:1}}>{p.stage}</span>
                  <span className="num" style={{fontFamily:F.mono, fontSize:11, fontWeight:600}}>{p.val}</span>
                  <Tag c={p.status==='done'?'g':p.status==='running'?'y':'w'}>{p.status}</Tag>
                </div>
              );
            })}
          </div>
          <div style={{marginTop:10}}>
            <SubLabel>Plan health</SubLabel>
            <KpiRow cols={3}>
              <Blk label="S&OP Gap · Vol" value={`+${M.sop.volumeGap}%`} accent={C.gn}/>
              <Blk label="Margin Gap" value={`+${M.sop.marginGap}%`} accent={C.gn}/>
              <Blk label="Inv Gap" value={`${M.sop.inventoryGap}%`} accent={C.dg}/>
            </KpiRow>
          </div>
        </Card>
      </div>
    </div>
  );
}
window.StageHome = StageHome;
