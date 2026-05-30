// ════════════════════════════════════════════════════════════════════════
// lib.jsx — shared design-system atoms (handoff §1 component kit)
// Brutalist mono grid. All color via CSS vars so themes (mono/noir/sepia)
// swap with zero component changes. Exported to window for all stages.
// ════════════════════════════════════════════════════════════════════════
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

// ─────────────────────── SectionInfo ⓘ popover (handoff: keep these) ───────
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

// ─────────────────────── DevNote (Claude Code handoff annotation) ─────────
function DevNote({ comp, props, state, note }) {
  const [open, setOpen] = useState(false);
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

// ─────────────────────── Card (handoff card anatomy) ──────────────────────
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

// ─────────────────────── DataTable ────────────────────────────────────────
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

// ─────────────────────── Field + NumInput (shared building blocks) ─────────
function Field({ label, hint, children, span }) {
  return (
    <label style={{display:'flex', flexDirection:'column', gap:4, gridColumn: span?`span ${span}`:'auto', minWidth:0}}>
      <span style={{fontFamily:F.mono, fontSize:9, letterSpacing:'.08em', color:C.tx3, textTransform:'uppercase'}}>{label}</span>
      {children}
      {hint && <span style={{fontFamily:F.mono, fontSize:8.5, color:C.tx3}}>{hint}</span>}
    </label>
  );
}
function NumInput({ value, suffix, prefix, disabled, w }) {
  return (
    <span style={{display:'inline-flex', alignItems:'center', border:`2px solid ${disabled?C.line2:C.line}`, background:disabled?C.bg3:C.paper, height:30, width:w||'auto'}}>
      {prefix && <span style={{padding:'0 0 0 8px', fontFamily:F.mono, fontSize:11, color:C.tx3}}>{prefix}</span>}
      <input defaultValue={value} disabled={disabled} className="num" style={{
        border:'none', background:'transparent', color:C.tx, fontFamily:F.disp, fontWeight:600, fontSize:13,
        padding:'0 8px', width:'100%', minWidth:0, outline:'none',
      }}/>
      {suffix && <span style={{padding:'0 8px 0 0', fontFamily:F.mono, fontSize:10, color:C.tx3}}>{suffix}</span>}
    </span>
  );
}
function TextInput({ value, disabled, w }) {
  return (
    <input defaultValue={value} disabled={disabled} style={{
      border:`2px solid ${disabled?C.line2:C.line}`, background:disabled?C.bg3:C.paper, color:C.tx,
      fontFamily:F.disp, fontWeight:600, fontSize:13, padding:'6px 8px', height:30, width:w||'100%', outline:'none',
    }}/>
  );
}
function Select({ value, options, disabled, w }) {
  return (
    <select defaultValue={value} disabled={disabled} style={{
      border:`2px solid ${disabled?C.line2:C.line}`, background:disabled?C.bg3:C.paper, color:C.tx,
      fontFamily:F.disp, fontWeight:600, fontSize:12, padding:'6px 8px', height:30, width:w||'100%', outline:'none',
      appearance:'none', backgroundImage:'none', cursor:'pointer',
    }}>{(options||[value]).map((o,i)=><option key={i}>{o}</option>)}</select>
  );
}

// ─────────────────────── Advanced ▸ progressive disclosure (P5) ────────────
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

// ─────────────────────── SubTabNav (P3: the Finance pattern) ───────────────
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

// ─────────────────────── StageHeader (title + kicker for each stage) ───────
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

// ─────────────────────── mini-viz helpers ─────────────────────────────────
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

Object.assign(window, {
  C, F, Box, Sep, Blk, KPI, KpiRow, Tag, Badge, Btn, SectionInfo, DevNote, Card,
  DataTable, Field, NumInput, TextInput, Select, Advanced, SubTabNav, StageHeader,
  MiniBar, Spark, Ring, Grid, SubLabel,
});
