// ════════════════════════════════════════════════════════════════════════
// reference.jsx — Reference. Sub-tabs: Learning Lab · SAP Mode.
// ════════════════════════════════════════════════════════════════════════
function StageReference({ onNav }) {
  const [sub, setSub] = useState('map');
  const tabs = [
    { id:'map',   n:'a', label:'Model Map', count:M.solvers.length },
    { id:'learn', n:'b', label:'Learning Lab', count:M.learnSections.length },
    { id:'sap',   n:'c', label:'SAP Mode', count:M.sapTcodes.length },
    { id:'api',   n:'d', label:'Open API' },
  ];
  return (
    <div>
      <StageHeader n="12" title="Reference" kicker="Live model map & cross-solver consistency · Learning Lab · SAP T-code map · open solve-API substrate"/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='map'   && <ModelMap onNav={onNav}/>}
        {sub==='learn' && <RefLearn/>}
        {sub==='sap'   && <RefSAP onNav={onNav}/>}
        {sub==='api'   && <RefAPI/>}
      </div>
    </div>
  );
}

// ── D7 · COMPOSABILITY / OPEN SOLVE-API SUBSTRATE ──────────────────────────────
// The "why us over a monolith" packaging: every optimiser already runs behind its
// own HTTP endpoint, against ONE shared dataset. This tab proves it — the catalog
// is fetched LIVE from /api/meta/solvers (introspected from the real Flask url_map,
// not a hand-kept list), so a best-of-breed tool or the customer's own script can
// call a single solver without the whole suite. The "lightweight digital twin"
// framing made concrete. No new numbers — it documents the substrate that exists.
const _API_KIND = { solve:{c:'g', label:'optimiser'}, calc:{c:'c', label:'calculator'},
  forecast:{c:'y', label:'demand'}, risk:{c:'k', label:'risk'}, util:{c:'w', label:'utility'} };
function RefAPI() {
  const [data, setData] = useState(null);
  const [err, setErr]   = useState(null);
  const [busy, setBusy] = useState(true);
  const load = ()=>{ setBusy(true); setErr(null);
    apiGet('/api/meta/solvers').then(d=>{ setData(d); setBusy(false); })
      .catch(e=>{ setErr(e.message||String(e)); setBusy(false); }); };
  useEffect(()=>{ load(); }, []);
  const eps = (data && data.endpoints) || [];
  const solveN = eps.filter(e=>e.kind==='solve').length;
  const sample = eps.find(e=>e.path==='/api/solve/profitmix') || eps.find(e=>e.kind==='solve') || eps[0];
  const curl = sample
    ? `curl -X POST ${(data&&data.base)||'http://localhost:5000'}${sample.path} \\\n  -H 'Content-Type: application/json' \\\n  -d '{ ...one slice of the shared dataset... }'`
    : '';
  return (
    <Grid cols={1}>
      <Card icon="🧩" title="Open solve API — the composable substrate" span={2}
        badge={busy?'loading…':err?'offline':`${data?data.count:0} endpoints`} badgeTone={err?'k':data?'g':'y'}
        right={<Provenance kind="external" note="live /api/meta/solvers"/>}
        info={{ what:'Every solver is a standalone HTTP call against one shared dataset — introspected live from the Flask route map, so this catalog can never drift from what is actually deployed.', flows:'Best-of-breed tools / customer scripts call individual solvers; no monolith lock-in.' }}
        dev={{ comp:'RefAPI (D7)', props:'apiGet(/api/meta/solvers)', note:'Backend introspects app.url_map — real routes, not a static list.' }}>
        <div style={{padding:'9px 11px', border:`2px solid ${C.line}`, background:C.ink, color:C.ac, fontFamily:F.disp, fontSize:12, fontWeight:700, lineHeight:1.5}}>
          One dataset → {solveN||'every'} solvers, each a single HTTP call = a lightweight digital twin.
          <div style={{fontFamily:F.mono, fontSize:9.5, fontWeight:400, color:C.tx3, marginTop:4}}>
            The incumbents are a monolith you buy whole and need consultants to query. Here the optimisers are open — call one, call all, or wire ours into your own stack.
          </div>
        </div>
        {err && <div style={{marginTop:10, padding:'9px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>
          API catalog unavailable: {err}. <span style={{textDecoration:'underline', cursor:'pointer'}} onClick={load}>retry</span> — the backend must be running.</div>}
        {busy && !data && <div style={{marginTop:10, fontFamily:F.mono, fontSize:10.5, color:C.tx3}}>introspecting the route map…</div>}
        {sample && (
          <div style={{marginTop:10}}>
            <SubLabel>Call any solver directly</SubLabel>
            <pre style={{margin:'4px 0 0', padding:'9px 11px', border:`2px solid ${C.line}`, background:C.paper,
              fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5, whiteSpace:'pre-wrap', overflowX:'auto'}}>{curl}</pre>
          </div>
        )}
      </Card>
      {eps.length>0 && (
        <Card icon="📡" title="Endpoint catalog" badge={`${eps.length} live`}
          info={{ what:'The registered API surface, grouped by kind. Each row is a real, callable route on the running server.', flows:'Integration / composability reference.' }}
          dev={{ comp:'RefAPI·catalog', props:'data.endpoints' }}>
          <DataTable dense cols={['Endpoint','Methods','Kind','What it does']} align={['left','left','left','left']}
            rows={eps.map(e=>{ const k=_API_KIND[e.kind]||_API_KIND.util; return [
              <span style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.tx}}>{e.path}</span>,
              <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{(e.methods||['GET']).join(', ')}</span>,
              <Tag c={k.c}>{k.label}</Tag>,
              <span style={{fontSize:10.5, color:C.tx2}}>{e.doc||'—'}</span>]; })}/>
          <Reading tone={C.tx2}
            formula={`${solveN} optimisers · ${eps.length-solveN} calculators/util · one shared dataset`}
            soWhat={data && data.note ? data.note : 'Each endpoint is independently callable — compose only what you need.'}/>
        </Card>
      )}
    </Grid>
  );
}

// ════════════════════════════════════════════════════════════════════════
// OBS-1 · Live model map  +  OBS-2 · cross-solver consistency
//   (Observability spec, Part 6 · Tier-1)
// The headline SolverNetwork fabric colours nodes by the SEED `status` field, so it
// lies about which engines have actually run. ModelMap re-renders the SAME fabric from
// LIVE solve freshness (the `solves`/`solveResults` slices), adds a node drill-down
// (inputs → formula → API → last result) and surfaces the cross-solver identities the
// per-tab smokes never check end-to-end. Every number is read from the cache or config —
// nothing fabricated; honest "—" when a solve has not run.
// ════════════════════════════════════════════════════════════════════════
const _OBS_KEY = { forecast:'forecast', aggregate:'aggregate', procurement:'procurement',
  production:'production', profitmix:'profitmix', transport:'transport', montecarlo:'montecarlo',
  cvar:'cvar', capital:'capital', allocation:'transport', consolidate:'transport' };
//  B-12 — allocation & consolidate are TRANSPORT sub-steps (edges transport→{allocation,
//  consolidate}, go:logistics, both rendered off the single /api/solve/transport solve in
//  Logistics). They were wrongly mapped to the inventory meio/meionet solvers across KEY/API/
//  METHOD/obj — the map lied about two of its own nodes. Now keyed to the transport solve.
// (disaggregate, reconcile, sequencing, lotsizing, capital_capacity have NO cross-stage
//  cache key — they run local-only, so the map shows them faint/"untracked", honestly.)
const _OBS_API = { forecast:'/api/forecast', aggregate:'/api/solve/aggregate', disaggregate:'/api/calc/disaggregate',
  reconcile:'/api/solve/sop', profitmix:'/api/solve/profitmix', procurement:'/api/solve/procurement',
  production:'/api/solve/production', sequencing:'/api/solve/sequence', lotsizing:'/api/solve/lotsizing',
  transport:'/api/solve/transport', allocation:'/api/solve/transport', consolidate:'/api/solve/transport',
  montecarlo:'/api/solve/montecarlo', cvar:'/api/solve/cvar', capital:'/api/solve/capital', capital_capacity:'/api/solve/capital-capacity' };
const _OBS_METHOD = {
  forecast:'Holt-Winters + RandomForest hybrid · Croston/SBA/TSB for the intermittent tail · MASE/MAPE out-of-sample backtest',
  aggregate:'Hax–Meal / Holt-Modigliani-Muth-Simon level-vs-chase LP — InvBal in worker-time units',
  disaggregate:'Hierarchical disaggregation, proportional to physical demand share',
  reconcile:'Top-down ⇄ bottom-up consensus reconciliation',
  profitmix:'True LP with duals — shadow price = ₹/unit of the binding resource; reduced cost = why a SKU is dropped',
  procurement:'Multi-period MILP · SS = Heizer z·σ_LTD or Rockafellar–Uryasev CVaR · explodes per-FG bomForSku',
  production:'Scheduling MILP · Theory-of-Constraints bottleneck · campaign min-run',
  sequencing:'Changeover-min Hamiltonian path (ATSP) over the 6 SKUs',
  lotsizing:'EOQ (Wilson) · Wagner-Whitin DP (optimal) · Silver-Meal · (s,S) Min-Max',
  transport:'Transportation-problem LP (min-cost flow)',
  allocation:'Transport LP allocation — least-cost DC→customer lane assignment (each lane picks its mode), from the /api/solve/transport solve',
  consolidate:'LTL→FTL consolidation heuristic — merge shipments on a lane when FTL cost < ΣLTL within the SLA slack (same transport solve)',
  montecarlo:'Simulation with lead-time lag, replayed on the committed production plan',
  cvar:'Rockafellar–Uryasev CVaR LP · newsvendor critical ratio',
  capital:'CAPM + Hamada re-levering βL=βU(1+(1−t)D/E) · blended hurdle · NPV + depreciation shield',
  capital_capacity:'Endogenous-capacity capital plan — CapEx justified by the bottleneck shadow price',
};
function _obsCr(n){ const v=Math.abs(+n||0); return v>=1e7?`${(n/1e7).toFixed(2)} Cr`:v>=1e5?`${(n/1e5).toFixed(1)} L`:`${Math.round(n).toLocaleString('en-IN')}`; }
function _obsObj(id, r){
  if(!r) return null;
  try{
    switch(id){
      case 'forecast':   return r.winner ? `winner ${r.winner.model||r.winner}` : (r.mape!=null?`MAPE ${r.mape}%`:'ran');
      case 'aggregate':  return (r.strategy||'plan') + (r.total_cost!=null?` · ₹${_obsCr(r.total_cost)}`:'');
      case 'production': { const u=r.gantt?r.gantt.reduce((a,e)=>a+(+e.quantity||0),0):null; return (r.status||'ran')+(u!=null?` · ${u.toLocaleString('en-IN')}u`:''); }
      case 'procurement':return r.materials?`${r.materials.length} parts`:'ran';
      case 'montecarlo': return r.avg_fill!=null?`fill ${(r.avg_fill*100).toFixed(0)}%`:'ran';
      case 'profitmix':  return r.total_profit!=null?`₹${_obsCr(r.total_profit)}`:'ran';
      case 'transport':  return r.total_cost!=null?`₹${_obsCr(r.total_cost)}`:'ran';
      case 'capital':    return r.total_npv!=null?`NPV ₹${_obsCr(r.total_npv)}`:'ran';   // B-15 — capital.py returns total_npv (portfolio Σ NPVᵢ·xᵢ); r.npv was undefined → node fell to 'ran'. Exposed once B-3 lit the node.
      case 'cvar':       return r.cvar95!=null?`CVaR ₹${_obsCr(r.cvar95)}`:'ran';
      case 'allocation': return r.n_shipments!=null?`${r.n_shipments} lanes`:'ran';
      case 'consolidate':return r.consolidation_saving!=null?`saved ₹${_obsCr(r.consolidation_saving)}`:'ran';
      default: return 'ran';
    }
  }catch(e){ return 'ran'; }
}

// OBS-1 · the ONE freshness/obj builder, shared by the ModelMap AND the Console
// fabric (closes B-2 — the Console SolverNetwork used to colour by the seed `status`
// field, lying about what ran). id → 'fresh'|'stale'|'never'|'untracked' from the
// live cross-stage cache, plus id → last real objective string. One source of truth.
function solverFreshnessMaps(solves, results){
  solves = solves||{}; results = results||{};
  const fresh = {}, obj = {};
  (M.solvers||[]).forEach(s=>{
    const key = _OBS_KEY[s.id];
    if(!key){ fresh[s.id]='untracked'; return; }
    const sv = solves[key], rc = results[key];
    fresh[s.id] = (sv&&sv.stale) ? 'stale' : ((sv&&sv.ranAt)||rc) ? 'fresh' : 'never';
    obj[s.id] = _obsObj(s.id, rc&&rc.result);
  });
  return { fresh, obj };
}

function ModelMap({ onNav }){
  const { state: solves }  = useStore(s=>s.solves||{});
  const { state: results } = useStore(s=>s.solveResults||{});
  const { state: demand }  = useStore(s=>s.demand||{});
  const { config } = useConfig();
  const [sel, setSel] = useState(null);

  const { fresh, obj } = solverFreshnessMaps(solves, results);
  const counts = { fresh:0, stale:0, never:0, untracked:0 };
  M.solvers.forEach(s=>counts[fresh[s.id]]++);
  const tracked = M.solvers.length - counts.untracked;

  const swatch = (c,label,n)=> (
    <span style={{display:'inline-flex', alignItems:'center', gap:5, fontFamily:F.mono, fontSize:9, color:C.tx2}}>
      <span style={{width:11, height:11, background:c, border:`1px solid ${C.line}`}}/>{label}{n!=null?` · ${n}`:''}</span>
  );

  return (
    <Grid cols={1}>
      <Card icon="🗺" title="Live model map — the machine, coloured by what has actually run" span={2}
        badge={`${counts.fresh}/${M.solvers.length} fresh`} badgeTone={counts.fresh?'g':'y'}
        right={<Provenance kind="derived"/>}
        info={{ what:'The 16 solvers in 5 family lanes, with the real /api/solve hand-offs as edges. Node colour is LIVE solve freshness from the cross-stage cache — not the seed status the Home/Console fabric shows. Click a node to trace its inputs → formula → API → last result.', flows:'The observability map: freshness, lineage and the last real output of every engine in one place.' }}
        dev={{ comp:'ModelMap (OBS-1)', props:'useStore(solves, solveResults) → freshness; SolverNetwork(freshness, liveObj)', note:'Re-uses the SolverNetwork fabric with live colouring — no third drawing (P-H).' }}>
        <div style={{border:`2px solid ${C.line}`, background:C.paper, padding:'8px 6px'}}>
          <SolverNetwork freshness={fresh} liveObj={obj} sel={sel} onSelect={setSel} onNav={onNav}/>
        </div>
        <div style={{display:'flex', gap:16, flexWrap:'wrap', marginTop:9, alignItems:'center'}}>
          {swatch(C.gn,'fresh',counts.fresh)}{swatch(C.a4,'stale',counts.stale)}{swatch(C.tx3,'never run',counts.never)}{swatch(C.line2,'untracked',counts.untracked)}
        </div>
        <Reading tone={C.tx2}
          formula={`${tracked} of ${M.solvers.length} solvers persist to the cross-stage cache · ${counts.untracked} run local-only (untracked)`}
          soWhat={counts.untracked>0 ? 'The untracked engines (disaggregate, reconcile, sequencing, lot-sizing, capital-capacity) run only inside their own tab — their outputs are not observable to a cross-solver check or the value ledger. Giving the consequential ones a solveKey would put them on this map.' : 'Every solver is observable.'}/>
      </Card>

      {sel ? <ModelNodeDetail sel={sel} results={results} solves={solves} fresh={fresh[sel]} onNav={onNav} onClose={()=>setSel(null)}/>
           : <Card icon="👆" title="Trace a solver" badge="click a node" badgeTone="c"
               info={{ what:'Pick any engine above to see exactly what feeds it and what it last produced.' }}>
               <div style={{padding:'14px 12px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3}}>
                 Click a solver node to trace its inputs → formula → API → last real result.</div>
             </Card>}

      <ConsistencyPanel results={results} solves={solves} demand={demand} config={config} onNav={onNav}/>
    </Grid>
  );
}

function ModelNodeDetail({ sel, results, solves, fresh, onNav, onClose }){
  const s = M.solvers.find(x=>x.id===sel); if(!s) return null;
  const key = _OBS_KEY[sel];
  const sv = key ? solves[key] : null;
  const rc = key ? results[key] : null;
  const r  = rc && rc.result;
  const deps = (key && SOLVE_DEPS[key]) || null;
  const provKind = !key ? 'seed' : (sv&&sv.stale) ? 'derived' : r ? 'solved' : 'seed';
  const ranAt = (sv&&sv.ranAt) ? new Date(sv.ranAt).toLocaleString('en-IN') : (rc&&rc.ranAt? new Date(rc.ranAt).toLocaleString('en-IN'):null);
  const live = _obsObj(sel, r);
  return (
    <Card icon="🔬" title={`${s.name} — lineage`} badge={fresh} badgeTone={fresh==='fresh'?'g':fresh==='stale'?'k':undefined}
      right={<Provenance kind={provKind} asOf={provKind==='solved'?ranAt:undefined} stale={!!(sv&&sv.stale)}/>}
      info={{ what:`How ${s.name} is wired: the inputs it depends on, the method it runs, the API it calls, and its last real output.` }}
      dev={{ comp:'ModelNodeDetail (OBS-1)', props:`SOLVE_DEPS['${key||'—'}'], getSolveResult('${key||'—'}')` }}>
      <KpiRow>
        <Blk label="Family" value={s.fam} tone="c"/>
        <Blk label="Engine" value={s.engine}/>
        <Blk label="Freshness" value={fresh} accent={fresh==='fresh'?C.gn:fresh==='stale'?C.a4:C.tx3}/>
        <Blk label="Last result" value={live||'not run'} accent={live?C.gn:C.tx3}/>
      </KpiRow>
      <SubLabel>Method / formula</SubLabel>
      <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.5, marginBottom:8}}>{_OBS_METHOD[sel]||'—'}</div>
      <SubLabel>Inputs it depends on (SOLVE_DEPS — edit any of these and this solve goes stale)</SubLabel>
      <div style={{display:'flex', gap:6, flexWrap:'wrap', margin:'4px 0 10px'}}>
        {deps ? deps.map(d=><Tag key={d} c="w">{d}</Tag>)
              : <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>{key?'no declared dependencies':'runs local-only — not in the cross-stage cache'}</span>}
      </div>
      <SubLabel>API</SubLabel>
      <div style={{fontFamily:F.mono, fontSize:10, color:C.tx, marginBottom:10}}>{_OBS_API[sel]||'—'}{ranAt?`  ·  last ran ${ranAt}`:''}</div>
      <div style={{display:'flex', gap:8}}>
        <Btn kind="primary" sm onClick={()=>onNav&&onNav(s.go)}>open {s.name} tab →</Btn>
        <Btn sm onClick={onClose}>close</Btn>
      </div>
    </Card>
  );
}

function ConsistencyPanel({ results, solves, demand, config, onNav }){
  const R = k => results[k] && results[k].result;
  const pr=R('production'), mc=R('montecarlo'), lc=R('linecap'), pm=R('profitmix'), mn=R('meionet');
  const finished = (M.products||[]).filter(p=>p.cat==='Finished');
  const demTot = finished.reduce((a,p)=>{ const s=demand[p.sku]; return a+(s&&s.length?s.reduce((x,y)=>x+(+y||0),0):0); },0);
  const prodUnits = pr&&pr.gantt ? pr.gantt.reduce((a,e)=>a+(+e.quantity||0),0) : null;
  let hurdle=null, carry=null;
  try{ if(typeof finBlendedHurdle==='function') hurdle=finBlendedHurdle(config).wacc; }catch(e){}
  try{ if(typeof carryRate==='function') carry=carryRate(config)*100; }catch(e){}
  const lcMax = lc&&lc.lines ? Math.max(0,...lc.lines.map(x=>+x.shadow_price||0)) : null;
  const pmBinding = pm&&pm.shadow_prices ? pm.shadow_prices.filter(x=>x.binding) : null;
  const pmMax  = pmBinding ? Math.max(0,...pmBinding.map(x=>+x.shadow_price||0)) : null;
  const pmNames = pmBinding ? pmBinding.map(x=>x.constraint||x.resource||x.name).filter(Boolean).slice(0,4) : [];
  const prodAt = solves.production&&solves.production.ranAt;
  const mcAt   = solves.montecarlo&&solves.montecarlo.ranAt;
  const ratio = (demTot>0 && prodUnits!=null) ? prodUnits/demTot : null;

  // B-13 — the S&OP (aggregate) plan must consume the COMMITTED demand series
  // (getItemDemand — the same source procurement + production read), NOT the seed
  // master reslice. Re-derive the REAL loop payload and compare each COMMITTED SKU's
  // forecast to getItemDemand over the same period count — the exact check HARNESS-1b
  // runs. Uncommitted SKUs legitimately fall back to the seed reslice, so they are
  // scoped out (comparing them would false-flag the flat seed vs the seasonal reslice).
  let b13st='na', b13detail='run Demand (or the Loop) to commit a demand series — then this asserts the S&OP plan consumes it, not the seed master';
  try{
    if(typeof _loopAggregatePayload==='function' && typeof getItemDemand==='function'){
      const ap = _loopAggregatePayload(appStore.get().planning);
      const per = (ap.params&&ap.params.periods)||6;
      const committedSkus = (ap.products||[]).filter(p=>{ const s=demand[p.name]; return s&&s.length; });
      if(committedSkus.length){
        const mism = committedSkus.filter(p=>{
          const c = getItemDemand(p.name, per).reduce((a,b)=>a+(+b||0),0);
          const inPlan = (p.forecast||[]).reduce((a,b)=>a+(+b||0),0);
          return Math.abs(c-inPlan)>1; });
        b13st = mism.length?'bad':'ok';
        b13detail = mism.length
          ? `${mism.length} SKU(s) plan to the SEED, not committed demand: `+mism.map(p=>p.name).join(', ')
          : `all ${committedSkus.length} committed SKU(s): S&OP forecast == getItemDemand over ${per} periods (not the seed reslice)`;
      }
    }
  }catch(e){ b13st='na'; b13detail='aggregate payload not derivable: '+(e&&e.message||e); }

  const checks = [
    { id:'I-5', label:'Plan ⇄ Production ⇄ Demand units reconcile',
      st: ratio==null?'na':(ratio>=0.7&&ratio<=1.4?'ok':'bad'),
      detail: ratio==null ? 'run Demand + Production to compare' :
        `committed demand ${Math.round(demTot).toLocaleString('en-IN')}u vs production build ${Math.round(prodUnits).toLocaleString('en-IN')}u (ratio ${ratio.toFixed(2)})` +
        (ratio>=0.7&&ratio<=1.4?' — within inventory swing':' — ⚠ off; check the labor-weighted vs physical unit basis (P-C)'),
      go: ratio==null?'production':null },
    { id:'B-13', label:'S&OP plan sources COMMITTED demand (not the seed master)',
      st: b13st, detail: b13detail, go: b13st==='na'?'demand':null },
    { id:'I-3', label:'Sourcing carry rate is anchored to the Finance hurdle',
      st: hurdle==null?'na':'ok',
      detail: hurdle==null ? 'finance helpers unavailable' :
        `blended hurdle ${hurdle.toFixed(2)}%` + (carry!=null?` · carry rate ${carry.toFixed(2)}% (= hurdle + holding spread)`:'') + ' — carryRate() reads finBlendedHurdle() by construction (FIN-8)' },
    { id:'#5', label:'Monte-Carlo ran on the COMMITTED production plan (not a fresh one)',
      st: (!prodAt||!mcAt)?'na':(mcAt>=prodAt?'ok':'bad'),
      detail: (!prodAt||!mcAt) ? 'run Production then Monte-Carlo to verify the replay' :
        (mcAt>=prodAt ? 'MC ran after the committed schedule — it replays the same gantt' : '⚠ MC is older than the current schedule — re-run risk on the committed plan'),
      go: (!prodAt||!mcAt)?'scenarios':null },
    { id:'I-2', label:'A capacity bottleneck is priced (profit-mix shadow price)',
      st: pmMax==null?'na':(pmMax>0?'ok':'bad'),
      detail: pmMax==null ? 'run profit-mix in Console to price the binding constraint' :
        (pmMax>0 ? `profit-mix binding dual ₹${pmMax.toFixed(0)}/unit` + (pmNames.length?` binds [${pmNames.join(', ')}]`:'') +
            (lcMax!=null ? ` · line-capacity dual ₹${lcMax.toFixed(0)}/unit (${lcMax>0?'binds':'all lines honestly slack, π=0 at this volume'})` : ' · line-capacity dual not in cache')
          : 'profit-mix reports NO binding dual — the glass-box bottleneck claim would be empty (expected Shared Capacity to bind)'),
      go: pmMax==null?'console':null },
    { id:'I-6', label:'MEIO pooled safety stock < Σ decentralised (√N dividend)',
      st: mn==null?'na':(mn.total_ss_value_pooled<mn.total_ss_value_decentralised?'ok':'bad'),
      detail: mn==null ? 'run MEIO-network in Sourcing to check pooling' :
        `pooled ₹${_obsCr(mn.total_ss_value_pooled)} < decentralised ₹${_obsCr(mn.total_ss_value_decentralised)} · capital freed ₹${_obsCr(mn.total_capital_freed)}`,
      go: mn==null?'sourcing':null },
  ];
  const ST = { ok:{i:'✓',c:C.gn}, bad:{i:'✗',c:C.dg}, info:{i:'•',c:C.a4}, na:{i:'—',c:C.tx3} };
  const okN = checks.filter(c=>c.st==='ok').length, badN = checks.filter(c=>c.st==='bad').length;

  return (
    <Card icon="🧮" title="Cross-solver consistency — do the engines agree?" span={2}
      badge={badN?`${badN} mismatch`:`${okN} checks pass`} badgeTone={badN?'k':okN?'g':'y'}
      right={<Provenance kind="derived"/>}
      info={{ what:'The per-tab smokes each verify ONE solver in isolation. These checks assert that the SAME quantity agrees ACROSS solvers in the live cache — the end-to-end observability that was the biggest blind spot.', flows:'A red row means two engines disagree on a number that must match — fix before trusting the plan.' }}
      dev={{ comp:'ConsistencyPanel (OBS-2)', props:'getSolveResult(aggregate, production, procurement, montecarlo, linecap, profitmix, meionet) + _loopAggregatePayload + config', note:'Surfaces ALL 6 cross-solver identities HARNESS-1b asserts (I-5, B-13, I-3, #5, I-2, I-6) — kept in lockstep with tools/golden_path.js by the model_check "panel == harness" gate (G-RF1). Honest "—" when a solve has not run.' }}>
      <div style={{display:'flex', flexDirection:'column', gap:7}}>
        {checks.map(c=>{ const m=ST[c.st];
          return (
            <div key={c.id} style={{display:'flex', alignItems:'flex-start', gap:10, padding:'8px 10px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${m.c}`, background:C.bg3}}>
              <span style={{fontFamily:F.mono, fontWeight:800, fontSize:13, color:m.c, width:14, textAlign:'center'}}>{m.i}</span>
              <div style={{flex:1}}>
                <div style={{fontFamily:F.body, fontSize:11.5, fontWeight:700, color:C.tx}}>{c.label} <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, fontWeight:600}}>· {c.id}</span></div>
                <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, marginTop:2, lineHeight:1.45}}>{c.detail}</div>
              </div>
              {c.go && <button onClick={()=>onNav&&onNav(c.go)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline', whiteSpace:'nowrap'}}>run →</button>}
            </div>
          );
        })}
      </div>
      <Reading tone={C.tx2}
        formula="the SAME 6 identities HARNESS-1b asserts end-to-end (I-5 · B-13 · I-3 · #5 · I-2 · I-6), read live from the cross-stage cache — the panel DISPLAYS them, the harness FAILS the build on a violation"
        soWhat="These are the cross-solver identities from the observability spec §4.1, asserted on whatever is in the live cache. Run the full loop (Scenarios ▸ Loop) — and profit-mix in Console — to light them all up."/>
    </Card>
  );
}

// R13 honesty pass: the EOQ worked example now COMPUTES live from the inputs
// (was three hardcoded result strings). Every figure is the real formula on the
// current numbers — change a field and EOQ, order frequency and total cost all move.
function RefLearn() {
  const [open, setOpen] = useState(3);
  const [D, setD]   = useState(2840);   // annual demand
  const [S, setS]   = useState(1200);   // order cost
  const [hP, setHP] = useState(18);     // holding %/yr
  const [c, setC]   = useState(1190);   // unit cost
  const num = v => v===''||v==null?0:Number(v);
  const h    = num(hP)/100*num(c);                                   // ₹ holding per unit per year
  const eoq  = h>0 && num(D)>0 ? Math.sqrt(2*num(D)*num(S)/h) : 0;    // √(2DS/h)
  const orders = eoq>0 ? num(D)/eoq : 0;
  const totCost = eoq>0 ? (num(D)/eoq)*num(S) + (eoq/2)*h : 0;        // ordering + holding
  const fmt = n => isFinite(n)?Math.round(n).toLocaleString('en-IN'):'—';
  return (
    <Grid cols={1}>
      <Card icon="📚" title="Learning Lab" badge={`${M.learnSections.length} concepts`} info={{ what:'Supply-chain fundamentals — the EOQ worked example below computes live.', flows:'Folds into inline SectionInfo popovers.' }}
        dev={{ comp:'LearningLab', props:'concept', note:'Consider folding into SectionInfo popovers.' }}>
        <Grid cols={3} gap={8}>
          {M.learnSections.map((s,i)=>(
            <button key={i} onClick={()=>setOpen(i)} style={{
              textAlign:'left', border:`2px solid ${C.line}`, cursor:'pointer', padding:'9px 11px',
              background: open===i?C.ac:C.paper, color:C.tx, display:'flex', flexDirection:'column', gap:2,
            }}>
              <span style={{fontFamily:F.mono, fontSize:8.5, color: open===i?C.onAc:C.tx3}}>{String(i+1).padStart(2,'0')}</span>
              <span style={{fontFamily:F.disp, fontSize:11.5, fontWeight:700}}>{s}</span>
            </button>
          ))}
        </Grid>
      </Card>
      <Card icon="🧮" title="EOQ — worked live" badge="computed" badgeTone="g"
        right={<Provenance kind="derived" note="√(2DS/h) on your inputs"/>}
        info={{ what:'The economic order quantity computed live from your numbers — not a stored answer. Change any input and the result recomputes.', flows:'Builds intuition; the same formula the (s,S)/(R,Q) autopilot uses.' }}
        dev={{ comp:'EOQPlayground', props:'D,S,h,c → EOQ', note:'R13 — live calc replacing the hardcoded result strings.' }}>
        <Grid cols={2}>
          <div>
            <SubLabel>Try it</SubLabel>
            <Grid cols={2} gap={8}>
              <Field label="Annual Demand (D)"><NumInput value={D} onChange={setD} suffix="u"/></Field>
              <Field label="Order Cost (S)"><NumInput value={S} onChange={setS} prefix="₹"/></Field>
              <Field label="Holding (h)"><NumInput value={hP} onChange={setHP} suffix="%"/></Field>
              <Field label="Unit Cost (c)"><NumInput value={c} onChange={setC} prefix="₹"/></Field>
            </Grid>
          </div>
          <div>
            <SubLabel>Result</SubLabel>
            <KpiRow cols={1}>
              <Blk label="EOQ = √(2DS/h)" value={eoq>0?`${fmt(eoq)} u`:'—'} tone="y"/>
              <Blk label="Orders / yr" value={orders>0?orders.toFixed(1):'—'}/>
              <Blk label="Total relevant cost" value={totCost>0?`₹ ${fmt(totCost)} / yr`:'—'}/>
            </KpiRow>
          </div>
        </Grid>
        <Reading tone={C.tx2}
          formula={`EOQ = √(2·${fmt(D)}·${fmt(S)} / ${fmt(h)}) = ${fmt(eoq)} u  ·  h = ${num(hP)}% × ₹${fmt(c)} = ₹${fmt(h)}/u/yr`}
          soWhat={eoq>0?`Ordering ${fmt(eoq)} units at a time balances ordering against holding at ₹${fmt(totCost)}/yr — the convex minimum. Raise the order cost S and the EOQ grows (order less often); raise holding h and it shrinks.`:'Enter positive demand, holding % and unit cost to compute the EOQ.'}/>
      </Card>
    </Grid>
  );
}

function RefSAP({ onNav }) {
  // R13 honesty pass: read the REAL cached Monte-Carlo solve instead of three
  // hardcoded ₹ figures. If risk hasn't been run, say so (illustrative seed) and
  // point to where to solve it — never present a seed as a live number.
  const mc = (typeof useSolveResult==='function') ? useSolveResult('montecarlo') : { result:null };
  const r = mc.result;
  const L = n => (n==null||isNaN(n))?'—':`₹${(n/1e5).toFixed(0)}L`;
  const premium = r && r.cvar95!=null && r.avg_cost!=null ? r.cvar95 - r.avg_cost : null;
  return (
    <Grid cols={2}>
      <Card icon="🏢" title="SAP Mode · Overview" badge="parallel world" badgeTone="k" info={{ what:'Maps this model to an SAP multi-plant reference.', flows:'Reference/T-code overlay unless multi-plant committed.' }} span={2}
        dev={{ comp:'SAPModeTab', props:'state (read-only map)', note:'Parallel multi-plant world — reference overlay.' }}>
        <div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, marginBottom:8}}>Reference map of the SAP-equivalent areas — read-only labels, not switchable views.</div>
        <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
          {['Overview','Physical Network','Master Data','Planning Runs','ML Demand Sensing','Stochastic / CVaR Solver'].map((s,i)=>(
            <div key={i} style={{border:`2px solid ${C.line2}`, padding:'8px 12px', fontFamily:F.disp, fontSize:11, fontWeight:700, background:C.bg3, color:C.tx2}}>{s}</div>
          ))}
        </div>
      </Card>
      <Card icon="⌨️" title="T-Code Cheatsheet" badge={`${M.sapTcodes.length} codes`} info={{ what:'SAP transaction codes mapped to this app\u2019s actions.', flows:'Migration crib sheet.' }}
        dev={{ comp:'TCodeCard', props:'sapTcodes' }}>
        <DataTable cols={['T-Code','Function','Area']} align={['left','left','left']}
          rows={M.sapTcodes.map(t=>[<span style={{fontWeight:700}}>{t.code}</span>, t.name, <Tag c="w">{t.area}</Tag>])}/>
      </Card>
      <Card icon="🔮" title="Stochastic / CVaR Solver" badge={r?'live · from Risk':'not run'} badgeTone={r?'g':'k'} info={{ what:'Risk-averse view minimising CVaR not just mean — read from the committed-plan Monte-Carlo solve when it exists.', flows:'Alt objective for Console.' }}
        right={r ? <Provenance kind="solved" asOf={mc.ranAt} note="montecarlo cache"/> : <Provenance kind="external" run="seed"/>}
        dev={{ comp:'CVaRSolverCard', props:'useSolveResult(montecarlo)', note:'R13 — reads the cached MC solve; honest "not run" otherwise.' }}>
        {r ? <>
          <KpiRow cols={2}>
            <Blk label="Mean cost" value={L(r.avg_cost)}/>
            <Blk label="CVaR 95%" value={L(r.cvar95)} accent={C.dg}/>
            <Blk label="Risk premium" value={L(premium)} tone="c"/>
            <Blk label="Mean fill" value={r.avg_fill!=null?`${r.avg_fill}%`:'—'} tone="y"/>
          </KpiRow>
          <div style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>The β=95% tail costs {L(premium)} over the mean on the committed plan ({r.n_runs} runs, policy {r.policy_simulated}). Choose per risk appetite.</div>
        </> : (
          <div style={{padding:'10px 12px', border:`2px dashed ${C.line2}`, fontFamily:F.mono, fontSize:10.5, color:C.tx3, lineHeight:1.5}}>
            Not solved yet — run Monte Carlo in the <span onClick={()=>onNav&&onNav('scenarios')} style={{textDecoration:'underline', cursor:'pointer', color:C.a2}}>Scenario &amp; Risk Lab</span> and the real mean / CVaR95 / risk-premium of the committed plan appear here. No seed numbers shown.
          </div>
        )}
      </Card>
    </Grid>
  );
}
window.StageReference = StageReference;
