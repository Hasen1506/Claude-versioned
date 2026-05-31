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
        right={<Btn kind="secondary">⤓ Import JSON</Btn>}/>
      <div style={{padding:18}}>
        <SetupIdentity onNav={onNav}/>
        <SetupCalendar/>
        <SetupProfile/>
      </div>
    </div>
  );
}

function SetupIdentity({ onNav }) {
  return (
    <StageSection step="1" title="Company Identity" sub="legal entity · currency · tax regime · service level — the MSME tier is derived, not chosen">
      <Grid cols={3}>
        <Card icon="🏢" title="Company" badge="GST · REG" span={2}
          info={{ what:'Legal identity, currency, tax regime, service level.', flows:'Tax rate → Finance; service level → safety stock.' }}
          dev={{ comp:'SetupTab', props:'state.config', state:'config.company, config.currency, config.taxRate' }}>
          {/* big editable name title — the owner couldn't read the cramped KV row */}
          <div style={{marginBottom:6, fontFamily:F.mono, fontSize:9, letterSpacing:'.1em', color:C.tx3}}>COMPANY NAME</div>
          <input defaultValue={M.company} style={{
            width:'100%', border:`2px solid ${C.line}`, background:C.paper, color:C.ink,
            fontFamily:F.disp, fontWeight:900, fontSize:22, letterSpacing:'-.5px', padding:'8px 12px', outline:'none',
          }}/>
          <div style={{marginTop:14, display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
            <Field label="Base Currency"><Select value="₹ INR · ₹84.20/$" options={['₹ INR · ₹84.20/$','$ USD','€ EUR']}/></Field>
            <Field label="Plant State"><Select value="Tamil Nadu" options={['Tamil Nadu','Maharashtra','Gujarat','Karnataka']}/></Field>
            <Field label="Effective Tax"><NumInput value="25.17" suffix="%"/></Field>
            <Field label="Service Level"><NumInput value="95.0" suffix="% z=1.645"/></Field>
          </div>
          <div style={{marginTop:12, display:'flex', alignItems:'center', gap:14}}>
            <Field label="GST Registered"><div style={{display:'flex', border:`2px solid ${C.line}`, width:120}}>
              {['ON','OFF'].map((o,i)=><div key={o} style={{flex:1, textAlign:'center', padding:'5px 0', fontFamily:F.mono, fontSize:10, fontWeight:700, background:i===0?C.ink:C.paper, color:i===0?C.ac:C.tx3, borderRight:i===0?`2px solid ${C.line}`:'none', cursor:'pointer'}}>{o}</div>)}
            </div></Field>
            <div style={{display:'flex', gap:6, flexWrap:'wrap', alignSelf:'flex-end', paddingBottom:4}}>
              <Tag c="k">GST · ITC RECOVERABLE</Tag><span style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3}}>CIN {M.cin}</span>
            </div>
          </div>
        </Card>

        <Card icon="🏷️" title="MSME Tier" badge="DERIVED" badgeTone="y"
          info={{ what:'Tier auto-computed from turnover + investment; drives 43B(h) terms.', flows:'Payment terms → Sourcing & Finance.' }}
          dev={{ comp:'MSMEBadge', props:'config.turnover, config.investment (computed)', note:'No selector — derived from the two inputs.' }}>
          <Grid cols={1} gap={8}>
            <Field label="Plant & Machinery" hint="sourced from Finance · Asset Register"><NumInput value="9.40" prefix="₹" suffix="Cr" disabled/></Field>
            <Field label="Annual Turnover" hint="sourced from Finance · actuals"><NumInput value="38.40" prefix="₹" suffix="Cr" disabled/></Field>
          </Grid>
          <div style={{marginTop:12, padding:'14px', background:C.ink, color:C.paper, textAlign:'center'}}>
            <div style={{fontFamily:F.disp, fontSize:26, fontWeight:900, color:C.ac, letterSpacing:'.04em'}}>SMALL</div>
            <div style={{fontFamily:F.mono, fontSize:9, color:C.paper, marginTop:4, opacity:.8}}>investment &lt; ₹10Cr · turnover &lt; ₹50Cr</div>
          </div>
          <Reading formula="tier = f(investment, turnover) per MSMED Act" soWhat="43B(h): MSME suppliers must be paid in 45 days or the spend is tax-disallowed."/>
        </Card>
      </Grid>
    </StageSection>
  );
}

function SetupCalendar() {
  const grain = M.calendar.grain;
  return (
    <StageSection step="2" title="Planning Calendar" sub="the one clock the whole app renders against — grain + horizon drive every period axis">
      <Grid cols={3}>
        <Card icon="📅" title="Grain & Horizon" badge={`${M.calendar.count} buckets`}
          info={{ what:'Grain (day/week/month) + horizon define the single period axis app-wide.', flows:'Axis → every solver, forecast, MPS, contract.' }}
          dev={{ comp:'CalendarCard', props:'state.calendar', state:'calendar.{grain,start,count}' }}>
          <Field label="Time Grain">
            <div style={{display:'flex', border:`2px solid ${C.line}`}}>
              {['day','week','month'].map((g,i)=>(
                <div key={g} style={{flex:1, textAlign:'center', padding:'7px 0', fontFamily:F.disp, fontSize:11, fontWeight:800, textTransform:'uppercase', cursor:'pointer',
                  background:g===grain?C.ac:C.paper, color:g===grain?C.onAc:C.tx, borderRight:i<2?`2px solid ${C.line}`:'none'}}>{g}</div>
              ))}
            </div>
          </Field>
          <div style={{marginTop:10, display:'grid', gridTemplateColumns:'1fr 1fr', gap:10}}>
            <Field label="Horizon"><NumInput value={M.calendar.count} suffix={grain+'s'}/></Field>
            <Field label="Start Date"><TextInput value="01 Jun 2026"/></Field>
            <Field label="Work Days / Wk"><NumInput value="6"/></Field>
            <Field label="Frozen / Slushy"><TextInput value="4w / 12w"/></Field>
          </div>
          <div style={{marginTop:12, padding:'9px 11px', background:C.ac, color:C.onAc, fontFamily:F.mono, fontSize:10, fontWeight:600, lineHeight:1.5}}>
            ◆ Planning {M.calendar.count} {grain}ly buckets · {M.periods[0].label} {M.periods[0].date}-26 → {M.periods[M.periods.length-1].label} {M.periods[M.periods.length-1].date}-27 · ₹ · 95% service.
          </div>
          <div style={{marginTop:8, padding:'7px 10px', border:`2px dashed ${C.a2}`, fontFamily:F.mono, fontSize:9, color:C.tx2, lineHeight:1.5}}>
            ⛓ MPS · Procurement · Contracts all render this same horizon — change the grain or count here and the whole app re-buckets.
          </div>
        </Card>

        <Card icon="📆" title="TN Gazetted Holidays 2026" badge="22"
          info={{ what:'State holidays removed from available workdays.', flows:'Net workdays → capacity calc.' }}
          dev={{ comp:'HolidayEditor', props:'state.calendar.holidays' }} span={2}>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'2px 16px'}}>
            {M.holidays.map(([d,n],i)=>(
              <div key={i} style={{display:'flex', justifyContent:'space-between', fontFamily:F.mono, fontSize:11, padding:'5px 0', borderBottom:`1px dotted ${C.line2}`}}>
                <span style={{fontWeight:700}}>{d}</span><span style={{color:C.tx2}}>{n}</span>
              </div>
            ))}
          </div>
          <div style={{marginTop:12}}>
            <SubLabel>Workday availability · 2026</SubLabel>
            <div style={{display:'flex', height:26, border:`2px solid ${C.line}`}}>
              <div style={{width:'74%', background:C.gn, color:'#fff', display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:10, fontWeight:700}}>270 WORKDAYS</div>
              <div style={{width:'14%', background:C.bg3, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9}}>52 WK-OFF</div>
              <div style={{width:'12%', background:C.ac, color:C.onAc, display:'grid', placeItems:'center', fontFamily:F.mono, fontSize:9, fontWeight:700}}>22 HOL</div>
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
    <StageSection step="3" title="Planning Profile" sub="six answers that turn whole capabilities on or off — so a new user never sees all 16 engines at once">
      <Grid cols={3}>
        <Card icon="🎚️" title="Profile" badge="GATES THE SPINE" badgeTone="y" span={2}
          info={{ what:'Adaptive triage: each answer hides stages that don\u2019t apply to your operation.', flows:'Profile → spine gating, nav, solver readiness.' }}
          dev={{ comp:'PlanningProfileCard', props:'state.profile, dispatch(SET_PROFILE)', state:'profile.{makePolicy,capacity,imports,lines,distribution,externalForecast}', note:'Drives M.profileGate — gated stages render <GateNote/>, not empty grids.' }}>
          <Grid cols={2} gap={12}>
            <Field label="Make policy"><Seg k="makePolicy" opts={[['MTS + MTO','MTS+MTO'],['MTO','pure MTO'],['ATO','ATO']]}/></Field>
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
window.StageSetup = StageSetup;
