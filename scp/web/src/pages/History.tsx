// The company's history (Phase I, Q14): every save with who made it and what changed, membership changes, and a way
// to compare an earlier state with now or put the company back to it.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Comparison, LogRow } from "../api/types";
import { Badge, Empty, Panel, StageHeader } from "../components/ui";
import { when } from "../components/SaveStatus";
import { href } from "../lib/router";
import { store, unsaved, useStore } from "../state/store";
import { CompareView } from "./Versions";

const ACTION: Record<string, [string, "ok" | "info" | "warning" | undefined]> = {
  created: ["created", "ok"], saved: ["saved", undefined], restored: ["put back", "warning"], member: ["people", "info"],
  deleted: ["deleted", "warning"],
};

export function History() {
  const company = useStore((s) => s.company);
  const ds = useStore((s) => s.dataset);
  const [rows, setRows] = useState<LogRow[] | null>(null);
  const [more, setMore] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [cmp, setCmp] = useState<[number, Comparison] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const id = company?.id;
  const revision = company?.revision;

  const load = useCallback(async (before?: number) => {
    if (!id) return;
    try {
      const got = await api.companyHistory(id, before);
      setRows((r) => before ? [...(r ?? []), ...got] : got);
      setMore(got.length >= 200);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [id]);
  useEffect(() => { void load(); }, [load, revision]);

  if (!company) {
    return <div className="content"><Empty title="Not kept on the server">This company is kept only in this browser, so there is no
      history of its saves. <a href={href("account")}>Keep it on the server</a> to record who changes what.</Empty></div>;
  }
  const canPutBack = company.role !== "viewer";
  const compare = async (r: LogRow) => {
    if (!ds || r.revision == null) return;
    setBusy(true);
    setErr(null);
    try {
      const then = await api.companyRevision(company.id, r.revision);
      setCmp([r.seq, await api.compare(then, ds, `revision ${r.revision}`, "now")]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const putBack = async (r: LogRow) => {
    if (r.revision == null) return;
    if (!window.confirm(`Put ${company.name} back to how it was after revision ${r.revision} (${when(r.at)}, ${r.user})? `
      + "Everyone then works on that. Nothing is lost: the current state stays in this history and can be put back too.")) return;
    setBusy(true);
    setErr(null);
    try {
      if (unsaved(store.get())) await store.saveNow();
      const latest = store.get().company?.revision ?? company.revision;
      const rep = await api.restoreCompany(company.id, r.revision, latest);
      store.openCompany(await api.company(company.id));
      setMsg(`Put back to revision ${r.revision}: ${rep.summary || "no change"}.`);
      setCmp(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <StageHeader title="History" kicker={<>Every save of <b>{company.name}</b>: who made it, when, and what changed. Compare an
        earlier state with now, or put the company back to it.</>}
        how={<>Each save is a revision. The document of each person's run of saves within ten minutes is kept (the last of the
          run), so those revisions can be compared and put back; the others show what they changed.</>} />
      <div className="content">
        {msg && <div className="banner ok">{msg}</div>}
        {err && <div className="banner error">{err}</div>}
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
      </div>
    </div>
  );
}
