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
      <ItemSelector onNav={onNav}/>
      <div style={{padding:18}}>
        <ScopeBanner kind="product" name={p.name} code={p.sku}
          sub="yield, BOM, costs & policy are for THIS product — the ▦ Catalog and ▦ Make-to-Order cards are portfolio-wide (each section is scope-tagged below)"/>
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
  // inline cell editors — the catalogue is MASTER DATA, so name/price/margin/make/
  // mode/demand are now editable in place (review Fact 5: a read-only input is a bug).
  // They write straight to M.products via editProductAttr, which logs the change and
  // flags dependent solves stale. Seed make/mode/tgt/life fall back to the `ex` map
  // until the user overrides (then they live on the product object).
  const tin = { border:`1.5px solid ${C.line2}`, background:C.paper, color:C.tx, fontFamily:F.disp,
    fontWeight:700, fontSize:11, padding:'3px 5px', width:'100%', outline:'none', boxSizing:'border-box' };
  const ETxt = ({v,on,w,align})=> <input value={v==null?'':v} onChange={e=>on(e.target.value)} style={{...tin, width:w||'100%', textAlign:align||'left'}}/>;
  const ENum = ({v,on,w})=> <input value={v==null?'':v} onChange={e=>{ const s=e.target.value; const n=Number(s); on(s===''?'':(Number.isNaN(n)?v:n)); }} className="num" style={{...tin, width:w||62, textAlign:'right'}}/>;
  const ESel = ({v,on,opts})=> <select value={v} onChange={e=>on(e.target.value)} style={{...tin, cursor:'pointer'}}>{opts.map(o=><option key={o} value={o}>{o}</option>)}</select>;
  const demandFor = (p)=> getItemDemand(p.sku, 12).reduce((a,b)=>a+b,0);   // committed annual (forecast or seed)
  return (
    <StageSection step="1" scope="global" title="Define Products" sub="one row per finished good — edit the commercial fields inline (name, make/buy, mode, price, target %, demand); Wt/Vol/Shelf/Yield are edited in the Yield card, Family/Method/Lifecycle are derived. This is where you describe YOUR products, not a fixed demo">
      <Card icon="🏭" title="Finished-Goods Catalog" badge={`${M.items.length} products · editable`} badgeTone="y"
        info={{ what:'The catalog of what you make: identity, commercials, physical attributes, lifecycle. Editable master data.', flows:'Defines the items every downstream stage filters to.' }}
        dev={{ comp:'DefineProductsCard', props:'editProductAttr(sku,…)', state:'products[] {name,price,demand,makeBuy,mode,targetMargin}' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              {['Code','Name','Family','Make/Buy','Mode','Sell ₹','Tgt %','Demand/yr','Wt kg','Vol m³','Shelf','Yield','Lifecycle','Method'].map((h,i)=>(
                <th key={i} style={{color:C.paper, textAlign:i<2?'left':'right', padding:'6px 8px', fontSize:8.5, letterSpacing:'.04em', textTransform:'uppercase', whiteSpace:'nowrap'}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {M.products.filter(p=>p.cat==='Finished').map((p,ri)=>{ const e=ex[p.sku]||{};
                const mk = p.makeBuy || e.make || 'Make';
                const md = p.mode || e.mode || 'MTS';
                const tg = p.targetMargin!=null ? p.targetMargin : (e.tgt!=null ? e.tgt : 35);
                return (
                  <tr key={p.sku} style={{borderTop:`1px solid ${C.line2}`, background: ri%2?C.bg3:C.paper}}>
                    <td style={{padding:'4px 8px', fontWeight:700, whiteSpace:'nowrap'}}>{p.sku}</td>
                    <td style={{padding:'4px 6px', minWidth:150}}><ETxt v={p.name} on={v=>editProductAttr(p.sku,{name:v})}/></td>
                    <td style={{padding:'4px 8px', textAlign:'right', color:C.tx2}}>{(M.itemById(p.sku)||{}).family}</td>
                    <td style={{padding:'4px 6px'}}><ESel v={mk} on={v=>editProductAttr(p.sku,{makeBuy:v})} opts={['Make','Buy']}/></td>
                    <td style={{padding:'4px 6px'}}><ESel v={md} on={v=>editProductAttr(p.sku,{mode:v})} opts={['MTS','MTO','ATO']}/></td>
                    <td style={{padding:'4px 6px'}}><ENum v={p.price} on={v=>editProductAttr(p.sku,{price:Number(v)||0})}/></td>
                    <td style={{padding:'4px 6px'}}><ENum v={tg} w={50} on={v=>editProductAttr(p.sku,{targetMargin:Number(v)||0})}/></td>
                    <td style={{padding:'4px 6px'}}><ENum v={p.demand} w={74} on={v=>{ editProductAttr(p.sku,{demand:Number(v)||0}); try{markStale('demand');}catch(x){} }}/></td>
                    <td className="num" style={{padding:'4px 8px', textAlign:'right', color:C.tx3}}>{skuWeightKg(p.sku)}</td>
                    <td className="num" style={{padding:'4px 8px', textAlign:'right', color:C.tx3}}>{skuVolM3(p.sku)}</td>
                    <td className="num" style={{padding:'4px 8px', textAlign:'right', color:C.tx3}}>{p.shelf}d</td>
                    {(()=>{ const my=(typeof measuredYield==='function')?measuredYield(p.sku):null;
                      return <td className="num" title={my!=null?`measured from confirmations (typed seed ${Math.round((Number(p.yield)||0.95)*100)}%)`:'typed planning seed'}
                        style={{padding:'4px 8px', textAlign:'right', color:my!=null?C.tx:C.tx3, fontWeight:my!=null?700:400}}>
                        {Math.round((my!=null?my:(Number(p.yield)||0.95))*100)}%{my!=null?'*':''}</td>; })()}
                    <td style={{padding:'4px 8px', textAlign:'right', color:C.tx2}}>{e.life||'—'}</td>
                    <td style={{padding:'4px 8px', textAlign:'right'}}><MethodTag sku={p.sku}/></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{marginTop:10, display:'flex', gap:8}}>
          <Btn kind="primary" sm onClick={onAdd}>+ Add product</Btn>
          <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, alignSelf:'center'}}>edit any cell — name, make/buy, mode, price, target margin, annual demand. Wt/Vol/Shelf/Yield are edited in the Yield card (right of the selector below). Demand/yr is the committed series (forecast if run, else this seed). Target margin is a goal — realised mix is Profit-mix output.</span>
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
    <StageSection step="1a" scope="item" title={`Yield & expiry · ${p.name}`} sub="the real solver levers — what fraction comes out good, and what happens to stock that ages out">
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
      <YieldConfirmations p={p}/>
    </StageSection>
  );
}

// ── (G-I1) MEASURED yield. The card above edits the typed PLANNING yield; this one
// records actual production confirmations (good ÷ started) from the floor. When any
// batch is logged, the rolling measured yield REPLACES the typed seed in every solve
// (skuYield()), so yield stops being an assumption and becomes a measurement. No
// confirmations ⇒ planning stays on the typed seed (byte-identical).
function YieldConfirmations({ p }){
  const { confirmations, measured, log, clear } = useYieldConfirmations(p.sku);
  const [started, setStarted] = useState('');
  const [good, setGood] = useState('');
  const typed = (Number(p.yield)||0.95);
  const planUses = (measured!=null) ? measured : typed;
  const totStarted = confirmations.reduce((s,c)=>s+(Number(c.started)||0),0);
  const totGood = confirmations.reduce((s,c)=>s+(Number(c.good)||0),0);
  const onLog = ()=>{ const s=Number(started); if(s>0){ log(s, Number(good)||0); setStarted(''); setGood(''); } };
  return (
    <Card icon="📋" title={`Production yield confirmations · ${p.sku}`}
      badge={measured!=null?'measured — drives the solvers':'no data — using typed seed'} badgeTone={measured!=null?'y':undefined}
      info={{ what:'Log actual good/started from completed production batches. The rolling measured yield (Σ good ÷ Σ started) REPLACES the typed seed yield in every solve, so planning grosses up material & capacity off the floor reality, not an assumption.', flows:'→ skuYield() → procurement effective_qty · production · profit-mix · Monte-Carlo · pooling.' }}
      dev={{ comp:'YieldConfirmations', props:'logYieldConfirmation(sku,started,good)', state:'yieldConfirmations[sku][]' }}>
      <div style={{display:'flex', gap:12, alignItems:'flex-end', flexWrap:'wrap'}}>
        <Field label="Units started"><NumInput value={started} suffix="u" onChange={setStarted}/></Field>
        <Field label="Good units out"><NumInput value={good} suffix="u" onChange={setGood}/></Field>
        <Btn kind="primary" sm onClick={onLog}>+ Log batch</Btn>
        {confirmations.length>0 && <Btn kind="ghost" sm onClick={clear}>clear all</Btn>}
      </div>
      {confirmations.length>0 && <div style={{marginTop:11, fontFamily:F.mono, fontSize:10, color:C.tx2}}>
        {confirmations.map((c,i)=>(
          <div key={i} style={{display:'flex', justifyContent:'space-between', padding:'3px 0', borderBottom:`1px solid ${C.line2}`}}>
            <span>batch {i+1}: <b style={{color:C.tx}}>{c.good}</b> good / <b style={{color:C.tx}}>{c.started}</b> started</span>
            <span style={{color:C.tx3}}>{((Number(c.good)||0)/Math.max(Number(c.started)||1,1)*100).toFixed(1)}%</span>
          </div>
        ))}
      </div>}
      <Reading formula={measured!=null
          ? `measured yield = ${totGood} good ÷ ${totStarted} started = ${(measured*100).toFixed(1)}%  ·  typed seed ${(typed*100).toFixed(1)}%`
          : `no confirmations — planning uses the typed seed ${(typed*100).toFixed(1)}%`}
        soWhat={measured!=null
          ? `Planning now grosses up to the MEASURED ${(measured*100).toFixed(1)}% from ${confirmations.length} batch${confirmations.length>1?'es':''}, overriding the typed ${(typed*100).toFixed(1)}% in procurement / production / profit-mix / Monte-Carlo / pooling. Those solves are flagged stale — re-run to see the floor reality flow through (a worse measured yield raises the material you must buy).`
          : `Log a completed batch's good/started to switch yield from an ASSUMPTION to a MEASUREMENT. Until then every solve uses your typed ${(typed*100).toFixed(1)}% seed.`}/>
    </Card>
  );
}

function ProdBOM({ p }) {
  useMasterRev();
  const parts = bomForSku(p.sku);                 // Ph2 · R7 — THIS FG's bill (skuBom ⋈ master ⋈ per-SKU qty)
  return (
    <StageSection step="2" scope="item" title={`Bill of Materials · ${p.name}`} sub="the parts THIS finished good uses and how much of each per unit — qty-per is per-product (edit it here); a part's cost / lead time / MOQ / supplier are shared across every product that uses the part">
      <Card icon="🔧" title={`Bill of Materials · ${p.sku}`} badge={`${parts.length} parts`}
        info={{ what:'The per-product bill: which parts this FG consumes (from its skuBom) and the qty-per. Qty-per is editable PER PRODUCT; part cost / lead time / MOQ are shared part-master attributes (editing them affects every FG that uses the part).', flows:'Explodes into this SKU’s material cost, the (s,S) policy, and the risk sim’s per-SKU costed bill.' }}
        dev={{ comp:'BOMEditor', props:'bomForSku(p.sku)', state:'M.skuBom[sku] (parts+qty) ⋈ M.bom (master) ⋈ bomOverrides[sku][part].qty' }}>
        {parts.length===0
          ? <div style={{padding:'14px', textAlign:'center', fontFamily:F.mono, fontSize:10, color:C.tx3, border:`2px dashed ${C.line2}`}}>No bill defined for {p.sku} — add it to M.skuBom.</div>
          : <>
        <SubLabel right={<span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>qty/u editable per-product · cost / lead shared</span>}>Physical structure</SubLabel>
        {(()=>{ const tin={ border:`1.5px solid ${C.line2}`, background:C.paper, color:C.tx, fontFamily:F.disp, fontWeight:700, fontSize:11, padding:'3px 5px', textAlign:'right', outline:'none', boxSizing:'border-box' };
          const EN=({v,on,w,sfx,pfx})=> <span style={{display:'inline-flex',alignItems:'center',gap:2,justifyContent:'flex-end'}}>{pfx&&<span style={{color:C.tx3,fontSize:10}}>{pfx}</span>}<input className="num" value={v==null?'':v} onChange={e=>{const s=e.target.value;const n=Number(s);on(s===''?'':(Number.isNaN(n)?v:n));}} style={{...tin,width:w||58}}/>{sfx&&<span style={{color:C.tx3,fontSize:9}}>{sfx}</span>}</span>;
          const total = parts.reduce((s,b)=>s+b.cost*b.qty,0);
          return (
          <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
            <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
              <thead><tr style={{background:C.ink}}>{['Part','Component','Qty/u · per-SKU','Unit Cost · shared','Lead · shared'].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i<2?'left':'right', padding:'6px 9px', fontSize:9, textTransform:'uppercase', whiteSpace:'nowrap'}}>{h}</th>)}</tr></thead>
              <tbody>
                {parts.map((b,ri)=>(
                  <tr key={b.part} style={{borderTop:`1px solid ${C.line2}`, background:ri%2?C.bg3:C.paper}}>
                    <td style={{padding:'4px 9px', fontWeight:700}}>{b.part}</td>
                    <td style={{padding:'4px 9px', color:C.tx2}}>{b.name}</td>
                    <td style={{padding:'4px 6px', textAlign:'right', whiteSpace:'nowrap'}}><EN v={b.qty} on={v=>editPartQty(p.sku, b.part, v)}/>{b.qtyOver && <span title={`per-product override · skuBom seed ${b.qtySeed}`} style={{marginLeft:3, fontFamily:F.mono, fontSize:8, color:C.a2}}>●</span>}</td>
                    <td style={{padding:'4px 6px', textAlign:'right'}}><EN v={b.cost} pfx="₹" on={v=>editPartAttr(b.part,{cost:Number(v)||0})}/></td>
                    <td style={{padding:'4px 6px', textAlign:'right'}}><EN v={b.lt} sfx="d" on={v=>editPartAttr(b.part,{lt:Number(v)||0})}/></td>
                  </tr>
                ))}
                <tr style={{background:C.ink}}><td style={{padding:'6px 9px',color:C.ac,fontWeight:700}}>TOTAL</td><td style={{padding:'6px 9px',color:C.ac}}>{parts.length} parts</td><td></td><td className="num" style={{padding:'6px 9px',textAlign:'right',color:C.ac,fontWeight:700}}>₹{total.toFixed(0)}/u</td><td></td></tr>
              </tbody>
            </table>
          </div>
          ); })()}
        <Advanced label="Commercial & ordering terms (shared part master)" count={parts.length}>
          <DataTable cols={['Part','MOQ','Ordering S','Holding %','Contract Price','Supplier']} align={['left','right','right','right','right','left']}
            rows={parts.map(b=>{ const ct=M.contracts.find(x=>x.item===b.part);
              return [b.part, b.moq.toLocaleString('en-IN'), `₹${b.S}`, `${b.hold}%`, ct?`₹${ct.rateByPeriod[0][1]}→₹${ct.rateByPeriod[ct.rateByPeriod.length-1][1]}`:`₹${b.cost}`, b.sup];
            })}/>
          <Reading formula="commercial price = contract.rateByPeriod[t] (Network)" soWhat="These are shared part-master terms (same for every FG that uses the part). Steel steps from ₹142 to ₹151 at W29 — the procurement MILP times buys around it."/>
          <SubLabel right={<span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>per-part · shared · distinct from product yield</span>}>Conversion scrap (material lost)</SubLabel>
          <div style={{display:'flex', flexWrap:'wrap', gap:10}}>
            {parts.map(b=>(
              <Field key={b.part} label={`${b.part} scrap %`}>
                <NumInput value={Math.round((Number(b.scrap)||0.01)*1000)/10} suffix="%" w={92}
                  onChange={(v)=>editPartAttr(b.part, { scrap: Math.min(0.5, Math.max(0, Number(v)/100)) })}/>
              </Field>
            ))}
          </div>
          <Reading formula="effective material = qty · (1 + scrap) / yield  (procurement.py)"
            soWhat="Scrap is the fraction of THIS part's material lost in conversion (chips, offcuts) — separate from product yield, which is the fraction of finished units that come out good. Both gross up what procurement must buy."/>
        </Advanced>
          </>}
      </Card>
    </StageSection>
  );
}

function ProdCosts({ p }) {
  // Material is now genuinely DERIVED from the BOM (Σ qty·cost), not a fake 70% of cost.
  // Setup + labour are editable + persisted; "conversion & overhead" is the residual
  // that reconciles the rollup to the item's standard cost at seed, then floats as you edit.
  const lot = p.moq || 100;
  const bomMaterial = bomForSku(p.sku).reduce((s,b)=>s + b.qty*b.cost, 0);   // Ph2 · R7 — THIS FG's material, not the shared bill
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
    <StageSection step="3" scope="item" title="Costs" sub="setup + labour, the unit-cost rollup, and contribution margin">
      <Grid cols={3}>
        <Card icon="💵" title="Fixed & Setup Costs" badge="per run"
          info={{ what:'Setup cost + labour/unit (double-count guard against BOM).', flows:'Setup → production MILP changeover; labour → unit cost.' }}
          dev={{ comp:'CostEditor', props:'useProductCosts(sku)', state:'productCosts[sku].{setupCost,laborPerUnit}' }}>
          <Grid cols={2} gap={8}>
            <Field label="Setup Cost / Run"><NumInput value={costs.setupCost} prefix="₹" onChange={(v)=>setCosts({setupCost:v})}/></Field>
            <Field label="Labour / Unit"><NumInput value={costs.laborPerUnit} prefix="₹" onChange={(v)=>setCosts({laborPerUnit:v})}/></Field>
            <Field label="Lot size (MOQ)" hint="setup is amortized over this run size"><NumInput value={p.moq||100} suffix="u" onChange={(v)=>editProductAttr(p.sku,{moq:Math.max(1,Number(v)||1)})}/></Field>
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
            soWhat={`Material ₹${Math.round(bomMaterial)} is summed live from ${p.name}’s ${bomForSku(p.sku).length}-part bill — edit a part cost or this FG’s qty-per and this rollup (and the margin) move with it.`}/>
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
  // G-I2 — this FG's service target is differentiated by its ABC class (A 98 / B 95 / C 90),
  // not one global α: a class-A item earns a tighter fill (higher z) than a long-tail C-item.
  const sl = (typeof serviceLevelForSku==='function') ? serviceLevelForSku(p.sku) : config.serviceLevel;
  // build the engine payload from the live BOM + this item's annual demand + service level.
  const policy = useSolve('/api/solve/policy', ()=>({
    products:[{ name:p.sku, yield_pct:(typeof skuYield==='function'?skuYield(p,0.97):(p.yield||0.97)),   // G-I1 measured ?? seed
      demand: Array.from({length:T}, ()=> p.demand / T),   // flat seed until Demand stage feeds a real series
      parts: bomForSku(p.sku).map(b=>({ name:b.part, cost:b.cost, qty_per:b.qty, lead_time:b.lt,
        ordering_cost:b.S, hold_pct:b.hold, moq:b.moq })) }],   // Ph2 · R7 — derive policy for THIS FG's parts
    params:{ service_level: sl, time_grain: planning.timeGrain==='week'?'weekly':planning.timeGrain==='day'?'daily':'monthly', periods:T },
  }));
  const pol = policy.result;
  return (
    <StageSection step="4" scope="item" title="Inventory Policy" sub="this is COMPUTED from demand CV + lead time + service level — not an input you type">
      <Card icon="📊" title="Inventory Policy (s,S) / (R,Q)" badge={pol?`z=${pol.z} · class-${p.abc||'?'}`:'DERIVED'} badgeTone="y"
        info={{ what:'EOQ, safety stock, reorder point per RM part — what procurement actually orders against.', flows:'Policy → MRP & reorder solver.' }}
        dev={{ comp:'PolicyCard', props:'useSolve(/api/solve/policy)', note:'Real engine output — per-part, keyed off the BOM + service level.' }}
        right={<div style={{display:'flex', alignItems:'center', gap:8}}>
          {pol && <Provenance kind="solved" run="policy.py" asOf={policy.ranAt?policy.ranAt.toLocaleTimeString():undefined}/>}
          <Btn kind={pol?'secondary':'primary'} onClick={()=>policy.run().catch(()=>{})}>{policy.solving?'deriving…':pol?'↻ Re-derive':'⚙ Derive policies'}</Btn>
        </div>}>
        {policy.error && <div style={{marginBottom:10, padding:'7px 10px', border:`2px solid ${C.dg}`, color:C.dg, fontFamily:F.mono, fontSize:10}}>⚠ {policy.error}</div>}
        {!pol && <div style={{marginBottom:10, padding:'8px 11px', border:`2px dashed ${C.line2}`, fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>
          Click <b>Derive policies</b> — the real (s,S)/(R,Q) engine sizes EOQ, safety stock and reorder points for each of {p.name}’s {bomForSku(p.sku).length} parts from the live demand & this item’s <b>class-{p.abc||'?'}</b> service level ({(sl*100).toFixed(0)}%).</div>}
        {pol && <DataTable cols={['Part','Annual Dem','EOQ','Safety','Reorder s','Order-up S','Orders/yr','Policy']}
          align={['left','right','right','right','right','right','right','left']}
          rows={pol.policies.map(q=>[q.part, Math.round(q.annual_demand).toLocaleString('en-IN'), q.eoq, q.safety_stock, q.reorder_point_s, q.order_up_to_S, q.orders_per_year, q.recommended_policy])}/>}
        <Reading formula="SS = z·σ_LTD  ·  s = μ_LT + SS  ·  S = s + EOQ  ·  EOQ = max(√(2DS/h), MOQ)"
          soWhat={pol
            ? `At z=${pol.z} (class-${p.abc||'?'} ⇒ ${(sl*100).toFixed(0)}% service, G-I2 ABC-differentiated), each part re-derives — a higher class/service raises z and the safety stocks climb. Flat-demand seed gives σ=0; the Demand stage will feed real variability.`
            : `At the class-${p.abc||'?'} ${(sl*100).toFixed(0)}% service target the engine will set z and size every part — you don't type these, they re-derive when inputs change.`}/>
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
  const firm   = M.orders.filter(o=>o.status==='firm');
  const firmQty= firm.reduce((s,o)=>s+(Number(o.qty)||0),0);
  const firmSku= new Set(firm.map(o=>o.sku)).size;
  return (
    <StageSection step="5" scope="global" title="Make-to-Order" sub="firm customer orders that floor the demand plan — the whole order book across every SKU">
      <Card icon="📋" title="Make-to-Order (MTO)" badge={`${M.orders.length} orders`}
        info={{ what:'Per-SKU customer orders. Firm orders are a production floor the profit-mix optimizer must satisfy.', flows:'Firm MTO → profit-mix min_quantity (floor) + Demand consensus.' }}
        dev={{ comp:'MTOEditor', props:'state.orders', state:'orders[] → profitmixPayload.min_quantity' }}>
        <DataTable cols={['PO','Customer','SKU','Qty','Due','Price','Status']} align={['left','left','left','right','right','right','left']}
          rows={M.orders.map(o=>({cells:[o.po, o.cust, o.sku, o.qty, o.due.slice(5), `₹${o.price}`, <Tag c={o.status==='firm'?'g':'w'}>{o.status}</Tag>]}))}
          foot={['TOTAL',`${custN} customers`,'',totQty.toLocaleString('en-IN'),'',`₹${(totVal/1e5).toFixed(1)}L`,'']}/>
        <Reading formula="profit-mix floor: q[k] ≥ Σ firm orders[k]  (planned orders excluded — not a commitment)"
          soWhat={`${firmQty.toLocaleString('en-IN')} u of firm orders across ${firmSku} SKU${firmSku===1?'':'s'} are now enforced as a production floor in the profit-mix optimizer — it can no longer drop a contracted SKU to zero to chase margin. Planned orders stay advisory.`}/>
      </Card>
    </StageSection>
  );
}
window.StageProducts = StageProducts;
