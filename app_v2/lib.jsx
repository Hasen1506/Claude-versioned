// ──────────────────────────────────────────────────────────────────────
// lib.jsx — shared design-system atoms (handoff §1 component kit)
// Brutalist mono grid. All color via CSS vars so themes (mono/noir/sepia)
// swap with zero component changes. Exported to window for all stages.
// ──────────────────────────────────────────────────────────────────────
const { useState, useMemo, useRef, useEffect } = React;

// token aliases → CSS vars (handoff: never hard-code hex)
const C = {
  bg:'var(--bg)', bg2:'var(--bg2)', bg3:'var(--bg3)', bg4:'var(--bg4)',
  ink:'var(--ink)', tx:'var(--tx)', tx2:'var(--tx2)', tx3:'var(--tx3)',
  paper:'var(--paper)', card:'var(--card)',
  line:'var(--br)', line2:'var(--br2)',
  ac:'var(--ac)', ac2:'var(--ac2)', a2:'var(--a2)', a3:'var(--a3)', a4:'var(--a4)',
  gn:'var(--gn)', dg:'var(--dg)', hl:'var(--hl)', hl2:'var(--hl2)', onAc:'var(--onAc)',
};
const F = { disp:'var(--disp)', body:'var(--body)', mono:'var(--mono)' };

// ── BUILD config ────────────────────────────────────────────────────────────
// app_v2 ships clean: the handoff <DevNote/> annotations are OFF for end users.
// Flip on for implementation work with localStorage.setItem('es_dev','1').
const BUILD = {
  devNotes: (typeof localStorage!=='undefined' && localStorage.getItem('es_dev')==='1'),
};

// ─────────────────────────── primitives ───────────────────────────
const Box = ({children, style, ...rest}) => (
  <div {...rest} style={{border:`2px solid ${C.line}`, background:C.paper, ...style}}>{children}</div>
);

const Sep = ({v, style}) => (
  <div style={ v
    ? {width:2, alignSelf:'stretch', background:C.line, ...style}
    : {height:2, background:C.line, margin:'12px 0', ...style} }/>
);

// metric block / KPI tile
const Blk = ({label, value, sub, tone, wide, accent, onClick}) => (
  <div onClick={onClick} style={{
    border:`2px solid ${C.line}`,
    background: tone==='y'?C.ac : tone==='k'?C.ink : tone==='c'?C.card : C.paper,
    color: tone==='k'?C.paper : tone==='y'?C.onAc : C.tx,
    padding:'10px 12px', gridColumn: wide?'span 2':'span 1',
    display:'flex', flexDirection:'column', gap:2, cursor:onClick?'pointer':'default',
    position:'relative', minWidth:0,
  }}>
    {accent && <div style={{position:'absolute', top:0, left:0, bottom:0, width:4, background:accent}}/>}
    <div style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.1em', textTransform:'uppercase', opacity:.7, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{label}</div>
    <div className="num" style={{fontFamily:F.disp, fontSize:22, fontWeight:700, letterSpacing:-.5, lineHeight:1.02}}>{value}</div>
    {sub && <div style={{fontFamily:F.mono, fontSize:10, opacity:.66, marginTop:2}}>{sub}</div>}
  </div>
);
const KPI = Blk;

const KpiRow = ({children, cols}) => (
  <div style={{display:'grid', gridTemplateColumns:`repeat(${cols||4}, 1fr)`, gap:8}}>{children}</div>
);

const Tag = ({c, children, style}) => {
  const map = {
    y:{bg:C.ac, fg:C.onAc}, k:{bg:C.ink, fg:C.paper}, r:{bg:C.dg, fg:'#fff'},
    g:{bg:C.gn, fg:'#fff'}, b:{bg:C.a2, fg:'#fff'}, v:{bg:C.a3, fg:'#fff'},
    a:{bg:C.a4, fg:'#fff'}, w:{bg:C.paper, fg:C.tx},
  };
  const t = map[c] || map.w;
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:4, padding:'2px 6px', fontFamily:F.mono, fontSize:9, fontWeight:700,
      letterSpacing:'.06em', textTransform:'uppercase', background:t.bg, color:t.fg,
      border:`1.5px solid ${C.line}`, whiteSpace:'nowrap', ...style,
    }}>{children}</span>
  );
};

const Badge = ({children, tone}) => (
  <span style={{
    fontFamily:F.mono, fontSize:9, fontWeight:700, letterSpacing:'.06em', padding:'1px 5px',
    border:`1.5px solid ${C.line}`, background: tone==='k'?C.ink:tone==='y'?C.ac:C.paper,
    color: tone==='k'?C.paper:C.tx, textTransform:'uppercase',
  }}>{children}</span>
);

const Btn = ({children, kind, sm, onClick, style, ...rest}) => {
  const k = {
    primary:{bg:C.ink, fg:C.paper}, secondary:{bg:C.paper, fg:C.tx},
    accent:{bg:C.ac, fg:C.onAc}, danger:{bg:C.dg, fg:'#fff'}, ghost:{bg:'transparent', fg:C.tx},
  }[kind||'secondary'];
  return (
    <button onClick={onClick} {...rest} style={{
      fontFamily:F.disp, fontWeight:800, letterSpacing:'.04em', textTransform:'uppercase',
      fontSize: sm?10:11, padding: sm?'5px 9px':'8px 14px', border:`2px solid ${C.line}`,
      background:k.bg, color:k.fg, cursor:'pointer', display:'inline-flex', alignItems:'center', gap:6, whiteSpace:'nowrap', ...style,
    }}>{children}</button>
  );
};

// ───────────────────────── SectionInfo — popover (handoff: keep these) ───────
function SectionInfo({ what, flows }) {
  const [open, setOpen] = useState(false);
  return (
    <span style={{position:'relative', display:'inline-block'}}>
      <span onClick={()=>setOpen(o=>!o)} title="what it does / flows to" style={{
        cursor:'pointer', width:15, height:15, display:'inline-grid', placeItems:'center',
        border:`1.5px solid ${C.line}`, borderRadius:'50%', fontFamily:F.mono, fontSize:10,
        fontWeight:700, background: open?C.ac:C.paper, color:C.tx, lineHeight:1,
      }}>i</span>
      {open && (
        <div style={{
          position:'absolute', top:20, left:0, zIndex:40, width:248, background:C.paper,
          border:`2px solid ${C.line}`, boxShadow:`5px 5px 0 ${C.ink}`, padding:'10px 11px',
          fontFamily:F.body, fontSize:11, lineHeight:1.5, color:C.tx,
        }}>
          <div style={{fontFamily:F.mono, fontSize:8.5, letterSpacing:'.12em', color:C.tx3, marginBottom:3}}>WHAT IT DOES</div>
          <div style={{marginBottom:7}}>{what}</div>
          <div style={{fontFamily:F.mono, fontSize:8.5, letterSpacing:'.12em', color:C.tx3, marginBottom:3}}>FLOWS TO</div>
          <div style={{color:C.tx2}}>{flows}</div>
        </div>
      )}
    </span>
  );
}

// ───────────────────────── DevNote (Claude Code handoff annotation) ─────────
function DevNote({ comp, props, state, note }) {
  const [open, setOpen] = useState(false);
  if (!BUILD.devNotes) return null;   // hidden for end users; on via es_dev=1
  return (
    <span style={{position:'relative', display:'inline-block', marginLeft:'auto'}}>
      <span onClick={()=>setOpen(o=>!o)} title="dev wiring" style={{
        cursor:'pointer', fontFamily:F.mono, fontSize:8.5, fontWeight:700, letterSpacing:'.08em',
        padding:'2px 6px', border:`1.5px dashed ${C.a2}`, color:C.a2, background:'transparent',
        textTransform:'uppercase', whiteSpace:'nowrap',
      }}>&lt;/&gt; {comp}</span>
      {open && (
        <div style={{
          position:'absolute', top:22, right:0, zIndex:50, width:300, background:C.bg2,
          border:`2px solid ${C.a2}`, boxShadow:`5px 5px 0 ${C.line}`, padding:'10px 11px',
          fontFamily:F.mono, fontSize:10, lineHeight:1.55, color:C.tx,
        }}>
          <div style={{fontSize:8.5, letterSpacing:'.12em', color:C.a2, marginBottom:3}}>COMPONENT</div>
          <div style={{fontWeight:700, marginBottom:6}}>&lt;{comp}/&gt;</div>
          {props && (<><div style={{fontSize:8.5, letterSpacing:'.12em', color:C.a2, marginBottom:3}}>PROPS</div>
            <div style={{marginBottom:6, color:C.tx2}}>{props}</div></>)}
          {state && (<><div style={{fontSize:8.5, letterSpacing:'.12em', color:C.a2, marginBottom:3}}>STATE KEYS</div>
            <div style={{marginBottom:6, color:C.tx2}}>{state}</div></>)}
          {note && <div style={{color:C.tx3, fontStyle:'italic'}}>{note}</div>}
        </div>
      )}
    </span>
  );
}

// ───────────────────────── Card (handoff card anatomy) ──────────────────────
// .card → .card-title (emoji + name + badge + SectionInfo + DevNote) → body
function Card({ icon, title, badge, badgeTone, info, dev, right, children, span, style, accent }) {
  return (
    <div className="animate-in" style={{
      border:`2px solid ${C.line}`, background:C.paper, display:'flex', flexDirection:'column',
      gridColumn: span?`span ${span}`:'auto', position:'relative', minWidth:0, ...style,
    }}>
      {accent && <div style={{height:4, background:accent}}/>}
      <div style={{
        display:'flex', alignItems:'center', gap:8, padding:'9px 12px',
        borderBottom:`2px solid ${C.line}`, background:C.card,
      }}>
        {icon && <span style={{fontSize:14, lineHeight:1, filter:'grayscale(.15)'}}>{icon}</span>}
        <span style={{fontFamily:F.disp, fontSize:11.5, fontWeight:800, letterSpacing:'.04em', textTransform:'uppercase'}}>{title}</span>
        {badge && <Badge tone={badgeTone}>{badge}</Badge>}
        {info && <SectionInfo what={info.what} flows={info.flows}/>}
        {right}
        {dev && <DevNote {...dev}/>}
      </div>
      <div style={{padding:'12px', flex:1, minWidth:0}}>{children}</div>
    </div>
  );
}

// ───────────────────────── DataTable ────────────────────────────────────────
function DataTable({ cols, rows, align, dense, foot }) {
  return (
    <div style={{overflowX:'auto', border:`2px solid ${C.line}`}}>
      <table style={{borderCollapse:'collapse', width:'100%', fontFamily:F.mono, fontSize:10.5}}>
        <thead>
          <tr style={{background:C.ink}}>
            {cols.map((c,i)=>(
              <th key={i} style={{
                color:C.paper, textAlign:(align&&align[i])||(i?'right':'left'), padding:'6px 9px',
                fontSize:9, letterSpacing:'.08em', textTransform:'uppercase', fontWeight:700,
                whiteSpace:'nowrap', borderRight: i<cols.length-1?`1px solid ${C.tx3}`:'none',
              }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r,ri)=>(
            <tr key={ri} style={{background: r.__hl?C.ac: ri%2?C.bg3:C.paper, borderTop:`1px solid ${C.line2}`}}>
              {(r.cells||r).map((cell,ci)=>(
                <td key={ci} className={ci?'num':''} style={{
                  textAlign:(align&&align[ci])||(ci?'right':'left'), padding: dense?'4px 9px':'6px 9px',
                  color: r.__hl?C.onAc:C.tx, fontWeight: ci===0||r.__b?700:400,
                  borderRight: ci<(r.cells||r).length-1?`1px solid ${C.line2}`:'none', whiteSpace:'nowrap',
                }}>{cell}</td>
              ))}
            </tr>
          ))}
          {foot && (
            <tr style={{background:C.ink}}>
              {foot.map((cell,ci)=>(
                <td key={ci} className={ci?'num':''} style={{
                  textAlign:(align&&align[ci])||(ci?'right':'left'), padding:'6px 9px', color:C.ac,
                  fontWeight:700, fontSize:10.5, whiteSpace:'nowrap',
                }}>{cell}</td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ───────────────────────── Field + NumInput (shared building blocks) ─────────
function Field({ label, hint, children, span }) {
  return (
    <label style={{display:'flex', flexDirection:'column', gap:4, gridColumn: span?`span ${span}`:'auto', minWidth:0}}>
      <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.08em', color:C.tx3, textTransform:'uppercase'}}>{label}</span>
      {children}
      {hint && <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{hint}</span>}
    </label>
  );
}
// Inputs support BOTH modes (wiring pass): pass `onChange` → controlled (bound to
// real store state); omit it → uncontrolled `defaultValue` (the prototype default,
// so every not-yet-wired call site is unchanged). NumInput keeps a local string
// buffer so partial entries ("1.", "-") don't get mangled by Number() mid-type.
function NumInput({ value, suffix, prefix, disabled, w, onChange }) {
  const controlled = typeof onChange === 'function';
  const [buf, setBuf] = useState(value==null?'':String(value));
  useEffect(()=>{ if(controlled) setBuf(value==null?'':String(value)); }, [value, controlled]);
  const inputProps = controlled
    ? { value: buf, onChange:(e)=>{ const v=e.target.value; setBuf(v);
        if(v==='') return onChange('');
        const n=Number(v); if(!Number.isNaN(n)) onChange(n); } }
    : { defaultValue: value };
  return (
    <span style={{display:'inline-flex', alignItems:'center', border:`2px solid ${disabled?C.line2:C.line}`, background:disabled?C.bg3:C.paper, height:30, width:w||'auto'}}>
      {prefix && <span style={{padding:'0 0 0 8px', fontFamily:F.mono, fontSize:11, color:C.tx3}}>{prefix}</span>}
      <input {...inputProps} disabled={disabled} className="num" style={{
        border:'none', background:'transparent', color:C.tx, fontFamily:F.disp, fontWeight:600, fontSize:13,
        padding:'0 8px', width:'100%', minWidth:0, outline:'none',
      }}/>
      {suffix && <span style={{padding:'0 8px 0 0', fontFamily:F.mono, fontSize:10, color:C.tx3}}>{suffix}</span>}
    </span>
  );
}
function TextInput({ value, disabled, w, onChange }) {
  const controlled = typeof onChange === 'function';
  const inputProps = controlled ? { value: value==null?'':value, onChange:(e)=>onChange(e.target.value) } : { defaultValue: value };
  return (
    <input {...inputProps} disabled={disabled} style={{
      border:`2px solid ${disabled?C.line2:C.line}`, background:disabled?C.bg3:C.paper, color:C.tx,
      fontFamily:F.disp, fontWeight:600, fontSize:13, padding:'6px 8px', height:30, width:w||'100%', outline:'none',
    }}/>
  );
}
function Select({ value, options, disabled, w, onChange }) {
  const controlled = typeof onChange === 'function';
  const selProps = controlled ? { value, onChange:(e)=>onChange(e.target.value) } : { defaultValue: value };
  return (
    <select {...selProps} disabled={disabled} style={{
      border:`2px solid ${disabled?C.line2:C.line}`, background:disabled?C.bg3:C.paper, color:C.tx,
      fontFamily:F.disp, fontWeight:600, fontSize:12, padding:'6px 8px', height:30, width:w||'100%', outline:'none',
      appearance:'none', backgroundImage:'none', cursor:'pointer',
    }}>{(options||[value]).map((o,i)=><option key={i} value={typeof o==='object'?o.value:o}>{typeof o==='object'?o.label:o}</option>)}</select>
  );
}

// ───────────────────────── Advanced ▸ progressive disclosure (P5) ────────────
function Advanced({ label, children, count }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{marginTop:8}}>
      <button onClick={()=>setOpen(o=>!o)} style={{
        width:'100%', textAlign:'left', border:`2px dashed ${C.line2}`, background:'transparent', cursor:'pointer',
        padding:'6px 10px', fontFamily:F.mono, fontSize:10, fontWeight:700, letterSpacing:'.06em',
        color:C.tx2, textTransform:'uppercase', display:'flex', alignItems:'center', gap:8,
      }}>
        <span style={{display:'inline-block', transform:open?'rotate(90deg)':'none', transition:'transform .15s'}}>▸</span>
        {label || 'Advanced'} {count!=null && <span style={{color:C.tx3}}>· {count} fields</span>}
        <span style={{marginLeft:'auto', color:C.tx3}}>{open?'hide':'show'}</span>
      </button>
      {open && <div className="animate-in" style={{marginTop:8}}>{children}</div>}
    </div>
  );
}

// ───────────────────────── SubTabNav (P3: the Finance pattern) ───────────────
function SubTabNav({ tabs, active, onChange }) {
  return (
    <div style={{display:'flex', borderBottom:`2px solid ${C.line}`, background:C.bg2, flexWrap:'wrap'}}>
      {tabs.map(t=>{
        const a = active===t.id;
        return (
          <button key={t.id} onClick={()=>onChange(t.id)} style={{
            padding:'9px 15px', border:'none', borderRight:`2px solid ${C.line}`, cursor:'pointer',
            background: a?C.ink:'transparent', color: a?C.paper:C.tx, position:'relative',
            fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.05em', textTransform:'uppercase',
            display:'flex', alignItems:'center', gap:7,
          }}>
            {t.n && <span style={{fontFamily:F.mono, fontSize:9, opacity:.6}}>{t.n}</span>}
            {t.label}
            {t.count!=null && <span style={{fontFamily:F.mono, fontSize:9, padding:'0 4px', border:`1px solid ${a?C.paper:C.line2}`, opacity:.8}}>{t.count}</span>}
            {a && <span style={{position:'absolute', left:0, right:0, bottom:-2, height:2, background:C.ac}}/>}
          </button>
        );
      })}
    </div>
  );
}

// ───────────────────────── StageHeader (title + kicker for each stage) ───────
function StageHeader({ n, title, kicker, right }) {
  return (
    <div style={{display:'flex', alignItems:'flex-end', gap:14, padding:'14px 18px 12px', borderBottom:`2px solid ${C.line}`, background:C.bg2}}>
      <div style={{fontFamily:F.disp, fontSize:30, fontWeight:900, color:C.ac, lineHeight:.9, letterSpacing:-1, WebkitTextStroke:`1px ${C.line}`}}>{n}</div>
      <div style={{flex:1}}>
        <div style={{fontFamily:F.disp, fontSize:18, fontWeight:900, letterSpacing:'.01em', textTransform:'uppercase', lineHeight:1}}>{title}</div>
        <div style={{fontFamily:F.mono, fontSize:10.5, color:C.tx3, marginTop:3}}>{kicker}</div>
      </div>
      {right}
    </div>
  );
}

// ───────────────────────── mini-viz helpers ─────────────────────────────────
// horizontal bar
const MiniBar = ({v, max, color, h}) => (
  <div style={{height:h||8, background:C.bg3, border:`1px solid ${C.line2}`, position:'relative', flex:1}}>
    <div style={{position:'absolute', inset:0, width:`${Math.max(2,Math.min(100, v/max*100))}%`, background:color||C.ink}}/>
  </div>
);
// sparkline
function Spark({ data, w, h, color, fill }) {
  const W=w||120, H=h||32, mn=Math.min(...data), mx=Math.max(...data), rng=(mx-mn)||1;
  const pts = data.map((d,i)=>[i/(data.length-1)*W, H-2-((d-mn)/rng)*(H-4)]);
  const path = pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:W, height:H, display:'block'}}>
      {fill && <path d={`${path} L${W} ${H} L0 ${H} Z`} fill={color||C.ac} opacity=".18"/>}
      <path d={path} fill="none" stroke={color||C.ink} strokeWidth="1.6"/>
    </svg>
  );
}
// donut/gauge ring
function Ring({ pct, size, color, label }) {
  const S=size||56, r=S/2-5, cir=2*Math.PI*r;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} style={{width:S, height:S}}>
      <circle cx={S/2} cy={S/2} r={r} fill="none" stroke={C.line2} strokeWidth="6"/>
      <circle cx={S/2} cy={S/2} r={r} fill="none" stroke={color||C.ac} strokeWidth="6"
        strokeDasharray={`${cir*pct/100} ${cir}`} strokeLinecap="butt" transform={`rotate(-90 ${S/2} ${S/2})`}/>
      <text x={S/2} y={S/2+1} textAnchor="middle" dominantBaseline="middle" fontFamily={F.disp} fontWeight="700" fontSize={S*0.26} fill={C.tx}>{label!=null?label:pct+'%'}</text>
    </svg>
  );
}
// grid of cards
const Grid = ({cols, gap, children, style}) => (
  <div style={{display:'grid', gridTemplateColumns:`repeat(${cols}, 1fr)`, gap:gap==null?12:gap, ...style}}>{children}</div>
);

// small section label inside a card
const SubLabel = ({children, right}) => (
  <div style={{display:'flex', alignItems:'center', gap:8, margin:'2px 0 8px'}}>
    <span style={{fontFamily:F.mono, fontSize:9.5, letterSpacing:'.1em', color:C.tx3, textTransform:'uppercase'}}>{children}</span>
    <div style={{flex:1, height:1, background:C.line2}}/>
    {right}
  </div>
);

// ───────────── ItemSelector — persistent item identity (handoff v2 §1.1) ──
// One global control pinned to every PLANNING stage. Reads/writes a tiny
// external store so any stage stays in sync without prop-drilling.
const itemStore = {
  id: (typeof localStorage!=='undefined' && localStorage.getItem('es_item')) || 'TPA-4471',
  view: (typeof localStorage!=='undefined' && localStorage.getItem('es_itemview')) || 'fg',
  subs: new Set(),
  set(patch){ Object.assign(this, patch);
    try{ localStorage.setItem('es_item', this.id); localStorage.setItem('es_itemview', this.view); }catch(e){}
    this.subs.forEach(f=>f()); },
};
function useActiveItem(){
  const [,force] = useState(0);
  useEffect(()=>{ const f=()=>force(x=>x+1); itemStore.subs.add(f); return ()=>itemStore.subs.delete(f); }, []);
  const item = (window.M && M.itemById(itemStore.id)) || null;
  return { item, view:itemStore.view, setItem:id=>itemStore.set({id}), setView:v=>itemStore.set({view:v}) };
}
function ItemSelector({ onNav }){
  const { item, view, setItem, setView } = useActiveItem();
  if(!item) return null;
  return (
    <div style={{borderBottom:`2px solid ${C.line}`, background:C.ink, color:C.paper}}>
      <div style={{display:'flex', alignItems:'center', gap:12, padding:'8px 18px', flexWrap:'wrap'}}>
        <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.14em', color:C.ac}}>PRODUCT ▸</span>
        <span style={{position:'relative', display:'inline-flex', alignItems:'center'}}>
          <select value={item.id} onChange={e=>setItem(e.target.value)} style={{
            appearance:'none', border:`2px solid ${C.ac}`, background:C.paper, color:C.ink, cursor:'pointer',
            fontFamily:F.disp, fontWeight:800, fontSize:13, padding:'5px 30px 5px 10px', letterSpacing:'.02em',
          }}>
            {M.items.map(it=> <option key={it.id} value={it.id}>{it.name} · {it.code}</option>)}
          </select>
          <span style={{position:'absolute', right:9, color:C.ink, fontSize:10, pointerEvents:'none'}}>▾</span>
        </span>
        <span style={{fontFamily:F.mono, fontSize:9, padding:'2px 6px', border:`1.5px solid ${C.ac}`, color:C.ac}}>{item.family}</span>
        <div style={{marginLeft:'auto', display:'flex', alignItems:'center', gap:0, border:`2px solid ${C.ac}`}}>
          {[['fg','Finished good'],['parts','Its parts']].map(([v,l])=>(
            <button key={v} onClick={()=>setView(v)} style={{
              fontFamily:F.mono, fontSize:9.5, fontWeight:700, letterSpacing:'.04em', padding:'4px 10px', border:'none', cursor:'pointer',
              background: view===v?C.ac:'transparent', color: view===v?C.onAc:C.paper,
            }}>{view===v?'● ':'○ '}{l}</button>
          ))}
        </div>
      </div>
      <PortfolioWorklist activeId={item.id} setItem={setItem} onNav={onNav}/>
    </div>
  );
}
// ───────────── PortfolioWorklist (Ph4 / P5) — persistent commit progress ──
// A SKU is "committed" when the planner took an EXPLICIT commit-class action on it
// (forecast-commit / override / sensing / lifecycle / NPI), recorded in the event log
// — the SAME `isDemandCommitted` test Demand's Consensus uses (Demand D-1). It is NOT
// "demand[sku] non-empty": merely viewing a SKU auto-runs the forecast and populates a
// WORKING series, which is a proposal, not a commitment. The strip rolls every finished
// SKU into "N/6 committed", points at the next uncommitted one, and jumps there (selects
// it + opens Demand to review & commit). It reads live events, so committing a SKU climbs
// the count in place — the worklist never resets or disappears (gate ⑪).
function PortfolioWorklist({ activeId, setItem, onNav }){
  const { state: events } = useStore(s=>s.events||[]);
  const items = M.items || [];
  if(items.length < 2) return null;
  const isCommitted = (it)=> isDemandCommitted(it.code, events);
  const done = items.filter(isCommitted);
  const next = items.find(it=> !isCommitted(it));
  const goNext = ()=>{ if(!next) return; setItem(next.id); if(onNav) onNav('demand'); };
  const allDone = !next;
  return (
    <div style={{display:'flex', alignItems:'center', gap:10, padding:'5px 18px', borderTop:`1px solid ${C.line2}`, background:C.bg3, color:C.tx, flexWrap:'wrap'}}>
      <span style={{fontFamily:F.mono, fontSize:8.5, letterSpacing:'.12em', color:C.tx3}}>PORTFOLIO ▸</span>
      <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800}}>{done.length}/{items.length} committed</span>
      <div style={{display:'flex', gap:4, flexWrap:'wrap'}}>
        {items.map(it=>{ const c = isCommitted(it); const on = it.id===activeId;
          return (
            <button key={it.id} onClick={()=>setItem(it.id)} title={`${it.code} — ${c?'committed (planner accepted/overrode the forecast)':'proposed — auto-forecast not yet committed'}${on?' · selected':''}`}
              style={{fontFamily:F.mono, fontSize:8.5, fontWeight:700, padding:'1px 6px', cursor:'pointer',
                border:`1.5px solid ${on?C.ac:c?C.gn:C.line2}`, background: c?C.gn:'transparent',
                color: c?C.paper:C.tx3, letterSpacing:'.02em'}}>
              {c?'●':'○'} {it.code}
            </button>
          );
        })}
      </div>
      {allDone
        ? <span style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.gn}}>✓ all {items.length} committed</span>
        : <button onClick={goNext} style={{marginLeft:'auto', fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.ac, background:'transparent',
            border:`1.5px solid ${C.ac}`, padding:'2px 8px', cursor:'pointer', letterSpacing:'.02em'}}>
            next: {next.code} →
          </button>}
    </div>
  );
}

// ───────────── Reading — the interpretation contract (handoff v2 §1.6) ──
// Inline under every result: (a) the formula/source, (b) one line of "so what".
function Reading({ formula, soWhat, tone }){
  return (
    <div style={{marginTop:8, border:`1.5px solid ${C.line2}`, borderLeft:`4px solid ${tone||C.ac}`, background:C.bg3, padding:'7px 10px'}}>
      {formula && <div style={{fontFamily:F.mono, fontSize:10, color:C.tx2, lineHeight:1.45}}><span style={{color:C.tx3, fontWeight:700}}>ƒ </span>{formula}</div>}
      {soWhat && <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx, marginTop:formula?5:0, fontWeight:600, lineHeight:1.4}}>→ {soWhat}</div>}
    </div>
  );
}

// ScopeBadge (Ph4 / R5): every section can declare whether it edits ONE item or the
// whole portfolio, so a card under the item selector can never be silently mis-scoped.
// 'item' = scoped to the selected SKU; 'global'/'portfolio' = all SKUs / company-wide.
// Pure presentation — the badge LABELS scope, it does not change it.
function ScopeBadge({ scope }){
  if(!scope) return null;
  const item = scope==='item';
  return (
    <span title={item ? 'scoped to the selected item — switch items in the selector above' : 'company-wide / all SKUs — not scoped to the selected item'}
      style={{fontFamily:F.mono, fontSize:8, fontWeight:700, letterSpacing:'.08em', padding:'1px 5px', flexShrink:0,
        border:`1.5px solid ${item?C.ac:C.line}`, color:item?C.ac:C.tx3, background:item?'transparent':C.bg3, whiteSpace:'nowrap'}}>
      {item ? '◧ THIS ITEM' : '▦ PORTFOLIO'}
    </span>
  );
}
// ───────────── StageSection — numbered band for single-scroll stages (handoff v2 Part 2) ──
function StageSection({ step, title, sub, right, scope, children }){
  return (
    <section style={{marginBottom:18}}>
      <div style={{display:'flex', alignItems:'center', gap:11, marginBottom:10}}>
        {step!=null && <span style={{fontFamily:F.disp, fontSize:13, fontWeight:900, color:C.onAc, background:C.ac, border:`2px solid ${C.line}`, width:26, height:26, display:'grid', placeItems:'center', flexShrink:0}}>{step}</span>}
        <div style={{minWidth:0}}>
          <div style={{display:'flex', alignItems:'center', gap:7, flexWrap:'wrap'}}>
            <span style={{fontFamily:F.disp, fontSize:14, fontWeight:900, letterSpacing:'.03em', textTransform:'uppercase'}}>{title}</span>
            <ScopeBadge scope={scope}/>
          </div>
          {sub && <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, marginTop:1}}>{sub}</div>}
        </div>
        <div style={{flex:1, height:2, background:C.line, marginLeft:4}}/>
        {right}
      </div>
      {children}
    </section>
  );
}

// ───────────── PrereqNote — dependency gate (handoff v2 Part 6.2) ──
function PrereqNote({ children, onNav, go, goLabel }){
  return (
    <div style={{display:'flex', alignItems:'center', gap:10, padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.a4}`, background:C.bg3, marginBottom:14}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.a4, letterSpacing:'.1em'}}>PREREQ</span>
      <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, flex:1}}>{children}</span>
      {go && <button onClick={()=>onNav(go)} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>{goLabel||'define →'}</button>}
    </div>
  );
}

// ───────────── SolverNetwork — ONE graph, 16 engines in 5 family lanes (handoff v2 §1.3) ──
// Rendered identically by Home and Console (delete the two divergent drawings).
function SolverNetwork({ onNav, sel, onSelect, height, freshness, liveObj }){
  const fams = M.solverFamilies;
  const accentMap = { a2:C.a2, a3:C.a3, a4:C.a4, gn:C.gn, ink:C.ink };
  const stCol = { done:C.gn, running:C.ac, queued:C.tx3, idle:C.tx3 };
  // OBS-1: when a live `freshness` map is supplied (id→fresh|stale|never|untracked),
  // colour the node strip from REAL solve state instead of the seed `status` field —
  // the headline fabric otherwise lies about which engines have actually run.
  const FRESH_COL = { fresh:C.gn, stale:C.a4, never:C.tx3, untracked:C.line2 };
  const colW = 156, nodeW = 132, nodeH = 44, gapY = 13, headY = 30, padX = 12;
  // group engines by family, compute positions
  const byFam = fams.map(f => M.solvers.filter(s=>s.fam===f.id));
  const maxRows = Math.max(...byFam.map(a=>a.length));
  const W = padX*2 + fams.length*colW;
  const H = headY + 14 + maxRows*(nodeH+gapY);
  const pos = {};
  byFam.forEach((engines, fi)=>{
    const x = padX + fi*colW + (colW-nodeW)/2;
    engines.forEach((s, ri)=>{ const y = headY + 14 + ri*(nodeH+gapY);
      pos[s.id] = { x, y, cx:x+nodeW, cy:y+nodeH/2, lx:x, ly:y+nodeH/2 };
    });
  });
  const edge = (a,b)=>{
    const p=pos[a], q=pos[b]; if(!p||!q) return null;
    // forward edges leave the right side, enter the left; back/vertical use centers
    const sameCol = Math.abs(p.x-q.x) < 4;
    const x1 = sameCol ? p.x+nodeW/2 : p.cx;
    const y1 = p.cy, x2 = sameCol ? q.x+nodeW/2 : q.lx, y2 = q.cy;
    const back = q.x < p.x;
    const mx = (x1+x2)/2;
    const d = sameCol ? `M${x1} ${y1} L${x2} ${y2}` : `M${x1} ${y1} C${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
    return <path key={a+b} d={d} fill="none" stroke={back?C.a3:C.tx2} strokeWidth={back?1.4:1.3} strokeDasharray={back?'4 3':'none'} markerEnd="url(#snah)" opacity={back?.6:.5}/>;
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', height:height||'auto', display:'block', maxWidth:W}}>
      <defs><marker id="snah" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6 Z" fill={C.tx2}/></marker></defs>
      {/* family lane bands + headers */}
      {fams.map((f, fi)=>{
        const x = padX + fi*colW;
        return (
          <g key={f.id}>
            <rect x={x+2} y={headY} width={colW-4} height={H-headY-4} fill={accentMap[f.accent]} opacity=".05"/>
            <text x={x+colW/2} y={16} textAnchor="middle" fontFamily={F.disp} fontWeight="900" fontSize="10.5" fill={accentMap[f.accent]} letterSpacing=".06em">{f.name.toUpperCase()}</text>
            <text x={x+colW/2} y={26} textAnchor="middle" fontFamily={F.mono} fontSize="7.5" fill={C.tx3}>{f.kind}</text>
          </g>
        );
      })}
      {/* edges */}
      {M.solverEdges.map(([a,b])=>edge(a,b))}
      {/* nodes */}
      {M.solvers.map(s=>{ const p=pos[s.id]; if(!p) return null; const on = sel===s.id;
        const stripColor = freshness ? (FRESH_COL[freshness[s.id]||'never']) : stCol[s.status];
        const objText = freshness ? ((liveObj && liveObj[s.id]) || '—') : s.obj;   // live result or honest dash, never the seed obj
        return (
          <g key={s.id} style={{cursor:'pointer'}} onClick={()=>{ onSelect && onSelect(s.id); onNav && !onSelect && onNav(s.go); }}>
            <rect x={p.x} y={p.y} width={nodeW} height={nodeH} fill={on?C.ink:C.paper} stroke={on?C.ac:C.line} strokeWidth={on?3:2}/>
            <rect x={p.x} y={p.y} width="5" height={nodeH} fill={stripColor}/>
            <text x={p.x+13} y={p.y+18} fontFamily={F.disp} fontWeight="800" fontSize="11" fill={on?C.paper:C.tx}>{s.name}</text>
            <text x={p.x+13} y={p.y+32} fontFamily={F.mono} fontSize="8" fill={on?C.ac:C.tx3}>{s.engine} · {objText}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ───────────── useProfile — adaptive planning profile (handoff v2 §7.3) ──
// Setup captures it; stages/spine read it to turn capabilities on/off.
const profileStore = {
  p: (()=>{ try{ return JSON.parse(localStorage.getItem('es_profile')); }catch(e){ return null; } })() || null,
  subs: new Set(),
  get(){ return this.p || (window.M ? M.planningProfile : {}); },
  set(patch){ this.p = { ...this.get(), ...patch };
    try{ localStorage.setItem('es_profile', JSON.stringify(this.p)); }catch(e){}
    this.subs.forEach(f=>f()); },
};
function useProfile(){
  const [,force] = useState(0);
  useEffect(()=>{ const f=()=>force(x=>x+1); profileStore.subs.add(f); return ()=>profileStore.subs.delete(f); }, []);
  const profile = profileStore.get();
  const gate = window.M ? M.profileGate(profile) : {};
  return { profile, gate, setProfile:patch=>profileStore.set(patch) };
}

// ───────────── GateNote — "not needed for your setup" banner (handoff v2 §7.3) ──
// Shown at the top of a capability that the profile switched off — explains WHY
// and links back to Setup, instead of leaving an empty grid.
function GateNote({ children, onNav }){
  return (
    <div style={{display:'flex', alignItems:'center', gap:11, padding:'11px 14px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.tx3}`, background:C.bg3, marginBottom:14}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.tx3, letterSpacing:'.1em'}}>NOT NEEDED</span>
      <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, flex:1, lineHeight:1.4}}>{children}</span>
      {onNav && <button onClick={()=>onNav('setup')} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline', whiteSpace:'nowrap'}}>change in Setup →</button>}
    </div>
  );
}

// ───────────── MethodTag — autopilot (s,S) vs optimized (MILP) (handoff v2 §7.4) ──
function MethodTag({ sku }){
  const m = window.M ? M.itemMethod(sku) : 'optimized';
  const meta = M.methodMeta[m];
  return <Tag c={meta.tag} style={{cursor:'help'}} title={meta.note}>{meta.label}</Tag>;
}

// ───────────── SolverIO — the IO contract line on a result (handoff v2 §7.2) ──
// "came from · feeds" so the planner always knows where an output sits.
function SolverIO({ id }){
  const io = window.M && M.solverIO[id]; if(!io) return null;
  return (
    <div style={{marginTop:8, display:'flex', flexWrap:'wrap', gap:0, border:`2px solid ${C.line}`, fontFamily:F.mono, fontSize:9.5}}>
      {[['ANSWERS', io.answers, C.tx],['FROM', io.from, C.tx2],['FEEDS →', io.feeds, C.a2]].map(([k,v,c],i)=>(
        <div key={i} style={{flex:'1 1 30%', minWidth:130, padding:'6px 9px', borderRight:i<2?`1px solid ${C.line2}`:'none', borderTop:'none'}}>
          <div style={{fontSize:8, letterSpacing:'.12em', color:C.tx3, marginBottom:2}}>{k}</div>
          <div style={{color:c, fontWeight:600, lineHeight:1.35}}>{v}</div>
        </div>
      ))}
    </div>
  );
}

// ───────────── PlanningSpine — ordered solve chain, conditional (handoff v2 §7.1) ──
// Reads the profile: a step its gate switches off renders dimmed + "skipped".
function PlanningSpine({ onNav }){
  const { gate } = useProfile();
  return (
    <div style={{display:'flex', flexWrap:'wrap', gap:0, border:`2px solid ${C.line}`, background:C.paper}}>
      {M.spine.map((s,i)=>{
        const off = s.gate && gate[s.gate];
        return (
          <button key={s.id} onClick={()=>onNav && onNav(s.go)} style={{
            flex:'1 1 0', minWidth:138, textAlign:'left', border:'none',
            borderRight: i<M.spine.length-1?`1px solid ${C.line2}`:'none',
            background: off?C.bg4:'transparent', cursor:'pointer', padding:'9px 11px',
            opacity: off?.55:1, position:'relative',
          }}>
            <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:3}}>
              <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, color:C.onAc, background:off?C.tx3:C.ac, width:17, height:17, display:'grid', placeItems:'center', flexShrink:0}}>{s.n}</span>
              <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, letterSpacing:'.02em'}}>{s.name}</span>
            </div>
            <div style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, lineHeight:1.35}}>{s.out}</div>
            <div style={{marginTop:5, fontFamily:F.mono, fontSize:8, fontWeight:700, letterSpacing:'.04em', color: off?C.dg : s.when==='always'?C.gn : C.a4}}>
              {off ? '✕ SKIPPED · '+s.when : s.when.toUpperCase()}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ───────────── Provenance — the BI trust atom (app_v2 trust layer) ──
// Every figure can declare WHERE it came from, so no number on screen is
// unattributable. Five kinds: input (you typed/imported it), derived
// (computed from other fields), solved (an optimisation output), external
// (an outside source — RBI FX, an uploaded forecast), seed (an illustrative
// default — NOT your data and NOT a solve, so it never reads green/solved).
// `asOf` stamps when; `stale` flags a solved/derived value whose inputs changed.
const _PROV = {
  input:    { i:'⌨', l:'INPUT',    c:C.a2, t:'entered by you or imported' },
  derived:  { i:'ƒ', l:'DERIVED',  c:C.a3, t:'computed from other fields' },
  solved:   { i:'⚙', l:'SOLVED',   c:C.gn, t:'output of an optimisation run' },
  external: { i:'↧', l:'EXTERNAL', c:C.a4, t:'imported from an outside source' },
  seed:     { i:'◇', l:'SEED',     c:C.tx3, t:'illustrative seed default — not your data and not a solve' },
};
function Provenance({ kind='solved', asOf, run, stale, style }){
  const m = _PROV[kind] || _PROV.solved;
  // a Date can't be a React child — coerce defensively (several call sites pass a
  // raw Date, e.g. Logistics' tr.ranAt, which otherwise throws and blanks the tab).
  const asOfStr = (asOf instanceof Date) ? asOf.toLocaleTimeString('en-IN') : asOf;
  return (
    <span title={m.t} style={{
      display:'inline-flex', alignItems:'center', gap:5, padding:'1px 6px',
      border:`1.5px solid ${stale?C.a4:C.line2}`, background: stale?'color-mix(in srgb,var(--a4) 12%,transparent)':C.bg3,
      fontFamily:F.mono, fontSize:8.5, fontWeight:700, letterSpacing:'.06em', whiteSpace:'nowrap', cursor:'help', ...style,
    }}>
      <span style={{color:m.c, fontSize:9.5}}>{m.i}</span>
      <span style={{color:C.tx2}}>{m.l}</span>
      {run && <span style={{color:C.tx3, fontWeight:600}}>· {run}</span>}
      {asOfStr && <span style={{color:C.tx3, fontWeight:400}}>· {asOfStr}</span>}
      {stale && <span style={{color:C.a4, fontWeight:800}}>· STALE</span>}
    </span>
  );
}
// AsOf — bare timestamp chip for any panel header
const AsOf = ({ t, style }) => (
  <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3, letterSpacing:'.04em', whiteSpace:'nowrap', ...style}}>as of {t}</span>
);
// StaleMark — amber banner when a result's inputs changed after the last solve
function StaleMark({ since, onNav, go }){
  return (
    <div style={{display:'flex', alignItems:'center', gap:9, padding:'7px 11px', border:`2px solid ${C.a4}`, borderLeft:`5px solid ${C.a4}`, background:'color-mix(in srgb,var(--a4) 9%,transparent)', marginBottom:10}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, color:C.a4, letterSpacing:'.08em'}}>⚠ STALE</span>
      <span style={{fontFamily:F.body, fontSize:11, color:C.tx2, flex:1}}>Inputs changed{since?` ${since}`:''} since this was last solved — re-run to trust these numbers.</span>
      {go && <button onClick={()=>onNav&&onNav(go)} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline', whiteSpace:'nowrap'}}>re-solve →</button>}
    </div>
  );
}

// ───────────── SeedFence — loud "illustrative seed, NOT a live solve" band (R2 · gate ①) ──
// The quiet Provenance·external·seed chip is right for ONE figure; a whole tab of demo
// numbers (Finance·Cash, Buy-vs-Lease, FX VaR, Scenarios·Cost) needs a band a first-time
// user cannot miss in <2 s — the §3.2 guardrail "a seed must never read as a solve."
// States the numbers are illustrative and points at what to run for the real ones.
function SeedFence({ children, what, onNav, go, goLabel }){
  return (
    <div style={{display:'flex', alignItems:'center', gap:10, padding:'9px 12px', border:`2px solid ${C.a4}`, borderLeft:`5px solid ${C.a4}`, background:'color-mix(in srgb,var(--a4) 9%,transparent)', marginBottom:12}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, color:C.a4, letterSpacing:'.08em', whiteSpace:'nowrap'}}>◇ ILLUSTRATIVE</span>
      <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, flex:1, lineHeight:1.4}}>{children || what || 'Seed figures for layout — not the output of a solve. Run the engine to replace them with your numbers.'}</span>
      {go && <button onClick={()=>onNav&&onNav(go)} style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.a2, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline', whiteSpace:'nowrap'}}>{goLabel||'solve →'}</button>}
    </div>
  );
}

// ───────────── PreviewTag — honest marker for an intentionally inert control (R3 · gate ③) ──
// The honest-affordance rule (P6): no live affordance unless wired. Where a control is
// shown for shape but not yet wired, it renders `disabled` AND carries this tag so the
// dead state is explained, never mysterious. kind: 'preview' (wiring pending),
// 'readonly' (derived/solved elsewhere), 'redirect' (its real home is another tab).
function PreviewTag({ kind='preview', where }){
  const m = {
    preview:  { l:'PREVIEW',         t:'shown for shape — not wired to a solve yet' },
    readonly: { l:'READ-ONLY',       t:'derived/solved elsewhere — not editable here' },
    redirect: { l:'EDIT ELSEWHERE',  t: where ? ('set this on '+where) : 'set this on its home tab' },
  }[kind] || { l:'PREVIEW', t:'' };
  return (
    <span title={m.t} style={{
      display:'inline-flex', alignItems:'center', gap:4, padding:'1px 5px', border:`1.5px dashed ${C.tx3}`,
      background:C.bg3, fontFamily:F.mono, fontSize:8, fontWeight:700, letterSpacing:'.06em', color:C.tx3,
      whiteSpace:'nowrap', cursor:'help',
    }}>{m.l}{kind==='redirect'&&where?` · ${where}`:''}</span>
  );
}

// ───────────── Lineage — the "⛓ lineage" hook (P1 anchor for R1) ──
// The dependency chain exists in code (SOLVE_DEPS / markStale) but is invisible. This is
// the UI hook for it: a dot beside a value's Provenance that opens "what feeds this / what
// this feeds". Phase 1 ships the HOOK (callers pass what they know, or nothing → an honest
// placeholder); Phase 2's parameter registry will resolve `param` against the real
// dependency map so this popover and the stale-cascade tell the same story.
function Lineage({ from, feeds, param, note }){
  const [open, setOpen] = useState(false);
  const has = (from && from.length) || (feeds && feeds.length);
  return (
    <span style={{position:'relative', display:'inline-block'}}>
      <span onClick={()=>setOpen(o=>!o)} title="where this number comes from / goes" style={{
        cursor:'pointer', width:14, height:14, display:'inline-grid', placeItems:'center',
        border:`1.5px solid ${C.line2}`, borderRadius:'50%', fontFamily:F.mono, fontSize:9,
        fontWeight:700, background: open?C.ac:C.bg3, color:C.tx2, lineHeight:1,
      }}>⛓</span>
      {open && (
        <div style={{
          position:'absolute', top:18, left:0, zIndex:45, width:236, background:C.paper,
          border:`2px solid ${C.line}`, boxShadow:`5px 5px 0 ${C.ink}`, padding:'9px 11px',
          fontFamily:F.body, fontSize:11, lineHeight:1.5, color:C.tx,
        }}>
          {has ? (
            <>
              {from && from.length>0 && <><div style={{fontFamily:F.mono, fontSize:8, letterSpacing:'.12em', color:C.tx3, marginBottom:3}}>FED BY</div><div style={{marginBottom:7, color:C.tx2}}>{from.join(' · ')}</div></>}
              {feeds && feeds.length>0 && <><div style={{fontFamily:F.mono, fontSize:8, letterSpacing:'.12em', color:C.tx3, marginBottom:3}}>FEEDS</div><div style={{color:C.a2}}>{feeds.join(' · ')}</div></>}
            </>
          ) : (
            <div style={{color:C.tx3, fontStyle:'italic'}}>{note || 'Full dependency map arrives in the governance pass (Phase 2): this number’s single home and every consumer will be listed here.'}</div>
          )}
        </div>
      )}
    </span>
  );
}

// ───────────── ParamRegistry — the governed-parameter registry (P2 · governance) ──
// The single inventory of every governed input: live value, provenance (seed vs your
// override), the stale-cascade TOKEN it travels on (the SAME token SOLVE_DEPS uses, so
// the registry and the cascade tell ONE story), what it feeds, and a jump to its editor.
// Built ON the P1 contract — nothing here is faked: value + provenance are read LIVE from
// state by the caller; an un-edited param reads 'seed', never a phantom solve. rows[] =
// { group, param, value, seed, prov:'seed'|'override'|'derived'|'solved', token, feeds:[],
//   from:[], editTab, editLabel }.
function ParamRegistry({ rows, onNav }){
  const groups = [];
  (rows||[]).forEach(r=>{ let g=groups.find(x=>x.name===r.group); if(!g){ g={name:r.group, items:[]}; groups.push(g); } g.items.push(r); });
  const provTone = { seed:'w', override:'b', derived:'v', solved:'g' };
  const GTC = '1.5fr 0.9fr auto 1.2fr auto';
  return (
    <div style={{border:`2px solid ${C.line}`, background:C.paper}}>
      <div style={{display:'grid', gridTemplateColumns:GTC, gap:8, fontFamily:F.mono, fontSize:8, letterSpacing:'.1em', color:C.tx3, background:C.bg3, borderBottom:`2px solid ${C.line}`, padding:'5px 11px'}}>
        <span>PARAMETER · TOKEN</span><span>VALUE</span><span>PROVENANCE</span><span>FEEDS</span><span>EDIT</span>
      </div>
      {groups.map((g,gi)=>(
        <div key={gi}>
          <div style={{fontFamily:F.disp, fontSize:9.5, fontWeight:800, textTransform:'uppercase', letterSpacing:'.06em', color:C.tx2, background:C.bg2, padding:'4px 11px', borderBottom:`1px solid ${C.line2}`}}>{g.name}</div>
          {g.items.map((r,ri)=>(
            <div key={ri} style={{display:'grid', gridTemplateColumns:GTC, gap:8, alignItems:'center', padding:'7px 11px', borderBottom:`1px solid ${C.line2}`}}>
              <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx}}>{r.param}{r.token && <span style={{marginLeft:6, fontFamily:F.mono, fontSize:8, color:C.tx3}} title="stale-cascade token — the dependency key SOLVE_DEPS uses for this input">·{r.token}</span>}</span>
              <span className="num" style={{fontFamily:F.disp, fontSize:12, fontWeight:700, color:C.tx}}>{r.value}</span>
              <span style={{display:'flex', alignItems:'center', gap:5}}><Tag c={provTone[r.prov]||'w'}>{r.prov}</Tag>{r.prov==='override' && r.seed!=null && <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>seed {r.seed}</span>}</span>
              <span style={{display:'flex', alignItems:'center', gap:5}}>
                <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2}}>{(r.feeds||[]).length} solve{(r.feeds||[]).length===1?'':'s'}</span>
                {(r.feeds||[]).length>0 && <Lineage feeds={r.feeds} from={r.from}/>}
              </span>
              <span>{r.editTab && <button onClick={()=>onNav&&onNav(r.editTab)} style={{cursor:'pointer', border:`1.5px solid ${C.ac}`, background:'transparent', color:C.ac, fontFamily:F.mono, fontSize:8.5, fontWeight:700, padding:'2px 7px', whiteSpace:'nowrap'}}>{r.editLabel||'edit →'}</button>}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ───────────── SolverInput — governed solver parameter (W0 · P3 · no-fake) ──
// The single input surface every solver parameter should use. It is honest in
// three ways the prototype NumInput is not (CRITIQUE_R2 Part D · "no fabricated
// defaults", and D-DEC-1: a seeded rate the user may override):
//   (a) PROVENANCE — a seed/default value carries an EXTERNAL·seed badge and
//       renders italic/dim until the user edits it, then flips to INPUT (user).
//   (b) VALIDATION — checks required / min / max / integer and shows the breach
//       inline in red; an out-of-range value never passes silently to a solver.
//   (c) NO FAKE — with no seed and nothing entered it shows an explicit
//       "not set" state, never a made-up number. Clearing a user value resets
//       to the seed (so "revert to default" is just emptying the field).
// value = the user's stored value (undefined/'' when unset); seed = the default.
function SolverInput({ label, hint, value, seed, onChange, min, max, required,
                      suffix, prefix, w, span, integer }){
  const hasUser = value!==undefined && value!==null && value!=='';
  const seedHas = seed!==undefined && seed!==null && seed!=='';
  const isSeed  = !hasUser && seedHas;
  const empty   = !hasUser && !seedHas;
  const [buf, setBuf] = useState(hasUser ? String(value) : '');
  useEffect(()=>{ setBuf(hasUser ? String(value) : ''); }, [value]);   // external sync
  const display = isSeed ? String(seed) : buf;
  // validate the effective number
  const eff = hasUser ? Number(buf) : (seedHas ? Number(seed) : NaN);
  let err = null;
  if(required && empty)               err = 'required';
  else if(hasUser && buf!=='' && Number.isNaN(eff)) err = 'not a number';
  else if(!Number.isNaN(eff)){
    if(min!=null && eff<min)          err = `min ${min}`;
    else if(max!=null && eff>max)     err = `max ${max}`;
    else if(integer && !Number.isInteger(eff)) err = 'whole number';
  }
  const onIn = (e)=>{ const v=e.target.value; setBuf(v);
    if(v==='') return onChange('');
    const n=Number(v); onChange(Number.isNaN(n)?v:n); };
  return (
    <label style={{display:'flex', flexDirection:'column', gap:4, gridColumn: span?`span ${span}`:'auto', minWidth:0}}>
      <span style={{display:'flex', alignItems:'center', gap:6, flexWrap:'wrap'}}>
        <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.08em', color:C.tx3, textTransform:'uppercase'}}>{label}</span>
        {isSeed && <Provenance kind="external" run="seed" style={{padding:'0 4px', fontSize:7.5}}/>}
        {hasUser && <Provenance kind="input" style={{padding:'0 4px', fontSize:7.5}}/>}
      </span>
      {empty ? (
        <span style={{display:'inline-flex', alignItems:'center', height:30, border:`2px dashed ${C.line2}`, background:C.bg3, padding:'0 8px', fontFamily:F.mono, fontSize:10, color:C.tx3, width:w||'auto'}}>not set — enter a value</span>
      ) : (
        <span style={{display:'inline-flex', alignItems:'center', border:`2px solid ${err?C.dg:(isSeed?C.line2:C.line)}`, background: isSeed?C.bg3:C.paper, height:30, width:w||'auto'}}>
          {prefix && <span style={{padding:'0 0 0 8px', fontFamily:F.mono, fontSize:11, color:C.tx3}}>{prefix}</span>}
          <input value={display} onChange={onIn} className="num" style={{
            border:'none', background:'transparent', color: isSeed?C.tx2:C.tx, fontFamily:F.disp, fontWeight:600,
            fontSize:13, padding:'0 8px', width:'100%', minWidth:0, outline:'none', fontStyle: isSeed?'italic':'normal',
          }}/>
          {suffix && <span style={{padding:'0 8px 0 0', fontFamily:F.mono, fontSize:10, color:C.tx3}}>{suffix}</span>}
        </span>
      )}
      {err
        ? <span style={{fontFamily:F.mono, fontSize:8.5, color:C.dg, fontWeight:700}}>⚠ {err}</span>
        : isSeed
          ? <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>using default · edit to override</span>
          : (hint && <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{hint}</span>)}
    </label>
  );
}

// ───────────── StageContext — the "what am I looking at" strip (W0 · P5) ──
// One consistent orientation band under a stage's StageHeader: which item ·
// which horizon/grain · as-of when. Fixes the entry-point ambiguity CRITIQUE_R2
// Part D flagged (Plan/Finance/Scenarios had no item/period anchor). `item` is
// optional (item-agnostic tabs omit it); `asOf` absent ⇒ honest "not yet solved".
function StageContext({ item, asOf, stale, extra }){
  const { planning } = (typeof usePlanning==='function') ? usePlanning() : { planning:null };
  const grain = (planning && planning.timeGrain) || 'period';
  const horizon = planning && planning.horizonLength;
  const cell = (k,v,c)=> (
    <span style={{display:'inline-flex', alignItems:'baseline', gap:5}}>
      <span style={{fontFamily:F.mono, fontSize:8.5, letterSpacing:'.1em', color:C.tx3}}>{k}</span>
      <span style={{fontFamily:F.disp, fontSize:11, fontWeight:800, color:c||C.tx}}>{v}</span>
    </span>
  );
  return (
    <div style={{display:'flex', alignItems:'center', gap:16, flexWrap:'wrap', padding:'7px 18px', borderBottom:`2px solid ${C.line}`, background:C.bg3}}>
      {item && cell('ITEM', item.name || item.sku || item.id, C.tx)}
      {cell('HORIZON', horizon ? `${horizon} × ${grain}` : String(grain).toUpperCase())}
      {extra}
      <span style={{marginLeft:'auto', display:'inline-flex', alignItems:'center', gap:8}}>
        {stale && <Tag c="r">stale</Tag>}
        {asOf ? <AsOf t={asOf}/> : <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>not yet solved</span>}
      </span>
    </div>
  );
}

// ───────────── ScopeBanner — loud "what am I editing" band (review Theme 3) ──
// Item-scoped tabs (Products/Network/Sourcing/Demand) felt like disconnected cards
// because the item selector was too quiet — "no clue what product I'm looking at"
// recurs all over the notes. This is the loud answer: a high-contrast band that
// states the entity every card below is scoped to, with an optional kind chip and
// right-slot (e.g. a switcher or count). Pure presentation, no state.
function ScopeBanner({ kind, name, code, sub, right, tone }){
  const bg = tone==='accent' ? C.ac : C.ink;
  const fg = tone==='accent' ? C.onAc : C.paper;
  return (
    <div style={{display:'flex', alignItems:'center', gap:12, padding:'9px 14px', background:bg, color:fg,
      border:`2px solid ${C.line}`, marginBottom:14, flexWrap:'wrap'}}>
      <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.14em', color: tone==='accent'?C.ink:C.ac}}>EDITING ▸</span>
      {kind && <span style={{fontFamily:F.mono, fontSize:9, fontWeight:700, padding:'2px 6px', border:`1.5px solid ${tone==='accent'?C.ink:C.ac}`, color: tone==='accent'?C.ink:C.ac, textTransform:'uppercase'}}>{kind}</span>}
      <span style={{fontFamily:F.disp, fontSize:15, fontWeight:900, letterSpacing:'.01em'}}>{name}</span>
      {code && <span style={{fontFamily:F.mono, fontSize:10, opacity:.7}}>{code}</span>}
      {sub && <span style={{fontFamily:F.mono, fontSize:9.5, opacity:.6}}>{sub}</span>}
      {right && <span style={{marginLeft:'auto'}}>{right}</span>}
    </div>
  );
}

// ───────────── ActivityLog — the change-log surface (review Theme 5) ──
// One chronological reader of the immutable event trail (useEvents) — the
// "record a change as of a date, see its impact" ledger the notes asked for in
// Products (price changes), Demand, and Sourcing. Reads only; the trail is written
// by editProductAttr/editPartAttr/logEvent across the app. `filter` narrows by
// event type or target; `limit` caps rows (newest first); `compact` for sidebars.
const _EVENT_META = {
  override:    { icon:'✎', label:'edit',        c:C.a2 },
  commit:      { icon:'✔', label:'commit',      c:C.gn },
  replan:      { icon:'↻', label:'re-plan',     c:C.a3 },
  cancel:      { icon:'✕', label:'cancel',      c:C.dg },
  actuals:     { icon:'◉', label:'actuals',     c:C.a4 },
  template_apply:{ icon:'▦', label:'template',  c:C.a3 },
  rec_apply:   { icon:'★', label:'applied rec', c:C.gn },
  scenario_create:{ icon:'⎘', label:'scenario', c:C.a2 },
  scenario_run:{ icon:'⚙', label:'scenario run',c:C.gn },
};
function ActivityLog({ filter, limit, compact, title, empty }){
  const { events } = (typeof useEvents==='function') ? useEvents() : { events:[] };
  let rows = (events||[]).slice();
  if(typeof filter === 'function') rows = rows.filter(filter);
  else if(typeof filter === 'string') rows = rows.filter(e=>e.type===filter || e.target===filter);
  rows = rows.reverse();                              // newest first
  if(limit) rows = rows.slice(0, limit);
  const fmt = (ts)=>{ try{ const d=new Date(ts); return d.toLocaleDateString(undefined,{day:'2-digit',month:'short'})+' '+d.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}); }catch(e){ return ts; } };
  const detail = (e)=>{
    if(!e.detail) return '';
    if(e.detail.fields) return e.detail.fields.join(', ') + (e.detail.to ? ' → '+Object.values(e.detail.to).join(', ') : '');
    if(e.detail.name) return e.detail.name;
    try{ return Object.entries(e.detail).slice(0,2).map(([k,v])=>`${k}:${typeof v==='object'?'…':v}`).join(' · '); }catch(x){ return ''; }
  };
  return (
    <div>
      {title && <SubLabel>{title}{rows.length?` · ${rows.length}`:''}</SubLabel>}
      {!rows.length ? (
        <div style={{padding:'12px', textAlign:'center', fontFamily:F.mono, fontSize:10, color:C.tx3, border:`2px dashed ${C.line2}`}}>{empty||'no activity yet — edits and solves you make are logged here with a timestamp.'}</div>
      ) : (
        <div style={{display:'flex', flexDirection:'column', border:`2px solid ${C.line}`}}>
          {rows.map((e,i)=>{ const m = _EVENT_META[e.type] || { icon:'·', label:e.type, c:C.tx3 };
            return (
              <div key={e.id||i} style={{display:'flex', alignItems:'center', gap:9, padding: compact?'5px 9px':'7px 11px', borderBottom:i<rows.length-1?`1px solid ${C.line2}`:'none', background:i%2?C.bg3:C.paper}}>
                <span style={{color:m.c, fontSize:12, width:14, textAlign:'center', flexShrink:0}}>{m.icon}</span>
                <span style={{fontFamily:F.mono, fontSize:8.5, fontWeight:700, letterSpacing:'.06em', color:m.c, textTransform:'uppercase', width:74, flexShrink:0}}>{m.label}</span>
                <span style={{fontFamily:F.disp, fontSize:11, fontWeight:700, color:C.tx, flexShrink:0}}>{e.target||'—'}</span>
                <span style={{fontFamily:F.mono, fontSize:10, color:C.tx2, flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{detail(e)}</span>
                <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3, flexShrink:0}}>{fmt(e.ts)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── (R14) ModelIO — real Export/Import of the live editable model (was an inert
// header button). Export downloads exportModelJson(); Import reads a chosen .json
// file and applies it via importModelJson(). Shared by Products/Setup/Network headers.
function ModelIO({ label }){
  const fileRef = useRef(null);
  const [msg, setMsg] = useState(null);
  const flash = (t)=>{ setMsg(t); setTimeout(()=>setMsg(null), 4000); };
  const onExport = ()=>{
    if(typeof exportModelJson!=='function') return;
    downloadText('es-model.json', exportModelJson(), 'application/json');
    flash('exported es-model.json');
  };
  const onFile = (e)=>{
    const f = e.target.files && e.target.files[0]; if(!f) return;
    const r = new FileReader();
    r.onload = ()=>{ const res = importModelJson(String(r.result));
      flash(res.ok ? `imported ${res.products} SKUs · ${res.parts} parts` : `⚠ ${res.error}`); };
    r.readAsText(f); e.target.value='';
  };
  return (
    <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
      {msg && <span style={{fontFamily:F.mono, fontSize:9, color:C.tx3}}>{msg}</span>}
      <Btn kind="secondary" sm onClick={onExport}>⬇ Export</Btn>
      <Btn kind="secondary" sm onClick={()=>fileRef.current&&fileRef.current.click()}>⤓ {label||'Import'}</Btn>
      <input ref={fileRef} type="file" accept=".json,application/json" style={{display:'none'}} onChange={onFile}/>
    </span>
  );
}
// ReportExport — real PDF download from /api/report/pdf (reportlab). Was inert.
function ReportExport(){
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(null);
  const go = async ()=>{ setBusy(true); setErr(null);
    try{ await reportPdf(); }catch(e){ setErr(String(e.message||e)); } finally{ setBusy(false); } };
  return (
    <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
      {err && <span style={{fontFamily:F.mono, fontSize:9, color:C.dg}}>⚠ {err}</span>}
      <Btn kind="secondary" sm onClick={go}>{busy?'building…':'📄 Report PDF'}</Btn>
    </span>
  );
}

// ───────────── SolverExplain — plain-language "what is this?" on a solver card ──
// Batch 5 (🧭). The terse SolverIO grid (ANSWERS·FROM·FEEDS) is for planners who
// already speak the jargon. This is the one friendly sentence a first-time user
// needs — built from the same Fact-4 roster (M.solverIO) so it can never drift from
// what the engine actually does. SOLVER_PLAIN supplies the layman wording; any id
// without one falls back to the roster's `answers` so every engine still explains.
const SOLVER_PLAIN = {
  forecast:   'Looks at your past sales and predicts how much you’ll sell in each upcoming period.',
  aggregate:  'Decides, month by month, whether to run the factory at a steady pace or chase demand — and how many people that needs.',
  disaggregate:'Splits the family-level plan back down to a number for each individual SKU.',
  reconcile:  'Makes the sales plan and the operations plan agree on one committed set of numbers.',
  profitmix:  'When you can’t make everything, picks the product mix that earns the most profit from the capacity you have.',
  procurement:'Works out which raw materials to buy, how much, from which supplier, and when each order must be placed.',
  production: 'Lays the build out over time on each line, respecting lot sizes, changeovers and capacity.',
  sequencing: 'Puts the day’s jobs in the best order on a line to minimise changeover time.',
  lotsizing:  'Finds the order quantity that balances setup cost against the cost of holding inventory.',
  transport:  'Chooses how to ship finished goods across your lanes and carriers at the lowest cost.',
  allocation: 'Decides which distribution centre serves which customer from the stock on hand.',
  consolidate:'Merges small shipments onto shared trucks to cut freight cost.',
  montecarlo: 'Runs the committed plan through thousands of “what could go wrong” scenarios to see how fragile it is.',
  cvar:       'Sizes the worst-case (tail) cost so you can plan for bad luck, not just the average.',
  capital:    'Tells you whether spending money to add capacity actually pays for itself.',
  capital_capacity:'Works out how much extra capacity is worth adding before the payback stops.',
  meionet:    'Pools safety stock across products and sites so you hold less inventory for the same service.',
};
function SolverExplain({ id }){
  const io = window.M && M.solverIO[id];
  const plain = SOLVER_PLAIN[id] || (io && io.answers ? `Works out ${io.answers}.` : null);
  if(!plain) return null;
  return (
    <div style={{display:'flex', alignItems:'flex-start', gap:10, padding:'9px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${C.a2}`, background:C.bg3, marginBottom:12}}>
      <span style={{fontFamily:F.mono, fontSize:9, fontWeight:800, color:C.a2, letterSpacing:'.08em', whiteSpace:'nowrap', marginTop:1}}>WHAT IS THIS?</span>
      <span style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.45, flex:1}}>
        {plain}{io && <span style={{color:C.tx3}}> · it reads {io.from} and its answer feeds {io.feeds}.</span>}
      </span>
    </div>
  );
}

// ───────────── OnboardingWizard — first-run greeting that sets the profile ──
// Batch 5 (🧭, Theme 2). A new user shouldn't meet all 16 engines at once. On the
// first load (no es_onboarded flag) this greeting asks the same six profile
// questions Setup holds, in plain words, sets the profile (which gates the spine),
// and shows live how many capabilities that hides. Skippable; re-answerable any time
// in Setup. Pure UI over the existing profileStore — no new state model.
const ONB_Q = [
  { k:'makePolicy',     label:'How do you fulfil customer orders?',  opts:[['MTS','Make to stock'],['MTS+MTO','A bit of both'],['MTO','Make to order'],['ATO','Assemble to order']] },
  { k:'capacity',       label:'Is factory capacity tight or ample?', opts:[['tight','Usually tight'],['ample','Plenty spare']] },
  { k:'imports',        label:'Do you import raw materials?',        opts:[[true,'Yes, we import'],[false,'All domestic']] },
  { k:'lines',          label:'How many production lines?',          opts:[['1','Just one'],['many','Several']] },
  { k:'distribution',   label:'One site, or a distribution network?',opts:[['single','Single site'],['network','A network']] },
  { k:'externalForecast',label:'Who makes your demand forecast?',    opts:[[false,'We forecast here'],[true,'It’s supplied to us']] },
];
function OnboardingWizard(){
  const { profile, gate, setProfile } = useProfile();
  const [open, setOpen] = useState(()=>{ try{ return !localStorage.getItem('es_onboarded'); }catch(e){ return true; } });
  if(!open) return null;
  const close = ()=>{ try{ localStorage.setItem('es_onboarded','1'); }catch(e){} setOpen(false); };
  const offList = [
    gate.profitmix    && 'Profit-mix + seasonal Aggregate',
    gate.sequencing   && 'Sequencing',
    gate.transport    && 'Transport / Logistics',
    gate.landed       && 'Landed cost · FX · Incoterms',
    gate.demandModels && 'Demand model-competition',
  ].filter(Boolean);
  const Seg = ({ k, opts }) => (
    <div style={{display:'flex', border:`2px solid ${C.line}`}}>
      {opts.map(([v,l],i)=>(
        <button key={String(v)} onClick={()=>setProfile({ [k]:v })} style={{
          flex:1, textAlign:'center', padding:'7px 8px', fontFamily:F.mono, fontSize:9.5, fontWeight:700,
          border:'none', borderRight:i<opts.length-1?`2px solid ${C.line}`:'none', cursor:'pointer',
          background: profile[k]===v?C.ink:C.paper, color: profile[k]===v?C.ac:C.tx3, whiteSpace:'nowrap',
        }}>{profile[k]===v?'● ':'○ '}{l}</button>
      ))}
    </div>
  );
  return (
    <div style={{position:'fixed', inset:0, zIndex:9999, background:'rgba(0,0,0,.5)', display:'flex', alignItems:'flex-start', justifyContent:'center', overflowY:'auto', padding:'40px 18px'}}>
      <div style={{width:'100%', maxWidth:680, background:C.paper, border:`2px solid ${C.line}`, boxShadow:'0 12px 40px rgba(0,0,0,.3)'}}>
        <div style={{padding:'14px 18px', borderBottom:`2px solid ${C.line}`, background:C.card, display:'flex', alignItems:'center', gap:10}}>
          <span style={{fontSize:20}}>👋</span>
          <div>
            <div style={{fontFamily:F.disp, fontSize:15, fontWeight:900, letterSpacing:'.02em'}}>Welcome — let’s right-size the workspace</div>
            <div style={{fontFamily:F.mono, fontSize:9.5, color:C.tx3, marginTop:2}}>Six quick answers so you only see the engines your operation actually needs. Change them any time in Setup.</div>
          </div>
        </div>
        <div style={{padding:'16px 18px'}}>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'12px 16px'}}>
            {ONB_Q.map(q=>(
              <div key={q.k}>
                <div style={{fontFamily:F.mono, fontSize:9.5, fontWeight:700, color:C.tx2, marginBottom:4}}>{q.label}</div>
                <Seg k={q.k} opts={q.opts}/>
              </div>
            ))}
          </div>
          <div style={{marginTop:14, padding:'10px 12px', border:`2px solid ${C.line}`, borderLeft:`5px solid ${offList.length?C.a4:C.gn}`, background:C.bg3}}>
            {offList.length ? (
              <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.5}}>
                Based on your answers we’ll <b>hide {offList.length} capabilit{offList.length===1?'y':'ies'}</b> you don’t need: <span style={{color:C.tx3}}>{offList.join(' · ')}</span>. They stay one toggle away in Setup.
              </div>
            ) : (
              <div style={{fontFamily:F.body, fontSize:11.5, color:C.tx2, lineHeight:1.5}}>Your answers keep <b>every engine on</b> — the full S&OP spine. You can trim it later in Setup.</div>
            )}
          </div>
        </div>
        <div style={{padding:'12px 18px', borderTop:`2px solid ${C.line}`, display:'flex', alignItems:'center', gap:10}}>
          <button onClick={close} style={{fontFamily:F.mono, fontSize:10, fontWeight:700, color:C.tx3, background:'transparent', border:'none', cursor:'pointer', textDecoration:'underline'}}>Skip — show me everything</button>
          <span style={{marginLeft:'auto'}}><Btn kind="accent" onClick={close}>Start planning →</Btn></span>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  C, F, BUILD, Box, Sep, Blk, KPI, KpiRow, Tag, Badge, Btn, SectionInfo, DevNote, Card,
  DataTable, Field, NumInput, TextInput, Select, Advanced, SubTabNav, StageHeader,
  MiniBar, Spark, Ring, Grid, SubLabel,
  useActiveItem, ItemSelector, Reading, StageSection, PrereqNote, SolverNetwork,
  useProfile, GateNote, MethodTag, SolverIO, PlanningSpine,
  Provenance, AsOf, StaleMark, SolverInput, StageContext,
  SeedFence, PreviewTag, Lineage, ParamRegistry,
  ScopeBanner, ActivityLog, SolverExplain, OnboardingWizard,
  ModelIO, ReportExport,
});
