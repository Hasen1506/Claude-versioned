import { useEffect, useState } from "react";
import { api, RUN_TIMEOUT_MS } from "../api/client";
import type { ScenarioCheck, ScenarioInfo, ScenarioReport, ScenarioStep } from "../api/types";
import { Badge, Empty, Panel, SectionBand, SevIcon, StageHeader, StatTile } from "../components/ui";
import { go, href, type Route } from "../lib/router";
import { STAGES, stageById } from "../lib/stages";
import { store, useStore } from "../state/store";

// The stages a scenario can touch: the planning spine plus versions, which sits outside it.
const COLUMNS = [...STAGES, { id: "versions", n: "V", name: "Versions", sub: "branch · compare · promote" }];

// Reports survive leaving the page; they describe the engine, not the open dataset.
const cache: Record<string, ScenarioReport> = {};

/** A value as a planner would write it: 22.613, not 22.61299875788332; nested lists in brackets. */
export function show(v: unknown, depth = 0): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(7)));
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v === "" ? "“”" : v;
  if (Array.isArray(v)) {
    if (!v.length) return "none";
    const s = v.map((x) => show(x, depth + 1)).join(", ");
    return depth ? `(${s})` : s;
  }
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${show(x, depth + 1)}`).join(" · ");
  return String(v);
}

const stagesOf = (step: ScenarioStep) => step.stage.split("+");

const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];
const word = (n: number) => WORDS[n] ?? String(n);
const clock = (s: number) => (s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`);

function perStage(r: ScenarioReport | undefined) {
  const out: Record<string, { passed: number; failed: number }> = {};
  for (const s of r?.steps ?? [])
    for (const st of stagesOf(s)) {
      const o = (out[st] ??= { passed: 0, failed: 0 });
      o.passed += s.checks.filter((c) => c.passed).length;
      o.failed += s.checks.filter((c) => !c.passed).length + (s.error ? 1 : 0);
    }
  return out;
}

export function Proof({ route }: { route: Route }) {
  const [infos, setInfos] = useState<ScenarioInfo[] | null>(null);
  const [reports, setReports] = useState<Record<string, ScenarioReport>>(() => ({ ...cache }));
  const [running, setRunning] = useState<string | null>(null);
  const [started, setStarted] = useState(0);
  const [now, setNow] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.scenarios().then(setInfos).catch((e) => setErr(String(e))); }, []);
  // a run answers only when it is done, so show how long it has been going
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  const run = async (id: string) => {
    setRunning(id);
    setStarted(Date.now());
    setNow(Date.now());
    setErr(null);
    try {
      const r = await api.runScenario(id);
      cache[id] = r;
      setReports((m) => ({ ...m, [id]: r }));
    } catch (e) {
      setErr(`${id}: ${String(e)}`);
    } finally {
      setRunning(null);
    }
  };
  const runAll = async () => { for (const s of infos ?? []) await run(s.id); };

  if (err && !infos) return <div className="content"><div className="banner error">Engine unreachable: {err}</div></div>;
  if (!infos) return <div className="content faint">Loading scenarios…</div>;

  const selected = infos.find((s) => s.id === route[1]) ?? infos[0];
  const done = infos.filter((s) => reports[s.id]);
  const passed = done.reduce((a, s) => a + reports[s.id].passed, 0);
  const failed = done.reduce((a, s) => a + reports[s.id].failed, 0);
  const declared = new Set(infos.flatMap((s) => s.stages));
  const proven = new Set(done.filter((s) => reports[s.id].ok).flatMap((s) => s.stages));
  const count = (set: Set<string>) => STAGES.filter((s) => set.has(s.id)).length;
  const caught = infos.reduce((a, s) => a + (s.found?.length ?? 0), 0);
  const generated = infos.filter((s) => s.generated).length;
  const byHand = infos.length - generated;
  const elapsed = running ? clock(Math.max(0, Math.round((now - started) / 1000))) : "";
  const current = infos.find((s) => s.id === running);
  const name = current ? (current.generated ? current.title : current.company) : running;
  const last = running ? cache[running]?.seconds : undefined;

  return (
    <div>
      <StageHeader n="QED" title="Proof" kicker={<>{word(byHand)} fictional companies, each worked out by hand before the engine ran: every
        checkpoint sets the engine's answer beside one derived independently (a closed form, a full enumeration, a brute-force
        search or a second solver) with the arithmetic in between.{generated > 0 && <> {generated === 1 ? "One more runs" : `${word(generated)} more run`} the
        same flow over generated companies and {generated === 1 ? "checks" : "check"} what must hold for any plan.</>} Runs use a private
        in-memory store: your data is never touched.</>}
        right={<>
          {done.length > 0 && (failed ? <Badge sev="error">{failed} failed</Badge> : <Badge sev="ok">{passed} checkpoints hold</Badge>)}
          <button className="btn accent" disabled={!!running} onClick={runAll}>{running ? `Running ${name}… ${elapsed}` : `Run all ${infos.length}`}</button>
        </>} />
      <div className="content stack">
        {err && <div className="banner error">{err}</div>}
        {running && <div className="banner info" role="status">
          <span><b>{name}</b> has been running for {elapsed}.{last !== undefined && <> Its last run here took {clock(Math.round(last))}.</>}
            {current?.generated && <> It plans and checks many generated companies, so it takes the longest.</>} The engine answers once the whole run is
            done; the page waits up to {Math.round(RUN_TIMEOUT_MS / 60_000)} minutes before it gives up.</span>
        </div>}
        <div className="grid-auto">
          <StatTile label="Scenarios" value={infos.length} sub={generated ? `${byHand} worked by hand · ${generated} generated` : "companies, end to end"} />
          <StatTile label="Checkpoints" value={done.length ? `${passed}/${passed + failed}` : "—"}
            sub={done.length ? `${done.length} of ${infos.length} scenarios run` : "run to verify"} tone={done.length === infos.length && !failed ? "hl" : undefined} />
          <StatTile label="Stages proven" value={done.length ? `${count(proven)}/${STAGES.length}` : "—"}
            sub={done.length ? `by the passing runs · ${count(declared)} in the suite` : `${count(declared)} in the suite · run to prove`} />
          <StatTile label="Defects caught" value={caught} sub="each fixed, each with a regression test" />
        </div>

        <SectionBand step="A" title="Coverage" right={<span className="faint small">rows: scenarios · columns: stages of the spine · numbers: checkpoints</span>} />
        <Panel flush>
          <div className="table-wrap">
            <table className="t cov">
              <thead>
                <tr>
                  <th className="stub">Scenario</th>
                  {COLUMNS.map((c) => <th key={c.id} className="c" title={c.name}>{c.n}<span className="nm">{c.name}</span></th>)}
                  <th className="num">Result</th>
                </tr>
              </thead>
              <tbody>
                {infos.map((s, i) => {
                  const r = reports[s.id];
                  const by = perStage(r);
                  return (
                    <tr key={s.id} className={`clickable ${s.id === selected.id ? "selected" : ""}`} onClick={() => go("proof", s.id)}>
                      <td className="stub">
                        <a href={href("proof", s.id)} onClick={(e) => e.stopPropagation()}><b>S{i + 1}</b> {s.company}</a>
                        <div className="faint small">{s.title}</div>
                      </td>
                      {COLUMNS.map((c) => {
                        const on = s.stages.includes(c.id);
                        const x = by[c.id];
                        const cls = !on ? "" : !x ? "on" : x.failed ? "on fail" : "on pass";
                        return (
                          <td key={c.id} className={`c ${cls}`} title={on ? `${c.name}${x ? `: ${x.passed} passed${x.failed ? `, ${x.failed} failed` : ""}` : ""}` : ""}>
                            {on && (x ? <>{x.failed ? "✕" : ""}{x.passed + x.failed}</> : <span className="pip" aria-label="covered" />)}
                          </td>
                        );
                      })}
                      <td className="num">
                        {running === s.id ? <span className="faint">running… {elapsed}</span>
                          : r ? <Badge sev={r.ok ? "ok" : "error"}>{r.passed}/{r.passed + r.failed}</Badge>
                          : <button className="btn sm" disabled={!!running} onClick={(e) => { e.stopPropagation(); run(s.id); }}>Run</button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>

        <Scenario info={selected} n={infos.indexOf(selected) + 1} report={reports[selected.id]}
          running={running === selected.id ? elapsed : null} busy={!!running} onRun={() => run(selected.id)} />
      </div>
    </div>
  );
}

function Scenario({ info, n, report, running, busy, onRun }: {
  info: ScenarioInfo; n: number; report?: ScenarioReport; running: string | null; busy: boolean; onRun: () => void;
}) {
  const open = useStore((s) => s.dataset);
  const [only, setOnly] = useState(false);
  const openData = async () => {
    if (open && !window.confirm(`Replace the open dataset with ${info.company}'s starting data? Export it first if you want to keep it.`)) return;
    store.load(await api.scenarioDataset(info.id));
    go(info.stages.find((s) => stageById[s]) ?? "network");
  };
  const steps = report?.steps.filter((s) => !only || s.error || s.checks.some((c) => !c.passed)) ?? [];
  return (
    <>
      <SectionBand step={`S${n}`} title={`${info.company} · ${info.title}`} right={<div className="row wrap">
        <button className="btn" onClick={openData} title="Load this scenario's starting dataset and follow the workflow yourself">Open starting data</button>
        <button className="btn primary" disabled={busy} onClick={onRun}>{running !== null ? `Running… ${running}` : report ? "Run again" : "Run"}</button>
      </div>} />
      <p className="story">{info.story}</p>
      <div className="grid-2">
        <Panel title="What it proves">
          <ul className="ticks">{info.proves.map((p) => <li key={p}><SevIcon sev="ok" />{p}</li>)}</ul>
        </Panel>
        <Panel title={`What it caught (${info.found?.length ?? 0})`}>
          {info.found?.length ? <ul className="ticks">{info.found.map((p) => <li key={p}><SevIcon sev="error" />
            <span>{p} <span className="faint">· fixed</span></span></li>)}</ul>
            : <p className="muted small" style={{ margin: 0 }}>No engine defects: the schedule matched the brute-force optimum first time.</p>}
        </Panel>
      </div>

      {!report ? (
        <Panel><Empty title="Not run yet">
          <p className="muted">Run it to see every step: the API call it makes, what should happen and why, and each checkpoint's
            hand-derived value beside the engine's.</p>
          <button className="btn accent" disabled={busy} onClick={onRun}>{running !== null ? `Running… ${running}` : "Run this scenario"}</button>
        </Empty></Panel>
      ) : (
        <>
          <div className="row wrap">
            {report.ok ? <Badge sev="ok">All {report.passed} checkpoints hold</Badge> : <Badge sev="error">{report.failed} of {report.passed + report.failed} failed</Badge>}
            <span className="faint small mono">{report.steps.length} steps · {(report.seconds * 1000).toFixed(0)} ms · engine client</span>
            <span className="spacer" style={{ flex: 1 }} />
            <div className="seg" role="group" aria-label="Filter checkpoints">
              <button className={only ? "" : "on"} onClick={() => setOnly(false)}>All steps</button>
              <button className={only ? "on" : ""} onClick={() => setOnly(true)}>Failures only</button>
            </div>
          </div>
          {only && !steps.length && <div className="banner ok">Nothing failed.</div>}
          {steps.map((s) => <Step key={s.n} step={s} />)}
        </>
      )}
    </>
  );
}

function Step({ step }: { step: ScenarioStep }) {
  const bad = step.error || step.checks.some((c) => !c.passed);
  return (
    <section className={`panel proof-step ${bad ? "bad" : ""}`}>
      <div className="panel-head">
        <span className="stepno">{step.n}</span>
        <h3>{step.title}</h3>
        <span className="spacer" style={{ flex: 1 }} />
        {stagesOf(step).map((st) => <span key={st} className="chip">{stageById[st] ? `${stageById[st].n} ${stageById[st].name}` : st}</span>)}
        <code className="call">{step.call}</code>
      </div>
      <div className="panel-body flush">
        {step.narrative && <p className="narr">{step.narrative}</p>}
        {step.error && <div className="banner error" style={{ margin: 12 }}>The step stopped: {step.error}</div>}
        {step.checks.length > 0 && (
          <table className="t checks">
            <thead><tr><th aria-label="Result" /><th>Checkpoint</th><th>Worked by hand</th><th>Engine</th></tr></thead>
            <tbody>{step.checks.map((c, i) => <CheckRow key={i} c={c} />)}</tbody>
          </table>
        )}
      </div>
    </section>
  );
}

/** A long value (a whole set of findings) folds to a few lines until asked for. */
function Val({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  if (text.length <= 240 || all) return <>{text}</>;
  return <>{text.slice(0, 200)}… <button className="linkish" onClick={() => setAll(true)}>show all {text.split(", ").length}</button></>;
}

function CheckRow({ c }: { c: ScenarioCheck }) {
  const e = show(c.expected);
  const a = show(c.actual);
  const same = c.passed && a === e;
  return (
    <tr className={c.passed ? "" : "fail"}>
      <td className="ic"><SevIcon sev={c.passed ? "ok" : "error"} /><span className="sr">{c.passed ? "passed" : "failed"}</span></td>
      <td>
        <div className="lbl">{c.label}</div>
        {c.why && <div className="why">{c.why}</div>}
      </td>
      <td className="v" title={JSON.stringify(c.expected)}><Val text={e} />{c.tolerance != null && c.tolerance > 0 && <div className="tol">± {show(c.tolerance)}</div>}</td>
      <td className="v" title={JSON.stringify(c.actual)}>{same && a.length > 60 ? <span className="same">identical</span>
        : same ? <span className="same">{a}</span> : <Val text={a} />}</td>
    </tr>
  );
}
