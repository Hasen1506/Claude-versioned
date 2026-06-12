// ════════════════════════════════════════════════════════════════════════
// logistics.jsx — Logistics (stage 08, handoff v2 §3.08). This is transport
// OPTIMIZATION OUTPUT, not master data (nodes/lanes/contracts live in Network
// 03). 0 sub-tabs. Each result is a network-flow visual — distinct from the
// Monte-Carlo histogram on Scenarios.
// ════════════════════════════════════════════════════════════════════════
function StageLogistics({ onNav }) {
  const { gate } = useProfile();
  const tr = useSolve('/api/solve/transport', transportPayload, { solveKey:'transport' });   // B-3 — same cache key as Console: a run on either tab persists the result to the map + value ledger
  const runTr = ()=> tr.run().then(d=>{ markSolved('transport'); return d; }).catch(()=>{});   // B-3 — clear the stale flag so the model map colours it fresh
  return (
    <div>
      <StageHeader n="08" title="Logistics · Transport Optimization" kicker="Allocation (per-lane mode LP) · consolidation (LTL→FTL) · center-of-gravity — all network-flow visuals"
        right={<Btn kind="accent" onClick={runTr}>{tr.solving?'⏳ Routing…':'⚡ Solve Transport'}</Btn>}/>
      <div style={{padding:18}}>
        <SolverExplain id="transport"/>
        {gate.transport && <GateNote onNav={onNav}>Your profile is <b>single-site distribution</b> — there is nothing to ship between locations, so the transport solver is off. Switch to a network in Setup to enable it.</GateNote>}
        <PrereqNote onNav={onNav} go="network" goLabel="open Network →">Topology (nodes, lanes, contracts) is master data — defined once in <b>Network (03)</b>. The COST levers the transport LP prices are steered right here (step 0).</PrereqNote>
        {tr.error && <div style={{margin:'0 0 12px', padding:'8px 12px', border:`2px solid ${C.dg}`, borderLeft:`5px solid ${C.dg}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.dg}}>Transport solver: {tr.error}</div>}
        {/* V3-4 — the tab's FIRST steering inputs: lane rates + the SLA deadline as
            GovFields (this tab had ZERO editable inputs; the LP could not be steered). */}
        <StageSection step="0" title="Steering inputs · lane economics" sub="the cost levers the transport LP prices — outbound lane rates (₹/km) and the delivery SLA; every value is the TPAC seed until you override it"><LogSteering/></StageSection>
        <StageSection step="1" title="Allocation" sub="per-lane transport-mode LP (cheapest mode meeting each lane's SLA) + DC→customer min-cost flow assignment (G-L1: which DC serves each customer, cost-optimised)"><LogAllocation tr={tr}/></StageSection>
        <LgModeSplit tr={tr}/>
        <StageSection step="2" title="Consolidation" sub="where merging LTL into FTL cuts cost"><LogConsolidation tr={tr}/>
          {/* V2-7 — the plain-English transport glass-box moved here from the Console's
              (now deleted) duplicate ResTransport card: one-result-one-home. */}
          {tr.result && <div style={{marginTop:12}}><GlassBoxExplainer icon="🚛" title="Why these routes? — plain-English" rows={explainTransport(tr.result)} prov="transport solve"
            note="Every mode/lane and saving above is the freight optimiser's own pick — this only says it in words."/></div>}</StageSection>
        <StageSection step="3" title="Center of Gravity" sub="weighted-distance optimal hub — config and result as one"><LogCoG/></StageSection>
      </div>
    </div>
  );
}

// ── V3-4 · LogSteering — the Logistics tab's first steering inputs ──────────
// The blueprint's Part-5 finding: logistics had ZERO editable inputs (0/2) —
// lane costs were master-data-only, so the transport LP could not be steered
// from the tab that reads its answer. This card converts the COST levers to
// GovFields: each outbound lane's rate (the ₹/km the mode LP and the G-L1
// allocation cost_matrix both price) writes the governed network slice (lanes
// stay master TOPOLOGY in Network 03 — from/to/km/mode are not duplicated
// here), and the delivery SLA (config.slaDeadlineDays, seed 7) is the deadline
// every lane's mode choice must meet. Both ride real SOLVE_DEPS tokens, so the
// used-by chips and the stale cascade are live, not decorative.
// Structured by WHICH MODEL TERM each lever feeds (not "governed vs not"): every
// outbound leg is priced by exactly ONE lever, in exactly one group below —
//   A · SERVICE POLICY — the SLA deadline, a CONSTRAINT on every lane's mode choice.
//   B · MODE TARIFFS (₹/kg) — what prices the mode-booked legs (PLANT→WH, WH→DC):
//       transport.py's MODE_SPECS cost_per_kg, governed via params.mode_overrides.
//       (Their lane `rate` is not a model input — the tariff is the real lever.)
//   C · FINAL-LEG LANE RATES (₹/km) — the DC→customer legs, priced per-lane at
//       rate × km in the G-L1 allocation LP's cost_matrix.
// Topology (from/to/km/mode) stays master data in Network 03.
const _MODE_TARIFFS = [   // seeds = transport.py MODE_SPECS cost_per_kg (the modes TPAC's outbound legs can book)
  { id:'road_ftl',     label:'Road FTL',  seed:1.8 },
  { id:'road_ltl',     label:'Road LTL',  seed:3.5 },
  { id:'rail',         label:'Rail',      seed:1.2 },
  { id:'air_standard', label:'Air Std',   seed:15.0 },
];
function LogSteering(){
  const { network, setNetwork } = useNetwork();
  const { config, setConfig } = useConfig();
  const outbound = (network.lanes||[]).filter(l=>l.direction==='outbound');
  const nodeById = {}; ((window.M&&M.nodes)||[]).forEach(n=>{ nodeById[n.id]=n; });
  const custLanes = outbound.filter(l=> (nodeById[l.to]||{}).type==='customer');
  const modeLegs  = outbound.filter(l=> (nodeById[l.to]||{}).type!=='customer');
  const seedRate = (id)=>{ const s=((window.M&&M.lanes)||[]).find(x=>x.id===id); return s?Number(s.rate):undefined; };
  const setLaneRate = (id, v)=> setNetwork({ lanes: network.lanes.map(l=> l.id===id?{...l, rate:v}:l) });
  const tariffs = config.modeTariffs || {};
  const setTariff = (id, v)=> setConfig({ modeTariffs: { ...tariffs, [id]: v } });
  const group = (k, title, sub)=> (
    <div style={{display:'flex', alignItems:'baseline', gap:8, margin:'12px 0 6px'}}>
      <span style={{fontFamily:F.disp, fontWeight:900, fontSize:12, color:C.ac}}>{k}</span>
      <span style={{fontFamily:F.disp, fontWeight:800, fontSize:11, letterSpacing:'.05em', textTransform:'uppercase'}}>{title}</span>
      <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{sub}</span>
    </div>
  );
  return (
    <Card icon="🎛️" title="Transport cost levers" badge={`${1+_MODE_TARIFFS.length+custLanes.length} governed levers · 3 terms`} badgeTone="y"
      info={{ what:'The transport model’s cost levers, grouped by the model term each one feeds: the SLA constrains every mode choice; mode tariffs (₹/kg) price the mode-booked legs; per-lane rates (₹/km) price the final DC→customer legs in the allocation LP. Every outbound leg is priced by exactly one lever here. Topology stays in Network 03.', flows:'SLA → deadline_days · tariffs → params.mode_overrides[mode].cost_per_kg · DC→customer rate × km → allocation cost_matrix.' }}
      dev={{ comp:'LogSteering', props:'config.slaDeadlineDays · config.modeTariffs · network.lanes[].rate (customer lanes)', state:'setConfig → markStale(config) · setNetwork → markStale(network)' }}>
      {group('A','Service policy','constrains every lane’s mode choice')}
      <Grid cols={3} gap={10}>
        <GovField label="Delivery SLA" token="config" suffix="d" seed={7}
          value={config.slaDeadlineDays} min={1} max={60} integer
          why="The deadline every outbound lane must meet — the mode LP only considers modes whose transit time fits inside it (a tight SLA forces Air; a loose one lets Rail win on cost)."
          formula="mode choice: min cost s.t. transit_days ≤ SLA"
          onChange={(v)=>setConfig({slaDeadlineDays:v})}/>
      </Grid>
      {group('B','Mode tariffs · ₹/kg',`price the mode-booked legs: ${modeLegs.map(l=>`${l.from}→${l.to}`).join(' · ')||'—'}`)}
      <Grid cols={4} gap={10}>
        {_MODE_TARIFFS.map(m=>(
          <GovField key={m.id} label={m.label} token="config" prefix="₹" suffix="/kg" seed={m.seed}
            value={tariffs[m.id]!=null?tariffs[m.id]:m.seed} min={0.1} max={100}
            why={`What ${m.label} charges per kilogram — the mode model prices any leg booked on it at weight × this tariff, then picks the cheapest mode that fits the SLA and the load.`}
            formula={`leg cost = weight_kg × tariff · override → mode_overrides.${m.id}`}
            onChange={(v)=>setTariff(m.id, v)}/>
        ))}
      </Grid>
      {group('C','Final-leg lane rates · ₹/km','price the DC→customer legs in the allocation LP')}
      <Grid cols={3} gap={10}>
        {custLanes.map(l=>(
          <GovField key={l.id} label={`${l.from}→${l.to} · ${l.mode}`} token="network" prefix="₹" suffix="/km" seed={seedRate(l.id)}
            value={l.rate} min={0.5} max={500}
            why={`What this final-leg ${l.mode} lane costs per km (${l.km} km) — the allocation LP prices serving this customer from ${l.from} at rate × km; raise it and the LP reroutes via the cheaper DC.`}
            formula={`cost_matrix[${l.from}→${l.to}] = rate × ${l.km} km`}
            hint={`${l.km} km · lead ${l.lt}d`}
            onChange={(v)=>setLaneRate(l.id, v)}/>
        ))}
      </Grid>
      <Reading formula="A: transit ≤ SLA · B: leg cost = weight × tariff(mode) · C: cost_matrix = rate × km"
        soWhat="One lever per leg, in the group where the model actually consumes it: mode-booked legs answer to their mode's tariff, the final customer leg to its lane rate, and the SLA decides which modes are even admissible. Edit any of them and the chips pulse the solves that just went stale."/>
    </Card>
  );
}

// ── V5-4 · LgModeSplit — multi-mode split on capacity/deadline binds ─────────
// The per-lane pick above is all-or-nothing: one mode carries the whole lane. Two
// binds make that wrong: a lane heavier than every mode's max load used to come
// back rec=None and silently price the lane at ₹0; and a demand spike forced the
// ENTIRE shipment to air when only the consumption bridge needs to fly. Armed,
// transport.py may split a lane across modes (full bulk loads + remainder leg, or
// fast bridge + slow bulk) and reports each split with its saving vs the single
// pick. Toggle OFF ⇒ payload and solver output byte-identical to baseline.
function LgModeSplit({ tr }){
  const { config, setConfig } = useConfig();
  const on = !!config.modeSplitEnabled;
  const res = tr && tr.result;
  const active = !!(res && res.mode_split_active);
  const splits = active ? (res.shipments||[]).filter(s=>s.split) : [];
  const rescued = splits.filter(s=>s.split.single_cost==null);
  return (
    <StageSection step="1b" title="Multi-mode split" sub="one lane, several modes: when a lane outweighs every single mode (capacity bind) or a spike would force everything to air (deadline bind), the optimiser splits the load instead of failing or over-paying">
      <Card icon="🔀" title="Mode split on binds" span={2} badge={on?'armed — splits allowed':'off — one mode per lane'} badgeTone={on?'y':'k'}
        right={<Btn kind={on?'primary':'secondary'} sm onClick={()=>setConfig({ modeSplitEnabled: !on })}>{on?'⏻ disarm split':'⏻ arm mode split'}</Btn>}
        info={{ what:'All-or-nothing mode picks fail two ways: a lane heavier than every mode\'s max load is reported as UNSERVEABLE (and silently priced ₹0), and a demand spike flies the whole shipment when only the bridge quantity — slow-lane transit minus days-of-stock — needs air. Armed, the optimiser may split a lane across modes: n full bulk loads + a remainder leg, or a fast bridge + slow bulk, and only when the split beats the best single mode.', flows:'config.modeSplitEnabled → params.mode_split · buffer → split_bridge_buffer_pct → transport.py split plans → shipments[].split + split_saving.' }}
        dev={{ comp:'LgModeSplit', props:'config.modeSplitEnabled · config.splitBridgeBufferPct', note:'V5-4 — _capacity_split (bin-pack full loads + remainder) · _deadline_split (air bridge = (slow_t − DoS) × burn × (1+buffer)).' }}>
        <Grid cols={3} gap={10}>
          <GovField label="Bridge buffer" token="config" suffix="%" min={0} max={100} seed={15}
            value={config.splitBridgeBufferPct==null?'':config.splitBridgeBufferPct}
            onChange={v=>setConfig({ splitBridgeBufferPct: v })}
            hint="safety on the fast-lane bridge qty"
            why="The deadline split flies exactly the consumption gap (slow-lane days minus days-of-stock × daily burn) — this buffer over-sizes that bridge so a late vessel or a hot week doesn't reopen the stockout it just closed."
            formula="bridge_kg = (slow_days − DoS) × burn × (1 + buffer%)"/>
        </Grid>
        {on && (
          <div data-vis="v5-modesplit" style={{marginTop:10, border:`2px solid ${C.line}`, borderLeft:`5px solid ${splits.length?C.hl:C.gn}`, background:C.paper, padding:'9px 12px'}}>
            {!res ? (
              <span style={{fontFamily:F.mono, fontSize:10, color:C.tx3}}>armed — run transport to see split decisions</span>
            ) : !active ? (
              <span style={{fontFamily:F.mono, fontSize:10, color:C.tx3}}>armed after the last solve — re-run transport to allow splits</span>
            ) : (<>
              <div style={{fontFamily:F.mono, fontSize:9.5, fontWeight:800, letterSpacing:'.06em', color:C.tx2, marginBottom:6}}>
                MODE SPLITS — {splits.length?`${splits.length} lane(s) split`:'no binds: single-mode picks already optimal'}
                {res.split_saving>0?` · ₹${Math.round(res.split_saving).toLocaleString('en-IN')} saved vs single-mode`:''}
                {rescued.length?` · ${rescued.length} lane(s) rescued from UNSERVEABLE`:''}
              </div>
              {splits.length>0 && (
                <div style={{display:'flex', flexDirection:'column', gap:8}}>
                  {splits.map(s=>(
                    <div key={s.name} style={{border:`1.5px solid ${C.line2}`, padding:'5px 8px'}}>
                      <div style={{fontFamily:F.mono, fontSize:9.5, fontWeight:800}}>
                        {s.name} · {s.split.reason==='capacity'?'CAPACITY bind':'DEADLINE bind'}
                        {s.split.single_cost==null
                          ? <span style={{color:C.hl}}> · no single mode fits {s.weight_kg.toLocaleString('en-IN')} kg — split is the only plan</span>
                          : <span style={{color:C.gn}}> · saves ₹{Math.round(s.split.saving).toLocaleString('en-IN')} vs {s.recommended?s.recommended.label:'single mode'}</span>}
                      </div>
                      <div style={{fontFamily:F.mono, fontSize:9, color:C.tx2, marginTop:2}}>
                        {s.split.legs.map(l=>`${l.label}${l.loads>1?` ×${l.loads}`:''} — ${Math.round(l.weight_kg).toLocaleString('en-IN')} kg · ₹${Math.round(l.base_cost).toLocaleString('en-IN')} · ${l.total_days}d`).join('  +  ')}
                      </div>
                      {s.split.reason==='deadline' && s.split.bridge_kg!=null && (
                        <div style={{fontFamily:F.mono, fontSize:9, color:C.tx2}}>
                          bridge {Math.round(s.split.bridge_kg).toLocaleString('en-IN')} kg flies (lands before day {Math.round(s.days_of_stock)}); the rest rides the cheap lane{s.split.residual_stockout_cost>0?` · residual exposure ₹${Math.round(s.split.residual_stockout_cost).toLocaleString('en-IN')}`:''}
                        </div>)}
                    </div>
                  ))}
                </div>)}
              <Reading formula="split chosen only when Σ leg costs (+ residual stockout) < best single-mode total"
                soWhat={splits.length?'A bind is live — the split is the honest plan: the lane ships whole (or the bridge lands before the stockout) at the least cost that respects every mode\'s physical limits.':'No lane currently outweighs its modes and no spike forces a bridge — the toggle is a live guardrail; it will split first under surge or branch what-ifs.'}/>
            </>)}
          </div>)}
      </Card>
    </StageSection>
  );
}

// India map — projected lat/long, silhouette drawn in the SAME projection so
// nodes land correctly, with marker + label de-overlap so nothing stacks.
function IndiaMap({ marks, cog, flows }) {
  const W=480, H=440;
  const px = lng => (lng-66.5)/(98-66.5)*(W-150)+80;
  const py = lat => (37.5-lat)/(37.5-6)*(H-90)+40;
  // outline as real coordinates → projected, so it aligns with the nodes
  const OUTLINE=[[34.5,76],[32,78.5],[30,81],[27.3,88.2],[26,89.8],[24,91.8],[25.3,94.3],[22,91],
    [21.4,87.8],[19.2,85],[15.8,81.2],[13,80.3],[10,79.9],[8,77.5],[9.3,76.3],[13,74.6],[16,73.4],
    [19,72.8],[21,72.6],[22.6,69],[23.7,68],[24.7,71],[27,70.2],[30,73],[32.6,74.6],[34.5,76]];
  const outline = OUTLINE.map(([la,ln],i)=>(i?'L':'M')+px(ln).toFixed(0)+' '+py(la).toFixed(0)).join(' ')+' Z';
  // project nodes, then spread any markers closer than 18px
  const pts = marks.map(m=>({ id:m.id, type:m.type, x:px(m.lng), y:py(m.lat) }));
  for(let a=0;a<pts.length;a++) for(let b=a+1;b<pts.length;b++){
    const dx=pts[b].x-pts[a].x, dy=pts[b].y-pts[a].y, d=Math.hypot(dx,dy)||0.01;
    if(d<18){ const k=(18-d)/2, ux=dx/d, uy=dy/d; pts[a].x-=ux*k; pts[a].y-=uy*k; pts[b].x+=ux*k; pts[b].y+=uy*k; }
  }
  const byId = Object.fromEntries(pts.map(p=>[p.id,p]));
  // de-overlap labels vertically; flip side on the eastern half
  const sorted=[...pts].sort((a,b)=>a.y-b.y); let last=-100;
  sorted.forEach(p=>{ let ly=p.y+3; if(ly-last<15) ly=last+15; p.ly=ly; last=ly; p.left = p.x > W*0.58; });
  const colOf=t=> t==='plant'?C.dg:t==='customer'?C.a2:t==='supplier'?C.tx3:C.ink;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', maxWidth:W, height:'auto', display:'block', border:`2px solid ${C.line}`, background:C.paper}}>
      <path d={outline} fill={C.bg3} stroke={C.line2} strokeWidth="1.5"/>
      {flows && flows.map((f,i)=>{ const a=byId[f.from], b=byId[f.to]; if(!a||!b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={C.ink} strokeWidth={1+f.w*4} opacity=".4" strokeLinecap="round"/>;
      })}
      {pts.map((p,i)=>{ const lx = p.left ? p.x-12 : p.x+12;
        return (
          <g key={i}>
            <line x1={p.x} y1={p.y} x2={lx} y2={p.ly-3} stroke={C.line2} strokeWidth="1"/>
            <circle cx={p.x} cy={p.y} r={p.type==='plant'?6:4.5} fill={colOf(p.type)} stroke={C.paper} strokeWidth="1.6"/>
            <text x={lx} y={p.ly} textAnchor={p.left?'end':'start'} fontFamily={F.mono} fontSize="9" fontWeight="700"
              fill={C.tx} style={{paintOrder:'stroke'}} stroke={C.paper} strokeWidth="3" strokeLinejoin="round">{p.id}</text>
          </g>
        );
      })}
      {cog && (()=>{ const x=px(cog.lng), y=py(cog.lat);
        return <g>
          <circle cx={x} cy={y} r="10" fill="none" stroke={C.ac2} strokeWidth="2.5"/>
          <line x1={x-14} y1={y} x2={x+14} y2={y} stroke={C.ac2} strokeWidth="2"/>
          <line x1={x} y1={y-14} x2={x} y2={y+14} stroke={C.ac2} strokeWidth="2"/>
          <text x={x} y={y-18} textAnchor="middle" fontFamily={F.mono} fontSize="9" fontWeight="700" fill={C.ac2}
            style={{paintOrder:'stroke'}} stroke={C.paper} strokeWidth="3">CoG</text>
        </g>;
      })()}
    </svg>
  );
}

function LogAllocation({ tr }) {
  const r = tr && tr.result;
  // LG-1 — allocation matrix BUILT FROM THE SOLVE: each solved shipment is a lane that
  // picked ONE mode (the transport LP's choice); the matrix is lane × chosen-mode with
  // the cell = that lane's value share on its picked mode (100% — one mode per lane).
  // Falls back to the illustrative literal only before the first solve.
  const SEED_LANES=['CHN→BLR','CHN→PUN','PUN→GGN','BLR→GGN'];
  const SEED_MODES=['FTL','LTL','Rail','Air'];
  const SEED_ALLOC=[[100,0,0,0],[0,0,100,0],[0,60,0,40],[0,0,0,100]];
  let lanes=SEED_LANES, modes=SEED_MODES, alloc=SEED_ALLOC;
  if(r && (r.shipments||[]).length){
    lanes = r.shipments.map(s=>s.name);
    const modeOf = s=> (s.recommended && (s.recommended.label||s.recommended.mode)) || '—';
    modes = Array.from(new Set(r.shipments.map(modeOf)));
    alloc = r.shipments.map(s=> modes.map(m=> modeOf(s)===m ? 100 : 0));
  }
  // real flows from the solved shipments (line weight = value share)
  let flows=[{from:'WH-CHN',to:'DC-BLR',w:.8},{from:'WH-CHN',to:'DC-PUN',w:1},{from:'DC-PUN',to:'CUST-GGN',w:.6},{from:'DC-BLR',to:'CUST-GGN',w:.3}];
  if(r && (r.shipments||[]).length){
    const mxv = Math.max(...r.shipments.map(s=>Number(s.value)||0), 1);
    flows = r.shipments.map(s=>({ from:s.origin, to:s.destination, w: Math.max(.2, (Number(s.value)||0)/mxv) }));
  }
  // real freight KPIs from the solve: total cost, weighted avg cost/shipment, SLA proxy
  const totFreight = r ? r.total_cost : null;
  const avgCost = r && r.shipments.length ? r.total_cost / r.shipments.length : null;
  const onTime = r ? Math.round(1000 - r.shipments.filter(s=>s.recommended && s.recommended.transit_days > s.deadline_days).length/Math.max(r.shipments.length,1)*1000)/10 : null;
  // G-L1 — the optimised DC→customer assignment from transport.py's min-cost flow LP (now
  // fed origins/destinations/cost_matrix via transportPayload). Render the solver's chosen
  // routes + the saving over an even demand-spread across the same DC→customer lanes.
  const ra = r && r.allocation;
  const allocRows = (ra && ra.allocation) || null;
  const lpCost = ra && ra.total_cost;
  let evenCost = null;
  if(allocRows && allocRows.length){
    const nodeById={}; (M.nodes||[]).forEach(n=>nodeById[n.id]=n);
    const net = (typeof getNetwork==='function') ? getNetwork() : { lanes:M.lanes||[] };
    const custLanes = (net.lanes||[]).filter(l=>l.direction==='outbound' && nodeById[l.to] && nodeById[l.to].type==='customer');
    const fin = (M.products||[]).filter(p=>p.cat==='Finished');
    const totalUnits = Math.max(1, Math.round(fin.reduce((s,p)=> s + getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12, 0)));
    const destIds = [...new Set(custLanes.map(l=>l.to))];
    // even split: each customer's demand spread equally across the DCs that serve it
    evenCost = 0;
    destIds.forEach(d=>{ const serving = custLanes.filter(l=>l.to===d); const share = (totalUnits/destIds.length)/Math.max(serving.length,1);
      serving.forEach(l=> evenCost += share * ((Number(l.rate)||1)*(Number(l.km)||1))); });
    evenCost = Math.round(evenCost);
  }
  const allocSaving = (lpCost!=null && evenCost!=null) ? (evenCost - lpCost) : null;
  return (
    <Grid cols={2}>
      <Card icon="🗺️" title="Allocation Flow Map" badge={allocRows?'min-cost LP':'weighted lanes'} badgeTone={allocRows?'g':'y'} info={{ what:'DC→customer assignment as a network flow. With the allocation LP solved, the routes are the COST-OPTIMISED min-cost flow (which DC serves each customer), not an even demand-spread.', flows:'Allocation → carrier booking.' }}
        right={allocRows ? <Provenance kind="solved" asOf={tr.ranAt}/> : undefined}
        dev={{ comp:'AllocationFlowCard', props:'solve.transport.allocation', note:'G-L1 — origins/destinations/cost_matrix now fed; transport.py min-cost flow LP runs.' }}>
        <IndiaMap marks={M.nodes.filter(n=>n.type!=='supplier')} flows={flows}/>
        {allocRows ? (
          <div style={{marginTop:8, border:`2px solid ${C.line}`}}>
            <div style={{background:C.bg3, padding:'5px 9px', fontFamily:F.disp, fontWeight:800, fontSize:11}}>G-L1 · Optimised DC→customer assignment <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, fontWeight:400}}>min-cost flow · rate×km</span></div>
            <DataTable dense cols={['From (DC)','To (customer)','Units','Lane cost']} align={['left','left','right','right']}
              rows={allocRows.map(a=>[a.from, a.to, Math.round(a.quantity).toLocaleString('en-IN'), `₹${Math.round(a.total_cost).toLocaleString('en-IN')}`])}/>
            {allocSaving!=null && (
              <div style={{padding:'7px 9px', fontFamily:F.mono, fontSize:10, color:allocSaving>0?C.gn:C.tx2, borderTop:`1px solid ${C.line2}`}}>
                LP total ₹{Math.round(lpCost).toLocaleString('en-IN')} vs even-split ₹{evenCost.toLocaleString('en-IN')} — {allocSaving>0?`saves ₹${allocSaving.toLocaleString('en-IN')} by routing via the cheaper DC`:'even split was already optimal'}.
              </div>
            )}
          </div>
        ) : (
          <div style={{marginTop:6, fontFamily:F.mono, fontSize:9, color:C.tx3}}>Line weight = shipped volume · deterministic LP, not a simulation. <i>Run the solver to compute the min-cost DC→customer assignment.</i></div>
        )}
      </Card>
      <Card icon="🚛" title="Allocation Matrix" badge="lane × mode" info={{ what:'How shipments split across modes per lane.', flows:'From transport LP.' }}
        dev={{ comp:'TransportAllocationCard', props:'solve.transport.allocation' }}>
        <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
          <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
            <thead><tr style={{background:C.ink}}>
              <th style={{color:C.paper, textAlign:'left', padding:'6px 9px', fontSize:9}}>LANE ↓ / MODE →</th>
              {modes.map(m=><th key={m} style={{color:C.paper, textAlign:'center', padding:'6px 9px', fontSize:9}}>{m}</th>)}
            </tr></thead>
            <tbody>
              {alloc.map((row,ri)=>(
                <tr key={ri} style={{borderTop:`1px solid ${C.line2}`}}>
                  <td style={{padding:'6px 9px', fontWeight:700, background:C.bg3}}>{lanes[ri]}</td>
                  {row.map((v,ci)=>(
                    <td key={ci} className="num" style={{textAlign:'center', padding:'6px 9px', background: v===0?C.paper: v===100?C.ink:C.ac, color: v===100?C.ac: v===0?C.tx3:C.onAc, fontWeight:700}}>{v?`${v}%`:'·'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{marginTop:10}}>
          <KpiRow cols={3}>
            <Blk label="Total Freight" value={r?`₹ ${(totFreight/1e5).toFixed(2)} L`:'₹ 24.8 L'} sub={r?'solved':'planned'}/>
            <Blk label="Avg Cost/Shipment" value={r?`₹ ${Math.round(avgCost).toLocaleString('en-IN')}`:'₹ 1,420'} tone="c"/>
            <Blk label="On-time SLA" value={r?`${onTime}%`:'96.4%'} accent={C.gn}/>
          </KpiRow>
        </div>
        {r && <div style={{marginTop:8, fontFamily:F.mono, fontSize:10, color:C.tx2}}>Solver chose: {Object.entries(r.mode_summary).map(([m,v])=>`${v.count}× ${v.label}`).join(' · ')} over {r.n_shipments} outbound shipments.</div>}
        <LogSkuFlows/>
        <Reading formula="mode choice: per lane min cost over modes s.t. transit ≤ deadline · total = Σ chosen-mode cost.  DC→customer allocation (G-L1): min-cost transportation LP — min Σ cost_matrix[i,j]·x[i,j] s.t. Σ_j x ≤ supply_i, Σ_i x ≥ demand_j" soWhat={r?`Mode mix minimises freight at ₹${(totFreight/1e5).toFixed(2)}L; and the DC→customer split is now the COST-OPTIMISED min-cost flow (the solver routes each customer via its cheapest DC subject to supply), not an even demand-spread — see the assignment table above.`:"Rail wins CHN→PUN on cost; Air only survives on BLR→GGN where the SLA forces speed. Run the solver to compute the optimised DC→customer assignment."}/>
      </Card>
    </Grid>
  );
}

// LG-2 — per-SKU outbound flow breakdown with REAL per-SKU shipping weights (kg/unit,
// from store skuWeightKg), replacing the old flat 3 kg/unit even-split. Each finished
// SKU's monthly flow (committed demand) × its own mass → mix-accurate tonnage, so the
// lane weight the transport solver prices reflects the actual product mix.
function LogSkuFlows(){
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const rows = fin.map(p=>{ const monthly = getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12;
    const w = (typeof skuWeightKg==='function') ? skuWeightKg(p.sku) : 3;
    return { sku:p.sku, monthly, w, kg:monthly*w }; }).sort((a,b)=>b.kg-a.kg);
  const totKg = rows.reduce((s,r)=>s+r.kg,0) || 1;
  const fmt = n=>Math.round(n).toLocaleString('en-IN');
  return (
    <div style={{marginTop:10, border:`2px solid ${C.line}`}}>
      <div style={{background:C.bg3, padding:'5px 9px', fontFamily:F.disp, fontWeight:800, fontSize:11}}>LG-2 · Per-SKU outbound flow <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, fontWeight:400}}>real kg/unit · {fmt(totKg)} kg/mo total</span></div>
      <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10}}>
        <thead><tr style={{background:C.ink}}>
          {['SKU','units/mo','kg/unit','kg/mo','mix %'].map((h,i)=><th key={i} style={{color:C.paper, textAlign:i?'right':'left', padding:'4px 9px', fontSize:8.5}}>{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((r,i)=>(
            <tr key={i} style={{borderTop:`1px solid ${C.line2}`, background:i%2?C.bg3:C.paper}}>
              <td style={{padding:'3px 9px', fontWeight:700}}>{r.sku}</td>
              <td style={{padding:'3px 9px', textAlign:'right', color:C.tx2}}>{fmt(r.monthly)}</td>
              <td style={{padding:'3px 9px', textAlign:'right', color:C.tx3}}>{r.w.toFixed(1)}</td>
              <td style={{padding:'3px 9px', textAlign:'right', fontWeight:700}}>{fmt(r.kg)}</td>
              <td style={{padding:'3px 9px', textAlign:'right', color: r.kg/totKg>0.25?C.gn:C.tx3}}>{((r.kg/totKg)*100).toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogConsolidation({ tr }) {
  const r = tr && tr.result;
  const cons = r ? (r.consolidation||[]) : null;
  const best = cons && cons.length ? cons[0] : null;       // already sorted by saving desc
  const recs = cons ? cons.filter(c=>c.recommend_consolidate) : null;
  return (
    <Card icon="📦" title="Consolidation Plan" badge={r?(recs.length?`${recs.length} lanes`:'none beat FTL'):'LTL→FTL'} badgeTone="y"
      right={r ? <Provenance kind="solved" asOf={tr.ranAt}/> : undefined}
      info={{ what:'Where merging shipments cuts unit cost.', flows:'Plan → carrier booking.' }}
      dev={{ comp:'ConsolidationCard', props:'solve.transport.consol' }}>
      <Grid cols={3}>
        <Blk label="Consolidation saving" value={r?`₹ ${(r.consolidation_saving/1e5).toFixed(2)} L`:'₹ 3.2 L/yr'} tone="y"/>
        <Blk label="Unit cost cut" value={best&&best.cost_individual?`−${Math.round((best.saving/best.cost_individual)*100)}%`:'−22%'} accent={C.gn}/>
        <Blk label="Best-lane util" value={best?`${best.utilization_pct}%`:'+0.5 d'} accent={C.a4}/>
      </Grid>
      {r ? (
        recs.length ? (
          <div style={{marginTop:10, fontFamily:F.mono, fontSize:10.5, color:C.tx2, lineHeight:1.7}}>
            {recs.map((c,i)=><div key={i}>{c.lane}: merge {c.n_shipments}×{c.individual_mode} → {c.consolidated_mode} · saves ₹{(c.saving/1000).toFixed(0)}K</div>)}
          </div>
        ) : (
          <div style={{marginTop:10, padding:'9px 11px', border:`2px solid ${C.line2}`, background:C.bg3, fontFamily:F.mono, fontSize:10.5, color:C.tx2}}>
            No outbound lane's combined weight clears a full-truckload at current volumes{best?` — best is ${best.lane} at ${best.utilization_pct}% truck utilisation`:''}. Keep individual {best?best.individual_mode:'LTL'} bookings.
          </div>
        )
      ) : (
        <>
          <div style={{marginTop:10, display:'flex', alignItems:'center', gap:10}}>
            <div style={{display:'flex', alignItems:'center', gap:4}}>
              {[1,2,3].map(i=><span key={i} style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'4px 7px', border:`2px solid ${C.line2}`, background:C.bg3}}>LTL</span>)}
            </div>
            <span style={{color:C.tx3, fontSize:16}}>→</span>
            <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'4px 9px', border:`2px solid ${C.line}`, background:C.ac, color:C.onAc}}>1 × FTL</span>
            <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>Merge 3 weekly LTL CHN→PUN into one FTL.</span>
          </div>
          <Reading formula="consolidate when FTL_cost < Σ LTL_cost AND transit penalty ≤ SLA slack"
            soWhat="The three CHN→PUN LTLs share a destination and have 0.5d of SLA slack — collapse them."/>
        </>
      )}
    </Card>
  );
}

// Center of gravity — the closed-form weighted centroid x*=Σwᵢxᵢ/Σwᵢ over the
// delivery-side nodes (DCs + customers), weighted by node capacity (throughput
// proxy; customers get the total monthly FG flow). A real derivation, not the
// mock — no backend endpoint exists for it (it's a formula, not an optimisation).
function computeCoG(){
  const net = getNetwork();
  const M = window.M || {};
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const monthly = fin.reduce((s,p)=>s + getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12, 0);
  const dest = (net.nodes||[]).filter(n=>n.type==='dc' || n.type==='customer');
  let sw=0, sx=0, sy=0;
  dest.forEach(n=>{ const w = n.type==='customer' ? Math.max(monthly, 1) : (n.capacity||1);
    sw+=w; sx+=w*n.lng; sy+=w*n.lat; });
  if(!sw) return { lat:M.cog.lat, lng:M.cog.lng, label:M.cog.label, nodes:0, mock:true };
  const lat=+(sy/sw).toFixed(2), lng=+(sx/sw).toFixed(2);
  // nearest known city label for the computed point
  const cities=[['Kurnool',15.83,78.04],['Hyderabad',17.39,78.49],['Bengaluru',12.97,77.59],['Nagpur',21.15,79.09],['Solapur',17.66,75.91],['Hubli',15.36,75.12]];
  let best=cities[0], bd=1e9;
  cities.forEach(([nm,la,ln])=>{ const d=(la-lat)**2+(ln-lng)**2; if(d<bd){bd=d;best=[nm,la,ln];} });
  return { lat, lng, label:`Optimal hub ~ ${best[0]} (weighted centroid)`, nodes:dest.length, mock:false };
}
function LogCoG() {
  const cog = computeCoG();
  return (
    <Grid cols={2}>
      <Card icon="📍" title="Center of Gravity" badge={cog.mock?'optimal hub':`${cog.nodes} demand nodes`} badgeTone="y" info={{ what:'Weighted-distance optimal facility location.', flows:'Hub candidate → network design.' }}
        dev={{ comp:'CenterOfGravityCard', props:'nodes, demandWeights', note:'Config + result as one.' }}>
        <IndiaMap marks={M.nodes.filter(n=>n.type!=='supplier')} cog={cog}/>
      </Card>
      <Card icon="🎯" title="CoG Result" badge={cog.mock?'vs current':'derived'} badgeTone={cog.mock?undefined:'g'}
        right={cog.mock ? <Provenance kind="seed"/> : <Provenance kind="derived" asOf={new Date()}/>}
        info={{ what:'Recommended hub coordinates and savings.', flows:'Decision input for new DC.' }}
        dev={{ comp:'CoGResult', props:'cog (computed)' }}>
        <Blk label="Optimal Location" value={cog.label} tone="y"/>
        <div style={{marginTop:8}}><KpiRow cols={2}>
          <Blk label="Latitude" value={`${cog.lat}°N`}/>
          <Blk label="Longitude" value={`${cog.lng}°E`}/>
        </KpiRow></div>
        <div style={{marginTop:10, padding:'10px 11px', background:C.gn, color:'#fff', fontFamily:F.disp, fontWeight:800, fontSize:14}}>{cog.mock?M.cog.saving:`Centroid of ${cog.nodes} delivery nodes, demand-weighted`}</div>
        <Reading formula="x* = Σ(wᵢxᵢ)/Σwᵢ ,  y* = Σ(wᵢyᵢ)/Σwᵢ   (wᵢ = demand)"
          soWhat={cog.mock?"A Kurnool hub cuts average outbound km ~18% and relieves the DC-BLR cube pressure flagged on Network.":`Live centroid of the DC + customer nodes, weighted by throughput — recompute it whenever Network topology or the demand forecast changes.`}/>
      </Card>
    </Grid>
  );
}
window.StageLogistics = StageLogistics;
