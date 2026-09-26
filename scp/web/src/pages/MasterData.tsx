import { useMemo, useState } from "react";
import type { Dataset, Issue, ValidationResult } from "../api/types";
import { Badge, Empty, Panel, StageHeader } from "../components/ui";
import { byKey, COLLECTIONS, items, whereUsed, type CollectionKey } from "../model/collections";
import { ImportPanel } from "../components/Import";
import { checkTitle } from "../lib/checks";
import { humanize } from "../lib/format";
import { go, href } from "../lib/router";
import { defaults, SchemaForm, useSchema, type FieldErrors } from "../schema/SchemaForm";
import { store, useStore, NO_ISSUES } from "../state/store";

type Obj = Record<string, unknown>;
const NO_ASIDE: NonNullable<ValidationResult["set_aside"]> = [];

export function MasterData({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset);
  const issues = useStore((s) => s.validation?.issues ?? NO_ISSUES);
  const key = (route[1] as CollectionKey) || "locations";
  if (!ds) return null;
  const def = byKey[key];
  const body = key === ("settings" as CollectionKey) ? <SettingsEditor />
    : !def ? <Empty title="Unknown data type" />
    : <CollectionView key={key} ds={ds} ckey={key} selected={route[2]} issues={issues} />;
  return <div className="md-layout"><DataIndex ds={ds} current={key} issues={issues} /><div className="md-main">{body}</div></div>;
}

/** Every table of master data, grouped, with its row count and any data-check problems. A select on a phone. */
function DataIndex({ ds, current, issues }: { ds: Dataset; current: string; issues: Issue[] }) {
  const problems = (type: string) => issues.filter((i) => i.object_type === type).length;
  return (
    <nav className="md-index" aria-label="Master data tables">
      <select className="select md-select" value={current} aria-label="Table" onChange={(e) => go("data", e.target.value)}>
        <option value="settings">Company settings</option>
        {DATA_GROUPS.map((g) => <optgroup key={g} label={g}>
          {COLLECTIONS.filter((c) => c.group === g).map((c) => <option key={c.key} value={c.key}>{c.label} ({items(ds, c.key).length})</option>)}
        </optgroup>)}
      </select>
      <div className="md-list">
        <a className={current === "settings" ? "on" : ""} href={href("data", "settings")}>Company settings</a>
        {DATA_GROUPS.map((g) => (
          <div key={g}>
            <div className="md-group">{g}</div>
            {COLLECTIONS.filter((c) => c.group === g).map((c) => {
              const n = problems(c.issueType);
              return <a key={c.key} className={current === c.key ? "on" : ""} href={href("data", c.key)}>
                <span>{c.label}</span>{n > 0 ? <Badge sev="warning">{n}</Badge> : <span className="faint">{items(ds, c.key).length}</span>}</a>;
            })}
          </div>
        ))}
      </div>
    </nav>
  );
}

function issuesFor(issues: Issue[], type: string, id: string) {
  const key = type === "location_product" ? id.replace("|", "/") : id;
  return issues.filter((i) => i.object_type === type && i.object_id === key);
}

function CollectionView({ ds, ckey, selected, issues }: { ds: Dataset; ckey: CollectionKey; selected?: string; issues: Issue[] }) {
  const def = byKey[ckey];
  const list = items(ds, ckey);
  const schema = useSchema();
  const schemaErrors = useStore((s) => s.schemaErrors);
  const [q, setQ] = useState("");
  const [upload, setUpload] = useState(false);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return list.map((o, i) => ({ o, i, k: def.keyOf(o, i) })).filter(({ o }) =>
      !needle || def.columns.some((c) => String(c.get(o, ds) ?? "").toLowerCase().includes(needle)));
  }, [list, q, def, ds]);
  const shown = rows.slice(0, 500);
  const selIndex = selected !== undefined ? list.findIndex((o, i) => def.keyOf(o, i) === selected) : -1;
  const sel = selIndex >= 0 ? list[selIndex] : null;

  const aside = useStore((s) => s.validation?.set_aside ?? NO_ASIDE);
  const errFor = (index: number): FieldErrors => {
    const out: FieldErrors = {};
    // a record the data check set aside: show why on the field to fix
    for (const a of aside) if (a.collection === ckey && a.index === index) out[a.field ?? ""] = a.reason;
    for (const e of schemaErrors) {
      const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
      if (loc[0] === ckey && loc[1] === index) out[loc.slice(2).join(".")] = e.msg;
    }
    return out;
  };
  const issueCount = (o: Obj, i: number) => issuesFor(issues, def.issueType, def.keyOf(o, i));

  const add = () => {
    if (!schema) return;
    const seed: Obj = {};
    if ("id" in (schema.$defs[def.defName].properties ?? {})) {
      let n = list.length + 1;
      const prefix = def.singular.split(" ").map((w) => w[0]).join("").toUpperCase();
      while (list.some((o) => o.id === `${prefix}-${n}`)) n++;
      seed.id = `${prefix}-${n}`;
    }
    const start = ds.settings.planning_start;
    if (ckey === "demand" || ckey === "overrides") seed.date = start;
    if (ckey === "receipts") seed.due_date = start;
    if (ckey === "npi") seed.launch_date = start;
    if (ckey === "events") { seed.start = start; seed.end = start; }
    if (ckey === "history") {
      const d = new Date(start + "T00:00:00Z");
      d.setUTCDate(d.getUTCDate() - 7);
      seed.date = d.toISOString().slice(0, 10);
    }
    if (ckey === "overrides") seed.change = 0;
    // start valid: a lane needs a transport mode, and a reference with only one sensible choice is filled in
    if (ckey === "lanes") seed.modes = [{ mode: "truck_ftl", transit_days: 1 }];
    const only = (types: string[]) => {
      const c = (ds.locations ?? []).filter((l) => types.includes(l.type));
      return c.length === 1 ? c[0].id : "";
    };
    const onlyProduct = (types: string[]) => {
      const c = (ds.products ?? []).filter((p) => types.includes(p.type));
      return c.length === 1 ? c[0].id : (ds.products ?? []).length === 1 ? ds.products![0].id : "";
    };
    if (ckey === "resources" || ckey === "production_sources") seed.location = only(["plant"]);
    if (ckey === "production_sources") seed.product = onlyProduct(["FG", "SFG"]);
    if (ckey === "purchasing_sources") { seed.supplier = only(["supplier"]); seed.product = onlyProduct(["RM", "PKG"]); }
    if (ckey === "demand" || ckey === "history") {
      seed.location = only(["dc", "customer", "store", "warehouse"]) || only(["plant"]);
      seed.product = onlyProduct(["FG"]);
    }
    const obj = defaults(schema, def.defName, seed);
    store.update((d) => { items(d, ckey).push(obj); });
    go("data", ckey, def.keyOf(obj, list.length));
  };

  return (
    <div>
      <StageHeader n="MD" title={def.label} kicker={def.blurb} />
      <div className="content">
      {upload && <div style={{ marginBottom: 14 }}><ImportPanel ds={ds} ckey={ckey} onClose={() => setUpload(false)}
        kinds={ckey === "production_sources" ? ["bom", "routing", "records"] : undefined} /></div>}
      <div className="split">
        <Panel flush title={<div className="row" style={{ flex: 1 }}>
          <input className="input" placeholder={`Search ${def.label.toLowerCase()}…`} value={q}
            onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 280, minWidth: 140 }} aria-label="Search" />
          <span className="faint small nowrap">{rows.length === list.length ? list.length : `${rows.length} of ${list.length}`}</span>
        </div>} actions={<>
          <button className="btn" onClick={() => setUpload(!upload)} aria-expanded={upload}>Upload CSV / Excel</button>
          <button className="btn primary" onClick={add} disabled={!schema}>+ New {def.singular}</button></>}>
          <div className="table-wrap" style={{ maxHeight: "calc(100vh - 230px)" }}>
            <table className="t">
              <thead><tr>{def.columns.map((c) => <th key={c.label} className={c.num ? "num" : ""}>{c.label}</th>)}<th /></tr></thead>
              <tbody>
                {shown.map(({ o, i, k }) => {
                  const iss = issueCount(o, i);
                  const errs = iss.filter((x) => x.severity === "error").length;
                  return (
                    <tr key={`${k}-${i}`} className={`clickable ${k === selected ? "selected" : ""}`}
                      onClick={() => go("data", ckey, k)}>
                      {def.columns.map((c) => <td key={c.label} className={c.num ? "num" : ""}>{c.get(o, ds) ?? ""}</td>)}
                      <td>{errs > 0 ? <Badge sev="error">{errs}</Badge> : iss.length > 0 ? <Badge sev="warning">{iss.length}</Badge> : null}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {rows.length > shown.length && <div className="faint small" style={{ padding: 10 }}>Showing the first 500 — refine the search.</div>}
            {!list.length && <Empty title={`No ${def.label.toLowerCase()} yet`}><p>Create the first {def.singular}, or upload them from a spreadsheet.</p>
              <button className="btn" onClick={() => setUpload(true)}>Upload CSV / Excel</button></Empty>}
          </div>
        </Panel>
        <div className="editor">
          {sel ? (
            <Editor key={`${ckey}-${selIndex}`} ds={ds} ckey={ckey} index={selIndex} obj={sel} errors={errFor(selIndex)}
              issues={issuesFor(issues, def.issueType, def.keyOf(sel, selIndex))} />
          ) : (
            <Panel><div className="faint">Select a {def.singular} to edit, or create a new one.</div></Panel>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}

function Editor({ ds, ckey, index, obj, errors, issues }: {
  ds: Dataset; ckey: CollectionKey; index: number; obj: Obj; errors: FieldErrors; issues: Issue[];
}) {
  const def = byKey[ckey];
  const k = def.keyOf(obj, index);
  const refKind = ckey === "locations" ? "location" : ckey === "products" ? "product" : ckey === "resources" ? "resource"
    : ckey === "calendars" ? "calendar" : null;
  const used = refKind ? whereUsed(ds, refKind, String(obj.id)) : [];

  const onChange = (next: Obj) => {
    store.update((d) => { items(d, ckey)[index] = next; });
    const nk = def.keyOf(next, index);
    if (nk !== k) go("data", ckey, nk);
  };
  const remove = () => {
    if (used.length && !window.confirm(`${String(obj.id)} is used by ${used.length} object(s):\n${used.join("\n")}\n\nDelete anyway?`)) return;
    store.update((d) => { items(d, ckey).splice(index, 1); });
    go("data", ckey);
  };
  const duplicate = () => {
    const copy = structuredClone(obj);
    if ("id" in copy) {
      let n = 2;
      while (items(ds, ckey).some((o) => o.id === `${obj.id}-${n}`)) n++;
      copy.id = `${obj.id}-${n}`;
    }
    store.update((d) => { items(d, ckey).splice(index + 1, 0, copy); });
    go("data", ckey, def.keyOf(copy, index + 1));
  };

  return (
    <Panel title={<div className="context-bar"><a href={href("data", ckey)}>{def.label}</a><span>›</span><b>{k}</b></div>}
      actions={<>
        <button className="btn sm" onClick={duplicate}>Duplicate</button>
        <button className="btn sm danger" onClick={remove}>Delete</button>
      </>}>
      {issues.length > 0 && (
        <div className="stack" style={{ gap: 6, marginBottom: 10 }}>
          {issues.map((i, n) => (
            <div key={n} className={`banner ${i.severity === "error" ? "error" : "warning"}`} style={{ margin: 0 }}>
              <Badge sev={i.severity === "error" ? "error" : "warning"}>{checkTitle(i.code)}</Badge>
              <div><div>{humanize(i.message)}</div>{i.hint && <div className="small">{i.hint}</div>}</div>
            </div>
          ))}
        </div>
      )}
      <SchemaForm defName={def.defName} value={obj} onChange={onChange} errors={errors} />
      {refKind && (
        <div className="fieldset">
          <div className="legend">Where used</div>
          {used.length ? <ul className="small" style={{ margin: "4px 0", paddingLeft: 18 }}>{used.map((u) => <li key={u}>{u}</li>)}</ul>
            : <div className="faint small">Not referenced anywhere yet.</div>}
        </div>
      )}
    </Panel>
  );
}

function SettingsEditor() {
  const ds = useStore((s) => s.dataset)!;
  const schemaErrors = useStore((s) => s.schemaErrors);
  const errors: FieldErrors = {};
  for (const e of schemaErrors) {
    const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
    if (loc[0] === "settings") errors[loc.slice(1).join(".")] = e.msg;
  }
  const rate = (ds.settings.wacc ?? 0.12) + (ds.settings.holding_spread ?? 0.08);
  return (
    <div>
      <StageHeader n="MD" title="Settings" kicker={<>The world every engine runs in: currency and exchange rates, the planning start and
        horizon, bucket size, and the cost of money. Carrying rate = WACC + holding spread = <b>{(rate * 100).toFixed(1)}% per year</b>.</>} />
      <div className="content" style={{ maxWidth: 800 }}>
        <Panel title="Planning settings">
          <SchemaForm defName="Settings" value={ds.settings as unknown as Obj} errors={errors}
            onChange={(next) => store.update((d) => { d.settings = next as unknown as Dataset["settings"]; })} />
        </Panel>
      </div>
    </div>
  );
}

export const DATA_GROUPS = ["Network", "Make & buy", "Planning data", "Demand inputs", "Execution"] as const;
export { COLLECTIONS };
