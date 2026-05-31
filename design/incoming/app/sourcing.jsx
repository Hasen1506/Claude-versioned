// ════════════════════════════════════════════════════════════════════════
// sourcing.jsx — Sourcing (stage 07, handoff v2 §3.07). 0 sub-tabs guided
// scroll under the item selector. PER-PART lens: set the selector to "its
// parts" to see that part's MRP, supplier, inbound lane and landed cost.
// Supplier master now lives in Network (03); Sourcing consumes it.
// ════════════════════════════════════════════════════════════════════════
function StageSourcing({ onNav }) {
  const { item, view } = useActiveItem();
  return (
    <div>
      <StageHeader n="07" title="Suppliers & Procurement" kicker="Per-part MRP · incoterm responsibility · landed cost · PO release — for the parts of the selected product"
        right={<Btn kind="secondary">🛃 Import tools</Btn>}/>
      <ItemSelector/>
      <div style={{padding:18}}>
        <SrcMRP item={item} view={view} onNav={onNav}/>
        <SrcIncoterms/>
        <SrcLanded onNav={onNav}/>
        <SrcResults/>
      </div>
    </div>
  );
}

// per-part MRP lens — answers "which subproduct am I looking at and its flow"
function SrcMRP({ item, view, onNav }) {
  const [pi, setPi] = useState(0);
  const part = M.bom[pi];
  const lane = M.lanes.find(l=>l.item===part.part);
  const sup = M.suppliers.find(s=>s.code===part.sup) || {};
  const backupMap = { 'RM-STL42':'SUP-018', 'RM-BRG18':'SUP-024', 'CN-SEAL9':'SUP-031', 'CN-BLT04':'SUP-012', 'CN-LUB02':'SUP-031' };
  const backup = M.suppliers.find(s=>s.code===backupMap[part.part]) || {};
  const wk = M.periods.slice(0,8);
  // synthesize MRP rows for the part
  const gross = [0,0,1200,0,900,0,1100,0];
  const sched = [800,0,0,0,0,0,0,0];
  let oh = 1400; const onhand=[], net=[], po=[];
  gross.forEach((g,i)=>{ oh = oh + (sched[i]||0) - g; onhand.push(oh); const n = oh<part.S? part.S-oh:0; net.push(n>0?part.S-Math.max(oh,0):0);
    const planned = n>0? Math.ceil((part.S-oh)/part.moq)*part.moq : 0; po.push(planned); if(planned) oh+=planned; });
  return (
    <StageSection step="1" title="Per-Part MRP" sub={`set the selector to "its parts" — gross → net → planned PO on the period axis, with this part's supplier and inbound lane`}>
      <Card icon="🧩" title="Parts of the selected product" badge={`${M.bom.length} parts`} badgeTone="y"
        info={{ what:'Pick a part to explode its MRP, supplier, lane and landed cost.', flows:'Net requirements → procurement MILP.' }}
        dev={{ comp:'MRPLens', props:'activeItem.parts, mrp', state:'sourcing.mrp[part][period]' }}>
        <div style={{display:'flex', gap:0, overflowX:'auto', border:`2px solid ${C.line}`, marginBottom:12}}>
          {M.bom.map((b,i)=>(
            <button key={b.part} onClick={()=>setPi(i)} style={{flexShrink:0, padding:'7px 11px', border:'none', borderRight:`1px solid ${C.line2}`, cursor:'pointer', textAlign:'left',
              background: pi===i?C.ac:'transparent', color:C.tx, minWidth:130}}>
              <div style={{fontFamily:F.mono, fontSize:10, fontWeight:700}}>{b.part}</div>
              <div style={{fontFamily:F.disp, fontSize:10.5, fontWeight:600, whiteSpace:'nowrap'}}>{b.name}</div>
            </button>
          ))}
        </div>
        <div style={{display:'flex', gap:8, marginBottom:10, flexWrap:'wrap'}}>
          <Tag c="k">{part.part}</Tag><Tag c="w">qty/u {part.qty}</Tag><Tag c="w">LT {part.lt}d</Tag>
          <Tag c="w">supplier {sup.name||part.sup}</Tag>
          {backup.name && <Tag c="a">backup {backup.name} · LT {backup.lt}d</Tag>}
          {lane && <Tag c="b">{lane.from}→{lane.to} · {lane.mode}</Tag>}
        </div>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
            <thead><tr style={{background:C.ink}}>
              <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9}}>MRP ROW</th>
              {wk.map(w=><th key={w.id} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{w.label}</th>)}
            </tr></thead>
            <tbody>
              {[['Gross req', gross, C.tx],['Sched receipts', sched, C.gn],['Proj on-hand', onhand, C.tx2],['Planned PO', po, C.ac]].map(([lbl,arr,col],ri)=>(
                <tr key={ri} style={{borderTop:`1px solid ${C.line2}`, background: ri===3?C.bg3:C.paper}}>
                  <td style={{padding:'5px 9px', fontWeight:700, color:col}}>{lbl}</td>
                  {arr.map((v,i)=><td key={i} className="num" style={{textAlign:'right', padding:'5px 9px', fontWeight: ri===3?700:400}}>{v||'·'}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Reading formula="net = max(0, gross − on-hand − scheduled)   ·   planned PO = ⌈net / MOQ⌉ × MOQ, offset by LT"
          soWhat={`This part reorders in MOQ-${part.moq.toLocaleString('en-IN')} lots from ${sup.name||part.sup}; its ${part.lt}-day lead offsets the release earlier than the need.`}/>
      </Card>
    </StageSection>
  );
}

function SrcIncoterms() {
  const who=v=> v==='S'?{l:'SELLER',c:C.ink,t:C.paper}:{l:'BUYER',c:C.ac,t:C.onAc};
  return (
    <StageSection step="2" title="Incoterms" sub="who bears cost & risk at each step">
      <Card icon="🛃" title="Incoterm Responsibility Matrix" badge="merged + ref"
        info={{ what:'Who bears cost & risk at export, main carriage, import per Incoterm.', flows:'Incoterm → landed cost split & risk transfer.' }}
        dev={{ comp:'IncotermMatrix', props:'state.incoterms' }}>
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
    </StageSection>
  );
}

function SrcLanded({ onNav }) {
  const { gate } = useProfile();
  const fmt=n=> n.toLocaleString('en-IN');
  if(gate.landed) return (
    <StageSection step="3" title="Landed Cost" sub="domestic-only — no import cost build-up needed">
      <GateNote onNav={onNav}>Your profile has <b>no imports</b>, so landed cost, FX and incoterms don’t apply — all sourcing is domestic at quoted price.</GateNote>
    </StageSection>
  );
  return (
    <StageSection step="3" title="Landed Cost" sub="full FOB → plant-gate build-up for an imported part">
      <Card icon="🛃" title="Landed Cost Rollup" badge="worked example"
        info={{ what:'Full import cost build-up from FOB to plant gate.', flows:'Landed cost → true unit cost & sourcing decision.' }}
        dev={{ comp:'LandedCostCard', props:'item, fx, duties' }}>
        <div style={{fontFamily:F.disp, fontSize:13, fontWeight:700, marginBottom:8}}>{M.landedCost.item}</div>
        <div style={{border:`2px solid ${C.line}`}}>
          {M.landedCost.rows.map((r,i)=>(
            <div key={i} style={{display:'flex', justifyContent:'space-between', padding:'7px 11px', borderTop:i?`1px solid ${C.line2}`:'none',
              background: r.total?C.ink: r.em?C.bg3:C.paper, color: r.total?C.ac:C.tx, fontWeight: r.total||r.em?700:400}}>
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
        <Reading formula="landed = CIF + BCD + SWS + clearing + inland (IGST recoverable as ITC)"
          soWhat="Imported POSCO billet lands 12.4% above Sundaram domestic — only worth it when Sundaram can't cover the volume."/>
      </Card>
    </StageSection>
  );
}

function SrcResults() {
  return (
    <StageSection step="4" title="Release & Shortages" sub="time-phased PO releases and projected stockouts">
      <Grid cols={2}>
        <Card icon="📦" title="PO Release Plan" badge="time-phased" info={{ what:'When to release each PO to land on time.', flows:'From procurement MILP; releases to ERP.' }}
          dev={{ comp:'PoReleasePlanCard', props:'solve.procurement.poPlan' }}>
          <DataTable dense cols={['PO','Part','Supplier','Qty','Release','Value']} align={['left','left','left','right','left','right']}
            rows={M.poRegister.map(p=>[p.po, p.part, p.sup, p.qty.toLocaleString('en-IN'), p.wk, `₹${(p.val/1000).toFixed(0)}K`])}/>
        </Card>
        <Card icon="⚠" title="Shortage Forecast" badge="2 risks" badgeTone="k" info={{ what:'Projected stockouts before next receipt.', flows:'Shortages → expedite or safety adjust.' }}
          dev={{ comp:'ShortageForecastCard', props:'inventoryProjection' }}>
          <div style={{display:'flex', flexDirection:'column', gap:8}}>
            {[['RM-BRG18',M.pLabel(11),'−240 kg','POSCO LT slip',C.dg],['CN-SEAL9',M.pLabel(15),'−180 u','MOQ timing',C.a4]].map((r,i)=>(
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
    </StageSection>
  );
}
window.StageSourcing = StageSourcing;
