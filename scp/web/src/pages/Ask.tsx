import { useState } from "react";
import { api } from "../api/client";
import type { AskAnswer, AskCite, AskProposal, Dataset, FixResult, VersionMeta, WhatIfChip } from "../api/types";
import { Empty, Panel } from "../components/ui";
import { money } from "../lib/format";
import { href } from "../lib/router";
import { store, useReadOnly } from "../state/store";
import { FixOutcome, keepEdits } from "./Tower";

const EXAMPLES = ["What is at risk?", "Why is anything late?", "Who owns the open problems?", "What if demand rises 20 %?"];

/** Enterprise plan 5.2: a question in plain words, answered from the plan's own records (engine: tower/ask.py). Every
 *  sentence cites the records it rests on; what it proposes is tried on a copy and kept by a person. */
export function Ask({ ds }: { ds: Dataset }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskAnswer | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const cur = ds.settings.currency;
  const run = (question: string) => {
    const text = question.trim();
    if (!text) return;
    setQ(text); setBusy(true); setErr(null);
    // the data as it is now (after a kept fix, the store's newest copy)
    api.ask(store.get().dataset ?? ds, text).then(setRes)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false));
  };
  return (
    <div className="stack">
      <Panel>
        <form className="ask-form" onSubmit={(e) => { e.preventDefault(); run(q); }}>
          <label className="ask-label" htmlFor="ask-q">Ask the plan</label>
          <div className="row" style={{ gap: 8 }}>
            <input id="ask-q" className="input ask-input" value={q} maxLength={500} onChange={(e) => setQ(e.target.value)}
              placeholder="Why is the kettle late for E-commerce? What if Hindalco is out? Who owns MG-750?" />
            <button className="btn primary" type="submit" disabled={busy || !q.trim()}>{busy ? "Asking…" : "Ask"}</button>
          </div>
          <div className="row wrap" style={{ gap: 6 }} aria-label="Questions to try">
            {(res?.suggestions.length ? res.suggestions : EXAMPLES).map((s) => (
              <button key={s} type="button" className="chip-btn" disabled={busy} onClick={() => run(s)}>{s}</button>
            ))}
          </div>
          <p className="small faint" style={{ margin: 0 }}>Answered from this plan and its open problems, never from
            outside it: every sentence links to the records it rests on. Asking changes nothing; a fix it offers is tried
            on a copy first, and kept only if you keep it.</p>
        </form>
      </Panel>
      {err && <div className="banner error" role="alert">{err}</div>}
      {res ? <Answer a={res} cur={cur} ds={ds} onAgain={() => run(res.question)} />
        : !err && <Panel><Empty title="Nothing asked yet">Ask why something is late, what happens if something changes,
          who owns a problem, or what is at risk.</Empty></Panel>}
    </div>
  );
}

function CiteLink({ c }: { c: AskCite }) {
  const label = c.label && c.label !== c.id ? `${c.id} · ${c.label}` : c.id;
  // a demand's or a problem's id is the plan's own key: it is named in words instead
  const text = c.kind === "exception" ? "problem" : c.kind === "demand" ? "demand" : c.id;
  return <a className="cite" href={c.href || "#"} title={`${c.kind}: ${label}`}>{text}</a>;
}

function Answer({ a, cur, ds, onAgain }: { a: AskAnswer; cur: string; ds: Dataset; onAgain: () => void }) {
  return (
    <section className="stack" aria-label="The answer">
      <Panel>
        <div className="small muted" aria-label="Read as">Read as: <b>{a.understood}</b></div>
        <p className="ask-answer" role="status">{a.answer}</p>
        {a.findings.length > 0 && <ol className="ask-findings" aria-label="Why">
          {a.findings.map((f, i) => (
            <li key={i}>
              <div>{f.text} {f.cites.map((c, j) => <CiteLink key={j} c={c} />)}</div>
              {f.chain.length > 0 && <details open={i === 0} className="ask-chain">
                <summary className="small muted">What holds it up ({f.chain.length} step{f.chain.length === 1 ? "" : "s"})</summary>
                <ol>{f.chain.map((s, j) => <li key={j} className="small">{s.text} {s.cites.map((c, k) => <CiteLink key={k} c={c} />)}</li>)}</ol>
              </details>}
            </li>
          ))}
        </ol>}
        {a.more > 0 && <div className="small faint">and {a.more} more not listed: narrow the question by product or customer.</div>}
      </Panel>
      {a.proposals.length > 0 && <Panel title="What to do about it">
        <div className="stack" style={{ gap: 10 }}>
          {a.proposals.map((p, i) => <ProposalRow key={`${p.kind}-${p.key}-${i}`} p={p} cur={cur} ds={ds} onKept={onAgain} />)}
        </div>
      </Panel>}
    </section>
  );
}

function ProposalRow({ p, cur, ds, onKept }: { p: AskProposal; cur: string; ds: Dataset; onKept: () => void }) {
  const ro = useReadOnly();
  const [state, setState] = useState<{ busy?: boolean; fix?: FixResult; error?: string; kept?: VersionMeta }>({});
  const tryIt = () => {
    setState({ busy: true });
    api.towerFix(store.get().dataset ?? ds, p.key).then((fix) => setState({ fix }))
      .catch((e) => setState({ error: e instanceof Error ? e.message : String(e) }));
  };
  const keepScenario = async () => {
    setState({ busy: true });
    try {
      const before = store.captureWorking();
      const out = await api.keepWhatIf(before.dataset, p.name,
        p.chips as WhatIfChip[], before.version?.id ?? null);
      if (out.base) store.saved(out.base, before);
      setState({ kept: out.version });
    } catch (e) {
      setState({ error: e instanceof Error ? e.message : String(e) });
    }
  };
  return (
    <div className="ask-proposal" data-kind={p.kind}>
      <div className="row wrap" style={{ gap: 8, alignItems: "center" }}>
        {p.kind === "fix" && <button className="btn sm primary" aria-label={`Try it: ${p.label}`} disabled={state.busy}
          onClick={tryIt}>{state.busy ? "Trying…" : "Try it"}</button>}
        {p.kind === "scenario" && !ro && !state.kept && <button className="btn sm primary" disabled={state.busy}
          onClick={keepScenario}>{state.busy ? "Keeping…" : "Keep as a scenario"}</button>}
        {p.kind === "open" && <a className="btn sm" href={p.href || "#/tower/inbox"}>Open</a>}
        <span><b>{p.kind === "scenario" ? `“${p.name}”` : p.label}</b>
          {p.message && <span className="small muted"> · {p.message}</span>}</span>
        {(p.kind === "fix" || p.kind === "open") && <span className="small faint">protects {money(p.protects, cur)}
          {p.costs !== null && p.costs !== undefined ? ` · costs ${money(p.costs, cur)}` : ""}</span>}
      </div>
      {p.kind === "open" && p.why_not && <div className="small faint">Not in one click: {p.why_not}</div>}
      {state.error && <div className="banner error" role="alert">{state.error}</div>}
      {state.kept && <div className="small" role="status">Kept as the scenario <a href={href("versions")}>{state.kept.name}</a>: open
        it under Versions to compare or promote it.</div>}
      {state.fix && <FixOutcome f={state.fix} cur={cur} ro={ro}
        onKeep={() => { keepEdits(state.fix!.edits); setState({}); onKept(); }} onLeave={() => setState({})} />}
    </div>
  );
}
