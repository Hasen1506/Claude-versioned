// ════════════════════════════════════════════════════════════════════════
// demand.jsx — Demand Planning (DemandTab). Sub-tabs: Forecast · Models ·
// Segmentation · Events · Consensus.
// ════════════════════════════════════════════════════════════════════════
function StageDemand({ onNav }) {
  const [sub, setSub] = useState('forecast');
  const tabs = [
    { id:'forecast',  n:'a', label:'Forecast' },
    { id:'models',    n:'b', label:'Models', count:M.forecastModels.length },
    { id:'segment',   n:'c', label:'Segmentation' },
    { id:'events',    n:'d', label:'Events' },
    { id:'consensus', n:'e', label:'Consensus' },
  ];
  return (
    <div>
      <StageHeader n="03" title="Demand Planning" kicker="History · ML/DL forecast · model competition · ABC-XYZ · lifecycle · promotions · consensus"
        right={<Btn kind="accent">🤖 Run Forecast</Btn>}/>
      <SubTabNav tabs={tabs} active={sub} onChange={setSub}/>
      <div style={{padding:14}}>
        {sub==='forecast'  && <DemForecast/>}
        {sub==='models'    && <DemModels/>}
        {sub==='segment'   && <DemSegment/>}
        {sub==='events'    && <DemEvents/>}
        {sub==='consensus' && <DemConsensus/>}
      </div>
    </div>
  );
}

function ForecastChart() {
  const hist=M.history24, fc=M.forecast12, W=780, H=240, pad=34;
  const all=[...hist,...fc], mx=Math.max(...all)*1.1;
  const xs=(i,n)=> pad + i/(n-1+12)*(W-pad-8);
  const y=(v)=> H-22-(v/mx)*(H-40);
  const histPts = hist.map((v,i)=>[xs(i,hist.length), y(v)]);
  const fcPts = fc.map((v,i)=>[xs(hist.length+i,hist.length), y(v)]);
  const ln = pts=>pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', height:H, display:'block'}}>
      {[0,1,2,3,4].map(i=>(<line key={i} x1={pad} x2={W-8} y1={18+i*((H-40)/4)} y2={18+i*((H-40)/4)} stroke={C.line2} strokeWidth=".8"/>))}
      {[0,1,2,3,4].map(i=>(<text key={i} x={pad-5} y={22+i*((H-40)/4)} fontSize="9" fontFamily={F.mono} fill={C.tx3} textAnchor="end">{Math.round(mx*(1-i/4))}</text>))}
      {/* forecast band */}
      <rect x={xs(hist.length-0.5,hist.length)} y="14" width={W-8-xs(hist.length-0.5,hist.length)} height={H-36} fill={C.ac} opacity=".1"/>
      <path d={`${ln(histPts)} L${fcPts[0][0]} ${fcPts[0][1]}`} fill="none" stroke={C.ink} strokeWidth="2"/>
      <path d={ln(fcPts)} fill="none" stroke={C.ac2} strokeWidth="2.4" strokeDasharray="5 3"/>
      {histPts.filter((_,i)=>i%3===0).map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r="2.4" fill={C.ink}/>)}
      {fcPts.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r="2.4" fill={C.ac2}/>)}
      <text x={pad+4} y={H-6} fontSize="9" fontFamily={F.mono} fill={C.tx3}>24-MO HISTORY</text>
      <text x={W-12} y={H-6} fontSize="9" fontFamily={F.mono} fill={C.ac2} textAnchor="end" fontWeight="700">12-MO FORECAST →</text>
    </svg>
  );
}

function DemForecast() {
  return (
    <Grid cols={1}>
      <Card icon="📊" title="Historical Time Series + Forecast" badge="HW MULTIPLICATIVE" badgeTone="y" info={{ what:'Demand history entry (grain-aware cascade) + winning model forecast.', flows:'Forecast → S&OP aggregate & profit mix.' }}
        dev={{ comp:'HistoryPanel', props:'prod, grain, dispatch(SET_HISTORY)', state:'demand.history[sku][]' }}>
        <ForecastChart/>
      </Card>
      <Grid cols={3}>
        <Card icon="🤖" title="Server-Side ML/DL Forecast" badge="/api/forecast" info={{ what:'classical → ML → hybrid → DL pipeline on the backend.', flows:'POST demand → ranked models.' }}
          dev={{ comp:'ServerForecastCard', props:'prod', note:'POSTs to /api/forecast — keep payload camelCase.' }}>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {[['Classical','done',C.gn],['ML (LightGBM)','done',C.gn],['Hybrid','done',C.gn],['DL (N-BEATS)','running',C.ac]].map(([k,s,c],i)=>(
              <div key={i} style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${C.line}`, padding:'6px 9px'}}>
                <span style={{width:9, height:9, background:c, borderRadius:s==='running'?'50%':0, border:`1.5px solid ${C.line}`}}/>
                <span style={{fontFamily:F.disp, fontSize:12, fontWeight:700, flex:1}}>{k}</span>
                <Tag c={s==='done'?'g':'y'}>{s}</Tag>
              </div>
            ))}
          </div>
        </Card>
        <Card icon="⚖" title="Demand-Ceiling vs MTO-Floor" badge="bounded" info={{ what:'Statistical forecast bounded below by firm MTO orders.', flows:'Bounds → profit mix demand range.' }}
          dev={{ comp:'CeilingFloorCard', props:'prod, orders' }}>
          <div style={{display:'flex', flexDirection:'column', gap:8, marginTop:4}}>
            {[['Ceiling (stat)','2,840 u',C.a2],['Consensus','2,640 u',C.ink],['MTO Floor','1,280 u',C.ac]].map(([k,v,c],i)=>(
              <div key={i}>
                <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:3}}><span style={{color:C.tx2}}>{k}</span><span className="num" style={{fontWeight:700}}>{v}</span></div>
                <MiniBar v={[2840,2640,1280][i]} max={2840} color={c} h={10}/>
              </div>
            ))}
          </div>
        </Card>
        <Card icon="✏️" title="Demand Override" badge="manual" info={{ what:'Planner override on any period with audit trail.', flows:'Override → committed demand.' }}
          dev={{ comp:'OverrideCard', props:'prod, dispatch(SET_OVERRIDE)', state:'demand.override[sku][period]' }}>
          <Grid cols={2} gap={8}>
            <Field label="Period"><Select value="Jun 2026" options={['Jun 2026','Jul 2026','Aug 2026']}/></Field>
            <Field label="Override Qty"><NumInput value="3120" suffix="u"/></Field>
          </Grid>
          <div style={{marginTop:8}}><Field label="Reason"><TextInput value="Festive OEM ramp confirmed"/></Field></div>
          <div style={{marginTop:8}}><Btn kind="primary" sm>Apply override</Btn></div>
        </Card>
      </Grid>
    </Grid>
  );
}

function DemModels() {
  const ms=M.forecastModels, maxM=Math.max(...ms.map(m=>m.mape));
  return (
    <Card icon="🏆" title="Forecast Model Competition" badge={`${ms.length} models`} badgeTone="k" info={{ what:'Leaderboard: MAPE / WMAPE / bias / tracking-signal incl. intermittent (Croston/SBA/TSB).', flows:'Winner → committed forecast.' }}
      dev={{ comp:'ModelCompetition', props:'prod, forecastResults', note:'Merges Forecast Comparison + Competition.' }}>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
          <thead><tr style={{background:C.ink}}>
            {['#','Model','MAPE','WMAPE','Bias','Track-Sig','',''].map((h,i)=>(
              <th key={i} style={{color:C.paper, textAlign:i<2?'left':'right', padding:'6px 9px', fontSize:9, letterSpacing:'.06em', textTransform:'uppercase', fontWeight:700, whiteSpace:'nowrap'}}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {ms.map((m,i)=>(
              <tr key={i} style={{background: m.win?C.ac: i%2?C.bg3:C.paper, borderTop:`1px solid ${C.line2}`}}>
                <td style={{padding:'4px 9px', fontWeight:700, color:m.win?C.onAc:C.tx2}}>{i+1}</td>
                <td style={{padding:'4px 9px', fontWeight:700}}>{m.win&&'★ '}{m.name} {m.intermittent && <Tag c="v">INT</Tag>}</td>
                <td className="num" style={{textAlign:'right', padding:'4px 9px', fontWeight:700}}>{m.mape}%</td>
                <td className="num" style={{textAlign:'right', padding:'4px 9px'}}>{m.wmape}%</td>
                <td className="num" style={{textAlign:'right', padding:'4px 9px', color: Math.abs(m.bias)>2?C.dg:C.tx}}>{m.bias>0?'+':''}{m.bias}</td>
                <td className="num" style={{textAlign:'right', padding:'4px 9px'}}>{m.ts}</td>
                <td style={{padding:'4px 9px', width:120}}><MiniBar v={maxM-m.mape+2} max={maxM} color={m.win?C.ink:C.tx3}/></td>
                <td style={{padding:'4px 9px', textAlign:'right'}}>{m.win?<Tag c="k">WINNER</Tag>:''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function DemSegment() {
  const cell=(n)=> n===0?C.bg3 : n===1?C.ac : C.ink;
  return (
    <Grid cols={2}>
      <Card icon="🏷️" title="ABC / XYZ Segmentation" badge="9-box" info={{ what:'Value (ABC) × variability (XYZ) classification.', flows:'Segment → policy & forecast model choice.' }}
        dev={{ comp:'ABCXYZCard', props:'products', state:'products[].{abc,xyz}' }}>
        <div style={{display:'grid', gridTemplateColumns:'40px 1fr 1fr 1fr', gap:4, marginTop:6}}>
          <div/>{['X · steady','Y · variable','Z · erratic'].map((h,i)=><div key={i} style={{fontFamily:F.mono, fontSize:9, color:C.tx3, textAlign:'center', textTransform:'uppercase'}}>{h}</div>)}
          {M.abcxyz.map((row,ri)=>(
            <React.Fragment key={ri}>
              <div style={{fontFamily:F.disp, fontWeight:800, fontSize:13, display:'grid', placeItems:'center'}}>{row.abc}</div>
              {[row.X,row.Y,row.Z].map((n,ci)=>(
                <div key={ci} style={{height:54, border:`2px solid ${C.line}`, background:cell(n), color: n===2?C.paper:C.tx, display:'grid', placeItems:'center', fontFamily:F.disp, fontSize:18, fontWeight:900}}>{n||''}</div>
              ))}
            </React.Fragment>
          ))}
        </div>
        <div style={{marginTop:10, fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>AX = tight (s,S) + HW model · CZ = lean, Croston, review monthly.</div>
      </Card>
      <Card icon="🔄" title="Lifecycle Curve" badge="4 phases" info={{ what:'Phase multiplier shaping the base forecast.', flows:'Lifecycle → demand shaping.' }}
        dev={{ comp:'LifecycleCard', props:'prod.lifecycle' }}>
        <svg viewBox="0 0 360 150" style={{width:'100%', height:150, display:'block'}}>
          <polyline points={M.lifecycle.map((d,i)=>`${20+i*108},${135-d.v*110}`).join(' ')} fill="none" stroke={C.ink} strokeWidth="2.4"/>
          {M.lifecycle.map((d,i)=>(<g key={i}>
            <circle cx={20+i*108} cy={135-d.v*110} r="4" fill={C.ac} stroke={C.ink} strokeWidth="1.5"/>
            <text x={20+i*108} y="148" fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{d.ph}</text>
          </g>))}
        </svg>
        <div style={{marginTop:4, display:'flex', justifyContent:'space-between'}}>
          {M.lifecycle.map((d,i)=><Blk key={i} label={d.ph} value={`${d.v}×`}/>)}
        </div>
      </Card>
    </Grid>
  );
}

function DemEvents() {
  return (
    <Card icon="🎯" title="Promotions & Events" badge={`${M.promos.length} active`} info={{ what:'Demand lift from promotions/contracts at known periods.', flows:'Lift → forecast adjustment.' }}
      dev={{ comp:'PromoCard', props:'state.promos', state:'demand.promos[]' }}>
      <DataTable cols={['Week','SKU','Type','Lift %','Units']} align={['left','left','left','right','right']}
        rows={M.promos.map(p=>({cells:[p.wk, p.sku, p.kind, <span style={{color:C.gn, fontWeight:700}}>{p.lift}</span>, p.units]}))}/>
      <div style={{marginTop:12}}>
        <SubLabel>Promo-adjusted demand · selected SKU</SubLabel>
        <svg viewBox="0 0 700 70" style={{width:'100%', height:70, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
          <polyline points="0,45 120,42 180,20 240,42 360,40 420,40 480,18 540,40 700,38" fill="none" stroke={C.ink} strokeWidth="2"/>
          {[['W12',180],['W40',480]].map(([w,x],i)=>(<g key={i}><circle cx={x} cy={i?18:20} r="4" fill={C.ac} stroke={C.ink} strokeWidth="1.5"/><text x={x} y="62" fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{w}</text></g>))}
        </svg>
      </div>
    </Card>
  );
}

function DemConsensus() {
  return (
    <Grid cols={2}>
      <Card icon="🎯" title="Consensus Workflow" badge="committed" badgeTone="y" info={{ what:'Cross-functional forecast reconciliation to one committed number.', flows:'Consensus → S&OP plan.' }}
        dev={{ comp:'ConsensusCard', props:'state.consensus', state:'demand.consensus' }}>
        <div style={{display:'flex', flexDirection:'column', gap:0, border:`2px solid ${C.line}`}}>
          {M.consensus.map((c,i)=>(
            <div key={i} style={{display:'flex', alignItems:'center', gap:10, padding:'9px 11px', borderTop:i?`1px solid ${C.line2}`:'none', background: c.em?C.ac:C.paper}}>
              <span style={{fontFamily:F.disp, fontSize:13, fontWeight:800, width:110, color:c.em?C.onAc:C.tx}}>{c.fn}</span>
              <span className="num" style={{fontFamily:F.disp, fontSize:16, fontWeight:700, flex:1}}>{c.fc}</span>
              <Tag c={c.em?'k':'w'}>{c.stance}</Tag>
            </div>
          ))}
        </div>
      </Card>
      <Card icon="📐" title="Forecast Value-Add (FVA)" badge="vs naive" info={{ what:'Does each step beat the naive forecast?', flows:'Process discipline metric.' }}
        dev={{ comp:'FVACard', props:'forecastResults' }}>
        <div style={{display:'flex', flexDirection:'column', gap:8, marginTop:4}}>
          {[['Naive',24.1,C.tx3],['Statistical',6.8,C.ink],['+ Analyst',7.4,C.dg],['+ Consensus',6.2,C.gn]].map(([k,v,c],i)=>(
            <div key={i}>
              <div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10, marginBottom:3}}><span style={{color:C.tx2}}>{k}</span><span className="num" style={{fontWeight:700}}>MAPE {v}%</span></div>
              <MiniBar v={28-v} max={28} color={c} h={12}/>
            </div>
          ))}
        </div>
        <div style={{marginTop:10, padding:'8px 10px', border:`2px dashed ${C.dg}`, fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>
          ⚠ Analyst step ADDS error (+0.6 MAPE) — consensus recovers it. Flag for review.
        </div>
      </Card>
    </Grid>
  );
}
window.StageDemand = StageDemand;
