// ════════════════════════════════════════════════════════════════════════
// network.jsx — Network (NEW stage 03, handoff v2 §3.03). Absorbs the master
// data that used to be scattered into Setup + Sourcing: nodes, supplier
// master, per-item inbound/outbound lanes, time-varying contracts, opening
// on-hand. Single guided scroll (0 sub-tabs). Flow is PER-ITEM, DIRECTIONAL.
// ════════════════════════════════════════════════════════════════════════
function StageNetwork({ onNav }) {
  const { item, view } = useActiveItem();
  return (
    <div>
      <StageHeader n="03" title="Network · Nodes, Flows & Contracts"
        kicker="Physical nodes · per-item inbound/outbound lanes · time-varying contracts · opening on-hand — defined AFTER products exist"
        right={<Btn kind="secondary">⤓ Import topology</Btn>}/>
      <ItemSelector/>
      <div style={{padding:18}}>
        <NetFlows item={item} view={view}/>
        <NetNodes/>
        <NetSuppliers/>
        <NetContracts/>
        <NetOnHand item={item}/>
      </div>
    </div>
  );
}

// ── the answer to "for what product is what" — light up the active item's chain ──
function NetFlows({ item, view }) {
  const inbound  = M.lanes.filter(l=>l.direction==='inbound');
  const outbound = M.lanes.filter(l=>l.direction==='outbound');
  const nById = Object.fromEntries(M.nodes.map(n=>[n.id,n]));
  // build outbound hop chain WH→DC→CUST for the active FG
  const chain = [
    { id:'PLANT-CHN' },
    ...outbound.map(l=>({ id:l.to, lane:l })),
  ];
  return (
    <StageSection step="A" title={`Flow · ${item?item.name:''}`} sub="inbound part lanes feed the plant · outbound FG lanes serve customers — each hop shows mode · ₹rate · lead time">
      <Card icon="🧭" title={view==='parts'?'Inbound Chain · purchased parts':'Outbound Chain · finished good'} badge={view==='parts'?`${inbound.length} parts`:`${outbound.length} hops`} badgeTone="y"
        info={{ what:'Directed, per-item material flow: a node\u2019s capacity is consumed by specific items.', flows:'Lanes → transport MILP & landed cost.' }}
        dev={{ comp:'NetworkFlowCard', props:'state.network.lanes, activeItem', state:'network.lanes[] {direction,item}' }}>
        <svg viewBox="0 0 880 280" style={{width:'100%', height:280, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
          {/* inbound suppliers → plant */}
          {inbound.map((l,i)=>{ const y=40+i*64;
            const intl = l.mode==='CIF';
            return (
              <g key={l.id}>
                <line x1="190" y1={y+18} x2="330" y2="140" stroke={intl?C.a3:C.tx2} strokeWidth="1.6" strokeDasharray={intl?'5 3':'none'} markerEnd="url(#nfah)" opacity=".7"/>
                <rect x="18" y={y} width="172" height="38" fill={C.bg3} stroke={C.line} strokeWidth="2"/>
                <rect x="18" y={y} width="5" height="38" fill={C.a2}/>
                <text x="30" y={y+16} fontFamily={F.disp} fontWeight="800" fontSize="10.5" fill={C.tx}>{nById[l.from]?nById[l.from].name:l.from}</text>
                <text x="30" y={y+30} fontFamily={F.mono} fontSize="8" fill={C.tx3}>{l.item} · {l.mode} · {l.leadDays}d</text>
              </g>
            );
          })}
          <text x="18" y="24" fontFamily={F.mono} fontSize="8.5" fill={C.tx3} letterSpacing=".1em">INBOUND · per purchased part →</text>
          {/* plant hub */}
          <rect x="330" y="120" width="150" height="46" fill={C.ink}/>
          <text x="342" y="142" fontFamily={F.disp} fontWeight="900" fontSize="13" fill={C.ac}>PLANT-CHN</text>
          <text x="342" y="156" fontFamily={F.mono} fontSize="8" fill={C.paper}>Chennai · 4,360 u/mo</text>
          {/* outbound plant → wh → dc → customer */}
          {outbound.map((l,i)=>{
            const xs=[480,560,640,720,800]; const x1=xs[i], x2=xs[i+1]||xs[i]+80;
            return (
              <g key={l.id}>
                <line x1={x1} y1="143" x2={x1+74} y2="143" stroke={C.tx2} strokeWidth="1.6" markerEnd="url(#nfah)" opacity=".7"/>
                <text x={x1+37} y="134" textAnchor="middle" fontFamily={F.mono} fontSize="7.5" fill={C.tx2}>{l.mode}·₹{l.rate}</text>
                <text x={x1+37} y="160" textAnchor="middle" fontFamily={F.mono} fontSize="7.5" fill={C.tx3}>{l.leadDays}d</text>
              </g>
            );
          })}
          {[['WH-CHN',506],['DC-BLR',586],['DC-PUN',666],['GGN',760]].map(([lbl,x],i)=>(
            <g key={i}>
              <rect x={x-2} y="124" width="58" height="38" fill={i===3?C.bg3:C.paper} stroke={C.line} strokeWidth="2"/>
              <text x={x+27} y="147" textAnchor="middle" fontFamily={F.disp} fontWeight="800" fontSize="9" fill={C.tx}>{lbl}</text>
            </g>
          ))}
          <text x="480" y="24" fontFamily={F.mono} fontSize="8.5" fill={C.tx3} letterSpacing=".1em">OUTBOUND · finished good →</text>
          <defs><marker id="nfah" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6 Z" fill={C.tx2}/></marker></defs>
        </svg>
        <Reading formula="utilization = Σ(item volume × on-hand) ÷ node capacity"
          soWhat={`Switch the item selector to “its parts” to trace the inbound side; international lanes (POSCO/CIF, dashed) carry the long ${inbound.find(l=>l.mode==='CIF')?inbound.find(l=>l.mode==='CIF').leadDays:18}-day lead.`}/>
      </Card>
    </StageSection>
  );
}

function NetNodes() {
  const ttl = { plant:'Plant', wh:'Warehouse', dc:'Dist. Center', customer:'Customer', supplier:'Supplier' };
  const util = { 'WH-CHN':62, 'DC-BLR':74, 'DC-PUN':48 };
  return (
    <StageSection step="B" title="Nodes" sub="plants · warehouses · DCs · customers · suppliers — capacity is item-aware">
      <Grid cols={2}>
        <Card icon="🏭" title="Node Master" badge={`${M.nodes.length} nodes`}
          info={{ what:'Every physical node with geo and capacity (uom per node).', flows:'Topology → lanes, transport solver, CoG.' }}
          dev={{ comp:'NodeMaster', props:'state.network.nodes', state:'network.nodes[]' }}>
          <DataTable dense cols={['Node','Type','Name','Capacity']} align={['left','left','left','right']}
            rows={M.nodes.map(n=>[n.id, ttl[n.type]||n.type, n.name, n.cap])}/>
        </Card>
        <Card icon="📦" title="Storage Utilization" badge="item-aware" badgeTone="y"
          info={{ what:'Σ(item volume × on-hand) ÷ node capacity — storage is not a lump.', flows:'Util → CoG, capacity gates.' }}
          dev={{ comp:'NodeUtilCard', props:'nodes, onHand, item volumes (computed)' }}>
          <div style={{display:'flex', flexDirection:'column', gap:10, marginTop:2}}>
            {M.nodes.filter(n=>n.type==='wh'||n.type==='dc').map((n,i)=>(
              <div key={n.id}>
                <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:3}}>
                  <span style={{fontWeight:700}}>{n.id}</span><span className="num" style={{color:C.tx2}}>{util[n.id]||40}% of {n.cap}</span>
                </div>
                <MiniBar v={util[n.id]||40} max={100} color={(util[n.id]||40)>70?C.a4:C.ink} h={12}/>
              </div>
            ))}
          </div>
          <Reading formula="util = Σ(volᵢ · onhandᵢ) / capacity_node" soWhat="DC-BLR at 74% — nearing the cube limit; the CoG study (Logistics) tests a Kurnool hub to relieve it."/>
        </Card>
      </Grid>
    </StageSection>
  );
}

function NetSuppliers() {
  return (
    <StageSection step="C" title="Supplier Master" sub="moved here from Sourcing — BOM buy-terms reference these suppliers">
      <Card icon="📋" title="Supplier Master" badge={`${M.suppliers.length} suppliers`}
        info={{ what:'Supplier directory: lead time, variability, incoterm, spend, risk.', flows:'Suppliers → BOM commercial terms & procurement MILP.' }}
        dev={{ comp:'SupplierMaster', props:'state.network.suppliers', state:'suppliers[]' }}>
        <DataTable cols={['Code','Supplier','Location','LT','LT CV','Incoterm','Annual Qty','Spend','OTIF','Risk']} align={['left','left','left','right','right','left','right','right','right','left']}
          rows={M.suppliers.map(s=>({cells:[s.code, s.name, s.loc, `${s.lt}d`, `${s.ltCv}%`, <Tag c="w">{s.incoterm}</Tag>, s.qty.toLocaleString('en-IN'), `₹${(s.spend/100000).toFixed(1)}L`, `${s.otif}%`, <Tag c={s.risk==='H'?'r':s.risk==='M'?'a':'g'}>{s.risk}</Tag>]}))}
          foot={['TOTAL','6 suppliers','','','','','35,900','₹85.0L','92.4%','']}/>
      </Card>
    </StageSection>
  );
}

function NetContracts() {
  const tone = { spot:C.tx3, fixed:C.a2, volume:C.a3, 'take-or-pay':C.a4 };
  return (
    <StageSection step="D" title="Contracts · Time-Varying Price" sub="spot vs fixed vs volume vs take-or-pay — prices that change mid-horizon bind to the period axis">
      <Card icon="📜" title="Contract Ledger" badge={`${M.contracts.length} contracts`}
        info={{ what:'Each contract stores rateByPeriod so a price step mid-horizon is modelled, not averaged.', flows:'Rates → landed cost & procurement MILP.' }}
        dev={{ comp:'ContractLedger', props:'state.network.contracts', state:'contracts[].rateByPeriod' }}>
        <div style={{display:'flex', flexDirection:'column', gap:10}}>
          {M.contracts.map(c=>{
            const pts = c.rateByPeriod;
            const prices = pts.map(p=>p[1]); const mn=Math.min(...prices)*0.9, mx=Math.max(...prices)*1.05, rng=(mx-mn)||1;
            return (
              <div key={c.id} style={{border:`2px solid ${C.line}`, padding:'9px 11px', display:'grid', gridTemplateColumns:'160px 1fr 200px', gap:12, alignItems:'center'}}>
                <div>
                  <div style={{fontFamily:F.disp, fontSize:12, fontWeight:800}}>{c.id}</div>
                  <div style={{fontFamily:F.mono, fontSize:9, color:C.tx3, marginTop:2}}>{c.party} · {c.item}</div>
                  <Tag c="w" style={{marginTop:4, background:tone[c.type], color:'#fff'}}>{c.type}</Tag>
                </div>
                <svg viewBox="0 0 320 56" style={{width:'100%', height:56}}>
                  {(()=>{ const xs=pid=>20+(pid/51)*290, yy=v=>50-((v-mn)/rng)*42;
                    const d = pts.map((p,i)=>(i?'L':'M')+xs(p[0]).toFixed(1)+' '+yy(p[1]).toFixed(1)).join(' ');
                    // step line
                    let sd=''; pts.forEach((p,i)=>{ const x=xs(p[0]),y=yy(p[1]); if(i===0) sd=`M${x} ${y}`; else { const px=xs(pts[i-1][0]); sd+=` L${x} ${yy(pts[i-1][1]).toFixed(1)} L${x} ${y}`; } });
                    sd+=` L${xs(51)} ${yy(pts[pts.length-1][1]).toFixed(1)}`;
                    return <>
                      <path d={sd} fill="none" stroke={C.ink} strokeWidth="2"/>
                      {pts.map((p,i)=><g key={i}><circle cx={xs(p[0])} cy={yy(p[1])} r="3" fill={C.ac} stroke={C.ink} strokeWidth="1.3"/><text x={xs(p[0])} y={yy(p[1])-6} textAnchor="middle" fontFamily={F.mono} fontSize="8" fill={C.tx2}>₹{p[1]}</text></g>)}
                    </>;
                  })()}
                </svg>
                <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>
                  {pts.map((p,i)=><div key={i}>{M.pLabel(p[0])} ({M.pDate(p[0])}) → ₹{p[1]}</div>)}
                </div>
              </div>
            );
          })}
        </div>
        <Reading formula="landed_cost(t) = rateByPeriod[t] × qty + duties + freight" soWhat="The steel contract steps +6.5% at W29 (Jul) — the rolling-horizon solver buys ahead of the step, not after."/>
      </Card>
    </StageSection>
  );
}

function NetOnHand({ item }) {
  const locs = [...new Set(M.onHand.map(o=>o.loc))];
  const items = [...new Set(M.onHand.map(o=>o.item))];
  const cell = (it,loc)=> M.onHand.find(o=>o.item===it && o.loc===loc);
  return (
    <StageSection step="E" title="Opening On-Hand" sub="item × location — only meaningful now that both products AND nodes exist">
      <Card icon="📦" title="On-Hand Matrix" badge="opening stock"
        info={{ what:'Starting inventory per item per site at horizon start.', flows:'Initial stock → MRP & inventory projection.' }}
        dev={{ comp:'OnHandMatrix', props:'state.network.onHand', state:'network.onHand[item][loc]' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
            <thead><tr style={{background:C.ink}}>
              <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>Item ↓ / Node →</th>
              {locs.map(l=><th key={l} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{l}</th>)}
            </tr></thead>
            <tbody>
              {items.map((it,ri)=>(
                <tr key={it} style={{borderTop:`1px solid ${C.line2}`, background: item&&it===item.id?C.ac: ri%2?C.bg3:C.paper}}>
                  <td style={{padding:'5px 9px', fontWeight:700}}>{it}</td>
                  {locs.map(l=>{ const c=cell(it,l);
                    return <td key={l} className="num" style={{textAlign:'right', padding:'5px 9px', color: c?C.tx:C.tx3}}>{c?`${c.qty.toLocaleString('en-IN')} ${c.uom}`:'·'}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Reading soWhat="The highlighted row is the active item — its WH/DC stock seeds the MRP net-requirement on Sourcing."/>
      </Card>
    </StageSection>
  );
}
window.StageNetwork = StageNetwork;
