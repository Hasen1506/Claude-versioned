// The planning spine: the ordered stages of the end-to-end flow (S/4 guide: demand → plan → source/make →
// store → deliver). The rail, the freshness strip and the page headers all read this one list, so a
// stage can never have two names or two numbers.
export interface Stage {
  id: string;        // route
  n: string;         // number shown on the rail and header
  name: string;
  sub: string;       // what it produces
}

export const STAGES: Stage[] = [
  { id: "network", n: "01", name: "Network", sub: "design & map" },
  { id: "readiness", n: "02", name: "Readiness", sub: "master-data gate" },
  { id: "demand", n: "03", name: "Demand", sub: "forecast & consensus" },
  { id: "inventory", n: "04", name: "Inventory", sub: "buffer placement" },
  { id: "sop", n: "05", name: "S&OP", sub: "constrained plan" },
  { id: "plan", n: "06", name: "Supply", sub: "MRP / DRP" },
];

export const stageById = Object.fromEntries(STAGES.map((s) => [s.id, s])) as Record<string, Stage>;
