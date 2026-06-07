// ──────────────────────────────────────────────────────────────────────
// chrome.jsx — app shell: masthead · stage rail · pipeline ribbon · footer
// Themeable via data-theme on <html>. Renders active stage as children.
// ──────────────────────────────────────────────────────────────────────

// ── pipeline ribbon (P6 / Ph3 IA): a FRESHNESS STRIP, not a second nav ──
// LIVE: the 6 dots map 1:1 onto the real LOOP_STEPS solve keys, so each dot and value
// reflect the cross-stage solve cache (solveResults) + freshness (solves) — done /
// stale / not-run. No hardcoded statuses or values; an unsolved stage reads "—" and
// goes grey. Subscribes to the store so a re-plan animates the whole ribbon.
//   Ph3 (R4 — one nav vocabulary): the strip is demoted to a STATUS bar whose jump
//   targets use the RAIL's page vocabulary (`page` = the M.stages name of `go`), NOT a
//   second taxonomy (the old DEMAND/PROCURE/PRODUCE/CAPITAL/RISK labels competed with
//   the rail's Demand/Sourcing/Production/Plan/Scenarios). The solve PHASE/method is
//   kept as a thin sub so the spine's meaning survives — e.g. two dots open Plan (S&OP
//   aggregate + capital dual), which is honest: both solves surface on the Plan page.
const _RIBBON_STAGES = [
  { key:'forecast',    phase:'forecast',     go:'demand',
    val:r=>`${(r.products||[]).length||'—'} SKUs` },
  { key:'aggregate',   phase:'S&OP',         go:'plan',
    val:r=>r.strategy?String(r.strategy):'solved' },
  { key:'procurement', phase:'procure·MILP', go:'sourcing',
    val:r=>`${(r.materials||[]).length||0} parts` },
  { key:'production',  phase:'schedule',     go:'production',
    val:r=>`${(r.gantt||[]).length||0} runs` },
  { key:'linecap',     phase:'capital dual', go:'plan',
    val:r=>`${(r.lines||[]).filter(l=>l.binding).length} binding` },
  { key:'montecarlo',  phase:'risk·CVaR',    go:'scenarios',
    val:r=>r.avg_fill!=null?`${r.avg_fill}% fill`:'solved' },
];
// the page label every jump shows comes from the rail (M.stages), so the ribbon and the
// rail can never drift to two names for the same destination.
const _ribbonPage = (go)=>{ const s=(M.stages||[]).find(x=>x.id===go); return s?s.name:go; };
function PipelineRibbon({ active, onNav }) {
  const { state:sr }     = useStore(s=>s.solveResults||{});
  const { state:solves } = useStore(s=>s.solves||{});
  const stColor = { done:C.gn, stale:C.a4, idle:C.tx3 };
  const solvedN = _RIBBON_STAGES.filter(s=>sr[s.key]).length;
  const staleN  = _RIBBON_STAGES.filter(s=>(solves[s.key]||{}).stale).length;
  return (
    <div style={{display:'flex', alignItems:'stretch', borderBottom:`2px solid ${C.line}`, background:C.bg2}}>
      <div style={{display:'flex', flexDirection:'column', justifyContent:'center', gap:1, padding:'0 14px', borderRight:`2px solid ${C.line}`, background:C.ink, color:C.paper}}>
        <span style={{fontFamily:F.disp, fontSize:10, fontWeight:800, letterSpacing:'.1em', whiteSpace:'nowrap'}}>SOLVE FRESHNESS · {solvedN}/{_RIBBON_STAGES.length} FRESH</span>
        <span style={{fontFamily:F.mono, fontSize:7.5, color: staleN?C.a4:C.ac, letterSpacing:'.04em', whiteSpace:'nowrap'}}>{staleN?`${staleN} stale — re-plan from Home`:'planning-spine status · jump to its page'}</span>
      </div>
      <div style={{display:'flex', flex:1, minWidth:0}}>
        {_RIBBON_STAGES.map((p,i)=>{
          const res    = sr[p.key] ? sr[p.key].result : null;
          const st     = solves[p.key] || {};
          const status = !res ? 'idle' : (st.stale ? 'stale' : 'done');
          const val    = res ? p.val(res) : '—';
          const page   = _ribbonPage(p.go);
          const onPage = active===p.go;
          return (
            <button key={p.key} onClick={()=>onNav(p.go)} title={`${page} — ${status==='stale'?'stale (inputs changed since last solve)':status==='done'?'fresh':'not solved yet'} · click to open`} style={{
              flex:1, minWidth:0, border:'none', borderRight: i<_RIBBON_STAGES.length-1?`1px solid ${C.line2}`:'none',
              background: onPage?C.bg3:'transparent', cursor:'pointer', padding:'7px 10px', display:'flex', alignItems:'center', gap:9, textAlign:'left',
            }}>
              <span style={{
                width:9, height:9, flexShrink:0, background:stColor[status], border:`1.5px solid ${C.line}`,
              }}/>
              <span style={{minWidth:0}}>
                <span style={{display:'flex', alignItems:'center', gap:6}}>
                  <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.03em', textTransform:'uppercase'}}>{page}</span>
                  <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{p.phase}</span>
                </span>
                <span className="num" style={{fontFamily:F.mono, fontSize:10, color: status==='idle'?C.tx3:status==='stale'?C.a4:C.tx, fontWeight:600}}>{val}</span>
              </span>
              {i<_RIBBON_STAGES.length-1 && <span style={{marginLeft:'auto', color:C.tx3, fontSize:12}}>›</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── stage nav rail ──
function NavRail({ active, onNav }) {
  const { profile } = useProfile();
  const sGate = M.stageGate(profile);
  return (
    <nav style={{width:188, flexShrink:0, borderRight:`2px solid ${C.line}`, background:C.bg2, overflowY:'auto', display:'flex', flexDirection:'column'}}>
      {M.stages.map((s,i)=>{
        const a = active===s.id;
        const off = sGate[s.id];
        const prev = M.stages[i-1];
        const showBand = s.band && (!prev || prev.band!==s.band);
        return (
          <React.Fragment key={s.id}>
            {showBand && (
              <div style={{padding:'7px 12px 4px', background:C.bg2, borderBottom:`1px solid ${C.line2}`}}>
                <span style={{fontFamily:F.mono, fontSize:8, fontWeight:700, letterSpacing:'.18em', color:C.tx3}}>{s.band}</span>
              </div>
            )}
            <button onClick={()=>onNav(s.id)} data-screen-label={s.name} style={{
              textAlign:'left', border:'none', borderBottom:`1px solid ${C.line2}`, cursor:'pointer',
              background: a?C.ink:'transparent', color: a?C.paper:C.tx, padding:'9px 12px',
              display:'flex', alignItems:'center', gap:10, position:'relative', opacity: off&&!a?.5:1,
            }}>
              {a && <span style={{position:'absolute', left:0, top:0, bottom:0, width:4, background:C.ac}}/>}
              <span style={{fontFamily:F.mono, fontSize:11, fontWeight:700, color: a?C.ac:C.tx3, width:18}}>{s.n}</span>
              <span style={{minWidth:0, flex:1}}>
                <span style={{display:'flex', alignItems:'center', gap:5}}>
                  <span style={{fontFamily:F.disp, fontSize:12.5, fontWeight:800, letterSpacing:'.03em', textTransform:'uppercase'}}>{s.name}</span>
                  {off && <span style={{fontFamily:F.mono, fontSize:7.5, fontWeight:700, color:C.tx3, border:`1px solid ${C.line2}`, padding:'0 3px'}}>N/A</span>}
                </span>
                <span style={{display:'block', fontFamily:F.mono, fontSize:8.5, color: a?'rgba(255,255,255,.55)':C.tx3, marginTop:1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{off?'not needed for your setup':s.sub}</span>
              </span>
            </button>
          </React.Fragment>
        );
      })}
      <div style={{marginTop:'auto', padding:'10px 12px', borderTop:`2px solid ${C.line}`}}>
        <div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, letterSpacing:'.1em'}}>HANDOFF BUILD</div>
        <div style={{fontFamily:F.disp, fontSize:11, fontWeight:800, marginTop:2}}>v4 · SPINE</div>
      </div>
    </nav>
  );
}

// ── theme switcher ──
function ThemeSwitch({ theme, onTheme }) {
  const opts=[['mono','MONO'],['noir','NOIR'],['sepia','SEPIA']];
  return (
    <div style={{display:'flex', border:`2px solid ${C.line}`}}>
      {opts.map(([id,lbl],i)=>(
        <button key={id} onClick={()=>onTheme(id)} style={{
          fontFamily:F.mono, fontSize:9, fontWeight:700, letterSpacing:'.08em', padding:'4px 8px',
          border:'none', borderRight: i<2?`1px solid ${C.line}`:'none', cursor:'pointer',
          background: theme===id?C.ac:C.paper, color: theme===id?C.onAc:C.tx,
        }}>{lbl}</button>
      ))}
    </div>
  );
}

// ── version history menu (app_v2) — moved from Scenarios·Performance; an
// audit/version concern belongs in the system chrome, not a scenario tab ──
function VersionMenu() {
  const [open, setOpen] = useState(false);
  const cur = M.versions[0];
  return (
    <span style={{position:'relative', display:'inline-block'}}>
      <button onClick={()=>setOpen(o=>!o)} title="version history" style={{
        fontFamily:F.mono, fontSize:9.5, fontWeight:700, letterSpacing:'.04em', padding:'3px 8px',
        border:`1.5px solid ${C.line}`, background: open?C.ac:C.paper, color: open?C.onAc:C.tx, cursor:'pointer',
        display:'inline-flex', alignItems:'center', gap:6,
      }}>⟳ {cur.v}<span style={{color: open?C.onAc:C.tx3}}>▾</span></button>
      {open && (
        <div style={{position:'absolute', top:27, right:0, zIndex:60, width:300, background:C.paper, border:`2px solid ${C.line}`, boxShadow:`5px 5px 0 ${C.ink}`}}>
          <div style={{padding:'7px 10px', borderBottom:`2px solid ${C.line}`, background:C.card, display:'flex', alignItems:'center', gap:8}}>
            <span style={{fontFamily:F.disp, fontSize:10.5, fontWeight:800, letterSpacing:'.04em', textTransform:'uppercase'}}>Version History</span>
            <Badge>{M.versions.length}</Badge>
            <button onClick={()=>setOpen(false)} style={{marginLeft:'auto', border:'none', background:'transparent', cursor:'pointer', fontFamily:F.mono, fontSize:11, color:C.tx3}}>✕</button>
          </div>
          <div style={{maxHeight:260, overflowY:'auto'}}>
            {M.versions.map((v,i)=>(
              <div key={i} style={{display:'flex', flexDirection:'column', gap:2, padding:'8px 10px', borderTop:i?`1px solid ${C.line2}`:'none', background: i===0?C.bg3:C.paper}}>
                <div style={{display:'flex', alignItems:'center', gap:8}}>
                  <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800}}>{v.v}</span>
                  {i===0 && <Tag c="g">current</Tag>}
                  <span style={{marginLeft:'auto', fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{v.t}</span>
                </div>
                <div style={{fontFamily:F.body, fontSize:11, color:C.tx2, lineHeight:1.35}}>{v.note}</div>
                <div style={{display:'flex', alignItems:'center', gap:8}}>
                  <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>by {v.who}</span>
                  {i>0 && <span title="Version restore is not wired yet — the version trail is read-only for now." style={{marginLeft:'auto', fontFamily:F.mono, fontSize:8.5, fontWeight:700, color:C.tx3, cursor:'not-allowed'}}>restore (soon)</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </span>
  );
}

// ── masthead ──
function Masthead({ theme, onTheme, onNav }) {
  return (
    <header style={{display:'grid', gridTemplateColumns:'auto 1fr auto', borderBottom:`3px solid ${C.line}`, background:C.bg2}}>
      <div style={{padding:'11px 18px', borderRight:`2px solid ${C.line}`, background:C.ink, color:C.paper, display:'flex', alignItems:'center', gap:11}}>
        <div style={{width:26, height:26, background:C.ac, border:`2px solid ${C.paper}`, display:'grid', placeItems:'center', fontFamily:F.disp, fontWeight:900, color:C.onAc, fontSize:15}}>E</div>
        <div>
          <div style={{fontFamily:F.disp, fontSize:14, fontWeight:800, letterSpacing:'.02em'}}>ENTERPRISE SIMULATOR</div>
          <div style={{fontFamily:F.mono, fontSize:8.5, opacity:.6, letterSpacing:'.12em'}}>SUPPLY-CHAIN OS · MILP/LP PLATFORM</div>
        </div>
      </div>
      <div style={{padding:'10px 18px', display:'flex', alignItems:'center', gap:14, fontFamily:F.mono, fontSize:10.5, flexWrap:'wrap'}}>
        <span style={{fontWeight:700}}>{M.company}</span>
        <span style={{color:C.tx3}}>·</span><span>{M.city}</span>
        <span style={{color:C.tx3}}>·</span><span>{M.fy}</span>
        <span style={{color:C.tx3}}>·</span>
        <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
          <span style={{width:8, height:8, background:C.gn, borderRadius:'50%', boxShadow:`0 0 0 2px ${C.bg2}, 0 0 0 3px ${C.line}`}}/>
          PuLP/CBC · ready
        </span>
      </div>
      <div style={{padding:'9px 16px', borderLeft:`2px solid ${C.line}`, display:'flex', alignItems:'center', gap:12}}>
        <ThemeSwitch theme={theme} onTheme={onTheme}/>
        <VersionMenu/>
        <button onClick={()=>onNav&&onNav('reference')} title="Reference — Learning Lab, SAP map & open API (also in the rail under LEARN)" style={{
          fontFamily:F.mono, fontSize:9.5, fontWeight:700, letterSpacing:'.04em', padding:'3px 8px',
          border:`1.5px solid ${C.line}`, background:C.paper, color:C.tx, cursor:'pointer',
        }}>❓ Reference</button>
        <span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, display:'flex', alignItems:'center', gap:8}}>
          <span style={{border:`1.5px solid ${C.line}`, padding:'2px 6px'}}>⌘K</span>
          {M.updated.split('·')[1]}
        </span>
      </div>
    </header>
  );
}

// ── footer status bar ──
function Footer() {
  return (
    <footer style={{borderTop:`3px solid ${C.line}`, background:C.ink, color:C.paper, padding:'6px 18px', display:'flex', gap:16, fontFamily:F.mono, fontSize:10, letterSpacing:'.04em', alignItems:'center'}}>
      <span style={{color:C.ac, fontWeight:700}}>● LIVE</span>
      <span>SOLVERS · {M.solverLabel.toUpperCase()}</span><span style={{color:C.tx3}}>·</span>
      <span>GRAIN · {M.calendar.grain.toUpperCase()}LY</span><span style={{color:C.tx3}}>·</span>
      <span>HORIZON · {M.calendar.count}{M.calendar.grain[0]} · {M.periods[0].date}→{M.periods[M.periods.length-1].date}</span><span style={{color:C.tx3}}>·</span>
      <span>ITEMS · {M.items.length} FG</span>
      <span style={{marginLeft:'auto', color:C.ac}}>⌘S SAVE · ⌘R SOLVE · ⌘E EXPORT</span>
    </footer>
  );
}

// ── chrome wrapper ──
function Chrome({ active, onNav, theme, onTheme, children }) {
  return (
    <div style={{width:'100vw', height:'100vh', display:'flex', flexDirection:'column', overflow:'hidden', background:C.bg, color:C.tx}}>
      <Masthead theme={theme} onTheme={onTheme} onNav={onNav}/>
      <PipelineRibbon active={active} onNav={onNav}/>
      <div style={{flex:1, minHeight:0, display:'flex'}}>
        <NavRail active={active} onNav={onNav}/>
        <main style={{flex:1, minWidth:0, overflow:'auto', background:C.bg}}>{children}</main>
      </div>
      <Footer/>
    </div>
  );
}

window.Chrome = Chrome;
