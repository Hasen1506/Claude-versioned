// ════════════════════════════════════════════════════════════════════════
// sourcing.jsx — Sourcing (stage 07, handoff v2 §3.07). 0 sub-tabs guided
// scroll under the item selector. PER-PART lens: set the selector to "its
// parts" to see that part's MRP, supplier, inbound lane and landed cost.
// Supplier master now lives in Network (03); Sourcing consumes it.
// ════════════════════════════════════════════════════════════════════════
// Procurement MILP payload — the selected FG's demand series (the keystone the
// Demand forecast wrote) exploded through the shared BOM. Period length converts
// the parts' day-leads to periods. Capacity set comfortably above peak demand.
// partsWithSourcing(pd) — the shared BOM mapped to solver parts, but each part's
// `landed_cost` now set from its governed sourcing terms (S-1): quoted cost lifted
// by the duty+inbound-freight %. The procurement/policy solvers PREFER landed_cost
// over raw cost (procurement.py P6), so the MILP plans on the true cost-to-gate.
// Domestic parts (dutyFreightPct=0) get landed_cost == cost — fully backward-compatible.
function partsWithSourcing(pd){
  const base = bomParts(pd);
  const bom = (M.bom||[]);
  return base.map((p,i)=>{
    const b = bom[i] || {};
    const src = getSourcing(b.part, b);
    // supplier carried through so policy.py can group parts into joint-replenishment
    // baskets (SS-B); landed_cost lifted by duty/freight % AND the live FX factor (SS-D).
    return { ...p, landed_cost: effLandedCost(p.cost, src), supplier: b.sup };
  });
}
function procurementPayload(sku, planning, serviceLevel){
  const grain = planning.timeGrain==='week'?'weekly':planning.timeGrain==='day'?'daily':'monthly';
  const pd = planning.timeGrain==='week'?7:planning.timeGrain==='day'?1:30;
  const dem = getItemDemand(sku, 12);
  const p = (M.products||[]).find(x=>x.sku===sku) || {};
  const cap = Math.max(400, Math.ceil(Math.max(...dem) * 1.5));
  // carry_rate is the FG-level annual holding rate — NO longer a hardcoded 0.24; it
  // reads the governed blended WACC + holding spread from Finance (carryRate()), so the
  // MILP's FG-holding term reflects the real cost of capital. Per-part RM hold_pct stays
  // per-BOM. Defaults preserve the prior 24%/yr behaviour at the seed WACC.
  const carry = (typeof carryRate==='function') ? carryRate() : 0.24;
  return { products:[{ name:sku, demand:dem, capacity:cap,
    variable_cost:p.cost||1190, sell_price:p.price||1850, yield_pct:p.yield||0.97, parts:partsWithSourcing(pd) }],
    params:{ periods:12, time_grain:grain, service_level: serviceLevel, carry_rate: carry } };
}
// S-3 autopilot uses the SAME procurement-shaped payload (policy.py reads
// products[].parts[] with landed_cost) — so the (s,S)/(R,Q) policy is derived on
// the identical landed economics the MILP plans on.
function policyPayload(sku, planning, serviceLevel){
  const base = procurementPayload(sku, planning, serviceLevel);
  // SS-B — joint_major_cost = the shared per-PO cost amortised across a supplier's
  // basket (truck booking + admin + inbound inspection). Seed ₹2,500; the per-part
  // ordering_cost (₹120) is the minor cost added per line on a joint order.
  // carry_rate now flows from procurementPayload (governed WACC + spread via carryRate());
  // keep an explicit fallback only if the base ever omits it.
  base.params = { ...base.params, carry_rate: base.params.carry_rate ?? ((typeof carryRate==='function') ? carryRate() : 0.24), joint_major_cost: 2500 };
  return base;
}
// S-4 rolling re-plan: replay the procurement MILP over a sliding horizon. waves =
// number of re-plans, shift = periods advanced per wave, frozen = committed front
// (periods) that this round can't re-plan. Nervousness = Σ|Δ order qty| across
// consecutive re-plans over the still-open, overlapping window.
function rollingPayload(sku, planning, serviceLevel, rp){
  return { n_waves: rp.waves, shift_weeks: rp.shift, frozen_weeks: rp.frozen,
    base: procurementPayload(sku, planning, serviceLevel) };
}
// MEIO (multi-echelon SS placement) payload — builds the RM→WIP→FG assembly graph
// the guaranteed-service model places buffers on (meio.py). All times in DAYS (the
// native lead-time unit), so net-replenishment τ and √τ safety stock are coherent.
//   • RM stages   : one per BOM part, T = supplier lead (days), value = LANDED cost
//                   (S-1 — so an expensive import correctly resists being buffered),
//                   demand μ/σ propagated up the BOM (μ_fg·qty/yield).
//   • WIP stage   : the assembly, T = production cycle (days), value = rolled material.
//   • FG stage    : the demand node, T = finishing, value = full product cost, with a
//                   GOVERNED max committed service time — the knob that lets the model
//                   choose make-to-order (no FG buffer) over a finished buffer.
const MEIO_DPY = 300;   // working days/yr — converts annual demand to a daily rate
function meioPayload(sku, serviceLevel, maxServiceDays){
  const p = (M.products||[]).find(x=>x.sku===sku) || {};
  const bom = M.bom || [];
  const cv = Math.max(Number(p.mape)||1, 1) / 100;        // forecast error % as demand CV proxy
  const muFg = (Number(p.demand)||0) / MEIO_DPY;          // FG units/day
  const sigFg = cv * muFg;
  const yld = Number(p.yield) || 0.97;
  const rolled = bom.reduce((s,b)=> s + b.qty * effLandedCost(b.cost, getSourcing(b.part,b)), 0);
  const stages = [];
  bom.forEach(b=>{
    const src = getSourcing(b.part, b);
    const mu = muFg * b.qty / Math.max(yld, 1e-6);
    stages.push({ id:b.part, name:b.name, kind:'RM', lead_time:b.lt,
      unit_cost: effLandedCost(b.cost, src), hold_pct:b.hold, mu, sigma: cv*mu, suppliers:[] });
  });
  stages.push({ id:'WIP', name:'Assembly WIP', kind:'WIP', lead_time:Math.max(1, Math.round(Number(p.cycle)||3)),
    unit_cost: Math.round(rolled*100)/100, hold_pct:24, mu:muFg, sigma:sigFg, suppliers: bom.map(b=>b.part) });
  stages.push({ id:sku, name:(p.name||sku), kind:'FG', lead_time:1,
    unit_cost: Number(p.cost)||0, hold_pct:24, mu:muFg, sigma:sigFg,
    max_service: Math.max(0, Math.round(Number(maxServiceDays)||0)), suppliers:['WIP'] });
  return { stages, params:{ service_level: serviceLevel, time_unit:'days' } };
}
// W8 · NETWORK / POOLED MEIO payload — risk-pool each shared BOM part across the
// finished SKUs that consume it. meioPayload places ONE buffer per FG TREE; this
// pools a part shared by N SKUs into a single buffer (σ_pool = √(Σσ²+2ρΣσᵢσⱼ) ≤ Σσ).
// Each FG contributes its part-level component demand μ_part = μ_fg·qty/yield with
// σ_part = CV·μ_part (CV = the FG's forecast MAPE — its real demand variability).
// unit_cost = LANDED cost (S-1), lead_time/hold from the BOM row.
// MN-A — the pooled cohort per part is now the REAL subset of SKUs that consume it
// (from M.skuBom), each with its OWN qty_per, not all-6-FG on one shared qty. MN-B —
// each part carries two PLACEMENT echelons (raw upstream: cheap unit, long lead; or
// finished/postponed: dearer unit, short lead), and the solver places the pooled buffer
// at the cheaper one. MN-C — opts.pairwise builds a per-pair ρ matrix from XYZ
// co-movement so correlated SKUs pool poorly and independent ones richly.
const _MEIONET_VALUE_MULT = 2.6;   // finished-stage value of a raw part unit (embedded conversion)
const _MEIONET_ASSY_LT = 3;        // final-assembly lead time (days) the FG echelon must cover
function meioNetworkPayload(serviceLevel, correlation, poolingFixedCost, opts){
  opts = opts || {};
  const bom = M.bom || [];
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const skuBom = M.skuBom || {};
  const rhoBase = Number(correlation)||0;
  const xyzRank = { X:0, Y:1, Z:2 };
  // which finished SKUs consume a given part, with each one's own qty_per (MN-A).
  const consumers = (partId)=>{ const out=[];
    fin.forEach(p=>{ const ln=(skuBom[p.sku]||[]).find(x=>x.part===partId); if(ln) out.push({ p, qty:Number(ln.qty)||0 }); });
    return out; };
  // pairwise ρ matrix from XYZ class distance: same class co-moves at ρ; one apart ρ/2;
  // two apart independent. A documented co-movement heuristic (no fabricated covariance).
  const corrMatrix = (skus)=>{ const n=skus.length, m=[];
    for(let i=0;i<n;i++){ m[i]=[]; for(let j=0;j<n;j++){
      if(i===j){ m[i][j]=1; continue; }
      const d=Math.abs((xyzRank[skus[i].xyz]??1)-(xyzRank[skus[j].xyz]??1));
      m[i][j] = d===0?rhoBase : d===1?rhoBase/2 : 0; } }
    return m; };
  const parts = bom.map(b=>{
    const src = getSourcing(b.part, b);
    const cons = consumers(b.part);
    const landed = effLandedCost(b.cost, src);
    const fgs = cons.map(({p, qty})=>{
      const cv = Math.max(Number(p.mape)||1, 1) / 100;
      const muFg = (Number(p.demand)||0) / MEIO_DPY;          // FG units/day
      return { name:p.sku, mu:muFg, sigma:cv*muFg, qty_per:qty, yield:Number(p.yield)||0.97 };
    });
    const part = { id:b.part, name:b.name, unit_cost:landed, hold_pct:b.hold, lead_time:b.lt, fgs,
      echelons:[
        { node:'raw (upstream)',       lead_time:b.lt,             unit_cost:landed,                                    hold_pct:b.hold },
        { node:'finished (postponed)', lead_time:_MEIONET_ASSY_LT, unit_cost:Math.round(landed*_MEIONET_VALUE_MULT*100)/100, hold_pct:24 },
      ] };
    if(opts.pairwise) part.corr_matrix = corrMatrix(cons.map(c=>c.p));
    return part;
  });
  return { parts, params:{ service_level: serviceLevel,
    correlation: rhoBase, pooling_fixed_cost: Number(poolingFixedCost)||0,
    time_unit:'days' } };
}
// S-7 · COSTLY-ITEM NEWSVENDOR (h vs p) + CVaR payload — for ONE chosen part, the
// single-period stocking economics: overage h (cost of a leftover unit) vs underage p
// (cost of a stockout unit). The critical ratio p/(p+h) sets the expected-value order-up-to;
// cvar.py also returns the CVaR-β-robust order-up-to (covers the demand tail, not just the
// mean) and the robustness premium between them. A costly part where holding dominates
// (low critical ratio) is the make-to-order regime. Lead-time demand μ/σ from the same
// BOM explosion the MEIO/MILP use (μ_part = μ_fg·qty/yield, over the part's lead-time days).
function cvarPayload(sku, partId, overage, underage, beta){
  const p = (M.products||[]).find(x=>x.sku===sku) || {};
  const bom = M.bom || [];
  const b = bom.find(x=>x.part===partId) || bom[0] || {};
  const cv = Math.max(Number(p.mape)||1, 1) / 100;
  const yld = Number(p.yield) || 0.97;
  const muDay = (Number(p.demand)||0) / MEIO_DPY * (Number(b.qty)||0) / Math.max(yld, 1e-6);
  const lt = Math.max(1, Number(b.lt)||1);
  const mean = muDay * lt;                         // lead-time demand (the newsvendor horizon)
  const std = Math.max(cv * mean, 1e-6);
  return { mean, std, holding_cost: Number(overage)||0, shortage_cost: Number(underage)||0,
    beta: Number(beta)||0.95, n_scenarios:300 };
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
        <ScopeBanner kind="sourcing" name={`Parts of ${(item&&item.name)||sku}`} code={sku}
          sub="edit landed-cost terms, freight lots & policy for this product's parts"
          right={onNav && <button onClick={()=>onNav('products')} style={{cursor:'pointer', border:`1.5px solid ${C.ac}`, background:'transparent', color:C.ac, fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'3px 9px'}}>↗ Part costs & BOM in Products</button>}/>
        <SolverExplain id="procurement"/>
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
        <StageSection step="0b" title="External-Signal Drivers" sub="commodity / port-congestion / FX indices — planning signals (not IoT telemetry); hidden by default to keep the default view focused">
          <Advanced label="Show external-signal drivers · commodity / port / FX" count={3}>
            <SrcExternalSignals planning={planning} onRerun={runProc} bare/>
          </Advanced>
        </StageSection>
        <SrcMRP item={item} view={view} onNav={onNav} proc={proc}/>
        <SrcIncoterms/>
        <SrcSourcingTerms/>
        <SrcLanded onNav={onNav}/>
        <SrcFreight proc={proc}/>
        <SrcPolicy sku={sku} planning={planning} sl={sl}/>
        <SrcRolling sku={sku} planning={planning} sl={sl}/>
        <SrcMEIO sku={sku} sl={sl}/>
        <SrcMEIONet sl={sl}/>
        <SrcNewsvendor sku={sku}/>
        <SrcPostpone proc={proc}/>
        <SrcResults proc={proc}/>
        <SrcExceptions proc={proc}/>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════
// D6 · EXTERNAL-SIGNAL DRIVERS — planning-cadence external indices (the in-fit
// replacement for "real-time IoT": we ingest external SIGNALS, not MES telemetry).
// A commodity-price index re-prices BOM material, a port-congestion bump lengthens
// inbound lead, and the FX table (SS-D) re-prices imported parts. All three are
// REAL solver drivers: bomParts (store.jsx) applies the commodity factor + port
// lead, and because they live on config, editing one re-flags procurement / policy /
// rolling / MEIO stale. Neutral seed (0% / 0d) ⇒ nothing moves until a planner sets
// an index. The card proves the propagation on real BOM parts — no fabricated number.
// ════════════════════════════════════════════════════════════════════════
function SrcExternalSignals({ planning, onRerun, bare }){
  const { config, setConfig } = useConfig();
  const sig = config.signals || {};
  const setSig = (p)=> setConfig({ signals: { ...sig, ...p } });
  const pd = planning.timeGrain==='week'?7:planning.timeGrain==='day'?1:30;
  const cf = commodityFactor(), portP = portDelayPeriods(pd);
  const idxPct = Number(sig.commodityIndexPct)||0, portDays = Number(sig.portDelayDays)||0;
  const active = Math.abs(idxPct)>0.001 || portDays>0;
  const bom = (M.bom||[]).slice(0,4);
  const fxRates = config.fxRates || {};
  // solves that consume bomParts (so the commodity/port signals genuinely drive them)
  const driven = ['procurement','policy','rolling','meio','meionet'];
  // bare = rendered inside an <Advanced> disclosure (no duplicate StageSection header)
  const Wrap = bare
    ? ({ children })=> <div>{children}</div>
    : ({ children })=> <StageSection step="0b" title="External-Signal Drivers" sub="commodity / port-congestion / FX indices that drive the procurement & policy solvers — planning signals, not IoT telemetry">{children}</StageSection>;
  return (
    <Wrap>
      <Card icon="📡" title="External signals → solver inputs" badge={active?'driving':'neutral'} badgeTone={active?'g':'k'} span={2}
        right={<Provenance kind="external" note="planning-cadence indices"/>}
        info={{ what:'External market signals the plan should react to — a steel/alloy price index, port-congestion days, and the FX table. Each one feeds a real solver input (BOM material cost, inbound lead time, imported-part landed cost), so moving an index re-prices the plan and re-flags the affected solves stale.', flows:'Signal → bomParts / fxFactor → procurement·policy·rolling·MEIO MILPs.' }}
        dev={{ comp:'SrcExternalSignals (D6)', props:'config.signals · commodityFactor · portDelayPeriods', state:'config.signals (seed 0%/0d)' }}>
        <Grid cols={3}>
          <Field label="Commodity price index" hint="±% vs base on all BOM material cost">
            <NumInput value={idxPct} suffix="%" onChange={v=>setSig({ commodityIndexPct: v===''?0:v })}/>
          </Field>
          <Field label="Port congestion" hint="extra inbound transit (days) → lead time">
            <NumInput value={portDays} suffix="d" onChange={v=>setSig({ portDelayDays: v===''?0:v })}/>
          </Field>
          <Field label="FX table (USD→₹)" hint="edited in Finance/Setup · drives imported parts">
            <NumInput value={fxRates.USD!=null?fxRates.USD:84.2} disabled/>
          </Field>
        </Grid>

        <div style={{marginTop:10}}><SubLabel>Propagation onto real BOM parts</SubLabel></div>
        <DataTable dense cols={['Part','Base cost','Index cost','Δ','Base lead','+Port']} align={['left','right','right','right','right','right']}
          rows={bom.map(b=>{ const ic=Math.round(b.cost*cf*100)/100, dlt=ic-b.cost;
            const baseLeadP=Math.max(1,Math.round(b.lt/pd)), newLeadP=baseLeadP+portP;
            return [
              <span style={{fontFamily:F.mono, fontSize:9.5}}>{b.part}</span>,
              `₹${b.cost}`,
              <span style={{color: Math.abs(dlt)>0.001?(dlt>0?C.dg:C.gn):C.tx3, fontWeight:700}}>₹{ic}</span>,
              <span style={{color: Math.abs(dlt)>0.001?(dlt>0?C.dg:C.gn):C.tx3, fontFamily:F.mono, fontSize:9.5}}>{Math.abs(dlt)>0.001?(dlt>0?'+':'−')+'₹'+Math.abs(dlt).toFixed(1):'—'}</span>,
              <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>{baseLeadP}p</span>,
              <span style={{fontWeight:700, color: newLeadP>baseLeadP?C.dg:C.tx3}}>{newLeadP}p</span>];
          })}/>

        <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3, lineHeight:1.5}}>
          Note: one shared index applies to all BOM material (the mock BOM carries no material class — a documented limitation). Port days round to whole planning periods ({pd}d), so a sub-period delay honestly doesn't shift a {planning.timeGrain==='week'?'weekly':planning.timeGrain==='day'?'daily':'monthly'} bucket. FX is one source of truth — edit it where imported parts are quoted.
        </div>

        {active && onRerun && <div style={{marginTop:8}}>
          <Btn kind="primary" sm onClick={onRerun}>▶ Re-solve procurement on these signals</Btn>
          <span style={{marginLeft:10, fontFamily:F.mono, fontSize:9, color:C.a4}}>drives: {driven.join(' · ')} (now stale)</span>
        </div>}

        <Reading tone={active?C.a4:C.tx3}
          formula={`material ×${cf.toFixed(3)} (index ${idxPct>=0?'+':''}${idxPct}%) · inbound +${portP} period${portP===1?'':'s'} (${portDays}d port)`}
          soWhat={active
            ? `These external signals are now driving the plan: BOM material is re-priced ×${cf.toFixed(3)} and inbound lead carries +${portP} period(s). The procurement, policy, rolling and MEIO solves are flagged stale — re-solve to see the buy plan, safety stock and pooling shift. This is how a commodity spike or a port backlog re-plans supply, automatically.`
            : 'Both signals are at their neutral seed, so the plan is byte-identical to the base case. Set a commodity index or port delay to drive a re-plan — the impact propagates to every solver that consumes the BOM.'}/>
      </Card>
    </Wrap>
  );
}

// ════════════════════════════════════════════════════════════════════════
// S-1 + S-2 · GOVERNED SOURCING TERMS — the input surface that turns each part's
// quoted cost into a LANDED cost (duty + inbound freight) the procurement MILP
// plans on, and sets the truck lot that drives the stepwise freight curve. Seed
// provenance until a cell is overridden (D-DEC-1 seeded-with-override). Editing
// any field re-flags procurement/policy/rolling stale via the 'sourcing' source.
// ════════════════════════════════════════════════════════════════════════
function SrcSourcingTerms(){
  const bom = M.bom || [];
  return (
    <StageSection step="3" title="Sourcing Terms" sub="per-part import status, landed-cost uplift and inbound-truck lot — the governed inputs the supply MILP plans on">
      <Card icon="🧾" title="Landed-cost & freight terms" badge="governed" badgeTone="y"
        info={{ what:'Imported parts carry a duty+inbound-freight uplift that turns quoted cost into landed cost; the MILP plans on landed cost. The truck lot sets the stepwise freight curve below.', flows:'→ procurement/policy parts[].landed_cost + freight steps.' }}
        dev={{ comp:'SrcSourcingTerms', props:'sourcing[part]', state:'sourcing[part] (seed sourcingDefault)' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
            <thead><tr style={{background:C.ink}}>
              {['Part','Import?','Quoted ₹','Duty+freight %','Landed ₹','Units/truck','₹/truck','src'].map((h,i)=>(
                <th key={i} style={{color:C.paper, textAlign:i<2?'left':'right', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {bom.map((b,i)=><SrcTermRow key={b.part} b={b}/>)}
            </tbody>
          </table>
        </div>
        <Reading formula="landed = quoted × (1 + duty+freight%)   ·   the MILP prefers landed over quoted cost, so a part that lands +12% reshapes which supplier/lot wins"
          soWhat="Flip a part to imported (or edit its %) and the procurement plan re-solves on the higher landed cost — long-lead imports get ordered in fewer, larger lots to amortise freight. Domestic parts (0%) are unchanged."/>
      </Card>
    </StageSection>
  );
}
function SrcTermRow({ b }){
  const { src, setSrc } = useSourcing(b.part, b);
  const landed = effLandedCost(b.cost, src);
  const up = (landed - b.cost);
  const cell = { padding:'4px 7px', borderTop:`1px solid ${C.line2}` };
  const num  = { ...cell, textAlign:'right' };
  const inp  = (val,key,step,w)=>(
    <input type="number" value={val} step={step||1} onChange={e=>setSrc({ [key]: e.target.value===''?'':Number(e.target.value) })}
      style={{ width:w||56, fontFamily:F.mono, fontSize:10.5, textAlign:'right', padding:'2px 4px', border:`1px solid ${C.line}`, background:C.paper, color:C.tx }}/>
  );
  return (
    <tr style={{background: src.imported?C.bg3:C.paper}}>
      <td style={{...cell}}><span style={{fontWeight:700}}>{b.part}</span><div style={{fontSize:9, color:C.tx3, fontFamily:F.disp}}>{b.name}</div></td>
      <td style={{...cell}}>
        <button onClick={()=>setSrc({ imported: !src.imported, dutyFreightPct: !src.imported ? (Number(src.dutyFreightPct)||12) : 0 })}
          style={{ cursor:'pointer', border:`1.5px solid ${C.line}`, padding:'2px 7px', fontFamily:F.mono, fontSize:9, fontWeight:700,
            background: src.imported?C.ac:'transparent', color: src.imported?C.onAc:C.tx2 }}>
          {src.imported?'IMPORT':'DOMESTIC'}
        </button>
      </td>
      <td style={{...num, color:C.tx2}}>₹{b.cost.toLocaleString('en-IN')}</td>
      <td style={{...num}}>{inp(src.dutyFreightPct, 'dutyFreightPct', 0.5, 52)}</td>
      <td style={{...num, fontWeight:700, color: up>0?C.dg:C.tx}}>₹{landed.toLocaleString('en-IN')}{up>0?<span style={{fontSize:8.5, color:C.dg}}> +{((up/b.cost)*100).toFixed(1)}%</span>:''}
        {src.imported && Math.abs(fxFactor(src)-1)>0.001 && <div style={{fontSize:8, color:C.a4, fontFamily:F.mono}}>FX ×{fxFactor(src).toFixed(3)}</div>}</td>
      <td style={{...num}}>{inp(src.unitsPerTruck, 'unitsPerTruck', 100, 64)}</td>
      <td style={{...num}}>{inp(src.costPerTruck, 'costPerTruck', 1000, 70)}</td>
      <td style={{...num}}><Tag c={src._prov==='user'?'g':'w'}>{src._prov==='user'?'user':'seed'}</Tag></td>
    </tr>
  );
}

// ════════════════════════════════════════════════════════════════════════
// S-2 · STEPWISE INBOUND FREIGHT — freight = ⌈qty / units-per-truck⌉ × ₹/truck.
// Driven by the SELECTED part's REAL MILP order quantity (proc.result.materials),
// so the card shows the actual trucks the plan books and the marginal-truck cliff:
// "this order fills N trucks at U%; one more unit tips you into truck N+1." This is
// the honest face of the duty+freight % the MILP averages into landed cost — it
// reveals the lumpy lot economics the average hides. (D-DEC-3 option b.)
// ════════════════════════════════════════════════════════════════════════
function SrcFreight({ proc }){
  const bom = M.bom || [];
  const [pi, setPi] = useState(0);
  const b = bom[pi] || {};
  const { src } = useSourcing(b.part, b);
  // the real ordered qty for this part from the MILP (sum of its purchase orders)
  const mat = proc && proc.result && (proc.result.materials||[])[pi];
  const ordered = mat ? (mat.total_ordered || 0) : 0;
  const steps = freightSteps(ordered, src);
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  // build a small step ladder around the current qty so the cliff is visible
  const ladderQ = ordered>0 ? [steps.cap*Math.max(0,steps.trucks-1)+1, ordered, steps.nextStepAt] : [];
  // SS-A — supplier-level truck CONSOLIDATION. Real inbound from ONE supplier shares
  // trucks: each part fills a fraction (ordered ÷ units-per-truck) of a truck, so the
  // supplier's trucks = ⌈Σ fractions⌉ vs the Σ⌈fraction⌉ booked part-by-part. The diff
  // is the consolidation dividend (fewer trucks for the same freight ₹/truck). Uses the
  // SAME MILP order qty per part — no extra solve, no faking.
  const mats = (proc && proc.result && proc.result.materials) || [];
  const consol = (()=>{
    if(!mats.length || !b.sup) return null;
    const grp = bom.map((bb,i)=>({ bb, i })).filter(x=> x.bb.sup === b.sup);
    if(grp.length < 2) return null;
    let fracSum=0, indepTrucks=0, indepCost=0, anyOrder=false; const rows=[];
    grp.forEach(({bb,i})=>{ const s=getSourcing(bb.part,bb); const ord=(mats[i]&&mats[i].total_ordered)||0;
      const fs=freightSteps(ord, s); if(ord>0) anyOrder=true;
      fracSum += ord / Math.max(1, s.unitsPerTruck); indepTrucks += fs.trucks; indepCost += fs.cost;
      rows.push({ part:bb.part, ord, trucks:fs.trucks }); });
    const perTruck = Number(src.costPerTruck)||0;
    const consTrucks = Math.max(anyOrder?1:0, Math.ceil(fracSum));
    const consCost = consTrucks * perTruck;
    return { rows, indepTrucks, indepCost, consTrucks, consCost, saving: indepCost-consCost, anyOrder, sup:b.sup };
  })();
  return (
    <StageSection step="5" title="Stepwise Inbound Freight" sub="freight is booked by the truck/container, not the unit — see the marginal-truck cliff on the selected part's planned order">
      <Card icon="🚚" title="Truck-step freight" badge={mat?'on MILP order':'run procurement first'} badgeTone={mat?'g':'k'}
        right={mat ? <Provenance kind="derived" asOf={proc.ranAt}/> : undefined}
        info={{ what:'Freight per truckload step-function on the planned order quantity. Folded (as an average) into the part landed cost the MILP optimises.', flows:'Stepwise truck cost ← MILP order qty × governed truck lot.' }}
        dev={{ comp:'SrcFreight', props:'sourcing[part], proc.materials[i].total_ordered' }}>
        <div style={{display:'flex', gap:0, overflowX:'auto', border:`2px solid ${C.line}`, marginBottom:12}}>
          {bom.map((bb,i)=>(
            <button key={bb.part} onClick={()=>setPi(i)} style={{flexShrink:0, padding:'6px 10px', border:'none', borderRight:`1px solid ${C.line2}`, cursor:'pointer',
              background: pi===i?C.ac:'transparent', color:C.tx, minWidth:118}}>
              <div style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700}}>{bb.part}</div>
              <div style={{fontFamily:F.mono, fontSize:9, color: pi===i?C.onAc:C.tx3}}>{getSourcing(bb.part,bb).imported?'import':'domestic'}</div>
            </button>
          ))}
        </div>
        {!mat ? (
          <div style={{padding:'12px', border:`2px dashed ${C.line}`, fontFamily:F.mono, fontSize:11, color:C.tx3}}>
            Run procurement (⚡ above) to size the order — then this shows the exact trucks it books and the next-truck cliff.
          </div>
        ) : ordered<=0 ? (
          <div style={{padding:'12px', border:`2px solid ${C.gn}`, background:C.bg3, fontFamily:F.mono, fontSize:11, color:C.gn}}>
            ✓ The MILP plans no inbound order for {b.name} in this horizon (covered from on-hand) — no inbound freight.
          </div>
        ) : (
          <div>
            <div style={{display:'flex', gap:8, marginBottom:12}}>
              <Blk label="Planned order" value={fmt(ordered)} sub={`${b.part} units`} tone="k"/>
              <Blk label="Trucks booked" value={`${steps.trucks}`} sub={`${fmt(steps.cap)} / truck`} tone="y"/>
              <Blk label="Freight" value={`₹${fmt(steps.cost)}`} sub={`₹${fmt(steps.costPerTruck)}/truck`} accent={C.dg}/>
              <Blk label="Last-truck fill" value={`${steps.fillPct.toFixed(0)}%`} sub={steps.fillPct<70?'under-filled':'well-filled'} accent={steps.fillPct<70?C.dg:C.gn}/>
            </div>
            <div style={{border:`2px solid ${C.line}`}}>
              <div style={{display:'flex', background:C.ink, color:C.paper, fontFamily:F.mono, fontSize:9, fontWeight:700, textTransform:'uppercase'}}>
                {['order qty','trucks','freight','₹/unit',''].map((h,i)=><div key={i} style={{flex: i===4?2:1, padding:'5px 9px', textAlign:i&&i<4?'right':'left'}}>{h}</div>)}
              </div>
              {ladderQ.map((q,i)=>{ const s=freightSteps(q,src); const here = q===ordered;
                return (
                  <div key={i} style={{display:'flex', borderTop:`1px solid ${C.line2}`, background: here?C.bg3:C.paper, fontFamily:F.mono, fontSize:10.5, fontWeight: here?700:400}}>
                    <div style={{flex:1, padding:'5px 9px'}}>{fmt(q)}{here?' ◀ plan':''}</div>
                    <div style={{flex:1, padding:'5px 9px', textAlign:'right'}}>{s.trucks}</div>
                    <div style={{flex:1, padding:'5px 9px', textAlign:'right'}}>₹{fmt(s.cost)}</div>
                    <div style={{flex:1, padding:'5px 9px', textAlign:'right'}}>₹{s.perUnit.toFixed(1)}</div>
                    <div style={{flex:2, padding:'5px 9px', color:C.tx3, fontSize:9}}>{q===steps.nextStepAt?`+1 unit over ${fmt(steps.cap*steps.trucks)} ⇒ truck ${steps.trucks+1} (₹${fmt(steps.marginalTruck)})`:''}</div>
                  </div>
                );
              })}
            </div>
            <Reading formula="freight = ⌈qty / units-per-truck⌉ × ₹/truck   ·   the cost is flat per truck, so per-unit freight is cheapest at a full truck and jumps at every boundary"
              soWhat={`This order books ${steps.trucks} truck${steps.trucks===1?'':'s'} at ${steps.fillPct.toFixed(0)}% fill on the last one. ${steps.fillPct<70?`Rounding the lot up toward ${fmt(steps.cap*steps.trucks)} fills the booked truck at no extra freight; going one unit over ⇒ a whole extra ₹${fmt(steps.marginalTruck)} truck.`:'The last truck is well-filled — freight per unit is near its floor.'}`}/>
            {consol && consol.anyOrder && (
              <div style={{marginTop:14, border:`2px solid ${consol.saving>0?C.gn:C.line}`, borderLeft:`5px solid ${consol.saving>0?C.gn:C.line2}`, padding:'9px 11px', background:C.bg3}}>
                <div style={{fontFamily:F.disp, fontWeight:800, fontSize:12, marginBottom:6}}>SS-A · Supplier consolidation — {consol.sup} <Tag c={consol.saving>0?'g':'k'}>{consol.rows.length} parts share trucks</Tag></div>
                <div style={{display:'flex', gap:8, marginBottom:8, flexWrap:'wrap'}}>
                  <Blk label="Part-by-part trucks" value={`${consol.indepTrucks}`} sub={`₹${fmt(consol.indepCost)}`} tone="k"/>
                  <Blk label="Consolidated trucks" value={`${consol.consTrucks}`} sub={`₹${fmt(consol.consCost)}`} tone="y"/>
                  <Blk label="Trucks saved" value={`${Math.max(0,consol.indepTrucks-consol.consTrucks)}`} accent={C.gn}/>
                  <Blk label="Freight saved" value={`₹${fmt(Math.max(0,consol.saving))}`} accent={consol.saving>0?C.gn:C.tx3}/>
                </div>
                <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.6}}>
                  {consol.rows.filter(r=>r.ord>0).map(r=>`${r.part} (${fmt(r.ord)}u, ${r.trucks}t)`).join(' + ')} → ⌈Σ truck-fractions⌉ = {consol.consTrucks} shared truck{consol.consTrucks===1?'':'s'}.
                  {consol.saving>0?` Booking ${consol.sup}'s parts together cuts ${consol.indepTrucks-consol.consTrucks} truck(s) of dead freight.`:' Already truck-efficient — no consolidation gain at these volumes.'}
                </div>
              </div>
            )}
          </div>
        )}
      </Card>
    </StageSection>
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
    <StageSection step="4" title="Landed Cost" sub="domestic-only — no import cost build-up needed">
      <GateNote onNav={onNav}>Your profile has <b>no imports</b>, so landed cost, FX and incoterms don’t apply — all sourcing is domestic at quoted price.</GateNote>
    </StageSection>
  );
  const rows = res ? landedRows(res, i) : M.landedCost.rows;
  // derived footer blocks (real when solved)
  const unit    = res ? res.net_landed / i.qty : 1877;
  const vsDom   = ((unit - i.domesticUnit) / i.domesticUnit) * 100;
  const itc     = res ? res.itc_recovery : 495000;
  return (
    <StageSection step="4" title="Landed Cost" sub="full FOB → plant-gate build-up for an imported part">
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
    <StageSection step="11" title="Release & Shortages" sub="time-phased PO releases and projected stockouts">
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
// ════════════════════════════════════════════════════════════════════════
// S-3 · INVENTORY POLICY AUTOPILOT — derives a continuous-review (s,S) or
// periodic-review (R,Q) reorder policy per part from the SAME landed economics
// the MILP plans on (policy.py). GATE (ledger H2): the EOQ autopilot is shown ONLY
// for STEADY movers (recommended '(R,Q) periodic'); lumpy / intermittent parts
// (recommended '(s,S) continuous') are NOT given an EOQ beside the MILP plan — they
// stay on the time-phased PO schedule, and we say so. No EOQ for one-offs.
// ════════════════════════════════════════════════════════════════════════
// Carry-rate control — the ONE editable knob for inventory holding economics, placed in
// its natural home (the reorder-policy card, where EOQ's h term lives). Shows the full
// rate decomposed: blended WACC (from Finance, read-only here) + holding spread (editable).
// Editing the spread marks procurement/policy/rolling/montecarlo stale via setConfig.
function CarryRateControl(){
  const { config, setConfig } = useConfig();
  const cp = (typeof carryRateParts==='function') ? carryRateParts(config) : { wacc:11.24, spread:12.8, total:24.0 };
  return (
    <div style={{marginBottom:10, border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.ac}`, background:C.bg3, padding:'8px 11px',
      display:'flex', alignItems:'center', gap:14, flexWrap:'wrap'}}>
      <div style={{fontFamily:F.disp, fontWeight:800, fontSize:11.5}}>Inventory carry rate <Tag c="b">{cp.total}% / yr</Tag></div>
      <div style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>
        = WACC <b style={{color:C.tx}}>{cp.wacc}%</b> <span style={{color:C.tx3}}>(from Finance · blended hurdle)</span> + holding spread
      </div>
      <Field label="Holding spread (storage·insurance·obsolescence)" hint="cost above the WACC of keeping a unit a year">
        <NumInput value={config.invHoldingSpread==null?12.8:config.invHoldingSpread} suffix="%/yr" w={92}
          onChange={v=>setConfig({ invHoldingSpread: v===''?12.8:Number(v) })}/>
      </Field>
    </div>
  );
}
function SrcPolicy({ sku, planning, sl }){
  const pol = useSolve('/api/solve/policy', ()=>policyPayload(sku, planning, sl));
  const { stale } = useStale('policy');
  const run = ()=> pol.run().then(d=>{ markSolved('policy'); return d; }).catch(()=>{});
  const res = pol.result;
  const steady = res ? (res.policies||[]).filter(p=>/periodic/i.test(p.recommended_policy)) : [];
  const lumpy  = res ? (res.policies||[]).filter(p=>!/periodic/i.test(p.recommended_policy)) : [];
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  return (
    <StageSection step="6" title="Inventory Policy (autopilot)" sub="for steady movers — a standing (s,S)/(R,Q) reorder rule the planner runs between MILP re-solves; lumpy parts stay MILP-only">
      <Card icon="🔁" title="Reorder-policy autopilot" badge={res?`${steady.length} steady · solved`:'derive (s,S)/(R,Q)'} badgeTone={res?'g':undefined}
        right={res ? <Provenance kind="solved" asOf={pol.ranAt}/> : <Btn kind="accent" sm onClick={run}>{pol.solving?'⏳ Deriving…':'🔁 Derive policies'}</Btn>}
        info={{ what:'EOQ + safety stock → reorder point s and order-up-to S, on landed cost. Only steady parts get the autopilot; lumpy parts are planned by the MILP.', flows:'policy.py ← same parts[] (landed) as procurement.' }}
        dev={{ comp:'SrcPolicy', props:'solve.policy.policies', state:'service_level, carry_rate' }}>
        {stale && res && <div style={{marginBottom:10}}><StaleMark since="(sourcing or demand changed)" onNav={run} go="re-derive"/></div>}
        {pol.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>policy error: {pol.error}</div>}
        <CarryRateControl/>
        {!res ? (
          <div style={{padding:'12px', border:`2px dashed ${C.line}`, fontFamily:F.mono, fontSize:11, color:C.tx3}}>
            Derive standing reorder policies (EOQ, reorder point, order-up-to) for the steady parts — the rule the planner executes day-to-day between full MILP re-plans.
          </div>
        ) : (
          <div>
            <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
              <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
                <thead><tr style={{background:C.ink}}>
                  {['Part','CV','Policy','EOQ','Reorder s','Order-up-to S','Safety','Orders/yr'].map((h,i)=>(
                    <th key={i} style={{color:C.paper, textAlign:i?'right':'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {steady.map((p,i)=>(
                    <tr key={i} style={{borderTop:`1px solid ${C.line2}`}}>
                      <td style={{padding:'5px 9px', fontWeight:700}}>{p.part}</td>
                      <td style={{padding:'5px 9px', textAlign:'right', color:C.tx2}}>{p.demand_cv}</td>
                      <td style={{padding:'5px 9px', textAlign:'right'}}><Tag c="b">{p.recommended_policy}</Tag></td>
                      <td style={{padding:'5px 9px', textAlign:'right', fontWeight:700}}>{fmt(p.eoq)}</td>
                      <td style={{padding:'5px 9px', textAlign:'right'}}>{fmt(p.reorder_point_s)}</td>
                      <td style={{padding:'5px 9px', textAlign:'right'}}>{fmt(p.order_up_to_S)}</td>
                      <td style={{padding:'5px 9px', textAlign:'right', color:C.tx2}}>{fmt(p.safety_stock)}</td>
                      <td style={{padding:'5px 9px', textAlign:'right', color:C.tx2}}>{p.orders_per_year}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {lumpy.length>0 && (
              <div style={{marginTop:10, border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.a4}`, background:C.bg3, padding:'9px 11px'}}>
                <div style={{fontFamily:F.disp, fontWeight:800, fontSize:11.5, color:C.tx, marginBottom:4}}>⚠ MILP-planned (no autopilot): {lumpy.map(p=>p.part).join(', ')}</div>
                <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, lineHeight:1.6}}>
                  These parts are lumpy (CV &gt; 0.5) — a fixed EOQ reorder rule would over- or under-buy. They stay on the time-phased MILP PO schedule (Release plan below), deliberately NOT given an EOQ.
                </div>
              </div>
            )}
            {res.joint_replenishment && (res.joint_replenishment.groups||[]).length>0 && (
              <div style={{marginTop:12, border:`2px solid ${C.gn}`, borderLeft:`5px solid ${C.gn}`, background:C.bg3, padding:'9px 11px'}}>
                <div style={{fontFamily:F.disp, fontWeight:800, fontSize:12, marginBottom:6}}>SS-B · Joint replenishment <Tag c="g">₹{fmt(res.joint_replenishment.total_annual_saving)}/yr saved</Tag></div>
                <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
                  <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
                    <thead><tr style={{background:C.ink}}>
                      {['Supplier','Parts','Common cycle','Indep ₹/yr','Joint ₹/yr','Saving'].map((h,i)=>(
                        <th key={i} style={{color:C.paper, textAlign:i?'right':'left', padding:'5px 9px', fontSize:8.5, textTransform:'uppercase'}}>{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {res.joint_replenishment.groups.map((g,i)=>(
                        <tr key={i} style={{borderTop:`1px solid ${C.line2}`}}>
                          <td style={{padding:'5px 9px', fontWeight:700}}>{g.supplier}</td>
                          <td style={{padding:'5px 9px', textAlign:'right', color:C.tx2}}>{g.parts.join('+')}</td>
                          <td style={{padding:'5px 9px', textAlign:'right'}}>every {g.common_cycle_periods}p · {g.orders_per_year}/yr</td>
                          <td style={{padding:'5px 9px', textAlign:'right', color:C.tx3}}>₹{fmt(g.independent_annual_cost)}</td>
                          <td style={{padding:'5px 9px', textAlign:'right', fontWeight:700}}>₹{fmt(g.joint_annual_cost)}</td>
                          <td style={{padding:'5px 9px', textAlign:'right', fontWeight:700, color: g.annual_saving>0?C.gn:C.tx3}}>{g.annual_saving>0?`₹${fmt(g.annual_saving)}`:'·'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{fontFamily:F.mono, fontSize:9, color:C.tx2, marginTop:5, lineHeight:1.6}}>Parts from one supplier ordered on a COMMON review cycle T*=√(2(S+Σsᵢ)/ΣDᵢhᵢ) amortise the per-PO major cost (₹2,500 truck/admin) across the basket — the coordinated-review win for the steady cohort.</div>
              </div>
            )}
            <Reading formula="EOQ = √(2·D·K / h)  ·  s = μ_L + z·σ_LTD  ·  S = s + EOQ   (D, h on LANDED cost; z from service level α)"
              soWhat={`${steady.length} steady part${steady.length===1?'':'s'} get a standing reorder rule at α = ${sl}; validate it by checking the rolling re-plan below stays low-nervousness as the forecast tail is revealed.`}/>
          </div>
        )}
      </Card>
    </StageSection>
  );
}

// ════════════════════════════════════════════════════════════════════════
// S-4 · ROLLING RE-PLAN & NERVOUSNESS — replays the procurement MILP over a
// sliding horizon (waves), freezing the committed front each round, and measures
// nervousness = Σ|Δ order qty| across consecutive re-plans on the still-open,
// overlapping window. Low nervousness ⇒ a stable plan you can trust week-to-week.
// ════════════════════════════════════════════════════════════════════════
function SrcRolling({ sku, planning, sl }){
  const [rp, setRp] = useState({ waves:4, shift:1, frozen:2 });
  const roll = useSolve('/api/solve/rolling', ()=>rollingPayload(sku, planning, sl, rp));
  const { stale } = useStale('rolling');
  const run = ()=> roll.run().then(d=>{ markSolved('rolling'); return d; }).catch(()=>{});
  const res = roll.result;
  const waves = res ? (res.waves||[]) : [];
  const nerv = res ? res.nervousness : 0;
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  // contextualise nervousness against total planned order volume (final plan)
  const totVol = res && res.final_plan ? (res.final_plan.materials||[]).reduce((s,m)=>s+(m.total_ordered||0),0) : 0;
  const nervPct = totVol>0 ? (nerv/totVol)*100 : 0;
  const tone = nervPct<5 ? C.gn : nervPct<15 ? C.a4 : C.dg;
  const verdict = nervPct<5 ? 'STABLE' : nervPct<15 ? 'MODERATE' : 'NERVOUS';
  const num = (val,key,min,max)=>(
    <input type="number" value={val} min={min} max={max} onChange={e=>setRp({ ...rp, [key]: Math.max(min, Math.min(max, Number(e.target.value)||min)) })}
      style={{ width:54, fontFamily:F.mono, fontSize:11, textAlign:'right', padding:'3px 5px', border:`1px solid ${C.line}`, background:C.paper, color:C.tx }}/>
  );
  return (
    <StageSection step="7" title="Rolling Re-plan & Nervousness" sub="re-solve the plan as the horizon advances and the forecast tail is revealed — how much does the near-term order churn?">
      <Card icon="🌀" title="Rolling-horizon stability" badge={res?verdict:'replay the plan'} badgeTone={res?(nervPct<5?'g':'k'):undefined}
        right={res ? <Provenance kind="solved" asOf={roll.ranAt}/> : undefined}
        info={{ what:'Replays the MILP over a sliding horizon, freezing the committed front, and sums the change in planned order qty across re-plans. Low ⇒ stable.', flows:'rolling.py ← procurement base × {waves, shift, frozen}.' }}
        dev={{ comp:'SrcRolling', props:'solve.rolling.waves, nervousness' }}>
        <Grid cols={4}>
          <Field label="Re-plans (waves)" hint="number of rolling re-solves">{num(rp.waves,'waves',2,8)}</Field>
          <Field label="Shift / wave" hint="periods advanced each wave">{num(rp.shift,'shift',1,4)}</Field>
          <Field label="Frozen front" hint="committed periods (no re-plan)">{num(rp.frozen,'frozen',0,6)}</Field>
          <Field label=" " hint=" "><Btn kind="accent" sm onClick={run}>{roll.solving?'⏳ Replaying…':'🌀 Run rolling re-plan'}</Btn></Field>
        </Grid>
        {stale && res && <div style={{margin:'8px 0'}}><StaleMark since="(sourcing or demand changed)" onNav={run} go="re-run"/></div>}
        {roll.error && <div style={{margin:'8px 0', padding:'7px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>rolling error: {roll.error}</div>}
        {res && (
          <div style={{marginTop:12}}>
            <div style={{display:'flex', gap:8, marginBottom:12}}>
              <Blk label="Nervousness" value={fmt(nerv)} sub="Σ|Δ order qty| over re-plans" accent={tone}/>
              <Blk label="vs plan volume" value={`${nervPct.toFixed(1)}%`} sub={`of ${fmt(totVol)} u planned`} accent={tone}/>
              <Blk label="Verdict" value={verdict} sub={nervPct<5?'trust week-to-week':'expect churn'} tone={nervPct<5?'c':'k'}/>
            </div>
            <div style={{border:`2px solid ${C.line}`}}>
              <div style={{display:'flex', background:C.ink, color:C.paper, fontFamily:F.mono, fontSize:9, fontWeight:700, textTransform:'uppercase'}}>
                {['wave','horizon shift','plan cost','churn vs prev'].map((h,i)=><div key={i} style={{flex:1, padding:'5px 9px', textAlign:i?'right':'left'}}>{h}</div>)}
              </div>
              {waves.map((w,i)=>(
                <div key={i} style={{display:'flex', borderTop:`1px solid ${C.line2}`, fontFamily:F.mono, fontSize:10.5, background: w.error?C.bg3:C.paper}}>
                  <div style={{flex:1, padding:'5px 9px', fontWeight:700}}>#{w.wave}{w.error?` · ${w.error}`:''}</div>
                  <div style={{flex:1, padding:'5px 9px', textAlign:'right', color:C.tx2}}>+{w.shift_weeks} period{w.shift_weeks===1?'':'s'}</div>
                  <div style={{flex:1, padding:'5px 9px', textAlign:'right'}}>₹{fmt(w.total_cost/1000)}K</div>
                  <div style={{flex:1, padding:'5px 9px', textAlign:'right', fontWeight:700, color: (w.wave_nervousness||0)>0?C.dg:C.tx3}}>{i===0?'—':fmt(w.wave_nervousness||0)}</div>
                </div>
              ))}
            </div>
            <Reading formula="nervousness = Σ_waves Σ_part |qty_wave − qty_prev|  over the open, overlapping window (frozen front excluded)"
              soWhat={`At ${nervPct.toFixed(1)}% of planned volume the plan is ${verdict.toLowerCase()}. ${nervPct<5?'The near-term order barely moves as the horizon advances — the policy and lot sizes are robust to the revealed forecast.':'The near-term order shifts materially each re-plan — widen the frozen front or revisit lot sizing to dampen the churn.'}`}/>
          </div>
        )}
      </Card>
    </StageSection>
  );
}
// ════════════════════════════════════════════════════════════════════════
// MEIO · MULTI-ECHELON SAFETY-STOCK PLACEMENT (GAP-MEIO) — where in the RM→WIP→FG
// chain to hold ONE buffer, vs policy.py's single-echelon z·σ on every node. The
// guaranteed-service model (meio.py) minimises total holding cost over integer
// service times; two answers fall out: (1) decoupling points = the stages that
// actually hold safety stock; (2) an FG with net-replenishment 0 is MAKE-TO-ORDER
// — no finished buffer, exactly the "expensive item we never stock" case. The
// committed-service knob is the lever: a longer quote lets the FG go MTO and pushes
// the buffer upstream to cheaper RM/WIP. No faking — if the FG is MTO we show the
// honest "no FG buffer" state, not a fabricated finished safety stock.
// ════════════════════════════════════════════════════════════════════════
function SrcMEIO({ sku, sl }){
  const [maxSvc, setMaxSvc] = useState(7);   // governed committed service time (days)
  const meio = useSolve('/api/solve/meio', ()=>meioPayload(sku, sl, maxSvc));
  const { stale } = useStale('meio');
  const run = ()=> meio.run().then(d=>{ markSolved('meio'); return d; }).catch(()=>{});
  const res = meio.result;
  const stages = res ? (res.stages||[]) : [];
  const fg = stages.find(s=>s.kind==='FG');
  const mto = fg && fg.mode==='make-to-order';
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  const buffers = res ? (res.decoupling_points||[]) : [];
  const roleTone = s=> s.is_decoupling_point ? (s.kind==='FG'?C.dg:C.ac) : C.tx3;
  return (
    <StageSection step="8" title="Multi-Echelon SS Placement (MEIO)" sub="across RM → WIP → FG: where to hold ONE buffer — and which finished goods are make-to-order (no FG stock at all)">
      <Card icon="🎯" title="Decoupling-point placement" badge={res?(mto?'FG make-to-order':`${buffers.length} buffer node${buffers.length===1?'':'s'}`):'place the buffer'} badgeTone={res?(mto?'k':'g'):undefined}
        right={res ? <Provenance kind="solved" asOf={meio.ranAt}/> : undefined}
        info={{ what:'Guaranteed-service MEIO places safety stock at the cheapest decoupling point in the RM→WIP→FG chain, not z·σ at every node. A longer committed service time lets the FG go make-to-order (no finished buffer) and pushes the buffer upstream.', flows:'meio.py ← BOM echelon graph (landed RM cost, rolled WIP, full FG cost) × committed service.' }}
        dev={{ comp:'SrcMEIO', props:'solve.meio.stages, decoupling_points', state:'maxSvc (committed service days)' }}>
        <Grid cols={3}>
          <Field label="Committed service (days)" hint="lead time you quote the customer — longer ⇒ FG can go make-to-order">
            <input type="number" value={maxSvc} min={0} max={60} onChange={e=>setMaxSvc(Math.max(0, Math.min(60, Number(e.target.value)||0)))}
              style={{ width:64, fontFamily:F.mono, fontSize:11, textAlign:'right', padding:'3px 5px', border:`1px solid ${C.line}`, background:C.paper, color:C.tx }}/>
          </Field>
          <Field label="Service level (α)" hint="from the solver-parameters card above"><div style={{fontFamily:F.mono, fontSize:13, fontWeight:700, paddingTop:3}}>{sl}</div></Field>
          <Field label=" " hint=" "><Btn kind="accent" sm onClick={run}>{meio.solving?'⏳ Placing…':'🎯 Place buffers'}</Btn></Field>
        </Grid>
        {stale && res && <div style={{margin:'8px 0'}}><StaleMark since="(sourcing or demand changed)" onNav={run} go="re-place"/></div>}
        {meio.error && <div style={{margin:'8px 0', padding:'7px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>MEIO error: {meio.error}</div>}
        {!res ? (
          <div style={{marginTop:10, padding:'12px', border:`2px dashed ${C.line}`, fontFamily:F.mono, fontSize:11, color:C.tx3}}>
            Place the buffer across the echelon. The model decides which stages hold safety stock (decoupling points) and whether this finished good is worth stocking or better made-to-order — single-echelon policy.py can't see this.
          </div>
        ) : (
          <div style={{marginTop:12}}>
            {/* FG verdict — the make-to-order vs make-to-stock answer the planner asked for */}
            <div style={{border:`2px solid ${C.line}`, borderLeft:`5px solid ${mto?C.dg:C.gn}`, background:C.bg3, padding:'10px 12px', marginBottom:12}}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                <span style={{fontFamily:F.disp, fontWeight:800, fontSize:13}}>{fg ? fg.name : sku} → <span style={{color:mto?C.dg:C.gn}}>{mto?'MAKE-TO-ORDER':'MAKE-TO-STOCK'}</span></span>
                <Tag c={mto?'r':'g'}>{mto?'no FG buffer':`FG buffer ${fmt(fg?fg.safety_stock:0)} u`}</Tag>
              </div>
              <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:5, lineHeight:1.6}}>
                {mto
                  ? `Holding finished value (₹${fmt(fg?fg.unit_cost:0)}/u) is dearer than quoting your ${maxSvc}-day lead — the model holds NO finished safety stock and decouples upstream at ${buffers.join(', ')||'no node'}. Build on the order.`
                  : `The ${maxSvc}-day quote is too tight to absorb upstream lead, so the FG must serve from a finished buffer of ${fmt(fg?fg.safety_stock:0)} u. Lengthen the committed service to push the buffer upstream and free the finished capital.`}
              </div>
            </div>
            {/* per-stage echelon table, RM → WIP → FG */}
            <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
              <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
                <thead><tr style={{background:C.ink}}>
                  {['Stage','Ech','Lead d','In-svc','Out-svc','Net repl τ','Unit ₹','Safety','SS value ₹','Hold ₹/yr','Role'].map((h,i)=>(
                    <th key={i} style={{color:C.paper, textAlign:i<2?'left':'right', padding:'6px 8px', fontSize:8.5, textTransform:'uppercase'}}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {stages.map((s,i)=>(
                    <tr key={i} style={{borderTop:`1px solid ${C.line2}`, background: s.is_decoupling_point?C.bg3:C.paper}}>
                      <td style={{padding:'5px 8px', fontWeight:700}}>{s.name}</td>
                      <td style={{padding:'5px 8px'}}><Tag c={s.kind==='FG'?'a':s.kind==='WIP'?'b':'w'}>{s.kind}</Tag></td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>{s.processing_time}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx3}}>{s.inbound_service}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx3}}>{s.outbound_service}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', fontWeight:700, color: s.net_replenishment>0?C.tx:C.tx3}}>{s.net_replenishment}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>₹{fmt(s.unit_cost)}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', fontWeight:700}}>{s.safety_stock>0?fmt(s.safety_stock):'·'}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>{s.safety_stock_value>0?`₹${fmt(s.safety_stock_value)}`:'·'}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>{s.annual_holding_cost>0?`₹${fmt(s.annual_holding_cost)}`:'·'}</td>
                      <td style={{padding:'5px 8px', textAlign:'right'}}><span style={{fontWeight:700, fontSize:9, color:roleTone(s)}}>{s.is_decoupling_point?'● BUFFER':'○ flow'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{display:'flex', gap:8, marginTop:12}}>
              <Blk label="Buffer nodes" value={`${buffers.length}`} sub={`of ${stages.length} stages`} tone="y"/>
              <Blk label="Total SS holding" value={`₹${fmt(res.total_holding_cost)}`} sub="per year, all echelons" accent={C.dg}/>
              <Blk label="SS capital" value={`₹${fmt(res.total_safety_stock_value)}`} sub="value tied in buffers" tone="k"/>
              <Blk label="Service level" value={`${(res.service_level*100).toFixed(1)}%`} sub={`z = ${res.z}`} tone="c"/>
            </div>
            <Reading formula="τ_j = SI_j + T_j − S_j   ·   ss_j = z·σ_j·√τ_j   ·   min Σ_j h_j·ss_j   (h rises RM→WIP→FG, so the buffer seeks the cheapest node)"
              soWhat={mto
                ? `At a ${maxSvc}-day quote the model makes ${fg?fg.name:sku} to order — zero finished buffer — and holds only ₹${fmt(res.total_holding_cost)}/yr of cheap upstream stock at ${buffers.join(', ')||'no node'}. This is the multi-echelon answer single-echelon policy can't give: it would have prescribed a finished buffer you'd never want.`
                : `The buffer sits at ${buffers.join(', ')||'no node'} for ₹${fmt(res.total_holding_cost)}/yr. Lengthen the committed service time to let the FG go make-to-order and shift capital to cheaper upstream inventory; shorten it to serve faster off a finished buffer.`}/>
          </div>
        )}
      </Card>
    </StageSection>
  );
}
// ════════════════════════════════════════════════════════════════════════
// W8 · NETWORK / POOLED MEIO — multi-product risk pooling on SHARED parts. SrcMEIO
// (above) places ONE buffer per FG assembly TREE; but TPAC's finished SKUs share the
// same RM/CN parts, so a part buffered per-tree is over-buffered. This card pools each
// shared part across the SKUs that consume it: σ_pool = √(Σσ²+2ρΣσᵢσⱼ) ≤ Σσ (the
// square-root law), so one central buffer holds strictly less stock at the same service
// level. The gap (decentralised − pooled) is capital freed; pooling is only RECOMMENDED
// when its annual holding dividend clears the pooling fixed cost — an honest decision,
// not a free lunch. New module meio_network.py; existing solver logic untouched.
// ════════════════════════════════════════════════════════════════════════
function SrcMEIONet({ sl }){
  const [rho, setRho] = useState('');           // demand correlation (seed 0)
  const [fixed, setFixed] = useState('');       // pooling fixed cost ₹/yr (seed 0)
  const [pairwise, setPairwise] = useState(false);   // MN-C — per-pair ρ from XYZ co-movement
  const net = useSolve('/api/solve/meio-network',
    ()=>meioNetworkPayload(sl, rho===''?0:rho, fixed===''?0:fixed, { pairwise }));
  const { stale } = useStale('meionet');
  const run = ()=> net.run().then(d=>{ markSolved('meionet'); return d; }).catch(()=>{});
  const res = net.result;
  const parts = res ? (res.parts||[]) : [];
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  const shared = parts.filter(p=>p.poolable);
  return (
    <StageSection step="8b" title="Network Risk Pooling (multi-product MEIO)" sub="pool a SHARED part's buffer across every finished SKU that uses it — the cross-tree capital single-tree MEIO leaves on the table">
      <Card icon="🕸️" title="Pooled-buffer placement" badge={res?`${res.recommended_pool.length} part${res.recommended_pool.length===1?'':'s'} to pool`:'pool shared parts'} badgeTone={res?(res.recommended_pool.length?'g':'k'):undefined}
        right={res ? <Provenance kind="solved" asOf={net.ranAt}/> : undefined}
        info={{ what:'Statistical risk pooling: a part shared by N SKUs needs σ_pool=√(Σσ²+2ρΣσᵢσⱼ) ≤ Σσ of safety stock as ONE central buffer vs a buffer per tree. The gap is capital freed at the same service level.', flows:'meio_network.py ← shared BOM parts × per-SKU forecast variability (MAPE).' }}
        dev={{ comp:'SrcMEIONet', props:'solve.meionet.parts, recommended_pool', state:'rho, pooling_fixed_cost' }}>
        <Grid cols={4}>
          <SolverInput label="Demand correlation ρ" seed={0} value={rho} onChange={setRho} min={-0.99} max={0.99} w={90} hint={pairwise?'base ρ — scaled per pair by XYZ':'across SKUs · 0 = full pooling benefit'}/>
          <SolverInput label="Pooling fixed cost" seed={0} value={fixed} onChange={setFixed} min={0} prefix="₹" w={110} hint="central-buffer running cost / yr"/>
          <Field label="Pairwise ρ (MN-C)" hint="per-pair from XYZ co-movement">
            <label style={{display:'flex', alignItems:'center', gap:6, fontFamily:F.mono, fontSize:10, fontWeight:700, color:C.tx2, cursor:'pointer', paddingTop:5}}>
              <input type="checkbox" checked={pairwise} onChange={e=>setPairwise(e.target.checked)}/>{pairwise?'matrix':'scalar'}
            </label>
          </Field>
          <Field label=" " hint=" "><Btn kind="accent" sm onClick={run}>{net.solving?'⏳ Pooling…':'🕸️ Pool buffers'}</Btn></Field>
        </Grid>
        {stale && res && <div style={{margin:'8px 0'}}><StaleMark since="(sourcing or demand changed)" onNav={run} go="re-pool"/></div>}
        {net.error && <div style={{margin:'8px 0', padding:'7px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Pooling error: {net.error}</div>}
        {!res ? (
          <div style={{marginTop:10, padding:'12px', border:`2px dashed ${C.line}`, fontFamily:F.mono, fontSize:11, color:C.tx3}}>
            Pool the shared-part buffers across the finished portfolio. The model reports, per part, the safety stock held separately per SKU vs one pooled buffer — and the capital that consolidation frees at the same service level.
          </div>
        ) : (
          <div style={{marginTop:12}}>
            <div style={{display:'flex', gap:8, marginBottom:12}}>
              <Blk label="Capital freed" value={`₹${fmt(res.total_capital_freed)}`} sub="SS value: separate − pooled" accent={C.gn}/>
              <Blk label="Annual dividend" value={`₹${fmt(res.total_annual_dividend)}`} sub="holding saved on pooled parts" tone="c"/>
              <Blk label="Parts to pool" value={`${res.recommended_pool.length}`} sub={`of ${shared.length} shared`} tone="y"/>
              <Blk label="Service level" value={`${(res.service_level*100).toFixed(1)}%`} sub={`z = ${res.z} · ρ = ${res.correlation}`} tone="k"/>
            </div>
            <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
              <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
                <thead><tr style={{background:C.ink}}>
                  {['Shared part','# SKUs','Σσ','σ pooled','SS separate','SS pooled','Place at','Units freed','Dividend ₹/yr','Verdict'].map((h,i)=>(
                    <th key={i} style={{color:C.paper, textAlign:i<1?'left':i===6?'center':'right', padding:'6px 8px', fontSize:8.5, textTransform:'uppercase'}}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {parts.map((p,i)=>(
                    <tr key={i} style={{borderTop:`1px solid ${C.line2}`, background: p.recommend_pool?C.bg3:C.paper}}>
                      <td style={{padding:'5px 8px', fontWeight:700}}>{p.name}{p.pairwise_corr?<span title="pairwise ρ matrix" style={{color:C.ac}}> ⊞</span>:''}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color: p.poolable?C.tx:C.tx3}}>{p.n_skus}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx3}}>{p.sum_sigma}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>{p.sigma_pooled}</td>
                      <td style={{padding:'5px 8px', textAlign:'right'}}>{fmt(p.ss_decentralised)}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', fontWeight:700}}>{fmt(p.ss_pooled)}</td>
                      <td style={{padding:'5px 8px', textAlign:'center', fontSize:9, color: (p.placed_at||'').indexOf('finished')>=0?C.ac:C.tx2}}>{p.poolable?(p.placed_at||'raw').split(' ')[0]:'·'}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color: p.units_saved>0?C.gn:C.tx3, fontWeight:700}}>{p.units_saved>0?fmt(p.units_saved):'·'}</td>
                      <td style={{padding:'5px 8px', textAlign:'right', color:C.tx2}}>{p.annual_dividend>0?`₹${fmt(p.annual_dividend)}`:'·'}</td>
                      <td style={{padding:'5px 8px', textAlign:'right'}}><Tag c={p.recommend_pool?'g':(p.poolable?'w':'k')}>{p.recommend_pool?'POOL':(p.poolable?'marginal':'single')}</Tag></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Reading formula="σ_pool = √(Σσᵢ² + 2ρᵢⱼ·Σσᵢσⱼ) ≤ Σσᵢ   ·   place pooled buffer at argmin(holding₹) echelon   ·   dividend = decentralised − pooled holding"
              soWhat={res.recommended_pool.length
                ? `Pooling ${res.recommended_pool.join(', ')} into central buffer(s) frees ₹${fmt(res.total_capital_freed)} (₹${fmt(res.total_annual_dividend)}/yr holding) at the SAME ${(res.service_level*100).toFixed(0)}% service${parts.some(p=>(p.placed_at||'').indexOf('finished')>=0)?' — and some buffers are cheaper held POSTPONED at the finished echelon (shorter lead to cover) than as raw (MN-B place+pool)':' (each placed at its cheapest echelon — MN-B)'}. The cohort per part is its REAL consuming SKUs (MN-A); ${parts.some(p=>p.pairwise_corr)?'ρ is per-pair from XYZ co-movement (MN-C ⊞) — correlated cohorts pool less':'raise ρ toward 1 and the dividend shrinks (correlated demand pools poorly)'}.`
                : `No part clears the pooling fixed cost at ρ = ${res.correlation}: either the shared parts are too correlated to pool or the central-buffer cost outweighs the dividend. Honest "don't pool" — not a fabricated saving.`}/>
          </div>
        )}
      </Card>
    </StageSection>
  );
}
// ════════════════════════════════════════════════════════════════════════
// S-7 · COSTLY-ITEM NEWSVENDOR (h vs p) + CVaR — for a chosen part, the single-period
// stocking decision under its own overage/underage economics. cvar.py returns BOTH the
// expected-value (critical-ratio) order-up-to AND the CVaR-β-robust one (Rockafellar–Uryasev),
// so the planner sees the robustness premium — the extra units the tail-robust plan holds
// over the mean-optimal plan. When holding dominates (low critical ratio) the order-up-to
// collapses toward the mean: the costly-item make-to-order regime. h/p are GOVERNED inputs
// seeded from the part's landed economics (seed→user), so no number is fabricated.
// ════════════════════════════════════════════════════════════════════════
function SrcNewsvendor({ sku }){
  const bom = M.bom || [];
  // default to the costliest part by landed cost — the one whose stocking economics matter most
  const landedOf = b => effLandedCost(b.cost, getSourcing(b.part, b));
  const costliest = bom.slice().sort((a,b)=>landedOf(b)-landedOf(a))[0] || {};
  const seedOver = b => Math.round(landedOf(b) * (Number(b.hold)||20)/100 * 100)/100; // ₹/unit/yr holding ⇒ overage
  const seedUnder = b => Math.round(landedOf(b) * 0.5);                                // stockout/expedite premium ≈ ½ part value
  const [partId, setPartId] = useState(costliest.part || (bom[0]||{}).part);
  const part = bom.find(b=>b.part===partId) || costliest;
  const [ov, setOv] = useState(seedOver(costliest));
  const [un, setUn] = useState(seedUnder(costliest));
  const [beta, setBeta] = useState(0.95);
  const onPart = id => { const b = bom.find(x=>x.part===id)||{}; setPartId(id); setOv(seedOver(b)); setUn(seedUnder(b)); };
  const nv = useSolve('/api/solve/cvar', ()=>cvarPayload(sku, partId, ov, un, beta));
  const run = ()=> nv.run().then(d=>{ markSolved('cvar'); return d; }).catch(()=>{});
  const res = nv.result;
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  const cr = res ? res.critical_ratio : null;
  // make-to-order regime: when the critical ratio is low the optimal stock barely exceeds the mean
  const mto = res ? (res.safety_stock <= 0.5 || cr < 0.35) : false;
  const num = (val,set,min,max,step)=>(
    <input type="number" value={val} min={min} max={max} step={step||1} onChange={e=>set(Math.max(min, Math.min(max, Number(e.target.value)||0)))}
      style={{ width:74, fontFamily:F.mono, fontSize:11, textAlign:'right', padding:'3px 5px', border:`1px solid ${C.line}`, background:C.paper, color:C.tx }}/>
  );
  return (
    <StageSection step="9" title="Costly-Item Newsvendor (h vs p) + CVaR" sub="for an expensive part — the single-period stock that balances holding vs stockout, and how much MORE a tail-robust (CVaR) plan would hold">
      <Card icon="⚖️" title="Newsvendor & CVaR-robust stocking" badge={res?(mto?'make-to-order regime':`CR ${(cr*100).toFixed(0)}%`):'balance h vs p'} badgeTone={res?(mto?'k':'g'):undefined}
        right={res ? <Provenance kind="solved" asOf={nv.ranAt}/> : undefined}
        info={{ what:'For the chosen part: the expected-value (critical-ratio) order-up-to AND the CVaR-β-robust one. The gap is the robustness premium — units held to cover the demand tail. Low critical ratio ⇒ holding dominates ⇒ make-to-order.', flows:'cvar.py (Rockafellar–Uryasev LP) ← part lead-time demand μ/σ × {overage h, underage p, β}.' }}
        dev={{ comp:'SrcNewsvendor', props:'solve.cvar.{critical_ratio,order_up_to,expected_value_order_up_to,robustness_premium_units}', state:'partId, overage, underage, beta' }}>
        <Grid cols={4}>
          <Field label="Part" hint="seeded to the costliest landed part">
            <select value={partId} onChange={e=>onPart(e.target.value)}
              style={{ fontFamily:F.mono, fontSize:11, padding:'3px 5px', border:`1px solid ${C.line}`, background:C.paper, color:C.tx, maxWidth:150 }}>
              {bom.map(b=><option key={b.part} value={b.part}>{b.name} · ₹{fmt(landedOf(b))}</option>)}
            </select>
          </Field>
          <Field label="Overage h (₹/unit)" hint="cost of one leftover unit — holding/obsolescence">{num(ov,setOv,0,100000,1)}</Field>
          <Field label="Underage p (₹/unit)" hint="cost of one stockout unit — lost margin / expedite">{num(un,setUn,0,1000000,1)}</Field>
          <Field label="CVaR β (tail)" hint="0.95 ⇒ robust to worst 5% of demand">{num(beta,setBeta,0.5,0.999,0.01)}</Field>
        </Grid>
        <div style={{margin:'10px 0'}}><Btn kind="accent" sm onClick={run}>{nv.solving?'⏳ Solving…':'⚖️ Solve newsvendor + CVaR'}</Btn></div>
        {nv.error && <div style={{margin:'8px 0', padding:'7px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>CVaR error: {nv.error}</div>}
        {!res ? (
          <div style={{padding:'12px', border:`2px dashed ${C.line}`, fontFamily:F.mono, fontSize:11, color:C.tx3}}>
            Pick a costly part and set its overage h (cost to hold a leftover) and underage p (cost of a stockout). The model returns the cost-balancing stock and the extra a tail-robust plan would carry — and flags the make-to-order regime when holding dominates.
          </div>
        ) : (
          <div>
            <div style={{border:`2px solid ${C.line}`, borderLeft:`5px solid ${mto?C.dg:C.gn}`, background:C.bg3, padding:'10px 12px', marginBottom:12}}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                <span style={{fontFamily:F.disp, fontWeight:800, fontSize:13}}>{part.name} → <span style={{color:mto?C.dg:C.gn}}>{mto?'MAKE-TO-ORDER':'STOCK TO ORDER-UP-TO'}</span></span>
                <Tag c={mto?'r':'g'}>critical ratio {(cr*100).toFixed(0)}%</Tag>
              </div>
              <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:5, lineHeight:1.6}}>
                {mto
                  ? `With overage ₹${fmt(ov)} dominating underage ₹${fmt(un)}, the critical ratio is only ${(cr*100).toFixed(0)}% — the optimal stock barely clears the mean (safety ${fmt(res.safety_stock)} u). Hold near-zero buffer and build this part to the order.`
                  : `Underage ₹${fmt(un)} outweighs overage ₹${fmt(ov)} (critical ratio ${(cr*100).toFixed(0)}%), so it pays to pre-stock: the expected-value plan orders up to ${fmt(res.expected_value_order_up_to)} u; the CVaR-${(beta*100).toFixed(0)} plan holds ${res.robustness_premium_units>=0?'+':''}${fmt(res.robustness_premium_units)} more to cover the tail.`}
              </div>
            </div>
            <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
              <Blk label="Critical ratio" value={`${(cr*100).toFixed(0)}%`} sub="p / (p + h)" tone={mto?'k':'c'}/>
              <Blk label="EV order-up-to" value={fmt(res.expected_value_order_up_to)} sub="mean-optimal (newsvendor)" tone="b"/>
              <Blk label={`CVaR-${(beta*100).toFixed(0)} order-up-to`} value={fmt(res.order_up_to)} sub="tail-robust (R–U LP)" accent={C.ac}/>
              <Blk label="Robustness premium" value={`${res.robustness_premium_units>=0?'+':''}${fmt(res.robustness_premium_units)} u`} sub="CVaR − EV stock" accent={res.robustness_premium_units>0?C.dg:C.tx3}/>
              <Blk label="Implied safety" value={fmt(res.safety_stock)} sub={`over mean ${fmt(res.mean_demand)} u`} tone="y"/>
            </div>
            <Reading formula="critical ratio = p / (p + h)   ·   Q*_EV = μ + z(CR)·σ   ·   Q*_CVaR = argmin_Q [ α + 1/((1−β)S)·Σ(L_s−α)⁺ ]   (Rockafellar–Uryasev)"
              soWhat={mto
                ? `${part.name} sits in the make-to-order regime: holding a leftover (₹${fmt(ov)}) costs more than the stocking it buys back, so the optimizer refuses to pre-build. This is the costly-item case — pair it with the MEIO card to confirm the buffer belongs upstream, not on this node.`
                : `It pays to stock ${part.name}. The CVaR-${(beta*100).toFixed(0)} plan carries ${res.robustness_premium_units>0?`${fmt(res.robustness_premium_units)} units more than`:'no more than'} the mean-optimal plan to protect the worst ${(100-beta*100).toFixed(0)}% of demand — that premium is the price of robustness you choose to pay or not.`}/>
          </div>
        )}
      </Card>
    </StageSection>
  );
}
// ════════════════════════════════════════════════════════════════════════
// S-5 · POSTPONABLE vs PINNED PO RELEASES — release-timing slack derived from the MILP's
// OWN solved inventory trajectory (no extra solve, no faking). Per part, implied per-period
// consumption = inv[t−1] + arrivals[t] − inv[t]; a PO landing at period a can slide later by
// as many periods as the stock already on hand (inv[a−1]) covers the consumption that follows.
// slack 0 ⇒ PINNED (just-in-time, fragile to any slip); slack ≥ 1 ⇒ POSTPONABLE (its capital
// outlay can be deferred). Surfaces the working-capital and flexibility the flat release plan hides.
// ════════════════════════════════════════════════════════════════════════
function SrcPostpone({ proc }){
  const res = proc && proc.result;
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  let rows=null, postponable=0, pinned=0, deferValue=0, slackUnits=0;
  if(res){
    rows=[];
    (res.materials||[]).forEach((m,mi)=>{
      const inv = m.inventory||[]; const T = inv.length;
      const pos = m.purchase_orders||[];
      if(!T || !pos.length) return;
      // arrivals per period from the PO list (arrive_period carries release + lead time)
      const arrivals = new Array(T).fill(0);
      pos.forEach(po=>{ if(po.arrive_period<T) arrivals[po.arrive_period]+=po.quantity; });
      // implied consumption from the solved balance (clamped ≥ 0 for display robustness)
      const cons = new Array(T).fill(0);
      for(let t=0;t<T;t++){ cons[t] = Math.max(0, (t>0?inv[t-1]:0) + arrivals[t] - inv[t]); }
      pos.forEach((po,pi)=>{
        const a = po.arrive_period;
        let cover = a>0 ? inv[a-1] : 0;       // stock on hand the period BEFORE this PO lands
        let need = 0, slack = 0;
        for(let j=a;j<T;j++){ need += cons[j]; if(cover>=need) slack++; else break; }
        const pin = slack<=0;
        if(pin) pinned++; else { postponable++; deferValue += po.cost||0; slackUnits += slack; }
        rows.push([`PO-${String(mi+1).padStart(2,'0')}${pi+1}`, m.name,
          po.quantity.toLocaleString('en-IN'), `P${po.period}→${po.arrive_period}`,
          pin?'pinned':`+${slack}p`, pin, `₹${((po.cost||0)/1000).toFixed(0)}K`]);
      });
    });
    rows.sort((a,b)=> (a[5]===b[5]) ? 0 : (a[5]? -1 : 1)); // pinned first (the ones you must protect)
  }
  return (
    <StageSection step="10" title="Postponable vs Pinned PO Releases" sub="which releases must land just-in-time (pinned) and which can slide later — the release-timing slack inside the committed plan">
      <Card icon="⏳" title="Release-timing slack" badge={res?`${postponable} postponable · ${pinned} pinned`:'derive from plan'} badgeTone={res?'g':undefined}
        right={res ? <Provenance kind="derived" asOf={proc.ranAt}/> : undefined}
        info={{ what:'Per PO, how many periods its release could slide before the stock already on hand runs dry. 0 ⇒ pinned (JIT, protect it); ≥1 ⇒ postponable (defer the cash). Derived from the MILP’s own inventory trajectory — no extra solve.', flows:'← procurement materials[].{inventory, purchase_orders}.' }}
        dev={{ comp:'SrcPostpone', props:'solve.procurement.materials[].inventory/purchase_orders (derived slack)' }}>
        {!res ? (
          <div style={{padding:'12px', border:`2px dashed ${C.line}`, fontFamily:F.mono, fontSize:11, color:C.tx3}}>
            Run the procurement MILP above — this reads its solved inventory path and tells you, per PO, whether the release is pinned (must land just-in-time) or has slack you can postpone to defer working capital.
          </div>
        ) : !rows.length ? (
          <div style={{padding:'10px 11px', border:`2px solid ${C.line}`, background:C.bg3, fontFamily:F.mono, fontSize:11, color:C.tx3}}>No POs in the horizon to classify.</div>
        ) : (
          <div>
            <div style={{display:'flex', gap:8, marginBottom:12, flexWrap:'wrap'}}>
              <Blk label="Postponable POs" value={`${postponable}`} sub={`of ${postponable+pinned} releases`} tone="c"/>
              <Blk label="Pinned (JIT)" value={`${pinned}`} sub="must land on time" accent={C.dg}/>
              <Blk label="Deferrable cash" value={`₹${fmt(deferValue/1000)}K`} sub="outlay you can slide later" tone="y"/>
              <Blk label="Total slack" value={`${slackUnits} p`} sub="period-shifts available" tone="g"/>
            </div>
            <DataTable dense cols={['PO','Part','Qty','Release→Arrive','Slack','Value']} align={['left','left','right','left','right','right']}
              rows={rows.map(r=>[r[0], r[1], r[2], r[3],
                r[5] ? <Tag c="r">pinned</Tag> : <Tag c="g">{r[4]}</Tag>, r[6]])}/>
            <Reading formula="slack(PO) = max k : inv[arrive−1] ≥ Σ consumption[arrive … arrive+k−1]   ·   slack 0 ⇒ pinned, ≥1 ⇒ postponable"
              soWhat={`${postponable} of ${postponable+pinned} releases carry slack — ₹${fmt(deferValue/1000)}K of purchasing could slide later without breaching cover, freeing working capital. The ${pinned} pinned PO${pinned===1?'':'s'} are the just-in-time releases to protect first when a supplier slips.`}/>
          </div>
        )}
      </Card>
    </StageSection>
  );
}
// ════════════════════════════════════════════════════════════════════════
// S-8 · MRP-AT-SCALE EXCEPTION ROLL-UP — the answer to "what about 10+ parts?". Not a giant
// per-part × per-period grid (unreadable at scale); instead an exception-first roll-up: every
// part scored on real signals from the solve — zero-cover (JIT-fragile), capital concentration,
// reorder frequency — with only the flagged parts surfaced for action and the rest rolled into
// a one-line "clear" count. Plus the FG’s projected shortages as the top-level exception. The
// pattern is what scales: a planner reads 3 exceptions, not a 200-cell matrix. All flags derived.
// ════════════════════════════════════════════════════════════════════════
function SrcExceptions({ proc }){
  const res = proc && proc.result;
  const fmt = n=> Math.round(n).toLocaleString('en-IN');
  let parts=null, flagged=0, fgShort=null, fgName='';
  if(res){
    const mats = res.materials||[];
    const caps = mats.map(m=>m.total_landed_cost||0).sort((a,b)=>b-a);
    const capCut = caps.length ? caps[Math.max(0, Math.floor(caps.length/3)-1)] : Infinity; // top tercile by capital
    parts = mats.map(m=>{
      const inv = m.inventory||[];
      const minCover = inv.length ? Math.min(...inv) : 0;
      const reorders = m.num_orders||0;
      const ex=[];
      if(inv.length && minCover<=0) ex.push('zero-cover');                 // runs to JIT — fragile to any slip
      if((m.total_landed_cost||0)>=capCut && caps.length>=3) ex.push('high-capital');
      if(reorders>=4) ex.push('many-releases');                            // frequent reorders ⇒ ordering-cost / nervousness risk
      return { name:m.name, minCover, reorders, capital:m.total_landed_cost||0, ordered:m.total_ordered||0, ex };
    });
    flagged = parts.filter(p=>p.ex.length).length;
    parts.sort((a,b)=> b.ex.length-a.ex.length || b.capital-a.capital);
    const fg = (res.products||[])[0] || {}; fgName = fg.name||'';
    fgShort = (fg.shortages||[]).map((q,t)=>({t,q})).filter(s=>s.q>0.5);
  }
  const exLabel = { 'zero-cover':['r','zero-cover'], 'high-capital':['a','high-capital'], 'many-releases':['y','many-releases'] };
  return (
    <StageSection step="12" title="MRP Exception Roll-up (at scale)" sub="not a giant grid — every part scored on the solve, only the exceptions surfaced; the pattern that scales to a 10+ part BOM">
      <Card icon="🚦" title="Exception-based MRP" badge={res?(flagged?`${flagged} need attention`:'all clear'):'roll up the plan'} badgeTone={res?(flagged?'k':'g'):undefined}
        right={res ? <Provenance kind="derived" asOf={proc.ranAt}/> : undefined}
        info={{ what:'Scores every part on zero-cover (JIT-fragile), capital concentration and reorder frequency, and surfaces only the flagged ones — the exception-first view that stays readable as the BOM grows. FG shortages shown as the top exception.', flows:'← procurement materials[] + products[0].shortages (derived flags).' }}
        dev={{ comp:'SrcExceptions', props:'solve.procurement.materials[] (derived exception flags)' }}>
        {!res ? (
          <div style={{padding:'12px', border:`2px dashed ${C.line}`, fontFamily:F.mono, fontSize:11, color:C.tx3}}>
            Run the procurement MILP — this rolls every part up into an exception list (zero-cover, capital-heavy, churny) so a planner reads the few parts that need action instead of a part × period matrix that doesn’t scale.
          </div>
        ) : (
          <div>
            {fgShort && fgShort.length>0 && (
              <div style={{border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, padding:'9px 11px', marginBottom:12}}>
                <div style={{fontFamily:F.disp, fontWeight:800, fontSize:12, color:C.dg, marginBottom:3}}>⚠ Top exception — {fgName} projects {fgShort.length} shortage period{fgShort.length===1?'':'s'}</div>
                <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>{fgShort.map(s=>`P${s.t} (−${fmt(s.q)}u)`).join('  ·  ')}  — resolve before drilling part exceptions.</div>
              </div>
            )}
            <div style={{display:'flex', gap:8, marginBottom:12, flexWrap:'wrap'}}>
              <Blk label="Parts flagged" value={`${flagged}`} sub={`of ${parts.length} in BOM`} tone={flagged?'k':'c'}/>
              <Blk label="Clear" value={`${parts.length-flagged}`} sub="no exception — rolled up" tone="g"/>
              <Blk label="BOM capital" value={`₹${fmt(parts.reduce((s,p)=>s+p.capital,0)/1000)}K`} sub="total landed across parts" tone="y"/>
            </div>
            <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
              <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
                <thead><tr style={{background:C.ink}}>
                  {['Part','Min cover','Reorders','Capital ₹','Status'].map((h,i)=>(
                    <th key={i} style={{color:C.paper, textAlign:i?'right':'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {parts.map((p,i)=>(
                    <tr key={i} style={{borderTop:`1px solid ${C.line2}`, background:p.ex.length?C.bg3:C.paper}}>
                      <td style={{padding:'5px 9px', fontWeight:700}}>{p.name}</td>
                      <td style={{padding:'5px 9px', textAlign:'right', color:p.minCover<=0?C.dg:C.tx2, fontWeight:p.minCover<=0?700:400}}>{fmt(p.minCover)}</td>
                      <td style={{padding:'5px 9px', textAlign:'right', color:C.tx2}}>{p.reorders}</td>
                      <td style={{padding:'5px 9px', textAlign:'right', color:C.tx2}}>₹{fmt(p.capital/1000)}K</td>
                      <td style={{padding:'5px 9px', textAlign:'right'}}>
                        {p.ex.length ? <span style={{display:'inline-flex', gap:4, flexWrap:'wrap', justifyContent:'flex-end'}}>{p.ex.map((e,j)=><Tag key={j} c={exLabel[e][0]}>{exLabel[e][1]}</Tag>)}</span>
                                     : <Tag c="g">✓ clear</Tag>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Reading formula="exception = zero-cover (min inv ≤ 0) ∨ high-capital (top-tercile landed) ∨ many-releases (≥4 reorders)   ·   surface flagged, roll up the rest"
              soWhat={flagged
                ? `${flagged} of ${parts.length} parts need attention — a planner acts on these, not on a ${parts.length}×period grid. At a 10+ part BOM this is the difference between a readable worklist and an unscannable matrix; the ${parts.length-flagged} clear part${parts.length-flagged===1?'':'s'} stay rolled up.`
                : `No part trips an exception — every part holds cover, no capital concentration or churn flag. At scale this empty state is the signal the plan is healthy without reading a single cell.`}/>
          </div>
        )}
      </Card>
    </StageSection>
  );
}
window.StageSourcing = StageSourcing;
