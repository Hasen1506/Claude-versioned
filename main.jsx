// ════════════════════════════════════════════════════════════════════════
// main.jsx — App: theme + active-stage state (persisted), router, mount.
// ════════════════════════════════════════════════════════════════════════
function App() {
  const [active, setActive] = useState(()=> localStorage.getItem('es_stage') || 'home');
  const [theme, setTheme]   = useState(()=> localStorage.getItem('es_theme') || 'mono');

  useEffect(()=>{ document.documentElement.dataset.theme = theme; localStorage.setItem('es_theme', theme); }, [theme]);
  const nav = (id)=>{ setActive(id); localStorage.setItem('es_stage', id);
    const m = document.querySelector('main'); if (m) m.scrollTop = 0; };

  const registry = {
    home:window.StageHome, setup:window.StageSetup, products:window.StageProducts,
    demand:window.StageDemand, plan:window.StagePlan, production:window.StageProduction,
    sourcing:window.StageSourcing, logistics:window.StageLogistics, finance:window.StageFinance,
    console:window.StageConsole, scenarios:window.StageScenarios, reference:window.StageReference,
  };
  const Stage = registry[active];

  return (
    <Chrome active={active} onNav={nav} theme={theme} onTheme={setTheme}>
      {Stage ? <Stage onNav={nav}/> : (
        <div style={{padding:40, fontFamily:F.mono, color:C.tx3}}>Stage "{active}" not yet wired.</div>
      )}
    </Chrome>
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
