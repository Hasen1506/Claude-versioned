// ════════════════════════════════════════════════════════════════════════
// reference.jsx — Reference. Sub-tabs: Learning Lab · SAP Mode.
// ════════════════════════════════════════════════════════════════════════
function StageReference({ onNav }) {
  const [sub, setSub] = useState('learn');
  const tabs = [
    { id:'learn', n:'a', label:'Learning Lab', count:M.learnSections.length },
    { id:'sap',   n:'b', label:'SAP Mode', count:M.sapTcodes.length },
    { id:'api',   n:'c', label:'Open API' },
  ];
  return (
    <div>
      <StageHeader n="12" title="Reference" kicker="Learning Lab concept explainers · SAP T-code map · open solve-API substrate"/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
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
        <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
          {['Overview','Physical Network','Master Data','Planning Runs','ML Demand Sensing','Stochastic / CVaR Solver'].map((s,i)=>(
            <div key={i} style={{border:`2px solid ${C.line}`, padding:'8px 12px', fontFamily:F.disp, fontSize:11, fontWeight:700, background: i===0?C.ink:C.paper, color:i===0?C.ac:C.tx}}>{s}</div>
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
