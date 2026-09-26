// "What's missing": the engine's setup checklist (validate/setup.py), step by step in the order a planner sets a
// company up, each line with the one button that fixes it. Used on Home and on the Data check.
import type { ValidationResult } from "../api/types";
import { href } from "../lib/router";
import { SevIcon } from "./ui";

type Item = NonNullable<ValidationResult["setup"]>[number];

const STEP_TITLE: Record<string, string> = {
  places: "Places", products: "Products", demand: "Demand", supply: "How each product gets where it's needed",
  making: "How products are made", stock: "Stock on hand", unfinished: "Unfinished records",
};
const ORDER = ["places", "products", "demand", "supply", "making", "stock", "unfinished"];
const SEV = { done: "ok", todo: "error", check: "warning", info: "info" } as const;
const WORD = { done: "Done", todo: "To do", check: "Check", info: "Note" } as const;

/** Is there anything a planner must still do before a plan means something? */
export const setupTodo = (v: ValidationResult | null) => (v?.setup ?? []).filter((i) => i.status === "todo");

export function Checklist({ items, compact, max }: { items: Item[]; compact?: boolean; max?: number }) {
  const steps = ORDER.filter((s) => items.some((i) => i.step === s));
  let left = max ?? Infinity;
  return (
    <ol className={`checklist ${compact ? "compact" : ""}`}>
      {steps.map((s) => {
        const list = items.filter((i) => i.step === s);
        const worst = list.find((i) => i.status === "todo") ?? list.find((i) => i.status === "check") ?? list.find((i) => i.status === "info") ?? list[0];
        const shown = compact ? list.filter((i) => i.status !== "done") : list;
        if (compact && !shown.length) return null;
        if (left <= 0) return null;
        const cut = shown.slice(0, left);
        left -= cut.length;
        return (
          <li key={s} className={`cl-step ${worst.status}`}>
            <div className="cl-title"><SevIcon sev={SEV[worst.status]} /><b>{STEP_TITLE[s] ?? s}</b>
              <span className="cl-word">{WORD[worst.status]}</span></div>
            <ul>
              {cut.map((i, n) => (
                <li key={n} className={i.status}>
                  <span>{i.text}</span>
                  {i.action && <a className={i.status === "todo" ? "btn sm primary" : "btn sm"} href={href(...i.action.route)}>{i.action.label}</a>}
                </li>
              ))}
              {shown.length > cut.length && <li className="faint">and {shown.length - cut.length} more</li>}
            </ul>
          </li>
        );
      })}
    </ol>
  );
}
