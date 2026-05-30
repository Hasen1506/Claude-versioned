// ════════════════════════════════════════════════════════════════════════
// console.jsx — Optimize & Solve (OptimizeTab) — the god-tab, split per P1:
//   · CARTESIAN SOLVER-MAP (priority layout): 7 solvers plotted on a
//     horizon × decision-domain plane, edges = data hand-offs.
//   · RUN CONSOLE: mode picker + constraint toggles + solve + status.
//   · RESULT SUB-TABS grouped by solver.
// ════════════════════════════════════════════════════════════════════════
function CartesianSolverMap({ sel, onSelect }) {
  const W=640, H=420, m=46;                 // plot margins
  const px = x => m + x*(W-m-16);
  const py = y => (H-m) - y*(H-m-16);       // y up
  const stCol = { done:C.gn, running:C.ac, queued:C.tx3, idle:C.tx3 };
  const byId = Object.fromEntries(M.solvers.map(s=>[s.id,s]));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', height:'100%', display:'block'}}>
      <defs>
        <marker id="cah" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6 Z" fill={C.tx2}/></marker>
      </defs>
      {/* quadrant tints */}
      <rect x={m} y="16" width={(W-m-16)/2} height={(H-m-16)/2} fill={C.ac} opacity=".05"/>
      <rect x={m+(W-m-16)/2} y="16" width={(W-m-16)/2} height={(H-m-16)/2} fill={C.a2} opacity=".05"/>
      {/* gridlines */}
      {[0,.25,.5,.75,1].map((g,i)=>(<g key={i}>
        <line x1={px(g)} y1="16" x2={px(g)} y2={H-m} stroke={C.line2} strokeWidth=".7"/>
        <line x1={m} y1={py(g)} x2={W-16} y2={py(g)} stroke={C.line2} strokeWidth=".7"/>
      </g>))}
      {/* axes */}
      <line x1={m} y1={H-m} x2={W-16} y2={H-m} stroke={C.line} strokeWidth="2"/>
      <line x1={m} y1="16" x2={m} y2={H-m} stroke={C.line} strokeWidth="2"/>
      {/* axis labels */}
      <text x={(W+m)/2} y={H-12} fontFamily={F.mono} fontSize="9.5" fill={C.tx2} textAnchor="middle" letterSpacing="1">HORIZON · OPERATIONAL → STRATEGIC →</text>
      <text x="14" y={(H-m)/2} fontFamily={F.mono} fontSize="9.5" fill={C.tx2} textAnchor="middle" letterSpacing="1" transform={`rotate(-90 14 ${(H-m)/2})`}>DOMAIN · EXECUTION → FINANCIAL →</text>
      {/* quadrant captions */}
      <text x={px(.02)} y={py(.97)} fontFamily={F.disp} fontSize="9" fontWeight="800" fill={C.tx3}>TACTICAL · FINANCIAL</text>
      <text x={px(.62)} y={py(.97)} fontFamily={F.disp} fontSize="9" fontWeight="800" fill={C.tx3}>STRATEGIC · FINANCIAL</text>
      <text x={px(.02)} y={py(.04)} fontFamily={F.disp} fontSize="9" fontWeight="800" fill={C.tx3}>EXECUTION</text>
      <text x={px(.62)} y={py(.04)} fontFamily={F.disp} fontSize="9" fontWeight="800" fill={C.tx3}>NETWORK</text>
      {/* edges (feeds) */}
      {M.solvers.map(s=> s.feeds.map((f,j)=>{ const t=byId[f]; if(!t) return null;
        return <line key={s.id+f+j} x1={px(s.x)} y1={py(s.y)} x2={px(t.x)} y2={py(t.y)} stroke={C.tx2} strokeWidth="1.3" markerEnd="url(#cah)" opacity=".5"/>;
      }))}
      {/* nodes */}
      {M.solvers.map(s=>{ const x=px(s.x), y=py(s.y), on=sel===s.id;
        return (
          <g key={s.id} style={{cursor:'pointer'}} onClick={()=>onSelect(s.id)}>
            <rect x={x-52} y={y-19} width="104" height="38" fill={on?C.ink:C.paper} stroke={on?C.ac:C.line} strokeWidth={on?3:2}/>
            <rect x={x-52} y={y-19} width="5" height="38" fill={stCol[s.status]}/>
            <text x={x-42} y={y-4} fontFamily={F.disp} fontWeight="800" fontSize="10.5" fill={on?C.paper:C.tx}>{s.name}</text>
            <text x={x-42} y={y+9} fontFamily={F.mono} fontSize="8" fill={on?C.ac:C.tx3}>{s.engine} · {s.obj}</text>
          </g>
        );
      })}
    </svg>
  );
}

function StageConsole({ onNav }) {
  const [sel, setSel] = useState('procure');          // selected solver (map ↔ results)
  const [modes, setModes] = useState(()=>M.solverModes.filter(m=>m.sel).map(m=>m.id));
  const [cons, setCons] = useState(()=>Object.fromEntries(M.constraints.map(c=>[c.id,c.on])));
  const resultKey = { profit:'profit', procure:'procurement', produce:'production', transport:'transport', montecarlo:'risk', capital:'capital', sop:'sop' }[sel] || 'procurement';
  const sections = M.consoleResults[resultKey] || [];
  const selSolver = M.solvers.find(s=>s.id===sel);

  return (
    <div>
      <StageHeader n="09" title="Optimize & Solve Console" kicker="7 MILP/LP/sim solvers on a horizon × domain plane · run control · solver-grouped results (P1)"
        right={<Btn kind="accent">⚡ Solve all queued</Btn>}/>

      <div style={{padding:14, display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:14}}>
        {/* CARTESIAN SOLVER MAP */}
        <Card icon="🧭" title="Cartesian Solver Map" badge="7 solvers" badgeTone="y" info={{ what:'Solvers placed by planning horizon (x) and decision domain (y); arrows are data hand-offs.', flows:'Click a node → its run mode + results.' }}
          dev={{ comp:'SolverMap', props:'solvers, sel, onSelect', note:'Bespoke Cartesian layout (priority).' }} style={{minHeight:470}}>
          <div style={{height:430}}><CartesianSolverMap sel={sel} onSelect={setSel}/></div>
        </Card>

        {/* RUN CONSOLE */}
        <div style={{display:'flex', flexDirection:'column', gap:14}}>
          <Card icon="⚡" title="Run Console" badge="mode + constraints" info={{ what:'Pick solver mode(s), toggle constraints, solve.', flows:'POSTs to /api/solve/*.' }}
            dev={{ comp:'OptimizeTab', props:'state, dispatch(SOLVE_FINISHED)', state:'solve.mode, solve.constraints', note:'Run control only — results split out per P1.' }}>
            <SubLabel>Solver mode</SubLabel>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:5}}>
              {M.solverModes.map(m=>{ const on=modes.includes(m.id);
                return (
                  <button key={m.id} onClick={()=>setModes(s=> on?s.filter(x=>x!==m.id):[...s,m.id])} style={{
                    textAlign:'left', padding:'6px 8px', border:`2px solid ${C.line}`, cursor:'pointer',
                    background: on?C.ink:C.paper, color: on?C.ac:C.tx, fontFamily:F.disp, fontSize:10, fontWeight:700,
                    display:'flex', alignItems:'center', gap:6,
                  }}>
                    <span style={{width:9, height:9, flexShrink:0, background: on?C.ac:'transparent', border:`1.5px solid ${on?C.ac:C.line2}`}}/>
                    {m.label}
                  </button>
                );
              })}
            </div>
            <div style={{marginTop:10}}><SubLabel>Constraints</SubLabel></div>
            <div style={{display:'flex', flexWrap:'wrap', gap:5}}>
              {M.constraints.map(c=>{ const on=cons[c.id];
                return (
                  <button key={c.id} onClick={()=>setCons(s=>({...s,[c.id]:!s[c.id]}))} style={{
                    padding:'4px 8px', border:`2px solid ${C.line}`, cursor:'pointer', fontFamily:F.mono, fontSize:9.5, fontWeight:700,
                    background: on?C.ac:C.paper, color: on?C.onAc:C.tx3, textTransform:'uppercase',
                  }}>{on?'✓ ':'○ '}{c.label}</button>
                );
              })}
            </div>
            <div style={{marginTop:12, display:'flex', gap:8}}>
              <Btn kind="primary" style={{flex:1, justifyContent:'center'}}>▶ SOLVE ({modes.length})</Btn>
              <Btn kind="secondary">Reset</Btn>
            </div>
          </Card>

          <Card icon="📡" title="Solve Status" badge={selSolver?selSolver.status:'idle'} badgeTone="k" info={{ what:'Objective, runtime and binding constraints of the last solve.', flows:'Status → pipeline ribbon.' }}
            dev={{ comp:'SolveStatus', props:'solve.result' }}>
            <KpiRow cols={3}>
              <Blk label="Status" value={selSolver?selSolver.status:'—'} tone={selSolver&&selSolver.status==='done'?'y':'c'}/>
              <Blk label="Objective" value={selSolver?selSolver.obj:'—'}/>
              <Blk label="Runtime" value={selSolver&&selSolver.t?`${selSolver.t}s`:'—'}/>
            </KpiRow>
            <div style={{marginTop:10}}><SubLabel>Shadow prices · binding</SubLabel></div>
            <DataTable dense cols={['Resource','Dual','Status']} align={['left','right','left']}
              rows={M.shadow.filter(s=>s.binding).map(s=>[s.res, `₹${s.dual.toFixed(0)}`, <Tag c="k">BIND</Tag>])}/>
          </Card>
        </div>
      </div>

      {/* RESULT SUB-TABS grouped by solver */}
      <div style={{padding:'0 14px 14px'}}>
        <div style={{border:`2px solid ${C.line}`, background:C.bg2}}>
          <div style={{display:'flex', flexWrap:'wrap', borderBottom:`2px solid ${C.line}`}}>
            {[['profit','Profit'],['procure','Procurement'],['produce','Production'],['transport','Transport'],['montecarlo','Risk/MC'],['capital','Capital'],['sop','S&OP']].map(([id,lbl])=>{
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
            <ConsoleResults solver={sel} sections={sections}/>
          </div>
        </div>
      </div>
    </div>
  );
}

// result sections — hero example fully built per group + section grid
function ConsoleResults({ solver, sections }) {
  return (
    <div>
      {solver==='procure'  && <ResProcure/>}
      {solver==='produce'  && <ResProduce/>}
      {solver==='profit'   && <ResProfit/>}
      {solver==='transport'&& <ResTransport/>}
      {solver==='montecarlo'&& <ResRisk/>}
      {solver==='capital'  && <ResCapital/>}
      {solver==='sop'      && <ResSOP/>}
      <div style={{marginTop:14}}>
        <SubLabel>All {sections.length} result sections in this group</SubLabel>
        <Grid cols={4} gap={8}>
          {sections.map((s,i)=>(
            <div key={i} style={{border:`2px solid ${C.line2}`, background:C.paper, padding:'8px 10px', display:'flex', alignItems:'center', gap:7}}>
              <span style={{width:7, height:7, background: i===0?C.gn:C.tx3, flexShrink:0}}/>
              <span style={{fontFamily:F.disp, fontSize:10.5, fontWeight:700}}>{s}</span>
            </div>
          ))}
        </Grid>
      </div>
    </div>
  );
}

function ResProcure() {
  return (
    <Grid cols={2}>
      <Card icon="📦" title="Procurement MILP Results" badge="₹3.12 Cr" badgeTone="y" info={{ what:'Optimal PO plan minimising inventory + ordering cost.', flows:'POs → Sourcing release plan.' }}
        dev={{ comp:'ProcurementResults', props:'solve.procurement' }}>
        <DataTable dense cols={['PO','Part','Supplier','Qty','Week','Value']} align={['left','left','left','right','left','right']}
          rows={M.poRegister.map(p=>[p.po, p.part, p.sup, p.qty.toLocaleString('en-IN'), p.wk, `₹${(p.val/1000).toFixed(0)}K`])}
          foot={['TOTAL','','','—','','₹11.4L']}/>
      </Card>
      <Card icon="🌐" title="Multi-Echelon Inventory" badge="2-echelon" info={{ what:'Optimal stock split plant ↔ DC.', flows:'Targets → reorder policy.' }}
        dev={{ comp:'MultiEchelonCard', props:'solve.procurement.echelon' }}>
        <DataTable dense cols={['Echelon','Item','Target','Safety']} align={['left','left','right','right']}
          rows={[['Plant','RM-STL42','3,200','420'],['Plant','RM-BRG18','1,800','240'],['DC-BLR','TPA-3215','620','90'],['DC-PUN','TPA-9904','180','30']]}/>
      </Card>
      <Card icon="📋" title="Reorder Policy (s,S) / (R,Q)" badge="per part" info={{ what:'Computed reorder point & order-up-to / qty.', flows:'Policy → MRP.' }} span={2}
        dev={{ comp:'ReorderPolicyCard', props:'solve.procurement.policy' }}>
        <DataTable dense cols={['Part','Policy','s / R','S / Q','Review']} align={['left','left','right','right','left']}
          rows={[['RM-STL42','(s,S)','2,400','4,800','continuous'],['RM-BRG18','(R,Q)','—','1,500','weekly'],['CN-SEAL9','(s,S)','1,200','6,000','continuous']]}/>
      </Card>
    </Grid>
  );
}

function GanttChart() {
  const wk=18;
  return (
    <svg viewBox={`0 0 720 150`} style={{width:'100%', height:150, display:'block'}}>
      {[...Array(wk)].map((_,i)=>(<line key={i} x1={70+i*36} y1="10" x2={70+i*36} y2="140" stroke={C.line2} strokeWidth=".6"/>))}
      {M.gantt.map((ln,li)=>{ const y=24+li*40;
        return (<g key={li}>
          <text x="8" y={y+16} fontFamily={F.mono} fontSize="9.5" fontWeight="700" fill={C.tx}>{ln.line}</text>
          {ln.jobs.map((j,ji)=>(
            <g key={ji}>
              <rect x={70+j.s*36} y={y} width={j.d*36-3} height="26" fill={j.util>.85?C.ink:j.util>.7?C.ac:C.bg4} stroke={C.line} strokeWidth="1.5"/>
              <text x={70+j.s*36+4} y={y+16} fontFamily={F.mono} fontSize="8" fill={j.util>.85?C.ac:C.tx} fontWeight="700">{j.sku.slice(4)}</text>
            </g>
          ))}
        </g>);
      })}
    </svg>
  );
}

function ResProduce() {
  return (
    <Grid cols={1}>
      <Card icon="📅" title="Production Schedule · Gantt" badge="3 lines · 18 wk" badgeTone="y" info={{ what:'Sequenced jobs per line over the horizon.', flows:'Schedule → shop-floor execution.' }}
        dev={{ comp:'GanttCard', props:'solve.production.schedule' }}>
        <GanttChart/>
        <div style={{marginTop:6, display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2}}>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ink}}/>util &gt;85%</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.ac}}/>70–85%</span>
          <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.bg4}}/>&lt;70%</span>
        </div>
      </Card>
      <Grid cols={2}>
        <Card icon="📦" title="Product Fulfillment" badge="vs demand" info={{ what:'Met vs unmet demand per SKU.', flows:'Gaps → lost sales.' }}
          dev={{ comp:'FulfillmentCard', props:'solve.production.fulfil' }}>
          <DataTable dense cols={['SKU','Demand','Made','Fill']} align={['left','right','right','right']}
            rows={[['TPA-4471','2840','2840','100%'],['TPA-3215','4120','3980','97%'],['TPA-2188','920','840','91%']]}/>
        </Card>
        <Card icon="💤" title="Shutdown Candidates" badge="low util" info={{ what:'Lines/shifts worth idling.', flows:'Cost saving option.' }}
          dev={{ comp:'ShutdownCard', props:'solve.production.shutdown' }}>
          <div style={{padding:'10px', border:`2px solid ${C.line}`, background:C.bg3}}>
            <div style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>LINE-03 · Shift B</div>
            <div style={{fontFamily:F.mono, fontSize:10, color:C.tx3, marginTop:3}}>55% util in W01–W03 · idle saves ₹2.1L</div>
          </div>
        </Card>
      </Grid>
    </Grid>
  );
}

function ResProfit() {
  return (
    <Grid cols={2}>
      <Card icon="💰" title="Profit Maximizer Results" badge="₹6.84 Cr" badgeTone="y" info={{ what:'Optimal product mix maximising contribution.', flows:'Mix → procurement & production targets.' }} span={2}
        dev={{ comp:'ProfitResults', props:'solve.profit' }}>
        <DataTable cols={['SKU','Optimal Qty','Price','Unit Cost','Contribution','% of profit']} align={['left','right','right','right','right','right']}
          rows={M.products.filter(p=>p.cat==='Finished').map(p=>{ const c=(p.price-p.cost)*p.demand;
            return [p.sku, p.demand.toLocaleString('en-IN'), `₹${p.price}`, `₹${p.cost}`, `₹${(c/100000).toFixed(1)}L`, `${Math.round(c/6840000*100)}%`];
          })}
          foot={['TOTAL','','','','₹68.4L','100%']}/>
      </Card>
    </Grid>
  );
}

function ResTransport() {
  return (
    <Grid cols={2}>
      <Card icon="🚛" title="Transport Results" badge="₹24.8 L" info={{ what:'Optimal mode/lane allocation.', flows:'Bookings → 3PL.' }}
        dev={{ comp:'TransportResults', props:'solve.transport' }}>
        <DataTable dense cols={['Lane','Mode','Volume','Cost']} align={['left','left','right','right']}
          rows={[['CHN→BLR','FTL','42 t','₹4.8L'],['CHN→PUN','Rail','68 t','₹6.2L'],['PUN→GGN','LTL','24 t','₹8.4L'],['BLR→GGN','Air','6 t','₹5.4L']]}/>
      </Card>
      <Card icon="📦" title="Consolidation Plan" badge="LTL→FTL" info={{ what:'Where consolidating shipments cuts cost.', flows:'Plan → carrier booking.' }}
        dev={{ comp:'ConsolidationCard', props:'solve.transport.consol' }}>
        <Blk label="Consolidation saving" value="₹ 3.2 L/yr" tone="y"/>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2, lineHeight:1.5}}>Merge 3 weekly LTL CHN→PUN into 1 FTL — 22% unit cost cut, +0.5d transit.</div>
      </Card>
    </Grid>
  );
}

function McChart() {
  const b=M.mcBuckets, mxN=Math.max(...b.map(x=>x.n));
  return (
    <svg viewBox="0 0 460 160" style={{width:'100%', height:160, display:'block'}}>
      {b.map((x,i)=>{ const h=x.n/mxN*120, bx=20+i*32;
        return <rect key={i} x={bx} y={140-h} width="26" height={h} fill={x.x>=518?C.dg:C.ink}/>;
      })}
      <line x1={20+8*32+13} y1="10" x2={20+8*32+13} y2="145" stroke={C.ac2} strokeWidth="2" strokeDasharray="4 2"/>
      <text x={20+8*32+16} y="20" fontFamily={F.mono} fontSize="8.5" fill={C.tx2}>mean 478</text>
    </svg>
  );
}

function ResRisk() {
  const s=M.mcStats;
  return (
    <Grid cols={2}>
      <Card icon="🎲" title="Monte Carlo Results" badge="1,000 runs" badgeTone="y" info={{ what:'Total-cost distribution under uncertainty.', flows:'Risk → CVaR & hedging.' }} span={2}
        dev={{ comp:'MonteCarloResults', props:'solve.montecarlo', note:'montecarlo.py backend.' }}>
        <McChart/>
        <KpiRow cols={5}>
          <Blk label="Mean" value={`₹${s.mean}L`}/>
          <Blk label="Median" value={`₹${s.median}L`}/>
          <Blk label="P95" value={`₹${s.p95}L`} accent={C.a4}/>
          <Blk label="CVaR 95%" value={`₹${s.cvar95}L`} accent={C.dg}/>
          <Blk label="Fragility" value={s.fragility} tone="y"/>
        </KpiRow>
      </Card>
    </Grid>
  );
}

function ResCapital() {
  return (
    <Grid cols={2}>
      <Card icon="🏗️" title="Capital Budget Results" badge="endogenous" badgeTone="y" info={{ what:'Optimal capacity investments from duals.', flows:'CapEx → Finance verdict.' }} span={2}
        dev={{ comp:'CapitalResults', props:'solve.capital', note:'capital.py backend.' }}>
        <DataTable cols={['Investment','CapEx','ΔCapacity','NPV','IRR','Decision']} align={['left','right','right','right','right','left']}
          rows={[['Heat-Treat #2','₹1.8 Cr','+38%','₹24L','19.2%',<Tag c="g">FUND</Tag>],['Grinder upgrade','₹0.9 Cr','+12%','₹14L','16.4%',<Tag c="g">FUND</Tag>],['Honing cell','₹1.2 Cr','+9%','₹9L','13.1%',<Tag c="w">DEFER</Tag>]]}/>
      </Card>
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
      <Card icon="🔗" title="Pipeline (3 steps)" badge="profit→procure→produce" info={{ what:'End-to-end chained solve.', flows:'Each step seeds the next.' }}
        dev={{ comp:'PipelineCard', props:'solve.pipeline' }}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {[['Profit Mix','₹6.84 Cr',C.gn],['Procurement','₹3.12 Cr',C.ac],['Production','₹42 L',C.tx3]].map((s,i)=>(
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
