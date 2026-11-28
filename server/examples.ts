import fs from "node:fs";
import path from "node:path";
import type { CaseInfo, Dataset, ExampleInfo, ForecastModels, RuleInfo, ScenarioInfo, ScheduleCatalogue } from "./types.ts";

const EXAMPLES_DIR = path.resolve(process.cwd(), "scp", "examples");

const CASE_LABEL = "Example case (fictional, not real company data)";

export const CASES: Record<string, CaseInfo> = {
  chennai_port_pumps: {
    example: "chennai_port_pumps",
    company_name: "Example case: Coromandel Pumps, Chennai (fictional)",
    title: "DMSC case: a Chennai pump maker and the north-east monsoon",
    label: CASE_LABEL,
    brief:
      "Coromandel Pumps (invented for this case) assembles farm pumps and export pumps at Sriperumbudur. " +
      "Farm pumps go to Tamil Nadu dealers by truck; export pumps leave through the Chennai port yard for " +
      "Jebel Ali and Singapore, and the mechanical seals in every pump arrive from overseas through the " +
      "same port. In the north-east monsoon (October to December) heavy rain and swell slow the port: " +
      "here, six more days through the port yard and ten more on imported seals.",
    questions: [
      "How many points of on-time service does the monsoon cost, and which customers lose them?",
      "Does a third shift on the assembly line buy that service back? Why, or why not?",
      "What would you change before October: more seals in stock, an earlier export cut-off, a second seal supplier? Try it in the data and compare again.",
    ],
    scenarios: [
      { label: "Baseline", chips: [], dataset: null, version: null },
      {
        label: "Monsoon at the port",
        chips: [
          { kind: "lane_delay", days: 6, location: "PORT-MAA" },
          { kind: "lead_time", days: 10, supplier: "SUP-SEAL-IMPORT" },
        ],
        dataset: null,
        version: null,
      },
      {
        label: "Monsoon + third shift",
        chips: [
          { kind: "lane_delay", days: 6, location: "PORT-MAA" },
          { kind: "lead_time", days: 10, supplier: "SUP-SEAL-IMPORT" },
          { kind: "add_shift", resource: "ASM-LINE" },
        ],
        dataset: null,
        version: null,
      },
    ],
  },
};

export function listExamples(): ExampleInfo[] {
  if (!fs.existsSync(EXAMPLES_DIR)) return [];
  const files = fs
    .readdirSync(EXAMPLES_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort();
  return files.map((file) => {
    const name = file.replace(/\.json$/, "");
    const raw = JSON.parse(fs.readFileSync(path.join(EXAMPLES_DIR, file), "utf-8")) as Dataset;
    const c = CASES[name];
    return {
      name,
      title: raw.settings?.company_name || name,
      locations: raw.locations?.length ?? 0,
      products: raw.products?.length ?? 0,
      case: Boolean(c),
      label: c?.label ?? "",
      brief: c?.brief ?? "",
    };
  });
}

export function getExample(name: string): Dataset | null {
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) return null;
  const filePath = path.join(EXAMPLES_DIR, `${name}.json`);
  if (!fs.existsSync(filePath)) return null;
  const raw = JSON.parse(fs.readFileSync(filePath, "utf-8")) as Dataset;
  return normalizeDataset(raw);
}

/** Ensure optional collections exist as arrays so UI components never trip over undefined collections. */
export function normalizeDataset(raw: Partial<Dataset>): Dataset {
  const s = (raw.settings ?? {}) as Partial<Dataset["settings"]>;
  return {
    schema_version: raw.schema_version ?? "1",
    settings: {
      company_name: s.company_name ?? "My company",
      company_address: s.company_address ?? "",
      company_tax_id: s.company_tax_id ?? "",
      company_region: s.company_region ?? "",
      currency: s.currency ?? "INR",
      planning_start: s.planning_start ?? new Date().toISOString().slice(0, 10),
      horizon_days: s.horizon_days ?? 84,
      bucket: s.bucket ?? "week",
      week_start: s.week_start ?? 0,
      fx_rates: s.fx_rates ?? {},
      wacc: s.wacc ?? 0.12,
      holding_spread: s.holding_spread ?? 0.06,
      default_service_level: s.default_service_level ?? 0.95,
      default_calendar: s.default_calendar ?? "CAL-5D",
      capacity_constrained: s.capacity_constrained ?? false,
      capacity_direction: s.capacity_direction ?? "earlier",
      default_lot_policy: s.default_lot_policy ?? "POQ",
      default_lot_periods: s.default_lot_periods ?? 1,
      capacity_overtime: s.capacity_overtime ?? false,
      capacity_max_early_days: s.capacity_max_early_days ?? 14,
      working_day_fences: s.working_day_fences ?? false,
      rescheduling_horizon_days: s.rescheduling_horizon_days ?? 14,
      reschedule_out_tolerance_days: s.reschedule_out_tolerance_days ?? 3,
      ...s,
    } as Dataset["settings"],
    calendars: raw.calendars ?? [],
    locations: raw.locations ?? [],
    products: raw.products ?? [],
    location_products: raw.location_products ?? [],
    resources: raw.resources ?? [],
    production_sources: raw.production_sources ?? [],
    purchasing_sources: raw.purchasing_sources ?? [],
    lanes: raw.lanes ?? [],
    demand: raw.demand ?? [],
    receipts: raw.receipts ?? [],
    history: raw.history ?? [],
    events: raw.events ?? [],
    npi: raw.npi ?? [],
    overrides: raw.overrides ?? [],
    allocations: raw.allocations ?? [],
    confirmations: raw.confirmations ?? [],
    movements: raw.movements ?? [],
    closed_orders: raw.closed_orders ?? [],
    accuracy: raw.accuracy ?? [],
    purchase_orders: raw.purchase_orders ?? [],
    sales_orders: raw.sales_orders ?? [],
    quotations: raw.quotations ?? [],
    deliveries: raw.deliveries ?? [],
    invoices: raw.invoices ?? [],
    returns: raw.returns ?? [],
    supplier_invoices: raw.supplier_invoices ?? [],
    contracts: raw.contracts ?? [],
    supplier_returns: raw.supplier_returns ?? [],
    customer_prices: raw.customer_prices ?? [],
    batches: raw.batches ?? [],
    inventory_docs: raw.inventory_docs ?? [],
    changeovers: raw.changeovers ?? [],
    mrp_groups: raw.mrp_groups ?? [],
    bins: raw.bins ?? [],
    storage_types: raw.storage_types ?? [],
    putaway_rules: raw.putaway_rules ?? [],
    warehouse_tasks: raw.warehouse_tasks ?? [],
    waves: raw.waves ?? [],
    carriers: raw.carriers ?? [],
    freight_orders: raw.freight_orders ?? [],
    third_party_orders: raw.third_party_orders ?? [],
    challans: raw.challans ?? [],
    intercompany_invoices: raw.intercompany_invoices ?? [],
    transfer_prices: raw.transfer_prices ?? [],
    ...raw,
  } as Dataset;
}

export const RULES: RuleInfo[] = [
  { code: "NO_LOCATIONS", severity: "error", description: "Company has no locations defined" },
  { code: "NO_PRODUCTS", severity: "error", description: "Company has no products defined" },
  { code: "NO_DEMAND", severity: "warning", description: "No demand records in the planning horizon" },
  { code: "UNKNOWN_LOCATION", severity: "error", description: "Record references a location id that does not exist" },
  { code: "UNKNOWN_PRODUCT", severity: "error", description: "Record references a product id that does not exist" },
  { code: "MISSING_SOURCE", severity: "warning", description: "Demanded product has no production, purchasing, or lane source" },
  { code: "NETWORK_CYCLE", severity: "error", description: "Circular supply or BOM loop detected in the network" },
  { code: "MISSING_PRICE", severity: "info", description: "Finished product has no selling price set" },
  { code: "SET_ASIDE", severity: "warning", description: "An unfinished record is left out of planning until it is fixed" },
];

export const FORECAST_MODELS: ForecastModels = {
  models: [
    { id: "naive", label: "Naive (last value)", family: "baseline", description: "Repeats the last observed period." },
    { id: "seasonal_naive", label: "Seasonal naive", family: "baseline", description: "Repeats the same period from the previous seasonal cycle." },
    { id: "moving_average", label: "Moving average (4-period)", family: "smoothing", description: "Average of the most recent four periods." },
    { id: "ses", label: "Simple exponential smoothing", family: "smoothing", description: "Exponentially weighted moving average." },
    { id: "holt_damped", label: "Damped Holt trend", family: "smoothing", description: "Level and damped trend smoothing." },
    { id: "holt_winters", label: "Holt-Winters seasonal", family: "smoothing", description: "Level, trend, and seasonal components." },
    { id: "croston", label: "Croston (intermittent)", family: "intermittent", description: "Separates demand interval from non-zero size." },
  ],
  foundation: {
    enabled: false,
    available: false,
    model: "TimesFM",
    license: "Apache-2.0",
    detail: "Statistical models active in Node.js runtime",
  },
};

export const SCHEDULE_CATALOGUE: ScheduleCatalogue = {
  heuristics: [
    { id: "edd", name: "Earliest due date", what: "Run jobs in order of their plan due date.", good_for: "Protects delivery dates first.", sap: "EDD" },
    { id: "spt", name: "Shortest job first", what: "Run shorter jobs before longer ones.", good_for: "Reduces average wait and work in progress.", sap: "SPT" },
    { id: "slack", name: "Least slack", what: "Prioritise jobs with the least buffer before due date.", good_for: "Balances urgency and run duration.", sap: "CR/SLACK" },
    { id: "campaign", name: "Campaign by setup group", what: "Group similar products to reduce changeovers.", good_for: "Minimises changeover hours on bottleneck lines.", sap: "SETUP" },
  ],
  profiles: [
    {
      id: "balanced",
      name: "Balanced",
      what: "Weighs late delivery four times as heavily as changeover time.",
      settings: { heuristic: "edd", tardiness_weight: 4, setup_weight: 1, earliness_weight: 0.1, makespan_weight: 0.2 },
    },
    {
      id: "due_dates",
      name: "Protect due dates",
      what: "Minimises late orders even if extra changeovers are needed.",
      settings: { heuristic: "edd", tardiness_weight: 10, setup_weight: 0.5, earliness_weight: 0, makespan_weight: 0.1 },
    },
    {
      id: "fewest_changeovers",
      name: "Fewest changeovers",
      what: "Campaigns products together to keep lines running.",
      settings: { heuristic: "campaign", tardiness_weight: 1, setup_weight: 5, earliness_weight: 0, makespan_weight: 0.2 },
    },
  ],
};

export const SCENARIO_EXAMPLES: Record<string, string> = {
  "s1-coffee": "single_product_plant",
  "s2-network": "kitchenware_network",
  "s3-monsoon": "chennai_port_pumps",
};

export const SCENARIOS: ScenarioInfo[] = [
  {
    id: "s1-coffee",
    title: "S1 · Coffee roaster (single-plant MRP)",
    company: "Single-product bottler (fictional)",
    story: "Checks stock netting, fixed lot sizing, safety stock and BOM explosion.",
    proves: ["Netting against on-hand stock", "BOM explosion to raw materials", "Finance reconciliation"],
    stages: ["Validate", "Plan", "Finance"],
    found: [],
    generated: false,
  },
  {
    id: "s2-network",
    title: "S2 · Multi-echelon kitchenware network",
    company: "Kitchenware network (fictional)",
    story: "Checks DRP transfers across plants, DCs, stores, purchasing and finance reconciliation.",
    proves: ["Multi-echelon DRP transfers", "Supplier purchase requisitions", "Finance reconciliation"],
    stages: ["Validate", "Network", "Plan", "Finance"],
    found: [],
    generated: false,
  },
  {
    id: "s3-monsoon",
    title: "S3 · Chennai pump maker (disruption & what-if)",
    company: "Example case: Coromandel Pumps, Chennai (fictional)",
    story: "Checks port delay sensitivity, seal lead times, and assembly shift capacity.",
    proves: ["Port delay sensitivity", "Seal lead time impact", "Assembly capacity check"],
    stages: ["Validate", "Plan", "What-if"],
    found: [],
    generated: false,
  },
];

export function getJsonSchema(): Record<string, unknown> {
  return {
    title: "Dataset",
    type: "object",
    properties: {
      settings: {
        type: "object",
        title: "Settings",
        properties: {
          company_name: { type: "string", title: "Company name" },
          currency: { type: "string", title: "Currency", default: "INR" },
          planning_start: { type: "string", format: "date", title: "Planning start" },
          horizon_days: { type: "integer", title: "Horizon days", default: 84 },
          bucket: { type: "string", enum: ["day", "week", "month"], default: "week" },
          wacc: { type: "number", title: "WACC", default: 0.12 },
          holding_spread: { type: "number", title: "Holding spread", default: 0.06 },
        },
      },
      locations: { type: "array", items: { type: "object" } },
      products: { type: "array", items: { type: "object" } },
      location_products: { type: "array", items: { type: "object" } },
      resources: { type: "array", items: { type: "object" } },
      production_sources: { type: "array", items: { type: "object" } },
      purchasing_sources: { type: "array", items: { type: "object" } },
      lanes: { type: "array", items: { type: "object" } },
      demand: { type: "array", items: { type: "object" } },
      receipts: { type: "array", items: { type: "object" } },
    },
    $defs: {},
  };
}
