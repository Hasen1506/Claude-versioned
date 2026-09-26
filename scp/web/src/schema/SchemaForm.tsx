// One form generator for every master-data object, driven by the engine's JSON schema.
// The schema's `x-unit` picks the unit suffix (fractions are shown as %, stored as 0–1),
// `x-ref` turns a string into a picker of existing ids. No page hand-builds its own inputs.
import { useEffect, useState, type ReactNode } from "react";
import { api, type JsonSchema, type JsonSchemaNode } from "../api/client";
import type { Dataset } from "../api/types";
import { useStore } from "../state/store";

let schemaPromise: Promise<JsonSchema> | null = null;

export function useSchema(): JsonSchema | null {
  const [s, setS] = useState<JsonSchema | null>(null);
  useEffect(() => {
    schemaPromise ??= api.schema();
    schemaPromise.then(setS).catch(() => (schemaPromise = null));
  }, []);
  return s;
}

export type Obj = Record<string, unknown>;
export type FieldErrors = Record<string, string>;

export function deref(schema: JsonSchema, node: JsonSchemaNode): JsonSchemaNode {
  if (node.$ref) return schema.$defs[node.$ref.split("/").pop()!];
  return node;
}

/** Unwrap `anyOf: [X, null]` → X, remembering that null is allowed. */
export function unwrap(schema: JsonSchema, node: JsonSchemaNode): { node: JsonSchemaNode; nullable: boolean } {
  if (node.anyOf) {
    const nonNull = node.anyOf.filter((n) => n.type !== "null");
    const nullable = nonNull.length < node.anyOf.length;
    const inner = deref(schema, nonNull[0] ?? {});
    return { node: { ...inner, ...pick(node) }, nullable };
  }
  if (node.$ref) return { node: { ...deref(schema, node), ...pick(node) }, nullable: false };
  return { node, nullable: false };
}

function pick(n: JsonSchemaNode): JsonSchemaNode {
  const out: JsonSchemaNode = {};
  for (const k of ["title", "description", "x-unit", "x-ref", "default"] as const) {
    if (n[k] !== undefined) (out as Record<string, unknown>)[k] = n[k];
  }
  return out;
}

const ACRONYM: Record<string, string> = {
  id: "Id", moq: "MOQ", gr: "GR", fx: "FX", uom: "UoM", wacc: "WACC", mrp: "MRP", m3: "m³", kg: "kg", lat: "Latitude",
  lon: "Longitude", qty: "quantity", cv: "CV",
};

/** Fields whose name alone reads badly. */
const TITLE: Record<string, string> = {
  float_before_workdays: "Float before production (working days)", float_after_workdays: "Float after production (working days)",
  mrp_controller: "MRP controller (who plans it)", procurement: "Procurement type", phantom: "Phantom assembly",
  send_ahead_qty: "Overlap: send ahead quantity", co_products: "Co-products and by-products", capacity_changes: "Capacity changes",
  fixed_qty: "Fixed quantity per run", change: "Engineering change", subcontract: "Done outside by a supplier",
  alternatives: "Alternative machines", break_minutes: "Break (minutes)", cost_share: "Share of the run's cost",
  capacity_constrained: "Plan within machine capacity", wait_for_parts: "Wait for parts", step_resources: "Steps on an alternative machine",
  scheduled: "Dated by the shop floor schedule",
  capacity_direction: "When a day is full, first try", capacity_max_early_days: "Build at most this many days ahead",
  earliness_weight: "Weight: an hour early", makespan_weight: "Weight: an hour to clear the window", start_rule: "Start rule",
  optimizer: "Use the optimiser (constraint solver)", backward_buffer_days: "Backward: buffer before the due date (days)",
  frozen_days: "Frozen zone (days)", profile: "Scheduling profile", hold: "Not before",
  price_scales: "Price scales (quantity breaks)", from_qty: "From quantity", fixed: "Fixed source (planning uses it first)",
  blocked: "Blocked", vendor_material: "Supplier's part number", payment_terms_days: "Payment terms (days)",
  confirmation_required: "Supplier confirms each order", confirmation_days: "Confirmation expected within (days)",
  over_delivery_tolerance: "Over-delivery allowed", under_delivery_tolerance: "Short delivery that still closes the line",
  min_order_value: "Minimum order value", approval_limit: "Orders above this need approval",
  release_window_days: "Show as due to order within (days)", sent_on: "Sent on", vendor_reference: "Supplier's confirmation number",
  po: "Purchase order", confirmed_date: "Confirmed delivery date", confirmed_qty: "Confirmed quantity",
  block_reason: "Why blocked", incoterms: "Delivery terms (Incoterms)",
};

/** Plain words for enum values; the stored value stays the code. */
const ENUM_LABEL: Record<string, string> = {
  any: "Made here or got from outside", make: "Made here only (in-house)", external: "Bought or shipped in only (external)",
  deterministic: "Plan to requirements (PD)", reorder_point: "Reorder point (VB)", none: "None",
  MTS: "Make to stock, orders don't consume the forecast (10)", MTS_CONSUME: "Make to stock, orders consume the forecast (40)",
  MTO: "Make to order (20)", ATO: "Assemble to order (50)",
  L4L: "Lot for lot: exactly what is needed", FIXED: "Fixed lot size", EOQ: "Economic order quantity",
  POQ: "Cover a number of periods", MIN_MAX: "Replenish up to the maximum stock",
  fixed: "A fixed quantity", days_of_supply: "Days of cover", service_level: "Service level (chance of no stockout)",
  fill_rate: "Fill rate (share of demand served from stock)",
  earlier: "Start earlier (build ahead)", later: "Finish later (delay)",
  edd: "Earliest due date first", spt: "Shortest job first", slack: "Least slack first",
  campaign: "Campaigns by setup group", backward: "Backward from the due date (just in time)",
};

/** Sentence-case label from a field name: `gr_processing_days` → "GR processing days". */
export function humanize(name: string): string {
  if (TITLE[name]) return TITLE[name];
  const words = name.split("_").map((w) => ACRONYM[w] ?? w);
  const out = words.join(" ");
  return out.charAt(0).toUpperCase() + out.slice(1);
}

export function unitLabel(unit: string | undefined, currency: string): string | null {
  switch (unit) {
    case "fraction": return "%";
    case "days": return "days";
    case "workdays": return "work days";
    case "hours": return "h";
    case "qty": return "units";
    case "kg": return "kg";
    case "m3": return "m³";
    case "money": return currency;
    case "money_per_unit": return `${currency}/unit`;
    case "money_per_hour": return `${currency}/h`;
    case "money_per_kg": return `${currency}/kg`;
    case "money_per_m3": return `${currency}/m³`;
    default: return null;
  }
}

/** Build a new object with schema defaults (required fields without a default get an empty value). */
export function defaults(schema: JsonSchema, defName: string, seed: Obj = {}): Obj {
  const def = schema.$defs[defName];
  const out: Obj = {};
  for (const [k, raw] of Object.entries(def.properties ?? {})) {
    if (k in seed) continue;
    const { node } = unwrap(schema, raw);
    if (raw.default !== undefined) out[k] = structuredClone(raw.default);
    else if (def.required?.includes(k)) {
      if (node.enum) out[k] = node.enum[0];
      else if (node.type === "number" || node.type === "integer") out[k] = node.minimum ?? 0;
      else if (node.type === "array") out[k] = [];
      else if (node.type === "boolean") out[k] = false;
      else if (node.type === "object" && node.properties) out[k] = defaults(schema, raw.$ref!.split("/").pop()!);
      else out[k] = "";
    }
  }
  return { ...out, ...seed };
}

function refOptions(ds: Dataset | null, kind: string): { id: string; label: string }[] {
  if (!ds) return [];
  const list =
    kind === "location" ? ds.locations : kind === "product" ? ds.products : kind === "resource" ? ds.resources
      : kind === "calendar" ? ds.calendars ?? [] : [];
  return (list ?? []).map((x) => {
    const o = x as { id: string; name?: string; type?: string };
    return { id: o.id, label: o.name && o.name !== o.id ? `${o.id} — ${o.name}` : o.id };
  });
}

// ------------------------------------------------------------------------------------------------
export function SchemaForm({ defName, value, onChange, errors = {}, path = "", hide = [], only, compact }: {
  defName: string; value: Obj; onChange: (next: Obj) => void; errors?: FieldErrors; path?: string;
  hide?: string[]; compact?: boolean;
  /** Show only these fields, in this order (a tab of a larger record). */
  only?: string[];
}) {
  const schema = useSchema();
  if (!schema) return <div className="faint small">Loading form…</div>;
  const def = schema.$defs[defName];
  if (!def) return <div className="faint">Unknown object type {defName}</div>;
  const props = def.properties ?? {};
  const entries = only ? only.filter((k) => k in props).map((k) => [k, props[k]] as const) : Object.entries(props);
  return (
    <div className={compact ? "form compact" : "form"}>
      {entries.filter(([k]) => !hide.includes(k)).map(([key, raw]) => (
        <FieldFor key={key} schema={schema} name={key} raw={raw} required={!!def.required?.includes(key)}
          value={value[key]} errors={errors} path={path ? `${path}.${key}` : key}
          onChange={(v) => {
            const next = { ...value };
            if (v === undefined) delete next[key];
            else next[key] = v;
            onChange(next);
          }} />
      ))}
    </div>
  );
}

function FieldFor({ schema, name, raw, required, value, onChange, errors, path }: {
  schema: JsonSchema; name: string; raw: JsonSchemaNode; required: boolean; value: unknown;
  onChange: (v: unknown) => void; errors: FieldErrors; path: string;
}) {
  const currency = useStore((s) => s.dataset?.settings.currency ?? "INR");
  const { node, nullable } = unwrap(schema, raw);
  const title = humanize(name);
  const err = errors[path];
  const help = raw.description;

  // nested object → fieldset
  if (node.type === "object" && node.properties) {
    const defName = (raw.$ref ?? raw.anyOf?.find((a) => a.$ref)?.$ref ?? "").split("/").pop()!;
    const obj = (value as Obj | null | undefined) ?? (nullable ? null : defaults(schema, defName));
    return (
      <div className="fieldset">
        <div className="legend">{title}</div>
        {obj === null ? (
          <button className="btn sm" onClick={() => onChange(defaults(schema, defName))}>+ Add {title.toLowerCase()}</button>
        ) : (
          <SchemaForm defName={defName} value={obj as Obj} onChange={onChange} errors={errors} path={path} />
        )}
      </div>
    );
  }
  // list of enum values → a checkbox set
  const itemNode = node.type === "array" && node.items ? deref(schema, node.items) : null;
  if (itemNode?.enum) {
    const list = (value as string[] | null | undefined) ?? [];
    return (
      <div className="field">
        <label>{title}{required && <span className="req">*</span>}</label>
        <div className="chips" role="group" aria-label={title}>
          {itemNode.enum.map((opt) => (
            <label key={opt} className="chip" style={{ cursor: "pointer" }}>
              <input type="checkbox" checked={list.includes(opt)}
                onChange={(e) => onChange(e.target.checked ? [...list, opt] : list.filter((x) => x !== opt))} />
              {opt}
            </label>
          ))}
        </div>
        {err && <div className="err">{err}</div>}
        {help && !err && <div className="help">{help}</div>}
      </div>
    );
  }
  // list of nested objects → repeatable cards
  if (node.type === "array" && node.items && (node.items.$ref || node.items.properties)) {
    const itemDef = (node.items.$ref ?? "").split("/").pop()!;
    const list = (value as Obj[] | undefined) ?? [];
    return (
      <div className="fieldset">
        <div className="row">
          <div className="legend">{title} <span className="faint">({list.length})</span></div>
          <span className="spacer" />
          <button className="btn sm" onClick={() => onChange([...list, defaults(schema, itemDef)])}>+ Add</button>
        </div>
        {err && <div className="err small">{err}</div>}
        {list.map((item, i) => (
          <div key={i} className="panel" style={{ margin: "8px 0", padding: "4px 10px 6px", boxShadow: "none" }}>
            <div className="row small faint" style={{ paddingTop: 4 }}>
              #{i + 1}
              <span className="spacer" />
              <button className="btn ghost sm" disabled={i === 0} title="Move up"
                onClick={() => { const n = [...list]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; onChange(n); }}>↑</button>
              <button className="btn ghost sm danger" onClick={() => onChange(list.filter((_, j) => j !== i))}>Remove</button>
            </div>
            <SchemaForm defName={itemDef} value={item} errors={errors} path={`${path}.${i}`}
              onChange={(v) => onChange(list.map((x, j) => (j === i ? v : x)))} />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="field">
      <label htmlFor={path}>{title}{required && <span className="req">*</span>}</label>
      <div>
        <Widget id={path} name={name} node={node} nullable={nullable} value={value}
          onChange={onChange} currency={currency} invalid={!!err} />
      </div>
      {err && <div className="err">{err}</div>}
      {help && !err && <div className="help">{help}</div>}
    </div>
  );
}

function Widget({ id, name, node, nullable, value, onChange, currency, invalid }: {
  id: string; name: string; node: JsonSchemaNode; nullable: boolean; value: unknown;
  onChange: (v: unknown) => void; currency: string; invalid: boolean;
}): ReactNode {
  const ds = useStore((s) => s.dataset);
  const cls = `input ${invalid ? "invalid" : ""}`;

  if (node.enum) {
    return (
      <select id={id} className="select" value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? (nullable ? null : undefined) : e.target.value)}>
        {nullable && <option value="">—</option>}
        {node.enum.map((v) => <option key={v} value={v}>{ENUM_LABEL[v] ?? v}</option>)}
      </select>
    );
  }
  if (node["x-ref"] && node.type === "array") {
    return <RefMulti id={id} options={refOptions(ds, node["x-ref"])} value={(value as string[] | null) ?? []}
      onChange={(v) => onChange(v.length ? v : nullable ? null : [])} />;
  }
  if (node["x-ref"]) {
    const opts = refOptions(ds, node["x-ref"]);
    const v = (value as string | null | undefined) ?? "";
    return (
      <select id={id} className={`select ${invalid ? "invalid" : ""}`} value={v}
        onChange={(e) => onChange(e.target.value === "" ? (nullable ? null : "") : e.target.value)}>
        <option value="">{nullable ? "—" : "Select…"}</option>
        {v && !opts.some((o) => o.id === v) && <option value={v}>{v} (unknown)</option>}
        {opts.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    );
  }
  if (node.type === "boolean") {
    return <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} style={{ marginTop: 9 }} />;
  }
  if (node.type === "number" || node.type === "integer") {
    return <NumberInput id={id} node={node} nullable={nullable} value={value as number | null | undefined}
      onChange={onChange} unit={unitLabel(node["x-unit"], currency)} integer={node.type === "integer"}
      invalid={invalid} />;
  }
  if (node.type === "array" && node.items?.type === "integer" && name === "workdays") {
    return <Weekdays value={(value as number[]) ?? []} onChange={onChange} />;
  }
  if (node.type === "array" && node.items?.format === "date") {
    return <DateList value={(value as string[]) ?? []} onChange={onChange} />;
  }
  if (node.type === "object" && node.additionalProperties) {
    return <KeyValue value={(value as Record<string, number>) ?? {}} onChange={onChange} />;
  }
  if (node.format === "date") {
    return <input id={id} type="date" className={cls} value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value || (nullable ? null : ""))} />;
  }
  return <input id={id} className={cls} value={(value as string) ?? ""}
    onChange={(e) => onChange(e.target.value === "" && nullable ? null : e.target.value)} />;
}

function NumberInput({ id, node, nullable, value, onChange, unit, integer, invalid }: {
  id: string; node: JsonSchemaNode; nullable: boolean; value: number | null | undefined;
  onChange: (v: unknown) => void; unit: string | null; integer: boolean; invalid: boolean;
}) {
  const isPct = node["x-unit"] === "fraction";
  const shown = (v: number | null | undefined) =>
    v === null || v === undefined ? "" : isPct ? String(+(v * 100).toFixed(6)) : String(v);
  const [text, setText] = useState(shown(value));
  // re-sync when the stored value changes from outside (undo, another editor)
  useEffect(() => setText(shown(value)), [value, isPct]);
  const commit = (t: string) => {
    if (t.trim() === "") return onChange(nullable ? null : undefined);
    const n = Number(t);
    if (!Number.isFinite(n)) return;
    const v = isPct ? n / 100 : integer ? Math.round(n) : n;
    onChange(v);
  };
  const lo = node.minimum ?? node.exclusiveMinimum;
  const hi = node.maximum ?? node.exclusiveMaximum;
  const n = Number(text);
  const outOfRange = text !== "" && Number.isFinite(n) && (
    (lo !== undefined && (isPct ? n / 100 : n) < lo) || (hi !== undefined && (isPct ? n / 100 : n) > hi));
  return (
    <div className={`input-wrap ${unit ? "has-unit" : ""}`}>
      <input id={id} className={`input num ${invalid || outOfRange ? "invalid" : ""}`} inputMode="decimal" value={text}
        placeholder={nullable ? "—" : ""} onChange={(e) => setText(e.target.value)} onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && commit((e.target as HTMLInputElement).value)}
        title={lo !== undefined || hi !== undefined
          ? `Allowed: ${lo ?? "−∞"} … ${hi ?? "∞"}${isPct ? " (as a fraction)" : ""}` : undefined} />
      {unit && <span className="unit">{unit}</span>}
    </div>
  );
}

const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function Weekdays({ value, onChange }: { value: number[]; onChange: (v: unknown) => void }) {
  return (
    <div className="toggle-days">
      {WD.map((d, i) => (
        <button key={d} type="button" className={value.includes(i) ? "on" : ""} aria-pressed={value.includes(i)}
          onClick={() => onChange(value.includes(i) ? value.filter((x) => x !== i) : [...value, i].sort())}>{d}</button>
      ))}
    </div>
  );
}

function DateList({ value, onChange }: { value: string[]; onChange: (v: unknown) => void }) {
  const [d, setD] = useState("");
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="chips">
        {value.map((x) => (
          <span key={x} className="chip">{x}<button aria-label={`Remove ${x}`} onClick={() => onChange(value.filter((y) => y !== x))}>×</button></span>
        ))}
        {!value.length && <span className="faint small">None</span>}
      </div>
      <div className="row">
        <input type="date" className="input" value={d} onChange={(e) => setD(e.target.value)} style={{ maxWidth: 180 }} />
        <button className="btn sm" disabled={!d || value.includes(d)} onClick={() => { onChange([...value, d].sort()); setD(""); }}>Add</button>
      </div>
    </div>
  );
}

function KeyValue({ value, onChange }: { value: Record<string, number>; onChange: (v: unknown) => void }) {
  const [k, setK] = useState("");
  const [v, setV] = useState("");
  return (
    <div className="stack" style={{ gap: 6 }}>
      {Object.entries(value).map(([key, val]) => (
        <div key={key} className="row">
          <code style={{ width: 50 }}>{key}</code>
          <input className="input num" defaultValue={val} style={{ maxWidth: 140 }}
            onBlur={(e) => Number(e.target.value) > 0 && onChange({ ...value, [key]: Number(e.target.value) })} />
          <button className="btn ghost sm danger" onClick={() => { const n = { ...value }; delete n[key]; onChange(n); }}>Remove</button>
        </div>
      ))}
      <div className="row">
        <input className="input" placeholder="USD" value={k} onChange={(e) => setK(e.target.value.toUpperCase())} style={{ width: 70 }} maxLength={3} />
        <input className="input num" placeholder="rate" value={v} onChange={(e) => setV(e.target.value)} style={{ maxWidth: 140 }} />
        <button className="btn sm" disabled={k.length !== 3 || !(Number(v) > 0)}
          onClick={() => { onChange({ ...value, [k]: Number(v) }); setK(""); setV(""); }}>Add</button>
      </div>
    </div>
  );
}

function RefMulti({ id, options, value, onChange }: {
  id: string; options: { id: string; label: string }[]; value: string[]; onChange: (v: string[]) => void;
}) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="chips">
        {value.map((x) => (
          <span key={x} className="chip">{x}<button aria-label={`Remove ${x}`} onClick={() => onChange(value.filter((y) => y !== x))}>×</button></span>
        ))}
        {!value.length && <span className="faint small">All</span>}
      </div>
      <select id={id} className="select" value="" onChange={(e) => e.target.value && onChange([...value, e.target.value])}>
        <option value="">Add…</option>
        {options.filter((o) => !value.includes(o.id)).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </div>
  );
}
