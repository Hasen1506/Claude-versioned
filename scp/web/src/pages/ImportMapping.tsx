// The connector framework's screens (ENTERPRISE_PLAN 3.1): which column or field of the other system fills each
// field here, how a web API gives its pages, and a dry run that shows what would become of each line before anything
// is saved.
import type { FieldMap, Mapping, MessageRow, Paging, Tried } from "../api/types";
import { Badge, type Severity } from "../components/ui";

/** One field of the mapping as typed: codes and numbers stay text until the import is saved or tried. */
export type MapRow = { target: string; source: string; codes: string; factor: string; date_format: string; value: string };

const FIRST: Record<string, string[]> = {
  orders: ["number", "customer", "product", "qty", "date"],
  stock: ["location", "product", "qty"],
  postings: ["ref", "action", "number", "qty", "date"],
};

export const FIELD_NAMES: Record<string, string> = {
  number: "order number", customer: "customer", order_date: "ordered on", customer_ref: "customer's reference",
  payment_terms: "payment terms", product: "product", qty: "quantity", date: "wanted on (or posted on)", price: "price",
  cancelled: "cancelled", note: "note", location: "place", batch: "batch", expires_on: "expires on", stock_type: "stock type",
  quality: "in quality inspection", blocked: "blocked", ref: "document number", action: "movement", final: "last one",
  supplier_batch: "supplier's batch", to_type: "to stock type",
};

const DATES = new Set(["date", "order_date", "expires_on"]);
const NUMBERS = new Set(["qty", "price", "quality", "blocked"]);

export function startRows(kind: string, fields: string[]): MapRow[] {
  return (FIRST[kind] ?? fields.slice(0, 3)).map((target) => blankRow(target));
}

export const blankRow = (target: string): MapRow => ({ target, source: "", codes: "", factor: "", date_format: "", value: "" });

/** "WH-01=P; Main Godown=P; *=?" ↔ { "WH-01": "P", … } */
function codesOf(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of text.split(/[;\n]/)) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

export function fromMapping(m: Mapping | null | undefined): { items: string; each: string; rows: MapRow[] } {
  const rows = Object.entries(m?.fields ?? {}).map(([target, f]) => ({
    target, source: f.source ?? "", codes: Object.entries(f.values ?? {}).map(([k, v]) => `${k}=${v}`).join("; "),
    factor: f.factor == null ? "" : String(f.factor), date_format: f.date_format ?? "", value: f.value == null ? "" : String(f.value),
  }));
  return { items: m?.items ?? "", each: m?.each ?? "", rows };
}

export function toMapping(items: string, each: string, rows: MapRow[]): Mapping {
  const fields: Record<string, FieldMap> = {};
  for (const r of rows) {
    if (!r.source.trim() && !r.value.trim()) continue;
    const f: FieldMap = { source: r.source.trim(), date_format: r.date_format.trim() };
    const codes = codesOf(r.codes);
    if (Object.keys(codes).length) f.values = codes;
    if (r.factor.trim() && Number.isFinite(Number(r.factor))) f.factor = Number(r.factor);
    if (r.value.trim()) f.value = r.value.trim();
    fields[r.target] = f;
  }
  return { items: items.trim(), each: each.trim(), fields };
}

export function MappingEditor({ kind, fields, json, items, each, rows, columns, onChange }: {
  kind: string; fields: string[]; json: boolean; items: string; each: string; rows: MapRow[]; columns: string[];
  onChange: (p: { items?: string; each?: string; rows?: MapRow[] }) => void;
}) {
  const set = (i: number, p: Partial<MapRow>) => onChange({ rows: rows.map((r, j) => (j === i ? { ...r, ...p } : r)) });
  const left = fields.filter((f) => !rows.some((r) => r.target === f));
  const list = `cols-${kind.replace(/\W/g, "")}`;
  const any = kind.startsWith("records:");   // master data: any field may be a number or a date
  return <div className="stack" style={{ gap: 8 }} role="group" aria-label="Field mapping">
    {json && <div className="qrow">
      <label className="qf"><span className="qf-l">Records at</span>
        <input className="input mono" value={items} onChange={(ev) => onChange({ items: ev.target.value })} placeholder="data.items" aria-label="Records at" />
        <span className="qf-h">the path to the list in the answer; empty: the answer itself</span></label>
      <label className="qf"><span className="qf-l">One row per element of <span className="faint">(optional)</span></span>
        <input className="input mono" value={each} onChange={(ev) => onChange({ each: ev.target.value })} placeholder="line_items" aria-label="One row per element of" />
        <span className="qf-h">a list inside each record, such as an order's lines: read its fields as <code>line.sku</code></span></label>
    </div>}
    <datalist id={list}>{columns.map((c) => <option key={c} value={c} />)}</datalist>
    <div className="table-wrap"><table className="t small">
      <thead><tr><th>Field here</th><th>From (column or path)</th><th>Codes there = here</th><th>× by</th><th>Dates written as</th><th>If empty</th><th /></tr></thead>
      <tbody>{rows.map((r, i) => <tr key={r.target}>
        <td className="nowrap"><b>{FIELD_NAMES[r.target] ?? r.target.replace(/_/g, " ")}</b><div className="faint mono">{r.target}</div></td>
        <td><input className="input mono" list={list} value={r.source} onChange={(ev) => set(i, { source: ev.target.value })} aria-label={`${r.target} from`} placeholder={json ? "customer.code" : "Item Code"} /></td>
        <td><input className="input mono" value={r.codes} onChange={(ev) => set(i, { codes: ev.target.value })} aria-label={`${r.target} codes`} placeholder="WH-01=P; *=?" /></td>
        <td>{(any || NUMBERS.has(r.target)) && <input className="input num" inputMode="decimal" value={r.factor} onChange={(ev) => set(i, { factor: ev.target.value })} aria-label={`${r.target} times`} style={{ width: 70 }} />}</td>
        <td>{(any || DATES.has(r.target)) && <input className="input mono" value={r.date_format} onChange={(ev) => set(i, { date_format: ev.target.value })} aria-label={`${r.target} date format`} placeholder="%d-%b-%Y" style={{ width: 110 }} />}</td>
        <td><input className="input" value={r.value} onChange={(ev) => set(i, { value: ev.target.value })} aria-label={`${r.target} if empty`} style={{ width: 90 }} /></td>
        <td><button type="button" className="btn sm ghost" aria-label={`Leave out ${r.target}`} onClick={() => onChange({ rows: rows.filter((_, j) => j !== i) })}>×</button></td>
      </tr>)}</tbody>
    </table></div>
    {left.length > 0 && <label className="row small">Add a field
      <select className="select" value="" aria-label="Add a field" style={{ width: "auto" }} onChange={(ev) => ev.target.value && onChange({ rows: [...rows, blankRow(ev.target.value)] })}>
        <option value="">choose…</option>{left.map((f) => <option key={f} value={f}>{FIELD_NAMES[f] ?? f.replace(/_/g, " ")}</option>)}</select></label>}
    <span className="faint small">Codes are translated one by one (<code>*</code> for any other); dates use <code>%d</code> day, <code>%m</code> or <code>%b</code> month,
      <code>%Y</code> year. A field left out is not changed.</span>
  </div>;
}

export function PagingFields({ value, onChange }: { value: Paging; onChange: (p: Paging) => void }) {
  const set = (p: Partial<Paging>) => onChange({ ...value, ...p });
  return <div className="qrow" role="group" aria-label="Pages">
    <label className="qf"><span className="qf-l">Pages</span>
      <select className="select" value={value.mode ?? "next"} onChange={(ev) => set({ mode: ev.target.value as Paging["mode"] })} aria-label="Pages come">
        <option value="next">each answer names the next page</option><option value="page">numbered pages</option></select></label>
    <label className="qf"><span className="qf-l">{value.mode === "page" ? "More pages flag" : "Next page at"}</span>
      <input className="input mono" value={value.next ?? ""} onChange={(ev) => set({ next: ev.target.value })} aria-label="Next page path"
        placeholder={value.mode === "page" ? "page_context.has_more_page" : "links.next"} />
      <span className="qf-h">{value.mode === "page" ? "empty: until a page has no records" : "the path in the answer to the next page's address"}</span></label>
    {value.mode === "page" && <label className="qf"><span className="qf-l">Page parameter</span>
      <input className="input mono" value={value.param ?? "page"} onChange={(ev) => set({ param: ev.target.value })} aria-label="Page parameter" /></label>}
    <label className="qf"><span className="qf-l">At most</span>
      <input className="input num" type="number" min={1} max={500} value={value.max_pages ?? 50} onChange={(ev) => set({ max_pages: Number(ev.target.value) || 50 })} aria-label="Most pages" style={{ width: 90 }} />
      <span className="qf-h">pages; more is a failure, never half an answer</span></label>
  </div>;
}

const ITEM: Record<string, Severity | undefined> = { applied: "ok", refused: "error", unchanged: undefined, duplicate: undefined };
const ITEM_WORD: Record<string, string> = { applied: "would be taken", refused: "refused", unchanged: "as here already", duplicate: "sent before" };

function cell(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "object") return Array.isArray(v) ? v.map((x) => (typeof x === "object" ? Object.values(x as object).join(" ") : String(x))).join(" · ") : JSON.stringify(v);
  return String(v);
}

/** A dry run: the columns found, the first rows as the fields here, and what would become of each line. */
export function TryResult({ t, onColumn }: { t: Tried; onColumn?: (c: string) => void }) {
  const keys = [...new Set((t.rows ?? []).flatMap((r) => Object.keys(r)))];
  return <div className="stack" style={{ gap: 8 }} aria-label="Dry run">
    {(t.columns ?? []).length > 0 && <div className="small"><b>Found in what was read:</b>{" "}
      {t.columns!.map((c) => onColumn ? <button key={c} type="button" className="btn sm ghost mono" onClick={() => onColumn(c)} title="Use in the mapping">{c}</button>
        : <code key={c} style={{ marginRight: 6 }}>{c}</code>)}</div>}
    {keys.length > 0 && <div className="table-wrap"><table className="t small" aria-label="First rows as the fields here">
      <thead><tr>{keys.map((k) => <th key={k}>{FIELD_NAMES[k] ?? k}</th>)}</tr></thead>
      <tbody>{t.rows!.map((r, i) => <tr key={i}>{keys.map((k) => <td key={k} className="mono">{cell(r[k])}</td>)}</tr>)}</tbody>
    </table></div>}
    {t.messages.map((m: MessageRow, i) => <div key={i}>
      <div className={`banner ${m.status === "failed" || m.status === "refused" ? "error" : m.status === "partly" ? "warning" : "ok"}`} role="status" style={{ margin: 0 }}>{m.summary}</div>
      {m.items.length > 0 && <table className="t small"><tbody>{m.items.map((it, j) => <tr key={j}>
        <td className="nowrap"><b>{it.ref || "—"}</b></td><td><Badge sev={ITEM[it.status]}>{ITEM_WORD[it.status] ?? it.status}</Badge></td><td>{it.message}</td></tr>)}</tbody></table>}
    </div>)}
  </div>;
}
