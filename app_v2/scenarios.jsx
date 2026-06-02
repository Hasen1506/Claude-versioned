// ════════════════════════════════════════════════════════════════════════
// scenarios.jsx — Risk & Scenarios (AnalysisTab). Sub-tabbed per P2:
// Risk · Cost · Performance · Explore.
// ════════════════════════════════════════════════════════════════════════
function StageScenarios({ onNav }) {
  const [sub, setSub] = useState('risk');
  const tabs = M.scenarioSubtabs.map(t=>({ id:t.id, n:t.n, label:t.label, count:t.count }));
  return (
    <div>
      <StageHeader n="11" title="Risk & Scenarios" kicker="Control tower · Monte Carlo · sensitivity · TCO · what-if — sub-tabbed by intent (P2)"
        right={<Btn kind="secondary">📄 Report export</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='risk'    && <ScnRisk/>}
        {sub==='cost'    && <ScnCost/>}
        {sub==='explore' && <ScnExplore/>}
      </div>
    </div>
  );
}

function Tornado() {
  const t=M.tornado, mx=Math.max(...t.flatMap(r=>[Math.abs(r.low),r.high]))*1.1;
  return (
    <svg viewBox={`0 0 480 ${t.length*26+20}`} style={{width:'100%', height:t.length*26+20, display:'block'}}>
      <line x1="240" y1="6" x2="240" y2={t.length*26+6} stroke={C.line} strokeWidth="1.5"/>
      {t.map((r,i)=>{ const y=14+i*26;
        const lw=Math.abs(r.low)/mx*220, hw=r.high/mx*220;
        return (<g key={i}>
          <rect x={240-lw} y={y-8} width={lw} height="16" fill={C.dg}/>
          <rect x="240" y={y-8} width={hw} height="16" fill={C.gn}/>
          <text x="234" y={y+4} fontFamily={F.mono} fontSize="8.5" fill={C.tx} textAnchor="end" style={{display:lw>40?'block':'none'}}>{r.low}%</text>
          <text x="246" y={y+4} fontFamily={F.mono} fontSize="8.5" fill="#fff" style={{display:hw>40?'block':'none'}}>+{r.high}%</text>
        </g>);
      })}
    </svg>
  );
}

function ScnRisk() {
  return (
    <>
    <Grid cols={2}>
      <Card icon="🚨" title="Control Tower" badge={`${M.controlTower.length} alerts · full list`} badgeTone="k" info={{ what:'The full exception list (Home shows the top 3 of this same source).', flows:'Drill into owning stage.' }}
        dev={{ comp:'ControlTower', props:'alerts (shared with Home)', state:'analysis.alerts[]' }}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {M.controlTower.map((a,i)=>{ const sc=a.sev==='H'?C.dg:a.sev==='M'?C.a4:C.tx3;
            return (<div key={i} style={{display:'flex', alignItems:'center', gap:9, border:`2px solid ${C.line}`, padding:'7px 9px', borderLeft:`5px solid ${sc}`}}>
              <span style={{width:20, height:20, flexShrink:0, display:'grid', placeItems:'center', background:sc, color:'#fff', fontFamily:F.disp, fontWeight:900, fontSize:10}}>{a.sev}</span>
              <span style={{fontFamily:F.body, fontSize:11.5, fontWeight:600, flex:1}}>{a.msg}</span>
              <Tag c="w">{a.area}</Tag><span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{a.t}</span>
            </div>);
          })}
        </div>
      </Card>
      <Card icon="📊" title="Sensitivity (Tornado)" badge="±% on cost" info={{ what:'Which parameters move total cost most.', flows:'Top drivers → hedging & focus.' }}
        dev={{ comp:'SensitivityCard', props:'analysis.tornado' }}>
        <Tornado/>
      </Card>
      <Card icon="⚠" title="Risk Matrix" badge="prob × impact" info={{ what:'Heat map of risks by probability and impact.', flows:'High cells → mitigation.' }}
        dev={{ comp:'RiskMatrixCard', props:'analysis.risks', state:'analysis.riskMatrix' }}>
        <div style={{display:'grid', gridTemplateColumns:'46px 1fr 1fr 1fr', gap:4}}>
          <div/>{['Low','Med','High'].map(h=><div key={h} style={{fontFamily:F.mono, fontSize:9, color:C.tx3, textAlign:'center'}}>{h} impact</div>)}
          {M.riskMatrix.map((row,ri)=>(
            <React.Fragment key={ri}>
              <div style={{fontFamily:F.mono, fontSize:9, color:C.tx3, display:'grid', placeItems:'center'}}>{row.p}</div>
              {row.cells.map((n,ci)=>{ const score=(2-ri)+ci;
                const col = score>=3?C.dg:score>=2?C.a4:C.gn;
                return <div key={ci} style={{height:48, border:`2px solid ${C.line}`, background:col, color:'#fff', display:'grid', placeItems:'center', fontFamily:F.disp, fontWeight:900, fontSize:16}}>{n}</div>;
              })}
            </React.Fragment>
          ))}
        </div>
      </Card>
      <Card icon="⚡" title="Disruption Registry" badge={`${M.disruptions.length}`} info={{ what:'Catalogued disruption events with mitigation.', flows:'Feeds Monte Carlo scenarios.' }}
        dev={{ comp:'DisruptionRegistryCard', props:'analysis.disruptions', state:'analysis.disruptions[]' }}>
        <DataTable dense cols={['Event','Prob','Impact','Mitigation']} align={['left','left','right','left']}
          rows={M.disruptions.map(d=>[d.event, d.prob, d.impact, d.mitig])}/>
      </Card>
      <Card icon="🩸" title="Lost Sales" badge="unmet" info={{ what:'Demand that could not be served.', flows:'Lost margin → service-level tuning.' }}
        dev={{ comp:'LostSalesCard', props:'solve.production.fulfil' }}>
        <KpiRow cols={2}>
          <Blk label="Units Lost" value="220 u" accent={C.dg}/>
          <Blk label="Lost Margin" value="₹ 1.6 L" tone="c"/>
        </KpiRow>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2}}>TPA-2188 capacity-bound in Q3 — LINE-03 investment recovers it.</div>
      </Card>
    </Grid>
    {/* governance garnish, not core planning — demoted behind Advanced (app_v2) */}
    <Advanced label="Stakeholder map · governance (not core planning)" count={M.stakeholders.length}>
      <Card icon="👥" title="Stakeholder Power × Interest" badge={`${M.stakeholders.length}`} info={{ what:'Engagement quadrant for stakeholders.', flows:'Comms plan.' }}
        dev={{ comp:'StakeholderMatrixCard', props:'analysis.stakeholders' }}>
        <DataTable dense cols={['Stakeholder','Power','Interest','Strategy']} align={['left','center','center','left']}
          rows={M.stakeholders.map(s=>[s.name, s.power, s.interest, s.q])}/>
      </Card>
    </Advanced>
    </>
  );
}

function ScnCost() {
  const cw=M.costWaterfall;
  return (
    <Grid cols={2}>
      <Card icon="📊" title="Cost Waterfall" badge="₹12.64 Cr" badgeTone="y" info={{ what:'Build-up of total cost by category.', flows:'Cost structure → savings hunt.' }} span={2}
        dev={{ comp:'CostWaterfallCard', props:'analysis.costStructure' }}>
        <svg viewBox="0 0 700 170" style={{width:'100%', height:170, display:'block'}}>
          {(()=>{ let cum=0; const mx=12.64;
            return cw.map((d,i)=>{ const x=30+i*112, h=d.v/mx*130;
              const y = d.total ? 150-h : 150-(cum+d.v)/mx*130;
              const bar = d.total ? <rect x={x} y={150-h} width="80" height={h} fill={C.ink}/> : <rect x={x} y={150-(cum+d.v)/mx*130} width="80" height={d.v/mx*130} fill={C.ac}/>;
              const out=(<g key={i}>{bar}
                <text x={x+40} y="163" fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{d.k}</text>
                <text x={x+40} y={(d.total?150-h:150-(cum+d.v)/mx*130)-4} fontFamily={F.disp} fontSize="10" fontWeight="700" fill={C.tx} textAnchor="middle">₹{d.v}</text>
              </g>);
              if(!d.total) cum+=d.v; return out;
            });
          })()}
        </svg>
      </Card>
      <Card icon="🏗️" title="TCO per SKU" badge="total cost of ownership" info={{ what:'Unit + holding + ordering + quality + obsolescence.', flows:'TCO → true profitability.' }} span={2}
        dev={{ comp:'TCOCard', props:'analysis.tco' }}>
        <DataTable cols={['SKU','Unit','Holding','Ordering','Quality','Obsol.','TCO/u']} align={['left','right','right','right','right','right','right']}
          rows={M.tco.map(t=>({cells:[t.sku, `₹${t.unit}`, `₹${t.hold}`, `₹${t.order}`, `₹${t.quality}`, `₹${t.obsol}`, <span style={{fontWeight:700, color:C.dg}}>₹{t.tco}</span>]}))}/>
      </Card>
    </Grid>
  );
}

function ScnExplore() {
  return (
    <Grid cols={2}>
      <Card icon="🤖" title="What-If Bot" badge="natural language" badgeTone="y" info={{ what:'Ask a scenario in plain language; bot reruns affected solvers.', flows:'Scenario → delta vs base.' }}
        right={<Tag c="a">preview</Tag>}
        dev={{ comp:'WhatIfBot', props:'state, dispatch', note:'Backed by /api/whatif — preview until wired.' }}>
        <div style={{border:`2px solid ${C.line}`, padding:'8px 10px', display:'flex', alignItems:'center', gap:8, background:C.paper}}>
          <span style={{fontFamily:F.mono, fontSize:11, color:C.tx3}}>›</span>
          <input defaultValue="Material cost up 20% for Q3" style={{flex:1, border:'none', outline:'none', fontFamily:F.mono, fontSize:11, background:'transparent', color:C.tx}}/>
          <Btn kind="primary" sm>Run</Btn>
        </div>
        <div style={{marginTop:8, display:'flex', flexWrap:'wrap', gap:5}}>
          {M.whatif.map((w,i)=><span key={i} style={{fontFamily:F.mono, fontSize:9, padding:'3px 7px', border:`1.5px solid ${C.line2}`, color:C.tx2, cursor:'pointer'}}>{w}</span>)}
        </div>
        <div style={{marginTop:10}}><KpiRow cols={3}>
          <Blk label="Δ Total Cost" value="+₹1.4Cr" accent={C.dg}/>
          <Blk label="Δ Margin" value="-3.8pp" accent={C.dg}/>
          <Blk label="Re-source?" value="YES" tone="y"/>
        </KpiRow></div>
      </Card>
      <Card icon="🧠" title="Live Insight" badge="streaming" info={{ what:'Continuously surfaces notable changes.', flows:'Insight → control tower.' }}
        right={<Tag c="a">preview</Tag>}
        dev={{ comp:'InsightEngineCard', props:'state (observer)', note:'Backed by /api/ai/insights — preview until wired.' }}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {['POSCO LT slip raises CVaR by ₹10L','Line-03 the binding constraint in 4/6 months','Lease beats buy on CNC by ₹5L PV','EUR exposure unhedged — ₹1.8L at risk'].map((t,i)=>(
            <div key={i} style={{border:`2px solid ${C.line2}`, padding:'7px 9px', fontFamily:F.body, fontSize:11.5, display:'flex', gap:8, alignItems:'center'}}>
              <span style={{width:6, height:6, background:C.ac, flexShrink:0}}/>{t}
            </div>
          ))}
        </div>
      </Card>
      <Card icon="🔬" title="Auto-Researcher" badge="agentic" info={{ what:'Sweeps parameter space for better plans.', flows:'Proposals → human review.' }}
        right={<Tag c="a">preview</Tag>}
        dev={{ comp:'AutoResearcherCard', props:'state, searchSpace', note:'Backed by /api/solve/researcher — preview until wired.' }}>
        <DataTable dense cols={['Hypothesis','Δ Cost','Verdict']} align={['left','right','left']}
          rows={[['Dual-source RM-BRG18','-₹8L',<Tag c="g">adopt</Tag>],['Raise SL to 98%','+₹12L',<Tag c="r">reject</Tag>],['Prebuild May +480u','-₹3L',<Tag c="g">adopt</Tag>]]}/>
      </Card>
      <Card icon="🔗" title="Parameter Cascade" badge="trace" info={{ what:'Traces how one parameter ripples through the model.', flows:'Explainability.' }}
        dev={{ comp:'CascadeTracker', props:'param, state' }}>
        <div style={{display:'flex', flexWrap:'wrap', gap:6, alignItems:'center'}}>
          {M.cascade.map((c,i)=>(<React.Fragment key={i}>
            <span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, padding:'4px 8px', border:`2px solid ${C.line}`, background: i===0?C.ac:C.paper}}>{c.replace('→ ','')}</span>
            {i<M.cascade.length-1 && <span style={{color:C.tx3}}>→</span>}
          </React.Fragment>))}
        </div>
      </Card>
      <Card icon="📋" title="Multi-SKU Comparison" badge="15-section" info={{ what:'Side-by-side SKU economics across all metrics.', flows:'Portfolio view.' }} span={2}
        dev={{ comp:'MultiSKU15', props:'products', note:'15-section comparison.' }}>
        <DataTable dense cols={['SKU','ABC/XYZ','Demand','Margin %','TCO/u','Service','Fill']} align={['left','left','right','right','right','right','right']}
          rows={M.products.filter(p=>p.cat==='Finished').map(p=>[p.sku, `${p.abc}${p.xyz}`, p.demand.toLocaleString('en-IN'), `${Math.round((1-p.cost/p.price)*100)}%`, `₹${Math.round(p.cost*1.14)}`, `${p.sl}%`, p.abc==='A'?'100%':p.abc==='B'?'94%':'88%'])}/>
      </Card>
    </Grid>
  );
}
window.StageScenarios = StageScenarios;
