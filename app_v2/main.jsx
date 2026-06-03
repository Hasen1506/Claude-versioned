// ════════════════════════════════════════════════════════════════════════
// main.jsx — App: theme + active-stage state (persisted), router, mount.
// ════════════════════════════════════════════════════════════════════════

// ── ErrorBoundary (review Part 8.1) — the single highest-value reliability fix.
// Before this, a throw in ANY one stage's render unmounted the whole SPA — so one
// bad data path on, say, Logistics blanked every tab including Console (exactly the
// Page-14 "freeze + empty Console" symptom). This catches the throw, keeps the
// chrome/nav alive, and shows a recover card scoped to the failed stage. `stageKey`
// is passed so navigating to a different tab resets the boundary (getDerivedState…
// can't see nav, so we reset on prop change in componentDidUpdate).
class ErrorBoundary extends React.Component {
  constructor(props){ super(props); this.state = { err:null, info:null }; }
  static getDerivedStateFromError(err){ return { err }; }
  componentDidCatch(err, info){ this.setState({ info });
    try{ console.error('[stage error]', this.props.stageKey, err, info); }catch(e){} }
  componentDidUpdate(prev){ if(prev.stageKey !== this.props.stageKey && this.state.err){ this.setState({ err:null, info:null }); } }
  render(){
    if(!this.state.err) return this.props.children;
    const msg = (this.state.err && (this.state.err.message || String(this.state.err))) || 'unknown error';
    const stack = (this.state.info && this.state.info.componentStack) || '';
    return (
      <div style={{padding:28, fontFamily:F.mono}}>
        <div style={{border:`2px solid ${C.dg}`, borderLeft:`6px solid ${C.dg}`, background:C.paper, maxWidth:760}}>
          <div style={{padding:'10px 14px', borderBottom:`2px solid ${C.line}`, background:C.card, display:'flex', alignItems:'center', gap:10}}>
            <span style={{fontFamily:F.disp, fontSize:13, fontWeight:900, letterSpacing:'.04em', textTransform:'uppercase', color:C.dg}}>⚠ This stage hit an error</span>
            <span style={{marginLeft:'auto', fontSize:9.5, color:C.tx3}}>stage: {this.props.stageKey}</span>
          </div>
          <div style={{padding:'14px 16px', fontSize:11.5, lineHeight:1.6, color:C.tx}}>
            <div style={{marginBottom:10, color:C.tx2}}>The rest of the app is fine — only this one screen failed to render. Your data and every other tab are intact.</div>
            <div style={{padding:'8px 10px', background:C.bg3, border:`1.5px solid ${C.line2}`, color:C.dg, fontSize:10.5, whiteSpace:'pre-wrap', wordBreak:'break-word', marginBottom:12}}>{msg}</div>
            <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
              <button onClick={()=>{ this.setState({err:null,info:null}); this.props.onNav && this.props.onNav('home'); }} style={{fontFamily:F.disp, fontWeight:800, fontSize:11, textTransform:'uppercase', letterSpacing:'.04em', padding:'8px 14px', border:`2px solid ${C.line}`, background:C.ink, color:C.paper, cursor:'pointer'}}>← Back to Home</button>
              <button onClick={()=>this.setState({err:null,info:null})} style={{fontFamily:F.disp, fontWeight:800, fontSize:11, textTransform:'uppercase', letterSpacing:'.04em', padding:'8px 14px', border:`2px solid ${C.line}`, background:C.paper, color:C.tx, cursor:'pointer'}}>↻ Retry this stage</button>
            </div>
            {stack && <details style={{marginTop:12}}><summary style={{cursor:'pointer', fontSize:9.5, color:C.tx3}}>component stack</summary>
              <div style={{marginTop:6, padding:'8px 10px', background:C.bg3, border:`1px solid ${C.line2}`, fontSize:9.5, color:C.tx3, whiteSpace:'pre-wrap', maxHeight:200, overflow:'auto'}}>{stack}</div></details>}
          </div>
        </div>
      </div>
    );
  }
}

function App() {
  const [active, setActive] = useState(()=> localStorage.getItem('es_stage') || 'home');
  const [theme, setTheme]   = useState(()=> localStorage.getItem('es_theme') || 'mono');

  useEffect(()=>{ document.documentElement.dataset.theme = theme; localStorage.setItem('es_theme', theme); }, [theme]);
  const nav = (id)=>{ setActive(id); localStorage.setItem('es_stage', id);
    const m = document.querySelector('main'); if (m) m.scrollTop = 0; };

  const registry = {
    home:window.StageHome, setup:window.StageSetup, products:window.StageProducts,
    network:window.StageNetwork,
    demand:window.StageDemand, plan:window.StagePlan, production:window.StageProduction,
    sourcing:window.StageSourcing, logistics:window.StageLogistics, finance:window.StageFinance,
    console:window.StageConsole, scenarios:window.StageScenarios, reference:window.StageReference,
  };
  const Stage = registry[active];

  return (
    <React.Fragment>
      <Chrome active={active} onNav={nav} theme={theme} onTheme={setTheme}>
        <ErrorBoundary stageKey={active} onNav={nav}>
          {Stage ? <Stage onNav={nav}/> : (
            <div style={{padding:40, fontFamily:F.mono, color:C.tx3}}>Stage "{active}" not yet wired.</div>
          )}
        </ErrorBoundary>
      </Chrome>
      {/* Batch 5 — first-run greeting that sets the planning profile (overlays all). */}
      <OnboardingWizard/>
    </React.Fragment>
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
