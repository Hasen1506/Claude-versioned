// Turn spreadsheet rows into dataset records, using the engine's JSON schema for the columns, types and units, so every
// table can be uploaded the same way. Headers are matched loosely ("Qty", "quantity", "QTY" all work; a place or product
// can be given by id or by name). Nothing is written until the planner has seen the preview.
import type { JsonSchema, JsonSchemaNode } from "../api/client";
import type { Dataset } from "../api/types";
import { byKey, items, type CollectionKey } from "../model/collections";
import { humanize, unwrap } from "../schema/SchemaForm";
import type { Grid } from "./tabular";

type Obj = Record<string, unknown>;

export type ColKind = "string" | "number" | "integer" | "boolean" | "date" | "enum" | "list";

export interface Col {
  path: string;          // "qty", "lot_sizing.policy", "modes.0.transit_days"
  header: string;        // template header, e.g. "transit_days" or "scrap %"
  label: string;         // for people: "Transit days"
  kind: ColKind;
  required: boolean;
  enum?: string[];
  ref?: string;          // location | product | resource | calendar
  percent?: boolean;     // a 0–1 fraction written as a percentage
  help?: string;
}

/** What an upload contains. Most tables are one row per record; production sources also take BOM and routing lines. */
export type ImportKind = "records" | "bom" | "routing";

const SKIP = new Set(["from_journal"]);

/** The columns of a collection's records, flattened one level into objects (lot sizing, safety stock) and, for lanes,
 *  into the first transport mode. Lists of objects (components, operations) have their own import kinds. */
export function columnsFor(schema: JsonSchema, ckey: CollectionKey, kind: ImportKind = "records"): Col[] {
  if (kind === "bom") return BOM_COLS;
  if (kind === "routing") return ROUTING_COLS;
  const def = schema.$defs[byKey[ckey].defName];
  const out: Col[] = [];
  const walk = (d: JsonSchemaNode, prefix: string, req: string[], depth: number) => {
    for (const [k, raw] of Object.entries(d.properties ?? {})) {
      if (SKIP.has(k)) continue;
      const { node } = unwrap(schema, raw);
      const path = prefix + k;
      const required = req.includes(k) && raw.default === undefined;
      if (node.type === "object" && node.properties && depth === 0) {
        walk(node, `${path}.`, node.required ?? [], 1);
        continue;
      }
      if (ckey === "lanes" && k === "modes") {
        const modeDef = schema.$defs.LaneMode;
        walk(modeDef, "modes.0.", modeDef.required ?? [], 1);
        continue;
      }
      const item = node.type === "array" && node.items ? unwrap(schema, node.items).node : null;
      let ck: ColKind;
      if (node.enum) ck = "enum";
      else if (node.format === "date") ck = "date";
      else if (node.type === "number") ck = "number";
      else if (node.type === "integer") ck = "integer";
      else if (node.type === "boolean") ck = "boolean";
      else if (node.type === "string") ck = "string";
      else if (item && (item.type === "string" || item.type === "integer" || item.format === "date")) ck = "list";
      else continue; // nested lists of objects, maps
      const percent = node["x-unit"] === "fraction";
      out.push({
        path, kind: ck, required, enum: node.enum, ref: node["x-ref"] ?? item?.["x-ref"], percent, help: raw.description,
        header: path.replace(/^modes\.0\./, "") + (percent ? " %" : ""),
        label: humanize(path.split(".").pop()!) + (percent ? " (%)" : ""),
      });
    }
  };
  walk(def, "", def.required ?? [], 0);
  // required first, keeping the schema's order otherwise
  return [...out.filter((c) => c.required), ...out.filter((c) => !c.required)];
}

const BOM_COLS: Col[] = [
  { path: "location", header: "plant", label: "Plant", kind: "string", required: true, ref: "location" },
  { path: "product", header: "product", label: "Product made", kind: "string", required: true, ref: "product" },
  { path: "component", header: "component", label: "Component", kind: "string", required: true, ref: "product" },
  { path: "qty", header: "qty", label: "Quantity per unit made", kind: "number", required: true },
  { path: "scrap", header: "scrap %", label: "Component scrap (%)", kind: "number", required: false, percent: true },
  { path: "source", header: "source_id", label: "Production source id (optional)", kind: "string", required: false },
];
const ROUTING_COLS: Col[] = [
  { path: "location", header: "plant", label: "Plant", kind: "string", required: true, ref: "location" },
  { path: "product", header: "product", label: "Product made", kind: "string", required: true, ref: "product" },
  { path: "seq", header: "step", label: "Step number", kind: "integer", required: true },
  { path: "resource", header: "resource", label: "Machine, line or crew", kind: "string", required: true, ref: "resource" },
  { path: "setup_hours", header: "setup_hours", label: "Setup hours per run", kind: "number", required: false },
  { path: "run_hours_per_unit", header: "run_hours_per_unit", label: "Run hours per unit", kind: "number", required: false },
  { path: "run_minutes_per_unit", header: "run_minutes_per_unit", label: "Run minutes per unit (instead of hours)", kind: "number", required: false },
  { path: "name", header: "step_name", label: "Step name", kind: "string", required: false },
  { path: "source", header: "source_id", label: "Production source id (optional)", kind: "string", required: false },
];

// ---- header matching -----------------------------------------------------------------------------------------------
const norm = (s: string) => s.toLowerCase().replace(/%/g, "").replace(/[^a-z0-9]/g, "");
const SYNONYMS: Record<string, string[]> = {
  qty: ["quantity", "units", "volume", "demand", "amount"], location: ["place", "site", "plant", "warehouse", "dc", "locationid"],
  product: ["item", "material", "sku", "productid", "article"], date: ["day", "week", "weekof", "period", "deliverydate", "duedate"],
  lead_time_days: ["leadtime", "lt", "leadtimedays"], supplier: ["vendor", "supplierid", "vendorid"], price: ["unitprice", "cost"],
  origin: ["from"], destination: ["to"], on_hand: ["stock", "onhand", "inventory", "stockonhand"], id: ["code", "number", "no"],
  name: ["description", "desc"], type: ["kind", "category"], component: ["part", "componentid", "material"],
  transit_days: ["transit", "transittime", "days"], resource: ["workcentre", "workcenter", "machine", "line"],
};

/** For each column of the grid's header, the matching import column (or none). */
export function matchHeaders(header: string[], cols: Col[]): (Col | null)[] {
  const used = new Set<string>();
  return header.map((h) => {
    const n = norm(h);
    if (!n) return null;
    const find = (pred: (c: Col) => boolean) => cols.find((c) => !used.has(c.path) && pred(c));
    const c = find((c) => norm(c.header) === n || norm(c.path) === n)
      ?? find((c) => norm(c.label) === n)
      ?? find((c) => norm(c.path.split(".").pop()!) === n)
      ?? find((c) => (SYNONYMS[c.path.split(".").pop()!] ?? []).includes(n));
    if (c) used.add(c.path);
    return c ?? null;
  });
}

// ---- values --------------------------------------------------------------------------------------------------------
export interface Options { dayFirst: boolean }

export function parseDate(v: string, dayFirst: boolean): string | null {
  const s = v.trim();
  let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$/);
  if (m) return iso(+m[1], +m[2], +m[3]);
  m = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/);
  if (m) {
    const y = m[3].length === 2 ? 2000 + +m[3] : +m[3];
    return dayFirst ? iso(y, +m[2], +m[1]) : iso(y, +m[1], +m[2]);
  }
  m = s.match(/^(\d{1,2})[ -]([A-Za-z]{3,})[ -,]*(\d{4})$/);
  if (m) {
    const mon = MONTHS.indexOf(m[2].slice(0, 3).toLowerCase()) + 1;
    if (mon) return iso(+m[3], mon, +m[1]);
  }
  if (/^\d{5}(\.\d+)?$/.test(s)) {   // an Excel day number
    const d = new Date(Math.round((Number(s) - 25569) * 86400000));
    return d.toISOString().slice(0, 10);
  }
  return null;
}
const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
function iso(y: number, m: number, d: number): string | null {
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
  return dt.toISOString().slice(0, 10);
}

function parseNumber(v: string): number | null {
  const s = v.replace(/[\s,](?=\d{3}\b)/g, "").replace(/%$/, "").replace(/^[^\d\-.]+/, "");
  if (s === "" || isNaN(Number(s))) return null;
  return Number(s);
}

const ENUM_WORDS: Record<string, string> = {
  distributioncentre: "dc", distributioncenter: "dc", finishedgood: "FG", finished: "FG", semifinished: "SFG", subassembly: "SFG",
  rawmaterial: "RM", raw: "RM", packaging: "PKG", salesorder: "sales_order", order: "sales_order", so: "sales_order", fc: "forecast",
  lotforlot: "L4L", exact: "L4L", fixedlot: "FIXED", daysofsupply: "days_of_supply", daysofcover: "days_of_supply",
  truck: "truck_ftl", fullload: "truck_ftl", partload: "truck_ltl", ftl: "truck_ftl", ltl: "truck_ltl", ship: "sea", ocean: "sea",
  vendor: "supplier", maketostock: "MTS", maketoorder: "MTO", assembletoorder: "ATO",
};

// ---- rows → records ------------------------------------------------------------------------------------------------
export interface RowResult {
  line: number;          // spreadsheet row number (header = 1)
  record: Obj | null;    // null when the row has a problem
  key: string | null;    // the record's key when it is keyed (for "updates")
  action: "add" | "update" | "skip";
  problems: string[];
}

function lookup(ds: Dataset, kind: string, v: string, extra: Obj[]): string | null {
  const list = ((kind === "location" ? ds.locations : kind === "product" ? ds.products : kind === "resource" ? ds.resources
    : kind === "calendar" ? ds.calendars : []) ?? []) as { id: string; name?: string }[];
  const all = [...list, ...(extra as { id: string; name?: string }[])];
  const lv = v.toLowerCase();
  return all.find((x) => x.id === v)?.id ?? all.find((x) => x.id.toLowerCase() === lv)?.id
    ?? all.find((x) => (x.name ?? "").toLowerCase() === lv)?.id ?? null;
}

function setPath(o: Obj, path: string, v: unknown) {
  const parts = path.split(".");
  let cur: Obj | unknown[] = o;
  for (let i = 0; i < parts.length - 1; i++) {
    const k = parts[i], nextIsIndex = /^\d+$/.test(parts[i + 1]);
    const c = cur as Record<string, unknown>;
    if (c[k] === undefined) c[k] = nextIsIndex ? [] : {};
    cur = c[k] as Obj;
  }
  (cur as Record<string, unknown>)[parts[parts.length - 1]] = v;
}

/** Parse the grid (first row = headers) into records for `ckey`, each with what will happen to it. */
export function readRows(grid: Grid, cols: Col[], ds: Dataset, ckey: CollectionKey, kind: ImportKind, opt: Options):
  { mapped: (Col | null)[]; rows: RowResult[]; missing: Col[] } {
  const [header = [], ...body] = grid;
  const mapped = matchHeaders(header, cols);
  const missing = cols.filter((c) => c.required && !mapped.includes(c));
  const def = byKey[ckey];
  const existing = new Map(items(ds, ckey).map((o, i) => [def.keyOf(o, i), o]));
  // places and products uploaded in this same file can be referred to by later rows
  const self = kind === "records" && (ckey === "locations" || ckey === "products" || ckey === "resources") ? [] as Obj[] : null;
  const selfKind = ckey === "locations" ? "location" : ckey === "products" ? "product" : "resource";
  const seen = new Set<string>();
  const rows: RowResult[] = body.map((cells, bi) => {
    const rec: Obj = {};
    const problems: string[] = [];
    mapped.forEach((c, i) => {
      if (!c) return;
      const raw = (cells[i] ?? "").trim();
      if (raw === "") return;
      let v: unknown = raw;
      switch (c.kind) {
        case "number": case "integer": {
          const n = parseNumber(raw);
          if (n === null) { problems.push(`${c.label}: “${raw}” is not a number`); return; }
          v = c.percent ? (raw.includes("%") || n > 1 ? n / 100 : n) : n;
          if (c.kind === "integer" && !Number.isInteger(v)) { problems.push(`${c.label}: “${raw}” must be a whole number`); return; }
          break;
        }
        case "date": {
          const d = parseDate(raw, opt.dayFirst);
          if (!d) { problems.push(`${c.label}: “${raw}” is not a date`); return; }
          v = d;
          break;
        }
        case "boolean": {
          const b = raw.toLowerCase();
          if (["yes", "y", "true", "1", "x"].includes(b)) v = true;
          else if (["no", "n", "false", "0", ""].includes(b)) v = false;
          else { problems.push(`${c.label}: “${raw}” should be yes or no`); return; }
          break;
        }
        case "enum": {
          const e = c.enum ?? [];
          const n = norm(raw);
          const hit = e.find((x) => x === raw) ?? e.find((x) => norm(x) === n) ?? (ENUM_WORDS[n] && e.includes(ENUM_WORDS[n]) ? ENUM_WORDS[n] : undefined);
          if (!hit) { problems.push(`${c.label}: “${raw}” should be one of ${e.join(", ")}`); return; }
          v = hit;
          break;
        }
        case "list": {
          const parts = raw.split(/[;|]/).map((x) => x.trim()).filter(Boolean);
          v = c.ref ? parts.map((x) => lookup(ds, c.ref!, x, self && c.ref === selfKind ? self : []) ?? x) : parts;
          break;
        }
        default:
          if (c.ref) {
            const id = lookup(ds, c.ref, raw, self && c.ref === selfKind ? self : []);
            if (!id) { problems.push(`${c.label}: there is no ${c.ref} “${raw}”${c.ref === "location" ? " (add the place first)" : c.ref === "product" ? " (add the product first)" : ""}`); return; }
            v = id;
          }
      }
      setPath(rec, c.path, v);
    });
    for (const c of cols) if (c.required && getPath(rec, c.path) === undefined && mapped.includes(c) && !problems.some((p) => p.startsWith(c.label))) problems.push(`${c.label} is empty`);
    if (kind === "routing" && rec.run_minutes_per_unit !== undefined) {
      rec.run_hours_per_unit = (rec.run_minutes_per_unit as number) / 60;
      delete rec.run_minutes_per_unit;
    }
    let key: string | null = null, action: RowResult["action"] = "add";
    if (!problems.length && kind === "records") {
      key = ["demand", "history", "overrides", "confirmations", "changeovers", "movements", "accuracy", "rolled_weeks"].includes(ckey) && !rec.id
        ? null : def.keyOf(rec, -1);
      if (key && key.startsWith("#")) key = null;
      if (key && seen.has(key)) problems.push(`the same ${def.singular} appears twice in the file`);
      if (key) seen.add(key);
      if (key && existing.has(key)) action = "update";
      if (self && rec.id) self.push(rec);
    }
    return { line: bi + 2, record: problems.length ? null : rec, key, action: problems.length ? "skip" : action, problems };
  });
  return { mapped, rows, missing };
}

/** Write the good rows into the dataset. `replace` empties the table first (records only). */
export function applyRows(d: Dataset, ckey: CollectionKey, kind: ImportKind, rows: RowResult[], replace: boolean) {
  const coll = d as unknown as Record<string, Obj[] | undefined>;
  const good = rows.filter((r) => r.record);
  if (kind === "records") {
    const def = byKey[ckey];
    if (replace) coll[ckey] = [];
    const list = (coll[ckey] ??= []);
    for (const r of good) {
      const at = r.key ? list.findIndex((o, i) => def.keyOf(o, i) === r.key) : -1;
      if (at >= 0) list[at] = deepMerge(list[at], r.record!);
      else list.push(r.record!);
    }
    return;
  }
  // BOM or routing lines: group by production source (id, or plant + product), replacing that list on each source
  const ps = (coll.production_sources ??= []);
  const groups = new Map<string, Obj[]>();
  for (const r of good) {
    const rec = r.record!;
    const k = rec.source ? `id:${rec.source}` : `${rec.location}|${rec.product}`;
    groups.set(k, [...(groups.get(k) ?? []), rec]);
  }
  for (const [k, recs] of groups) {
    const first = recs[0];
    let src = k.startsWith("id:") ? ps.find((x) => x.id === first.source)
      : ps.find((x) => x.location === first.location && x.product === first.product);
    if (!src) {
      const taken = new Set(ps.map((x) => String(x.id)));
      let id = (first.source as string) || `${first.product}-${first.location}`.toUpperCase().replace(/[^A-Z0-9_.-]+/g, "-"), n = 2;
      while (taken.has(id)) id = `${first.source || `${first.product}-${first.location}`}-${n++}`;
      src = { id, location: first.location, product: first.product, components: [], operations: [] };
      ps.push(src);
    }
    if (kind === "bom") src.components = recs.map((r) => ({ product: r.component, qty: r.qty, ...(r.scrap !== undefined ? { scrap: r.scrap } : {}) }));
    else src.operations = [...recs].sort((a, b) => (a.seq as number) - (b.seq as number)).map((r) => ({
      seq: r.seq, resource: r.resource, ...(r.name ? { name: r.name } : {}),
      setup_hours: r.setup_hours ?? 0, run_hours_per_unit: r.run_hours_per_unit ?? 0,
    }));
  }
}

function deepMerge(a: Obj, b: Obj): Obj {
  const out: Obj = { ...a };
  for (const [k, v] of Object.entries(b)) {
    out[k] = v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object" && !Array.isArray(a[k])
      ? deepMerge(a[k] as Obj, v as Obj) : Array.isArray(v) && Array.isArray(a[k]) && k === "modes"
      ? (v as Obj[]).map((m, i) => ({ ...((a[k] as Obj[])[i] ?? {}), ...m })) : v;
  }
  return out;
}

// ---- templates and export ----------------------------------------------------------------------------------------------
function getPath(o: Obj, path: string): unknown {
  return path.split(".").reduce<unknown>((cur, k) => (cur && typeof cur === "object" ? (cur as Obj)[k] : undefined), o);
}

function cell(c: Col, v: unknown): string | number {
  if (v === null || v === undefined) return "";
  if (c.percent && typeof v === "number") return +(v * 100).toFixed(6);
  if (Array.isArray(v)) return v.join(";");
  if (typeof v === "boolean") return v ? "yes" : "no";
  return v as string | number;
}

/** The table as rows (header first): the current records, or for BOM / routing their lines. */
export function exportRows(ds: Dataset, ckey: CollectionKey, cols: Col[], kind: ImportKind): (string | number)[][] {
  const head = cols.map((c) => c.header);
  if (kind === "bom") {
    return [head, ...(ds.production_sources ?? []).flatMap((p) => (p.components ?? []).map((c) =>
      [p.location, p.product, c.product, c.qty, cell(BOM_COLS[4], c.scrap), p.id]))];
  }
  if (kind === "routing") {
    return [head, ...(ds.production_sources ?? []).flatMap((p) => (p.operations ?? []).map((o) =>
      [p.location, p.product, o.seq, o.resource, o.setup_hours ?? 0, o.run_hours_per_unit ?? 0, "", o.name ?? "", p.id]))];
  }
  return [head, ...items(ds, ckey).map((o) => cols.map((c) => cell(c, getPath(o, c.path))))];
}

/** A template: the header, plus an example row made from the company's own places and products where it has them. */
export function templateRows(ds: Dataset, ckey: CollectionKey, cols: Col[], kind: ImportKind): (string | number)[][] {
  const loc = (types: string[]) => (ds.locations ?? []).find((l) => types.includes(l.type))?.id;
  const prod = (types: string[]) => (ds.products ?? []).find((p) => types.includes(p.type))?.id;
  const start = ds.settings.planning_start;
  const example = (c: Col): string | number => {
    const f = c.path.split(".").pop()!;
    if (c.ref === "location") return (f === "supplier" ? loc(["supplier"]) : f === "destination" ? loc(["dc", "warehouse", "store", "customer"]) : loc(["plant", "dc", "warehouse"])) ?? "PLANT-1";
    if (c.ref === "product") return (kind === "bom" && f === "component" ? prod(["RM", "PKG", "SFG"]) : prod(["FG"])) ?? "PRODUCT-1";
    if (c.ref === "resource") return (ds.resources ?? [])[0]?.id ?? "LINE-1";
    if (c.kind === "date") return start;
    if (c.kind === "enum") return c.enum?.[0] ?? "";
    if (c.kind === "boolean") return "no";
    if (c.kind === "number" || c.kind === "integer") return f === "qty" ? 100 : f === "seq" ? 10 : f.includes("days") ? 7 : 1;
    if (f === "id") return `${byKey[ckey].singular.split(" ").map((w) => w[0]).join("").toUpperCase()}-1`;
    return "";
  };
  return [cols.map((c) => c.header), cols.map((c) => (c.required || ["qty", "date", "kind"].includes(c.path) ? example(c) : ""))];
}
