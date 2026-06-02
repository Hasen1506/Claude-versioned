// ════════════════════════════════════════════════════════════════════════
// sourcing.jsx — Sourcing (stage 07, handoff v2 §3.07). 0 sub-tabs guided
// scroll under the item selector. PER-PART lens: set the selector to "its
// parts" to see that part's MRP, supplier, inbound lane and landed cost.
// Supplier master now lives in Network (03); Sourcing consumes it.
// ════════════════════════════════════════════════════════════════════════
// Procurement MILP payload — the selected FG's demand series (the keystone the
// Demand forecast wrote) exploded through the shared BOM. Period length converts
// the parts' day-leads to periods. Capacity set comfortably above peak demand.
function procurementPayload(sku, planning, serviceLevel){
  const grain = planning.timeGrain==='week'?'weekly':planning.timeGrain==='day'?'daily':'monthly';
  const pd = planning.timeGrain==='week'?7:planning.timeGrain==='day'?1:30;
  const dem = getItemDemand(sku, 12);
  const p = (M.products||[]).find(x=>x.sku===sku) || {};
  const cap = Math.max(400, Math.ceil(Math.max(...dem) * 1.5));
  return { products:[{ name:sku, demand:dem, capacity:cap,
    variable_cost:p.cost||1190, sell_price:p.price||1850, yield_pct:p.yield||0.97, parts:bomParts(pd) }],
    params:{ periods:12, time_grain:grain, service_level: serviceLevel } };
}
// effective service level: the user's governed override, else the 0.95 default.
function effServiceLevel(config){
  const o = config && config.serviceLevelOverride;
  return (o!=null && o!=='') ? Number(o) : 0.95;
}
function StageSourcing({ onNav }) {
  const { item, view } = useActiveItem();
  const { planning } = usePlanning();
  const { config, setConfig } = useConfig();
  const sku = (item&&item.code)||'TPA-4471';
  const sl = effServiceLevel(config);
  const proc = useSolve('/api/solve/procurement', ()=>procurementPayload(sku, planning, sl));
  // W0·P1.b — recompute DAG: a fresh solve clears the stale flag; editing demand
  // (or any SOLVE_DEPS source — incl. the service level below) re-flags it so the
  // StaleMark appears. W0·P3 — the service level is a GOVERNED input (SolverInput).
  const { stale, ranAt } = useStale('procurement');
  const runProc = ()=> proc.run().then(d=>{ markSolved('procurement'); return d; }).catch(()=>{});
  return (
    <div>
      <StageHeader n="07" title="Suppliers & Procurement" kicker="Per-part MRP · incoterm responsibility · landed cost · PO release — for the parts of the selected product"
        right={<Btn kind="accent" onClick={runProc}>{proc.solving?'⏳ Planning…':'⚡ Run procurement'}</Btn>}/>
      <ItemSelector/>
      <StageContext item={item} asOf={ranAt ? ranAt.toLocaleString('en-IN') : null} stale={stale}/>
      <div style={{padding:18}}>
        {stale && <StaleMark since="(demand or cost inputs changed)" onNav={()=>runProc()} go="rerun"/>}
        {proc.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Procurement MILP: {proc.error}</div>}
        <StageSection step="0" title="Solver Parameters" sub="governed inputs — a seed default until you override it; an override re-flags the plan to re-solve">
          <Card icon="🎛️" title="Procurement MILP inputs" badge="governed" badgeTone="y"
            info={{ what:'The service level sets the cycle-service target the MILP sizes safety stock to. Seeded at 0.95; override per run.', flows:'→ procurement MILP params.service_level.' }}
            dev={{ comp:'SolverInput', props:'config.serviceLevelOverride', state:'config.serviceLevelOverride (seed 0.95)' }}>
            <Grid cols={3}>
              <SolverInput label="Service level (α)" seed={0.95} value={config.serviceLevelOverride}
                onChange={v=>setConfig({ serviceLevelOverride:v })} min={0.5} max={0.999}
                hint="cycle-service target → safety stock"/>
            </Grid>
            <Reading formula="safety stock = z(α) · σ_LTD   ·   higher α ⇒ more buffer, fewer stockouts, more capital tied up"
              soWhat={`The MILP is currently planning to α = ${sl} ${(config.serviceLevelOverride!=null && config.serviceLevelOverride!=='')?'(your override)':'(default)'}. Change it and re-run — the safety buffer and PO release schedule shift (a tighter α consolidates releases to keep cover).`}/>
          </Card>
        </StageSection>
        <SrcMRP item={item} view={view} onNav={onNav} proc={proc}/>
        <SrcIncoterms/>
        <SrcLanded onNav={onNav}/>
        <SrcResults proc={proc}/>
      </div>
    </div>
  );
}

// per-part MRP lens — answers "which subproduct am I looking at and its flow"
function SrcMRP({ item, view, onNav, proc }) {
  const [pi, setPi] = useState(0);
  const part = M.bom[pi];
  // real MILP material plan for THIS part (same row order as M.bom via bomParts)
  const mat = proc && proc.result && (proc.result.materials||[])[pi];
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
        {mat && (
          <div style={{marginTop:12, border:`2px solid ${C.gn}`, background:C.bg3, padding:'9px 11px'}}>
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:6}}>
              <span style={{fontFamily:F.disp, fontWeight:800, fontSize:12, color:C.gn}}>✓ MILP planned orders for {part.name}</span>
              <Provenance kind="solved" asOf={proc.ranAt}/>
            </div>
            <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx, lineHeight:1.7}}>
              {mat.num_orders} PO{mat.num_orders===1?'':'s'} · <b>{mat.total_ordered.toLocaleString('en-IN')}</b> units total · ₹{(mat.total_cost/1000).toFixed(0)}K material spend
              {(mat.purchase_orders||[]).length>0 && <> · first release P{mat.purchase_orders[0].period} → arrives P{mat.purchase_orders[0].arrive_period}</>}
            </div>
            <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, marginTop:4}}>
              The synthetic table above teaches the gross→net→PO mechanic; these are the actual joint-MILP releases for this part on the selected item's forecast.
            </div>
          </div>
        )}
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

// Landed-cost worked example (POSCO billet) — drives the real /api/calc/landed-cost
// payload. Echoed input rows (FOB/FX) + duty constants pending a per-import inputs card.
const LANDED_INPUTS = { fobUsd:28500, fx:84.20, freight:124000, insurancePct:0.5,
  bcdPct:7.5, swsPct:10, igstPct:18, cha:28000, inland:42000, qty:1500, domesticUnit:1670 };
// Build the FOB→plant-gate rollup rows from the solver response (same shape the
// mock used: {k,v,c,em?,sub?,total?}); FOB/FX echoed from the inputs we sent.
function landedRows(res, inp){
  return [
    { k:'FOB Price (USD)', v:inp.fobUsd, c:'USD' },
    { k:`FX @ ₹${inp.fx.toFixed(2)}/$`, v:Math.round(inp.fobUsd*inp.fx), c:'INR' },
    { k:'Ocean Freight', v:inp.freight, c:'INR' },
    { k:`Insurance @ ${inp.insurancePct}%`, v:Math.round(inp.fobUsd*inp.fx*inp.insurancePct/100), c:'INR' },
    { k:'CIF Value', v:Math.round(res.assessable_value), c:'INR', em:true },
    { k:`Basic Customs Duty ${res.bcd_pct}%`, v:Math.round(res.bcd), c:'INR' },
    { k:`Social Welfare ${inp.swsPct}%`, v:Math.round(res.sws), c:'INR' },
    { k:`IGST ${res.igst_pct}% (ITC)`, v:Math.round(res.igst), c:'INR', sub:true },
    { k:'Clearing · CHA', v:res.cha_charges, c:'INR' },
    { k:'Inland to Plant', v:res.local_transport, c:'INR' },
    { k:'LANDED COST', v:Math.round(res.net_landed), c:'INR', total:true },
  ];
}
function SrcLanded({ onNav }) {
  const { gate } = useProfile();
  const i = LANDED_INPUTS;
  const land = useSolve('/api/calc/landed-cost', ()=>({
    foreign_value:i.fobUsd, exchange_rate:i.fx, freight:i.freight, insurance_pct:i.insurancePct,
    bcd_pct:i.bcdPct, sws_pct:i.swsPct, igst_pct:i.igstPct,
    cha_charges:i.cha, port_handling:0, local_transport:i.inland, gst_registered:true,
  }));
  const res = land.result;
  const fmt=n=> n.toLocaleString('en-IN');
  if(gate.landed) return (
    <StageSection step="3" title="Landed Cost" sub="domestic-only — no import cost build-up needed">
      <GateNote onNav={onNav}>Your profile has <b>no imports</b>, so landed cost, FX and incoterms don’t apply — all sourcing is domestic at quoted price.</GateNote>
    </StageSection>
  );
  const rows = res ? landedRows(res, i) : M.landedCost.rows;
  // derived footer blocks (real when solved)
  const unit    = res ? res.net_landed / i.qty : 1877;
  const vsDom   = ((unit - i.domesticUnit) / i.domesticUnit) * 100;
  const itc     = res ? res.itc_recovery : 495000;
  return (
    <StageSection step="3" title="Landed Cost" sub="full FOB → plant-gate build-up for an imported part">
      <Card icon="🛃" title="Landed Cost Rollup" badge={res?'solved':'worked example'} badgeTone={res?'g':undefined}
        right={res ? <Provenance kind="solved" asOf={land.ranAt}/> : <Btn kind="accent" sm onClick={()=>land.run().catch(()=>{})}>{land.solving?'⏳ Computing…':'🛃 Compute landed cost'}</Btn>}
        info={{ what:'Full import cost build-up from FOB to plant gate.', flows:'Landed cost → true unit cost & sourcing decision.' }}
        dev={{ comp:'LandedCostCard', props:'item, fx, duties' }}>
        {land.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>landed-cost error: {land.error}</div>}
        <div style={{fontFamily:F.disp, fontSize:13, fontWeight:700, marginBottom:8}}>{M.landedCost.item}</div>
        <div style={{border:`2px solid ${C.line}`}}>
          {rows.map((r,idx)=>(
            <div key={idx} style={{display:'flex', justifyContent:'space-between', padding:'7px 11px', borderTop:idx?`1px solid ${C.line2}`:'none',
              background: r.total?C.ink: r.em?C.bg3:C.paper, color: r.total?C.ac:C.tx, fontWeight: r.total||r.em?700:400}}>
              <span style={{fontFamily:F.mono, fontSize:11, paddingLeft: r.sub?16:0, color: r.sub?C.tx3: r.total?C.ac:C.tx}}>{r.sub&&'↳ '}{r.k}</span>
              <span className="num" style={{fontFamily:F.disp, fontSize: r.total?16:13, fontWeight:700}}>{r.c==='USD'?'$':'₹'}{fmt(r.v)}</span>
            </div>
          ))}
        </div>
        <div style={{marginTop:10, display:'flex', gap:8}}>
          <Blk label="Landed / unit" value={`₹ ${fmt(Math.round(unit))}`} sub={`${fmt(i.qty)} billets`} tone="y"/>
          <Blk label="vs Domestic" value={`${vsDom>=0?'+':''}${vsDom.toFixed(1)}%`} sub={`Sundaram ₹${fmt(i.domesticUnit)}`} accent={vsDom>=0?C.dg:C.gn}/>
          <Blk label="ITC Recoverable" value={`₹ ${(itc/1e5).toFixed(2)} L`} sub="IGST credit" accent={C.gn}/>
        </div>
        <Reading formula="landed = CIF + BCD + SWS + clearing + inland (IGST recoverable as ITC)"
          soWhat={`Imported POSCO billet lands ${vsDom.toFixed(1)}% ${vsDom>=0?'above':'below'} Sundaram domestic — only worth it when Sundaram can't cover the volume.`}/>
      </Card>
    </StageSection>
  );
}

function SrcResults({ proc }) {
  const res = proc && proc.result;
  // Flatten every part's purchase_orders into one PO register; derive shortages
  // from the FG product result (periods where unmet demand is projected).
  let poRows = null, shortages = null;
  if(res){
    poRows = [];
    (res.materials||[]).forEach((m,mi)=>{ (m.purchase_orders||[]).forEach((po,pi)=>{
      poRows.push([`PO-${String(mi+1).padStart(2,'0')}${pi+1}`, m.name, m.supplier_name||'—',
        po.quantity.toLocaleString('en-IN'), `P${po.period}→${po.arrive_period}`, `₹${(po.cost/1000).toFixed(0)}K`]);
    }); });
    const fg = (res.products||[])[0] || {};
    shortages = (fg.shortages||[]).map((q,t)=>({t,q})).filter(s=>s.q>0.5);
  }
  return (
    <StageSection step="4" title="Release & Shortages" sub="time-phased PO releases and projected stockouts">
      <Grid cols={2}>
        <Card icon="📦" title="PO Release Plan" badge={res?`${poRows.length} POs · solved`:'time-phased'} badgeTone={res?'g':undefined}
          right={res ? <Provenance kind="solved" asOf={proc.ranAt}/> : undefined}
          info={{ what:'When to release each PO to land on time.', flows:'From procurement MILP; releases to ERP.' }}
          dev={{ comp:'PoReleasePlanCard', props:'solve.procurement.poPlan' }}>
          <DataTable dense cols={['PO','Part','Supplier','Qty','Release→Arrive','Value']} align={['left','left','left','right','left','right']}
            rows={res ? (poRows.length?poRows:[['—','no orders in horizon','—','—','—','—']])
                      : M.poRegister.map(p=>[p.po, p.part, p.sup, p.qty.toLocaleString('en-IN'), p.wk, `₹${(p.val/1000).toFixed(0)}K`])}/>
          {res && <Reading formula="release period = need period − lead time   ·   lot = ⌈net/MOQ⌉ × MOQ"
            soWhat={`The MILP placed ${poRows.length} POs to keep ${(res.products||[])[0]?.name||'the FG'} at 100% fill — long-lead parts release earliest.`}/>}
        </Card>
        <Card icon="⚠" title="Shortage Forecast" badge={res?(shortages.length?`${shortages.length} risks`:'no shortage'):'2 risks'} badgeTone="k"
          right={res ? <Provenance kind="solved" asOf={proc.ranAt}/> : undefined}
          info={{ what:'Projected stockouts before next receipt.', flows:'Shortages → expedite or safety adjust.' }}
          dev={{ comp:'ShortageForecastCard', props:'inventoryProjection' }}>
          {res ? (
            shortages.length ? (
              <div style={{display:'flex', flexDirection:'column', gap:8}}>
                {shortages.map((s,i)=>(
                  <div key={i} style={{border:`2px solid ${C.line}`, padding:'8px 10px', borderLeft:`5px solid ${C.dg}`}}>
                    <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                      <span style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>{(res.products||[])[0]?.name}</span>
                      <Tag c="r">−{Math.round(s.q).toLocaleString('en-IN')} u @ P{s.t}</Tag>
                    </div>
                    <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:3}}>cause: capacity / lead-time binds this period</div>
                  </div>
                ))}
              </div>
            ) : <div style={{padding:'10px 11px', border:`2px solid ${C.gn}`, background:C.bg3, fontFamily:F.mono, fontSize:11, color:C.gn}}>✓ No projected shortage — every period's demand is met from plan + safety stock.</div>
          ) : (
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
          )}
          {!res && <div style={{marginTop:10}}><Btn kind="danger" sm>⚡ Expedite both</Btn></div>}
        </Card>
      </Grid>
    </StageSection>
  );
}
window.StageSourcing = StageSourcing;
