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
        right={<Btn kind="secondary">📁 Import / Export</Btn>}/>
      <ItemSelector/>
      <div style={{padding:18}}>
        <ProdDefine/>
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
  const ex = {
    'TPA-4471':{ make:'Make', mode:'MTS', tgt:36, wt:0.84, vol:0.0021, life:'Maturity' },
    'TPA-3215':{ make:'Make', mode:'MTS', tgt:38, wt:0.31, vol:0.0009, life:'Growth' },
    'TPA-9904':{ make:'Make', mode:'MTO', tgt:36, wt:0.22, vol:0.0006, life:'Maturity' },
    'TPA-2188':{ make:'Make', mode:'MTO', tgt:33, wt:1.40, vol:0.0042, life:'Maturity' },
    'TPA-5540':{ make:'Make', mode:'ATO', tgt:32, wt:0.96, vol:0.0031, life:'Growth' },
    'TPA-7722':{ make:'Buy', mode:'MTO', tgt:31, wt:0.18, vol:0.0005, life:'Decline' },
  };
  return (
    <StageSection step="1" title="Define Products" sub="one row per finished good — a new user starts HERE, adds a product, then the selector has something to select">
      <Card icon="🏭" title="Finished-Goods Catalog" badge={`${M.items.length} products`} badgeTone="y"
        info={{ what:'The catalog of what you make: identity, commercials, physical attributes, lifecycle.', flows:'Defines the items every downstream stage filters to.' }}
        dev={{ comp:'DefineProductsCard', props:'state.products', state:'products[] {make,mode,price,margin,wt,vol,shelf,life}' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              {['Code','Name','Family','UoM','Make/Buy','Mode','Sell ₹','Tgt %','Wt kg','Vol m³','Shelf','Lifecycle','Method','Status'].map((h,i)=>(
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
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{e.wt}</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{e.vol}</td>
                    <td className="num" style={{padding:'5px 8px', textAlign:'right'}}>{p.shelf}d</td>
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
          <Btn kind="primary" sm>+ Add product</Btn>
          <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, alignSelf:'center'}}>weight & volume drive storage utilization on Network · shelf-life gates lot policy · target margin is a goal — actual mix is an output of Profit-mix, never typed here</span>
        </div>
      </Card>
    </StageSection>
  );
}

function ProdBOM({ p }) {
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
        </Advanced>
      </Card>
    </StageSection>
  );
}

function ProdCosts({ p }) {
  const labor = Math.round(p.cost*0.18), setup = 4200;
  return (
    <StageSection step="3" title="Costs" sub="setup + labour, the unit-cost rollup, and contribution margin">
      <Grid cols={3}>
        <Card icon="💵" title="Fixed & Setup Costs" badge="per run"
          info={{ what:'Setup cost + labour/unit (double-count guard against BOM).', flows:'Setup → production MILP changeover; labour → unit cost.' }}
          dev={{ comp:'CostEditor', props:'prod.costs', state:'products[id].setupCost, products[id].labor' }}>
          <Grid cols={2} gap={8}>
            <Field label="Setup Cost / Run"><NumInput value={setup} prefix="₹"/></Field>
            <Field label="Labour / Unit"><NumInput value={labor} prefix="₹"/></Field>
          </Grid>
          <div style={{marginTop:10, padding:'8px 10px', border:`2px dashed ${C.a4}`, fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>
            ⚠ Double-count guard: labour here excludes any labour already in BOM component cost.
          </div>
        </Card>
        <Card icon="🧮" title="Unit Cost Rollup" badge="derived"
          info={{ what:'BOM material + labour + setup amortized = unit cost.', flows:'Cost → profit mix LP, TCO.' }}
          dev={{ comp:'CostRollup', props:'prod (computed)' }}>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {[['Material (BOM)', p.cost*0.7, C.ink],['Labour', p.cost*0.18, C.a2],['Setup (amort.)', p.cost*0.07, C.a4],['Overhead', p.cost*0.05, C.tx3]].map(([k,v,c],i)=>(
              <div key={i} style={{display:'flex', alignItems:'center', gap:8}}>
                <span style={{fontFamily:F.mono, fontSize:10, width:110, color:C.tx2}}>{k}</span>
                <MiniBar v={v} max={p.cost} color={c}/>
                <span className="num" style={{fontFamily:F.disp, fontSize:11, fontWeight:700, width:54, textAlign:'right'}}>₹{Math.round(v)}</span>
              </div>
            ))}
          </div>
          <div style={{marginTop:10}}><Blk label="Total Unit Cost" value={`₹${p.cost}`} tone="y"/></div>
        </Card>
        <Card icon="📈" title="Price & Contribution" badge={`${Math.round((1-p.cost/p.price)*100)}% CM`}
          info={{ what:'Sell price vs unit cost → contribution margin.', flows:'Margin → profit mix objective.' }}
          dev={{ comp:'PriceCard', props:'prod.price' }}>
          <KpiRow cols={2}>
            <Blk label="Sell Price" value={`₹${p.price}`}/>
            <Blk label="Unit Cost" value={`₹${p.cost}`} tone="c"/>
            <Blk label="Contribution" value={`₹${p.price-p.cost}`} tone="y"/>
            <Blk label="CM %" value={`${Math.round((1-p.cost/p.price)*100)}%`} accent={C.gn}/>
          </KpiRow>
        </Card>
      </Grid>
    </StageSection>
  );
}

// inventory policy is an OUTPUT — mark it derived, show the formulas
function ProdPolicy({ p }) {
  return (
    <StageSection step="4" title="Inventory Policy" sub="this is COMPUTED from demand CV + lead time + service level — not an input you type">
      <Card icon="📊" title="Inventory Policy (s,S)" badge="DERIVED" badgeTone="y"
        info={{ what:'Cycle stock, safety stock, reorder point, EOQ — all computed from params.', flows:'Policy → MRP & reorder solver.' }}
        dev={{ comp:'PolicyCard', props:'prod (derived)', note:'Outputs, not inputs — fields are read-only.' }}>
        <KpiRow cols={3}>
          <Blk label="Annual Demand" value={p.demand.toLocaleString('en-IN')} sub="units/yr"/>
          <Blk label="Cycle Stock" value="142 u" sub="D·L / 2"/>
          <Blk label="Safety Stock" value="67 u" sub="z·σ_LTD" tone="y"/>
          <Blk label="Reorder Point" value="284 u" sub="μ_LT + SS"/>
          <Blk label="EOQ" value="320 u" sub="√(2DS/h)"/>
          <Blk label="Order-up-to (S)" value="462 u" sub="s + EOQ"/>
        </KpiRow>
        <Reading formula="SS = z·σ_LTD  ·  s = μ_LT + SS  ·  S = s + EOQ  ·  EOQ = √(2DS/h)"
          soWhat={`At z=1.645 (95%) and LT-demand σ, this SKU holds 67u safety. Raise service level → SS climbs; it re-derives, you don't re-type.`}/>
        <div style={{marginTop:8, display:'flex', alignItems:'center', gap:10, padding:'8px 11px', border:`2px solid ${C.line}`, background:C.bg3}}>
          <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.tx3, letterSpacing:'.08em'}}>ROUTING</span>
          <span style={{fontFamily:F.body, fontSize:11, color:C.tx2, flex:1, lineHeight:1.4}}>This item is <MethodTag sku={p.sku}/> — {M.methodMeta[M.itemMethod(p.sku)].note}.</span>
        </div>
      </Card>
    </StageSection>
  );
}

function ProdMTO() {
  return (
    <StageSection step="5" title="Make-to-Order" sub="firm customer orders that floor the demand plan">
      <Card icon="📋" title="Make-to-Order (MTO)" badge={`${M.orders.length} orders`}
        info={{ what:'Per-SKU customer orders.', flows:'MTO floor → demand & profit constraints.' }}
        dev={{ comp:'MTOEditor', props:'state.orders', state:'orders[]' }}>
        <DataTable cols={['PO','Customer','SKU','Qty','Due','Price','Status']} align={['left','left','left','right','right','right','left']}
          rows={M.orders.map(o=>({cells:[o.po, o.cust, o.sku, o.qty, o.due.slice(5), `₹${o.price}`, <Tag c={o.status==='firm'?'g':'w'}>{o.status}</Tag>]}))}
          foot={['TOTAL','6 customers','','—','','₹ 48.6 L','']}/>
      </Card>
    </StageSection>
  );
}
window.StageProducts = StageProducts;
