const nf0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** Quantities: integers stay integers, small fractional values keep precision. */
export function qty(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) < 1e-9) return "0";
  return Math.abs(v) >= 100 ? nf0.format(v) : Math.abs(v) >= 10 ? nf1.format(v) : nf2.format(v);
}

/** Compact money: ₹1.2 Cr / ₹4.5 L / ₹12.3K for INR; K/M/B otherwise. */
export function money(v: number | null | undefined, currency = "INR"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sym = currency === "INR" ? "₹" : currency === "USD" ? "$" : currency === "EUR" ? "€" : `${currency} `;
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (currency === "INR") {
    if (a >= 1e7) return `${sign}${sym}${nf2.format(a / 1e7)} Cr`;
    if (a >= 1e5) return `${sign}${sym}${nf2.format(a / 1e5)} L`;
  } else {
    if (a >= 1e9) return `${sign}${sym}${nf1.format(a / 1e9)}B`;
    if (a >= 1e6) return `${sign}${sym}${nf1.format(a / 1e6)}M`;
  }
  if (a >= 1e3) return `${sign}${sym}${nf1.format(a / 1e3)}K`;
  return `${sign}${sym}${nf2.format(a)}`;
}

/** A per-unit amount: full precision with the currency symbol (₹1,023.4), never compacted. */
export function unitMoney(v: number | null | undefined, currency = "INR"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sym = currency === "INR" ? "₹" : currency === "USD" ? "$" : currency === "EUR" ? "€" : `${currency} `;
  return `${v < 0 ? "−" : ""}${sym}${qty(Math.abs(v))}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (!Number.isFinite(v)) return "∞";
  return `${(v * 100).toFixed(digits)}%`;
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
}

export const TYPE_LABEL: Record<string, string> = {
  plant: "Plant", dc: "Distribution centre", warehouse: "Warehouse", store: "Store",
  supplier: "Supplier", customer: "Customer",
};

export const ORDER_LABEL: Record<string, string> = { make: "Production", buy: "Purchase", transfer: "Transfer" };

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The one date style for plain-language text: "Mon 28 Sep" (the year only when it is not the planning year). */
export function dayName(iso: string | null | undefined, year?: number): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  const s = `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return year !== undefined && d.getFullYear() !== year ? `${s} ${d.getFullYear()}` : s;
}

/** ISO date plus whole days. */
export function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** "1 order" / "3 orders". */
export const plural = (n: number, one: string, many = `${one}s`) => `${qty(n)} ${n === 1 ? one : many}`;
