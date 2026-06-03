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
        right={<ModelIO label="Import model"/>}/>
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
  const { network, setNetwork } = useNetwork();
  const inbound  = network.lanes.filter(l=>l.direction==='inbound');
  const outbound = network.lanes.filter(l=>l.direction==='outbound');
  const nById = Object.fromEntries(network.nodes.map(n=>[n.id,n]));
  // (review §4.1) REAL directed lane graph — not the old linear conga line. Place each
  // node in a role column (supplier→plant→wh→dc→customer) and draw every lane as its
  // own from→to edge, so hub-and-spoke and parallel paths appear exactly as defined.
  const lanes = view==='parts' ? inbound : outbound;
  const ORDER = ['supplier','plant','wh','dc','customer'];
  const ids = [...new Set(lanes.flatMap(l=>[l.from,l.to]))];
  const colOf = (id)=>{ const n=nById[id]; const t=n&&ORDER.includes(n.type)?n.type:'plant'; return t; };
  const byCol = {}; ORDER.forEach(t=>byCol[t]=[]);
  ids.forEach(id=>{ byCol[colOf(id)].push(id); });
  const cols = ORDER.filter(t=>byCol[t].length);
  const boxW=148, boxH=44, gapX=58, gapY=20, padT=42, padL=20;
  const colX = {}; cols.forEach((t,i)=> colX[t] = padL + i*(boxW+gapX));
  const maxRows = Math.max(1, ...cols.map(t=>byCol[t].length));
  const pos = {};
  cols.forEach(t=>{ const list=byCol[t]; const startY = padT + ((maxRows-list.length)*(boxH+gapY))/2;
    list.forEach((id,r)=>{ const x=colX[t], y=startY+r*(boxH+gapY); pos[id]={x,y,cx:x+boxW,cy:y+boxH/2,lx:x}; }); });
  const W = padL*2 + cols.length*boxW + Math.max(0,cols.length-1)*gapX;
  const H = padT + maxRows*(boxH+gapY) + 6;
  const roleColor = { supplier:C.a2, plant:C.ink, wh:C.a3, dc:C.a4, customer:C.gn };
  const setLane=(id,patch)=>{ setNetwork({ lanes: network.lanes.map(l=> l.id===id?{...l,...patch}:l ) }); if(typeof logEvent==='function') logEvent('override','lane:'+id,{fields:Object.keys(patch),to:patch}); };
  return (
    <StageSection step="A" title={`Flow · ${item?item.name:''}`} sub="inbound part lanes feed the plant · outbound FG lanes serve customers — each hop shows mode · ₹rate · lead time">
      <Card icon="🧭" title={view==='parts'?'Inbound Chain · purchased parts':'Outbound Chain · finished good'} badge={view==='parts'?`${inbound.length} parts`:`${outbound.length} hops`} badgeTone="y"
        info={{ what:'Directed, per-item material flow: a node\u2019s capacity is consumed by specific items.', flows:'Lanes → transport LP & landed cost.' }}
        dev={{ comp:'NetworkFlowCard', props:'state.network.lanes, activeItem', state:'network.lanes[] {direction,item}' }}>
        <svg viewBox={`0 0 ${Math.max(W,320)} ${H}`} style={{width:'100%', height:Math.max(H,160), display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
          <defs><marker id="nfah" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6 Z" fill={C.tx2}/></marker></defs>
          {cols.map((t)=>(<text key={t} x={colX[t]+boxW/2} y="14" textAnchor="middle" fontFamily={F.mono} fontSize="8.5" fill={C.tx3} letterSpacing=".1em">{t.toUpperCase()}</text>))}
          {/* edges — one per lane, from the real from→to */}
          {lanes.map(l=>{ const a=pos[l.from], b=pos[l.to]; if(!a||!b) return null;
            const intl = l.mode==='CIF'; const mx=(a.cx+b.lx)/2;
            const d=`M${a.cx} ${a.cy} C${mx} ${a.cy}, ${mx} ${b.cy}, ${b.lx} ${b.cy}`;
            return (<g key={l.id}>
              <path d={d} fill="none" stroke={intl?C.a3:C.tx2} strokeWidth="1.6" strokeDasharray={intl?'5 3':'none'} markerEnd="url(#nfah)" opacity=".75"/>
              <text x={mx} y={(a.cy+b.cy)/2 - 4} textAnchor="middle" fontFamily={F.mono} fontSize="7.5" fill={C.tx2}>{l.mode}·₹{l.rate}·{l.leadDays}d</text>
            </g>);
          })}
          {/* node boxes */}
          {ids.map(id=>{ const n=nById[id]||{id,name:id,type:'plant'}; const p=pos[id]; if(!p) return null;
            const on = item && (id===item.id); const col=roleColor[n.type]||C.ink;
            return (<g key={id}>
              <rect x={p.x} y={p.y} width={boxW} height={boxH} fill={n.type==='plant'?C.ink:C.paper} stroke={on?C.ac:C.line} strokeWidth={on?3:2}/>
              <rect x={p.x} y={p.y} width="5" height={boxH} fill={col}/>
              <text x={p.x+13} y={p.y+18} fontFamily={F.disp} fontWeight="800" fontSize="10.5" fill={n.type==='plant'?C.ac:C.tx}>{n.id}</text>
              <text x={p.x+13} y={p.y+32} fontFamily={F.mono} fontSize="7.5" fill={n.type==='plant'?C.paper:C.tx3}>{(n.name||'').slice(0,22)}</text>
            </g>);
          })}
        </svg>
        <Reading formula="each edge = one network.lanes[] row drawn from its real from→to"
          soWhat={`This is the true topology, not a linear chain: ${view==='parts'?'each supplier feeds the plant on its own inbound lane (CIF/international dashed).':'the warehouse feeds DC-BLR and DC-PUN in parallel, and the customer is reachable from either DC directly.'} Edit the lanes below — the graph and the transport LP both re-read them.`}/>

        {/* editable lane table — lanes were un-editable; trunk capacity was the missing field */}
        {(()=>{ const tin={ border:`1.5px solid ${C.line2}`, background:C.paper, color:C.tx, fontFamily:F.disp, fontWeight:700, fontSize:11, padding:'3px 5px', outline:'none', boxSizing:'border-box', textAlign:'right' };
          const EN=({v,on,w,pfx,sfx})=> <span style={{display:'inline-flex',alignItems:'center',gap:2,justifyContent:'flex-end'}}>{pfx&&<span style={{color:C.tx3,fontSize:9}}>{pfx}</span>}<input className="num" value={v==null?'':v} onChange={e=>{const s=e.target.value;const n=Number(s);on(s===''?'':(Number.isNaN(n)?v:n));}} style={{...tin,width:w||50}}/>{sfx&&<span style={{color:C.tx3,fontSize:9}}>{sfx}</span>}</span>;
          return (
          <div style={{marginTop:12}}>
            <SubLabel right={<span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>editable · mode / rate / lead / trunk capacity</span>}>Lane terms</SubLabel>
            <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
              <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
                <thead><tr style={{background:C.ink}}>{['Lane','From','To','Item','Mode','₹/unit','Lead','Trunk cap (u)'].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i<4?'left':'right', padding:'5px 8px', fontSize:8.5, textTransform:'uppercase', whiteSpace:'nowrap'}}>{h}</th>)}</tr></thead>
                <tbody>
                  {lanes.map((l,ri)=>(
                    <tr key={l.id} style={{borderTop:`1px solid ${C.line2}`, background:ri%2?C.bg3:C.paper}}>
                      <td style={{padding:'4px 8px', fontWeight:700}}>{l.id}</td>
                      <td style={{padding:'4px 8px', color:C.tx2}}>{l.from}</td>
                      <td style={{padding:'4px 8px', color:C.tx2}}>{l.to}</td>
                      <td style={{padding:'4px 8px', color:C.tx2}}>{l.item}</td>
                      <td style={{padding:'4px 6px'}}><input value={l.mode} onChange={e=>setLane(l.id,{mode:e.target.value})} style={{...tin,textAlign:'left',width:58}}/></td>
                      <td style={{padding:'4px 6px', textAlign:'right'}}><EN v={l.rate} pfx="₹" on={v=>setLane(l.id,{rate:Number(v)||0})}/></td>
                      <td style={{padding:'4px 6px', textAlign:'right'}}><EN v={l.leadDays} sfx="d" on={v=>setLane(l.id,{leadDays:Number(v)||0, lt:Number(v)||0})}/></td>
                      <td style={{padding:'4px 6px', textAlign:'right'}}><EN v={l.cap!=null?l.cap:''} w={72} on={v=>setLane(l.id,{cap:v===''?null:(Number(v)||0)})}/></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{marginTop:6, fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>trunk capacity = units per vehicle/container on this lane (blank = uncapped) — the missing planning field the review flagged; feeds shipment consolidation.</div>
          </div>
          ); })()}
      </Card>
    </StageSection>
  );
}

function NetNodes() {
  const { network, setNetwork } = useNetwork();
  const ttl = { plant:'Plant', wh:'Warehouse', dc:'Dist. Center', customer:'Customer', supplier:'Supplier' };
  const setNode=(id,patch)=>{ setNetwork({ nodes: network.nodes.map(n=> n.id===id?{...n,...patch}:n ) }); if(typeof logEvent==='function') logEvent('override','node:'+id,{fields:Object.keys(patch)}); };
  const addNode=()=>{ const n=network.nodes.length+1; const id='NODE-'+String(n).padStart(2,'0');
    if(network.nodes.some(x=>x.id===id)) return;
    setNetwork({ nodes:[...network.nodes, { id, type:'wh', name:'New node '+n, lat:0, lng:0, capacityUom:'m³', capacity:1000, cap:'1,000 m³' }] });
    if(typeof logEvent==='function') logEvent('commit','node:'+id,{added:true}); };
  const delNode=(id)=>{ setNetwork({ nodes: network.nodes.filter(n=>n.id!==id) }); if(typeof logEvent==='function') logEvent('cancel','node:'+id,{removed:true}); };
  const tin={ border:`1.5px solid ${C.line2}`, background:C.paper, color:C.tx, fontFamily:F.disp, fontWeight:700, fontSize:11, padding:'3px 5px', outline:'none', boxSizing:'border-box' };
  // (R13) storage utilisation now DERIVED — Σ(on-hand qty × volume) ÷ node cube,
  // volume from the single store authority (skuVolM3). Was hardcoded 62/74/48%.
  const vol = (typeof skuVolM3==='function') ? skuVolM3 : (()=>0);
  const usedM3 = (nodeId)=> (network.onHand||[])
    .filter(o=>o.loc===nodeId)
    .reduce((s,o)=>s + (Number(o.qty)||0)*vol(o.item), 0);
  return (
    <StageSection step="B" title="Nodes" sub="plants · warehouses · DCs · customers · suppliers — capacity is item-aware">
      <Grid cols={2}>
        <Card icon="🏭" title="Node Master" badge={`${network.nodes.length} nodes · editable`} badgeTone="y"
          info={{ what:'Every physical node with geo and capacity (uom per node). Editable master data — add/rename/resize/remove.', flows:'Topology → lanes, transport solver, CoG.' }}
          dev={{ comp:'NodeMaster', props:'setNetwork({nodes})', state:'network.nodes[]' }}>
          <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
            <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
              <thead><tr style={{background:C.ink}}>{['Node','Type','Name','Capacity','UoM',''].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i===3?'right':'left', padding:'5px 8px', fontSize:8.5, textTransform:'uppercase', whiteSpace:'nowrap'}}>{h}</th>)}</tr></thead>
              <tbody>
                {network.nodes.map((n,ri)=>(
                  <tr key={n.id} style={{borderTop:`1px solid ${C.line2}`, background:ri%2?C.bg3:C.paper}}>
                    <td style={{padding:'4px 8px', fontWeight:700, whiteSpace:'nowrap'}}>{n.id}</td>
                    <td style={{padding:'4px 6px'}}><select value={n.type} onChange={e=>setNode(n.id,{type:e.target.value})} style={{...tin, cursor:'pointer'}}>{['plant','wh','dc','customer','supplier'].map(t=><option key={t} value={t}>{ttl[t]}</option>)}</select></td>
                    <td style={{padding:'4px 6px', minWidth:120}}><input value={n.name} onChange={e=>setNode(n.id,{name:e.target.value})} style={{...tin, width:'100%'}}/></td>
                    <td style={{padding:'4px 6px', textAlign:'right'}}><input className="num" value={n.capacity==null?'':n.capacity} onChange={e=>{const v=Number(e.target.value)||0; setNode(n.id,{capacity:v, cap:v.toLocaleString('en-IN')+' '+(n.capacityUom||'')});}} style={{...tin, width:74, textAlign:'right'}}/></td>
                    <td style={{padding:'4px 6px', color:C.tx3}}>{n.capacityUom}</td>
                    <td style={{padding:'4px 6px', textAlign:'center'}}><button onClick={()=>delNode(n.id)} title="remove node" style={{border:'none', background:'transparent', color:C.dg, cursor:'pointer', fontSize:11}}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{marginTop:8}}><Btn kind="primary" sm onClick={addNode}>+ Add node</Btn></div>
        </Card>
        <Card icon="📦" title="Storage Utilization" badge="item-aware · derived" badgeTone="y"
          right={<Provenance kind="derived" note="Σ vol·on-hand / cube"/>}
          info={{ what:'Σ(item volume × on-hand) ÷ node capacity — computed from opening on-hand and the single volume master, not a lump or a seed.', flows:'Util → CoG, capacity gates.' }}
          dev={{ comp:'NodeUtilCard', props:'network.onHand × skuVolM3 ÷ node.capacity', note:'R13 — real derivation; was hardcoded 62/74/48%.' }}>
          <div style={{display:'flex', flexDirection:'column', gap:10, marginTop:2}}>
            {network.nodes.filter(n=>n.type==='wh'||n.type==='dc').map((n)=>{
              const cap = Number(n.capacity)||0; const used = usedM3(n.id);
              const pct = cap>0 ? used/cap*100 : 0;
              return (
                <div key={n.id}>
                  <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:3}}>
                    <span style={{fontWeight:700}}>{n.id}</span>
                    <span className="num" style={{color:C.tx2}}>{used.toFixed(2)} m³ · {pct<0.1&&pct>0?'<0.1':pct.toFixed(1)}% of {n.cap}</span>
                  </div>
                  <MiniBar v={pct} max={100} color={pct>70?C.a4:C.ink} h={12}/>
                </div>
              );
            })}
          </div>
          <Reading formula="util = Σ(volᵢ · onhandᵢ) / capacity_node"
            soWhat="Computed from opening on-hand × the volume master: the DCs start nearly empty (a few m³ of a multi-thousand-m³ cube) — utilisation builds as production lands. The CoG study (Logistics) sizes the hub against full-flow volume, not opening stock."/>
        </Card>
      </Grid>
    </StageSection>
  );
}

function NetSuppliers() {
  const { network } = useNetwork();
  const sup = network.suppliers;
  // footer totals now DERIVED from the rows (was hardcoded 6/35,900/₹85.0L/92.4%)
  const totQty   = sup.reduce((s,x)=>s+x.qty, 0);
  const totSpend = sup.reduce((s,x)=>s+x.spend, 0);
  const wOtif    = totQty ? sup.reduce((s,x)=>s+x.otif*x.qty, 0)/totQty : 0; // qty-weighted
  return (
    <StageSection step="C" title="Supplier Master" sub="moved here from Sourcing — BOM buy-terms reference these suppliers">
      <Card icon="📋" title="Supplier Master" badge={`${sup.length} suppliers`}
        info={{ what:'Supplier directory: lead time, variability, incoterm, spend, risk.', flows:'Suppliers → BOM commercial terms & procurement MILP.' }}
        dev={{ comp:'SupplierMaster', props:'state.network.suppliers', state:'suppliers[]' }}>
        <DataTable cols={['Code','Supplier','Location','LT','LT CV','Incoterm','Annual Qty','Spend','OTIF','Risk']} align={['left','left','left','right','right','left','right','right','right','left']}
          rows={sup.map(s=>({cells:[s.code, s.name, s.loc, `${s.lt}d`, `${s.ltCv}%`, <Tag c="w">{s.incoterm}</Tag>, s.qty.toLocaleString('en-IN'), `₹${(s.spend/100000).toFixed(1)}L`, `${s.otif}%`, <Tag c={s.risk==='H'?'r':s.risk==='M'?'a':'g'}>{s.risk}</Tag>]}))}
          foot={['TOTAL',`${sup.length} suppliers`,'','','','',totQty.toLocaleString('en-IN'),`₹${(totSpend/100000).toFixed(1)}L`,`${wOtif.toFixed(1)}%`,'']}/>
      </Card>
    </StageSection>
  );
}

function NetContracts() {
  const { network } = useNetwork();
  const tone = { spot:C.tx3, fixed:C.a2, volume:C.a3, 'take-or-pay':C.a4 };
  return (
    <StageSection step="D" title="Contracts · Time-Varying Price" sub="spot vs fixed vs volume vs take-or-pay — prices that change mid-horizon bind to the period axis">
      <Card icon="📜" title="Contract Ledger" badge={`${network.contracts.length} contracts`}
        info={{ what:'Each contract stores rateByPeriod so a price step mid-horizon is modelled, not averaged.', flows:'Rates → landed cost & procurement MILP.' }}
        dev={{ comp:'ContractLedger', props:'state.network.contracts', state:'contracts[].rateByPeriod' }}>
        <div style={{display:'flex', flexDirection:'column', gap:10}}>
          {network.contracts.map(c=>{
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
  const { network, setNetwork } = useNetwork();
  const locs = [...new Set(network.onHand.map(o=>o.loc))];
  const items = [...new Set(network.onHand.map(o=>o.item))];
  const cell = (it,loc)=> network.onHand.find(o=>o.item===it && o.loc===loc);
  const uomFor = (it)=>{ const r=network.onHand.find(o=>o.item===it); return r?r.uom:'u'; };
  const setQty = (it,loc,v)=>{ const q=Math.max(0, Number(v)||0); const exists=cell(it,loc);
    const next = exists ? network.onHand.map(o=> (o.item===it&&o.loc===loc)?{...o,qty:q}:o )
                        : [...network.onHand, { item:it, loc, qty:q, uom:uomFor(it) }];
    setNetwork({ onHand: next }); if(typeof logEvent==='function') logEvent('override','onhand:'+it+'@'+loc,{to:{qty:q}}); };
  const tin={ border:`1.5px solid ${C.line2}`, background:C.paper, color:C.tx, fontFamily:F.disp, fontWeight:700, fontSize:11, padding:'2px 4px', outline:'none', width:62, textAlign:'right', boxSizing:'border-box' };
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
                    return <td key={l} style={{textAlign:'right', padding:'3px 6px'}}>
                      <span style={{display:'inline-flex', alignItems:'center', gap:3, justifyContent:'flex-end'}}>
                        <input className="num" value={c?c.qty:''} placeholder="·" onChange={e=>setQty(it,l,e.target.value)} style={tin}/>
                        <span style={{color:C.tx3, fontSize:9}}>{uomFor(it)}</span>
                      </span></td>;
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
