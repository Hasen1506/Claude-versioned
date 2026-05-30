// ════════════════════════════════════════════════════════════════════════
// production.jsx — Production Architecture (ProductionArchitectureTab).
// Rich non-card UI: line→stage→machine tree, bottleneck, MPS, ATP/CTP,
// sequence-dependent changeover.  Sub-tabs: Architecture · MPS · ATP/CTP · Changeover
// ════════════════════════════════════════════════════════════════════════
function StageProduction({ onNav }) {
  const [sub, setSub] = useState('arch');
  const tabs = [
    { id:'arch',   n:'a', label:'Architecture', count:M.lines.length },
    { id:'mps',    n:'b', label:'MPS' },
    { id:'atp',    n:'c', label:'ATP / CTP' },
    { id:'change', n:'d', label:'Changeover' },
  ];
  return (
    <div>
      <StageHeader n="05" title="Production Architecture" kicker="Lines → stages → machines · OEE · bottleneck = min(stage) · MPS · order promising"
        right={<Btn kind="secondary">+ Add line</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='arch'   && <ProdArch/>}
        {sub==='mps'    && <ProdMPS/>}
        {sub==='atp'    && <ProdATP/>}
        {sub==='change' && <ProdChange/>}
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
      <div style={{marginBottom:10, display:'flex', alignItems:'center', gap:8}}>
        <span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, letterSpacing:'.08em'}}>LINE → STAGE → MACHINE TREE · bottleneck stage caps the line</span>
        <DevNote comp="ProductionArchitectureTab" props="state.production.lines" state="production.lines[].stages[].machines" note="Rich non-card editor — first-class screen."/>
      </div>
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
            rows={M.lines.map(l=>({cells:[l.id, l.bottleneck, `${l.cap.toLocaleString('en-IN')} u/mo`, `${(l.oee*100).toFixed(0)}%`, <span style={{fontWeight:700, color: l.id==='LINE-03'?C.dg:C.tx}}>{l.id==='LINE-01'?'94%':l.id==='LINE-02'?'88%':'96%'}</span>]}))}/>
        </Card>
      </div>
    </div>
  );
}

function ProdMPS() {
  const wk=['W01','W02','W03','W04','W05','W06','W07','W08'];
  return (
    <Card icon="📅" title="Master Production Schedule (MPS)" badge="8 weeks" info={{ what:'Time-phased production quantities per SKU.', flows:'MPS → MRP explosion & order promising.' }}
      dev={{ comp:'MPSVizCard', props:'state.production.mps', state:'production.mps[sku][week]' }}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9, textTransform:'uppercase'}}>SKU</th>
            {wk.map(w=><th key={w} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{w}</th>)}
          </tr></thead>
          <tbody>
            {M.mps.map((row,ri)=>(
              <tr key={ri} style={{borderTop:`1px solid ${C.line2}`, background: ri%2?C.bg3:C.paper}}>
                <td style={{padding:'5px 9px', fontWeight:700}}>{row.sku}</td>
                {row.wk.map((q,i)=>(
                  <td key={i} className="num" style={{textAlign:'right', padding:'5px 9px', position:'relative'}}>
                    <span style={{position:'relative', zIndex:1}}>{q}</span>
                    <span style={{position:'absolute', right:4, bottom:3, height:3, width:`${q/110*40}px`, background:C.ac}}/>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Bar overlay = relative weekly load. Frozen window W01–W04.</div>
    </Card>
  );
}

function ProdATP() {
  const wk=['W01','W02','W03','W04','W05','W06','W07','W08'];
  return (
    <Card icon="📦" title="Order Promising · ATP / CTP" badge="available-to-promise" info={{ what:'Uncommitted supply available to promise to new orders; CTP checks capacity.', flows:'ATP → quoting & MTO acceptance.' }}
      dev={{ comp:'ATPCard', props:'state.production.mps, orders', note:'ATP = MPS − committed; CTP adds capacity check.' }}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9}}>SKU</th>
            {wk.map(w=><th key={w} style={{color:C.paper, textAlign:'right', padding:'6px 9px', fontSize:9}}>{w}</th>)}
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
      <div style={{marginTop:10, display:'flex', gap:14, fontFamily:F.mono, fontSize:9, color:C.tx2}}>
        <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:'color-mix(in srgb,var(--gn) 14%,transparent)', border:`1px solid ${C.line2}`}}/>ample ATP</span>
        <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:'color-mix(in srgb,var(--dg) 14%,transparent)', border:`1px solid ${C.line2}`}}/>tight</span>
        <span style={{display:'flex', gap:5, alignItems:'center'}}><span style={{width:10, height:10, background:C.bg4, border:`1px solid ${C.line2}`}}/>fully committed</span>
      </div>
    </Card>
  );
}

function ProdChange() {
  const skus=['TPA-4471','TPA-3215','TPA-9904','TPA-2188'];
  return (
    <Grid cols={2}>
      <Card icon="🔀" title="Sequence-Dependent Changeover" badge="setup hrs" info={{ what:'Setup time depends on from→to SKU sequence.', flows:'Changeover matrix → production MILP sequencing.' }}
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
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Red = high changeover penalty — solver avoids these transitions.</div>
      </Card>
      <Card icon="⚡" title="Capacity Conflict Check" badge="pre-solve" info={{ what:'Flags where committed load exceeds a stage capacity.', flows:'Conflicts → reschedule or overtime.' }}
        dev={{ comp:'ConflictCheck', props:'mps, lines' }}>
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          {M.lines.map((l,i)=>{
            const util=[94,88,96][i];
            return (
              <div key={l.id} style={{border:`2px solid ${C.line}`, padding:'8px 10px', background: util>95?'color-mix(in srgb,var(--dg) 10%,transparent)':C.paper}}>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:5}}>
                  <span style={{fontFamily:F.disp, fontSize:12, fontWeight:800}}>{l.id} · {l.bottleneck}</span>
                  <Tag c={util>95?'r':util>90?'a':'g'}>{util}% util</Tag>
                </div>
                <MiniBar v={util} max={100} color={util>95?C.dg:util>90?C.a4:C.gn} h={10}/>
              </div>
            );
          })}
        </div>
        <div style={{marginTop:10, padding:'8px 10px', border:`2px dashed ${C.dg}`, fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>
          ⚠ LINE-03 Heat Treat at 96% — single point of failure. Consider OT or capital (see Console · Capital).
        </div>
      </Card>
    </Grid>
  );
}
window.StageProduction = StageProduction;
