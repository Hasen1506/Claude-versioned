// Upload a table from CSV or Excel (or paste it), see exactly which rows will be added, updated or skipped and why,
// then apply. Also: download a template, or the table as it is.
import { useMemo, useState } from "react";
import type { Dataset } from "../api/types";
import { applyRows, columnsFor, exportRows, readRows, templateRows, type ImportKind } from "../lib/importer";
import { download, parseDelimited, readFile, toCsv, type Grid } from "../lib/tabular";
import { byKey, type CollectionKey } from "../model/collections";
import { useSchema } from "../schema/SchemaForm";
import { store } from "../state/store";
import { Badge, Panel } from "./ui";

const KIND_LABEL: Record<ImportKind, string> = {
  records: "Production sources, one row each", bom: "Bill of material lines (plant, product, component, quantity)",
  routing: "Routing steps (plant, product, step, machine, hours)",
};

export function ImportPanel({ ds, ckey, onClose, kinds }: { ds: Dataset; ckey: CollectionKey; onClose: () => void; kinds?: ImportKind[] }) {
  const schema = useSchema();
  const def = byKey[ckey];
  const [kind, setKind] = useState<ImportKind>(kinds?.[0] ?? "records");
  const [grid, setGrid] = useState<Grid | null>(null);
  const [paste, setPaste] = useState("");
  const [file, setFile] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [dayFirst, setDayFirst] = useState(true);
  const [replace, setReplace] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const cols = useMemo(() => (schema ? columnsFor(schema, ckey, kind) : []), [schema, ckey, kind]);
  const res = useMemo(() => (grid && cols.length ? readRows(grid, cols, ds, ckey, kind, { dayFirst }) : null), [grid, cols, ds, ckey, kind, dayFirst]);
  if (!schema) return null;

  const base = kind === "records" ? def.label.toLowerCase().replace(/\s+/g, "-") : kind;
  const load = async (f: File | undefined) => {
    if (!f) return;
    setErr(null); setDone(null);
    try { setGrid(await readFile(f)); setFile(f.name); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const good = res?.rows.filter((r) => r.record) ?? [];
  const adds = good.filter((r) => r.action === "add").length, ups = good.filter((r) => r.action === "update").length;
  const bad = (res?.rows.length ?? 0) - good.length;
  const apply = () => {
    if (!res) return;
    store.update((d) => applyRows(d, ckey, kind, res.rows, replace));
    setDone(`${good.length} row${good.length === 1 ? "" : "s"} imported${bad ? `; ${bad} skipped` : ""}. Undo (Ctrl+Z) takes the whole import back.`);
    setGrid(null); setPaste(""); setFile("");
  };
  const dates = cols.some((c) => c.kind === "date");
  const name = (k: "product" | "location", id: string) =>
    ((k === "product" ? ds.products : ds.locations) ?? []).find((x) => x.id === id)?.name || id;
  // products the file names that don't exist yet: offer to add them (as parts when they appear only as components)
  const missingProducts = new Map<string, "FG" | "RM">();
  if (res && grid) {
    res.mapped.forEach((c, i) => {
      if (c?.ref !== "product") return;
      for (const [n, r] of res.rows.entries()) {
        const v = (grid[n + 1]?.[i] ?? "").trim();
        if (v && r.problems.some((p) => p.includes(`no product “${v}”`)))
          missingProducts.set(v, c.path === "component" || missingProducts.get(v) === "RM" ? "RM" : "FG");
      }
    });
  }
  const addMissing = () => store.update((d) => {
    const list = ((d as unknown as Record<string, Record<string, unknown>[]>).products ??= []);
    for (const [nm, type] of missingProducts) {
      let id = nm.toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "PRODUCT", n = 2;
      while (list.some((p) => p.id === id)) id = `${id.replace(/-\d+$/, "")}-${n++}`;
      list.push({ id, name: nm, type });
    }
  });

  return (
    <Panel className="import" title={<h3>Upload {kind === "records" ? def.label.toLowerCase() : kind === "bom" ? "bills of material" : "routings"}</h3>}
      actions={<button className="btn sm ghost" onClick={onClose}>Close</button>}>
      <div className="stack">
        {kinds && kinds.length > 1 && <div className="row wrap">
          <span className="small muted">The file holds</span>
          <select className="select" style={{ width: "auto" }} value={kind} onChange={(e) => { setKind(e.target.value as ImportKind); setGrid(null); }} aria-label="The file holds">
            {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select>
        </div>}
        <div className="import-help">
          <p className="small">One row per {kind === "records" ? def.singular : kind === "bom" ? "component of a product" : "step"}, first row the column names. CSV, Excel (.xlsx) or text pasted from a spreadsheet.
            Columns can be in any order; names like “Qty”, “Quantity” or “Item” are recognised, and places and products can be given by id or name.</p>
          <details><summary className="small">The columns</summary>
            <table className="t small"><tbody>{cols.map((c) => <tr key={c.path}><td className="mono">{c.header}</td><td>{c.label}{c.required && <b> (required)</b>}</td>
              <td className="faint">{c.enum ? `one of ${c.enum.join(", ")}` : c.kind === "date" ? "a date, e.g. 2026-10-05" : c.percent ? "a percentage, e.g. 5" : c.kind === "list" ? "several, separated by ;" : c.ref ? `a ${c.ref} id or name` : c.help ?? ""}</td></tr>)}</tbody></table>
          </details>
          <div className="row wrap">
            <button className="btn sm" onClick={() => download(`${base}-template.csv`, toCsv(templateRows(ds, ckey, cols, kind)))}>Download a template</button>
            <button className="btn sm ghost" onClick={() => download(`${base}.csv`, toCsv(exportRows(ds, ckey, cols, kind)))}>Download the current table</button>
          </div>
        </div>
        <div className="row wrap">
          <label className="btn primary">Choose a file…<input type="file" accept=".csv,.tsv,.txt,.xlsx" hidden onChange={(e) => load(e.target.files?.[0])} aria-label="Choose a file" /></label>
          {file && <span className="small">{file}</span>}
        </div>
        <details>
          <summary className="small">…or paste from a spreadsheet</summary>
          <textarea className="input" rows={6} value={paste} onChange={(e) => setPaste(e.target.value)} aria-label="Paste rows"
            placeholder={cols.slice(0, 5).map((c) => c.header).join("\t")} style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 12 }} />
          <button className="btn sm" disabled={!paste.trim()} onClick={() => { setGrid(parseDelimited(paste)); setFile("pasted rows"); setDone(null); }}>Read the pasted rows</button>
        </details>
        {err && <div className="banner error" role="alert">{err}</div>}
        {done && <div className="banner ok" role="status">{done}</div>}
        {res && <>
          {res.missing.length > 0 && <div className="banner error" role="alert">The file has no {res.missing.map((c) => `“${c.header}”`).join(", ")} column{res.missing.length > 1 ? "s" : ""}, which {res.missing.length > 1 ? "are" : "is"} needed.
            Rename a column to match, or start from the template.</div>}
          <div className="small">Columns read: {grid![0].map((h, i) => <span key={i} className={`chip ${res.mapped[i] ? "" : "faint"}`} title={res.mapped[i] ? res.mapped[i]!.label : "not used"}>
            {h}{res.mapped[i] ? ` → ${res.mapped[i]!.label}` : " (not used)"}</span>)}</div>
          {dates && <label className="row small"><input type="checkbox" checked={dayFirst} onChange={(e) => setDayFirst(e.target.checked)} />
            Dates like 05/10/2026 are day/month/year</label>}
          {missingProducts.size > 0 && <div className="banner warning">
            {missingProducts.size === 1 ? "One product in the file doesn't exist yet" : `${missingProducts.size} products in the file don't exist yet`}: {[...missingProducts.keys()].slice(0, 6).join(", ")}{missingProducts.size > 6 ? "…" : ""}.
            <button className="btn sm" onClick={addMissing}>Add {missingProducts.size === 1 ? "it" : "them"} as {[...missingProducts.values()].every((t) => t === "RM") ? "raw materials" : "products"}</button></div>}
          <div className="row wrap">
            <Badge sev="ok">{kind === "records" ? `${adds} new` : `${good.length} ${kind === "bom" ? "parts" : "steps"}`}</Badge>{ups > 0 && <Badge sev="info">{ups} update existing</Badge>}{bad > 0 && <Badge sev="error">{bad} can't be read</Badge>}
          </div>
          <div className="table-wrap" style={{ maxHeight: 320 }}>
            <table className="t small">
              <thead><tr><th>Row</th><th>What happens</th>{grid![0].map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
              <tbody>{res.rows.slice(0, 300).map((r, n) => <tr key={n} className={r.problems.length ? "bad" : ""}>
                <td className="num">{r.line}</td>
                <td>{r.problems.length ? <span className="err-text">{r.problems.join("; ")}</span>
                  : kind !== "records" ? `${kind === "bom" ? "a part" : "a step"} of ${name("product", r.record!.product as string)} at ${name("location", r.record!.location as string)}`
                  : r.action === "update" ? "updates " + r.key : "added"}</td>
                {grid![n + 1]?.map((c, i) => <td key={i}>{c}</td>)}
              </tr>)}</tbody>
            </table>
          </div>
          {res.rows.length > 300 && <p className="faint small">Showing the first 300 of {res.rows.length} rows.</p>}
          {kind === "records" && <label className="row small"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            Replace every {def.singular} now in the table ({((ds as unknown as Record<string, unknown[]>)[ckey] ?? []).length}) with the file's rows</label>}
          {kind !== "records" && <p className="small muted">Each product's {kind === "bom" ? "components" : "steps"} in the file replace the ones it has now; a product made nowhere yet gets a new production source.</p>}
          <div className="row">
            <button className="btn primary" disabled={!good.length || res.missing.length > 0} onClick={apply}>Import {good.length} row{good.length === 1 ? "" : "s"}</button>
            <button className="btn ghost" onClick={() => { setGrid(null); setFile(""); }}>Start again</button>
          </div>
        </>}
      </div>
    </Panel>
  );
}
