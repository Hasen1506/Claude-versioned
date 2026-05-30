// ════════════════════════════════════════════════════════════════════════
// setup.jsx — Setup (SetupTab). Sub-tabs: Company · Calendar · Locations · Budget
// Includes read-only WACC (P4) with "edit in Finance →".
// ════════════════════════════════════════════════════════════════════════
function StageSetup({ onNav }) {
  const [sub, setSub] = useState('company');
  const tabs = [
    { id:'company',   n:'a', label:'Company', count:4 },
    { id:'calendar',  n:'b', label:'Calendar', count:1 },
    { id:'locations', n:'c', label:'Locations', count:3 },
    { id:'budget',    n:'d', label:'Budget', count:3 },
  ];
  return (
    <div>
      <StageHeader n="01" title="Setup · Company & Calendar" kicker="Global identity · fiscal parameters · planning calendar · budget envelopes"
        right={<Btn kind="secondary">⤓ Import JSON</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='company'   && <SetupCompany onNav={onNav}/>}
        {sub==='calendar'  && <SetupCalendar/>}
        {sub==='locations' && <SetupLocations/>}
        {sub==='budget'    && <SetupBudget/>}
      </div>
    </div>
  );
}

function KV({ rows }) {
  return (
    <div>
      {rows.map(([k,v,edit],i)=>(
        <div key={i} style={{display:'grid', gridTemplateColumns:'150px 1fr', alignItems:'center', borderTop:i?`1px solid ${C.line2}`:'none', padding:'8px 0', gap:10}}>
          <span style={{fontFamily:F.mono, fontSize:10, color:C.tx3, letterSpacing:'.06em'}}>{k}</span>
          {edit ? <TextInput value={v}/> : <span style={{fontFamily:F.disp, fontSize:13, fontWeight:600}}>{v}</span>}
        </div>
      ))}
    </div>
  );
}

function SetupCompany({ onNav }) {
  const w = M.wacc;
  return (
    <Grid cols={3}>
      <Card icon="🏢" title="Company Profile" badge="GST · REG" info={{ what:'Legal identity, currency, tax regime, service level.', flows:'Tax rate → Finance; service level → safety stock.' }}
        dev={{ comp:'SetupTab', props:'state.config', state:'config.company, config.currency, config.taxRate' }}>
        <KV rows={[['Company Name', M.company, true],['Legal Entity','Private Limited · TN'],['CIN', M.cin],['GSTIN', M.gstin],['Base Currency','₹ INR · ₹84.20/$', true],['Effective Tax','25.17 %'],['Service Level','95.0 % (z=1.645)', true]]}/>
        <div style={{marginTop:12, display:'flex', gap:6, flexWrap:'wrap'}}>
          <Tag c="k">GST · REGISTERED</Tag><Tag c="y">ITC RECOVERABLE</Tag><Tag c="w">MSME · SMALL</Tag>
        </div>
      </Card>

      <Card icon="🏷️" title="MSME Classification" badge="SMALL" badgeTone="y" info={{ what:'Investment & turnover → MSME tier; drives 43B(h) payment terms.', flows:'Payment terms → Sourcing & Finance.' }}
        dev={{ comp:'SetupTab', props:'state.config.msme', state:'config.msme.tier' }}>
        <Grid cols={2} gap={8}>
          <Field label="Plant & Machinery"><NumInput value="9.40" prefix="₹" suffix="Cr"/></Field>
          <Field label="Annual Turnover"><NumInput value="38.40" prefix="₹" suffix="Cr"/></Field>
        </Grid>
        <div style={{marginTop:10, display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:6}}>
          {[['MICRO',false],['SMALL',true],['MEDIUM',false]].map(([n,a],i)=>(
            <div key={i} style={{padding:'10px', border:`2px solid ${C.line}`, background:a?C.ink:C.paper, color:a?C.ac:C.tx, fontFamily:F.disp, fontWeight:800, fontSize:12, textAlign:'center'}}>{a?'▶ ':''}{n}</div>
          ))}
        </div>
        <div style={{marginTop:10, padding:'8px 10px', background:C.bg3, border:`2px solid ${C.line2}`, fontFamily:F.mono, fontSize:10, lineHeight:1.5}}>
          ◆ 43B(h): payments to MSME suppliers due in <b>45 days</b> or disallowed for tax. Applied in Sourcing terms.
        </div>
      </Card>

      <Card icon="💹" title="WACC (read-only)" badge="11.40%" badgeTone="k" info={{ what:'Discount rate for all NPV/capital decisions.', flows:'Used by Finance NPV, Capital Budget solver.' }}
        right={<button onClick={()=>onNav('finance')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>edit in Finance →</button>}
        dev={{ comp:'WACCCard', props:'state.finance.wacc (readOnly)', note:'P4: single editor lives on Finance. Shown read-only here.' }}>
        <div style={{display:'flex', alignItems:'center', gap:14}}>
          <Ring pct={w.rate*4} size={72} label={w.rate+'%'} color={C.ac}/>
          <div style={{flex:1}}>
            <KpiRow cols={2}>
              <Blk label="Cost of Equity" value={w.ke+'%'} tone="c"/>
              <Blk label="Cost of Debt" value={w.kd+'%'} tone="c"/>
            </KpiRow>
            <div style={{marginTop:8, display:'flex', height:20, border:`2px solid ${C.line}`}}>
              <div style={{width:`${w.eWeight}%`, background:C.ink, color:C.paper, fontFamily:F.mono, fontSize:9, display:'grid', placeItems:'center'}}>E {w.eWeight}%</div>
              <div style={{width:`${w.dWeight}%`, background:C.ac, color:C.onAc, fontFamily:F.mono, fontSize:9, display:'grid', placeItems:'center'}}>D {w.dWeight}%</div>
            </div>
          </div>
        </div>
        <div style={{marginTop:10, fontFamily:F.mono, fontSize:10, color:C.tx3}}>β {w.beta} · Rf {w.rf}% · ERP {w.erp}% · tax shield {w.taxShield}%</div>
      </Card>

      <Card icon="🎯" title="CAC Summary" badge="ANCHOR" info={{ what:'Cost-to-acquire anchor; full economics on Finance.', flows:'LTV/CAC → Finance · CAC sub-tab.' }} span={3}
        right={<button onClick={()=>onNav('finance')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>full economics in Finance →</button>}
        dev={{ comp:'CACSummary', props:'state.finance.cac (anchor)' }}>
        <KpiRow cols={4}>
          <Blk label="Blended CAC" value={`₹${M.cac.blended.toLocaleString('en-IN')}`} tone="y"/>
          <Blk label="Payback" value={M.cac.payback}/>
          <Blk label="LTV" value={`₹${(M.cac.ltv/1000)}K`}/>
          <Blk label="LTV : CAC" value={`${M.cac.ltvcac}×`} accent={C.gn}/>
        </KpiRow>
      </Card>
    </Grid>
  );
}

function SetupCalendar() {
  return (
    <Grid cols={3}>
      <Card icon="📅" title="Planning Calendar" badge="52w" info={{ what:'Horizon × unit, grain, workdays, frozen/slushy fences.', flows:'Time grain → all solvers & forecasts.' }}
        dev={{ comp:'SetupTab', props:'state.planning', state:'planning.horizon, planning.grain, planning.workdays' }} span={1}>
        <KV rows={[['Work Days / Week','6 (Mon–Sat)', true],['Horizon','52 weeks · weekly', true],['Frozen / Slushy','4w / 12w', true],['Working Days 2026','270 of 365'],['Gazetted Holidays','22 excluded'],['OEE Benchmark','82 % (auto)']]}/>
      </Card>

      <Card icon="📆" title="TN Gazetted Holidays 2026" badge="22" info={{ what:'State holidays removed from available workdays.', flows:'Net workdays → capacity calc.' }}
        dev={{ comp:'HolidayEditor', props:'state.planning.holidays' }} span={2}>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'2px 16px'}}>
          {M.holidays.map(([d,n],i)=>(
            <div key={i} style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:11, padding:'5px 0', borderBottom:`1px dotted ${C.line2}`}}>
              <span style={{fontWeight:700}}>{d}</span><span style={{color:C.tx2}}>{n}</span>
            </div>
          ))}
        </div>
        <div style={{marginTop:12}}>
          <SubLabel>Workday availability · 2026</SubLabel>
          <div style={{display:'flex', height:26, border:`2px solid ${C.line}`}}>
            <div style={{width:'74%', background:C.gn, color:'#fff', display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>270 WORKDAYS</div>
            <div style={{width:'14%', background:C.bg3, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9}}>52 WK-OFF</div>
            <div style={{width:'12%', background:C.ac, color:C.onAc, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, fontWeight:700}}>22 HOL</div>
          </div>
        </div>
      </Card>
    </Grid>
  );
}

function SetupLocations() {
  const onhand = [['PLANT-CHN','RM-STL42','4,200 kg'],['PLANT-CHN','RM-BRG18','1,800 kg'],['WH-CHN','TPA-4471','340 u'],['DC-BLR','TPA-3215','620 u'],['DC-PUN','TPA-9904','180 u']];
  return (
    <Grid cols={2}>
      <Card icon="📍" title="Locations Master" badge={`${M.nodes.length} nodes`} info={{ what:'Physical nodes: plant, WH, DC, customer, supplier.', flows:'Network topology → Logistics & Transport solver.' }}
        dev={{ comp:'SetupTab', props:'state.network.nodes', state:'network.nodes[]' }}>
        <DataTable cols={['Node','Type','Location','Capacity']} align={['left','left','left','right']}
          rows={M.nodes.map(n=>[n.id, n.type, n.name, n.cap])}/>
      </Card>
      <Card icon="📦" title="Per-Location On-Hand" badge="opening" info={{ what:'Starting inventory per site at horizon start.', flows:'Initial stock → MRP & inventory projection.' }}
        dev={{ comp:'OnHandEditor', props:'state.network.onHand', state:'network.onHand[node][sku]' }}>
        <DataTable cols={['Node','Item','On-Hand']} align={['left','left','right']} rows={onhand}/>
      </Card>
      <Card icon="🚚" title="Transport Modes & Contracts" badge="4 modes" info={{ what:'Mode rates and contract types available to solvers.', flows:'Mode/rate → Transport MILP & landed cost.' }} span={2}
        dev={{ comp:'TransportModeEditor', props:'state.network.modes', state:'network.modes[]' }}>
        <DataTable cols={['Mode','Basis','Rate','Min Charge','Transit','Contract']} align={['left','left','right','right','right','left']}
          rows={[['FTL','per km','₹14','₹4,200','1.0 d','Spot'],['LTL','per kg','₹22','₹850','2.5 d','Annual'],['Rail','per km','₹6.2','₹12,000','3.0 d','CONCOR'],['Air','per kg','₹88','₹3,500','0.5 d','Spot']]}/>
      </Card>
    </Grid>
  );
}

function SetupBudget() {
  return (
    <Grid cols={3}>
      <Card icon="💰" title="Master Budget Envelope" badge="HARD CAP" badgeTone="k" info={{ what:'Split capital across 5 heads + reserve. Hard solver constraints.', flows:'Caps → every MILP budget constraint.' }}
        dev={{ comp:'SetupTab', props:'state.budget', state:'budget.procurement, budget.capex, budget.wc' }}>
        <Grid cols={2} gap={8}>
          <Blk label="Procurement" value="₹ 8.50 Cr" sub="per quarter" tone="y"/>
          <Blk label="CapEx" value="₹ 2.20 Cr" sub="FY 26-27"/>
          <Blk label="Working Capital" value="₹ 3.80 Cr" sub="max tied-up"/>
          <Blk label="Overtime" value="240 hrs" sub="per line/wk"/>
          <Blk label="Logistics" value="₹ 1.40 Cr" sub="annual"/>
          <Blk label="Reserve" value="₹ 0.60 Cr" sub="contingency" tone="c"/>
        </Grid>
        <div style={{marginTop:10}}>
          <SubLabel>Allocation</SubLabel>
          <div style={{display:'flex', height:22, border:`2px solid ${C.line}`}}>
            {[['Proc',50,C.ink],['CapEx',13,C.ac],['WC',22,C.a2],['Log',8,C.gn],['Res',7,C.bg3]].map(([l,w,c],i)=>(
              <div key={i} style={{width:`${w}%`, background:c, color: c===C.bg3?C.tx:'#fff', fontFamily:F.mono, fontSize:8.5, display:'grid', placeItems:'center', borderRight:i<4?`1px solid ${C.paper}`:'none'}}>{l}</div>
            ))}
          </div>
        </div>
      </Card>

      <Card icon="🎯" title="Industry Preset" badge="AUTOMOTIVE" badgeTone="y" info={{ what:'One-shot defaults: OEE, quality regime, safety, lot policy.', flows:'Seeds every SKU/line default — override per SKU.' }}
        dev={{ comp:'IndustryPreset', props:'dispatch(APPLY_PRESET)', note:'Wizard-style one-shot.' }}>
        <Grid cols={2} gap={6}>
          {[['AUTOMOTIVE',true],['FMCG',false],['HEAVY ENG.',false],['PHARMA',false]].map(([n,a],i)=>(
            <div key={i} style={{padding:'9px 10px', border:`2px solid ${C.line}`, background:a?C.ink:C.paper, color:a?C.ac:C.tx, fontFamily:F.disp, fontSize:11, fontWeight:800}}>{a?'▶ ':'   '}{n}</div>
          ))}
        </Grid>
        <div style={{marginTop:10, padding:'9px 10px', background:C.ac, color:C.onAc, fontFamily:F.mono, fontSize:10, fontWeight:600, lineHeight:1.5}}>
          ◆ Seeds OEE 82%, IATF 16949 quality, 15-day safety, JIT lean lot policy.
        </div>
      </Card>

      <Card icon="📋" title="Order Book (read-only)" badge={`${M.orders.length} MTO`} info={{ what:'All make-to-order demand, read-only here.', flows:'Edits live on Products · MTO.' }}
        right={<button onClick={()=>onNav('products')} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>edit on Products →</button>}
        dev={{ comp:'OrderBookView', props:'state.orders (readOnly)' }}>
        <DataTable dense cols={['PO','Customer','SKU','Qty','Due']} align={['left','left','left','right','right']}
          rows={M.orders.slice(0,5).map(o=>[o.po, o.cust, o.sku, o.qty, o.due.slice(5)])}/>
      </Card>
    </Grid>
  );
}
window.StageSetup = StageSetup;
