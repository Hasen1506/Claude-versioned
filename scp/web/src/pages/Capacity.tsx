// Capacity levelling: day by day, which machines and crews the supply plan asks for more hours than they have, which
// orders make up that load, and what planning within capacity would move (earlier, onto an alternative machine, or
// later). The daily load is the plan's own (each step's hours spread over the working days of its window); the day's
// capacity is the same arithmetic as Machines & shifts and the engine.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, LevelPreview, PlannedOrder, PlanResult, Resource, ResourcePlan } from "../api/types";
import { BucketChart } from "../components/charts";
import { Badge, Empty, Panel, Provenance, Reading, RunButton, StageHeader, StatTile } from "../components/ui";
import { day, pct, plural, qty } from "../lib/format";
import { Prod } from "../lib/names";
import { go, href } from "../lib/router";
import { calendarOf, dayCap, hoursOf } from "./Machines";
import { isStale, store, useStore } from "../state/store";

const DAY = 86400000;
const toT = (iso: string) => new Date(iso + "T00:00:00Z").getTime();
const iso = (t: number) => new Date(t).toISOString().slice(0, 10);
type Scale = "days" | "weeks";

interface DayRow { date: string; load: number; cap: number }
interface MachineLoad { r: Resource; rp: ResourcePlan; days: DayRow[]; over: DayRow[]; peak: DayRow | null }

/** Each machine's load and capacity for every day of the plan. */
function machineLoads(ds: Dataset, plan: PlanResult): MachineLoad[] {
  const start = toT(ds.settings.planning_start);
  const n = ds.settings.horizon_days ?? 182;
  const dayStart = ds.scheduling?.day_start_hour ?? 6;
  return (ds.resources ?? []).flatMap((r) => {
    const rp = plan.resources.find((x) => x.resource === r.id);
    if (!rp) return [];
    const cal = calendarOf(ds, r);
    const days: DayRow[] = [];
    for (let k = 0; k < n; k++) {
      const t = start + k * DAY;
      days.push({ date: iso(t), load: rp.daily_load?.[iso(t)] ?? 0, cap: hoursOf(dayCap(r, cal.isWork, t, dayStart)) });
    }
    const over = r.finite === false ? [] : days.filter((d) => d.load > d.cap + 1e-6);
    const peak = days.reduce<DayRow | null>((best, d) => (d.load > 0 && (!best || d.load / (d.cap || 1e-9) > best.load / (best.cap || 1e-9)) ? d : best), null);
    return [{ r, rp, days, over, peak }];
  });
}

const util = (d: DayRow) => (d.cap > 0 ? d.load / d.cap : d.load > 0 ? Infinity : 0);

export function Capacity({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset);
  if (!ds) return null;
  return <CapacityPage ds={ds} sel={route[1]} />;
}

function CapacityPage({ ds, sel }: { ds: Dataset; sel?: string }) {
  const run = useStore((s) => s.runs.plan);
  const plan = run.data;
  const stale = useStore((s) => isStale(s, "plan"));
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const loads = useMemo(() => (plan?.ok ? machineLoads(ds, plan) : []), [ds, plan]);
  const worst = loads.filter((m) => m.over.length).sort((a, b) => util(b.peak!) - util(a.peak!));
  const current = loads.find((m) => m.r.id === sel) ?? worst[0] ?? loads[0] ?? null;
  const on = !!ds.settings.capacity_constrained;
  const overDays = worst.reduce((a, m) => a + m.over.length, 0);

  const head = (
    <StageHeader title="Capacity levelling" kicker="Day by day, where the supply plan asks a machine or crew for more hours than it has, which orders make up that load, and what planning within capacity would move."
      how={<>Each step of an order puts its hours on its machine, spread evenly over the working days the plan gives it. A day is over when that load
        is more than the day's productive hours (shifts × units × efficiency, with any capacity change that day). Weekly totals can look fine while single days are not.</>}
      answer={plan?.ok ? (worst.length
        ? <>{plural(worst.length, "machine or crew", "machines or crews")} {worst.length === 1 ? "is" : "are"} asked for more than {worst.length === 1 ? "it has" : "they have"} on {plural(overDays, "day")};
          the worst is {worst[0].r.name || worst[0].r.id} at {pct(util(worst[0].peak!), 0)} on {day(worst[0].peak!.date)}.
          {on ? " Planning within capacity is on, but it never moves released production orders: what is left is theirs, or orders that fit nowhere. Click a red day to see which." : ""}</>
        : <>No machine or crew is asked for more hours than it has on any day{on ? ", because the plan keeps within capacity" : ""}.</>) : undefined}
      right={<>{plan && <Provenance kind="solved" at={run.at} stale={stale} />}
        <RunButton running={run.running} has={!!plan} onClick={() => store.run("plan")} disabled={blocking} /></>} />
  );
  if (!plan) {
    return <div>{head}<div className="content"><Panel><Empty title={blocking ? "Fix the data check first" : "No supply plan yet"}>
      {blocking ? <a className="btn" href={href("readiness")}>Open the data check</a>
        : <button className="btn" onClick={() => store.run("plan")} disabled={run.running}>Calculate the supply plan</button>}
    </Empty></Panel></div></div>;
  }
  if (!plan.ok) {
    return <div>{head}<div className="content"><div className="banner error"><Badge sev="error">Not planned</Badge>
      The data has blocking problems. <a href={href("readiness")}>Review them</a>.</div></div></div>;
  }
  return (
    <div>{head}<div className="content stack">
      <Levelling ds={ds} plan={plan} on={on} stale={stale} />
      {loads.length === 0 ? <Panel><Empty title="No machines or crews">Add resources and routings to see their load.</Empty></Panel> : <>
        <div className="row wrap" role="tablist" aria-label="Machines and crews">
          {loads.map((m) => (
            <button key={m.r.id} role="tab" aria-selected={m === current} className={`btn sm ${m === current ? "primary" : ""}`}
              onClick={() => go("capacity", m.r.id)}>
              {m.r.name || m.r.id}{" "}
              {m.r.finite === false ? <span className="faint small">not limited</span>
                : m.over.length ? <Badge sev="error">{plural(m.over.length, "day")} over</Badge> : <span className="faint small">{m.peak ? pct(util(m.peak), 0) : "idle"}</span>}
            </button>
          ))}
        </div>
        {current && <MachineView m={current} plan={plan} key={current.r.id} />}
      </>}
    </div></div>
  );
}

// ------------------------------------------------------------------------------------------------
function MachineView({ m, plan }: { m: MachineLoad; plan: PlanResult }) {
  const [scale, setScale] = useState<Scale>("days");
  const [pick, setPick] = useState<number | null>(null);
  const firstOver = m.over.length ? m.days.indexOf(m.over[0]) : -1;
  // days: eight weeks from the first overloaded day (or today); weeks: the whole plan
  const from = scale === "days" ? Math.max(0, Math.min(firstOver >= 0 ? firstOver - 3 : 0, m.days.length - 56)) : 0;
  const rows = useMemo(() => {
    if (scale === "days") return m.days.slice(from, from + 56).map((d) => ({ label: d.date.slice(5), from: d.date, to: d.date, load: d.load, cap: d.cap }));
    const out: { label: string; from: string; to: string; load: number; cap: number }[] = [];
    for (let i = 0; i < m.days.length; i += 7) {
      const w = m.days.slice(i, i + 7);
      out.push({ label: w[0].date.slice(5), from: w[0].date, to: w[w.length - 1].date, load: w.reduce((a, d) => a + d.load, 0), cap: w.reduce((a, d) => a + d.cap, 0) });
    }
    return out;
  }, [m, scale, from]);
  const sel = pick !== null ? rows[pick] : null;
  const orders = useMemo(() => new Map(plan.orders.map((o) => [o.id, o])), [plan]);
  const inRange = (d: string) => !!sel && d >= sel.from && d <= sel.to;
  const lines = sel ? m.rp.orders.map((ol) => ({ ol, h: Object.entries(ol.hours).filter(([d]) => inRange(d)).reduce((a, [, v]) => a + v, 0),
    total: Object.values(ol.hours).reduce((a, v) => a + v, 0) })).filter((x) => x.h > 1e-9).sort((a, b) => b.h - a.h) : [];
  const total = m.days.reduce((a, d) => a + d.load, 0);
  const capTotal = m.days.reduce((a, d) => a + d.cap, 0);
  const limited = m.r.finite !== false;
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Hours asked for" value={qty(total)} sub={`of ${qty(capTotal)} over the plan · ${pct(capTotal ? total / capTotal : 0, 0)}`} />
        <StatTile label="Days over capacity" value={limited ? String(m.over.length) : "—"} sub={limited ? (m.over.length ? `first ${day(m.over[0].date)}` : "none") : "this resource is not limited"}
          tone={m.over.length ? "hl" : undefined} />
        <StatTile label="Busiest day" value={m.peak ? pct(util(m.peak), 0) : "—"} sub={m.peak ? `${day(m.peak.date)}: ${qty(m.peak.load)} of ${qty(m.peak.cap)} h` : "no load"} />
        <StatTile label="Orders on it" value={String(m.rp.orders.length)} sub={`${m.rp.orders.filter((o) => o.firm).length} released`} />
      </div>
      <Panel title={<h3>{m.r.name || m.r.id}: hours asked for {scale === "days" ? "each day" : "each week"}</h3>} actions={
        <div className="row">
          {(["days", "weeks"] as Scale[]).map((s) => <button key={s} className={`btn sm ${scale === s ? "primary" : ""}`} onClick={() => { setScale(s); setPick(null); }}>
            {s === "days" ? "Days (8 weeks)" : "Weeks (whole plan)"}</button>)}
          <a className="btn sm ghost" href={href("machines", m.r.id)}>Shifts</a>
        </div>}>
        <BucketChart labels={rows.map((r) => r.label)} unit=" h" height={240} picked={pick} onPick={(i) => setPick(i === pick ? null : i)}
          series={[
            { name: "Hours asked for", color: "var(--series-1)", values: rows.map((r) => r.load), kind: "column",
              colorAt: (i) => (limited && rows[i].load > rows[i].cap + 1e-6 ? "var(--critical)" : undefined) },
            { name: "Hours it has", color: "var(--text-2)", values: rows.map((r) => r.cap), kind: "step" },
          ]} />
        <div className="legend" style={{ marginTop: 6 }}>
          {limited && <span><span className="key box" style={{ background: "var(--critical)" }} />more than it has</span>}
          <span className="faint small">Click a {scale === "days" ? "day" : "week"} to see the orders on it.</span>
        </div>
      </Panel>
      {sel && <Panel flush title={<h3>Orders on {m.r.name || m.r.id}, {sel.from === sel.to ? day(sel.from) : `week of ${day(sel.from)}`}:
        {" "}{qty(sel.load)} of {qty(sel.cap)} h</h3>} actions={<button className="btn sm ghost" onClick={() => setPick(null)}>Close</button>}>
        {lines.length === 0 ? <Empty title="Nothing runs on it then" /> : (
          <div className="table-wrap"><table className="t nowrap">
            <thead><tr><th>Order</th><th>Product</th><th className="num">Hours then</th><th className="num">Hours in all</th><th>Runs</th><th>Needed by</th><th>Levelling</th></tr></thead>
            <tbody>{lines.map(({ ol, h, total: t }) => {
              const o: PlannedOrder | undefined = orders.get(ol.order);
              return (
                <tr key={ol.order}>
                  <td>{o ? <a href={href("plan", "orders", o.id)}><b>{ol.order}</b></a> : <b>{ol.order}</b>} {ol.firm && <Badge>released</Badge>}</td>
                  <td><Prod id={ol.product} /></td>
                  <td className="num">{qty(h)}</td><td className="num">{qty(t)}</td>
                  <td>{o ? `${day(o.start_date)} → ${day(o.due_date)}` : "—"}</td>
                  <td>{o ? day(o.need_date) : "—"}</td>
                  <td>{!o ? <span className="faint small">released: moves only by re-dating it</span>
                    : o.capacity_shift_days < 0 ? <Badge sev="info">{plural(-o.capacity_shift_days, "day")} earlier</Badge>
                    : o.capacity_shift_days > 0 ? <Badge sev="warning">{plural(o.capacity_shift_days, "day")} later</Badge>
                    : Object.keys(o.step_resources ?? {}).length ? <Badge sev="info">on {Object.values(o.step_resources ?? {}).join(", ")}</Badge>
                    : <span className="faint">·</span>}</td>
                </tr>
              );
            })}</tbody>
          </table></div>
        )}
      </Panel>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
/** Planning within capacity: what it would move, switching it on or off, and keeping the levelled dates. */
function Levelling({ ds, plan, on, stale }: { ds: Dataset; plan: PlanResult; on: boolean; stale: boolean }) {
  const [preview, setPreview] = useState<LevelPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const moved = plan.orders.filter((o) => o.capacity_shift_days !== 0 || Object.keys(o.step_resources ?? {}).length > 0);
  const show = async () => {
    setBusy(true); setErr(null);
    try { setPreview(await api.level(ds)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const toggle = async (v: boolean) => {
    store.update((d) => { d.settings.capacity_constrained = v; });
    setPreview(null);
    await store.run("plan");
  };
  const keep = async () => {
    setBusy(true); setErr(null);
    try {
      const out = await api.firm(ds, moved.map((o) => o.id));
      store.replace(out.dataset);
      setMsg(`${plural(out.report.firmed.length, "order")} kept at their levelled dates as production orders.`);
      setAsking(false);
      await store.run("plan");
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const early = preview?.moves.filter((m) => m.shift_days < 0).length ?? 0;
  const later = preview?.moves.filter((m) => m.shift_days > 0).length ?? 0;
  const alt = preview?.moves.filter((m) => Object.keys(m.step_resources ?? {}).length).length ?? 0;
  return (
    <Panel title={<h3>Plan within capacity <Badge sev={on ? "ok" : undefined}>{on ? "on" : "off"}</Badge></h3>} actions={<div className="row wrap">
      <button className="btn sm" onClick={show} disabled={busy}>{busy && !asking ? "Working…" : "Show what levelling moves"}</button>
      {on ? <button className="btn sm ghost" onClick={() => toggle(false)} disabled={busy}>Go back to unlimited capacity</button>
        : <button className="btn sm accent" onClick={() => toggle(true)} disabled={busy}>Plan within capacity</button>}
      {on && moved.length > 0 && <button className="btn sm" onClick={() => setAsking(true)} disabled={busy || stale}
        title={stale ? "Recalculate the supply plan first" : "Make the moved orders firm production orders at their levelled dates"}>Keep these dates</button>}
    </div>}>
      <p className="small" style={{ marginTop: 0 }}>{on
        ? <>The supply plan keeps every limited machine and crew within its day. An order that doesn't fit goes to an alternative machine, else starts earlier
          (never before today), else finishes later and is reported. {moved.length ? <>{plural(moved.length, "order")} moved in this plan.</> : "Nothing had to move."}</>
        : <>The supply plan now assumes unlimited capacity: each order goes where its dates say, even onto a full machine; the shop floor schedule then
          finds out. Planning within capacity moves orders to where they fit instead.</>}</p>
      {err && <div className="banner error"><Badge sev="error">That didn't work</Badge>{err}</div>}
      {msg && <div className="banner ok"><span>{msg}</span><span className="spacer" /><button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
      {asking && <div className="banner warning" role="alertdialog" aria-label="Keep the levelled dates">
        <Badge sev="warning">Check</Badge>
        <span>This makes {plural(moved.length, "planned order")} firm production orders at the dates levelling gave them, so they stay there even if you
          switch levelling off. Undo reverts it.</span><span className="spacer" />
        <button className="btn sm accent" onClick={keep} disabled={busy}>{busy ? "Saving…" : "Keep the dates"}</button>
        <button className="btn sm ghost" onClick={() => setAsking(false)} disabled={busy}>Cancel</button>
      </div>}
      {preview && preview.ok && <>
        <p className="small"><b>Levelling moves {plural(preview.moves.length, "order")}</b>: {early} earlier, {alt} onto an alternative machine, {later} later.
          Orders finishing after they are needed: {preview.late_before} → {preview.late_after}. Demand on time: {pct(preview.fill_before, 1)} → {pct(preview.fill_after, 1)}.</p>
        <div className="table-wrap"><table className="t nowrap">
          <thead><tr><th>Machine or crew</th><th className="num">Busiest day</th><th className="num">Days over</th><th className="num">Hours</th></tr></thead>
          <tbody>{preview.resources.filter((r) => r.hours > 0).map((r) => (
            <tr key={r.resource}>
              <td>{(ds.resources ?? []).find((x) => x.id === r.resource)?.name || r.resource}{!r.finite && <span className="faint small"> not limited</span>}</td>
              <td className="num">{pct(r.peak_before, 0)} → <b className={r.peak_after > 1 + 1e-6 ? "neg" : ""}>{pct(r.peak_after, 0)}</b></td>
              <td className="num">{r.overloaded_days_before} → <b>{r.overloaded_days_after}</b></td>
              <td className="num">{qty(r.hours)}</td>
            </tr>))}</tbody>
        </table></div>
        {preview.moves.length > 0 && <div className="table-wrap" style={{ maxHeight: 320, marginTop: 10 }}><table className="t nowrap">
          <thead><tr><th>Product</th><th className="num">Qty</th><th>Needed by</th><th>Starts</th><th>Usable from</th><th>Change</th></tr></thead>
          <tbody>{preview.moves.map((mv) => (
            <tr key={mv.order}>
              <td><Prod id={mv.product} /></td><td className="num">{qty(mv.qty)}</td><td>{day(mv.need_date)}</td>
              <td>{day(mv.was_start)} → {day(mv.start)}</td><td>{day(mv.was_available)} → {day(mv.available)}</td>
              <td>{mv.late_days > 0 ? <Badge sev="warning">{mv.shift_days > 0 ? `${plural(mv.shift_days, "day")} later, ` : ""}{plural(mv.late_days, "day")} late in all</Badge>
                : mv.shift_days < 0 ? <Badge sev="info">{plural(-mv.shift_days, "day")} earlier</Badge>
                : Object.keys(mv.step_resources ?? {}).length ? <Badge sev="info">on {Object.values(mv.step_resources ?? {}).join(", ")}</Badge>
                : <span className="faint">·</span>}</td>
            </tr>))}</tbody>
        </table></div>}
      </>}
      <Reading formula="Levelling places orders one at a time in planning order (finished goods first, released orders before planned ones): on the step's own machine if the days it needs have room, else on its first alternative that does, else a day earlier at a time, else a day later at a time."
        soWhat="Earlier means stock is built ahead (holding cost); later means a customer date is at risk. Adding a shift or overtime on the busiest machine is often cheaper than either." />
    </Panel>
  );
}
