// ════════════════════════════════════════════════════════════════════════
// sourcing.jsx — Suppliers & Procurement (SupplyTab). Sub-tabs: Suppliers ·
// Incoterms · Landed Cost · Network · Results.  Merges the 2 incoterm cards.
// ════════════════════════════════════════════════════════════════════════
function StageSourcing({ onNav }) {
  const [sub, setSub] = useState('suppliers');
  const tabs = [
    { id:'suppliers', n:'a', label:'Suppliers', count:M.suppliers.length },
    { id:'incoterms', n:'b', label:'Incoterms' },
    { id:'landed',    n:'c', label:'Landed Cost' },
    { id:'network',   n:'d', label:'Network' },
    { id:'results',   n:'e', label:'Results' },
  ];
  return (
    <div>
      <StageHeader n="06" title="Suppliers & Procurement" kicker="Supplier master · OTIF · incoterm responsibility · landed cost · inbound network · PO results"
        right={<Btn kind="secondary">🛃 Import tools</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='suppliers' && <SrcSuppliers/>}
        {sub==='incoterms' && <SrcIncoterms/>}
        {sub==='landed'    && <SrcLanded/>}
        {sub==='network'   && <SrcNetwork onNav={onNav}/>}
        {sub==='results'   && <SrcResults/>}
      </div>
    </div>
  );
}

function SrcSuppliers() {
  const riskC=r=> r==='H'?C.dg:r==='M'?C.a4:C.gn;
  return (
    <Grid cols={1}>
      <Card icon="📋" title="Supplier Master" badge={`${M.suppliers.length} suppliers`} info={{ what:'Supplier directory: lead time, variability, incoterm, spend, risk.', flows:'Suppliers → procurement MILP sourcing.' }}
        dev={{ comp:'SupplierMaster', props:'state.network.suppliers', state:'suppliers[]' }}>
        <DataTable cols={['Code','Supplier','Location','LT','LT CV','Incoterm','Annual Qty','Spend','OTIF','Risk']} align={['left','left','left','right','right','left','right','right','right','left']}
          rows={M.suppliers.map(s=>({cells:[s.code, s.name, s.loc, `${s.lt}d`, `${s.ltCv}%`, <Tag c="w">{s.incoterm}</Tag>, s.qty.toLocaleString('en-IN'), `₹${(s.spend/100000).toFixed(1)}L`, `${s.otif}%`, <Tag c={s.risk==='H'?'r':s.risk==='M'?'a':'g'}>{s.risk}</Tag>]}))}
          foot={['TOTAL','6 suppliers','','','','','35,900','₹85.0L','92.4%','']}/>
      </Card>
      <Card icon="📒" title="OTIF Ledger" badge="on-time-in-full" info={{ what:'Delivery performance: due vs received, in-full check.', flows:'OTIF → supplier risk & control tower.' }}
        dev={{ comp:'OTIFLedgerCard', props:'state.poHistory', state:'sourcing.otif[]' }}>
        <DataTable cols={['PO','Supplier','Due','Received','Qty','OTIF']} align={['left','left','left','left','right','left']}
          rows={M.otifLedger.map(o=>({cells:[o.po, o.sup, o.due, o.got, o.qty, <Tag c={o.otif==='✓'?'g':o.otif==='late'?'a':'r'}>{o.otif}</Tag>]}))}/>
      </Card>
    </Grid>
  );
}

function SrcIncoterms() {
  const who=v=> v==='S'?{l:'SELLER',c:C.ink,t:C.paper}:{l:'BUYER',c:C.ac,t:C.onAc};
  return (
    <Grid cols={1}>
      <Card icon="🛃" title="Incoterm Responsibility Matrix" badge="merged + ref" info={{ what:'Who bears cost & risk at export, main carriage, import per Incoterm.', flows:'Incoterm → landed cost split & risk transfer.' }}
        dev={{ comp:'IncotermMatrix', props:'state.incoterms', note:'Merges matrix + quick-reference (hover) into one.' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
            <thead><tr style={{background:C.ink}}>
              {['Term','Export Clearance','Main Carriage','Import Clearance','Risk Transfer'].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i?'center':'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>{h}</th>)}
            </tr></thead>
            <tbody>
              {M.incoterms.map((t,i)=>(
                <tr key={i} style={{borderTop:`1px solid ${C.line2}`}}>
                  <td style={{padding:'6px 9px', fontWeight:700, fontFamily:F.disp, fontSize:13}}>{t.term}</td>
                  {[t.export,t.main,t.import].map((v,j)=>{ const w=who(v);
                    return <td key={j} style={{padding:'5px 9px', textAlign:'center'}}><span style={{display:'inline-block', minWidth:54, padding:'2px 6px', background:w.c, color:w.t, fontFamily:F.mono, fontSize:8.5, fontWeight:700, border:`1.5px solid ${C.line}`}}>{w.l}</span></td>;
                  })}
                  <td style={{padding:'6px 9px', fontFamily:F.body, fontSize:11, color:C.tx2}}>{t.risk}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{marginTop:10, display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2}}>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:12, height:12, background:C.ink}}/>seller bears</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:12, height:12, background:C.ac}}/>buyer bears</span>
          <span style={{marginLeft:'auto'}}>Incoterms® 2020 · TPAC imports mostly CIF / FOB</span>
        </div>
      </Card>
    </Grid>
  );
}

function SrcLanded() {
  const fmt=n=> n.toLocaleString('en-IN');
  return (
    <Grid cols={2}>
      <Card icon="🛃" title="Landed Cost Rollup" badge="worked example" info={{ what:'Full import cost build-up from FOB to plant gate.', flows:'Landed cost → true unit cost & sourcing decision.' }} span={2}
        dev={{ comp:'LandedCostCard', props:'item, fx, duties', state:'sourcing.landedCost' }}>
        <div style={{fontFamily:F.disp, fontSize:13, fontWeight:700, marginBottom:8}}>{M.landedCost.item}</div>
        <div style={{border:`2px solid ${C.line}`}}>
          {M.landedCost.rows.map((r,i)=>(
            <div key={i} style={{display:'flex', justifyContent:'space-between', padding:'7px 11px', borderTop:i?`1px solid ${C.line2}`:'none',
              background: r.total?C.ink: r.em?C.bg3:C.paper, color: r.total?C.ac:C.tx,
              fontWeight: r.total||r.em?700:400}}>
              <span style={{fontFamily:F.mono, fontSize:11, paddingLeft: r.sub?16:0, color: r.sub?C.tx3: r.total?C.ac:C.tx}}>{r.sub&&'↳ '}{r.k}</span>
              <span className="num" style={{fontFamily:F.disp, fontSize: r.total?16:13, fontWeight:700}}>{r.c==='USD'?'$':'₹'}{fmt(r.v)}</span>
            </div>
          ))}
        </div>
        <div style={{marginTop:10, display:'flex', gap:8}}>
          <Blk label="Landed / unit" value="₹ 1,877" sub="1,500 billets" tone="y"/>
          <Blk label="vs Domestic" value="+12.4%" sub="Sundaram ₹1,670" accent={C.dg}/>
          <Blk label="ITC Recoverable" value="₹ 4.95 L" sub="IGST credit" accent={C.gn}/>
        </div>
      </Card>
    </Grid>
  );
}

function SrcNetwork({ onNav }) {
  return (
    <Grid cols={1}>
      <Card icon="🧭" title="Inbound Network Topology" badge="nodes & lanes" info={{ what:'Physical supplier → plant inbound structure.', flows:'Topology → transport & landed cost.' }}
        right={<button onClick={()=>onNav('logistics')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>full network in Logistics →</button>}
        dev={{ comp:'InboundTopology', props:'state.network.nodes, lanes' }}>
        <svg viewBox="0 0 760 240" style={{width:'100%', height:240, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
          {/* suppliers on left → plant on right */}
          {[['Bharat Forge',40,'Pune'],['Mahindra Steel',95,'Mumbai'],['Sundaram',150,'Coimbatore'],['Jindal',200,'Raigarh'],['POSCO',60,'Korea']].map((s,i)=>{
            const y=30+i*42; return (
              <g key={i}>
                <line x1="180" y1={y} x2="560" y2="120" stroke={C.tx3} strokeWidth={i===4?2:1.2} strokeDasharray={i===4?'4 3':'none'} opacity=".6"/>
                <rect x="20" y={y-13} width="160" height="26" fill={C.bg3} stroke={C.line} strokeWidth="1.5"/>
                <text x="28" y={y+1} fontFamily={F.disp} fontWeight="700" fontSize="10" fill={C.tx}>{s[0]}</text>
                <text x="28" y={y+10} fontFamily={F.mono} fontSize="7.5" fill={C.tx3}>{s[2]}</text>
              </g>
            );
          })}
          <rect x="560" y="96" width="170" height="48" fill={C.ink}/>
          <text x="572" y="118" fontFamily={F.disp} fontWeight="800" fontSize="13" fill={C.ac}>PLANT-CHN</text>
          <text x="572" y="132" fontFamily={F.mono} fontSize="8.5" fill={C.paper}>Chennai · 13.08°N</text>
        </svg>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Dashed = international lane (POSCO, 42d LT). Solid = domestic.</div>
      </Card>
    </Grid>
  );
}

function SrcResults() {
  return (
    <Grid cols={2}>
      <Card icon="📦" title="PO Release Plan" badge="time-phased" info={{ what:'When to release each PO to land on time.', flows:'From procurement MILP; releases to ERP.' }}
        dev={{ comp:'PoReleasePlanCard', props:'solve.procurement.poPlan' }}>
        <DataTable dense cols={['PO','Part','Supplier','Qty','Release','Value']} align={['left','left','left','right','left','right']}
          rows={M.poRegister.map(p=>[p.po, p.part, p.sup, p.qty.toLocaleString('en-IN'), p.wk, `₹${(p.val/1000).toFixed(0)}K`])}/>
      </Card>
      <Card icon="⚠" title="Shortage Forecast" badge="2 risks" badgeTone="k" info={{ what:'Projected stockouts before next receipt.', flows:'Shortages → expedite or safety adjust.' }}
        dev={{ comp:'ShortageForecastCard', props:'inventoryProjection' }}>
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          {[['RM-BRG18','W17','−240 kg','POSCO LT slip',C.dg],['CN-SEAL9','W21','−180 u','MOQ timing',C.a4]].map((r,i)=>(
            <div key={i} style={{border:`2px solid ${C.line}`, padding:'8px 10px', borderLeft:`5px solid ${r[4]}`}}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                <span style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>{r[0]}</span>
                <Tag c="r">{r[2]} @ {r[1]}</Tag>
              </div>
              <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:3}}>cause: {r[3]}</div>
            </div>
          ))}
        </div>
        <div style={{marginTop:10}}><Btn kind="danger" sm>⚡ Expedite both</Btn></div>
      </Card>
    </Grid>
  );
}
window.StageSourcing = StageSourcing;
