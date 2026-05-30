// ════════════════════════════════════════════════════════════════════════
// reference.jsx — Reference. Sub-tabs: Learning Lab · SAP Mode.
// ════════════════════════════════════════════════════════════════════════
function StageReference({ onNav }) {
  const [sub, setSub] = useState('learn');
  const tabs = [
    { id:'learn', n:'a', label:'Learning Lab', count:M.learnSections.length },
    { id:'sap',   n:'b', label:'SAP Mode', count:M.sapTcodes.length },
  ];
  return (
    <div>
      <StageHeader n="11" title="Reference" kicker="Learning Lab concept explainers · SAP T-code map (parallel multi-plant reference)"/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='learn' && <RefLearn/>}
        {sub==='sap'   && <RefSAP/>}
      </div>
    </div>
  );
}

function RefLearn() {
  const [open, setOpen] = useState(3);
  return (
    <Grid cols={1}>
      <Card icon="📚" title="Learning Lab" badge={`${M.learnSections.length} interactive`} info={{ what:'Supply-chain fundamentals — try each with your own numbers.', flows:'Folds into inline SectionInfo popovers.' }}
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
      <Card icon="🧮" title={M.learnSections[open]} badge="worked" badgeTone="y" info={{ what:'Interactive concept playground.', flows:'Builds intuition.' }}
        dev={{ comp:'ConceptPlayground', props:'concept, inputs' }}>
        <Grid cols={2}>
          <div>
            <SubLabel>Try it</SubLabel>
            <Grid cols={2} gap={8}>
              <Field label="Annual Demand (D)"><NumInput value="2840" suffix="u"/></Field>
              <Field label="Order Cost (S)"><NumInput value="1200" prefix="₹"/></Field>
              <Field label="Holding (h)"><NumInput value="18" suffix="%"/></Field>
              <Field label="Unit Cost (c)"><NumInput value="1190" prefix="₹"/></Field>
            </Grid>
          </div>
          <div>
            <SubLabel>Result</SubLabel>
            <KpiRow cols={1}>
              <Blk label="EOQ = √(2DS/h)" value="320 u" tone="y"/>
              <Blk label="Orders / yr" value="8.9"/>
              <Blk label="Total Cost" value="₹ 6,840 / yr"/>
            </KpiRow>
          </div>
        </Grid>
      </Card>
    </Grid>
  );
}

function RefSAP() {
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
      <Card icon="🔮" title="Stochastic / CVaR Solver" badge="risk-aware" info={{ what:'Risk-averse planning minimising CVaR not just mean.', flows:'Alt objective for Console.' }}
        dev={{ comp:'CVaRSolverCard', props:'solve.cvar' }}>
        <KpiRow cols={2}>
          <Blk label="Mean cost" value="₹478L"/>
          <Blk label="CVaR 95%" value="₹528L" accent={C.dg}/>
          <Blk label="Risk premium" value="₹50L" tone="c"/>
          <Blk label="Mode" value="CVaR" tone="y"/>
        </KpiRow>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.5}}>Trades ₹8L higher mean for ₹22L lower tail — choose per risk appetite.</div>
      </Card>
    </Grid>
  );
}
window.StageReference = StageReference;
