// Friendly aliases over the generated OpenAPI types (src/api/schema.d.ts — regenerate with
// `npm run gen:api` whenever the engine's models change; never edit it by hand).
import type { components } from "./schema";

type S = components["schemas"];

export type Dataset = S["Dataset"];
export type Settings = S["Settings"];
export type Location = S["Location"];
export type Product = S["Product"];
export type LocationProduct = S["LocationProduct"];
export type Resource = S["Resource"];
export type ProductionSource = S["ProductionSource"];
export type PurchasingSource = S["PurchasingSource"];
export type TransportLane = S["TransportLane"];
export type DemandRecord = S["DemandRecord"];
export type ScheduledReceipt = S["ScheduledReceipt"];
export type Calendar = S["Calendar"];

export type Issue = S["Issue"];
export type ValidationResult = S["ValidationResult"];
export type RuleInfo = S["RuleInfo"];
export type ExampleInfo = S["ExampleInfo"];

export type NetworkView = S["NetworkView"];
export type NetLocation = S["NetLocation"];
export type NetEdge = S["NetEdge"];

export type PlanResult = S["PlanResult"];
export type PlannedOrder = S["PlannedOrder"];
export type NodePlan = S["NodePlan"];
export type NodeBucket = S["NodeBucket"];
export type ResourcePlan = S["ResourcePlan"];
export type PlanException = S["PlanException"];
export type Requirement = S["Requirement"];
export type Peg = S["Peg"];
export type Kpis = S["Kpis"];
export type BucketOut = S["BucketOut"];

/** FastAPI 422 body: pydantic errors with a location path into the posted dataset. */
export interface SchemaError {
  loc: (string | number)[];
  msg: string;
  type: string;
}
