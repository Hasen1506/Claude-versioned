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
export type SalesHistory = S["SalesHistory"];
export type DemandEvent = S["DemandEvent"];
export type NpiRule = S["NpiRule"];
export type ForecastOverride = S["ForecastOverride"];
export type ForecastSettings = S["ForecastSettings"];

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

export type ForecastResult = S["ForecastResult"];
export type ForecastSeries = S["Series"];
export type ForecastPoint = S["ForecastPoint"];
export type HistoryPoint = S["HistoryPoint"];
export type ModelScore = S["ModelScore"];
export type ForecastModels = S["ForecastModels"];
export type ReleaseResponse = S["ReleaseResponse"];

export type InventoryResult = S["InventoryResult"];
export type NodeInventory = S["NodeInventory"];
export type DdmrpRow = S["DdmrpRow"];
export type PoolingRow = S["PoolingRow"];

export type SopResult = S["SopResult"];
export type SopReleaseResponse = S["SopReleaseResponse"];
export type SopDemandLine = S["DemandLine"];
export type SopResourceLine = S["ResourceLine"];
export type SopBinding = S["Binding"];

export type ScheduleResult = S["ScheduleResult"];
export type ScheduledOp = S["ScheduledOp"];
export type ScheduledOrder = S["ScheduledOrder"];
export type ScheduleResource = S["ScheduleResource"];
export type ScheduleKpis = S["ScheduleKpis"];
export type LabourDay = S["LabourDay"];
export type Changeover = S["Changeover"];

export type PromiseResult = S["PromiseResult"];
export type OrderPromise = S["OrderPromise"];
export type AtpNode = S["AtpNode"];
export type ScheduleLine = S["ScheduleLine"];
export type CtpStep = S["CtpStep"];
export type BopRow = S["BopRow"];
export type PromiseCommitResponse = S["PromiseCommitResponse"];

export type ActualsView = S["ActualsView"];
export type StockRow = S["StockRow"];
export type OpenOrderRow = S["OpenOrderRow"];
export type AccuracyReport = S["AccuracyReport"];
export type AccuracySeries = S["AccuracySeries"];
export type RollReport = S["RollReport"];
export type RollResponse = S["RollResponse"];
export type FirmResponse = S["FirmResponse"];
export type GoodsMovement = S["GoodsMovement"];
export type ClosedOrder = S["ClosedOrder"];

export type FinanceResult = S["FinanceResult"];
export type ServeRow = S["ServeRow"];
export type CostLine = S["CostLine"];
export type InventoryValue = S["InventoryValue"];
export type CapacityAppraisal = S["CapacityAppraisal"];

export type VersionMeta = S["VersionMeta"];
export type VersionDoc = S["VersionDoc"];
export type Comparison = S["Comparison"];
export type DatasetDiff = S["DatasetDiff"];
export type PlanSummary = S["PlanSummary"];
