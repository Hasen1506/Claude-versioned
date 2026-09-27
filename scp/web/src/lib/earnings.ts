// Revenue and margin only where a selling price exists (Q10): demand without a price is listed, never valued.
import type { ServeRow } from "../api/types";

export interface Earnings { revenue: number; margin: number; unpriced: string[] }

export function earnings(rows: ServeRow[]): Earnings {
  let revenue = 0, margin = 0;
  const unpriced = new Set<string>();
  for (const r of rows) {
    if (r.margin === null || r.margin === undefined) {
      if (r.demand > 0) unpriced.add(r.product);
      continue;
    }
    revenue += r.revenue;
    margin += r.margin;
  }
  return { revenue, margin, unpriced: [...unpriced].sort() };
}

/** "A, B and 3 more" from product names. */
export function listNames(ids: string[], name: (id: string) => string, max = 3): string {
  const n = ids.map(name);
  if (n.length <= max) return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}` : n.join("");
  return `${n.slice(0, max).join(", ")} and ${n.length - max} more`;
}
