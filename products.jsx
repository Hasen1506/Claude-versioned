// ════════════════════════════════════════════════════════════════════════
// products.jsx — Products & BOM (ProductsTab). SKU selector + sub-tabs:
// BOM · Costs · SKU Params · Cycle/Line · MTO · Cost Events.  P5 disclosure.
// ════════════════════════════════════════════════════════════════════════
function StageProducts({ onNav }) {
  const [sel, setSel] = useState(0);
  const [sub, setSub] = useState('bom');
  const p = M.products[sel];
  const tabs = [
    { id:'bom',    n:'a', label:'BOM', count:M.bom.length },
    { id:'costs',  n:'b', label:'Costs' },
    { id:'params', n:'c', label:'SKU Params' },
    { id:'cycle',  n:'d', label:'Cycle / Line' },
    { id:'mto',    n:'e', label:'MTO', count:M.orders.length },
    { id:'events', n:'f', label:'Cost Events', count:M.costEvents.length },
  ];
  return (
    <div>
      <StageHeader n="02" title="Products & BOM" kicker="Bill of materials · costs · SKU parameters · make-to-order · rolling cost events"
        right={<Btn kind="secondary" onClick={()=>{}}>📁 Import / Export</Btn>}/>
      {/* SKU selector strip */}
      <div style={{display:'flex', gap:0, overflowX:'auto', borderBottom:`2px solid ${C.line}`, background:C.bg2}}>
        {M.products.map((x,i)=>{
          const a = sel===i;
          return (
            <button key={x.sku} onClick={()=>setSel(i)} style={{
              flexShrink:0, padding:'7px 12px', border:'none', borderRight:`1px solid ${C.line2}`, cursor:'pointer',
              background: a?C.ac:'transparent', color:C.tx, textAlign:'left', minWidth:140,
            }}>
              <div style={{display:'flex', alignItems:'center', gap:6}}>
                <span style={{fontFamily:F.mono, fontSize:10, fontWeight:700}}>{x.sku}</span>
                <span style={{fontFamily:F.mono, fontSize:8, padding:'0 4px', border:`1px solid ${C.line}`, background:x.abc==='A'?C.ink:C.paper, color:x.abc==='A'?C.ac:C.tx}}>{x.abc}{x.xyz}</span>
              </div>
              <div style={{fontFamily:F.disp, fontSize:11, fontWeight:600, marginTop:1, whiteSpace:'nowrap'}}>{x.name}</div>
            </button>
          );
        })}
      </div>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        <div style={{marginBottom:12, display:'flex', alignItems:'center', gap:12}}>
          <span style={{fontFamily:F.disp, fontSize:20, fontWeight:900}}>{p.name}</span>
          <Tag c="k">{p.sku}</Tag><Tag c="w">{p.cat}</Tag><Tag c="y">SL {p.sl}%</Tag><Tag c="w">SHELF {p.shelf}d</Tag>
        </div>
        {sub==='bom'    && <ProdBOM p={p}/>}
        {sub==='costs'  && <ProdCosts p={p}/>}
        {sub==='params' && <ProdParams p={p}/>}
        {sub==='cycle'  && <ProdCycle p={p} onNav={onNav}/>}
        {sub==='mto'    && <ProdMTO/>}
        {sub==='events' && <ProdEvents/>}
      </div>
    </div>
  );
}

function ProdBOM({ p }) {
  return (
    <Grid cols={1}>
      <Card icon="🔧" title="Bill of Materials" badge={`${M.bom.length} parts`} info={{ what:'Parts, qty/unit, cost, lead time + commercial ordering terms.', flows:'Explodes into MRP & procurement MILP demand.' }}
        dev={{ comp:'BOMEditor', props:'prod, state.products[].bom', state:'products[id].bom[]' }}>
        <SubLabel right={<span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>primary fields</span>}>Physical structure</SubLabel>
        <DataTable cols={['Part','Component','Qty/u','Unit Cost','Lead Time']} align={['left','left','right','right','right']}
          rows={M.bom.map(b=>[b.part, b.name, b.qty, `₹${b.cost}`, `${b.lt}d`])}
          foot={['TOTAL', '5 parts', '', `₹${M.bom.reduce((s,b)=>s+b.cost*b.qty,0).toFixed(0)}/u`, '']}/>
        {/* P5 progressive disclosure */}
        <Advanced label="Commercial & ordering terms" count={5}>
          <DataTable cols={['Part','MOQ','Ordering S','Holding %','Shelf-life','Supplier']} align={['left','right','right','right','right','left']}
            rows={M.bom.map(b=>[b.part, b.moq.toLocaleString('en-IN'), `₹${b.S}`, `${b.hold}%`, b.shelf===999?'∞':`${b.shelf}d`, b.sup])}/>
        </Advanced>
      </Card>
    </Grid>
  );
}

function ProdCosts({ p }) {
  const labor = Math.round(p.cost*0.18), setup = 4200;
  return (
    <Grid cols={3}>
      <Card icon="💵" title="Fixed & Setup Costs" badge="per run" info={{ what:'Setup cost + labour/unit (double-count guard against BOM).', flows:'Setup → production MILP changeover; labour → unit cost.' }}
        dev={{ comp:'CostEditor', props:'prod.costs', state:'products[id].setupCost, products[id].labor' }}>
        <Grid cols={2} gap={8}>
          <Field label="Setup Cost / Run"><NumInput value={setup} prefix="₹"/></Field>
          <Field label="Labour / Unit"><NumInput value={labor} prefix="₹"/></Field>
        </Grid>
        <div style={{marginTop:10, padding:'8px 10px', border:`2px dashed ${C.a4}`, fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>
          ⚠ Double-count guard: labour here excludes any labour already in BOM component cost.
        </div>
      </Card>
      <Card icon="🧮" title="Unit Cost Rollup" badge="derived" info={{ what:'BOM material + labour + setup amortized = unit cost.', flows:'Cost → profit mix LP, TCO.' }}
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
      <Card icon="📈" title="Price & Contribution" badge={`${Math.round((1-p.cost/p.price)*100)}% CM`} info={{ what:'Sell price vs unit cost → contribution margin.', flows:'Margin → profit mix objective.' }}
        dev={{ comp:'PriceCard', props:'prod.price' }}>
        <KpiRow cols={2}>
          <Blk label="Sell Price" value={`₹${p.price}`}/>
          <Blk label="Unit Cost" value={`₹${p.cost}`} tone="c"/>
          <Blk label="Contribution" value={`₹${p.price-p.cost}`} tone="y"/>
          <Blk label="CM %" value={`${Math.round((1-p.cost/p.price)*100)}%`} accent={C.gn}/>
        </KpiRow>
      </Card>
    </Grid>
  );
}

function ProdParams({ p }) {
  return (
    <Grid cols={2}>
      <Card icon="⚙️" title="Product Parameters" badge="planning" info={{ what:'Capacity, MAPE, yield, OEE, price, shelf-life, demand mode.', flows:'Feeds forecast, capacity, safety stock.' }}
        dev={{ comp:'ProductsTab', props:'prod', state:'products[id].{mape,yield,oee,demandMode}' }}>
        <Grid cols={2} gap={8}>
          <Field label="Forecast MAPE"><NumInput value={p.mape} suffix="%"/></Field>
          <Field label="Process Yield"><NumInput value={(p.yield*100).toFixed(0)} suffix="%"/></Field>
          <Field label="OEE"><NumInput value={(p.oee*100).toFixed(0)} suffix="%"/></Field>
          <Field label="Service Level"><NumInput value={p.sl} suffix="%"/></Field>
          <Field label="Shelf-life"><NumInput value={p.shelf} suffix="d"/></Field>
          <Field label="Demand Mode"><Select value="Continuous" options={['Continuous','Intermittent','Lumpy']}/></Field>
        </Grid>
      </Card>
      <Card icon="📊" title="Inventory Policy" badge="(s,S)" info={{ what:'Cycle stock, safety stock, reorder point from params.', flows:'Policy → MRP & reorder solver.' }}
        dev={{ comp:'PolicyCard', props:'prod (derived)' }}>
        <KpiRow cols={2}>
          <Blk label="Annual Demand" value={p.demand.toLocaleString('en-IN')} sub="units/yr"/>
          <Blk label="Cycle Stock" value="142 u" sub="D/2·L"/>
          <Blk label="Safety Stock" value="67 u" sub="z·σ_LTD" tone="y"/>
          <Blk label="Reorder Point" value="284 u" sub="ROP"/>
          <Blk label="EOQ" value="320 u" sub="√(2DS/h)"/>
          <Blk label="Max (S)" value="462 u" sub="order-up-to"/>
        </KpiRow>
      </Card>
    </Grid>
  );
}

function ProdCycle({ p, onNav }) {
  return (
    <Grid cols={2}>
      <Card icon="🏭" title="Cycle Time & Line Assignment" badge={p.line} info={{ what:'Per-SKU cycle time + line assignment.', flows:'Cycle/line → production MILP & MPS.' }}
        dev={{ comp:'CycleEditor', props:'prod.cycle, prod.line', state:'products[id].{cycle,line}' }}>
        <Grid cols={2} gap={8}>
          <Field label="Cycle Time"><NumInput value={p.cycle} suffix="min/u"/></Field>
          <Field label="Assigned Line"><Select value={p.line} options={['LINE-01','LINE-02','LINE-03']}/></Field>
          <Field label="Effective Rate"><NumInput value={(60/p.cycle*p.oee).toFixed(1)} suffix="u/hr" disabled/></Field>
          <Field label="Batch Size"><NumInput value={p.moq}/></Field>
        </Grid>
        <div style={{marginTop:10, padding:'8px 10px', background:C.bg3, border:`2px solid ${C.line2}`, fontFamily:F.mono, fontSize:10}}>
          Theoretical {(60/p.cycle).toFixed(1)} u/hr × OEE {(p.oee*100).toFixed(0)}% = <b>{(60/p.cycle*p.oee).toFixed(1)} u/hr</b> effective.
        </div>
      </Card>
      <Card icon="📅" title="Line Load Preview" badge="this SKU" info={{ what:'Where this SKU sits on its assigned line.', flows:'Shared with Production Architecture.' }}
        right={<button onClick={()=>onNav&&onNav('production')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>full view →</button>}
        dev={{ comp:'LineLoadMini', props:'prod.line' }}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {['W01','W02','W03','W04','W05','W06'].map((w,i)=>(
            <div key={i} style={{display:'flex', alignItems:'center', gap:8}}>
              <span style={{fontFamily:F.mono, fontSize:10, width:34, color:C.tx2}}>{w}</span>
              <MiniBar v={[60,72,68,80,55,64][i]} max={100} color={C.ink} h={12}/>
              <span className="num" style={{fontFamily:F.mono, fontSize:10, width:36, textAlign:'right'}}>{[60,72,68,80,55,64][i]}%</span>
            </div>
          ))}
        </div>
      </Card>
    </Grid>
  );
}

function ProdMTO() {
  return (
    <Card icon="📋" title="Make-to-Order (MTO)" badge={`${M.orders.length} orders`} info={{ what:'Per-SKU customer orders; edit home for Order Book.', flows:'MTO floor → demand & profit constraints.' }}
      dev={{ comp:'MTOEditor', props:'state.orders', state:'orders[]' }}>
      <DataTable cols={['PO','Customer','SKU','Qty','Due','Price','Status']} align={['left','left','left','right','right','right','left']}
        rows={M.orders.map(o=>({cells:[o.po, o.cust, o.sku, o.qty, o.due.slice(5), `₹${o.price}`, <Tag c={o.status==='firm'?'g':'w'}>{o.status}</Tag>]}))}
        foot={['TOTAL','6 customers','','—','','₹ 48.6 L','']}/>
    </Card>
  );
}

function ProdEvents() {
  return (
    <Card icon="📅" title="Cost Events · Rolling Horizon" badge={`${M.costEvents.length} events`} info={{ what:'Period-indexed cost step-changes over the horizon.', flows:'Time-phased costs → rolling-horizon solver.' }}
      dev={{ comp:'CostEventEditor', props:'state.costEvents', state:'costEvents[]' }}>
      <DataTable cols={['Week','Item','Change','Delta','Reason']} align={['left','left','left','right','left']}
        rows={M.costEvents.map(e=>({cells:[e.wk, e.item, e.kind, <span style={{color:e.delta[0]==='+'?C.dg:C.gn, fontWeight:700}}>{e.delta}</span>, e.reason]}))}/>
      <div style={{marginTop:12}}>
        <SubLabel>Cost index timeline · 52w</SubLabel>
        <svg viewBox="0 0 700 80" style={{width:'100%', height:80, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
          <polyline points="0,50 110,50 110,40 200,40 200,46 310,46 310,40 440,40 440,52 700,52" fill="none" stroke={C.ink} strokeWidth="2"/>
          {[['W08',110],['W14',200],['W22',310],['W31',440]].map(([w,x],i)=>(
            <g key={i}><line x1={x} y1="10" x2={x} y2="70" stroke={C.ac} strokeWidth="1.5" strokeDasharray="3 2"/><text x={x+3} y="20" fontFamily={F.mono} fontSize="9" fill={C.tx2}>{w}</text></g>
          ))}
        </svg>
      </div>
    </Card>
  );
}
window.StageProducts = StageProducts;
