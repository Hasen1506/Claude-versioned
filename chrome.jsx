// ════════════════════════════════════════════════════════════════════════
// chrome.jsx — app shell: masthead · stage rail · pipeline ribbon · footer
// Themeable via data-theme on <html>. Renders active stage as children.
// ════════════════════════════════════════════════════════════════════════

// ── pipeline ribbon (P6): solver spine, doubles as nav ──
function PipelineRibbon({ onNav }) {
  const stColor = { done:C.gn, running:C.ac, queued:C.tx3, idle:C.tx3 };
  return (
    <div style={{display:'flex', alignItems:'stretch', borderBottom:`2px solid ${C.line}`, background:C.bg2}}>
      <div style={{display:'flex', alignItems:'center', gap:8, padding:'0 14px', borderRight:`2px solid ${C.line}`, background:C.ink, color:C.paper}}>
        <span style={{fontFamily:F.disp, fontSize:10, fontWeight:800, letterSpacing:'.1em', whiteSpace:'nowrap'}}>SOLVER PIPELINE</span>
      </div>
      <div style={{display:'flex', flex:1, minWidth:0}}>
        {M.pipeline.map((p,i)=>(
          <button key={p.id} onClick={()=>onNav(p.go)} style={{
            flex:1, minWidth:0, border:'none', borderRight: i<M.pipeline.length-1?`1px solid ${C.line2}`:'none',
            background:'transparent', cursor:'pointer', padding:'7px 10px', display:'flex', alignItems:'center', gap:9, textAlign:'left',
          }}>
            <span style={{
              width:9, height:9, flexShrink:0, background:stColor[p.status],
              borderRadius: p.status==='running'?'50%':0, border:`1.5px solid ${C.line}`,
              boxShadow: p.status==='running'?`0 0 0 3px color-mix(in srgb, ${C.ac} 35%, transparent)`:'none',
            }}/>
            <span style={{minWidth:0}}>
              <span style={{display:'flex', alignItems:'center', gap:6}}>
                <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.03em'}}>{p.stage}</span>
                <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{p.sub}</span>
              </span>
              <span className="num" style={{fontFamily:F.mono, fontSize:10, color: p.status==='running'?C.tx:C.tx2, fontWeight:600}}>{p.val}</span>
            </span>
            {i<M.pipeline.length-1 && <span style={{marginLeft:'auto', color:C.tx3, fontSize:12}}>›</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── stage nav rail ──
function NavRail({ active, onNav }) {
  return (
    <nav style={{width:188, flexShrink:0, borderRight:`2px solid ${C.line}`, background:C.bg2, overflowY:'auto', display:'flex', flexDirection:'column'}}>
      {M.stages.map(s=>{
        const a = active===s.id;
        return (
          <button key={s.id} onClick={()=>onNav(s.id)} data-screen-label={s.name} style={{
            textAlign:'left', border:'none', borderBottom:`1px solid ${C.line2}`, cursor:'pointer',
            background: a?C.ink:'transparent', color: a?C.paper:C.tx, padding:'9px 12px',
            display:'flex', alignItems:'center', gap:10, position:'relative',
          }}>
            {a && <span style={{position:'absolute', left:0, top:0, bottom:0, width:4, background:C.ac}}/>}
            <span style={{fontFamily:F.mono, fontSize:11, fontWeight:700, color: a?C.ac:C.tx3, width:18}}>{s.n}</span>
            <span style={{minWidth:0}}>
              <span style={{display:'block', fontFamily:F.disp, fontSize:12.5, fontWeight:800, letterSpacing:'.03em', textTransform:'uppercase'}}>{s.name}</span>
              <span style={{display:'block', fontFamily:F.mono, fontSize:8.5, color: a?'rgba(255,255,255,.55)':C.tx3, marginTop:1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{s.sub}</span>
            </span>
          </button>
        );
      })}
      <div style={{marginTop:'auto', padding:'10px 12px', borderTop:`2px solid ${C.line}`}}>
        <div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, letterSpacing:'.1em'}}>HANDOFF BUILD</div>
        <div style={{fontFamily:F.disp, fontSize:11, fontWeight:800, marginTop:2}}>v3.2 · COMPLETE</div>
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

// ── masthead ──
function Masthead({ theme, onTheme }) {
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
        <span style={{color:C.tx3}}>│</span><span>{M.city}</span>
        <span style={{color:C.tx3}}>│</span><span>{M.fy}</span>
        <span style={{color:C.tx3}}>│</span>
        <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
          <span style={{width:8, height:8, background:C.gn, borderRadius:'50%', boxShadow:`0 0 0 2px ${C.bg2}, 0 0 0 3px ${C.line}`}}/>
          PuLP/CBC · ready
        </span>
      </div>
      <div style={{padding:'9px 16px', borderLeft:`2px solid ${C.line}`, display:'flex', alignItems:'center', gap:12}}>
        <ThemeSwitch theme={theme} onTheme={onTheme}/>
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
      <span>SOLVER · CBC 2.10.12</span><span style={{color:C.tx3}}>│</span>
      <span>GRAIN · WEEKLY</span><span style={{color:C.tx3}}>│</span>
      <span>HORIZON · 52w</span><span style={{color:C.tx3}}>│</span>
      <span>SKUS · {M.kpis.skus}</span><span style={{color:C.tx3}}>│</span>
      <span>LAST SOLVE · 2.18s</span>
      <span style={{marginLeft:'auto', color:C.ac}}>⌘S SAVE · ⌘R SOLVE · ⌘E EXPORT</span>
    </footer>
  );
}

// ── chrome wrapper ──
function Chrome({ active, onNav, theme, onTheme, children }) {
  return (
    <div style={{width:'100vw', height:'100vh', display:'flex', flexDirection:'column', overflow:'hidden', background:C.bg, color:C.tx}}>
      <Masthead theme={theme} onTheme={onTheme}/>
      <PipelineRibbon onNav={onNav}/>
      <div style={{flex:1, minHeight:0, display:'flex'}}>
        <NavRail active={active} onNav={onNav}/>
        <main style={{flex:1, minWidth:0, overflow:'auto', background:C.bg}}>{children}</main>
      </div>
      <Footer/>
    </div>
  );
}

window.Chrome = Chrome;
