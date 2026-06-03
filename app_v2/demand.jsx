// ════════════════════════════════════════════════════════════════════════
// demand.jsx — Demand (stage 04, handoff v2 §3.04). 0 sub-tabs, guided scroll
// under the item selector: history ENTRY grid (item×period, multi-grain) →
// forecast + override side-by-side → leaderboard WITH formulas → ABC/XYZ +
// lifecycle reading → period-aware promos → consensus. Low-data path explicit.
// ════════════════════════════════════════════════════════════════════════
// real-engine model keys → display label + intermittent flag (the mock used
// marketing names; forecast.py returns these snake_case keys).
const FCAST_MODEL_LABEL = {
  naive:'Naive', holt_winters:'Holt-Winters', arima:'ARIMA',
  random_forest:'Random Forest (ML)', gradient_boost:'Gradient Boost (ML)',
  xgboost:'XGBoost (ML)', mlp:'MLP (DL)', hybrid:'Hybrid (HW+ML)',
  croston:'Croston', sba:'SBA', tsb:'TSB',
  ensemble:'Ensemble (top-N blend)',   // W9·D-5
};
const FCAST_INT = new Set(['croston','sba','tsb']);
// Batch 4 (🟥) — distinguish a cold-start "warming up" (too little data yet) from a
// genuine engine failure. A thin-history error is EXPECTED on a new SKU, so we show
// it as amber guidance ("add more history, re-run"), not a red FAILED banner. Only a
// real backend fault (timeout, traceback, missing engine) reads as an error.
function fcStatus(fc){
  if(!fc) return { kind:'idle' };
  if(fc.solving) return { kind:'running' };
  const e = fc.error;
  if(e){
    const cold = /histor|data|insufficient|too few|short|empty|length|at least|series|warm|min(imum)?\s*\d/i.test(String(e));
    return { kind: cold?'warming':'error', msg:String(e) };
  }
  if(fc.result) return { kind:'ok' };
  return { kind:'idle' };
}
// pull the winning model's forward forecast array out of a /api/forecast result.
function winnerForecast(res){
  const p = res && res.products && res.products[0];
  if(!p || !p.leaderboard || !p.leaderboard.length) return null;
  const w = p.leaderboard.find(l=>l.model===(p.winner||p.recommendation)) || p.leaderboard[0];
  return (w && w.forecast) || null;
}

// Build the /api/forecast payload for an item at a chosen grain. The history is
// the item's real series AT that grain (day = finest, week/month = roll-ups);
// season + horizon follow the grain. Day grain (season 7) surfaces the demand
// spikes that production is planned around — the reason most shops plan by day.
// Promotions live as horizon-relative offsets (fidx = 0-based forecast period);
// the engine wants COMBINED-axis indices (history + future), so we add n_hist.
// holidays are global ISO dates; horizon_start_date anchors the calendar features.
function fcPayload(item, grain, di, holidays){
  const sku = (item && item.code) || '';
  const hist = historyFor(sku, grain);   // W9 D-7 — imported / like-modeled history wins over the seed
  const promos = (di && di.promos) || [];
  const promo_periods = promos.map(p=> hist.length + (p.fidx|0)).filter(x=>x>=0);
  return {
    products:[{ name: sku || 'ITEM', history: hist, promo_periods }],
    params:{ h_periods: M.horizonFor(grain), time_grain: grain, season_length: M.seasonFor(grain),
      horizon_start_date: (window.M && M.calendar && M.calendar.start) || undefined,
      holidays: (holidays && holidays.length) ? holidays : undefined },
  };
}
function StageDemand({ onNav }) {
  const { item } = useActiveItem();
  // Grain is the USER's choice — default WEEK (Batch 4 🧭): the weekly roll-up shows
  // a smooth, readable demand curve instead of the jagged day-grain "heart-monitor"
  // spikes that confuse a first read. Day is one click away for spike-level planning;
  // Month is the coarsest. The engine runs at the chosen grain with a matching season.
  const [grain, setGrain] = useState('weekly');
  const sku = (item && item.code) || '';
  // Governed forecast INPUTS (W1 · D-1): planned promos + global holidays feed the
  // engine; re-running re-applies them. These are inputs, not the committed output.
  const { di } = useDemandInputs(sku);
  const { holidays } = useHolidays();
  const fc = useSolve('/api/forecast', ()=>fcPayload(item, grain, di, holidays));
  // KEYSTONE write: persist the winning series into the shared demand slice so
  // Sourcing/Production/Console MILPs plan to this exact curve.
  const runForecast = (g)=>{ const gg = g || grain;
    return fc.run(fcPayload(item, gg, di, holidays)).then(res=>{
      const f = winnerForecast(res);
      if(f && f.length && item && item.code) setItemDemand(item.code, f);
    }).catch(()=>{});
  };
  // Run the REAL engine on mount and whenever the item, grain, OR the governed
  // forecast inputs (promos/holidays) change — so flagging a promo re-applies live.
  const inputSig = JSON.stringify(di.promos) + '|' + (holidays||[]).join(',');
  React.useEffect(()=>{ runForecast(grain); }, [sku, grain, inputSig]); // eslint-disable-line
  const grainToggle = (
    <div style={{display:'flex', border:`2px solid ${C.line}`}}>
      {[['daily','Day'],['weekly','Week'],['monthly','Month']].map(([g,l],i)=>(
        <button key={g} onClick={()=>setGrain(g)} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'4px 10px', border:'none', borderRight:i<2?`2px solid ${C.line}`:'none', cursor:'pointer', background:grain===g?C.ac:C.paper, color:grain===g?C.onAc:C.tx}}>{l}</button>
      ))}
    </div>
  );
  return (
    <div>
      <StageHeader n="04" title="Demand Planning" kicker="Pick the grain (week is the smooth default; day exposes the spikes) · run the model competition · read ABC/XYZ · override — all for the selected item"
        right={<div style={{display:'flex', alignItems:'center', gap:8}}>{grainToggle}<Btn kind="accent" onClick={()=>runForecast()}>{fc.solving?'⏳ Running…':'🤖 Run Forecast'}</Btn></div>}/>
      <ItemSelector/>
      <StageContext item={item} asOf={fc.ranAt ? fc.ranAt.toLocaleString('en-IN') : null}/>
      <div style={{padding:18}}>
        <SolverExplain id="forecast"/>
        {(()=>{ const s=fcStatus(fc);
          if(s.kind==='warming') return (
            <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.a4}`, borderLeft:`5px solid ${C.a4}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.a4}}>
              🌱 <b>Warming up</b> — not enough history yet to fit the full model competition ({s.msg}). Add more history in step 1 / import a series in step 1b, then re-run. This is a cold start, <b>not</b> a failure.
            </div>);
          if(s.kind==='error') return (
            <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Forecast engine: {s.msg}</div>);
          return null;
        })()}
        <DemHistory item={item} grain={grain}/>
        <DemImport item={item} grain={grain} onApplied={()=>runForecast()}/>
        <DemForecast item={item} fc={fc} grain={grain}/>
        <DemActuals item={item} fc={fc} grain={grain}/>
        <DemModels onNav={onNav} fc={fc} item={item}/>
        <DemSegment item={item} fc={fc}/>
        <DemEvents item={item} grain={grain}/>
        <DemCommit item={item} fc={fc}/>
      </div>
    </div>
  );
}

// ── ingestion modes (7.5) + history ENTRY grid (item × period) + low-data path ──
function DemHistory({ item, grain }) {
  const [mode, setMode] = useState('history');
  const { profile } = useProfile();
  const g = grain || 'daily';
  const series = historyFor((item&&item.code)||'', g);  // W9 — reflects an imported series
  const vals = series.slice(-12);                       // last 12 buckets of the real series
  const gl = M.grainLabel(g);
  const ext = profile.externalForecast;
  return (
    <StageSection step="1" title={`Data Ingestion · ${item?item.name:''} · by ${gl}`} sub="real shops import daily multi-SKU data — the grid below is an override tool, not the main path">
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
              <th style={{color:C.paper, textAlign:'left', padding:'6px 8px', fontSize:8.5}}>last 12 · {gl} →</th>
              {vals.map((_,i)=><th key={i} style={{color:C.paper, textAlign:'center', padding:'6px 6px', fontSize:8.5}}>{gl.charAt(0).toUpperCase()}-{vals.length-1-i}</th>)}
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

        {/* data-tier note — informational only; the model competition runs from the
            🤖 Run Forecast button (top right), NOT here. No fabricated results. */}
        {!ext && mode!=='forecast' && (
        <div style={{marginTop:10, display:'flex', alignItems:'center', gap:10, padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.a4}`, background:C.bg3}}>
          <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.a4, letterSpacing:'.1em'}}>DATA TIER</span>
          <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, flex:1, lineHeight:1.4}}>
            <b>{series.length} {gl}s</b> of history at the chosen grain (day is the finest — it exposes the spikes production plans around). The live competition fits classical, ARIMA, intermittent (Croston/SBA/TSB) and — at this depth — ML/DL models, then reports the real winner in step 3.
          </span>
        </div>
        )}
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

function ForecastChart({ forecast, history, pi }) {
  // history + forecast must be at the SAME grain. The forecast overlay draws ONLY
  // when the live engine returned one — no mock curve stands in for it.
  const hist=(history&&history.length)?history:M.history24, fc=(forecast&&forecast.length)?forecast:[], W=780, H=240, pad=34;
  const hasF=fc.length>0, total=hist.length+fc.length;
  // DM-A — include the P90 ceiling in the y-scale so the uncertainty cone fits.
  const band = (pi && pi.length) ? pi : null;
  const all=hasF?[...hist,...fc,...(band?band.map(b=>b.p90):[])]:hist, mx=Math.max(...all,1)*1.1;
  const xs=(i)=> pad + i/Math.max(1,total-1)*(W-pad-8);
  const y=(v)=> H-22-(v/mx)*(H-40);
  const histPts = hist.map((v,i)=>[xs(i), y(v)]);
  const fcPts = fc.map((v,i)=>[xs(hist.length+i), y(v)]);
  const ln = pts=>pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
  // DM-A — shaded P10–P90 cone behind the forecast line (closed polygon p90→ then p10 back).
  let bandPath = null;
  if(band && fc.length){
    const up = band.map((b,i)=>[xs(hist.length+i), y(b.p90)]);
    const lo = band.map((b,i)=>[xs(hist.length+i), y(b.p10)]).reverse();
    bandPath = ln(up) + ' ' + lo.map(p=>'L'+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ') + ' Z';
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', height:H, display:'block'}}>
      {[0,1,2,3,4].map(i=>(<line key={i} x1={pad} x2={W-8} y1={18+i*((H-40)/4)} y2={18+i*((H-40)/4)} stroke={C.line2} strokeWidth=".8"/>))}
      {[0,1,2,3,4].map(i=>(<text key={i} x={pad-5} y={22+i*((H-40)/4)} fontSize="9" fontFamily={F.mono} fill={C.tx3} textAnchor="end">{Math.round(mx*(1-i/4))}</text>))}
      {hasF && <rect x={xs(hist.length-0.5)} y="14" width={W-8-xs(hist.length-0.5)} height={H-36} fill={C.ac} opacity=".1"/>}
      {bandPath && <path d={bandPath} fill={C.ac2} opacity=".15" stroke="none"/>}
      <path d={hasF?`${ln(histPts)} L${fcPts[0][0]} ${fcPts[0][1]}`:ln(histPts)} fill="none" stroke={C.ink} strokeWidth="2"/>
      {hasF && <path d={ln(fcPts)} fill="none" stroke={C.ac2} strokeWidth="2.4" strokeDasharray="5 3"/>}
      {histPts.filter((_,i)=>i%3===0).map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r="2.4" fill={C.ink}/>)}
      {fcPts.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r="2.4" fill={C.ac2}/>)}
      <text x={pad+4} y={H-6} fontSize="9" fontFamily={F.mono} fill={C.tx3}>{hist.length}-PERIOD HISTORY</text>
      {hasF
        ? <text x={W-12} y={H-6} fontSize="9" fontFamily={F.mono} fill={C.ac2} textAnchor="end" fontWeight="700">{fc.length}-PERIOD FORECAST →</text>
        : <text x={W-12} y={H-6} fontSize="9" fontFamily={F.mono} fill={C.tx3} textAnchor="end">run forecast to overlay →</text>}
    </svg>
  );
}

// ── Per-period forecast numbers (W1 · D-2) ────────────────────────────────
// The chart shows the SHAPE; planners commit to NUMBERS. This renders every
// forecast period as date + units, straight from the winner's forecast array —
// promo-flagged periods (D-1) are marked so the two inputs stay visibly linked.
function PerPeriodTable({ item, fcastArr, grain, prod }) {
  const sku = (item && item.code) || '';
  const { di } = useDemandInputs(sku);
  const g = grain || 'daily';
  const promoSet = new Set((di.promos||[]).map(p=>p.fidx));
  if(!fcastArr || !fcastArr.length) return null;
  const total = fcastArr.reduce((a,b)=>a+(b||0),0);
  const avg = total / fcastArr.length;
  // DM-A — per-period prediction interval (P10/P90), keyed by step. DM-B — promo
  // uplift attribution (baseline vs the share the promo flag is driving).
  const pi = (prod && prod.forecast_pi) || null;
  const attr = (prod && prod.promo_attribution) || null;
  const attrByStep = {}; if(attr && attr.periods) attr.periods.forEach(r=>{ attrByStep[r.step] = r; });
  return (
    <div style={{marginTop:12}}>
      <SubLabel>Forecast by {M.grainLabel(g)} · {fcastArr.length} periods · Σ {Math.round(total).toLocaleString('en-IN')} u{pi?' · P10–P90 band':''}</SubLabel>
      <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
          <thead><tr style={{background:C.ink}}>
            <th style={{color:C.paper, textAlign:'left', padding:'5px 8px', fontSize:8.5}}>#</th>
            <th style={{color:C.paper, textAlign:'left', padding:'5px 8px', fontSize:8.5}}>Date</th>
            <th style={{color:C.paper, textAlign:'right', padding:'5px 8px', fontSize:8.5}}>Units</th>
            {pi && <th style={{color:C.paper, textAlign:'right', padding:'5px 8px', fontSize:8.5}}>P10–P90</th>}
            {attr && <th style={{color:C.paper, textAlign:'right', padding:'5px 8px', fontSize:8.5}}>promo Δ</th>}
            <th style={{color:C.paper, textAlign:'left', padding:'5px 8px', fontSize:8.5}}>vs avg</th>
          </tr></thead>
          <tbody>
            {fcastArr.map((v,i)=>{ const promo = promoSet.has(i); const hi = v>avg*1.15;
              const band = pi && pi[i]; const ar = attrByStep[i+1];
              return (
              <tr key={i} style={{background: promo?C.ac: i%2?C.bg3:C.paper, borderTop:`1px solid ${C.line2}`}}>
                <td style={{padding:'3px 8px', fontWeight:700, color: promo?C.onAc:C.tx2}}>P{i+1}</td>
                <td style={{padding:'3px 8px', color: promo?C.onAc:C.tx2}}>{futureLabel(g,i)}{promo && <Tag c="k">PROMO</Tag>}</td>
                <td className="num" style={{padding:'3px 8px', textAlign:'right', fontWeight:700, color: promo?C.onAc:C.tx, fontFamily:F.disp, fontSize:12}}>{Math.round(v||0).toLocaleString('en-IN')}</td>
                {pi && <td className="num" style={{padding:'3px 8px', textAlign:'right', fontSize:9, color: promo?C.onAc:C.tx3}}>{band?`${Math.round(band.p10).toLocaleString('en-IN')}–${Math.round(band.p90).toLocaleString('en-IN')}`:'—'}</td>}
                {attr && <td className="num" style={{padding:'3px 8px', textAlign:'right', fontSize:9, fontWeight:700, color: (ar&&ar.uplift>0)?(promo?C.onAc:C.gn):(promo?C.onAc:C.tx3)}}>{ar&&Math.abs(ar.uplift)>=0.5?`+${Math.round(ar.uplift).toLocaleString('en-IN')}`:'·'}</td>}
                <td style={{padding:'3px 8px', fontSize:9, color: promo?C.onAc:(hi?C.gn:C.tx3)}}>{v>=avg?'▲':'▽'} {Math.round(((v-avg)/Math.max(1,avg))*100)}%</td>
              </tr>
            );})}
          </tbody>
        </table>
      </div>
      {attr && attr.promo_uplift_total>0 && (
        <div style={{marginTop:6, fontFamily:F.mono, fontSize:9.5, color:C.tx2}}>
          <b>DM-B promo attribution</b> ({attr.model}): of the forecast total, <b style={{color:C.gn}}>+{Math.round(attr.promo_uplift_total).toLocaleString('en-IN')} u</b> is the promo flag's causal uplift over the no-promo baseline (winner counterfactual).
        </div>
      )}
      {pi && <div style={{marginTop:4, fontFamily:F.mono, fontSize:9, color:C.tx3}}>DM-A band = ±1.28·σ_resid·√step (P10/P90) — the cone of forecast uncertainty the safety-stock/CVaR cards consume.</div>}
    </div>
  );
}

// override placed BESIDE the forecast + the schedule it edits
function DemForecast({ item, fc, grain }) {
  const gl = M.grainLabel(grain||'daily');
  const res = fc && fc.result;
  const prod = res && res.products && res.products[0];
  const winnerKey = prod && (prod.winner || prod.recommendation);
  const winLabel = winnerKey ? (FCAST_MODEL_LABEL[winnerKey] || winnerKey).toUpperCase() : (fc&&fc.solving?'RUNNING…':'NOT RUN');
  const fcastArr = winnerForecast(res);
  return (
    <StageSection step="2" title={`Forecast & Override · by ${gl}`} sub={`${fcastArr?fcastArr.length+' '+gl+'s ahead — ':''}winning model overlaid on history; the override writes back to committed demand`}>
      <Grid cols={3}>
        <Card icon="📊" title="History + Forecast" badge={winLabel} badgeTone="y" span={2}
          right={res ? <Provenance kind="solved" asOf={fc.ranAt?fc.ranAt.toLocaleTimeString():undefined}/> : undefined}
          info={{ what:'History with the winning model\u2019s forecast overlaid.', flows:'Forecast → S&OP aggregate & profit mix.' }}
          dev={{ comp:'ForecastChart', props:'item, forecastResults' }}>
          <ForecastChart forecast={fcastArr} history={M.historyAt((item&&item.code)||'', grain||'daily')} pi={prod && prod.forecast_pi}/>
          <PerPeriodTable item={item} fcastArr={fcastArr} grain={grain||'daily'} prod={prod}/>
          <Reading formula={fcastArr?`winner = ${winLabel} (lowest holdout MAPE)`:"the curve overlays only once the live engine returns a winner"} soWhat={fcastArr?"Forecast curve is the live engine winner over this item's history — the override beside it edits a period and writes back to committed demand.":"No forecast yet — the chart shows history only; nothing is drawn for the forecast line until the engine runs."}/>
        </Card>
        <OverrideCard item={item} fcastArr={fcastArr}/>
      </Grid>
    </StageSection>
  );
}

// Real override: edits one forecast period and writes the series back to the
// shared demand slice (the same slice the Sourcing/Production MILPs read).
function OverrideCard({ item, fcastArr }) {
  const base = fcastArr && fcastArr.length ? fcastArr : null;
  const [pidx, setPidx] = useState(0);
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const [savedAt, setSavedAt] = useState(null);
  const i = base ? Math.min(pidx, base.length-1) : 0;
  const stat = base ? Math.round(base[i]||0) : null;
  const ov = qty==='' ? null : Math.max(0, Math.round(+qty||0));
  const apply = ()=>{
    if(!base || ov==null || !item || !item.code) return;
    const next = base.slice(); next[i] = ov;
    setItemDemand(item.code, next);
    logEvent('override', item.code, { period:i+1, from:Math.round(base[i]||0), to:ov, reason: reason||null });
    setSavedAt(new Date());
  };
  return (
    <Card icon="✏️" title="Override + Schedule" badge={base?'writes to demand':'run forecast first'}
      info={{ what:'Planner override on a forecast period; Apply writes back to the committed demand series the downstream solvers read.', flows:'Override -> committed demand -> Sourcing / Production.' }}
      dev={{ comp:'OverrideCard', props:'item, fcastArr', state:'demand[sku][period] via setItemDemand' }}>
      {!base ? (
        <div style={{padding:'16px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3}}>
          Run the forecast — the statistical baseline you override comes from the live winner.
        </div>
      ) : (<>
        <Grid cols={2} gap={8}>
          <Field label="Forecast period"><Select value={String(i)} onChange={v=>setPidx(Number(v))} options={base.map((_,k)=>({value:String(k), label:'Period '+(k+1)}))}/></Field>
          <Field label="Override Qty"><NumInput value={qty} onChange={setQty} suffix="u"/></Field>
        </Grid>
        <div style={{marginTop:8, display:'flex', flexDirection:'column', gap:6}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', border:`2px solid ${C.line}`, padding:'5px 9px', background:C.paper}}>
            <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>Statistical (winner)</span><span className="num" style={{fontFamily:F.disp, fontWeight:800, fontSize:13}}>{stat.toLocaleString('en-IN')} u</span>
          </div>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', border:`2px solid ${C.line}`, padding:'5px 9px', background: ov!=null?C.ac:C.bg3}}>
            <span style={{fontFamily:F.mono, fontSize:10, color: ov!=null?C.onAc:C.tx3}}>Overridden</span><span className="num" style={{fontFamily:F.disp, fontWeight:800, fontSize:13, color: ov!=null?C.onAc:C.tx3}}>{ov!=null?ov.toLocaleString('en-IN')+' u':'— enter qty'}</span>
          </div>
        </div>
        <div style={{marginTop:8}}><Field label="Reason"><TextInput value={reason} onChange={setReason}/></Field></div>
        <div style={{marginTop:8, fontFamily:F.mono, fontSize:8.5, color: savedAt?C.gn:C.tx3}}>{savedAt?`✓ written to committed demand · ${savedAt.toLocaleTimeString()}`:'not yet applied'}</div>
        <div style={{marginTop:8}}><Btn kind="primary" sm onClick={apply}>Apply override → demand</Btn></div>
      </>)}
    </Card>
  );
}

// ── Actuals entry + demand sensing (W0 · P2.b + finding D-6) ──────────────
// The closed-loop entry CRITIQUE_R2 Part H flagged as missing: the planner
// records what ACTUALLY happened, the backend pattern-senses it against the
// statistical baseline (/api/demand/sense → pattern_sensing.py: promo/holiday/
// outage/trend-break match), and the sensed/blended curve can SUPERSEDE the
// committed forecast. Every actuals entry writes to the immutable event log;
// committing the sensed curve logs a replan and (via setItemDemand) re-flags
// every downstream solver stale through the recompute DAG.
function DemActuals({ item, fc, grain }) {
  const gl = M.grainLabel(grain||'daily');
  const base = winnerForecast(fc && fc.result);          // the statistical baseline
  const sku = (item && item.code) || '';
  const [acts, setActs] = useState(()=> M.historyAt(sku, grain||'daily').slice(-6));
  useEffect(()=>{ setActs(M.historyAt(sku, grain||'daily').slice(-6)); }, [sku, grain]);
  const sense = useSolve('/api/demand/sense', ()=>({
    actuals: acts.map(v=>Number(v)||0), baseline_forecast: base || [],
    horizon: (base && base.length) || 12,
  }));
  const r = sense.result;
  const blended = r && r.blended_forecast;
  const runSense = (manual)=>{ if(!base || !base.length) return Promise.resolve();
    return sense.run().then(res=>{ if(manual) logEvent('actuals', sku, { n:acts.length, pattern: res && res.primary_pattern }); }).catch(()=>{}); };
  // DM-C — sensing CADENCE: once a baseline exists, auto-re-sense (debounced) when
  // the actuals change, so the loop closes without a manual click — new actuals
  // immediately re-pattern-match against the baseline. The manual button still logs
  // the 'actuals' event; the auto path is silent (no event-log spam). The planner
  // still COMMITS explicitly — sensing never overwrites the forecast on its own.
  const actSig = acts.join(',');
  const autoRef = React.useRef('');
  useEffect(()=>{ if(!base || !base.length) return;
    if(autoRef.current === actSig) return;
    const h = setTimeout(()=>{ autoRef.current = actSig; runSense(false); }, 700);
    return ()=>clearTimeout(h);
  }, [actSig, !!(base && base.length)]); // eslint-disable-line
  const commit = ()=>{ if(!blended || !blended.length || !sku) return;
    setItemDemand(sku, blended);                          // → markStale('demand') cascades downstream
    logEvent('replan', sku, { source:'demand-sensing', pattern: r.primary_pattern }); };
  const setAct = (i,v)=> setActs(a=>{ const n=a.slice(); n[i] = v===''?'':Number(v); return n; });
  const ssm = r && r.posterior && r.posterior.safety_stock_multiplier;
  return (
    <StageSection step="3" title="Actuals & Demand Sensing" sub="record what actually happened — the engine pattern-matches it against the baseline and can supersede the committed forecast">
      <Card icon="📡" title="Recent actuals → sensing" badge={base?`${gl} actuals`:'run forecast first'} badgeTone={base?'y':undefined}
        right={r ? <Provenance kind="solved" asOf={sense.ranAt?sense.ranAt.toLocaleTimeString():undefined}/> : undefined}
        info={{ what:'Latest actuals pattern-matched (promo/holiday/outage/trend-break) against the baseline to sense near-term demand.', flows:'Sensed → committed demand → Sourcing/Production (closed loop).' }}
        dev={{ comp:'DemActuals', props:'item, baseline', state:'events[] (actuals/replan) · demand[sku]' }}>
        {!base ? (
          <div style={{padding:'16px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3}}>
            Run the forecast first — sensing blends your actuals against the statistical baseline.
          </div>
        ) : (<>
          {sense.error && <div style={{margin:'0 0 10px', padding:'7px 11px', border:`2px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>sensing error: {sense.error}</div>}
          <SubLabel>Enter the last {acts.length} {gl}s of actuals</SubLabel>
          <div style={{overflowX:'auto', border:`2px solid ${C.line}`, marginBottom:10}}>
            <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
              <thead><tr style={{background:C.ink}}>
                {acts.map((_,i)=><th key={i} style={{color:C.paper, textAlign:'center', padding:'6px 6px', fontSize:8.5}}>{gl.charAt(0).toUpperCase()}-{acts.length-i}</th>)}
              </tr></thead>
              <tbody><tr>
                {acts.map((v,i)=>(
                  <td key={i} style={{padding:'2px', textAlign:'center', borderLeft:i?`1px solid ${C.line2}`:'none'}}>
                    <input value={v} onChange={e=>setAct(i,e.target.value)} className="num" style={{width:48, border:'none', background:'transparent', textAlign:'center', fontFamily:F.disp, fontWeight:600, fontSize:12, color:C.tx, outline:'none'}}/>
                  </td>
                ))}
              </tr></tbody>
            </table>
          </div>
          <Btn kind="accent" sm onClick={()=>runSense(true)}>{sense.solving?'⏳ Sensing…':'📡 Run demand sensing'}</Btn>
          {r && (
            <div style={{marginTop:12}}>
              <div style={{display:'flex', gap:8, flexWrap:'wrap', marginBottom:8}}>
                <Blk label="Pattern" value={String(r.primary_pattern||'none').toUpperCase()} sub={`conf ${Math.round((r.pattern_confidence||0)*100)}%`} tone="c"/>
                <Blk label="SS multiplier" value={`×${(ssm||0).toFixed(2)}`} sub="posterior σ" accent={C.a4}/>
                <Blk label="Sensed horizon" value={`${(blended||[]).length} ${gl}s`} sub="blended" accent={C.gn}/>
              </div>
              <Reading formula="blended = sensed (pattern-matched actuals) ⊕ statistical baseline, decaying across the blend window"
                soWhat={`Recent actuals match a ${r.primary_pattern||'none'} pattern — committing rewrites the near-term demand the downstream solvers plan to and re-flags every one to re-run.`}/>
              <div style={{marginTop:8}}><Btn kind="primary" sm onClick={commit}>Commit sensed → committed demand</Btn></div>
            </div>
          )}
        </>)}
      </Card>
    </StageSection>
  );
}

// ── Consolidated commit panel (W1 · D-4, decision D-DEC-2 = combined) ──────
// Replaces the illustrative "consensus" seed. The committed number is not a
// fabricated cross-functional table — it IS the demand series steps 2-3/5 wrote
// (forecast → override → sensing → lifecycle), shown two linked ways: the
// selected item's dossier + the company rollup across every finished SKU. The
// event log supplies provenance (what last touched each series, and when).
const COMMIT_SRC = { forecast:'Forecast', override:'Override', replan:'Demand sensing', lifecycle:'Lifecycle', actuals:'Actuals' };
function DemCommit({ item, fc }) {
  const { state: demand } = useStore(s=>s.demand||{});
  const { events } = useEvents();
  const sku = (item && item.code) || '';
  const finished = (M.products||[]).filter(p=>p.cat==='Finished');
  const lastFor = (code)=>{ for(let i=events.length-1;i>=0;i--){ const e=events[i];
    if(e.target===code && COMMIT_SRC[e.type]) return e; } return null; };
  const sumOf = (code)=>{ const s=demand[code]; return (s&&s.length)?s.reduce((a,b)=>a+(b||0),0):null; };
  // Batch 4 (🟨, Theme 4) — the firm MTO order book, summed per SKU, so the unified
  // consensus table shows the forecast-driven (MTS) number and the contracted (MTO)
  // backlog side by side. `null` ⇒ this SKU has no firm orders (honest dash).
  const firmFor = (code)=>{ const o=(M.orders||[]).filter(x=>x.sku===code && x.status==='firm');
    return o.length ? o.reduce((a,b)=>a+(b.qty||0),0) : null; };
  const myS = demand[sku]; const myTot = sumOf(sku); const myEv = lastFor(sku);
  const grand = finished.reduce((a,p)=>a+(sumOf(p.sku)||0),0);
  const grandFirm = finished.reduce((a,p)=>a+(firmFor(p.sku)||0),0);
  const committedCount = finished.filter(p=>sumOf(p.sku)!=null).length;
  return (
    <StageSection step="7" title="Committed Demand & Consensus" sub="the one number the plant plans to — the live series you built above, per item and rolled up across every SKU with forecast-driven (MTS) and firm-order (MTO) demand side by side">
      <Grid cols={2}>
        <Card icon="✅" title={`Committed · ${item?item.name:'—'}`} badge={myTot!=null?'committed':'not committed'} badgeTone={myTot!=null?'y':'k'}
          right={myTot!=null ? <Provenance kind="solved" asOf={myEv?new Date(myEv.ts).toLocaleString('en-IN'):undefined}/> : <Provenance kind="derived"/>}
          info={{ what:'The committed demand series the downstream solvers read for this item, with the action that last set it.', flows:'Committed → Sourcing / Production / Console.' }}
          dev={{ comp:'DemCommit', props:'demand[sku], events', state:'appStore.demand[sku]' }}>
          {myTot==null ? (
            <div style={{padding:'16px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3}}>
              No committed series yet — run the forecast (step 2). Until then the solvers fall back to the seed annual demand spread evenly.
            </div>
          ) : (<>
            <div style={{display:'flex', gap:8, marginBottom:8}}>
              <Blk label="Committed Σ" value={`${Math.round(myTot).toLocaleString('en-IN')} u`} sub={`${myS.length} periods`} accent={C.gn}/>
              <Blk label="Set by" value={myEv?COMMIT_SRC[myEv.type]:'Forecast'} sub={myEv?new Date(myEv.ts).toLocaleDateString('en-IN'):'—'} tone="c"/>
              <Blk label="Per-period avg" value={Math.round(myTot/myS.length).toLocaleString('en-IN')} sub="u" accent={C.a4}/>
            </div>
            <svg viewBox="0 0 700 50" style={{width:'100%', height:50, display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
              {(()=>{ const mx=Math.max(...myS,1); const n=myS.length;
                return myS.map((v,i)=>{ const h=Math.max(1,(v/mx)*38); const w=Math.max(2,(680/n)-2);
                  return <rect key={i} x={10+i*(680/n)} y={44-h} width={w} height={h} fill={C.ac}/>; }); })()}
            </svg>
            <Reading soWhat="This is the live committed series — overrides, demand-sensing and lifecycle shaping all write here, and the event trail above records which one set the current numbers."/>
          </>)}
        </Card>
        <Card icon="🏢" title="All-SKU Consensus" badge={`${committedCount}/${finished.length} committed`} badgeTone="y"
          right={<Provenance kind="derived"/>}
          info={{ what:'Every finished SKU on one line: the forecast-driven committed number (MTS) and the contracted firm-order backlog (MTO) side by side, summed to a company total.', flows:'Consensus → S&OP aggregate / capital plan.' }}
          dev={{ comp:'AllSkuConsensus', props:'demand (all SKUs) + M.orders (firm)', state:'Σ appStore.demand · Σ firm MTO' }}>
          <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
            <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
              <thead><tr style={{background:C.ink}}>
                {['SKU','Item','Committed Σ (MTS)','Firm MTO','Set by'].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i>1?'right':'left', padding:'5px 8px', fontSize:8.5}}>{h}</th>)}
              </tr></thead>
              <tbody>
                {finished.map((p,i)=>{ const t=sumOf(p.sku); const fm=firmFor(p.sku); const e=lastFor(p.sku); const me=p.sku===sku;
                  return (
                  <tr key={p.sku} style={{background: me?C.ac: i%2?C.bg3:C.paper, borderTop:`1px solid ${C.line2}`}}>
                    <td style={{padding:'4px 8px', fontWeight:700, color:me?C.onAc:C.tx2}}>{p.sku}</td>
                    <td style={{padding:'4px 8px', color:me?C.onAc:C.tx2}}>{p.name}</td>
                    <td className="num" style={{padding:'4px 8px', textAlign:'right', fontWeight:700, fontFamily:F.disp, fontSize:12, color: me?C.onAc:(t!=null?C.tx:C.tx3)}}>{t!=null?Math.round(t).toLocaleString('en-IN'):'—'}</td>
                    <td className="num" style={{padding:'4px 8px', textAlign:'right', fontWeight:700, fontFamily:F.disp, fontSize:12, color: me?C.onAc:(fm!=null?C.a2:C.tx3)}}>{fm!=null?Math.round(fm).toLocaleString('en-IN'):'—'}</td>
                    <td style={{padding:'4px 8px', textAlign:'right', fontSize:9, color:me?C.onAc:C.tx3}}>{t!=null?(e?COMMIT_SRC[e.type]:'Forecast'):'not run'}</td>
                  </tr>
                );})}
                <tr style={{background:C.ink}}>
                  <td colSpan={2} style={{padding:'5px 8px', color:C.paper, fontWeight:800, fontFamily:F.disp}}>COMPANY Σ</td>
                  <td className="num" style={{padding:'5px 8px', textAlign:'right', color:C.paper, fontWeight:800, fontFamily:F.disp, fontSize:13}}>{Math.round(grand).toLocaleString('en-IN')}</td>
                  <td className="num" style={{padding:'5px 8px', textAlign:'right', color:C.ac2, fontWeight:800, fontFamily:F.disp, fontSize:13}}>{grandFirm?Math.round(grandFirm).toLocaleString('en-IN'):'—'}</td>
                  <td style={{padding:'5px 8px', textAlign:'right', color:C.ac, fontSize:9, fontWeight:700}}>consensus</td>
                </tr>
              </tbody>
            </table>
          </div>
          <Reading formula="MTS committed = Σ each forecast/override series · MTO firm = Σ firm orders in the order book (status='firm')"
            soWhat={committedCount<finished.length ? `${finished.length-committedCount} SKU(s) have no committed series yet — run their forecast so the consensus reflects the whole portfolio. Firm MTO orders (₹-blue) are already contracted backlog independent of the forecast.` : 'Every finished SKU has a committed MTS number; the firm MTO column (₹-blue) is contracted backlog already on the books — together they are the full consensus demand the S&OP and capital plans consume.'}/>
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
function DemModels({ onNav, fc, item }) {
  const { gate } = useProfile();
  // LIVE /api/forecast leaderboard only (model/mape/rmse/mae/status), sorted by MAPE.
  // No mock fallback — before a run we show an honest empty/running state.
  const res = fc && fc.result;
  const prod = res && res.products && res.products[0];
  const lb = prod && Array.isArray(prod.leaderboard)
    ? [...prod.leaderboard].filter(m=>m && m.model).sort((a,b)=>(a.mape??1e9)-(b.mape??1e9))
    : null;
  const winnerKey = prod && (prod.winner || prod.recommendation);
  const winMape = lb && winnerKey ? (lb.find(m=>m.model===winnerKey)||{}).mape : null;
  // honest engine-availability read-out from the backend's reported env.
  const env = res && res.env;
  const envOff = env ? [!env.statsmodels&&'Holt-Winters/ARIMA', !env.sklearn&&'ML (RF/GBM/MLP)', !env.xgboost&&'XGBoost'].filter(Boolean) : [];
  if(gate.demandModels) return (
    <StageSection step="4" title="Model Competition" sub="bypassed — you import a finished forecast">
      <GateNote onNav={onNav}>An <b>external forecast</b> is loaded, so the model competition is skipped — the imported numbers flow straight to Aggregate / Profit-mix.</GateNote>
    </StageSection>
  );
  return (
    <StageSection step="4" title="Model Competition" sub="every model the live engine actually ran on YOUR history — MAPE, RMSE, MAE, fit status">
      <Card icon="🏆" title="Forecast Leaderboard" badge={lb?`${lb.length} models · live`:(fc&&fc.solving?'running…':'idle')} badgeTone="k"
        info={{ what:'Ranked competition incl. intermittent (Croston/SBA/TSB), each scored on a held-back tail of your own history.', flows:'Winner → committed forecast.' }}
        right={lb ? <Provenance kind="solved" asOf={fc.ranAt?fc.ranAt.toLocaleTimeString():undefined}/> : undefined}
        dev={{ comp:'ModelCompetition', props:'item, forecastResults' }}>
        {lb ? (
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
            <thead><tr style={{background:C.ink}}>
              {['#','Model','MAPE','RMSE','MAE','Status',''].map((h,i)=>(
                <th key={i} style={{color:C.paper, textAlign:i<2?'left':'right', padding:'6px 9px', fontSize:8.5, letterSpacing:'.04em', textTransform:'uppercase', fontWeight:700, whiteSpace:'nowrap'}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {lb.map((m,i)=>{ const win = m.model===winnerKey; const ok = (m.status||'ok')==='ok';
                return (
                <tr key={i} style={{background: win?C.ac: i%2?C.bg3:C.paper, borderTop:`1px solid ${C.line2}`, opacity: ok?1:0.5}}>
                  <td style={{padding:'4px 9px', fontWeight:700, color:win?C.onAc:C.tx2}}>{i+1}</td>
                  <td style={{padding:'4px 9px', fontWeight:700, whiteSpace:'nowrap'}}>{win&&'★ '}{FCAST_MODEL_LABEL[m.model]||m.model} {FCAST_INT.has(m.model) && <Tag c="v">INT</Tag>}{m.model==='ensemble' && <Tag c="c" title={(m.components||[]).map(c=>`${FCAST_MODEL_LABEL[c.model]||c.model} ${(c.weight*100).toFixed(0)}%`).join(' · ')}>BLEND</Tag>}</td>
                  <td className="num" style={{textAlign:'right', padding:'4px 9px', fontWeight:700}}>{m.mape!=null?m.mape.toFixed(1)+'%':'—'}</td>
                  <td className="num" style={{textAlign:'right', padding:'4px 9px'}}>{m.rmse!=null?m.rmse.toFixed(1):'—'}</td>
                  <td className="num" style={{textAlign:'right', padding:'4px 9px'}}>{m.mae!=null?m.mae.toFixed(1):'—'}</td>
                  <td style={{padding:'4px 9px', textAlign:'right', fontSize:9, color:ok?C.tx3:C.dg}}>{m.status||'ok'}</td>
                  <td style={{padding:'4px 9px', textAlign:'right'}}>{win?<Tag c="k">WINNER</Tag>:''}</td>
                </tr>
              );})}
            </tbody>
          </table>
        </div>
        ) : (
        <div style={{padding:'20px 14px', border:`2px dashed ${C.line2}`, background:C.bg3, textAlign:'center', fontFamily:F.mono, fontSize:10.5, color:C.tx2, lineHeight:1.6}}>
          {(()=>{ const s=fcStatus(fc);
            if(s.kind==='warming') return <span style={{color:C.a4}}>🌱 Warming up — too little history to run the competition yet ({s.msg}). Add/import more history and re-run; this is a cold start, not an error.</span>;
            if(s.kind==='error') return <span style={{color:C.dg}}>Forecast engine error: {s.msg}</span>;
            if(s.kind==='running') return <>Running the model competition on your history…</>;
            return <>No live result yet — press <b>🤖 Run Forecast</b> (top right). Nothing is fabricated here.</>;
          })()}
        </div>
        )}
        {env && (
          <div style={{marginTop:8, fontFamily:F.mono, fontSize:9, color: envOff.length?C.dg:C.tx3}}>
            ⚙ {envOff.length ? `engines OFFLINE: ${envOff.join(', ')} — install statsmodels / scikit-learn / xgboost to enable` : 'all engines available · classical + ARIMA + ML + DL'}
          </div>
        )}
        <Reading formula="holdout MAPE = mean |actual − pred| / actual on the held-back tail (lower wins)"
          soWhat={lb?`Live engine ranked ${lb.length} models on your history; ★ ${FCAST_MODEL_LABEL[winnerKey]||winnerKey} won${winMape!=null?` at ${winMape.toFixed(1)}% MAPE`:''}. Models that failed to fit (greyed) are shown honestly, not hidden.`:"The leaderboard populates only from a live run — there is no illustrative table standing in for it."}/>
      </Card>
      {/* W9 · Demand L4 — accuracy-by-horizon backtest + ensemble gate + reconciliation. */}
      {prod && (prod.accuracy_by_horizon || prod.ensemble || (res && res.reconciliation)) &&
        <div style={{marginTop:14}}><DemHorizon prod={prod} res={res}/></div>}
      {/* FVA — scores the FORECAST process, computed from the live leaderboard. */}
      <div style={{marginTop:14}}><FVACard lb={lb} winnerKey={winnerKey}/></div>
      {/* D-6 — trigger monitor on the winner's quality metrics (live). */}
      <div style={{marginTop:14}}><TriggerMonitor winner={lb && winnerKey ? lb.find(m=>m.model===winnerKey) : null} item={item}/></div>
    </StageSection>
  );
}

// ── W9 · Demand L4 — accuracy-by-horizon + ensemble gate + reconciliation ──
// Three depth signals the headline MAPE hides: how the winner's error grows step
// by step into the future (a held-back backtest), whether a top-N ensemble was
// blended or honestly skipped on thin data (D-5), and the bottom-up reconciliation
// that makes the SKU and aggregate forecasts agree by construction (D-8). All read
// straight from the live /api/forecast result — nothing fabricated.
function DemHorizon({ prod, res }){
  const abh = prod && prod.accuracy_by_horizon;
  const rec = res && res.reconciliation;
  const ens = prod && prod.ensemble;
  if(!abh && !rec && !ens) return null;
  const mx = abh && abh.length ? Math.max(5, ...abh.map(s=>s.ape)) : 1;
  return (
    <Card icon="📐" title="Accuracy by Horizon & Reconciliation" badge="W9 · Demand L4" badgeTone="c"
      info={{ what:'How the winner\'s error grows step-by-step into the future (the headline MAPE averages it away), whether a top-N ensemble was blended or skipped, and the bottom-up reconciliation that makes the SKU and total forecasts agree.', flows:'Horizon decay → how far out to trust the plan; reconciliation → coherent SKU↔aggregate.' }}
      right={<Provenance kind="solved"/>}
      dev={{ comp:'DemHorizon', props:'prod.accuracy_by_horizon, prod.ensemble, res.reconciliation' }}>
      {abh && abh.length>0 && <>
        <SubLabel>Winner APE by horizon step (holdout backtest)</SubLabel>
        <div style={{display:'flex', alignItems:'flex-end', gap:6, height:90, marginBottom:6}}>
          {abh.map((s,i)=>(
            <div key={i} style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:3}}>
              <div style={{width:'70%', height:`${Math.max(2,s.ape/mx*70)}px`, background:s.ape>15?C.dg:C.ac, border:`1px solid ${C.line}`}} title={`${s.ape}% APE`}/>
              <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>h{s.step}</span>
            </div>
          ))}
        </div>
        <Reading formula="APEₖ = |actualₖ − forecastₖ| / actualₖ on the held-back tail, per step k ahead"
          soWhat={`Step-1 error ${abh[0].ape}% → step-${abh.length} ${abh[abh.length-1].ape}%: ${abh[abh.length-1].ape>abh[0].ape*1.4?'accuracy decays materially further out — trust the near horizon, re-forecast the far one':'error stays stable across the horizon — the forecast holds out to '+abh.length+' steps'}.`}/>
      </>}
      {ens && <div style={{marginTop:10, fontFamily:F.mono, fontSize:9.5, color:C.tx2, padding:'7px 9px', border:`2px solid ${C.line2}`, background:C.bg3}}>
        {ens.skipped ? `🔀 Ensemble skipped — ${ens.reason}.` : `🔀 Ensemble (D-5): ${(ens.components||[]).map(c=>`${FCAST_MODEL_LABEL[c.model]||c.model} ${(c.weight*100).toFixed(0)}%`).join(' + ')} · gated on ${ens.gated_on}.`}
      </div>}
      {rec && <div style={{marginTop:10}}>
        <SubLabel>Hierarchical reconciliation ({(rec.method||'bottom_up').replace('_','-')})</SubLabel>
        <KpiRow cols={2}>
          <Blk label="Series reconciled" value={`${rec.n_series}`} tone="c"/>
          <Blk label="Coherent total / horizon" value={`${Math.round(rec.total_horizon).toLocaleString('en-IN')} u`} tone="y"/>
        </KpiRow>
        <div style={{marginTop:4, fontFamily:F.mono, fontSize:9, color:C.tx3}}>{rec.note}</div>
      </div>}
    </Card>
  );
}

// ── Forecast-quality trigger monitor (W1 · D-6) ───────────────────────────
// Reads the winner's LIVE metrics (forecast.py already returns mape, bias,
// tracking_signal, out_of_control). A breach = the forecast can no longer be
// trusted unattended → the planner should re-forecast / intervene. Thresholds
// are the textbook ones; the MAPE target is the item's own accuracy target (seed
// `item.mape`) so "breach" means worse than this SKU is expected to forecast.
// Acknowledging writes a 'trigger' event — no side-effects fire during render.
// DM-C — effect-only child (mounted ONLY when a breach exists, so its hook order is
// stable): on a NEW breach signature it auto-flags downstream solves stale via the
// recompute DAG (a forecast that's out of control shouldn't silently drive the plan)
// and logs an immutable 'auto_trigger' event. Fires once per unique breach set.
function BreachFlagger({ sig, item, metrics }){
  const ref = React.useRef('');
  useEffect(()=>{ if(sig && ref.current!==sig){ ref.current = sig; markStale('demand');
    logEvent('auto_trigger', item&&item.code, { breaches: sig.split('|'), ...(metrics||{}) }); }
  }, [sig]); // eslint-disable-line
  return null;
}
function TriggerMonitor({ winner, item }) {
  const [ack, setAck] = useState(null);
  if(!winner) return (
    <Card icon="🚨" title="Forecast Quality Triggers" badge="needs a live run"
      info={{ what:'Watches the winner’s MAPE, bias and tracking signal for out-of-control forecasts.', flows:'Breach → re-forecast / planner review.' }}>
      <div style={{padding:'16px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3}}>Run the forecast — the monitor reads the winner’s live error metrics.</div>
    </Card>
  );
  const target = (item && item.mape) || 15;                  // this SKU's accuracy target (%)
  const mape = winner.mape, bias = winner.bias, ts = winner.tracking_signal, ooc = winner.out_of_control;
  const checks = [
    { k:'MAPE vs target', v: mape!=null?`${mape.toFixed(1)}% / ${target}%`:'—', bad: mape!=null && mape > target + 5,
      note:`accuracy ${mape!=null && mape>target+5?'breaches':'within'} the ${target}% target (+5pt tolerance)` },
    { k:'Bias (signed)', v: bias!=null?bias.toFixed(2):'—', bad: bias!=null && Math.abs(bias) > Math.max(1, target*0.3),
      note:`${bias!=null && bias>0?'over':'under'}-forecasting drift` },
    { k:'Tracking signal', v: ts!=null?ts.toFixed(2):'—', bad: (ts!=null && Math.abs(ts) > 4) || !!ooc,
      note:'|TS|>4 ⇒ systematic, non-random error (out of control)' },
  ];
  const breaches = checks.filter(c=>c.bad);
  const fire = ()=>{ logEvent('trigger', item&&item.code, { breaches: breaches.map(b=>b.k), mape, bias, ts }); setAck(new Date()); };
  return (
    <Card icon={breaches.length?'🚨':'✅'} title="Forecast Quality Triggers" badge={breaches.length?`${breaches.length} breach`:'in control'} badgeTone={breaches.length?'k':'y'}
      right={<Provenance kind="solved"/>}
      info={{ what:'Watches the winner’s MAPE, bias and tracking signal; flags when the forecast is out of control.', flows:'Breach → re-forecast / planner review (logged as a trigger event).' }}
      dev={{ comp:'TriggerMonitor', props:'winner metrics, item.mape', state:'events[] (trigger)' }}>
      <div style={{display:'flex', flexDirection:'column', gap:6}}>
        {checks.map((c,i)=>(
          <div key={i} style={{display:'flex', alignItems:'center', gap:10, border:`2px solid ${c.bad?C.dg:C.line}`, borderLeft:`5px solid ${c.bad?C.dg:C.gn}`, padding:'6px 10px', background: c.bad?C.bg3:C.paper}}>
            <Tag c={c.bad?'r':'g'}>{c.bad?'BREACH':'OK'}</Tag>
            <span style={{fontFamily:F.disp, fontSize:12, fontWeight:700, width:140}}>{c.k}</span>
            <span className="num" style={{fontFamily:F.disp, fontWeight:800, fontSize:13, width:90}}>{c.v}</span>
            <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3, flex:1}}>{c.note}</span>
          </div>
        ))}
      </div>
      {breaches.length>0 && (
        <div style={{marginTop:10, display:'flex', alignItems:'center', gap:10}}>
          <BreachFlagger sig={breaches.map(b=>b.k).join('|')} item={item} metrics={{ mape, bias, ts }}/>
          <Btn kind="danger" sm onClick={fire}>Log review trigger</Btn>
          <span style={{fontFamily:F.mono, fontSize:8.5, color: ack?C.gn:C.dg}}>{ack?`✓ trigger logged · ${ack.toLocaleTimeString()}`:`${breaches.length} metric(s) out of control — auto-flagged downstream stale; re-forecast or review`}</span>
        </div>
      )}
      <Reading formula="breach if MAPE>target+5pt · |bias|>0.3·target · |tracking signal|>4 (or engine out_of_control)"
        soWhat={breaches.length?`The winning model is out of control on ${breaches.map(b=>b.k.toLowerCase()).join(', ')} — its numbers shouldn't drive the plan unreviewed.`:'The winning model is inside all control limits — safe to let it drive the committed plan.'}/>
    </Card>
  );
}

// Forecast Value-Add: naive MAPE − winner MAPE, both read from the LIVE run.
function FVACard({ lb, winnerKey }) {
  if(!lb || !lb.length) return (
    <Card icon="📐" title="Forecast Value-Add (FVA)" badge="needs a live run"
      info={{ what:'Does the chosen model actually beat the naive baseline? Computed from the live leaderboard.', flows:'FVA → keep the statistical step, or fall back to autopilot.' }}>
      <div style={{padding:'16px', fontFamily:F.mono, fontSize:10.5, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3}}>Run the forecast to compute FVA against the naive baseline.</div>
    </Card>
  );
  const naive = lb.find(m=>m.model==='naive');
  const winner = lb.find(m=>m.model===winnerKey) || lb[0];
  const nM = naive ? naive.mape : null, wM = winner ? winner.mape : null;
  const fva = (nM!=null && wM!=null) ? +(nM - wM).toFixed(2) : null;
  const rows = [['Naive baseline', nM, C.tx3], [`Winner · ${FCAST_MODEL_LABEL[winnerKey]||winnerKey||'—'}`, wM, C.gn]];
  const mx = Math.max(...rows.map(r=>r[1]||0), 1);
  return (
    <Card icon="📐" title="Forecast Value-Add (FVA)" badge="from live run"
      right={<Provenance kind="derived"/>}
      info={{ what:'FVA = naive MAPE − winner MAPE, both from the live run. Positive ⇒ the statistical step earns its keep.', flows:'FVA → keep the statistical step, or fall back to autopilot.' }}
      dev={{ comp:'FVACard', props:'forecast leaderboard (live)' }}>
      <div style={{display:'flex', flexDirection:'column', gap:6, marginTop:2}}>
        {rows.map(([k,v,c],i)=>(
          <div key={i}><div style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:10}}><span>{k}</span><span style={{fontWeight:700}}>{v!=null?v.toFixed(1)+'%':'—'}</span></div><MiniBar v={mx-(v||0)} max={mx} color={c} h={10}/></div>
        ))}
      </div>
      <Reading formula="FVA = naive MAPE − winner MAPE  (positive ⇒ the model beats naive)"
        soWhat={fva!=null ? (fva>0.5 ? `The winner adds +${fva.toFixed(1)} MAPE points over naive — the statistical step earns its keep.` : `The winner is within ${Math.abs(fva).toFixed(1)} pt of naive — barely worth the complexity for this SKU; autopilot (s,S) may be enough.`) : 'Naive baseline not present in this run, so FVA can’t be computed.'}/>
    </Card>
  );
}

function DemSegment({ item, fc }) {
  const cell=(n)=> n===0?C.bg3 : n===1?C.ac : C.ink;
  // derive the 9-box counts from the actual finished products (was a static table).
  const abcxyz = ['A','B','C'].map(a=>{
    const r={abc:a, X:0, Y:0, Z:0};
    M.products.filter(p=>p.cat==='Finished').forEach(p=>{ if(p.abc===a && (p.xyz==='X'||p.xyz==='Y'||p.xyz==='Z')) r[p.xyz]++; });
    return r;
  });
  return (
    <StageSection step="5" title="Segmentation & Lifecycle" sub="ABC = annual ₹-value Pareto · XYZ = demand CV · each cell prescribes a policy + model">
      <Grid cols={2}>
        <Card icon="🏷️" title="ABC / XYZ → method" badge="9-box"
          info={{ what:'Value (ABC) × variability (XYZ) classification — and the planning method it routes to.', flows:'Segment → policy, forecast-model, and autopilot-vs-optimizer routing.' }}
          dev={{ comp:'ABCXYZCard', props:'products, M.itemMethod' }}>
          <div style={{display:'grid', gridTemplateColumns:'40px 1fr 1fr 1fr', gap:4, marginTop:6}}>
            <div/>{['X · steady','Y · variable','Z · erratic'].map((h,i)=><div key={i} style={{fontFamily:F.mono, fontSize:9, color:C.tx3, textAlign:'center', textTransform:'uppercase'}}>{h}</div>)}
            {abcxyz.map((row,ri)=>(
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
            <div style={{marginTop:6, fontFamily:F.mono, fontSize:8.5, color:C.tx3, lineHeight:1.5}}>autopilot = (s,S)/ROP/EOQ rule, no solver · optimized = LP/MILP optimizer (coupled capacity/MOQ/budget). Don’t drag a stable washer through the optimizer.</div>
          </div>
        </Card>
        <LifecycleCard item={item} fc={fc}/>
      </Grid>
    </StageSection>
  );
}

// ── Lifecycle shaping (W1 · D-3) — OPT-IN, transparent, reversible ─────────
// The concern this card answers: "most people won't know if this applies."
// So it leads with a plain decider, DEFAULTS to None (no shaping — the forecast
// already reflects recent demand), shows the exact before→after on the committed
// total, and only changes the numbers the MILPs read when you explicitly Apply.
// It is a planning JUDGEMENT (a chosen multiplier), never a claimed statistical fit.
const LC_PHASES = [
  { key:null,        ph:'None',     v:1.0, when:'Default. Steady SKU, or you’re not sure — leave it here. The statistical forecast already reflects recent demand.' },
  { key:'launch',    ph:'Launch',   v:0.3, when:'Brand-new SKU with little history. Early demand is a fraction of the eventual run-rate; the stat model can over-read sparse early sales.' },
  { key:'growth',    ph:'Growth',   v:0.7, when:'Ramping but not yet at steady state — adoption still climbing.' },
  { key:'maturity',  ph:'Maturity', v:1.0, when:'Established, stable demand. Multiplier is 1.0 (no shaping) — pick it to record the judgement explicitly.' },
  { key:'decline',   ph:'Decline',  v:0.55,when:'Being phased out / superseded; recent history overstates forward demand.' },
];
function LifecycleCard({ item, fc }) {
  const sku = (item && item.code) || '';
  const { di, setDI } = useDemandInputs(sku);
  const [savedAt, setSavedAt] = useState(null);
  const sel = LC_PHASES.find(p=>p.key===di.lifecycle) || LC_PHASES[0];
  const base = winnerForecast(fc && fc.result);
  const baseTot = base && base.length ? base.reduce((a,b)=>a+(b||0),0) : null;
  const shapedTot = baseTot!=null ? Math.round(baseTot*sel.v) : null;
  const setPhase = (key)=>{ setDI({ lifecycle:key }); setSavedAt(null); };
  const apply = ()=>{ if(!base || !base.length || !sku) return;
    const shaped = base.map(v=>Math.max(0, Math.round((v||0)*sel.v)));
    setItemDemand(sku, shaped);                       // → markStale('demand') cascades
    logEvent('lifecycle', sku, { phase: sel.ph, multiplier: sel.v, baseTot:Math.round(baseTot), shapedTot });
    setSavedAt(new Date());
  };
  return (
    <Card icon="🔄" title="Lifecycle Shaping" badge={sel.key?`${sel.ph} ×${sel.v}`:'none (default)'} badgeTone={sel.key?'y':undefined}
      right={<Provenance kind="external" run={sel.key?'user':'seed'}/>}
      info={{ what:'OPT-IN judgement: scale the statistical forecast for where the SKU sits in its life. Default None = no change.', flows:'Apply → committed demand → Sourcing/Production.' }}
      dev={{ comp:'LifecycleCard', props:'demandInputs[sku].lifecycle', note:'Opt-in multiplier on committed series; never a claimed fit. Apply is explicit + reversible (re-run forecast restores the raw base).' }}>
      <div style={{display:'flex', gap:6, marginBottom:10, flexWrap:'wrap'}}>
        {LC_PHASES.map((d)=>{ const on = d.key===sel.key;
          return (
          <button key={d.ph} onClick={()=>setPhase(d.key)} style={{
            fontFamily:F.mono, fontSize:9.5, fontWeight:700, padding:'4px 9px', cursor:'pointer',
            border:`2px solid ${C.line}`, background: on?C.ac:C.paper, color: on?C.onAc:C.tx,
          }}>{on?'● ':'○ '}{d.ph} ×{d.v}</button>
        );})}
      </div>
      <div style={{padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${sel.key?C.a4:C.tx3}`, background:C.bg3, marginBottom:10, fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.45}}>
        <b>{sel.ph}:</b> {sel.when}
      </div>
      {/* before → after impact, computed from the live forecast (no fabricated numbers) */}
      {baseTot!=null ? (
        <div style={{display:'flex', alignItems:'stretch', gap:8, marginBottom:8}}>
          <div style={{flex:1, border:`2px solid ${C.line}`, padding:'7px 10px', background:C.paper}}>
            <div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, textTransform:'uppercase'}}>Statistical base Σ</div>
            <div className="num" style={{fontFamily:F.disp, fontWeight:800, fontSize:15}}>{Math.round(baseTot).toLocaleString('en-IN')} u</div>
          </div>
          <div style={{display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:11, fontWeight:700, color:C.tx3}}>×{sel.v} →</div>
          <div style={{flex:1, border:`2px solid ${sel.v!==1?C.ac:C.line}`, padding:'7px 10px', background: sel.v!==1?C.ac:C.paper}}>
            <div style={{fontFamily:F.mono, fontSize:8.5, color: sel.v!==1?C.onAc:C.tx3, textTransform:'uppercase'}}>Shaped Σ</div>
            <div className="num" style={{fontFamily:F.disp, fontWeight:800, fontSize:15, color: sel.v!==1?C.onAc:C.tx}}>{shapedTot.toLocaleString('en-IN')} u</div>
          </div>
        </div>
      ) : (
        <div style={{padding:'12px', fontFamily:F.mono, fontSize:10, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`, background:C.bg3, marginBottom:8}}>Run the forecast to preview the lifecycle impact.</div>
      )}
      <div style={{display:'flex', alignItems:'center', gap:10}}>
        <Btn kind="primary" sm onClick={apply} disabled={!base||!base.length||sel.v===1} style={(!base||!base.length||sel.v===1)?{opacity:.45, cursor:'not-allowed'}:undefined}>{sel.v===1?'No change to apply':'Apply shaping → demand'}</Btn>
        <span style={{fontFamily:F.mono, fontSize:8.5, color: savedAt?C.gn:C.tx3}}>{savedAt?`✓ committed · ${savedAt.toLocaleTimeString()}`:(sel.v===1?'identity multiplier — nothing to write':'not applied — committed demand unchanged')}</span>
      </div>
      <Reading formula="shaped = statistical base × lifecycle multiplier (a chosen planning factor, not a fitted curve)"
        soWhat="Nothing changes until you Apply; re-running the forecast restores the raw base, so this is fully reversible. Leave it on None when unsure — the model already learns the trend from recent history."/>
    </Card>
  );
}

// ── Governed promotions + holidays (W1 · D-1) ─────────────────────────────
// A planned promo is a horizon-relative period flag fed to the forecast ML promo
// regressor (forecast.py _build_features → 'promo' column). The lift that shows
// up is REAL but proportional to the effect the engine learned from your history
// — we say so, rather than painting a fixed +X% on the curve.
function futureLabel(grain, k){
  const start = (window.M && M.calendar && M.calendar.start) || '2026-06-01';
  const step = grain==='daily' ? 1 : grain==='weekly' ? 7 : 30;
  const d = new Date(start + 'T00:00:00'); d.setDate(d.getDate() + k*step);
  return String(d.getDate()).padStart(2,'0') + ' ' + ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()] + " '" + String(d.getFullYear()).slice(2);
}
function DemEvents({ item, grain }) {
  const sku = (item && item.code) || '';
  const g = grain || 'daily';
  const gl = M.grainLabel(g);
  const H = M.horizonFor(g);
  const { di, setDI } = useDemandInputs(sku);
  const { holidays, setHolidays } = useHolidays();
  const [pf, setPf] = useState('0');          // chosen future period (offset)
  const [kind, setKind] = useState('Promotion');
  const [hol, setHol] = useState('');
  const promos = di.promos || [];
  const addPromo = ()=>{ const fidx = Number(pf);
    if(promos.some(p=>p.fidx===fidx)) return;     // one flag per period
    setDI({ promos:[...promos, { fidx, kind: kind||'Promotion' }].sort((a,b)=>a.fidx-b.fidx) });
    logEvent('promo', sku, { period:fidx+1, kind });
  };
  const delPromo = (fidx)=> setDI({ promos: promos.filter(p=>p.fidx!==fidx) });
  const addHol = ()=>{ const v=(hol||'').trim();
    if(!/^\d{4}-\d{2}-\d{2}$/.test(v) || holidays.includes(v)) return;
    setHolidays([...holidays, v].sort()); setHol(''); };
  const delHol = (v)=> setHolidays(holidays.filter(h=>h!==v));
  return (
    <StageSection step="6" title="Promotions & Calendar" sub="governed forecast inputs — flag a planned promo period or a holiday; the engine re-runs and lifts/adjusts those periods by the effect it learned from your history">
      <Grid cols={2}>
        <Card icon="🎯" title="Planned Promotions → forecast" badge={promos.length?`${promos.length} flagged`:'none set'} badgeTone={promos.length?'y':undefined}
          right={<Provenance kind="external" run={promos.length?'user':'seed'}/>}
          info={{ what:'Flag forecast periods that have a planned promotion; each becomes a promo=1 feature the ML models use.', flows:'Promo flag → forecast promo regressor → committed demand.' }}
          dev={{ comp:'PromoCard', props:'demandInputs[sku].promos', state:'promos:[{fidx,kind}] → fcPayload.promo_periods' }}>
          <Grid cols={3} gap={8}>
            <Field label={`Forecast ${gl}`} span={2}><Select value={pf} onChange={setPf} options={Array.from({length:H},(_,k)=>({ value:String(k), label:`P${k+1} · ${futureLabel(g,k)}` }))}/></Field>
            <Field label="Type"><TextInput value={kind} onChange={setKind}/></Field>
          </Grid>
          <div style={{marginTop:8}}><Btn kind="primary" sm onClick={addPromo}>+ Flag promo period</Btn></div>
          <div style={{marginTop:10, border:`2px solid ${C.line}`}}>
            {promos.length===0 ? (
              <div style={{padding:'14px', fontFamily:F.mono, fontSize:10, color:C.tx3, textAlign:'center'}}>No promotions flagged — the forecast runs unpromoted.</div>
            ) : promos.map((p,i)=>(
              <div key={p.fidx} style={{display:'flex', alignItems:'center', gap:8, padding:'6px 10px', borderTop:i?`1px solid ${C.line2}`:'none', background:i%2?C.bg3:C.paper}}>
                <Tag c="y">P{p.fidx+1}</Tag>
                <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>{futureLabel(g,p.fidx)}</span>
                <span style={{fontFamily:F.disp, fontSize:11, fontWeight:700, marginLeft:4}}>{p.kind}</span>
                <button onClick={()=>delPromo(p.fidx)} style={{marginLeft:'auto', border:'none', background:'transparent', cursor:'pointer', color:C.dg, fontFamily:F.mono, fontSize:11, fontWeight:700}}>✕</button>
              </div>
            ))}
          </div>
          <Reading formula="promo[t]=1 → ML lift learned from past promo-labelled demand (forecast.py _build_features)"
            soWhat="Flagging a period re-runs the forecast with that period marked promotional. The lift is real but proportional to the effect the engine learned from history — on a flat history it may be near-zero, which is honest, not broken."/>
        </Card>
        <Card icon="📅" title="Holiday Calendar → forecast" badge={holidays.length?`${holidays.length} dates`:'none set'} badgeTone={holidays.length?'y':undefined}
          right={<Provenance kind="external" run={holidays.length?'user':'seed'}/>}
          info={{ what:'Global ISO holiday dates become a holiday=1 calendar feature the forecast engine uses.', flows:'Holiday → forecast calendar feature → committed demand.' }}
          dev={{ comp:'HolidayCard', props:'state.holidays', state:'holidays:[ISO] → fcPayload.params.holidays' }}>
          <Grid cols={3} gap={8}>
            <Field label="Date (YYYY-MM-DD)" span={2}><TextInput value={hol} onChange={setHol}/></Field>
            <div style={{display:'flex', alignItems:'flex-end'}}><Btn kind="primary" sm onClick={addHol}>+ Add</Btn></div>
          </Grid>
          <div style={{marginTop:10, display:'flex', flexWrap:'wrap', gap:6}}>
            {holidays.length===0 ? (
              <div style={{padding:'14px', width:'100%', fontFamily:F.mono, fontSize:10, color:C.tx3, textAlign:'center', border:`2px dashed ${C.line2}`}}>No holidays set — calendar feature is all-zero.</div>
            ) : holidays.map(h=>(
              <span key={h} style={{display:'inline-flex', alignItems:'center', gap:6, border:`2px solid ${C.line}`, padding:'3px 8px', background:C.paper, fontFamily:F.mono, fontSize:10, fontWeight:700}}>
                {h}<button onClick={()=>delHol(h)} style={{border:'none', background:'transparent', cursor:'pointer', color:C.dg, fontWeight:700}}>✕</button>
              </span>
            ))}
          </div>
          <Reading formula="holiday[date]=1 calendar feature (anchored by horizon_start_date)"
            soWhat="Holidays apply across SKUs and only bite the ML/DL models (lag+calendar features). Classical models ignore them — shown honestly in the leaderboard."/>
        </Card>
      </Grid>
    </StageSection>
  );
}
// ════════════════════════════════════════════════════════════════════════
// W9 (Demand L4 tail) · DemImport — REAL CSV history ingestion (D-7) + NPI
// like-modeling. Two cards:
//   D-7  Paste a CSV/TSV series → parse (delimiter + header detection) → bucket to
//        the active grain (by date when present) → preview → "Use as history".
//        Writes histImports[sku]; the forecast then competes models on YOUR data.
//   NPI  A new/low-history item is modeled on an ANALOG SKU: analog history × scale
//        × an adoption ramp → a like-modeled prior, written as committed demand
//        (provenance = derived). Surrogate forecasting, the standard NPI method.
// ════════════════════════════════════════════════════════════════════════
function DemImport({ item, grain, onApplied }){
  const sku = (item && item.code) || '';
  const g = grain || 'daily';
  const gl = M.grainLabel(g);
  const { imp, setImp } = useHistoryImport(sku);
  const [text, setText] = useState('');
  const parsed = React.useMemo(()=> text.trim() ? parseHistoryCsv(text) : null, [text]);
  const series = parsed && !parsed.error ? bucketHistory(parsed.rows, parsed.hasDates, g) : [];
  const applyCsv = ()=>{
    if(!sku || !series.length) return;
    setImp({ grain:g, series, importedAt:new Date().toISOString(), source:'csv' });
    logEvent('import', sku, { rows:series.length, grain:g, source:'csv' });
    setText(''); onApplied && onApplied();
  };
  const clearImp = ()=>{ setImp(null); logEvent('import_clear', sku, {}); onApplied && onApplied(); };

  // NPI like-model
  const fin = (M.products||[]).filter(p=>p.cat==='Finished' && p.sku!==sku);
  const [ref, setRef] = useState(fin[0]?fin[0].sku:'');
  const [scale, setScale] = useState('80');
  const [ramp, setRamp] = useState('3');
  const refHist = ref ? historyFor(ref, g) : [];
  const npiSeries = React.useMemo(()=>{
    if(!refHist.length) return [];
    const sc = (Number(scale)||0)/100, rp = Math.max(0, Math.round(Number(ramp)||0));
    return refHist.map((v,i)=>{ const adopt = rp>0 ? Math.min(1, (i+1)/rp) : 1;
      return Math.max(0, Math.round(v*sc*adopt)); });
  }, [ref, scale, ramp, g, refHist.length]);
  const applyNpi = ()=>{
    if(!sku || !npiSeries.length) return;
    setItemDemand(sku, npiSeries);
    logEvent('npi_likemodel', sku, { analog:ref, scalePct:Number(scale)||0, rampPeriods:Number(ramp)||0 });
    onApplied && onApplied();
  };

  const spark = (arr, color)=>{ if(!arr.length) return null;
    const mx = Math.max(1,...arr), w=Math.max(2, 200/arr.length);
    return <svg viewBox={`0 0 200 36`} style={{width:'100%', height:36, display:'block'}}>
      {arr.map((v,i)=><rect key={i} x={i*w} y={36-v/mx*32} width={Math.max(1,w-1)} height={v/mx*32} fill={color}/>)}
    </svg>;
  };

  return (
    <StageSection step="1b" title={`Import history & NPI · ${item?item.name:''}`} sub="upload your own history (real CSV ingestion) or — for a brand-new product — model it on an analog SKU; both feed the live model competition">
      <div>
        {/* D-7 · CSV import — the common path, always visible */}
        <Card icon="⤓" title="Import history (CSV / TSV)" badge={imp?`imported · ${imp.series.length} ${gl}s`:'paste a series'} badgeTone={imp?'g':'k'}
          right={imp ? <Btn kind="secondary" sm onClick={clearImp}>Clear → seed</Btn> : null}
          info={{ what:'Paste a date,value (or value-only) series. The parser detects the delimiter + a header row and buckets dated rows to the active grain; the forecast engine then competes models on it.', flows:'histImports[sku] → fcPayload.history → /api/forecast.' }}
          dev={{ comp:'DemImport·csv', props:'parseHistoryCsv + bucketHistory', state:'histImports[sku]={grain,series}' }}>
          {imp ? <>
            <div style={{fontFamily:F.mono, fontSize:10, color:C.tx2, marginBottom:6}}>Active import · <b>{imp.series.length}</b> {M.grainLabel(imp.grain)}s · {new Date(imp.importedAt).toLocaleString('en-IN')}{imp.grain!==g?<span style={{color:C.dg}}> · imported at {M.grainLabel(imp.grain)} grain — switch to that grain to forecast on it</span>:''}</div>
            {spark(imp.series.slice(-40), C.a2)}
            <Reading formula="histImports wins over the seed M.historyAt when its grain matches" soWhat={`The forecast above is now competing models on YOUR ${imp.series.length}-point series (re-run with 🤖). Clear to revert to the seed history.`}/>
          </> : <>
            <textarea value={text} onChange={e=>setText(e.target.value)} rows={5} placeholder={"2025-01-01,120\n2025-02-01,138\n2025-03-01,151\n…  (or one value per line)"}
              style={{width:'100%', boxSizing:'border-box', border:`2px solid ${C.line}`, padding:'7px 9px', fontFamily:F.mono, fontSize:10, color:C.tx, outline:'none', resize:'vertical'}}/>
            {parsed && parsed.error && <div style={{fontFamily:F.mono, fontSize:10, color:C.dg, marginTop:6}}>⚠ {parsed.error}</div>}
            {parsed && !parsed.error && <div style={{marginTop:8}}>
              <div style={{fontFamily:F.mono, fontSize:10, color:C.tx2, marginBottom:4}}>
                {parsed.rows.length} rows parsed{parsed.hasDates?` · dated → bucketed to ${gl}`:' · value-only (file order)'} → <b>{series.length}</b> {gl} buckets
              </div>
              {spark(series.slice(-40), C.ac)}
              <div style={{display:'flex', gap:8, marginTop:8}}>
                <Btn kind="primary" sm onClick={applyCsv}>Use as history</Btn>
                <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3, alignSelf:'center'}}>writes histImports[{sku||'—'}] · re-runs the forecast</span>
              </div>
            </div>}
          </>}
        </Card>

        {/* NPI like-modeling — niche (only for brand-new products), hidden behind
            Advanced (Batch 4 🧭) so the default view stays the one common path. */}
        <div style={{marginTop:12}}>
        <Advanced label="New-product (NPI) like-modeling · model a launch on an analog SKU" count={1}>
        <Card icon="🌱" title="NPI like-modeling (analog SKU)" badge="surrogate prior" badgeTone="y"
          info={{ what:'A new or low-history item inherits the demand shape of an analog SKU, scaled and ramped to launch. analog × scale% × adoption-ramp → a like-modeled committed prior (provenance derived) the downstream plan can use until real actuals arrive.', flows:'analog history → setItemDemand[sku] → all downstream solvers.' }}
          dev={{ comp:'DemImport·npi', props:'analog × scale × ramp', state:'demand[sku] via setItemDemand' }}>
          <div style={{display:'flex', gap:8, flexWrap:'wrap', alignItems:'flex-end', marginBottom:8}}>
            <div>
              <SubLabel>Analog SKU</SubLabel>
              <select value={ref} onChange={e=>setRef(e.target.value)} style={{border:`2px solid ${C.line}`, padding:'5px 7px', fontFamily:F.mono, fontSize:10, outline:'none', background:C.paper, color:C.tx}}>
                {fin.map(p=><option key={p.sku} value={p.sku}>{p.sku} · {p.name}</option>)}
              </select>
            </div>
            <SolverInput label="Scale" seed={80} value={scale} onChange={setScale} min={5} max={300} suffix="%" w={84} hint="of analog volume"/>
            <SolverInput label="Adoption ramp" seed={3} value={ramp} onChange={setRamp} min={0} integer suffix={gl+'s'} w={96} hint="periods to full"/>
          </div>
          {npiSeries.length ? <>
            <div style={{fontFamily:F.mono, fontSize:10, color:C.tx2, marginBottom:4}}>like-modeled prior · {npiSeries.length} {gl}s · Σ {npiSeries.reduce((a,b)=>a+b,0).toLocaleString('en-IN')}u (analog {ref} × {Number(scale)||0}% × {Number(ramp)||0}-{gl} ramp)</div>
            {spark(npiSeries, C.a4)}
            <div style={{display:'flex', gap:8, marginTop:8}}>
              <Btn kind="primary" sm onClick={applyNpi}>Apply as committed prior</Btn>
              <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3, alignSelf:'center'}}>writes committed demand for {sku||'—'}</span>
            </div>
            <Reading formula="prior[t] = analog_history[t] × scale × min(1, (t+1)/ramp)" soWhat={`Until ${item?item.name:'the item'} has its own actuals, it plans to ${ref}'s shape scaled to ${Number(scale)||0}% with a ${Number(ramp)||0}-${gl} adoption ramp. Replace it once real sales land (Actuals → sensing).`}/>
          </> : <div style={{fontFamily:F.mono, fontSize:11, color:C.tx3, padding:'10px 0'}}>Pick an analog SKU with history to build a like-modeled launch prior.</div>}
        </Card>
        </Advanced>
        </div>
      </div>
    </StageSection>
  );
}

window.StageDemand = StageDemand;
