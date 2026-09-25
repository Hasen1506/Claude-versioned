import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, Kpi, TowerResult, WorkItem, WorkItemEntry } from "../api/types";
import {
  Badge, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, type Severity,
} from "../components/ui";
import { day, money, pct, qty, unitMoney } from "../lib/format";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "kpis" | "worklist" | "quality" | "settings";

// The §18.2 set, grouped the way a weekly review reads it.
const GROUPS: { title: string; ids: string[] }[] = [
  { title: "Demand", ids: ["forecast_accuracy", "forecast_bias"] },
  { title: "Customer service", ids: ["confirmation_rate", "otif_confirmed", "otif_requested", "perfect_order"] },
  { title: "Supply & production", ids: ["supplier_reliability", "schedule_adherence"] },
  { title: "Inventory", ids: ["days_of_supply", "excess_obsolete"] },
  { title: "Planning process & cost", ids: ["plan_stability", "exception_ageing", "cost_to_serve"] },
];

const STATUS_SEV: Record<string, Severity | undefined> = { good: "ok", warning: "warning", critical: "error" };
const STATUS_LABEL: Record<string, string> = { good: "On target", warning: "Near target", critical: "Off target", none: "No data" };
const ITEM_SEV: Record<string, Severity> = { error: "error", warning: "warning", info: "info" };

function fmtKpi(k: Pick<Kpi, "unit">, v: number | null | undefined, cur: string): string {
  if (v === null || v === undefined) return "—";
  if (k.unit === "ratio") return pct(v, 1);
  if (k.unit === "days") return `${qty(v)} d`;
  if (k.unit === "money_per_unit") return unitMoney(v, cur);
  return money(v, cur);
}

function targetText(k: Kpi, cur: string): string {
  if (k.target === null || k.direction === "none") return "no target";
  const t = fmtKpi(k, k.target, cur);
  return k.direction === "up" ? `target ≥ ${t}` : k.direction === "down" ? `target ≤ ${t}` : `target within ±${t}`;
}

export function Tower({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.tower);
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "tower"));
  const view = ((route[1] as View) || "kpis") as View;
  const cur = ds.settings.currency;

  const head = (
    <StageHeader n="11" title="Control tower" kicker={<>How the supply chain is performing and what needs a planner now. The KPI set
      of the S/4 guide §18.2, each with its definition, source and target; one worklist of exceptions from every stage with an owner,
      an age on the planning clock and an SLA, kept across runs; master-data defects in their own data-quality view.</>} right={<>
      {res && <Provenance kind="derived" at={run.at} stale={stale} />}
      <button className="btn accent" onClick={() => store.run("tower")} disabled={run.running}>
        {run.running ? "Refreshing…" : res ? "Refresh" : "Refresh tower"}
      </button></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  const live = res?.worklist.filter((w) => w.status === "open" || w.status === "acknowledged") ?? [];
  const nav = (
    <Tabs<View> value={view} onChange={(v) => go("tower", v)} tabs={[
      { id: "kpis", label: "KPIs", count: res?.kpis.length },
      { id: "worklist", label: "Exception worklist", count: res ? live.length : undefined },
      { id: "quality", label: "Data quality", count: res?.data_quality.reduce((a, r) => a + r.count, 0) },
      { id: "settings", label: "Owners, SLA & targets" },
    ]} />
  );
  if (view === "settings") return body(<>{nav}<Settings ds={ds} /></>);
  if (run.error) return body(<div className="banner error"><Badge sev="error">Could not refresh the tower</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      <SolverIO answers="Are we forecasting, serving, buying, making and stocking well — against target — and which exceptions are open, whose they are and for how long."
        from="The accuracy and closed-order logs (Execution), promises, the supply plan and its exceptions, the finance overlay, earlier base versions and the worklist history."
        feeds="The weekly performance review and each planner's day: every exception links back to the stage that resolves it." />
      <div style={{ height: 14 }} />
      <Panel><Empty title="Tower not refreshed yet">
        <p>Refreshing plans supply, checks promises and records today's exceptions against {day(ds.settings.planning_start)} (the planning clock).</p>
      </Empty></Panel></>);
  }
  return body(<>
    {stale && <StaleMark what="tower" onRerun={() => store.run("tower")} busy={run.running} />}
    {nav}
    {view === "kpis" && <Kpis res={res} cur={cur} sel={route[2]} />}
    {view === "worklist" && <Worklist res={res} ds={ds} rev={run.revision ?? 0} />}
    {view === "quality" && <Quality res={res} />}
  </>);
}

// ------------------------------------------------------------------------------------------------
function Kpis({ res, cur, sel }: { res: TowerResult; cur: string; sel?: string }) {
  const by = Object.fromEntries(res.kpis.map((k) => [k.id, k]));
  const cur_ = by[sel ?? ""] ?? res.kpis.find((k) => k.status === "critical") ?? res.kpis[0];
  const count = (s: string) => res.kpis.filter((k) => k.status === s).length;
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="On target" value={count("good")} sub={`of ${res.kpis.length} KPIs`} />
        <StatTile label="Near target" value={count("warning")} />
        <StatTile label="Off target" value={count("critical")} tone={count("critical") ? "hl" : undefined} />
        <StatTile label="No data yet" value={count("none")} sub="not graded" />
        <StatTile label="Measured up to" value={day(res.as_of)} sub="the planning start" />
      </div>
      {GROUPS.map((g) => (
        <div key={g.title}>
          <SectionBand title={g.title} />
          <div className="kpi-grid">
            {g.ids.filter((id) => by[id]).map((id) => {
              const k = by[id];
              return (
                <button key={id} className={`kpi-card ${k.status} ${cur_?.id === id ? "on" : ""}`} onClick={() => go("tower", "kpis", id)}
                  aria-pressed={cur_?.id === id} aria-label={`${k.name}: ${fmtKpi(k, k.value, cur)}, ${STATUS_LABEL[k.status]}`}>
                  <span className="kpi-name">{k.name}</span>
                  <span className="kpi-value">{fmtKpi(k, k.value, cur)}</span>
                  <span className="kpi-foot">
                    {STATUS_SEV[k.status] ? <Badge sev={STATUS_SEV[k.status]}>{STATUS_LABEL[k.status]}</Badge> : <span className="faint">{STATUS_LABEL[k.status]}</span>}
                    <span className="faint">{targetText(k, cur)}</span>
                  </span>
                  <span className="kpi-n faint">{k.n ? `${qty(k.n)} observations` : k.note ? "—" : ""}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {cur_ && <KpiDetail k={cur_} cur={cur} />}
    </div>
  );
}

function KpiDetail({ k, cur }: { k: Kpi; cur: string }) {
  const max = Math.max(1e-9, ...k.breakdown.map((r) => Math.abs(r.value ?? 0)), k.unit === "ratio" ? 1 : 0);
  const ratio = k.unit === "ratio";
  return (
    <>
      <SectionBand title={k.name} right={<span className="faint small">{targetText(k, cur)}</span>} />
      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="stack">
          <Reading formula={k.definition} soWhat={<>Source: {k.source}.{k.note && <> {k.note}</>}</>} />
          {k.value !== null && ratio && <div className="faint small">{qty(k.numerator)} of {qty(k.denominator)} ({k.id === "forecast_bias" ? "Σ forecast − Σ actual over Σ actual" : "numerator over denominator"})</div>}
        </div>
        <Panel flush title={k.breakdown_by ? `By ${k.breakdown_by}` : "Breakdown"}>
          {k.breakdown.length === 0 ? <p className="faint small" style={{ padding: 12 }}>Nothing to break down yet.</p> : (
            <div className="table-wrap" style={{ maxHeight: 360 }}>
              <table className="t">
                <thead><tr><th>{k.breakdown_by || "Item"}</th><th className="num">Value</th><th style={{ width: "40%" }} /><th className="num">n / base</th></tr></thead>
                <tbody>
                  {k.breakdown.map((r) => {
                    const bad = k.target !== null && r.value !== null && (
                      (k.direction === "up" && r.value < k.target) || (k.direction === "down" && r.value > k.target)
                      || (k.direction === "zero" && Math.abs(r.value) > k.target));
                    return (
                      <tr key={r.label}>
                        <td>{r.label}</td>
                        <td className={`num ${bad ? "neg" : ""}`}>{k.id === "excess_obsolete" ? money(r.value, cur) : fmtKpi(k, r.value, cur)}</td>
                        <td>
                          <div className="bar-track" style={{ position: "relative" }}>
                            <div className="bar-fill" style={{ width: `${(Math.abs(r.value ?? 0) / max) * 100}%`, background: bad ? "var(--critical)" : "var(--series-1)" }} />
                            {ratio && k.target !== null && k.direction === "up" && <span className="bar-target" style={{ left: `${(k.target / max) * 100}%` }} />}
                          </div>
                        </td>
                        <td className="num faint">{k.id === "excess_obsolete" ? "" : `${qty(r.numerator)} / ${qty(r.denominator)}`}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

// ------------------------------------------------------------------------------------------------
const CAT_LINK: Record<string, string[]> = {
  coverage: ["plan", "exceptions"], capacity: ["plan", "capacity"], inventory: ["inventory"], orders: ["execution", "orders"],
  delivery: ["promise"], demand: ["execution", "accuracy"],
};
const AGE_BINS: { label: string; lo: number; hi: number }[] = [
  { label: "0–1 d", lo: 0, hi: 1 }, { label: "2–3 d", lo: 2, hi: 3 }, { label: "4–7 d", lo: 4, hi: 7 },
  { label: "8–14 d", lo: 8, hi: 14 }, { label: "15+ d", lo: 15, hi: Infinity },
];

function Worklist({ res, ds, rev }: { res: TowerResult; ds: Dataset; rev: number }) {
  const [cat, setCat] = useState<string>("all");
  const [owner, setOwner] = useState<string>("all");
  const [status, setStatus] = useState<string>("live");
  const [lateOnly, setLateOnly] = useState(false);
  const [selId, setSelId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const items = res.worklist;
  const live = items.filter((w) => w.status === "open" || w.status === "acknowledged");
  const cats = [...new Set(items.map((w) => w.category))].sort();
  const owners = [...new Set([...items.map((w) => w.owner), ...(ds.tower?.owners ?? []).map((o) => o.owner), ds.tower?.default_owner ?? "Unassigned"])].sort();
  const shown = items.filter((w) => (cat === "all" || w.category === cat) && (owner === "all" || w.owner === owner)
    && (status === "all" || (status === "live" ? w.status === "open" || w.status === "acknowledged" : w.status === status))
    && (!lateOnly || w.breached));
  const sel = items.find((w) => w.id === selId) ?? null;

  const patch = async (w: WorkItem, p: Parameters<typeof api.towerItem>[1]) => {
    setErr(null);
    try {
      const u = await api.towerItem(w.id, { ...p, sla_days: (ds.tower?.sla_days ?? {}) as Record<string, number> });
      store.put("tower", { ...res, worklist: res.worklist.map((x) => (x.id === u.id ? { ...u, age_days: x.age_days, breached: x.breached } : x)) }, rev);
    } catch (e) {
      setErr(String(e));
    }
  };

  const byOwner = useMemo(() => {
    const m = new Map<string, { n: number; late: number }>();
    for (const w of live) {
      const x = m.get(w.owner) ?? { n: 0, late: 0 };
      x.n += 1;
      if (w.breached) x.late += 1;
      m.set(w.owner, x);
    }
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n);
  }, [live]);

  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Open" value={live.filter((w) => w.status === "open").length} sub="not yet picked up" tone="ink" />
        <StatTile label="Acknowledged" value={live.filter((w) => w.status === "acknowledged").length} sub="being worked" />
        <StatTile label="Past SLA" value={live.filter((w) => w.breached).length} tone={live.some((w) => w.breached) ? "hl" : undefined} />
        <StatTile label="Cleared this run" value={res.cleared.length} sub="no longer detected" />
        <StatTile label="Reopened" value={live.filter((w) => w.reopened > 0).length} sub="came back after clearing" />
      </div>
      {err && <div className="banner error"><Badge sev="error">Update failed</Badge>{err}</div>}
      <div className="grid-2" style={{ alignItems: "start" }}>
        <Panel title="Age of open exceptions (planning days)">
          <div className="bar-list">
            {AGE_BINS.map((b) => {
              const n = live.filter((w) => w.age_days >= b.lo && w.age_days <= b.hi).length;
              return (
                <div key={b.label} className="bar-row">
                  <span>{b.label}</span>
                  <div className="bar-track"><div className="bar-fill" style={{ width: `${(n / Math.max(1, live.length)) * 100}%` }} /></div>
                  <span className="num">{n}</span>
                </div>
              );
            })}
          </div>
        </Panel>
        <Panel flush title="By owner">
          <div className="table-wrap" style={{ maxHeight: 220 }}>
            <table className="t">
              <thead><tr><th>Owner</th><th className="num">Open</th><th className="num">Past SLA</th></tr></thead>
              <tbody>
                {byOwner.map(([o, x]) => (
                  <tr key={o} className="clickable" onClick={() => setOwner(o)}>
                    <td>{o}</td><td className="num">{x.n}</td><td className={`num ${x.late ? "neg" : ""}`}>{x.late}</td>
                  </tr>
                ))}
                {byOwner.length === 0 && <tr><td colSpan={3} className="faint">Nothing open.</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <div className="row filters" style={{ gap: 10, flexWrap: "wrap" }}>
        <label className="small">Category <select className="select" aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} style={{ width: 150 }}>
          <option value="all">All</option>{cats.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label className="small">Owner <select className="select" aria-label="Owner filter" value={owner} onChange={(e) => setOwner(e.target.value)} style={{ width: 210 }}>
          <option value="all">All</option>{owners.map((o) => <option key={o}>{o}</option>)}</select></label>
        <label className="small">Status <select className="select" aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 200 }}>
          <option value="live">Open + acknowledged</option><option value="open">Open</option><option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option><option value="all">All</option></select></label>
        <label className="small row" style={{ gap: 6 }}><input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} />Past SLA only</label>
        <span className="spacer" /><span className="faint small">{shown.length} of {items.length}</span>
      </div>
      <datalist id="tower-owners">{owners.map((o) => <option key={o} value={o} />)}</datalist>
      <Panel flush>
        <div className="table-wrap" style={{ maxHeight: 620 }}>
          <table className="t">
            <thead><tr><th>Sev</th><th>Category</th><th>Exception</th><th>Where</th><th>Owner</th><th style={{ width: 150 }}>Age / SLA</th>
              <th>Status</th><th>First seen</th><th /></tr></thead>
            <tbody>
              {shown.map((w) => (
                <tr key={w.id} className={`${sel?.id === w.id ? "selected" : ""} ${w.status === "resolved" ? "dim" : ""}`}>
                  <td><Badge sev={ITEM_SEV[w.severity]} /></td>
                  <td><a href={href(...(CAT_LINK[w.category] ?? ["plan"]))}>{w.category}</a></td>
                  <td><b className="mono small">{w.code}</b><div className="small">{w.message}</div></td>
                  <td className="small nowrap">{[w.location, w.product].filter(Boolean).join(" · ") || w.resource}{w.order_id && <div className="faint">{w.order_id}</div>}</td>
                  <td>
                    <input className="input" list="tower-owners" aria-label={`Owner of ${w.code} ${w.location ?? ""} ${w.product ?? ""}`.trim()} defaultValue={w.owner}
                      key={`${w.id}-${w.owner}`} style={{ height: 28, minWidth: 230 }}
                      onBlur={(e) => { if (e.target.value.trim() !== w.owner) void patch(w, { owner: e.target.value }); }}
                      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
                    {w.owner_source !== "manual" && <div className="faint small">by {w.owner_source === "rule" ? "rule" : "default"}</div>}
                  </td>
                  <td>
                    <div className="age-bar" title={w.sla_days !== null ? `${w.age_days} of ${w.sla_days} days` : `${w.age_days} days`}>
                      <span style={{ width: `${Math.min(100, (w.age_days / Math.max(1, w.sla_days ?? w.age_days)) * 100)}%` }} className={w.breached ? "late" : ""} />
                    </div>
                    <span className={`small ${w.breached ? "neg-text" : "faint"}`}>{w.age_days} d{w.sla_days !== null ? ` / ${w.sla_days} d` : ""}{w.breached ? " · past SLA" : ""}</span>
                  </td>
                  <td className="nowrap">
                    <span className="small">{w.status}</span>
                    <div className="row" style={{ gap: 4, marginTop: 3 }}>
                      {w.status === "open" && <button className="btn sm" onClick={() => patch(w, { status: "acknowledged" })} aria-label={`Acknowledge ${w.code} ${w.location ?? ""} ${w.product ?? ""}`.trim()}>Ack</button>}
                      {w.status !== "resolved" && <button className="btn sm" onClick={() => patch(w, { status: "resolved" })} aria-label={`Resolve ${w.code} ${w.location ?? ""} ${w.product ?? ""}`.trim()}>Resolve</button>}
                      {w.status === "resolved" && <button className="btn sm ghost" onClick={() => patch(w, { status: "open" })}>Reopen</button>}
                    </div>
                  </td>
                  <td className="small nowrap">{day(w.first_seen)}{w.reopened > 0 && <div className="faint">reopened ×{w.reopened}</div>}</td>
                  <td><button className="btn sm ghost" onClick={() => setSelId(sel?.id === w.id ? null : w.id)} aria-label={`Details of ${w.code}`}>{sel?.id === w.id ? "Close" : "Details"}</button></td>
                </tr>
              ))}
              {shown.length === 0 && <tr><td colSpan={9} className="faint" style={{ padding: 16 }}>No exceptions match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
      {sel && <ItemDetail w={sel} onNote={(note) => patch(sel, { note })} />}
      {res.cleared.length > 0 && (
        <Panel flush title={`Cleared by this refresh (${res.cleared.length})`}>
          <div className="table-wrap" style={{ maxHeight: 240 }}>
            <table className="t">
              <thead><tr><th>Exception</th><th>Where</th><th>Owner</th><th className="num">Was open</th></tr></thead>
              <tbody>{res.cleared.map((w) => (
                <tr key={w.id}><td><b className="mono small">{w.code}</b> <span className="small">{w.message}</span></td>
                  <td className="small">{[w.location, w.product].filter(Boolean).join(" · ") || w.resource}</td><td>{w.owner}</td><td className="num">{w.age_days} d</td></tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
      )}
      <Reading formula="age = planning start − first seen (planning days, so it follows the roll-forward); past SLA when age > the category's SLA. An exception not detected by a refresh is cleared; if it comes back it reopens with a fresh age."
        soWhat="Owners come from the first matching rule unless someone assigns the item by hand; a hand assignment sticks across refreshes. Resolving an item still detected keeps it resolved for today — it reopens at the next planning date if the cause is still there." />
    </div>
  );
}

function ItemDetail({ w, onNote }: { w: WorkItem; onNote: (note: string) => void }) {
  const [hist, setHist] = useState<WorkItemEntry[] | null>(null);
  const [note, setNote] = useState(w.note);
  useEffect(() => {
    setNote(w.note);
    api.towerHistory(w.id).then(setHist).catch(() => setHist([]));
  }, [w.id, w.note, w.status, w.owner]);
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title={`${w.code} · ${[w.location, w.product].filter(Boolean).join(" · ") || w.resource || ""}`}>
        <p style={{ marginTop: 0 }}>{w.message}</p>
        <div className="small faint" style={{ marginBottom: 8 }}>
          {w.date && <>Date {day(w.date)} · </>}{w.qty !== null && <>qty {qty(w.qty)} · </>}first seen {day(w.first_seen)} · last seen {day(w.last_seen)}
        </div>
        <label className="small" htmlFor="wl-note">Note</label>
        <textarea id="wl-note" className="input" style={{ height: 70, padding: 8 }} value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row" style={{ marginTop: 8 }}><button className="btn" disabled={note === w.note} onClick={() => onNote(note)}>Save note</button></div>
      </Panel>
      <Panel flush title="History">
        <div className="table-wrap" style={{ maxHeight: 240 }}>
          <table className="t">
            <thead><tr><th>Planning date</th><th>Action</th><th>Detail</th></tr></thead>
            <tbody>{(hist ?? []).map((h, i) => <tr key={i}><td className="nowrap">{day(h.at)}</td><td>{h.action}</td><td className="small">{h.detail}</td></tr>)}</tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Quality({ res }: { res: TowerResult }) {
  const total = res.data_quality.reduce((a, r) => a + r.count, 0);
  return (
    <div className="stack">
      <div className="banner info"><Badge sev="info">Kept apart</Badge>Master-data defects go to data owners, not into planner worklists (S/4 guide §8.6). Fix them in Readiness.</div>
      {total === 0 ? <Panel><Empty title="No data-quality findings"><p>Every readiness check passes.</p></Empty></Panel> : (
        <Panel flush title={`${total} findings by rule`}>
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Sev</th><th>Rule</th><th>What</th><th className="num">Count</th><th>Examples</th></tr></thead>
              <tbody>{res.data_quality.map((r) => (
                <tr key={r.code}>
                  <td><Badge sev={r.severity === "error" ? "error" : r.severity === "warning" ? "warning" : "info"} /></td>
                  <td><a className="mono small" href={href("readiness")}>{r.code}</a></td><td>{r.title}</td>
                  <td className="num">{r.count}</td><td className="small faint">{r.examples.join(" · ")}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

function Settings({ ds }: { ds: Dataset }) {
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title="Owners, SLA and KPI targets">
        <SchemaForm defName="TowerSettings" value={(ds.tower ?? {}) as unknown as Obj}
          onChange={(next) => store.update((d) => { d.tower = next as unknown as Dataset["tower"]; })} />
      </Panel>
      <Reading formula="Owner rules are tried in order; the first whose categories, locations, products and families all match (empty = any) owns the exception. Categories: coverage, capacity, inventory, orders, delivery, demand."
        soWhat="Targets are graded with a band: within 5 points of a ratio target (or 25 % of another) is ‘near target’. KPIs with no data are not graded." />
    </div>
  );
}
