// ORDER-NEW-01/02: the checks a new customer order gets before anything is sent to the engine.
import type { Dataset } from "../api/types";
import { day, qty } from "./format";

/** What is wrong with a new order's typed quantity and priority (ORDER-NEW-01): nothing is sent until both are right. */
export function orderProblems(raw: { qty: string; priority: string }): { qty?: string; priority?: string } {
  const out: { qty?: string; priority?: string } = {};
  const q = Number(raw.qty);
  if (raw.qty.trim() === "" || !Number.isFinite(q)) out.qty = "Type the quantity ordered, as a number.";
  else if (q <= 0) out.qty = "The quantity must be more than zero.";
  const p = Number(raw.priority);
  if (raw.priority.trim() === "" || !Number.isInteger(p) || p < 1 || p > 9) out.priority = "The priority is a whole number from 1 (first) to 9.";
  return out;
}

/** What a new order should make the planner look twice at (ORDER-NEW-02): a quantity far above any order of the product
 * so far, and a date before the plan starts. Warnings: the order can still be taken. */
export function orderWarnings(ds: Dataset, o: { product: string; qty: number; date: string }, start: string): string[] {
  const out: string[] = [];
  const most = Math.max(0, ...(ds.demand ?? []).filter((d) => d.product === o.product).map((d) => d.qty));
  if (most > 0 ? o.qty > 10 * most : o.qty >= 100_000)
    out.push(`${qty(o.qty)} is far more than any order of this product so far${most > 0 ? ` (the largest is ${qty(most)})` : ""}: check the quantity.`);
  if (o.date && o.date < start) out.push(`Wanted on ${day(o.date)}, before the plan starts (${day(start)}): it is planned as overdue.`);
  return out;
}
