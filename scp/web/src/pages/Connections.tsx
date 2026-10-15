// Connected to the rest of the company (Phase Q): what other systems sent and took (the message log), the keys they
// use, the files and addresses read on a schedule, and the e-mail the server sends (documents and worklist reminders).
// Only for a company kept on the server: the ERP talks to the server, not to a browser.
import { Fragment, useState } from "react";
import { api } from "../api/client";
import type { ApiKey, ImportJob, ImportJobs, JobInput, MailRow, MailSetup, MessageRow, Paging, Tried } from "../api/types";
import { Badge, Empty, Panel, StageHeader, Tabs, type Severity } from "../components/ui";
import { when } from "../components/SaveStatus";
import { useLatest } from "../lib/latest";
import { go, href } from "../lib/router";
import { store, useStore } from "../state/store";
import { fromMapping, MappingEditor, PagingFields, startRows, toMapping, TryResult, type MapRow } from "./ImportMapping";

type Tab = "messages" | "keys" | "imports" | "mail";
const TABS: { id: Tab; label: string }[] = [
  { id: "messages", label: "Messages" }, { id: "keys", label: "Keys" }, { id: "imports", label: "Scheduled imports" },
  { id: "mail", label: "E-mail" },
];

const STATUS: Record<string, [string, Severity | undefined]> = {
  applied: ["taken", "ok"], partly: ["partly taken", "warning"], refused: ["refused", "error"], unchanged: ["as here already", undefined],
  duplicate: ["sent before", undefined], sent: ["sent", "ok"], failed: ["failed", "error"],
};
const ITEM: Record<string, Severity | undefined> = { applied: "ok", refused: "error", unchanged: undefined, duplicate: undefined };

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const err = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** "orders", "records:products" → what a person calls them. */
export function kindName(kind: string): string {
  const k: Record<string, string> = {
    orders: "customer orders", stock: "stock", postings: "goods movements", acknowledgements: "order numbers back",
    purchase_orders: "purchase orders taken", production_orders: "production orders taken", transfer_orders: "transfers taken",
  };
  return k[kind] ?? (kind.startsWith("records:") ? kind.slice(8).replace(/_/g, " ") : kind.replace(/_/g, " "));
}

function StatusBadge({ status }: { status: string }) {
  const [label, sev] = STATUS[status] ?? [status, undefined];
  return <Badge sev={sev}>{label}</Badge>;
}

// ---- messages ----------------------------------------------------------------------------------------------------
function Messages({ id }: { id: string }) {
  const revision = useStore((s) => s.company?.revision);
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  // a filter changed quickly: the list of the last one asked is the one shown
  const { value: rows, error: e } = useLatest<MessageRow[]>(() => api.messages(id, { status }), [id, status, revision]);
  return <Panel title="What other systems sent and took" actions={
    <select className="select" aria-label="Show messages" value={status} onChange={(ev) => setStatus(ev.target.value)} style={{ width: "auto" }}>
      <option value="">all</option><option value="refused">refused</option><option value="partly">partly taken</option><option value="applied">taken</option>
    </select>}>
    {e && <div className="banner error">{e}</div>}
    {!rows ? <div className="faint">Loading…</div> : !rows.length ? (
      <p className="muted small" style={{ margin: 0 }}>Nothing yet. Messages an ERP sends with a key, and the files a scheduled import reads, are
        listed here with what became of each line.</p>
    ) : <div className="table-wrap"><table className="t">
      <thead><tr><th>When</th><th>From</th><th>What</th><th>Became of it</th><th /></tr></thead>
      <tbody>{rows.map((m) => <Fragment key={m.seq}>
        <tr>
          <td className="nowrap small">{when(m.at)}</td>
          <td>{m.by}{m.source && <div className="faint small">{m.source}</div>}</td>
          <td>{m.direction === "out" ? "← " : "→ "}{kindName(m.kind)}{m.message_id && <div className="faint small">message {m.message_id}</div>}</td>
          <td><StatusBadge status={m.status} /> <span className="small">{m.summary}</span>
            {m.revision != null && <div className="faint small">saved as revision {m.revision} · <a href={href("history")}>History</a></div>}</td>
          <td>{(m.items.length > 0 || !!m.sample) && <button className="btn sm ghost" aria-expanded={open === m.seq} onClick={() => setOpen(open === m.seq ? null : m.seq)}>
            {open === m.seq ? "Hide" : m.items.length ? `${m.items.length} line${m.items.length === 1 ? "" : "s"}` : "What was read"}</button>}</td>
        </tr>
        {open === m.seq && <tr><td colSpan={5}>
          <table className="t small"><tbody>{m.items.map((it, i) => <tr key={i}>
            <td className="nowrap"><b>{it.ref || "—"}</b></td><td><Badge sev={ITEM[it.status]}>{STATUS[it.status]?.[0] ?? it.status}</Badge></td>
            <td>{it.message}</td><td className="faint">{it.id ?? ""}</td></tr>)}</tbody></table>
          {m.sample && <details open={!m.items.length}><summary className="small">What was read (the start)</summary>
            <pre className="mono small" style={{ whiteSpace: "pre-wrap", maxHeight: 240, overflow: "auto", margin: 0 }}>{m.sample}</pre></details>}
        </td></tr>}
      </Fragment>)}</tbody>
    </table></div>}
  </Panel>;
}

// ---- keys --------------------------------------------------------------------------------------------------------
function Keys({ id, owner }: { id: string; owner: boolean }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<"planner" | "viewer">("planner");
  const [made, setMade] = useState<ApiKey | null>(null);
  const [failed, setE] = useState<string | null>(null);
  const { value: list, show: setList, error: readErr } = useLatest<ApiKey[]>(owner ? () => api.keys(id) : null, [id, owner]);
  const e = failed ?? readErr;
  if (!owner) return <Panel title="Keys for other systems"><p className="muted small" style={{ margin: 0 }}>Only an owner makes or withdraws keys.</p></Panel>;
  const live = (list ?? []).filter((k) => !k.revoked_at);
  return <Panel title="Keys for other systems">
    <p className="small muted" style={{ marginTop: 0 }}>An ERP, a warehouse system or a script sends and takes data with a key. A key works in this company
      only, as a planner (sends orders, stock and movements, takes purchase and production orders) or a viewer (only takes).
      What it sends is saved as a change by the key, in the History, like a colleague's.</p>
    {made?.token && <div className="banner ok" role="status">
      <div><b>{made.name}</b>'s key, shown this once: give it to that system now.</div>
      <input className="input mono" readOnly value={made.token} aria-label="The new key" onFocus={(ev) => ev.target.select()} style={{ width: "100%", maxWidth: 520 }} />
      <div className="small">It sends it as <code>Authorization: Bearer {made.token.slice(0, 12)}…</code> See the integration guide for the messages.</div>
    </div>}
    {list && live.length > 0 && <div className="table-wrap"><table className="t">
      <thead><tr><th>Key</th><th>Acts as</th><th>Made</th><th>Last used</th><th /></tr></thead>
      <tbody>{live.map((k) => <tr key={k.id}>
        <td><b>{k.name}</b><div className="faint small mono">{k.prefix}…</div></td><td>{k.role}</td>
        <td className="small">{when(k.created_at)}<div className="faint">{k.created_by}</div></td>
        <td className="small">{k.last_used ? when(k.last_used) : <span className="faint">never</span>}</td>
        <td><button className="btn sm ghost" aria-label={`Withdraw ${k.name}`} onClick={async () => {
          if (!window.confirm(`Withdraw ${k.name}? The system using it can no longer send or take data.`)) return;
          try { setList(await api.revokeKey(id, k.id)); setMade(null); } catch (x) { setE(err(x)); }
        }}>Withdraw</button></td>
      </tr>)}</tbody>
    </table></div>}
    {list && !live.length && <p className="faint small">No key yet.</p>}
    <form className="row wrap inline-form" style={{ gap: 8 }} onSubmit={async (ev) => {
      ev.preventDefault();
      setE(null);
      try { const k = await api.makeKey(id, name.trim(), role); setMade(k); setName(""); setList(await api.keys(id)); } catch (x) { setE(err(x)); }
    }}>
      <input className="input" required maxLength={60} placeholder="e.g. SAP" aria-label="Name of the system" value={name} onChange={(ev) => setName(ev.target.value)} />
      <select className="select" aria-label="The key acts as" value={role} onChange={(ev) => setRole(ev.target.value as "planner" | "viewer")}>
        <option value="planner">planner: sends and takes</option><option value="viewer">viewer: only takes</option>
      </select>
      <button className="btn">Make a key</button>
    </form>
    {e && <div className="banner error">{e}</div>}
    {list && list.some((k) => k.revoked_at) && <details className="small"><summary>Withdrawn keys</summary>
      <ul>{list.filter((k) => k.revoked_at).map((k) => <li key={k.id}>{k.name} ({k.prefix}…), withdrawn {when(k.revoked_at)}</li>)}</ul></details>}
  </Panel>;
}

// ---- imports -----------------------------------------------------------------------------------------------------
const blank = (kinds: string[]): JobInput => ({
  name: "", kind: kinds[0] ?? "orders", source_type: "url", source: "", headers: {}, format: "csv", day_first: true, every: "day",
  at: "06:00", weekday: 0, enabled: true,
});

function schedule(j: Pick<ImportJob, "every" | "at" | "weekday">): string {
  if (j.every === "hour") return `every hour at :${j.at.slice(3)}`;
  if (j.every === "week") return `every ${DAYS[j.weekday]} at ${j.at}`;
  return `every day at ${j.at}`;
}

function JobForm({ cid, jid, data, initial, onSave, onCancel }: { cid: string; jid?: string; data: ImportJobs; initial: JobInput; onSave: (j: JobInput) => Promise<void>; onCancel: () => void }) {
  const [j, setJ] = useState<JobInput>(initial);
  const [auth, setAuth] = useState("");
  const [clearAuth, setClearAuth] = useState(false);
  const [e, setE] = useState<string | null>(null);
  const start = fromMapping(initial.mapping);
  const [mapped, setMapped] = useState(start.rows.length > 0);
  const [items, setItems] = useState(start.items);
  const [each, setEach] = useState(start.each);
  const [rows, setRows] = useState<MapRow[]>(start.rows);
  const [paging, setPaging] = useState<Paging>(initial.paging ?? { mode: "next", next: "", param: "page", max_pages: 50 });
  const [sample, setSample] = useState("");
  const [tried, setTried] = useState<Tried | null>(null);
  const [trying, setTrying] = useState(false);
  const set = (p: Partial<JobInput>) => setJ({ ...j, ...p });
  const fields = data.fields?.[j.kind] ?? [];
  const web = j.source_type !== "folder";
  const payload = (): JobInput => {
    const headers = clearAuth || !web ? {} : auth.trim() ? { Authorization: auth.trim() } : j.headers;
    const { name, kind, source_type, source, day_first, every, at, weekday, enabled } = j;
    const format = source_type === "api" ? "json" : j.format;
    const mapping = mapped ? toMapping(items, each, rows) : items.trim() && format === "json" ? toMapping(items, "", []) : null;
    return { name, kind, source_type, source, format, day_first, every, at, weekday, enabled, headers, mapping,
      paging: source_type === "api" ? paging : null };
  };
  const tryIt = async () => {
    setE(null);
    setTrying(true);
    try { setTried(await api.tryImport(cid, { job: payload(), content: sample.trim() ? sample : null, id: jid ?? null })); }
    catch (x) { setE(err(x)); setTried(null); } finally { setTrying(false); }
  };
  return <form className="stack" style={{ gap: 10 }} aria-label="Scheduled import" onSubmit={async (ev) => {
    ev.preventDefault();
    setE(null);
    try { await onSave(payload()); }
    catch (x) { setE(err(x)); }
  }}>
    <div className="qrow">
      <label className="qf"><span className="qf-l">Name</span>
        <input className="input" required maxLength={60} value={j.name} onChange={(ev) => set({ name: ev.target.value })} placeholder="Open orders from SAP" aria-label="Import name" /></label>
      <label className="qf"><span className="qf-l">What it brings</span>
        <select className="select" value={j.kind} onChange={(ev) => { set({ kind: ev.target.value }); if (mapped) setRows(startRows(ev.target.value, data.fields?.[ev.target.value] ?? [])); }} aria-label="What it brings">
          {data.kinds.map((k) => <option key={k} value={k}>{kindName(k)}</option>)}</select></label>
      {j.source_type !== "api" && <label className="qf"><span className="qf-l">Format</span>
        <select className="select" value={j.format} onChange={(ev) => set({ format: ev.target.value as JobInput["format"] })} aria-label="Format">
          <option value="csv">CSV (or a semicolon list)</option><option value="json">JSON</option></select></label>}
    </div>
    <div className="qrow">
      <label className="qf"><span className="qf-l">From</span>
        <select className="select" value={j.source_type} onChange={(ev) => set({ source_type: ev.target.value as JobInput["source_type"] })} aria-label="Read from">
          <option value="url">a file at a web address</option><option value="api">a web API (JSON, page by page)</option>
          <option value="folder" disabled={!data.folder}>a folder on the server{data.folder ? "" : " (not set up)"}</option></select></label>
      <label className="qf" style={{ flex: "2 1 280px" }}><span className="qf-l">{web ? "Web address" : "Files"}</span>
        <input className="input" required value={j.source} onChange={(ev) => set({ source: ev.target.value })} aria-label="Source"
          placeholder={j.source_type === "api" ? "https://erp.example.com/api/stock?changed_after={since}" : web ? "https://erp.example.com/exports/orders.csv" : "orders-*.csv"} />
        <span className="qf-h">{web ? <>only addresses on hosts the server's administrator allowed; <code>{"{since}"}</code> in it is the time the last good run started, so only what changed is read
          {(initial as Partial<ImportJob>).since && <> (now {when((initial as Partial<ImportJob>).since!)})</>}</>
          : <>files matching this in <code>{data.folder}</code>; each read file moves to <code>done/</code> (or <code>failed/</code>)</>}</span></label>
    </div>
    {web && <label className="qf"><span className="qf-l">Authorization header <span className="faint">(optional)</span></span>
      <input className="input" type="password" disabled={clearAuth} value={auth} onChange={(ev) => setAuth(ev.target.value)} aria-label="Authorization header" autoComplete="off"
        placeholder={(initial.headers && Object.keys(initial.headers).length) || (initial as Partial<ImportJob>).header_names?.length ? "kept as it is" : "Bearer …"} />
      <span className="qf-h">sent with each request to this host only (a next page elsewhere gets none); not shown again. Saved credentials are cleared if the host, protocol or port changes.</span>
      {(initial as Partial<ImportJob>).header_names?.length ? <span className="row small">
        <input type="checkbox" checked={clearAuth} onChange={(ev) => setClearAuth(ev.target.checked)} aria-label="Remove saved request headers" />
        Remove saved request headers</span> : null}</label>}
    {j.source_type === "api" && <PagingFields value={paging} onChange={setPaging} />}
    <fieldset className="stack" style={{ gap: 8, border: "1px solid var(--border)", padding: "8px 12px", margin: 0 }}>
      <legend className="small"><label className="row small"><input type="checkbox" checked={mapped} onChange={(ev) => {
        setMapped(ev.target.checked);
        if (ev.target.checked && !rows.length) setRows(startRows(j.kind, fields));
      }} /> <b>Name the fields myself</b></label></legend>
      {!mapped ? <span className="faint small">Off: columns are recognised by their names, in English and as SAP exports name them{(j.format === "json" || j.source_type === "api") && "; a JSON answer is the message the ERP would send"}.
        {(j.format === "json" || j.source_type === "api") && <label className="qf" style={{ marginTop: 6 }}><span className="qf-l">Records at</span>
          <input className="input mono" value={items} onChange={(ev) => setItems(ev.target.value)} placeholder="data.items" aria-label="Records at" /></label>}</span>
        : <MappingEditor kind={j.kind} fields={fields} json={j.format === "json" || j.source_type === "api"} items={items} each={each} rows={rows}
          columns={tried?.columns ?? []} onChange={(p) => { if (p.items !== undefined) setItems(p.items); if (p.each !== undefined) setEach(p.each); if (p.rows) setRows(p.rows); }} />}
    </fieldset>
    <details className="small" open={!!tried}><summary><b>Try it first</b>: a dry run, nothing is saved</summary>
      <div className="stack" style={{ gap: 8, marginTop: 8 }}>
        <label className="qf"><span className="qf-l">A sample <span className="faint">(optional)</span></span>
          <textarea className="input mono" rows={4} value={sample} onChange={(ev) => setSample(ev.target.value)} aria-label="Sample to try"
            placeholder={j.format === "json" || j.source_type === "api" ? '{"orders": [ … ]}' : "Item Code,Godown,Closing Qty\nTIN-W,Main Godown,8"} />
          <span className="qf-h">paste a few lines of the file (or one page of the answer); empty: the source is read now</span></label>
        <div><button type="button" className="btn sm" disabled={trying || (!sample.trim() && !j.source.trim())} onClick={tryIt}>{trying ? "Trying…" : "Try it"}</button></div>
        {tried && <TryResult t={tried} />}
      </div>
    </details>
    <div className="qrow">
      <label className="qf"><span className="qf-l">How often</span>
        <select className="select" value={j.every} onChange={(ev) => set({ every: ev.target.value as JobInput["every"] })} aria-label="How often">
          <option value="hour">every hour</option><option value="day">every day</option><option value="week">every week</option></select></label>
      {j.every === "week" && <label className="qf"><span className="qf-l">On</span>
        <select className="select" value={j.weekday} onChange={(ev) => set({ weekday: Number(ev.target.value) })} aria-label="Weekday">
          {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></label>}
      <label className="qf"><span className="qf-l">{j.every === "hour" ? "Minute past" : "At"}</span>
        <input className="input" type="time" value={j.at} onChange={(ev) => set({ at: ev.target.value })} aria-label="Time" />
        <span className="qf-h">{data.timezone} time</span></label>
      {j.format === "csv" && j.source_type !== "api" && <label className="row small" style={{ alignSelf: "end" }}>
        <input type="checkbox" checked={j.day_first} onChange={(ev) => set({ day_first: ev.target.checked })} /> dates are day first (05/01 is 5 January)</label>}
      <label className="row small" style={{ alignSelf: "end" }}>
        <input type="checkbox" checked={j.enabled} onChange={(ev) => set({ enabled: ev.target.checked })} /> on</label>
    </div>
    {e && <div className="banner error" role="alert" style={{ margin: 0 }}>{e}</div>}
    <div className="row"><button className="btn primary">Save the import</button><button type="button" className="btn ghost" onClick={onCancel}>Cancel</button></div>
  </form>;
}

function Imports({ id, owner }: { id: string; owner: boolean }) {
  const [editing, setEditing] = useState<ImportJob | "new" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [failed, setE] = useState<string | null>(null);
  const [dry, setDry] = useState<{ name: string; t: Tried } | null>(null);
  const { value: data, show: setData, error: readErr } = useLatest<ImportJobs>(() => api.imports(id), [id]);
  const e = failed ?? readErr;
  const run = async (j: ImportJob) => {
    setBusy(j.id);
    setE(null);
    setMsg(null);
    setDry(null);
    try {
      const rows = await api.runImport(id, j.id);
      setMsg(rows.length ? rows.map((r) => `${r.source || j.name}: ${r.summary}`).join(" · ") : `${j.name}: no new file.`);
      setData(await api.imports(id));
      if (rows.some((r) => r.revision != null)) await store.refreshCompany();
    } catch (x) { setE(err(x)); } finally { setBusy(null); }
  };
  const tryRun = async (j: ImportJob) => {
    setBusy(`dry:${j.id}`);
    setE(null);
    setMsg(null);
    try { setDry({ name: j.name, t: await api.dryRunImport(id, j.id) }); } catch (x) { setE(err(x)); } finally { setBusy(null); }
  };
  if (!data) return e ? <div className="banner error">{e}</div> : <div className="faint">Loading…</div>;
  return <Panel title="Files and addresses read on a schedule" actions={owner && !editing && <button className="btn sm" onClick={() => setEditing("new")}>New import</button>}>
    <p className="small muted" style={{ marginTop: 0 }}>The server reads an export your ERP writes (open orders, stock, movements, master data) at the time set, and
      takes it in as that system's message would be: each line taken or refused with why, in Messages. The same file is never
      taken twice. Column names are recognised in English and as SAP exports name them, or you name which column fills which field;
      a web API is read page by page, only what changed since the last good run. <i>Dry run</i> shows what would become of each line first.</p>
    {editing && <div className="hcard" style={{ marginBottom: 12 }}>
      <JobForm cid={id} jid={editing === "new" ? undefined : editing.id} data={data} initial={editing === "new" ? blank(data.kinds) : { ...editing, headers: undefined } as unknown as JobInput}
        onCancel={() => setEditing(null)} onSave={async (j) => {
          setData(await api.saveImport(id, j, editing === "new" ? undefined : editing.id));
          setEditing(null);
          setMsg(`${j.name} saved: it runs ${schedule(j)}.`);
        }} />
    </div>}
    {!data.jobs.length ? <p className="faint small">No scheduled import yet.{!owner && " Only an owner sets them up."}</p>
      : <div className="table-wrap"><table className="t">
        <thead><tr><th>Import</th><th>When</th><th>Last time</th><th /></tr></thead>
        <tbody>{data.jobs.map((j) => <tr key={j.id}>
          <td><b>{j.name}</b> {!j.enabled && <Badge>off</Badge>}<div className="small">{kindName(j.kind)} · {j.source_type === "api" ? "web API" : j.format.toUpperCase()} from {j.source_type === "folder" ? "the folder: " : ""}<span className="mono">{j.source}</span></div>
            {j.mapping && Object.keys(j.mapping.fields ?? {}).length > 0 && <div className="faint small">{Object.keys(j.mapping.fields ?? {}).length} fields mapped</div>}
            <div className="faint small">runs as {j.run_as}</div></td>
          <td className="small">{schedule(j)}{j.enabled && j.next_run && <div className="faint">next {when(j.next_run)}</div>}</td>
          <td className="small">{j.last_run ? <>{when(j.last_run)} <StatusBadge status={j.last_status} /><div>{j.last_summary}</div></> : <span className="faint">not yet</span>}</td>
          <td className="nowrap">{owner && <>
            <button className="btn sm" disabled={busy === j.id} onClick={() => run(j)}>{busy === j.id ? "Reading…" : "Run now"}</button>{" "}
            <button className="btn sm ghost" disabled={busy === `dry:${j.id}`} onClick={() => tryRun(j)}>{busy === `dry:${j.id}` ? "Trying…" : "Dry run"}</button>{" "}
            <button className="btn sm ghost" onClick={() => setEditing(j)}>Change</button>{" "}
            <button className="btn sm ghost" aria-label={`Remove ${j.name}`} onClick={async () => {
              if (!window.confirm(`Remove the import ${j.name}?`)) return;
              try { setData(await api.removeImport(id, j.id)); } catch (x) { setE(err(x)); }
            }}>Remove</button></>}</td>
        </tr>)}</tbody>
      </table></div>}
    {dry && <div className="hcard" style={{ marginTop: 12 }} aria-label={`Dry run of ${dry.name}`}>
      <div className="row" style={{ justifyContent: "space-between" }}><b>Dry run of {dry.name}</b>
        <button className="btn sm ghost" onClick={() => setDry(null)}>Close</button></div>
      <TryResult t={dry.t} /></div>}
    {msg && <div className="banner ok" role="status">{msg}</div>}
    {e && <div className="banner error">{e}</div>}
  </Panel>;
}

// ---- e-mail ------------------------------------------------------------------------------------------------------
function Mail({ id, owner }: { id: string; owner: boolean }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [failed, setE] = useState<string | null>(null);
  const { value: setup, show: setSetup, reload: reloadSetup, error: setupErr } = useLatest<MailSetup>(() => api.mailSetup(id), [id]);
  const { value: sent, reload: reloadSent, error: sentErr } = useLatest<MailRow[]>(() => api.mailSent(id), [id]);
  const load = () => { reloadSetup(); reloadSent(); };
  const e = failed ?? setupErr ?? sentErr;
  if (!setup) return e ? <div className="banner error">{e}</div> : <div className="faint">Loading…</div>;
  const r = { on: !!setup.reminders.on, at: setup.reminders.at ?? "08:00", weekdays: setup.reminders.weekdays ?? [] };
  const save = async (p: Partial<typeof r>) => {
    setE(null);
    setMsg(null);
    try { setSetup(await api.setReminders(id, { ...r, ...p })); } catch (x) { setE(err(x)); }
  };
  return <>
    <Panel title="E-mail from the server">
      {setup.mail ? <p className="small" style={{ marginTop: 0 }}>The server sends mail from <b>{setup.sender}</b>. Purchase orders, delivery schedules,
        order confirmations, invoices, credit notes, statements and payment reminders have <i>Send from here</i> on Buying and Selling: the document goes to
        the supplier's or customer's address in their purchasing or sales data, attached as a PDF and as the page Print shows, and replies come to whoever sent it.</p>
        : <p className="small muted" style={{ marginTop: 0 }}>This server sends no mail (its administrator has not set up a mail server). <i>E-mail</i> on a document
          opens your own mail program instead, and worklist reminders cannot be sent.</p>}
    </Panel>
    <Panel title="Worklist reminders">
      <p className="small muted" style={{ marginTop: 0 }}>On the days set, each person who owns open exceptions on the <a href={href("tower")}>worklist</a> gets one
        e-mail with them, the ones past their time first. An owner is found by e-mail address or by a member's name.</p>
      <div className="stack" style={{ gap: 8 }}>
        <label className="row small"><input type="checkbox" checked={r.on} disabled={!owner || !setup.mail} onChange={(ev) => save({ on: ev.target.checked })} />
          <b>Send worklist reminders</b></label>
        <div className="row wrap small" role="group" aria-label="Reminder days">{DAYS.map((d, i) => <label key={d} className="row small">
          <input type="checkbox" checked={r.weekdays.includes(i)} disabled={!owner}
            onChange={(ev) => save({ weekdays: ev.target.checked ? [...r.weekdays, i] : r.weekdays.filter((x) => x !== i) })} /> {d}</label>)}
          <label className="row small">at <input className="input" type="time" value={r.at} disabled={!owner} aria-label="Reminder time"
            onChange={(ev) => ev.target.value && save({ at: ev.target.value })} /> {setup.timezone}</label></div>
        <span className="faint small">{r.on && setup.next_reminder ? `Next: ${when(setup.next_reminder)}.` : "Off."}
          {setup.last_reminder && ` Last sent ${when(setup.last_reminder)}.`}{!owner && " Only an owner changes this."}</span>
        {owner && setup.mail && <div><button className="btn sm" onClick={async () => {
          setE(null);
          try { const rows = await api.remindNow(id); setMsg(rows.length ? `Sent to ${rows.map((x) => x.to.join(", ")).join("; ")}.` : "Nobody owns an open exception: nothing to send."); load(); }
          catch (x) { setE(err(x)); }
        }}>Send them now</button></div>}
      </div>
      {msg && <div className="banner ok" role="status">{msg}</div>}
      {e && <div className="banner error">{e}</div>}
    </Panel>
    <Panel title="Sent">
      {!sent?.length ? <p className="faint small" style={{ margin: 0 }}>Nothing sent yet.</p> : <div className="table-wrap"><table className="t">
        <thead><tr><th>When</th><th>What</th><th>To</th><th /></tr></thead>
        <tbody>{sent.map((m) => <tr key={m.seq}>
          <td className="nowrap small">{when(m.at)}<div className="faint">{m.by}</div></td>
          <td>{m.subject}{m.attachment && <div className="faint small">attached: {m.attachment}</div>}</td>
          <td className="small">{m.to.join(", ")}{m.cc.length > 0 && <div className="faint">cc {m.cc.join(", ")}</div>}</td>
          <td><StatusBadge status={m.status} />{m.error && <div className="small">{m.error}</div>}</td>
        </tr>)}</tbody>
      </table></div>}
    </Panel>
  </>;
}

export function Connections({ route = [] }: { route?: string[] }) {
  const company = useStore((s) => s.company);
  const tab = (TABS.find((t) => t.id === route[1])?.id ?? "messages") as Tab;
  return <div>
    <StageHeader title="Connections" kicker={<>What your ERP and other systems send and take, the files read on a schedule, and the e-mail the
      server sends.</>} howLabel="How messages are applied" how={<>A message is applied to the company's latest save on the server and saved as a new revision by the key that sent it,
        so it is in the History and can be put back; your open window takes it in on its next save, as it would a colleague's change.
        Records you set aside as unfinished stay as they are. A message sent again with the same id is not applied twice.</>} />
    <div className="content">
      {!company?.live ? <Empty title="For a company kept on the server">Other systems send to and take from the server. <a href={href("account")}>Keep this
        company on the server</a> first.</Empty> : <>
        <Tabs tabs={TABS} value={tab} onChange={(t) => go("connections", t)} />
        {tab === "messages" && <Messages id={company.id} />}
        {tab === "keys" && <Keys id={company.id} owner={company.role === "owner"} />}
        {tab === "imports" && <Imports id={company.id} owner={company.role === "owner"} />}
        {tab === "mail" && <Mail id={company.id} owner={company.role === "owner"} />}
      </>}
    </div>
  </div>;
}
