// ════════════════════════════════════════════════════════════════════════
// logistics.jsx — Logistics (stage 08, handoff v2 §3.08). This is transport
// OPTIMIZATION OUTPUT, not master data (nodes/lanes/contracts live in Network
// 03). 0 sub-tabs. Each result is a network-flow visual — distinct from the
// Monte-Carlo histogram on Scenarios.
// ════════════════════════════════════════════════════════════════════════
function StageLogistics({ onNav }) {
  const { gate } = useProfile();
  return (
    <div>
      <StageHeader n="08" title="Logistics · Transport Optimization" kicker="Allocation (DC→customer LP) · consolidation (LTL→FTL) · center-of-gravity — all network-flow visuals"
        right={<Btn kind="accent" onClick={()=>onNav('console')}>⚡ Solve Transport</Btn>}/>
      <div style={{padding:18}}>
        {gate.transport && <GateNote onNav={onNav}>Your profile is <b>single-site distribution</b> — there is nothing to ship between locations, so the transport solver is off. Switch to a network in Setup to enable it.</GateNote>}
        <PrereqNote onNav={onNav} go="network" goLabel="open Network →">Nodes, lanes and contracts are master data — defined once in <b>Network (03)</b>. This stage only shows the transport solver's output.</PrereqNote>
        <StageSection step="1" title="Allocation" sub="DC → customer assignment as a weighted flow map (LP)"><LogAllocation/></StageSection>
        <StageSection step="2" title="Consolidation" sub="where merging LTL into FTL cuts cost"><LogConsolidation/></StageSection>
        <StageSection step="3" title="Center of Gravity" sub="weighted-distance optimal hub — config and result as one"><LogCoG/></StageSection>
      </div>
    </div>
  );
}

// crude India map with plotted nodes (lowercase node types)
function IndiaMap({ marks, cog, flows }) {
  const px=(lng)=> (lng-68)/(92-68)*340+20;
  const py=(lat)=> (30-lat)/(30-8)*300+14;
  return (
    <svg viewBox="0 0 380 330" style={{width:'100%', maxWidth:380, height:330, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
      <path d="M120 20 L180 30 L230 25 L250 70 L280 120 L250 180 L210 250 L180 300 L150 260 L120 200 L90 150 L80 90 L100 50 Z"
        fill={C.bg3} stroke={C.line2} strokeWidth="1.5"/>
      {/* weighted outbound flows */}
      {flows && flows.map((f,i)=>{ const a=marks.find(m=>m.id===f.from), b=marks.find(m=>m.id===f.to); if(!a||!b) return null;
        return <line key={i} x1={px(a.lng)} y1={py(a.lat)} x2={px(b.lng)} y2={py(b.lat)} stroke={C.ink} strokeWidth={1+f.w*4} opacity=".5"/>;
      })}
      {marks.map((m,i)=>{
        const x=px(m.lng), y=py(m.lat);
        const col=m.type==='plant'?C.dg:m.type==='customer'?C.a2:m.type==='supplier'?C.tx3:C.ink;
        return (<g key={i}>
          <circle cx={x} cy={y} r={m.type==='plant'?6:4} fill={col} stroke={C.paper} strokeWidth="1.5"/>
          <text x={x+8} y={y+3} fontFamily={F.mono} fontSize="8.5" fill={C.tx} fontWeight="700">{m.id}</text>
        </g>);
      })}
      {cog && (()=>{ const x=px(cog.lng), y=py(cog.lat);
        return <g><circle cx={x} cy={y} r="9" fill="none" stroke={C.ac2} strokeWidth="2.5"/><line x1={x-13} y1={y} x2={x+13} y2={y} stroke={C.ac2} strokeWidth="2"/><line x1={x} y1={y-13} x2={x} y2={y+13} stroke={C.ac2} strokeWidth="2"/></g>;
      })()}
    </svg>
  );
}

function LogAllocation() {
  const lanes=['CHN→BLR','CHN→PUN','PUN→GGN','BLR→GGN'];
  const modes=['FTL','LTL','Rail','Air'];
  const alloc=[[100,0,0,0],[0,0,100,0],[0,60,0,40],[0,0,0,100]];
  const flows=[{from:'WH-CHN',to:'DC-BLR',w:.8},{from:'WH-CHN',to:'DC-PUN',w:1},{from:'DC-PUN',to:'CUST-GGN',w:.6},{from:'DC-BLR',to:'CUST-GGN',w:.3}];
  return (
    <Grid cols={2}>
      <Card icon="🗺️" title="Allocation Flow Map" badge="weighted lanes" badgeTone="y" info={{ what:'DC→customer assignment drawn as a network flow (line weight = volume).', flows:'Allocation → carrier booking.' }}
        dev={{ comp:'AllocationFlowCard', props:'solve.transport.allocation', note:'Network-flow visual — distinct from MC histogram.' }}>
        <IndiaMap marks={M.nodes.filter(n=>n.type!=='supplier')} flows={flows}/>
        <div style={{marginTop:6, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Line weight = shipped volume · deterministic LP, not a simulation.</div>
      </Card>
      <Card icon="🚛" title="Allocation Matrix" badge="lane × mode" info={{ what:'How shipments split across modes per lane.', flows:'From transport MILP.' }}
        dev={{ comp:'TransportAllocationCard', props:'solve.transport.allocation' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
            <thead><tr style={{background:C.ink}}>
              <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9}}>LANE ↓ / MODE →</th>
              {modes.map(m=><th key={m} style={{color:C.paper, textAlign:'center', padding:'6px 9px', fontSize:9}}>{m}</th>)}
            </tr></thead>
            <tbody>
              {alloc.map((row,ri)=>(
                <tr key={ri} style={{borderTop:`1px solid ${C.line2}`}}>
                  <td style={{padding:'6px 9px', fontWeight:700, background:C.bg3}}>{lanes[ri]}</td>
                  {row.map((v,ci)=>(
                    <td key={ci} className="num" style={{textAlign:'center', padding:'6px 9px', background: v===0?C.paper: v===100?C.ink:C.ac, color: v===100?C.ac: v===0?C.tx3:C.onAc, fontWeight:700}}>{v?`${v}%`:'·'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{marginTop:10}}>
          <KpiRow cols={3}>
            <Blk label="Total Freight" value="₹ 24.8 L" sub="planned"/>
            <Blk label="Avg Cost/Order" value="₹ 1,420" tone="c"/>
            <Blk label="On-time SLA" value="96.4%" accent={C.gn}/>
          </KpiRow>
        </div>
        <Reading formula="min Σ (lane cost × volume)  s.t. demand met, capacity, SLA" soWhat="Rail wins CHN→PUN on cost; Air only survives on BLR→GGN where the SLA forces speed."/>
      </Card>
    </Grid>
  );
}

function LogConsolidation() {
  return (
    <Card icon="📦" title="Consolidation Plan" badge="LTL→FTL" badgeTone="y" info={{ what:'Where merging shipments cuts unit cost.', flows:'Plan → carrier booking.' }}
      dev={{ comp:'ConsolidationCard', props:'solve.transport.consol' }}>
      <Grid cols={3}>
        <Blk label="Consolidation saving" value="₹ 3.2 L/yr" tone="y"/>
        <Blk label="Unit cost cut" value="−22%" accent={C.gn}/>
        <Blk label="Transit penalty" value="+0.5 d" accent={C.a4}/>
      </Grid>
      <div style={{marginTop:10, display:'flex', alignItems:'center', gap:10}}>
        <div style={{display:'flex', alignItems:'center', gap:4}}>
          {[1,2,3].map(i=><span key={i} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line2}`, background:C.bg3}}>LTL</span>)}
        </div>
        <span style={{color:C.tx3, fontSize:16}}>→</span>
        <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'4px 9px', border:`2px solid ${C.line}`, background:C.ac, color:C.onAc}}>1 × FTL</span>
        <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>Merge 3 weekly LTL CHN→PUN into one FTL.</span>
      </div>
      <Reading formula="consolidate when FTL_cost < Σ LTL_cost AND transit penalty ≤ SLA slack"
        soWhat="The three CHN→PUN LTLs share a destination and have 0.5d of SLA slack — collapse them."/>
    </Card>
  );
}

function LogCoG() {
  return (
    <Grid cols={2}>
      <Card icon="📍" title="Center of Gravity" badge="optimal hub" badgeTone="y" info={{ what:'Weighted-distance optimal facility location.', flows:'Hub candidate → network design.' }}
        dev={{ comp:'CenterOfGravityCard', props:'nodes, demandWeights', note:'Config + result as one.' }}>
        <IndiaMap marks={M.nodes.filter(n=>n.type!=='supplier')} cog={M.cog}/>
      </Card>
      <Card icon="🎯" title="CoG Result" badge="vs current" info={{ what:'Recommended hub coordinates and savings.', flows:'Decision input for new DC.' }}
        dev={{ comp:'CoGResult', props:'cog (computed)' }}>
        <Blk label="Optimal Location" value={M.cog.label} tone="y"/>
        <div style={{marginTop:8}}><KpiRow cols={2}>
          <Blk label="Latitude" value={`${M.cog.lat}°N`}/>
          <Blk label="Longitude" value={`${M.cog.lng}°E`}/>
        </KpiRow></div>
        <div style={{marginTop:10, padding:'10px 11px', background:C.gn, color:'#fff', fontFamily:F.disp, fontWeight:800, fontSize:14}}>{M.cog.saving}</div>
        <Reading formula="x* = Σ(wᵢxᵢ)/Σwᵢ ,  y* = Σ(wᵢyᵢ)/Σwᵢ   (wᵢ = demand)"
          soWhat="A Kurnool hub cuts average outbound km ~18% and relieves the DC-BLR cube pressure flagged on Network."/>
      </Card>
    </Grid>
  );
}
window.StageLogistics = StageLogistics;
