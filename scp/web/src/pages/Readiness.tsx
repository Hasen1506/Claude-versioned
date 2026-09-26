import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { RuleInfo } from "../api/types";
import { Checklist, setupTodo } from "../components/Checklist";
import { Badge, Panel, StageHeader } from "../components/ui";
import { checkTitle, objectWords } from "../lib/checks";
import { humanize } from "../lib/format";
import { href } from "../lib/router";
import { byKey, issueRoute, items, type CollectionKey } from "../model/collections";
import { useStore } from "../state/store";

export function Readiness() {
  const ds = useStore((s) => s.dataset);
  const validation = useStore((s) => s.validation);
  const schemaErrors = useStore((s) => s.schemaErrors);
  const checking = useStore((s) => s.checking);
  const [code, setCode] = useState("");
  const [rules, setRules] = useState<RuleInfo[]>([]);
  useEffect(() => { api.rules().then(setRules).catch(() => setRules([])); }, []);

  // unfinished records are in the checklist; the problem list is the rest
  const issues = useMemo(() => (validation?.issues ?? []).filter((i) => i.code !== "SET_ASIDE"), [validation]);
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    issues.forEach((i) => m.set(i.code, (m.get(i.code) ?? 0) + 1));
    return m;
  }, [issues]);
  const shown = code ? issues.filter((i) => i.code === code) : issues;
  const errors = issues.filter((i) => i.severity === "error").length;
  const todo = setupTodo(validation).length;
  const nm = useMemo(() => {
    const l = Object.fromEntries((ds?.locations ?? []).map((x) => [x.id, x.name || x.id])) as Record<string, string>;
    const p = Object.fromEntries((ds?.products ?? []).map((x) => [x.id, x.name || x.id])) as Record<string, string>;
    return { loc: (id: string) => l[id] ?? id, prod: (id: string) => p[id] ?? id };
  }, [ds]);

  const verdict = checking && !validation ? <Badge sev="info">Checking…</Badge>
    : schemaErrors.length ? <Badge sev="error">Can't read {schemaErrors.length === 1 ? "one value" : `${schemaErrors.length} values`}</Badge>
    : errors ? <Badge sev="error">{errors} problem{errors === 1 ? "" : "s"} stop planning</Badge>
    : todo ? <Badge sev="warning">{todo} thing{todo === 1 ? "" : "s"} still to set up</Badge>
    : <Badge sev="ok">Ready to plan</Badge>;

  return (
    <div>
      <StageHeader title="Data check" kicker={<>What is still missing before your company can be planned, and anything in the data that
        would make the plan wrong. It runs again on every change.</>}
        how={<>The checklist follows the order you set a company up in: places, products, demand, how each product is supplied and
          made, and stock. Below it, a set of rules, like SAP's readiness checks, looks for data that contradicts itself.
          <b> Stop planning</b> problems must be fixed first; the others are planned around. A record you haven't finished is
          left out of the plan until it is, so it never stops the rest.</>}
        right={verdict} />
      <div className="content stack">

      {schemaErrors.length > 0 && (
        <Panel title="These values can't be read">
          <p className="muted small" style={{ marginTop: 0 }}>Nothing can be checked or planned until they are fixed.</p>
          <table className="t">
            <thead><tr><th>Where</th><th>Problem</th></tr></thead>
            <tbody>
              {schemaErrors.map((e, i) => {
                const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
                const coll = byKey[loc[0] as CollectionKey];
                const rec = coll && ds && typeof loc[1] === "number" ? items(ds, coll.key)[loc[1]] : undefined;
                const key = coll && rec ? coll.keyOf(rec, loc[1] as number) : null;
                const link = coll && key ? href("data", coll.key, key) : loc[0] === "settings" ? href("data", "settings") : null;
                const where = loc[0] === "settings" ? "Company settings" : coll ? `${coll.singular[0].toUpperCase()}${coll.singular.slice(1)} ${key ?? ""}` : String(loc[0]);
                return (
                  <tr key={i}>
                    <td>{link ? <a href={link}>{where}</a> : where}</td>
                    <td>{e.msg}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
      )}

      {validation && (
        <Panel title="What's missing">
          {validation.setup?.length ? <Checklist items={validation.setup} /> : <p className="muted">Nothing to check yet.</p>}
        </Panel>
      )}

      {!schemaErrors.length && validation && (<>
        <Panel flush title={<h3>Problems in the data</h3>}
          actions={issues.length > 0 ? <select className="select" style={{ width: "auto" }} value={code} onChange={(e) => setCode(e.target.value)} aria-label="Show">
            <option value="">All ({issues.length})</option>
            {[...counts.entries()].map(([c, n]) => <option key={c} value={c}>{checkTitle(c)} ({n})</option>)}
          </select> : undefined}>
          {shown.length ? (
            <div className="table-wrap">
              <table className="t">
                <thead><tr><th>Effect</th><th>Problem</th><th>Where</th><th>How to fix</th></tr></thead>
                <tbody>
                  {shown.map((i, n) => {
                    let r = issueRoute(i.object_type, i.object_id);
                    // a product at a place with no planning record yet: its setup page, where the record is made
                    if (i.object_type === "location_product" && ds && !(ds.location_products ?? []).some((x) => `${x.location}/${x.product}` === i.object_id)) {
                      const [l, p] = i.object_id.split("/");
                      r = ["setup", "product", p, l];
                    }
                    const what = objectWords(i.object_type, i.object_id, nm);
                    return (
                      <tr key={n}>
                        <td className="nowrap"><Badge sev={i.severity === "error" ? "error" : "warning"}>{i.severity === "error" ? "Stops planning" : "Planned around"}</Badge></td>
                        <td><b>{checkTitle(i.code)}</b><div className="small muted">{humanize(i.message)}</div></td>
                        <td>{r ? <a href={href(...r)}>{what}</a> : what}</td>
                        <td className="muted small">{i.hint}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty"><Badge sev="ok">None found</Badge><p>Nothing in the data contradicts itself.</p></div>
          )}
        </Panel>
        <details>
          <summary className="muted" style={{ cursor: "pointer" }}>All {rules.length} rules the check applies</summary>
          <Panel flush>
            <table className="t">
              <tbody>{rules.map((r) => (
                <tr key={r.code}><td>{checkTitle(r.code)}</td>
                  <td className="nowrap"><Badge sev={r.severity === "error" ? "error" : "warning"}>{r.severity === "error" ? "Stops planning" : "Planned around"}</Badge></td>
                  <td className="mono faint small">{r.code}</td></tr>
              ))}</tbody>
            </table>
          </Panel>
        </details>
      </>)}
      </div>
    </div>
  );
}
