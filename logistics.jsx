// ════════════════════════════════════════════════════════════════════════
// logistics.jsx — Logistics & Network (LogisticsTab). Sub-tabs: Network ·
// Lanes · 3PL · Center of Gravity · Allocation.
// ════════════════════════════════════════════════════════════════════════
function StageLogistics({ onNav }) {
  const [sub, setSub] = useState('network');
  const tabs = [
    { id:'network',    n:'a', label:'Network', count:M.nodes.length },
    { id:'lanes',      n:'b', label:'Lanes', count:M.lanes.length },
    { id:'providers',  n:'c', label:'3PL & Delivery' },
    { id:'cog',        n:'d', label:'Center of Gravity' },
    { id:'allocation', n:'e', label:'Allocation' },
  ];
  return (
    <div>
      <StageHeader n="07" title="Logistics & Network" kicker="Nodes · multi-hop lanes · 3PL providers · center-of-gravity · transport allocation"
        right={<Btn kind="accent" onClick={()=>onNav('console')}>⚡ Solve Transport</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='network'    && <LogNetwork/>}
        {sub==='lanes'      && <LogLanes/>}
        {sub==='providers'  && <LogProviders/>}
        {sub==='cog'        && <LogCoG/>}
        {sub==='allocation' && <LogAllocation/>}
      </div>
    </div>
  );
}

// crude India map with plotted nodes
function IndiaMap({ marks, cog }) {
  // normalize lat/lng to a box (India approx lat 8-30, lng 68-92)
  const px=(lng)=> (lng-68)/(92-68)*340+20;
  const py=(lat)=> (30-lat)/(30-8)*300+14;
  return (
    <svg viewBox="0 0 380 330" style={{width:'100%', maxWidth:380, height:330, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
      <path d="M120 20 L180 30 L230 25 L250 70 L280 120 L250 180 L210 250 L180 300 L150 260 L120 200 L90 150 L80 90 L100 50 Z"
        fill={C.bg3} stroke={C.line2} strokeWidth="1.5"/>
      {marks.map((m,i)=>{
        const x=px(m.lng), y=py(m.lat);
        const col=m.type==='Plant'?C.dg:m.type==='Customer'?C.a2:C.ink;
        return (<g key={i}>
          <circle cx={x} cy={y} r={m.type==='Plant'?6:4} fill={col} stroke={C.paper} strokeWidth="1.5"/>
          <text x={x+8} y={y+3} fontFamily={F.mono} fontSize="8.5" fill={C.tx} fontWeight="700">{m.id}</text>
        </g>);
      })}
      {cog && (()=>{ const x=px(cog.lng), y=py(cog.lat);
        return <g><circle cx={x} cy={y} r="9" fill="none" stroke={C.ac2} strokeWidth="2.5"/><line x1={x-13} y1={y} x2={x+13} y2={y} stroke={C.ac2} strokeWidth="2"/><line x1={x} y1={y-13} x2={x} y2={y+13} stroke={C.ac2} strokeWidth="2"/></g>;
      })()}
    </svg>
  );
}

function LogNetwork() {
  return (
    <Grid cols={2}>
      <Card icon="🏭" title="Network Node Master" badge={`${M.nodes.length} nodes`} info={{ what:'All physical nodes with type and capacity.', flows:'Nodes → lanes & transport solver.' }}
        dev={{ comp:'LogisticsNodeMasterCard', props:'state.network.nodes', state:'network.nodes[]' }}>
        <DataTable dense cols={['Node','Type','Name','Lat','Lng','Cap']} align={['left','left','left','right','right','right']}
          rows={M.nodes.map(n=>[n.id, n.type, n.name, n.lat, n.lng, n.cap])}/>
      </Card>
      <Card icon="🗺️" title="Network Map" badge="geo" info={{ what:'Geographic view of the distribution network.', flows:'Visual for CoG & lane planning.' }}
        dev={{ comp:'NetworkMap', props:'nodes' }}>
        <IndiaMap marks={M.nodes}/>
      </Card>
      <Card icon="💰" title="Logistics Budget Gate" badge="₹1.40 Cr" badgeTone="k" info={{ what:'Annual logistics budget the transport solver cannot exceed.', flows:'Gate → transport MILP constraint.' }} span={2}
        dev={{ comp:'LogisticsBudgetGateCard', props:'state.budget.logistics' }}>
        <div style={{display:'flex', gap:14, alignItems:'center'}}>
          <div style={{flex:1}}>
            <div style={{display:'flex', height:26, border:`2px solid ${C.line}`}}>
              <div style={{width:'68%', background:C.ink, color:C.paper, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>SPENT ₹95L</div>
              <div style={{width:'32%', background:C.ac, color:C.onAc, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>FREE ₹45L</div>
            </div>
          </div>
          <Blk label="Utilization" value="68%" accent={C.gn}/>
        </div>
      </Card>
    </Grid>
  );
}

function LogLanes() {
  return (
    <Grid cols={1}>
      <Card icon="🛣️" title="Multi-Hop Lane Network" badge={`${M.lanes.length} lanes`} info={{ what:'Origin→destination legs with mode, distance, rate, transit.', flows:'Lanes → transport MILP routing.' }}
        dev={{ comp:'LogisticsLaneEditorCard', props:'state.network.lanes', state:'network.lanes[]' }}>
        <DataTable cols={['From','To','Mode','Distance','Rate','Transit']} align={['left','left','left','right','right','right']}
          rows={M.lanes.map(l=>({cells:[l.from, l.to, <Tag c="w">{l.mode}</Tag>, `${l.km} km`, `₹${l.rate}/${l.mode==='LTL'||l.mode==='Air'?'kg':'km'}`, `${l.lt}d`]}))}/>
      </Card>
      <Card icon="📋" title="Transport Contract Ledger" badge="modes & rates" info={{ what:'Contracted vs spot rates per mode.', flows:'Rates → landed & transport cost.' }}
        dev={{ comp:'TransportContractLedgerCard', props:'state.network.contracts' }}>
        <DataTable dense cols={['Contract','Mode','Basis','Rate','Term','Committed Vol']} align={['left','left','left','right','left','right']}
          rows={[['VRL-2026','FTL','per km','₹14','Annual','60%'],['BlueDart','LTL','per kg','₹22','Annual','—'],['CONCOR','Rail','per km','₹6.2','Trunk','40%'],['SpiceXpress','Air','per kg','₹88','Spot','—']]}/>
      </Card>
    </Grid>
  );
}

function LogProviders() {
  return (
    <Grid cols={2}>
      <Card icon="🚛" title="3PL Provider Master" badge={`${M.tpl.length} providers`} info={{ what:'Third-party carriers with SLA, rate, coverage.', flows:'3PL → transport sourcing.' }}
        dev={{ comp:'ThreePlProviderCard', props:'state.network.tpl', state:'network.tpl[]' }}>
        <DataTable cols={['Code','Provider','Mode','SLA','Rate','Zones']} align={['left','left','left','right','right','left']}
          rows={M.tpl.map(t=>[t.code, t.name, t.mode, t.sla, t.rate, t.zones])}/>
      </Card>
      <Card icon="📅" title="MTO Delivery Schedule" badge="committed" info={{ what:'Outbound delivery dates per MTO order.', flows:'From transport solver; SLA tracking.' }}
        dev={{ comp:'MTODeliveryScheduleCard', props:'orders, transport' }}>
        <DataTable dense cols={['PO','Customer','Ship Wk','Mode','ETA']} align={['left','left','left','left','left']}
          rows={M.orders.slice(0,5).map((o,i)=>[o.po, o.cust, ['W14','W16','W18','W17','W20'][i], ['FTL','LTL','Rail','FTL','Air'][i], o.due.slice(5)])}/>
      </Card>
    </Grid>
  );
}

function LogCoG() {
  return (
    <Grid cols={2}>
      <Card icon="📍" title="Center of Gravity" badge="optimal hub" badgeTone="y" info={{ what:'Weighted-distance optimal facility location.', flows:'Hub candidate → network design.' }}
        dev={{ comp:'CenterOfGravityCard', props:'nodes, demandWeights', note:'Config + result rendered as one.' }}>
        <IndiaMap marks={M.nodes} cog={M.cog}/>
      </Card>
      <Card icon="🎯" title="CoG Result" badge="vs current" info={{ what:'Recommended hub coordinates and savings.', flows:'Decision input for new DC.' }}
        dev={{ comp:'CoGResult', props:'cog (computed)' }}>
        <Blk label="Optimal Location" value={M.cog.label} tone="y"/>
        <div style={{marginTop:8}}><KpiRow cols={2}>
          <Blk label="Latitude" value={`${M.cog.lat}°N`}/>
          <Blk label="Longitude" value={`${M.cog.lng}°E`}/>
        </KpiRow></div>
        <div style={{marginTop:10, padding:'10px 11px', background:C.gn, color:'#fff', fontFamily:F.disp, fontWeight:800, fontSize:14}}>
          {M.cog.saving}
        </div>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color:C.tx3, lineHeight:1.5}}>
          Weighted by demand at DC-BLR, DC-PUN, CUST-GGN. A Kurnool hub cuts avg outbound km 18%.
        </div>
      </Card>
    </Grid>
  );
}

function LogAllocation() {
  const lanes=['CHN→BLR','CHN→PUN','PUN→GGN','BLR→GGN'];
  const modes=['FTL','LTL','Rail','Air'];
  const alloc=[[100,0,0,0],[0,0,100,0],[0,60,0,40],[0,0,0,100]];
  return (
    <Card icon="🚛" title="Transport Allocation Matrix" badge="lane × mode" info={{ what:'How shipments split across modes per lane (from solver).', flows:'Allocation → carrier booking.' }}
      dev={{ comp:'TransportAllocationCard', props:'solve.transport.allocation', note:'Was on Command — belongs here (handoff §3.06).' }}>
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
    </Card>
  );
}
window.StageLogistics = StageLogistics;
