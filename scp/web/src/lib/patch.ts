// What changed between two saves of a company, as the server takes it (scp/companies/patch.py): per list of records,
// the records added or changed and the keys of those removed; a list whose records cannot be told apart (two with one
// key, one with none, or a new order) goes whole, as do settings. `sizes` lets the server catch a patch applied to a
// company other than the one it was made from. KEYS and SINGLE must stay the server's (a server test compares them).

/** The fields that identify a record in each list (scp/versions/diff.py KEYS). */
export const KEYS: Record<string, string[]> = {
  calendars: ["id"], locations: ["id"], products: ["id"], resources: ["id"],
  production_sources: ["id"], purchasing_sources: ["id"], lanes: ["id"], receipts: ["id"],
  events: ["id"], allocations: ["id"], movements: ["id"], batches: ["product", "id"], inventory_docs: ["id"],
  location_products: ["location", "product"], npi: ["location", "product"],
  history: ["location", "product", "date"], overrides: ["location", "product", "date"],
  demand: ["id", "location", "product", "date", "kind"], confirmations: ["order", "ship_from", "ship_date"],
  changeovers: ["resource", "from_group", "to_group"], closed_orders: ["kind", "id"],
  accuracy: ["location", "product", "start"], customer_prices: ["customer", "product"], vendors: ["supplier"],
  purchase_orders: ["id"], stock_targets: ["location", "product", "date"], rolled_weeks: ["start"],
  customers: ["customer"], payment_terms: ["id"], sales_orders: ["id"], quotations: ["id"], deliveries: ["id"],
  invoices: ["id"], returns: ["id"], contracts: ["id"], supplier_invoices: ["id"], supplier_returns: ["id"],
};

/** Parts compared as one object (scp/versions/diff.py SINGLE). */
export const SINGLE = ["settings", "forecasting", "inventory", "sop", "scheduling", "promising", "execution", "purchasing", "finance",
  "tower", "sales"];

type Doc = Record<string, unknown>;
type Rec = Record<string, unknown>;
export interface ListChange { upsert?: Rec[]; remove?: unknown[][] }
export interface Patch { v: 1; lists?: Record<string, ListChange>; set?: Doc; drop?: string[]; sizes: Record<string, number> }

/** JSON text with every object's keys sorted: two records equal but for the order of their fields (the server
 *  answers with sorted keys) read the same. */
function stable(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v) ?? "null";
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o).filter((k) => o[k] !== undefined).sort().map((k) => `${JSON.stringify(k)}:${stable(o[k])}`).join(",")}}`;
}

const same = (a: unknown, b: unknown) => a === b || JSON.stringify(a) === JSON.stringify(b) || stable(a) === stable(b);

function recordKeys(rows: unknown[], fields: string[]): unknown[][] | null {
  const out: unknown[][] = [];
  const seen = new Set<string>();
  for (const r of rows) {
    if (!r || typeof r !== "object" || Array.isArray(r)) return null;
    const k = fields.map((f) => (r as Rec)[f] ?? null);
    if (k.every((v) => v === null)) return null;
    const s = JSON.stringify(k);
    if (seen.has(s)) return null;
    seen.add(s);
    out.push(k);
  }
  return out;
}

function listChange(name: string, a: unknown[], b: unknown[]): ListChange | null {
  const fields = KEYS[name] ?? ["id"];
  const ka = recordKeys(a, fields), kb = recordKeys(b, fields);
  if (!ka || !kb) return null;
  const ia = new Map(ka.map((k, i) => [JSON.stringify(k), a[i]] as const));
  const ib = new Set(kb.map((k) => JSON.stringify(k)));
  const keptA = ka.map((k) => JSON.stringify(k)).filter((k) => ib.has(k));
  const keptB = kb.map((k) => JSON.stringify(k)).filter((k) => ia.has(k));
  if (keptA.length !== keptB.length || keptA.some((k, i) => k !== keptB[i])) return null;
  // new records must come last: the server appends them
  const nNew = kb.length - keptB.length;
  if (kb.slice(kb.length - nNew).some((k) => ia.has(JSON.stringify(k)))) return null;
  const upsert = b.filter((r, i) => { const old = ia.get(JSON.stringify(kb[i])); return old === undefined || !same(old, r); }) as Rec[];
  const remove = ka.filter((k) => !ib.has(JSON.stringify(k)));
  const ch: ListChange = {};
  if (upsert.length) ch.upsert = upsert;
  if (remove.length) ch.remove = remove;
  return ch;
}

/** The patch that turns `before` into `after`. */
export function makePatch(before: Doc, after: Doc): Patch {
  const out: Patch = { v: 1, sizes: {} };
  for (const name of [...Object.keys(after), ...Object.keys(before).filter((k) => !(k in after))]) {
    if (!(name in after)) { (out.drop ??= []).push(name); continue; }
    const a = before[name], b = after[name];
    if (Array.isArray(b)) out.sizes[name] = b.length;
    if (name in before && same(a, b)) continue;
    const ch = Array.isArray(a) && Array.isArray(b) && !SINGLE.includes(name) ? listChange(name, a, b) : null;
    if (ch) (out.lists ??= {})[name] = ch;
    else (out.set ??= {})[name] = b;
  }
  return out;
}

/** How big a patch is against the whole company: sending it whole is simpler when most of it changed. */
export const patchIsSmall = (p: Patch, whole: Doc) => {
  // a large company is not written out to be measured: about a hundred characters a record
  const rows = Object.values(whole).reduce<number>((n, v) => n + (Array.isArray(v) ? v.length : 0), 0);
  return JSON.stringify(p).length * 3 < (rows > 50_000 ? rows * 100 : JSON.stringify(whole).length);
};

/** `doc` with `patch` applied, as the server applies it (scp/companies/patch.py apply_patch), for an engine answer
 *  that says what it changed instead of sending the company back whole (Phase S). Records are found by their key,
 *  so records the patch does not name (one the checks set aside, say) stay as they are. Throws when it does not fit. */
export function applyPatch<T extends object>(doc: T, patch: Patch): T {
  if (patch.v !== 1) throw new Error("not a patch this client understands");
  const out = { ...(doc as Doc) };
  for (const name of patch.drop ?? []) delete out[name];
  for (const [name, v] of Object.entries(patch.set ?? {})) out[name] = v;
  for (const [name, ch] of Object.entries(patch.lists ?? {})) {
    const rows = (out[name] ?? []) as unknown[];
    const fields = KEYS[name] ?? ["id"];
    const keys = recordKeys(rows, fields);
    if (!keys) throw new Error(`the records of ${name} cannot be told apart here`);
    const pos = new Map(keys.map((k, i) => [JSON.stringify(k), i] as const));
    const next = [...rows];
    const gone = new Set<number>();
    for (const k of ch.remove ?? []) {
      const i = pos.get(JSON.stringify(k));
      if (i === undefined) throw new Error(`${name}: a removed record is not here`);
      gone.add(i);
    }
    for (const r of ch.upsert ?? []) {
      const s = JSON.stringify(fields.map((f) => r[f] ?? null));
      const i = pos.get(s);
      if (i !== undefined) next[i] = r;
      else { pos.set(s, next.length); next.push(r); }
    }
    out[name] = gone.size ? next.filter((_, i) => !gone.has(i)) : next;
  }
  return out as T;
}
