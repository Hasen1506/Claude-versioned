import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Changeover, Dataset, ScheduledOp, ScheduleResource, ScheduleResult } from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, cols, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, useTooltip,
} from "../components/ui";
import { pct, qty } from "../lib/format";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "board" | "orders" | "resources" | "setups" | "settings";

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
  const view = ((route[1] as View) || "board") as View;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  /** Re-decode with a hand-edited sequence on one resource (every other resource keeps its order). */
  const resequence = async (resource: string, seq: string[]) => {
    if (!res) return;
    setBusy(true);
    setErr(null);
    try {
      const all = Object.fromEntries(res.resources.map((r) => [r.id, r.sequence]));
      all[resource] = seq;
      store.put("schedule", await api.schedule(ds, all), rev);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const head = (
    <StageHeader n="07" title="Detailed scheduling" kicker={<>Finite sequencing of the released production orders on each machine
      and line, in clock time on the shift calendar: sequence-dependent changeovers, parallel units, queue times. The improver
      groups setup families into campaigns without letting orders slip further.</>} right={<>
      {res && <Provenance kind="solved" at={run.at} stale={stale} />}
      {res?.search.mode === "manual" && <button className="btn" onClick={() => store.run("schedule")} disabled={run.running}>Reset to optimised</button>}
      <button className="btn accent" onClick={() => store.run("schedule")} disabled={run.running || blocking}>
        {run.running ? "Scheduling…" : res ? "Re-schedule" : "Schedule"}
      </button></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  if (view === "settings") return body(<><Nav view={view} res={res} /><SettingsView ds={ds} /></>);
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
    {err && <div className="banner error"><Badge sev="error">Re-sequencing failed</Badge>{err}</div>}
    {res.violations.length > 0 && (
      <div className="banner error"><Badge sev="error">{res.violations.length} feasibility violations</Badge>{res.violations.slice(0, 3).join(" · ")}</div>
    )}
    {res.search.mode === "manual" && (
      <div className="banner info"><Badge sev="info">Manual sequence</Badge>
        <span>You changed the order on a resource; the schedule was re-timed with your sequence. Undo is “Reset to optimised”.</span></div>
    )}
    <Nav view={view} res={res} />
    {view === "board" && <Board res={res} sel={route[2]} busy={busy} onResequence={resequence} />}
    {view === "orders" && <Orders res={res} />}
    {view === "resources" && <Resources res={res} />}
  </>);
}

function Nav({ view, res }: { view: View; res: ScheduleResult | null }) {
  return (
    <Tabs<View> value={view} onChange={(v) => go("schedule", v)} tabs={[
      { id: "board", label: "Planning board" },
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
      <StatTile label="Late orders" value={`${k.late_orders} / ${k.orders}`} sub={delta(k.late_orders, b.late_orders, (v) => `${v}`)} tone={k.late_orders ? undefined : "hl"} />
      <StatTile label="Tardiness" value={hours(k.tardiness_hours)} sub={`${delta(k.tardiness_hours, b.tardiness_hours, hours)} · worst ${hours(Math.max(0, k.max_lateness_hours))}`} />
      <StatTile label="Changeover time" value={hours(k.setup_hours)} sub={`${k.changeovers} changeovers · ${delta(k.setup_hours, b.setup_hours, hours)}`} />
      {busiest && <StatTile label="Busiest resource" value={pct(busiest.utilization, 0)} sub={`${busiest.id} over the window`} />}
      <StatTile label="Sequencer" value={res.search.mode !== "improved" ? res.search.mode.toUpperCase()
        : res.search.moves_accepted ? `${res.search.moves_accepted} moves` : "EDD kept"}
        sub={res.search.mode === "manual" ? "your sequence, re-timed" : res.search.mode === "edd" ? "local search off"
          : res.search.moves_accepted ? `${res.search.moves_tried} tried · ${res.search.seconds.toFixed(2)} s · ${res.search.stopped.replace("_", " ")}`
          : `no improving move in ${res.search.moves_tried} tried`} />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
const ZOOMS: [string, number][] = [["Month", 1.2], ["2 weeks", 2.6], ["Week", 5.2], ["Days", 12]];

function Board({ res, sel, busy, onResequence }: {
  res: ScheduleResult; sel?: string; busy: boolean; onResequence: (resource: string, seq: string[]) => void;
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
        <Gantt res={res} pxh={zoom} sel={order?.id ?? null} colors={colors} />
        <div className="legend" style={{ padding: "8px 12px" }}>
          {Object.entries(colors).map(([g, c]) => <span key={g}><span className="key box" style={{ background: c }} />{g}</span>)}
          <span><span className="key box gantt-setup-key" />changeover</span>
          <span><span className="key box gantt-off-key" />off shift</span>
          <span><span className="key box" style={{ background: "transparent", outline: "2px solid var(--critical)" }} />late order</span>
        </div>
      </Panel>
      {order ? <OrderDetail res={res} id={order.id} busy={busy} onResequence={onResequence} />
        : <p className="faint small" style={{ margin: 0 }}>Click an operation to follow its order across resources, see its due date and move it in the sequence.</p>}
      <SectionBand step="ƒ" title="How it is computed" />
      <Reading formula={<>Each resource works its sequence in order; an operation starts at max(order release or predecessor end + queue, unit free),
        sets up (nothing before → full setup; same product → 0; same group → minor setup; other group → setup matrix), then runs
        work ÷ OEE clock hours inside shift windows. Objective = w<sub>T</sub>·Σ tardiness + w<sub>S</sub>·Σ setup hours; the improver pulls operations
        behind the nearest same-group operation (campaigns) and swaps neighbours, keeping only changes that lower the objective.</>}
        soWhat="Late orders here are the ones infinite-capacity MRP could not see: either resequence, add a shift or overtime, or let promising (ATP/CTP) quote the later date." />
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

function Gantt({ res, pxh, sel, colors }: { res: ScheduleResult; pxh: number; sel: string | null; colors: Record<string, string> }) {
  const tip = useTooltip();
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
            <line x1={x(selOrder.release)} x2={x(selOrder.release)} y1={TOP} y2={H} stroke="var(--text-2)" strokeDasharray="2 3" strokeWidth={1.5} />
            <line x1={x(selOrder.due)} x2={x(selOrder.due)} y1={TOP} y2={H} stroke={selOrder.tardy ? "var(--critical)" : "var(--good)"} strokeDasharray="5 3" strokeWidth={2} />
            <text x={x(selOrder.due) + 4} y={H - 6} style={{ fill: "var(--text)" }}>due {selOrder.id}</text>
          </>}
          {/* operations */}
          {res.ops.map((op) => {
            const li = laneOf(op);
            if (li < 0) return null;
            const y = TOP + li * RH + 3;
            const h = RH - 6;
            const wins = lanes[li].resource.windows;
            const dim = sel && op.order !== sel ? 0.22 : 1;
            const c = colors[op.group];
            const ord = orderById[op.order];
            const show = (e: React.MouseEvent) => tip.show(e, <div>
              <b>{op.order}</b> · {op.product} {ord?.firm && <Badge>firm</Badge>}
              <div className="faint small">{op.resource} unit {op.unit + 1} · operation {op.seq}{op.sub > 0 || res.ops.some((o) => o.key === op.key && o.sub > 0) ? ` · sublot ${op.sub + 1}` : ""}</div>
              <div className="small">{qty(op.qty)} units</div>
              {op.setup_hours > 0 && <div className="small">Setup {hours(op.setup_hours)} {op.setup_from ? `(${op.setup_from} → ${op.group})` : "(first on unit)"}</div>}
              <div className="small">Run {hours(op.run_hours)} · {when(origin, op.run_start)} → {when(origin, op.end)}</div>
              {ord && <div className="small">Order due {when(origin, ord.due)} · {ord.tardy ? <b style={{ color: "var(--critical)" }}>late {hours(ord.lateness_hours)}</b> : `${hours(-ord.lateness_hours)} early`}</div>}
            </div>);
            const run = segments(op.run_start, op.end, wins);
            return (
              <g key={op.id} data-order={op.order} opacity={dim} style={{ cursor: "pointer" }} onClick={() => go("schedule", "board", op.order === sel ? undefined : op.order)}
                onMouseMove={show} onMouseLeave={tip.hide}>
                {segments(op.setup_start, op.run_start, wins).map(([a, b]) => (
                  <rect key={`s${a}`} x={x(a)} y={y} width={Math.max(1, x(b) - x(a))} height={h} fill="url(#gantt-setup)" stroke="var(--surface)" strokeWidth={1} />
                ))}
                {run.map(([a, b]) => (
                  <rect key={`r${a}`} x={x(a)} y={y} width={Math.max(1.5, x(b) - x(a))} height={h} fill={c}
                    stroke={op.late ? "var(--critical)" : "var(--surface)"} strokeWidth={op.late ? 2 : 1} />
                ))}
                {run.length > 0 && x(run[0][1]) - x(run[0][0]) > 46 && (
                  <text x={x(run[0][0]) + 4} y={y + h / 2 + 3.5} style={{ fill: "var(--surface)", fontWeight: 700, pointerEvents: "none" }}>{op.order.replace(/^MO-0*/, "")}</text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {tip.node}
    </div>
  );
}

function OrderDetail({ res, id, busy, onResequence }: {
  res: ScheduleResult; id: string; busy: boolean; onResequence: (resource: string, seq: string[]) => void;
}) {
  const o = res.orders.find((x) => x.id === id)!;
  const origin = res.origin!;
  const ops = res.ops.filter((x) => x.order === id).sort((a, b) => a.seq - b.seq || a.sub - b.sub);
  const keys = [...new Set(ops.map((x) => x.key))];
  const move = (key: string, dir: -1 | 1) => {
    const r = res.resources.find((x) => x.sequence.includes(key))!;
    const seq = [...r.sequence];
    const i = seq.indexOf(key);
    const j = i + dir;
    if (j < 0 || j >= seq.length) return;
    [seq[i], seq[j]] = [seq[j], seq[i]];
    onResequence(r.id, seq);
  };
  return (
    <Panel title={`${o.id} · ${o.product} · ${qty(o.qty)} units`} actions={<button className="btn sm ghost" onClick={() => go("schedule", "board")}>Close</button>}>
      <div className="grid-auto" style={{ marginBottom: 12 }}>
        <StatTile label="Released" value={when(origin, o.release)} sub={o.firm ? "firm production order" : `MRP start ${o.mrp_start_date}`} />
        <StatTile label="Due" value={when(origin, o.due)} sub={`MRP due ${o.mrp_due_date}`} />
        <StatTile label="Finishes" value={when(origin, o.completion)} sub={o.tardy ? `late by ${hours(o.lateness_hours)}` : `${hours(-o.lateness_hours)} to spare`} />
        <StatTile label="vs EDD sequence" value={hours(o.completion - o.baseline_completion)} sub={o.completion < o.baseline_completion - 1e-6 ? "earlier" : o.completion > o.baseline_completion + 1e-6 ? "later" : "unchanged"} />
      </div>
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
                <td>{parts[0].resource}</td>
                <td className="num">{pos + 1} / {r?.sequence.length}</td>
                <td>{when(origin, Math.min(...parts.map((p) => p.setup_start)))}</td>
                <td>{when(origin, Math.max(...parts.map((p) => p.end)))}</td>
                <td className="num">{hours(parts.reduce((a, p) => a + p.setup_hours, 0))}</td>
                <td className="num">{hours(parts.reduce((a, p) => a + p.run_hours, 0))}</td>
                <td>
                  <button className="btn sm" disabled={busy || pos <= 0} onClick={() => move(k, -1)} title="Swap with the operation before it">◀ earlier</button>{" "}
                  <button className="btn sm" disabled={busy || !r || pos >= r.sequence.length - 1} onClick={() => move(k, 1)} title="Swap with the operation after it">later ▶</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
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
            <thead><tr><th>Order</th><th>Product</th><th className="num">Qty</th><th>Released</th><th>Due</th><th>Finishes</th>
              <th className="num">Lateness</th><th style={{ width: 200 }}>early ◀ │ ▶ late</th><th className="num">vs EDD</th></tr></thead>
            <tbody>
              {res.orders.map((o) => {
                const w = (Math.abs(o.lateness_hours) / maxAbs) * 50;
                return (
                  <tr key={o.id} className="clickable" onClick={() => go("schedule", "board", o.id)}>
                    <td><b>{o.id}</b> {o.firm && <Badge>firm</Badge>}</td><td>{o.product}</td><td className="num">{qty(o.qty)}</td>
                    <td>{when(origin, o.release)}</td><td>{when(origin, o.due)}</td><td>{when(origin, o.completion)}</td>
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
      <Reading formula="Lateness = finish (last operation end + its queue time) − MRP due date; negative = time to spare."
        soWhat="MRP dates assume infinite capacity. A late order here is a real conflict on the shop floor: move it up the sequence, add capacity, or re-promise." />
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
        if (!m.has(op.resource)) m.set(op.resource, new Set());
        m.get(op.resource)!.add(groupOf(ps.product));
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
          onChange={(next) => store.update((d) => { d.scheduling = next as unknown as Dataset["scheduling"]; })} />
      </Panel>
      <Reading formula="The window picks which MRP orders are sequenced (by planned start). Weights trade tardiness hours against changeover hours in the improver's objective."
        soWhat="Raise the setup weight to favour longer campaigns; raise the tardiness weight to protect due dates. Turn the improver off to see the pure EDD sequence." />
    </div>
  );
}

