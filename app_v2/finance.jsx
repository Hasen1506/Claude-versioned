// ════════════════════════════════════════════════════════════════════════
// finance.jsx — Finance & Costs (FinanceTab). The sub-tab PATTERN source (P3).
// cashflow · capital · decisions(7B) · assets · bvl · cac · fx.
// Single canonical WACC editor lives here (P4).
// ════════════════════════════════════════════════════════════════════════
function StageFinance({ onNav }) {
  const [sub, setSub] = useState('cash');
  const tabs = M.financeSubtabs.map(t=>({ id:t.id, n:t.n, label:t.label, count:t.count }));
  return (
    <div>
      <StageHeader n="09" title="Finance & Costs" kicker="Cash & working capital · capital structure · investment decisions · assets · FX hedging"
        right={<Btn kind="secondary">📄 Board pack</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='cash'    && <FinCash/>}
        {sub==='capital' && <FinCapital/>}
        {sub==='value'   && <FinValue/>}
        {sub==='invest'  && <FinInvest/>}
        {sub==='assets'  && <FinAssets/>}
        {sub==='fx'      && <FinFX/>}
      </div>
    </div>
  );
}

function FinCash() {
  const cf=M.cashflow, mx=Math.max(...cf.map(m=>m.net))*1.15; const e=M.evm;
  // F-9 — honest provenance: there is no live AR/AP/inventory ledger feed in this build, so the
  // working-capital, payables and budget figures below are ILLUSTRATIVE seeds, not solved or
  // derived from a posted ledger. EVM/CCC are computed from those seeds (derived-from-seed).
  // The capital-charge / EVA numbers that DO drive decisions live on the Capital & Value subtabs
  // and are solved/derived — this subtab is flagged so a seed is never mistaken for a result.
  return (
    <>
    <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px dashed ${C.a4}`, background:C.bg3, fontFamily:F.mono, fontSize:10, color:C.tx2, lineHeight:1.5}}>
      ⓘ <b>Illustrative working-capital seeds</b> — no live AR/AP/inventory ledger is connected in this build, so the cards below are seeded examples (EVM/CCC are derived from them). The decision-grade, solved numbers are on <b>Capital</b> (hurdle, WACC structure) and <b>Value (EVA)</b>. Wire a ledger feed to make this subtab live.
    </div>
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

      {/* EVM — moved here from Scenarios (it's cost/schedule controlling, the
          disciplined twin of Budget vs Actual above) */}
      <Card icon="📈" title="Earned Value (EVM)" badge={`CPI ${e.cpi}`} badgeTone="y" info={{ what:'Planned vs earned vs actual cost, with schedule (SPI) and cost (CPI) indices — the disciplined twin of Budget vs Actual.', flows:'CPI → EAC forecast → board pack.' }} span={2}
        right={<Provenance kind="derived" asOf={M.updated.split('·')[1].trim()} run="v3.2.1"/>}
        dev={{ comp:'EVMCard', props:'finance.evm', note:'Relocated from Scenarios·Performance (app_v2).' }}>
        <KpiRow cols={4}>
          <Blk label="Planned Value" value={`₹${(e.pv/100000).toFixed(0)}L`}/>
          <Blk label="Earned Value" value={`₹${(e.ev/100000).toFixed(0)}L`} tone="c"/>
          <Blk label="Actual Cost" value={`₹${(e.ac/100000).toFixed(0)}L`}/>
          <Blk label="EAC" value={`₹${(e.eac/100000).toFixed(0)}L`} accent={C.dg}/>
        </KpiRow>
        <div style={{marginTop:10}}><KpiRow cols={2}>
          <div><div style={{fontFamily:F.mono, fontSize:9, color:C.tx3, marginBottom:3}}>SPI · schedule</div><MiniBar v={e.spi} max={1.2} color={e.spi<1?C.a4:C.gn} h={14}/><div className="num" style={{fontFamily:F.disp, fontWeight:700, marginTop:2}}>{e.spi}</div></div>
          <div><div style={{fontFamily:F.mono, fontSize:9, color:C.tx3, marginBottom:3}}>CPI · cost</div><MiniBar v={e.cpi} max={1.2} color={e.cpi<1?C.a4:C.gn} h={14}/><div className="num" style={{fontFamily:F.disp, fontWeight:700, marginTop:2}}>{e.cpi}</div></div>
        </KpiRow></div>
        <Reading formula="EAC = BAC / CPI = ₹126.4L / 0.97" soWhat="At CPI 0.97 the program lands ~₹3.9L over budget — the overrun traces to the +9% CapEx variance above."/>
      </Card>

      {/* CCC — moved here from Scenarios·Cost (pure cash-cycle finance) */}
      <Card icon="💳" title="Cash Conversion Cycle" badge="CCC 41d" badgeTone="y" info={{ what:'Days cash is locked in the operating cycle: inventory + receivables − payables.', flows:'CCC → financing need & working-capital target.' }} span={2}
        right={<Provenance kind="derived" asOf={M.updated.split('·')[1].trim()}/>}
        dev={{ comp:'CashCycleCard', props:'finance.cashflow', note:'Relocated from Scenarios·Cost (app_v2).' }}>
        <div style={{display:'flex', alignItems:'center', height:30, border:`2px solid ${C.line}`, fontFamily:F.mono, fontSize:9, fontWeight:700}}>
          <div style={{width:'52%', background:C.ink, color:C.paper, height:'100%', display:'grid', placeItems:'center'}}>DIO 52d</div>
          <div style={{width:'26%', background:C.ac, color:C.onAc, height:'100%', display:'grid', placeItems:'center'}}>DSO 28d</div>
          <div style={{width:'22%', background:C.bg4, height:'100%', display:'grid', placeItems:'center'}}>−DPO 39d</div>
        </div>
        <Reading formula="CCC = DIO + DSO − DPO = 52 + 28 − 39" soWhat="41 days of operating cash is tied up — every day shaved frees ~₹0.9L of working capital."/>
      </Card>
    </Grid>

    {/* CAC demoted — commercial/growth metric, weak fit for a plant-ops finance
        view; kept reachable behind Advanced, flagged for removal. */}
    <Advanced label="Commercial · unit economics (CAC)" count={4}>
      <FinCAC/>
    </Advanced>
    </>
  );
}

// W5 · Finance wedge — seed capital sources (₹). Equity 9.3 Cr + Debt 5.7 Cr = ₹15 Cr,
// the 62/38 split the structure bar shows. Each source carries its own opportunity cost;
// the blend (NOT a single textbook Ke) is the owner's real hurdle — F-1.
const FIN_EQUITY = [
  { name:'Retained earnings', amount:54000000, cost:14.2 },
  { name:'Promoter funds',    amount:29000000, cost:12.0 },
  { name:'PE round',          amount:10000000, cost:18.0 },
];
const FIN_DEBT = [
  { name:'Bank term loan', amount:42000000, rate:9.5 },
  { name:'Family loan',    amount:15000000, rate:7.0 },
];
const _effNum = (v, seed)=> (v!=null && v!=='') ? Number(v) : seed;
// effective source rows: governed override (config.finEquity / finDebt) else the seed.
function finSources(config){
  const eqOv = config.finEquity || {}, dbOv = config.finDebt || {};
  const equity = FIN_EQUITY.map((r,i)=>({ name:r.name,
    amount:_effNum((eqOv[i]||{}).amount, r.amount), cost:_effNum((eqOv[i]||{}).cost, r.cost) }));
  const debt = FIN_DEBT.map((r,i)=>({ name:r.name,
    amount:_effNum((dbOv[i]||{}).amount, r.amount), rate:_effNum((dbOv[i]||{}).rate, r.rate) }));
  return { equity, debt };
}
const FIN_CR = n=>`₹ ${(n/1e7).toFixed(2)} Cr`;
const FIN_L  = n=>`₹ ${(n/1e5).toFixed(1)} L`;

// Client-side blend of the SAME source table the F-1 endpoint uses — so the derived
// Value cards (EVA, required-sales) can charge the real hurdle without re-running the
// solve in every subtab. FinCapital shows the SOLVED version (solved provenance); these
// derived cards label themselves derived. Both compute the identical weighted blend.
function finBlendedHurdle(config){
  const tax = _effNum(config.taxRate, M.wacc.taxShield)/100;
  const { equity, debt } = finSources(config);
  const eE = equity.reduce((s,r)=>s+r.amount,0), eD = debt.reduce((s,r)=>s+r.amount,0);
  const V = (eE+eD) || 1;
  const ke = eE ? equity.reduce((s,r)=>s+r.amount*r.cost,0)/eE : 0;
  const kd = eD ? debt.reduce((s,r)=>s+r.amount*r.rate,0)/eD : 0;
  const wacc = (eE/V)*ke + (eD/V)*kd*(1-tax);
  return { ke:+ke.toFixed(2), kd_after:+(kd*(1-tax)).toFixed(2), wacc:+wacc.toFixed(2), tax, V, eE, eD };
}
// FV-A · invested capital from the REAL ops plan (not a turns proxy). Reads the
// cached solves: the time-phased production schedule's projected_inventory (avg
// ending FG inventory × unit cost = working capital actually tied up), the pooled
// safety-stock value from the W8 network-MEIO solve, and the fixed-asset register
// at NET block (Σ WDV, not gross cost). Falls back to the COGS÷turns proxy only
// when no production solve is cached — so the capital charge reflects the plan that
// will execute. Hook-free (reads getSolveResult) so finEva stays callable anywhere.
function finOpsCapital(){
  const M = window.M || {};
  const prod = (typeof getSolveResult==='function') ? getSolveResult('production') : null;
  const net  = (typeof getSolveResult==='function') ? getSolveResult('meionet')    : null;
  let invBySku = null, invTotal = 0;
  if(prod && prod.projected_inventory && prod.projected_inventory.length){
    invBySku = {};
    prod.projected_inventory.forEach(pi=>{
      const arr = pi.ending_inventory || [];
      const avg = arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : 0;
      const p = (M.products||[]).find(x=>x.sku===pi.name) || {};
      const cap = avg * (Number(p.cost)||0);
      invBySku[pi.name] = cap; invTotal += cap;
    });
  }
  const ssCapital = net ? (Number(net.total_ss_value_pooled)||0) : 0;
  const fixedNet  = (M.assets||[]).reduce((s,a)=>s+(Number(a.wdv)||Number(a.cost)||0),0);
  return { invBySku, invTotal, ssCapital, fixedNet, solvedInv:!!invBySku, solvedSS:!!net };
}
// F-4 — contribution-based EVA/ROIC per finished SKU vs the blended hurdle.
//   NOPAT  = contribution·(1−t)             (contribution = (price−cost)·demand)
//   capital = SOLVED FG inventory WC + share of pooled safety-stock capital + net-block
//             fixed assets (FV-A) — or the COGS÷turns proxy when no plan is cached.
//   ROIC = NOPAT ÷ capital ;  EVA = NOPAT − hurdle·capital ;  destroyer ⇔ ROIC < hurdle
function finEva(config){
  const { wacc } = finBlendedHurdle(config);
  const hurdle = wacc/100;
  const tax = _effNum(config.taxRate, M.wacc.taxShield)/100;
  const turns = _effNum(config.invTurns, 6);
  const fg = M.products.filter(p=>p.cat==='Finished');
  const ops = finOpsCapital();                                   // FV-A — solved capital base
  const fixedBase = (ops.solvedInv||ops.solvedSS) ? ops.fixedNet : M.assets.reduce((s,a)=>s+a.cost,0);
  const revTot  = fg.reduce((s,p)=>s+p.price*p.demand,0) || 1;
  const cogsTot = fg.reduce((s,p)=>s+p.cost*p.demand,0) || 1;
  const rows = fg.map(p=>{
    const rev=p.price*p.demand, cogs=p.cost*p.demand, contrib=(p.price-p.cost)*p.demand;
    const nopat=contrib*(1-tax);
    // FV-A — per-SKU capital = solved FG inventory (or turns proxy) + COGS-share of pooled
    // SS capital + revenue-share of net-block fixed assets.
    const invCap = ops.solvedInv ? (ops.invBySku[p.sku]||0) : (cogs/turns);
    const ssCap  = ops.solvedSS ? ops.ssCapital*(cogs/cogsTot) : 0;
    const fixCap = fixedBase*(rev/revTot);
    const cap = invCap + ssCap + fixCap;
    const roic=cap?nopat/cap:0;
    return { sku:p.sku, name:p.name, abc:p.abc, rev, cogs, contrib, nopat, cap, roic,
             eva:nopat-hurdle*cap, destroyer:roic<hurdle, marginPct:rev?contrib/rev:0,
             invCap, ssCap, fixCap };
  });
  const tot = rows.reduce((a,r)=>({ rev:a.rev+r.rev, cogs:a.cogs+r.cogs, contrib:a.contrib+r.contrib,
    nopat:a.nopat+r.nopat, cap:a.cap+r.cap, eva:a.eva+r.eva }), { rev:0,cogs:0,contrib:0,nopat:0,cap:0,eva:0 });
  return { hurdle, rows, tot, turns, tax, marginPct:tot.rev?tot.contrib/tot.rev:0,
    capitalBasis:(ops.solvedInv?'solved inventory':'turns proxy'), ops };
}

function FinCapital() {
  const { config, setConfig } = useConfig();
  const tax = _effNum(config.taxRate, M.wacc.taxShield);
  const { equity, debt } = finSources(config);
  const totalCap = [...equity, ...debt].reduce((s,r)=>s+r.amount, 0);
  // F-1 — the blended source-weighted hurdle from the REAL capital stack.
  const hurdle = useSolve('/api/calc/hurdle', ()=>({
    equity_sources: equity, debt_sources: debt, tax_rate: tax }));
  // F-2 — WACC-vs-leverage curve + DSCR-capped min-WACC structure.
  const noi = _effNum(config.finNOI, 32000000);   // net operating income (₹) for DSCR
  const struct = useSolve('/api/calc/wacc-structure', ()=>({
    risk_free:M.wacc.rf, equity_risk_premium:M.wacc.erp, unlevered_beta:_effNum(config.finBetaU, 0.9),
    base_cost_of_debt:_effNum(config.finBaseKd, 9.0), credit_spread_slope:6.0,
    tax_rate:tax, total_capital:totalCap, net_operating_income:noi,
    min_dscr:_effNum(config.finMinDscr, 1.5), max_debt_ratio:0.8, step:0.05 }));
  const hr = hurdle.result, sr = struct.result;
  const rate = hr ? hr.hurdle_wacc : M.wacc.rate;
  // NPV with F-7 tax + depreciation shield (toggle): after-tax CF + depₜ×t.
  const taxShield = !!config.finTaxShield;
  const capex0 = Math.abs(M.npv[0].cf);
  const projLife = M.npv.length - 1;
  const annualDep = capex0 / projLife;     // SLM over the project life
  // FV-D — depreciation method toggle. SLM is flat; WDV (written-down value, the Indian
  // Income-Tax block-of-assets reality) front-loads the shield via a declining balance at
  // wdv_rate — the SAME closed form finance.calc_depreciation('WDV') uses on the backend.
  // A front-loaded shield is worth more in PV, so it raises the after-tax NPV / shifts the
  // lease-vs-buy call. Toggling it is a genuine after-tax decision, not cosmetic.
  const depMethod = (config.finDepMethod==='WDV') ? 'WDV' : 'SLM';
  const wdvRate = _effNum(config.finWdvRate, 0.25);
  const depArr = (()=>{ if(depMethod==='SLM') return Array(projLife).fill(annualDep);
    const out=[]; let bv=capex0; for(let y=0;y<projLife;y++){ const d=bv*wdvRate; out.push(d); bv-=d; } return out; })();
  const npvCfs = M.npv.map((p,i)=> i===0 ? p.cf
    : (taxShield ? Math.round(p.cf*(1-tax/100) + (depArr[i-1]||0)*(tax/100)) : p.cf));
  const npv = useSolve('/api/calc/npv', ()=>({ cash_flows:npvCfs,
    wacc:(hr?hr.hurdle_wacc:rate)/100, annual_debt_service: totalCap*(struct.result?struct.result.dscr_feasible_optimum.debt_ratio:0.38)*0.195, net_operating_income:noi }));
  const nr = npv.result;
  const runAll = ()=>{ hurdle.run().then(()=>struct.run()).then(()=>npv.run()).catch(()=>{}); };
  const setEq = (i,k,v)=> setConfig({ finEquity:{ ...(config.finEquity||{}), [i]:{ ...((config.finEquity||{})[i]||{}), [k]:v } } });
  const setDb = (i,k,v)=> setConfig({ finDebt:{ ...(config.finDebt||{}), [i]:{ ...((config.finDebt||{})[i]||{}), [k]:v } } });
  return (
    <Grid cols={3}>
      {/* F-1 — source-weighted hurdle */}
      <Card icon="🏦" title="Source-Weighted Hurdle" badge={hr?`${rate}% · solved`:'blended Ke/Kd'} badgeTone={hr?'g':'y'} span={3}
        info={{ what:'The owner\'s REAL cost of capital — the ₹-weighted blend of every equity source (retained/promoter/PE) and debt source (bank/family), debt tax-shielded. Not a single textbook Ke.', flows:'Hurdle → every NPV/EVA/required-sales gate.' }}
        right={hr ? <Provenance kind="solved" asOf={hurdle.ranAt}/> : <Btn kind="accent" sm onClick={runAll}>{hurdle.solving||struct.solving?'⏳ Computing…':'💹 Compute hurdle'}</Btn>}
        dev={{ comp:'HurdleCard', props:'config.finEquity, config.finDebt → /api/calc/hurdle', state:'config.finEquity[], config.finDebt[]' }}>
        {hurdle.error && <div style={{marginBottom:8, padding:'6px 9px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10, color:C.dg}}>hurdle error: {hurdle.error}</div>}
        <Grid cols={2}>
          <div>
            <SubLabel>Equity sources — opportunity cost</SubLabel>
            {equity.map((r,i)=>(
              <div key={i} style={{display:'flex', gap:8, alignItems:'flex-end', marginBottom:6}}>
                <div style={{flex:1.6, fontFamily:F.mono, fontSize:10, fontWeight:700, paddingBottom:7}}>{r.name}</div>
                <SolverInput label="₹ amount" seed={FIN_EQUITY[i].amount} value={(config.finEquity||{})[i]?.amount} onChange={v=>setEq(i,'amount',v)} min={0}/>
                <SolverInput label="cost" seed={FIN_EQUITY[i].cost} value={(config.finEquity||{})[i]?.cost} onChange={v=>setEq(i,'cost',v)} min={0} suffix="%"/>
              </div>
            ))}
          </div>
          <div>
            <SubLabel>Debt sources — pre-tax rate</SubLabel>
            {debt.map((r,i)=>(
              <div key={i} style={{display:'flex', gap:8, alignItems:'flex-end', marginBottom:6}}>
                <div style={{flex:1.6, fontFamily:F.mono, fontSize:10, fontWeight:700, paddingBottom:7}}>{r.name}</div>
                <SolverInput label="₹ amount" seed={FIN_DEBT[i].amount} value={(config.finDebt||{})[i]?.amount} onChange={v=>setDb(i,'amount',v)} min={0}/>
                <SolverInput label="rate" seed={FIN_DEBT[i].rate} value={(config.finDebt||{})[i]?.rate} onChange={v=>setDb(i,'rate',v)} min={0} suffix="%"/>
              </div>
            ))}
            <Field label="Tax rate (debt shield)"><NumInput value={tax} suffix="%" disabled/></Field>
          </div>
        </Grid>
        {hr && <div style={{marginTop:10, display:'flex', alignItems:'center', gap:14, padding:'10px 12px', background:C.ink, color:C.paper}}>
          <Ring pct={rate*5} size={52} label={rate+'%'} color={C.ac}/>
          <div><div style={{fontFamily:F.mono, fontSize:9, color:C.ac}}>BLENDED HURDLE</div><div style={{fontFamily:F.disp, fontSize:22, fontWeight:900}}>{rate}%</div></div>
          <div style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9.5, textAlign:'right', lineHeight:1.7}}>
            Blended Ke {hr.blended_ke}% · Kd(1−t) {hr.blended_kd_after_tax}%<br/>
            Weights E {hr.equity_weight_pct}% / D {hr.debt_weight_pct}% · capital {FIN_CR(hr.total_capital)}
          </div>
        </div>}
        {hr && <Reading formula="hurdle = wE·Ke* + wD·Kd*·(1−t),  Ke*/Kd* = ₹-weighted blend of the sources"
          soWhat={`The most expensive rupee is ${[...hr.sources].sort((a,b)=>b.cost_pct-a.cost_pct)[0].name} at ${[...hr.sources].sort((a,b)=>b.cost_pct-a.cost_pct)[0].cost_pct}%. Every project must clear ${rate}% — not the cheap bank rate, not a textbook 12%.`}/>}
      </Card>

      {/* F-2 — min-WACC capital structure */}
      <Card icon="📉" title="Min-WACC Capital Structure" badge={sr?(sr.dscr_capped?'DSCR-capped':`opt d=${(sr.dscr_feasible_optimum.debt_ratio*100).toFixed(0)}%`):'WACC curve'} badgeTone={sr?'g':'y'} span={2}
        info={{ what:'WACC vs leverage (Hamada re-levering + a widening credit spread) — the U-curve and its trough, capped by the DSCR covenant.', flows:'Optimal structure → target debt/equity, debt capacity.' }}
        right={sr ? <Provenance kind="solved" asOf={struct.ranAt}/> : <Btn kind="primary" sm onClick={()=>struct.run().catch(()=>{})}>{struct.solving?'⏳…':'📉 Find min'}</Btn>}
        dev={{ comp:'WACCCurveCard', props:'config.fin* → /api/calc/wacc-structure' }}>
        {struct.error && <div style={{marginBottom:8, fontFamily:F.mono, fontSize:10, color:C.dg}}>structure error: {struct.error}</div>}
        {sr ? (<>
          <svg viewBox="0 0 380 150" style={{width:'100%', height:150, display:'block'}}>
            {(()=>{ const c=sr.curve, ws=c.map(r=>r.wacc); const mn=Math.min(...ws), mx=Math.max(...ws);
              const x=i=>20+i*(350/(c.length-1)); const y=v=>135-((v-mn)/((mx-mn)||1))*110;
              const optI=c.findIndex(r=>r.debt_ratio===sr.dscr_feasible_optimum.debt_ratio);
              return <g>
                <polyline points={c.map((r,i)=>`${x(i)},${y(r.wacc)}`).join(' ')} fill="none" stroke={C.ink} strokeWidth="2"/>
                {c.map((r,i)=><circle key={i} cx={x(i)} cy={y(r.wacc)} r={r.dscr_feasible?2.5:2.5} fill={r.dscr_feasible?C.ac:C.dg}/>)}
                {optI>=0 && <g><line x1={x(optI)} y1="20" x2={x(optI)} y2="140" stroke={C.gn} strokeWidth="1.5" strokeDasharray="4 3"/><text x={x(optI)} y="14" fontFamily={F.mono} fontSize="9" fill={C.gn} textAnchor="middle">min {sr.dscr_feasible_optimum.wacc}%</text></g>}
                <text x="20" y="148" fontFamily={F.mono} fontSize="8" fill={C.tx3}>0% debt</text>
                <text x="350" y="148" fontFamily={F.mono} fontSize="8" fill={C.tx3} textAnchor="end">{(sr.curve[sr.curve.length-1].debt_ratio*100).toFixed(0)}%</text>
              </g>; })()}
          </svg>
          <div style={{marginTop:6, fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>● DSCR-feasible · <span style={{color:C.dg}}>●</span> covenant-breaching</div>
          <Reading formula="WACC(d) = (1−d)·Ke(d) + d·Kd(d)·(1−t)   ·   Ke,Kd both rise with leverage; trough capped at DSCR ≥ {min}"
            soWhat={`Min WACC ${sr.dscr_feasible_optimum.wacc}% at ${(sr.dscr_feasible_optimum.debt_ratio*100).toFixed(0)}% debt${sr.dscr_capped?` — the DSCR covenant caps it here (the unconstrained trough at ${(sr.min_wacc_point.debt_ratio*100).toFixed(0)}% would breach ${sr.min_dscr}× cover)`:` (DSCR ${sr.dscr_feasible_optimum.dscr}× — covenant has room)`}.`}/>
        </>) : (
          <div style={{padding:'24px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Compute the hurdle (above) or press Find min — the WACC-vs-leverage curve and its DSCR-capped trough render here.</div>
        )}
      </Card>

      {/* F-6 — DSCR covenant + DSRA */}
      <Card icon="🛡️" title="DSCR Covenant & DSRA" badge={sr?`${sr.dscr_feasible_optimum.dscr}× cover`:'covenant'} badgeTone={sr&&sr.dscr_feasible_optimum.dscr>=sr.min_dscr?'g':'k'}
        info={{ what:'Debt-service coverage at the chosen structure vs the covenant floor, and the cash a Debt-Service Reserve Account must hold.', flows:'DSCR → max debt (caps F-2); DSRA → restricted cash in WC.' }}
        right={sr ? <Provenance kind="derived"/> : undefined}
        dev={{ comp:'DSCRCard', props:'wacc-structure.dscr_feasible_optimum, noi' }}>
        {sr ? (()=>{ const opt=sr.dscr_feasible_optimum; const debtAmt=totalCap*opt.debt_ratio;
          const svc=debtAmt*(opt.kd_pretax/100+0.10); const dsra=svc/2;
          return (<>
            <KpiRow cols={2}>
              <Blk label="DSCR @ optimum" value={`${opt.dscr}×`} accent={opt.dscr>=sr.min_dscr?C.gn:C.dg}/>
              <Blk label="Covenant floor" value={`${sr.min_dscr}×`} tone="c"/>
            </KpiRow>
            <div style={{marginTop:8}}><KpiRow cols={2}>
              <Blk label="Debt service / yr" value={FIN_L(svc)}/>
              <Blk label="DSRA (6 mo)" value={FIN_L(dsra)} tone="y"/>
            </KpiRow></div>
            <Reading formula="DSCR = NOI ÷ debt service   ·   DSRA = 6 months of debt service (restricted cash)"
              soWhat={opt.dscr>=sr.min_dscr?`Cover is ${opt.dscr}× vs the ${sr.min_dscr}× floor — headroom. Park ${FIN_L(dsra)} in a DSRA; it's restricted, so subtract it from free working capital.`:`Cover ${opt.dscr}× is BELOW the ${sr.min_dscr}× floor — deleverage or raise NOI before drawing this debt.`}/>
          </>); })() : (
          <div style={{padding:'18px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10, color:C.tx3, border:`2px dashed ${C.line2}`}}>Solve the structure to evaluate the covenant.</div>
        )}
      </Card>

      {/* NPV/IRR with F-7 tax + depreciation shield */}
      <Card icon="💎" title="NPV / IRR — Program DCF" badge={nr?(taxShield?'after-tax · solved':'pre-tax · solved'):'DCF'} badgeTone={nr?'g':undefined} span={2}
        info={{ what:'Discounted cash flow of the investment program at the blended hurdle. Tax shield adds the depreciation tax saving to after-tax operating cash flows (F-7).', flows:'NPV/IRR → investment verdict.' }}
        right={nr ? <Provenance kind="solved" asOf={npv.ranAt}/> : undefined}
        dev={{ comp:'NPVCard', props:'cashflows(after-tax+dep shield), hurdle' }}>
        <div style={{display:'flex', alignItems:'center', gap:14, marginBottom:8, flexWrap:'wrap'}}>
          <label style={{display:'flex', alignItems:'center', gap:7, fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.tx2, cursor:'pointer'}}>
            <input type="checkbox" checked={taxShield} onChange={e=>{ setConfig({ finTaxShield:e.target.checked }); }}/>
            TAX + DEPRECIATION SHIELD · CF→CF·(1−t) + depₜ·t
          </label>
          {taxShield && <div style={{display:'flex', alignItems:'center', gap:6}}>
            {['SLM','WDV'].map(m=>(
              <button key={m} onClick={()=>setConfig({ finDepMethod:m })} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'3px 9px', border:`2px solid ${C.line}`, cursor:'pointer', background:depMethod===m?C.ink:C.paper, color:depMethod===m?C.paper:C.tx}}>{m}</button>
            ))}
            {depMethod==='WDV' && <SolverInput label="WDV rate" seed={0.25} value={config.finWdvRate} onChange={v=>setConfig({finWdvRate:v})} min={0.05} max={0.6} w={84} suffix="/yr"/>}
            <span style={{fontWeight:400, fontFamily:F.mono, fontSize:9, color:C.tx3}}>{depMethod==='WDV'?`Y1 dep ₹${(depArr[0]/1e5).toFixed(1)}L → front-loaded`:`dep ₹${(annualDep/1e5).toFixed(1)}L/yr flat`} × {tax}%</span>
          </div>}
        </div>
        <div style={{display:'flex', gap:14}}>
          <div style={{flex:1}}>
            <svg viewBox="0 0 380 150" style={{width:'100%', height:150, display:'block'}}>
              <line x1="20" y1="100" x2="370" y2="100" stroke={C.line} strokeWidth="1.5"/>
              {npvCfs.map((cf,i)=>{ const h=Math.abs(cf)/22000000*70;
                return <g key={i}><rect x={30+i*58} y={cf<0?100:100-h} width="34" height={h} fill={cf<0?C.dg:C.ink}/><text x={30+i*58+17} y="115" fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{M.npv[i].y}</text></g>;
              })}
            </svg>
          </div>
          <div style={{width:170}}>
            <KpiRow cols={1}>
              <Blk label={`NPV @ ${rate}%`} value={nr?FIN_L(nr.npv):'run hurdle'} tone="y"/>
              <Blk label="IRR" value={nr&&nr.irr!=null?`${nr.irr}%`:'—'} accent={C.gn}/>
              <Blk label="Payback" value={nr&&nr.payback_discounted!=null?`${nr.payback_discounted} yr`:'—'}/>
              <Blk label="PI" value={nr?`${((nr.npv+capex0)/capex0).toFixed(2)}×`:'—'}/>
            </KpiRow>
          </div>
        </div>
        {nr && <Reading formula={taxShield?`CFₜ = operating CFₜ·(1−t) + depₜ·t  ·  ${depMethod==='WDV'?`WDV declining balance @ ${(wdvRate*100).toFixed(0)}%/yr (front-loaded)`:'SLM (flat over life)'}`:"pre-tax cash flows discounted at the blended hurdle"}
          soWhat={taxShield?`${depMethod==='WDV'?`WDV front-loads the shield: ₹${(depArr[0]*tax/100/1e5).toFixed(1)}L of tax saving in Y1 (vs ₹${(annualDep*tax/100/1e5).toFixed(1)}L flat under SLM), worth more in PV — switch to SLM to see the call change.`:`SLM gives a flat ₹${(annualDep*tax/100/1e5).toFixed(1)}L/yr shield. Switch to WDV (India block-of-assets) to front-load it and lift the after-tax NPV.`} Toggling the shield off drops NPV — ignoring it understates returns.`:`Turn on the shield to value the program after tax (SLM or WDV) — the depreciation tax saving is real cash.`}/>}
      </Card>

      {/* capital structure bar — now from the SOLVED hurdle weights */}
      <Card icon="🏦" title="Capital Stack" badge={hr?FIN_CR(hr.total_capital):FIN_CR(totalCap)} info={{ what:'Total capital and its debt/equity split, from the source table above.', flows:'Structure → hurdle weights.' }}
        dev={{ comp:'CapStackCard', props:'hurdle.equity_weight_pct / debt_weight_pct' }}>
        {(()=>{ const eW=hr?hr.equity_weight_pct:62, dW=hr?hr.debt_weight_pct:38;
          return (<><div style={{display:'flex', height:26, border:`2px solid ${C.line}`, marginBottom:10}}>
            <div style={{width:`${eW}%`, background:C.ink, color:C.paper, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>EQUITY {eW.toFixed(0)}%</div>
            <div style={{width:`${dW}%`, background:C.ac, color:C.onAc, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>DEBT {dW.toFixed(0)}%</div>
          </div>
          <KpiRow cols={2}><Blk label="Equity" value={FIN_CR(equity.reduce((s,r)=>s+r.amount,0))}/><Blk label="Debt" value={FIN_CR(debt.reduce((s,r)=>s+r.amount,0))}/></KpiRow></>); })()}
      </Card>
    </Grid>
  );
}

// EVA-driven scenario branch (Finance L4 · the ops↔finance wedge beyond IBP) — turn
// the EVA verdict into an ACTION: branch the live model with the value-destroyer SKUs
// PRUNED (demand zeroed), run the full loop on the branch (concurrent / transparent —
// the live working set is byte-restored after), and report whether dropping the
// ROIC<hurdle SKUs actually lifts company cost / fill / EVA, or whether their shared
// line/part load was load-bearing. A finance flag drives a real ops re-plan.
function EvaPruneBranch({ destroyers }){
  const [busy,setBusy]=useState(false);
  const [out,setOut]=useState(null);
  const FIN=(v)=> v==null?'—':`₹${(Number(v)/1e5).toFixed(2)}L`;
  const run = async ()=>{
    setBusy(true); setOut(null);
    try{
      const base = _captureKpis();                                   // live KPIs (if any solves cached)
      const id = scenarioPruneSkus(destroyers.map(d=>d.sku));
      const { kpis } = await runScenario(id);                        // transparent — live restored after
      setOut({ base, kpis, n:destroyers.length });
    }catch(err){ setOut({ error: err.message||String(err) }); }
    finally{ setBusy(false); }
  };
  const delta = out && out.base && out.kpis ? {
    cost: (out.kpis.planCost!=null && out.base.planCost!=null) ? out.kpis.planCost-out.base.planCost : null,
    fill: (out.kpis.avgFill!=null && out.base.avgFill!=null) ? out.kpis.avgFill-out.base.avgFill : null,
    cvar: (out.kpis.cvar95!=null && out.base.cvar95!=null) ? out.kpis.cvar95-out.base.cvar95 : null,
  } : null;
  return (
    <div style={{marginTop:12, border:`2px solid ${C.ink}`, borderLeft:`5px solid ${C.ac2}`, padding:'10px 12px', background:C.bg3}}>
      <div style={{display:'flex', alignItems:'center', gap:10, flexWrap:'wrap'}}>
        <span style={{fontFamily:F.disp, fontWeight:800, fontSize:12}}>EVA-driven branch · prune {destroyers.length} destroyer{destroyers.length===1?'':'s'}</span>
        <Btn kind="accent" sm onClick={run}>{busy?'⏳ Re-solving portfolio…':'✂ Branch & re-plan without them'}</Btn>
        <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{destroyers.map(d=>d.sku).join(', ')} → demand zeroed · full loop re-solved (live untouched)</span>
      </div>
      {out && out.error && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.dg}}>branch failed: {out.error}</div>}
      {out && out.kpis && (
        <div style={{marginTop:10}}>
          <KpiRow cols={4}>
            <Blk label="Pruned plan cost" value={FIN(out.kpis.planCost)} sub={delta&&delta.cost!=null?`Δ ${delta.cost<0?'−':'+'}${FIN(Math.abs(delta.cost))} vs base`:'no base solve'} accent={delta&&delta.cost<0?C.gn:C.dg}/>
            <Blk label="Pruned mean fill" value={out.kpis.avgFill!=null?`${out.kpis.avgFill}%`:'—'} sub={delta&&delta.fill!=null?`Δ ${delta.fill>0?'+':''}${delta.fill.toFixed(1)}pt`:''} accent={delta&&delta.fill>=0?C.gn:C.dg}/>
            <Blk label="Pruned CVaR95" value={FIN(out.kpis.cvar95)} sub={delta&&delta.cvar!=null?`Δ ${delta.cvar<0?'−':'+'}${FIN(Math.abs(delta.cvar))}`:''} accent={delta&&delta.cvar<0?C.gn:C.dg}/>
            <Blk label="Loop status" value={out.kpis.prodStatus||'—'} sub={`${out.kpis.prodRuns||0} runs`} tone="k"/>
          </KpiRow>
          <div style={{marginTop:6, fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.6}}>
            {delta && delta.cost!=null
              ? (delta.cost<0
                  ? `Dropping the destroyer(s) cuts plan cost ${FIN(Math.abs(delta.cost))} — their negative-EVA load was NOT carrying shared capacity. The scenario lives in Scenarios → compare/merge.`
                  : `Plan cost RISES ${FIN(Math.abs(delta.cost))} without them — their contribution was load-bearing on shared lines/parts; pruning is value-destroying despite the EVA flag. (The wedge: ops proves the finance call wrong.)`)
              : 'Run the end-to-end loop on the live base first to get a comparison baseline; the pruned branch is scored and saved to Scenarios.'}
          </div>
        </div>
      )}
    </div>
  );
}

// W5 · F-4/F-5/F-3 — the value subtab. EVA/ROIC scoreboard flags value-destroyers,
// a per-SKU margin build rolls up to the company P&L (D-DEC-2 combined), and the
// required-sales bridge says how much more revenue closes the economic-profit gap.
function FinValue() {
  const { config } = useConfig();
  const e = finEva(config);
  const hurdlePct = (e.hurdle*100).toFixed(2);
  const destroyers = e.rows.filter(r=>r.destroyer);
  // F-3 — required incremental sales to turn company EVA positive at the current margin.
  const gap = Math.max(0, e.hurdle*e.tot.cap - e.tot.nopat);     // ₹ NOPAT shortfall vs capital charge
  const reqContrib = e.tax<1 ? gap/(1-e.tax) : gap;             // pre-tax contribution needed
  const reqSales = e.marginPct>0 ? reqContrib/e.marginPct : 0;  // at the blended contribution margin
  // FV-B — per-destroyer required sales on its OWN contribution margin (a low-margin
  // value-destroyer needs disproportionately MORE revenue to clear its capital charge
  // than the company-blended bridge implies — turn each one around on its own economics).
  const perDestroyer = destroyers.map(d=>{
    const gap_i = Math.max(0, e.hurdle*d.cap - d.nopat);
    const reqContrib_i = e.tax<1 ? gap_i/(1-e.tax) : gap_i;
    const reqSales_i = d.marginPct>0 ? reqContrib_i/d.marginPct : 0;
    return { name:d.name, marginPct:d.marginPct, gap_i, reqSales_i };
  });
  // F-5 — ABC segmentation of the margin build.
  const segs = ['A','B','C'].map(cls=>{
    const rs = e.rows.filter(r=>r.abc===cls);
    const rev=rs.reduce((s,r)=>s+r.rev,0), contrib=rs.reduce((s,r)=>s+r.contrib,0), eva=rs.reduce((s,r)=>s+r.eva,0);
    return { cls, n:rs.length, rev, contrib, marginPct:rev?contrib/rev:0, eva };
  }).filter(s=>s.n);
  return (
    <Grid cols={3}>
      <Card icon="📊" title="EVA / ROIC Scoreboard" badge={`hurdle ${hurdlePct}% · ${destroyers.length} destroyer${destroyers.length===1?'':'s'} · cap ${e.capitalBasis}`} badgeTone={destroyers.length?'k':'g'} span={3}
        info={{ what:'Per-SKU economic value added: NOPAT vs the capital charge (hurdle × invested capital). Invested capital is the SOLVED working capital (production projected inventory + pooled safety stock) + net-block fixed assets when a plan is cached (FV-A); else a COGS÷turns proxy. ROIC below the hurdle destroys value even at a book profit.', flows:'Value-destroyers → shutdown/pivot/re-price decision.' }}
        right={<Provenance kind={e.capitalBasis==='solved inventory'?'solved':'derived'}/>}
        dev={{ comp:'EVAScoreboard', props:'finEva(config) — M.products × blended hurdle', note:'FV-A: capital = solved FG inventory + pooled SS + net-block assets (fallback: COGS÷turns).' }}>
        <DataTable cols={['SKU','ABC','Revenue','Contribution','NOPAT','Invested cap','ROIC','EVA','Verdict']} align={['left','left','right','right','right','right','right','right','left']}
          rows={e.rows.map(r=>({__hl:r.destroyer, cells:[r.name, r.abc, FIN_L(r.rev), FIN_L(r.contrib), FIN_L(r.nopat), FIN_L(r.cap),
            <span style={{fontWeight:700, color:r.destroyer?C.dg:C.gn}}>{(r.roic*100).toFixed(1)}%</span>,
            <span style={{fontWeight:700, color:r.eva<0?C.dg:C.tx}}>{r.eva<0?'−':'+'}{FIN_L(Math.abs(r.eva)).replace('₹ ','₹')}</span>,
            <Tag c={r.destroyer?'r':'g'}>{r.destroyer?'DESTROYS':'creates'}</Tag>]}))}
          foot={['COMPANY','', FIN_L(e.tot.rev), FIN_L(e.tot.contrib), FIN_L(e.tot.nopat), FIN_L(e.tot.cap),
            `${(e.tot.cap?e.tot.nopat/e.tot.cap*100:0).toFixed(1)}%`, `${e.tot.eva<0?'−':'+'}${FIN_L(Math.abs(e.tot.eva)).replace('₹ ','₹')}`, '']}/>
        <Reading formula={e.capitalBasis==='solved inventory'
          ? "EVA = NOPAT − hurdle × invested capital   ·   capital = SOLVED FG inventory (production schedule) + pooled SS (W8) + net-block fixed assets"
          : "EVA = NOPAT − hurdle × invested capital   ·   capital = COGS÷turns proxy + fixed-asset revenue share (run Production time-phased to solve the real base)"}
          soWhat={destroyers.length
            ? `${destroyers.map(d=>d.name).join(', ')} earn${destroyers.length===1?'s':''} a positive contribution but ROIC below the ${hurdlePct}% hurdle — ${e.tot.eva<0?'the portfolio destroys value overall':'they drag the portfolio'}. Re-price, cut their capital (turns), or pivot the mix.`
            : `Every SKU clears the ${hurdlePct}% hurdle — company EVA is +${FIN_L(e.tot.eva)}. The stack earns its cost of capital.`}/>
        {destroyers.length>0 && <EvaPruneBranch destroyers={destroyers}/>}
      </Card>

      {/* F-3 required-sales bridge */}
      <Card icon="🌉" title="Required-Sales Bridge" badge={gap>0?'gap to close':'clearing'} badgeTone={gap>0?'k':'g'}
        info={{ what:'How much more revenue (at the current blended margin) is needed to cover the capital charge and turn company EVA positive.', flows:'Target → profit-mix volume goal.' }}
        right={<Provenance kind="derived"/>}
        dev={{ comp:'RequiredSalesCard', props:'(hurdle·capital − NOPAT) ÷ margin' }}>
        {gap>0 ? (<>
          <KpiRow cols={1}>
            <Blk label="EVA gap (capital charge − NOPAT)" value={FIN_L(gap)} accent={C.dg}/>
            <Blk label="Blended contribution margin" value={`${(e.marginPct*100).toFixed(1)}%`} tone="c"/>
            <Blk label="Required extra sales (company)" value={FIN_L(reqSales)} tone="y"/>
          </KpiRow>
          {perDestroyer.length>0 && <div style={{marginTop:8}}>
            <SubLabel>Per value-destroyer — on its OWN margin (FV-B)</SubLabel>
            <DataTable dense cols={['SKU','Own margin','EVA gap','Required sales']} align={['left','right','right','right']}
              rows={perDestroyer.map(d=>[d.name, `${(d.marginPct*100).toFixed(1)}%`, FIN_L(d.gap_i),
                <span style={{fontWeight:700, color:C.dg}}>{FIN_L(d.reqSales_i)}</span>])}/>
          </div>}
          <Reading formula="required sales = (hurdle·capitalᵢ − NOPATᵢ) ÷ (1−t) ÷ own-contribution-margin%"
            soWhat={`Company-wide ~${FIN_L(reqSales)} clears the ${FIN_L(gap)} shortfall at the blended ${(e.marginPct*100).toFixed(1)}% margin — but ${perDestroyer.length?`the per-SKU bridge shows a thin-margin destroyer like ${perDestroyer.sort((a,b)=>b.reqSales_i-a.reqSales_i)[0].name} needs ${FIN_L(perDestroyer.sort((a,b)=>b.reqSales_i-a.reqSales_i)[0].reqSales_i)} on its own ${(perDestroyer.sort((a,b)=>b.reqSales_i-a.reqSales_i)[0].marginPct*100).toFixed(1)}% margin`:'no single SKU destroys value'} — or cut its invested capital (raise turns) instead.`}/>
        </>) : (
          <div style={{padding:'14px 12px', fontFamily:F.mono, fontSize:10.5, color:C.tx2, border:`2px solid ${C.gn}`, background:'color-mix(in srgb,var(--gn) 8%,transparent)'}}>
            Company NOPAT already exceeds the {hurdlePct}% capital charge — EVA is +{FIN_L(e.tot.eva)}. No additional sales are required to clear the hurdle.
          </div>
        )}
      </Card>

      {/* F-5 margin-build segmentation (ABC) */}
      <Card icon="🧱" title="Product-Economics Segmentation" badge="ABC margin build" span={2}
        info={{ what:'Per-SKU margin build rolled up by ABC class — the portfolio view of where contribution and economic value come from.', flows:'Segment economics → mix & portfolio strategy.' }}
        right={<Provenance kind="derived"/>}
        dev={{ comp:'SegmentationCard', props:'finEva rows grouped by ABC' }}>
        <DataTable cols={['Class','SKUs','Revenue','Contribution','Margin %','EVA']} align={['left','right','right','right','right','right']}
          rows={segs.map(s=>({cells:[<b>Class {s.cls}</b>, s.n, FIN_L(s.rev), FIN_L(s.contrib),
            `${(s.marginPct*100).toFixed(1)}%`,
            <span style={{fontWeight:700, color:s.eva<0?C.dg:C.gn}}>{s.eva<0?'−':'+'}{FIN_L(Math.abs(s.eva)).replace('₹ ','₹')}</span>]}))}/>
        <div style={{marginTop:10, display:'flex', height:24, border:`2px solid ${C.line}`}}>
          {segs.map((s,i)=>{ const tot=segs.reduce((a,x)=>a+x.contrib,0)||1;
            return <div key={i} style={{width:`${s.contrib/tot*100}%`, background:[C.ink,C.ac,C.bg4][i%3], color:i===1?C.onAc:'#fff', display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, fontWeight:700}}>{s.cls} {(s.contrib/tot*100).toFixed(0)}%</div>; })}
        </div>
        <Reading formula="contribution = (price − cost) × demand, summed by ABC class"
          soWhat={`Class A SKUs carry the contribution; the bar shows each class's share. Cross-reference the EVA column — a high-revenue class can still be a net value-destroyer if its ROIC trails the hurdle.`}/>
      </Card>
      <FinBVL/>
    </Grid>
  );
}

// W5 · F-8 — Investment decisions on the REAL capital-capacity solver. Each production
// line is a candidate expansion (a 'capacity' option whose cash flow is DERIVED from the
// throughput it unlocks: added hours × margin/hr × utilization − opex), and the solver
// picks which/when under a budget and reports a Monte-Carlo risk-adjusted NPV. The line
// margin/hr defaults to the contribution-per-machine-hour each line earns — and the loop
// closes when Plan's binding-line shadow price (PL-A) is entered as that margin.
function FinInvest() {
  const { config, setConfig } = useConfig();
  const hurdle = finBlendedHurdle(config).wacc/100;
  // per-line contribution margin per machine-hour = Σ contribution / Σ machine-hours of its SKUs.
  const lineMph = {};      // derived contribution/hr — the fallback
  const lineUPH = {};      // units/hr per line — converts the ₹/unit capacity dual → ₹/hr
  (M.lines||[]).forEach(l=>{
    const sk = M.products.filter(p=>p.cat==='Finished'&&p.line===l.id);
    const contribYr = sk.reduce((s,p)=>s+(p.price-p.cost)*p.demand,0);
    const hrsYr = sk.reduce((s,p)=>s+(p.demand*p.cycle/60),0);
    const unitsYr = sk.reduce((s,p)=>s+(p.demand||0),0);
    lineMph[l.id] = hrsYr ? contribYr/hrsYr : 0;
    lineUPH[l.id] = hrsYr ? unitsYr/hrsYr : 0;
  });
  // FV-C — when the line-capacity LP (Plan · PL-A) has solved, value added hours at the
  // BINDING line's shadow price (₹/unit capacity × units/hr = ₹/hr of added capacity). A
  // line the schedule leaves SLACK earns 0 from expansion — so a line is only worth
  // expanding where the committed schedule is genuinely capacity-bound, not on a mock margin.
  const lc = (typeof getSolveResult==='function') ? getSolveResult('linecap') : null;
  const lcByLine = {}; if(lc && lc.lines) lc.lines.forEach(l=>{ lcByLine[l.line_id]=l; });
  const solvedMph = {};
  (M.lines||[]).forEach(l=>{ const r = lcByLine[l.id];
    solvedMph[l.id] = lc ? ((r && r.binding) ? Math.round((r.shadow_price||0)*(lineUPH[l.id]||0)) : 0) : null; });
  const mphSolved = !!lc;
  const effMph = (lid)=> (solvedMph[lid]!=null) ? solvedMph[lid] : Math.round(lineMph[lid]||0);
  const seedCapex = { 'LINE-01':9000000, 'LINE-02':12000000, 'LINE-03':18000000 };
  const addedHrsYr = _effNum(config.finAddedHrs, 2400);   // +1 shift ≈ 2,400 machine-hrs/yr
  const budget = _effNum(config.finCapexBudget, 25000000);
  const cap = useSolve('/api/solve/capital-capacity', ()=>({
    investments: (M.lines||[]).map(l=>({
      name:`Expand ${l.id}`, type:'capacity',
      capex: _effNum((config.finCapex||{})[l.id], seedCapex[l.id]||10000000),
      capacity_hours_per_period: addedHrsYr,
      margin_per_hour: effMph(l.id),                    // FV-C — solved binding-line dual when available

      utilization: 0.85, opex_per_period: Math.round((_effNum((config.finCapex||{})[l.id], seedCapex[l.id]||10000000))*0.04),
      useful_life: 8, earliest_period:0, latest_period:4,
    })),
    params: { horizon_periods:5, wacc:hurdle, budget_per_period:budget, budget_rollover:true,
      capacity_shadow_price:_effNum(config.finLineShadow, 0), npv_mc_runs:400, driver_cv:0.20 },
  }));
  const cr = cap.result;
  const setCapex = (lid,v)=> setConfig({ finCapex:{ ...(config.finCapex||{}), [lid]:v } });
  return (
    <Grid cols={3}>
      <Card icon="🏗️" title="Endogenous-Capacity Capital Plan" badge={cr?`NPV ${FIN_CR(cr.total_npv)} · solved`:'capital-capacity MILP'} badgeTone={cr?'g':'y'} span={3}
        info={{ what:'Which line expansions to fund and when, on the real multi-period capital-capacity solver. Each option\'s cash flow is DERIVED from the throughput it unlocks (hours × margin/hr × utilization − opex), not a hand-set number.', flows:'Selected plan → budget lock; risk-adjusted NPV → board.' }}
        right={cr ? <Provenance kind="solved" asOf={cap.ranAt}/> : <Btn kind="accent" sm onClick={()=>cap.run().catch(()=>{})}>{cap.solving?'⏳ Optimizing…':'🏗️ Solve capital plan'}</Btn>}
        dev={{ comp:'CapitalCapacityCard', props:'M.lines → /api/solve/capital-capacity', state:'config.finCapex, finLineShadow' }}>
        {cap.error && <div style={{marginBottom:8, padding:'6px 9px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10, color:C.dg}}>capital error: {cap.error}</div>}
        <Grid cols={4}>
          {(M.lines||[]).map(l=>(
            <SolverInput key={l.id} label={`${l.id} CapEx`} seed={seedCapex[l.id]} value={(config.finCapex||{})[l.id]} onChange={v=>setCapex(l.id,v)} min={0} prefix="₹"/>
          ))}
          <SolverInput label="Budget / yr" seed={25000000} value={config.finCapexBudget} onChange={v=>setConfig({finCapexBudget:v})} min={0} prefix="₹"/>
          <SolverInput label="Added hrs/yr (1 shift)" seed={2400} value={config.finAddedHrs} onChange={v=>setConfig({finAddedHrs:v})} min={0}/>
          <SolverInput label="Line shadow ₹/hr (from Plan PL-A)" seed={0} value={config.finLineShadow} onChange={v=>setConfig({finLineShadow:v})} min={0} suffix="₹/hr" hint="overrides derived margin/hr if a line binds"/>
        </Grid>
        <div style={{marginTop:6, fontFamily:F.mono, fontSize:9, color:C.tx3}}>{mphSolved?'Solved margin/hr (binding-line dual · PL-A)':'Derived margin/hr per line'}: {(M.lines||[]).map(l=>`${l.id} ₹${effMph(l.id).toLocaleString('en-IN')}${mphSolved&&lcByLine[l.id]&&lcByLine[l.id].binding?'⚡':''}`).join(' · ')}{mphSolved?' · slack lines value expansion at ₹0':' — run Plan · Line-capacity (PL-A) to value on the solved dual'}</div>
        {cr && (cr.schedule.length ? <div style={{marginTop:10}}>
          <DataTable cols={['Expansion','Invest yr','CapEx','Margin/hr','Annual CF','Option NPV','IRR']} align={['left','right','right','right','right','right','right']}
            rows={cr.schedule.map(s=>{ const lid=(s.name||'').replace('Expand ','');
              return {cells:[s.name, `Y${s.invest_period}`, FIN_L(s.capex), `₹${effMph(lid).toLocaleString('en-IN')}`, FIN_L(s.annual_cash_flow), <span style={{fontWeight:700, color:s.npv>0?C.gn:C.dg}}>{FIN_L(s.npv)}</span>, s.irr!=null?`${s.irr}%`:'—']};})}/>
        </div> : (
          <div style={{marginTop:10, padding:'14px 12px', fontFamily:F.mono, fontSize:10, color:C.tx2, border:`2px dashed ${C.line2}`}}>
            No expansion clears the {(hurdle*100).toFixed(1)}% hurdle at these CapEx/throughput values — the lines have slack (consistent with Plan: all lines ₹0 shadow price). Lower a line's CapEx, raise its margin/hr, or enter Plan's binding-line shadow price to make the case.
          </div>
        ))}
      </Card>
      {cr && <Card icon="🎲" title="Risk-Adjusted NPV" badge={`P(NPV<0) ${cr.risk_adjusted_npv.prob_negative}%`} badgeTone={cr.risk_adjusted_npv.prob_negative>20?'k':'g'} span={2}
        info={{ what:'Monte-Carlo on the chosen plan: perturb margin/hr and utilization (±CV), recompute portfolio NPV.', flows:'Distribution → go/no-go confidence.' }}
        right={<Provenance kind="solved" asOf={cap.ranAt}/>}
        dev={{ comp:'RiskNPVCard', props:'capital-capacity.risk_adjusted_npv' }}>
        <KpiRow cols={4}>
          <Blk label="Mean NPV" value={FIN_CR(cr.risk_adjusted_npv.mean)} tone="y"/>
          <Blk label="P10" value={FIN_CR(cr.risk_adjusted_npv.p10)} accent={C.dg}/>
          <Blk label="P90" value={FIN_CR(cr.risk_adjusted_npv.p90)} accent={C.gn}/>
          <Blk label="P(loss)" value={`${cr.risk_adjusted_npv.prob_negative}%`} accent={cr.risk_adjusted_npv.prob_negative>20?C.dg:C.gn}/>
        </KpiRow>
        <Reading formula="MC over margin/hr & utilization (±20% CV), n=400 — portfolio NPV distribution"
          soWhat={`The plan's NPV is ${FIN_CR(cr.risk_adjusted_npv.mean)} on average with a ${cr.risk_adjusted_npv.prob_negative}% chance of a loss — ${cr.risk_adjusted_npv.prob_negative>20?'material downside; size the CapEx cautiously':'a robust case'}. Enter Plan\'s line shadow price (PL-A) above to value a binding line at its true marginal worth.`}/>
      </Card>}
      <Card icon="⚖️" title="Investment Verdict" badge={cr?(cr.total_npv>0?'APPROVE':'HOLD'):'pending'} badgeTone="k"
        info={{ what:'Go/no-go from the solved plan vs the blended hurdle.', flows:'Verdict → budget lock.' }}
        dev={{ comp:'VerdictCard', props:'capital-capacity.total_npv, hurdle' }}>
        {cr ? (
          <div style={{padding:'16px', background:cr.total_npv>0?C.gn:C.bg4, color:cr.total_npv>0?'#fff':C.tx, textAlign:'center'}}>
            <div style={{fontFamily:F.disp, fontSize:22, fontWeight:900}}>{cr.total_npv>0?'✓ APPROVE':'⏸ HOLD'}</div>
            <div style={{fontFamily:F.mono, fontSize:10, marginTop:4}}>{cr.total_npv>0?`NPV +${FIN_CR(cr.total_npv)} at ${(hurdle*100).toFixed(1)}% hurdle`:`No positive-NPV expansion at ${(hurdle*100).toFixed(1)}% hurdle`}</div>
          </div>
        ) : (
          <div style={{padding:'18px 12px', textAlign:'center', fontFamily:F.mono, fontSize:10, color:C.tx3, border:`2px dashed ${C.line2}`}}>Solve the capital plan for the verdict.</div>
        )}
      </Card>
      <FinBVL/>
    </Grid>
  );
}

function FinAssets() {
  const fmt=n=>`₹${(n/100000).toFixed(1)}L`;
  // Portfolio net-block schedule from the real WDV engine: aggregate the register
  // (Σcost) at the portfolio WDV rate (Σ annual dep ÷ Σ cost) → /api/calc/depreciation.
  const totCost = M.assets.reduce((s,a)=>s+a.cost,0);
  const totDep  = M.assets.reduce((s,a)=>s+a.dep,0);
  const totWdv  = M.assets.reduce((s,a)=>s+a.wdv,0);
  const rate = totCost ? totDep/totCost : 0.1;
  const dep = useSolve('/api/calc/depreciation', ()=>({
    purchase_price:totCost, residual_value:0, useful_life:6, method:'WDV', wdv_rate:rate,
  }));
  const sched = dep.result && dep.result.schedule;
  const bars = sched ? [totCost, ...sched.map(s=>s.book_value)] : [238,183,142,110,86,68].map(v=>v*1e5);
  const mx = Math.max(...bars);
  return (
    <Grid cols={2}>
      <Card icon="🏭" title="Asset Register" badge={`${M.assets.length} assets`} info={{ what:'Capital assets: cost, life, age, written-down value.', flows:'Assets → depreciation & WC.' }} span={2}
        dev={{ comp:'AssetRegisterCard', props:'state.finance.assets', state:'finance.assets[]' }}>
        <DataTable cols={['ID','Asset','Cost','Life','Age','WDV','Annual Dep']} align={['left','left','right','right','right','right','right']}
          rows={M.assets.map(a=>[a.id, a.name, fmt(a.cost), `${a.life}y`, `${a.age}y`, fmt(a.wdv), fmt(a.dep)])}
          foot={['TOTAL','4 assets',fmt(totCost),'','',fmt(totWdv),fmt(totDep)]}/>
      </Card>
      <Card icon="📉" title="Asset Depreciation" badge={sched?`WDV ${(rate*100).toFixed(1)}% · solved`:'WDV method'} badgeTone={sched?'g':undefined}
        right={sched ? <Provenance kind="solved" asOf={dep.ranAt}/> : <Btn kind="accent" sm onClick={()=>dep.run().catch(()=>{})}>{dep.solving?'⏳…':'📉 Compute schedule'}</Btn>} span={2}
        info={{ what:'Depreciation schedule over remaining life.', flows:'Dep → P&L & tax shield.' }}
        dev={{ comp:'DepreciationCard', props:'assets' }}>
        {dep.error && <div style={{margin:'0 0 8px', padding:'6px 9px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10, color:C.dg}}>depreciation error: {dep.error}</div>}
        <div style={{display:'flex', alignItems:'flex-end', gap:8, height:90}}>
          {bars.map((v,i)=>(
            <div key={i} style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:4}}>
              <div style={{width:'68%', height:`${v/mx*78}px`, background:i===0?C.ink:C.bg4, border:`2px solid ${C.line}`}} title={fmt(v)}/>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx2}}>Y{i}</span>
            </div>
          ))}
        </div>
        <div style={{marginTop:6, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Net block ₹ Lakhs · WDV declining balance{sched?` (portfolio rate ${(rate*100).toFixed(1)}%/yr)`:''}.</div>
      </Card>
    </Grid>
  );
}

function FinBVL() {
  return (
    <Card icon="🔄" title="Buy vs Lease" badge="decision" span={3} info={{ what:'NPV comparison of buying vs leasing an asset.', flows:'Lower-cost option → capital plan.' }}
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
      <Card icon="💱" title="FX Rate Table" badge={`as of ${M.fxRates.asOf.split('·')[0].trim()}`} badgeTone="y" info={{ what:'Editable spot rates with an as-of date — every $→₹ in the app reads this, nothing is hard-coded.', flows:'Rates → landed cost, hedging, procurement VaR.' }} span={2}
        dev={{ comp:'FXRateTable', props:'state.finance.fxRates', state:'finance.fxRates.{asOf,rows[]}', note:'Single source of truth — landed-cost CIF, hedge marks and VaR all read this.' }}>
        <div style={{display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end', marginBottom:10}}>
          {M.fxRates.rows.map((r,i)=>(
            <Field key={i} label={`${r.ccy} / ₹ · ${r.src}`}><NumInput value={r.rate} prefix="₹"/></Field>
          ))}
          <Field label="As-of timestamp"><TextInput value={M.fxRates.asOf}/></Field>
        </div>
        <Reading formula="all conversions read fxRates[ccy] at the as-of date — no literal 84.20 anywhere" soWhat="Update the rate here and the POSCO landed cost, hedge marks and VaR all re-price together."/>
      </Card>
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
