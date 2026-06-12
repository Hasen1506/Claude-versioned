// ════════════════════════════════════════════════════════════════════════
// console.jsx — Optimize & Solve. R13: the two jobs Console quietly did are now
// EXPLICIT, banded top-to-bottom:
//   ① ORCHESTRATE — the planning spine, the SOLE solver-network graph (Home no
//      longer duplicates it), the run console + solve status. "Pick & run."
//   ② INTERPRET   — the selected solver's results + the D1 glass-box explainer
//      and D1+ prove-it. "Run & understand." The header names the live selection.
// SolverNetwork is rendered ONLY here now (Home links to it) — one graph, one job.
// ════════════════════════════════════════════════════════════════════════
// small labeled divider naming each of Console's two jobs.
function JobBand({ n, title, sub, right }){
  return (
    <div style={{display:'flex', alignItems:'center', gap:10, padding:'9px 14px', borderTop:`2px solid ${C.line}`, borderBottom:`2px solid ${C.line}`, background:C.ink, color:C.paper}}>
      <span style={{fontFamily:F.disp, fontWeight:900, fontSize:13, color:C.ac, width:18}}>{n}</span>
      <span style={{fontFamily:F.disp, fontSize:12, fontWeight:800, letterSpacing:'.06em', textTransform:'uppercase'}}>{title}</span>
      {sub && <span style={{fontFamily:F.mono, fontSize:9, color:'rgba(255,255,255,.55)'}}>{sub}</span>}
      {right && <span style={{marginLeft:'auto'}}>{right}</span>}
    </div>
  );
}

function StageConsole({ onNav }) {
  const [sel, setSel] = useState('procurement');          // selected engine (graph ↔ results)
  // B-2 — colour the fabric by LIVE solve freshness (cross-stage cache), not the seed
  // `status` field. Same one-source builder the Reference ▸ Model Map uses.
  const { state:_solves }  = useStore(s=>s.solves||{});
  const { state:_results } = useStore(s=>s.solveResults||{});
  const { state:_events }  = useStore(s=>s.events||[]);   // V3-5 — tower inbox/ledger read the real event log
  const { fresh:_fresh, obj:_liveObj } = (typeof solverFreshnessMaps==='function') ? solverFreshnessMaps(_solves, _results) : {};
  const [allBusy, setAllBusy] = useState(false);   // header "run spine" → real runFullLoop
  const runSpine = async ()=>{ setAllBusy(true); try{ await runFullLoop({}); }finally{ setAllBusy(false); } };
  const resultKey = { profitmix:'profit', procurement:'procurement', production:'production', sequencing:'production', transport:'transport', allocation:'transport', consolidate:'transport', montecarlo:'risk', cvar:'risk', capital:'capital', capital_capacity:'capital', sop:'sop', forecast:'profit', aggregate:'sop', disaggregate:'sop', reconcile:'sop', lotsizing:'procurement' }[sel] || 'procurement';
  const sections = M.consoleResults[resultKey] || [];
  const selSolver = M.solvers.find(s=>s.id===sel);

  return (
    <div>
      <StageHeader n="10" title="Optimize & Solve Console" kicker="Two jobs, banded — ① orchestrate (pick & run a solver) and ② interpret (read its result + the glass-box explainer)"
        right={<Btn kind="accent" disabled={allBusy} onClick={runSpine} title="Runs the 6-step planning spine (forecast → procurement → aggregate → production → capital signal → Monte-Carlo risk) live on the committed dataset. Per-engine runs are in the Anatomy Lab (③) below.">{allBusy?'⏳ Solving spine…':'▶ Run spine · 6 of 16'}</Btn>}/>

      <JobBand n="①" title="Orchestrate" sub="control tower — run the spine · the one solver network · live engine status · exceptions / activity / identities"/>

      {/* PLANNING SPINE (handoff v2 §7.1) — the ordered solve chain, conditional on profile */}
      <div style={{padding:'14px 14px 0'}}>
        <Card icon="🧬" title="Planning Spine" badge="9 steps · profile-gated" badgeTone="k"
          info={{ what:'The order solvers run in — with steps your profile makes unnecessary greyed out.', flows:'Profit-mix only exists to ration scarce capacity; ample capacity skips it.' }}
          dev={{ comp:'PlanningSpine', props:'M.spine, profileGate', note:'A step’s gate references a profile answer (e.g. capacity ample → skip Profit-mix).' }}>
          <PlanningSpine onNav={onNav}/>
        </Card>
      </div>

      <div style={{padding:14, display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:14}}>
        {/* SHARED SOLVER NETWORK (same component as Home) */}
        <Card icon="🧭" title="Solver Network" badge={M.solverLabel} badgeTone="y" info={{ what:'The 5-family engine network — the one place it lives now (Home links here). Node colour = LIVE solve freshness (green fresh · amber stale · grey not run), not a seed status. Click a node to load its run mode + results in ② below.', flows:'One graph, one data source. Full freshness legend + lineage on Reference ▸ Model Map.' }}
          dev={{ comp:'SolverNetwork', props:'solvers, edges, sel, onSelect, freshness, liveObj', note:'R13 — sole home of the graph; B-2 — now coloured by solverFreshnessMaps (same builder as Model Map), not the seed status.' }}>
          <div style={{overflowX:'auto'}}><SolverNetwork freshness={_fresh} liveObj={_liveObj} sel={sel} onSelect={setSel} onNav={onNav}/></div>
          <div style={{marginTop:8, display:'flex', gap:8, alignItems:'center'}}>
            <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>selected:</span>
            <Tag c="k">{selSolver?selSolver.name:sel}</Tag>
            {selSolver && <button onClick={()=>onNav(selSolver.go)} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>open {selSolver.go} →</button>}
          </div>
        </Card>

        {/* CONTROL TOWER — V3-5: the inert Run-Profile picker (composed a profile nothing
            consumed; its ▶ SOLVE was permanently disabled) and the SEED Solve-Status card
            (selSolver.status/obj + the static M.shadow dual table — seed numbers wearing a
            live face) are GONE. Their replacements read only live state: freshness for the
            selected engine + the exception inbox / event ledger / identity links below. */}
        <div style={{display:'flex', flexDirection:'column', gap:14}}>
          {(()=>{ const _k = (typeof _OBS_KEY!=='undefined' && _OBS_KEY[sel]) || sel;
            const _sv = _solves && _solves[_k];
            const _f = (_fresh && _fresh[sel]) || 'never';
            return (
          <Card icon="📡" title="Engine Status · live" badge={_f==='never'?'not run yet':_f} badgeTone={_f==='fresh'?'g':_f==='stale'?'w':'k'}
            info={{ what:'The selected engine, read from the cross-stage solve cache: freshness, the cached objective of its LAST REAL solve, and when it ran. No seed numbers.', flows:'Freshness → re-run decisions; click the graph to switch engines.' }}
            dev={{ comp:'EngineStatus (V3-5)', props:'solverFreshnessMaps(solves, solveResults)[sel] + solves[_OBS_KEY[sel]]', note:'replaces the seed Solve Status card (selSolver.status/obj + static M.shadow duals).' }}>
            <KpiRow cols={3}>
              <Blk label="Freshness" value={_f==='never'?'not run':_f} tone={_f==='fresh'?'y':'c'}/>
              <Blk label="Last objective" value={(_liveObj&&_liveObj[sel])||'—'} />
              <Blk label="Last run" value={_sv&&_sv.ranAt?new Date(_sv.ranAt).toLocaleTimeString():'—'}/>
            </KpiRow>
            {_sv && _sv.stale && _sv.root &&
              <div style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color:C.a4}}>stale because you edited <b>{_sv.root}</b> — re-run it (Anatomy Lab ③ or its home tab).</div>}
            <div style={{marginTop:10}}><SolverExplain id={sel}/></div>
            <SolverIO id={sel}/>
          </Card>); })()}
          <TowerRow events={_events} solves={_solves} results={_results} onNav={onNav}/>
        </div>
      </div>

      <JobBand n="②" title="Interpret" sub="the selected solver's result + the plain-English glass-box explainer & prove-it"
        right={<span style={{display:'inline-flex', alignItems:'center', gap:8}}>
          <span style={{fontFamily:F.mono, fontSize:9, color:'rgba(255,255,255,.55)'}}>showing</span>
          <Tag c="g">{selSolver?selSolver.name:sel}</Tag>
          {selSolver && <button onClick={()=>onNav(selSolver.go)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.ac, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>open {selSolver.go} →</button>}
        </span>}/>

      {/* RESULT SUB-TABS grouped by solver */}
      <div style={{padding:'14px 14px 14px'}}>
        <div style={{border:`2px solid ${C.line}`, background:C.bg2}}>
          <div style={{display:'flex', flexWrap:'wrap', borderBottom:`2px solid ${C.line}`}}>
            {[['profitmix','Profit'],['procurement','Procurement'],['production','Production'],['transport','Transport'],['montecarlo','Risk/MC'],['capital','Capital'],['sop','S&OP']].map(([id,lbl])=>{
              const a=sel===id;
              return (
                <button key={id} onClick={()=>setSel(id)} style={{
                  padding:'8px 14px', border:'none', borderRight:`2px solid ${C.line}`, cursor:'pointer',
                  background: a?C.ac:'transparent', color:C.tx, fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.04em', textTransform:'uppercase',
                }}>{lbl}</button>
              );
            })}
            <span style={{marginLeft:'auto', alignSelf:'center', padding:'0 14px', fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>{sections.length} result sections</span>
          </div>
          <div style={{padding:14}}>
            <ConsoleResults solver={sel} sections={sections} onNav={onNav}/>
          </div>
        </div>
      </div>

      <JobBand n="③" title="Anatomy Lab" sub="glass-box — the REAL model, what feeds each term, and a live solve (Cartesian-style)"
        right={<span style={{display:'inline-flex', alignItems:'center', gap:8}}>
          <span style={{fontFamily:F.mono, fontSize:9, color:'rgba(255,255,255,.55)'}}>dissecting</span>
          <Tag c="g">{selSolver?selSolver.name:sel}</Tag>
        </span>}/>
      <div style={{padding:'14px 14px 18px'}}><SolverLab sel={sel} onNav={onNav}/></div>
    </div>
  );
}

// ── V3-5 · TowerRow — the control tower's three cross-solver summary cards ──
// Part-4 rule applied to the non-result surfaces too: the Console shows a LIVE
// one-line summary + a link to the home surface — it never re-renders the full
// card (that is how the FIN-1/ResProfit duplicate-render bug class is born).
//   · Exceptions — exceptionInbox() COUNTS by severity + the top item; home =
//     Scenarios ▸ Cockpit (the full ranked inbox).
//   · Activity   — the last real events from the immutable audit log (events[]);
//     home = Scenarios ▸ Cockpit (ValueLedger scores them into ₹).
//   · Identities — how many engines are fresh/stale/never from the SAME
//     solverFreshnessMaps the Model Map uses + a link to the full OBS-2
//     ConsistencyPanel (NOT recomputed here — the panel is gate-pinned to the
//     harness (G-RF1); a second computation could drift).
function TowerRow({ events, solves, results, onNav }){
  const items = (typeof exceptionInbox==='function') ? exceptionInbox(solves||{}, events||[], results||{}) : [];
  const hi = items.filter(i=>i.sev==='H').length;
  const top = items[0];
  const recent = (events||[]).slice(-4).reverse();
  const counts = { fresh:0, stale:0, never:0, untracked:0 };
  if(typeof solverFreshnessMaps==='function'){ const { fresh } = solverFreshnessMaps(solves||{}, results||{});
    (M.solvers||[]).forEach(s=>{ counts[fresh[s.id]] = (counts[fresh[s.id]]||0)+1; }); }
  const link = (go, label)=> <button onClick={()=>onNav && onNav(go)} style={{border:'none', background:'transparent', cursor:'pointer', color:C.a2, fontFamily:F.mono, fontSize:9, fontWeight:700, textDecoration:'underline', padding:0}}>{label}</button>;
  return (
    <Card icon="🗼" title="Tower · exceptions / activity / identities" badge={items.length?`${items.length} open · ${hi} high`:'all clear'} badgeTone={hi?'w':'g'}
      info={{ what:'Cross-solver summaries only the Console can show: the live exception inbox count, the latest audit-log activity, and engine freshness — each linking to its full home surface rather than re-rendering it.', flows:'inbox → Scenarios cockpit · activity → ValueLedger · identities → Reference Model Map (OBS-2 panel).' }}
      dev={{ comp:'TowerRow (V3-5)', props:'exceptionInbox(solves,events,results) · events[] tail · solverFreshnessMaps counts', note:'summary+link only — one-result-one-home applied to non-result surfaces.' }}>
      <div style={{display:'flex', flexDirection:'column', gap:8}}>
        <div style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${hi?C.dg:C.line}`, padding:'6px 9px', background:hi?C.bg3:C.paper}}>
          <Tag c={hi?'r':'g'}>{items.length?`${items.length} EXC`:'CLEAR'}</Tag>
          <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, flex:1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{top?top.msg:'no exceptions — fabric clean'}</span>
          {link('scenarios','inbox →')}
        </div>
        <div style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${C.line}`, padding:'6px 9px'}}>
          <Tag c="c">LOG</Tag>
          <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, flex:1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>
            {recent.length?recent.map(e=>`${e.type}${e.target?` ${e.target}`:''}`).join(' · '):'no decisions logged yet'}
          </span>
          {link('scenarios','ledger →')}
        </div>
        <div style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${C.line}`, padding:'6px 9px'}}>
          <Tag c={counts.stale?'w':'g'}>{counts.fresh}/{(M.solvers||[]).length} FRESH</Tag>
          <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, flex:1}}>{counts.stale} stale · {counts.never} never run — 6 cross-solver identities live on the Model Map</span>
          {link('reference','identities →')}
        </div>
      </div>
    </Card>
  );
}

// ════════════════════════════════════════════════════════════════════════
// SolverLab (Cartesian-style glass-box) — three panes for the SELECTED engine:
//   ① The model   — its REAL type (LP/MILP/closed-form/sim/ML, from M.solverType,
//                    read straight off the .py docstring), objective, decision vars,
//                    constraints + a read-only source view (/api/meta/solver-source).
//   ② Inputs      — every objective/constraint TERM mapped to the define-section that
//                    feeds it (✓ wired) or honestly flagged ⚠ defaulted-in-the-.py,
//                    plus `extras` = capability modelled but never wired ("too much
//                    stuff"). This is the term→input cross-reference, made visible.
//   ③ Live solve  — runs the engine's REAL endpoint on the committed dataset (for the
//                    engines with a shared payload builder) or reads its cached solve;
//                    shows status, objective, runtime + duals / binding / distribution.
// NO editable-code→execution path (that would be RCE): the source pane is read-only,
// and the solve only ever calls the existing curated /api/solve endpoints.
const LAB_EP = {
  forecast:'/api/forecast', aggregate:'/api/solve/aggregate', profitmix:'/api/solve/profitmix',
  procurement:'/api/solve/procurement', production:'/api/solve/production', transport:'/api/solve/transport',
  allocation:'/api/solve/transport', consolidate:'/api/solve/consolidate', montecarlo:'/api/solve/montecarlo',
  cvar:'/api/solve/cvar', capital:'/api/solve/capital', capital_capacity:'/api/solve/capital-capacity',
  sequencing:'/api/solve/sequence', lotsizing:'/api/solve/lotsizing', linecap:'/api/solve/linecap',
  policy:'/api/solve/policy', meio:'/api/solve/meio', meionet:'/api/solve/meio-network',
};
function SolverLab({ sel, onNav }){
  const { planning } = (typeof usePlanning==='function') ? usePlanning() : { planning:{} };
  const ty = (window.M && M.solverType && M.solverType[sel]) || null;
  const model = (window.M && M.solverModel && M.solverModel[sel]) || null;
  const [src, setSrc] = useState(null);
  const [srcOpen, setSrcOpen] = useState(false);
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  React.useEffect(()=>{ setRun(null); setErr(null); setSrc(null); setSrcOpen(false); }, [sel]);
  // shared payload builders (globals from store.jsx) — only these can re-solve live
  const builders = {
    forecast: ()=>_loopForecastPayload(planning), aggregate: ()=>_loopAggregatePayload(planning),
    procurement: ()=>_loopProcurementPayload(planning), production: ()=>productionPayload(planning),
    transport: ()=>transportPayload(), montecarlo: ()=>montecarloPayload(planning),
  };
  const canRun = !!(builders[sel] && LAB_EP[sel]);
  const cached = (typeof getSolveResult==='function') ? getSolveResult(sel) : null;
  const result = run || (cached && cached.result) || null;
  const fromCache = !run && !!(cached && cached.result);
  const loadSrc = ()=>{ setSrcOpen(o=>!o); if(src) return;
    fetch('/api/meta/solver-source/'+sel).then(r=>r.json()).then(d=>setSrc(d)).catch(e=>setSrc({ error:String(e.message||e) })); };
  const doRun = ()=>{ if(!canRun) return; setBusy(true); setErr(null); const t0=performance.now();
    fetch(LAB_EP[sel], { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(builders[sel]()) })
      .then(r=>r.json()).then(d=>{ if(d && d.error) throw new Error(d.error); setRun({ ...d, _ms:Math.round(performance.now()-t0) }); })
      .catch(e=>setErr(String(e.message||e))).finally(()=>setBusy(false)); };
  // adaptive result read-out
  const num = (v)=> (v==null||isNaN(v))?null:v;
  const objLine = (()=>{ if(!result) return null;
    if(result.total_cost!=null) return `min cost ₹${(result.total_cost/1e5).toFixed(1)}L`;
    if(result.total_npv!=null) return `max NPV ₹${(result.total_npv/1e5).toFixed(1)}L`;
    if(result.objective!=null) return `objective ${Math.round(result.objective).toLocaleString('en-IN')}`;
    if(result.avg_fill!=null) return `mean fill ${result.avg_fill}% · CVaR95 ₹${((result.cvar95||0)/1e5).toFixed(1)}L`;
    if(result.products && result.products[0]) { const p=result.products[0]; return `winner ${p.winner||p.recommendation||'—'}`; }
    if(result.total_changeover_min!=null) return `changeover ${result.total_changeover_min} min`;
    return null; })();
  const status = result ? (result.status || (result.products?'Fitted':(result.avg_fill!=null?'Simulated':'OK'))) : null;
  const duals = (()=>{ if(!result) return null;
    if(Array.isArray(result.shadow_prices) && result.shadow_prices.length) return result.shadow_prices.map(s=>({ k:s.resource||s.name||s.res, v:s.shadow_price!=null?s.shadow_price:s.dual, bind:s.binding }));
    if(Array.isArray(result.lines) && result.lines.some(l=>l.shadow_price!=null)) return result.lines.map(l=>({ k:l.name||l.id, v:l.shadow_price, bind:l.binding }));
    return null; })();
  const Pane = ({ n, title, children, tone })=>(
    <div style={{border:`2px solid ${C.line}`, background:C.paper, display:'flex', flexDirection:'column', minWidth:0}}>
      <div style={{padding:'7px 11px', borderBottom:`2px solid ${C.line}`, background:tone||C.bg3, display:'flex', alignItems:'center', gap:7}}>
        <span style={{fontFamily:F.disp, fontWeight:900, fontSize:11, color:C.ac}}>{n}</span>
        <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.05em', textTransform:'uppercase'}}>{title}</span>
      </div>
      <div style={{padding:11, flex:1}}>{children}</div>
    </div>
  );
  return (
    <div style={{display:'grid', gridTemplateColumns:'1.05fr 1.05fr 0.9fr', gap:12}}>
      {/* ① THE MODEL */}
      <Pane n="①" title="The model">
        {ty ? <>
          <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:8}}>
            <Tag c={ty.tag}>{ty.type}</Tag>
            <span style={{fontFamily:F.mono, fontSize:9, color: ty.solves?C.gn:C.tx3}}>{ty.solves?'optimiser':'estimator / sim'}</span>
          </div>
          <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.5, marginBottom:10}}>{ty.method}</div>
          {model ? <>
            <SubLabel>Objective</SubLabel>
            <div style={{fontFamily:F.mono, fontSize:10, color:C.tx, padding:'6px 9px', border:`2px solid ${C.line2}`, background:C.bg3, marginBottom:8, lineHeight:1.4}}>{model.objective}</div>
            <SubLabel>Decision variables</SubLabel>
            <div style={{marginBottom:8}}>{model.vars.map((v,i)=><div key={i} style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>• {v}</div>)}</div>
            <SubLabel>Constraints</SubLabel>
            <div>{model.constraints.map((c,i)=><div key={i} style={{fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>· {c}</div>)}</div>
          </> : <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3}}>Anatomy detail not authored for this engine yet — type + source still apply.</div>}
          <div style={{marginTop:10}}>
            <button onClick={loadSrc} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:`1.5px solid ${C.line2}`, cursor:'pointer', padding:'4px 9px'}}>{srcOpen?'▾ hide source':'▸ view real source (read-only)'}</button>
            {srcOpen && <div style={{marginTop:8}}>
              {!src ? <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>loading source…</div>
                : src.error ? <div style={{fontFamily:F.mono, fontSize:9.5, color:C.dg}}>⚠ {src.error}</div>
                : <><div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, marginBottom:4}}>{src.file} · {src.lines} lines · docstring + first {src.excerpt_lines}</div>
                  <pre style={{margin:0, maxHeight:240, overflow:'auto', background:C.ink, color:'#cbd5e1', fontFamily:F.mono, fontSize:9, lineHeight:1.45, padding:'8px 10px', whiteSpace:'pre-wrap'}}>{src.docstring}{'\n\n— — — source excerpt — — —\n\n'}{src.excerpt}</pre></>}
            </div>}
          </div>
        </> : <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx3}}>No type metadata for "{sel}".</div>}
      </Pane>

      {/* ② INPUTS & PROVENANCE (the audit) */}
      <Pane n="②" title="Inputs ▸ does every term have a source?">
        {model ? <>
          <div style={{display:'flex', flexDirection:'column', gap:5}}>
            {model.terms.map((t,i)=>(
              <div key={i} style={{display:'flex', alignItems:'flex-start', gap:8, border:`2px solid ${t.wired?C.line2:C.a4}`, borderLeft:`5px solid ${t.wired?C.gn:C.a4}`, background: t.wired?C.paper:C.bg3, padding:'5px 8px'}}>
                <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, color: t.wired?C.gn:C.a4, marginTop:1, whiteSpace:'nowrap'}}>{t.wired?'✓ WIRED':'⚠ DEFAULT'}</span>
                <div style={{minWidth:0, flex:1}}>
                  <div style={{fontFamily:F.disp, fontSize:11, fontWeight:700}}>{t.t}</div>
                  <div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{t.src}</div>
                </div>
              </div>
            ))}
          </div>
          {model.extras && model.extras.length>0 && <div style={{marginTop:9, padding:'7px 9px', border:`2px solid ${C.line2}`, background:C.bg3}}>
            <div style={{fontFamily:F.mono, fontSize:8.5, fontWeight:800, color:C.dg, letterSpacing:'.08em', marginBottom:4}}>MODELLED BUT NOT WIRED · the "too much stuff"</div>
            <div style={{fontFamily:F.mono, fontSize:9, color:C.tx2, lineHeight:1.5}}>{model.extras.join(' · ')}</div>
            <div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, marginTop:4}}>These capabilities live in the .py but have no define-section input — they run on built-in defaults (mostly "off"). Either wire an input or treat as out-of-scope.</div>
          </div>}
          {(()=>{ const wired=model.terms.filter(t=>t.wired).length, tot=model.terms.length;
            return <div style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color: wired===tot?C.gn:C.a4}}>{wired}/{tot} core terms fed by a real input{model.extras&&model.extras.length?` · ${model.extras.length} extra capabilit${model.extras.length===1?'y':'ies'} unwired`:''}</div>; })()}
        </> : <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3}}>Term→input map not authored for this engine — see the SolverIO contract above for its inputs.</div>}
      </Pane>

      {/* ③ LIVE SOLVE */}
      <Pane n="③" title="Live solve">
        <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:8}}>
          {canRun
            ? <Btn kind="accent" sm onClick={doRun}>{busy?'⏳ solving…':'▶ Run live'}</Btn>
            : <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>no shared payload — <button onClick={()=>onNav && onNav((M.solvers.find(s=>s.id===sel)||{}).go||'home')} style={{color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline', fontFamily:F.mono, fontSize:9.5, fontWeight:700}}>run from its tab →</button></span>}
          {result && <Tag c={fromCache?'w':'g'}>{fromCache?'cached solve':'live'}</Tag>}
        </div>
        {err && <div style={{fontFamily:F.mono, fontSize:9.5, color:C.dg, marginBottom:6}}>⚠ {err}</div>}
        {!result ? <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, padding:'10px 0'}}>{canRun?'Run to solve this engine on the committed dataset — status, objective and duals appear here.':'No cached solve yet for this engine.'}</div> : <>
          <KpiRow cols={2}>
            <Blk label="Status" value={status||'—'} tone={status==='Optimal'?'y':'c'}/>
            <Blk label="Runtime" value={run&&run._ms!=null?`${run._ms} ms`:(fromCache?'cached':'—')}/>
          </KpiRow>
          {objLine && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10.5, fontWeight:700, color:C.tx, padding:'6px 9px', border:`2px solid ${C.line2}`, background:C.bg3}}>{objLine}</div>}
          {duals ? <div style={{marginTop:8}}>
            <SubLabel>Shadow prices (duals)</SubLabel>
            <div style={{maxHeight:150, overflow:'auto'}}>{duals.slice(0,10).map((d,i)=>(
              <div key={i} style={{display:'flex', justifyContent:'space-between', alignItems:'center', fontFamily:F.mono, fontSize:9.5, padding:'2px 0', borderBottom:`1px solid ${C.line2}`}}>
                <span style={{color:C.tx2}}>{d.bind?'🔴 ':'⬜ '}{d.k}</span>
                <span style={{fontWeight:700}}>{d.v!=null?`₹${Math.round(d.v)}`:'—'}</span>
              </div>
            ))}</div>
            <div style={{fontFamily:F.mono, fontSize:8, color:C.tx3, marginTop:3}}>valid duals — this is an LP. (MILPs report binding/gap instead.)</div>
          </div> : (ty && !ty.solves && result ? <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>{ty.type==='Simulation'?'Distribution-based — no duals (it is a simulation, not an optimiser).':'Estimator — no duals.'}</div> : (ty && ty.type==='MILP' && result ? <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>MILP — integer vars, so no valid shadow prices; read binding constraints / optimality gap instead.</div> : null))}
        </>}
      </Pane>
    </div>
  );
}

// V2-7 — one-result-one-home. A solver's result table renders ONCE, in the tab
// that owns the decision; the Console shows this one-line KPI + freshness chip
// linking there instead. Homes: profitmix → Production ▸ Profit-Mix · transport →
// Logistics · capital → Finance ▸ Investment decisions. Enforced by model_check's
// `one-result-one-home` rule (each Res* component JSX-mounted at most once, and
// the moved trio never again in console.jsx).
function ResultHomeLink({ solveKey, label, go, goLabel, kpi, onNav }){
  const cached = (typeof getSolveResult==='function') ? getSolveResult(solveKey) : null;
  const r = cached && cached.result;
  const { stale, ranAt } = (typeof useStale==='function') ? useStale(solveKey) : { stale:false, ranAt:null };
  const line = r ? kpi(r) : null;
  return (
    <Card icon="🏠" title={label} badge={r ? (stale?'cached · stale':'cached') : 'not run yet'} badgeTone={r ? (stale?'r':'g') : undefined}
      info={{ what:`One-line KPI only — the full result, explainer and inputs live in ${goLabel} (one-result-one-home).`, flows:`Console → ${goLabel}.` }}
      dev={{ comp:'ResultHomeLink', props:`getSolveResult('${solveKey}')`, note:'V2-7 — console is a control tower, not a second render of the decision.' }}>
      {line
        ? <div style={{fontFamily:F.mono, fontSize:11, fontWeight:700, color:C.tx, padding:'6px 9px', border:`2px solid ${C.line2}`, background:C.bg3}}>{line}{ranAt ? <span style={{fontWeight:400, color:C.tx3}}>  · ran {ranAt}</span> : null}</div>
        : <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3}}>No cached solve yet — run it from its home tab.</div>}
      <div style={{marginTop:9}}>
        <Btn kind="accent" sm onClick={()=>onNav && onNav(go)}>open {goLabel} →</Btn>
      </div>
    </Card>
  );
}
// result sections — hero example fully built per group + section grid
function ConsoleResults({ solver, sections, onNav }) {
  const fmtL = n=>`₹${((+n||0)/1e5).toFixed(1)}L`;
  return (
    <div>
      {solver==='procurement'  && <ResProcure/>}
      {solver==='production'  && <ResProduce/>}
      {solver==='profitmix'   && <ResultHomeLink onNav={onNav} solveKey="profitmix" label="Profit-Mix · lives in Production" go="production" goLabel="Production ▸ Profit-Mix"
        kpi={r=>`max profit ${fmtL(r.total_profit)} · ${(r.products||[]).filter(p=>p.quantity>0.5).length}/${(r.products||[]).length} SKUs make`}/>}
      {solver==='transport'&& <ResultHomeLink onNav={onNav} solveKey="transport" label="Transport · lives in Logistics" go="logistics" goLabel="Logistics"
        kpi={r=>`min freight ${fmtL(r.total_cost)} · consolidation saves ${fmtL(r.consolidation_saving)}`}/>}
      {solver==='montecarlo'&& <ResRisk/>}
      {solver==='capital'  && <ResultHomeLink onNav={onNav} solveKey="capital" label="Capital Budget · lives in Finance" go="finance" goLabel="Finance ▸ Investment decisions"
        kpi={r=>`fund ${(r.selected||[]).length} proposals · CapEx ₹${((r.total_capex||0)/1e7).toFixed(2)}Cr · NPV ${fmtL(r.total_npv)}`}/>}
      {solver==='sop'      && <ResSOP/>}
    </div>
  );
}

// Console procurement: run the MILP on the primary finished SKU + shared BOM,
// driven by the keystone demand series. (Console isn't item-scoped, so it shows
// the representative item's joint PO plan.)
function consoleProcurePayload(){
  const fin = M.products.filter(p=>p.cat==='Finished');
  const p = fin[0] || {}; const sku = p.sku || 'TPA-4471';
  const dem = getItemDemand(sku, 12);
  const _pl = (typeof appStore!=='undefined') ? (appStore.get().planning||{}) : {};
  return { products:[{ name:sku, demand:dem, capacity:Math.max(400, Math.ceil(Math.max(...dem)*1.5)),
    variable_cost:(typeof effUnitCost==='function'?effUnitCost(p):(p.cost||1190)), sell_price:p.price||1850, yield_pct:(typeof skuYield==='function'?skuYield(p,0.97):(p.yield||0.97)), parts:bomParts(30) }],   // G-I1 measured ?? seed · V2-2 derived cost
    params:{ periods:12, time_grain:'monthly',
      // G-N1 — open/in-transit POs net the buy (procurement.py T6 locked_pos).
      horizon_start_date:_pl.startDate,
      locked_pos:(typeof scheduledReceiptsLocked==='function') ? scheduledReceiptsLocked() : [] } };
}
function ResProcure() {
  const proc = useSolve('/api/solve/procurement', consoleProcurePayload);
  const r = proc.result;
  const poRows = r ? [].concat(...(r.materials||[]).map((m,mi)=>(m.purchase_orders||[]).map((po,pi)=>
    [`PO-${String(mi+1).padStart(2,'0')}${pi+1}`, m.name, m.supplier_name||'—',
     po.quantity.toLocaleString('en-IN'), `P${po.period}`, `₹${(po.cost/1000).toFixed(0)}K`]))) : null;
  const pols = r ? (r.inventory_policies||[]) : null;
  return (
    <Grid cols={2}>
      <Card icon="📦" title="Procurement MILP Results" badge={r?`₹${(r.total_cost/1e7).toFixed(2)} Cr`:'₹3.12 Cr'} badgeTone="y"
        right={r ? <Provenance kind="solved" asOf={proc.ranAt}/> : <Btn kind="accent" sm onClick={()=>proc.run().catch(()=>{})}>{proc.solving?'⏳ Planning…':'📦 Run MILP'}</Btn>}
        info={{ what:'Optimal PO plan minimising inventory + ordering cost.', flows:'POs → Sourcing release plan.' }} span={2}
        dev={{ comp:'ProcurementResults', props:'solve.procurement' }}>
        {proc.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>procurement error: {proc.error}</div>}
        <DataTable dense cols={['PO','Part','Supplier','Qty','Release','Value']} align={['left','left','left','right','left','right']}
          rows={r ? (poRows.length?poRows:[['—','no orders in horizon','—','—','—','—']])
                  : M.poRegister.map(p=>[p.po, p.part, p.sup, p.qty.toLocaleString('en-IN'), p.wk, `₹${(p.val/1000).toFixed(0)}K`])}
          foot={r ? ['TOTAL','','','—','',`₹${(r.total_cost/1e5).toFixed(1)}L`] : ['TOTAL','','','—','','₹11.4L']}/>
      </Card>
      <Card icon="📋" title="Reorder Policy (s,S) / (R,Q)" badge={pols?`${pols.length} parts · solved`:'per part'} badgeTone={pols?'g':undefined} span={2}
        right={pols ? <Provenance kind="solved" asOf={proc.ranAt}/> : undefined}
        info={{ what:'Computed reorder point & order-up-to / qty.', flows:'Policy → MRP.' }}
        dev={{ comp:'ReorderPolicyCard', props:'solve.procurement.policy' }}>
        <DataTable dense cols={['Part','Policy','s (ROP)','S / Q','Review']} align={['left','left','right','right','left']}
          rows={pols ? pols.map(p=>{ const rq=/R,Q/.test(p.recommended_policy||'');
                 return [p.part, p.recommended_policy||'(s,S)',
                   Math.round((rq?p.rq_reorder_point:p.reorder_point_s)||0).toLocaleString('en-IN'),
                   Math.round((rq?p.rq_order_qty:p.order_up_to_S)||0).toLocaleString('en-IN'),
                   rq?`every ${Math.round(p.review_period_periods||0)}p`:'continuous']; })
               : [['RM-STL42','(s,S)','2,400','4,800','continuous'],['RM-BRG18','(R,Q)','—','1,500','weekly'],['CN-SEAL9','(s,S)','1,200','6,000','continuous']]}/>
      </Card>
    </Grid>
  );
}

// Transform the solver's flat gantt [{line,period,quantity,product}] into the
// per-line lane shape the chart draws; colour by the line's overall utilisation.
function GanttChart({ gantt, lines }) {
  let lanes;
  if(gantt){
    const utilOf = {}; (lines||[]).forEach(l=>{ utilOf[l.name]=(l.utilization||0)/100; });
    const byLine = {};
    gantt.forEach(g=>{ (byLine[g.line] = byLine[g.line] || []).push({ s:g.period, d:1, sku:g.product, util:utilOf[g.line]??0.7 }); });
    lanes = Object.keys(byLine).map(line=>({ line, jobs:byLine[line] }));
  } else { lanes = M.gantt; }
  const wk=18;
  return (
    <svg viewBox={`0 0 720 ${Math.max(150, 24+lanes.length*40+10)}`} style={{width:'100%', height:Math.max(150, 24+lanes.length*40+10), display:'block'}}>
      {[...Array(wk)].map((_,i)=>(<line key={i} x1={70+i*36} y1="10" x2={70+i*36} y2={24+lanes.length*40} stroke={C.line2} strokeWidth=".6"/>))}
      {lanes.map((ln,li)=>{ const y=24+li*40;
        return (<g key={li}>
          <text x="8" y={y+16} fontFamily={F.mono} fontSize="9.5" fontWeight="700" fill={C.tx}>{ln.line}</text>
          {ln.jobs.map((j,ji)=>(
            <g key={ji}>
              <rect x={70+j.s*36} y={y} width={j.d*36-3} height="26" fill={j.util>.85?C.ink:j.util>.7?C.ac:C.bg4} stroke={C.line} strokeWidth="1.5"/>
              <text x={70+j.s*36+4} y={y+16} fontFamily={F.mono} fontSize="8" fill={j.util>.85?C.ac:C.tx} fontWeight="700">{String(j.sku).slice(4)}</text>
            </g>
          ))}
        </g>);
      })}
    </svg>
  );
}

// NOTE — productionPayload lives in store.jsx (governed: planning + opts). A no-arg
// duplicate used to live here and, because console.jsx loads AFTER store.jsx in
// index_v2.html, it silently shadowed the governed one for EVERY consumer
// (production.jsx, the runFullLoop production step, the LAB builder) — neutering
// labor-rate/time-phasing/routing. Removed; this card now uses the one governed payload.
function ResProduce() {
  const { planning } = usePlanning();
  const pr = useSolve('/api/solve/production', ()=>productionPayload(planning, productionOptsFromConfig()));
  const r = pr.result;
  return (
    <Grid cols={1}>
      <Card icon="📅" title="Production Schedule · Gantt" badge={r?`${r.lines.length} lines · ${r.periods}p · solved`:'3 lines · 18 wk'} badgeTone="y"
        right={r ? <Provenance kind="solved" asOf={pr.ranAt}/> : <Btn kind="accent" sm onClick={()=>pr.run().catch(()=>{})}>{pr.solving?'⏳ Scheduling…':'📅 Run scheduler'}</Btn>}
        info={{ what:'Sequenced jobs per line over the horizon.', flows:'Schedule → shop-floor execution.' }}
        dev={{ comp:'GanttCard', props:'solve.production.schedule' }}>
        {pr.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>production error: {pr.error}</div>}
        <GanttChart gantt={r?r.gantt:undefined} lines={r?r.lines:undefined}/>
        <div style={{marginTop:6, display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2}}>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ink}}/>util &gt;85%</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ac}}/>70–85%</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.bg4}}/>&lt;70%</span>
        </div>
      </Card>
      <Grid cols={2}>
        <Card icon="📦" title="Product Fulfillment" badge={r?'vs demand · solved':'vs demand'} badgeTone={r?'g':undefined}
          info={{ what:'Met vs unmet demand per SKU.', flows:'Gaps → lost sales.' }}
          dev={{ comp:'FulfillmentCard', props:'solve.production.fulfil' }}>
          <DataTable dense cols={['SKU','Required','Made','Fill']} align={['left','right','right','right']}
            rows={r ? r.products.map(p=>[p.name, p.required.toLocaleString('en-IN'), p.produced.toLocaleString('en-IN'),
                   `${Math.min(100, Math.round(p.produced/Math.max(p.required,1)*100))}%`])
                 : [['TPA-4471','2840','2840','100%'],['TPA-3215','4120','3980','97%'],['TPA-2188','920','840','91%']]}/>
        </Card>
        <Card icon="💤" title="Shutdown Candidates" badge={r?(r.shutdown_recommendations.length?`${r.shutdown_recommendations.length} found`:'none'):'low util'}
          info={{ what:'Lines/shifts worth idling.', flows:'Cost saving option.' }}
          dev={{ comp:'ShutdownCard', props:'solve.production.shutdown' }}>
          {r ? (
            r.shutdown_recommendations.length ? r.shutdown_recommendations.map((s,i)=>(
              <div key={i} style={{padding:'10px', border:`2px solid ${C.line}`, background:C.bg3, marginBottom:6}}>
                <div style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>{s.line||s.name||`Line ${s.line_idx}`}{s.period!=null?` · P${s.period}`:''}</div>
                <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:3}}>{s.type||'low-util'}{s.savings!=null?` · idle saves ₹${(s.savings/1e5).toFixed(1)}L`:''}</div>
              </div>
            )) : (()=>{ const low=[...r.lines].sort((a,b)=>a.utilization-b.utilization)[0];
              return <div style={{padding:'10px', border:`2px solid ${C.gn}`, background:C.bg3, fontFamily:F.mono, fontSize:11, color:C.gn}}>✓ No shutdown beats keep-running below the {r.shutdown_threshold_pct}% threshold. Lowest line: {low?low.name:'—'} at {low?low.utilization:0}% util.</div>;
            })()
          ) : (
            <div style={{padding:'10px', border:`2px solid ${C.line}`, background:C.bg3}}>
              <div style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>LINE-03 · Shift B</div>
              <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:3}}>55% util in W01–W03 · idle saves ₹2.1L</div>
            </div>
          )}
        </Card>
      </Grid>
    </Grid>
  );
}

// Build the profit-mix payload from the finished-goods master. V2-1 (blueprint Q3):
// capacity is now the REAL production architecture — profitmix.py's line pool
// (lines[] with avail_hrs_per_week × OEE, per-SKU cycle minutes, routing-pinned
// eligibility) built from M.lines — replacing `shared_capacity = demandHours×0.82`,
// which was CIRCULAR (capacity scaled WITH demand; 0.82 was a magic OEE stand-in,
// so "Shared Capacity" always bound at the same place no matter the factory).
// BASIS: master `p.demand` is ANNUAL (MPS weekly ≈ demand/52 for every seeded SKU),
// so planning_horizon_months:12 — the solver scales weekly line hours to the same
// 12-month window the demand ceiling spans. With honest capacity the lines may be
// SLACK at current volumes; then the binding duals are the demand ceilings ("the
// market, not the factory, caps profit") — that is the truthful answer, not a bug.
// CRITICAL wire (audit fix): committed FIRM MTO orders (the M.orders order book shown
// in Products) are a production FLOOR the profit-mix MUST satisfy — profitmix.py reads
// it as min_quantity (its else/mts branch: floor = min_quantity). Before this the LP
// ignored firm orders and could drop a contracted SKU to zero. Firm-only (planned
// orders are not a commitment); all firm totals sit below each SKU's max_demand, so the
// floor stays feasible.
function _firmOrderFloor(sku){
  const o = (window.M && M.orders || []).filter(x=>x.sku===sku && x.status==='firm');
  return o.length ? o.reduce((a,b)=>a+(Number(b.qty)||0),0) : 0;
}
function profitmixPayload(){
  const fin = M.products.filter(p=>p.cat==='Finished');
  // shelf_life must be in WEEKS here (profitmix.py compares shelf_weeks→months vs the
  // horizon); p.shelf is in DAYS, so convert — passing raw days made the expiry penalty
  // never bite (365 "weeks" ≫ horizon). salvage_rate + yield_pct are real levers too.
  const prods = fin.map(p=>({ name:p.sku, sell_price:p.price,
    variable_cost:(typeof effUnitCost==='function'?effUnitCost(p):p.cost),   // V2-2 — derived cost chain (≡ p.cost at seed)
    max_demand:p.demand,
    max_quantity:p.demand,                  // V2-1 — label the demand ceiling ("Max prod:") so a binding
                                            // ceiling is PRICED in shadow_prices, not silently absorbed
    mape_pct:Number(p.mape)||15,            // V2-1 — real per-SKU forecast error, not the solver's 15% default
    cycle_time:(Number(p.cycle)||0)/60,     // HOURS — legacy fallback only; the LP optimises on per-line MINUTES below
    min_quantity:_firmOrderFloor(p.sku),    // firm MTO order book → production floor
    shelf_life:Math.max(1, Math.round((Number(p.shelf)||365)/7)),
    yield_pct:(typeof skuYield==='function'?skuYield(p,0.95):(p.yield||0.95)), salvage_rate:Number(p.salvage)||0.8 }));   // G-I1 measured ?? seed
  // V2-1 — real line pool: same effective-routing rule as productionPayload
  // (governed config.prodRouting override → master p.line / p.cycle). Weekly hours
  // = workDays × hrsPerShift × shifts; profitmix.py derates by OEE and scales to the horizon.
  const _store = (typeof appStore!=='undefined') ? appStore.get() : {};
  const _cfg = _store.config||{};
  const _route = _cfg.prodRouting||{};
  const _pl = _store.planning||{};
  const _wdays = Math.max(1, Number(_pl.workDaysPerWeek)||6);
  const _hps = Math.max(1, Number(_pl.hrsPerShift)||8);     // governed (Setup ▸ Net Hrs/Shift)
  const _eff = p=>{ const ov=_route[p.sku]||{};
    return { line: ov.line||p.line,
             cyc: (ov.cycle!=null && ov.cycle!=='') ? Number(ov.cycle) : p.cycle }; };
  const lines = (M.lines||[]).map(l=>{
    const eligible_skus=[], cycle_time_by_sku_min={};
    fin.forEach((p,k)=>{ const e=_eff(p);
      if(e.line===l.id){ eligible_skus.push(k); cycle_time_by_sku_min[k]=Number(e.cyc)||0; } });
    return { id:l.id, name:l.name, oee:Number(l.oee)||1,
             avail_hrs_per_week:_wdays*_hps*(Number(l.shifts)||1),
             eligible_skus, cycle_time_by_sku_min };
  });
  // optional ₹ working-capital budget (Σ variable_cost·q) and warehouse storage slots (Σ q)
  // — profitmix.py treats 0 as UNBOUNDED, so the seed-0 default leaves the mix unconstrained.
  const constraints = { budget: Number(_cfg.pmBudget)||0, warehouse: Number(_cfg.pmWarehouse)||0 };
  return { products:prods, lines, constraints, planning_horizon_months:12 };
}
// ── D1 · GLASS-BOX DECISION EXPLAINER ────────────────────────────────────────
// The wedge: incumbents are black boxes. We read the REAL optimiser duals — the
// constraint shadow prices, slacks and reduced costs PuLP hands back — and rewrite
// them in plain English a non-modeller can act on: what's capping your profit,
// what one more unit is worth, and why each SKU made or missed the cut. Every
// figure here is a solved dual/slack/reduced-cost; this layer only TRANSLATES —
// it invents no numbers (the "no faking" contract).
function _diMoney(n){ const a=Math.abs(+n||0);
  return a>=1e5?`₹${(a/1e5).toFixed(1)}L`:a>=1e3?`₹${(a/1e3).toFixed(0)}K`:`₹${Math.round(a)}`; }

// friendly resource name + unit-noun, parsed from the solver's constraint label
function _diResource(name){
  const n=String(name||'');
  if(/^Line hrs:/i.test(n))        return { who:n.replace(/^Line hrs:\s*/i,'').trim(), unit:'hour', kind:'capacity' };
  if(/Shared Capacity/i.test(n))   return { who:'your shared machine line', unit:'machine-hour', kind:'capacity' };
  if(/Org Labor Hours/i.test(n))   return { who:'your people / labour hours', unit:'labour hour', kind:'labour' };
  if(/^Material:/i.test(n))        return { who:n.replace(/^Material:\s*/i,'').trim()+' stock', unit:'unit', kind:'material' };
  if(/Budget/i.test(n))            return { who:'your cash budget', unit:'rupee', kind:'budget' };
  if(/Warehouse/i.test(n))         return { who:'warehouse space', unit:'storage slot', kind:'space' };
  if(/^Max prod:/i.test(n))        return { who:n.replace(/^Max prod:\s*/i,'').trim(), unit:'order', kind:'demand' };
  if(/^(Min prod|Floor|MTO)/i.test(n)) return { who:n.replace(/^[^:]*:\s*/,'').trim()+' minimum', unit:'unit', kind:'floor' };
  return { who:n, unit:'unit', kind:'other' };
}

// one constraint dual → a plain-English verdict {tone,tag,icon,head,plain,action}
function explainConstraint(s){
  const f=_diResource(s.constraint), v=Math.abs(+s.shadow_price||0);
  if(s.binding && v>0){
    let action;
    if(f.kind==='demand')
      action=`You're already making and selling every ${f.who} you possibly can — demand is the ceiling, not your factory. Each extra order you could win would add about ${_diMoney(v)} of profit, so this is where sales & marketing effort pays back.`;
    else if(f.kind==='budget')
      action=`Your cash is fully spent. Freeing up one more rupee to invest returns about ₹${v.toFixed(2)} of profit — so this money is working hard; more of it would help.`;
    else if(f.kind==='floor')
      action=`You're forced to make this minimum even though it's not the most profitable use of the line. Dropping the requirement by one ${f.unit} would free up about ${_diMoney(v)} of profit elsewhere.`;
    else
      action=`This is your #1 bottleneck. One more ${f.unit} of ${f.who} is worth about ${_diMoney(v)} in extra profit — the best place to add overtime, speed up a changeover, or invest, and the most costly thing to lose.`;
    return { tone:C.dg, tag:'BOTTLENECK', icon:'🔴', head:`${f.who} — maxed out`,
             plain:`There's no spare left here. This is one of the things capping your profit right now.`, action,
             kind:f.kind, who:f.who, unit:f.unit, sp:v, cname:s.constraint };
  }
  const slack = s.slack!=null ? Math.abs(+s.slack) : null;
  return { tone:C.gn, tag:'SPARE', icon:'🟢', head:`${f.who} — room to spare`,
           plain: slack!=null ? `You're using less than you have — about ${Math.round(slack)} ${f.unit}${slack>=2?'s':''} sitting idle.` : `Not a limiting factor right now.`,
           action:`This isn't what's holding you back, so spending money to add more of it won't raise profit — leave it until a real bottleneck frees up.`,
           kind:f.kind, who:f.who, unit:f.unit, sp:v, cname:s.constraint };
}

// reduced cost → why a SKU made / missed the cut
function explainProduct(rc){
  const dj=Math.abs(+rc.reduced_cost||0);
  if(rc.in_solution){
    if(dj<=0.01) return null;
    return { tone:C.gn, icon:'✅', head:`${rc.variable} earns its place`,
      plain:`It's worth making. Its margin could fall by up to ₹${dj.toFixed(0)}/unit before it'd stop being worth the line time.` };
  }
  return { tone:C.tx3, icon:'⬜', head:`${rc.variable} left out`,
    plain:`It isn't profitable enough per scarce hour to earn a slot. Lift its margin by about ₹${dj.toFixed(0)}/unit — raise the price or cut the cost — and it would make the cut.` };
}

// ── D1+ · SANDBOXED, TESTABLE RECOMMENDATION ─────────────────────────────────
// A shadow price is a LINEAR estimate — true only until the next constraint binds.
// Incumbents assert it; we PROVE it. "🧪 Prove it" re-solves the SAME profit-mix
// model with the one perturbation applied (a stateless POST — it touches NO live
// state, the committed plan is never mutated) and shows the ACTUAL Δprofit vs the
// dual's prediction, including where the linear estimate OVERSTATES the gain
// because a second limit kicks in. Only THEN, on an explicit click, does "Apply"
// write the change to the working set (price only — capacity is a capital call,
// routed not auto-written). Sandboxed prove-it → explicit apply, never silent.
async function _solveProfit(payload){ return await apiPost('/api/solve/profitmix', payload); }

// the ONE explicit write: set a finished-good's sell price on the working set
// (M.products is the live master data every payload derives from), flag the
// dependent solves stale so the user re-solves, and audit it on the event log
// (so the D2 value ledger counts a recommendation that was actually acted on).
function _applyPrice(sku, price){
  const p=((window.M&&window.M.products)||[]).find(x=>x.sku===sku);
  if(!p) return;
  p.price=Math.round(price);
  if(typeof markStale==='function') markStale('config');     // profitmix/capital depend on config
  if(typeof logEvent==='function') logEvent('rec_apply', sku, { field:'sell_price', to:p.price, source:'glass-box crossover' });
}

// honesty verdict comparing the solver's actual Δ to the dual's linear prediction
function _recVerdict(predicted, actual){
  if(predicted==null){                       // crossover / "does it enter" tests
    return { tone:C.gn, txt:'' };
  }
  const a=+actual||0, p=+predicted||0;
  if(p<=0) return { tone:C.tx3, txt:'No measurable gain — another limit dominates.' };
  const ratio = a/p;
  if(a<=0)        return { tone:C.dg, txt:`⚠ The estimate doesn't hold here — re-solving delivered ~₹0. Another constraint absorbs the extra capacity, so don't invest on the shadow price alone.` };
  if(ratio>=0.9)  return { tone:C.gn, txt:`✓ Confirmed — the full re-solve delivers ${_diMoney(a)}, matching the ${_diMoney(p)} estimate. The recommendation holds at this size.` };
  return { tone:C.a4, txt:`⚠ The shadow price OVERSTATES it: predicted ${_diMoney(p)}, but only ${_diMoney(a)} (${Math.round(ratio*100)}%) actually materialises — a second limit binds partway through. Size any investment to the proven figure, not the headline.` };
}

// one testable recommendation: a "🧪 Prove it" button → real re-solve → verdict,
// then an explicit Apply (when the change maps to one editable input).
function RecTest({ build, predicted, predLabel, enterSku, apply, applyLabel, applied }){
  const [busy,setBusy]=useState(false);
  const [out,setOut]=useState(null);     // {actual, entered, err}
  const [done,setDone]=useState(false);
  const run=async()=>{
    setBusy(true); setOut(null);
    try{
      const { payload, baseProfit } = build();
      const res = await _solveProfit(payload);
      const actual = (+res.total_profit||0) - (+baseProfit||0);
      const entered = enterSku ? ((res.products||[]).find(p=>p.name===enterSku)||{}).quantity>0.5 : null;
      setOut({ actual, entered });
    }catch(e){ setOut({ err:e.message||String(e) }); }
    finally{ setBusy(false); }
  };
  const verdict = out && !out.err ? _recVerdict(predicted, out.actual) : null;
  return (
    <div style={{margin:'-3px 0 9px 25px', padding:'7px 10px', borderLeft:`2px dashed ${C.line2}`, background:C.bg2}}>
      <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
        <Btn sm onClick={run} disabled={busy}>{busy?'⏳ re-solving…':'🧪 Prove it'}</Btn>
        <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>
          {predLabel || (predicted!=null ? `shadow-price says ≈ ${_diMoney(predicted)}` : 'sandboxed re-solve — no live state touched')}
        </span>
      </div>
      {out && out.err && <div style={{marginTop:6, fontFamily:F.mono, fontSize:10, color:C.dg}}>re-solve failed: {out.err}</div>}
      {out && !out.err && (
        <div style={{marginTop:6}}>
          {enterSku
            ? <div style={{fontFamily:F.body, fontSize:11.5, color:out.entered?C.gn:C.tx3, fontWeight:600}}>
                {out.entered ? `✓ Proven — at that price ${enterSku} wins a slot in the re-solved plan.`
                             : `✗ Even at that price ${enterSku} stays out — another limit (demand or a tighter SKU) keeps it off the line.`}
              </div>
            : <div style={{fontFamily:F.body, fontSize:11.5, color:verdict.tone, fontWeight:600}}>{verdict.txt}</div>}
          {apply && (out.entered!==false) && !done && (
            <div style={{marginTop:7}}>
              <Btn sm kind="accent" onClick={()=>{ apply(); setDone(true); }}>{applyLabel||'Apply to working set →'}</Btn>
              <span style={{marginLeft:8, fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>explicit — writes the input, then re-solve to ripple it through</span>
            </div>
          )}
          {(done||applied) && <div style={{marginTop:6, fontFamily:F.mono, fontSize:9.5, color:C.gn}}>✓ applied to the working set · re-solve the mix to see it ripple through</div>}
        </div>
      )}
    </div>
  );
}

function DiRow({ icon, tone, head, plain, action, tag }){
  return (
    <div style={{display:'flex', gap:10, padding:'9px 11px', border:`1.5px solid ${C.line2}`, borderLeft:`4px solid ${tone}`, background:C.bg3, marginBottom:7}}>
      <span style={{fontSize:15, lineHeight:1.2}}>{icon}</span>
      <div style={{minWidth:0, flex:1}}>
        <div style={{display:'flex', alignItems:'center', gap:8}}>
          <span style={{fontFamily:F.disp, fontSize:12.5, fontWeight:900, color:C.tx}}>{head}</span>
          {tag && <span style={{fontFamily:F.mono, fontSize:8.5, fontWeight:800, letterSpacing:'.08em', color:tone, border:`1.5px solid ${tone}`, padding:'1px 5px'}}>{tag}</span>}
        </div>
        <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, marginTop:3, lineHeight:1.45}}>{plain}</div>
        {action && <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx, marginTop:4, lineHeight:1.45, fontWeight:600}}>→ {action}</div>}
      </div>
    </div>
  );
}

function DecisionExplainer({ r }){
  if(!r) return (
    <Card icon="🔍" title="Why this plan? — plain-English explainer" badge="run to explain" span={2}
      info={{ what:'Translates the optimiser’s shadow prices & reduced costs into plain language — your bottleneck, what one more unit is worth, and why each SKU made or missed the cut.', flows:'Reads the profit-mix solve. No new numbers — only translation of the duals.' }}
      dev={{ comp:'DecisionExplainer (D1)', props:'solve.profit.{shadow_prices,reduced_costs,crossover}' }}>
      <div style={{fontFamily:F.body, fontSize:12, color:C.tx3, padding:'10px 2px'}}>Optimize the mix above, then this reads the solver’s own reasoning back to you in plain English.</div>
    </Card>
  );
  const cons=(r.shadow_prices||[]).map(explainConstraint);
  const bottlenecks=cons.filter(c=>c.tag==='BOTTLENECK');
  const spare=cons.filter(c=>c.tag==='SPARE');
  const prods=(r.reduced_costs||[]).map(explainProduct).filter(Boolean);
  const dropped=prods.filter(p=>p.icon==='⬜');
  const cross=(r.crossover_analysis||r.crossover||[]);   // solver emits crossover_analysis
  // D1+ · build a sandboxed test spec for a perturbable bottleneck (else null → no test offered)
  function specFor(c){
    const b0=profitmixPayload();
    if(c.kind==='capacity' && b0.lines && b0.lines.length){
      // V2-1 — capacity is the per-line hours pool now: bump the NAMED binding line's
      // weekly hours +5% (fall back to all lines if the name doesn't match). The dual is
      // per machine-HOUR over the horizon, so ΔRHS = 0.05 × avail × weeks × OEE.
      const nm=String(c.cname||'').replace(/^Line hrs:\s*/i,'').trim();
      const hit=b0.lines.some(l=>l.name===nm);
      const m=Number(b0.planning_horizon_months)||0;
      const weeks=Math.max(1, m>0 ? Math.round(30*m/7) : 4.33);   // mirrors profitmix.py's weeks formula
      const dH=b0.lines.filter(l=>!hit||l.name===nm)
        .reduce((s,l)=>s + l.avail_hrs_per_week*0.05*weeks*(Number(l.oee)||1), 0);
      if(dH<=0) return null;
      return { predicted:c.sp*dH, predLabel:`test +${Math.round(dH).toLocaleString('en-IN')} machine-hours on ${hit?nm:'all lines'} · estimate ≈ ${_diMoney(c.sp*dH)}`,
        build:()=>({ payload:{...b0, lines:b0.lines.map(l=>(!hit||l.name===nm)?{...l, avail_hrs_per_week:l.avail_hrs_per_week*1.05}:l)}, baseProfit:r.total_profit }) };
    }
    if(c.kind==='demand'){
      const prod=(b0.products||[]).find(p=>p.name===c.who); if(!prod) return null;
      const dU=Math.max(1,Math.round((prod.max_demand||0)*0.05));
      return { predicted:c.sp*dU, predLabel:`test +${dU.toLocaleString('en-IN')} units of demand · estimate ≈ ${_diMoney(c.sp*dU)}`,
        build:()=>({ payload:{...b0, products:b0.products.map(p=>p.name===c.who?{...p,max_demand:(p.max_demand||0)+dU}:p)}, baseProfit:r.total_profit }) };
    }
    return null;
  }
  const heroWho=bottlenecks[0] ? bottlenecks[0].head.replace(/ —.*/,'') : null;
  return (
    <Card icon="🔍" title="Why this plan? — plain-English explainer" badge={`${bottlenecks.length} bottleneck${bottlenecks.length===1?'':'s'}`} badgeTone={bottlenecks.length?'r':'g'} span={2}
      right={<Provenance kind="solved" note="constraint duals"/>}
      info={{ what:'Translates the optimiser’s shadow prices & reduced costs into plain language — your bottleneck, what one more unit is worth, and why each SKU made or missed the cut.', flows:'Reads the profit-mix solve. No new numbers — only translation of the duals.' }}
      dev={{ comp:'DecisionExplainer (D1)', props:'solve.profit.{shadow_prices,reduced_costs,crossover}' }}>

      <div style={{border:`2px solid ${C.line}`, background:C.bg2, padding:'10px 12px', marginBottom:12}}>
        <div style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.12em', color:C.tx3, marginBottom:4}}>IN PLAIN TERMS</div>
        <div style={{fontFamily:F.body, fontSize:12.5, color:C.tx, lineHeight:1.5, fontWeight:600}}>
          {heroWho
            ? <>The optimiser made every SKU compete for scarce capacity. <b>{heroWho}</b> is the main thing capping your profit — relieve it first. Everything below is the optimiser’s own maths, in words.</>
            : <>Nothing is binding — you have spare capacity everywhere, so the plan simply makes whatever sells at a profit. No bottleneck to relieve.</>}
        </div>
      </div>

      {bottlenecks.length>0 && <>
        <SubLabel>What’s holding profit back (relieve these first) · 🧪 prove each before you spend</SubLabel>
        {bottlenecks.map((c,i)=>{ const spec=specFor(c); return (
          <React.Fragment key={'b'+i}>
            <DiRow {...c}/>
            {spec && <RecTest build={spec.build} predicted={spec.predicted} predLabel={spec.predLabel}/>}
          </React.Fragment>
        ); })}
      </>}

      {dropped.length>0 && <>
        <div style={{marginTop:8}}><SubLabel>Why some SKUs didn’t make the plan</SubLabel></div>
        {dropped.map((c,i)=><DiRow key={'d'+i} {...c}/>)}
      </>}

      {cross.length>0 && <>
        <div style={{marginTop:8}}><SubLabel>What it would take to bring a dropped SKU back · 🧪 prove it, then apply</SubLabel></div>
        {cross.map((c,i)=>(
          <React.Fragment key={'c'+i}>
            <DiRow icon="💡" tone={C.a4} head={`${c.product} → raise price to ${_diMoney(c.crossover_price)}`}
              plain={`Lift ${c.product}’s price to about ${_diMoney(c.crossover_price)} — a ${_diMoney(c.price_increase_needed)} (${c.price_increase_pct}%) bump — and it earns enough per hour to win a slot back in the plan.`}/>
            <RecTest enterSku={c.product}
              build={()=>{ const b0=profitmixPayload(); return { payload:{...b0, products:b0.products.map(p=>p.name===c.product?{...p,sell_price:c.crossover_price}:p)}, baseProfit:r.total_profit }; }}
              apply={()=>_applyPrice(c.product, c.crossover_price)} applyLabel={`Apply ₹${Math.round(c.crossover_price).toLocaleString('en-IN')} price →`}/>
          </React.Fragment>
        ))}
      </>}

      {spare.length>0 && <>
        <div style={{marginTop:8}}><SubLabel>Where you have room to spare (don’t invest here)</SubLabel></div>
        {spare.map((c,i)=><DiRow key={'s'+i} {...c}/>)}
      </>}

      <div style={{marginTop:10, fontFamily:F.mono, fontSize:9.5, color:C.tx3, lineHeight:1.5}}>
        Every figure above is a solved value from the optimisation — shadow prices (₹ per extra unit of a limit) and reduced costs (₹ a dropped SKU’s margin must improve). Nothing here is hand-entered.
      </div>
    </Card>
  );
}

// ── G-C1 · GLASS-BOX EXPLAINERS for the OTHER solvers ────────────────────────
// The same wedge as DecisionExplainer, extended past profit-mix to the line-capacity
// dual LP (linecap), the transport min-cost flow, the capital knapsack and the
// Monte-Carlo CVaR tail. Each returns an array of plain-English DiRow specs grounded
// ONLY in the solver's own returned numbers (shadow prices / NPVs / tail costs) — it
// invents no figures (the "no faking" contract). Top-level so plan.jsx (linecap card)
// and the boot probe can call them.
function explainLinecap(r){
  if(!r || !Array.isArray(r.lines)) return [];
  const rows=[]; const unmet=+r.unmet_demand||0;
  const nm=(l)=> l.line || l.line_id || l.name || l.id;
  const isBind=(l)=> l.binding || Math.abs(+l.shadow_price||0)>0.0001;
  const binding=r.lines.filter(isBind).sort((a,b)=>Math.abs(+b.shadow_price||0)-Math.abs(+a.shadow_price||0));
  const slack=r.lines.filter(l=>!isBind(l));
  binding.forEach((l,i)=>{ const v=Math.abs(+l.shadow_price||0);
    rows.push({ tone:C.dg, icon:'🔴', tag:'BOTTLENECK', head:`${nm(l)} — capacity maxed (${l.util||0}% util)`,
      plain:`This line has no spare hours left at the current plan.${(i===0&&unmet>0)?` About ${Math.round(unmet).toLocaleString('en-IN')} units of demand go unmet across the binding lines.`:''}`,
      action:`One more unit of capacity on ${nm(l)} is worth about ${_diMoney(v)} — the best place to add a shift, speed a changeover or invest, and the most costly to lose.` });
  });
  slack.forEach(l=>{ const idle=+l.slack||0;
    rows.push({ tone:C.gn, icon:'🟢', tag:'SPARE', head:`${nm(l)} — room to spare`,
      plain:`This line isn't the constraint${idle>0?` — about ${Math.round(idle).toLocaleString('en-IN')} units of capacity sit idle`:''}.`,
      action:`Adding capacity here won't lift output until it actually binds; leave it until a real bottleneck frees up.` });
  });
  return rows;
}
function explainTransport(r){
  if(!r) return [];
  const rows=[]; const ships=(r.shipments||[]).filter(s=>s.recommended&&s.recommended.label);
  ships.slice().sort((a,b)=>((b.recommended&&b.recommended.total_cost)||0)-((a.recommended&&a.recommended.total_cost)||0)).slice(0,4).forEach(s=>{
    const rec=s.recommended;
    rows.push({ tone:C.ink, icon:'🚛', head:`${s.name} → ${rec.label}`,
      plain:`For ${((s.weight_kg||0)/1000).toFixed(1)} t on this lane, ${rec.label} is the cheapest mode the optimiser found — about ${_diMoney(rec.total_cost)}.` });
  });
  const cons=(r.consolidation||[]).filter(c=>c.recommend_consolidate);
  if((r.consolidation_saving||0)>0 && cons.length)
    rows.push({ tone:C.gn, icon:'🟢', tag:'SAVING', head:`Consolidate ${cons.length} lane${cons.length>1?'s':''} — save ${_diMoney(r.consolidation_saving)}`,
      plain:`Merging part-loads into full trucks cuts ${_diMoney(r.consolidation_saving)}: ${cons.map(c=>`${c.lane} (${c.n_shipments}× ${c.individual_mode}→${c.consolidated_mode})`).join(', ')}.`,
      action:`Book the consolidated trucks — same goods, fewer trips.` });
  else
    rows.push({ tone:C.tx3, icon:'⬜', head:'No consolidation gain yet',
      plain:`No lane reaches a full truckload at current volumes, so part-load stays cheapest — nothing to merge.` });
  return rows;
}
function explainCapital(r){
  if(!r) return [];
  const rows=[]; const wacc=(r.params&&r.params.wacc!=null)?r.params.wacc*100:null;
  (r.selected||[]).forEach(s=>{
    rows.push({ tone:C.gn, icon:'✅', tag:'FUND', head:`${s.name} — fund it`,
      plain:`It clears the cost-of-capital hurdle${wacc!=null?` (${wacc.toFixed(1)}% WACC)`:''}: NPV ${_diMoney(s.npv)}${s.irr!=null?`, IRR ${s.irr}%`:''} — it earns more than the money costs.` });
  });
  (r.rejected||[]).forEach(s=>{ const npv=+s.npv||0;
    rows.push({ tone: npv>0?C.a4:C.tx3, icon: npv>0?'💡':'⬜', tag:'DEFER', head:`${s.name} — defer`,
      plain: npv>0
        ? `It IS value-creating (NPV ${_diMoney(npv)}) but the budget can't fit everything — it loses the knapsack to picks that return more per rupee. Fund it when the budget grows.`
        : `At this cost of capital it doesn't pay back (NPV ${_diMoney(npv)}) — don't fund it as-is.` });
  });
  if(r.total_capex!=null && r.budget!=null){
    const used=+r.total_capex, b=+r.budget;
    const util=(r.budget_utilization!=null)?+r.budget_utilization:(b>0?used/b*100:0);
    const dual=+r.budget_shadow_price||0;
    const binds = dual>0 || util>=99.5;
    rows.push({ tone: binds?C.dg:C.tx3, icon: binds?'🔴':'🟢', tag: binds?'BUDGET BINDS':'BUDGET SLACK',
      head:`Budget ${_diMoney(used)} of ${_diMoney(b)} used (${util.toFixed(0)}%)`,
      plain: binds?`The capital budget is the binding constraint${dual>0?` (dual ₹${dual} of NPV per extra rupee)`:''} — more budget would let a deferred positive-NPV project in.`
                  :`The budget isn't the limiter — every project worth funding fits inside it.` });
  }
  return rows;
}
function explainCvar(r){
  if(!r) return [];
  const rows=[]; const L=n=>_diMoney(n);
  const typical=(r.p50!=null)?r.p50:r.avg_cost;
  rows.push({ tone:C.ink, icon:'🎲', head:`Typical cost ${L(typical)} — but plan for the tail`,
    plain:`Across ${r.n_runs||'the'} simulated futures${r.policy_simulated?` (on the ${r.policy_simulated} plan)`:''}, a normal outcome costs about ${L(typical)}.` });
  if(r.cvar95!=null) rows.push({ tone:C.dg, icon:'🔴', tag:'TAIL RISK', head:`Worst-5% average ${L(r.cvar95)} (CVaR 95%)`,
    plain:`In the worst 1-in-20 outcomes, cost averages ${L(r.cvar95)} — that's the exposure to hedge or buffer against, not the average.`,
    action:`Size safety stock / hedging to survive the ${L(r.cvar95)} tail, not the ${L(r.avg_cost)} mean.` });
  if(r.var95!=null) rows.push({ tone:C.a4, icon:'📈', head:`95% of the time, under ${L(r.var95)} (VaR)`,
    plain:`You can be 95% confident cost won't exceed ${L(r.var95)}.` });
  if(r.fragility!=null){ const fat=r.fragility>1.2;
    rows.push({ tone: fat?C.dg:C.gn, icon: fat?'⚠':'🟢', head:`Fragility ${r.fragility}× ${fat?'— fat tail':'— well-behaved'}`,
      plain: fat?`The downside is disproportionately heavy (VaR is ${r.fragility}× the mean) — a few bad scenarios dominate the risk.`
                :`The cost distribution is well-behaved — no disproportionate tail.` }); }
  if(r.avg_fill!=null) rows.push({ tone:(r.min_fill!=null&&r.min_fill<90)?C.a4:C.gn, icon:'📦', head:`Service: avg fill ${r.avg_fill}%${r.min_fill!=null?`, worst ${r.min_fill}%`:''}`,
    plain:`On average you serve ${r.avg_fill}% of demand${r.min_fill!=null?`, dropping to ${r.min_fill}% in the worst run`:''}.` });
  return rows;
}
// Generic glass-box card rendering any explain*() row set — same DiRow plain-English
// surface as DecisionExplainer, reused across the four solvers (G-C1).
function GlassBoxExplainer({ icon, title, rows, note, badge, badgeTone, prov }){
  if(!rows || !rows.length) return null;
  // prov-ok: pure translator — rows = explain*() of a parent solve (Logistics transport/ResCapital/ResRisk useSolve · LinePressureTable linecap); no figures invented here
  const provChip = <Provenance kind="solved" note={prov||'solver output'}/>;
  return (
    <Card icon={icon||'🔍'} title={title||'Why this result? — plain-English explainer'} badge={badge||`${rows.length} insight${rows.length===1?'':'s'}`} badgeTone={badgeTone||'y'} span={2}
      right={provChip}
      info={{ what:'Translates the solver’s own numbers — shadow prices, NPVs, the CVaR tail — into plain language you can act on. No new figures, only translation.', flows:'Reads the live solve.' }}
      dev={{ comp:'GlassBoxExplainer (G-C1)', props:'explain{Linecap,Transport,Capital,Cvar}(result)' }}>
      {rows.map((c,i)=><DiRow key={i} {...c}/>)}
      {note && <div style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color:C.tx3, lineHeight:1.5}}>{note}</div>}
    </Card>
  );
}

// G-PM1/G-SU2 — true ⇔ exactly one finished SKU ⇒ no product mix to optimise (a "mix" of
// one is trivial: make to the binding constraint). Top-level so the boot probe can call it.
function profitMixSingleProduct(){ return (M.products||[]).filter(p=>p.cat==='Finished').length === 1; }

// The collapsed Profit-mix surface for a single-product portfolio: there is no rationing
// across products, so we replace the optimiser with an honest one-SKU capacity check
// (peak committed demand vs the line's stated per-period cap) + a nudge to add products.
function SingleProductCheck({ sku }){
  const dem = (typeof getItemDemand==='function') ? getItemDemand(sku.sku, 12) : [];
  const peak = dem.length ? Math.max(...dem) : (sku.demand||0);
  const total = dem.reduce((a,b)=>a+b, 0);
  const line = (M.lines||[]).find(l=>l.id===sku.line);
  const cap = line ? (Number(line.cap)||0) : 0;
  const binds = cap>0 && peak>cap;
  const margin = (sku.price||0) - (sku.cost||0);
  return (
    <Card icon="🎯" title="Single-product capacity check" badge="no mix to optimise" badgeTone="y" span={2}
      info={{ what:'With one finished SKU there is no product mix to ration — the Profit-mix optimiser is collapsed to a capacity check (can the line meet demand?).', flows:'Add a second finished product and the mix optimiser returns automatically.' }}
      right={<Provenance kind="derived"/>}
      dev={{ comp:'SingleProductCheck', props:'M.products(Finished)===1, getItemDemand, M.lines[].cap', note:'G-PM1/G-SU2 — profile gate also greys Profit-mix when finished.length===1.' }}>
      <div style={{fontFamily:F.mono, fontSize:11, color:C.tx2, marginBottom:11, lineHeight:1.6}}>
        Your portfolio has a <b>single finished product</b> — <b>{sku.name}</b> ({sku.sku}). There is no
        contribution <i>mix</i> to optimise; the plan simply makes to the binding constraint
        ({binds ? 'capacity — peak demand exceeds the line cap' : 'demand — the line has slack'}).
      </div>
      <DataTable dense cols={['Metric','Value']} align={['left','right']}
        rows={[
          ['Committed demand (peak / period)', `${Math.round(peak).toLocaleString('en-IN')} u`],
          ['Committed demand (horizon total)', `${Math.round(total).toLocaleString('en-IN')} u`],
          ['Line', line ? `${line.id}` : '—'],
          ['Line capacity (u / period)', cap ? cap.toLocaleString('en-IN') : '— (not set)'],
          ['Capacity verdict', binds ? '🔴 binds — demand > cap' : (cap?'🟢 slack — cap meets demand':'—')],
          ['Unit contribution', `₹${Math.round(margin).toLocaleString('en-IN')}`],
        ]}/>
      <div style={{marginTop:11, padding:'8px 11px', border:`1px dashed ${C.line2}`, fontFamily:F.mono, fontSize:10, color:C.tx3, lineHeight:1.55}}>
        💡 <b>Add a second finished product</b> (Products tab) and the Profit-mix optimiser returns — it
        only earns its keep when contribution must be rationed across competing SKUs. If you expect
        scarce capacity across products soon, set <b>Setup → capacity profile</b> accordingly.
      </div>
    </Card>
  );
}

function ResProfit() {
  const { config, setConfig } = useConfig();
  const pm = useSolve('/api/solve/profitmix', profitmixPayload, { solveKey:'profitmix' });   // B-3 — persist to the cross-stage cache (OBS-2 dual cross-check vs linecap + value ledger)
  // G-PM1/G-SU2 — gate AFTER all hooks (Rules of Hooks): one finished SKU ⇒ collapse to a
  // capacity check, there is no mix to ration. 6-SKU golden path never hits this (byte-identical).
  const _fin = M.products.filter(p=>p.cat==='Finished');
  if (_fin.length === 1) return <Grid cols={2}><SingleProductCheck sku={_fin[0]}/></Grid>;
  const r = pm.result;
  const runPm = ()=> pm.run().then(d=>{ markSolved('profitmix'); return d; }).catch(()=>{});   // B-3 — clear the stale flag so the model map colours it fresh
  const fmtL = n=>`₹${(n/1e5).toFixed(1)}L`;
  // pre-solve headline = the REAL Σ(price−cost)·demand of the finished goods, so the
  // badge + table foot + per-row % all agree with the data. (Was 3 mismatched hardcodes:
  // badge ₹6.84 Cr, foot ₹68.4L, denom 6840000 — none matched the ~₹56L the seed implies.)
  const seedTotal = M.products.filter(p=>p.cat==='Finished').reduce((s,p)=>s+(p.price-p.cost)*p.demand,0);
  return (
    <Grid cols={2}>
      <Card icon="💰" title="Profit Maximizer Results" badge={r?fmtL(r.total_profit):fmtL(seedTotal)} badgeTone="y" info={{ what:'Optimal product mix maximising contribution under a binding capacity ration. Optional ₹ budget (caps Σ variable-cost·qty) and warehouse slots (caps Σ qty) add working-capital / storage limits.', flows:'Mix → procurement & production targets.' }} span={2}
        right={r ? <Provenance kind="solved" asOf={pm.ranAt}/> : <Btn kind="accent" sm onClick={runPm}>{pm.solving?'⏳ Optimizing…':'💰 Optimize mix'}</Btn>}
        dev={{ comp:'ProfitResults', props:'solve.profit', state:'config.pmBudget, config.pmWarehouse (0=unbounded)' }}>
        {pm.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>profit-mix error: {pm.error}</div>}
        <div style={{display:'flex', gap:14, flexWrap:'wrap', alignItems:'flex-end', marginBottom:12, paddingBottom:11, borderBottom:`2px solid ${C.line2}`}}>
          <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, letterSpacing:'.1em', color:C.tx3, alignSelf:'center'}}>OPTIONAL CONSTRAINTS</span>
          <Field label="Cash budget (Σ var-cost·qty)" hint="0 = unbounded; caps the working capital the mix can deploy">
            <NumInput value={config.pmBudget==null?0:config.pmBudget} prefix="₹" w={120}
              onChange={v=>setConfig({ pmBudget: v===''?0:Number(v) })}/>
          </Field>
          <Field label="Warehouse slots (Σ qty)" hint="0 = unbounded; caps total units the FG store can hold">
            <NumInput value={config.pmWarehouse==null?0:config.pmWarehouse} suffix="u" w={110}
              onChange={v=>setConfig({ pmWarehouse: v===''?0:Number(v) })}/>
          </Field>
          {r && (Number(config.pmBudget)>0 || Number(config.pmWarehouse)>0) &&
            <span style={{fontFamily:F.mono, fontSize:9, color:C.tx2, alignSelf:'center'}}>active — re-optimize to apply</span>}
        </div>
        {r ? (
          <>
            <DataTable cols={['SKU','Optimal Qty','Margin/u','Margin/hr','Profit','% of profit','Status']} align={['left','right','right','right','right','right','left']}
              rows={[...r.products].sort((a,b)=>b.margin_per_hour-a.margin_per_hour).map(p=>[
                p.name, Math.round(p.quantity).toLocaleString('en-IN'), `₹${Math.round(p.margin_per_unit)}`,
                `₹${p.margin_per_hour.toFixed(0)}`, fmtL(p.profit), `${(p.pct_of_total||0).toFixed(0)}%`,
                p.quantity>0.5 ? <Tag c="g">make</Tag> : <Tag c="r">drop</Tag>,
              ])}
              foot={['TOTAL','','','',fmtL(r.total_profit),`${r.margin_pct}% margin`,'']}/>
            {r.shadow_prices && r.shadow_prices.filter(s=>s.binding).length>0 && (
              <div style={{marginTop:10, fontFamily:F.mono, fontSize:10, color:C.tx2}}>
                Binding: {r.shadow_prices.filter(s=>s.binding).map(s=>`${s.constraint} (dual ₹${s.shadow_price.toFixed(0)}/u)`).join(' · ')} — the lowest margin/hr SKU is rationed out first.
              </div>
            )}
          </>
        ) : (
          <DataTable cols={['SKU','Optimal Qty','Price','Unit Cost','Contribution','% of profit']} align={['left','right','right','right','right','right']}
            rows={M.products.filter(p=>p.cat==='Finished').map(p=>{ const c=(p.price-p.cost)*p.demand;
              return [p.sku, p.demand.toLocaleString('en-IN'), `₹${p.price}`, `₹${p.cost}`, `₹${(c/100000).toFixed(1)}L`, `${Math.round(c/seedTotal*100)}%`];
            })}
            foot={['TOTAL','','','',fmtL(seedTotal),'100%']}/>
        )}
      </Card>
      <DecisionExplainer r={r}/>
    </Grid>
  );
}

// V2-7 — ResTransport deleted (one-result-one-home): its lane/mode + consolidation
// tables were a second render of the SAME transport solve that Logistics (LogAllocation/
// LogConsolidation) already owns, and its GlassBoxExplainer moved to Logistics step 2.
// The Console transport entry is now a ResultHomeLink KPI chip.

// Build the Monte-Carlo payload from finished goods: spread annual demand over
// 12 monthly periods, use each SKU's MAPE as the demand CV and price/cost as the
// economics. Capacity set just above mean demand so fill-rate risk is real.
// NOTE — montecarloPayload also lives in store.jsx (governed: replays the committed
// production gantt with per-SKU bills, live FX, and lead-time lag). The no-arg duplicate
// that used to live here shadowed it (same load-order bug as productionPayload above), so
// the Risk suite simulated a flat demand/T payload and `params.plan_committed` was always
// undefined ⇒ "MC on committed plan" silently never engaged. Removed.
function McChart({ hist, mean }) {
  // real histogram (bins[21] + counts[20]) when solved, else the mock buckets
  const buckets = hist ? hist.counts.map((n,i)=>({ x:hist.bins[i], n })) : M.mcBuckets.map(b=>({x:b.x,n:b.n}));
  const mxN=Math.max(...buckets.map(x=>x.n))||1;
  const n=buckets.length, slot=440/n, w=Math.max(4,slot-3);
  const meanX = mean!=null ? mean : 518; // value at which to draw the marker / colour threshold
  const lo = buckets[0]?.x ?? 0, hi = buckets[n-1]?.x ?? 1;
  const mx = lo!==hi ? 20 + (meanX-lo)/(hi-lo)*440 : 20+n*slot/2;
  const fmt = v=> hist ? `₹${(v/1e5).toFixed(0)}L` : `mean ${v}`;
  return (
    <svg viewBox="0 0 460 160" style={{width:'100%', height:160, display:'block'}}>
      {buckets.map((x,i)=>{ const h=x.n/mxN*120, bx=20+i*slot;
        return <rect key={i} x={bx} y={140-h} width={w} height={h} fill={x.x>=meanX?C.dg:C.ink}/>;
      })}
      <line x1={mx} y1="10" x2={mx} y2="145" stroke={C.ac2} strokeWidth="2" strokeDasharray="4 2"/>
      <text x={mx+3} y="20" fontFamily={F.mono} fontSize="8.5" fill={C.tx2}>{fmt(meanX)}</text>
    </svg>
  );
}

function ResRisk() {
  const { planning } = usePlanning();
  const mc = useSolve('/api/solve/montecarlo', ()=>montecarloPayload(planning));
  const r = mc.result;
  const s = M.mcStats;
  const L = n=>`₹${(n/1e5).toFixed(0)}L`;
  return (
    <Grid cols={2}>
      <Card icon="🎲" title="Monte Carlo Results" badge={r?`${r.n_runs} runs · ${r.policy_simulated}`:'1,000 runs'} badgeTone="y" info={{ what:'Total-cost distribution under uncertainty.', flows:'Risk → CVaR & hedging.' }} span={2}
        right={r ? <Provenance kind="solved" asOf={mc.ranAt}/> : <Btn kind="accent" sm onClick={()=>mc.run().catch(()=>{})}>{mc.solving?'⏳ Simulating…':'🎲 Run 500 sims'}</Btn>}
        dev={{ comp:'MonteCarloResults', props:'solve.montecarlo', note:'montecarlo.py backend.' }}>
        {mc.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>monte-carlo error: {mc.error}</div>}
        <McChart hist={r?r.histogram:undefined} mean={r?r.avg_cost:undefined}/>
        <KpiRow cols={5}>
          <Blk label="Mean" value={r?L(r.avg_cost):`₹${s.mean}L`}/>
          <Blk label="Median" value={r?L(r.p50):`₹${s.median}L`}/>
          <Blk label="P95 (VaR)" value={r?L(r.var95):`₹${s.p95}L`} accent={C.a4}/>
          <Blk label="CVaR 95%" value={r?L(r.cvar95):`₹${s.cvar95}L`} accent={C.dg}/>
          <Blk label="Fragility" value={r?(r.fragility!=null?String(r.fragility):'—'):s.fragility} tone="y"/>
        </KpiRow>
        {r && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2}}>Avg fill {r.avg_fill}% · min fill {r.min_fill}% · CVaR is the mean cost of the worst 5% of {r.n_runs} runs.</div>}
      </Card>
      {r && <GlassBoxExplainer icon="🎲" title="What the risk numbers mean — plain-English" rows={explainCvar(r)} prov="Monte-Carlo / CVaR"
        note="Mean, VaR, CVaR and fill are the simulation's own outputs — this reads the tail back to you in words you can act on."/>}
    </Grid>
  );
}

// Per-line CapEx proposals → capital-budget knapsack under a ₹2.5 Cr budget that
// can't fund all three, so the MILP must choose. (Mirrors Finance's PerLineCapex.)
const CAPEX_PROPOSALS = [
  { name:'Heat-Treat #2 (LINE-03)', capex:18000000, annual_cash_flow:3500000, useful_life:10, residual_value:1800000, dcap:'+38%' },
  { name:'Grinder upgrade (LINE-01)', capex:9000000, annual_cash_flow:1784000, useful_life:10, residual_value:900000, dcap:'+12%' },
  { name:'Honing cell (LINE-02)', capex:12000000, annual_cash_flow:2213000, useful_life:10, residual_value:1200000, dcap:'+9%' },
];
function capitalPayload(){
  // NB: avoid object-REST destructuring here. Babel-standalone hoists a top-level
  // `const _excluded` helper per transpiled file for `{a, ...r}`; lib.jsx (Box/Btn)
  // already declares one, and a second in this file collides in the shared global
  // scope ("Identifier '_excluded' already declared") — which blanks the whole app.
  // Strip `dcap` without rest-destructuring so lib.jsx stays the only _excluded emitter.
  const _stripDcap = (p)=>{ const r = Object.assign({}, p); delete r.dcap; return r; };
  // CRITICAL wire (audit fix): the CapEx budget and WACC are NOT hardcoded — they read
  // the SAME governed Finance inputs the capital-capacity solver already uses
  // (config.finCapexBudget "Budget/yr" + the live blended WACC from finBlendedHurdle),
  // so changing them in Finance re-prices this selection too. Falls back to the prior
  // seeds when Finance hasn't been touched, so default behaviour is unchanged.
  const cfg = ((typeof appStore!=='undefined' && appStore.get().config) || {});
  const budget = (typeof _effNum==='function') ? _effNum(cfg.finCapexBudget, 25000000) : (cfg.finCapexBudget||25000000);
  const wacc = (typeof finBlendedHurdle==='function') ? finBlendedHurdle(cfg).wacc/100 : 0.1124;
  return { investments:CAPEX_PROPOSALS.map(_stripDcap), params:{ budget, wacc } };
}
function ResCapital() {
  const cap = useSolve('/api/solve/capital', capitalPayload, { solveKey:'capital' });   // B-3 — persist to the cross-stage cache (OBS-1 map + value ledger)
  const r = cap.result;
  const runCap = ()=> cap.run().then(d=>{ markSolved('capital'); return d; }).catch(()=>{});   // B-3 — clear the stale flag so the model map colours it fresh
  const dcapOf = n=>{ const p=CAPEX_PROPOSALS.find(x=>x.name===n); return p?p.dcap:'—'; };
  const all = r ? [...(r.selected||[]), ...(r.rejected||[])] : null;
  // budget + WACC now come from Finance (config.finCapexBudget + blended WACC) — show
  // the live figures the solve actually used instead of a hardcoded "₹2.5 Cr".
  const _cfg = ((typeof appStore!=='undefined' && appStore.get().config) || {});
  const _budget = (typeof _effNum==='function') ? _effNum(_cfg.finCapexBudget, 25000000) : 25000000;
  const _wacc = (typeof finBlendedHurdle==='function') ? finBlendedHurdle(_cfg).wacc : 11.24;
  return (
    <Grid cols={2}>
      <Card icon="🏗️" title="Capital Budget Results" badge={r?`fund ${r.selected.length}/${CAPEX_PROPOSALS.length} · ₹${(r.total_capex/1e7).toFixed(2)}Cr`:'endogenous'} badgeTone="y"
        right={r ? <Provenance kind="solved" asOf={cap.ranAt}/> : <Btn kind="accent" sm onClick={runCap}>{cap.solving?'⏳ Allocating…':'🏗️ Run capital budget'}</Btn>}
        info={{ what:'Optimal capacity investments under a binding budget.', flows:'CapEx → Finance verdict.' }} span={2}
        dev={{ comp:'CapitalResults', props:'solve.capital', note:'capital.py backend.' }}>
        {cap.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>capital error: {cap.error}</div>}
        <DataTable cols={['Investment','CapEx','ΔCapacity','NPV','IRR','Decision']} align={['left','right','right','right','right','left']}
          rows={r ? all.map(s=>[s.name, `₹${(s.capex/1e7).toFixed(2)} Cr`, dcapOf(s.name), `₹${(s.npv/1e5).toFixed(1)}L`,
                 s.irr!=null?`${s.irr}%`:'—', s.selected?<Tag c="g">FUND</Tag>:<Tag c="w">DEFER</Tag>])
               : [['Heat-Treat #2','₹1.8 Cr','+38%','₹24L','19.2%',<Tag c="g">FUND</Tag>],['Grinder upgrade','₹0.9 Cr','+12%','₹14L','16.4%',<Tag c="g">FUND</Tag>],['Honing cell','₹1.2 Cr','+9%','₹9L','13.1%',<Tag c="w">DEFER</Tag>]]}/>
        {r && <Reading formula="max Σ NPVᵢ·xᵢ  s.t.  Σ CapExᵢ·xᵢ ≤ budget,  xᵢ ∈ {0,1}"
          soWhat={`Budget ₹${(_budget/1e7).toFixed(2)} Cr @ WACC ${_wacc.toFixed(2)}% (both from Finance · CapEx budget/yr + blended WACC, not hardcoded) funds ${r.selected.map(s=>s.name.split(' (')[0]).join(' + ')||'nothing'} for ₹${(r.total_npv/1e5).toFixed(1)}L NPV — the knapsack can defer a higher single-NPV item to fit two that together return more.`}/>}
      </Card>
      {r && <GlassBoxExplainer icon="🏗️" title="Why fund these? — plain-English" rows={explainCapital(r)} prov="capital knapsack"
        note="Each fund/defer verdict is the knapsack's own NPV vs the budget — translated, not re-decided."/>}
    </Grid>
  );
}

function ResSOP() {
  return (
    <Grid cols={3}>
      <Card icon="🔁" title="Closed-loop S&OP" badge="reconciled" badgeTone="y" info={{ what:'Demand/supply/finance reconciled to one plan.', flows:'Loop back into Profit mix.' }} span={2}
        dev={{ comp:'ClosedLoopSOP', props:'solve.sop' }}>
        <KpiRow cols={4}>
          <Blk label="Vol Gap" value={`+${M.sop.volumeGap}%`} accent={C.gn}/>
          <Blk label="Rev Gap" value={`${M.sop.revGap}%`} accent={C.dg}/>
          <Blk label="Margin Gap" value={`+${M.sop.marginGap}%`} accent={C.gn}/>
          <Blk label="Inv Gap" value={`${M.sop.inventoryGap}%`} accent={C.dg}/>
        </KpiRow>
      </Card>
      <Card icon="🔗" title="Pipeline (3 steps)" badge="profit→procure→produce" info={{ what:'End-to-end chained solve — reads each stage’s live cached result; ◇ run = not solved yet.', flows:'Each step seeds the next.' }}
        right={(()=>{ const g=typeof getSolveResult==='function'; const any=g&&(getSolveResult('profitmix')||getSolveResult('procurement')||getSolveResult('production')); return any?<Provenance kind="solved"/>:<Provenance kind="seed"/>; })()}
        dev={{ comp:'PipelineCard', props:'getSolveResult(profitmix|procurement|production)' }}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {(()=>{ const g=typeof getSolveResult==='function'; const pm=g&&getSolveResult('profitmix'), pr=g&&getSolveResult('procurement'), pd=g&&getSolveResult('production');
            const Cr=n=>`₹${(n/1e7).toFixed(2)} Cr`;
            const pdUnits=pd?((pd.gantt||[]).reduce((s,x)=>s+(x.quantity||0),0)):0;
            return [['Profit Mix', pm?Cr(pm.total_profit):'◇ run', C.gn],
                    ['Procurement', pr?Cr(pr.total_cost):'◇ run', C.ac],
                    ['Production', pd?`${Math.round(pdUnits).toLocaleString('en-IN')} u`:'◇ run', C.tx3]]; })().map((s,i)=>(
            <div key={i} style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${C.line}`, padding:'6px 9px'}}>
              <span style={{width:9, height:9, background:s[2], border:`1.5px solid ${C.line}`}}/>
              <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, flex:1}}>{s[0]}</span>
              <span className="num" style={{fontFamily:F.mono, fontSize:11, fontWeight:700}}>{s[1]}</span>
            </div>
          ))}
        </div>
      </Card>
    </Grid>
  );
}
window.StageConsole = StageConsole;
