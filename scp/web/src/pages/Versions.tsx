import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Comparison, Dataset, PlanSummary, VersionMeta } from "../api/types";
import { Badge, Empty, Panel, Reading, SectionBand, StageHeader, StatTile } from "../components/ui";
import { day, money, pct, qty } from "../lib/format";
import { go, href } from "../lib/router";
import { isModified, store, useStore } from "../state/store";

const STATUS_SEV: Record<string, "ok" | "info" | "warning" | undefined> = {
  active: "ok", promoted: "info", superseded: undefined, discarded: "warning",
};

/** Versions as a tree: every version under the one it was branched or promoted from. */
function tree(vs: VersionMeta[]): { v: VersionMeta; depth: number }[] {
  const kids = new Map<string | null, VersionMeta[]>();
  const ids = new Set(vs.map((v) => v.id));
  for (const v of vs) {
    const p = v.parent_id && ids.has(v.parent_id) ? v.parent_id : null;
    kids.set(p, [...(kids.get(p) ?? []), v]);
  }
  const out: { v: VersionMeta; depth: number }[] = [];
  const walk = (p: string | null, depth: number) => {
    for (const v of kids.get(p) ?? []) {
      out.push({ v, depth });
      walk(v.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

const WORKING = "__working__";

export function Versions() {
  const ds = useStore((s) => s.dataset)!;
  const current = useStore((s) => s.version);
  const modified = useStore(isModified);
  const [list, setList] = useState<VersionMeta[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // a version is a complete, valid company: unfinished records must be finished (or deleted) first
  const unfinished = useStore((s) => s.validation?.set_aside?.length ?? 0);
  const [name, setName] = useState("");
  const [pick, setPick] = useState<[string | null, string | null]>([null, null]);
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [showAll, setShowAll] = useState(false);

  const refresh = useCallback(() => api.versions().then(setList).catch((e) => setErr(String(e))), []);
  useEffect(() => { refresh(); }, [refresh]);

  const act = async (f: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await f();
      await refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const label = name.trim() || (current ? `Scenario of ${current.id}` : `Plan of ${day(ds.settings.planning_start)}`);
  const saveBase = () => act(async () => {
    const m = await api.saveBase(ds, name.trim() || `Plan of ${day(ds.settings.planning_start)}`);
    store.saved(m);
    setName("");
  });
  const saveScenario = () => act(async () => {
    if (!current) return;
    const m = await api.saveVersion(current.id, ds);
    store.saved(m);
  });
  const saveAsScenario = () => act(async () => {
    if (!current) return;
    const b = await api.branch(current.id, label);
    const m = await api.saveVersion(b.id, ds);
    store.saved(m);
    setName("");
  });
  const open = (v: VersionMeta) => act(async () => {
    if (modified && !window.confirm(`The working copy has unsaved changes to ${current?.id}. Open ${v.id} anyway?`)) return;
    const doc = await api.version(v.id);
    store.load(doc.dataset, doc.meta);
    go("versions");
  });
  const branch = (v: VersionMeta) => act(async () => {
    const b = await api.branch(v.id, name.trim() || `Scenario of ${v.id}`);
    const doc = await api.version(b.id);
    store.load(doc.dataset, doc.meta);
    setName("");
  });
  const discard = (v: VersionMeta) => act(async () => {
    if (!window.confirm(`Discard scenario ${v.id} “${v.name}”? Its base is not affected.`)) return;
    const m = await api.discard(v.id);
    if (current?.id === v.id) store.saved(m);
  });
  const promote = (v: VersionMeta) => act(async () => {
    const m = await api.promote(v.id);
    if (current?.id === v.id) {
      const doc = await api.version(m.id);
      store.load(doc.dataset, doc.meta);
    }
  });
  const runCompare = () => act(async () => {
    const [a, b] = pick;
    if (!a || !b) return;
    const load = async (id: string): Promise<[Dataset, string]> =>
      id === WORKING ? [ds, "working copy"] : [(await api.version(id)).dataset, id];
    if (a !== WORKING && b !== WORKING) setCmp(await api.compareVersions(a, b));
    else {
      const [[da, la], [db, lb]] = await Promise.all([load(a), load(b)]);
      setCmp(await api.compare(da, db, la, lb));
    }
  });

  const rows = useMemo(() => tree((list ?? []).filter((v) => showAll || v.status !== "discarded")), [list, showAll]);
  const canSave = current?.kind === "scenario" && current.status === "active";
  const choice = (id: string) => (
    <span className="row" style={{ gap: 4 }}>
      <button className={`btn sm ${pick[0] === id ? "primary" : ""}`} aria-label={`Compare ${id} as A`} onClick={() => setPick([id, pick[1]])}>A</button>
      <button className={`btn sm ${pick[1] === id ? "primary" : ""}`} aria-label={`Compare ${id} as B`} onClick={() => setPick([pick[0], id])}>B</button>
    </span>
  );

  return (
    <div>
      <StageHeader title="Versions and what-ifs" kicker={<>Save today's data as a <b>base version</b>. To try a change, save it as a
        {" "}<b>scenario</b> of that base, then compare the two side by side, data and plan. Keep the scenario as the next base, or drop it.</>}
        how={<>A saved version never changes: its content is stored with a fingerprint (SHA-256 of the data), which the table shows.
          Promoting a scenario writes a new base and marks the old one superseded, byte for byte as it was.</>} />
      <div className="content">
        {err && <div className="banner error"><Badge sev="error">Version store</Badge>{err}</div>}
        <Panel title="Working copy">
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            <span>{current ? <>Opened from <b>{current.id}</b> · {current.kind} “{current.name}”</> : <>Not saved as a version yet</>}</span>
            {current && (modified ? <Badge sev="warning">modified</Badge> : <Badge sev="ok">saved</Badge>)}
            {current && current.status !== "active" && <Badge sev="info">{current.status}</Badge>}
            <span className="spacer" />
            <input className="input" style={{ width: 260 }} placeholder={label} value={name} onChange={(e) => setName(e.target.value)} aria-label="Version name" />
            <button className="btn accent" disabled={busy || unfinished > 0} onClick={saveBase}>Save as base version</button>
            {current && <button className="btn" disabled={busy || unfinished > 0} onClick={saveAsScenario}>Save as new scenario of {current.id}</button>}
            {canSave && <button className="btn" disabled={busy || unfinished > 0 || !modified} onClick={saveScenario}>Save to {current!.id}</button>}
          </div>
          {unfinished > 0 && <p className="small" style={{ marginBottom: 0 }}><Badge sev="warning">Can't save yet</Badge>{" "}
            {unfinished === 1 ? "One record is" : `${unfinished} records are`} not finished, and a saved version must be complete.{" "}
            <a href={href("readiness")}>Finish or delete {unfinished === 1 ? "it" : "them"}</a>.</p>}
          {current?.kind === "base" && modified && <p className="small muted" style={{ marginBottom: 0 }}>{current.id} is a base version and stays as it is:
            save your edits as a new scenario of it, or as a new base.</p>}
        </Panel>

        <Panel flush title="Stored versions" actions={<label className="small row" style={{ gap: 6 }}>
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show discarded</label>}>
          {!list ? <Empty title="Loading…" /> : rows.length === 0 ? <Empty title="No versions yet">Save the working copy as the first base version.</Empty> : (
            <div className="table-wrap">
              <table className="t">
                <thead><tr><th>Version</th><th>Kind</th><th>Status</th><th>Planning start</th><th>Saved</th><th>SHA-256</th><th>Compare</th><th /></tr></thead>
                <tbody>
                  {rows.map(({ v, depth }) => (
                    <tr key={v.id} className={current?.id === v.id ? "selected" : ""}>
                      <td><span style={{ paddingLeft: depth * 18 }}>{depth > 0 && <span className="faint">└ </span>}<b>{v.id}</b> {v.name}</span>
                        {v.note && <div className="faint small" style={{ paddingLeft: depth * 18 + 14 }}>{v.note}</div>}</td>
                      <td>{v.kind === "base" ? <Badge sev="info">base</Badge> : "scenario"}</td>
                      <td><Badge sev={STATUS_SEV[v.status]}>{v.status}</Badge></td>
                      <td>{day(v.planning_start)}</td>
                      <td className="small">{v.updated_at.replace("T", " ").slice(0, 16)}</td>
                      <td className="faint small" title={v.sha256} style={{ fontFamily: "var(--mono)" }}>{v.sha256.slice(0, 10)}</td>
                      <td>{choice(v.id)}</td>
                      <td><div className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                        <button className="btn sm" disabled={busy} onClick={() => open(v)} aria-label={`Open ${v.id}`}>Open</button>
                        {v.status !== "discarded" && <button className="btn sm" disabled={busy} onClick={() => branch(v)} aria-label={`Branch ${v.id}`}>Branch</button>}
                        {v.kind === "scenario" && v.status === "active" && <>
                          <button className="btn sm" disabled={busy} onClick={() => promote(v)} aria-label={`Promote ${v.id}`}>Promote</button>
                          <button className="btn sm ghost" disabled={busy} onClick={() => discard(v)} aria-label={`Discard ${v.id}`}>Discard</button></>}
                      </div></td>
                    </tr>
                  ))}
                  <tr>
                    <td><i>Working copy</i></td><td colSpan={5} className="faint small">the dataset open in this browser</td>
                    <td>{choice(WORKING)}</td><td />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <div className="row" style={{ gap: 10 }}>
          <span className="muted">Compare <b>{pick[0] === WORKING ? "working copy" : pick[0] ?? "A"}</b> with <b>{pick[1] === WORKING ? "working copy" : pick[1] ?? "B"}</b></span>
          <button className="btn accent" disabled={busy || !pick[0] || !pick[1] || pick[0] === pick[1]} onClick={runCompare}>{busy ? "Comparing…" : "Compare"}</button>
        </div>
        {cmp && <CompareView c={cmp} currency={ds.settings.currency} />}
        <Reading formula="A base version is stored once as canonical JSON with its SHA-256; the database refuses any later change to it. Scenarios are branches: edit, save, discard, or promote — promotion writes a new base and marks the old one superseded."
          soWhat="Plan against a named base, try what-ifs as scenarios, and keep an audit trail of what was decided and when." />
      </div>
    </div>
  );
}

function CompareView({ c, currency }: { c: Comparison; currency: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows: [string, (p: PlanSummary) => number, (v: number) => string, boolean][] = [
    ["Total plan cost", (p) => p.total_cost, (v) => money(v, currency), false],
    ["On-time fill rate", (p) => p.fill_rate, (v) => pct(v, 1), true],
    ["Planned orders", (p) => p.orders, qty, false],
    ["Average inventory value", (p) => p.inventory_value_avg, (v) => money(v, currency), false],
    ["Peak utilisation", (p) => p.max_utilization, (v) => pct(v, 0), false],
    ["Exceptions (errors)", (p) => p.errors, qty, false],
  ];
  return (
    <>
      <SectionBand step="Δ" title={`${c.a} → ${c.b}`} />
      <div className="grid-auto">
        <StatTile label="Data changes" value={qty(c.diff.changes)} sub={c.diff.identical ? "identical" : `${c.diff.collections.length} object types`} />
        <StatTile label="Plan cost Δ" value={money(c.plan_b.total_cost - c.plan_a.total_cost, currency)} sub={`${c.a} → ${c.b}`} />
        <StatTile label="Fill rate Δ" value={`${c.plan_b.fill_rate >= c.plan_a.fill_rate ? "+" : ""}${pct(c.plan_b.fill_rate - c.plan_a.fill_rate, 1)}`} sub="on-time, independent demand" />
      </div>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <Panel flush title="Plan side by side (MRP)">
          <table className="t">
            <thead><tr><th>KPI</th><th className="num">{c.a}</th><th className="num">{c.b}</th><th className="num">Δ</th></tr></thead>
            <tbody>
              {rows.map(([label, get, fmt, higherBetter]) => {
                const a = get(c.plan_a), b = get(c.plan_b), d = b - a;
                const better = Math.abs(d) < 1e-9 ? undefined : (d > 0) === higherBetter ? "ok" : "warning";
                return <tr key={label}><td>{label}</td><td className="num">{fmt(a)}</td><td className="num">{fmt(b)}</td>
                  <td className="num">{better ? <Badge sev={better}>{d > 0 ? "+" : ""}{fmt(d)}</Badge> : <span className="faint">—</span>}</td></tr>;
              })}
            </tbody>
          </table>
        </Panel>
        <Panel flush title="What changed">
          {c.diff.identical ? <Empty title="The datasets are identical" /> : (
            <div className="table-wrap" style={{ maxHeight: 480 }}>
              <table className="t">
                <thead><tr><th>Object type</th><th className="num">Added</th><th className="num">Removed</th><th className="num">Changed</th></tr></thead>
                <tbody>
                  {c.diff.collections.map((col) => (
                    <Fragment key={col.collection}>
                      <tr className="clickable" onClick={() => setOpen(open === col.collection ? null : col.collection)}>
                        <td><b>{col.collection.replace(/_/g, " ")}</b></td><td className="num">{col.added || ""}</td>
                        <td className="num">{col.removed || ""}</td><td className="num">{col.changed || ""}</td>
                      </tr>
                      {open === col.collection && col.items.map((it) => (
                        <tr key={`${col.collection}|${it.key}`}>
                          <td colSpan={4} className="small">
                            <Badge sev={it.change === "added" ? "ok" : it.change === "removed" ? "warning" : "info"}>{it.change}</Badge> <b>{it.key}</b>
                            {it.fields.map((f) => <div key={f.path} className="faint" style={{ paddingLeft: 12, fontFamily: "var(--mono)" }}>
                              {f.path}: {JSON.stringify(f.a)} → {JSON.stringify(f.b)}</div>)}
                            {it.more > 0 && <div className="faint" style={{ paddingLeft: 12 }}>…and {it.more} more fields</div>}
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
