// ════════════════════════════════════════════════════════════════════════
// finance.jsx — Finance & Costs (FinanceTab). The sub-tab PATTERN source (P3).
// cashflow · capital · decisions(7B) · assets · bvl · cac · fx.
// Single canonical WACC editor lives here (P4).
// ════════════════════════════════════════════════════════════════════════
function StageFinance({ onNav }) {
  const [sub, setSub] = useState('cashflow');
  const tabs = M.financeSubtabs.map(t=>({ id:t.id, n:t.n, label:t.label, count:t.count }));
  return (
    <div>
      <StageHeader n="08" title="Finance & Costs" kicker="Cash flow · capital structure · capital decisions · assets · buy-vs-lease · CAC · FX hedging"
        right={<Btn kind="secondary">📄 Board pack</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='cashflow'  && <FinCashflow/>}
        {sub==='capital'   && <FinCapital/>}
        {sub==='decisions' && <FinDecisions/>}
        {sub==='assets'    && <FinAssets/>}
        {sub==='bvl'       && <FinBVL/>}
        {sub==='cac'       && <FinCAC/>}
        {sub==='fx'        && <FinFX/>}
      </div>
    </div>
  );
}

function FinCashflow() {
  const cf=M.cashflow, mx=Math.max(...cf.map(m=>m.net))*1.15;
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Working Capital — Period View" badge="6 months" info={{ what:'AR, AP, inventory and net working capital by month.', flows:'WC → cash cycle & budget gate.' }} span={2}
        dev={{ comp:'WorkingCapitalPeriodCard', props:'state.finance.cashflow', state:'finance.cashflow[]' }}>
        <div style={{display:'flex', alignItems:'flex-end', gap:14, height:140, padding:'0 6px'}}>
          {cf.map((m,i)=>(
            <div key={i} style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:5}}>
              <div style={{width:'100%', display:'flex', gap:3, alignItems:'flex-end', height:110, justifyContent:'center'}}>
                <div style={{width:14, height:`${m.ar/mx*100}%`, background:C.ink}} title="AR"/>
                <div style={{width:14, height:`${m.ap/mx*100}%`, background:C.ac}} title="AP"/>
                <div style={{width:14, height:`${m.inv/mx*100}%`, background:C.a2}} title="Inv"/>
              </div>
              <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>{m.m}</span>
            </div>
          ))}
        </div>
        <div style={{marginTop:8, display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2}}>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ink}}/>AR</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ac}}/>AP</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.a2}}/>Inventory</span>
          <span style={{marginLeft:'auto'}}>₹ Cr</span>
        </div>
      </Card>
      <Card icon="📒" title="Payment Ledger" badge="43B(h)" info={{ what:'Payables aged against the 45-day MSME rule.', flows:'Late MSME payments → tax disallowance.' }}
        dev={{ comp:'PaymentLedgerCard', props:'state.finance.payables' }}>
        <DataTable dense cols={['Vendor','Amount','Age','Status']} align={['left','right','right','left']}
          rows={[['Bharat Forge','₹4.2L','22d',<Tag c="g">ok</Tag>],['Sundaram (MSME)','₹1.8L','41d',<Tag c="a">due soon</Tag>],['POSCO','₹7.2L','18d',<Tag c="g">ok</Tag>],['Kalyani (MSME)','₹0.9L','47d',<Tag c="r">43B risk</Tag>]]}/>
      </Card>
      <Card icon="📈" title="Budget — Plan vs Actual" badge="variance" info={{ what:'Budget heads: planned vs actual with variance.', flows:'Variance → re-forecast & control tower.' }}
        dev={{ comp:'BudgetPlanVsActualCard', props:'state.budget, actuals' }}>
        <DataTable dense cols={['Head','Plan','Actual','Var']} align={['left','right','right','right']}
          rows={[['Procurement','₹8.5L','₹8.1L',<span style={{color:C.gn,fontWeight:700}}>-5%</span>],['CapEx','₹2.2L','₹2.4L',<span style={{color:C.dg,fontWeight:700}}>+9%</span>],['Logistics','₹1.4L','₹1.3L',<span style={{color:C.gn,fontWeight:700}}>-7%</span>],['WC','₹3.8L','₹3.8L',<span style={{color:C.tx2}}>0%</span>]]}/>
      </Card>
    </Grid>
  );
}

function FinCapital() {
  const w=M.wacc;
  return (
    <Grid cols={3}>
      <Card icon="💹" title="WACC Calculator" badge="EDITOR" badgeTone="y" info={{ what:'The single source-of-truth discount rate (Setup shows read-only).', flows:'WACC → NPV, capital budget, Plan NPV.' }}
        dev={{ comp:'WACCCard', props:'state.finance.wacc, dispatch(SET_FINANCE)', state:'finance.wacc', note:'P4: canonical editor. Setup mirrors read-only.' }}>
        <Grid cols={2} gap={8}>
          <Field label="Risk-free Rf"><NumInput value={w.rf} suffix="%"/></Field>
          <Field label="Beta β"><NumInput value={w.beta}/></Field>
          <Field label="Equity Risk Prem"><NumInput value={w.erp} suffix="%"/></Field>
          <Field label="Cost of Debt"><NumInput value={w.kd} suffix="%"/></Field>
          <Field label="Equity Weight"><NumInput value={w.eWeight} suffix="%"/></Field>
          <Field label="Tax Rate"><NumInput value={w.taxShield} suffix="%"/></Field>
        </Grid>
        <div style={{marginTop:10, display:'flex', alignItems:'center', gap:12, padding:'10px', background:C.ink, color:C.paper}}>
          <Ring pct={w.rate*5} size={56} label={w.rate+'%'} color={C.ac}/>
          <div><div style={{fontFamily:F.mono, fontSize:9, color:C.ac}}>WACC</div><div style={{fontFamily:F.disp, fontSize:24, fontWeight:900}}>{w.rate}%</div></div>
          <div style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9, textAlign:'right', lineHeight:1.6}}>Ke {w.ke}%<br/>Kd(1-t) {(w.kd*(1-w.taxShield/100)).toFixed(1)}%</div>
        </div>
      </Card>
      <Card icon="💎" title="NPV / IRR Calculator" badge="DCF" info={{ what:'Discounted cash flow of the investment program.', flows:'NPV/IRR → investment verdict.' }} span={2}
        dev={{ comp:'NPVCard', props:'cashflows, wacc' }}>
        <div style={{display:'flex', gap:14}}>
          <div style={{flex:1}}>
            <svg viewBox="0 0 380 150" style={{width:'100%', height:150, display:'block'}}>
              <line x1="20" y1="100" x2="370" y2="100" stroke={C.line} strokeWidth="1.5"/>
              {M.npv.map((p,i)=>{ const x=30+i*58, h=Math.abs(p.dcf)/22000000*70;
                return <g key={i}><rect x={x} y={p.dcf<0?100:100-h} width="34" height={h} fill={p.dcf<0?C.dg:C.ink}/><text x={x+17} y="115" fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{p.y}</text></g>;
              })}
            </svg>
          </div>
          <div style={{width:170}}>
            <KpiRow cols={1}>
              <Blk label="NPV @ 11.4%" value="₹ 13.7 L" tone="y"/>
              <Blk label="IRR" value="14.8%" accent={C.gn}/>
              <Blk label="Payback" value="3.2 yr"/>
              <Blk label="PI" value="1.06×"/>
            </KpiRow>
          </div>
        </div>
      </Card>
      <Card icon="🏦" title="Master Budget & Capital Structure" badge="₹15 Cr" info={{ what:'Total capital and its debt/equity split.', flows:'Structure → WACC weights.' }}
        dev={{ comp:'CapStructureCard', props:'state.budget, finance.wacc' }}>
        <div style={{display:'flex', height:26, border:`2px solid ${C.line}`, marginBottom:10}}>
          <div style={{width:`${w.eWeight}%`, background:C.ink, color:C.paper, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>EQUITY {w.eWeight}%</div>
          <div style={{width:`${w.dWeight}%`, background:C.ac, color:C.onAc, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>DEBT {w.dWeight}%</div>
        </div>
        <KpiRow cols={2}><Blk label="Equity" value="₹ 9.3 Cr"/><Blk label="Debt" value="₹ 5.7 Cr"/></KpiRow>
      </Card>
      <Card icon="📈" title="Plan NPV (MPS-driven)" badge="endogenous" info={{ what:'NPV computed from the actual production plan cash flows.', flows:'Links plan → valuation.' }} span={2}
        dev={{ comp:'PlanNPVCard', props:'mps, finance' }}>
        <div style={{display:'flex', gap:14, alignItems:'center'}}>
          <Blk label="Plan NPV" value="₹ 11.2 L" tone="y"/>
          <Blk label="vs Static" value="-18%" accent={C.dg}/>
          <div style={{flex:1, fontFamily:F.mono, fontSize:10, color:C.tx2, lineHeight:1.5}}>Plan-driven NPV is lower than static because capacity limits defer Q3 demand — investment in LINE-03 closes the gap (see Capital Decisions).</div>
        </div>
      </Card>
    </Grid>
  );
}

function FinDecisions() {
  return (
    <Grid cols={3}>
      <Card icon="💎" title="Investment Decision" badge="LINE-03" badgeTone="y" info={{ what:'Whether to add capacity given shadow prices & NPV.', flows:'Verdict → capital budget solver.' }}
        dev={{ comp:'InvestmentDecisionTab', props:'state.investment', state:'investment.proposals[]' }}>
        <Blk label="Proposal" value="Heat-Treat #2" tone="c"/>
        <div style={{marginTop:8}}><KpiRow cols={2}><Blk label="CapEx" value="₹ 1.8 Cr"/><Blk label="NPV" value="₹ 24 L" tone="y"/></KpiRow></div>
        <div style={{marginTop:8}}><KpiRow cols={2}><Blk label="IRR" value="19.2%" accent={C.gn}/><Blk label="Payback" value="2.6 yr"/></KpiRow></div>
      </Card>
      <Card icon="🏗️" title="Endogenous-Capacity Capital Plan" badge="from duals" info={{ what:'Capacity investments driven by aggregate shadow prices.', flows:'Consumes Plan duals → capital MILP.' }}
        dev={{ comp:'EndogenousCapacityCard', props:'aggregatePlan.shadow', note:'Consumes Aggregate shadow prices.' }}>
        <DataTable dense cols={['Resource','Dual','Add','ΔNPV']} align={['left','right','right','right']}
          rows={[['Line-1 cap','₹1248','+10%','+₹14L'],['Line-2 cap','₹980','+8%','+₹9L'],['Heat Treat','₹0','#2 unit','+₹24L']]}/>
      </Card>
      <Card icon="⚖️" title="Investment Verdict" badge="APPROVED" badgeTone="k" info={{ what:'Final go/no-go on the capital program.', flows:'Verdict → budget lock.' }}
        dev={{ comp:'VerdictCard', props:'investment (computed)' }}>
        <div style={{padding:'16px', background:C.gn, color:'#fff', textAlign:'center'}}>
          <div style={{fontFamily:F.disp, fontSize:24, fontWeight:900}}>✓ APPROVE</div>
          <div style={{fontFamily:F.mono, fontSize:10, marginTop:4}}>NPV+ at 11.4% WACC · IRR &gt; hurdle</div>
        </div>
      </Card>
      <Card icon="📊" title="Cash Flow Builder" badge="5-year" info={{ what:'Build out year-by-year project cash flows.', flows:'Feeds NPV/IRR.' }} span={2}
        dev={{ comp:'CashFlowBuilder', props:'state.investment.cashflows' }}>
        <DataTable dense cols={['Year','Capex','Revenue','Opex','Net CF','DCF']} align={['left','right','right','right','right','right']}
          rows={M.npv.map((p,i)=>[p.y, i===0?'₹22L':'—', i?`₹${(8+i*0.6).toFixed(1)}L`:'—', i?`₹${(2+i*0.2).toFixed(1)}L`:'—', `₹${(p.cf/100000).toFixed(1)}L`, `₹${(p.dcf/100000).toFixed(1)}L`])}/>
      </Card>
      <Card icon="🏦" title="Equity Sources & Opportunity Cost" badge="funding" info={{ what:'Where equity comes from and its opportunity cost.', flows:'Funding mix → Ke.' }}
        dev={{ comp:'EquitySourcesCard', props:'finance.equity' }}>
        <DataTable dense cols={['Source','Amount','Opp Cost']} align={['left','right','right']}
          rows={[['Retained','₹5.4 Cr','14.2%'],['Promoter','₹2.9 Cr','12.0%'],['PE round','₹1.0 Cr','18.0%']]}/>
      </Card>
      <Card icon="🏭" title="Per-Line CapEx Proposals" badge="3 lines" info={{ what:'CapEx asks per production line.', flows:'Ranked by ΔNPV / ₹.' }} span={3}
        dev={{ comp:'PerLineCapexCard', props:'lines, investment' }}>
        <DataTable cols={['Line','Proposal','CapEx','ΔCapacity','NPV','IRR','Rank']} align={['left','left','right','right','right','right','right']}
          rows={[['LINE-03','Heat-Treat #2','₹1.8 Cr','+38%','₹24L','19.2%',<Tag c="y">1</Tag>],['LINE-01','Grinder upgrade','₹0.9 Cr','+12%','₹14L','16.4%',<Tag c="w">2</Tag>],['LINE-02','Honing cell','₹1.2 Cr','+9%','₹9L','13.1%',<Tag c="w">3</Tag>]]}/>
      </Card>
    </Grid>
  );
}

function FinAssets() {
  const fmt=n=>`₹${(n/100000).toFixed(1)}L`;
  return (
    <Grid cols={2}>
      <Card icon="🏭" title="Asset Register" badge={`${M.assets.length} assets`} info={{ what:'Capital assets: cost, life, age, written-down value.', flows:'Assets → depreciation & WC.' }} span={2}
        dev={{ comp:'AssetRegisterCard', props:'state.finance.assets', state:'finance.assets[]' }}>
        <DataTable cols={['ID','Asset','Cost','Life','Age','WDV','Annual Dep']} align={['left','left','right','right','right','right','right']}
          rows={M.assets.map(a=>[a.id, a.name, fmt(a.cost), `${a.life}y`, `${a.age}y`, fmt(a.wdv), fmt(a.dep)])}
          foot={['TOTAL','4 assets','₹238L','','','₹183L','₹21.9L']}/>
      </Card>
      <Card icon="📉" title="Asset Depreciation" badge="WDV method" info={{ what:'Depreciation schedule over remaining life.', flows:'Dep → P&L & tax shield.' }} span={2}
        dev={{ comp:'DepreciationCard', props:'assets' }}>
        <div style={{display:'flex', alignItems:'flex-end', gap:8, height:90}}>
          {[238,183,142,110,86,68].map((v,i)=>(
            <div key={i} style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:4}}>
              <div style={{width:'68%', height:`${v/238*78}px`, background:i===0?C.ink:C.bg4, border:`2px solid ${C.line}`}}/>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx2}}>Y{i}</span>
            </div>
          ))}
        </div>
        <div style={{marginTop:6, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Net block ₹ Lakhs · WDV declining balance.</div>
      </Card>
    </Grid>
  );
}

function FinBVL() {
  return (
    <Card icon="🔄" title="Buy vs Lease" badge="decision" info={{ what:'NPV comparison of buying vs leasing an asset.', flows:'Lower-cost option → capital plan.' }}
      dev={{ comp:'BuyVsLeaseCard', props:'asset, wacc' }}>
      <Grid cols={2}>
        <div style={{border:`2px solid ${C.line}`, padding:14}}>
          <div style={{fontFamily:F.disp, fontSize:14, fontWeight:800, marginBottom:8}}>BUY · DMG CNC</div>
          <KpiRow cols={1}>
            <Blk label="Upfront" value="₹ 84 L"/>
            <Blk label="PV of costs" value="₹ 71 L" tone="c"/>
            <Blk label="Tax shield" value="₹ 13 L" accent={C.gn}/>
          </KpiRow>
        </div>
        <div style={{border:`2px solid ${C.line}`, padding:14, background:C.ac}}>
          <div style={{fontFamily:F.disp, fontSize:14, fontWeight:800, marginBottom:8}}>LEASE · 5yr ✓</div>
          <KpiRow cols={1}>
            <Blk label="Annual lease" value="₹ 18 L"/>
            <Blk label="PV of costs" value="₹ 66 L" tone="k"/>
            <Blk label="Flexibility" value="HIGH"/>
          </KpiRow>
        </div>
      </Grid>
      <div style={{marginTop:10, padding:'10px', background:C.gn, color:'#fff', fontFamily:F.disp, fontWeight:800, fontSize:14, textAlign:'center'}}>
        ✓ LEASE wins by ₹5L PV — preserves working capital for procurement
      </div>
    </Card>
  );
}

function FinCAC() {
  const c=M.cac;
  return (
    <Grid cols={2}>
      <Card icon="🎯" title="Customer Acquisition Economics" badge={`LTV:CAC ${c.ltvcac}×`} badgeTone="y" info={{ what:'Full CAC economics (Setup shows the anchor only).', flows:'Unit economics → growth budget.' }} span={2}
        dev={{ comp:'CACCard', props:'state.finance.cac', state:'finance.cac' }}>
        <KpiRow cols={4}>
          <Blk label="Blended CAC" value={`₹${c.blended.toLocaleString('en-IN')}`} tone="c"/>
          <Blk label="Payback" value={c.payback}/>
          <Blk label="LTV" value={`₹${(c.ltv/1000)}K`} tone="y"/>
          <Blk label="LTV : CAC" value={`${c.ltvcac}×`} accent={C.gn}/>
        </KpiRow>
        <div style={{marginTop:12}}>
          <SubLabel>CAC by channel</SubLabel>
          <DataTable dense cols={['Channel','CAC','Mix %']} align={['left','right','right']}
            rows={c.channels.map(ch=>[ch.ch, `₹${ch.cac.toLocaleString('en-IN')}`, `${ch.share}%`])}/>
        </div>
      </Card>
    </Grid>
  );
}

function FinFX() {
  return (
    <Grid cols={2}>
      <Card icon="🛡️" title="Currency Hedging" badge="exposures" info={{ what:'FX exposures and hedge coverage.', flows:'Hedge → procurement risk.' }} span={2}
        dev={{ comp:'CurrencyHedgeCard', props:'state.finance.fx', state:'finance.fxHedge[]' }}>
        <DataTable cols={['Exposure','Amount','Due','Hedge Instrument','Coverage']} align={['left','right','left','left','right']}
          rows={M.fxHedge.map(h=>({cells:[h.exp, h.amt, h.due, h.hedge, <Tag c={h.cover==='0%'?'r':h.cover==='60%'?'a':'g'}>{h.cover}</Tag>]}))}/>
      </Card>
      <Card icon="⚠" title="Procurement Risk & FX" badge="VaR" info={{ what:'Combined supply + currency risk on procurement spend.', flows:'Risk → hedge decision & Monte Carlo.' }} span={2}
        dev={{ comp:'ProcurementRiskCard', props:'fx, suppliers' }}>
        <KpiRow cols={3}>
          <Blk label="Unhedged FX" value="€12.0K" accent={C.dg}/>
          <Blk label="VaR @95%" value="₹ 2.4 L" tone="c"/>
          <Blk label="If ₹→86.5" value="+₹1.8L cost" accent={C.dg}/>
        </KpiRow>
        <div style={{marginTop:10, padding:'8px 10px', border:`2px dashed ${C.a4}`, fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>
          ⚠ EUR steel import unhedged — recommend forward cover before W26 (see Scenarios · What-If).
        </div>
      </Card>
    </Grid>
  );
}
window.StageFinance = StageFinance;
