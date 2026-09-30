// The company itself: its name, currency, when planning starts, the working week, how much each order covers, and
// exchange rates. The first step of a blank company (Q12), and #/setup/company afterwards.
import { useState } from "react";
import type { Dataset } from "../api/types";
import { Panel } from "../components/ui";

type Obj = Record<string, unknown>;

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "JPY", "CNY", "AUD", "CAD", "CHF", "ZAR", "BRL", "MXN", "IDR", "THB", "MYR", "SAR", "KES", "NGN"];

/** How much each order covers where a product's planning policy leaves it empty. */
export const COVER: { id: string; label: string; policy: "L4L" | "POQ"; periods: number }[] = [
  { id: "day", label: "Exactly what's needed, day by day", policy: "L4L", periods: 1 },
  { id: "week", label: "A week's need (recommended)", policy: "POQ", periods: 1 },
  { id: "2w", label: "Two weeks' need", policy: "POQ", periods: 2 },
  { id: "4w", label: "Four weeks' need", policy: "POQ", periods: 4 },
];
export function coverOf(s: { default_lot_policy?: string | null; default_lot_periods?: number | null }): string {
  if ((s.default_lot_policy ?? "L4L") === "L4L") return "day";
  return COVER.find((c) => c.policy === "POQ" && c.periods === (s.default_lot_periods ?? 1))?.id ?? "week";
}
export function coverLabel(s: { default_lot_policy?: string | null; default_lot_periods?: number | null }): string {
  const c = coverOf(s);
  if (c === "day") return "exactly what's needed";
  const n = s.default_lot_periods ?? 1;
  return n === 1 ? "a week's need" : `${n} weeks' need`;
}

/** The next Monday from today (the usual start of a weekly plan). */
export function nextMonday(): string {
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() + ((8 - today.getDay()) % 7 || 7));
  return `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, "0")}-${String(monday.getDate()).padStart(2, "0")}`;
}

/** A blank company with these settings. */
export function blankCompany(v: CompanyValues): Dataset {
  return {
    schema_version: "1",
    settings: { company_name: v.name, company_address: v.address ?? "", company_tax_id: v.taxId ?? "", currency: v.currency, planning_start: v.start, horizon_days: 182, bucket: "week",
      week_start: 0, fx_rates: v.fx, wacc: 0.12, holding_spread: 0.08, default_service_level: 0.95, default_calendar: "CAL-STD",
      default_lot_policy: COVER.find((c) => c.id === v.cover)!.policy, default_lot_periods: COVER.find((c) => c.id === v.cover)!.periods },
    calendars: [{ id: "CAL-STD", name: workweekName(v.workdays), workdays: v.workdays, holidays: [] }],
    locations: [], products: [], location_products: [], resources: [], production_sources: [],
    purchasing_sources: [], lanes: [], demand: [], receipts: [], history: [], events: [], npi: [], overrides: [],
  } as unknown as Dataset;
}

function workweekName(days: number[]): string {
  const s = [...days].sort((a, b) => a - b);
  const run = s.every((d, i) => i === 0 || d === s[i - 1] + 1);
  return run && s.length > 1 ? `${DAYS[s[0]]}–${DAYS[s[s.length - 1]]}` : s.map((d) => DAYS[d]).join(", ");
}

export interface CompanyValues {
  name: string; currency: string; start: string; workdays: number[]; cover: string; fx: Record<string, number>;
  address?: string; taxId?: string;
}

/** The company's own settings as the form edits them. */
export function companyValues(ds: Dataset): CompanyValues {
  const s = ds.settings as unknown as Obj;
  const cal = (ds.calendars ?? []).find((c) => c.id === s.default_calendar) ?? (ds.calendars ?? [])[0];
  return {
    name: String(s.company_name ?? ""), currency: String(s.currency ?? "INR"), start: String(s.planning_start),
    workdays: cal?.workdays ?? [0, 1, 2, 3, 4], cover: coverOf(s as never), fx: { ...((s.fx_rates as Record<string, number>) ?? {}) },
    address: String(s.company_address ?? ""), taxId: String(s.company_tax_id ?? ""),
  };
}

/** Write the form's values into a dataset (the default calendar's weekdays included). */
export function applyCompany(d: Dataset, v: CompanyValues, alsoExact: boolean) {
  const s = d.settings as unknown as Obj;
  const c = COVER.find((x) => x.id === v.cover)!;
  Object.assign(s, { company_name: v.name, company_address: (v.address ?? "").trim(), company_tax_id: (v.taxId ?? "").trim(), currency: v.currency, planning_start: v.start, fx_rates: v.fx,
    default_lot_policy: c.policy, default_lot_periods: c.periods });
  const cals = (d.calendars ??= []);
  let cal = cals.find((x) => x.id === s.default_calendar);
  if (!cal) {
    cal = { id: "CAL-STD", name: "", workdays: [], holidays: [] } as unknown as (typeof cals)[number];
    cals.push(cal);
    s.default_calendar = cal.id;
  }
  const days = [...v.workdays].sort((a, b) => a - b);
  // the calendar is named after its week only when the week changes: a saved form must not rename "India Mon–Sat"
  if (JSON.stringify(days) !== JSON.stringify(cal.workdays) || !cal.name) {
    cal.workdays = days;
    cal.name = workweekName(days);
  }
  if (alsoExact) for (const lp of d.location_products ?? []) {
    const ls = lp.lot_sizing as Obj | undefined;
    if (ls && (ls.policy ?? "L4L") === "L4L") ls.policy = null;
  }
}

/** Currencies the company's suppliers price in, other than its own. */
export function foreignCurrencies(ds: Dataset | null, own: string): string[] {
  const out = new Set<string>();
  for (const pu of ds?.purchasing_sources ?? []) if (pu.currency && pu.currency !== own) out.add(pu.currency);
  for (const v of ds?.vendors ?? []) if (v.currency && v.currency !== own) out.add(v.currency);
  return [...out].sort();
}

/** Places and products that now order exactly what's needed by their own setting (not the company default). */
export function exactNodes(ds: Dataset | null): number {
  return (ds?.location_products ?? []).filter((lp) => (lp.lot_sizing as Obj | undefined)?.policy === "L4L").length;
}

export function CompanyForm({ ds, initial, submit, submitLabel, cancel }: {
  ds: Dataset | null; initial: CompanyValues; submit: (v: CompanyValues, alsoExact: boolean) => void; submitLabel: string; cancel?: () => void;
}) {
  const [v, setV] = useState<CompanyValues>(initial);
  const [alsoExact, setAlsoExact] = useState(false);
  const [newCur, setNewCur] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const set = (patch: Partial<CompanyValues>) => setV({ ...v, ...patch });
  const foreign = [...new Set([...foreignCurrencies(ds, v.currency), ...Object.keys(v.fx)])].filter((c) => c !== v.currency).sort();
  const exact = exactNodes(ds);
  const save = () => {
    if (!v.name.trim()) return setErr("Give the company a name.");
    if (!/^[A-Za-z]{3}$/.test(v.currency)) return setErr("The currency is a three-letter code, e.g. INR, USD or EUR.");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v.start)) return setErr("Choose the day planning starts.");
    if (!v.workdays.length) return setErr("Tick at least one working day.");
    const missing = foreign.filter((c) => !(v.fx[c] > 0));
    if (missing.length) return setErr(`Enter what one ${missing.join(", one ")} costs in ${v.currency.toUpperCase()}.`);
    setErr(null);
    submit({ ...v, name: v.name.trim(), currency: v.currency.toUpperCase() }, alsoExact);
  };
  return (
    <div className="stack company-form">
      <div className="qrow">
        <label className="qf"><span className="qf-l">Company name</span>
          <input className="input" value={v.name} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. Kaveri Paints" aria-label="Company name" /></label>
        <label className="qf"><span className="qf-l">Currency</span>
          <input className="input" list="currencies" value={v.currency} maxLength={3} style={{ width: 80, textTransform: "uppercase" }}
            onChange={(e) => set({ currency: e.target.value.toUpperCase() })} aria-label="Currency" />
          <datalist id="currencies">{CURRENCIES.map((c) => <option key={c} value={c} />)}</datalist>
          <span className="qf-h">prices, costs and money pages are in this</span></label>
        <label className="qf"><span className="qf-l">Planning starts</span>
          <input className="input" type="date" value={v.start} onChange={(e) => set({ start: e.target.value })} aria-label="Planning starts" />
          <span className="qf-h">"today" for the plan; move it on each week</span></label>
      </div>
      <div className="qrow">
        <label className="qf" style={{ flex: "2 1 260px" }}><span className="qf-l">Address</span>
          <textarea className="input" rows={3} value={v.address ?? ""} onChange={(e) => set({ address: e.target.value })} aria-label="Company address"
            placeholder={"Plot 14, GIDC Estate\nVapi 396195, Gujarat"} />
          <span className="qf-h">optional: printed on purchase orders as the address to invoice</span></label>
        <label className="qf"><span className="qf-l">Tax number</span>
          <input className="input" value={v.taxId ?? ""} onChange={(e) => set({ taxId: e.target.value })} aria-label="Company tax number" placeholder="GSTIN or VAT number" />
          <span className="qf-h">optional</span></label>
      </div>
      <div className="qf"><span className="qf-l">Working days</span>
        <div className="row wrap" role="group" aria-label="Working days">{DAYS.map((d, i) => <label key={d} className="row small">
          <input type="checkbox" checked={v.workdays.includes(i)}
            onChange={(e) => set({ workdays: e.target.checked ? [...v.workdays, i] : v.workdays.filter((x) => x !== i) })} /> {d}</label>)}</div>
        <span className="qf-h">plants, warehouses and suppliers work these days unless they have their own calendar</span></div>
      <label className="qf"><span className="qf-l">Each order covers</span>
        <select className="select" value={v.cover} onChange={(e) => set({ cover: e.target.value })} aria-label="Each order covers" style={{ width: "auto" }}>
          {COVER.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select>
        <span className="qf-h">how much one production run, purchase or transfer brings in, where a product doesn't say otherwise. Day by day
          makes many small orders; a week's need is where most planners start. Fixed batches and minimums are set per product.</span></label>
      {exact > 0 && coverOf({ default_lot_policy: COVER.find((c) => c.id === v.cover)!.policy }) !== "day" && <label className="row small">
        <input type="checkbox" checked={alsoExact} onChange={(e) => setAlsoExact(e.target.checked)} />
        Also use it for the {exact} product{exact === 1 ? "" : "s"} at places now set to order exactly what's needed</label>}
      <div className="qf"><span className="qf-l">Exchange rates</span>
        {foreign.map((c) => <div key={c} className="row small">1 {c} =
          <input className="input num" type="number" min={0} step="any" value={v.fx[c] ?? ""} style={{ width: 100 }} aria-label={`${v.currency} per ${c}`}
            onChange={(e) => set({ fx: { ...v.fx, [c]: Number(e.target.value) } })} /> {v.currency}
          {!foreignCurrencies(ds, v.currency).includes(c) && <button className="btn sm ghost" onClick={() => { const fx = { ...v.fx }; delete fx[c]; set({ fx }); }}>Remove</button>}</div>)}
        <div className="row small">
          <input className="input" list="currencies" value={newCur} maxLength={3} placeholder="USD" style={{ width: 70, textTransform: "uppercase" }}
            onChange={(e) => setNewCur(e.target.value.toUpperCase())} aria-label="Add a currency" />
          <button className="btn sm" disabled={!/^[A-Z]{3}$/.test(newCur) || newCur === v.currency || newCur in v.fx}
            onClick={() => { set({ fx: { ...v.fx, [newCur]: 0 } }); setNewCur(""); }}>Add a currency</button>
        </div>
        <span className="qf-h">for suppliers who invoice in another currency: their prices are kept in it and turned into {v.currency} with this rate</span></div>
      {err && <div className="banner warning" role="alert">{err}</div>}
      <div className="row"><button className="btn primary" onClick={save}>{submitLabel}</button>{cancel && <button className="btn ghost" onClick={cancel}>Cancel</button>}</div>
    </div>
  );
}

export function CompanyPanel({ ds, onSave }: { ds: Dataset; onSave: (v: CompanyValues, alsoExact: boolean) => void }) {
  return <Panel title="Your company"><CompanyForm ds={ds} initial={companyValues(ds)} submit={onSave} submitLabel="Save" /></Panel>;
}
