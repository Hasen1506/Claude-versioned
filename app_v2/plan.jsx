// ════════════════════════════════════════════════════════════════════════
// plan.jsx — Aggregate Plan / S&OP (AggregateTab). Sub-tabs: Strategy ·
// Capacity · Workforce · Disaggregation.
// ════════════════════════════════════════════════════════════════════════
// Seed planning economics — DEFAULT cost/capacity params for the aggregate solve.
// These are placeholders pending a dedicated Plan "cost inputs" card (deferred);
// they're chosen so the solve is non-degenerate and the capacity duals are real.
const PLAN_PARAMS = {
  init_workforce: 42, rate_per_worker: 30,        // ≈1,260 u/mo regular capacity
  reg_cost_per_unit: 820, ot_cost_per_unit: 1230, // ₹/u (OT = 1.5×)
  holding_cost_per_unit: 45, backorder_cost_per_unit: 1500,
  hire_cost: 18000, fire_cost: 25000, wage_per_worker: 22000,
  max_ot_pct: 0.25, min_workforce: 30, max_workforce: 60, allow_backorder: true,
};
// aggregate result → the {m,dem,cap,prod,inv} row shape the CapacityChart/table use.
function aggMonths(res){
  if(!res || !res.periods) return null;
  const rate = res.rate_per_worker || 0;
  return res.periods.map(p=>({
    m:'P'+p.period,
    dem:Math.round(p.demand),
    cap:Math.round(rate*p.workforce),
    prod:Math.round(p.regular_production + p.overtime_production),
    inv:Math.round(p.inventory - p.backorder),
  }));
}

// W4 — effective governed plan-cost param: override (config.planParams) else seed.
function planParam(config, k){
  const v = (config.planParams || {})[k];
  return (v!=null && v!=='') ? Number(v) : PLAN_PARAMS[k];
}
// boolean governed override (allow_backorder etc.) — config wins if explicitly set, else seed.
function planBool(config, k){
  const v = (config.planParams || {})[k];
  return (v===true || v===false) ? v : PLAN_PARAMS[k];
}
// W4 · PL-1 — the line registry total monthly capacity: the SAME M.lines the
// production MILP respects. The aggregate plan must reconcile to THIS ceiling,
// not to an arbitrary labor number (was the mock's single-line 1,240 u/mo).
function lineRegistryCapacity(){
  return (M.lines || []).reduce((s,l)=>s + (Number(l.cap)||0), 0);
}

function StagePlan({ onNav }) {
  const { config, setConfig } = useConfig();
  // family monthly demand (mock 6-month profile) split per finished SKU by annual share,
  // so the solver can disaggregate it back — sku_plans feeds the Disaggregation card.
  const rate = planParam(config, 'rate_per_worker') || 1;
  const lineCap = lineRegistryCapacity();
  // PL-1 — bound the workforce so regular capacity can never exceed the line
  // registry ceiling: max regular units = rate · max_workforce ≤ Σ line cap.
  const wfCeiling = Math.max(planParam(config,'min_workforce')+1, Math.round(lineCap / rate));
  const agg = useSolve('/api/solve/aggregate', ()=>{
    const fg = M.products.filter(p=>p.cat==='Finished');
    const months = M.aggregate.months;
    const totAnnual = fg.reduce((s,p)=>s+(p.demand||0),0) || 1;
    // labor_hours_per_unit — demand-weighted, mean-normalised labor content (cycle/60),
    // so a labor-heavy SKU consumes proportionally more family capacity WITHOUT rescaling
    // the aggregate vs the governed rate_per_worker (aggLaborWeights, store.jsx). Flat 1.0
    // fallback when no cycle data ⇒ unchanged default.
    const lw = (typeof aggLaborWeights==='function') ? aggLaborWeights(fg) : {};
    return {
      products: fg.map(p=>({
        name:p.sku,
        forecast: months.map(mo=> Math.max(0, Math.round(mo.dem * (p.demand||0)/totAnnual))),
        labor_hours_per_unit: lw[p.sku] != null ? lw[p.sku] : 1,
      })),
      params: {
        periods: months.length,
        init_workforce: planParam(config,'init_workforce'),
        init_inventory: planOpeningInv(config),   // PL-G5′ — auto-reconciled from Network FG on-hand (labor-weighted); explicit override wins
        rate_per_worker: rate,
        reg_cost_per_unit: planParam(config,'reg_cost_per_unit'),
        ot_cost_per_unit: planParam(config,'ot_cost_per_unit'),
        holding_cost_per_unit: planParam(config,'holding_cost_per_unit'),
        backorder_cost_per_unit: planParam(config,'backorder_cost_per_unit'),
        hire_cost: planParam(config,'hire_cost'),
        fire_cost: planParam(config,'fire_cost'),
        wage_per_worker: planParam(config,'wage_per_worker'),
        max_ot_pct: planParam(config,'max_ot_pct'),
        min_workforce: planParam(config,'min_workforce'),
        max_workforce: wfCeiling,                 // PL-1 — line-registry ceiling
        allow_backorder: planBool(config,'allow_backorder'),   // PL-G8 — governed demand-shorting lever
        // G-P2 — service-driven horizon-end cover (no-op when config.planEndCoverEnabled is off).
        ...(typeof aggEndCoverParams==='function' ? aggEndCoverParams(config) : {}),
      },
    };
  }, { solveKey:'aggregate' });   // LP-C hydrate from loop cache
  const { stale, ranAt } = (typeof useStale==='function') ? useStale('aggregate') : { stale:false };
  const runAgg = ()=> agg.run().then(d=>{ if(typeof markSolved==='function') markSolved('aggregate'); return d; }).catch(()=>{});
  // Batch 4 — make the level-of-aggregation explicit. The S&OP plan pools every
  // finished SKU into a family/portfolio capacity & workforce plan; SKUs come back
  // in step 4. Users kept reading the family numbers as per-SKU numbers.
  const _finP = M.products.filter(p=>p.cat==='Finished');
  // PL-G2 — family count comes from M.items (which carries the family map via _FAMILY);
  // M.products has NO .family field, so the old `_finP.map(p=>p.family)` was always undefined.
  const famN = [...new Set((M.items||[]).map(it=>it.family).filter(Boolean))].length;
  const nFin = _finP.length;
  return (
    <div>
      <StageHeader n="05" title="Plan · Sales & Operations" kicker="Level-vs-chase strategy · seasonal prebuild · workforce plan · capacity duals · SKU disaggregation"
        right={<Btn kind="accent" onClick={runAgg}>{agg.solving?'⏳ Solving…':'⚡ Solve Aggregate'}</Btn>}/>
      <div style={{padding:'9px 18px', borderBottom:`2px solid ${C.line}`, background:C.bg3, display:'flex', alignItems:'center', gap:10}}>
        <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.12em', color:C.onAc, background:C.ink, padding:'3px 8px', whiteSpace:'nowrap'}}>VIEWING ▸ PORTFOLIO AGGREGATE</span>
        <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.4}}>
          This is <b>ONE pooled aggregate plan across your whole finished portfolio</b> — {nFin} SKUs{famN>1?<> spanning <b>{famN} families</b></>:null}, <b>not</b> a separate plan per family. Every finished SKU's committed demand is pooled by <b>worker-time</b> into one capacity &amp; workforce plan; per-SKU numbers are recovered in <b>step 4 · Disaggregation</b>.
        </span>
      </div>
      <div style={{padding:18}}>
        <SolverExplain id="aggregate"/>
        {agg.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Aggregate solver: {agg.error}</div>}
        {stale && <StaleMark since="(demand or cost inputs changed)" onNav={runAgg} go="rerun"/>}
        <StageSection step="0" title="Plan Cost Inputs" sub="governed — seed defaults you may override; the workforce is bounded so the plan can never exceed the line registry"><PlanParamsCard config={config} setConfig={setConfig} lineCap={lineCap} rate={rate} wfCeiling={wfCeiling} agg={agg} ranAt={ranAt} onNav={onNav}/></StageSection>
        <StageSection step="0b" title="Labor content (workforce weighting)" sub="this plan sizes PEOPLE — so each SKU is pooled by worker-time, not machine cycle; set the automated SKUs' hands-on % lower"><PlanLaborContent/></StageSection>
        <StageSection step="1" title="Strategy" sub="level vs chase, and the seasonal prebuild it implies"><PlanStrategy agg={agg}/></StageSection>
        <StageSection step="2" title="Capacity & Duals" sub="demand vs the line-registry ceiling; the labor dual vs the binding line"><PlanCapacity onNav={onNav} agg={agg} lineCap={lineCap}/></StageSection>
        <StageSection step="3" title="Workforce" sub="hire / fire / overtime by period — and the capacity gap each fills"><PlanWorkforce agg={agg} rate={rate} initWf={planParam(config,'init_workforce')}/></StageSection>
        <StageSection step="4" title="Disaggregation" sub="family plan split back to SKUs by mix"><PlanDisagg agg={agg}/></StageSection>
        <StageSection step="5" title="Gap to Target" sub="committed consensus plan vs business target — the S&OP outcome (moved here from Scenarios)"><PlanGap onNav={onNav}/></StageSection>
      </div>
    </div>
  );
}

// W4 · PL-3 — governed plan cost inputs (replaces the PLAN_PARAMS hardcodes as
// the EDITABLE surface; seeds still come from PLAN_PARAMS). Seed→override with
// provenance, same pattern as the Production + Sourcing solver-parameter cards.
function PlanParamsCard({ config, setConfig, lineCap, rate, wfCeiling, agg, ranAt, onNav }){
  const set = (k,v)=> setConfig({ planParams: { ...(config.planParams||{}), [k]:v } });
  const pp = config.planParams || {};
  // PL-G5′ — the plan's t=0 opening stock auto-reconciles FROM Network FG on-hand. The
  // user holds _net.phys physical units (the headline); the solver consumes _net.weighted,
  // the SAME stock measured in the plan's worker-time yardstick (labor-light mix ⇒ fewer
  // worker-hours — a translation, NOT a reduction). aggregate.py InvBal nets Σ qty·weight,
  // so feeding the weighted value is the dimensionally-consistent choice. Override wins.
  // useNetwork() keeps this card reactive to Network edits.
  const { network } = (typeof useNetwork==='function') ? useNetwork() : { network:{} };
  const _net = (typeof networkOpeningInv==='function') ? networkOpeningInv() : { phys:0, weighted:0 };
  const hasOpenOverride = pp.init_inventory!=null && pp.init_inventory!=='';
  const effOpen = hasOpenOverride ? Number(pp.init_inventory) : _net.weighted;
  // PL-G8 — the two demand-shorting levers (decide level-vs-chase) are now governed, not hardcoded.
  const allowBO  = planBool(config,'allow_backorder');
  return (
    <Card icon="🎛️" title="Aggregate-plan cost & capacity inputs" badge="governed" badgeTone="y"
      right={agg && agg.result ? <Provenance kind="solved" asOf={ranAt?ranAt.toLocaleTimeString():undefined}/> : null}
      info={{ what:'Per-unit production/holding/backorder costs, hire/fire/wage costs, and the workforce + overtime + backorder levers the Hax–Meal aggregate LP minimizes. Every field here is a seed you may override per run — including the demand-shorting levers (allow-backorder + backorder cost) that decide level-vs-chase.', flows:'→ /api/solve/aggregate params.' }}
      dev={{ comp:'SolverInput', props:'config.planParams', state:'config.planParams.{rate_per_worker,reg_cost_per_unit,backorder_cost_per_unit,init_workforce,min_workforce,max_ot_pct,allow_backorder,…}' }}>
      <Grid cols={4}>
        <SolverInput label="Rate / worker" seed={PLAN_PARAMS.rate_per_worker} value={pp.rate_per_worker} onChange={v=>set('rate_per_worker',v)} min={1} suffix="u/mo"/>
        <SolverInput label="Regular cost" seed={PLAN_PARAMS.reg_cost_per_unit} value={pp.reg_cost_per_unit} onChange={v=>set('reg_cost_per_unit',v)} min={0} prefix="₹"/>
        <SolverInput label="Overtime cost" seed={PLAN_PARAMS.ot_cost_per_unit} value={pp.ot_cost_per_unit} onChange={v=>set('ot_cost_per_unit',v)} min={0} prefix="₹"/>
        <SolverInput label="Holding cost" seed={PLAN_PARAMS.holding_cost_per_unit} value={pp.holding_cost_per_unit} onChange={v=>set('holding_cost_per_unit',v)} min={0} prefix="₹"/>
        <SolverInput label="Backorder cost" seed={PLAN_PARAMS.backorder_cost_per_unit} value={pp.backorder_cost_per_unit} onChange={v=>set('backorder_cost_per_unit',v)} min={0} prefix="₹" hint="penalty per unit of demand shorted — the lever that pushes the plan toward meeting demand vs carrying the backlog"/>
        <SolverInput label="Hire cost" seed={PLAN_PARAMS.hire_cost} value={pp.hire_cost} onChange={v=>set('hire_cost',v)} min={0} prefix="₹"/>
        <SolverInput label="Fire cost" seed={PLAN_PARAMS.fire_cost} value={pp.fire_cost} onChange={v=>set('fire_cost',v)} min={0} prefix="₹"/>
        <SolverInput label="Wage / worker" seed={PLAN_PARAMS.wage_per_worker} value={pp.wage_per_worker} onChange={v=>set('wage_per_worker',v)} min={0} prefix="₹"/>
        <SolverInput label="Initial workforce" seed={PLAN_PARAMS.init_workforce} value={pp.init_workforce} onChange={v=>set('init_workforce',v)} min={1} suffix="heads" hint="crew on the books at period 0 (the starting point hire/fire moves from)"/>
        <SolverInput label="Min workforce" seed={PLAN_PARAMS.min_workforce} value={pp.min_workforce} onChange={v=>set('min_workforce',v)} min={0} suffix="heads" hint="floor the plan can fire down to"/>
        <SolverInput label="Opening FG inventory" seed={_net.weighted} value={pp.init_inventory} onChange={v=>set('init_inventory',v)} min={0} suffix="u" hint={`auto-reconciled from your Network FG on-hand: ${_net.phys.toLocaleString('en-IN')} u physical → ${_net.weighted.toLocaleString('en-IN')} labor-weighted u (the plan's worker-time yardstick — same stock, NOT a cut). Leave blank to stay linked to Network; type a value only to pin a different opening stock.`}/>
      </Grid>
      <div style={{display:'flex', alignItems:'center', gap:22, marginTop:11, flexWrap:'wrap'}}>
        <label style={{display:'flex', alignItems:'center', gap:7, fontFamily:F.mono, fontSize:10.5, color:C.tx2, cursor:'pointer'}}>
          <input type="checkbox" checked={allowBO} onChange={e=>set('allow_backorder', e.target.checked)}/>
          Allow backorder <span style={{color:C.tx3}}>— off ⇒ demand MUST be met every period (no shorting; forces hire / OT / prebuild)</span>
        </label>
        <div style={{display:'flex', alignItems:'center', gap:7, fontFamily:F.mono, fontSize:10.5, color:C.tx2}}>
          Max overtime
          <NumInput value={Math.round(planParam(config,'max_ot_pct')*100)} suffix="%" w={76}
            onChange={v=> set('max_ot_pct', v===''?'' : Math.max(0, Math.min(1, Number(v)/100)))}/>
          <span style={{color:C.tx3}}>of regular capacity</span>
        </div>
      </div>
      {/* G-P2 — service-driven horizon-end cover. OFF by default ⇒ the plan ends at zero;
          ON ⇒ aggregate.py floors I_T at z(serviceLevel)·σ(agg_demand)·√cover so the horizon
          doesn't end empty. serviceLevel is the shared §7 service target (config.serviceLevel). */}
      <div style={{display:'flex', alignItems:'center', gap:18, marginTop:11, flexWrap:'wrap'}}>
        <label style={{display:'flex', alignItems:'center', gap:7, fontFamily:F.mono, fontSize:10.5, color:C.tx2, cursor:'pointer'}}>
          <input type="checkbox" checked={!!config.planEndCoverEnabled}
            onChange={e=>setConfig({ planEndCoverEnabled: e.target.checked })}/>
          Service-driven end-cover <span style={{color:C.tx3}}>— floor horizon-end inventory at z({Math.round((Number(config.serviceLevel)||0.95)*100)}%)·σ(demand) so the plan doesn't run terminal stock to zero</span>
        </label>
        {config.planEndCoverEnabled && <div style={{display:'flex', alignItems:'center', gap:7, fontFamily:F.mono, fontSize:10.5, color:C.tx2}}>
          Cover
          <NumInput value={config.planEndCoverPeriods==null?1:config.planEndCoverPeriods} suffix="periods" w={92}
            onChange={v=> setConfig({ planEndCoverPeriods: v===''?1 : Math.max(1, Number(v)) })}/>
          <span style={{color:C.tx3}}>of demand-σ</span>
        </div>}
        {config.planEndCoverEnabled && agg && agg.result && agg.result.ending_floor!=null && (()=>{
          const b = agg.result.ending_floor_basis||{}; const endInv = agg.result.ending_inventory;
          const met = endInv!=null && endInv >= agg.result.ending_floor - 0.5;
          return <span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, color:met?C.gn:C.dg}}>
            {met?'✓':'⚠'} floor {Math.round(agg.result.ending_floor).toLocaleString('en-IN')} u
            {b.z!=null && <span style={{color:C.tx3, fontWeight:400}}> = z{b.z}·σ{b.sigma_agg_demand}{b.cover_periods>1?`·√${b.cover_periods}`:''}</span>}
            <span style={{color:C.tx3, fontWeight:400}}> · ends {endInv!=null?Math.round(endInv).toLocaleString('en-IN'):'—'} u</span>
          </span>;
        })()}
      </div>
      <Reading formula={`line-registry ceiling = Σ line cap = ${lineCap.toLocaleString('en-IN')} u/mo  ⇒  max workforce = ${lineCap.toLocaleString('en-IN')} ÷ ${rate} = ${wfCeiling} heads`}
        soWhat={`The plan is bounded to the SAME ${(M.lines||[]).length}-line capacity the production schedule respects (${(M.lines||[]).map(l=>l.cap.toLocaleString('en-IN')).join(' + ')} u/mo) — it can never promise more than the floor can physically build. Override the rate to re-scale the ceiling.`}/>
      {_net.phys>0 && <div style={{marginTop:10, padding:'9px 11px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${hasOpenOverride?C.a4:C.gn}`, background:C.bg3, fontFamily:F.mono, fontSize:10, lineHeight:1.55, color:C.tx2}}>
        {hasOpenOverride
          ? <>✎ <b style={{color:C.tx}}>Opening stock is pinned (override).</b> You set <b>{effOpen.toLocaleString('en-IN')} u</b> by hand; the auto-reconcile from Network — <b>{_net.phys.toLocaleString('en-IN')} u</b> physical → <b>{_net.weighted.toLocaleString('en-IN')} u</b> labor-weighted — is <b>ignored</b> until you clear the field. </>
          : <>✓ <b style={{color:C.tx}}>Opening stock auto-reconciled from Network.</b> You hold <b>{_net.phys.toLocaleString('en-IN')} u</b> of finished goods across DCs; the plan opens with that same stock, expressed as <b>{_net.weighted.toLocaleString('en-IN')} labor-weighted u</b> for the workforce math — <span style={{color:C.tx3}}>your labor-light mix just carries fewer worker-hours, so it's a yardstick conversion, NOT a reduction.</span> Either way it won't tell you to re-build stock you already hold. </>}
        {onNav && <button onClick={()=>onNav('network')} style={{marginLeft:4, fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>{hasOpenOverride?'open Network on-hand →':'adjust at source in Network →'}</button>}
      </div>}
    </Card>
  );
}

// Per-SKU labor content — the input that makes the people-bound aggregate weighting honest.
// The aggregate constraint is production ≤ rate × WORKERS, so a SKU's family weight must be
// WORKER-time, not machine cycle time. Hands-on % = the share of the machine cycle a worker
// is actually occupied (1.0 = fully manual default; low = automated cell). worker-min = cycle ×
// hands-on; weights are demand-mean-normalised so the average SKU stays 1.00× (rate/worker
// calibration untouched) and only the labor MIX shifts.
function PlanLaborContent(){
  const { config, setConfig } = useConfig();
  const fg = M.products.filter(p=>p.cat==='Finished');
  const w = (typeof aggLaborWeights==='function') ? aggLaborWeights(fg) : {};
  const frac = (sku)=>{ const m=config.skuLaborFrac||{}; const v=m[sku]; return (v==null||v==='')?1.0:Number(v); };
  const setFrac = (sku,v)=> setConfig({ skuLaborFrac:{ ...(config.skuLaborFrac||{}), [sku]:v } });
  return (
    <Card icon="🧑‍🏭" title="Per-SKU labor content" badge="workforce-bound weighting" badgeTone="y"
      info={{ what:'The aggregate plan is workforce-bound (production ≤ rate × workers), so it weights each SKU by WORKER-time, not machine cycle. Hands-on % = the share of the machine cycle a worker is actually occupied (100% = fully manual; lower = more automated). Worker-min/unit = cycle × hands-on %.', flows:'→ aggLaborWeights → /api/solve/aggregate labor_hours_per_unit.' }}
      dev={{ comp:'PlanLaborContent', props:'config.skuLaborFrac', state:'config.skuLaborFrac{sku→0..1}' }}>
      <DataTable cols={['SKU','Machine cycle','Hands-on %','Worker-min / unit','Family weight']} align={['left','right','right','right','right']}
        rows={fg.map(p=>({cells:[
          p.name||p.sku,
          `${(Number(p.cycle)||0).toFixed(1)} min`,
          <NumInput value={Math.round(frac(p.sku)*100)} suffix="%" w={84}
            onChange={v=> setFrac(p.sku, v===''?1 : Math.max(0, Math.min(1, Number(v)/100)))}/>,
          `${((Number(p.cycle)||0)*frac(p.sku)).toFixed(1)} min`,
          <span style={{fontWeight:700, color:(w[p.sku]||1)>1.001?C.ac:((w[p.sku]||1)<0.999?C.tx3:C.tx2)}}>{(w[p.sku]||1).toFixed(2)}×</span>,
        ]}))}/>
      <Reading formula="worker-min/unit = machine cycle × hands-on %   ·   family weight = worker-min ÷ demand-weighted-average (so the average SKU = 1.00×)"
        soWhat="Set the automated SKUs to a low hands-on % — they then weigh LESS than their long machine cycle implies, because a worker only loads/unloads them. The weights are normalised so the average stays 1.00× (your rate/worker number is untouched); only the labor MIX shifts. Leave everything at 100% to treat every station as fully manual. Worked example: a 6.0-min cycle at 30% hands-on = 1.8 worker-min/unit, while a fully-manual 3.0-min cycle = 3.0 worker-min/unit — so the 'slower' automated part actually consumes LESS of your crew than the faster manual one. That reversal is the whole point: a people-bound plan must weight by hands-on time, not machine time."/>
    </Card>
  );
}

function CapacityChart({ data }) {
  const A=(data&&data.length)?data:M.aggregate.months, W=720, H=200, pad=30;
  const mx=Math.max(...A.map(m=>Math.max(m.dem,m.cap,m.prod)))*1.1;
  const bw=(W-pad-8)/A.length;
  const y=v=>H-22-(v/mx)*(H-40);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', height:H, display:'block'}}>
      {[0,1,2,3].map(i=>(<line key={i} x1={pad} x2={W-8} y1={18+i*((H-40)/3)} y2={18+i*((H-40)/3)} stroke={C.line2} strokeWidth=".8"/>))}
      {/* capacity line */}
      <polyline points={A.map((m,i)=>`${pad+bw*i+bw/2},${y(m.cap)}`).join(' ')} fill="none" stroke={C.dg} strokeWidth="2" strokeDasharray="5 3"/>
      {A.map((m,i)=>{
        const x=pad+bw*i, cx=x+bw/2;
        return (<g key={i}>
          <rect x={x+bw*0.18} y={y(m.dem)} width={bw*0.3} height={H-22-y(m.dem)} fill={C.ink}/>
          <rect x={x+bw*0.5} y={y(m.prod)} width={bw*0.3} height={H-22-y(m.prod)} fill={C.ac}/>
          <text x={cx} y={H-7} fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{m.m}</text>
        </g>);
      })}
      <text x={pad+2} y="14" fontFamily={F.mono} fontSize="9" fill={C.tx3}>■ demand  ■ production  --- capacity</text>
    </svg>
  );
}

function PlanStrategy({ agg }) {
  const a=M.aggregate;
  const res = agg && agg.result;
  const months = aggMonths(res);
  const strat = res ? (res.strategy||'').toUpperCase() : a.strategy;
  return (
    <Grid cols={3}>
      <Card icon="⚖" title="Level vs Chase" badge={strat} badgeTone="y" info={{ what:'Classifies the optimal aggregate strategy: level production vs chase demand.', flows:'Strategy → workforce & inventory plan.' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'AggregateTab', props:'state.aggregatePlan', state:'aggregatePlan.strategy' }}>
        <div style={{display:'flex', gap:14, alignItems:'center'}}>
          <div style={{flex:1}}>
            <div style={{fontFamily:F.disp, fontSize:34, fontWeight:900, color:C.ac, letterSpacing:-1, WebkitTextStroke:`1px ${C.line}`}}>{strat}</div>
            <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx2, marginTop:4, lineHeight:1.5}}>{res ? res.strategy_note : 'Steady output with inventory buffering beats chasing demand — lower hire/fire churn, OEE held high.'}</div>
          </div>
          <div style={{width:200}}>
            {(res
              ? [['Workforce CV',res.workforce_cv,C.ink],['Inventory CV',res.inventory_cv,C.gn]]
              : [['Level fit',a.levelScore,C.gn],['Chase fit',a.chaseScore,C.tx3]]
            ).map(([k,v,c],i)=>(
              <div key={i} style={{marginBottom:8}}>
                <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:3}}><span>{k}</span><span className="num" style={{fontWeight:700}}>{res?(v*100).toFixed(1)+'%':(v*100).toFixed(0)+'%'}</span></div>
                {/* PL-G3 — honest scale: full bar = CV 0.10, so the 0.05 level/chase pivot sits at mid-bar (was a magic ×4). */}
                <MiniBar v={res?Math.min(1, v/0.10):v} max={1} color={c} h={14}/>
              </div>
            ))}
            {res
              ? <div style={{fontFamily:F.mono, fontSize:8, color:C.tx3, lineHeight:1.4}}>bar: full = CV 0.10 · pivot at 0.05 · rule: workforce-CV &lt; 0.05 ⇒ hold the crew (LEVEL); ≥ 0.05 ⇒ flex it (CHASE)</div>
              : <div style={{fontFamily:F.mono, fontSize:8, color:C.tx3, lineHeight:1.4}}>seed fit scores — solve for the live workforce / inventory CV</div>}
          </div>
        </div>
        <div style={{marginTop:12}}><CapacityChart data={months}/></div>
        {res && (()=>{
          // PL-G4 — "did I need S&OP?" — bound to the live CV branch (mirrors aggregate.py:245-256).
          const wfcv=res.workforce_cv||0, icv=res.inventory_cv||0;
          const flat     = wfcv<0.05 && icv<0.05;
          const seasonal = !flat && icv>=0.05 && icv>=wfcv;
          const chase    = !flat && wfcv>=0.05 && wfcv>icv;
          const tone = flat?C.tx3:(seasonal?C.gn:C.ac);
          const msg = flat
            ? `Your demand is essentially flat — both swings are under 5%. Level-vs-chase is moot this cycle: a steady crew covers it, so S&OP added little decision value here. The plan is near-trivial — spend your attention on the mix (Profit-mix) and buffers instead.`
            : seasonal
            ? `This is where S&OP pays. Demand swings far more (inventory CV ${(icv*100).toFixed(0)}%) than your crew (${(wfcv*100).toFixed(0)}%) — the plan is deliberately building ahead rather than hiring/firing. Check the prebuild detector and the peak inventory you'll carry.`
            : chase
            ? `S&OP is doing real work: your crew is flexing (workforce CV ${(wfcv*100).toFixed(0)}%) to chase demand rather than carrying inventory. Watch the hire/fire churn and its cost in the Workforce plan.`
            : `Mixed plan — partial crew flex plus partial build-ahead. S&OP is choosing a blend; the duals in step 2 show which lever is binding.`;
          return <div style={{marginTop:12, padding:'10px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${tone}`, background:C.bg3, fontFamily:F.body, fontSize:11.5, lineHeight:1.5, color:C.tx2}}>
            <b style={{fontFamily:F.mono, fontSize:9.5, letterSpacing:'.08em', color:tone}}>DID I NEED S&OP? </b>{msg}
          </div>;
        })()}
        <Reading formula="CV (coefficient of variation) = σ ÷ μ — how much a series swings relative to its own average"
          soWhat="Workforce CV = how much the crew size swings month to month; Inventory CV = how much stock swings. Low crew-swing + high stock-swing ⇒ LEVEL (hold the crew, let inventory flex the seasonality). High crew-swing ⇒ CHASE (flex the crew, carry little stock). The 0.05 line is the level/chase pivot the solver uses."/>
      </Card>
      <Card icon="📦" title="Seasonal Prebuild Detector" badge={(res?res.seasonal_prebuild:a.prebuild.detected)?'DETECTED':'none'} badgeTone="k" info={{ what:'Flags months where demand exceeds capacity → prebuild earlier.', flows:'Prebuild qty → inventory plan.' }}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'PrebuildCard', props:'state.aggregatePlan.prebuild' }}>
        {res ? (<>
          <Blk label="Build-ahead" value={res.seasonal_prebuild?'detected':'not needed'} tone="y"/>
          <div style={{marginTop:8}}><Blk label="Peak Inventory" value={`${res.peak_inventory} u`}/></div>
          <div style={{marginTop:8}}><Blk label="Total Backorder" value={`${res.total_backorder} u`}/></div>
          <div style={{marginTop:10, padding:'9px 10px', border:`2px solid ${C.line}`, background:C.bg3, fontFamily:F.mono, fontSize:10, lineHeight:1.5}}>
            ◆ {res.seasonal_prebuild?`Inventory peaks (${res.peak_inventory}u) BEFORE the demand peak — the plan builds ahead.`:'No build-ahead: capacity tracks demand within the horizon.'}
          </div>
        </>) : (<>
          <Blk label="Prebuild Month" value={a.prebuild.month} tone="y"/>
          <div style={{marginTop:8}}><Blk label="Prebuild Qty" value={`${a.prebuild.units} u`}/></div>
          <div style={{marginTop:10, padding:'9px 10px', border:`2px solid ${C.line}`, background:C.bg3, fontFamily:F.mono, fontSize:10, lineHeight:1.5}}>
            ◆ {a.prebuild.reason}. Build {a.prebuild.units}u in {a.prebuild.month}, hold to Jun.
          </div>
        </>)}
      </Card>
    </Grid>
  );
}

// W4 · PL-1/PL-2 — per-line load from the disaggregated SKU plan vs the line
// REGISTRY capacity. This is the line/machine pressure signal Capital should
// consume (NOT the labor dual) — the binding line is where machine CapEx pays
// back. Honest: at low demand every line shows slack (no CapEx case).
function linePressure(res){
  if(!res || !res.sku_plans || !res.sku_plans.length) return null;
  const T = (res.periods && res.periods.length) || 1;
  const byLine = {};
  res.sku_plans.forEach(sp=>{
    const prod = M.products.find(p=>p.sku===sp.name);
    const lid = (prod && prod.line) || '—';
    byLine[lid] = (byLine[lid]||0) + (sp.total_planned||0);
  });
  return (M.lines||[]).map(l=>{
    const load = byLine[l.id] || 0;             // units planned over the horizon
    const cap  = (Number(l.cap)||0) * T;        // line capacity over the same horizon
    const util = cap ? load/cap : 0;
    return { line:l.name, id:l.id, loadPerMo:Math.round(load/T), cap:l.cap,
             util, shortfall:Math.max(0, Math.round((load-cap)/T)), binding: util>=0.95 };
  });
}

// PL-A — payload for the line-capacity shadow-price LP. Each disaggregated SKU carries its
// MONTHLY planned demand (total_planned ÷ horizon), its assigned line, and its contribution
// margin (price − cost) as the lost-margin if that line can't build it. The LP's capacity
// dual is then the true ₹/unit value of one more unit of that line's capacity.
function linecapPayload(res){
  const T = (res && res.periods && res.periods.length) || 1;
  const lines = (M.lines || []).map(l=>({ id:l.id, name:l.name, cap:Number(l.cap)||0 }));
  const skus = ((res && res.sku_plans) || []).map(sp=>{
    const prod = M.products.find(p=>p.sku===sp.name) || {};
    return { name:sp.name, line:prod.line, demand:Math.round((sp.total_planned||0)/T),
             lost_margin_per_unit:Math.max(0, (prod.price||0)-(prod.cost||0)) };
  });
  return { lines, skus, params:{} };
}

function PlanCapacity({ onNav, agg, lineCap }) {
  const res = agg && agg.result;
  const months = aggMonths(res);
  const shadow = res && res.shadow_prices;
  const press = linePressure(res);
  // PL-A — the true ₹ line shadow price (dual of the line-capacity constraint). Manual run
  // (needs the solved sku_plans first). When solved, it replaces utilization-only "binding"
  // with an economically-grounded one: a line binds iff its capacity dual > 0.
  const lc = useSolve('/api/solve/linecap', ()=>linecapPayload(res), { solveKey:'linecap' });   // LP-C hydrate from loop cache
  const lcByLine = {};
  if(lc.result && lc.result.lines) lc.result.lines.forEach(l=>{ lcByLine[l.line_id] = l; });
  const lcSolved = !!(lc.result && lc.result.lines);
  const bind = lcSolved
    ? press && press.find(p=>(lcByLine[p.id]||{}).binding)
    : press && press.find(p=>p.binding);
  const runLc = ()=> lc.run().catch(()=>{});
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Capacity vs Demand" badge={`${(months||M.aggregate.months).length} periods · ceiling ${lineCap?lineCap.toLocaleString('en-IN'):'—'} u/mo`} info={{ what:'Monthly demand against the planned regular-labor capacity (rate × workforce), bounded by the line-registry ceiling.', flows:'Shortfalls → prebuild & overtime.' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'CapacityPlanCard', props:'aggregate.periods, lineCap' }}>
        <CapacityChart data={months}/>
        <DataTable dense cols={['Period','Demand','Labor cap','Production','Net Inv']} align={['left','right','right','right','right']}
          rows={(months||M.aggregate.months).map(m=>({cells:[m.m, m.dem, m.cap, m.prod, <span style={{color:m.inv<0?C.dg:C.tx, fontWeight:700}}>{m.inv>0?'+':''}{m.inv}</span>]}))}/>
        <Reading formula={`line-registry ceiling = Σ line cap = ${lineCap?lineCap.toLocaleString('en-IN'):'—'} u/mo  ·  "Labor cap" column = rate × workforce that period`}
          soWhat="The capacity the plan deploys each period is the LABOR capacity (rate × heads); it can rise only to the line-registry ceiling above. Demand under the ceiling means the lines are not the constraint — labor is. The family demand is weighted by each SKU's WORKER-time (machine cycle × the hands-on % you set in step 0b, mean-normalised so the rate/worker calibration is preserved) — a labor-heavy SKU consumes more of this capacity, an automated one less, and the family plan is split back to physical SKU units in step 4. Units: every column here (Demand · Labor cap · Production · Net Inv) is in aggregate (labor-weighted) units — ≈ physical because the weights mean-normalise to 1.0, but the physical SKU split in step 4 will not foot exactly to the aggregate Production total unless every SKU is at 100% hands-on."/>
      </Card>
      <Card icon="🔑" title="Labor Capacity Shadow Prices" badge={shadow?`${shadow.length} duals · live`:'duals'} badgeTone="y" info={{ what:'Marginal value of one more WORKER-PERIOD of regular capacity (the aggregate LP dual). This is a labor dual — not a line/machine dual.', flows:'Labor duals → hire/OT decision, NOT line CapEx.' }} span={2}
        right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'ShadowPriceCard', props:'aggregate.shadow_prices', note:'Worker-period duals (P_t ≤ rate·W_t).' }}>
        {shadow ? (
          shadow.length ? <DataTable cols={['Constraint','Dual (₹/worker-unit)','Slack','Status']} align={['left','right','right','left']}
            rows={shadow.map(s=>({__hl:s.binding, cells:[s.constraint, s.shadow_price?`₹${Number(s.shadow_price).toFixed(2)}`:'—', s.slack==null?'—':s.slack, <Tag c={s.binding?'k':'w'}>{s.binding?'BINDING':'slack'}</Tag>]}))}/>
          : <div style={{padding:'12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>No binding labor-capacity rows — the plan has workforce slack everywhere (no resource is worth expanding at these costs).</div>
        ) : (
          <div style={{padding:'12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Solve the aggregate plan to see the live labor duals.</div>
        )}
        <Reading formula="labor dual λ = ∂(objective) / ∂(worker-period capacity)  — ₹ saved per extra worker-unit"
          soWhat="A binding labor dual means the answer is hire/overtime, not machines. Line/machine CapEx is justified by the line-pressure table below — a different constraint."/>
      </Card>
      <Card icon="🏭" title="Line Capacity Pressure" badge={press?(bind?`${bind.line} binding`:(lcSolved?'all slack · ₹0':'all slack')):'solve first'} badgeTone="k" span={2}
        info={{ what:'The disaggregated SKU plan loaded onto each line vs its registry capacity, plus the TRUE ₹ shadow price of each line\'s capacity (PL-A, dual of a min-cost assignment LP). The binding line is where machine CapEx pays back — the line/machine signal Capital consumes (not the labor dual).', flows:'Binding line + ₹ shadow price → Capital / Investment Decision.' }}
        right={<div style={{marginLeft:'auto', display:'flex', alignItems:'center', gap:10}}>
          {res ? (lcSolved ? <Provenance kind="solved" asOf={lc.ranAt?lc.ranAt.toLocaleTimeString():undefined}/>
            : <Btn kind="primary" sm onClick={runLc}>{lc.solving?'⏳ Pricing…':'₹ Price capacity'}</Btn>) : null}
          {res && bind ? <button onClick={()=>onNav&&onNav('finance')} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>invest in {bind.line} →</button> : null}
        </div>}
        dev={{ comp:'LinePressureTable', props:'aggregate.sku_plans grouped by line vs M.lines.cap + /api/solve/linecap dual' }}>
        {lc.error && <div style={{marginBottom:8, fontFamily:F.mono, fontSize:9.5, color:C.dg}}>Line-capacity LP: {lc.error}</div>}
        {press ? (
          <DataTable cols={['Line','Planned u/mo','Registry cap','Util','Shortfall u/mo','₹ shadow / cap unit','Status']} align={['left','right','right','right','right','right','left']}
            rows={press.map(p=>{ const l = lcByLine[p.id]; const binds = lcSolved ? (l&&l.binding) : p.binding;
              return {__hl:binds, cells:[p.line, p.loadPerMo.toLocaleString('en-IN'), p.cap.toLocaleString('en-IN'),
              <span style={{fontWeight:700, color:p.util>0.95?C.dg:C.tx}}>{(p.util*100).toFixed(0)}%</span>,
              p.shortfall?`+${p.shortfall.toLocaleString('en-IN')}`:'—',
              lcSolved ? <span style={{fontWeight:700, color:(l&&l.shadow_price)?C.dg:C.tx3}}>{l&&l.shadow_price?`₹${l.shadow_price.toLocaleString('en-IN')}`:'₹0'}</span> : <span style={{color:C.tx3}}>—</span>,
              <Tag c={binds?'k':'w'}>{binds?'BINDING':'slack'}</Tag>]};})}/>
        ) : (
          <div style={{padding:'12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, border:`2px dashed ${C.line2}`}}>Solve the aggregate plan — the SKU disaggregation loads each line against its registry capacity here.</div>
        )}
        <Reading formula={lcSolved?"₹ shadow = dual of (Σ SKU load on line ≤ line cap) in a min-cost assignment LP — ₹ of contribution margin one more unit of capacity unlocks":"line util = Σ(planned SKU qty on the line) ÷ (line registry cap × horizon)"}
          soWhat={press?(bind?`${bind.line} binds at a ₹${(lcByLine[bind.id]||{}).shadow_price||'—'}/unit shadow price — every extra unit of its capacity recovers that much lost margin. THAT is the CapEx case Finance capitalizes (F-8 consumes this as the capacity shadow price).`:(lcSolved?'Priced: every line\'s capacity dual is ₹0 — they all have slack, so no machine CapEx is justified at this demand. The constraint is labor (see the duals above), not the lines. The mechanism is live: when demand pressures a line its dual turns positive here.':'Every line has slack at this demand — press "₹ Price capacity" to confirm the line duals are ₹0 (no CapEx case) vs the labor dual above.')):'—'}/>
      </Card>
      {lcSolved && typeof explainLinecap==='function' && typeof GlassBoxExplainer==='function' &&
        <GlassBoxExplainer icon="🏭" title="What the line duals mean — plain-English" rows={explainLinecap(lc.result)} prov="linecap dual LP"
          note="Each line's bottleneck/spare verdict is its own capacity shadow price (₹/unit) — translated, not re-decided. A binding line is a machine-CapEx case; a slack line (₹0) is not."/>}
    </Grid>
  );
}

function PlanWorkforce({ agg, rate, initWf }) {
  const res = agg && agg.result;
  const r = Number(rate) || PLAN_PARAMS.rate_per_worker || 1;
  const wf0 = (initWf!=null && initWf!=='') ? Number(initWf) : PLAN_PARAMS.init_workforce;
  // PL-5 — tie each period's hire/OT back to the capacity GAP it fills:
  // gap = demand − regular capacity at the START-of-period headcount (rate × prior heads).
  // A positive gap is exactly what the hire + overtime in that row exist to cover.
  const wf = res && res.periods
    ? res.periods.map((p,i,arr)=>{
        const priorHeads = i===0 ? wf0 : Math.round(arr[i-1].workforce);
        const gap = Math.max(0, Math.round((p.demand||0) - r*priorHeads));
        return { period:'P'+p.period, base:Math.round(p.workforce), hire:Math.round(p.hires), fire:Math.round(p.fires),
                 ot:Math.round(p.overtime_production), otCost:(p.overtime_cost!=null?p.overtime_cost:null), gap };
      })
    : M.aggregate.workforce.map(w=>({ ...w, otCost:null, gap:null }));
  const otLabel = res ? 'Overtime (u)' : 'Overtime (hrs)';
  const otCostTotal = wf.reduce((s,w)=>s+(w.otCost||0),0);   // G-P1 — itemised OT rupee cost
  const wfMax = Math.max(...wf.map(w=>w.base), 1);
  return (
    <Card icon="👷" title="Workforce Plan · Hire / Fire / OT" badge={res?`${wf.length} periods · live`:'4 quarters'} info={{ what:'Period workforce decisions: base heads, hire, fire, overtime — and the demand-vs-capacity gap each fills.', flows:'Labour capacity → production MILP.' }}
      right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : undefined}
      dev={{ comp:'WorkforceCard', props:'aggregate.periods (workforce, hires, fires, OT, demand)' }}>
      <DataTable cols={['Period','Base Heads','Hire','Fire',otLabel,'OT ₹','Fills gap (u)']} align={['left','right','right','right','right','right','right']}
        rows={wf.map(w=>({cells:[w.period, w.base, <span style={{color:w.hire?C.gn:C.tx3, fontWeight:700}}>{w.hire?`+${w.hire}`:'—'}</span>, <span style={{color:w.fire?C.dg:C.tx3, fontWeight:700}}>{w.fire?`-${w.fire}`:'—'}</span>, w.ot, w.otCost==null?'—':<span style={{color:w.otCost>0?C.dg:C.tx3, fontWeight:w.otCost>0?700:400}}>{w.otCost>0?`₹${Math.round(w.otCost).toLocaleString('en-IN')}`:'—'}</span>, w.gap==null?'—':<span style={{color:w.gap>0?C.dg:C.tx3, fontWeight:700}}>{w.gap>0?`+${w.gap}`:'0'}</span>]}))}
        foot={res?['TOTAL','','','','',`₹${Math.round(otCostTotal).toLocaleString('en-IN')}`,'']:undefined}/>
      {res && <Reading formula="OT ₹ per period = ot_cost_per_unit · overtime_units   ·   gap = demand − rate × (start-of-period heads), filled by hire + overtime"
        soWhat={`A positive gap is the capacity hole the period's hire + overtime exist to close. The plan spends ₹${Math.round(otCostTotal).toLocaleString('en-IN')} on overtime across the horizon — itemised per period so the OT premium is visible, not buried in the objective. When the gap is 0 the base workforce already covers demand and any OT is buffering.`}/>}
      <div style={{marginTop:12}}>
        <SubLabel>Headcount trajectory</SubLabel>
        <div style={{display:'flex', alignItems:'flex-end', gap:10, height:80}}>
          {wf.map((w,i)=>(
            <div key={i} style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:4}}>
              <div style={{width:'70%', height:`${w.base/(res?wfMax:52)*100}%`, background:C.ink, border:`2px solid ${C.line}`}}/>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx2}}>{w.period}·{w.base}</span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function PlanDisagg({ agg }) {
  const res = agg && agg.result;
  const palette=[C.ink,C.ac,C.a2,C.gn,C.a4,C.a3,C.dg];
  // when solved, DERIVE the split from the solver's per-SKU disaggregation (sku_plans);
  // mix % = each SKU's planned share of the total planned family quantity.
  let split, familyQty;
  if(res && res.sku_plans && res.sku_plans.length){
    familyQty = res.sku_plans.reduce((s,p)=>s+(p.total_planned||0),0) || 1;
    split = res.sku_plans.map(p=>[p.name, +(100*(p.total_planned||0)/familyQty).toFixed(1), p.total_planned]);
  } else {
    familyQty = 13400;
    split = [['TPA-4471',32],['TPA-3215',46],['TPA-9904',12],['TPA-2188',6],['TPA-5540',4]].map(([s,w])=>[s,w,Math.round(13400*w/100)]);
  }
  // PL-4 — name the family + horizon explicitly so the split is not a mystery slice.
  const nFG = M.products.filter(p=>p.cat==='Finished').length;
  const horizon = (M.aggregate.months||[]).length;
  return (
    <Card icon="🔀" title="SKU Disaggregation" badge={res?'aggregate → SKU · solved':'aggregate → SKU · seed'} info={{ what:`Splits the solved aggregate family plan (${nFG} finished SKUs, ${horizon}-month horizon) back to individual SKUs by each SKU's planned share. Seed shares shown until solved.`, flows:'SKU-level plan → MPS & procurement.' }}
      right={res ? <Provenance kind="solved" asOf={agg.ranAt?agg.ranAt.toLocaleTimeString():undefined}/> : <Provenance kind="seed"/>}
      dev={{ comp:'DisaggregateCard', props:'aggregate.sku_plans (total_planned share)', note:'derived from the solved aggregate plan; seed split until solved.' }}>
      <div style={{marginBottom:10, fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>FAMILY: all finished goods ({nFG} SKUs) · HORIZON: {horizon} months · BASIS: {res?'solved per-SKU planned quantity':'annual-demand seed share (not yet solved)'}</div>
      <div style={{display:'flex', height:30, border:`2px solid ${C.line}`, marginBottom:14}}>
        {split.map(([s,w],i)=>(
          <div key={i} style={{width:`${w}%`, background:palette[i%palette.length], color: i===1?C.onAc:'#fff', display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, fontWeight:700, borderRight:i<split.length-1?`1px solid ${C.paper}`:'none'}}>{w}%</div>
        ))}
      </div>
      <DataTable cols={['SKU','Mix %','Family Qty','SKU Qty','Line']} align={['left','right','right','right','left']}
        rows={split.map(([s,w,q])=>[s, `${w}%`, Math.round(familyQty).toLocaleString('en-IN'), Math.round(q).toLocaleString('en-IN'), M.products.find(p=>p.sku===s)?.line||'—'])}/>
    </Card>
  );
}
// S&OP Gap — relocated from Scenarios·Performance (app_v2). This is the
// reconciliation OUTCOME of the S&OP stage, so it belongs at the end of Plan.
function PlanGap({ onNav }) {
  // PL-G1 — M.sop is a hardcoded SEED (data.jsx). It was rendered under a "derived" chip with a
  // fabricated as-of timestamp (a live R2). Fenced as illustrative until the consensus reconcile is wired.
  return (
    <Card icon="📋" title="S&OP Gap · Plan vs Target" badge="illustrative" badgeTone="y"
      info={{ what:'Where the committed consensus plan WOULD stand against the business target — volume, revenue, margin, inventory. The live consensus reconcile is not yet wired into this card; the figures below are illustrative seeds for layout.', flows:'Gaps → next S&OP cycle re-plan & Profit-mix.' }}
      right={<Provenance kind="seed"/>}
      dev={{ comp:'SOPGapCard', props:'M.sop (seed) — pending a wired consensus reconcile', note:'Relocated from Scenarios·Performance (app_v2). M.sop is seed, not a solve.' }}>
      <SeedFence what="These gap figures are illustrative seeds for layout — NOT the output of a consensus reconcile. The S&OP reconcile (committed plan vs business target) runs in the Scenarios cockpit; run it to replace these with your numbers." onNav={onNav} go="scenarios" goLabel="reconcile in Scenarios →"/>
      <KpiRow cols={4}>
        <Blk label="Volume" value={`+${M.sop.volumeGap}%`} accent={C.gn}/>
        <Blk label="Revenue" value={`${M.sop.revGap}%`} accent={C.dg}/>
        <Blk label="Margin" value={`+${M.sop.marginGap}%`} accent={C.gn}/>
        <Blk label="Inventory" value={`${M.sop.inventoryGap}%`} accent={C.dg}/>
      </KpiRow>
      <Reading formula="gap = committed plan − target, per dimension"
        soWhat="When wired, a positive volume gap with a negative revenue gap means the plan wins units on lower-margin SKUs — tighten the mix in Profit-mix before committing. (The figures above are illustrative seeds until the reconcile runs.)"/>
    </Card>
  );
}
window.StagePlan = StagePlan;
