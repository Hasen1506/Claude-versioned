// The company's history (Phase I, Q14): every save with who made it and what changed, membership changes, and a way
// to compare an earlier state with now or put the company back to it.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Comparison, FieldChangeRow, HeldChange, LogRow } from "../api/types";
import { Badge, Empty, Panel, StageHeader } from "../components/ui";
import { when } from "../components/SaveStatus";
import { useLatest } from "../lib/latest";
import { href } from "../lib/router";
import { store, unsaved, useStore } from "../state/store";
import { CompareView } from "./Versions";

const ACTION: Record<string, [string, "ok" | "info" | "warning" | undefined]> = {
  created: ["created", "ok"], saved: ["saved", undefined], restored: ["put back", "warning"], member: ["people", "info"],
  deleted: ["deleted", "warning"], merged: ["merged", undefined], approved: ["approved", "ok"], held: ["approval", "info"],
};

/** A value as a change document shows it. */
function val(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString("en-IN", { maximumFractionDigits: 4 });
  if (typeof v === "boolean") return v ? "yes" : "no";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 80 ? `${s.slice(0, 77)}…` : s;
}

/** Field-by-field changes, old → new. */
function FieldTable({ rows, who }: { rows: FieldChangeRow[]; who?: boolean }) {
  return <div className="table-wrap"><table className="t small">
    <thead><tr>{who && <th>When</th>}{who && <th>Who</th>}<th>What</th><th>Field</th><th>Was</th><th>Now</th></tr></thead>
    <tbody>{rows.map((r, i) => <tr key={r.seq || i}>
      {who && <td className="nowrap">{when(r.at)}</td>}{who && <td>{r.user}</td>}
      <td>{r.list}{r.record ? <> <b>{r.record.replace(/ \| /g, " · ")}</b></> : ""}</td>
      <td>{r.field ? r.field.replace(/_/g, " ") : r.old == null ? <i>added</i> : <i>removed</i>}</td>
      <td className="muted">{r.field ? val(r.old) : r.old == null ? "" : "the record"}</td>
      <td>{r.field ? val(r.new) : r.new == null ? "" : "the record"}</td></tr>)}</tbody>
  </table></div>;
}

/** Master-data changes waiting for a second person (Phase L). */
function Waiting({ id, canDecide, onDone }: { id: string; canDecide: boolean; onDone: (msg: string) => void }) {
  const pending = useStore((s) => s.company?.pending ?? 0);
  const [failed, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const revision = useStore((s) => s.company?.revision);
  const { value: list, show: setList, error: readErr } = useLatest<HeldChange[]>(() => api.heldChanges(id), [id, revision, pending]);
  const err = failed ?? readErr;
  if (!list?.length) return err ? <div className="banner error">{err}</div> : null;
  const decide = async (h: HeldChange, d: "approve" | "reject" | "withdraw") => {
    const note = d === "reject" ? window.prompt(`Why is ${h.by}'s change rejected? (optional, they see it)`) ?? "" : "";
    setBusy(true);
    setErr(null);
    try {
      if (d === "approve" && unsaved(store.get())) await store.saveNow();   // one's own changes first
      const rep = await api.decideHeld(id, h.id, d, note);
      if (d === "approve" && rep.dataset) await store.adoptServerSave(rep.meta, rep.dataset);
      else store.noteCompany(rep.meta);
      setList(await api.heldChanges(id));
      onDone(d === "approve" ? `${h.by}'s change #${h.id} approved and saved: ${h.summary}.` : `Change #${h.id} ${d === "reject" ? "rejected" : "withdrawn"}.`);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return <Panel title={`Waiting for approval (${list.length})`}>
    <p className="small muted" style={{ marginTop: 0 }}>Master data changes wait here until someone other than who made them approves
      them. Until then the company keeps what it had.</p>
    <div className="stack" style={{ gap: 14 }}>
      {list.map((h) => <div key={h.id} className="stack" style={{ gap: 6 }}>
        <div className="history-head"><b>#{h.id}</b><span className="history-when">{when(h.at)}</span><b>{h.by}</b>
          <span>{h.summary}</span><span className="spacer" />
          {h.by_me ? <button className="btn sm" disabled={busy} onClick={() => decide(h, "withdraw")}>Withdraw</button>
            : canDecide ? <>
              <button className="btn sm accent" disabled={busy} onClick={() => decide(h, "approve")}>Approve</button>
              <button className="btn sm" disabled={busy} onClick={() => decide(h, "reject")}>Reject</button></>
            : <span className="faint small">a planner or owner approves it</span>}
        </div>
        {h.by_me && <span className="faint small">Your change: someone else approves it.</span>}
        <FieldTable rows={h.changes} />
      </div>)}
    </div>
    {err && <div className="banner error">{err}</div>}
  </Panel>;
}

/** Change documents: every field changed on a record, old and new, with who and when. */
function RecordChanges({ id }: { id: string }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<FieldChangeRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const find = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setErr(null);
    try { setRows(await api.changes(id, q.trim())); } catch (x) { setErr(x instanceof Error ? x.message : String(x)); }
  };
  return <Panel title="Changes to a record, field by field">
    <form className="row wrap inline-form" style={{ gap: 8 }} onSubmit={find}>
      <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="A product, a place, an order number…"
        aria-label="Record to find changes of" />
      <button className="btn">Find</button>
      {rows && <span className="faint small">{rows.length >= 200 ? "the latest 200" : `${rows.length} changes`}</span>}
    </form>
    {rows && (rows.length ? <FieldTable rows={rows} who /> : <p className="muted small">No change recorded for “{q}”. Changes are
      recorded field by field from Phase L on; earlier saves show what they changed in the list below.</p>)}
    {err && <div className="banner error">{err}</div>}
  </Panel>;
}

export function History() {
  const company = useStore((s) => s.company);
  const ds = useStore((s) => s.dataset);
  const [history, setHistory] = useState<{ id: string; rows: LogRow[] } | null>(null);
  const request = useRef(0);
  const [more, setMore] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [cmp, setCmp] = useState<[number, Comparison] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const id = company?.id;
  const revision = company?.revision;
  const rows = history && history.id === id ? history.rows : null;

  const load = useCallback(async (before?: number) => {
    if (!id) return;
    const context = store.captureContext();
    const ticket = ++request.current;
    try {
      const got = await api.companyHistory(id, before);
      if (ticket !== request.current || !store.currentContext(context)) return;
      setHistory((r) => ({ id, rows: before && r?.id === id ? [...r.rows, ...got] : got }));
      setMore(got.length >= 200);
    } catch (e) {
      if (ticket === request.current && store.currentContext(context)) setErr(e instanceof Error ? e.message : String(e));
    }
  }, [id]);
  useEffect(() => { void load(); return () => { request.current++; }; }, [load, revision]);
  useEffect(() => { setErr(null); setMsg(null); setCmp(null); setOpen(null); }, [id]);

  if (!company) {
    return <div className="content"><Empty title="Not kept on the server">This company is kept only in this browser, so there is no
      history of its saves. <a href={href("account")}>Keep it on the server</a> to record who changes what.</Empty></div>;
  }
  const canPutBack = company.role !== "viewer";
  const compare = async (r: LogRow) => {
    if (!ds || r.revision == null) return;
    const context = store.captureWorking();
    setBusy(true);
    setErr(null);
    try {
      const then = await api.companyRevision(company.id, r.revision);
      store.assertWorking(context, true);
      const result = await api.compare(then, context.dataset, `revision ${r.revision}`, "now");
      store.assertWorking(context, true);
      setCmp([r.seq, result]);
    } catch (e) {
      if (store.currentContext(context)) setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const putBack = async (r: LogRow) => {
    if (r.revision == null) return;
    if (!window.confirm(`Put ${company.name} back to how it was after revision ${r.revision} (${when(r.at)}, ${r.user})? `
      + "Everyone then works on that. Nothing is lost: the current state stays in this history and can be put back too.")) return;
    const context = store.captureContext();
    setBusy(true);
    setErr(null);
    try {
      if (unsaved(store.get())) await store.saveNow();
      store.assertWorking(context, true);
      if (unsaved(store.get())) throw new Error("Your changes could not be saved. Keep or download them before restoring an earlier revision.");
      const latest = store.get().company?.revision ?? company.revision;
      const rep = await api.restoreCompany(company.id, r.revision, latest);
      store.assertWorking(context, true);
      store.openCompany(await api.company(company.id), context);
      setMsg(`Put back to revision ${r.revision}: ${rep.summary || "no change"}.`);
      setCmp(null);
    } catch (e) {
      if (store.currentContext(context)) setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <StageHeader title="History" kicker={<>Every save of <b>{company.name}</b>: who made it, when, and what changed. Compare an
        earlier state with now, or put the company back to it.</>}
        howLabel="How the history works" how={<>Each save is a revision, and every one is kept: any of them can be compared with now and put back (a new
          revision; nothing is lost). Saves made before every save was kept (one per person per ten minutes) show only what
          they changed.</>} />
      <div className="content">
        {msg && <div className="banner ok">{msg}</div>}
        {err && <div className="banner error">{err}</div>}
        <Waiting id={company.id} canDecide={company.role !== "viewer"} onDone={setMsg} />
        <Panel flush title={`Revision ${company.revision} is the latest`}>
          {!rows ? <Empty title="Loading…" /> : !rows.length ? <Empty title="Nothing recorded yet" /> : (
            <ol className="history">
              {rows.map((r) => {
                const [label, sev] = ACTION[r.action] ?? [r.action, undefined];
                const lists = r.changes;
                return (
                  <li key={r.seq} className={cmp?.[0] === r.seq ? "selected" : ""}>
                    <div className="history-head">
                      <span className="history-when">{when(r.at)}</span>
                      <b>{r.user}</b>
                      <Badge sev={sev}>{label}</Badge>
                      {r.revision != null && r.action !== "member" && <span className="faint small">revision {r.revision}</span>}
                      <span className="spacer" />
                      {r.kept && r.revision !== company.revision && <>
                        <button className="btn sm" disabled={busy} onClick={() => compare(r)}>Compare with now</button>
                        {canPutBack && <button className="btn sm" disabled={busy} onClick={() => putBack(r)}>Put back to this</button>}
                      </>}
                    </div>
                    <div className="history-what">{r.summary || <span className="faint">no change</span>}</div>
                    {lists.length > 0 && <button className="btn sm ghost" onClick={() => setOpen(open === r.seq ? null : r.seq)} aria-expanded={open === r.seq}>
                      {open === r.seq ? "Hide records" : "Which records"}</button>}
                    {open === r.seq && <ul className="history-lists">
                      {lists.map((c) => <li key={c.list}><b>{c.list}</b>
                        <div className="chips">{c.names.map((n) => <span className="chip" key={n}>{n}</span>)}
                          {c.added + c.removed + c.changed > c.names.length && <span className="faint small">…and {c.added + c.removed + c.changed - c.names.length} more</span>}</div></li>)}
                    </ul>}
                    {cmp?.[0] === r.seq && ds && <div className="history-compare"><CompareView c={cmp[1]} currency={ds.settings.currency} /></div>}
                  </li>
                );
              })}
            </ol>
          )}
          {rows && more && rows.length > 0 && <div style={{ padding: 12 }}><button className="btn sm" onClick={() => load(rows[rows.length - 1].seq)}>Older</button></div>}
        </Panel>
        <RecordChanges id={company.id} />
      </div>
    </div>
  );
}

