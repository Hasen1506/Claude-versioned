import type {
  Dataset, ExampleInfo, ForecastModels, ForecastResult, InventoryResult, ScheduleResult, SopReleaseResponse, SopResult, NetworkView, PlanResult, ReleaseResponse, RuleInfo,
  SchemaError, ValidationResult,
} from "./types";

/** Thrown when the engine rejects the dataset shape (HTTP 422). Carries field-level errors. */
export class SchemaRejected extends Error {
  constructor(public errors: SchemaError[]) {
    super(`${errors.length} schema error(s)`);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
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
}

const post = <T>(path: string, ds: Dataset) => call<T>(path, { method: "POST", body: JSON.stringify(ds) });

export const api = {
  examples: () => call<ExampleInfo[]>("/api/examples"),
  example: (name: string) => call<Dataset>(`/api/examples/${encodeURIComponent(name)}`),
  schema: () => call<JsonSchema>("/api/schema"),
  rules: () => call<RuleInfo[]>("/api/rules"),
  validate: (ds: Dataset) => post<ValidationResult>("/api/validate", ds),
  network: (ds: Dataset) => post<NetworkView>("/api/network", ds),
  plan: (ds: Dataset) => post<PlanResult>("/api/plan", ds),
  sop: (ds: Dataset) => post<SopResult>("/api/sop", ds),
  sopRelease: (ds: Dataset) => post<SopReleaseResponse>("/api/sop/release", ds),
  inventory: (ds: Dataset) => post<InventoryResult>("/api/inventory", ds),
  /** Detailed schedule; `sequence` (resource → operation keys) fixes the order on those resources. */
  schedule: (dataset: Dataset, sequence?: Record<string, string[]>) =>
    call<ScheduleResult>("/api/schedule", { method: "POST", body: JSON.stringify({ dataset, sequence: sequence ?? null }) }),
  forecastModels: () => call<ForecastModels>("/api/forecast/models"),
  forecast: (ds: Dataset) => post<ForecastResult>("/api/forecast", ds),
  release: (dataset: Dataset, keys?: string[]) =>
    call<ReleaseResponse>("/api/forecast/release", { method: "POST", body: JSON.stringify({ dataset, keys: keys ?? null }) }),
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
