// Registry of master/transactional data collections: how each is listed, keyed and cross-
// referenced. Adding an object type to the engine means adding one entry here.
import type { Dataset } from "../api/types";

type Obj = Record<string, unknown>;

export type CollectionKey =
  | "locations" | "products" | "location_products" | "resources" | "production_sources"
  | "purchasing_sources" | "lanes" | "calendars" | "changeovers" | "allocations" | "confirmations" | "demand" | "receipts" | "history" | "events" | "npi" | "overrides"
  | "movements" | "closed_orders" | "accuracy" | "rolled_weeks" | "vendors" | "purchase_orders" | "customer_prices" | "batches" | "mrp_groups"
  | "customers" | "payment_terms" | "sales_orders" | "quotations" | "deliveries" | "invoices" | "returns"
  | "contracts" | "supplier_invoices" | "supplier_returns";

export interface Column {
  label: string;
  get: (o: Obj, ds: Dataset) => string | number | null | undefined;
  num?: boolean;
}

export interface CollectionDef {
  key: CollectionKey;
  label: string;
  singular: string;
  defName: string;
  /** readiness-gate object_type */
  issueType: string;
  keyOf: (o: Obj, index: number) => string;
  columns: Column[];
  group: "Network" | "Make & buy" | "Planning data" | "Demand inputs" | "Execution";
  blurb: string;
}

const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const lanesModes = (o: Obj) => ((o.modes as Obj[]) ?? []).map((m) => `${m.mode} ${m.transit_days}d`).join(", ");

export const COLLECTIONS: CollectionDef[] = [
  {
    key: "locations", label: "Locations", singular: "location", defName: "Location", issueType: "location",
    group: "Network", keyOf: (o) => s(o.id),
    blurb: "Plants, distribution centres, warehouses, stores, suppliers and customers — the nodes of your network.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Type", get: (o) => s(o.type) }, { label: "Region", get: (o) => s(o.region) },
      { label: "Calendar", get: (o) => s(o.calendar) },
    ],
  },
  {
    key: "lanes", label: "Transport lanes", singular: "lane", defName: "TransportLane", issueType: "lane",
    group: "Network", keyOf: (o) => s(o.id),
    blurb: "How goods move between two locations: modes, transit times, costs and capacities.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "From", get: (o) => s(o.origin) },
      { label: "To", get: (o) => s(o.destination) },
      { label: "Products", get: (o) => ((o.products as string[] | null)?.length ? (o.products as string[]).join(", ") : "all") },
      { label: "Modes", get: (o) => lanesModes(o) },
    ],
  },
  {
    key: "calendars", label: "Calendars", singular: "calendar", defName: "Calendar", issueType: "calendar",
    group: "Network", keyOf: (o) => s(o.id),
    blurb: "Working weekdays and holidays. Production lead times and capacity count working days only.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Workdays", get: (o) => ((o.workdays as number[]) ?? []).map((d) => "MTWTFSS"[d]).join("") },
      { label: "Holidays", get: (o) => ((o.holidays as string[]) ?? []).length, num: true },
    ],
  },
  {
    key: "products", label: "Products", singular: "product", defName: "Product", issueType: "product",
    group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "Finished goods, sub-assemblies, raw materials and packaging, with base UoM, weight, volume and shelf life.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Type", get: (o) => s(o.type) }, { label: "UoM", get: (o) => s(o.base_uom ?? "EA") },
      { label: "kg", get: (o) => o.weight_kg as number, num: true },
    ],
  },
  {
    key: "resources", label: "Resources", singular: "resource", defName: "Resource", issueType: "resource",
    group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "Machines, lines, labour pools and tools with shifts, efficiency (OEE) and overtime.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Plant", get: (o) => s(o.location) },
      { label: "Kind", get: (o) => s(o.kind) }, { label: "Units", get: (o) => o.units as number, num: true },
      { label: "h/day", num: true, get: (o) => {
        const u = (o.units as number) ?? 1, sh = (o.shifts_per_day as number) ?? 1, h = (o.hours_per_shift as number) ?? 8,
          e = (o.efficiency as number) ?? 0.85;
        return +(u * sh * h * e).toFixed(1);
      } },
    ],
  },  {
    key: "changeovers", label: "Changeovers", singular: "changeover", defName: "Changeover", issueType: "changeover",
    group: "Make & buy", keyOf: (_o, i) => `#${i}`,
    blurb: "The setup matrix: hours to switch a resource from one setup group to another. Without an entry a switch costs the operation's full setup.",
    columns: [
      { label: "Resource", get: (o) => s(o.resource) || "all" }, { label: "From", get: (o) => s(o.from_group) },
      { label: "To", get: (o) => s(o.to_group) }, { label: "Hours", get: (o) => o.hours as number, num: true },
    ],
  },

  {
    key: "production_sources", label: "Production sources", singular: "production source",
    defName: "ProductionSource", issueType: "production_source", group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "How a product is made at a plant: bill of material (components, scrap) and routing (operations on resources).",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Plant", get: (o) => s(o.location) },
      { label: "Output", get: (o) => s(o.product) },
      { label: "Components", get: (o) => ((o.components as Obj[]) ?? []).length, num: true },
      { label: "Operations", get: (o) => ((o.operations as Obj[]) ?? []).length, num: true },
    ],
  },
  {
    key: "purchasing_sources", label: "Purchasing sources", singular: "purchasing source",
    defName: "PurchasingSource", issueType: "purchasing_source", group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "Who sells you a product: price, currency, duty, MOQ, lead time and capacity.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Supplier", get: (o) => s(o.supplier) },
      { label: "Product", get: (o) => s(o.product) }, { label: "To", get: (o) => s(o.location) },
      { label: "Price", get: (o) => `${o.price} ${s(o.currency) || ""}`.trim() },
      { label: "LT d", get: (o) => o.lead_time_days as number, num: true },
    ],
  },
  {
    key: "vendors", label: "Supplier purchasing data", singular: "supplier record", defName: "Vendor", issueType: "vendor",
    group: "Make & buy", keyOf: (o) => s(o.supplier),
    blurb: "How you buy from each supplier: contact, payment terms, whether they confirm orders, delivery tolerances and a purchasing block. A supplier without a record buys on the defaults.",
    columns: [
      { label: "Supplier", get: (o) => s(o.supplier) }, { label: "Contact", get: (o) => s(o.contact) },
      { label: "Pay days", get: (o) => o.payment_terms_days as number, num: true },
      { label: "Confirms", get: (o) => (o.confirmation_required ? "yes" : "") },
      { label: "Blocked", get: (o) => (o.blocked ? `yes${o.block_reason ? `: ${s(o.block_reason)}` : ""}` : "") },
    ],
  },
  {
    key: "location_products", label: "Planning policies", singular: "planning policy", defName: "LocationProduct",
    issueType: "location_product", group: "Planning data", keyOf: (o) => `${s(o.location)}|${s(o.product)}`,
    blurb: "How each product is planned at each location: strategy, stock, lot sizing, safety stock, fences.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Strategy", get: (o) => s(o.strategy ?? "MTS_CONSUME") },
      { label: "Lot", get: (o) => s((o.lot_sizing as Obj | undefined)?.policy ?? "company default") },
      { label: "Safety stock", get: (o) => s((o.safety_stock as Obj | undefined)?.method ?? "none") },
      { label: "On hand", get: (o) => (o.on_hand as number) ?? 0, num: true },
    ],
  },
  {
    key: "mrp_groups", label: "MRP groups", singular: "MRP group", defName: "MrpGroup", issueType: "mrp_group",
    group: "Planning data", keyOf: (o) => s(o.id),
    blurb: "Planning values shared by many products: a planning policy that names the group is planned with the group's strategy, lot size, safety time, fence and consumption windows wherever the group sets one.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Strategy", get: (o) => s(o.strategy ?? "each product's own") },
      { label: "Lot", get: (o) => s((o.lot_sizing as Obj | undefined)?.policy ?? "each product's own") },
      { label: "Products", get: (o, ds) => (ds.location_products ?? []).filter((lp) => lp.mrp_group === o.id).length, num: true },
    ],
  },
  {
    key: "demand", label: "Demand", singular: "demand record", defName: "DemandRecord", issueType: "demand",
    group: "Planning data", keyOf: (o, i) => s(o.id) || `#${i}`,
    blurb: "Forecasts (optionally spread over a period's working days) and firm sales orders.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Location", get: (o) => s(o.location) },
      { label: "Product", get: (o) => s(o.product) }, { label: "Date", get: (o) => s(o.date) },
      { label: "Kind", get: (o) => s(o.kind ?? "forecast") }, { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "receipts", label: "Scheduled receipts", singular: "scheduled receipt", defName: "ScheduledReceipt",
    issueType: "receipt", group: "Planning data", keyOf: (o) => s(o.id),
    blurb: "Firm supply already in the pipeline: open POs, released production orders, stock in transit.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Kind", get: (o) => s(o.kind) },
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Due", get: (o) => s(o.due_date) }, { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "purchase_orders", label: "Purchase orders", singular: "purchase order", defName: "PurchaseOrder",
    issueType: "purchase_order", group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Purchase order headers: supplier, receiving place, order date, approval and when it was sent. The lines are the scheduled receipts that name the order (Buying manages both).",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Supplier", get: (o) => s(o.supplier) },
      { label: "To", get: (o) => s(o.location) }, { label: "Ordered", get: (o) => s(o.order_date) },
      { label: "Sent", get: (o) => s(o.sent_on) }, { label: "Approved", get: (o) => (o.approved === false ? "no" : "yes") },
    ],
  },
  {
    key: "sales_orders", label: "Sales orders", singular: "sales order", defName: "SalesOrder",
    issueType: "sales_order", group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Sales order headers: customer, order date, the customer's number, payment terms and a credit block. The lines are the sales-order demand that names the order (Selling manages both).",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Customer", get: (o) => s(o.customer) },
      { label: "Ordered", get: (o) => s(o.order_date) }, { label: "Their number", get: (o) => s(o.customer_ref) },
      { label: "Credit block", get: (o) => (o.credit_block ? "yes" : "") },
    ],
  },
  {
    key: "quotations", label: "Quotations", singular: "quotation", defName: "Quotation", issueType: "quotation",
    group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Offers to customers with their prices and how long they hold. A quotation promises nothing until it is won and becomes an order.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Customer", get: (o) => s(o.customer) },
      { label: "Valid to", get: (o) => s(o.valid_to) }, { label: "Status", get: (o) => s(o.status) },
      { label: "Lines", get: (o) => ((o.lines as Obj[]) ?? []).length, num: true },
    ],
  },
  {
    key: "deliveries", label: "Deliveries", singular: "delivery", defName: "Delivery", issueType: "delivery",
    group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Outbound deliveries: what is picked, packed and shipped to a customer, and who signed for it.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Customer", get: (o) => s(o.customer) },
      { label: "From", get: (o) => s(o.ship_from) }, { label: "Shipped", get: (o) => s(o.issued_on) },
      { label: "Delivered", get: (o) => s(o.pod_on) },
    ],
  },
  {
    key: "invoices", label: "Invoices", singular: "invoice", defName: "Invoice", issueType: "invoice",
    group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Invoices and credit notes to customers, with their payment terms and the payments received.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Kind", get: (o) => (o.kind === "credit_note" ? "credit note" : "invoice") },
      { label: "Customer", get: (o) => s(o.customer) }, { label: "Date", get: (o) => s(o.date) },
      { label: "Due", get: (o) => s(o.due_date) },
    ],
  },
  {
    key: "returns", label: "Customer returns", singular: "return", defName: "ReturnOrder", issueType: "return",
    group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Goods a customer sends back: agreed, received into stock, and credited.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Customer", get: (o) => s(o.customer) },
      { label: "Product", get: (o) => s(o.product) }, { label: "Qty", get: (o) => o.qty as number, num: true },
      { label: "Received", get: (o) => s(o.received_on) }, { label: "Credit note", get: (o) => s(o.credit_note) },
    ],
  },
  {
    key: "contracts", label: "Contracts", singular: "contract", defName: "PurchaseContract", issueType: "contract",
    group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "Prices agreed with a supplier for a period, per product, with the quantity or value agreed. Purchase orders made while a contract is valid take its price and count against it.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Supplier", get: (o) => s(o.supplier) },
      { label: "From", get: (o) => s(o.valid_from) }, { label: "To", get: (o) => s(o.valid_to) },
      { label: "Products", get: (o) => ((o.lines as Obj[]) ?? []).length, num: true },
    ],
  },
  {
    key: "supplier_invoices", label: "Supplier invoices", singular: "supplier invoice", defName: "SupplierInvoice",
    issueType: "supplier_invoice", group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Suppliers' invoices and credit memos, checked against the order and the goods received, with the payments made (Buying manages them).",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Kind", get: (o) => (s(o.kind) || "invoice").replace(/_/g, " ") },
      { label: "Supplier", get: (o) => s(o.supplier) }, { label: "Their number", get: (o) => s(o.reference) },
      { label: "Date", get: (o) => s(o.date) }, { label: "Due", get: (o) => s(o.due_date) },
    ],
  },
  {
    key: "supplier_returns", label: "Returns to suppliers", singular: "return to a supplier", defName: "SupplierReturn",
    issueType: "supplier_return", group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Goods sent back to a supplier against the order line they came on, to be replaced or credited.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Supplier", get: (o) => s(o.supplier) },
      { label: "Order line", get: (o) => s(o.order) }, { label: "Qty", get: (o) => o.qty as number, num: true },
      { label: "Date", get: (o) => s(o.date) }, { label: "Credit memo", get: (o) => s(o.credit_memo) },
    ],
  },
  {
    key: "customers", label: "Customer sales data", singular: "customer record", defName: "Customer", issueType: "customer",
    group: "Demand inputs", keyOf: (o) => s(o.customer),
    blurb: "How you sell to each customer: contact, payment terms, a credit limit, a discount on everything they buy, the tax on their invoices and a sales block. A customer without a record buys on the defaults.",
    columns: [
      { label: "Customer", get: (o) => s(o.customer) }, { label: "Terms", get: (o) => s(o.payment_terms) },
      { label: "Credit limit", get: (o) => (o.credit_limit as number | null) ?? "", num: true },
      { label: "Discount", get: (o) => (o.discount ? `${Math.round((o.discount as number) * 1000) / 10} %` : "") },
      { label: "Blocked", get: (o) => (o.blocked ? `yes${o.block_reason ? `: ${s(o.block_reason)}` : ""}` : "") },
    ],
  },
  {
    key: "payment_terms", label: "Payment terms", singular: "payment terms", defName: "PaymentTerms",
    issueType: "payment_terms", group: "Demand inputs", keyOf: (o) => s(o.id),
    blurb: "When an invoice is due, and the cash discount for paying early (e.g. 2 % within 10 days, net 30).",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Net days", get: (o) => o.net_days as number, num: true },
      { label: "Discount", get: (o) => (o.discount ? `${Math.round((o.discount as number) * 1000) / 10} % in ${o.discount_days} d` : "") },
    ],
  },
  {
    key: "customer_prices", label: "Customer prices", singular: "customer price", defName: "CustomerPrice",
    issueType: "customer_price", group: "Demand inputs", keyOf: (o) => `${s(o.customer)}/${s(o.product)}`,
    blurb: "What a customer pays for a product, where it differs from the product's selling price. An order's own price wins over both; without any price, sales show no revenue or margin.",
    columns: [
      { label: "Customer", get: (o) => s(o.customer) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Price", get: (o) => o.price as number, num: true },
    ],
  },
  {
    key: "allocations", label: "Allocations", singular: "allocation", defName: "Allocation", issueType: "allocation",
    group: "Planning data", keyOf: (o) => s(o.id),
    blurb: "Product allocation: the most that may be promised to a product (and customers) in a period, whatever the stock.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Customers", get: (o) => ((o.customers as string[]) ?? []).join(", ") || "all" },
      { label: "From", get: (o) => s(o.start) }, { label: "To", get: (o) => s(o.end) },
      { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "confirmations", label: "Confirmations", singular: "confirmation", defName: "Confirmation", issueType: "confirmation",
    group: "Planning data", keyOf: (_o, i) => `#${i}`,
    blurb: "Committed promises (schedule lines) per sales order. Written by Promising → Commit; they claim supply in every later check.",
    columns: [
      { label: "Order", get: (o) => s(o.order) }, { label: "From", get: (o) => s(o.ship_from) },
      { label: "Ships", get: (o) => s(o.ship_date) }, { label: "Delivers", get: (o) => s(o.date) },
      { label: "Method", get: (o) => s(o.method ?? "atp") }, { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "history", label: "Sales history", singular: "history row", defName: "SalesHistory", issueType: "history",
    group: "Demand inputs", keyOf: (_o, i) => `#${i}`,
    blurb: "What actually sold, per location, product and date (long format). The forecast learns from it; promo rows are cleansed.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Date", get: (o) => s(o.date) }, { label: "Qty", get: (o) => o.qty as number, num: true },
      { label: "Promo", get: (o) => (o.promo ? "yes" : "") },
    ],
  },
  {
    key: "events", label: "Demand events", singular: "event", defName: "DemandEvent", issueType: "event",
    group: "Demand inputs", keyOf: (o) => s(o.id),
    blurb: "Promotions, price changes, launches, competitor moves. Past events are cleansed from history and their lift measured; future ones lift the forecast.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Kind", get: (o) => s(o.kind) },
      { label: "From", get: (o) => s(o.start) }, { label: "To", get: (o) => s(o.end) },
      { label: "Lift", get: (o) => (o.lift === null || o.lift === undefined ? "measured" : `${Math.round((o.lift as number) * 100)}%`) },
    ],
  },
  {
    key: "npi", label: "New products (NPI)", singular: "NPI rule", defName: "NpiRule", issueType: "npi",
    group: "Demand inputs", keyOf: (o) => `${s(o.location)}|${s(o.product)}`,
    blurb: "Forecast a product without history from a like product: scale, launch date, ramp-up and cannibalisation.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Like", get: (o) => s(o.like_product) }, { label: "Scale", get: (o) => `${Math.round(((o.scale as number) ?? 1) * 100)}%` },
      { label: "Launch", get: (o) => s(o.launch_date) },
    ],
  },
  {
    key: "overrides", label: "Consensus overrides", singular: "override", defName: "ForecastOverride", issueType: "override",
    group: "Demand inputs", keyOf: (_o, i) => `#${i}`,
    blurb: "Planner or sales adjustments to one forecast period: a final quantity or a percentage change, with a reason.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Period of", get: (o) => s(o.date) },
      { label: "Change", get: (o) => (o.qty !== null && o.qty !== undefined ? `= ${o.qty}` : `${Math.round(((o.change as number) ?? 0) * 100)}%`) },
      { label: "Reason", get: (o) => s(o.reason) },
    ],
  },
  {
    key: "movements", label: "Goods movements", singular: "goods movement", defName: "GoodsMovement", issueType: "movement",
    group: "Execution", keyOf: (o) => s(o.id),
    blurb: "The stock journal: openings, goods receipts, component issues, sales, transfer issues, scrap and count adjustments. On-hand is the sum of these.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Date", get: (o) => s(o.date) }, { label: "Type", get: (o) => s(o.type) },
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Reference", get: (o) => s(o.reference) }, { label: "Customer or supplier", get: (o) => s(o.counterparty) },
      { label: "Qty", get: (o) => o.qty as number, num: true }, { label: "Note", get: (o) => s(o.note) },
    ],
  },
  {
    key: "batches", label: "Batches", singular: "batch", defName: "Batch", issueType: "batch",
    group: "Execution", keyOf: (o) => `${s(o.product)}/${s(o.id)}`,
    blurb: "Batches of products kept by batch, with the day each expires. A receipt makes one; correct an expiry date here, and planning and the stock follow.",
    columns: [
      { label: "Product", get: (o) => s(o.product) }, { label: "Batch", get: (o) => s(o.id) }, { label: "Made", get: (o) => s(o.made_on) },
      { label: "Expires", get: (o) => s(o.expires_on) }, { label: "Supplier's batch", get: (o) => s(o.supplier_batch) },
    ],
  },
  {
    key: "closed_orders", label: "Closed orders", singular: "closed order", defName: "ClosedOrder", issueType: "closed_order",
    group: "Execution", keyOf: (o) => `${s(o.kind)}|${s(o.id)}`,
    blurb: "Orders the roll-forward completed, with due and delivery dates: the record OTIF and supplier reliability are measured on.",
    columns: [
      { label: "Kind", get: (o) => s(o.kind) }, { label: "Id", get: (o) => s(o.id) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Due", get: (o) => s(o.due_date) }, { label: "Delivered", get: (o) => s(o.last_delivery) },
      { label: "Ordered", get: (o) => o.ordered_qty as number, num: true }, { label: "Qty", get: (o) => o.delivered_qty as number, num: true },
    ],
  },
  {
    key: "accuracy", label: "Forecast accuracy log", singular: "accuracy record", defName: "AccuracyRecord", issueType: "accuracy",
    group: "Execution", keyOf: (_o, i) => `#${i}`,
    blurb: "Forecast against actual sales per series and elapsed week, logged by every roll-forward.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Week of", get: (o) => s(o.start) }, { label: "Forecast", get: (o) => o.forecast as number, num: true },
      { label: "Actual", get: (o) => o.actual as number, num: true },
    ],
  },
  {
    key: "rolled_weeks", label: "Rolled weeks", singular: "rolled week", defName: "RolledWeek", issueType: "rolled_week",
    group: "Execution", keyOf: (_o, i) => `#${i}`,
    blurb: "The weeks the roll-forward has closed. Each later roll re-reads their actuals from the journal, so a late posting still counts.",
    columns: [{ label: "From", get: (o) => s(o.start) }, { label: "To (exclusive)", get: (o) => s(o.end) }],
  },
];

export const byKey = Object.fromEntries(COLLECTIONS.map((c) => [c.key, c])) as Record<CollectionKey, CollectionDef>;
export const byIssueType = Object.fromEntries(COLLECTIONS.map((c) => [c.issueType, c])) as Record<string, CollectionDef>;

export function items(ds: Dataset, key: CollectionKey): Obj[] {
  return ((ds as unknown as Record<string, Obj[] | undefined>)[key] ?? []) as Obj[];
}

/** Where an id is referenced — so deleting or renaming never silently breaks the network. */
export function whereUsed(ds: Dataset, kind: "location" | "product" | "resource" | "calendar", id: string): string[] {
  const out: string[] = [];
  const add = (cond: boolean, what: string) => cond && out.push(what);
  if (kind === "location") {
    for (const r of ds.resources ?? []) add(r.location === id, `machine ${r.id}`);
    for (const p of ds.production_sources ?? []) add(p.location === id, `way to make ${p.id}`);
    for (const p of ds.purchasing_sources ?? []) add(p.supplier === id || p.location === id, `way to buy ${p.id}`);
    for (const v of ds.vendors ?? []) add(v.supplier === id, "its supplier purchasing data");
    for (const p of ds.purchase_orders ?? []) add(p.supplier === id || p.location === id, `purchase order ${p.id}`);
    for (const c of ds.customers ?? []) add(c.customer === id, "its customer sales data");
    for (const k of ds.contracts ?? []) add(k.supplier === id || k.location === id, `contract ${k.id}`);
    for (const i of ds.supplier_invoices ?? []) add(i.supplier === id, `supplier ${(i.kind ?? "invoice").replace(/_/g, " ")} ${i.id}`);
    for (const o of ds.sales_orders ?? []) add(o.customer === id, `sales order ${o.id}`);
    for (const i of ds.invoices ?? []) add(i.customer === id, `${i.kind === "credit_note" ? "credit note" : "invoice"} ${i.id}`);
    for (const l of ds.lanes ?? []) add(l.origin === id || l.destination === id, `route ${l.id}`);
    const lp = (ds.location_products ?? []).filter((x) => x.location === id).length;
    add(lp > 0, `${lp} planning polic${lp === 1 ? "y" : "ies"}`);
    const dm = (ds.demand ?? []).filter((x) => x.location === id).length;
    add(dm > 0, `${dm} order${dm === 1 ? "" : "s"} and forecast${dm === 1 ? "" : "s"}`);
    const hs = (ds.history ?? []).filter((x) => x.location === id).length;
    add(hs > 0, `${hs} week${hs === 1 ? "" : "s"} of sales history`);
    for (const n of ds.npi ?? []) add(n.location === id || n.like_location === id, `new-product rule ${n.product} at ${n.location}`);
    for (const e of ds.events ?? []) add(!!e.locations?.includes(id), `event ${e.id}`);
    const cp = (ds.customer_prices ?? []).filter((x) => x.customer === id).length;
    add(cp > 0, `${cp} customer price${cp === 1 ? "" : "s"}`);
  }
  if (kind === "product") {
    for (const p of ds.production_sources ?? []) {
      add(p.product === id, `made by ${p.id}`);
      add((p.components ?? []).some((c) => c.product === id), `a part in ${p.id}`);
    }
    for (const p of ds.purchasing_sources ?? []) add(p.product === id, `way to buy ${p.id}`);
    for (const l of ds.lanes ?? []) add(!!l.products?.includes(id), `route ${l.id}`);
    const lp = (ds.location_products ?? []).filter((x) => x.product === id).length;
    add(lp > 0, `${lp} planning polic${lp === 1 ? "y" : "ies"}`);
    const dm = (ds.demand ?? []).filter((x) => x.product === id).length;
    add(dm > 0, `${dm} order${dm === 1 ? "" : "s"} and forecast${dm === 1 ? "" : "s"}`);
    const hs = (ds.history ?? []).filter((x) => x.product === id).length;
    add(hs > 0, `${hs} week${hs === 1 ? "" : "s"} of sales history`);
    for (const n of ds.npi ?? []) add(n.product === id || n.like_product === id, `new-product rule ${n.product} at ${n.location}`);
    for (const e of ds.events ?? []) add(!!e.products?.includes(id), `event ${e.id}`);
    const cp = (ds.customer_prices ?? []).filter((x) => x.product === id).length;
    add(cp > 0, `${cp} customer price${cp === 1 ? "" : "s"}`);
  }
  if (kind === "resource") {
    for (const p of ds.production_sources ?? [])
      for (const op of p.operations ?? []) {
        add(op.resource === id, `step ${op.seq} of ${p.id} (machine)`);
        add(op.labor_resource === id, `step ${op.seq} of ${p.id} (labour)`);
      }
  }
  if (kind === "calendar") {
    add(ds.settings.default_calendar === id, "company settings (the default calendar)");
    for (const l of ds.locations ?? []) add(l.calendar === id, `place ${l.id}`);
    for (const r of ds.resources ?? []) add(r.calendar === id, `machine ${r.id}`);
  }
  return out;
}

export function issueRoute(objectType: string, objectId: string): string[] | null {
  if (objectType === "settings") return ["settings"];
  if (objectType === "network") return ["network"];
  const c = byIssueType[objectType];
  if (!c || objectId === "*") return c ? ["data", c.key] : null;
  if (c.key === "overrides") return ["data", c.key];
  const id = c.key === "location_products" || c.key === "npi" ? objectId.replace("/", "|") : objectId;
  return ["data", c.key, id];
}
