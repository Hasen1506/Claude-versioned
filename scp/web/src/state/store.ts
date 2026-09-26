// The client owns the planning dataset (one JSON document). Every edit goes through `update`,
// which bumps the revision, records undo history, persists locally, and schedules a
// re-validation against the engine. Every engine run (forecast, plan, …) remembers the revision it
// was computed on, so the UI can show "stale" the moment any input changes — the legacy STALE
// cascade, done by construction instead of by a dependency table.
import { useSyncExternalStore } from "react";
import { api, SchemaRejected, setPlanningView } from "../api/client";
import type { ActualsView, Dataset, FinanceResult, TowerResult, ForecastResult, InventoryResult, NetworkView, PlanResult, PromiseResult, ScheduleResult, SopResult, SchemaError, ValidationResult } from "../api/types";

export interface RunResults {
  forecast: ForecastResult;
  inventory: InventoryResult;
  sop: SopResult;
  plan: PlanResult;
  schedule: ScheduleResult;
  promise: PromiseResult;
  actuals: ActualsView;
  finance: FinanceResult;
  tower: TowerResult;
}
export type RunKey = keyof RunResults;

export interface Run<T> {
  data: T | null;
  revision: number | null;   // dataset revision the result was computed on
  running: boolean;
  error: string | null;
  at: string | null;         // wall-clock time of the last successful run
}

/** The stored version the working copy was opened from or last saved to (P8). */
export interface WorkingVersion {
  id: string;
  name: string;
  kind: string;          // base | scenario
  status: string;
  savedRevision: number; // working-copy revision that equals the stored content
}

export interface State {
  dataset: Dataset | null;
  version: WorkingVersion | null;
  revision: number;
  validation: ValidationResult | null;
  schemaErrors: SchemaError[];
  network: NetworkView | null;
  runs: { [K in RunKey]: Run<RunResults[K]> };
  checking: boolean;
  engineError: string | null;
  canUndo: boolean;
  canRedo: boolean;
  /** "Plan everything" in progress: which step of how many, and what it is doing now. */
  planning: { done: number; of: number; label: string } | null;
}

/** What "Plan everything" calculates, in order. Every step only reads the dataset; none changes it. */
export const PLAN_STEPS: { key: RunKey; label: string }[] = [
  { key: "forecast", label: "Forecasting demand" },
  { key: "plan", label: "Planning supply" },
  { key: "promise", label: "Checking customer orders" },
  { key: "inventory", label: "Sizing safety stock" },
  { key: "sop", label: "Balancing capacity" },
  { key: "schedule", label: "Sequencing the shop floor" },
  { key: "actuals", label: "Reading actuals" },
  { key: "finance", label: "Costing the plan" },
  { key: "tower", label: "Measuring performance" },
];

const RUNNERS: { [K in RunKey]: (ds: Dataset) => Promise<RunResults[K]> } = {
  forecast: api.forecast,
  inventory: api.inventory,
  sop: api.sop,
  plan: api.plan,
  schedule: (ds) => api.schedule(ds),
  promise: api.promise,
  actuals: (ds) => api.actuals(ds),
  finance: api.finance,
  tower: api.tower,
};

const STORAGE_KEY = "scp.dataset.v1";
const VERSION_KEY = "scp.version.v1";
const HISTORY = 100;

const emptyRun = <T>(): Run<T> => ({ data: null, revision: null, running: false, error: null, at: null });
const emptyRuns = (): State["runs"] => ({ forecast: emptyRun(), inventory: emptyRun(), sop: emptyRun(), plan: emptyRun(), schedule: emptyRun(), promise: emptyRun(), actuals: emptyRun(), finance: emptyRun(), tower: emptyRun() });

let state: State = {
  dataset: null, version: null, revision: 0, validation: null, schemaErrors: [], network: null, runs: emptyRuns(),
  checking: false, engineError: null, canUndo: false, canRedo: false, planning: null,
};
const listeners = new Set<() => void>();
const past: Dataset[] = [];
const future: Dataset[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;
/** Revision the last data check answered for (validation and set-aside records are current at it). */
let checkedRevision = -1;
/** Unfinished records the last data check set aside, by collection, as their JSON text: matched by content, so
 *  an edit elsewhere (which shifts row positions) never un-sets or wrongly sets aside a record. */
let setAside: Map<string, Set<string>> = new Map();

type Coll = Record<string, unknown[] | undefined>;

setPlanningView((ds) => {
  if (!setAside.size) return { clean: ds, restore: (x) => x };
  const clean = { ...ds } as unknown as Coll;
  const dropped: [string, unknown[]][] = [];
  for (const [coll, texts] of setAside) {
    const list = clean[coll];
    if (!list) continue;
    const out = list.filter((r) => !texts.has(JSON.stringify(r)));
    if (out.length !== list.length) {
      dropped.push([coll, list.filter((r) => texts.has(JSON.stringify(r)))]);
      clean[coll] = out;
    }
  }
  return {
    clean: clean as unknown as Dataset,
    restore: (next) => {
      if (!dropped.length) return next;
      const back = { ...next } as unknown as Coll;
      for (const [coll, recs] of dropped) back[coll] = [...(back[coll] ?? []), ...recs];
      return back as unknown as Dataset;
    },
  };
});

function set(patch: Partial<State>) {
  state = { ...state, ...patch, canUndo: past.length > 0, canRedo: future.length > 0 };
  listeners.forEach((l) => l());
}

function setRun<K extends RunKey>(key: K, patch: Partial<Run<RunResults[K]>>) {
  set({ runs: { ...state.runs, [key]: { ...state.runs[key], ...patch } } });
}

function persist(ds: Dataset | null) {
  try {
    if (ds) localStorage.setItem(STORAGE_KEY, JSON.stringify(ds));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode, quota) — the app still works in memory */
  }
}

function persistVersion(v: WorkingVersion | null, modified: boolean) {
  try {
    if (v) localStorage.setItem(VERSION_KEY, JSON.stringify({ ...v, modified }));
    else localStorage.removeItem(VERSION_KEY);
  } catch {
    /* ignore */
  }
}

function scheduleCheck() {
  clearTimeout(timer);
  timer = setTimeout(check, 350);
}

async function check() {
  const ds = state.dataset;
  if (!ds) return;
  const rev = state.revision;
  set({ checking: true });
  try {
    const [validation, network] = await Promise.all([api.validate(ds), api.network(ds)]);
    if (rev !== state.revision) return; // superseded by a newer edit
    const aside = new Map<string, Set<string>>();
    for (const a of validation.set_aside ?? []) {
      const rec = (ds as unknown as Coll)[a.collection]?.[a.index];
      if (rec === undefined) continue;
      if (!aside.has(a.collection)) aside.set(a.collection, new Set());
      aside.get(a.collection)!.add(JSON.stringify(rec));
    }
    setAside = aside;
    checkedRevision = rev;
    set({ validation, network, schemaErrors: [], engineError: null, checking: false });
  } catch (e) {
    if (rev !== state.revision) return;
    if (e instanceof SchemaRejected) set({ schemaErrors: e.errors, validation: null, checking: false, engineError: null });
    else set({ engineError: String(e), checking: false });
  }
}

function commit(next: Dataset) {
  past.push(state.dataset!);
  if (past.length > HISTORY) past.shift();
  future.length = 0;
  persist(next);
  if (state.version) persistVersion(state.version, true);
  set({ dataset: next, revision: state.revision + 1 });
  scheduleCheck();
}

export const store = {
  get: () => state,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },

  /** Replace the whole dataset (load example, import file, open a version). Clears history and every
   *  result; `version` names the stored version it came from (none for an example or a file). */
  load(ds: Dataset, version: Omit<WorkingVersion, "savedRevision"> | null = null) {
    past.length = 0;
    future.length = 0;
    persist(ds);
    const rev = state.revision + 1;
    const v = version ? { ...version, savedRevision: rev } : null;
    persistVersion(v, false);
    setAside = new Map();
    set({ dataset: ds, version: v, revision: rev, runs: emptyRuns(), validation: null, network: null });
    scheduleCheck();
  },

  /** The working copy was just saved as (or to) this version. */
  saved(version: Omit<WorkingVersion, "savedRevision">) {
    const v = { ...version, savedRevision: state.revision };
    persistVersion(v, false);
    set({ version: v });
  },

  clear() {
    setAside = new Map();
    past.length = 0;
    future.length = 0;
    persist(null);
    persistVersion(null, false);
    set({ dataset: null, version: null, revision: state.revision + 1, runs: emptyRuns(), validation: null, network: null,
      schemaErrors: [] });
  },

  /** Apply an edit to a deep copy of the dataset. */
  update(mutate: (draft: Dataset) => void) {
    if (!state.dataset) return;
    const draft = structuredClone(state.dataset);
    mutate(draft);
    // a no-op edit (e.g. the same value committed on Enter and again on blur) must not create history
    if (JSON.stringify(draft) === JSON.stringify(state.dataset)) return;
    commit(draft);
  },

  /** Replace the dataset with an engine-produced version (e.g. a released forecast), undoable. */
  replace(next: Dataset) {
    if (!state.dataset) return;
    commit(next);
  },

  undo() {
    const prev = past.pop();
    if (!prev || !state.dataset) return;
    future.push(state.dataset);
    persist(prev);
    set({ dataset: prev, revision: state.revision + 1 });
    scheduleCheck();
  },

  redo() {
    const next = future.pop();
    if (!next || !state.dataset) return;
    past.push(state.dataset);
    persist(next);
    set({ dataset: next, revision: state.revision + 1 });
    scheduleCheck();
  },

  async run<K extends RunKey>(key: K) {
    if (!state.dataset) return;
    // plan on what the data check has seen, so unfinished records are set aside and not sent to the engine
    if (checkedRevision !== state.revision) { clearTimeout(timer); await check(); }
    const ds = state.dataset;
    if (!ds) return;
    const rev = state.revision;
    setRun(key, { running: true, error: null });
    try {
      const data = await RUNNERS[key](ds);
      setRun(key, { data, revision: rev, running: false, at: new Date().toLocaleTimeString("en-GB") } as Partial<Run<RunResults[K]>>);
    } catch (e) {
      if (e instanceof SchemaRejected) {
        set({ schemaErrors: e.errors });
        setRun(key, { running: false, error: "The dataset has invalid values." });
      } else setRun(key, { running: false, error: String(e) });
    }
  },

  /** "Plan everything": check the data, then calculate every result in order. Stops at the data check
   *  when something blocks planning; nothing it does changes the dataset. */
  async planAll() {
    if (!state.dataset || state.planning) return;
    const of = PLAN_STEPS.length + 1;
    set({ planning: { done: 0, of, label: "Checking your data" } });
    clearTimeout(timer);
    await check();
    if (!state.dataset || state.engineError || state.schemaErrors.length || !state.validation || state.validation.blocking) {
      set({ planning: null });
      return;
    }
    for (const [i, st] of PLAN_STEPS.entries()) {
      if (!state.dataset) break;
      set({ planning: { done: i + 1, of, label: st.label } });
      await store.run(st.key);
    }
    set({ planning: null });
  },

  /** Store a result computed outside `run` (e.g. a schedule with a hand-edited sequence). */
  put<K extends RunKey>(key: K, data: RunResults[K], rev: number) {
    setRun(key, { data, revision: rev, running: false, error: null, at: new Date().toLocaleTimeString("en-GB") } as Partial<Run<RunResults[K]>>);
  },

  restore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const ds = JSON.parse(raw) as Dataset;
        const rev = state.revision + 1;
        const vr = localStorage.getItem(VERSION_KEY);
        const v = vr ? (JSON.parse(vr) as WorkingVersion & { modified?: boolean }) : null;
        // a reload keeps the link to the stored version; "modified" survives as a revision mismatch
        const version = v ? { id: v.id, name: v.name, kind: v.kind, status: v.status, savedRevision: v.modified ? -1 : rev } : null;
        set({ dataset: ds, version, revision: rev });
        scheduleCheck();
      }
    } catch {
      /* ignore unreadable storage */
    }
  },
};

export function useStore<T>(select: (s: State) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(state));
}

/** A result exists but the dataset changed after it was computed. */
export const isStale = (s: State, key: RunKey) => s.runs[key].data !== null && s.runs[key].revision !== s.revision;

/** Where a result stands: up to date, out of date (the data changed after it ran), or not calculated. */
export type Freshness = "fresh" | "stale" | "none";
export const freshness = (s: State, key: RunKey): Freshness => !s.runs[key].data ? "none" : isStale(s, key) ? "stale" : "fresh";

/** The whole plan's state, for the top bar: "none" until something ran, "stale" when any result is out of date. */
export function planFreshness(s: State): Freshness {
  const f = PLAN_STEPS.map((p) => freshness(s, p.key));
  if (f.every((x) => x === "none")) return "none";
  return f.some((x) => x !== "fresh") ? "stale" : "fresh";
}

/** Stable empty values for selectors: a fresh `[]` per call would re-render forever. */
export const NO_ISSUES: NonNullable<State["validation"]>["issues"] = [];

/** The working copy differs from the stored version it came from. */
export const isModified = (s: State) => s.version !== null && s.version.savedRevision !== s.revision;
