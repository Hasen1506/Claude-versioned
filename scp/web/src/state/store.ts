// The client owns the planning dataset (one JSON document). Every edit goes through `update`,
// which bumps the revision, records undo history, persists locally, and schedules a
// re-validation against the engine. A plan remembers the revision it was computed on, so the UI
// can show "stale" the moment any input changes (the legacy STALE cascade, done by construction).
import { useSyncExternalStore } from "react";
import { api, SchemaRejected } from "../api/client";
import type { Dataset, NetworkView, PlanResult, SchemaError, ValidationResult } from "../api/types";

export interface State {
  dataset: Dataset | null;
  revision: number;
  validation: ValidationResult | null;
  schemaErrors: SchemaError[];
  network: NetworkView | null;
  plan: PlanResult | null;
  planRevision: number | null;
  planning: boolean;
  checking: boolean;
  engineError: string | null;
  canUndo: boolean;
  canRedo: boolean;
}

const STORAGE_KEY = "scp.dataset.v1";
const HISTORY = 100;

let state: State = {
  dataset: null, revision: 0, validation: null, schemaErrors: [], network: null, plan: null,
  planRevision: null, planning: false, checking: false, engineError: null, canUndo: false, canRedo: false,
};
const listeners = new Set<() => void>();
const past: Dataset[] = [];
const future: Dataset[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;

function set(patch: Partial<State>) {
  state = { ...state, ...patch, canUndo: past.length > 0, canRedo: future.length > 0 };
  listeners.forEach((l) => l());
}

function persist(ds: Dataset | null) {
  try {
    if (ds) localStorage.setItem(STORAGE_KEY, JSON.stringify(ds));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode, quota) — the app still works in memory */
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
    set({ validation, network, schemaErrors: [], engineError: null, checking: false });
  } catch (e) {
    if (rev !== state.revision) return;
    if (e instanceof SchemaRejected) set({ schemaErrors: e.errors, validation: null, checking: false, engineError: null });
    else set({ engineError: String(e), checking: false });
  }
}

export const store = {
  get: () => state,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },

  /** Replace the whole dataset (load example, import file). Clears history and the plan. */
  load(ds: Dataset) {
    past.length = 0;
    future.length = 0;
    persist(ds);
    set({ dataset: ds, revision: state.revision + 1, plan: null, planRevision: null, validation: null, network: null });
    scheduleCheck();
  },

  clear() {
    past.length = 0;
    future.length = 0;
    persist(null);
    set({ dataset: null, revision: state.revision + 1, plan: null, planRevision: null, validation: null, network: null,
      schemaErrors: [] });
  },

  /** Apply an edit to a deep copy of the dataset. */
  update(mutate: (draft: Dataset) => void) {
    if (!state.dataset) return;
    const draft = structuredClone(state.dataset);
    mutate(draft);
    // a no-op edit (e.g. the same value committed on Enter and again on blur) must not create history
    if (JSON.stringify(draft) === JSON.stringify(state.dataset)) return;
    past.push(state.dataset);
    if (past.length > HISTORY) past.shift();
    future.length = 0;
    persist(draft);
    set({ dataset: draft, revision: state.revision + 1 });
    scheduleCheck();
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

  async runPlan() {
    const ds = state.dataset;
    if (!ds) return;
    const rev = state.revision;
    set({ planning: true, engineError: null });
    try {
      const plan = await api.plan(ds);
      set({ plan, planRevision: rev, planning: false });
    } catch (e) {
      if (e instanceof SchemaRejected) set({ schemaErrors: e.errors, planning: false });
      else set({ engineError: String(e), planning: false });
    }
  },

  restore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const ds = JSON.parse(raw) as Dataset;
        set({ dataset: ds, revision: state.revision + 1 });
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

export const planIsStale = (s: State) => s.plan !== null && s.planRevision !== s.revision;

/** Stable empty values for selectors: a fresh `[]` per call would re-render forever. */
export const NO_ISSUES: NonNullable<State["validation"]>["issues"] = [];
