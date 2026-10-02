// Friendly aliases over the generated OpenAPI types (src/api/schema.d.ts — regenerate with
// `npm run gen:api` whenever the engine's models change; never edit it by hand).
import type { components } from "./schema";

type S = components["schemas"];

export type Dataset = S["Dataset"];
export type ProductionUsageInput = S["ProductionUsageInput"];
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

/** The supply plan as the browser gets it (Phase S): without the requirements and the pegging, two thirds of a large
 *  plan; `api.planTrace` gives an order's or a product's part of them when a page shows it. */
export type PlanResult = Omit<S["PlanResult"], "requirements" | "pegs">;
export type PlanTrace = S["PlanTrace"];
export type PlannedOrder = S["PlannedOrder"];
export type NodePlan = S["NodePlan"];
export type NodeBucket = S["NodeBucket"];
export type ResourcePlan = S["ResourcePlan"];
export type OrderLoad = S["OrderLoad"];
export type LevelPreview = S["LevelPreview"];
export type LevelMove = S["LevelMove"];
export type LevelResource = S["LevelResource"];
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
export type PlacementResponse = S["PlacementResponse"];
export type SopDemandLine = S["DemandLine"];
export type SopResourceLine = S["ResourceLine"];
export type SopBinding = S["Binding"];

export type ScheduleResult = S["ScheduleResult"];
export type ScheduledOp = S["ScheduledOp"];
export type ScheduledOrder = S["ScheduledOrder"];
export type ScheduleResource = S["ScheduleResource"];
export type ScheduleKpis = S["ScheduleKpis"];
export type PartSupply = S["PartSupply"];
export type ScheduleApplyResponse = S["ScheduleApplyResponse"];
export type ScheduleCatalogue = S["ScheduleCatalogue"];
export type ScheduleHeuristic = S["Heuristic"];
export type ScheduleProfile = S["Profile"];
export type ScheduleComparison = S["ScheduleComparison"];
export type CompareRow = S["CompareRow"];
export type OptimizerInfo = S["OptimizerInfo"];
export type AppliedOrder = S["AppliedOrder"];
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
export type YieldRow = S["YieldRow"];
export type OpenOrderRow = S["OpenOrderRow"];
export type AccuracyReport = S["AccuracyReport"];
export type AccuracySeries = S["AccuracySeries"];
export type RollReport = S["RollReport"];
export type RollResponse = S["RollResponse"];
export type FirmResponse = S["FirmResponse"];
export type GoodsMovement = S["GoodsMovement"];
export type Unbooked = S["Unbooked"];
export type PostAction = S["PostRequest"]["action"];
export type SalesOrderResponse = S["SalesOrderResponse"];
export type SalesOrderChange = S["SalesOrderChange"];
export type CustomerPrice = S["CustomerPrice"];
export type CountInput = S["CountInput"];
export type UsageInput = S["UsageInput"];
export type ClosedOrder = S["ClosedOrder"];
export type LotRow = S["LotRow"];
export type ShortOrder = S["ShortOrder"];
export type ActionReport = S["ActionReport"];
export type Batch = S["Batch"];
export type InventoryDoc = S["InventoryDoc"];
export type CountItem = S["CountItem"];
export type StockType = S["StockType"];
export type NegativeStock = S["NegativeStock"];

export type FinanceResult = S["FinanceResult"];
export type ServeRow = S["ServeRow"];
export type CostLine = S["CostLine"];
export type InventoryValue = S["InventoryValue"];
export type CapacityAppraisal = S["CapacityAppraisal"];

export type TowerResult = S["TowerResult"];
export type Kpi = S["Kpi"];
export type WorkItem = S["WorkItem"];
export type WorkItemEntry = S["WorkItemEntry"];
export type DataQualityRow = S["DataQualityRow"];

export type VersionMeta = S["VersionMeta"];
export type VersionDoc = S["VersionDoc"];
export type Comparison = S["Comparison"];
export type DatasetDiff = S["DatasetDiff"];
export type PlanSummary = S["PlanSummary"];

export type ScenarioInfo = S["ScenarioInfo"];
export type ScenarioReport = S["ScenarioReport"];
export type ScenarioStep = S["StepReport"];
export type ScenarioCheck = S["Check"];

export type PurchasingView = S["PurchasingView"];
export type Requisition = S["Requisition"];
export type SourceChoice = S["SourceChoice"];
export type PoView = S["PoView"];
export type PoLine = S["PoLine"];
export type VendorRow = S["VendorRow"];
export type InfoRecord = S["InfoRecord"];
export type CreateReport = S["CreateReport"];
export type CreatePoResponse = S["CreatePoResponse"];
export type PoActionResponse = S["PoActionResponse"];
export type PoAction = S["PoActionRequest"]["action"];
export type PoLineInput = S["PoLineInput"];
export type RequisitionPick = S["RequisitionPick"];

// Phase M: order to cash
export type SalesView = S["SalesView"];
export type OrderView = S["OrderView"];
export type OrderLineView = S["OrderLineView"];
export type QuotationView = S["QuotationView"];
export type DeliveryView = S["DeliveryView"];
export type InvoiceView = S["InvoiceView"];
export type ReturnView = S["ReturnView"];
export type ToDeliver = S["ToDeliver"];
export type ToBill = S["ToBill"];
export type CustomerRow = S["CustomerRow"];
export type SalesReport = S["SalesReport"];
export type SalesAction = S["SalesActionRequest"]["action"];
export type SalesLineInput = S["SalesLineInput"];
export type SalesActionResponse = S["SalesActionResponse"];
export type SalesActionInput = Omit<Partial<S["SalesActionRequest"]>, "dataset" | "action">;

// Phase I: sign-in and companies kept on the server
export type AuthConfig = S["AuthConfig"];
export type Session = S["Session"];
export type User = S["User"];
export type Me = S["Me"];
export type CompanyMeta = S["CompanyMeta"];
export type CompanyDoc = S["CompanyDoc"];
export type SaveReport = S["SaveReport"];
export type Member = S["Member"];
export type LogRow = S["LogRow"];
export type ListChange = S["ListChange"];
export type MergeResult = S["MergeResult"];
export type Clash = S["Clash"];
export type HeldChange = S["HeldChange"];
export type FieldChangeRow = S["FieldChangeRow"];
export type ResetLink = S["ResetLink"];
