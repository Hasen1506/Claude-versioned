// ════════════════════════════════════════════════════════════════════════
// logistics.jsx — Logistics (stage 08, handoff v2 §3.08). This is transport
// OPTIMIZATION OUTPUT, not master data (nodes/lanes/contracts live in Network
// 03). 0 sub-tabs. Each result is a network-flow visual — distinct from the
// Monte-Carlo histogram on Scenarios.
// ════════════════════════════════════════════════════════════════════════
function StageLogistics({ onNav }) {
  const { gate } = useProfile();
  const tr = useSolve('/api/solve/transport', transportPayload);
  return (
    <div>
      <StageHeader n="08" title="Logistics · Transport Optimization" kicker="Allocation (DC→customer LP) · consolidation (LTL→FTL) · center-of-gravity — all network-flow visuals"
        right={<Btn kind="accent" onClick={()=>tr.run().catch(()=>{})}>{tr.solving?'⏳ Routing…':'⚡ Solve Transport'}</Btn>}/>
      <div style={{padding:18}}>
        {gate.transport && <GateNote onNav={onNav}>Your profile is <b>single-site distribution</b> — there is nothing to ship between locations, so the transport solver is off. Switch to a network in Setup to enable it.</GateNote>}
        <PrereqNote onNav={onNav} go="network" goLabel="open Network →">Nodes, lanes and contracts are master data — defined once in <b>Network (03)</b>. This stage only shows the transport solver's output.</PrereqNote>
        {tr.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Transport solver: {tr.error}</div>}
        <StageSection step="1" title="Allocation" sub="DC → customer assignment as a weighted flow map (LP)"><LogAllocation tr={tr}/></StageSection>
        <StageSection step="2" title="Consolidation" sub="where merging LTL into FTL cuts cost"><LogConsolidation tr={tr}/></StageSection>
        <StageSection step="3" title="Center of Gravity" sub="weighted-distance optimal hub — config and result as one"><LogCoG/></StageSection>
      </div>
    </div>
  );
}

// India map — projected lat/long, silhouette drawn in the SAME projection so
// nodes land correctly, with marker + label de-overlap so nothing stacks.
function IndiaMap({ marks, cog, flows }) {
  const W=480, H=440;
  const px = lng => (lng-66.5)/(98-66.5)*(W-150)+80;
  const py = lat => (37.5-lat)/(37.5-6)*(H-90)+40;
  // outline as real coordinates → projected, so it aligns with the nodes
  const OUTLINE=[[34.5,76],[32,78.5],[30,81],[27.3,88.2],[26,89.8],[24,91.8],[25.3,94.3],[22,91],
    [21.4,87.8],[19.2,85],[15.8,81.2],[13,80.3],[10,79.9],[8,77.5],[9.3,76.3],[13,74.6],[16,73.4],
    [19,72.8],[21,72.6],[22.6,69],[23.7,68],[24.7,71],[27,70.2],[30,73],[32.6,74.6],[34.5,76]];
  const outline = OUTLINE.map(([la,ln],i)=>(i?'L':'M')+px(ln).toFixed(0)+' '+py(la).toFixed(0)).join(' ')+' Z';
  // project nodes, then spread any markers closer than 18px
  const pts = marks.map(m=>({ id:m.id, type:m.type, x:px(m.lng), y:py(m.lat) }));
  for(let a=0;a<pts.length;a++) for(let b=a+1;b<pts.length;b++){
    const dx=pts[b].x-pts[a].x, dy=pts[b].y-pts[a].y, d=Math.hypot(dx,dy)||0.01;
    if(d<18){ const k=(18-d)/2, ux=dx/d, uy=dy/d; pts[a].x-=ux*k; pts[a].y-=uy*k; pts[b].x+=ux*k; pts[b].y+=uy*k; }
  }
  const byId = Object.fromEntries(pts.map(p=>[p.id,p]));
  // de-overlap labels vertically; flip side on the eastern half
  const sorted=[...pts].sort((a,b)=>a.y-b.y); let last=-100;
  sorted.forEach(p=>{ let ly=p.y+3; if(ly-last<15) ly=last+15; p.ly=ly; last=ly; p.left = p.x > W*0.58; });
  const colOf=t=> t==='plant'?C.dg:t==='customer'?C.a2:t==='supplier'?C.tx3:C.ink;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', maxWidth:W, height:'auto', display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
      <path d={outline} fill={C.bg3} stroke={C.line2} strokeWidth="1.5"/>
      {flows && flows.map((f,i)=>{ const a=byId[f.from], b=byId[f.to]; if(!a||!b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={C.ink} strokeWidth={1+f.w*4} opacity=".4" strokeLinecap="round"/>;
      })}
      {pts.map((p,i)=>{ const lx = p.left ? p.x-12 : p.x+12;
        return (
          <g key={i}>
            <line x1={p.x} y1={p.y} x2={lx} y2={p.ly-3} stroke={C.line2} strokeWidth="1"/>
            <circle cx={p.x} cy={p.y} r={p.type==='plant'?6:4.5} fill={colOf(p.type)} stroke={C.paper} strokeWidth="1.6"/>
            <text x={lx} y={p.ly} textAnchor={p.left?'end':'start'} fontFamily={F.mono} fontSize="9" fontWeight="700"
              fill={C.tx} style={{paintOrder:'stroke'}} stroke={C.paper} strokeWidth="3" strokeLinejoin="round">{p.id}</text>
          </g>
        );
      })}
      {cog && (()=>{ const x=px(cog.lng), y=py(cog.lat);
        return <g>
          <circle cx={x} cy={y} r="10" fill="none" stroke={C.ac2} strokeWidth="2.5"/>
          <line x1={x-14} y1={y} x2={x+14} y2={y} stroke={C.ac2} strokeWidth="2"/>
          <line x1={x} y1={y-14} x2={x} y2={y+14} stroke={C.ac2} strokeWidth="2"/>
          <text x={x} y={y-18} textAnchor="middle" fontFamily={F.mono} fontSize="9" fontWeight="700" fill={C.ac2}
            style={{paintOrder:'stroke'}} stroke={C.paper} strokeWidth="3">CoG</text>
        </g>;
      })()}
    </svg>
  );
}

function LogAllocation({ tr }) {
  const r = tr && tr.result;
  // LG-1 — allocation matrix BUILT FROM THE SOLVE: each solved shipment is a lane that
  // picked ONE mode (the transport MILP's choice); the matrix is lane × chosen-mode with
  // the cell = that lane's value share on its picked mode (100% — one mode per lane).
  // Falls back to the illustrative literal only before the first solve.
  const SEED_LANES=['CHN→BLR','CHN→PUN','PUN→GGN','BLR→GGN'];
  const SEED_MODES=['FTL','LTL','Rail','Air'];
  const SEED_ALLOC=[[100,0,0,0],[0,0,100,0],[0,60,0,40],[0,0,0,100]];
  let lanes=SEED_LANES, modes=SEED_MODES, alloc=SEED_ALLOC;
  if(r && (r.shipments||[]).length){
    lanes = r.shipments.map(s=>s.name);
    const modeOf = s=> (s.recommended && (s.recommended.label||s.recommended.mode)) || '—';
    modes = Array.from(new Set(r.shipments.map(modeOf)));
    alloc = r.shipments.map(s=> modes.map(m=> modeOf(s)===m ? 100 : 0));
  }
  // real flows from the solved shipments (line weight = value share)
  let flows=[{from:'WH-CHN',to:'DC-BLR',w:.8},{from:'WH-CHN',to:'DC-PUN',w:1},{from:'DC-PUN',to:'CUST-GGN',w:.6},{from:'DC-BLR',to:'CUST-GGN',w:.3}];
  if(r && (r.shipments||[]).length){
    const mxv = Math.max(...r.shipments.map(s=>Number(s.value)||0), 1);
    flows = r.shipments.map(s=>({ from:s.origin, to:s.destination, w: Math.max(.2, (Number(s.value)||0)/mxv) }));
  }
  // real freight KPIs from the solve: total cost, weighted avg cost/shipment, SLA proxy
  const totFreight = r ? r.total_cost : null;
  const avgCost = r && r.shipments.length ? r.total_cost / r.shipments.length : null;
  const onTime = r ? Math.round(1000 - r.shipments.filter(s=>s.recommended && s.recommended.transit_days > s.deadline_days).length/Math.max(r.shipments.length,1)*1000)/10 : null;
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
            <Blk label="Total Freight" value={r?`₹ ${(totFreight/1e5).toFixed(2)} L`:'₹ 24.8 L'} sub={r?'solved':'planned'}/>
            <Blk label="Avg Cost/Shipment" value={r?`₹ ${Math.round(avgCost).toLocaleString('en-IN')}`:'₹ 1,420'} tone="c"/>
            <Blk label="On-time SLA" value={r?`${onTime}%`:'96.4%'} accent={C.gn}/>
          </KpiRow>
        </div>
        {r && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2}}>Solver chose: {Object.entries(r.mode_summary).map(([m,v])=>`${v.count}× ${v.label}`).join(' · ')} over {r.n_shipments} outbound shipments.</div>}
        <LogSkuFlows/>
        <Reading formula="min Σ (lane cost × volume)  s.t. demand met, capacity, SLA" soWhat={r?`Mode mix minimises freight at ₹${(totFreight/1e5).toFixed(2)}L for the outbound flow; weight tiers and deadlines drive each lane's pick.`:"Rail wins CHN→PUN on cost; Air only survives on BLR→GGN where the SLA forces speed."}/>
      </Card>
    </Grid>
  );
}

// LG-2 — per-SKU outbound flow breakdown with REAL per-SKU shipping weights (kg/unit,
// from store skuWeightKg), replacing the old flat 3 kg/unit even-split. Each finished
// SKU's monthly flow (committed demand) × its own mass → mix-accurate tonnage, so the
// lane weight the transport solver prices reflects the actual product mix.
function LogSkuFlows(){
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const rows = fin.map(p=>{ const monthly = getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12;
    const w = (typeof skuWeightKg==='function') ? skuWeightKg(p.sku) : 3;
    return { sku:p.sku, monthly, w, kg:monthly*w }; }).sort((a,b)=>b.kg-a.kg);
  const totKg = rows.reduce((s,r)=>s+r.kg,0) || 1;
  const fmt = n=>Math.round(n).toLocaleString('en-IN');
  return (
    <div style={{marginTop:10, border:`2px solid ${C.line}`}}>
      <div style={{background:C.bg3, padding:'5px 9px', fontFamily:F.disp, fontWeight:800, fontSize:11}}>LG-2 · Per-SKU outbound flow <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, fontWeight:400}}>real kg/unit · {fmt(totKg)} kg/mo total</span></div>
      <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
        <thead><tr style={{background:C.ink}}>
          {['SKU','units/mo','kg/unit','kg/mo','mix %'].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i?'right':'left', padding:'4px 9px', fontSize:8.5}}>{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((r,i)=>(
            <tr key={i} style={{borderTop:`1px solid ${C.line2}`, background:i%2?C.bg3:C.paper}}>
              <td style={{padding:'3px 9px', fontWeight:700}}>{r.sku}</td>
              <td style={{padding:'3px 9px', textAlign:'right', color:C.tx2}}>{fmt(r.monthly)}</td>
              <td style={{padding:'3px 9px', textAlign:'right', color:C.tx3}}>{r.w.toFixed(1)}</td>
              <td style={{padding:'3px 9px', textAlign:'right', fontWeight:700}}>{fmt(r.kg)}</td>
              <td style={{padding:'3px 9px', textAlign:'right', color: r.kg/totKg>0.25?C.gn:C.tx3}}>{((r.kg/totKg)*100).toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogConsolidation({ tr }) {
  const r = tr && tr.result;
  const cons = r ? (r.consolidation||[]) : null;
  const best = cons && cons.length ? cons[0] : null;       // already sorted by saving desc
  const recs = cons ? cons.filter(c=>c.recommend_consolidate) : null;
  return (
    <Card icon="📦" title="Consolidation Plan" badge={r?(recs.length?`${recs.length} lanes`:'none beat FTL'):'LTL→FTL'} badgeTone="y"
      right={r ? <Provenance kind="solved" asOf={tr.ranAt}/> : undefined}
      info={{ what:'Where merging shipments cuts unit cost.', flows:'Plan → carrier booking.' }}
      dev={{ comp:'ConsolidationCard', props:'solve.transport.consol' }}>
      <Grid cols={3}>
        <Blk label="Consolidation saving" value={r?`₹ ${(r.consolidation_saving/1e5).toFixed(2)} L`:'₹ 3.2 L/yr'} tone="y"/>
        <Blk label="Unit cost cut" value={best&&best.cost_individual?`−${Math.round((best.saving/best.cost_individual)*100)}%`:'−22%'} accent={C.gn}/>
        <Blk label="Best-lane util" value={best?`${best.utilization_pct}%`:'+0.5 d'} accent={C.a4}/>
      </Grid>
      {r ? (
        recs.length ? (
          <div style={{marginTop:10, fontFamily:F.mono, fontSize:10.5, color:C.tx2, lineHeight:1.7}}>
            {recs.map((c,i)=><div key={i}>{c.lane}: merge {c.n_shipments}×{c.individual_mode} → {c.consolidated_mode} · saves ₹{(c.saving/1000).toFixed(0)}K</div>)}
          </div>
        ) : (
          <div style={{marginTop:10, padding:'9px 11px', border:`2px solid ${C.line2}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.tx2}}>
            No outbound lane's combined weight clears a full-truckload at current volumes{best?` — best is ${best.lane} at ${best.utilization_pct}% truck utilisation`:''}. Keep individual {best?best.individual_mode:'LTL'} bookings.
          </div>
        )
      ) : (
        <>
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
        </>
      )}
    </Card>
  );
}

// Center of gravity — the closed-form weighted centroid x*=Σwᵢxᵢ/Σwᵢ over the
// delivery-side nodes (DCs + customers), weighted by node capacity (throughput
// proxy; customers get the total monthly FG flow). A real derivation, not the
// mock — no backend endpoint exists for it (it's a formula, not an optimisation).
function computeCoG(){
  const net = getNetwork();
  const M = window.M || {};
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const monthly = fin.reduce((s,p)=>s + getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12, 0);
  const dest = (net.nodes||[]).filter(n=>n.type==='dc' || n.type==='customer');
  let sw=0, sx=0, sy=0;
  dest.forEach(n=>{ const w = n.type==='customer' ? Math.max(monthly, 1) : (n.capacity||1);
    sw+=w; sx+=w*n.lng; sy+=w*n.lat; });
  if(!sw) return { lat:M.cog.lat, lng:M.cog.lng, label:M.cog.label, nodes:0, mock:true };
  const lat=+(sy/sw).toFixed(2), lng=+(sx/sw).toFixed(2);
  // nearest known city label for the computed point
  const cities=[['Kurnool',15.83,78.04],['Hyderabad',17.39,78.49],['Bengaluru',12.97,77.59],['Nagpur',21.15,79.09],['Solapur',17.66,75.91],['Hubli',15.36,75.12]];
  let best=cities[0], bd=1e9;
  cities.forEach(([nm,la,ln])=>{ const d=(la-lat)**2+(ln-lng)**2; if(d<bd){bd=d;best=[nm,la,ln];} });
  return { lat, lng, label:`Optimal hub ~ ${best[0]} (weighted centroid)`, nodes:dest.length, mock:false };
}
function LogCoG() {
  const cog = computeCoG();
  return (
    <Grid cols={2}>
      <Card icon="📍" title="Center of Gravity" badge={cog.mock?'optimal hub':`${cog.nodes} demand nodes`} badgeTone="y" info={{ what:'Weighted-distance optimal facility location.', flows:'Hub candidate → network design.' }}
        dev={{ comp:'CenterOfGravityCard', props:'nodes, demandWeights', note:'Config + result as one.' }}>
        <IndiaMap marks={M.nodes.filter(n=>n.type!=='supplier')} cog={cog}/>
      </Card>
      <Card icon="🎯" title="CoG Result" badge={cog.mock?'vs current':'derived'} badgeTone={cog.mock?undefined:'g'}
        right={cog.mock ? undefined : <Provenance kind="derived" asOf={new Date()}/>}
        info={{ what:'Recommended hub coordinates and savings.', flows:'Decision input for new DC.' }}
        dev={{ comp:'CoGResult', props:'cog (computed)' }}>
        <Blk label="Optimal Location" value={cog.label} tone="y"/>
        <div style={{marginTop:8}}><KpiRow cols={2}>
          <Blk label="Latitude" value={`${cog.lat}°N`}/>
          <Blk label="Longitude" value={`${cog.lng}°E`}/>
        </KpiRow></div>
        <div style={{marginTop:10, padding:'10px 11px', background:C.gn, color:'#fff', fontFamily:F.disp, fontWeight:800, fontSize:14}}>{cog.mock?M.cog.saving:`Centroid of ${cog.nodes} delivery nodes, demand-weighted`}</div>
        <Reading formula="x* = Σ(wᵢxᵢ)/Σwᵢ ,  y* = Σ(wᵢyᵢ)/Σwᵢ   (wᵢ = demand)"
          soWhat={cog.mock?"A Kurnool hub cuts average outbound km ~18% and relieves the DC-BLR cube pressure flagged on Network.":`Live centroid of the DC + customer nodes, weighted by throughput — recompute it whenever Network topology or the demand forecast changes.`}/>
      </Card>
    </Grid>
  );
}
window.StageLogistics = StageLogistics;
