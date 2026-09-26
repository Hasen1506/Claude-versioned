// Machines, lines and crews: when each one works (named shifts with breaks, on which weekdays), how that changes over
// time (a second shift from a date, a week of maintenance), and the hours it offers week by week. The arithmetic
// mirrors the engine's (engine/scp/time/capacity.py), so what is shown here is what MRP, the capacity plan and the
// shop floor schedule use.
import { useMemo, useState } from "react";
import type { Dataset, Resource } from "../api/types";
import { Badge, Empty, Panel, StageHeader } from "../components/ui";
import { day, qty } from "../lib/format";
import { useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { store, useStore } from "../state/store";

type Shift = NonNullable<Resource["shifts"]>[number];
type Change = NonNullable<Resource["capacity_changes"]>[number];
const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY = 86400000;
const hm = (s: string) => { const [h, m] = s.split(":").map(Number); return h + m / 60; };
const toT = (iso: string) => new Date(iso + "T00:00:00Z").getTime();
const iso = (t: number) => new Date(t).toISOString().slice(0, 10);
const weekday = (t: number) => (new Date(t).getUTCDay() + 6) % 7;

function lengthOf(s: Shift) { const x = ((hm(s.end) - hm(s.start)) % 24 + 24) % 24; return x || 24; }
function netOf(s: Shift) { return lengthOf(s) - (s.break_minutes ?? 0) / 60; }
function windowsOf(s: Shift): [number, number][] {
  const a = hm(s.start), b = a + lengthOf(s), brk = (s.break_minutes ?? 0) / 60;
  if (brk <= 0) return [[a, b]];
  const bs = s.break_start ? a + ((hm(s.break_start) - a) % 24 + 24) % 24 : a + (lengthOf(s) - brk) / 2;
  return ([[a, bs], [bs + brk, b]] as [number, number][]).filter(([x, y]) => y > x + 1e-9);
}
const runsOn = (s: Shift, wd: number) => !s.weekdays?.length || s.weekdays.includes(wd);

/** The resource's calendar: its own, else its place's, else the company default, else Monday to Friday. */
export function calendarOf(ds: Dataset, r: Resource) {
  const loc = (ds.locations ?? []).find((l) => l.id === r.location);
  const id = r.calendar || loc?.calendar || ds.settings.default_calendar;
  const cal = (ds.calendars ?? []).find((c) => c.id === id);
  const work = new Set(cal?.workdays ?? [0, 1, 2, 3, 4]);
  const hol = new Set(cal?.holidays ?? []);
  return { name: cal ? cal.name || cal.id : "Monday to Friday", isWork: (t: number) => work.has(weekday(t)) && !hol.has(iso(t)) };
}

function changeOn(r: Resource, t: number): Change | undefined {
  const d = iso(t);
  let hit: Change | undefined;
  for (const c of r.capacity_changes ?? []) if (c.valid_from <= d && (!c.valid_to || d <= c.valid_to)) hit = c;
  return hit;
}

/** One day's working windows (clock hours from midnight), units and efficiency — as the engine computes them. */
export function dayCap(r: Resource, isWork: (t: number) => boolean, t: number, dayStart: number) {
  const ch = changeOn(r, t);
  const units = ch?.units ?? r.units ?? 1;
  const eff = ch?.efficiency ?? r.efficiency ?? 0.85;
  if (!isWork(t) || units <= 0) return { wins: [] as [number, number][], units, eff, ch };
  let shifts = ch?.shifts ?? r.shifts ?? [];
  let span = (r.shifts_per_day ?? 1) * (r.hours_per_shift ?? 8);
  if (ch && ch.shifts == null && ch.shifts_per_day != null) { shifts = []; span = ch.shifts_per_day * (r.hours_per_shift ?? 8); }
  const wins = shifts.length ? shifts.filter((s) => runsOn(s, weekday(t))).flatMap(windowsOf).sort((a, b) => a[0] - b[0])
    : [[dayStart, dayStart + span] as [number, number]];
  const merged: [number, number][] = [];
  for (const [a, b] of wins) {
    const last = merged[merged.length - 1];
    if (last && a <= last[1] + 1e-9) last[1] = Math.max(last[1], b); else merged.push([a, b]);
  }
  return { wins: merged, units, eff, ch };
}
export const hoursOf = (c: ReturnType<typeof dayCap>) => c.wins.reduce((a, [x, y]) => a + y - x, 0) * c.eff * c.units;

export function Machines({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset);
  if (!ds) return null;
  return <MachinesPage ds={ds} sel={route[1]} />;
}

function MachinesPage({ ds, sel }: { ds: Dataset; sel?: string }) {
  const nm = useNames();
  const list = ds.resources ?? [];
  const r = list.find((x) => x.id === sel) ?? null;
  const byPlace = useMemo(() => {
    const m = new Map<string, Resource[]>();
    for (const x of list) m.set(x.location, [...(m.get(x.location) ?? []), x]);
    return [...m.entries()];
  }, [list]);
  const usual = (x: Resource) => x.shifts?.length
    ? (() => { const days = [0, 1, 2, 3, 4, 5, 6].map((d) => x.shifts!.filter((s) => runsOn(s, d)).reduce((a, s) => a + netOf(s), 0)).filter((h) => h > 0); return days.length ? days.reduce((a, b) => a + b) / days.length : 0; })()
    : (x.shifts_per_day ?? 1) * (x.hours_per_shift ?? 8);
  return (
    <div>
      <StageHeader title="Machines & shifts" kicker={<>When each machine, line or crew works, and how much it can do. The supply plan, the capacity plan
        and the shop floor schedule all read these hours.</>}
        how={<>Like a work centre's capacity in SAP: named shifts with their clock times and breaks, the weekdays each runs,
          and <b>capacity changes</b> for a period (a second shift from November, a week of maintenance). Productive hours =
          shift hours × efficiency × machines or people.</>} />
      <div className="content split" style={{ display: "grid", gridTemplateColumns: "minmax(220px, 300px) minmax(0, 1fr)", gap: 16 }}>
        <Panel flush title="Machines, lines and crews">
          {!list.length ? <div style={{ padding: 14 }} className="muted small">None yet. Add one when you say how a product is made
            (<a href={href("setup", "products")}>Set up → Products</a>), or in <a href={href("data", "resources")}>Master data</a>.</div> : (
            <table className="t">
              <tbody>{byPlace.flatMap(([loc, rs]) => [
                <tr key={loc}><td colSpan={2} className="faint small" style={{ paddingTop: 10 }}>{nm.loc(loc)}</td></tr>,
                ...rs.map((x) => <tr key={x.id} className={`clickable ${x.id === sel ? "selected" : ""}`} onClick={() => go("machines", x.id)}>
                  <td><a href={href("machines", x.id)} onClick={(e) => e.stopPropagation()}>{x.name || x.id}</a>
                    {x.capacity_changes?.length ? <span className="faint small"> · {x.capacity_changes.length} change{x.capacity_changes.length === 1 ? "" : "s"}</span> : null}</td>
                  <td className="num small">{x.units ?? 1} × {qty(usual(x))} h</td></tr>),
              ])}</tbody>
            </table>
          )}
        </Panel>
        {r ? <ResourceDetail ds={ds} r={r} /> : <Panel><Empty title="Choose one">
          <p>Pick a machine, line or crew to see and change when it works.</p></Empty></Panel>}
      </div>
    </div>
  );
}

function ResourceDetail({ ds, r }: { ds: Dataset; r: Resource }) {
  const nm = useNames();
  const plan = useStore((s) => s.runs.plan.data);
  const cal = calendarOf(ds, r);
  const dayStart = ds.scheduling?.day_start_hour ?? 6;
  const set = (patch: Partial<Resource>) => store.update((d) => {
    const i = (d.resources ?? []).findIndex((x) => x.id === r.id);
    if (i >= 0) d.resources![i] = { ...d.resources![i], ...patch } as Resource;
  });
  const shifts = r.shifts ?? [];
  const setShift = (i: number, patch: Partial<Shift>) => set({ shifts: shifts.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const changes = r.capacity_changes ?? [];
  const setChange = (i: number, patch: Partial<Change>) => set({ capacity_changes: changes.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const [preset, setPreset] = useState("");
  const usePreset = (p: string) => {
    const S = (name: string, start: string, end: string, br = 30): Shift => ({ name, start, end, break_minutes: br } as Shift);
    const map: Record<string, Shift[]> = {
      one: [S("Day", "08:00", "16:30")],
      two: [S("Early", "06:00", "14:00"), S("Late", "14:00", "22:00")],
      three: [S("Early", "06:00", "14:00"), S("Late", "14:00", "22:00"), S("Night", "22:00", "06:00")],
    };
    if (map[p]) set({ shifts: map[p] });
    setPreset("");
  };

  // a sample week (the first full one of the plan) drawn as clock bars
  const start = toT(ds.settings.planning_start);
  const monday = start + ((7 - weekday(start)) % 7) * DAY;
  const week = [0, 1, 2, 3, 4, 5, 6].map((k) => ({ t: monday + k * DAY, c: dayCap(r, cal.isWork, monday + k * DAY, dayStart) }));
  // hours week by week over the plan, with the plan's load where one has run
  const weeks = useMemo(() => {
    const out: { from: number; hours: number; note: string }[] = [];
    const end = start + (ds.settings.horizon_days ?? 182) * DAY;
    for (let w = start - weekday(start) * DAY; w < end; w += 7 * DAY) {
      let h = 0; const notes = new Set<string>();
      for (let k = 0; k < 7; k++) {
        const t = w + k * DAY;
        if (t < start || t >= end) continue;
        const c = dayCap(r, cal.isWork, t, dayStart);
        h += hoursOf(c);
        if (c.ch) notes.add(c.ch.note || (c.ch.units === 0 ? "shut down" : "changed"));
      }
      out.push({ from: w, hours: h, note: [...notes].join("; ") });
    }
    return out;
  }, [r, ds, start, cal, dayStart]);
  const max = Math.max(1, ...weeks.map((w) => w.hours));
  const rp = plan?.resources.find((x) => x.resource === r.id);
  // the plan's load by day, summed over the week (whatever bucket the plan reports in)
  const loadOf = (t: number) => {
    if (!rp) return null;
    let h = 0;
    for (const [d, v] of Object.entries(rp.daily_load ?? {})) { const x = toT(d); if (x >= t && x < t + 7 * DAY) h += v; }
    return h;
  };

  return (
    <div className="stack">
      <Panel title={<h3>{r.name || r.id} <span className="faint small">at {nm.loc(r.location)}</span></h3>}
        actions={<a className="btn sm ghost" href={href("data", "resources", r.id)}>Every field</a>}>
        <div className="row wrap">
          <label className="qf">Machines or people<input className="input" type="number" min={1} value={r.units ?? 1} style={{ width: 80 }}
            onChange={(e) => Number(e.target.value) >= 1 && set({ units: Math.round(Number(e.target.value)) })} /></label>
          <label className="qf">Efficiency %<input className="input" type="number" min={1} max={100} value={Math.round((r.efficiency ?? 0.85) * 100)} style={{ width: 80 }}
            onChange={(e) => { const v = Number(e.target.value); if (v > 0 && v <= 100) set({ efficiency: v / 100 }); }} /></label>
          <div className="small muted">Works on the days of <b>{cal.name}</b>.</div>
        </div>
      </Panel>

      <Panel title="Shifts" actions={<select className="select" style={{ width: "auto" }} value={preset} onChange={(e) => usePreset(e.target.value)} aria-label="Use a pattern">
        <option value="">Use a pattern…</option><option value="one">One day shift</option><option value="two">Two shifts</option><option value="three">Three shifts, round the clock</option></select>}>
        {!shifts.length ? (
          <div className="row wrap">
            <span className="small">No named shifts: it works</span>
            <input className="input" type="number" min={0.5} max={4} step={0.5} value={r.shifts_per_day ?? 1} style={{ width: 70 }} aria-label="Shifts per day"
              onChange={(e) => { const v = Number(e.target.value); if (v > 0 && v <= 4) set({ shifts_per_day: v }); }} />
            <span className="small">shift(s) of</span>
            <input className="input" type="number" min={1} max={24} step={0.5} value={r.hours_per_shift ?? 8} style={{ width: 70 }} aria-label="Hours per shift"
              onChange={(e) => { const v = Number(e.target.value); if (v > 0 && v <= 24) set({ hours_per_shift: v }); }} />
            <span className="small">hours from {String(Math.floor(dayStart)).padStart(2, "0")}:00, with no breaks.</span>
            <button className="btn sm" onClick={() => set({ shifts: [{ name: "Day", start: "08:00", end: "16:30", break_minutes: 30 } as Shift] })}>+ Name the shifts</button>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Name</th><th>From</th><th>To</th><th>Break (min)</th><th>Break at</th><th>Weekdays</th><th className="num">Hours</th><th /></tr></thead>
              <tbody>{shifts.map((s, i) => (
                <tr key={i}>
                  <td><input className="input" value={s.name ?? ""} style={{ width: 90 }} aria-label="Shift name" onChange={(e) => setShift(i, { name: e.target.value })} /></td>
                  <td><input className="input" type="time" value={s.start} aria-label="Starts" onChange={(e) => e.target.value && setShift(i, { start: e.target.value })} /></td>
                  <td><input className="input" type="time" value={s.end} aria-label="Ends" onChange={(e) => e.target.value && setShift(i, { end: e.target.value })} /></td>
                  <td><input className="input" type="number" min={0} value={s.break_minutes ?? 0} style={{ width: 70 }} aria-label="Break minutes"
                    onChange={(e) => { const v = Number(e.target.value); if (v >= 0 && v / 60 < lengthOf(s)) setShift(i, { break_minutes: v }); }} /></td>
                  <td><input className="input" type="time" value={s.break_start ?? ""} aria-label="Break starts" title="Empty: halfway through the shift"
                    onChange={(e) => setShift(i, { break_start: e.target.value || null })} /></td>
                  <td><div className="wd" role="group" aria-label="Weekdays">{WD.map((w, d) => {
                    const on = !!s.weekdays?.includes(d);
                    return <button key={w} type="button" className={on ? "on" : ""} aria-pressed={on} title={w} onClick={() => {
                      const cur = s.weekdays ?? [];
                      const next = on ? cur.filter((x) => x !== d) : [...cur, d].sort();
                      setShift(i, { weekdays: next.length ? next : null });
                    }}>{w[0]}</button>;
                  })}</div>
                    <div className="faint small">{s.weekdays?.length ? s.weekdays.map((d) => WD[d]).join(" ") : "every working day"}</div></td>
                  <td className="num">{qty(netOf(s))}</td>
                  <td><button className="btn sm ghost danger" onClick={() => set({ shifts: shifts.filter((_, j) => j !== i) })} aria-label="Remove shift">Remove</button></td>
                </tr>))}</tbody>
            </table>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn sm" onClick={() => set({ shifts: [...shifts, { name: "", start: "14:00", end: "22:00", break_minutes: 30 } as Shift] })}>+ Add a shift</button>
              <button className="btn sm ghost" onClick={() => set({ shifts: [] })}>Back to a simple day</button>
            </div>
          </div>
        )}
        <WeekBars week={week} />
      </Panel>

      <Panel title="Capacity changes" actions={<button className="btn sm" onClick={() => set({ capacity_changes: [...changes, { valid_from: ds.settings.planning_start, units: 0, note: "maintenance" } as Change] })}>+ Add a change</button>}>
        {!changes.length ? <p className="muted small" style={{ margin: 0 }}>None: it works the same every week. Add one for a shutdown, a second shift from a date, or a slower start-up.</p> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>From</th><th>To</th><th>What changes</th><th>Note</th><th /></tr></thead>
              <tbody>{changes.map((c, i) => {
                const mode = c.units === 0 ? "down" : c.shifts ? "own" : c.shifts_per_day != null ? "shifts" : c.units != null ? "units" : c.efficiency != null ? "eff" : "units";
                return (
                  <tr key={i}>
                    <td><input className="input" type="date" value={c.valid_from} aria-label="From" onChange={(e) => e.target.value && setChange(i, { valid_from: e.target.value })} /></td>
                    <td><input className="input" type="date" value={c.valid_to ?? ""} aria-label="To" onChange={(e) => setChange(i, { valid_to: e.target.value || null })} />
                      {!c.valid_to && <div className="faint small">from then on</div>}</td>
                    <td><div className="row wrap">
                      <select className="select" style={{ width: "auto" }} value={mode} aria-label="What changes" onChange={(e) => {
                        const m = e.target.value;
                        const base = { units: null, shifts_per_day: null, efficiency: null } as Partial<Change>;
                        setChange(i, m === "down" ? { ...base, units: 0, shifts: null } : m === "units" ? { ...base, units: (r.units ?? 1) + 1, shifts: null }
                          : m === "shifts" ? { ...base, shifts_per_day: 2, shifts: null } : m === "eff" ? { ...base, efficiency: 0.6, shifts: null } : {});
                      }}>
                        <option value="down">Shut down</option><option value="units">Machines or people</option>
                        <option value="shifts">Shifts per day</option><option value="eff">Efficiency</option>
                        {mode === "own" && <option value="own">Its own shifts</option>}
                      </select>
                      {mode === "units" && <input className="input" type="number" min={0} value={c.units ?? 1} style={{ width: 70 }} aria-label="Units in this period" onChange={(e) => Number(e.target.value) >= 0 && setChange(i, { units: Math.round(Number(e.target.value)) })} />}
                      {mode === "shifts" && <input className="input" type="number" min={0.5} max={4} step={0.5} value={c.shifts_per_day ?? 1} style={{ width: 70 }} aria-label="Shifts per day in this period" onChange={(e) => { const v = Number(e.target.value); if (v > 0 && v <= 4) setChange(i, { shifts_per_day: v }); }} />}
                      {mode === "shifts" && shifts.length > 0 && <span className="faint small">of {qty(r.hours_per_shift ?? 8)} h, instead of the named shifts</span>}
                      {mode === "eff" && <><input className="input" type="number" min={1} max={100} value={Math.round((c.efficiency ?? 0.85) * 100)} style={{ width: 70 }} aria-label="Efficiency in this period" onChange={(e) => { const v = Number(e.target.value); if (v > 0 && v <= 100) setChange(i, { efficiency: v / 100 }); }} /><span className="small">%</span></>}
                      {mode === "own" && <a className="small" href={href("data", "resources", r.id)}>edit in Master data</a>}
                    </div></td>
                    <td><input className="input" value={c.note ?? ""} aria-label="Note" onChange={(e) => setChange(i, { note: e.target.value })} /></td>
                    <td><button className="btn sm ghost danger" onClick={() => set({ capacity_changes: changes.filter((_, j) => j !== i) })} aria-label="Remove change">Remove</button></td>
                  </tr>
                );
              })}</tbody>
            </table>
            {changes.length > 1 && <p className="faint small">Where two changes cover the same day, the lower one in the list wins.</p>}
          </div>
        )}
      </Panel>

      <Panel flush title={<h3>Hours week by week</h3>} actions={rp ? <a className="btn sm ghost" href={href("plan", "capacity", r.id)}>Load in the supply plan</a> : undefined}>
        <div className="table-wrap" style={{ maxHeight: 360 }}>
          <table className="t">
            <thead><tr><th>Week of</th><th className="num">Productive hours</th><th style={{ width: "40%" }} />{rp && <th className="num">Plan needs</th>}<th>Why it differs</th></tr></thead>
            <tbody>{weeks.map((w) => {
              const load = loadOf(w.from);
              return (
                <tr key={w.from}>
                  <td className="nowrap">{day(iso(w.from))}</td>
                  <td className="num">{qty(w.hours)}</td>
                  <td><div className="bar"><span style={{ width: `${(w.hours / max) * 100}%` }} />{load != null && load > 0 && <i style={{ left: `${Math.min(100, (load / max) * 100)}%` }} title={`Plan needs ${qty(load)} h`} />}</div></td>
                  {rp && <td className={`num ${load != null && load > w.hours + 1e-6 ? "neg" : ""}`}>{load != null ? qty(load) : "—"}</td>}
                  <td className="small muted">{w.note}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </Panel>
      {changes.some((c) => c.units === 0) && <Badge sev="info">Orders due around a shutdown are planned to finish before it or after it.</Badge>}
    </div>
  );
}

/** A week of working windows as clock bars: shifts, breaks, overnight work and days off at a glance. */
function WeekBars({ week }: { week: { t: number; c: ReturnType<typeof dayCap> }[] }) {
  const W = 560, L = 44, row = 18, H = week.length * row + 22;
  const x = (h: number) => L + (h / 24) * (W - L - 48);
  return (
    <div style={{ overflowX: "auto", marginTop: 12 }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: "100%" }} role="img" aria-label="Working hours in a sample week">
        {[0, 6, 12, 18, 24].map((h) => <g key={h}>
          <line x1={x(h)} x2={x(h)} y1={0} y2={H - 16} stroke="var(--border)" />
          <text x={x(h)} y={H - 4} fontSize={10} textAnchor="middle" fill="var(--text-3)">{String(h).padStart(2, "0")}:00</text></g>)}
        {week.map(({ t, c }, i) => {
          const y = i * row + 3;
          const bars: [number, number][] = [];
          for (const [a, b] of c.wins) { bars.push([a, Math.min(b, 24)]); }
          const prev = i > 0 ? week[i - 1].c.wins.filter(([, b]) => b > 24).map(([, b]) => [0, b - 24] as [number, number]) : [];
          return <g key={t}>
            <text x={0} y={y + 11} fontSize={11} fill="var(--text-2)">{WD[weekday(t)]} {new Date(t).getUTCDate()}</text>
            {!c.wins.length && !prev.length && <text x={x(0) + 4} y={y + 11} fontSize={10} fill="var(--text-3)">{c.units === 0 ? "shut down" : "not working"}</text>}
            {[...prev, ...bars].map(([a, b], k) => <rect key={k} x={x(a)} y={y} width={Math.max(1, x(b) - x(a))} height={row - 6} rx={2}
              fill="var(--series-1)" opacity={c.units > 1 ? 1 : 0.85}><title>{`${a.toFixed(2)}–${b.toFixed(2)} h`}</title></rect>)}
            {c.wins.length > 0 && <text x={W - 4} y={y + 11} fontSize={10} textAnchor="end" fill="var(--text-3)">{qty(hoursOf(c))} h</text>}
          </g>;
        })}
      </svg>
    </div>
  );
}
