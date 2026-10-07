// The first-run guide on Home ticks a step only when the planner has really done it (UX audit: "Check a new order" and
// "Try a what-if" were ticked after merely opening the pages). The API client records the event when the request that
// IS the step succeeds: a promise check, or a comparison of two versions or scenarios.
export const DONE_KEY = "scp.guide.done.v1";
export type GuideEvent = "check" | "whatif";

export function guideDone(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(DONE_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

export function markDone(ev: GuideEvent) {
  const s = guideDone();
  if (s.has(ev)) return;
  s.add(ev);
  try {
    localStorage.setItem(DONE_KEY, JSON.stringify([...s]));
  } catch {
    /* storage unavailable: the guide just doesn't tick */
  }
}

/** Pass a request's result through, recording the guide step once it succeeded. */
export const done = <T,>(ev: GuideEvent) => (r: T): T => {
  markDone(ev);
  return r;
};
