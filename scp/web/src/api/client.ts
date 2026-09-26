import type {
  Comparison, FinanceResult, TowerResult, WorkItem, WorkItemEntry, VersionDoc, VersionMeta, ActualsView, FirmResponse, RollResponse, Dataset, DemandRecord, ExampleInfo, ForecastModels, ForecastResult, InventoryResult, PlacementResponse, PromiseCommitResponse, PromiseResult, ScheduleResult, SopReleaseResponse, SopResult, NetworkView, PlanResult, ReleaseResponse, RuleInfo,
  ScenarioInfo, ScenarioReport, SchemaError, ValidationResult,
} from "./types";

/** Thrown when the engine rejects the dataset shape (HTTP 422). Carries field-level errors. */
export class SchemaRejected extends Error {
  constructor(public errors: SchemaError[]) {
    super(`${errors.length} schema error(s)`);
  }
}

const API_ORIGIN = import.meta.env.VITE_API_ORIGIN || "";
/** A proof run answers only when it is done; on a small server the generated flow takes minutes. */
export const RUN_TIMEOUT_MS = 15 * 60_000;

/** `timeoutMs`: give up (and say so) when the engine has not answered by then. */
async function call<T>(path: string, init?: RequestInit, timeoutMs?: number): Promise<T> {
  const ctrl = timeoutMs ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : undefined;
  try {
    const res = await fetch(`${API_ORIGIN}${path}`, {
      ...init,
      signal: ctrl?.signal ?? init?.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (res.status === 422) {
      const body = await res.json();
      throw new SchemaRejected((body.detail ?? []) as SchemaError[]);
    }
    if (!res.ok) {
      let detail = "";
      try {
        detail = ((await res.json()) as { detail?: string }).detail ?? "";
      } catch {
        /* not JSON */
      }
      throw new Error(detail || `${path}: HTTP ${res.status}`);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (ctrl?.signal.aborted) {
      throw new Error(`no answer after ${Math.round(timeoutMs! / 60_000)} minutes: the engine may be overloaded or restarting`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

const post = <T>(path: string, ds: Dataset) => call<T>(path, { method: "POST", body: JSON.stringify(ds) });

/** What the engine plans: the dataset without the unfinished records the data check set aside, and a way to put
 *  them back into a dataset the engine returns (a released forecast, committed promises, …), so an engine write
 *  never loses a record the planner is still filling in. The store installs this. */
export interface PlanningView { clean: Dataset; restore: (next: Dataset) => Dataset }
let planningViewOf: (ds: Dataset) => PlanningView = (ds) => ({ clean: ds, restore: (x) => x });
export function setPlanningView(fn: (ds: Dataset) => PlanningView) { planningViewOf = fn; }
const clean = (ds: Dataset) => planningViewOf(ds).clean;
const planPost = <T>(path: string, ds: Dataset) => post<T>(path, clean(ds));
/** POST `{ dataset, ...extra }` and put the set-aside records back into the dataset that comes back. */
async function write<T extends { dataset: Dataset }>(path: string, dataset: Dataset, extra: Record<string, unknown> = {}): Promise<T> {
  const v = planningViewOf(dataset);
  const out = await call<T>(path, { method: "POST", body: JSON.stringify({ dataset: v.clean, ...extra }) });
  return { ...out, dataset: v.restore(out.dataset) };
}
const withDataset = <T>(path: string, dataset: Dataset, extra: Record<string, unknown> = {}) =>
  call<T>(path, { method: "POST", body: JSON.stringify({ dataset: clean(dataset), ...extra }) });

export const api = {
  examples: () => call<ExampleInfo[]>("/api/examples"),
  example: (name: string) => call<Dataset>(`/api/examples/${encodeURIComponent(name)}`),
  schema: () => call<JsonSchema>("/api/schema"),
  rules: () => call<RuleInfo[]>("/api/rules"),
  validate: (ds: Dataset) => post<ValidationResult>("/api/validate", ds),
  network: (ds: Dataset) => post<NetworkView>("/api/network", ds),
  plan: (ds: Dataset) => planPost<PlanResult>("/api/plan", ds),
  sop: (ds: Dataset) => planPost<SopResult>("/api/sop", ds),
  sopRelease: async (ds: Dataset) => {
    const v = planningViewOf(ds);
    const out = await post<SopReleaseResponse>("/api/sop/release", v.clean);
    return { ...out, dataset: v.restore(out.dataset) };
  },
  inventory: (ds: Dataset) => planPost<InventoryResult>("/api/inventory", ds),
  /** Write the multi-echelon recommendation as fixed policies; keys "location|product", null = every stage that differs. */
  applyPlacement: (dataset: Dataset, keys: string[] | null) =>
    write<PlacementResponse>("/api/inventory/apply", dataset, { keys }),
  promise: (ds: Dataset) => planPost<PromiseResult>("/api/promise", ds),
  bop: (ds: Dataset) => planPost<PromiseResult>("/api/promise/bop", ds),
  promiseCheck: (dataset: Dataset, order: DemandRecord) =>
    withDataset<PromiseResult>("/api/promise/check", dataset, { order }),
  promiseCommit: (dataset: Dataset, mode: "entry" | "bop") =>
    write<PromiseCommitResponse>("/api/promise/commit", dataset, { mode }),
  /** Detailed schedule; `sequence` (resource → operation keys) fixes the order on those resources. */
  schedule: (dataset: Dataset, sequence?: Record<string, string[]>) =>
    withDataset<ScheduleResult>("/api/schedule", dataset, { sequence: sequence ?? null }),
  actuals: (dataset: Dataset, asOf?: string) =>
    withDataset<ActualsView>("/api/actuals", dataset, { as_of: asOf ?? null }),
  roll: (dataset: Dataset, asOf: string) =>
    write<RollResponse>("/api/actuals/roll", dataset, { as_of: asOf }),
  /** Firm planned orders into receipts: `ids`, or everything starting within the firm zone. */
  firm: (dataset: Dataset, ids?: string[], withinDays?: number) =>
    write<FirmResponse>("/api/orders/firm", dataset, { ids: ids ?? null, within_days: withinDays ?? null }),
  versions: () => call<VersionMeta[]>("/api/versions"),
  version: (id: string) => call<VersionDoc>(`/api/versions/${encodeURIComponent(id)}`),
  saveBase: (dataset: Dataset, name: string, note = "") =>
    call<VersionMeta>("/api/versions", { method: "POST", body: JSON.stringify({ dataset, name, note }) }),
  saveVersion: (id: string, dataset: Dataset) =>
    call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(dataset) }),
  branch: (id: string, name: string, note = "") =>
    call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}/branch`, { method: "POST", body: JSON.stringify({ name, note }) }),
  discard: (id: string) => call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}/discard`, { method: "POST" }),
  promote: (id: string, name?: string) =>
    call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}/promote`, { method: "POST", body: JSON.stringify({ name: name ?? null }) }),
  compareVersions: (a: string, b: string) => call<Comparison>(`/api/versions/${encodeURIComponent(a)}/compare/${encodeURIComponent(b)}`),
  compare: (a: Dataset, b: Dataset, labelA: string, labelB: string) =>
    call<Comparison>("/api/compare", { method: "POST", body: JSON.stringify({ a: clean(a), b: clean(b), label_a: labelA, label_b: labelB }) }),
  finance: (ds: Dataset) => planPost<FinanceResult>("/api/finance", ds),
  tower: (ds: Dataset) => planPost<TowerResult>("/api/tower", ds),
  /** Assign (owner "" = back to the rules), acknowledge / resolve / reopen, or annotate a worklist item. */
  towerItem: (id: string, patch: { owner?: string; status?: "open" | "acknowledged" | "resolved"; note?: string; sla_days?: Record<string, number> }) =>
    call<WorkItem>(`/api/tower/items/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify(patch) }),
  towerHistory: (id: string) => call<WorkItemEntry[]>(`/api/tower/items/${encodeURIComponent(id)}/history`),
  forecastModels: () => call<ForecastModels>("/api/forecast/models"),
  forecast: (ds: Dataset) => planPost<ForecastResult>("/api/forecast", ds),
  release: (dataset: Dataset, keys?: string[]) =>
    write<ReleaseResponse>("/api/forecast/release", dataset, { keys: keys ?? null }),
  /** Proof: end-to-end scenarios with hand-derived answers, run against an isolated in-memory store. */
  scenarios: () => call<ScenarioInfo[]>("/api/scenarios"),
  scenarioDataset: (id: string) => call<Dataset>(`/api/scenarios/${encodeURIComponent(id)}/dataset`),
  runScenario: (id: string) => call<ScenarioReport>(`/api/scenarios/${encodeURIComponent(id)}/run`, { method: "POST" }, RUN_TIMEOUT_MS),
};

// Minimal JSON-schema shape used by the form generator.
export interface JsonSchemaNode {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  $ref?: string;
  anyOf?: JsonSchemaNode[];
  items?: JsonSchemaNode;
  properties?: Record<string, JsonSchemaNode>;
  required?: string[];
  additionalProperties?: JsonSchemaNode | boolean;
  format?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  "x-unit"?: string;
  "x-ref"?: string;
}

export interface JsonSchema extends JsonSchemaNode {
  $defs: Record<string, JsonSchemaNode>;
}
