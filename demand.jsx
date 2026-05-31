// ════════════════════════════════════════════════════════════════════════
// demand.jsx — Demand (stage 04, handoff v2 §3.04). 0 sub-tabs, guided scroll
// under the item selector: history ENTRY grid (item×period, multi-grain) →
// forecast + override side-by-side → leaderboard WITH formulas → ABC/XYZ +
// lifecycle reading → period-aware promos → consensus. Low-data path explicit.
// ════════════════════════════════════════════════════════════════════════
function StageDemand({ onNav }) {
  const { item } = useActiveItem();
  return (
    <div>
      <StageHeader n="04" title="Demand Planning" kicker="Enter history · run the model competition · read ABC/XYZ · override with audit — all for the selected item"
        right={<Btn kind="accent">🤖 Run Forecast</Btn>}/>
      <ItemSelector/>
      <div style={{padding:18}}>
        <DemHistory item={item}/>
        <DemForecast item={item}/>
        <DemModels onNav={onNav}/>
        <DemSegment/>
        <DemEvents item={item}/>
        <DemConsensus/>
      </div>
    </div>
  );
}

// ── ingestion modes (7.5) + history ENTRY grid (item × period) + low-data path ──
function DemHistory({ item }) {
  const [ran, setRan] = useState(false);
  const [mode, setMode] = useState('history');
  const { profile } = useProfile();
  const periods = M.periods.slice(0, 12);
  const vals = M.history24.slice(-12);
  const ext = profile.externalForecast;
  return (
    <StageSection step="1" title={`Data Ingestion · ${item?item.name:''}`} sub="real shops import daily multi-SKU data — the 12-cell grid is an override tool, not the main path">
      <Card icon="📥" title="How demand data gets in" badge={ext?'external forecast':'2 import targets'} badgeTone="y"
        info={{ what:'Two distinct import targets (history vs forecast) + a manual override grid.', flows:'History → model competition · Forecast → straight to Aggregate.' }}
        dev={{ comp:'IngestionPanel', props:'mode, dispatch(IMPORT)', state:'demand.source, demand.history[item][period]' }}>
        {/* mode picker */}
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:8, marginBottom:12}}>
          {M.ingestModes.map(m=>{ const on = mode===m.id;
            return (
              <button key={m.id} onClick={()=>setMode(m.id)} style={{
                textAlign:'left', border:`2px solid ${on?C.line:C.line2}`, background: on?C.ink:C.paper, color: on?C.paper:C.tx,
                cursor:'pointer', padding:'9px 11px', display:'flex', flexDirection:'column', gap:4,
              }}>
                <span style={{display:'flex', alignItems:'center', gap:6}}>
                  <span style={{width:9, height:9, background: on?C.ac:'transparent', border:`1.5px solid ${on?C.ac:C.line2}`}}/>
                  <span style={{fontFamily:F.disp, fontSize:11.5, fontWeight:800}}>{m.label}</span>
                </span>
                <span style={{fontFamily:F.mono, fontSize:8.5, color: on?C.ac:C.tx3, letterSpacing:'.02em'}}>{m.schema}</span>
              </button>
            );
          })}
        </div>
        {(()=>{ const m = M.ingestModes.find(x=>x.id===mode);
          return (
            <div style={{padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.a2}`, background:C.bg3, marginBottom:12}}>
              <div style={{fontFamily:F.mono, fontSize:10, color:C.tx2, lineHeight:1.5}}><b>{m.label}:</b> {m.note}</div>
              <div style={{fontFamily:F.mono, fontSize:9, color:C.a2, fontWeight:700, marginTop:4}}>{m.drops}</div>
            </div>
          );
        })()}

        {mode==='manual' && (
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              <th style={{color:C.paper, textAlign:'left', padding:'6px 8px', fontSize:8.5}}>PERIOD →</th>
              {periods.map(p=><th key={p.id} style={{color:C.paper, textAlign:'center', padding:'6px 6px', fontSize:8.5}}>{p.label}<br/><span style={{color:C.tx3, fontWeight:400}}>{p.date}</span></th>)}
            </tr></thead>
            <tbody>
              <tr>
                <td style={{padding:'5px 8px', fontWeight:700, background:C.bg3}}>{item?item.code:'—'}</td>
                {vals.map((v,i)=>(
                  <td key={i} style={{padding:'2px', textAlign:'center', borderLeft:`1px solid ${C.line2}`}}>
                    <input defaultValue={v} className="num" style={{width:42, border:'none', background:'transparent', textAlign:'center', fontFamily:F.disp, fontWeight:600, fontSize:12, color:C.tx, outline:'none'}}/>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        )}
        {mode!=='manual' && (
          <div style={{display:'flex', alignItems:'center', gap:12, padding:'16px', border:`2px dashed ${C.line2}`, background:C.paper}}>
            <span style={{fontSize:22}}>{mode==='history'?'📄':'📈'}</span>
            <div style={{flex:1, minWidth:0}}>
              <div style={{fontFamily:F.disp, fontSize:12, fontWeight:800}}>Drop a {mode==='history'?'history':'forecast'} file (CSV / XLSX)</div>
              <div style={{fontFamily:F.mono, fontSize:9, color:C.tx3, marginTop:2}}>columns: {M.ingestModes.find(m=>m.id===mode).schema}</div>
            </div>
            <Btn kind="primary" sm>⤓ Choose file</Btn>
          </div>
        )}

        {/* low-data path banner — only when WE forecast */}
        {!ext && mode!=='forecast' && (<>
        <div style={{marginTop:10, display:'flex', alignItems:'center', gap:10, padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.a4}`, background:C.bg3}}>
          <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.a4, letterSpacing:'.1em'}}>DATA TIER</span>
          <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, flex:1, lineHeight:1.4}}>
            <b>12 points</b> entered. Classical + intermittent (Croston/SBA/TSB) run now; <b>ML unlocks at 12</b>, <b>DL at 36</b>. Sparse SKUs stay on Croston.
          </span>
          <Btn kind="primary" sm onClick={()=>setRan(true)}>{ran?'✓ ML ran':'Run ML'}</Btn>
        </div>
        {ran && (
          <div className="animate-in" style={{marginTop:10, display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:8}}>
            {[['Classical (HW)','MAPE 6.8%','done'],['ML (LightGBM)','MAPE 7.5%','done'],['DL (N-BEATS)','locked · need 36','idle']].map(([k,v,s],i)=>(
              <div key={i} style={{border:`2px solid ${C.line}`, padding:'8px 10px', background: s==='idle'?C.bg4:C.paper}}>
                <div style={{display:'flex', alignItems:'center', gap:6}}><span style={{width:8,height:8,background:s==='done'?C.gn:C.tx3}}/><span style={{fontFamily:F.disp, fontSize:11, fontWeight:800}}>{k}</span></div>
                <div className="num" style={{fontFamily:F.mono, fontSize:10, color:C.tx2, marginTop:4}}>{v}</div>
              </div>
            ))}
          </div>
        )}
        </>)}
        {ext && (
          <div style={{marginTop:10, padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.tx3}`, background:C.bg3, fontFamily:F.body, fontSize:11.5, color:C.tx2}}>
            <b>External forecast loaded.</b> Model competition is bypassed — you drop straight at Aggregate / Profit-mix. (Set in Setup → Planning Profile.)
          </div>
        )}
        <Reading formula="grain Σ: daily → weekly → monthly (finer entry, no accuracy loss)" soWhat="Enter at the finest grain you actually have; the axis re-buckets. ML results render right here, not on another tab."/>
      </Card>
    </StageSection>
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
      <rect x={xs(hist.length-0.5,hist.length)} y="14" width={W-8-xs(hist.length-0.5,hist.length)} height={H-36} fill={C.ac} opacity=".1"/>
      <path d={`${ln(histPts)} L${fcPts[0][0]} ${fcPts[0][1]}`} fill="none" stroke={C.ink} strokeWidth="2"/>
      <path d={ln(fcPts)} fill="none" stroke={C.ac2} strokeWidth="2.4" strokeDasharray="5 3"/>
      {histPts.filter((_,i)=>i%3===0).map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r="2.4" fill={C.ink}/>)}
      {fcPts.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r="2.4" fill={C.ac2}/>)}
      <text x={pad+4} y={H-6} fontSize="9" fontFamily={F.mono} fill={C.tx3}>24-PERIOD HISTORY</text>
      <text x={W-12} y={H-6} fontSize="9" fontFamily={F.mono} fill={C.ac2} textAnchor="end" fontWeight="700">12-PERIOD FORECAST →</text>
    </svg>
  );
}

// override placed BESIDE the forecast + the schedule it edits
function DemForecast({ item }) {
  return (
    <StageSection step="2" title="Forecast & Override" sub="winning model overlaid on history — the override sits next to the forecast and the schedule it changes">
      <Grid cols={3}>
        <Card icon="📊" title="History + Forecast" badge="HW MULTIPLICATIVE" badgeTone="y" span={2}
          info={{ what:'History with the winning model\u2019s forecast overlaid.', flows:'Forecast → S&OP aggregate & profit mix.' }}
          dev={{ comp:'ForecastChart', props:'item, forecastResults' }}>
          <ForecastChart/>
          <Reading formula="HW multiplicative: level × trend × seasonal index" soWhat="Forecast rises into the festive window — the override below schedules the OEM ramp on top."/>
        </Card>
        <Card icon="✏️" title="Override + Schedule" badge="audited"
          info={{ what:'Planner override with statistical-vs-overridden side by side + audit line.', flows:'Override → committed demand → MPS preview.' }}
          dev={{ comp:'OverrideCard', props:'item, dispatch(SET_OVERRIDE)', state:'demand.override[item][period]' }}>
          <Grid cols={2} gap={8}>
            <Field label="Period"><Select value={M.pLabel(8)+' · '+M.pDate(8)} options={[M.pLabel(8),M.pLabel(9),M.pLabel(10)]}/></Field>
            <Field label="Override Qty"><NumInput value="3120" suffix="u"/></Field>
          </Grid>
          <div style={{marginTop:8, display:'flex', flexDirection:'column', gap:6}}>
            {[['Statistical','2,840 u',C.tx2],['Overridden','3,120 u',C.ac]].map(([k,v,c],i)=>(
              <div key={i} style={{display:'flex', justifyContent:'space-between', alignItems:'center', border:`2px solid ${C.line}`, padding:'5px 9px', background:i?C.ac:C.paper}}>
                <span style={{fontFamily:F.mono, fontSize:10, color: i?C.onAc:C.tx2}}>{k}</span><span className="num" style={{fontFamily:F.disp, fontWeight:800, fontSize:13}}>{v}</span>
              </div>
            ))}
          </div>
          <div style={{marginTop:8}}><Field label="Reason"><TextInput value="Festive OEM ramp confirmed"/></Field></div>
          <div style={{marginTop:8, fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>audit · planner · {M.updated}</div>
          <div style={{marginTop:8}}><Btn kind="primary" sm>Apply & preview schedule</Btn></div>
        </Card>
      </Grid>
    </StageSection>
  );
}

const MODEL_FX = {
  'HW Multiplicative':'level × trend × seasonal (multiplicative)',
  'Auto-SARIMA':'(p,d,q)(P,D,Q)ₛ — seasonal ARIMA, auto-orders',
  'LightGBM (ML)':'gradient-boosted trees on lag/calendar features',
  'Seasonal LinReg':'OLS on seasonal dummies + trend',
  'N-BEATS (DL)':'deep basis-expansion residual stacks',
  'HW Additive':'level + trend + seasonal (additive)',
  'DES (Holt)':'double exponential smoothing (no season)',
  'Auto-ARIMA':'(p,d,q) auto-orders, non-seasonal',
  'Croston / SBA':'separates demand size from interval — intermittent',
  'TSB (intermittent)':'Croston variant updating demand probability',
  'Linear Regression':'OLS on trend only',
  'SES':'single exponential smoothing',
  'WMA(3)':'weighted moving average, 3 periods',
  'Seasonal Naive':'last season\u2019s same period',
  'Naive':'last observed value',
};
function DemModels({ onNav }) {
  const { gate } = useProfile();
  const ms=M.forecastModels, maxM=Math.max(...ms.map(m=>m.mape));
  if(gate.demandModels) return (
    <StageSection step="3" title="Model Competition" sub="bypassed — you import a finished forecast">
      <GateNote onNav={onNav}>An <b>external forecast</b> is loaded, so the 15-model competition is skipped — the imported numbers flow straight to Aggregate / Profit-mix.</GateNote>
    </StageSection>
  );
  return (
    <StageSection step="3" title="Model Competition" sub="every model with its formula and a one-line read — MAPE, WMAPE, bias, tracking signal">
      <Card icon="🏆" title="Forecast Leaderboard" badge={`${ms.length} models`} badgeTone="k"
        info={{ what:'Ranked competition incl. intermittent (Croston/SBA/TSB), each with its maths.', flows:'Winner → committed forecast.' }}
        dev={{ comp:'ModelCompetition', props:'item, forecastResults' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              {['#','Model','Formula','MAPE','WMAPE','Bias','Track-Sig',''].map((h,i)=>(
                <th key={i} style={{color:C.paper, textAlign:i<3?'left':'right', padding:'6px 9px', fontSize:8.5, letterSpacing:'.04em', textTransform:'uppercase', fontWeight:700, whiteSpace:'nowrap'}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {ms.map((m,i)=>(
                <tr key={i} style={{background: m.win?C.ac: i%2?C.bg3:C.paper, borderTop:`1px solid ${C.line2}`}}>
                  <td style={{padding:'4px 9px', fontWeight:700, color:m.win?C.onAc:C.tx2}}>{i+1}</td>
                  <td style={{padding:'4px 9px', fontWeight:700, whiteSpace:'nowrap'}}>{m.win&&'★ '}{m.name} {m.intermittent && <Tag c="v">INT</Tag>}</td>
                  <td style={{padding:'4px 9px', color:m.win?C.onAc:C.tx3, fontSize:9, maxWidth:230}}>{MODEL_FX[m.name]}</td>
                  <td className="num" style={{textAlign:'right', padding:'4px 9px', fontWeight:700}}>{m.mape}%</td>
                  <td className="num" style={{textAlign:'right', padding:'4px 9px'}}>{m.wmape}%</td>
                  <td className="num" style={{textAlign:'right', padding:'4px 9px', color: Math.abs(m.bias)>2?C.dg:(m.win?C.onAc:C.tx)}}>{m.bias>0?'+':''}{m.bias}</td>
                  <td className="num" style={{textAlign:'right', padding:'4px 9px'}}>{m.ts}</td>
                  <td style={{padding:'4px 9px', textAlign:'right'}}>{m.win?<Tag c="k">WINNER</Tag>:''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Reading formula="MASE = MAE ÷ naïve-MAE (<1 beats naïve)  ·  Tracking signal = Σerror ÷ MAD (outside ±4 ⇒ biased, re-fit)"
          soWhat="HW multiplicative wins at 6.8% MAPE with bias near zero. Anything with |TS|>4 is drifting and should be re-fit."/>
      </Card>
    </StageSection>
  );
}

function DemSegment() {
  const [phase, setPhase] = useState(2);
  const cell=(n)=> n===0?C.bg3 : n===1?C.ac : C.ink;
  return (
    <StageSection step="4" title="Segmentation & Lifecycle" sub="ABC = annual ₹-value Pareto · XYZ = demand CV · each cell prescribes a policy + model">
      <Grid cols={2}>
        <Card icon="🏷️" title="ABC / XYZ → method" badge="9-box"
          info={{ what:'Value (ABC) × variability (XYZ) classification — and the planning method it routes to.', flows:'Segment → policy, forecast-model, and autopilot-vs-MILP routing.' }}
          dev={{ comp:'ABCXYZCard', props:'products, M.itemMethod' }}>
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
          <Reading formula="ABC = annual £-value Pareto · XYZ = σ/μ (demand CV)"
            soWhat="AX → tight (s,S) + HW · CZ → lean, Croston, monthly review. Class drives both policy and model."/>
          <div style={{marginTop:10}}>
            <SubLabel>Method routing per item (handoff §7.4)</SubLabel>
            <div style={{display:'flex', flexDirection:'column', gap:4}}>
              {M.products.filter(p=>p.cat==='Finished').map(p=>(
                <div key={p.sku} style={{display:'flex', alignItems:'center', gap:8, border:`1.5px solid ${C.line2}`, padding:'4px 8px', background:C.paper}}>
                  <span style={{fontFamily:F.mono, fontSize:10, fontWeight:700, width:78}}>{p.sku}</span>
                  <Tag c="w">{p.abc}{p.xyz}</Tag>
                  <span style={{marginLeft:'auto'}}><MethodTag sku={p.sku}/></span>
                </div>
              ))}
            </div>
            <div style={{marginTop:6, fontFamily:F.mono, fontSize:8.5, color:C.tx3, lineHeight:1.5}}>autopilot = (s,S)/ROP/EOQ rule, no solver · optimized = MILP (coupled capacity/MOQ/budget). Don’t drag a stable washer through the optimizer.</div>
          </div>
        </Card>
        <Card icon="🔄" title="Lifecycle Curve" badge="phase tag" badgeTone="y"
          info={{ what:'Pick the phase; the multiplier shapes the base forecast. New SKUs borrow an analogous curve.', flows:'Lifecycle → demand shaping.' }}
          dev={{ comp:'LifecycleCard', props:'item.lifecyclePhase', note:'User picks a phase; only fit a curve if data supports it — do not claim “fitted” on 24 pts.' }}>
          <div style={{display:'flex', gap:6, marginBottom:10, flexWrap:'wrap'}}>
            {M.lifecycle.map((d,i)=>(
              <button key={d.ph} onClick={()=>setPhase(i)} style={{
                fontFamily:F.mono, fontSize:9.5, fontWeight:700, padding:'4px 9px', cursor:'pointer',
                border:`2px solid ${C.line}`, background: phase===i?C.ac:C.paper, color: phase===i?C.onAc:C.tx,
              }}>{phase===i?'● ':'○ '}{d.ph}</button>
            ))}
          </div>
          <svg viewBox="0 0 360 150" style={{width:'100%', height:150, display:'block'}}>
            <polyline points={M.lifecycle.map((d,i)=>`${20+i*108},${135-d.v*110}`).join(' ')} fill="none" stroke={C.ink} strokeWidth="2.4"/>
            {M.lifecycle.map((d,i)=>(<g key={i}>
              <circle cx={20+i*108} cy={135-d.v*110} r={phase===i?6:4} fill={phase===i?C.ac:C.paper} stroke={C.ink} strokeWidth="1.5"/>
              <text x={20+i*108} y="148" fontFamily={F.mono} fontSize="9" fill={phase===i?C.tx:C.tx2} fontWeight={phase===i?700:400} textAnchor="middle">{d.ph}</text>
            </g>))}
          </svg>
          <Reading formula={`phase = ${M.lifecycle[phase].ph} → multiplier ×${M.lifecycle[phase].v}`}
            soWhat="You tag the phase (it’s a choice, not a claim of a fit). The multiplier scales the statistical base before override; new SKUs inherit an analogous SKU’s curve."/>
        </Card>
      </Grid>
    </StageSection>
  );
}

function DemEvents({ item }) {
  return (
    <StageSection step="5" title="Promotions & Consensus" sub="events bound to real dates on the period axis, then reconciled to one committed number">
      <Grid cols={2}>
        <Card icon="🎯" title="Promotions & Events" badge={`${M.promos.length} active`}
          info={{ what:'Demand lift from promotions/contracts at known periods.', flows:'Lift → forecast adjustment.' }}
          dev={{ comp:'PromoCard', props:'state.promos (period-bound)', state:'demand.promos[].pid' }}>
          <DataTable cols={['Period','Date','SKU','Type','Lift %','Units']} align={['left','left','left','left','right','right']}
            rows={M.promos.map(p=>({cells:[M.pLabel(p.pid), M.pDate(p.pid), p.sku, p.kind, <span style={{color:C.gn, fontWeight:700}}>{p.lift}</span>, p.units]}))}/>
          <div style={{marginTop:10}}>
            <SubLabel>Promo-adjusted demand · period axis</SubLabel>
            <svg viewBox="0 0 700 70" style={{width:'100%', height:70, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
              <polyline points="0,45 120,42 180,20 240,42 360,40 420,40 480,18 540,40 700,38" fill="none" stroke={C.ink} strokeWidth="2"/>
              {M.promos.map((p,i)=>{ const x=20+(p.pid/51)*660;
                return <g key={i}><circle cx={x} cy={i===1?20:i===2?18:30} r="4" fill={C.ac} stroke={C.ink} strokeWidth="1.5"/><text x={x} y="62" fontFamily={F.mono} fontSize="9" fill={C.tx2} textAnchor="middle">{M.pLabel(p.pid)}</text></g>;
              })}
            </svg>
          </div>
        </Card>
        <Card icon="🤝" title="Consensus Workflow" badge="committed" badgeTone="y"
          info={{ what:'Cross-functional reconciliation to one committed number.', flows:'Consensus → S&OP plan.' }}
          dev={{ comp:'ConsensusCard', props:'state.consensus', state:'demand.consensus' }}>
          <div style={{display:'flex', flexDirection:'column', gap:0, border:`2px solid ${C.line}`}}>
            {M.consensus.map((c,i)=>(
              <div key={i} style={{display:'flex', alignItems:'center', gap:10, padding:'8px 11px', borderTop:i?`1px solid ${C.line2}`:'none', background: c.em?C.ac:C.paper}}>
                <span style={{fontFamily:F.disp, fontSize:12.5, fontWeight:800, width:100, color:c.em?C.onAc:C.tx}}>{c.fn}</span>
                <span className="num" style={{fontFamily:F.disp, fontSize:15, fontWeight:700, flex:1}}>{c.fc}</span>
                <Tag c={c.em?'k':'w'}>{c.stance}</Tag>
              </div>
            ))}
          </div>
          <Reading soWhat="Committed = 13,400 (Ops-bounded). Sales optimism is trimmed by capacity — that's the number S&OP plans against."/>
        </Card>
      </Grid>
    </StageSection>
  );
}
function DemConsensus(){ return null; }
window.StageDemand = StageDemand;
