import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  Changeover, CompareRow, Dataset, ScheduleCatalogue, ScheduleComparison, ScheduledOp, ScheduleResource, ScheduleResult,
} from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, cols, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, useTooltip, RunButton, Term,
} from "../components/ui";
import { day, pct, plural, qty } from "../lib/format";
import { Prod } from "../lib/names";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "board" | "methods" | "orders" | "resources" | "setups" | "settings";
type Seqs = Record<string, string[]>;

/** The schedule on the page as the engine takes it back: every machine's sequence (realised order and machine). */
const sequences = (res: ScheduleResult): Seqs => Object.fromEntries(res.resources.map((r) => [r.id, r.sequence]));

const RULE_NAME: Record<string, string> = {
  edd: "Earliest due date", spt: "Shortest job first", slack: "Least slack", campaign: "Campaigns", backward: "Backward (just in time)",
};

// ---- time helpers: engine times are clock hours from the origin (planning start, 00:00) -----------
const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
function clock(origin: string, h: number): Date {
  return new Date(new Date(origin).getTime() + h * 3600_000);
}
function when(origin: string, h: number): string {
  const d = clock(origin, h);
  return `${WD[d.getDay()]} ${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function hours(h: number): string {
  const a = Math.abs(h);
  const s = a >= 48 ? `${(a / 24).toFixed(1)} d` : `${a.toFixed(a < 10 ? 1 : 0)} h`;
  return h < 0 ? `−${s}` : s;
}

/** Setup groups get categorical hues in a fixed (alphabetical) order, so colour follows the group. */
function groupColors(res: ScheduleResult): Record<string, string> {
  const groups = [...new Set(res.ops.map((o) => o.group))].sort();
  return Object.fromEntries(groups.map((g, i) => [g, i < 7 ? `var(--series-${i + 1})` : "var(--text-3)"]));
}

export function Schedule({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.schedule);
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const rev = useStore((s) => s.revision);
  const stale = useStore((s) => isStale(s, "schedule"));
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const partsCheck = ds.scheduling?.wait_for_parts ?? true;
  const view = ((route[1] as View) || "board") as View;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);

  /** Fix the schedule's dates on its orders: planned ones become production orders, released ones are re-dated. */
  const useDates = async () => {
    if (!res) return;
    setBusy(true);
    setErr(null);
    try {
      // exactly the schedule on the page: the optimiser need not find the same one twice
      const out = await api.applySchedule(ds, sequences(res), undefined, res.holds);
      store.replace(out.dataset);
      const made = out.report.applied.filter((a) => a.new).length;
      const moved = out.report.applied.filter((a) => !a.new && (a.due_date !== a.was_due || a.start_date !== a.was_start)).length;
      setApplied(`${plural(made, "planned order")} became production orders with the schedule's dates${moved ? `, and ${plural(moved, "released order")} got new dates` : ""}. `
        + "The supply plan, promises and money now use these dates; an order the schedule finishes late shows up there as late, not as a new order.");
      setAsking(false);
      await Promise.all([store.run("plan"), store.run("schedule")]);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const [moved, setMoved] = useState<string | null>(null);
  /** Re-time the schedule with a step moved: `key` goes onto `to`, before `before` (null = last). Every other step keeps
   *  its machine and place; the not-before times the schedule had stay. */
  const move = async (key: string, to: string, before: string | null) => {
    if (!res) return;
    const all = sequences(res);
    const from = res.resources.find((r) => r.sequence.includes(key))?.id;
    for (const r of Object.keys(all)) all[r] = all[r].filter((k) => k !== key);
    const seq = all[to] ?? [];
    const at = before ? seq.indexOf(before) : -1;
    all[to] = at < 0 ? [...seq, key] : [...seq.slice(0, at), key, ...seq.slice(at)];
    setBusy(true);
    setErr(null);
    try {
      const next = await api.schedule(ds, all, res.holds);
      store.put("schedule", next, rev);
      const [order, step] = key.split(/:(?=[^:]*$)/);
      const k0 = res.kpis, k1 = next.kpis;
      setMoved(`${order} step ${step} ${from !== to ? `moved to ${to}` : "moved"}${before ? `, before ${before.split(/:(?=[^:]*$)/)[0]}` : ", last"}. `
        + `Late orders ${k0.late_orders} → ${k1.late_orders}, changeovers ${k0.changeovers} → ${k1.changeovers}, weighted score ${k0.objective.toFixed(0)} → ${k1.objective.toFixed(0)}.`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const head = (
    <StageHeader title="Shop floor" kicker="In what order each machine and line should run its jobs, hour by hour, so orders finish on time with the fewest changeovers."
      how={<>Production orders are sequenced on each machine and line in clock time on its shift calendar, with
        <Term t="Changeover"> changeovers</Term> that depend on what ran before, parallel units, alternative machines and queue times.
        A profile picks how: a start rule (due date, shortest first, least slack, campaigns or backward from the due date), a local
        search, and optionally a constraint solver, all scored by the same weights. Drag a step on the board to change it by hand.</>}
      answer={res && (res.kpis.orders ? <>{res.kpis.late_orders ? <>{res.kpis.late_orders} of {plural(res.kpis.orders, "production order")} finish late,
        the worst by {hours(res.kpis.max_lateness_hours)}.</> : <>All {plural(res.kpis.orders, "production order")} finish on time.</>}{" "}
        {plural(res.kpis.changeovers, "changeover")} take {hours(res.kpis.setup_hours)}.
        {partsCheck ? (res.kpis.waiting_for_parts > 0 && <> {plural(res.kpis.waiting_for_parts, "order")} wait for parts before a step can start.</>)
          : <> Parts are assumed to be there (the parts check is off in Settings).</>}</> : <>No production orders fall in the window.</>)}
      right={<>
      {res && <Provenance kind="solved" at={run.at} stale={stale} />}
      {res?.ok && res.orders.length > 0 && <button className="btn" onClick={() => setAsking(true)} disabled={busy || stale || run.running}
        title={stale ? "Schedule again first" : "Give the orders on this schedule its dates, so the supply plan and promises use them"}>Use these dates in the plan</button>}
      {res?.search.mode === "manual" && <button className="btn" onClick={() => store.run("schedule")} disabled={run.running}>Undo my changes to the order</button>}
      <RunButton running={run.running} has={!!res} onClick={() => store.run("schedule")} disabled={blocking} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  if (view === "settings") return body(<><Nav view={view} res={res} /><SettingsView ds={ds} /></>);
  if (view === "methods") return body(<><Nav view={view} res={res} /><Methods ds={ds} res={res} running={run.running} /></>);
  if (view === "setups") return body(<><Nav view={view} res={res} /><SetupMatrix ds={ds} res={res} /></>);
  if (run.error) return body(<div className="banner error"><Badge sev="error">Scheduling failed</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      <SolverIO answers="When each production order runs on which machine, in what sequence, what it spends on changeovers, and which orders finish late."
        from="Planned make orders from MRP (inside the scheduling window) and firm production orders, routings, shift calendars, OEE, the setup matrix."
        feeds="Dispatch lists for the shop floor, realistic finish dates for promising (ATP/CTP), capacity exceptions." />
      <div style={{ height: 14 }} />
      <Panel><Empty title={blocking ? "Fix blocking readiness issues first" : "Not scheduled yet"}>
        {blocking ? <a className="btn" href={href("readiness")}>Open readiness</a>
          : <p>Schedule to sequence the next {ds.scheduling?.horizon_days ?? 42} days of production orders on finite capacity.</p>}
      </Empty></Panel></>);
  }
  if (!res.ok || !res.origin) {
    return body(<div className="banner error"><Badge sev="error">Not scheduled</Badge>
      The dataset has blocking readiness issues. <a href={href("readiness")}>Review them</a>.</div>);
  }
  return body(<>
    {stale && <StaleMark what="schedule" onRerun={() => store.run("schedule")} busy={run.running} />}
    {err && <div className="banner error"><Badge sev="error">That didn't work</Badge>{err}</div>}
    {asking && <UseDates res={res} busy={busy} onYes={useDates} onNo={() => setAsking(false)} />}
    {applied && <div className="banner info"><Badge sev="ok">Dates in the plan</Badge><span>{applied} <a href={href("plan")}>Open the supply plan</a></span>
      <span className="spacer" /><button className="btn sm ghost" aria-label="Dismiss" onClick={() => setApplied(null)}>✕</button></div>}
    {res.violations.length > 0 && (
      <div className="banner error"><Badge sev="error">{res.violations.length} feasibility violations</Badge>{res.violations.slice(0, 3).join(" · ")}</div>
    )}
    {res.search.mode === "manual" && (
      <div className="banner info"><Badge sev="info">Your sequence</Badge>
        <span>{moved ?? "You changed the order or machine of a step; the schedule was re-timed with your sequence."} “Undo my changes to the order” schedules again from the profile.</span>
        {moved && <><span className="spacer" /><button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMoved(null)}>✕</button></>}</div>
    )}
    <Nav view={view} res={res} />
    {view === "board" && <Board res={res} sel={route[2]} busy={busy} onMove={move} />}
    {view === "orders" && <Orders res={res} />}
    {view === "resources" && <Resources res={res} />}
  </>);
}

/** The confirmation step for writing the schedule's dates into the data (the viewer never shows browser dialogs). */
function UseDates({ res, busy, onYes, onNo }: { res: ScheduleResult; busy: boolean; onYes: () => void; onNo: () => void }) {
  const planned = res.orders.filter((o) => !o.firm).length;
  const firm = res.orders.length - planned;
  const late = res.orders.filter((o) => o.days_late > 0).length;
  return (
    <div className="banner warning" role="alertdialog" aria-label="Use the schedule's dates">
      <Badge sev="warning">Check</Badge>
      <span>This makes {plural(planned, "planned order")} firm production orders{firm ? ` and re-dates ${plural(firm, "released order")}` : ""},
        each starting and finishing when this schedule says{late ? `; ${plural(late, "order")} will then show as late in the supply plan` : ""}.
        Undo reverts it.</span>
      <span className="spacer" />
      <button className="btn sm accent" onClick={onYes} disabled={busy}>{busy ? "Saving…" : "Use the dates"}</button>
      <button className="btn sm ghost" onClick={onNo} disabled={busy}>Cancel</button>
    </div>
  );
}

function Nav({ view, res }: { view: View; res: ScheduleResult | null }) {
  return (
    <Tabs<View> value={view} onChange={(v) => go("schedule", v)} tabs={[
      { id: "board", label: "Planning board" },
      { id: "methods", label: "Methods & profiles" },
      { id: "orders", label: "Orders", count: res?.orders.length },
      { id: "resources", label: "Resources & labour", count: res?.resources.length },
      { id: "setups", label: "Setup matrix" },
      { id: "settings", label: "Settings" },
    ]} />
  );
}

// ------------------------------------------------------------------------------------------------
function Kpis({ res }: { res: ScheduleResult }) {
  const k = res.kpis;
  const b = res.baseline;
  const delta = (cur: number, base: number, unit: (v: number) => string) =>
    Math.abs(cur - base) < 1e-6 ? "same as EDD" : `${cur < base ? "−" : "+"}${unit(Math.abs(cur - base))} vs EDD`;
  const busiest = [...res.resources].sort((x, y) => y.utilization - x.utilization)[0];
  const firm = res.orders.filter((o) => o.firm).length;
  return (
    <div className="grid-auto">
      <StatTile label="Orders scheduled" value={qty(k.orders)} sub={`${k.operations} operations${firm ? ` · ${firm} firm` : ""}${res.beyond_horizon ? ` · ${res.beyond_horizon} later` : ""}`} />
      <StatTile label="Late orders" value={`${k.late_orders} / ${k.orders}`} sub={delta(k.late_orders, b.late_orders, (v) => `${v}`)} tone={k.late_orders ? "hl" : undefined} />
      <StatTile label="Tardiness" value={hours(k.tardiness_hours)} sub={`${delta(k.tardiness_hours, b.tardiness_hours, hours)} · worst ${hours(Math.max(0, k.max_lateness_hours))}`} />
      <StatTile label="Waiting for parts" value={`${k.waiting_for_parts} / ${k.orders}`}
        sub={k.waiting_for_parts ? `${hours(res.orders.reduce((a, o) => a + o.held_for_parts, 0))} held in total` : "every step had its parts"}
        tone={k.waiting_for_parts ? "hl" : undefined} />
      <StatTile label="Changeover time" value={hours(k.setup_hours)} sub={`${k.changeovers} changeovers · ${delta(k.setup_hours, b.setup_hours, hours)}`} />
      {busiest && <StatTile label="Busiest resource" value={pct(busiest.utilization, 0)} sub={`${busiest.id} over the window`} />}
      {k.earliness_hours > 0.05 && <StatTile label="Finished early" value={hours(k.earliness_hours)}
        sub={`order hours before due${(res.kpis.orders && Object.keys(res.holds).length) ? ` · ${plural(Object.keys(res.holds).length, "order")} held back` : ""}`} />}
      <Sequencer res={res} />
    </div>
  );
}

/** How the schedule was found: the profile, the start rule, the local search and the optimiser. */
function Sequencer({ res }: { res: ScheduleResult }) {
  const s = res.search;
  const opt = s.optimizer;
  const rule = RULE_NAME[s.start_rule] ?? s.start_rule;
  const profile = res.profile && res.profile !== "custom" ? `${res.profile.replace(/_/g, " ")} profile · ` : "";
  if (s.mode === "manual") return <StatTile label="Sequence" value="Yours" sub="your order and machines, re-timed" />;
  if (s.mode === "optimized" && opt) {
    return <StatTile label="Sequence" value={opt.kept ? "Optimiser" : "Local search"}
      sub={opt.kept ? `${profile}${opt.status}${opt.machines_changed ? ` · ${plural(opt.machines_changed, "step")} on another machine` : ""} · ${opt.seconds.toFixed(1)} s`
        : `${profile}${opt.note || "the solver found nothing better"}`} />;
  }
  if (s.mode === "improved") {
    return <StatTile label="Sequence" value={s.moves_accepted ? `${rule} + ${s.moves_accepted} moves` : rule}
      sub={`${profile}local search: ${s.moves_accepted ? `${s.moves_tried} tried · ${s.seconds.toFixed(2)} s` : `no better move in ${s.moves_tried} tried`}`} />;
  }
  return <StatTile label="Sequence" value={rule} sub={`${profile}local search off`} />;
}

// ------------------------------------------------------------------------------------------------
const ZOOMS: [string, number][] = [["Month", 1.2], ["2 weeks", 2.6], ["Week", 5.2], ["Days", 12]];

type Move = (key: string, to: string, before: string | null) => void;

function Board({ res, sel, busy, onMove }: {
  res: ScheduleResult; sel?: string; busy: boolean; onMove: Move;
}) {
  const [zoom, setZoom] = useState(2.6);
  const order = res.orders.find((o) => o.id === sel) ?? null;
  const colors = useMemo(() => groupColors(res), [res]);
  return (
    <div className="stack">
      <Kpis res={res} />
      <Panel flush title="Planning board" actions={
        <div className="row">
          {ZOOMS.map(([l, z]) => <button key={l} className={`btn sm ${zoom === z ? "primary" : ""}`} onClick={() => setZoom(z)}>{l}</button>)}
        </div>}>
        <Gantt res={res} pxh={zoom} sel={order?.id ?? null} colors={colors} busy={busy} onMove={onMove} />
        <div className="legend" style={{ padding: "8px 12px" }}>
          {Object.entries(colors).map(([g, c]) => <span key={g}><span className="key box" style={{ background: c }} />{g}</span>)}
          <span><span className="key box gantt-setup-key" />changeover</span>
          <span><span className="key box gantt-off-key" />off shift</span>
          <span><span className="key box" style={{ background: "transparent", outline: "2px solid var(--critical)" }} />late order</span>
          {res.orders.some((o) => o.frozen) && <span><span className="key box" style={{ background: "transparent", outline: "2px dashed var(--ink)" }} />frozen (stays put)</span>}
        </div>
      </Panel>
      {order ? <OrderDetail res={res} id={order.id} busy={busy} onMove={onMove} />
        : <p className="faint small" style={{ margin: 0 }}>Drag a step along its row to run it earlier or later, or onto another machine's row that can run it
          (an alternative); the schedule is re-timed at once. Click a step to follow its order across machines.</p>}
      <Reading formula={<>Each resource works its sequence in order; an operation starts at max(order release or predecessor end + queue, unit free),
        sets up (nothing before → full setup; same product → 0; same group → minor setup; other group → setup matrix), then runs
        work ÷ OEE clock hours inside shift windows. Weighted score = w<sub>late</sub>·Σ hours late + w<sub>setup</sub>·Σ changeover hours
        + w<sub>early</sub>·Σ hours early + w<sub>span</sub>·hours to clear the window. A dragged step keeps its new machine and place; every
        other step keeps its machine and order, and frozen orders keep theirs.</>}
        soWhat={<>Late orders here are ones the supply plan did not see: it plans machines by the day, the schedule by the hour and with parts arriving.
          Change the order, add a shift or overtime, or use these dates in the plan so promises quote them. To plan within capacity
          from the start, see <a href={href("capacity")}>Capacity levelling</a>.</>} />
    </div>
  );
}

type Lane = { resource: ScheduleResource; unit: number; first: boolean };

/** Clip [a, b) to the working windows so paused jobs show as separate bars around the night. */
function segments(a: number, b: number, windows: number[][]): [number, number][] {
  const out: [number, number][] = [];
  for (const [s, e] of windows) {
    if (e <= a) continue;
    if (s >= b) break;
    out.push([Math.max(a, s), Math.min(b, e)]);
  }
  if (!out.length && b > a) out.push([a, b]);
  return out;
}

type Drag = { op: ScheduledOp; lane: number; px: number; py: number; dx: number; dy: number; moved: boolean };

function Gantt({ res, pxh, sel, colors, busy, onMove }: {
  res: ScheduleResult; pxh: number; sel: string | null; colors: Record<string, string>; busy: boolean; onMove: Move;
}) {
  const tip = useTooltip();
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragged = useRef(false);
  const origin = res.origin!;
  const lanes: Lane[] = useMemo(() => res.resources.flatMap((r) => {
    const units = r.finite ? r.units : Math.max(1, new Set(res.ops.filter((o) => o.resource === r.id).map((o) => o.unit)).size);
    return Array.from({ length: units }, (_, u) => ({ resource: r, unit: u, first: u === 0 }));
  }), [res]);
  const unitIndex = useMemo(() => {
    // non-finite resources: compact the engine's per-op unit ids to lanes
    const m = new Map<string, number>();
    for (const r of res.resources) {
      if (r.finite) continue;
      [...new Set(res.ops.filter((o) => o.resource === r.id).map((o) => o.unit))].forEach((u, i) => m.set(`${r.id}|${u}`, i));
    }
    return m;
  }, [res]);
  const orderById = useMemo(() => Object.fromEntries(res.orders.map((o) => [o.id, o])), [res]);
  const selOrder = sel ? orderById[sel] : null;
  const LABEL = 150, TOP = 34, RH = 26;
  const span = Math.ceil(res.span_hours / 24) * 24;
  const W = span * pxh;
  const H = TOP + lanes.length * RH + 6;
  const x = (h: number) => h * pxh;
  const laneOf = (op: ScheduledOp) => {
    const u = unitIndex.get(`${op.resource}|${op.unit}`) ?? op.unit;
    return lanes.findIndex((l) => l.resource.id === op.resource && l.unit === u);
  };
  const days = Array.from({ length: span / 24 }, (_, d) => d);
  const scroller = useRef<HTMLDivElement>(null);
  const focus = selOrder?.release ?? null;
  useEffect(() => {
    // bring the selected order into view (release a little in from the left edge)
    if (focus !== null && scroller.current) scroller.current.scrollTo({ left: Math.max(0, focus * pxh - 60), behavior: "smooth" });
  }, [focus, pxh]);
  const dayLabel = pxh * 24 >= 44;
  /** Where a drag would drop: the lane under the pointer, whether that machine can run the step, the time, and the step
   *  it would go before. */
  const target = (d: Drag) => {
    const li = Math.max(0, Math.min(lanes.length - 1, d.lane + Math.round(d.dy / RH)));
    const to = lanes[li].resource.id;
    const machines = d.op.machines?.length ? d.op.machines : [d.op.resource];
    const t = d.op.setup_start + d.dx / pxh;
    const starts = new Map<string, number>();
    for (const o of res.ops) {
      if (o.resource === to && o.key !== d.op.key) starts.set(o.key, Math.min(starts.get(o.key) ?? Infinity, o.setup_start));
    }
    const seq = (res.resources.find((r) => r.id === to)?.sequence ?? []).filter((k) => k !== d.op.key);
    const before = seq.find((k) => (starts.get(k) ?? Infinity) > t) ?? null;
    return { li, to, ok: machines.includes(to), t, before };
  };
  const drop = drag?.moved ? target(drag) : null;
  return (
    <div className="gantt">
      <div className="gantt-labels" style={{ width: LABEL }}>
        <div style={{ height: TOP }} />
        {lanes.map((l) => (
          <div key={`${l.resource.id}-${l.unit}`} className={`gantt-lane-label ${l.first ? "first" : ""}`} style={{ height: RH }}>
            {l.first ? <><b>{l.resource.id}</b><span className="faint small"> {pct(l.resource.utilization, 0)}</span></> : <span className="faint small">unit {l.unit + 1}</span>}
          </div>
        ))}
      </div>
      <div className="gantt-scroll" ref={scroller}>
        <svg className="chart" width={W} height={H} role="img" aria-label="Gantt chart of the detailed schedule">
          <defs>
            <pattern id="gantt-off" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="var(--surface-2)" /><line x1="0" y1="0" x2="0" y2="6" stroke="var(--surface-3)" strokeWidth="3" />
            </pattern>
            <pattern id="gantt-setup" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(135)">
              <rect width="5" height="5" fill="var(--surface)" /><line x1="0" y1="0" x2="0" y2="5" stroke="var(--text-2)" strokeWidth="2" />
            </pattern>
          </defs>
          {/* day grid + axis */}
          {days.map((d) => {
            const dt = clock(origin, d * 24);
            const monday = dt.getDay() === 1;
            return (
              <g key={d}>
                <line x1={x(d * 24)} x2={x(d * 24)} y1={TOP - 6} y2={H} className="gridline" style={monday ? { stroke: "var(--text-3)" } : undefined} />
                {(dayLabel || monday) && <text x={x(d * 24) + 3} y={TOP - 18}>{dayLabel ? WD[dt.getDay()] : "wk"}</text>}
                {(dayLabel || monday) && <text x={x(d * 24) + 3} y={TOP - 6}>{dt.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</text>}
              </g>
            );
          })}
          {/* lanes: off-shift hatch, working windows on top */}
          {lanes.map((l, i) => (
            <g key={`${l.resource.id}-${l.unit}`}>
              <rect x={0} y={TOP + i * RH} width={W} height={RH} fill="url(#gantt-off)" />
              {l.resource.windows.map(([s, e]) => <rect key={s} x={x(s)} y={TOP + i * RH} width={x(e) - x(s)} height={RH} fill="var(--surface)" />)}
              {l.first && i > 0 && <line x1={0} x2={W} y1={TOP + i * RH} y2={TOP + i * RH} stroke="var(--ink)" strokeWidth={1.5} />}
            </g>
          ))}
          {selOrder && <>
            {selOrder.parts_ready > selOrder.release + 1e-6 && <>
              <line x1={x(selOrder.parts_ready)} x2={x(selOrder.parts_ready)} y1={TOP} y2={H} stroke="var(--warning)" strokeDasharray="1 3" strokeWidth={2} />
              <text x={x(selOrder.parts_ready) + 4} y={H - 18} style={{ fill: "var(--text)" }}>last parts</text></>}
            <line x1={x(selOrder.release)} x2={x(selOrder.release)} y1={TOP} y2={H} stroke="var(--text-2)" strokeDasharray="2 3" strokeWidth={1.5} />
            <line x1={x(selOrder.due)} x2={x(selOrder.due)} y1={TOP} y2={H} stroke={selOrder.tardy ? "var(--critical)" : "var(--good)"} strokeDasharray="5 3" strokeWidth={2} />
            <text x={x(selOrder.due) + 4} y={H - 6} style={{ fill: "var(--text)" }}>due {selOrder.id}</text>
          </>}
          {drop && <rect x={0} y={TOP + drop.li * RH} width={W} height={RH} fill={drop.ok ? "var(--good)" : "var(--critical)"} opacity={0.14} pointerEvents="none" />}
          {/* operations */}
          {res.ops.map((op) => {
            const li = laneOf(op);
            if (li < 0) return null;
            const y = TOP + li * RH + 3;
            const h = RH - 6;
            const wins = lanes[li].resource.windows;
            const dim = drag?.moved && drag.op.id === op.id ? 0.35 : sel && op.order !== sel ? 0.22 : 1;
            const c = colors[op.group];
            const ord = orderById[op.order];
            const locked = !!ord?.frozen;
            const alts = (op.machines ?? []).filter((m) => m !== op.resource);
            const show = (e: React.MouseEvent) => tip.show(e, <div>
              <b>{op.order}</b> · {op.product} {ord?.firm && <Badge>firm</Badge>}
              <div className="faint small">{op.resource} unit {op.unit + 1} · operation {op.seq}{op.sub > 0 || res.ops.some((o) => o.key === op.key && o.sub > 0) ? ` · sublot ${op.sub + 1}` : ""}</div>
              <div className="small">{qty(op.qty)} units</div>
              {op.setup_hours > 0 && <div className="small">Setup {hours(op.setup_hours)} {op.setup_from ? `(${op.setup_from} → ${op.group})` : "(first on unit)"}</div>}
              <div className="small">Run {hours(op.run_hours)} · {when(origin, op.run_start)} → {when(origin, op.end)}</div>
              {ord && <div className="small">Order due {when(origin, ord.due)} · {ord.tardy ? <b style={{ color: "var(--critical)" }}>late {hours(ord.lateness_hours)}</b> : `${hours(-ord.lateness_hours)} early`}</div>}
              {ord?.hold != null && <div className="small">Held back until {when(origin, ord.hold)} (so it isn't built early)</div>}
              <div className="faint small">{locked ? "Frozen: already dated inside the frozen zone, it keeps its place and machine."
                : `Drag to move${alts.length ? `; can also run on ${alts.join(", ")}` : ""}.`}</div>
            </div>);
            const run = segments(op.run_start, op.end, wins);
            return (
              <g key={op.id} data-order={op.order} data-op={op.key} opacity={dim} style={{ cursor: locked ? "pointer" : busy ? "progress" : "grab" }}
                onClick={() => { if (dragged.current) { dragged.current = false; return; } go("schedule", "board", op.order === sel ? undefined : op.order); }}
                onMouseMove={drag ? undefined : show} onMouseLeave={tip.hide}
                onPointerDown={(e) => {
                  // mouse and pen drag; on a touch screen a drag scrolls the board and a tap selects
                  if (locked || busy || e.pointerType === "touch" || e.button !== 0) return;
                  e.currentTarget.setPointerCapture(e.pointerId);
                  setDrag({ op, lane: li, px: e.clientX, py: e.clientY, dx: 0, dy: 0, moved: false });
                }}
                onPointerMove={(e) => {
                  if (!drag || drag.op.id !== op.id) return;
                  const dx = e.clientX - drag.px, dy = e.clientY - drag.py;
                  if (!drag.moved && Math.hypot(dx, dy) < 5) return;
                  tip.hide();
                  setDrag({ ...drag, dx, dy, moved: true });
                }}
                onPointerUp={() => {
                  if (!drag || drag.op.id !== op.id) return;
                  setDrag(null);
                  if (!drag.moved) return;
                  dragged.current = true;
                  const d = target(drag);
                  if (d.ok) onMove(op.key, d.to, d.before);
                }}
                onPointerCancel={() => setDrag(null)}>
                {segments(op.setup_start, op.run_start, wins).map(([a, b]) => (
                  <rect key={`s${a}`} x={x(a)} y={y} width={Math.max(1, x(b) - x(a))} height={h} fill="url(#gantt-setup)" stroke="var(--surface)" strokeWidth={1} />
                ))}
                {run.map(([a, b]) => (
                  <rect key={`r${a}`} x={x(a)} y={y} width={Math.max(1.5, x(b) - x(a))} height={h} fill={c}
                    stroke={op.late ? "var(--critical)" : locked ? "var(--ink)" : "var(--surface)"} strokeWidth={op.late || locked ? 2 : 1}
                    strokeDasharray={locked && !op.late ? "3 2" : undefined} />
                ))}
                {run.length > 0 && x(run[0][1]) - x(run[0][0]) > 46 && (
                  <text x={x(run[0][0]) + 4} y={y + h / 2 + 3.5} style={{ fill: "var(--surface)", fontWeight: 700, pointerEvents: "none" }}>{op.order.replace(/^MO-0*/, "")}</text>
                )}
              </g>
            );
          })}
          {drag?.moved && drop && (
            <g pointerEvents="none">
              <rect x={x(drag.op.setup_start) + drag.dx} y={TOP + drop.li * RH + 3} width={Math.max(4, x(drag.op.end) - x(drag.op.setup_start))} height={RH - 6}
                fill={colors[drag.op.group]} opacity={0.75} stroke={drop.ok ? "var(--ink)" : "var(--critical)"} strokeWidth={2} strokeDasharray="4 3" />
              <text x={x(drag.op.setup_start) + drag.dx} y={TOP + drop.li * RH - 3} style={{ fill: "var(--text)", fontWeight: 600 }}>
                {drop.ok ? `${drop.to}${drop.before ? `, before ${drop.before.split(/:(?=[^:]*$)/)[0]}` : ", last"}` : `${drop.to} can't run this step`}
              </text>
            </g>
          )}
        </svg>
      </div>
      {tip.node}
    </div>
  );
}

function OrderDetail({ res, id, busy, onMove }: {
  res: ScheduleResult; id: string; busy: boolean; onMove: Move;
}) {
  const o = res.orders.find((x) => x.id === id)!;
  const origin = res.origin!;
  const ops = res.ops.filter((x) => x.order === id).sort((a, b) => a.seq - b.seq || a.sub - b.sub);
  const keys = [...new Set(ops.map((x) => x.key))];
  /** One place earlier or later on its machine. */
  const step = (key: string, dir: -1 | 1) => {
    const r = res.resources.find((x) => x.sequence.includes(key))!;
    const seq = r.sequence.filter((k) => k !== key);
    const i = r.sequence.indexOf(key) + dir;
    if (i < 0 || i > seq.length) return;
    onMove(key, r.id, seq[i] ?? null);
  };
  /** Onto another machine that can run it, where its current start time falls in that machine's sequence. */
  const onto = (key: string, to: string) => {
    const at = Math.min(...ops.filter((x) => x.key === key).map((x) => x.setup_start));
    const starts = new Map<string, number>();
    for (const x of res.ops) if (x.resource === to) starts.set(x.key, Math.min(starts.get(x.key) ?? Infinity, x.setup_start));
    const seq = res.resources.find((r) => r.id === to)?.sequence ?? [];
    onMove(key, to, seq.find((k) => (starts.get(k) ?? Infinity) > at) ?? null);
  };
  return (
    <Panel title={`${o.id} · ${o.product} · ${qty(o.qty)} units`} actions={<button className="btn sm ghost" onClick={() => go("schedule", "board")}>Close</button>}>
      <div className="grid-auto" style={{ marginBottom: 12 }}>
        <StatTile label="Released" value={when(origin, o.release)} sub={o.firm ? "firm production order" : `MRP start ${o.mrp_start_date}`} />
        <StatTile label="Due" value={when(origin, o.due)} sub={`MRP due ${o.mrp_due_date}`} />
        <StatTile label="Finishes" value={when(origin, o.completion)} sub={o.tardy ? `late by ${hours(o.lateness_hours)}` : `${hours(-o.lateness_hours)} to spare`} />
        <StatTile label="Usable from" value={o.available_date ? day(o.available_date) : "—"} sub={o.days_late ? `${plural(o.days_late, "day")} after the plan's date` : "as the plan expects"}
          tone={o.days_late ? "hl" : undefined} />
        <StatTile label="vs EDD sequence" value={hours(o.completion - o.baseline_completion)} sub={o.completion < o.baseline_completion - 1e-6 ? "earlier" : o.completion > o.baseline_completion + 1e-6 ? "later" : "unchanged"} />
        {o.hold != null && <StatTile label="Held back until" value={when(origin, o.hold)} sub="not started earlier, so stock isn't built ahead of need" />}
      </div>
      {o.frozen && <p className="small" style={{ marginTop: 0 }}><Badge>frozen</Badge> Dated by an earlier schedule and starting inside the frozen zone
        (Settings → Frozen zone): it keeps its place and machine whatever else moves.</p>}
      <Parts res={res} id={id} />
      <table className="t nowrap">
        <thead><tr><th>Op</th><th>Resource</th><th className="num">Position</th><th>Start</th><th>End</th><th className="num">Setup</th><th className="num">Run</th><th>Sequence</th></tr></thead>
        <tbody>
          {keys.map((k) => {
            const parts = ops.filter((x) => x.key === k);
            const r = res.resources.find((x) => x.sequence.includes(k));
            const pos = r ? r.sequence.indexOf(k) : -1;
            return (
              <tr key={k}>
                <td className="num">{parts[0].seq}{parts.length > 1 && <span className="faint small"> ×{parts.length}</span>}</td>
                <td>{(parts[0].machines ?? []).length > 1 && !o.frozen
                  ? <select aria-label={`Machine for step ${parts[0].seq}`} value={parts[0].resource} disabled={busy} onChange={(e) => onto(k, e.target.value)}>
                    {(parts[0].machines ?? []).map((m) => <option key={m} value={m}>{m}{m !== parts[0].machines![0] ? " (alternative)" : ""}</option>)}
                  </select>
                  : parts[0].resource}</td>
                <td className="num">{pos + 1} / {r?.sequence.length}</td>
                <td>{when(origin, Math.min(...parts.map((p) => p.setup_start)))}</td>
                <td>{when(origin, Math.max(...parts.map((p) => p.end)))}</td>
                <td className="num">{hours(parts.reduce((a, p) => a + p.setup_hours, 0))}</td>
                <td className="num">{hours(parts.reduce((a, p) => a + p.run_hours, 0))}</td>
                <td>
                  <button className="btn sm" disabled={busy || o.frozen || pos <= 0} onClick={() => step(k, -1)} title="Swap with the operation before it">◀ earlier</button>{" "}
                  <button className="btn sm" disabled={busy || o.frozen || !r || pos >= r.sequence.length - 1} onClick={() => step(k, 1)} title="Swap with the operation after it">later ▶</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}

/** Where an order's parts come from, when they are there, and how long its steps waited for them. */
function Parts({ res, id }: { res: ScheduleResult; id: string }) {
  const o = res.orders.find((x) => x.id === id)!;
  const origin = res.origin!;
  if (!o.parts_from.length && !o.missing_parts.length) {
    return <p className="small muted" style={{ marginTop: 0 }}>Parts: all there when each step can start (from stock or earlier arrivals).</p>;
  }
  return (
    <div style={{ marginBottom: 12 }}>
      <p className="small" style={{ marginTop: 0 }}>
        {o.held_for_parts > 0 ? <><b>Waited {hours(o.held_for_parts)} for parts.</b> </> : <>Parts arrive after it is released, but in time for the step that uses them. </>}
        {o.missing_parts.length > 0 && <Badge sev="error">no supply for {o.missing_parts.join(", ")}</Badge>}
      </p>
      {o.parts_from.length > 0 && <div className="table-wrap"><table className="t nowrap">
        <thead><tr><th>Part</th><th>Comes from</th><th>There from</th></tr></thead>
        <tbody>{o.parts_from.map((p) => (
          <tr key={`${p.supply}-${p.product}`}>
            <td><Prod id={p.product} /></td>
            <td>{p.scheduled ? <a href={href("schedule", "board", p.supply)}>{p.supply}</a> : p.supply}
              <span className="faint small"> {p.scheduled ? "made on this schedule" : "incoming (purchase, transfer or order outside the window)"}</span></td>
            <td>{when(origin, p.available)}</td>
          </tr>))}
        </tbody>
      </table></div>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Orders({ res }: { res: ScheduleResult }) {
  const origin = res.origin!;
  const maxAbs = Math.max(1, ...res.orders.map((o) => Math.abs(o.lateness_hours)));
  return (
    <div className="stack">
      <Kpis res={res} />
      <Panel flush title="Orders by due date">
        <div className="table-wrap" style={{ maxHeight: 620 }}>
          <table className="t nowrap">
            <thead><tr><th>Order</th><th>Product</th><th className="num">Qty</th><th>Released</th><th>Parts</th><th>Due</th><th>Finishes</th>
              <th className="num">Lateness</th><th style={{ width: 200 }}>early ◀ │ ▶ late</th><th className="num">vs EDD</th></tr></thead>
            <tbody>
              {res.orders.map((o) => {
                const w = (Math.abs(o.lateness_hours) / maxAbs) * 50;
                return (
                  <tr key={o.id} className="clickable" onClick={() => go("schedule", "board", o.id)}>
                    <td><b>{o.id}</b> {o.firm && <Badge>firm</Badge>}</td><td><Prod id={o.product} /></td><td className="num">{qty(o.qty)}</td>
                    <td>{when(origin, o.release)}</td>
                    <td>{o.missing_parts.length ? <Badge sev="error">missing</Badge> : o.held_for_parts > 0 ? <Badge sev="warning">waited {hours(o.held_for_parts)}</Badge> : <span className="faint">·</span>}</td>
                    <td>{when(origin, o.due)}</td><td>{when(origin, o.completion)}</td>
                    <td className="num">{o.tardy ? <Badge sev="error">{hours(o.lateness_hours)}</Badge> : <span className="muted">{hours(o.lateness_hours)}</span>}</td>
                    <td>
                      <div style={{ position: "relative", height: 10 }}>
                        <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "var(--ink)" }} />
                        <div style={{ position: "absolute", top: 1, height: 8, background: o.tardy ? "var(--critical)" : "var(--good)",
                          left: o.tardy ? "50%" : `${50 - w}%`, width: `${w}%` }} />
                      </div>
                    </td>
                    <td className="num small">{Math.abs(o.completion - o.baseline_completion) < 1e-6 ? "·" : hours(o.completion - o.baseline_completion)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="Lateness = finish (last operation end + its queue time) − MRP due date; negative = time to spare. Parts: a step starts once the parts it uses are there (from stock, an incoming order, or the order on this schedule that makes them)."
        soWhat="A late order here is a real conflict on the shop floor or in the parts: move it up the sequence, add capacity, chase the part, or re-promise." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Resources({ res }: { res: ScheduleResult }) {
  const labour = [...new Set(res.labour.map((l) => l.resource))];
  const [pool, setPool] = useState(labour[0] ?? "");
  const days = res.labour.filter((l) => l.resource === pool);
  const over = res.labour.filter((l) => l.overload);
  return (
    <div className="stack">
      <Panel flush title="Resource load over the scheduling window">
        <div className="table-wrap">
          <table className="t nowrap">
            <thead><tr><th>Resource</th><th>Kind</th><th className="num">Units</th><th className="num">OEE</th><th style={{ width: 220 }}>Utilisation</th>
              <th className="num">Busy</th><th className="num">Setup</th><th className="num">Changeovers</th><th className="num">Operations</th></tr></thead>
            <tbody>
              {res.resources.map((r) => (
                <tr key={r.id}>
                  <td><b>{r.id}</b><div className="faint small">{r.name}</div></td><td>{r.kind}{!r.finite && <> · <Badge>infinite</Badge></>}</td>
                  <td className="num">{r.units}</td><td className="num">{pct(r.efficiency, 0)}</td>
                  <td><div className="row"><div className="bar-track" style={{ flex: 1, minWidth: 90 }}><div className="bar-fill" style={{ width: `${Math.min(100, r.utilization * 100)}%`,
                    background: r.utilization > 0.85 ? "var(--warning)" : "var(--series-1)" }} /></div><span className="num small">{pct(r.utilization, 0)}</span></div></td>
                  <td className="num">{hours(r.busy_hours)}</td><td className="num">{hours(r.setup_hours)}</td>
                  <td className="num">{r.changeovers}</td><td className="num">{r.sequence.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <SectionBand step="L" title="Labour pools" right={over.length ? <Badge sev="warning">{over.length} overloaded days</Badge> : <Badge sev="ok">within headcount</Badge>} />
      {labour.length === 0 ? <Panel><Empty title="No labour on the scheduled operations" /></Panel> : <>
        <div className="row wrap">{labour.map((l) => <button key={l} className={`btn sm ${l === pool ? "primary" : ""}`} onClick={() => setPool(l)}>{l}</button>)}</div>
        <Panel title={`${pool}: operator hours per day`}>
          <BucketChart labels={days.map((d) => d.date.slice(5))} unit=" h" series={[
            { name: "Required by the schedule", color: "var(--series-1)", values: days.map((d) => d.required), kind: "column" },
            { name: "Available (headcount × shift × efficiency)", color: "var(--text-2)", values: days.map((d) => d.available), kind: "step" },
          ]} />
        </Panel>
      </>}
      <Reading formula="Utilisation = clock hours with a job on a unit ÷ (shift hours × units) over the window. Labour = operation labour hours spread over the days the run is on the machine."
        soWhat="Labour pools are checked, not sequenced: an overloaded day needs overtime, a shift move, or a different sequence on the machines that draw on the pool." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
/** The setup matrix for one resource: rows = from group, columns = to group, cells = hours. */
function SetupMatrix({ ds, res }: { ds: Dataset; res: ScheduleResult | null }) {
  const used = useMemo(() => {
    const m = new Map<string, Set<string>>();
    const groupOf = (p: string) => (ds.products ?? []).find((x) => x.id === p)?.setup_group || p;
    for (const ps of ds.production_sources ?? []) {
      for (const op of ps.operations ?? []) {
        for (const r of [op.resource, ...(op.alternatives ?? [])]) {
          if (!r) continue;
          if (!m.has(r)) m.set(r, new Set());
          m.get(r)!.add(groupOf(ps.product));
        }
      }
    }
    return m;
  }, [ds]);
  const resources = [...used.keys()].sort();
  const [rid, setRid] = useState(resources[0] ?? "");
  const groups = [...(used.get(rid) ?? [])].sort();
  const cos = (ds.changeovers ?? []) as Changeover[];
  const find = (from: string, to: string) => cos.findIndex((c) => (c.resource ?? null) === rid && c.from_group === from && c.to_group === to);
  const generic = (from: string, to: string) => cos.find((c) => !c.resource && c.from_group === from && c.to_group === to);
  const setCell = (from: string, to: string, raw: string) => {
    const v = raw.trim() === "" ? null : Number(raw);
    if (v !== null && (!Number.isFinite(v) || v < 0)) return;
    store.update((d) => {
      const list = ((d.changeovers ?? []) as Changeover[]).filter((c) => !((c.resource ?? null) === rid && c.from_group === from && c.to_group === to));
      if (v !== null) list.push({ resource: rid, from_group: from, to_group: to, hours: v });
      d.changeovers = list;
    });
  };
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const op of res?.ops ?? []) {
      if (op.resource === rid && op.setup_from && op.setup_from !== op.group && op.setup_hours > 0) {
        m.set(`${op.setup_from}|${op.group}`, (m.get(`${op.setup_from}|${op.group}`) ?? 0) + 1);
      }
    }
    return m;
  }, [res, rid]);
  const fullSetup = (g: string) => {
    const hrs = (ds.production_sources ?? []).filter((ps) => ((ds.products ?? []).find((p) => p.id === ps.product)?.setup_group || ps.product) === g)
      .flatMap((ps) => (ps.operations ?? []).filter((o) => o.resource === rid).map((o) => o.setup_hours ?? 0));
    return hrs.length ? Math.max(...hrs) : 0;
  };
  const minor = ds.scheduling?.minor_setup_factor ?? 0.2;
  if (!resources.length) return <Panel><Empty title="No routings">Add operations to production sources to sequence resources.</Empty></Panel>;
  return (
    <div className="split" style={cols("minmax(0, 1fr) minmax(260px, 360px)")}>
      <div className="stack">
        <div className="row wrap">{resources.map((r) => <button key={r} className={`btn sm ${r === rid ? "primary" : ""}`} onClick={() => setRid(r)}>{r}</button>)}</div>
        <Panel flush title={`${rid}: changeover hours (from row → to column)`}>
          <div className="table-wrap">
            <table className="t nowrap">
              <thead><tr><th>from ↓ · to →</th>{groups.map((g) => <th key={g} className="num">{g}</th>)}</tr></thead>
              <tbody>
                {groups.map((f) => (
                  <tr key={f}>
                    <td><b>{f}</b></td>
                    {groups.map((t) => {
                      if (f === t) return <td key={t} className="num faint small">minor ×{minor}</td>;
                      const i = find(f, t);
                      const gen = generic(f, t);
                      const n = counts.get(`${f}|${t}`);
                      return (
                        <td key={t} className="num">
                          <input className="cell" aria-label={`${f} to ${t} hours`} defaultValue={i >= 0 ? String(cos[i].hours) : ""} key={`${rid}-${f}-${t}-${i >= 0 ? cos[i].hours : ""}`}
                            placeholder={gen ? `${gen.hours} (all)` : `${fullSetup(t)} (full)`} onBlur={(e) => setCell(f, t, e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
                          {n ? <div className="faint small">{n}× in schedule</div> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <Reading formula={<>Setup when a unit switches: nothing before → the operation's full setup; same product → none; same group → full × {minor};
        different group → this matrix (resource entry, else an “all resources” entry), else the full setup.</>}
        soWhat="Asymmetric changeovers (light → dark, thin → thick wire, allergen-free → allergen) are what campaigns exploit. Blank = fall back to the value in grey. Re-schedule after editing." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
/** The settings a method (a row of the comparison) runs with. */
function methodSettings(m: string): Record<string, unknown> {
  if (m === "optimize") return { optimizer: true, improve: true };
  if (m === "improve") return { optimizer: false, improve: true };
  return { start_rule: m, improve: false, optimizer: false };
}

/** Profiles (how to schedule, in one click), the comparison of every method on this window, and what each does. */
function Methods({ ds, res, running }: { ds: Dataset; res: ScheduleResult | null; running: boolean }) {
  const [cat, setCat] = useState<ScheduleCatalogue | null>(null);
  const [cmp, setCmp] = useState<ScheduleComparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const rev = useStore((s) => s.revision);
  const [cmpRev, setCmpRev] = useState(-1);
  useEffect(() => { api.scheduleCatalogue().then(setCat, (e) => setErr(String(e))); }, []);
  const cfg = (ds.scheduling ?? {}) as unknown as Record<string, unknown>;
  const current = String(cfg.profile ?? "balanced");
  const pick = async (patch: Record<string, unknown>, profile: string) => {
    store.update((d) => { d.scheduling = { ...(d.scheduling ?? {}), ...patch, profile } as unknown as Dataset["scheduling"]; });
    await store.run("schedule");
  };
  const compare = async () => {
    setBusy(true); setErr(null);
    try { setCmp(await api.compareSchedules(ds)); setCmpRev(rev); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const name = (m: string) => cat?.heuristics.find((h) => h.id === m)?.name ?? m;
  const rows = cmp?.rows ?? [];
  const worst = Math.max(1, ...rows.map((r) => r.kpis.objective));
  const cmpStale = cmp !== null && cmpRev !== rev;
  const inUse = (r: CompareRow) => {
    if (r.method === "optimize") return !!cfg.optimizer;
    if (r.method === "improve") return !cfg.optimizer && cfg.improve !== false;
    return !cfg.optimizer && cfg.improve === false && (cfg.start_rule ?? "edd") === r.method;
  };
  return (
    <div className="stack">
      {err && <div className="banner error"><Badge sev="error">That didn't work</Badge>{err}</div>}
      <Panel title="How to schedule" actions={res && <span className="small muted">now: <b>{current === "custom" ? "your own settings" : cat?.profiles.find((p) => p.id === current)?.name ?? current}</b></span>}>
        <p className="small" style={{ marginTop: 0 }}>A profile sets the start rule, the search and what the score weighs, together. Picking one schedules again; Undo puts
          the settings back. Change any field in Settings to make your own.</p>
        <div className="grid-auto">
          {(cat?.profiles ?? []).map((p) => {
            const on = current === p.id;
            return (
              <button key={p.id} className={`panel tile choice ${on ? "on" : ""}`} aria-pressed={on} disabled={running}
                onClick={() => pick(p.settings as Record<string, unknown>, p.id)} style={{ textAlign: "left", cursor: "pointer" }}>
                <div className="label">{on ? "✓ in use" : "profile"}</div>
                <div style={{ fontWeight: 650, margin: "2px 0 4px" }}>{p.name}</div>
                <div className="small muted">{p.what}</div>
              </button>
            );
          })}
        </div>
      </Panel>
      <Panel flush title="Compare the methods on these orders" actions={<button className="btn sm accent" onClick={compare} disabled={busy}>
        {busy ? "Scheduling every way…" : cmp ? "Compare again" : "Compare all methods"}</button>}>
        {!cmp ? <p className="small muted" style={{ padding: "0 14px 12px", margin: 0 }}>Schedules the same orders with every start rule, the local search and the optimiser,
          all scored with your current weights, so you can see which suits this week. Takes a few seconds.</p> : <>
          {cmpStale && <p className="small" style={{ padding: "0 14px", margin: 0 }}><Badge sev="warning">out of date</Badge> The data or settings changed since; compare again.</p>}
          <div className="table-wrap"><table className="t nowrap">
            <thead><tr><th>Method</th><th className="num">Late orders</th><th className="num">Hours late</th><th className="num">Changeovers</th>
              <th className="num">Hours early</th><th className="num">Weighted score</th><th style={{ width: 160 }}>lower is better</th><th className="num">Time</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.method}>
                <td><b>{name(r.method)}</b> {r.best && <Badge sev="ok">best</Badge>} {inUse(r) && <Badge>in use</Badge>}</td>
                <td className="num">{r.kpis.late_orders} / {r.kpis.orders}</td>
                <td className="num">{hours(r.kpis.tardiness_hours)}</td>
                <td className="num">{r.kpis.changeovers} <span className="faint small">{hours(r.kpis.setup_hours)}</span></td>
                <td className="num">{hours(r.kpis.earliness_hours)}</td>
                <td className="num"><b>{r.kpis.objective.toFixed(0)}</b></td>
                <td><div className="bar-track"><div className="bar-fill" style={{ width: `${(r.kpis.objective / worst) * 100}%`,
                  background: r.best ? "var(--good)" : "var(--series-1)" }} /></div></td>
                <td className="num small">{r.seconds < 0.05 ? "<0.1 s" : `${r.seconds.toFixed(1)} s`}</td>
                <td>{!inUse(r) && <button className="btn sm" disabled={running} onClick={() => pick(methodSettings(r.method), "custom")}>Use this</button>}</td>
              </tr>))}</tbody>
          </table></div>
          <p className="small muted" style={{ padding: "8px 14px 12px", margin: 0 }}>Score = {Object.entries(cmp.weights).filter(([, v]) => v > 0)
            .map(([k, v]) => `${v} × ${k === "tardiness" ? "hours late" : k === "setup" ? "changeover hours" : k === "earliness" ? "hours early" : "hours to clear the window"}`).join(" + ")}.
            The local search starts from the start rule in Settings; the optimiser starts from the local search's answer, so it is never worse.</p>
        </>}
      </Panel>
      <Panel flush title="What each method does">
        <div className="table-wrap"><table className="t">
          <thead><tr><th>Method</th><th>What it does</th><th>Good for</th><th>In SAP PP/DS</th></tr></thead>
          <tbody>{(cat?.heuristics ?? []).map((h) => (
            <tr key={h.id}><td style={{ minWidth: 150 }}><b>{h.name}</b></td><td className="small">{h.what}</td><td className="small">{h.good_for}</td><td className="small muted">{h.sap}</td></tr>))}</tbody>
        </table></div>
      </Panel>
      <Reading formula="Every method builds a sequence per machine and runs it through the same timing on the shift calendars (parts, queues, parallel units), so the scores compare like with like. Start rules are one pass; the local search tries moves and keeps those that lower the score; the optimiser (a constraint solver) chooses machines and order together, then its answer is timed exactly and kept only if it scores better."
        soWhat="If campaigns or the optimiser win clearly, make that your profile. If the start rules all score about the same, the capacity, not the sequence, is what makes orders late: look at Capacity levelling." />
    </div>
  );
}

const PROFILE_FIELDS = ["tardiness_weight", "setup_weight", "earliness_weight", "makespan_weight", "start_rule", "improve", "optimizer"];

function SettingsView({ ds }: { ds: Dataset }) {
  const schemaErrors = useStore((s) => s.schemaErrors);
  const errors: Record<string, string> = {};
  for (const e of schemaErrors) {
    const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
    if (loc[0] === "scheduling") errors[loc.slice(1).join(".")] = e.msg;
  }
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title="Scheduling rules">
        <SchemaForm defName="ScheduleSettings" value={(ds.scheduling ?? {}) as unknown as Obj} errors={errors}
          onChange={(next) => store.update((d) => {
            // changing what a profile sets makes the settings your own
            const was = (d.scheduling ?? {}) as unknown as Obj;
            const own = PROFILE_FIELDS.some((k) => next[k] !== was[k]);
            d.scheduling = { ...next, ...(own ? { profile: "custom" } : {}) } as unknown as Dataset["scheduling"];
          })} />
      </Panel>
      <Reading formula="The window picks which MRP orders are sequenced (by planned start). The weights score every schedule: hours late, changeover hours, hours early and hours to clear the window. A profile (Methods & profiles) sets the start rule, the search and the weights together; changing a field here makes it your own."
        soWhat="Raise the setup weight to favour longer campaigns; raise the tardiness weight to protect due dates; an earliness weight keeps stock from being built ahead. A frozen zone stops re-scheduling from moving orders about to start." />
    </div>
  );
}

