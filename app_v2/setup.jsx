// ════════════════════════════════════════════════════════════════════════
// setup.jsx — Setup (stage 01). Declutter per handoff v2 §3.01:
// identity + calendar ONLY, 0 sub-tabs. WACC/CAC/Budget → Finance;
// locations/on-hand/transport → Network. MSME is a single DERIVED badge.
// ════════════════════════════════════════════════════════════════════════
function StageSetup({ onNav }) {
  return (
    <div>
      <StageHeader n="01" title="Setup · Identity & Calendar"
        kicker="Just two things: who you are, and the clock everything plans against. WACC/CAC live in Finance; nodes/on-hand in Network."
        right={<ModelIO label="Import JSON"/>}/>
      <div style={{padding:18}}>
        <SetupIdentity onNav={onNav}/>
        <SetupTemplates onNav={onNav}/>
        <SetupProfile/>
        <SetupCalendar/>
        <SetupRegistry onNav={onNav}/>
      </div>
    </div>
  );
}

function SetupIdentity({ onNav }) {
  const { config, setConfig } = useConfig();
  const usd = config.fxRates.USD;
  return (
    <StageSection step="1" title="Company Identity" sub="legal entity · currency · tax regime · service level — the MSME tier is derived, not chosen">
      <Grid cols={3}>
        <Card icon="🏢" title="Company" badge="GST · REG" span={2}
          info={{ what:'Legal identity, currency, tax regime, service level.', flows:'Tax rate → Finance; service level → safety stock.' }}
          dev={{ comp:'SetupTab', props:'useConfig()', state:'config.companyName, config.currency, config.taxRate, config.serviceLevel' }}>
          {/* big editable name title — bound to real state (config.companyName) */}
          <div style={{marginBottom:6, fontFamily:F.mono, fontSize:9, letterSpacing:'.1em', color:C.tx3}}>COMPANY NAME</div>
          <input value={config.companyName} onChange={(e)=>setConfig({companyName:e.target.value})} style={{
            width:'100%', border:`2px solid ${C.line}`, background:C.paper, color:C.ink,
            fontFamily:F.disp, fontWeight:900, fontSize:22, letterSpacing:'-.5px', padding:'8px 12px', outline:'none',
          }}/>
          <div style={{marginTop:14, display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
            <Field label="Base Currency" hint={`USD @ ₹${usd} · FX as of ${config.fxAsOf.split('·')[0].trim()} — edit in Finance`}>
              <Select value={config.currency} onChange={(v)=>setConfig({currency:v, currencyName:{'₹':'INR','$':'USD','€':'EUR'}[v]||'INR'})}
                options={[{value:'₹',label:`₹ INR · ₹${usd}/$`},{value:'$',label:'$ USD'},{value:'€',label:'€ EUR'}]}/>
            </Field>
            <Field label="Plant State"><Select value={config.plantState}
              onChange={(v)=>setConfig({plantState:v})}
              options={[{value:'TN',label:'Tamil Nadu'},{value:'MH',label:'Maharashtra'},{value:'GJ',label:'Gujarat'},{value:'KA',label:'Karnataka'}]}/></Field>
            <Field label="Effective Tax"><NumInput value={config.taxRate} suffix="%" onChange={(v)=>setConfig({taxRate:v})}/></Field>
            <Field label="Service Level"><NumInput value={(config.serviceLevel*100).toFixed(1)} suffix="% z=1.645"
              onChange={(v)=>setConfig({serviceLevel:(Number(v)||0)/100})}/></Field>
          </div>
          <div style={{marginTop:12, display:'flex', alignItems:'center', gap:14}}>
            <Field label="GST Registered"><div style={{display:'flex', border:`2px solid ${C.line}`, width:120}}>
              {['ON','OFF'].map((o,i)=>{ const on=config.gstRegistered===(o==='ON');
                return <div key={o} onClick={()=>setConfig({gstRegistered:o==='ON'})} style={{flex:1, textAlign:'center', padding:'5px 0', fontFamily:F.mono, fontSize:10, fontWeight:700, background:on?C.ink:C.paper, color:on?C.ac:C.tx3, borderRight:o==='ON'?`2px solid ${C.line}`:'none', cursor:'pointer'}}>{o}</div>; })}
            </div></Field>
            <Field label="CIN" hint="corporate identity number — your registry of record">
              <TextInput value={config.cin!=null?config.cin:M.cin} onChange={(v)=>setConfig({cin:v})} w={220}/>
            </Field>
            <div style={{display:'flex', gap:6, flexWrap:'wrap', alignSelf:'flex-end', paddingBottom:4}}>
              {config.gstRegistered && <Tag c="k">GST · ITC RECOVERABLE</Tag>}
            </div>
          </div>
        </Card>

        <Card icon="🏷️" title="MSME Tier" badge="DERIVED" badgeTone="y"
          info={{ what:'Tier auto-computed from turnover + investment per the MSMED Act — including the case where a firm is too large to be an MSME at all.', flows:'If MSME: 43B(h) 45-day rule → Sourcing & Finance. If not: standard credit terms.' }}
          dev={{ comp:'MSMEBadge', props:'msmeTier(config.investmentCr, config.annualTurnoverCr)', note:'No selector — derived live from the two figures; non-MSME (large) is a valid outcome.' }}
          right={<Provenance kind="derived"/>}>
          {(()=>{
            const { tier, isMsme, band } = msmeTier(config.investmentCr, config.annualTurnoverCr);
            return (<>
              <Grid cols={1} gap={8}>
                <Field label="Plant & Machinery" hint="your figure · also sourced from Finance · Asset Register">
                  <NumInput value={config.investmentCr} prefix="₹" suffix="Cr" onChange={(v)=>setConfig({investmentCr:v})}/></Field>
                <Field label="Annual Turnover" hint="your figure · also sourced from Finance · actuals">
                  <NumInput value={config.annualTurnoverCr} prefix="₹" suffix="Cr" onChange={(v)=>setConfig({annualTurnoverCr:v})}/></Field>
              </Grid>
              <div style={{marginTop:12, padding:'14px', textAlign:'center', background: isMsme?C.ink:C.bg4, color: isMsme?C.paper:C.tx, border: isMsme?'none':`2px solid ${C.line}`}}>
                <div style={{fontFamily:F.disp, fontSize:26, fontWeight:900, color: isMsme?C.ac:C.tx, letterSpacing:'.04em'}}>{tier}</div>
                <div style={{fontFamily:F.mono, fontSize:9, marginTop:4, opacity:.85}}>{band}</div>
              </div>
              <Reading formula="tier = f(investment, turnover) per MSMED Act 2020 — Micro / Small / Medium, else not an MSME"
                soWhat={isMsme
                  ? '43B(h): MSME suppliers must be paid within 45 days or the spend is tax-disallowed — Sourcing flags at-risk payables.'
                  : 'This firm exceeds the MSME ceiling, so 43B(h) does not apply — standard negotiated credit terms govern payables.'}/>
            </>);
          })()}
        </Card>
      </Grid>
    </StageSection>
  );
}

// ── D4 · INDUSTRY TEMPLATE LOADER (differentiation track) ────────────────────
// Time-to-value / low-TCO wedge: incumbents need a 6-month consulting build to
// stand up a usable model. A planner here picks an industry archetype and starts
// from TUNED defaults instead of a blank slate. HONESTY: a preset retunes the
// planning PARAMETERS that solvers actually consume (service level → safety stock
// & CVaR; freeze/slush horizon → re-plan nervousness; profile → which engines the
// spine shows) and flags the modules that matter for that industry. It does NOT
// fabricate a dataset — your own products/BOM/network stay exactly as entered;
// the native dataset here is automotive, so CPG/pharma reshape the knobs, not the
// data. Every value below is written straight into the live config/planning/profile
// slices the rest of the app reads — nothing cosmetic, nothing faked.
const INDUSTRY_TEMPLATES = [
  { id:'auto', name:'Automotive · discrete JIT', icon:'🚗', native:true,
    tag:'native fit for this dataset',
    blurb:'Tight-capacity, multi-line discrete manufacturing on a JIT inbound. Sequencing & changeover dominate; supplier consolidation cuts inbound freight.',
    cfg:{ serviceLevel:0.95 },
    plan:{ timeGrain:'week', frozenWeeks:4, slushyWeeks:12, horizonLength:52 },
    profile:{ makePolicy:'MTS+MTO', capacity:'tight', imports:true, lines:'many', distribution:'network', externalForecast:false },
    emphasis:[ ['console','Line-capacity shadow price'], ['production','Sequencing & changeover'], ['sourcing','JIT supplier consolidation'] ],
    audit:'standard' },
  { id:'cpg', name:'CPG / FMCG · high-velocity', icon:'🛒',
    tag:'promo-driven · short freeze',
    blurb:'Fast-moving, promo-driven demand with a short responsive freeze. Forecast accuracy and service-vs-inventory are the battleground; sensing reacts to in-week swings.',
    cfg:{ serviceLevel:0.98 },
    plan:{ timeGrain:'week', frozenWeeks:2, slushyWeeks:8, horizonLength:52 },
    profile:{ makePolicy:'MTS+MTO', capacity:'tight', imports:false, lines:'many', distribution:'network', externalForecast:false },
    emphasis:[ ['demand','Promo-uplift forecast + sensing'], ['sourcing','Safety stock vs service'], ['scenarios','Live control tower'] ],
    audit:'standard' },
  { id:'pharma', name:'Pharma · regulated batch', icon:'💊',
    tag:'audit trail bundled · 99% service',
    blurb:'Regulated, expiry-critical batch production with imported APIs. Long freeze for compliance, very high service, and a full audit trail of every plan change.',
    cfg:{ serviceLevel:0.99 },
    plan:{ timeGrain:'week', frozenWeeks:8, slushyWeeks:16, horizonLength:52 },
    profile:{ makePolicy:'MTS+MTO', capacity:'tight', imports:true, lines:'many', distribution:'network', externalForecast:false },
    emphasis:[ ['scenarios','Audit trail & version replay'], ['demand','Very-high (99%) service'], ['sourcing','Cold-chain carry & expiry'] ],
    audit:'bundled' },
];

function SetupTemplates({ onNav }) {
  const { config, setConfig } = useConfig();
  const { setPlanning } = usePlanning();
  const { setProfile } = useProfile();
  const active = config.industryProfile || null;
  const apply = (t)=>{
    setConfig({ serviceLevel:t.cfg.serviceLevel, industryProfile:t.id });
    setPlanning({ timeGrain:t.plan.timeGrain, frozenWeeks:t.plan.frozenWeeks, slushyWeeks:t.plan.slushyWeeks, horizonLength:t.plan.horizonLength });
    setProfile(t.profile);
    if(typeof logEvent==='function') logEvent('template_apply', t.id, { name:t.name, serviceLevel:t.cfg.serviceLevel, freeze:t.plan.frozenWeeks });
  };
  return (
    <StageSection step="★" title="Industry Quick-Start" sub="pick an archetype to start from tuned planning defaults instead of a blank model — your data stays, the knobs retune">
      <Card icon="🏭" title="Industry Templates" badge={active?`active: ${active}`:'choose a preset'} badgeTone={active?'g':'y'} span={3}
        info={{ what:'Each preset writes industry-tuned defaults into the live config, planning horizon and planning profile — the knobs solvers actually consume.', flows:'service level → safety stock & CVaR · freeze/slush → re-plan nervousness · profile → which engines the spine shows.' }}
        dev={{ comp:'SetupTemplates (D4)', props:'useConfig/usePlanning/useProfile', state:'config.industryProfile + tuned config/planning/profile patches' }}
        right={<Provenance kind="input"/>}>
        <div style={{padding:'8px 11px', marginBottom:12, border:`2px dashed ${C.a2}`, background:C.bg2, fontFamily:F.mono, fontSize:9.5, color:C.tx2, lineHeight:1.55}}>
          ⓘ A preset <b>retunes planning defaults &amp; highlights the right modules</b> — it does <b>not</b> generate synthetic data. Your products, BOM and network are untouched; the seeded dataset is automotive, so CPG/pharma reshape the parameters, not the data. Tweak anything afterwards in Setup, Demand or the Profile card below.
        </div>
        <Grid cols={3} gap={12}>
          {INDUSTRY_TEMPLATES.map(t=>{ const on=active===t.id; return (
            <div key={t.id} style={{border:`2px solid ${on?C.gn:C.line2}`, background:on?C.bg2:C.bg3, padding:'12px 13px', display:'flex', flexDirection:'column', gap:8}}>
              <div style={{display:'flex', alignItems:'center', gap:8}}>
                <span style={{fontSize:18}}>{t.icon}</span>
                <div style={{minWidth:0}}>
                  <div style={{fontFamily:F.disp, fontWeight:900, fontSize:12.5, color:C.tx}}>{t.name}</div>
                  <div style={{fontFamily:F.mono, fontSize:8.5, color:on?C.gn:C.tx3, letterSpacing:'.04em'}}>{on?'● ACTIVE':t.tag}{t.native&&!on?' · ◆ native':''}</div>
                </div>
              </div>
              <div style={{fontFamily:F.body, fontSize:11, color:C.tx2, lineHeight:1.45}}>{t.blurb}</div>
              <div style={{display:'flex', flexWrap:'wrap', gap:5, fontFamily:F.mono, fontSize:8.5}}>
                <Tag c="k">{(t.cfg.serviceLevel*100).toFixed(0)}% service</Tag>
                <Tag c="k">{t.plan.frozenWeeks}w freeze</Tag>
                <Tag c="k">{t.plan.timeGrain}ly</Tag>
                {t.audit==='bundled' && <Tag c="g">audit trail</Tag>}
              </div>
              <div style={{borderTop:`1px dotted ${C.line2}`, paddingTop:7, marginTop:'auto'}}>
                <div style={{fontFamily:F.mono, fontSize:8, color:C.tx3, letterSpacing:'.08em', marginBottom:5}}>EMPHASISES</div>
                <div style={{display:'flex', flexDirection:'column', gap:3}}>
                  {t.emphasis.map(([go,lbl],i)=>(
                    <button key={i} onClick={()=>onNav&&onNav(go)} style={{textAlign:'left', background:'transparent', border:'none', cursor:'pointer', fontFamily:F.mono, fontSize:10, color:C.a2, padding:0, textDecoration:'underline'}}>→ {lbl}</button>
                  ))}
                </div>
              </div>
              <Btn kind={on?'secondary':'accent'} sm onClick={()=>apply(t)} style={{justifyContent:'center', marginTop:4}}>
                {on?'✓ Applied — re-apply':'Apply preset →'}
              </Btn>
            </div>
          ); })}
        </Grid>
        {active && (()=>{ const t=INDUSTRY_TEMPLATES.find(x=>x.id===active); return t?(
          <Reading formula={`preset → serviceLevel ${(t.cfg.serviceLevel*100).toFixed(0)}% · freeze ${t.plan.frozenWeeks}w / slush ${t.plan.slushyWeeks}w · ${t.plan.timeGrain}ly · profile retuned`}
            soWhat={`These are now the live defaults every solver reads. ${t.audit==='bundled'?'The audit trail (every plan change logged + version replay) is the pharma compliance differentiator — see Scenarios → Versions.':'Re-solve any stage to plan against the tuned numbers.'} Override anything below or in Demand/Sourcing.`}/>
        ):null; })()}
      </Card>
    </StageSection>
  );
}

// horizonRange(planning): the date window the horizon ACTUALLY spans, computed live
// from startDate + horizonLength × grain — so the banner follows the user's input
// (the review's "I set 52 but the banner is stuck on the seed periods" bug). Returns
// formatted start/end labels; pure date math, no seed period array.
function horizonRange(planning){
  const fmt = (d)=>d.toLocaleDateString(undefined,{day:'2-digit',month:'short',year:'numeric'});
  const start = new Date(planning.startDate || '2026-06-01');
  if(isNaN(start.getTime())) return { start:'—', end:'—', days:0 };
  const n = Math.max(1, Number(planning.horizonLength)||1);
  const end = new Date(start);
  if(planning.timeGrain==='day')        end.setDate(start.getDate() + (n-1));
  else if(planning.timeGrain==='month'){ end.setMonth(start.getMonth() + n); end.setDate(end.getDate()-1); }
  else                                   end.setDate(start.getDate() + (n*7 - 1));   // week (default)
  const days = Math.round((end - start)/86400000) + 1;
  return { start:fmt(start), end:fmt(end), days };
}

function SetupCalendar() {
  const { config, setConfig } = useConfig();
  const { planning, setPlanning } = usePlanning();
  const { calendar, setCalendar } = useCalendar();
  const grain = planning.timeGrain;
  const customHolidays = config.customHolidays || [];
  // start_month is 0-indexed (Jan=0); derive from the YYYY-MM-DD start date.
  const startD = new Date(planning.startDate);
  const cal = useSolve('/api/calc/calendar', ()=>({
    work_days_per_week: planning.workDaysPerWeek,
    indian_holidays: planning.indianHolidays,
    start_month: startD.getMonth(),
    year: startD.getFullYear(),
    state: config.plantState,                                            // selector now drives the gazette
    custom_holidays: customHolidays.map(h=>[h.month, h.day, h.name]),     // per-day add/remove
  }));
  // G-D4 — unify the calendar source: keep M.calendar.start in lock-step with the governed
  // planning.startDate (the seed M.calendar.start was static and drifted). Every reader of
  // M.calendar.start (forecast/promo/actuals labels, solver horizon_start_date) now tracks Setup.
  const recompute = async ()=>{
    try{ if(window.M){ M.calendar = { ...(M.calendar||{}), start: planning.startDate,
        grain: planning.timeGrain, count: Number(planning.horizonLength)||52 }; } }catch(e){}
    try{ const r=await cal.run(); setCalendar({ result:r, computedAt:new Date().toISOString() }); }catch(e){}
  };
  // auto-compute once on load and whenever an input that changes the calendar moves —
  // so the card is never silently showing stale seed and the plant-state selector is live.
  React.useEffect(()=>{ recompute(); /* eslint-disable-next-line */ },
    [config.plantState, planning.workDaysPerWeek, planning.startDate, planning.indianHolidays, customHolidays.length]);
  // live totals from the last /api/calc/calendar run (fall back to seed display)
  const res = calendar.result;
  const yr = startD.getFullYear();
  const daysInYear = (yr%4===0 && (yr%100!==0||yr%400===0)) ? 366 : 365;
  const workdays = res ? res.total_working_days : 270;
  const holidays = res ? res.total_holidays : 22;
  const weekoff  = res ? Math.max(0, daysInYear - workdays - holidays) : 73;
  const tot = workdays + holidays + weekoff || 1;
  const hr = horizonRange(planning);
  const stateName = {TN:'Tamil Nadu',MH:'Maharashtra',GJ:'Gujarat',KA:'Karnataka'}[config.plantState] || config.plantState;
  // add-holiday local form state
  const [nd, setNd] = React.useState(''); const [nn, setNn] = React.useState('');
  const addHoliday = ()=>{ if(!nd) return; const d=new Date(nd); if(isNaN(d.getTime())) return;
    const rec = { month:d.getMonth()+1, day:d.getDate(), name:nn||'Custom holiday', date:nd };
    const dup = customHolidays.some(h=>h.month===rec.month && h.day===rec.day);
    if(!dup){ setConfigCustom([...customHolidays, rec]); }
    setNd(''); setNn(''); };
  const setConfigCustom = (arr)=>{ setConfig({ customHolidays: arr });
    if(typeof logEvent==='function') logEvent('override', 'calendar', { fields:['customHolidays'], to:{ count:arr.length } }); };
  const removeHoliday = (i)=> setConfigCustom(customHolidays.filter((_,j)=>j!==i));
  const isCustom = (m,d)=> customHolidays.some(h=>h.month===m && h.day===d);
  return (
    <StageSection step="3" title="Planning Calendar" sub="the one clock the whole app renders against — grain + horizon drive every period axis">
      <Grid cols={3}>
        <Card icon="📅" title="Grain & Horizon" badge={`${planning.horizonLength} buckets`}
          info={{ what:'Grain (day/week/month) + horizon define the single period axis app-wide.', flows:'Axis → every solver, forecast, MPS, contract.' }}
          dev={{ comp:'CalendarCard', props:'usePlanning()', state:'planning.{timeGrain,horizonLength,startDate,workDaysPerWeek}' }}>
          <Field label="Time Grain">
            <div style={{display:'flex', border:`2px solid ${C.line}`}}>
              {['day','week','month'].map((g,i)=>(
                <div key={g} onClick={()=>setPlanning({timeGrain:g})} style={{flex:1, textAlign:'center', padding:'7px 0', fontFamily:F.disp, fontSize:11, fontWeight:800, textTransform:'uppercase', cursor:'pointer',
                  background:g===grain?C.ac:C.paper, color:g===grain?C.onAc:C.tx, borderRight:i<2?`2px solid ${C.line}`:'none'}}>{g}</div>
              ))}
            </div>
          </Field>
          <div style={{marginTop:10, display:'grid', gridTemplateColumns:'1fr 1fr', gap:10}}>
            <Field label="Horizon"><NumInput value={planning.horizonLength} suffix={grain+'s'} onChange={(v)=>setPlanning({horizonLength:v})}/></Field>
            <Field label="Start Date" hint="pick a date — drives every period axis">
              <input type="date" value={planning.startDate} onChange={(e)=>setPlanning({startDate:e.target.value})} style={{
                border:`2px solid ${C.line}`, background:C.paper, color:C.tx, fontFamily:F.disp, fontWeight:600,
                fontSize:13, padding:'5px 8px', height:30, width:'100%', outline:'none'}}/>
            </Field>
            <Field label="Work Days / Wk"><NumInput value={planning.workDaysPerWeek} onChange={(v)=>setPlanning({workDaysPerWeek:v})}/></Field>
            <Field label="Net Hrs / Shift" hint="productive hours/shift after breaks — drives machine-hours (Production)"><NumInput value={planning.hrsPerShift} suffix="h" onChange={(v)=>setPlanning({hrsPerShift:v})}/></Field>
            <Field label="Frozen Wks" hint="no-change fence"><NumInput value={planning.frozenWeeks} suffix="w" onChange={(v)=>setPlanning({frozenWeeks:v})}/></Field>
            <Field label="Slushy Wks" hint="change-with-approval"><NumInput value={planning.slushyWeeks} suffix="w" onChange={(v)=>setPlanning({slushyWeeks:v})}/></Field>
            <Field label="Schedule Fence" hint="MILP weeks — production/procurement/risk basis"><NumInput value={planning.productionScheduleWeeks} suffix="w" onChange={(v)=>setPlanning({productionScheduleWeeks:v})}/></Field>
          </div>
          <div style={{marginTop:12, padding:'9px 11px', background:C.ac, color:C.onAc, fontFamily:F.mono, fontSize:10, fontWeight:600, lineHeight:1.5}}>
            ◆ Planning {planning.horizonLength} {grain}ly buckets · {hr.start} → {hr.end} ({hr.days} days) · {config.currency} · {(config.serviceLevel*100).toFixed(0)}% service.
          </div>
          <div style={{marginTop:8, padding:'7px 10px', border:`2px dashed ${C.a2}`, fontFamily:F.mono, fontSize:9, color:C.tx2, lineHeight:1.5}}>
            ⛓ HORIZON CONTRACT — this is the governing horizon; each solver runs its own declared basis off it: production · procurement · risk on the {planning.productionScheduleWeeks}w schedule fence ↑ · forecast on its grain (30d/13w/12mo) · S&OP aggregate monthly. Grain/count/start re-axis every solver; the schedule fence sizes the MILP.
          </div>
        </Card>

        <Card icon="📆" title={`${config.plantState} · ${stateName} Holidays ${yr}`} badge={String(holidays)}
          info={{ what:'Gazetted + regional state holidays removed from available workdays; you can add your own.', flows:'Net workdays → capacity calc.' }}
          dev={{ comp:'HolidayEditor', props:'useSolve(/api/calc/calendar)', state:'calendar.result.holiday_list + config.customHolidays' }} span={2}
          right={<div style={{display:'flex', alignItems:'center', gap:8}}>
            {res && <Provenance kind="solved" run="calendar.py" asOf={calendar.computedAt ? new Date(calendar.computedAt).toLocaleTimeString() : undefined}/>}
            <Btn kind="secondary" onClick={recompute}>{cal.solving?'computing…':'↻ Recompute'}</Btn>
          </div>}>
          {cal.error && <div style={{marginBottom:10, padding:'7px 10px', border:`2px solid ${C.dg}`, color:C.dg, fontFamily:F.mono, fontSize:10}}>⚠ {cal.error}</div>}
          {!res && !cal.solving && <div style={{marginBottom:10, padding:'7px 10px', border:`2px dashed ${C.line2}`, fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>showing seed figures — computing from the real engine…</div>}
          {/* add-a-holiday row — the per-day editor the review asked for */}
          <div style={{display:'flex', alignItems:'flex-end', gap:8, marginBottom:10, flexWrap:'wrap', padding:'8px 10px', border:`2px dashed ${C.line2}`, background:C.bg3}}>
            <Field label="Add holiday — date">
              <input type="date" value={nd} onChange={(e)=>setNd(e.target.value)} style={{border:`2px solid ${C.line}`, background:C.paper, color:C.tx, fontFamily:F.disp, fontWeight:600, fontSize:12, padding:'4px 7px', height:28, outline:'none'}}/>
            </Field>
            <Field label="Label"><TextInput value={nn} onChange={setNn} w={160}/></Field>
            <Btn kind="accent" sm onClick={addHoliday}>＋ Add</Btn>
            <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, marginLeft:'auto'}}>regional add-ons for {config.plantState} are bundled · your customs marked ◆</span>
          </div>
          {/* holiday list — from the solver when available, else the mock gazette */}
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'2px 16px'}}>
            {(res && res.holiday_list && res.holiday_list.length
              ? res.holiday_list.slice().sort((a,b)=>a.month-b.month||a.day-b.day).map(h=>({d:`${String(h.day).padStart(2,'0')}/${String(h.month).padStart(2,'0')}`, n:h.name, cust:isCustom(h.month,h.day), m:h.month, day:h.day}))
              : M.holidays.map(([d,n])=>({d,n,cust:false}))
            ).map((h,i)=>(
              <div key={i} style={{display:'flex', justifyContent:'space-between', alignItems:'center', gap:6, fontFamily:F.mono, fontSize:11, padding:'5px 0', borderBottom:`1px dotted ${C.line2}`}}>
                <span style={{fontWeight:700, whiteSpace:'nowrap'}}>{h.cust?'◆ ':''}{h.d}</span>
                <span style={{color:C.tx2, flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', textAlign:'right'}}>{h.n}</span>
                {h.cust && <button onClick={()=>removeHoliday(customHolidays.findIndex(x=>x.month===h.m&&x.day===h.day))} title="remove custom holiday" style={{border:'none', background:'transparent', color:C.dg, cursor:'pointer', fontSize:11, padding:0, lineHeight:1}}>✕</button>}
              </div>
            ))}
          </div>
          <div style={{marginTop:12}}>
            <SubLabel>Workday availability · {yr}{res?'':' (seed)'}</SubLabel>
            <div style={{display:'flex', height:26, border:`2px solid ${C.line}`}}>
              <div style={{width:`${workdays/tot*100}%`, background:C.gn, color:'#fff', display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700, whiteSpace:'nowrap', overflow:'hidden'}}>{workdays} WORKDAYS</div>
              <div style={{width:`${weekoff/tot*100}%`, background:C.bg3, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, whiteSpace:'nowrap', overflow:'hidden'}}>{weekoff} WK-OFF</div>
              <div style={{width:`${holidays/tot*100}%`, background:C.ac, color:C.onAc, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, fontWeight:700, whiteSpace:'nowrap', overflow:'hidden'}}>{holidays} HOL</div>
            </div>
          </div>
        </Card>
      </Grid>
    </StageSection>
  );
}
// ── Planning Profile (handoff v2 §7.3) — gates the spine; stages turn on/off ──
function SetupProfile() {
  const { profile, gate, setProfile } = useProfile();
  const Seg = ({ k, opts }) => (
    <div style={{display:'flex', border:`2px solid ${C.line}`}}>
      {opts.map(([v,l],i)=>(
        <button key={v} onClick={()=>setProfile({ [k]:v })} style={{
          flex:1, textAlign:'center', padding:'6px 8px', fontFamily:F.mono, fontSize:9.5, fontWeight:700, letterSpacing:'.03em',
          border:'none', borderRight:i<opts.length-1?`2px solid ${C.line}`:'none', cursor:'pointer',
          background: profile[k]===v?C.ink:C.paper, color: profile[k]===v?C.ac:C.tx3, whiteSpace:'nowrap',
        }}>{profile[k]===v?'● ':'○ '}{l}</button>
      ))}
    </div>
  );
  const offList = [
    gate.profitmix    && 'Profit-mix + seasonal Aggregate',
    gate.sequencing   && 'Sequencing',
    gate.transport    && 'Transport / Logistics',
    gate.landed       && 'Landed cost · FX · Incoterms',
    gate.demandModels && 'Demand model-competition',
  ].filter(Boolean);
  return (
    <StageSection step="2" title="Planning Profile" sub="six answers that turn whole capabilities on or off — so a new user never sees all 16 engines at once">
      <Grid cols={3}>
        <Card icon="🎚️" title="Profile" badge="GATES THE SPINE" badgeTone="y" span={2}
          info={{ what:'Adaptive triage: each answer hides stages that don\u2019t apply to your operation.', flows:'Profile → spine gating, nav, solver readiness.' }}
          dev={{ comp:'PlanningProfileCard', props:'state.profile, dispatch(SET_PROFILE)', state:'profile.{makePolicy,capacity,imports,lines,distribution,externalForecast}', note:'Drives M.profileGate — gated stages render <GateNote/>, not empty grids.' }}>
          <Grid cols={2} gap={12}>
            <Field label="Make policy"><Seg k="makePolicy" opts={[['MTS','pure MTS'],['MTS+MTO','MTS+MTO'],['MTO','pure MTO'],['ATO','ATO']]}/></Field>
            <Field label="Capacity tightness"><Seg k="capacity" opts={[['tight','tight'],['ample','ample']]}/></Field>
            <Field label="Imports?"><Seg k="imports" opts={[[true,'yes'],[false,'no']]}/></Field>
            <Field label="Production lines"><Seg k="lines" opts={[['1','single'],['many','many']]}/></Field>
            <Field label="Distribution"><Seg k="distribution" opts={[['single','single-site'],['network','network']]}/></Field>
            <Field label="Forecast supplied externally?"><Seg k="externalForecast" opts={[[false,'we forecast'],[true,'external']]}/></Field>
          </Grid>
        </Card>
        <Card icon="🚦" title="What this switches off" badge={`${offList.length} hidden`} badgeTone={offList.length?'k':undefined}
          info={{ what:'Live preview of the capabilities your profile hides.', flows:'Hidden stages show a GateNote, not an empty screen.' }}
          dev={{ comp:'ProfileGatePreview', props:'M.profileGate(profile)' }}>
          {offList.length ? (
            <div style={{display:'flex', flexDirection:'column', gap:6}}>
              {offList.map((o,i)=>(
                <div key={i} style={{display:'flex', alignItems:'center', gap:8, border:`2px solid ${C.line2}`, padding:'6px 9px', background:C.bg3}}>
                  <span style={{width:14, height:14, flexShrink:0, display:'grid', placeItems:'center', background:C.tx3, color:C.paper, fontFamily:F.disp, fontWeight:900, fontSize:10}}>✕</span>
                  <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>{o}</span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{padding:'14px', textAlign:'center', fontFamily:F.mono, fontSize:10, color:C.tx3, border:`2px dashed ${C.line2}`}}>
              full spine active — every stage shows
            </div>
          )}
          <Reading formula="stage.visible = !profileGate[stage]" soWhat="Pure-MTO + ample capacity hides Profit-mix; one line hides Sequencing; single-site hides Transport."/>
        </Card>
      </Grid>
    </StageSection>
  );
}
// ── Parameter Governance (Ph2 · P2) — the registry, bound to LIVE state ──────
// One ledger of every governed input: value + provenance read live, the SOLVE_DEPS
// token it travels on, and exactly which solves re-flag on edit. Nothing faked.
function SetupRegistry({ onNav }){
  const { config } = useConfig();
  const { planning } = usePlanning();
  const num = (v,seed)=> (v==null||v==='') ? seed : Number(v);
  const ov  = (v,seed)=> (v!=null && v!=='' && Number(v)!==Number(seed)) ? 'override' : 'seed';
  const fxRows = (M.fxRates && M.fxRates.rows) || [];
  const fxLive = config.fxRates || {};
  const fxAt   = (r)=> (fxLive[r.ccy]!=null && fxLive[r.ccy]!=='') ? fxLive[r.ccy] : r.rate;
  const fxOver = fxRows.some(r => Number(fxAt(r)) !== r.rate);
  const fxVal  = fxRows.map(fxAt);
  const INV  = ['Procurement','Policy','Rolling','MEIO','MEIO-net','CVaR'];
  const PROD = ['Production','Aggregate','Line-capacity'];
  const PLAN = INV.concat(PROD);
  const budget = Number(config.procBudget)>0;
  const pmOn   = Number(config.pmBudget)>0 || Number(config.pmWarehouse)>0;
  const campOn = Number(config.prodCampaignMinRun)>0;
  const rows = [
    { group:'Inventory & service', param:'Service level (α)', value:`${(num(config.serviceLevel,0.95)*100).toFixed(0)}%`, seed:'95%', prov:ov(config.serviceLevel,0.95), token:'config', feeds:INV, editTab:'sourcing', editLabel:'Sourcing' },
    { group:'Inventory & service', param:'Inventory holding spread', value:`${num(config.invHoldingSpread,12.8)}%/yr`, seed:'12.8%', prov:ov(config.invHoldingSpread,12.8), token:'config', feeds:INV.concat(['Capital']), editTab:'finance', editLabel:'Finance' },
    { group:'Inventory & service', param:'Inventory carry rate', value:`${(typeof carryRateParts==='function'?carryRateParts(config).total:24)}%/yr`, seed:'≈24%', prov:'derived', token:'config → WACC', feeds:INV.concat(['Capital']), from:['WACC · Finance hurdle','Holding spread · above'], editTab:'finance', editLabel:'Finance' },
    { group:'Inventory & service', param:'RM-spend budget / period', value: budget?`₹${Number(config.procBudget).toLocaleString('en-IN')}`:'unbounded', seed:'unbounded', prov: budget?'override':'seed', token:'config', feeds:['Procurement','Policy','Rolling'], editTab:'sourcing', editLabel:'Sourcing' },
    { group:'FX · ₹ per unit', param:'USD / EUR / JPY', value:`${fxVal[0]} / ${fxVal[1]} / ${fxVal[2]}`, seed:'84.20 / 91.40 / 0.563', prov: fxOver?'override':'seed', token:'config', feeds:INV.concat(['Profit-mix']), editTab:'finance', editLabel:'Finance · FX' },
    { group:'Tax & capital', param:'Corporate tax rate', value:`${num(config.taxRate,25.17)}%`, seed:'25.17%', prov:ov(config.taxRate,25.17), token:'config → WACC', feeds:['Capital'].concat(INV), editTab:'finance', editLabel:'Finance' },
    { group:'Production schedule', param:'Line labor rate', value:`₹${num(config.prodLaborRate,120)}/hr`, seed:'₹120', prov:ov(config.prodLaborRate,120), token:'cfg.prod', feeds:PROD, editTab:'production', editLabel:'Production' },
    { group:'Production schedule', param:'Shutdown threshold', value:`${num(config.prodShutdownPct,25)}% util`, seed:'25%', prov:ov(config.prodShutdownPct,25), token:'cfg.prod', feeds:PROD, editTab:'production', editLabel:'Production' },
    { group:'Production schedule', param:'Campaign min-run', value: campOn?`${config.prodCampaignMinRun} u/run`:'off', seed:'off', prov: campOn?'override':'seed', token:'cfg.prod', feeds:PROD, editTab:'production', editLabel:'Production' },
    { group:'Profit-mix caps', param:'Cash budget · warehouse', value:`${Number(config.pmBudget)>0?'₹'+Number(config.pmBudget).toLocaleString('en-IN'):'∞'} · ${Number(config.pmWarehouse)>0?config.pmWarehouse+'u':'∞'}`, seed:'∞ · ∞', prov: pmOn?'override':'seed', token:'cfg.profit', feeds:['Profit-mix'], editTab:'console', editLabel:'Console' },
    { group:'Planning calendar', param:'Frozen / Slushy fence', value:`${planning.frozenWeeks}w / ${planning.slushyWeeks}w`, seed:'4w / 12w', prov:(Number(planning.frozenWeeks)!==4||Number(planning.slushyWeeks)!==12)?'override':'seed', token:'planning', feeds:PLAN, editTab:'setup', editLabel:'Calendar ↑' },
    { group:'Planning calendar', param:'Horizon · grain', value:`${planning.horizonLength} ${planning.timeGrain}s`, seed:'52 weeks', prov:(Number(planning.horizonLength)!==52||planning.timeGrain!=='week')?'override':'seed', token:'planning', feeds:PLAN, editTab:'setup', editLabel:'Calendar ↑' },
    { group:'Planning calendar', param:'Schedule fence (MILP)', value:`${num(planning.productionScheduleWeeks,13)}w`, seed:'13w', prov:ov(planning.productionScheduleWeeks,13), token:'planning', feeds:PROD, editTab:'setup', editLabel:'Calendar ↑' },
  ];
  return (
    <StageSection step="4" title="Parameter Governance" sub="every governed input in one ledger — its live value, whether it’s still a seed or your override, the dependency token it travels on, and exactly what re-solves when you change it">
      <Card icon="🗂️" title="Parameter Registry" badge={`${rows.length} governed`} badgeTone="y" span={3}
        info={{ what:'The single inventory of governed inputs. PROVENANCE says whether a value is still the seed default or your override; TOKEN is the stale-cascade key SOLVE_DEPS uses; FEEDS lists the solves that consume the input. The Ph2 carve-outs cfg.prod / cfg.profit re-flag EXACTLY their FEEDS (a production-knob or profit-cap edit no longer drags FX/tax-only solves stale); the broad `config` token re-flags the whole inventory family conservatively (it stales at least its FEEDS — never fewer — plus shared consumers like profit-mix/capital, since those inputs fan through WACC/landed cost). Read live from state — no faked rows.', flows:'Registry → every governed solver input · provenance · lineage.' }}
        dev={{ comp:'ParamRegistry', props:'config, planning → rows[]', state:'config.*, planning.*', note:'token column = SOLVE_DEPS dependency key; cfg.prod/cfg.profit are the Ph2 carve-outs.' }}>
        <ParamRegistry rows={rows} onNav={onNav}/>
        <Reading formula="provenance = (value ≠ seed) ? override : seed   ·   token = SOLVE_DEPS key   ·   feeds = solves that consume the input"
          soWhat="The provenance contract, made inspectable: the TOKEN a param travels on is the same key the stale-cascade fires on. The cfg.prod / cfg.profit carve-outs re-flag exactly their FEEDS; the broad `config` token over-flags conservatively (≥ its FEEDS, never fewer) — over-staling is safe, under-staling is the bug it refuses. Click ⛓ for lineage, or jump to a param’s editor."/>
      </Card>
    </StageSection>
  );
}
window.StageSetup = StageSetup;
