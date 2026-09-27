// The data check's rules in a planner's words. The engine's codes (validate/__init__.py RULES) stay stable ids for
// tests and filters; people read these instead.
export const CHECK_TITLE: Record<string, string> = {
  SET_ASIDE: "Unfinished, left out of the plan",
  DUP_ID: "The same id is used twice",
  DUP_LOCATION_PRODUCT: "Two planning policies for the same product and place",
  REF_UNKNOWN: "Points at something that doesn't exist",
  REF_WRONG_TYPE: "Points at the wrong kind of place",
  FX_MISSING: "A currency with no exchange rate",
  CALENDAR_NO_WORKDAY_IN_HORIZON: "A calendar with no working day in the plan",
  BOM_CYCLE: "Goes round in a circle (made from itself, or shipped in a loop)",
  NO_SOURCE: "Needed, but no way to get it",
  LANE_WEIGHT_MISSING: "Freight costed by weight, but the product has no weight",
  RESOURCE_WRONG_LOCATION: "Made on a machine at another plant",
  SS_NO_VARIABILITY: "Safety stock by service level, but nothing to size it from",
  SOURCE_NOT_VALID_IN_HORIZON: "A source that isn't valid for the whole plan",
  PRODUCTION_NO_OPERATIONS: "Made with no routing, so no machine time is planned",
  PRODUCTION_NO_LEAD_TIME: "Made instantly: no routing and no lead time",
  PURCHASE_ZERO_LEAD_TIME: "Bought with no lead time",
  SS_AND_SAFETY_TIME: "Safety stock and safety time both set",
  QUOTA_SUM: "Quotas don't add up to 100%",
  DEMAND_OUTSIDE_HORIZON: "Demand after the end of the plan, ignored",
  DEMAND_PAST_DUE: "Demand before the plan starts, treated as overdue",
  MTO_WITH_FORECAST: "A forecast on a make-to-order product, ignored",
  STOCK_AT_CUSTOMER: "Stock entered at a customer, not planned",
  RESOURCE_UNUSED: "A machine or crew no product uses",
  LOCATION_PRODUCT_DEFAULTED: "No planning policy, so defaults are used",
  SHELF_LIFE_VS_LEAD_TIME: "Takes longer to replenish than it keeps",
  HISTORY_AFTER_START: "Sales history on or after the plan start, not used",
  NPI_LIKE_WITHOUT_HISTORY: "A new product modelled on one with no history",
  NPI_DUPLICATE: "Two new-product rules for the same product and place",
  OVERRIDE_OUTSIDE_HORIZON: "A forecast override outside the forecast, ignored",
  OVERRIDE_WITHOUT_FORECAST: "A forecast override where there is no forecast",
  CONFIRMATION_ORPHAN: "A promise for an order that no longer exists",
  STOCK_NOT_SYNCED: "Stock on hand differs from the stock journal",
  NEGATIVE_STOCK: "The stock journal goes below zero",
  MOVEMENT_REF_UNKNOWN: "A goods movement for an unknown order",
  PHANTOM_NOT_MADE: "A phantom assembly that isn't made there",
};

export const checkTitle = (code: string) => CHECK_TITLE[code] ?? code.toLowerCase().replace(/_/g, " ");

/** What an issue is about, in words: "lane LN-1", "planning policy for FLT at DC". */
export const OBJECT_WORD: Record<string, string> = {
  location_product: "planning policy", production_source: "production source", purchasing_source: "purchasing source",
  lane: "lane", demand: "demand", receipt: "scheduled receipt", history: "sales history", event: "event", npi: "new-product rule",
  override: "forecast override", allocation: "allocation", confirmation: "confirmation", changeover: "changeover",
  movement: "goods movement", resource: "resource", location: "location", product: "product", calendar: "calendar",
  settings: "company settings", network: "network", closed_order: "closed order", bop_segment: "order-priority segment",
};

export function objectWords(type: string, id: string, name?: { loc: (id: string) => string; prod: (id: string) => string }): string {
  const w = OBJECT_WORD[type] ?? type.replace(/_/g, " ");
  if (type === "settings" || type === "network") return w;
  if (id.startsWith("#")) return `${w}, row ${Number(id.slice(1)) + 1}`;
  if ((type === "location_product" || type === "npi") && id.includes("/")) {
    const [l, p] = id.split("/");
    return `${w === "planning policy" ? "stock and ordering rules" : w} for ${name ? name.prod(p) : p} at ${name ? name.loc(l) : l}`;
  }
  if (type === "location" && name) return `${w} ${name.loc(id)}`;
  if (type === "product" && name) return `${w} ${name.prod(id)}`;
  return `${w} ${id}`;
}
