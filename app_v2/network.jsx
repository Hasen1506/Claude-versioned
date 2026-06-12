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
      <ItemSelector onNav={onNav}/>
      {/* ① DECIDE strip (Part 3.2) — derived live from the network master; no solve, nothing faked */}
      <div style={{padding:'8px 18px', borderBottom:`2px solid ${C.line}`, background:C.paper}}>
        <NetworkDecideStrip/>
      </div>
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
    <StageSection step="A" scope="item" title={`Flow · ${item?item.name:''}`} sub="inbound part lanes feed the plant · outbound FG lanes serve customers — each hop shows mode · ₹rate · lead time">
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
  // (R13→G-N3) storage utilisation is DERIVED — Σ(on-hand qty × volume) ÷ node cube,
  // volume from the single store authority (skuVolM3), now split per storage class
  // (nodeStorageUtil). Was hardcoded 62/74/48%.
  return (
    <StageSection step="B" scope="global" title="Nodes" sub="plants · warehouses · DCs · customers · suppliers — the shared network; the capacity column is an item-aware lens on the selected SKU">
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
        <Card icon="📦" title="Storage Utilization" badge="per-class · derived" badgeTone="y"
          right={<Provenance kind="derived" note="Σ vol·on-hand / class cube"/>}
          info={{ what:'Σ(item volume × on-hand) ÷ node capacity, split BY STORAGE CLASS (ambient/cold/hazmat) — a cold SKU and an ambient SKU cannot share the same m³. Default: every item is ambient and the whole cube is ambient capacity (= the single-bar number).', flows:'Util → CoG, capacity gates.' }}
          dev={{ comp:'NodeUtilCard', props:'network.onHand × skuVolM3 ÷ node.classCaps[cls]', note:'G-N3 — per-storage-class; was one lump cube (R13).' }}>
          <div style={{display:'flex', flexDirection:'column', gap:10, marginTop:2}}>
            {network.nodes.filter(n=>n.type==='wh'||n.type==='dc').map((n)=>{
              const util = nodeStorageUtil(n);
              const totalUsed = STORAGE_CLASSES.reduce((s,c)=>s+util[c].used,0);
              const shown = STORAGE_CLASSES.filter(c=> c==='ambient' || util[c].cap>0 || util[c].used>0.0001);
              const editClassCap=(cls,val)=>{
                const cc = n.classCaps ? {...n.classCaps} : { ambient:Number(n.capacity)||0, cold:0, hazmat:0 };
                cc[cls] = val===''?'':(Number(val)||0);
                setNode(n.id, { classCaps:cc });
              };
              return (
                <div key={n.id} style={{border:`1px solid ${C.line2}`, padding:'6px 8px'}}>
                  <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:5}}>
                    <span style={{fontWeight:700}}>{n.id}</span>
                    <span className="num" style={{color:C.tx3}}>{totalUsed.toFixed(2)} m³ stored · {n.classCaps?'per-class caps':'single cube'}</span>
                  </div>
                  {shown.map(c=>{
                    const u=util[c]; const noCap = !(u.cap>0);
                    return (
                      <div key={c} style={{marginBottom:4}}>
                        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', fontFamily:F.mono, fontSize:9, marginBottom:2}}>
                          <span style={{color:C.tx2}}>{STORAGE_CLASS_LABEL[c]}</span>
                          <span style={{display:'flex', alignItems:'center', gap:5}}>
                            <span className="num" style={{color: u.pct>90?C.dg:C.tx3}}>{u.used.toFixed(2)} / </span>
                            <input className="num" value={u.cap===''?'':u.cap} onChange={e=>editClassCap(c,e.target.value)} title="class capacity (m³)"
                              style={{ width:60, fontFamily:F.mono, fontSize:9, textAlign:'right', padding:'1px 3px', border:`1px solid ${C.line2}`, background:C.paper, color:C.tx }}/>
                            <span style={{color:C.tx3}}>m³{noCap?'':` · ${u.pct<0.1&&u.pct>0?'<0.1':u.pct.toFixed(1)}%`}</span>
                          </span>
                        </div>
                        {noCap
                          ? (u.used>0.0001 ? <div style={{fontFamily:F.mono, fontSize:8, color:C.dg}}>⚠ {u.used.toFixed(2)} m³ stored but NO {c} capacity declared</div> : null)
                          : <MiniBar v={u.pct} max={100} color={u.pct>90?C.dg:u.pct>70?C.a4:C.ink} h={9}/>}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
          <Reading formula="util_class = Σ(volᵢ · onhandᵢ | classᵢ = class) / classCap_node"
            soWhat="Split by storage class: a cold-chain or hazmat SKU draws on its OWN node capacity, not the shared cube — so a node can be 30% full overall yet out of cold space. Assign classes below; default all-ambient = the prior single cube."/>
        </Card>
      </Grid>
      <NetStorageClasses/>
    </StageSection>
  );
}
// G-N3 — per-item STORAGE CLASS assignment (ambient/cold/hazmat). Scoped to the items
// actually held in opening on-hand. Default ambient ⇒ node utilisation = the single-cube
// number; flip a SKU to cold/hazmat and it draws on that class's node capacity instead.
function NetStorageClasses(){
  const { network } = useNetwork();
  const { config, setConfig } = useConfig();
  const cls = config.storageClass || {};
  const items = Array.from(new Set((network.onHand||[]).map(o=>o.item)));
  const nameOf = (it)=>{ const p=((window.M&&M.products)||[]).find(x=>x.sku===it); if(p) return p.name;
    const b=((window.M&&M.bom)||[]).find(x=>x.part===it); return b?b.name:''; };
  const setItemClass=(it,v)=> setConfig({ storageClass: { ...cls, [it]: v } });
  return (
    <Card icon="🌡" title="Storage class by item" badge="warehousing master" badgeTone="y"
      info={{ what:'The storage class each held item needs — ambient, cold chain, or hazmat. Drives the per-class node utilisation above (a cold SKU consumes cold m³, not the shared cube).', flows:'Item class → per-class node utilisation.' }}
      dev={{ comp:'NetStorageClasses', props:'config.storageClass{item:class}', state:'config.storageClass' }}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>{['Item','Name','Storage class'].map((h,i)=><th key={i} style={{color:C.paper, textAlign:'left', padding:'5px 9px', fontSize:8.5, textTransform:'uppercase'}}>{h}</th>)}</tr></thead>
          <tbody>
            {items.map((it,ri)=>(
              <tr key={it} style={{borderTop:`1px solid ${C.line2}`, background:ri%2?C.bg3:C.paper}}>
                <td style={{padding:'4px 9px', fontWeight:700}}>{it}</td>
                <td style={{padding:'4px 9px', color:C.tx3}}>{nameOf(it)}</td>
                <td style={{padding:'4px 9px'}}>
                  <select value={cls[it]||'ambient'} onChange={e=>setItemClass(it,e.target.value)}
                    style={{ fontFamily:F.mono, fontSize:10, padding:'2px 4px', border:`1px solid ${C.line}`, background:C.paper, color:C.tx, cursor:'pointer' }}>
                    {STORAGE_CLASSES.map(c=><option key={c} value={c}>{STORAGE_CLASS_LABEL[c]}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Reading formula="item → storage class → which node-class cube it consumes"
        soWhat="Default is ambient for every item (so utilisation matches the single-cube view). Mark a SKU cold or hazmat and the per-class bars above re-attribute its volume to that class — exposing a node that's out of cold space even when the overall cube has room."/>
    </Card>
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
    <StageSection step="C" scope="global" title="Supplier Master" sub="moved here from Sourcing — BOM buy-terms reference these suppliers">
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
    <StageSection step="D" scope="global" title="Contracts · Time-Varying Price" sub="spot vs fixed vs volume vs take-or-pay — prices that change mid-horizon bind to the period axis">
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
    <StageSection step="E" scope="item" title="Opening On-Hand" sub="item × location — the selected SKU's opening stock at each node">
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
        {/* V5-1 — the netting POLICY made explicit: WHICH solver consumes each row, and the
            DRP discipline for downstream stock. Scope toggle is governed (cfg.prod). */}
        <NetNettingPolicy/>
      </Card>

      <NetScheduledReceipts/>
    </StageSection>
  );
}

// V5-1 — multi-site netting policy strip: the on-hand TRANSACTION layer is now
// consumed by the solvers, and this states exactly where each row nets (no silent
// assumptions). The FG scope toggle writes config.netFgScope (token cfg.prod →
// production + aggregate go stale when flipped).
function NetNettingPolicy(){
  const { config, setConfig } = useConfig();
  const scope = config.netFgScope || 'plant_wh';
  const opts = [
    { id:'plant_wh', label:'Plant + WH (DRP)', hint:'DC stock serves its region, not the plant build' },
    { id:'all',      label:'Whole network',    hint:'every location nets the master schedule' },
    { id:'off',      label:'Off (gross)',      hint:'schedule ignores FG stock' },
  ];
  return (
    <div data-vis="v5-net" style={{marginTop:11, padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.a3}`, background:C.bg3}}>
      <div style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.a3, letterSpacing:'.1em', marginBottom:5}}>WHERE EACH ROW NETS (V5-1 — the ledger is consumed, not decorative)</div>
      <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.55}}>
        <b>RM at plant/WH</b> → opens the procurement MILP's material balance (no more fabricated
        avg-demand cover). <b>FG at plant/WH</b> → nets the master schedule's required_qty and serves
        the earliest weeks via opening inventory. <b>FG at a DC</b> → positioned stock serving its
        region (DRP): netted by S&amp;OP network-wide, but NOT against the plant build unless you widen
        the scope. <b>Aggregate S&amp;OP</b> always nets the whole network (planOpeningInv).
      </div>
      <div style={{display:'flex', gap:6, alignItems:'center', marginTop:8}}>
        <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>SCHEDULE NETTING SCOPE</span>
        {opts.map(o=>(
          <button key={o.id} title={o.hint} onClick={()=>setConfig({ netFgScope:o.id })}
            style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, padding:'4px 9px', cursor:'pointer',
              border:`2px solid ${scope===o.id?C.ac:C.line}`, background:scope===o.id?C.ac:C.paper,
              color:scope===o.id?C.paper:C.tx2}}>{o.label}</button>
        ))}
      </div>
    </div>
  );
}

// G-N1 — open / in-transit POs already released to suppliers. The procurement MILP
// books each as an exogenous RM arrival (release + lead time) and re-optimises only the
// residual gap, so a receipt NETS DOWN the planned buy. Editable; empty ⇒ greenfield buy.
function NetScheduledReceipts(){
  const { network, setNetwork } = useNetwork();
  const M = window.M || {};
  const rows = network.scheduledReceipts || [];
  const partName = (id)=>{ const b=(M.bom||[]).find(x=>x.part===id); return b?b.name:id; };
  const leadDays = (id)=>{ const b=(M.bom||[]).find(x=>x.part===id); return b?b.lt:0; };
  const arrive = (rel,id)=>{ if(!rel) return '—'; const d=new Date(rel); if(isNaN(d.getTime())) return '—';
    d.setDate(d.getDate()+leadDays(id)); return d.toISOString().slice(0,10); };
  const setRow = (i,patch)=>{ const next = rows.map((r,j)=> j===i?{...r,...patch}:r); setNetwork({ scheduledReceipts: next });
    if(typeof logEvent==='function') logEvent('override','sched-receipt:'+(rows[i]&&rows[i].part),{to:patch}); };
  const del = (i)=>{ setNetwork({ scheduledReceipts: rows.filter((_,j)=>j!==i) }); };
  const add = ()=>{ const firstPart=(M.bom&&M.bom[0]&&M.bom[0].part)||'RM-STL42';
    setNetwork({ scheduledReceipts:[...rows, { part:firstPart, qty:0, releaseDate:'', po:'' }] }); };
  const tin={ border:`1.5px solid ${C.line2}`, background:C.paper, color:C.tx, fontFamily:F.disp, fontWeight:700, fontSize:11, padding:'2px 4px', outline:'none', boxSizing:'border-box' };
  return (
    <Card icon="🚚" title="Scheduled Receipts" badge={`${rows.length} open PO${rows.length===1?'':'s'}`} badgeTone="g"
      info={{ what:'Open / in-transit purchase orders already released to suppliers. The MRP nets against these — it books each as a raw-material arrival at release + lead time and only buys the residual gap, so it never re-orders what is already inbound.', flows:'Scheduled receipts → procurement MILP (locked_pos) → net buy ↓.' }}
      dev={{ comp:'NetScheduledReceipts', props:'state.network.scheduledReceipts', state:'network.scheduledReceipts[]', note:'G-N1 — wired to procurement.py T6 locked_pos via scheduledReceiptsLocked() (store.jsx).' }}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            {['Part','Qty','Release date','→ Arrives (rel + lead)','PO ref',''].map((h,i)=>
              <th key={i} style={{color:C.paper, textAlign:i===1?'right':'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.length===0 && <tr><td colSpan={6} style={{padding:'8px 9px', color:C.tx3}}>No open POs — the buy plan is greenfield (orders everything from scratch).</td></tr>}
            {rows.map((r,i)=>(
              <tr key={i} style={{borderTop:`1px solid ${C.line2}`, background: i%2?C.bg3:C.paper}}>
                <td style={{padding:'4px 9px'}}>
                  <select value={r.part} onChange={e=>setRow(i,{part:e.target.value})} style={{...tin, width:150}}>
                    {(M.bom||[]).map(b=><option key={b.part} value={b.part}>{b.part} · {b.name}</option>)}
                  </select>
                </td>
                <td style={{textAlign:'right', padding:'4px 9px'}}><input className="num" value={r.qty} onChange={e=>setRow(i,{qty:Math.max(0,Number(e.target.value)||0)})} style={{...tin, width:72, textAlign:'right'}}/></td>
                <td style={{padding:'4px 9px'}}><input type="date" value={r.releaseDate||''} onChange={e=>setRow(i,{releaseDate:e.target.value})} style={{...tin, width:130}}/></td>
                <td style={{padding:'4px 9px', color:C.gn, fontWeight:700}}>{arrive(r.releaseDate, r.part)}</td>
                <td style={{padding:'4px 9px', color:C.tx2}}><input value={r.po||''} onChange={e=>setRow(i,{po:e.target.value})} placeholder="PO ref" style={{...tin, width:110, fontWeight:600}}/></td>
                <td style={{padding:'4px 9px', textAlign:'right'}}><button onClick={()=>del(i)} style={{border:`1px solid ${C.line2}`, background:'transparent', color:C.tx3, cursor:'pointer', fontSize:11, padding:'1px 7px'}}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{marginTop:8}}><Btn sm onClick={add}>+ Open PO</Btn></div>
      <Reading formula="net req = gross demand − on-hand − scheduled receipts   ·   receipt arrives at release + part lead time"
        soWhat="Each open PO lands in raw-material inventory at its arrival period and the procurement MILP buys only the residual — change a qty or release date and re-run Sourcing to see the planned buy move."/>
    </Card>
  );
}
// ── V3-9 · ① DECIDE strip (blueprint 3.2) — the tab's question + KPIs, DERIVED ──
// live from the network master (no solver runs on this tab; every numeric here
// rides a structured per-row grid — lanes, nodes, on-hand, receipts — which is
// the honest editor for row-shaped master data, so there are deliberately ZERO
// scalar GovFields on this tab): topology size, the tightest storage class, and
// the inbound already on the water.
function NetworkDecideStrip(){
  const { network } = useNetwork();
  const nodes = network.nodes || [], lanes = network.lanes || [];
  let worst = null;   // tightest storage class across wh/dc nodes (derived, same math as the util card)
  nodes.filter(n=>n.type==='wh'||n.type==='dc').forEach(n=>{
    const u = nodeStorageUtil(n);
    STORAGE_CLASSES.forEach(c=>{ if(u[c].cap>0 && (!worst || u[c].pct>worst.pct)) worst = { node:n.id, cls:c, pct:u[c].pct }; });
  });
  const recQty = (network.scheduledReceipts||[]).reduce((s,r)=>s+(Number(r.qty)||0),0);
  return (
    <div data-vis="network-decide" style={{display:'flex', alignItems:'center', gap:14, flexWrap:'wrap'}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.08em', color:C.tx3}}>① WHERE DOES MATERIAL FLOW — AND CAN THE NODES HOLD IT?</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}><b className="num" style={{fontFamily:F.disp, color:C.tx}}>{nodes.length}</b> nodes · <b className="num" style={{fontFamily:F.disp, color:C.tx}}>{lanes.length}</b> lanes</span>
      <span style={{color:C.line2}}>·</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>tightest store {worst
        ? <><b className="num" style={{fontFamily:F.disp, color:worst.pct>90?C.dg:C.tx}}>{worst.pct.toFixed(0)}%</b> ({worst.node} · {worst.cls})</>
        : <b style={{color:C.tx3}}>no class caps set</b>}</span>
      <span style={{color:C.line2}}>·</span>
      <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>inbound on open POs <b className="num" style={{fontFamily:F.disp, color:C.tx}}>{recQty.toLocaleString('en-IN')}u</b></span>
      <Provenance kind="derived" style={{padding:'0 4px', fontSize:7.5}}/>
    </div>
  );
}

window.StageNetwork = StageNetwork;
