// ════════════════════════════════════════════════════════════════════════
// products.jsx — Products (stage 02, handoff v2 §3.02). Adds the missing
// "Define Products" first screen; guided flow Define → BOM → Costs → Policy
// → MTO under the persistent item selector (0 sub-tabs). Inventory policy is
// DERIVED (formulas shown). Cycle/Line MOVED to Production. Events period-aware.
// ════════════════════════════════════════════════════════════════════════
function StageProducts({ onNav }) {
  const { item } = useActiveItem();
  const p = M.products.find(x=>x.sku===(item&&item.id)) || M.products[0];
  return (
    <div>
      <StageHeader n="02" title="Products" kicker="Step 1 — tell us what you make. Then its bill of materials, costs, and the inventory policy we derive."
        right={<ModelIO/>}/>
      <ItemSelector/>
      <div style={{padding:18}}>
        <ProdDefine/>
        <ProdYieldExpiry p={p}/>
        <ProdBOM p={p}/>
        <ProdCosts p={p}/>
        <ProdPolicy p={p}/>
        <ProdMTO/>
      </div>
    </div>
  );
}

// ── NEW first screen — the catalog the prototype assumed existed ──
function ProdDefine() {
  useMasterRev();   // re-render when yield/shelf/salvage are edited or a product is added
  const { setItem } = useActiveItem();
  const onAdd = ()=>{ const np=addProduct(); if(np) setItem(np.sku); };   // select the new SKU so the flow has something to edit
  // make/mode/target-margin/lifecycle are catalog attributes (static seed — not
  // computed). Weight & volume are NO LONGER duplicated here: they read the single
  // store authority (skuWeightKg/skuVolM3), the same source Logistics tonnage and
  // Network storage utilisation use — so one SKU has one weight, one volume.
  const ex = {
    'TPA-4471':{ make:'Make', mode:'MTS', tgt:36, life:'Maturity' },
    'TPA-3215':{ make:'Make', mode:'MTS', tgt:38, life:'Growth' },
    'TPA-9904':{ make:'Make', mode:'MTO', tgt:36, life:'Maturity' },
    'TPA-2188':{ make:'Make', mode:'MTO', tgt:33, life:'Maturity' },
    'TPA-5540':{ make:'Make', mode:'ATO', tgt:32, life:'Growth' },
    'TPA-7722':{ make:'Buy', mode:'MTO', tgt:31, life:'Decline' },
  };
  return (
    <StageSection step="1" title="Define Products" sub="one row per finished good — a new user starts HERE, adds a product, then the selector has something to select">
      <Card icon="🏭" title="Finished-Goods Catalog" badge={`${M.items.length} products`} badgeTone="y"
        info={{ what:'The catalog of what you make: identity, commercials, physical attributes, lifecycle.', flows:'Defines the items every downstream stage filters to.' }}
        dev={{ comp:'DefineProductsCard', props:'state.products', state:'products[] {make,mode,price,margin,wt,vol,shelf,life}' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              {['Code','Name','Family','UoM','Make/Buy','Mode','Sell ₹','Tgt %','Wt kg','Vol m³','Shelf','Yield','Lifecycle','Method','Status'].map((h,i)=>(
                <th key={i} style={{color:C.paper, textAlign:i<2?'left':'right', padding:'6px 8px', fontSize:8.5, letterSpacing:'.04em', textTransform:'uppercase', whiteSpace:'nowrap'}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {M.products.filter(p=>p.cat==='Finished').map((p,ri)=>{ const e=ex[p.sku]||{};
                return (
                  <tr key={p.sku} style={{borderTop:`1px solid ${C.line2}`, background: ri%2?C.bg3:C.paper}}>
                    <td style={{padding:'5px 8px', fontWeight:700}}>{p.sku}</td>
                    <td style={{padding:'5px 8px', fontWeight:600, whiteSpace:'nowrap'}}>{p.name}</td>
                    <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>{(M.itemById(p.sku)||{}).family}</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>unit</td>
                    <td style={{padding:'5px 8px', textAlign:'right'}}><Tag c={e.make==='Buy'?'a':'w'}>{e.make}</Tag></td>
                    <td style={{padding:'5px 8px', textAlign:'right'}}><Tag c={e.mode==='MTO'?'v':'w'}>{e.mode}</Tag></td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right', fontWeight:700}}>{p.price}</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{e.tgt}%</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{skuWeightKg(p.sku)}</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{skuVolM3(p.sku)}</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{p.shelf}d</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{Math.round((Number(p.yield)||0.95)*100)}%</td>
                    <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>{e.life}</td>
                    <td style={{padding:'5px 8px', textAlign:'right'}}><MethodTag sku={p.sku}/></td>
                    <td style={{padding:'5px 8px', textAlign:'right'}}><Tag c="g">active</Tag></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{marginTop:10, display:'flex', gap:8}}>
          <Btn kind="primary" sm onClick={onAdd}>+ Add product</Btn>
          <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, alignSelf:'center'}}>adds a finished SKU (template defaults · zero demand) and selects it · weight & volume drive storage utilization on Network · shelf-life gates lot policy · target margin is a goal — actual mix is an output of Profit-mix, never typed here</span>
        </div>
      </Card>
    </StageSection>
  );
}

// ── (R14) Editable yield-loss & expiry parameters for the SELECTED item. These are
// the solvers' REAL levers (procurement effective_qty, profit-mix/MC expiry write-off)
// that were previously buried JS constants. The discipline (per the input audit):
// yield biases EVERY solve, so it leads; salvage + shelf only change cost when expiry
// actually occurs (shelf < horizon), so they're flagged honestly, not hidden.
function ProdYieldExpiry({ p }){
  useMasterRev();
  const { planning } = usePlanning();
  const T = planning.horizonLength || 52;
  const shelfWk = Math.max(1, Math.round((Number(p.shelf)||365)/7));
  const expires = shelfWk < T;     // expiry only bites inside the horizon
  return (
    <StageSection step="1a" title={`Yield & expiry · ${p.name}`} sub="the real solver levers — what fraction comes out good, and what happens to stock that ages out">
      <Card icon="⚗️" title="Yield-loss & expiry parameters" badge="drives the solvers" badgeTone="y"
        right={<Provenance kind="input"/>}
        info={{ what:'Yield = good units per unit started (grosses up material + capacity everywhere). Shelf-life gates expiry write-offs; salvage = fraction of make-cost recovered when expired/excess stock is scrapped.', flows:'→ procurement effective_qty=qty·(1+scrap)/yield · profit-mix & Monte-Carlo expiry write-off.' }}
        dev={{ comp:'ProdYieldExpiry', props:'editProductAttr(sku,…)', state:'M.products[sku].{yield,shelf,salvage}' }}>
        <Grid cols={3} gap={10}>
          <Field label="Yield % (good units / started)">
            <NumInput value={Math.round((Number(p.yield)||0.95)*1000)/10} suffix="%"
              onChange={(v)=>editProductAttr(p.sku, { yield: Math.min(1, Math.max(0.01, Number(v)/100)) })}/>
          </Field>
          <Field label="Shelf-life (days)">
            <NumInput value={p.shelf} suffix="d"
              onChange={(v)=>editProductAttr(p.sku, { shelf: Math.max(1, Number(v)||1) })}/>
          </Field>
          <Field label="Salvage % of make-cost">
            <NumInput value={Math.round((Number(p.salvage)||0.8)*100)} suffix="%"
              onChange={(v)=>editProductAttr(p.sku, { salvage: Math.min(1, Math.max(0, Number(v)/100)) })}/>
          </Field>
        </Grid>
        <Reading formula={`shelf ${shelfWk} wk vs horizon ${T} wk → expiry ${expires?'ACTIVE':'inactive'}`}
          soWhat={expires
            ? `This SKU's stock ages out inside the plan, so salvage % is a live lever: lower salvage raises the write-off the optimiser pays on excess/expired units. Re-run Profit-mix / Monte-Carlo to see it move.`
            : `Shelf-life ≥ horizon, so nothing expires within the plan — salvage % is inert for this SKU at the current horizon (honest: it only bites if you shorten shelf-life below ${T} weeks or lengthen the horizon). Yield still drives every solve.`}/>
      </Card>
    </StageSection>
  );
}

function ProdBOM({ p }) {
  useMasterRev();
  const c = M.contracts.find(x=>x.item==='RM-STL42');
  return (
    <StageSection step="2" title={`Bill of Materials · ${p.name}`} sub="physical structure + commercial terms (time-varying contract price, supplier from Network master)">
      <Card icon="🔧" title="Bill of Materials" badge={`${M.bom.length} parts`}
        info={{ what:'Parts, qty/unit, cost, lead time + commercial ordering terms.', flows:'Explodes into MRP & procurement MILP demand.' }}
        dev={{ comp:'BOMEditor', props:'prod, state.products[].bom', state:'products[id].bom[]' }}>
        <SubLabel right={<span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>primary fields</span>}>Physical structure</SubLabel>
        <DataTable cols={['Part','Component','Qty/u','Unit Cost','Lead Time']} align={['left','left','right','right','right']}
          rows={M.bom.map(b=>[b.part, b.name, b.qty, `₹${b.cost}`, `${b.lt}d`])}
          foot={['TOTAL', '5 parts', '', `₹${M.bom.reduce((s,b)=>s+b.cost*b.qty,0).toFixed(0)}/u`, '']}/>
        <Advanced label="Commercial & ordering terms" count={6}>
          <DataTable cols={['Part','MOQ','Ordering S','Holding %','Contract Price','Supplier']} align={['left','right','right','right','right','left']}
            rows={M.bom.map(b=>{ const ct=M.contracts.find(x=>x.item===b.part);
              return [b.part, b.moq.toLocaleString('en-IN'), `₹${b.S}`, `${b.hold}%`, ct?`₹${ct.rateByPeriod[0][1]}→₹${ct.rateByPeriod[ct.rateByPeriod.length-1][1]}`:`₹${b.cost}`, b.sup];
            })}/>
          <Reading formula="commercial price = contract.rateByPeriod[t] (Network)" soWhat="Steel steps from ₹142 to ₹151 at W29 — the procurement MILP times buys around it."/>
          <SubLabel right={<span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>per-part · distinct from product yield</span>}>Conversion scrap (material lost)</SubLabel>
          <div style={{display:'flex', flexWrap:'wrap', gap:10}}>
            {M.bom.map(b=>(
              <Field key={b.part} label={`${b.part} scrap %`}>
                <NumInput value={Math.round((Number(b.scrap)||0.01)*1000)/10} suffix="%" w={92}
                  onChange={(v)=>editPartAttr(b.part, { scrap: Math.min(0.5, Math.max(0, Number(v)/100)) })}/>
              </Field>
            ))}
          </div>
          <Reading formula="effective material = qty · (1 + scrap) / yield  (procurement.py)"
            soWhat="Scrap is the fraction of THIS part's material lost in conversion (chips, offcuts) — separate from product yield, which is the fraction of finished units that come out good. Both gross up what procurement must buy."/>
        </Advanced>
      </Card>
    </StageSection>
  );
}

function ProdCosts({ p }) {
  // Material is now genuinely DERIVED from the BOM (Σ qty·cost), not a fake 70% of cost.
  // Setup + labour are editable + persisted; "conversion & overhead" is the residual
  // that reconciles the rollup to the item's standard cost at seed, then floats as you edit.
  const lot = p.moq || 100;
  const bomMaterial = M.bom.reduce((s,b)=>s + b.qty*b.cost, 0);
  const seedLabour = Math.round(p.cost*0.18);
  const { costs, setCosts } = useProductCosts(p.sku, { setupCost:4200, laborPerUnit:seedLabour });
  const setupAmort = (Number(costs.setupCost)||0) / lot;
  const seedSetupAmort = 4200 / lot;
  // fixed conversion/overhead the BOM doesn't capture (machine time, energy, QA, margin to std cost)
  const conversion = Math.max(0, p.cost - bomMaterial - seedLabour - seedSetupAmort);
  const labour = Number(costs.laborPerUnit)||0;
  const total = bomMaterial + labour + setupAmort + conversion;
  const cm = Math.round((1 - total/p.price)*100);
  return (
    <StageSection step="3" title="Costs" sub="setup + labour, the unit-cost rollup, and contribution margin">
      <Grid cols={3}>
        <Card icon="💵" title="Fixed & Setup Costs" badge="per run"
          info={{ what:'Setup cost + labour/unit (double-count guard against BOM).', flows:'Setup → production MILP changeover; labour → unit cost.' }}
          dev={{ comp:'CostEditor', props:'useProductCosts(sku)', state:'productCosts[sku].{setupCost,laborPerUnit}' }}>
          <Grid cols={2} gap={8}>
            <Field label="Setup Cost / Run"><NumInput value={costs.setupCost} prefix="₹" onChange={(v)=>setCosts({setupCost:v})}/></Field>
            <Field label="Labour / Unit"><NumInput value={costs.laborPerUnit} prefix="₹" onChange={(v)=>setCosts({laborPerUnit:v})}/></Field>
          </Grid>
          <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>setup amortized over lot of {lot.toLocaleString('en-IN')} u → ₹{setupAmort.toFixed(2)}/u</div>
          <div style={{marginTop:10, padding:'8px 10px', border:`2px dashed ${C.a4}`, fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>
            ⚠ Double-count guard: labour here excludes any labour already in BOM component cost.
          </div>
        </Card>
        <Card icon="🧮" title="Unit Cost Rollup" badge="DERIVED" badgeTone="y" right={<Provenance kind="derived"/>}
          info={{ what:'BOM material (computed) + labour + setup amortized + conversion = unit cost.', flows:'Cost → profit mix LP, TCO.' }}
          dev={{ comp:'CostRollup', props:'derived: Σ bom.qty·cost + labour + setupAmort + conversion' }}>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {[['Material (BOM)', bomMaterial, C.ink],['Labour', labour, C.a2],['Setup (amort.)', setupAmort, C.a4],['Conversion & OH', conversion, C.tx3]].map(([k,v,c],i)=>(
              <div key={i} style={{display:'flex', alignItems:'center', gap:8}}>
                <span style={{fontFamily:F.mono, fontSize:10, width:110, color:C.tx2}}>{k}</span>
                <MiniBar v={v} max={total} color={c}/>
                <span className="num" style={{fontFamily:F.disp, fontSize:11, fontWeight:700, width:54, textAlign:'right'}}>₹{Math.round(v)}</span>
              </div>
            ))}
          </div>
          <div style={{marginTop:10}}><Blk label="Total Unit Cost" value={`₹${Math.round(total)}`} tone="y"/></div>
          <Reading formula="unit cost = Σ(part.qty·part.cost) + labour + setup/lot + conversion"
            soWhat={`Material ₹${Math.round(bomMaterial)} is summed live from the ${M.bom.length}-part BOM — edit a part or its qty and this rollup (and the margin) move with it.`}/>
        </Card>
        <Card icon="📈" title="Price & Contribution" badge={`${cm}% CM`}
          info={{ what:'Sell price vs unit cost → contribution margin.', flows:'Margin → profit mix objective.' }}
          dev={{ comp:'PriceCard', props:'prod.price, derived total cost' }}>
          <KpiRow cols={2}>
            <Blk label="Sell Price" value={`₹${p.price}`}/>
            <Blk label="Unit Cost" value={`₹${Math.round(total)}`} tone="c"/>
            <Blk label="Contribution" value={`₹${Math.round(p.price-total)}`} tone="y"/>
            <Blk label="CM %" value={`${cm}%`} accent={C.gn}/>
          </KpiRow>
        </Card>
      </Grid>
    </StageSection>
  );
}

// inventory policy is an OUTPUT — derived by the real (s,S)/(R,Q) engine (/api/solve/policy).
function ProdPolicy({ p }) {
  const { config } = useConfig();
  const { planning } = usePlanning();
  const T = planning.horizonLength || 52;
  // build the engine payload from the live BOM + this item's annual demand + service level.
  const policy = useSolve('/api/solve/policy', ()=>({
    products:[{ name:p.sku, yield_pct:p.yield||0.97,
      demand: Array.from({length:T}, ()=> p.demand / T),   // flat seed until Demand stage feeds a real series
      parts: M.bom.map(b=>({ name:b.part, cost:b.cost, qty_per:b.qty, lead_time:b.lt,
        ordering_cost:b.S, hold_pct:b.hold, moq:b.moq })) }],
    params:{ service_level: config.serviceLevel, time_grain: planning.timeGrain==='week'?'weekly':planning.timeGrain==='day'?'daily':'monthly', periods:T },
  }));
  const pol = policy.result;
  return (
    <StageSection step="4" title="Inventory Policy" sub="this is COMPUTED from demand CV + lead time + service level — not an input you type">
      <Card icon="📊" title="Inventory Policy (s,S) / (R,Q)" badge={pol?`z=${pol.z}`:'DERIVED'} badgeTone="y"
        info={{ what:'EOQ, safety stock, reorder point per RM part — what procurement actually orders against.', flows:'Policy → MRP & reorder solver.' }}
        dev={{ comp:'PolicyCard', props:'useSolve(/api/solve/policy)', note:'Real engine output — per-part, keyed off the BOM + service level.' }}
        right={<div style={{display:'flex', alignItems:'center', gap:8}}>
          {pol && <Provenance kind="solved" run="policy.py" asOf={policy.ranAt?policy.ranAt.toLocaleTimeString():undefined}/>}
          <Btn kind={pol?'secondary':'primary'} onClick={()=>policy.run().catch(()=>{})}>{policy.solving?'deriving…':pol?'↻ Re-derive':'⚙ Derive policies'}</Btn>
        </div>}>
        {policy.error && <div style={{marginBottom:10, padding:'7px 10px', border:`2px solid ${C.dg}`, color:C.dg, fontFamily:F.mono, fontSize:10}}>⚠ {policy.error}</div>}
        {!pol && <div style={{marginBottom:10, padding:'8px 11px', border:`2px dashed ${C.line2}`, fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>
          Click <b>Derive policies</b> — the real (s,S)/(R,Q) engine sizes EOQ, safety stock and reorder points for each of the {M.bom.length} BOM parts from the live demand & service level ({(config.serviceLevel*100).toFixed(0)}%).</div>}
        {pol && <DataTable cols={['Part','Annual Dem','EOQ','Safety','Reorder s','Order-up S','Orders/yr','Policy']}
          align={['left','right','right','right','right','right','right','left']}
          rows={pol.policies.map(q=>[q.part, Math.round(q.annual_demand).toLocaleString('en-IN'), q.eoq, q.safety_stock, q.reorder_point_s, q.order_up_to_S, q.orders_per_year, q.recommended_policy])}/>}
        <Reading formula="SS = z·σ_LTD  ·  s = μ_LT + SS  ·  S = s + EOQ  ·  EOQ = max(√(2DS/h), MOQ)"
          soWhat={pol
            ? `At z=${pol.z} (${(config.serviceLevel*100).toFixed(0)}% service), each part re-derives — raise service level in Setup and re-run, the safety stocks climb. Flat-demand seed gives σ=0; the Demand stage will feed real variability.`
            : `At ${(config.serviceLevel*100).toFixed(0)}% service the engine will set z and size every part — you don't type these, they re-derive when inputs change.`}/>
        <div style={{marginTop:8, display:'flex', alignItems:'center', gap:10, padding:'8px 11px', border:`2px solid ${C.line}`, background:C.bg3}}>
          <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.tx3, letterSpacing:'.08em'}}>ROUTING</span>
          <span style={{fontFamily:F.body, fontSize:11, color:C.tx2, flex:1, lineHeight:1.4}}>This item is <MethodTag sku={p.sku}/> — {M.methodMeta[M.itemMethod(p.sku)].note}.</span>
        </div>
      </Card>
    </StageSection>
  );
}

function ProdMTO() {
  // footer totals DERIVED from the rows (was hardcoded '6 customers' / '₹ 48.6 L').
  const custN  = new Set(M.orders.map(o=>o.cust)).size;
  const totQty = M.orders.reduce((s,o)=>s+(Number(o.qty)||0),0);
  const totVal = M.orders.reduce((s,o)=>s+(Number(o.qty)||0)*(Number(o.price)||0),0);
  return (
    <StageSection step="5" title="Make-to-Order" sub="firm customer orders that floor the demand plan">
      <Card icon="📋" title="Make-to-Order (MTO)" badge={`${M.orders.length} orders`}
        info={{ what:'Per-SKU customer orders.', flows:'MTO floor → demand & profit constraints.' }}
        dev={{ comp:'MTOEditor', props:'state.orders', state:'orders[]' }}>
        <DataTable cols={['PO','Customer','SKU','Qty','Due','Price','Status']} align={['left','left','left','right','right','right','left']}
          rows={M.orders.map(o=>({cells:[o.po, o.cust, o.sku, o.qty, o.due.slice(5), `₹${o.price}`, <Tag c={o.status==='firm'?'g':'w'}>{o.status}</Tag>]}))}
          foot={['TOTAL',`${custN} customers`,'',totQty.toLocaleString('en-IN'),'',`₹${(totVal/1e5).toFixed(1)}L`,'']}/>
      </Card>
    </StageSection>
  );
}
window.StageProducts = StageProducts;
