// The client owns the planning dataset (one JSON document). Every edit goes through `update`,
// which bumps the revision, records undo history, persists locally, and schedules a
// re-validation against the engine. Every engine run (forecast, plan, …) remembers the revision it
// was computed on, so the UI can show "stale" the moment any input it reads changes — the legacy STALE
// cascade, done by construction: every result reads the whole dataset except the parts only the shop floor
// schedule reads (its settings and the changeover matrix), which leave the other results fresh.
import { useEffect, useState, useSyncExternalStore } from "react";
import { api, ApiError, SchemaRejected, setAuth, setDataRef, setPlanningView, setWriteGuard, type DataRef } from "../api/client";
import { makePatch, patchIsSmall, type Patch } from "../lib/patch";
import { keepSteps, stepsFor } from "./undoStore";
import type { CompanyDoc, CompanyMeta, PlanTrace, User, ActualsView, PurchasingView, Dataset, FinanceResult, TowerResult, ForecastResult, InventoryResult, NetworkView, PlanResult, PromiseResult, ScheduleResult, SopResult, SchemaError, ValidationResult } from "../api/types";

export interface RunResults {
  forecast: ForecastResult;
  inventory: InventoryResult;
  sop: SopResult;
  plan: PlanResult;
  schedule: ScheduleResult;
  promise: PromiseResult;
  actuals: ActualsView;
  purchasing: PurchasingView;
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
  on?: Dataset | null;       // the working copy it was computed on (a trace of the plan asks about that data)
}

/** The stored version the working copy was opened from or last saved to (P8). */
export interface WorkingVersion {
  id: string;
  name: string;
  kind: string;          // base | scenario
  status: string;
  savedRevision: number; // working-copy revision that equals the stored content
}

/** Signed in to the server (Phase I). */
export interface Session { token: string; user: User }

/** The company kept on the server that the working copy belongs to. `live`: the working copy is the company's
 *  data and is saved to it as you go; not live: a plan version of the company is open instead (saved in Versions). */
export interface OpenCompany {
  id: string;
  name: string;
  role: string;           // owner | planner | viewer
  revision: number;       // the server revision the working copy is based on
  savedRevision: number;  // working-copy revision that equals the server's content
  live: boolean;
  approval?: boolean;     // master-data changes wait for a second person's approval
  pending?: number;       // changes waiting for approval
  places?: string[];      // this person's rights are limited to these places (empty: all)
  families?: string[];    // … and these product groups
}

/** What the company's meta says about approval and one's own limits. */
const fromMeta = (m: CompanyMeta) => ({ approval: !!m.approval, pending: m.pending ?? 0, places: m.places ?? [], families: m.families ?? [] });

/** Where saving stands. "local": no server company, the working copy is kept in this browser only. */
export interface SaveState {
  status: "local" | "pending" | "saving" | "saved" | "failed" | "conflict" | "readonly";
  at: string | null;          // time of the last save
  error: string | null;
  /** Someone else saved after the working copy's revision: who, when, which revision. */
  conflict: { by: string; at: string; revision: number } | null;
  /** A newer save by someone else was seen while nothing here was unsaved. */
  newer: { by: string; at: string; revision: number } | null;
  /** This browser could not keep the working copy (storage full or blocked). */
  localError: string | null;
  /** A viewer tried to change something (time of the last try, to show the notice). */
  refused: number;
  /** A colleague's save was merged in on its own (nothing both changed): what the merge did, in plain words. */
  merged?: string | null;
}

export interface State {
  session: Session | null;
  company: OpenCompany | null;
  save: SaveState;
  dataset: Dataset | null;
  version: WorkingVersion | null;
  revision: number;
  touched: Record<string, number>;   // part of the dataset → the revision it last changed at (see isStale)
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
  { key: "purchasing", label: "Listing what to buy" },
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
  purchasing: api.purchasing,
  finance: api.finance,
  tower: api.tower,
};

const STORAGE_KEY = "scp.dataset.v1";
const VERSION_KEY = "scp.version.v1";
const SESSION_KEY = "scp.session.v1";
const COMPANY_KEY = "scp.company.v1";
const BASE_KEY = "scp.company.base.v2";   // the save the working copy was made from, and its revision: saves send what
                                          // changed since it, and a merge after a conflict needs it
const SAVE_DELAY = 1200;       // save this long after the last change
const RETRY_DELAY = 15_000;    // try a failed save again after this
const CHECK_EVERY = 60_000;    // look for a colleague's newer save this often
const HISTORY = 100;

/** Records in a working copy beyond which this browser keeps no copy of a company the server keeps (Phase S): its
 *  storage holds a few megabytes, a large company is tens, and trying costs seconds on every change. */
const LOCAL_ROWS = 50_000;
export const rowsOf = (ds: Dataset) => Object.values(ds as unknown as Record<string, unknown>)
  .reduce<number>((n, v) => n + (Array.isArray(v) ? v.length : 0), 0);

const emptyRun = <T>(): Run<T> => ({ data: null, revision: null, running: false, error: null, at: null });
const emptyRuns = (): State["runs"] => ({ forecast: emptyRun(), inventory: emptyRun(), sop: emptyRun(), plan: emptyRun(), schedule: emptyRun(), promise: emptyRun(), actuals: emptyRun(), purchasing: emptyRun(), finance: emptyRun(), tower: emptyRun() });

const localSave = (): SaveState => ({ status: "local", at: null, error: null, conflict: null, newer: null, localError: null, refused: 0 });

let state: State = {
  session: null, company: null, save: localSave(),
  dataset: null, version: null, revision: 0, touched: {}, validation: null, schemaErrors: [], network: null, runs: emptyRuns(),
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
/** Counts datasets replaced whole (a company opened, a file or version loaded, closed): a result asked for before
 *  belongs to the data that was there, and is dropped when it arrives; a "Plan everything" of it stops. */
let loadEpoch = 0;
let planningEpoch = -1;
let planQueued = false;

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
    restore: (next, only) => {
      const put = only ? dropped.filter(([coll]) => only.includes(coll)) : dropped;
      if (!put.length) return next;
      const back = { ...next } as unknown as Coll;
      for (const [coll, recs] of put) back[coll] = [...(back[coll] ?? []), ...recs];
      return back as unknown as Dataset;
    },
  };
});

/** True while the undo steps kept for the reloaded working copy are read back (nothing is kept over them meanwhile). */
let restoringSteps = false;

function set(patch: Partial<State>) {
  state = { ...state, ...patch, canUndo: past.length > 0, canRedo: future.length > 0 };
  // undo survives a reload (R19); not for a company too large to keep here (thirty steps of it would be gigabytes)
  if ("dataset" in patch && !restoringSteps) keepSteps(() => state.dataset && rowsOf(state.dataset) > LOCAL_ROWS ? [null, [], []] : [state.dataset, past, future]);
  listeners.forEach((l) => l());
}

function setRun<K extends RunKey>(key: K, patch: Partial<Run<RunResults[K]>>) {
  set({ runs: { ...state.runs, [key]: { ...state.runs[key], ...patch } } });
}

function persist(ds: Dataset | null, live = !!state.company?.live) {
  try {
    if (ds && live && rowsOf(ds) > LOCAL_ROWS) {
      // the server keeps it; a reload opens it from there (restore)
      localStorage.removeItem(STORAGE_KEY);
      if (state.save.localError) set({ save: { ...state.save, localError: null } });
      return;
    }
    if (ds) localStorage.setItem(STORAGE_KEY, JSON.stringify(ds));
    else localStorage.removeItem(STORAGE_KEY);
    if (state.save.localError) set({ save: { ...state.save, localError: null } });
  } catch (e) {
    // storage unavailable (private mode, quota): the app still works in memory, but say so: a company that exists
    // only in this browser is lost on closing it. On the server the company is safe; the local copy is a cache.
    const full = e instanceof DOMException && (e.name === "QuotaExceededError" || e.code === 22);
    const localError = full ? "This browser's storage is full: the latest changes are not kept here"
      : "This browser does not let the app keep data: changes are lost when the page closes";
    if (state.save.localError !== localError) set({ save: { ...state.save, localError } });
  }
}

function persistCompany() {
  try {
    const c = state.company;
    if (c) localStorage.setItem(COMPANY_KEY, JSON.stringify({ ...c, dirty: c.savedRevision !== state.revision }));
    else localStorage.removeItem(COMPANY_KEY);
  } catch {
    /* ignore */
  }
}

function persistSession() {
  try {
    if (state.session) localStorage.setItem(SESSION_KEY, JSON.stringify(state.session));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}

setAuth(() => ({ token: state.session?.token ?? null, company: state.company?.id ?? null }));
setWriteGuard(() => state.company && state.company.role === "viewer"
  ? `Nothing was changed: you are a viewer of ${state.company.name}. Ask an owner to make you a planner to change it.` : null);

/** The server company's save the working copy was made from, and its revision: a save sends only what changed
 *  since it (N64), and merging after a conflict needs it. */
let baseDoc: Dataset | null = null;
let baseRev = -1;
function setBase(ds: Dataset | null, rev = -1) {
  baseDoc = ds;
  baseRev = ds ? rev : -1;
  try {
    if (ds && rowsOf(ds) > LOCAL_ROWS) localStorage.removeItem(BASE_KEY);   // kept in memory only (see persist)
    else if (ds) localStorage.setItem(BASE_KEY, JSON.stringify({ revision: baseRev, dataset: ds }));
    else localStorage.removeItem(BASE_KEY);
  } catch {
    /* the next save then sends the whole company, and merging asks the server for the base */
  }
}

/** The working copy as the planning calls send it (Phase S): the server's save it was made from and what changed
 *  since, when the server keeps the company and this browser has that save; worked out once per edit. */
let refMemo: { ds: Dataset; rev: number; ref: DataRef } | null = null;
/** References made for earlier working copies: a result computed on one (the plan on screen, out of date) is asked
 *  about with the same reference, so the server answers from what it kept instead of working it out again. */
const refsMade = new WeakMap<Dataset, DataRef>();
/** The server did not take a reference on this save (its copy differed): send the company whole until the next. */
let refUnfitAt = -2;
setDataRef((ds) => {
  const c = state.company;
  if (!c?.live || !state.session) return null;
  if (ds !== state.dataset) return refsMade.get(ds) ?? null;
  if (!baseDoc || baseRev !== c.revision || refUnfitAt === baseRev) return null;
  if (refMemo && refMemo.ds === ds && refMemo.rev === baseRev) return refMemo.ref;
  let patch: Patch | null = null;
  if (baseDoc !== ds) {
    patch = makePatch(baseDoc as unknown as Record<string, unknown>, ds as unknown as Record<string, unknown>);
    if (!patch.lists && !patch.set && !patch.drop) patch = null;
  }
  refMemo = { ds, rev: baseRev, ref: { revision: baseRev, patch } };
  refsMade.set(ds, refMemo.ref);
  return refMemo.ref;
}, () => { refUnfitAt = baseRev; refMemo = null; });

/** What a save sends: the changes since the save it was made from when that is known and they are small, else the
 *  whole working copy. */
function whatToSend(c: OpenCompany, ds: Dataset): { dataset: Dataset } | { patch: ReturnType<typeof makePatch> } {
  if (!baseDoc || baseRev !== c.revision) return { dataset: ds };
  const patch = makePatch(baseDoc as unknown as Record<string, unknown>, ds as unknown as Record<string, unknown>);
  return patchIsSmall(patch, ds as unknown as Record<string, unknown>) ? { patch } : { dataset: ds };
}

const now = () => new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const canEdit = (c: OpenCompany | null) => !c || c.role !== "viewer";
/** The working copy has changes the server does not have yet. */
export const unsaved = (s: State) => !!s.company?.live && s.company.savedRevision !== s.revision;

let saveTimer: ReturnType<typeof setTimeout> | undefined;
let saving: Promise<void> | null = null;

/** Save the working copy to the server company shortly (autosave). */
function scheduleSave(delay = SAVE_DELAY) {
  const c = state.company;
  if (!c?.live || !canEdit(c) || !state.session || state.save.status === "conflict") return;
  clearTimeout(saveTimer);
  if (state.save.status !== "saving") set({ save: { ...state.save, status: "pending", error: null } });
  saveTimer = setTimeout(() => { void saveNow(); }, delay);
}

async function saveNow(note = ""): Promise<void> {
  clearTimeout(saveTimer);
  if (saving) { await saving; if (unsaved(state)) scheduleSave(200); return; }
  const c = state.company;
  const ds = state.dataset;
  if (!c?.live || !ds || !state.session || !canEdit(c) || state.save.status === "conflict") return;
  if (c.savedRevision === state.revision) { set({ save: { ...state.save, status: "saved" } }); return; }
  const rev = state.revision;
  set({ save: { ...state.save, status: "saving", error: null } });
  saving = (async () => {
    try {
      const what = whatToSend(c, ds);
      const r = await api.saveCompany(c.id, what, c.revision, note).catch((e) => {
        // the changes did not fit the server's copy (it was not the save this copy was made from): send it whole
        if ("patch" in what && e instanceof ApiError && e.status === 409 && e.body.patch === "unfit") {
          return api.saveCompany(c.id, { dataset: ds }, c.revision, note);
        }
        throw e;
      });
      if (state.company?.id !== c.id) return;
      if (r.held && r.dataset) {
        // master data waits for approval: the server kept the rest; carry on from what it saved
        if (state.revision === rev) adopt(r.dataset as unknown as Dataset, r.meta, heldNote(r.held.summary));
        else { setBase(r.dataset as unknown as Dataset, r.meta.revision); set({ company: { ...state.company, revision: r.meta.revision, ...fromMeta(r.meta) },
          save: { ...state.save, status: "saved", at: now(), merged: heldNote(r.held.summary) } }); }
        return;
      }
      setBase(ds, r.meta.revision);
      set({ company: { ...state.company, revision: r.meta.revision, name: r.meta.name, role: r.meta.role, savedRevision: rev, ...fromMeta(r.meta) },
        save: { ...state.save, status: "saved", at: now(), error: null, newer: null } });
      persistCompany();
    } catch (e) {
      if (state.company?.id !== c.id) return;
      if (e instanceof ApiError && e.status === 409 && typeof e.body.revision === "number") {
        if (await mergeQuietly(c, ds, rev)) return;
        set({ save: { ...state.save, status: "conflict", error: e.message, newer: null,
          conflict: { by: e.body.self ? "You (in another window)" : String(e.body.updated_by ?? "someone"),
            at: String(e.body.updated_at ?? ""), revision: e.body.revision } } });
      } else if (e instanceof ApiError && e.status === 401) {
        set({ save: { ...state.save, status: "failed", error: "Your sign-in has expired: sign in again to save" } });
      } else if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
        set({ save: { ...state.save, status: "failed", error: e.message } });
      } else {
        set({ save: { ...state.save, status: "failed", error: "The server could not be reached; trying again shortly" } });
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => { void saveNow(); }, RETRY_DELAY);
      }
    }
  })();
  await saving;
  saving = null;
  if (state.save.status === "saved" && unsaved(state)) scheduleSave(200);
}

/** A merge needs the save the working copy was made from; one saved before every save was kept may be gone. */
function noBase(e: unknown): never {
  if (e instanceof ApiError && e.status === 409 && e.body.base === "missing") {
    throw new Error(`The save your changes were made from is no longer kept, so they cannot be merged: download them, open ${state.save.conflict?.by ?? "the latest"} save, and make them again`);
  }
  throw e;
}

/** A save refused because a colleague saved first: merge the two when no record was changed by both (the server
 *  refuses otherwise, and the planner chooses), save that, and carry on from it. Edits made while the merge ran are
 *  merged onto its result the same way. False when it could not merge. */
async function mergeQuietly(c: OpenCompany, ds: Dataset, rev: number): Promise<boolean> {
  try {
    let base: Dataset | undefined = baseDoc && baseRev === c.revision ? baseDoc : undefined;
    let mine = ds, mineRev = rev;
    // only what changed goes when the server has the save it was made from (it keeps every save)
    let r = await mergeOnServer(c, base, mine, c.revision, { cleanOnly: true });
    for (let i = 0; i < 3 && state.company?.id === c.id && state.revision !== mineRev; i++) {
      base = mine; mine = state.dataset!; mineRev = state.revision;
      r = await api.mergeCompany(c.id, { base, dataset: mine, baseRevision: c.revision, cleanOnly: true });
    }
    if (state.company?.id !== c.id) return true;
    if (state.revision !== mineRev) return false;
    const rep = r.report;
    const note = r.merged_with === "you"
      ? "You saved this company from another window too; both are kept, and where both changed a record your later change is."
      : [`${r.merged_with || "Someone"} saved while you were working; both sets of changes are kept (${rep.summary}).`,
        rep.renumbered.length ? `Renumbered: ${rep.renumbered.join(", ")}.` : ""].filter(Boolean).join(" ");
    // undo would bring back a copy without the colleague's changes, and autosave would then undo them on the server
    adopt(r.dataset as unknown as Dataset, r.meta, r.held ? `${note} ${heldNote(r.held.summary)}` : note);
    return true;
  } catch {
    return false;
  }
}

/** Take the company as the server saved it as the working copy (it differs from what was sent: a merge, or master
 *  data held for approval), with a note for the planner. Undo is cleared: it would bring back a copy without it. */
function adopt(ds: Dataset, meta: CompanyMeta, note: string | null) {
  past.length = 0;
  future.length = 0;
  setBase(ds, meta.revision);
  persist(ds);
  advance(ds);
  set({ company: { ...state.company!, revision: meta.revision, savedRevision: state.revision, ...fromMeta(meta) },
    save: { ...state.save, status: "saved", at: now(), error: null, conflict: null, newer: null, merged: note } });
  persistCompany();
  scheduleCheck();
}

const heldNote = (summary: string) => `Your master data change (${summary}) waits for a second person's approval (History → Waiting for approval); until then the company keeps what it had.`;

/** Merge on the server: the working copy as what changed since `base` (the save it was made from) when the server
 *  keeps that save, else whole with its base. */
async function mergeOnServer(c: OpenCompany, base: Dataset | undefined, mine: Dataset, baseRevision: number,
  o: { cleanOnly?: boolean; choose?: Record<string, "mine" | "theirs">; preview?: boolean }) {
  if (base) {
    try {
      return await api.mergeCompany(c.id, { patch: makePatch(base as unknown as Record<string, unknown>, mine as unknown as Record<string, unknown>),
        baseRevision, ...o });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409 && (e.body.patch === "unfit" || e.body.base === "missing"))) throw e;
      return api.mergeCompany(c.id, { base, dataset: mine, baseRevision, ...o });
    }
  }
  return api.mergeCompany(c.id, { dataset: mine, baseRevision, ...o });   // the server finds the base itself
}

/** Look for a colleague's newer save of the open company. */
async function checkNewer() {
  const c = state.company;
  if (!c?.live || !state.session || document.hidden) return;
  try {
    const m = (await api.companies()).find((x) => x.id === c.id);
    if (!m || state.company?.id !== c.id) return;
    if (m.role !== state.company.role || (m.pending ?? 0) !== (state.company.pending ?? 0) || !!m.approval !== !!state.company.approval) {
      set({ company: { ...state.company, role: m.role, ...fromMeta(m) } });
    }
    if (m.revision > state.company.revision && !saving) {
      // a viewer has nothing of their own to lose: show them the latest plan, not the one they opened
      if (m.role === "viewer") {
        const doc = await api.company(c.id);
        if (state.company?.id === c.id && state.company.role === "viewer") store.openCompany(doc);
        return;
      }
      const newer = { by: m.updated_by, at: m.updated_at, revision: m.revision };
      // nothing unsaved here: nothing to lose, but say so rather than change the page under the planner's hands
      if (!unsaved(state)) set({ save: { ...state.save, newer } });
    }
  } catch {
    /* offline: the next save says so */
  }
}
setInterval(() => { void checkNewer(); }, CHECK_EVERY);
if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", (e) => {
    if (unsaved(state) && canEdit(state.company)) { void saveNow(); e.preventDefault(); }
  });
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

/** Parts of the dataset only the shop floor schedule reads (the day start hour is read by the plan and promising too). */
const SCHEDULE_ONLY = new Set(["scheduling", "changeovers"]);

/** The parts of the dataset an edit changed: top-level collections, with the day start hour on its own. */
function changedParts(a: Dataset | null, b: Dataset): string[] {
  if (!a) return ["*"];
  const x = a as unknown as Record<string, unknown>, y = b as unknown as Record<string, unknown>;
  const out = [...new Set([...Object.keys(x), ...Object.keys(y)])].filter((k) => x[k] !== y[k] && JSON.stringify(x[k]) !== JSON.stringify(y[k]));
  if (a.scheduling?.day_start_hour !== b.scheduling?.day_start_hour) out.push("scheduling.day_start_hour");
  return out;
}

/** Move to another dataset: bump the revision and note which parts changed at it. */
function advance(next: Dataset) {
  const rev = state.revision + 1;
  const touched = { ...state.touched };
  for (const k of changedParts(state.dataset, next)) touched[k] = rev;
  set({ dataset: next, revision: rev, touched });
}

/** A viewer of a server company cannot change it: nothing is changed, and the page says why. */
function refused(): boolean {
  if (canEdit(state.company)) return false;
  set({ save: { ...state.save, refused: Date.now() } });
  return true;
}

function commit(next: Dataset) {
  if (refused()) return;
  past.push(state.dataset!);
  if (past.length > HISTORY) past.shift();
  future.length = 0;
  persist(next);
  if (state.version) persistVersion(state.version, true);
  advance(next);
  persistCompany();
  scheduleCheck();
  scheduleSave();
}

export const store = {
  get: () => state,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },

  /** Replace the whole dataset (load example, import file, open a version). Clears history and every
   *  result; `version` names the stored version it came from (none for an example or a file). An example, a file
   *  or a blank company leaves the open server company (the working copy is then this browser's own); a plan
   *  version of the open company keeps it, but is not its live data. */
  load(ds: Dataset, version: Omit<WorkingVersion, "savedRevision"> | null = null) {
    loadEpoch++;
    past.length = 0;
    future.length = 0;
    persist(ds);
    const rev = state.revision + 1;
    const v = version ? { ...version, savedRevision: rev } : null;
    persistVersion(v, false);
    setAside = new Map();
    clearTimeout(saveTimer);
    const company = state.company && version ? { ...state.company, live: false } : null;
    if (!company) setBase(null);
    set({ dataset: ds, version: v, revision: rev, runs: emptyRuns(), validation: null, network: null, company,
      save: company ? { ...state.save, status: "saved", conflict: null, newer: null } : { ...localSave(), localError: state.save.localError } });
    persistCompany();
    scheduleCheck();
  },

  // ---- sign-in and the company on the server (Phase I) --------------------------------------------------------
  signedIn(session: Session) {
    set({ session });
    persistSession();
    if (state.company?.live && unsaved(state)) scheduleSave(100);
  },

  /** Sign out. The company open from the server is closed on this browser (it stays on the server). */
  async signOut() {
    try { await api.signOut(); } catch { /* signed out here anyway */ }
    if (state.company) store.clear();
    set({ session: null });
    persistSession();
  },

  /** Open a company kept on the server: its latest save becomes the working copy. */
  openCompany(doc: CompanyDoc) {
    loadEpoch++;
    past.length = 0;
    future.length = 0;
    const ds = doc.dataset as unknown as Dataset;
    persist(ds, true);
    persistVersion(null, false);
    const rev = state.revision + 1;
    setAside = new Map();
    clearTimeout(saveTimer);
    const m = doc.meta;
    setBase(ds, m.revision);
    set({ dataset: ds, version: null, revision: rev, runs: emptyRuns(), validation: null, network: null,
      company: { id: m.id, name: m.name, role: m.role, revision: m.revision, savedRevision: rev, live: true, ...fromMeta(m) },
      save: { ...localSave(), status: m.role === "viewer" ? "readonly" : "saved", at: null, localError: state.save.localError } });
    persistCompany();
    scheduleCheck();
    setTimeout(() => { void store.planAll(); }, 0);   // no page opens empty
  },

  /** The server saved the company differently from this working copy (an approval made here): carry on from it. */
  async adoptServerSave(meta: CompanyMeta, ds: Record<string, unknown>) {
    if (!state.company || state.company.id !== meta.id) return;
    if (unsaved(state)) await saveNow();
    if (unsaved(state)) return;          // not saved here: the next check shows the newer save instead
    adopt(ds as unknown as Dataset, meta, null);
  },

  /** What a company's meta says now (approval, changes waiting). */
  noteCompany(meta: CompanyMeta) {
    if (state.company?.id === meta.id) set({ company: { ...state.company, ...fromMeta(meta) } });
  },

  /** The planner has read what an automatic merge did. */
  clearMerged() { if (state.save.merged) set({ save: { ...state.save, merged: null } }); },

  /** Save now (and wait): before signing out, or when the planner asks. */
  saveNow: (note = "") => saveNow(note),

  /** After a conflict: save the working copy over the colleague's save (theirs stays in the history). */
  async keepMine() {
    const c = state.company;
    const x = state.save.conflict;
    if (!c || !x) return;
    set({ company: { ...c, revision: x.revision }, save: { ...state.save, status: "pending", conflict: null, error: null } });
    await saveNow(`kept over ${x.by}'s save`);
  },

  /** After a conflict: what merging would do, without saving: each record both changed, side by side (N65). */
  async previewMerge() {
    const c = state.company;
    const ds = state.dataset;
    if (!c || !ds) throw new Error("Nothing to merge");
    return (await mergeOnServer(c, baseDoc && baseRev === c.revision ? baseDoc : undefined, ds, c.revision, { preview: true })
      .catch(noBase)).report;
  },

  /** After a conflict: merge the working copy with the saves made since, record by record (a record both changed
   *  keeps the version `choose` names, else theirs), and open the result. Returns what the merge did, in plain words. */
  async mergeMine(choose: Record<string, "mine" | "theirs"> = {}): Promise<string> {
    const c = state.company;
    const ds = state.dataset;
    if (!c || !ds) throw new Error("Nothing to merge");
    const r = await mergeOnServer(c, baseDoc && baseRev === c.revision ? baseDoc : undefined, ds, c.revision, { choose }).catch(noBase);
    store.openCompany({ meta: r.meta, dataset: r.dataset });
    set({ save: { ...state.save, status: "saved", at: now() } });
    const rep = r.report;
    const lines = [`Merged with ${r.merged_with || "the latest save"}: ${rep.summary}.`];
    const named = (x: { list: string; record: string }) => `${x.list}${x.record ? ` ${x.record.replace(/ \| /g, " · ").replace(/_/g, " ")}` : ""}`;
    const theirs = (rep.clashes ?? []).filter((x) => x.kept === "theirs").map(named);
    const mine = (rep.clashes ?? []).filter((x) => x.kept === "mine").map(named);
    const few = (xs: string[]) => `${xs.slice(0, 6).join("; ")}${xs.length > 6 ? "; …" : ""}`;
    if (theirs.length) lines.push(`Changed on both sides, their version kept: ${few(theirs)}.`);
    if (mine.length) lines.push(`Changed on both sides, your version kept: ${few(mine)}.`);
    return lines.join(" ");
  },

  /** The working copy was a plan version of the open company: make it the company's live data again. */
  useAsCompanyData(latestRevision: number, note: string) {
    const c = state.company;
    if (!c || !state.dataset || refused()) return;
    persistVersion(null, false);
    set({ company: { ...c, live: true, revision: latestRevision, savedRevision: -1 }, version: null,
      save: { ...state.save, status: "pending", conflict: null, newer: null } });
    persistCompany();
    void saveNow(note);
  },

  /** The working copy was just saved as (or to) this version. */
  saved(version: Omit<WorkingVersion, "savedRevision">) {
    const v = { ...version, savedRevision: state.revision };
    persistVersion(v, false);
    set({ version: v });
  },

  clear() {
    loadEpoch++;
    clearTimeout(saveTimer);
    setAside = new Map();
    past.length = 0;
    future.length = 0;
    persist(null);
    persistVersion(null, false);
    set({ dataset: null, version: null, revision: state.revision + 1, runs: emptyRuns(), validation: null, network: null,
      schemaErrors: [], company: null, save: localSave() });
    persistCompany();
    setBase(null);
  },

  /** Apply an edit to a deep copy of the dataset. */
  update(mutate: (draft: Dataset) => void) {
    if (!state.dataset) return;
    // the edit gets a copy of each part it reads or writes, the rest stays shared: a large company's two years of
    // sales history are not copied, nor compared, for a change to one product (Phase S)
    const base = state.dataset as unknown as Record<string, unknown>;
    const next: Record<string, unknown> = { ...base };
    const parts = new Set<string>();
    const draft = new Proxy(next, {
      get(t, k) {
        if (typeof k === "string" && !parts.has(k) && k in base) {
          parts.add(k);
          if (base[k] !== null && typeof base[k] === "object") t[k] = structuredClone(base[k]);
        }
        return Reflect.get(t, k);
      },
      set(t, k, v) { if (typeof k === "string") parts.add(k); return Reflect.set(t, k, v); },
      deleteProperty(t, k) { if (typeof k === "string") parts.add(k); return Reflect.deleteProperty(t, k); },
    });
    mutate(draft as unknown as Dataset);
    // a part read but not changed keeps the one it was; a no-op edit (the same value committed on Enter and again on
    // blur) must not create history
    let changed = false;
    for (const k of parts) {
      if (k in base && k in next && JSON.stringify(next[k]) === JSON.stringify(base[k])) next[k] = base[k];
      else changed = true;
    }
    if (!changed) return;
    commit(next as unknown as Dataset);
  },

  /** Replace the dataset with an engine-produced version (e.g. a released forecast), undoable. */
  replace(next: Dataset) {
    if (!state.dataset) return;
    commit(next);
  },

  undo() {
    if (!state.dataset || !past.length || refused()) return;
    const prev = past.pop()!;
    future.push(state.dataset);
    persist(prev);
    advance(prev);
    persistCompany();
    scheduleCheck();
    scheduleSave();
  },

  redo() {
    if (!state.dataset || !future.length || refused()) return;
    const next = future.pop()!;
    past.push(state.dataset);
    persist(next);
    advance(next);
    persistCompany();
    scheduleCheck();
    scheduleSave();
  },

  async run<K extends RunKey>(key: K) {
    if (!state.dataset) return;
    // plan on what the data check has seen, so unfinished records are set aside and not sent to the engine
    if (checkedRevision !== state.revision) { clearTimeout(timer); await check(); }
    const ds = state.dataset;
    if (!ds) return;
    const rev = state.revision;
    const epoch = loadEpoch;
    setRun(key, { running: true, error: null });
    try {
      const data = await RUNNERS[key](ds);
      if (epoch !== loadEpoch) return;   // another company or file was opened meanwhile
      setRun(key, { data, revision: rev, on: ds, running: false, at: new Date().toLocaleTimeString("en-GB") } as Partial<Run<RunResults[K]>>);
    } catch (e) {
      if (epoch !== loadEpoch) return;
      if (e instanceof SchemaRejected) {
        set({ schemaErrors: e.errors });
        setRun(key, { running: false, error: "The dataset has invalid values." });
      } else setRun(key, { running: false, error: String(e) });
    }
  },

  /** "Plan everything": check the data, then calculate every result in order. Stops at the data check
   *  when something blocks planning; nothing it does changes the dataset. */
  async planAll() {
    if (!state.dataset) return;
    if (state.planning) {
      // still planning what was open before: stop that at its next step and plan this instead
      if (planningEpoch !== loadEpoch) planQueued = true;
      return;
    }
    const epoch = planningEpoch = loadEpoch;
    const of = PLAN_STEPS.length + 1;
    const done = () => {
      set({ planning: null });
      if (planQueued) { planQueued = false; void store.planAll(); }
    };
    set({ planning: { done: 0, of, label: "Checking your data" } });
    clearTimeout(timer);
    await check();
    if (epoch !== loadEpoch || !state.dataset || state.engineError || state.schemaErrors.length || !state.validation
        || state.validation.blocking) {
      done();
      return;
    }
    for (const [i, st] of PLAN_STEPS.entries()) {
      if (!state.dataset || epoch !== loadEpoch) break;
      set({ planning: { done: i + 1, of, label: st.label } });
      await store.run(st.key);
    }
    done();
  },

  /** Store a result computed outside `run` (e.g. a schedule with a hand-edited sequence). */
  put<K extends RunKey>(key: K, data: RunResults[K], rev: number) {
    setRun(key, { data, revision: rev, on: rev === state.revision ? state.dataset : null, running: false, error: null,
      at: new Date().toLocaleTimeString("en-GB") } as Partial<Run<RunResults[K]>>);
  },

  restore() {
    try {
      const sr = localStorage.getItem(SESSION_KEY);
      if (sr) set({ session: JSON.parse(sr) as Session });
    } catch {
      /* ignore */
    }
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw && state.session) {
        // a company too large to keep in this browser (persist): open its latest save from the server
        const cr = localStorage.getItem(COMPANY_KEY);
        const c = cr ? (JSON.parse(cr) as OpenCompany) : null;
        if (c?.live) void api.company(c.id).then((doc) => { if (!state.dataset) store.openCompany(doc); }, () => { /* opened by hand */ });
      }
      if (raw) {
        const ds = JSON.parse(raw) as Dataset;
        const rev = state.revision + 1;
        const vr = localStorage.getItem(VERSION_KEY);
        const v = vr ? (JSON.parse(vr) as WorkingVersion & { modified?: boolean }) : null;
        // a reload keeps the link to the stored version; "modified" survives as a revision mismatch
        const version = v ? { id: v.id, name: v.name, kind: v.kind, status: v.status, savedRevision: v.modified ? -1 : rev } : null;
        restoringSteps = true;
        set({ dataset: ds, version, revision: rev });
        // the undo steps kept for exactly this working copy come back with it
        void stepsFor(ds).then((st) => {
          restoringSteps = false;
          if (!st || state.dataset !== ds || past.length || future.length) return;
          past.push(...(st.past as Dataset[]));
          future.push(...(st.future as Dataset[]));
          set({});
        });
        const cr = localStorage.getItem(COMPANY_KEY);
        const c = cr && state.session ? (JSON.parse(cr) as OpenCompany & { dirty?: boolean }) : null;
        if (c) {
          try {
            const br = localStorage.getItem(BASE_KEY);
            const b = br ? (JSON.parse(br) as { revision: number; dataset: Dataset }) : null;
            baseDoc = b?.dataset ?? null;
            baseRev = b?.revision ?? -1;
          } catch { baseDoc = null; baseRev = -1; }
          set({ company: { id: c.id, name: c.name, role: c.role, revision: c.revision, live: c.live, savedRevision: c.dirty ? -1 : rev },
            save: { ...localSave(), status: c.role === "viewer" ? "readonly" : c.dirty ? "pending" : "saved" } });
          void store.refreshCompany();
        }
        scheduleCheck();
      }
    } catch {
      /* ignore unreadable storage */
    }
  },

  /** After a reload: open the company's latest save when nothing here is unsaved, else save what is. */
  async refreshCompany() {
    const c = state.company;
    if (!c || !state.session) return;
    if (!c.live) return;
    if (unsaved(state)) { scheduleSave(100); return; }
    try {
      const doc = await api.company(c.id);
      if (state.company?.id !== c.id || unsaved(state)) return;
      if (doc.meta.revision !== c.revision) store.openCompany(doc);
      else {
        setBase(doc.dataset as unknown as Dataset, doc.meta.revision);
        set({ company: { ...state.company, role: doc.meta.role, name: doc.meta.name } });
      }
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 404)) {
        set({ save: { ...state.save, status: "failed", error: e.status === 401 ? "Your sign-in has expired: sign in again to save"
          : `${c.name} is no longer yours to open: it was deleted or you were removed from it` } });
      }
    }
  },
};

export function useStore<T>(select: (s: State) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(state));
}

/** Part of the plan's requirements and pegging (Phase S: the plan comes without them): an order's chain, or one
 *  product's at one place, asked about the data the plan on screen was computed on. `data` is null while it comes. */
export function usePlanTrace(what: { order: string } | { location: string; product: string } | null) {
  const run = useStore((s) => s.runs.plan);
  const key = what && run.data ? `${JSON.stringify(what)}@${run.revision}` : "";
  const [got, setGot] = useState<{ key: string; data: PlanTrace | null; error: string | null }>({ key: "", data: null, error: null });
  useEffect(() => {
    const on = run.on ?? state.dataset;
    if (!key || !what || !on) return;
    let live = true;
    api.planTrace(on, what).then((data) => { if (live) setGot({ key, data, error: null }); },
      (e) => { if (live) setGot({ key, data: null, error: String(e) }); });
    return () => { live = false; };
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  return got.key === key ? got : { key, data: null, error: null };
}

/** A viewer of the open company: controls that change data are shown disabled (N62). */
export const useReadOnly = () => useStore((s) => s.company?.role === "viewer" && s.company.live);

/** Results that take a moment to rebuild: a page showing one calculates it when it opens out of date (N56) or not
 * calculated at all (N71, e.g. after reopening the browser), instead of showing the earlier result behind an "out of
 * date" mark, or an empty page waiting for *Calculate*. */
const QUICK: ReadonlySet<RunKey> = new Set<RunKey>(["actuals", "purchasing", "finance", "promise"]);

export function useFreshResult(key: RunKey) {
  useEffect(() => {
    const r = state.runs[key];
    if (!QUICK.has(key) || r.running || r.error || !state.dataset) return;
    const missing = r.data === null && !state.schemaErrors.length && !state.validation?.blocking;
    if (missing || isStale(state, key)) void store.run(key);
  }, [key]);   // on opening the page only: edits made on it keep their "out of date" mark until recalculated
}

/** A result exists but a part of the dataset it reads changed after it was computed. */
export function isStale(s: State, key: RunKey): boolean {
  const run = s.runs[key];
  if (run.data === null || run.revision === s.revision) return false;
  const since = run.revision ?? -1;
  return Object.entries(s.touched).some(([part, rev]) => rev > since && (key === "schedule" || !SCHEDULE_ONLY.has(part)));
}

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
