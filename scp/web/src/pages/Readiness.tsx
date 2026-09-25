import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { RuleInfo } from "../api/types";
import { Badge, Panel } from "../components/ui";
import { byKey, issueRoute, type CollectionKey } from "../model/collections";
import { href } from "../lib/router";
import { useStore } from "../state/store";

export function Readiness() {
  const validation = useStore((s) => s.validation);
  const schemaErrors = useStore((s) => s.schemaErrors);
  const checking = useStore((s) => s.checking);
  const [code, setCode] = useState("");
  const [rules, setRules] = useState<RuleInfo[]>([]);
  useEffect(() => { api.rules().then(setRules).catch(() => setRules([])); }, []);

  const issues = validation?.issues ?? [];
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    issues.forEach((i) => m.set(i.code, (m.get(i.code) ?? 0) + 1));
    return m;
  }, [issues]);
  const shown = code ? issues.filter((i) => i.code === code) : issues;
  const errors = issues.filter((i) => i.severity === "error").length;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Readiness</h1>
          <p>Master-data checks that run before any plan, like the SAP readiness gate: most "the system planned it wrong"
            problems are data defects. Errors block planning; warnings are planned around and shown with the plan.</p>
        </div>
        <span className="spacer" />
        {checking ? <Badge sev="info">Checking…</Badge> : schemaErrors.length ? <Badge sev="error">Cannot read dataset</Badge>
          : errors ? <Badge sev="error">{errors} blocking</Badge> : <Badge sev="ok">Ready to plan</Badge>}
      </div>

      {schemaErrors.length > 0 && (
        <Panel title="The engine rejected these values">
          <p className="muted small" style={{ marginTop: 0 }}>These are type or range errors (e.g. a percentage typed where a fraction is expected). Fix them first.</p>
          <table className="t">
            <thead><tr><th>Where</th><th>Problem</th></tr></thead>
            <tbody>
              {schemaErrors.map((e, i) => {
                const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
                const coll = byKey[loc[0] as CollectionKey];
                const link = coll && typeof loc[1] === "number" ? href("data", coll.key) : loc[0] === "settings" ? href("settings") : null;
                return (
                  <tr key={i}>
                    <td><code>{loc.join(" › ")}</code>{link && <> · <a href={link}>open</a></>}</td>
                    <td>{e.msg}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
      )}

      {!schemaErrors.length && (
        <div className="stack">
          <div className="chips">
            <button className={`btn sm ${code === "" ? "primary" : ""}`} onClick={() => setCode("")}>All ({issues.length})</button>
            {[...counts.entries()].map(([c, n]) => (
              <button key={c} className={`btn sm ${code === c ? "primary" : ""}`} onClick={() => setCode(c)}>{c} ({n})</button>
            ))}
          </div>
          <Panel flush>
            {shown.length ? (
              <table className="t">
                <thead><tr><th>Severity</th><th>Check</th><th>Object</th><th>Problem</th><th>How to fix</th></tr></thead>
                <tbody>
                  {shown.map((i, n) => {
                    const r = issueRoute(i.object_type, i.object_id);
                    return (
                      <tr key={n}>
                        <td><Badge sev={i.severity === "error" ? "error" : "warning"} /></td>
                        <td><code>{i.code}</code></td>
                        <td>{r ? <a href={href(...r)}>{i.object_type} {i.object_id}</a> : `${i.object_type} ${i.object_id}`}</td>
                        <td>{i.message}</td>
                        <td className="muted">{i.hint}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="empty"><Badge sev="ok">No issues</Badge><p>Every readiness check passes.</p></div>
            )}
          </Panel>
          <details>
            <summary className="muted" style={{ cursor: "pointer" }}>All {rules.length} readiness checks</summary>
            <Panel flush>
              <table className="t">
                <tbody>{rules.map((r) => (
                  <tr key={r.code}><td><code>{r.code}</code></td><td><Badge sev={r.severity === "error" ? "error" : "warning"} /></td><td>{r.description}</td></tr>
                ))}</tbody>
              </table>
            </Panel>
          </details>
        </div>
      )}
    </div>
  );
}
