// The safe date of an order check (Enterprise 4.4): the order checked again with the high end of the forecast still to
// be ordered before its date promised first. The high end is the top of the forecast's interval: P90 at 80 %.
import type { Dataset, OrderPromise } from "../api/types";
import { day, qty } from "./format";

export type Safe = NonNullable<OrderPromise["safe"]>;

/** "P90" for the default 80 % interval, "P95" for 90 %. */
export function highEnd(ds: Dataset): string {
  return `P${Math.round(50 + 50 * (ds.forecasting?.interval ?? 0.8))}`;
}

/** How often a period goes over its high end: one in 10 at P90. */
export function overEvery(ds: Dataset): number {
  return Math.round(2 / (1 - (ds.forecasting?.interval ?? 0.8)));
}

/** The safe answer in words: on time, late by when, or how much cannot be promised. */
export function safeWords(s: Safe, ordered: number): string {
  if (s.status === "on_time") return "still on time";
  if (s.confirmed <= 1e-9) return "cannot be promised";
  const rest = s.confirmed < ordered - 1e-6 ? `${qty(ordered - s.confirmed)} cannot be promised` : `the rest by ${day(s.date!)}`;
  return `${s.on_time > 1e-9 ? `${qty(s.on_time)} on time, ` : ""}${rest}`;
}
