// ════════════════════════════════════════════════════════════════════════
// production.jsx — Production (stage 06, handoff v2 §3.06). 0 sub-tabs guided
// scroll under the item selector. MPS gains a day/week grain toggle (default
// day inside the frozen fence). ATP/CTP & changeover interpreted inline.
// Now OWNS Cycle Time & Line Assignment (moved out of Products).
// ════════════════════════════════════════════════════════════════════════
function StageProduction({ onNav }) {
  const { item } = useActiveItem();
  const p = M.products.find(x=>x.sku===(item&&item.id)) || M.products[0];
  // sub-tabbed to tame density — this was the busiest single-scroll stage
  const [sub, setSub] = useState('arch');
  const tabs = [
    { id:'arch',   label:'Architecture' },
    { id:'cycle',  label:'Cycle & Line' },
    { id:'sched',  label:'Schedule' },
    { id:'change', label:'Changeover' },
  ];
  return (
    <div>
      <StageHeader n="06" title="Production Architecture" kicker="Lines → stages → machines · OEE · bottleneck = min(stage) · cycle/line · MPS(day) · order promising"
        right={<Btn kind="secondary">+ Add line</Btn>}/>
      <ItemSelector/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:18}}>
        {sub==='arch'   && <StageSection step="1" title="Architecture" sub="line → stage → machine tree · the slowest stage caps the line"><ProdArch/></StageSection>}
        {sub==='cycle'  && <StageSection step="2" title={`Cycle & Line · ${p.name}`} sub="cycle time and line assignment are line properties (moved here from Products)"><ProdCycle p={p} onNav={onNav}/></StageSection>}
        {sub==='sched'  && <>
          <StageSection step="3" title="Master Production Schedule" sub="day-level inside the frozen fence, week beyond — a planner reads this by day"><ProdMPS/></StageSection>
          <StageSection step="4" title="Order Promising · ATP / CTP" sub="what you can still promise, read inline"><ProdATP/></StageSection>
        </>}
        {sub==='change' && <StageSection step="5" title="Sequence-Dependent Changeover" sub="the matrix, plus the solver's chosen run order and the minutes it saves"><ProdChange/></StageSection>}
      </div>
    </div>
  );
}

function StageNode({ st }) {
  return (
    <div style={{border:`2px solid ${C.line}`, background: st.bottleneck?C.ac:C.paper, color:C.tx, position:'relative'}}>
      {st.bottleneck && <div style={{position:'absolute', top:-9, right:6, fontFamily:F.mono, fontSize:8, fontWeight:700, background:C.dg, color:'#fff', padding:'1px 5px', border:`1.5px solid ${C.line}`}}>BOTTLENECK</div>}
      <div style={{padding:'7px 9px', borderBottom:`1.5px solid ${C.line}`, display:'flex', justifyContent:'space-between', alignItems:'center'}}>
        <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800}}>{st.name}</span>
        <span style={{fontFamily:F.mono, fontSize:8.5, color: st.bottleneck?C.onAc:C.tx3}}>{st.id}</span>
      </div>
      <div style={{padding:'7px 9px', display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:4, fontFamily:F.mono, fontSize:9.5}}>
        <div><div style={{color: st.bottleneck?C.onAc:C.tx3, fontSize:8}}>MACHINES</div><div className="num" style={{fontWeight:700, fontFamily:F.disp, fontSize:13}}>{st.m}</div></div>
        <div><div style={{color: st.bottleneck?C.onAc:C.tx3, fontSize:8}}>CYCLE</div><div className="num" style={{fontWeight:700, fontFamily:F.disp, fontSize:13}}>{st.ct}</div></div>
        <div><div style={{color: st.bottleneck?C.onAc:C.tx3, fontSize:8}}>OEE</div><div className="num" style={{fontWeight:700, fontFamily:F.disp, fontSize:13}}>{(st.oee*100).toFixed(0)}%</div></div>
      </div>
      <div style={{padding:'4px 9px', borderTop:`1.5px solid ${C.line2}`, fontFamily:F.mono, fontSize:9, display:'flex', justifyContent:'space-between'}}>
        <span style={{color: st.bottleneck?C.onAc:C.tx3}}>CAP</span><span className="num" style={{fontWeight:700}}>{st.cap.toLocaleString('en-IN')} u/mo</span>
      </div>
    </div>
  );
}

function ProdArch() {
  return (
    <div>
      <Grid cols={3}>
        {M.lines.map(line=>(
          <div key={line.id} style={{border:`2px solid ${C.line}`, background:C.bg2}}>
            <div style={{padding:'9px 11px', background:C.ink, color:C.paper, display:'flex', alignItems:'center', gap:8}}>
              <span style={{fontFamily:F.disp, fontSize:13, fontWeight:800}}>{line.id}</span>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.ac}}>{line.name}</span>
              <span style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9}}>OEE {(line.oee*100).toFixed(0)}%</span>
            </div>
            <div style={{padding:11, display:'flex', flexDirection:'column', gap:14}}>
              {line.stages.map((st,i)=>(
                <div key={st.id} style={{position:'relative'}}>
                  <StageNode st={st}/>
                  {i<line.stages.length-1 && <div style={{position:'absolute', left:'50%', bottom:-12, transform:'translateX(-50%)', color:C.tx3, fontSize:13}}>↓</div>}
                </div>
              ))}
            </div>
            <div style={{padding:'8px 11px', borderTop:`2px solid ${C.line}`, background:C.bg3, display:'flex', justifyContent:'space-between', alignItems:'center'}}>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>LINE CAPACITY</span>
              <span className="num" style={{fontFamily:F.disp, fontSize:15, fontWeight:800, color:C.dg}}>{line.cap.toLocaleString('en-IN')} u/mo</span>
            </div>
          </div>
        ))}
      </Grid>
      <div style={{marginTop:12}}>
        <Card icon="📉" title="Derived Capacities & Bottlenecks" badge="min(stage)" info={{ what:'Each line is capped by its slowest stage.', flows:'Line cap → aggregate & production MILP.' }}
          dev={{ comp:'BottleneckTable', props:'lines (computed)' }}>
          <DataTable cols={['Line','Bottleneck Stage','Bottleneck Cap','Line OEE','Util @ plan']} align={['left','left','right','right','right']}
            rows={M.lines.map(l=>{
              // util DERIVED: Σ(monthly demand of finished SKUs on this line) ÷ line cap (was hardcoded 94/88/96%).
              const mDem = M.products.filter(p=>p.cat==='Finished'&&p.line===l.id).reduce((s,p)=>s+p.demand/12,0);
              const util = l.cap ? mDem/l.cap : 0;
              return {cells:[l.id, l.bottleneck, `${l.cap.toLocaleString('en-IN')} u/mo`, `${(l.oee*100).toFixed(0)}%`,
                <span style={{fontWeight:700, color: util>0.95?C.dg:C.tx}}>{(util*100).toFixed(0)}%</span>]};
            })}/>
          <Reading formula="util = Σ(monthly demand of SKUs on the line) ÷ line capacity" soWhat="A line over ~95% has no slack — its capacity dual turns positive on Plan, which is where added capacity earns its return."/>
        </Card>
      </div>
    </div>
  );
}

function ProdCycle({ p, onNav }) {
  const [capMode, setCapMode] = useState('oee');
  const flatRate = (60/p.cycle).toFixed(1);
  const effRate = (60/p.cycle*p.oee).toFixed(1);
  return (
    <Grid cols={2}>
      <Card icon="🏭" title="Cycle Time & Line Assignment" badge={p.line} info={{ what:'Per-SKU cycle time + line assignment (a line property, owned here).', flows:'Cycle/line → production MILP & MPS.' }}
        dev={{ comp:'CycleEditor', props:'prod.cycle, prod.line, capMode', state:'products[id].{cycle,line,capMode}', note:'OEE is OPTIONAL — flat rate (rate×hours) is allowed for shops that don\u2019t track OEE.' }}
        right={<div style={{display:'flex', border:`2px solid ${C.line}`, marginRight:8}}>
          {[['oee','OEE'],['flat','FLAT']].map(([v,l],i)=><button key={v} onClick={()=>setCapMode(v)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'3px 9px', border:'none', borderRight:i===0?`2px solid ${C.line}`:'none', cursor:'pointer', background:capMode===v?C.ac:C.paper, color:capMode===v?C.onAc:C.tx}}>{l}</button>)}
        </div>}>
        <Grid cols={2} gap={8}>
          <Field label="Cycle Time"><NumInput value={p.cycle} suffix="min/u"/></Field>
          <Field label="Assigned Line"><Select value={p.line} options={['LINE-01','LINE-02','LINE-03']}/></Field>
          {capMode==='oee'
            ? <Field label="OEE"><NumInput value={(p.oee*100).toFixed(0)} suffix="%"/></Field>
            : <Field label="Run hours / day"><NumInput value="20"/></Field>}
          <Field label="Effective Rate"><NumInput value={capMode==='oee'?effRate:flatRate} suffix="u/hr" disabled/></Field>
          <Field label="Batch Size" span={2}><NumInput value={p.moq}/></Field>
        </Grid>
        {capMode==='oee'
          ? <Reading formula={`theoretical ${flatRate} u/hr × OEE ${(p.oee*100).toFixed(0)}% = ${effRate} u/hr effective`}
              soWhat="OEE decomposes capacity into availability × performance × quality — use it when you measure those losses."/>
          : <Reading formula={`flat capacity = ${flatRate} u/hr × run hours (no OEE decomposition)`}
              soWhat="If you don\u2019t track OEE, a flat rate × hours is a valid capacity input — the MILP doesn\u2019t require the decomposition."/>}
      </Card>
      <Card icon="📅" title="Line Load Preview" badge="this SKU" info={{ what:'Where this SKU sits on its assigned line.', flows:'Shared with the schedule.' }}
        dev={{ comp:'LineLoadMini', props:'prod.line' }}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {M.periods.slice(0,6).map((wk,i)=>(
            <div key={i} style={{display:'flex', alignItems:'center', gap:8}}>
              <span style={{fontFamily:F.mono, fontSize:10, width:42, color:C.tx2}}>{wk.label}</span>
              <MiniBar v={[60,72,68,80,55,64][i]} max={100} color={C.ink} h={12}/>
              <span className="num" style={{fontFamily:F.mono, fontSize:10, width:36, textAlign:'right'}}>{[60,72,68,80,55,64][i]}%</span>
            </div>
          ))}
        </div>
      </Card>
    </Grid>
  );
}

function ProdMPS() {
  const [grain, setGrain] = useState('day');
  const wks = M.periods.slice(0,8);
  // synthesize a daily view of the first 2 weeks (frozen fence) — 10 working days
  const days = Array.from({length:10},(_,i)=>({ d:i, label:'D'+(i+1), wk:Math.floor(i/5) }));
  return (
    <Card icon="📅" title="Master Production Schedule (MPS)" badge={grain==='day'?'frozen · daily':'weekly'} info={{ what:'Time-phased production quantities per SKU.', flows:'MPS → MRP explosion & order promising.' }}
      dev={{ comp:'MPSVizCard', props:'state.production.mps, grain', state:'production.mps[sku][period]' }}
      right={<div style={{display:'flex', border:`2px solid ${C.line}`, marginRight:8}}>
        {['day','week'].map((g,i)=><button key={g} onClick={()=>setGrain(g)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'3px 9px', border:'none', borderRight:i===0?`2px solid ${C.line}`:'none', cursor:'pointer', background:grain===g?C.ac:C.paper, color:grain===g?C.onAc:C.tx, textTransform:'uppercase'}}>{g}</button>)}
      </div>}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>SKU</th>
            {grain==='week'
              ? wks.map(w=><th key={w.id} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{w.label}</th>)
              : days.map(d=><th key={d.d} style={{color:C.paper, textAlign:'right', padding:'6px 7px', fontSize:9, background:d.wk===0?'#000':C.ink}}>{d.label}</th>)}
          </tr></thead>
          <tbody>
            {M.mps.map((row,ri)=>(
              <tr key={ri} style={{borderTop:`1px solid ${C.line2}`, background: ri%2?C.bg3:C.paper}}>
                <td style={{padding:'5px 9px', fontWeight:700}}>{row.sku}</td>
                {grain==='week'
                  ? row.wk.map((q,i)=>(
                      <td key={i} className="num" style={{textAlign:'right', padding:'5px 9px', position:'relative'}}>
                        <span style={{position:'relative', zIndex:1}}>{q}</span>
                        <span style={{position:'absolute', right:4, bottom:3, height:3, width:`${q/110*40}px`, background:C.ac}}/>
                      </td>
                    ))
                  : days.map((d,i)=>{ const wq=row.wk[d.wk]; const dq=Math.round(wq/5 + ((i%3)-1)*2);
                      return <td key={i} className="num" style={{textAlign:'right', padding:'5px 7px', color: d.wk===0?C.tx:C.tx2}}>{dq}</td>;
                    })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Reading formula={grain==='day'?'daily qty = weekly MPS ÷ workdays (frozen fence = days)':'weekly MPS = Σ daily within bucket'}
        soWhat={grain==='day'?'Inside the 2-week frozen fence the schedule is executable by day; beyond it, switch to weekly.':'Weekly view is for the slushy/free horizon; switch to day to release work.'}/>
    </Card>
  );
}

function ProdATP() {
  const wk=M.periods.slice(0,8);
  return (
    <Card icon="📦" title="Order Promising · ATP / CTP" badge="available-to-promise" info={{ what:'Uncommitted supply available to promise; CTP adds a capacity check.', flows:'ATP → quoting & MTO acceptance.' }}
      dev={{ comp:'ATPCard', props:'state.production.mps, orders' }}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9}}>SKU</th>
            {wk.map(w=><th key={w.id} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{w.label}</th>)}
          </tr></thead>
          <tbody>
            {M.mps.map((row,ri)=>(
              <tr key={ri} style={{borderTop:`1px solid ${C.line2}`}}>
                <td style={{padding:'5px 9px', fontWeight:700}}>{row.sku}</td>
                {row.atp.map((q,i)=>(
                  <td key={i} className="num" style={{textAlign:'right', padding:'5px 9px', background: q===0?C.bg4: q<6?'color-mix(in srgb,var(--dg) 14%,transparent)':'color-mix(in srgb,var(--gn) 14%,transparent)', fontWeight:700, color: q===0?C.tx3:C.tx}}>{q}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Reading formula="ATP = on-hand + scheduled receipts − committed   ·   CTP = ATP + what you could still produce in time"
        soWhat={`Reading row TPA-4471: ${M.mps[0].atp.reduce((a,b)=>a+b,0)} units promisable across the fence; the W03 zero means fully committed — quote ${M.pLabel(4)} or later.`}/>
    </Card>
  );
}

function ProdChange() {
  const skus=['TPA-4471','TPA-3215','TPA-9904','TPA-2188'];
  // build the nested {from:{to:min}} matrix the sequence solver wants (skip '—' diagonal).
  const seq = useSolve('/api/solve/sequence', ()=>{
    const matrix={};
    skus.forEach((a,ri)=>{ matrix[a]={}; skus.forEach((b,ci)=>{ const v=M.changeover[ri][ci]; if(typeof v==='number') matrix[a][b]=v; }); });
    return { skus, changeover_matrix:matrix };
  });
  const sres = seq.result;
  // client-side fallback (brute-force the fixed order) until the solver runs.
  const order=[0,2,1,3];
  const seqCost=(s)=>{ let t=0; for(let i=0;i<s.length-1;i++){ const v=M.changeover[s[i]][s[i+1]]; if(typeof v==='number') t+=v; } return t; };
  const alpha=seqCost([0,1,2,3]);
  // solved sequence (sku names) → index order for the chips; fall back to the fixed order.
  const solvedOrder = sres && Array.isArray(sres.sequence) ? sres.sequence.map(s=>skus.indexOf(s)).filter(i=>i>=0) : null;
  const chosenIdx = solvedOrder && solvedOrder.length===skus.length ? solvedOrder : order;
  const opt = sres && sres.total_changeover_min!=null ? sres.total_changeover_min : seqCost(order);
  const saved = sres && sres.sequence_saving_min!=null ? sres.sequence_saving_min : (alpha-opt);
  return (
    <Grid cols={2}>
      <Card icon="🔀" title="Changeover Matrix" badge="setup hrs" info={{ what:'Setup time depends on from→to SKU sequence.', flows:'Matrix → sequencing MILP.' }}
        dev={{ comp:'ChangeoverMatrix', props:'state.production.changeover', state:'production.changeover[from][to]' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              <th style={{color:C.paper, padding:'5px 7px', fontSize:8.5}}>FROM ↓ TO →</th>
              {skus.map(s=><th key={s} style={{color:C.paper, padding:'5px 7px', fontSize:8.5}}>{s.slice(4)}</th>)}
            </tr></thead>
            <tbody>
              {M.changeover.map((row,ri)=>(
                <tr key={ri} style={{borderTop:`1px solid ${C.line2}`}}>
                  <td style={{padding:'5px 7px', fontWeight:700, background:C.bg3}}>{skus[ri].slice(4)}</td>
                  {row.map((v,ci)=>(
                    <td key={ci} className="num" style={{textAlign:'center', padding:'5px 7px', background: v==='—'?C.bg4: typeof v==='number'&&v>2?'color-mix(in srgb,var(--dg) 16%,transparent)':C.paper, fontWeight:700}}>{v}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Red = high penalty — the sequencer avoids these transitions.</div>
      </Card>
      <Card icon="⚡" title="Chosen Run Order" badge={`−${saved.toFixed(1)} hrs`} badgeTone="y" info={{ what:'The sequence the solver picks and the setup time it saves vs alphabetical.', flows:'Order → production schedule.' }}
        right={sres ? <Provenance kind="solved" asOf={seq.ranAt?seq.ranAt.toLocaleTimeString():undefined}/> : <Btn kind="primary" sm onClick={()=>seq.run().catch(()=>{})}>{seq.solving?'⏳ …':'⚡ Sequence'}</Btn>}
        dev={{ comp:'SequenceResult', props:'solve.sequencing' }}>
        {seq.error && <div style={{marginBottom:8, fontFamily:F.mono, fontSize:9.5, color:C.dg}}>Sequencer: {seq.error}</div>}
        <SubLabel>Alphabetical</SubLabel>
        <div style={{display:'flex', alignItems:'center', gap:4, flexWrap:'wrap', marginBottom:10}}>
          {[0,1,2,3].map((s,i)=><React.Fragment key={i}><span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line2}`, background:C.bg3}}>{skus[s].slice(4)}</span>{i<3 && <span style={{color:C.tx3}}>→</span>}</React.Fragment>)}
          <span className="num" style={{marginLeft:'auto', fontFamily:F.disp, fontWeight:800}}>{alpha.toFixed(1)} hrs</span>
        </div>
        <SubLabel>{sres?`Solver-optimized · ${sres.basis||'exact'}`:'Solver-optimized'}</SubLabel>
        <div style={{display:'flex', alignItems:'center', gap:4, flexWrap:'wrap'}}>
          {chosenIdx.map((s,i)=><React.Fragment key={i}><span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line}`, background:C.ac, color:C.onAc}}>{skus[s].slice(4)}</span>{i<chosenIdx.length-1 && <span style={{color:C.tx3}}>→</span>}</React.Fragment>)}
          <span className="num" style={{marginLeft:'auto', fontFamily:F.disp, fontWeight:800}}>{opt.toFixed(1)} hrs</span>
        </div>
        <Reading formula={sres?`shortest Hamiltonian path over the changeover matrix (${sres.basis||'exact'}) vs averaged approximation`:"min Σ changeover(seqᵢ, seqᵢ₊₁) over all permutations"}
          soWhat={`Re-ordering saves ${saved.toFixed(1)} setup hours per cycle — roughly ₹${Math.round(saved*4200).toLocaleString('en-IN')} at the setup rate.${sres?'':' Press ⚡ Sequence to solve it against the live engine.'}`}/>
      </Card>
    </Grid>
  );
}
window.StageProduction = StageProduction;
